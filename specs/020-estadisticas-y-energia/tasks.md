---
description: "Tareas de la sub-feature 020 — estadísticas y energía (Hermes 1.2.0)"
---

# Tareas: estadísticas y energía (020)

**Entrada**: `specs/020-estadisticas-y-energia/` (spec.md, plan.md,
research.md, data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `DummyMCP` o
`_RecordingMCP`, `AsyncMock` de `ws_send` que responde por `type` de comando
(y registra lo enviado), `structlog.testing.capture_logs`, tokens reales de
`security.py` con `HERMES_CONFIG_BASE` propio (como los tests de Lovelace).
Datos ficticios (`sensor.consumo`, `sensor.solar`, `banco:importada`,
`centinela-020`). Nada de la instalación real ni de las tools MCP de Hermes.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`.
Línea base en Windows al especificar (2026-11-15, punta `c4a57bf`): 2926
passed, 95 skipped, 6 failed (los 6 conocidos). Cada tramo termina con
exactamente esos 6 fallos en local; la referencia es el CI de Linux.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 borrar, US2 unidades y metadatos, US3 sumas, US4
importar, US5 energía, US6 nada se rompe.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado (uno o varios commits; el tramo no se cierra con la suite en rojo).

| Tramo | Tareas | Cubre |
|---|---|---|
| 1 | T001–T020 | `ha_clear_statistics`, `ha_change_statistics_unit`, `ha_update_statistics_metadata`, el ayudante común, el inventario del banco de la 020 |
| 2 | T021–T035 | `ha_adjust_statistics_sum`, `ha_import_statistics`, `update_statistics_issues` por la tabla |
| 3 | T036–T052 | familia `energy`, `ha_get_energy_prefs`, `ha_update_energy_prefs`, cuatro lecturas por la tabla, documentación final |

---

## Tramo 1 — Borrar, cambiar la unidad y editar metadatos (US1, US2, US6)

### Preparación

- [ ] T001 Comprobar la base: `tools/recorder_status.py` y la familia `recorder` (029), `tests/banco/cobertura_012.py` y `cobertura_escrituras.py` (028/012), `tests/test_confirmation_args_inventory.py` (033), `tests/test_matriz_pruebas.py` (014), `estado` en `create_confirmation_token` (018). Si falta algo, parar y avisar. Línea base de la suite, anotada en el commit del tramo
- [ ] T002 [US6] En `tests/test_tools_statistics_maintenance.py`, el doble de HA del módulo: `AsyncMock` de `ws_send` que responde a `recorder/get_statistics_metadata` con metadatos configurables (`sensor.consumo`: `source: recorder`, Wh, `unit_class: energy`, `has_sum: true`; `banco:externa`: `source: banco`), a `recorder/statistics_during_period` y a cada comando de escritura, y registra lo enviado; utilidad que comprueba que un paso NO envió ningún comando de escritura

### Tests de las tools (antes del código)

- [ ] T003 [P] [US1] Tests de `ha_clear_statistics`: vista previa sin rango (`scope: "entire"`, `removes_metadata: true`, metadatos de cada id, `irreversible`, `undo`) sin enviar `recorder/clear_statistics`; con rango, `requested_range` y `effective_range` (horaria: después de `start_time - 1 h`; 5 minutos: después de `start_time - 5 min`; antes de `end_time`, en UTC); confirmación que envía los ids ordenados y sin repetir y las fechas en UTC; ids repetidos se piden una vez; id desconocido → `statistics_not_found` con la lista y sin token; 0 o 101 ids, id sin forma, solo `start_time`, `start_time >= end_time`, fecha sin zona → `invalid_argument` sin llamar a HA; `unknown_command` → `recorder_not_loaded`; `timeout` de HA → `ha_timeout` con el aviso de la cola; error de HA con `centinela-020` → redactado con `ha_code`; log capturado: paso y recuentos, ningún id ni fecha (FR-001, FR-006, FR-008, FR-017…FR-019)
- [ ] T004 [P] [US2] Tests de `ha_change_statistics_unit`: vista previa con unidad y clase actuales y nuevas, `converts` y `tables`, sin enviar el comando; confirmación con `new_unit_of_measurement`/`old_unit_of_measurement` → `queued: true` y `check_with`; `source` distinto de `recorder` → `not_supported_for_source`; `old_unit` distinto de la guardada → `unit_mismatch` con la actual; `old_unit == new_unit` → `invalid_argument`; id desconocido → `statistics_not_found`; ninguno de los tres emite token; log sin ids ni unidades (FR-002, FR-006, FR-008, FR-018)
- [ ] T005 [P] [US2] Tests de `ha_update_statistics_metadata`: vista previa con `current` y `new` y `converts_values: false`; confirmación que envía SIEMPRE `unit_class` (también `null`) → `updated: true`; id desconocido → `statistics_not_found`; `timeout` → `ha_timeout`; `unknown_command` → `recorder_not_loaded`; `invalid_format`/`home_assistant_error` de HA → `ha_command_failed` con `ha_code` y `table_ha_core` (FR-003, FR-006, FR-008, FR-019)
- [ ] T006 [P] [US1] [US2] Tests del token en las tres: confirmar cambiando cualquier argumento (otro id, otro rango, sin rango, otra unidad, otra clase) → «does not match» y nada enviado; metadatos distintos al confirmar (unidad cambiada, estadística borrada) → `ESTADO_CAMBIADO` y nada enviado; token usado dos veces → rechazado; fechas equivalentes en otra zona (`+02:00` y `Z`) atan lo mismo (normalización) (FR-007, SC-003)
- [ ] T007 [P] [US6] Tests en `tests/test_tool_families.py` (familia `recorder` con los módulos `recorder_status` y `statistics_maintenance`; su descripción ya no contiene «read only» y nombra el mantenimiento) y en `tests/test_tools_registration.py` (las tres en `_HINTS_NUEVAS_1_2_0` con `-DI-` y su título; las tres toman `confirmation_token`; con `recorder` desactivada no aparece ninguna de las seis de la familia). Actualizar a la vez los tests de la 029 que fijan la familia: `test_recorder_es_de_la_1_2_0` (`modulos`) y `TestRecorderRegistration` (`test_desactivada_no_registra_ninguna` y `test_sin_las_dos_familias_es_la_lista_de_antes_de_la_029` restan también las de la 020), con un comentario que lo explique (FR-014, FR-016, SC-001)

### Implementación

- [ ] T008 [US1] [US2] `hermes/src/hermes/tools/statistics_maintenance.py`: ayudante común (plan.md, «Patrón común») y las tres tools de contracts/tools.md, reutilizando `_STATISTIC_ID_RE`, `_con_forma` y `_error_ha` de `recorder_status.py` (sin cambiarlos); descripciones en inglés que dicen qué borran o cambian, que solo un backup lo deshace y `queued` donde HA encola; comentarios del porqué (R-1, R-2). T002–T006 en verde (FR-001…FR-003, FR-006…FR-008, FR-017…FR-019)
- [ ] T009 [US1] [US2] `tests/test_confirmation_args_inventory.py`: filas de las tres (data-model, «Inventario de argumentos atados»), recuento del docstring actualizado; el test en verde (FR-007)
- [ ] T010 [US6] `tool_families.py` (módulo y descripción nueva de `recorder`, comentario que retira el «read only»), `tools/__init__.py` (registro bajo `if _activa("recorder")`), `tools/_annotations.py` (las tres en `_DESTRUCTIVE_EXACT` con el porqué y en `_HINTS_NUEVAS_1_2_0`). T007 en verde y el invariante «destructiva ⇒ token» también (FR-014, FR-016)

### Tabla

- [ ] T011 [P] [US6] Tests en `tests/test_tools_generic_commands.py`: `ha_call_ws_command` y `ha_read_ws_command` con `recorder/clear_statistics`, `recorder/change_statistics_unit` y `recorder/update_statistics_metadata` → `use_dedicated_tool` con su tool y sin `ws_send`; con `recorder` desactivada → `family_disabled: true` (FR-015)
- [ ] T012 [US6] `command_table.py`: las tres a `E("dedicated", "cubierto por <tool>", "recorder", tool=…, cap="CAP-050")`; sus claves en `_DEDICADAS_INICIALES` de `scripts/inventario/generar_tabla.py` (bloque comentado «020»); ejecutar el generador y comprobar que `git diff -- hermes/src/hermes/command_table.py` no cambia nada respecto a la edición a mano; anotarlo en el commit. T011, `tests/test_command_table.py` y `tests/test_generar_tabla.py` en verde (FR-015)

### Guía

- [ ] T013 [US1] [US2] Tests en `tests/test_tools_guide.py`: el tema `recorder` nombra las tres tools nuevas, explica dos pasos, `queued`, la diferencia entre cambiar la unidad (convierte) y editar metadatos (no convierte) y que solo un backup deshace; ya no dice que todo el tema es de solo lectura (el test de la 029, `test_tema_con_contenido`, busca «SOLO LECTURA»: la frase se queda para el grupo de las tres lecturas o el test se actualiza, sin perder lo que comprueba); las huellas de `_HUELLAS_ANTES_DE_LA_013` no cambian (el tema `data` tampoco) (FR-020)
- [ ] T014 [US1] [US2] `hermes/src/hermes/tools/guide.py`: tema `recorder` ampliado (en español, como los demás) y línea del índice. T013 en verde (FR-020)

### Banco de Core

- [ ] T015 [US1] [US2] `tests/banco/test_banco_estadisticas.py` (marcador `banco`, helpers de la 010/028): siembra del lector con `recorder/import_statistics` directo a Core (`sensor.banco_<sufijo>_energia`, `source: recorder`, kWh, `unit_class: energy`, `mean_type: 0`, `has_sum: true`, 24 filas horarias de hace dos días; y una externa `banco:<sufijo>_externa`), esperando a verla con `recorder/statistics_during_period`, y borrado al final. Casos: (a) `ha_clear_statistics` con rango de 3 horas: vista previa sin efecto (el lector ve las 24 filas), confirmación → el lector ve 21 o menos y ninguna dentro del rango efectivo; sin rango sobre la externa → desaparece de `recorder/list_statistic_ids`; (b) `ha_change_statistics_unit` kWh→Wh: vista previa sin efecto; confirmación → el lector ve unidad `Wh` y la suma ×1000 (sondeo con plazo); sobre la externa → `not_supported_for_source`; (c) `ha_update_statistics_metadata` a `MWh`/`energy`: el lector ve la unidad nueva y los mismos valores. Si algo falla en HA real, `xfail` estricto con ese fallo concreto y anotado como hallazgo (FR-006, FR-021, SC-003, SC-005)
- [ ] T016 [US6] `tests/banco/cobertura_020.py` (docstring con el contrato de la 028): `PROBADAS_020` con las tres y `NO_EJECUTABLES_020 = {}`; sumarlas a `_listas()` de `tests/test_banco_cobertura_escrituras.py` y `PROBADAS_020` a `TOOLS_EXIGIDAS_DEL_JOB` de `tests/banco/cobertura_escrituras.py`; `MODULOS_020 = ("statistics_maintenance", "energy")` en `cobertura_020.py` y, en `TestCoberturaDeLa029.test_modulos_de_las_familias_de_la_029` de `tests/test_banco_cobertura.py`, restar `MODULOS_020` de los módulos de las familias (si no, cae al añadir `statistics_maintenance` a `recorder`); `test_inventario_exacto` sigue igual (lista los módulos de la 029) (FR-021)
- [ ] T017 [US6] `docs/HOJA-DE-RUTA.md`, matriz de pruebas (entre los marcadores `matriz-pruebas`): tres filas `banco de Core` / `ok`. `tests/test_matriz_pruebas.py` en verde (FR-021, FR-022)
- [ ] T018 [US6] Ejecutar `tests/test_banco_cobertura_escrituras.py`, `tests/test_matriz_pruebas.py`, `tests/test_confirmation_args_inventory.py` y `tests/test_command_table.py` juntos: verde

### Cierre del tramo 1

- [ ] T019 Control negativo del tramo 1, anotando recuentos: (a) quitar `end_time` del dict del token de `ha_clear_statistics` → cae T006; (b) no pasar `estado` → cae el de `ESTADO_CAMBIADO`; (c) quitar la comprobación de `source` → cae el de `not_supported_for_source`; (d) enviar el comando en la vista previa → cae la utilidad de T002; (e) no redactar el error de HA → cae el centinela; (f) registrar los ids en el log → cae el de log; (g) dejar `recorder/clear_statistics` en `deny` → cae T011; (h) quitar una de `PROBADAS_020` → cae `test_banco_cobertura_escrituras.py`; (i) quitar su fila de la matriz → cae `test_matriz_pruebas.py`. Restaurar y comprobar verde
- [ ] T020 Documentación parcial y cierre: recuento de tools (+3) y filas de la familia en `README.md`, `README.es.md` y `hermes/DOCS.md` (`TestToolCountInDocs`; descripción nueva de `recorder`); sección «Estadísticas y energía» en `## [1.2.0]` de `hermes/CHANGELOG.md` con lo del tramo (incluido el cambio del tema `recorder` y de la descripción de la familia); 020 «en curso» en la tabla del programa de `docs/HOJA-DE-RUTA.md`; suite completa (los 6 fallos conocidos y ninguno más); revisión del diff (principio VIII, sin identificadores de modelos); commit en español con la línea base de T001, el resultado de T012 y los recuentos de T019 (FR-022)

---

## Tramo 2 — Ajustar sumas, importar y avisos (US3, US4, US6)

### Tests de las tools (antes del código)

- [ ] T021 [P] [US3] Tests de `ha_adjust_statistics_sum` (doble de T002): vista previa con `from` en UTC, ajuste y unidades, `sum_at_start` leído con `recorder/statistics_during_period` (`period: "hour"`, `types: ["sum"]`, esa hora; `before` y `after` si las unidades coinciden, solo `before` si no; `null` sin fila), `repeat_warning`; sin enviar el comando; confirmación con `adjustment_unit_of_measurement` → `queued: true`; `has_sum: false` → `statistic_has_no_sum`; id desconocido → `statistics_not_found`; `adjustment` 0, NaN o infinito, fecha sin zona → `invalid_argument`; `invalid_units` de HA → `ha_command_failed` con `ha_code`; log sin ids ni valores (FR-004, FR-006, FR-008, FR-017, FR-018)
- [ ] T022 [P] [US4] Tests de `ha_import_statistics`: vista previa con `exists`, metadatos actuales y nuevos, `rows`, `first_start`, `last_start` y `overwritten_rows` (contadas con una lectura horaria del rango cuando es ≤ 31 días; `null` con `overwritten_rows_reason` si es mayor); aviso `recorded_entity_warning` si el id es de una entidad que existe; confirmación que envía `metadata` con `mean_type` y `unit_class` y sin `has_mean`, y `stats` en UTC ordenado → `queued: true`; `invalid_argument` sin llamar a HA con: `start` sin zona o con minutos, filas repetidas, 0 o 5001 filas, valor no finito, `mean_type` 3, clave desconocida en `metadata` o en una fila, `source` que no casa (`sensor.x` con `banco`; `banco:x` con `otra`), falta una clave obligatoria (FR-005, FR-006, FR-017)
- [ ] T023 [P] [US3] [US4] Tests del token en las dos: cambiar `adjustment`, su unidad o `start_time` → «does not match»; `ha_import_statistics` confirmada sin `stats` → usa lo guardado (`omit_on_confirm`, `confirm_hint`); con `stats` distinto (una fila cambiada) → «does not match»; metadatos cambiados entre medias → `ESTADO_CAMBIADO`; tope de `stored_args` lleno → la confirmación sin `stats` se rechaza pidiendo reenviarlo (FR-005, FR-007, SC-003)

### Implementación

- [ ] T024 [US3] [US4] `statistics_maintenance.py`: las dos tools de contracts/tools.md con el ayudante del tramo 1 (`omitibles=("stats",)` en la importación); descripciones en inglés (repetir el ajuste suma dos veces; la importación sobrescribe filas con la misma hora). T021–T023 en verde (FR-004…FR-008, FR-017, FR-018)
- [ ] T025 [US3] [US4] `_annotations.py`: las dos en `_DESTRUCTIVE_EXACT`, `ha_adjust_statistics_sum` también en `_NON_IDEMPOTENT_EXACT` (con el porqué), y en `_HINTS_NUEVAS_1_2_0` (`-D--` y `-DI-`); tests en `tests/test_tools_registration.py` primero (FR-016)
- [ ] T026 [US3] [US4] `tests/test_confirmation_args_inventory.py`: filas de las dos (`stats` atado y omitible) y recuento (FR-007)

### Tabla

- [ ] T027 [P] [US6] Tests: en `tests/test_tools_generic_commands.py`, `recorder/adjust_sum_statistics` e `recorder/import_statistics` → `use_dedicated_tool`; `ha_call_ws_command("recorder/update_statistics_issues")` da vista previa con token y, al confirmar, lo envía sin carga; `ha_read_ws_command` con él → rechazado por ser `confirm`. En `tests/test_command_table.py`, `recorder/update_statistics_issues` en `_POR_LA_TABLA` con «spec 020: …» (research R-3) (FR-009, FR-015)
- [ ] T028 [US6] `command_table.py`: las dos a `dedicated` (familia `recorder`, CAP-050) con sus claves en `_DEDICADAS_INICIALES`; `recorder/update_statistics_issues` a `E("confirm", "<motivo de data-model>", "generic_commands", cap="CAP-050")` a mano; regenerar y comprobar que no cambia nada. T027 y los de la tabla en verde (FR-009, FR-015)

### Guía

- [ ] T029 [US3] [US4] Tests y después `guide.py`: el tema `recorder` nombra las cinco de mantenimiento, explica el ajuste (no idempotente), la importación (horas en punto, `mean_type`, fuente, `stats` omitible al confirmar) y `ha_call_ws_command(type="recorder/update_statistics_issues")` para regenerar los avisos de Repairs tras arreglar (FR-020)

### Banco de Core

- [ ] T030 [US3] [US4] `tests/banco/test_banco_estadisticas.py`: (a) `ha_adjust_statistics_sum` +5 kWh desde la hora 12 de la siembra: vista previa sin efecto; confirmación → el lector ve la suma +5 desde esa hora y la misma antes (sondeo); (b) `ha_import_statistics` de `banco:<sufijo>_importada` con 6 filas: vista previa sin efecto (no existe para el lector); confirmación → el lector ve las 6 filas y los metadatos; reimportar una fila cambiada sobrescribe; (c) `ha_call_ws_command("recorder/update_statistics_issues")` en dos pasos responde con éxito y `repairs/list_issues` del lector responde después. Limpieza con el lector (FR-009, FR-021)
- [ ] T031 [US6] `PROBADAS_020` con las dos (cinco en total); `test_banco_cobertura_escrituras.py` en verde (FR-021)
- [ ] T032 [US6] Matriz de pruebas de `docs/HOJA-DE-RUTA.md`: dos filas más; `test_matriz_pruebas.py` en verde (FR-021, FR-022)

### Cierre del tramo 2

- [ ] T033 Control negativo del tramo 2, anotando recuentos: (a) quitar `adjustment_unit` del token → cae T023; (b) no comprobar `has_sum` → cae el de `statistic_has_no_sum`; (c) aceptar `start` con minutos → cae el de T022; (d) no declarar `stats` omitible → cae el de `omit_on_confirm`; (e) quitar `ha_adjust_statistics_sum` de `_NON_IDEMPOTENT_EXACT` → cae T025; (f) dejar `update_statistics_issues` en `deny` → cae T027; (g) quitar una de `PROBADAS_020` → cae T031. Restaurar y comprobar verde
- [ ] T034 CHANGELOG (sección «Estadísticas y energía» con lo del tramo), recuento +2 en `README.md`, `README.es.md` y `hermes/DOCS.md` (FR-022)
- [ ] T035 Cierre del tramo 2: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII), commit con los recuentos de T033 y el resultado de la regeneración de T028

