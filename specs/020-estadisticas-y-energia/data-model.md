# Modelo de datos: estadísticas y energía (020)

## Catálogo de familias (`tool_families.py`)

| Familia | Desde | Desactivable | Módulos | Descripción (inglés, la ve el usuario) |
|---|---|---|---|---|
| `recorder` (029, cambia) | 1.2.0 | sí | `recorder_status`, `statistics_maintenance` | Recorder status and long-term statistics: validation, metadata and maintenance (clear, change units, fix metadata, adjust sums, import; with confirmation). |
| `energy` (nueva) | 1.2.0 | sí | `energy` | Energy dashboard preferences: read and save (with confirmation). |

## Tabla de clasificación (`command_table.py`)

| Comando | Antes | Después | Tool / motivo | Familia | CAP |
|---|---|---|---|---|---|
| `recorder/clear_statistics` | deny (spec 020) | dedicated | `ha_clear_statistics` | `recorder` | CAP-050 |
| `recorder/change_statistics_unit` | deny (spec 020) | dedicated | `ha_change_statistics_unit` | `recorder` | CAP-050 |
| `recorder/update_statistics_metadata` | deny (spec 020) | dedicated | `ha_update_statistics_metadata` | `recorder` | CAP-050 |
| `recorder/adjust_sum_statistics` | deny (spec 020) | dedicated | `ha_adjust_statistics_sum` | `recorder` | CAP-050 |
| `recorder/import_statistics` | deny (spec 020) | dedicated | `ha_import_statistics` | `recorder` | CAP-050 |
| `recorder/update_statistics_issues` | deny (spec 020) | confirm | «vuelve a crear o quitar los avisos de Repairs de las estadísticas; no toca filas ni metadatos» | `generic_commands` | CAP-050 |
| `energy/get_prefs` | deny (spec 020) | dedicated | `ha_get_energy_prefs` | `energy` | CAP-054 |
| `energy/save_prefs` | deny (spec 020) | dedicated | `ha_update_energy_prefs` | `energy` | CAP-054 |
| `energy/validate` | deny (spec 020) | read | «problemas de configuración del panel de energía por fuente y dispositivo; solo lee» | `generic_commands` | CAP-054 |
| `energy/info` | deny (spec 020) | read | «sensores de coste creados por energía y dominios con previsión solar; solo lee» | `generic_commands` | CAP-054 |
| `energy/solar_forecast` | deny (spec 020) | read | «previsión solar que ya tienen las integraciones configuradas en las fuentes solares; solo lee, no la descarga» | `generic_commands` | CAP-054 |
| `energy/fossil_energy_consumption` | deny (spec 020) | read | «consumo de origen fósil calculado con estadísticas de energía y de intensidad de CO2; solo lee» + `example` | `generic_commands` | CAP-054 |

`example` de `energy/fossil_energy_consumption` (revisado contra
`energy/websocket_api.py`):

```json
{"start_time": "2026-01-01T00:00:00+00:00", "end_time": "2026-01-02T00:00:00+00:00",
 "energy_statistic_ids": ["sensor.consumo"], "co2_statistic_id": "sensor.intensidad_co2",
 "period": "hour"}
```

Generador: las siete claves `dedicated` en `_DEDICADAS_INICIALES` (bloque
comentado «020»). Las cinco `read`/`confirm` se editan a mano en la tabla (la
regeneración conserva lo editado) y van en `_POR_LA_TABLA` de
`tests/test_command_table.py` con «spec 020: <porqué>».

## Anotaciones (`tools/_annotations.py`)

| Tool | Hint | Título | Dónde |
|---|---|---|---|
| `ha_clear_statistics` | `-DI-` | Clear statistics (Home Assistant) | `_DESTRUCTIVE_EXACT` |
| `ha_change_statistics_unit` | `-DI-` | Change statistics unit (Home Assistant) | `_DESTRUCTIVE_EXACT` |
| `ha_update_statistics_metadata` | `-DI-` | Update statistics metadata (Home Assistant) | `_DESTRUCTIVE_EXACT` |
| `ha_adjust_statistics_sum` | `-D--` | Adjust statistics sum (Home Assistant) | `_DESTRUCTIVE_EXACT` y `_NON_IDEMPOTENT_EXACT` |
| `ha_import_statistics` | `-DI-` | Import statistics (Home Assistant) | `_DESTRUCTIVE_EXACT` |
| `ha_get_energy_prefs` | `R-I-` | Get energy prefs (Home Assistant) | prefijo |
| `ha_update_energy_prefs` | `-DI-` | Update energy prefs (Home Assistant) | `_DESTRUCTIVE_EXACT` |

## Inventario de argumentos atados (`tests/test_confirmation_args_inventory.py`)

