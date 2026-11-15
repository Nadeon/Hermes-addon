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

- [x] T001 Comprobar la base: `tools/recorder_status.py` y la familia `recorder` (029), `tests/banco/cobertura_012.py` y `cobertura_escrituras.py` (028/012), `tests/test_confirmation_args_inventory.py` (033), `tests/test_matriz_pruebas.py` (014), `estado` en `create_confirmation_token` (018). Si falta algo, parar y avisar. Línea base de la suite, anotada en el commit del tramo
- [x] T002 [US6] En `tests/test_tools_statistics_maintenance.py`, el doble de HA del módulo: `AsyncMock` de `ws_send` que responde a `recorder/get_statistics_metadata` con metadatos configurables (`sensor.consumo`: `source: recorder`, Wh, `unit_class: energy`, `has_sum: true`; `banco:externa`: `source: banco`), a `recorder/statistics_during_period` y a cada comando de escritura, y registra lo enviado; utilidad que comprueba que un paso NO envió ningún comando de escritura

### Tests de las tools (antes del código)

- [x] T003 [P] [US1] Tests de `ha_clear_statistics`: vista previa sin rango (`scope: "entire"`, `removes_metadata: true`, metadatos de cada id, `irreversible`, `undo`) sin enviar `recorder/clear_statistics`; con rango, `requested_range` y `effective_range` (horaria: después de `start_time - 1 h`; 5 minutos: después de `start_time - 5 min`; antes de `end_time`, en UTC); confirmación que envía los ids ordenados y sin repetir y las fechas en UTC; ids repetidos se piden una vez; id desconocido → `statistics_not_found` con la lista y sin token; 0 o 101 ids, id sin forma, solo `start_time`, `start_time >= end_time`, fecha sin zona → `invalid_argument` sin llamar a HA; `unknown_command` → `recorder_not_loaded`; `timeout` de HA → `ha_timeout` con el aviso de la cola; error de HA con `centinela-020` → redactado con `ha_code`; log capturado: paso y recuentos, ningún id ni fecha (FR-001, FR-006, FR-008, FR-017…FR-019)
- [x] T004 [P] [US2] Tests de `ha_change_statistics_unit`: vista previa con unidad y clase actuales y nuevas, `converts` y `tables`, sin enviar el comando; confirmación con `new_unit_of_measurement`/`old_unit_of_measurement` → `queued: true` y `check_with`; `source` distinto de `recorder` → `not_supported_for_source`; `old_unit` distinto de la guardada → `unit_mismatch` con la actual; `old_unit == new_unit` → `invalid_argument`; id desconocido → `statistics_not_found`; ninguno de los tres emite token; log sin ids ni unidades (FR-002, FR-006, FR-008, FR-018)
- [x] T005 [P] [US2] Tests de `ha_update_statistics_metadata`: vista previa con `current` y `new` y `converts_values: false`; confirmación que envía SIEMPRE `unit_class` (también `null`) → `updated: true`; id desconocido → `statistics_not_found`; `timeout` → `ha_timeout`; `unknown_command` → `recorder_not_loaded`; `invalid_format`/`home_assistant_error` de HA → `ha_command_failed` con `ha_code` y `table_ha_core` (FR-003, FR-006, FR-008, FR-019)
- [x] T006 [P] [US1] [US2] Tests del token en las tres: confirmar cambiando cualquier argumento (otro id, otro rango, sin rango, otra unidad, otra clase) → «does not match» y nada enviado; metadatos distintos al confirmar (unidad cambiada, estadística borrada) → `ESTADO_CAMBIADO` y nada enviado; token usado dos veces → rechazado; fechas equivalentes en otra zona (`+02:00` y `Z`) atan lo mismo (normalización) (FR-007, SC-003)
- [x] T007 [P] [US6] Tests en `tests/test_tool_families.py` (familia `recorder` con los módulos `recorder_status` y `statistics_maintenance`; su descripción ya no contiene «read only» y nombra el mantenimiento) y en `tests/test_tools_registration.py` (las tres en `_HINTS_NUEVAS_1_2_0` con `-DI-` y su título; las tres toman `confirmation_token`; con `recorder` desactivada no aparece ninguna de las seis de la familia). Actualizar a la vez los tests de la 029 que fijan la familia: `test_recorder_es_de_la_1_2_0` (`modulos`) y `TestRecorderRegistration` (`test_desactivada_no_registra_ninguna` y `test_sin_las_dos_familias_es_la_lista_de_antes_de_la_029` restan también las de la 020), con un comentario que lo explique (FR-014, FR-016, SC-001)

### Implementación

