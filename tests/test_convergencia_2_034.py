"""Convergencia 2 de la spec 034 (T051–T056), tras la verificación
independiente de la primera convergencia.

- T051 (N1): `store_copy_stale` mira TODO /addons, como
  `utils.get_latest_mtime` del Supervisor 2026.11.0 (que usa
  `RepositoryLocal.update` para decidir si relee las apps locales).
- T052 (N2): las recargas de la tienda que lanza Hermes van en serie, con un
  candado común, y su inicio se toma con el candado cogido.
- T053 (N3): `sv_update_addon` enseña los privilegios, ata su token a ellos
  y, para una app local, comprueba `store_copy_stale` como instalar.
- T054 (N4): el CHANGELOG dice qué va por descriptor de carpeta y qué por
  ruta.
- T055 (N5): un `config.*` que el Supervisor descartaría
  (`store/data.py`, `_process_apps_config`; esquema en `apps/validate.py`)
  no bloquea otras apps y sale en `ignored_config_files` con su motivo.
- T056 (N6): la espera del candado de una carpeta tiene tope:
  `folder_busy` sin gastar el token.

Las fichas tienen la forma real del Supervisor 2026.11.0 (las de
`test_tools_privilegios`); `/addons` es una carpeta temporal con ficheros
reales. Los controles negativos comprobados están en cada clase.
"""

from __future__ import annotations

import ast
import asyncio
import os
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from hermes import folders
from hermes.security import CONFIRMATION_TTL_SECONDS, REDACTED_MARKER
from hermes.tools import _store
from hermes.tools import addons as addons_mod
from hermes.tools import folders_write
from hermes.tools import store_apps as store_apps_mod
from hermes.tools import store_repositories
from hermes.tools import system_updates
from hermes.tools.guide import _GUIDE
from tests.fixtures.supervisor_tienda import SupervisorSimulado
from tests.test_tools_privilegios import (
    _CONFIG_LOCAL,
    _LOCAL,
    _MCP,
    _TERCEROS,
    _ConRaices,
    ficha_extendida,
    info_instalada,
)

_RAIZ = Path(__file__).resolve().parent.parent
_HACE = 600.0


class _Tienda(_ConRaices):
    """Las tres tools que aplican la copia de la tienda, con un Supervisor
    simulado y una app local `local_ejemplo` en `/addons/ejemplo`."""

    def setUp(self) -> None:
        super().setUp()
        self.sv = SupervisorSimulado()
        mcp = _MCP()
        addons_mod.register(mcp, self.sv)
        store_apps_mod.register(mcp, self.sv)
        self.t = mcp.tools
        self.sv.respuesta("GET", f"/store/addons/{_LOCAL}",
                          ficha_extendida(_LOCAL, repository="local"))
        self.sv.respuesta("GET", f"/store/addons/{_LOCAL}/availability", {})
        self.sv.respuesta("POST", f"/store/addons/{_LOCAL}/install", {"job_id": "j1"})

    def envejecer(self, hace: float = _HACE) -> None:
        """Todo /addons (la raíz incluida) con fecha de hace `hace` s."""
        antes = time.time() - hace
        for dirpath, dirnames, filenames in os.walk(self.addons):
            for nombre in (*dirnames, *filenames):
                os.utime(Path(dirpath) / nombre, (antes, antes))
        os.utime(self.addons, (antes, antes))

    def recargada(self, hace: float = 300.0) -> None:
        _store._ULTIMA_RECARGA = time.time() - hace

    def actualizable(self, **campos: Any) -> None:
        """`local_ejemplo` instalada en 1.0.0, con la 1.1.0 en la tienda."""
        self.sv.respuesta("GET", f"/addons/{_LOCAL}/info", info_instalada(
            _LOCAL, version="1.0.0", version_latest="1.1.0", update_available=True,
            **campos))
        self.sv.respuesta("GET", f"/store/addons/{_LOCAL}", ficha_extendida(
            _LOCAL, repository="local", installed=True, version="1.0.0",
            version_latest="1.1.0"))
        self.sv.respuesta("POST", f"/store/addons/{_LOCAL}/update", {"job_id": "u1"})


# ── T051: todo /addons, como `get_latest_mtime` ───────────────────────────────


