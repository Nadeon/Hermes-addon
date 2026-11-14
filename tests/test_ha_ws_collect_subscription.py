"""`HAClient.ws_collect_subscription` (spec 029, FR-002, SC-005; T004).

`system_health/info` es una suscripción de varios mensajes: HA confirma con un
`result`, manda un evento `initial` con lo que ya sabe y luego un `update` por
cada valor lento, hasta un `finish`. `ws_one_shot_subscription` se queda con el
PRIMER evento, así que hace falta un método que recoja eventos hasta que un
predicado diga que terminó o venza un plazo TOTAL, y que cancele la
suscripción en todos los caminos: si quedara abierta, HA seguiría mandando
eventos por la WebSocket compartida sin nadie al otro lado.

Se prueba con una WebSocket simulada que registra lo enviado; los mensajes de
HA se inyectan con `_handle_ws_message`, como en los tests de fiabilidad.

Control negativo (T018 a), con recuentos en el commit del tramo:
- plazo por evento en vez de total → cae `test_plazo_total_no_por_evento_cancela`;
- quitar el `unsubscribe` del `finally` → caen los de cancelación
  (`test_*_cancela` y `test_sin_confirmacion_en_el_plazo`).
"""

from __future__ import annotations

import asyncio
import time
import unittest
from typing import Any

from aiohttp import ClientSession

from hermes.ha import HAConnectionError

from tests.test_ha_ws_reliability import _prepare_ws_client


def _es_finish(evento: Any) -> bool:
    return isinstance(evento, dict) and evento.get("type") == "finish"


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.client, self.ws = _prepare_ws_client(self.session)

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def _lanzar(self, timeout: float = 2.0) -> asyncio.Task:
        return asyncio.create_task(self.client.ws_collect_subscription(
            {"type": "system_health/info"}, terminado=_es_finish,
            timeout_seconds=timeout))

    async def _id(self) -> int:
        for _ in range(50):
            if self.ws.sent:
                return self.ws.sent[0]["id"]
            await asyncio.sleep(0.01)
        self.fail("no se mandó el comando")

    async def _resultado(self, rid: int, ok: bool = True) -> None:
        msg: dict[str, Any] = {"type": "result", "id": rid, "success": ok}
        if ok:
            msg["result"] = None
        else:
            msg["error"] = {"code": "unknown_command", "message": "Unknown command."}
        await self.client._handle_ws_message(msg)

    async def _evento(self, rid: int, evento: dict[str, Any]) -> None:
        await self.client._handle_ws_message({"type": "event", "id": rid, "event": evento})

    def _cancelaciones(self, rid: int) -> list[dict[str, Any]]:
        return [m for m in self.ws.sent
                if m.get("type") == "unsubscribe_events" and m.get("subscription") == rid]

    def _nada_registrado(self, rid: int) -> None:
        self.assertNotIn(rid, self.client._pending_ws_responses)
        self.assertNotIn(rid, self.client._event_subscription_queues)
        self.assertNotIn(rid, self.client._pending_ws_subscriptions)


class TestRecogida(_Base):
    async def test_tres_eventos_hasta_el_que_termina_cancela(self) -> None:
        tarea = self._lanzar()
        rid = await self._id()
        self.assertEqual(self.ws.sent[0], {"type": "system_health/info", "id": rid})
        await self._resultado(rid)
        eventos = [{"type": "initial", "data": {}},
                   {"type": "update", "domain": "x", "key": "y", "success": True, "data": 1},
                   {"type": "finish"}]
        for e in eventos:
            await self._evento(rid, e)
        recibidos, completo = await asyncio.wait_for(tarea, 1.0)
        self.assertEqual(recibidos, eventos)
        self.assertTrue(completo)
        self.assertEqual(len(self._cancelaciones(rid)), 1)
        self._nada_registrado(rid)

    async def test_eventos_antes_de_esperar_no_se_pierden(self) -> None:
        # HA manda `result`, `initial` y `finish` seguidos cuando no hay nada
        # pendiente: pueden llegar antes de que el método empiece a esperar.
        tarea = self._lanzar()
        rid = await self._id()
        await self._resultado(rid)
        await self._evento(rid, {"type": "initial", "data": {}})
        await self._evento(rid, {"type": "finish"})
        recibidos, completo = await asyncio.wait_for(tarea, 1.0)
        self.assertEqual([e["type"] for e in recibidos], ["initial", "finish"])
        self.assertTrue(completo)

    async def test_plazo_total_no_por_evento_cancela(self) -> None:
        """Eventos cada 0,3 s con un plazo de 1 s: si el plazo fuera por
        evento, la recogida no terminaría nunca (SC-005)."""
        inicio = time.monotonic()
        tarea = self._lanzar(timeout=1.0)
        rid = await self._id()
        await self._resultado(rid)

        async def goteo() -> None:
            n = 0
            while True:
                await self._evento(rid, {"type": "update", "n": n})
                n += 1
                await asyncio.sleep(0.3)

        gotero = asyncio.create_task(goteo())
        try:
            recibidos, completo = await asyncio.wait_for(tarea, 3.0)
        finally:
            gotero.cancel()
        duracion = time.monotonic() - inicio
        self.assertFalse(completo)
        self.assertGreaterEqual(len(recibidos), 2)
        self.assertLess(duracion, 1.8, duracion)
        self.assertEqual(len(self._cancelaciones(rid)), 1)
        self._nada_registrado(rid)