- [x] T008 [US1] [US2] `hermes/src/hermes/tools/statistics_maintenance.py`: ayudante común (plan.md, «Patrón común») y las tres tools de contracts/tools.md, reutilizando `_STATISTIC_ID_RE`, `_con_forma` y `_error_ha` de `recorder_status.py` (sin cambiarlos); descripciones en inglés que dicen qué borran o cambian, que solo un backup lo deshace y `queued` donde HA encola; comentarios del porqué (R-1, R-2). T002–T006 en verde (FR-001…FR-003, FR-006…FR-008, FR-017…FR-019)
- [x] T009 [US1] [US2] `tests/test_confirmation_args_inventory.py`: filas de las tres (data-model, «Inventario de argumentos atados»), recuento del docstring actualizado; el test en verde (FR-007)
- [x] T010 [US6] `tool_families.py` (módulo y descripción nueva de `recorder`, comentario que retira el «read only»), `tools/__init__.py` (registro bajo `if _activa("recorder")`), `tools/_annotations.py` (las tres en `_DESTRUCTIVE_EXACT` con el porqué y en `_HINTS_NUEVAS_1_2_0`). T007 en verde y el invariante «destructiva ⇒ token» también (FR-014, FR-016)

### Tabla

- [x] T011 [P] [US6] Tests en `tests/test_tools_generic_commands.py`: `ha_call_ws_command` y `ha_read_ws_command` con `recorder/clear_statistics`, `recorder/change_statistics_unit` y `recorder/update_statistics_metadata` → `use_dedicated_tool` con su tool y sin `ws_send`; con `recorder` desactivada → `family_disabled: true` (FR-015)
- [x] T012 [US6] `command_table.py`: las tres a `E("dedicated", "cubierto por <tool>", "recorder", tool=…, cap="CAP-050")`; sus claves en `_DEDICADAS_INICIALES` de `scripts/inventario/generar_tabla.py` (bloque comentado «020»); ejecutar el generador y comprobar que `git diff -- hermes/src/hermes/command_table.py` no cambia nada respecto a la edición a mano; anotarlo en el commit. T011, `tests/test_command_table.py` y `tests/test_generar_tabla.py` en verde (FR-015)

### Guía

- [x] T013 [US1] [US2] Tests en `tests/test_tools_guide.py`: el tema `recorder` nombra las tres tools nuevas, explica dos pasos, `queued`, la diferencia entre cambiar la unidad (convierte) y editar metadatos (no convierte) y que solo un backup deshace; ya no dice que todo el tema es de solo lectura (el test de la 029, `test_tema_con_contenido`, busca «SOLO LECTURA»: la frase se queda para el grupo de las tres lecturas o el test se actualiza, sin perder lo que comprueba); las huellas de `_HUELLAS_ANTES_DE_LA_013` no cambian (el tema `data` tampoco) (FR-020)
- [x] T014 [US1] [US2] `hermes/src/hermes/tools/guide.py`: tema `recorder` ampliado (en español, como los demás) y línea del índice. T013 en verde (FR-020)

### Banco de Core

- [x] T015 [US1] [US2] `tests/banco/test_banco_estadisticas.py` (marcador `banco`, helpers de la 010/028): siembra del lector con `recorder/import_statistics` directo a Core (`sensor.banco_<sufijo>_energia`, `source: recorder`, kWh, `unit_class: energy`, `mean_type: 0`, `has_sum: true`, 24 filas horarias de hace dos días; y una externa `banco:<sufijo>_externa`), esperando a verla con `recorder/statistics_during_period`, y borrado al final. Casos: (a) `ha_clear_statistics` con rango de 3 horas: vista previa sin efecto (el lector ve las 24 filas), confirmación → el lector ve 21 o menos y ninguna dentro del rango efectivo; sin rango sobre la externa → desaparece de `recorder/list_statistic_ids`; (b) `ha_change_statistics_unit` kWh→Wh: vista previa sin efecto; confirmación → el lector ve unidad `Wh` y la suma ×1000 (sondeo con plazo); sobre la externa → `not_supported_for_source`; (c) `ha_update_statistics_metadata` a `MWh`/`energy`: el lector ve la unidad nueva y los mismos valores. Si algo falla en HA real, `xfail` estricto con ese fallo concreto y anotado como hallazgo (FR-006, FR-021, SC-003, SC-005)
- [x] T016 [US6] `tests/banco/cobertura_020.py` (docstring con el contrato de la 028): `PROBADAS_020` con las tres y `NO_EJECUTABLES_020 = {}`; sumarlas a `_listas()` de `tests/test_banco_cobertura_escrituras.py` y `PROBADAS_020` a `TOOLS_EXIGIDAS_DEL_JOB` de `tests/banco/cobertura_escrituras.py`; `MODULOS_020 = ("statistics_maintenance", "energy")` en `cobertura_020.py` y, en `TestCoberturaDeLa029.test_modulos_de_las_familias_de_la_029` de `tests/test_banco_cobertura.py`, restar `MODULOS_020` de los módulos de las familias (si no, cae al añadir `statistics_maintenance` a `recorder`); `test_inventario_exacto` sigue igual (lista los módulos de la 029) (FR-021)
- [x] T017 [US6] `docs/HOJA-DE-RUTA.md`, matriz de pruebas (entre los marcadores `matriz-pruebas`): tres filas `banco de Core` / `ok`. `tests/test_matriz_pruebas.py` en verde (FR-021, FR-022)
- [x] T018 [US6] Ejecutar `tests/test_banco_cobertura_escrituras.py`, `tests/test_matriz_pruebas.py`, `tests/test_confirmation_args_inventory.py` y `tests/test_command_table.py` juntos: verde

