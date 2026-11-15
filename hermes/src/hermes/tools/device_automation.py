"""Hermes — Automatizaciones de dispositivo (spec 017, tramo C, CAP-051).

Familia `automation_assist`. Tres tools de solo lectura:

- `ha_list_device_triggers` (`device_automation/trigger/list`),
- `ha_list_device_conditions` (`device_automation/condition/list`),
- `ha_list_device_actions` (`device_automation/action/list`).

POR QUÉ ASÍ (research R-6)
--------------------------
Cada elemento de la lista es lo que se pega TAL CUAL en una automatización
(`trigger: device`, `domain`, `device_id`, `entity_id`, `type`…), así que se
devuelve sin tocar su forma. Los campos extra que admite cada uno (la
duración `for`, un umbral…) salen de otro comando, `…/capabilities`, que pide
el elemento entero: con `include_capabilities=true` la tool hace esa llamada
por cada elemento y la cuelga en `capabilities`. Una tool aparte obligaría al
agente a reenviar cada elemento (más llamadas y más contexto para lo mismo).

- Las llamadas de capacidades van en serie (no se satura la WebSocket) y como
  mucho para los 50 primeros elementos; si hay más, `capabilities_truncated`
  y los demás sin `capabilities`. Un dispositivo con cientos de entidades no
  puede convertir una lectura en cientos de llamadas.
- Si las capacidades de un elemento fallan, ese elemento lleva
  `capabilities_error` (redactado) y la lista sigue: un elemento raro no deja
  al agente sin el resto.
- Lo que viene de HA pasa por `redact_structure` y `redact_secrets` antes de
  salir (FR-015): un valor por defecto de una capacidad lo escribe la
  integración. Los ids hexadecimales no se tocan (no parecen secretos).
- El log lleva el tipo, recuentos y códigos de HA; nunca el `device_id` ni
  los elementos.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import REDACTED_MARKER, es_clave_sensible, redact_secrets
from hermes.tools._common import (
    _LIMIT_HINT,
    ajustar_lista_a_bytes,
    requires_ready,
    sobre_de_lista,
)

logger = structlog.get_logger(__name__)

# Tope de llamadas de capacidades por lista (research R-6).
_MAX_CAPACIDADES = 50


def _limpio(valor: Any, clave: str = "") -> Any:
    """`redact_structure` + `redact_secrets` en todos los textos (FR-015)."""
    if isinstance(valor, Mapping):
        return {k: _limpio(v, str(k)) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_limpio(v, clave) for v in valor]
    if isinstance(valor, str):
        if valor and es_clave_sensible(clave):
            return REDACTED_MARKER
        return redact_secrets(valor)
    return valor


def _invalido(tool: str, campo: str, detalle: str) -> dict[str, Any]:
    logger.info(f"{tool}_failed", error="invalid_argument", field=campo)
    return {"error": "invalid_argument", "field": campo, "detail": detalle}


async def _listar(
    ha_client: HAClient,
    tool: str,
    tipo: str,
    device_id: Any,
    include_capabilities: Any,
    response_max_bytes: int,
    sobre: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Lo común de las tres tools: `tipo` es `trigger`, `condition` o `action`,
    que es también la clave del elemento en `…/capabilities`.

    `sobre` arma el sobre común: cada tool pasa una lambda que llama a
    `sobre_de_lista`, para que el test transversal de la spec 018 (por AST,
    en la función de la tool) vea que la tool usa el sobre."""
    if not isinstance(device_id, str) or not device_id.strip():
        return _invalido(tool, "device_id", "must be a non-empty string")
    if not isinstance(include_capabilities, bool):
        return _invalido(tool, "include_capabilities", "must be true or false")

    try:
        raw = await ha_client.ws_send(
            {"type": f"device_automation/{tipo}/list", "device_id": device_id})
    except HAConnectionError as exc:
        if exc.code == "not_found":
            logger.info(f"{tool}_failed", error="not_found")
            return {"error": "not_found", "device_id": device_id}
        if exc.code is None:
            logger.info(f"{tool}_failed", error="connection")
            return {"error": redact_secrets(str(exc))}
        logger.info(f"{tool}_failed", error=exc.code)
        return {"error": "ha_command_failed", "ha_code": exc.code,
                "detail": redact_secrets(str(exc))}

    if not isinstance(raw, list):
        logger.info(f"{tool}_failed", error="unexpected_response")
        return {"error": "unexpected_response",
                "detail": f"device_automation/{tipo}/list did not return a list"}

    items = [_limpio(e) if isinstance(e, Mapping) else e for e in raw]
    cabecera: dict[str, Any] = {"device_id": device_id}
    fallidas = 0
    if include_capabilities:
        for original, item in zip(raw[:_MAX_CAPACIDADES], items):
            if not isinstance(item, dict):
                continue
            # Se manda el elemento de HA, no la copia redactada: es el que HA
            # sabe validar (una clave tapada lo rompería).
            try:
                caps = await ha_client.ws_send(
                    {"type": f"device_automation/{tipo}/capabilities", tipo: original})
            except HAConnectionError as exc:
                fallidas += 1
                item["capabilities_error"] = redact_secrets(str(exc))
                continue
            item["capabilities"] = _limpio(caps) if isinstance(caps, Mapping) else {}
        cabecera["capabilities_truncated"] = len(items) > _MAX_CAPACIDADES
    total = len(items)

    def construir(lista: list[Any], recortada: bool) -> dict[str, Any]:
        out = sobre(lista, recortada, **cabecera)
        if recortada:
            out["_response_limit"] = {
                "list": "items", "returned": len(lista), "total": total,
                "max_bytes": response_max_bytes, "hint": _LIMIT_HINT,
            }
        return out

    respuesta = ajustar_lista_a_bytes(items, construir, response_max_bytes)
    logger.info(f"{tool}_ok", count=respuesta["count"], total=total,
                capabilities=include_capabilities, capabilities_failed=fallidas)
    return respuesta


