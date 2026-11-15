"""Hermes — Tools MCP para counter de Home Assistant."""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.models.counter import CounterConfig
from hermes.tools._common import (
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


def _state_number(state: dict[str, Any]) -> int | None:
    try:
        return int(state.get("state"))
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _value_problem(state: dict[str, Any], value: int) -> dict[str, Any] | None:
    """Por qué HA rechazaría `counter.set_value` con `value`, o None si lo acepta.

    Spec 033 (FR-009, research R-7): `async_set_value` de
    `counter/entity.py` lanza `ValueError` si el valor pasa de `maximum`,
    baja de `minimum` o no es múltiplo de `step`, y el REST de Core no
    traduce ese `ValueError`: llega un 500 genérico que no dice nada. Se
    comprueba antes, con los mismos atributos que HA publica en el estado
    (`extra_state_attributes`) y en el mismo orden que HA. Sin `step` en los
    atributos se asume 1, el valor por defecto de la integración.
    """
    attrs = state.get("attributes") or {}
    step = _int_or_none(attrs.get("step")) or 1
    minimum = _int_or_none(attrs.get("minimum"))
    maximum = _int_or_none(attrs.get("maximum"))
    reason: str | None = None
    if (maximum is not None and value > maximum) or (
        minimum is not None and value < minimum
    ):
        reason = "out_of_range"
    elif value % step != 0:
        reason = "not_multiple_of_step"
    if reason is None:
        return None
    return {"reason": reason, "step": step, "minimum": minimum, "maximum": maximum}


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
        estado actual y fijamos el nuevo valor de una sola llamada. Antes se
        comprueba que HA lo vaya a aceptar (`_value_problem`): si no, Core da
        un 500 sin explicación (spec 033, FR-009).
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
        target = current + delta
        problem = _value_problem(state, target)
        if problem is not None:
            logger.warning(
                "counter_invalid_amount", entity_id=eid, target=target, reason=problem["reason"]
            )
            return {
                "error": "invalid_amount",
                "reason": problem["reason"],
                "entity_id": eid,
                "current": current,
                "target": target,
                "step": problem["step"],
                "minimum": problem["minimum"],
                "maximum": problem["maximum"],
                "hint": (
                    "Home Assistant only accepts values that are multiples of step "
                    "and within minimum/maximum. Call without amount to move one "
                    "step, or use ha_set_counter_value with a valid value."
                ),
            }
        return await ha_client.call_service(
            DOMAIN, "set_value", {"entity_id": eid, "value": target}
        )

    @mcp.tool()
    @ready
    async def ha_increment_counter(
        entity_id: str, amount: int | None = None
    ) -> object:
        """Incrementa un counter. Mapea a `counter.increment`.

        Si se suministra `amount`, usa el estado actual y `counter.set_value`
        para saltar en bloque (HA no soporta amount directo en increment): el
        valor resultante (actual + amount) tiene que ser múltiplo de `step` y
        estar dentro de `minimum`/`maximum`, o HA lo rechaza. Si no lo es,
        responde `invalid_amount` (con `reason` `not_multiple_of_step` u
        `out_of_range`) sin tocar el counter. Sin `amount`, HA avanza un
        `step` y se queda en el límite si lo alcanza.
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
        amount directo en decrement): el valor resultante (actual − amount)
        tiene que ser múltiplo de `step` y estar dentro de
        `minimum`/`maximum`; si no, responde `invalid_amount` sin tocar el
        counter. Sin `amount`, HA baja un `step` y se queda en el límite.
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
        """Fija el valor de un counter. Mapea a `counter.set_value`.

        HA solo acepta un `value` múltiplo de `step` y dentro de
        `minimum`/`maximum`; si no lo es, responde `invalid_value` (con
        `reason` `not_multiple_of_step` u `out_of_range`) sin tocar el counter.
        """
        eid = _entity_id_of(entity_id)
        # Se lee el estado (y no solo si existe) para comprobar el valor con
        # sus atributos: sin esto, HA responde un 500 genérico (extra del
        # supervisor en la spec 033, misma regla que `amount`).
        state = await ha_client.get_state(eid)
        if not isinstance(state, dict):
            logger.warning("ha_set_counter_value_not_found", entity_id=eid)
            return not_found_response(eid)
        problem = _value_problem(state, value)
        if problem is not None:
            logger.warning(
                "counter_invalid_value", entity_id=eid, value=value, reason=problem["reason"]
            )
            return {
                "error": "invalid_value",
                "reason": problem["reason"],
                "entity_id": eid,
                "current": _state_number(state),
                "value": value,
                "step": problem["step"],
                "minimum": problem["minimum"],
                "maximum": problem["maximum"],
                "hint": (
                    "Home Assistant only accepts values that are multiples of step "
                    "and within minimum/maximum."
                ),
            }
        return await ha_client.call_service(
            DOMAIN, "set_value", {"entity_id": eid, "value": value}
        )

    @mcp.tool()
    @ready
    async def ha_reload_counters(
        confirmation_token: str | None = None,
    ) -> object:
        """DEPRECATED (removed in 1.3.0): Home Assistant has no counter reload.

        Siempre responde `not_supported`, con o sin `confirmation_token` (que
        se acepta y se ignora), sin llamar a Home Assistant. La integración
        `counter` no tiene servicio `counter.reload`: los counters creados
        desde la UI o con Hermes se aplican al guardarlos, y los de YAML se
        leen al reiniciar Home Assistant.
        """
        # Spec 033 (FR-004, research R-2): `counter/services.py` solo registra
        # increment, decrement, reset y set_value, y ninguna otra vía recarga
        # los contadores (`reload_all` tampoco). Antes esta tool pedía token y
        # al confirmar Core respondía 400. No se emite ni se gasta ningún
        # token: no hay nada que confirmar. El nombre, el argumento y las
        # anotaciones se quedan hasta la 1.3.0 (FR-020 de la 008).
        return {
            "error": "not_supported",
            "message": (
                "Home Assistant has no counter.reload service: the counter "
                "integration only registers increment, decrement, reset and set_value."
            ),
            "hint": (
                "Counters created from the UI or with Hermes apply on save; YAML "
                "counters are read when Home Assistant restarts."
            ),
            "_deprecated": (
                "ha_reload_counters is deprecated and will be removed in 1.3.0; "
                "there is nothing to replace it with."
            ),
        }
