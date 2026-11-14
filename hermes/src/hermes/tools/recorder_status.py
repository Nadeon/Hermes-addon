"""Hermes — el recorder y las estadísticas de largo plazo (spec 029, CAP-049).

Tres tools, familia `recorder`, hoy todas de SOLO LECTURA:

- `ha_validate_statistics`: los problemas que HA detecta en las estadísticas
  (`recorder/validate_statistics`).
- `ha_get_statistics_metadata`: los metadatos de unas estadísticas concretas
  (`recorder/get_statistics_metadata`).
- `ha_get_recorder_info`: si el recorder graba, su cola y su migración
  (`recorder/info`) y, con `entity_id`, si esa entidad se graba
  (`recorder/entity_options/get`).

POR QUÉ UNA FAMILIA `recorder` Y NO `statistics`
------------------------------------------------
La familia agrupa todo lo que habla con el recorder, no solo las lecturas: la
020 (CAP-050, FR-069 de la 008) añadirá aquí el mantenimiento de estadísticas
(limpiar, cambiar la unidad, editar metadatos, ajustar sumas, importar,
regenerar los avisos de Repairs). Quien apague `recorder` apaga entonces lo
que lee y lo que escribe en la base de estadísticas, que es lo que espera. El
día que entre la primera tool que escribe, la descripción de la familia deja
de decir «read only» (principio V) y esas tools llevan su confirmación en dos
pasos; las de este módulo siguen sin token. `ha_list_statistic_ids` y
`ha_statistics_during_period` son de la 1.1.2 y siguen en `data` (FR-010 de
la 008: las familias de la 1.1.2 no cambian).

LO COMÚN CON `system_status`
----------------------------
Se valida la forma de cada argumento ANTES de llamar a HA; toda respuesta
pasa por `redact_structure` + `redact_secrets`; las listas usan el sobre común
(`ajustar_lista_a_bytes`); el log lleva solo el resultado y recuentos, nunca
ids de estadísticas, nombres de entidades ni valores (FR-019).

`unknown_command` en un comando del recorder significa que la integración no
está cargada (sin `recorder:` ni `default_config:`): `recorder_not_loaded`,
no «versión de HA» (FR-011, FR-020, principio V). La excepción es
`recorder/entity_options/get` cuando `recorder/info` acaba de responder: con
el recorder cargado, no conocerlo solo puede ser la versión.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import redact_secrets
from hermes.tools._common import (
    ajustar_lista_a_bytes,
    entity_exists,
    not_found_response,
    requires_ready,
)
from hermes.tools.system_status import _invalido, _limpio

logger = structlog.get_logger(__name__)

# `<dominio>.<objeto>` (las de una entidad, fuente `recorder`) o
# `<fuente>:<id>` (las externas, p. ej. `kitchen_sink:gas_consumption`): la
# forma de `valid_statistic_id` de HA, más permisiva solo en el separador.
_STATISTIC_ID_RE = re.compile(r"[a-z0-9_]+[.:][a-z0-9_]+")
_ENTITY_ID_RE = re.compile(r"[a-z0-9_]+\.[a-z0-9_]+")
_TIPO_RE = re.compile(r"[a-z0-9_]+")
_ID_MAX = 255
_METADATOS_MAX = 100

# Los siete campos de `recorder/info` en HA 2026.11 (`basic_websocket_api.py`).
_CAMPOS_INFO = (
    "recording", "thread_running", "backlog", "max_backlog",
    "migration_in_progress", "migration_is_live", "db_in_default_location",
)

_NO_CARGADO = (
    "The recorder integration is not loaded in Home Assistant (it is part of "
    "default_config); without it there is no history, logbook or statistics. "
    "Add `recorder:` to configuration.yaml to enable it."
)


def _con_forma(valor: Any, patron: re.Pattern[str], maximo: int = _ID_MAX) -> bool:
    return (isinstance(valor, str) and 0 < len(valor) <= maximo
            and patron.fullmatch(valor) is not None)


def _error_ha(tool: str, exc: HAConnectionError) -> dict[str, Any]:
    """Traduce un error de un comando del recorder (FR-011, FR-020)."""
    detalle = redact_secrets(str(exc))
    if exc.code is None:
        # Sin código de HA es un fallo de conexión: el error de siempre.
        logger.info(f"{tool}_failed", error="connection")
        return {"error": detalle}
    if exc.code == "unknown_command":
        logger.info(f"{tool}_failed", error="recorder_not_loaded")
        return {"error": "recorder_not_loaded", "detail": _NO_CARGADO,
                "ha_code": exc.code}
    logger.info(f"{tool}_failed", error=exc.code)
    return {"error": "ha_command_failed", "detail": detalle, "ha_code": exc.code}


# ── Registro ─────────────────────────────────────────────────────────────────

def register(mcp: Any, ha_client: HAClient, *, response_max_bytes: int) -> None:
    """Registra las tres tools de la familia `recorder`."""
    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_validate_statistics(
        statistic_id: str | None = None, issue_type: str | None = None,
    ) -> object:
        """List the problems Home Assistant finds in its long-term statistics (what Developer tools > Statistics shows as issues).

        Read only: it only validates. It does not fix anything, and it does
        not create or dismiss Repairs issues. Typical issue types: units
        changed, state_class removed or not supported, entity no longer
        recorded or no longer present, mean type changed. Items are sorted by
        statistic_id; `by_type` counts every issue found, before the filters.

        Args:
            statistic_id: Only issues of this statistic, e.g. "sensor.energy"
                or "kitchen_sink:gas".
            issue_type: Only issues of this type, e.g. "units_changed".

        Returns:
            {count, truncated, by_type, items: [{statistic_id, type, data}]}.
            Error recorder_not_loaded when Home Assistant has no recorder.
        """
        tool = "ha_validate_statistics"
        if statistic_id is not None and not _con_forma(statistic_id, _STATISTIC_ID_RE):
            return _invalido(tool, "statistic_id",
                             "statistic_id must look like 'sensor.energy' or "
                             "'source:statistic' (lowercase letters, digits and '_').")
        if issue_type is not None and not _con_forma(issue_type, _TIPO_RE, 64):
            return _invalido(tool, "issue_type",
                             "issue_type must be lowercase letters, digits and '_', "
                             "e.g. 'units_changed'.")
        try:
            bruto = await ha_client.ws_send({"type": "recorder/validate_statistics"})
        except HAConnectionError as exc:
            return _error_ha(tool, exc)

        todos: list[dict[str, Any]] = []
        for sid, problemas in (bruto.items() if isinstance(bruto, Mapping) else ()):
            for p in (problemas if isinstance(problemas, list) else ()):
                if isinstance(p, Mapping):
                    todos.append({"statistic_id": sid, "type": p.get("type"),
                                  "data": p.get("data")})
        todos.sort(key=lambda x: (str(x["statistic_id"]), str(x["type"])))
        por_tipo = dict(sorted(Counter(str(x["type"]) for x in todos).items()))
        items = [x for x in todos
                 if (statistic_id is None or x["statistic_id"] == statistic_id)
                 and (issue_type is None or x["type"] == issue_type)]

        def construir(xs: list[Any], recortada: bool) -> dict[str, Any]:
            return {"count": len(xs), "truncated": recortada, "by_type": por_tipo,
                    "items": xs}

        out = ajustar_lista_a_bytes(_limpio(items), construir, response_max_bytes)
        logger.info(f"{tool}_ok", count=out["count"], issues=len(todos),
                    types=len(por_tipo), truncated=out["truncated"])
        return out

    @mcp.tool()
    @ready
    async def ha_get_statistics_metadata(statistic_ids: list[str]) -> object:
        """Read the metadata of the named long-term statistics: source, units, whether they have a mean and a sum.

        Read only. Duplicated ids are asked once; the ones Home Assistant does
        not know are listed in `missing`. To list every statistic, use
        `ha_list_statistic_ids`; for the values, `ha_statistics_during_period`.

        Args:
            statistic_ids: 1-100 statistic ids, e.g. ["sensor.energy",
                "kitchen_sink:gas"].

        Returns:
            {count, truncated, missing, items: [{statistic_id, name, source,
            has_mean, mean_type, has_sum, statistics_unit_of_measurement,
            display_unit_of_measurement, unit_class}]} as Home Assistant gives
            them. Error recorder_not_loaded when Home Assistant has no
            recorder.
        """
        tool = "ha_get_statistics_metadata"
        if (not isinstance(statistic_ids, list)
                or not 1 <= len(statistic_ids) <= _METADATOS_MAX
                or not all(_con_forma(x, _STATISTIC_ID_RE) for x in statistic_ids)):
            return _invalido(tool, "statistic_ids",
                             "statistic_ids must be a list of 1 to 100 ids like "
                             "'sensor.energy' or 'source:statistic'.")
        pedidas = list(dict.fromkeys(statistic_ids))
        try:
            bruto = await ha_client.ws_send(
                {"type": "recorder/get_statistics_metadata", "statistic_ids": pedidas})
        except HAConnectionError as exc:
            return _error_ha(tool, exc)

        filas = [m for m in (bruto if isinstance(bruto, list) else [])
                 if isinstance(m, Mapping)]
        devueltas = {m.get("statistic_id") for m in filas}
        missing = [s for s in pedidas if s not in devueltas]
        items = sorted(filas, key=lambda m: str(m.get("statistic_id")))

        def construir(xs: list[Any], recortada: bool) -> dict[str, Any]:
            return {"count": len(xs), "truncated": recortada, "missing": missing,
                    "items": xs}

        out = ajustar_lista_a_bytes(_limpio(items), construir, response_max_bytes)
        logger.info(f"{tool}_ok", requested=len(pedidas), count=out["count"],
                    missing=len(missing), truncated=out["truncated"])
        return out

    @mcp.tool()
    @ready
    async def ha_get_recorder_info(entity_id: str | None = None) -> object:
        """Read the recorder status: whether it is recording, its queue, and whether a database migration is running.

        Read only. With `entity_id`, it also says whether that entity is
        recorded (`recorded`) and who disabled its recording
        (`recording_disabled_by`, null when it is recorded). It does not
        change what is recorded.

        Args:
            entity_id: An existing entity, e.g. "sensor.energy".

        Returns:
            {recording, thread_running, backlog, max_backlog,
            migration_in_progress, migration_is_live, db_in_default_location,
            entity?: {entity_id, recorded, recording_disabled_by}}. Errors:
            invalid_argument, not_found (the entity does not exist),
            recorder_not_loaded.
        """
        tool = "ha_get_recorder_info"
        if entity_id is not None:
            if not _con_forma(entity_id, _ENTITY_ID_RE):
                return _invalido(tool, "entity_id",
                                 "entity_id must look like 'sensor.energy' "
                                 "(lowercase letters, digits and '_').")
            # Primero que exista: HA contesta `recorded: true` a cualquier
            # entity_id bien formado, exista o no, y eso induciría a pensar
            # que una entidad mal escrita se está grabando (FR-010).
            try:
                existe = await entity_exists(ha_client, entity_id)
            except HAConnectionError as exc:
                return _error_ha(tool, exc)
            if not existe:
                logger.info(f"{tool}_failed", error="not_found")
                return not_found_response(entity_id)
        try:
            bruto = await ha_client.ws_send({"type": "recorder/info"})
        except HAConnectionError as exc:
            return _error_ha(tool, exc)
        info = bruto if isinstance(bruto, Mapping) else {}
        out: dict[str, Any] = {c: info.get(c) for c in _CAMPOS_INFO}

        if entity_id is not None:
            try:
                opciones = await ha_client.ws_send(
                    {"type": "recorder/entity_options/get", "entity_id": entity_id})
            except HAConnectionError as exc:
                if exc.code == "unknown_command":
                    # `recorder/info` acaba de responder: el recorder está
                    # cargado y lo que falta es el comando (versión de HA).
                    from hermes.command_table import TABLE_HA_CORE
                    out["entity"] = {
                        "entity_id": entity_id,
                        "error": "unsupported_by_ha_version",
                        "detail": ("The installed Home Assistant cannot tell whether one "
                                   f"entity is recorded; Hermes' table is for {TABLE_HA_CORE}."),
                        "ha_code": exc.code,
                        "table_ha_core": TABLE_HA_CORE,
                    }
                else:
                    return _error_ha(tool, exc)
            else:
                por = opciones.get("recording_disabled_by") if isinstance(opciones, Mapping) else None
                out["entity"] = {"entity_id": entity_id, "recorded": por is None,
                                 "recording_disabled_by": por}

        out = _limpio(out)
        entidad = out.get("entity") or {}
        logger.info(f"{tool}_ok", recording=out["recording"], backlog=out["backlog"],
                    entity=entity_id is not None, recorded=entidad.get("recorded"))
        return out
