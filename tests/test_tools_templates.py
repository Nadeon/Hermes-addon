"""Tests de ha_render_template — cubre el flujo WS de suscripción completo."""

from __future__ import annotations

import asyncio
import json
import unittest

from aiohttp import ClientSession

import hermes.tools.templates as mod
from tests._ha_fixture import make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _make_client_with_subscription(session, event_payload: dict, delay: float = 0.0, fail_result: bool = False):
    """Construye un HAClient cuyo ws_one_shot_subscription finge el flujo HA:
       - Devuelve event_payload como si HA lo hubiera emitido como type:event.
       - Si fail_result=True, lanza HAConnectionError (suscripción rechazada).
       - Si delay>0, espera antes de devolver (simula latencia de HA).
    """
    from hermes.ha import HAConnectionError

    client = make_ready_client(session, {})

    async def fake_one_shot(payload, event_timeout_seconds=10.0):
        if fail_result:
            raise HAConnectionError("HA WS command failed: template error")
        if delay > 0:
            await asyncio.sleep(delay)
        return event_payload

    client.ws_one_shot_subscription = fake_one_shot  # type: ignore[method-assign]
    return client


def _make_client_with_timeout(session):
    """Simula timeout en ws_one_shot_subscription."""
    from hermes.ha import HAConnectionError

    client = make_ready_client(session, {})

    async def fake_timeout(payload, event_timeout_seconds=10.0):
        raise HAConnectionError("Timeout waiting for subscription event: render_template")

    client.ws_one_shot_subscription = fake_timeout  # type: ignore[method-assign]
    return client


class TestToolsTemplates(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_render_simple_template(self) -> None:
        client = _make_client_with_subscription(
            self.session,
            {"result": "on", "listeners": {"entities": ["light.salon"], "all_states": False}},
        )
        mcp = DummyMCP()
        mod.register(mcp, client)
        raw = await mcp.tools["ha_render_template"]("{{ states('light.salon') }}")
        result = json.loads(raw)
        self.assertEqual(result["result"], "on")
        self.assertIn("listeners", result)

    async def test_render_returns_numeric_result(self) -> None:
        client = _make_client_with_subscription(
            self.session,
            {"result": 42, "listeners": {}},
        )
        mcp = DummyMCP()
        mod.register(mcp, client)
        raw = await mcp.tools["ha_render_template"]("{{ 6 * 7 }}")
        result = json.loads(raw)
        self.assertEqual(result["result"], 42)

    async def test_render_nonexistent_entity_returns_unknown(self) -> None:
        """states('sensor.no_existe_xxx') devuelve 'unknown' — no error.

        Con report_errors=True y strict=False (defaults), HA devuelve
        event con result='unknown'.
        """
        client = _make_client_with_subscription(
            self.session,
            {"result": "unknown", "listeners": {"entities": [], "all_states": False}},
        )
        mcp = DummyMCP()
        mod.register(mcp, client)
        raw = await mcp.tools["ha_render_template"]("{{ states('sensor.no_existe_xxx') }}")
        result = json.loads(raw)
        self.assertEqual(result["result"], "unknown")

    async def test_render_template_error_returned_as_structured(self) -> None:
        """Errores de template vienen como event {error: ..., level: ...}."""
        client = _make_client_with_subscription(
            self.session,
            {"error": "UndefinedError: 'no_var' is undefined", "level": "ERROR"},
        )
        mcp = DummyMCP()
        mod.register(mcp, client)
        raw = await mcp.tools["ha_render_template"]("{{ no_var }}", strict=True)
        result = json.loads(raw)
        self.assertEqual(result["error"], "template_error")
        self.assertIn("undefined", result["detail"])
        self.assertEqual(result["level"], "ERROR")

    async def test_render_timeout_returns_structured_error(self) -> None:
        """Timeout devuelve {"error": "template_timeout", "template": ...}."""
        client = _make_client_with_timeout(self.session)
        mcp = DummyMCP()
        mod.register(mcp, client)
        raw = await mcp.tools["ha_render_template"]("{{ states.all | list }}", timeout=5.0)
        result = json.loads(raw)
        self.assertEqual(result["error"], "template_timeout")
        self.assertIn("template", result)
        self.assertIn("hint", result)

    async def test_render_with_variables(self) -> None:
        """Variables se pasan al payload WS."""
        received_payload: list[dict] = []
        session = self.session
        client = make_ready_client(session, {})

        async def capture_payload(payload, event_timeout_seconds=10.0):
            received_payload.append(payload)
            return {"result": "hola mundo", "listeners": {}}

        client.ws_one_shot_subscription = capture_payload  # type: ignore[method-assign]

        mcp = DummyMCP()
        mod.register(mcp, client)
        await mcp.tools["ha_render_template"](
            "{{ greeting }} {{ name }}",
            variables={"greeting": "hola", "name": "mundo"},
        )
        self.assertEqual(received_payload[0]["variables"], {"greeting": "hola", "name": "mundo"})

    async def test_render_strict_flag_passed(self) -> None:
        """strict=True se pasa al payload WS."""
        received_payload: list[dict] = []
        session = self.session
        client = make_ready_client(session, {})

        async def capture_payload(payload, event_timeout_seconds=10.0):
            received_payload.append(payload)
            return {"result": "x", "listeners": {}}

        client.ws_one_shot_subscription = capture_payload  # type: ignore[method-assign]

        mcp = DummyMCP()
        mod.register(mcp, client)
        await mcp.tools["ha_render_template"]("{{ x }}", strict=True)
        self.assertTrue(received_payload[0]["strict"])
        self.assertTrue(received_payload[0]["report_errors"])
