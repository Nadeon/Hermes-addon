"""Tools que modifican /addons y /share (spec 034, tramo 2: T018–T024).

`fs_write_file_in_folder`, `fs_create_dir_in_folder`, `fs_move_in_folder` y
`fs_delete_in_folder`, en las dos carpetas, con ficheros REALES en raíces
temporales (`folders.ADDONS_BASE` y `folders.SHARE_BASE` parcheadas) y un
Supervisor simulado con la forma de 2026.11.0 (`GET /addons` →
`{"addons": [{"slug": …}]}`, research R-4). Datos ficticios: `ejemplo`,
`local_ejemplo`, `local_perdida`, `centinela-clave-1`.

Independencia del sistema operativo: los symlinks se crean con un ayudante
que hace `skip` si el sistema operativo no lo permite (corren en el CI de
Linux); los puntos de montaje, con el predicado sustituible
`folders.es_punto_de_montaje`; las fechas, con `os.utime(ns=…)`; los
ficheros se escriben en binario para que Windows no cambie los saltos de
línea.

Controles negativos comprobados (T027; recuentos en el commit del tramo):
(a) sin `estado` en el token de borrar → caen los de cambio entre vista
previa y confirmación de borrar; (b) sin repetir la comprobación de apps al
confirmar → cae `test_se_instala_entre_medias`; (c) token con el Supervisor
caído y un `config.*` → caen los de `installed_check_failed`; (d) borrar con
`normalizar` (que sigue el symlink) → cae el del symlink hacia fuera (en
Linux); (e) sin comprobar puntos de montaje → caen `TestPuntosDeMontaje`;
(f) admitiendo la raíz → caen los de `root_protected`; (g) sin el aviso de
`/addons` → cae `TestAvisoAddons`.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import pathlib
import shutil
from typing import Any

import pytest
from structlog.testing import capture_logs

from hermes import folders
from hermes.ha import HAConnectionError
from hermes.security import ESTADO_CAMBIADO
from hermes.tools import folders_write
from hermes.tools._common import tam_json

CARPETAS = ["addons", "share"]
CENTINELA = "centinela-clave-1"


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class SupervisorSimulado:
    """`sv_request` de `HAClient` con la respuesta de `GET /addons`."""

    def __init__(self, respuesta: Any = None) -> None:
        self.respuesta = {"addons": []} if respuesta is None else respuesta
        self.llamadas: list[tuple[str, str]] = []

    async def sv_request(self, method: str, sv_path: str, **_: Any) -> Any:
        self.llamadas.append((method, sv_path))
        if isinstance(self.respuesta, Exception):
            raise self.respuesta
        return self.respuesta


def _instalada(slug: str) -> dict[str, Any]:
    # Forma de `_list_apps_data` de `api/apps.py` (Supervisor 2026.11.0).
    return {"name": "Ejemplo", "slug": slug, "description": "", "advanced": False,
            "stage": "stable", "version": "1.0.0", "version_latest": "1.0.0",
            "update_available": False, "available": True, "detached": False,
            "homeassistant": None, "state": "started", "repository": "local",
            "build": True, "url": None, "icon": False, "logo": False,
            "system_managed": False}


def _con(*slugs: str) -> dict[str, Any]:
    return {"addons": [_instalada(s) for s in slugs]}


def _symlink(enlace: pathlib.Path, destino: os.PathLike | str, *, dir: bool = False) -> None:
    try:
        os.symlink(destino, enlace, target_is_directory=dir)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"el sistema operativo no deja crear symlinks: {exc}")


def _leido(p: pathlib.Path) -> bytes:
    """Lo escrito por la tool. `safe_write_file` (la escritura atómica de
    /config, reutilizada) abre el temporal con `os.open` sin `O_BINARY`, y en
    Windows escribe `\r\n` por cada `\n`: es uno de los 6 fallos conocidos de
    Windows (`test_preserves_lf_line_endings`). Aquí se deshace solo en
    Windows para no sumar otro; en Linux (el CI) se compara byte a byte."""
    datos = p.read_bytes()
    return datos.replace(b"\r\n", b"\n") if os.name == "nt" else datos


def _escribir(p: pathlib.Path, datos: bytes | str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(datos.encode("utf-8") if isinstance(datos, str) else datos)


@pytest.fixture()
def raices(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, pathlib.Path]:
    addons = (tmp_path / "addons").resolve()
    share = (tmp_path / "share").resolve()
    addons.mkdir()
    share.mkdir()
    monkeypatch.setattr(folders, "ADDONS_BASE", addons)
    monkeypatch.setattr(folders, "SHARE_BASE", share)
    return {"addons": addons, "share": share}


def _tools(supervisor: Any = None, response_max_bytes: int = 131_072) -> dict[str, Any]:
    mcp = DummyMCP()
    folders_write.register(mcp, supervisor or SupervisorSimulado(),
                           response_max_bytes=response_max_bytes)
    return mcp.tools


def _llamar(tools: dict[str, Any], nombre: str, **kwargs: Any) -> Any:
    return asyncio.run(tools[nombre](**kwargs))


def _foto(base: pathlib.Path) -> dict[str, Any]:
    """Todo lo que hay bajo `base`: ruta → contenido (o `dir`/`symlink`)."""
    out: dict[str, Any] = {}
    for dirpath, dirnames, filenames in os.walk(base):
        for d in dirnames:
            p = pathlib.Path(dirpath, d)
            rel = p.relative_to(base).as_posix()
            out[rel] = "symlink" if p.is_symlink() else "dir"
        for f in filenames:
            p = pathlib.Path(dirpath, f)
            rel = p.relative_to(base).as_posix()
            out[rel] = ("symlink", os.readlink(p)) if p.is_symlink() else p.read_bytes()
    return out


def _arbol(base: pathlib.Path) -> None:
    """Escenario común: un fichero, una carpeta con contenido y una vacía."""
    _escribir(base / "a.txt", "uno\n")
    _escribir(base / "dir" / "x.txt", "equis\n")
    _escribir(base / "dir" / "sub" / "y.txt", "i griega\n")
    (base / "vacia").mkdir()


# Una llamada de cada tool que modifica sobre `_arbol`, con lo que tiene que
# cambiar al confirmar.
CASOS = {
    "fs_write_file_in_folder": {"path": "a.txt", "content": "nuevo\n"},
    "fs_create_dir_in_folder": {"path": "nueva/hija"},
    "fs_move_in_folder": {"src": "dir", "dst": "movida"},
    "fs_delete_in_folder": {"path": "dir", "recursive": True},
}


def _efecto_hecho(tool: str, base: pathlib.Path) -> bool:
    if tool == "fs_write_file_in_folder":
        return _leido(base / "a.txt") == b"nuevo\n"
    if tool == "fs_create_dir_in_folder":
        return (base / "nueva" / "hija").is_dir()
    if tool == "fs_move_in_folder":
        return not (base / "dir").exists() and (base / "movida" / "sub" / "y.txt").is_file()
    return not (base / "dir").exists()


def _confirmar(t: dict[str, Any], tool: str, folder: str, r: dict[str, Any], **args: Any) -> Any:
    return _llamar(t, tool, folder=folder, confirmation_token=r["confirmation_token"], **args)


# ── Token y estado (T018) ─────────────────────────────────────────────────────


@pytest.mark.parametrize("folder", CARPETAS)
@pytest.mark.parametrize("tool", list(CASOS))
class TestTokenYEstado:
    def test_sin_token_vista_previa_y_el_disco_no_cambia(self, raices, folder, tool) -> None:
        base = raices[folder]
        _arbol(base)
        antes = _foto(base)
        r = _llamar(_tools(), tool, folder=folder, **CASOS[tool])
        assert "confirmation_token" in r, r
        assert r["preview"]["folder"] == folder
        assert _foto(base) == antes

    def test_con_token_hace_lo_previsualizado(self, raices, folder, tool) -> None:
        base = raices[folder]
        _arbol(base)
        t = _tools()
        r = _llamar(t, tool, folder=folder, **CASOS[tool])
        c = _confirmar(t, tool, folder, r, **CASOS[tool])
        assert c.get("result") == "ok", c
        assert _efecto_hecho(tool, base)
        # El token es de un solo uso.
        otra = _confirmar(t, tool, folder, r, **CASOS[tool])
        assert "error" in otra

    def test_otros_argumentos_no_casan(self, raices, folder, tool) -> None:
        for b in raices.values():
            _arbol(b)
            _escribir(b / "b.txt", "be\n")
        base = raices[folder]
        t = _tools()
        r = _llamar(t, tool, folder=folder, **CASOS[tool])
        otra_carpeta = "share" if folder == "addons" else "addons"
        cambios: list[dict[str, Any]] = [{"folder": otra_carpeta, **CASOS[tool]}]
        if tool == "fs_write_file_in_folder":
            cambios += [{"folder": folder, "path": "b.txt", "content": "nuevo\n"},
                        {"folder": folder, "path": "a.txt", "content": "otro\n"}]
        elif tool == "fs_create_dir_in_folder":
            cambios += [{"folder": folder, "path": "nueva/otra"}]
        elif tool == "fs_move_in_folder":
            cambios += [{"folder": folder, "src": "dir", "dst": "otro"},
                        {"folder": folder, "src": "vacia", "dst": "movida"}]
        else:
            # `recursive` también va atado: con el mismo `path` y `recursive`
            # false el token no casa (y la carpeta no se toca).
            cambios += [{"folder": folder, "path": "dir", "recursive": False},
                        {"folder": folder, "path": "vacia", "recursive": True}]
        antes = {k: _foto(b) for k, b in raices.items()}
        for args in cambios:
            c = _llamar(t, tool, confirmation_token=r["confirmation_token"], **args)
            assert "does not match" in str(c.get("error")), (args, c)
        assert {k: _foto(b) for k, b in raices.items()} == antes
        # El token sigue valiendo para lo previsualizado.
        assert _confirmar(t, tool, folder, r, **CASOS[tool]).get("result") == "ok"
        assert _efecto_hecho(tool, base)

    def test_el_token_de_otra_tool_no_vale(self, raices, folder, tool) -> None:
        base = raices[folder]
        _arbol(base)
        t = _tools()
        otra = next(n for n in CASOS if n != tool)
        r = _llamar(t, otra, folder=folder, **CASOS[otra])
        antes = _foto(base)
        c = _llamar(t, tool, folder=folder, confirmation_token=r["confirmation_token"],
                    **CASOS[tool])
        assert "does not match" in str(c.get("error")), c
        assert _foto(base) == antes


def _cambiar_dentro(base: pathlib.Path, como: str) -> None:
    if como == "crear":
        _escribir(base / "dir" / "sub" / "nuevo.txt", "n\n")
    elif como == "modificar":
        # Mismo tamaño y contenido distinto, y además la fecha.
        _escribir(base / "dir" / "x.txt", "EQUIS\n")
        os.utime(base / "dir" / "x.txt", ns=(1_000_000_000, 1_000_000_000))
    elif como == "fecha":
        # Solo la fecha: el contenido y el tamaño son los mismos.
        st = os.stat(base / "dir" / "x.txt")
        os.utime(base / "dir" / "x.txt", ns=(st.st_atime_ns, st.st_mtime_ns + 7_000_000_000))
    else:
        (base / "dir" / "sub" / "y.txt").unlink()


def _estado_cambiado(c: dict[str, Any]) -> None:
    assert c.get("error") == ESTADO_CAMBIADO, c
    assert c.get("preview_outdated") is True
    assert "new preview" in c.get("hint", "")


@pytest.mark.parametrize("folder", CARPETAS)
class TestCambioEntreMedias:
    """FR-011, FR-012, SC-003: cualquier cambio en el objetivo entre la vista
    previa y la confirmación la cancela sin tocar nada."""

    @pytest.mark.parametrize("como", ["crear", "modificar", "fecha", "borrar"])
    def test_borrar(self, raices, folder, como) -> None:
        base = raices[folder]
        _arbol(base)
        t = _tools()
        r = _llamar(t, "fs_delete_in_folder", folder=folder, path="dir", recursive=True)
        _cambiar_dentro(base, como)
        c = _confirmar(t, "fs_delete_in_folder", folder, r, path="dir", recursive=True)
        _estado_cambiado(c)
        assert (base / "dir" / "x.txt").exists()

    @pytest.mark.parametrize("como", ["crear", "modificar", "borrar"])
    def test_mover_cambia_el_origen(self, raices, folder, como) -> None:
        base = raices[folder]
        _arbol(base)
        t = _tools()
        r = _llamar(t, "fs_move_in_folder", folder=folder, src="dir", dst="movida")
        _cambiar_dentro(base, como)
        c = _confirmar(t, "fs_move_in_folder", folder, r, src="dir", dst="movida")
        _estado_cambiado(c)
        assert (base / "dir").is_dir() and not (base / "movida").exists()

    def test_mover_aparece_el_destino(self, raices, folder) -> None:
        base = raices[folder]
        _arbol(base)
        t = _tools()
        r = _llamar(t, "fs_move_in_folder", folder=folder, src="a.txt", dst="b.txt")
        _escribir(base / "b.txt", "alguien\n")
        c = _confirmar(t, "fs_move_in_folder", folder, r, src="a.txt", dst="b.txt")
        _estado_cambiado(c)
        assert (base / "b.txt").read_bytes() == b"alguien\n"
        assert (base / "a.txt").exists()

    @pytest.mark.parametrize("como", ["modificar", "crear", "borrar"])
    def test_escribir(self, raices, folder, como) -> None:
        base = raices[folder]
        t = _tools()
        if como != "crear":
            _escribir(base / "f.txt", "antes\n")
        r = _llamar(t, "fs_write_file_in_folder", folder=folder, path="f.txt",
                    content="despues\n")
        if como == "modificar":
            _escribir(base / "f.txt", "ANTES\n")
        elif como == "crear":
            _escribir(base / "f.txt", "otro\n")
        else:
            (base / "f.txt").unlink()
        esperado = _foto(base)
        c = _confirmar(t, "fs_write_file_in_folder", folder, r, path="f.txt")
        _estado_cambiado(c)
        assert _foto(base) == esperado

    def test_crear_carpeta_que_aparece(self, raices, folder) -> None:
        base = raices[folder]
        t = _tools()
        r = _llamar(t, "fs_create_dir_in_folder", folder=folder, path="nueva")
        _escribir(base / "nueva", "soy un fichero\n")
        c = _confirmar(t, "fs_create_dir_in_folder", folder, r, path="nueva")
        _estado_cambiado(c)
        assert (base / "nueva").is_file()


@pytest.mark.parametrize("folder", CARPETAS)
class TestRecompruebaAlConfirmar:
    """FR-017: al confirmar se repiten las comprobaciones que no van en el
    estado; si algo ya no se cumple, no se hace nada y el token se gasta
    (se completa con error, no se queda en `executing`)."""

    def test_desaparece_el_padre_del_destino(self, raices, folder) -> None:
        base = raices[folder]
        _arbol(base)
        (base / "destino").mkdir()
        t = _tools()
        r = _llamar(t, "fs_move_in_folder", folder=folder, src="a.txt", dst="destino/a.txt")
        assert "confirmation_token" in r, r
        (base / "destino").rmdir()
        c = _confirmar(t, "fs_move_in_folder", folder, r, src="a.txt", dst="destino/a.txt")
        assert c.get("error") == "destination_parent_missing", c
        assert (base / "a.txt").exists()
        # Gastado: no se queda «executing» ni vuelve a valer.
        (base / "destino").mkdir()
        otra = _confirmar(t, "fs_move_in_folder", folder, r, src="a.txt", dst="destino/a.txt")
        assert "confirmation_token" in str(otra.get("error")), otra
        assert "currently being executed" not in str(otra.get("error"))
        assert (base / "a.txt").exists()


# ── Aviso de /addons y sin backup (T018) ──────────────────────────────────────


@pytest.mark.parametrize("tool", list(CASOS))
class TestAvisoAddons:
    def test_solo_en_addons(self, raices, tool) -> None:
        for folder, base in raices.items():
            _arbol(base)
            r = _llamar(_tools(), tool, folder=folder, **CASOS[tool])
            if folder == "addons":
                assert r["preview"]["warning"] == folders.AVISO_ADDONS
                assert "Supervisor builds and runs" in r["preview"]["warning"]
            else:
                assert "warning" not in r["preview"], r["preview"]


@pytest.mark.parametrize("tool", list(CASOS))
class TestSinBackup:
    def test_backup_null_y_la_llamada_exacta(self, raices, tool) -> None:
        esperado = {
            "addons": "sv_create_backup_partial(folders='[\"addons/local\"]')",
            "share": "sv_create_backup_partial(folders='[\"share\"]')",
        }
        for folder, base in raices.items():
            _arbol(base)
            p = _llamar(_tools(), tool, folder=folder, **CASOS[tool])["preview"]
            assert "backup" in p and p["backup"] is None
            assert p["reversible"] is (tool == "fs_create_dir_in_folder")
            assert esperado[folder] in p["backup_hint"]
            if tool != "fs_create_dir_in_folder":
                assert "cannot be undone" in p["backup_hint"]
            assert p["state_bound"] == folders.ESTADO_ATADO


# ── Escribir (T019) ───────────────────────────────────────────────────────────


def _sha12(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()[:12]


@pytest.mark.parametrize("folder", CARPETAS)
class TestEscribir:
    def test_fichero_nuevo_con_padres(self, raices, folder) -> None:
        base = raices[folder]
        t = _tools()
        r = _llamar(t, "fs_write_file_in_folder", folder=folder, path="a/b/c.txt",
                    content="hola\n")
        p = r["preview"]
        assert p["action"] == "write" and p["path"] == "a/b/c.txt"
        assert p["exists"] is False
        assert p["new_size_bytes"] == 5 and p["new_sha256_12"] == _sha12(b"hola\n")
        assert "current_size_bytes" not in p
        assert p["is_blacklisted"] is False
        assert r["omit_on_confirm"] == ["content"]
        # Basta con la ruta y el token: el contenido lo guardó el servidor.
        c = _confirmar(t, "fs_write_file_in_folder", folder, r, path="a/b/c.txt")
        destino = base / "a" / "b" / "c.txt"
        assert c == {"result": "ok", "action": "write", "folder": folder,
                     "path": "a/b/c.txt", "bytes_written": destino.stat().st_size}
        assert _leido(destino) == b"hola\n"

    def test_fichero_existente(self, raices, folder) -> None:
        base = raices[folder]
        _escribir(base / "f.txt", "antes\n")
        r = _llamar(_tools(), "fs_write_file_in_folder", folder=folder, path="/" + folder + "/f.txt",
                    content="despues!\n")
        p = r["preview"]
        assert p["path"] == "f.txt" and p["exists"] is True
        assert p["current_size_bytes"] == 6 and p["current_sha256_12"] == _sha12(b"antes\n")
        assert p["new_size_bytes"] == 9 and p["new_sha256_12"] == _sha12(b"despues!\n")
        assert len(p["current_sha256_12"]) == 12

    def test_otro_contenido_al_confirmar_no_casa(self, raices, folder) -> None:
        base = raices[folder]
        t = _tools()
        r = _llamar(t, "fs_write_file_in_folder", folder=folder, path="f.txt", content="uno\n")
        c = _confirmar(t, "fs_write_file_in_folder", folder, r, path="f.txt", content="dos\n")
        assert "does not match" in c["error"]
        assert not (base / "f.txt").exists()
        c = _confirmar(t, "fs_write_file_in_folder", folder, r, path="f.txt", content="uno\n")
        assert c["result"] == "ok"

    @pytest.mark.parametrize("ruta", ["dir", ".", "dir/"])
    def test_directorio(self, raices, folder, ruta) -> None:
        (raices[folder] / "dir").mkdir()
        r = _llamar(_tools(), "fs_write_file_in_folder", folder=folder, path=ruta, content="x")
        assert r["error"] == "is_directory" and "confirmation_token" not in r

    def test_padre_que_es_un_fichero(self, raices, folder) -> None:
        _escribir(raices[folder] / "f.txt", "x\n")
        r = _llamar(_tools(), "fs_write_file_in_folder", folder=folder, path="f.txt/g.txt",
                    content="x")
        assert r["error"] == "not_a_directory" and "confirmation_token" not in r

    def test_sin_contenido_ni_token(self, raices, folder) -> None:
        r = _llamar(_tools(), "fs_write_file_in_folder", folder=folder, path="f.txt")
        assert r["error"] == "invalid_argument" and r["field"] == "content"

    def test_escritura_atomica_conserva_crlf_y_bom(self, raices, folder) -> None:
        if os.name == "nt":
            pytest.skip("safe_write_file escribe en modo texto en Windows (fallo "
                        "conocido de /config); este caso corre en el CI de Linux")
        base = raices[folder]
        _escribir(base / "f.txt", b"\xef\xbb\xbfa\r\nb\r\n")
        t = _tools()
        r = _llamar(t, "fs_write_file_in_folder", folder=folder, path="f.txt", content="x\ny\n")
        c = _confirmar(t, "fs_write_file_in_folder", folder, r, path="f.txt")
        assert (base / "f.txt").read_bytes() == b"\xef\xbb\xbfx\r\ny\r\n"
        assert c["bytes_written"] == len(b"\xef\xbb\xbfx\r\ny\r\n")
        assert not list(base.glob("*.mcp_tmp"))

    def test_json_llega_como_texto(self, raices, folder) -> None:
        # `content` anotado exactamente `str`: el SDK no hace `json.loads`.
        firma = inspect.signature(_tools()["fs_write_file_in_folder"])
        assert firma.parameters["content"].annotation in (str, "str")
        base = raices[folder]
        t = _tools()
        r = _llamar(t, "fs_write_file_in_folder", folder=folder, path="d.json", content='{"a": 1}')
        _confirmar(t, "fs_write_file_in_folder", folder, r, path="d.json")
        assert _leido(base / "d.json") == b'{"a": 1}\n'

    def test_lista_negra_se_escribe_sin_ensenar_contenido(self, raices, folder) -> None:
        base = raices[folder]
        _escribir(base / "secrets.yaml", "viejo: " + CENTINELA + "\n")
        t = _tools()
        nuevo = "clave: " + CENTINELA + "-nuevo\n"
        r = _llamar(t, "fs_write_file_in_folder", folder=folder, path="secrets.yaml",
                    content=nuevo)
        assert r["preview"]["is_blacklisted"] is True
        assert CENTINELA not in json.dumps(r)
        c = _confirmar(t, "fs_write_file_in_folder", folder, r, path="secrets.yaml")
        assert c["result"] == "ok" and CENTINELA not in json.dumps(c)
        assert (base / "secrets.yaml").read_text(encoding="utf-8") == nuevo


# ── Crear carpeta (T020) ──────────────────────────────────────────────────────


@pytest.mark.parametrize("folder", CARPETAS)
class TestCrearCarpeta:
    def test_con_padres(self, raices, folder) -> None:
        base = raices[folder]
        (base / "x").mkdir()
        t = _tools()
        r = _llamar(t, "fs_create_dir_in_folder", folder=folder, path="x/y/z")
        p = r["preview"]
        assert p["action"] == "create_dir" and p["path"] == "x/y/z"
        assert p["creates_parents"] == ["x/y"]
        assert p["reversible"] is True
        c = _confirmar(t, "fs_create_dir_in_folder", folder, r, path="x/y/z")
        assert c == {"result": "ok", "action": "create_dir", "folder": folder,
                     "path": "x/y/z", "created": ["x/y", "x/y/z"]}
        assert (base / "x" / "y" / "z").is_dir()

    @pytest.mark.parametrize("ruta", ["f.txt", "d", ".", "/addons", "/share"])
    def test_ya_existe(self, raices, folder, ruta) -> None:
        base = raices[folder]
        _escribir(base / "f.txt", "x")
        (base / "d").mkdir()
        if ruta.startswith("/") and ruta != "/" + folder:
            pytest.skip("la otra carpeta es traversal (TestRutas)")
        r = _llamar(_tools(), "fs_create_dir_in_folder", folder=folder, path=ruta)
        assert r["error"] == "already_exists" and "confirmation_token" not in r


# ── Mover (T021) ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("folder", CARPETAS)
class TestMover:
    def test_fichero(self, raices, folder) -> None:
        base = raices[folder]
        _arbol(base)
        t = _tools()
        r = _llamar(t, "fs_move_in_folder", folder=folder, src="a.txt", dst="vacia/b.txt")
        p = r["preview"]
        assert p["action"] == "move" and p["src"] == "a.txt" and p["dst"] == "vacia/b.txt"
        assert p["type"] == "file" and "contents" not in p
        c = _confirmar(t, "fs_move_in_folder", folder, r, src="a.txt", dst="vacia/b.txt")
        assert c == {"result": "ok", "action": "move", "folder": folder,
                     "src": "a.txt", "dst": "vacia/b.txt"}
        assert (base / "vacia" / "b.txt").read_bytes() == b"uno\n"
        assert not (base / "a.txt").exists()

    def test_carpeta_con_recuento(self, raices, folder) -> None:
        base = raices[folder]
        _arbol(base)
        r = _llamar(_tools(), "fs_move_in_folder", folder=folder, src="dir", dst="otra")
        p = r["preview"]
        assert p["type"] == "dir"
        assert p["contents"]["files"] == 2 and p["contents"]["dirs"] == 1
        assert p["contents"]["sample"] == ["sub", "sub/y.txt", "x.txt"]

    def test_symlink_mueve_el_enlace(self, raices, folder, tmp_path) -> None:
        base = raices[folder]
        fuera = tmp_path / "fuera.txt"
        _escribir(fuera, "intacto\n")
        _symlink(base / "enlace", fuera)
        t = _tools()
        r = _llamar(t, "fs_move_in_folder", folder=folder, src="enlace", dst="otro")
        assert r["preview"]["type"] == "symlink", r
        c = _confirmar(t, "fs_move_in_folder", folder, r, src="enlace", dst="otro")
        assert c["result"] == "ok"
        assert os.readlink(base / "otro") == str(fuera)
        assert fuera.read_bytes() == b"intacto\n"

    def test_rechazos_sin_token(self, raices, folder, monkeypatch) -> None:
        base = raices[folder]
        _arbol(base)
        (base / "con" / "nas").mkdir(parents=True)
        monkeypatch.setattr(folders, "es_punto_de_montaje",
                            lambda p: pathlib.Path(p).name == "nas")
        casos = [
            ("no_existe", "x", "not_found"),
            ("a.txt", "dir", "destination_exists"),
            ("a.txt", "falta/b.txt", "destination_parent_missing"),
            ("dir", "dir/sub/dentro", "invalid_destination"),
            ("dir", "dir", "destination_exists"),
            (".", "x", "root_protected"),
            ("a.txt", ".", "root_protected"),
            ("a.txt", "/" + folder, "root_protected"),
            ("con", "otro", "mount_point"),
            ("con/nas", "otro", "mount_point"),
            ("a.txt", "../fuera.txt", "traversal"),
        ]
        antes = _foto(base)
        for src, dst, codigo in casos:
            r = _llamar(_tools(), "fs_move_in_folder", folder=folder, src=src, dst=dst)
            assert r.get("error") == codigo, (src, dst, r)
            assert "confirmation_token" not in r
        assert _foto(base) == antes

    def test_no_entre_carpetas(self, raices, folder) -> None:
        _arbol(raices[folder])
        otra = "share" if folder == "addons" else "addons"
        r = _llamar(_tools(), "fs_move_in_folder", folder=folder, src="a.txt",
                    dst="/" + otra + "/a.txt")
        assert r["error"] == "traversal"


# ── Borrar y puntos de montaje (T022) ─────────────────────────────────────────


@pytest.mark.parametrize("folder", CARPETAS)
class TestBorrar:
    def test_fichero(self, raices, folder) -> None:
        base = raices[folder]
        _arbol(base)
        t = _tools()
        r = _llamar(t, "fs_delete_in_folder", folder=folder, path="a.txt")
        p = r["preview"]
        assert p["action"] == "delete" and p["type"] == "file" and p["size_bytes"] == 4
        c = _confirmar(t, "fs_delete_in_folder", folder, r, path="a.txt")
        assert c["result"] == "ok" and c["deleted"] == {"files": 1, "dirs": 0, "symlinks": 0}
        assert not (base / "a.txt").exists()

    def test_carpeta_vacia_sin_recursive(self, raices, folder) -> None:
        base = raices[folder]
        _arbol(base)
        t = _tools()
        r = _llamar(t, "fs_delete_in_folder", folder=folder, path="vacia")
        assert r["preview"]["type"] == "dir"
        c = _confirmar(t, "fs_delete_in_folder", folder, r, path="vacia")
        assert c["deleted"] == {"files": 0, "dirs": 1, "symlinks": 0}
        assert not (base / "vacia").exists()

    def test_no_vacia_sin_recursive(self, raices, folder) -> None:
        _arbol(raices[folder])
        r = _llamar(_tools(), "fs_delete_in_folder", folder=folder, path="dir")
        assert r["error"] == "directory_not_empty" and "recursive" in r["hint"]
        assert "confirmation_token" not in r

    def test_recursivo_con_recuento_y_muestra(self, raices, folder) -> None:
        base = raices[folder]
        for i in range(25):
            _escribir(base / "grande" / f"f{i:02d}.txt", "x" * i)
        (base / "grande" / "sub").mkdir()
        t = _tools()
        r = _llamar(t, "fs_delete_in_folder", folder=folder, path="grande", recursive=True)
        cont = r["preview"]["contents"]
        assert cont["files"] == 25 and cont["dirs"] == 1 and cont["symlinks"] == 0
        assert cont["total_bytes"] == sum(range(25))
        assert cont["sample"] == [f"f{i:02d}.txt" for i in range(20)]
        assert cont["sample_truncated"] is True
        c = _confirmar(t, "fs_delete_in_folder", folder, r, path="grande", recursive=True)
        assert c["deleted"] == {"files": 25, "dirs": 2, "symlinks": 0}
        assert not (base / "grande").exists()

    @pytest.mark.parametrize("ruta", ["", " ", ".", "./", "dir/..", "ROOT", "ROOT/"])
    def test_raiz(self, raices, folder, ruta) -> None:
        base = raices[folder]
        _arbol(base)
        ruta = ruta.replace("ROOT", "/" + folder)
        for recursive in (False, True):
            r = _llamar(_tools(), "fs_delete_in_folder", folder=folder, path=ruta,
                        recursive=recursive)
            assert r.get("error") == "root_protected", (ruta, r)
        assert (base / "a.txt").exists()

    def test_no_existe(self, raices, folder) -> None:
        r = _llamar(_tools(), "fs_delete_in_folder", folder=folder, path="nada")
        assert r["error"] == "not_found"

    def test_symlink_borra_el_enlace_y_no_el_destino(self, raices, folder, tmp_path) -> None:
        base = raices[folder]
        fuera = tmp_path / "fuera"
        _escribir(fuera / "importante.txt", "no tocar\n")
        _symlink(base / "enlace", fuera, dir=True)
        t = _tools()
        r = _llamar(t, "fs_delete_in_folder", folder=folder, path="enlace", recursive=True)
        assert r["preview"]["type"] == "symlink", r
        c = _confirmar(t, "fs_delete_in_folder", folder, r, path="enlace", recursive=True)
        assert c["deleted"] == {"files": 0, "dirs": 0, "symlinks": 1}
        assert not os.path.lexists(base / "enlace")
        assert (fuera / "importante.txt").read_bytes() == b"no tocar\n"

    def test_recursivo_no_sigue_symlinks(self, raices, folder, tmp_path) -> None:
        base = raices[folder]
        fuera = tmp_path / "fuera"
        _escribir(fuera / "importante.txt", "no tocar\n")
        _escribir(base / "d" / "f.txt", "x")
        _symlink(base / "d" / "enlace", fuera, dir=True)
        t = _tools()
        r = _llamar(t, "fs_delete_in_folder", folder=folder, path="d", recursive=True)
        assert r["preview"]["contents"]["symlinks"] == 1
        c = _confirmar(t, "fs_delete_in_folder", folder, r, path="d", recursive=True)
        assert c["result"] == "ok"
        assert (fuera / "importante.txt").exists()

    def test_demasiado_grande(self, raices, folder, monkeypatch) -> None:
        base = raices[folder]
        for i in range(10):
            _escribir(base / "d" / f"{i}.txt", "x")
        monkeypatch.setattr(folders, "MAX_ENTRADAS", 5)
        r = _llamar(_tools(), "fs_delete_in_folder", folder=folder, path="d", recursive=True)
        assert r["error"] == "too_large_to_preview" and "confirmation_token" not in r

    def test_a_medias(self, raices, folder, monkeypatch) -> None:
        base = raices[folder]
        _escribir(base / "d" / "uno.txt", "1")
        _escribir(base / "d" / "dos.txt", "2")
        t = _tools()
        r = _llamar(t, "fs_delete_in_folder", folder=folder, path="d", recursive=True)

        def rmtree_a_medias(path: Any, *, onexc: Any = None, **_: Any) -> None:
            # Borra un fichero y falla con el otro, como un `rmtree` que se
            # encuentra un fichero sin permiso: llama a `onexc` y sigue.
            os.unlink(pathlib.Path(path) / "uno.txt")
            onexc(os.unlink, os.fspath(pathlib.Path(path) / "dos.txt"),
                  PermissionError("denied"))
            onexc(os.rmdir, os.fspath(path), OSError("not empty"))

        # Por ruta: el `rmtree` falso no sabe de `dir_fd` (T048); los dos
        # caminos se prueban en `test_los_dos_caminos_*`.
        monkeypatch.setattr(folders, "USAR_DIR_FD", False)
        monkeypatch.setattr(folders_write.shutil, "rmtree", rmtree_a_medias)
        c = _confirmar(t, "fs_delete_in_folder", folder, r, path="d", recursive=True)
        assert c.get("error") == "partial" and c["partial"] is True
        assert c["remaining"] == {"files": 1, "dirs": 1, "symlinks": 0}
        assert "result" not in c
        # El token se completó como fallido: no vuelve a valer.
        otra = _confirmar(t, "fs_delete_in_folder", folder, r, path="d", recursive=True)
        assert "confirmation_token" in str(otra.get("error"))

    def test_vista_previa_cabe_en_el_tope(self, raices, folder) -> None:
        base = raices[folder]
        # Nombres de 100 caracteres: la muestra entera (20) no cabe en 2000
        # bytes; las rutas largas de Windows (260) no dejan ir mucho más allá.
        for i in range(25):
            _escribir(base / "d" / (f"{i:02d}" + "n" * 94 + ".txt"), "x")
        r = _llamar(_tools(response_max_bytes=2000), "fs_delete_in_folder", folder=folder,
                    path="d", recursive=True)
        assert "confirmation_token" in r
        assert tam_json(r) <= 2000
        cont = r["preview"]["contents"]
        assert cont["files"] == 25 and cont["sample_truncated"] is True
        assert len(cont["sample"]) < 20


@pytest.mark.parametrize("folder", CARPETAS)
class TestPuntosDeMontaje:
    @pytest.fixture(autouse=True)
    def _nas(self, raices, folder, monkeypatch) -> None:
        base = raices[folder]
        _escribir(base / "datos" / "nas" / "f.txt", "del NAS\n")
        _escribir(base / "datos" / "local.txt", "x\n")
        monkeypatch.setattr(folders, "es_punto_de_montaje",
                            lambda p: pathlib.Path(p).name == "nas")

    @pytest.mark.parametrize("ruta", ["datos/nas", "datos"])
    def test_borrar(self, raices, folder, ruta) -> None:
        for recursive in (False, True):
            r = _llamar(_tools(), "fs_delete_in_folder", folder=folder, path=ruta,
                        recursive=recursive)
            assert r.get("error") == "mount_point", (ruta, recursive, r)
            assert "confirmation_token" not in r
        assert (raices[folder] / "datos" / "nas" / "f.txt").exists()

    def test_lo_de_al_lado_si(self, raices, folder) -> None:
        r = _llamar(_tools(), "fs_delete_in_folder", folder=folder, path="datos/local.txt")
        assert "confirmation_token" in r

    def test_aparece_entre_medias(self, raices, folder, monkeypatch) -> None:
        # Un montaje que aparece después de la vista previa (el Supervisor
        # monta el NAS) cambia la huella y además se recomprueba.
        t = _tools()
        _escribir(raices[folder] / "otro" / "red" / "f.txt", "x")
        r = _llamar(t, "fs_delete_in_folder", folder=folder, path="otro", recursive=True)
        monkeypatch.setattr(folders, "es_punto_de_montaje",
                            lambda p: pathlib.Path(p).name in ("nas", "red"))
        c = _confirmar(t, "fs_delete_in_folder", folder, r, path="otro", recursive=True)
        assert "error" in c
        assert (raices[folder] / "otro" / "red" / "f.txt").exists()


# ── Apps locales instaladas (T023) ────────────────────────────────────────────


@pytest.fixture()
def app(raices) -> pathlib.Path:
    base = raices["addons"]
    _escribir(base / "ejemplo" / "config.yaml", "name: Ejemplo\nslug: ejemplo\nversion: 1.0.0\n")
    _escribir(base / "ejemplo" / "Dockerfile", "FROM scratch\n")
    _escribir(base / "dev" / "anidada" / "config.json", '{"slug": "anidada"}')
    return base


class TestAppsInstaladas:
    @pytest.mark.parametrize("tool,args", [
        ("fs_delete_in_folder", {"path": "ejemplo", "recursive": True}),
        ("fs_delete_in_folder", {"path": "ejemplo/config.yaml"}),
        ("fs_move_in_folder", {"src": "ejemplo", "dst": "otra"}),
        ("fs_move_in_folder", {"src": "ejemplo/config.yaml", "dst": "ejemplo/viejo.yaml"}),
    ])
    def test_instalada_se_rechaza(self, app, tool, args) -> None:
        antes = _foto(app)
        r = _llamar(_tools(SupervisorSimulado(_con("local_ejemplo"))), tool,
                    folder="addons", **args)
        assert r.get("error") == "installed_app", r
        assert r["slug"] == "local_ejemplo"
        assert "sv_uninstall_addon(slug='local_ejemplo')" in r["hint"]
        assert "confirmation_token" not in r
        assert _foto(app) == antes

    def test_carpeta_que_la_contiene(self, app) -> None:
        sup = SupervisorSimulado(_con("local_anidada"))
        for ruta in ("dev", "dev/anidada"):
            r = _llamar(_tools(sup), "fs_delete_in_folder", folder="addons", path=ruta,
                        recursive=True)
            assert r.get("error") == "installed_app" and r["slug"] == "local_anidada", r

    def test_un_fichero_suyo_con_aviso(self, app) -> None:
        r = _llamar(_tools(SupervisorSimulado(_con("local_ejemplo"))), "fs_delete_in_folder",
                    folder="addons", path="ejemplo/Dockerfile")
        assert "confirmation_token" in r, r
        aviso = r["preview"]["inside_installed_app"]
        assert aviso["slug"] == "local_ejemplo" and "sv_rebuild_addon" in aviso["note"]

    def test_no_instalada(self, app) -> None:
        t = _tools(SupervisorSimulado(_con("local_otra_cosa", "core_mosquitto")))
        r = _llamar(t, "fs_delete_in_folder", folder="addons", path="ejemplo", recursive=True)
        assert "confirmation_token" in r, r
        assert "inside_installed_app" not in r["preview"]
        c = _confirmar(t, "fs_delete_in_folder", "addons", r, path="ejemplo", recursive=True)
        assert c["result"] == "ok" and not (app / "ejemplo").exists()

    @pytest.mark.parametrize("respuesta", [HAConnectionError("caído"), {"result": "error"}])
    def test_supervisor_caido_con_config(self, app, respuesta) -> None:
        r = _llamar(_tools(SupervisorSimulado(respuesta)), "fs_delete_in_folder",
                    folder="addons", path="ejemplo", recursive=True)
        assert r.get("error") == "installed_check_failed", r
        assert "confirmation_token" not in r

    def test_supervisor_caido_sin_config(self, app) -> None:
        _escribir(app / "suelto" / "x.txt", "x")
        r = _llamar(_tools(SupervisorSimulado(HAConnectionError("caído"))),
                    "fs_delete_in_folder", folder="addons", path="suelto", recursive=True)
        assert "confirmation_token" in r, r
        assert r["preview"]["installed_check"] == "failed"

    def test_huerfana_y_config_ilegible(self, app) -> None:
        _escribir(app / "rota" / "config.yaml", "slug: [sin cerrar\n")
        sup = SupervisorSimulado(_con("local_perdida"))
        r = _llamar(_tools(sup), "fs_delete_in_folder", folder="addons", path="rota",
                    recursive=True)
        assert r.get("error") == "installed_check_inconclusive", r
        assert r["installed_without_folder"] == ["local_perdida"]
        # Sin huérfanas, un `config.*` ilegible no es una app (el Supervisor
        # tampoco lo carga).
        r = _llamar(_tools(SupervisorSimulado(_con("local_ejemplo"))), "fs_delete_in_folder",
                    folder="addons", path="rota", recursive=True)
        assert "confirmation_token" in r, r

    @pytest.mark.parametrize("contenido", ["slug: otro\n", "slug: [roto\n", "name: sin slug\n"])
    def test_escribir_su_config_con_otro_slug(self, app, contenido) -> None:
        r = _llamar(_tools(SupervisorSimulado(_con("local_ejemplo"))),
                    "fs_write_file_in_folder", folder="addons", path="ejemplo/config.yaml",
                    content=contenido)
        assert r.get("error") == "installed_app" and r["slug"] == "local_ejemplo", r

    def test_escribir_su_config_con_el_mismo_slug(self, app) -> None:
        r = _llamar(_tools(SupervisorSimulado(_con("local_ejemplo"))),
                    "fs_write_file_in_folder", folder="addons", path="ejemplo/config.yaml",
                    content="name: Ejemplo 2\nslug: ejemplo\nversion: 1.0.1\n")
        assert "confirmation_token" in r, r
        assert r["preview"]["inside_installed_app"]["slug"] == "local_ejemplo"

    def test_supervisor_caido_al_escribir(self, app) -> None:
        sup = SupervisorSimulado(HAConnectionError("caído"))
        r = _llamar(_tools(sup), "fs_write_file_in_folder", folder="addons",
                    path="nueva/config.yaml", content="slug: nueva\n")
        assert r.get("error") == "installed_check_failed", r
        r = _llamar(_tools(sup), "fs_write_file_in_folder", folder="addons",
                    path="ejemplo/Dockerfile", content="FROM alpine\n")
        assert "confirmation_token" in r, r
        assert r["preview"]["installed_check"] == "failed"

    @pytest.mark.parametrize("tool,args", [
        ("fs_delete_in_folder", {"path": "ejemplo", "recursive": True}),
        ("fs_move_in_folder", {"src": "ejemplo", "dst": "otra"}),
        ("fs_write_file_in_folder", {"path": "ejemplo/config.yaml", "content": "slug: x\n"}),
    ])
    def test_se_instala_entre_medias(self, app, tool, args) -> None:
        sup = SupervisorSimulado(_con())
        t = _tools(sup)
        r = _llamar(t, tool, folder="addons", **args)
        assert "confirmation_token" in r, r
        sup.respuesta = _con("local_ejemplo")
        antes = _foto(app)
        c = _confirmar(t, tool, "addons", r, **args)
        assert c.get("error") == "installed_app", c
        assert _foto(app) == antes

    def test_supervisor_cae_entre_medias(self, app) -> None:
        sup = SupervisorSimulado(_con())
        t = _tools(sup)
        r = _llamar(t, "fs_delete_in_folder", folder="addons", path="ejemplo", recursive=True)
        sup.respuesta = HAConnectionError("caído")
        c = _confirmar(t, "fs_delete_in_folder", "addons", r, path="ejemplo", recursive=True)
        assert c.get("error") == "installed_check_failed", c
        assert (app / "ejemplo").exists()

    def test_mover_dentro_de_una_instalada_avisa(self, app) -> None:
        _escribir(app / "suelto.txt", "x")
        r = _llamar(_tools(SupervisorSimulado(_con("local_ejemplo"))), "fs_move_in_folder",
                    folder="addons", src="suelto.txt", dst="ejemplo/suelto.txt")
        assert r["preview"]["inside_installed_app"]["slug"] == "local_ejemplo"

    def test_en_share_no_se_pregunta(self, raices) -> None:
        base = raices["share"]
        _escribir(base / "ejemplo" / "config.yaml", "slug: ejemplo\n")
        sup = SupervisorSimulado(_con("local_ejemplo"))
        t = _tools(sup)
        for tool, args in [
            ("fs_delete_in_folder", {"path": "ejemplo", "recursive": True}),
            ("fs_move_in_folder", {"src": "ejemplo", "dst": "otra"}),
            ("fs_write_file_in_folder", {"path": "ejemplo/config.yaml", "content": "slug: x\n"}),
            ("fs_create_dir_in_folder", {"path": "ejemplo/nueva"}),
        ]:
            r = _llamar(t, tool, folder="share", **args)
            assert "confirmation_token" in r, (tool, r)
            assert "inside_installed_app" not in r["preview"]
        c = _confirmar(t, "fs_delete_in_folder", "share", r := _llamar(
            t, "fs_delete_in_folder", folder="share", path="ejemplo", recursive=True),
            path="ejemplo", recursive=True)
        assert c["result"] == "ok"
        assert sup.llamadas == []


# ── Rutas (T018, SC-002) ──────────────────────────────────────────────────────


@pytest.mark.parametrize("folder", CARPETAS)
@pytest.mark.parametrize("tool", list(CASOS))
class TestRutas:
    @pytest.mark.parametrize("ruta", ["../fuera", "/etc/passwd", "/config/x", "a\x00b",
                                      "a%00b", "x/" + "n" * 300])
    def test_traversal(self, raices, folder, tool, ruta) -> None:
        args = dict(CASOS[tool])
        clave = "src" if tool == "fs_move_in_folder" else "path"
        args[clave] = ruta
        r = _llamar(_tools(), tool, folder=folder, **args)
        assert r.get("error") == "traversal", r

    def test_symlink_hacia_fuera_al_escribir(self, raices, folder, tool, tmp_path) -> None:
        if tool != "fs_write_file_in_folder":
            pytest.skip("solo escribir sigue el symlink")
        fuera = tmp_path / "fuera.txt"
        _escribir(fuera, "no\n")
        _symlink(raices[folder] / "enlace", fuera)
        r = _llamar(_tools(), tool, folder=folder, path="enlace", content="si\n")
        assert r.get("error") == "traversal", r
        assert fuera.read_bytes() == b"no\n"

    def test_carpeta_invalida_y_no_disponible(self, raices, folder, tool, monkeypatch,
                                              tmp_path) -> None:
        r = _llamar(_tools(), tool, folder="config", **CASOS[tool])
        assert r.get("error") == "invalid_argument", r
        monkeypatch.setattr(folders, "ADDONS_BASE" if folder == "addons" else "SHARE_BASE",
                            tmp_path / "no_montada")
        r = _llamar(_tools(), tool, folder=folder, **CASOS[tool])
        assert r.get("error") == "folder_unavailable", r


# ── Log (T024) ────────────────────────────────────────────────────────────────


class TestLog:
    def test_folder_action_sin_contenido_ni_huellas(self, raices) -> None:
        base = raices["share"]
        contenido = "clave: " + CENTINELA + "\n"
        t = _tools()
        with capture_logs() as logs:
            r = _llamar(t, "fs_write_file_in_folder", folder="share", path="f.txt",
                        content=contenido)
            _confirmar(t, "fs_write_file_in_folder", "share", r, path="f.txt")
            _llamar(t, "fs_delete_in_folder", folder="share", path=".")
        eventos = [e for e in logs if e.get("event") == "folder_action"]
        assert [(e["tool"], e["folder"], e["path"], e["result"]) for e in eventos] == [
            ("fs_write_file_in_folder", "share", "f.txt", "preview"),
            ("fs_write_file_in_folder", "share", "f.txt", "ok"),
            ("fs_delete_in_folder", "share", ".", "rejected:root_protected"),
        ]
        texto = json.dumps(logs, default=str)
        assert CENTINELA not in texto
        assert hashlib.sha256(contenido.encode()).hexdigest() not in texto
        assert (base / "f.txt").exists()

    def test_estado_cambiado_queda_en_el_log(self, raices) -> None:
        base = raices["share"]
        _escribir(base / "f.txt", "a\n")
        t = _tools()
        r = _llamar(t, "fs_delete_in_folder", folder="share", path="f.txt")
        _escribir(base / "f.txt", "b\n")
        with capture_logs() as logs:
            _confirmar(t, "fs_delete_in_folder", "share", r, path="f.txt")
        assert [e["result"] for e in logs if e.get("event") == "folder_action"] == [
            "rejected:preview_outdated"]


def test_rmtree_del_modulo_es_el_de_shutil() -> None:
    # El test de borrado a medias parchea `folders_write.shutil.rmtree`: el
    # módulo tiene que usar `shutil` por su nombre (y no un `from shutil
    # import rmtree`), o el parche no llegaría.
    assert folders_write.shutil is shutil


# ── Convergencia T048: candado y revalidación justo antes de operar ───────────


@pytest.fixture(params=["dir_fd", "ruta"])
def camino(request, monkeypatch) -> str:
    """Los dos caminos de la operación final: relativa al descriptor de la
    carpeta padre (donde el sistema lo da: Linux) y por ruta (Windows)."""
    if request.param == "dir_fd" and not folders.USAR_DIR_FD:
        pytest.skip("este sistema no da operaciones relativas a un descriptor")
    monkeypatch.setattr(folders, "USAR_DIR_FD", request.param == "dir_fd")
    return request.param


@pytest.mark.parametrize("folder", CARPETAS)
@pytest.mark.parametrize("tool", list(CASOS))
def test_los_dos_caminos_hacen_lo_previsualizado(raices, folder, tool, camino) -> None:
    base = raices[folder]
    _arbol(base)
    t = _tools()
    r = _llamar(t, tool, folder=folder, **CASOS[tool])
    c = _confirmar(t, tool, folder, r, **CASOS[tool])
    assert c.get("result") == "ok", c
    assert _efecto_hecho(tool, base)


def test_los_dos_caminos_borran_carpeta_vacia_y_symlink(raices, camino, tmp_path) -> None:
    base = raices["share"]
    (base / "vacia").mkdir()
    fuera = tmp_path / "fuera"
    _escribir(fuera / "no.txt", "no\n")
    t = _tools()
    r = _llamar(t, "fs_delete_in_folder", folder="share", path="vacia")
    assert _confirmar(t, "fs_delete_in_folder", "share", r, path="vacia")["result"] == "ok"
    assert not (base / "vacia").exists()
    _symlink(base / "enlace", fuera, dir=True)
    r = _llamar(t, "fs_delete_in_folder", folder="share", path="enlace")
    assert _confirmar(t, "fs_delete_in_folder", "share", r, path="enlace")["result"] == "ok"
    assert not os.path.lexists(base / "enlace") and (fuera / "no.txt").exists()


def _traza_de_tokens(monkeypatch) -> list[str]:
    """Parchea la comprobación del token (lo primero de una confirmación)
    para que tarde y deje traza de cuándo entra y sale cada carpeta."""
    traza: list[str] = []
    real = folders_write.resolve_confirmation_token

    async def lento(token, tool, args, **kw):
        traza.append("entra " + args["folder"])
        await asyncio.sleep(0.05)
        try:
            return await real(token, tool, args, **kw)
        finally:
            traza.append("sale " + args["folder"])

    monkeypatch.setattr(folders_write, "resolve_confirmation_token", lento)
    return traza


@pytest.mark.parametrize("folder", CARPETAS)
def test_confirmaciones_de_una_carpeta_van_de_una_en_una(raices, folder, monkeypatch) -> None:
    # Dos confirmaciones a la vez en la misma carpeta: la segunda no empieza
    # hasta que la primera acaba (de la comprobación del token a la llamada
    # al sistema).
    # Control negativo comprobado: sin `@_con_candado` las trazas se
    # entrelazan (entra, entra, sale, sale) y cae este test.
    base = raices[folder]
    _escribir(base / "a.txt", "a\n")
    _escribir(base / "b.txt", "b\n")
    t = _tools()
    previas = {n: _llamar(t, "fs_delete_in_folder", folder=folder, path=n)
               for n in ("a.txt", "b.txt")}
    traza = _traza_de_tokens(monkeypatch)

    async def dos() -> list[Any]:
        return await asyncio.gather(*(
            t["fs_delete_in_folder"](folder=folder, path=n,
                                     confirmation_token=previas[n]["confirmation_token"])
            for n in ("a.txt", "b.txt")))

    r1, r2 = asyncio.run(dos())
    assert r1["result"] == r2["result"] == "ok"
    assert traza == ["entra " + folder, "sale " + folder] * 2


def test_carpetas_distintas_no_se_esperan(raices, monkeypatch) -> None:
    for b in raices.values():
        _escribir(b / "a.txt", "a\n")
    t = _tools()
    previas = {f: _llamar(t, "fs_delete_in_folder", folder=f, path="a.txt")
               for f in CARPETAS}
    traza = _traza_de_tokens(monkeypatch)

    async def dos() -> list[Any]:
        return await asyncio.gather(*(
            t["fs_delete_in_folder"](folder=f, path="a.txt",
                                     confirmation_token=previas[f]["confirmation_token"])
            for f in CARPETAS))

    asyncio.run(dos())
    # Las dos entran antes de que salga ninguna (el orden entre ellas no
    # está garantizado).
    assert sorted(traza[:2]) == ["entra addons", "entra share"]


@pytest.mark.parametrize("tool", list(CASOS))
def test_la_ruta_que_ya_no_resuelve_igual_no_se_toca(raices, tool, monkeypatch, camino) -> None:
    # T048, independiente del sistema operativo: si al revalidar (en el hilo,
    # justo antes de la llamada al sistema) la ruta resuelve a otra cosa, no
    # se hace nada y la respuesta es `path_changed`. Se simula que la
    # resolución cambia DESPUÉS de las comprobaciones de la tool, en
    # `revalidar`, que es lo que llama la operación final.
    # Control negativo comprobado: sin `folders.revalidar` en las cuatro
    # operaciones se hace la operación y caen las cuatro variantes.
    base = raices["share"]
    _arbol(base)
    t = _tools()
    r = _llamar(t, tool, folder="share", **CASOS[tool])
    antes = _foto(base)
    reales = {True: folders.normalizar, False: folders.normalizar_sin_seguir}
    revalidar_real = folders.revalidar

    def revalidar_con_cambio(folder, rel, p, *, seguir):
        with monkeypatch.context() as m:
            # Durante la revalidación, la ruta resuelve a otro sitio (como si
            # una carpeta intermedia hubiera cambiado).
            m.setattr(folders, "normalizar",
                      lambda f, q: reales[True](f, q).parent / "otra")
            m.setattr(folders, "normalizar_sin_seguir",
                      lambda f, q: reales[False](f, q).parent / "otra")
            return revalidar_real(folder, rel, p, seguir=seguir)

    monkeypatch.setattr(folders, "revalidar", revalidar_con_cambio)
    c = _confirmar(t, tool, "share", r, **CASOS[tool])
    assert c.get("error") == "path_changed", c
    assert _foto(base) == antes


def test_carrera_con_symlink_intermedio_no_borra_fuera(raices, tmp_path, monkeypatch, camino) -> None:
    # T048 de verdad (symlinks: en el CI de Linux): entre la validación y el
    # borrado otra operación cambia una carpeta intermedia por un symlink
    # que apunta fuera. El `rmtree` no lo sigue: `path_changed` y lo de
    # fuera, intacto. Control negativo en el CI (rama desechable): sin
    # revalidar y sin `dir_fd`, se borraba `fuera/y`.
    base = raices["share"]
    _escribir(base / "x" / "y" / "dentro.txt", "d\n")
    fuera = tmp_path / "fuera"
    _escribir(fuera / "y" / "valioso.txt", "v\n")
    _symlink(tmp_path / "prueba_enlace", fuera, dir=True)
    os.unlink(tmp_path / "prueba_enlace")
    t = _tools()
    r = _llamar(t, "fs_delete_in_folder", folder="share", path="x/y", recursive=True)
    assert "confirmation_token" in r
    real = folders_write.resolve_confirmation_token

    async def con_cambio(token, tool, args, **kw):
        os.rename(base / "x", base / "x_old")
        os.symlink(fuera, base / "x", target_is_directory=True)
        return await real(token, tool, args, **kw)

    monkeypatch.setattr(folders_write, "resolve_confirmation_token", con_cambio)
    c = _confirmar(t, "fs_delete_in_folder", "share", r, path="x/y", recursive=True)
    assert (fuera / "y" / "valioso.txt").exists(), c
    assert c.get("error") == "path_changed", c


# ── Convergencia T049: solo se sobrescriben ficheros regulares ────────────────


def _lstat_fifo(m, objetivo: pathlib.Path) -> None:
    import stat as stat_mod

    real = os.lstat

    def falso(p, *a, **k):
        st = real(p, *a, **k)
        if pathlib.Path(p) == objetivo:
            campos = list(st)
            campos[0] = stat_mod.S_IFIFO | 0o644
            return os.stat_result(campos)
        return st

    m.setattr(folders.os, "lstat", falso)


@pytest.mark.parametrize("folder", CARPETAS)
def test_escribir_sobre_algo_no_regular(raices, folder, monkeypatch) -> None:
    # Independiente del sistema operativo: un `lstat` que dice FIFO →
    # `not_regular_file` sin token en la vista previa y, si aparece entre la
    # vista previa y la confirmación, al confirmar, sin escribir.
    # Control negativo comprobado: sin `exigir_regular_o_ausente` en
    # `comprobar` y en `escribir` caen las dos variantes.
    base = raices[folder]
    _escribir(base / "fifo", "x\n")
    t = _tools()
    r = _llamar(t, "fs_write_file_in_folder", folder=folder, path="fifo", content="y\n")
    assert "confirmation_token" in r
    huella_real = folders.huella
    de_antes = huella_real(base / "fifo")
    with monkeypatch.context() as m:
        _lstat_fifo(m, base / "fifo")
        sin = _llamar(t, "fs_write_file_in_folder", folder=folder, path="fifo", content="y\n")
        assert sin["error"] == "not_regular_file" and "confirmation_token" not in sin
        # Que aparezca DESPUÉS de calcular la huella del token (si no, la
        # huella ya cambia y es `preview_outdated`, que también protege).
        m.setattr(folders, "huella",
                  lambda q: de_antes if q == base / "fifo" else huella_real(q))
        escritos: list[Any] = []
        m.setattr(folders_write, "safe_write_file", lambda *a: escritos.append(a))
        c = _confirmar(t, "fs_write_file_in_folder", folder, r, path="fifo")
        assert c["error"] == "not_regular_file" and escritos == []
    assert _leido(base / "fifo") == b"x\n"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="sin FIFO en este sistema")
def test_escribir_sobre_un_fifo_real_no_bloquea(raices) -> None:
    # En Linux (CI): `safe_write_file` leía el original y se bloqueaba en un
    # FIFO sin escritor. Si vuelve a bloquear, falla por tiempo y el
    # `finally` desbloquea el hilo. Control negativo en el CI (rama
    # desechable).
    f = raices["share"] / "snapfifo"
    os.mkfifo(f)
    t = _tools()

    async def escribir() -> Any:
        return await asyncio.wait_for(t["fs_write_file_in_folder"](
            folder="share", path="snapfifo", content="x\n"), 5)

    try:
        r = asyncio.run(escribir())
    finally:
        try:
            os.close(os.open(f, os.O_WRONLY | os.O_NONBLOCK))
        except OSError:
            pass
    assert r["error"] == "not_regular_file"
