"""Actualizaciones del sistema (spec 015, tramos 1 y 2: FR-001…FR-010,
FR-018).

Todo contra el Supervisor simulado de `tests/fixtures/supervisor_actualizaciones.py`
(formas del Supervisor 2026.11.0, datos ficticios). Nunca hay una
actualización real: lo que se comprueba es lo que Hermes LEE, lo que MANDA y
lo que devuelve.

- `TestValidacion`, `TestBloqueos`: funciones puras (`_validar_version`,
  `_bloqueos`, `_comparar`).
- `TestListar`, `TestBuscar`: `sv_list_available_updates` y
  `sv_check_for_updates`.
- `TestVistaPreviaCore`, `TestUpdateCore`, `TestTokenAtado`: `sv_update_core`.
- Tramo 2: `TestUpdateOs`, `TestUpdateSupervisor` (vistas previas) y
  `TestSegundoPlano` (petición de fondo, búsqueda del job, cortes, token).

Controles negativos del tramo 1 (T015), con sus recuentos en el commit:
(a) emitir token con `blocked` no vacío; (b) no atar `_to_version`;
(c) enviar `/core/update` sin `version`; (d) escribir `check_config_state.json`
en la vista previa; (e) quitar `redact_secrets` del detalle de `/core/check`;
(f) `/reload_updates` en vez de `/refresh_updates`. Cada uno pone en rojo
los tests que lo vigilan.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import aiohttp
from structlog.testing import capture_logs

from hermes import fs_write, security
from hermes.ha import HAConnectionError
from hermes.tools import addons as addons_mod
from hermes.tools import system_updates as mod
from tests.fixtures.supervisor_actualizaciones import (
    AVISO_REINICIO_OS,
    CENTINELA_JWT,
    CENTINELA_PASSWORD,
    CORE_ACTUAL,
    CORE_ULTIMA,
    OS_ACTUAL,
    OS_ULTIMA,
    SLUG_APP,
    SLUG_HERMES,
    SUPERVISOR_ACTUAL,
    SUPERVISOR_ULTIMA,
    URL_NOTAS_CORE,
    URL_NOTAS_OS,
    URL_NOTAS_SUPERVISOR,
    SupervisorActualizaciones,
    con_actualizaciones_de_todo,
    con_os_y_supervisor_desactualizados,
    con_plugin_desactualizado,
    error_404,
    job,
    sin_supervisor_pendiente,
    sistema_sano,
)

_JOB = "0a1b2c3d4e5f40718293a4b5c6d7e8f9"


class _MCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


# ── Funciones puras ───────────────────────────────────────────────────────────


class TestValidacion(unittest.TestCase):
    def test_versiones_validas(self) -> None:
        for v in ("2026.11.1", "2026.12.0b1", "16.3", "1", "2026.11.0.dev20261114"):
            with self.subTest(v=v):
                self.assertTrue(mod._validar_version(v))

    def test_versiones_invalidas(self) -> None:
        for v in ("", " ", "2026.11.1 ", "2026 11", "../etc", "2026/11", "1..2",
                  "a2026.11", "-1", "1" * 33, "2026.11.1;rm", "1\n2", 2026, None):
            with self.subTest(v=v):
                self.assertFalse(mod._validar_version(v))

    def test_32_caracteres_es_el_limite(self) -> None:
        self.assertTrue(mod._validar_version("1" * 32))
        self.assertFalse(mod._validar_version("1" * 33))

    def test_comparar(self) -> None:
        self.assertEqual(mod._comparar("2026.12.0", "2026.11.1"), 1)
        self.assertEqual(mod._comparar("2026.11.1", "2026.12.0"), -1)
        self.assertEqual(mod._comparar("16.3", "16.3"), 0)
        self.assertEqual(mod._comparar("2026.12.0b1", "2026.12.0"), -1)
        self.assertIsNone(mod._comparar("no-es-version", "2026.11.1"))
        self.assertIsNone(mod._comparar(None, "2026.11.1"))


def _sano() -> dict[str, Any]:
    """Datos ya leídos de un sistema sano, para `_bloqueos`."""
    return {
        "salud": {"unhealthy": [], "unsupported": [], "issues": []},
        "supervisor": {"update_available": False, "auto_update": True},
        "plugins": {p: {"version": "1", "version_latest": "1", "update_available": False}
                    for p in ("dns", "audio", "cli", "observer", "multicast")},
        "host": {"disk_free": 50.0},
        "config_check": {"result": "ok", "details": None},
        "os_info": {"version": "16.2", "version_pending": None},
        "to_version": "16.3",
    }


class TestBloqueos(unittest.TestCase):
    def _codigos(self, componente: str, **cambios: Any) -> tuple[list[str], list[str]]:
        datos = _sano()
        datos.update(cambios)
        bloqueos, avisos = mod._bloqueos(componente, **datos)
        for b in bloqueos:
            self.assertEqual(set(b), {"code", "message"})
            self.assertTrue(b["message"])
        return [b["code"] for b in bloqueos], avisos

    def test_sistema_sano_no_bloquea(self) -> None:
        for componente in ("core", "os", "supervisor"):
            with self.subTest(componente=componente):
                codigos, _ = self._codigos(componente)
                self.assertEqual(codigos, [])

    def test_unhealthy(self) -> None:
        salud = {"unhealthy": ["docker"], "unsupported": [], "issues": []}
        self.assertEqual(self._codigos("core", salud=salud)[0], ["unhealthy"])
        self.assertEqual(self._codigos("os", salud=salud)[0], ["unhealthy"])
        # El Supervisor no pone condiciones a su propia actualización (R-6).
        self.assertEqual(self._codigos("supervisor", salud=salud)[0], [])
        bloqueos, _ = mod._bloqueos("core", **{**_sano(), "salud": salud})
        self.assertIn("docker", bloqueos[0]["message"])

    def test_supervisor_pendiente(self) -> None:
        sup = {"update_available": True, "auto_update": True}
        self.assertEqual(self._codigos("core", supervisor=sup)[0],
                         ["supervisor_update_pending"])
        self.assertEqual(self._codigos("os", supervisor=sup)[0],
                         ["supervisor_update_pending"])
        self.assertEqual(self._codigos("supervisor", supervisor=sup)[0], [])

    def test_plugins_desactualizados(self) -> None:
        plugins = _sano()["plugins"]
        plugins["dns"] = {"version": "1", "version_latest": "2", "update_available": True}
        # Con la actualización automática apagada, el Supervisor la rechaza.
        codigos, _ = self._codigos(
            "core", plugins=plugins,
            supervisor={"update_available": False, "auto_update": False})
        self.assertEqual(codigos, ["plugins_outdated"])
        bloqueos, _ = mod._bloqueos("core", **{
            **_sano(), "plugins": plugins,
            "supervisor": {"update_available": False, "auto_update": False}})
        self.assertIn("dns", bloqueos[0]["message"])
        # Con ella activa, los actualiza antes: aviso, no bloqueo (FR-004).
        codigos, avisos = self._codigos("core", plugins=plugins)
        self.assertEqual(codigos, [])
        self.assertTrue(any("dns" in a for a in avisos), avisos)
        # Al OS no le afecta (`os_manager_update` no tiene PLUGINS_UPDATED).
        codigos, _ = self._codigos(
            "os", plugins=plugins,
            supervisor={"update_available": False, "auto_update": False})
        self.assertEqual(codigos, [])

    def test_poco_disco(self) -> None:
        self.assertEqual(self._codigos("core", host={"disk_free": 1.9})[0],
                         ["low_disk_space"])
        self.assertEqual(self._codigos("core", host={"disk_free": 2.0})[0], [])
        self.assertEqual(self._codigos("os", host={"disk_free": 1.0})[0], [])

    def test_reinicio_pendiente_del_os(self) -> None:
        os_info = {"version": "16.2", "version_pending": "16.3"}
        self.assertEqual(self._codigos("os", os_info=os_info)[0], ["reboot_pending"])
        # Pendiente otra versión: no es el mismo destino.
        self.assertEqual(self._codigos("os", os_info=os_info, to_version="16.4")[0], [])

    def test_configuracion(self) -> None:
        for resultado, codigo in (("error", "config_invalid"),
                                  ("timeout", "config_check_failed"),
                                  ("unavailable", "config_check_failed")):
            with self.subTest(resultado=resultado):
                cc = {"result": resultado, "details": None}
                self.assertEqual(self._codigos("core", config_check=cc)[0], [codigo])
                # Es una regla de Hermes para Core (R-6), no para el OS.
                self.assertEqual(self._codigos("os", config_check=cc)[0], [])

    def test_lecturas_que_faltan_avisan(self) -> None:
        codigos, avisos = self._codigos("core", salud=None, supervisor=None, host=None,
                                        plugins={"dns": None})
        self.assertEqual(codigos, [])
        self.assertGreaterEqual(len(avisos), 4)

    def test_varios_a_la_vez(self) -> None:
        codigos, _ = self._codigos(
            "core",
            salud={"unhealthy": ["setup"], "unsupported": [], "issues": []},
            supervisor={"update_available": True, "auto_update": True},
            host={"disk_free": 0.5},
            config_check={"result": "error", "details": "x"})
        self.assertEqual(codigos, ["unhealthy", "supervisor_update_pending",
                                   "low_disk_space", "config_invalid"])


# ── Base con el Supervisor simulado ───────────────────────────────────────────


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._parches = [
            mock.patch.object(security, "CONFIRMATIONS_DIR", base / "tokens"),
            mock.patch.object(addons_mod, "_PENDING_JOBS_PATH", base / "pending_jobs.json"),
            mock.patch.object(fs_write, "CHECK_CONFIG_STATE_PATH",
                              base / "check_config_state.json"),
        ]
        for p in self._parches:
            p.start()
        self.estado_check = base / "check_config_state.json"
        self.sv = sistema_sano(SupervisorActualizaciones())
        mcp = _MCP()
        mod.register(mcp, self.sv, response_max_bytes=131_072)
        self.t = mcp.tools

    async def asyncTearDown(self) -> None:
        for p in self._parches:
            p.stop()
        self.tmp.cleanup()

    async def vista_previa(self, **kw: Any) -> dict[str, Any]:
        return await self.t["sv_update_core"](**kw)

    def posts_de_actualizacion(self) -> list[tuple[str, str]]:
        return [r for r in self.sv.posts() if r[1] == "/core/update"]


# ── Listar y buscar (FR-001, FR-002) ──────────────────────────────────────────


class TestListar(_Base):
    async def test_todo_desactualizado(self) -> None:
        con_actualizaciones_de_todo(self.sv)
        r = await self.t["sv_list_available_updates"]()
        self.assertNotIn("error", r)
        self.assertEqual(r["count"], len(r["items"]))
        self.assertIs(r["truncated"], False)
        self.assertNotIn("partial", r)
        self.assertEqual(r["auto_update"], True)
        self.assertEqual(r["channel"], "stable")
        self.assertEqual(r["_third_party_text"]["fields"], ["name"])
        tipos = [i["type"] for i in r["items"]]
        # Orden en que conviene actualizar: supervisor → core → os → plugins → apps.
        self.assertEqual(tipos, ["core", "plugin", "addon", "addon"])
        core, plugin, app, hermes = r["items"]
        self.assertEqual(core, {
            "type": "core", "name": "Home Assistant Core", "slug": None,
            "installed_version": CORE_ACTUAL, "latest_version": CORE_ULTIMA,
            "update_with": "sv_update_core"})
        self.assertEqual(plugin["slug"], "dns")
        self.assertEqual(plugin["name"], "dns plugin")
        self.assertEqual(plugin["update_with"], "sv_call_api POST /dns/update")
        self.assertIn("automatically", plugin["note"])
        self.assertEqual((app["slug"], app["installed_version"], app["latest_version"],
                          app["update_with"]), (SLUG_APP, "1.0.0", "1.1.0", "sv_update_addon"))
        self.assertEqual(hermes["slug"], SLUG_HERMES)
        self.assertIsNone(hermes["update_with"])
        self.assertIn("Home Assistant UI", hermes["note"])

    async def test_hermes_por_el_slug_exacto(self) -> None:
        """T048: el criterio de Hermes es el de `ha_install_update` (slug
        exacto de `/addons/self/info`), y una app `*_hermes` que no es Hermes
        no se manda a `sv_update_addon`, que la rechazaría (D-13). Control
        negativo (comprobado): volver a `_es_hermes(slug)` como único criterio
        pone este test en rojo (la nota de la otra app dice «cannot update
        itself»)."""
        con_actualizaciones_de_todo(self.sv)
        self.sv.respuesta("GET", "/addons/self/info", {"slug": SLUG_HERMES})
        otra = "b9c8d7e6_hermes"
        info = dict(self.sv.json[("GET", "/supervisor/info")])
        info["addons"] = [*info["addons"], {"name": "Otra", "slug": otra, "version": "0.1.0"}]
        self.sv.respuesta("GET", "/supervisor/info", info)
        actual = self.sv.json[("GET", "/available_updates")]["available_updates"]
        self.sv.respuesta("GET", "/available_updates", {"available_updates": [
            *actual, {"update_type": "addon", "name": "Otra",
                      "panel_path": f"/update-available/{otra}", "version_latest": "0.2.0"}]})
        r = await self.t["sv_list_available_updates"]()
        por_slug = {i["slug"]: i for i in r["items"] if i["type"] == "addon"}
        self.assertIsNone(por_slug[SLUG_HERMES]["update_with"])
        self.assertIn("cannot update itself", por_slug[SLUG_HERMES]["note"])
        self.assertIsNone(por_slug[otra]["update_with"])
        self.assertIn("sv_update_addon refuses", por_slug[otra]["note"])
        self.assertNotIn("cannot update itself", por_slug[otra]["note"])
        self.assertEqual(por_slug[SLUG_APP]["update_with"], "sv_update_addon")

    async def test_hermes_con_slug_sin_sufijo(self) -> None:
        # Si el slug propio no termina en `_hermes` (copia local), cuenta él.
        con_actualizaciones_de_todo(self.sv)
        self.sv.respuesta("GET", "/addons/self/info", {"slug": SLUG_APP})
        r = await self.t["sv_list_available_updates"]()
        por_slug = {i["slug"]: i for i in r["items"] if i["type"] == "addon"}
        self.assertIsNone(por_slug[SLUG_APP]["update_with"])
        self.assertIn("cannot update itself", por_slug[SLUG_APP]["note"])
        self.assertIsNone(por_slug[SLUG_HERMES]["update_with"])
        self.assertIn("sv_update_addon refuses", por_slug[SLUG_HERMES]["note"])

    async def test_sin_slug_propio_cae_al_sufijo(self) -> None:
        # Fail-closed: sin `/addons/self/info`, cualquier `*_hermes` puede ser
        # Hermes, y se dice.
        con_actualizaciones_de_todo(self.sv)
        self.sv.respuesta("GET", "/addons/self/info", error_404("GET", "/addons/self/info"))
        r = await self.t["sv_list_available_updates"]()
        por_slug = {i["slug"]: i for i in r["items"] if i["type"] == "addon"}
        self.assertIsNone(por_slug[SLUG_HERMES]["update_with"])
        self.assertIn("could not read its own app slug", por_slug[SLUG_HERMES]["note"])
        self.assertEqual(por_slug[SLUG_APP]["update_with"], "sv_update_addon")

    async def test_sin_apps_no_lee_el_slug_propio(self) -> None:
        self.sv.respuesta("GET", "/available_updates", {"available_updates": []})
        await self.t["sv_list_available_updates"]()
        self.assertNotIn(("GET", "/addons/self/info"), self.sv.rutas())

    async def test_orden_con_supervisor_y_os(self) -> None:
        con_actualizaciones_de_todo(self.sv)
        info = dict(self.sv.json[("GET", "/supervisor/info")])
        info.update(version_latest="2026.12.0", update_available=True)
        self.sv.respuesta("GET", "/supervisor/info", info)
        self.sv.respuesta("GET", "/os/info", {
            "version": "16.2", "version_latest": "16.3", "version_pending": None,
            "update_available": True})
        actual = self.sv.json[("GET", "/available_updates")]["available_updates"]
        self.sv.respuesta("GET", "/available_updates", {"available_updates": [
            {"update_type": "os", "panel_path": "/update-available/os",
             "version_latest": "16.3"},
            *actual,
            {"update_type": "supervisor", "panel_path": "/update-available/supervisor",
             "version_latest": "2026.12.0"},
        ]})
        r = await self.t["sv_list_available_updates"]()
        self.assertEqual([i["type"] for i in r["items"]],
                         ["supervisor", "core", "os", "plugin", "addon", "addon"])
        sup = r["items"][0]
        self.assertEqual((sup["installed_version"], sup["update_with"]),
                         ("2026.11.0", "sv_update_supervisor"))
        os_ = r["items"][2]
        self.assertEqual((os_["installed_version"], os_["update_with"]),
                         ("16.2", "sv_update_os"))

    async def test_sin_haos_no_hay_os_ni_error(self) -> None:
        self.sv.respuesta("GET", "/os/info", error_404("GET", "/os/info"))
        r = await self.t["sv_list_available_updates"]()
        self.assertNotIn("partial", r)
        self.assertNotIn("os", [i["type"] for i in r["items"]])

    async def test_lectura_que_falla_es_parcial(self) -> None:
        self.sv.respuesta("GET", "/available_updates",
                          HAConnectionError("Supervisor error: algo"))
        self.sv.respuesta("GET", "/dns/info", HAConnectionError("Supervisor error: x"))
        r = await self.t["sv_list_available_updates"]()
        self.assertIs(r["partial"], True)
        self.assertEqual(sorted(r["unavailable"]), ["/available_updates", "/dns/info"])

    async def test_core_ilegible_deja_la_version_a_null(self) -> None:
        self.sv.respuesta("GET", "/core/info", HAConnectionError("Supervisor error: x"))
        r = await self.t["sv_list_available_updates"]()
        self.assertIs(r["partial"], True)
        self.assertIn("/core/info", r["unavailable"])
        core = r["items"][0]
        self.assertIsNone(core["installed_version"])
        self.assertEqual(core["latest_version"], CORE_ULTIMA)

    async def test_solo_lee(self) -> None:
        con_actualizaciones_de_todo(self.sv)
        await self.t["sv_list_available_updates"]()
        self.assertEqual({c["metodo"] for c in self.sv.llamadas}, {"GET"})

    async def test_nada_pendiente(self) -> None:
        self.sv.respuesta("GET", "/available_updates", {"available_updates": []})
        r = await self.t["sv_list_available_updates"]()
        self.assertEqual((r["count"], r["items"]), (0, []))
        self.assertNotIn("partial", r)


class TestBuscar(_Base):
    async def test_refresca_y_lista(self) -> None:
        con_actualizaciones_de_todo(self.sv)
        r = await self.t["sv_check_for_updates"]()
        posts = [c for c in self.sv.llamadas if c["metodo"] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["ruta"], "/refresh_updates")
        self.assertEqual(posts[0]["timeout"], 120)
        # El POST va antes que la lista: si no, devolvería la caché vieja.
        self.assertEqual(self.sv.llamadas[0]["ruta"], "/refresh_updates")
        self.assertEqual(r["count"], 4)
        self.assertIs(r["refreshed"], True)
        self.assertNotIn("/reload_updates", [c["ruta"] for c in self.sv.llamadas])

    async def test_error_redactado(self) -> None:
        self.sv.respuesta("POST", "/refresh_updates", HAConnectionError(
            f"Supervisor error: password: {CENTINELA_PASSWORD} Bearer {CENTINELA_JWT}"))
        with capture_logs() as logs:
            r = await self.t["sv_check_for_updates"]()
        self.assertEqual(r["error"], "supervisor_error")
        texto = json.dumps(r) + repr(logs)
        self.assertNotIn(CENTINELA_PASSWORD, texto)
        self.assertNotIn(CENTINELA_JWT, texto)
        self.assertEqual([c["ruta"] for c in self.sv.llamadas], ["/refresh_updates"])


# ── sv_update_core: vista previa (FR-003, FR-004, FR-005, FR-010) ─────────────


class TestVistaPreviaCore(_Base):
    async def test_bloques_completos(self) -> None:
        r = await self.vista_previa()
        self.assertIn("confirmation_token", r)
        p = r["preview"]
        self.assertEqual(p["action"], "update_core")
        self.assertEqual(p["component"], "core")
        self.assertEqual((p["from_version"], p["to_version"]), (CORE_ACTUAL, CORE_ULTIMA))
        self.assertIs(p["downgrade"], False)
        self.assertEqual(p["release_notes"], {
            "available": False, "text": None,
            "reason": p["release_notes"]["reason"], "release_url": URL_NOTAS_CORE})
        self.assertIn("does not provide release notes", p["release_notes"]["reason"])
        self.assertEqual(p["backup"], {
            "will_create": True, "possible": True,
            "kind": "partial backup of Home Assistant Core (no apps)",
            "name": f"core_{CORE_ACTUAL}",
            "location": "default Supervisor backup location",
            "exclude_database": False, "hint": None})
        self.assertEqual(p["restarts"]["components"], ["core"])
        for frase in ("ha_*", "Hermes keeps running", "previous"):
            self.assertIn(frase, p["restarts"]["description"])
        self.assertIsNone(p["restarts"]["after"])
        self.assertEqual(p["system_health"], {
            "unhealthy": [], "unsupported": [], "issues": [], "unavailable": False})
        self.assertEqual(p["config_check"], {"result": "ok", "details": None})
        self.assertEqual(p["plugins_to_update_first"], [])
        self.assertEqual(p["blocked"], [])
        self.assertIn("the Supervisor also checks internet access when it runs",
                      p["warnings"])
        self.assertEqual(self.posts_de_actualizacion(), [])

    async def test_check_con_su_espera_y_sin_tocar_el_estado(self) -> None:
        self.estado_check.write_text('{"marca": "antes"}', encoding="utf-8")
        await self.vista_previa()
        check = [c for c in self.sv.llamadas if c["ruta"] == "/core/check"]
        self.assertEqual(len(check), 1)
        self.assertEqual((check[0]["metodo"], check[0]["timeout"]), ("POST", 120))
        # La vista previa no puede levantar el bloqueo de reinicio de
        # `sv_restart_core`: eso es de `sv_check_core_config` (R-6).
        self.assertEqual(self.estado_check.read_text(encoding="utf-8"), '{"marca": "antes"}')

    async def test_sin_estado_previo_tampoco_lo_crea(self) -> None:
        await self.vista_previa()
        self.assertFalse(self.estado_check.exists())

    async def test_exclude_database_de_core_info(self) -> None:
        info = dict(self.sv.json[("GET", "/core/info")])
        info["backups_exclude_database"] = True
        self.sv.respuesta("GET", "/core/info", info)
        r = await self.vista_previa()
        self.assertIs(r["preview"]["backup"]["exclude_database"], True)

    async def test_sin_backup(self) -> None:
        r = await self.vista_previa(backup=False)
        b = r["preview"]["backup"]
        self.assertIs(b["will_create"], False)
        self.assertIsNone(b["name"])
        self.assertIn("backup=true", b["hint"])

    async def test_notas_con_core_caido(self) -> None:
        self.sv.core_caido = True
        r = await self.vista_previa()
        notas = r["preview"]["release_notes"]
        self.assertIs(notas["available"], False)
        self.assertIsNone(notas["release_url"])
        self.assertIn("did not respond", notas["reason"])
        # Sin URL de notas no deja de haber token: es información, no un bloqueo.
        self.assertIn("confirmation_token", r)

    async def test_entidad_por_registro_y_no_por_nombre(self) -> None:
        # La otra entidad tiene el mismo `unique_id` pero no es de `hassio`.
        r = await self.vista_previa()
        self.assertEqual(r["preview"]["release_notes"]["release_url"], URL_NOTAS_CORE)
        get_entries = [c for c in self.sv.ws_llamadas
                       if c.get("type") == "config/entity_registry/get_entries"]
        self.assertEqual(len(get_entries), 1)
        self.assertNotIn("light.salon", get_entries[0]["entity_ids"])

    async def _bloqueada(self, codigo: str) -> dict[str, Any]:
        r = await self.vista_previa()
        self.assertEqual(r["error"], "update_blocked", r)
        self.assertNotIn("confirmation_token", r)
        self.assertIn(codigo, [b["code"] for b in r["preview"]["blocked"]])
        self.assertEqual(self.posts_de_actualizacion(), [])
        return r

    async def test_unhealthy(self) -> None:
        self.sv.respuesta("GET", "/resolution/info", {
            "unsupported": ["os"], "unhealthy": ["docker"], "suggestions": [],
            "issues": [{"type": "free_space", "context": "system", "reference": None,
                        "uuid": "u1"}], "checks": []})
        r = await self._bloqueada("unhealthy")
        self.assertEqual(r["preview"]["system_health"], {
            "unhealthy": ["docker"], "unsupported": ["os"],
            "issues": [{"type": "free_space", "context": "system"}], "unavailable": False})

    async def test_supervisor_pendiente(self) -> None:
        info = dict(self.sv.json[("GET", "/supervisor/info")])
        info["update_available"] = True
        self.sv.respuesta("GET", "/supervisor/info", info)
        await self._bloqueada("supervisor_update_pending")

    async def test_plugins_desactualizados_sin_auto_update(self) -> None:
        con_plugin_desactualizado(self.sv, "cli")
        info = dict(self.sv.json[("GET", "/supervisor/info")])
        info["auto_update"] = False
        self.sv.respuesta("GET", "/supervisor/info", info)
        await self._bloqueada("plugins_outdated")

    async def test_plugins_desactualizados_con_auto_update(self) -> None:
        con_plugin_desactualizado(self.sv, "cli")
        r = await self.vista_previa()
        self.assertIn("confirmation_token", r)
        self.assertEqual(r["preview"]["plugins_to_update_first"], ["cli"])
        self.assertTrue(any("cli" in a for a in r["preview"]["warnings"]))

    async def test_poco_disco(self) -> None:
        self.sv.respuesta("GET", "/host/info", {"disk_free": 1.2})
        await self._bloqueada("low_disk_space")

    async def test_configuracion_invalida(self) -> None:
        self.sv.respuesta("POST", "/core/check", HAConnectionError(
            "Supervisor REST POST http://supervisor/core/check failed 400: "
            '{"result": "error", "message": "Invalid config for [light]"}', status=400))
        r = await self._bloqueada("config_invalid")
        self.assertEqual(r["preview"]["config_check"]["result"], "error")
        self.assertIn("Invalid config", r["preview"]["config_check"]["details"])

    async def test_configuracion_sin_respuesta(self) -> None:
        self.sv.respuesta("POST", "/core/check", TimeoutError())
        r = await self._bloqueada("config_check_failed")
        self.assertEqual(r["preview"]["config_check"]["result"], "timeout")
        self.sv.respuesta("POST", "/core/check", HAConnectionError("caído", status=502))
        r = await self._bloqueada("config_check_failed")
        self.assertEqual(r["preview"]["config_check"]["result"], "unavailable")

    async def _sin_token(self, codigo: str, **kw: Any) -> dict[str, Any]:
        r = await self.vista_previa(**kw)
        self.assertEqual(r["error"], codigo, r)
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.posts_de_actualizacion(), [])
        return r

    async def test_ya_instalada(self) -> None:
        await self._sin_token("already_installed", version=CORE_ACTUAL)

    async def test_sin_actualizacion(self) -> None:
        info = dict(self.sv.json[("GET", "/core/info")])
        info.update(version_latest=CORE_ACTUAL, update_available=False)
        self.sv.respuesta("GET", "/core/info", info)
        await self._sin_token("no_update_available")

    async def test_versiones_ilegibles(self) -> None:
        self.sv.respuesta("GET", "/core/info", HAConnectionError("Supervisor error: x"))
        await self._sin_token("versions_unavailable")
        info = dict(sistema_sano(SupervisorActualizaciones()).json[("GET", "/core/info")])
        info["version_latest"] = None
        self.sv.respuesta("GET", "/core/info", info)
        await self._sin_token("versions_unavailable")

    async def test_argumento_invalido_sin_llamar_y_sin_copiarlo(self) -> None:
        with capture_logs() as logs:
            r = await self._sin_token("invalid_argument", version="../centinela-version")
        self.assertEqual(self.sv.llamadas, [])
        self.assertNotIn("centinela-version", json.dumps(r) + repr(logs))
        self.assertIn("^[0-9][0-9A-Za-z.]{0,31}$", r["detail"])

    async def test_bajar_de_version(self) -> None:
        r = await self.vista_previa(version="2026.10.2")
        p = r["preview"]
        self.assertIs(p["downgrade"], True)
        self.assertTrue(any("downgrade" in a.lower() for a in p["warnings"]))
        self.assertIn("confirmation_token", r)

    async def test_version_no_comparable(self) -> None:
        r = await self.vista_previa(version="2026.12.0x")
        self.assertIsNone(r["preview"]["downgrade"])
        self.assertTrue(any("compare" in a for a in r["preview"]["warnings"]))


# ── sv_update_core: ejecución y token atado (FR-005, FR-008, FR-018) ─────────


class TestUpdateCore(_Base):
    async def test_confirmar_envia_la_version_explicita(self) -> None:
        r = await self.vista_previa()
        token = r["confirmation_token"]
        self.sv.llamadas.clear()
        with capture_logs() as logs:
            r = await self.t["sv_update_core"](confirmation_token=token)
        self.assertEqual(r, {"job_id": _JOB, "status": "running",
                             "poll_with": "sv_get_job_status",
                             "from_version": CORE_ACTUAL, "to_version": CORE_ULTIMA})
        posts = [c for c in self.sv.llamadas if c["metodo"] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["ruta"], "/core/update")
        self.assertEqual(posts[0]["cuerpo"],
                         {"version": CORE_ULTIMA, "backup": True, "background": True})
        jobs = json.loads(addons_mod._PENDING_JOBS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(jobs[_JOB]["op"], "update_core")
        self.assertEqual((jobs[_JOB]["from"], jobs[_JOB]["to"]), (CORE_ACTUAL, CORE_ULTIMA))
        eventos = [e for e in logs if e["event"] == "system_update_started"]
        self.assertEqual(len(eventos), 1)
        self.assertEqual(
            {k: eventos[0][k] for k in ("tool", "component", "from_version",
                                         "to_version", "job_id")},
            {"tool": "sv_update_core", "component": "core", "from_version": CORE_ACTUAL,
             "to_version": CORE_ULTIMA, "job_id": _JOB})
        # Y el token ya no sirve.
        r = await self.t["sv_update_core"](confirmation_token=token)
        self.assertIn("error", r)
        self.assertEqual(len(self.posts_de_actualizacion()), 1)

    async def test_con_version_y_sin_backup(self) -> None:
        r = await self.vista_previa(version="2026.11.2", backup=False)
        self.sv.llamadas.clear()
        await self.t["sv_update_core"](version="2026.11.2", backup=False,
                                       confirmation_token=r["confirmation_token"])
        cuerpo = [c["cuerpo"] for c in self.sv.llamadas if c["ruta"] == "/core/update"]
        self.assertEqual(cuerpo, [{"version": "2026.11.2", "backup": False,
                                   "background": True}])

    async def test_sin_job_id(self) -> None:
        self.sv.respuesta("POST", "/core/update", {})
        r = await self.vista_previa()
        r = await self.t["sv_update_core"](confirmation_token=r["confirmation_token"])
        self.assertEqual(r, {"result": "ok", "from_version": CORE_ACTUAL,
                             "to_version": CORE_ULTIMA})

    async def test_error_del_supervisor_redactado(self) -> None:
        self.sv.respuesta("POST", "/core/update", HAConnectionError(
            f"Supervisor error: password: {CENTINELA_PASSWORD} token {CENTINELA_JWT}"))
        r = await self.vista_previa()
        token = r["confirmation_token"]
        with capture_logs() as logs:
            r = await self.t["sv_update_core"](confirmation_token=token)
        self.assertEqual(r["error"], "supervisor_error")
        texto = json.dumps(r) + repr(logs)
        self.assertNotIn(CENTINELA_PASSWORD, texto)
        self.assertNotIn(CENTINELA_JWT, texto)
        datos = json.loads((security.CONFIRMATIONS_DIR / f"{token}.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(datos["state"], "failed")

    async def test_detalle_de_check_redactado(self) -> None:
        self.sv.respuesta("POST", "/core/check", HAConnectionError(
            f"Supervisor error: Invalid config: password: {CENTINELA_PASSWORD} "
            f"Authorization: Bearer {CENTINELA_JWT} " + "x" * 2000, status=400))
        with capture_logs() as logs:
            r = await self.vista_previa()
        texto = json.dumps(r) + repr(logs)
        self.assertNotIn(CENTINELA_PASSWORD, texto)
        self.assertNotIn(CENTINELA_JWT, texto)
        self.assertLessEqual(len(r["preview"]["config_check"]["details"]), 500)
        # Ni el detalle en el log, aunque esté redactado (FR-018).
        self.assertNotIn("Invalid config", repr(logs))


class TestTokenAtado(_Base):
    async def test_version_cambiada_entre_vista_previa_y_confirmacion(self) -> None:
        r = await self.vista_previa()
        token = r["confirmation_token"]
        info = dict(self.sv.json[("GET", "/core/info")])
        info["version_latest"] = "2026.12.1"
        self.sv.respuesta("GET", "/core/info", info)
        self.sv.llamadas.clear()
        r = await self.t["sv_update_core"](confirmation_token=token)
        self.assertIs(r["preview_outdated"], True)
        self.assertIn("does not match", r["error"])
        self.assertIn("versions", r["hint"])
        self.assertEqual(self.sv.posts(), [])
        datos = json.loads((security.CONFIRMATIONS_DIR / f"{token}.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(datos["state"], "pending")

    async def test_version_instalada_cambiada(self) -> None:
        r = await self.vista_previa()
        info = dict(self.sv.json[("GET", "/core/info")])
        info["version"] = "2026.11.2"
        self.sv.respuesta("GET", "/core/info", info)
        r = await self.t["sv_update_core"](confirmation_token=r["confirmation_token"])
        self.assertIs(r["preview_outdated"], True)
        self.assertEqual(self.posts_de_actualizacion(), [])

    async def test_argumentos_distintos(self) -> None:
        r = await self.vista_previa()
        token = r["confirmation_token"]
        for kw in ({"backup": False}, {"version": CORE_ULTIMA}):
            with self.subTest(kw=kw):
                r = await self.t["sv_update_core"](confirmation_token=token, **kw)
                self.assertIs(r["preview_outdated"], True)
        self.assertEqual(self.posts_de_actualizacion(), [])
        # El token sigue pendiente: con los argumentos de la vista previa vale.
        r = await self.t["sv_update_core"](confirmation_token=token)
        self.assertEqual(r["status"], "running")

    async def test_versiones_ilegibles_al_confirmar(self) -> None:
        r = await self.vista_previa()
        token = r["confirmation_token"]
        self.sv.respuesta("GET", "/core/info", HAConnectionError("Supervisor error: x"))
        r = await self.t["sv_update_core"](confirmation_token=token)
        self.assertEqual(r["error"], "versions_unavailable")
        self.assertEqual(self.posts_de_actualizacion(), [])

    async def test_confirmar_no_repite_la_comprobacion(self) -> None:
        r = await self.vista_previa()
        self.sv.llamadas.clear()
        await self.t["sv_update_core"](confirmation_token=r["confirmation_token"])
        self.assertEqual(self.sv.rutas(), [("GET", "/core/info"), ("POST", "/core/update")])


# ── Tramo 2: OS y Supervisor (FR-003, FR-004, FR-006…FR-009, FR-018) ─────────

_JOB_OS = "1b2c3d4e5f60718293a4b5c6d7e8f901"
_JOB_SUP = "2c3d4e5f60718293a4b5c6d7e8f90123"


class _BaseOsSup(_Base):
    """OS 16.2 → 16.3 y Supervisor con actualización; el Supervisor ya al día
    para el OS salvo que el test diga otra cosa. Reloj y espera falsos: la
    búsqueda del job avanza el reloj sin dormir de verdad."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        con_os_y_supervisor_desactualizados(self.sv)
        self.ahora = 0.0

        async def dormir(segundos: float) -> None:
            self.ahora += segundos
            await asyncio.sleep(0)

        self._parches += [
            mock.patch.object(mod, "_reloj", lambda: self.ahora),
            mock.patch.object(mod, "_dormir", dormir),
        ]
        for p in self._parches[-2:]:
            p.start()
        self.soltar = asyncio.Event()

    async def asyncTearDown(self) -> None:
        self.soltar.set()
        await self.fondo()
        await super().asyncTearDown()

    async def fondo(self) -> list[dict[str, Any]]:
        """Espera a que terminen las tareas de fondo y da sus resultados."""
        return list(await asyncio.gather(*list(mod._TAREAS_DE_FONDO)))

    def peticion_lenta(self, ruta: str, *, al_final: BaseException | None = None) -> None:
        """La petición de actualización queda en curso hasta `self.soltar`."""
        async def lenta() -> dict[str, Any]:
            await self.soltar.wait()
            if al_final is not None:
                raise al_final
            return {}
        self.sv.respuesta("POST", ruta, lenta)

    def jobs(self, *lista: dict[str, Any], previos: tuple[dict[str, Any], ...] = ()) -> None:
        """`/jobs/info`: `previos` están desde el principio (otra
        actualización ya en marcha); `lista` aparece solo DESPUÉS de que
        Hermes mande la petición de actualización, como en el Supervisor real
        (el job nace con la petición). Así la vista previa y la lectura de
        antes de lanzar (T047) no los ven."""
        def responder() -> dict[str, Any]:
            lanzada = any(c["metodo"] == "POST" and c["ruta"] in ("/os/update",
                                                                  "/supervisor/update")
                          for c in self.sv.llamadas)
            return {"ignore_conditions": [],
                    "jobs": [*previos, *(lista if lanzada else ())]}
        self.sv.respuesta("GET", "/jobs/info", responder)

    def posts_de(self, ruta: str) -> list[dict[str, Any]]:
        return [c for c in self.sv.llamadas if c["metodo"] == "POST" and c["ruta"] == ruta]

    def estado_token(self, token: str) -> str:
        return json.loads((security.CONFIRMATIONS_DIR / f"{token}.json")
                          .read_text(encoding="utf-8"))["state"]


