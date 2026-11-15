"""Convergencia 4 de la spec 034 (T060–T063), tras la tercera verificación
independiente.

- T060 (N1): fail-closed simétrico. Si el `utils.get_latest_mtime` del
  Supervisor 2026.11.0 lanza (relanza todo `OSError` salvo `ENOENT` y
  `ELOOP`), `RepositoryLocal.update` lo convierte en
  `StoreRepositoryUnknownError` y `StoreManager.reload` se lo traga
  (`asyncio.gather(..., return_exceptions=True)`): la recarga responde bien
  SIN releer las apps locales, y Hermes la anotaba. Ahora el recorrido de
  Hermes rechaza (`store_copy_stale`, con el motivo) ante cualquier error o
  entrada que pueda hacer fallar el del Supervisor, y las tools que crean o
  mueven en /addons rechazan una ruta demasiado larga (`path_too_long`).

`/addons` es una carpeta temporal con ficheros reales. Lo que solo pasa en
Linux (symlinks reales, `ENOTDIR`, `ELOOP`, `PATH_MAX`) se salta donde el
sistema operativo no lo permite y corre en el CI de Linux; lo demás se
simula de forma independiente del sistema operativo. Los controles
negativos comprobados están en cada clase.
"""

from __future__ import annotations

import asyncio
import errno
import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from hermes import folders
from hermes.tools import _store
from hermes.tools import folders_write
from tests.test_convergencia_3_034 import _PRIVILEGIADO, SupervisorConFechas, _ConRecarga
from tests.test_tools_privilegios import _LOCAL, _MCP, _ConRaices

#: Un tope pequeño para los tests (el real, 3840 bytes, no se puede crear en
#: Windows): con él, `_LARGA` pasa y `_CORTA` no.
_TOPE = 120
_PREFIJO = len(folders.RAIZ_ADDONS_EN_EL_SUPERVISOR)
_CORTA = "s/" + "c" * 20 + ".txt"
_LARGA = "s/" + "l" * (_TOPE - _PREFIJO) + ".txt"


def _symlink(enlace: Path, destino: str, *, dir: bool = False) -> None:
    try:
        os.symlink(destino, enlace, target_is_directory=dir)
    except (OSError, NotImplementedError) as exc:
        raise unittest.SkipTest(f"el sistema operativo no deja crear symlinks: {exc}") from exc


class SupervisorQueTragaErrores(SupervisorConFechas):
    """Como `SupervisorConFechas`, más lo que hace el Supervisor 2026.11.0
    cuando `get_latest_mtime` lanza: la ruta, medida bajo
    `/data/apps/local/`, que pasa de su límite da `ENAMETOOLONG` en
    `path.stat()` (aquí el límite es `limite`, simulado), y la excepción
    acaba tragada en `StoreManager.reload` (`gather` con
    `return_exceptions=True`): la recarga responde `{}` sin releer."""

    def __init__(self, addons: Path, limite: int) -> None:
        super().__init__(addons)
        self.limite = limite

    def _fecha_mas_reciente(self) -> float:
        for p in self.addons.rglob("*"):
            rel = p.relative_to(self.addons).as_posix()
            if folders.bytes_en_el_supervisor(rel) >= self.limite:
                raise OSError(errno.ENAMETOOLONG, "File name too long", str(p))
        return super()._fecha_mas_reciente()

    async def sv_request(self, method: str, sv_path: str, **kw: Any) -> Any:
        if (method.upper(), sv_path) == ("POST", "/store/reload"):
            try:
                self._fecha_mas_reciente()
            except OSError:
                self.llamadas.append({"metodo": "POST", "ruta": sv_path, "json": None,
                                      "params": None, "timeout": kw.get("timeout_seconds")})
                return {}
        return await super().sv_request(method, sv_path, **kw)


# ── T060 (N1): el recorrido de Hermes falla donde falla el del Supervisor ───


