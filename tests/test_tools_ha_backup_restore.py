"""Restaurar un backup con la integración de HA (spec 031, tramo 3: T034-T036).

`ha_restore_backup` con `ws_send` simulado. Datos ficticios
(`hassio.nas_backups`, `cloud.cloud`, `core_mosquitto`, `192.0.2.10`,
`centinela-031`).

Sin `password`, un backup protegido se descifra con la clave de los backups
de HA, que `backup/config/info` devuelve EN CLARO: el centinela no puede salir
en ninguna vista previa, respuesta, error, log ni fichero de token. Tampoco la
`password` que pase el cliente (que solo entra en el HMAC del token).

Controles negativos (T045), comprobados:
- (b) sin las apps en la huella (`content`) cae
  `test_backup_cambiado_es_state_changed` (subtest «otra app»);
- (c) `completed` en vez de `restore_started` en el timeout cae
  `test_sin_respuesta_tras_enviar_es_restore_started`;
- (d) sin comprobar `not_in_backup` cae `test_no_esta_en_el_backup`;
- (e) `password` en la vista previa cae `test_secretos_fuera_de_todo`.
- (T063) con la clave añadida al `estado` del token cae
  `test_la_clave_no_entra_en_el_token`: el fichero del token solo guarda
  huellas HMAC, así que se espía lo que recibe `security`;
- (T064) con el aviso fijo «Home Assistant has no backup encryption key» cae
  `test_aviso_segun_el_motivo`.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from structlog.testing import capture_logs

from hermes import security
from hermes.ha import HAConnectionError
from hermes.tools import ha_backup_restore as mod
from hermes.tools import ha_backups as hb

_CENTINELA = "centinela-031"
_PASSWORD = "contrasena-del-cliente-031"


class _MCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, *a: Any, **k: Any):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


class _HA:
    def __init__(self, respuestas: dict[str, Any]) -> None:
        self.respuestas = respuestas
        self.enviados: list[dict[str, Any]] = []
        self.plazos: list[int] = []

    async def wait_ready(self, timeout: float = 5.0) -> bool:
        return True

    async def ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.enviados.append(copy.deepcopy(payload))
        self.plazos.append(timeout_seconds)
        r = self.respuestas.get(payload["type"], AssertionError(f"inesperado {payload['type']}"))
        if isinstance(r, BaseException):
            raise r
        return copy.deepcopy(r)

    def tipos(self) -> list[str]:
        return [p["type"] for p in self.enviados]

    def de_tipo(self, tipo: str) -> list[dict[str, Any]]:
        return [p for p in self.enviados if p["type"] == tipo]


def _config_info(password: Any = _CENTINELA) -> dict[str, Any]:
    return {"config": {
        "agents": {}, "automatic_backups_configured": True,
        "create_backup": {"agent_ids": ["hassio.local"], "include_addons": None,
                          "include_all_addons": True, "include_database": True,
                          "include_folders": None, "name": None, "password": password},
        "retention": {"copies": 3, "days": None},
        "schedule": {"days": [], "recurrence": "daily", "time": "04:30:00"},
    }}


def _agents_info(*ids: str) -> dict[str, Any]:
    ids = ids or ("hassio.local", "hassio.nas_backups", "cloud.cloud")
    return {"agents": [{"agent_id": a, "name": a.split(".")[1]} for a in ids]}


def _backup(agentes: dict[str, Any] | None = None, **cambios: Any) -> dict[str, Any]:
    b = {
        "backup_id": "abc123", "name": "Automatic backup 2026.11.1",
        "date": "2026-11-14T04:30:12+00:00",
        "agents": agentes if agentes is not None else {
            "hassio.local": {"protected": True, "size": 734003200},
            "cloud.cloud": {"protected": True, "size": 734003200},
        },
        "addons": [
            {"slug": "core_mosquitto", "name": "Mosquitto broker", "version": "6.5.1"},
            {"slug": "a0d7b954_vscode", "name": "Studio Code Server", "version": "5.19.0"},
        ],
        "folders": ["share", "media", "ssl"],
        "database_included": True, "homeassistant_included": True,
        "homeassistant_version": "2026.11.1", "with_automatic_settings": True,
        "extra_metadata": {"instance_id": "SENTINEL-INSTANCE"},
    }
    b.update(cambios)
    return b


def _respuestas(**extra: Any) -> dict[str, Any]:
    r: dict[str, Any] = {
        "backup/details": {"backup": _backup(), "agent_errors": {}},
        "backup/agents/info": _agents_info(),
        "backup/config/info": _config_info(),
        "backup/restore": None,
    }
    r.update(extra)
    return r


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name) / "tokens"
        self._parche = patch.object(hb, "ha_at_least", new=AsyncMock(return_value=True))
        self._parche.start()
        self.montar(_respuestas())

    def tearDown(self) -> None:
        self._parche.stop()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    def montar(self, respuestas: dict[str, Any], max_bytes: int = 131_072) -> None:
        self.ha = _HA(respuestas)
        mcp = _MCP()
        mod.register(mcp, self.ha, response_max_bytes=max_bytes)
        self.t = mcp.tools

    async def restore(self, **args: Any) -> dict[str, Any]:
        args.setdefault("backup_id", "abc123")
        return await self.t["ha_restore_backup"](**args)

    async def confirmar(self, **args: Any) -> dict[str, Any]:
        vista = await self.restore(**args)
        self.assertIn("confirmation_token", vista, vista)
        return await self.restore(**args, confirmation_token=vista["confirmation_token"])

    def ficheros(self) -> str:
        return "".join(p.read_text(encoding="utf-8")
                       for p in Path(self.temp_dir.name).rglob("*") if p.is_file())


# ── T034: vista previa ──────────────────────────────────────────────────────

class TestVistaPrevia(_Base):
    async def test_todos_los_datos_de_fr_007(self) -> None:
        r = await self.restore(restore_addons=["core_mosquitto"], restore_folders=["share"])
        p = r["preview"]
        self.assertEqual(p["action"], "restore_backup")
        self.assertEqual(p["backup"], {"backup_id": "abc123", "name": "Automatic backup 2026.11.1",
                                       "date": "2026-11-14T04:30:12+00:00",
                                       "homeassistant_version": "2026.11.1"})
        self.assertEqual(p["location"], {"agent_id": "hassio.local", "name": "local",
                                         "kind": "local", "protected": True,
                                         "size": 734003200, "also_in": ["cloud.cloud"]})
        self.assertEqual(p["password_source"], "backup_encryption_key")
        self.assertEqual(p["overwrites"], {
            "homeassistant_configuration": True, "database": True,
            "addons": [{"slug": "core_mosquitto", "name": "Mosquitto broker",
                        "version": "6.5.1"}],
            "folders": ["share"]})
        self.assertEqual(p["not_restored"]["addons"],
                         [{"slug": "a0d7b954_vscode", "name": "Studio Code Server",
                           "version": "5.19.0"}])
        self.assertEqual(p["not_restored"]["folders"], ["media", "ssl"])
        avisos = " ".join(p["warnings"])
        self.assertIn("LOST", avisos)
        self.assertIn("2026-11-14T04:30:12+00:00", avisos)
        self.assertIn("restarts", avisos)
        self.assertNotIn("downloaded", avisos)
        self.assertNotIn("backup/restore", self.ha.tipos())
        self.assertNotIn("SENTINEL-INSTANCE", json.dumps(r))

    async def test_sin_agent_id_elige_la_local(self) -> None:
        r = await self.restore()
        self.assertEqual(r["preview"]["location"]["agent_id"], "hassio.local")
        self.assertEqual(r["preview"]["location"]["also_in"], ["cloud.cloud"])

    async def test_solo_en_remotos_pide_agent_id(self) -> None:
        self.montar(_respuestas(**{"backup/details": {"backup": _backup({
            "cloud.cloud": {"protected": True, "size": 1},
            "hassio.nas_backups": {"protected": True, "size": 1}}), "agent_errors": {}}}))
        r = await self.restore()
        self.assertEqual(r["error"], "agent_id_required")
        self.assertEqual(r["locations"], ["cloud.cloud", "hassio.nas_backups"])
        self.assertNotIn("confirmation_token", r)
        # Con agent_id remoto: aviso de descarga.
        r = await self.restore(agent_id="cloud.cloud")
        self.assertEqual(r["preview"]["location"]["kind"], "remote")
        self.assertIn("downloaded", " ".join(r["preview"]["warnings"]))

    async def test_agent_id_donde_no_esta(self) -> None:
        r = await self.restore(agent_id="hassio.nas_backups")
        self.assertEqual(r["error"], "not_found")
        self.assertEqual(r["locations"], ["cloud.cloud", "hassio.local"])
        self.assertNotIn("confirmation_token", r)

    async def test_backup_que_no_existe(self) -> None:
        self.montar(_respuestas(**{"backup/details": {"backup": None, "agent_errors": {}}}))
        r = await self.restore()
        self.assertEqual(r["error"], "not_found")

    async def test_no_esta_en_el_backup(self) -> None:
        for args, falta in (({"restore_addons": ["otra_app"]}, "addons"),
                            ({"restore_folders": ["addons/local"]}, "folders")):
            with self.subTest(args=args):
                r = await self.restore(**args)
                self.assertEqual(r["error"], "not_in_backup", r)
                self.assertIn(falta, r["missing"])
                self.assertNotIn("confirmation_token", r)

    async def test_restore_database(self) -> None:
        # Por defecto, lo que trae el backup.
        r = await self.restore()
        self.assertIs(r["preview"]["overwrites"]["database"], True)
        self.montar(_respuestas(**{"backup/details": {
            "backup": _backup(database_included=False), "agent_errors": {}}}))
        r = await self.restore()
        self.assertIs(r["preview"]["overwrites"]["database"], False)
        # Con Supervisor, distinto con restore_homeassistant → invalid_argument.
        r = await self.restore(restore_database=True)
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "restore_database"))
        # Sin Supervisor (solo backup.local) se admite.
        self.montar(_respuestas(**{
            "backup/details": {"backup": _backup({"backup.local": {"protected": False,
                                                                   "size": 1}}),
                               "agent_errors": {}},
            "backup/agents/info": _agents_info("backup.local")}))
        r = await self.restore(restore_database=False)
        self.assertIs(r["preview"]["overwrites"]["database"], False)
        self.assertIs(r["preview"]["not_restored"]["database"], True)
        self.assertEqual(r["preview"]["location"]["agent_id"], "backup.local")

    async def test_argumentos_invalidos_sin_llamar_a_ha(self) -> None:
        casos = (
            ({"backup_id": "../x"}, "backup_id"),
            ({"agent_id": "sin punto"}, "agent_id"),
            ({"restore_homeassistant": "si"}, "restore_homeassistant"),
            ({"restore_database": "si"}, "restore_database"),
            ({"restore_database": True, "restore_homeassistant": False,
              "restore_folders": ["share"]}, "restore_database"),
            ({"restore_homeassistant": False}, "restore_homeassistant"),
            ({"restore_folders": ["homeassistant"]}, "restore_folders"),
            ({"restore_addons": ["core_mosquitto", "core_mosquitto"]}, "restore_addons"),
            ({"password": ""}, "password"),
        )
        for args, campo in casos:
            with self.subTest(args=args):
                r = await self.restore(**args)
                self.assertEqual((r.get("error"), r.get("field")), ("invalid_argument", campo), r)
        self.assertEqual(self.ha.enviados, [])

    async def test_apps_o_carpetas_sin_supervisor(self) -> None:
        self.montar(_respuestas(**{
            "backup/details": {"backup": _backup({"backup.local": {"protected": True,
                                                                   "size": 1}}),
                               "agent_errors": {}},
            "backup/agents/info": _agents_info("backup.local")}))
        for args, campo in (({"restore_addons": ["core_mosquitto"]}, "restore_addons"),
                            ({"restore_folders": ["share"]}, "restore_folders")):
            with self.subTest(args=args):
                r = await self.restore(**args)
                self.assertEqual((r.get("error"), r.get("field")), ("invalid_argument", campo))
        self.assertNotIn("backup/restore", self.ha.tipos())

    async def test_password_source(self) -> None:
        r = await self.restore(password=_PASSWORD)
        self.assertEqual(r["preview"]["password_source"], "provided")
        self.assertNotIn("backup/config/info", self.ha.tipos())
        self.montar(_respuestas(**{"backup/details": {"backup": _backup({
            "hassio.local": {"protected": False, "size": 1}}), "agent_errors": {}}}))
        r = await self.restore()
        self.assertEqual(r["preview"]["password_source"], "not_needed")
        self.assertNotIn("backup/config/info", self.ha.tipos())
        self.montar(_respuestas())
        r = await self.restore()
        self.assertEqual(r["preview"]["password_source"], "backup_encryption_key")
        for password in (None, ""):
            with self.subTest(password=password):
                self.montar(_respuestas(**{"backup/config/info": _config_info(password)}))
                r = await self.restore()
                self.assertEqual(r["preview"]["password_source"],
                                 "backup_encryption_key_unavailable")
                self.assertEqual(r["preview"]["password_source_reason"], "no_key_configured")
                self.assertIn("unless you pass password", " ".join(r["preview"]["warnings"]))

    async def test_aviso_si_se_restaura_hermes(self) -> None:
        b = _backup()
        b["addons"].append({"slug": "local_hermes", "name": "Hermes", "version": "1.1.2"})
        self.montar(_respuestas(**{"backup/details": {"backup": b, "agent_errors": {}}}))
        r = await self.restore(restore_addons=["local_hermes"])
        self.assertIn("Hermes itself is replaced", " ".join(r["preview"]["warnings"]))
        r = await self.restore(restore_addons=["core_mosquitto"])
        self.assertNotIn("Hermes itself", " ".join(r["preview"]["warnings"]))

    async def test_vista_previa_que_no_cabe(self) -> None:
        b = _backup()
        b["addons"] = [{"slug": f"app_{i}", "name": "X" * 80, "version": "1.0.0"}
                       for i in range(80)]
        self.montar(_respuestas(**{"backup/details": {"backup": b, "agent_errors": {}}}),
                    max_bytes=4096)
        r = await self.restore()
        self.assertEqual(r["error"], "response_too_large")
        self.assertNotIn("confirmation_token", r)
        self.assertFalse(security.CONFIRMATIONS_DIR.exists()
                         and any(security.CONFIRMATIONS_DIR.iterdir()))

    async def test_agente_ilegible(self) -> None:
        errores = {"hassio.nas_backups": "Timeout contacting 192.0.2.10 token=centinela-031"}
        self.montar(_respuestas(**{"backup/details": {"backup": None,
                                                      "agent_errors": errores}}))
        r = await self.restore()
        self.assertEqual(r["error"], "backup_locations_unreadable")
        self.assertNotIn("192.0.2.10", json.dumps(r))
        self.assertNotIn(_CENTINELA, json.dumps(r))

    async def test_secretos_fuera_de_todo(self) -> None:
        with capture_logs() as logs:
            v1 = await self.restore()
            r1 = await self.restore(confirmation_token=v1["confirmation_token"])
            v2 = await self.restore(password=_PASSWORD)
            r2 = await self.restore(password=_PASSWORD,
                                    confirmation_token=v2["confirmation_token"])
        self.assertEqual(r1, {"result": "completed"})
        self.assertEqual(r2, {"result": "completed"})
        for secreto in (_CENTINELA, _PASSWORD):
            with self.subTest(secreto=secreto):
                for cosa in (v1, r1, v2, r2, logs):
                    self.assertNotIn(secreto, json.dumps(cosa, default=str))
                self.assertNotIn(secreto, self.ficheros())


# ── T035: token atado ───────────────────────────────────────────────────────

class TestTokenAtado(_Base):
    async def test_backup_cambiado_es_state_changed(self) -> None:
        def con_app_de_mas() -> dict[str, Any]:
            b = _backup()
            b["addons"].append({"slug": "otra", "name": "Otra", "version": "1"})
            return b

        def con_otra_version() -> dict[str, Any]:
            b = _backup()
            b["addons"][0]["version"] = "6.5.2"
            return b

        cambios = {
            "fecha": _backup(date="2026-11-15T04:30:12+00:00"),
            "otra app": con_app_de_mas(),
            "otra versión": con_otra_version(),
            "protected": _backup({"hassio.local": {"protected": False, "size": 734003200},
                                  "cloud.cloud": {"protected": True, "size": 734003200}}),
            "tamaño": _backup({"hassio.local": {"protected": True, "size": 1},
                               "cloud.cloud": {"protected": True, "size": 734003200}}),
            "ya no está": _backup({"cloud.cloud": {"protected": True, "size": 734003200}}),
        }
        for nombre, nuevo in cambios.items():
            with self.subTest(cambio=nombre):
                self.montar(_respuestas())
                vista = await self.restore(agent_id="hassio.local")
                self.ha.respuestas["backup/details"] = {"backup": nuevo, "agent_errors": {}}
                r = await self.restore(agent_id="hassio.local",
                                       confirmation_token=vista["confirmation_token"])
                self.assertIn(r["error"], ("state_changed", "not_found"), r)
                if nombre != "ya no está":
                    self.assertEqual(r["error"], "state_changed")
                self.assertEqual(self.ha.de_tipo("backup/restore"), [])

    async def test_clave_quitada_entre_vista_y_confirmacion(self) -> None:
        vista = await self.restore()
        self.ha.respuestas["backup/config/info"] = _config_info(None)
        r = await self.restore(confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "state_changed")
        self.assertEqual(self.ha.de_tipo("backup/restore"), [])

    async def test_otra_password_invalida_el_token(self) -> None:
        vista = await self.restore(password=_PASSWORD)
        r = await self.restore(password="otra-031",
                               confirmation_token=vista["confirmation_token"])
        self.assertIn("does not match", r["error"])
        self.assertEqual(self.ha.de_tipo("backup/restore"), [])

    async def test_mismos_argumentos_restauran(self) -> None:
        r = await self.confirmar(restore_addons=["core_mosquitto"], restore_folders=["share"])
        self.assertEqual(r, {"result": "completed"})
        [enviado] = self.ha.de_tipo("backup/restore")
        self.assertEqual(enviado, {
            "type": "backup/restore", "backup_id": "abc123", "agent_id": "hassio.local",
            "restore_homeassistant": True, "restore_database": True,
            "restore_addons": ["core_mosquitto"], "restore_folders": ["share"],
            "password": _CENTINELA})
        self.assertEqual(self.ha.plazos[self.ha.tipos().index("backup/restore")], 30)
        # Con password, la dada.
        self.montar(_respuestas())
        await self.confirmar(password=_PASSWORD)
        self.assertEqual(self.ha.de_tipo("backup/restore")[0]["password"], _PASSWORD)
        # No protegido: sin password.
        self.montar(_respuestas(**{"backup/details": {"backup": _backup({
            "hassio.local": {"protected": False, "size": 1}}), "agent_errors": {}}}))
        await self.confirmar()
        self.assertNotIn("password", self.ha.de_tipo("backup/restore")[0])


# ── T036: resultado ─────────────────────────────────────────────────────────

class TestResultado(_Base):
    async def _con_error(self, exc: BaseException, **args: Any) -> dict[str, Any]:
        self.ha.respuestas["backup/restore"] = exc
        return await self.confirmar(**args)

    def estado_token(self) -> dict[str, Any]:
        [f] = list(security.CONFIRMATIONS_DIR.glob("*.json"))
        return json.loads(f.read_text(encoding="utf-8"))

    async def test_completed(self) -> None:
        self.assertEqual(await self.confirmar(), {"result": "completed"})
        self.assertEqual(self.estado_token()["state"], "completed")

    async def test_password_incorrect(self) -> None:
        r = await self._con_error(HAConnectionError("HA WS command failed: Incorrect password",
                                                    code="password_incorrect"))
        self.assertEqual(r["error"], "password_incorrect")
        self.assertIn("older key", r["hint"])
        self.assertEqual(self.estado_token()["state"], "failed")

    async def test_backup_not_found(self) -> None:
        r = await self._con_error(HAConnectionError("HA WS command failed: Backup not found",
                                                    code="backup_not_found"))
        self.assertEqual(r["error"], "backup_not_found")
        self.assertEqual(self.estado_token()["state"], "failed")

    async def test_otro_error_redactado(self) -> None:
        # Un error que citara lo que se mandó (la clave de HA o la password
        # del cliente) sale tapado, igual que la red.
        for secreto, args in ((_CENTINELA, {}), (_PASSWORD, {"password": _PASSWORD})):
            with self.subTest(secreto=secreto):
                self.montar(_respuestas())
                for f in security.CONFIRMATIONS_DIR.glob("*.json"):
                    f.unlink()
                r = await self._con_error(HAConnectionError(
                    f"HA WS command failed: cannot reach 192.0.2.10 with {secreto}",
                    code="home_assistant_error"), **args)
                self.assertEqual(r["error"], "restore_failed")
                texto = json.dumps(r)
                for prohibido in ("192.0.2.10", secreto):
                    self.assertNotIn(prohibido, texto)
                self.assertEqual(self.estado_token()["state"], "failed")

    async def test_sin_respuesta_tras_enviar_es_restore_started(self) -> None:
        for exc in (HAConnectionError("Timeout waiting for HA WS response", sent=True),
                    HAConnectionError("WebSocket cerrado por Home Assistant.", sent=True)):
            with self.subTest(exc=str(exc)):
                self.montar(_respuestas())
                for f in security.CONFIRMATIONS_DIR.glob("*.json"):
                    f.unlink()
                r = await self._con_error(exc)
                self.assertEqual(r["status"], "restore_started")
                self.assertNotIn("result", r)
                self.assertTrue(any("ha_list_backups" in c for c in r["check_with"]))
                token = self.estado_token()
                self.assertEqual(token["state"], "completed")

    async def test_orden_no_enviada_es_error(self) -> None:
        r = await self._con_error(HAConnectionError("WebSocket no disponible", sent=False))
        self.assertEqual(r["error"], "ha_unreachable")
        self.assertNotIn("status", r)
        self.assertEqual(self.estado_token()["state"], "failed")

    async def test_sent_desconocido_no_afirma_ni_envio_ni_nada_cambio(self) -> None:
        # Contrato de la 022: `sent=None` (por defecto) es «no se sabe o no
        # aplica». Ni `restore_started` (afirmaría que salió) ni
        # `ha_unreachable` (afirmaría que nada cambió). Control negativo
        # (integración de la 031): con la condición antigua
        # (`codigo is None` sin mirar `sent is False`) salía `ha_unreachable`.
        r = await self._con_error(HAConnectionError("HA WS command failed: boom"))
        self.assertEqual(r["error"], "restore_failed")
        self.assertNotIn("status", r)
        self.assertEqual(self.estado_token()["state"], "failed")



# ── T063 y T064 (convergencia de la revisión) ───────────────────────────────

class TestConvergencia(_Base):
    async def test_la_clave_no_entra_en_el_token(self) -> None:
        # Ni en los argumentos ni en el estado que se atan al token, en los
        # dos pasos (sin la 019, la huella en disco sería atacable).
        vistos: list[Any] = []
        crear, resolver = mod.create_confirmation_token, mod.resolve_confirmation_token

        async def espia_crear(tool, args, **kw):
            vistos.append((args, kw.get("estado")))
            return await crear(tool, args, **kw)

        async def espia_resolver(token, tool, args, **kw):
            vistos.append((args, kw.get("estado")))
            return await resolver(token, tool, args, **kw)

        with patch.object(mod, "create_confirmation_token", espia_crear), \
                patch.object(mod, "resolve_confirmation_token", espia_resolver):
            r = await self.confirmar()
        self.assertEqual(r, {"result": "completed"})
        self.assertEqual(len(vistos), 2)
        self.assertTrue(all(e["password_source"] == "backup_encryption_key"
                            for _, e in vistos))
        self.assertNotIn(_CENTINELA, json.dumps(vistos, default=str))
        self.assertNotIn(_CENTINELA, self.ficheros())

    async def test_aviso_segun_el_motivo(self) -> None:
        # «No tiene clave» solo si es verdad; si HA no responde o la
        # integración no está, se dice que no se pudo leer.
        casos = {
            "no_key_configured": (_config_info(None), "has no backup encryption key"),
            "ha_unreachable": (HAConnectionError("WebSocket no disponible"),
                               "did not answer"),
            "backup_integration_unavailable": (
                HAConnectionError("HA WS command failed: Unknown command.",
                                  code="unknown_command"),
                "backup integration is not available"),
        }
        for motivo, (respuesta, frase) in casos.items():
            with self.subTest(motivo=motivo):
                self.montar(_respuestas(**{"backup/config/info": respuesta}))
                r = await self.restore()
                avisos = " ".join(r["preview"]["warnings"])
                self.assertEqual(r["preview"]["password_source_reason"], motivo)
                self.assertIn(frase, avisos)
                self.assertIn("unless you pass password", avisos)
                if motivo != "no_key_configured":
                    self.assertNotIn("has no backup encryption key", avisos)


if __name__ == "__main__":
    unittest.main()
