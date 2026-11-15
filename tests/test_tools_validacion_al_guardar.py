"""Validación al guardar (spec 017, tramo D, T043, FR-010; FR-062 de la 008).

La vista previa de `ha_create_or_update_automation` y `_script` valida con
`validate_config` (y, con `use_blueprint`, sustituye antes con
`blueprint/substitute`). Una configuración que HA rechazaría, o que no se
pudo validar, sale sin token. La confirmación no vuelve a validar.

Transporte: REST de config con `aioresponses` (como los tests de
automatizaciones y scripts) y `ws_send` simulado por `type`. Datos
ficticios.

Controles negativos (T054), comprobados y restaurados:
1. emitir token aunque una parte sea inválida → caen los `test_parte_invalida`;
2. dar token si `validate_config` falla → caen los `test_validacion_no_disponible`
   y `test_respuesta_que_no_es_objeto`;
3. validar sin sustituir el blueprint (mandar la config con `use_blueprint`
   a `validate_config`) → caen los `test_use_blueprint`.
4. (convergencia, T057) tratar `unknown_command` como cualquier otro fallo
   (sin token) → caen `test_ha_sin_validate_config` y
   `test_ha_sin_blueprint_substitute`; darlo con cualquier código → caen
   `test_validacion_no_disponible` y `test_sustitucion_fallida`.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes import security
from hermes.ha import HAConnectionError
from hermes.models.automation import AutomationConfig
from hermes.models.script import ScriptConfig
import hermes.tools.automations as automations_module
import hermes.tools.scripts as scripts_module

from tests._ha_fixture import REST_BASE, make_ready_client

CENTINELA = "centinela-017"


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


class FakeWS:
    """`ws_send` simulado: respuestas por `type`, y registro de lo enviado."""

    def __init__(self) -> None:
        self.enviados: list[dict] = []
        self.invalidas: dict[str, str] = {}
        self.respuesta_validacion: Any = None
        self.error_validacion: Exception | None = None
        self.sustituida: dict | None = None
        self.error_sustitucion: Exception | None = None

    async def __call__(self, payload: dict, timeout_seconds: int = 30) -> Any:
        self.enviados.append(payload)
        if payload["type"] == "validate_config":
            if self.error_validacion is not None:
                raise self.error_validacion
            if self.respuesta_validacion is not None:
                return self.respuesta_validacion
            return {
                k: ({"valid": False, "error": self.invalidas[k]} if k in self.invalidas
                    else {"valid": True, "error": None})
                for k in payload if k != "type"
            }
        if payload["type"] == "blueprint/substitute":
            if self.error_sustitucion is not None:
                raise self.error_sustitucion
            return {"substituted_config": self.sustituida}
        raise AssertionError(f"comando inesperado: {payload}")

    def de_tipo(self, tipo: str) -> list[dict]:
        return [p for p in self.enviados if p["type"] == tipo]


# Lo que cambia entre automatizaciones y scripts.
_AUTOMATIZACION = {
    "tool": "ha_create_or_update_automation", "id": "automation.cocina",
    "url": f"{REST_BASE}/config/automation/config/1689", "dominio": "automation",
    "valida": {"alias": "Ficticia", "mode": "single",
               "triggers": [{"trigger": "state", "entity_id": "light.salon"}],
               "actions": [{"action": "light.turn_off", "target": {"entity_id": "light.salon"}}]},
    "partes": ["actions", "triggers"],
    "parte_invalida": "triggers",
    "modelo": AutomationConfig,
}
_SCRIPT = {
    "tool": "ha_create_or_update_script", "id": "script.saludar",
    "url": f"{REST_BASE}/config/script/config/saludar", "dominio": "script",
    "valida": {"alias": "Ficticio", "mode": "single",
               "sequence": [{"action": "light.turn_on", "target": {"entity_id": "light.salon"}}]},
    "partes": ["actions"],
    "parte_invalida": "actions",
    "modelo": ScriptConfig,
}


class _Base:
    """Mezcla con los tests; cada subclase fija `C` (automatización o script)."""

    C: dict[str, Any] = {}

    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.session = ClientSession()
        cache = {"automation.cocina": {"entity_id": "automation.cocina", "state": "on",
                                       "attributes": {"id": "1689"}}}
        self.ha_client = make_ready_client(self.session, cache)
        self.ws = FakeWS()
        self.ha_client.ws_send = self.ws
        self.mcp = DummyMCP()
        automations_module.register(self.mcp, self.ha_client)
        scripts_module.register(self.mcp, self.ha_client)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def vista_previa(self, config: dict) -> dict:
        with aioresponses() as m:
            m.get(self.C["url"], status=404, body="no")
            return await self.mcp.tools[self.C["tool"]](self.C["id"], config)

    def sin_token(self, r: dict) -> None:
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(list(security.CONFIRMATIONS_DIR.iterdir()), [],
                         "quedó un fichero de token")

    # (a)
    async def test_parte_invalida(self) -> None:
        parte = self.C["parte_invalida"]
        self.ws.invalidas = {parte: f"Invalid value, password={CENTINELA}"}
        r = await self.vista_previa(self.C["valida"])
        self.assertEqual(r["error"], "invalid_config")
        self.assertEqual(list(r["parts"]), [parte])
        self.assertIn("hint", r)
        self.assertNotIn(CENTINELA, json.dumps(r))
        self.sin_token(r)

    # (b)
    async def test_todo_valido(self) -> None:
        r = await self.vista_previa(self.C["valida"])
        self.assertIn("confirmation_token", r)
        v = r["preview"]["validation"]
        self.assertEqual(v["validated"], self.C["partes"])
        self.assertEqual(v["not_validated"], ["alias", "mode"])
        self.assertIsNone(v["via_blueprint"])
        enviado = self.ws.de_tipo("validate_config")[0]
        self.assertEqual(sorted(k for k in enviado if k != "type"), self.C["partes"])

    # (c)
    async def test_use_blueprint(self) -> None:
        self.ws.sustituida = dict(self.C["valida"])
        config = {"alias": "Desde blueprint",
                  "use_blueprint": {"path": "homeassistant/motion_light.yaml",
                                    "input": {"motion_entity": "binary_sensor.x"}}}
        r = await self.vista_previa(config)
        self.assertIn("confirmation_token", r, r)
        sustitucion = self.ws.de_tipo("blueprint/substitute")
        self.assertEqual(sustitucion, [{
            "type": "blueprint/substitute", "domain": self.C["dominio"],
            "path": "homeassistant/motion_light.yaml",
            "input": {"motion_entity": "binary_sensor.x"},
        }])
        enviado = self.ws.de_tipo("validate_config")[0]
        self.assertEqual(sorted(k for k in enviado if k != "type"), self.C["partes"])
        self.assertNotIn("use_blueprint", enviado)
        v = r["preview"]["validation"]
        self.assertEqual(v["via_blueprint"], "homeassistant/motion_light.yaml")
        self.assertEqual(v["validated"], self.C["partes"])
        self.assertIn("alias", v["not_validated"])
        self.assertNotIn("use_blueprint", v["not_validated"])

    async def test_use_blueprint_invalido_tras_sustituir(self) -> None:
        self.ws.sustituida = dict(self.C["valida"])
        self.ws.invalidas = {self.C["parte_invalida"]: "bad"}
        r = await self.vista_previa(
            {"use_blueprint": {"path": "mio/luz.yaml", "input": {}}})
        self.assertEqual(r["error"], "invalid_config")
        self.assertEqual(r["via_blueprint"], "mio/luz.yaml")
        self.sin_token(r)

    async def test_use_blueprint_mal_formado(self) -> None:
        r = await self.vista_previa({"use_blueprint": {"input": {}}})
        self.assertEqual(r["error"], "invalid_argument")
        self.assertEqual(self.ws.enviados, [])
        self.sin_token(r)

    # (d)
    async def test_sustitucion_fallida(self) -> None:
        self.ws.error_sustitucion = HAConnectionError(
            f"HA WS command failed: Missing input motion_entity token={CENTINELA}",
            code="unknown_error")
        r = await self.vista_previa(
            {"use_blueprint": {"path": "homeassistant/motion_light.yaml", "input": {}}})
        self.assertEqual(r["error"], "blueprint_substitution_failed")
        self.assertEqual(r["blueprint"], "homeassistant/motion_light.yaml")
        self.assertNotIn(CENTINELA, json.dumps(r))
        self.assertEqual(self.ws.de_tipo("validate_config"), [])
        self.sin_token(r)

    # (e)
    async def test_validacion_no_disponible(self) -> None:
        self.ws.error_validacion = HAConnectionError("WebSocket no disponible")
        r = await self.vista_previa(self.C["valida"])
        self.assertEqual(r["error"], "validation_unavailable")
        self.assertIn("hint", r)
        self.sin_token(r)

    async def test_ha_sin_validate_config(self) -> None:
        # T057: un HA anterior al comando. El guardado real valida con las
        # mismas funciones: se da token, sin decir que se validó nada.
        self.ws.error_validacion = HAConnectionError(
            "HA WS command failed: Unknown command.", code="unknown_command")
        r = await self.vista_previa(self.C["valida"])
        self.assertIn("confirmation_token", r, r)
        v = r["preview"]["validation"]
        self.assertEqual((v["available"], v["reason"], v["validated"]),
                         (False, "unsupported_by_ha_version", []))
        self.assertEqual(v["not_validated"], sorted(self.C["valida"]))
        self.assertIn("note", v)

    async def test_ha_sin_blueprint_substitute(self) -> None:
        self.ws.error_sustitucion = HAConnectionError(
            "HA WS command failed: Unknown command.", code="unknown_command")
        config = {"alias": "Desde blueprint",
                  "use_blueprint": {"path": "homeassistant/motion_light.yaml",
                                    "input": {}}}
        r = await self.vista_previa(config)
        self.assertIn("confirmation_token", r, r)
        v = r["preview"]["validation"]
        self.assertEqual((v["available"], v["reason"], v["validated"]),
                         (False, "unsupported_by_ha_version", []))
        # Sin sustitución no se sabe qué añade el blueprint: solo las claves
        # dadas, también `use_blueprint`, y la nota lo dice.
        self.assertEqual(v["not_validated"], ["alias", "use_blueprint"])
        self.assertEqual(v["via_blueprint"], "homeassistant/motion_light.yaml")
        self.assertIn("substitution", v["note"])
        self.assertEqual(self.ws.de_tipo("validate_config"), [])

    async def test_validacion_disponible_lo_dice(self) -> None:
        r = await self.vista_previa(self.C["valida"])
        self.assertIs(r["preview"]["validation"]["available"], True)

    async def test_otros_codigos_siguen_sin_token(self) -> None:
        for codigo in ("unknown_error", "home_assistant_error", None):
            with self.subTest(codigo=codigo):
                self.ws.error_validacion = HAConnectionError("fallo", code=codigo)
                r = await self.vista_previa(self.C["valida"])
                self.assertEqual(r["error"], "validation_unavailable")
                self.sin_token(r)

    async def test_respuesta_que_no_es_objeto(self) -> None:
        self.ws.respuesta_validacion = ["no", "es", "un", "objeto"]
        r = await self.vista_previa(self.C["valida"])
        self.assertEqual(r["error"], "validation_unavailable")
        self.sin_token(r)

    async def test_parte_sin_resultado(self) -> None:
        self.ws.respuesta_validacion = {}
        r = await self.vista_previa(self.C["valida"])
        self.assertEqual(r["error"], "validation_unavailable")
        self.sin_token(r)

    # (f)
    async def test_sin_partes(self) -> None:
        r = await self.vista_previa({"alias": "Solo alias"})
        self.assertIn("confirmation_token", r)
        v = r["preview"]["validation"]
        self.assertEqual(v["validated"], [])
        self.assertEqual(v["not_validated"], ["alias"])
        self.assertIn("note", v)
        self.assertEqual(self.ws.enviados, [])

    # (h)
    async def test_confirmar_no_valida_y_guarda_lo_previsualizado(self) -> None:
        r = await self.vista_previa(self.C["valida"])
        token = r["confirmation_token"]
        self.ws.enviados.clear()
        # Aunque HA ahora diría que no, la confirmación no vuelve a validar.
        self.ws.error_validacion = HAConnectionError("no debería llamarse")
        with aioresponses() as m:
            m.post(self.C["url"], status=200, payload={"result": "ok"})
            res = await self.mcp.tools[self.C["tool"]](self.C["id"], confirmation_token=token)
            enviados_rest = [k for k in m.requests if k[0] == "POST"]
            cuerpo = m.requests[enviados_rest[0]][0].kwargs["json"]
        self.assertEqual(res, {"result": "ok"})
        self.assertEqual(self.ws.de_tipo("validate_config"), [])
        normalizada = self.C["modelo"].model_validate(self.C["valida"]).model_dump(
            exclude_none=True, by_alias=True, mode="json")
        self.assertEqual(cuerpo, normalizada)


class TestAutomatizacion(_Base, unittest.IsolatedAsyncioTestCase):
    C = _AUTOMATIZACION

    async def test_claves_antiguas_se_validan_por_su_parte(self) -> None:
        r = await self.vista_previa({"trigger": [{"trigger": "state", "entity_id": "x.y"}],
                                     "condition": [], "action": []})
        self.assertIn("confirmation_token", r)
        self.assertEqual(r["preview"]["validation"]["validated"],
                         ["actions", "conditions", "triggers"])


class TestScript(_Base, unittest.IsolatedAsyncioTestCase):
    C = _SCRIPT

    # (g)
    async def test_sequence_se_valida_como_actions(self) -> None:
        await self.vista_previa(self.C["valida"])
        enviado = self.ws.de_tipo("validate_config")[0]
        self.assertEqual(enviado["actions"], self.C["valida"]["sequence"])
        self.assertNotIn("sequence", enviado)


class TestSinFamiliasNuevas(unittest.IsolatedAsyncioTestCase):
    """(i) La validación no depende de las familias `blueprints`,
    `automation_assist` ni `core_diagnostics`: son funciones de módulo."""

    async def test_valida_con_las_familias_apagadas(self) -> None:
        from hermes.tools import register_all_tools

        original = security.CONFIRMATIONS_DIR
        tmp = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(tmp.name)
        session = ClientSession()
        try:
            ha = make_ready_client(session, {})
            ws = FakeWS()
            ws.invalidas = {"actions": "bad"}
            ha.ws_send = ws
            mcp = DummyMCP()
            register_all_tools(
                mcp, ha, fire_event_allowlist=[], response_max_bytes=131_072,
                safety_backup_window_minutes=30, safety_backup_enabled=False,
                file_backup_max_per_path=20, file_backup_max_total_mb=200,
                config_write_min_interval_seconds=5, config_write_max_per_minute=10,
                call_service_denylist_extra=[], call_service_restricted_entities=[],
                call_service_auto_classify=False, wait_for_event_max_seconds=90,
                wait_for_event_max_concurrent=5, safety_backup_keep=3,
                tool_families_disabled=["blueprints", "automation_assist",
                                        "core_diagnostics"],
            )
            self.assertNotIn("ha_validate_config", mcp.tools)
            with aioresponses() as m:
                m.get(_SCRIPT["url"], status=404, body="no")
                r = await mcp.tools["ha_create_or_update_script"](
                    "script.saludar", _SCRIPT["valida"])
            self.assertEqual(r["error"], "invalid_config")
            self.ws_tipos = [p["type"] for p in ws.enviados]
            self.assertEqual(self.ws_tipos, ["validate_config"])
        finally:
            await session.close()
            security.CONFIRMATIONS_DIR = original
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
