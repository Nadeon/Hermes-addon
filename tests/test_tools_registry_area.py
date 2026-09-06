"""Tests para tools de area registry con fake WS."""

from __future__ import annotations

import json
import unittest

from aiohttp import ClientSession

import hermes.tools.registry_area as area_mod
from tests._ha_fixture import make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _make_area_entries(n: int) -> list[dict]:
    return [
        {
            "area_id": f"area_{i}",
            "name": f"Area {i}",
            "icon": None,
            "picture": None,
            "aliases": [],
            "floor_id": None,
            "labels": [],
        }
        for i in range(n)
    ]


# ── Tests ha_list_areas ───────────────────────────────────────────────────────

class TestListAreas(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_basic_list(self) -> None:
        areas = _make_area_entries(4)
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return areas
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        area_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_areas"]()
        result = json.loads(raw)
        self.assertEqual(result["count"], 4)
        self.assertEqual(len(result["areas"]), 4)

    async def test_empty(self) -> None:
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return []
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        area_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_areas"]()
        result = json.loads(raw)
        self.assertEqual(result["count"], 0)

    async def test_ws_error(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(payload, timeout_seconds=30):
            raise HAConnectionError("offline")
        client.ws_send = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        area_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_areas"]()
        result = json.loads(raw)
        self.assertIn("error", result)


# ── Tests ha_get_area ─────────────────────────────────────────────────────────

class TestGetArea(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_found(self) -> None:
        areas = _make_area_entries(3)
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return areas
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        area_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_area"]("area_1")
        result = json.loads(raw)
        self.assertEqual(result["area_id"], "area_1")
        self.assertEqual(result["name"], "Area 1")

    async def test_not_found(self) -> None:
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return []
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        area_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_area"]("ghost_area")
        result = json.loads(raw)
        self.assertEqual(result["error"], "not_found")


# ── Tests ha_create_area ──────────────────────────────────────────────────────

class TestCreateArea(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_create_basic(self) -> None:
        response = {"area_id": "salon", "name": "Salón", "aliases": [], "labels": []}
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            return response
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        area_mod.register(mcp, client)
        raw = await mcp.tools["ha_create_area"]("Salón")
        result = json.loads(raw)
        self.assertEqual(result["area_id"], "salon")
        self.assertEqual(received[0]["type"], "config/area_registry/create")
        self.assertEqual(received[0]["name"], "Salón")

    async def test_create_with_optional_fields(self) -> None:
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            return {"area_id": "salon", "name": "Salón"}
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        area_mod.register(mcp, client)
        await mcp.tools["ha_create_area"](
            "Salón",
            icon="mdi:sofa",
            floor_id="planta_baja",
            aliases=["Living", "Sala"],
            labels=["principale"],
        )
        payload = received[0]
        self.assertEqual(payload["icon"], "mdi:sofa")
        self.assertEqual(payload["floor_id"], "planta_baja")
        self.assertIn("Living", payload["aliases"])
        self.assertIn("principale", payload["labels"])

    async def test_aliases_strips_whitespace(self) -> None:
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            return {"area_id": "x", "name": "X"}
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        area_mod.register(mcp, client)
        await mcp.tools["ha_create_area"]("X", aliases=["  Sala  ", "", "  "])
        # Empty strings and whitespace-only stripped
        self.assertEqual(received[0]["aliases"], ["Sala"])

    async def test_empty_name_rejected(self) -> None:
        client = make_ready_client(self.session, {})
        mcp = DummyMCP()
        area_mod.register(mcp, client)
        raw = await mcp.tools["ha_create_area"]("   ")
        result = json.loads(raw)
        self.assertIn("error", result)

    async def test_ws_error(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(payload, timeout_seconds=30):
            raise HAConnectionError("offline")
        client.ws_send = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        area_mod.register(mcp, client)
        raw = await mcp.tools["ha_create_area"]("Test")
        result = json.loads(raw)
        self.assertIn("error", result)


# ── Tests ha_update_area ──────────────────────────────────────────────────────

class TestUpdateArea(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def _make_client_with_areas(self, areas):
        client = make_ready_client(self.session, {})
        responses = {"list": areas, "update": {"area_id": "area_0", "name": "X"}}
        async def fake_ws(payload, timeout_seconds=30):
            if payload.get("type") == "config/area_registry/list":
                return responses["list"]
            return responses["update"]
        client.ws_send = fake_ws  # type: ignore[method-assign]
        return client

    async def test_preview_without_token(self) -> None:
        areas = _make_area_entries(2)
        client = self._make_client_with_areas(areas)
        mcp = DummyMCP()
        area_mod.register(mcp, client)
        raw = await mcp.tools["ha_update_area"]("area_0", {"name": "Nuevo Nombre"})
        result = json.loads(raw)
        self.assertIn("confirmation_token", result)
        self.assertIn("preview", result)
        self.assertEqual(result["preview"]["area_id"], "area_0")

    async def test_update_with_valid_token(self) -> None:
        areas = _make_area_entries(2)
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            if payload.get("type") == "config/area_registry/list":
                return areas
            return {"area_id": "area_0", "name": "Nuevo Nombre"}
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        area_mod.register(mcp, client)
        raw = await mcp.tools["ha_update_area"]("area_0", {"name": "Nuevo Nombre"})
        token = json.loads(raw)["confirmation_token"]
        raw2 = await mcp.tools["ha_update_area"](
            "area_0", {"name": "Nuevo Nombre"}, confirmation_token=token
        )
        result = json.loads(raw2)
        self.assertEqual(result["result"], "ok")
        update_call = next(
            p for p in received
            if p.get("type") == "config/area_registry/update"
        )
        self.assertEqual(update_call["area_id"], "area_0")
        self.assertEqual(update_call["name"], "Nuevo Nombre")

    async def test_invalid_aliases_rejected(self) -> None:
        client = make_ready_client(self.session, {})
        mcp = DummyMCP()
        area_mod.register(mcp, client)
        raw = await mcp.tools["ha_update_area"](
            "area_0", {"aliases": "not_a_list"}
        )
        result = json.loads(raw)
        self.assertIn("error", result)

    async def test_empty_updates_rejected(self) -> None:
        client = make_ready_client(self.session, {})
        mcp = DummyMCP()
        area_mod.register(mcp, client)
        raw = await mcp.tools["ha_update_area"]("area_0", {})
        result = json.loads(raw)
        self.assertIn("error", result)


# ── Tests ha_delete_area ──────────────────────────────────────────────────────

class TestDeleteArea(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_preview_includes_impact(self) -> None:
        """Preview must show entities_orphaned + devices_orphaned counts."""
        areas = [{"area_id": "salon", "name": "Salón"}]
        entities = [
            {"entity_id": "sensor.t1", "area_id": "salon"},
            {"entity_id": "sensor.t2", "area_id": "salon"},
            {"entity_id": "sensor.t3", "area_id": "other"},
        ]
        devices = [
            {"id": "d1", "area_id": "salon"},
            {"id": "d2", "area_id": "other"},
        ]
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            t = payload.get("type", "")
            if t == "config/area_registry/list":
                return areas
            if t == "config/entity_registry/list":
                return entities
            if t == "config/device_registry/list":
                return devices
            return None
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        area_mod.register(mcp, client)
        raw = await mcp.tools["ha_delete_area"]("salon")
        result = json.loads(raw)
        self.assertIn("confirmation_token", result)
        preview = result["preview"]
        self.assertEqual(preview["impact"]["entities_orphaned"], 2)
        self.assertEqual(preview["impact"]["devices_orphaned"], 1)
        self.assertIn("warning", preview)

    async def test_delete_with_valid_token(self) -> None:
        areas = [{"area_id": "salon", "name": "Salón"}]
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            t = payload.get("type", "")
            if t == "config/area_registry/list":
                return areas
            if t in ("config/entity_registry/list", "config/device_registry/list"):
                return []
            return "success"
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        area_mod.register(mcp, client)
        raw = await mcp.tools["ha_delete_area"]("salon")
        token = json.loads(raw)["confirmation_token"]
        raw2 = await mcp.tools["ha_delete_area"]("salon", confirmation_token=token)
        result = json.loads(raw2)
        self.assertEqual(result["result"], "ok")
        delete_calls = [
            p for p in received
            if p.get("type") == "config/area_registry/delete"
        ]
        self.assertEqual(len(delete_calls), 1)
        self.assertEqual(delete_calls[0]["area_id"], "salon")

    async def test_invalid_token_rejected(self) -> None:
        client = make_ready_client(self.session, {})
        mcp = DummyMCP()
        area_mod.register(mcp, client)
        raw = await mcp.tools["ha_delete_area"](
            "salon", confirmation_token="garbage"
        )
        result = json.loads(raw)
        self.assertIn("error", result)
