"""Hermes — Tool MCP `ha_search_related` (comando WS `search/related`).

Responde a «¿qué usa / qué depende de esto?»: dada una entidad, un
dispositivo, un área… devuelve las automatizaciones, escenas, scripts, áreas,
etc. relacionadas, agrupadas por tipo.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes.ha import HAClient, HAConnectionError
from hermes.ha_version import ha_at_least, ha_core_version
from hermes.tools._common import requires_ready, tam_json

logger = structlog.get_logger(__name__)

# Los tipos que acepta `search/related` en HA (`ItemType` de la integración
# `search`). Se validan aquí para dar un error útil sin gastar una llamada:
# HA respondería `invalid_format` sin decir cuáles son los válidos.
_ITEM_TYPES: tuple[str, ...] = (
    "area", "automation", "automation_blueprint", "config_entry", "device",
    "entity", "floor", "group", "integration", "label", "person", "scene",
    "script", "script_blueprint",
)

# Tope de ids por tipo. Un área grande o una integración con cientos de
# entidades devolverían miles de ids; los recuentos siguen siendo exactos.
_MAX_IDS_POR_TIPO = 200

# Topes por tipo que se prueban, de mayor a menor, hasta que la respuesta
# quepa en `response_max_bytes`: 200 ids de 14 tipos pueden pasar del tope
# (hallazgo M-1). Bajar el tope de todos por igual conserva un poco de cada
# tipo en vez de vaciar los últimos; los recuentos siguen siendo exactos.
_TOPES_POR_BYTES = (_MAX_IDS_POR_TIPO, 100, 50, 20, 10, 5, 1, 0)

# `include_disabled_entities` llegó en 2026.10; las versiones anteriores
# rechazan cualquier clave extra con `invalid_format`.
_MIN_INCLUDE_DISABLED = "2026.10.0"


def _version_no_soportada(current: str | None) -> str:
    return json.dumps({
        "error": "ha_version_unsupported",
        "feature": "include_disabled_entities",
        "required": _MIN_INCLUDE_DISABLED,
        "current": current,
    })


def register(
    mcp: object,
    ha_client: HAClient,
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
) -> None:
    """Registra la tool de búsqueda de relaciones."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_search_related(
        item_type: str,
        item_id: str,
        include_disabled_entities: bool = False,
    ) -> object:
        """Find what is related to an item (what uses it and what it uses).

        Read-only. Results are grouped by type (automation, scene, script,
        area, device, entity…) with counts; at most 200 ids per type, fewer
        if the response would exceed the size limit ("truncated": true when
        cut; counts are always exact).

        Args:
            item_type: One of area, automation, automation_blueprint,
                config_entry, device, entity, floor, group, integration,
                label, person, scene, script, script_blueprint.
            item_id: Id of the item (entity_id, device_id, area_id,
                config entry id, integration domain…).
            include_disabled_entities: Also include disabled entities.
                Requires Home Assistant 2026.10 or newer.

        Returns:
            JSON {"item_type", "item_id", "related": {type: [ids]},
            "counts": {type: n}, "truncated": bool}.
        """
        if item_type not in _ITEM_TYPES:
            return json.dumps({
                "error": "invalid_argument",
                "field": "item_type",
                "detail": "must be one of: " + ", ".join(_ITEM_TYPES),
            })
        if not isinstance(item_id, str) or not item_id.strip():
            return json.dumps({
                "error": "invalid_argument",
                "field": "item_id",
                "detail": "must be a non-empty string",
            })

        payload: dict[str, Any] = {
            "type": "search/related",
            "item_type": item_type,
            "item_id": item_id,
        }
        if include_disabled_entities:
            # La versión se pregunta en cada llamada (sin caché): HA puede
            # actualizarse sin reiniciar Hermes. `None` (desconocida) no
            # bloquea: se intenta y, si HA rechaza la clave, se traduce abajo.
            soportado = await ha_at_least(ha_client, _MIN_INCLUDE_DISABLED)
            if soportado is False:
                version = await ha_core_version(ha_client)
                return _version_no_soportada(
                    str(version) if version is not None else None
                )
            payload["include_disabled_entities"] = True
        # Con `false` la clave no se envía nunca: el resultado es el mismo y
        # así funciona en cualquier versión.

        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            if include_disabled_entities and exc.code == "invalid_format":
                return _version_no_soportada(None)
            logger.error(
                "ha_search_related_ws_error",
                item_type=item_type, error=str(exc),
            )
            return json.dumps({"error": str(exc)})

        if not isinstance(raw, dict):
            return json.dumps(
                {"error": "unexpected response from search/related"}
            )

        # HA devuelve listas (o conjuntos serializados como listas); lo que
        # no tenga esa forma se ignora en vez de devolverse en crudo.
        listas = {t: ids for t, ids in raw.items() if isinstance(ids, list)}
        counts = {t: len(ids) for t, ids in listas.items()}
        out: dict[str, Any] = {}
        for tope in _TOPES_POR_BYTES:
            out = {
                "item_type": item_type,
                "item_id": item_id,
                "related": {t: ids[:tope] for t, ids in listas.items()},
                "counts": counts,
                "truncated": any(n > tope for n in counts.values()),
            }
            if tam_json(out) <= response_max_bytes:
                break

        logger.info(
            "ha_search_related_ok", item_type=item_type, types=len(listas),
            truncated=out["truncated"],
        )
        return json.dumps(out, ensure_ascii=False)
