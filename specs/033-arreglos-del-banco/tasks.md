---

description: "Tareas de la sub-feature 033 (arreglos de tools existentes destapados por el banco)"
---

# Tareas: 033 — arreglos de tools existentes destapados por el banco

**Entrada**: `specs/033-arreglos-del-banco/` (spec.md, plan.md, research.md,
contracts/tools.md, quickstart.md).

**Tests**: obligatorios y **primero** (TDD): cada historia empieza por sus
tests, que se ejecutan y se ven en **rojo** sobre el código sin arreglar;
después, el arreglo; al final, el **control negativo** (principio VII): se
deshace un momento la parte del código, se comprueba qué tests caen, se
restaura y se anota el recuento en el test o en el commit. Estilo de los
existentes: `unittest.IsolatedAsyncioTestCase`, `DummyMCP`, los simuladores de
cada fichero, `CONFIRMATIONS_DIR` en un `tempfile.TemporaryDirectory`. Solo
marcadores genéricos (`script.ficticio`, `automation.ficticia`,
`light.salon`, `counter.ficticio`, `scene.fiesta`).

**Banco**: los tests del banco solo corren en el job `banco de Core` del CI;
en local se saltan. Reglas de la 010: `pytestmark = banco`, sin `skipTest`, sin
pausas fijas, sin `xfail` fuera de la lista, efecto comprobado por el lector
independiente. La tarea «banco en verde» se da por hecha con el run del CI en
verde (o queda anotada como pendiente si el tramo no sube la rama).

**Suite**: desde la raíz del worktree,
`HERMES_CONFIG_BASE=<carpeta propia> <python del .venv> -m pytest -q -p no:cacheprovider`.
En Windows fallan exactamente los 6 conocidos. Línea base de la spec (punta
`cc478d4`): 2080 passed, 38 skipped, 6 failed.

## Formato: `[ID] [P?] [Historia] Descripción`

- **[P]**: se puede hacer en paralelo (ficheros distintos, sin dependencias).
- **[US1]…[US7]**: historias de [spec.md](spec.md).

## Tramos

Dos tramos; cada uno lo hace un agente nuevo, deja la suite en verde y termina
en su propio commit (solo las rutas que toca, añadidas por nombre).

| Tramo | Tareas | Cubre |
|---|---|---|
| **1** — token atado (seguridad) | **T001–T011** | US1 y su parte de US7: FR-001, FR-002, FR-003, FR-010 (tokens en el banco), FR-012 (CHANGELOG y guía de su parte), FR-013 |
| **2** — honestidad del resto | **T012–T036** | US2…US6 y el resto de US7: FR-004…FR-009, FR-010 (resto), FR-011, FR-012, FR-013 |

---

# TRAMO 1 — el token ata lo que se ejecuta (T001–T011)

## Fase 1: Preparación

- [x] T001 Línea base del tramo 1: comprobar que `feat/cobertura-total` tiene integradas la 011 y la 028 (con su T033: script y automatización restringidos del banco); si no, integrar la rama del programa en `feat/033-arreglos-del-banco` y resolver conflictos (S-01). Ejecutar la suite completa y anotar el recuento

**Notas del tramo 1** (implementación):

- T001: `feat/cobertura-total` integrada (009, 010, 011 y 028 con su T033).
  Línea base en Windows: 2320 passed, 65 skipped, 6 failed (los 6 conocidos).
- T006: son **81** tools con `confirmation_token`, no 79: la 011 integró
  después de la auditoría `ha_call_ws_command` y `sv_call_api`, que atan todo
  lo que envían (`type`/`payload`; `method`/`path`/`body`). Desviación anotada
  en el test.
- T007: el control negativo queda permanente en el propio test
  (`TestControlNegativo`, sobre una copia temporal de `tools/`).
- T008: el efecto se ve en un `input_boolean` del lector elegido por la
  variable `objetivo` (como el `xfail` de la 028), no en un `input_text` con
  su valor; hay un test para cada tool (`TestScript` y `TestAutomatizacion`).
  Se quita `TokenSinAtarLaAccion` de `tests/banco/base_escrituras.py`, que ya
  no usa nadie.

