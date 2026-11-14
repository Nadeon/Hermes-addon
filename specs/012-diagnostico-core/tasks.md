---

description: "Tareas de la sub-feature 012 — diagnóstico de Core (Hermes 1.2.0)"
---

# Tareas: diagnóstico de Core (012)

**Entrada**: `specs/012-diagnostico-core/` (spec.md, plan.md, research.md,
data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `CONFIRMATIONS_DIR` en
un `tempfile.TemporaryDirectory`, `DummyMCP`/`_RecordingMCP`, `AsyncMock` de
`ws_send`, `call_service`, `_request_json` y `rest_get_text_tail`,
`structlog.testing.capture_logs`. Datos ficticios (`light.salon`,
`<entry_id>`, `mqtt`, `centinela-012`, un JWT de prueba). Nada de la
instalación real ni de las tools MCP de Hermes.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" python -m pytest -q -p no:cacheprovider`.
Línea base en Windows al especificar (2026-11-14, punta `ab8c888`, sin la 009
ni la 010 integradas): 2021 passed, 16 skipped, 6 failed (los 6 conocidos).
T001 la vuelve a tomar tras integrar las dependencias. Cada tramo termina con
exactamente esos 6 fallos en local; la referencia es el CI de Linux.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 saber qué falla, US2 probar antes de guardar, US3
depurar una integración, US4 ordenar avisos y log, US5 nada se rompe.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado (uno o varios commits; el tramo no se cierra con la suite en rojo).

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **A** — base común y logs | **T001–T019** | Familia `core_diagnostics` (con `core_logs`); `HAClient.rest_get_text_tail`; `ha_list_system_log`, `ha_get_error_log`, `ha_get_log_levels`, `ha_set_log_level`, `ha_clear_system_log` registradas, anotadas y probadas; 4 entradas de `logger/` y `system_log/list` en `dedicated` con el generador al día; tema de la guía (logs); banco de logs; CHANGELOG y hoja de ruta parciales |
| **B** — validación, diagnósticos y notificaciones | **T020–T034** | `ha_validate_config`, `ha_test_condition`, `ha_list_diagnostics_handlers`, `ha_get_config_entry_diagnostics`, `ha_get_device_diagnostics`, `ha_list_persistent_notifications`, `ha_dismiss_persistent_notification`; las otras 5 entradas en `dedicated`; guía completa; banco del resto; documentación final y matriz de la 008 |

El tramo B necesita el A integrado.

---

## Tramo A — base común y logs (US1, US3, US4, US5)

### Preparación

- [x] T001 Integrar en la rama lo que falta de las dependencias (S-01): la 009 (redacción lineal y `## [1.2.0]`), la 010 (banco) y la 011 entera (genéricas, opción `tool_families_disabled`, registro por familias), por merge desde `feat/cobertura-total` o desde sus ramas según lo que esté integrado; resolver conflictos sin cambiar comportamiento. Ejecutar la suite y anotar la línea base en el mensaje del commit. Si la 010 no está disponible, seguir y marcar T015 como pendiente (nota en el commit y en `docs/HOJA-DE-RUTA.md`)

### Familia (US5)

- [x] T002 [P] [US5] Tests en `tests/test_tool_families.py`: `core_diagnostics` existe, `desde="1.2.0"`, desactivable, con exactamente los módulos del tramo (`core_logs`); `validar_desactivadas(["core_diagnostics"])` la acepta; el test existente de SC-005 (familias de la 1.2.0 desactivadas → las 216 de la 1.1.2) sigue pasando sin tocarlo (FR-013)
- [x] T003 [US5] `hermes/src/hermes/tool_families.py`: `Familia("core_diagnostics", …)` según data-model, en el bloque de la 1.2.0, con comentario del porqué de una sola familia (research R-9). T002 en verde (FR-013)

### Cliente: texto de Core (US1)

- [x] T004 [P] [US1] Tests en `tests/test_ha_rest_text_tail.py` con un servidor aiohttp local (patrón de los tests de `HAClient` existentes): cuerpo de 5000 líneas → devuelve las últimas `lines`; cuerpo sin salto final; línea de 10 000 bytes → recortada a `max_line_bytes` con la marca; cuerpo vacío → lista vacía; 404 → `HAConnectionError` con `status == 404`; 500 → `HAConnectionError` con su estado; ruta con `..` → rechazada sin petición (`_assert_safe_request_path`); cliente sin sesión → `HAConnectionError` (FR-004)
- [x] T005 [US1] `HAClient.rest_get_text_tail(path, *, lines, max_line_bytes=4096)` en `hermes/src/hermes/ha.py` (research R-2): lectura en flujo de `resp.content`, `deque(maxlen=lines)`, decodificación UTF-8 con `errors="replace"`, `ClientTimeout(total=30)`, comentario del porqué (fichero que puede tener cientos de MB; sin `Range`). T004 en verde (FR-004)

### Tests de las tools de logs (escritos antes de T011)

- [x] T006 [P] [US1] Tests de `ha_list_system_log` en `tests/test_tools_core_logs.py`: transformación de cada campo de data-model (ISO 8601 de `timestamp` y `first_occurred`, `source` como objeto); orden por `last_seen` descendente; `level` (mayúsculas o minúsculas) e `integration` (`homeassistant.components.mqtt`, `homeassistant.components.mqtt.client`, `custom_components.mqtt`; no `homeassistant.components.mqtt_room`); traza reducida a su última línea con `exception_truncated` y entera con `include_tracebacks=true`; `_third_party_text` presente; `level="verbose"` o `integration="Mqtt X"` → `invalid_argument` sin `ws_send`; respuesta que no es lista → error, no lista vacía; `unknown_command` → `system_log_unavailable` con `ha_code`; centinela (`password=centinela-012` y un JWT) en un mensaje y en una traza → tapado en la respuesta y ausente del log capturado; el log de Hermes lleva `count` y ningún mensaje; 200 entradas grandes con `response_max_bytes` pequeño → sobre con `truncated: true` y recuentos coherentes (FR-003, FR-017, FR-018)
- [x] T007 [P] [US1] Tests de `ha_get_error_log`: llama a `rest_get_text_tail("/error_log", lines=…)` con `lines` acotado (0 → 1, 5000 → 1000, por defecto 100); líneas redactadas (centinela y JWT) y `redacted: true`; sin nada que redactar → `redacted: false`; texto que no cabe → últimas líneas que caben, `truncated`, `lines_returned` y pista; `HAConnectionError(status=404)` → `error_log_unavailable` con `detail` y `hint` de data-model; otro error → `{"error": …}` redactado; el log de Hermes no lleva líneas (FR-004, FR-017)
- [x] T008 [P] [US3] Tests de `ha_get_log_levels`: `logger/log_info` con niveles 10, 20, 30, 40, 50, 0 y 15 → nombres DEBUG…NOTSET y «LEVEL 15» con `level_value`; orden por dominio; filtro `domain`; `domain` con forma inválida → `invalid_argument`; sobre común y recorte (FR-005, FR-018)
- [x] T009 [P] [US3] Tests de `ha_set_log_level`: (a) validación sin llamar a HA: nivel desconocido, `WARN`/`FATAL`, ninguna o las dos de `integration`/`module`, `module` con espacios o de más de 255, `persistence="always"`; (b) vista previa de integración: lee `logger/log_info`, `previous_level` del dominio (o `null` con nota si no está cargada), `new_level` en mayúsculas, `persistence_effect` de cada valor, efecto de `NOTSET`, token, y NINGÚN `ws_send` de escritura; (c) vista previa de módulo: `previous_level: null` con `previous_level_note` y sin leer `log_info`; (d) confirmación: un solo `ws_send` con `logger/integration_log_level` o `logger/log_level` y los cuatro campos; (e) token con otro nivel, otro objetivo, otro tipo de objetivo u otra persistencia → rechazado sin `ws_send`; `level="debug"` en la vista previa y `"DEBUG"` al confirmar → aceptado (se normaliza antes de atar); token reutilizado → rechazado; (f) HA `not_found` al confirmar → `not_found` y token completado con fallo; (g) lectura previa que falla → `preview_unavailable` sin token; (h) error de HA con un centinela → tapado; ni la vista previa ni los ficheros de `CONFIRMATIONS_DIR` lo contienen (FR-006, FR-017, SC-003, SC-004)
- [x] T010 [P] [US4] [US5] Tests de `ha_clear_system_log`: vista previa con `entries` y `by_level` y el texto de efecto de data-model, sin `call_service`; log vacío → `unchanged` sin token ni fichero de token; confirmación → un solo `call_service("system_log", "clear", {})` y `{"result": "ok"}`; token reutilizado o de otra tool → rechazado; lectura previa que falla → `preview_unavailable`; `unknown_command` en la lectura previa → `system_log_unavailable` sin token. Más un test de no regresión: `service_policy` sigue teniendo en la denylist `logger.set_level`, `system_log.clear`, `persistent_notification.dismiss` y `persistent_notification.dismiss_all` (FR-007, FR-020)

### Implementación

- [x] T011 [US1] [US3] [US4] `hermes/src/hermes/tools/core_logs.py` (research R-2…R-4, data-model): `register(mcp, ha_client, *, response_max_bytes)` con las cinco tools, `@ready`, docstrings en inglés que dicen lo que hacen y lo que no (fichero de log ausente bajo el Supervisor; la limpieza no toca fichero ni journal; persistencias), dos pasos con `create_confirmation_token`/`validate_confirmation_token`/`complete_confirmation_token`, redacción, sobre con `ajustar_lista_a_bytes`, últimas líneas con el helper de `sv_get_addon_logs` (si se mueve a `_common.py`, sin cambiar su comportamiento y con sus tests en verde), eventos de log de data-model. Comentarios en español con el porqué. T006–T010 en verde (FR-003…FR-007, FR-017, FR-018)
- [x] T012 [US5] Registro y anotaciones: `register_core_logs` en `hermes/src/hermes/tools/__init__.py` dentro de la comprobación de `core_diagnostics`, con `response_max_bytes`; `ha_set_log_level` y `ha_clear_system_log` en `_DESTRUCTIVE_EXACT` de `tools/_annotations.py` con el comentario de contracts/tools.md. Tests en `tests/test_tools_registration.py`: hints y títulos de las cinco según contracts/tools.md; con `core_diagnostics` desactivada no aparece ninguna; las de la 1.1.2 sin cambios (los invariantes existentes, incluido «pide token ⇔ destructiva», pasan sin excepciones nuevas) (FR-013, FR-015, FR-020)

### Tabla y generador (US5)

- [x] T013 [US5] Tabla: (a) tests primero: en `tests/test_generar_tabla.py`, una fila A de vía D cuya clave está en `_DEDICADAS_INICIALES` sale `dedicated` con la familia de su tool en la primera generación; en `tests/test_command_table.py`, `test_clase_a_de_via_dedicada_pendiente_de_su_spec` admite `dedicated` con una tool de una familia `desde="1.2.0"` y sigue fallando con `read`/`confirm`; en `tests/test_tools_generic_commands.py`, `ha_read_ws_command("system_log/list")` → `use_dedicated_tool` con `ha_list_system_log` y, con `core_diagnostics` desactivada, `family_disabled: true`; (b) `scripts/inventario/generar_tabla.py`: las cuatro claves en `_DEDICADAS_INICIALES` (`logger/integration_log_level` pasa de `ha_call_service` a `ha_set_log_level`) y `_clasificar` consulta el mapa para la clase A antes de la regla «pendiente» (research R-7); (c) `hermes/src/hermes/command_table.py`: `system_log/list`, `logger/log_info`, `logger/log_level` y `logger/integration_log_level` a `E("dedicated", "cubierto por <tool>", "core_diagnostics", tool=…, cap=…)` según data-model, sustituyendo el comentario de `logger/integration_log_level` por el porqué de la dedicada; (d) ejecutar el generador y comprobar que `git diff -- hermes/src/hermes/command_table.py` no cambia nada respecto a (c); anotarlo en el commit (FR-014, SC-002)

### Guía (US5)

- [x] T014 [US5] `hermes/src/hermes/tools/guide.py`: tema `core_diagnostics` con la parte de logs de contracts/tools.md (system log frente a error log, HA OS sin `duplicate_log_file`, niveles y persistencias, `NOTSET`, limpieza) y alias `logs`, `log`; línea en `diagnostics` que remite al tema nuevo. Tests en `tests/test_tools_guide.py`: el tema existe con sus alias; cada tool registrada de la familia `core_diagnostics` aparece nombrada en él (test genérico que el tramo B no tiene que tocar); el índice lo lista (FR-016)

### Banco (US1, US3, US4)

- [x] T015 [US1] [US3] [US4] Banco de Core (con el marcador y la base de la 010): `system_log:` en `tests/banco/ha_config/configuration.yaml` con comentario; `tests/banco/test_banco_core_logs.py`: el lector siembra con `system_log.write` (mensaje con un centinela) → `ha_list_system_log` lo ve con `count`, y el centinela sale tapado; `ha_get_error_log(lines=50)` devuelve líneas (en el banco hay fichero); `ha_get_log_levels` incluye `input_boolean`; `ha_set_log_level(integration="input_boolean", level="debug")` vista previa → el lector comprueba que no cambió → confirmación → el lector lee `logger/log_info` con 10 → limpieza con `NOTSET` por la tool o por el lector; `ha_set_log_level(module="homeassistant.components.input_boolean")` igual, comprobando con `logger/log_info` el nivel efectivo de ese logger; `ha_clear_system_log` vista previa → el lector ve las entradas → confirmación → el lector ve `system_log/list` vacío. `tests/banco/cobertura_012.py` con `PROBADAS_012 = {ha_set_log_level, ha_clear_system_log}` y `NO_EJECUTABLES_012 = {}`, sumada al invariante de escrituras de la 028 o, si no está integrada, con `tests/test_banco_cobertura_012.py` propio (contracts/tools.md). Si la 010 no está, pendiente con nota (S-01) (FR-019, SC-005)

### Documentación y cierre del tramo

- [x] T016 Documentación parcial: sección «Diagnóstico de Core (spec 012)» en `## [1.2.0]` de `hermes/CHANGELOG.md` con las cinco tools, la familia y las entradas de la tabla; fila 012 de la tabla del programa en `docs/HOJA-DE-RUTA.md` → «en curso (tramo A)» (FR-021)
- [x] T017 [US5] Revisión del principio V: leer cada docstring y el tema de la guía contra lo que hace el código (la limpieza no toca el fichero, el nivel de módulo no se conoce, `error_log_unavailable` dice la causa real); corregir lo que no cuadre
- [x] T018 Control negativo del tramo A, anotando recuentos: (a) quitar `redact_secrets` de los mensajes o de las líneas → caen los centinelas de T006/T007; (b) emitir token sin leer `log_info` / enviar el comando en la vista previa → caen los de T009(b); (c) atar el token sin `level` (o sin normalizarlo) → cae T009(e); (d) devolver lista vacía cuando la respuesta no es lista → cae T006; (e) tratar el 404 como error genérico → cae T007; (f) en `rest_get_text_tail`, acumular todo el cuerpo sin `maxlen` → cae el de últimas líneas o el de tamaño de T004; (g) dejar `system_log/list` en `deny` → cae el de la genérica de T013; quitar la consulta del mapa para la clase A → cae el del generador; (h) sacar `core_logs` de la familia → cae T002; quitar `ha_set_log_level` de `_DESTRUCTIVE_EXACT` → cae el invariante de registro. Restaurar y comprobar verde
- [x] T019 Cierre del tramo A: suite completa (exactamente los 6 fallos conocidos en Windows), CI de la rama en verde, revisión del diff buscando datos personales e identificadores de modelos (principio VIII, FR-022), commit en español con la línea base de T001 y los recuentos de T018 (SC-006, SC-007)

---

## Tramo B — validación, diagnósticos y notificaciones (US2, US3, US4, US5)

Los tests de cada módulo se escriben y se ven fallar antes de su
implementación.

- [x] T020 [P] [US2] Tests en `tests/test_tools_core_validation.py`: `ha_validate_config` con las tres partes → un solo `ws_send({"type": "validate_config", …})` con solo las enviadas y respuesta por parte con `saved: false`; con `config` de automatización (`triggers`/`conditions`/`actions` y las formas en singular) y de script (`sequence`) → mapeo de research R-1 y `not_validated` con el resto de claves ordenadas; `trigger` y `triggers` a la vez, `config` y partes a la vez, nada, `config` que no es objeto → `invalid_argument` sin `ws_send`; `error` de HA con un centinela → tapado. `ha_test_condition`: `result` y `template_errors` tal cual; `variables` pasa; `condition` que no es objeto → `invalid_argument`; `invalid_format` → `invalid_condition` y `home_assistant_error` → `condition_error`, con `detail` redactado; Core caído → error de conexión (FR-001, FR-002, FR-017)
- [x] T021 [US2] `hermes/src/hermes/tools/core_validation.py`: las dos tools según data-model y research R-1, docstrings que dicen que no guardan y qué no se valida. T020 en verde (FR-001, FR-002)
- [x] T022 [P] [US3] Tests en `tests/test_tools_integration_diagnostics.py`: `ha_list_diagnostics_handlers` sin y con `domain` (`diagnostics/list` frente a `diagnostics/get`), dominio sin plataforma → `diagnostics_not_supported`, `unknown_command` → `diagnostics_unavailable`; `ha_get_config_entry_diagnostics`: entrada inexistente → `not_found` sin `_request_json`; dominio sin handler de entrada → `diagnostics_not_supported` sin `_request_json`; camino feliz → `GET /diagnostics/config_entry/<entry_id>` y respuesta con `data`, `issues`, sin `system_info`; con `include_system_info` → las cuatro claves; `keys` válidas → solo esas y `keys_returned`; clave inexistente → `invalid_argument` con las disponibles; diagnóstico mayor que `response_max_bytes` → `response_too_large` con `data_keys` y tamaños, nunca JSON cortado; centinela bajo `token` y un JWT en un texto de `data` y de `issues` → tapados; `entry_id` con `/` o `..` → `invalid_argument`; `ha_get_device_diagnostics`: dueña tomada de `config_entry_id` del registro, ruta `…/device/<device_id>`; dispositivo inexistente → `not_found`; sin `config_entry_id` → `diagnostics_not_supported` con `reason`; integración sin handler de dispositivo → `diagnostics_not_supported` sin descarga; el log de Hermes no lleva datos (FR-008, FR-009, FR-010, FR-017, FR-018)
- [x] T023 [US3] `hermes/src/hermes/tools/integration_diagnostics.py` según research R-5 y data-model (comprobaciones previas, `validate_path_segment`, redacción doble, recorte por claves). T022 en verde (FR-008…FR-010)
- [x] T024 [P] [US4] Tests en `tests/test_tools_persistent_notifications.py`: lista ordenada por `created_at` descendente, campos de data-model, `_third_party_text`, centinela tapado, sobre y recorte; `ha_dismiss_persistent_notification`: id vacío → `invalid_argument`; id inexistente → `not_found` sin token; vista previa con título, mensaje redactado, `message_truncated` con un mensaje de 5000 caracteres, sin `call_service`; confirmación → relectura y un solo `call_service("persistent_notification", "dismiss", {"notification_id": …})`; desaparecida entre medias → `already_dismissed` sin `call_service`; token con otro id → rechazado; ni la vista previa ni `CONFIRMATIONS_DIR` contienen el centinela (FR-011, FR-012, FR-017, FR-018, SC-003, SC-004)
- [x] T025 [US4] `hermes/src/hermes/tools/persistent_notifications.py` según research R-6 y data-model. T024 en verde (FR-011, FR-012)
- [x] T026 [P] [US5] Tests de familia y registro: `tests/test_tool_families.py` con los cuatro módulos en `core_diagnostics`; `tests/test_tools_registration.py` con hints y títulos de las siete nuevas según contracts/tools.md (`ha_validate_config` y `ha_test_condition` de solo lectura sin prefijo; `ha_dismiss_persistent_notification` destructiva); con `core_diagnostics` desactivada no aparece ninguna de las 12; las de la 1.1.2 sin cambios (FR-013, FR-015, FR-020, SC-001)
- [x] T027 [US5] Familia con los cuatro módulos en `tool_families.py`; registro de los tres módulos en `tools/__init__.py` bajo la familia; `_READ_ONLY_EXACT` (`ha_validate_config`, `ha_test_condition`, con comentario: no tienen prefijo de lectura y no guardan) y `_DESTRUCTIVE_EXACT` (`ha_dismiss_persistent_notification`) en `tools/_annotations.py`. T026 en verde (FR-013, FR-015)
- [x] T028 [US5] Tabla: `validate_config`, `test_condition`, `diagnostics/list`, `diagnostics/get` y `persistent_notification/get` a `dedicated` (data-model) en `command_table.py` y en `_DEDICADAS_INICIALES`; regenerar y comprobar que no cambia nada; test de la genérica con una de ellas (FR-014, SC-002)
- [x] T029 [US5] Guía: completar el tema `core_diagnostics` (validación, diagnósticos, notificaciones, receta «¿por qué falla esta integración?») y alias `notifications`, `validation`; el test genérico de T014 cubre las 12 (FR-016)
- [x] T030 [US5] Revisión del principio V de las siete tools nuevas y del tema completo, como T017
- [x] T031 [US2] [US3] [US4] Banco: `diagnostics:` en la configuración del banco; elegir la integración sin red con diagnóstico de entrada (research R-8) y anotarla; `tests/banco/test_banco_core_diagnostico.py`: `ha_validate_config` con una automatización válida y otra con un trigger inválido; `ha_test_condition` con una condición de estado sobre un `input_boolean` del lector (verdadera y falsa); `ha_list_diagnostics_handlers`; `ha_get_config_entry_diagnostics` de la entrada creada por el lector (limpieza al cerrar); `ha_get_device_diagnostics` en su camino `diagnostics_not_supported`; notificación creada por el lector → listada → descarte en dos pasos → el lector no la ve. `ha_dismiss_persistent_notification` a `PROBADAS_012`. Si la integración no carga, el camino feliz del diagnóstico de entrada queda en unitarios y como pendiente manual en la matriz de la 014, con el motivo (FR-019, SC-005)
- [x] T032 Documentación final: CHANGELOG (sección de la 012 completa: 12 tools, familia, 9 entradas de la tabla, el caso del log sin fichero); hoja de ruta → «hecha» con la lista de lo probado en el banco y los pendientes manuales; `README.md` y `README.es.md` sincronizados (tools nuevas en la lista por áreas y el recuento si lo llevan); `hermes/DOCS.md` si la opción `tool_families_disabled` enumera familias; `specs/008-cobertura-total/plan.md`: filas CAP-040, CAP-041, CAP-042 y CAP-047 de la matriz con las tools y los ficheros de test, sin cambiar las columnas que lee `_matriz_008` (sub-feature y vía) (FR-021)
- [x] T033 Control negativo del tramo B, anotando recuentos: (a) aceptar `config` y partes a la vez → cae T020; no informar `not_validated` → cae; (b) descargar sin comprobar el handler → caen los de `diagnostics_not_supported` sin descarga; (c) devolver el diagnóstico sin mirar el tope → cae el de `response_too_large`; quitar `redact_structure` → cae el centinela bajo `token`; (d) tomar la dueña de `config_entries[0]` en vez de `config_entry_id` → cae el del dispositivo; (e) en el descarte, no releer al confirmar → cae `already_dismissed`; guardar el mensaje sin redactar en la vista previa → cae el del fichero del token; (f) dejar `diagnostics/list` en `deny` → cae el de la genérica; quitar `ha_validate_config` de `_READ_ONLY_EXACT` → cae el de hints. Restaurar y comprobar verde
- [x] T034 Cierre del tramo B: suite completa (los 6 fallos conocidos y ninguno más), CI de la rama y banco en verde, revisión del diff (principio VIII, FR-022), commit con los recuentos de T033 (SC-006, SC-007)

---

## Dependencias

- T001 antes que todo. T002→T003; T004→T005; T006–T010 (en paralelo) →
  T011 (necesita T005); T011→T012→T013→T014; T015 tras T012 (y la 010);
  T016–T019 al final del tramo.
- Tramo B tras el A integrado: T020→T021, T022→T023, T024→T025 en paralelo
  entre sí; T026→T027 tras T021, T023 y T025; T028, T029 tras T027; T031 tras
  T027; T030, T032–T034 al final.

## Paralelismo

- Tramo A: T002, T004 y T006–T010 a la vez (ficheros distintos salvo
  `test_tools_core_logs.py`, que T006–T010 escriben en clases separadas).
- Tramo B: los tres pares de test e implementación en paralelo.

## Estrategia

MVP = tramo A: con él, el agente ya puede leer el log del sistema, los niveles
y depurar una integración subiendo su nivel, que es lo que más se pide. El
tramo B añade la validación previa al guardado (que la 017 usará), los
diagnósticos y las notificaciones.

## Notas del tramo

(Las rellena cada agente al cerrar su tramo: desviaciones, hallazgos en el
banco, decisiones.)

### Tramo A (T001–T019)

- **T001**: merge `--no-ff` de `feat/cobertura-total` (009, 010, 011 entera y
  028) sin conflictos. Línea base en Windows tras integrar: 2320 passed, 65
  skipped, 6 failed (los 6 conocidos).
- **Extras del supervisor**: (1) `logger.set_default_level` entra en la
  `CALL_SERVICE_DENYLIST` (`logger.set_level` ya estaba), con test por
  pertenencia y por `ha_call_service` (pide token) y control negativo;
  (2) la nota del inventario de `logger/log_level` dice ya que escribe (fija
  el nivel de un módulo) y no lo agrupa con las lecturas; (3) el `hint` de
  `error_log_unavailable` remite a `sv_get_core_logs` (013) y a
  `duplicate_log_file`, sin plan B automático (duda D-1 resuelta así).
- **Desviaciones**:
  - Las vistas previas siguen el formato de siempre de
    `create_confirmation_token` (`confirmation_token`, `expires_in_seconds` y
    los campos de data-model dentro de `preview`), no el plano que dibuja
    data-model con `expires_in`.
  - Las tools devuelven `dict` (contrato `-> object` de la 011), no JSON en
    texto como `repairs.py`.
  - `_ultimas_lineas_que_caben` pasa de `addons.py` a `_common.py` como
    `ultimas_lineas_que_caben(…, clave=…)`; `sv_get_addon_logs` la usa con
    `clave="logs"` sin cambiar su comportamiento (sus tests, en verde).
  - El generador ya no añade «(acción de HA)» a una fila «cubierto» por
    acción genérica si su tool no es `ha_call_service*`
    (`logger/integration_log_level` → `ha_set_log_level`).
  - `ha_get_log_levels` y `ha_list_system_log` devuelven el sobre con
    `count`, `returned`, `truncated` e `items` (y `_response_limit` al
    recortar).
  - Al pasar a 225 tools, README, README.es y DOCS cambian el recuento, la
    fila de la familia y la frase «apagando las familias de la 1.2.0 tienes la
    1.1.2» (ahora son dos: `generic_commands` y `core_diagnostics`).
  - `test_banco_cobertura_escrituras.py`: el recuento de las que modifican
    pasa de 126 a 128 y `PROBADAS_012` se suma a `TOOLS_EXIGIDAS_DEL_JOB`.
- **Controles negativos (T018)**: ver el mensaje del commit del tramo A.

### Tramo B (T020–T034)

- **Línea base** al empezar (punta `8f513e3`): 2388 passed, 70 skipped, 6
  failed (los 6 conocidos). Al cerrar: 2449 passed, 75 skipped (los 5 tests
  nuevos del banco, que fuera del job se saltan), 6 failed (los mismos).
- **Banco (R-8)**: el diagnóstico de entrada se prueba con una entrada de
  `local_calendar` que el lector crea por REST (`create_empty`, sin red ni
  hardware) y borra al cerrar; `diagnostics:` entra en la configuración del
  banco. `ha_get_device_diagnostics` solo en su camino
  `diagnostics_not_supported`, con un dispositivo de `kitchen_sink` (sin
  plataforma de diagnóstico): ninguna integración sin hardware ni nube ofrece
  diagnóstico de dispositivo en 2026.11.1, así que su camino feliz queda en
  los unitarios y como prueba manual pendiente. La matriz de la 014 no está
  integrada en esta rama: el pendiente va en la fila CAP-042 de la matriz de
  la 008 y en la hoja de ruta.
- **Desviaciones**:
  - Como en el tramo A: respuestas `dict` y vistas previas con el formato de
    siempre de `create_confirmation_token`.
  - `ha_validate_config` con una `config` sin ninguna de las tres partes →
    `invalid_argument` (no lo decía data-model): validar nada no puede
    responder como si todo estuviera bien.
  - `keys` con una clave inexistente → `invalid_argument` con
    `available_keys` (data-model dice «con las disponibles» sin nombre de
    campo); `keys` vacía o no lista de textos → `invalid_argument`.
  - `ha_list_diagnostics_handlers(domain=…)` devuelve el mismo sobre con un
    solo elemento.
  - `diagnostics_not_supported` de un dispositivo sin `config_entry_id` lleva
    `device_id` (no hay dominio que dar).
  - `template_errors` de `ha_test_condition` pasa por `redact_secrets` (sin
    secretos sale tal cual).
  - `ha_dismiss_persistent_notification` y `ha_clear_system_log` llaman a su
    acción con `allow_dangerous=True` tras validar su propio token: la acción
    está en la denylist y `HAClient.call_service` la rechazaría.
  - Al pasar a 232 tools, README, README.es y DOCS cambian el recuento y la
    fila de la familia; el invariante de escrituras pasa de 128 a 129.
- **Controles negativos (T033)**: ver el mensaje del commit del cierre.
- **CI (T034)**: el primer run del banco cayó en el test del diagnóstico de
  dispositivo, que leía con `llamar` un rechazo esperado (Hermes marca con
  `isError` toda respuesta de error); corregido con `call_tool`, como las
  genéricas. Run final en verde: pytest 3.12 y 3.13, y banco de Core con 56
  passed y 3 xfailed (los de la 028); `local_calendar` carga en la imagen y
  su diagnóstico de entrada se prueba de verdad. Semgrep en verde.

---

## Fase 3: Convergencia

Añadida por la revisión independiente y `speckit-converge` sobre la punta de la
rama (`32bdf50`). Severidad entre corchetes.

- [x] T035 [MEDIO] Una línea del log de errores de más de `max_line_bytes` se corta ANTES de redactarla (`HAClient.rest_get_text_tail`, `hermes/src/hermes/ha.py`, `guardar`; `ha_get_error_log` redacta después en `tools/core_logs.py`), y un secreto que cruce el corte queda a medias y sin tapar: con `{"…", "password": "hunter2-supersecret"}` cortado dentro del valor, `_JSON_SECRET_RE` ya no ve la comilla de cierre y sale `"password": "hunter2 …[line truncated]` (comprobado con un HAClient y una respuesta en flujo simulada). Arreglo mínimo: al recortar, retroceder hasta el último separador (espacio, coma, comilla, `=`, `:`) antes de la marca, de modo que no quede un trozo de valor, y redactar después; test con un centinela JSON y otro `clave=valor` justo en el corte, con control negativo per FR-017, SC-004 (partial)
- [x] T036 [MEDIO] El manejador de `system_log` de HA está a nivel WARNING (`system_log/__init__.py`, `handler.setLevel(logging.WARNING)`; también `system_log.write`, que pasa por `logging`): ninguna línea DEBUG ni INFO llega nunca al log del sistema. Pero la receta «¿por qué falla esta integración?» de `hermes_guide("core_diagnostics")` dice subir a DEBUG y luego mirar `ha_list_system_log`, y el argumento `level` de `ha_list_system_log` ofrece DEBUG e INFO, que nunca devuelven nada. Arreglo mínimo: la guía y el docstring dicen que el log del sistema solo guarda WARNING o más y que las líneas DEBUG van al fichero (`ha_get_error_log`) o al journal (`sv_get_core_logs`, 013); `level` acepta solo WARNING, ERROR y CRITICAL (o lo dice); test del texto per FR-016, FR-003, principio V (contradicts)
- [x] T037 [BAJO] La vista previa de `ha_set_log_level` (`tools/core_logs.py`, `persistence_effect`) no dice lo que hace HA con la persistencia (`logger/helpers.py`, `LoggerSettings.async_update` y `_async_data_to_save`): con `NOTSET` se borra el ajuste guardado sea cual sea `persistence`, pero con `permanent` la vista previa dice «Saved: applied on every start until changed»; y con `none` se borra además cualquier nivel guardado antes (`once`/`permanent`) para ese objetivo, cosa que la vista previa no avisa. Arreglo mínimo: con `NOTSET`, `persistence_effect` dice que la persistencia no aplica; con `none`, que también quita un nivel guardado antes; test de los dos textos per FR-006, principio V (partial)