class TestTodoAddons(_Tienda):
    """Control negativo comprobado: con la comprobación de antes (solo el
    camino del `config.*`) en vez de `folders.fecha_mas_reciente(base)`,
    caen `test_dos_config_del_mismo_slug_y_se_borra_el_que_gano`,
    `test_un_cambio_en_otra_carpeta_cuenta` y
    `test_una_carpeta_oculta_tambien_cuenta`."""

    async def test_dos_config_del_mismo_slug_y_se_borra_el_que_gano(self) -> None:
        # El escenario N1: en la recarga había dos `config.*` con el mismo
        # slug (el Supervisor se queda con el último del glob, aquí el
        # privilegiado); después se borra ese y el que queda es inocuo.
        self.app_local(carpeta="s")
        malo = self.app_local(_CONFIG_LOCAL.replace("NET_ADMIN", "SYS_ADMIN"), carpeta="r")
        self.envejecer()
        self.recargada()
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r.get("error"), "store_copy_stale", r)
        self.assertIn("Several config files", r["reason"])
        malo.unlink()
        # Solo cambia la fecha de /addons/r, fuera del camino de s/config.yaml.
        for tool in ("sv_install_addon", "sv_rebuild_addon"):
            with self.subTest(tool=tool):
                if tool == "sv_rebuild_addon":
                    self.sv.respuesta("GET", f"/addons/{_LOCAL}/info", info_instalada(_LOCAL))
                r = await self.t[tool](_LOCAL)
                self.assertEqual(r.get("error"), "store_copy_stale", r)
                self.assertIn("'r'", r["reason"])
                self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras(), [])

    async def test_un_cambio_en_otra_carpeta_cuenta(self) -> None:
        self.app_local()
        (self.addons / "otra").mkdir()
        (self.addons / "otra" / "x.txt").write_text("x\n", encoding="utf-8")
        self.envejecer()
        self.recargada()
        self.assertIn("confirmation_token", await self.t["sv_install_addon"](_LOCAL))
        (self.addons / "otra" / "x.txt").write_text("y\n", encoding="utf-8")
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r.get("error"), "store_copy_stale", r)
        self.assertIn("otra/x.txt", r["reason"])

    async def test_una_carpeta_oculta_tambien_cuenta(self) -> None:
        # `get_latest_mtime` usa `rglob("*")`: no salta carpetas ocultas.
        self.app_local()
        (self.addons / "ejemplo" / ".git").mkdir()
        self.envejecer()
        self.recargada()
        (self.addons / "ejemplo" / ".git" / "HEAD").write_text("x\n", encoding="utf-8")
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r.get("error"), "store_copy_stale", r)

    async def test_sin_cambios_hay_token(self) -> None:
        self.app_local()
        (self.addons / "otra" / "sub").mkdir(parents=True)
        self.envejecer()
        self.recargada()
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertIn("confirmation_token", r)

    async def test_arbol_demasiado_grande_se_rechaza(self) -> None:
        self.app_local()
        for i in range(5):
            (self.addons / f"d{i}").mkdir()
        self.envejecer()
        self.recargada()
        with mock.patch.object(folders, "MAX_ENTRADAS", 3):
            r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r.get("error"), "store_copy_stale", r)
        self.assertIn("too large", r["reason"])
        with mock.patch.object(folders, "MAX_SEGUNDOS", 0.0):
            r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r.get("error"), "store_copy_stale", r)

    def test_fecha_mas_reciente_y_su_ruta(self) -> None:
        self.app_local()
        self.envejecer()
        os.utime(self.addons / "ejemplo" / "config.yaml", (time.time(), time.time()))
        fecha, ruta = folders.fecha_mas_reciente(self.addons)
        self.assertEqual(ruta, "ejemplo/config.yaml")
        self.assertGreater(fecha, time.time() - 60)


# ── T052: recargas en serie ───────────────────────────────────────────────────


class _Lento:
    """Supervisor que tarda en cada `POST` de recarga y deja traza."""

    def __init__(self) -> None:
        self.traza: list[tuple[str, str, float]] = []

    async def sv_request(self, metodo: str, ruta: str, **_: Any) -> Any:
        if metodo == "POST":
            self.traza.append(("entra", ruta, time.time()))
            await asyncio.sleep(0.05)
            self.traza.append(("sale", ruta, time.time()))
        return {}


