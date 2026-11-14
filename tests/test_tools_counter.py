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

    async def test_reload_no_soportada(self) -> None:
        """Spec 033 (FR-004, T013): HA Core no tiene `counter.reload`.

        La integración `counter` solo registra increment, decrement, reset y
        set_value (research R-2): antes la tool pedía token y, al confirmar,
        Core respondía 400. Ahora responde `not_supported` siempre, con o sin
        token, sin llamar a HA, sin emitir ni gastar tokens, y avisa de su
        retirada en la 1.3.0.

        Control negativo (T017), comprobado y restaurado: devolviendo la
        llamada a `guarded_reload`, este test cae (sale la vista previa con
        token en vez de `not_supported`).
        """
        llamadas: list[tuple] = []

        async def espia(*args, **kwargs):
            llamadas.append((args, kwargs))
            return []

        self.ha_client.call_service = espia  # type: ignore[method-assign]
        tool = self.mcp.tools["ha_reload_counters"]
        self.assertTrue(tool.__doc__.lstrip().startswith("DEPRECATED (removed in 1.3.0)"))
        sin_token = await tool()
        con_token = await tool(confirmation_token="cualquiera")
        for respuesta in (sin_token, con_token):
            self.assertEqual(respuesta["error"], "not_supported", respuesta)
            self.assertIn("counter.reload", respuesta["message"])
            self.assertTrue(respuesta["hint"])
            self.assertIn("1.3.0", respuesta["_deprecated"])
            self.assertNotIn("confirmation_token", respuesta)
        self.assertEqual(llamadas, [])
        # Ningún token emitido (ni gastado).
        self.assertEqual(list(Path(self.temp_dir.name).iterdir()), [])

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


