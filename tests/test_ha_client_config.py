"""Tests de HAClient.config_read / config_save / config_delete con aioresponses."""

from __future__ import annotations

import unittest

from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes.ha import HAConnectionError

from tests._ha_fixture import REST_BASE, make_ready_client


class TestHAClientConfigHelpers(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.client = make_ready_client(self.session)

    async def asyncTearDown(self) -> None:
        await self.session.close()

    # ── config_read ─────────────────────────────────────────

    async def test_config_read_ok(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/automation/config/1689",
                status=200,
                payload={"id": "1689", "alias": "Cocina"},
            )
            result = await self.client.config_read("automation", "1689")
        self.assertEqual(result, {"id": "1689", "alias": "Cocina"})

    async def test_config_read_not_found(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/automation/config/ghost",
                status=404,
                body="Resource not found",
            )
            result = await self.client.config_read("automation", "ghost")
        self.assertIsNone(result)

    async def test_config_read_server_error(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/config/automation/config/x",
                status=500,
                body="boom",
            )
            with self.assertRaises(HAConnectionError):
                await self.client.config_read("automation", "x")

    # ── config_save ─────────────────────────────────────────

    async def test_config_save_ok(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/config/script/config/saludar",
                status=200,
                payload={"result": "ok"},
            )
            result = await self.client.config_save(
                "script",
                "saludar",
                {"alias": "Saludar", "sequence": []},
            )
        self.assertEqual(result, {"result": "ok"})

    async def test_config_save_unexpected_body(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/config/script/config/foo",
                status=200,
                payload={"weird": "body"},
            )
            with self.assertRaises(HAConnectionError):
                await self.client.config_save("script", "foo", {})

    async def test_config_save_400(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/config/script/config/foo",
                status=400,
                body="Message malformed",
            )
            with self.assertRaises(HAConnectionError):
                await self.client.config_save("script", "foo", {})

    # ── config_delete ───────────────────────────────────────

    async def test_config_delete_ok(self) -> None:
        with aioresponses() as m:
            m.delete(
                f"{REST_BASE}/config/automation/config/1689",
                status=200,
                payload={"result": "ok"},
            )
            result = await self.client.config_delete("automation", "1689")
        self.assertEqual(result, {"result": "ok"})

    async def test_config_delete_missing_returns_none(self) -> None:
        with aioresponses() as m:
            m.delete(
                f"{REST_BASE}/config/automation/config/ghost",
                status=400,
                body="Resource not found",
            )
            result = await self.client.config_delete("automation", "ghost")
        self.assertIsNone(result)

    async def test_config_delete_server_error(self) -> None:
        with aioresponses() as m:
            m.delete(
                f"{REST_BASE}/config/automation/config/x",
                status=500,
                body="boom",
            )
            with self.assertRaises(HAConnectionError):
                await self.client.config_delete("automation", "x")