class TestRecargasEnSerie(unittest.IsolatedAsyncioTestCase):
    """Control negativo comprobado: sin `async with candado_de_recarga()` en
    `sv_reload_store` caen `test_dos_recargas_a_la_vez_van_en_serie` (la
    traza se entrelaza) y `test_recargar_y_buscar_actualizaciones_comparten`."""

    def setUp(self) -> None:
        _store._ULTIMA_RECARGA = None
        self.sv = _Lento()
        mcp = _MCP()
        store_repositories.register(mcp, self.sv)
        system_updates.register(mcp, self.sv)
        self.t = mcp.tools

    async def test_dos_recargas_a_la_vez_van_en_serie(self) -> None:
        r1, r2 = await asyncio.gather(self.t["sv_reload_store"](),
                                      self.t["sv_reload_store"]())
        self.assertEqual((r1["result"], r2["result"]), ("ok", "ok"))
        self.assertEqual([p for p, _, _ in self.sv.traza], ["entra", "sale"] * 2)
        # El inicio anotado es el de la segunda, tomado con el candado ya
        # cogido: después de que la primera terminara.
        fin_de_la_primera = self.sv.traza[1][2]
        self.assertGreaterEqual(_store.ultima_recarga_de_tienda(), fin_de_la_primera)

    async def test_recargar_y_buscar_actualizaciones_comparten(self) -> None:
        await asyncio.gather(self.t["sv_reload_store"](), self.t["sv_check_for_updates"]())
        self.assertEqual([p for p, _, _ in self.sv.traza], ["entra", "sale"] * 2)

    def test_las_cuatro_vias_anotan_con_el_candado_cogido(self) -> None:
        # Por AST: cada `anotar_recarga_de_tienda(...)` de los módulos de
        # tools está dentro de un `async with candado_de_recarga()`, y hay
        # exactamente las cuatro vías (reload, check, añadir y quitar).
        vias = 0
        for modulo in ("store_repositories.py", "system_updates.py"):
            arbol = ast.parse((_RAIZ / "hermes" / "src" / "hermes" / "tools" / modulo)
                              .read_text(encoding="utf-8"))
            padres: dict[ast.AST, ast.AST] = {}
            for nodo in ast.walk(arbol):
                for hijo in ast.iter_child_nodes(nodo):
                    padres[hijo] = nodo
            for nodo in ast.walk(arbol):
                if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                        and nodo.func.id == "anotar_recarga_de_tienda"):
                    vias += 1
                    p: ast.AST | None = nodo
                    dentro = False
                    while p is not None:
                        if isinstance(p, ast.AsyncWith) and any(
                                isinstance(i.context_expr, ast.Call)
                                and getattr(i.context_expr.func, "id", "") == "candado_de_recarga"
                                for i in p.items):
                            dentro = True
                            break
                        p = padres.get(p)
                    self.assertTrue(dentro, f"{modulo}: anotar fuera del candado")
        self.assertEqual(vias, 4)


# ── T053: actualizar ──────────────────────────────────────────────────────────


