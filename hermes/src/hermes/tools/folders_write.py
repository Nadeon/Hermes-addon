"""Hermes — Tools MCP que modifican /addons y /share (spec 034, 1.2.1).

Familia `addons_share`, junto a `tools/folders.py` (lectura). Cuatro tools,
todas en DOS pasos (D-5):

  fs_write_file_in_folder  — crea o sobrescribe un fichero de texto
  fs_create_dir_in_folder  — crea una carpeta (y sus padres)
  fs_move_in_folder        — mueve o renombra dentro de la misma carpeta
  fs_delete_in_folder      — borra un fichero, un symlink o una carpeta

POR QUÉ ASÍ
-----------
- El token ata la tool, `folder`, las rutas ya normalizadas, el contenido y
  `recursive` (action_hash) y, con `estado`, la HUELLA de lo que la vista
  previa vio (`folders.huella`). Al confirmar se vuelve a calcular: si algo
  cambió dentro del objetivo, `ESTADO_CAMBIADO` y no se toca nada (FR-011,
  FR-012). Lo que la vista previa promete («se borran 12 ficheros») tiene
  que ser lo que se hace.
- Lo que NO va en la huella se vuelve a comprobar entero al confirmar
  (FR-017): la raíz, los puntos de montaje, el padre del destino y, en
  `/addons`, las apps locales instaladas (una app que se instala entre la
  vista previa y la confirmación cancela el borrado). Si algo ya no se
  cumple, el token se completa con error: no se queda en `executing`.
- Borrar y mover actúan sobre el ENLACE si la ruta es un symlink
  (`folders.normalizar_sin_seguir`), nunca sobre su destino, que puede estar
  fuera de la carpeta; el borrado recursivo no sigue ninguno y no entra en
  puntos de montaje (un NAS bajo `/share`): borrar o mover algo que los
  contiene se rechaza.
- Las confirmaciones de una carpeta van de una en una (`folders.candado`)
  y la operación final vuelve a resolver la ruta en su hilo, justo antes de
  la llamada al sistema, y opera relativa al descriptor de la carpeta padre
  donde el sistema lo da (convergencia T048). Solo se sobrescriben ficheros
  regulares (T049).
- No hay backup (research R-6): la vista previa lo dice (`backup: null`) y
  da la llamada exacta para hacerlo antes.

Las `fs_*` de `/config` no cambian (D-4); de ellas se reutiliza la escritura
atómica (`safe_write_file`) y, a través de `hermes.folders`, la validación de
rutas.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import inspect
import os
import shutil
from pathlib import Path
from typing import Any

from hermes import folders as _folders
from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes import fs as _fs
from hermes.fs import PathTraversalError, blacklisted_name
from hermes.fs_write import safe_write_file
from hermes.security import (
    ESTADO_CAMBIADO,
    complete_confirmation_token,
    create_confirmation_token,
    resolve_confirmation_token,
)
from hermes.tools._common import tam_json
from hermes.tools.folders import _log, _rechazo, _resolver

# `content` es lo único grande: la vista previa lo guarda en el servidor y la
# confirmación puede omitirlo (como `fs_write_file`, spec 007).
_OMITIBLES_ESCRIBIR = ("content",)

#: Lo que ocupan las claves del token alrededor de la vista previa, con
#: margen, para recortar la muestra antes de emitirlo (FR-025).
_RESERVA_TOKEN = 400


# ── Ayudantes ─────────────────────────────────────────────────────────────────

def _sha12(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()[:12]


def _es_raiz_pedida(folder: str, path: object) -> bool:
    """True si `path` nombra la raíz de la carpeta (vacía, `.`, `/addons`,
    `x/..`). Se mira ANTES de `normalizar_sin_seguir`, que no la admite como
    último nombre, para responder `root_protected` y no `traversal`.

    Solo cuando el último nombre es vacío, `.` o `..`: un symlink que apunta
    a la raíz es un enlace más y se puede borrar (sin tocar su destino)."""
    if not isinstance(path, str) or not path.strip():
        return True
    try:
        base = _folders.raiz(folder)
        relativa = _fs.prepare_in_root(path, base, "/" + folder)
        if relativa is None:
            return True
        if relativa.rstrip("/").rpartition("/")[2] not in ("", ".", ".."):
            return False
        return _folders.es_raiz(folder, _folders.normalizar(folder, path))
    except (PathTraversalError, _folders.CarpetaError):
        return False


def _quitar_enlace_o_fichero(p: Path) -> None:
    """`unlink` borra el enlace, nunca su destino. En Windows un symlink a
    una carpeta se quita con `rmdir` (que tampoco toca el destino)."""
    try:
        os.unlink(p)
    except (IsADirectoryError, PermissionError):
        if os.path.islink(p):
            os.rmdir(p)
        else:
            raise


def _sin_seguir(folder: str, path: str) -> Path | dict[str, Any]:
    """Ruta del objetivo SIN seguir el último symlink, o el rechazo listo
    (`root_protected` para la raíz, `traversal`, `invalid_argument`,
    `folder_unavailable`)."""
    try:
        _folders.raiz(folder)
    except _folders.CarpetaError as exc:
        return exc.respuesta()
    if _es_raiz_pedida(folder, path):
        return {
            "error": "root_protected", "path": ".",
            "detail": "The root of the folder itself cannot be deleted or moved.",
        }
    try:
        return _folders.normalizar_sin_seguir(folder, path)
    except _folders.CarpetaError as exc:
        return exc.respuesta()
    except PathTraversalError as exc:
        return {"error": "traversal", "detail": str(exc)}


def _ajustar_muestra(preview: dict[str, Any], response_max_bytes: int) -> None:
    """Recorta la muestra de `contents` hasta que la respuesta quepa en el
    tope (FR-025). La muestra es lo único que crece con la ruta."""
    contenido = preview.get("contents")
    if not isinstance(contenido, dict):
        return
    while (contenido["sample"]
           and tam_json(preview) + _RESERVA_TOKEN > response_max_bytes):
        contenido["sample"].pop()
        contenido["sample_truncated"] = True


def _muestra_para(recuento: dict[str, Any]) -> dict[str, Any]:
    return dict(recuento, sample=list(recuento["sample"]))


async def _apps(ha_client: Any, folder: str, rel: str, *, modo: str,
                contenido: str | None = None,
                otras: tuple[str, ...] = ()) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Comprobación de apps instaladas (FR-019), solo en `addons`: en `share`
    no se pregunta nada al Supervisor."""
    if folder != "addons":
        return None, {}
    return await _folders.comprobar_apps_instaladas(
        ha_client, rel, modo=modo, contenido=contenido, otras=otras)


