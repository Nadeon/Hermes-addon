"""Hermes — mantenimiento de las estadísticas de largo plazo (spec 020, CAP-050).

Tools de la familia `recorder` que ESCRIBEN en la base de estadísticas, todas
en dos pasos (vista previa con token y confirmación):

- `ha_clear_statistics`: borra estadísticas enteras (filas y metadatos) o las
  filas que se solapan con un rango (`recorder/clear_statistics`).
- `ha_change_statistics_unit`: convierte todo el histórico a otra unidad de
  la misma clase (`recorder/change_statistics_unit`).
- `ha_update_statistics_metadata`: cambia la unidad y la clase guardadas SIN
  convertir los valores (`recorder/update_statistics_metadata`).

- `ha_adjust_statistics_sum`: suma una cantidad a la suma de cada fila desde
  un instante (`recorder/adjust_sum_statistics`). NO es idempotente.
- `ha_import_statistics`: importa filas horarias y crea o actualiza los
  metadatos (`recorder/import_statistics`).

POR QUÉ DOS PASOS Y UNA VISTA PREVIA QUE LEE ANTES (research R-1, R-2)
----------------------------------------------------------------------
Reescriben histórico y solo se deshacen restaurando un backup. Además, Home
Assistant responde «ok» en casos en que no hace nada: borrar o editar un id
que no existe, cambiar la unidad de una estadística externa o con otra unidad
guardada (el trabajo de la cola solo avisa en el log de HA). Por eso cada
tool lee antes los metadatos con `recorder/get_statistics_metadata` y
rechaza, sin emitir token, lo que HA aceptaría en silencio sin hacerlo.

Esos metadatos son además el `estado` del token (spec 018): la confirmación
los vuelve a leer y, si la estadística cambió de unidad, desapareció o
apareció entre medias, `resolve_confirmation_token` responde
`ESTADO_CAMBIADO` y no se envía nada. El estado es siempre una lista (nunca
`None`, con el que el token no ataría nada); si no se puede leer, la tool
falla cerrada sin token o sin ejecutar.

El token ata los argumentos NORMALIZADOS tal como se envían a HA: ids
ordenados y sin repetir, fechas en UTC. Así, la misma hora escrita en otra
zona es la misma acción.

`queued: true` (decisión D-1 del supervisor): `change_statistics_unit`,
`adjust_sum_statistics` e `import_statistics` solo encolan el trabajo en el
recorder y HA contesta antes de hacerlo. Hermes no
espera a que la cola se vacíe; dice que se aplica en segundo plano y cómo
comprobarlo. Borrar y editar metadatos sí esperan en HA (10 s); si vence,
`ha_timeout` avisa de que el trabajo puede seguir en la cola.

Log: nombre de la tool, paso, resultado y recuentos. Nunca ids, unidades,
fechas ni valores (FR-018): dicen qué hay en la casa.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    ESTADO_CAMBIADO,
    complete_confirmation_token,
    create_confirmation_token,
    resolve_confirmation_token,
)
from hermes.tools._common import requires_ready
from hermes.tools.recorder_status import _STATISTIC_ID_RE, _con_forma, _error_ha
from hermes.tools.system_status import _invalido, _limpio

logger = structlog.get_logger(__name__)

_IDS_MAX = 100
_UNIDAD_MAX = 64
_NOMBRE_MAX = 255
# Tope de filas por importación: 5000 horas son casi siete meses. Basta para
# rellenar un hueco o migrar un contador, y el documento (unos 400 KB) sigue
# cabiendo en el token y en una respuesta. Para más, varias importaciones.
_FILAS_MAX = 5000
# Rango máximo en el que la vista previa cuenta las filas que ya existen: 31
# días son 744 filas horarias, una lectura acotada (research R-4).
_RANGO_RECUENTO = timedelta(days=31)

_UNDO = (
    "Cannot be undone from Hermes: only restoring a backup that includes the "
    "Home Assistant database brings the old data back."
)
_ID_DETALLE = "must look like 'sensor.energy' or 'source:statistic' (lowercase letters, digits and '_')"
# T055 (b): `recorder/get_statistics_metadata` lista también lo que una
# integración «añadirá en el próximo periodo» (todo sensor con `state_class`
# aunque aún no se haya compilado, `list_statistic_ids` de HA), con los mismos
# campos que lo guardado en la base: Hermes no puede distinguirlo. Los
# trabajos de cambiar la unidad, editar los metadatos y ajustar miran la
# base, así que con una de esas HA responde «ok» y no hace nada. No se
# afirma lo que no se sabe: va en `not_validated`.
_NO_VALIDADO = ["statistic_in_database"]
_NO_VALIDADO_DETALLE = (
    "Not checked: whether this statistic is already stored in the database. Home "
    "Assistant also lists statistics that an integration will only add at its next "
    "compilation (a new sensor with a state_class, or one whose statistics were just "
    "deleted); for those it answers ok and changes nothing. Check the result as "
    "described in check_with.")
_TIMEOUT = (
    "Home Assistant did not confirm within its 10 s limit. The job may still be "
    "in the recorder queue and run later: check the result with "
    "ha_get_statistics_metadata or ha_statistics_during_period before retrying."
)


# ── Validación ───────────────────────────────────────────────────────────────

def _fecha_utc(valor: Any) -> datetime | None:
    """ISO 8601 con zona → `datetime` en UTC; `None` si no vale.

    Sin zona no se adivina: HA la tomaría como hora local del servidor, y la
    vista previa diría otro periodo del que se borra.
    """
    if not isinstance(valor, str) or not 0 < len(valor) <= 64:
        return None
    try:
        fecha = datetime.fromisoformat(valor)
    except ValueError:
        return None
    if fecha.tzinfo is None or fecha.utcoffset() is None:
        return None
    return fecha.astimezone(timezone.utc)


def _unidad_valida(valor: Any) -> bool:
    return valor is None or (isinstance(valor, str) and 0 < len(valor) <= _UNIDAD_MAX)


# ── Ayudante común (plan.md, «Patrón común») ─────────────────────────────────

async def _leer_metadatos(ha_client: HAClient, ids: list[str]) -> list[dict[str, Any]]:
    """Metadatos de `ids` ordenados por id: el estado atado al token.

    Lanza `HAConnectionError` si HA falla, y también si la respuesta no es una
    lista: sin metadatos fiables no hay vista previa honesta ni estado que
    atar (fail-closed).
    """
    bruto = await ha_client.ws_send(
        {"type": "recorder/get_statistics_metadata", "statistic_ids": ids})
    if not isinstance(bruto, list):
        raise HAConnectionError(
            "recorder/get_statistics_metadata returned an unexpected shape",
            code="unexpected_response")
    filas = [dict(m) for m in bruto
             if isinstance(m, Mapping) and m.get("statistic_id") in ids]
    return sorted(filas, key=lambda m: str(m.get("statistic_id")))


def _no_encontradas(tool: str, ids: list[str], metas: list[dict[str, Any]]) -> dict[str, Any] | None:
    conocidas = {m.get("statistic_id") for m in metas}
    faltan = [s for s in ids if s not in conocidas]
    if not faltan:
        return None
    logger.info(f"{tool}_failed", error="statistics_not_found", missing=len(faltan))
    return {"error": "statistics_not_found", "missing": faltan,
            "detail": ("Home Assistant has no long-term statistics with these ids "
                       "(list them with ha_list_statistic_ids). Nothing was done.")}


def _error_de_ha(tool: str, exc: HAConnectionError) -> dict[str, Any]:
    """El traductor de la 029 más `table_ha_core` en `ha_command_failed`."""
    out = _error_ha(tool, exc)
    if out.get("error") == "ha_command_failed":
        from hermes.command_table import TABLE_HA_CORE
        out["table_ha_core"] = TABLE_HA_CORE
    return out


async def _dos_pasos(
    ha_client: HAClient,
    *,
    tool: str,
    args: dict[str, Any],
    ids: list[str],
    confirmation_token: str | None,
    comprobar: Callable[[list[dict[str, Any]]], dict[str, Any] | None],
    vista: Callable[[list[dict[str, Any]]], Any],
    comando: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]],
    resultado: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]],
    omitibles: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Lectura de metadatos → comprobaciones → vista previa o ejecución.

    `args` son los argumentos normalizados que ata el token (los mismos que
    acaban en `comando`). `comprobar` devuelve un error (sin token) para lo
    que HA aceptaría sin hacer nada. `resultado` es lo que se devuelve si HA
    responde bien.

    `vista` puede ser asíncrona cuando la vista previa lee algo más (la suma
    de una hora, las filas que se sobrescriben); si esa lectura falla, no hay
    token: una vista previa a medias no dice lo que se va a hacer. `comando`
    y `resultado` pueden ser funciones de los argumentos RESUELTOS por el
    token: con un omitible (`stats`), lo que se envía es lo guardado en la
    vista previa, no lo que llegó (nada) en la confirmación.
    """
    try:
        metas = await _leer_metadatos(ha_client, ids)
    except HAConnectionError as exc:
        # Fail-closed: sin estado no hay token, y un token pendiente sigue
        # pendiente (se puede reintentar dentro de su TTL).
        return _error_de_ha(tool, exc)

    if not confirmation_token:
        error = comprobar(metas)
        if error is not None:
            return error
        try:
            preview = vista(metas)
            if inspect.isawaitable(preview):
                preview = await preview
        except HAConnectionError as exc:
            return _error_de_ha(tool, exc)
        preview = _limpio(preview)
        logger.info(f"{tool}_preview", statistics=len(ids))
        return await create_confirmation_token(
            tool, args, preview, omitibles=omitibles, estado=metas)

    valido, motivo, resueltos = await resolve_confirmation_token(
        confirmation_token, tool, args, omitibles=omitibles, estado=metas)
    if not valido:
        if motivo == ESTADO_CAMBIADO:
            logger.info(f"{tool}_failed", error="statistics_changed")
            return {"error": "statistics_changed", "detail": ESTADO_CAMBIADO}
        logger.info(f"{tool}_failed", error="token_invalid")
        return {"error": motivo}
    # Mismo estado que en la vista previa, así que pasa; se comprueba igual
    # por si un día el estado atado dejara de cubrir algo (fail-closed).
    error = comprobar(metas)
    if error is not None:
        await complete_confirmation_token(
            confirmation_token, success=False, error=str(error.get("error")))
        return error

    if callable(comando):
        comando = comando(resueltos)
    if callable(resultado):
        resultado = resultado(resueltos)
    try:
        await ha_client.ws_send(comando)
    except HAConnectionError as exc:
        await complete_confirmation_token(
            confirmation_token, success=False, error=exc.code or "connection")
        if exc.code == "timeout":
            logger.info(f"{tool}_failed", error="ha_timeout")
            return {"error": "ha_timeout", "detail": _TIMEOUT, "ha_code": exc.code}
        return _error_de_ha(tool, exc)
    await complete_confirmation_token(confirmation_token, success=True, result=resultado)
    logger.info(f"{tool}_ok", statistics=len(ids))
    return resultado


