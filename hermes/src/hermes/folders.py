"""Hermes — carpetas /addons y /share (spec 034, 1.2.1). Sin tools.

POR QUÉ UN MÓDULO APARTE Y NO AMPLIAR `fs_*`
--------------------------------------------
Las once `fs_*` de `/config` no cambian (decisión D-4): ni nombre, ni esquema,
ni comportamiento. Las carpetas nuevas tienen su propia familia de tools
(`addons_share`, módulos `tools/folders.py` y `tools/folders_write.py`) y este
módulo común reúne lo que comparten:

- las raíces (`ADDONS_BASE`, `SHARE_BASE`), cambiables por entorno y en los
  tests, como `fs.CONFIG_BASE`, y `raiz(folder)` con sus dos rechazos;
- la validación de rutas, que es la MISMA de `/config`
  (`fs.normalize_in_root`) con la raíz de la carpeta, más el rechazo
  explícito del byte nulo (en Windows `resolve()` no lo rechaza; así los tests
  no dependen del sistema operativo) y una variante que no sigue el último
  symlink, para borrar o mover el enlace y nunca su destino;
- huellas (el estado que se ata al token), recuentos y topes de los
  recorridos, que no siguen symlinks ni entran en puntos de montaje
  (`/share/<nombre>` puede ser un NAS montado por el Supervisor);
- el índice de apps locales de `/addons`, calculado como lo calcula el
  Supervisor (`store/data.py`).

Mensajes y códigos de error en inglés (los ve el cliente); comentarios en
español.
"""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import os
import stat as _stat
import shutil
import time
import weakref as _weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import yaml

from hermes import fs as _fs
from hermes.fs import PathTraversalError

# ── Raíces ────────────────────────────────────────────────────────────────────
# Resueltas al importar y mutables para los tests (como `fs.CONFIG_BASE`). En
# HAOS el Supervisor monta `addons` en /addons (tipo heredado, ver
# `hermes/config.yaml`) y `share` en /share. Las variables de entorno sirven
# para desarrollo y para el día en que /addons pase a /local_apps.
ADDONS_BASE: Path = Path(os.environ.get("HERMES_ADDONS_BASE", "/addons")).resolve()
SHARE_BASE: Path = Path(os.environ.get("HERMES_SHARE_BASE", "/share")).resolve()

#: Valores admitidos del argumento `folder`. Ninguna otra carpeta (D-1).
CARPETAS: tuple[str, ...] = ("addons", "share")

# ── Topes (mutables para los tests) ───────────────────────────────────────────
#: Hasta este tamaño la huella de un fichero es su SHA-256; por encima,
#: tamaño, fecha en ns e inodo (leer 64 MiB en un hilo es asumible en HAOS;
#: un fichero de varios GB, no).
UMBRAL_SHA256_BYTES = 64 * 1024 * 1024
#: Un recorrido de más entradas que esto no se previsualiza (`/share` puede
#: tener millones de ficheros).
MAX_ENTRADAS = 50_000
#: Ni uno que tarde más que esto (un NAS lento o un árbol enorme).
MAX_SEGUNDOS = 10.0
#: Rutas de muestra en la vista previa de una carpeta.
TAM_MUESTRA = 20
#: Un `config.*` mayor que esto no se lee: cuenta como ilegible.
TAM_MAX_CONFIG = 1024 * 1024
#: Sufijos que el Supervisor lee como manifiesto (`FILE_SUFFIX_CONFIGURATION`).
SUFIJOS_CONFIG: tuple[str, ...] = (".yaml", ".yml", ".json")

_TROZO = 1024 * 1024


# ── Errores ───────────────────────────────────────────────────────────────────

class CarpetaError(Exception):
    """Rechazo con un código para el cliente y un `detail` en inglés."""

    codigo = "invalid_argument"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def respuesta(self, **extra: Any) -> dict[str, Any]:
        return {"error": self.codigo, "detail": self.detail, **extra}


class CarpetaInvalida(CarpetaError):
    """`folder` no es `addons` ni `share`."""

    codigo = "invalid_argument"


class CarpetaNoDisponible(CarpetaError):
    """La raíz no existe o no es un directorio (instalación sin el montaje)."""

    codigo = "folder_unavailable"


class ArbolDemasiadoGrande(CarpetaError):
    """El recorrido pasó del tope de entradas o de tiempo."""

    codigo = "too_large_to_preview"


# ── Raíz y rutas ──────────────────────────────────────────────────────────────

