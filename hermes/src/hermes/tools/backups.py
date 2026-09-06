"""Hermes — Tools MCP para Backups del Supervisor.

Gestión de backups de HAOS vía Supervisor REST API.

Tools:
  sv_list_backups          — lista backups disponibles
  sv_get_backup            — info detallada de un backup
  sv_create_backup_full    — crea backup completo (async, sin token)
  sv_create_backup_partial — crea backup parcial (async, sin token)
  sv_create_safety_backup  — wrapper de create_backup_full con cooldown
  sv_delete_backup         — elimina un backup (siempre requiere token)
  sv_restore_backup_full   — restaura backup completo (token + advertencia)
  sv_restore_backup_partial— restaura backup parcial (token + advertencia)
  sv_get_job_status        — consulta estado de un job en curso
  sv_list_pending_jobs     — jobs lanzados por Hermes en la última hora

Modo async (MODE A): todas las operaciones largas usan background=True.
El Supervisor devuelve inmediatamente un job_id. El cliente debe pollear
con sv_get_job_status(job_id) hasta ver done=True.

Safety backup: sv_create_safety_backup respeta safety_backup_window_minutes.
Si el último safety backup fue hace menos del window, devuelve referencia
al existente sin crear uno nuevo. Límite duro: nunca <60s entre safety
backups consecutivos.
"""

from __future__ import annotations

import json
from datetime import datetime
import time
from pathlib import Path
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    validate_confirmation_token,
)
from hermes.tools.addons import _PENDING_JOBS_PATH, _jobs_lock, _load_jobs_sync, _track_job, _write_jobs_sync
from hermes.tools._validation import InvalidIdentifier, validate_identifier, validate_slug

logger = structlog.get_logger(__name__)

_LONG_OP_TIMEOUT = 300.0  # 5 min
_SAFETY_BACKUP_STATE_PATH = Path("/data/last_safety_backup.json")
_SAFETY_BACKUP_MIN_INTERVAL_SECONDS = 60  # límite duro absoluto


