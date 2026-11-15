"""Hermes — Tools MCP de lectura de /addons y /share (spec 034, 1.2.1).

Familia `addons_share` (desactivable, activa por defecto). Tres tools:

  fs_list_dir_in_folder   — lista una carpeta (sobre común de listas)
  fs_stat_in_folder       — metadatos; en /addons, si es la carpeta de una app
  fs_read_file_in_folder  — lee texto por líneas, en streaming

Todas reciben `folder` (`addons` o `share`) y una ruta relativa a esa carpeta.
TODA la validación pasa por `hermes.folders` (la misma de `/config`,
parametrizada por raíz); nunca se abre una ruta del cliente sin pasar por
ahí. La lista negra es la de `/config` por NOMBRE de fichero
(`fs.blacklisted_name`): su contenido no se devuelve nunca. El resto se
devuelve sin redactar, igual que `fs_read_file` (research R-5).

Las `fs_*` de `/config` no cambian (D-4): por eso estas tienen nombre propio
(sufijo `_in_folder`) y viven en su propia familia.
"""

from __future__ import annotations

import asyncio
import codecs
import datetime
import os
import stat as _stat
from pathlib import Path
from typing import Any

import structlog

from hermes import folders as _folders
from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes.fs import PathTraversalError, blacklisted_name, is_binary
from hermes.fs import _open_file_nofollow
from hermes.tools._common import ajustar_lista_a_bytes, sobre_de_lista, tam_json

logger = structlog.get_logger(__name__)

_LIST_MAX_ENTRIES = 500
_MAX_DEPTH = 3
_MAX_LINES_PER_READ = 5000
#: Muestra para decidir si un fichero es binario (byte nulo), como `/config`.
_BINARY_PROBE = 8192
#: Hasta este tamaño se cuentan todas las líneas (`total_lines`); por encima,
#: contarlas obligaría a leer el fichero entero en cada página. Mutable para
#: los tests.
TOTAL_LINES_MAX_BYTES = 4 * 1024 * 1024
#: Tope de lo que se registra de una ruta que no se pudo normalizar.
_LOG_PATH_MAX = 200

_UTF8_BOM = b"\xef\xbb\xbf"


# ── Ayudantes ─────────────────────────────────────────────────────────────────

def _log(tool: str, folder: object, path: object, result: str) -> None:
    """Evento `folder_action` (FR-026): tool, carpeta, ruta y resultado.
    Nunca contenido ni huellas."""
    logger.info(
        "folder_action",
        tool=tool,
        folder=str(folder)[:20],
        path=str(path)[:_LOG_PATH_MAX],
        result=result,
    )


def _rechazo(tool: str, folder: object, path: object, respuesta: dict[str, Any]) -> dict[str, Any]:
    _log(tool, folder, path, f"rejected:{respuesta.get('error')}")
    return respuesta


def _resolver(folder: str, path: str) -> Path | dict[str, Any]:
    """Ruta absoluta y resuelta, o la respuesta de error lista para devolver."""
    try:
        return _folders.normalizar(folder, path)
    except _folders.CarpetaError as exc:
        return exc.respuesta()
    except PathTraversalError as exc:
        return {"error": "traversal", "detail": str(exc)}


def _fecha(st: os.stat_result) -> str:
    return datetime.datetime.fromtimestamp(
        st.st_mtime, tz=datetime.timezone.utc
    ).isoformat()


def _tipo(modo: int) -> str:
    if _stat.S_ISLNK(modo):
        return "symlink"
    if _stat.S_ISDIR(modo):
        return "dir"
    if _stat.S_ISREG(modo):
        return "file"
    return "other"


def _listar(base: Path, recursive: bool, max_depth: int) -> tuple[list[dict[str, Any]], bool]:
    """Recorrido en preorden (carpetas primero), sin seguir symlinks."""
    entradas: list[dict[str, Any]] = []
    truncated = False

    def recoger(carpeta: Path, prefijo: str, nivel: int) -> None:
        nonlocal truncated
        try:
            with os.scandir(carpeta) as it:
                hijos = list(it)
        except OSError:
            return
        datos = []
        for e in hijos:
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                st = None
            datos.append((e, st))
        datos.sort(key=lambda d: (d[1] is None or not _stat.S_ISDIR(d[1].st_mode), d[0].name))
        for e, st in datos:
            if len(entradas) >= _LIST_MAX_ENTRIES:
                truncated = True
                return
            if st is None:
                tipo, size, modified = "unknown", None, None
            else:
                tipo = _tipo(st.st_mode)
                size = st.st_size if tipo == "file" else None
                modified = _fecha(st)
            entradas.append({
                "name": prefijo + e.name,
                "type": tipo,
                "size_bytes": size,
                "modified": modified,
                "is_blacklisted": blacklisted_name(e.name)[0],
            })
            # Nunca se entra en un symlink (`tipo` sale de `lstat`).
            if recursive and tipo == "dir" and nivel < max_depth:
                recoger(Path(e.path), prefijo + e.name + "/", nivel + 1)
                if truncated:
                    return

    recoger(base, "", 1)
    return entradas, truncated


