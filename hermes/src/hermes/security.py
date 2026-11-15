"""Hermes — Seguridad: canonicalización, confirmation tokens y redacción.

Contiene tres piezas independientes:

- Canonicalización determinista de un par (tool, args) en un `action_hash`
  (HMAC-SHA256 con una clave del proceso), para que un confirmation token
  solo valga para la acción exacta que se previsualizó.
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
import hmac
import json
import math
import os
import re
import secrets
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


# ── Clave del action_hash (spec 019, decisión del programa) ───
# El action_hash es lo único que se escribe en disco de los argumentos de una
# acción, y algunos argumentos son secretos: la contraseña de un montaje CIFS,
# el valor de `fs_set_secret`, la de un backup al restaurarlo. Con un SHA-256
# sin clave, quien leyera el directorio de tokens (está en /data, que entra
# en los backups del add-on) podía probar contraseñas débiles sin conexión
# hasta dar con el hash. Con HMAC-SHA256 y una clave aleatoria que solo vive
# en la memoria de este proceso, el hash no sirve para eso sin la clave.
#
# La clave nunca se escribe en disco ni en el log, y cambia en cada arranque.
# Eso CAMBIA el comportamiento respecto a la 1.1.2, y es a propósito: allí el
# hash era determinista y el arranque solo barría los tokens caducados, así
# que un token vigente (menos de 60 s) seguía valiendo después de reiniciar
# Hermes. Ahora no: con la clave nueva no casa y se rechaza («lost across
# restart», ver `_ARRANQUE`), sin gastarlo. Falla cerrado: lo peor que pasa
# es que hay que pedir otra vista previa. Nada más depende del valor del
# hash entre arranques: la idempotencia y `cached_result` van por el fichero
# del token, y los documentos guardados (`stored_args`) también se comprueban
# con el hash del proceso que los guardó.
_CLAVE_HASH: bytes = secrets.token_bytes(32)

# Momento del arranque de este proceso. Un token creado antes no puede casar
# (la clave del hash es otra): se responde que se perdió con el reinicio, que
# es lo que pasó, y no que «no casa con la acción».
_ARRANQUE: float = time.time()


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

    Sin clave: sirve para comparar dos valores en el mismo momento (una vista
    de un dashboard antes y después). Lo que se escribe en disco junto a un
    token usa `compute_action_hash`, con clave.
    """
    return hashlib.sha256(_serializar_canonico(value)).hexdigest()


def _serializar_canonico(value: Any) -> bytes:
    """Bytes canónicos de `value` (las reglas de `canonicalize_for_hash`)."""
    normalized = _normalize_value(value)
    serialized = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return serialized.encode("utf-8")


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
    """Calcula el action_hash (HMAC-SHA256 con la clave del proceso) para un
    par (tool_name, args), sobre la misma forma canónica de siempre."""
    payload = {"tool": tool_name, "args": args}
    return hmac.new(
        _CLAVE_HASH, _serializar_canonico(payload), hashlib.sha256
    ).hexdigest()


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


# Mensaje de `resolve_confirmation_token` cuando el objetivo cambió desde la
# vista previa (spec 018, FR-003). Público para que la tool lo distinga de un
# token que no casa y responda con su propio código (`dashboard_changed`): no es
# un error del cliente, solo tiene que pedir otra vista previa.
ESTADO_CAMBIADO = (
    "The target changed since the preview. Nothing was done; request a new "
    "preview."
)