class TestRutaLarga(_ConRecarga):
    """El escenario N1 de la verificación (caso G de su `f1_marca.py`).

    Control negativo comprobado: sin la comprobación de
    `demasiado_larga_para_el_supervisor` en `folders.fecha_mas_reciente`
    cae `test_escenario` (la recarga que no relee se anota y hay token con
    la copia de `SYS_ADMIN`) y `test_con_margen`."""

    def setUp(self) -> None:
        super().setUp()
        self.sv = SupervisorQueTragaErrores(self.addons, limite=_TOPE + 10)
        mcp = _MCP()
        from hermes.tools import addons as addons_mod
        from hermes.tools import store_apps as store_apps_mod
        from hermes.tools import store_repositories

        addons_mod.register(mcp, self.sv)
        store_apps_mod.register(mcp, self.sv)
        store_repositories.register(mcp, self.sv)
        self.t = mcp.tools
        from tests.test_convergencia_3_034 import _ficha_local

        self.sv.respuesta("GET", f"/store/addons/{_LOCAL}", _ficha_local())
        self.sv.respuesta("GET", f"/store/addons/{_LOCAL}/availability", {})
        self.sv.respuesta("POST", f"/store/addons/{_LOCAL}/install", {"job_id": "j1"})
        p = mock.patch.object(folders, "TOPE_RUTA_EN_EL_SUPERVISOR", _TOPE)
        p.start()
        self.addCleanup(p.stop)

    async def test_escenario(self) -> None:
        self.app_local(_PRIVILEGIADO, carpeta="s")
        r = await self.recargar()
        self.assertEqual(r.get("result"), "ok", r)
        self.assertEqual(self.sv.copia[_LOCAL]["privileged"], ["SYS_ADMIN"])
        # Se reescribe inocuo y aparece una ruta que el Supervisor no puede
        # mirar: su recarga responde bien sin releer.
        self.app_local(carpeta="s")
        largo = "s/" + "l" * (_TOPE + 20 - _PREFIJO)
        (self.addons / largo).write_text("x\n", encoding="utf-8")
        relecturas = self.sv.relecturas
        r = await self.recargar()
        self.assertEqual(r.get("result"), "ok", r)
        self.assertEqual(self.sv.relecturas, relecturas)
        self.assertEqual(self.sv.copia[_LOCAL]["privileged"], ["SYS_ADMIN"])
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r.get("error"), "store_copy_stale", r)
        self.assertNotIn("confirmation_token", r)
        self.assertIn("bytes long in the Supervisor", r["reason"])
        self.assertIn("silently stops re-reading", r["reason"])
        self.assertIn("Fix or remove", r["hint"])
        # Sin ella, la siguiente recarga relee y hay token con la copia buena.
        (self.addons / largo).unlink()
        r = await self.recargar()
        self.assertEqual(self.sv.copia[_LOCAL]["privileged"], ["NET_ADMIN"])
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertIn("confirmation_token", r, r)

    async def test_con_margen(self) -> None:
        # Por encima del tope de Hermes, aunque el Supervisor aún la lea.
        self.app_local(carpeta="s")
        (self.addons / _LARGA).write_text("x\n", encoding="utf-8")
        self.assertLess(folders.bytes_en_el_supervisor(_LARGA), self.sv.limite)
        await self.recargar()
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r.get("error"), "store_copy_stale", r)
        (self.addons / _LARGA).unlink()
        (self.addons / _CORTA).write_text("x\n", encoding="utf-8")
        await self.recargar()
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertIn("confirmation_token", r, r)


class TestNingunErrorSeIgnora(_ConRaices):
    """Control negativo comprobado: con el `contextlib.suppress(OSError)` de
    antes sobre el `stat` del destino de un symlink caen
    `test_symlink_que_pasa_por_un_fichero`, `test_symlink_roto` y
    `test_symlink_en_bucle` (en Linux, CI de la rama desechable); sin el
    `try` alrededor de `os.scandir`, `test_carpeta_que_no_se_puede_listar`
    sigue en rojo con un `PermissionError` sin motivo."""

    def setUp(self) -> None:
        super().setUp()
        self.app_local(carpeta="s")

    def recorrer(self) -> str:
        with self.assertRaises(folders.RecorridoNoFiable) as ctx:
            folders.fecha_mas_reciente(self.addons)
        self.assertIsInstance(ctx.exception, OSError)
        return ctx.exception.detail

    def test_symlink_que_pasa_por_un_fichero(self) -> None:
        # La variante de la verificación: `ln -s s/config.yaml/x z` (ENOTDIR).
        _symlink(self.addons / "z", "s/config.yaml/x")
        detalle = self.recorrer()
        self.assertIn("'z'", detalle)
        self.assertIn("target cannot be checked", detalle)
        if sys.platform.startswith("linux"):
            self.assertIn("ENOTDIR", detalle)

    def test_symlink_roto(self) -> None:
        _symlink(self.addons / "roto", "no_existe")
        detalle = self.recorrer()
        self.assertIn("'roto'", detalle)
        if sys.platform.startswith("linux"):
            self.assertIn("ENOENT", detalle)

    def test_symlink_en_bucle(self) -> None:
        _symlink(self.addons / "a", "b")
        _symlink(self.addons / "b", "a")
        detalle = self.recorrer()
        if sys.platform.startswith("linux"):
            self.assertIn("ELOOP", detalle)

    def test_symlink_que_sale_de_addons(self) -> None:
        for nombre, destino in (("absoluto", os.path.abspath(os.sep)),
                                ("relativo", "../fuera")):
            with self.subTest(caso=nombre):
                (self.addons.parent / "fuera").mkdir(exist_ok=True)
                _symlink(self.addons / nombre, destino, dir=True)
                self.assertIn("points outside /addons", self.recorrer())
                os.unlink(self.addons / nombre)

    def test_symlink_dentro_de_addons_vale(self) -> None:
        _symlink(self.addons / "enlace", "s/config.yaml")
        fecha, _ruta = folders.fecha_mas_reciente(self.addons)
        self.assertGreater(fecha, 0)

    def test_carpeta_que_no_se_puede_listar(self) -> None:
        # Independiente del sistema operativo: un `scandir` que falla con
        # `EACCES` en una subcarpeta (el `rglob` del Supervisor se la
        # saltaría en silencio y no vería sus cambios).
        real = os.scandir

        def scandir(ruta: Any) -> Any:
            if os.path.basename(os.fspath(ruta)) == "s":
                raise PermissionError(errno.EACCES, "Permission denied", ruta)
            return real(ruta)

        with mock.patch.object(folders.os, "scandir", side_effect=scandir):
            detalle = self.recorrer()
        self.assertIn("'s'", detalle)
        self.assertIn("could not be listed", detalle)
        self.assertIn("EACCES", detalle)

    def test_en_la_vista_previa(self) -> None:
        _store._ULTIMA_RECARGA = 0.0  # no se llega a mirar la fecha
        with mock.patch.object(folders, "fecha_mas_reciente",
                               side_effect=folders.RecorridoNoFiable("'x': boom (EIO)")):
            rechazo, _nota = _store.copia_de_tienda_desfasada(_LOCAL)
        self.assertEqual(rechazo["error"], "store_copy_stale")
        self.assertIn("'x': boom (EIO)", rechazo["reason"])


