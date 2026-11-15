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


def _leer_lineas(p: Path, offset: int, limit: int,
                 presupuesto: int = RESPONSE_MAX_BYTES_DEFAULT) -> dict[str, Any]:
    """Lee `limit` líneas desde `offset` sin cargar el fichero entero.

    Devuelve `binary: True` si hay un byte nulo en los primeros 8 KiB. Si el
    texto no es UTF-8 se vuelve a leer como latin-1 (como `detect_encoding`).
    `more` dice si quedan líneas después del trozo (o si se paró antes del
    final por el presupuesto). `presupuesto` es el tope de caracteres que se
    guardan de las líneas que se van a devolver (convergencia T045): más no
    cabría en la respuesta, así que tampoco se carga en memoria.

    Raises:
        NoEsFichero: `p` no es un fichero regular (T049).
        OSError: si no se puede leer.
    """
    with _abrir_regular(p) as f:
        size = os.fstat(f.fileno()).st_size
        probe = f.read(_BINARY_PROBE)
        if is_binary(probe):
            return {"binary": True, "size": size}
        contar_todas = size <= TOTAL_LINES_MAX_BYTES
        for encoding in ("utf-8", "latin-1"):
            try:
                f.seek(0)
                return {"size": size, **_trozo(f, encoding, offset, limit, contar_todas,
                                               probe, presupuesto)}
            except UnicodeDecodeError:
                continue
    raise AssertionError("latin-1 decodifica cualquier secuencia de bytes")  # pragma: no cover


def _no_regular(rel: str) -> dict[str, Any]:
    return {"error": "not_regular_file", "path": rel,
            "detail": ("Not a regular file (a FIFO, socket or device): it is not "
                       "read nor written, so nothing can block waiting on it.")}


class NoEsFichero(OSError):
    """La ruta no es un fichero regular (FIFO, socket, dispositivo): no se lee
    (convergencia T049)."""


def _abrir_regular(p: Path):
    """Abre `p` para leer SOLO si es un fichero regular (T049).

    Un FIFO sin escritor bloquea `open(O_RDONLY)` para siempre (en `/share`
    los hay, p. ej. el de Snapcast); un dispositivo puede no acabar nunca.
    Por eso: `lstat` antes (sin abrir nada), apertura con `O_NONBLOCK` (en
    un FIFO vuelve en el acto) y `fstat` del descriptor después (lo que se
    abrió es lo que se lee, aunque alguien cambie el fichero en medio).
    """
    if not _stat.S_ISREG(os.lstat(p).st_mode):
        raise NoEsFichero(f"{p.name!r} is not a regular file")
    fd = os.open(str(p), os.O_RDONLY | _O_NOFOLLOW | _O_NONBLOCK | _O_BINARY)
    try:
        if not _stat.S_ISREG(os.fstat(fd).st_mode):
            raise NoEsFichero(f"{p.name!r} is not a regular file")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_O_BINARY = getattr(os, "O_BINARY", 0)
#: Lo que `str.splitlines` toma como fin de línea (`\r\n` acaba en `\n`).
_FINES: tuple[str, ...] = ("\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e",
                           "\x85", "\u2028", "\u2029")
#: Bloque de lectura. Mutable para los tests.
TAM_BLOQUE = 1024 * 1024