class TestErrores(_Base):
    async def test_error_de_ha_en_el_result_con_codigo_cancela(self) -> None:
        tarea = self._lanzar()
        rid = await self._id()
        await self._resultado(rid, ok=False)
        with self.assertRaises(HAConnectionError) as ctx:
            await asyncio.wait_for(tarea, 1.0)
        self.assertEqual(ctx.exception.code, "unknown_command")
        self.assertEqual(len(self._cancelaciones(rid)), 1)
        self._nada_registrado(rid)

    async def test_websocket_cerrada_antes(self) -> None:
        self.ws.closed = True
        with self.assertRaises(HAConnectionError) as ctx:
            await self.client.ws_collect_subscription(
                {"type": "system_health/info"}, terminado=_es_finish, timeout_seconds=1)
        self.assertIsNone(ctx.exception.code)
        self.assertEqual(self.ws.sent, [])

    async def test_websocket_caida_a_mitad(self) -> None:
        tarea = self._lanzar()
        rid = await self._id()
        await self._resultado(rid)
        await self._evento(rid, {"type": "initial", "data": {}})
        self.client._fail_pending_requests(HAConnectionError("caída"))
        with self.assertRaises(HAConnectionError) as ctx:
            await asyncio.wait_for(tarea, 1.0)
        self.assertIsNone(ctx.exception.code)
        self._nada_registrado(rid)

    async def test_tarea_cancelada_cancela(self) -> None:
        tarea = self._lanzar(timeout=5.0)
        rid = await self._id()
        await self._resultado(rid)
        await self._evento(rid, {"type": "initial", "data": {}})
        await asyncio.sleep(0.05)
        tarea.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await tarea
        self.assertEqual(len(self._cancelaciones(rid)), 1)
        self._nada_registrado(rid)

    async def test_sin_confirmacion_en_el_plazo(self) -> None:
        tarea = self._lanzar(timeout=0.3)
        rid = await self._id()
        with self.assertRaises(HAConnectionError):
            await asyncio.wait_for(tarea, 2.0)
        self.assertEqual(len(self._cancelaciones(rid)), 1)
        self._nada_registrado(rid)


class TestOneShotSinCambios(_Base):
    """FR-002 y FR-020 de la 008: el método nuevo no toca el de un solo
    mensaje. Sus tests de siempre siguen sin cambios (test_tools_templates,
    test_ha_ws_error_code); aquí se comprueba además que sigue devolviendo el
    PRIMER evento y cancelando."""

    async def test_one_shot_devuelve_el_primer_evento(self) -> None:
        tarea = asyncio.create_task(self.client.ws_one_shot_subscription(
            {"type": "subscribe_system_state"}, event_timeout_seconds=1.0))
        rid = await self._id()
        await self._resultado(rid)
        await self._evento(rid, {"home_assistant_restart_required": False})
        await self._evento(rid, {"home_assistant_restart_required": True})
        self.assertEqual(await asyncio.wait_for(tarea, 1.0),
                         {"home_assistant_restart_required": False})
        self.assertEqual(len(self._cancelaciones(rid)), 1)
