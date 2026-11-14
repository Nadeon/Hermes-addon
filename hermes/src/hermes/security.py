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

# ── Tope de lo guardado junto a los tokens ───────────────────
# Suma de los bytes de los documentos guardados en los tokens vigentes. Cada
# documento cabe en una petición (`max_request_body_bytes`, 4 MiB por defecto)
# y el techo global es de 120 peticiones por minuto: sin tope, un cliente
# podría dejar unos 480 MiB en /data durante un minuto. 16 MiB caben cuatro
# documentos del tamaño máximo y cientos de dashboards reales.
CONFIRMATION_STORED_MAX_BYTES = 16 * 1024 * 1024

# ── Barrido acotado (FR-009 de la 009) ───────────────────────
# En la 1.1.2 cada vista previa con documento releía y parseaba todos los
# tokens del directorio para barrer los caducados y sumar lo guardado: con el
# tope casi lleno, decenas de milisegundos en el bucle de eventos por vista
# previa. Ahora se barre como mucho una vez por segundo y, entre barridos, el
# total sale de memoria: el del último barrido más lo guardado después.
#
# Al completar o caducar un token el total NO se descuenta hasta el siguiente
# barrido: se sobrestima, nunca se subestima. Sobrestimar solo puede hacer que
# un documento no se guarde y haya que reenviarlo entero (el comportamiento
# degradado de la 1.1.1, ya previsto); subestimar dejaría pasar del tope
# (fail-closed, principio III). Restar en cada sitio exigiría acertar en tres
# caminos y reconciliar con el disco al arrancar; un error en una resta rompe
# el tope.
_BARRIDO_MIN_INTERVALO_S = 1.0
# Bytes de documentos de tokens vigentes según el último barrido, más los
# guardados después. Invariante: >= lo realmente guardado en tokens vigentes.
_en_uso_bytes = 0
# `_monotonic()` del último barrido completo; `None` = ninguno.
_ultimo_barrido: float | None = None
# Directorio del último barrido: el total es de ese directorio. Si cambia
# (los tests lo cambian; en producción es fijo), se barre de nuevo.
_barrido_dir: Path | None = None


def _monotonic() -> float:
    """Reloj del barrido; función propia para poder simularlo en los tests sin
    tocar el `time.monotonic` que usa el bucle de eventos."""
    return time.monotonic()


def _toca_barrer() -> bool:
    """True si el total en memoria no vale y hay que releer el directorio."""
    if _ultimo_barrido is None or _barrido_dir != CONFIRMATIONS_DIR:
        return True
    transcurrido = _monotonic() - _ultimo_barrido
    # Negativo: el reloj no avanzó como se espera; mejor barrer que fiarse.
    return transcurrido < 0 or transcurrido >= _BARRIDO_MIN_INTERVALO_S


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


def _escape_key(key: str) -> str:
    """Aparta las claves de usuario del espacio de nombres de los centinelas.

    Los floats y los bools se codifican como `{"__float__": ...}` /
    `{"__bool__": ...}`. Sin escapar, un dict escrito a mano por el cliente
    —`{"x": {"__float__": "1.5"}}`— normalizaba EXACTAMENTE igual que `{"x":
    1.5}`: dos acciones distintas con el mismo action_hash, y el action_hash es
    lo único que ata un confirmation_token a lo que se va a ejecutar. Quien
    obtuviera un token para una acción inocua podía canjearlo por otra.

    Con el escape, toda clave de usuario que empiece por '__' sale con un '_'
    delante, así que las claves emitidas por el usuario empiezan por '___' y
    jamás pueden coincidir con un centinela. La transformación es inyectiva
    (claves distintas siguen dando claves distintas), que es lo que hace falta
    para que el hash no colisione.
    """
    return "_" + key if key.startswith("__") else key


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
            result[_escape_key(norm_k)] = _normalize_value(v)
        return result

    # Fallback: convertir a string
    return str(value)


def compute_action_hash(tool_name: str, args: dict[str, Any]) -> str:
    """Calcula el action_hash SHA-256 para un par (tool_name, args)."""
    payload = {"tool": tool_name, "args": args}
    return canonicalize_for_hash(payload)