class TestValorDeContadorValido(unittest.IsolatedAsyncioTestCase):
    """Spec 033 (FR-009, T026) y extra del supervisor (`ha_set_counter_value`).

    HA solo acepta en `counter.set_value` un valor múltiplo de `step` y
    dentro de `minimum`/`maximum` (`counter/entity.py`, `async_set_value`);
    si no, lanza `ValueError` y el REST de Core responde un 500 genérico
    (research R-7). `amount` de increment/decrement va por `set_value`, así
    que Hermes comprueba el valor con los atributos del estado ANTES de
    llamar y responde un error claro sin tocar HA.

    Control negativo (T028), comprobado y restaurado: quitando la
    comprobación de `_bulk_adjust` caen los cuatro tests de `amount`
    inválido (HA recibe la llamada); quitándola de `ha_set_counter_value`
    caen los dos de `invalid_value`.
    """

    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.cache = {
            # `initial` 5 y `step` 3, como el contador del banco: 5 no es
            # múltiplo de 3, así que ningún `amount` lleva a un valor válido.
            "counter.ficticio": {
                "entity_id": "counter.ficticio",
                "state": "5",
                "attributes": {"initial": 5, "step": 3, "minimum": None, "maximum": None},
            },
            "counter.seis": {
                "entity_id": "counter.seis",
                "state": "6",
                "attributes": {"initial": 0, "step": 3},
            },
            "counter.tope": {
                "entity_id": "counter.tope",
                "state": "9",
                "attributes": {"initial": 0, "step": 1, "minimum": 0, "maximum": 10},
            },
            # Sin `step` en los atributos: se asume 1, el valor por defecto de HA.
            "counter.sin_step": {
                "entity_id": "counter.sin_step",
                "state": "4",
                "attributes": {"initial": 0},
            },
        }
        self.ha_client = make_ready_client(self.session, self.cache)
        self.llamadas: list[tuple] = []

        async def espia(domain, service, data=None, **kwargs):
            self.llamadas.append((domain, service, data))
            return []

        self.ha_client.call_service = espia  # type: ignore[method-assign]
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha_client)

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def _tool(self, nombre: str, *args, **kwargs):
        return await self.mcp.tools[nombre](*args, **kwargs)

    async def test_amount_no_multiplo_del_step(self) -> None:
        r = await self._tool("ha_increment_counter", "counter.ficticio", amount=3)
        self.assertEqual(r["error"], "invalid_amount")
        self.assertEqual(r["reason"], "not_multiple_of_step")
        self.assertEqual(
            (r["entity_id"], r["current"], r["target"], r["step"], r["minimum"], r["maximum"]),
            ("counter.ficticio", 5, 8, 3, None, None),
        )
        self.assertIn("ha_set_counter_value", r["hint"])
        self.assertEqual(self.llamadas, [])

    async def test_decrement_amount_no_multiplo(self) -> None:
        r = await self._tool("ha_decrement_counter", "counter.ficticio", amount=3)
        self.assertEqual((r["error"], r["reason"], r["target"]), ("invalid_amount", "not_multiple_of_step", 2))
        self.assertEqual(self.llamadas, [])

    async def test_amount_fuera_del_maximo(self) -> None:
        r = await self._tool("ha_increment_counter", "counter.tope", amount=5)
        self.assertEqual((r["error"], r["reason"]), ("invalid_amount", "out_of_range"))
        self.assertEqual((r["current"], r["target"], r["minimum"], r["maximum"]), (9, 14, 0, 10))
        self.assertEqual(self.llamadas, [])

    async def test_amount_por_debajo_del_minimo(self) -> None:
        r = await self._tool("ha_decrement_counter", "counter.tope", amount=10)
        self.assertEqual((r["error"], r["reason"], r["target"]), ("invalid_amount", "out_of_range", -1))
        self.assertEqual(self.llamadas, [])

    async def test_amount_valido_llama_a_set_value(self) -> None:
        r = await self._tool("ha_increment_counter", "counter.seis", amount=3)
        self.assertEqual(r, [])
        self.assertEqual(
            self.llamadas, [("counter", "set_value", {"entity_id": "counter.seis", "value": 9})]
        )

    async def test_sin_step_se_asume_uno(self) -> None:
        r = await self._tool("ha_decrement_counter", "counter.sin_step", amount=7)
        self.assertEqual(r, [])
        self.assertEqual(
            self.llamadas, [("counter", "set_value", {"entity_id": "counter.sin_step", "value": -3})]
        )

    async def test_sin_amount_no_cambia(self) -> None:
        # Sin `amount` va a increment/decrement, que HA recorta a los límites:
        # no hay nada que comprobar.
        await self._tool("ha_increment_counter", "counter.ficticio")
        await self._tool("ha_decrement_counter", "counter.tope")
        self.assertEqual(
            self.llamadas,
            [
                ("counter", "increment", {"entity_id": "counter.ficticio"}),
                ("counter", "decrement", {"entity_id": "counter.tope"}),
            ],
        )

    async def test_set_value_no_multiplo_del_step(self) -> None:
        r = await self._tool("ha_set_counter_value", "counter.ficticio", 7)
        self.assertEqual((r["error"], r["reason"]), ("invalid_value", "not_multiple_of_step"))
        self.assertEqual(
            (r["entity_id"], r["current"], r["value"], r["step"]), ("counter.ficticio", 5, 7, 3)
        )
        self.assertTrue(r["hint"])
        self.assertEqual(self.llamadas, [])

    async def test_set_value_fuera_de_limites(self) -> None:
        r = await self._tool("ha_set_counter_value", "counter.tope", 11)
        self.assertEqual((r["error"], r["reason"]), ("invalid_value", "out_of_range"))
        self.assertEqual((r["minimum"], r["maximum"]), (0, 10))
        self.assertEqual(self.llamadas, [])

    async def test_set_value_valido(self) -> None:
        self.assertEqual(await self._tool("ha_set_counter_value", "counter.ficticio", 6), [])
        self.assertEqual(
            self.llamadas, [("counter", "set_value", {"entity_id": "counter.ficticio", "value": 6})]
        )
