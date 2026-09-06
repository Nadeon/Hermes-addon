"""Tests de la tool ha_fire_event."""

from __future__ import annotations

import unittest

from aiohttp import ClientSession

import hermes.tools.events as mod
from tests._ha_fixture import make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class TestToolsEvents(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.ha_client = make_ready_client(self.session, {})
        self.fired: list[tuple[str, dict | None]] = []

        async def fake_fire_event(event_type, event_data=None):
            self.fired.append((event_type, event_data))
            return {"context": {"id": "test-ctx"}}

        self.ha_client.fire_event = fake_fire_event  # type: ignore[method-assign]

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_disabled_when_allowlist_empty(self) -> None:
        mcp = DummyMCP()
        mod.register(mcp, self.ha_client, [])
        result = await mcp.tools["ha_fire_event"]("hermes_test")
        self.assertEqual(result["error"], "event firing disabled")
        self.assertEqual(self.fired, [])

    async def test_rejected_when_not_in_allowlist(self) -> None:
        mcp = DummyMCP()
        mod.register(mcp, self.ha_client, ["allowed_a", "allowed_b"])
        result = await mcp.tools["ha_fire_event"]("hermes_test")
        self.assertEqual(result["error"], "event_type not in allowlist")
        self.assertEqual(result["allowed"], ["allowed_a", "allowed_b"])
        self.assertEqual(self.fired, [])

    async def test_fires_when_allowed(self) -> None:
        mcp = DummyMCP()
        mod.register(mcp, self.ha_client, ["hermes_test"])
        result = await mcp.tools["ha_fire_event"](
            "hermes_test", {"foo": "bar"}
        )
        self.assertEqual(result["result"], "ok")
        self.assertEqual(result["event_type"], "hermes_test")
        self.assertEqual(self.fired, [("hermes_test", {"foo": "bar"})])

    async def test_fires_without_data(self) -> None:
        mcp = DummyMCP()
        mod.register(mcp, self.ha_client, ["hermes_test"])
        result = await mcp.tools["ha_fire_event"]("hermes_test")
        self.assertEqual(result["result"], "ok")
        self.assertEqual(self.fired, [("hermes_test", None)])

    async def test_fire_event_handles_exceptions(self) -> None:
        async def boom(event_type, event_data=None):
            raise RuntimeError("ws down")

        self.ha_client.fire_event = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        mod.register(mcp, self.ha_client, ["hermes_test"])
        result = await mcp.tools["ha_fire_event"]("hermes_test")
        self.assertIn("error", result)
        self.assertIn("ws down", result["error"])
