"""Tests para tools de device registry con fake WS."""

from __future__ import annotations

import json
import unittest

from aiohttp import ClientSession

import hermes.tools.registry_device as device_mod
from tests._ha_fixture import make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _make_device_entries(n: int) -> list[dict]:
    manufacturers = ["Xiaomi", "Philips", "Ikea"]
    return [
        {
            "id": f"device_{i:04d}",
            "name": f"Device {i}",
            "name_by_user": None,
            "manufacturer": manufacturers[i % 3],
            "model": f"Model {i}",
            "area_id": "salon" if i % 2 == 0 else None,
            "disabled_by": None,
            "labels": [],
            "config_entries": [f"ce_{i}"],
        }
        for i in range(n)
    ]


class TestListDevices(unittest.IsolatedAsyncioTestCase):
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
        devices = _make_device_entries(5)
        client = self._make_client(devices)
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_devices"]()
        result = json.loads(raw)
        self.assertEqual(result["count"], 5)
        self.assertFalse(result["truncated"])

    async def test_filter_area_id(self) -> None:
        devices = _make_device_entries(6)
        client = self._make_client(devices)
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_devices"](area_id="salon")
        result = json.loads(raw)
        self.assertEqual(result["count"], 3)  # i=0,2,4

    async def test_filter_manufacturer(self) -> None:
        devices = _make_device_entries(6)
        client = self._make_client(devices)
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_devices"](manufacturer="Xiaomi")
        result = json.loads(raw)
        self.assertEqual(result["count"], 2)  # i=0,3

    async def test_filter_disabled_true(self) -> None:
        devices = _make_device_entries(4)
        devices[1]["disabled_by"] = "user"
        client = self._make_client(devices)
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_devices"](disabled=True)
        result = json.loads(raw)
        self.assertEqual(result["count"], 1)

    async def test_filter_disabled_false(self) -> None:
        devices = _make_device_entries(4)
        devices[1]["disabled_by"] = "user"
        client = self._make_client(devices)
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_devices"](disabled=False)
        result = json.loads(raw)
        self.assertEqual(result["count"], 3)

    async def test_truncation(self) -> None:
        devices = _make_device_entries(100)
        client = self._make_client(devices)
        mcp = DummyMCP()
        device_mod.register(mcp, client, response_max_bytes=2000)
        raw = await mcp.tools["ha_list_devices"]()
        result = json.loads(raw)
        self.assertTrue(result["truncated"])

    async def test_ws_error(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(payload, timeout_seconds=30):
            raise HAConnectionError("offline")
        client.ws_send = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_devices"]()
        result = json.loads(raw)
        self.assertIn("error", result)


class TestGetDevice(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_found(self) -> None:
        devices = _make_device_entries(3)
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return devices
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_device"]("device_0001")
        result = json.loads(raw)
        self.assertEqual(result["id"], "device_0001")

    async def test_not_found(self) -> None:
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return []
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_device"]("ghost_device")
        result = json.loads(raw)
        self.assertEqual(result["error"], "not_found")


class TestUpdateDevice(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_preview_without_token(self) -> None:
        devices = _make_device_entries(1)
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return devices
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        raw = await mcp.tools["ha_update_device"](
            "device_0000", {"name_by_user": "Mi Device"}
        )
        result = json.loads(raw)
        self.assertIn("confirmation_token", result)
        self.assertIn("preview", result)

    async def test_bool_disabled_by_coercion(self) -> None:
        devices = _make_device_entries(1)
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            return devices
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        raw = await mcp.tools["ha_update_device"](
            "device_0000", {"disabled_by": False}
        )
        token = json.loads(raw)["confirmation_token"]
        await mcp.tools["ha_update_device"](
            "device_0000", {"disabled_by": False}, confirmation_token=token
        )
        update_payload = next(
            p for p in received
            if p.get("type") == "config/device_registry/update"
        )
        self.assertIsNone(update_payload["disabled_by"])

    async def test_invalid_disabled_by_rejected(self) -> None:
        client = make_ready_client(self.session, {})
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        raw = await mcp.tools["ha_update_device"](
            "device_0000", {"disabled_by": "config_entry"}
        )
        result = json.loads(raw)
        self.assertIn("error", result)

    async def test_labels_validated(self) -> None:
        client = make_ready_client(self.session, {})
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        raw = await mcp.tools["ha_update_device"](
            "device_0000", {"labels": "not_a_list"}
        )
        result = json.loads(raw)
        self.assertIn("error", result)

    async def test_payload_sent_to_ws(self) -> None:
        devices = _make_device_entries(1)
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            return devices
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        raw = await mcp.tools["ha_update_device"](
            "device_0000", {"area_id": "cocina", "name_by_user": "Sensor Cocina"}
        )
        token = json.loads(raw)["confirmation_token"]
        await mcp.tools["ha_update_device"](
            "device_0000",
            {"area_id": "cocina", "name_by_user": "Sensor Cocina"},
            confirmation_token=token,
        )
        update_payload = next(
            p for p in received
            if p.get("type") == "config/device_registry/update"
        )
        self.assertEqual(update_payload["area_id"], "cocina")
        self.assertEqual(update_payload["name_by_user"], "Sensor Cocina")
        self.assertEqual(update_payload["device_id"], "device_0000")


class TestRemoveDeviceFromConfigEntry(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_preview_without_token(self) -> None:
        client = make_ready_client(self.session, {})
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        raw = await mcp.tools["ha_remove_device_from_config_entry"](
            "device_0000", "ce_abc"
        )
        result = json.loads(raw)
        self.assertIn("confirmation_token", result)
        self.assertIn("preview", result)
        self.assertIn("warning", result["preview"])

    async def test_remove_with_valid_token(self) -> None:
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            return {"id": "device_0000"}
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        raw = await mcp.tools["ha_remove_device_from_config_entry"](
            "device_0000", "ce_abc"
        )
        token = json.loads(raw)["confirmation_token"]
        raw2 = await mcp.tools["ha_remove_device_from_config_entry"](
            "device_0000", "ce_abc", confirmation_token=token
        )
        result = json.loads(raw2)
        self.assertEqual(result["result"], "ok")
        remove_calls = [
            p for p in received
            if p.get("type") == "config/device_registry/remove_config_entry"
        ]
        self.assertEqual(len(remove_calls), 1)
        self.assertEqual(remove_calls[0]["device_id"], "device_0000")
        self.assertEqual(remove_calls[0]["config_entry_id"], "ce_abc")