### Cierre del tramo 1

- [x] T019 Control negativo del tramo 1, anotando recuentos: (a) quitar `end_time` del dict del token de `ha_clear_statistics` → cae T006; (b) no pasar `estado` → cae el de `ESTADO_CAMBIADO`; (c) quitar la comprobación de `source` → cae el de `not_supported_for_source`; (d) enviar el comando en la vista previa → cae la utilidad de T002; (e) no redactar el error de HA → cae el centinela; (f) registrar los ids en el log → cae el de log; (g) dejar `recorder/clear_statistics` en `deny` → cae T011; (h) quitar una de `PROBADAS_020` → cae `test_banco_cobertura_escrituras.py`; (i) quitar su fila de la matriz → cae `test_matriz_pruebas.py`. Restaurar y comprobar verde
- [x] T020 Documentación parcial y cierre: recuento de tools (+3) y filas de la familia en `README.md`, `README.es.md` y `hermes/DOCS.md` (`TestToolCountInDocs`; descripción nueva de `recorder`); sección «Estadísticas y energía» en `## [1.2.0]` de `hermes/CHANGELOG.md` con lo del tramo (incluido el cambio del tema `recorder` y de la descripción de la familia); 020 «en curso» en la tabla del programa de `docs/HOJA-DE-RUTA.md`; suite completa (los 6 fallos conocidos y ninguno más); revisión del diff (principio VIII, sin identificadores de modelos); commit en español con la línea base de T001, el resultado de T012 y los recuentos de T019 (FR-022)

### Notas del tramo 1 (implementación)

- Línea base (T001): 2926 passed, 95 skipped, 6 failed (los 6 de Windows).
  Al cerrar: 2965 passed, 98 skipped (los 3 del banco), los mismos 6.
- La confirmación vuelve a leer los metadatos y resuelve el token con ese
  `estado` ANTES de las comprobaciones previas: una estadística borrada o con
  otra unidad entre medias da `statistics_changed` (detalle
  `ESTADO_CAMBIADO`), no `statistics_not_found`. Si los metadatos no se
  pueden leer (o la respuesta no es una lista), falla cerrado y el token
  sigue pendiente.
- `table_ha_core` se añade sobre `_error_ha` de la 029 (sin cambiarlo).
- El tope de respuesta lo pone la red central (`recortar_a_bytes`, que
  conserva el token): las vistas previas no tienen listas propias grandes.
- T012: el generador, ejecutado sobre la tabla editada, la deja idéntica
  (0 entradas nuevas, 0 quitadas, sin diferencias).
- T019, controles negativos (comprobados y restaurados): (a) sin `end_time`
  en el token → 5 en rojo; (b) sin `estado` → 16; (c) sin la comprobación de
  `source` → 1; (d) comando en la vista previa → 19; (e) error sin redactar →
  3; (f) ids en el log → 2; (g) `recorder/clear_statistics` en `deny` → 2 de
  `test_tools_generic_commands.py`; (h) una menos en `PROBADAS_020` → 1 de
  `test_banco_cobertura_escrituras.py`; (i) sin su fila en la matriz → 2 de
  `test_matriz_pruebas.py`.
- Desviaciones: `test_banco_cobertura.py::test_el_job_exige_las_probadas` y
  `test_banco_cobertura_escrituras.py` (recuento 129 → 132 y la unión del
  job) también suman la 020; no los nombraba T016.

---

## Tramo 2 — Ajustar sumas, importar y avisos (US3, US4, US6)

### Tests de las tools (antes del código)