def _resumen(meta: Mapping[str, Any]) -> dict[str, Any]:
    """Lo que la vista previa enseña de cada estadística."""
    return {k: meta.get(k) for k in (
        "statistic_id", "source", "name", "statistics_unit_of_measurement",
        "unit_class", "has_mean", "mean_type", "has_sum")}


def _iso(fecha: datetime) -> str:
    return fecha.isoformat()


def _numero_finito(valor: Any) -> bool:
    """int o float finito; `bool` no cuenta (en Python es un int).

    Un entero enorme (`10**400`, JSON válido) no cabe en un float y
    `math.isfinite` lanza `OverflowError`: no es un número que HA pueda
    guardar, así que cuenta como no finito y la tool responde
    `invalid_argument` en vez de reventar (T054).
    """
    if not isinstance(valor, (int, float)) or isinstance(valor, bool):
        return False
    try:
        return math.isfinite(valor)
    except OverflowError:
        return False


def _inicio_ms(fila: Mapping[str, Any]) -> float | None:
    """`start` de una fila de `statistics_during_period` en milisegundos.

    HA da milisegundos desde la época; se acepta también un ISO por si una
    versión lo devuelve así.
    """
    inicio = fila.get("start")
    if _numero_finito(inicio):
        return float(inicio)
    fecha = _fecha_utc(inicio)
    return fecha.timestamp() * 1000 if fecha is not None else None


