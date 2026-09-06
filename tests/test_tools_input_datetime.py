"""Tests de tools de input_datetime."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes import security
from hermes.models.input_datetime import InputDatetimeConfig
import hermes.tools.input_datetime as mod

from tests._ha_fixture import REST_BASE, FakeCollectionStore, make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class TestToolsInputDatetime(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

        self.session = ClientSession()
        self.cache = {
            "input_datetime.despertador": {
                "entity_id": "input_datetime.despertador",
                "state": "07:30:00",
                "attributes": {
                    "friendly_name": "Despertador",
                    "has_date": False,
                    "has_time": True,
                },
            }
        }
        self.ha_client = make_ready_client(self.session, self.cache)
        self.store = FakeCollectionStore()
        self.store.install(self.ha_client)
        self.store.seed(
            "input_datetime",
            "despertador",
            {"name": "Despertador", "has_date": False, "has_time": True},
        )
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha_client)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def test_list(self) -> None:
        result = await self.mcp.tools["ha_list_input_datetimes"]()
        parsed = json.loads(result)
        self.assertEqual(parsed[0]["entity_id"], "input_datetime.despertador")

    async def test_get_ok(self) -> None:
        result = await self.mcp.tools["ha_get_input_datetime"](
            "input_datetime.despertador"
        )
        self.assertEqual(result["config"]["name"], "Despertador")

    async def test_update_apply(self) -> None:
        new_config = {"name": "Despertador", "has_date": False, "has_time": True}
        normalized = InputDatetimeConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_input_datetime",
            {"entity_id": "input_datetime.despertador", "config": normalized},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_create_or_update_input_datetime"](
            "input_datetime.despertador",
            new_config,
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(
            self.store.get("input_datetime", "despertador")["name"],
            "Despertador",
        )

    async def test_delete_apply(self) -> None:
        token_response = await security.create_confirmation_token(
            "ha_delete_input_datetime",
            {"entity_id": "input_datetime.despertador"},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_delete_input_datetime"](
            "input_datetime.despertador",
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertIsNone(self.store.get("input_datetime", "despertador"))

    async def test_set_time(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/input_datetime/set_datetime",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_set_input_datetime"](
                "input_datetime.despertador", time="08:00:00"
            )
        self.assertEqual(result, [])

    async def test_set_datetime_full(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/input_datetime/set_datetime",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_set_input_datetime"](
                "input_datetime.despertador", datetime="2026-04-12 08:00:00"
            )
        self.assertEqual(result, [])

    async def test_set_not_found(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/input_datetime.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_set_input_datetime"](
                "input_datetime.fantasma", time="08:00:00"
            )
        self.assertEqual(
            result,
            {"error": "not_found", "entity_id": "input_datetime.fantasma"},
        )
