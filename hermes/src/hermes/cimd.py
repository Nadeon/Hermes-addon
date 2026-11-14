"""Hermes — Client ID Metadata Documents (CIMD) para el servidor OAuth.

Con CIMD el `client_id` de un cliente OAuth es una URL `https://…` donde el
propio cliente publica un documento JSON con su nombre y sus `redirect_uris`.
Claude Code lo usa: así no necesita registrarse por DCR en cada servidor.

Para el servidor de autorización eso significa algo delicado: descargar una
URL que elige quien llama a un endpoint PÚBLICO (`/oauth/authorize`). Sin
defensas, Hermes se convierte en un proxy hacia la red del dueño (SSRF): un
`client_id` como `https://192.168.1.1/admin` o un dominio que resuelve a la
tailnet bastaría para que Hermes hablara con el router o con el propio Home
Assistant. Por eso este módulo vive aparte de `oauth.py` y se prueba aislado.

Defensas (borrador CIMD §6, RFC 6890, RFC 8252):
  * Forma de la URL estricta antes de descargar nada (`parse_client_id_url`).
  * Resolución DNS propia: se rechaza la petición entera si ALGUNA dirección
    es de uso especial, y aiohttp conecta a las direcciones ya validadas sin
    volver a resolver (contra el DNS rebinding). Las IP literales, que aiohttp
    no pasa por el resolvedor, se comprueban antes de pedir nada.
  * Sin redirecciones, sin proxies del entorno, 5 s en total y 5 120 bytes.
  * JSON estricto y validación de cada campo; `client_id` igual carácter a
    carácter a la URL descargada.
  * Cupo de descargas (4 simultáneas, 30 por minuto en total y 10 por IP de
    origen) para no servir de amplificador a quien rota IPs. Los clientes ya
    conocidos (refresh con un token válido, o un cliente con el que el dueño
    ya inició sesión) no gastan cupo: un anónimo no puede dejarlos fuera.
  * Caché en memoria acotada; los errores nunca se cachean y las entradas de
    los clientes conocidos no las expulsan las de los anónimos.

Todo es fail-closed: cualquier caso no previsto acaba en error, nunca en un
documento aceptado.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import ipaddress
import json
import re
import socket
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable
from urllib.parse import urlsplit

import aiohttp
import structlog
from aiohttp.abc import AbstractResolver, ResolveResult

logger = structlog.get_logger(__name__)

# ── Límites ───────────────────────────────────────────────────
MAX_URL_LEN = 2048
MAX_DOCUMENT_BYTES = 5120          # borrador CIMD: documentos pequeños
FETCH_TIMEOUT_SECONDS = 5.0        # tiempo total de la descarga
MAX_CONCURRENT_FETCHES = 4
MAX_FETCHES_PER_WINDOW = 30
FETCH_WINDOW_SECONDS = 60.0
# Cupo por IP de origen dentro del global: con solo el global, dos IPs (el
# freno pre-auth deja 20 peticiones por minuto a cada una) bastaban para
# agotarlo y dejar al dueño sin poder iniciar sesión (revisión 1.1.0, MEDIO-2).
MAX_FETCHES_PER_SOURCE_PER_WINDOW = 10
# Clientes «conocidos» (ver `CimdResolver.pin`): con los que el dueño ya
# inició sesión o renovó tokens. Pocos: son los dispositivos del dueño.
MAX_PINNED = 16

# Caché (FR-016, FR-017). Las cifras son supuestos de la spec (S-09).
CACHE_MAX_ENTRIES = 64
CACHE_MIN_TTL = 300
CACHE_MAX_TTL = 86_400
CACHE_DEFAULT_TTL = 3_600
STALE_MAX_AGE = 86_400             # copia caducada usable ante fallos temporales

MAX_CLIENT_NAME_LEN = 200
MAX_REDIRECT_URIS = 10
MAX_REDIRECT_URI_LEN = 2048
_DANGEROUS_SCHEMES = frozenset({"javascript", "data", "vbscript", "file"})

# Hosts loopback para los que el puerto del redirect_uri se ignora (RFC 8252
# §7.3). Se comparan tal cual aparecen en la URL: `LOCALHOST` o `127.1` no
# cuentan, igual que no cuenta `localhost.evil.example`.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})

# RFC 3986 §3.1.
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*$")

# Prefijo NAT64 bien conocido (RFC 6052). `ipaddress` lo da por global, pero
# detrás de un traductor NAT64 `64:ff9b::a00:5` llega a 10.0.0.5.
_NAT64_WKP = ipaddress.ip_network("64:ff9b::/96")
# IPv4-compatibles (obsoletas, RFC 4291 §2.5.5.1): `::a00:5` es "global" para
# `ipaddress` y embebe 10.0.0.5. Ningún servidor público legítimo las usa.
_IPV4_COMPAT = ipaddress.ip_network("::/96")
# IPv4 traducida (SIIT, RFC 6145/7915): `::ffff:0:a00:5` es 10.0.0.5 detrás
# de un traductor, e `ipaddress` la da por global (revisión 1.1.0, BAJO-7).
_IPV4_TRANSLATED = ipaddress.ip_network("::ffff:0:0:0/96")
# Rangos que `ipaddress` da por globales pero que no son destinos públicos:
# site-local obsoleto (aún enrutado en alguna LAN) y SRv6 (RFC 9602).
_IPV6_EXTRA_FORBIDDEN = (
    ipaddress.ip_network("fec0::/10"),
    ipaddress.ip_network("5f00::/16"),
)

# Nombre DNS en minúsculas, sin punto final, con al menos dos etiquetas y un
# TLD que empieza por letra. Que el TLD no pueda empezar por un dígito es lo
# que deja fuera todas las formas de IPv4 que acepta `inet_aton` (`127.1`,
# `2130706433`, `0177.0.0.1`, `0x7f.1`): aiohttp las da por IP, no las pasa
# por el resolvedor seguro y conecta a ellas directamente (revisión 1.1.0,
# ALTO-1).
_DNS_HOST_RE = re.compile(
    r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?"
)

# Resolución DNS en un pool propio y pequeño: `loop.getaddrinfo` usa el
# executor por defecto, el mismo que `validate_token` usa en CADA petición
# MCP. Un DNS autoritativo que no responde nunca (lo controla quien elige el
# `client_id`) dejaría hilos colgados que `asyncio.timeout` no mata, y con
# unos pocos el MCP del dueño se pararía (revisión 1.1.0, BAJO-5).
_DNS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="hermes-cimd-dns"
)


async def _pooled_getaddrinfo(host: str, port: int, *, type: int = 0,
                              family: int = 0) -> list[tuple[Any, ...]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _DNS_EXECUTOR,
        functools.partial(socket.getaddrinfo, host, port, family, type),
    )


# ── Errores y resultado ───────────────────────────────────────


class CimdError(Exception):
    """Error al obtener o validar un documento CIMD. `reason` es un código corto."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class CimdInvalidError(CimdError):
    """Fallo: URL, dirección, respuesta o documento inaceptables.

    Si es `definitive` borra la copia de la caché y, en el token endpoint,
    revoca los refresh tokens del cliente (FR-018). Si no lo es, se rechaza
    igual pero sin borrar nada: ver `definitive`.
    """

    @property
    def definitive(self) -> bool:
        """True si el fallo prueba que el CLIENTE ya no es válido.

        Solo lo prueban un documento inválido o un 404/410. Un 401/403 (la
        gestión de bots de un CDN), un 3xx (el documento se ha movido), una
        dirección prohibida (DNS64 local, un filtro DNS que responde 0.0.0.0)
        o una codificación no pedida pueden ser cosa de la red o del
        servidor, y revocar por ellos echaba de golpe todas las sesiones del
        dueño (revisión 1.1.0, BAJO-6).
        """
        if self.reason in ("http_404", "http_410"):
            return True
        if self.reason.startswith("http_") or self.reason in _SOFT_INVALID_REASONS:
            return False
        return True


