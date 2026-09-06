"""Tests de tools de scenes con transporte REST mockeado."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes import security
from hermes.models.scene import SceneConfig
import hermes.tools.scenes as scenes_module

from tests._ha_fixture import REST_BASE, make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class TestToolsScenes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

        self.session = ClientSession()
        self.cache = {
            "scene.fiesta": {
                "entity_id": "scene.fiesta",
                "state": "scening",
                "attributes": {
                    "id": "1710000000001",
                    "friendly_name": "Fiesta",
                    "icon": "mdi:party-popper",
                },
            }
        }
        self.ha_client = make_ready_client(self.session, self.cache)
        self.mcp = DummyMCP()
        scenes_module.register(self.mcp, self.ha_client)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    # ── list ────────────────────────────────────────────────

    async def test_list_scenes(self) -> None:
        result = await self.mcp.tools["ha_list_scenes"]()
        parsed = json.loads(result)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["entity_id"], "scene.fiesta")
        self.assertEqual(parsed[0]["friendly_name"], "Fiesta")
        self.assertEqual(parsed[0]["icon"], "mdi:party-popper")

    # ── get ─────────────────────────────────────────────────

    async def test_get_scene_returns_config_and_state(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=200,
                payload={
                    "id": "1710000000001",
                    "name": "Fiesta",
                    "entities": {"light.salon": "on"},
                },
            )
            result = await self.mcp.tools["ha_get_scene"]("scene.fiesta")

        self.assertEqual(result["config"]["name"], "Fiesta")
        self.assertEqual(result["state"]["entity_id"], "scene.fiesta")

    async def test_get_scene_missing_config(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_get_scene"]("scene.fiesta")

        self.assertIsNone(result["config"])
        self.assertEqual(result["state"]["entity_id"], "scene.fiesta")

    # ── update ──────────────────────────────────────────────

    async def test_update_scene_preview_when_exists(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=200,
                payload={"name": "Fiesta antigua", "entities": {"light.salon": "off"}},
            )
            result = await self.mcp.tools["ha_create_or_update_scene"](
                "scene.fiesta",
                {"name": "Fiesta nueva", "entities": {"light.salon": "on"}},
            )

        self.assertIn("confirmation_token", result)
        self.assertEqual(result["preview"]["current"]["name"], "Fiesta antigua")
        self.assertEqual(result["preview"]["new"]["name"], "Fiesta nueva")

    async def test_update_scene_apply_with_token(self) -> None:
        new_config = {"name": "Fiesta nueva", "entities": {"light.salon": "on"}}
        normalized = SceneConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_scene",
            {"scene_id": "scene.fiesta", "config": normalized},
        )
        token = token_response["confirmation_token"]

        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=200,
                payload={"result": "ok"},
            )
            result = await self.mcp.tools["ha_create_or_update_scene"](
                "scene.fiesta",
                new_config,
                confirmation_token=token,
            )

        self.assertEqual(result, {"result": "ok"})

    async def test_update_scene_creates_directly_when_not_exists(self) -> None:
        """Sin token y sin config previa: se crea directamente."""
        new_config = {"name": "Nueva", "entities": {"light.cocina": "on"}}

        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=404,
                body="nope",
            )
            m.post(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=200,
                payload={"result": "ok"},
            )
            result = await self.mcp.tools["ha_create_or_update_scene"](
                "scene.fiesta",
                new_config,
            )

        self.assertEqual(result, {"result": "ok"})

    # ── delete ──────────────────────────────────────────────

    async def test_delete_scene_requires_token(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=200,
                payload={"name": "Fiesta"},
            )
            result = await self.mcp.tools["ha_delete_scene"]("scene.fiesta")

        self.assertIn("confirmation_token", result)

    async def test_delete_scene_apply(self) -> None:
        token_response = await security.create_confirmation_token(
            "ha_delete_scene",
            {"scene_id": "scene.fiesta"},
        )
        token = token_response["confirmation_token"]

        with aioresponses() as m:
            m.delete(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=200,
                payload={"result": "ok"},
            )
            result = await self.mcp.tools["ha_delete_scene"](
                "scene.fiesta",
                confirmation_token=token,
            )

        self.assertEqual(result, {"result": "ok"})

    # ── service wrappers ────────────────────────────────────

    async def test_activate_scene_calls_service(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/scene/turn_on",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_activate_scene"](
                "scene.fiesta",
                transition=2.5,
            )
        self.assertEqual(result, [])

    # ── Bug 1: serialization ────────────────────────────────

    async def test_update_scene_body_has_no_nulls(self) -> None:
        new_config = {
            "name": "Fiesta",
            "icon": None,
            "entities": {"light.salon": "on"},
        }
        normalized = SceneConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_scene",
            {"scene_id": "scene.fiesta", "config": normalized},
        )
        token = token_response["confirmation_token"]

        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/config/scene/config/1710000000001",
                status=200,
                payload={"result": "ok"},
            )
            await self.mcp.tools["ha_create_or_update_scene"](
                "scene.fiesta",
                new_config,
                confirmation_token=token,
            )
            posted = None
            for (method, _url), calls in m.requests.items():
                if method.upper() == "POST":
                    posted = calls[0].kwargs.get("json")
                    break

        self.assertIsNotNone(posted)
        self.assertNotIn("icon", posted)
        for k, v in posted.items():
            self.assertIsNotNone(v, f"clave {k} no debería ser null")

    # ── Bug 3: existence check ─────────────────────────────

    async def test_activate_scene_not_found(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/scene.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_activate_scene"]("scene.fantasma")
        self.assertEqual(
            result,
            {"error": "not_found", "entity_id": "scene.fantasma"},
        )

    async def test_reload_scenes(self) -> None:
        """Recargar exige confirmación: `scene.reload` está en la denylist.

        Antes esta tool llamaba directa al cliente y ejecutaba el servicio sin
        token, pese a que la denylist lo veta expresamente ("Reloads que pueden
        activar YAML envenenado"). Era la ruta limpia para materializar un
        fs_write_file malicioso previo.
        """
        # 1. Sin token: preview + confirmation_token, y NADA se ejecuta.
        first = await self.mcp.tools["ha_reload_scenes"]()
        payload = json.loads(first) if isinstance(first, str) else first
        self.assertIn("confirmation_token", payload)
        self.assertEqual(payload["preview"]["service"], "scene.reload")

        # 2. Con el token: se ejecuta.
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/scene/reload",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_reload_scenes"](
                confirmation_token=payload["confirmation_token"]
            )
        self.assertEqual(result, [])

    async def test_create_scene_from_current(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/scene/create",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_create_scene_from_current"](
                "scene.nueva",
                ["light.salon", "light.cocina"],
                name="Nueva",
            )
        self.assertEqual(result, [])
