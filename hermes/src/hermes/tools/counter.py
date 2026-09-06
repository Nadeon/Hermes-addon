"""Hermes — Tools MCP para counter de Home Assistant."""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.models.counter import CounterConfig
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

DOMAIN = "counter"


def _entity_id_of(raw: str) -> str:
    return raw if raw.startswith(f"{DOMAIN}.") else f"{DOMAIN}.{raw}"


def _compact(state: dict[str, Any]) -> dict[str, Any]:
    attrs = state.get("attributes", {}) or {}
    return {
        "entity_id": state.get("entity_id"),
        "friendly_name": attrs.get("friendly_name") or state.get("entity_id"),
        "state": state.get("state"),
        "minimum": attrs.get("minimum"),
        "maximum": attrs.get("maximum"),
        "step": attrs.get("step"),
        "initial": attrs.get("initial"),
    }


def _dump_config(model: CounterConfig) -> dict[str, Any]:
    return model.model_dump(exclude_none=True, by_alias=True, mode="json")


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de counter."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_list_counters() -> object:
        """Lista los counters disponibles."""
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
    async def ha_get_counter(entity_id: str) -> object:
        """Devuelve la config persistida y el estado de un counter."""
        try:
            config = await collection_get_current(ha_client, DOMAIN, entity_id)
            try:
                state = await ha_client.get_state(_entity_id_of(entity_id))
            except HAConnectionError:
                state = None
            return {"config": config, "state": state}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_get_counter_failed",
                entity_id=entity_id,
                error=str(exc),
                exc_info=True,
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_create_or_update_counter(
        entity_id: str,
        config: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Crea o modifica un counter vía WS. Preview + token."""
        try:
            normalized_config = _dump_config(CounterConfig.model_validate(config))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ha_create_or_update_counter_validation_failed",
                entity_id=entity_id,
                error=str(exc),
            )
            return {"error": f"config validation: {exc}"}

        return await collection_update_flow(
            ha_client,
            DOMAIN,
            entity_id,
            normalized_config,
            "ha_create_or_update_counter",
            confirmation_token,
            logger,
        )

    @mcp.tool()
    @ready
    async def ha_delete_counter(
        entity_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina un counter vía WS. Siempre requiere `confirmation_token`."""
        return await collection_delete_flow(
            ha_client,
            DOMAIN,
            entity_id,
            "ha_delete_counter",
            confirmation_token,
            logger,
        )

    # ── Acciones específicas ────────────────────────────────

    async def _bulk_adjust(eid: str, delta: int) -> object:
        """Ajusta el valor de un counter en `delta` vía `counter.set_value`.

        HA no soporta `amount` en increment/decrement, así que leemos el
        estado actual y fijamos el nuevo valor de una sola llamada.
        """
        try:
            state = await ha_client.get_state(eid)
        except HAConnectionError as exc:
            return {"error": f"state_read: {exc}"}
        if not isinstance(state, dict):
            return not_found_response(eid)
        try:
            current = int(state.get("state", 0))
        except (TypeError, ValueError):
            return {"error": f"invalid_state: {state.get('state')!r}"}
        return await ha_client.call_service(
            DOMAIN, "set_value", {"entity_id": eid, "value": current + delta}
        )

    @mcp.tool()
    @ready
    async def ha_increment_counter(
        entity_id: str, amount: int | None = None
    ) -> object:
        """Incrementa un counter. Mapea a `counter.increment`.

        Si se suministra `amount`, usa el estado actual y `counter.set_value`
        para saltar en bloque (HA no soporta amount directo en increment).
        """
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_increment_counter_not_found", entity_id=eid)
            return not_found_response(eid)
        if amount is None:
            return await ha_client.call_service(
                DOMAIN, "increment", {"entity_id": eid}
            )
        return await _bulk_adjust(eid, amount)

    @mcp.tool()
    @ready
    async def ha_decrement_counter(
        entity_id: str, amount: int | None = None
    ) -> object:
        """Decrementa un counter. Mapea a `counter.decrement`.

        Con `amount`, salta en bloque vía `counter.set_value` (HA no soporta
        amount directo en decrement).
        """
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_decrement_counter_not_found", entity_id=eid)
            return not_found_response(eid)
        if amount is None:
            return await ha_client.call_service(
                DOMAIN, "decrement", {"entity_id": eid}
            )
        return await _bulk_adjust(eid, -amount)

    @mcp.tool()
    @ready
    async def ha_reset_counter(entity_id: str) -> object:
        """Resetea un counter al valor `initial`. Mapea a `counter.reset`."""
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_reset_counter_not_found", entity_id=eid)
            return not_found_response(eid)
        return await ha_client.call_service(DOMAIN, "reset", {"entity_id": eid})

    @mcp.tool()
    @ready
    async def ha_set_counter_value(entity_id: str, value: int) -> object:
        """Fija el valor de un counter. Mapea a `counter.set_value`."""
        eid = _entity_id_of(entity_id)
        if not await entity_exists(ha_client, eid):
            logger.warning("ha_set_counter_value_not_found", entity_id=eid)
            return not_found_response(eid)
        return await ha_client.call_service(
            DOMAIN, "set_value", {"entity_id": eid, "value": value}
        )

    @mcp.tool()
    @ready
    async def ha_reload_counters(
        confirmation_token: str | None = None,
    ) -> object:
        """Recarga los counters en Home Assistant.

        Requiere `confirmation_token`. Una recarga activa el YAML tal y
        como esté en /config en ese instante, así que es el paso que
        materializa cualquier escritura previa: el servicio
        `counter.reload` está en la denylist justo por eso.
        """
        return await guarded_reload(
            ha_client, "counter", "ha_reload_counters", confirmation_token, "los counters"
        )
