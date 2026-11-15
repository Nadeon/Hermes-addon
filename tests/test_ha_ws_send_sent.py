"""`HAConnectionError.sent` (spec 031, tramo 3: T033, FR-008, research R-6).

Restaurar un backup no responde hasta terminar y reinicia Core, así que la
tool tiene que distinguir «la orden no salió» (error, nada cambió) de «salió
y no hubo respuesta» (la restauración puede estar en marcha). `ws_send` lo
dice con `sent`:

- False: sin WebSocket, socket cerrado o `send_json` que falla;
- True: plazo agotado tras enviar, o conexión caída con la petición
  pendiente;
- las respuestas de error de HA no cambian (False, con su `code`).

Control negativo (T045 a), comprobado: con `sent` siempre True (en el
constructor) caen 5: `test_por_defecto_false`, `test_sin_websocket`,
`test_socket_cerrado`, `test_send_json_que_falla` y `test_error_de_ha_no_cambia`.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from aiohttp import ClientSession

from hermes.ha import HAConnectionError

from tests._ha_fixture import make_ready_client


class _WS:
    def __init__(self, falla: bool = False) -> None:
        self.closed = False
        self.falla = falla
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        if self.falla:
            raise ConnectionResetError("Cannot write to closing transport")
        self.sent.append(payload)


class _Salud:
    def set_ws_connected(self, value: bool) -> None:
        pass


class TestSent(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.client = make_ready_client(self.session, {})
        self.client._event_subscription_queues = {}
        self.client._health_server = _Salud()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def test_por_defecto_false(self) -> None:
        self.assertFalse(HAConnectionError("x").sent)
        self.assertTrue(HAConnectionError("x", sent=True).sent)

    async def test_sin_websocket(self) -> None:
        self.client._ws = None
        with self.assertRaises(HAConnectionError) as ctx:
            await self.client.ws_send({"type": "backup/restore"})
        self.assertFalse(ctx.exception.sent)

    async def test_socket_cerrado(self) -> None:
        ws = _WS()
        ws.closed = True
        self.client._ws = ws
        with self.assertRaises(HAConnectionError) as ctx:
            await self.client.ws_send({"type": "backup/restore"})
        self.assertFalse(ctx.exception.sent)

    async def test_send_json_que_falla(self) -> None:
        self.client._ws = _WS(falla=True)
        with self.assertRaises(HAConnectionError) as ctx:
            await self.client.ws_send({"type": "backup/restore"})
        self.assertFalse(ctx.exception.sent)
        self.assertIsNone(ctx.exception.code)
        # Nada pendiente que colgar.
        self.assertEqual(self.client._pending_ws_responses, {})

    async def test_timeout_tras_enviar(self) -> None:
        ws = _WS()
        self.client._ws = ws
        with self.assertRaises(HAConnectionError) as ctx:
            await self.client.ws_send({"type": "backup/restore"}, timeout_seconds=0.05)
        self.assertTrue(ctx.exception.sent)
        self.assertEqual(len(ws.sent), 1)

    async def test_conexion_caida_con_la_peticion_pendiente(self) -> None:
        ws = _WS()
        self.client._ws = ws
        tarea = asyncio.create_task(
            self.client.ws_send({"type": "backup/restore"}, timeout_seconds=5))
        await asyncio.sleep(0.02)
        self.assertEqual(len(ws.sent), 1)
        self.client._fail_pending_requests(HAConnectionError("WebSocket cerrado por Home Assistant."))
        with self.assertRaises(HAConnectionError) as ctx:
            await tarea
        self.assertTrue(ctx.exception.sent)

    async def test_error_de_ha_no_cambia(self) -> None:
        ws = _WS()
        self.client._ws = ws
        tarea = asyncio.create_task(
            self.client.ws_send({"type": "backup/restore"}, timeout_seconds=5))
        await asyncio.sleep(0.02)
        await self.client._handle_ws_message({
            "type": "result", "id": ws.sent[0]["id"], "success": False,
            "error": {"code": "password_incorrect", "message": "Incorrect password"},
        })
        with self.assertRaises(HAConnectionError) as ctx:
            await tarea
        self.assertFalse(ctx.exception.sent)
        self.assertEqual(ctx.exception.code, "password_incorrect")


if __name__ == "__main__":
    unittest.main()
