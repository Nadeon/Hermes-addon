"""Hermes — Endpoint /health con 4 estados.

Se levanta muy temprano en el boot (paso 3.5) en 172.30.32.1:8766
para que el watchdog del Supervisor no reciba ECONNREFUSED durante
los pasos largos del boot.

Estados:
  (a) booting       — pasos 3.5 a 8, devuelve 200 fijo
  (b) healthy       — arranque pleno + grace period
  (c) degraded      — WS caída en reconexión, 200 con body degraded
  (d) degraded_long — pasada la tolerancia de reconexión, 200 igualmente

Por qué (d) ya NO devuelve 503: el 503 hacía que el watchdog del Supervisor
reiniciara el add-on, y un reinicio nunca arregla una caída del core de HA —
solo la empeora. Al reiniciar, el paso 8 del boot volvía a encontrarse el core
caído, el watchdog reintentaba un número acotado de veces y acababa dejando
Hermes parado para siempre, cuando el bucle de reconexión de `hermes.ha` se
habría recuperado solo en cuanto el core volviera.

`health_reconnect_tolerance_seconds` se sigue aceptando (no rompe configs
existentes) pero ya solo distingue "degraded" de "degraded_long" en el cuerpo
de la respuesta: sirve para diagnosticar, no para matar el proceso.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from hermes import __version__

logger = structlog.get_logger(__name__)


class HealthServer:
    """Servidor de health check para el watchdog del Supervisor."""

    def __init__(
        self,
        bind_host: str = "172.30.32.1",
        bind_port: int = 8766,
        reconnect_tolerance_seconds: int = 300,
    ) -> None:
        self._bind_host = bind_host
        self._bind_port = bind_port
        self._reconnect_tolerance = reconnect_tolerance_seconds

        # Eventos de estado
        self._full_health_ready = asyncio.Event()
        self._boot_start_time = time.monotonic()
        self._boot_step = 0

        # Estado del WS (lo actualiza hermes.ha.HAClient)
        self._ws_connected = True
        self._ws_disconnected_since: float | None = None

        # Task del servidor
        self._server_task: asyncio.Task[None] | None = None

    @property
    def full_health_ready(self) -> asyncio.Event:
        """Evento que marca la transición de booting a operacional."""
        return self._full_health_ready

    def set_boot_step(self, step: int) -> None:
        """Actualiza el paso de boot actual (para el body de /health)."""
        self._boot_step = step

    def set_bind_host(self, host: str) -> None:
        """Configura el host de bind antes de llamar a start()."""
        self._bind_host = host

    def set_ws_connected(self, connected: bool) -> None:
        """Actualiza el estado de la conexión WS con HA."""
        self._ws_connected = connected
        if connected:
            self._ws_disconnected_since = None
        elif self._ws_disconnected_since is None:
            self._ws_disconnected_since = time.monotonic()

    async def _health_endpoint(self, request: Request) -> JSONResponse:
        """Handler del endpoint /health."""
        peer_ip = request.client.host if request.client else "unknown"
        logger.debug("health_check", peer_ip=peer_ip)

        now = time.monotonic()

        # Estado (a): booting
        if not self._full_health_ready.is_set():
            elapsed = now - self._boot_start_time
            return JSONResponse(
                {
                    "status": "booting",
                    "step": self._boot_step,
                    "elapsed_seconds": round(elapsed, 1),
                    "version": __version__,
                },
                status_code=200,
            )

        # Estado (b)/(c)/(d): operacional
        body: dict[str, Any] = {
            "version": __version__,
            "ws_connected": self._ws_connected,
        }

        if self._ws_connected:
            body["status"] = "healthy"
            return JSONResponse(body, status_code=200)

        # WS desconectada — ¿cuánto tiempo?
        disconnected_for = 0.0
        if self._ws_disconnected_since is not None:
            disconnected_for = now - self._ws_disconnected_since

        body["reconnecting_for_seconds"] = round(disconnected_for, 1)

        if disconnected_for < self._reconnect_tolerance:
            # Estado (c): degradado tolerable
            body["status"] = "degraded"
            return JSONResponse(body, status_code=200)

        # Estado (d): degradado prolongado. 200 a propósito — ver el docstring
        # del módulo: un 503 aquí provoca un reinicio del watchdog que no
        # arregla una caída del core y sí puede dejar el add-on parado del todo.
        body["status"] = "degraded_long"
        body["reconnect_tolerance_seconds"] = self._reconnect_tolerance
        return JSONResponse(body, status_code=200)

    def _create_app(self) -> Starlette:
        """Crea la app Starlette minimalista para /health."""
        return Starlette(
            routes=[Route("/health", self._health_endpoint, methods=["GET"])],
        )

    async def start(self, *, host: str | None = None) -> None:
        """Arranca el servidor de health en background.

        Args:
            host: override del bind host (si no se pasa, usa el del __init__).
        """
        if host is not None:
            self._bind_host = host

        app = self._create_app()

        config = uvicorn.Config(
            app=app,
            host=self._bind_host,
            port=self._bind_port,
            log_level="error",
            access_log=False,
            log_config=None,
        )
        server = uvicorn.Server(config)

        self._server_task = asyncio.create_task(
            server.serve(), name="health_server"
        )

        logger.info(
            "health_server_started",
            host=self._bind_host,
            port=self._bind_port,
        )

    async def stop(self) -> None:
        """Detiene el servidor de health."""
        if self._server_task and not self._server_task.done():
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
