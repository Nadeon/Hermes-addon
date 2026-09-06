"""Hermes — Tools MCP para Supervisor / Host / Core.

Información y gestión del sistema vía Supervisor REST API.

Tools:
  sv_get_supervisor_info — versión del Supervisor, canal, estado
  sv_get_host_info       — OS, hostname, kernel, disco
  sv_get_core_info       — versión HA core, update_available
  sv_check_core_config   — valida la configuración de HA (POST /core/check)
  sv_restart_core        — reinicia el core de HA (siempre requiere token)
  sv_reboot_host         — reinicia el host HAOS completo (siempre requiere token)

sv_restart_core respeta el estado de check_config_state.json, que escriben las
tools de escritura sobre /config: si hay escrituras sin un check posterior,
bloquea el restart. Si el fichero no existe no hay nada pendiente, y permite.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.fs_write import check_restart_allowed_sync, record_check_config_ok
from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    redact_structure,
    complete_confirmation_token,
    create_confirmation_token,
    validate_confirmation_token,
)

logger = structlog.get_logger(__name__)


def _check_restart_allowed() -> tuple[bool, str]:
    """Delega a fs_write.check_restart_allowed_sync."""
    return check_restart_allowed_sync()


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de Supervisor/Host/Core en la instancia MCP."""

    @mcp.tool()
    async def sv_get_supervisor_info() -> object:
        """Estado del propio Supervisor: versión, canal y salud (no el hardware).

        Para disco, hostname o sistema operativo usa sv_get_host_info.

        Returns:
            {"version": "...", "channel": "stable|beta|dev",
             "healthy": bool, "supported": bool, ...}
        """
        try:
            data = redact_structure(await ha_client.sv_request("GET", "/supervisor/info"))
            if not isinstance(data, dict):
                return {"error": "unexpected_response"}
            return {
                "version": data.get("version"),
                "channel": data.get("channel"),
                "healthy": data.get("healthy"),
                "supported": data.get("supported"),
                "arch": data.get("arch"),
                "machine": data.get("machine"),
                "docker_version": data.get("docker_version"),
            }
        except HAConnectionError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_get_host_info() -> object:
        """Hardware y SO del host: espacio en disco, hostname, kernel, zona horaria.

        Es la tool para "¿cuánto disco queda?". Para la versión del Supervisor
        usa sv_get_supervisor_info; para la de HA, sv_get_core_info.

        Returns:
            {"hostname": "...", "operating_system": "...",
             "kernel_version": "...", "disk_total": N, "disk_used": N,
             "disk_free": N, "boot_timestamp": "..."}
        """
        try:
            data = redact_structure(await ha_client.sv_request("GET", "/host/info"))
            if not isinstance(data, dict):
                return {"error": "unexpected_response"}
            return {
                "hostname": data.get("hostname"),
                "operating_system": data.get("operating_system"),
                "kernel_version": data.get("kernel_version"),
                "chassis": data.get("chassis"),
                "disk_total": data.get("disk_total"),
                "disk_used": data.get("disk_used"),
                "disk_free": data.get("disk_free"),
                "boot_timestamp": data.get("boot_timestamp"),
                "timezone": data.get("timezone"),
            }
        except HAConnectionError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_get_core_info() -> object:
        """Devuelve información sobre el core de Home Assistant.

        Returns:
            {"version": "...", "version_latest": "...",
             "update_available": bool, "state": "running|stopped|..."}
        """
        try:
            data = redact_structure(await ha_client.sv_request("GET", "/core/info"))
            if not isinstance(data, dict):
                return {"error": "unexpected_response"}
            return {
                "version": data.get("version"),
                "version_latest": data.get("version_latest"),
                "update_available": data.get("update_available"),
                "state": data.get("state"),
                "arch": data.get("arch"),
                "machine": data.get("machine"),
                "boot": data.get("boot"),
            }
        except HAConnectionError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_check_core_config() -> object:
        """Valida la configuración de Home Assistant sin aplicarla.

        Llama a POST /core/check en el Supervisor. No pide confirmation_token,
        pero NO es de solo lectura: si el check pasa, escribe
        check_config_state.json, y con ello levanta el bloqueo que impide
        reiniciar HA cuando hay escrituras en /config sin validar. Por eso está
        anotada como no read-only.

        Returns:
            {"result": "ok"} si la configuración es válida.
            {"result": "error", "details": "..."} si hay errores.
        """
        try:
            data = await ha_client.sv_request("POST", "/core/check")
            logger.info("sv_check_core_config_ok")
            # Actualizar check_config_state para desbloquear restart
            await record_check_config_ok()
            if isinstance(data, dict):
                return {"result": "ok", **data}
            return {"result": "ok"}
        except HAConnectionError as exc:
            # El Supervisor devuelve error si la config es inválida
            err_str = str(exc)
            logger.warning("sv_check_core_config_failed", error=err_str)
            return {"result": "error", "details": err_str}

    @mcp.tool()
    async def sv_restart_core(
        confirmation_token: str | None = None,
    ) -> object:
        """Reinicia el core de Home Assistant.

        Siempre requiere confirmation_token. Verifica que no hay
        escrituras en /config sin validar antes de ejecutar.

        Primera llamada: preview + token.
        Segunda llamada: reinicia HA core.

        Args:
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"result": "ok"} si el restart se inició.
        """
        tool_name = "sv_restart_core"
        args: dict[str, Any] = {}

        if not confirmation_token:
            # Verificar check_config_state antes de dar el preview
            allowed, reason = _check_restart_allowed()
            try:
                core_info = await ha_client.sv_request("GET", "/core/info")
                version = core_info.get("version") if isinstance(core_info, dict) else None
            except HAConnectionError:
                version = None

            preview: dict[str, Any] = {
                "action": "restart_core",
                "current_version": version,
                "warning": (
                    "This will restart Home Assistant core. "
                    "All integrations and automations will be temporarily unavailable."
                ),
            }
            if not allowed:
                preview["blocked"] = reason
                preview["note"] = (
                    "Restart blocked: call sv_check_core_config first to clear the block."
                )
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        # Verificar de nuevo justo antes de ejecutar
        allowed, reason = _check_restart_allowed()
        if not allowed:
            await complete_confirmation_token(confirmation_token, success=False, error=reason)
            return {"error": reason}

        try:
            await ha_client.sv_request("POST", "/core/restart")
            result: dict[str, Any] = {"result": "ok"}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_restart_core_ok")
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_reboot_host(
        confirmation_token: str | None = None,
    ) -> object:
        """Reinicia el host HAOS completo.

        WARNING: esto reinicia toda la máquina HAOS — Hermes, HA core,
        todos los add-ons estarán inaccesibles varios minutos.

        Siempre requiere confirmation_token.

        Args:
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"result": "ok"} si el reboot se envió.
        """
        tool_name = "sv_reboot_host"
        args: dict[str, Any] = {}

        if not confirmation_token:
            preview: dict[str, Any] = {
                "action": "reboot_host",
                "warning": (
                    "WARNING: this reboots the entire HAOS host. "
                    "Hermes, HA core, and ALL add-ons will be unavailable "
                    "for several minutes. Recovery is automatic but takes time."
                ),
            }
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        try:
            await ha_client.sv_request("POST", "/host/reboot")
            result: dict[str, Any] = {"result": "ok", "note": "Host reboot initiated."}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_reboot_host_ok")
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}
