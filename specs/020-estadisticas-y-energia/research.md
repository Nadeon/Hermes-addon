# Research: estadísticas y energía (020)

Todo lo de Home Assistant está leído en el código de Core 2026.11.1 (carpeta
`fuentes`, solo lectura); lo de Hermes, en la rama
`feat/020-estadisticas-y-energia` (base `c4a57bf`). No se ha llamado a ninguna
tool de Hermes ni ejecutado nada de HA.

## R-0 — Punto de partida en Hermes

- **Tabla** (`command_table.py`): los doce comandos de CAP-050 y CAP-054 que
  el inventario marca clase A están en `deny` «pendiente de tool dedicada
  (spec 020)» con familia `generic_commands`:
  `recorder/{adjust_sum_statistics, change_statistics_unit,
  clear_statistics, import_statistics, update_statistics_issues,
  update_statistics_metadata}` y `energy/{fossil_energy_consumption,
  get_prefs, info, save_prefs, solar_forecast, validate}`. Ya `dedicated` (029 y 1.1.2) y que no se tocan:
  `recorder/info`, `recorder/entity_options/get`,
  `recorder/validate_statistics`, `recorder/get_statistics_metadata`,
  `recorder/list_statistic_ids`, `recorder/statistics_during_period`;
  `recorder/statistic_during_period` es `read`.
- **Familia `recorder`** (029): módulo `recorder_status`, descripción «…
  (read only)». El comentario de `tool_families.py` y el docstring de
  `recorder_status.py` ya dicen que la 020 añade aquí el mantenimiento y que
  entonces la descripción deja de decir «read only».
- **Matriz del generador** (`scripts/inventario/generar_tabla.py`, `MATRIZ`):
  `CAP-050: ("D", "020", "020")` y `CAP-054: ("D+T", "020", "020")`.
- **Test de la clase A** (`tests/test_command_table.py`,
  `test_clase_a_de_via_dedicada_pendiente_de_su_spec`): para una CAP de vía
  D/D+T/D+X admite `dedicated` hacia una tool de una familia de la 1.2.0, o
  `read`/`confirm` solo si la clave está en `_POR_LA_TABLA` con «spec NNN: …»
  y NNN entre las sub-features de esa CAP. Es el camino de las cuatro lecturas
  de energía y de `update_statistics_issues`.
- **Confirmación** (`security.py`): `create_confirmation_token(tool, args,
  preview, *, omitibles, estado)` y `resolve_confirmation_token(…, omitibles,
  estado)`. `estado` (018) ata el token a una huella del objetivo leído en la
  vista previa y da `ESTADO_CAMBIADO` si difiere; `omitibles` deja omitir un
  documento grande al confirmar (Lovelace).
- **Inventarios transversales**: `tests/test_confirmation_args_inventory.py`
  (033), `tests/test_banco_cobertura_escrituras.py` (028, con
  `cobertura_<NNN>.py` por sub-feature), `tests/test_matriz_pruebas.py` (014),
  `tests/test_allow_dangerous_inventario.py` (018; no aplica: ninguna tool de
  la 020 llama a servicios), `tests/test_sobre_de_lista.py` (018; no aplica:
  ninguna tool nueva es de lista).

## R-1 — Qué hace HA con cada comando de CAP-050

`components/recorder/websocket_api.py` y `statistics.py`:

| Comando | Admin | Esquema | Qué hace | ¿Espera? |
|---|---|---|---|---|
| `clear_statistics` | sí | `statistic_ids: [str]`; `start_time` y `end_time` inclusivos (los dos o ninguno), `cv.datetime` | Sin rango: borra los metadatos (y en cascada las filas) de cada id (`statistics_meta_manager.delete`). Con rango: `start_time >= end_time` → `invalid_time_range`; borra de `StatisticsShortTerm` y `Statistics` las filas con `start_ts > start_time - duración` y `start_ts < end_time`, es decir, **las que se solapan** con el rango. | Sí, hasta 10 s (`CLEAR_STATISTICS_TIME_OUT`); si vence, `timeout` |
| `update_statistics_metadata` | sí | `statistic_id`, `unit_of_measurement` (str/None) obligatorios; `unit_class` (str/None) opcional, sin él avisa de obsoleto («dejará de funcionar en 2026.11») | Cambia unidad y clase guardadas; no convierte valores. `unit_class` desconocida o unidad no válida para la clase → `HomeAssistantError` | Sí, 10 s (`UPDATE_STATISTICS_METADATA_TIME_OUT`) |
| `change_statistics_unit` | sí | `statistic_id`, `new_unit_of_measurement`, `old_unit_of_measurement` (str/None) | Comprueba que haya metadatos (`No metadata found`) y que se pueda convertir; **encola**. En la cola, si `source != "recorder"` o la unidad guardada no es `old_unit`, **solo avisa en el log y no hace nada**; si no, convierte `mean, min, max, state, sum` de las dos tablas y cambia la unidad | No |
| `adjust_sum_statistics` | sí | `statistic_id`, `start_time` (str), `adjustment` (número), `adjustment_unit_of_measurement` (str/None) | `start_time` inválido → `invalid_start_time`; id desconocido → `unknown_statistic_id`; unidades no convertibles → `invalid_units`. **Encola**: suma `adjustment` (convertido a la unidad de la estadística) a `sum` de toda fila con `start_ts >= start_time` (5 minutos) y `>= start_time` con minutos a 0 (horaria). Con `sum` nulo no cambia nada | No |
| `import_statistics` | sí | `metadata` {`has_mean`?, `mean_type`? (0/1/2), `has_sum`, `name`, `source`, `statistic_id`, `unit_class`?, `unit_of_measurement`}; `stats`: [{`start`, `mean`?, `min`?, `max`?, `last_reset`?, `state`?, `sum`?}] | Id `dominio.objeto` → fuente tiene que ser `recorder`; id `fuente:objeto` → fuente = dominio. Fechas con zona y en hora en punto (si no, `HomeAssistantError`). **Encola** un import que inserta o actualiza filas por `start` y actualiza los metadatos. Sin `mean_type`/`unit_class`, aviso de obsoleto | No (handler `@callback`) |
| `update_statistics_issues` | no | sin argumentos | Ejecuta en un hilo la actualización de avisos de Repairs de las plataformas del recorder (sensor). No toca filas ni metadatos | Sí |

