"""Hermes — Tools MCP para schedule de Home Assistant."""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.models.schedule import ScheduleConfig
from hermes.tools._common import (
    guarded_reload,
    collection_delete_flow,
    collection_get_current,
    collection_update_flow,
    requires_ready,
)

logger = structlog.get_logger(__name__)

DOMAIN = "schedule"


def _entity_id_of(raw: str) -> str:
    return raw if raw.startswith(f"{DOMAIN}.") else f"{DOMAIN}.{raw}"


def _compact(state: dict[str, Any]) -> dict[str, Any]:
    attrs = state.get("attributes", {}) or {}
    return {
        "entity_id": state.get("entity_id"),
        "friendly_name": attrs.get("friendly_name") or state.get("entity_id"),
        "state": state.get("state"),
        "next_event": attrs.get("next_event"),
    }


def _dump_config(model: ScheduleConfig) -> dict[str, Any]:
    return model.model_dump(exclude_none=True, by_alias=True, mode="json")


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de schedule."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_list_schedules() -> object:
        """Lista los schedules disponibles."""
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
    async def ha_get_schedule(entity_id: str) -> object:
        """Devuelve la config persistida y el estado de un schedule."""
        try:
            config = await collection_get_current(ha_client, DOMAIN, entity_id)
            try:
                state = await ha_client.get_state(_entity_id_of(entity_id))
            except HAConnectionError:
                state = None
            return {"config": config, "state": state}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_get_schedule_failed",
                entity_id=entity_id,
                error=str(exc),
                exc_info=True,
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_create_or_update_schedule(
        entity_id: str,
        config: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Crea o modifica un schedule vía WS. Preview + token."""
        try:
            normalized_config = _dump_config(ScheduleConfig.model_validate(config))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ha_create_or_update_schedule_validation_failed",
                entity_id=entity_id,
                error=str(exc),
            )
            return {"error": f"config validation: {exc}"}

        return await collection_update_flow(
            ha_client,
            DOMAIN,
            entity_id,
            normalized_config,
            "ha_create_or_update_schedule",
            confirmation_token,
            logger,
        )

    @mcp.tool()
    @ready
    async def ha_delete_schedule(
        entity_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina un schedule vía WS. Siempre requiere `confirmation_token`."""
        return await collection_delete_flow(
            ha_client,
            DOMAIN,
            entity_id,
            "ha_delete_schedule",
            confirmation_token,
            logger,
        )

    @mcp.tool()
    @ready
    async def ha_reload_schedules(
        confirmation_token: str | None = None,
    ) -> object:
        """Recarga los schedules en Home Assistant.

        Requiere `confirmation_token`. Una recarga activa el YAML tal y
        como esté en /config en ese instante, así que es el paso que
        materializa cualquier escritura previa: el servicio
        `schedule.reload` está en la denylist justo por eso.
        """
        return await guarded_reload(
            ha_client, "schedule", "ha_reload_schedules", confirmation_token, "los schedules"
        )