## Fase 2: Historia 1 — Lo que se confirma es lo que se vio (P1) 🎯

**Objetivo**: el token de `ha_run_script` y `ha_trigger_automation` ata `variables` y la vista previa las enseña.
**Prueba independiente**: confirmar con variables distintas se rechaza sin llamar a HA.

- [x] T002 [P] [US1] Tests unitarios en `tests/test_security_regressions.py` (clase de `guarded_entity_invoke`, con `CONFIRMATIONS_DIR` temporal y el espía de `call_service`): (a) la vista previa de una entidad restringida trae `variables`; (b) confirmar con otras variables, sin ellas, o con ellas tras una vista previa sin ellas → error de token y el espía no ve ninguna llamada; (c) mismas variables con otro orden de claves → una llamada con `allow_dangerous=True` y el payload con esas variables; (d) entidad no restringida con variables → un paso, como hoy. Ver (a)–(c) en rojo
- [x] T003 [P] [US1] Tests de las tools en `tests/test_tools_scripts.py` y `tests/test_tools_automations.py`: `ha_run_script` y `ha_trigger_automation` sobre una entidad restringida con variables A en la vista previa y B en la confirmación → rechazo sin llamada a HA; con A → HA recibe A. En rojo
- [x] T004 [US1] Arreglo en `hermes/src/hermes/tools/_common.py` (`guarded_entity_invoke`: argumento `variables` explícito, atado en `args` tal como llega y enseñado en la vista previa; docstring con el porqué) y en sus dos llamadores `hermes/src/hermes/tools/scripts.py` y `hermes/src/hermes/tools/automations.py`. Docstrings de `ha_run_script` y `ha_trigger_automation`: con entidad restringida, el token cubre también `variables`. T002 y T003 en verde
- [x] T005 [US1] Control negativo de T004: quitar `variables` de `args` (dejando la vista previa) → caen T002 (b) y T003; quitarla solo de la vista previa → cae T002 (a). Restaurar y anotar los recuentos

## Fase 3: Inventario de argumentos atados (FR-003)

- [x] T006 [US1] `tests/test_confirmation_args_inventory.py` (nuevo): dict `tool → {argumento: "atado" | "exento: <motivo>"}` para las 79 tools con `confirmation_token` (research R-1); comprobación por AST de las firmas de `@mcp.tool` en `hermes/src/hermes/tools/*.py`: el dict cubre exactamente esas tools y, en cada una, exactamente sus argumentos; ningún motivo vacío; `confirmation_token` siempre exento. Docstring con la regla para las sub-features siguientes (una tool nueva con token añade su entrada)
- [x] T007 [US1] Control negativo de T006: añadir en una copia temporal una tool con token sin entrada, y un argumento nuevo a una tool existente → el test cae nombrándolos; restaurar y anotar

## Fase 4: Banco (FR-010, parte del tramo 1)

- [x] T008 [US7] Test del banco en `tests/banco/test_banco_escrituras_automatizacion.py` con el script y la automatización restringidos inocuos de la 028 (T033), ampliados para usar una variable (por ejemplo, poner un `input_text` del lector al valor de `variables.valor`): vista previa con la variable visible; confirmación con otro valor → error de token y el lector no ve el servicio ni el cambio; confirmación con el mismo valor → el lector ve el `input_text` con ese valor. Las dos tools siguen en `PROBADAS_028` y se exigen por ejecución
- [ ] T009 [US7] Control negativo del test del banco: si el tramo sube la rama, un commit temporal con T004 revertido pone el job en rojo en el test de T008 (la confirmación con otro valor se ejecuta) y se descarta después; si no se sube, se anota como pendiente y el control negativo del arreglo queda cubierto por T005

## Fase 5: Cierre del tramo 1

- [x] T010 [P] Documentación: subsección «Arreglos destapados por el banco (033)» en `### Correcciones` de `## [1.2.0]` en `hermes/CHANGELOG.md` con la viñeta del token; en `hermes/src/hermes/tools/guide.py`, tema de automatizaciones y scripts: el token de una entidad restringida cubre también `variables`; en `specs/008-cobertura-total/plan.md`, fila CAP-039 de la matriz con los tests del tramo 1
- [ ] T011 Suite completa (solo los 6 conocidos en Windows), revisión del diff buscando datos personales, y commit del tramo 1 con los recuentos de T005, T007 y T009. Si se sube la rama: CI y banco en verde

