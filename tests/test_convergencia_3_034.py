"""Convergencia 3 de la spec 034 (T057–T059), tras la segunda verificación
independiente.

- T057 (F1): antes de cada recarga de la tienda que lanza Hermes, Hermes
  cambia la fecha de la raíz de `/addons` para que el Supervisor relea las
  apps locales. El Supervisor 2026.11.0 solo relee si el máximo de
  `utils.get_latest_mtime` (la raíz con `stat()` y todo lo de debajo con
  `rglob("*")`) es DISTINTO (`!=`) del que guardó, y lo guarda ANTES de
  releer (`RepositoryLocal.update`, `store/repository.py`; `data.update()`
  en `StoreManager.reload`, `store/__init__.py`): una recarga que revienta
  al releer deja la fecha guardada y la siguiente volvía «bien» sin releer.
  La marca de Hermes se reconoce por su valor exacto en ns y solo si es la de
  la última recarga anotada.
- T058 (F2): con un job de recarga de la tienda sin terminar en `/jobs/info`
  (`store_manager_reload`; la recarga programada NO sale ahí: ver
  `test_convergencia_4_034.TestLaProgramadaNoSeVe`), `store_copy_stale` rechaza y una recarga de Hermes no se anota; si
  `/jobs/info` no responde, tampoco (fail-closed).
- T059 (F3): un `config.*` cuya lectura lanza una excepción que el
  Supervisor no captura (`read_yaml_file`, `utils/yaml.py`, solo captura
  `YAMLError`, `AttributeError`, `OSError` y `UnicodeDecodeError`) no se
  «ignora»: tumba toda recarga, y bloquea instalar, actualizar y
  reconstruir apps locales.

`/addons` es una carpeta temporal con ficheros reales; las fichas y la lista
de jobs tienen la forma del Supervisor 2026.11.0. Los controles negativos
comprobados están en cada clase.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any
from unittest import mock

import yaml

from hermes import folders
from hermes.ha import HAConnectionError
from hermes.tools import _store
from hermes.tools import store_repositories
from tests.fixtures.supervisor_tienda import SupervisorSimulado
from tests.test_convergencia_2_034 import _Tienda
from tests.test_tools_privilegios import _CONFIG_LOCAL, _LOCAL, _MCP

#: Pausa entre pasos: las fechas de los ficheros y `time.time()` no salen
#: del mismo reloj (en Linux el de los ficheros va unos ms por detrás).
_PAUSA = 0.06

_SIN_JOBS = {"ignore_conditions": [], "jobs": []}


def _job(nombre: str, done: bool | None, hijos: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Un job de `GET /jobs/info` con la forma de `SupervisorJob.as_dict`
    (`jobs/__init__.py`), sin `parent_id` y con `child_jobs` (`api/jobs.py`)."""
    return {"name": nombre, "reference": None, "uuid": "0" * 32, "progress": 0,
            "stage": None, "done": done, "errors": [],
            "created": "2026-11-15T10:00:00+00:00", "extra": None,
            "child_jobs": hijos or []}


