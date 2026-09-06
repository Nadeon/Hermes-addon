"""Tests de tools de input_select."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes import security
from hermes.models.input_select import InputSelectConfig
import hermes.tools.input_select as mod

from tests._ha_fixture import REST_BASE, FakeCollectionStore, make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class TestToolsInputSelect(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

        self.session = ClientSession()
        self.cache = {
            "input_select.modo": {
                "entity_id": "input_select.modo",
                "state": "dia",
                "attributes": {
                    "friendly_name": "Modo casa",
                    "options": ["dia", "noche", "fuera"],
                },
            }
        }
        self.ha_client = make_ready_client(self.session, self.cache)
        self.store = FakeCollectionStore()
        self.store.install(self.ha_client)
        self.store.seed(
            "input_select",
            "modo",
            {"name": "Modo", "options": ["dia", "noche"]},
        )
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha_client)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def test_list(self) -> None:
        result = await self.mcp.tools["ha_list_input_selects"]()
        parsed = json.loads(result)
        self.assertEqual(parsed[0]["entity_id"], "input_select.modo")
        self.assertEqual(parsed[0]["options"], ["dia", "noche", "fuera"])

    async def test_get_ok(self) -> None:
        result = await self.mcp.tools["ha_get_input_select"](
            "input_select.modo"
        )
        self.assertEqual(result["config"]["options"], ["dia", "noche"])

    async def test_update_apply(self) -> None:
        new_config = {"name": "Modo", "options": ["a", "b"]}
        normalized = InputSelectConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_input_select",
            {"entity_id": "input_select.modo", "config": normalized},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_create_or_update_input_select"](
            "input_select.modo",
            new_config,
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(
            self.store.get("input_select", "modo")["options"], ["a", "b"]
        )

    async def test_delete_apply(self) -> None:
        token_response = await security.create_confirmation_token(
            "ha_delete_input_select",
            {"entity_id": "input_select.modo"},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_delete_input_select"](
            "input_select.modo",
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertIsNone(self.store.get("input_select", "modo"))

    async def test_set_option(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/input_select/select_option",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_set_input_select"](
                "input_select.modo", "noche"
            )
        self.assertEqual(result, [])

    async def test_cycle_next(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/input_select/select_next",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_cycle_input_select"](
                "input_select.modo", direction="next"
            )
        self.assertEqual(result, [])

    async def test_cycle_previous(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/input_select/select_previous",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_cycle_input_select"](
                "input_select.modo", direction="previous"
            )
        self.assertEqual(result, [])

    async def test_cycle_invalid_direction(self) -> None:
        result = await self.mcp.tools["ha_cycle_input_select"](
            "input_select.modo", direction="sideways"
        )
        self.assertIn("error", result)

    async def test_set_options(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/input_select/set_options",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_set_input_select_options"](
                "input_select.modo", ["x", "y", "z"]
            )
        self.assertEqual(result, [])

    async def test_set_not_found(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/input_select.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_set_input_select"](
                "input_select.fantasma", "x"
            )
        self.assertEqual(
            result,
            {"error": "not_found", "entity_id": "input_select.fantasma"},
        )
