"""Hermes — Logging con structlog en modo JSON + redactor de secretos.

Cada línea de log es un objeto JSON para que `ha addons logs hermes -f`
lo capture limpio. El redactor elimina tokens y secretos antes de loguear.
"""

from __future__ import annotations

import contextvars
import logging
import re
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


def setup_logging(level: str = "info") -> None:
    """Configura structlog en modo JSON a stdout.

    Llamar una sola vez al arranque, antes de cualquier log.
    """
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
            structlog.processors.StackInfoRenderer(),
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