---

## Tramo 3 — Energía y cierre (US5, US6)

### Tests (antes del código)

- [ ] T036 [P] [US6] Tests en `tests/test_tool_families.py` (familia `energy`, `desde="1.2.0"`, desactivable, módulo `energy`, descripción de data-model) y en `tests/test_tools_registration.py` (`ha_get_energy_prefs` `R-I-` y `ha_update_energy_prefs` `-DI-` en `_HINTS_NUEVAS_1_2_0`; la segunda toma `confirmation_token`; con `energy` desactivada no aparece ninguna y el resto no cambia; con `recorder` y `energy` desactivadas, el conjunto es exactamente el de antes de la 029) (FR-014, FR-016, SC-001)
- [ ] T037 [P] [US5] Tests en `tests/test_tools_energy.py`, `ha_get_energy_prefs`: preferencias de HA devueltas con `configured: true`; `not_found` de HA → `configured: false` y tres listas vacías; `unknown_command` → `energy_not_loaded`; un secreto en un nombre → redactado; documento mayor que el tope → `response_too_large`; Core caído → error de siempre; log sin el documento (FR-010, FR-017…FR-019)
- [ ] T038 [P] [US5] Tests de `ha_update_energy_prefs`: ninguna lista → `invalid_argument`; lista que no es de objetos, fuente con `type` desconocido, dispositivo sin `stat_consumption` → `invalid_argument` sin llamar a HA; vista previa (sin enviar `energy/save_prefs`) con `changes` por lista (`before_count`, `after_count`, `added`, `removed`, `changed` identificados por `type` y `stat_*`), `kept` con las listas no recibidas, `removes_all_sources` al mandar `energy_sources: []` con fuentes, `warnings` con las estadísticas que `recorder/get_statistics_metadata` no devuelve (y el aviso de que no se pudo comprobar si el recorder no está), `current` de las listas que cambian; preferencias sin configurar → `before_count: 0`; confirmación que envía SOLO las listas recibidas y devuelve lo que HA guardó; cualquier lista distinta al confirmar → «does not match»; preferencias cambiadas por otro entre medias → `ESTADO_CAMBIADO` y nada enviado; sin preferencias en la vista previa y guardadas por otro antes de confirmar → `ESTADO_CAMBIADO` (el estado es `{"configured": false}`, no `None`); `invalid_format` de HA → `ha_command_failed` redactado; log con recuentos por lista y sin estadísticas (FR-011, FR-012, FR-017, FR-018, SC-003)