---

# TRAMO 2 — honestidad de las demás tools (T012–T036)

## Fase 6: Preparación

- [ ] T012 Línea base del tramo 2 sobre el commit del tramo 1 (y, si hace falta, integrar de nuevo la rama del programa: S-01). Comprobar si la 028 dejó en `tests/banco/cobertura_escrituras.py` un hallazgo de `ha_create_scene_from_current` en `HALLAZGOS_028` / `XFAIL_PERMITIDOS_028` y anotarlo

## Fase 7: Historia 2 — `ha_reload_counters` y `ha_get_config_entry_options` lo dicen (P1)

- [ ] T013 [P] [US2] Tests en `tests/test_tools_counter.py`: `ha_reload_counters` sin token y con un token cualquiera → `not_supported` con `_deprecated`; el doble de HA no recibe ninguna llamada; no se crea ningún fichero de token; la docstring empieza por `DEPRECATED (removed in 1.3.0)`. En rojo
- [ ] T014 [US2] Arreglo en `hermes/src/hermes/tools/counter.py` (`ha_reload_counters` según contracts/tools.md, sin `guarded_reload`; comentario con el porqué y la referencia a research R-2). T013 en verde
- [ ] T015 [P] [US2] Tests en `tests/test_tools_config_entry_flows.py`: con una entry existente → `not_supported` con `entry_id`, `domain`, `title`, `supports_options`, `hint` y `_deprecated`, sin clave `options`; entry inexistente → `not_found` como hoy; error de conexión → como hoy. En rojo
- [ ] T016 [US2] Arreglo en `hermes/src/hermes/tools/config_entry_flows.py` (`ha_get_config_entry_options` según el contrato; docstring `DEPRECATED (removed in 1.3.0)` con el motivo). T015 en verde
- [ ] T017 [US2] Controles negativos de T014 y T016 (volver a llamar a `guarded_reload`; volver a devolver `options: {}`) → caen T013 y T015; restaurar y anotar

## Fase 8: Historia 3 — `ha_wait_for_event` sin `ctx` en el esquema (P1)

- [ ] T018 [P] [US3] Tests: en `tests/test_tools_registration.py`, con el registro real, el esquema de `ha_wait_for_event` tiene `event_type`, `filters`, `timeout_seconds`, solo `event_type` obligatorio, y la tool registrada tiene `context_kwarg == "ctx"`; en `tests/test_tools_wait_for_event.py`, (a) una espera más larga que `_KEEPALIVE_INTERVAL` (parcheado a algo corto) con un `Context` de prueba (subclase o doble con `report_progress`) llama a `report_progress`; (b) por el `MCPServer` real, `call_tool` con un `ctx` sobrante no da error de validación. En rojo lo que corresponda
- [ ] T019 [US3] Arreglo en `hermes/src/hermes/tools/wait_for_event.py`: `ctx: Context` en la misma posición (plan, Diseño). T018 en verde y los tests existentes de `ha_wait_for_event` sin tocar
- [ ] T020 [US3] Control negativo de T019 (volver a `Any`) → cae el test del esquema y el de `context_kwarg`; anotar

## Fase 9: Historias 4 y 5 — escenas (P2, P3)

