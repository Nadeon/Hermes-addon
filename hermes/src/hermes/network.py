"""Hermes — Resolución de red: tailscale0, bridge hassio, supervisor URL.

Todas las resoluciones se hacen al boot y se cachean para toda la vida
del proceso.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
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
    """Espera a que exista una interfaz de Tailscale con IP CGNAT (100.64/10).

    Solo se miran interfaces cuyo nombre empiece por "tailscale" (la de TUN es
    `tailscale0`; puede haber `tailscale1` si hay varias instancias). El modo
    userspace NO crea ninguna interfaz ni expone la IP CGNAT en el host —de ahí
    que el README exija `userspace_networking: false`—, así que esperar a verla
    en cualquier sitio no tenía sentido.

    Antes se aceptaba una IP CGNAT en CUALQUIER interfaz que no fuera lo ni
    hassio, y 100.64.0.0/10 es el rango CGNAT genérico: un uplink de LTE, de
    satélite o de cualquier operador que haga NAT de nivel de operador reparte
    direcciones de ahí. Con uno de esos, la espera se daba por satisfecha sin
    que Tailscale estuviera levantado, y el arranque seguía hasta fallar más
    tarde y en otro sitio.

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

        # Intento 2: otra interfaz de Tailscale (tailscale1, tailscale2…).
        # El filtro por nombre es lo que impide confundir el CGNAT de un
        # operador con el de Tailscale: ambos viven en 100.64.0.0/10.
        for iface_name, iface_addrs in addrs.items():
            if iface_name == "tailscale0" or not iface_name.startswith("tailscale"):
                continue
            for addr in iface_addrs:
                if addr.family != socket.AF_INET:
                    continue
                try:
                    ip = ipaddress.IPv4Address(addr.address)
                    if ip in _TAILSCALE_NETWORK:
                        logger.info(
                            "tailscale_ready",
                            mode="tun",
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
        f"No Tailscale CGNAT IP (100.x.x.x) found on a tailscale* interface "
        f"after {timeout_seconds}s. "
        f"Check that the Tailscale add-on is running and authenticated, and "
        f"that it runs with userspace_networking: false (userspace mode "
        f"creates no interface at all)."
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


def _version_como_texto(valor: object) -> str:
    """Normaliza el campo `version` de /core/info a texto, o a "" si no sirve.

    `Version()` solo acepta cadenas: con cualquier otra cosa lanza `TypeError`,
    que NO está en el except del bucle de reintentos y por tanto abortaba el
    arranque entero. Y el campo no siempre es una cadena: un YAML o un JSON con
    `version: 2026` lo entrega como entero, y eso es una versión perfectamente
    legible una vez convertida.

    Lo que no sea texto ni número (una lista, un objeto, un `null`, un booleano
    —que en Python es un int y no es una versión—) se trata como "todavía no
    hay versión" y se reintenta, igual que el caso del campo vacío: el core a
    medio arrancar responde cosas raras y dos segundos después ya no.
    """
    if isinstance(valor, str):
        return valor.strip()
    if isinstance(valor, bool):
        return ""
    if isinstance(valor, (int, float)):
        return str(valor)
    return ""


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

    Todo lo que sea "el core todavía no está en condiciones de contestar" se
    reintenta, no solo los errores de transporte: mientras el core arranca,
    /core/info responde 200 con `version: "landingpage"` (que
    `packaging.version` rechaza con InvalidVersion), o con un cuerpo que no es
    JSON, o con algo que no es un objeto. Cualquiera de esos casos abortaba el
    boot entero en el primer intento aunque el core hubiera terminado de
    arrancar dos segundos después. Lo único que sigue siendo fatal e inmediato
    es una versión legible POR DEBAJO del mínimo soportado: esa no mejora
    esperando.
    """
    from packaging.version import InvalidVersion, Version

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
                    if not isinstance(data, dict):
                        last_error = (
                            f"/core/info response is not a JSON object "
                            f"({type(data).__name__})"
                        )
                        await asyncio.sleep(delay)
                        delay = min(delay * 1.5, 15.0)
                        continue

                    info = data.get("data", data)
                    if not isinstance(info, dict):
                        last_error = "/core/info 'data' field is not an object"
                        await asyncio.sleep(delay)
                        delay = min(delay * 1.5, 15.0)
                        continue

                    version_raw = info.get("version", "")
                    version_str = _version_como_texto(version_raw)

                    if not version_str:
                        last_error = (
                            f"/core/info response has no usable 'version' "
                            f"field (got {type(version_raw).__name__})"
                        )
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

        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            json.JSONDecodeError,
            InvalidVersion,
        ) as exc:
            # InvalidVersion incluye el "landingpage" que sirve el core
            # mientras arranca; JSONDecodeError, un cuerpo a medio escribir.
            # Los dos son transitorios: reintentar con el mismo backoff.
            last_error = f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 15.0)
            continue

    raise RuntimeError(
        f"HA core did not become reachable within grace period "
        f"({grace_seconds}s). Last error: {last_error}"
    )
