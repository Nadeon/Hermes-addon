"""Tests de tools de scripts con transporte REST mockeado."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes import security
from hermes.models.script import ScriptConfig
import hermes.tools.scripts as scripts_module

from tests._ha_fixture import REST_BASE, make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class TestToolsScripts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

        self.session = ClientSession()
        self.cache = {
            "script.saludar": {
                "entity_id": "script.saludar",
                "state": "off",
                "attributes": {
                    "friendly_name": "Saludar",
                    "last_triggered": "2026-04-12T12:00:00+00:00",
                    "mode": "single",
                },
            }
        }
        self.ha_client = make_ready_client(self.session, self.cache)
        self.mcp = DummyMCP()
        scripts_module.register(self.mcp, self.ha_client)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    # ── list ────────────────────────────────────────────────

    async def test_list_scripts(self) -> None:
        result = await self.mcp.tools["ha_list_scripts"]()
        parsed = json.loads(result)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["entity_id"], "script.saludar")
        self.assertEqual(parsed[0]["alias"], "Saludar")

    # ── get ─────────────────────────────────────────────────

    async def test_get_script_returns_config_and_state(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/script/config/saludar",
                status=200,
                payload={"alias": "Saludar", "sequence": []},
            )
            result = await self.mcp.tools["ha_get_script"]("script.saludar")
        self.assertEqual(result["config"]["alias"], "Saludar")
        self.assertEqual(result["state"]["entity_id"], "script.saludar")

    async def test_get_script_missing_config(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/script/config/saludar",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_get_script"]("script.saludar")
        self.assertIsNone(result["config"])
        self.assertEqual(result["state"]["entity_id"], "script.saludar")

    # ── update ──────────────────────────────────────────────

    async def test_update_script_preview(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/script/config/saludar",
                status=200,
                payload={"alias": "Viejo", "sequence": []},
            )
            result = await self.mcp.tools["ha_create_or_update_script"](
                "script.saludar",
                {"alias": "Nuevo", "sequence": [{"service": "test"}]},
            )

        self.assertIn("confirmation_token", result)
        self.assertEqual(result["preview"]["current"]["alias"], "Viejo")
        self.assertEqual(result["preview"]["new"]["alias"], "Nuevo")

    async def test_update_script_apply(self) -> None:
        new_config = {"alias": "Nuevo", "sequence": [{"service": "test"}]}
        normalized = ScriptConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_script",
            {"script_id": "script.saludar", "config": normalized},
        )
        token = token_response["confirmation_token"]

        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/config/script/config/saludar",
                status=200,
                payload={"result": "ok"},
            )
            result = await self.mcp.tools["ha_create_or_update_script"](
                "script.saludar",
                new_config,
                confirmation_token=token,
            )
        self.assertEqual(result, {"result": "ok"})

    async def test_update_script_expired_token(self) -> None:
        new_config = {"alias": "N", "sequence": [{"service": "test"}]}
        normalized = ScriptConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_script",
            {"script_id": "script.saludar", "config": normalized},
        )
        token = token_response["confirmation_token"]

        token_file = security.CONFIRMATIONS_DIR / f"{token}.json"
        data = json.loads(token_file.read_text(encoding="utf-8"))
        data["expires_at"] = 0
        token_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        result = await self.mcp.tools["ha_create_or_update_script"](
            "script.saludar",
            new_config,
            confirmation_token=token,
        )
        self.assertIn("error", result)

    async def test_update_script_server_error(self) -> None:
        new_config = {"alias": "N", "sequence": [{"service": "test"}]}
        normalized = ScriptConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_script",
            {"script_id": "script.saludar", "config": normalized},
        )
        token = token_response["confirmation_token"]

        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/config/script/config/saludar",
                status=500,
                body="kaboom",
            )
            result = await self.mcp.tools["ha_create_or_update_script"](
                "script.saludar",
                new_config,
                confirmation_token=token,
            )
        self.assertIn("error", result)

    # ── delete ──────────────────────────────────────────────

    async def test_delete_script_requires_token(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/script/config/saludar",
                status=200,
                payload={"alias": "Saludar"},
            )
            result = await self.mcp.tools["ha_delete_script"]("script.saludar")
        self.assertIn("confirmation_token", result)

    async def test_delete_script_apply(self) -> None:
        token_response = await security.create_confirmation_token(
            "ha_delete_script",
            {"script_id": "script.saludar"},
        )
        token = token_response["confirmation_token"]

        with aioresponses() as m:
            m.delete(
                f"{REST_BASE}/config/script/config/saludar",
                status=200,
                payload={"result": "ok"},
            )
            result = await self.mcp.tools["ha_delete_script"](
                "script.saludar",
                confirmation_token=token,
            )
        self.assertEqual(result, {"result": "ok"})

    async def test_delete_script_not_found(self) -> None:
        token_response = await security.create_confirmation_token(
            "ha_delete_script",
            {"script_id": "script.saludar"},
        )
        token = token_response["confirmation_token"]

        with aioresponses() as m:
            m.delete(
                f"{REST_BASE}/config/script/config/saludar",
                status=400,
                body="Resource not found",
            )
            result = await self.mcp.tools["ha_delete_script"](
                "script.saludar",
                confirmation_token=token,
            )
        self.assertEqual(result, {"result": "not_found"})

    # ── service wrappers ────────────────────────────────────

    async def test_run_script_executes_service(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/script/turn_on",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_run_script"](
                "script.saludar",
                variables={"greeting": "hola"},
            )
        self.assertEqual(result, [])

    # ── Bug 1: serialization ────────────────────────────────

    async def test_update_script_body_has_no_nulls(self) -> None:
        new_config = {
            "alias": "Saludar",
            "description": None,
            "icon": None,
            "mode": None,
            "max": None,
            "variables": None,
            "trace": None,
            "sequence": [{"service": "light.turn_on"}],
        }
        normalized = ScriptConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_script",
            {"script_id": "script.saludar", "config": normalized},
        )
        token = token_response["confirmation_token"]

        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/config/script/config/saludar",
                status=200,
                payload={"result": "ok"},
            )
            await self.mcp.tools["ha_create_or_update_script"](
                "script.saludar",
                new_config,
                confirmation_token=token,
            )
            posted = None
            for (method, _url), calls in m.requests.items():
                if method.upper() == "POST":
                    posted = calls[0].kwargs.get("json")
                    break

        self.assertIsNotNone(posted)
        for k in ("description", "icon", "mode", "max", "variables", "trace"):
            self.assertNotIn(k, posted)
        for k, v in posted.items():
            self.assertIsNotNone(v, f"clave {k} no debería ser null")

    # ── Bug 2: get_script missing both config and state ─────

    async def test_get_script_missing_everything(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/script/config/fantasma",
                status=404,
                body="nope",
            )
            m.get(
                f"{REST_BASE}/states/script.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_get_script"]("script.fantasma")
        self.assertIsInstance(result, dict)
        self.assertIsNone(result.get("config"))
        self.assertIsNone(result.get("state"))
        self.assertNotIn("error", result)

    # ── Bug 3: existence check ─────────────────────────────

    async def test_run_script_not_found(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/script.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_run_script"]("script.fantasma")
        self.assertEqual(
            result,
            {"error": "not_found", "entity_id": "script.fantasma"},
        )

    async def test_run_script_con_ha_caido_no_dice_not_found(self) -> None:
        """Una caída de HA no puede disfrazarse de "el script no existe".

        `entity_exists` se tragaba cualquier HAConnectionError y devolvía
        False: durante un corte, `ha_run_script` contestaba `not_found` y el
        cliente daba por borrado un script que sigue ahí.
        """
        from hermes.ha import HAConnectionError

        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/script.saludar_otro",
                status=503,
                body="service unavailable",
            )
            with self.assertRaises(HAConnectionError):
                await self.mcp.tools["ha_run_script"]("script.saludar_otro")

    async def test_reload_scripts(self) -> None:
        """Recargar exige confirmación: `script.reload` está en la denylist.

        Antes esta tool llamaba directa al cliente y ejecutaba el servicio sin
        token, pese a que la denylist lo veta expresamente ("Reloads que pueden
        activar YAML envenenado"). Era la ruta limpia para materializar un
        fs_write_file malicioso previo.
        """
        # 1. Sin token: preview + confirmation_token, y NADA se ejecuta.
        first = await self.mcp.tools["ha_reload_scripts"]()
        payload = json.loads(first) if isinstance(first, str) else first
        self.assertIn("confirmation_token", payload)
        self.assertEqual(payload["preview"]["service"], "script.reload")

        # 2. Con el token: se ejecuta.
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/script/reload",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_reload_scripts"](
                confirmation_token=payload["confirmation_token"]
            )
        self.assertEqual(result, [])

    # ── R5: `trace` es un diccionario (FR-032) ──────────────

    async def test_update_script_accepts_trace_dict(self) -> None:
        """HA define `trace` como diccionario (`stored_traces`); el modelo lo
        declaraba como lista y rechazaba cualquier script con trazas
        configuradas. Debe pasar la validación y llegar intacto a HA."""
        new_config = {
            "sequence": [{"action": "light.turn_on"}],
            "trace": {"stored_traces": 20},
        }
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/script/config/saludar",
                status=200,
                payload={"alias": "Viejo", "sequence": []},
            )
            preview = await self.mcp.tools["ha_create_or_update_script"](
                "script.saludar", new_config
            )
        self.assertIn("confirmation_token", preview, preview)
        self.assertEqual(preview["preview"]["new"]["trace"], {"stored_traces": 20})

        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/config/script/config/saludar",
                status=200,
                payload={"result": "ok"},
            )
            result = await self.mcp.tools["ha_create_or_update_script"](
                "script.saludar",
                new_config,
                confirmation_token=preview["confirmation_token"],
            )
            posted = None
            for (method, _url), calls in m.requests.items():
                if method.upper() == "POST":
                    posted = calls[0].kwargs.get("json")
                    break
        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(posted["trace"], {"stored_traces": 20})

    async def test_update_script_rejects_trace_list(self) -> None:
        result = await self.mcp.tools["ha_create_or_update_script"](
            "script.saludar",
            {"sequence": [], "trace": [{"stored_traces": 20}]},
        )
        self.assertIn("error", result)
        self.assertIn("config validation", result["error"])
        self.assertNotIn("confirmation_token", result)


class TestConfirmarSinConfigScript(unittest.IsolatedAsyncioTestCase):
    """Confirmar `ha_create_or_update_script` sin reenviar `config` (spec 007, Hermes 1.1.2).

    La vista previa guarda la configuración normalizada junto al token; la
    confirmación con solo `script_id` y `confirmation_token` guarda
    exactamente esa. Control negativo comprobado: con `scripts.py` de 1.1.1
    (`config` obligatorio y `validate_confirmation_token`) caen todos los de
    esta clase; con `resolve_confirmation_token` tomando lo guardado aunque se
    envíe otro `config`, cae el de config distinto.
    """

    asyncSetUp = TestToolsScripts.asyncSetUp
    asyncTearDown = TestToolsScripts.asyncTearDown

    URL = f"{REST_BASE}/config/script/config/saludar"
    NUEVA = {'alias': 'Ficticio nuevo', 'sequence': [{'service': 'test'}]}
    OTRA = {'alias': 'Ficticio distinto', 'sequence': [{'service': 'test'}]}

    async def _vista_previa(self) -> dict:
        with aioresponses() as m:
            m.get(self.URL, status=200, payload={'alias': 'Ficticio antiguo'})
            return await self.mcp.tools["ha_create_or_update_script"]("script.saludar", self.NUEVA)

    async def _confirmar(self, token: str, **extra) -> tuple[object, list]:
        with aioresponses() as m:
            m.post(self.URL, status=200, payload={"result": "ok"})
            res = await self.mcp.tools["ha_create_or_update_script"](
                "script.saludar", confirmation_token=token, **extra)
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
        self.assertEqual(r["confirm_with"], ["confirmation_token", "script_id"])
        self.assertIn("script_id", r["confirm_hint"])
        res, enviados = await self._confirmar(r["confirmation_token"])
        self.assertEqual(res, {"result": "ok"})
        normalizada = ScriptConfig.model_validate(self.NUEVA).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        self.assertEqual(enviados, [normalizada])

    async def test_sin_token_y_sin_config_es_invalid_argument(self) -> None:
        with aioresponses() as m:
            res = await self.mcp.tools["ha_create_or_update_script"]("script.saludar")
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