async def _leer_filas(ha_client: HAClient, statistic_id: str, desde: datetime,
                      hasta: datetime, types: list[str] | None = None) -> list[dict[str, Any]]:
    """Filas horarias de `statistic_id` en [desde, hasta) según HA.

    Lanza `HAConnectionError` si HA falla o la respuesta no tiene forma.
    """
    mensaje: dict[str, Any] = {
        "type": "recorder/statistics_during_period", "statistic_ids": [statistic_id],
        "start_time": _iso(desde), "end_time": _iso(hasta), "period": "hour"}
    if types is not None:
        mensaje["types"] = types
    bruto = await ha_client.ws_send(mensaje)
    filas = (bruto.get(statistic_id) or []) if isinstance(bruto, Mapping) else None
    if not isinstance(filas, list):
        raise HAConnectionError(
            "recorder/statistics_during_period returned an unexpected shape",
            code="unexpected_response")
    return [f for f in filas if isinstance(f, Mapping)]


# ── Validación de la importación ─────────────────────────────────────────────

_META_CLAVES = ("statistic_id", "source", "name", "unit_of_measurement",
                "unit_class", "mean_type", "has_sum")
_FILA_NUMEROS = ("mean", "min", "max", "state", "sum")


def _validar_metadata(metadata: Any) -> tuple[dict[str, Any] | None, str, str]:
    """`metadata` normalizado, o (None, campo, detalle) si no vale.

    Se exigen las siete claves: sin `mean_type` ni `unit_class` HA las deduce
    y avisa de que esa forma deja de funcionar (research R-1); `has_mean` no
    se admite porque `mean_type` manda y las dos podrían contradecirse.
    """
    if not isinstance(metadata, Mapping):
        return None, "metadata", "metadata must be an object."
    sobran = sorted(set(map(str, metadata)) - set(_META_CLAVES))
    if sobran:
        return None, "metadata", (f"Unknown metadata keys: {', '.join(sobran)}. Allowed: "
                                  f"{', '.join(_META_CLAVES)} (has_mean is replaced by "
                                  "mean_type).")
    faltan = [k for k in _META_CLAVES if k not in metadata]
    if faltan:
        return None, "metadata", f"Missing metadata keys: {', '.join(faltan)}."
    sid, fuente = metadata["statistic_id"], metadata["source"]
    if not _con_forma(sid, _STATISTIC_ID_RE):
        return None, "metadata.statistic_id", "statistic_id " + _ID_DETALLE + "."
    # La misma regla que HA (`async_import_statistics` y
    # `async_add_external_statistics`): un id de entidad solo se importa con
    # la fuente `recorder`, y uno externo con la fuente de su prefijo. Si no,
    # HA lo rechaza al validar y no importa nada.
    esperada = "recorder" if "." in sid else sid.split(":", 1)[0]
    if fuente != esperada:
        return None, "metadata.source", (f"source must be '{esperada}' for this statistic_id "
                                         "('recorder' for an entity id, the prefix for "
                                         "'source:statistic').")
    nombre = metadata["name"]
    if not (nombre is None or (isinstance(nombre, str) and len(nombre) <= _NOMBRE_MAX)):
        return None, "metadata.name", f"name must be a text (up to {_NOMBRE_MAX}) or null."
    for campo in ("unit_of_measurement", "unit_class"):
        if not _unidad_valida(metadata[campo]):
            return None, f"metadata.{campo}", (f"{campo} must be a text (up to "
                                               f"{_UNIDAD_MAX} characters) or null.")
    tipo = metadata["mean_type"]
    if isinstance(tipo, bool) or tipo not in (0, 1, 2):
        return None, "metadata.mean_type", ("mean_type must be 0 (no mean), 1 (arithmetic) "
                                            "or 2 (circular).")
    if not isinstance(metadata["has_sum"], bool):
        return None, "metadata.has_sum", "has_sum must be true or false."
    return {k: metadata[k] for k in _META_CLAVES}, "", ""


