"""Tests de `ha_search_related` con Home Assistant simulado.

`ha_at_least` y `ha_core_version` se parchean en el módulo de la tool para
fijar la versión de HA sin depender de `get_config`.
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession
from packaging.version import Version

import hermes.tools.search as search_mod
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


_TIPOS = (
    "area", "automation", "automation_blueprint", "config_entry", "device",
    "entity", "floor", "group", "integration", "label", "person", "scene",
    "script", "script_blueprint",
)


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        client = make_ready_client(self.session, {})
        self.sent: list[dict[str, Any]] = []
        self.respuesta: Any = {}
        self.error: HAConnectionError | None = None

        async def fake_ws(payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
            self.sent.append(payload)
            if self.error is not None:
                raise self.error
            return self.respuesta

        client.ws_send = fake_ws  # type: ignore[method-assign]
        self.mcp = DummyMCP()
        search_mod.register(self.mcp, client)
        self.tool = self.mcp.tools["ha_search_related"]

    async def asyncTearDown(self) -> None:
        await self.session.close()


class TestSearchRelated(_Base):
    async def test_envia_tipo_e_id_sin_include_disabled(self) -> None:
        self.respuesta = {
            "automation": ["automation.demo"],
            "scene": ["scene.demo"],
            "area": ["zona_demo"],
        }
        res = json.loads(await self.tool("entity", "light.demo"))
        self.assertEqual(
            self.sent,
            [{"type": "search/related", "item_type": "entity",
              "item_id": "light.demo"}],
        )
        self.assertEqual(res["item_type"], "entity")
        self.assertEqual(res["item_id"], "light.demo")
        self.assertEqual(res["related"]["automation"], ["automation.demo"])
        self.assertEqual(res["counts"],
                         {"automation": 1, "scene": 1, "area": 1})
        self.assertFalse(res["truncated"])

    async def test_item_type_invalido(self) -> None:
        res = json.loads(await self.tool("room", "x"))
        self.assertEqual(res["error"], "invalid_argument")
        self.assertEqual(res["field"], "item_type")
        for tipo in _TIPOS:
            self.assertIn(tipo, res["detail"])
        self.assertEqual(self.sent, [])

    async def test_los_catorce_tipos_son_validos(self) -> None:
        self.assertEqual(set(search_mod._ITEM_TYPES), set(_TIPOS))

    async def test_recorte_a_200_por_tipo(self) -> None:
        self.respuesta = {
            "entity": [f"sensor.demo_{i}" for i in range(250)],
            "device": ["dev1"],
        }
        res = json.loads(await self.tool("area", "zona_demo"))
        self.assertEqual(len(res["related"]["entity"]), 200)
        self.assertEqual(res["counts"]["entity"], 250)
        self.assertEqual(res["counts"]["device"], 1)
        self.assertTrue(res["truncated"])

    async def test_error_de_ha(self) -> None:
        self.error = HAConnectionError("offline")
        res = json.loads(await self.tool("entity", "light.demo"))
        self.assertIn("error", res)


class TestIncludeDisabledEntities(_Base):
    async def test_version_antigua_no_llama(self) -> None:
        with patch.object(search_mod, "ha_at_least",
                          AsyncMock(return_value=False)), \
             patch.object(search_mod, "ha_core_version",
                          AsyncMock(return_value=Version("2026.9.2"))):
            res = json.loads(await self.tool(
                "device", "dev1", include_disabled_entities=True))
        self.assertEqual(res, {
            "error": "ha_version_unsupported",
            "feature": "include_disabled_entities",
            "required": "2026.10.0",
            "current": "2026.9.2",
        })
        self.assertEqual(self.sent, [])

    async def test_version_nueva_lo_envia(self) -> None:
        self.respuesta = {"entity": ["sensor.demo"]}
        with patch.object(search_mod, "ha_at_least",
                          AsyncMock(return_value=True)):
            res = json.loads(await self.tool(
                "device", "dev1", include_disabled_entities=True))
        self.assertEqual(
            self.sent,
            [{"type": "search/related", "item_type": "device",
              "item_id": "dev1", "include_disabled_entities": True}],
        )
        self.assertEqual(res["counts"], {"entity": 1})

    async def test_version_desconocida_lo_envia_y_traduce_invalid_format(self) -> None:
        self.error = HAConnectionError("extra keys not allowed",
                                       code="invalid_format")
        with patch.object(search_mod, "ha_at_least",
                          AsyncMock(return_value=None)):
            res = json.loads(await self.tool(
                "device", "dev1", include_disabled_entities=True))
        self.assertEqual(self.sent[0].get("include_disabled_entities"), True)
        self.assertEqual(res, {
            "error": "ha_version_unsupported",
            "feature": "include_disabled_entities",
            "required": "2026.10.0",
            "current": None,
        })

    async def test_false_no_consulta_version(self) -> None:
        version = AsyncMock(return_value=False)
        with patch.object(search_mod, "ha_at_least", version):
            await self.tool("device", "dev1", include_disabled_entities=False)
        version.assert_not_awaited()
        self.assertNotIn("include_disabled_entities", self.sent[0])


if __name__ == "__main__":
    unittest.main()
