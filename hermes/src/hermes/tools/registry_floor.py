"""Hermes — Tools MCP para Floor Registry (plantas).

Usa los comandos WS `config/floor_registry/{list,create,update,delete}`, que
existen con los mismos campos desde 2024.10.0 (el mínimo de Hermes), así que
no hace falta comprobar versión.

Campos de una planta: floor_id (slug generado por HA), name, level (int o
null), icon, aliases (lista de textos), created_at, modified_at.

Este módulo también alberga los ayudantes de vista previa que comparten
`registry_label` y `registry_category` (lectura fail-closed, acotado de listas
y referencias de `search/related`). Viven aquí, y no en un módulo común nuevo,
porque los tres registros se implementan juntos y así no se crea un fichero
fuera de los que les corresponden.
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

logger = structlog.get_logger(__name__)

# Máximo de ids por tipo en una vista previa. El recuento siempre es el real:
# lo que se recorta es la enumeración, para no agotar el contexto del agente
# con una planta de cien áreas, sin esconder cuántas son.
MAX_IDS_PREVIEW = 50

# Tipos de `search/related` que pueden usar una planta o etiqueta como destino.
# Son los únicos que Home Assistant NO edita al borrar: sus destinos dejan de
# resolver en silencio. Las áreas, dispositivos y entidades que también
# devuelve `search/related` se descartan aquí porque su asignación se calcula
# desde los registros, que es lo que HA sí limpiará.
_TIPOS_REFERENCIA = ("automation", "script", "scene")

_FLOOR_FIELDS = ("name", "level", "icon", "aliases")


# ── Ayudantes compartidos (también los usan etiquetas y categorías) ─────────


class LecturaFallida(Exception):
    """Una lectura necesaria para la vista previa falló o llegó con forma rara.

    Se usa para cortar la vista previa entera: con un dato que falta, la
    vista previa mentiría por omisión («0 áreas») y el humano confirmaría un
    borrado creyendo que no afecta a nada. Por eso no se emite token.
    """


def invalid_argument(field: str, detail: str) -> dict[str, str]:
    """Error de validación estándar: se devuelve sin llamar a Home Assistant."""
    return {"error": "invalid_argument", "field": field, "detail": detail}


def preview_unavailable(id_field: str, id_value: str, detail: str) -> str:
    """Respuesta fail-closed: sin vista previa veraz, no hay token."""
    return json.dumps(
        {"error": "preview_unavailable", id_field: id_value, "detail": detail},
        ensure_ascii=False,
    )


def acotar(ids: list[str], limite: int = MAX_IDS_PREVIEW) -> dict[str, Any]:
    """Recuento exacto y como mucho `limite` ids, con `truncated` si sobran."""
    return {"count": len(ids), "ids": ids[:limite], "truncated": len(ids) > limite}


async def leer_lista(
    ha_client: HAClient, command: str, extra: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Lee un registro y exige una lista de dicts; si no, `LecturaFallida`.

    No se tolera un elemento que no sea dict: aceptar la lista «limpiando» lo
    raro haría que la vista previa contara de menos sin decirlo.
    """
    payload: dict[str, Any] = {"type": command, **(extra or {})}
    try:
        raw: Any = await ha_client.ws_send(payload)
    except HAConnectionError as exc:
        raise LecturaFallida(f"{command} failed: {exc}") from exc
    if not isinstance(raw, list) or not all(isinstance(e, dict) for e in raw):
        raise LecturaFallida(f"{command} returned an unexpected shape")
    return raw