### Implementación

- [ ] T039 [US5] Revisar el doble de HA de `tests/test_tools_energy.py` contra `energy/websocket_api.py` y `data.py` (respuesta de `get_prefs`, `save_prefs` devuelve `manager.data`, `not_found` «No prefs»); anotar en el fichero de test el código de HA consultado
- [ ] T040 [US5] `hermes/src/hermes/tools/energy.py` con las dos tools de contracts/tools.md (`estado` = preferencias actuales leídas con `energy/get_prefs`; sin omitibles); descripciones en inglés (reemplaza cada lista que llega, conserva las otras; HA valida el esquema). T037 y T038 en verde (FR-010…FR-012, FR-017…FR-019)
- [ ] T041 [US6] `tool_families.py` (familia `energy`), `tools/__init__.py` (registro bajo `if _activa("energy")`), `_annotations.py` (`ha_update_energy_prefs` en `_DESTRUCTIVE_EXACT` con el porqué; las dos en `_HINTS_NUEVAS_1_2_0`). T036 en verde (FR-014, FR-016)
- [ ] T042 [US5] `tests/test_confirmation_args_inventory.py`: fila de `ha_update_energy_prefs` (tres listas atadas) y recuento (FR-012)

### Tabla

- [ ] T043 [P] [US5] [US6] Tests: en `tests/test_tools_generic_commands.py`, `energy/get_prefs` y `energy/save_prefs` → `use_dedicated_tool`; `ha_read_ws_command` con `energy/validate`, `energy/info`, `energy/solar_forecast` (sin carga) y `energy/fossil_energy_consumption` (con la carga del `example`) → se envían y vuelven redactadas; con `energy` desactivada, las dos dedicadas → `family_disabled: true`. En `tests/test_command_table.py`, las cuatro claves en `_POR_LA_TABLA` con «spec 020: …» y un test nuevo: ninguna entrada con «(spec 020)» y las doce de CAP-050/CAP-054 con la categoría de data-model (FR-013, FR-015, SC-002)
- [ ] T044 [US5] [US6] `command_table.py`: `energy/get_prefs` y `energy/save_prefs` a `dedicated` (familia `energy`, CAP-054) con sus claves en `_DEDICADAS_INICIALES`; las cuatro lecturas a `read` a mano con el motivo de data-model y el `example` de consumo fósil (revisado contra `energy/websocket_api.py`); regenerar y comprobar que no cambia nada. T043 en verde (FR-013, FR-015)

