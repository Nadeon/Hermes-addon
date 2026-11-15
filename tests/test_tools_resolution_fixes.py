"""Aplicar sugerencias del centro de resolución (spec 022, tramo 2; CAP-087).

`sv_apply_resolution_suggestion` contra el Supervisor simulado de
`tests/fixtures/supervisor_control.py` (forma del Supervisor 2026.11.0, datos
ficticios). Lo que se vigila:

- cada par con fixup se traduce a su efecto, lo que corta, cuánto tarda y si
  se puede deshacer (SC-003: un subtest por par);
- los rechazos (FR-010) no emiten token ni producen ningún `POST`;
- Hermes se reconoce por el slug EXACTO de `/addons/self/info`, nunca por el
  sufijo `_hermes` (decisión del supervisor del programa);
- el token ata la sugerencia y, como estado, la lista de backups a borrar, la
  de contenedores y la de arreglos automáticos (FR-011): si cambia, se
  rechaza sin aplicar;
- al log van tipo, contexto y resultado; nunca `reference` (FR-019).

Controles negativos del tramo (T028), con recuentos, en el mensaje del commit.
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import MagicMock

import aiohttp
from structlog.testing import capture_logs

from hermes.ha import HAConnectionError, HATimeoutError
from hermes.tools.resolution_fixes import _FIXUPS, register
from tests.fixtures.supervisor_control import (
    CENTINELA_SV,
    SLUG_HERMES,
    SLUG_OTRA_HERMES,
    SupervisorDeControl,
    backup,
    error_400,
    issue,
    sugerencia,
)

_U1 = "1" * 32
_U2 = "2" * 32
_U3 = "3" * 32
_U4 = "4" * 32
_TOOL = "sv_apply_resolution_suggestion"

# Referencia de ejemplo por contexto (ficticias).
_REF = {"addon": "local_ejemplo", "mount": "nas_backups", "plugin": "dns",
        "store": "a1b2c3d4", "core": None, "system": None}


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
        self.sv.addons["local_ejemplo"] = {"slug": "local_ejemplo", "name": "Ejemplo",
                                           "state": "stopped"}
        self.mcp = DummyMCP()
        register(self.mcp, self.sv, response_max_bytes=131_072)
        self.apply = self.mcp.tools[_TOOL]

    def poner(self, *sugerencias: dict[str, Any], issues: list | None = None) -> None:
        self.sv.resolution["suggestions"] = list(sugerencias)
        self.sv.resolution["issues"] = issues or []

    def posts(self) -> list[str]:
        return [c["ruta"] for c in self.sv.escrituras]

    async def rechazo(self, code: str, uuid: str = _U1) -> dict[str, Any]:
        r = await self.apply(uuid)
        self.assertEqual(r.get("error"), code, r)
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.posts(), [])
        return r


# ── T018: traducción, detalles y ejecución (FR-009, FR-019) ──────────────────


class TestTraduccion(_Base):
    async def test_cada_par_con_fixup(self) -> None:
        """SC-003: cada par de la tabla da su traducción y un token."""
        for (tipo, contexto), fx in _FIXUPS.items():
            with self.subTest(par=(tipo, contexto)):
                self.setUp()
                self.poner(sugerencia(_U1, tipo, contexto, _REF[contexto]))
                r = await self.apply(_U1)
                self.assertIn("confirmation_token", r, r)
                p = r["preview"]
                self.assertEqual(p["action"], "apply_resolution_suggestion")
                self.assertEqual((p["suggestion"]["type"], p["suggestion"]["context"]),
                                 (tipo, contexto))
                self.assertEqual((p["interrupts"], p["duration"], p["reversible"]),
                                 (fx.interrupts, fx.duration, fx.reversible))
                if (tipo, contexto) != ("clear_full_backup", "system"):
                    self.assertEqual(p["effect"], fx.effect)
                self.assertEqual(p["verify_with"], "sv_get_resolution")
                self.assertEqual(self.posts(), [])

    def test_tabla_coherente_con_data_model(self) -> None:
        # Los irreversibles de data-model, y solo ellos.
        irreversibles = sorted(k for k, f in _FIXUPS.items() if f.reversible is False)
        self.assertEqual(irreversibles, sorted([
            ("execute_remove", "addon"), ("execute_remove", "mount"),
            ("move_local_data", "mount"), ("execute_remove", "store"),
            ("clear_full_backup", "system")]))
        self.assertEqual(len(_FIXUPS), 22)

    async def test_clear_full_backup_lista_los_antiguos(self) -> None:
        self.sv.backups = [
            backup("b4", "2026-11-04T00:00:00+00:00"),
            backup("b1", "2026-11-01T00:00:00+00:00"),
            backup("p0", "2026-10-01T00:00:00+00:00", tipo="partial"),
            backup("b3", "2026-11-03T00:00:00+00:00"),
            backup("b2", "2026-11-02T00:00:00+00:00"),
        ]
        self.poner(sugerencia(_U1, "clear_full_backup", "system"))
        r = await self.apply(_U1)
        borrar = r["preview"]["details"]["backups_to_delete"]
        self.assertEqual([b["slug"] for b in borrar], ["b1", "b2"])
        self.assertEqual(set(borrar[0]), {"slug", "name", "date", "size", "locations"})
        self.assertIn("cannot be undone", _texto(r["preview"]["warnings"]))

    async def test_clear_full_backup_con_dos_no_borra_nada(self) -> None:
        self.sv.backups = [backup("b1", "2026-11-01T00:00:00+00:00"),
                           backup("b2", "2026-11-02T00:00:00+00:00"),
                           backup("p0", "2026-10-01T00:00:00+00:00", tipo="partial")]
        self.poner(sugerencia(_U1, "clear_full_backup", "system"))
        r = await self.apply(_U1)
        p = r["preview"]
        self.assertEqual(p["details"]["backups_to_delete"], [])
        self.assertIn("deletes nothing", p["effect"])

    async def test_rebuild_system_lista_contenedores(self) -> None:
        self.poner(sugerencia(_U1, "execute_rebuild", "system"),
                   sugerencia(_U2, "execute_rebuild", "addon", "local_ejemplo"),
                   sugerencia(_U3, "execute_rebuild", "plugin", "dns"),
                   sugerencia(_U4, "execute_restart", "addon", "local_ejemplo"))
        r = await self.apply(_U1)
        self.assertEqual(r["preview"]["details"]["containers_to_rebuild"], [
            {"context": "addon", "reference": "local_ejemplo"},
            {"context": "plugin", "reference": "dns"}])

    async def test_contexto_addon_trae_la_app(self) -> None:
        self.poner(sugerencia(_U1, "execute_start", "addon", "local_ejemplo"))
        r = await self.apply(_U1)
        self.assertEqual(r["preview"]["details"]["app"],
                         {"slug": "local_ejemplo", "name": "Ejemplo", "state": "stopped"})

    async def test_also_auto_applied_y_aviso(self) -> None:
        self.poner(sugerencia(_U1, "create_full_backup", "system"),
                   sugerencia(_U2, "execute_rebuild", "plugin", "dns", auto=True),
                   sugerencia(_U3, "execute_reload", "store", "a1b2c3d4", auto=True),
                   sugerencia(_U4, "execute_restart", "addon", "local_ejemplo"))
        r = await self.apply(_U1)
        p = r["preview"]
        self.assertEqual(p["also_auto_applied"], [
            {"uuid": _U2, "type": "execute_rebuild", "context": "plugin"},
            {"uuid": _U3, "type": "execute_reload", "context": "store"}])
        self.assertIn("automatic fixes", _texto(p["warnings"]))

    async def test_issues_ligados(self) -> None:
        self.poner(sugerencia(_U1, "execute_start", "addon", "local_ejemplo"),
                   issues=[issue(_U2, "fatal_error", "addon", "local_ejemplo"),
                           issue(_U3, "free_space", "system")])
        r = await self.apply(_U1)
        self.assertEqual([i["uuid"] for i in r["preview"]["issues"]], [_U2])

    async def test_uuid_con_guiones(self) -> None:
        self.poner(sugerencia(_U1, "enable_ntp", "system"))
        con_guiones = f"{_U1[:8]}-{_U1[8:12]}-{_U1[12:16]}-{_U1[16:20]}-{_U1[20:]}"
        r = await self.apply(con_guiones)
        self.assertIn("confirmation_token", r)

    async def test_confirmar_aplica_una_vez(self) -> None:
        self.poner(sugerencia(_U1, "enable_ntp", "system"))
        vista = await self.apply(_U1)
        r = await self.apply(_U1, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r, {"result": "ok", "effect": "starts the time sync service",
                             "verify_with": "sv_get_resolution"})
        self.assertEqual([(c["ruta"], c["timeout"]) for c in self.sv.escrituras],
                         [(f"/resolution/suggestion/{_U1}", 900.0)])

    async def test_tiempo_vencido_es_started(self) -> None:
        self.poner(sugerencia(_U1, "create_full_backup", "system"))
        self.sv.errores[("POST", f"/resolution/suggestion/{_U1}")] = TimeoutError()
        vista = await self.apply(_U1)
        r = await self.apply(_U1, confirmation_token=vista["confirmation_token"])
        self.assertEqual((r["status"], r["verify_with"]), ("started", "sv_get_resolution"))

    # Cierre de robustez 1.2.0: el plazo agotado sale del cliente como
    # `HATimeoutError` (`HAConnectionError` y `TimeoutError` a la vez, `sent`
    # en `None`). Tiene que seguir leyéndose como plazo, no como error. Aquí
    # también pasaría sin `TimeoutError` en sus bases (sin `status` ni `code`
    # ya se lee como corte); el control negativo de esa herencia lo dan
    # `sv_update_core` y `ha_install_update`.
    async def test_tiempo_vencido_con_el_plazo_del_cliente(self) -> None:
        self.poner(sugerencia(_U1, "create_full_backup", "system"))
        self.sv.errores[("POST", f"/resolution/suggestion/{_U1}")] = HATimeoutError("p")
        vista = await self.apply(_U1)
        r = await self.apply(_U1, confirmation_token=vista["confirmation_token"])
        self.assertEqual((r["status"], r["verify_with"]), ("started", "sv_get_resolution"))

    async def test_error_del_fixup_redactado(self) -> None:
        self.poner(sugerencia(_U1, "enable_ntp", "system"))
        self.sv.errores[("POST", f"/resolution/suggestion/{_U1}")] = error_400(
            f"/resolution/suggestion/{_U1}", f"failed password={CENTINELA_SV}")
        vista = await self.apply(_U1)
        r = await self.apply(_U1, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "supervisor_request_failed")
        self.assertNotIn(CENTINELA_SV, _texto(r))


# ── Fase 3: convergencia (T030-T035) ─────────────────────────────────────────


class TestConvergencia(_Base):
    """Arreglos de la revisión independiente. Cada uno con su control
    negativo, anotado en el docstring del test."""

    async def test_clear_port_config_arranca_y_no_reinicia(self) -> None:
        """T030: el fixup llama a `app.start()`, que arranca la app parada y
        no reinicia la que ya corre. Control negativo: con el texto anterior
        («the app restarts if it is running») falla."""
        self.poner(sugerencia(_U1, "clear_port_config", "addon", "local_ejemplo"))
        p = (await self.apply(_U1))["preview"]
        self.assertIn("starts the app if it is stopped", p["effect"])
        self.assertIn("not restarted", p["effect"])
        self.assertIn("keeps the old mapping until its next restart", p["effect"])
        self.assertNotIn("restart", p["interrupts"])
        self.assertIn("stopped app is started", p["interrupts"])

    async def test_clear_full_backup_todas_las_ubicaciones(self) -> None:
        """T031: cada backup a borrar lleva TODAS sus ubicaciones y, si alguna
        está fuera del host, el primer aviso lo dice. Control negativo: sin
        `locations` en `backups_to_delete` (o sin el aviso) falla."""
        self.sv.backups = [
            backup("b1", "2026-11-01T00:00:00+00:00", ubicaciones=[None, "nas_backups"]),
            backup("b2", "2026-11-02T00:00:00+00:00"),
            backup("b3", "2026-11-03T00:00:00+00:00"),
            backup("b4", "2026-11-04T00:00:00+00:00"),
        ]
        self.poner(sugerencia(_U1, "clear_full_backup", "system"))
        r = await self.apply(_U1)
        p = r["preview"]
        borrar = p["details"]["backups_to_delete"]
        self.assertEqual([b["slug"] for b in borrar], ["b1", "b2"])
        self.assertEqual(
            [(u["location"], u["kind"], u["off_host"]) for u in borrar[0]["locations"]],
            [("local", "local", False), ("nas_backups", "network", True)])
        self.assertEqual([u["location"] for u in borrar[1]["locations"]], ["local"])
        self.assertIs(p["details"]["off_host_copies_deleted"], True)
        self.assertTrue(p["warnings"][0].startswith("OFF-HOST COPIES"), p["warnings"])
        self.assertIn("nas_backups", p["warnings"][0])
        self.assertIn("ALL its locations", p["effect"])
        # La carpeta `.cloud_backup` no sale en /backups: se avisa.
        self.assertIn(".cloud_backup", _texto(p["warnings"]))

    async def test_clear_full_backup_solo_local_sin_aviso_fuera(self) -> None:
        self.sv.backups = [backup(f"b{i}", f"2026-11-0{i}T00:00:00+00:00")
                           for i in range(1, 4)]
        self.poner(sugerencia(_U1, "clear_full_backup", "system"))
        p = (await self.apply(_U1))["preview"]
        self.assertIs(p["details"]["off_host_copies_deleted"], False)
        self.assertNotIn("OFF-HOST", _texto(p["warnings"]))

    async def test_clear_full_backup_sin_ubicaciones_no_hay_token(self) -> None:
        """T031, fail-closed: sin saber de dónde se borra un backup, no hay
        token. Control negativo: aceptando cualquier `locations` falla."""
        for malas in ([], "local", [None, 3], None):
            with self.subTest(locations=malas):
                self.setUp()
                self.sv.backups = [backup(f"b{i}", f"2026-11-0{i}T00:00:00+00:00")
                                   for i in range(1, 4)]
                if malas is None:
                    del self.sv.backups[0]["locations"]
                else:
                    self.sv.backups[0]["locations"] = malas
                self.poner(sugerencia(_U1, "clear_full_backup", "system"))
                r = await self.rechazo("supervisor_request_failed")
                self.assertIn("where each backup", r["detail"])

    async def test_clear_full_backup_ubicaciones_atadas_al_token(self) -> None:
        """T031: si un backup a borrar gana una copia en el NAS entre la vista
        previa y la confirmación, `suggestion_changed`. Control negativo:
        atando solo los slugs, se aplica."""
        self.sv.backups = [backup(f"b{i}", f"2026-11-0{i}T00:00:00+00:00")
                           for i in range(1, 4)]
        self.poner(sugerencia(_U1, "clear_full_backup", "system"))
        vista = await self.apply(_U1)
        self.sv.backups[0]["locations"] = [None, "nas_backups"]
        r = await self.apply(_U1, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "suggestion_changed")
        self.assertEqual(self.posts(), [])

    async def test_no_enviada_es_error_y_no_started(self) -> None:
        """T032: con el cliente HTTP sin inicializar o sin poder conectar, la
        petición no salió: error con `sent: false`, nunca `started`. Control
        negativo: sin `_no_enviada` en `_es_corte`, sale `started`."""
        conector = aiohttp.ClientConnectorError(MagicMock(), OSError(111, "refused"))
        for nombre, exc in (
                ("no_inicializado",
                 HAConnectionError("Cliente HTTP de HA no inicializado.", sent=False)),
                ("sin_conexion", conector)):
            with self.subTest(caso=nombre):
                self.setUp()
                self.poner(sugerencia(_U1, "enable_ntp", "system"))
                self.sv.errores[("POST", f"/resolution/suggestion/{_U1}")] = exc
                vista = await self.apply(_U1)
                r = await self.apply(_U1, confirmation_token=vista["confirmation_token"])
                self.assertEqual(r["error"], "supervisor_request_failed")
                self.assertIs(r["sent"], False)
                self.assertNotIn("status", r)
                self.assertIn("nothing was done", r["note"])

    async def test_auto_aplicadas_no_es_lista_completa(self) -> None:
        """T033: los chequeos del healthcheck pueden añadir sugerencias
        automáticas nuevas; el aviso lo dice aunque hoy no haya ninguna.
        Control negativo: con el aviso anterior (solo si hay lista) falla."""
        self.poner(sugerencia(_U1, "enable_ntp", "system"))
        p = (await self.apply(_U1))["preview"]
        self.assertEqual(p["also_auto_applied"], [])
        avisos = _texto(p["warnings"])
        self.assertIn("known now", avisos)
        self.assertIn("new ones the checks add", avisos)

    async def test_create_full_backup_para_las_apps_en_frio(self) -> None:
        """T035: `do_backup_full` para durante la copia las apps con backup en
        frío. Control negativo: con «nothing (uses disk space)» falla."""
        self.poner(sugerencia(_U1, "create_full_backup", "system"))
        p = (await self.apply(_U1))["preview"]
        self.assertIn("cold backup mode", p["interrupts"])
        self.assertNotIn("nothing", p["interrupts"])
        self.assertIn("cannot list them", _texto(p["warnings"]))


class TestLog(_Base):
    async def test_eventos_sin_reference(self) -> None:
        self.poner(sugerencia(_U1, "execute_start", "addon", "local_ejemplo"),
                   sugerencia(_U2, "execute_stop", "addon", "local_ejemplo"))
        with capture_logs() as eventos:
            vista = await self.apply(_U1)
            await self.apply(_U1, confirmation_token=vista["confirmation_token"])
            await self.apply(_U2)
        nombres = [e["event"] for e in eventos if e["event"].startswith("resolution_fix_")]
        self.assertEqual(nombres, ["resolution_fix_preview", "resolution_fix_done",
                                   "resolution_fix_rejected"])
        for e in eventos:
            if e["event"].startswith("resolution_fix_"):
                self.assertEqual(e["context"], "addon")
                self.assertIn("suggestion_type", e)
        self.assertEqual(eventos[-1]["code"], "no_fixup")
        self.assertNotIn("local_ejemplo", _texto(eventos))


# ── T019: rechazos, token y estado (FR-010, FR-011) ──────────────────────────


class TestRechazos(_Base):
    async def test_uuid_invalido(self) -> None:
        for malo in ("../core/stop", "x" * 32, "", "1" * 31):
            with self.subTest(malo=malo):
                r = await self.apply(malo)
                self.assertEqual((r["error"], r["field"]),
                                 ("invalid_argument", "suggestion_uuid"))
        self.assertEqual(self.sv.llamadas, [])

    async def test_inexistente(self) -> None:
        self.poner(sugerencia(_U2, "enable_ntp", "system"))
        await self.rechazo("suggestion_not_found")

    async def test_sin_fixup(self) -> None:
        for tipo, contexto in (("execute_stop", "addon"), ("execute_update", "core"),
                               ("registry_login", "system"), ("execute_reboot", "addon")):
            with self.subTest(par=(tipo, contexto)):
                self.setUp()
                self.poner(sugerencia(_U1, tipo, contexto, _REF.get(contexto)))
                await self.rechazo("no_fixup")

    async def test_efecto_desconocido(self) -> None:
        for tipo, contexto in (("execute_teleport", "system"), ("execute_start", "galaxy")):
            with self.subTest(par=(tipo, contexto)):
                self.setUp()
                self.poner(sugerencia(_U1, tipo, contexto))
                await self.rechazo("unknown_effect")

    async def test_discos_de_datos(self) -> None:
        for tipo in ("adopt_data_disk", "rename_data_disk"):
            with self.subTest(tipo=tipo):
                self.setUp()
                self.poner(sugerencia(_U1, tipo, "system"))
                r = await self.rechazo("not_allowed")
                self.assertIn("reason", r)

    async def test_apunta_a_hermes(self) -> None:
        casos = {
            "addon": [sugerencia(_U1, "execute_restart", "addon", SLUG_HERMES)],
            "remove": [sugerencia(_U1, "execute_remove", "addon", SLUG_HERMES)],
            "rebuild_system": [sugerencia(_U1, "execute_rebuild", "system"),
                               sugerencia(_U2, "execute_rebuild", "addon", SLUG_HERMES)],
            "autofix": [sugerencia(_U1, "enable_ntp", "system"),
                        sugerencia(_U2, "execute_repair", "addon", SLUG_HERMES, auto=True)],
        }
        for nombre, sugs in casos.items():
            with self.subTest(caso=nombre):
                self.setUp()
                self.poner(*sugs)
                await self.rechazo("targets_hermes")

    async def test_otra_app_acabada_en_hermes_no_es_hermes(self) -> None:
        """El slug se compara exacto con `/addons/self/info`: una app que se
        llama `<otro>_hermes` no es Hermes."""
        self.sv.addons[SLUG_OTRA_HERMES] = {"slug": SLUG_OTRA_HERMES, "name": "Otra",
                                            "state": "started"}
        self.poner(sugerencia(_U1, "execute_restart", "addon", SLUG_OTRA_HERMES))
        r = await self.apply(_U1)
        self.assertIn("confirmation_token", r, r)

    async def test_sin_saber_quien_es_hermes_no_hay_token(self) -> None:
        self.sv.errores[("GET", "/addons/self/info")] = error_400("/addons/self/info", "x")
        self.poner(sugerencia(_U1, "execute_restart", "addon", "local_ejemplo"))
        await self.rechazo("supervisor_request_failed")

    async def test_rechazos_al_confirmar(self) -> None:
        """Lo que pasa a apuntar a Hermes entre vista previa y confirmación se
        rechaza al confirmar, sin `POST`."""
        self.poner(sugerencia(_U1, "execute_rebuild", "system"),
                   sugerencia(_U2, "execute_rebuild", "plugin", "dns"))
        vista = await self.apply(_U1)
        self.poner(sugerencia(_U1, "execute_rebuild", "system"),
                   sugerencia(_U2, "execute_rebuild", "addon", SLUG_HERMES))
        r = await self.apply(_U1, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "targets_hermes")
        self.assertEqual(self.posts(), [])


class TestTokenYEstado(_Base):
    async def test_otro_uuid(self) -> None:
        self.poner(sugerencia(_U1, "enable_ntp", "system"),
                   sugerencia(_U2, "enable_ntp", "system"))
        vista = await self.apply(_U1)
        r = await self.apply(_U2, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "invalid_confirmation_token")
        self.assertEqual(self.posts(), [])

    async def test_desaparece(self) -> None:
        self.poner(sugerencia(_U1, "enable_ntp", "system"))
        vista = await self.apply(_U1)
        self.poner()
        r = await self.apply(_U1, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "suggestion_not_found")
        self.assertEqual(self.posts(), [])

    async def test_cambios_de_estado(self) -> None:
        def ref() -> None:
            self.poner(sugerencia(_U1, "execute_start", "addon", "local_otra"))

        def backups() -> None:
            self.sv.backups.append(backup("b5", "2026-11-05T00:00:00+00:00"))

        def autofix() -> None:
            self.sv.resolution["suggestions"].append(
                sugerencia(_U3, "execute_reload", "store", "a1b2c3d4", auto=True))

        for nombre, cambio, sug in (
                ("reference", ref, sugerencia(_U1, "execute_start", "addon", "local_ejemplo")),
                ("backups", backups, sugerencia(_U1, "clear_full_backup", "system")),
                ("autofixes", autofix, sugerencia(_U1, "enable_ntp", "system"))):
            with self.subTest(cambio=nombre):
                self.setUp()
                self.sv.backups = [backup(f"b{i}", f"2026-11-0{i}T00:00:00+00:00")
                                   for i in range(1, 5)]
                self.poner(sug)
                vista = await self.apply(_U1)
                cambio()
                r = await self.apply(_U1, confirmation_token=vista["confirmation_token"])
                self.assertEqual(r["error"], "suggestion_changed")
                self.assertEqual(self.posts(), [])


if __name__ == "__main__":
    unittest.main()