class SupervisorConFechas(SupervisorSimulado):
    """`POST /store/reload` como el Supervisor 2026.11.0 para el repositorio
    local: calcula la fecha más reciente de `/addons` como
    `utils.get_latest_mtime` (escrito aquí a mano), y solo si es distinta de
    la guardada la guarda (ANTES) y relee las fichas. Releer revienta (la
    API responde error) si un `config.*` hace saltar algo que el Supervisor
    no captura; aquí, `devices: [5]` (la variante de la verificación:
    `_migrate_app_config` hace `":" in line` sobre un entero), que Hermes
    no reconoce y cuenta como una app más."""

    def __init__(self, addons: Path) -> None:
        super().__init__()
        self.addons = addons
        self.guardada: float | None = None
        self.copia: dict[str, dict[str, Any]] = {}
        self.relecturas = 0

    def _fecha_mas_reciente(self) -> float:
        ultima = self.addons.stat().st_mtime
        for p in self.addons.rglob("*"):
            ultima = max(ultima, p.stat().st_mtime)
        return ultima

    def _releer(self) -> None:
        self.relecturas += 1
        copia: dict[str, dict[str, Any]] = {}
        for p in sorted(self.addons.glob("**/config.yaml")):
            datos = yaml.safe_load(p.read_text(encoding="utf-8"))
            # `_migrate_app_config`: `any(":" in line for line in
            # config[ATTR_DEVICES])`; con un entero, `TypeError`.
            _ = any(":" in linea for linea in datos.get("devices", []))
            copia["local_" + datos["slug"]] = datos
        self.copia = copia

    async def sv_request(self, method: str, sv_path: str, **kw: Any) -> Any:
        if (method.upper(), sv_path) != ("POST", "/store/reload"):
            return await super().sv_request(method, sv_path, **kw)
        self.llamadas.append({"metodo": "POST", "ruta": sv_path, "json": None,
                              "params": None, "timeout": kw.get("timeout_seconds")})
        fecha = self._fecha_mas_reciente()
        if fecha != self.guardada:
            self.guardada = fecha
            try:
                self._releer()
            except TypeError as exc:
                raise HAConnectionError(
                    f"Supervisor REST POST http://supervisor{sv_path} failed 400: "
                    f"{exc}", status=400) from None
        return {}


class _ConRecarga(_Tienda):
    def setUp(self) -> None:
        super().setUp()
        _store._ULTIMA_RECARGA = None
        self.sv = SupervisorConFechas(self.addons)
        mcp = _MCP()
        from hermes.tools import addons as addons_mod
        from hermes.tools import store_apps as store_apps_mod

        addons_mod.register(mcp, self.sv)
        store_apps_mod.register(mcp, self.sv)
        store_repositories.register(mcp, self.sv)
        self.t = mcp.tools
        self.sv.respuesta("GET", f"/store/addons/{_LOCAL}", _ficha_local())
        self.sv.respuesta("GET", f"/store/addons/{_LOCAL}/availability", {})
        self.sv.respuesta("POST", f"/store/addons/{_LOCAL}/install", {"job_id": "j1"})
        # Margen 0: los pasos van separados por `_PAUSA` y no hace falta
        # esperar los 2 s del margen real.
        p = mock.patch.object(_store, "MARGEN_RECARGA_S", 0.0)
        p.start()
        self.addCleanup(p.stop)

    async def recargar(self) -> dict[str, Any]:
        await asyncio.sleep(_PAUSA)
        r = await self.t["sv_reload_store"]()
        await asyncio.sleep(_PAUSA)
        return r


def _ficha_local() -> dict[str, Any]:
    from tests.test_tools_privilegios import ficha_extendida

    return ficha_extendida(_LOCAL, repository="local")


_PRIVILEGIADO = _CONFIG_LOCAL.replace("NET_ADMIN", "SYS_ADMIN")
_REVIENTA = """\
name: Otra
version: "1.0.0"
slug: otra
description: Otra app
arch: [amd64]
devices: [5]
"""


# ── T057 (F1): la recarga de Hermes obliga a releer ──────────────────────────