def _validar_stats(stats: Any) -> tuple[list[dict[str, Any]] | None, str]:
    """Filas normalizadas (UTC, ordenadas), o (None, detalle) si no valen.

    `start` tiene que ser una hora en punto EN UTC: HA solo comprueba los
    minutos en la zona que llega, y con una zona de media hora (+05:30)
    guardaría una fila a y media.
    """
    if not isinstance(stats, list) or not 1 <= len(stats) <= _FILAS_MAX:
        return None, (f"stats must be a list of 1 to {_FILAS_MAX} rows; for more, import "
                      "in several calls.")
    filas: dict[datetime, dict[str, Any]] = {}
    for n, fila in enumerate(stats):
        if not isinstance(fila, Mapping):
            return None, f"stats[{n}] must be an object."
        sobran = sorted(set(map(str, fila)) - {"start", "last_reset", *_FILA_NUMEROS})
        if sobran:
            return None, f"stats[{n}] has unknown keys: {', '.join(sobran)}."
        inicio = _fecha_utc(fila.get("start"))
        if inicio is None:
            return None, f"stats[{n}].start must be ISO 8601 with a time zone."
        if inicio.minute or inicio.second or inicio.microsecond:
            return None, f"stats[{n}].start must be at the top of an hour (in UTC)."
        if inicio in filas:
            return None, f"stats[{n}].start is repeated: one row per hour."
        normal: dict[str, Any] = {"start": _iso(inicio)}
        if fila.get("last_reset") is not None:
            reinicio = _fecha_utc(fila["last_reset"])
            if reinicio is None:
                return None, (f"stats[{n}].last_reset must be ISO 8601 with a time zone "
                              "or null.")
            normal["last_reset"] = _iso(reinicio)
        elif "last_reset" in fila:
            normal["last_reset"] = None
        for campo in _FILA_NUMEROS:
            if campo in fila:
                if not _numero_finito(fila[campo]):
                    return None, f"stats[{n}].{campo} must be a finite number."
                normal[campo] = fila[campo]
        filas[inicio] = normal
    return [filas[k] for k in sorted(filas)], ""


# ── Registro ─────────────────────────────────────────────────────────────────

