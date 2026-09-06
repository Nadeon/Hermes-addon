"""Hermes — Tools MCP para Config Entries.

Usa los comandos WS `config_entries/*` y REST `/api/config/config_entries/`
de Home Assistant.

Campos clave de una config entry:
  entry_id (str UUID), domain (str), title (str), source (str),
  state (str enum: loaded|setup_error|migration_error|setup_retry|not_loaded|
                   failed_unload|setup_in_progress|unload_in_progress),
  supports_options (bool), supports_remove_device (bool),
  supports_unload (bool), supports_reconfigure (bool),
  pref_disable_new_entities (bool), pref_disable_polling (bool),
  disabled_by ("user" | null),
  reason (str | null), error_reason_translation_key (str | null),
  num_subentries (int), created_at (str ISO), modified_at (str ISO).

Notas de implementación:
  - ha_reload_config_entry usa REST POST (no WS).
  - ha_delete_config_entry usa REST DELETE + confirmation_token.
  - ha_disable/enable_config_entry usan WS config_entries/disable con
    disabled_by: "user" (disable) o null (enable).
  - Sub-entries están fuera de alcance.
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
from hermes.tools._validation import InvalidIdentifier, validate_identifier

logger = structlog.get_logger(__name__)


async def _count_config_entry_dependents(
    ha_client: HAClient, entry_id: str
) -> dict[str, int]:
    """Cuenta entities y devices vinculados a un config_entry_id."""
    entities_count = 0
    devices_count = 0
    try:
        raw_ents: Any = await ha_client.ws_send(
            {"type": "config/entity_registry/list"}
        )
        if isinstance(raw_ents, list):
            entities_count = sum(
                1
                for e in raw_ents
                if entry_id in (e.get("config_entry_id") or "")
                or entry_id in (e.get("config_entries") or [])
            )
    except HAConnectionError:
        pass
    try:
        raw_devs: Any = await ha_client.ws_send(
            {"type": "config/device_registry/list"}
        )
        if isinstance(raw_devs, list):
            devices_count = sum(
                1
                for d in raw_devs
                if entry_id in (d.get("config_entries") or [])
            )
    except HAConnectionError:
        pass
    return {"entities": entities_count, "devices": devices_count}


def register(mcp: object, ha_client: HAClient, response_max_bytes: int = 1_048_576) -> None:
    """Registra las tools de config entries."""

    ready = requires_ready(ha_client)

    def _bad_entry(entry_id: str) -> str | None:
        try:
            validate_identifier(entry_id, field="entry_id")
            return None
        except InvalidIdentifier as exc:
            return json.dumps({"error": "invalid_identifier", "detail": str(exc)})

    # ── ha_list_config_entries ────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_config_entries(
        domain: str | None = None,
        type_filter: str | None = None,
    ) -> object:
        """Lista las config entries (integraciones) de Home Assistant.

        Args:
            domain:      Filtra por dominio (ej. "hue", "mqtt"). Opcional.
            type_filter: Filtra por tipo de entry: "helper" | "integration" |
                         "hub" | "device" | "service". Opcional.

        Returns:
            JSON con {
              "count": int,
              "entries": [
                {
                  "entry_id": "abc123",
                  "domain": "hue",
                  "title": "Philips Hue",
                  "source": "user",
                  "state": "loaded",
                  "supports_options": true,
                  "supports_unload": true,
                  "disabled_by": null,
                  "pref_disable_new_entities": false,
                  "pref_disable_polling": false
                }, ...
              ]
            }
        """
        payload: dict[str, Any] = {"type": "config_entries/get"}
        if domain is not None:
            payload["domain"] = domain
        if type_filter is not None:
            payload["type_filter"] = type_filter

        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            logger.error("ha_list_config_entries_ws_error", error=str(exc))
            return json.dumps({"error": str(exc)})

        items: list[dict] = raw if isinstance(raw, list) else []

        out = json.dumps(
            {"count": len(items), "entries": items}, ensure_ascii=False
        )
        if len(out.encode()) > response_max_bytes:
            # Truncate gracefully
            kept: list[dict] = []
            size = 0
            overhead = len(
                json.dumps(
                    {"count": len(items), "entries": [], "truncated": True, "hint": ""},
                    ensure_ascii=False,
                ).encode()
            )
            for item in items:
                chunk = json.dumps(item, ensure_ascii=False).encode()
                if size + len(chunk) + overhead > response_max_bytes:
                    break
                kept.append(item)
                size += len(chunk) + 1  # +1 for comma
            out = json.dumps(
                {
                    "count": len(items),
                    "returned": len(kept),
                    "entries": kept,
                    "truncated": True,
                    "hint": "Use domain or type_filter to narrow results.",
                },
                ensure_ascii=False,
            )

        logger.info("ha_list_config_entries_ok", count=len(items))
        return out

    # ── ha_get_config_entry ───────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_get_config_entry(entry_id: str) -> object:
        """Devuelve la config entry completa para un entry_id.

        Args:
            entry_id: UUID de la config entry (ej. "a1b2c3d4e5f6...").

        Returns:
            JSON con la config entry, o {"error": "not_found"}.
        """
        if (err := _bad_entry(entry_id)):
            return err
        try:
            raw: Any = await ha_client.ws_send(
                {"type": "config_entries/get_single", "entry_id": entry_id}
            )
        except HAConnectionError as exc:
            logger.error(
                "ha_get_config_entry_ws_error", entry_id=entry_id, error=str(exc)
            )
            return json.dumps({"error": str(exc)})

        if not isinstance(raw, dict):
            return json.dumps({"error": "not_found", "entry_id": entry_id})

        # HA devuelve {"config_entry": {...}}
        entry = raw.get("config_entry") if "config_entry" in raw else raw

        if entry is None:
            return json.dumps({"error": "not_found", "entry_id": entry_id})

        logger.info(
            "ha_get_config_entry_ok",
            entry_id=entry_id,
            domain=entry.get("domain") if isinstance(entry, dict) else None,
        )
        return json.dumps(entry, ensure_ascii=False)

    # ── ha_reload_config_entry ────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_reload_config_entry(entry_id: str) -> object:
        """Recarga una config entry (equivale a descargar + volver a cargar).

        Usa la API REST de HA. Requiere que la integración soporte unload
        (supports_unload: true). Útil para aplicar cambios de opciones o
        refrescar conexiones sin reiniciar HA.

        Args:
            entry_id: UUID de la config entry a recargar.

        Returns:
            JSON {"result": "ok", "require_restart": bool}
            o {"error": "..."} si falla.
        """
        if (err := _bad_entry(entry_id)):
            return err
        try:
            resp: Any = await ha_client._request_json(  # noqa: SLF001
                "POST",
                f"/config/config_entries/entry/{entry_id}/reload",
            )
        except HAConnectionError as exc:
            logger.error(
                "ha_reload_config_entry_rest_error", entry_id=entry_id, error=str(exc)
            )
            return json.dumps({"error": str(exc)})

        require_restart = False
        if isinstance(resp, dict):
            require_restart = bool(resp.get("require_restart", False))

        logger.info(
            "ha_reload_config_entry_ok",
            entry_id=entry_id,
            require_restart=require_restart,
        )
        return json.dumps({"result": "ok", "require_restart": require_restart})

    # ── ha_disable_config_entry ───────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_disable_config_entry(
        entry_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Deshabilita una config entry (disabled_by = "user").

        La integración se descarga: sus entidades y devices quedan
        deshabilitados y cualquier automatización que dependa de ellos deja de
        funcionar. Es reversible con `ha_enable_config_entry`, pero el efecto es
        inmediato y visible, así que requiere confirmación en dos pasos como el
        resto de acciones destructivas.

        Args:
            entry_id:           UUID de la config entry a deshabilitar.
            confirmation_token: Token obtenido en una llamada previa sin token.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token válido: {"result": "ok", "require_restart": bool}
            Error: {"error": "..."}
        """
        if (err := _bad_entry(entry_id)):
            return err
        args = {"entry_id": entry_id}

        if not confirmation_token:
            current: dict | None = None
            try:
                raw_entry: Any = await ha_client.ws_send(
                    {"type": "config_entries/get_single", "entry_id": entry_id}
                )
                if isinstance(raw_entry, dict):
                    current = raw_entry.get("config_entry", raw_entry)
            except HAConnectionError as exc:
                logger.warning(
                    "ha_disable_config_entry_preview_read_failed",
                    entry_id=entry_id,
                    error=str(exc),
                )

            impact = await _count_config_entry_dependents(ha_client, entry_id)
            domain = current.get("domain", "?") if current else "?"
            title = current.get("title", entry_id) if current else entry_id

            preview = {
                "entry_id": entry_id,
                "domain": domain,
                "title": title,
                "impact": impact,
                "warning": (
                    f"Disabling '{title}' ({domain}) will unload the integration "
                    f"and disable {impact['entities']} entities and "
                    f"{impact['devices']} devices. Reversible with "
                    "ha_enable_config_entry."
                ),
            }
            token_data = await create_confirmation_token(
                "ha_disable_config_entry", args, preview=preview
            )
            return json.dumps(token_data, ensure_ascii=False)

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_disable_config_entry", args
        )
        if not valid:
            logger.warning(
                "ha_disable_config_entry_token_invalid",
                entry_id=entry_id,
                reason=error,
            )
            return json.dumps({"error": error})

        try:
            raw: Any = await ha_client.ws_send(
                {
                    "type": "config_entries/disable",
                    "entry_id": entry_id,
                    "disabled_by": "user",
                }
            )
        except HAConnectionError as exc:
            logger.error(
                "ha_disable_config_entry_ws_error", entry_id=entry_id, error=str(exc)
            )
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return json.dumps({"error": str(exc)})

        require_restart = False
        if isinstance(raw, dict):
            require_restart = bool(raw.get("require_restart", False))

        resultado = {"result": "ok", "require_restart": require_restart}
        await complete_confirmation_token(
            confirmation_token, success=True, result=resultado
        )
        logger.info(
            "ha_disable_config_entry_ok",
            entry_id=entry_id,
            require_restart=require_restart,
        )
        return json.dumps(resultado)

    # ── ha_enable_config_entry ────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_enable_config_entry(entry_id: str) -> object:
        """Habilita una config entry previamente deshabilitada por el usuario.

        Establece disabled_by = null. La integración se vuelve a cargar.

        Args:
            entry_id: UUID de la config entry a habilitar.

        Returns:
            JSON {"result": "ok", "require_restart": bool}
            o {"error": "..."}.
        """
        if (err := _bad_entry(entry_id)):
            return err
        try:
            raw: Any = await ha_client.ws_send(
                {
                    "type": "config_entries/disable",
                    "entry_id": entry_id,
                    "disabled_by": None,
                }
            )
        except HAConnectionError as exc:
            logger.error(
                "ha_enable_config_entry_ws_error", entry_id=entry_id, error=str(exc)
            )
            return json.dumps({"error": str(exc)})

        require_restart = False
        if isinstance(raw, dict):
            require_restart = bool(raw.get("require_restart", False))

        logger.info(
            "ha_enable_config_entry_ok",
            entry_id=entry_id,
            require_restart=require_restart,
        )
        return json.dumps({"result": "ok", "require_restart": require_restart})

    # ── ha_delete_config_entry ────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_delete_config_entry(
        entry_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina permanentemente una config entry (integración).

        ADVERTENCIA: Esta acción borra la integración y todas sus entidades y
        devices asociados. No se puede deshacer. Usa ha_disable_config_entry
        para deshabilitarla de forma reversible.

        El preview muestra el número de entities y devices que serán eliminados.
        Siempre requiere confirmation_token.

        Args:
            entry_id:           UUID de la config entry a eliminar.
            confirmation_token: Token obtenido en llamada previa sin token.

        Returns:
            Sin token: {
              "confirmation_token": "...",
              "preview": {
                "entry_id": "...",
                "domain": "...",
                "title": "...",
                "impact": {"entities": N, "devices": M},
                "warning": "..."
              }
            }
            Con token válido: {"result": "ok", "require_restart": bool}
            Error: {"error": "..."}
        """
        if (err := _bad_entry(entry_id)):
            return err
        args = {"entry_id": entry_id}

        if not confirmation_token:
            # Fetch current entry for preview
            current: dict | None = None
            try:
                raw_entry: Any = await ha_client.ws_send(
                    {"type": "config_entries/get_single", "entry_id": entry_id}
                )
                if isinstance(raw_entry, dict):
                    current = raw_entry.get("config_entry", raw_entry)
            except HAConnectionError as exc:
                logger.warning(
                    "ha_delete_config_entry_preview_read_failed",
                    entry_id=entry_id,
                    error=str(exc),
                )

            impact = await _count_config_entry_dependents(ha_client, entry_id)

            domain = current.get("domain", "?") if current else "?"
            title = current.get("title", entry_id) if current else entry_id

            preview = {
                "entry_id": entry_id,
                "domain": domain,
                "title": title,
                "current": current,
                "impact": impact,
                "warning": (
                    f"Permanently deleting config entry '{title}' ({domain}) "
                    f"will remove {impact['entities']} entities and "
                    f"{impact['devices']} devices. This cannot be undone. "
                    "Use ha_disable_config_entry to disable reversibly."
                ),
            }
            token_data = await create_confirmation_token(
                "ha_delete_config_entry", args, preview=preview
            )
            return json.dumps(token_data, ensure_ascii=False)

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_delete_config_entry", args
        )
        if not valid:
            logger.warning(
                "ha_delete_config_entry_token_invalid",
                entry_id=entry_id,
                reason=error,
            )
            return json.dumps({"error": error})

        try:
            resp: Any = await ha_client._request_json(  # noqa: SLF001
                "DELETE",
                f"/config/config_entries/entry/{entry_id}",
            )
        except HAConnectionError as exc:
            logger.error(
                "ha_delete_config_entry_rest_error", entry_id=entry_id, error=str(exc)
            )
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return json.dumps({"error": str(exc)})

        require_restart = False
        if isinstance(resp, dict):
            require_restart = bool(resp.get("require_restart", False))

        await complete_confirmation_token(
            confirmation_token,
            success=True,
            result={"result": "ok", "require_restart": require_restart},
        )
        logger.info(
            "ha_delete_config_entry_ok",
            entry_id=entry_id,
            require_restart=require_restart,
        )
        return json.dumps({"result": "ok", "require_restart": require_restart})
