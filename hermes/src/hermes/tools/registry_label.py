"""Hermes — Tools MCP para Label Registry (etiquetas).

Usa los comandos WS `config/label_registry/{list,create,update,delete}`,
presentes con los mismos campos desde 2024.10.0.

Campos de una etiqueta: label_id (slug generado por HA), name, color, icon,
description, created_at, modified_at.

Al borrar una etiqueta, Home Assistant la quita de áreas, dispositivos y
entidades (comprobado en `helpers/area_registry.py`, que escucha el borrado en
el registro de etiquetas igual que los otros dos registros). Las
automatizaciones, scripts y escenas que la usan como destino no se editan.
"""

from __future__ import annotations

import json
import re
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
    frase_referencias,
    ids_con_etiqueta,
    invalid_argument,
    leer_lista,
    plural,
    preview_unavailable,
    referencias_sin_resolver,
)

logger = structlog.get_logger(__name__)

# Colores de tema que admite HA para etiquetas (SUPPORTED_LABEL_THEME_COLORS).
# Se validan aquí para dar un error claro sin ida y vuelta a Home Assistant.
_THEME_COLORS = frozenset({
    "primary", "accent", "disabled", "red", "pink", "purple", "deep-purple",
    "indigo", "blue", "light-blue", "cyan", "teal", "green", "light-green",
    "lime", "yellow", "amber", "orange", "deep-orange", "brown", "light-grey",
    "grey", "dark-grey", "blue-grey", "black", "white",
})
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

_LABEL_FIELDS = ("name", "color", "icon", "description")


def _validate_label_fields(
    fields: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str] | None]:
    """Valida y normaliza campos de etiqueta antes de enviar nada a HA."""
    out: dict[str, Any] = {}
    for k, v in fields.items():
        if k == "name":
            if not isinstance(v, str) or not v.strip():
                return {}, invalid_argument("name", "must be a non-empty string")
            out[k] = v.strip()
        elif k == "color":
            if v is not None and not (
                isinstance(v, str) and (v in _THEME_COLORS or _HEX_COLOR_RE.match(v))
            ):
                return {}, invalid_argument(
                    "color",
                    "must be null, '#rrggbb' or one of: " + ", ".join(sorted(_THEME_COLORS)),
                )
            out[k] = v
        elif k in ("icon", "description"):
            if v is not None and not isinstance(v, str):
                return {}, invalid_argument(k, "must be a string or null")
            out[k] = v
        else:
            return {}, invalid_argument(
                k, f"unknown field; allowed: {', '.join(_LABEL_FIELDS)}"
            )
    return out, None


