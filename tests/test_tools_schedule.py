"""Tests de tools de schedule."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes import security
from hermes.models.schedule import ScheduleConfig
import hermes.tools.schedule as mod

from tests._ha_fixture import REST_BASE, FakeCollectionStore, make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class TestToolsSchedule(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

        self.session = ClientSession()
        self.cache = {
            "schedule.oficina": {
                "entity_id": "schedule.oficina",
                "state": "on",
                "attributes": {
                    "friendly_name": "Horario oficina",
                    "next_event": "2026-04-13T07:00:00+00:00",
                },
            }
        }
        self.ha_client = make_ready_client(self.session, self.cache)
        self.store = FakeCollectionStore()
        self.store.install(self.ha_client)
        self.store.seed(
            "schedule",
            "oficina",
            {
                "name": "Oficina",
                "monday": [{"from": "07:00:00", "to": "19:00:00"}],
                "tuesday": [{"from": "07:00:00", "to": "19:00:00"}],
            },
        )
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha_client)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def test_list(self) -> None:
        result = await self.mcp.tools["ha_list_schedules"]()
        parsed = json.loads(result)
        self.assertEqual(parsed[0]["entity_id"], "schedule.oficina")
        self.assertEqual(parsed[0]["state"], "on")

    async def test_get_ok(self) -> None:
        result = await self.mcp.tools["ha_get_schedule"]("schedule.oficina")
        self.assertEqual(result["config"]["monday"][0]["from"], "07:00:00")

    async def test_get_missing(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/schedule.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_get_schedule"](
                "schedule.fantasma"
            )
        self.assertIsNone(result["config"])
        self.assertIsNone(result["state"])

    async def test_model_roundtrip_from_alias(self) -> None:
        """`from` (alias) debe sobrevivir al validate→dump con by_alias=True."""
        cfg = ScheduleConfig.model_validate(
            {
                "name": "Test",
                "monday": [{"from": "08:00:00", "to": "12:00:00"}],
            }
        )
        dumped = cfg.model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        self.assertEqual(dumped["monday"][0]["from"], "08:00:00")
        self.assertEqual(dumped["monday"][0]["to"], "12:00:00")
        self.assertNotIn("from_", dumped["monday"][0])

    async def test_update_preview(self) -> None:
        result = await self.mcp.tools["ha_create_or_update_schedule"](
            "schedule.oficina",
            {
                "name": "Nuevo",
                "monday": [{"from": "09:00:00", "to": "18:00:00"}],
                "icon": None,
            },
        )
        self.assertIn("confirmation_token", result)
        self.assertEqual(
            result["preview"]["new"]["monday"][0]["from"], "09:00:00"
        )
        self.assertNotIn("icon", result["preview"]["new"])

    async def test_update_apply(self) -> None:
        new_config = {
            "name": "Oficina",
            "monday": [{"from": "09:00:00", "to": "18:00:00"}],
            "tuesday": [{"from": "09:00:00", "to": "18:00:00"}],
        }
        normalized = ScheduleConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_schedule",
            {"entity_id": "schedule.oficina", "config": normalized},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_create_or_update_schedule"](
            "schedule.oficina",
            new_config,
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        stored = self.store.get("schedule", "oficina")
        self.assertEqual(stored["monday"][0]["from"], "09:00:00")
        self.assertNotIn("from_", stored["monday"][0])

    async def test_update_token_invalid(self) -> None:
        result = await self.mcp.tools["ha_create_or_update_schedule"](
            "schedule.oficina",
            {"name": "X"},
            confirmation_token="token-no-existe",
        )
        self.assertIn("error", result)

    async def test_delete_requires_token(self) -> None:
        result = await self.mcp.tools["ha_delete_schedule"](
            "schedule.oficina"
        )
        self.assertIn("confirmation_token", result)

    async def test_delete_apply(self) -> None:
        token_response = await security.create_confirmation_token(
            "ha_delete_schedule",
            {"entity_id": "schedule.oficina"},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_delete_schedule"](
            "schedule.oficina",
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertIsNone(self.store.get("schedule", "oficina"))

    async def test_reload(self) -> None:
        """Recargar exige confirmación: `schedule.reload` está en la denylist.

        Antes esta tool llamaba directa al cliente y ejecutaba el servicio sin
        token, pese a que la denylist lo veta expresamente ("Reloads que pueden
        activar YAML envenenado"). Era la ruta limpia para materializar un
        fs_write_file malicioso previo.
        """
        # 1. Sin token: preview + confirmation_token, y NADA se ejecuta.
        first = await self.mcp.tools["ha_reload_schedules"]()
        payload = json.loads(first) if isinstance(first, str) else first
        self.assertIn("confirmation_token", payload)
        self.assertEqual(payload["preview"]["service"], "schedule.reload")

        # 2. Con el token: se ejecuta.
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/schedule/reload",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_reload_schedules"](
                confirmation_token=payload["confirmation_token"]
            )
        self.assertEqual(result, [])