_SOFT_INVALID_REASONS = frozenset({"redirect", "forbidden_address", "content_encoding"})


class CimdTemporaryError(CimdError):
    """Fallo temporal: red, DNS, timeout, 5xx, 429 o cupo agotado.

    No borra la copia de la caché: un claude.ai caído un rato no debe echar al
    dueño de Hermes (FR-017).
    """


@dataclass(frozen=True)
class CimdClient:
    """Lo único que Hermes usa de un documento válido."""

    client_id: str
    client_name: str
    redirect_uris: tuple[str, ...]
    allow_refresh: bool


# ── Forma de la URL (FR-002) ──────────────────────────────────


def parse_client_id_url(url: str) -> str | None:
    """Motivo por el que `url` no es un `client_id` CIMD aceptable, o None.

    Se comprueba ANTES de descargar nada. Las reglas son las del borrador
    CIMD: https con host, sin userinfo, sin query ni fragmento, con path y sin
    segmentos `.`/`..` (que harían que dos URLs distintas nombraran el mismo
    documento), sin más puerto que el 443.
    """
    if not isinstance(url, str) or not url:
        return "empty"
    if len(url) > MAX_URL_LEN:
        return "too_long"
    # Solo ASCII imprimible y sin barra invertida: los navegadores y las
    # librerías no se ponen de acuerdo en cómo tratar espacios, controles o
    # `\`, y cualquier desacuerdo entre quien valida y quien descarga es una
    # puerta abierta. Un client_id legítimo no los necesita.
    if any(not (0x21 <= ord(ch) <= 0x7E) or ch == "\\" for ch in url):
        return "bad_characters"
    if not url.startswith("https://"):
        return "not_https"
    if "#" in url:
        return "fragment"
    if "?" in url:
        return "query"
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "bad_port"
    netloc = parts.netloc
    if not netloc or not parts.hostname:
        return "no_host"
    if "@" in netloc:
        return "userinfo"
    if netloc.endswith(":"):
        return "bad_port"
    if port is not None and port != 443:
        return "bad_port"
    host_reason = dns_host_problem(parts.hostname)
    if host_reason:
        return host_reason
    if not parts.path or parts.path == "/":
        return "no_path"
    for segment in parts.path.split("/"):
        # `%2e` es un punto codificado: `/%2e%2e/` normaliza a `/../`.
        decoded = segment.lower().replace("%2e", ".")
        if decoded in (".", ".."):
            return "dot_segment"
    return None