### Guía

- [ ] T045 [P] [US5] Tests en `tests/test_tools_guide.py`: tema `energy` con las dos tools, la semántica de reemplazo por lista, el ciclo leer → editar → guardar, las cuatro lecturas con su llamada exacta a `ha_read_ws_command`; alias `energy_prefs`, `energy_dashboard`, `energia` resuelven a él; el índice lo menciona; `hermes_guide(topic="generic_commands", search="fossil")` muestra el ejemplo de la tabla (FR-020)
- [ ] T046 [US5] `guide.py`: tema `energy`, alias e índice. T045 en verde (FR-020)

### Banco de Core

- [ ] T047 [US5] `tests/banco/ha_config/configuration.yaml`: `energy:` con comentario del porqué; `tests/banco/test_banco_energia.py`: el lector lee `energy/get_prefs` antes (o `not_found`); `ha_get_energy_prefs` da lo mismo; `ha_update_energy_prefs(device_consumption=[{"stat_consumption": <estadística sembrada por el lector>}])`: vista previa sin efecto (el lector ve lo de antes), confirmación → el lector ve el dispositivo y las fuentes intactas; segunda vista previa con las preferencias cambiadas por el lector entre medias → la confirmación da `ESTADO_CAMBIADO`; las cuatro lecturas por `ha_read_ws_command` responden (`fossil_energy_consumption` con una estadística sembrada y su `co2`); al final el lector restaura las preferencias de antes (FR-013, FR-021)
- [ ] T048 [US6] `cobertura_020.py`: `ha_update_energy_prefs` en `PROBADAS_020` (seis) y `LECTURAS_020 = frozenset({"ha_get_energy_prefs"})` (nombre fuera de la convención `PROBADAS*`, que es solo de escrituras) sumado a `TOOLS_EXIGIDAS_DEL_JOB`; tests de inventario en verde (FR-021, SC-005)
- [ ] T049 [US6] Matriz de pruebas: una fila más (`ha_update_energy_prefs`); documentación final: `hermes/DOCS.md` (familia `energy` en la lista de `tool_families_disabled`, recuento), `README.md` y `README.es.md` sincronizados (+2 y fila de la familia), sección «Estadísticas y energía» completa en el CHANGELOG, 020 «hecha» en la tabla del programa de `docs/HOJA-DE-RUTA.md` (FR-022)