def _huella_de_estado(estado: Any) -> str:
    """Huella del estado leído en la vista previa (spec 018, research R-2).

    La misma canonicalización que el action_hash: el orden de las claves no
    cuenta y un 1.0 es un 1. Solo se escribe la huella: el estado (el
    dashboard entero) puede llevar datos de la casa y /data entra en los
    backups (principio II).
    """
    return compute_action_hash("estado", {"estado": estado})


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
    estado: Any = None,
) -> dict[str, Any]:
    """Crea un token de confirmación vinculado a una acción.

    `estado` (opcional, spec 018) ata además el token al estado del objetivo
    leído en la vista previa: se guarda su huella (`state_hash`) y
    `resolve_confirmation_token` exige el mismo estado. Es para las vistas
    previas que prometen conservar algo que puede cambiar en los 60 s del
    token (el resto de un dashboard al guardar una sola vista). No entra en
    el action_hash ni en `confirm_with`: el cliente no lo manda ni lo conoce.

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
    if estado is not None:
        token_data["state_hash"] = _huella_de_estado(estado)

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
    estado: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Valida un token y devuelve los argumentos con los que se ejecuta.

    `estado` (opcional, spec 018): el estado actual del objetivo. Si el token
    se emitió con estado, o llega uno ahora, las dos huellas tienen que
    coincidir; si no, `ESTADO_CAMBIADO` sin tocar el token (el cliente puede
    pedir otra vista previa, y un token emitido sin estado no vale para una
    tool que lo exige: fail-closed). Sin `estado` en ninguno de los dos
    lados, igual que en la 1.1.2.

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
    # Se comparan bytes: `compare_digest` con dos `str` lanza `TypeError` si
    # alguno no es ASCII, y el `action_hash` del fichero puede venir dañado o
    # manipulado (está en /data). Con bytes, un hash así simplemente no casa
    # y la respuesta es el error limpio de siempre (fail-closed, T034).
    if not hmac.compare_digest(str(expected_hash).encode("utf-8"),
                               actual_hash.encode("ascii")):
        # Un token de un arranque anterior se hizo con otra clave y no puede
        # casar con nada: decirlo así y no como si fuera otra acción.
        creado = token_data.get("created_at")
        if isinstance(creado, (int, float)) and creado < _ARRANQUE:
            return False, (
                "confirmation_token expired or lost across restart. "
                "Request a new preview."
            ), {}
        return False, "confirmation_token does not match this action.", {}

    # Estado del objetivo (spec 018): después del action_hash, para que un
    # token de otra acción siga dando «does not match», y antes de
    # `executing`, sin ningún `await` entre medias, para no gastar el token.
    huella_token = token_data.get("state_hash")
    if huella_token is not None or estado is not None:
        if estado is None or huella_token != _huella_de_estado(estado):
            return False, ESTADO_CAMBIADO, {}

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
    # Claves de seguridad S0 y S2 de Z-Wave (spec 025, D-2): la integración
    # las escribe en las opciones de la app Z-Wave JS con estos nombres
    # (`zwave_js/const.py`, `CONF_ADDON_S0_LEGACY_KEY`…) y ninguno contiene
    # otro marcador; `sv_get_addon_options` las devolvía en claro. Las
    # variantes de largo alcance (`lr_s2_…`) las contienen como subcadena.
    "s0_legacy_key", "s2_access_control_key", "s2_authenticated_key",
    "s2_unauthenticated_key",
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


def tapar_entero(value: Any) -> bool:
    """True si, bajo una clave sensible, el valor se sustituye ENTERO.

    Spec 025, D-2 (hallazgo H-1): antes solo se tapaban textos, y un objeto
    bajo una clave sensible se recorría. La clave de red de ZHA viaja como
    `{"network_key": {"key": "…", "tx_counter": …}}`: `network_key` es
    sensible, pero `key` no, y la clave salía en claro. Ahora la decisión es
    de la clave, no del tipo: texto, número, objeto o lista, se tapa entero.

    Se conservan `None`, los booleanos y lo vacío (cadena, objeto o lista):
    dicen si algo está configurado o activado, que es diagnóstico útil, y no
    pueden llevar un secreto. Público para que las redacciones locales de las
    tools (`_limpio`, `_redactar` de las genéricas) usen el MISMO criterio.
    """
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (str, dict, list, tuple)) and not value:
        return False
    return True


def redact_structure(value: Any, _key: str = "") -> Any:
    """Devuelve una copia del dato con los valores sensibles sustituidos.

    Pensado para lo que las tools devuelven al cliente MCP, no para logs
    (de eso se encarga `logging_setup`). Motivo: tools como `sv_get_addon` o
    `sv_get_addon_options` devuelven la respuesta del Supervisor, y ahí viaja
    el bloque `options` del add-on — incluida la `auth_password` del propio
    Hermes, que es el único secreto que protege la instalación. Sin esta
    redacción, un cliente con un token válido la leería en claro y se quedaría
    con un secreto de larga duración que sobrevive a la revocación del token.

    Bajo una clave sensible se sustituye el valor ENTERO, sea texto, número,
    objeto o lista (spec 025, D-2; ver `tapar_entero`). Hasta la 025 solo se
    tapaban textos, y un objeto como `{"network_key": {"key": "…"}}` dejaba
    la clave en claro. El precio: un número legítimo bajo una clave sensible
    (`token_expiry_seconds`) también sale tapado; preferimos ese ruido a un
    PIN o una clave numérica en claro.

    Las cadenas vacías, `None`, los booleanos y los objetos o listas vacíos se
    conservan: saber que una opción está SIN configurar es información de
    diagnóstico útil (p. ej. "el add-on no arranca porque le falta la
    contraseña") y no revela ningún secreto.
    """
    if _key and _looks_sensitive(str(_key)) and tapar_entero(value):
        return _STRUCT_REDACTED
    if isinstance(value, dict):
        return {k: redact_structure(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_structure(item, _key) for item in value]
    return value


# ── Recorte sin secreto a medias (spec 012, T035) ─────────────────────────
#
# `HAClient.rest_get_text_tail` corta las líneas de log de más de
# `max_line_bytes` para no acumular en memoria una línea de un giga, y la
# redacción viene DESPUÉS (no se puede redactar la línea entera sin tenerla
# entera). Si el corte cae dentro de un secreto, lo que queda es un secreto
# abierto que `redact_secrets` no reconoce porque le falta el final: la
# comilla de cierre en JSON (`"password": "hunter2 …[line truncated]`) o la
# `@` de una URL con contraseña (`mqtt://user:hunter2…`). Esta función quita
# del FINAL del texto ese trozo de valor abierto; las formas `clave: valor` y
# `clave valor` no lo necesitan, porque su valor se redacta aunque esté
# cortado.

# Caracteres de un JWT (base64url y puntos).
_CARACTERES_JWT = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-."
)


def _inicio_racha_final(texto: str, dentro: Any) -> int:
    """Posición donde empieza la racha final de caracteres que cumplen `dentro`.

    Recorrido hacia atrás: lineal. Una expresión anclada al final con
    `search` probaría cada posición de cada racha hasta su final
    (cuadrático en una racha larga).
    """
    i = len(texto)
    while i > 0 and dentro(texto[i - 1]):
        i -= 1
    return i


def quitar_secreto_abierto(texto: str) -> str:
    """Quita del final de un texto recortado un secreto que quedó abierto.

    Para usar justo después de cortar una línea por su longitud y antes de
    `redact_secrets`. Solo mira el final: todo lo anterior al corte está
    completo y lo redacta `redact_secrets` como siempre. Lineal en la
    longitud del texto (se llama con textos acotados, de unos KB).
    """
    if not texto:
        return texto

    # 1. Valor JSON sin comilla de cierre: con la comilla añadida, la última
    # coincidencia de `_JSON_SECRET_RE` acabaría justo al final del texto.
    # Se corta al principio del valor; la clave se conserva.
    ultima = None
    for m in _JSON_SECRET_RE.finditer(texto + '"'):
        ultima = m
    if ultima is not None and ultima.end() == len(texto) + 1:
        texto = texto[:ultima.start(2)]

    # 2. Contraseña de una URL sin la `@` final. `scheme://user:clave` no
    # lleva espacios ni `@`, así que, si la contraseña llega al final, todo
    # está en la última racha sin espacio ni `@`: basta buscar ahí (lineal).
    # Se corta tras `scheme://user:` de la primera coincidencia de la racha.
    if "://" in texto:
        inicio = _inicio_racha_final(texto, lambda c: c != "@" and not c.isspace())
        m = _BASIC_AUTH_PREFIJO_RE.search(texto, inicio)
        if m is not None:
            texto = texto[:m.end()]

    # 3. JWT cortado: sin la firma no sirve, pero la cabecera y parte de la
    # carga (o un trozo de firma) no se dejan a la vista.
    jwt = texto.find("eyJ", _inicio_racha_final(texto, _CARACTERES_JWT.__contains__))
    if jwt >= 0:
        texto = texto[:jwt]

    return texto