class TestActualizar(_Tienda):
    """Control negativo comprobado: (a) sin `privileges` en el `estado` del
    token → cae `test_token_atado_a_los_privilegios`; (b) sin la comprobación
    en la vista previa → cae `test_local_desfasada_sin_token`; (c) sin ella
    al confirmar → cae `test_local_desfasada_al_confirmar`."""

    def setUp(self) -> None:
        super().setUp()
        self.app_local()
        self.envejecer()
        self.recargada()
        self.actualizable()

    async def test_vista_previa_con_privilegios(self) -> None:
        r = await self.t["sv_update_addon"](_LOCAL)
        self.assertIn("confirmation_token", r, r)
        priv = r["preview"]["privileges"]
        self.assertEqual(set(priv), {"store", "installed", "declared_in_folder", "elevated"})
        self.assertEqual(priv["declared_in_folder"]["config"], "ejemplo/config.yaml")
        self.assertIn("privileged", priv["elevated"])
        self.assertNotIn(REDACTED_MARKER, priv["declared_in_folder"]["note"])
        self.assertEqual(self.sv.escrituras(), [])

    async def test_otra_app_tambien_y_sin_depender_de_la_recarga(self) -> None:
        _store._ULTIMA_RECARGA = None
        self.sv.respuesta("GET", f"/addons/{_TERCEROS}/info", info_instalada(
            _TERCEROS, version="1.0.0", version_latest="1.1.0", update_available=True,
            host_network=True))
        self.sv.respuesta("GET", f"/store/addons/{_TERCEROS}", ficha_extendida(_TERCEROS))
        r = await self.t["sv_update_addon"](_TERCEROS)
        self.assertIn("confirmation_token", r, r)
        priv = r["preview"]["privileges"]
        self.assertEqual(set(priv), {"store", "installed", "elevated"})
        self.assertIn("host_network", priv["elevated"])

    async def test_sin_poder_leer_nada(self) -> None:
        from hermes.ha import HAConnectionError

        self.sv.respuesta("GET", f"/addons/{_TERCEROS}/info",
                          HAConnectionError("failed 500: boom", status=500))
        r = await self.t["sv_update_addon"](_TERCEROS)
        self.assertIn("confirmation_token", r)
        self.assertIsNone(r["preview"]["privileges"])
        self.assertIn("privileges_unavailable", r["preview"])

    async def test_token_atado_a_los_privilegios(self) -> None:
        prev = await self.t["sv_update_addon"](_LOCAL)
        self.actualizable(privileged=["SYS_ADMIN"])
        r = await self.t["sv_update_addon"](_LOCAL, confirmation_token=prev["confirmation_token"])
        self.assertIs(r.get("preview_outdated"), True, r)
        self.assertIn("privileges", r["hint"])
        self.assertEqual(self.sv.escrituras(), [])

    async def test_local_desfasada_sin_token(self) -> None:
        _store._ULTIMA_RECARGA = None
        r = await self.t["sv_update_addon"](_LOCAL)
        self.assertEqual(r.get("error"), "store_copy_stale", r)
        self.assertNotIn("confirmation_token", r)

    async def test_local_desfasada_al_confirmar(self) -> None:
        prev = await self.t["sv_update_addon"](_LOCAL)
        (self.addons / "nueva.txt").write_text("x\n", encoding="utf-8")
        r = await self.t["sv_update_addon"](_LOCAL, confirmation_token=prev["confirmation_token"])
        self.assertEqual(r.get("error"), "store_copy_stale", r)
        self.assertEqual(self.sv.escrituras(), [])

    async def test_al_dia_actualiza(self) -> None:
        prev = await self.t["sv_update_addon"](_LOCAL)
        r = await self.t["sv_update_addon"](_LOCAL, confirmation_token=prev["confirmation_token"])
        self.assertEqual(r.get("job_id"), "u1", r)
        [post] = self.sv.escrituras()
        self.assertEqual((post["ruta"], post["json"]),
                         (f"/store/addons/{_LOCAL}/update", {"background": True}))

    async def test_confirmar_espera_al_candado_de_addons(self) -> None:
        prev = await self.t["sv_update_addon"](_LOCAL)
        candado = folders.candado("addons")
        await candado.acquire()
        tarea = asyncio.ensure_future(self.t["sv_update_addon"](
            _LOCAL, confirmation_token=prev["confirmation_token"]))
        await asyncio.sleep(0.05)
        self.assertFalse(tarea.done())
        self.assertEqual(self.sv.escrituras(), [])
        candado.release()
        self.assertEqual((await tarea).get("job_id"), "u1")


# ── T055: lo que el Supervisor descartaría ────────────────────────────────────


_CABECERA = "name: Otra\nversion: '1'\ndescription: d\narch: [amd64]\n"


