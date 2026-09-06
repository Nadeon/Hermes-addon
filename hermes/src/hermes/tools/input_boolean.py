"""Hermes — Tools MCP para input_boolean de Home Assistant."""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.models.input_boolean import InputBooleanConfig
from hermes.tools._common import (
    collection_delete_flow,
    collection_get_current,
    collection_update_flow,
    entity_exists,
    not_found_response,
    requires_ready,
)

logger = structlog.get_logger(__name__)

DOMAIN = "input_boolean"


def _entity_id_of(raw: str) -> str:
    return raw if raw.startswith(f"{DOMAIN}.") else f"{DOMAIN}.{raw}"


def _compact(state: dict[str, Any]) -> dict[str, Any]:
    attrs = state.get("attributes", {}) or {}
    return {
        "entity_id": state.get("entity_id"),
        "friendly_name": attrs.get("friendly_name") or state.get("entity_id"),
        "state": state.get("state"),
        "icon": attrs.get("icon"),
    }


def _dump_config(model: InputBooleanConfig) -> dict[str, Any]:
    return model.model_dump(exclude_none=True, by_alias=True, mode="json")


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de input_boolean."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_list_input_booleans() -> object:
        """Lista los input_boolean disponibles en Home Assistant."""
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
    async def ha_get_input_boolean(entity_id: str) -> object:
        """Devuelve la config persistida y el estado de un input_boolean."""
        try:
            config = await collection_get_current(ha_client, DOMAIN, entity_id)
            try:
                state = await ha_client.get_state(_entity_id_of(entity_id))
            except HAConnectionError:
                state = None
            return {"config": config, "state": state}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_get_input_boolean_failed",
                entity_id=entity_id,
                error=str(exc),
                exc_info=True,
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_create_or_update_input_boolean(
        entity_id: str,
        config: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Crea o modifica un input_boolean vía WS `input_boolean/{create,update}`.

        Si no se suministra `confirmation_token`, devuelve preview + token.
        En create, HA genera el object_id desde `slugify(name)`.
        """
        try:
            normalized_config = _dump_config(
                InputBooleanConfig.model_validate(config)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ha_create_or_update_input_boolean_validation_failed",
                entity_id=entity_id,
                error=str(exc),
            )
            return {"error": f"config validation: {exc}"}

        return await collection_update_flow(
            ha_client,
            DOMAIN,
            entity_id,
            normalized_config,
            "ha_create_or_update_input_boolean",
            confirmation_token,
            logger,
        )

    @mcp.tool()
    @ready
    async def ha_delete_input_boolean(
        entity_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina un input_boolean vía WS. Siempre requiere `confirmation_token`."""
        return await collection_delete_flow(
            ha_client,
            DOMAIN,
            entity_id,
            "ha_delete_input_boolean",
            confirmation_token,
            logger,
        )

    # ── Acciones específicas ────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_set_input_boolean(entity_id: str, value: bool) -> object:
        """Pone un input_boolean en on/off. Mapea a `input_boolean.turn_on/turn_off`."""
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_set_input_boolean_not_found", entity_id=eid)
            return not_found_response(eid)
        service = "turn_on" if value else "turn_off"
        return await ha_client.call_service(DOMAIN, service, {"entity_id": eid})

    @mcp.tool()
    @ready
    async def ha_toggle_input_boolean(entity_id: str) -> object:
        """Conmuta un input_boolean. Mapea a `input_boolean.toggle`."""
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_toggle_input_boolean_not_found", entity_id=eid)
            return not_found_response(eid)
        return await ha_client.call_service(DOMAIN, "toggle", {"entity_id": eid})
