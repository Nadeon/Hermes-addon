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
import multiprocessing
import os
import queue as _queue
import re
import time
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

# ── Frenos contra regex de coste exponencial (ReDoS) en fs_search_in_config ───
#: Longitud máxima del patrón aceptado.
_SEARCH_PATTERN_MAX_LEN = 256
#: Solo se escanean con la regex los primeros N caracteres de cada línea.
_SEARCH_MAX_LINE_LEN = 4096
#: Caracteres que introducen un cuantificador que puede repetir sin tope.
_QUANTIFIERS = frozenset("*+{")
#: Tope de tiempo de pared del escaneo completo de una búsqueda, en segundos.
#: Pasado ese plazo el subproceso que la ejecuta se mata.
_SEARCH_TIMEOUT_SECONDS = 10.0
#: Cada cuánto mira el padre si el hijo ya ha dejado el resultado en la cola.
_SEARCH_POLL_INTERVAL_SECONDS = 0.05
#: Margen que se le da a un hijo terminado (o matado) para acabar de morir.
_SEARCH_REAP_TIMEOUT_SECONDS = 5.0


def _pattern_redos_risk(pattern: str) -> str | None:
    """Heurística conservadora contra patrones de coste exponencial.

    Devuelve el motivo del rechazo, o None si el patrón se acepta.

    POR QUÉ existe: el módulo `re` de CPython es un motor con backtracking y su
    ejecución NO se puede interrumpir — corre dentro de una llamada en C que no
    atiende señales ni la cancelación de asyncio. `(a+)+$` contra una línea de
    40 caracteres «a» no termina nunca. Es la primera capa, la barata: rechaza
    lo obvio sin gastar ni una lectura de disco ni un proceso.

    NO es la capa que sostiene la garantía. Esa es el subproceso con timeout de
    `_run_scan_in_subprocess`: lo que esta heurística no vea se ejecuta igual,
    pero fuera del intérprete del add-on y con un plazo de muerte.

    Detecta las dos construcciones que disparan el coste exponencial de forma
    reconocible sintácticamente:
      - cuantificador anidado: un grupo que ya lleva cuantificador dentro y va
        cuantificado por fuera — `(a+)+`, `(a*)*`, `(x{1,3})+`;
      - retrorreferencias (`\\1`, `(?P=nombre)`), que hacen el matching NP-duro
        por definición.

    RIESGO RESIDUAL, asumido y documentado: la comprobación es sintáctica y no
    es completa. No cubre la explosión por alternativas solapadas (`(a|aa)+`)
    ni la de cuantificadores adyacentes (`a*a*$`), así que sigue siendo posible
    construir un patrón caro que la pase — medido: `(a|aa)+$b` contra 38 «a»
    tarda 20 s y cada dos caracteres más multiplica por 2,6. Por eso NO es la
    única defensa: el patrón está limitado a `_SEARCH_PATTERN_MAX_LEN`
    caracteres, cada línea se escanea recortada a `_SEARCH_MAX_LINE_LEN` y,
    sobre todo, el escaneo corre en un proceso aparte que se mata a los
    `_SEARCH_TIMEOUT_SECONDS`.
    """
    i = 0
    n = len(pattern)
    # Un elemento por grupo abierto: ¿lleva ya un cuantificador dentro?
    group_has_quantifier: list[bool] = []
    in_char_class = False

    while i < n:
        ch = pattern[i]

        if ch == "\\":
            nxt = pattern[i + 1] if i + 1 < n else ""
            if nxt.isdigit() and nxt != "0":
                return "backreference"
            i += 2
            continue

        if in_char_class:
            # Dentro de [...] los cuantificadores son literales.
            if ch == "]":
                in_char_class = False
            i += 1
            continue

        if ch == "[":
            in_char_class = True
            i += 1
            continue

        if ch == "(":
            if pattern.startswith("(?P=", i):
                return "backreference"
            group_has_quantifier.append(False)
            i += 1
            continue

        if ch == ")":
            inner = group_has_quantifier.pop() if group_has_quantifier else False
            nxt = pattern[i + 1] if i + 1 < n else ""
            if inner and nxt in _QUANTIFIERS:
                return "nested quantifier"
            if nxt in _QUANTIFIERS or nxt == "?":
                # El grupo cuantificado cuenta como cuantificador del grupo que
                # lo envuelve: así se detecta también `((a+)x)+`.
                if group_has_quantifier:
                    group_has_quantifier[-1] = True
            i += 1
            continue

        if ch in _QUANTIFIERS:
            if group_has_quantifier:
                group_has_quantifier[-1] = True
            i += 1
            continue

        i += 1

    return None


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


