"""Hermes — Tools MCP para Device Registry.

Usa los comandos WS `config/device_registry/*` de HA.

Campos clave de una entry del device registry:
  id (UUID), name, name_by_user (override), manufacturer, model, model_id,
  area_id, disabled_by, labels, config_entry_id (integración principal, el
  campo vigente), config_entries (list, retirable en HA 2027.8), connections
  (set of tuples), identifiers (set of tuples), via_device_id, entry_type,
  hw_version, sw_version, serial_number.

Dispositivos hijo (HA 2026.9+): llevan `parent_device_id` y `config_entry_id`,
pero no `config_entries`, `manufacturer`, `model`, `via_device_id` ni
`connections`. Si su `area_id` es null, están en el área de su padre.

disabled_by: "user" | "config_entry" | "integration" | null
  Vía API solo se puede cambiar a "user" o null.
  Conveniencia: True → "user", False → null.
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

logger = structlog.get_logger(__name__)

# HA 2026.9 añade `config/device_registry/remove` y convierte
# `remove_config_entry` en su alias deprecado (retirada en 2027.9): por debajo
# de esta versión el comando nuevo no existe.
_REMOVE_DEVICE_MIN_HA = "2026.9.0"


def devices_by_id(raw: Any) -> dict[str, dict]:
    """Indexa por `id` la respuesta de `config/device_registry/list`."""
    if not isinstance(raw, list):
        return {}
    return {
        d["id"]: d for d in raw if isinstance(d, dict) and isinstance(d.get("id"), str)
    }


def effective_area_id(
    device: dict, by_id: dict[str, dict], max_depth: int = 8
) -> str | None:
    """Área en la que está realmente un dispositivo.

    Desde HA 2026.9 un dispositivo hijo sin área propia hereda la de su padre
    (`async_get_effective_area_id` en HA). Mirar solo `area_id` lo dejaba fuera
    de filtros y recuentos. El límite de saltos y el registro de visitados
    evitan colgarse si el registro trae un ciclo: un ciclo da «sin área».
    """
    vistos: set[Any] = set()
    actual = device
    for _ in range(max_depth + 1):
        area = actual.get("area_id")
        if area is not None:
            return area
        padre_id = actual.get("parent_device_id")
        if not isinstance(padre_id, str):
            return None
        vistos.add(actual.get("id"))
        padre = by_id.get(padre_id)
        if padre_id in vistos or not isinstance(padre, dict):
            return None
        actual = padre
    return None


def device_config_entries(device: dict) -> list[str]:
    """Integraciones de un dispositivo: `config_entry_id` y `config_entries`.

    `config_entry_id` es el campo vigente (los hijos solo tienen ese) y
    `config_entries` es retirable en HA 2027.8; se unen sin repetidos.
    """
    out: list[str] = []
    principal = device.get("config_entry_id")
    if isinstance(principal, str) and principal:
        out.append(principal)
    for ce in device.get("config_entries") or []:
        if isinstance(ce, str) and ce and ce not in out:
            out.append(ce)
    return out


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
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
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

        `config_entry_id` es el campo vigente de la integración del device;
        `config_entries` se mantiene por compatibilidad y HA puede retirarlo
        en 2027.8. Los dispositivos hijo (HA 2026.9+) llevan
        `parent_device_id` y no tienen fabricante, modelo ni `config_entries`.

        Args:
            area_id:      Filtrar por área efectiva: la propia o, en un
                          dispositivo hijo sin área, la de su padre. Si se
                          omite, no se filtra por área.
            manufacturer: Filtrar por fabricante (búsqueda exacta, case-sensitive).
                          Los dispositivos hijo no tienen fabricante y quedan
                          fuera de este filtro.
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
                  "config_entry_id": "ce123...",
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
            # Área efectiva: un hijo sin área propia está en la de su padre.
            by_id = devices_by_id(items)
            items = [
                d for d in items
                if isinstance(d, dict) and effective_area_id(d, by_id) == area_id
            ]
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
        """DEPRECATED: usa ha_remove_device. Se retirará antes de HA 2027.9.

        Envía `config/device_registry/remove_config_entry`. Lo que hace
        depende de la versión de HA:
          - HA 2026.9 o posterior: si la config entry es la del device, BORRA
            EL DEVICE ENTERO (con sus entidades del registry); HA convirtió
            este comando en alias del borrado de dispositivos.
          - Versiones anteriores: quita la asociación; si era la última
            config entry del device, HA borra el device.
        La config entry debe soportar eliminación manual de devices; si no lo
        soporta, HA devuelve error.

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
                # La preview decía «quita la asociación», pero desde HA 2026.9
                # el mismo comando borra el dispositivo entero: el preview no
                # puede ocultar ese efecto.
                "deprecated": True,
                "replacement": "ha_remove_device",
                "warning": (
                    "DEPRECATED, will be removed before Home Assistant 2027.9. "
                    "On Home Assistant 2026.9 or newer this DELETES THE WHOLE "
                    "DEVICE if the config entry is the device's own; on older "
                    "versions it removes the association, and the device is "
                    "deleted if it was its last config entry. "
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

    # ── ha_remove_device ──────────────────────────────────────────────────

    # Comando elegido en cada preview, por token. El token solo ata
    # `device_id` (el cliente no tiene por qué saber la versión de HA), así
    # que el método anunciado se guarda aquí para comprobar al ejecutar que no
    # ha cambiado: si HA se actualiza entre las dos llamadas, ejecutar otro
    # comando distinto del anunciado sería un preview que miente.
    metodos_anunciados: dict[str, tuple[str, str | None]] = {}

    async def _plan_remove_device(
        device_id: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Decide cómo se borrará el device. Devuelve (plan, error)."""
        try:
            raw_devs: Any = await ha_client.ws_send(
                {"type": "config/device_registry/list"}
            )
        except HAConnectionError as exc:
            return None, {"error": str(exc)}
        device = devices_by_id(raw_devs).get(device_id)
        if device is None:
            return None, {"error": "not_found", "device_id": device_id}

        # Fail-closed: sin versión no se puede anunciar qué comando se usará.
        nuevo = await ha_at_least(ha_client, _REMOVE_DEVICE_MIN_HA)
        if nuevo is None:
            return None, {
                "error": "ha_version_unknown",
                "detail": "Could not read the Home Assistant version; "
                          "refusing to choose a removal command blindly.",
            }
        config_entry_id: str | None = None
        if nuevo:
            method = "config/device_registry/remove"
        else:
            # En HA < 2026.9 el device se borra cuando pierde su última
            # integración; con varias habría que hacer varias llamadas y un
            # fallo a medias no se puede describir en la preview.
            entries = device_config_entries(device)
            if len(entries) != 1:
                return None, {
                    "error": "multiple_config_entries"
                    if entries else "no_config_entries",
                    "device_id": device_id,
                    "config_entries": entries,
                    "hint": (
                        "Home Assistant older than 2026.9 can only delete a "
                        "device by removing its config entries one by one: use "
                        "ha_remove_device_from_config_entry for each of them."
                    ),
                }
            method = "config/device_registry/remove_config_entry"
            config_entry_id = entries[0]
        return {
            "device": device,
            "method": method,
            "config_entry_id": config_entry_id,
        }, None

    @mcp.tool()
    @ready
    async def ha_remove_device(
        device_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Borra un device del device registry junto con sus entidades del registry.

        Elige el comando según la versión de HA y la preview dice cuál usará:
          - HA 2026.9 o posterior: `config/device_registry/remove`.
          - Versiones anteriores: `config/device_registry/remove_config_entry`
            con la única config entry del device (HA borra el device al
            quedarse sin integraciones). Si tiene varias, se niega
            (`multiple_config_entries`).
        Si no se puede leer la versión de HA, se niega (`ha_version_unknown`).

        La integración debe permitir el borrado manual de devices; si no, HA
        devuelve error. Si la integración vuelve a descubrir el device, puede
        recrearlo.

        Siempre requiere confirmation_token.

        Args:
            device_id:          UUID del device a borrar.
            confirmation_token: Token obtenido en llamada previa sin token.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token válido: {"result": "ok", "method": "..."}
            Error: {"error": "not_found" | "ha_version_unknown" |
                    "multiple_config_entries" | "ha_version_changed" | "..."}
        """
        args = {"device_id": device_id}

        if not confirmation_token:
            plan, err = await _plan_remove_device(device_id)
            if err is not None or plan is None:
                return json.dumps(err or {"error": "unknown"}, ensure_ascii=False)
            try:
                raw_ents: Any = await ha_client.ws_send(
                    {"type": "config/entity_registry/list"}
                )
            except HAConnectionError as exc:
                # Sin el recuento la preview no diría la verdad: no hay token.
                return json.dumps({"error": str(exc)})
            entities_count = sum(
                1 for e in (raw_ents if isinstance(raw_ents, list) else [])
                if isinstance(e, dict) and e.get("device_id") == device_id
            )
            device = plan["device"]
            preview: dict[str, Any] = {
                "device_id": device_id,
                "device_name": device.get("name_by_user") or device.get("name"),
                "action": "delete_device",
                "method": plan["method"],
            }
            if plan["config_entry_id"] is not None:
                preview["config_entry_id"] = plan["config_entry_id"]
            preview["entities_count"] = entities_count
            warning = (
                f"Deletes this device from the device registry together with "
                f"its {entities_count} entity registry entries. The integration "
                f"must allow manual removal; it may re-add the device if it "
                f"discovers it again."
            )
            if plan["config_entry_id"] is not None:
                warning += (
                    " Home Assistant is older than 2026.9, so this removes the "
                    "device's only config entry, which deletes the device."
                )
            preview["warning"] = warning
            token_data = await create_confirmation_token(
                "ha_remove_device", args, preview=preview
            )
            metodos_anunciados[token_data["confirmation_token"]] = (
                plan["method"], plan["config_entry_id"],
            )
            # Los tokens caducan en segundos; se acota el dict para que las
            # previews nunca confirmadas no lo hagan crecer sin límite.
            while len(metodos_anunciados) > 256:
                metodos_anunciados.pop(next(iter(metodos_anunciados)))
            return json.dumps(token_data, ensure_ascii=False)

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_remove_device", args
        )
        if not valid:
            logger.warning(
                "ha_remove_device_token_invalid", device_id=device_id, reason=error
            )
            return json.dumps({"error": error})

        anunciado = metodos_anunciados.pop(confirmation_token, None)
        plan, err = await _plan_remove_device(device_id)
        if err is not None or plan is None:
            err = err or {"error": "unknown"}
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(err.get("error"))
            )
            return json.dumps(err, ensure_ascii=False)
        if anunciado != (plan["method"], plan["config_entry_id"]):
            # Sin el método anunciado (Hermes se reinició) tampoco se puede
            # garantizar que se ejecute lo que dijo la preview.
            await complete_confirmation_token(
                confirmation_token, success=False, error="ha_version_changed"
            )
            return json.dumps({
                "error": "ha_version_changed",
                "detail": "The removal method changed since the preview "
                          "(Home Assistant was updated or Hermes restarted). "
                          "Request a new preview.",
            })

        payload: dict[str, Any] = {"type": plan["method"], "device_id": device_id}
        if plan["config_entry_id"] is not None:
            payload["config_entry_id"] = plan["config_entry_id"]
        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            logger.error(
                "ha_remove_device_ws_error", device_id=device_id, error=str(exc)
            )
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return json.dumps({"error": str(exc)})

        await complete_confirmation_token(
            confirmation_token, success=True, result=raw
        )
        logger.info(
            "ha_remove_device_ok", device_id=device_id, method=plan["method"]
        )
        return json.dumps({"result": "ok", "method": plan["method"]})
