"""Tests de tools de counter."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes import security
from hermes.ha import HAConnectionError
from hermes.models.counter import CounterConfig
import hermes.tools.counter as mod

from tests._ha_fixture import REST_BASE, FakeCollectionStore, make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class TestToolsCounter(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

        self.session = ClientSession()
        self.cache = {
            "counter.cafes": {
                "entity_id": "counter.cafes",
                "state": "3",
                "attributes": {
                    "friendly_name": "Cafés del día",
                    "initial": 0,
                    "minimum": 0,
                    "maximum": 20,
                    "step": 1,
                },
            }
        }
        self.ha_client = make_ready_client(self.session, self.cache)
        self.store = FakeCollectionStore()
        self.store.install(self.ha_client)
        self.store.seed(
            "counter",
            "cafes",
            {"name": "Cafés", "initial": 0, "maximum": 20},
        )
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha_client)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def test_list(self) -> None:
        result = await self.mcp.tools["ha_list_counters"]()
        parsed = json.loads(result)
        self.assertEqual(parsed[0]["entity_id"], "counter.cafes")
        self.assertEqual(parsed[0]["maximum"], 20)

    async def test_get_ok(self) -> None:
        result = await self.mcp.tools["ha_get_counter"]("counter.cafes")
        self.assertEqual(result["config"]["maximum"], 20)
        self.assertEqual(result["state"]["entity_id"], "counter.cafes")

    async def test_get_missing(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/counter.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_get_counter"]("counter.fantasma")
        self.assertIsNone(result["config"])
        self.assertIsNone(result["state"])

    async def test_update_preview(self) -> None:
        result = await self.mcp.tools["ha_create_or_update_counter"](
            "counter.cafes",
            {"name": "Nuevo", "maximum": 30, "initial": None},
        )
        self.assertIn("confirmation_token", result)
        self.assertEqual(result["preview"]["new"]["name"], "Nuevo")
        self.assertNotIn("initial", result["preview"]["new"])

    async def test_update_apply(self) -> None:
        new_config = {"name": "Cafés", "maximum": 30}
        normalized = CounterConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_counter",
            {"entity_id": "counter.cafes", "config": normalized},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_create_or_update_counter"](
            "counter.cafes",
            new_config,
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(
            self.store.get("counter", "cafes")["maximum"], 30
        )

    async def test_partial_update_keeps_other_fields(self) -> None:
        """`{domain}/update` de HA reemplaza el item: hay que mandarlo entero.

        Regresión: al enviar solo los campos cambiados, HA borraba el resto de
        la configuración (aquí `initial`) sin avisar.
        """
        new_config = {"name": "Cafés", "maximum": 30}
        normalized = CounterConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_counter",
            {"entity_id": "counter.cafes", "config": normalized},
        )
        result = await self.mcp.tools["ha_create_or_update_counter"](
            "counter.cafes",
            new_config,
            confirmation_token=token_response["confirmation_token"],
        )
        self.assertEqual(result, {"result": "ok"})
        stored = self.store.get("counter", "cafes")
        self.assertEqual(stored["maximum"], 30)
        self.assertEqual(stored["initial"], 0)

    async def test_partial_update_without_name_does_not_fail(self) -> None:
        """`name` es Required en el schema de update: omitirlo rompía la tool."""
        new_config = {"maximum": 42}
        normalized = CounterConfig.model_validate(new_config).model_dump(
            exclude_none=True, by_alias=True, mode="json"
        )
        token_response = await security.create_confirmation_token(
            "ha_create_or_update_counter",
            {"entity_id": "counter.cafes", "config": normalized},
        )
        result = await self.mcp.tools["ha_create_or_update_counter"](
            "counter.cafes",
            new_config,
            confirmation_token=token_response["confirmation_token"],
        )
        self.assertEqual(result, {"result": "ok"})
        stored = self.store.get("counter", "cafes")
        self.assertEqual(stored["maximum"], 42)
        self.assertEqual(stored["name"], "Cafés")

    async def test_update_token_invalid(self) -> None:
        result = await self.mcp.tools["ha_create_or_update_counter"](
            "counter.cafes",
            {"name": "X"},
            confirmation_token="token-no-existe",
        )
        self.assertIn("error", result)

    async def test_delete_requires_token(self) -> None:
        result = await self.mcp.tools["ha_delete_counter"]("counter.cafes")
        self.assertIn("confirmation_token", result)

    async def test_delete_apply(self) -> None:
        token_response = await security.create_confirmation_token(
            "ha_delete_counter",
            {"entity_id": "counter.cafes"},
        )
        token = token_response["confirmation_token"]
        result = await self.mcp.tools["ha_delete_counter"](
            "counter.cafes",
            confirmation_token=token,
        )
        self.assertEqual(result, {"result": "ok"})
        self.assertIsNone(self.store.get("counter", "cafes"))

    def _real_delete_raising(self, exc: HAConnectionError) -> list[dict]:
        """Vuelve a poner el `ws_collection_delete` real del cliente (el
        FakeCollectionStore lo sustituye) y hace que `counter/delete` falle
        con `exc`, como lo haría HA."""
        del self.ha_client.ws_collection_delete
        sent: list[dict] = []

        async def fake_ws_send(payload, timeout_seconds=30):
            sent.append(payload)
            raise exc

        self.ha_client.ws_send = fake_ws_send  # type: ignore[method-assign]
        return sent

    async def test_delete_missing_returns_not_found_by_code(self) -> None:
        """D1: HA responde «Unable to find counter_id …» con código
        `not_found`; el texto no contiene «not found», así que buscarlo en el
        mensaje convertía el caso en un error genérico."""
        sent = self._real_delete_raising(
            HAConnectionError(
                "HA WS command failed: Unable to find counter_id no_existe",
                code="not_found",
            )
        )
        token_response = await security.create_confirmation_token(
            "ha_delete_counter",
            {"entity_id": "counter.no_existe"},
        )
        result = await self.mcp.tools["ha_delete_counter"](
            "counter.no_existe",
            confirmation_token=token_response["confirmation_token"],
        )
        self.assertEqual(result, {"result": "not_found"})
        self.assertEqual(
            sent, [{"type": "counter/delete", "counter_id": "no_existe"}]
        )

    async def test_delete_other_error_code_is_error(self) -> None:
        """Un error con otro código no se disfraza de `not_found`, aunque su
        texto diga «not found»."""
        self._real_delete_raising(
            HAConnectionError(
                "HA WS command failed: storage not found",
                code="home_assistant_error",
            )
        )
        token_response = await security.create_confirmation_token(
            "ha_delete_counter",
            {"entity_id": "counter.cafes"},
        )
        result = await self.mcp.tools["ha_delete_counter"](
            "counter.cafes",
            confirmation_token=token_response["confirmation_token"],
        )
        self.assertIn("error", result)
        self.assertNotEqual(result.get("result"), "not_found")

    async def test_increment(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/counter/increment",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_increment_counter"](
                "counter.cafes"
            )
        self.assertEqual(result, [])

    async def test_increment_amount(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/counter/set_value",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_increment_counter"](
                "counter.cafes", amount=5
            )
            posted = None
            for (method, _url), calls in m.requests.items():
                if method.upper() == "POST":
                    posted = calls[0].kwargs.get("json")
                    break
        self.assertEqual(result, [])
        # estado actual = 3, delta = +5 → 8
        self.assertEqual(posted["value"], 8)

    async def test_decrement(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/counter/decrement",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_decrement_counter"](
                "counter.cafes"
            )
        self.assertEqual(result, [])

    async def test_decrement_amount(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/counter/set_value",
                status=200,
                payload=[],
            )
            await self.mcp.tools["ha_decrement_counter"](
                "counter.cafes", amount=2
            )
            posted = None
            for (method, _url), calls in m.requests.items():
                if method.upper() == "POST":
                    posted = calls[0].kwargs.get("json")
                    break
        # estado actual = 3, delta = -2 → 1
        self.assertEqual(posted["value"], 1)

    async def test_reset(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/counter/reset",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_reset_counter"]("counter.cafes")
        self.assertEqual(result, [])

    async def test_set_value(self) -> None:
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/counter/set_value",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_set_counter_value"](
                "counter.cafes", 10
            )
        self.assertEqual(result, [])

    async def test_reload(self) -> None:
        """Recargar exige confirmación: `counter.reload` está en la denylist.

        Antes esta tool llamaba directa al cliente y ejecutaba el servicio sin
        token, pese a que la denylist lo veta expresamente ("Reloads que pueden
        activar YAML envenenado"). Era la ruta limpia para materializar un
        fs_write_file malicioso previo.
        """
        # 1. Sin token: preview + confirmation_token, y NADA se ejecuta.
        first = await self.mcp.tools["ha_reload_counters"]()
        payload = json.loads(first) if isinstance(first, str) else first
        self.assertIn("confirmation_token", payload)
        self.assertEqual(payload["preview"]["service"], "counter.reload")

        # 2. Con el token: se ejecuta.
        with aioresponses() as m:
            m.post(
                f"{REST_BASE}/services/counter/reload",
                status=200,
                payload=[],
            )
            result = await self.mcp.tools["ha_reload_counters"](
                confirmation_token=payload["confirmation_token"]
            )
        self.assertEqual(result, [])

    async def test_increment_not_found(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/counter.fantasma",
                status=404,
                body="nope",
            )
            result = await self.mcp.tools["ha_increment_counter"](
                "counter.fantasma"
            )
        self.assertEqual(
            result,
            {"error": "not_found", "entity_id": "counter.fantasma"},
        )
