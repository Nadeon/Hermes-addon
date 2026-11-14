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

from structlog.testing import capture_logs

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


# Forma de `frontend/get_system_data` con `key: "core"`, comprobada en el
# código de Home Assistant 2026.11.1 (T043, spec S-04):
# - `components/frontend/storage.py`, `websocket_get_system_data`, responde
#   `send_result(id, {"value": store.data.get(msg["key"])})`; el almacén es
#   `.storage/frontend.system_data`. Si nadie escribió nunca la clave `core`,
#   `value` es `None`.
# - `components/lovelace/__init__.py`, `_async_migrate_default_config` (la
#   migración de 2026.2, solo en modo storage), escribe
#   `core = {**core_data, "default_panel": "lovelace"}` si no había panel; el
#   usuario puede cambiarlo después desde el frontend.
# Así que `value` es `None` o un dict, y `default_panel` (si está) es un str.
# Coincide con research R-C1; cualquier otra forma se trata como desconocida.
FAKE_SYSTEM_DATA_CORE = {"value": {"default_panel": "lovelace"}}

# Instalación migrada por HA 2026.2: el dashboard principal ya es una entrada
# más de la colección, con `url_path: "lovelace"`.
FAKE_LOVELACE_DASHBOARD = {
    "id": "lovelace",
    "url_path": "lovelace",
    "title": "Overview",
    "icon": "mdi:view-dashboard",
    "mode": "storage",
    "show_in_sidebar": True,
    "require_admin": False,
}


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
        self.ws.set("lovelace/dashboards/list", FAKE_DASHBOARDS)
        self.ws.set("lovelace/config", FAKE_DEFAULT_CONFIG)
        self.ws.set("lovelace/resources/list", FAKE_RESOURCES)
        # Respuesta real de HA 2026.11 tras la migración de 2026.2 (ver
        # FAKE_SYSTEM_DATA_CORE): el panel por defecto es `lovelace`.
        self.ws.set("frontend/get_system_data", FAKE_SYSTEM_DATA_CORE)

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
        # Cuando lovelace/dashboards/list falla, se devuelve al menos el
        # dashboard default (degraded graceful).
        self.ws.set("lovelace/dashboards/list", HAConnectionError("ws down"))
        result = await self.mcp.tools["ha_list_lovelace_dashboards"]()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["is_default"])

    async def test_list_dashboards_uses_registered_ws_command(self) -> None:
        # Regresión: se enviaba `lovelace/dashboards` a secas, que HA nunca
        # registra (StorageCollectionWebsocket solo da de alta
        # `<prefijo>/list|create|update|delete|subscribe`). El resultado era
        # `success: false` y todas las tools de dashboards extra muertas.
        await self.mcp.tools["ha_list_lovelace_dashboards"]()
        self.assertEqual(len(self.ws.calls_for("lovelace/dashboards/list")), 1)
        self.assertEqual(self.ws.calls_for("lovelace/dashboards"), [])

    async def test_list_dashboards_no_duplicate_default_when_lovelace_exists(
        self,
    ) -> None:
        # Regresión C2 (FR-028): desde la migración de HA 2026.2 el dashboard
        # principal es la entrada `lovelace`, y HA redirige `url_path=None` a
        # ella. Añadir además el «Default» sintético lo listaba dos veces, y
        # `lovelace` salía con `is_default: false`.
        self.ws.set(
            "lovelace/dashboards/list", [FAKE_LOVELACE_DASHBOARD, *FAKE_DASHBOARDS]
        )
        result = await self.mcp.tools["ha_list_lovelace_dashboards"]()
        self.assertIsInstance(result, list)
        self.assertNotIn(None, [d.get("url_path") for d in result])
        self.assertEqual(len(result), 1 + len(FAKE_DASHBOARDS))
        by_path = {d["url_path"]: d for d in result}
        self.assertIs(by_path["lovelace"]["is_default"], True)
        self.assertEqual(
            [d for d in result if d["is_default"]], [by_path["lovelace"]]
        )

    async def test_list_dashboards_ws_error_is_logged(self) -> None:
        # El error no puede tragarse en silencio: sin log, un comando WS
        # inexistente pasa por "no hay dashboards extra" durante meses.
        self.ws.set("lovelace/dashboards/list", HAConnectionError("ws down"))
        with capture_logs() as logs:
            await self.mcp.tools["ha_list_lovelace_dashboards"]()
        self.assertIn(
            "lovelace_dashboards_list_failed",
            [entry.get("event") for entry in logs],
        )

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

    # ── Regresión M-3 (revisión de 1.1.0): dashboards que solo se leen por
    # vistas no pierden sus claves de nivel superior al guardarse. ─────────────

    _GRANDE = {
        "title": "Casa ficticia",
        "background": "var(--fondo-ficticio)",
        "kiosk_mode": {"hide_header": True},
        "views": [
            {"title": f"Vista {i}", "cards": [{"type": "markdown", "content": "x" * 400}]}
            for i in range(4)
        ],
    }

    def _mcp_tope(self, tope: int) -> Any:
        mod2 = __import__("hermes.tools.lovelace", fromlist=["register"])
        mcp = DummyMCP()
        mod2.register(mcp, self.ha_client, response_max_bytes=tope)
        return mcp

    async def test_too_large_y_view_index_traen_claves_superiores(self) -> None:
        self.ws.set("lovelace/config", self._GRANDE)
        mcp = self._mcp_tope(1024)
        grande = await mcp.tools["ha_get_lovelace_dashboard"]()
        self.assertEqual(grande["error"], "too_large")
        esperado = {"title": "Casa ficticia", "background": "var(--fondo-ficticio)",
                    "kiosk_mode": {"hide_header": True}}
        self.assertEqual(grande["top_level"], esperado)
        vista = await mcp.tools["ha_get_lovelace_dashboard"](None, view_index=2)
        self.assertEqual(vista["top_level"], esperado)
        # Con lo que dan las lecturas parciales se reconstruye sin pérdida.
        vistas = [
            (await mcp.tools["ha_get_lovelace_dashboard"](None, view_index=i))["view"]
            for i in range(grande["views_count"])
        ]
        self.assertEqual({**grande["top_level"], "views": vistas}, self._GRANDE)

    async def test_too_large_sin_sitio_para_valores_da_nombres(self) -> None:
        enorme = {**self._GRANDE, "background": "y" * 5000}
        self.ws.set("lovelace/config", enorme)
        res = await self._mcp_tope(1024).tools["ha_get_lovelace_dashboard"]()
        self.assertNotIn("top_level", res)
        self.assertEqual(res["top_level_keys"], ["background", "kiosk_mode", "title"])

    async def test_guardar_sin_claves_superiores_se_niega(self) -> None:
        self.ws.set("lovelace/config", self._GRANDE)
        self.ws.set("lovelace/config/save", None)
        solo_vistas = {"views": self._GRANDE["views"]}
        res = await self.mcp.tools["ha_save_lovelace_dashboard"](None, solo_vistas)
        self.assertEqual(res["error"], "top_level_keys_missing")
        self.assertEqual(res["missing"], ["background", "kiosk_mode", "title"])
        self.assertNotIn("confirmation_token", res)
        self.assertEqual(self.ws.calls_for("lovelace/config/save"), [])

    async def test_guardar_completo_si_emite_token(self) -> None:
        """Control negativo: con todas las claves, la guarda no estorba."""
        self.ws.set("lovelace/config", self._GRANDE)
        res = await self.mcp.tools["ha_save_lovelace_dashboard"](None, dict(self._GRANDE))
        self.assertIn("confirmation_token", res)

    async def test_quitar_claves_a_proposito(self) -> None:
        self.ws.set("lovelace/config", self._GRANDE)
        self.ws.set("lovelace/config/save", None)
        nuevo = {"title": "Casa ficticia", "views": self._GRANDE["views"]}
        quitar = ["kiosk_mode", "background"]
        res = await self.mcp.tools["ha_save_lovelace_dashboard"](
            None, nuevo, remove_top_level_keys=quitar)
        self.assertEqual(res["preview"]["top_level_keys_removed"],
                         ["background", "kiosk_mode"])
        # El token queda atado a la lista: sin ella no vale.
        sin = await self.mcp.tools["ha_save_lovelace_dashboard"](
            None, nuevo, confirmation_token=res["confirmation_token"])
        self.assertIn("error", sin)
        self.assertEqual(self.ws.calls_for("lovelace/config/save"), [])
        res = await self.mcp.tools["ha_save_lovelace_dashboard"](
            None, nuevo, remove_top_level_keys=quitar)
        ok = await self.mcp.tools["ha_save_lovelace_dashboard"](
            None, nuevo, confirmation_token=res["confirmation_token"],
            remove_top_level_keys=quitar)
        self.assertEqual(ok["result"], "ok")

    async def test_lectura_actual_fallida_sin_token(self) -> None:
        self.ws.set("lovelace/config", HAConnectionError("ws down"))
        res = await self.mcp.tools["ha_save_lovelace_dashboard"](
            None, {"views": []})
        self.assertEqual(res["error"], "preview_unavailable")
        self.assertNotIn("confirmation_token", res)

    async def test_dashboard_sin_config_si_emite_token(self) -> None:
        self.ws.set("lovelace/config",
                    HAConnectionError("No config found.", code="config_not_found"))
        res = await self.mcp.tools["ha_save_lovelace_dashboard"](
            None, {"views": []})
        self.assertIn("confirmation_token", res)

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

    # P3 (FR-025…FR-027): el dashboard principal nunca se borra. Desde la
    # migración de HA 2026.2 es la entrada `lovelace` de la colección (y
    # `lovelace/dashboards/delete` la acepta), y el panel por defecto puede ser
    # otro dashboard. Ninguna respuesta de rechazo lleva token.

    def _assert_rejected(self, result: Any, error: str) -> None:
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("error"), error)
        self.assertNotIn("confirmation_token", result)
        self.assertEqual(self.ws.calls_for("lovelace/dashboards/delete"), [])

    async def test_delete_lovelace_rejected_without_token(self) -> None:
        self.ws.set(
            "lovelace/dashboards/list", [FAKE_LOVELACE_DASHBOARD, *FAKE_DASHBOARDS]
        )
        self.ws.set("lovelace/dashboards/delete", None)
        result = await self.mcp.tools["ha_delete_lovelace_dashboard"]("lovelace")
        self._assert_rejected(result, "cannot_delete_default_dashboard")

    async def test_delete_lovelace_rejected_with_any_token(self) -> None:
        # La guarda va antes de mirar el token: ningún token sirve para
        # saltársela.
        self.ws.set(
            "lovelace/dashboards/list", [FAKE_LOVELACE_DASHBOARD, *FAKE_DASHBOARDS]
        )
        self.ws.set("lovelace/dashboards/delete", None)
        result = await self.mcp.tools["ha_delete_lovelace_dashboard"](
            "lovelace", confirmation_token="cualquiera"
        )
        self._assert_rejected(result, "cannot_delete_default_dashboard")

    async def test_delete_lovelace_rejected_even_without_system_data(self) -> None:
        # `lovelace` se protege aunque HA no tenga `frontend/get_system_data`.
        self.ws.set(
            "lovelace/dashboards/list", [FAKE_LOVELACE_DASHBOARD, *FAKE_DASHBOARDS]
        )
        self.ws.set(
            "frontend/get_system_data",
            HAConnectionError("Unknown command.", code="unknown_command"),
        )
        result = await self.mcp.tools["ha_delete_lovelace_dashboard"]("lovelace")
        self._assert_rejected(result, "cannot_delete_default_dashboard")

    async def test_delete_default_panel_dashboard_rejected(self) -> None:
        # El usuario eligió `map` como panel por defecto: es su dashboard
        # principal y se protege igual, con o sin token.
        self.ws.set("frontend/get_system_data", {"value": {"default_panel": "map"}})
        self.ws.set("lovelace/dashboards/delete", None)
        result = await self.mcp.tools["ha_delete_lovelace_dashboard"]("map")
        self._assert_rejected(result, "cannot_delete_default_dashboard")
        result = await self.mcp.tools["ha_delete_lovelace_dashboard"](
            "map", confirmation_token="cualquiera"
        )
        self._assert_rejected(result, "cannot_delete_default_dashboard")

    async def test_delete_rejected_when_default_panel_read_fails(self) -> None:
        # Fail-closed (FR-026): si no se sabe cuál es el panel por defecto,
        # no se borra ningún dashboard.
        self.ws.set("lovelace/dashboards/delete", None)
        for failure in (
            HAConnectionError("ws down"),
            HAConnectionError("Unauthorized", code="unauthorized"),
        ):
            for token in (None, "cualquiera"):
                with self.subTest(failure=str(failure), token=token):
                    self.ws.set("frontend/get_system_data", failure)
                    result = await self.mcp.tools["ha_delete_lovelace_dashboard"](
                        "map", confirmation_token=token
                    )
                    self._assert_rejected(result, "default_panel_unknown")

    async def test_delete_rejected_when_default_panel_shape_unexpected(self) -> None:
        for response in (
            None,
            [],
            "lovelace",
            {},
            {"value": ["lovelace"]},
            {"value": "lovelace"},
            {"value": {"default_panel": 42}},
            {"value": {"default_panel": ["map"]}},
        ):
            with self.subTest(response=response):
                self.ws.set("frontend/get_system_data", response)
                result = await self.mcp.tools["ha_delete_lovelace_dashboard"]("map")
                self._assert_rejected(result, "default_panel_unknown")

    async def test_delete_allowed_when_core_data_has_no_default_panel(self) -> None:
        # `value: None` (nadie escribió `core`) o `core` sin `default_panel`
        # son formas reales de HA: el frontend usa entonces `lovelace`, que ya
        # está protegido, así que un dashboard extra se puede borrar.
        for response in (
            {"value": None},
            {"value": {}},
            {"value": {"default_panel": None}},
        ):
            with self.subTest(response=response):
                self.ws.set("frontend/get_system_data", response)
                result = await self.mcp.tools["ha_delete_lovelace_dashboard"]("map")
                self.assertIn("confirmation_token", result)

    async def test_delete_extra_allowed_with_unknown_command(self) -> None:
        # HA anterior a 2025.12: sin `frontend/get_system_data` no hay panel
        # por defecto configurable; basta con proteger `null` y `lovelace`, y
        # un dashboard extra se borra con el flujo de token normal.
        self.ws.set(
            "frontend/get_system_data",
            HAConnectionError("Unknown command.", code="unknown_command"),
        )
        self.ws.set("lovelace/dashboards/delete", None)
        token_resp = await self.mcp.tools["ha_delete_lovelace_dashboard"]("map")
        self.assertIn("confirmation_token", token_resp)
        result = await self.mcp.tools["ha_delete_lovelace_dashboard"](
            "map", confirmation_token=token_resp["confirmation_token"]
        )
        self.assertEqual(result.get("result"), "ok")
        self.assertEqual(len(self.ws.calls_for("lovelace/dashboards/delete")), 1)

    async def test_delete_reads_default_panel_from_core_system_data(self) -> None:
        await self.mcp.tools["ha_delete_lovelace_dashboard"]("map")
        calls = self.ws.calls_for("frontend/get_system_data")
        self.assertTrue(calls)
        self.assertEqual(calls[0].get("key"), "core")

    async def test_dashboard_docstrings_name_protected_dashboards(self) -> None:
        # FR-027: las descripciones dicen qué se protege y por qué, no solo
        # «el default».
        for name in ("ha_delete_lovelace_dashboard", "ha_list_lovelace_dashboards"):
            with self.subTest(tool=name):
                doc = self.mcp.tools[name].__doc__ or ""
                self.assertIn("`lovelace`", doc)
                self.assertIn("default_panel", doc)
                self.assertIn("2026.2", doc)

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

    async def test_list_resources_uses_current_ws_command(self) -> None:
        # Regresión (FR-029): `lovelace/resources` a secas es un alias que HA
        # anunció retirar en 2025.1; `lovelace/resources/list` existe en modo
        # storage y en modo YAML.
        await self.mcp.tools["ha_list_lovelace_resources"]()
        self.assertEqual(len(self.ws.calls_for("lovelace/resources/list")), 1)
        self.assertEqual(self.ws.calls_for("lovelace/resources"), [])

    async def test_list_resources_ws_error(self) -> None:
        self.ws.set("lovelace/resources/list", HAConnectionError("ws error"))
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

    def test_create_resource_doc_uses_marketplace_path(self) -> None:
        # Desde HA 2026.11 el Marketplace sirve los recursos en
        # `/local/community/`; el ejemplo con `/hacsfiles/` llevaba al agente a
        # la ruta antigua (FR-023).
        doc = self.mcp.tools["ha_create_lovelace_resource"].__doc__ or ""
        self.assertIn("/local/community/", doc)

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