- [x] T021 [P] [US3] Tests de `ha_adjust_statistics_sum` (doble de T002): vista previa con `from` en UTC, ajuste y unidades, `sum_at_start` leído con `recorder/statistics_during_period` (`period: "hour"`, `types: ["sum"]`, esa hora; `before` y `after` si las unidades coinciden, solo `before` si no; `null` sin fila), `repeat_warning`; sin enviar el comando; confirmación con `adjustment_unit_of_measurement` → `queued: true`; `has_sum: false` → `statistic_has_no_sum`; id desconocido → `statistics_not_found`; `adjustment` 0, NaN o infinito, fecha sin zona → `invalid_argument`; `invalid_units` de HA → `ha_command_failed` con `ha_code`; log sin ids ni valores (FR-004, FR-006, FR-008, FR-017, FR-018)
- [x] T022 [P] [US4] Tests de `ha_import_statistics`: vista previa con `exists`, metadatos actuales y nuevos, `rows`, `first_start`, `last_start` y `overwritten_rows` (contadas con una lectura horaria del rango cuando es ≤ 31 días; `null` con `overwritten_rows_reason` si es mayor); aviso `recorded_entity_warning` si el id es de una entidad que existe; confirmación que envía `metadata` con `mean_type` y `unit_class` y sin `has_mean`, y `stats` en UTC ordenado → `queued: true`; `invalid_argument` sin llamar a HA con: `start` sin zona o con minutos, filas repetidas, 0 o 5001 filas, valor no finito, `mean_type` 3, clave desconocida en `metadata` o en una fila, `source` que no casa (`sensor.x` con `banco`; `banco:x` con `otra`), falta una clave obligatoria (FR-005, FR-006, FR-017)
- [x] T023 [P] [US3] [US4] Tests del token en las dos: cambiar `adjustment`, su unidad o `start_time` → «does not match»; `ha_import_statistics` confirmada sin `stats` → usa lo guardado (`omit_on_confirm`, `confirm_hint`); con `stats` distinto (una fila cambiada) → «does not match»; metadatos cambiados entre medias → `ESTADO_CAMBIADO`; tope de `stored_args` lleno → la confirmación sin `stats` se rechaza pidiendo reenviarlo (FR-005, FR-007, SC-003)

### Implementación

- [x] T024 [US3] [US4] `statistics_maintenance.py`: las dos tools de contracts/tools.md con el ayudante del tramo 1 (`omitibles=("stats",)` en la importación); descripciones en inglés (repetir el ajuste suma dos veces; la importación sobrescribe filas con la misma hora). T021–T023 en verde (FR-004…FR-008, FR-017, FR-018)
- [x] T025 [US3] [US4] `_annotations.py`: las dos en `_DESTRUCTIVE_EXACT`, `ha_adjust_statistics_sum` también en `_NON_IDEMPOTENT_EXACT` (con el porqué), y en `_HINTS_NUEVAS_1_2_0` (`-D--` y `-DI-`); tests en `tests/test_tools_registration.py` primero (FR-016)
- [x] T026 [US3] [US4] `tests/test_confirmation_args_inventory.py`: filas de las dos (`stats` atado y omitible) y recuento (FR-007)

### Tabla

- [x] T027 [P] [US6] Tests: en `tests/test_tools_generic_commands.py`, `recorder/adjust_sum_statistics` e `recorder/import_statistics` → `use_dedicated_tool`; `ha_call_ws_command("recorder/update_statistics_issues")` da vista previa con token y, al confirmar, lo envía sin carga; `ha_read_ws_command` con él → rechazado por ser `confirm`. En `tests/test_command_table.py`, `recorder/update_statistics_issues` en `_POR_LA_TABLA` con «spec 020: …» (research R-3) (FR-009, FR-015)
- [x] T028 [US6] `command_table.py`: las dos a `dedicated` (familia `recorder`, CAP-050) con sus claves en `_DEDICADAS_INICIALES`; `recorder/update_statistics_issues` a `E("confirm", "<motivo de data-model>", "generic_commands", cap="CAP-050")` a mano; regenerar y comprobar que no cambia nada. T027 y los de la tabla en verde (FR-009, FR-015)

### Guía

- [x] T029 [US3] [US4] Tests y después `guide.py`: el tema `recorder` nombra las cinco de mantenimiento, explica el ajuste (no idempotente), la importación (horas en punto, `mean_type`, fuente, `stats` omitible al confirmar) y `ha_call_ws_command(type="recorder/update_statistics_issues")` para regenerar los avisos de Repairs tras arreglar (FR-020)

### Banco de Core

- [x] T030 [US3] [US4] `tests/banco/test_banco_estadisticas.py`: (a) `ha_adjust_statistics_sum` +5 kWh desde la hora 12 de la siembra: vista previa sin efecto; confirmación → el lector ve la suma +5 desde esa hora y la misma antes (sondeo); (b) `ha_import_statistics` de `banco:<sufijo>_importada` con 6 filas: vista previa sin efecto (no existe para el lector); confirmación → el lector ve las 6 filas y los metadatos; reimportar una fila cambiada sobrescribe; (c) `ha_call_ws_command("recorder/update_statistics_issues")` en dos pasos responde con éxito y `repairs/list_issues` del lector responde después. Limpieza con el lector (FR-009, FR-021)
- [x] T031 [US6] `PROBADAS_020` con las dos (cinco en total); `test_banco_cobertura_escrituras.py` en verde (FR-021)
- [x] T032 [US6] Matriz de pruebas de `docs/HOJA-DE-RUTA.md`: dos filas más; `test_matriz_pruebas.py` en verde (FR-021, FR-022)

