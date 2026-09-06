"""Hermes — Tools MCP para Entity Registry.

Usa los comandos WS `config/entity_registry/*` de HA.
Estos operan sobre el registry persistido, no sobre el estado en tiempo real.

Campos clave de una entry del entity registry:
  entity_id, unique_id, platform, device_id, area_id, name (override del
  friendly_name), icon, disabled_by, hidden_by, aliases, labels, categories,
  original_name, original_icon, device_class, entity_category, unit_of_measurement.

disabled_by / hidden_by son enum strings, no booleanos:
  - disabled_by: "user" | "integration" | "device" | "config_entry" | "hass" | null
  - hidden_by:   "user" | "integration" | null
  Vía API solo se puede cambiar a "user" o null (los otros los gestiona HA).
  Como conveniencia, True → "user", False → null.
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
from hermes.tools._validation import build_ws_payload
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)

# Campos de disabled_by / hidden_by que la API permite cambiar
_DISABLER_USER = "user"

# Campos destructivos que requieren token aunque no sean remove
_TOKEN_REQUIRED_FIELDS = {"disabled_by", "new_entity_id"}


def _coerce_flag(val: Any, field: str) -> str | None:
    """Convierte bool conveniente a enum string esperado por HA.

    True  → "user"   (activa la restricción por el usuario)
    False → None     (desactiva)
    "user" → "user"  (pass-through)
    None  → None     (pass-through)
    Cualquier otro string → error (lo llama el validador del payload)
    """
    if isinstance(val, bool):
        return _DISABLER_USER if val else None
    return val


def _validate_updates(updates: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Valida y normaliza el dict de updates para entity registry.

    Returns (normalized_updates, error_message_or_None).
    """
    out: dict[str, Any] = {}
    for k, v in updates.items():
        if k == "disabled_by":
            coerced = _coerce_flag(v, k)
            if coerced not in (None, "user"):
                return {}, f"disabled_by must be 'user', null, true or false; got {v!r}"
            out[k] = coerced
        elif k == "hidden_by":
            coerced = _coerce_flag(v, k)
            if coerced not in (None, "user"):
                return {}, f"hidden_by must be 'user', null, true or false; got {v!r}"
            out[k] = coerced
        elif k == "aliases":
            if v is not None and not isinstance(v, list):
                return {}, "aliases must be a list of strings or null"
            out[k] = [str(a) for a in v] if v is not None else v
        elif k == "labels":
            if not isinstance(v, list):
                return {}, "labels must be a list of strings"
            out[k] = [str(lbl) for lbl in v]
        elif k in ("name", "icon", "area_id", "device_class", "new_entity_id"):
            out[k] = v  # str or None — HA handles it
        elif k in ("categories",):
            if v is not None and not isinstance(v, dict):
                return {}, "categories must be a dict or null"
            out[k] = v
        elif k in ("options_domain", "options"):
            out[k] = v
        else:
            # Pass unknown fields through — HA will validate
            out[k] = v
    return out, None


def _needs_token(updates: dict[str, Any]) -> bool:
    """True si el update contiene al menos un campo destructivo."""
    return bool(set(updates) & _TOKEN_REQUIRED_FIELDS)


