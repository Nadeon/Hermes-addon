"""Hermes — Targets y triggers/condiciones/acciones por propósito (spec 017,
tramo C, CAP-052).

Familia `automation_assist`. Cinco tools de solo lectura:

- `ha_resolve_target` (`extract_from_target`): qué entidades, dispositivos y
  áreas abarca un target, y qué referencias no existen.
- `ha_explain_target` (`explain_target`): por qué entra cada entidad y qué
  quita cada exclusión.
- `ha_list_triggers_for_target`, `ha_list_conditions_for_target` y
  `ha_list_actions_for_target` (`get_triggers_for_target`,
  `get_conditions_for_target`, `get_services_for_target`): los NOMBRES de
  los triggers, condiciones y acciones aplicables a alguna entidad del
  target, incluidos los «por propósito» (`light.turned_on`).

POR QUÉ ASÍ (research R-7)
--------------------------
- El target se valida aquí antes de llamar (claves admitidas, texto o lista
  de textos no vacíos, `exclude` con las mismas claves y al menos una clave
  fuera de `exclude`, la regla `exclude_requires_target` de HA). HA daría un
  `invalid_format` genérico o, peor, aceptaría un target solo con `exclude`
  en estos comandos (no aplican esa regla) y devolvería «nada» sin decir por
  qué. Una clave desconocida se nombra en el error: fail-closed y útil.
- `expand_group` y `primary_entities_only` existen con los valores por
  defecto de HA de cada comando (distintos entre `extract_from_target` y
  `explain_target`), para que la tool diga lo mismo que la interfaz de HA.
- Las listas dan solo nombres: las opciones de cada trigger o condición
  salen por suscripciones (`trigger_platforms/subscribe`), que Hermes no
  expone. La guía explica la forma general y remite a `ha_validate_config`
  (duda D-2 de la spec).
- Un `unknown_command` es un HA anterior a estos comandos:
  `ha_version_unsupported` con la versión, como `ha_search_related`.
- El tope de respuesta se aplica aquí: las listas con el sobre común;
  resolver y explicar recortan su lista mayor con `recortar_a_bytes` y lo
  dicen (`truncated` y `_response_limit`), con los recuentos exactos.
- El log lleva el nombre de la tool, recuentos y códigos; nunca el target.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.ha_version import ha_core_version
from hermes.security import redact_secrets
from hermes.tools._common import (
    _LIMIT_HINT,
    ajustar_lista_a_bytes,
    recortar_a_bytes,
    requires_ready,
    sobre_de_lista,
)

logger = structlog.get_logger(__name__)

# Las claves de un target en HA 2026.11.1 (`TARGET_ID_KEYS` de
# `helpers/config_validation.py`) y el bloque `exclude` con las mismas.
_CLAVES_TARGET: tuple[str, ...] = (
    "entity_id", "device_id", "area_id", "floor_id", "label_id",
)
_EXCLUDE = "exclude"


def _invalido(campo: str, detalle: str) -> dict[str, Any]:
    return {"error": "invalid_argument", "field": campo, "detail": detalle}


def _validar_ids(bloque: Mapping[Any, Any], prefijo: str) -> dict[str, Any] | None:
    """Las claves de `bloque` (sin `exclude`) y sus valores."""
    for clave, valor in bloque.items():
        campo = f"{prefijo}.{clave}"
        if clave not in _CLAVES_TARGET:
            return _invalido(campo, (
                f"unknown target key {clave!r}; valid keys: "
                + ", ".join(_CLAVES_TARGET)
                + (", exclude" if prefijo == "target" else "")))
        valores = valor if isinstance(valor, list) else [valor]
        if not valores or not all(isinstance(v, str) and v.strip() for v in valores):
            return _invalido(campo, "must be a non-empty string or a non-empty list of non-empty strings")
    return None


def _validar_target(target: Any) -> dict[str, Any] | None:
    """`None` si `target` es un target válido; si no, `invalid_argument`.

    Mismas reglas que `TARGET_FIELDS` + `exclude_requires_target` de HA, salvo
    que aquí no se admite un `exclude` vacío (no excluye nada: es un error
    del agente, no una intención).
    """
    if not isinstance(target, Mapping) or not target:
        return _invalido("target", (
            "must be an object with at least one of: " + ", ".join(_CLAVES_TARGET)))
    principal = {k: v for k, v in target.items() if k != _EXCLUDE}
    error = _validar_ids(principal, "target")
    if error:
        return error
    if _EXCLUDE in target:
        exclude = target[_EXCLUDE]
        if not isinstance(exclude, Mapping) or not exclude:
            return _invalido("target.exclude", (
                "must be an object with at least one of: " + ", ".join(_CLAVES_TARGET)))
        error = _validar_ids(exclude, "target.exclude")
        if error:
            return error
    if not principal:
        return _invalido("target", (
            "an exclude block requires a target to exclude from: add at least "
            "one of " + ", ".join(_CLAVES_TARGET)))
    return None


def _validar_bool(**valores: Any) -> dict[str, Any] | None:
    for nombre, valor in valores.items():
        if not isinstance(valor, bool):
            return _invalido(nombre, "must be true or false")
    return None


async def _enviar(
    ha_client: HAClient, tool: str, payload: dict[str, Any],
) -> tuple[Any, dict[str, Any] | None]:
    """`(respuesta, None)` o `(None, error)` con el error ya traducido."""
    try:
        return await ha_client.ws_send(payload), None
    except HAConnectionError as exc:
        if exc.code is None:
            logger.info(f"{tool}_failed", error="connection")
            return None, {"error": redact_secrets(str(exc))}
        logger.info(f"{tool}_failed", error=exc.code)
        if exc.code == "unknown_command":
            version = await ha_core_version(ha_client)
            return None, {
                "error": "ha_version_unsupported",
                "command": payload["type"],
                "current": str(version) if version is not None else None,
                "detail": ("This Home Assistant does not know this command; "
                           "it needs a newer Home Assistant."),
            }
        if exc.code == "invalid_format":
            # HA valida más fino que Hermes (p. ej. la forma de un entity_id).
            return None, {"error": "invalid_argument", "field": "target",
                          "ha_code": exc.code, "detail": redact_secrets(str(exc))}
        return None, {"error": "ha_command_failed", "ha_code": exc.code,
                      "detail": redact_secrets(str(exc))}


def _textos(valor: Any) -> list[str]:
    """Una lista (o conjunto serializado) de HA como lista ordenada de textos."""
    if not isinstance(valor, list):
        return []
    return sorted(str(v) for v in valor)


def _inesperada(tool: str, comando: str) -> dict[str, Any]:
    logger.info(f"{tool}_failed", error="unexpected_response")
    return {"error": "unexpected_response",
            "detail": f"{comando} returned an unexpected shape"}


def register(
    mcp: object,
    ha_client: HAClient,
    *,
    response_max_bytes: int,
) -> None:
    """Registra las tools de targets."""

    ready = requires_ready(ha_client)

    async def _lista_por_target(
        tool: str, comando: str, target: Any, expand_group: Any,
        sobre: Callable[[list[Any], bool], dict[str, Any]],
    ) -> dict[str, Any]:
        # `sobre` arma el sobre común: cada tool pasa una lambda que llama a
        # `sobre_de_lista`, para que el test transversal de la spec 018 (por
        # AST, en la función de la tool) vea que la tool usa el sobre.
        error = _validar_target(target) or _validar_bool(expand_group=expand_group)
        if error:
            logger.info(f"{tool}_failed", error="invalid_argument", field=error["field"])
            return error
        raw, error = await _enviar(ha_client, tool, {
            "type": comando, "target": target, "expand_group": expand_group})
        if error:
            return error
        if not isinstance(raw, list):
            return _inesperada(tool, comando)
        nombres = _textos(raw)
        total = len(nombres)

        def construir(lista: list[Any], recortada: bool) -> dict[str, Any]:
            out = sobre(lista, recortada)
            if recortada:
                out["_response_limit"] = {
                    "list": "items", "returned": len(lista), "total": total,
                    "max_bytes": response_max_bytes, "hint": _LIMIT_HINT,
                }
            return out

        respuesta = ajustar_lista_a_bytes(nombres, construir, response_max_bytes)
        logger.info(f"{tool}_ok", count=respuesta["count"], total=total)
        return respuesta

    @mcp.tool()
    @ready
    async def ha_resolve_target(
        target: dict[str, Any],
        expand_group: bool = False,
        primary_entities_only: bool = True,
    ) -> object:
        """Resolve a target to the entities, devices and areas it covers.

        Read-only. A target is what actions and purpose triggers take:
        {"entity_id"|"device_id"|"area_id"|"floor_id"|"label_id": id or
        [ids], "exclude": {same keys}}, with at least one key outside
        `exclude`. Ids that do not exist come back in `missing`. Lists are
        sorted; `counts` are exact even if the response was cut to fit the
        size limit ("truncated": true).

        Args:
            target: The target object.
            expand_group: Also expand group entities into their members
                (Home Assistant's default here is false).
            primary_entities_only: Leave out config and diagnostic entities
                (default true).

        Returns:
            {"entities", "devices", "areas", "missing": {"devices", "areas",
            "floors", "labels"}, "counts", "truncated"}, or {"error": ...}.
        """
        tool = "ha_resolve_target"
        error = (_validar_target(target)
                 or _validar_bool(expand_group=expand_group,
                                  primary_entities_only=primary_entities_only))
        if error:
            logger.info(f"{tool}_failed", error="invalid_argument", field=error["field"])
            return error
        raw, error = await _enviar(ha_client, tool, {
            "type": "extract_from_target", "target": target,
            "expand_group": expand_group,
            "primary_entities_only": primary_entities_only,
        })
        if error:
            return error
        if not isinstance(raw, dict):
            return _inesperada(tool, "extract_from_target")
        out: dict[str, Any] = {
            "entities": _textos(raw.get("referenced_entities")),
            "devices": _textos(raw.get("referenced_devices")),
            "areas": _textos(raw.get("referenced_areas")),
            "missing": {
                tipo: _textos(raw.get(f"missing_{tipo}"))
                for tipo in ("devices", "areas", "floors", "labels")
            },
        }
        out["counts"] = {k: len(out[k]) for k in ("entities", "devices", "areas")}
        out["truncated"] = False
        respuesta = recortar_a_bytes(out, response_max_bytes)
        logger.info(f"{tool}_ok", **out["counts"],
                    truncated=bool(respuesta.get("truncated")))
        return respuesta

    @mcp.tool()
    @ready
    async def ha_explain_target(
        target: dict[str, Any],
        expand_group: bool = True,
        primary_entities_only: bool = True,
    ) -> object:
        """Explain why each entity is part of a target (read-only).

        `includes`: one item per key of the target (type, id), with the
        entities it brings in and the areas and devices it goes through.
        `excludes`: what each `exclude` key removes. Same target format as
        ha_resolve_target. If the response does not fit the size limit, the
        largest list is cut and "truncated": true.

        Args:
            target: The target object.
            expand_group: Also expand group entities (default true here).
            primary_entities_only: Leave out config and diagnostic entities
                (default true).

        Returns:
            {"includes": [...], "excludes": [...], "truncated"}, or
            {"error": ...}.
        """
        tool = "ha_explain_target"
        error = (_validar_target(target)
                 or _validar_bool(expand_group=expand_group,
                                  primary_entities_only=primary_entities_only))
        if error:
            logger.info(f"{tool}_failed", error="invalid_argument", field=error["field"])
            return error
        raw, error = await _enviar(ha_client, tool, {
            "type": "explain_target", "target": target,
            "expand_group": expand_group,
            "primary_entities_only": primary_entities_only,
        })
        if error:
            return error
        if not isinstance(raw, dict):
            return _inesperada(tool, "explain_target")
        out = {
            "includes": raw.get("includes") if isinstance(raw.get("includes"), list) else [],
            "excludes": raw.get("excludes") if isinstance(raw.get("excludes"), list) else [],
            "truncated": False,
        }
        respuesta = recortar_a_bytes(out, response_max_bytes)
        logger.info(f"{tool}_ok", includes=len(out["includes"]),
                    excludes=len(out["excludes"]),
                    truncated=bool(respuesta.get("truncated")))
        return respuesta

    @mcp.tool()
    @ready
    async def ha_list_triggers_for_target(
        target: dict[str, Any], expand_group: bool = True,
    ) -> object:
        """List the names of the triggers usable with a target (read-only).

        Names only, sorted (e.g. "light.turned_on",
        "light.brightness_changed"), of the triggers that apply to at least
        one entity of the target, including purpose-specific ones. Write one
        as {"trigger": "light.turned_on", "target": {...}} and check it with
        ha_validate_config; this tool does not return each trigger's options.
        Same target format as ha_resolve_target.

        Args:
            target: The target object.
            expand_group: Also expand group entities (default true).

        Returns:
            {"count", "items", "truncated"}, or {"error": ...}
            ("ha_version_unsupported" on an older Home Assistant).
        """
        return await _lista_por_target(
            "ha_list_triggers_for_target", "get_triggers_for_target",
            target, expand_group,
            lambda items, recortada: sobre_de_lista(items, truncated=recortada))

    @mcp.tool()
    @ready
    async def ha_list_conditions_for_target(
        target: dict[str, Any], expand_group: bool = True,
    ) -> object:
        """List the names of the conditions usable with a target (read-only).

        Names only, sorted (e.g. "light.is_on"), of the conditions that
        apply to at least one entity of the target, including
        purpose-specific ones. Write one as {"condition": "light.is_on",
        "target": {...}} and check it with ha_validate_config; this tool does
        not return each condition's options. Same target format as
        ha_resolve_target.

        Args:
            target: The target object.
            expand_group: Also expand group entities (default true).

        Returns:
            {"count", "items", "truncated"}, or {"error": ...}
            ("ha_version_unsupported" on an older Home Assistant).
        """
        return await _lista_por_target(
            "ha_list_conditions_for_target", "get_conditions_for_target",
            target, expand_group,
            lambda items, recortada: sobre_de_lista(items, truncated=recortada))

    @mcp.tool()
    @ready
    async def ha_list_actions_for_target(
        target: dict[str, Any], expand_group: bool = True,
    ) -> object:
        """List the names of the actions usable with a target (read-only;
        runs nothing).

        Names only, sorted (e.g. "light.turn_on"), of the actions (services)
        that apply to at least one entity of the target. Their fields are in
        ha_list_services. Same target format as ha_resolve_target.

        Args:
            target: The target object.
            expand_group: Also expand group entities (default true).

        Returns:
            {"count", "items", "truncated"}, or {"error": ...}
            ("ha_version_unsupported" on an older Home Assistant).
        """
        return await _lista_por_target(
            "ha_list_actions_for_target", "get_services_for_target",
            target, expand_group,
            lambda items, recortada: sobre_de_lista(items, truncated=recortada))
