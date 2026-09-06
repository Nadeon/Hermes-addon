"""Tests para tools de config entry flows con fake WS/REST."""

from __future__ import annotations

import json
import unittest

from aiohttp import ClientSession

import hermes.tools.config_entry_flows as flows_mod
from tests._ha_fixture import make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


# ── Tests ha_list_configured_domains ───────────────────────────────────────────────
# Uses WS (config_entries/get)

class TestListFlowHandlers(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_returns_unique_domains(self) -> None:
        entries = [
            {"entry_id": "e1", "domain": "hue"},
            {"entry_id": "e2", "domain": "mqtt"},
            {"entry_id": "e3", "domain": "hue"},  # duplicate
        ]
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return entries
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_configured_domains"]()
        result = json.loads(raw)
        self.assertEqual(result["count"], 2)
        self.assertIn("hue", result["domains"])
        self.assertIn("mqtt", result["domains"])

    async def test_empty(self) -> None:
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return []
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_configured_domains"]()
        result = json.loads(raw)
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["domains"], [])

    async def test_ws_error(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(payload, timeout_seconds=30):
            raise HAConnectionError("offline")
        client.ws_send = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_configured_domains"]()
        result = json.loads(raw)
        self.assertIn("error", result)


# ── Tests ha_start_config_entry_flow ──────────────────────────────────────────
# Uses REST (POST /config/config_entries/flow)

class TestStartConfigEntryFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_form_result(self) -> None:
        flow_resp = {
            "flow_id": "flow1",
            "type": "form",
            "step_id": "user",
            "schema": [{"name": "host", "type": "string"}],
        }
        client = make_ready_client(self.session, {})
        async def fake_rest(method, path, json_body=None, params=None):
            return flow_resp
        client._request_json = fake_rest  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_start_config_entry_flow"]("hue")
        result = json.loads(raw)
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["flow_id"], "flow1")

    async def test_create_entry_result(self) -> None:
        flow_resp = {
            "flow_id": "flow2",
            "type": "create_entry",
            "entry_id": "e_new",
            "title": "My Integration",
        }
        client = make_ready_client(self.session, {})
        async def fake_rest(method, path, json_body=None, params=None):
            return flow_resp
        client._request_json = fake_rest  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_start_config_entry_flow"]("simple_int")
        result = json.loads(raw)
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["entry_id"], "e_new")

    async def test_external_type_auto_aborts(self) -> None:
        """OAuth flows must be auto-aborted and return non_automatable error."""
        rest_calls: list[tuple] = []
        flow_resp = {"flow_id": "flow3", "type": "external", "url": "https://oauth.example.com"}

        client = make_ready_client(self.session, {})
        async def fake_rest(method, path, json_body=None, params=None):
            rest_calls.append((method, path))
            if method == "DELETE":
                return None
            return flow_resp
        client._request_json = fake_rest  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_start_config_entry_flow"]("google")
        result = json.loads(raw)
        self.assertEqual(result["error"], "non_automatable")
        self.assertEqual(result["type"], "external")
        # Abort DELETE was called
        delete_calls = [c for c in rest_calls if c[0] == "DELETE"]
        self.assertEqual(len(delete_calls), 1)
        self.assertIn("flow3", delete_calls[0][1])

    async def test_progress_type_auto_aborts(self) -> None:
        rest_calls: list[tuple] = []
        flow_resp = {"flow_id": "flow4", "type": "progress"}

        client = make_ready_client(self.session, {})
        async def fake_rest(method, path, json_body=None, params=None):
            rest_calls.append((method, path))
            if method == "DELETE":
                return None
            return flow_resp
        client._request_json = fake_rest  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_start_config_entry_flow"]("zeroconf_discovery")
        result = json.loads(raw)
        self.assertEqual(result["error"], "non_automatable")
        delete_calls = [c for c in rest_calls if c[0] == "DELETE"]
        self.assertEqual(len(delete_calls), 1)

    async def test_empty_handler_rejected(self) -> None:
        client = make_ready_client(self.session, {})
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_start_config_entry_flow"]("   ")
        result = json.loads(raw)
        self.assertIn("error", result)

    async def test_rest_sends_correct_path_and_body(self) -> None:
        received: list[tuple] = []
        client = make_ready_client(self.session, {})
        async def capture(method, path, json_body=None, params=None):
            received.append((method, path, json_body))
            return {"flow_id": "f1", "type": "form", "step_id": "user", "schema": []}
        client._request_json = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        await mcp.tools["ha_start_config_entry_flow"]("hue")
        self.assertEqual(received[0][0], "POST")
        self.assertEqual(received[0][1], "/config/config_entries/flow")
        self.assertEqual(received[0][2]["handler"], "hue")

    async def test_rest_error(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(method, path, json_body=None, params=None):
            raise HAConnectionError("404")
        client._request_json = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_start_config_entry_flow"]("hue")
        result = json.loads(raw)
        self.assertIn("error", result)


# ── Tests ha_continue_config_entry_flow ───────────────────────────────────────
# Uses REST (POST /config/config_entries/flow/{flow_id})

class TestContinueConfigEntryFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_continue_form_step(self) -> None:
        next_step = {
            "flow_id": "flow1",
            "type": "form",
            "step_id": "confirm",
            "schema": [],
        }
        received: list[tuple] = []
        client = make_ready_client(self.session, {})
        async def capture(method, path, json_body=None, params=None):
            received.append((method, path, json_body))
            return next_step
        client._request_json = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_continue_config_entry_flow"](
            "flow1", {"host": "192.168.1.1"}
        )
        result = json.loads(raw)
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "confirm")
        self.assertEqual(received[0][0], "POST")
        self.assertEqual(received[0][1], "/config/config_entries/flow/flow1")
        self.assertEqual(received[0][2]["host"], "192.168.1.1")

    async def test_continue_creates_entry(self) -> None:
        create_resp = {
            "flow_id": "flow1",
            "type": "create_entry",
            "entry_id": "new_e",
            "title": "Hue Bridge",
        }
        client = make_ready_client(self.session, {})
        async def fake_rest(method, path, json_body=None, params=None):
            return create_resp
        client._request_json = fake_rest  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_continue_config_entry_flow"](
            "flow1", {"confirm": True}
        )
        result = json.loads(raw)
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["result"], "ok")
        self.assertEqual(result["entry_id"], "new_e")

    async def test_continue_abort(self) -> None:
        abort_resp = {"flow_id": "flow1", "type": "abort", "reason": "already_configured"}
        client = make_ready_client(self.session, {})
        async def fake_rest(method, path, json_body=None, params=None):
            return abort_resp
        client._request_json = fake_rest  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_continue_config_entry_flow"]("flow1", {})
        result = json.loads(raw)
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "already_configured")

    async def test_rest_error(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(method, path, json_body=None, params=None):
            raise HAConnectionError("offline")
        client._request_json = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_continue_config_entry_flow"]("f1", {})
        result = json.loads(raw)
        self.assertIn("error", result)


# ── Tests ha_abort_config_entry_flow ──────────────────────────────────────────
# Uses REST (DELETE /config/config_entries/flow/{flow_id})

class TestAbortConfigEntryFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_abort_sends_delete(self) -> None:
        received: list[tuple] = []
        client = make_ready_client(self.session, {})
        async def capture(method, path, json_body=None, params=None):
            received.append((method, path))
            return None
        client._request_json = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_abort_config_entry_flow"]("flow1")
        result = json.loads(raw)
        self.assertEqual(result["result"], "ok")
        self.assertEqual(received[0][0], "DELETE")
        self.assertEqual(received[0][1], "/config/config_entries/flow/flow1")

    async def test_rest_error(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(method, path, json_body=None, params=None):
            raise HAConnectionError("flow not found")
        client._request_json = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_abort_config_entry_flow"]("flow1")
        result = json.loads(raw)
        self.assertIn("error", result)


# ── Tests ha_get_config_entry_options ─────────────────────────────────────────
# Uses WS (config_entries/get_single)

class TestGetConfigEntryOptions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_returns_options(self) -> None:
        entry = {
            "entry_id": "e1",
            "domain": "hue",
            "title": "Hue",
            "supports_options": True,
            "options": {"scan_interval": 30, "allow_unreachable": False},
        }
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return {"config_entry": entry}
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_config_entry_options"]("e1")
        result = json.loads(raw)
        self.assertEqual(result["entry_id"], "e1")
        self.assertTrue(result["supports_options"])
        self.assertEqual(result["options"]["scan_interval"], 30)

    async def test_not_found(self) -> None:
        client = make_ready_client(self.session, {})
        async def fake_ws(payload, timeout_seconds=30):
            return {"config_entry": None}
        client.ws_send = fake_ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_config_entry_options"]("ghost")
        result = json.loads(raw)
        self.assertEqual(result["error"], "not_found")


# ── Tests ha_start_options_flow ───────────────────────────────────────────────
# Uses REST (POST /config/config_entries/options/flow)

class TestStartOptionsFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_options_flow_form(self) -> None:
        flow_resp = {
            "flow_id": "opt_flow1",
            "type": "form",
            "step_id": "init",
            "schema": [{"name": "scan_interval", "type": "integer"}],
        }
        received: list[tuple] = []
        client = make_ready_client(self.session, {})
        async def capture(method, path, json_body=None, params=None):
            received.append((method, path, json_body))
            return flow_resp
        client._request_json = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_start_options_flow"]("e1")
        result = json.loads(raw)
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["flow_id"], "opt_flow1")
        self.assertEqual(received[0][0], "POST")
        self.assertEqual(received[0][1], "/config/config_entries/options/flow")
        self.assertEqual(received[0][2]["handler"], "e1")

    async def test_external_type_auto_aborts(self) -> None:
        rest_calls: list[tuple] = []
        flow_resp = {"flow_id": "opt_flow2", "type": "external"}

        client = make_ready_client(self.session, {})
        async def fake_rest(method, path, json_body=None, params=None):
            rest_calls.append((method, path))
            if method == "DELETE":
                return None
            return flow_resp
        client._request_json = fake_rest  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_start_options_flow"]("e1")
        result = json.loads(raw)
        self.assertEqual(result["error"], "non_automatable")
        delete_calls = [c for c in rest_calls if c[0] == "DELETE"]
        self.assertEqual(len(delete_calls), 1)

    async def test_rest_error(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(method, path, json_body=None, params=None):
            raise HAConnectionError("offline")
        client._request_json = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_start_options_flow"]("e1")
        result = json.loads(raw)
        self.assertIn("error", result)


# ── Tests ha_continue_options_flow ────────────────────────────────────────────
# Uses REST (POST /config/config_entries/options/flow/{flow_id})

class TestContinueOptionsFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_options_saved(self) -> None:
        save_resp = {
            "flow_id": "opt_flow1",
            "type": "create_entry",
            "entry_id": "e1",
        }
        received: list[tuple] = []
        client = make_ready_client(self.session, {})
        async def capture(method, path, json_body=None, params=None):
            received.append((method, path, json_body))
            return save_resp
        client._request_json = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_continue_options_flow"](
            "opt_flow1", {"scan_interval": 60}
        )
        result = json.loads(raw)
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["result"], "ok")
        self.assertEqual(received[0][0], "POST")
        self.assertEqual(received[0][1], "/config/config_entries/options/flow/opt_flow1")
        self.assertEqual(received[0][2]["scan_interval"], 60)

    async def test_next_form_step(self) -> None:
        next_resp = {"flow_id": "opt_flow1", "type": "form", "step_id": "confirm", "schema": []}
        client = make_ready_client(self.session, {})
        async def fake_rest(method, path, json_body=None, params=None):
            return next_resp
        client._request_json = fake_rest  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_continue_options_flow"]("opt_flow1", {})
        result = json.loads(raw)
        self.assertEqual(result["type"], "form")
        self.assertNotIn("result", result)

    async def test_rest_error(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(method, path, json_body=None, params=None):
            raise HAConnectionError("offline")
        client._request_json = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        flows_mod.register(mcp, client)
        raw = await mcp.tools["ha_continue_options_flow"]("f1", {})
        result = json.loads(raw)
        self.assertIn("error", result)
