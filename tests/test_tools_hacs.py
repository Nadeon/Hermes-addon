"""Tests de las tools ha_hacs_* (R3 y C5, FR-038 y FR-039).

Desde HA 2026.11 HACS viene integrado como Marketplace y los comandos
`hacs/*` ya no existen: HA responde `unknown_command`. Hermes lo explicaba
como un fallo genérico y sugería actualizar Hermes, que no lo arregla.
"""

from __future__ import annotations

import unittest

from aiohttp import ClientSession

import hermes.tools.hacs as hacs_mod
from hermes.ha import HAConnectionError
from tests._ha_fixture import make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


# Cada tool con los argumentos mínimos para que llegue a hablar con HA.
_LLAMADAS = {
    "ha_hacs_info": {},
    "ha_hacs_list_repositories": {},
    "ha_hacs_get_repository": {"repository_id": "123"},
    "ha_hacs_list_updates": {},
}


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def _register(self, ws_send) -> DummyMCP:
        client = make_ready_client(self.session, {})
        client.ws_send = ws_send  # type: ignore[method-assign]
        mcp = DummyMCP()
        hacs_mod.register(mcp, client)
        return mcp


class TestHacsUnknownCommand(_Base):
    def _mcp_sin_hacs(self, version: str | None) -> DummyMCP:
        """HA sin los comandos `hacs/*`, con `version` (None: no se sabe)."""

        async def fake_ws_send(payload, timeout_seconds=30):
            if payload["type"] == "get_config":
                if version is None:
                    raise HAConnectionError("HA WS command failed: boom")
                return {"version": version}
            raise HAConnectionError(
                "HA WS command failed: Unknown command.", code="unknown_command"
            )

        return self._register(fake_ws_send)

    async def test_marketplace_on_2026_11(self) -> None:
        mcp = self._mcp_sin_hacs("2026.11.1")
        for nombre, kwargs in _LLAMADAS.items():
            with self.subTest(tool=nombre):
                result = await mcp.tools[nombre](**kwargs)
                self.assertEqual(result["error"], "hacs_moved_to_marketplace")
                self.assertIn('ha_get_states(domain="update")', result["hint"])
                self.assertNotIn("update hermes", str(result).lower())

    async def test_not_installed_before_2026_11_or_unknown(self) -> None:
        for version in ("2026.10.3", None):
            mcp = self._mcp_sin_hacs(version)
            for nombre, kwargs in _LLAMADAS.items():
                with self.subTest(tool=nombre, version=version):
                    result = await mcp.tools[nombre](**kwargs)
                    self.assertEqual(result["error"], "hacs_not_installed")
                    self.assertNotIn("update hermes", str(result).lower())

    async def test_other_errors_keep_message(self) -> None:
        async def fake_ws_send(payload, timeout_seconds=30):
            raise HAConnectionError(
                "HA WS command failed: boom", code="home_assistant_error"
            )

        mcp = self._register(fake_ws_send)
        result = await mcp.tools["ha_hacs_info"]()
        self.assertIn("boom", result["error"])


class TestHacsCategories(_Base):
    async def test_template_accepted_netdaemon_rejected(self) -> None:
        enviados: list[dict] = []

        async def fake_ws_send(payload, timeout_seconds=30):
            enviados.append(payload)
            return []

        mcp = self._register(fake_ws_send)
        ok = await mcp.tools["ha_hacs_list_repositories"](category="template")
        self.assertNotIn("error", ok)
        self.assertEqual(enviados[-1]["categories"], ["template"])

        enviados.clear()
        mal = await mcp.tools["ha_hacs_list_repositories"](category="netdaemon")
        self.assertIn("error", mal)
        self.assertEqual(enviados, [])

    async def test_description_lists_real_categories(self) -> None:
        mcp = self._register(None)
        doc = mcp.tools["ha_hacs_list_repositories"].__doc__
        self.assertIn("template", doc)
        self.assertNotIn("netdaemon", doc)


class TestHacsPendingUpgrade(_Base):
    async def test_pending_upgrade_wins_over_version_text(self) -> None:
        """HACS calcula `pending_upgrade` comparando de verdad (commits,
        versiones con prefijo); el texto de las versiones puede coincidir y
        haber actualización, o diferir y no haberla."""
        repos = [
            {
                "id": "1", "name": "a", "installed": True,
                "installed_version": "abc1234", "available_version": "abc1234",
                "pending_upgrade": True,
            },
            {
                "id": "2", "name": "b", "installed": True,
                "installed_version": "v1.0", "available_version": "1.0",
                "pending_upgrade": False,
            },
            {
                # Sin `pending_upgrade`: se sigue comparando el texto.
                "id": "3", "name": "c", "installed": True,
                "installed_version": "1.0", "available_version": "2.0",
            },
        ]

        async def fake_ws_send(payload, timeout_seconds=30):
            return repos

        mcp = self._register(fake_ws_send)
        result = await mcp.tools["ha_hacs_list_updates"]()
        self.assertEqual([u["id"] for u in result["updates"]], ["1", "3"])


if __name__ == "__main__":
    unittest.main()