def dns_host_problem(host: str | None) -> str | None:
    """Motivo por el que `host` no es un nombre DNS aceptable, o None.

    Un `client_id` CIMD legítimo nunca es una IP. Rechazar aquí cualquier
    forma numérica o con `:` evita depender de cómo decide aiohttp qué es una
    IP (una heurística que ha cambiado entre versiones): ningún literal llega
    a la descarga. El punto final también se rechaza (`127.0.0.1.`, o
    `claude.ai.` como alias de `claude.ai`).
    """
    host = (host or "").lower()
    if not host:
        return "no_host"
    last_label = host.rstrip(".").rsplit(".", 1)[-1]
    if ":" in host or host.replace(".", "").isdigit() or last_label[:1].isdigit():
        return "ip_host"
    if not _DNS_HOST_RE.fullmatch(host):
        return "bad_host"
    return None


def normalize_host(host: str) -> str:
    """Host en minúsculas y sin punto final, para comparar con la lista."""
    return (host or "").strip().lower().rstrip(".")


def normalize_allowed_hosts(hosts: Iterable[str]) -> frozenset[str]:
    """Normaliza `oauth_cimd_allowed_hosts`; ValueError si alguno no es DNS.

    Una entrada mal escrita no se ignora: si se descartara y la lista quedara
    vacía, «vacía» significa «cualquier host» y el error abriría en vez de
    cerrar.
    """
    out: set[str] = set()
    for raw in hosts:
        host = normalize_host(str(raw))
        if dns_host_problem(host):
            raise ValueError(f"oauth_cimd_allowed_hosts: host no válido: {raw!r}")
        out.add(host)
    return frozenset(out)


