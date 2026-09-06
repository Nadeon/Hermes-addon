"""Tests de tools de input_button."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes import security
from hermes.models.input_button import InputButtonConfig
import hermes.tools.input_button as mod

from tests._ha_fixture import REST_BASE, FakeCollectionStore, make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class TestToolsInputButton(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

        self.session = ClientSession()
        self.cache = {
            "input_button.reinicio": {
                "entity_id": "input_button.reinicio",
                "state": "unknown",
                "attributes": {
                    "friendly_name": "Reinicio",
                    "icon": "mdi:restart",
                },
            }
        }
        self.ha_client = make_ready_client(self.session, self.cache)
        self.store = FakeCollectionStore()
        self.store.install(self.ha_client)
        self.store.seed(
            "input_button",
            "reinicio",
            {"name": "Reinicio", "icon": "mdi:restart"},
        )
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha_client)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def test_list(self) -> None:
        result = await self.mcp.tools["ha_list_input_buttons"]()
        parsed = json.loads(result)
        self.assertEqual(parsed[0]["entity_id"], "input_button.reinicio")

    async def test_get_ok(self) -> None:
        result = await self.mcp.tools["ha_get_input_button"](
            "input_button.reinicio"
        )
        self.assertEqual(result["config"]["name"], "Reinicio")

    async def test_update_apply(self) -> None:
        new_config = {"name": "Reinicio", "icon": "mdi:restart"}
        normalized = InputButtonConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_input_button",
            {"entity_id": "input_button.reinicio", "config": normalized},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_create_or_update_input_button"](
            "input_button.reinicio",
            new_config,
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(
            self.store.get("input_button", "reinicio")["name"], "Reinicio"
        )

    async def test_delete_apply(self) -> None:
        token_response = await security.create_confirmation_token(
            "ha_delete_input_button",
            {"entity_id": "input_button.reinicio"},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_delete_input_button"](
            "input_button.reinicio",
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertIsNone(self.store.get("input_button", "reinicio"))

    async def test_press(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/input_button/press",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_press_input_button"](
                "input_button.reinicio"
            )
        self.assertEqual(result, [])

    async def test_press_not_found(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/input_button.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_press_input_button"](
                "input_button.fantasma"
            )
        self.assertEqual(
            result,
            {"error": "not_found", "entity_id": "input_button.fantasma"},
        )
