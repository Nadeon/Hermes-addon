"""Hermes — Resolución de red: tailscale0, bridge hassio, supervisor URL.

Todas las resoluciones se hacen al boot y se cachean para toda la vida
del proceso.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket

import aiohttp
import psutil
import structlog

logger = structlog.get_logger(__name__)

# ── Constantes ────────────────────────────────────────────────
_HASSIO_NETWORK = ipaddress.IPv4Network("172.30.32.0/23")
_HASSIO_GATEWAY = "172.30.32.1"
_SUPERVISOR_FALLBACK_IP = "172.30.32.2"
_TAILSCALE_NETWORK = ipaddress.IPv4Network("100.64.0.0/10")


async def wait_for_tailscale0_ready(
    timeout_seconds: int = 120,
    poll_interval: float = 2.0,
) -> str:
    """Espera a que Tailscale esté listo y tenga una IP 100.x.x.x/10.

    Soporta dos modos:
    1. TUN mode: busca interfaz 'tailscale0' con IP en rango CGNAT.
    2. Userspace mode: no existe tailscale0; busca una IP 100.x.x.x en
       cualquier interfaz (Tailscale userspace proxy la expone así).

    Devuelve la IP resuelta. Sale con error si no se cumple en timeout.
    """
    deadline = asyncio.get_event_loop().time() + timeout_seconds

    while asyncio.get_event_loop().time() < deadline:
        addrs = psutil.net_if_addrs()

        # Intento 1: modo TUN — interfaz tailscale0 con IP CGNAT
        if "tailscale0" in addrs:
            for addr in addrs["tailscale0"]:
                if addr.family != socket.AF_INET:
                    continue
                try:
                    ip = ipaddress.IPv4Address(addr.address)
                    if ip in _TAILSCALE_NETWORK:
                        logger.info(
                            "tailscale_ready",
                            mode="tun",
                            interface="tailscale0",
                            ip=str(ip),
                        )
                        return str(ip)
                except (ValueError, TypeError):
                    continue

        # Intento 2: modo userspace — buscar IP CGNAT en cualquier interfaz
        # (con host_network: true vemos las interfaces del host)
        for iface_name, iface_addrs in addrs.items():
            # Saltar loopback y bridge hassio
            if iface_name in ("lo", "hassio"):
                continue
            for addr in iface_addrs:
                if addr.family != socket.AF_INET:
                    continue
                try:
                    ip = ipaddress.IPv4Address(addr.address)
                    if ip in _TAILSCALE_NETWORK:
                        logger.info(
                            "tailscale_ready",
                            mode="userspace",
                            interface=iface_name,
                            ip=str(ip),
                        )
                        return str(ip)
                except (ValueError, TypeError):
                    continue

        logger.debug(
            "tailscale_not_ready",
            available_ifaces=list(addrs.keys()),
        )
        await asyncio.sleep(poll_interval)

    raise RuntimeError(
        f"No Tailscale CGNAT IP (100.x.x.x) found on any interface "
        f"after {timeout_seconds}s. "
        f"Check that the Tailscale add-on is running and authenticated."
    )


async def wait_for_tailscale_if_required(
    network_mode: str,
    timeout_seconds: int,
    mcp_bind: str = "127.0.0.1",
) -> str | None:
    """Espera a Tailscale solo si la topología lo requiere.

    En `network_mode: tailscale` el add-on de Tailscale publica el Funnel, así
    que tiene sentido no seguir arrancando hasta que la interfaz exista.

    En `reverse_proxy` el TLS y el hostname público los pone otro componente
    (Cloudflare Tunnel, Nginx Proxy Manager, Caddy…) y no va a haber ninguna
    interfaz de Tailscale: esperarla solo serviría para impedir el arranque,
    porque `wait_for_tailscale0_ready` lanza `RuntimeError` al agotar el
    tiempo y eso termina en `sys.exit(1)`.

    Devuelve la IP de Tailscale, o None si no aplica. El valor es informativo:
    Hermes escucha en `mcp_bind` y no lo usa para nada más.
    """
    if network_mode == "tailscale":
        return await wait_for_tailscale0_ready(timeout_seconds=timeout_seconds)

    logger.info(
        "tailscale_wait_skipped",
        network_mode=network_mode,
        bind=mcp_bind,
        message=(
            "El TLS y el hostname público los aporta un proxy inverso externo; "
            "Hermes solo escucha HTTP plano en el bind indicado."
        ),
    )
    return None


def resolve_hassio_bridge_gateway() -> str:
    """Busca la IP del host en la bridge hassio (172.30.32.0/23).

    Devuelve la IP encontrada, o el fallback 172.30.32.1 con un aviso en el log.
    """
    addrs = psutil.net_if_addrs()

    for iface_name, iface_addrs in addrs.items():
        for addr in iface_addrs:
            if addr.family != socket.AF_INET:
                continue
            try:
                ip = ipaddress.IPv4Address(addr.address)
                if ip in _HASSIO_NETWORK:
                    logger.info(
                        "hassio_bridge_found",
                        interface=iface_name,
                        ip=str(ip),
                    )
                    return str(ip)
            except (ValueError, TypeError):
                continue

    # Fallback hardcoded — host_network: true debe exponer la bridge
    logger.warning(
        "hassio_bridge_not_found_using_fallback",
        fallback=_HASSIO_GATEWAY,
        message=(
            "hassio bridge interface not visible via psutil. "
            "Using fallback 172.30.32.1. Is host_network: true set?"
        ),
    )
    return _HASSIO_GATEWAY


async def resolve_supervisor_base_url(supervisor_token: str) -> str:
    """Resuelve la URL base del Supervisor.

    1. Intenta resolución por nombre 'supervisor'.
    2. Si falla, intenta IP fija 172.30.32.2.
    3. Si ambas fallan, aborta.

    Devuelve la URL base sin trailing slash (ej. 'http://supervisor').
    """
    # Intento 1: resolución por nombre
    # socket.getaddrinfo es bloqueante — wrapearlo con asyncio.to_thread
    try:
        await asyncio.to_thread(socket.getaddrinfo, "supervisor", 80)
        base_url = "http://supervisor"
        if await _ping_supervisor(base_url, supervisor_token):
            logger.info("supervisor_resolved", method="hostname", url=base_url)
            return base_url
    except socket.gaierror:
        logger.debug("supervisor_hostname_resolution_failed")

    # Intento 2: IP fija
    base_url = f"http://{_SUPERVISOR_FALLBACK_IP}"
    if await _ping_supervisor(base_url, supervisor_token):
        logger.warning(
            "supervisor_using_fallback_ip",
            url=base_url,
            message="supervisor hostname no resuelve; usando IP fija 172.30.32.2",
        )
        return base_url

    # Ambas fallaron
    raise RuntimeError(
        "Supervisor inalcanzable por nombre ni por IP 172.30.32.2. "
        "Check host_network config and extra_hosts injection."
    )


async def _ping_supervisor(base_url: str, token: str) -> bool:
    """Hace ping al Supervisor. /supervisor/ping no requiere token."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base_url}/supervisor/ping",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return False


