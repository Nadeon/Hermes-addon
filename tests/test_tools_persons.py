"""Tests de tools de person."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes import security
from hermes.models.person import PersonConfig
import hermes.tools.persons as mod

from tests._ha_fixture import REST_BASE, FakeCollectionStore, make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class TestToolsPersons(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

        self.session = ClientSession()
        self.cache = {
            "person.ana": {
                "entity_id": "person.ana",
                "state": "home",
                "attributes": {"friendly_name": "Ana"},
            },
            "device_tracker.ana_phone": {
                "entity_id": "device_tracker.ana_phone",
                "state": "home",
                "attributes": {},
            },
            "device_tracker.ana_watch": {
                "entity_id": "device_tracker.ana_watch",
                "state": "home",
                "attributes": {},
            },
        }
        self.ha_client = make_ready_client(self.session, self.cache)
        self.store = FakeCollectionStore()
        self.store.install(self.ha_client)
        self.store.seed(
            "person",
            "ana",
            {
                "name": "Ana",
                "device_trackers": ["device_tracker.ana_phone"],
            },
        )
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha_client)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def test_list(self) -> None:
        result = await self.mcp.tools["ha_list_persons"]()
        parsed = json.loads(result)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["name"], "Ana")

    async def test_get_ok(self) -> None:
        result = await self.mcp.tools["ha_get_person"]("person.ana")
        self.assertEqual(result["config"]["name"], "Ana")
        self.assertEqual(result["state"]["state"], "home")

    async def test_create_ok(self) -> None:
        result = await self.mcp.tools["ha_create_person"](
            name="Bea",
            device_trackers=["device_tracker.ana_phone"],
        )
        self.assertEqual(result["result"], "ok")
        self.assertEqual(result["entity_id"], "person.bea")
        self.assertIsNotNone(self.store.get("person", "bea"))

    async def test_create_unknown_tracker(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/device_tracker.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_create_person"](
                name="Carlos",
                device_trackers=["device_tracker.fantasma"],
            )
        self.assertEqual(result["error"], "unknown_device_trackers")
        self.assertEqual(result["missing"], ["device_tracker.fantasma"])
        self.assertIsNone(self.store.get("person", "carlos"))

    async def test_update_preview(self) -> None:
        result = await self.mcp.tools["ha_update_person"](
            "person.ana",
            {"name": "Ana", "picture": "/local/ana.png"},
        )
        self.assertIn("confirmation_token", result)
        self.assertEqual(result["preview"]["new"]["picture"], "/local/ana.png")

    async def test_update_apply(self) -> None:
        new_config = {
            "name": "Ana",
            "device_trackers": [
                "device_tracker.ana_phone",
                "device_tracker.ana_watch",
            ],
        }
        normalized = PersonConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_update_person",
            {"entity_id": "person.ana", "config": normalized},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_update_person"](
            "person.ana",
            new_config,
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(
            self.store.get("person", "ana")["device_trackers"],
            ["device_tracker.ana_phone", "device_tracker.ana_watch"],
        )

    async def test_update_unknown_tracker(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/device_tracker.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_update_person"](
                "person.ana",
                {"name": "Ana", "device_trackers": ["device_tracker.fantasma"]},
            )
        self.assertEqual(result["error"], "unknown_device_trackers")

    async def test_delete_requires_token(self) -> None:
        result = await self.mcp.tools["ha_delete_person"]("person.ana")
        self.assertIn("confirmation_token", result)

    async def test_delete_apply(self) -> None:
        token_response = await security.create_confirmation_token(
            "ha_delete_person",
            {"entity_id": "person.ana"},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_delete_person"](
            "person.ana",
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertIsNone(self.store.get("person", "ana"))
