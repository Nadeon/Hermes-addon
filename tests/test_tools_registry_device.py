"""Tests para tools de device registry con fake WS."""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

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

    async def test_preview_and_description_say_deprecated(self) -> None:
        """P2/FR-019: desde HA 2026.9 este comando borra el dispositivo entero
        si la integración es la suya; la preview decía «quita la asociación»."""
        client = make_ready_client(self.session, {})
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        tool = mcp.tools["ha_remove_device_from_config_entry"]
        preview = json.loads(await tool("device_0000", "ce_abc"))["preview"]
        self.assertIs(preview.get("deprecated"), True)
        self.assertEqual(preview.get("replacement"), "ha_remove_device")
        self.assertIn("2026.9", preview["warning"])
        self.assertIn("WHOLE DEVICE", preview["warning"])
        self.assertIn("2027.9", preview["warning"])
        doc = tool.__doc__ or ""
        self.assertIn("DEPRECATED", doc)
        self.assertIn("2027.9", doc)
        self.assertIn("ha_remove_device", doc.replace("ha_remove_device_from", ""))


# ── Regresiones 1.0.12: ha_remove_device (P2) ───────────────────────────────


class TestRemoveDevice(unittest.IsolatedAsyncioTestCase):
    """P2: no había forma veraz de borrar un dispositivo. La tool nueva elige
    el comando por la versión de HA y la preview dice cuál usará."""

    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.devices = [
            {
                "id": "dev_a", "name": "Device A", "name_by_user": None,
                "config_entry_id": "ce_1", "config_entries": ["ce_1"],
            },
            {
                "id": "dev_b", "name": "Device B", "name_by_user": "Mi B",
                "config_entry_id": "ce_1", "config_entries": ["ce_1", "ce_2"],
            },
        ]
        self.entities = [
            {"entity_id": "light.a1", "device_id": "dev_a"},
            {"entity_id": "light.a2", "device_id": "dev_a"},
            {"entity_id": "sensor.a3", "device_id": "dev_a"},
            {"entity_id": "light.b1", "device_id": "dev_b"},
        ]
        self.received: list[dict] = []

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def _tool(self):
        client = make_ready_client(self.session, {})

        async def fake_ws(payload, timeout_seconds=30):
            self.received.append(payload)
            t = payload.get("type")
            if t == "config/device_registry/list":
                return self.devices
            if t == "config/entity_registry/list":
                return self.entities
            return None

        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        return mcp.tools["ha_remove_device"]

    def _removals(self) -> list[dict]:
        return [
            p for p in self.received
            if p.get("type", "").startswith("config/device_registry/remove")
        ]

    def _version(self, *values):
        """Parchea ha_at_least con una respuesta por llamada."""
        return patch.object(
            device_mod, "ha_at_least", AsyncMock(side_effect=list(values))
        )

    async def test_new_ha_uses_remove_and_preview_is_truthful(self) -> None:
        tool = self._tool()
        with self._version(True, True):
            first = json.loads(await tool("dev_a"))
            preview = first["preview"]
            self.assertEqual(preview["action"], "delete_device")
            self.assertEqual(preview["method"], "config/device_registry/remove")
            self.assertEqual(preview["entities_count"], 3)
            self.assertEqual(preview["device_name"], "Device A")
            self.assertIn("Deletes this device", preview["warning"])
            self.assertIn("3 entity registry entries", preview["warning"])
            self.assertNotIn("config_entry_id", preview)
            self.assertEqual(self._removals(), [], "la preview no borra nada")
            result = json.loads(await tool(
                "dev_a", confirmation_token=first["confirmation_token"]
            ))
        self.assertEqual(result["result"], "ok")
        self.assertEqual(result["method"], "config/device_registry/remove")
        self.assertEqual(
            self._removals(),
            [{"type": "config/device_registry/remove", "device_id": "dev_a"}],
        )

    async def test_old_ha_with_one_entry_uses_remove_config_entry(self) -> None:
        tool = self._tool()
        with self._version(False, False):
            first = json.loads(await tool("dev_a"))
            preview = first["preview"]
            self.assertEqual(
                preview["method"], "config/device_registry/remove_config_entry"
            )
            self.assertEqual(preview["config_entry_id"], "ce_1")
            self.assertIn("Deletes this device", preview["warning"])
            await tool("dev_a", confirmation_token=first["confirmation_token"])
        self.assertEqual(
            self._removals(),
            [{
                "type": "config/device_registry/remove_config_entry",
                "device_id": "dev_a",
                "config_entry_id": "ce_1",
            }],
        )

    async def test_old_ha_with_several_entries_refuses(self) -> None:
        tool = self._tool()
        with self._version(False):
            result = json.loads(await tool("dev_b"))
        self.assertEqual(result["error"], "multiple_config_entries")
        self.assertNotIn("confirmation_token", result)
        self.assertIn("ha_remove_device_from_config_entry", result["hint"])

    async def test_unknown_version_refuses(self) -> None:
        tool = self._tool()
        with self._version(None):
            result = json.loads(await tool("dev_a"))
        self.assertEqual(result["error"], "ha_version_unknown")
        self.assertNotIn("confirmation_token", result)

    async def test_missing_device_is_not_found(self) -> None:
        tool = self._tool()
        with self._version(True):
            result = json.loads(await tool("dev_ghost"))
        self.assertEqual(result["error"], "not_found")
        self.assertNotIn("confirmation_token", result)

    async def test_version_change_between_preview_and_run_aborts(self) -> None:
        tool = self._tool()
        with self._version(False, True):
            first = json.loads(await tool("dev_a"))
            token = first["confirmation_token"]
            result = json.loads(await tool("dev_a", confirmation_token=token))
        self.assertEqual(result["error"], "ha_version_changed")
        self.assertEqual(self._removals(), [])
        # El token queda fallido: no se puede reintentar con él.
        with self._version(True):
            again = json.loads(await tool("dev_a", confirmation_token=token))
        self.assertIn("error", again)
        self.assertEqual(self._removals(), [])

    def test_is_classified_destructive(self) -> None:
        from hermes.tools._annotations import classify
        annotations = classify("ha_remove_device")
        self.assertTrue(annotations.destructive_hint)
        self.assertFalse(annotations.read_only_hint)

    async def test_token_bound_to_device_id(self) -> None:
        tool = self._tool()
        self.devices.append({"id": "dev_c", "name": "C", "config_entry_id": "ce_3"})
        with self._version(True, True):
            first = json.loads(await tool("dev_a"))
            result = json.loads(await tool(
                "dev_c", confirmation_token=first["confirmation_token"]
            ))
        self.assertIn("error", result)
        self.assertNotEqual(result.get("result"), "ok")
        self.assertEqual(self._removals(), [])