def _estado_cambiado() -> dict[str, Any]:
    return {
        "error": ESTADO_CAMBIADO,
        "preview_outdated": True,
        "hint": ("The target changed since the preview. Nothing was done; "
                 "request a new preview."),
    }


async def _validar_token(tool: str, folder: str, rel: str, token: str,
                         args: dict[str, Any], estado: Any, *,
                         omitibles: tuple[str, ...] = ()) -> tuple[bool, dict[str, Any]]:
    """`resolve_confirmation_token` con el estado actual. Devuelve los
    argumentos resueltos o el rechazo listo (ya registrado en el log)."""
    ok, error, resueltos = await resolve_confirmation_token(
        token, tool, args, omitibles=omitibles, estado=estado)
    if ok:
        return True, resueltos
    if error == ESTADO_CAMBIADO:
        _log(tool, folder, rel, "rejected:preview_outdated")
        return False, _estado_cambiado()
    _log(tool, folder, rel, "rejected:token")
    return False, {"error": error}


async def _fallo(tool: str, folder: str, rel: str, token: str,
                 respuesta: dict[str, Any]) -> dict[str, Any]:
    """Una comprobación repetida al confirmar ya no se cumple (FR-017): no se
    hace nada y el token se completa con error (no se queda «executing»)."""
    await complete_confirmation_token(token, success=False, error=str(respuesta.get("error")))
    return _rechazo(tool, folder, rel, respuesta)


def _rechazo_de_inspeccion(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, _folders.ArbolDemasiadoGrande):
        return dict(exc.respuesta(),
                    hint="Work on smaller subfolders; the preview walks the whole tree.")
    return {"error": "io_error", "detail": str(exc)}


def _mount_point(rel: str) -> dict[str, Any]:
    return {
        "error": "mount_point", "path": rel,
        "detail": (f"{rel!r} is or contains a mount point (for example a network "
                   "share mounted by the Supervisor under /share). Deleting or "
                   "moving it would touch the mounted storage; it is refused."),
    }