def _trozo(f: Any, encoding: str, offset: int, limit: int,
           contar_todas: bool, probe: bytes, presupuesto: int) -> dict[str, Any]:
    """Las líneas `[offset, offset+limit)` de `f`, leyendo por bloques.

    Memoria acotada (convergencia T045): de una línea solo se guarda lo que
    cabe en `presupuesto` (caracteres; un carácter ocupa al menos un byte en
    la respuesta) y, de las que no se devuelven, nada. Así un fichero de
    varios GB sin un solo salto de línea ocupa a lo sumo `presupuesto` más un
    bloque. Solo la PRIMERA línea de la página puede salir cortada (es la
    única forma de avanzar); si otra no cabe entera, la página acaba antes
    de ella y la siguiente llamada empieza por ella con todo el presupuesto.
    """
    nombre = encoding
    if encoding == "utf-8" and probe.startswith(_UTF8_BOM):
        encoding, nombre = "utf-8-sig", "utf-8-bom"
    decoder = codecs.getincrementaldecoder(encoding)("strict")
    lineas: list[str] = []
    cortes: list[dict[str, Any]] = []
    total = 0
    more = False
    usado = 0
    # La línea en curso: trozos guardados, caracteres vistos y si se cortó.
    trozos: list[str] = []
    guardado = 0
    largo = 0
    cortada = False
    # Un `\r` al final de un bloque: la línea queda abierta por si el
    # siguiente empieza con `\n` (mismas fronteras que `splitlines`).
    cr_pendiente = False

    def en_pagina() -> bool:
        return offset <= total < offset + limit and not more

    def anadir(parte: str) -> None:
        nonlocal guardado, largo, cortada
        largo += len(parte)
        if not en_pagina():
            return
        sitio = presupuesto - usado - guardado
        if sitio <= 0:
            cortada = cortada or bool(parte)
            return
        if len(parte) > sitio:
            parte, cortada = parte[:sitio], True
        trozos.append(parte)
        guardado += len(parte)

    def cerrar() -> bool:
        """Cierra la línea en curso; False cuando ya no hace falta leer más."""
        nonlocal total, more, usado, trozos, guardado, largo, cortada
        if offset <= total < offset + limit and not more:
            if cortada and lineas:
                # No es la primera de la página: no se corta, se deja para
                # la siguiente llamada.
                more = True
            else:
                lineas.append("".join(trozos))
                usado += guardado
                if cortada:
                    cortes.append({"line": total, "returned_chars": guardado,
                                   "line_chars": largo})
        elif total >= offset + limit:
            more = True
        total += 1
        trozos, guardado, largo, cortada = [], 0, 0, False
        if not contar_todas and (more or usado >= presupuesto):
            more = True
            return False
        return True

    seguir = True
    while seguir:
        bloque = f.read(TAM_BLOQUE)
        texto = decoder.decode(bloque, final=not bloque)
        if cr_pendiente and texto:
            cr_pendiente = False
            if texto.startswith("\n"):
                anadir("\n")
                texto = texto[1:]
            if not cerrar():
                break
        partes = texto.splitlines(keepends=True)
        for i, parte in enumerate(partes):
            anadir(parte)
            if not parte.endswith(_FINES):
                continue  # la última, sin terminar: sigue en el próximo bloque
            if parte.endswith("\r") and i == len(partes) - 1 and bloque:
                cr_pendiente = True
                continue
            if not cerrar():
                seguir = False
                break
        else:
            # Corte de una línea gigante a mitad (fichero grande): no hace
            # falta leer hasta su final para devolver lo que cabe.
            if (not contar_todas and cortada and en_pagina()
                    and not lineas and not cr_pendiente):
                cortes.append({"line": total, "returned_chars": guardado,
                               "line_chars": None})
                lineas.append("".join(trozos))
                more = True
                break
        if not bloque:
            if cr_pendiente or largo:
                cerrar()
            break
    return {
        "encoding": nombre,
        "lines": lineas,
        "cut_lines": cortes,
        # Con `contar_todas` nunca se para antes del final: el recuento vale.
        "total_lines": total if contar_todas else None,
        "more": more,
    }


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
                instaladas = await _folders.apps_instaladas(ha_client)
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
        `limit` lines (max 5000) starting at line `offset` (0-based), in
        blocks, keeping in memory only what fits in the answer; if more lines
        may remain, `truncated: true` and `next_offset` say where to
        continue. The answer is also cut to the response size limit. A line
        longer than that limit (a minified file, a dump without line breaks)
        is returned cut, only when it is the first of the page: `cut_lines`
        says which one and how many characters came back; the rest of that
        line cannot be read with this tool.

        Only regular files are read: a FIFO, socket or device returns
        not_regular_file without opening it.

        Files with a sensitive name (secrets.yaml, *.key, *.pem, *token*,
        *.db…) are rejected ("blacklisted"), as under /config. A binary file
        (null byte in its first 8 KiB) returns only its metadata. The rest is
        returned as is, not redacted, like fs_read_file.

        Returns:
            {"folder", "path", "size_bytes", "encoding", "offset",
            "returned_lines", "total_lines" (null above 4 MiB), "lines",
            "truncated"} plus "next_offset" and "hint" when truncated and
            "cut_lines": [{"line", "returned_chars", "line_chars"}] when a
            line was cut. Binary: {"folder", "path", "size_bytes", "binary":
            true, "content": null, "hint"}. Errors: invalid_argument,
            folder_unavailable, traversal, blacklisted, not_found,
            is_directory, not_regular_file, io_error.
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
            leido = await asyncio.to_thread(_leer_lineas, abs_path, offset, limit,
                                            response_max_bytes)
        except FileNotFoundError:
            return _rechazo(tool, folder, rel, {"error": "not_found", "path": rel})
        except NoEsFichero:
            return _rechazo(tool, folder, rel, _no_regular(rel))
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
        cortes: dict[int, dict[str, Any]] = {c["line"]: c for c in leido["cut_lines"]}

        def armar(n: int, recortada: bool, primera: str | None = None) -> dict[str, Any]:
            truncated = recortada or leido["more"]
            devueltas = lineas[:n]
            cortadas = [dict(cortes[offset + i]) for i in range(n) if offset + i in cortes]
            if primera is not None and n:
                # La primera línea, recortada aún más para que quepa con sus
                # escapes JSON: se dice cuánto se devuelve de ella.
                devueltas = [primera] + devueltas[1:]
                if cortadas and cortadas[0]["line"] == offset:
                    cortadas[0]["returned_chars"] = len(primera)
                else:
                    cortadas.insert(0, {"line": offset, "returned_chars": len(primera),
                                        "line_chars": len(lineas[0])})
            out: dict[str, Any] = {
                "folder": folder,
                "path": rel,
                "size_bytes": leido["size"],
                "encoding": leido["encoding"],
                "offset": offset,
                "returned_lines": n,
                "total_lines": leido["total_lines"],
                "lines": devueltas,
                "truncated": truncated,
            }
            if cortadas:
                out["cut_lines"] = cortadas
            if truncated:
                out["next_offset"] = offset + n
                out["hint"] = (
                    "More lines may remain; call again with offset=next_offset."
                    if n else
                    "The line at this offset alone exceeds the response size limit."
                )
            if cortadas:
                out["hint"] = (
                    "Line " + ", ".join(str(c["line"]) for c in cortadas)
                    + " is longer than the response size limit and was cut: only "
                    "its first returned_chars characters are returned "
                    "(line_chars is its length, null if not read to its end). "
                    "The rest of that line cannot be read with this tool."
                    + (" Call again with offset=next_offset for the next lines."
                       if truncated else "")
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
            if n == 0 and lineas:
                # Ni la primera cabe entera (escapes JSON): se recorta para
                # avanzar siempre (T045). Búsqueda binaria del trozo más largo.
                bajo, alto = 0, len(lineas[0])
                while bajo < alto:
                    medio = (bajo + alto + 1) // 2
                    if tam_json(armar(1, True, lineas[0][:medio])) <= response_max_bytes:
                        bajo = medio
                    else:
                        alto = medio - 1
                if bajo:
                    # Truncada solo si quedan líneas: el corte lo dice `cut_lines`.
                    resultado = armar(1, len(lineas) > 1, lineas[0][:bajo])
        _log(tool, folder, rel, "ok")
        return resultado
