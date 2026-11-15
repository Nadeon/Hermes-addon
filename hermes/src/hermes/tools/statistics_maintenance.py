"""Hermes — mantenimiento de las estadísticas de largo plazo (spec 020, CAP-050).

Tools de la familia `recorder` que ESCRIBEN en la base de estadísticas, todas
en dos pasos (vista previa con token y confirmación):

- `ha_clear_statistics`: borra estadísticas enteras (filas y metadatos) o las
  filas que se solapan con un rango (`recorder/clear_statistics`).
- `ha_change_statistics_unit`: convierte todo el histórico a otra unidad de
  la misma clase (`recorder/change_statistics_unit`).
- `ha_update_statistics_metadata`: cambia la unidad y la clase guardadas SIN
  convertir los valores (`recorder/update_statistics_metadata`).

(El tramo 2 añade aquí ajustar sumas e importar, con el mismo ayudante.)

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

`queued: true` (decisión D-1 del supervisor): `change_statistics_unit` solo
encola el trabajo en el recorder y HA contesta antes de hacerlo. Hermes no
espera a que la cola se vacíe; dice que se aplica en segundo plano y cómo
comprobarlo. Borrar y editar metadatos sí esperan en HA (10 s); si vence,
`ha_timeout` avisa de que el trabajo puede seguir en la cola.

Log: nombre de la tool, paso, resultado y recuentos. Nunca ids, unidades,
fechas ni valores (FR-018): dicen qué hay en la casa.
"""

from __future__ import annotations

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

_UNDO = (
    "Cannot be undone from Hermes: only restoring a backup that includes the "
    "Home Assistant database brings the old data back."
)
_ID_DETALLE = "must look like 'sensor.energy' or 'source:statistic' (lowercase letters, digits and '_')"
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
    vista: Callable[[list[dict[str, Any]]], dict[str, Any]],
    comando: dict[str, Any],
    resultado: dict[str, Any],
    omitibles: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Lectura de metadatos → comprobaciones → vista previa o ejecución.

    `args` son los argumentos normalizados que ata el token (los mismos que
    acaban en `comando`). `comprobar` devuelve un error (sin token) para lo
    que HA aceptaría sin hacer nada. `resultado` es lo que se devuelve si HA
    responde bien.
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
        preview = _limpio(vista(metas))
        logger.info(f"{tool}_preview", statistics=len(ids))
        return await create_confirmation_token(
            tool, args, preview, omitibles=omitibles, estado=metas)

    valido, motivo, _ = await resolve_confirmation_token(
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
        delete. Without a range each statistic disappears entirely. With a
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
                preview["effect"] = (
                    "Deletes these statistics entirely: every row and their "
                    "metadata. They disappear from the statistics lists.")
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
            Confirmed: {queued: true, check_with, detail}. Errors:
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
            Confirmed: {updated: true}. Errors: invalid_argument,
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
            resultado={"updated": True},
        )