### Cierre del tramo 2

- [x] T033 Control negativo del tramo 2, anotando recuentos: (a) quitar `adjustment_unit` del token → cae T023; (b) no comprobar `has_sum` → cae el de `statistic_has_no_sum`; (c) aceptar `start` con minutos → cae el de T022; (d) no declarar `stats` omitible → cae el de `omit_on_confirm`; (e) quitar `ha_adjust_statistics_sum` de `_NON_IDEMPOTENT_EXACT` → cae T025; (f) dejar `update_statistics_issues` en `deny` → cae T027; (g) quitar una de `PROBADAS_020` → cae T031. Restaurar y comprobar verde
- [x] T034 CHANGELOG (sección «Estadísticas y energía» con lo del tramo), recuento +2 en `README.md`, `README.es.md` y `hermes/DOCS.md` (FR-022)
- [x] T035 Cierre del tramo 2: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII), commit con los recuentos de T033 y el resultado de la regeneración de T028

### Notas del tramo 2 (implementación)

- Línea base (punta `8c25508`): 2965 passed, 98 skipped, 6 failed (los 6 de
  Windows). Al cerrar: 2996 passed, 101 skipped (los del banco), los mismos 6.
- El ayudante `_dos_pasos` admite una vista previa asíncrona (lee la suma de
  la hora o las filas que se sobrescriben; si esa lectura falla, no hay
  token) y un comando y un resultado calculados con los argumentos RESUELTOS
  por el token (con `stats` omitido, se envía lo guardado).
- `ha_import_statistics` exige las siete claves de `metadata` y no admite
  `has_mean` (manda `mean_type`); `start` tiene que ser hora en punto EN UTC
  (más estricto que HA, que mira los minutos en la zona que llega).
- La vista previa de la importación no cuenta filas si la estadística no
  existe (`overwritten_rows: 0` sin leer) y solo lee con 31 días o menos.
- T028: el generador, sobre la tabla editada, la deja idéntica (0 entradas
  nuevas, 0 quitadas, sin diferencias).
- T033, controles negativos (comprobados y restaurados): (a) sin
  `adjustment_unit` en el token → 1 en rojo; (b) sin comprobar `has_sum` →
  1; (c) `start` con minutos aceptado → 3 casos; (d) `stats` sin declarar
  omitible → 4; (e) sin `ha_adjust_statistics_sum` en
  `_NON_IDEMPOTENT_EXACT` → 2 de `test_tools_registration.py`; (f)
  `update_statistics_issues` en `deny` → 2 de `test_tools_generic_commands.py`;
  (g) una menos en `PROBADAS_020` → 1 de `test_banco_cobertura_escrituras.py`.
- Desviaciones: `test_command_table.py::test_tres_rutas_a_read` comparaba
  `_POR_LA_TABLA` entero con las de la 013; ahora filtra las «spec 013: ».
  `ha_import_statistics` sale en la vista previa con `columns` (las columnas
  que llegan) además de lo de data-model.

---

## Tramo 3 — Energía y cierre (US5, US6)

### Tests (antes del código)

- [x] T036 [P] [US6] Tests en `tests/test_tool_families.py` (familia `energy`, `desde="1.2.0"`, desactivable, módulo `energy`, descripción de data-model) y en `tests/test_tools_registration.py` (`ha_get_energy_prefs` `R-I-` y `ha_update_energy_prefs` `-DI-` en `_HINTS_NUEVAS_1_2_0`; la segunda toma `confirmation_token`; con `energy` desactivada no aparece ninguna y el resto no cambia; con `recorder` y `energy` desactivadas, el conjunto es exactamente el de antes de la 029) (FR-014, FR-016, SC-001)
- [x] T037 [P] [US5] Tests en `tests/test_tools_energy.py`, `ha_get_energy_prefs`: preferencias de HA devueltas con `configured: true`; `not_found` de HA → `configured: false` y tres listas vacías; `unknown_command` → `energy_not_loaded`; un secreto en un nombre → redactado; documento mayor que el tope → `response_too_large`; Core caído → error de siempre; log sin el documento (FR-010, FR-017…FR-019)
- [x] T038 [P] [US5] Tests de `ha_update_energy_prefs`: ninguna lista → `invalid_argument`; lista que no es de objetos, fuente con `type` desconocido, dispositivo sin `stat_consumption` → `invalid_argument` sin llamar a HA; vista previa (sin enviar `energy/save_prefs`) con `changes` por lista (`before_count`, `after_count`, `added`, `removed`, `changed` identificados por `type` y `stat_*`), `kept` con las listas no recibidas, `removes_all_sources` al mandar `energy_sources: []` con fuentes, `warnings` con las estadísticas que `recorder/get_statistics_metadata` no devuelve (y el aviso de que no se pudo comprobar si el recorder no está), `current` de las listas que cambian; preferencias sin configurar → `before_count: 0`; confirmación que envía SOLO las listas recibidas y devuelve lo que HA guardó; cualquier lista distinta al confirmar → «does not match»; preferencias cambiadas por otro entre medias → `ESTADO_CAMBIADO` y nada enviado; sin preferencias en la vista previa y guardadas por otro antes de confirmar → `ESTADO_CAMBIADO` (el estado es `{"configured": false}`, no `None`); `invalid_format` de HA → `ha_command_failed` redactado; log con recuentos por lista y sin estadísticas (FR-011, FR-012, FR-017, FR-018, SC-003)

