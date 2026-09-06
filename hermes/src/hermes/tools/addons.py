"""Hermes — Tools MCP para Add-ons del Supervisor.

Gestión de add-ons de HAOS vía Supervisor REST API.

Tools:
  sv_list_addons        — lista add-ons (instalados o todos del store)
  sv_get_addon          — info completa de un add-on
  sv_get_addon_options  — opciones actuales de configuración
  sv_set_addon_options  — actualiza opciones (siempre requiere token)
  sv_start_addon        — arranca un add-on (siempre requiere token)
  sv_stop_addon         — para un add-on (siempre requiere token)
  sv_restart_addon      — reinicia un add-on (siempre requiere token)
  sv_install_addon      — instala desde el store (token + async job)
  sv_uninstall_addon    — desinstala (token + async job)
  sv_update_addon       — actualiza a la última versión (token + async job)
  sv_get_addon_logs     — logs recientes (REDACTADOS de secretos)
  sv_get_addon_stats    — CPU / RAM / red del add-on

Auto-protección: si el slug del add-on objetivo es el propio Hermes
(local_hermes), las operaciones destructivas incluyen una advertencia
explícita en el preview.

Redacción de logs: todos los logs pasan por security.redact_secrets()
antes de ser devueltos al cliente MCP. Mosquitto, Zigbee2MQTT, MariaDB
y similares pueden incluir contraseñas y tokens en texto claro.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    redact_structure,
    complete_confirmation_token,
    create_confirmation_token,
    redact_secrets,
    validate_confirmation_token,
)
from hermes.tools._validation import InvalidIdentifier, validate_slug

logger = structlog.get_logger(__name__)

# Slug del propio add-on, para avisar antes de que Hermes se apague a sí mismo.
#
# No se puede fijar a una constante: el Supervisor le pone al slug un prefijo
# que depende de DÓNDE está instalado el add-on. En una carpeta local es
# `local_hermes`; instalado desde un repositorio es `<hash del repo>_hermes`,
# y ese hash es distinto en cada repositorio. Comparar contra `local_hermes` a
# secas hacía que el aviso no saltara nunca salvo en una instalación local.
#
# El Supervisor pone el hostname del contenedor igual que el slug pero con
# guiones, así que de ahí sale el valor real. Si no estuviera disponible, se
# cae a reconocer cualquier slug que termine en `hermes`.
_HERMES_SLUG = (os.environ.get("HOSTNAME") or "local-hermes").replace("-", "_").lower()

# Timeout largo para operaciones de instalación/actualización/desinstalación
_LONG_OP_TIMEOUT = 300.0  # 5 minutos


def _es_hermes(slug: str) -> bool:
    """True si el slug apunta al propio Hermes, esté instalado como esté."""
    s = slug.lower()
    return s == _HERMES_SLUG or s == "hermes" or s.endswith("_hermes")


def _self_warning(slug: str, action: str) -> str | None:
    """Devuelve un aviso de auto-daño si el slug es el propio Hermes."""
    if _es_hermes(slug):
        return (
            f"WARNING: {action} targets Hermes itself (slug={slug!r}). "
            "After this operation Hermes will be unavailable. "
            "Manual recovery via Supervisor UI will be required."
        )
    return None


def _addon_summary(addon: dict[str, Any]) -> dict[str, Any]:
    """Extrae campos relevantes de un objeto add-on del Supervisor."""
    return {
        "slug": addon.get("slug"),
        "name": addon.get("name"),
        "version": addon.get("version"),
        "version_latest": addon.get("version_latest"),
        "state": addon.get("state"),
        "update_available": addon.get("update_available"),
        "repository": addon.get("repository"),
        "description": addon.get("description"),
    }


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de add-ons en la instancia MCP."""

    def _bad_slug(slug: str) -> dict[str, Any] | None:
        """Valida el slug del add-on antes de interpolarlo en una URL REST."""
        try:
            validate_slug(slug, field="slug")
            return None
        except InvalidIdentifier as exc:
            return {"error": "invalid_identifier", "detail": str(exc)}

    @mcp.tool()
    async def sv_list_addons(installed_only: bool = True) -> object:
        """Lista los add-ons de Home Assistant.

        Args:
            installed_only: Si True (default), solo devuelve los add-ons
                instalados. Si False, incluye también los del store
                (puede ser una lista larga).

        Returns:
            {"addons": [...], "count": N}
            Cada item: slug, name, version, version_latest, state,
            update_available, repository, description.
        """
        try:
            data = await ha_client.sv_request("GET", "/addons")
            addons = data.get("addons", []) if isinstance(data, dict) else []
            if installed_only:
                addons = [a for a in addons if a.get("installed") is not False and a.get("version")]
            summaries = [_addon_summary(a) for a in addons]
            return {"addons": summaries, "count": len(summaries)}
        except HAConnectionError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_get_addon(slug: str, include_long_description: bool = False) -> object:
        """Devuelve información detallada de un add-on instalado.

        Args:
            slug: Identificador del add-on (ej. 'core_mosquitto',
                  'a0d7b954_tailscale', 'local_hermes').
            include_long_description: Incluir el README completo del add-on.
                  Por defecto NO: en add-ons con documentación larga son
                  decenas de miles de caracteres que rara vez se necesitan.

        Returns:
            Información completa: slug, name, version, version_latest,
            state, update_available, description, repository, boot,
            auto_update, protected, hostname, y otros campos del Supervisor.
            El README va aparte, bajo `long_description_omitted`, salvo que se
            pida expresamente.
        """
        if (err := _bad_slug(slug)):
            return err
        try:
            data = await ha_client.sv_request("GET", f"/addons/{slug}/info")
            if isinstance(data, dict):
                # /addons/{slug}/info incluye el bloque `options` del add-on,
                # con sus secretos en claro. Nunca devolverlo sin redactar.
                data = redact_structure(data)
                if not include_long_description and isinstance(data, dict):
                    # `long_description` es el README entero del add-on:
                    # suele ser la mayor parte de la respuesta y casi nunca se
                    # necesita. Devolverlo se pagaría en cada llamada aunque
                    # nadie lo mirase, desplazando contexto útil.
                    readme = data.pop("long_description", None)
                    if readme is not None:
                        data["long_description_omitted"] = {
                            "bytes": len(readme) if isinstance(readme, str) else 0,
                            "hint": (
                                "README completo del add-on. Vuelve a llamar con "
                                "include_long_description=True si lo necesitas."
                            ),
                        }
                return data
            return {"error": "unexpected_response", "raw": str(data)}
        except HAConnectionError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_get_addon_options(slug: str) -> object:
        """Devuelve las opciones actuales de configuración de un add-on.

        Devuelve las opciones tal como el usuario las tiene configuradas
        (el formulario del add-on en la UI de HAOS).

        Args:
            slug: Identificador del add-on.

        Returns:
            Objeto con las opciones actuales del add-on.
        """
        if (err := _bad_slug(slug)):
            return err
        try:
            data = await ha_client.sv_request("GET", f"/addons/{slug}/options/config")
            # Esta tool devuelve opciones por definición: redactar es
            # obligatorio, no opcional.
            data = redact_structure(data)
            return data if isinstance(data, dict) else {"options": data}
        except HAConnectionError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_set_addon_options(
        slug: str,
        options: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Actualiza las opciones de configuración de un add-on.

        Siempre requiere confirmation_token — cambiar opciones puede
        interrumpir un add-on en producción.

        Primera llamada (sin token): devuelve preview con las opciones
        actuales vs. las nuevas + confirmation_token.
        Segunda llamada (con token): aplica los cambios.

        Args:
            slug: Identificador del add-on.
            options: JSON string con el objeto de opciones a establecer.
                     Pasa solo los campos que quieres cambiar; el resto
                     se mantiene como está.
            confirmation_token: Token obtenido del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token válido: {"result": "ok"}
        """
        if (err := _bad_slug(slug)):
            return err
        try:
            opts_dict = json.loads(options) if isinstance(options, str) else options
        except json.JSONDecodeError as exc:
            return {"error": f"options must be valid JSON: {exc}"}

        tool_name = "sv_set_addon_options"
        args: dict[str, Any] = {"slug": slug, "options": options}

        if not confirmation_token:
            # Obtener opciones actuales para el preview
            try:
                current_opts = await ha_client.sv_request(
                    "GET", f"/addons/{slug}/options/config"
                )
            except HAConnectionError:
                current_opts = None

            warning = _self_warning(slug, "changing options of")
            preview: dict[str, Any] = {
                "slug": slug,
                # Redactado igual que en sv_get_addon_options: este preview
                # lee las opciones ACTUALES del add-on, así que sin redactar
                # filtraría los secretos en claro por la puerta de atrás de la
                # tool de escritura.
                "current_options": redact_structure(current_opts),
                # `new_options` es lo que envió el propio llamante: devolverlo no
                # añade información que no tuviera ya, y verlo es justo el punto
                # de un preview antes de confirmar.
                "new_options": opts_dict,
            }
            if warning:
                preview["warning"] = warning
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(
            confirmation_token, tool_name, args
        )
        if not valid:
            return {"error": error}

        try:
            await ha_client.sv_request(
                "POST", f"/addons/{slug}/options", json_body={"options": opts_dict}
            )
            result: dict[str, Any] = {"result": "ok", "slug": slug}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_set_addon_options_ok", slug=slug)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_start_addon(
        slug: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Arranca un add-on detenido.

        Siempre requiere confirmation_token.
        Primera llamada: devuelve preview + token.
        Segunda llamada: arranca el add-on.

        Args:
            slug: Identificador del add-on.
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"result": "ok"}
        """
        if (err := _bad_slug(slug)):
            return err
        tool_name = "sv_start_addon"
        args: dict[str, Any] = {"slug": slug}

        if not confirmation_token:
            try:
                info = await ha_client.sv_request("GET", f"/addons/{slug}/info")
                state = info.get("state") if isinstance(info, dict) else None
            except HAConnectionError:
                state = None
            preview: dict[str, Any] = {"slug": slug, "current_state": state, "action": "start"}
            w = _self_warning(slug, "starting")
            if w:
                preview["warning"] = w
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        try:
            await ha_client.sv_request("POST", f"/addons/{slug}/start")
            result: dict[str, Any] = {"result": "ok", "slug": slug}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_start_addon_ok", slug=slug)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_stop_addon(
        slug: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Para un add-on en ejecución.

        Siempre requiere confirmation_token. Si el add-on objetivo es
        Hermes mismo, el preview incluye una advertencia crítica.

        Args:
            slug: Identificador del add-on.
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"result": "ok"}
        """
        if (err := _bad_slug(slug)):
            return err
        tool_name = "sv_stop_addon"
        args: dict[str, Any] = {"slug": slug}

        if not confirmation_token:
            try:
                info = await ha_client.sv_request("GET", f"/addons/{slug}/info")
                state = info.get("state") if isinstance(info, dict) else None
            except HAConnectionError:
                state = None
            preview: dict[str, Any] = {"slug": slug, "current_state": state, "action": "stop"}
            w = _self_warning(slug, "stopping")
            if w:
                preview["warning"] = w
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        try:
            await ha_client.sv_request("POST", f"/addons/{slug}/stop")
            result: dict[str, Any] = {"result": "ok", "slug": slug}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_stop_addon_ok", slug=slug)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_restart_addon(
        slug: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Reinicia un add-on.

        Siempre requiere confirmation_token. Si el add-on objetivo es
        Hermes mismo, el preview incluye una advertencia crítica.

        Args:
            slug: Identificador del add-on.
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"result": "ok"}
        """
        if (err := _bad_slug(slug)):
            return err
        tool_name = "sv_restart_addon"
        args: dict[str, Any] = {"slug": slug}

        if not confirmation_token:
            try:
                info = await ha_client.sv_request("GET", f"/addons/{slug}/info")
                state = info.get("state") if isinstance(info, dict) else None
            except HAConnectionError:
                state = None
            preview: dict[str, Any] = {"slug": slug, "current_state": state, "action": "restart"}
            w = _self_warning(slug, "restarting")
            if w:
                preview["warning"] = w
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        try:
            await ha_client.sv_request("POST", f"/addons/{slug}/restart")
            result: dict[str, Any] = {"result": "ok", "slug": slug}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_restart_addon_ok", slug=slug)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_install_addon(
        slug: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Instala un add-on del store de HAOS.

        Operación larga — devuelve inmediatamente un job_id.
        Usa sv_get_job_status(job_id) para consultar el progreso.

        Args:
            slug: Identificador del add-on en el store.
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"job_id": "...", "status": "running",
                        "poll_with": "sv_get_job_status"}
        """
        if (err := _bad_slug(slug)):
            return err
        tool_name = "sv_install_addon"
        args: dict[str, Any] = {"slug": slug}

        if not confirmation_token:
            preview: dict[str, Any] = {
                "slug": slug,
                "action": "install",
                "note": "This operation may take several minutes.",
            }
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        try:
            data = await ha_client.sv_request(
                "POST",
                f"/store/addons/{slug}/install",
                json_body={"background": True},
                timeout_seconds=_LONG_OP_TIMEOUT,
            )
            job_id = data.get("job_id") if isinstance(data, dict) else None
            if job_id:
                await _track_job(job_id, {"op": "install_addon", "slug": slug})
                result: dict[str, Any] = {
                    "job_id": job_id,
                    "status": "running",
                    "poll_with": "sv_get_job_status",
                }
            else:
                result = {"result": "ok", "slug": slug}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_install_addon_started", slug=slug, job_id=job_id)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_uninstall_addon(
        slug: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Desinstala un add-on de HAOS.

        WARNING: la desinstalación elimina todos los datos del add-on
        en /data por defecto. Lee la documentación del add-on antes de
        confirmar si necesitas conservar los datos.

        Operación larga — devuelve job_id. Usa sv_get_job_status(job_id).

        Args:
            slug: Identificador del add-on.
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"job_id": "...", "status": "running",
                        "poll_with": "sv_get_job_status"}
        """
        if (err := _bad_slug(slug)):
            return err
        tool_name = "sv_uninstall_addon"
        args: dict[str, Any] = {"slug": slug}

        if not confirmation_token:
            try:
                info = await ha_client.sv_request("GET", f"/addons/{slug}/info")
                version = info.get("version") if isinstance(info, dict) else None
            except HAConnectionError:
                version = None
            preview: dict[str, Any] = {
                "slug": slug,
                "version": version,
                "action": "uninstall",
                "warning": (
                    "By default uninstall removes ALL add-on data in /data. "
                    "Read the add-on docs before confirming if you need to preserve data."
                ),
            }
            w = _self_warning(slug, "uninstalling")
            if w:
                preview["critical_warning"] = w
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        try:
            data = await ha_client.sv_request(
                "POST",
                f"/addons/{slug}/uninstall",
                timeout_seconds=_LONG_OP_TIMEOUT,
            )
            job_id = data.get("job_id") if isinstance(data, dict) else None
            if job_id:
                await _track_job(job_id, {"op": "uninstall_addon", "slug": slug})
                result: dict[str, Any] = {
                    "job_id": job_id,
                    "status": "running",
                    "poll_with": "sv_get_job_status",
                }
            else:
                result = {"result": "ok", "slug": slug}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_uninstall_addon_started", slug=slug, job_id=job_id)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_update_addon(
        slug: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Actualiza un add-on a la versión más reciente disponible.

        Operación larga — devuelve job_id. Usa sv_get_job_status(job_id).

        Args:
            slug: Identificador del add-on.
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"job_id": "...", "status": "running",
                        "poll_with": "sv_get_job_status"}
        """
        if (err := _bad_slug(slug)):
            return err
        tool_name = "sv_update_addon"
        args: dict[str, Any] = {"slug": slug}

        if not confirmation_token:
            try:
                info = await ha_client.sv_request("GET", f"/addons/{slug}/info")
                if isinstance(info, dict):
                    current = info.get("version")
                    latest = info.get("version_latest")
                    avail = info.get("update_available", False)
                else:
                    current = latest = avail = None
            except HAConnectionError:
                current = latest = avail = None

            preview: dict[str, Any] = {
                "slug": slug,
                "current_version": current,
                "version_latest": latest,
                "update_available": avail,
            }
            if not avail and avail is not None:
                preview["note"] = "No update available at this time."
            w = _self_warning(slug, "updating")
            if w:
                preview["warning"] = w
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        try:
            data = await ha_client.sv_request(
                "POST",
                f"/store/addons/{slug}/update",
                json_body={"background": True},
                timeout_seconds=_LONG_OP_TIMEOUT,
            )
            job_id = data.get("job_id") if isinstance(data, dict) else None
            if job_id:
                await _track_job(job_id, {"op": "update_addon", "slug": slug})
                result: dict[str, Any] = {
                    "job_id": job_id,
                    "status": "running",
                    "poll_with": "sv_get_job_status",
                }
            else:
                result = {"result": "ok", "slug": slug}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_update_addon_started", slug=slug, job_id=job_id)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_get_addon_logs(slug: str, lines: int = 100) -> object:
        """Lee los logs recientes de un add-on.

        Los logs se REDACTAN automáticamente antes de ser devueltos:
        passwords, tokens, JWT, URLs con auth básica son sustituidos
        por ***REDACTED*** / ***JWT_REDACTED***.

        Args:
            slug: Identificador del add-on.
            lines: Número de líneas a devolver (default 100, máx 1000).

        Returns:
            {"slug": "...", "lines_requested": N, "redacted": bool,
             "logs": "texto del log"}
            `lines_requested` es el número pedido después de acotarlo a
            [1, 1000]; el log devuelto puede traer menos líneas si el add-on
            no tiene más.
        """
        if (err := _bad_slug(slug)):
            return err
        lines = min(max(1, lines), 1000)
        try:
            raw = await ha_client.sv_request_text(
                f"/addons/{slug}/logs",
                params={"lines": str(lines)},
            )
        except HAConnectionError as exc:
            return {"error": str(exc)}

        redacted = redact_secrets(raw)
        was_redacted = redacted != raw
        logger.info(
            "sv_get_addon_logs",
            slug=slug,
            lines=lines,
            bytes=len(raw),
            redacted=was_redacted,
        )
        return {
            "slug": slug,
            "lines_requested": lines,
            "redacted": was_redacted,
            "logs": redacted,
        }

    @mcp.tool()
    async def sv_get_addon_stats(slug: str) -> object:
        """Devuelve estadísticas de recursos de un add-on (CPU, RAM, red).

        Args:
            slug: Identificador del add-on.

        Returns:
            {"cpu_percent": ..., "memory_usage": ..., "memory_limit": ...,
             "network_tx": ..., "network_rx": ...,
             "disk_read": ..., "disk_write": ...}
        """
        if (err := _bad_slug(slug)):
            return err
        try:
            data = await ha_client.sv_request("GET", f"/addons/{slug}/stats")
            return data if isinstance(data, dict) else {"raw": data}
        except HAConnectionError as exc:
            return {"error": str(exc)}


# ── Job tracking helpers ──────────────────────────────────────────────────────
# Compartido entre addons.py y backups.py a través de importación directa.
# Fichero de estado: /data/pending_jobs.json

_PENDING_JOBS_PATH = Path("/data/pending_jobs.json")
_jobs_lock = asyncio.Lock()
_JOB_CLEANUP_AFTER_SECONDS = 3600  # 1 hora


def _load_jobs_sync() -> dict[str, Any]:
    try:
        return json.loads(_PENDING_JOBS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_jobs_sync(jobs: dict[str, Any]) -> None:
    tmp = _PENDING_JOBS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_PENDING_JOBS_PATH)


async def _track_job(job_id: str, meta: dict[str, Any]) -> None:
    """Persiste un job en vuelo en pending_jobs.json."""
    _PENDING_JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with _jobs_lock:
        jobs = _load_jobs_sync()
        jobs[job_id] = {
            **meta,
            "started_at": time.time(),
            "status": "running",
        }
        # Limpiar jobs viejos (>1h)
        cutoff = time.time() - _JOB_CLEANUP_AFTER_SECONDS
        jobs = {k: v for k, v in jobs.items() if v.get("started_at", 0) > cutoff}
        jobs[job_id] = {**meta, "started_at": time.time(), "status": "running"}
        _write_jobs_sync(jobs)