def _dashboard_ficticio(bytes_minimos: int) -> dict[str, Any]:
    """Dashboard ficticio de al menos `bytes_minimos` bytes en JSON."""
    vistas: list[dict[str, Any]] = []
    doc: dict[str, Any] = {"views": vistas}
    i = 0
    while len(json.dumps(doc)) < bytes_minimos:
        vistas.append({
            "title": f"Vista ficticia {i}",
            "path": f"vista-{i}",
            "cards": [
                {"type": "markdown", "content": f"Texto ficticio {i} " * 40},
                {"type": "entities", "entities": [f"light.ficticia_{i}_{j}" for j in range(8)]},
            ],
        })
        i += 1
    return doc


class TestConfirmarSoloConTokenLovelace(unittest.IsolatedAsyncioTestCase):
    """`ha_save_lovelace_dashboard` se confirma sin reenviar `config` (spec 007).

    En las pruebas en vivo de la 1.1.1, la confirmación de un dashboard de
    41 KB llegó a los 104 s de la vista previa y el token (60 s) ya había
    caducado: por encima de unos 20–25 KB era imposible guardar. Ahora la
    vista previa guarda `config` en el servidor y basta con `url_path` y el
    token.

    Control negativo comprobado: con `lovelace.py` de 1.1.1 (`config`
    obligatorio y `validate_confirmation_token`) caen todos los de esta clase
    salvo el de reenviar todo, que es justo la compatibilidad con 1.1.1; con
    `resolve_confirmation_token` tomando lo guardado aunque se envíe otro
    `config`, cae el de config distinto; si el hash deja fuera el destino,
    caen los dos de otro destino.
    """

    asyncSetUp = TestToolsLovelace.asyncSetUp
    asyncTearDown = TestToolsLovelace.asyncTearDown

    async def _guardar(self, *args: Any, **kwargs: Any) -> Any:
        return await self.mcp.tools["ha_save_lovelace_dashboard"](*args, **kwargs)

    async def _guarda_grande_sin_config(self, url_path: str | None, tam: int) -> None:
        self.ws.set("lovelace/config/save", None)
        doc = _dashboard_ficticio(tam)
        self.assertGreaterEqual(len(json.dumps(doc)), tam)
        r = await self._guardar(url_path, doc)
        token = r["confirmation_token"]
        self.assertEqual(r["omit_on_confirm"], ["config"])
        # SC-001: lo que se escribe para confirmar no depende del tamaño.
        confirmacion = {"url_path": url_path, "confirmation_token": token}
        self.assertLess(len(json.dumps(confirmacion)), 1024)
        res = await self._guardar(**confirmacion)
        self.assertEqual(res, {"result": "ok", "url_path": url_path})
        guardados = self.ws.calls_for("lovelace/config/save")
        self.assertEqual(len(guardados), 1)
        # Byte a byte: el documento de la vista previa, no una copia parecida.
        self.assertEqual(json.dumps(guardados[0]["config"]), json.dumps(doc))
        if url_path is None:
            self.assertNotIn("url_path", guardados[0])
        else:
            self.assertEqual(guardados[0]["url_path"], url_path)

    async def test_dashboard_de_41_kb_sin_reenviar_config(self) -> None:
        await self._guarda_grande_sin_config("map", 41 * 1024)

    async def test_dashboard_de_1_mb_sin_reenviar_config(self) -> None:
        await self._guarda_grande_sin_config("map", 1024 * 1024)

    async def test_dashboard_principal_url_path_null(self) -> None:
        """`null` es el dashboard principal, un destino, no una omisión."""
        await self._guarda_grande_sin_config(None, 41 * 1024)

    async def test_confirmar_reenviando_todo_sigue_funcionando(self) -> None:
        self.ws.set("lovelace/config/save", None)
        config = {"views": [{"title": "Ficticia", "cards": []}]}
        r = await self._guardar("map", config)
        res = await self._guardar("map", config, confirmation_token=r["confirmation_token"])
        self.assertEqual(res["result"], "ok")
        self.assertEqual(self.ws.calls_for("lovelace/config/save")[0]["config"], config)

    async def test_sin_token_y_sin_config_es_invalid_argument(self) -> None:
        res = await self._guardar("map")
        self.assertEqual(res["error"], "invalid_argument")
        self.assertEqual(res["field"], "config")
        self.assertNotIn("confirmation_token", res)
        self.assertEqual(self.ws.calls_for("lovelace/config"), [])
        self.assertEqual(list(security.CONFIRMATIONS_DIR.glob("*.json")), [])

    async def test_modo_yaml_se_rechaza_al_confirmar_sin_config(self) -> None:
        self.ws.set("lovelace/config/save", None)
        r = await security.create_confirmation_token(
            "ha_save_lovelace_dashboard",
            {"url_path": "yaml-dash", "config": {"views": []}},
            omitibles=("config",),
        )
        res = await self._guardar("yaml-dash", confirmation_token=r["confirmation_token"])
        self.assertEqual(res["error"], "yaml_mode")
        self.assertEqual(self.ws.calls_for("lovelace/config/save"), [])

    async def test_vista_previa_dice_como_confirmar(self) -> None:
        r = await self._guardar("map", {"views": [{"title": "Ficticia", "cards": []}]})
        self.assertEqual(r["confirm_with"], ["confirmation_token", "url_path"])
        self.assertEqual(r["omit_on_confirm"], ["config"])
        self.assertEqual(
            r["confirm_hint"],
            "To confirm, call ha_save_lovelace_dashboard again with only "
            "confirmation_token, url_path. config can be omitted: the server "
            "kept the one from this preview. Any argument you do send must be "
            "identical to the preview.",
        )

    async def test_vista_previa_con_remove_top_level_keys(self) -> None:
        self.ws.set("lovelace/config", TestToolsLovelace._GRANDE)
        self.ws.set("lovelace/config/save", None)
        nuevo = {"title": "Casa ficticia", "views": TestToolsLovelace._GRANDE["views"]}
        quitar = ["background", "kiosk_mode"]
        r = await self._guardar(None, nuevo, remove_top_level_keys=quitar)
        self.assertEqual(
            r["confirm_with"],
            ["confirmation_token", "remove_top_level_keys", "url_path"],
        )
        # Sin la lista no vale: no es omitible.
        sin = await self._guardar(None, confirmation_token=r["confirmation_token"])
        self.assertEqual(sin, {"error": "confirmation_token does not match this action."})
        ok = await self._guardar(None, confirmation_token=r["confirmation_token"],
                                 remove_top_level_keys=quitar)
        self.assertEqual(ok["result"], "ok")
        self.assertEqual(self.ws.calls_for("lovelace/config/save")[0]["config"], nuevo)

    # ── SC-002: ningún token ejecuta otra cosa ─────────────────────────────────

    async def _token_panel_a(self) -> tuple[str, dict[str, Any]]:
        self.ws.set("lovelace/config/save", None)
        config = {"views": [{"title": "Panel A ficticio", "cards": []}]}
        r = await self._guardar("panel-a", config)
        return r["confirmation_token"], config

    async def _sigue_sirviendo(self, token: str) -> None:
        self.assertEqual(self.ws.calls_for("lovelace/config/save"), [])
        ok = await self._guardar("panel-a", confirmation_token=token)
        self.assertEqual(ok["result"], "ok")
        self.assertEqual(
            self.ws.calls_for("lovelace/config/save")[0]["url_path"], "panel-a")

    async def test_otro_destino_sin_config_no_vale(self) -> None:
        token, _ = await self._token_panel_a()
        res = await self._guardar("panel-b", confirmation_token=token)
        self.assertEqual(res, {"error": "confirmation_token does not match this action."})
        await self._sigue_sirviendo(token)

    async def test_otro_destino_con_config_no_vale(self) -> None:
        token, config = await self._token_panel_a()
        res = await self._guardar("panel-b", config, confirmation_token=token)
        self.assertEqual(res, {"error": "confirmation_token does not match this action."})
        await self._sigue_sirviendo(token)

    async def test_config_distinto_no_vale(self) -> None:
        token, _ = await self._token_panel_a()
        otro = {"views": [{"title": "Otro panel ficticio", "cards": []}]}
        res = await self._guardar("panel-a", otro, confirmation_token=token)
        self.assertEqual(res, {"error": "confirmation_token does not match this action."})
        await self._sigue_sirviendo(token)

    async def test_argumento_anadido_no_vale(self) -> None:
        token, _ = await self._token_panel_a()
        res = await self._guardar("panel-a", confirmation_token=token,
                                  remove_top_level_keys=["title"])
        self.assertEqual(res, {"error": "confirmation_token does not match this action."})
        await self._sigue_sirviendo(token)