### Implementación

- [x] T039 [US5] Revisar el doble de HA de `tests/test_tools_energy.py` contra `energy/websocket_api.py` y `data.py` (respuesta de `get_prefs`, `save_prefs` devuelve `manager.data`, `not_found` «No prefs»); anotar en el fichero de test el código de HA consultado
- [x] T040 [US5] `hermes/src/hermes/tools/energy.py` con las dos tools de contracts/tools.md (`estado` = preferencias actuales leídas con `energy/get_prefs`; sin omitibles); descripciones en inglés (reemplaza cada lista que llega, conserva las otras; HA valida el esquema). T037 y T038 en verde (FR-010…FR-012, FR-017…FR-019)
- [x] T041 [US6] `tool_families.py` (familia `energy`), `tools/__init__.py` (registro bajo `if _activa("energy")`), `_annotations.py` (`ha_update_energy_prefs` en `_DESTRUCTIVE_EXACT` con el porqué; las dos en `_HINTS_NUEVAS_1_2_0`). T036 en verde (FR-014, FR-016)
- [x] T042 [US5] `tests/test_confirmation_args_inventory.py`: fila de `ha_update_energy_prefs` (tres listas atadas) y recuento (FR-012)

### Tabla

- [x] T043 [P] [US5] [US6] Tests: en `tests/test_tools_generic_commands.py`, `energy/get_prefs` y `energy/save_prefs` → `use_dedicated_tool`; `ha_read_ws_command` con `energy/validate`, `energy/info`, `energy/solar_forecast` (sin carga) y `energy/fossil_energy_consumption` (con la carga del `example`) → se envían y vuelven redactadas; con `energy` desactivada, las dos dedicadas → `family_disabled: true`. En `tests/test_command_table.py`, las cuatro claves en `_POR_LA_TABLA` con «spec 020: …» y un test nuevo: ninguna entrada con «(spec 020)» y las doce de CAP-050/CAP-054 con la categoría de data-model (FR-013, FR-015, SC-002)
- [x] T044 [US5] [US6] `command_table.py`: `energy/get_prefs` y `energy/save_prefs` a `dedicated` (familia `energy`, CAP-054) con sus claves en `_DEDICADAS_INICIALES`; las cuatro lecturas a `read` a mano con el motivo de data-model y el `example` de consumo fósil (revisado contra `energy/websocket_api.py`); regenerar y comprobar que no cambia nada. T043 en verde (FR-013, FR-015)

### Guía

- [x] T045 [P] [US5] Tests en `tests/test_tools_guide.py`: tema `energy` con las dos tools, la semántica de reemplazo por lista, el ciclo leer → editar → guardar, las cuatro lecturas con su llamada exacta a `ha_read_ws_command`; alias `energy_prefs`, `energy_dashboard`, `energia` resuelven a él; el índice lo menciona; `hermes_guide(topic="generic_commands", search="fossil")` muestra el ejemplo de la tabla (FR-020)
- [x] T046 [US5] `guide.py`: tema `energy`, alias e índice. T045 en verde (FR-020)

### Banco de Core

