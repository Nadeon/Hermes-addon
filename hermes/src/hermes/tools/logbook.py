"""Hermes — Tool MCP ha_get_logbook.

Usa el comando WS `logbook/get_events` de HA. Es single-shot: HA devuelve
todos los eventos en un único type:result, compatible con ws_send actual.

Nota: sensores con state_class (sensores continuos) son filtrados
automáticamente por HA y no aparecen en el logbook. Para datos de sensores
continuos usar ha_statistics_during_period.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

# Sin opción explícita, el mismo tope que la configuración (spec 003): el
# antiguo 1 MiB supera lo que el cliente acepta en una respuesta.
from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes.ha import HAClient, HAConnectionError
from hermes.tools._common import ajustar_lista_a_bytes, requires_ready

logger = structlog.get_logger(__name__)

# Máximo de eventos antes de truncar
_MAX_EVENTS = 2000


def _truncate_events_to_bytes(
    events: list[dict[str, Any]],
    max_bytes: int,
) -> tuple[list[dict[str, Any]], bool, float | None]:
    """Trunca la lista de eventos para que quepa en max_bytes.

    Elimina desde el final (eventos más recientes primero). Nunca corta
    a mitad de evento.

    Se mide la respuesta ENTERA (`count`, `truncated`, `truncated_at`), no
    solo la lista: con el envoltorio fuera de la cuenta la respuesta pasaba
    del tope, el guardián central quitaba unos eventos más y `count` y
    `truncated_at` seguían apuntando al último que había quitado, así que
    paginar desde `truncated_at` se saltaba eventos (revisión de 1.1.1, M-1).

    Returns:
        (events_truncados, fue_truncado, when_del_ultimo_incluido)
    """
    out = ajustar_lista_a_bytes(events, _envolver, max_bytes)
    return out["events"], out["truncated"], out["truncated_at"]


def _envolver(final: list[dict[str, Any]], truncated: bool) -> dict[str, Any]:
    """La respuesta completa de `ha_get_logbook`, tal como sale."""
    return {
        "events": final,
        "count": len(final),
        "truncated": truncated,
        "truncated_at": final[-1].get("when") if truncated and final else None,
    }


def register(mcp: object, ha_client: HAClient, response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT) -> None:
    """Registra ha_get_logbook."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_get_logbook(
        entity_ids: list[str] | None = None,
        hours_back: float = 24.0,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> object:
        """Devuelve el logbook de Home Assistant: eventos y cambios de estado legibles.

        El logbook muestra automations disparadas, scripts ejecutados, luces
        encendidas/apagadas, etc. en lenguaje natural. Los sensores continuos
        (con state_class, como sensores de temperatura o energía) son filtrados
        automáticamente por HA y no aparecen aquí — usar ha_statistics_during_period
        para ese tipo de datos.

        Args:
            entity_ids: Lista de entity_ids a filtrar (ej. ["light.salon",
                        "automation.mi_automatizacion"]). Si None devuelve todos.
                        Puede ser lento/grande sin filtro en instalaciones grandes.
            hours_back: Horas hacia atrás desde ahora. Default 24h. Ignorado
                        si se proporciona start_time.
            start_time: Inicio del rango en ISO 8601 UTC.
            end_time: Fin del rango en ISO 8601 UTC. Default: ahora.

        Returns:
            JSON con {
              "events": [
                {
                  "when": 1712345678.123,   // Unix timestamp float
                  "entity_id": "light.salon",
                  "name": "Salón",
                  "domain": "light",
                  "message": "turned on",
                  "state": "on",
...                        // campos opcionales: icon, source, context_id
                },
...
              ],
              "count": 42,
              "truncated": false,
              "truncated_at": null           // Unix timestamp del último incluido si truncated
            }
        """
        if start_time is None:
            start_dt = datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)
            start_iso = start_dt.isoformat()
        else:
            start_iso = start_time

        payload: dict[str, Any] = {
            "type": "logbook/get_events",
            "start_time": start_iso,
        }
        if end_time is not None:
            payload["end_time"] = end_time
        if entity_ids:
            payload["entity_ids"] = entity_ids

        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            logger.error("ha_get_logbook_ws_error", error=str(exc))
            return json.dumps({"error": str(exc)})

        events: list[dict[str, Any]] = raw if isinstance(raw, list) else []

        # Truncar por conteo primero
        if len(events) > _MAX_EVENTS:
            events = events[:_MAX_EVENTS]

        # Truncar por bytes (nunca a mitad de evento)
        final, truncated, _ = _truncate_events_to_bytes(events, response_max_bytes)

        logger.info(
            "ha_get_logbook_ok",
            count=len(final),
            truncated=truncated,
        )
        # `ensure_ascii=False`, como se mide: con `\uXXXX` un nombre con
        # tildes ocupaba más de lo medido.
        return json.dumps(_envolver(final, truncated), ensure_ascii=False)
