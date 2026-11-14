"""Tests de los alias deprecados `ha_hacs_*` (spec 004, lote B; FR-021, FR-022).

Desde HA 2026.11 HACS viene integrado como el Marketplace y los comandos
`hacs/*` ya no existen. En 1.0.12 los `ha_hacs_*` respondían
`hacs_moved_to_marketplace`; desde 1.1.0 son alias de las `ha_marketplace_*`:
devuelven lo mismo que su sustituta más `_deprecated`, para que quien los use
siga funcionando y sepa a qué tool pasarse antes de que se retiren en 1.3.0.

Todos los repositorios y entidades son ficticios (`owner/repo`).
"""

from __future__ import annotations

import unittest
from typing import Any

from aiohttp import ClientSession

import hermes.tools.hacs as hacs_mod
import hermes.tools.marketplace as mp
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


def _unknown() -> HAConnectionError:
    return HAConnectionError("HA WS command failed: Unknown command.", code="unknown_command")


# El mismo simulador que los tests del Marketplace: filtra por `categories`
# como HA y falla si se pide el catálogo entero, que en HA 2026.11.1 tumba la
# WebSocket (spec 006). Con uno propio que no lo hiciera, los alias pasarían
# en verde aunque pidieran el catálogo entero.
from tests.test_tools_marketplace import FakeHA  # noqa: E402


_REPOS = [
    {
        "id": "123", "full_name": "owner/repo", "name": "repo", "category": "plugin",
        "description": "A card", "installed": True, "installed_version": "1.0.0",
        "available_version": "1.1.0", "pending_upgrade": True, "can_install": True,
    },
    {
        "id": "456", "full_name": "owner/other", "name": "other", "category": "integration",
        "description": "Not installed", "installed": False, "installed_version": None,
        "available_version": "2.0.0", "pending_upgrade": False, "can_install": True,
    },
]

_MARKETPLACE = {
    "marketplace/info": {"version": "1.0", "categories": ["plugin"], "stage": "running"},
    "marketplace/repositories/list": _REPOS,
    "config/entity_registry/list": [
        {"entity_id": "update.example", "platform": "marketplace", "unique_id": "123"},
    ],
}

# Alias → (sustituta, argumentos mínimos).
_ALIAS = {
    "ha_hacs_info": ("ha_marketplace_info", {}),
    "ha_hacs_list_repositories": ("ha_marketplace_list_repositories", {}),
    "ha_hacs_get_repository": ("ha_marketplace_get_repository", {"repository_id": "123"}),
    "ha_hacs_list_updates": ("ha_marketplace_list_updates", {}),
}


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def _register(self, fake: FakeHA | None) -> DummyMCP:
        client = make_ready_client(self.session, {})
        client.ws_send = fake  # type: ignore[method-assign]
        mcp = DummyMCP()
        mp.register(mcp, client)
        hacs_mod.register(mcp, client)
        return mcp


class TestAliasSameAsMarketplace(_Base):
    async def test_each_alias_returns_its_replacement_plus_deprecated(self) -> None:
        mcp = self._register(FakeHA(dict(_MARKETPLACE)))
        for alias, (nueva, kwargs) in _ALIAS.items():
            with self.subTest(alias=alias):
                esperado = await mcp.tools[nueva](**kwargs)
                obtenido = await mcp.tools[alias](**kwargs)
                self.assertNotIn("error", obtenido)
                self.assertIn(nueva, obtenido["_deprecated"])
                self.assertIn(alias, obtenido["_deprecated"])
                self.assertIn("1.3.0", obtenido["_deprecated"])
                sin_aviso = {k: v for k, v in obtenido.items() if k != "_deprecated"}
                self.assertEqual(sin_aviso, esperado)

    async def test_no_1_0_12_leftovers(self) -> None:
        mcp = self._register(FakeHA(dict(_MARKETPLACE)))
        for alias, (_nueva, kwargs) in _ALIAS.items():
            with self.subTest(alias=alias):
                texto = str(await mcp.tools[alias](**kwargs))
                self.assertNotIn("hacs_moved_to_marketplace", texto)
                self.assertNotIn("_disclaimer", texto)

    async def test_list_updates_uses_pending_upgrade(self) -> None:
        mcp = self._register(FakeHA(dict(_MARKETPLACE)))
        result = await mcp.tools["ha_hacs_list_updates"]()
        self.assertEqual([u["id"] for u in result["updates"]], ["123"])
        self.assertEqual(result["updates"][0]["update_entity_id"], "update.example")


class TestAliasErrors(_Base):
    async def test_not_installed_before_2026_11(self) -> None:
        fake = FakeHA({"get_config": {"version": "2026.10.3"}})
        mcp = self._register(fake)
        for alias, (_nueva, kwargs) in _ALIAS.items():
            with self.subTest(alias=alias):
                result = await mcp.tools[alias](**kwargs)
                self.assertEqual(result["error"], "hacs_not_installed")
                self.assertNotIn("update hermes", str(result).lower())
                self.assertIn("_deprecated", result)

    async def test_ws_error_is_reported(self) -> None:
        fake = FakeHA({
            "marketplace/info": HAConnectionError(
                "HA WS command failed: boom", code="home_assistant_error"),
        })
        mcp = self._register(fake)
        result = await mcp.tools["ha_hacs_info"]()
        self.assertEqual(result["error"], "home_assistant_error")
        self.assertIn("boom", result["detail"])


class TestAliasArguments(_Base):
    async def test_list_repositories_accepts_new_arguments(self) -> None:
        fake = FakeHA(dict(_MARKETPLACE))
        mcp = self._register(fake)
        result = await mcp.tools["ha_hacs_list_repositories"](
            category="integration", installed_only=False, search="OTHER", limit=5,
        )
        self.assertEqual([r["full_name"] for r in result["repositories"]], ["owner/other"])
        # HACS y el Marketplace declaran `categories` (lista) con PREVENT_EXTRA:
        # un `category` singular haría que HA rechazara el comando entero.
        enviado = [p for p in fake.sent if p["type"].endswith("repositories/list")][-1]
        self.assertEqual(enviado.get("categories"), ["integration"])
        self.assertNotIn("category", enviado)

    async def test_invalid_category_sends_nothing(self) -> None:
        fake = FakeHA(dict(_MARKETPLACE))
        mcp = self._register(fake)
        result = await mcp.tools["ha_hacs_list_repositories"](category="netdaemon")
        self.assertEqual(result["error"], "invalid_category")
        self.assertEqual(fake.sent, [])


class TestAliasDescriptions(_Base):
    def test_descriptions_say_deprecated(self) -> None:
        mcp = self._register(None)
        for alias, (nueva, _kwargs) in _ALIAS.items():
            with self.subTest(alias=alias):
                doc = mcp.tools[alias].__doc__ or ""
                self.assertTrue(doc.startswith("DEPRECATED"), doc[:60])
                self.assertIn(nueva, doc)
                self.assertIn("1.3.0", doc)

    def test_signatures_match_replacements(self) -> None:
        import inspect

        mcp = self._register(None)
        for alias, (nueva, _kwargs) in _ALIAS.items():
            with self.subTest(alias=alias):
                self.assertEqual(
                    inspect.signature(mcp.tools[alias]).parameters.keys(),
                    inspect.signature(mcp.tools[nueva]).parameters.keys(),
                )


if __name__ == "__main__":
    unittest.main()