- [x] T047 [US5] `tests/banco/ha_config/configuration.yaml`: `energy:` con comentario del porqué; `tests/banco/test_banco_energia.py`: el lector lee `energy/get_prefs` antes (o `not_found`); `ha_get_energy_prefs` da lo mismo; `ha_update_energy_prefs(device_consumption=[{"stat_consumption": <estadística sembrada por el lector>}])`: vista previa sin efecto (el lector ve lo de antes), confirmación → el lector ve el dispositivo y las fuentes intactas; segunda vista previa con las preferencias cambiadas por el lector entre medias → la confirmación da `ESTADO_CAMBIADO`; las cuatro lecturas por `ha_read_ws_command` responden (`fossil_energy_consumption` con una estadística sembrada y su `co2`); al final el lector restaura las preferencias de antes (FR-013, FR-021)
- [x] T048 [US6] `cobertura_020.py`: `ha_update_energy_prefs` en `PROBADAS_020` (seis) y `LECTURAS_020 = frozenset({"ha_get_energy_prefs"})` (nombre fuera de la convención `PROBADAS*`, que es solo de escrituras) sumado a `TOOLS_EXIGIDAS_DEL_JOB`; tests de inventario en verde (FR-021, SC-005)
- [x] T049 [US6] Matriz de pruebas: una fila más (`ha_update_energy_prefs`); documentación final: `hermes/DOCS.md` (familia `energy` en la lista de `tool_families_disabled`, recuento), `README.md` y `README.es.md` sincronizados (+2 y fila de la familia), sección «Estadísticas y energía» completa en el CHANGELOG, 020 «hecha» en la tabla del programa de `docs/HOJA-DE-RUTA.md` (FR-022)

### Cierre

- [x] T050 Control negativo del tramo 3, anotando recuentos: (a) no pasar `estado` en energía → cae el de `ESTADO_CAMBIADO`; (b) enviar las tres listas aunque solo llegue una → cae el de «solo las listas recibidas»; (c) no tratar `not_found` → cae el de `configured: false`; (d) quitar `warnings` → cae; (e) dejar `energy/validate` en `deny` → cae T043; (f) quitar `ha_get_energy_prefs` de `LECTURAS_020` → cae el test de inventario; (g) quitar `ha_update_energy_prefs` de la matriz → cae `test_matriz_pruebas.py`. Restaurar y comprobar verde
- [x] T051 Matriz de trazabilidad de `specs/008-cobertura-total/plan.md`: filas CAP-050 y CAP-054 con estado `X`, las tools y entradas definitivas y los ficheros de test (`test_tools_statistics_maintenance.py`, `test_tools_energy.py`, `test_tools_generic_commands.py`, `tests/banco/test_banco_estadisticas.py`, `tests/banco/test_banco_energia.py`) (FR-022)
- [x] T052 Cierre del tramo 3: suite completa (los 6 fallos conocidos y ninguno más), CI en verde con el banco, revisión del diff (principio VIII), commit con los recuentos de T050 y el resultado de la regeneración de T044

### Notas del tramo 3 (implementación)

- Línea base (punta `a6b18a6`): 2996 passed, 101 skipped, 6 failed (los 6 de
  Windows). Al cerrar: 3042 passed, 102 skipped (los del banco), los mismos 6.
- Decisiones del supervisor aplicadas: la vista previa de
  `ha_update_energy_prefs` da `current` (antes) y `new` (después) de cada
  lista que llega, y en `warnings` un `removes_items` por cada lista de la
  que se quitan elementos (además de `unknown_statistic` y
  `statistics_not_checked`). El token ata las tres listas (`None` las que no
  llegan) y el estado leído; un cambio entre medias da
  `energy_prefs_changed` con el detalle `ESTADO_CAMBIADO` (mismo patrón que
  `statistics_changed`). Si las preferencias no se pueden leer, falla
  cerrado (sin token; en la confirmación, el token sigue pendiente).
- Extra: se rechaza un `***REDACTED***` reenviado desde una lectura
  (guardarlo pisaría el valor real), como `sv_set_addon_options`. La
  confirmación devuelve `prefs` sin `configured`; si no caben en el tope,
  `prefs_omitted: true` (guardado, sin recortar).
- Las cuatro lecturas, revisadas en `energy/websocket_api.py`: solo leen y
  ninguna sale a internet (`solar_forecast` devuelve los datos que la
  integración de previsión ya tiene en memoria). Quedan `read` sin
  `open_world`.
- T044: el generador, sobre la tabla editada, la deja idéntica (0 entradas
  nuevas, 0 quitadas, sin diferencias); `test_desde_cero_igual_que_la_tabla_real`
  en verde con `energy/get_prefs` y `energy/save_prefs` en el mapa.
- T047, banco: si el banco no tenía preferencias, la limpieza guarda las tres
  listas vacías (HA no tiene comando para borrarlas).
- T050, controles negativos (comprobados y restaurados): (a) sin `estado` en
  la vista previa y en la confirmación → 2 en rojo (los de `ESTADO_CAMBIADO`);
  quitarlo solo de la confirmación hace caer 5 (todo token deja de valer);
  (b) enviar las tres listas → 1; (c) sin tratar `not_found` → 4; (d) sin
  `warnings` → 3; (e) `energy/validate` en `deny` → 1
  (`test_las_cuatro_lecturas`); (f) sin `ha_get_energy_prefs` en
  `LECTURAS_020` → 1 (`TestCoberturaDeLa020::test_inventario_exacto`); (g)
  sin su fila en la matriz → 2 de `test_matriz_pruebas.py`.