async def smoke_check_ha_core_version(
    supervisor_base_url: str,
    supervisor_token: str,
    min_supported: str,
    last_tested: str,
    grace_seconds: int = 120,
) -> str:
    """Verifica la versión del core de HA contra min/max.

    Hace retry con backoff exponencial durante grace_seconds.
    Devuelve la versión encontrada.
    """
    from packaging.version import Version

    headers = {"Authorization": f"Bearer {supervisor_token}"}
    deadline = asyncio.get_event_loop().time() + grace_seconds
    delay = 2.0
    last_error: str = "no response received before deadline"

    while asyncio.get_event_loop().time() < deadline:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{supervisor_base_url}/core/info",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        last_error = f"GET /core/info returned {resp.status}"
                        await asyncio.sleep(delay)
                        delay = min(delay * 1.5, 15.0)
                        continue

                    data = await resp.json()
                    # /core/info devuelve los datos directamente o bajo "data"
                    info = data.get("data", data)
                    version_str = info.get("version", "")

                    if not version_str:
                        last_error = "/core/info response has no 'version' field"
                        await asyncio.sleep(delay)
                        delay = min(delay * 1.5, 15.0)
                        continue

                    installed = Version(version_str)
                    min_ver = Version(min_supported)
                    tested = Version(last_tested)

                    if installed < min_ver:
                        raise RuntimeError(
                            f"HA core {version_str} < minimum supported "
                            f"{min_supported}. Please update."
                        )

                    if installed > tested:
                        logger.warning(
                            "ha_core_version_untested",
                            installed=version_str,
                            last_tested=last_tested,
                            message=(
                                f"HA core {version_str} is newer than "
                                f"last tested {last_tested}. "
                                "Hermes may work but has not been verified. "
                                "Check the add-on changelog for updates."
                            ),
                        )

                    logger.info(
                        "ha_core_version_ok",
                        version=version_str,
                        min_supported=min_supported,
                        last_tested=last_tested,
                    )
                    return version_str

        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            last_error = str(exc)
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 15.0)
            continue

    raise RuntimeError(
        f"HA core did not become reachable within grace period "
        f"({grace_seconds}s). Last error: {last_error}"
    )
