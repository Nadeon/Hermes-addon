"""Hermes — Tools MCP para Category Registry (categorías).

Usa los comandos WS `config/category_registry/{list,create,update,delete}`,
presentes con los mismos campos desde 2024.10.0. Todos llevan `scope`, también
`list`: cada scope es un registro aparte y la misma `category_id` puede
existir en dos scopes como cosas distintas.

Campos de una categoría: category_id (generado por HA), name, icon,
created_at, modified_at. Una entidad la referencia en
`categories: {scope: category_id}`.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    validate_confirmation_token,
)
from hermes.tools._common import requires_ready
from hermes.tools._validation import (
    InvalidIdentifier,
    build_ws_payload,
    identifier_error,
    validate_identifier,
)
from hermes.tools.registry_floor import (
    LecturaFallida,
    acotar,
    buscar_entrada,
    invalid_argument,
    leer_lista,
    plural,
    preview_unavailable,
)

logger = structlog.get_logger(__name__)

# Scopes que usa el frontend. HA acepta cualquier texto como `scope`, así que
# esta es la única barrera: una categoría con un scope inventado se crearía
# bien pero sería invisible en la interfaz.
_SCOPES = ("automation", "script", "scene", "helpers")

_CATEGORY_FIELDS = ("name", "icon")


def _scope_error(scope: Any) -> dict[str, str] | None:
    if scope in _SCOPES:
        return None
    return invalid_argument("scope", f"must be one of: {', '.join(_SCOPES)}")


def _validate_category_fields(
    fields: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str] | None]:
    """Valida y normaliza campos de categoría antes de enviar nada a HA."""
    out: dict[str, Any] = {}
    for k, v in fields.items():
        if k == "name":
            if not isinstance(v, str) or not v.strip():
                return {}, invalid_argument("name", "must be a non-empty string")
            out[k] = v.strip()
        elif k == "icon":
            if v is not None and not isinstance(v, str):
                return {}, invalid_argument("icon", "must be a string or null")
            out[k] = v
        else:
            return {}, invalid_argument(
                k, f"unknown field; allowed: {', '.join(_CATEGORY_FIELDS)}"
            )
    return out, None


def _validar_ids(scope: Any, category_id: Any) -> str | None:
    """Valida scope e id; devuelve el JSON de error o None."""
    err = _scope_error(scope)
    if err:
        return json.dumps(err)
    try:
        validate_identifier(category_id, field="category_id")
    except InvalidIdentifier as exc:
        return json.dumps(identifier_error(exc))
    return None


async def _impacto_categoria(
    ha_client: HAClient, scope: str, category_id: str
) -> dict[str, Any]:
    """Entidades que perderán la categoría en ESTE scope.

    Se compara `categories[scope]` y no «alguna categoría con esa id»: la
    misma id en otro scope es otra categoría y no se toca. Sin
    `references_unresolved`: las categorías no se usan como destino.
    """
    entities = await leer_lista(ha_client, "config/entity_registry/list")
    ids: list[str] = []
    for e in entities:
        categorias = e.get("categories") or {}
        if not isinstance(categorias, dict):
            raise LecturaFallida(
                f"categories of {e.get('entity_id')!r} is not an object"
            )
        if categorias.get(scope) == category_id:
            ids.append(str(e.get("entity_id")))
    return {"assignments_removed": {"entities": acotar(ids)}}


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de category registry."""

    ready = requires_ready(ha_client)

    async def _leer_actual(scope: str, category_id: str) -> dict[str, Any] | None:
        return await buscar_entrada(
            ha_client,
            "config/category_registry/list",
            "category_id",
            category_id,
            {"scope": scope},
        )

    # ── ha_list_categories ────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_categories(scope: str) -> object:
        """List the categories of one scope.

        Args:
            scope: automation, script, scene or helpers.

        Returns:
            JSON {"scope", "count": n, "categories": [{"category_id",
            "name", "icon", ...}, ...]}
        """
        err = _scope_error(scope)
        if err:
            return json.dumps(err)
        try:
            raw: Any = await ha_client.ws_send(
                {"type": "config/category_registry/list", "scope": scope}
            )
        except HAConnectionError as exc:
            logger.error("ha_list_categories_ws_error", scope=scope, error=str(exc))
            return json.dumps({"error": str(exc)})
        items: list[dict] = raw if isinstance(raw, list) else []
        logger.info("ha_list_categories_ok", scope=scope, count=len(items))
        return json.dumps(
            {"scope": scope, "count": len(items), "categories": items},
            ensure_ascii=False,
        )

    # ── ha_create_category ────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_create_category(
        scope: str,
        name: str,
        icon: str | None = None,
    ) -> object:
        """Create a category in a scope. No confirmation needed.

        Args:
            scope: automation, script, scene or helpers.
            name:  Category name.
            icon:  MDI icon. Optional.

        Returns:
            JSON with the created entry, including the generated category_id.
        """
        err = _scope_error(scope)
        if err:
            return json.dumps(err)
        fields: dict[str, Any] = {"name": name}
        if icon is not None:
            fields["icon"] = icon
        normalized, err = _validate_category_fields(fields)
        if err:
            return json.dumps(err)

        payload = build_ws_payload(
            "config/category_registry/create", {"scope": scope}, normalized
        )
        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            logger.error("ha_create_category_ws_error", scope=scope, error=str(exc))
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        logger.info(
            "ha_create_category_ok",
            scope=scope,
            category_id=raw.get("category_id") if isinstance(raw, dict) else None,
        )
        return json.dumps(raw, ensure_ascii=False)

    # ── ha_update_category ────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_update_category(
        scope: str,
        category_id: str,
        updates: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Edit an existing category (it does not create one). Two-step confirmation.

        Args:
            scope:              automation, script, scene or helpers.
            category_id:        Category to edit.
            updates:            Any of: name (str), icon (str|null).
            confirmation_token: Token from the preview call.

        Returns:
            Without token: {"confirmation_token", "preview": {"scope",
            "category_id", "current", "proposed_changes"}}; errors not_found
            or preview_unavailable (no token). With token: {"result": "ok", ...}.
        """
        err_ids = _validar_ids(scope, category_id)
        if err_ids:
            return err_ids
        if not isinstance(updates, dict):
            return json.dumps(invalid_argument("updates", "must be an object"))
        normalized, err = _validate_category_fields(updates)
        if err:
            return json.dumps(err)
        if not normalized:
            return json.dumps({"error": "updates is empty"})

        # El scope va atado al token: sin él, un token emitido tras revisar la
        # categoría de automatizaciones serviría para editar la homónima de
        # scripts, que el humano no ha visto.
        args = {"scope": scope, "category_id": category_id, "updates": normalized}

        if not confirmation_token:
            try:
                current = await _leer_actual(scope, category_id)
            except LecturaFallida as exc:
                logger.warning(
                    "ha_update_category_preview_unavailable",
                    scope=scope, category_id=category_id,
                )
                return preview_unavailable("category_id", category_id, str(exc))
            if current is None:
                return json.dumps(
                    {"error": "not_found", "scope": scope, "category_id": category_id}
                )
            preview = {
                "scope": scope,
                "category_id": category_id,
                "current": current,
                "proposed_changes": normalized,
            }
            token_data = await create_confirmation_token(
                "ha_update_category", args, preview=preview
            )
            return json.dumps(token_data, ensure_ascii=False)

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_update_category", args
        )
        if not valid:
            logger.warning(
                "ha_update_category_token_invalid",
                scope=scope, category_id=category_id, reason=error,
            )
            return json.dumps({"error": error})

        payload = build_ws_payload(
            "config/category_registry/update",
            {"scope": scope, "category_id": category_id},
            normalized,
        )
        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            logger.error(
                "ha_update_category_ws_error",
                scope=scope, category_id=category_id, error=str(exc),
            )
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

        await complete_confirmation_token(confirmation_token, success=True, result=raw)
        logger.info("ha_update_category_ok", scope=scope, category_id=category_id)
        result: dict[str, Any] = {"result": "ok"}
        if isinstance(raw, dict):
            result.update(raw)
        return json.dumps(result, ensure_ascii=False)

    # ── ha_delete_category ────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_delete_category(
        scope: str,
        category_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Delete a category. Two-step confirmation with an impact preview.

        Home Assistant removes the category from the entities that have it in
        this scope; the automations/scripts/scenes/helpers themselves keep
        working. The preview lists those entities (up to 50 ids, exact count).
        If any read fails, no token is issued (preview_unavailable).

        Args:
            scope:              automation, script, scene or helpers.
            category_id:        Category to delete.
            confirmation_token: Token from the preview call.

        Returns:
            Without token: {"confirmation_token", "preview": {"scope",
            "category_id", "current", "impact": {"assignments_removed":
            {"entities"}}, "warning"}}. With token: {"result": "ok"}.
        """
        err_ids = _validar_ids(scope, category_id)
        if err_ids:
            return err_ids

        args = {"scope": scope, "category_id": category_id}

        if not confirmation_token:
            try:
                current = await _leer_actual(scope, category_id)
                if current is None:
                    return json.dumps(
                        {"error": "not_found", "scope": scope, "category_id": category_id}
                    )
                impact = await _impacto_categoria(ha_client, scope, category_id)
            except LecturaFallida as exc:
                logger.warning(
                    "ha_delete_category_preview_unavailable",
                    scope=scope, category_id=category_id,
                )
                return preview_unavailable("category_id", category_id, str(exc))

            n = impact["assignments_removed"]["entities"]["count"]
            preview = {
                "scope": scope,
                "category_id": category_id,
                "current": current,
                "impact": impact,
                "warning": (
                    f"Deleting this category removes it from "
                    f"{plural(n, 'entity', 'entities')} in scope '{scope}'. "
                    "They keep working; only the grouping is lost."
                ),
            }
            token_data = await create_confirmation_token(
                "ha_delete_category", args, preview=preview
            )
            return json.dumps(token_data, ensure_ascii=False)

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_delete_category", args
        )
        if not valid:
            logger.warning(
                "ha_delete_category_token_invalid",
                scope=scope, category_id=category_id, reason=error,
            )
            return json.dumps({"error": error})

        try:
            await ha_client.ws_send({
                "type": "config/category_registry/delete",
                "scope": scope,
                "category_id": category_id,
            })
        except HAConnectionError as exc:
            logger.error(
                "ha_delete_category_ws_error",
                scope=scope, category_id=category_id, error=str(exc),
            )
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

        await complete_confirmation_token(
            confirmation_token, success=True, result={"result": "ok"}
        )
        logger.info("ha_delete_category_ok", scope=scope, category_id=category_id)
        return json.dumps({"result": "ok"})