class TestDescartados(_Tienda):
    """Control negativo comprobado: con `ilegibles` volviendo a contar todo
    `config.*` sin slug (como antes) caen `test_no_bloquean_otras_apps` y
    `test_rebuild_tambien`; sin preferir el no descartado en
    `IndiceDeApps.apps` cae `test_un_duplicado_descartado_no_cuenta`."""

    async def _con(self, rel: str, contenido: bytes) -> dict[str, Any]:
        self.app_local()
        p = self.addons / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(contenido)
        self.envejecer()
        self.recargada()
        return await self.t["sv_install_addon"](_LOCAL)

    async def test_no_bloquean_otras_apps(self) -> None:
        casos = {
            "sin slug": (b"name: X\nversion: '1'\ndescription: d\narch: [amd64]\n",
                         "it has no 'slug'"),
            "sin nada": (b"foo: 1\n", "it has no 'name'"),
            "UTF-8 roto": (b"\xff\xfe: [", "it is not valid UTF-8"),
            "YAML roto": (b"slug: [sin cerrar\n", "it is not valid YAML"),
            "lista": (b"- 1\n- 2\n", "it is not a mapping"),
            "slug no válido": (_CABECERA.encode() + b"slug: 'a b'\n", "its 'slug' is not valid"),
            "slug largo": (_CABECERA.encode() + b"slug: " + b"x" * 60 + b"\n",
                           "longer than 60"),
        }
        for nombre, (contenido, motivo) in casos.items():
            with self.subTest(caso=nombre):
                for hijo in list(self.addons.iterdir()):
                    import shutil

                    shutil.rmtree(hijo)
                r = await self._con("otro/config.yml", contenido)
                self.assertIn("confirmation_token", r, r)
                nota = r["preview"]["ignored_config_files"]
                self.assertEqual(nota["count"], 1)
                [f] = nota["files"]
                self.assertEqual(f["path"], "otro/config.yml")
                self.assertIn(motivo, f["reason"])
                self.assertNotIn("cannot be read", str(r))

    async def test_un_json_roto_tampoco(self) -> None:
        r = await self._con("otro/config.json", b"{no es json")
        self.assertIn("confirmation_token", r, r)
        self.assertEqual(r["preview"]["ignored_config_files"]["files"][0]["reason"],
                         "it is not valid JSON")

    async def test_lo_que_hermes_no_lee_bloquea_con_su_motivo(self) -> None:
        r = await self._con("grande/config.yaml",
                            b"slug: grande\n" + b"#" * (folders.TAM_MAX_CONFIG + 1))
        self.assertEqual(r.get("error"), "store_copy_stale", r)
        self.assertIn("grande/config.yaml: it is larger than 1 MiB", r["reason"])
        self.assertIn("Hermes cannot read", r["reason"])

    async def test_un_duplicado_descartado_no_cuenta(self) -> None:
        # `a_rota` va antes que `ejemplo` por orden de ruta y declara el
        # mismo slug con SYS_ADMIN, pero sin `name`: el Supervisor la salta.
        r = await self._con("a_rota/config.yaml",
                            b"slug: ejemplo\nprivileged: [SYS_ADMIN]\n")
        self.assertIn("confirmation_token", r, r)
        priv = r["preview"]["privileges"]
        self.assertEqual(priv["declared_in_folder"]["config"], "ejemplo/config.yaml")
        self.assertEqual(priv["declared_in_folder"]["privileged"], ["NET_ADMIN"])

    async def test_si_solo_lo_declara_uno_descartado(self) -> None:
        p = self.app_local()
        p.write_text("slug: ejemplo\n", encoding="utf-8")
        self.envejecer()
        self.recargada()
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r.get("error"), "store_copy_stale", r)
        self.assertIn("would be skipped by the Supervisor", r["reason"])
        self.assertIn("it has no 'name'", r["reason"])

    async def test_rebuild_tambien(self) -> None:
        self.app_local()
        (self.addons / "otro").mkdir()
        (self.addons / "otro" / "config.yml").write_bytes(b"foo: 1\n")
        self.envejecer()
        self.recargada()
        self.sv.respuesta("GET", f"/store/addons/{_LOCAL}", ficha_extendida(
            _LOCAL, repository="local", installed=True, version="1.0.0",
            version_latest="1.0.0", build=True))
        self.sv.respuesta("GET", f"/addons/{_LOCAL}/info", info_instalada(_LOCAL))
        r = await self.t["sv_rebuild_addon"](_LOCAL)
        self.assertIn("confirmation_token", r, r)
        self.assertEqual(r["preview"]["ignored_config_files"]["count"], 1)


# ── T056: tope de espera del candado ──────────────────────────────────────────