# ── Gestión de confirmation tokens ────────────────────────────

# Formato exacto de lo que emite `create_confirmation_token`: un UUID4 en
# minúsculas. Se comprueba ANTES de construir ninguna ruta con el token. Sin
# esta guarda, `CONFIRMATIONS_DIR / f"{token}.json"` con un token como
# `../options` sale del directorio de confirmaciones, y como
# `validate_confirmation_token` borra el fichero que encuentra cuando no parece
# un token vigente, cualquier llamada a una tool destructiva se convertía en
# una primitiva para borrar ficheros `.json` arbitrarios bajo /data y más allá.
_TOKEN_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def is_valid_confirmation_token_format(token: object) -> bool:
    """True si `token` tiene la forma de un token emitido por Hermes."""
    return isinstance(token, str) and _TOKEN_RE.match(token) is not None


def _bytes_guardados(guardados: dict[str, Any]) -> int:
    """Tamaño de lo guardado tal como se escribe en el fichero del token."""
    return len(json.dumps(guardados, ensure_ascii=False).encode("utf-8"))


def _pistas_de_confirmacion(
    tool_name: str,
    args: dict[str, Any],
    guardados: dict[str, Any],
    no_guardados: list[str],
) -> dict[str, Any]:
    """Campos de la vista previa que dicen al agente cómo confirmar.

    Sin ellos el agente reenvía el documento entero como en 1.1.1 y la
    confirmación sigue llegando tarde: a unos 0,4 KB/s, uno de 41 KB tarda más
    que los 60 s del token solo en escribirse. Si el documento no se pudo
    guardar (tope), se dice que hay que reenviarlo todo: el comportamiento de
    1.1.1, nunca uno más permisivo.
    """
    confirm_with = sorted(
        {k for k in args if k not in guardados} | {"confirmation_token"}
    )
    pistas: dict[str, Any] = {"confirm_with": confirm_with}
    if guardados:
        omitir = sorted(guardados)
        pistas["omit_on_confirm"] = omitir
        pistas["confirm_hint"] = (
            f"To confirm, call {tool_name} again with only "
            f"{', '.join(confirm_with)}. {', '.join(omitir)} can be omitted: "
            "the server kept the one from this preview. Any argument you do "
            "send must be identical to the preview."
        )
    else:
        pistas["confirm_hint"] = (
            "Repeat the same call with all the same arguments plus "
            "confirmation_token: the server could not keep "
            f"{', '.join(no_guardados)} this time."
        )
    return pistas