- Desviaciones: T051 pedía «estado `X`» en las filas CAP-050 y CAP-054, pero
  esa columna es la VÍA (D, D+T) y la leen `test_command_table.py` y la copia
  del generador; se dejan su vía y se completa la columna de tests, como en
  CAP-049. Tests nuevos fuera de los nombrados: `TestCoberturaDeLa020` en
  `tests/test_banco_cobertura.py` (inventario exacto de `MODULOS_020`);
  `test_banco_cobertura_escrituras.py` pasa de 134 a 135 y suma
  `LECTURAS_020` a la unión del job.

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

## Fase 4: Convergencia

Añadida por la revisión independiente y `speckit-converge` sobre la punta de la
rama (258ea8f). Severidad entre corchetes. Cada arreglo con su test de
regresión y su control negativo (principio VII). T052 no se reabre: la suite
local da los 6 fallos conocidos y el CI de la punta (pytest 3.12 y 3.13 y el
banco de Core) está en verde; solo falta marcarla.

- [x] T053 [MEDIO] La vista previa de `ha_adjust_statistics_sum` miente cuando `start_time` tiene segundos o microsegundos: HA ajusta la tabla horaria con `start_ts >= start_time.replace(minute=0)` (`adjust_statistics` en `recorder/statistics.py`), que conserva los segundos, así que con `10:30:15Z` la fila horaria de las 10:00 NO se ajusta (umbral 10:00:15); la vista previa lee esa fila y enseña `sum_at_start: {before: 100, after: 105}`, y la descripción y la guía dicen «every hourly row from its hour on» (comprobado con el doble de HA). Arreglo mínimo: rechazar con `invalid_argument` un `start_time` con segundos o microsegundos distintos de cero (o calcular la hora como HA y decir que esa fila no se toca); test con `10:30:15Z` per FR-004, FR-006, principio V (contradicts)
- [x] T054 [BAJO] Entrada hostil: un entero enorme (p. ej. `10**400`, válido en JSON) en una fila de `stats` de `ha_import_statistics` (y en `adjustment` si llega sin convertir) lanza `OverflowError` en `math.isfinite` (`_numero_finito`) y la tool revienta con una excepción en vez de `invalid_argument` (comprobado; no se escribe nada). Arreglo mínimo: en `_numero_finito`, capturar `OverflowError` y devolver `False`; test con `10**400` per FR-004, FR-005 (partial)
- [x] T055 [BAJO] `recorder/get_statistics_metadata` devuelve también las estadísticas que la integración «añadirá en el próximo periodo» aunque no estén en la base (`list_statistic_ids` consulta las plataformas, p. ej. todo sensor con `state_class`). Consecuencias: (a) tras borrar entera la estadística de un sensor vivo sigue saliendo en las listas y el recorder la recrea en la siguiente compilación, pero la vista previa y la guía dicen «They disappear from the statistics lists» / «desaparecen de las listas»; (b) en esa ventana (sensor nuevo sin compilar), `ha_change_statistics_unit`, `ha_update_statistics_metadata` y `ha_adjust_statistics_sum` dan token y `queued`/`updated` y HA no hace nada (sus trabajos de la cola miran la base). Arreglo mínimo: corregir el texto de la vista previa y de la guía de borrar («una estadística de una entidad que se graba vuelve a aparecer y se recompila desde ahora; las filas borradas no vuelven») y decirlo en las descripciones; (b) basta documentarlo per FR-006, FR-008, FR-020, principio V (partial)

Resolución de la fase 4 (decisiones del supervisor):

- T053: `start_time` tiene que ser una hora en punto en UTC (minutos,
  segundos y microsegundos a cero); si no, `invalid_argument` sin token. Las
  demás tools de la 020 no tienen el problema: el rango de borrar ya da el
  periodo efectivo de HA para cualquier instante, e importar ya exigía horas
  en punto.
- T054: `_numero_finito` captura `OverflowError` (cubre `stats`,
  `adjustment` y el `start` que lee la vista previa).
- T055 (a): vista previa, descripción y guía de borrar dicen que la
  estadística de una entidad que se graba se vuelve a compilar.
- T055 (b): HA devuelve lo guardado y lo que compilará con los mismos campos
  (`list_statistic_ids`), así que Hermes no puede distinguirlos ni rechazar
  sin riesgo de rechazar lo bueno. Cambiar la unidad, editar los metadatos y
  ajustar lo dicen en `not_validated: ["statistic_in_database"]` (vista
  previa y respuesta), con `check_with`.