class TestElTope(unittest.TestCase):
    def test_tope_y_margen(self) -> None:
        self.assertEqual(folders.RAIZ_ADDONS_EN_EL_SUPERVISOR, "/data/apps/local/")
        self.assertEqual(folders.TOPE_RUTA_EN_EL_SUPERVISOR,
                         folders.PATH_MAX_LINUX - folders.MARGEN_PATH_MAX)
        self.assertEqual(folders.TOPE_RUTA_EN_EL_SUPERVISOR, 3840)
        self.assertEqual(folders.bytes_en_el_supervisor("ab/ñ"), 17 + 5)

    @unittest.skipUnless(sys.platform.startswith("linux"), "PATH_MAX de Linux")
    def test_path_max_es_el_de_linux(self) -> None:
        self.assertEqual(os.pathconf("/", "PC_PATH_MAX"), folders.PATH_MAX_LINUX)
        with self.assertRaises(OSError) as ctx:
            os.stat("/" + "a/" * (folders.PATH_MAX_LINUX // 2))
        self.assertEqual(ctx.exception.errno, errno.ENAMETOOLONG)


class TestHerramientasNoCreanRutasLargas(_ConRaices):
    """`path_too_long` sin token en /addons; en /share, no aplica.

    Control negativo comprobado: con `_larga_en_addons` devolviendo siempre
    `None` caen los tres casos de /addons (hay token)."""

    def setUp(self) -> None:
        super().setUp()
        mcp = _MCP()
        folders_write.register(mcp, SupervisorConFechas(self.addons))
        self.t = mcp.tools
        p = mock.patch.object(folders, "TOPE_RUTA_EN_EL_SUPERVISOR", _TOPE)
        p.start()
        self.addCleanup(p.stop)
        for raiz in (self.addons, self.share):
            (raiz / "s").mkdir()
            (raiz / "d" / "hondo").mkdir(parents=True)
            (raiz / "d" / "hondo" / ("h" * 40)).write_text("x\n", encoding="utf-8")

    def llamar(self, tool: str, **args: Any) -> dict[str, Any]:
        return asyncio.run(self.t[tool](**args))

    def casos(self) -> list[tuple[str, dict[str, Any]]]:
        destino = "s/" + "m" * (_TOPE - _PREFIJO - 40)
        return [
            ("fs_write_file_in_folder", {"path": _LARGA, "content": "x\n"}),
            ("fs_create_dir_in_folder", {"path": _LARGA}),
            # El destino cabe; lo que cuelga de la carpeta movida, no.
            ("fs_move_in_folder", {"src": "d", "dst": destino}),
        ]

    def test_en_addons_se_rechaza(self) -> None:
        for tool, args in self.casos():
            with self.subTest(tool=tool):
                r = self.llamar(tool, folder="addons", **args)
                self.assertEqual(r.get("error"), "path_too_long", r)
                self.assertNotIn("confirmation_token", r)
                self.assertIn("/data/apps/local/", r["detail"])

    def test_en_share_no(self) -> None:
        for tool, args in self.casos():
            with self.subTest(tool=tool):
                r = self.llamar(tool, folder="share", **args)
                self.assertIn("confirmation_token", r, r)

    def test_corta_si(self) -> None:
        r = self.llamar("fs_write_file_in_folder", folder="addons", path=_CORTA,
                        content="x\n")
        self.assertIn("confirmation_token", r, r)
        r = self.llamar("fs_move_in_folder", folder="addons", src="d", dst="e")
        self.assertIn("confirmation_token", r, r)

    def test_tambien_al_confirmar(self) -> None:
        r = self.llamar("fs_create_dir_in_folder", folder="addons", path=_CORTA)
        self.assertIn("confirmation_token", r, r)
        with mock.patch.object(folders, "TOPE_RUTA_EN_EL_SUPERVISOR", _PREFIJO + 5):
            c = self.llamar("fs_create_dir_in_folder", folder="addons", path=_CORTA,
                            confirmation_token=r["confirmation_token"])
        self.assertEqual(c.get("error"), "path_too_long", c)
        self.assertFalse((self.addons / _CORTA).exists())