# ── Spec 018: guardado por vista (US1) ────────────────────────────────────────


def _dashboard_tres_vistas() -> dict[str, Any]:
    """Dashboard ficticio de tres vistas (T002 de la 018).

    `Inicio` sin `path`, `Cocina` con `path` y tarjetas, `Jardín` de tipo
    `sections`; claves de nivel superior `title` y `background`. Nuevo en cada
    llamada, para que un test pueda cambiarlo sin afectar a los demás. El
    `FakeWSSender` ya guarda cada `lovelace/config/save` recibido y su `set`
    cambia el documento devuelto entre llamadas.
    """
    return {
        "title": "Casa ficticia",
        "background": "var(--fondo-ficticio)",
        "views": [
            {"title": "Inicio", "cards": [{"type": "markdown", "content": "hola"}]},
            {
                "title": "Cocina",
                "path": "cocina",
                "badges": [{"entity": "sensor.temperatura_cocina"}],
                "cards": [
                    {"type": "light", "entity": "light.salon"},
                    {"type": "entities", "entities": ["light.cocina"]},
                ],
            },
            {
                "title": "Jardín",
                "path": "jardin",
                "type": "sections",
                "sections": [
                    {"type": "grid", "cards": [{"type": "tile", "entity": "light.jardin"}]},
                ],
            },
        ],
    }


