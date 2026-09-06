"""Hermes — Tools MCP ha_statistics_during_period + ha_list_statistic_ids.

Usa los comandos WS `recorder/statistics_during_period` y
`recorder/list_statistic_ids` de HA. Ambos son single-shot (type:result),
compatibles con ws_send actual.

Los timestamps de los puntos estadísticos (start, end) llegan como floats Unix
y se convierten a ISO 8601 antes de devolver al cliente MCP.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)

# Máximo de puntos por statistic_id antes de truncar por conteo
_MAX_POINTS_PER_STATISTIC = 1000

# Granularidades válidas según HA recorder
_VALID_PERIODS = {"5minute", "hour", "day", "week", "month"}

# Rango máximo permitido para granularidad 5minute (7 días)
_FIVEMINUTE_MAX_HOURS = 7 * 24.0


_TS_MS_THRESHOLD = 9_999_999_999.0  # timestamps > este valor están en milisegundos


def _ts_to_iso(ts: float | None) -> str | None:
    """Convierte Unix timestamp float a ISO 8601 UTC. None si ts es None.

    HA statistics envía algunos timestamps en milisegundos (p.ej. integraciones
    externas). Si `ts` supera el umbral de ~año 2286 se interpreta como ms y
    se divide entre 1000 antes de convertir.
    """
    if ts is None:
        return None
    if ts > _TS_MS_THRESHOLD:
        ts = ts / 1000.0
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _clean_float(val: Any) -> Any:
    """Convierte NaN/Inf a None para que json.dumps no falle.

    HA statistics devuelven NaN para campos que no aplican al tipo de sensor
    (ej. mean=NaN en sensores de suma, sum=NaN en sensores de media).
    """
    if isinstance(val, float) and not math.isfinite(val):
        return None
    return val


def _expand_stat_point(point: dict[str, Any]) -> dict[str, Any]:
    """Convierte campos start/end de float Unix a ISO y limpia NaN/Inf."""
    result: dict[str, Any] = {}
    for key, val in point.items():
        if key in ("start", "end") and isinstance(val, (int, float)) and math.isfinite(val):
            result[key] = _ts_to_iso(val)
        else:
            result[key] = _clean_float(val)
    return result


def _truncate_stats_to_bytes(
    stats: dict[str, list[dict[str, Any]]],
    max_bytes: int,
) -> tuple[dict[str, list[dict[str, Any]]], bool, str | None]:
    """Trunca a max_bytes eliminando puntos del final (más recientes).

    Nunca corta a mitad de punto. Reduce de forma equitativa entre statistic_ids.

    Returns:
        (stats_truncados, fue_truncado, truncated_at_iso)
        truncated_at_iso es el campo `end` (o `start`) del último punto incluido.
    """
    serialized = json.dumps(stats, ensure_ascii=False)
    if len(serialized.encode()) <= max_bytes:
        return stats, False, None

    working = {sid: list(pts) for sid, pts in stats.items()}
    while True:
        serialized = json.dumps(working, ensure_ascii=False)
        if len(serialized.encode()) <= max_bytes:
            break
        total = sum(len(v) for v in working.values())
        if total == 0:
            break
        # Quitar el último punto de la lista con más puntos
        biggest = max(working, key=lambda k: len(working[k]))
        if not working[biggest]:
            break
        working[biggest].pop()

    # Encontrar el timestamp del último punto incluido
    last_ts: str | None = None
    for pts in working.values():
        if pts:
            ts = pts[-1].get("end") or pts[-1].get("start")
            if ts and (last_ts is None or ts > last_ts):
                last_ts = ts

    return working, True, last_ts


def register(mcp: object, ha_client: HAClient, response_max_bytes: int = 1_048_576) -> None:
    """Registra ha_statistics_during_period y ha_list_statistic_ids."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_list_statistic_ids(
        statistic_type: str | None = None,
    ) -> object:
        """Lista los statistic_ids disponibles en el recorder de HA con metadata.

        Útil para descubrir qué sensores tienen estadísticas largas (energía,
        temperatura, contadores acumulativos, etc.) antes de llamar a
        ha_statistics_during_period.

        Args:
            statistic_type: Filtrar por tipo de estadística:
                            "mean"  → sensores con media (temperatura, humedad…)
                            "sum"   → sensores acumulativos (energía, agua…)
                            Si None, devuelve todos.

        Returns:
            JSON con {
              "statistic_ids": [
                {
                  "statistic_id": "sensor.energia_total",
                  "name": "Energía total",
                  "source": "recorder",
                  "unit_of_measurement": "kWh",
                  "has_mean": false,
                  "has_sum": true
                },
...
              ],
              "count": 42
            }
        """
        payload: dict[str, Any] = {"type": "recorder/list_statistic_ids"}
        if statistic_type is not None:
            payload["statistic_type"] = statistic_type

        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            logger.error("ha_list_statistic_ids_ws_error", error=str(exc))
            return json.dumps({"error": str(exc)})

        items: list[dict] = raw if isinstance(raw, list) else []
        logger.info("ha_list_statistic_ids_ok", count=len(items))
        return json.dumps({"statistic_ids": items, "count": len(items)})

    @mcp.tool()
    @ready
    async def ha_statistics_during_period(
        statistic_ids: list[str],
        period: str = "hour",
        hours_back: float = 24.0,
        start_time: str | None = None,
        end_time: str | None = None,
        types: list[str] | None = None,
        units: dict[str, str] | None = None,
    ) -> object:
        """Devuelve estadísticas agregadas de sensores (energía, temperatura, etc.).

        Para sensores con `state_class` (measurement / total / total_increasing).
        Los datos se agregan por `period`. Los sensores sin state_class no tienen
        estadísticas; usa ha_get_history para su historial de cambios de estado.

        Usa ha_list_statistic_ids para descubrir statistic_ids disponibles y sus
        unidades antes de llamar a esta herramienta.

        Args:
            statistic_ids: Lista de statistic_ids a consultar
                           (ej. ["sensor.energia_total", "sensor.temperatura_salon"]).
            period: Granularidad de agregación: "5minute", "hour", "day", "week",
                    "month". Rangos >7 días rechazan "5minute" (demasiados puntos).
            hours_back: Horas hacia atrás desde ahora. Default 24h. Ignorado si
                        se proporciona start_time.
            start_time: Inicio del rango en ISO 8601
                        (ej. "2026-04-01T00:00:00Z").
            end_time: Fin del rango en ISO 8601. Default: ahora.
            types: Tipos de estadística a incluir — combinación de "mean", "min",
                   "max", "sum", "state", "change". Si None, HA devuelve todos
                   los disponibles para cada statistic_id.
            units: Conversión de unidades (ej. {"energy": "kWh", "temperature": "°C"}).
                   Si None, HA usa las unidades configuradas del sensor.

        Returns:
            JSON con {
              "statistics": {
                "<statistic_id>": [
                  {
                    "start":  "2026-04-12T10:00:00+00:00",
                    "end":    "2026-04-12T11:00:00+00:00",
                    "mean":   20.5,    // null si no aplica para este sensor
                    "min":    18.0,
                    "max":    23.0,
                    "sum":    null,
                    "state":  null,
                    "change": null
                  },
...
                ]
              },
              "covered_range": {
                "start": "2026-04-12T10:00:00+00:00",  // primer punto incluido
                "end":   "2026-04-13T10:00:00+00:00"   // último punto incluido
              },
              "granularity": "hour",
              "truncated": false,
              "truncated_at": null   // ISO del último punto incluido si truncated
            }

            En caso de error de validación devuelve:
            {"error": "invalid_period" | "range_too_large_for_5minute", "detail": "..."}
        """
        # Calcular rango temporal y estimar range_hours para validación
        if start_time is None:
            start_dt = datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)
            start_iso = start_dt.isoformat()
            range_hours = hours_back
        else:
            start_iso = start_time
            try:
                start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
                end_dt = (
                    datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                    if end_time
                    else datetime.now(tz=timezone.utc)
                )
                range_hours = (end_dt - start_dt).total_seconds() / 3600
            except Exception:
                range_hours = hours_back

        # Validar period
        if period not in _VALID_PERIODS:
            return json.dumps({
                "error": "invalid_period",
                "detail": f"period must be one of {sorted(_VALID_PERIODS)}",
                "given": period,
            })

        # Validar 5minute solo para rangos ≤7 días
        if period == "5minute" and range_hours > _FIVEMINUTE_MAX_HOURS:
            return json.dumps({
                "error": "range_too_large_for_5minute",
                "detail": (
                    f"Granularidad '5minute' solo permite rangos ≤7 días "
                    f"({_FIVEMINUTE_MAX_HOURS:.0f}h). "
                    f"Rango solicitado: {range_hours:.1f}h. "
                    f"Usa period='hour' o superior para rangos más largos."
                ),
                "hint": "Reduce el rango o cambia period a 'hour'.",
            })

        payload: dict[str, Any] = {
            "type": "recorder/statistics_during_period",
            "start_time": start_iso,
            "statistic_ids": statistic_ids,
            "period": period,
        }
        if end_time is not None:
            payload["end_time"] = end_time
        if types is not None:
            payload["types"] = types
        if units is not None:
            payload["units"] = units

        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            logger.error("ha_statistics_during_period_ws_error", error=str(exc))
            return json.dumps({"error": str(exc)})

        if not isinstance(raw, dict):
            raw = {}

        # Expandir timestamps y truncar por conteo
        expanded: dict[str, list[dict[str, Any]]] = {}
        for sid, pts in raw.items():
            if not isinstance(pts, list):
                continue
            points = [_expand_stat_point(p) for p in pts if isinstance(p, dict)]
            if len(points) > _MAX_POINTS_PER_STATISTIC:
                points = points[:_MAX_POINTS_PER_STATISTIC]
            expanded[sid] = points

        # Truncar por bytes (nunca a mitad de punto)
        final, truncated, truncated_at = _truncate_stats_to_bytes(expanded, response_max_bytes)

        # Calcular covered_range sobre los datos finales
        all_starts = [pts[0].get("start") for pts in final.values() if pts]
        all_ends = [
            pts[-1].get("end") or pts[-1].get("start")
            for pts in final.values() if pts
        ]
        covered_range: dict[str, str | None] = {
            "start": min(all_starts) if all_starts else None,
            "end": max(all_ends) if all_ends else None,
        }

        logger.info(
            "ha_statistics_during_period_ok",
            statistic_count=len(final),
            period=period,
            truncated=truncated,
        )
        return json.dumps({
            "statistics": final,
            "covered_range": covered_range,
            "granularity": period,
            "truncated": truncated,
            "truncated_at": truncated_at,
        })
