"""Host y OS del Supervisor (spec 032, tramo 1; CAP-086, FR-081 de la 008).

`sv_shutdown_host`, `sv_set_hostname`, `sv_set_swap` y `sv_set_boot_slot`
contra el Supervisor simulado de `tests/fixtures/supervisor_host.py` (forma y
comportamiento del Supervisor 2026.11.0, datos genéricos).

Lo que se vigila, además de cada petición exacta:

- las vistas previas solo leen (ninguna llamada que no sea GET) y dicen lo
  que va a pasar: nadie enciende el host a distancia, la ranura reinicia ya
  en otro OS, la swap pide reiniciar (FR-001…FR-004);
- todo argumento inválido se rechaza sin ninguna llamada y sin copiar el
  valor;
- el token ata los argumentos y la huella del estado que describe la vista
  previa, pero no el disco libre, que cambia solo (FR-011);
- un corte después de enviar no es ni «ok» ni un error a secas:
  `outcome: "unknown"` (FR-013);
- el log no lleva el hostname, la swap ni las versiones (FR-012).

Controles negativos del tramo 1 (T012), con recuentos, en el mensaje del
commit que añade este fichero y en `specs/032-host-y-red-del-host/tasks.md`.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

import aiohttp
from structlog.testing import capture_logs

from hermes.ha import HAConnectionError
from hermes.tools.host_control import register
from tests.fixtures.supervisor_host import (
    HOSTNAME_ACTUAL,
    HOSTNAME_NUEVO,
    SWAP_ACTUAL,
    VERSION_A,
    VERSION_B,
    SupervisorDeHost,
    core_state,
    corte,
    error_hostname_invalido,
    error_migracion,
    os_info_sin_haos,
)


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _texto(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, default=str)


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sv = SupervisorDeHost()
        self.mcp = DummyMCP()
        register(self.mcp, self.sv)
        self.t = self.mcp.tools

    async def _vista(self, tool: str, **kw: Any) -> dict[str, Any]:
        antes = len(self.sv.escrituras)
        vista = await self.t[tool](**kw)
        self.assertIn("confirmation_token", vista, vista)
        self.assertEqual(len(self.sv.escrituras), antes, "la vista previa escribió")
        return vista

    async def _confirmar(self, tool: str, **kw: Any) -> tuple[dict, dict]:
        vista = await self._vista(tool, **kw)
        hecho = await self.t[tool](**kw, confirmation_token=vista["confirmation_token"])
        return vista, hecho

    def _sin_llamadas(self) -> None:
        self.assertEqual(self.sv.llamadas, [])


# ── T004 (US1): apagar ───────────────────────────────────────────────────────


class TestApagar(_Base):
    async def test_vista_previa_con_el_aviso(self) -> None:
        vista = await self._vista("sv_shutdown_host")
        # Sin lecturas: no hay estado que describir.
        self._sin_llamadas()
        p = vista["preview"]
        self.assertEqual(p["action"], "shutdown_host")
        self.assertEqual(p["stops"], ["host", "home_assistant_core", "all_apps", "hermes"])
        self.assertIn("Nobody can power", p["warning"])
        self.assertIn("remotely", p["warning"])
        self.assertIn("physical access", p["warning"])
        self.assertIn("lost", p["connection"])

    async def test_confirmar_sin_force(self) -> None:
        _, hecho = await self._confirmar("sv_shutdown_host")
        self.assertEqual(hecho["result"], "ok", hecho)
        self.assertIn("shutdown initiated", hecho["note"])
        self.assertEqual(self.sv.escrituras, [
            {"metodo": "POST", "ruta": "/host/shutdown", "json_body": {}}])

    async def test_no_hay_argumento_force(self) -> None:
        with self.assertRaises(TypeError):
            await self.t["sv_shutdown_host"](force=True)

    async def test_migracion_en_curso_sin_reintento(self) -> None:
        self.sv.errores[("POST", "/host/shutdown")] = error_migracion()
        _, hecho = await self._confirmar("sv_shutdown_host")
        self.assertIn("migration in progress", hecho["error"])
        self.assertNotIn("outcome", hecho)
        # Una sola orden, sin `force`: no se reintenta saltándose la guarda.
        self.assertEqual(self.sv.escrituras, [
            {"metodo": "POST", "ruta": "/host/shutdown", "json_body": {}}])


# ── T004 (US2): hostname ─────────────────────────────────────────────────────


class TestHostname(_Base):
    async def test_vista_previa(self) -> None:
        vista = await self._vista("sv_set_hostname", hostname=HOSTNAME_NUEVO)
        p = vista["preview"]
        self.assertEqual((p["action"], p["from"], p["to"]),
                         ("set_hostname", HOSTNAME_ACTUAL, HOSTNAME_NUEVO))
        self.assertIn(".local", p["warning"])
        self.assertEqual([(c["metodo"], c["ruta"]) for c in self.sv.llamadas],
                         [("GET", "/host/info")])

    async def test_confirmar(self) -> None:
        _, hecho = await self._confirmar("sv_set_hostname", hostname=HOSTNAME_NUEVO)
        self.assertEqual(hecho, {"result": "ok", "hostname": HOSTNAME_NUEVO})
        self.assertEqual(self.sv.escrituras, [
            {"metodo": "POST", "ruta": "/host/options",
             "json_body": {"hostname": HOSTNAME_NUEVO}}])

    async def test_relectura_fallida(self) -> None:
        vista = await self._vista("sv_set_hostname", hostname=HOSTNAME_NUEVO)
        original = self.sv.sv_request
        enviado = False

        async def falla_al_releer(method: str, path: str, **kw: Any) -> Any:
            nonlocal enviado
            if enviado and method == "GET":
                raise corte()
            r = await original(method, path, **kw)
            enviado = enviado or method == "POST"
            return r

        self.sv.sv_request = falla_al_releer  # type: ignore[method-assign]
        hecho = await self.t["sv_set_hostname"](
            hostname=HOSTNAME_NUEVO, confirmation_token=vista["confirmation_token"])
        self.assertEqual(hecho["result"], "ok")
        self.assertIsNone(hecho["hostname"])
        self.assertEqual(hecho["verify_with"], "sv_get_host_info")

    async def test_invalidos_sin_llamar(self) -> None:
        for valor in ("Casa-HA", "casa ha", "casa.ha", "-casa", "casa-",
                      "a" * 64, "", 7, None, ["casa"]):
            with self.subTest(valor=valor):
                self.sv.llamadas.clear()
                r = await self.t["sv_set_hostname"](hostname=valor)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "hostname"))
                self.assertNotIn("confirmation_token", r)
                if isinstance(valor, str) and valor:
                    self.assertNotIn(valor, r["detail"])
                self._sin_llamadas()

    async def test_limites_validos(self) -> None:
        for valor in ("a", "a" * 63, "ha-1", "0ha"):
            with self.subTest(valor=valor):
                r = await self.t["sv_set_hostname"](hostname=valor)
                self.assertIn("confirmation_token", r, r)

    async def test_igual_al_actual(self) -> None:
        r = await self.t["sv_set_hostname"](hostname=HOSTNAME_ACTUAL)
        self.assertEqual(r["error"], "no_change")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras, [])

    async def test_lectura_fallida_o_forma_inesperada(self) -> None:
        self.sv.errores[("GET", "/host/info")] = corte()
        r = await self.t["sv_set_hostname"](hostname=HOSTNAME_NUEVO)
        self.assertIn("error", r)
        self.assertNotIn("confirmation_token", r)
        del self.sv.errores[("GET", "/host/info")]
        for forma in ([], {"disk_free": 1.0}, {"hostname": 5}):
            with self.subTest(forma=forma):
                self.sv.formas[("GET", "/host/info")] = forma
                r = await self.t["sv_set_hostname"](hostname=HOSTNAME_NUEVO)
                self.assertIn("unexpected", r["error"].lower())
                self.assertNotIn("confirmation_token", r)

    async def test_error_del_supervisor(self) -> None:
        self.sv.errores[("POST", "/host/options")] = error_hostname_invalido()
        _, hecho = await self._confirmar("sv_set_hostname", hostname=HOSTNAME_NUEVO)
        self.assertIn("Invalid hostname", hecho["error"])
        self.assertNotIn("outcome", hecho)


# ── T004 (US2): swap ─────────────────────────────────────────────────────────


class TestSwap(_Base):
    async def test_vista_previa(self) -> None:
        vista = await self._vista("sv_set_swap", swap_size="2G")
        p = vista["preview"]
        self.assertEqual(p["action"], "set_swap")
        self.assertEqual(p["changes"], {"swap_size": {"from": SWAP_ACTUAL, "to": "2G"}})
        self.assertEqual(p["disk_free_gib"], 20.5)
        self.assertIs(p["reboot_required"], True)
        self.assertNotIn("warning", p)
        self.assertEqual(sorted((c["metodo"], c["ruta"]) for c in self.sv.llamadas),
                         [("GET", "/host/info"), ("GET", "/os/config/swap")])

    async def test_confirmar_solo_lo_pasado(self) -> None:
        _, hecho = await self._confirmar("sv_set_swap", swappiness=60)
        self.assertEqual(self.sv.escrituras, [
            {"metodo": "POST", "ruta": "/os/config/swap",
             "json_body": {"swappiness": 60}}])
        self.assertEqual(hecho["result"], "ok")
        self.assertEqual(hecho["swap"], {"swap_size": SWAP_ACTUAL, "swappiness": 60})
        self.assertIs(hecho["reboot_required"], True)
        self.assertIn("sv_reboot_host", hecho["hint"])

    async def test_las_dos_claves(self) -> None:
        await self._confirmar("sv_set_swap", swap_size="512M", swappiness=10)
        self.assertEqual(self.sv.escrituras[0]["json_body"],
                         {"swap_size": "512M", "swappiness": 10})

    async def test_invalidos_sin_llamar(self) -> None:
        casos = [
            ({}, "swap_size"),
            ({"swap_size": "2T"}, "swap_size"),
            ({"swap_size": "-1"}, "swap_size"),
            ({"swap_size": "2 G"}, "swap_size"),
            ({"swap_size": 2}, "swap_size"),
            ({"swappiness": 201}, "swappiness"),
            ({"swappiness": -1}, "swappiness"),
            ({"swappiness": True}, "swappiness"),
            ({"swappiness": "60"}, "swappiness"),
        ]
        for kw, campo in casos:
            with self.subTest(kw=kw):
                self.sv.llamadas.clear()
                r = await self.t["sv_set_swap"](**kw)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", campo))
                for v in kw.values():
                    if isinstance(v, str):
                        self.assertNotIn(v, r["detail"])
                self._sin_llamadas()

    async def test_formas_validas_del_supervisor(self) -> None:
        for valor in ("0", "1024", "2G", "2GB", "2GiB", "512m", "100K", "10B"):
            with self.subTest(valor=valor):
                r = await self.t["sv_set_swap"](swap_size=valor)
                self.assertIn("confirmation_token", r, r)

    async def test_sin_cambios(self) -> None:
        for kw in ({"swap_size": SWAP_ACTUAL}, {"swap_size": "1024M"},
                   {"swappiness": 1}, {"swap_size": "1G", "swappiness": 1}):
            with self.subTest(kw=kw):
                r = await self.t["sv_set_swap"](**kw)
                self.assertEqual(r["error"], "no_change")
                self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras, [])

    async def test_disco_con_un_entero_enorme(self) -> None:
        # Cierre 1.2.0: `float()` de un entero enorme lanzaba `OverflowError`;
        # ahora es una forma inesperada, sin token. Control negativo
        # comprobado: con la comprobación de antes, la tool revienta.
        self.sv.host.update({"disk_free": 10**400})
        r = await self.t["sv_set_swap"](swap_size="2G")
        self.assertIn("unexpected", r["error"].lower())
        self.assertNotIn("confirmation_token", r)

    async def test_disco_insuficiente(self) -> None:
        r = await self.t["sv_set_swap"](swap_size="21G")
        self.assertEqual(r["error"], "insufficient_disk")
        self.assertNotIn("confirmation_token", r)

    async def test_margen_de_disco(self) -> None:
        # T033: 20,5 GiB libres de 31,2: el margen es el 10 % (3,1 GiB), así
        # que caben 17 GiB y no 18 ni 20 (antes, con `>` estricto, cabían
        # 20). Control negativo: comparando con `libre` sin margen, caen los
        # casos de 18G y 20G.
        for valor, cabe in (("17G", True), ("18G", False), ("20G", False),
                            ("20992M", False)):
            with self.subTest(valor=valor):
                r = await self.t["sv_set_swap"](swap_size=valor)
                if cabe:
                    self.assertIn("confirmation_token", r, r)
                    self.assertEqual(r["preview"]["disk_reserve_gib"], 3.1)
                else:
                    self.assertEqual(r["error"], "insufficient_disk", r)
                    self.assertIn("3.1 GiB", r["detail"])
                    self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras, [])

    async def test_margen_minimo_de_un_gib(self) -> None:
        # En un disco pequeño (8 GiB, 10 % = 0,8) manda el suelo de 1 GiB.
        self.sv.host.update({"disk_free": 3.0, "disk_total": 8.0})
        self.assertIn("confirmation_token", await self.t["sv_set_swap"](swap_size="2G"))
        r = await self.t["sv_set_swap"](swap_size="2049M")
        self.assertEqual(r["error"], "insufficient_disk", r)
        self.assertIn("1.0 GiB", r["detail"])

    async def test_margen_se_repite_al_confirmar(self) -> None:
        vista = await self._vista("sv_set_swap", swap_size="17G")
        self.sv.host["disk_free"] = 19.5
        r = await self.t["sv_set_swap"](swap_size="17G",
                                        confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "insufficient_disk", r)
        self.assertEqual(self.sv.escrituras, [])

    async def test_sin_disco_total_no_hay_token(self) -> None:
        del self.sv.host["disk_total"]
        r = await self.t["sv_set_swap"](swap_size="2G")
        self.assertIn("unexpected", r["error"].lower())
        self.assertNotIn("confirmation_token", r)

    async def test_cero_desactiva(self) -> None:
        vista = await self._vista("sv_set_swap", swap_size="0")
        self.assertIn("disables swap", vista["preview"]["warning"])

    async def test_sin_swap_configurable(self) -> None:
        self.sv.swap = None
        r = await self.t["sv_set_swap"](swap_size="2G")
        self.assertEqual(r["error"], "not_supported")
        self.assertIn("OS 15", r["hint"])
        self.assertNotIn("confirmation_token", r)

    async def test_forma_inesperada(self) -> None:
        for clave, forma in ((("GET", "/os/config/swap"), {"swap_size": 1}),
                             (("GET", "/host/info"), {"hostname": "x"})):
            with self.subTest(clave=clave):
                self.sv.formas = {clave: forma}
                r = await self.t["sv_set_swap"](swap_size="2G")
                self.assertIn("unexpected", r["error"].lower())
                self.assertNotIn("confirmation_token", r)


# ── T004 (US2): ranura de arranque ───────────────────────────────────────────


class TestRanura(_Base):
    async def test_vista_previa(self) -> None:
        vista = await self._vista("sv_set_boot_slot", boot_slot="B")
        p = vista["preview"]
        self.assertEqual(p["action"], "set_boot_slot")
        self.assertEqual(p["current"], {"slot": "A", "version": VERSION_A})
        self.assertEqual(p["target"], {"slot": "B", "version": VERSION_B,
                                       "state": "inactive", "status": "bad"})
        self.assertIs(p["reboots_now"], True)
        self.assertIn("reboots immediately", p["warning"])
        self.assertIn("bad", p["slot_warning"])
        self.assertEqual(p["rollback"], 'sv_set_boot_slot("A")')
        # Las ranuras y el estado de Core (la migración, T029).
        self.assertEqual([(c["metodo"], c["ruta"]) for c in self.sv.llamadas],
                         [("GET", "/os/info"), ("GET", "/core/api/core/state")])

    async def test_confirmar_en_mayusculas(self) -> None:
        _, hecho = await self._confirmar("sv_set_boot_slot", boot_slot="b")
        self.assertEqual(self.sv.escrituras, [
            {"metodo": "POST", "ruta": "/os/boot-slot", "json_body": {"boot_slot": "B"}}])
        self.assertEqual(hecho["result"], "ok")
        self.assertEqual(hecho["verify_with"], "sv_get_os_info")

    async def test_minuscula_y_mayuscula_son_la_misma_accion(self) -> None:
        vista = await self._vista("sv_set_boot_slot", boot_slot="b")
        hecho = await self.t["sv_set_boot_slot"](
            boot_slot="B", confirmation_token=vista["confirmation_token"])
        self.assertEqual(hecho["result"], "ok", hecho)

    async def test_sin_aviso_si_esta_bien(self) -> None:
        self.sv.os["boot_slots"]["B"]["status"] = "good"
        vista = await self._vista("sv_set_boot_slot", boot_slot="B")
        self.assertNotIn("slot_warning", vista["preview"])

    async def test_invalidos_sin_llamar(self) -> None:
        for valor in ("C", "", "AB", 1, None, True):
            with self.subTest(valor=valor):
                self.sv.llamadas.clear()
                r = await self.t["sv_set_boot_slot"](boot_slot=valor)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "boot_slot"))
                self._sin_llamadas()

    async def test_ya_activa(self) -> None:
        r = await self.t["sv_set_boot_slot"](boot_slot="A")
        self.assertEqual(r["error"], "already_booted")
        self.assertNotIn("confirmation_token", r)

    async def test_inutilizable(self) -> None:
        sin_version = SupervisorDeHost()
        sin_version.os["boot_slots"]["B"]["version"] = None
        sin_b = SupervisorDeHost()
        del sin_b.os["boot_slots"]["B"]
        for sv in (sin_version, sin_b):
            with self.subTest():
                mcp = DummyMCP()
                register(mcp, sv)
                r = await mcp.tools["sv_set_boot_slot"](boot_slot="B")
                self.assertEqual(r["error"], "slot_unusable")
                self.assertNotIn("confirmation_token", r)

    async def test_sin_haos(self) -> None:
        # T032: lo que contesta de verdad el Supervisor 2026.11.0 sin HAOS
        # (`boot: null`, `boot_slots: {}`), no un 404. Control negativo:
        # quitando la rama de `_leer_ranuras`, sale «Unexpected Supervisor
        # response» y este test cae.
        self.sv.os = os_info_sin_haos()
        r = await self.t["sv_set_boot_slot"](boot_slot="B")
        self.assertEqual(r["error"], "not_supported", r)
        self.assertIn("Home Assistant OS", r["hint"])
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras, [])

    async def test_forma_inesperada(self) -> None:
        for forma in ({"boot": "A"}, {"boot": None, "boot_slots": {"A": {}}},
                      {"boot": None}, [], {}):
            with self.subTest(forma=forma):
                self.sv.formas[("GET", "/os/info")] = forma
                r = await self.t["sv_set_boot_slot"](boot_slot="B")
                self.assertIn("unexpected", r["error"].lower())
                self.assertNotIn("confirmation_token", r)


class TestRanuraYMigracion(_Base):
    """T029: el Supervisor NO comprueba la migración de la base de datos de
    Core al cambiar de ranura (`os/manager.py::set_boot_slot` reinicia
    directamente), así que lo hace Hermes, con el criterio de
    `get_api_state`, antes de dar token y otra vez antes de enviar.

    Control negativo: quitando la llamada a `_sin_migracion`, caen
    `test_migracion_offline_sin_token`, `test_migracion_que_empieza_tras_la_
    vista` y `test_estado_ilegible_sin_token`.
    """

    async def test_migracion_offline_sin_token(self) -> None:
        self.sv.core = core_state(migrando=True)
        r = await self.t["sv_set_boot_slot"](boot_slot="B")
        self.assertEqual(r["error"], "db_migration_in_progress", r)
        self.assertIn("migrating its database", r["detail"])
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras, [])

    async def test_migracion_en_vivo_no_bloquea(self) -> None:
        # Igual que el Supervisor: una migración en vivo no impide reiniciar.
        self.sv.core = core_state(migrando=True, en_vivo=True)
        await self._confirmar("sv_set_boot_slot", boot_slot="B")
        self.assertEqual(len(self.sv.escrituras), 1)

    async def test_core_antiguo_sin_recorder_state(self) -> None:
        self.sv.core = {"state": "RUNNING"}
        await self._vista("sv_set_boot_slot", boot_slot="B")

    async def test_migracion_que_empieza_tras_la_vista(self) -> None:
        vista = await self._vista("sv_set_boot_slot", boot_slot="B")
        self.sv.core = core_state(migrando=True)
        r = await self.t["sv_set_boot_slot"](
            boot_slot="B", confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "db_migration_in_progress", r)
        self.assertEqual(self.sv.escrituras, [])

    async def test_estado_ilegible_sin_token(self) -> None:
        # Fail-closed: sin saber si migra, no se reinicia.
        casos = {
            "corte": lambda sv: sv.errores.__setitem__(
                ("GET", "/core/api/core/state"), corte()),
            "lista": lambda sv: setattr(sv, "core", []),
            "recorder_state raro": lambda sv: setattr(
                sv, "core", {"state": "RUNNING", "recorder_state": "x"}),
        }
        for nombre, preparar in casos.items():
            with self.subTest(caso=nombre):
                self.sv = SupervisorDeHost()
                self.mcp = DummyMCP()
                register(self.mcp, self.sv)
                preparar(self.sv)
                r = await self.mcp.tools["sv_set_boot_slot"](boot_slot="B")
                self.assertEqual(r["error"], "core_state_unknown", r)
                self.assertNotIn("confirmation_token", r)
                self.assertEqual(self.sv.escrituras, [])

    async def test_apagar_no_lee_core(self) -> None:
        # `sv_shutdown_host` no lo necesita: con `{}` lo comprueba el
        # propio Supervisor (`_check_ha_offline_migration`).
        self.sv.core = core_state(migrando=True)
        await self._confirmar("sv_shutdown_host")
        self.assertNotIn(("GET", "/core/api/core/state"),
                         [(c["metodo"], c["ruta"]) for c in self.sv.llamadas])


# ── T005: token atado, corte tras enviar y log ───────────────────────────────


class TestTokenAtado(_Base):
    async def _con_otro(self, tool: str, kw: dict, otro: dict) -> dict:
        vista = await self._vista(tool, **kw)
        return await self.t[tool](**otro, confirmation_token=vista["confirmation_token"])

    async def test_otro_argumento_no_ejecuta(self) -> None:
        casos = (
            ("sv_set_hostname", {"hostname": HOSTNAME_NUEVO}, {"hostname": "otra-casa"}),
            ("sv_set_swap", {"swap_size": "2G"}, {"swap_size": "3G"}),
            ("sv_set_swap", {"swap_size": "2G"}, {"swap_size": "2G", "swappiness": 5}),
            ("sv_set_boot_slot", {"boot_slot": "B"}, {"boot_slot": "A"}),
        )
        for tool, kw, otro in casos:
            with self.subTest(tool=tool, otro=otro):
                self.sv = SupervisorDeHost()
                self.mcp = DummyMCP()
                register(self.mcp, self.sv)
                self.t = self.mcp.tools
                r = await self._con_otro(tool, kw, otro)
                self.assertIn("error", r)
                self.assertNotEqual(r.get("result"), "ok")
                self.assertEqual(self.sv.escrituras, [])

    async def test_estado_cambiado_no_ejecuta(self) -> None:
        def hostname(sv: SupervisorDeHost) -> None:
            sv.host["hostname"] = "otro-nombre"

        def swap(sv: SupervisorDeHost) -> None:
            sv.swap["swappiness"] = 30

        def ranuras(sv: SupervisorDeHost) -> None:
            sv.os["boot_slots"]["B"]["version"] = "17.2"

        casos = (("sv_set_hostname", {"hostname": HOSTNAME_NUEVO}, hostname),
                 ("sv_set_swap", {"swap_size": "2G"}, swap),
                 ("sv_set_boot_slot", {"boot_slot": "B"}, ranuras))
        for tool, kw, cambiar in casos:
            with self.subTest(tool=tool):
                sv = SupervisorDeHost()
                mcp = DummyMCP()
                register(mcp, sv)
                vista = await mcp.tools[tool](**kw)
                cambiar(sv)
                r = await mcp.tools[tool](**kw, confirmation_token=vista["confirmation_token"])
                self.assertEqual(r["error"], "state_changed", r)
                self.assertIn("new preview", r["detail"])
                self.assertEqual(sv.escrituras, [])

    async def test_el_disco_libre_no_invalida_el_token(self) -> None:
        vista = await self._vista("sv_set_swap", swap_size="2G")
        self.sv.host["disk_free"] = 19.8
        hecho = await self.t["sv_set_swap"](
            swap_size="2G", confirmation_token=vista["confirmation_token"])
        self.assertEqual(hecho["result"], "ok", hecho)

    async def test_disco_insuficiente_se_repite_al_confirmar(self) -> None:
        vista = await self._vista("sv_set_swap", swap_size="2G")
        self.sv.host["disk_free"] = 1.5
        r = await self.t["sv_set_swap"](
            swap_size="2G", confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "insufficient_disk")
        self.assertEqual(self.sv.escrituras, [])

    async def test_un_token_sirve_una_vez(self) -> None:
        vista, hecho = await self._confirmar("sv_shutdown_host")
        self.assertEqual(hecho["result"], "ok")
        otra = await self.t["sv_shutdown_host"](confirmation_token=vista["confirmation_token"])
        self.assertIn("error", otra)
        self.assertEqual(len(self.sv.escrituras), 1)

    async def test_token_de_otra_tool(self) -> None:
        vista = await self._vista("sv_shutdown_host")
        r = await self.t["sv_set_boot_slot"](
            boot_slot="B", confirmation_token=vista["confirmation_token"])
        self.assertIn("does not match", r["error"])
        self.assertEqual(self.sv.escrituras, [])


class TestCorteTrasEnviar(_Base):
    async def test_corte_tras_enviar_es_unknown(self) -> None:
        casos = (
            ("sv_shutdown_host", {}, "/host/shutdown", corte()),
            ("sv_set_boot_slot", {"boot_slot": "B"}, "/os/boot-slot", corte()),
            ("sv_set_boot_slot", {"boot_slot": "B"}, "/os/boot-slot",
             aiohttp.ServerDisconnectedError()),
            ("sv_set_hostname", {"hostname": HOSTNAME_NUEVO}, "/host/options", corte()),
            ("sv_set_swap", {"swap_size": "2G"}, "/os/config/swap", TimeoutError()),
        )
        for tool, kw, ruta, exc in casos:
            with self.subTest(tool=tool, exc=type(exc).__name__):
                sv = SupervisorDeHost()
                sv.errores[("POST", ruta)] = exc
                mcp = DummyMCP()
                register(mcp, sv)
                vista = await mcp.tools[tool](**kw)
                token = vista["confirmation_token"]
                r = await mcp.tools[tool](**kw, confirmation_token=token)
                self.assertEqual(r["outcome"], "unknown", r)
                self.assertNotIn("result", r)
                self.assertNotIn("error", r)
                self.assertTrue(r["hint"])
                self.assertTrue(r["verify_with"])
                # El token queda gastado: repetir no vuelve a enviar.
                otra = await mcp.tools[tool](**kw, confirmation_token=token)
                self.assertIn("error", otra)
                self.assertEqual(len(sv.escrituras), 1)

    async def test_verify_with_de_cada_tool(self) -> None:
        self.sv.errores[("POST", "/os/boot-slot")] = corte()
        _, r = await self._confirmar("sv_set_boot_slot", boot_slot="B")
        self.assertEqual(r["verify_with"], "sv_get_os_info")

    async def test_fallo_en_la_lectura_previa_es_error(self) -> None:
        self.sv.errores[("GET", "/os/info")] = corte()
        r = await self.t["sv_set_boot_slot"](boot_slot="B")
        self.assertIn("error", r)
        self.assertNotIn("outcome", r)
        self.assertNotIn("confirmation_token", r)


class TestContratoSent(_Base):
    """Integración con la 022: el `_enviar` del control del host respeta el
    contrato de tres valores de `HAConnectionError.sent`. `False` (o una
    conexión que ni se estableció) es «no se hizo nada»: error con
    `sent: false`, nunca `outcome: "unknown"`. `True` y `None` (sin `status`
    ni `Supervisor error:`) no aseguran nada: `unknown`, nunca `ok`.

    Control negativo comprobado: con `_no_salio` devolviendo siempre False,
    `test_no_salio_es_error_sin_unknown` cae (sale `outcome: "unknown"`);
    restaurado, verde."""

    async def _con_error(self, exc: BaseException) -> tuple[dict, dict, SupervisorDeHost]:
        sv = SupervisorDeHost()
        sv.errores[("POST", "/host/options")] = exc
        mcp = DummyMCP()
        register(mcp, sv)
        kw = {"hostname": HOSTNAME_NUEVO}
        vista = await mcp.tools["sv_set_hostname"](**kw)
        token = vista["confirmation_token"]
        r = await mcp.tools["sv_set_hostname"](**kw, confirmation_token=token)
        otra = await mcp.tools["sv_set_hostname"](**kw, confirmation_token=token)
        return r, otra, sv

    async def test_no_salio_es_error_sin_unknown(self) -> None:
        from unittest.mock import MagicMock

        for exc in (HAConnectionError("Cliente HTTP de HA no inicializado.", sent=False),
                    aiohttp.ClientConnectorError(MagicMock(), OSError(111, "refused"))):
            with self.subTest(exc=type(exc).__name__):
                r, otra, sv = await self._con_error(exc)
                self.assertIs(r.get("sent"), False, r)
                self.assertIn("nothing was done", r["note"])
                self.assertNotIn("outcome", r)
                self.assertNotIn("result", r)
                # El token queda gastado: no se reintenta solo.
                self.assertIn("error", otra)
                self.assertEqual(len(sv.escrituras), 1)

    async def test_salio_o_no_se_sabe_es_unknown(self) -> None:
        for exc in (HAConnectionError("Timeout esperando al Supervisor", sent=True),
                    HAConnectionError("Server disconnected"),
                    aiohttp.ServerDisconnectedError(), TimeoutError()):
            with self.subTest(exc=repr(exc)):
                r, _, _ = await self._con_error(exc)
                self.assertEqual(r.get("outcome"), "unknown", r)
                self.assertNotIn("sent", r)
                self.assertNotIn("result", r)


class TestLog(_Base):
    _PROHIBIDO = (HOSTNAME_ACTUAL, HOSTNAME_NUEVO, SWAP_ACTUAL, "2G", VERSION_A, VERSION_B)

    async def test_eventos_sin_valores(self) -> None:
        with capture_logs() as eventos:
            await self._confirmar("sv_set_hostname", hostname=HOSTNAME_NUEVO)
            await self._confirmar("sv_set_swap", swap_size="2G")
            await self._confirmar("sv_set_boot_slot", boot_slot="B")
            await self._confirmar("sv_shutdown_host")
            await self.t["sv_set_hostname"](hostname="Casa HA")
            await self.t["sv_set_hostname"](hostname=HOSTNAME_NUEVO)  # no_change
        propios = [e for e in eventos if e.get("event") == "host_control"]
        self.assertTrue(propios)
        texto = _texto(eventos)
        for valor in self._PROHIBIDO:
            with self.subTest(valor=valor):
                self.assertNotIn(valor, texto)
        for e in propios:
            self.assertIn("tool", e)
            self.assertIn("outcome", e)
        ok = [e for e in propios if e["outcome"] == "ok"]
        self.assertEqual(
            {e["tool"]: e.get("changed") for e in ok},
            {"sv_set_hostname": ["hostname"], "sv_set_swap": ["swap_size"],
             "sv_set_boot_slot": ["boot_slot"], "sv_shutdown_host": []})
        self.assertIn("invalid_argument", {e["outcome"] for e in propios})
        self.assertIn("rejected", {e["outcome"] for e in propios})

    async def test_errores_y_cortes_sin_valores(self) -> None:
        self.sv.errores[("POST", "/host/options")] = error_hostname_invalido()
        self.sv.errores[("POST", "/os/boot-slot")] = corte()
        with capture_logs() as eventos:
            await self._confirmar("sv_set_hostname", hostname=HOSTNAME_NUEVO)
            await self._confirmar("sv_set_boot_slot", boot_slot="B")
        texto = _texto(eventos)
        for valor in self._PROHIBIDO:
            self.assertNotIn(valor, texto)
        resultados = {e["outcome"] for e in eventos if e.get("event") == "host_control"}
        self.assertLessEqual({"error", "unknown"}, resultados)


if __name__ == "__main__":
    unittest.main()
