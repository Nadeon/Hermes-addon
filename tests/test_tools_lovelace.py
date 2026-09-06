"""Tests de tools de Lovelace dashboards.

Usa un FakeWSSender que monkey-patchea ws_send en el HAClient con
respuestas configurables por tipo de comando.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from hermes import security
from hermes.ha import HAConnectionError
import hermes.tools.lovelace as mod
from hermes.tools.lovelace import _count_cards, _summarize_dashboard_diff

from tests._ha_fixture import make_ready_client
from aiohttp import ClientSession


# ── Fixtures ───────────────────────────────────────────────────────────────────


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


FAKE_DASHBOARDS = [
    {
        "id": "map",
        "url_path": "map",
        "title": "Mapa",
        "icon": "mdi:map",
        "mode": "storage",
        "show_in_sidebar": True,
        "require_admin": False,
    },
    {
        "id": "yaml-dash",
        "url_path": "yaml-dash",
        "title": "YAML Dashboard",
        "icon": None,
        "mode": "yaml",
        "show_in_sidebar": True,
        "require_admin": False,
    },
]

FAKE_MAP_CONFIG = {
    "strategy": {"type": "map"},
}

FAKE_DEFAULT_CONFIG = {
    "views": [
        {
            "title": "Home",
            "path": "home",
            "cards": [
                {"type": "weather-forecast", "entity": "weather.home"},
                {"type": "entities", "entities": ["light.living_room"]},
            ],
        },
        {
            "title": "Lights",
            "path": "lights",
            "cards": [
                {"type": "light", "entity": "light.bedroom"},
            ],
        },
    ]
}

FAKE_RESOURCES = [
    {
        "id": "res1",
        "url": "/hacsfiles/sunsynk-power-flow-card/sunsynk-power-flow-card.js",
        "type": "module",
    }
]


class FakeWSSender:
    """Fake de ws_send con respuestas configurables por type de comando."""

    def __init__(self) -> None:
        self._responses: dict[str, Any] = {}
        self._calls: list[dict[str, Any]] = []

    def set(self, ws_type: str, response: Any) -> None:
        self._responses[ws_type] = response

    def calls_for(self, ws_type: str) -> list[dict]:
        return [c for c in self._calls if c.get("type") == ws_type]

    async def ws_send(self, payload: dict, timeout_seconds: int = 30) -> Any:
        self._calls.append(dict(payload))
        t = payload.get("type", "")
        if t in self._responses:
            resp = self._responses[t]
            if isinstance(resp, Exception):
                raise resp
            return resp
        raise HAConnectionError(f"FakeWSSender: no response configured for type={t!r}")

    def install(self, ha_client: Any) -> None:
        ha_client.ws_send = self.ws_send


# ── Test class ─────────────────────────────────────────────────────────────────


class TestLovelaceHelpers(unittest.TestCase):
    """Unit tests for internal helper functions."""

    def test_count_cards_empty(self) -> None:
        self.assertEqual(_count_cards([]), 0)

    def test_count_cards_basic(self) -> None:
        views = [{"cards": [1, 2]}, {"cards": [3]}]
        self.assertEqual(_count_cards(views), 3)

    def test_count_cards_sections(self) -> None:
        views = [
            {"sections": [{"cards": [1, 2]}, {"cards": [3]}]},
        ]
        self.assertEqual(_count_cards(views), 3)

    def test_count_cards_badges(self) -> None:
        views = [{"cards": [1], "badges": ["a", "b"]}]
        self.assertEqual(_count_cards(views), 3)

    def test_summarize_diff_basic(self) -> None:
        current = {"views": [{"cards": [1, 2]}]}
        new = {"views": [{"cards": [1, 2, 3]}, {"cards": [4]}]}
        diff = _summarize_dashboard_diff(current, new)
        self.assertEqual(diff["views_count_before"], 1)
        self.assertEqual(diff["views_count_after"], 2)
        self.assertEqual(diff["total_cards_badges_before"], 2)
        self.assertEqual(diff["total_cards_badges_after"], 4)
        self.assertFalse(diff["has_strategy"])

    def test_summarize_diff_strategy(self) -> None:
        diff = _summarize_dashboard_diff(None, {"strategy": {"type": "map"}})
        self.assertTrue(diff["has_strategy"])
        self.assertEqual(diff["views_count_before"], 0)

    def test_summarize_diff_theme_changed(self) -> None:
        diff = _summarize_dashboard_diff(
            {"views": [], "theme": "dark"},
            {"views": [], "theme": "light"},
        )
        self.assertTrue(diff["theme_changed"])

    def test_summarize_diff_no_current(self) -> None:
        diff = _summarize_dashboard_diff(None, {"views": []})
        self.assertEqual(diff["views_count_before"], 0)


class TestToolsLovelace(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

        self.session = ClientSession()
        self.ha_client = make_ready_client(self.session)
        self.ws = FakeWSSender()
        self.ws.install(self.ha_client)

        # Default responses
        self.ws.set("lovelace/dashboards", FAKE_DASHBOARDS)
        self.ws.set("lovelace/config", FAKE_DEFAULT_CONFIG)
        self.ws.set("lovelace/resources", FAKE_RESOURCES)

        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha_client, response_max_bytes=1_048_576)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    # ── ha_list_lovelace_dashboards ────────────────────────────────────────────

    async def test_list_dashboards_includes_default(self) -> None:
        result = await self.mcp.tools["ha_list_lovelace_dashboards"]()
        self.assertIsInstance(result, list)
        # First entry is synthetic default
        self.assertIs(result[0]["url_path"], None)
        self.assertTrue(result[0]["is_default"])

    async def test_list_dashboards_includes_extra(self) -> None:
        result = await self.mcp.tools["ha_list_lovelace_dashboards"]()
        url_paths = [d.get("url_path") for d in result]
        self.assertIn("map", url_paths)
        self.assertIn("yaml-dash", url_paths)

    async def test_list_dashboards_extra_not_default(self) -> None:
        result = await self.mcp.tools["ha_list_lovelace_dashboards"]()
        for d in result[1:]:
            self.assertFalse(d["is_default"])

    async def test_list_dashboards_ws_error(self) -> None:
        # Cuando lovelace/dashboards falla (HA no registra el comando),
        # se devuelve al menos el dashboard default (degraded graceful).
        self.ws.set("lovelace/dashboards", HAConnectionError("ws down"))
        result = await self.mcp.tools["ha_list_lovelace_dashboards"]()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["is_default"])

    # ── ha_get_lovelace_dashboard ──────────────────────────────────────────────

    async def test_get_default_dashboard(self) -> None:
        result = await self.mcp.tools["ha_get_lovelace_dashboard"]()
        self.assertIn("views", result)
        self.assertEqual(len(result["views"]), 2)

    async def test_get_dashboard_by_url_path(self) -> None:
        self.ws.set("lovelace/config", FAKE_MAP_CONFIG)
        result = await self.mcp.tools["ha_get_lovelace_dashboard"]("map")
        self.assertIn("strategy", result)

    async def test_get_dashboard_yaml_mode(self) -> None:
        result = await self.mcp.tools["ha_get_lovelace_dashboard"]("yaml-dash")
        self.assertEqual(result.get("error"), "yaml_mode")
        self.assertEqual(result.get("url_path"), "yaml-dash")

    async def test_get_dashboard_view_index(self) -> None:
        result = await self.mcp.tools["ha_get_lovelace_dashboard"](None, view_index=1)
        self.assertEqual(result["view_index"], 1)
        self.assertEqual(result["view"]["title"], "Lights")
        self.assertEqual(result["views_total"], 2)

    async def test_get_dashboard_view_index_out_of_range(self) -> None:
        result = await self.mcp.tools["ha_get_lovelace_dashboard"](None, view_index=99)
        self.assertEqual(result.get("error"), "view_index_out_of_range")
        self.assertEqual(result.get("views_count"), 2)

    async def test_get_dashboard_too_large(self) -> None:
        mod2 = __import__("hermes.tools.lovelace", fromlist=["register"])
        small_mcp = DummyMCP()
        mod2.register(small_mcp, self.ha_client, response_max_bytes=10)
        result = await small_mcp.tools["ha_get_lovelace_dashboard"]()
        self.assertEqual(result.get("error"), "too_large")
        self.assertIn("hint", result)

    async def test_get_dashboard_no_views_for_index(self) -> None:
        self.ws.set("lovelace/config", FAKE_MAP_CONFIG)
        result = await self.mcp.tools["ha_get_lovelace_dashboard"]("map", view_index=0)
        self.assertEqual(result.get("error"), "no_views")

    # ── ha_save_lovelace_dashboard ─────────────────────────────────────────────

    async def test_save_dashboard_preview(self) -> None:
        config = {"views": [{"title": "New", "cards": []}]}
        result = await self.mcp.tools["ha_save_lovelace_dashboard"](None, config)
        self.assertIn("confirmation_token", result)
        self.assertIn("diff", result.get("preview", {}))

    async def test_save_dashboard_apply(self) -> None:
        config = {"views": [{"title": "New", "cards": []}]}
        self.ws.set("lovelace/config/save", None)
        token_resp = await self.mcp.tools["ha_save_lovelace_dashboard"](None, config)
        token = token_resp["confirmation_token"]
        result = await self.mcp.tools["ha_save_lovelace_dashboard"](
            None, config, confirmation_token=token
        )
        self.assertEqual(result.get("result"), "ok")
        save_calls = self.ws.calls_for("lovelace/config/save")
        self.assertEqual(len(save_calls), 1)
        self.assertEqual(save_calls[0]["config"], config)

    async def test_save_dashboard_with_url_path(self) -> None:
        config = {"views": [{"title": "Map Home", "cards": []}]}
        self.ws.set("lovelace/config/save", None)
        # First get the token
        token_resp = await self.mcp.tools["ha_save_lovelace_dashboard"]("map", config)
        token = token_resp["confirmation_token"]
        result = await self.mcp.tools["ha_save_lovelace_dashboard"](
            "map", config, confirmation_token=token
        )
        self.assertEqual(result.get("result"), "ok")
        self.assertEqual(result.get("url_path"), "map")
        save_calls = self.ws.calls_for("lovelace/config/save")
        self.assertIn("url_path", save_calls[0])
        self.assertEqual(save_calls[0]["url_path"], "map")

    async def test_save_dashboard_yaml_mode_rejected(self) -> None:
        config = {"views": []}
        result = await self.mcp.tools["ha_save_lovelace_dashboard"](
            "yaml-dash", config
        )
        self.assertEqual(result.get("error"), "yaml_mode")

    async def test_save_dashboard_invalid_config(self) -> None:
        result = await self.mcp.tools["ha_save_lovelace_dashboard"](None, {"foo": "bar"})
        self.assertIn("error", result)
        self.assertIn("invalid_config", result["error"])

    async def test_save_dashboard_invalid_token(self) -> None:
        config = {"views": []}
        result = await self.mcp.tools["ha_save_lovelace_dashboard"](
            None, config, confirmation_token="bad-token"
        )
        self.assertIn("error", result)

    # ── ha_create_lovelace_dashboard ───────────────────────────────────────────

    async def test_create_dashboard(self) -> None:
        self.ws.set(
            "lovelace/dashboards/create",
            {"id": "test-dash", "url_path": "test-dash", "title": "Test"},
        )
        result = await self.mcp.tools["ha_create_lovelace_dashboard"](
            "test-dash", "Test Dashboard"
        )
        self.assertNotIn("error", result)
        self.assertEqual(result.get("url_path"), "test-dash")

    async def test_create_dashboard_with_icon(self) -> None:
        self.ws.set(
            "lovelace/dashboards/create",
            {"id": "my-dash", "url_path": "my-dash", "title": "My"},
        )
        await self.mcp.tools["ha_create_lovelace_dashboard"](
            "my-dash", "My Dash", icon="mdi:home"
        )
        calls = self.ws.calls_for("lovelace/dashboards/create")
        self.assertEqual(calls[0].get("icon"), "mdi:home")

    async def test_create_dashboard_no_token_needed(self) -> None:
        # create should not return a confirmation_token
        self.ws.set(
            "lovelace/dashboards/create",
            {"id": "x", "url_path": "x", "title": "X"},
        )
        result = await self.mcp.tools["ha_create_lovelace_dashboard"]("x", "X")
        self.assertNotIn("confirmation_token", result)

    async def test_create_dashboard_ws_error(self) -> None:
        self.ws.set(
            "lovelace/dashboards/create",
            HAConnectionError("url_path already in use"),
        )
        result = await self.mcp.tools["ha_create_lovelace_dashboard"]("map", "Dup")
        self.assertIn("error", result)

    # ── ha_update_lovelace_dashboard_metadata ──────────────────────────────────

    async def test_update_metadata_title_no_token(self) -> None:
        self.ws.set(
            "lovelace/dashboards/update",
            {"id": "map", "url_path": "map", "title": "New Name"},
        )
        result = await self.mcp.tools["ha_update_lovelace_dashboard_metadata"](
            "map", {"title": "New Name"}
        )
        # No token needed for title change
        self.assertNotIn("error", result)
        self.assertNotIn("confirmation_token", result)

    async def test_update_metadata_sidebar_needs_token(self) -> None:
        result = await self.mcp.tools["ha_update_lovelace_dashboard_metadata"](
            "map", {"show_in_sidebar": False}
        )
        self.assertIn("confirmation_token", result)

    async def test_update_metadata_require_admin_needs_token(self) -> None:
        result = await self.mcp.tools["ha_update_lovelace_dashboard_metadata"](
            "map", {"require_admin": True}
        )
        self.assertIn("confirmation_token", result)

    async def test_update_metadata_apply_with_token(self) -> None:
        self.ws.set(
            "lovelace/dashboards/update",
            {"id": "map", "url_path": "map", "require_admin": True},
        )
        token_resp = await self.mcp.tools["ha_update_lovelace_dashboard_metadata"](
            "map", {"require_admin": True}
        )
        token = token_resp["confirmation_token"]
        result = await self.mcp.tools["ha_update_lovelace_dashboard_metadata"](
            "map", {"require_admin": True}, confirmation_token=token
        )
        self.assertNotIn("error", result)
        calls = self.ws.calls_for("lovelace/dashboards/update")
        self.assertEqual(calls[0]["dashboard_id"], "map")
        self.assertTrue(calls[0].get("require_admin"))

    async def test_update_metadata_not_found(self) -> None:
        result = await self.mcp.tools["ha_update_lovelace_dashboard_metadata"](
            "nonexistent", {"title": "Nope"}
        )
        self.assertEqual(result.get("error"), "not_found")

    # ── ha_delete_lovelace_dashboard ───────────────────────────────────────────

    async def test_delete_default_rejected(self) -> None:
        result = await self.mcp.tools["ha_delete_lovelace_dashboard"](None)
        self.assertEqual(result.get("error"), "cannot_delete_default_dashboard")

    async def test_delete_dashboard_preview(self) -> None:
        result = await self.mcp.tools["ha_delete_lovelace_dashboard"]("map")
        self.assertIn("confirmation_token", result)
        self.assertIn("dashboard", result.get("preview", {}))

    async def test_delete_dashboard_apply(self) -> None:
        self.ws.set("lovelace/dashboards/delete", None)
        token_resp = await self.mcp.tools["ha_delete_lovelace_dashboard"]("map")
        token = token_resp["confirmation_token"]
        result = await self.mcp.tools["ha_delete_lovelace_dashboard"](
            "map", confirmation_token=token
        )
        self.assertEqual(result.get("result"), "ok")
        del_calls = self.ws.calls_for("lovelace/dashboards/delete")
        self.assertEqual(len(del_calls), 1)
        self.assertEqual(del_calls[0]["dashboard_id"], "map")

    async def test_delete_dashboard_not_found(self) -> None:
        result = await self.mcp.tools["ha_delete_lovelace_dashboard"]("ghost")
        self.assertEqual(result.get("error"), "not_found")

    async def test_delete_dashboard_invalid_token(self) -> None:
        result = await self.mcp.tools["ha_delete_lovelace_dashboard"](
            "map", confirmation_token="bad"
        )
        self.assertIn("error", result)

    # ── ha_list_lovelace_resources ─────────────────────────────────────────────

    async def test_list_resources(self) -> None:
        result = await self.mcp.tools["ha_list_lovelace_resources"]()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "res1")

    async def test_list_resources_ws_error(self) -> None:
        self.ws.set("lovelace/resources", HAConnectionError("ws error"))
        result = await self.mcp.tools["ha_list_lovelace_resources"]()
        self.assertIn("error", result)

    # ── ha_create_lovelace_resource ────────────────────────────────────────────

    async def test_create_resource_preview(self) -> None:
        result = await self.mcp.tools["ha_create_lovelace_resource"](
            "/hacsfiles/card.js", "module"
        )
        self.assertIn("confirmation_token", result)
        self.assertIn("WARNING", result["preview"]["warning"])

    async def test_create_resource_apply(self) -> None:
        self.ws.set(
            "lovelace/resources/create",
            {"id": "new-res", "url": "/hacsfiles/card.js", "type": "module"},
        )
        token_resp = await self.mcp.tools["ha_create_lovelace_resource"](
            "/hacsfiles/card.js", "module"
        )
        token = token_resp["confirmation_token"]
        result = await self.mcp.tools["ha_create_lovelace_resource"](
            "/hacsfiles/card.js", "module", confirmation_token=token
        )
        self.assertNotIn("error", result)
        calls = self.ws.calls_for("lovelace/resources/create")
        self.assertEqual(calls[0]["url"], "/hacsfiles/card.js")
        self.assertEqual(calls[0]["res_type"], "module")

    async def test_create_resource_invalid_token(self) -> None:
        result = await self.mcp.tools["ha_create_lovelace_resource"](
            "/card.js", "module", confirmation_token="bad"
        )
        self.assertIn("error", result)

    # ── ha_update_lovelace_resource ────────────────────────────────────────────

    async def test_update_resource_preview(self) -> None:
        result = await self.mcp.tools["ha_update_lovelace_resource"](
            "res1", {"url": "/hacsfiles/card-v2.js"}
        )
        self.assertIn("confirmation_token", result)

    async def test_update_resource_apply(self) -> None:
        self.ws.set(
            "lovelace/resources/update",
            {"id": "res1", "url": "/hacsfiles/card-v2.js", "type": "module"},
        )
        token_resp = await self.mcp.tools["ha_update_lovelace_resource"](
            "res1", {"url": "/hacsfiles/card-v2.js"}
        )
        token = token_resp["confirmation_token"]
        result = await self.mcp.tools["ha_update_lovelace_resource"](
            "res1", {"url": "/hacsfiles/card-v2.js"}, confirmation_token=token
        )
        self.assertNotIn("error", result)
        calls = self.ws.calls_for("lovelace/resources/update")
        self.assertEqual(calls[0]["resource_id"], "res1")
        self.assertEqual(calls[0]["url"], "/hacsfiles/card-v2.js")

    # ── ha_delete_lovelace_resource ────────────────────────────────────────────

    async def test_delete_resource_preview(self) -> None:
        result = await self.mcp.tools["ha_delete_lovelace_resource"]("res1")
        self.assertIn("confirmation_token", result)

    async def test_delete_resource_apply(self) -> None:
        self.ws.set("lovelace/resources/delete", None)
        token_resp = await self.mcp.tools["ha_delete_lovelace_resource"]("res1")
        token = token_resp["confirmation_token"]
        result = await self.mcp.tools["ha_delete_lovelace_resource"](
            "res1", confirmation_token=token
        )
        self.assertEqual(result.get("result"), "ok")
        self.assertEqual(result.get("resource_id"), "res1")
        del_calls = self.ws.calls_for("lovelace/resources/delete")
        self.assertEqual(del_calls[0]["resource_id"], "res1")

    async def test_delete_resource_invalid_token(self) -> None:
        result = await self.mcp.tools["ha_delete_lovelace_resource"](
            "res1", confirmation_token="bad"
        )
        self.assertIn("error", result)
