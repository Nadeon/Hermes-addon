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
  * Cupo de descargas (4 simultáneas, 30 por minuto) para no servir de
    amplificador a quien rota IPs.
  * Caché en memoria acotada; los errores nunca se cachean.

Todo es fail-closed: cualquier caso no previsto acaba en error, nunca en un
documento aceptado.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

import aiohttp
import structlog
from aiohttp.abc import AbstractResolver, ResolveResult

from hermes import __version__

logger = structlog.get_logger(__name__)

# ── Límites ───────────────────────────────────────────────────
MAX_URL_LEN = 2048
MAX_DOCUMENT_BYTES = 5120          # borrador CIMD: documentos pequeños
FETCH_TIMEOUT_SECONDS = 5.0        # tiempo total de la descarga
MAX_CONCURRENT_FETCHES = 4
MAX_FETCHES_PER_WINDOW = 30
FETCH_WINDOW_SECONDS = 60.0

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


# ── Errores y resultado ───────────────────────────────────────


class CimdError(Exception):
    """Error al obtener o validar un documento CIMD. `reason` es un código corto."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class CimdInvalidError(CimdError):
    """Fallo definitivo: URL, dirección, respuesta o documento inaceptables.

    Borra la copia de la caché; en el token endpoint revoca los refresh tokens
    del cliente (FR-018).
    """


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
    if not parts.path or parts.path == "/":
        return "no_path"
    for segment in parts.path.split("/"):
        # `%2e` es un punto codificado: `/%2e%2e/` normaliza a `/../`.
        decoded = segment.lower().replace("%2e", ".")
        if decoded in (".", ".."):
            return "dot_segment"
    return None


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
        embedded: list[ipaddress.IPv4Address] = []
        if ip.ipv4_mapped is not None:
            embedded.append(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            embedded.append(ip.sixtofour)
        if ip.teredo is not None:
            embedded.extend(ip.teredo)
        if ip in _NAT64_WKP:
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

        getaddrinfo = self._getaddrinfo or asyncio.get_running_loop().getaddrinfo
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

    def forget(self, url: str) -> None:
        """Borra la copia de `url` de la caché."""
        self._cache.pop(url, None)

    async def resolve(self, url: str) -> CimdClient:
        """Documento válido de `url`, de la caché o descargado.

        `CimdInvalidError`: fallo definitivo (borra la copia).
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
            client, lifetime = await self._fetch(url)
        except CimdTemporaryError as exc:
            if entry is not None and now - entry.fetched_at < STALE_MAX_AGE:
                self._cache.move_to_end(url)
                logger.info("oauth_cimd_stale_copy_used",
                            host=client_id_host(url), reason=exc.reason)
                return entry.client
            self._cache.pop(url, None)
            raise
        except CimdInvalidError:
            # Los errores no se cachean, y una copia vieja de un documento que
            # ahora es inválido tampoco puede seguir valiendo.
            self._cache.pop(url, None)
            raise

        fetched_at = self._clock()
        self._cache[url] = _CacheEntry(client, fetched_at, fetched_at + lifetime)
        self._cache.move_to_end(url)
        while len(self._cache) > CACHE_MAX_ENTRIES:
            self._cache.popitem(last=False)
        return client

    def _take_rate_slot(self) -> None:
        """Reserva una descarga en la ventana de un minuto, o fallo temporal."""
        now = self._monotonic()
        while self._fetch_times and now - self._fetch_times[0] >= FETCH_WINDOW_SECONDS:
            self._fetch_times.popleft()
        if len(self._fetch_times) >= MAX_FETCHES_PER_WINDOW:
            raise CimdTemporaryError("rate_limited")
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
            headers={"User-Agent": f"Hermes/{__version__}"},
        )

    async def _fetch(self, url: str) -> tuple[CimdClient, int]:
        """Descarga y valida `url`. Devuelve el cliente y la vida en caché."""
        # aiohttp no pasa las IP literales por el resolvedor: se comprueban
        # aquí, antes de abrir ninguna conexión.
        host = urlsplit(url).hostname or ""
        literal = _literal_ip(host)
        if literal is not None and is_forbidden_address(literal):
            raise CimdInvalidError("forbidden_address")

        self._take_rate_slot()
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
                headers={"Accept": "application/json"},
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