def _load_safety_state() -> dict[str, Any]:
    try:
        return json.loads(_SAFETY_BACKUP_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# Clave canónica de la marca de tiempo del último safety backup, en segundos
# epoch. Hay DOS caminos que crean safety backups —la tool `sv_create_safety_
# backup` y el disparo automático antes de escribir en /config— y comparten
# este fichero de estado. Usar cada uno su propia clave, con un guardado que
# reemplazaba el documento entero, hacía que cada camino borrara la marca del
# otro: ambos veían "nunca se hizo ninguno" y disparaban un backup COMPLETO de
# varios GB, saltándose tanto la ventana configurable como el límite duro.
_MARCA = "last_safety_backup_at"

# Claves que usaron versiones anteriores. Se leen para no perder la marca de
# una instalación que ya venía funcionando.
_MARCAS_ANTIGUAS = ("last_created_at", "last_completed_at")


def _leer_marca(state: dict[str, Any]) -> float:
    """Momento del último safety backup, en epoch. 0 si no hay ninguno.

    Tolera los dos formatos que han existido: epoch numérico e ISO-8601.
    """
    for clave in (_MARCA, *_MARCAS_ANTIGUAS):
        valor = state.get(clave)
        if isinstance(valor, (int, float)) and valor > 0:
            return float(valor)
        if isinstance(valor, str) and valor:
            try:
                return datetime.fromisoformat(valor.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
    return 0.0


def _save_safety_state(state: dict[str, Any]) -> None:
    """Funde los campos nuevos con los que ya hubiera en disco.

    Reemplazar el documento entero es lo que permitía que un camino borrara la
    marca del otro.
    """
    actual = _load_safety_state()
    actual.update(state)
    _SAFETY_BACKUP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SAFETY_BACKUP_STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(actual, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_SAFETY_BACKUP_STATE_PATH)


def register(
    mcp: object,
    ha_client: HAClient,
    safety_backup_window_minutes: int = 30,
) -> None:
    """Registra las tools de backups en la instancia MCP."""

    def _bad_slug(slug: str) -> dict[str, Any] | None:
        try:
            validate_slug(slug, field="slug")
            return None
        except InvalidIdentifier as exc:
            return {"error": "invalid_identifier", "detail": str(exc)}

    def _bad_job(job_id: str) -> dict[str, Any] | None:
        try:
            validate_identifier(job_id, field="job_id")
            return None
        except InvalidIdentifier as exc:
            return {"error": "invalid_identifier", "detail": str(exc)}

    @mcp.tool()
    async def sv_list_backups() -> object:
        """Lista los backups disponibles en HAOS.

        Returns:
            {"backups": [...], "count": N}
            Cada item: slug, name, date, type (full/partial),
            size_mb, protected.
        """
        try:
            data = await ha_client.sv_request("GET", "/backups")
            backups = data.get("backups", []) if isinstance(data, dict) else []
            summaries = [
                {
                    "slug": b.get("slug"),
                    "name": b.get("name"),
                    "date": b.get("date"),
                    "type": b.get("type"),
                    "size_mb": round(b.get("size", 0) / (1024 * 1024), 2) if b.get("size") else None,
                    "protected": b.get("protected", False),
                    "location": b.get("location"),
                }
                for b in backups
            ]
            return {"backups": summaries, "count": len(summaries)}
        except HAConnectionError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_get_backup(slug: str) -> object:
        """Devuelve información detallada de un backup.

        Args:
            slug: Identificador del backup (hash hexadecimal).

        Returns:
            Metadata completa: name, date, type, size, homeassistant
            version, add-ons incluidos, carpetas incluidas.
        """
        if (err := _bad_slug(slug)):
            return err
        try:
            data = await ha_client.sv_request("GET", f"/backups/{slug}/info")
            return data if isinstance(data, dict) else {"raw": data}
        except HAConnectionError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_create_backup_full(
        name: str,
        password: str | None = None,
    ) -> object:
        """Crea un backup completo de HAOS.

        Operación larga — devuelve job_id inmediatamente.
        Usa sv_get_job_status(job_id) para consultar el progreso.
        No requiere confirmation_token — crear backups es defensivo.

        Args:
            name: Nombre descriptivo del backup.
            password: Contraseña opcional para cifrar el backup.

        Returns:
            {"job_id": "...", "status": "running",
             "poll_with": "sv_get_job_status"}
        """
        payload: dict[str, Any] = {"name": name, "background": True}
        if password:
            payload["password"] = password

        try:
            data = await ha_client.sv_request(
                "POST", "/backups/new/full",
                json_body=payload,
                timeout_seconds=_LONG_OP_TIMEOUT,
            )
            job_id = data.get("job_id") if isinstance(data, dict) else None
            if job_id:
                await _track_job(job_id, {"op": "create_backup_full", "name": name})
                logger.info("sv_create_backup_full_started", name=name, job_id=job_id)
                return {
                    "job_id": job_id,
                    "status": "running",
                    "poll_with": "sv_get_job_status",
                }
            # Backup completado sincrónicamente (no debería ocurrir con background=True)
            slug = data.get("slug") if isinstance(data, dict) else None
            return {"result": "ok", "slug": slug}
        except HAConnectionError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_create_backup_partial(
        name: str,
        addons: str | None = None,
        folders: str | None = None,
        password: str | None = None,
        include_homeassistant: bool = True,
    ) -> object:
        """Crea un backup parcial de HAOS.

        Operación larga — devuelve job_id inmediatamente.
        No requiere confirmation_token.

        Args:
            name: Nombre descriptivo del backup.
            addons: JSON array de slugs de add-ons a incluir,
                    ej. '["core_mosquitto", "local_hermes"]'.
                    Si null, no incluye add-ons.
            folders: JSON array de carpetas a incluir,
                     ej. '["homeassistant", "share", "ssl"]'.
                     Si null, no incluye carpetas extra.
            password: Contraseña opcional para cifrar el backup.
            include_homeassistant: Si incluir la configuración de HA
                                   core (default True).

        Returns:
            {"job_id": "...", "status": "running",
             "poll_with": "sv_get_job_status"}
        """
        payload: dict[str, Any] = {
            "name": name,
            "background": True,
            "homeassistant": include_homeassistant,
        }
        if password:
            payload["password"] = password
        if addons:
            try:
                payload["addons"] = json.loads(addons)
            except json.JSONDecodeError as exc:
                return {"error": f"addons must be a JSON array: {exc}"}
        if folders:
            try:
                payload["folders"] = json.loads(folders)
            except json.JSONDecodeError as exc:
                return {"error": f"folders must be a JSON array: {exc}"}

        try:
            data = await ha_client.sv_request(
                "POST", "/backups/new/partial",
                json_body=payload,
                timeout_seconds=_LONG_OP_TIMEOUT,
            )
            job_id = data.get("job_id") if isinstance(data, dict) else None
            if job_id:
                await _track_job(job_id, {"op": "create_backup_partial", "name": name})
                logger.info("sv_create_backup_partial_started", name=name, job_id=job_id)
                return {
                    "job_id": job_id,
                    "status": "running",
                    "poll_with": "sv_get_job_status",
                }
            slug = data.get("slug") if isinstance(data, dict) else None
            return {"result": "ok", "slug": slug}
        except HAConnectionError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_create_safety_backup() -> object:
        """Crea un backup completo de seguridad antes de operaciones destructivas.

        Wrapper de sv_create_backup_full con nombre automático
        hermes-safety-<timestamp>. Operación larga: devuelve job_id.

        Cooldown: si el último safety backup fue hace menos de
        `safety_backup_window_minutes` (opción del add-on, 30 por defecto),
        devuelve una referencia al existente sin crear uno nuevo. Límite duro:
        nunca menos de 60 segundos entre safety backups consecutivos.

        No requiere confirmation_token — crear backups es defensivo.

        Returns:
            Si reutiliza uno reciente: {"reused": true, "job_id"|"slug": ...}.
            Si crea uno nuevo: {"job_id": "...", "status": "running",
            "poll_with": "sv_get_job_status"}.
        """
        now = time.time()
        state = _load_safety_state()
        last_ts = _leer_marca(state)
        last_job = state.get("last_job_id")
        last_slug = state.get("last_slug")

        # Límite duro: nunca <60s entre safety backups
        if now - last_ts < _SAFETY_BACKUP_MIN_INTERVAL_SECONDS:
            return {
                "reused": True,
                "reason": "hard_limit",
                "last_created_at": last_ts,
                "job_id": last_job,
                "slug": last_slug,
            }

        # Cooldown por ventana configurable
        window_seconds = safety_backup_window_minutes * 60
        if now - last_ts < window_seconds:
            return {
                "reused": True,
                "reason": "within_window",
                "window_minutes": safety_backup_window_minutes,
                "last_created_at": last_ts,
                "job_id": last_job,
                "slug": last_slug,
            }

        ts_label = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now))
        backup_name = f"hermes-safety-{ts_label}"

        try:
            data = await ha_client.sv_request(
                "POST", "/backups/new/full",
                json_body={"name": backup_name, "background": True},
                timeout_seconds=_LONG_OP_TIMEOUT,
            )
            job_id = data.get("job_id") if isinstance(data, dict) else None
            slug = data.get("slug") if isinstance(data, dict) else None

            new_state = {
                _MARCA: now,
                "last_job_id": job_id,
                "last_slug": slug,
                "backup_name": backup_name,
            }
            _save_safety_state(new_state)

            if job_id:
                await _track_job(job_id, {"op": "create_safety_backup", "name": backup_name})
                logger.info("sv_create_safety_backup_started", name=backup_name, job_id=job_id)
                return {
                    "reused": False,
                    "job_id": job_id,
                    "status": "running",
                    "backup_name": backup_name,
                    "poll_with": "sv_get_job_status",
                }
            return {"reused": False, "result": "ok", "slug": slug, "backup_name": backup_name}
        except HAConnectionError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_delete_backup(
        slug: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina un backup de HAOS.

        Siempre requiere confirmation_token.

        Args:
            slug: Identificador del backup (hash hexadecimal).
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"result": "ok"}
        """
        if (err := _bad_slug(slug)):
            return err
        tool_name = "sv_delete_backup"
        args: dict[str, Any] = {"slug": slug}

        if not confirmation_token:
            try:
                info = await ha_client.sv_request("GET", f"/backups/{slug}/info")
                name = info.get("name") if isinstance(info, dict) else None
                bdate = info.get("date") if isinstance(info, dict) else None
                btype = info.get("type") if isinstance(info, dict) else None
            except HAConnectionError:
                name = bdate = btype = None
            preview: dict[str, Any] = {
                "slug": slug,
                "name": name,
                "date": bdate,
                "type": btype,
                "action": "delete",
            }
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        try:
            await ha_client.sv_request("DELETE", f"/backups/{slug}")
            result: dict[str, Any] = {"result": "ok", "slug": slug}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_delete_backup_ok", slug=slug)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_restore_backup_full(
        slug: str,
        confirmation_token: str | None = None,
        password: str | None = None,
    ) -> object:
        """Restaura un backup completo de HAOS.

        WARNING CRÍTICO: esto sobreescribe HA core, todos los add-ons y
        todos los datos. El estado actual se PIERDE. Hermes mismo será
        reemplazado por la versión del backup — si esa versión está rota,
        se necesitará intervención manual.

        Operación larga — devuelve job_id. Usa sv_get_job_status(job_id).

        Args:
            slug: Identificador del backup.
            confirmation_token: Token del preview anterior.
            password: Contraseña del backup si está cifrado.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"job_id": "...", "status": "running",
                        "poll_with": "sv_get_job_status"}
        """
        if (err := _bad_slug(slug)):
            return err
        tool_name = "sv_restore_backup_full"
        args: dict[str, Any] = {"slug": slug, "password": password}

        if not confirmation_token:
            try:
                info = await ha_client.sv_request("GET", f"/backups/{slug}/info")
                name = info.get("name") if isinstance(info, dict) else None
                bdate = info.get("date") if isinstance(info, dict) else None
                ha_version = (
                    info.get("homeassistant") if isinstance(info, dict) else None
                )
            except HAConnectionError:
                name = bdate = ha_version = None
            preview: dict[str, Any] = {
                "slug": slug,
                "name": name,
                "date": bdate,
                "homeassistant_version": ha_version,
                "action": "restore_full",
                "warning": (
                    "WARNING: this overwrites HA core, ALL add-ons, and ALL data. "
                    "The current state will be PERMANENTLY LOST. "
                    "Hermes itself will be replaced by the version in the backup. "
                    "Recovery requires manual intervention if the restored Hermes is broken."
                ),
            }
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        try:
            payload: dict[str, Any] = {"background": True}
            if password:
                payload["password"] = password
            data = await ha_client.sv_request(
                "POST", f"/backups/{slug}/restore/full",
                json_body=payload,
                timeout_seconds=_LONG_OP_TIMEOUT,
            )
            job_id = data.get("job_id") if isinstance(data, dict) else None
            if job_id:
                await _track_job(job_id, {"op": "restore_backup_full", "slug": slug})
                result: dict[str, Any] = {
                    "job_id": job_id,
                    "status": "running",
                    "poll_with": "sv_get_job_status",
                }
            else:
                result = {"result": "ok"}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_restore_backup_full_started", slug=slug, job_id=job_id)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_restore_backup_partial(
        slug: str,
        confirmation_token: str | None = None,
        addons: str | None = None,
        folders: str | None = None,
        password: str | None = None,
        include_homeassistant: bool = False,
    ) -> object:
        """Restaura un backup parcial de HAOS.

        Siempre requiere confirmation_token. Operación larga → job_id.

        Args:
            slug: Identificador del backup.
            confirmation_token: Token del preview anterior.
            addons: JSON array de slugs de add-ons a restaurar.
            folders: JSON array de carpetas a restaurar.
            password: Contraseña del backup si está cifrado.
            include_homeassistant: Si restaurar la configuración de HA.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"job_id": "...", "status": "running",
                        "poll_with": "sv_get_job_status"}
        """
        if (err := _bad_slug(slug)):
            return err
        tool_name = "sv_restore_backup_partial"
        args: dict[str, Any] = {
            "slug": slug,
            "addons": addons,
            "folders": folders,
            "password": password,
            "include_homeassistant": include_homeassistant,
        }

        if not confirmation_token:
            try:
                info = await ha_client.sv_request("GET", f"/backups/{slug}/info")
                name = info.get("name") if isinstance(info, dict) else None
            except HAConnectionError:
                name = None
            preview: dict[str, Any] = {
                "slug": slug,
                "name": name,
                "addons_to_restore": addons,
                "folders_to_restore": folders,
                "include_homeassistant": include_homeassistant,
                "action": "restore_partial",
                "warning": (
                    "Selected components will be overwritten with the backup versions."
                ),
            }
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        payload: dict[str, Any] = {
            "background": True,
            "homeassistant": include_homeassistant,
        }
        if password:
            payload["password"] = password
        if addons:
            try:
                payload["addons"] = json.loads(addons)
            except json.JSONDecodeError as exc:
                await complete_confirmation_token(
                    confirmation_token, success=False, error=str(exc)
                )
                return {"error": f"addons must be a JSON array: {exc}"}
        if folders:
            try:
                payload["folders"] = json.loads(folders)
            except json.JSONDecodeError as exc:
                await complete_confirmation_token(
                    confirmation_token, success=False, error=str(exc)
                )
                return {"error": f"folders must be a JSON array: {exc}"}

        try:
            data = await ha_client.sv_request(
                "POST", f"/backups/{slug}/restore/partial",
                json_body=payload,
                timeout_seconds=_LONG_OP_TIMEOUT,
            )
            job_id = data.get("job_id") if isinstance(data, dict) else None
            if job_id:
                await _track_job(job_id, {"op": "restore_backup_partial", "slug": slug})
                result: dict[str, Any] = {
                    "job_id": job_id,
                    "status": "running",
                    "poll_with": "sv_get_job_status",
                }
            else:
                result = {"result": "ok"}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_restore_backup_partial_started", slug=slug, job_id=job_id)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_get_job_status(job_id: str) -> object:
        """Consulta el estado de un job asíncrono del Supervisor.

        Útil para pollear el progreso de operaciones largas:
        install/update/uninstall de add-ons, create/restore backups.

        Args:
            job_id: Identificador del job (UUID hex).

        Returns:
            {"job_id": "...", "name": "...", "done": bool,
             "progress": 0-100, "stage": "...", "reference": "..."}
            Cuando done=True, reference puede contener el slug del backup
            creado u otro identificador del resultado.
        """
        if (err := _bad_job(job_id)):
            return err
        try:
            data = await ha_client.sv_request("GET", f"/jobs/{job_id}")
            if not isinstance(data, dict):
                return {"error": "unexpected_response"}

            result: dict[str, Any] = {
                "job_id": job_id,
                "name": data.get("name"),
                "done": data.get("done", False),
                "progress": data.get("progress"),
                "stage": data.get("stage"),
                "reference": data.get("reference"),
                "child_jobs": data.get("child_jobs"),
            }

            # Si el job ha terminado, actualizar nuestro tracking local
            if data.get("done"):
                async with _jobs_lock:
                    jobs = _load_jobs_sync()
                    if job_id in jobs:
                        jobs[job_id]["status"] = "done"
                        jobs[job_id]["reference"] = data.get("reference")
                        _write_jobs_sync(jobs)

            return result
        except HAConnectionError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_list_pending_jobs() -> object:
        """Lista los jobs asíncronos que Hermes ha iniciado en la última hora.

        Lee /data/pending_jobs.json, que persiste entre reinicios del add-on:
        la lista NO se limita a la sesión actual. El filtro es la antigüedad
        —menos de 1 h desde `started_at`—, no el estado, así que incluye
        también jobs ya terminados, cada uno con su `status`. Para el estado
        actual de uno concreto usa sv_get_job_status(job_id).

        Returns:
            {"jobs": [...], "count": N}
            Cada item: job_id, op, slug, started_at, status.
        """
        async with _jobs_lock:
            jobs = _load_jobs_sync()

        # Filtrar jobs muy viejos (>1h) para la respuesta
        cutoff = time.time() - 3600
        active = [
            {
                "job_id": jid,
                **{k: v for k, v in meta.items() if k != "status"},
                "status": meta.get("status", "running"),
            }
            for jid, meta in jobs.items()
            if meta.get("started_at", 0) > cutoff
        ]
        return {"jobs": active, "count": len(active)}
