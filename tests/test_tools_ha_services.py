"""Tests del filtro `domain` de ha_list_services (D5, FR-035).

La lista completa de servicios ronda los 100 KB en una instalación normal,
más de lo que admiten algunos clientes MCP en una respuesta. Con `domain` se
pide solo lo que hace falta.
"""

from __future__ import annotations

import json
import unittest

from aiohttp import ClientSession

import hermes.tools.ha as ha_tools
from tests._ha_fixture import make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _servicios(dominio: str, n: int) -> dict:
    return {
        f"servicio_{i}": {
            "name": f"Servicio {i}",
            "description": "Descripción larga de relleno " * 4,
            "fields": {"entity_id": {"required": True}},
        }
        for i in range(n)
    }


_SERVICES = [
    {"domain": "light", "services": _servicios("light", 2)},
    {"domain": "switch", "services": _servicios("switch", 15)},
    {"domain": "homeassistant", "services": _servicios("homeassistant", 15)},
]


class TestListServicesDomain(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.client = make_ready_client(self.session, {})

        async def fake_get_services():
            return [dict(item) for item in _SERVICES]

        self.client.get_services = fake_get_services  # type: ignore[method-assign]
        self.mcp = DummyMCP()
        ha_tools.register(self.mcp, self.client)

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_filter_by_domain(self) -> None:
        raw = await self.mcp.tools["ha_list_services"](domain="light")
        result = json.loads(raw)
        self.assertEqual([item["domain"] for item in result], ["light"])
        self.assertEqual(result[0]["services"], _SERVICES[0]["services"])

    async def test_unknown_domain_returns_empty_list(self) -> None:
        raw = await self.mcp.tools["ha_list_services"](domain="no_existe")
        self.assertEqual(json.loads(raw), [])

    async def test_without_domain_returns_everything(self) -> None:
        raw = await self.mcp.tools["ha_list_services"]()
        self.assertEqual(json.loads(raw), _SERVICES)

    async def test_filtered_response_is_much_smaller(self) -> None:
        """SC-007: la respuesta filtrada mide menos del 10 % de la completa."""
        completa = await self.mcp.tools["ha_list_services"]()
        filtrada = await self.mcp.tools["ha_list_services"](domain="light")
        self.assertLess(len(filtrada), 0.1 * len(completa))

    async def test_description_recommends_domain(self) -> None:
        doc = self.mcp.tools["ha_list_services"].__doc__
        self.assertIn("domain", doc)


if __name__ == "__main__":
    unittest.main()
