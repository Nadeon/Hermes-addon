"""Tests para tools de entity registry con fake WS."""

from __future__ import annotations

import json
import unittest

from aiohttp import ClientSession

import hermes.tools.registry_entity as entity_mod
from tests._ha_fixture import make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_entity_entries(n: int) -> list[dict]:
    return [
        {
            "entity_id": f"sensor.temp_{i}",
            "platform": "mqtt",
            "device_id": f"device_{i % 3}",
            "area_id": "salon" if i % 2 == 0 else None,
            "name": None,
            "original_name": f"Temperature {i}",
            "icon": None,
            "disabled_by": None,
            "hidden_by": None,
            "unique_id": f"unique_{i}",
            "aliases": [],
            "labels": [],
        }
        for i in range(n)
    ]


# ── Tests ha_list_entities_registry ─────────────────────────────────────────

class TestListEntitiesRegistry(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def _make_client(self, ws_result):
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return ws_result
        client.ws_send = fake_ws  # type: ignore[method-assign]
        return client

    async def test_basic_list(self) -> None:
        entries = _make_entity_entries(5)
        client = self._make_client(entries)
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_entities_registry"]()
        result = json.loads(raw)
        self.assertEqual(result["count"], 5)
        self.assertEqual(len(result["entities"]), 5)
        self.assertFalse(result["truncated"])

    async def test_filter_area_id(self) -> None:
        entries = _make_entity_entries(6)
        client = self._make_client(entries)
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_entities_registry"](area_id="salon")
        result = json.loads(raw)
        # Even indices → area_id=salon: 0,2,4 → 3 entries
        self.assertEqual(result["count"], 3)
        for e in result["entities"]:
            self.assertEqual(e["area_id"], "salon")

    async def test_filter_area_id_none(self) -> None:
        entries = _make_entity_entries(4)
        client = self._make_client(entries)
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_entities_registry"](area_id=None)
        result = json.loads(raw)
        # No filter applied when area_id param is None
        self.assertEqual(result["count"], 4)

    async def test_filter_platform(self) -> None:
        entries = _make_entity_entries(4)
        entries[0]["platform"] = "zha"
        client = self._make_client(entries)
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_entities_registry"](platform="zha")
        result = json.loads(raw)
        self.assertEqual(result["count"], 1)

    async def test_filter_device_id(self) -> None:
        entries = _make_entity_entries(6)
        client = self._make_client(entries)
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_entities_registry"](device_id="device_0")
        result = json.loads(raw)
        # device_0 at i=0,3 → 2 entries
        self.assertEqual(result["count"], 2)

    async def test_filter_disabled_true(self) -> None:
        entries = _make_entity_entries(4)
        entries[1]["disabled_by"] = "user"
        entries[3]["disabled_by"] = "integration"
        client = self._make_client(entries)
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_entities_registry"](disabled=True)
        result = json.loads(raw)
        self.assertEqual(result["count"], 2)

    async def test_filter_disabled_false(self) -> None:
        entries = _make_entity_entries(4)
        entries[1]["disabled_by"] = "user"
        client = self._make_client(entries)
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_entities_registry"](disabled=False)
        result = json.loads(raw)
        self.assertEqual(result["count"], 3)

    async def test_truncation_by_bytes(self) -> None:
        entries = _make_entity_entries(100)
        client = self._make_client(entries)
        mcp = DummyMCP()
        entity_mod.register(mcp, client, response_max_bytes=2000)
        raw = await mcp.tools["ha_list_entities_registry"]()
        result = json.loads(raw)
        self.assertTrue(result["truncated"])
        self.assertLess(result["count"], 100)

    async def test_ws_error(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(payload, timeout_seconds=30):
            raise HAConnectionError("offline")
        client.ws_send = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_entities_registry"]()
        result = json.loads(raw)
        self.assertIn("error", result)

    async def test_empty_registry(self) -> None:
        client = self._make_client([])
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_entities_registry"]()
        result = json.loads(raw)
        self.assertEqual(result["count"], 0)
        self.assertFalse(result["truncated"])


# ── Tests ha_get_entity_registry ─────────────────────────────────────────────

class TestGetEntityRegistry(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_found(self) -> None:
        entry = {
            "entity_id": "sensor.temp",
            "platform": "mqtt",
            "unique_id": "abc",
            "disabled_by": None,
        }
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return entry
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_entity_registry"]("sensor.temp")
        result = json.loads(raw)
        self.assertEqual(result["entity_id"], "sensor.temp")

    async def test_not_found(self) -> None:
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return None
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_entity_registry"]("sensor.ghost")
        result = json.loads(raw)
        self.assertIn("error", result)
        self.assertEqual(result["error"], "not_found")

    async def test_ws_error(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(payload, timeout_seconds=30):
            raise HAConnectionError("offline")
        client.ws_send = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_entity_registry"]("sensor.temp")
        result = json.loads(raw)
        self.assertIn("error", result)


# ── Tests ha_update_entity_registry ─────────────────────────────────────────

class TestUpdateEntityRegistry(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def _make_client(self, get_result=None, update_result=None):
        client = make_ready_client(self.session, {})
        responses = {"get": get_result, "update": update_result}
        async def fake_ws(payload, timeout_seconds=30):
            if payload.get("type") == "config/entity_registry/get":
                return responses["get"]
            return responses["update"]
        client.ws_send = fake_ws  # type: ignore[method-assign]
        return client

    async def test_preview_returned_without_token(self) -> None:
        client = self._make_client(
            get_result={"entity_id": "sensor.temp", "name": None}
        )
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_update_entity_registry"](
            "sensor.temp", {"name": "Mi Sensor"}
        )
        result = json.loads(raw)
        self.assertIn("confirmation_token", result)
        self.assertIn("preview", result)

    async def test_bool_disabled_by_coercion(self) -> None:
        """True → 'user', False → None."""
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            if payload.get("type") == "config/entity_registry/get":
                return {"entity_id": "sensor.temp"}
            return {"entity_entry": {"entity_id": "sensor.temp"}}
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        # First call gets token
        raw = await mcp.tools["ha_update_entity_registry"](
            "sensor.temp", {"disabled_by": True}
        )
        token = json.loads(raw)["confirmation_token"]
        # Second call with token
        await mcp.tools["ha_update_entity_registry"](
            "sensor.temp", {"disabled_by": True}, confirmation_token=token
        )
        update_payload = next(
            p for p in received if p.get("type") == "config/entity_registry/update"
        )
        self.assertEqual(update_payload["disabled_by"], "user")

    async def test_invalid_disabled_by_rejected(self) -> None:
        client = make_ready_client(self.session, {})
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_update_entity_registry"](
            "sensor.temp", {"disabled_by": "integration"}
        )
        result = json.loads(raw)
        self.assertIn("error", result)

    async def test_empty_updates_rejected(self) -> None:
        client = make_ready_client(self.session, {})
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_update_entity_registry"]("sensor.temp", {})
        result = json.loads(raw)
        self.assertIn("error", result)

    async def test_payload_fields_sent_to_ws(self) -> None:
        """Los campos de updates se incluyen en el payload WS."""
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            if payload.get("type") == "config/entity_registry/get":
                return {"entity_id": "sensor.temp"}
            return {"entity_entry": {"entity_id": "sensor.temp"}}
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_update_entity_registry"](
            "sensor.temp", {"name": "Nuevo Nombre", "area_id": "salon"}
        )
        token = json.loads(raw)["confirmation_token"]
        await mcp.tools["ha_update_entity_registry"](
            "sensor.temp",
            {"name": "Nuevo Nombre", "area_id": "salon"},
            confirmation_token=token,
        )
        update_payload = next(
            p for p in received if p.get("type") == "config/entity_registry/update"
        )
        self.assertEqual(update_payload["name"], "Nuevo Nombre")
        self.assertEqual(update_payload["area_id"], "salon")

    async def test_invalid_token_rejected(self) -> None:
        client = make_ready_client(self.session, {})
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_update_entity_registry"](
            "sensor.temp", {"name": "X"}, confirmation_token="bad-token"
        )
        result = json.loads(raw)
        self.assertIn("error", result)


# ── Tests ha_remove_entity_registry ─────────────────────────────────────────

class TestRemoveEntityRegistry(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_preview_without_token(self) -> None:
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return {"entity_id": "sensor.temp", "unique_id": "abc"}
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_remove_entity_registry"]("sensor.temp")
        result = json.loads(raw)
        self.assertIn("confirmation_token", result)
        self.assertIn("preview", result)
        # Warning about device recreation must be present
        self.assertIn("warning", result["preview"])

    async def test_remove_with_valid_token(self) -> None:
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            if payload.get("type") == "config/entity_registry/get":
                return {"entity_id": "sensor.temp"}
            return None  # remove returns null
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_remove_entity_registry"]("sensor.temp")
        token = json.loads(raw)["confirmation_token"]
        raw2 = await mcp.tools["ha_remove_entity_registry"](
            "sensor.temp", confirmation_token=token
        )
        result = json.loads(raw2)
        self.assertEqual(result["result"], "ok")
        remove_calls = [
            p for p in received
            if p.get("type") == "config/entity_registry/remove"
        ]
        self.assertEqual(len(remove_calls), 1)
        self.assertEqual(remove_calls[0]["entity_id"], "sensor.temp")

    async def test_invalid_token_rejected(self) -> None:
        client = make_ready_client(self.session, {})
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        raw = await mcp.tools["ha_remove_entity_registry"](
            "sensor.temp", confirmation_token="garbage"
        )
        result = json.loads(raw)
        self.assertIn("error", result)