class TestUpdateOs(_BaseOsSup):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        sin_supervisor_pendiente(self.sv)

    async def test_bloques_de_la_vista_previa(self) -> None:
        r = await self.t["sv_update_os"]()
        self.assertIn("confirmation_token", r)
        p = r["preview"]
        self.assertEqual((p["action"], p["component"]), ("update_os", "os"))
        self.assertEqual((p["from_version"], p["to_version"]), (OS_ACTUAL, OS_ULTIMA))
        self.assertIs(p["downgrade"], False)
        # El aviso de reinicio de la entidad del OS es lo único que Core da.
        self.assertEqual(p["release_notes"]["text"], AVISO_REINICIO_OS)
        self.assertIs(p["release_notes"]["available"], False)
        self.assertEqual(p["release_notes"]["release_url"], URL_NOTAS_OS)
        # Instalar no reinicia nada; aplicarlo reinicia el host, y la vista
        # previa lo dice sin rodeos.
        self.assertEqual(p["restarts"]["components"], [])
        self.assertIn("sv_reboot_host", p["restarts"]["after"])
        for frase in ("inactive boot slot", "NOT running until the host reboots",
                      "restarts EVERYTHING", "Hermes", "reboot_required"):
            self.assertIn(frase, p["restarts"]["description"])
        self.assertTrue(p["warnings"][0].startswith("applying this update needs a host reboot"))
        self.assertIn("the Supervisor also checks internet access when it runs", p["warnings"])
        # D-2: sin backup, con la pista.
        self.assertEqual((p["backup"]["will_create"], p["backup"]["possible"]), (False, False))
        self.assertIn("sv_create_backup_full", p["backup"]["hint"])
        self.assertEqual(p["system_health"]["unavailable"], False)
        self.assertEqual(p["blocked"], [])
        self.assertNotIn("config_check", p)
        self.assertEqual(self.sv.posts(), [])

    async def test_sin_haos(self) -> None:
        self.sv.respuesta("GET", "/os/info", error_404("GET", "/os/info"))
        r = await self.t["sv_update_os"]()
        self.assertEqual(r["error"], "not_haos")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.rutas(), [("GET", "/os/info")])

    async def test_os_info_ilegible(self) -> None:
        self.sv.respuesta("GET", "/os/info", HAConnectionError("caído", status=502))
        r = await self.t["sv_update_os"]()
        self.assertEqual(r["error"], "versions_unavailable")
        self.assertEqual(self.sv.posts(), [])

    async def test_reinicio_pendiente(self) -> None:
        info = dict(self.sv.json[("GET", "/os/info")])
        info["version_pending"] = OS_ULTIMA
        self.sv.respuesta("GET", "/os/info", info)
        r = await self.t["sv_update_os"]()
        self.assertEqual(r["error"], "update_blocked")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual([b["code"] for b in r["preview"]["blocked"]], ["reboot_pending"])
        self.assertEqual(self.sv.posts(), [])

    async def test_otra_version_pendiente_avisa(self) -> None:
        info = dict(self.sv.json[("GET", "/os/info")])
        info.update(version_pending="16.25", version_latest="16.4")
        self.sv.respuesta("GET", "/os/info", info)
        r = await self.t["sv_update_os"]()
        self.assertIn("confirmation_token", r)
        self.assertTrue(any("16.25" in a and "replaces" in a for a in r["preview"]["warnings"]))

    async def test_supervisor_pendiente_bloquea(self) -> None:
        con_os_y_supervisor_desactualizados(self.sv)
        r = await self.t["sv_update_os"]()
        self.assertEqual(r["error"], "update_blocked")
        self.assertIn("supervisor_update_pending", [b["code"] for b in r["preview"]["blocked"]])
        self.assertNotIn("confirmation_token", r)

    async def test_no_saludable_bloquea(self) -> None:
        self.sv.respuesta("GET", "/resolution/info", {
            "unsupported": [], "unhealthy": ["docker"], "suggestions": [], "issues": [],
            "checks": []})
        r = await self.t["sv_update_os"]()
        self.assertEqual(r["error"], "update_blocked")
        self.assertEqual([b["code"] for b in r["preview"]["blocked"]], ["unhealthy"])

    async def test_core_caido_sin_notas_pero_con_token(self) -> None:
        self.sv.core_caido = True
        r = await self.t["sv_update_os"]()
        self.assertIn("confirmation_token", r)
        notas = r["preview"]["release_notes"]
        self.assertEqual((notas["text"], notas["release_url"]), (None, None))
        self.assertIn("did not respond", notas["reason"])

    async def test_ya_instalada_y_sin_actualizacion(self) -> None:
        r = await self.t["sv_update_os"](version=OS_ACTUAL)
        self.assertEqual(r["error"], "already_installed")
        info = dict(self.sv.json[("GET", "/os/info")])
        info["version_latest"] = OS_ACTUAL
        self.sv.respuesta("GET", "/os/info", info)
        r = await self.t["sv_update_os"]()
        self.assertEqual(r["error"], "no_update_available")
        self.assertEqual(self.sv.posts(), [])

    async def test_argumento_invalido(self) -> None:
        r = await self.t["sv_update_os"](version="16.3/../x")
        self.assertEqual(r["error"], "invalid_argument")
        self.assertEqual(self.sv.llamadas, [])

    async def test_bajar_de_version(self) -> None:
        r = await self.t["sv_update_os"](version="15.2")
        self.assertIs(r["preview"]["downgrade"], True)
        self.assertTrue(any("downgrade" in a for a in r["preview"]["warnings"]))


