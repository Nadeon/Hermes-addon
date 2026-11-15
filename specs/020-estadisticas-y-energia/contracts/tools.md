# Contratos de las tools (020)

Descripciones al cliente en inglés (como todas); aquí, lo que cada una tiene
que decir y hacer. Todas: `@ready`, validación antes de llamar a HA,
`redact_structure` + `redact_secrets`, tope de respuesta, log sin ids ni
valores. Las seis que modifican: dos pasos SIEMPRE (sin token → vista previa,
nada cambia; con token → ejecuta), token atado a los argumentos y al `estado`.

## Familia `recorder` (módulo nuevo `tools/statistics_maintenance.py`)

### `ha_clear_statistics(statistic_ids: list[str], start_time: str | None = None, end_time: str | None = None, confirmation_token: str | None = None)`

Delete long-term statistics: whole statistics (rows and metadata) or only the
rows that overlap a time range. Cannot be undone except by restoring a backup.
- 1–100 ids (`dominio.objeto` o `fuente:objeto`); repetidos se quitan.
- `start_time`/`end_time`: los dos o ninguno; ISO 8601 con zona; inicio < fin.
- Comprueba con `recorder/get_statistics_metadata` → `statistics_not_found`.
- Vista previa: data-model. Confirmación: `recorder/clear_statistics` con los
  ids y, si hay rango, las fechas en UTC; HA espera al recorder (10 s).

### `ha_change_statistics_unit(statistic_id: str, old_unit: str | None, new_unit: str | None, confirmation_token: str | None = None)`

Convert every stored value of a recorder statistic to another unit of the same
unit class (e.g. Wh → kWh) and change its unit. Only statistics whose source is
`recorder`; `old_unit` must be the current unit.
- Rechaza `not_supported_for_source`, `unit_mismatch`, `statistics_not_found`;
  misma unidad vieja y nueva → `invalid_argument`.
- Confirmación: `recorder/change_statistics_unit` (claves
  `new_unit_of_measurement`, `old_unit_of_measurement`); responde
  `queued: true`: HA lo aplica desde la cola del recorder.

### `ha_update_statistics_metadata(statistic_id: str, unit_of_measurement: str | None, unit_class: str | None, confirmation_token: str | None = None)`

Change the stored unit and unit class of a statistic WITHOUT converting its
values (fixes a "units changed" issue when the values are already right). To
convert values use `ha_change_statistics_unit`.
- Los dos argumentos obligatorios (pueden ser `null`).
- Confirmación: `recorder/update_statistics_metadata` con `unit_class`
  siempre; HA espera al recorder (10 s).

### `ha_adjust_statistics_sum(statistic_id: str, start_time: str, adjustment: float, adjustment_unit: str | None, confirmation_token: str | None = None)`

Add `adjustment` (in `adjustment_unit`, converted by Home Assistant) to the
sum of every row from `start_time` on. Calling it twice adds twice.
- `statistic_has_no_sum`, `statistics_not_found`; `adjustment` finito ≠ 0.
- Confirmación: `recorder/adjust_sum_statistics` (`start_time` en UTC ISO,
  `adjustment_unit_of_measurement`); `queued: true`.

### `ha_import_statistics(metadata: dict, stats: list[dict] | None = None, confirmation_token: str | None = None)`

Import hourly long-term statistics (insert or overwrite rows with the same
start) and create or update the statistic's metadata.
- `metadata`: `statistic_id`, `source`, `name`, `unit_of_measurement`,
  `unit_class`, `mean_type` (0 none, 1 arithmetic, 2 circular), `has_sum`;
  claves desconocidas → `invalid_argument`.
- `stats`: 1–5000 filas `{start, mean?, min?, max?, state?, sum?,
  last_reset?}`; `start` con zona y en hora en punto, sin repetidos.
- `stats` omitible al confirmar (`omitibles=("stats",)`): obligatorio en la
  vista previa.
- Confirmación: `recorder/import_statistics` con `metadata` (sin `has_mean`:
  `mean_type` manda) y `stats` en UTC; `queued: true`.

## Familia `energy` (módulo nuevo `tools/energy.py`)

### `ha_get_energy_prefs()`

Read the energy dashboard configuration: energy sources (grid, solar,
battery, gas, water, home), individual electricity devices and water devices.
Read only. `configured: false` when it was never set up.

### `ha_update_energy_prefs(energy_sources: list | None = None, device_consumption: list | None = None, device_consumption_water: list | None = None, confirmation_token: str | None = None)`

Save the energy dashboard configuration. Each list you pass REPLACES that
whole list in Home Assistant; lists you do not pass are kept. Read the
current lists with `ha_get_energy_prefs`, edit them and pass them complete.
- Al menos una lista; forma básica: listas de objetos; fuentes con `type` en
  `grid|solar|battery|gas|water|home`; dispositivos con `stat_consumption`.
- Vista previa con diferencias y avisos (data-model); el esquema completo lo
  valida HA al guardar (`invalid_format` → `ha_command_failed`).
- Confirmación: `energy/save_prefs` solo con las listas recibidas; devuelve
  lo que HA guardó.

## Por la tabla (sin tool nueva)

- `ha_call_ws_command(type="recorder/update_statistics_issues")` — `confirm`
  (token de la genérica).
- `ha_read_ws_command(type="energy/validate" | "energy/info" |
  "energy/solar_forecast")` sin carga; `energy/fossil_energy_consumption` con
  la carga del `example`.

## Rechazos de la genérica (sin cambiar código de la 011)

`ha_read_ws_command`/`ha_call_ws_command` con cualquiera de los siete
comandos `dedicated` → `use_dedicated_tool` con su tool, sin llegar a HA;
con la familia desactivada, además `family_disabled: true`.
