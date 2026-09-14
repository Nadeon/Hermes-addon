"""Una caída larga del core de HA no puede dejar Hermes parado para siempre.

El ciclo que se reproducía en producción:

  1. El core de HA se cae (actualización larga, reinicio, disco lento…).
  2. Pasada `health_reconnect_tolerance_seconds`, `/health` devolvía 503.
  3. El watchdog del Supervisor leía el 503 y reiniciaba el add-on.
  4. El paso 8 del boot se encontraba el core todavía caído y salía con
     `sys.exit(1)`.
  5. El watchdog reintenta un número acotado de veces y se rinde.

Resultado: Hermes queda parado aunque el core vuelva, cuando el bucle de
reconexión de `hermes.ha` se habría recuperado solo sin tocar nada.

Los dos extremos se arreglan por separado y aquí se prueban por separado:
`/health` ya no devuelve 503 por una desconexión larga (un reinicio no arregla
una caída del core) y el paso 8 ya no es fatal.
"""

from __future__ import annotations

import asyncio
import time
import unittest

from starlette.testclient import TestClient

from hermes.__main__ import _connect_ha_ws
from hermes.health import HealthServer


def _servidor_operacional(tolerancia: int = 300) -> HealthServer:
    """HealthServer ya arrancado del todo (fuera del estado `booting`)."""
    server = HealthServer(reconnect_tolerance_seconds=tolerancia)
    server.full_health_ready.set()
    return server


class TestHealthDuranteUnaCaidaDelCore(unittest.TestCase):
    def _get(self, server: HealthServer):
        with TestClient(server._create_app()) as client:
            return client.get("/health")

    def test_conectado_es_healthy(self) -> None:
        server = _servidor_operacional()
        resp = self._get(server)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "healthy")

    def test_desconexion_corta_es_degraded_con_200(self) -> None:
        server = _servidor_operacional(tolerancia=300)
        server.set_ws_connected(False)
        resp = self._get(server)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "degraded")

    def test_desconexion_larga_ya_no_devuelve_503(self) -> None:
        """El caso del bug: el 503 disparaba el watchdog sin arreglar nada."""
        server = _servidor_operacional(tolerancia=300)
        server.set_ws_connected(False)
        # Simular que la WS lleva caída mucho más que la tolerancia.
        server._ws_disconnected_since = time.monotonic() - 3600

        resp = self._get(server)

        self.assertEqual(
            resp.status_code,
            200,
            "un 503 aquí hace que el watchdog reinicie el add-on, y reiniciar "
            "no levanta el core de HA",
        )
        cuerpo = resp.json()
        self.assertEqual(cuerpo["status"], "degraded_long")
        self.assertFalse(cuerpo["ws_connected"])
        self.assertGreaterEqual(cuerpo["reconnecting_for_seconds"], 3600)
        # La opción se sigue aceptando y se sigue viendo: ahora solo distingue
        # `degraded` de `degraded_long`, no mata el proceso.
        self.assertEqual(cuerpo["reconnect_tolerance_seconds"], 300)

    def test_reconexion_vuelve_a_healthy(self) -> None:
        server = _servidor_operacional(tolerancia=1)
        server.set_ws_connected(False)
        server._ws_disconnected_since = time.monotonic() - 3600
        server.set_ws_connected(True)
        resp = self._get(server)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "healthy")


class _ClienteHAFalso:
    """Doble de `HAClient` que reproduce lo que hace el real al expirar.

    `HAClient.start` lanza la task de reconexión en segundo plano y solo espera
    al evento de conexión: si el plazo se agota, lanza `HAConnectionError` pero
    NO cancela la task, que sigue reintentando. El doble hace lo mismo para que
    el test pueda comprobar que el paso 8 la deja viva.
    """

    def __init__(self, *, conecta: bool) -> None:
        self._conecta = conecta
        self.background_task: asyncio.Task[None] | None = None

    async def _bucle_reconexion(self) -> None:
        while True:
            await asyncio.sleep(0.01)

    async def start(self, timeout_seconds: int = 30) -> None:
        self.background_task = asyncio.create_task(self._bucle_reconexion())
        if not self._conecta:
            raise RuntimeError("No se pudo conectar al WebSocket de HA.")


class TestPaso8NoEsFatal(unittest.IsolatedAsyncioTestCase):
    async def test_sin_ws_el_boot_continua(self) -> None:
        """Antes esto era `sys.exit(1)` y condenaba al add-on al watchdog."""
        cliente = _ClienteHAFalso(conecta=False)

        listo = await _connect_ha_ws(cliente, 1)  # type: ignore[arg-type]

        self.assertFalse(listo, "debe informar de que la WS no quedó lista")
        # Y sobre todo: no ha salido del proceso ni ha propagado la excepción.
        self.assertIsNotNone(cliente.background_task)
        assert cliente.background_task is not None
        self.assertFalse(
            cliente.background_task.done(),
            "el bucle de reconexión debe seguir vivo tras el paso 8",
        )
        cliente.background_task.cancel()

    async def test_sin_ws_no_sale_del_proceso(self) -> None:
        """`sys.exit` levanta SystemExit: que no se escape de aquí."""
        cliente = _ClienteHAFalso(conecta=False)
        try:
            await _connect_ha_ws(cliente, 1)  # type: ignore[arg-type]
        except SystemExit:  # pragma: no cover — es el bug
            self.fail("el paso 8 no debe abortar el arranque")
        finally:
            if cliente.background_task is not None:
                cliente.background_task.cancel()

    async def test_con_ws_devuelve_listo(self) -> None:
        cliente = _ClienteHAFalso(conecta=True)
        listo = await _connect_ha_ws(cliente, 1)  # type: ignore[arg-type]
        self.assertTrue(listo)
        assert cliente.background_task is not None
        cliente.background_task.cancel()


if __name__ == "__main__":
    unittest.main()
