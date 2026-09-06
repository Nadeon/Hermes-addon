"""Hermes — Arranque del servidor MCP.

Boot sequence con 9 pasos en orden estricto. Cada paso está numerado
con comentarios para que ningún refactor futuro los mueva por accidente.

TLS: NO hay TLS en este proceso. Lo termina siempre el componente de delante
—Tailscale Funnel, o el proxy inverso en `network_mode: reverse_proxy`— y desde
ahí llega HTTP plano a `mcp_bind:8765`.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import sys
from pathlib import Path

import structlog
import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount

from hermes import __version__
from hermes.config import (
    HA_CORE_LAST_TESTED,
    HA_CORE_MIN_SUPPORTED,
    HEALTH_PORT,
    MCP_PORT,
    HermesConfig,
    load_config,
)
from hermes.crash_loop import check_crash_loop
from hermes.health import HealthServer
from hermes.logging_setup import setup_logging
from hermes.middleware import (
    BodySizeLimitMiddleware,
    LoggingMiddleware,
    McpProtocolVersionMiddleware,
    OAuthBearerAuth,
    RateLimitPostAuth,
    RateLimitPreAuth,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
)
from hermes.network import (
    resolve_hassio_bridge_gateway,
    resolve_supervisor_base_url,
    smoke_check_ha_core_version,
    wait_for_tailscale_if_required,
)
from hermes.ha import HAClient
from hermes.oauth import OAuthServer
from hermes.security import cleanup_expired_confirmations
from mcp.server.transport_security import TransportSecuritySettings

logger = structlog.get_logger(__name__)


async def _boot(config: HermesConfig) -> None:
    """Secuencia de arranque completa — 9 pasos en orden estricto.

    1=config, 2=crash loop, 3=disk, 3.5=health, 4=tailscale,
    5=supervisor, 6=HA version, 7=confirmations, 8=WS a HA, 9=MCP.
    """

    # Instanciar health server (se usa en varios pasos)
    health_server = HealthServer(
        bind_host="172.30.32.1",  # Se sobreescribe en paso 3.5
        bind_port=HEALTH_PORT,
        reconnect_tolerance_seconds=config.health_reconnect_tolerance_seconds,
    )

    # ── Paso 2: Detectar crash loop ───────────────────────────
    # (Paso 1 es cargar config, ya hecho antes de llamar a _boot)
    health_server.set_boot_step(2)
    logger.info("boot_step_2", action="crash_loop_check")
    check_crash_loop()

    # ── Paso 3: Check espacio libre en /data ──────────────────
    health_server.set_boot_step(3)
    logger.info("boot_step_3", action="disk_space_check")
    await _check_disk_space(config)

    # ── Paso 3.5: Health socket temprano ──────────────────────
    # Se levanta ANTES de Tailscale para que el watchdog no reciba
    # ECONNREFUSED durante los pasos largos del boot.
    health_server.set_boot_step(35)
    logger.info("boot_step_3.5", action="start_health_socket_early")

    # Resolver el gateway de hassio para el bind del health
    try:
        hassio_ip = resolve_hassio_bridge_gateway()
        health_server.set_bind_host(hassio_ip)
    except Exception:
        # Si no podemos resolver la bridge, usar fallback
        logger.warning("hassio_bridge_fallback", ip="172.30.32.1")

    await health_server.start()

    # ── Paso 4: Esperar tailscale0 (solo en modo tailscale) ───
    # En modo reverse_proxy el TLS y el hostname público los pone otro
    # componente (Cloudflare Tunnel, Nginx Proxy Manager, Caddy…), así que
    # esperar a una interfaz de Tailscale que no va a existir solo serviría
    # para impedir el arranque. La IP resuelta es informativa: Hermes escucha
    # en `mcp_bind` y no la usa para nada más.
    health_server.set_boot_step(4)
    logger.info("boot_step_4", action="wait_for_tailscale0",
                network_mode=config.network_mode)
    tailscale_ip = await wait_for_tailscale_if_required(
        network_mode=config.network_mode,
        timeout_seconds=config.health_startup_grace_seconds,
        mcp_bind=config.mcp_bind,
    )

    # ── Paso 5: Resolver URL del Supervisor ───────────────────
    health_server.set_boot_step(5)
    logger.info("boot_step_5", action="resolve_supervisor")
    supervisor_url = await resolve_supervisor_base_url(config.supervisor_token)

    # ── Paso 6: Smoke check versión HA ────────────────────────
    health_server.set_boot_step(6)
    logger.info("boot_step_6", action="smoke_check_ha_version")
    try:
        ha_version = await smoke_check_ha_core_version(
            supervisor_base_url=supervisor_url,
            supervisor_token=config.supervisor_token,
            min_supported=HA_CORE_MIN_SUPPORTED,
            last_tested=HA_CORE_LAST_TESTED,
            grace_seconds=config.health_startup_grace_seconds,
        )
    except RuntimeError as exc:
        logger.error("ha_version_check_failed", error=str(exc))
        sys.exit(1)

    # ── Paso 7: Cleanup de confirmaciones expiradas ───────────
    health_server.set_boot_step(7)
    logger.info("boot_step_7", action="cleanup_confirmations")
    cleaned = await cleanup_expired_confirmations()
    if cleaned:
        logger.info("confirmations_cleaned", count=cleaned)

    # ── Paso 8: Conectar WS a HA ──────────────────────────────
    health_server.set_boot_step(8)
    logger.info("boot_step_8", action="ha_ws_connect")

    ha_client = HAClient(
        supervisor_base_url=supervisor_url,
        supervisor_token=config.supervisor_token,
        health_server=health_server,
        ws_max_msg_size=config.ha_ws_max_msg_size_bytes,
    )

    try:
        await ha_client.start(timeout_seconds=config.health_startup_grace_seconds)
    except Exception as exc:
        logger.error("ha_ws_connect_failed", error=str(exc))
        sys.exit(1)

    # ── Paso 9: Arrancar servidor MCP principal ──────────────
    health_server.set_boot_step(9)
    logger.info(
        "boot_step_9",
        action="start_mcp_server",
        host=config.mcp_bind,
        port=MCP_PORT,
        version=__version__,
    )

    # Crear servidor OAuth
    oauth_server = OAuthServer(
        auth_password=config.auth_password,
        public_hostname=config.public_hostname,
    )

    # Crear servidor MCP (MCPServer, antes FastMCP: renombrada en el SDK 2.x).
    # El SDK aplica protección DNS rebinding por defecto para HTTPS locales
    # (Host header 127.0.0.1/localhost). Como Hermes está siempre detrás del
    # componente que termina TLS, las solicitudes entrantes llevan el
    # public_hostname real en el Host header: hay que ampliar allowed_hosts
    # para incluirlo o el SDK las rechazaría todas.
    #
    # En el SDK 2.x `stateless_http` y `transport_security` se pasan al crear
    # la app ASGI (`streamable_http_app`), no al construir el servidor; por eso
    # los ajustes se guardan aquí y se aplican más abajo, al montar la ruta.
    from mcp.server.mcpserver import MCPServer
    from hermes.tools.guide import INSTRUCTIONS

    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            config.public_hostname,
            f"{config.public_hostname}:*",
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
        ],
        allowed_origins=[
            f"https://{config.public_hostname}",
            f"https://{config.public_hostname}:*",
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
        ],
    )

    mcp = MCPServer(
        "hermes",
        instructions=INSTRUCTIONS,
    )

    # Registrar tools
    from hermes.tools import register_all_tools
    register_all_tools(
        mcp,
        ha_client,
        fire_event_allowlist=config.fire_event_allowlist,
        response_max_bytes=config.response_max_bytes,
        safety_backup_enabled=config.safety_backup_enabled,
        safety_backup_window_minutes=config.safety_backup_window_minutes,
        file_backup_max_per_path=config.file_backup_max_per_path,
        file_backup_max_total_mb=config.file_backup_max_total_mb,
        config_write_min_interval_seconds=config.config_write_min_interval_seconds,
        config_write_max_per_minute=config.config_write_max_per_minute,
        call_service_denylist_extra=config.call_service_denylist_extra,
        call_service_restricted_entities=config.call_service_restricted_entities,
        call_service_auto_classify=config.call_service_auto_classify_dangerous,
    )

    # Lifespan: arrancar el StreamableHTTPSessionManager del SDK
    # y la task de limpieza periódica de OAuth (cada hora).
    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        async with mcp.session_manager.run():
            oauth_server.start_periodic_cleanup()
            try:
                yield
            finally:
                oauth_server.stop_periodic_cleanup()
                await ha_client.stop()

    # Stack de middleware Starlette (de fuera a dentro):
    # 1. SecurityHeadersMiddleware — cabeceras de seguridad en TODA respuesta
    # 2. RateLimitPreAuth — techo de requests/min de la superficie pública
    # 3. OAuthBearerAuth — valida el access token (no lee el body)
    # 4. BodySizeLimitMiddleware — 413 por payload excesivo, ya autenticado
    # 5. RateLimitPostAuth — rate limit global post-auth
    # 6. RequestIdMiddleware — UUID4 por request
    # 7. LoggingMiddleware — structlog (con motivo de los 4xx/5xx del MCP)
    # 8. McpProtocolVersionMiddleware — error JSON-RPC legible (y log) ante
    #    versiones de protocolo MCP que el SDK instalado no habla
    middleware_stack = [
        # SecurityHeaders va el PRIMERO para que sus cabeceras lleguen a TODA
        # respuesta, incluidos los rechazos que se generan arriba del stack. Por
        # dentro del limitador de cuerpo, por ejemplo, el 413 saldría sin
        # nosniff, sin CSP y sin X-Frame-Options.
        Middleware(SecurityHeadersMiddleware),
        Middleware(
            RateLimitPreAuth,
            max_per_minute=config.mcp_preauth_max_requests_per_minute_per_ip,
            authenticated_max_per_minute=config.mcp_max_requests_per_minute,
        ),
        Middleware(
            OAuthBearerAuth,
            oauth_validator=oauth_server,
            resource_metadata_url=oauth_server.resource_metadata_url,
            auth_failure_max_per_minute=(
                config.mcp_preauth_max_requests_per_minute_per_ip
            ),
        ),
        # El limitador de cuerpo va DESPUÉS de autenticar. Bufferizar es
        # inevitable para responder un 413 limpio a un body chunked —hay que
        # leer por delante y conservar lo leído para reenviarlo—, pero
        # bufferizar el cuerpo de quien va a recibir un 401 NO lo es: sería
        # regalar `max_request_body_bytes` de memoria del host por conexión a
        # alguien sin credenciales. Ningún middleware anterior consume el body,
        # así que una petición sin token se rechaza sin leer un solo byte.
        Middleware(
            BodySizeLimitMiddleware,
            max_body_bytes=config.max_request_body_bytes,
        ),
        Middleware(
            RateLimitPostAuth,
            max_per_minute=config.mcp_max_requests_per_minute,
        ),
        Middleware(RequestIdMiddleware),
        Middleware(LoggingMiddleware),
        Middleware(McpProtocolVersionMiddleware),
    ]

    # Combinar rutas OAuth + MCP
    routes = oauth_server.get_routes() + [
        Mount(
            "/",
            app=mcp.streamable_http_app(
                stateless_http=True,
                transport_security=transport_security,
            ),
        ),
    ]

    app = Starlette(
        routes=routes,
        middleware=middleware_stack,
        lifespan=lifespan,
    )

    # Configurar uvicorn — HTTP plano, sin TLS
    uvi_config = uvicorn.Config(
        app=app,
        host=config.mcp_bind,
        port=MCP_PORT,
        log_level="error",
        access_log=False,
        log_config=None,
        # Sin tope de concurrencia, cada petición en vuelo puede retener hasta
        # max_request_body_bytes en memoria y nada acota cuántas hay a la vez.
        # El valor por defecto (64) deja holgura de sobra frente al uso real: el
        # cliente MCP lanza ráfagas de una veintena de llamadas y en reposo no
        # mantiene ninguna conexión abierta. Al llenarse, uvicorn responde 503
        # por encima de todo el stack y el servicio se recupera solo en cuanto
        # se liberan plazas.
        #
        # La contrapartida de cualquier tope es que se puede ocupar: bastan
        # tantos sockets como plazas mandando media petición y quedándose ahí
        # (slowloris) para que el resto reciba 503. No es alcanzable desde
        # internet en modo tailscale: tailscaled lee la petición entera antes de
        # abrir nada hacia el backend, así que la absorbe. Solo llega desde el
        # loopback del host, donde quien esté ya puede hacer cosas peores. En
        # `network_mode: reverse_proxy` con `mcp_bind` en la red puente, el
        # alcance es cualquier add-on de esa red.
        limit_concurrency=config.max_concurrent_requests,
        # NOTA: h11_max_incomplete_event_size solo limita el tamaño de headers
        # HTTP incompletos, NO el body. El body se limita vía
        # BodySizeLimitMiddleware en el stack de middleware.
    )

    server = uvicorn.Server(uvi_config)

    # Marcar health como plenamente operacional
    health_server.full_health_ready.set()

    logger.info(
        "hermes_started",
        version=__version__,
        network_mode=config.network_mode,
        mcp_bind=config.mcp_bind,
        mcp_port=MCP_PORT,
        health_port=HEALTH_PORT,
        ha_version=ha_version,
        tailscale_ip=tailscale_ip,
        supervisor_url=supervisor_url,
        public_hostname=config.public_hostname,
    )

    # Handler de graceful shutdown — loop.add_signal_handler es
    # signal-safe en asyncio (Event.set desde signal.signal no lo es).
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    import signal as _signal
    for sig in (_signal.SIGTERM, _signal.SIGINT):
        loop.add_signal_handler(sig, shutdown_event.set)

    # Arrancar el servidor MCP en una task
    server_task = asyncio.create_task(server.serve(), name="mcp_server")

    # Esperar a shutdown
    await shutdown_event.wait()

    logger.info("graceful_shutdown_starting")

    # Parar servidores
    server.should_exit = True
    await health_server.stop()

    # Esperar a que el servidor MCP termine
    try:
        await asyncio.wait_for(server_task, timeout=5.0)
    except asyncio.TimeoutError:
        server_task.cancel()

    # Limpiar ficheros temporales .mcp_tmp
    _cleanup_tmp_files()

    logger.info("hermes_stopped")


async def _check_disk_space(config: HermesConfig) -> None:
    """Check espacio libre en /data."""
    try:
        usage = await asyncio.to_thread(shutil.disk_usage, "/data")
        free_mb = usage.free / (1024 * 1024)
        # Doble headroom sobre el cupo de backups por fichero: x2 por si
        # `safety_backup_enabled` está activo + x2 para copias de trabajo
        # temporales y picos transitorios.
        threshold_mb = config.file_backup_max_total_mb * 2 * 2
        if free_mb < threshold_mb:
            logger.warning(
                "low_disk_space",
                free_mb=round(free_mb, 1),
                threshold_mb=threshold_mb,
                message=(
                    f"Only {free_mb:.0f} MB free in /data "
                    f"(threshold: {threshold_mb} MB). "
                    f"Consider freeing space in /data/backups/."
                ),
            )
        else:
            logger.info("disk_space_ok", free_mb=round(free_mb, 1))
    except OSError as exc:
        logger.warning("disk_space_check_failed", error=str(exc))


# Subdirectorios con ficheros temporales que limpiar al shutdown.
# Limitar a estos en vez de rglob("/data") evita recorrer backups grandes.
_TMP_CLEANUP_DIRS = [
    Path("/data/oauth/codes"),
    Path("/data/oauth/tokens"),
    Path("/data/pending_confirmations"),
]


def _cleanup_tmp_files() -> None:
    """Limpia ficheros temporales .tmp y .mcp_tmp en subdirs conocidos."""
    for subdir in _TMP_CLEANUP_DIRS:
        if not subdir.exists():
            continue
        for tmp_file in subdir.glob("*.tmp"):
            try:
                tmp_file.unlink()
            except OSError:
                pass
        for tmp_file in subdir.glob("*.mcp_tmp"):
            try:
                tmp_file.unlink()
            except OSError:
                pass


def main() -> None:
    """Punto de entrada principal."""
    # ── Paso 1: Cargar configuración ──────────────────────────
    config = load_config()

    # Configurar logging antes de cualquier otra cosa
    setup_logging(config.log_level)

    logger.info(
        "boot_step_1",
        action="config_loaded",
        version=__version__,
        log_level=config.log_level,
        public_hostname=config.public_hostname,
    )

    # Validar configuración obligatoria
    try:
        config.validate()
    except ValueError as exc:
        logger.critical("config_validation_failed", error=str(exc))
        sys.exit(1)

    # Arrancar el event loop
    try:
        asyncio.run(_boot(config))
    except KeyboardInterrupt:
        logger.info("interrupted")
    except SystemExit:
        raise
    except Exception as exc:
        logger.critical("boot_failed", error=str(exc), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