def register(mcp: Any, ha_client: HAClient, *, response_max_bytes: int) -> None:
    """Registra las tools de mantenimiento de estadísticas (familia `recorder`)."""
    del response_max_bytes  # sin listas propias: el tope central basta
    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_clear_statistics(
        statistic_ids: list[str],
        start_time: str | None = None,
        end_time: str | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Delete long-term statistics: whole statistics (all their rows and their metadata) or only the rows that overlap a time range.

        Cannot be undone except by restoring a backup. Two steps: without
        confirmation_token it returns a preview (each statistic with its
        metadata, the scope and, with a range, the effective range per table)
        and changes nothing; repeat the same call with confirmation_token to
        delete. Without a range all rows and the metadata are deleted; the
        statistic of an entity that is still recorded stays listed and the
        recorder compiles it again from now on (deleted rows do not come
        back). With a
        range, Home Assistant deletes every row whose period OVERLAPS it: the
        hourly row that starts up to 1 hour before start_time and the
        5-minute row that starts up to 5 minutes before it are deleted too.

        Args:
            statistic_ids: 1-100 statistic ids, e.g. ["sensor.energy",
                "kitchen_sink:gas"]. Duplicates are removed.
            start_time: ISO 8601 with time zone, e.g.
                "2026-01-01T00:00:00+00:00". Together with end_time or not at all.
            end_time: ISO 8601 with time zone, after start_time.
            confirmation_token: Token from the preview call.

        Returns:
            Preview: {confirmation_token, expires_in_seconds, preview}.
            Confirmed: {cleared: true, statistic_ids_count, scope}. Errors:
            invalid_argument, statistics_not_found (with `missing`),
            recorder_not_loaded, ha_timeout, ha_command_failed.
        """
        tool = "ha_clear_statistics"
        if (not isinstance(statistic_ids, list)
                or not 1 <= len(statistic_ids) <= _IDS_MAX
                or not all(_con_forma(x, _STATISTIC_ID_RE) for x in statistic_ids)):
            return _invalido(tool, "statistic_ids",
                             f"statistic_ids must be a list of 1 to {_IDS_MAX} ids; each "
                             + _ID_DETALLE + ".")
        if (start_time is None) != (end_time is None):
            return _invalido(tool, "start_time",
                             "start_time and end_time go together: pass both or neither.")
        inicio = fin = None
        if start_time is not None:
            inicio, fin = _fecha_utc(start_time), _fecha_utc(end_time)
            if inicio is None or fin is None:
                return _invalido(tool, "start_time" if inicio is None else "end_time",
                                 "Dates must be ISO 8601 with a time zone, e.g. "
                                 "'2026-01-01T00:00:00+00:00'.")
            if inicio >= fin:
                return _invalido(tool, "end_time", "start_time must be before end_time.")

        ids = sorted(set(statistic_ids))
        args = {"statistic_ids": ids,
                "start_time": _iso(inicio) if inicio else None,
                "end_time": _iso(fin) if fin else None}
        comando: dict[str, Any] = {"type": "recorder/clear_statistics", "statistic_ids": ids}
        if inicio is not None and fin is not None:
            comando.update(start_time=args["start_time"], end_time=args["end_time"])
        alcance = "range" if inicio is not None else "entire"

        def vista(metas: list[dict[str, Any]]) -> dict[str, Any]:
            preview: dict[str, Any] = {
                "action": "clear_statistics",
                "statistics": [_resumen(m) for m in metas],
                "scope": alcance,
                "removes_metadata": alcance == "entire",
            }
            if inicio is not None and fin is not None:
                # El periodo efectivo es el de la consulta de HA
                # (`clear_statistics_range`): borra toda fila con
                # `start > start_time - duración` y `start < end_time`, es
                # decir, las que se solapan con el rango pedido.
                preview["requested_range"] = {"start_time": args["start_time"],
                                              "end_time": args["end_time"]}
                preview["effective_range"] = {
                    "hourly": {"after": _iso(inicio - timedelta(hours=1)),
                               "before": args["end_time"]},
                    "five_minute": {"after": _iso(inicio - timedelta(minutes=5)),
                                    "before": args["end_time"]},
                }
                preview["effect"] = (
                    "Deletes every row of these statistics that starts after "
                    "`after` and before `before` (both exclusive) in each table. "
                    "The metadata stays.")
            else:
                # T055 (a): HA lista también lo que las integraciones
                # compilarán (`list_statistic_ids`): la estadística de un
                # sensor que se sigue grabando no desaparece y se recompila
                # desde la próxima compilación. Lo borrado no vuelve.
                preview["effect"] = (
                    "Deletes these statistics entirely: every row and their "
                    "metadata. The deleted rows do not come back, but a statistic "
                    "of an entity that is still recorded does NOT disappear: it "
                    "stays in the statistics lists and the recorder compiles it "
                    "again from now on.")
            preview["irreversible"] = True
            preview["undo"] = _UNDO
            return preview

        return await _dos_pasos(
            ha_client, tool=tool, args=args, ids=ids,
            confirmation_token=confirmation_token,
            comprobar=lambda metas: _no_encontradas(tool, ids, metas),
            vista=vista, comando=comando,
            resultado={"cleared": True, "statistic_ids_count": len(ids), "scope": alcance},
        )

    @mcp.tool()
    @ready
    async def ha_change_statistics_unit(
        statistic_id: str,
        old_unit: str | None,
        new_unit: str | None,
        confirmation_token: str | None = None,
    ) -> object:
        """Convert every stored value of a recorder statistic to another unit of the same unit class (e.g. Wh -> kWh) and change its unit.

        Rewrites the whole history (mean, min, max, state and sum, hourly and
        5-minute tables); cannot be undone except by restoring a backup. Only
        statistics whose source is `recorder` (those of an entity), and
        `old_unit` must be the unit stored now. Two steps: without
        confirmation_token it returns a preview and changes nothing. Home
        Assistant applies the change from the recorder queue in the
        background: the confirmation answers `queued: true`; check it with
        ha_get_statistics_metadata. To change the stored unit WITHOUT
        converting values, use ha_update_statistics_metadata.

        Args:
            statistic_id: e.g. "sensor.energy".
            old_unit: The unit stored now (null if it has none).
            new_unit: The unit to convert to, e.g. "kWh".
            confirmation_token: Token from the preview call.

        Returns:
            Preview: {confirmation_token, expires_in_seconds, preview}.
            Confirmed: {queued: true, check_with, not_validated, detail}.
            not_validated: Hermes cannot tell whether the statistic is
            already stored or only announced by its integration (a new
            sensor not compiled yet); for the latter Home Assistant does
            nothing. Errors:
            invalid_argument, statistics_not_found, not_supported_for_source,
            unit_mismatch (with the current unit), recorder_not_loaded,
            ha_command_failed.
        """
        tool = "ha_change_statistics_unit"
        if not _con_forma(statistic_id, _STATISTIC_ID_RE):
            return _invalido(tool, "statistic_id", "statistic_id " + _ID_DETALLE + ".")
        for campo, valor in (("old_unit", old_unit), ("new_unit", new_unit)):
            if not _unidad_valida(valor):
                return _invalido(tool, campo, f"{campo} must be a unit text (up to "
                                 f"{_UNIDAD_MAX} characters) or null.")
        if old_unit == new_unit:
            # HA respondería «ok» y el trabajo de la cola no haría nada.
            return _invalido(tool, "new_unit", "new_unit is the same as old_unit: "
                             "there is nothing to convert.")
        args = {"statistic_id": statistic_id, "old_unit": old_unit, "new_unit": new_unit}

        def comprobar(metas: list[dict[str, Any]]) -> dict[str, Any] | None:
            error = _no_encontradas(tool, [statistic_id], metas)
            if error is not None:
                return error
            meta = metas[0]
            # En estos dos casos el trabajo de la cola de HA solo avisa en su
            # log («Could not change statistics unit») y no cambia nada,
            # aunque el comando haya respondido «ok» (research R-1).
            if meta.get("source") != "recorder":
                logger.info(f"{tool}_failed", error="not_supported_for_source")
                return {"error": "not_supported_for_source", "source": meta.get("source"),
                        "detail": ("Home Assistant only converts statistics whose source "
                                   "is 'recorder' (those of an entity). Nothing was done.")}
            actual = meta.get("statistics_unit_of_measurement")
            if actual != old_unit:
                logger.info(f"{tool}_failed", error="unit_mismatch")
                return {"error": "unit_mismatch", "current_unit": actual,
                        "detail": ("old_unit is not the unit stored now; Home Assistant "
                                   "would do nothing. Nothing was done.")}
            return None

        def vista(metas: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "action": "change_statistics_unit",
                "statistic": _resumen(metas[0]),
                "old_unit": old_unit,
                "new_unit": new_unit,
                "unit_class": metas[0].get("unit_class"),
                "converts": ["mean", "min", "max", "state", "sum"],
                "tables": ["hourly", "five_minute"],
                "scope": "entire_history",
                "effect": ("Converts every stored value of this statistic from "
                           "old_unit to new_unit and stores new_unit. Home Assistant "
                           "rejects units it cannot convert."),
                "not_validated": list(_NO_VALIDADO),
                "not_validated_detail": _NO_VALIDADO_DETALLE,
                "irreversible": True,
                "undo": _UNDO,
            }

        return await _dos_pasos(
            ha_client, tool=tool, args=args, ids=[statistic_id],
            confirmation_token=confirmation_token, comprobar=comprobar, vista=vista,
            comando={"type": "recorder/change_statistics_unit",
                     "statistic_id": statistic_id,
                     "new_unit_of_measurement": new_unit,
                     "old_unit_of_measurement": old_unit},
            resultado={
                "queued": True,
                "check_with": "ha_get_statistics_metadata",
                "not_validated": list(_NO_VALIDADO),
                "not_validated_detail": _NO_VALIDADO_DETALLE,
                "detail": ("Home Assistant queued the conversion in the recorder and "
                           "applies it in the background, usually within seconds. "
                           "It is done when ha_get_statistics_metadata shows the new "
                           "unit in statistics_unit_of_measurement."),
            },
        )

    @mcp.tool()
    @ready
    async def ha_update_statistics_metadata(
        statistic_id: str,
        unit_of_measurement: str | None,
        unit_class: str | None,
        confirmation_token: str | None = None,
    ) -> object:
        """Change the stored unit and unit class of a statistic WITHOUT converting its values.

        Use it to fix a "units changed" issue when the stored values are
        already in the new unit. To convert the values, use
        ha_change_statistics_unit. Cannot be undone except by restoring a
        backup (or by setting the old unit again). Two steps: without
        confirmation_token it returns a preview (current and new unit and
        class) and changes nothing.

        Args:
            statistic_id: e.g. "sensor.energy" or "kitchen_sink:gas".
            unit_of_measurement: The new stored unit, or null.
            unit_class: The unit class, e.g. "energy", or null when the unit
                has no class. Required: Home Assistant validates the unit
                against it.
            confirmation_token: Token from the preview call.

        Returns:
            Preview: {confirmation_token, expires_in_seconds, preview}.
            Confirmed: {updated: true, check_with, not_validated}.
            not_validated: Hermes cannot tell whether the statistic is
            already stored or only announced by its integration (a new
            sensor not compiled yet); for the latter Home Assistant does
            nothing. Errors: invalid_argument,
            statistics_not_found, recorder_not_loaded, ha_timeout,
            ha_command_failed (e.g. a unit not valid for the class).
        """
        tool = "ha_update_statistics_metadata"
        if not _con_forma(statistic_id, _STATISTIC_ID_RE):
            return _invalido(tool, "statistic_id", "statistic_id " + _ID_DETALLE + ".")
        for campo, valor in (("unit_of_measurement", unit_of_measurement),
                             ("unit_class", unit_class)):
            if not _unidad_valida(valor):
                return _invalido(tool, campo, f"{campo} must be a text (up to "
                                 f"{_UNIDAD_MAX} characters) or null.")
        args = {"statistic_id": statistic_id, "unit_of_measurement": unit_of_measurement,
                "unit_class": unit_class}

        def vista(metas: list[dict[str, Any]]) -> dict[str, Any]:
            meta = metas[0]
            return {
                "action": "update_statistics_metadata",
                "statistic_id": statistic_id,
                "source": meta.get("source"),
                "current": {"unit_of_measurement": meta.get("statistics_unit_of_measurement"),
                            "unit_class": meta.get("unit_class")},
                "new": {"unit_of_measurement": unit_of_measurement, "unit_class": unit_class},
                "converts_values": False,
                "hint": "use ha_change_statistics_unit to convert stored values",
                "not_validated": list(_NO_VALIDADO),
                "not_validated_detail": _NO_VALIDADO_DETALLE,
                "irreversible": True,
                "undo": _UNDO,
            }

        # `unit_class` va SIEMPRE, también `null`: sin ella HA la deduce de la
        # unidad y avisa de que esa forma deja de funcionar (research R-1).
        return await _dos_pasos(
            ha_client, tool=tool, args=args, ids=[statistic_id],
            confirmation_token=confirmation_token,
            comprobar=lambda metas: _no_encontradas(tool, [statistic_id], metas),
            vista=vista,
            comando={"type": "recorder/update_statistics_metadata",
                     "statistic_id": statistic_id,
                     "unit_of_measurement": unit_of_measurement,
                     "unit_class": unit_class},
            resultado={"updated": True, "check_with": "ha_get_statistics_metadata",
                       "not_validated": list(_NO_VALIDADO),
                       "not_validated_detail": _NO_VALIDADO_DETALLE},
        )

    @mcp.tool()
    @ready
    async def ha_adjust_statistics_sum(
        statistic_id: str,
        start_time: str,
        adjustment: float,
        adjustment_unit: str | None,
        confirmation_token: str | None = None,
    ) -> object:
        """Add `adjustment` to the sum of a statistic in every row from start_time on (to fix a jump or a reset in an energy or gas meter).

        NOT idempotent: confirming twice (two previews, two tokens) adds it
        twice. Cannot be undone except by restoring a backup, or by adjusting
        again with the opposite amount. Two steps: without confirmation_token
        it returns a preview (the sum stored in the hour of start_time before
        and, when the units match, after) and changes nothing. Each token is
        valid once. Home Assistant converts adjustment_unit to the unit of the
        statistic and applies the change from the recorder queue in the
        background: the confirmation answers `queued: true`; check it with
        ha_statistics_during_period.

        Args:
            statistic_id: A statistic with a sum, e.g. "sensor.energy".
            start_time: ISO 8601 with time zone at the top of an hour (in
                UTC), e.g. "2026-01-01T10:00:00+00:00". Every hourly and
                5-minute row from this instant on is adjusted.
            adjustment: The amount to add (negative to subtract); not 0.
            adjustment_unit: The unit of adjustment, e.g. "kWh" (null if the
                statistic has no unit).
            confirmation_token: Token from the preview call.

        Returns:
            Preview: {confirmation_token, expires_in_seconds, preview}.
            Confirmed: {queued: true, check_with, not_validated, detail}.
            not_validated: Hermes cannot tell whether the statistic is
            already stored or only announced by its integration (a new
            sensor not compiled yet); for the latter Home Assistant does
            nothing. Errors:
            invalid_argument (start_time not at the top of an hour, too),
            statistics_not_found, statistic_has_no_sum,
            recorder_not_loaded, ha_command_failed (e.g. invalid_units).
        """
        tool = "ha_adjust_statistics_sum"
        if not _con_forma(statistic_id, _STATISTIC_ID_RE):
            return _invalido(tool, "statistic_id", "statistic_id " + _ID_DETALLE + ".")
        inicio = _fecha_utc(start_time)
        if inicio is None:
            return _invalido(tool, "start_time", "start_time must be ISO 8601 with a time "
                             "zone, e.g. '2026-01-01T00:00:00+00:00'.")
        if inicio.minute or inicio.second or inicio.microsecond:
            # T053: HA ajusta la tabla horaria desde `start_time.replace(minute=0)`,
            # que conserva segundos y microsegundos: con 10:30:15 la fila de
            # las 10:00 NO se toca, y con 10:30 la de 5 minutos empieza a y
            # media mientras la horaria empieza a las 10. La vista previa
            # enseña la suma de esa hora: solo es verdad en una hora en punto.
            return _invalido(tool, "start_time", (
                "start_time must be at the top of an hour (in UTC), e.g. "
                "'2026-01-01T10:00:00+00:00': with minutes or seconds Home Assistant "
                "would not adjust the hourly row the preview shows."))
        if not _numero_finito(adjustment) or adjustment == 0:
            return _invalido(tool, "adjustment", "adjustment must be a finite number other "
                             "than 0.")
        if not _unidad_valida(adjustment_unit):
            return _invalido(tool, "adjustment_unit", "adjustment_unit must be a unit text "
                             f"(up to {_UNIDAD_MAX} characters) or null.")
        # El token ata los cuatro: la cantidad, la estadística, el instante (en
        # UTC, como se envía) y la unidad. Es de un solo uso, así que un
        # reintento con el mismo token no suma dos veces.
        args = {"statistic_id": statistic_id, "start_time": _iso(inicio),
                "adjustment": adjustment, "adjustment_unit": adjustment_unit}

        def comprobar(metas: list[dict[str, Any]]) -> dict[str, Any] | None:
            error = _no_encontradas(tool, [statistic_id], metas)
            if error is not None:
                return error
            # Sin suma, HA encola el ajuste y no cambia nada (research R-1).
            if not metas[0].get("has_sum"):
                logger.info(f"{tool}_failed", error="statistic_has_no_sum")
                return {"error": "statistic_has_no_sum",
                        "detail": ("This statistic has no sum (has_sum is false): there is "
                                   "nothing to adjust. Nothing was done.")}
            return None

        async def vista(metas: list[dict[str, Any]]) -> dict[str, Any]:
            unidad = metas[0].get("statistics_unit_of_measurement")
            hora = inicio.replace(minute=0, second=0, microsecond=0)
            filas = await _leer_filas(ha_client, statistic_id, hora,
                                      hora + timedelta(hours=1), types=["sum"])
            fila = next((f for f in filas if _inicio_ms(f) == hora.timestamp() * 1000), None)
            suma: dict[str, Any] | None = None
            if fila is not None and _numero_finito(fila.get("sum")):
                suma = {"before": fila["sum"]}
                # Solo con la misma unidad se puede decir la suma que queda
                # sin repetir la conversión de HA.
                if adjustment_unit == unidad:
                    suma["after"] = fila["sum"] + adjustment
            return {
                "action": "adjust_statistics_sum",
                "statistic_id": statistic_id,
                "from": args["start_time"],
                "adjustment": adjustment,
                "adjustment_unit": adjustment_unit,
                "statistics_unit": unidad,
                "sum_at_start": suma,
                "applies_to": "every row from this hour on (hourly and 5-minute)",
                "not_validated": list(_NO_VALIDADO),
                "not_validated_detail": _NO_VALIDADO_DETALLE,
                "repeat_warning": ("Not idempotent: adjusting twice adds the amount twice. "
                                   "Check with ha_statistics_during_period before "
                                   "repeating."),
                "irreversible": True,
                "undo": _UNDO + " Or adjust again with the opposite amount.",
            }

        return await _dos_pasos(
            ha_client, tool=tool, args=args, ids=[statistic_id],
            confirmation_token=confirmation_token, comprobar=comprobar, vista=vista,
            comando={"type": "recorder/adjust_sum_statistics",
                     "statistic_id": statistic_id,
                     "start_time": args["start_time"],
                     "adjustment": adjustment,
                     "adjustment_unit_of_measurement": adjustment_unit},
            resultado={
                "queued": True,
                "check_with": "ha_statistics_during_period",
                "not_validated": list(_NO_VALIDADO),
                "not_validated_detail": _NO_VALIDADO_DETALLE,
                "detail": ("Home Assistant queued the adjustment in the recorder and "
                           "applies it in the background, usually within seconds. Do "
                           "not repeat it: check the sum with "
                           "ha_statistics_during_period first."),
            },
        )

    @mcp.tool()
    @ready
    async def ha_import_statistics(
        metadata: dict,
        stats: list[dict] | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Import hourly long-term statistics: insert rows, overwrite the rows that have the same start, and create or update the statistic's metadata.

        Cannot be undone except by restoring a backup (overwritten rows are
        lost). Two steps: without confirmation_token it returns a preview
        (whether the statistic exists, current and new metadata, number of
        rows, first and last hour, and how many existing rows are
        overwritten) and changes nothing. To confirm, repeat the call with
        metadata and confirmation_token; stats can be omitted (the server
        keeps the one from the preview) and, if sent, must be identical. Home
        Assistant imports from the recorder queue in the background: the
        confirmation answers `queued: true`; check it with
        ha_statistics_during_period.

        Args:
            metadata: {statistic_id, source, name, unit_of_measurement,
                unit_class, mean_type, has_sum}, all required. statistic_id
                "sensor.x" needs source "recorder"; "mysource:x" needs source
                "mysource". mean_type: 0 none, 1 arithmetic, 2 circular
                (angles).
            stats: 1-5000 rows {start, mean?, min?, max?, state?, sum?,
                last_reset?}. start: ISO 8601 with time zone at the top of an
                hour (in UTC), one row per hour. Required in the preview.
            confirmation_token: Token from the preview call.

        Returns:
            Preview: {confirmation_token, expires_in_seconds, preview,
            confirm_with, omit_on_confirm, confirm_hint}. Confirmed:
            {queued: true, rows, check_with, detail}. Errors:
            invalid_argument, recorder_not_loaded, ha_command_failed.
        """
        tool = "ha_import_statistics"
        meta, campo, detalle = _validar_metadata(metadata)
        if meta is None:
            return _invalido(tool, campo, detalle)
        filas: list[dict[str, Any]] | None = None
        if stats is not None or not confirmation_token:
            # En la vista previa `stats` es obligatorio; al confirmar, si
            # llega, se normaliza igual para compararlo con lo previsualizado.
            filas, detalle = _validar_stats(stats)
            if filas is None:
                return _invalido(tool, "stats", detalle)
        statistic_id = meta["statistic_id"]
        # El token ata el documento COMPLETO normalizado (su hash): una fila
        # distinta da «does not match». `stats` se guarda con el token para
        # no tener que reenviarlo (spec 018); si no cabe, hay que reenviarlo.
        args = {"metadata": meta, "stats": filas}

        async def vista(metas: list[dict[str, Any]]) -> dict[str, Any]:
            assert filas is not None
            primera = datetime.fromisoformat(filas[0]["start"])
            ultima = datetime.fromisoformat(filas[-1]["start"])
            preview: dict[str, Any] = {
                "action": "import_statistics",
                "statistic_id": statistic_id,
                "exists": bool(metas),
            }
            if metas:
                preview["current_metadata"] = _resumen(metas[0])
            preview.update(
                new_metadata=meta, rows=len(filas),
                columns=sorted({k for f in filas for k in f} - {"start"}),
                first_start=filas[0]["start"], last_start=filas[-1]["start"])
            if not metas:
                preview["overwritten_rows"] = 0
            elif ultima - primera <= _RANGO_RECUENTO:
                existentes = await _leer_filas(ha_client, statistic_id, primera,
                                               ultima + timedelta(hours=1))
                nuevas = {datetime.fromisoformat(f["start"]).timestamp() * 1000 for f in filas}
                preview["overwritten_rows"] = sum(
                    1 for f in existentes if _inicio_ms(f) in nuevas)
            else:
                # Contar en un rango de meses o años exigiría leerlo entero.
                preview["overwritten_rows"] = None
                preview["overwritten_rows_reason"] = (
                    "Not counted: the rows span more than 31 days. Rows with the same "
                    "start as an existing row overwrite it.")
            if "." in statistic_id and await ha_client.get_state(statistic_id) is not None:
                preview["recorded_entity_warning"] = (
                    "This statistic belongs to an existing entity: the recorder keeps "
                    "compiling its statistics every hour and may overwrite imported rows "
                    "for new hours.")
            preview["effect"] = ("Inserts the rows, overwrites existing rows with the same "
                                 "start, and stores new_metadata.")
            preview["irreversible"] = True
            preview["undo"] = _UNDO
            return preview

        def comando(resueltos: dict[str, Any]) -> dict[str, Any]:
            return {"type": "recorder/import_statistics", "metadata": resueltos["metadata"],
                    "stats": resueltos["stats"]}

        def resultado(resueltos: dict[str, Any]) -> dict[str, Any]:
            return {
                "queued": True,
                "rows": len(resueltos["stats"]),
                "check_with": "ha_statistics_during_period",
                "detail": ("Home Assistant queued the import in the recorder and applies "
                           "it in the background, usually within seconds."),
            }

        return await _dos_pasos(
            ha_client, tool=tool, args=args, ids=[statistic_id],
            confirmation_token=confirmation_token,
            # Puede no existir: importar también crea. Lo que HA rechazaría ya
            # lo rechazó la validación (fuente, horas en punto, `mean_type`).
            comprobar=lambda metas: None,
            vista=vista, comando=comando, resultado=resultado, omitibles=("stats",),
        )