def host_allowed(url: str, allowed: frozenset[str]) -> bool:
    """True si el host del `client_id` está permitido (lista vacía = todos)."""
    if not allowed:
        return True
    return normalize_host(client_id_host(url)) in allowed


def client_id_host(url: str) -> str:
    """Host de un `client_id` para el log y la pantalla de consentimiento."""
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


# ── Clasificación de direcciones (FR-006) ─────────────────────


def is_forbidden_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True si `ip` es de uso especial (RFC 6890) y Hermes no debe conectar a ella.

    Se usa `is_global` como base porque cubre loopback, privadas, link-local,
    CGNAT 100.64.0.0/10 (la tailnet), ULA, documentación, reservadas y no
    especificadas. Lo que `ipaddress` da por global pero no lo es para un
    servidor (multicast, IPv6 que embebe una IPv4 interna) se añade aparte.
    """
    if ip.is_multicast or not ip.is_global:
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        if ip in _IPV4_COMPAT:
            return True
        if any(ip in net for net in _IPV6_EXTRA_FORBIDDEN):
            return True
        embedded: list[ipaddress.IPv4Address] = []
        if ip.ipv4_mapped is not None:
            embedded.append(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            embedded.append(ip.sixtofour)
        if ip.teredo is not None:
            embedded.extend(ip.teredo)
        if ip in _NAT64_WKP or ip in _IPV4_TRANSLATED:
            embedded.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        if any(is_forbidden_address(v4) for v4 in embedded):
            return True
    return False


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


GetAddrInfo = Callable[..., Awaitable[list[tuple[Any, ...]]]]


class _SafeResolver(AbstractResolver):
    """Resolvedor de aiohttp que solo devuelve direcciones globales.

    aiohttp conecta a lo que devuelve este método y usa `hostname` para SNI y
    para verificar el certificado, sin volver a resolver: así la dirección que
    se valida es exactamente la dirección a la que se conecta, y un DNS que
    cambie de respuesta entre una consulta y otra (rebinding) no tiene una
    segunda consulta que aprovechar.

    Basta UNA dirección especial para rechazarlo todo: quedarse con las buenas
    dejaría al atacante elegir, con el orden de las respuestas, a cuál se
    conecta cuando la buena falla.
    """

    def __init__(self, getaddrinfo: GetAddrInfo | None = None) -> None:
        self._getaddrinfo = getaddrinfo

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_UNSPEC
    ) -> list[ResolveResult]:
        literal = _literal_ip(host)
        if literal is not None:
            # aiohttp no llama al resolvedor con IP literales (ver
            # `CimdResolver._fetch`), pero si algún día lo hace la regla es la
            # misma y sin consultar el DNS.
            if is_forbidden_address(literal):
                raise CimdInvalidError("forbidden_address")
            fam = socket.AF_INET6 if literal.version == 6 else socket.AF_INET
            return [ResolveResult(hostname=host, host=str(literal), port=port,
                                  family=fam, proto=0, flags=socket.AI_NUMERICHOST)]

        getaddrinfo = self._getaddrinfo or _pooled_getaddrinfo
        try:
            infos = await getaddrinfo(host, port, type=socket.SOCK_STREAM, family=family)
        except (OSError, UnicodeError) as exc:
            raise CimdTemporaryError("dns") from exc
        if not infos:
            raise CimdTemporaryError("dns")

        results: list[ResolveResult] = []
        for fam, _type, proto, _canon, sockaddr in infos:
            ip = _literal_ip(str(sockaddr[0]).split("%", 1)[0])
            if ip is None or is_forbidden_address(ip):
                # Una sola dirección especial invalida toda la respuesta.
                raise CimdInvalidError("forbidden_address")
            results.append(ResolveResult(
                hostname=host, host=str(ip), port=port,
                family=fam, proto=proto, flags=socket.AI_NUMERICHOST,
            ))
        return results

    async def close(self) -> None:
        return None


# ── Validación del documento (FR-008…FR-010) ──────────────────


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            # Con claves duplicadas cada parser se queda con una distinta: lo
            # que Hermes valida podría no ser lo que otro lee.
            raise ValueError("duplicate key")
        out[key] = value
    return out


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-standard JSON constant {name}")


def _valid_redirect_uri(uri: Any) -> bool:
    if not isinstance(uri, str) or not uri or len(uri) > MAX_REDIRECT_URI_LEN:
        return False
    if "#" in uri or any(ord(ch) <= 0x20 or ord(ch) == 0x7F for ch in uri):
        return False
    try:
        parts = urlsplit(uri)
    except ValueError:
        return False
    if not parts.scheme or not _SCHEME_RE.match(parts.scheme):
        return False  # relativa
    if parts.scheme.lower() in _DANGEROUS_SCHEMES:
        return False
    return bool(parts.netloc or parts.path)


def validate_document(url: str, raw: bytes) -> CimdClient:
    """Valida el cuerpo descargado de `url` y devuelve lo que Hermes usa de él.

    Lanza `CimdInvalidError` con un motivo corto en cualquier desviación.
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        raise CimdInvalidError("bom")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CimdInvalidError("not_utf8") from exc
    try:
        doc = json.loads(
            text,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except (ValueError, RecursionError) as exc:
        raise CimdInvalidError("bad_json") from exc
    if not isinstance(doc, dict):
        raise CimdInvalidError("not_object")

    # Comparación exacta, carácter a carácter: ni mayúsculas, ni barra final,
    # ni normalización. Es lo que ata el documento a la URL que lo sirve.
    if doc.get("client_id") != url:
        raise CimdInvalidError("client_id_mismatch")

    name = doc.get("client_name")
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_CLIENT_NAME_LEN:
        raise CimdInvalidError("bad_client_name")

    uris = doc.get("redirect_uris")
    if (not isinstance(uris, list) or not 1 <= len(uris) <= MAX_REDIRECT_URIS
            or not all(_valid_redirect_uri(u) for u in uris)):
        raise CimdInvalidError("bad_redirect_uris")

    # Hermes solo atiende clientes públicos: un documento con secreto es o un
    # error o un intento de publicar un secreto, y en los dos casos no vale.
    if "client_secret" in doc or "client_secret_expires_at" in doc:
        raise CimdInvalidError("client_secret_present")
    if doc.get("token_endpoint_auth_method", "none") != "none":
        raise CimdInvalidError("bad_auth_method")

    grants = doc.get("grant_types", ["authorization_code"])
    if (not isinstance(grants, list) or not all(isinstance(g, str) for g in grants)
            or "authorization_code" not in grants):
        raise CimdInvalidError("bad_grant_types")
    responses = doc.get("response_types", ["code"])
    if (not isinstance(responses, list) or not all(isinstance(r, str) for r in responses)
            or "code" not in responses):
        raise CimdInvalidError("bad_response_types")

    return CimdClient(
        client_id=url,
        client_name=name,
        redirect_uris=tuple(uris),
        allow_refresh="refresh_token" in grants,
    )


# ── redirect_uri (FR-011, FR-012) ─────────────────────────────


def _split_loopback(uri: str) -> tuple[str, str, str] | None:
    """(host, path, query) si `uri` es `http://<loopback>[:puerto]/…`, o None."""
    try:
        parts = urlsplit(uri)
    except ValueError:
        return None
    if parts.scheme != "http" or parts.fragment or "#" in uri:
        return None
    netloc = parts.netloc
    if "@" in netloc:
        return None
    if netloc.startswith("["):
        end = netloc.find("]")
        if end < 0:
            return None
        host, rest = netloc[: end + 1], netloc[end + 1:]
    else:
        host, sep, port = netloc.partition(":")
        rest = sep + port
    if rest:
        if not rest.startswith(":") or not rest[1:].isdigit() or not rest[1:].isascii():
            return None
        if not 0 < int(rest[1:]) < 65536:
            return None
    if host not in _LOOPBACK_HOSTS:
        return None
    return host, parts.path, parts.query


def redirect_uri_matches(registered: str, requested: str) -> bool:
    """True si `requested` vale para el `registered` del documento.

    Igualdad exacta, salvo en loopback (RFC 8252 §7.3): una app nativa abre un
    puerto libre cualquiera en el momento, así que no lo puede declarar de
    antemano. Ahí se ignora SOLO el puerto; esquema `http`, host (el mismo
    literal en los dos), path y query siguen comparándose exactamente.
    """
    # `urlsplit` quita `\t\r\n` en silencio: `http://local\nhost:1/cb`
    # casaría con `http://localhost/cb` y la redirección real (con `%0A`) no
    # sería la que se validó ni la que ve el dueño (revisión 1.1.0, BAJO-8).
    if any(ord(ch) <= 0x20 or ord(ch) == 0x7F for ch in requested):
        return False
    if registered == requested:
        return True
    reg = _split_loopback(registered)
    req = _split_loopback(requested)
    if reg is None or req is None:
        return False
    return reg == req


def is_loopback_redirect(uri: str) -> bool:
    """True si `uri` va a una app del mismo dispositivo (`http://localhost…`)."""
    return _split_loopback(uri) is not None


# ── Resolvedor con caché y cupo ───────────────────────────────


def _cache_lifetime(cache_control: str | None) -> int:
    """Vida de una entrada según `Cache-Control`, acotada (FR-016)."""
    if not cache_control:
        return CACHE_DEFAULT_TTL
    max_age: int | None = None
    for directive in cache_control.lower().split(","):
        name, _, value = directive.strip().partition("=")
        name = name.strip()
        if name in ("no-store", "no-cache"):
            # El documento pide no guardarse, pero sin caché alguna cada
            # petición iría a la red: se guarda lo mínimo.
            return CACHE_MIN_TTL
        if name == "max-age":
            value = value.strip().strip('"')
            if value.isdigit():
                max_age = int(value)
    if max_age is None:
        return CACHE_DEFAULT_TTL
    return max(CACHE_MIN_TTL, min(CACHE_MAX_TTL, max_age))


@dataclass
class _CacheEntry:
    client: CimdClient
    fetched_at: float
    expires_at: float


class CimdResolver:
    """Obtiene documentos CIMD de forma segura, con caché y cupo de descargas."""

    def __init__(
        self,
        *,
        getaddrinfo: GetAddrInfo | None = None,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._getaddrinfo = getaddrinfo
        self._clock = clock
        self._monotonic = monotonic
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
        self._fetch_times: deque[float] = deque()
        self._source_times: dict[str, deque[float]] = {}
        self._pinned: OrderedDict[str, None] = OrderedDict()

    def forget(self, url: str) -> None:
        """Borra la copia de `url` de la caché."""
        self._cache.pop(url, None)
        self._pinned.pop(url, None)

    def pin(self, url: str) -> None:
        """Marca `url` como cliente conocido del dueño.

        Se llama cuando el dueño ya ha demostrado quién es con ese cliente
        (contraseña correcta o refresh token válido). Un cliente conocido no
        gasta cupo al recargar su documento y su entrada no la expulsan las de
        clientes anónimos: así nadie sin contraseña puede dejar a Claude Code
        sin login ni sin refresh (revisión 1.1.0, MEDIO-2).
        """
        self._pinned[url] = None
        self._pinned.move_to_end(url)
        while len(self._pinned) > MAX_PINNED:
            self._pinned.popitem(last=False)

    async def resolve(self, url: str, *, source: str | None = None,
                      trusted: bool = False) -> CimdClient:
        """Documento válido de `url`, de la caché o descargado.

        `source` es la IP de origen de una petición anónima (cupo por IP).
        `trusted` indica que quien llama ya está autenticado (refresh token
        válido): no gasta cupo y el cliente pasa a ser conocido.

        `CimdInvalidError`: fallo (borra la copia solo si es definitivo).
        `CimdTemporaryError`: fallo temporal sin copia usable.
        """
        reason = parse_client_id_url(url)
        if reason:
            raise CimdInvalidError(reason)

        entry = self._cache.get(url)
        now = self._clock()
        if entry is not None and now < entry.expires_at:
            self._cache.move_to_end(url)
            return entry.client

        try:
            client, lifetime = await self._fetch(
                url, source=source, charge_quota=not (trusted or url in self._pinned)
            )
        except CimdTemporaryError as exc:
            if entry is not None and now - entry.fetched_at < STALE_MAX_AGE:
                self._cache.move_to_end(url)
                logger.info("oauth_cimd_stale_copy_used",
                            host=client_id_host(url), reason=exc.reason)
                return entry.client
            self._cache.pop(url, None)
            raise
        except CimdInvalidError as exc:
            # Los errores no se cachean, y una copia vieja de un documento que
            # ahora es inválido tampoco puede seguir valiendo. Un fallo que no
            # es definitivo (ver `definitive`) no prueba nada contra el
            # documento: la copia se conserva para cuando el problema pase.
            if exc.definitive:
                self.forget(url)
            raise

        fetched_at = self._clock()
        self._cache[url] = _CacheEntry(client, fetched_at, fetched_at + lifetime)
        self._cache.move_to_end(url)
        if trusted:
            self.pin(url)
        self._evict()
        return client

    def _evict(self) -> None:
        """Deja la caché en su tamaño expulsando primero a los no conocidos.

        Con un LRU puro, 64 documentos válidos publicados por cualquiera
        echaban de la caché el de Claude Code y, con él, la copia de reserva
        que el refresh usa si claude.ai falla un rato (revisión 1.1.0, MEDIO-2).
        """
        while len(self._cache) > CACHE_MAX_ENTRIES:
            victim = next((u for u in self._cache if u not in self._pinned), None)
            if victim is None:
                self._cache.popitem(last=False)
            else:
                del self._cache[victim]

    def _take_rate_slot(self, source: str | None = None) -> None:
        """Reserva una descarga en la ventana de un minuto, o fallo temporal.

        Se comprueban los dos cupos (global y de la IP de origen) antes de
        anotar en ninguno: un rechazo no gasta cupo.
        """
        now = self._monotonic()

        def _purge(times: deque[float]) -> None:
            while times and now - times[0] >= FETCH_WINDOW_SECONDS:
                times.popleft()

        _purge(self._fetch_times)
        for key in list(self._source_times):
            _purge(self._source_times[key])
            if not self._source_times[key]:
                del self._source_times[key]
        if len(self._fetch_times) >= MAX_FETCHES_PER_WINDOW:
            raise CimdTemporaryError("rate_limited")
        if source is not None:
            per_source = self._source_times.get(source)
            if per_source is not None and len(per_source) >= MAX_FETCHES_PER_SOURCE_PER_WINDOW:
                raise CimdTemporaryError("rate_limited")
            # Solo se crean entradas para descargas que admite el cupo
            # global, así que el diccionario nunca pasa de 30 IPs.
            self._source_times.setdefault(source, deque()).append(now)
        self._fetch_times.append(now)

    def _new_session(self) -> aiohttp.ClientSession:
        connector = aiohttp.TCPConnector(
            resolver=_SafeResolver(self._getaddrinfo),
            use_dns_cache=False,   # cada conexión pasa por el resolvedor seguro
            force_close=True,
            limit=MAX_CONCURRENT_FETCHES,
        )
        return aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT_SECONDS),
            # Sin HTTP(S)_PROXY del entorno: con un proxy la conexión iría al
            # proxy y el filtro de direcciones no vería el destino real.
            trust_env=False,
            # Sin descompresión: el límite de 5 120 bytes debe medir lo que
            # llega por la red, no lo que sale de un gzip. En aiohttp < 3.13.3
            # un chunk comprimido pequeño se inflaba entero en memoria
            # (CVE-2025-69223; revisión 1.1.0, BAJO-4).
            auto_decompress=False,
            # Sin versión: quien publica un `client_id` ve esta cabecera, y la
            # versión exacta solo le sirve a un atacante (revisión 1.1.0,
            # MEDIO-1).
            headers={"User-Agent": "Hermes-CIMD"},
        )

    async def _fetch(self, url: str, *, source: str | None = None,
                     charge_quota: bool = True) -> tuple[CimdClient, int]:
        """Descarga y valida `url`. Devuelve el cliente y la vida en caché."""
        # Defensa en profundidad de `parse_client_id_url`: aiohttp no pasa
        # por el resolvedor nada que ÉL considere una IP, y su criterio
        # (`127.1`, `0177.0.0.1`…) no es el de `ipaddress`. Solo un nombre DNS
        # llega a la conexión.
        host_reason = dns_host_problem(urlsplit(url).hostname)
        if host_reason:
            raise CimdInvalidError(host_reason)

        if charge_quota:
            self._take_rate_slot(source)
        async with self._semaphore:
            try:
                async with asyncio.timeout(FETCH_TIMEOUT_SECONDS):
                    return await self._download(url)
            except CimdError:
                raise
            except TimeoutError as exc:
                raise CimdTemporaryError("timeout") from exc
            except (aiohttp.ClientError, OSError) as exc:
                raise CimdTemporaryError("network") from exc

    async def _download(self, url: str) -> tuple[CimdClient, int]:
        async with self._new_session() as session:
            async with session.get(
                url,
                headers={"Accept": "application/json", "Accept-Encoding": "identity"},
                # Una redirección llevaría a una URL que nadie ha validado
                # (y que puede ser interna): cualquier 3xx es un error.
                allow_redirects=False,
            ) as resp:
                status = resp.status
                if 300 <= status < 400:
                    raise CimdInvalidError("redirect")
                if status == 429 or status >= 500:
                    raise CimdTemporaryError(f"http_{status}")
                if status != 200:
                    raise CimdInvalidError(f"http_{status}")
                encoding = resp.headers.get("Content-Encoding", "").strip().lower()
                if encoding not in ("", "identity"):
                    # Se pidió `identity`; un cuerpo comprimido ni se
                    # descomprime (ver `_new_session`) ni se interpreta.
                    raise CimdInvalidError("content_encoding")
                if resp.content_length is not None and resp.content_length > MAX_DOCUMENT_BYTES:
                    raise CimdInvalidError("too_large")
                # Se lee como mucho un byte más del límite: llegar a él es
                # error, sin intentar interpretar el prefijo.
                body = bytearray()
                while len(body) <= MAX_DOCUMENT_BYTES:
                    chunk = await resp.content.read(MAX_DOCUMENT_BYTES + 1 - len(body))
                    if not chunk:
                        break
                    body += chunk
                if len(body) > MAX_DOCUMENT_BYTES:
                    raise CimdInvalidError("too_large")
                cache_control = resp.headers.get("Cache-Control")
        client = validate_document(url, bytes(body))
        return client, _cache_lifetime(cache_control)