| Tool | Atados | Exentos |
|---|---|---|
| `ha_clear_statistics` | `statistic_ids` (ordenados, sin repetir), `start_time`, `end_time` (UTC ISO) | `confirmation_token` |
| `ha_change_statistics_unit` | `statistic_id`, `old_unit`, `new_unit` | `confirmation_token` |
| `ha_update_statistics_metadata` | `statistic_id`, `unit_of_measurement`, `unit_class` | `confirmation_token` |
| `ha_adjust_statistics_sum` | `statistic_id`, `start_time` (UTC ISO), `adjustment`, `adjustment_unit` | `confirmation_token` |
| `ha_import_statistics` | `metadata`, `stats` (omitible al confirmar; normalizado: `start` en UTC ISO, ordenado) | `confirmation_token` |
| `ha_update_energy_prefs` | `energy_sources`, `device_consumption`, `device_consumption_water` | `confirmation_token` |

Además del `action_hash`, todas pasan `estado`: los metadatos leídos de las
estadísticas tocadas (las cinco de CAP-050) o las preferencias actuales
(energía).

## Respuestas

### Vista previa (primer paso, común)

`{confirmation_token, expires_in_seconds, preview: {...}}` (+ `confirm_with`,
`omit_on_confirm`, `confirm_hint` en `ha_import_statistics`). `preview`
siempre lleva `action`, `irreversible: true` (salvo energía:
`irreversible: false`, se puede volver a guardar lo anterior, que la vista
previa incluye en `current`), `undo` (texto) y lo propio de cada tool.

### `ha_clear_statistics`

- preview: `{action: "clear_statistics", statistics: [{statistic_id, source,
  name, statistics_unit_of_measurement, unit_class, has_mean, mean_type,
  has_sum}], scope: "entire" | "range", requested_range?: {start_time,
  end_time}, effective_range?: {hourly: {after, before}, five_minute: {after,
  before}}, removes_metadata: bool, irreversible, undo}`.
- confirmación: `{cleared: true, statistic_ids_count, scope}`.

### `ha_change_statistics_unit`

- preview: `{action, statistic: {…metadatos}, old_unit, new_unit, unit_class,
  converts: ["mean", "min", "max", "state", "sum"], tables: ["hourly",
  "five_minute"], scope: "entire_history", irreversible, undo}`.
- confirmación: `{queued: true, check_with: "ha_get_statistics_metadata"}`.

### `ha_update_statistics_metadata`

- preview: `{action, statistic_id, current: {unit_of_measurement,
  unit_class}, new: {unit_of_measurement, unit_class}, converts_values: false,
  hint: "use ha_change_statistics_unit to convert stored values"}`.
- confirmación: `{updated: true}`.

### `ha_adjust_statistics_sum`

- preview: `{action, statistic_id, from: start_time (UTC), adjustment,
  adjustment_unit, statistics_unit, sum_at_start: {before, after} | null,
  applies_to: "every row from this hour on (hourly and 5-minute)",
  repeat_warning, irreversible, undo}`.
- confirmación: `{queued: true, check_with: "ha_statistics_during_period"}`.

### `ha_import_statistics`

- preview: `{action, statistic_id, exists, current_metadata?, new_metadata,
  rows, first_start, last_start, overwritten_rows: int | null,
  overwritten_rows_reason?, recorded_entity_warning?, irreversible, undo}`.
- confirmación: `{queued: true, rows}`.

### `ha_get_energy_prefs`

`{configured, energy_sources: [...], device_consumption: [...],
device_consumption_water: [...]}` como los da HA, redactado.

### `ha_update_energy_prefs`

- preview: `{action, changes: {<lista>: {before_count, after_count, added:
  [...], removed: [...], changed: [...]}}, kept: [<listas que no llegan>],
  removes_all_sources: bool, warnings: [{statistic_id, problem:
  "unknown_statistic"}], current: {<listas que cambian, como están>}}`.
  Cada elemento de `added`/`removed`/`changed` es un resumen: `type` (fuentes)
  y sus `stat_*`.
- confirmación: `{saved: true, prefs: {…lo que devolvió HA}}`.

## Errores

| Código | Cuándo |
|---|---|
| `invalid_argument` | forma de ids, fechas sin zona o fuera de hora en punto, rango incompleto o invertido, `adjustment` 0 o no finito, `mean_type` fuera de 0–2, fuente que no casa, filas repetidas o más de 5000, listas de energía mal formadas, ninguna lista en energía — sin llamar a HA |
| `statistics_not_found` | ids que HA no conoce (borrar, unidad, metadatos, ajustar), con la lista |
| `not_supported_for_source` | cambiar la unidad de una estadística cuya fuente no es `recorder` |
| `unit_mismatch` | `old_unit` no es la unidad guardada (con la actual) |
| `statistic_has_no_sum` | ajustar una estadística sin suma |
| `recorder_not_loaded` | `unknown_command` en un comando del recorder |
| `energy_not_loaded` | `unknown_command` en `energy/*` |
| `ha_timeout` | `timeout` de HA en borrar o metadatos (puede seguir en la cola) |
| `ha_command_failed` | otro error de HA (`invalid_units`, `invalid_format`, `home_assistant_error`…), redactado, con `ha_code` y `table_ha_core` |
| `response_too_large` | un documento que no cabe en el tope |
| errores de token | los de `resolve_confirmation_token` (`does not match`, caducado, usado, `ESTADO_CAMBIADO`) |