class TestObligaAReleer(_ConRecarga):
    """Control negativo comprobado: con `marcar_raiz_de_addons` devolviendo
    un número sin llamar a `os.utime` (lo de antes: Hermes no tocaba
    /addons), cae `test_recarga_que_revienta_y_la_siguiente_no_relee` (la
    segunda recarga no relee, se anota y hay token con la copia de
    `SYS_ADMIN`). Sin `marca_raiz_ns` en `fecha_mas_reciente` (la marca de
    Hermes contaría como cambio) cae `test_sin_cambios_hay_token`."""

    async def test_recarga_que_revienta_y_la_siguiente_no_relee(self) -> None:
        # El escenario F1 de la verificación.
        self.app_local(_PRIVILEGIADO, carpeta="s")
        r = await self.recargar()
        self.assertEqual(r.get("result"), "ok", r)
        self.assertEqual(self.sv.copia[_LOCAL]["privileged"], ["SYS_ADMIN"])
        # Se reescribe inocuo y aparece un `config.*` que revienta la
        # relectura del Supervisor.
        self.app_local(carpeta="s")
        self.app_local(_REVIENTA, carpeta="z")
        r = await self.recargar()
        self.assertIn("error", r)
        relecturas = self.sv.relecturas
        r = await self.recargar()
        # Hermes cambió la fecha de /addons: el Supervisor vuelve a releer,
        # vuelve a reventar y la recarga no se anota.
        self.assertEqual(self.sv.relecturas, relecturas + 1)
        self.assertIn("error", r)
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r.get("error"), "store_copy_stale", r)
        self.assertNotIn("confirmation_token", r)
        # Arreglado el fichero, la siguiente recarga relee y hay token con la
        # copia buena.
        (self.addons / "z" / "config.yaml").unlink()
        r = await self.recargar()
        self.assertEqual(r.get("result"), "ok", r)
        self.assertEqual(self.sv.copia[_LOCAL]["privileged"], ["NET_ADMIN"])
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertIn("confirmation_token", r, r)

    async def test_sin_cambios_hay_token(self) -> None:
        self.app_local()
        self.envejecer()
        r = await self.recargar()
        self.assertEqual(r.get("result"), "ok", r)
        # La raíz tiene la marca de Hermes, dentro de los 2 s del margen
        # real: no cuenta porque es exactamente la marca registrada.
        self.assertEqual(os.lstat(self.addons).st_mtime_ns, _store._MARCA_RAIZ_NS)
        with mock.patch.object(_store, "MARGEN_RECARGA_S", 2.0):
            r = await self.t["sv_install_addon"](_LOCAL)
        self.assertIn("confirmation_token", r, r)

    async def test_un_cambio_posterior_en_la_raiz_cuenta(self) -> None:
        # Crear y borrar algo en la raíz solo cambia la fecha de la raíz: ya
        # no es la marca de Hermes, así que cuenta.
        self.app_local()
        await self.recargar()
        (self.addons / "tmp.txt").write_text("x\n", encoding="utf-8")
        (self.addons / "tmp.txt").unlink()
        self.assertNotEqual(os.lstat(self.addons).st_mtime_ns, _store._MARCA_RAIZ_NS)
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r.get("error"), "store_copy_stale", r)
        self.assertIn("/addons itself", r["reason"])

    async def test_la_marca_de_una_recarga_que_fallo_cuenta(self) -> None:
        # Una recarga que falla (aquí, el Supervisor la rechaza antes de
        # empezar) deja su marca en la raíz, pero no se registra: la marca
        # que no cuenta es solo la de la última recarga anotada.
        self.app_local()
        await self.recargar()
        marca = _store._MARCA_RAIZ_NS
        with mock.patch.object(SupervisorConFechas, "_fecha_mas_reciente",
                               side_effect=HAConnectionError("failed 400: job", status=400)):
            r = await self.recargar()
        self.assertIn("error", r)
        self.assertNotEqual(os.lstat(self.addons).st_mtime_ns, marca)
        self.assertEqual(_store._MARCA_RAIZ_NS, marca)
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r.get("error"), "store_copy_stale", r)

    async def test_sin_addons_no_se_anota(self) -> None:
        with mock.patch.object(folders, "ADDONS_BASE", self.addons / "sin_montar"):
            r = await self.recargar()
        self.assertEqual(r.get("result"), "ok", r)
        self.assertIsNone(_store.ultima_recarga_de_tienda())

    async def test_si_no_se_puede_marcar_no_se_anota(self) -> None:
        self.app_local()
        with mock.patch.object(_store.os, "utime", side_effect=PermissionError(1, "no")):
            r = await self.recargar()
        self.assertEqual(r.get("result"), "ok", r)
        self.assertIsNone(_store.ultima_recarga_de_tienda())
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r.get("error"), "store_copy_stale", r)

    def test_la_marca_es_mayor_y_cambia_el_float(self) -> None:
        # La fecha de la raíz, en el futuro: la marca la supera igualmente
        # (el máximo cambia) y el `float` que compara el Supervisor también.
        futuro = time.time_ns() + 3_600 * 10**9
        os.utime(self.addons, ns=(futuro, futuro))
        antes = os.lstat(self.addons).st_mtime
        marca = _store.marcar_raiz_de_addons()
        self.assertIsNotNone(marca)
        self.assertGreater(marca, futuro)
        self.assertNotEqual(os.lstat(self.addons).st_mtime, antes)


