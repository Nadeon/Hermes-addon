"""Hermes — Logging con structlog en modo JSON + redactor de secretos.

Cada línea de log es un objeto JSON para que `ha addons logs hermes -f`
lo capture limpio. El redactor elimina tokens y secretos antes de loguear.
"""

from __future__ import annotations

import contextvars
import hashlib
import hmac
import ipaddress
import logging
import re
import secrets
from typing import Any

import structlog

# `hermes.security` no importa este módulo, así que no hay ciclo. Se
# encadena porque cubre formas que los patrones locales no ven: JSON,
# JWT y URLs con basic-auth.
from hermes.security import redact_secrets as _redact_secrets

# ── Context var para request ID ───────────────────────────────
REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

# ── Patrones de secretos a redactar ───────────────────────────
# Aplicados tanto a logs propios como a outputs de tools que traen
# logs externos (get_addon_logs, etc.)
_REDACT_KEYS = frozenset({
    "authorization",
    "supervisor_token",
    "password",
    "auth_password",
    "token",
    "api_key",
    "bearer_token",
    "access_token",
    "refresh_token",
    "client_secret",
    "secret",
})

_REDACT_PATTERNS = [
    # Bearer tokens en texto libre
    re.compile(r"(Bearer\s+)\S+", re.IGNORECASE),
    # SUPERVISOR_TOKEN en texto libre
    re.compile(r"(SUPERVISOR_TOKEN[=:]\s*)\S+", re.IGNORECASE),
]

_REDACTED = "***REDACTED***"


def _redact_value(key: str, value: Any) -> Any:
    """Redacta un valor si la clave es sensible."""
    if isinstance(value, str) and key.lower() in _REDACT_KEYS:
        return _REDACTED
    return value


def _redact_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Redacta recursivamente un diccionario."""
    result = {}
    for k, v in d.items():
        if isinstance(v, dict):
            result[k] = _redact_dict(v)
        elif isinstance(v, list):
            result[k] = [
                _redact_dict(item) if isinstance(item, dict) else _redact_value(k, item)
                for item in v
            ]
        else:
            result[k] = _redact_value(k, v)
    return result


def _redact_string(text: str) -> str:
    """Redacta patrones de secretos en texto libre (Bearer, SUPERVISOR_TOKEN)."""
    for pattern in _REDACT_PATTERNS:
        text = pattern.sub(rf"\g<1>{_REDACTED}", text)
    return text


def _redact_string_full(text: str) -> str:
    """Redacta secretos en texto libre — versión completa.

    Aplica tanto los regex patterns (Bearer, SUPERVISOR_TOKEN)
    como los key=value / key: value patterns para todas las _REDACT_KEYS.
    Usada por el processor interno y por redact_external_logs.
    """
    result = _redact_string(text)
    for key in _REDACT_KEYS:
        pattern = re.compile(
            rf"({re.escape(key)}\s*[=:]\s*)\S+", re.IGNORECASE
        )
        result = pattern.sub(rf"\g<1>{_REDACTED}", result)
    return result



# ── Redacción de datos de red (spec 003, US6) ─────────────────
# El repositorio es público y el log es lo que más se pega en un issue. Hasta
# 1.0.12 salían en claro el hostname de Tailscale (que identifica la tailnet y
# figura en Certificate Transparency), la IP de la tailnet, la IP real de cada
# cliente y la cabecera `Host` que el SDK de MCP registra al rechazar una
# petición. Decisión 10 del mantenedor: redactarlo POR DEFECTO, con la opción
# `log_redact_network` para desactivarlo al depurar.
#
# La redacción no puede dejar el log inservible para diagnosticar. Por eso
# cada IP se sustituye por `<ip:CLASE:HHHHHHHH>`: la clase (tailnet, privada,
# pública…) dice de dónde viene la petición, y el seudónimo —un HMAC con una
# sal aleatoria por proceso— permite correlacionar «las 40 peticiones de la
# misma IP» sin revelarla. Sin sal, el hash de una IPv4 se invierte por fuerza
# bruta en segundos (solo hay 2^32).

# Estado del módulo: desactivado hasta que `setup_logging` lo active, para que
# importar este módulo (o los tests que no lo configuran) no cambie nada.
# Se sustituye la tupla entera de una vez: un hilo que redacte mientras otro
# reconfigura ve el estado viejo o el nuevo, nunca una mezcla.
_net_state: tuple[bool, re.Pattern[str] | None, bytes] = (False, None, b"")

_NET_PUBLIC_PLACEHOLDER = "<public_hostname>"

# Cualquier nombre de Tailscale, no solo el propio: un peer o el hostname
# antiguo tras renombrar la máquina también identifican la tailnet. Las
# lookarounds evitan comerse parte de un nombre más largo.
_TS_NET_RE = re.compile(
    r"(?<![A-Za-z0-9.-])[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.ts\.net(?![A-Za-z0-9-])",
    re.IGNORECASE,
)

# Candidatos amplios; quien decide es `ipaddress`. Así `2026.11.1`,
# `999.1.1.1`, una hora `06:54:12` o una MAC no se tocan. Delante no puede ir
# una letra ni un dígito: `v1.2.3.4-beta` es una versión, no una IP.
_IPV4_RE = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w]|\.\d)")
# IPv6: hex, `:` y `.` (para `::ffff:10.0.0.5`). Se exigen en código al menos
# dos `:`. Los corchetes de `[2001:db8::1]:443` quedan fuera del candidato.
_IPV6_RE = re.compile(r"(?<![\w:.])[0-9A-Fa-f:][0-9A-Fa-f:.]*[0-9A-Fa-f](?![\w:])")

# Rangos de la tailnet: el CGNAT que usa Tailscale y su ULA fija.
_TAILNET_NETS = (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fd7a:115c:a1e0::/48"),
)
# Privadas enumeradas a mano: `is_private` de `ipaddress` incluye también los
# rangos de documentación, y esos deben salir como `other`.
_PRIVATE_NETS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def configure_network_redaction(enabled: bool, public_hostname: str) -> None:
    """Activa o desactiva la redacción de red y genera una sal nueva.

    `public_hostname` puede llevar puerto (`host:8443`); solo se busca el
    nombre, sin distinguir mayúsculas, para cubrir también URLs y cabeceras.
    """
    global _net_state
    host = (public_hostname or "").strip()
    # Quitar el puerto: el nombre aparece con y sin él, y el puerto no
    # identifica a nadie.
    if host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    pattern = (
        re.compile(
            rf"(?<![A-Za-z0-9.-]){re.escape(host)}(?![A-Za-z0-9-]|\.[A-Za-z0-9])",
            re.IGNORECASE,
        )
        if host
        else None
    )
    _net_state = (bool(enabled), pattern, secrets.token_bytes(16))


def _unmap(ip: _IPAddress) -> _IPAddress:
    """`::ffff:10.0.0.5` es la IPv4 `10.0.0.5`: se clasifica como tal."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _ip_class(ip: _IPAddress) -> str:
    ip = _unmap(ip)
    # El orden importa: 100.64.0.0/10 no es global, y la ULA de Tailscale
    # está dentro de fc00::/7; la tailnet tiene que ganar a ambas.
    if any(ip in net for net in _TAILNET_NETS if net.version == ip.version):
        return "tailnet"
    if ip.is_link_local:
        return "link-local"
    if any(ip in net for net in _PRIVATE_NETS if net.version == ip.version):
        return "private"
    if ip.is_global:
        return "public"
    return "other"