def raiz(folder: object) -> Path:
    """Raíz de la carpeta `folder` (`addons` o `share`).

    Primero valida el nombre, sin tocar el disco; después, que la raíz exista
    y sea un directorio. Las raíces se leen en cada llamada (los tests las
    parchean).

    Raises:
        CarpetaInvalida: `folder` no es exactamente `addons` ni `share`.
        CarpetaNoDisponible: la raíz no está montada.
    """
    if not isinstance(folder, str) or folder not in CARPETAS:
        raise CarpetaInvalida(
            f"folder must be one of {', '.join(repr(c) for c in CARPETAS)}; "
            f"got {folder!r}"
        )
    base = ADDONS_BASE if folder == "addons" else SHARE_BASE
    if not base.is_dir():
        raise CarpetaNoDisponible(
            f"The folder /{folder} is not available in this installation (it is "
            "not mounted)."
        )
    return base


def _alias(folder: str) -> str:
    # Concatenación y no f-string con «/» delante: el inventario de
    # `test_security_regressions` busca así las rutas de API sin validar, y
    # esto no es una ruta de API sino el alias de la carpeta.
    return "/" + folder


def _sin_byte_nulo(path: object) -> None:
    # Antes de `resolve()`: en Linux lo rechaza él (ValueError), en Windows
    # no. También codificado (`%00`), porque la preparación decodifica.
    if isinstance(path, str) and ("\x00" in path or "\x00" in unquote(path)):
        raise PathTraversalError("Invalid path: embedded null byte")


def normalizar(folder: str, path: str) -> Path:
    """Ruta absoluta y resuelta (sigue symlinks) de `path` dentro de `folder`.

    La MISMA validación que `/config` (`fs.normalize_in_root`) con la raíz de
    la carpeta y su alias (`/addons/…`, `/share/…`); cualquier otra absoluta,
    `..` que sale, un symlink que apunta fuera o un byte nulo →
    `PathTraversalError`.

    Raises:
        CarpetaInvalida, CarpetaNoDisponible, PathTraversalError.
    """
    base = raiz(folder)
    _sin_byte_nulo(path)
    return _fs.normalize_in_root(path, base, _alias(folder))


def normalizar_sin_seguir(folder: str, path: str) -> Path:
    """Como `normalizar`, pero SIN resolver el último nombre (FR-006).

    Para borrar y mover: si `path` es un symlink, se actúa sobre el enlace, no
    sobre su destino (que puede estar fuera de la carpeta). Se valida y
    resuelve la carpeta padre; el último nombre se conserva literal y no puede
    ser `.`, `..` ni vacío. La raíz misma nunca sale de aquí (su último nombre
    sería vacío): quien necesite reconocerla usa `normalizar` y `es_raiz`.

    Raises:
        CarpetaInvalida, CarpetaNoDisponible, PathTraversalError.
    """
    base = raiz(folder)
    _sin_byte_nulo(path)
    alias = _alias(folder)
    relativa = _fs.prepare_in_root(path, base, alias)
    if relativa is None:
        raise PathTraversalError(
            "The last path component cannot be '.', '..' or empty (the folder "
            "root itself)"
        )
    relativa = relativa.rstrip("/")
    padre, _, ultimo = relativa.rpartition("/")
    if ultimo in ("", ".", ".."):
        raise PathTraversalError(
            f"The last path component cannot be '.', '..' or empty: {path!r}"
        )
    if len(ultimo.encode("utf-8", "surrogatepass")) > _fs._NAME_MAX_BYTES:
        raise PathTraversalError(
            f"Path component is too long (max {_fs._NAME_MAX_BYTES} bytes): "
            f"{ultimo[:80]!r}…"
        )
    carpeta_padre = base if not padre else _fs.resolve_in_root(padre, base, alias)
    resultado = carpeta_padre / ultimo
    if len(str(resultado).encode("utf-8", "surrogatepass")) > _fs._PATH_MAX_BYTES:
        raise PathTraversalError(
            f"Path is too long (max {_fs._PATH_MAX_BYTES} bytes): {relativa[:80]!r}…"
        )
    return resultado


def es_raiz(folder: str, p: Path) -> bool:
    """True si `p` es la raíz de `folder` (que nunca se borra ni se mueve)."""
    return Path(p) == raiz(folder)


def relativa(folder: str, p: Path) -> str:
    """Ruta de `p` relativa a la raíz de `folder`, en POSIX (`.` la raíz)."""
    rel = Path(p).relative_to(raiz(folder)).as_posix()
    return rel or "."


# ── Puntos de montaje ─────────────────────────────────────────────────────────

