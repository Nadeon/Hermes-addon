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
from hermes.security import es_clave_sensible as _es_clave_sensible
from hermes.security import redact_secrets as _redact_secrets
from hermes.security import tapar_entero as _tapar_entero

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
    """Redacta recursivamente un diccionario.

    Bajo una clave sensible (el criterio del log más el de las respuestas,
    `es_clave_sensible`) el valor se tapa ENTERO, sea texto, número, objeto o
    lista: es `tapar_entero` de `security`, la regla de la 025 para lo que
    devuelven las tools (cierre de seguridad de la 1.2.0). Antes solo se
    tapaban textos y con la clave exacta de `_REDACT_KEYS`: un
    `{"network_key": {"key": [...]}}` o un `{"mqtt_password": "…"}` en un
    campo del log salían en claro.
    """
    result = {}
    for k, v in d.items():
        if _clave_del_log_sensible(str(k)) and _tapar_entero(v):
            result[k] = _REDACTED
        elif isinstance(v, dict):
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
#
# Campos: (activada, patrón del hostname público, hosts de las URLs de HA,
# sal). Los hosts de HA son pares (patrón, marcador) que rellena
# `set_ha_url_hosts` al conectar con HA (FR-002 de la 009).
_net_state: tuple[
    bool,
    re.Pattern[str] | None,
    tuple[tuple[re.Pattern[str], str], ...],
    bytes,
] = (False, None, (), b"")

_NET_PUBLIC_PLACEHOLDER = "<public_hostname>"
_NET_HA_EXTERNAL_PLACEHOLDER = "<ha_external_host>"
_NET_HA_INTERNAL_PLACEHOLDER = "<ha_internal_host>"

# Nombres que HA trae por defecto y no identifican a nadie. `homeassistant`,
# además, es el dominio de servicios del log (`homeassistant.restart`): taparlo
# dejaría el log ilegible sin ganar privacidad.
_HA_HOSTS_GENERICOS = frozenset({"localhost", "homeassistant", "homeassistant.local"})

# Cualquier nombre de Tailscale, no solo el propio: un peer o el hostname
# antiguo tras renombrar la máquina también identifican la tailnet. Las
# lookarounds evitan comerse parte de un nombre más largo.
_TS_NET_RE = re.compile(
    r"(?<![A-Za-z0-9.-])[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.ts\.net(?![A-Za-z0-9-])",
    re.IGNORECASE,
)

# Candidatos amplios; quien decide es `ipaddress`. Así `2026.11.1`,
# `999.1.1.1`, una hora `06:54:12` o una MAC no se tocan. Delante no puede ir
# una letra ni un dígito: `v1.2.3.4-beta` es una versión, no una IP. Sí puede
# ir un `_` (`x_192.0.2.5`) o un escape JSON `\n`/`\t`/`\r`: en las líneas
# antiguas que `sv_get_addon_logs` vuelve a redactar, la IP que sigue a un
# salto de línea escapado va pegada a la `n` (revisión 1.1.0, BAJO-2).
_IPV4_RE = re.compile(
    r"(?:(?<=\\[ntr])|(?<![A-Za-z0-9.]))\d{1,3}(?:\.\d{1,3}){3}(?![\w]|\.\d)"
)
# IPv6: hex, `:` y `.` (para `::ffff:10.0.0.5`). Se exigen en código al menos
# dos `:`. Los corchetes de `[2001:db8::1]:443` quedan fuera del candidato.
# Puede acabar en `::`: el prefijo delegado por el ISP (`2001:db8:1::/48`)
# identifica al abonado tanto como una dirección completa.
_IPV6_RE = re.compile(
    r"(?<![\w:.])[0-9A-Fa-f:][0-9A-Fa-f:.]*(?:[0-9A-Fa-f]|::)(?![\w:])"
)
# Nombres con la IPv4 escrita con guiones (`ip-10-0-0-5.ec2.internal`, el
# hostname por defecto de EC2 y de muchas imágenes cloud): llevan la IP privada
# de la máquina y `_IPV4_RE` exige puntos (FR-004 de la 009). Delante no puede
# ir una letra, un dígito ni un guion (`xip-…` es otro nombre) y detrás ni un
# carácter de palabra ni `-dígito` (`ip-10-0-0-5-6` no es una IPv4). El
# prefijo literal `ip-` ancla cada intento: lineal.
_IP_DASHED_RE = re.compile(
    r"(?<![A-Za-z0-9-])ip-(\d{1,3})-(\d{1,3})-(\d{1,3})-(\d{1,3})(?!\w|-\d)",
    re.IGNORECASE,
)

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