def _replace_ip(match: re.Match[str], salt: bytes, *, v6: bool) -> str:
    text = match.group(0)
    if v6 and text.count(":") < 2:
        return text
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return text
    # Loopback no identifica a nadie y es lo que más ayuda a leer el log
    # (`trusted_proxy_ips: ["127.0.0.1"]`).
    if _unmap(ip).is_loopback:
        return text
    digest = hmac.new(salt, ip.packed, hashlib.sha256).hexdigest()[:8]
    return f"<ip:{_ip_class(ip)}:{digest}>"


def redact_network(text: str) -> str:
    """Sustituye hostname, nombres `*.ts.net` e IPs no loopback de `text`.

    No hace nada si la redacción está desactivada. Es idempotente: lo ya
    redactado no vuelve a coincidir con ningún patrón, así que no importa que
    una línea pase por el processor y después por el filtro de `logging`.
    """
    enabled, host_re, salt = _net_state
    if not enabled or not text:
        return text
    if host_re is not None:
        text = host_re.sub(_NET_PUBLIC_PLACEHOLDER, text)
    text = _TS_NET_RE.sub("<redacted>.ts.net", text)
    # IPv6 antes que IPv4: en `::ffff:10.0.0.5` la IPv4 es parte de la IPv6.
    text = _IPV6_RE.sub(lambda m: _replace_ip(m, salt, v6=True), text)
    text = _IPV4_RE.sub(lambda m: _replace_ip(m, salt, v6=False), text)
    return text


def _redact_network_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_network(value)
    if isinstance(value, dict):
        return {k: _redact_network_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_redact_network_value(v) for v in value)
    return value


