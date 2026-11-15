"""Clave de cifrado de los backups de Home Assistant (spec 031, FR-011).

POR QUÉ ESTA CLAVE (research R-3, D-031-1 aceptada)
---------------------------------------------------
Es `create_backup.password` de `backup/config/info`: la que la interfaz de HA
genera al configurar los backups automáticos y entrega como «kit de
emergencia». Cifrar con ella (los backups que crea Hermes y, en el tramo 4,
los safety backups) deja que el usuario restaure desde la interfaz o la CLI
de HA aunque Hermes esté roto, que es justo cuando hace falta. Una clave
generada en `/data` solo la conocería Hermes y viajaría dentro del propio
backup que cifra.

POR QUÉ SIN CACHÉ
-----------------
Cada uso la vuelve a leer y la descarta al terminar la llamada: así no queda
en memoria más de lo necesario, y si el usuario cambia la clave en HA, el
siguiente backup ya usa la nueva.

POR QUÉ SE TAPA EL `repr`
-------------------------
Un `logger.info(..., clave=resultado)` o una excepción que formatee el objeto
sacarían la clave al log. `__repr__` y `__str__` la ocultan; quien la
necesita lee `.clave` a propósito, y solo para mandarla a HA en el momento.

Distingue los cuatro casos de FR-011 (hay clave, HA sin clave, integración no
disponible, HA inalcanzable) y, ante cualquier respuesta inesperada, NO hay
clave (fail-closed).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, TypeVar

from hermes.ha import HAConnectionError

_T = TypeVar("_T")

# Plazo corto: la lectura va delante de crear un backup (y, en el tramo 4, de
# un safety backup que bloquea una escritura en /config); no puede retrasarla
# los 30 s por defecto de `ws_send`.
_PLAZO_S = 10

SIN_CLAVE = "no_key_configured"
SIN_INTEGRACION = "backup_integration_unavailable"
HA_INALCANZABLE = "ha_unreachable"


@dataclass(frozen=True)
class ClaveDeBackups:
    """Resultado de leer la clave. `clave` es None si `motivo` no lo es."""

    clave: str | None
    motivo: str | None

    def __repr__(self) -> str:
        oculta = "<oculta>" if self.clave is not None else "None"
        return f"ClaveDeBackups(clave={oculta}, motivo={self.motivo!r})"

    __str__ = __repr__


async def leer_clave_de_backups(ha_client: Any) -> ClaveDeBackups:
    """Lee la clave de cifrado de los backups de HA en este momento."""
    try:
        data = await ha_client.ws_send({"type": "backup/config/info"},
                                       timeout_seconds=_PLAZO_S)
    except HAConnectionError as exc:
        if getattr(exc, "code", None) == "unknown_command":
            return ClaveDeBackups(None, SIN_INTEGRACION)
        if getattr(exc, "code", None) is None:
            # Sin código WS: no hubo respuesta de HA (WebSocket caído,
            # plazo agotado).
            return ClaveDeBackups(None, HA_INALCANZABLE)
        return ClaveDeBackups(None, SIN_INTEGRACION)
    config = data.get("config") if isinstance(data, dict) else None
    if not isinstance(config, dict):
        return ClaveDeBackups(None, SIN_INTEGRACION)
    crear = config.get("create_backup")
    if not isinstance(crear, dict):
        return ClaveDeBackups(None, SIN_INTEGRACION)
    clave = crear.get("password")
    if clave is None or clave == "":
        return ClaveDeBackups(None, SIN_CLAVE)
    if not isinstance(clave, str):
        return ClaveDeBackups(None, SIN_INTEGRACION)
    return ClaveDeBackups(clave, None)


# ── Avisos sin clave según el motivo (T064, principio V) ───────────────────
# «Home Assistant no tiene clave» solo es verdad con `no_key_configured`. Si
# HA no respondió o la integración no está, no se sabe si la tiene, y decir
# que no la tiene manda al usuario a configurar algo que quizá ya existe.
_POR_QUE_SIN_CLAVE = {
    SIN_CLAVE: "Home Assistant has no backup encryption key configured",
    HA_INALCANZABLE: ("Home Assistant's backup encryption key could not be read "
                      "because Home Assistant did not answer, so it is not known "
                      "whether it has one"),
    SIN_INTEGRACION: ("Home Assistant's backup encryption key could not be read "
                      "because the backup integration is not available, so it is "
                      "not known whether it has one"),
}


def por_que_sin_clave(motivo: str | None) -> str:
    """Frase honesta de por qué no hay clave, sin punto final. Un motivo
    desconocido se dice como «no se pudo leer», nunca como «no hay clave»."""
    return _POR_QUE_SIN_CLAVE.get(motivo or "", _POR_QUE_SIN_CLAVE[SIN_INTEGRACION])


# ── Tapar la clave en todo lo que sale (T061, FR-011) ───────────────────────
# La clave solo viaja a HA o al Supervisor dentro de una carga. Lo único que
# puede devolverla es la RESPUESTA a esa carga: el texto de un error (HA o el
# Supervisor citando lo recibido) o, en teoría, los datos de vuelta. Por eso
# el único punto es `sin_secretos`, que envuelve la llamada que lleva la
# clave: la excepción y el resultado salen ya tapados, y todo lo que viene
# después (respuesta de la tool, error, log, fichero del token, estado y
# anotaciones de /data) solo puede ver el texto tapado. `ha_create_backup`,
# `ha_restore_backup`, `sv_restore_backup_full`/`_partial` y los dos caminos
# del safety backup (la tool y el automático de `fs_write`) mandan la clave
# SOLO a través de `sin_secretos`; `test_backup_key_tapado.py` lo vigila.
TAPADO = "***"
# Un trozo final más corto que esto no se tapa: tres caracteres no revelan
# una clave, y taparlos estropearía el final de cualquier texto que por
# casualidad acabe como empieza la clave.
_MIN_TROZO_FINAL = 4
# Marcas que se ponen detrás de un texto recortado: «...» la de
# `humanize_error` de voluptuous (el Supervisor la usa en sus errores de
# validación) y «…» la de Hermes.
_MARCAS_RECORTE = ("...", "…")


def _escapes(texto: str) -> set[str]:
    """El texto tal cual y escapado como JSON (ASCII o no) y como `repr`."""
    return {
        texto,
        json.dumps(texto)[1:-1],
        json.dumps(texto, ensure_ascii=False)[1:-1],
        repr(texto)[1:-1],
    }


def _formas(secreto: str) -> set[str]:
    """Cómo puede aparecer el secreto en un texto: tal cual o escapado una o
    dos veces (el cuerpo JSON del Supervisor que cita un `repr`, por
    ejemplo)."""
    formas: set[str] = set()
    for una in _escapes(secreto):
        formas |= _escapes(una)
    return formas


def _tapar_cortada(texto: str, forma: str) -> str:
    """Tapa un trozo inicial de `forma` que quedó cortado: al final del texto
    o justo delante de una marca de recorte. La marca puede no ser lo último:
    el Supervisor mete el mensaje recortado de voluptuous dentro de su cuerpo
    JSON, y detrás de «...» aún van las comillas y la llave de cierre."""
    for largo in range(len(forma) - 1, _MIN_TROZO_FINAL - 1, -1):
        trozo = forma[:largo]
        for marca in _MARCAS_RECORTE:
            texto = texto.replace(trozo + marca, TAPADO + marca)
        if texto.endswith(trozo):
            texto = texto[: len(texto) - largo] + TAPADO
    return texto


def _tapar_texto(texto: str, formas: list[str]) -> str:
    # La forma más larga primero: una corta no puede dejar a medias otra que
    # la contiene.
    for forma in formas:
        texto = texto.replace(forma, TAPADO)
    for forma in formas:
        texto = _tapar_cortada(texto, forma)
    return texto


def _tapar_valor(valor: Any, formas: list[str]) -> Any:
    if isinstance(valor, str):
        return _tapar_texto(valor, formas)
    if isinstance(valor, dict):
        return {_tapar_valor(k, formas): _tapar_valor(v, formas) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_tapar_valor(v, formas) for v in valor]
    if isinstance(valor, tuple):
        return tuple(_tapar_valor(v, formas) for v in valor)
    return valor


def tapar_clave(valor: Any, *secretos: str | None) -> Any:
    """Copia de `valor` (texto, dict, lista o tupla) sin ningún secreto.

    Lo tapa con o sin `password=` delante, escapado en JSON o en `repr`,
    entero o cortado al final del texto. Lo que no es texto se deja igual.
    """
    formas: set[str] = set()
    for s in secretos:
        if s:
            formas |= _formas(s)
    if not formas:
        return valor
    return _tapar_valor(valor, sorted(formas, key=len, reverse=True))


def _excepcion_tapada(exc: Exception, secretos: tuple[str, ...]) -> Exception:
    """La misma excepción (tipo, `status`, `code`, `sent`) con el texto tapado."""
    args = tuple(tapar_clave(a, *secretos) for a in exc.args)
    if isinstance(exc, HAConnectionError):
        return HAConnectionError(*args, status=exc.status, code=exc.code, sent=exc.sent)
    try:
        nueva = type(exc)(*args)
    except Exception:  # noqa: BLE001 — un tipo que no se deja copiar así
        nueva = RuntimeError(*args)
    if str(nueva) != tapar_clave(str(nueva), *secretos):
        # Su texto no sale solo de los args: no se puede fiar de la copia.
        nueva = RuntimeError(tapar_clave(str(exc), *secretos))
    return nueva


async def sin_secretos(llamada: Awaitable[_T], *secretos: str | None) -> _T:
    """Espera la llamada que lleva la clave y devuelve su resultado tapado.

    Si falla, lanza una COPIA tapada de la excepción, y la lanza fuera del
    `except`: así no arrastra la original como `__context__`, y ni una traza
    en el log puede enseñar el texto sin tapar.
    """
    activos = tuple(s for s in secretos if s)
    if not activos:
        return await llamada
    try:
        resultado = await llamada
    except Exception as exc:  # noqa: BLE001 — se relanza tapada
        tapada = _excepcion_tapada(exc, activos)
    else:
        return tapar_clave(resultado, *activos)
    raise tapada


# ── Safety backups (spec 031, tramo 4; FR-012, FR-013) ──────────────────────
# Valores de la opción `safety_backup_encryption` y el error de `required`.
CIFRADO_AUTO = "auto"
CIFRADO_OBLIGATORIO = "required"
CIFRADO_NO = "off"
CLAVE_NO_DISPONIBLE = "encryption_key_unavailable"


async def clave_para_safety_backup(ha_client: Any, modo: str) -> ClaveDeBackups | None:
    """Clave con la que cifrar un safety backup según `safety_backup_encryption`.

    Devuelve None con `off` (no se lee nada: exactamente la 1.1.2). Con
    `auto` o `required`, el resultado de `leer_clave_de_backups`; quien llama
    decide qué hacer sin clave. Un valor desconocido se trata como `required`
    (fail-closed): `config.validate()` ya lo impide al arrancar, pero quien
    registre las tools a mano no puede acabar sin cifrar por una errata.

    Cualquier excepción inesperada al leer (no `HAConnectionError`) cuenta como
    «integración no disponible»: un safety backup no puede caerse con una
    traza por esto, y el texto de la excepción no se guarda en ningún sitio.
    """
    if modo == CIFRADO_NO:
        return None
    try:
        return await leer_clave_de_backups(ha_client)
    except Exception:  # noqa: BLE001 — fail-closed: sin clave
        return ClaveDeBackups(None, SIN_INTEGRACION)


def exige_cifrado(modo: str) -> bool:
    """¿El modo exige que el safety backup que cubre una escritura vaya
    cifrado? `required` y, fail-closed, cualquier valor desconocido."""
    return modo not in (CIFRADO_AUTO, CIFRADO_NO)


def sin_clave_bloquea(modo: str) -> bool:
    """¿Sin clave no hay safety backup? Solo `auto` deja crearlo sin cifrar."""
    return modo != CIFRADO_AUTO