def register(
    mcp: object,
    ha_client: HAClient,
    response_max_bytes: int = 1_048_576,
) -> None:
    """Registra las tools de entity registry."""

    ready = requires_ready(ha_client)

    # ── ha_list_entities_registry ─────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_entities_registry(
        area_id: str | None = None,
        device_id: str | None = None,
        platform: str | None = None,
        disabled: bool | None = None,
    ) -> object:
        """Lista entries del entity registry con filtros opcionales.

        El entity registry contiene TODAS las entidades conocidas por HA,
        incluyendo las deshabilitadas. Es distinto de ha_get_states que solo
        devuelve entidades activas.

        Sin filtros puede devolver miles de entries — usa los filtros para
        acotar.

        Args:
            area_id:   Filtrar por area asignada (string area_id de HA).
                       Si se omite, no se filtra por área.
            device_id: Filtrar por device_id (UUID del device registry).
            platform:  Filtrar por plataforma de integración (ej. "mqtt",
                       "zha", "homekit_controller").
            disabled:  True → solo deshabilitadas, False → solo habilitadas,
                       None → todas.

        Returns:
            JSON con {
              "count": int,
              "entities": [
                {
                  "entity_id": "sensor.temperatura",
                  "platform": "mqtt",
                  "device_id": "abc123",
                  "area_id": "salon",
                  "name": null,           // override de nombre (null = usa original)
                  "original_name": "Temperatura",
                  "icon": null,
                  "disabled_by": null,    // null | "user" | "integration" | ...
                  "hidden_by": null,
...
                }, ...
              ],
              "truncated": bool
            }
        """
        try:
            raw: Any = await ha_client.ws_send(
                {"type": "config/entity_registry/list"}
            )
        except HAConnectionError as exc:
            logger.error("ha_list_entities_registry_ws_error", error=str(exc))
            return json.dumps({"error": str(exc)})

        items: list[dict] = raw if isinstance(raw, list) else []

        # Apply filters
        if area_id is not None:
            items = [e for e in items if e.get("area_id") == area_id]
        if device_id is not None:
            items = [e for e in items if e.get("device_id") == device_id]
        if platform is not None:
            items = [e for e in items if e.get("platform") == platform]
        if disabled is True:
            items = [e for e in items if e.get("disabled_by") is not None]
        elif disabled is False:
            items = [e for e in items if e.get("disabled_by") is None]

        # Truncate by bytes
        truncated = False
        serialized = json.dumps(items, ensure_ascii=False)
        if len(serialized.encode()) > response_max_bytes:
            truncated = True
            while items and len(
                json.dumps(items, ensure_ascii=False).encode()
            ) > response_max_bytes:
                items.pop()

        logger.info(
            "ha_list_entities_registry_ok",
            count=len(items),
            truncated=truncated,
        )
        return json.dumps(
            {"count": len(items), "entities": items, "truncated": truncated},
            ensure_ascii=False,
        )

    # ── ha_get_entity_registry ────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_get_entity_registry(entity_id: str) -> object:
        """Devuelve la entry completa del entity registry para una entidad.

        Devuelve los datos del REGISTRY (nombre override, área asignada,
        disabled_by, unique_id, device_id…), NO el estado en tiempo real.
        Para el estado actual usa ha_get_state.

        Args:
            entity_id: ID de la entidad (ej. "sensor.temperatura_salon").

        Returns:
            JSON con la entry extendida del registry, o {"error": "not_found"}.
        """
        try:
            raw: Any = await ha_client.ws_send(
                {"type": "config/entity_registry/get", "entity_id": entity_id}
            )
        except HAConnectionError as exc:
            logger.error(
                "ha_get_entity_registry_ws_error",
                entity_id=entity_id,
                error=str(exc),
            )
            return json.dumps({"error": str(exc)})

        if raw is None:
            return json.dumps({"error": "not_found", "entity_id": entity_id})

        logger.info("ha_get_entity_registry_ok", entity_id=entity_id)
        return json.dumps(raw, ensure_ascii=False)

    # ── ha_update_entity_registry ─────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_update_entity_registry(
        entity_id: str,
        updates: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Actualiza parcialmente una entry del entity registry.

        Permite cambiar nombre, icono, área, deshabilitar/ocultar la entidad,
        renombrarla (new_entity_id), gestionar aliases y labels.

        Campos soportados en `updates`:
          name (str|null)        — Override del nombre mostrado. null = usar original.
          icon (str|null)        — Override del icono. null = usar original.
          area_id (str|null)     — Asignar a área. null = desasignar.
          disabled_by (str|null|bool) — Deshabilitar/habilitar entidad.
                                    "user" o true → deshabilita.
                                    null o false  → habilita.
                                    Solo se puede cambiar a "user"/null vía API.
          hidden_by (str|null|bool)   — Ocultar/mostrar entidad. Mismo patrón.
          new_entity_id (str)    — DESTRUCTIVO: renombra el entity_id. Requiere
                                   confirmation_token.
          aliases (list[str]|null) — Lista de aliases. null = limpiar aliases.
          labels (list[str])     — Lista de labels.
          device_class (str|null) — Override del device class.
          categories (dict)      — Categorías por scope.

        El confirmation_token es SIEMPRE obligatorio: sin él, cualquier
        `updates` devuelve preview + token en vez de aplicarse. Que el update
        contenga `disabled_by` o `new_entity_id` no cambia eso; solo marca
        `preview["destructive"] = true` para que el cliente avise más fuerte.

        Args:
            entity_id:          ID de la entidad a actualizar.
            updates:            Dict con los campos a cambiar.
            confirmation_token: Token obtenido en llamada previa sin token.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token válido: {"result": "ok", "entity_entry": {...}}
            Error: {"error": "..."}
        """
        normalized, err = _validate_updates(updates)
        if err:
            return json.dumps({"error": err})

        if not normalized:
            return json.dumps({"error": "updates is empty"})

        args = {"entity_id": entity_id, "updates": normalized}
        requires_token = _needs_token(normalized)

        # Preview / token generation
        if not confirmation_token:
            try:
                current_raw: Any = await ha_client.ws_send(
                    {"type": "config/entity_registry/get", "entity_id": entity_id}
                )
            except HAConnectionError as exc:
                current_raw = None
                logger.warning(
                    "ha_update_entity_registry_preview_read_failed",
                    entity_id=entity_id,
                    error=str(exc),
                )

            preview = {
                "entity_id": entity_id,
                "current": current_raw,
                "proposed_changes": normalized,
                "requires_confirmation": True,
                "destructive": requires_token,
            }
            token_data = await create_confirmation_token(
                "ha_update_entity_registry", args, preview=preview
            )
            return json.dumps(token_data, ensure_ascii=False)

        # Validate token
        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_update_entity_registry", args
        )
        if not valid:
            logger.warning(
                "ha_update_entity_registry_token_invalid",
                entity_id=entity_id,
                reason=error,
            )
            return json.dumps({"error": error})

        # Build WS payload
        payload = build_ws_payload(
            "config/entity_registry/update",
            {"entity_id": entity_id},
            normalized,
        )

        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            logger.error(
                "ha_update_entity_registry_ws_error",
                entity_id=entity_id,
                error=str(exc),
            )
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return json.dumps({"error": str(exc)})

        await complete_confirmation_token(
            confirmation_token, success=True, result=raw
        )
        logger.info("ha_update_entity_registry_ok", entity_id=entity_id)

        # raw is {"entity_entry": {...}, "require_restart": bool (optional)}
        result: dict[str, Any] = {"result": "ok"}
        if isinstance(raw, dict):
            result.update(raw)
        return json.dumps(result, ensure_ascii=False)

    # ── ha_remove_entity_registry ─────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_remove_entity_registry(
        entity_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina una entry del entity registry.

        IMPORTANTE: esto NO elimina el dispositivo físico ni desinstala la
        integración. Solo borra la entry del registry. Si el dispositivo
        físico sigue activo, HA recrea la entry automáticamente en el próximo
        descubrimiento o reinicio de la integración.

        Casos de uso legítimos:
          - Limpiar orphaned entries de dispositivos que ya no existen.
          - Forzar re-descubrimiento de una entidad.

        Siempre requiere confirmation_token.

        Args:
            entity_id:          ID de la entidad a eliminar del registry.
            confirmation_token: Token obtenido en llamada previa sin token.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token válido: {"result": "ok"}
            Error: {"error": "..."}
        """
        args = {"entity_id": entity_id}

        if not confirmation_token:
            try:
                current_raw: Any = await ha_client.ws_send(
                    {"type": "config/entity_registry/get", "entity_id": entity_id}
                )
            except HAConnectionError:
                current_raw = None

            preview = {
                "entity_id": entity_id,
                "current": current_raw,
                "warning": (
                    "This removes the registry entry only. If the physical device "
                    "is still active, HA will recreate it on next integration reload."
                ),
            }
            token_data = await create_confirmation_token(
                "ha_remove_entity_registry", args, preview=preview
            )
            return json.dumps(token_data, ensure_ascii=False)

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_remove_entity_registry", args
        )
        if not valid:
            logger.warning(
                "ha_remove_entity_registry_token_invalid",
                entity_id=entity_id,
                reason=error,
            )
            return json.dumps({"error": error})

        try:
            await ha_client.ws_send(
                {"type": "config/entity_registry/remove", "entity_id": entity_id}
            )
        except HAConnectionError as exc:
            logger.error(
                "ha_remove_entity_registry_ws_error",
                entity_id=entity_id,
                error=str(exc),
            )
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return json.dumps({"error": str(exc)})

        await complete_confirmation_token(
            confirmation_token, success=True, result={"result": "ok"}
        )
        logger.info("ha_remove_entity_registry_ok", entity_id=entity_id)
        return json.dumps({"result": "ok"})
