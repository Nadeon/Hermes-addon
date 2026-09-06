"""Hermes — Tools MCP para input_datetime de Home Assistant."""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.models.input_datetime import InputDatetimeConfig
from hermes.tools._common import (
    collection_delete_flow,
    collection_get_current,
    collection_update_flow,
    entity_exists,
    not_found_response,
    requires_ready,
)

logger = structlog.get_logger(__name__)

DOMAIN = "input_datetime"


def _entity_id_of(raw: str) -> str:
    return raw if raw.startswith(f"{DOMAIN}.") else f"{DOMAIN}.{raw}"


def _compact(state: dict[str, Any]) -> dict[str, Any]:
    attrs = state.get("attributes", {}) or {}
    return {
        "entity_id": state.get("entity_id"),
        "friendly_name": attrs.get("friendly_name") or state.get("entity_id"),
        "state": state.get("state"),
        "has_date": attrs.get("has_date"),
        "has_time": attrs.get("has_time"),
    }


def _dump_config(model: InputDatetimeConfig) -> dict[str, Any]:
    return model.model_dump(exclude_none=True, by_alias=True, mode="json")


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de input_datetime."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_list_input_datetimes() -> object:
        """Lista los input_datetime disponibles."""
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
    async def ha_get_input_datetime(entity_id: str) -> object:
        """Devuelve la config persistida y el estado de un input_datetime."""
        try:
            config = await collection_get_current(ha_client, DOMAIN, entity_id)
            try:
                state = await ha_client.get_state(_entity_id_of(entity_id))
            except HAConnectionError:
                state = None
            return {"config": config, "state": state}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_get_input_datetime_failed",
                entity_id=entity_id,
                error=str(exc),
                exc_info=True,
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_create_or_update_input_datetime(
        entity_id: str,
        config: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Crea o modifica un input_datetime vía WS. Preview + token."""
        try:
            normalized_config = _dump_config(
                InputDatetimeConfig.model_validate(config)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ha_create_or_update_input_datetime_validation_failed",
                entity_id=entity_id,
                error=str(exc),
            )
            return {"error": f"config validation: {exc}"}

        return await collection_update_flow(
            ha_client,
            DOMAIN,
            entity_id,
            normalized_config,
            "ha_create_or_update_input_datetime",
            confirmation_token,
            logger,
        )

    @mcp.tool()
    @ready
    async def ha_delete_input_datetime(
        entity_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina un input_datetime vía WS. Siempre requiere `confirmation_token`."""
        return await collection_delete_flow(
            ha_client,
            DOMAIN,
            entity_id,
            "ha_delete_input_datetime",
            confirmation_token,
            logger,
        )

    # ── Acciones específicas ────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_set_input_datetime(
        entity_id: str,
        date: str | None = None,
        time: str | None = None,
        datetime: str | None = None,
        timestamp: float | None = None,
    ) -> object:
        """Pone el valor de un input_datetime. Mapea a `input_datetime.set_datetime`.

        Acepta cualquiera de los cuatro formatos que soporta HA (usa solo uno):
        - `date`: "YYYY-MM-DD"
        - `time`: "HH:MM:SS"
        - `datetime`: "YYYY-MM-DD HH:MM:SS"
        - `timestamp`: segundos Unix
        """
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_set_input_datetime_not_found", entity_id=eid)
            return not_found_response(eid)
        payload: dict[str, Any] = {"entity_id": eid}
        if date is not None:
            payload["date"] = date
        if time is not None:
            payload["time"] = time
        if datetime is not None:
            payload["datetime"] = datetime
        if timestamp is not None:
            payload["timestamp"] = timestamp
        return await ha_client.call_service(DOMAIN, "set_datetime", payload)
