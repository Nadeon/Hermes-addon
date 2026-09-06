"""Tests para tools de config entries con fake WS."""

from __future__ import annotations

import json
import unittest

from aiohttp import ClientSession

import hermes.tools.config_entries as ce_mod
from tests._ha_fixture import make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _make_entry(
    entry_id: str = "e1",
    domain: str = "hue",
    title: str = "Philips Hue",
    state: str = "loaded",
    supports_options: bool = True,
    disabled_by: str | None = None,
) -> dict:
    return {
        "entry_id": entry_id,
        "domain": domain,
        "title": title,
        "source": "user",
        "state": state,
        "supports_options": supports_options,
        "supports_unload": True,
        "supports_remove_device": True,
        "disabled_by": disabled_by,
        "pref_disable_new_entities": False,
        "pref_disable_polling": False,
        "num_subentries": 0,
        "options": {"scan_interval": 30},
    }


# ── Tests ha_list_config_entries ──────────────────────────────────────────────

class TestListConfigEntries(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_basic_list(self) -> None:
        entries = [_make_entry("e1"), _make_entry("e2", domain="mqtt")]
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return entries
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_config_entries"]()
        result = json.loads(raw)
        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["entries"]), 2)

    async def test_empty(self) -> None:
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return []
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_config_entries"]()
        result = json.loads(raw)
        self.assertEqual(result["count"], 0)

    async def test_domain_filter_passed_to_ws(self) -> None:
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            return []
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)
        await mcp.tools["ha_list_config_entries"](domain="hue")
        self.assertEqual(received[0]["domain"], "hue")

    async def test_type_filter_passed_to_ws(self) -> None:
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            return []
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)
        await mcp.tools["ha_list_config_entries"](type_filter="helper")
        self.assertEqual(received[0]["type_filter"], "helper")

    async def test_ws_error(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(payload, timeout_seconds=30):
            raise HAConnectionError("offline")
        client.ws_send = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_config_entries"]()
        result = json.loads(raw)
        self.assertIn("error", result)


# ── Tests ha_get_config_entry ─────────────────────────────────────────────────

class TestGetConfigEntry(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_found_with_config_entry_wrapper(self) -> None:
        entry = _make_entry("e1")
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return {"config_entry": entry}
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_config_entry"]("e1")
        result = json.loads(raw)
        self.assertEqual(result["entry_id"], "e1")
        self.assertEqual(result["domain"], "hue")

    async def test_found_direct_dict(self) -> None:
        """HA puede devolver la entry directamente sin wrapper."""
        entry = _make_entry("e1")
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return entry
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_config_entry"]("e1")
        result = json.loads(raw)
        self.assertEqual(result["entry_id"], "e1")

    async def test_not_found_null(self) -> None:
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return {"config_entry": None}
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_config_entry"]("ghost")
        result = json.loads(raw)
        self.assertEqual(result["error"], "not_found")

    async def test_ws_error(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(payload, timeout_seconds=30):
            raise HAConnectionError("offline")
        client.ws_send = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_config_entry"]("e1")
        result = json.loads(raw)
        self.assertIn("error", result)


# ── Tests ha_reload_config_entry ──────────────────────────────────────────────

class TestReloadConfigEntry(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_reload_ok(self) -> None:
        rest_calls: list[tuple] = []
        client = make_ready_client(self.session, {})
        async def fake_rest(method, path, json_body=None, params=None):
            rest_calls.append((method, path))
            return {"require_restart": False}
        client._request_json = fake_rest  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)
        raw = await mcp.tools["ha_reload_config_entry"]("e1")
        result = json.loads(raw)
        self.assertEqual(result["result"], "ok")
        self.assertFalse(result["require_restart"])
        self.assertEqual(rest_calls[0], ("POST", "/config/config_entries/entry/e1/reload"))

    async def test_reload_require_restart(self) -> None:
        client = make_ready_client(self.session, {})
        async def fake_rest(method, path, json_body=None, params=None):
            return {"require_restart": True}
        client._request_json = fake_rest  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)
        raw = await mcp.tools["ha_reload_config_entry"]("e1")
        result = json.loads(raw)
        self.assertTrue(result["require_restart"])

    async def test_reload_rest_error(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(method, path, json_body=None, params=None):
            raise HAConnectionError("404")
        client._request_json = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)
        raw = await mcp.tools["ha_reload_config_entry"]("e1")
        result = json.loads(raw)
        self.assertIn("error", result)


# ── Tests ha_disable_config_entry ─────────────────────────────────────────────

class TestDisableEnableConfigEntry(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_disable_requires_a_token_first(self) -> None:
        """Deshabilitar deja la integración fuera: se confirma en dos pasos."""
        received: list[dict] = []
        client = make_ready_client(self.session, {})

        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            return {"require_restart": False}

        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)

        preview = json.loads(await mcp.tools["ha_disable_config_entry"]("e1"))
        self.assertIn("confirmation_token", preview)
        self.assertIn("preview", preview)
        self.assertNotIn(
            "config_entries/disable", [p.get("type") for p in received],
            "se deshabilitó sin confirmar")

    async def test_disable_sends_user_once_confirmed(self) -> None:
        received: list[dict] = []
        client = make_ready_client(self.session, {})

        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            return {"require_restart": False}

        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)

        preview = json.loads(await mcp.tools["ha_disable_config_entry"]("e1"))
        raw = await mcp.tools["ha_disable_config_entry"](
            "e1", confirmation_token=preview["confirmation_token"])
        result = json.loads(raw)
        self.assertEqual(result["result"], "ok")
        enviado = [p for p in received if p.get("type") == "config_entries/disable"]
        self.assertEqual(len(enviado), 1)
        self.assertEqual(enviado[0]["disabled_by"], "user")
        self.assertEqual(enviado[0]["entry_id"], "e1")

    async def test_disable_with_a_bad_token_does_nothing(self) -> None:
        received: list[dict] = []
        client = make_ready_client(self.session, {})

        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            return {"require_restart": False}

        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)

        result = json.loads(await mcp.tools["ha_disable_config_entry"](
            "e1", confirmation_token="no-vale"))
        self.assertIn("error", result)
        self.assertNotIn("config_entries/disable", [p.get("type") for p in received])

    async def test_enable_sends_null(self) -> None:
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            return {"require_restart": False}
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)
        raw = await mcp.tools["ha_enable_config_entry"]("e1")
        result = json.loads(raw)
        self.assertEqual(result["result"], "ok")
        self.assertIsNone(received[0]["disabled_by"])

    async def test_disable_ws_error_surfaces_on_the_confirmed_call(self) -> None:
        """El preview tolera que no se pueda leer la entry; la ejecución no.

        La primera llamada solo construye la vista previa, así que si el WS no
        responde se avisa en el log y se devuelve el token igualmente. El error
        tiene que aparecer cuando de verdad se intenta deshabilitar.
        """
        from hermes.ha import HAConnectionError

        client = make_ready_client(self.session, {})
        fallar = False

        async def quizas_falla(payload, timeout_seconds=30):
            if fallar:
                raise HAConnectionError("offline")
            return {}

        client.ws_send = quizas_falla  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)

        preview = json.loads(await mcp.tools["ha_disable_config_entry"]("e1"))
        self.assertIn("confirmation_token", preview)

        fallar = True
        result = json.loads(await mcp.tools["ha_disable_config_entry"](
            "e1", confirmation_token=preview["confirmation_token"]))
        self.assertIn("error", result)
        self.assertIn("offline", result["error"])


