"""Regresiones de fiabilidad del cliente WS/REST de Home Assistant.

Cubre tres fallos que compartían síntoma —el cliente MCP se queda esperando
sin necesidad— y uno de forma de respuesta:

1. `ws_send` sostenía el lock durante la espera de la respuesta, así que un
   comando sin contestar serializaba todo el tráfico WS detrás de él.
2. Una caída de la conexión solo fallaba las respuestas pendientes del bucle
   de lectura: suscripciones y colas de eventos se enteraban al vencer su
   propio timeout.
3. `get_state` convertía el 404 de una entidad inexistente en un error de
   conexión.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes.ha import HAConnectionError, _WS_CLOSED_SENTINEL

from tests._ha_fixture import REST_BASE, make_ready_client


class FakeWS:
    """WebSocket mínimo: registra lo que se le envía y nunca contesta solo."""

    def __init__(self) -> None:
        self.closed = False
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)


class FakeHealthServer:
    def __init__(self) -> None:
        self.ws_connected: bool | None = None

    def set_ws_connected(self, value: bool) -> None:
        self.ws_connected = value


def _prepare_ws_client(session: ClientSession):
    client = make_ready_client(session, {})
    client._event_subscription_queues = {}
    client._reconnect_generation = 0
    client._health_server = FakeHealthServer()
    ws = FakeWS()
    client._ws = ws
    return client, ws


class TestWsSendConcurrency(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.client, self.ws = _prepare_ws_client(self.session)

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_stalled_command_no_bloquea_a_los_demas(self) -> None:
        """Un comando sin respuesta no puede retrasar a otro que sí la tiene."""
        stalled = asyncio.create_task(
            self.client.ws_send({"type": "stalled"}, timeout_seconds=10)
        )
        await asyncio.sleep(0.05)

        rapido = asyncio.create_task(
            self.client.ws_send({"type": "rapido"}, timeout_seconds=10)
        )
        await asyncio.sleep(0.05)

        # El segundo comando tiene que haber SALIDO ya por el socket: con el
        # lock retenido durante la espera se quedaba sin enviar hasta que el
        # primero venciera su timeout.
        self.assertEqual(len(self.ws.sent), 2, self.ws.sent)
        self.assertEqual(self.ws.sent[1]["type"], "rapido")

        await self.client._handle_ws_message({
            "type": "result",
            "id": self.ws.sent[1]["id"],
            "success": True,
            "result": "ok",
        })

        resultado = await asyncio.wait_for(rapido, timeout=1.0)
        self.assertEqual(resultado, "ok")
        self.assertFalse(stalled.done())

        stalled.cancel()
        try:
            await stalled
        except asyncio.CancelledError:
            pass  # la cancelación es el desenlace esperado de la tarea colgada

    async def test_socket_cerrado_mientras_se_espera_el_lock(self) -> None:
        """El socket se revalida CON el lock cogido, no solo antes de pedirlo."""

        async def acaparar_lock() -> None:
            async with self.client._ws_request_lock:
                await asyncio.sleep(0.05)
                # Simula lo que hace una reconexión: el socket que se había
                # visto abierto deja de servir.
                self.ws.closed = True

        hog = asyncio.create_task(acaparar_lock())
        await asyncio.sleep(0)  # que el acaparador coja el lock primero

        with self.assertRaises(HAConnectionError) as ctx:
            await self.client.ws_send({"type": "tarde"}, timeout_seconds=1)

        self.assertIn("no disponible", str(ctx.exception))
        self.assertEqual(self.ws.sent, [])  # no se escribió en el socket muerto
        self.assertIsNone(await hog)


class TestFailPendingOnDisconnect(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.client, self.ws = _prepare_ws_client(self.session)

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_fail_pending_tambien_falla_suscripciones(self) -> None:
        loop = asyncio.get_running_loop()
        respuesta = loop.create_future()
        suscripcion = loop.create_future()
        self.client._pending_ws_responses[1] = respuesta
        self.client._pending_ws_subscriptions[2] = suscripcion

        self.client._fail_pending_requests(HAConnectionError("caída"))

        self.assertIsInstance(respuesta.exception(), HAConnectionError)
        self.assertIsInstance(suscripcion.exception(), HAConnectionError)
        self.assertEqual(self.client._pending_ws_subscriptions, {})

    async def test_fail_pending_avisa_a_las_colas_de_eventos(self) -> None:
        cola: asyncio.Queue = asyncio.Queue()
        self.client._event_subscription_queues[7] = cola

        self.client._fail_pending_requests(HAConnectionError("caída"))

        self.assertIs(cola.get_nowait(), _WS_CLOSED_SENTINEL)
        self.assertEqual(self.client._event_subscription_queues, {})

    async def test_fallo_de_conexion_desbloquea_lo_pendiente(self) -> None:
        """Un fallo en connect/auth/subscribe no pasa por el bucle de lectura."""
        loop = asyncio.get_running_loop()
        respuesta = loop.create_future()
        suscripcion = loop.create_future()
        cola: asyncio.Queue = asyncio.Queue()
        self.client._pending_ws_responses[1] = respuesta
        self.client._pending_ws_subscriptions[2] = suscripcion
        self.client._event_subscription_queues[3] = cola

        async def conexion_que_falla() -> None:
            raise HAConnectionError("auth rechazada")

        self.client._connect_and_watch = conexion_que_falla  # type: ignore[assignment]

        tarea = asyncio.create_task(self.client._run_background())
        await asyncio.sleep(0.05)
        tarea.cancel()
        try:
            await tarea
        except asyncio.CancelledError:
            pass  # la cancelación es el desenlace esperado de la tarea colgada

        self.assertIsInstance(respuesta.exception(), HAConnectionError)
        self.assertIsInstance(suscripcion.exception(), HAConnectionError)
        self.assertIs(cola.get_nowait(), _WS_CLOSED_SENTINEL)


class TestGetState404(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.client = make_ready_client(self.session, {})

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_get_state_404_devuelve_none(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/light.fantasma",
                status=404,
                body="Entity not found.",
            )
            self.assertIsNone(await self.client.get_state("light.fantasma"))

    async def test_get_state_500_sigue_siendo_error(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/light.salon",
                status=500,
                body="boom",
            )
            with self.assertRaises(HAConnectionError):
                await self.client.get_state("light.salon")


class TestGetStateToolNotFound(unittest.IsolatedAsyncioTestCase):
    """La tool tiene que traducir el 404 al resultado documentado."""

    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.client = make_ready_client(self.session, {})
        import hermes.tools.ha as ha_tools

        class DummyMCP:
            def __init__(self) -> None:
                self.tools: dict[str, Any] = {}

            def tool(self):
                def decorator(fn):
                    self.tools[fn.__name__] = fn
                    return fn
                return decorator

        self.mcp = DummyMCP()
        ha_tools.register(self.mcp, self.client)

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_ha_get_state_entidad_inexistente(self) -> None:
        with aioresponses() as m:
            m.get(
                f"{REST_BASE}/states/light.fantasma",
                status=404,
                body="Entity not found.",
            )
            result = await self.mcp.tools["ha_get_state"]("light.fantasma")
        self.assertEqual(
            result, {"error": "not_found", "entity_id": "light.fantasma"}
        )

    async def test_ha_get_state_con_ha_caido_no_finge_not_found(self) -> None:
        with aioresponses() as m:
            m.get(f"{REST_BASE}/states/light.salon", status=502, body="bad gateway")
            with self.assertRaises(HAConnectionError):
                await self.mcp.tools["ha_get_state"]("light.salon")


if __name__ == "__main__":
    unittest.main()
