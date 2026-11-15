"""Tests de ha_get_history y ha_get_logbook con fake WS (monkey-patch de ws_send)."""

from __future__ import annotations

import json
import unittest

from aiohttp import ClientSession

import hermes.tools.history as hist_mod
import hermes.tools.logbook as log_mod
from tests._ha_fixture import make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


# ── Fixtures de datos ─────────────────────────────────────────────────────────

def _make_compressed_points(n: int, base_ts: float = 1_712_000_000.0) -> list[dict]:
    """Genera n puntos comprimidos {s, a, lu} como los devuelve HA."""
    return [
        {
            "s": "on" if i % 2 == 0 else "off",
            "a": {"brightness": i * 10},
            "lu": base_ts + i * 60.0,
        }
        for i in range(n)
    ]


def _make_logbook_events(n: int, base_ts: float = 1_712_000_000.0) -> list[dict]:
    return [
        {
            "when": base_ts + i * 60.0,
            "entity_id": "light.salon",
            "name": "Salón",
            "domain": "light",
            "message": "turned on" if i % 2 == 0 else "turned off",
            "state": "on" if i % 2 == 0 else "off",
        }
        for i in range(n)
    ]


# ── Tests ha_get_history ───────────────────────────────────────────────────────

class TestGetHistory(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def _make_client(self, ws_result):
        client = make_ready_client(self.session, {})
        async def fake_ws_send(payload, timeout_seconds=30):
            return ws_result
        client.ws_send = fake_ws_send  # type: ignore[method-assign]
        return client

    async def test_basic_history(self) -> None:
        points = _make_compressed_points(3)
        client = self._make_client({"light.salon": points})
        mcp = DummyMCP()
        hist_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_history"](["light.salon"])
        result = json.loads(raw)
        self.assertIn("history", result)
        salon = result["history"]["light.salon"]
        self.assertEqual(len(salon), 3)
        # Verificar descompresión
        self.assertIn("state", salon[0])
        self.assertIn("last_updated", salon[0])
        self.assertIn("last_changed", salon[0])
        self.assertIn("attributes", salon[0])
        self.assertFalse(result["truncated"])

    async def test_decompression_expands_keys(self) -> None:
        """Verifica que {s,a,lu} se expande a nombres legibles."""
        points = [{"s": "on", "a": {"brightness": 50}, "lu": 1_712_000_000.0}]
        client = self._make_client({"light.test": points})
        mcp = DummyMCP()
        hist_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_history"](["light.test"])
        result = json.loads(raw)
        pt = result["history"]["light.test"][0]
        self.assertEqual(pt["state"], "on")
        self.assertEqual(pt["attributes"]["brightness"], 50)
        self.assertIn("2024", pt["last_updated"])  # timestamp válido ISO

    async def test_lc_only_present_when_differs(self) -> None:
        """last_changed se copia de last_updated si lc no está en el punto."""
        # Sin lc → last_changed == last_updated
        points = [{"s": "on", "lu": 1_712_000_000.0}]
        client = self._make_client({"light.test": points})
        mcp = DummyMCP()
        hist_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_history"](["light.test"])
        result = json.loads(raw)
        pt = result["history"]["light.test"][0]
        self.assertEqual(pt["last_changed"], pt["last_updated"])

        # Con lc diferente → last_changed distinto
        points2 = [{"s": "on", "lu": 1_712_000_060.0, "lc": 1_712_000_000.0}]
        client2 = self._make_client({"light.test": points2})
        # Recrear con nuevo client
        mcp2 = DummyMCP()
        hist_mod.register(mcp2, client2)
        raw2 = await mcp2.tools["ha_get_history"](["light.test"])
        result2 = json.loads(raw2)
        pt2 = result2["history"]["light.test"][0]
        self.assertNotEqual(pt2["last_changed"], pt2["last_updated"])

    async def test_no_attributes_flag(self) -> None:
        """Con no_attributes=True, 'attributes' no aparece en los puntos."""
        points = [{"s": "on", "lu": 1_712_000_000.0}]  # sin "a"
        client = self._make_client({"light.test": points})
        mcp = DummyMCP()
        hist_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_history"](["light.test"], no_attributes=True)
        result = json.loads(raw)
        pt = result["history"]["light.test"][0]
        self.assertNotIn("attributes", pt)

    async def test_truncation_by_count(self) -> None:
        """Más de _MAX_STATES_PER_ENTITY puntos por entidad → truncado."""
        from hermes.tools.history import _MAX_STATES_PER_ENTITY
        points = _make_compressed_points(_MAX_STATES_PER_ENTITY + 50)
        client = self._make_client({"light.test": points})
        mcp = DummyMCP()
        hist_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_history"](["light.test"])
        result = json.loads(raw)
        self.assertLessEqual(len(result["history"]["light.test"]), _MAX_STATES_PER_ENTITY)

    async def test_truncation_by_bytes(self) -> None:
        """response_max_bytes muy pequeño → truncado con truncated=True."""
        points = _make_compressed_points(100)
        client = self._make_client({"light.test": points})
        mcp = DummyMCP()
        hist_mod.register(mcp, client, response_max_bytes=500)
        raw = await mcp.tools["ha_get_history"](["light.test"])
        result = json.loads(raw)
        self.assertTrue(result["truncated"])
        self.assertIsNotNone(result["truncated_at"])

    async def test_empty_result(self) -> None:
        """HA devuelve {} → history vacío sin error."""
        client = self._make_client({})
        mcp = DummyMCP()
        hist_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_history"](["light.inexistente"])
        result = json.loads(raw)
        self.assertEqual(result["history"], {})
        self.assertFalse(result["truncated"])

    async def test_ws_error_returned(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(payload, timeout_seconds=30):
            raise HAConnectionError("WS down")
        client.ws_send = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        hist_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_history"](["light.test"])
        result = json.loads(raw)
        self.assertIn("error", result)


class TestLimiteDeRespuestaDelHistorial(unittest.IsolatedAsyncioTestCase):
    """FR-006 de la 009: un historial recortado dice cuánto se dejó fuera.

    Antes solo traía `truncated` y `truncated_at`: el agente no sabía si
    faltaba un estado o 2 500, ni cuál era el tope. Ahora, con `truncated`,
    lleva `_response_limit` (la misma forma que pone el guardián central en
    las demás listas) y la respuesta entera, con el bloque, cabe en el tope.
    """

    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def _pedir(self, puntos: dict, tope: int | None = None) -> tuple[str, dict]:
        client = make_ready_client(self.session, {})

        async def fake_ws_send(payload, timeout_seconds=30):
            return puntos
        client.ws_send = fake_ws_send  # type: ignore[method-assign]
        mcp = DummyMCP()
        if tope is None:
            hist_mod.register(mcp, client)
        else:
            hist_mod.register(mcp, client, response_max_bytes=tope)
        raw = await mcp.tools["ha_get_history"](list(puntos))
        return raw, json.loads(raw)

    async def test_recorte_por_bytes(self) -> None:
        raw, r = await self._pedir({"light.test": _make_compressed_points(100)}, tope=2000)
        self.assertTrue(r["truncated"])
        self.assertIsNotNone(r["truncated_at"])
        lim = r["_response_limit"]
        self.assertEqual(lim["list"], "history")
        self.assertEqual(lim["returned"], len(r["history"]["light.test"]))
        self.assertLess(lim["returned"], 100)
        self.assertEqual(lim["total"], 100)
        self.assertEqual(lim["max_bytes"], 2000)
        self.assertIn("truncated_at", lim["hint"])
        self.assertLessEqual(len(raw.encode("utf-8")), 2000)

    async def test_recorte_por_cantidad_aunque_quepa(self) -> None:
        from hermes.tools.history import _MAX_STATES_PER_ENTITY
        n = _MAX_STATES_PER_ENTITY + 50
        _, r = await self._pedir(
            {"light.test": _make_compressed_points(n)}, tope=10_000_000
        )
        self.assertTrue(r["truncated"])
        lim = r["_response_limit"]
        self.assertEqual(lim["returned"], _MAX_STATES_PER_ENTITY)
        # `total` es lo que devolvió HA, antes del corte por cantidad.
        self.assertEqual(lim["total"], n)

    async def test_la_pista_continua_por_entidad_sin_perder_estados(self) -> None:
        """T043: con una entidad muy activa y otra lenta, la pista no pierde nada.

        El recorte quita primero de la lista más larga y `truncated_at` es el
        más reciente de los últimos estados incluidos, así que pedirlo todo
        desde `truncated_at` (la pista anterior) se saltaba los estados de la
        entidad activa entre su último incluido y ese instante. La pista manda
        seguir cada entidad desde su último estado devuelto; aquí se sigue tal
        cual, simulando a HA con los mismos datos, y no falta ninguno.

        Control negativo: con la pista anterior («call again with start_time
        set to truncated_at») el test falla en las aserciones de la pista.
        """
        base = 1_712_000_000.0
        puntos = {
            "sensor.ocupado": [{"s": str(i), "lu": base + i * 60.0} for i in range(1000)],
            "sensor.lento": [{"s": str(i), "lu": base + i * 6000.0} for i in range(14)],
        }
        _, r = await self._pedir(puntos, tope=40_000)
        self.assertTrue(r["truncated"])
        devueltos = r["history"]
        completo = {
            eid: [hist_mod._expand_state(p) for p in pts] for eid, pts in puntos.items()
        }
        # El escenario de la revisión: la activa se corta antes de `truncated_at`.
        ultimo_ocupado = devueltos["sensor.ocupado"][-1]["last_updated"]
        self.assertLess(ultimo_ocupado, r["truncated_at"])
        desde_truncated_at = [
            s for s in completo["sensor.ocupado"]
            if s["last_updated"] > ultimo_ocupado and s["last_updated"] < r["truncated_at"]
        ]
        self.assertGreater(len(desde_truncated_at), 0)  # lo que perdía la pista anterior

        # La pista dice continuar por entidad y avisa de `truncated_at`.
        pista = r["_response_limit"]["hint"]
        self.assertIn("for each entity", pista)
        self.assertIn("its last returned state", pista)
        self.assertNotIn("call again with start_time set to truncated_at", pista)

        # Seguirla: cada entidad desde el last_updated de su último devuelto
        # (HA incluye el estado en start_time). No se pierde ninguno.
        for eid, estados in completo.items():
            desde = devueltos[eid][-1]["last_updated"]
            continuacion = [s for s in estados if s["last_updated"] >= desde]
            vistos = {s["last_updated"] for s in devueltos[eid] + continuacion}
            self.assertEqual(vistos, {s["last_updated"] for s in estados}, eid)

    async def test_sin_recorte_la_respuesta_de_la_112(self) -> None:
        _, r = await self._pedir({"light.test": _make_compressed_points(3)})
        self.assertEqual(set(r), {"history", "truncated", "truncated_at"})
        self.assertFalse(r["truncated"])
        self.assertIsNone(r["truncated_at"])


# ── Tests ha_get_logbook ───────────────────────────────────────────────────────

class TestGetLogbook(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def _make_client(self, ws_result):
        client = make_ready_client(self.session, {})
        async def fake_ws_send(payload, timeout_seconds=30):
            return ws_result
        client.ws_send = fake_ws_send  # type: ignore[method-assign]
        return client

    async def test_basic_logbook(self) -> None:
        events = _make_logbook_events(5)
        client = self._make_client(events)
        mcp = DummyMCP()
        log_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_logbook"]()
        result = json.loads(raw)
        self.assertEqual(len(result["events"]), 5)
        self.assertEqual(result["count"], 5)
        self.assertFalse(result["truncated"])

    async def test_truncation_by_count(self) -> None:
        from hermes.tools.logbook import _MAX_EVENTS
        events = _make_logbook_events(_MAX_EVENTS + 10)
        client = self._make_client(events)
        mcp = DummyMCP()
        log_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_logbook"]()
        result = json.loads(raw)
        self.assertLessEqual(result["count"], _MAX_EVENTS)

    async def test_truncation_by_bytes(self) -> None:
        events = _make_logbook_events(100)
        client = self._make_client(events)
        mcp = DummyMCP()
        log_mod.register(mcp, client, response_max_bytes=500)
        raw = await mcp.tools["ha_get_logbook"]()
        result = json.loads(raw)
        self.assertTrue(result["truncated"])
        self.assertIsNotNone(result["truncated_at"])

    async def test_empty_result(self) -> None:
        client = self._make_client([])
        mcp = DummyMCP()
        log_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_logbook"]()
        result = json.loads(raw)
        self.assertEqual(result["events"], [])
        self.assertEqual(result["count"], 0)
        self.assertFalse(result["truncated"])

    async def test_entity_ids_filter(self) -> None:
        """entity_ids se pasa al payload WS."""
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            return []
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        log_mod.register(mcp, client)
        await mcp.tools["ha_get_logbook"](entity_ids=["light.salon", "automation.luz"])
        self.assertEqual(received[0]["entity_ids"], ["light.salon", "automation.luz"])

    async def test_ws_error_returned(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(payload, timeout_seconds=30):
            raise HAConnectionError("recorder offline")
        client.ws_send = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        log_mod.register(mcp, client)
        raw = await mcp.tools["ha_get_logbook"]()
        result = json.loads(raw)
        self.assertIn("error", result)
