"""Hermes — Tools MCP para input_number de Home Assistant."""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.models.input_number import InputNumberConfig
from hermes.tools._common import (
    collection_delete_flow,
    collection_get_current,
    collection_update_flow,
    entity_exists,
    not_found_response,
    requires_ready,
)

logger = structlog.get_logger(__name__)

DOMAIN = "input_number"


def _entity_id_of(raw: str) -> str:
    return raw if raw.startswith(f"{DOMAIN}.") else f"{DOMAIN}.{raw}"


def _compact(state: dict[str, Any]) -> dict[str, Any]:
    attrs = state.get("attributes", {}) or {}
    return {
        "entity_id": state.get("entity_id"),
        "friendly_name": attrs.get("friendly_name") or state.get("entity_id"),
        "state": state.get("state"),
        "min": attrs.get("min"),
        "max": attrs.get("max"),
        "step": attrs.get("step"),
        "unit_of_measurement": attrs.get("unit_of_measurement"),
    }


def _dump_config(model: InputNumberConfig) -> dict[str, Any]:
    return model.model_dump(exclude_none=True, by_alias=True, mode="json")


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de input_number."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_list_input_numbers() -> object:
        """Lista los input_number disponibles."""
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
    async def ha_get_input_number(entity_id: str) -> object:
        """Devuelve la config persistida y el estado de un input_number."""
        try:
            config = await collection_get_current(ha_client, DOMAIN, entity_id)
            try:
                state = await ha_client.get_state(_entity_id_of(entity_id))
            except HAConnectionError:
                state = None
            return {"config": config, "state": state}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_get_input_number_failed",
                entity_id=entity_id,
                error=str(exc),
                exc_info=True,
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_create_or_update_input_number(
        entity_id: str,
        config: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Crea o modifica un input_number vía WS. Preview + token."""
        try:
            normalized_config = _dump_config(
                InputNumberConfig.model_validate(config)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ha_create_or_update_input_number_validation_failed",
                entity_id=entity_id,
                error=str(exc),
            )
            return {"error": f"config validation: {exc}"}

        return await collection_update_flow(
            ha_client,
            DOMAIN,
            entity_id,
            normalized_config,
            "ha_create_or_update_input_number",
            confirmation_token,
            logger,
        )

    @mcp.tool()
    @ready
    async def ha_delete_input_number(
        entity_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina un input_number vía WS. Siempre requiere `confirmation_token`."""
        return await collection_delete_flow(
            ha_client,
            DOMAIN,
            entity_id,
            "ha_delete_input_number",
            confirmation_token,
            logger,
        )

    # ── Acciones específicas ────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_set_input_number(entity_id: str, value: float) -> object:
        """Pone un input_number a un valor concreto. Mapea a `input_number.set_value`."""
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_set_input_number_not_found", entity_id=eid)
            return not_found_response(eid)
        return await ha_client.call_service(
            DOMAIN, "set_value", {"entity_id": eid, "value": value}
        )

    @mcp.tool()
    @ready
    async def ha_increment_input_number(entity_id: str) -> object:
        """Incrementa un input_number en `step`. Mapea a `input_number.increment`."""
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_increment_input_number_not_found", entity_id=eid)
            return not_found_response(eid)
        return await ha_client.call_service(DOMAIN, "increment", {"entity_id": eid})

    @mcp.tool()
    @ready
    async def ha_decrement_input_number(entity_id: str) -> object:
        """Decrementa un input_number en `step`. Mapea a `input_number.decrement`."""
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_decrement_input_number_not_found", entity_id=eid)
            return not_found_response(eid)
        return await ha_client.call_service(DOMAIN, "decrement", {"entity_id": eid})