async def buscar_entrada(
    ha_client: HAClient,
    command: str,
    id_field: str,
    id_value: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Devuelve la entrada del registro con ese id, o None si no existe."""
    entradas = await leer_lista(ha_client, command, extra)
    return next((e for e in entradas if e.get(id_field) == id_value), None)


def ids_con_etiqueta(
    entradas: list[dict[str, Any]], id_field: str, campo: str, valor: str
) -> list[str]:
    """Ids de las entradas cuya lista `campo` contiene `valor`.

    Un `campo` que no sea lista es una forma inesperada: se falla cerrado.
    """
    ids: list[str] = []
    for e in entradas:
        lista = e.get(campo) or []
        if not isinstance(lista, list):
            raise LecturaFallida(f"{campo} of {e.get(id_field)!r} is not a list")
        if valor in lista:
            ids.append(str(e.get(id_field)))
    return ids


async def referencias_sin_resolver(
    ha_client: HAClient, item_type: str, item_id: str
) -> dict[str, dict[str, Any]]:
    """Automatizaciones, scripts y escenas que usan el elemento como destino.

    Llama a `search/related` directamente en vez de importar la tool del
    bloque de diagnóstico: los dos se desarrollan en paralelo y así ninguno
    depende del otro (son cinco líneas).
    """
    try:
        raw: Any = await ha_client.ws_send(
            {"type": "search/related", "item_type": item_type, "item_id": item_id}
        )
    except HAConnectionError as exc:
        raise LecturaFallida(f"search/related failed: {exc}") from exc
    if not isinstance(raw, dict):
        raise LecturaFallida("search/related returned an unexpected shape")
    out: dict[str, dict[str, Any]] = {}
    for tipo in _TIPOS_REFERENCIA:
        ids = raw.get(tipo) or []
        if not isinstance(ids, list):
            raise LecturaFallida(f"search/related {tipo} is not a list")
        out[tipo] = acotar([str(i) for i in ids])
    return out


def plural(n: int, singular: str, plural_: str) -> str:
    return f"{n} {singular if n == 1 else plural_}"


def frase_referencias(refs: dict[str, dict[str, Any]], que: str) -> str:
    """Frase del aviso sobre los destinos que HA no editará."""
    return (
        f"{plural(refs['automation']['count'], 'automation', 'automations')}, "
        f"{plural(refs['script']['count'], 'script', 'scripts')} and "
        f"{plural(refs['scene']['count'], 'scene', 'scenes')} that target this "
        f"{que} will no longer match anything; Home Assistant does not edit them."
    )


# ── Validación de plantas ───────────────────────────────────────────────────


def _validate_floor_fields(
    fields: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str] | None]:
    """Valida y normaliza campos de planta antes de enviar nada a HA.

    `level` rechaza booleanos a propósito: en Python `True` es un `int` y HA
    lo guardaría como planta 1 sin quejarse.
    """
    out: dict[str, Any] = {}
    for k, v in fields.items():
        if k == "name":
            if not isinstance(v, str) or not v.strip():
                return {}, invalid_argument("name", "must be a non-empty string")
            out[k] = v.strip()
        elif k == "level":
            if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
                return {}, invalid_argument("level", "must be an integer or null")
            out[k] = v
        elif k == "icon":
            if v is not None and not isinstance(v, str):
                return {}, invalid_argument("icon", "must be a string or null")
            out[k] = v
        elif k == "aliases":
            if not isinstance(v, list) or not all(isinstance(a, str) for a in v):
                return {}, invalid_argument("aliases", "must be a list of strings")
            out[k] = [a.strip() for a in v if a.strip()]
        else:
            return {}, invalid_argument(
                k, f"unknown field; allowed: {', '.join(_FLOOR_FIELDS)}"
            )
    return out, None


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de floor registry."""

    ready = requires_ready(ha_client)

    # ── ha_list_floors ────────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_floors() -> object:
        """List all floors in the floor registry.

        Returns:
            JSON {"count": n, "floors": [{"floor_id", "name", "level",
            "icon", "aliases", ...}, ...]}
        """
        try:
            raw: Any = await ha_client.ws_send({"type": "config/floor_registry/list"})
        except HAConnectionError as exc:
            logger.error("ha_list_floors_ws_error", error=str(exc))
            return json.dumps({"error": str(exc)})
        items: list[dict] = raw if isinstance(raw, list) else []
        logger.info("ha_list_floors_ok", count=len(items))
        return json.dumps({"count": len(items), "floors": items}, ensure_ascii=False)

    # ── ha_create_floor ───────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_create_floor(
        name: str,
        level: int | None = None,
        icon: str | None = None,
        aliases: list[str] | None = None,
    ) -> object:
        """Create a floor. No confirmation needed (nothing is lost).

        Home Assistant generates `floor_id` from the name. A duplicate name is
        rejected by Home Assistant and returned as {"error": "..."}.

        Args:
            name:    Floor name, e.g. "Ground floor".
            level:   Integer level (0 = ground, negative = basement). Optional.
            icon:    MDI icon, e.g. "mdi:home-floor-0". Optional.
            aliases: Alternative names for Assist. Empty strings are dropped.

        Returns:
            JSON with the created entry, including the generated floor_id.
        """
        fields: dict[str, Any] = {"name": name}
        if level is not None:
            fields["level"] = level
        if icon is not None:
            fields["icon"] = icon
        if aliases is not None:
            fields["aliases"] = aliases
        normalized, err = _validate_floor_fields(fields)
        if err:
            return json.dumps(err)

        payload = build_ws_payload("config/floor_registry/create", {}, normalized)
        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            # Sin reintento: un nombre duplicado no se arregla repitiendo.
            logger.error("ha_create_floor_ws_error", error=str(exc))
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        logger.info(
            "ha_create_floor_ok",
            floor_id=raw.get("floor_id") if isinstance(raw, dict) else None,
        )
        return json.dumps(raw, ensure_ascii=False)

    # ── ha_update_floor ───────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_update_floor(
        floor_id: str,
        updates: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Edit an existing floor (it does not create one). Two-step confirmation.

        Renaming a floor changes how Assist and the UI refer to it, so the
        first call returns a preview (current entry + proposed changes) and a
        confirmation_token; repeat the same call with the token to apply.

        Args:
            floor_id:           Floor to edit.
            updates:            Any of: name (str), level (int|null),
                                icon (str|null), aliases (list[str]).
            confirmation_token: Token from the preview call.

        Returns:
            Without token: {"confirmation_token", "preview": {"floor_id",
            "current", "proposed_changes"}}; errors not_found or
            preview_unavailable (no token). With token: {"result": "ok", ...}.
        """
        try:
            validate_identifier(floor_id, field="floor_id")
        except InvalidIdentifier as exc:
            return json.dumps(identifier_error(exc))
        if not isinstance(updates, dict):
            return json.dumps(invalid_argument("updates", "must be an object"))
        normalized, err = _validate_floor_fields(updates)
        if err:
            return json.dumps(err)
        if not normalized:
            return json.dumps({"error": "updates is empty"})

        args = {"floor_id": floor_id, "updates": normalized}

        if not confirmation_token:
            # Fail-closed (a diferencia de ha_update_area, que emite token con
            # `current: null`): sin el estado actual el humano no puede ver qué
            # está cambiando, y la vista previa es su única revisión.
            try:
                current = await buscar_entrada(
                    ha_client, "config/floor_registry/list", "floor_id", floor_id
                )
            except LecturaFallida as exc:
                logger.warning("ha_update_floor_preview_unavailable", floor_id=floor_id)
                return preview_unavailable("floor_id", floor_id, str(exc))
            if current is None:
                return json.dumps({"error": "not_found", "floor_id": floor_id})
            preview = {
                "floor_id": floor_id,
                "current": current,
                "proposed_changes": normalized,
            }
            token_data = await create_confirmation_token(
                "ha_update_floor", args, preview=preview
            )
            return json.dumps(token_data, ensure_ascii=False)

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_update_floor", args
        )
        if not valid:
            logger.warning("ha_update_floor_token_invalid", floor_id=floor_id, reason=error)
            return json.dumps({"error": error})

        payload = build_ws_payload(
            "config/floor_registry/update", {"floor_id": floor_id}, normalized
        )
        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            logger.error("ha_update_floor_ws_error", floor_id=floor_id, error=str(exc))
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

        await complete_confirmation_token(confirmation_token, success=True, result=raw)
        logger.info("ha_update_floor_ok", floor_id=floor_id)
        result: dict[str, Any] = {"result": "ok"}
        if isinstance(raw, dict):
            result.update(raw)
        return json.dumps(result, ensure_ascii=False)

    # ── ha_delete_floor ───────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_delete_floor(
        floor_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Delete a floor. Two-step confirmation with an impact preview.

        Home Assistant sets floor_id to null on the floor's areas. Automations,
        scripts and scenes that target the floor are NOT edited: their targets
        silently stop matching. The preview lists both separately
        (assignments_removed vs references_unresolved), up to 50 ids per type
        with the exact count. If any read fails, no token is issued
        (preview_unavailable).

        Args:
            floor_id:           Floor to delete.
            confirmation_token: Token from the preview call.

        Returns:
            Without token: {"confirmation_token", "preview": {"floor_id",
            "current", "impact": {"assignments_removed": {"areas"},
            "references_unresolved": {"automation", "script", "scene"}},
            "warning"}}. With token: {"result": "ok"}.
        """
        try:
            validate_identifier(floor_id, field="floor_id")
        except InvalidIdentifier as exc:
            return json.dumps(identifier_error(exc))

        args = {"floor_id": floor_id}

        if not confirmation_token:
            try:
                current = await buscar_entrada(
                    ha_client, "config/floor_registry/list", "floor_id", floor_id
                )
                if current is None:
                    return json.dumps({"error": "not_found", "floor_id": floor_id})
                impact = await _impacto_planta(ha_client, floor_id)
            except LecturaFallida as exc:
                logger.warning("ha_delete_floor_preview_unavailable", floor_id=floor_id)
                return preview_unavailable("floor_id", floor_id, str(exc))

            n_areas = impact["assignments_removed"]["areas"]["count"]
            preview = {
                "floor_id": floor_id,
                "current": current,
                "impact": impact,
                "warning": (
                    f"Deleting this floor sets floor_id to null on "
                    f"{plural(n_areas, 'area', 'areas')}. "
                    + frase_referencias(impact["references_unresolved"], "floor")
                ),
            }
            token_data = await create_confirmation_token(
                "ha_delete_floor", args, preview=preview
            )
            return json.dumps(token_data, ensure_ascii=False)

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_delete_floor", args
        )
        if not valid:
            logger.warning("ha_delete_floor_token_invalid", floor_id=floor_id, reason=error)
            return json.dumps({"error": error})

        try:
            await ha_client.ws_send(
                {"type": "config/floor_registry/delete", "floor_id": floor_id}
            )
        except HAConnectionError as exc:
            logger.error("ha_delete_floor_ws_error", floor_id=floor_id, error=str(exc))
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

        await complete_confirmation_token(
            confirmation_token, success=True, result={"result": "ok"}
        )
        logger.info("ha_delete_floor_ok", floor_id=floor_id)
        return json.dumps({"result": "ok"})


async def _impacto_planta(ha_client: HAClient, floor_id: str) -> dict[str, Any]:
    """Qué pierde la asignación y qué deja de resolver al borrar la planta.

    Las áreas salen del registro de áreas (lo que HA pondrá a null); las
    referencias, de `search/related` (lo que HA no tocará).
    """
    areas = await leer_lista(ha_client, "config/area_registry/list")
    ids_areas = [str(a.get("area_id")) for a in areas if a.get("floor_id") == floor_id]
    return {
        "assignments_removed": {"areas": acotar(ids_areas)},
        "references_unresolved": await referencias_sin_resolver(
            ha_client, "floor", floor_id
        ),
    }