def es_punto_de_montaje(path: Path) -> bool:
    """Predicado sustituible en los tests (que no pueden montar nada).

    El Supervisor monta los recursos de red de uso `share` en
    `/share/<nombre>` (`mounts/mount.py`): un `rmtree` sobre ellos borraría el
    NAS. Los recorridos lo usan siempre a través del módulo
    (`folders.es_punto_de_montaje`), para que el parche llegue.
    """
    try:
        return os.path.ismount(path)
    except (OSError, ValueError):
        return False


def _es_montaje(path: Path, st: os.stat_result, dev_ref: int | None) -> bool:
    # Además del predicado, un directorio en otro dispositivo que su padre de
    # referencia es un montaje aunque `ismount` no lo vea (bind mounts).
    if es_punto_de_montaje(path):
        return True
    return dev_ref is not None and st.st_dev != dev_ref


# ── Recorrido, huellas y recuentos ────────────────────────────────────────────

#: Una entrada de la lista canónica: (ruta relativa POSIX, tipo, tamaño,
#: mtime_ns). Tipos: `file`, `dir`, `symlink`, `mount` (no se entra) y
#: `other`. El tamaño solo vale para ficheros y symlinks: el de una carpeta
#: depende del sistema de ficheros; y una carpeta tampoco lleva fecha (ver
#: `recorrer`).
Entrada = tuple[str, str, "int | None", "int | None"]


def _comprobar_tiempo(inicio: float) -> None:
    if time.monotonic() - inicio >= MAX_SEGUNDOS:
        raise ArbolDemasiadoGrande(
            f"Walking the tree took more than {MAX_SEGUNDOS:g} s; work on "
            "smaller subfolders."
        )


def recorrer(carpeta: Path) -> list[Entrada]:
    """Lista canónica (ordenada) de todo lo que hay bajo `carpeta`.

    Con `os.scandir`, sin seguir symlinks y sin entrar en puntos de montaje
    (salen como `mount`). Topes: `MAX_ENTRADAS` y `MAX_SEGUNDOS`.

    Raises:
        ArbolDemasiadoGrande: si pasa de un tope.
        OSError: si no se puede leer.
    """
    inicio = time.monotonic()
    dev_ref = os.lstat(carpeta).st_dev
    entradas: list[Entrada] = []
    pendientes: list[tuple[str, str]] = [(os.fspath(carpeta), "")]
    while pendientes:
        actual, prefijo = pendientes.pop()
        _comprobar_tiempo(inicio)
        with os.scandir(actual) as it:
            for e in it:
                rel = prefijo + e.name
                st = e.stat(follow_symlinks=False)
                modo = st.st_mode
                if _stat.S_ISLNK(modo):
                    entradas.append((rel, "symlink", st.st_size, st.st_mtime_ns))
                elif _stat.S_ISDIR(modo):
                    # `os.lstat` y no el `st` del `DirEntry`: en Windows este
                    # trae `st_dev` a 0 y toda carpeta parecería un montaje.
                    if _es_montaje(Path(e.path), os.lstat(e.path), dev_ref):
                        entradas.append((rel, "mount", None, None))
                    else:
                        # Sin fecha: la de una carpeta solo cambia cuando
                        # cambian sus entradas, que ya están en la lista, y
                        # en Windows se vio cambiar sin motivo entre dos
                        # recorridos seguidos (un token que nunca casaría).
                        entradas.append((rel, "dir", None, None))
                        pendientes.append((e.path, rel + "/"))
                elif _stat.S_ISREG(modo):
                    entradas.append((rel, "file", st.st_size, st.st_mtime_ns))
                else:
                    entradas.append((rel, "other", None, st.st_mtime_ns))
                if len(entradas) > MAX_ENTRADAS:
                    raise ArbolDemasiadoGrande(
                        f"More than {MAX_ENTRADAS} entries; work on smaller "
                        "subfolders."
                    )
                _comprobar_tiempo(inicio)
    entradas.sort(key=lambda x: x[0])
    return entradas


def _sha256_de_fichero(p: Path) -> str:
    h = hashlib.sha256()
    with _fs._open_file_nofollow(p) as f:
        while trozo := f.read(_TROZO):
            h.update(trozo)
    return h.hexdigest()