- [ ] T021 [P] [US4] Tests en `tests/test_tools_scenes.py` con el doble de HA del fichero: (a) `name` → `name_not_supported` sin ninguna llamada de servicio; (b) entidad inexistente → `entity_not_found`; (c) escena inexistente → `scene.create` con `scene_id` y `snapshot_entities` y SIN `name`, respuesta `result: ok`, `replaced: false`, `temporary: true` y `ha_response`; (d) escena temporal existente sin token → vista previa con `current_entities` y `new_entities` y sin llamada; con el token → `scene.create` y `replaced: true`; con otras `entity_ids` → rechazo del token; (e) escena con atributo `id`, o con entrada en el registro de entidades → `scene_exists` sin token ni llamada; (f) tras `scene.create`, una escena con otras entidades → `scene_not_created`. En rojo
- [ ] T022 [US4] Arreglo en `hermes/src/hermes/tools/scenes.py` (`ha_create_scene_from_current` según research R-4 y el contrato, con `confirmation_token` opcional; docstring: escena temporal, cuándo pide token, `name` deprecado) y en `hermes/src/hermes/tools/_annotations.py` (`ha_create_scene_from_current` en `_DESTRUCTIVE_EXACT`, con comentario), con la línea de `_HINTS_SNAPSHOT` de T032 en el mismo paso para no dejar la suite en rojo. T021 en verde
- [ ] T023 [P] [US5] Test en `tests/test_tools_scenes.py`: las docstrings de `ha_get_scene`, `ha_create_or_update_scene` y `ha_delete_scene` nombran `scenes.yaml` y no contienen `.storage/core.scene_`; la de `ha_create_or_update_scene` no dice que vea las escenas de `scene.create`. En rojo; arreglo de las docstrings en `hermes/src/hermes/tools/scenes.py`; en verde
- [ ] T024 [US4] Controles negativos de T022 (volver a mandar `name`; quitar la consulta de existencia; quitar la comprobación posterior) → anotar qué tests caen en cada caso

## Fase 10: Historia 6 — `amount` de los contadores (P2)

- [ ] T025 [US6] Test del banco PRIMERO, en `tests/banco/test_banco_helpers_tiempo.py` (`TestCounter`): contador creado por el lector con `initial` 5 y `step` 3; `ha_increment_counter` con `amount=3` → hoy 500 (la sospecha, confirmada contra HA real en el CI, se anota en el commit); tras el arreglo, `invalid_amount` con `reason: not_multiple_of_step` y el lector ve el contador en 5; `ha_set_counter_value` a 6 y `amount=3` → 9 (camino válido); contador con `step` 1 y `maximum` 10 en 9, `amount=5` → `invalid_amount` `out_of_range`
- [ ] T026 [P] [US6] Tests unitarios en `tests/test_tools_counter.py` con atributos `step`/`minimum`/`maximum` en el estado del doble: los casos de la Historia 6 para increment y decrement; sin `amount`, sin cambios; sin `step` en atributos → se asume 1. En rojo
- [ ] T027 [US6] Arreglo en `hermes/src/hermes/tools/counter.py` (`_bulk_adjust` según research R-7 y el contrato; docstrings de increment y decrement con la regla). T026 en verde
- [ ] T028 [US6] Control negativo de T027 (quitar la comprobación) → caen T026 y, en el banco, T025; anotar

## Fase 11: Historia 7 — el banco da los arreglos por probados (P1)

- [ ] T029 [US7] `tests/banco/test_banco_helpers_tiempo.py`: `TestCounter.test_recarga` sin `xfail`, como canario (research R-2): el lector comprueba que Core no tiene `counter.reload` en `get_services` y la tool responde `not_supported` sin que el lector vea ninguna llamada de servicio. `tests/banco/cobertura.py`: `ha_reload_counters` de `FALLAN_EN_BANCO` a `NO_EJECUTABLES` con su motivo, `XFAIL_PERMITIDOS` sin su test, docstrings y comentarios de recuento al día. EN EL MISMO COMMIT que T014 (el `xfail` estricto pondría el job en rojo)
- [ ] T030 [US7] Tests del banco de escenas en el fichero de escenas de la 028 (`tests/banco/test_banco_escrituras_automatizacion.py`): crear sin `name` (el lector ve la escena con esas entidades), reemplazar una temporal con token (el lector ve las entidades nuevas), `scene_exists` sobre una escena creada con `ha_create_or_update_scene` (el lector ve que no cambia), `name_not_supported` (el lector no ve `scene.create`). Quitar el `xfail` `HALLAZGO` de la escena y sus entradas de `HALLAZGOS_028` / `XFAIL_PERMITIDOS_028` si existen (T012)
- [ ] T031 [P] [US7] Tests del banco de `ha_wait_for_event` llamada sin `ctx` (el lector dispara el evento y la tool devuelve `matched: true`) y de `ha_get_config_entry_options` sobre la entry de `kitchen_sink` (`not_supported` con su `domain`), en los ficheros del banco de la 028 de servicios/eventos e integraciones