def _patron_de_host(host: str, guion_bajo: bool = False) -> re.Pattern[str]:
    """Patrón de un nombre de host sin distinguir mayúsculas.

    Las fronteras evitan tapar un trozo de un nombre más largo
    (`sub<host>`, `<host>ic`, `<host>.otro`).

    `guion_bajo`: `_` tampoco hace de frontera. Lo usan los hosts de las URLs
    de HA, que pueden ser de una sola etiqueta (`http://ha:8123`): sin esto,
    `ha` tapaba el principio de casi todos los eventos y tools del log
    (`ha_ws_connected` salía como `<ha_internal_host>_ws_connected`; revisión
    de la 009, T044). `_` no es válido en un nombre de host, así que no se
    deja de tapar ninguno en una URL.
    """
    extra = "_" if guion_bajo else ""
    return re.compile(
        rf"(?<![A-Za-z0-9{extra}.-]){re.escape(host)}"
        rf"(?![A-Za-z0-9{extra}-]|\.[A-Za-z0-9])",
        re.IGNORECASE,
    )


def configure_network_redaction(enabled: bool, public_hostname: str) -> None:
    """Activa o desactiva la redacción de red y genera una sal nueva.

    `public_hostname` puede llevar puerto (`host:8443`); solo se busca el
    nombre, sin distinguir mayúsculas, para cubrir también URLs y cabeceras.
    Los hosts de las URLs de HA quedan vacíos hasta `set_ha_url_hosts`.
    """
    global _net_state
    host = (public_hostname or "").strip()
    # Quitar el puerto: el nombre aparece con y sin él, y el puerto no
    # identifica a nadie.
    if host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    pattern = _patron_de_host(host) if host else None
    _net_state = (bool(enabled), pattern, (), secrets.token_bytes(16))


def _host_de_ha_util(
    host: str | None, public_re: re.Pattern[str] | None
) -> str | None:
    """El host en minúsculas si merece taparse; `None` si no.

    Fuera: vacío, los nombres por defecto de HA, los literales IP (ya los
    seudonimiza la redacción de IPs, que además dice su clase: tapar el nombre
    perdería esa información) y el hostname público (ya lo tapa su patrón).
    """
    host = (host or "").strip().strip("[]").lower()
    if not host or host in _HA_HOSTS_GENERICOS:
        return None
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    if public_re is not None and public_re.fullmatch(host):
        return None
    return host


def set_ha_url_hosts(external_host: str | None, internal_host: str | None) -> None:
    """Tapa en el log los hosts de `external_url` e `internal_url` de HA.

    Los lee `HAClient` de `/api/config` al conectar (FR-002 de la 009): el
    dominio propio de la casa salía en claro en cualquier línea que llevara
    una URL de HA. Sustituye el estado entero de una vez, como
    `configure_network_redaction`, pero conserva la sal: si la renovara, la
    misma IP tendría otro seudónimo antes y después de conectar y se perdería
    la correlación del log. `set_ha_url_hosts(None, None)` vacía la lista.
    """
    global _net_state
    enabled, public_re, _, salt = _net_state
    pares: list[tuple[re.Pattern[str], str]] = []
    externo = _host_de_ha_util(external_host, public_re)
    interno = _host_de_ha_util(internal_host, public_re)
    if externo is not None:
        pares.append((_patron_de_host(externo, guion_bajo=True), _NET_HA_EXTERNAL_PLACEHOLDER))
    if interno is not None and interno != externo:
        pares.append((_patron_de_host(interno, guion_bajo=True), _NET_HA_INTERNAL_PLACEHOLDER))
    _net_state = (enabled, public_re, tuple(pares), salt)