# ── Regresiones 1.0.12: dispositivos hijo y área efectiva (D3) ──────────────


class TestListDevicesEffectiveArea(unittest.IsolatedAsyncioTestCase):
    """D3: desde HA 2026.9 un dispositivo hijo sin área propia está en el área
    de su padre; el filtro solo miraba `area_id` y lo dejaba fuera."""

    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def _list(self, devices, **kwargs):
        client = make_ready_client(self.session, {})

        async def fake_ws(payload, timeout_seconds=30):
            return devices

        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        device_mod.register(mcp, client)
        return json.loads(await mcp.tools["ha_list_devices"](**kwargs))

    async def test_child_inherits_parent_area(self) -> None:
        devices = [
            {"id": "padre", "area_id": "salon", "manufacturer": "Acme"},
            {"id": "hijo", "area_id": None, "parent_device_id": "padre"},
            {"id": "nieto", "area_id": None, "parent_device_id": "hijo"},
            {"id": "otro", "area_id": "cocina", "manufacturer": "Acme"},
        ]
        result = await self._list(devices, area_id="salon")
        self.assertEqual(
            {d["id"] for d in result["devices"]}, {"padre", "hijo", "nieto"}
        )

    async def test_cycle_does_not_hang_or_match(self) -> None:
        devices = [
            {"id": "x", "area_id": None, "parent_device_id": "y"},
            {"id": "y", "area_id": None, "parent_device_id": "x"},
        ]
        result = await self._list(devices, area_id="salon")
        self.assertEqual(result["count"], 0)

    async def test_manufacturer_filter_unchanged(self) -> None:
        devices = [
            {"id": "padre", "area_id": "salon", "manufacturer": "Acme"},
            {"id": "hijo", "area_id": None, "parent_device_id": "padre"},
        ]
        result = await self._list(devices, manufacturer="Acme")
        self.assertEqual([d["id"] for d in result["devices"]], ["padre"])

    async def test_description_names_current_fields(self) -> None:
        """FR-024: la descripción nombra `config_entry_id` y avisa de los hijos."""
        mcp = DummyMCP()
        device_mod.register(mcp, make_ready_client(self.session, {}))
        doc = mcp.tools["ha_list_devices"].__doc__ or ""
        self.assertIn("config_entry_id", doc)
        self.assertIn("parent_device_id", doc)
        self.assertIn("2027.8", doc)
        self.assertIn("fabricante", doc)