def huella(p: Path) -> dict[str, Any]:
    """Resumen del estado de `p` para atarlo al token (FR-012).

    - fichero ≤ `UMBRAL_SHA256_BYTES`: SHA-256 del contenido;
    - fichero mayor: tamaño, `st_mtime_ns` e inodo (cambiar el contenido sin
      cambiar ninguno de los tres exige manipular la fecha a propósito, y el
      token dura 60 s);
    - symlink: su destino literal (no se sigue);
    - ausente: `absent`;
    - carpeta: SHA-256 de su lista canónica (`recorrer`) y cuántas entradas.

    Raises:
        ArbolDemasiadoGrande: carpeta por encima de un tope.
        OSError: si no se puede leer.
    """
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return {"kind": "absent"}
    modo = st.st_mode
    if _stat.S_ISLNK(modo):
        return {"kind": "symlink", "target": os.readlink(p)}
    if _stat.S_ISDIR(modo):
        return _huella_de_lista(recorrer(p))
    if _stat.S_ISREG(modo) and st.st_size <= UMBRAL_SHA256_BYTES:
        return {"kind": "file", "sha256": _sha256_de_fichero(p)}
    return {
        "kind": "file" if _stat.S_ISREG(modo) else "other",
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "ino": st.st_ino,
    }


def recuento(carpeta: Path) -> dict[str, Any]:
    """Recuento de una carpeta para la vista previa de borrar y mover.

    `total_bytes` suma los ficheros regulares (no sigue symlinks); la muestra
    son las `TAM_MUESTRA` primeras rutas en el orden de la lista canónica.

    Raises:
        ArbolDemasiadoGrande, OSError.
    """
    return _recuento_de_lista(recorrer(carpeta))


def _huella_de_lista(lista: list[Entrada]) -> dict[str, Any]:
    canonica = json.dumps(lista, ensure_ascii=False, separators=(",", ":"))
    return {
        "kind": "dir",
        "sha256": hashlib.sha256(canonica.encode("utf-8", "surrogatepass")).hexdigest(),
        "entries": len(lista),
    }


def _recuento_de_lista(lista: list[Entrada]) -> dict[str, Any]:
    ficheros = sum(1 for e in lista if e[1] in ("file", "other"))
    return {
        "files": ficheros,
        "dirs": sum(1 for e in lista if e[1] in ("dir", "mount")),
        "symlinks": sum(1 for e in lista if e[1] == "symlink"),
        "total_bytes": sum(e[2] or 0 for e in lista if e[1] == "file"),
        "sample": [e[0] for e in lista[:TAM_MUESTRA]],
        "sample_truncated": len(lista) > TAM_MUESTRA,
    }


def contiene_punto_de_montaje(p: Path) -> bool:
    """True si `p` es un punto de montaje o hay alguno debajo (sin seguir
    symlinks). Borrar o mover algo así se rechaza (FR-016).

    Raises:
        ArbolDemasiadoGrande, OSError.
    """
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return False
    if not _stat.S_ISDIR(st.st_mode):
        return False
    dev_padre = None
    try:
        dev_padre = os.lstat(Path(p).parent).st_dev
    except OSError:
        pass
    if _es_montaje(Path(p), st, dev_padre):
        return True
    return any(e[1] == "mount" for e in recorrer(p))


def inspeccionar(p: Path) -> dict[str, Any]:
    """Todo lo que la vista previa de borrar o mover necesita de `p`, con UN
    solo recorrido (en `/share` un árbol puede ser enorme y la vista previa
    y la confirmación lo miran dos veces cada una).

    Devuelve `{"tipo", "huella", "montaje", "recuento", "size"}`: `tipo` como
    en el listado (`file`, `dir`, `symlink`, `other`) o `None` si no existe;
    `montaje` dice si `p` es un punto de montaje o contiene alguno (sin
    entrar en él); `recuento` solo para una carpeta; `size` solo para un
    fichero.

    Raises:
        ArbolDemasiadoGrande, OSError.
    """
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return {"tipo": None, "huella": {"kind": "absent"}, "montaje": False,
                "recuento": None, "size": None}
    modo = st.st_mode
    if not _stat.S_ISDIR(modo):
        tipo = ("symlink" if _stat.S_ISLNK(modo)
                else "file" if _stat.S_ISREG(modo) else "other")
        return {"tipo": tipo, "huella": huella(p), "montaje": False,
                "recuento": None, "size": st.st_size if tipo == "file" else None}
    dev_padre = None
    try:
        dev_padre = os.lstat(Path(p).parent).st_dev
    except OSError:
        pass
    if _es_montaje(Path(p), st, dev_padre):
        # No se entra: recorrerlo sería recorrer el NAS. La huella basta con
        # decir que es un montaje (la vista previa se rechaza de todos modos).
        return {"tipo": "dir", "huella": {"kind": "mount"}, "montaje": True,
                "recuento": None, "size": None}
    lista = recorrer(p)
    return {
        "tipo": "dir",
        "huella": _huella_de_lista(lista),
        "montaje": any(e[1] == "mount" for e in lista),
        "recuento": _recuento_de_lista(lista),
        "size": None,
    }