def network_redaction_enabled() -> bool:
    """True si la opción `log_redact_network` está activa."""
    return _net_state[0]


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
    return _seudonimo_ip(match.group(0), salt, v6=v6)


def _replace_ip_dashed(match: re.Match[str], salt: bytes) -> str:
    """`ip-a-b-c-d` → el seudónimo de `a.b.c.d`, o el texto tal cual.

    Reutiliza lo mismo que las IPv4 con puntos (ceros a la izquierda, loopback
    sin tocar, misma sal), así que la misma IP sale con el mismo seudónimo
    escrita de las dos formas.
    """
    punteada = ".".join(match.groups())
    sustituto = _seudonimo_ip(punteada, salt, v6=False)
    return match.group(0) if sustituto == punteada else sustituto


def _seudonimo_ip(text: str, salt: bytes, *, v6: bool) -> str:
    if v6 and text.count(":") < 2:
        return text
    # Un candidato que acaba en `:` solo vale si es `::` tras al menos dos
    # grupos (`2001:db8::`): así `a::` o `::` sueltos no se toman por IPs.
    if v6 and text.endswith(":") and (
        not text.endswith("::") or len([g for g in text.split(":") if g]) < 2
    ):
        return text
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        # `192.168.001.010`: `ipaddress` no admite ceros a la izquierda,
        # pero sigue siendo una IPv4 que identifica a alguien.
        if v6:
            return text
        try:
            ip = ipaddress.ip_address(".".join(str(int(o)) for o in text.split(".")))
        except ValueError:
            return text
    # Loopback no identifica a nadie y es lo que más ayuda a leer el log
    # (`trusted_proxy_ips: ["127.0.0.1"]`).
    if _unmap(ip).is_loopback:
        return text
    digest = hmac.new(salt, ip.packed, hashlib.sha256).hexdigest()[:8]
    return f"<ip:{_ip_class(ip)}:{digest}>"


def redact_network(text: str) -> str:
    """Sustituye hostnames, nombres `*.ts.net` e IPs no loopback de `text`.

    Orden: hostname público, hosts de las URLs de HA, `*.ts.net`, IPv6, IPv4 y
    `ip-a-b-c-d`. El público va primero para que, si coincide con
    `external_url`, salga como `<public_hostname>`.

    No hace nada si la redacción está desactivada. Es idempotente: lo ya
    redactado no vuelve a coincidir con ningún patrón, así que no importa que
    una línea pase por el processor y después por el filtro de `logging`.
    """
    enabled, host_re, ha_hosts, salt = _net_state
    if not enabled or not text:
        return text
    if host_re is not None:
        text = host_re.sub(_NET_PUBLIC_PLACEHOLDER, text)
    for patron, marcador in ha_hosts:
        text = patron.sub(marcador, text)
    text = _TS_NET_RE.sub("<redacted>.ts.net", text)
    # IPv6 antes que IPv4: en `::ffff:10.0.0.5` la IPv4 es parte de la IPv6.
    text = _IPV6_RE.sub(lambda m: _replace_ip(m, salt, v6=True), text)
    text = _IPV4_RE.sub(lambda m: _replace_ip(m, salt, v6=False), text)
    text = _IP_DASHED_RE.sub(lambda m: _replace_ip_dashed(m, salt), text)
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


def _clave_del_log_sensible(key: str) -> bool:
    """El criterio del log y, además, el de las respuestas de las tools
    (`es_clave_sensible`: `psk`, `network_key`, las claves S0/S2 de Z-Wave,
    `webhook_id`…), para que lo que se tapa en una respuesta no salga en el
    log."""
    return _key_looks_sensitive(key) or _es_clave_sensible(key)


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
        if not isinstance(value, str) and _clave_del_log_sensible(key) and _tapar_entero(value):
            # Una estructura o un número bajo una clave sensible, ENTERO
            # (`tapar_entero`, cierre de seguridad de la 1.2.0).
            redacted[key] = _REDACTED
        elif isinstance(value, str):
            if _clave_del_log_sensible(key):
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