def _redact_network_processor(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Redacta datos de red en todo el event_dict, recursivamente.

    Recorre todos los campos y no una lista de nombres (`src_ip`, `peer_ip`…):
    las IPs llegan también en `error`, en URLs y en trazas, con el nombre de
    campo que quiera darles quien loguea.
    """
    if not _net_state[0]:
        return event_dict
    return {k: _redact_network_value(v) for k, v in event_dict.items()}


class _NetworkRedactionFilter(logging.Filter):
    """Redacta los registros del `logging` estándar antes de escribirlos.

    El aviso `Invalid Host header: …` del SDK de MCP, `uvicorn` y `aiohttp`
    usan `logging` directamente, no structlog, así que el processor no los ve.
    Se formatea el mensaje con sus argumentos, se redacta y se dejan los
    argumentos a `None` para que el manejador no vuelva a formatear el
    original. La traza se formatea aquí también para poder redactarla.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not _net_state[0]:
            return True
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — un mensaje mal formado no debe tirar el log
            return True
        record.msg = redact_network(message)
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_network(record.exc_text)
        if record.stack_info:
            record.stack_info = redact_network(record.stack_info)
        return True


def _install_network_filter() -> None:
    """Pone el filtro en los manejadores del raíz, sin duplicarlo.

    Va en los manejadores y no en el logger raíz porque los filtros de un
    logger no se aplican a los registros que le llegan propagados de sus
    hijos (`mcp.server.transport_security` → raíz).
    """
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, _NetworkRedactionFilter) for f in handler.filters):
            handler.addFilter(_NetworkRedactionFilter())


# ── Processors de structlog ───────────────────────────────────

def _add_request_id(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Añade request_id al log si existe en el contexto."""
    req_id = REQUEST_ID.get()
    if req_id is not None:
        event_dict["request_id"] = req_id
    return event_dict


# Marcadores de clave sensible, por SUBCADENA. Comparar la clave completa
# —como hace `_REDACT_KEYS`— deja pasar en claro nombres perfectamente
# normales: `mqtt_password`, `api_token`, `ts_authkey`. Ambas comprobaciones
# conviven en `_key_looks_sensitive`.
_SENSITIVE_KEY_MARKERS: tuple[str, ...] = (
    "password", "passwd", "passphrase", "secret", "token", "credential",
    "authorization", "api_key", "apikey", "auth_key", "authkey",
    "private_key", "privatekey", "salt",
)


def _key_looks_sensitive(key: str) -> bool:
    lowered = key.lower()
    return lowered in _REDACT_KEYS or any(
        marker in lowered for marker in _SENSITIVE_KEY_MARKERS
    )


def _redact_processor(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Redacta secretos de TODO el event_dict antes de serializar.

    Dos decisiones que parecen excesivas y no lo son:

    1. La clave se considera sensible por SUBCADENA, no por igualdad contra
       `_REDACT_KEYS`.
    2. Los patrones de texto (`Bearer …`, `token=…`, JSON, JWT, basic-auth en
       URL) se aplican a TODOS los valores de tipo texto, no solo al `event`.

    El motivo es que el contenido más peligroso llega en campos con nombres
    inocuos: `LoggingMiddleware` mete en `error` el cuerpo de las respuestas
    4xx/5xx, y `ha.py` loguea el cuerpo de las respuestas upstream. Es
    contenido ajeno, con la forma que quiera darle quien lo emita, y sin estas
    dos reglas la cadena queda cerrada de punta a punta: upstream → log sin
    redactar → `sv_get_addon_logs` → cliente MCP.
    """
    redacted: dict[str, Any] = {}
    for key, value in event_dict.items():
        if isinstance(value, str):
            if _key_looks_sensitive(key):
                redacted[key] = _REDACTED
            else:
                # Se encadena con `redact_secrets`, que cubre formas que los
                # patrones locales no ven: JSON (`"password": "x"`), JWT y URLs
                # con basic-auth. El campo `error` del middleware trae justo
                # esas formas.
                redacted[key] = _redact_secrets(_redact_string_full(value))
        elif isinstance(value, dict):
            redacted[key] = _redact_dict(value)
        elif isinstance(value, list):
            redacted[key] = [
                _redact_secrets(_redact_string_full(v)) if isinstance(v, str) else v for v in value
            ]
        else:
            redacted[key] = value
    return redacted


def setup_logging(
    level: str = "info",
    *,
    redact_network: bool = False,
    public_hostname: str = "",
) -> None:
    """Configura structlog en modo JSON a stdout.

    Llamar una sola vez al arranque, antes de cualquier log.

    `redact_network` activa la redacción de hostname e IPs (opción
    `log_redact_network`). Vale `False` por defecto para que esta firma no
    cambie nada hasta que el arranque le pase la opción; los secretos se
    redactan siempre, con o sin ella.
    """
    configure_network_redaction(redact_network, public_hostname)
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Configurar logging estándar para que structlog capture todo
    logging.basicConfig(
        format="%(message)s",
        level=log_level,
    )

    # Silenciar logs ruidosos de uvicorn y aiohttp
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

    # Tras `basicConfig`, que es quien crea el manejador de stdout.
    _install_network_filter()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _add_request_id,
            structlog.processors.format_exc_info,  # antes del redactor: el traceback también se redacta
            _redact_processor,
            # Tras los secretos y tras `format_exc_info`: la traza ya es texto
            # y también se redacta.
            _redact_network_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