# ── Candado y operación final (convergencia T048 y T049) ──────────────────────
#
# La vista previa y la confirmación resuelven la ruta al principio; la
# operación llega después de varios `await` (el token, la petición al
# Supervisor, el recorrido de /addons). En ese hueco otra confirmación de
# Hermes podía cambiar una carpeta intermedia por un symlink que apunta fuera
# (mover un symlink se admite) y `rmtree`, `mkdir` o la escritura lo habrían
# seguido. Dos defensas:
#
# 1. Un candado por carpeta, compartido por TODAS las confirmaciones que
#    modifican esa carpeta (y por la de instalar o reconstruir una app local,
#    T047): ninguna escritura de Hermes se cuela en medio de otra.
# 2. Dentro del mismo hilo, sin ningún `await` entre medias, la ruta se
#    vuelve a resolver y validar justo antes de la llamada al sistema
#    (`revalidar`) y, donde el sistema lo da (Linux), se opera relativo al
#    descriptor de la carpeta padre abierta componente a componente con
#    `O_NOFOLLOW` (`abrir_padre`): ni siquiera un cambio externo en ese
#    instante haría seguir un symlink intermedio. En Windows no hay
#    `dir_fd`: queda la revalidación (camino probado por los tests).

_CANDADOS: "_weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]]" = (
    _weakref.WeakKeyDictionary())


def candado(folder: object) -> asyncio.Lock:
    """El candado de `folder` en el bucle actual (uno por bucle: un
    `asyncio.Lock` no se puede compartir entre bucles, y los tests crean uno
    por test). Una carpeta no válida recibe uno propio, que no comparte
    nada (la llamada se rechazará de todos modos)."""
    if not isinstance(folder, str) or folder not in CARPETAS:
        return asyncio.Lock()
    por_bucle = _CANDADOS.setdefault(asyncio.get_running_loop(), {})
    return por_bucle.setdefault(folder, asyncio.Lock())


class RutaCambiada(PathTraversalError):
    """La ruta ya no resuelve a lo que se validó (T048)."""

    codigo = "path_changed"

    def respuesta(self) -> dict[str, Any]:
        return {
            "error": self.codigo,
            "detail": ("The path changed while confirming (a folder on the way was "
                       "moved or replaced, for example by a symlink). Nothing was "
                       "done; request a new preview."),
        }


class NoRegular(OSError):
    """El objetivo existe y no es un fichero regular (T049)."""

    codigo = "not_regular_file"

    def respuesta(self, rel: str) -> dict[str, Any]:
        return {"error": self.codigo, "path": rel,
                "detail": ("Not a regular file (a FIFO, socket or device): it is not "
                           "read nor written, so nothing can block waiting on it.")}


def revalidar(folder: str, rel: str, p: Path, *, seguir: bool) -> None:
    """Vuelve a resolver `rel` y comprueba que da `p` y que su carpeta padre
    sigue siendo un camino sin symlinks dentro de la raíz. Síncrono: se
    llama en el mismo hilo que la operación, justo antes.

    Raises:
        RutaCambiada: si no.
    """
    try:
        nueva = normalizar(folder, rel) if seguir else normalizar_sin_seguir(folder, rel)
    except (PathTraversalError, CarpetaError) as exc:
        raise RutaCambiada(str(exc)) from exc
    if nueva != p or os.path.realpath(p.parent) != os.fspath(p.parent):
        raise RutaCambiada(f"{rel!r} no longer resolves to the validated path")


_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)

#: True donde se puede operar relativo a un descriptor de carpeta sin seguir
#: symlinks (Linux). Mutable para los tests (que prueban los dos caminos).
USAR_DIR_FD: bool = bool(
    _O_DIRECTORY and _O_NOFOLLOW
    and {os.open, os.mkdir, os.rename, os.unlink, os.rmdir} <= os.supports_dir_fd
    and getattr(shutil.rmtree, "avoids_symlink_attacks", False)
)


def abrir_padre(base: Path, padre: Path, *, crear: bool = False) -> int:
    """Descriptor de `padre` abierto desde `base` componente a componente con
    `O_NOFOLLOW|O_DIRECTORY` (un symlink en el camino da error, no se sigue).
    Con `crear`, crea las carpetas que falten (como `mkdir -p`). Solo con
    `USAR_DIR_FD`. Quien llama cierra el descriptor.

    Raises:
        RutaCambiada: un componente es un symlink o no es una carpeta.
    """
    flags = os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW
    fd = os.open(base, flags)
    try:
        for parte in padre.relative_to(base).parts:
            if crear:
                try:
                    os.mkdir(parte, dir_fd=fd)
                except FileExistsError:
                    pass
            try:
                nuevo = os.open(parte, flags, dir_fd=fd)
            except (NotADirectoryError, OSError) as exc:
                if isinstance(exc, FileNotFoundError):
                    raise
                raise RutaCambiada(f"{parte!r} is not a plain directory") from exc
            os.close(fd)
            fd = nuevo
    except BaseException:
        os.close(fd)
        raise
    return fd


