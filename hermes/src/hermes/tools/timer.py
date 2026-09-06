"""Hermes — Tools MCP para timer de Home Assistant."""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.models.timer import TimerConfig
from hermes.tools._common import (
    guarded_reload,
    collection_delete_flow,
    collection_get_current,
    collection_update_flow,
    entity_exists,
    not_found_response,
    requires_ready,
)

logger = structlog.get_logger(__name__)

DOMAIN = "timer"


def _entity_id_of(raw: str) -> str:
    return raw if raw.startswith(f"{DOMAIN}.") else f"{DOMAIN}.{raw}"


def _compact(state: dict[str, Any]) -> dict[str, Any]:
    attrs = state.get("attributes", {}) or {}
    return {
        "entity_id": state.get("entity_id"),
        "friendly_name": attrs.get("friendly_name") or state.get("entity_id"),
        "state": state.get("state"),
        "duration": attrs.get("duration"),
        "remaining": attrs.get("remaining"),
        "finishes_at": attrs.get("finishes_at"),
    }


def _dump_config(model: TimerConfig) -> dict[str, Any]:
    return model.model_dump(exclude_none=True, by_alias=True, mode="json")


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de timer."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_list_timers() -> object:
        """Lista los timers disponibles."""
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
    async def ha_get_timer(entity_id: str) -> object:
        """Devuelve la config persistida y el estado de un timer."""
        try:
            config = await collection_get_current(ha_client, DOMAIN, entity_id)
            try:
                state = await ha_client.get_state(_entity_id_of(entity_id))
            except HAConnectionError:
                state = None
            return {"config": config, "state": state}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_get_timer_failed",
                entity_id=entity_id,
                error=str(exc),
                exc_info=True,
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_create_or_update_timer(
        entity_id: str,
        config: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Crea o modifica un timer vía WS. Preview + token."""
        try:
            normalized_config = _dump_config(TimerConfig.model_validate(config))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ha_create_or_update_timer_validation_failed",
                entity_id=entity_id,
                error=str(exc),
            )
            return {"error": f"config validation: {exc}"}

        return await collection_update_flow(
            ha_client,
            DOMAIN,
            entity_id,
            normalized_config,
            "ha_create_or_update_timer",
            confirmation_token,
            logger,
        )

    @mcp.tool()
    @ready
    async def ha_delete_timer(
        entity_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina un timer vía WS. Siempre requiere `confirmation_token`."""
        return await collection_delete_flow(
            ha_client,
            DOMAIN,
            entity_id,
            "ha_delete_timer",
            confirmation_token,
            logger,
        )

    # ── Acciones específicas ────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_start_timer(
        entity_id: str, duration: str | None = None
    ) -> object:
        """Arranca un timer. Mapea a `timer.start`.

        `duration` es opcional; formato `HH:MM:SS` o segundos como string.
        Si se omite, HA usa la duración configurada del timer.
        """
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_start_timer_not_found", entity_id=eid)
            return not_found_response(eid)
        payload: dict[str, Any] = {"entity_id": eid}
        if duration is not None:
            payload["duration"] = duration
        return await ha_client.call_service(DOMAIN, "start", payload)

    @mcp.tool()
    @ready
    async def ha_pause_timer(entity_id: str) -> object:
        """Pausa un timer. Mapea a `timer.pause`."""
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_pause_timer_not_found", entity_id=eid)
            return not_found_response(eid)
        return await ha_client.call_service(DOMAIN, "pause", {"entity_id": eid})

    @mcp.tool()
    @ready
    async def ha_cancel_timer(entity_id: str) -> object:
        """Cancela un timer. Mapea a `timer.cancel`."""
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_cancel_timer_not_found", entity_id=eid)
            return not_found_response(eid)
        return await ha_client.call_service(DOMAIN, "cancel", {"entity_id": eid})

    @mcp.tool()
    @ready
    async def ha_finish_timer(entity_id: str) -> object:
        """Fuerza el finish de un timer. Mapea a `timer.finish`."""
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_finish_timer_not_found", entity_id=eid)
            return not_found_response(eid)
        return await ha_client.call_service(DOMAIN, "finish", {"entity_id": eid})

    @mcp.tool()
    @ready
    async def ha_change_timer(entity_id: str, duration: str) -> object:
        """Cambia la duración restante de un timer activo. Mapea a `timer.change`.

        Solo aplicable a timers en estado `active`. `duration` es un delta:
        formato `HH:MM:SS` positivo añade, negativo resta.
        """
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_change_timer_not_found", entity_id=eid)
            return not_found_response(eid)
        return await ha_client.call_service(
            DOMAIN, "change", {"entity_id": eid, "duration": duration}
        )

    @mcp.tool()
    @ready
    async def ha_reload_timers(
        confirmation_token: str | None = None,
    ) -> object:
        """Recarga los timers en Home Assistant.

        Requiere `confirmation_token`. Una recarga activa el YAML tal y
        como esté en /config en ese instante, así que es el paso que
        materializa cualquier escritura previa: el servicio
        `timer.reload` está en la denylist justo por eso.
        """
        return await guarded_reload(
            ha_client, "timer", "ha_reload_timers", confirmation_token, "los timers"
        )