# ── T058 (F2): recargas en curso en el Supervisor ─────────────────────────────


class TestRecargaEnCurso(_ConRecarga):
    """Control negativo comprobado: sin la consulta de `/jobs/info` en
    `comprobar_copia_de_tienda` caen `test_job_en_curso_rechaza` y
    `test_sin_lista_de_jobs_rechaza`; sin la segunda consulta en
    `recarga_valida_para_apps_locales` cae
    `test_recarga_que_encuentra_otra_no_se_anota` (caso «después»)."""

    def setUp(self) -> None:
        super().setUp()
        self.app_local()

    async def al_dia(self) -> None:
        r = await self.recargar()
        self.assertEqual(r.get("result"), "ok", r)
        self.assertIsNotNone(_store.ultima_recarga_de_tienda())

    async def test_job_en_curso_rechaza(self) -> None:
        await self.al_dia()
        for nombre, jobs in (
            ("de la API", [_job("store_manager_reload", False)]),
            ("sin arrancar", [_job("store_manager_reload", None)]),
            # La recarga programada no está aquí: su forma real en
            # `/jobs/info` es una lista vacía (convergencia 4, T061).
            ("de hijo de otro job visible", [_job("backup_manager_full_backup", False,
                                                   [_job("store_manager_reload", False)])]),
            ("añadir repositorio", [_job("store_manager_add_repository", False)]),
        ):
            with self.subTest(caso=nombre):
                self.sv.respuesta("GET", "/jobs/info", {"ignore_conditions": [], "jobs": jobs})
                r = await self.t["sv_install_addon"](_LOCAL)
                self.assertEqual(r.get("error"), "store_copy_stale", r)
                self.assertIn("still running", r["reason"])
                self.assertIn("sv_list_pending_jobs", r["hint"])

    async def test_job_terminado_u_otro_no_rechaza(self) -> None:
        await self.al_dia()
        self.sv.respuesta("GET", "/jobs/info", {"ignore_conditions": [], "jobs": [
            _job("store_manager_reload", True), _job("backup_manager_full_backup", False)]})
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertIn("confirmation_token", r, r)

    async def test_sin_lista_de_jobs_rechaza(self) -> None:
        await self.al_dia()
        for valor in (HAConnectionError("failed 500: boom", status=500), {"jobs": "x"}):
            with self.subTest(valor=repr(valor)):
                self.sv.respuesta("GET", "/jobs/info", valor)
                r = await self.t["sv_install_addon"](_LOCAL)
                self.assertEqual(r.get("error"), "store_copy_stale", r)
                self.assertIn("job list could not be read", r["reason"])

    async def test_job_en_curso_al_confirmar(self) -> None:
        await self.al_dia()
        prev = await self.t["sv_install_addon"](_LOCAL)
        self.assertIn("confirmation_token", prev, prev)
        self.sv.respuesta("GET", "/jobs/info", {"ignore_conditions": [], "jobs": [
            _job("store_manager_reload", False)]})
        r = await self.t["sv_install_addon"](_LOCAL, confirmation_token=prev["confirmation_token"])
        self.assertEqual(r.get("error"), "store_copy_stale", r)
        self.assertEqual([c for c in self.sv.escrituras() if c["ruta"] != "/store/reload"], [])

    async def test_recarga_que_encuentra_otra_no_se_anota(self) -> None:
        en_curso = {"ignore_conditions": [], "jobs": [_job("store_manager_reload", False)]}
        error = HAConnectionError("failed 500: boom", status=500)
        for nombre, secuencia in (
            ("antes", [en_curso, _SIN_JOBS]),
            ("después", [_SIN_JOBS, en_curso]),
            ("sin lista antes", [error, _SIN_JOBS]),
            ("sin lista después", [_SIN_JOBS, error]),
        ):
            with self.subTest(caso=nombre):
                _store._ULTIMA_RECARGA = None
                self.sv.secuencia("GET", "/jobs/info", secuencia)
                r = await self.recargar()
                self.assertEqual(r.get("result"), "ok", r)
                self.assertIsNone(_store.ultima_recarga_de_tienda())
        self.sv.respuesta("GET", "/jobs/info", _SIN_JOBS)
        await self.al_dia()