def exigir_regular_o_ausente(p: Path) -> None:
    """T049: lo que se va a sobrescribir es un fichero regular (o no existe).

    Raises:
        NoRegular: si existe y es otra cosa (FIFO, socket, dispositivo…).
    """
    try:
        modo = os.lstat(p).st_mode
    except (FileNotFoundError, NotADirectoryError):
        # No existe (o un padre es un fichero: lo rechaza `_faltan_padres`
        # con `not_a_directory`).
        return
    if not _stat.S_ISREG(modo):
        raise NoRegular(f"{p.name!r} is not a regular file")


# ── Índice de apps locales (/addons) ──────────────────────────────────────────

@dataclass(frozen=True)
class IndiceDeApps:
    """Qué carpetas de `/addons` son apps locales para el Supervisor.

    `configs`: cada `config.*` candidato (ruta relativa POSIX) con su slug
    `local_<slug>`, o `None` si no se puede leer o no tiene `slug` (el
    Supervisor tampoco lo carga).
    """

    configs: dict[str, str | None] = field(default_factory=dict)

    @property
    def apps(self) -> dict[str, dict[str, str]]:
        """`local_<slug>` → `{"dir", "config"}` (el primero por orden de
        ruta si dos ficheros declaran el mismo slug)."""
        out: dict[str, dict[str, str]] = {}
        for config, slug in sorted(self.configs.items()):
            if slug is not None and slug not in out:
                carpeta = config.rpartition("/")[0] or "."
                out[slug] = {"dir": carpeta, "config": config}
        return out

    @property
    def ilegibles(self) -> list[str]:
        return sorted(c for c, s in self.configs.items() if s is None)

    def app_de_carpeta(self, rel_dir: str) -> str | None:
        """Slug de la app cuya carpeta es `rel_dir`, o `None`."""
        for slug, datos in self.apps.items():
            if datos["dir"] == rel_dir:
                return slug
        return None


def _slug_local(p: Path) -> str | None:
    """`local_<slug>` de un `config.*`, o `None` si el Supervisor no lo
    cargaría como app (ilegible, mayor que el tope, sin `slug` de texto)."""
    try:
        st = os.lstat(p)
    except OSError:
        return None
    # Un symlink no se sigue: podría apuntar fuera de /addons.
    if not _stat.S_ISREG(st.st_mode) or st.st_size > TAM_MAX_CONFIG:
        return None
    try:
        texto = _fs.read_bytes(p, TAM_MAX_CONFIG + 1).decode("utf-8")
    except Exception:  # noqa: BLE001 — cualquier fallo es «ilegible»
        return None
    return slug_de_texto(texto, p.suffix)


def slug_de_texto(texto: str, sufijo: str) -> str | None:
    """`local_<slug>` que declara el texto de un `config.*`, o `None`.

    Aparte de `_slug_local` para poder mirar también el contenido NUEVO que
    se quiere escribir (FR-019: reescribir el `config.*` de una app
    instalada con otro `slug` la desligaría de su carpeta).
    """
    if len(texto.encode("utf-8", "surrogatepass")) > TAM_MAX_CONFIG:
        return None
    try:
        # Como `read_json_or_yaml_file` del Supervisor: JSON por sufijo.
        datos = json.loads(texto) if sufijo == ".json" else yaml.safe_load(texto)
    except Exception:  # noqa: BLE001 — cualquier fallo es «ilegible»
        return None
    slug = datos.get("slug") if isinstance(datos, dict) else None
    if not isinstance(slug, str) or not slug.strip():
        return None
    return f"local_{slug}"


