"""Tests de tools de zone."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes import security
from hermes.models.zone import ZoneConfig
import hermes.tools.zones as mod

from tests._ha_fixture import REST_BASE, FakeCollectionStore, make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class TestToolsZones(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

        self.session = ClientSession()
        self.cache = {
            "zone.casa": {
                "entity_id": "zone.casa",
                "state": "1",
                "attributes": {
                    "friendly_name": "Casa",
                    "latitude": 40.4,
                    "longitude": -3.7,
                    "radius": 100,
                    "passive": False,
                    "icon": "mdi:home",
                },
            }
        }
        self.ha_client = make_ready_client(self.session, self.cache)
        self.store = FakeCollectionStore()
        self.store.install(self.ha_client)
        self.store.seed(
            "zone",
            "casa",
            {
                "name": "Casa",
                "latitude": 40.4,
                "longitude": -3.7,
                "radius": 100,
                "passive": False,
                "icon": "mdi:home",
            },
        )
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha_client)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def test_list(self) -> None:
        result = await self.mcp.tools["ha_list_zones"]()
        parsed = json.loads(result)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["entity_id"], "zone.casa")
        self.assertEqual(parsed[0]["radius"], 100)

    async def test_get_ok(self) -> None:
        result = await self.mcp.tools["ha_get_zone"]("zone.casa")
        self.assertEqual(result["config"]["name"], "Casa")
        self.assertEqual(result["state"]["entity_id"], "zone.casa")

    async def test_get_missing(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/zone.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_get_zone"]("zone.fantasma")
        self.assertIsNone(result["config"])
        self.assertIsNone(result["state"])

    async def test_update_preview(self) -> None:
        result = await self.mcp.tools["ha_create_or_update_zone"](
            "zone.casa",
            {"name": "Casa", "radius": 250},
        )
        self.assertIn("confirmation_token", result)
        self.assertEqual(result["preview"]["new"]["radius"], 250)

    async def test_update_apply(self) -> None:
        new_config = {"name": "Casa", "radius": 250, "latitude": 40.4, "longitude": -3.7}
        normalized = ZoneConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_zone",
            {"entity_id": "zone.casa", "config": normalized},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_create_or_update_zone"](
            "zone.casa",
            new_config,
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(self.store.get("zone", "casa")["radius"], 250)

    async def test_update_validation_lat_out_of_range(self) -> None:
        result = await self.mcp.tools["ha_create_or_update_zone"](
            "zone.casa",
            {"name": "Casa", "latitude": 200, "longitude": 0, "radius": 10},
        )
        self.assertIn("error", result)
        self.assertIn("latitude", result["error"])

    async def test_update_validation_radius_negative(self) -> None:
        result = await self.mcp.tools["ha_create_or_update_zone"](
            "zone.casa",
            {"name": "Casa", "radius": -5},
        )
        self.assertIn("error", result)
        self.assertIn("radius", result["error"])

    async def test_delete_requires_token(self) -> None:
        result = await self.mcp.tools["ha_delete_zone"]("zone.casa")
        self.assertIn("confirmation_token", result)

    async def test_delete_apply(self) -> None:
        token_response = await security.create_confirmation_token(
            "ha_delete_zone",
            {"entity_id": "zone.casa"},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_delete_zone"](
            "zone.casa",
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertIsNone(self.store.get("zone", "casa"))

    async def test_reload(self) -> None:
        """Recargar exige confirmación: `zone.reload` está en la denylist.

        Antes esta tool llamaba directa al cliente y ejecutaba el servicio sin
        token, pese a que la denylist lo veta expresamente ("Reloads que pueden
        activar YAML envenenado"). Era la ruta limpia para materializar un
        fs_write_file malicioso previo.
        """
        # 1. Sin token: preview + confirmation_token, y NADA se ejecuta.
        first = await self.mcp.tools["ha_reload_zones"]()
        payload = json.loads(first) if isinstance(first, str) else first
        self.assertIn("confirmation_token", payload)
        self.assertEqual(payload["preview"]["service"], "zone.reload")

        # 2. Con el token: se ejecuta.
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/zone/reload",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_reload_zones"](
                confirmation_token=payload["confirmation_token"]
            )
        self.assertEqual(result, [])