def _leer_lineas(p: Path, offset: int, limit: int) -> dict[str, Any]:
    """Lee `limit` líneas desde `offset` sin cargar el fichero entero.

    Devuelve `binary: True` si hay un byte nulo en los primeros 8 KiB. Si el
    texto no es UTF-8 se vuelve a leer como latin-1 (como `detect_encoding`).
    `more` dice si quedan líneas después del trozo.
    """
    size = os.stat(p).st_size
    with _open_file_nofollow(p) as f:
        probe = f.read(_BINARY_PROBE)
    if is_binary(probe):
        return {"binary": True, "size": size}
    contar_todas = size <= TOTAL_LINES_MAX_BYTES
    for encoding in ("utf-8", "latin-1"):
        try:
            return {"size": size, **_trozo(p, encoding, offset, limit, contar_todas, probe)}
        except UnicodeDecodeError:
            continue
    raise AssertionError("latin-1 decodifica cualquier secuencia de bytes")  # pragma: no cover


def _trozo(p: Path, encoding: str, offset: int, limit: int,
           contar_todas: bool, probe: bytes) -> dict[str, Any]:
    nombre = encoding
    if encoding == "utf-8" and probe.startswith(_UTF8_BOM):
        encoding, nombre = "utf-8-sig", "utf-8-bom"
    decoder = codecs.getincrementaldecoder(encoding)("strict")
    lineas: list[str] = []
    total = 0
    more = False
    pendiente = ""

    def anotar(linea: str) -> bool:
        """Cuenta una línea; False cuando ya no hace falta leer más."""
        nonlocal total, more
        if offset <= total < offset + limit:
            lineas.append(linea)
        elif total >= offset + limit:
            more = True
        total += 1
        return contar_todas or not more

    with _open_file_nofollow(p) as f:
        seguir = True
        while seguir:
            bloque = f.read(1024 * 1024)
            texto = decoder.decode(bloque, final=not bloque)
            pendiente += texto
            # Mismas fronteras que `splitlines(keepends=True)`, pero sin
            # cortar un `\r\n` que llega partido entre dos bloques.
            partes = pendiente.splitlines(keepends=True)
            if bloque and partes and (not partes[-1].endswith(("\n", "\r"))
                                      or partes[-1].endswith("\r")):
                pendiente = partes.pop()
            else:
                pendiente = ""
            for linea in partes:
                if not anotar(linea):
                    seguir = False
                    break
            if not bloque:
                break
    return {
        "encoding": nombre,
        "lines": lineas,
        "total_lines": total if contar_todas else None,
        "more": more,
    }


async def _apps_instaladas(ha_client: Any) -> set[str] | None:
    """Slugs instalados según el Supervisor (`GET /addons`), o `None` si no
    respondió o respondió algo que no se entiende (fail-closed: «no se sabe»)."""
    try:
        data = await ha_client.sv_request("GET", "/addons")
    except Exception:  # noqa: BLE001 — caído, sin permiso o lo que sea: no se sabe
        return None
    apps = data.get("addons") if isinstance(data, dict) else None
    if not isinstance(apps, list):
        return None
    return {a["slug"] for a in apps if isinstance(a, dict) and isinstance(a.get("slug"), str)}


# ── Registro ──────────────────────────────────────────────────────────────────

