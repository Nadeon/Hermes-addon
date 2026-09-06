"""Hermes — Tool MCP ha_get_history.

Usa el comando WS `history/history_during_period` de HA (no existe endpoint
REST equivalente en versiones modernas de HA). El resultado llega en formato
comprimido {s, a, lu, lc} que este módulo expande a nombres legibles antes
de devolver al cliente MCP.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)

# Claves comprimidas que usa HA en history/history_during_period
_S = "s"    # state
_A = "a"    # attributes
_LU = "lu"  # last_updated (float timestamp)
_LC = "lc"  # last_changed (float timestamp, solo si difiere de lu)

# Máximo de estados por entidad antes de truncar
_MAX_STATES_PER_ENTITY = 500


def _expand_state(point: dict[str, Any]) -> dict[str, Any]:
    """Convierte un punto comprimido {s,a,lu,lc} a nombres legibles."""
    lu_ts: float | None = point.get(_LU)
    lc_ts: float | None = point.get(_LC)

    expanded: dict[str, Any] = {
        "state": point.get(_S),
        "last_updated": (
            datetime.fromtimestamp(lu_ts, tz=timezone.utc).isoformat()
            if lu_ts is not None else None
        ),
    }
    # last_changed solo aparece en el comprimido si difiere de last_updated
    expanded["last_changed"] = (
        datetime.fromtimestamp(lc_ts, tz=timezone.utc).isoformat()
        if lc_ts is not None
        else expanded["last_updated"]
    )
    attrs = point.get(_A)
    if attrs is not None:
        expanded["attributes"] = attrs
    return expanded


def _truncate_to_bytes(
    result: dict[str, list[dict[str, Any]]],
    max_bytes: int,
) -> tuple[dict[str, list[dict[str, Any]]], bool, str | None]:
    """Trunca el resultado para que quepa en max_bytes.

    Elimina estados del final (más nuevos) de cada entidad de forma equitativa
    hasta que la serialización cabe. Nunca corta a mitad de registro.

    Returns:
        (result_truncado, fue_truncado, truncated_at_iso)
        truncated_at_iso es el last_updated del último estado incluido.
    """
    # Comprobación rápida: ¿cabe sin truncar?
    serialized = json.dumps(result, ensure_ascii=False)
    if len(serialized.encode()) <= max_bytes:
        return result, False, None

    # Estrategia: quitar el punto más nuevo de la lista más larga hasta que
    # quepa, lo que iguala las longitudes de forma natural
    working = {eid: list(states) for eid, states in result.items()}
    while True:
        serialized = json.dumps(working, ensure_ascii=False)
        if len(serialized.encode()) <= max_bytes:
            break
        # Si todas las listas están vacías, no podemos reducir más
        total = sum(len(v) for v in working.values())
        if total == 0:
            break
        # Quitar el último estado de la entidad con más estados
        biggest = max(working, key=lambda k: len(working[k]))
        if not working[biggest]:
            break
        working[biggest].pop()

    # Encontrar el timestamp del último estado incluido
    last_ts: str | None = None
    for states in working.values():
        if states:
            ts = states[-1].get("last_updated")
            if ts and (last_ts is None or ts > last_ts):
                last_ts = ts

    return working, True, last_ts


def register(mcp: object, ha_client: HAClient, response_max_bytes: int = 1_048_576) -> None:
    """Registra ha_get_history."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_get_history(
        entity_ids: list[str],
        hours_back: float = 24.0,
        start_time: str | None = None,
        end_time: str | None = None,
        significant_changes_only: bool = True,
        no_attributes: bool = False,
    ) -> object:
        """Devuelve el historial de cambios de estado de una o varias entidades.

        Usa el comando WS history/history_during_period de HA (no REST).
        Los timestamps se devuelven en ISO 8601 UTC.

        Args:
            entity_ids: Lista de entity_ids a consultar (ej. ["light.salon",
                        "sensor.temperatura"]). Máximo recomendado: 10 entidades
                        por llamada para evitar respuestas muy grandes.
            hours_back: Horas hacia atrás desde ahora. Default 24h. Ignorado
                        si se proporciona start_time.
            start_time: Inicio del rango en ISO 8601 (ej. "2026-04-12T00:00:00Z").
                        Tiene preferencia sobre hours_back.
            end_time: Fin del rango en ISO 8601. Default: ahora.
            significant_changes_only: Si True (default), filtra cambios menores
                                       (p.ej. actualizaciones de atributos sin
                                       cambio de state). Reduce el volumen de datos.
            no_attributes: Si True, omite atributos para reducir tamaño de
                           respuesta. Útil para sensores con muchos atributos.

        Returns:
            JSON con {
              "history": {
                "<entity_id>": [
                  {
                    "state": "on",
                    "last_updated": "2026-04-12T10:00:00+00:00",
                    "last_changed": "2026-04-12T10:00:00+00:00",
                    "attributes": {...}   // ausente si no_attributes=True
                  },
...
                ]
              },
              "truncated": false,       // true si se cortó por tamaño
              "truncated_at": null      // ISO del último estado incluido si truncated
            }
        """
        from datetime import timedelta

        now_iso = datetime.now(tz=timezone.utc).isoformat()

        if start_time is None:
            start_dt = datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)
            start_iso = start_dt.isoformat()
        else:
            start_iso = start_time

        payload: dict[str, Any] = {
            "type": "history/history_during_period",
            "start_time": start_iso,
            "entity_ids": entity_ids,
            "significant_changes_only": significant_changes_only,
            "no_attributes": no_attributes,
            "include_start_time_state": True,
            "minimal_response": False,
        }
        if end_time is not None:
            payload["end_time"] = end_time

        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            logger.error("ha_get_history_ws_error", error=str(exc))
            return json.dumps({"error": str(exc)})

        if not isinstance(raw, dict):
            raw = {}

        # Descomprimir {s,a,lu,lc} → {state, attributes, last_updated, last_changed}
        # y truncar a _MAX_STATES_PER_ENTITY antes de la serialización global
        expanded: dict[str, list[dict[str, Any]]] = {}
        for entity_id, points in raw.items():
            if not isinstance(points, list):
                continue
            states = [_expand_state(p) for p in points if isinstance(p, dict)]
            # Truncar por entidad primero
            if len(states) > _MAX_STATES_PER_ENTITY:
                states = states[:_MAX_STATES_PER_ENTITY]
            expanded[entity_id] = states

        # Truncar por bytes (nunca a mitad de registro)
        final, truncated, truncated_at = _truncate_to_bytes(expanded, response_max_bytes)

        logger.info(
            "ha_get_history_ok",
            entity_count=len(final),
            truncated=truncated,
        )
        return json.dumps({
            "history": final,
            "truncated": truncated,
            "truncated_at": truncated_at,
        })