### Cierre

- [ ] T050 Control negativo del tramo 3, anotando recuentos: (a) no pasar `estado` en energía → cae el de `ESTADO_CAMBIADO`; (b) enviar las tres listas aunque solo llegue una → cae el de «solo las listas recibidas»; (c) no tratar `not_found` → cae el de `configured: false`; (d) quitar `warnings` → cae; (e) dejar `energy/validate` en `deny` → cae T043; (f) quitar `ha_get_energy_prefs` de `LECTURAS_020` → cae el test de inventario; (g) quitar `ha_update_energy_prefs` de la matriz → cae `test_matriz_pruebas.py`. Restaurar y comprobar verde
- [ ] T051 Matriz de trazabilidad de `specs/008-cobertura-total/plan.md`: filas CAP-050 y CAP-054 con estado `X`, las tools y entradas definitivas y los ficheros de test (`test_tools_statistics_maintenance.py`, `test_tools_energy.py`, `test_tools_generic_commands.py`, `tests/banco/test_banco_estadisticas.py`, `tests/banco/test_banco_energia.py`) (FR-022)
- [ ] T052 Cierre del tramo 3: suite completa (los 6 fallos conocidos y ninguno más), CI en verde con el banco, revisión del diff (principio VIII), commit con los recuentos de T050 y el resultado de la regeneración de T044

---

## Dependencias

- Tramo 1: T001 → T002 → T003…T007 en paralelo → T008 → T009, T010; T011 → T012 (tras T008); T013 → T014; T015 tras T008 y T012; T016 → T017 → T018; T019, T020 al final.
- Tramo 2 (tras el tramo 1): T021…T023 en paralelo → T024 → T025, T026; T027 → T028; T029; T030 tras T024 y T028; T031, T032; T033…T035 al final.
- Tramo 3 (tras el tramo 2, por los ficheros compartidos): T036…T038 en paralelo, T039 → T040 → T041, T042; T043 → T044; T045 → T046; T047 tras T040 y T044; T048, T049; T050…T052 al final.

## Paralelo

- Tramo 1: T003, T004, T005, T006, T007 (clases distintas del mismo fichero escritas en orden; T007 en otros ficheros); T011 con T013.
- Tramo 2: T021, T022, T023; T027 con T029.
- Tramo 3: T036, T037, T038; T043 con T045.

## Estrategia

MVP = tramo 1 (US1 y US2: borrar y arreglar unidades, lo más pedido y lo más
arriesgado). El tramo 2 completa CAP-050 (US3, US4) y el 3 hace la energía
(US5) y cierra la documentación. US6 se comprueba en los tres.