def register(
    mcp: object,
    ha_client: object,
    *,
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
) -> None:
    """Registra las tools de lectura de /addons y /share."""

    @mcp.tool()
    async def fs_list_dir_in_folder(
        folder: str,
        path: str = ".",
        recursive: bool = False,
        max_depth: int = 3,
    ) -> object:
        """List a directory under /addons (local apps) or /share.

        `folder` is "addons" or "share"; `path` is relative to that folder
        ("." is its root; "/addons/x" or "/share/x" are also accepted). Paths
        that leave the folder (`..`, a symlink pointing outside, another
        absolute path) are rejected with "traversal".

        Symlinks are listed as "symlink" and never followed. Files whose name
        is sensitive (secrets.yaml, *.key, *.pem, *token*, *.db…) appear with
        is_blacklisted: true; their content cannot be read.

        Args:
            folder: "addons" or "share".
            path: Directory relative to the folder. Default: its root.
            recursive: List subfolders too.
            max_depth: Depth when recursive (1-3).

        Returns:
            {"folder", "path", "count", "items": [{"name", "type"
            ("file"|"dir"|"symlink"|"other"), "size_bytes", "modified",
            "is_blacklisted"}], "truncated"}; at most 500 items (with a hint
            when truncated). Errors: invalid_argument, folder_unavailable,
            traversal, not_found, not_a_directory.
        """
        tool = "fs_list_dir_in_folder"
        max_depth = max(1, min(int(max_depth), _MAX_DEPTH))
        abs_path = _resolver(folder, path)
        if isinstance(abs_path, dict):
            return _rechazo(tool, folder, path, abs_path)
        rel = _folders.relativa(folder, abs_path)
        if not abs_path.exists():
            return _rechazo(tool, folder, rel, {"error": "not_found", "path": rel})
        if not abs_path.is_dir():
            return _rechazo(tool, folder, rel, {"error": "not_a_directory", "path": rel})

        entradas, truncated = await asyncio.to_thread(_listar, abs_path, recursive, max_depth)

        def construir(items: list[Any], recortada: bool) -> dict[str, Any]:
            cabecera: dict[str, Any] = {"folder": folder, "path": rel}
            if truncated or recortada:
                cabecera["hint"] = (
                    f"More than {len(items)} entries; use a more specific path"
                    if recortada and not truncated else
                    f"More than {_LIST_MAX_ENTRIES} entries; use a more specific path"
                )
            return sobre_de_lista(items, truncated=truncated or recortada, **cabecera)

        resultado = ajustar_lista_a_bytes(entradas, construir, response_max_bytes)
        _log(tool, folder, rel, "ok")
        return resultado

    @mcp.tool()
    async def fs_stat_in_folder(folder: str, path: str) -> object:
        """Metadata of a file or directory under /addons or /share, without
        reading it.

        `folder` is "addons" or "share"; `path` is relative to it. A symlink
        pointing inside the folder is followed; one pointing outside is
        rejected ("traversal"). In "addons", when the path is the folder of a
        local app (it has a config.yaml/yml/json with a `slug`), `app` says
        its slug (local_<slug>) and whether it is installed (null if the
        Supervisor did not answer).

        Returns:
            {"folder", "path", "type", "size_bytes", "modified",
            "is_blacklisted", "is_mount_point"} and, for a local app folder,
            "app": {"slug", "installed"}. Errors: invalid_argument,
            folder_unavailable, traversal, not_found.
        """
        tool = "fs_stat_in_folder"
        abs_path = _resolver(folder, path)
        if isinstance(abs_path, dict):
            return _rechazo(tool, folder, path, abs_path)
        rel = _folders.relativa(folder, abs_path)
        try:
            st = await asyncio.to_thread(os.lstat, abs_path)
        except FileNotFoundError:
            return _rechazo(tool, folder, rel, {"error": "not_found", "path": rel})
        except OSError as exc:
            return _rechazo(tool, folder, rel, {"error": "io_error", "detail": str(exc)})
        tipo = _tipo(st.st_mode)
        base = _folders.raiz(folder)
        try:
            dev_raiz = os.lstat(base).st_dev
        except OSError:
            dev_raiz = None
        resultado: dict[str, Any] = {
            "folder": folder,
            "path": rel,
            "type": tipo,
            "size_bytes": st.st_size if tipo == "file" else None,
            "modified": _fecha(st),
            "is_blacklisted": blacklisted_name(abs_path.name)[0],
            "is_mount_point": tipo == "dir" and (
                _folders.es_punto_de_montaje(abs_path)
                or (abs_path != base and dev_raiz is not None and st.st_dev != dev_raiz)
            ),
        }
        if folder == "addons" and tipo == "dir":
            indice = await asyncio.to_thread(_folders.indice_de_apps_locales, base)
            slug = indice.app_de_carpeta(rel)
            # Solo se pregunta al Supervisor si la ruta es la carpeta de una
            # app: un `stat` cualquiera no tiene por qué depender de él.
            if slug is not None:
                instaladas = await _apps_instaladas(ha_client)
                resultado["app"] = {
                    "slug": slug,
                    "installed": None if instaladas is None else slug in instaladas,
                }
        _log(tool, folder, rel, "ok")
        return resultado

    @mcp.tool()
    async def fs_read_file_in_folder(
        folder: str,
        path: str,
        offset: int = 0,
        limit: int = 500,
    ) -> object:
        """Read a text file under /addons or /share by lines.

        `folder` is "addons" or "share"; `path` is relative to it. Reads
        `limit` lines (max 5000) starting at line `offset` (0-based) without
        loading the whole file; if more lines remain, `truncated: true` and
        `next_offset` say where to continue. The answer is also cut to the
        response size limit.

        Files with a sensitive name (secrets.yaml, *.key, *.pem, *token*,
        *.db…) are rejected ("blacklisted"), as under /config. A binary file
        (null byte in its first 8 KiB) returns only its metadata. The rest is
        returned as is, not redacted, like fs_read_file.

        Returns:
            {"folder", "path", "size_bytes", "encoding", "offset",
            "returned_lines", "total_lines" (null above 4 MiB), "lines",
            "truncated"} plus "next_offset" and "hint" when truncated. Binary:
            {"folder", "path", "size_bytes", "binary": true, "content": null,
            "hint"}. Errors: invalid_argument, folder_unavailable, traversal,
            blacklisted, not_found, is_directory, io_error.
        """
        tool = "fs_read_file_in_folder"
        limit = max(1, min(int(limit), _MAX_LINES_PER_READ))
        offset = max(0, int(offset))
        abs_path = _resolver(folder, path)
        if isinstance(abs_path, dict):
            return _rechazo(tool, folder, path, abs_path)
        rel = _folders.relativa(folder, abs_path)
        bloqueado, motivo = blacklisted_name(abs_path.name)
        if bloqueado:
            return _rechazo(tool, folder, rel, {
                "error": "blacklisted",
                "detail": f"Access denied to {rel!r}: {motivo}",
            })
        if not abs_path.exists():
            return _rechazo(tool, folder, rel, {"error": "not_found", "path": rel})
        if abs_path.is_dir():
            return _rechazo(tool, folder, rel, {
                "error": "is_directory", "path": rel,
                "hint": "Use fs_list_dir_in_folder to list a directory.",
            })
        try:
            leido = await asyncio.to_thread(_leer_lineas, abs_path, offset, limit)
        except FileNotFoundError:
            return _rechazo(tool, folder, rel, {"error": "not_found", "path": rel})
        except OSError as exc:
            return _rechazo(tool, folder, rel, {"error": "io_error", "detail": str(exc)})

        if leido.get("binary"):
            _log(tool, folder, rel, "ok")
            return {
                "folder": folder, "path": rel, "size_bytes": leido["size"],
                "binary": True, "content": None,
                "hint": "Binary file: only metadata is returned.",
            }

        lineas: list[str] = leido["lines"]

        def armar(n: int, recortada: bool) -> dict[str, Any]:
            truncated = recortada or leido["more"]
            out: dict[str, Any] = {
                "folder": folder,
                "path": rel,
                "size_bytes": leido["size"],
                "encoding": leido["encoding"],
                "offset": offset,
                "returned_lines": n,
                "total_lines": leido["total_lines"],
                "lines": lineas[:n],
                "truncated": truncated,
            }
            if truncated:
                out["next_offset"] = offset + n
                out["hint"] = (
                    "More lines remain; call again with offset=next_offset."
                    if n else
                    "The line at this offset alone exceeds the response size limit."
                )
            return out

        resultado = armar(len(lineas), False)
        if tam_json(resultado) > response_max_bytes:
            # Estimación lineal con el tamaño escapado de cada línea y
            # verificación con el tamaño real, quitando de una en una.
            presupuesto = response_max_bytes - tam_json(armar(0, True)) - 8
            n = usado = 0
            for linea in lineas:
                # Las comillas de la línea cuentan lo mismo que el ", ".
                coste = tam_json(linea)
                if usado + coste > presupuesto:
                    break
                usado += coste
                n += 1
            resultado = armar(n, True)
            while n > 0 and tam_json(resultado) > response_max_bytes:
                n -= 1
                resultado = armar(n, True)
        _log(tool, folder, rel, "ok")
        return resultado