# ── Escaneo de fs_search_in_config: lista en el padre, regex en un hijo ───────

def _collect_searchable_files(config_base: Path, glob: str) -> tuple[list[str], int]:
    """Resuelve el glob y deja SOLO los ficheros que se pueden leer.

    Devuelve (rutas absolutas como str, nº de ficheros descartados por política).

    POR QUÉ esto se queda en el proceso padre: decidir qué es legible es una
    decisión de seguridad y no se delega. El subproceso que ejecuta la regex
    recibe una lista ya filtrada y no vuelve a consultar blacklists ni
    allowlists — no puede ampliar el conjunto de ficheros legibles porque no es
    él quien lo calcula.
    """
    try:
        matched_paths = sorted(config_base.rglob(glob))
    except (OSError, ValueError):
        return [], 0

    files: list[str] = []
    skipped = 0
    for file_path in matched_paths:
        # `rglob` NO colapsa los `..` del patrón, así que un glob como
        # "sub/../secrets.yaml" o "../*" devuelve rutas fuera del sandbox.
        # `check_blacklisted` ya resuelve y exige contención; se filtra también
        # aquí para no depender de una sola capa y para no gastar E/S en rutas
        # que no se van a servir.
        if not _is_inside_config(file_path):
            continue
        if not file_path.is_file():
            continue
        blacklisted, _reason = check_blacklisted(file_path)
        if blacklisted:
            skipped += 1
            continue
        files.append(str(file_path))
    return files, skipped


def _scan_files_worker(
    config_base: str,
    file_paths: list[str],
    pattern: str,
    flags: int,
    max_matches: int,
    max_line_len: int,
    max_read_bytes: int,
    result_queue: Any,
) -> None:
    """Aplica la regex a los ficheros ya filtrados. Corre en el SUBPROCESO.

    Está a nivel de módulo, y no como función anidada dentro de la tool, porque
    el contexto "spawn" serializa el target por referencia (módulo + nombre) y
    el hijo lo reimporta: una closure no tiene nombre importable y no se podría
    lanzar. Por lo mismo, todos los argumentos son datos simples y CONFIG_BASE
    viaja como str — el hijo es un intérprete nuevo donde los monkeypatch del
    padre (los de los tests, por ejemplo) no existen.

    Deja en `result_queue` un único dict, con los resultados o con "error": el
    padre no ve la excepción del hijo, solo su código de salida, así que un
    fallo hay que contarlo explícitamente.

    La salida está acotada por construcción —como mucho `max_matches`
    coincidencias, cada línea recortada a `max_line_len`— para que el hijo no
    pueda devolver un volumen arbitrario por la cola.
    """
    matches: list[dict[str, Any]] = []
    searched = 0
    skipped = 0
    truncated = False

    try:
        regex = re.compile(pattern, flags)
        base = Path(config_base)

        for file_str in file_paths:
            if len(matches) >= max_matches:
                truncated = True
                break

            file_path = Path(file_str)
            try:
                raw = read_bytes(file_path, max_bytes=max_read_bytes)
            except (OSError, FileNotFoundError):
                skipped += 1
                continue

            if is_binary(raw[:_BINARY_PROBE]):
                skipped += 1
                continue

            try:
                _encoding, content = detect_encoding(raw)
            except ValueError:
                skipped += 1
                continue

            searched += 1
            try:
                file_rel = file_path.relative_to(base).as_posix()
            except ValueError:
                file_rel = file_path.as_posix()

            for lineno, line in enumerate(content.splitlines(), start=1):
                if len(matches) >= max_matches:
                    truncated = True
                    break
                if len(line) > max_line_len:
                    # Techo al trabajo del motor: el backtracking crece con la
                    # longitud de la entrada, así que una línea enorme (un
                    # .yaml minificado, un blob en base64) multiplica el coste
                    # de cualquier patrón. Se escanea solo el principio.
                    line = line[:max_line_len]
                m = regex.search(line)
                if m:
                    matches.append({
                        "path": file_rel,
                        "line_number": lineno,
                        "line_content": line.rstrip("\n\r"),
                        "match": m.group(0),
                    })

        payload: dict[str, Any] = {
            "matches": matches,
            "searched": searched,
            "skipped": skipped,
            "truncated": truncated,
        }
    except Exception as exc:  # noqa: BLE001 — el hijo no puede propagar nada
        payload = {
            "error": "search_failed",
            "detail": f"{type(exc).__name__}: {exc}",
        }

    try:
        result_queue.put(payload)
    except Exception:  # noqa: BLE001
        # Si la cola ya no está (padre muerto o hijo en proceso de morir) no
        # hay nada que hacer: el padre lo trata como fallo del hijo.
        pass


