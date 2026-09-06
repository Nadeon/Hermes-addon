"""Hermes — Tools MCP para Device Registry.

Usa los comandos WS `config/device_registry/*` de HA.

Campos clave de una entry del device registry:
  id (UUID), name, name_by_user (override), manufacturer, model, model_id,
  area_id, disabled_by, labels, config_entries (list), connections (set of
  tuples), identifiers (set of tuples), via_device_id, entry_type,
  hw_version, sw_version, serial_number.

disabled_by: "user" | "config_entry" | "integration" | null
  Vía API solo se puede cambiar a "user" o null.
  Conveniencia: True → "user", False → null.
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


def _coerce_disabled_by(val: Any) -> str | None:
    if isinstance(val, bool):
        return "user" if val else None
    return val


def _validate_device_updates(
    updates: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    out: dict[str, Any] = {}
    for k, v in updates.items():
        if k == "disabled_by":
            coerced = _coerce_disabled_by(v)
            if coerced not in (None, "user"):
                return {}, (
                    f"disabled_by must be 'user', null, true or false; got {v!r}"
                )
            out[k] = coerced
        elif k == "labels":
            if not isinstance(v, list):
                return {}, "labels must be a list of strings"
            out[k] = [str(lbl) for lbl in v]
        elif k in ("name_by_user", "area_id"):
            out[k] = v  # str or None
        else:
            out[k] = v
    return out, None


def register(
    mcp: object,
    ha_client: HAClient,
    response_max_bytes: int = 1_048_576,
) -> None:
    """Registra las tools de device registry."""

    ready = requires_ready(ha_client)

    # ── ha_list_devices ───────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_devices(
        area_id: str | None = None,
        manufacturer: str | None = None,
        disabled: bool | None = None,
    ) -> object:
        """Lista devices del device registry con filtros opcionales.

        Args:
            area_id:      Filtrar por área asignada. Si se omite, no se
                          filtra por área.
            manufacturer: Filtrar por fabricante (búsqueda exacta, case-sensitive).
            disabled:     True → solo deshabilitados, False → solo habilitados,
                          None → todos.

        Returns:
            JSON con {
              "count": int,
              "devices": [
                {
                  "id": "abc123...",
                  "name": "Sensor Despacho",
                  "name_by_user": null,
                  "manufacturer": "Xiaomi",
                  "model": "WSDCGQ01LM",
                  "area_id": "despacho",
                  "disabled_by": null,
                  "config_entries": [...],
...
                }, ...
              ],
              "truncated": bool
            }
        """
        try:
            raw: Any = await ha_client.ws_send(
                {"type": "config/device_registry/list"}
            )
        except HAConnectionError as exc:
            logger.error("ha_list_devices_ws_error", error=str(exc))
            return json.dumps({"error": str(exc)})

        items: list[dict] = raw if isinstance(raw, list) else []

        # Apply filters
        if area_id is not None:
            items = [d for d in items if d.get("area_id") == area_id]
        if manufacturer is not None:
            items = [
                d for d in items if d.get("manufacturer") == manufacturer
            ]
        if disabled is True:
            items = [d for d in items if d.get("disabled_by") is not None]
        elif disabled is False:
            items = [d for d in items if d.get("disabled_by") is None]

        # Truncate by bytes
        truncated = False
        if len(json.dumps(items, ensure_ascii=False).encode()) > response_max_bytes:
            truncated = True
            while items and len(
                json.dumps(items, ensure_ascii=False).encode()
            ) > response_max_bytes:
                items.pop()

        logger.info("ha_list_devices_ok", count=len(items), truncated=truncated)
        return json.dumps(
            {"count": len(items), "devices": items, "truncated": truncated},
            ensure_ascii=False,
        )

    # ── ha_get_device ─────────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_get_device(device_id: str) -> object:
        """Devuelve la entry completa del device registry para un device.

        Args:
            device_id: UUID del device (ej. obtenido de ha_list_devices
                       o del entity registry entry.device_id).

        Returns:
            JSON con la entry del device registry, o {"error": "not_found"}.
        """
        try:
            raw: Any = await ha_client.ws_send(
                {"type": "config/device_registry/list"}
            )
        except HAConnectionError as exc:
            logger.error(
                "ha_get_device_ws_error", device_id=device_id, error=str(exc)
            )
            return json.dumps({"error": str(exc)})

        items: list[dict] = raw if isinstance(raw, list) else []
        entry = next((d for d in items if d.get("id") == device_id), None)
        if entry is None:
            return json.dumps({"error": "not_found", "device_id": device_id})

        logger.info("ha_get_device_ok", device_id=device_id)
        return json.dumps(entry, ensure_ascii=False)

    # ── ha_update_device ──────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_update_device(
        device_id: str,
        updates: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Actualiza parcialmente un device del device registry.

        Campos soportados en `updates`:
          name_by_user (str|null) — Override del nombre mostrado en la UI.
                                    null = usar el nombre original del dispositivo.
          area_id (str|null)      — Asignar a área. null = desasignar.
          disabled_by (str|null|bool) — Deshabilitar/habilitar device y todas
                                    sus entidades asociadas.
                                    "user" o true → deshabilita.
                                    null o false  → habilita.
          labels (list[str])      — Lista de labels del device.

        Si no se pasa confirmation_token, devuelve preview + token.

        Args:
            device_id:          UUID del device a actualizar.
            updates:            Dict con los campos a cambiar.
            confirmation_token: Token obtenido en llamada previa sin token.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token válido: {"result": "ok", ...entry actualizada...}
            Error: {"error": "..."}
        """
        normalized, err = _validate_device_updates(updates)
        if err:
            return json.dumps({"error": err})
        if not normalized:
            return json.dumps({"error": "updates is empty"})

        args = {"device_id": device_id, "updates": normalized}

        if not confirmation_token:
            # Fetch current entry for preview
            try:
                raw_list: Any = await ha_client.ws_send(
                    {"type": "config/device_registry/list"}
                )
                all_devices: list[dict] = raw_list if isinstance(raw_list, list) else []
                current = next(
                    (d for d in all_devices if d.get("id") == device_id), None
                )
            except HAConnectionError as exc:
                current = None
                logger.warning(
                    "ha_update_device_preview_read_failed",
                    device_id=device_id,
                    error=str(exc),
                )

            preview = {
                "device_id": device_id,
                "current": current,
                "proposed_changes": normalized,
                "requires_confirmation": True,
            }
            token_data = await create_confirmation_token(
                "ha_update_device", args, preview=preview
            )
            return json.dumps(token_data, ensure_ascii=False)

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_update_device", args
        )
        if not valid:
            logger.warning(
                "ha_update_device_token_invalid",
                device_id=device_id,
                reason=error,
            )
            return json.dumps({"error": error})

        payload = build_ws_payload(
            "config/device_registry/update",
            {"device_id": device_id},
            normalized,
        )

        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            logger.error(
                "ha_update_device_ws_error", device_id=device_id, error=str(exc)
            )
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return json.dumps({"error": str(exc)})

        await complete_confirmation_token(
            confirmation_token, success=True, result=raw
        )
        logger.info("ha_update_device_ok", device_id=device_id)
        result: dict[str, Any] = {"result": "ok"}
        if isinstance(raw, dict):
            result.update(raw)
        return json.dumps(result, ensure_ascii=False)

    # ── ha_remove_device_from_config_entry ────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_remove_device_from_config_entry(
        device_id: str,
        config_entry_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Desasocia un device de una config entry.

        Útil para limpiar dispositivos fantasma (el dispositivo físico ya no
        existe pero la config entry sigue referenciándolo). La config entry
        debe soportar eliminación manual de devices; si no lo soporta, HA
        devuelve error.

        Siempre requiere confirmation_token.

        Args:
            device_id:          UUID del device a desasociar.
            config_entry_id:    ID de la config entry de la que desasociar.
            confirmation_token: Token obtenido en llamada previa sin token.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token válido: {"result": "ok"} o entry actualizada del device
            Error: {"error": "..."}
        """
        args = {"device_id": device_id, "config_entry_id": config_entry_id}

        if not confirmation_token:
            preview = {
                "device_id": device_id,
                "config_entry_id": config_entry_id,
                "action": "remove_config_entry_from_device",
                "warning": (
                    "Removes the association between this device and the config entry. "
                    "The config entry must support manual device removal."
                ),
            }
            token_data = await create_confirmation_token(
                "ha_remove_device_from_config_entry", args, preview=preview
            )
            return json.dumps(token_data, ensure_ascii=False)

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_remove_device_from_config_entry", args
        )
        if not valid:
            logger.warning(
                "ha_remove_device_from_config_entry_token_invalid",
                device_id=device_id,
                reason=error,
            )
            return json.dumps({"error": error})

        try:
            raw: Any = await ha_client.ws_send(
                {
                    "type": "config/device_registry/remove_config_entry",
                    "device_id": device_id,
                    "config_entry_id": config_entry_id,
                }
            )
        except HAConnectionError as exc:
            logger.error(
                "ha_remove_device_from_config_entry_ws_error",
                device_id=device_id,
                error=str(exc),
            )
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return json.dumps({"error": str(exc)})

        await complete_confirmation_token(
            confirmation_token, success=True, result=raw
        )
        logger.info(
            "ha_remove_device_from_config_entry_ok",
            device_id=device_id,
            config_entry_id=config_entry_id,
        )
        result: dict[str, Any] = {"result": "ok"}
        if isinstance(raw, dict):
            result.update(raw)
        return json.dumps(result, ensure_ascii=False)