def _con_candado(fn: Any) -> Any:
    """Las confirmaciones (con `confirmation_token`) de una carpeta van de una
    en una bajo `folders.candado(folder)` (convergencia T048): de la
    comprobación del token a la llamada al sistema, ninguna otra escritura de
    Hermes en esa carpeta se cuela en medio. Las vistas previas no lo toman.
    `functools.wraps` conserva el nombre, la firma y las anotaciones (el
    esquema MCP no cambia)."""
    firma = inspect.signature(fn)

    @functools.wraps(fn)
    async def envoltura(*args: Any, **kwargs: Any) -> Any:
        argumentos = firma.bind_partial(*args, **kwargs).arguments
        if not argumentos.get("confirmation_token"):
            return await fn(*args, **kwargs)
        async with _folders.candado(argumentos.get("folder")):
            return await fn(*args, **kwargs)
    return envoltura


def _en_padre(base: Path, p: Path, operar_fd: Any, operar_ruta: Any, *,
              crear: bool = False) -> Any:
    """La llamada al sistema final sobre `p` (T048): relativa al descriptor
    de su carpeta padre, abierta desde la raíz sin seguir symlinks, donde el
    sistema lo da (Linux); por ruta donde no (Windows), con la revalidación
    previa como defensa. Se llama en el mismo hilo, justo después de
    `folders.revalidar`. `crear` crea las carpetas padre que falten."""
    if not _folders.USAR_DIR_FD:
        if crear:
            p.parent.mkdir(parents=True, exist_ok=True)
        return operar_ruta(p)
    fd = _folders.abrir_padre(base, p.parent, crear=crear)
    try:
        return operar_fd(p.name, fd)
    finally:
        os.close(fd)


def _fallo_de_operacion(exc: Exception, rel: str) -> dict[str, Any]:
    """La respuesta de un fallo en la operación final."""
    if isinstance(exc, _folders.RutaCambiada):
        return exc.respuesta()
    if isinstance(exc, _folders.NoRegular):
        return exc.respuesta(rel)
    return {"error": "io_error", "detail": str(exc)}


#: Lo que puede fallar en la operación final (`RutaCambiada` no es OSError).
_FALLOS = (_folders.RutaCambiada, OSError)


def _faltan_padres(base: Path, p: Path) -> tuple[list[Path], dict[str, Any] | None]:
    """Padres de `p` que no existen (de arriba abajo), o el rechazo si el
    más cercano que existe no es una carpeta."""
    faltan: list[Path] = []
    actual = p.parent
    while actual != base and not os.path.lexists(actual):
        faltan.append(actual)
        actual = actual.parent
    if not actual.is_dir():
        return faltan, {
            "error": "not_a_directory",
            "path": actual.relative_to(base).as_posix() or ".",
            "detail": "A parent of the path exists and is not a directory.",
        }
    return list(reversed(faltan)), None


# ── Registro ──────────────────────────────────────────────────────────────────

