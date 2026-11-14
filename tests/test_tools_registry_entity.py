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


# ── Regresiones 1.0.12: alias, not_found y área efectiva ────────────────────


class TestAliasesNullMarker(unittest.IsolatedAsyncioTestCase):
    """P1/R6: desde HA 2026.4 un `null` dentro de `aliases` es el nombre
    calculado de la entidad. Hermes lo convertía en el texto "None" (P1) y
    aceptaba `aliases: null`, que el esquema de HA rechaza (R6)."""

    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def _client(self, received: list[dict], version: object = "2026.11.1"):
        client = make_ready_client(self.session, {})

        async def capture(payload, timeout_seconds=30):
            if payload.get("type") == "get_config":
                return {"version": version}
            received.append(payload)
            if payload.get("type") == "config/entity_registry/get":
                return {"entity_id": "light.x", "aliases": [None]}
            return {"entity_entry": {"entity_id": "light.x"}}

        client.ws_send = capture  # type: ignore[method-assign]
        return client

    async def _update(self, client, updates):
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        tool = mcp.tools["ha_update_entity_registry"]
        first = json.loads(await tool("light.x", updates))
        if "confirmation_token" not in first:
            return first
        return json.loads(await tool(
            "light.x", updates, confirmation_token=first["confirmation_token"]
        ))

    def _sent_update(self, received: list[dict]) -> dict:
        return next(
            p for p in received if p.get("type") == "config/entity_registry/update"
        )

    async def test_null_inside_aliases_reaches_ha_as_null(self) -> None:
        received: list[dict] = []
        result = await self._update(
            self._client(received), {"aliases": [None, "lámpara"]}
        )
        self.assertEqual(result.get("result"), "ok")
        self.assertEqual(self._sent_update(received)["aliases"], [None, "lámpara"])

    async def test_null_alias_on_old_ha_is_rejected(self) -> None:
        """M1: antes de 2026.4 HA no admite el null; en 2024.10 lo guardaba y
        rompía Assist. Sin token y sin llamar a HA."""
        for version in ("2024.10.0", "2026.3.4"):
            received: list[dict] = []
            result = await self._update(
                self._client(received, version), {"aliases": [None, "lámpara"]}
            )
            self.assertEqual(result.get("error"), "null_alias_requires_ha_2026_4")
            self.assertNotIn("confirmation_token", result)
            self.assertEqual(received, [])

    async def test_null_alias_with_unknown_version_is_rejected(self) -> None:
        """M1: versión desconocida → fail-closed."""
        received: list[dict] = []
        result = await self._update(
            self._client(received, None), {"aliases": [None]}
        )
        self.assertEqual(result.get("error"), "ha_version_unknown")
        self.assertEqual(received, [])

    async def test_string_aliases_on_old_ha_still_work(self) -> None:
        received: list[dict] = []
        result = await self._update(
            self._client(received, "2024.10.0"), {"aliases": ["lámpara"]}
        )
        self.assertEqual(result.get("result"), "ok")

    async def test_aliases_null_rejected_without_ws_call(self) -> None:
        received: list[dict] = []
        result = await self._update(self._client(received), {"aliases": None})
        self.assertIn("error", result)
        self.assertIn("[]", result["error"])
        self.assertIn("[null]", result["error"])
        self.assertEqual(received, [], "no debe llamarse a HA")

    async def test_aliases_with_dict_element_rejected(self) -> None:
        received: list[dict] = []
        result = await self._update(self._client(received), {"aliases": [{"a": 1}]})
        self.assertIn("error", result)
        self.assertEqual(received, [])

    async def test_aliases_number_becomes_text(self) -> None:
        received: list[dict] = []
        await self._update(self._client(received), {"aliases": [3]})
        self.assertEqual(self._sent_update(received)["aliases"], ["3"])

    async def test_description_explains_null_and_name(self) -> None:
        """C1 + FR-013: la descripción no puede mentir sobre `null` ni `name`."""
        mcp = DummyMCP()
        entity_mod.register(mcp, make_ready_client(self.session, {}))
        doc = mcp.tools["ha_update_entity_registry"].__doc__ or ""
        self.assertNotIn("null = limpiar", doc)
        # null dentro de la lista = nombre calculado; la lista sustituye.
        self.assertIn("[null]", doc)
        self.assertIn("calculado", doc)
        self.assertIn("sustituye", doc)
        # Desde 2026.11 HA antepone el nombre del dispositivo a `name`.
        self.assertIn("2026.11", doc)
        self.assertIn("antepone", doc)


class TestGetEntityRegistryNotFoundCode(unittest.IsolatedAsyncioTestCase):
    """C6: HA responde a una entidad inexistente con un error `not_found`, no
    con `None`; Hermes devolvía el texto del error en vez de `not_found`."""

    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def _get(self, exc):
        client = make_ready_client(self.session, {})

        async def boom(payload, timeout_seconds=30):
            raise exc

        client.ws_send = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        return json.loads(await mcp.tools["ha_get_entity_registry"]("sensor.ghost"))

    async def test_not_found_code_maps_to_not_found(self) -> None:
        from hermes.ha import HAConnectionError
        result = await self._get(HAConnectionError(
            "HA WS command failed: Entity not found", code="not_found"
        ))
        self.assertEqual(
            result, {"error": "not_found", "entity_id": "sensor.ghost"}
        )

    async def test_other_code_keeps_error_text(self) -> None:
        from hermes.ha import HAConnectionError
        result = await self._get(HAConnectionError(
            "HA WS command failed: boom", code="unknown_error"
        ))
        self.assertEqual(result, {"error": "HA WS command failed: boom"})


class TestListEntitiesEffectiveArea(unittest.IsolatedAsyncioTestCase):
    """D3: una entidad sin área propia está en el área de su dispositivo, y un
    dispositivo hijo sin área está en la de su padre (HA 2026.9)."""

    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_filter_uses_effective_area(self) -> None:
        devices = [
            {"id": "padre", "area_id": "salon"},
            {"id": "hijo", "area_id": None, "parent_device_id": "padre"},
            {"id": "otro", "area_id": "cocina"},
        ]
        entities = [
            {"entity_id": "light.propia", "area_id": "salon", "device_id": None},
            {"entity_id": "light.del_padre", "area_id": None, "device_id": "padre"},
            {"entity_id": "light.del_hijo", "area_id": None, "device_id": "hijo"},
            {"entity_id": "light.override", "area_id": "cocina", "device_id": "padre"},
            {"entity_id": "light.de_otro", "area_id": None, "device_id": "otro"},
        ]
        client = make_ready_client(self.session, {})

        async def fake_ws(payload, timeout_seconds=30):
            if payload.get("type") == "config/device_registry/list":
                return devices
            return entities

        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        entity_mod.register(mcp, client)
        result = json.loads(
            await mcp.tools["ha_list_entities_registry"](area_id="salon")
        )
        ids = {e["entity_id"] for e in result["entities"]}
        self.assertEqual(ids, {"light.propia", "light.del_padre", "light.del_hijo"})