class TestUpdateSupervisor(_BaseOsSup):
    def test_sin_argumento_version(self) -> None:
        import inspect
        params = set(inspect.signature(self.t["sv_update_supervisor"]).parameters)
        self.assertEqual(params, {"confirmation_token"})

    async def test_bloques_de_la_vista_previa(self) -> None:
        r = await self.t["sv_update_supervisor"]()
        self.assertIn("confirmation_token", r)
        p = r["preview"]
        self.assertEqual((p["action"], p["component"]), ("update_supervisor", "supervisor"))
        self.assertEqual((p["from_version"], p["to_version"]),
                         (SUPERVISOR_ACTUAL, SUPERVISOR_ULTIMA))
        self.assertEqual(p["channel"], "stable")
        self.assertEqual(p["restarts"]["components"], ["supervisor"])
        self.assertIn("Core and apps are not restarted", p["restarts"]["description"])
        self.assertIn("sv_* tools fail", p["restarts"]["description"])
        self.assertEqual((p["backup"]["will_create"], p["backup"]["possible"]), (False, False))
        self.assertEqual(p["release_notes"]["release_url"], URL_NOTAS_SUPERVISOR)
        self.assertIsNone(p["release_notes"]["text"])
        self.assertEqual(p["blocked"], [])
        self.assertTrue(any("sv_get_supervisor_info" in a for a in p["warnings"]))
        self.assertEqual(self.sv.posts(), [])

    async def test_sin_actualizacion(self) -> None:
        sin_supervisor_pendiente(self.sv)
        r = await self.t["sv_update_supervisor"]()
        self.assertEqual(r["error"], "no_update_available")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.posts(), [])

    async def test_no_saludable_no_bloquea(self) -> None:
        # `supervisor_update` no tiene condiciones (R-6): se enseña, no bloquea.
        self.sv.respuesta("GET", "/resolution/info", {
            "unsupported": [], "unhealthy": ["docker"], "suggestions": [], "issues": [],
            "checks": []})
        r = await self.t["sv_update_supervisor"]()
        self.assertIn("confirmation_token", r)
        self.assertEqual(r["preview"]["system_health"]["unhealthy"], ["docker"])

    async def test_info_ilegible(self) -> None:
        self.sv.respuesta("GET", "/supervisor/info", HAConnectionError("caído", status=502))
        r = await self.t["sv_update_supervisor"]()
        self.assertEqual(r["error"], "versions_unavailable")
        self.assertEqual(self.sv.posts(), [])