async def create_confirmation_token(
    tool_name: str,
    args: dict[str, Any],
    preview: dict[str, Any] | None = None,
    *,
    omitibles: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Crea un token de confirmación vinculado a una acción.

    `omitibles` son los argumentos que la tool deja omitir al confirmar (su
    documento grande). Se guardan junto al token para que la confirmación no
    tenga que reescribirlos; las tools que no los declaran guardan lo mismo
    que en 1.1.1.

    Devuelve: {confirmation_token, expires_in_seconds, preview} y, si la tool
    declara omitibles, {confirm_with, omit_on_confirm, confirm_hint}.
    """
    CONFIRMATIONS_DIR.mkdir(parents=True, exist_ok=True)

    token = str(uuid.uuid4())
    # El hash se calcula con TODOS los argumentos, como siempre: es lo que ata
    # el token a la acción previsualizada, se omita después lo que se omita.
    action_hash = compute_action_hash(tool_name, args)
    expires_at = time.time() + CONFIRMATION_TTL_SECONDS

    token_data: dict[str, Any] = {
        "token": token,
        "action_hash": action_hash,
        "expires_at": expires_at,
        "state": "pending",
        "tool_name": tool_name,
        "created_at": time.time(),
        "retries": 0,
    }

    # Solo los omitibles de la tool presentes en la vista previa, con el valor
    # que entró en el hash. Nada más: guardar todos los argumentos escribiría
    # en disco, por ejemplo, las opciones con contraseñas de
    # sv_set_addon_options, y los demás ya los ata el action_hash.
    guardados = {k: args[k] for k in omitibles if args.get(k) is not None}
    no_guardados: list[str] = []
    if guardados:
        # Los documentos pendientes pueden llevar datos sensibles: las vistas
        # previas barren los caducados, y el mismo barrido da lo que ocupan
        # los vigentes para el tope. Como mucho un barrido por segundo (ver
        # `_BARRIDO_MIN_INTERVALO_S`); entre medias, el total de memoria.
        # Sin ningún `await` entre leer el total y sumarle lo guardado.
        global _en_uso_bytes
        if _toca_barrer():
            _barrer_caducados()
        tam = _bytes_guardados(guardados)
        if _en_uso_bytes + tam <= CONFIRMATION_STORED_MAX_BYTES:
            token_data["stored_args"] = guardados
            token_data["stored_bytes"] = tam
            _en_uso_bytes += tam
        else:
            # Fail-closed: el token se emite igual, pero sin documento; la
            # confirmación tendrá que reenviarlo todo, como en 1.1.1. Al log,
            # solo nombres y bytes, nunca el contenido.
            no_guardados = sorted(guardados)
            logger.warning(
                "confirmation_args_not_stored",
                tool=tool_name,
                reason="storage_cap",
                keys=no_guardados,
                bytes=tam,
            )
            guardados = {}

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
    if omitibles:
        result.update(
            _pistas_de_confirmacion(tool_name, args, guardados, no_guardados)
        )

    return result


async def validate_confirmation_token(
    token: str,
    tool_name: str,
    args: dict[str, Any],
) -> tuple[bool, str]:
    """Valida un token de confirmación.

    Envoltorio de `resolve_confirmation_token` sin omitibles: las tools que no
    declaran ninguno siguen exigiendo todos los argumentos, como en 1.1.1.

    Devuelve: (is_valid, error_message)
    """
    ok, error, _ = await resolve_confirmation_token(token, tool_name, args)
    return ok, error


async def resolve_confirmation_token(
    token: str,
    tool_name: str,
    args: dict[str, Any],
    *,
    omitibles: tuple[str, ...] = (),
) -> tuple[bool, str, dict[str, Any]]:
    """Valida un token y devuelve los argumentos con los que se ejecuta.

    Un omitible ausente (o `None`) en `args` se toma de lo guardado en la
    vista previa; uno presente se usa tal cual. El action_hash se comprueba
    sobre los argumentos resultantes, así que un documento distinto, otro
    destino, un argumento añadido u otra tool dan «does not match», como
    siempre, y el token no se gasta.

    Entre leer el estado y escribir `executing` no hay ningún `await`: en un
    solo bucle de eventos eso es atómico frente a otra confirmación del mismo
    token, y solo una de las dos ejecuta.

    Devuelve: (is_valid, error_message, args_resueltos)
    """
    if not is_valid_confirmation_token_format(token):
        return False, "confirmation_token malformed. Request a new preview.", {}

    token_path = CONFIRMATIONS_DIR / f"{token}.json"

    if not token_path.exists():
        return False, (
            "confirmation_token expired or lost across restart. "
            "Request a new preview."
        ), {}

    try:
        token_data = json.loads(token_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, "confirmation_token corrupted. Request a new preview.", {}

    # Verificar expiración
    if time.time() > token_data.get("expires_at", 0):
        _safe_unlink(token_path)
        return False, "confirmation_token expired. Request a new preview.", {}

    # Verificar estado
    state = token_data.get("state", "")
    if state == "completed":
        return False, "confirmation_token already used.", {}
    if state == "executing":
        return False, "confirmation_token is currently being executed.", {}
    if state != "pending":
        return False, f"confirmation_token in unexpected state: {state}", {}

    guardados = token_data.get("stored_args")
    if not isinstance(guardados, dict):
        guardados = {}
    # Omitido sin nada guardado (token emitido con el tope lleno, o por la
    # 1.1.1 antes de actualizar): se rechaza sin tocar el estado, para que el
    # cliente pueda repetir la llamada completa dentro del TTL.
    faltan = [k for k in omitibles if args.get(k) is None and k not in guardados]
    if faltan:
        return False, (
            f"confirmation_token has no stored value for: {', '.join(faltan)}. "
            "Repeat the call with all its arguments."
        ), {}
    resueltos = {
        k: v for k, v in args.items() if not (k in omitibles and v is None)
    }
    for k in omitibles:
        if args.get(k) is None:
            resueltos[k] = guardados[k]

    # Verificar action_hash sobre los argumentos resultantes: lo que se manda
    # tiene que coincidir con lo previsualizado, y lo que se omite sale de lo
    # que se previsualizó.
    expected_hash = token_data.get("action_hash", "")
    actual_hash = compute_action_hash(tool_name, resueltos)
    if expected_hash != actual_hash:
        return False, "confirmation_token does not match this action.", {}

    # Marcar como executing
    token_data["state"] = "executing"
    tmp_path = token_path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(token_data, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(str(tmp_path), str(token_path))

    return True, "", resueltos


async def complete_confirmation_token(
    token: str,
    *,
    success: bool = True,
    result: Any = None,
    error: str = "",
) -> None:
    """Marca un token como completado o fallido."""
    if not is_valid_confirmation_token_format(token):
        return
    token_path = CONFIRMATIONS_DIR / f"{token}.json"
    if not token_path.exists():
        return

    try:
        token_data = json.loads(token_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    token_data["state"] = "completed" if success else "failed"
    token_data["completed_at"] = time.time()
    # El documento guardado ya no hace falta: el token no se puede volver a
    # usar. Se borra ya, y no al caducar, porque puede llevar datos sensibles
    # (un fs_write_file) y /data entra en los backups del add-on.
    token_data.pop("stored_args", None)
    token_data.pop("stored_bytes", None)
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


def _barrer_caducados() -> tuple[int, int]:
    """Borra tokens caducados, ficheros corruptos y `.tmp` huérfanos.

    Síncrona a propósito: la llama también `create_confirmation_token`, y sin
    ningún `await` dentro no se intercala con la escritura de otro token.

    Devuelve (ficheros limpiados, bytes de documentos guardados en los tokens
    vigentes). Lo segundo sale del mismo recorrido, que ya lee cada fichero
    para mirar su `expires_at`, y es lo que se compara con
    CONFIRMATION_STORED_MAX_BYTES.
    Tolerante a fallos: si un fichero no se puede procesar, sigue con el resto.

    Fija el total en memoria y la hora del barrido (FR-009 de la 009).
    """
    global _en_uso_bytes, _ultimo_barrido, _barrido_dir
    if not CONFIRMATIONS_DIR.exists():
        CONFIRMATIONS_DIR.mkdir(parents=True, exist_ok=True)
        _en_uso_bytes, _ultimo_barrido = 0, _monotonic()
        _barrido_dir = CONFIRMATIONS_DIR
        return 0, 0

    cleaned = 0
    en_uso = 0
    now = time.time()

    for token_file in CONFIRMATIONS_DIR.glob("*.json"):
        try:
            data = json.loads(token_file.read_text(encoding="utf-8"))
            if now > data.get("expires_at", 0):
                _safe_unlink(token_file)
                cleaned += 1
            elif isinstance(data.get("stored_bytes"), int):
                en_uso += data["stored_bytes"]
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

    _en_uso_bytes, _ultimo_barrido = en_uso, _monotonic()
    _barrido_dir = CONFIRMATIONS_DIR
    return cleaned, en_uso


async def cleanup_expired_confirmations() -> int:
    """Elimina tokens expirados y ficheros corruptos.

    Devuelve el número de ficheros limpiados.
    """
    cleaned, _ = _barrer_caducados()
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

# ── Por qué estas tres expresiones no son las de la 1.1.2 (FR-001, 009) ──
#
# En la 1.1.2 eran `eyJ[...]{2,}\.…`, `[a-zA-Z][a-zA-Z0-9+\-.]*://…` y
# `"[...]*(?:password|…)[...]*"…`: un prefijo que puede empezar en cada
# posición de una misma racha de caracteres, que la recorre hasta el final y
# falla al no encontrar el delimitador (`.`, `://` o `@`, `"`). n posiciones ×
# n caracteres: 30 KB de `eyJ` repetido, de `a://b:c` repetido o de `"` +
# `password` repetido tardaban 0,4–0,6 s, y `sv_get_addon_logs` redacta en el
# bucle de eventos (un log así bloqueaba Hermes para todos los clientes).
#
# Ahora cada carácter se examina un número acotado de veces y lo redactado es
# EXACTAMENTE lo mismo (test diferencial contra la 1.1.2 en
# tests/test_redact_secrets.py). Lo que no vale:
# - trocear la entrada parte un secreto en la frontera del trozo;
# - acotar los cuantificadores (`{2,64}`) deja sin redactar JWT largos y sigue
#   siendo cuadrático dentro de la cota;
# - una frontera con lookbehind (`(?<![A-Za-z0-9_-])eyJ`) es lineal pero deja
#   de redactar un JWT pegado a una letra (`xeyJ…`), que la 1.1.2 sí redacta:
#   redactar menos no se acepta (principio II).
#
# La idea común: dentro de una racha, todas las posiciones de inicio llegan al
# mismo final de racha, así que si falla la primera fallan todas. Se intenta
# solo la primera (se empieza en el inicio de la racha y se avanza de forma
# atómica hasta ella) y los cuantificadores son posesivos, que no retroceden.

# JWT tokens: header.payload.signature (base64url). El grupo 1 es lo que hay
# entre el inicio de la racha y el primer `eyJ`, que se conserva; desde ese
# `eyJ` el resultado es el de `eyJ[...]{2,}\.[...]{2,}\.[...]{2,}`: los
# segmentos son rachas completas porque `.` no está en la clase.
_JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_\-])(?>([A-Za-z0-9_\-]*?)eyJ)"
    r"[A-Za-z0-9_\-]{2,}+\.[A-Za-z0-9_\-]{2,}+\.[A-Za-z0-9_\-]{2,}+"
)

# URLs con basic auth: scheme://user:password@host. El prefijo `scheme://user:`
# se busca desde el inicio de cada racha del esquema, en su primera letra: las
# siguientes letras de la misma racha llegan al mismo `://` y fallarían igual.
_BASIC_AUTH_PREFIJO_RE = re.compile(
    r"(?<![a-zA-Z0-9+\-.])[0-9+\-.]*+"
    r"([a-zA-Z][a-zA-Z0-9+\-.]*+://[^:/@\s]++:)"
)
# La contraseña: todo hasta el primer `@` o espacio; tiene que acabar en `@`.
_BASIC_AUTH_CLAVE_RE = re.compile(r"[^@\s]*+")


def _redactar_basic_auth(text: str) -> str:
    """Equivale a `re.sub` de la expresión de la 1.1.2 con `\\1\\2***\\4`.

    En `a://b:c` repetido sin `@`, cada repetición es un candidato cuya
    contraseña llega hasta el final del texto: la 1.1.2 la recorría entera en
    cada uno. Aquí se recuerda la última contraseña recorrida: si el candidato
    siguiente empieza dentro de ella, acaba en el mismo sitio (entre medias no
    hay `@` ni espacio), así que cada carácter se recorre una vez.
    """
    if "://" not in text:
        return text
    trozos: list[str] = []
    copiado = 0
    pos = 0
    visto_desde, visto_hasta = -1, -1
    n = len(text)
    while True:
        m = _BASIC_AUTH_PREFIJO_RE.search(text, pos)
        if m is None:
            break
        x = m.end()
        if visto_desde <= x < visto_hasta:
            fin = visto_hasta
        else:
            fin = _BASIC_AUTH_CLAVE_RE.match(text, x).end()  # type: ignore[union-attr]
            visto_desde, visto_hasta = x, fin
        if x < fin < n and text[fin] == "@":
            trozos.append(text[copiado:x])
            trozos.append("***@")
            copiado = pos = fin + 1
        else:
            pos = m.start(1) + 1
    if not trozos:
        return text
    trozos.append(text[copiado:])
    return "".join(trozos)


# Formato JSON: "clave": "valor". Necesita patrón propio porque `_SECRET_KEY_RE`
# espera `clave` + separador + valor pegados, y en JSON la comilla de cierre se
# interpone: sin este patrón, ninguna línea de log en JSON se redactaría —ni las
# del propio Hermes, cuyo JSONRenderer produce exactamente esa forma, ni las de
# los add-ons que también loguean en JSON.
#
# Forma lineal (FR-001, 009): la clave es la racha entera hasta la comilla
# (`"` no está en la clase), así que primero un lookahead posesivo comprueba
# que la racha se cierra con `"`, y la palabra clave se busca una sola vez, de
# forma atómica: si lo que sigue falla, buscarla más adelante en la misma
# clave daría el mismo fallo. En la 1.1.2, `"` + `password` repetido sin
# cierre retrocedía probando cada aparición hasta el final.
_JSON_SECRET_RE = re.compile(
    r'("(?=[A-Za-z0-9_.-]*+")'
    r'(?>[A-Za-z0-9_.-]*?(?:password|passwd|passphrase|secret|token|api[_-]?key|'
    r'auth[_-]?key|credential|private[_-]?key))'
    r'[A-Za-z0-9_.-]*+"\s*+:\s*+")([^"]*+)(")',
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
    text = _JWT_RE.sub(r"\1***JWT_REDACTED***", text)

    # 1b. Formato JSON (ver el patrón arriba).
    text = _JSON_SECRET_RE.sub(r"\1***REDACTED***\3", text)

    # 2. Basic auth en URLs
    text = _redactar_basic_auth(text)

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
# Las claves criptográficas de los add-ons de red (WireGuard, Z-Wave, Zigbee,
# Matter) no se llaman "password" ni "token": son `psk`, `pre_shared_key`,
# `network_key`, `encryption_key`. Sin ellas en la lista, `sv_get_addon` y
# `sv_get_addon_options` devolvían en claro justo el material que da acceso a
# la red — verificado con {"peers":[{"psk":"..."}], "network_key":"..."}.
# `key` a secas NO entra: casi todo add-on tiene opciones con `key` en el
# nombre que no son secretos (`keyboard_layout`, `key_path`, `sort_key`).
_SENSITIVE_KEY_MARKERS: tuple[str, ...] = (
    "password", "passwd", "passphrase",
    "secret", "token", "credential", "authorization",
    "api_key", "apikey", "auth_key", "authkey",
    "private_key", "privatekey", "privkey", "salt",
    "psk", "shared_key", "sharedkey",
    "network_key", "networkkey",
    "encryption_key", "encryptionkey",
    # Credencial de hecho: quien conoce el `webhook_id` dispara la
    # automatización sin autenticarse, y viaja en la `config` y en
    # `trigger` de las trazas (revisión 1.1.0, BAJO-13).
    "webhook_id",
)

# Público porque las tools de escritura lo necesitan para lo contrario: rechazar
# un valor tapado que el llamante reenvía. Guardarlo machacaría el secreto real
# con este texto (ver `sv_set_addon_options`).
REDACTED_MARKER = "***REDACTED***"
_STRUCT_REDACTED = REDACTED_MARKER


def _looks_sensitive(key: str) -> bool:
    """True si el nombre de la clave delata un secreto.

    El guion se normaliza a subrayado antes de comparar: `api-key`,
    `pre-shared-key` y `network-key` son la misma clave que sus variantes con
    subrayado, y sin normalizar se colaban sin redactar.
    """
    lowered = key.lower().replace("-", "_")
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)


# Alias público, sin cambiar el comportamiento: el resumen de la carga de las
# tools genéricas (`command_policy.resumir_carga`, spec 011, FR-010) decide qué
# valores enseña en la vista previa con el MISMO criterio que la redacción de
# las respuestas. Dos criterios distintos acabarían enseñando en la vista
# previa un secreto que la respuesta sí taparía.
es_clave_sensible = _looks_sensitive


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