class TestFolderBusy(_Tienda):
    """Control negativo comprobado: con `folders.candado` (sin tope) en vez
    de `candado_con_tope` en `_con_candado` y en `candado_de_app`, las
    confirmaciones se quedan esperando y caen por el `wait_for` de 2 s
    `test_escribir_en_una_carpeta_ocupada` y `test_instalar_con_addons_ocupada`."""

    def setUp(self) -> None:
        super().setUp()
        p = mock.patch.object(folders, "ESPERA_MAX_CANDADO_S", 0.05)
        p.start()
        self.addCleanup(p.stop)

    async def test_escribir_en_una_carpeta_ocupada(self) -> None:
        mcp = _MCP()
        folders_write.register(mcp, SupervisorSimuladoVacio(), response_max_bytes=131_072)
        t = mcp.tools
        prev = await t["fs_write_file_in_folder"](folder="share", path="a.txt", content="a\n")
        candado = folders.candado("share")
        await candado.acquire()
        try:
            r = await asyncio.wait_for(t["fs_write_file_in_folder"](
                folder="share", path="a.txt", confirmation_token=prev["confirmation_token"]), 2)
        finally:
            candado.release()
        self.assertEqual(r["error"], "folder_busy", r)
        self.assertEqual(r["folder"], "share")
        self.assertFalse((self.share / "a.txt").exists())
        # El token no se gastó: la misma llamada vale después.
        r = await t["fs_write_file_in_folder"](
            folder="share", path="a.txt", confirmation_token=prev["confirmation_token"])
        self.assertEqual(r.get("result"), "ok", r)

    async def test_instalar_con_addons_ocupada(self) -> None:
        self.app_local()
        self.envejecer()
        self.recargada()
        prev = await self.t["sv_install_addon"](_LOCAL)
        candado = folders.candado("addons")
        await candado.acquire()
        try:
            r = await asyncio.wait_for(self.t["sv_install_addon"](
                _LOCAL, confirmation_token=prev["confirmation_token"]), 2)
        finally:
            candado.release()
        self.assertEqual(r["error"], "folder_busy", r)
        self.assertEqual(r["slug"], _LOCAL)
        self.assertEqual(self.sv.escrituras(), [])
        r = await self.t["sv_install_addon"](_LOCAL, confirmation_token=prev["confirmation_token"])
        self.assertEqual(r.get("job_id"), "j1", r)


class TestTope(unittest.TestCase):
    def test_el_tope_es_menor_que_la_vida_del_token(self) -> None:
        # Con margen para repetir la confirmación con el mismo token.
        self.assertEqual(folders.ESPERA_MAX_CANDADO_S, 15.0)
        self.assertLessEqual(folders.ESPERA_MAX_CANDADO_S * 4, CONFIRMATION_TTL_SECONDS)


class SupervisorSimuladoVacio:
    """`GET /addons` sin apps instaladas (lo único que piden las tools de
    carpetas al Supervisor)."""

    async def sv_request(self, metodo: str, ruta: str, **_: Any) -> Any:
        return {"addons": []}


# ── Documentación (T053–T056) ─────────────────────────────────────────────────


class TestDocumentacion(unittest.TestCase):
    """Control negativo comprobado: con el texto de antes en el CHANGELOG
    («se opera relativa a la carpeta padre» sin distinguir la escritura) cae
    `test_changelog_dice_que_escribir_va_por_ruta`."""

    def setUp(self) -> None:
        texto = (_RAIZ / "hermes" / "CHANGELOG.md").read_text(encoding="utf-8")
        self.entrada = " ".join(texto.split("## [1.2.0]")[0].split())

    def test_changelog_dice_que_escribir_va_por_ruta(self) -> None:
        self.assertIn("crear una carpeta, mover y borrar operan además relativos "
                      "a la carpeta padre", self.entrada)
        self.assertIn("el fichero se escribe por ruta", self.entrada)

    def test_changelog_convergencia_2(self) -> None:
        for trozo in ("### Convergencia 2", "`sv_update_addon` enseña los privilegios",
                      "`folder_busy`", "`ignored_config_files`", "15 s",
                      "comparten un candado"):
            with self.subTest(trozo=trozo):
                self.assertIn(trozo, self.entrada)

    def test_guia(self) -> None:
        folders_txt = " ".join(_GUIDE["folders"].split())
        for trozo in ("`folder_busy`", "SIN gastar el token", "`ignored_config_files`",
                      "`sv_update_addon`"):
            with self.subTest(tema="folders", trozo=trozo):
                self.assertIn(trozo, folders_txt)
        supervisor = " ".join(_GUIDE["supervisor"].split())
        self.assertIn("`sv_update_addon` hace lo mismo", supervisor)


if __name__ == "__main__":
    unittest.main()
