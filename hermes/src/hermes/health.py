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
import errno
import socket
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

        # Probar el bind ANTES de dárselo a uvicorn. Si el puerto o la
        # dirección no están disponibles, uvicorn hace `sys.exit(1)` dentro de
        # la task del health: el proceso se muere sin una sola línea de Hermes
        # que explique por qué, porque `server.serve()` corre en otra task y
        # nadie mira su resultado. Fuera de HAOS (o sin `host_network: true`)
        # 172.30.32.1 no es una dirección local y ese era exactamente el caso.
        self._precheck_bind()

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

    def _precheck_bind(self) -> None:
        """Comprueba que se puede escuchar en (host, port), o explica por qué no.

        Se abre un socket, se bindea y se cierra sin escuchar: no queda nada en
        TIME_WAIT y uvicorn vuelve a bindear un instante después. Lo que se gana
        es el diagnóstico —errno incluido— en vez de una muerte muda.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # El mismo flag que pone uvicorn: si no, este sondeo podría fallar
            # por una razón que el bind de verdad no tendría.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self._bind_host, self._bind_port))
        except OSError as exc:
            pista = _pista_de_bind(exc, self._bind_host)
            logger.error(
                "health_bind_failed",
                host=self._bind_host,
                port=self._bind_port,
                errno=exc.errno,
                error=str(exc),
                hint=pista,
            )
            raise RuntimeError(
                f"No se puede escuchar el health en {self._bind_host}:"
                f"{self._bind_port} ({exc.strerror or exc}, errno={exc.errno}). "
                f"{pista}"
            ) from exc
        finally:
            sock.close()

    async def stop(self) -> None:
        """Detiene el servidor de health."""
        if self._server_task and not self._server_task.done():
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass


def _pista_de_bind(exc: OSError, host: str) -> str:
    """Qué hacer ante el fallo de bind, según el errno.

    El mensaje se escribe para quien lo va a leer en el log del add-on, que casi
    siempre es una de dos personas: quien ejecuta Hermes fuera de HAOS (la
    bridge de hassio no existe en su máquina) y quien se ha quedado sin
    `host_network: true` tras tocar el manifiesto.
    """
    if exc.errno in (errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT):
        return (
            f"{host} no es una dirección local de esta máquina. Dentro de HAOS "
            f"la aporta la red puente de hassio y hace falta "
            f"`host_network: true` en el manifiesto del add-on; fuera de HAOS, "
            f"arranca con HERMES_HEALTH_BIND=127.0.0.1."
        )
    if exc.errno == errno.EADDRINUSE:
        return (
            "El puerto ya está ocupado. ¿Hay otra instancia de Hermes "
            "arrancada, o un add-on escuchando en ese puerto del host?"
        )
    if exc.errno == errno.EACCES:
        return "El proceso no tiene permiso para escuchar en esa dirección/puerto."
    return "Revisa la configuración de red del add-on."
