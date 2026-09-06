"""Tests de tools de timer."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes import security
from hermes.models.timer import TimerConfig
import hermes.tools.timer as mod

from tests._ha_fixture import REST_BASE, FakeCollectionStore, make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class TestToolsTimer(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

        self.session = ClientSession()
        self.cache = {
            "timer.pomodoro": {
                "entity_id": "timer.pomodoro",
                "state": "idle",
                "attributes": {
                    "friendly_name": "Pomodoro",
                    "duration": "0:25:00",
                    "remaining": "0:00:00",
                },
            }
        }
        self.ha_client = make_ready_client(self.session, self.cache)
        self.store = FakeCollectionStore()
        self.store.install(self.ha_client)
        self.store.seed(
            "timer", "pomodoro", {"name": "Pomodoro", "duration": "00:25:00"}
        )
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha_client)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def test_list(self) -> None:
        result = await self.mcp.tools["ha_list_timers"]()
        parsed = json.loads(result)
        self.assertEqual(parsed[0]["entity_id"], "timer.pomodoro")
        self.assertEqual(parsed[0]["duration"], "0:25:00")

    async def test_get_ok(self) -> None:
        result = await self.mcp.tools["ha_get_timer"]("timer.pomodoro")
        self.assertEqual(result["config"]["duration"], "00:25:00")

    async def test_get_missing(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/timer.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_get_timer"]("timer.fantasma")
        self.assertIsNone(result["config"])
        self.assertIsNone(result["state"])

    async def test_update_preview(self) -> None:
        result = await self.mcp.tools["ha_create_or_update_timer"](
            "timer.pomodoro",
            {"name": "Nuevo", "duration": "00:30:00", "icon": None},
        )
        self.assertIn("confirmation_token", result)
        self.assertEqual(result["preview"]["new"]["duration"], "00:30:00")
        self.assertNotIn("icon", result["preview"]["new"])

    async def test_update_apply(self) -> None:
        new_config = {"name": "Pomodoro", "duration": "00:30:00"}
        normalized = TimerConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_timer",
            {"entity_id": "timer.pomodoro", "config": normalized},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_create_or_update_timer"](
            "timer.pomodoro",
            new_config,
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(
            self.store.get("timer", "pomodoro")["duration"], "00:30:00"
        )

    async def test_update_token_invalid(self) -> None:
        result = await self.mcp.tools["ha_create_or_update_timer"](
            "timer.pomodoro",
            {"name": "X"},
            confirmation_token="token-no-existe",
        )
        self.assertIn("error", result)

    async def test_delete_requires_token(self) -> None:
        result = await self.mcp.tools["ha_delete_timer"]("timer.pomodoro")
        self.assertIn("confirmation_token", result)

    async def test_delete_apply(self) -> None:
        token_response = await security.create_confirmation_token(
            "ha_delete_timer",
            {"entity_id": "timer.pomodoro"},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_delete_timer"](
            "timer.pomodoro",
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertIsNone(self.store.get("timer", "pomodoro"))

    async def test_start_default(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/timer/start",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_start_timer"]("timer.pomodoro")
            posted = None
            for (method, _url), calls in m.requests.items():
                if method.upper() == "POST":
                    posted = calls[0].kwargs.get("json")
                    break
        self.assertEqual(result, [])
        self.assertNotIn("duration", posted)

    async def test_start_with_duration(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/timer/start",
                status=200,
                payload=[],
            )
            await self.mcp.tools["ha_start_timer"](
                "timer.pomodoro", duration="00:05:00"
            )
            posted = None
            for (method, _url), calls in m.requests.items():
                if method.upper() == "POST":
                    posted = calls[0].kwargs.get("json")
                    break
        self.assertEqual(posted["duration"], "00:05:00")

    async def test_pause(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/timer/pause",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_pause_timer"]("timer.pomodoro")
        self.assertEqual(result, [])

    async def test_cancel(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/timer/cancel",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_cancel_timer"]("timer.pomodoro")
        self.assertEqual(result, [])

    async def test_finish(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/timer/finish",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_finish_timer"]("timer.pomodoro")
        self.assertEqual(result, [])

    async def test_change(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/timer/change",
                status=200,
                payload=[],
            )
            await self.mcp.tools["ha_change_timer"](
                "timer.pomodoro", duration="00:01:00"
            )
            posted = None
            for (method, _url), calls in m.requests.items():
                if method.upper() == "POST":
                    posted = calls[0].kwargs.get("json")
                    break
        self.assertEqual(posted["duration"], "00:01:00")

    async def test_reload(self) -> None:
        """Recargar exige confirmación: `timer.reload` está en la denylist.

        Antes esta tool llamaba directa al cliente y ejecutaba el servicio sin
        token, pese a que la denylist lo veta expresamente ("Reloads que pueden
        activar YAML envenenado"). Era la ruta limpia para materializar un
        fs_write_file malicioso previo.
        """
        # 1. Sin token: preview + confirmation_token, y NADA se ejecuta.
        first = await self.mcp.tools["ha_reload_timers"]()
        payload = json.loads(first) if isinstance(first, str) else first
        self.assertIn("confirmation_token", payload)
        self.assertEqual(payload["preview"]["service"], "timer.reload")

        # 2. Con el token: se ejecuta.
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/timer/reload",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_reload_timers"](
                confirmation_token=payload["confirmation_token"]
            )
        self.assertEqual(result, [])

    async def test_start_not_found(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/timer.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_start_timer"]("timer.fantasma")
        self.assertEqual(
            result,
            {"error": "not_found", "entity_id": "timer.fantasma"},
        )