class TestGuardarPorVista(unittest.IsolatedAsyncioTestCase):
    """`ha_save_lovelace_dashboard` con `view_index` y `view` (spec 018,
    FR-001…FR-006 y FR-018).

    Guardar una vista sustituye solo esa vista del dashboard ACTUAL; lo demás
    queda igual. El token se ata al estado del dashboard: si cambia entre la
    vista previa y la confirmación, `dashboard_changed` y nada guardado.

    Control negativo comprobado (T011):
    (a) fusionar sustituyendo `views` entera por `[view]` → caen las
        comprobaciones de vistas conservadas;
    (b) no pasar `estado` al resolver → caen los de `dashboard_changed`;
    (c) aceptar `config` junto a `view_index` → cae su caso;
    (d) sacar `view` de los omitibles → caen `omit_on_confirm` y la
        confirmación sin `view`;
    (e) una sola tupla `("config", "view")` para los dos modos → caen los de
        `TestConfirmarSoloConTokenLovelace` y el de compatibilidad de aquí.
    Los recuentos exactos van en el mensaje del commit.
    """

    asyncSetUp_base = TestToolsLovelace.asyncSetUp
    asyncTearDown = TestToolsLovelace.asyncTearDown

    URL = "panel-prueba"

    async def asyncSetUp(self) -> None:
        await self.asyncSetUp_base()
        self.actual = _dashboard_tres_vistas()
        self.ws.set("lovelace/config", self.actual)
        self.ws.set("lovelace/config/save", None)
        self.nueva = {
            "title": "Cocina",
            "path": "cocina",
            "cards": [
                {"type": "light", "entity": "light.salon"},
                {"type": "entities", "entities": ["light.cocina"]},
                {"type": "markdown", "content": "nueva"},
            ],
        }

    async def _guardar(self, *args: Any, **kwargs: Any) -> Any:
        return await self.mcp.tools["ha_save_lovelace_dashboard"](*args, **kwargs)

    async def _vista_previa(self, view_index: int = 1, view: Any = None) -> dict:
        return await self._guardar(
            self.URL, view_index=view_index,
            view=self.nueva if view is None else view)

    def _sin_token_ni_guardado(self, res: Any) -> None:
        self.assertNotIn("confirmation_token", res)
        self.assertEqual(self.ws.calls_for("lovelace/config/save"), [])
        self.assertEqual(list(security.CONFIRMATIONS_DIR.glob("*.json")), [])

    # ── Vista previa ──────────────────────────────────────────────────────────

    async def test_vista_previa(self) -> None:
        r = await self._vista_previa()
        p = r["preview"]
        self.assertEqual(p["url_path"], self.URL)
        self.assertEqual(p["mode"], "single_view")
        self.assertEqual(p["view_index"], 1)
        self.assertEqual(p["views_total"], 3)
        self.assertEqual(p["view_before"], {"title": "Cocina", "path": "cocina",
                                            "type": None, "cards": 2, "badges": 1,
                                            "sections": 0})
        self.assertEqual(p["view_after"], {"title": "Cocina", "path": "cocina",
                                           "type": None, "cards": 3, "badges": 0,
                                           "sections": 0})
        self.assertIs(p["view_unchanged"], False)
        self.assertEqual(p["views_kept"], [
            {"index": 0, "title": "Inicio", "path": None},
            {"index": 2, "title": "Jardín", "path": "jardin"},
        ])
        self.assertEqual(p["top_level_keys_kept"], ["background", "title"])
        self.assertEqual(p["diff"]["views_count_before"], 3)
        self.assertEqual(p["diff"]["views_count_after"], 3)
        self.assertEqual(p["diff"]["total_cards_badges_before"], 5)
        self.assertEqual(p["diff"]["total_cards_badges_after"], 5)
        self.assertIn("Only view 1 is replaced", p["warning"])
        self.assertIn("refused", p["warning"])
        self.assertEqual(r["confirm_with"],
                         ["confirmation_token", "url_path", "view_index"])
        self.assertEqual(r["omit_on_confirm"], ["view"])
        self.assertIn("view can be omitted", r["confirm_hint"])
        self.assertEqual(self.ws.calls_for("lovelace/config/save"), [])
        # Nunca el JSON de la vista en la vista previa: solo recuentos.
        self.assertNotIn("nueva", json.dumps(r))

    async def test_vista_de_secciones_en_el_resumen(self) -> None:
        r = await self._vista_previa(2, {"title": "Jardín", "type": "sections",
                                         "sections": []})
        self.assertEqual(r["preview"]["view_before"],
                         {"title": "Jardín", "path": "jardin", "type": "sections",
                          "cards": 1, "badges": 0, "sections": 1})
        self.assertEqual([v["index"] for v in r["preview"]["views_kept"]], [0, 1])

    async def test_titulos_largos_se_recortan(self) -> None:
        self.actual["views"][0]["title"] = "T" * 200
        r = await self._vista_previa()
        self.assertEqual(r["preview"]["views_kept"][0]["title"], "T" * 80)

    async def test_vista_identica_dice_view_unchanged(self) -> None:
        r = await self._vista_previa(1, json.loads(json.dumps(self.actual["views"][1])))
        self.assertIs(r["preview"]["view_unchanged"], True)
        self.assertIn("confirmation_token", r)

    # ── Confirmación ──────────────────────────────────────────────────────────

    def _comprobar_guardado(self, vista: dict) -> None:
        guardados = self.ws.calls_for("lovelace/config/save")
        self.assertEqual(len(guardados), 1)
        self.assertEqual(guardados[0]["url_path"], self.URL)
        doc = guardados[0]["config"]
        original = _dashboard_tres_vistas()
        self.assertEqual(doc["views"][1], vista)
        # Lo demás, idéntico: vistas 0 y 2 y las claves de nivel superior.
        self.assertEqual(len(doc["views"]), 3)
        self.assertEqual(doc["views"][0], original["views"][0])
        self.assertEqual(doc["views"][2], original["views"][2])
        self.assertEqual({k: v for k, v in doc.items() if k != "views"},
                         {k: v for k, v in original.items() if k != "views"})

    async def test_confirmar_sin_reenviar_view(self) -> None:
        r = await self._vista_previa()
        res = await self._guardar(self.URL, view_index=1,
                                  confirmation_token=r["confirmation_token"])
        self.assertEqual(res, {"result": "ok", "url_path": self.URL, "view_index": 1})
        self._comprobar_guardado(self.nueva)

    async def test_confirmar_reenviando_view_identica(self) -> None:
        r = await self._vista_previa()
        res = await self._guardar(self.URL, view_index=1, view=dict(self.nueva),
                                  confirmation_token=r["confirmation_token"])
        self.assertEqual(res["result"], "ok")
        self._comprobar_guardado(self.nueva)

    async def test_confirmar_con_otra_view_no_vale(self) -> None:
        r = await self._vista_previa()
        otra = {"title": "Otra vista ficticia", "cards": []}
        res = await self._guardar(self.URL, view_index=1, view=otra,
                                  confirmation_token=r["confirmation_token"])
        self.assertEqual(res, {"error": "confirmation_token does not match this action."})
        self.assertEqual(self.ws.calls_for("lovelace/config/save"), [])

    async def test_confirmar_con_otro_indice_no_vale(self) -> None:
        r = await self._vista_previa()
        res = await self._guardar(self.URL, view_index=0,
                                  confirmation_token=r["confirmation_token"])
        self.assertEqual(res, {"error": "confirmation_token does not match this action."})
        self.assertEqual(self.ws.calls_for("lovelace/config/save"), [])

    async def _cambiado(self, cambiar) -> None:
        r = await self._vista_previa()
        cambiado = _dashboard_tres_vistas()
        cambiar(cambiado)
        self.ws.set("lovelace/config", cambiado)
        res = await self._guardar(self.URL, view_index=1,
                                  confirmation_token=r["confirmation_token"])
        self.assertEqual(res["error"], "dashboard_changed")
        self.assertEqual(res["url_path"], self.URL)
        self.assertEqual(res["view_index"], 1)
        self.assertIn("detail", res)
        self.assertEqual(self.ws.calls_for("lovelace/config/save"), [])
        # El token no se gastó: con el dashboard de la vista previa, vale.
        self.ws.set("lovelace/config", _dashboard_tres_vistas())
        ok = await self._guardar(self.URL, view_index=1,
                                 confirmation_token=r["confirmation_token"])
        self.assertEqual(ok["result"], "ok")

    async def test_otra_vista_cambiada_da_dashboard_changed(self) -> None:
        def cambiar(d: dict) -> None:
            d["views"][0]["cards"].append({"type": "markdown", "content": "otro"})
        await self._cambiado(cambiar)

    async def test_clave_superior_cambiada_da_dashboard_changed(self) -> None:
        def cambiar(d: dict) -> None:
            d["title"] = "Otro título ficticio"
        await self._cambiado(cambiar)

    async def test_vista_insertada_antes_da_dashboard_changed(self) -> None:
        def cambiar(d: dict) -> None:
            d["views"].insert(0, {"title": "Nueva primera"})
        await self._cambiado(cambiar)

    async def test_lectura_fallida_al_confirmar_deja_el_token(self) -> None:
        r = await self._vista_previa()
        self.ws.set("lovelace/config", HAConnectionError("ws down"))
        res = await self._guardar(self.URL, view_index=1,
                                  confirmation_token=r["confirmation_token"])
        self.assertEqual(res, {"error": "ws down"})
        self.assertEqual(self.ws.calls_for("lovelace/config/save"), [])
        datos = json.loads((security.CONFIRMATIONS_DIR /
                            f"{r['confirmation_token']}.json").read_text(encoding="utf-8"))
        self.assertEqual(datos["state"], "pending")

    async def test_fallo_de_ha_al_guardar(self) -> None:
        r = await self._vista_previa()
        self.ws.set("lovelace/config/save", HAConnectionError("save failed"))
        res = await self._guardar(self.URL, view_index=1,
                                  confirmation_token=r["confirmation_token"])
        self.assertEqual(res, {"error": "save failed"})
        otra = await self._guardar(self.URL, view_index=1,
                                   confirmation_token=r["confirmation_token"])
        self.assertIn("error", otra)
        self.assertEqual(len(self.ws.calls_for("lovelace/config/save")), 1)

    # ── Tokens cruzados entre los dos modos ───────────────────────────────────

    async def test_token_completo_no_vale_por_vista(self) -> None:
        r = await self._guardar(self.URL, _dashboard_tres_vistas())
        res = await self._guardar(self.URL, view_index=1, view=self.nueva,
                                  confirmation_token=r["confirmation_token"])
        self.assertEqual(res, {"error": "confirmation_token does not match this action."})
        res = await self._guardar(self.URL, view_index=1,
                                  confirmation_token=r["confirmation_token"])
        self.assertIn("error", res)
        self.assertEqual(self.ws.calls_for("lovelace/config/save"), [])

    async def test_token_por_vista_no_vale_completo(self) -> None:
        r = await self._vista_previa()
        res = await self._guardar(self.URL, confirmation_token=r["confirmation_token"])
        self.assertIn("error", res)
        res = await self._guardar(self.URL, _dashboard_tres_vistas(),
                                  confirmation_token=r["confirmation_token"])
        self.assertEqual(res, {"error": "confirmation_token does not match this action."})
        self.assertEqual(self.ws.calls_for("lovelace/config/save"), [])

    # ── Errores sin token ni escritura ────────────────────────────────────────

    async def _error(self, codigo: str, *args: Any, campo: str | None = None,
                     **kwargs: Any) -> dict:
        res = await self._guardar(*args, **kwargs)
        self.assertEqual(res["error"], codigo, res)
        if campo is not None:
            self.assertEqual(res["field"], campo)
        self._sin_token_ni_guardado(res)
        return res

    async def test_mezclas_se_rechazan_sin_leer(self) -> None:
        await self._error("invalid_argument", self.URL, _dashboard_tres_vistas(),
                          view_index=1, view=self.nueva, campo="config")
        await self._error("invalid_argument", self.URL, view_index=1, view=self.nueva,
                          remove_top_level_keys=["title"], campo="remove_top_level_keys")
        await self._error("invalid_argument", self.URL, view=self.nueva,
                          campo="view_index")
        await self._error("invalid_argument", self.URL, view_index=1, campo="view")
        # FR-005: las mezclas, antes de leer el dashboard.
        self.assertEqual(self.ws.calls_for("lovelace/config"), [])
        self.assertEqual(self.ws.calls_for("lovelace/dashboards/list"), [])

    async def test_view_invalida(self) -> None:
        await self._error("invalid_argument", self.URL, view_index=1, view=["x"],
                          campo="view")
        await self._error("invalid_argument", self.URL, view_index=1,
                          view={"views": [self.nueva]}, campo="view")
        await self._error("invalid_argument", self.URL, view_index=True,
                          view=self.nueva, campo="view_index")
        await self._error("invalid_argument", self.URL, view_index="1",
                          view=self.nueva, campo="view_index")

    async def test_indice_fuera_de_rango(self) -> None:
        for indice in (-1, 3):
            res = await self._error("view_index_out_of_range", self.URL,
                                    view_index=indice, view=self.nueva)
            self.assertEqual(res["views_count"], 3)
            self.assertEqual(res["requested"], indice)

    async def test_sin_configuracion_es_no_views(self) -> None:
        self.ws.set("lovelace/config",
                    HAConnectionError("No config found.", code="config_not_found"))
        await self._error("no_views", self.URL, view_index=0, view=self.nueva)

    async def test_estrategia_es_no_views(self) -> None:
        self.ws.set("lovelace/config", FAKE_MAP_CONFIG)
        await self._error("no_views", self.URL, view_index=0, view=self.nueva)

    async def test_modo_yaml(self) -> None:
        await self._error("yaml_mode", "yaml-dash", view_index=0, view=self.nueva)

    async def test_lectura_fallida_es_preview_unavailable(self) -> None:
        self.ws.set("lovelace/config", HAConnectionError("ws down"))
        await self._error("preview_unavailable", self.URL, view_index=1, view=self.nueva)

    # ── Tope de guardados, log y compatibilidad ───────────────────────────────

    async def test_tope_lleno_pide_reenviar_view(self) -> None:
        import unittest.mock as mock

        with mock.patch.object(security, "CONFIRMATION_STORED_MAX_BYTES", 10):
            r = await self._vista_previa()
        self.assertEqual(r["confirm_with"],
                         ["confirmation_token", "url_path", "view", "view_index"])
        self.assertNotIn("omit_on_confirm", r)
        sin = await self._guardar(self.URL, view_index=1,
                                  confirmation_token=r["confirmation_token"])
        self.assertIn("no stored value for: view", sin["error"])
        ok = await self._guardar(self.URL, view_index=1, view=self.nueva,
                                 confirmation_token=r["confirmation_token"])
        self.assertEqual(ok["result"], "ok")

    async def test_el_contenido_de_la_vista_no_llega_al_log(self) -> None:
        centinela = "CENTINELA-VISTA-3b7e"
        vista = {"title": "Cocina", "cards": [{"type": "markdown", "content": centinela}]}
        with capture_logs() as logs:
            r = await self._vista_previa(1, vista)
            await self._guardar(self.URL, view_index=0,
                                confirmation_token=r["confirmation_token"])
            ok = await self._guardar(self.URL, view_index=1,
                                     confirmation_token=r["confirmation_token"])
        self.assertEqual(ok["result"], "ok")
        evento = [e for e in logs if e["event"] == "ha_save_lovelace_dashboard_view_ok"]
        self.assertEqual(len(evento), 1)
        self.assertEqual(evento[0]["url_path"], self.URL)
        self.assertEqual(evento[0]["view_index"], 1)
        self.assertNotIn(centinela, repr(logs))

    async def test_compatibilidad_guardado_completo_de_la_1_1_2(self) -> None:
        """FR-006: sin `view_index` ni `view`, la vista previa es la de la
        1.1.2 (salvo el token), el token no se ata al estado y la
        confirmación sin `config` funciona.

        Control negativo comprobado: con una sola tupla de omitibles
        `("config", "view")` para los dos modos, la confirmación sin `config`
        se rechaza («has no stored value for: view») y cae este test.
        """
        nuevo = _dashboard_tres_vistas()
        nuevo["views"].append({"title": "Cuarta", "cards": []})
        r = await self._guardar(self.URL, nuevo)
        token = r.pop("confirmation_token")
        self.assertEqual(r, {
            "expires_in_seconds": 60,
            "preview": {
                "url_path": self.URL,
                "diff": {
                    "views_count_before": 3, "views_count_after": 4,
                    "total_cards_badges_before": 5, "total_cards_badges_after": 5,
                    "theme_changed": False, "title_changed": False,
                    "has_strategy": False,
                },
                "warning": "This replaces the ENTIRE dashboard configuration.",
            },
            "confirm_with": ["confirmation_token", "url_path"],
            "omit_on_confirm": ["config"],
            "confirm_hint": (
                "To confirm, call ha_save_lovelace_dashboard again with only "
                "confirmation_token, url_path. config can be omitted: the server "
                "kept the one from this preview. Any argument you do send must be "
                "identical to the preview."
            ),
        })
        datos = json.loads((security.CONFIRMATIONS_DIR / f"{token}.json")
                           .read_text(encoding="utf-8"))
        self.assertNotIn("state_hash", datos)
        # Aunque el dashboard cambie, el guardado completo no se ata al estado
        # (last-write-wins de la 1.1.2).
        self.ws.set("lovelace/config", {"views": []})
        res = await self._guardar(self.URL, confirmation_token=token)
        self.assertEqual(res, {"result": "ok", "url_path": self.URL})
        self.assertEqual(self.ws.calls_for("lovelace/config/save")[0]["config"], nuevo)