class TestSegundoPlano(_BaseOsSup):
    """La confirmación lanza la petición en una tarea de fondo y devuelve el
    job (FR-009). Controles negativos (T028): (a) esperar la petición en
    primer plano → `test_responde_sin_esperar_la_peticion`; (b) no guardar la
    referencia → `test_referencia_guardada_y_soltada`; (e) tratar el corte
    como error → los dos de corte; (f) sin redacción del error de fondo →
    `test_error_de_fondo_redactado`."""

    async def confirmar_os(self, **kw: Any) -> tuple[str, dict[str, Any]]:
        sin_supervisor_pendiente(self.sv)
        r = await self.t["sv_update_os"](**kw)
        token = r["confirmation_token"]
        self.sv.llamadas.clear()
        return token, await self.t["sv_update_os"](confirmation_token=token, **kw)

    async def confirmar_supervisor(self) -> tuple[str, dict[str, Any]]:
        r = await self.t["sv_update_supervisor"]()
        token = r["confirmation_token"]
        self.sv.llamadas.clear()
        return token, await self.t["sv_update_supervisor"](confirmation_token=token)

    async def test_os_con_job(self) -> None:
        self.peticion_lenta("/os/update")
        self.jobs(job("otro_job", "ffff"), job("os_manager_update", _JOB_OS))
        with capture_logs() as logs:
            token, r = await self.confirmar_os()
            self.assertEqual(r["job_id"], _JOB_OS)
            self.assertEqual((r["status"], r["poll_with"]), ("running", "sv_get_job_status"))
            self.assertEqual((r["from_version"], r["to_version"]), (OS_ACTUAL, OS_ULTIMA))
            self.assertIn("sv_reboot_host", r["after"])
            self.assertIn("restarts EVERYTHING", r["after"])
            posts = self.posts_de("/os/update")
            self.assertEqual(len(posts), 1)
            self.assertEqual((posts[0]["cuerpo"], posts[0]["timeout"]),
                             ({"version": OS_ULTIMA}, 1800))
            jobs = json.loads(addons_mod._PENDING_JOBS_PATH.read_text(encoding="utf-8"))
            self.assertEqual((jobs[_JOB_OS]["op"], jobs[_JOB_OS]["from"], jobs[_JOB_OS]["to"]),
                             ("update_os", OS_ACTUAL, OS_ULTIMA))
            self.assertEqual(self.estado_token(token), "completed")
            self.soltar.set()
            self.assertEqual(await self.fondo(), [{"outcome": "ok"}])
        inicio = [e for e in logs if e["event"] == "system_update_started"]
        self.assertEqual((inicio[0]["job_id"], inicio[0]["job_found"]), (_JOB_OS, True))
        fin = [e for e in logs if e["event"] == "system_update_finished"]
        self.assertEqual([e["outcome"] for e in fin], ["ok"])

    async def test_responde_sin_esperar_la_peticion(self) -> None:
        self.peticion_lenta("/os/update")
        self.jobs(job("os_manager_update", _JOB_OS))
        _token, r = await self.confirmar_os()
        self.assertEqual(r["status"], "running")
        # La respuesta llegó con la petición todavía en curso.
        self.assertEqual(len(mod._TAREAS_DE_FONDO), 1)
        self.assertFalse(next(iter(mod._TAREAS_DE_FONDO)).done())

    async def test_referencia_guardada_y_soltada(self) -> None:
        self.peticion_lenta("/os/update")
        self.jobs(job("os_manager_update", _JOB_OS))
        await self.confirmar_os()
        tareas = set(mod._TAREAS_DE_FONDO)
        self.assertEqual(len(tareas), 1)
        self.soltar.set()
        await asyncio.gather(*tareas)
        await asyncio.sleep(0)  # el callback de fin corre en la siguiente vuelta
        self.assertEqual(mod._TAREAS_DE_FONDO, set())

    async def test_job_que_no_aparece(self) -> None:
        self.peticion_lenta("/os/update")
        # Uno terminado con el mismo nombre (otra actualización) no vale.
        self.jobs(job("os_manager_update", "eeee", done=True))
        token, r = await self.confirmar_os()
        self.assertEqual(r["status"], "started")
        self.assertEqual(r["verify_with"], "sv_get_os_info")
        self.assertNotIn("job_id", r)
        self.assertGreaterEqual(self.ahora, 10)
        self.assertLessEqual(self.ahora, 11)
        lecturas = [c for c in self.sv.llamadas if c["ruta"] == "/jobs/info"]
        self.assertGreater(len(lecturas), 5)
        self.assertFalse(addons_mod._PENDING_JOBS_PATH.exists())
        self.assertEqual(self.estado_token(token), "completed")

    async def test_job_entre_los_hijos(self) -> None:
        self.peticion_lenta("/os/update")
        self.jobs(job("padre", "aaaa", hijos=[job("os_manager_update", _JOB_OS)]))
        _token, r = await self.confirmar_os()
        self.assertEqual(r["job_id"], _JOB_OS)

    async def test_supervisor_con_job(self) -> None:
        self.peticion_lenta("/supervisor/update")
        self.jobs(job("supervisor_update", _JOB_SUP))
        _token, r = await self.confirmar_supervisor()
        self.assertEqual(r["job_id"], _JOB_SUP)
        self.assertIn("sv_get_supervisor_info", r["note"])
        self.assertIn("disappears", r["note"])
        posts = self.posts_de("/supervisor/update")
        self.assertEqual(len(posts), 1)
        self.assertIsNone(posts[0]["cuerpo"])
        self.assertEqual(posts[0]["timeout"], 1800)
        jobs = json.loads(addons_mod._PENDING_JOBS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(jobs[_JOB_SUP]["op"], "update_supervisor")

    async def test_corte_al_momento_no_es_error(self) -> None:
        # El Supervisor se reinicia y corta antes de que se vea el job.
        self.sv.respuesta("POST", "/supervisor/update", aiohttp.ServerDisconnectedError())
        with capture_logs() as logs:
            token, r = await self.confirmar_supervisor()
        self.assertNotIn("error", r)
        self.assertEqual((r["status"], r["verify_with"]), ("started", "sv_get_supervisor_info"))
        self.assertEqual(self.estado_token(token), "completed")
        self.assertEqual([e["outcome"] for e in logs if e["event"] == "system_update_finished"],
                         ["connection_lost"])
        self.assertEqual([e for e in logs if e["event"] == "system_update_failed"], [])

    async def test_corte_despues_de_responder(self) -> None:
        self.peticion_lenta("/supervisor/update", al_final=aiohttp.ServerDisconnectedError())
        self.jobs(job("supervisor_update", _JOB_SUP))
        with capture_logs() as logs:
            _token, r = await self.confirmar_supervisor()
            antes = dict(r)
            self.soltar.set()
            resultados = await self.fondo()
        # Sin excepción sin recoger: la tarea termina con su resultado.
        self.assertEqual(resultados, [{"outcome": "connection_lost"}])
        self.assertEqual(r, antes)
        self.assertEqual([e["outcome"] for e in logs if e["event"] == "system_update_finished"],
                         ["connection_lost"])
        self.assertEqual([e for e in logs if e["event"] == "system_update_failed"], [])

    async def test_error_de_fondo_redactado(self) -> None:
        self.peticion_lenta("/os/update", al_final=HAConnectionError(
            f"Supervisor error: password: {CENTINELA_PASSWORD} Bearer {CENTINELA_JWT}"))
        self.jobs(job("os_manager_update", _JOB_OS))
        with capture_logs() as logs:
            _token, r = await self.confirmar_os()
            self.soltar.set()
            resultados = await self.fondo()
        self.assertEqual(r["status"], "running")
        self.assertEqual(resultados[0]["outcome"], "failed")
        fallos = [e for e in logs if e["event"] == "system_update_failed"]
        self.assertEqual(len(fallos), 1)
        self.assertEqual(fallos[0]["tool"], "sv_update_os")
        texto = repr(logs) + json.dumps(resultados)
        self.assertNotIn(CENTINELA_PASSWORD, texto)
        self.assertNotIn(CENTINELA_JWT, texto)

    async def test_rechazo_al_momento(self) -> None:
        self.sv.respuesta("POST", "/os/update", HAConnectionError(
            "Supervisor REST POST http://supervisor/os/update failed 400: "
            f'{{"result": "error", "message": "rechazada password: {CENTINELA_PASSWORD}"}}',
            status=400))
        with capture_logs() as logs:
            token, r = await self.confirmar_os()
        self.assertEqual(r["error"], "supervisor_error")
        self.assertIn("rechazada", r["detail"])
        self.assertNotIn(CENTINELA_PASSWORD, json.dumps(r) + repr(logs))
        self.assertEqual(self.estado_token(token), "failed")
        # Solo la lectura de ANTES de lanzar (T047): el rechazo se ve antes de
        # buscar el job.
        rutas = [c["ruta"] for c in self.sv.llamadas]
        self.assertEqual([r for r in rutas if r == "/jobs/info"], ["/jobs/info"])
        self.assertLess(rutas.index("/jobs/info"), rutas.index("/os/update"))

    async def test_version_del_os_cambiada(self) -> None:
        sin_supervisor_pendiente(self.sv)
        r = await self.t["sv_update_os"]()
        token = r["confirmation_token"]
        info = dict(self.sv.json[("GET", "/os/info")])
        info["version_latest"] = "16.4"
        self.sv.respuesta("GET", "/os/info", info)
        r = await self.t["sv_update_os"](confirmation_token=token)
        self.assertIs(r["preview_outdated"], True)
        self.assertEqual(self.sv.posts(), [])
        self.assertEqual(mod._TAREAS_DE_FONDO, set())
        self.assertEqual(self.estado_token(token), "pending")
        # Con otra `version` que la de la vista previa, igual.
        r = await self.t["sv_update_os"](version=OS_ULTIMA, confirmation_token=token)
        self.assertIs(r["preview_outdated"], True)
        self.assertEqual(self.sv.posts(), [])

    async def test_version_del_supervisor_cambiada(self) -> None:
        r = await self.t["sv_update_supervisor"]()
        token = r["confirmation_token"]
        info = dict(self.sv.json[("GET", "/supervisor/info")])
        info["version_latest"] = "2026.11.2"
        self.sv.respuesta("GET", "/supervisor/info", info)
        r = await self.t["sv_update_supervisor"](confirmation_token=token)
        self.assertIs(r["preview_outdated"], True)
        self.assertEqual(self.sv.posts(), [])

    async def test_os_con_version_explicita(self) -> None:
        self.peticion_lenta("/os/update")
        self.jobs(job("os_manager_update", _JOB_OS))
        _token, r = await self.confirmar_os(version="15.2")
        self.assertEqual(r["to_version"], "15.2")
        self.assertEqual(self.posts_de("/os/update")[0]["cuerpo"], {"version": "15.2"})


_JOB_AJENO = "aaaa1111aaaa1111aaaa1111aaaa1111"
_RECHAZO_OCUPADO = HAConnectionError(
    "Supervisor REST POST http://supervisor/os/update failed 400: "
    '{"result": "error", "message": "Another job is running"}', status=400)


class TestJobAjeno(_BaseOsSup):
    """T047: otra actualización del OS ya en marcha (de la interfaz o de otra
    llamada). Antes, la vista previa daba token y la confirmación tomaba el
    job ajeno por el suyo (`status: running` con el `to_version` de SU vista
    previa) mientras el Supervisor rechazaba su petición
    (`JobConcurrency.REJECT`), cosa que solo quedaba en el log.

    Controles negativos (comprobados): (a) quitar el bloqueo de la vista
    previa → los dos `test_vista_previa_bloquea*` en rojo (sale token); (b)
    no excluir los jobs previos (`excluir_previos=False` en `sv_update_os`) →
    `test_rechazo_que_tarda_un_poco` (el escenario de la revisión),
    `test_job_ajeno_y_peticion_lenta`, `test_job_ajeno_sin_el_propio_es_started`
    y `test_jobs_ilegibles_antes` en rojo (`job_id` ajeno); (c) adoptar jobs
    cuando no se pudieron leer antes → `test_jobs_ilegibles_antes` en rojo.
    Con el rechazo inmediato del Supervisor
    (`test_confirmacion_no_adopta_el_job_ajeno`) la respuesta ya era
    `supervisor_error` aun sin (b): la tarea de fondo se mira antes que los
    jobs."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        sin_supervisor_pendiente(self.sv)

    async def test_vista_previa_bloquea(self) -> None:
        self.jobs(previos=(job("os_manager_update", _JOB_AJENO),))
        r = await self.t["sv_update_os"]()
        self.assertEqual(r["error"], "update_in_progress")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual((r["job_id"], r["poll_with"]), (_JOB_AJENO, "sv_get_job_status"))
        self.assertEqual(self.sv.posts(), [])

    async def test_vista_previa_bloquea_con_el_job_entre_los_hijos(self) -> None:
        self.jobs(previos=(job("padre", "bbbb", hijos=[job("os_manager_update", _JOB_AJENO)]),))
        r = await self.t["sv_update_os"]()
        self.assertEqual(r["error"], "update_in_progress")

    async def test_job_terminado_u_otro_no_bloquea(self) -> None:
        self.jobs(previos=(job("os_manager_update", _JOB_AJENO, done=True),
                           job("supervisor_update", "cccc")))
        r = await self.t["sv_update_os"]()
        self.assertIn("confirmation_token", r)
        self.assertFalse(any("/jobs/info" in a for a in r["preview"]["warnings"]))

    async def test_jobs_ilegibles_en_la_vista_previa_avisa(self) -> None:
        self.sv.respuesta("GET", "/jobs/info", HAConnectionError("caído", status=502))
        r = await self.t["sv_update_os"]()
        self.assertIn("confirmation_token", r)
        self.assertTrue(any("/jobs/info" in a for a in r["preview"]["warnings"]))

    async def test_confirmacion_no_adopta_el_job_ajeno(self) -> None:
        # El job ajeno aparece entre la vista previa y la confirmación; el
        # Supervisor rechaza la petición de Hermes al momento.
        r = await self.t["sv_update_os"]()
        token = r["confirmation_token"]
        self.jobs(previos=(job("os_manager_update", _JOB_AJENO),))
        self.sv.respuesta("POST", "/os/update", _RECHAZO_OCUPADO)
        r = await self.t["sv_update_os"](confirmation_token=token)
        self.assertEqual(r["error"], "supervisor_error")
        self.assertIn("Another job is running", r["detail"])
        self.assertNotIn("job_id", r)
        self.assertNotIn("status", r)
        self.assertEqual(self.estado_token(token), "failed")
        self.assertFalse(addons_mod._PENDING_JOBS_PATH.exists())

    async def test_rechazo_que_tarda_un_poco(self) -> None:
        # El escenario de la revisión: el rechazo del Supervisor vuelve
        # después de que Hermes ya haya leído `/jobs/info` (con el job ajeno
        # dentro). La respuesta tiene que ser el rechazo, no `running`.
        r = await self.t["sv_update_os"]()
        token = r["confirmation_token"]
        self.jobs(previos=(job("os_manager_update", _JOB_AJENO),))

        async def rechazo_tardio() -> Any:
            # `soltar` (lo pone el tearDown) evita colgarse si la tool ya
            # respondió y el reloj falso no avanza más.
            while self.ahora < 2 and not self.soltar.is_set():
                await asyncio.sleep(0)
            raise _RECHAZO_OCUPADO

        self.sv.respuesta("POST", "/os/update", rechazo_tardio)
        r = await self.t["sv_update_os"](confirmation_token=token)
        self.assertEqual(r["error"], "supervisor_error", r)
        self.assertIn("Another job is running", r["detail"])
        self.assertEqual(self.estado_token(token), "failed")
        lecturas = [c for c in self.sv.llamadas if c["ruta"] == "/jobs/info"]
        self.assertGreater(len(lecturas), 2)

    async def test_job_ajeno_y_peticion_lenta(self) -> None:
        # Aunque la petición tarde, el job ajeno nunca es el de Hermes: se
        # devuelve el suyo cuando aparece.
        r = await self.t["sv_update_os"]()
        token = r["confirmation_token"]
        self.peticion_lenta("/os/update")
        self.jobs(job("os_manager_update", _JOB_OS),
                  previos=(job("os_manager_update", _JOB_AJENO),))
        r = await self.t["sv_update_os"](confirmation_token=token)
        self.assertEqual(r["job_id"], _JOB_OS)

    async def test_job_ajeno_sin_el_propio_es_started(self) -> None:
        r = await self.t["sv_update_os"]()
        token = r["confirmation_token"]
        self.peticion_lenta("/os/update")
        self.jobs(previos=(job("os_manager_update", _JOB_AJENO),))
        r = await self.t["sv_update_os"](confirmation_token=token)
        self.assertEqual((r["status"], r["verify_with"]), ("started", "sv_get_os_info"))
        self.assertNotIn("job_id", r)

    async def test_jobs_ilegibles_antes(self) -> None:
        # Si no se pudieron leer los jobs ANTES de lanzar, no se sabe cuál es
        # el de Hermes: no se adopta ninguno.
        r = await self.t["sv_update_os"]()
        token = r["confirmation_token"]
        self.peticion_lenta("/os/update")

        def responder() -> dict[str, Any]:
            if not self.posts_de("/os/update"):
                raise HAConnectionError("caído", status=502)
            return {"ignore_conditions": [], "jobs": [job("os_manager_update", _JOB_AJENO)]}

        self.sv.respuesta("GET", "/jobs/info", responder)
        r = await self.t["sv_update_os"](confirmation_token=token)
        self.assertEqual(r["status"], "started")
        self.assertNotIn("job_id", r)

    async def test_supervisor_comparte_el_job_en_curso(self) -> None:
        # En el Supervisor no hay carrera: su API comparte la tarea en curso
        # (`detach`), así que el job que ya corría ES el que la petición de
        # Hermes espera. Ni bloqueo ni exclusión.
        con_os_y_supervisor_desactualizados(self.sv)
        self.jobs(previos=(job("supervisor_update", _JOB_SUP),))
        r = await self.t["sv_update_supervisor"]()
        token = r["confirmation_token"]
        self.peticion_lenta("/supervisor/update")
        r = await self.t["sv_update_supervisor"](confirmation_token=token)
        self.assertEqual(r["job_id"], _JOB_SUP)


if __name__ == "__main__":
    unittest.main()