def _run_scan_in_subprocess(
    *,
    config_base: str,
    file_paths: list[str],
    pattern: str,
    flags: int,
    max_matches: int,
    max_line_len: int,
    max_read_bytes: int,
    timeout: float,
) -> dict[str, Any]:
    """Ejecuta `_scan_files_worker` en otro proceso y lo mata si se pasa de plazo.

    POR QUÉ un proceso y no un thread: una regex de CPython no se puede abortar
    a mitad — corre en C, no atiende señales ni la cancelación de asyncio, y ni
    `signal.setitimer` corta el bucle de backtracking. Un patrón exponencial en
    un `asyncio.to_thread` deja un worker del pool colgado PARA SIEMPRE, y el
    pool es finito: unas cuantas búsquedas así y el add-on se queda sin threads
    para cualquier otra cosa, sin más salida que reiniciarlo. Un proceso, en
    cambio, sí se puede matar desde fuera: SIGTERM y, si hace falta, SIGKILL.

    Se usa el contexto "spawn" a propósito, y no "fork": el add-on corre un
    bucle de asyncio con sockets y locks abiertos, y un fork los duplica en un
    hijo que nunca va a atenderlos (un lock tomado en otro thread al forkear se
    hereda tomado para siempre). "spawn" arranca un intérprete limpio.

    Esta función es SÍNCRONA y bloquea: el llamador la mete en
    `asyncio.to_thread` para no parar el bucle de eventos. El thread que espera
    sí se libera al vencer el plazo, que es justo lo que no pasaba antes.

    COSTE ACEPTADO: cada búsqueda arranca un intérprete nuevo, que reimporta
    hermes (unas décimas de segundo). Es el precio de poder matar el escaneo;
    una búsqueda en /config no es una operación de bucle cerrado.
    """
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()
    proc = ctx.Process(
        target=_scan_files_worker,
        args=(
            config_base,
            file_paths,
            pattern,
            flags,
            max_matches,
            max_line_len,
            max_read_bytes,
            result_queue,
        ),
        daemon=True,
    )
    proc.start()

    payload: dict[str, Any] | None = None
    timed_out = False
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                # Se lee ANTES de hacer join: un hijo que escribe en la cola se
                # queda bloqueado hasta que alguien vacía el pipe, así que
                # esperar primero a que muera es el interbloqueo clásico de
                # multiprocessing.
                payload = result_queue.get(timeout=_SEARCH_POLL_INTERVAL_SECONDS)
                break
            except _queue.Empty:
                pass  # sin resultado todavía: se comprueba el proceso y el plazo
            except (EOFError, OSError, ValueError):
                # Cola rota: el hijo murió a media escritura. Es un fallo del
                # escaneo, no una excepción que deba subir hasta la tool.
                payload = None
                break

            if not proc.is_alive():
                # Murió sin que hayamos leído nada: puede que el resultado siga
                # en tránsito por el pipe, así que se le da una última pasada
                # antes de darlo por fallido.
                try:
                    payload = result_queue.get(timeout=1.0)
                except (_queue.Empty, EOFError, OSError, ValueError):
                    payload = None
                break

            if time.monotonic() >= deadline:
                timed_out = True
                break

        if timed_out:
            logger.warning(
                "fs_search_subprocess_killed", pattern=pattern, timeout=timeout
            )
            return {
                "error": "search_timeout",
                "detail": (
                    f"Search aborted after {timeout:.0f}s: the pattern is too "
                    "expensive for the files it had to scan."
                ),
                "hint": (
                    "Narrow the glob or simplify the pattern; alternations that "
                    "overlap, such as (a|aa)+, backtrack exponentially."
                ),
            }

        if payload is None:
            return {
                "error": "search_failed",
                "detail": (
                    "The search subprocess ended without returning a result "
                    f"(exit code {proc.exitcode})."
                ),
            }

        if not isinstance(payload, dict):
            return {"error": "search_failed", "detail": "Malformed subprocess result"}

        return payload
    finally:
        # Pase lo que pase, aquí no queda ningún hijo vivo ni ningún descriptor
        # de la cola abierto: la defensa consiste precisamente en que el
        # proceso caro muera.
        if proc.is_alive():
            proc.terminate()
            proc.join(_SEARCH_REAP_TIMEOUT_SECONDS)
        if proc.is_alive():
            proc.kill()
            proc.join(_SEARCH_REAP_TIMEOUT_SECONDS)
        else:
            proc.join(_SEARCH_REAP_TIMEOUT_SECONDS)
        try:
            result_queue.close()
            result_queue.join_thread()
        except (OSError, ValueError):
            pass  # la cola ya estaba cerrada o rota: no queda nada que liberar
        try:
            proc.close()
        except ValueError:
            pass


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

        LÍMITES CONTRA ReDoS (el patrón lo elige quien llama), en capas:
          1. El patrón no puede pasar de 256 caracteres y se rechaza —con
             {"error": "pattern_too_complex"}— si lleva cuantificadores
             anidados (`(a+)+`) o retrorreferencias. Es una heurística
             sintáctica y NO es completa: `(a|aa)+$b` la pasa y tarda horas.
          2. Cada línea se escanea recortada a los primeros 4096 caracteres.
          3. La búsqueda entera corre en un SUBPROCESO con un plazo de 10 s; al
             vencer, el proceso se mata y la tool devuelve
             {"error": "search_timeout"}. Esta es la capa que garantiza que el
             add-on sigue respondiendo, porque una regex de CPython no se puede
             abortar a mitad: ejecutarla en un thread del add-on dejaba colgado
             un worker del pool para siempre.

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
            Error: {"error": "pattern_too_complex"|"invalid_pattern"|
                             "search_timeout"|"search_failed", "detail": "..."}
        """
        max_matches = max(1, min(max_matches, 200))
        config_base = _current_config_base()

        # Frenos ReDoS: ANTES de compilar y, sobre todo, antes de buscar nada.
        if len(pattern) > _SEARCH_PATTERN_MAX_LEN:
            return json.dumps({
                "error": "pattern_too_complex",
                "detail": (
                    f"Pattern is longer than {_SEARCH_PATTERN_MAX_LEN} characters"
                ),
            })
        risk = _pattern_redos_risk(pattern)
        if risk is not None:
            logger.warning("fs_search_pattern_rejected", pattern=pattern, risk=risk)
            return json.dumps({
                "error": "pattern_too_complex",
                "detail": f"Pattern rejected as potentially catastrophic: {risk}",
                "hint": (
                    "Avoid nested quantifiers such as (a+)+ and backreferences; "
                    "a regex engine cannot be interrupted once it starts."
                ),
            })

        # Compilar aquí es solo para VALIDAR: quien ejecuta la regex es el
        # subproceso, que la vuelve a compilar (un patrón compilado no cruza
        # bien un "spawn", y el hijo necesita el objeto en su propio
        # intérprete). Compilar es barato y no ejecuta nada, así que el error
        # de sintaxis se devuelve sin pagar un proceso.
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            re.compile(pattern, flags)
        except re.error as exc:
            return json.dumps({"error": "invalid_pattern", "detail": str(exc)})

        def _search_files() -> dict[str, Any]:
            # Qué ficheros se pueden abrir se decide AQUÍ, en el padre. El
            # subproceso solo recibe la lista ya filtrada.
            file_paths, skipped_by_policy = _collect_searchable_files(config_base, glob)
            if not file_paths:
                # Sin ficheros que mirar no hay regex que ejecutar: nos
                # ahorramos arrancar un intérprete entero.
                return {
                    "matches": [],
                    "searched": 0,
                    "skipped": skipped_by_policy,
                    "truncated": False,
                }

            payload = _run_scan_in_subprocess(
                config_base=str(config_base),
                file_paths=file_paths,
                pattern=pattern,
                flags=int(flags),
                max_matches=max_matches,
                max_line_len=_SEARCH_MAX_LINE_LEN,
                max_read_bytes=response_max_bytes,
                timeout=_SEARCH_TIMEOUT_SECONDS,
            )
            if "error" not in payload:
                payload["skipped"] = int(payload.get("skipped", 0)) + skipped_by_policy
            return payload

        result_payload = await asyncio.to_thread(_search_files)

        if result_payload.get("error") == "search_timeout":
            logger.warning(
                "fs_search_timeout",
                pattern=pattern,
                glob=glob,
                timeout_seconds=_SEARCH_TIMEOUT_SECONDS,
            )
            return json.dumps(result_payload, ensure_ascii=False)
        if "error" in result_payload:
            logger.warning(
                "fs_search_failed",
                pattern=pattern,
                glob=glob,
                detail=result_payload.get("detail"),
            )
            return json.dumps(result_payload, ensure_ascii=False)

        matches: list[dict[str, Any]] = result_payload.get("matches", [])
        searched = int(result_payload.get("searched", 0))
        skipped = int(result_payload.get("skipped", 0))
        truncated = bool(result_payload.get("truncated"))

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