def register(
    mcp: object,
    ha_client: HAClient,
    *,
    response_max_bytes: int,
) -> None:
    """Registra las tools de automatizaciones de dispositivo."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_list_device_triggers(
        device_id: str, include_capabilities: bool = False,
    ) -> object:
        """List the device triggers a device offers (read-only).

        Each item is a ready-made trigger: paste it as-is into an
        automation's `triggers` (it has `trigger: device`, `domain`,
        `device_id`, `entity_id`, `type`…). With include_capabilities=true,
        each of the first 50 items also gets `capabilities`: the extra fields
        it accepts (`extra_fields`, e.g. a `for` duration), to add next to
        the item's own keys. If an item's capabilities fail it gets
        `capabilities_error` instead; `capabilities_truncated` is true when
        there were more than 50 items.

        Args:
            device_id: Device registry id (from ha_list_devices).
            include_capabilities: Also fetch each item's extra fields.

        Returns:
            {"device_id", ["capabilities_truncated"], "count", "items",
            "truncated"}, or {"error": "not_found"|"invalid_argument"|...}.
        """
        return await _listar(ha_client, "ha_list_device_triggers", "trigger",
                             device_id, include_capabilities, response_max_bytes,
                             lambda items, recortada, **cab: sobre_de_lista(
                                 items, truncated=recortada, **cab))

    @mcp.tool()
    @ready
    async def ha_list_device_conditions(
        device_id: str, include_capabilities: bool = False,
    ) -> object:
        """List the device conditions a device offers (read-only).

        Each item is a ready-made condition: paste it as-is into an
        automation's `conditions` (it has `condition: device`, `domain`,
        `device_id`, `entity_id`, `type`…). With include_capabilities=true,
        each of the first 50 items also gets `capabilities`: the extra fields
        it accepts (`extra_fields`, e.g. a `for` duration or a threshold), to
        add next to the item's own keys. If an item's capabilities fail it
        gets `capabilities_error` instead; `capabilities_truncated` is true
        when there were more than 50 items.

        Args:
            device_id: Device registry id (from ha_list_devices).
            include_capabilities: Also fetch each item's extra fields.

        Returns:
            {"device_id", ["capabilities_truncated"], "count", "items",
            "truncated"}, or {"error": "not_found"|"invalid_argument"|...}.
        """
        return await _listar(ha_client, "ha_list_device_conditions", "condition",
                             device_id, include_capabilities, response_max_bytes,
                             lambda items, recortada, **cab: sobre_de_lista(
                                 items, truncated=recortada, **cab))

    @mcp.tool()
    @ready
    async def ha_list_device_actions(
        device_id: str, include_capabilities: bool = False,
    ) -> object:
        """List the device actions a device offers (read-only; runs nothing).

        Each item is a ready-made action step: paste it as-is into an
        automation's or script's `actions` (it has `domain`, `device_id`,
        `entity_id`, `type`…). With include_capabilities=true, each of the
        first 50 items also gets `capabilities`: the extra fields it accepts
        (`extra_fields`, e.g. a brightness), to add next to the item's own
        keys. If an item's capabilities fail it gets `capabilities_error`
        instead; `capabilities_truncated` is true when there were more than
        50 items.

        Args:
            device_id: Device registry id (from ha_list_devices).
            include_capabilities: Also fetch each item's extra fields.

        Returns:
            {"device_id", ["capabilities_truncated"], "count", "items",
            "truncated"}, or {"error": "not_found"|"invalid_argument"|...}.
        """
        return await _listar(ha_client, "ha_list_device_actions", "action",
                             device_id, include_capabilities, response_max_bytes,
                             lambda items, recortada, **cab: sobre_de_lista(
                                 items, truncated=recortada, **cab))