## Fase 12: Compatibilidad y cierre (FR-011, FR-012)

- [ ] T032 [US3] [US4] `tests/test_tools_registration.py`: en `_HINTS_SNAPSHOT`, `ha_create_scene_from_current` pasa de `----` a `-D--` con un comentario que cita FR-011 y FR-099 de la 008; en `test_esquemas_de_la_1_1_2` (si la 011 está integrada; si no, anotar la tarea para la integración), dos excepciones escritas junto a la de `hermes_guide`: `ha_wait_for_event` sin `ctx` (propiedad y obligatorio) y `ha_create_scene_from_current` con `confirmation_token` opcional, cada una con su porqué. Control negativo: con cualquiera de las dos excepciones quitada, el test cae
- [ ] T033 [P] Documentación: en `hermes/CHANGELOG.md`, viñetas del tramo 2 en la subsección de la 033; en `hermes/src/hermes/tools/guide.py`, contadores (sin recarga, regla de `amount`), escenas (temporal, `name`, `scenes.yaml`) y opciones de config entries (no publicadas, flujo de opciones); en `docs/HOJA-DE-RUTA.md`, deprecaciones con retirada en la 1.3.0 (`ha_reload_counters`, `ha_get_config_entry_options`, argumento `name` de `ha_create_scene_from_current`), fila 033 a «hecha», y el recuento del banco de helpers (46 probadas y 1 no ejecutable con motivo); en `specs/008-cobertura-total/plan.md`, la fila CAP-039 de la matriz completa con los tests
- [ ] T034 Revisión de honestidad (SC-005): releer las docstrings de las siete tools y los textos de la guía tocados contra el código y contra HA (research); la lista de frases revisadas va al commit
- [ ] T035 Suite completa (solo los 6 conocidos en Windows); revisión del diff buscando datos personales e identificadores de modelos
- [ ] T036 Commit del tramo 2 con los recuentos de T017, T020, T024, T028 y T032; si se sube la rama, CI y banco en verde (`FALLAN_EN_BANCO` vacío, ningún `xfail` de estas tools)

## Dependencias y orden

- Tramo 1: T001 → T002, T003 [P] → T004 → T005; T006 → T007 (independiente
  de T002–T005); T008 tras T004 → T009; T010 → T011.
- Tramo 2: T012 → historias en cualquier orden (T013–T017, T018–T020,
  T021–T024, T025–T028); T029 va con T014; T030 tras T022; T031 tras T016 y
  T019; T032 tras T019 y T022; T033 → T034 → T035 → T036.
- El tramo 2 empieza sobre el commit del tramo 1.

## Trazabilidad

| FR | Tareas |
|---|---|
| FR-001 | T002, T003, T004, T005 |
| FR-002 | T002, T004 |
| FR-003 | T006, T007 |
| FR-004 | T013, T014, T017, T029 |
| FR-005 | T018, T019, T020, T031 |
| FR-006 | T021, T022, T024, T030 |
| FR-007 | T023 |
| FR-008 | T015, T016, T017, T031 |
| FR-009 | T025, T026, T027, T028 |
| FR-010 | T008, T009, T025, T029, T030, T031 |
| FR-011 | T032 |
| FR-012 | T010, T033 |
| FR-013 | T005, T007, T009, T017, T020, T024, T028, T032 |

| SC | Tareas |
|---|---|
| SC-001 | T002, T003, T008 |
| SC-002 | T006 |
| SC-003 | T029, T030, T031, T036 |
| SC-004 | T032 |
| SC-005 | T034 |
| SC-006 | T011, T035, T036 |

## Notas

- Ninguna tool nueva: la tabla de clasificación y las familias no cambian.
- Los campos `message`, `hint` y `_deprecated` de las respuestas van en
  inglés (como `_deprecated` de `tools/hacs.py`); las docstrings (que son la
  descripción de la tool) siguen el idioma de las de su fichero, y los
  comentarios, en español.
- Si el CI no se puede ejecutar en un tramo, la tarea del banco queda anotada
  como pendiente en el commit, no marcada como hecha.