# ── Tests ha_delete_config_entry ──────────────────────────────────────────────

class TestDeleteConfigEntry(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def _make_client_with_responses(
        self,
        session,
        entry: dict,
        entities: list,
        devices: list,
        delete_resp: dict | None = None,
    ):
        """Cliente con WS fake multicall y REST fake."""
        client = make_ready_client(session, {})
        rest_resp = delete_resp or {"require_restart": False}

        async def fake_ws(payload, timeout_seconds=30):
            t = payload.get("type", "")
            if t == "config_entries/get_single":
                return {"config_entry": entry}
            if t == "config/entity_registry/list":
                return entities
            if t == "config/device_registry/list":
                return devices
            return None

        async def fake_rest(method, path, json_body=None, params=None):
            return rest_resp

        client.ws_send = fake_ws  # type: ignore[method-assign]
        client._request_json = fake_rest  # type: ignore[method-assign]
        return client

    async def test_preview_includes_impact(self) -> None:
        entry = _make_entry("e1")
        entities = [
            {"entity_id": "light.kitchen", "config_entry_id": "e1"},
            {"entity_id": "light.hallway", "config_entry_id": "e1"},
            {"entity_id": "sensor.outside", "config_entry_id": "e2"},
        ]
        devices = [
            {"id": "d1", "config_entries": ["e1"]},
            {"id": "d2", "config_entries": ["e2"]},
        ]
        client = self._make_client_with_responses(
            self.session, entry, entities, devices
        )
        mcp = DummyMCP()
        ce_mod.register(mcp, client)
        raw = await mcp.tools["ha_delete_config_entry"]("e1")
        result = json.loads(raw)
        self.assertIn("confirmation_token", result)
        preview = result["preview"]
        self.assertEqual(preview["impact"]["entities"], 2)
        self.assertEqual(preview["impact"]["devices"], 1)
        self.assertIn("warning", preview)
        self.assertIn("hue", preview["warning"].lower())

    async def test_delete_with_valid_token(self) -> None:
        entry = _make_entry("e1")
        rest_calls: list[tuple] = []
        client = make_ready_client(self.session, {})

        async def fake_ws(payload, timeout_seconds=30):
            t = payload.get("type", "")
            if t == "config_entries/get_single":
                return {"config_entry": entry}
            if t in ("config/entity_registry/list", "config/device_registry/list"):
                return []
            return None

        async def fake_rest(method, path, json_body=None, params=None):
            rest_calls.append((method, path))
            return {"require_restart": False}

        client.ws_send = fake_ws  # type: ignore[method-assign]
        client._request_json = fake_rest  # type: ignore[method-assign]
        mcp = DummyMCP()
        ce_mod.register(mcp, client)

        raw = await mcp.tools["ha_delete_config_entry"]("e1")
        token = json.loads(raw)["confirmation_token"]
        raw2 = await mcp.tools["ha_delete_config_entry"]("e1", confirmation_token=token)
        result = json.loads(raw2)
        self.assertEqual(result["result"], "ok")
        self.assertEqual(rest_calls[0], ("DELETE", "/config/config_entries/entry/e1"))

    async def test_invalid_token_rejected(self) -> None:
        client = make_ready_client(self.session, {})
        mcp = DummyMCP()
        ce_mod.register(mcp, client)
        raw = await mcp.tools["ha_delete_config_entry"](
            "e1", confirmation_token="garbage"
        )
        result = json.loads(raw)
        self.assertIn("error", result)

    async def test_preview_with_entities_in_config_entries_list(self) -> None:
        """Entity registry entries may use 'config_entries' list field."""
        entry = _make_entry("e1")
        entities = [
            {"entity_id": "sensor.x", "config_entries": ["e1"]},
            {"entity_id": "sensor.y", "config_entries": ["e1", "e2"]},
        ]
        devices: list = []
        client = self._make_client_with_responses(
            self.session, entry, entities, devices
        )
        mcp = DummyMCP()
        ce_mod.register(mcp, client)
        raw = await mcp.tools["ha_delete_config_entry"]("e1")
        result = json.loads(raw)
        preview = result["preview"]
        self.assertEqual(preview["impact"]["entities"], 2)
