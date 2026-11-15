"""El plazo agotado de aiohttp sale como `HATimeoutError` en todo `HAClient`
(cierre de robustez de la 1.2.0).

aiohttp avisa del plazo con `asyncio.TimeoutError` (o `ServerTimeoutError`),
que no es un `HAConnectionError`: se escapaba de las tools que solo capturan
ese. Ahora el REST de Core, el del Supervisor y el WebSocket lo convierten en
`HATimeoutError`, que es a la vez `HAConnectionError` y `TimeoutError`, y
respeta el contrato de `sent`: `None` en REST (no se sabe si el plazo venció
conectando o esperando la respuesta) y `True` en el WebSocket (la orden ya
salió). Nunca `False`.

Controles negativos comprobados:
- quitar el `with _plazo_como_error(...)` de `_request_json` → caen los casos
  de REST de Core (sale el `TimeoutError` crudo);
- quitar `TimeoutError` de las bases de `HATimeoutError` → caen
  `test_es_las_dos_cosas` aquí y, en las tools, los casos «con el plazo del
  cliente» (p. ej. `sv_update_core` daría la configuración por inválida).
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest import mock

import aiohttp
from aiohttp import ClientSession
from aioresponses import aioresponses

from hermes.ha import HAConnectionError, HATimeoutError
from tests._ha_fixture import REST_BASE, SUPERVISOR_BASE, make_ready_client


class _FakeWS:
    """WebSocket que acepta lo que se le manda y nunca contesta."""

    def __init__(self) -> None:
        self.closed = False
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)


def _plazos() -> list[BaseException]:
    # Los dos que lanza aiohttp: el genérico y el suyo propio.
    return [asyncio.TimeoutError(), aiohttp.ServerTimeoutError("read timeout")]


class TestHATimeoutError(unittest.TestCase):
    def test_es_las_dos_cosas(self) -> None:
        exc = HATimeoutError("x")
        self.assertIsInstance(exc, HAConnectionError)
        self.assertIsInstance(exc, TimeoutError)
        self.assertIsNone(exc.sent)


class TestRestConvierteElPlazo(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.client = make_ready_client(self.session)

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def _comprobar(self, metodo: str, url: str, llamada: Any) -> None:
        for plazo in _plazos():
            with self.subTest(plazo=type(plazo).__name__), aioresponses() as m:
                m.add(url, metodo, exception=plazo)
                with self.assertRaises(HATimeoutError) as ctx:
                    await llamada()
                # REST: no se sabe si salió. `False` diría «no se hizo nada».
                self.assertIsNone(ctx.exception.sent)
                self.assertIsNone(ctx.exception.status)

    async def test_core_request_json(self) -> None:
        await self._comprobar("GET", f"{REST_BASE}/services", self.client.get_services)

    async def test_core_call_service(self) -> None:
        await self._comprobar(
            "POST", f"{REST_BASE}/services/light/turn_on",
            lambda: self.client.call_service("light", "turn_on", {}))

    async def test_core_config(self) -> None:
        await self._comprobar(
            "GET", f"{REST_BASE}/config/automation/config/abc",
            lambda: self.client.config_read("automation", "abc"))

    async def test_core_texto(self) -> None:
        await self._comprobar(
            "GET", f"{REST_BASE}/error_log",
            lambda: self.client.rest_get_text_tail("/error_log", lines=5))

    async def test_core_imagen(self) -> None:
        await self._comprobar(
            "GET", f"{REST_BASE}/camera_proxy/camera.entrada",
            lambda: self.client.rest_get_image(
                "/camera_proxy/camera.entrada", max_bytes=1000))

    async def test_supervisor_json(self) -> None:
        await self._comprobar(
            "POST", f"{SUPERVISOR_BASE}/core/restart",
            lambda: self.client.sv_request("POST", "/core/restart"))

    async def test_supervisor_texto(self) -> None:
        await self._comprobar(
            "GET", f"{SUPERVISOR_BASE}/addons/x/logs",
            lambda: self.client.sv_request_text("/addons/x/logs"))

    async def test_un_error_http_no_se_toca(self) -> None:
        # Solo el plazo se convierte; un 500 sigue siendo un error con estado.
        with aioresponses() as m:
            m.get(f"{REST_BASE}/services", status=500, body="boom")
            with self.assertRaises(HAConnectionError) as ctx:
                await self.client.get_services()
        self.assertNotIsInstance(ctx.exception, TimeoutError)
        self.assertEqual(ctx.exception.status, 500)


async def _sin_esperar(aw: Any, timeout: float | None = None) -> Any:
    """`asyncio.wait_for` que vence al momento (sin esperar el plazo real)."""
    if asyncio.isfuture(aw):
        aw.cancel()
    elif asyncio.iscoroutine(aw):
        aw.close()
    raise asyncio.TimeoutError


class TestWebSocketConvierteElPlazo(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.client = make_ready_client(self.session)
        self.client._event_subscription_queues = {}
        self.client._reconnect_generation = 0
        self.client._ws = _FakeWS()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def _comprobar(self, llamada: Any) -> None:
        with self.assertRaises(HATimeoutError) as ctx:
            await llamada()
        # WebSocket: la orden ya salió, HA puede estar ejecutándola.
        self.assertIs(ctx.exception.sent, True)
        self.assertTrue(self.client._ws.sent, "la orden tenía que haber salido")

    async def test_ws_send(self) -> None:
        await self._comprobar(
            lambda: self.client.ws_send({"type": "x"}, timeout_seconds=0.01))

    async def test_suscripcion_de_un_evento(self) -> None:
        await self._comprobar(lambda: self.client.ws_one_shot_subscription(
            {"type": "render_template"}, event_timeout_seconds=0.01))

    async def test_suscripcion_que_recoge(self) -> None:
        await self._comprobar(lambda: self.client.ws_collect_subscription(
            {"type": "system_health/info"}, terminado=lambda _: True,
            timeout_seconds=0.01))

    async def test_suscripcion_con_cola(self) -> None:
        # Su plazo de confirmación es fijo (10 s): se adelanta el vencimiento.
        with mock.patch("hermes.ha.asyncio.wait_for", _sin_esperar):
            await self._comprobar(
                lambda: self.client.ws_subscribe_queue({"type": "subscribe_trigger"}))


if __name__ == "__main__":
    unittest.main()
