"""Tests de `HAClient.ws_subscribe_queue` (spec 017, T038, FR-009).

`ha_wait_for_trigger` necesita una suscripción que no es `subscribe_events`
(`subscribe_trigger`). En vez de copiar el montaje y la limpieza de
`ws_subscribe_events_queue` —que ya costó un arreglo (suscripciones
huérfanas en HA, `TestSubscriptionIsNeverOrphaned`)—, se generaliza:
`ws_subscribe_queue(payload)` hace todo y `ws_subscribe_events_queue` delega
en él con el mismo payload de siempre.

Control negativo, comprobado y restaurado: quitando el `_ws_unsubscribe`
del camino de rechazo (`except BaseException`) de `ws_subscribe_queue`, cae
`test_rechazo_de_ha_limpia_y_cancela`.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from hermes.ha import HAClient, HAConnectionError


class _Salud:
    def set_ws_connected(self, _v):
        pass


class _Base(unittest.IsolatedAsyncioTestCase):
    def _cliente(self) -> HAClient:
        cliente = HAClient(supervisor_base_url="http://supervisor",
                           supervisor_token="t", health_server=_Salud())
        self.enviados: list[dict] = []
        enviados = self.enviados

        class _WS:
            closed = False

            async def send_json(_self, payload):
                enviados.append(payload)

        cliente._ws = _WS()
        return cliente


class TestSuscripcionGenerica(_Base):
    async def test_envia_el_payload_con_id_y_entrega_eventos(self) -> None:
        cliente = self._cliente()

        async def _ok(fut, timeout=None):
            return None

        trigger = {"trigger": "state", "entity_id": "input_boolean.prueba"}
        with mock.patch("hermes.ha.asyncio.wait_for", new=_ok):
            sub_id, cola, generacion = await cliente.ws_subscribe_queue(
                {"type": "subscribe_trigger", "trigger": trigger}
            )

        self.assertEqual(self.enviados, [
            {"id": sub_id, "type": "subscribe_trigger", "trigger": trigger},
        ])
        self.assertEqual(generacion, cliente._reconnect_generation)
        # Un evento con ese id llega a la cola, como en `subscribe_events`.
        evento = {"variables": {"trigger": {"platform": "state"}}, "context": {}}
        await cliente._handle_ws_message({"id": sub_id, "type": "event", "event": evento})
        self.assertEqual(cola.get_nowait(), evento)

    async def test_rechazo_de_ha_limpia_y_cancela(self) -> None:
        cliente = self._cliente()
        with mock.patch(
            "hermes.ha.asyncio.wait_for",
            side_effect=HAConnectionError("HA WS command failed: bad", code="invalid_format"),
        ):
            with self.assertRaises(HAConnectionError) as ctx:
                await cliente.ws_subscribe_queue({"type": "subscribe_trigger", "trigger": {}})
        self.assertEqual(ctx.exception.code, "invalid_format")
        self.assertEqual(cliente._event_subscription_queues, {})
        self.assertEqual(cliente._pending_ws_responses, {})
        self.assertIn("unsubscribe_events", [p.get("type") for p in self.enviados])

    async def test_plazo_limpia_y_cancela(self) -> None:
        cliente = self._cliente()
        with mock.patch("hermes.ha.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            with self.assertRaises(HAConnectionError):
                await cliente.ws_subscribe_queue({"type": "subscribe_trigger", "trigger": {}})
        self.assertEqual(cliente._event_subscription_queues, {})
        self.assertEqual(cliente._pending_ws_responses, {})
        self.assertIn("unsubscribe_events", [p.get("type") for p in self.enviados])

    async def test_sin_websocket(self) -> None:
        cliente = self._cliente()
        cliente._ws = None
        with self.assertRaises(HAConnectionError):
            await cliente.ws_subscribe_queue({"type": "subscribe_trigger", "trigger": {}})


class TestEventosDelegaSinCambios(_Base):
    async def test_payload_exacto_de_siempre(self) -> None:
        cliente = self._cliente()

        async def _ok(fut, timeout=None):
            return None

        with mock.patch("hermes.ha.asyncio.wait_for", new=_ok):
            sub_id, _cola, _gen = await cliente.ws_subscribe_events_queue("x")
        self.assertEqual(self.enviados, [
            {"id": sub_id, "type": "subscribe_events", "event_type": "x"},
        ])

    async def test_texto_del_plazo_de_siempre(self) -> None:
        cliente = self._cliente()
        with mock.patch("hermes.ha.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            with self.assertRaises(HAConnectionError) as ctx:
                await cliente.ws_subscribe_events_queue("call_service")
        self.assertIn("'call_service'", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
