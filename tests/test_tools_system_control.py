"""Control de Core y del Supervisor (spec 022, tramo 1; CAP-084).

Las siete tools de `system_control` contra el Supervisor simulado de
`tests/fixtures/supervisor_control.py` (forma del Supervisor 2026.11.0,
datos ficticios). Lo que se vigila, además de cada petición exacta:

- ningún rechazo produce una llamada que escribe (se cuentan los `POST`);
- las vistas previas dicen qué se corta, cuánto y qué le pasa a Hermes;
- las listas cerradas de opciones se aplican antes de llamar (FR-003, FR-007);
- el token ata los argumentos y, en las opciones, los valores actuales;
- si Hermes no puede saber si una operación terminó, responde
  `status: "started"` con `verify_with` (FR-008);
- al log van nombres de claves, nunca valores ni el texto de un error
  (FR-019).

Controles negativos del tramo (T014), con recuentos, en el mensaje del commit
que añade este fichero.
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import aiohttp
from structlog.testing import capture_logs

from hermes.ha import HAConnectionError
from hermes.tools.system_control import register
from tests.fixtures.supervisor_control import (
    CENTINELA_SV,
    SupervisorDeControl,
    error_400,
    job,
)

_PARCHE_CHECK = "hermes.tools.system_control.check_restart_allowed_sync"


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
        self.sv = SupervisorDeControl()
        self.mcp = DummyMCP()
        register(self.mcp, self.sv, response_max_bytes=131_072)
        self.t = self.mcp.tools
        # Sin escrituras en /config pendientes salvo que el test lo diga.
        self.check = patch(_PARCHE_CHECK, return_value=(True, ""))
        self.check_mock = self.check.start()
        self.addCleanup(self.check.stop)

    def _posts(self) -> list[tuple[str, Any, float]]:
        return [(c["ruta"], c["json"], c["timeout"]) for c in self.sv.escrituras]

    def _bloquear(self) -> None:
        self.check_mock.return_value = (
            False, "There are /config writes not validated with sv_check_core_config.")

    async def _confirmar(self, tool: str, **kw: Any) -> tuple[dict, dict]:
        vista = await self.t[tool](**kw)
        self.assertIn("confirmation_token", vista, vista)
        r = await self.t[tool](**kw, confirmation_token=vista["confirmation_token"])
        return vista, r


# ── T003: arrancar y reconstruir Core (FR-001, FR-002) ───────────────────────


class TestStartCore(_Base):
    async def test_core_parado_vista_previa_y_arranque(self) -> None:
        self.sv.core_corre = False
        vista, r = await self._confirmar("sv_start_core")
        p = vista["preview"]
        self.assertEqual((p["action"], p["core_state"], p["version"]),
                         ("start_core", "stopped", "2026.11.1"))
        self.assertIn("duration", p["interrupts"])
        self.assertIn("Hermes keeps running", p["hermes"])
        self.assertEqual(r["result"], "ok")
        self.assertEqual(self._posts(), [("/core/start", None, 600.0)])

    async def test_core_en_marcha_already_running_sin_token(self) -> None:
        r = await self.t["sv_start_core"]()
        self.assertEqual(r["error"], "already_running")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self._posts(), [])

    async def test_pasa_a_en_marcha_antes_de_confirmar(self) -> None:
        self.sv.core_corre = False
        vista = await self.t["sv_start_core"]()
        self.sv.core_corre = True
        r = await self.t["sv_start_core"](confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "already_running")
        self.assertEqual(self._posts(), [])

    async def test_otro_error_de_stats_es_unknown_con_token(self) -> None:
        self.sv.errores[("GET", "/core/stats")] = HAConnectionError(
            "Supervisor REST GET failed 500: boom", status=500)
        vista = await self.t["sv_start_core"]()
        self.assertEqual(vista["preview"]["core_state"], "unknown")
        self.assertIn("confirmation_token", vista)
        self.assertTrue(vista["preview"]["warnings"])

    async def test_escrituras_sin_validar_avisan_sin_bloquear(self) -> None:
        self.sv.core_corre = False
        self._bloquear()
        vista, r = await self._confirmar("sv_start_core")
        self.assertIsNone(vista["preview"]["blocked"])
        self.assertIn("sv_check_core_config", _texto(vista["preview"]["warnings"]))
        self.assertEqual(r["result"], "ok")


class TestRebuildCore(_Base):
    async def test_vista_previa_y_rebuild(self) -> None:
        vista, r = await self._confirmar("sv_rebuild_core", safe_mode=True)
        p = vista["preview"]
        self.assertEqual((p["action"], p["safe_mode"], p["blocked"]),
                         ("rebuild_core", True, None))
        self.assertIn("custom integrations", p["safe_mode_meaning"])
        self.assertEqual(p["interrupts"]["stops"], ["Home Assistant Core"])
        self.assertEqual(r["result"], "ok")
        self.assertEqual(self._posts(), [("/core/rebuild", {"safe_mode": True}, 600.0)])

    async def test_nunca_force(self) -> None:
        await self._confirmar("sv_rebuild_core")
        self.assertEqual(self.sv.escrituras[0]["json"], {"safe_mode": False})

    async def test_safe_mode_no_booleano(self) -> None:
        for valor in ("true", 1, None):
            with self.subTest(valor=valor):
                r = await self.t["sv_rebuild_core"](safe_mode=valor)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "safe_mode"))
        self.assertEqual(self.sv.llamadas, [])

    async def test_token_de_otro_safe_mode(self) -> None:
        vista = await self.t["sv_rebuild_core"](safe_mode=True)
        r = await self.t["sv_rebuild_core"](
            safe_mode=False, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "invalid_confirmation_token")
        self.assertEqual(self._posts(), [])

    async def test_bloqueado_por_escrituras_sin_validar(self) -> None:
        self._bloquear()
        vista = await self.t["sv_rebuild_core"]()
        self.assertIn("sv_check_core_config", vista["preview"]["blocked"])
        r = await self.t["sv_rebuild_core"](confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "blocked")
        self.assertIn("sv_check_core_config", r["hint"])
        self.assertEqual(self._posts(), [])

    async def test_error_del_supervisor_redactado(self) -> None:
        self.sv.errores[("POST", "/core/rebuild")] = error_400(
            "/core/rebuild", f"fallo password={CENTINELA_SV}")
        _, r = await self._confirmar("sv_rebuild_core")
        self.assertEqual(r["error"], "supervisor_request_failed")
        self.assertNotIn(CENTINELA_SV, _texto(r))


class TestOperacionesLargas(_Base):
    """FR-008: si vence el tiempo o se corta la conexión, `started`."""

    async def test_start_vencido(self) -> None:
        self.sv.core_corre = False
        self.sv.errores[("POST", "/core/start")] = TimeoutError()
        _, r = await self._confirmar("sv_start_core")
        self.assertEqual((r["status"], r["verify_with"]), ("started", "sv_get_core_info"))
        self.assertNotIn("result", r)
        self.assertNotIn("error", r)

    async def test_rebuild_vencido(self) -> None:
        self.sv.errores[("POST", "/core/rebuild")] = TimeoutError()
        _, r = await self._confirmar("sv_rebuild_core")
        self.assertEqual((r["status"], r["verify_with"]), ("started", "sv_get_core_info"))

    async def test_repair_vencido(self) -> None:
        self.sv.errores[("POST", "/supervisor/repair")] = TimeoutError()
        _, r = await self._confirmar("sv_repair_supervisor")
        self.assertEqual((r["status"], r["verify_with"]), ("started", "sv_get_resolution"))

    async def test_restart_con_la_conexion_cortada(self) -> None:
        self.sv.errores[("POST", "/supervisor/restart")] = (
            aiohttp.ServerDisconnectedError())
        _, r = await self._confirmar("sv_restart_supervisor")
        self.assertEqual((r["status"], r["verify_with"]),
                         ("started", "sv_get_supervisor_info"))
        self.assertIn("cannot tell", r["note"])

    async def test_restart_sin_status_es_started(self) -> None:
        self.sv.errores[("POST", "/supervisor/restart")] = HAConnectionError(
            "Supervisor returned invalid JSON: ''")
        _, r = await self._confirmar("sv_restart_supervisor")
        self.assertEqual(r["status"], "started")

    async def test_peticion_no_enviada_es_error(self) -> None:
        """T032: si la petición ni salió (cliente HTTP sin inicializar o
        conexión que no se establece), error con `sent: false`; nunca
        `started` ni «the request was sent». Control negativo: sin
        `_no_enviada` en `_es_corte`, sale `started`."""
        no_init = HAConnectionError("Cliente HTTP de HA no inicializado.", sent=False)
        conector = aiohttp.ClientConnectorError(MagicMock(), OSError(111, "refused"))
        casos = [
            ("sv_start_core", "/core/start"),
            ("sv_rebuild_core", "/core/rebuild"),
            ("sv_repair_supervisor", "/supervisor/repair"),
            ("sv_restart_supervisor", "/supervisor/restart"),
        ]
        for tool, ruta in casos:
            for nombre, exc in (("no_inicializado", no_init), ("sin_conexion", conector)):
                with self.subTest(tool=tool, caso=nombre):
                    self.setUp()
                    self.sv.core_corre = tool != "sv_start_core"
                    self.sv.errores[("POST", ruta)] = exc
                    _, r = await self._confirmar(tool)
                    self.assertEqual(r.get("error"), "supervisor_request_failed", r)
                    self.assertIs(r["sent"], False)
                    self.assertNotIn("status", r)
                    self.assertNotIn("was sent", _texto(r))

    async def test_error_del_cliente_marca_no_enviada(self) -> None:
        """T032: el `HAClient` real marca con `sent=False` el error de
        cliente sin inicializar. Control negativo: sin `sent=False` en
        `sv_request`, falla."""
        from hermes.ha import HAClient

        cliente = HAClient.__new__(HAClient)
        cliente._session = None
        with self.assertRaises(HAConnectionError) as ctx:
            await cliente.sv_request("POST", "/core/start")
        self.assertIs(ctx.exception.sent, False)

    async def test_restart_con_status_400_es_error(self) -> None:
        self.sv.errores[("POST", "/supervisor/restart")] = error_400(
            "/supervisor/restart", f"no token={CENTINELA_SV}")
        _, r = await self._confirmar("sv_restart_supervisor")
        self.assertEqual(r["error"], "supervisor_request_failed")
        self.assertNotIn(CENTINELA_SV, _texto(r))


# ── T004: opciones de Core (FR-003) ──────────────────────────────────────────


class TestSetCoreOptions(_Base):
    async def test_diferencia_por_clave_y_solo_lo_que_cambia(self) -> None:
        opciones = {"boot": False, "watchdog": True, "audio_input": "alsa_input.x"}
        vista, r = await self._confirmar("sv_set_core_options", options=opciones)
        p = vista["preview"]
        self.assertEqual(p["changes"], {
            "boot": {"current": True, "new": False},
            "audio_input": {"current": None, "new": "alsa_input.x"},
        })
        self.assertEqual(p["unchanged"], ["watchdog"])
        self.assertIs(p["restart_needed"], False)
        self.assertEqual(r["result"], "ok")
        self.assertEqual(self._posts(), [
            ("/core/options", {"audio_input": "alsa_input.x", "boot": False}, 15.0)])

    async def test_avisos(self) -> None:
        casos = {
            "boot": (False, "sv_start_core"),
            "watchdog": (False, "will not restart"),
            "backups_exclude_database": (True, "recorder database"),
            "duplicate_log_file": (True, "next time Core starts"),
            "audio_output": ("alsa_output.y", "next time Core starts"),
        }
        for clave, (valor, frase) in casos.items():
            with self.subTest(clave=clave):
                vista = await self.t["sv_set_core_options"](options={clave: valor})
                self.assertIn(frase, _texto(vista["preview"]["warnings"]))

    async def test_claves_rechazadas(self) -> None:
        for clave, valor in (("image", "x/y"), ("refresh_token", "t"),
                             ("port", 8124), ("ssl", True)):
            with self.subTest(clave=clave):
                r = await self.t["sv_set_core_options"](options={clave: valor, "boot": True})
                self.assertEqual((r["error"], r["field"]), ("not_allowed", clave))
                self.assertIn("boot", r["allowed"])
                self.assertTrue(r["reason"])
        self.assertEqual(self.sv.llamadas, [])

    async def test_invalidas(self) -> None:
        casos = [
            ({"desconocida": 1}, "desconocida"),
            ({}, "options"),
            ({"boot": "no"}, "boot"),
            ({"audio_input": "a" * 129}, "audio_input"),
            ({"audio_input": 3}, "audio_input"),
        ]
        for opciones, campo in casos:
            with self.subTest(opciones=opciones):
                r = await self.t["sv_set_core_options"](options=opciones)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", campo))
        r = await self.t["sv_set_core_options"](options=["boot"])
        self.assertEqual(r["error"], "invalid_argument")
        self.assertEqual(self.sv.llamadas, [])

    async def test_no_changes(self) -> None:
        r = await self.t["sv_set_core_options"](options={"boot": True, "audio_input": None})
        self.assertEqual(r["error"], "no_changes")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self._posts(), [])

    async def test_options_distinto_al_confirmar(self) -> None:
        vista = await self.t["sv_set_core_options"](options={"boot": False})
        r = await self.t["sv_set_core_options"](
            options={"watchdog": False}, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "invalid_confirmation_token")
        self.assertEqual(self._posts(), [])

    async def test_estado_cambiado_entre_vista_previa_y_confirmacion(self) -> None:
        vista = await self.t["sv_set_core_options"](options={"boot": False})
        self.sv.core_info["boot"] = "otro"  # alguien lo cambió entre medias
        r = await self.t["sv_set_core_options"](
            options={"boot": False}, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "invalid_confirmation_token")
        self.assertIn("changed", r["detail"])
        self.assertEqual(self._posts(), [])


# ── T005: recargar, reiniciar y reparar el Supervisor (FR-004…FR-006) ────────


class TestReloadSupervisor(_Base):
    async def test_sin_token(self) -> None:
        r = await self.t["sv_reload_supervisor"]()
        self.assertEqual(r["result"], "ok")
        self.assertIn("note", r)
        self.assertEqual(self._posts(), [("/supervisor/reload", None, 120.0)])

    async def test_error_redactado(self) -> None:
        self.sv.errores[("POST", "/supervisor/reload")] = error_400(
            "/supervisor/reload", f"secret: {CENTINELA_SV}")
        r = await self.t["sv_reload_supervisor"]()
        self.assertEqual(r["error"], "supervisor_request_failed")
        self.assertNotIn(CENTINELA_SV, _texto(r))


class TestRestartSupervisor(_Base):
    async def test_vista_previa_y_reinicio(self) -> None:
        self.sv.jobs = [job("backup_manager_full_backup", True)]
        vista, r = await self._confirmar("sv_restart_supervisor")
        p = vista["preview"]
        self.assertEqual(p["interrupts"]["stops"],
                         ["Supervisor API", "Hermes' connection to Core"])
        self.assertEqual(p["interrupts"]["keeps_running"],
                         ["Home Assistant Core", "apps (add-ons)"])
        self.assertIn("seconds", p["interrupts"]["duration"])
        self.assertIn("reconnects", p["hermes"])
        self.assertEqual(p["version"], "2026.11.0")
        self.assertEqual((r["status"], r["verify_with"]),
                         ("started", "sv_get_supervisor_info"))
        self.assertEqual(self._posts(), [("/supervisor/restart", None, 60.0)])

    async def test_jobs_en_curso_tambien_hijos(self) -> None:
        casos = {
            "raiz": [job("addon_update", False, progress=40.0, stage="pull")],
            "hijo": [job("backup_full", True, hijos=[job("backup_store_addons", False)])],
            "sin_arrancar": [job("mount_reload", None)],
        }
        for nombre, jobs in casos.items():
            with self.subTest(caso=nombre):
                self.sv.jobs = jobs
                r = await self.t["sv_restart_supervisor"]()
                self.assertEqual(r["error"], "jobs_in_progress")
                self.assertNotIn("confirmation_token", r)
                self.assertTrue(r["jobs"])
        self.sv.jobs = casos["raiz"]
        r = await self.t["sv_restart_supervisor"]()
        self.assertEqual(r["jobs"], [{"name": "addon_update", "progress": 40.0,
                                      "stage": "pull"}])
        self.assertEqual(self._posts(), [])

    async def test_job_que_aparece_al_confirmar(self) -> None:
        vista = await self.t["sv_restart_supervisor"]()
        self.sv.jobs = [job("addon_install", False)]
        r = await self.t["sv_restart_supervisor"](confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "jobs_in_progress")
        self.assertEqual(self._posts(), [])

    async def test_jobs_info_que_falla(self) -> None:
        for fallo in (HAConnectionError("boom", status=500), TimeoutError()):
            with self.subTest(fallo=type(fallo).__name__):
                self.sv.errores[("GET", "/jobs/info")] = fallo
                r = await self.t["sv_restart_supervisor"]()
                self.assertEqual(r["error"], "supervisor_request_failed")
                self.assertNotIn("confirmation_token", r)
        del self.sv.errores[("GET", "/jobs/info")]
        self.sv.formas[("GET", "/jobs/info")] = {"sin_jobs": True}
        r = await self.t["sv_restart_supervisor"]()
        self.assertEqual(r["error"], "supervisor_request_failed")
        self.assertEqual(self._posts(), [])


class TestRepairSupervisor(_Base):
    async def test_vista_previa_y_reparacion(self) -> None:
        vista, r = await self._confirmar("sv_repair_supervisor")
        p = vista["preview"]
        self.assertEqual(len(p["steps"]), 5)
        self.assertIn("unused images", p["deletes"])
        self.assertIn("unused volumes", p["deletes"])
        self.assertIn("missing images", p["downloads"])
        self.assertEqual(p["interrupts"]["duration"], "several minutes")
        self.assertEqual(r["result"], "ok")
        self.assertEqual(self._posts(), [("/supervisor/repair", None, 900.0)])

    async def test_jobs_en_curso(self) -> None:
        self.sv.jobs = [job("addon_rebuild", False)]
        r = await self.t["sv_repair_supervisor"]()
        self.assertEqual(r["error"], "jobs_in_progress")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self._posts(), [])


# ── T006: opciones del Supervisor (FR-007) ───────────────────────────────────


class TestSetSupervisorOptions(_Base):
    async def test_diferencia_y_solo_lo_que_cambia(self) -> None:
        opciones = {"timezone": "Europe/Madrid", "country": "ES", "logging": "info"}
        vista, r = await self._confirmar("sv_set_supervisor_options", options=opciones)
        self.assertEqual(vista["preview"]["changes"], {
            "timezone": {"current": "UTC", "new": "Europe/Madrid"},
            "country": {"current": None, "new": "ES"},
        })
        self.assertEqual(vista["preview"]["unchanged"], ["logging"])
        self.assertEqual(r["result"], "ok")
        self.assertEqual(self._posts(), [
            ("/supervisor/options", {"country": "ES", "timezone": "Europe/Madrid"}, 15.0)])

    async def test_validacion(self) -> None:
        malas = [
            ({"timezone": "../x"}, "timezone"),
            ({"timezone": ""}, "timezone"),
            ({"timezone": "A" * 65}, "timezone"),
            ({"country": "es"}, "country"),
            ({"country": "ESP"}, "country"),
            ({"logging": "verbose"}, "logging"),
            ({"auto_update": "false"}, "auto_update"),
            ({"diagnostics": 1}, "diagnostics"),
            ({"otra": True}, "otra"),
        ]
        for opciones, campo in malas:
            with self.subTest(opciones=opciones):
                r = await self.t["sv_set_supervisor_options"](options=opciones)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", campo))
        self.assertEqual(self.sv.llamadas, [])
        # Y las buenas pasan la validación.
        r = await self.t["sv_set_supervisor_options"](
            options={"timezone": "America/Argentina/Buenos_Aires", "country": "AR"})
        self.assertIn("confirmation_token", r)

    async def test_rechazadas(self) -> None:
        for clave in ("channel", "debug", "debug_block", "detect_blocking_io",
                      "feature_flags", "addons_repositories", "wait_boot"):
            with self.subTest(clave=clave):
                r = await self.t["sv_set_supervisor_options"](options={clave: "beta"})
                self.assertEqual((r["error"], r["field"]), ("not_allowed", clave))
                self.assertIn("timezone", r["allowed"])
        self.assertEqual(self.sv.llamadas, [])

    async def test_avisos(self) -> None:
        casos = {
            "auto_update": (False, "are blocked"),
            "timezone": ("Europe/Madrid", "host time zone"),
            "diagnostics": (True, "third party"),
            "logging": ("debug", "verbose"),
        }
        for clave, (valor, frase) in casos.items():
            with self.subTest(clave=clave):
                vista = await self.t["sv_set_supervisor_options"](options={clave: valor})
                self.assertIn(frase, _texto(vista["preview"]["warnings"]))

    async def test_avisos_completos_de_la_convergencia(self) -> None:
        """T034: los efectos que faltaban, leídos en el Supervisor 2026.11.0.
        Control negativo: con los avisos anteriores fallan los tres casos."""
        self.sv.supervisor_info.update(auto_update=True, update_available=True)
        vista = await self.t["sv_set_supervisor_options"](options={"auto_update": False})
        aviso = _texto(vista["preview"]["warnings"])
        self.assertIn("marked unsupported", aviso)
        self.assertIn("the OS and the plugins", aviso)
        self.assertIn("reloading the store", aviso)
        self.assertIn("one exists now", aviso)

        self.sv.supervisor_info.update(auto_update=False)
        vista = await self.t["sv_set_supervisor_options"](options={"auto_update": True})
        aviso = _texto(vista["preview"]["warnings"])
        self.assertIn("updates and restarts itself", aviso)
        self.assertIn("Hermes loses its sv_* tools", aviso)

        for valor in (True, False):
            with self.subTest(diagnostics=valor):
                self.sv.supervisor_info["diagnostics"] = not valor
                vista = await self.t["sv_set_supervisor_options"](
                    options={"diagnostics": valor})
                self.assertIn("OS Agent", _texto(vista["preview"]["warnings"]))

    async def test_no_changes(self) -> None:
        r = await self.t["sv_set_supervisor_options"](options={"logging": "info"})
        self.assertEqual(r["error"], "no_changes")
        self.assertEqual(self._posts(), [])

    async def test_estado_cambiado(self) -> None:
        vista = await self.t["sv_set_supervisor_options"](options={"logging": "debug"})
        self.sv.supervisor_info["logging"] = "warning"
        r = await self.t["sv_set_supervisor_options"](
            options={"logging": "debug"}, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "invalid_confirmation_token")
        self.assertEqual(self._posts(), [])


# ── T007: log y redacción (FR-019) ───────────────────────────────────────────


class TestLog(_Base):
    def _eventos(self, eventos: list[dict], prefijo: str = "system_control_") -> list[dict]:
        return [e for e in eventos if e["event"].startswith(prefijo)]

    async def test_un_evento_por_llamada_con_nombres_de_claves(self) -> None:
        with capture_logs() as eventos:
            vista = await self.t["sv_set_supervisor_options"](
                options={"timezone": "Europe/Madrid", "country": "ES"})
            await self.t["sv_set_supervisor_options"](
                options={"timezone": "Europe/Madrid", "country": "ES"},
                confirmation_token=vista["confirmation_token"])
            await self.t["sv_set_core_options"](options={"image": "x"})
        propios = self._eventos(eventos)
        self.assertEqual([e["event"] for e in propios], [
            "system_control_preview", "system_control_done", "system_control_rejected"])
        self.assertEqual(propios[0]["keys"], ["country", "timezone"])
        self.assertEqual(propios[0]["tool"], "sv_set_supervisor_options")
        self.assertEqual(propios[0]["route"], "/supervisor/options")
        self.assertEqual(propios[1]["outcome"], "ok")
        self.assertEqual(propios[2]["code"], "not_allowed")
        texto = _texto(eventos)
        for valor in ("Europe/Madrid", '"ES"'):
            self.assertNotIn(valor, texto)

    async def test_valores_de_audio_no_van_al_log(self) -> None:
        with capture_logs() as eventos:
            vista = await self.t["sv_set_core_options"](options={"audio_input": "alsa_secreto"})
            await self.t["sv_set_core_options"](
                options={"audio_input": "alsa_secreto"},
                confirmation_token=vista["confirmation_token"])
        self.assertNotIn("alsa_secreto", _texto(eventos))
        self.assertEqual(len(self._eventos(eventos)), 2)

    async def test_error_con_centinela_no_va_al_log(self) -> None:
        self.sv.errores[("POST", "/supervisor/reload")] = error_400(
            "/supervisor/reload", f"detalle {CENTINELA_SV}")
        with capture_logs() as eventos:
            await self.t["sv_reload_supervisor"]()
        propios = self._eventos(eventos)
        self.assertEqual(len(propios), 1)
        self.assertEqual(propios[0]["code"], "supervisor_request_failed")
        self.assertNotIn(CENTINELA_SV, _texto(eventos))

    async def test_cada_tool_deja_su_evento(self) -> None:
        self.sv.core_corre = False
        llamadas = [
            ("sv_start_core", {}), ("sv_rebuild_core", {}),
            ("sv_restart_supervisor", {}), ("sv_repair_supervisor", {}),
        ]
        for tool, kw in llamadas:
            with self.subTest(tool=tool), capture_logs() as eventos:
                vista = await self.t[tool](**kw)
                await self.t[tool](**kw, confirmation_token=vista["confirmation_token"])
                propios = self._eventos(eventos)
                self.assertEqual([e["event"] for e in propios],
                                 ["system_control_preview", "system_control_done"])
                self.assertTrue(all(e["tool"] == tool for e in propios))
        with capture_logs() as eventos:
            await self.t["sv_reload_supervisor"]()
        self.assertEqual([e["event"] for e in self._eventos(eventos)],
                         ["system_control_done"])

    async def test_respuestas_redactadas(self) -> None:
        """Un secreto en `/core/info` no sale en ninguna respuesta."""
        self.sv.core_info["password"] = CENTINELA_SV
        self.sv.core_info["refresh_token"] = CENTINELA_SV
        self.sv.core_corre = False
        respuestas = [
            *await self._confirmar("sv_start_core"),
            *await self._confirmar("sv_rebuild_core"),
            *await self._confirmar("sv_set_core_options", options={"boot": False}),
        ]
        self.assertNotIn(CENTINELA_SV, _texto(respuestas))


if __name__ == "__main__":
    unittest.main()
