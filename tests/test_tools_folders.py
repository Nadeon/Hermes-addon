"""Tools de lectura de /addons y /share (spec 034, tramo 1: T012).

`fs_list_dir_in_folder`, `fs_stat_in_folder` y `fs_read_file_in_folder`, en
las dos carpetas, con ficheros REALES en raíces temporales
(`folders.ADDONS_BASE` y `folders.SHARE_BASE` parcheadas) y un Supervisor
simulado con la forma de 2026.11.0 (`GET /addons` → `{"addons": [{"slug":
…}]}`, research R-4). Datos ficticios: `ejemplo`, `local_ejemplo`,
`centinela-clave-1`.

Independencia del sistema operativo: los symlinks se crean con un ayudante
que hace `skip` si el sistema operativo no lo permite (corren en el CI de
Linux); el byte nulo lo rechaza `folders` antes de `resolve()`; los
ficheros se escriben con `newline=""` para que Windows no convierta los
saltos de línea.

Controles negativos comprobados (T015, recuentos en el commit del tramo):
(c) siguiendo symlinks en el listado → cae `TestSymlinks`
(`test_listar_no_sigue`, en Linux); (e) sin `blacklisted_name` en la lectura →
caen los tres de lectura de `TestListaNegra`.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
from typing import Any

import pytest
from structlog.testing import capture_logs

from hermes import folders
from hermes.ha import HAConnectionError
from hermes.tools import folders as tools_folders
from hermes.tools._common import tam_json

CARPETAS = ["addons", "share"]


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


def _symlink(enlace: pathlib.Path, destino: os.PathLike | str, *, dir: bool = False) -> None:
    try:
        os.symlink(destino, enlace, target_is_directory=dir)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"el sistema operativo no deja crear symlinks: {exc}")


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
    tools_folders.register(mcp, supervisor or SupervisorSimulado(),
                           response_max_bytes=response_max_bytes)
    return mcp.tools


def _llamar(tools: dict[str, Any], nombre: str, **kwargs: Any) -> Any:
    return asyncio.run(tools[nombre](**kwargs))


# ── Listar ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("folder", CARPETAS)
class TestListar:
    def test_sobre_y_tipos(self, raices, folder) -> None:
        base = raices[folder]
        (base / "configs").mkdir()
        (base / "configs" / "app.yaml").write_text("a: 1\n", encoding="utf-8", newline="")
        (base / "z.txt").write_text("hola", encoding="utf-8", newline="")
        r = _llamar(_tools(), "fs_list_dir_in_folder", folder=folder)
        assert r["folder"] == folder and r["path"] == "."
        assert r["truncated"] is False
        assert r["count"] == len(r["items"]) == 2
        assert [i["name"] for i in r["items"]] == ["configs", "z.txt"]
        dir_, fich = r["items"]
        assert dir_["type"] == "dir" and dir_["size_bytes"] is None
        assert fich == {"name": "z.txt", "type": "file", "size_bytes": 4,
                        "modified": fich["modified"], "is_blacklisted": False}
        assert fich["modified"].endswith("+00:00")
        # Las claves del sobre van al final, la cabecera delante.
        assert list(r)[-3:] == ["count", "items", "truncated"]

    def test_recursivo_hasta_max_depth(self, raices, folder) -> None:
        base = raices[folder]
        (base / "a" / "b" / "c" / "d").mkdir(parents=True)
        (base / "a" / "b" / "c" / "d" / "hondo.txt").write_text("x", encoding="utf-8", newline="")
        t = _tools()
        r = _llamar(t, "fs_list_dir_in_folder", folder=folder, recursive=True, max_depth=2)
        assert [i["name"] for i in r["items"]] == ["a", "a/b"]
        r = _llamar(t, "fs_list_dir_in_folder", folder=folder, recursive=True, max_depth=99)
        # Tope 3 aunque se pida más.
        assert [i["name"] for i in r["items"]] == ["a", "a/b", "a/b/c"]
        r = _llamar(t, "fs_list_dir_in_folder", folder=folder, path="a/b/c", recursive=True)
        assert [i["name"] for i in r["items"]] == ["d", "d/hondo.txt"]
        assert r["path"] == "a/b/c"

    def test_quinientas_como_mucho(self, raices, folder) -> None:
        base = raices[folder]
        for i in range(501):
            (base / f"f{i:03d}").write_text("", encoding="utf-8", newline="")
        r = _llamar(_tools(), "fs_list_dir_in_folder", folder=folder)
        assert r["count"] == 500 and r["truncated"] is True
        assert "500" in r["hint"]

    def test_rechazos(self, raices, folder) -> None:
        base = raices[folder]
        (base / "f.txt").write_text("", encoding="utf-8", newline="")
        t = _tools()
        assert _llamar(t, "fs_list_dir_in_folder", folder=folder,
                       path="no")["error"] == "not_found"
        assert _llamar(t, "fs_list_dir_in_folder", folder=folder,
                       path="f.txt")["error"] == "not_a_directory"
        assert _llamar(t, "fs_list_dir_in_folder", folder=folder,
                       path="../")["error"] == "traversal"

    def test_ruta_absoluta_con_alias(self, raices, folder) -> None:
        (raices[folder] / "sub").mkdir()
        (raices[folder] / "sub" / "x").write_text("", encoding="utf-8", newline="")
        r = _llamar(_tools(), "fs_list_dir_in_folder", folder=folder, path=f"/{folder}/sub")
        assert r["path"] == "sub" and [i["name"] for i in r["items"]] == ["x"]


# ── Stat ──────────────────────────────────────────────────────────────────────


class TestStat:
    @pytest.mark.parametrize("folder", CARPETAS)
    def test_fichero_y_carpeta(self, raices, folder) -> None:
        base = raices[folder]
        (base / "d").mkdir()
        (base / "d" / "f.txt").write_text("abc", encoding="utf-8", newline="")
        sup = SupervisorSimulado()
        t = _tools(sup)
        r = _llamar(t, "fs_stat_in_folder", folder=folder, path="d/f.txt")
        assert r == {"folder": folder, "path": "d/f.txt", "type": "file", "size_bytes": 3,
                     "modified": r["modified"], "is_blacklisted": False,
                     "is_mount_point": False}
        r = _llamar(t, "fs_stat_in_folder", folder=folder, path="d")
        assert r["type"] == "dir" and r["size_bytes"] is None and "app" not in r
        r = _llamar(t, "fs_stat_in_folder", folder=folder, path=".")
        assert r["path"] == "." and r["type"] == "dir"
        assert _llamar(t, "fs_stat_in_folder", folder=folder,
                       path="no")["error"] == "not_found"
        # Ninguna de estas es la carpeta de una app: el Supervisor ni se entera.
        assert sup.llamadas == []

    def test_punto_de_montaje(self, raices, monkeypatch) -> None:
        nas = raices["share"] / "nas"
        nas.mkdir()
        monkeypatch.setattr(folders, "es_punto_de_montaje",
                            lambda p: pathlib.Path(p) == nas)
        r = _llamar(_tools(), "fs_stat_in_folder", folder="share", path="nas")
        assert r["is_mount_point"] is True

    @staticmethod
    def _app(base: pathlib.Path) -> None:
        (base / "ejemplo").mkdir()
        (base / "ejemplo" / "config.yaml").write_text(
            "name: Ejemplo\nslug: ejemplo\nversion: '1.0'\n", encoding="utf-8", newline="")
        (base / "ejemplo" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8", newline="")

    def test_app_instalada(self, raices) -> None:
        self._app(raices["addons"])
        sup = SupervisorSimulado({"addons": [_instalada("local_ejemplo"),
                                             _instalada("core_mosquitto")]})
        r = _llamar(_tools(sup), "fs_stat_in_folder", folder="addons", path="ejemplo")
        assert r["app"] == {"slug": "local_ejemplo", "installed": True}
        assert sup.llamadas == [("GET", "/addons")]

    def test_app_no_instalada(self, raices) -> None:
        self._app(raices["addons"])
        sup = SupervisorSimulado({"addons": [_instalada("core_mosquitto")]})
        r = _llamar(_tools(sup), "fs_stat_in_folder", folder="addons", path="ejemplo")
        assert r["app"] == {"slug": "local_ejemplo", "installed": False}

    @pytest.mark.parametrize("respuesta", [HAConnectionError("caído"), ["no", "dict"],
                                           {"sin": "addons"}])
    def test_supervisor_sin_respuesta_util(self, raices, respuesta) -> None:
        self._app(raices["addons"])
        r = _llamar(_tools(SupervisorSimulado(respuesta)), "fs_stat_in_folder",
                    folder="addons", path="ejemplo")
        assert r["app"] == {"slug": "local_ejemplo", "installed": None}

    def test_sin_app_fuera_de_la_carpeta_de_la_app(self, raices) -> None:
        self._app(raices["addons"])
        sup = SupervisorSimulado({"addons": [_instalada("local_ejemplo")]})
        t = _tools(sup)
        for ruta in (".", "ejemplo/Dockerfile", "ejemplo/config.yaml"):
            assert "app" not in _llamar(t, "fs_stat_in_folder", folder="addons", path=ruta)
        assert sup.llamadas == []

    def test_nunca_app_en_share(self, raices) -> None:
        self._app(raices["share"])
        sup = SupervisorSimulado({"addons": [_instalada("local_ejemplo")]})
        r = _llamar(_tools(sup), "fs_stat_in_folder", folder="share", path="ejemplo")
        assert "app" not in r
        assert sup.llamadas == []


# ── Leer ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("folder", CARPETAS)
class TestLeer:
    def test_por_lineas(self, raices, folder) -> None:
        f = raices[folder] / "f.txt"
        f.write_bytes(b"".join(f"linea {i}\n".encode() for i in range(10)))
        t = _tools()
        r = _llamar(t, "fs_read_file_in_folder", folder=folder, path="f.txt")
        assert r["folder"] == folder and r["path"] == "f.txt"
        assert r["encoding"] == "utf-8" and r["total_lines"] == 10
        assert r["returned_lines"] == 10 and r["truncated"] is False
        assert r["lines"][0] == "linea 0\n" and "next_offset" not in r
        r = _llamar(t, "fs_read_file_in_folder", folder=folder, path="f.txt",
                    offset=3, limit=4)
        assert r["lines"] == [f"linea {i}\n" for i in range(3, 7)]
        assert r["truncated"] is True and r["next_offset"] == 7 and r["hint"]
        r = _llamar(t, "fs_read_file_in_folder", folder=folder, path="f.txt",
                    offset=7, limit=4)
        assert r["returned_lines"] == 3 and r["truncated"] is False
        r = _llamar(t, "fs_read_file_in_folder", folder=folder, path="f.txt", offset=50)
        assert r["lines"] == [] and r["truncated"] is False

    def test_tope_de_limit(self, raices, folder) -> None:
        f = raices[folder] / "largo.txt"
        f.write_text("x\n" * 6000, encoding="utf-8", newline="")
        r = _llamar(_tools(), "fs_read_file_in_folder", folder=folder,
                    path="largo.txt", limit=99999)
        assert r["returned_lines"] == 5000 and r["next_offset"] == 5000

    def test_finales_de_linea(self, raices, folder) -> None:
        # Las mismas fronteras que `splitlines(keepends=True)`.
        contenido = "a\r\nb\rc\nd"
        (raices[folder] / "f.txt").write_bytes(contenido.encode())
        r = _llamar(_tools(), "fs_read_file_in_folder", folder=folder, path="f.txt")
        assert r["lines"] == contenido.splitlines(keepends=True)

    def test_crlf_partido_entre_bloques(self, raices, folder) -> None:
        # Un `\r\n` que cae justo en la frontera de 1 MiB es UNA línea.
        cuerpo = b"x" * (1024 * 1024 - 1) + b"\r\n" + b"y\n"
        (raices[folder] / "f.txt").write_bytes(cuerpo)
        r = _llamar(_tools(response_max_bytes=4 * 1024 * 1024),
                    "fs_read_file_in_folder", folder=folder, path="f.txt")
        assert r["total_lines"] == 2
        assert r["lines"][1] == "y\n"

    @pytest.mark.parametrize("contar", [True, False])
    def test_linea_gigante_sin_cargar_el_fichero(self, raices, folder, monkeypatch,
                                                 contar) -> None:
        # Convergencia T045: un fichero de una sola línea (un minificado, un
        # volcado) no se carga entero: se guarda solo lo que cabe en la
        # respuesta más un bloque. Con `contar=False` el fichero pasa del
        # umbral de `total_lines` y la lectura para en cuanto la página está
        # llena, sin llegar al final de la línea.
        # Control negativo comprobado: sin el tope de lo que se guarda de la
        # línea (`sitio` ilimitado en `_trozo`, como antes, que acumulaba la
        # línea entera) el pico pasa de 1 MiB y caen las cuatro variantes.
        import tracemalloc

        monkeypatch.setattr(tools_folders, "TAM_BLOQUE", 64 * 1024)
        monkeypatch.setattr(tools_folders, "TOTAL_LINES_MAX_BYTES",
                            8 * 1024 * 1024 if contar else 1024)
        f = raices[folder] / "min.js"
        with open(f, "wb") as fh:
            for _ in range(64):
                fh.write(b"a" * (64 * 1024))
        tamano = 64 * 64 * 1024
        tracemalloc.start()
        try:
            leido = tools_folders._leer_lineas(f, 0, 10, 8192)
            _, pico = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert pico < 1024 * 1024, pico
        assert leido["lines"] == ["a" * 8192]
        assert leido["cut_lines"] == [{"line": 0, "returned_chars": 8192,
                                       "line_chars": tamano if contar else None}]
        r = _llamar(_tools(response_max_bytes=8192), "fs_read_file_in_folder",
                    folder=folder, path="min.js")
        assert tam_json(r) <= 8192
        assert r["returned_lines"] == 1
        # Sin leer hasta el final no se sabe si hay más líneas: se dice.
        assert r.get("next_offset") == (None if contar else 1)
        [corte] = r["cut_lines"]
        assert corte["line"] == 0 and corte["returned_chars"] == len(r["lines"][0]) > 7000
        assert corte["line_chars"] == (tamano if contar else None)
        assert r["truncated"] is (not contar)
        assert "cut" in r["hint"]

    def test_solo_la_primera_de_la_pagina_se_corta(self, raices, folder) -> None:
        # Una línea larga que no es la primera no se corta: la página acaba
        # antes de ella y la siguiente llamada empieza por ella.
        (raices[folder] / "f.txt").write_bytes(b"a\n" + b"b" * 20000 + b"\nc\n")
        t = _tools(response_max_bytes=4096)
        r = _llamar(t, "fs_read_file_in_folder", folder=folder, path="f.txt")
        assert r["lines"] == ["a\n"] and r["next_offset"] == 1 and "cut_lines" not in r
        r = _llamar(t, "fs_read_file_in_folder", folder=folder, path="f.txt", offset=1)
        assert r["returned_lines"] == 1 and r["lines"][0].startswith("bbb")
        assert r["cut_lines"][0]["line"] == 1 and r["cut_lines"][0]["line_chars"] == 20001
        assert r["truncated"] is True and r["next_offset"] == 2
        r = _llamar(t, "fs_read_file_in_folder", folder=folder, path="f.txt", offset=2)
        assert r["lines"] == ["c\n"] and r["truncated"] is False

    def test_fronteras_con_bloques_pequenos(self, raices, folder, monkeypatch) -> None:
        # Con bloques de 3 bytes, cualquier fin de línea (y `\r\n`) cae
        # partido entre dos bloques: las fronteras siguen siendo las de
        # `splitlines(keepends=True)`.
        monkeypatch.setattr(tools_folders, "TAM_BLOQUE", 3)
        contenido = "a\r\nbb\rcc\r\r\nd\x0be\x85f ñ\n\n\rg"
        (raices[folder] / "f.txt").write_bytes(contenido.encode("utf-8"))
        r = _llamar(_tools(), "fs_read_file_in_folder", folder=folder, path="f.txt")
        assert r["lines"] == contenido.splitlines(keepends=True)
        assert r["total_lines"] == len(contenido.splitlines())

    def test_no_regular_sin_abrirlo(self, raices, folder, monkeypatch) -> None:
        # Convergencia T049, independiente del sistema operativo: un `lstat`
        # que dice FIFO → `not_regular_file`, y el fichero ni se abre.
        # Control negativo comprobado: sin las dos comprobaciones de
        # `_abrir_regular` (`lstat` y `fstat`) caen las dos variantes.
        import stat as stat_mod

        f = raices[folder] / "snapfifo"
        f.write_bytes(b"x\n")
        lstat_real, open_real = os.lstat, os.open
        abiertos: list[str] = []

        def lstat_falso(p, *a, **k):
            st = lstat_real(p, *a, **k)
            if pathlib.Path(p) == f:
                campos = list(st)
                campos[0] = stat_mod.S_IFIFO | 0o644
                return os.stat_result(campos)
            return st

        def open_espia(p, *a, **k):
            abiertos.append(str(p))
            return open_real(p, *a, **k)

        monkeypatch.setattr(tools_folders.os, "lstat", lstat_falso)
        monkeypatch.setattr(tools_folders.os, "open", open_espia)
        r = _llamar(_tools(), "fs_read_file_in_folder", folder=folder, path="snapfifo")
        assert r["error"] == "not_regular_file" and r["path"] == "snapfifo"
        assert str(f) not in abiertos

    @pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="sin FIFO en este sistema")
    def test_fifo_real_no_bloquea(self, raices, folder) -> None:
        # Convergencia T049 en Linux (CI): un FIFO sin escritor bloqueaba
        # `open(O_RDONLY)` para siempre. Si vuelve a bloquear, el test falla
        # por tiempo y el `finally` desbloquea el hilo abriendo el otro lado.
        f = raices[folder] / "snapfifo"
        os.mkfifo(f)
        t = _tools()

        async def leer() -> Any:
            return await asyncio.wait_for(
                t["fs_read_file_in_folder"](folder=folder, path="snapfifo"), 5)

        try:
            r = asyncio.run(leer())
        finally:
            try:
                fd = os.open(f, os.O_WRONLY | os.O_NONBLOCK)
                os.close(fd)
            except OSError:
                # Solo desbloquea al hilo si sigue esperando: sin lector
                # (ENXIO) es que ya terminó, y el resultado lo mira el assert.
                pass
        assert r["error"] == "not_regular_file"

    def test_total_lines_null_por_encima_del_umbral(self, raices, folder, monkeypatch) -> None:
        monkeypatch.setattr(tools_folders, "TOTAL_LINES_MAX_BYTES", 10)
        (raices[folder] / "f.txt").write_text("".join(f"{i}\n" for i in range(100)),
                                              encoding="utf-8", newline="")
        r = _llamar(_tools(), "fs_read_file_in_folder", folder=folder, path="f.txt", limit=5)
        assert r["total_lines"] is None
        assert r["lines"] == [f"{i}\n" for i in range(5)] and r["next_offset"] == 5

    def test_binario(self, raices, folder) -> None:
        (raices[folder] / "foto.jpg").write_bytes(b"\xff\xd8\x00centinela-clave-1" * 10)
        r = _llamar(_tools(), "fs_read_file_in_folder", folder=folder, path="foto.jpg")
        assert r == {"folder": folder, "path": "foto.jpg", "size_bytes": 200,
                     "binary": True, "content": None,
                     "hint": "Binary file: only metadata is returned."}

    def test_latin1_y_bom(self, raices, folder) -> None:
        (raices[folder] / "l1.txt").write_bytes("año\n".encode("latin-1"))
        (raices[folder] / "bom.txt").write_bytes(b"\xef\xbb\xbfhola\n")
        t = _tools()
        r = _llamar(t, "fs_read_file_in_folder", folder=folder, path="l1.txt")
        assert r["encoding"] == "latin-1" and r["lines"] == ["año\n"]
        r = _llamar(t, "fs_read_file_in_folder", folder=folder, path="bom.txt")
        assert r["encoding"] == "utf-8-bom" and r["lines"] == ["hola\n"]

    def test_rechazos(self, raices, folder) -> None:
        (raices[folder] / "d").mkdir()
        t = _tools()
        assert _llamar(t, "fs_read_file_in_folder", folder=folder,
                       path="d")["error"] == "is_directory"
        assert _llamar(t, "fs_read_file_in_folder", folder=folder,
                       path="no.txt")["error"] == "not_found"


# ── Lista negra ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("folder", CARPETAS)
class TestListaNegra:
    NOMBRES = ["secrets.yaml", "x.pem", "mi_token.txt", "datos.db", "cert.key"]

    def _poblar(self, base: pathlib.Path) -> None:
        (base / "sub").mkdir()
        for nombre in self.NOMBRES:
            (base / "sub" / nombre).write_text("centinela-clave-1\n", encoding="utf-8", newline="")
        (base / "sub" / "ok.yaml").write_text("ok: 1\n", encoding="utf-8", newline="")

    def test_leer_se_rechaza(self, raices, folder) -> None:
        self._poblar(raices[folder])
        t = _tools()
        for nombre in self.NOMBRES:
            r = _llamar(t, "fs_read_file_in_folder", folder=folder, path=f"sub/{nombre}")
            assert r["error"] == "blacklisted", nombre
            assert "centinela" not in json.dumps(r)

    def test_listar_y_stat_los_marcan(self, raices, folder) -> None:
        self._poblar(raices[folder])
        t = _tools()
        r = _llamar(t, "fs_list_dir_in_folder", folder=folder, path="sub")
        marcas = {i["name"]: i["is_blacklisted"] for i in r["items"]}
        assert marcas == {**{n: True for n in self.NOMBRES}, "ok.yaml": False}
        assert _llamar(t, "fs_stat_in_folder", folder=folder,
                       path="sub/secrets.yaml")["is_blacklisted"] is True

    def test_el_resto_se_lee_sin_redactar(self, raices, folder) -> None:
        # Como `fs_read_file`: la protección es por nombre (research R-5).
        (raices[folder] / "notas.txt").write_text("clave: centinela-clave-1\n",
                                                  encoding="utf-8", newline="")
        r = _llamar(_tools(), "fs_read_file_in_folder", folder=folder, path="notas.txt")
        assert r["lines"] == ["clave: centinela-clave-1\n"]

    def test_reglas_de_directorio_de_config_no_aplican(self, raices, folder) -> None:
        (raices[folder] / "deps").mkdir()
        (raices[folder] / "deps" / "x.txt").write_text("x\n", encoding="utf-8", newline="")
        r = _llamar(_tools(), "fs_read_file_in_folder", folder=folder, path="deps/x.txt")
        assert r["lines"] == ["x\n"]


# ── Symlinks, rutas y carpeta no disponible ───────────────────────────────────


_TRES = {
    "fs_list_dir_in_folder": {},
    "fs_stat_in_folder": {},
    "fs_read_file_in_folder": {},
}


@pytest.mark.parametrize("folder", CARPETAS)
class TestSymlinks:
    def test_listar_no_sigue(self, raices, folder, tmp_path) -> None:
        base = raices[folder]
        otra = tmp_path / "otra"
        otra.mkdir()
        (otra / "dentro.txt").write_text("x", encoding="utf-8", newline="")
        _symlink(base / "enlace", otra, dir=True)
        r = _llamar(_tools(), "fs_list_dir_in_folder", folder=folder, recursive=True)
        assert [(i["name"], i["type"]) for i in r["items"]] == [("enlace", "symlink")]

    def test_leer_por_un_enlace_de_dentro(self, raices, folder) -> None:
        base = raices[folder]
        (base / "real.txt").write_text("hola\n", encoding="utf-8", newline="")
        _symlink(base / "enlace.txt", base / "real.txt")
        r = _llamar(_tools(), "fs_read_file_in_folder", folder=folder, path="enlace.txt")
        assert r["lines"] == ["hola\n"] and r["path"] == "real.txt"

    def test_enlace_hacia_fuera_es_traversal(self, raices, folder, tmp_path) -> None:
        base = raices[folder]
        fuera = tmp_path / "fuera"
        fuera.mkdir()
        (fuera / "f.txt").write_text("centinela-clave-1\n", encoding="utf-8", newline="")
        _symlink(base / "escape", fuera, dir=True)
        t = _tools()
        for nombre, ruta in (("fs_list_dir_in_folder", "escape"),
                             ("fs_stat_in_folder", "escape/f.txt"),
                             ("fs_read_file_in_folder", "escape/f.txt")):
            r = _llamar(t, nombre, folder=folder, path=ruta)
            assert r["error"] == "traversal", nombre
            assert "centinela" not in json.dumps(r)


@pytest.mark.parametrize("folder", CARPETAS)
@pytest.mark.parametrize("tool", list(_TRES))
class TestRutasEnLasTres:
    @pytest.mark.parametrize("ruta", ["../x", "a\x00b", "a%00b", "/etc/passwd",
                                      "/config/configuration.yaml"])
    def test_traversal(self, raices, folder, tool, ruta) -> None:
        r = _llamar(_tools(), tool, folder=folder, path=ruta)
        assert r["error"] == "traversal", r

    def test_la_otra_carpeta(self, raices, folder, tool) -> None:
        otra = "share" if folder == "addons" else "addons"
        (raices[otra] / "x").write_text("", encoding="utf-8", newline="")
        r = _llamar(_tools(), tool, folder=folder, path=f"/{otra}/x")
        assert r["error"] == "traversal"


@pytest.mark.parametrize("tool", list(_TRES))
class TestCarpetaNoDisponible:
    def test_raiz_inexistente(self, raices, tool, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(folders, "SHARE_BASE", tmp_path / "sin_montar")
        r = _llamar(_tools(), tool, folder="share", path="x")
        assert r["error"] == "folder_unavailable"

    @pytest.mark.parametrize("folder", ["config", "", "ADDONS", "media"])
    def test_carpeta_invalida(self, raices, tool, folder) -> None:
        r = _llamar(_tools(), tool, folder=folder, path="x")
        assert r["error"] == "invalid_argument"


# ── Tope de respuesta ─────────────────────────────────────────────────────────


class TestTopeDeRespuesta:
    def test_leer_recorta_y_da_next_offset(self, raices) -> None:
        (raices["share"] / "f.txt").write_text(
            "".join(f"{i:04d} " + "x" * 90 + "\n" for i in range(200)), encoding="utf-8", newline="")
        tope = 4000
        r = _llamar(_tools(response_max_bytes=tope), "fs_read_file_in_folder",
                    folder="share", path="f.txt")
        assert tam_json(r) <= tope
        assert 0 < r["returned_lines"] < 200
        assert r["truncated"] is True and r["next_offset"] == r["returned_lines"]
        assert r["total_lines"] == 200
        # La página siguiente empieza donde dijo.
        r2 = _llamar(_tools(response_max_bytes=tope), "fs_read_file_in_folder",
                     folder="share", path="f.txt", offset=r["next_offset"])
        assert r2["lines"][0].startswith(f"{r['next_offset']:04d} ")

    def test_listar_recorta_con_el_sobre(self, raices) -> None:
        for i in range(100):
            (raices["addons"] / f"fichero_con_nombre_largo_{i:03d}.txt").write_text(
                "", encoding="utf-8", newline="")
        tope = 3000
        r = _llamar(_tools(response_max_bytes=tope), "fs_list_dir_in_folder", folder="addons")
        assert tam_json(r) <= tope
        assert r["truncated"] is True and 0 < r["count"] == len(r["items"]) < 100
        assert r["hint"]


# ── Log ───────────────────────────────────────────────────────────────────────


class TestLog:
    def test_folder_action_sin_contenido(self, raices) -> None:
        (raices["share"] / "notas.txt").write_text("centinela-clave-1\n", encoding="utf-8", newline="")
        t = _tools()
        with capture_logs() as logs:
            _llamar(t, "fs_read_file_in_folder", folder="share", path="notas.txt")
            _llamar(t, "fs_read_file_in_folder", folder="share", path="../x")
        eventos = [e for e in logs if e.get("event") == "folder_action"]
        assert [(e["tool"], e["folder"], e["path"], e["result"]) for e in eventos] == [
            ("fs_read_file_in_folder", "share", "notas.txt", "ok"),
            ("fs_read_file_in_folder", "share", "../x", "rejected:traversal"),
        ]
        assert "centinela" not in json.dumps(logs, default=str)