def indice_de_apps_locales(base: Path | None = None) -> IndiceDeApps:
    """Índice de apps locales bajo la raíz de `addons` (research R-4).

    Las mismas reglas que `StoreData._find_app_configs` del Supervisor
    2026.11: todo `config.*` con sufijo `.yaml`, `.yml` o `.json`, a cualquier
    profundidad, salvo las rutas con alguna parte que empieza por `.` o que se
    llama `rootfs`. Sin seguir symlinks de carpeta (`**` no los sigue).
    Síncrono: quien lo llama desde una tool lo manda a un hilo.

    Raises:
        CarpetaInvalida, CarpetaNoDisponible (si `base` es None).
    """
    raiz_addons = raiz("addons") if base is None else base
    configs: dict[str, str | None] = {}
    for dirpath, dirnames, filenames in os.walk(raiz_addons, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and d != "rootfs"
        )
        rel_dir = Path(dirpath).relative_to(raiz_addons).as_posix()
        for nombre in sorted(filenames):
            if not fnmatch.fnmatchcase(nombre, "config.*"):
                continue
            if Path(nombre).suffix not in SUFIJOS_CONFIG:
                continue
            rel = nombre if rel_dir == "." else rel_dir + "/" + nombre
            configs[rel] = _slug_local(Path(dirpath) / nombre)
    return IndiceDeApps(configs)


def es_config_candidato(rel: str) -> bool:
    """True si el Supervisor leería `rel` (relativa a `/addons`) como el
    manifiesto de una app: `config.yaml|yml|json`, sin ninguna parte que
    empiece por `.` ni que se llame `rootfs` (las reglas de
    `indice_de_apps_locales`)."""
    partes = rel.split("/")
    if any(p.startswith(".") or p == "rootfs" for p in partes):
        return False
    nombre = partes[-1]
    return fnmatch.fnmatchcase(nombre, "config.*") and Path(nombre).suffix in SUFIJOS_CONFIG


# ── Apps instaladas (FR-019) ──────────────────────────────────────────────────

async def apps_instaladas(ha_client: Any) -> set[str] | None:
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


def _dentro(rel: str, carpeta: str) -> bool:
    """True si `rel` es `carpeta` o está debajo (rutas relativas POSIX)."""
    return carpeta == "." or rel == carpeta or rel.startswith(carpeta + "/")


def _app_que_contiene(indice: IndiceDeApps, rel: str, instaladas: set[str]) -> str | None:
    """Slug de la app INSTALADA en cuya carpeta está `rel` (la más honda)."""
    mejor: tuple[int, str] | None = None
    for config, slug in indice.configs.items():
        if slug is None or slug not in instaladas:
            continue
        carpeta = config.rpartition("/")[0] or "."
        if _dentro(rel, carpeta):
            hondura = 0 if carpeta == "." else carpeta.count("/") + 1
            if mejor is None or hondura > mejor[0]:
                mejor = (hondura, slug)
    return None if mejor is None else mejor[1]


def _rechazo_app(codigo: str, rel: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"error": codigo, "path": rel, "detail": detail, **extra}


def _instalada(slug: str, rel: str, detail: str) -> dict[str, Any]:
    return _rechazo_app(
        "installed_app", rel, detail, slug=slug,
        hint="Uninstall the app first with sv_uninstall_addon(slug='" + slug + "').",
    )


_SIN_SUPERVISOR = (
    "The Supervisor did not answer, so it is not possible to tell whether a "
    "local app here is installed. Nothing was done; try again later."
)