Consecuencias para Hermes: (a) las vistas previas no pueden confiar en que HA
rechace lo que no hará: comprobar antes con `recorder/get_statistics_metadata`
(existe, fuente, unidad, suma); (b) las tres que encolan devuelven
`queued: true` y la guía dice cómo comprobarlo; (c) siempre `unit_class` y
`mean_type`.

## R-2 — Comprobaciones previas y estado atado al token

Antes de emitir el token, cada tool lee los metadatos de lo que toca
(`recorder/get_statistics_metadata` con sus ids). Eso da:

- `statistics_not_found` (borrar, cambiar unidad, metadatos, ajustar): HA no
  falla con un id inexistente en borrar ni en metadatos; confirmar una errata
  daría «ok» sin hacer nada.
- `not_supported_for_source` y `unit_mismatch` (cambiar unidad), y
  `statistic_has_no_sum` (ajustar): HA respondería éxito sin hacer nada.
- El **estado** para `create_confirmation_token(…, estado=…)`: la lista de
  metadatos leída. Si entre la vista previa y la confirmación la estadística
  cambia de unidad, desaparece o aparece (importar), la confirmación vuelve a
  leerlos y `resolve_confirmation_token` responde `ESTADO_CAMBIADO`.

Alternativas descartadas: confiar en el error de HA (no lo hay en los casos
de arriba); emitir el token sin leer (vista previa que no dice lo que hará).

## R-3 — `update_statistics_issues` por la tabla

No está en FR-069 ni el research de la 008 le da tool. No toca datos: vuelve
a calcular qué avisos de Repairs de estadísticas deben existir. Se clasifica
`confirm` (la genérica de escritura pide token; la acción crea o borra avisos,
que es modificar), con su clave en `_POR_LA_TABLA`. Una tool dedicada sería
una tool sin argumentos y sin vista previa útil. Se prueba en el banco por
`ha_call_ws_command` (que ya está en `PROBADAS_GENERICAS`). Duda D-3 por si el
programa prefiere tool.

## R-4 — Vistas previas: qué se puede decir sin mentir

- **Borrar con rango**: el periodo efectivo sale de la consulta de HA, no de
  contar filas: horaria `(start_time - 1 h, end_time)` y de 5 minutos
  `(start_time - 5 min, end_time)`, abiertos. Se da el pedido y el efectivo
  en UTC. No se cuentan filas: con un histórico de años, contar exigiría leer
  todo; la vista previa dice qué ids y qué periodo, que es lo que pide el
  programa.
- **Borrar sin rango**: «la estadística entera: todas sus filas y sus
  metadatos; desaparece de las listas». Es lo que hace `delete` de los
  metadatos.
- **Ajustar la suma**: la suma actual en la hora de `start_time` se lee con
  `recorder/statistics_during_period` (`period: "hour"`, `types: ["sum"]`,
  esa hora) y se da con la que quedará si las unidades coinciden; si la
  unidad del ajuste es otra, se da el ajuste tal cual y que HA lo convierte.
- **Importar**: la estadística existe o no (metadatos), el rango de `stats`, el
  número de filas y, si el rango es de 31 días o menos, cuántas filas de ese
  rango ya existen (lectura horaria acotada: como mucho 744 filas por id);
  si es mayor, `overwritten_rows: null` con el motivo. Si el id es de una
  entidad que el recorder está grabando, aviso: el recorder sigue
  compilando sus estadísticas y puede pisar lo importado en las horas nuevas.
- Todas dicen `irreversible: true` y «solo se deshace restaurando un backup»
  (el de HA incluye la base del recorder).

## R-5 — Energía

`components/energy/websocket_api.py` y `data.py`:

- `energy/get_prefs` (no admin): `manager.data` o `not_found` «No prefs» si
  nunca se guardaron.
