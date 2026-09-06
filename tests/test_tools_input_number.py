"""Tests de tools de input_number."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes import security
from hermes.models.input_number import InputNumberConfig
import hermes.tools.input_number as mod

from tests._ha_fixture import REST_BASE, FakeCollectionStore, make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class TestToolsInputNumber(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

        self.session = ClientSession()
        self.cache = {
            "input_number.temperatura": {
                "entity_id": "input_number.temperatura",
                "state": "21.5",
                "attributes": {
                    "friendly_name": "Temperatura",
                    "min": 15.0,
                    "max": 30.0,
                    "step": 0.5,
                    "unit_of_measurement": "°C",
                },
            }
        }
        self.ha_client = make_ready_client(self.session, self.cache)
        self.store = FakeCollectionStore()
        self.store.install(self.ha_client)
        self.store.seed(
            "input_number",
            "temperatura",
            {"name": "Temperatura", "min": 15.0, "max": 30.0},
        )
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha_client)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def test_list(self) -> None:
        result = await self.mcp.tools["ha_list_input_numbers"]()
        parsed = json.loads(result)
        self.assertEqual(parsed[0]["entity_id"], "input_number.temperatura")
        self.assertEqual(parsed[0]["min"], 15.0)

    async def test_get_ok(self) -> None:
        result = await self.mcp.tools["ha_get_input_number"](
            "input_number.temperatura"
        )
        self.assertEqual(result["config"]["min"], 15.0)

    async def test_update_apply_no_nulls(self) -> None:
        new_config = {
            "name": "Temp",
            "min": 10.0,
            "max": 35.0,
            "step": None,
            "mode": None,
            "unit_of_measurement": "°C",
        }
        normalized = InputNumberConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_input_number",
            {"entity_id": "input_number.temperatura", "config": normalized},
        )
        token = token_response["confirmation_token"]

        result = await self.mcp.tools["ha_create_or_update_input_number"](
            "input_number.temperatura",
            new_config,
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        stored = self.store.get("input_number", "temperatura")
        self.assertIsNotNone(stored)
        # Los campos None no deben existir en el estado final
        # (la seed inicial no los tenía y el update no los añadió).
        self.assertNotIn("step", stored)
        self.assertNotIn("mode", stored)
        self.assertEqual(stored["name"], "Temp")
        self.assertEqual(stored["min"], 10.0)

    async def test_delete_apply(self) -> None:
        token_response = await security.create_confirmation_token(
            "ha_delete_input_number",
            {"entity_id": "input_number.temperatura"},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_delete_input_number"](
            "input_number.temperatura",
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertIsNone(self.store.get("input_number", "temperatura"))

    async def test_set_value(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/input_number/set_value",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_set_input_number"](
                "input_number.temperatura", 22.5
            )
        self.assertEqual(result, [])

    async def test_increment(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/input_number/increment",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_increment_input_number"](
                "input_number.temperatura"
            )
        self.assertEqual(result, [])

    async def test_decrement(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/input_number/decrement",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_decrement_input_number"](
                "input_number.temperatura"
            )
        self.assertEqual(result, [])

    async def test_set_not_found(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/input_number.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_set_input_number"](
                "input_number.fantasma", 1.0
            )
        self.assertEqual(
            result,
            {"error": "not_found", "entity_id": "input_number.fantasma"},
        )
