"""Hermes — Tools MCP para input_select de Home Assistant."""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.models.input_select import InputSelectConfig
from hermes.tools._common import (
    collection_delete_flow,
    collection_get_current,
    collection_update_flow,
    entity_exists,
    not_found_response,
    requires_ready,
)

logger = structlog.get_logger(__name__)

DOMAIN = "input_select"


def _entity_id_of(raw: str) -> str:
    return raw if raw.startswith(f"{DOMAIN}.") else f"{DOMAIN}.{raw}"


def _compact(state: dict[str, Any]) -> dict[str, Any]:
    attrs = state.get("attributes", {}) or {}
    return {
        "entity_id": state.get("entity_id"),
        "friendly_name": attrs.get("friendly_name") or state.get("entity_id"),
        "state": state.get("state"),
        "options": attrs.get("options"),
    }


def _dump_config(model: InputSelectConfig) -> dict[str, Any]:
    return model.model_dump(exclude_none=True, by_alias=True, mode="json")


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de input_select."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_list_input_selects() -> object:
        """Lista los input_select disponibles."""
        states = await ha_client.get_states()
        items = [
            _compact(state)
            for state in states
            if isinstance(state, dict)
            and isinstance(state.get("entity_id"), str)
            and state["entity_id"].startswith(f"{DOMAIN}.")
        ]
        return json.dumps(items, ensure_ascii=False, separators=(",", ":"))

    @mcp.tool()
    @ready
    async def ha_get_input_select(entity_id: str) -> object:
        """Devuelve la config persistida y el estado de un input_select."""
        try:
            config = await collection_get_current(ha_client, DOMAIN, entity_id)
            try:
                state = await ha_client.get_state(_entity_id_of(entity_id))
            except HAConnectionError:
                state = None
            return {"config": config, "state": state}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_get_input_select_failed",
                entity_id=entity_id,
                error=str(exc),
                exc_info=True,
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_create_or_update_input_select(
        entity_id: str,
        config: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Crea o modifica un input_select vía WS. Preview + token."""
        try:
            normalized_config = _dump_config(
                InputSelectConfig.model_validate(config)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ha_create_or_update_input_select_validation_failed",
                entity_id=entity_id,
                error=str(exc),
            )
            return {"error": f"config validation: {exc}"}

        return await collection_update_flow(
            ha_client,
            DOMAIN,
            entity_id,
            normalized_config,
            "ha_create_or_update_input_select",
            confirmation_token,
            logger,
        )

    @mcp.tool()
    @ready
    async def ha_delete_input_select(
        entity_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina un input_select vía WS. Siempre requiere `confirmation_token`."""
        return await collection_delete_flow(
            ha_client,
            DOMAIN,
            entity_id,
            "ha_delete_input_select",
            confirmation_token,
            logger,
        )

    # ── Acciones específicas ────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_set_input_select(entity_id: str, option: str) -> object:
        """Selecciona una opción en un input_select. Mapea a `input_select.select_option`."""
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_set_input_select_not_found", entity_id=eid)
            return not_found_response(eid)
        return await ha_client.call_service(
            DOMAIN, "select_option", {"entity_id": eid, "option": option}
        )

    @mcp.tool()
    @ready
    async def ha_cycle_input_select(
        entity_id: str,
        direction: str = "next",
        cycle: bool = True,
    ) -> object:
        """Avanza a la siguiente/anterior opción en un input_select.

        Args:
            direction: "next" (por defecto) o "previous".
            cycle: si True (por defecto), vuelve al principio al llegar al final.
        """
        if direction not in {"next", "previous"}:
            return {"error": f"direction inválida: {direction!r} (esperado 'next'|'previous')"}
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_cycle_input_select_not_found", entity_id=eid)
            return not_found_response(eid)
        service = "select_next" if direction == "next" else "select_previous"
        return await ha_client.call_service(
            DOMAIN, service, {"entity_id": eid, "cycle": cycle}
        )

    @mcp.tool()
    @ready
    async def ha_set_input_select_options(
        entity_id: str,
        options: list[str],
    ) -> object:
        """Reemplaza la lista de opciones de un input_select. Mapea a `input_select.set_options`."""
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_set_input_select_options_not_found", entity_id=eid)
            return not_found_response(eid)
        return await ha_client.call_service(
            DOMAIN, "set_options", {"entity_id": eid, "options": options}
        )
