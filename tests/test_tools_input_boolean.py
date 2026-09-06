"""Tests de tools de input_boolean."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes import security
from hermes.models.input_boolean import InputBooleanConfig
import hermes.tools.input_boolean as mod

from tests._ha_fixture import REST_BASE, FakeCollectionStore, make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class TestToolsInputBoolean(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

        self.session = ClientSession()
        self.cache = {
            "input_boolean.presencia": {
                "entity_id": "input_boolean.presencia",
                "state": "on",
                "attributes": {
                    "friendly_name": "Presencia",
                    "icon": "mdi:account",
                },
            }
        }
        self.ha_client = make_ready_client(self.session, self.cache)
        self.store = FakeCollectionStore()
        self.store.install(self.ha_client)
        self.store.seed(
            "input_boolean", "presencia", {"name": "Presencia", "icon": "mdi:account"}
        )
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha_client)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def test_list(self) -> None:
        result = await self.mcp.tools["ha_list_input_booleans"]()
        parsed = json.loads(result)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["entity_id"], "input_boolean.presencia")

    async def test_get_ok(self) -> None:
        result = await self.mcp.tools["ha_get_input_boolean"](
            "input_boolean.presencia"
        )
        self.assertEqual(result["config"]["name"], "Presencia")
        self.assertEqual(result["state"]["entity_id"], "input_boolean.presencia")

    async def test_get_missing(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/input_boolean.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_get_input_boolean"](
                "input_boolean.fantasma"
            )
        self.assertIsNone(result["config"])
        self.assertIsNone(result["state"])

    async def test_update_preview(self) -> None:
        result = await self.mcp.tools["ha_create_or_update_input_boolean"](
            "input_boolean.presencia",
            {"name": "Nuevo", "icon": None},
        )
        self.assertIn("confirmation_token", result)
        self.assertEqual(result["preview"]["new"]["name"], "Nuevo")
        self.assertNotIn("icon", result["preview"]["new"])

    async def test_update_apply(self) -> None:
        new_config = {"name": "Presencia"}
        normalized = InputBooleanConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_input_boolean",
            {"entity_id": "input_boolean.presencia", "config": normalized},
        )
        token = token_response["confirmation_token"]

        result = await self.mcp.tools["ha_create_or_update_input_boolean"](
            "input_boolean.presencia",
            new_config,
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(
            self.store.get("input_boolean", "presencia")["name"], "Presencia"
        )

    async def test_delete_requires_token(self) -> None:
        result = await self.mcp.tools["ha_delete_input_boolean"](
            "input_boolean.presencia"
        )
        self.assertIn("confirmation_token", result)

    async def test_delete_apply(self) -> None:
        token_response = await security.create_confirmation_token(
            "ha_delete_input_boolean",
            {"entity_id": "input_boolean.presencia"},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_delete_input_boolean"](
            "input_boolean.presencia",
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertIsNone(self.store.get("input_boolean", "presencia"))

    async def test_set_on(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/input_boolean/turn_on",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_set_input_boolean"](
                "input_boolean.presencia", True
            )
        self.assertEqual(result, [])

    async def test_set_off(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/input_boolean/turn_off",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_set_input_boolean"](
                "input_boolean.presencia", False
            )
        self.assertEqual(result, [])

    async def test_toggle(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/input_boolean/toggle",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_toggle_input_boolean"](
                "input_boolean.presencia"
            )
        self.assertEqual(result, [])

    async def test_set_not_found(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/input_boolean.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_set_input_boolean"](
                "input_boolean.fantasma", True
            )
        self.assertEqual(
            result,
            {"error": "not_found", "entity_id": "input_boolean.fantasma"},
        )