def evaluar_apps(
    indice: IndiceDeApps,
    instaladas: set[str] | None,
    rel: str,
    *,
    modo: str,
    contenido: str | None = None,
    otras: tuple[str, ...] = (),
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Reglas de FR-019 sobre una ruta de `/addons`, sin E/S (la hace
    `comprobar_apps_instaladas`).

    `modo`:
    - `quitar` (borrar, o el origen de mover): se rechaza si `rel` es o
      contiene el `config.*` de una app instalada (`installed_app`), si
      contiene algún `config.*` y el Supervisor no respondió
      (`installed_check_failed`), o si contiene un `config.*` ilegible y hay
      apps `local_*` instaladas sin carpeta en el índice
      (`installed_check_inconclusive`: podría ser el suyo);
    - `escribir`: si `rel` es un `config.*` candidato, sin Supervisor se
      rechaza, y si es el de una app instalada, el `slug` nuevo tiene que ser
      el mismo (si no, la app quedaría desligada de su carpeta);
    - `crear`: nunca se rechaza.

    `otras`: rutas que solo llevan el aviso (el destino de mover).

    Devuelve `(rechazo, extra)`: el rechazo listo para el cliente, o `None` y
    lo que se añade a la vista previa (`inside_installed_app`,
    `installed_check: "failed"`).
    """
    extra: dict[str, Any] = {}
    if modo == "quitar":
        dentro = sorted(c for c in indice.configs if _dentro(c, rel))
        if dentro and instaladas is None:
            return _rechazo_app("installed_check_failed", rel, _SIN_SUPERVISOR), extra
        for config in dentro:
            slug = indice.configs[config]
            if slug is not None and instaladas is not None and slug in instaladas:
                return _instalada(
                    slug, rel,
                    f"{rel!r} is or contains the folder of the installed local app "
                    f"{slug!r} ({config}). Removing it would leave the app without "
                    "its code.",
                ), extra
        huerfanas = sorted(
            s for s in (instaladas or set())
            if s.startswith("local_") and s not in indice.apps
        )
        ilegibles = [c for c in dentro if indice.configs[c] is None]
        if ilegibles and huerfanas:
            return _rechazo_app(
                "installed_check_inconclusive", rel,
                "There are installed local apps whose config file is not found "
                "under /addons, and this path contains a config file that "
                "cannot be read: it could be theirs. Nothing was done.",
                installed_without_folder=huerfanas, unreadable=ilegibles[:20],
            ), extra
    elif modo == "escribir" and es_config_candidato(rel):
        if instaladas is None:
            return _rechazo_app("installed_check_failed", rel, _SIN_SUPERVISOR), extra
        actual = indice.configs.get(rel)
        if actual is not None and actual in instaladas:
            nuevo = slug_de_texto(contenido or "", Path(rel).suffix)
            if nuevo != actual:
                declarado = "no readable slug" if nuevo is None else repr(nuevo)
                return _instalada(
                    actual, rel,
                    f"{rel!r} is the config file of the installed local app "
                    f"{actual!r}; the new content declares {declarado}, which "
                    "would detach the app from its folder. Keep the same slug.",
                ), extra
    if instaladas is None:
        extra["installed_check"] = "failed"
        extra["installed_check_detail"] = (
            "The Supervisor did not answer: it is not known whether this path "
            "belongs to an installed local app."
        )
        return None, extra
    avisos: list[dict[str, str]] = []
    for r in (rel, *otras):
        slug = _app_que_contiene(indice, r, instaladas)
        if slug is not None and all(a["slug"] != slug for a in avisos):
            avisos.append({
                "slug": slug,
                "note": (
                    "This path belongs to an installed local app; the change "
                    "applies when it is rebuilt with sv_rebuild_addon(slug='"
                    + slug + "')."
                ),
            })
    if avisos:
        extra["inside_installed_app"] = avisos[0] if len(avisos) == 1 else avisos
    return None, extra


async def comprobar_apps_instaladas(
    ha_client: Any,
    rel: str,
    *,
    modo: str,
    contenido: str | None = None,
    otras: tuple[str, ...] = (),
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """`evaluar_apps` con el índice de `/addons` (en un hilo) y las apps
    instaladas del Supervisor. Solo para `addons`; se repite ENTERA al
    confirmar (FR-017), así que una app instalada entre la vista previa y la
    confirmación cancela la acción.

    Raises:
        CarpetaInvalida, CarpetaNoDisponible.
    """
    indice = await asyncio.to_thread(indice_de_apps_locales)
    instaladas = await apps_instaladas(ha_client)
    return evaluar_apps(indice, instaladas, rel, modo=modo, contenido=contenido, otras=otras)


# ── Textos comunes de las vistas previas (FR-018, FR-020) ─────────────────────

#: Aviso de toda vista previa que modifica `/addons` (FR-018).
AVISO_ADDONS = (
    "/addons holds the code of local apps: the Supervisor builds and runs "
    "what is here."
)
#: Nombre de cada carpeta en un backup parcial (`api/backups.py`, v1).
NOMBRE_EN_BACKUP: dict[str, str] = {"addons": "addons/local", "share": "share"}
ESTADO_ATADO = (
    "The token is bound to the current state; any change before confirming "
    "cancels it."
)


def textos_de_vista_previa(folder: str, *, reversible: bool = False) -> dict[str, Any]:
    """Campos comunes de las vistas previas que modifican (FR-018, FR-020).

    No se hace backup (research R-6): la vista previa lo dice
    (`backup: null`) y da la llamada exacta para hacerlo antes.
    """
    llamada = (
        "sv_create_backup_partial(folders='[\""
        + NOMBRE_EN_BACKUP[folder] + "\"]')"
    )
    textos: dict[str, Any] = {}
    if folder == "addons":
        textos["warning"] = AVISO_ADDONS
    textos["backup"] = None
    textos["reversible"] = reversible
    if reversible:
        textos["backup_hint"] = (
            "No backup is made; the new folder can be removed with "
            "fs_delete_in_folder. To keep a copy first: " + llamada + "."
        )
    else:
        textos["backup_hint"] = (
            "No backup is made and this cannot be undone from Hermes. To keep "
            "a copy first: " + llamada + "."
        )
    textos["state_bound"] = ESTADO_ATADO
    return textos