def register(
    mcp: object,
    ha_client: object,
    *,
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
) -> None:
    """Registra las tools que modifican /addons y /share."""

    # ── fs_write_file_in_folder ───────────────────────────────────────────────

    @mcp.tool()
    @_con_candado
    async def fs_write_file_in_folder(
        folder: str,
        path: str,
        # `str` exactamente, y no `str | None`, como en `fs_write_file`: el
        # SDK hace `json.loads` de todo argumento de texto cuya anotación no
        # es exactamente `str`, y un `.json` llegaría convertido en dict.
        content: str = None,  # type: ignore[assignment]
        confirmation_token: str | None = None,
    ) -> object:
        """Create or overwrite a UTF-8 text file under /addons (local apps) or
        /share. ALWAYS two steps.

        `folder` is "addons" or "share"; `path` is relative to it (missing
        parent folders are created). First call (no token): a preview with
        the current and new size and short SHA-256, and a confirmation_token.
        Second call: the same `folder` and `path` plus the token; `content`
        can be omitted (the server kept it) and, if sent, must be identical.
        The token is bound to the file's current state: if it changes before
        confirming, nothing is written and a new preview is needed.

        No backup is made and it cannot be undone from Hermes; the preview
        gives the sv_create_backup_partial call to make one first. In
        "addons" the preview warns that the Supervisor builds and runs that
        code; the config.yaml of an installed local app cannot be rewritten
        with another slug. Files with a sensitive name can be written, but
        no preview shows content.

        Returns:
            Preview: {"confirmation_token", "expires_in_seconds", "preview":
            {"action": "write", "folder", "path", "exists",
            "current_size_bytes", "current_sha256_12", "new_size_bytes",
            "new_sha256_12", "is_blacklisted", "backup": null, ...}}.
            Confirmed: {"result": "ok", "action", "folder", "path",
            "bytes_written"}. Errors: invalid_argument, folder_unavailable,
            traversal, is_directory, not_a_directory, not_regular_file (a
            FIFO, socket or device is never overwritten), installed_app,
            installed_check_failed, preview_outdated, path_changed (a
            folder on the way changed while confirming: nothing was done),
            io_error.
        """
        tool = "fs_write_file_in_folder"
        p = _resolver(folder, path)
        if isinstance(p, dict):
            return _rechazo(tool, folder, path, p)
        rel = _folders.relativa(folder, p)
        base = _folders.raiz(folder)

        def comprobar() -> dict[str, Any] | None:
            if p.is_dir():
                return {"error": "is_directory", "path": rel,
                        "hint": "fs_write_file_in_folder only writes files."}
            try:
                _folders.exigir_regular_o_ausente(p)
            except _folders.NoRegular as exc:
                return exc.respuesta(rel)
            return _faltan_padres(base, p)[1]

        if not confirmation_token and (error := comprobar()):
            return _rechazo(tool, folder, rel, error)
        if content is None and not confirmation_token:
            return _rechazo(tool, folder, rel, {
                "error": "invalid_argument", "field": "content",
                "detail": ("content is required to request a preview; it can only "
                           "be omitted when confirming with confirmation_token."),
            })
        if content is not None and not isinstance(content, str):
            return _rechazo(tool, folder, rel, {
                "error": "invalid_argument", "field": "content",
                "detail": "content must be text.",
            })
        args: dict[str, Any] = {"folder": folder, "path": rel}
        if content is not None:
            args["content"] = content
        try:
            huella = await asyncio.to_thread(_folders.huella, p)
        except (_folders.ArbolDemasiadoGrande, OSError) as exc:
            return _rechazo(tool, folder, rel, _rechazo_de_inspeccion(exc))
        estado = {"target": huella}

        if not confirmation_token:
            error, extra = await _apps(ha_client, folder, rel, modo="escribir",
                                       contenido=content)
            if error:
                return _rechazo(tool, folder, rel, error)
            nuevo = content.encode("utf-8", "surrogatepass")
            preview: dict[str, Any] = {
                "action": "write", "folder": folder, "path": rel,
                "exists": huella["kind"] != "absent",
            }
            if huella["kind"] != "absent":
                preview["current_size_bytes"] = os.lstat(p).st_size
                preview["current_sha256_12"] = (
                    huella["sha256"][:12] if "sha256" in huella else None)
            preview["new_size_bytes"] = len(nuevo)
            preview["new_sha256_12"] = _sha12(nuevo)
            preview["is_blacklisted"] = blacklisted_name(p.name)[0]
            preview.update(extra)
            preview.update(_folders.textos_de_vista_previa(folder))
            respuesta = await create_confirmation_token(
                tool, args, preview=preview, omitibles=_OMITIBLES_ESCRIBIR, estado=estado)
            _log(tool, folder, rel, "preview")
            return respuesta

        ok, resultado = await _validar_token(
            tool, folder, rel, confirmation_token, args, estado,
            omitibles=_OMITIBLES_ESCRIBIR)
        if not ok:
            return resultado
        content = resultado["content"]
        # FR-017: las comprobaciones, otra vez, DESPUÉS del token y su estado
        # (un cambio en el objetivo es `preview_outdated`, no otro rechazo).
        error = comprobar()
        if error is None:
            error, _ = await _apps(ha_client, folder, rel, modo="escribir",
                                   contenido=content)
        if error:
            return await _fallo(tool, folder, rel, confirmation_token, error)
        def escribir() -> int:
            # T048 y T049: en este hilo y sin `await` hasta la escritura.
            _folders.revalidar(folder, rel, p, seguir=True)
            # Crea los padres que falten sin seguir symlinks (o por ruta).
            _en_padre(base, p, lambda _n, _fd: None, lambda _p: None, crear=True)
            _folders.revalidar(folder, rel, p, seguir=True)
            _folders.exigir_regular_o_ausente(p)
            safe_write_file(p, content)
            return os.lstat(p).st_size

        try:
            escritos = await asyncio.to_thread(escribir)
        except _FALLOS as exc:
            return await _fallo(tool, folder, rel, confirmation_token,
                                _fallo_de_operacion(exc, rel))
        respuesta = {"result": "ok", "action": "write", "folder": folder, "path": rel,
                     "bytes_written": escritos}
        await complete_confirmation_token(confirmation_token, success=True, result=respuesta)
        _log(tool, folder, rel, "ok")
        return respuesta

    # ── fs_create_dir_in_folder ───────────────────────────────────────────────

    @mcp.tool()
    @_con_candado
    async def fs_create_dir_in_folder(
        folder: str,
        path: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Create a directory (and its missing parents) under /addons or
        /share. Two steps, like every tool that modifies these folders.

        `folder` is "addons" or "share"; `path` is relative to it. First call
        (no token): a preview listing the parents that will be created, and a
        confirmation_token; second call: the same arguments plus the token.
        If anything already exists at `path` → already_exists (no token).
        No backup is needed: the folder can be removed with
        fs_delete_in_folder. In "addons" the preview warns that the
        Supervisor builds and runs that code.

        Returns:
            Preview: {"confirmation_token", "preview": {"action":
            "create_dir", "folder", "path", "creates_parents", "backup":
            null, "reversible": true, ...}}. Confirmed: {"result": "ok",
            "action", "folder", "path", "created"}. Errors: invalid_argument,
            folder_unavailable, traversal, already_exists, not_a_directory,
            preview_outdated, path_changed, io_error.
        """
        tool = "fs_create_dir_in_folder"
        p = _resolver(folder, path)
        if isinstance(p, dict):
            return _rechazo(tool, folder, path, p)
        rel = _folders.relativa(folder, p)
        base = _folders.raiz(folder)

        def comprobar() -> tuple[list[Path], dict[str, Any] | None]:
            if os.path.lexists(p):
                return [], {"error": "already_exists", "path": rel,
                            "detail": "Something already exists at this path."}
            return _faltan_padres(base, p)

        args = {"folder": folder, "path": rel}
        try:
            estado = {"target": await asyncio.to_thread(_folders.huella, p)}
        except (_folders.ArbolDemasiadoGrande, OSError) as exc:
            return _rechazo(tool, folder, rel, _rechazo_de_inspeccion(exc))

        if not confirmation_token:
            faltan, error = comprobar()
            if error:
                return _rechazo(tool, folder, rel, error)
            _, extra = await _apps(ha_client, folder, rel, modo="crear")
            preview: dict[str, Any] = {
                "action": "create_dir", "folder": folder, "path": rel,
                "creates_parents": [_folders.relativa(folder, f) for f in faltan],
            }
            preview.update(extra)
            preview.update(_folders.textos_de_vista_previa(folder, reversible=True))
            respuesta = await create_confirmation_token(tool, args, preview=preview,
                                                        estado=estado)
            _log(tool, folder, rel, "preview")
            return respuesta

        ok, resultado = await _validar_token(tool, folder, rel, confirmation_token,
                                             args, estado)
        if not ok:
            return resultado
        faltan, error = comprobar()
        if error:
            return await _fallo(tool, folder, rel, confirmation_token, error)
        def crear() -> None:
            # T048: revalidada en este hilo, justo antes de crear.
            _folders.revalidar(folder, rel, p, seguir=True)
            _en_padre(base, p, lambda nombre, fd: os.mkdir(nombre, dir_fd=fd),
                      lambda q: q.mkdir(parents=True, exist_ok=False), crear=True)

        try:
            await asyncio.to_thread(crear)
        except _FALLOS as exc:
            return await _fallo(tool, folder, rel, confirmation_token,
                                _fallo_de_operacion(exc, rel))
        respuesta = {
            "result": "ok", "action": "create_dir", "folder": folder, "path": rel,
            "created": [_folders.relativa(folder, f) for f in faltan] + [rel],
        }
        await complete_confirmation_token(confirmation_token, success=True, result=respuesta)
        _log(tool, folder, rel, "ok")
        return respuesta

    # ── fs_move_in_folder ─────────────────────────────────────────────────────

    def _reglas_mover(info: dict[str, Any], src_p: Path, dst_p: Path,
                      rel_src: str, rel_dst: str) -> dict[str, Any] | None:
        """Rechazos de mover que se miran en la vista previa y otra vez al
        confirmar (FR-015, FR-017), con la inspección del origen."""
        if info["tipo"] is None:
            return {"error": "not_found", "path": rel_src}
        if info["montaje"]:
            return _mount_point(rel_src)
        if os.path.lexists(dst_p):
            return {"error": "destination_exists", "path": rel_dst,
                    "detail": "The destination exists; nothing is overwritten."}
        if not dst_p.parent.is_dir():
            return {"error": "destination_parent_missing", "path": rel_dst,
                    "detail": ("The destination's parent folder does not exist; "
                               "create it first with fs_create_dir_in_folder.")}
        if info["tipo"] == "dir" and (dst_p == src_p or src_p in dst_p.parents):
            return {"error": "invalid_destination", "path": rel_dst,
                    "detail": "A folder cannot be moved inside itself."}
        return None

    @mcp.tool()
    @_con_candado
    async def fs_move_in_folder(
        folder: str,
        src: str,
        dst: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Move or rename a file, symlink or directory WITHIN /addons or
        WITHIN /share (never between them). ALWAYS two steps.

        `folder` is "addons" or "share"; `src` and `dst` are relative to it.
        A symlink is moved as a link (its target is not touched). Refused
        without a token: src missing (not_found), dst exists
        (destination_exists), dst's parent missing
        (destination_parent_missing), dst inside src (invalid_destination),
        the folder root (root_protected), a mount point or a folder that
        contains one (mount_point) and, in "addons", the folder or config
        file of an installed local app (installed_app: uninstall it first).
        The preview counts what a directory holds; the token is bound to the
        state of src and dst, so any change before confirming cancels it.
        No backup is made; the preview gives the call to make one first.

        Returns:
            Preview: {"confirmation_token", "preview": {"action": "move",
            "folder", "src", "dst", "type", "contents"?, "backup": null,
            ...}}. Confirmed: {"result": "ok", "action", "folder", "src",
            "dst"}. Errors: the ones above plus invalid_argument,
            folder_unavailable, traversal, too_large_to_preview,
            installed_check_failed, installed_check_inconclusive,
            preview_outdated, path_changed, io_error.
        """
        tool = "fs_move_in_folder"
        src_p = _sin_seguir(folder, src)
        if isinstance(src_p, dict):
            return _rechazo(tool, folder, src, src_p)
        dst_p = _sin_seguir(folder, dst)
        if isinstance(dst_p, dict):
            return _rechazo(tool, folder, src, dst_p)
        rel_src = _folders.relativa(folder, src_p)
        rel_dst = _folders.relativa(folder, dst_p)
        args = {"folder": folder, "src": rel_src, "dst": rel_dst}

        try:
            info = await asyncio.to_thread(_folders.inspeccionar, src_p)
            estado = {"src": info["huella"],
                      "dst": await asyncio.to_thread(_folders.huella, dst_p)}
        except (_folders.ArbolDemasiadoGrande, OSError) as exc:
            return _rechazo(tool, folder, rel_src, _rechazo_de_inspeccion(exc))

        if not confirmation_token:
            error = _reglas_mover(info, src_p, dst_p, rel_src, rel_dst)
            if error:
                return _rechazo(tool, folder, rel_src, error)
            error, extra = await _apps(ha_client, folder, rel_src, modo="quitar",
                                       otras=(rel_dst,))
            if error:
                return _rechazo(tool, folder, rel_src, error)
            preview: dict[str, Any] = {
                "action": "move", "folder": folder, "src": rel_src, "dst": rel_dst,
                "type": info["tipo"],
            }
            if info["recuento"] is not None:
                preview["contents"] = _muestra_para(info["recuento"])
            preview.update(extra)
            preview.update(_folders.textos_de_vista_previa(folder))
            _ajustar_muestra(preview, response_max_bytes)
            respuesta = await create_confirmation_token(tool, args, preview=preview,
                                                        estado=estado)
            _log(tool, folder, rel_src, "preview")
            return respuesta

        ok, resultado = await _validar_token(tool, folder, rel_src, confirmation_token,
                                             args, estado)
        if not ok:
            return resultado
        # FR-017: todo otra vez, DESPUÉS del token y su estado.
        error = _reglas_mover(info, src_p, dst_p, rel_src, rel_dst)
        if error is None:
            error, _ = await _apps(ha_client, folder, rel_src, modo="quitar",
                                   otras=(rel_dst,))
        if error:
            return await _fallo(tool, folder, rel_src, confirmation_token, error)
        base = _folders.raiz(folder)

        def mover() -> None:
            # T048: las dos rutas, revalidadas en este hilo justo antes.
            _folders.revalidar(folder, rel_src, src_p, seguir=False)
            _folders.revalidar(folder, rel_dst, dst_p, seguir=False)
            # `rename` y no `shutil.move`: dentro de la misma carpeta es una
            # operación atómica y, si cruzara de sistema de ficheros (un NAS
            # bajo /share), falla en vez de copiar y borrar a medias.
            if not _folders.USAR_DIR_FD:
                os.rename(src_p, dst_p)
                return
            fd_src = _folders.abrir_padre(base, src_p.parent)
            try:
                fd_dst = _folders.abrir_padre(base, dst_p.parent)
                try:
                    os.rename(src_p.name, dst_p.name, src_dir_fd=fd_src,
                              dst_dir_fd=fd_dst)
                finally:
                    os.close(fd_dst)
            finally:
                os.close(fd_src)

        try:
            await asyncio.to_thread(mover)
        except _FALLOS as exc:
            return await _fallo(tool, folder, rel_src, confirmation_token,
                                _fallo_de_operacion(exc, rel_src))
        respuesta = {"result": "ok", "action": "move", "folder": folder,
                     "src": rel_src, "dst": rel_dst}
        await complete_confirmation_token(confirmation_token, success=True, result=respuesta)
        _log(tool, folder, rel_src, "ok")
        return respuesta

    # ── fs_delete_in_folder ───────────────────────────────────────────────────

    def _reglas_borrar(info: dict[str, Any], rel: str,
                       recursive: bool) -> dict[str, Any] | None:
        """Rechazos de borrar que se miran en la vista previa y otra vez al
        confirmar (FR-016, FR-017), con la inspección del objetivo."""
        if info["tipo"] is None:
            return {"error": "not_found", "path": rel}
        if info["montaje"]:
            return _mount_point(rel)
        if info["tipo"] == "dir" and not recursive and info["recuento"]["sample"]:
            return {
                "error": "directory_not_empty", "path": rel,
                "hint": ("The directory is not empty; call again with recursive=true "
                         "to delete it with everything inside."),
            }
        return None

    @mcp.tool()
    @_con_candado
    async def fs_delete_in_folder(
        folder: str,
        path: str,
        recursive: bool = False,
        confirmation_token: str | None = None,
    ) -> object:
        """Delete a file, a symlink or a directory under /addons or /share.
        ALWAYS two steps.

        `folder` is "addons" or "share"; `path` is relative to it. A
        non-empty directory needs recursive=true; the preview then says how
        many files, directories and symlinks it holds, their total size and
        up to 20 sample paths. A symlink is deleted as a link, never its
        target; the recursive delete follows no symlink. The token is bound
        to the current state of the target: any change inside it before
        confirming cancels it.

        Refused without a token: the folder root (root_protected), a mount
        point or a directory containing one (mount_point: a network share
        under /share), a tree too big to preview (too_large_to_preview) and,
        in "addons", the folder or config file of an installed local app
        (installed_app: uninstall it first with sv_uninstall_addon). No
        backup is made and it cannot be undone from Hermes; the preview gives
        the sv_create_backup_partial call to make one first.

        Returns:
            Preview: {"confirmation_token", "preview": {"action": "delete",
            "folder", "path", "type", "size_bytes" | "contents", "recursive",
            "backup": null, ...}}. Confirmed: {"result": "ok", "action",
            "folder", "path", "deleted": {"files", "dirs", "symlinks"}}; if
            it stopped halfway: {"error": "partial", "partial": true,
            "remaining"}. Errors: the ones above plus invalid_argument,
            folder_unavailable, traversal, not_found, directory_not_empty,
            installed_check_failed, installed_check_inconclusive,
            preview_outdated, path_changed, io_error.
        """
        tool = "fs_delete_in_folder"
        p = _sin_seguir(folder, path)
        if isinstance(p, dict):
            return _rechazo(tool, folder, p.get("path", path), p)
        rel = _folders.relativa(folder, p)
        recursive = recursive is True
        args = {"folder": folder, "path": rel, "recursive": recursive}

        try:
            info = await asyncio.to_thread(_folders.inspeccionar, p)
        except (_folders.ArbolDemasiadoGrande, OSError) as exc:
            return _rechazo(tool, folder, rel, _rechazo_de_inspeccion(exc))
        estado = {"target": info["huella"]}

        if not confirmation_token:
            error = _reglas_borrar(info, rel, recursive)
            if error:
                return _rechazo(tool, folder, rel, error)
            error, extra = await _apps(ha_client, folder, rel, modo="quitar")
            if error:
                return _rechazo(tool, folder, rel, error)
            preview: dict[str, Any] = {
                "action": "delete", "folder": folder, "path": rel,
                "type": info["tipo"], "recursive": recursive,
            }
            if info["recuento"] is not None:
                preview["contents"] = _muestra_para(info["recuento"])
            elif info["size"] is not None:
                preview["size_bytes"] = info["size"]
            preview.update(extra)
            preview.update(_folders.textos_de_vista_previa(folder))
            _ajustar_muestra(preview, response_max_bytes)
            respuesta = await create_confirmation_token(tool, args, preview=preview,
                                                        estado=estado)
            _log(tool, folder, rel, "preview")
            return respuesta

        ok, resultado = await _validar_token(tool, folder, rel, confirmation_token,
                                             args, estado)
        if not ok:
            return resultado
        # FR-017: todo otra vez, DESPUÉS del token y su estado.
        error = _reglas_borrar(info, rel, recursive)
        if error is None:
            error, _ = await _apps(ha_client, folder, rel, modo="quitar")
        if error:
            return await _fallo(tool, folder, rel, confirmation_token, error)

        base = _folders.raiz(folder)

        def en_su_sitio(operar_fd: Any, operar_ruta: Any) -> Any:
            # T048: revalidada en este hilo, justo antes de la llamada.
            _folders.revalidar(folder, rel, p, seguir=False)
            return _en_padre(base, p, operar_fd, operar_ruta)

        if info["tipo"] != "dir":
            borrado = {"files": 0 if info["tipo"] == "symlink" else 1, "dirs": 0,
                       "symlinks": 1 if info["tipo"] == "symlink" else 0}
            try:
                await asyncio.to_thread(
                    en_su_sitio, lambda nombre, fd: os.unlink(nombre, dir_fd=fd),
                    _quitar_enlace_o_fichero)
            except _FALLOS as exc:
                return await _fallo(tool, folder, rel, confirmation_token,
                                    _fallo_de_operacion(exc, rel))
        elif not recursive:
            # Vacía (lo dice la huella, que no ha cambiado): `rmdir`, que
            # además falla si algo apareció dentro en este instante.
            borrado = {"files": 0, "dirs": 1, "symlinks": 0}
            try:
                await asyncio.to_thread(
                    en_su_sitio, lambda nombre, fd: os.rmdir(nombre, dir_fd=fd), os.rmdir)
            except _FALLOS as exc:
                return await _fallo(tool, folder, rel, confirmation_token,
                                    _fallo_de_operacion(exc, rel))
        else:
            cuenta = info["recuento"]
            borrado = {"files": cuenta["files"], "dirs": cuenta["dirs"] + 1,
                       "symlinks": cuenta["symlinks"]}
            errores: list[str] = []

            def anotar(_funcion: Any, ruta: Any, exc: BaseException) -> None:
                # Se sigue con lo demás y al final se cuenta lo que quedó.
                errores.append(f"{os.fspath(ruta)}: {exc}")

            # `shutil.rmtree` no sigue symlinks (en Linux usa la variante con
            # descriptores, segura frente a un symlink que aparece a medias);
            # con `dir_fd`, tampoco uno que cambie una carpeta intermedia.
            try:
                await asyncio.to_thread(
                    en_su_sitio,
                    lambda nombre, fd: shutil.rmtree(nombre, dir_fd=fd, onexc=anotar),
                    lambda q: shutil.rmtree(q, onexc=anotar))
            except _FALLOS as exc:
                return await _fallo(tool, folder, rel, confirmation_token,
                                    _fallo_de_operacion(exc, rel))
            if os.path.lexists(p) or errores:
                try:
                    queda = await asyncio.to_thread(_folders.recuento, p)
                    restante = {"files": queda["files"], "dirs": queda["dirs"] + 1,
                                "symlinks": queda["symlinks"]}
                except (_folders.ArbolDemasiadoGrande, OSError):
                    restante = None
                respuesta = {
                    "error": "partial", "partial": True, "folder": folder, "path": rel,
                    "remaining": restante,
                    "detail": ("The delete stopped halfway; part of the directory is "
                               "still there. " + "; ".join(errores[:5])[:1000]),
                }
                await complete_confirmation_token(confirmation_token, success=False,
                                                  error="partial")
                _log(tool, folder, rel, "rejected:partial")
                return respuesta
        respuesta = {"result": "ok", "action": "delete", "folder": folder, "path": rel,
                     "deleted": borrado}
        await complete_confirmation_token(confirmation_token, success=True, result=respuesta)
        _log(tool, folder, rel, "ok")
        return respuesta