# ── T059 (F3): los que tumban la recarga no se ignoran ───────────────────────


_FECHA_IMPOSIBLE = """\
name: Rota
version: "1.0.0"
slug: rota
description: Rota
arch: [amd64]
creada: 2001-13-01
"""


class TestTumbaLaRecarga(_ConRecarga):
    """Control negativo comprobado: con `except Exception` en vez de
    `except _YAML_QUE_EL_SUPERVISOR_SALTA` en `folders._analizar_texto` (lo
    de antes: todo fallo de YAML era un descarte) caen
    `test_clasificacion` y `test_bloquea_instalar_y_no_sale_como_ignorado`;
    sin el rechazo por `rompen_recarga` en `copia_de_tienda_desfasada` cae
    `test_bloquea_instalar_y_no_sale_como_ignorado`."""

    def test_clasificacion(self) -> None:
        # Lo que hace PyYAML (el cargador del Supervisor) con una fecha
        # imposible: `ValueError`, que no es `YAMLError`.
        with self.assertRaises(ValueError) as ctx:
            yaml.load(_FECHA_IMPOSIBLE, Loader=folders._CARGADOR_YAML)  # noqa: S506
        self.assertNotIsInstance(ctx.exception, yaml.YAMLError)
        self.app_local(_FECHA_IMPOSIBLE, carpeta="rota")
        self.app_local("name: [\n", carpeta="sintaxis")
        (self.addons / "json").mkdir()
        (self.addons / "json" / "config.json").write_text("{", encoding="utf-8")
        indice = folders.indice_de_apps_locales(self.addons)
        self.assertEqual(set(indice.rompen_recarga), {"rota/config.yaml"})
        self.assertIn("ValueError", indice.rompen_recarga["rota/config.yaml"])
        self.assertIn("every store reload fails", indice.rompen_recarga["rota/config.yaml"])
        self.assertEqual(set(indice.descartados), {"sintaxis/config.yaml", "json/config.json"})
        self.assertEqual(indice.no_legibles, {})

    async def test_bloquea_instalar_y_no_sale_como_ignorado(self) -> None:
        self.app_local()
        await self.recargar()
        _store._ULTIMA_RECARGA = time.time() + 60  # todo «al día» salvo esto
        self.app_local(_FECHA_IMPOSIBLE, carpeta="rota")
        self.app_local("name: [\n", carpeta="sintaxis")
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r.get("error"), "store_copy_stale", r)
        self.assertIn("every store reload fail", r["reason"])
        self.assertIn("rota/config.yaml", r["reason"])
        self.assertNotIn("sintaxis", r["reason"])
        self.assertIn("Fix or remove", r["hint"])
        self.assertNotIn("confirmation_token", r)
        # Sin él, el de sintaxis sí es un descarte y no bloquea.
        (self.addons / "rota" / "config.yaml").unlink()
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertIn("confirmation_token", r, r)
        nota = r["preview"]["ignored_config_files"]
        self.assertEqual([f["path"] for f in nota["files"]], ["sintaxis/config.yaml"])
        self.assertIn("skips each of these", nota["note"])
        self.assertNotIn("do not affect", nota["note"])