- `energy/save_prefs` (admin): claves opcionales `energy_sources`
  (`ENERGY_SOURCE_SCHEMA`: lista con `type` en `grid`, `solar`, `home`,
  `battery`, `gas`, `water`, más límites por tipo y unicidad de estadísticas de
  la red), `device_consumption` y `device_consumption_water`
  (`stat_consumption` obligatorio; `stat_rate`, `name`, `included_in_stat`).
  `EnergyManager.async_update` **reemplaza cada lista recibida y conserva las
  demás**, rellena `stat_rate` de las fuentes con `power_config`, guarda con
  `async_delay_save(…, 60)` (a disco hasta 60 s después; la memoria se
  actualiza al momento) y avisa a sus oyentes (sensores de coste). Devuelve
  `manager.data`.
- `energy/info`: `cost_sensors` y `solar_forecast_domains`.
- `energy/validate`: problemas por fuente y dispositivo (`as_dict()`).
- `energy/solar_forecast`: previsiones de las config entries de previsión
  solar configuradas en las fuentes solares (`{}` si ninguna); lee lo que la
  integración ya tiene.
- `energy/fossil_energy_consumption`: `start_time`, `end_time` (str),
  `energy_statistic_ids` ([str]), `co2_statistic_id` (str), `period`
  (`5minute`, `hour`, `day`, `month`). Solo lee estadísticas.

Decisiones: tres argumentos opcionales (no un `prefs` único) para que la
firma diga la semántica de HA; vista previa con diferencias por lista,
identificando cada elemento por su `type` y sus `stat_*` (los nombres son
opcionales); `estado` = preferencias actuales (si alguien guarda desde la
interfaz entre medias, `ESTADO_CAMBIADO`); sin omitibles (el documento es de
pocos KB). La comprobación de estadísticas inexistentes es un aviso, no un
rechazo: el panel admite estadísticas que aún no tienen datos.

Las cuatro lecturas quedan `read` sin `open_world`: ninguna sale de la
instalación (la previsión solar devuelve lo que la integración ya descargó).

## R-6 — Familias, anotaciones y guía

- `recorder`: módulo nuevo `statistics_maintenance` junto a
  `recorder_status`; descripción «Recorder status and long-term statistics:
  validation, metadata and maintenance (clear, change units, adjust sums,
  import; with confirmation).» Quien apaga `recorder` apaga lectura y
  mantenimiento, como anunció la 029.
- `energy`: familia nueva `desde="1.2.0"`, desactivable, «Energy dashboard
  preferences: read and save (with confirmation).»
- Anotaciones: los prefijos no clasifican bien (`ha_clear_`, `ha_change_`,
  `ha_adjust_`, `ha_import_`, `ha_update_` no son destructivos por prefijo):
  cinco a `_DESTRUCTIVE_EXACT` con el porqué; `ha_adjust_statistics_sum`
  también a `_NON_IDEMPOTENT_EXACT`. `ha_import_statistics` es idempotente
  (reimportar las mismas filas deja el mismo estado).
- Guía: el tema `recorder` (de la 029; no tiene huella en
  `_HUELLAS_ANTES_DE_LA_013`) se reescribe en parte; tema nuevo `energy` con
  alias `energy_prefs`, `energy_dashboard`, `energia`; el alias `statistics`
  sigue en `data` (huella de la 1.1.2 intacta).

## R-7 — Banco de Core

- `tests/banco/ha_config/configuration.yaml` ya carga `recorder:`,
  `frontend:` y `kitchen_sink:`. Se añade `energy:` (depende de `frontend`;
  sin red ni hardware). `kitchen_sink` importa estadísticas externas
  (`kitchen_sink:energy_consumption_kwh`…), útiles como referencia de lectura,
  pero los tests de la 029 las leen: **no se modifican**.
- El lector siembra con `recorder/import_statistics` directo a Core sus
  estadísticas (`sensor.banco_<sufijo>_…` con `source: recorder`, para poder
  cambiar la unidad; y `banco:<sufijo>_…` externas), espera a verlas con
  `recorder/statistics_during_period` (el import va por la cola) y las borra
  al final con `recorder/clear_statistics`.
- Efectos que comprueba el lector: borrar con rango (solo desaparecen esas
  horas), borrar entera (desaparece de `list_statistic_ids`), cambiar unidad
  (valores ×1000 y unidad nueva), metadatos (unidad nueva, valores iguales),
  ajustar (suma +x desde la hora), importar (filas nuevas), energía
  (`energy/get_prefs` antes y después, y restaurar al final). La vista previa
  de cada una se comprueba sin efecto.
- `update_statistics_issues` por la genérica (el lector comprueba que
  `repairs/list_issues` responde; el efecto concreto depende de qué avisos
  tenga el banco) y las cuatro lecturas de energía por la genérica.
- Nada queda sin probar: `NO_EJECUTABLES_020` vacío.

## R-8 — Log y privacidad

Igual que la 029: el log lleva nombre de la tool, paso, resultado y
recuentos. Ni ids de estadísticas (dicen qué hay en la casa), ni nombres de
entidades, ni valores, ni el documento de energía. Fixtures con
`sensor.consumo`, `sensor.solar`, `banco:importada`, `centinela-020`.
