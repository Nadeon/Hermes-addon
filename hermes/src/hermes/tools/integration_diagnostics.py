"""Hermes — Diagnósticos de integraciones (spec 012, tramo B).

Tres tools de la familia `core_diagnostics` (CAP-042 de la 008):

- `ha_list_diagnostics_handlers`: qué integraciones ofrecen diagnóstico y de
  qué tipo (`diagnostics/list` o `diagnostics/get`).
- `ha_get_config_entry_diagnostics`: el diagnóstico de una integración
  configurada (`GET /api/diagnostics/config_entry/<entry_id>`).
- `ha_get_device_diagnostics`: el de un dispositivo, pedido a la integración
  dueña (`…/config_entry/<entry_id>/device/<device_id>`).

POR QUÉ COMPROBAR ANTES DE DESCARGAR
------------------------------------
La descarga da 404 por cinco motivos distintos (no existe la entrada, su
integración no tiene diagnóstico, no lo tiene de ese tipo, no existe el
dispositivo, no es de esa entrada). Se comprueba antes con
`config_entries/get_single`, `config/device_registry/list` y
`diagnostics/get` para decir cuál es, y para no descargar varios MB que no se
van a poder usar (research R-5).

POR QUÉ REDACTAR OTRA VEZ
-------------------------
Cada integración tapa lo suyo con una lista de claves que puede quedarse
corta. Hermes añade su redacción por clave (`redact_structure`) y por patrón
en cada texto (`redact_secrets`) antes de devolver nada.

POR QUÉ RECORTAR AQUÍ
---------------------
Un diagnóstico de Z-Wave o ZHA puede ocupar varios MB, y el tope central no
sabe recortar un objeto de objetos. Si no cabe, se devuelve
`response_too_large` con el tamaño de cada clave de `data`, para que el agente
pida solo las que necesita con `keys=[…]`. Nunca JSON cortado.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.identifiers import InvalidIdentifier, validate_path_segment
from hermes.security import redact_secrets, redact_structure
from hermes.tools._common import (
    _LIMIT_HINT,
    ajustar_lista_a_bytes,
    requires_ready,
    sobre_de_lista,
    tam_json,
)

logger = structlog.get_logger(__name__)

_DOMINIO = re.compile(r"^[a-z0-9_]+$")

# Claves del diagnóstico que describen la instalación y no la integración:
# solo salen con `include_system_info=true` (ocupan y casi nunca hacen falta).
_SYSTEM_INFO = ("home_assistant", "custom_components", "integration_manifest", "setup_times")

_TOO_LARGE_HINT = "Request fewer keys with keys=[...]"


def _invalid(field: str, detail: str) -> dict[str, Any]:
    return {"error": "invalid_argument", "field": field, "detail": detail}


def _error_ha(exc: HAConnectionError) -> dict[str, Any]:
    return {"error": redact_secrets(str(exc))}


def _redactar(valor: Any) -> Any:
    """Redacta por clave (`redact_structure`) y por patrón en cada texto.

    Las dos capas hacen falta: la clave tapa `{"token": "…"}`, pero un JWT o
    una URL con credenciales bajo una clave inocente solo los detecta el
    patrón (mismo criterio que `_redactar` de `repairs.py`).
    """
    valor = redact_structure(valor)
    if isinstance(valor, dict):
        return {k: _redactar(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_redactar(v) for v in valor]
    if isinstance(valor, str):
        return redact_secrets(valor)
    return valor


def _no_disponible(exc: HAConnectionError) -> dict[str, Any] | None:
    # Sin la integración `diagnostics` cargada (configuración sin
    # `default_config`), el comando no existe.
    if exc.code == "unknown_command":
        return {"error": "diagnostics_unavailable", "ha_code": exc.code,
                "detail": redact_secrets(str(exc))}
    return None


def _handlers(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("domain"), str):
        return None
    h = raw.get("handlers") if isinstance(raw.get("handlers"), dict) else {}
    return {"domain": raw["domain"],
            "config_entry": h.get("config_entry") is True,
            "device": h.get("device") is True}


def _validar_keys(keys: Any) -> dict[str, Any] | None:
    if keys is None:
        return None
    if not isinstance(keys, list) or not keys or not all(isinstance(k, str) for k in keys):
        return _invalid("keys", "must be a non-empty list of top-level keys of 'data'")
    return None


def register(
    mcp: object,
    ha_client: HAClient,
    *,
    response_max_bytes: int,
) -> None:
    """Registra las tools de diagnóstico de integraciones."""

    ready = requires_ready(ha_client)

    async def _handlers_de(dominio: str) -> dict[str, Any]:
        """Handlers del dominio o un error ya formado (lanza si HA cae)."""
        try:
            raw = await ha_client.ws_send({"type": "diagnostics/get", "domain": dominio})
        except HAConnectionError as exc:
            if exc.code == "not_found":
                return {"error": "diagnostics_not_supported", "domain": dominio,
                        "reason": "The integration has no diagnostics."}
            no = _no_disponible(exc)
            if no is not None:
                return no
            raise
        h = _handlers(raw)
        if h is None:
            raise HAConnectionError("unexpected response from diagnostics/get")
        return h

    async def _entrada(entry_id: str) -> dict[str, Any] | None:
        """La entrada de configuración o None si no existe (lanza si HA cae)."""
        try:
            raw = await ha_client.ws_send(
                {"type": "config_entries/get_single", "entry_id": entry_id})
        except HAConnectionError as exc:
            if exc.code == "not_found":
                return None
            raise
        entrada = raw.get("config_entry", raw) if isinstance(raw, dict) else None
        if not isinstance(entrada, dict) or not isinstance(entrada.get("domain"), str):
            return None
        return entrada

    async def _descargar(
        tool: str,
        entry_id: str,
        dominio: str,
        device_id: str | None,
        keys: list[str] | None,
        include_system_info: bool,
    ) -> dict[str, Any]:
        """Comprueba el handler, descarga, redacta, filtra y mide."""
        tipo = "device" if device_id is not None else "config_entry"
        h = await _handlers_de(dominio)
        if "error" in h:
            h.setdefault("kind", tipo)
            logger.info(f"{tool}_error", code=h["error"], domain=dominio)
            return h
        if not h[tipo]:
            logger.info(f"{tool}_error", code="diagnostics_not_supported", domain=dominio)
            return {"error": "diagnostics_not_supported", "domain": dominio, "kind": tipo,
                    "reason": f"The integration has no {tipo.replace('_', ' ')} diagnostics."}

        ruta = f"/diagnostics/config_entry/{entry_id}"
        if device_id is not None:
            ruta += f"/device/{device_id}"
        try:
            raw = await ha_client._request_json("GET", ruta)  # noqa: SLF001
        except HAConnectionError as exc:
            logger.warning(f"{tool}_error", code=exc.status or "connection", domain=dominio)
            if exc.status == 404:
                # Ha desaparecido entre la comprobación y la descarga.
                return {"error": "not_found", "entry_id": entry_id,
                        **({"device_id": device_id} if device_id else {}),
                        "detail": "Home Assistant answered 404 to the diagnostics download."}
            return _error_ha(exc)
        if not isinstance(raw, dict):
            logger.warning(f"{tool}_error", code="unexpected_response", domain=dominio)
            return {"error": "unexpected response from the diagnostics download"}

        limpio = _redactar(raw)
        data = limpio.get("data")
        if keys is not None:
            if not isinstance(data, dict):
                return _invalid("keys", "this diagnostics 'data' is not an object")
            faltan = [k for k in keys if k not in data]
            if faltan:
                return {**_invalid("keys", f"unknown keys: {faltan}"),
                        "available_keys": list(data)}
            data = {k: data[k] for k in keys}

        out: dict[str, Any] = {"entry_id": entry_id, "domain": dominio}
        if device_id is not None:
            out["device_id"] = device_id
        out["data"] = data
        out["issues"] = limpio.get("issues", [])
        if include_system_info:
            out["system_info"] = {k: limpio.get(k) for k in _SYSTEM_INFO}
        out["keys_returned"] = list(data) if isinstance(data, dict) else []
        out["redacted_by"] = ["home_assistant", "hermes"]

        if tam_json(out) > response_max_bytes:
            tamanos = (
                [{"key": k, "bytes": tam_json(v)} for k, v in data.items()]
                if isinstance(data, dict) else []
            )
            logger.info(f"{tool}_error", code="response_too_large", domain=dominio,
                        keys=len(tamanos))
            return {"error": "response_too_large", "data_keys": tamanos,
                    "max_bytes": response_max_bytes, "hint": _TOO_LARGE_HINT}
        logger.info(f"{tool}_ok", domain=dominio, kind=tipo,
                    keys=len(out["keys_returned"]), system_info=include_system_info)
        return out

    # ── ha_list_diagnostics_handlers ──────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_diagnostics_handlers(domain: str | None = None) -> object:
        """List the integrations that offer diagnostics, and of which kind.

        "config_entry" means ha_get_config_entry_diagnostics works for its
        entries; "device" means ha_get_device_diagnostics works for its
        devices.

        Args:
            domain: Only this integration domain (for example "mqtt").

        Returns:
            {"count", "items": [{domain, config_entry: bool, device: bool}],
             "truncated"} ordered by domain ("_response_limit" if cut);
            {"error": "diagnostics_not_supported", "domain"} if the given
            domain has no diagnostics.
        """
        if domain is not None and (not isinstance(domain, str) or not _DOMINIO.match(domain)):
            return _invalid("domain", "must be an integration domain like 'mqtt'")
        try:
            if domain is not None:
                h = await _handlers_de(domain)
                if "error" in h:
                    logger.info("ha_list_diagnostics_handlers_error", code=h["error"],
                                domain=domain)
                    return h
                items = [h]
            else:
                raw = await ha_client.ws_send({"type": "diagnostics/list"})
                if not isinstance(raw, list):
                    raise HAConnectionError("unexpected response from diagnostics/list")
                items = sorted((h for h in map(_handlers, raw) if h is not None),
                               key=lambda i: i["domain"])
        except HAConnectionError as exc:
            logger.warning("ha_list_diagnostics_handlers_error", code=exc.code or "connection")
            return _no_disponible(exc) or _error_ha(exc)

        total = len(items)

        # Sobre común de las listas de la 1.2.0 (spec 018, FR-012): `count`
        # es cuántos `items` vienen; si se cortó, `_response_limit.total` dice
        # cuántos había, como el tope central (`recortar_a_bytes`).
        def construir(lista: list[Any], recortada: bool) -> dict[str, Any]:
            out = sobre_de_lista(lista, truncated=recortada)
            if recortada:
                out["_response_limit"] = {
                    "list": "items", "returned": len(lista), "total": total,
                    "max_bytes": response_max_bytes, "hint": _LIMIT_HINT,
                }
            return out

        respuesta = ajustar_lista_a_bytes(items, construir, response_max_bytes)
        logger.info("ha_list_diagnostics_handlers_ok", count=total, domain=domain)
        return respuesta

    # ── ha_get_config_entry_diagnostics ───────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_get_config_entry_diagnostics(
        entry_id: str,
        keys: list[str] | None = None,
        include_system_info: bool = False,
    ) -> object:
        """Download the diagnostics of a configured integration (config entry).

        The same data as "Download diagnostics" in the UI, redacted twice:
        by the integration and by Hermes. Without include_system_info, the
        Home Assistant system information, custom integrations, manifest
        and setup times are left out. If the result does not fit in the
        response limit, returns {"error": "response_too_large"} with the size
        of each key of "data": ask again with keys=[...].

        Args:
            entry_id: Config entry id (see ha_list_config_entries).
            keys: Only these top-level keys of "data".
            include_system_info: Also return "system_info".

        Returns:
            {"entry_id", "domain", "data", "issues", "keys_returned",
             "redacted_by"} (+ "system_info"); or {"error": "not_found" |
             "diagnostics_not_supported" | "response_too_large" | ...}.
        """
        try:
            validate_path_segment(entry_id, field="entry_id")
        except InvalidIdentifier as exc:
            return _invalid("entry_id", str(exc))
        if (error := _validar_keys(keys)) is not None:
            return error
        try:
            entrada = await _entrada(entry_id)
            if entrada is None:
                logger.info("ha_get_config_entry_diagnostics_error", code="not_found")
                return {"error": "not_found", "entry_id": entry_id}
            return await _descargar("ha_get_config_entry_diagnostics", entry_id,
                                    entrada["domain"], None, keys, bool(include_system_info))
        except HAConnectionError as exc:
            logger.warning("ha_get_config_entry_diagnostics_error",
                           code=exc.code or "connection")
            return _error_ha(exc)

    # ── ha_get_device_diagnostics ─────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_get_device_diagnostics(
        device_id: str,
        keys: list[str] | None = None,
        include_system_info: bool = False,
    ) -> object:
        """Download the diagnostics of a device from the integration that owns it.

        The owner is the device's primary integration ("config_entry_id" in
        the device registry); Home Assistant only serves device diagnostics
        from it. Redacted twice, by the integration and by Hermes. Few
        integrations offer device diagnostics (see
        ha_list_diagnostics_handlers). If the result does not fit, returns
        {"error": "response_too_large"} with the size of each key of "data":
        ask again with keys=[...].

        Args:
            device_id: Device id (see ha_list_devices).
            keys: Only these top-level keys of "data".
            include_system_info: Also return "system_info".

        Returns:
            {"entry_id", "domain", "device_id", "data", "issues",
             "keys_returned", "redacted_by"} (+ "system_info"); or
            {"error": "not_found" | "diagnostics_not_supported" |
             "response_too_large" | ...}.
        """
        try:
            validate_path_segment(device_id, field="device_id")
        except InvalidIdentifier as exc:
            return _invalid("device_id", str(exc))
        if (error := _validar_keys(keys)) is not None:
            return error
        tool = "ha_get_device_diagnostics"
        try:
            raw = await ha_client.ws_send({"type": "config/device_registry/list"})
            if not isinstance(raw, list):
                raise HAConnectionError("unexpected response from config/device_registry/list")
            dispositivo = next(
                (d for d in raw if isinstance(d, dict) and d.get("id") == device_id), None)
            if dispositivo is None:
                logger.info(f"{tool}_error", code="not_found")
                return {"error": "not_found", "device_id": device_id}
            # La dueña es `config_entry_id` (la integración principal), no la
            # primera de `config_entries`: HA solo sirve el diagnóstico de
            # dispositivo desde ella.
            entry_id = dispositivo.get("config_entry_id")
            if not isinstance(entry_id, str) or not entry_id:
                logger.info(f"{tool}_error", code="diagnostics_not_supported")
                return {"error": "diagnostics_not_supported", "device_id": device_id,
                        "kind": "device",
                        "reason": "The device has no owning integration "
                                  "(no config_entry_id in the device registry)."}
            try:
                validate_path_segment(entry_id, field="config_entry_id")
            except InvalidIdentifier:
                return {"error": "unexpected config_entry_id in the device registry"}
            entrada = await _entrada(entry_id)
            if entrada is None:
                logger.info(f"{tool}_error", code="not_found")
                return {"error": "not_found", "device_id": device_id, "entry_id": entry_id}
            return await _descargar(tool, entry_id, entrada["domain"], device_id, keys,
                                    bool(include_system_info))
        except HAConnectionError as exc:
            logger.warning(f"{tool}_error", code=exc.code or "connection")
            return _error_ha(exc)
