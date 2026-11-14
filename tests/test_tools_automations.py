"""Tests de tools de automations con transporte REST mockeado."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes import security
from hermes.models.automation import AutomationConfig
import hermes.tools.automations as automations_module

from tests._ha_fixture import REST_BASE, make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class TestToolsAutomations(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

        self.session = ClientSession()
        self.cache = {
            "automation.cocina": {
                "entity_id": "automation.cocina",
                "state": "on",
                "attributes": {
                    "id": "1689",
                    "friendly_name": "Cocina",
                    "last_triggered": None,
                },
            }
        }
        self.ha_client = make_ready_client(self.session, self.cache)
        self.mcp = DummyMCP()
        automations_module.register(self.mcp, self.ha_client)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    # ── list ────────────────────────────────────────────────

    async def test_list_automations(self) -> None:
        result = await self.mcp.tools["ha_list_automations"]()
        parsed = json.loads(result)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["entity_id"], "automation.cocina")

    # ── get ─────────────────────────────────────────────────

    async def test_get_automation_returns_config_and_state(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/automation/config/1689",
                status=200,
                payload={"id": "1689", "alias": "Cocina", "trigger": []},
            )
            result = await self.mcp.tools["ha_get_automation"]("automation.cocina")

        self.assertEqual(result["config"]["alias"], "Cocina")
        self.assertEqual(result["state"]["entity_id"], "automation.cocina")

    async def test_get_automation_missing_config(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/automation/config/1689",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_get_automation"]("automation.cocina")

        self.assertIsNone(result["config"])
        self.assertEqual(result["state"]["entity_id"], "automation.cocina")

    # ── update ──────────────────────────────────────────────

    async def test_update_automation_preview(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/automation/config/1689",
                status=200,
                payload={"id": "1689", "alias": "Cocina antigua"},
            )
            result = await self.mcp.tools["ha_create_or_update_automation"](
                "automation.cocina",
                {"alias": "Cocina nueva", "trigger": []},
            )

        self.assertIn("confirmation_token", result)
        self.assertEqual(result["preview"]["current"]["alias"], "Cocina antigua")
        self.assertEqual(result["preview"]["new"]["alias"], "Cocina nueva")

    async def test_update_automation_apply(self) -> None:
        new_config = {"alias": "Cocina nueva", "trigger": []}
        normalized = AutomationConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_automation",
            {"automation_id": "automation.cocina", "config": normalized},
        )
        token = token_response["confirmation_token"]

        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/config/automation/config/1689",
                status=200,
                payload={"result": "ok"},
            )
            result = await self.mcp.tools["ha_create_or_update_automation"](
                "automation.cocina",
                new_config,
                confirmation_token=token,
            )

        self.assertEqual(result, {"result": "ok"})

    async def test_update_automation_expired_token(self) -> None:
        new_config = {"alias": "c", "trigger": []}
        normalized = AutomationConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_automation",
            {"automation_id": "automation.cocina", "config": normalized},
        )
        token = token_response["confirmation_token"]

        token_file = security.CONFIRMATIONS_DIR / f"{token}.json"
        data = json.loads(token_file.read_text(encoding="utf-8"))
        data["expires_at"] = 0
        token_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        result = await self.mcp.tools["ha_create_or_update_automation"](
            "automation.cocina",
            new_config,
            confirmation_token=token,
        )
        self.assertIn("error", result)

    async def test_update_automation_save_server_error(self) -> None:
        new_config = {"alias": "Cocina", "trigger": []}
        normalized = AutomationConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_automation",
            {"automation_id": "automation.cocina", "config": normalized},
        )
        token = token_response["confirmation_token"]

        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/config/automation/config/1689",
                status=500,
                body="kaboom",
            )
            result = await self.mcp.tools["ha_create_or_update_automation"](
                "automation.cocina",
                new_config,
                confirmation_token=token,
            )
        self.assertIn("error", result)

    # ── delete ──────────────────────────────────────────────

    async def test_delete_automation_requires_token(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/automation/config/1689",
                status=200,
                payload={"alias": "Cocina"},
            )
            result = await self.mcp.tools["ha_delete_automation"]("automation.cocina")
        self.assertIn("confirmation_token", result)

    async def test_delete_automation_apply(self) -> None:
        token_response = await security.create_confirmation_token(
            "ha_delete_automation",
            {"automation_id": "automation.cocina"},
        )
        token = token_response["confirmation_token"]

        with aioresponses() as m:
            m.delete(
                f"{REST_BASE}/config/automation/config/1689",
                status=200,
                payload={"result": "ok"},
            )
            result = await self.mcp.tools["ha_delete_automation"](
                "automation.cocina",
                confirmation_token=token,
            )
        self.assertEqual(result, {"result": "ok"})

    async def test_delete_automation_not_found(self) -> None:
        token_response = await security.create_confirmation_token(
            "ha_delete_automation",
            {"automation_id": "automation.cocina"},
        )
        token = token_response["confirmation_token"]

        with aioresponses() as m:
            m.delete(
                f"{REST_BASE}/config/automation/config/1689",
                status=400,
                body="Resource not found",
            )
            result = await self.mcp.tools["ha_delete_automation"](
                "automation.cocina",
                confirmation_token=token,
            )
        self.assertEqual(result, {"result": "not_found"})

    # ── service wrappers ────────────────────────────────────

    async def test_enable_automation_calls_service(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/automation/turn_on",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_enable_automation"]("automation.cocina")
        self.assertEqual(result, [])

    # ── Bug 1: serialization ────────────────────────────────

    async def test_update_automation_body_has_no_nulls_and_modern_keys(self) -> None:
        new_config = {
            "alias": "Cocina",
            "description": None,
            "mode": None,
            "trigger": [{"platform": "state"}],
            "action": [{"service": "light.turn_on"}],
        }
        normalized = AutomationConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_automation",
            {"automation_id": "automation.cocina", "config": normalized},
        )
        token = token_response["confirmation_token"]

        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/config/automation/config/1689",
                status=200,
                payload={"result": "ok"},
            )
            await self.mcp.tools["ha_create_or_update_automation"](
                "automation.cocina",
                new_config,
                confirmation_token=token,
            )

            posted = None
            for (method, _url), calls in m.requests.items():
                if method.upper() == "POST":
                    posted = calls[0].kwargs.get("json")
                    break

        self.assertIsNotNone(posted)
        self.assertNotIn("description", posted)
        self.assertNotIn("mode", posted)
        self.assertNotIn("trigger", posted)
        self.assertNotIn("condition", posted)
        self.assertNotIn("action", posted)
        self.assertIn("triggers", posted)
        self.assertIn("actions", posted)
        for k, v in posted.items():
            self.assertIsNotNone(v, f"clave {k} no debería ser null")

    async def test_saving_a_dangerous_automation_restricts_its_real_entity_id(self) -> None:
        """Al guardar se registraba `automation.<id_numérico>`, mientras HA
        deriva la entidad del alias: la automatización quedaba sin restringir
        hasta el siguiente reinicio."""
        from hermes.tools.ha import _auto_restricted, get_auto_restricted_entities

        _auto_restricted.clear()
        new_config = {
            "alias": "Reiniciar Host",
            "trigger": [],
            "action": [{"service": "shell_command.rm_rf"}],
        }
        normalized = AutomationConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token = (await security.create_confirmation_token(
            "ha_create_or_update_automation",
            {"automation_id": "1712345678901", "config": normalized},
        ))["confirmation_token"]

        try:
            with aioresponses() as m:
                m.post(
                    f"{REST_BASE}/config/automation/config/1712345678901",
                    status=200,
                    payload={"result": "ok"},
                )
                result = await self.mcp.tools["ha_create_or_update_automation"](
                    "1712345678901", new_config, confirmation_token=token
                )
            self.assertEqual(result, {"result": "ok"})
            self.assertIn("automation.reiniciar_host", get_auto_restricted_entities())
        finally:
            _auto_restricted.clear()

    # ── Bug 3: existence check ─────────────────────────────

    async def test_trigger_automation_not_found(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/automation.no_existe",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_trigger_automation"]("automation.no_existe")
        self.assertEqual(
            result,
            {"error": "not_found", "entity_id": "automation.no_existe"},
        )

    async def test_reload_automations(self) -> None:
        """Recargar exige confirmación: `automation.reload` está en la denylist.

        Antes esta tool llamaba directa al cliente y ejecutaba el servicio sin
        token, pese a que la denylist lo veta expresamente ("Reloads que pueden
        activar YAML envenenado"). Era la ruta limpia para materializar un
        fs_write_file malicioso previo.
        """
        # 1. Sin token: preview + confirmation_token, y NADA se ejecuta.
        first = await self.mcp.tools["ha_reload_automations"]()
        payload = json.loads(first) if isinstance(first, str) else first
        self.assertIn("confirmation_token", payload)
        self.assertEqual(payload["preview"]["service"], "automation.reload")

        # 2. Con el token: se ejecuta.
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/automation/reload",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_reload_automations"](
                confirmation_token=payload["confirmation_token"]
            )
        self.assertEqual(result, [])


class TestConfirmarSinConfigAutomation(unittest.IsolatedAsyncioTestCase):
    """Confirmar `ha_create_or_update_automation` sin reenviar `config` (spec 007, Hermes 1.1.2).

    La vista previa guarda la configuración normalizada junto al token; la
    confirmación con solo `automation_id` y `confirmation_token` guarda
    exactamente esa. Control negativo comprobado: con `automations.py` de 1.1.1
    (`config` obligatorio y `validate_confirmation_token`) caen todos los de
    esta clase; con `resolve_confirmation_token` tomando lo guardado aunque se
    envíe otro `config`, cae el de config distinto.
    """

    asyncSetUp = TestToolsAutomations.asyncSetUp
    asyncTearDown = TestToolsAutomations.asyncTearDown

    URL = f"{REST_BASE}/config/automation/config/1689"
    NUEVA = {'alias': 'Ficticia nueva', 'trigger': []}
    OTRA = {'alias': 'Ficticia distinta', 'trigger': []}

    async def _vista_previa(self) -> dict:
        with aioresponses() as m:
            m.get(self.URL, status=200, payload={'id': '1689', 'alias': 'Ficticia antigua'})
            return await self.mcp.tools["ha_create_or_update_automation"]("automation.cocina", self.NUEVA)

    async def _confirmar(self, token: str, **extra) -> tuple[object, list]:
        with aioresponses() as m:
            m.post(self.URL, status=200, payload={"result": "ok"})
            res = await self.mcp.tools["ha_create_or_update_automation"](
                "automation.cocina", confirmation_token=token, **extra)
            enviados = [
                c.kwargs.get("json")
                for (metodo, _url), llamadas in m.requests.items()
                if metodo.upper() == "POST"
                for c in llamadas
            ]
        return res, enviados

    async def test_confirmar_sin_config_guarda_la_de_la_vista_previa(self) -> None:
        r = await self._vista_previa()
        self.assertEqual(r["omit_on_confirm"], ["config"])
        self.assertEqual(r["confirm_with"], ["automation_id", "confirmation_token"])
        self.assertIn("automation_id", r["confirm_hint"])
        res, enviados = await self._confirmar(r["confirmation_token"])
        self.assertEqual(res, {"result": "ok"})
        normalizada = AutomationConfig.model_validate(self.NUEVA).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        self.assertEqual(enviados, [normalizada])

    async def test_sin_token_y_sin_config_es_invalid_argument(self) -> None:
        with aioresponses() as m:
            res = await self.mcp.tools["ha_create_or_update_automation"]("automation.cocina")
            self.assertEqual(dict(m.requests), {})
        self.assertEqual(res["error"], "invalid_argument")
        self.assertEqual(res["field"], "config")
        self.assertNotIn("confirmation_token", res)
        self.assertEqual(list(security.CONFIRMATIONS_DIR.glob("*.json")), [])

    async def test_config_distinto_al_confirmar_no_vale(self) -> None:
        r = await self._vista_previa()
        res, enviados = await self._confirmar(r["confirmation_token"], config=self.OTRA)
        self.assertEqual(res, {"error": "confirmation_token does not match this action."})
        self.assertEqual(enviados, [])
        # El token no se ha gastado: la confirmación correcta sigue sirviendo.
        res, enviados = await self._confirmar(r["confirmation_token"])
        self.assertEqual(res, {"result": "ok"})
        self.assertEqual(len(enviados), 1)

    async def test_token_de_otra_tool_no_vale(self) -> None:
        """SC-002: un token de ha_save_lovelace_dashboard con los mismos
        argumentos no ejecuta una automatización."""
        normalizada = AutomationConfig.model_validate(self.NUEVA).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        args = {"automation_id": "automation.cocina", "config": normalizada}
        r = await security.create_confirmation_token(
            "ha_save_lovelace_dashboard", args, omitibles=("config",))
        res, enviados = await self._confirmar(r["confirmation_token"])
        self.assertEqual(res, {"error": "confirmation_token does not match this action."})
        self.assertEqual(enviados, [])
        ok, error, _ = await security.resolve_confirmation_token(
            r["confirmation_token"], "ha_save_lovelace_dashboard",
            {"automation_id": "automation.cocina"}, omitibles=("config",))
        self.assertTrue(ok, error)
