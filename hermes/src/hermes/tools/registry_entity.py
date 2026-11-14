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

# Sin opción explícita, el mismo tope que la configuración (spec 003): el
# antiguo 1 MiB supera lo que el cliente acepta en una respuesta.
from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes.ha import HAClient, HAConnectionError
from hermes.ha_version import ha_at_least
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    validate_confirmation_token,
)
from hermes.tools._validation import build_ws_payload
from hermes.tools._common import requires_ready
from hermes.tools.registry_device import devices_by_id, effective_area_id

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


# HA 2026.4 introduce el `null` dentro de `aliases` (nombre calculado).
_ALIASES_NULL_MIN_HA = "2026.4.0"


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
            # Desde HA 2026.4 un `null` dentro de la lista es el marcador del
            # nombre calculado y toda entidad nace con `[null]`: convertirlo
            # en el texto "None" creaba un alias falso y perdía el nombre al
            # reenviar lo leído. `aliases: null` a secas no lo admite el
            # esquema de HA (`[Any(str, None)]`), así que se rechaza aquí con
            # un mensaje útil en vez de dejar que HA falle.
            if not isinstance(v, list):
                return {}, (
                    "aliases must be a list; use [] to clear or [null] to keep "
                    "only the computed name"
                )
            if any(isinstance(a, (list, dict)) for a in v):
                return {}, "aliases items must be strings or null"
            out[k] = [a if a is None else str(a) for a in v]
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
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
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
            area_id:   Filtrar por área efectiva (string area_id de HA): la
                       propia de la entidad o, si no tiene, la de su
                       dispositivo (o la del padre de un dispositivo hijo).
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
            # Lo normal es que una entidad no tenga área propia y herede la de
            # su dispositivo (y un dispositivo hijo, la de su padre). Filtrar
            # solo por `area_id` propio dejaba fuera casi todo el área. El
            # registro de dispositivos solo se lee cuando hace falta.
            try:
                raw_devs: Any = await ha_client.ws_send(
                    {"type": "config/device_registry/list"}
                )
            except HAConnectionError as exc:
                logger.error("ha_list_entities_registry_ws_error", error=str(exc))
                return json.dumps({"error": str(exc)})
            by_id = devices_by_id(raw_devs)

            def _area_efectiva(e: dict) -> str | None:
                propia = e.get("area_id")
                if propia is not None:
                    return propia
                device = by_id.get(e.get("device_id"))
                return effective_area_id(device, by_id) if device else None

            items = [e for e in items if _area_efectiva(e) == area_id]
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
            # HA no devuelve `None` para una entidad inexistente: responde con
            # error `not_found`. Se decide por el código y no por el texto, que
            # HA puede cambiar o traducir.
            if exc.code == "not_found":
                return json.dumps({"error": "not_found", "entity_id": entity_id})
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
          name (str|null)        — Override del nombre de la entidad. null = usar
                                   original. Desde HA 2026.11 es solo la parte de
                                   la entidad: HA le antepone el nombre del
                                   dispositivo (p. ej. "Luz" en el dispositivo
                                   "Salón" se muestra "Salón Luz").
          icon (str|null)        — Override del icono. null = usar original.
          area_id (str|null)     — Asignar a área. null = desasignar.
          disabled_by (str|null|bool) — Deshabilitar/habilitar entidad.
                                    "user" o true → deshabilita.
                                    null o false  → habilita.
                                    Solo se puede cambiar a "user"/null vía API.
          hidden_by (str|null|bool)   — Ocultar/mostrar entidad. Mismo patrón.
          new_entity_id (str)    — DESTRUCTIVO: renombra el entity_id. Requiere
                                   confirmation_token.
          aliases (list[str|null]) — La lista sustituye a la anterior. Un null
                                   DENTRO de la lista es el nombre calculado de
                                   la entidad (HA 2026.4+; las entidades nacen
                                   con [null]). Para añadir un alias, lee los
                                   actuales y reenvíalos conservando el null
                                   (ej. [null, "lámpara"]). [] vacía la lista;
                                   [null] deja solo el nombre calculado.
                                   aliases: null (sin lista) se rechaza.
                                   En HA anterior a 2026.4 un null en la
                                   lista se rechaza
                                   (null_alias_requires_ha_2026_4), y también
                                   si no se puede leer la versión de HA.
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

        if None in normalized.get("aliases", []):
            # El `null` dentro de `aliases` solo existe desde HA 2026.4. En
            # 2024.10 HA lo guardaba tal cual y luego Assist fallaba al leerlo
            # (corrupción persistente); en 2026.3 daba `unknown_error`. Sin
            # versión no se puede saber cuál de los dos casos es: se niega.
            soporta = await ha_at_least(ha_client, _ALIASES_NULL_MIN_HA)
            if soporta is None:
                return json.dumps({
                    "error": "ha_version_unknown",
                    "detail": "Could not read the Home Assistant version; a "
                              "null alias is only valid on 2026.4 or newer.",
                })
            if not soporta:
                return json.dumps({
                    "error": "null_alias_requires_ha_2026_4",
                    "detail": "This Home Assistant is older than 2026.4 and "
                              "does not accept null inside aliases: send only "
                              "strings.",
                })

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
