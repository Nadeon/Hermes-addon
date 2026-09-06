"""Hermes — Tools MCP para Filesystem /config (escritura).

Escribe ficheros de configuración de HA con capas completas de seguridad:
1. Backup automático antes de cada escritura (nunca excepción).
2. Atomic safe_write_file (preserva modo, encoding, BOM, line endings).
3. Rate limit doble: min_interval + max_per_minute.
4. Confirmation token para todas las operaciones (sin excepciones).
5. Fail-closed: si configuration.yaml es inválido, todos los .yaml exigen token.
6. Managed paths (.storage/**) rechazados incluso con token.
7. Safety backup opcional (desactivado por defecto) con ventana configurable.

Tools:
  fs_write_file       — escribe un fichero (siempre requiere token)
  fs_delete_file      — borra un fichero (siempre requiere token)
  fs_move_file        — renombra/mueve (siempre requiere token)
  fs_set_secret       — escribe en secrets.yaml (siempre requiere token)
  fs_list_file_backups— lista backups disponibles en /data/backups/normal/
  fs_restore_file_backup — restaura un backup anterior (siempre requiere token)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

import hermes.fs as _fs
from hermes.fs import (
    BlacklistedPathError,
    PathTraversalError,
    check_blacklisted,
    check_path_readable,
    normalize_path,
)
from hermes.fs_write import (
    BACKUPS_NORMAL_DIR,
    BACKUPS_SENSITIVE_DIR,
    MANAGED_PATH_ERROR,
    RateLimitError,
    backup_before_write,
    is_managed_path,
    maybe_trigger_safety_backup,
    record_config_write,
    reserve_write_slot,
    safe_write_file,
)
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    validate_confirmation_token,
)
from hermes.yaml_include import (
    check_executable_by_indirection,
    get_executable_warning,
    invalidate_include_cache,
    is_fail_closed,
)

logger = structlog.get_logger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────

_SECRETS_YAML_REL = "secrets.yaml"


def _current_config_base() -> Path:
    return _fs.CONFIG_BASE


# ── Helpers de preview ────────────────────────────────────────────────────────

async def _build_write_preview(
    abs_path: Path,
    new_content: str,
) -> dict[str, Any]:
    """Construye el dict de preview para fs_write_file."""
    config_base = _current_config_base()
    rel = _fs._rel_posix(abs_path)

    # ¿Tiene contenido actual?
    current: str | None = None
    if abs_path.exists():
        try:
            raw = abs_path.read_bytes()
            _, current = _fs.detect_encoding(raw)
        except (OSError, ValueError):
            current = None

    executable = await check_executable_by_indirection(abs_path)
    warning = get_executable_warning(abs_path)
    fail_closed = await is_fail_closed()

    preview: dict[str, Any] = {
        "action": "write_file",
        "path": rel,
        "new_content_length": len(new_content),
        "is_executable_by_indirection": executable,
        "fail_closed_active": fail_closed,
    }
    if current is not None:
        preview["current_content_length"] = len(current)
        preview["current_exists"] = True
    else:
        preview["current_exists"] = False

    if warning:
        preview["warning"] = warning
    if fail_closed and abs_path.suffix.lower() in (".yaml", ".yml"):
        preview["note"] = (
            "YAML include resolver is in fail-closed mode: "
            "configuration.yaml could not be parsed. "
            "All .yaml/.yml writes require confirmation."
        )

    return preview


# ══════════════════════════════════════════════════════════════════════════════
# Registro de tools
# ══════════════════════════════════════════════════════════════════════════════

def register_write(
    mcp: object,
    ha_client: Any,
    safety_backup_window_minutes: int = 30,
    safety_backup_enabled: bool = False,
    file_backup_max_per_path: int = 20,
    file_backup_max_total_mb: int = 100,
    config_write_min_interval_seconds: int = 5,
    config_write_max_per_minute: int = 10,
) -> None:
    """Registra las tools de escritura en /config."""

    # ── fs_write_file ─────────────────────────────────────────────────────────

    @mcp.tool()
    async def fs_write_file(
        path: str,
        content: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Escribe el contenido de un fichero bajo /config.

        SIEMPRE requiere confirmation_token:
        - Primera llamada (sin token): genera preview y devuelve token.
        - Segunda llamada (con token): escribe el fichero.

        El preview incluye:
        - current_exists: si el fichero ya existe.
        - is_executable_by_indirection: si el path puede ejecutar código HA.
        - warning: mensaje de seguridad específico para rutas críticas.
        - fail_closed_active: si el resolver YAML está en modo fail-closed.

        Rechaza:
        - Rutas fuera de /config (traversal).
        - Paths managed (.storage/**) — incluso con token.
                - Rate limit excedido.

        Args:
            path: Ruta relativa o absoluta bajo /config.
            content: Contenido UTF-8 a escribir.
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"result": "ok", "path": "...", "backup": "..." | null}
        """
        tool_name = "fs_write_file"

        # 1. Normalizar path (traversal check)
        try:
            abs_path = normalize_path(path)
        except PathTraversalError as exc:
            return json.dumps({"error": "traversal", "detail": str(exc)})

        # 2. Managed path — rechazado siempre, incluso con token
        if is_managed_path(abs_path):
            return json.dumps({
                "error": "managed_path",
                "path": _fs._rel_posix(abs_path),
                "reason": MANAGED_PATH_ERROR,
            })

        args = {"path": _fs._rel_posix(abs_path), "content": content}

        if not confirmation_token:
            # Verificar si el fichero está en la blacklist (secretos)
            blacklisted, reason = check_blacklisted(abs_path)
            if blacklisted and abs_path.name != _SECRETS_YAML_REL:
                # secrets.yaml usa fs_set_secret, no fs_write_file
                return json.dumps({
                    "error": "blacklisted",
                    "detail": reason,
                    "hint": "Use fs_set_secret to modify secrets.yaml.",
                })
            if abs_path.name == _SECRETS_YAML_REL:
                return json.dumps({
                    "error": "use_fs_set_secret",
                    "hint": "Use fs_set_secret to add or update secrets. "
                            "fs_write_file cannot write secrets.yaml.",
                })

            # Construir preview
            preview = await _build_write_preview(abs_path, content)
            return json.dumps(
                await create_confirmation_token(tool_name, args, preview=preview),
                ensure_ascii=False,
            )

        # === CON TOKEN ===

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return json.dumps({"error": error})

        # Verificar managed path de nuevo (defensa en profundidad)
        if is_managed_path(abs_path):
            await complete_confirmation_token(confirmation_token, success=False, error="managed_path")
            return json.dumps({"error": "managed_path", "reason": MANAGED_PATH_ERROR})

        # Rate limit
        try:
            await reserve_write_slot(
                config_write_min_interval_seconds,
                config_write_max_per_minute,
            )
        except RateLimitError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return json.dumps({
                "error": "rate_limited",
                "reason": exc.reason,
                "min_interval_seconds": exc.min_interval_seconds,
                "max_per_minute": exc.max_per_minute,
                "next_allowed_at": exc.next_allowed_at,
            })

        # Safety backup automático
        backup_err = await maybe_trigger_safety_backup(
            ha_client, safety_backup_window_minutes,
            enabled=safety_backup_enabled,
        )
        if backup_err:
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(backup_err)
            )
            return json.dumps({"error": "safety_backup_failed", "detail": str(backup_err)})

        # Backup del original
        backup_path = await backup_before_write(
            abs_path,
            file_backup_max_per_path=file_backup_max_per_path,
            file_backup_max_total_mb=file_backup_max_total_mb,
        )

        # Escribir
        try:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(safe_write_file, abs_path, content)
        except OSError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return json.dumps({"error": "io_error", "detail": str(exc)})

        # La plaza del rate limit ya se reservó al comprobarlo.
        await record_config_write()

        rel = _fs._rel_posix(abs_path)
        # El caché del árbol de includes se invalida SIEMPRE, no solo al tocar
        # configuration.yaml. El conjunto que guarda es «qué ficheros YAML son
        # ejecutables por indirección», y de él depende que una escritura pida
        # las protecciones extra o no. Cualquier fichero del árbol puede a su
        # vez traer includes —packages/, automations.yaml, lo que sea—, así que
        # un fichero recién metido en el árbol no estaría en el conjunto
        # cacheado y se trataría como inofensivo: una señal de seguridad
        # fallando en abierto. Volver a resolver el árbol es barato y solo
        # pasa después de escribir.
        invalidate_include_cache()

        result: dict[str, Any] = {
            "result": "ok",
            "path": rel,
            "backup": backup_path,
        }
        await complete_confirmation_token(confirmation_token, success=True, result=result)
        logger.info("fs_write_file_ok", path=rel, backup=backup_path)
        return json.dumps(result, ensure_ascii=False)

    # ── fs_delete_file ────────────────────────────────────────────────────────

    @mcp.tool()
    async def fs_delete_file(
        path: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Borra un fichero bajo /config.

        SIEMPRE requiere confirmation_token.
        El preview incluye el contenido actual (si el fichero es legible).

        Rechaza:
        - Paths fuera de /config (traversal).
        - Paths managed (.storage/**).
        - Rate limit excedido.

        Args:
            path: Ruta relativa o absoluta bajo /config.
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"result": "ok", "path": "...", "backup": "..." | null}
        """
        tool_name = "fs_delete_file"

        try:
            abs_path = normalize_path(path)
        except PathTraversalError as exc:
            return json.dumps({"error": "traversal", "detail": str(exc)})

        if is_managed_path(abs_path):
            return json.dumps({
                "error": "managed_path",
                "path": _fs._rel_posix(abs_path),
                "reason": MANAGED_PATH_ERROR,
            })

        args = {"path": _fs._rel_posix(abs_path)}

        if not confirmation_token:
            if not abs_path.exists():
                return json.dumps({"error": "not_found", "path": _fs._rel_posix(abs_path)})
            if abs_path.is_dir():
                return json.dumps({
                    "error": "is_directory",
                    "path": _fs._rel_posix(abs_path),
                    "hint": "fs_delete_file only deletes files, not directories.",
                })

            blacklisted, _ = check_blacklisted(abs_path)
            is_managed = is_managed_path(abs_path)
            executable = await check_executable_by_indirection(abs_path)

            preview: dict[str, Any] = {
                "action": "delete_file",
                "path": _fs._rel_posix(abs_path),
                "is_managed_path": is_managed,
                "is_executable_by_indirection": executable,
            }

            # Incluir contenido actual si es legible
            if not blacklisted:
                try:
                    raw = abs_path.read_bytes()
                    if not _fs.is_binary(raw[:8192]):
                        _, current = _fs.detect_encoding(raw)
                        preview["current_content"] = current
                except (OSError, ValueError):
                    pass

            warning = get_executable_warning(abs_path)
            if warning:
                preview["warning"] = warning

            return json.dumps(
                await create_confirmation_token(tool_name, args, preview=preview),
                ensure_ascii=False,
            )

        # === CON TOKEN ===

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return json.dumps({"error": error})

        if not abs_path.exists():
            await complete_confirmation_token(
                confirmation_token, success=False, error="not_found"
            )
            return json.dumps({"error": "not_found", "path": _fs._rel_posix(abs_path)})

        try:
            await reserve_write_slot(
                config_write_min_interval_seconds,
                config_write_max_per_minute,
            )
        except RateLimitError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return json.dumps({
                "error": "rate_limited",
                "reason": exc.reason,
                "min_interval_seconds": exc.min_interval_seconds,
                "max_per_minute": exc.max_per_minute,
                "next_allowed_at": exc.next_allowed_at,
            })

        # Safety backup
        backup_err = await maybe_trigger_safety_backup(
            ha_client, safety_backup_window_minutes,
            enabled=safety_backup_enabled,
        )
        if backup_err:
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(backup_err)
            )
            return json.dumps({"error": "safety_backup_failed", "detail": str(backup_err)})

        # Backup del original
        backup_path = await backup_before_write(
            abs_path,
            file_backup_max_per_path=file_backup_max_per_path,
            file_backup_max_total_mb=file_backup_max_total_mb,
        )

        rel = _fs._rel_posix(abs_path)
        try:
            await asyncio.to_thread(abs_path.unlink)
        except FileNotFoundError:
            pass
        except OSError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return json.dumps({"error": "io_error", "detail": str(exc)})

        await record_config_write()

        invalidate_include_cache()  # siempre; ver el comentario en fs_write_file

        result: dict[str, Any] = {
            "result": "ok",
            "path": rel,
            "backup": backup_path,
        }
        await complete_confirmation_token(confirmation_token, success=True, result=result)
        logger.info("fs_delete_file_ok", path=rel, backup=backup_path)
        return json.dumps(result, ensure_ascii=False)

    # ── fs_move_file ──────────────────────────────────────────────────────────

    @mcp.tool()
    async def fs_move_file(
        src: str,
        dst: str,
        overwrite: bool = False,
        confirmation_token: str | None = None,
    ) -> object:
        """Renombra o mueve un fichero dentro de /config.

        SIEMPRE requiere confirmation_token.

        Args:
            src:                Path origen (relativo o absoluto bajo /config).
            dst:                Path destino (relativo o absoluto bajo /config).
            overwrite:          Si True, sobreescribe dst si existe (debe
                                confirmarse explícitamente en la misma llamada).
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"result": "ok", "src": "...", "dst": "...",
                        "backup_src": "...", "backup_dst": "..."}
        """
        tool_name = "fs_move_file"

        try:
            abs_src = normalize_path(src)
        except PathTraversalError as exc:
            return json.dumps({"error": "traversal_src", "detail": str(exc)})
        try:
            abs_dst = normalize_path(dst)
        except PathTraversalError as exc:
            return json.dumps({"error": "traversal_dst", "detail": str(exc)})

        # Blacklist en AMBOS extremos. La protección de lectura es por RUTA,
        # así que mover un fichero protegido fuera de su ruta la anularía y su
        # contenido volvería a ser legible —y con destino en `www/**` quedaría
        # además publicado por HTTP sin autenticación—. El destino se comprueba
        # por el motivo simétrico: no dejar sobrescribir un fichero protegido
        # con contenido arbitrario.
        for p, label in [(abs_src, "src"), (abs_dst, "dst")]:
            blacklisted, reason = check_blacklisted(p)
            if blacklisted:
                return json.dumps({
                    "error": "blacklisted",
                    "path": _fs._rel_posix(p),
                    "which": label,
                    "detail": reason,
                })

        for p, label in [(abs_src, "src"), (abs_dst, "dst")]:
            if is_managed_path(p):
                return json.dumps({
                    "error": "managed_path",
                    "path": _fs._rel_posix(p),
                    "which": label,
                    "reason": MANAGED_PATH_ERROR,
                })

        rel_src = _fs._rel_posix(abs_src)
        rel_dst = _fs._rel_posix(abs_dst)
        args = {"src": rel_src, "dst": rel_dst, "overwrite": overwrite}

        if not confirmation_token:
            if not abs_src.exists():
                return json.dumps({"error": "not_found", "path": rel_src})
            if abs_src.is_dir():
                return json.dumps({
                    "error": "is_directory",
                    "hint": "fs_move_file only moves files, not directories.",
                })

            dst_exists = abs_dst.exists()
            if dst_exists and not overwrite:
                return json.dumps({
                    "error": "dst_exists",
                    "dst": rel_dst,
                    "hint": "Set overwrite=true to replace the destination.",
                })

            preview: dict[str, Any] = {
                "action": "move_file",
                "src": rel_src,
                "dst": rel_dst,
                "dst_exists": dst_exists,
                "overwrite": overwrite,
                "is_executable_src": await check_executable_by_indirection(abs_src),
                "is_executable_dst": await check_executable_by_indirection(abs_dst),
            }
            return json.dumps(
                await create_confirmation_token(tool_name, args, preview=preview),
                ensure_ascii=False,
            )

        # === CON TOKEN ===

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return json.dumps({"error": error})

        if not abs_src.exists():
            await complete_confirmation_token(confirmation_token, success=False, error="src not found")
            return json.dumps({"error": "not_found", "path": rel_src})

        if abs_dst.exists() and not overwrite:
            await complete_confirmation_token(
                confirmation_token, success=False, error="dst exists without overwrite"
            )
            return json.dumps({"error": "dst_exists", "dst": rel_dst})

        try:
            await reserve_write_slot(
                config_write_min_interval_seconds,
                config_write_max_per_minute,
            )
        except RateLimitError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return json.dumps({
                "error": "rate_limited",
                "reason": exc.reason,
                "min_interval_seconds": exc.min_interval_seconds,
                "max_per_minute": exc.max_per_minute,
                "next_allowed_at": exc.next_allowed_at,
            })

        # Safety backup
        backup_err = await maybe_trigger_safety_backup(
            ha_client, safety_backup_window_minutes,
            enabled=safety_backup_enabled,
        )
        if backup_err:
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(backup_err)
            )
            return json.dumps({"error": "safety_backup_failed", "detail": str(backup_err)})

        backup_src = await backup_before_write(
            abs_src,
            file_backup_max_per_path=file_backup_max_per_path,
            file_backup_max_total_mb=file_backup_max_total_mb,
        )
        backup_dst = await backup_before_write(
            abs_dst,
            file_backup_max_per_path=file_backup_max_per_path,
            file_backup_max_total_mb=file_backup_max_total_mb,
        ) if abs_dst.exists() else None

        try:
            abs_dst.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.move, str(abs_src), str(abs_dst))
        except OSError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return json.dumps({"error": "io_error", "detail": str(exc)})

        await record_config_write()

        invalidate_include_cache()  # siempre; ver el comentario en fs_write_file

        result: dict[str, Any] = {
            "result": "ok",
            "src": rel_src,
            "dst": rel_dst,
            "backup_src": backup_src,
            "backup_dst": backup_dst,
        }
        await complete_confirmation_token(confirmation_token, success=True, result=result)
        logger.info("fs_move_file_ok", src=rel_src, dst=rel_dst)
        return json.dumps(result, ensure_ascii=False)

    # ── fs_set_secret ─────────────────────────────────────────────────────────

    @mcp.tool()
    async def fs_set_secret(
        key: str,
        value: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Escribe o actualiza una entrada en secrets.yaml.

        SIEMPRE requiere confirmation_token.
        NUNCA devuelve el contenido de secrets.yaml.
        Solo indica si la key fue añadida o actualizada.

        Args:
            key:                Nombre del secreto (solo alfanuméricos, _, -).
            value:              Valor del secreto.
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"result": "ok", "key_added": "...",
                        "was_update": bool}
        """
        tool_name = "fs_set_secret"

        # Validar key: solo alfanuméricos, _, -
        if not re.match(r"^[A-Za-z0-9_\-]+$", key):
            return json.dumps({
                "error": "invalid_key",
                "detail": "Secret key must contain only alphanumeric characters, _ and -",
            })

        args = {"key": key, "value": value}

        secrets_path = _current_config_base() / _SECRETS_YAML_REL

        if not confirmation_token:
            # Preview: no exponer el contenido actual
            key_exists = False
            if secrets_path.exists():
                try:
                    raw = secrets_path.read_text(encoding="utf-8")
                    key_exists = bool(re.search(rf"^{re.escape(key)}\s*:", raw, re.MULTILINE))
                except OSError:
                    pass

            preview: dict[str, Any] = {
                "action": "set_secret",
                "key": key,
                "is_update": key_exists,
                "note": (
                    "secrets.yaml is NEVER returned in responses. "
                    "The value is written to disk without being echoed back."
                ),
            }
            return json.dumps(
                await create_confirmation_token(tool_name, args, preview=preview),
                ensure_ascii=False,
            )

        # === CON TOKEN ===

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return json.dumps({"error": error})

        try:
            await reserve_write_slot(
                config_write_min_interval_seconds,
                config_write_max_per_minute,
            )
        except RateLimitError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return json.dumps({
                "error": "rate_limited",
                "reason": exc.reason,
                "min_interval_seconds": exc.min_interval_seconds,
                "max_per_minute": exc.max_per_minute,
                "next_allowed_at": exc.next_allowed_at,
            })

        # Safety backup (backup goes to /sensitive/)
        backup_err = await maybe_trigger_safety_backup(
            ha_client, safety_backup_window_minutes,
            enabled=safety_backup_enabled,
        )
        if backup_err:
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(backup_err)
            )
            return json.dumps({"error": "safety_backup_failed", "detail": str(backup_err)})

        # Backup secrets.yaml (→ /data/backups/sensitive/)
        await backup_before_write(
            secrets_path,
            file_backup_max_per_path=file_backup_max_per_path,
            file_backup_max_total_mb=file_backup_max_total_mb,
        )

        # Leer contenido actual (o crear nuevo)
        was_update = False
        if secrets_path.exists():
            try:
                raw = secrets_path.read_text(encoding="utf-8")
            except OSError:
                raw = ""
        else:
            raw = ""

        # Check si la key ya existe
        pattern = rf"^({re.escape(key)}\s*:)([^\n]*)"
        if re.search(pattern, raw, re.MULTILINE):
            was_update = True
            # Reemplazar el valor
            def _replace_secret(m: re.Match) -> str:
                return f"{m.group(1)} {value}"
            new_content = re.sub(pattern, _replace_secret, raw, flags=re.MULTILINE)
        else:
            # Añadir al final
            separator = "\n" if raw and not raw.endswith("\n") else ""
            new_content = raw + separator + f"{key}: {value}\n"

        try:
            secrets_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(safe_write_file, secrets_path, new_content)
        except OSError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return json.dumps({"error": "io_error", "detail": str(exc)})

        await record_config_write()

        # secrets.yaml forma parte del árbol de includes (el tag !secret lo
        # recorre), así que esta ruta también tiene que invalidar el caché.
        invalidate_include_cache()

        # NUNCA incluir contenido ni valor del secreto en la respuesta
        result: dict[str, Any] = {
            "result": "ok",
            "key_added": key,
            "was_update": was_update,
        }
        await complete_confirmation_token(confirmation_token, success=True, result=result)
        logger.info("fs_set_secret_ok", key=key, was_update=was_update)
        return json.dumps(result, ensure_ascii=False)

    # ── fs_list_file_backups ──────────────────────────────────────────────────

    @mcp.tool()
    async def fs_list_file_backups(path: str | None = None) -> object:
        """Lista los backups de ficheros disponibles en /data/backups/normal/.

        Los backups de /sensitive/ (secrets.yaml, etc.) NUNCA aparecen aquí.

        Args:
            path: Path relativo para filtrar backups de ese fichero.
                  Si None, lista todos los backups disponibles.

        Returns:
            {"backups": [...], "count": N}
            Cada item: {"path": "...", "timestamp": "...", "backup_file": "...",
                        "size_bytes": N}
        """
        config_base = _current_config_base()

        def _list_backups() -> list[dict[str, Any]]:
            if not BACKUPS_NORMAL_DIR.exists():
                return []

            results: list[dict[str, Any]] = []
            for backup_file in sorted(BACKUPS_NORMAL_DIR.iterdir()):
                if not backup_file.is_file():
                    continue

                name = backup_file.name
                # Format: YYYYMMDDTHHMMSSZ_rel__path
                parts = name.split("_", 1)
                if len(parts) < 2:
                    continue

                ts_part = parts[0]
                rel_part = parts[1].replace("__", "/")

                # Filter by path if specified
                if path is not None:
                    try:
                        filter_path = normalize_path(path)
                        filter_rel = _fs._rel_posix(filter_path)
                    except (PathTraversalError, ValueError):
                        return []
                    if rel_part != filter_rel:
                        continue

                try:
                    size = backup_file.stat().st_size
                except OSError:
                    size = 0

                results.append({
                    "path": rel_part,
                    "timestamp": ts_part,
                    "backup_file": name,
                    "size_bytes": size,
                })

            return sorted(results, key=lambda x: (x["path"], x["timestamp"]))

        backups = await asyncio.to_thread(_list_backups)
        return json.dumps({
            "backups": backups,
            "count": len(backups),
        }, ensure_ascii=False)

    # ── fs_restore_file_backup ────────────────────────────────────────────────

    @mcp.tool()
    async def fs_restore_file_backup(
        path: str,
        timestamp: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Restaura un backup anterior de un fichero.

        SIEMPRE requiere confirmation_token.
        Antes de restaurar, hace backup del estado actual (backup-before-restore).
        Respeta las reglas de escritura ACTUALES: si el path está ahora protegido,
        el restore se rechaza aunque el backup fuera creado cuando no lo estaba.

        Args:
            path:               Path relativo del fichero a restaurar.
            timestamp:          Timestamp del backup a restaurar (YYYYMMDDTHHMMSSZ).
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"result": "ok", "path": "...", "restored_from": "...",
                        "backup_before_restore": "..."}
        """
        tool_name = "fs_restore_file_backup"

        # Validar timestamp: formato fijo YYYYMMDDTHHMMSSZ. Evita que un
        # timestamp con '..' o '/' escape de BACKUPS_NORMAL_DIR al formar el
        # nombre del backup (backup_name = f"{timestamp}_{safe_rel}").
        if not re.match(r"^\d{8}T\d{6}Z$", timestamp):
            return json.dumps({
                "error": "invalid_timestamp",
                "detail": "timestamp must match YYYYMMDDTHHMMSSZ (see fs_list_file_backups).",
            })

        # Resolver path del fichero a restaurar
        try:
            abs_path = normalize_path(path)
        except PathTraversalError as exc:
            return json.dumps({"error": "traversal", "detail": str(exc)})

        # Managed paths rechazados
        if is_managed_path(abs_path):
            return json.dumps({
                "error": "managed_path",
                "path": _fs._rel_posix(abs_path),
                "reason": MANAGED_PATH_ERROR,
            })

        # Rechazar si el path está ahora blacklisteado
        blacklisted, reason = check_blacklisted(abs_path)
        if blacklisted:
            return json.dumps({
                "error": "blacklisted",
                "detail": (
                    f"Cannot restore to protected path: {reason}. "
                    "The path is now protected even if it wasn't when the backup was created."
                ),
            })

        rel = _fs._rel_posix(abs_path)

        # Buscar el backup
        safe_rel = rel.replace("/", "__")
        backup_name = f"{timestamp}_{safe_rel}"
        backup_file = BACKUPS_NORMAL_DIR / backup_name

        if not backup_file.exists():
            return json.dumps({
                "error": "backup_not_found",
                "path": rel,
                "timestamp": timestamp,
                "hint": "Use fs_list_file_backups to see available backups.",
            })

        args = {"path": rel, "timestamp": timestamp}

        if not confirmation_token:
            # Preview: mostrar contenido del backup
            try:
                raw = backup_file.read_bytes()
                if not _fs.is_binary(raw[:8192]):
                    _, backup_content = _fs.detect_encoding(raw)
                    preview_content: str | None = backup_content
                else:
                    preview_content = None
            except (OSError, ValueError):
                preview_content = None

            preview: dict[str, Any] = {
                "action": "restore_file_backup",
                "path": rel,
                "restore_from_timestamp": timestamp,
                "backup_size_bytes": backup_file.stat().st_size,
                "current_exists": abs_path.exists(),
                "is_executable_by_indirection": await check_executable_by_indirection(abs_path),
            }
            if preview_content is not None:
                preview["backup_content_length"] = len(preview_content)

            return json.dumps(
                await create_confirmation_token(tool_name, args, preview=preview),
                ensure_ascii=False,
            )

        # === CON TOKEN ===

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return json.dumps({"error": error})

        # Verificar de nuevo que el backup file existe
        if not backup_file.exists():
            await complete_confirmation_token(
                confirmation_token, success=False, error="backup not found at execution time"
            )
            return json.dumps({"error": "backup_not_found", "path": rel, "timestamp": timestamp})

        try:
            await reserve_write_slot(
                config_write_min_interval_seconds,
                config_write_max_per_minute,
            )
        except RateLimitError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return json.dumps({
                "error": "rate_limited",
                "reason": exc.reason,
                "min_interval_seconds": exc.min_interval_seconds,
                "max_per_minute": exc.max_per_minute,
                "next_allowed_at": exc.next_allowed_at,
            })

        # Safety backup
        backup_err = await maybe_trigger_safety_backup(
            ha_client, safety_backup_window_minutes,
            enabled=safety_backup_enabled,
        )
        if backup_err:
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(backup_err)
            )
            return json.dumps({"error": "safety_backup_failed", "detail": str(backup_err)})

        # Backup-before-restore del estado actual
        backup_before = await backup_before_write(
            abs_path,
            file_backup_max_per_path=file_backup_max_per_path,
            file_backup_max_total_mb=file_backup_max_total_mb,
        )

        # Restaurar: copiar el backup al destino
        try:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.copy2, str(backup_file), str(abs_path))
        except OSError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return json.dumps({"error": "io_error", "detail": str(exc)})

        await record_config_write()

        invalidate_include_cache()  # siempre; ver el comentario en fs_write_file

        result: dict[str, Any] = {
            "result": "ok",
            "path": rel,
            "restored_from": timestamp,
            "backup_before_restore": backup_before,
        }
        await complete_confirmation_token(confirmation_token, success=True, result=result)
        logger.info(
            "fs_restore_file_backup_ok",
            path=rel,
            timestamp=timestamp,
            backup_before_restore=backup_before,
        )
        return json.dumps(result, ensure_ascii=False)
