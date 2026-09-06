"""Hermes — Tools MCP para Filesystem /config.

Lectura de ficheros de configuración de HA bajo /config. TODA la
seguridad pasa por hermes.fs — nunca se abre un fichero directamente.

Tools:
  fs_read_file         — lee un fichero completo (con truncado limpio)
  fs_read_file_lines   — lee un rango de líneas (paginación)
  fs_list_dir          — lista directorio con flags de seguridad
  fs_search_in_config  — búsqueda tipo grep respetando blacklists
  fs_stat              — metadata sin leer contenido

No usa @requires_ready porque no toca HA WebSocket — opera sobre el
filesystem local del contenedor del add-on (/config está montado por
el manifest homeassistant_config).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
from pathlib import Path
from typing import Any

import structlog

from hermes import fs as _fs
from hermes.fs import (
    BlacklistedPathError,
    PathTraversalError,
    check_blacklisted,
    check_path_readable,
    detect_encoding,
    is_binary,
    normalize_path,
    path_stat,
    read_bytes,
)

logger = structlog.get_logger(__name__)

_BINARY_PROBE = 8192
_MAX_LINES_PER_READ = 5000
_LIST_MAX_ENTRIES = 500


def _current_config_base() -> Path:
    """Devuelve el CONFIG_BASE actual (permite monkeypatch en tests)."""
    return _fs.CONFIG_BASE


def _is_inside_config(path: Path) -> bool:
    """True si `path`, una vez resuelto, cae dentro de CONFIG_BASE."""
    try:
        path.resolve().relative_to(_fs.CONFIG_BASE.resolve())
    except (OSError, ValueError, RuntimeError):
        return False
    return True


def register(
    mcp: object,
    response_max_bytes: int = 1_048_576,
) -> None:
    """Registra las tools de filesystem."""

    # ── fs_read_file ──────────────────────────────────────────────────────

    @mcp.tool()
    async def fs_read_file(path: str) -> object:
        """Lee el contenido de un fichero de texto bajo /config.

        Acepta rutas relativas ("automations.yaml") o absolutas bajo
        /config ("/config/automations.yaml").

        Si el fichero supera response_max_bytes, trunca en borde de línea
        limpia e incluye truncated, truncated_at_line, line_count y hint
        para paginar con fs_read_file_lines.

        Rechaza automáticamente:
          - Rutas que escapen de /config (traversal).
          - Ficheros en la blacklist (secrets.yaml, .storage/auth, etc.).
          - Ficheros binarios (db, key, pem, binarios sin extensión).
          - Cualquier path bajo .storage/ no en la allowlist explícita.

        Args:
            path: Ruta relativa o absoluta bajo /config.

        Returns:
            JSON con {
              "path": "automations.yaml",
              "size_bytes": 8349,
              "content": "...",
              "encoding": "utf-8",
              "line_count": 150
            }
            Con truncado: añade truncated, truncated_at_line y hint.
            Error: {"error": "traversal"|"blacklisted"|"binary_file"|"not_found"|"..."
        """
        try:
            abs_path = check_path_readable(path)
        except PathTraversalError as exc:
            return json.dumps({"error": "traversal", "detail": str(exc)})
        except BlacklistedPathError as exc:
            return json.dumps({"error": "blacklisted", "detail": str(exc)})

        if not abs_path.exists():
            return json.dumps({"error": "not_found", "path": path})
        if abs_path.is_dir():
            return json.dumps({"error": "is_directory", "path": path,
                               "hint": "Use fs_list_dir to list directory contents"})

        try:
            raw = await asyncio.to_thread(read_bytes, abs_path)
        except FileNotFoundError:
            return json.dumps({"error": "not_found", "path": path})
        except OSError as exc:
            return json.dumps({"error": "io_error", "detail": str(exc)})

        # Binary detection
        probe = raw[:_BINARY_PROBE]
        if is_binary(probe):
            logger.info("fs_read_file_binary", path=path, size=len(raw))
            return json.dumps({
                "error": "binary_file",
                "path": path,
                "size_bytes": len(raw),
                "hint": "Use fs_stat for metadata; binary read is not supported",
            })

        # Encoding detection
        try:
            encoding, content = detect_encoding(raw)
        except ValueError:
            return json.dumps({"error": "binary_file", "path": path,
                               "size_bytes": len(raw),
                               "hint": "File cannot be decoded as text"})

        lines = content.splitlines(keepends=True)
        total_lines = len(lines)
        rel_path = _fs._rel_posix(abs_path)

        # Content limit: leave headroom for JSON envelope
        content_limit = response_max_bytes - 2048

        # Build response (with truncation if needed)
        if len(content.encode("utf-8")) <= content_limit:
            result: dict[str, Any] = {
                "path": rel_path,
                "size_bytes": len(raw),
                "content": content,
                "encoding": encoding,
                "line_count": total_lines,
            }
        else:
            # Truncate at clean line boundary
            kept: list[str] = []
            used = 0
            for i, line in enumerate(lines):
                chunk = len(line.encode("utf-8"))
                if used + chunk > content_limit:
                    truncated_at_line = i  # 1-indexed
                    break
                kept.append(line)
                used += chunk
            else:
                truncated_at_line = total_lines

            result = {
                "path": rel_path,
                "size_bytes": len(raw),
                "content": "".join(kept),
                "encoding": encoding,
                "line_count": total_lines,
                "truncated": True,
                "truncated_at_line": truncated_at_line,
                "hint": (
                    f"File has {total_lines} lines; only {truncated_at_line} shown. "
                    "Use fs_read_file_lines(path, offset, limit) to read in chunks."
                ),
            }

        logger.info(
            "fs_read_file_ok",
            path=rel_path,
            size=len(raw),
            encoding=encoding,
            truncated=result.get("truncated", False),
        )
        return json.dumps(result, ensure_ascii=False)

    # ── fs_read_file_lines ────────────────────────────────────────────────

    @mcp.tool()
    async def fs_read_file_lines(
        path: str,
        offset: int = 0,
        limit: int = 500,
    ) -> object:
        """Lee un rango de líneas de un fichero de /config.

        Útil para paginar ficheros grandes después de un fs_read_file
        truncado. offset es 0-indexed (primera línea del fichero = 0).

        Args:
            path:   Ruta relativa o absoluta bajo /config.
            offset: Número de línea desde la que empezar (0-indexed).
            limit:  Máximo de líneas a devolver (max 5000).

        Returns:
            JSON con {
              "path": "...",
              "offset": 0,
              "limit": 500,
              "returned_lines": 150,
              "total_lines": 150,
              "lines": ["line1\\n", "line2\\n", ...]
            }
        """
        # Clamp limit
        limit = max(1, min(limit, _MAX_LINES_PER_READ))
        offset = max(0, offset)

        try:
            abs_path = check_path_readable(path)
        except PathTraversalError as exc:
            return json.dumps({"error": "traversal", "detail": str(exc)})
        except BlacklistedPathError as exc:
            return json.dumps({"error": "blacklisted", "detail": str(exc)})

        if not abs_path.exists():
            return json.dumps({"error": "not_found", "path": path})
        if abs_path.is_dir():
            return json.dumps({"error": "is_directory", "path": path})

        try:
            raw = await asyncio.to_thread(read_bytes, abs_path)
        except FileNotFoundError:
            return json.dumps({"error": "not_found", "path": path})
        except OSError as exc:
            return json.dumps({"error": "io_error", "detail": str(exc)})

        probe = raw[:_BINARY_PROBE]
        if is_binary(probe):
            return json.dumps({"error": "binary_file", "path": path,
                               "size_bytes": len(raw)})

        try:
            encoding, content = detect_encoding(raw)
        except ValueError:
            return json.dumps({"error": "binary_file", "path": path})

        all_lines = content.splitlines(keepends=True)
        total_lines = len(all_lines)
        chunk = all_lines[offset: offset + limit]
        rel_path = _fs._rel_posix(abs_path)

        logger.info(
            "fs_read_file_lines_ok",
            path=rel_path,
            offset=offset,
            limit=limit,
            returned=len(chunk),
        )
        return json.dumps({
            "path": rel_path,
            "offset": offset,
            "limit": limit,
            "returned_lines": len(chunk),
            "total_lines": total_lines,
            "lines": chunk,
        }, ensure_ascii=False)

    # ── fs_list_dir ───────────────────────────────────────────────────────

    @mcp.tool()
    async def fs_list_dir(
        path: str = ".",
        recursive: bool = False,
        max_depth: int = 3,
    ) -> object:
        """Lista el contenido de un directorio bajo /config.

        Los ficheros blacklisteados aparecen con is_blacklisted: true —
        el LLM sabe que existen pero no puede leerlos. Esto es intencional:
        evita "sorpresas" (el LLM no sabe que secrets.yaml existe si no
        aparece en el listado).

        Args:
            path:      Directorio a listar (relativo o absoluto bajo /config).
                       Por defecto: raíz de /config.
            recursive: Si True, lista recursivamente.
            max_depth: Profundidad máxima si recursive=True (max 3).

        Returns:
            JSON con {
              "path": ".",
              "entries": [{
                "name": "automations.yaml",
                "type": "file",      # "file" | "dir" | "symlink"
                "size_bytes": 8349,
                "modified": "2026-04-09T23:42:00+00:00",
                "is_blacklisted": false
              }, ...],
              "count": N,
              "truncated": bool
            }
        """
        max_depth = max(1, min(max_depth, 3))

        try:
            abs_path = normalize_path(path)
        except PathTraversalError as exc:
            return json.dumps({"error": "traversal", "detail": str(exc)})

        if not abs_path.exists():
            return json.dumps({"error": "not_found", "path": path})
        if not abs_path.is_dir():
            return json.dumps({"error": "not_a_directory", "path": path})

        # For listing, we don't raise on blacklisted dirs — we show them marked
        entries: list[dict[str, Any]] = []
        truncated = False

        def _collect(dirpath: Path, depth: int) -> None:
            nonlocal truncated
            if len(entries) >= _LIST_MAX_ENTRIES:
                truncated = True
                return

            try:
                items = sorted(dirpath.iterdir(), key=lambda p: (p.is_file(), p.name))
            except PermissionError:
                return

            for item in items:
                if len(entries) >= _LIST_MAX_ENTRIES:
                    truncated = True
                    return

                try:
                    stat = item.lstat()
                    if item.is_symlink():
                        itype = "symlink"
                    elif item.is_dir():
                        itype = "dir"
                    else:
                        itype = "file"
                    size = stat.st_size if itype == "file" else None
                    modified = datetime.datetime.fromtimestamp(
                        stat.st_mtime, tz=datetime.timezone.utc
                    ).isoformat()
                except OSError:
                    itype = "unknown"
                    size = None
                    modified = None

                blacklisted, _reason = check_blacklisted(item)

                entry: dict[str, Any] = {
                    "name": item.name,
                    "type": itype,
                    "size_bytes": size,
                    "modified": modified,
                    "is_blacklisted": blacklisted,
                }
                entries.append(entry)

                if recursive and itype == "dir" and depth < max_depth and not blacklisted:
                    _collect(item, depth + 1)

        await asyncio.to_thread(_collect, abs_path, 1)

        rel_path = _fs._rel_posix(abs_path)
        logger.info("fs_list_dir_ok", path=rel_path, count=len(entries), truncated=truncated)

        result: dict[str, Any] = {
            "path": rel_path,
            "entries": entries,
            "count": len(entries),
        }
        if truncated:
            result["truncated"] = True
            result["hint"] = f"More than {_LIST_MAX_ENTRIES} entries; use a more specific path"
        return json.dumps(result, ensure_ascii=False)

    # ── fs_search_in_config ───────────────────────────────────────────────

    @mcp.tool()
    async def fs_search_in_config(
        pattern: str,
        glob: str = "**/*.yaml",
        case_sensitive: bool = False,
        max_matches: int = 100,
    ) -> object:
        """Búsqueda tipo grep en los ficheros de /config.

        Respeta íntegramente las blacklists y allowlists: no lee ningún
        fichero blacklisteado ni sus .storage/ no permitidos. Esto evita
        exfiltración de secretos via pattern matching.

        Args:
            pattern:        Expresión regular (o texto literal) a buscar.
            glob:           Patrón de ficheros a buscar. Default: **/*.yaml.
                            Solo busca dentro de /config.
            case_sensitive: Si False (default), búsqueda insensible a mayúsculas.
            max_matches:    Máximo de coincidencias a devolver (max 200).

        Returns:
            JSON con {
              "pattern": "influxdb",
              "glob": "**/*.yaml",
              "matches": [
                {
                  "path": "configuration.yaml",
                  "line_number": 3,
                  "line_content": "influxdb:",
                  "match": "influxdb"
                }, ...
              ],
              "count": N,
              "searched_files": M,
              "skipped_files": K,   # blacklisted/binary
              "truncated": bool
            }
        """
        max_matches = max(1, min(max_matches, 200))
        config_base = _current_config_base()

        # Compile pattern
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as exc:
            return json.dumps({"error": "invalid_pattern", "detail": str(exc)})

        matches: list[dict[str, Any]] = []
        searched = 0
        skipped = 0
        truncated = False

        def _search_files() -> None:
            nonlocal searched, skipped, truncated

            try:
                matched_paths = sorted(config_base.rglob(glob))
            except (OSError, ValueError):
                return

            # `rglob` NO colapsa los `..` del patrón, así que un glob como
            # "sub/../secrets.yaml" o "../*" devuelve rutas fuera del sandbox.
            # `check_blacklisted` ya resuelve y exige contención; se filtra
            # también aquí para no depender de una sola capa y para no gastar
            # E/S en rutas que no se van a servir.
            matched_paths = [fp for fp in matched_paths if _is_inside_config(fp)]

            for file_path in matched_paths:
                if not file_path.is_file():
                    continue
                if len(matches) >= max_matches:
                    truncated = True
                    break

                # Security check: skip blacklisted files
                blacklisted, _reason = check_blacklisted(file_path)
                if blacklisted:
                    skipped += 1
                    continue

                # Read (limited to response_max_bytes for efficiency)
                try:
                    raw = read_bytes(file_path, max_bytes=response_max_bytes)
                except (OSError, FileNotFoundError):
                    skipped += 1
                    continue

                # Skip binaries
                if is_binary(raw[:_BINARY_PROBE]):
                    skipped += 1
                    continue

                try:
                    _encoding, content = detect_encoding(raw)
                except ValueError:
                    skipped += 1
                    continue

                searched += 1
                file_rel = _fs._rel_posix(file_path)

                for lineno, line in enumerate(content.splitlines(), start=1):
                    if len(matches) >= max_matches:
                        truncated = True
                        break
                    m = regex.search(line)
                    if m:
                        matches.append({
                            "path": file_rel,
                            "line_number": lineno,
                            "line_content": line.rstrip("\n\r"),
                            "match": m.group(0),
                        })

        await asyncio.to_thread(_search_files)

        logger.info(
            "fs_search_in_config_ok",
            pattern=pattern,
            glob=glob,
            count=len(matches),
            searched=searched,
            skipped=skipped,
        )
        result: dict[str, Any] = {
            "pattern": pattern,
            "glob": glob,
            "case_sensitive": case_sensitive,
            "matches": matches,
            "count": len(matches),
            "searched_files": searched,
            "skipped_files": skipped,
        }
        if truncated:
            result["truncated"] = True
            result["hint"] = f"Results capped at {max_matches}; use a narrower pattern or glob"
        return json.dumps(result, ensure_ascii=False)

    # ── fs_stat ───────────────────────────────────────────────────────────

    @mcp.tool()
    async def fs_stat(path: str) -> object:
        """Devuelve metadata de un fichero o directorio sin leer contenido.

        No requiere que el fichero sea legible — muestra metadata incluso
        de ficheros blacklisteados. Útil para verificar si un fichero
        existe antes de intentar leerlo.

        Args:
            path: Ruta relativa o absoluta bajo /config.

        Returns:
            JSON con {
              "path": "secrets.yaml",
              "type": "file",
              "size_bytes": 270,
              "modified": "2026-04-13T15:07:00+00:00",
              "is_blacklisted": true,
              "is_managed_path": false
            }
        """
        try:
            abs_path = normalize_path(path)
        except PathTraversalError as exc:
            return json.dumps({"error": "traversal", "detail": str(exc)})

        if not abs_path.exists():
            return json.dumps({"error": "not_found", "path": path})

        result = await asyncio.to_thread(path_stat, abs_path)
        logger.info("fs_stat_ok", path=result["path"])
        return json.dumps(result, ensure_ascii=False)
