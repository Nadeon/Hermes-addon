"""Tests de la tool wait_for_event (los de HACS están en test_tools_hacs.py)."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from aiohttp import ClientSession

from hermes.ha import _WS_CLOSED_SENTINEL
import hermes.tools.wait_for_event as wfe_mod
from hermes.tools.wait_for_event import (
    _compare_value,
    _match_event,
    _resolve_dot_path,
)
from tests._ha_fixture import make_ready_client


# ── DummyMCP ───────────────────────────────────────────────────────────────────


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


# ── FakeHAClientForWait ────────────────────────────────────────────────────────


class FakeHAClientForWait:
    """Fake HAClient mínimo para tests de wait_for_event."""

    def __init__(self) -> None:
        self.ready = True
        self._preloaded_events: list[Any] = []
        self._sub_id_counter = 1
        self._unsubscribed: list[int] = []

    def preload(self, *events: Any) -> None:
        """Pre-carga eventos que se pondrán en la queue al suscribir."""
        self._preloaded_events = list(events)

    async def wait_ready(self, timeout: float = 5.0) -> bool:
        return self.ready

    async def ws_subscribe_events_queue(
        self, event_type: str
    ) -> tuple[int, asyncio.Queue, int]:
        sub_id = self._sub_id_counter
        self._sub_id_counter += 1
        queue: asyncio.Queue = asyncio.Queue()
        for ev in self._preloaded_events:
            queue.put_nowait(ev)
        return sub_id, queue, 0

    async def ws_unsubscribe_events_queue(self, sub_id: int) -> None:
        self._unsubscribed.append(sub_id)


# ── TestEventHelpers ───────────────────────────────────────────────────────────


class TestEventHelpers(unittest.TestCase):
    # _resolve_dot_path

    def test_resolve_dot_path_simple(self) -> None:
        obj = {"data": {"entity_id": "light.kitchen"}}
        self.assertEqual(_resolve_dot_path(obj, "data.entity_id"), "light.kitchen")

    def test_resolve_dot_path_nested(self) -> None:
        obj = {"data": {"new_state": {"state": "on"}}}
        self.assertEqual(_resolve_dot_path(obj, "data.new_state.state"), "on")

    def test_resolve_dot_path_missing(self) -> None:
        obj = {"data": {}}
        self.assertIsNone(_resolve_dot_path(obj, "data.entity_id"))

    # _compare_value

    def test_compare_equals(self) -> None:
        self.assertTrue(_compare_value("on", "on"))

    def test_compare_not_equals(self) -> None:
        self.assertTrue(_compare_value("on", "!=off"))
        self.assertFalse(_compare_value("on", "!=on"))

    def test_compare_greater(self) -> None:
        self.assertTrue(_compare_value(85, ">80"))
        self.assertFalse(_compare_value(75, ">80"))

    def test_compare_less(self) -> None:
        self.assertTrue(_compare_value(10, "<20"))
        self.assertFalse(_compare_value(25, "<20"))

    def test_compare_gte(self) -> None:
        self.assertTrue(_compare_value(80, ">=80"))
        self.assertTrue(_compare_value(81, ">=80"))
        self.assertFalse(_compare_value(79, ">=80"))

    def test_compare_lte(self) -> None:
        self.assertTrue(_compare_value(20, "<=20"))
        self.assertTrue(_compare_value(19, "<=20"))
        self.assertFalse(_compare_value(21, "<=20"))

    def test_compare_numeric_fail(self) -> None:
        self.assertFalse(_compare_value(75, ">80"))

    def test_match_event_no_filters(self) -> None:
        event = {"event_type": "state_changed", "data": {}}
        self.assertTrue(_match_event(event, {}))

    def test_match_event_match(self) -> None:
        event = {"data": {"entity_id": "light.kitchen"}}
        self.assertTrue(_match_event(event, {"data.entity_id": "light.kitchen"}))

    def test_match_event_no_match(self) -> None:
        event = {"data": {"entity_id": "light.bedroom"}}
        self.assertFalse(_match_event(event, {"data.entity_id": "light.kitchen"}))

    def test_match_event_dot_path(self) -> None:
        event = {"data": {"new_state": {"state": "on"}, "old_state": {"state": "off"}}}
        self.assertTrue(_match_event(event, {
            "data.new_state.state": "on",
            "data.old_state.state": "off",
        }))


# ── TestWaitForEvent ───────────────────────────────────────────────────────────


class TestWaitForEvent(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.fake_ha = FakeHAClientForWait()
        self.mcp = DummyMCP()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def _register(self, max_seconds: int = 30, max_concurrent: int = 5) -> None:
        wfe_mod.register(
            self.mcp,
            self.fake_ha,
            wait_for_event_max_seconds=max_seconds,
            wait_for_event_max_concurrent=max_concurrent,
        )

    async def test_wait_match_immediate(self) -> None:
        self._register()
        event = {"event_type": "state_changed", "data": {"entity_id": "light.kitchen"}}
        self.fake_ha.preload(event)

        result = await self.mcp.tools["ha_wait_for_event"](
            None, "state_changed"
        )
        self.assertTrue(result["matched"])
        self.assertEqual(result["event"], event)
        self.assertIn("waited_seconds", result)

    async def test_wait_timeout(self) -> None:
        self._register(max_seconds=30)
        # No events pre-loaded → will timeout
        result = await self.mcp.tools["ha_wait_for_event"](
            None, "state_changed", timeout_seconds=1
        )
        self.assertFalse(result["matched"])
        self.assertEqual(result["reason"], "timeout")

    async def test_wait_ws_reconnect(self) -> None:
        self._register()
        self.fake_ha.preload(_WS_CLOSED_SENTINEL)

        result = await self.mcp.tools["ha_wait_for_event"](
            None, "state_changed"
        )
        self.assertFalse(result["matched"])
        self.assertEqual(result["reason"], "ws_reconnect")
        self.assertIn("note", result)

    async def test_wait_with_filters_no_match_then_match(self) -> None:
        self._register()
        no_match = {"data": {"entity_id": "light.bedroom", "new_state": {"state": "on"}}}
        match = {"data": {"entity_id": "light.kitchen", "new_state": {"state": "on"}}}
        self.fake_ha.preload(no_match, match)

        result = await self.mcp.tools["ha_wait_for_event"](
            None,
            "state_changed",
            filters={"data.entity_id": "light.kitchen"},
        )
        self.assertTrue(result["matched"])
        self.assertEqual(result["event"], match)

    async def test_wait_timeout_exceeded_max(self) -> None:
        self._register(max_seconds=30)
        result = await self.mcp.tools["ha_wait_for_event"](
            None, "state_changed", timeout_seconds=60
        )
        self.assertIn("error", result)
        self.assertIn("exceeds max allowed", result["error"])

    async def test_wait_concurrency_limit(self) -> None:
        self._register(max_seconds=30, max_concurrent=5)
        # Register 5 waits manually by using a slow event source
        manager = None
        # Access the manager via the closure: register again with max_concurrent=1
        mcp2 = DummyMCP()
        fake2 = FakeHAClientForWait()
        wfe_mod.register(mcp2, fake2, wait_for_event_max_seconds=30, wait_for_event_max_concurrent=1)

        # Start one wait that will block (no events, long timeout)
        task = asyncio.create_task(
            mcp2.tools["ha_wait_for_event"](None, "state_changed", timeout_seconds=5)
        )
        # Yield to let the task start and register itself
        await asyncio.sleep(0.05)

        # Second call should be rejected
        result = await mcp2.tools["ha_wait_for_event"](None, "state_changed", timeout_seconds=1)
        self.assertIn("error", result)
        self.assertEqual(result["error"], "too_many_waits")

        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    async def test_cancel_wait_corta_la_espera_al_momento(self) -> None:
        """Cancelar tiene que surtir efecto ya, no en el siguiente keepalive.

        El loop solo miraba `cancel_event` al principio de cada vuelta y se
        quedaba hasta 15 s dentro de `queue.get()`: `ha_cancel_wait` decía "ok"
        y el wait seguía bloqueado todo ese rato.
        """
        self._register(max_seconds=60)
        tarea = asyncio.create_task(
            self.mcp.tools["ha_wait_for_event"](
                None, "state_changed", timeout_seconds=60
            )
        )
        # Dejar que el wait se registre y entre en la espera larga.
        await asyncio.sleep(0.1)

        activos = await self.mcp.tools["ha_list_active_waits"]()
        self.assertEqual(activos["count"], 1)
        wait_id = activos["waits"][0]["wait_id"]

        cancelacion = await self.mcp.tools["ha_cancel_wait"](wait_id)
        self.assertEqual(cancelacion["result"], "ok")

        result = await asyncio.wait_for(tarea, timeout=1.0)
        self.assertFalse(result["matched"])
        self.assertEqual(result["reason"], "cancelled")

    async def test_list_active_waits_empty(self) -> None:
        self._register()
        result = await self.mcp.tools["ha_list_active_waits"]()
        self.assertEqual(result["count"], 0)
        self.assertIsInstance(result["waits"], list)

    async def test_cancel_wait_not_found(self) -> None:
        self._register()
        result = await self.mcp.tools["ha_cancel_wait"]("nonexistent")
        self.assertEqual(result["error"], "not_found")

    async def test_filter_operators_gt(self) -> None:
        self._register()
        event = {"data": {"new_state": {"state": "85"}}}
        self.fake_ha.preload(event)

        result = await self.mcp.tools["ha_wait_for_event"](
            None,
            "state_changed",
            filters={"data.new_state.state": ">80"},
        )
        self.assertTrue(result["matched"])

    async def test_filter_operators_ne(self) -> None:
        self._register()
        # Event with state="on" should NOT match filter "!=on"
        event = {"data": {"new_state": {"state": "on"}}}
        # Second event with state="off" should match
        event2 = {"data": {"new_state": {"state": "off"}}}
        self.fake_ha.preload(event, event2)

        result = await self.mcp.tools["ha_wait_for_event"](
            None,
            "state_changed",
            filters={"data.new_state.state": "!=on"},
        )
        self.assertTrue(result["matched"])
        self.assertEqual(result["event"]["data"]["new_state"]["state"], "off")

    async def test_filter_dot_path_nested(self) -> None:
        self._register()
        event = {"data": {"entity_id": "sensor.temp", "new_state": {"state": "on"}}}
        self.fake_ha.preload(event)

        result = await self.mcp.tools["ha_wait_for_event"](
            None,
            "state_changed",
            filters={"data.new_state.state": "on"},
        )
        self.assertTrue(result["matched"])


# ── Spec 017 (T039, FR-009): gestor de esperas compartido con la de trigger ──


class TestGestorCompartido(unittest.IsolatedAsyncioTestCase):
    """`register` acepta un gestor; con el mismo gestor, `ha_wait_for_event` y
    `ha_wait_for_trigger` cuentan en el mismo cupo. Las entradas de eventos de
    `ha_list_active_waits` conservan exactamente sus claves de antes.

    Control negativo, comprobado y restaurado: ignorando el `manager` recibido
    (creando siempre uno propio) cae `test_dos_registros_comparten_cupo`.
    """

    _CLAVES_EVENTO = {"wait_id", "event_type", "filters", "started_at_iso",
                      "timeout_at_iso", "elapsed_seconds"}

    async def test_dos_registros_comparten_cupo(self) -> None:
        gestor = wfe_mod._WaitManager(max_concurrent=1)
        uno, dos = DummyMCP(), DummyMCP()
        wfe_mod.register(uno, FakeHAClientForWait(), wait_for_event_max_seconds=30,
                         manager=gestor)
        wfe_mod.register(dos, FakeHAClientForWait(), wait_for_event_max_seconds=30,
                         manager=gestor)
        tarea = asyncio.ensure_future(
            uno.tools["ha_wait_for_event"](None, "state_changed", timeout_seconds=5))
        for _ in range(20):
            await asyncio.sleep(0.01)
            if gestor.active_count:
                break
        try:
            r = await dos.tools["ha_wait_for_event"](None, "state_changed", timeout_seconds=1)
            self.assertEqual(r.get("error"), "too_many_waits")
            self.assertEqual((await dos.tools["ha_list_active_waits"]())["count"], 1)
        finally:
            for w in list(gestor._active):
                gestor.cancel(w)
            await tarea

    async def test_entrada_de_evento_con_las_claves_de_siempre(self) -> None:
        gestor = wfe_mod._WaitManager()
        await gestor.register(wfe_mod._ActiveWait(
            wait_id="a", event_type="state_changed", filters={}, started_at=0.0,
            timeout_at=1.0))
        self.assertEqual(set(gestor.list_active()[0]), self._CLAVES_EVENTO)

    async def test_entrada_de_trigger_con_kind_y_plataforma(self) -> None:
        gestor = wfe_mod._WaitManager()
        await gestor.register(wfe_mod._ActiveWait(
            wait_id="b", event_type="", filters={}, started_at=0.0, timeout_at=1.0,
            kind="trigger", trigger_platform="state"))
        entrada = gestor.list_active()[0]
        self.assertEqual(entrada["kind"], "trigger")
        self.assertEqual(entrada["trigger_platform"], "state")
        self.assertEqual(set(entrada), {"wait_id", "kind", "trigger_platform",
                                        "started_at_iso", "timeout_at_iso",
                                        "elapsed_seconds"})

    async def test_sin_gestor_crea_el_suyo(self) -> None:
        mcp = DummyMCP()
        wfe_mod.register(mcp, FakeHAClientForWait(), wait_for_event_max_seconds=30,
                         wait_for_event_max_concurrent=2)
        r = await mcp.tools["ha_list_active_waits"]()
        self.assertEqual(r["max_concurrent"], 2)
