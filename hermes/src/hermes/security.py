"""Hermes — Seguridad: canonicalización, confirmation tokens y redacción.

Contiene tres piezas independientes:

- Canonicalización determinista de un par (tool, args) en un `action_hash`,
  para que un confirmation token solo valga para la acción exacta que se
  previsualizó.
- Ciclo de vida de los confirmation tokens en /data (crear, validar, completar,
  limpiar los expirados).
- Redacción de secretos, tanto en texto libre (`redact_secrets`, pensado para
  logs de add-ons ajenos) como en estructuras que las tools devuelven al
  cliente MCP (`redact_structure`).

La denylist de servicios peligrosos NO vive aquí: está en `service_policy`,
que es un módulo neutral para que lo importen tanto `hermes.ha` como
`hermes.tools`.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ── Directorio de tokens de confirmación ──────────────────────
CONFIRMATIONS_DIR = Path("/data/pending_confirmations")

# ── TTL de tokens ─────────────────────────────────────────────
CONFIRMATION_TTL_SECONDS = 60


# ── Canonicalización robusta para action_hash ─────────────────

def canonicalize_for_hash(value: Any) -> str:
    """Canonicaliza un valor Python para producir un hash determinista.

    Reglas:
    - Unicode NFC en todos los strings
    - Floats exactos (1.0, 2.0) → int
    - Floats no exactos → repr fijo f"{v:.17g}"
    - bool tratado aparte de int ({x: True} ≠ {x: 1})
    - NaN/Infinity → error (allow_nan=False)
    - Serialización: json.dumps(sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False, allow_nan=False)
    - SHA-256 hex del resultado UTF-8
    """
    normalized = _normalize_value(value)
    serialized = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_value(value: Any) -> Any:
    """Normaliza recursivamente un valor para canonicalización."""
    if value is None:
        return None

    # bool ANTES de int (bool es subclase de int en Python)
    if isinstance(value, bool):
        return {"__bool__": value}

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError(
                f"NaN/Infinity not allowed in canonicalization: {value}"
            )
        # Exactos → int
        if value == int(value) and abs(value) < 2**53:
            return int(value)
        # No exactos → repr fijo
        return {"__float__": f"{value:.17g}"}

    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)

    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]

    if isinstance(value, dict):
        # Force string keys: json.dumps(sort_keys=True) requires string keys.
        # Without this, a bool key normalizing to {"__bool__": True} would crash.
        result = {}
        for k, v in value.items():
            norm_k = _normalize_value(k)
            # Coerce non-string keys to their JSON representation
            if not isinstance(norm_k, str):
                norm_k = json.dumps(norm_k, sort_keys=True, separators=(",", ":"))
            result[norm_k] = _normalize_value(v)
        return result

    # Fallback: convertir a string
    return str(value)


def compute_action_hash(tool_name: str, args: dict[str, Any]) -> str:
    """Calcula el action_hash SHA-256 para un par (tool_name, args)."""
    payload = {"tool": tool_name, "args": args}
    return canonicalize_for_hash(payload)


# ── Gestión de confirmation tokens ────────────────────────────

async def create_confirmation_token(
    tool_name: str,
    args: dict[str, Any],
    preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Crea un token de confirmación vinculado a una acción.

    Devuelve: {confirmation_token, action_hash, expires_at, preview}
    """
    CONFIRMATIONS_DIR.mkdir(parents=True, exist_ok=True)

    token = str(uuid.uuid4())
    action_hash = compute_action_hash(tool_name, args)
    expires_at = time.time() + CONFIRMATION_TTL_SECONDS

    token_data = {
        "token": token,
        "action_hash": action_hash,
        "expires_at": expires_at,
        "state": "pending",
        "tool_name": tool_name,
        "created_at": time.time(),
        "retries": 0,
    }

    # Escribir atómicamente — un fichero por token
    token_path = CONFIRMATIONS_DIR / f"{token}.json"
    tmp_path = token_path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(token_data, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(str(tmp_path), str(token_path))

    result: dict[str, Any] = {
        "confirmation_token": token,
        "expires_in_seconds": CONFIRMATION_TTL_SECONDS,
    }
    if preview:
        result["preview"] = preview

    return result


async def validate_confirmation_token(
    token: str,
    tool_name: str,
    args: dict[str, Any],
) -> tuple[bool, str]:
    """Valida un token de confirmación.

    Devuelve: (is_valid, error_message)
    """
    token_path = CONFIRMATIONS_DIR / f"{token}.json"

    if not token_path.exists():
        return False, (
            "confirmation_token expired or lost across restart. "
            "Request a new preview."
        )

    try:
        token_data = json.loads(token_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, "confirmation_token corrupted. Request a new preview."

    # Verificar expiración
    if time.time() > token_data.get("expires_at", 0):
        _safe_unlink(token_path)
        return False, "confirmation_token expired. Request a new preview."

    # Verificar estado
    state = token_data.get("state", "")
    if state == "completed":
        return False, "confirmation_token already used."
    if state == "executing":
        return False, "confirmation_token is currently being executed."
    if state != "pending":
        return False, f"confirmation_token in unexpected state: {state}"

    # Verificar action_hash
    expected_hash = token_data.get("action_hash", "")
    actual_hash = compute_action_hash(tool_name, args)
    if expected_hash != actual_hash:
        return False, "confirmation_token does not match this action."

    # Marcar como executing
    token_data["state"] = "executing"
    tmp_path = token_path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(token_data, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(str(tmp_path), str(token_path))

    return True, ""


async def complete_confirmation_token(
    token: str,
    *,
    success: bool = True,
    result: Any = None,
    error: str = "",
) -> None:
    """Marca un token como completado o fallido."""
    token_path = CONFIRMATIONS_DIR / f"{token}.json"
    if not token_path.exists():
        return

    try:
        token_data = json.loads(token_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    token_data["state"] = "completed" if success else "failed"
    token_data["completed_at"] = time.time()
    # Mantener 60s más para idempotencia ante reintentos
    token_data["expires_at"] = time.time() + CONFIRMATION_TTL_SECONDS

    if success and result is not None:
        token_data["cached_result"] = result
    if not success and error:
        token_data["cached_error"] = error

    tmp_path = token_path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(token_data, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(str(tmp_path), str(token_path))


async def cleanup_expired_confirmations() -> int:
    """Elimina tokens expirados y ficheros corruptos.

    Devuelve el número de ficheros limpiados.
    Tolerante a fallos: si un fichero no se puede procesar, sigue con el resto.
    """
    if not CONFIRMATIONS_DIR.exists():
        CONFIRMATIONS_DIR.mkdir(parents=True, exist_ok=True)
        return 0

    cleaned = 0
    now = time.time()

    for token_file in CONFIRMATIONS_DIR.glob("*.json"):
        try:
            data = json.loads(token_file.read_text(encoding="utf-8"))
            if now > data.get("expires_at", 0):
                _safe_unlink(token_file)
                cleaned += 1
        except (json.JSONDecodeError, OSError, KeyError):
            # Fichero corrupto (crash durante escritura atómica)
            _safe_unlink(token_file)
            cleaned += 1

    # Limpiar ficheros .tmp huérfanos
    for tmp_file in CONFIRMATIONS_DIR.glob("*.tmp"):
        _safe_unlink(tmp_file)
        cleaned += 1

    if cleaned > 0:
        logger.info("confirmations_cleanup", cleaned=cleaned)

    return cleaned


# ── Redacción de secretos en texto libre (logs de add-ons) ────────────────

# Claves que indican que el valor siguiente es un secreto (case-insensitive)
_SECRET_KEY_RE = re.compile(
    r"(?i)"
    r"(password|passwd|token|api[_\-]?key|secret|bearer"
    r"|access[_\-]?token|refresh[_\-]?token|client[_\-]?secret"
    r"|credentials?|auth(?:orization)?)"
    r"(\s*[:=]\s*)"  # separator
    r"(\S+)",        # value
)

# URLs con basic auth: scheme://user:password@host
_BASIC_AUTH_URL_RE = re.compile(
    r"([a-zA-Z][a-zA-Z0-9+\-.]*://[^:/@\s]+)"  # scheme://user
    r"(:)([^@\s]+)"                              # :password
    r"(@)",                                      # @host separator
)

# JWT tokens: header.payload.signature (base64url)
_JWT_RE = re.compile(
    r"eyJ[A-Za-z0-9_\-]{2,}\.[A-Za-z0-9_\-]{2,}\.[A-Za-z0-9_\-]{2,}"
)


# Formato JSON: "clave": "valor". Necesita patrón propio porque `_SECRET_KEY_RE`
# espera `clave` + separador + valor pegados, y en JSON la comilla de cierre se
# interpone: sin este patrón, ninguna línea de log en JSON se redactaría —ni las
# del propio Hermes, cuyo JSONRenderer produce exactamente esa forma, ni las de
# los add-ons que también loguean en JSON.
_JSON_SECRET_RE = re.compile(
    r'("(?:[A-Za-z0-9_.-]*(?:password|passwd|passphrase|secret|token|api[_-]?key|'
    r'auth[_-]?key|credential|private[_-]?key)[A-Za-z0-9_.-]*)"\s*:\s*")([^"]*)(")',
    re.IGNORECASE,
)

# Forma sin separador: `password hunter2` (la usa Mosquitto, entre otros).
_BARE_SECRET_RE = re.compile(
    # Separador `[ \t]+` y no `\s+`: `\s` incluye el salto de línea, así que un
    # "passwd" al final de una línea se comería el "password:" de la siguiente,
    # consumiría ambos como una sola coincidencia y dejaría al descubierto el
    # valor que sí tocaba redactar.
    # El valor tampoco puede empezar por ':' ni '=': esas formas las cubre
    # _SECRET_KEY_RE, que preserva el separador.
    r"\b((?:password|passwd|token|api[_-]?key|secret)[ \t]+)(?![:=])(\S+)",
    re.IGNORECASE,
)


def redact_secrets(text: str) -> str:
    """Redacta secretos en texto plano — uso típico: logs de add-ons.

    Tres pasadas en orden:
    1. JWT tokens (eyJ…) → ***JWT_REDACTED***
    2. URLs con basic auth (http://user:pass@host) → http://user:***@host
    3. key: value / key=value donde key sugiere un secreto → key: ***REDACTED***

    Seguro ante texto vacío o None-como-string.
    """
    if not text:
        return text

    # 1. JWTs primero (pueden aparecer dentro de otros patrones)
    text = _JWT_RE.sub("***JWT_REDACTED***", text)

    # 1b. Formato JSON (ver el patrón arriba).
    text = _JSON_SECRET_RE.sub(r"\1***REDACTED***\3", text)

    # 2. Basic auth en URLs
    text = _BASIC_AUTH_URL_RE.sub(r"\1\2***\4", text)

    # 3. key: value — preserva el nombre de la clave y el separador
    text = _SECRET_KEY_RE.sub(r"\1\2***REDACTED***", text)

    # Último: la forma sin separador, para no pisar a los anteriores.
    text = _BARE_SECRET_RE.sub(r"\1***REDACTED***", text)

    return text


def _safe_unlink(path: Path) -> None:
    """Borra un fichero sin propagar excepciones."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


# ── Redacción de estructuras (respuestas de tools) ────────────────────────────

# Marcadores de clave sensible. Se buscan por SUBCADENA, igual que en
# `logging_setup`: las opciones de un add-on son nombres arbitrarios elegidos
# por su autor (`mqtt_password`, `ts_authkey`, `api_token`…) y una lista cerrada
# de claves exactas nunca los cubriría todos.
_SENSITIVE_KEY_MARKERS: tuple[str, ...] = (
    "password", "passwd", "passphrase",
    "secret", "token", "credential", "authorization",
    "api_key", "apikey", "auth_key", "authkey",
    "private_key", "privatekey", "salt",
)

_STRUCT_REDACTED = "***REDACTED***"


def _looks_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)


def redact_structure(value: Any, _key: str = "") -> Any:
    """Devuelve una copia del dato con los valores sensibles sustituidos.

    Pensado para lo que las tools devuelven al cliente MCP, no para logs
    (de eso se encarga `logging_setup`). Motivo: tools como `sv_get_addon` o
    `sv_get_addon_options` devuelven la respuesta del Supervisor, y ahí viaja
    el bloque `options` del add-on — incluida la `auth_password` del propio
    Hermes, que es el único secreto que protege la instalación. Sin esta
    redacción, un cliente con un token válido la leería en claro y se quedaría
    con un secreto de larga duración que sobrevive a la revocación del token.

    Solo se sustituyen valores de tipo texto: un número o un booleano bajo una
    clave como `token_expiry_seconds` no es un secreto y redactarlo solo
    generaría ruido.

    Las cadenas vacías se conservan: saber que una opción está SIN configurar
    es información de diagnóstico útil (p. ej. "el add-on no arranca porque le
    falta la contraseña") y no revela ningún secreto.
    """
    if isinstance(value, dict):
        return {k: redact_structure(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_structure(item, _key) for item in value]
    if isinstance(value, str) and value and _looks_sensitive(_key):
        return _STRUCT_REDACTED
    return value