async def _impacto_etiqueta(ha_client: HAClient, label_id: str) -> dict[str, Any]:
    """Qué pierde la etiqueta y qué deja de resolver al borrarla.

    Se leen los tres registros (no `search/related`) para las asignaciones
    porque son la fuente de verdad de lo que HA limpiará; los dispositivos se
    identifican por `id` y las entidades por `entity_id`.
    """
    areas = await leer_lista(ha_client, "config/area_registry/list")
    devices = await leer_lista(ha_client, "config/device_registry/list")
    entities = await leer_lista(ha_client, "config/entity_registry/list")
    return {
        "assignments_removed": {
            "areas": acotar(ids_con_etiqueta(areas, "area_id", "labels", label_id)),
            "devices": acotar(ids_con_etiqueta(devices, "id", "labels", label_id)),
            "entities": acotar(ids_con_etiqueta(entities, "entity_id", "labels", label_id)),
        },
        "references_unresolved": await referencias_sin_resolver(
            ha_client, "label", label_id
        ),
    }


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de label registry."""

    ready = requires_ready(ha_client)

    # ── ha_list_labels ────────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_labels() -> object:
        """List all labels in the label registry.

        Returns:
            JSON {"count": n, "labels": [{"label_id", "name", "color",
            "icon", "description", ...}, ...]}
        """
        try:
            raw: Any = await ha_client.ws_send({"type": "config/label_registry/list"})
        except HAConnectionError as exc:
            logger.error("ha_list_labels_ws_error", error=str(exc))
            return json.dumps({"error": str(exc)})
        items: list[dict] = raw if isinstance(raw, list) else []
        logger.info("ha_list_labels_ok", count=len(items))
        return json.dumps({"count": len(items), "labels": items}, ensure_ascii=False)

    # ── ha_create_label ───────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_create_label(
        name: str,
        color: str | None = None,
        icon: str | None = None,
        description: str | None = None,
    ) -> object:
        """Create a label. No confirmation needed (nothing is lost).

        Home Assistant generates `label_id` from the name.

        Args:
            name:        Label name.
            color:       A theme color (primary, accent, disabled, red, pink,
                         purple, deep-purple, indigo, blue, light-blue, cyan,
                         teal, green, light-green, lime, yellow, amber, orange,
                         deep-orange, brown, light-grey, grey, dark-grey,
                         blue-grey, black, white) or "#rrggbb". Optional.
            icon:        MDI icon, e.g. "mdi:tag". Optional.
            description: Free text. Optional.

        Returns:
            JSON with the created entry, including the generated label_id.
        """
        fields: dict[str, Any] = {"name": name}
        for clave, valor in (("color", color), ("icon", icon), ("description", description)):
            if valor is not None:
                fields[clave] = valor
        normalized, err = _validate_label_fields(fields)
        if err:
            return json.dumps(err)

        payload = build_ws_payload("config/label_registry/create", {}, normalized)
        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            logger.error("ha_create_label_ws_error", error=str(exc))
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        logger.info(
            "ha_create_label_ok",
            label_id=raw.get("label_id") if isinstance(raw, dict) else None,
        )
        return json.dumps(raw, ensure_ascii=False)

    # ── ha_update_label ───────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_update_label(
        label_id: str,
        updates: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Edit an existing label (it does not create one). Two-step confirmation.

        The first call returns a preview (current entry + proposed changes)
        and a confirmation_token; repeat the same call with the token to apply.

        Args:
            label_id:           Label to edit.
            updates:            Any of: name (str), color (theme color,
                                "#rrggbb" or null), icon (str|null),
                                description (str|null).
            confirmation_token: Token from the preview call.

        Returns:
            Without token: {"confirmation_token", "preview": {"label_id",
            "current", "proposed_changes"}}; errors not_found or
            preview_unavailable (no token). With token: {"result": "ok", ...}.
        """
        try:
            validate_identifier(label_id, field="label_id")
        except InvalidIdentifier as exc:
            return json.dumps(identifier_error(exc))
        if not isinstance(updates, dict):
            return json.dumps(invalid_argument("updates", "must be an object"))
        normalized, err = _validate_label_fields(updates)
        if err:
            return json.dumps(err)
        if not normalized:
            return json.dumps({"error": "updates is empty"})

        args = {"label_id": label_id, "updates": normalized}

        if not confirmation_token:
            # Fail-closed: sin el estado actual la vista previa no sirve de
            # revisión, así que no se emite token.
            try:
                current = await buscar_entrada(
                    ha_client, "config/label_registry/list", "label_id", label_id
                )
            except LecturaFallida as exc:
                logger.warning("ha_update_label_preview_unavailable", label_id=label_id)
                return preview_unavailable("label_id", label_id, str(exc))
            if current is None:
                return json.dumps({"error": "not_found", "label_id": label_id})
            preview = {
                "label_id": label_id,
                "current": current,
                "proposed_changes": normalized,
            }
            token_data = await create_confirmation_token(
                "ha_update_label", args, preview=preview
            )
            return json.dumps(token_data, ensure_ascii=False)

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_update_label", args
        )
        if not valid:
            logger.warning("ha_update_label_token_invalid", label_id=label_id, reason=error)
            return json.dumps({"error": error})

        payload = build_ws_payload(
            "config/label_registry/update", {"label_id": label_id}, normalized
        )
        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            logger.error("ha_update_label_ws_error", label_id=label_id, error=str(exc))
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

        await complete_confirmation_token(confirmation_token, success=True, result=raw)
        logger.info("ha_update_label_ok", label_id=label_id)
        result: dict[str, Any] = {"result": "ok"}
        if isinstance(raw, dict):
            result.update(raw)
        return json.dumps(result, ensure_ascii=False)

    # ── ha_delete_label ───────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_delete_label(
        label_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Delete a label. Two-step confirmation with an impact preview.

        Home Assistant removes the label from areas, devices and entities.
        Automations, scripts and scenes that target the label are NOT edited:
        their targets silently stop matching. The preview lists both, per
        type, up to 50 ids each with the exact count. If any read fails, no
        token is issued (preview_unavailable).

        Args:
            label_id:           Label to delete.
            confirmation_token: Token from the preview call.

        Returns:
            Without token: {"confirmation_token", "preview": {"label_id",
            "current", "impact": {"assignments_removed": {"areas", "devices",
            "entities"}, "references_unresolved": {"automation", "script",
            "scene"}}, "warning"}}. With token: {"result": "ok"}.
        """
        try:
            validate_identifier(label_id, field="label_id")
        except InvalidIdentifier as exc:
            return json.dumps(identifier_error(exc))

        args = {"label_id": label_id}

        if not confirmation_token:
            try:
                current = await buscar_entrada(
                    ha_client, "config/label_registry/list", "label_id", label_id
                )
                if current is None:
                    return json.dumps({"error": "not_found", "label_id": label_id})
                impact = await _impacto_etiqueta(ha_client, label_id)
            except LecturaFallida as exc:
                logger.warning("ha_delete_label_preview_unavailable", label_id=label_id)
                return preview_unavailable("label_id", label_id, str(exc))

            asign = impact["assignments_removed"]
            preview = {
                "label_id": label_id,
                "current": current,
                "impact": impact,
                "warning": (
                    "Deleting this label removes it from "
                    f"{plural(asign['areas']['count'], 'area', 'areas')}, "
                    f"{plural(asign['devices']['count'], 'device', 'devices')} and "
                    f"{plural(asign['entities']['count'], 'entity', 'entities')}. "
                    + frase_referencias(impact["references_unresolved"], "label")
                ),
            }
            token_data = await create_confirmation_token(
                "ha_delete_label", args, preview=preview
            )
            return json.dumps(token_data, ensure_ascii=False)

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_delete_label", args
        )
        if not valid:
            logger.warning("ha_delete_label_token_invalid", label_id=label_id, reason=error)
            return json.dumps({"error": error})

        try:
            await ha_client.ws_send(
                {"type": "config/label_registry/delete", "label_id": label_id}
            )
        except HAConnectionError as exc:
            logger.error("ha_delete_label_ws_error", label_id=label_id, error=str(exc))
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

        await complete_confirmation_token(
            confirmation_token, success=True, result={"result": "ok"}
        )
        logger.info("ha_delete_label_ok", label_id=label_id)
        return json.dumps({"result": "ok"})
