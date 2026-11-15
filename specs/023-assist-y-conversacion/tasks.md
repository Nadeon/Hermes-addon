---
description: "Tareas de la sub-feature 023 — Assist y conversación (Hermes 1.2.0)"
---

# Tareas: Assist y conversación (023)

**Entrada**: `specs/023-assist-y-conversacion/` (spec.md, plan.md,
research.md, data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `DummyMCP` o
`_RecordingMCP`, `AsyncMock` de `ws_send`, `structlog.testing.capture_logs`.
Datos ficticios (`light.salon`, `conversation.ejemplo_llm`,
`assist_satellite.salon`, `frase centinela del banco`, `centinela-023`, un
`device_id` de 32 hex inventado). Nada de la instalación real ni de las tools
MCP de Hermes.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`.
Línea base en Windows al especificar (2026-11-15, punta `1752984`): 3611
passed, 111 skipped, 6 failed (los 6 conocidos). El tramo termina con
exactamente esos 6 fallos en local; la referencia es el CI de Linux.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 analizar, US2 agentes y frases, US3 procesar con
confirmación, US4 pipelines, motores y satélites por la tabla, US5 nada se
rompe.

## Tramos de implementación

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **1** — todo | **T001–T018** | Familia `conversation`; `ha_list_conversation_agents`, `ha_list_conversation_sentences`, `ha_debug_conversation` y `ha_process_conversation` registradas, anotadas y probadas; 5 entradas de CAP-060 a `dedicated` con el generador al día; 3 entradas de CAP-061/CAP-062 revisadas; tema `conversation`; banco de CAP-060, CAP-061 y CAP-062; unitarios de CAP-063; inventarios; documentación y matriz de la 008 |

Si el contexto no da para todo, se commitea al cerrar T012 (suite en verde) y
se sigue en un segundo commit; el tramo no se cierra con la suite en rojo.

---

## Tramo 1

### Preparación

- [x] T001 Comprobar la base: la rama contiene la 011 (tabla, genéricas, familias, `_DEDICADAS_INICIALES` con `_ConMatiz`), la 010/028 (banco e inventario de escrituras), la 014 (matriz), la 033 (inventario de argumentos atados) y la 018 (`sobre_de_lista`); anotar si la 021 está integrada (decide el texto de T012). Línea base de la suite, anotada en el commit

### Tests primero

- [x] T002 [P] [US5] Tests en `tests/test_tool_families.py`: familia `conversation`, `desde="1.2.0"`, desactivable, módulo `conversation`, descripción sin «read only» (FR-010)
- [x] T003 [P] [US2] Tests en `tests/test_tools_conversation.py` (`TestListarAgentes`, `TestListarFrases`, `TestErroresDeHA`): agentes con `is_default_agent`, el integrado primero y el resto por `id`, `supported_languages` `"*"` o lista; `language`/`country` pasados a HA solo si se dan; `include_language_scores=true` añade `default_agent_language_scores` (y sin él no se llama a `language_scores`); frases ordenadas sin distinguir mayúsculas, sin repetir, `search` sin distinguir mayúsculas, `limit` y `total`; `language` o `country` con forma inválida, `search` vacío, `limit` 0 o 501 → `invalid_argument` sin `ws_send`; `unknown_command` → `conversation_not_loaded` (en las CUATRO tools, también en la vista previa de procesar); `unauthorized` de HA en frases → `unauthorized`; otro error → redactado (centinela `token=centinela-023` tapado); log sin frases ni nombres de agentes (FR-001, FR-002, FR-011, FR-012)
- [x] T004 [P] [US1] Tests en `tests/test_tools_conversation.py` (`TestAnalizar`): resultados en el orden de las frases; `null` → `{"sentence", "match": false, "recognized": false}`; `source: "trigger"` → solo `match`, `source`, `sentence_template` y la nota; `custom` con `file`; 60 objetivos → 50 con `targets_total: 60` y `targets_truncated: true`; respuesta mayor que el tope → objetivos quitados por el final y, si no cabe, `response_too_large`; 0 o 21 frases, una vacía, una de 501 caracteres o `device_id` sin la forma → `invalid_argument` sin `ws_send`; nunca se llama a `conversation/process` (comprobado sobre todas las llamadas a `ws_send`) (FR-003, FR-011)
- [x] T005 [P] [US3] Tests en `tests/test_tools_conversation.py`:
  - `TestProcesarVistaPrevia`: sin token no se llama a `conversation/process`; con el agente integrado (sin `agent_id` o con `conversation.home_assistant`) la vista previa trae `agent` (`is_default_agent: true`, `local: true`) y `recognition` del `debug` con la misma frase, `language` y `device_id`; `source: "trigger"` → el aviso de la automatización; `match: false` → token igual y la nota; `debug` que falla → `recognition.checked: false` y token; con `conversation.ejemplo_llm` → `local: "unknown"`, sin `recognition`, sin llamar a `debug`, con el aviso del agente externo; `agent_id` que no está → `agent_not_found` con `available_agents` y sin token; argumentos inválidos → `invalid_argument` sin `ws_send`
  - `TestProcesarToken`: el token emitido valida con los mismos cinco argumentos; cambiar `text`, `agent_id`, `language`, `conversation_id` o `device_id` (uno a uno, también de `None` a un valor) → token rechazado y sin `conversation/process`; token reutilizado → rechazado; el fichero del token no contiene el texto (centinela en `text`)
  - `TestProcesarConfirmado`: con token, `conversation/process` con solo los campos dados y `timeout_seconds=90`; la respuesta trae `response_type`, `speech`, `data`, `language`, `conversation_id`, `continue_conversation`; `speech` de un LLM más largo que el tope → recortado con `speech_truncated: true` y dentro del tope; centinela en `speech` y en `data` → tapado; `HAConnectionError` sin código de HA (el plazo vencido de `ws_send` o la conexión caída esperando) → `outcome_unknown` con el texto de data-model y el token marcado fallido (no reutilizable); error de HA → `ha_error` redactado y token fallido
  - Log en los tres: `conversation_processed` con `is_default_agent`, `response_type` y recuentos, y ni el texto, ni `speech`, ni `conversation_id`, ni `conversation.ejemplo_llm`, ni `light.salon` (FR-004, FR-005, FR-011, SC-003, SC-004)
- [x] T006 [P] [US5] Tests en `tests/test_tools_registration.py`: las cuatro en `_HINTS_NUEVAS_1_2_0` (`R-I-` las tres de lectura con sus títulos; `-D-O` y «Process conversation (Home Assistant)» la de procesar); solo `ha_process_conversation` toma `confirmation_token`; con `conversation` desactivada no se registra ninguna y el resto no cambia (SC-001) (FR-007, FR-010)
- [x] T007 [P] [US3] Tests en `tests/test_tools_conversation.py` (`TestDescripciones`): la descripción de `ha_process_conversation` menciona que ejecuta, `confirmation_token`, «external» (el texto puede salir) y `ha_debug_conversation`; la de `ha_debug_conversation`, que no ejecuta nada; la de `ha_list_conversation_sentences`, que son solo las de disparadores de frase; la de agentes, que solo el integrado es local seguro (FR-006)

### Implementación

- [x] T008 [US1] [US2] [US3] `hermes/src/hermes/tools/conversation.py` con las cuatro tools de contracts/tools.md (docstring «POR QUÉ ASÍ», validación antes de llamar, redacción, sobre común, recortes, `create_confirmation_token`/`validate_confirmation_token`/`complete_confirmation_token`, plazo de 90 s, log con recuentos). T003–T005 y T007 en verde (FR-001…FR-006, FR-011, FR-012)
- [x] T009 [US5] `hermes/src/hermes/tool_families.py` (familia `conversation`), `hermes/src/hermes/tools/__init__.py` (registro bajo `if _activa("conversation")`) y `hermes/src/hermes/tools/_annotations.py` (`ha_debug_conversation` en `_READ_ONLY_EXACT`; `ha_process_conversation` en `_DESTRUCTIVE_EXACT`, `_NON_IDEMPOTENT_EXACT` y `_OPEN_WORLD`, con el porqué). T002 y T006 en verde (FR-007, FR-010)

### Tabla

- [x] T010 [P] [US3] [US4] Tests en `tests/test_tools_generic_commands.py`: `ha_read_ws_command` y `ha_call_ws_command` con cada uno de los cinco comandos de CAP-060 → `use_dedicated_tool` con su tool y sin `ws_send` (y `language_scores` → `ha_list_conversation_agents`); con `conversation` desactivada → `family_disabled: true`; `TestAssistPorLaTabla` con la tabla real: cada comando `read` de CAP-061/CAP-062/CAP-063 pasa por `ha_read_ws_command` y lo rechaza `ha_call_ws_command`, y al revés con los `confirm`; `assist_satellite/get_configuration` y `set_wake_words` (este en dos pasos, token atado a la carga) con la WebSocket simulada; `pipeline_debug/get` con un evento `tts-end` con `tts_output.url = "/api/tts_proxy/centinela-023.mp3"` y `token` → los dos tapados en la respuesta y ausentes del log; `assist_pipeline/run`, `device/capture` e `intercept_wake_word` rechazados por las dos (FR-008, FR-009, FR-014)
- [x] T011 [US3] [US4] `hermes/src/hermes/command_table.py`: las cinco de CAP-060 a `dedicated` y las tres revisadas (data-model, research R-5, motivos revisados contra el código); las claves en `_DEDICADAS_INICIALES` de `scripts/inventario/generar_tabla.py` (bloque comentado «023», `language_scores` con `_ConMatiz`); ejecutar el generador y comprobar que `git diff -- hermes/src/hermes/command_table.py` no cambia nada respecto a la edición a mano (y generada desde cero en un temporal, las cinco salen idénticas); test nuevo `test_dedicadas_de_la_023` en `tests/test_command_table.py` (forma exacta, clave en el mapa, ninguna entrada «(spec 023)»: SC-002). T010 y `tests/test_command_table.py` en verde (FR-008, FR-009)

### Guía

- [x] T012 [US1] [US2] [US3] [US4] Tests en `tests/test_tools_guide.py` (tema `conversation` con contenido; nombra las cuatro tools, `confirmation_token`, el aviso del agente externo, `assist_pipeline/pipeline/list`, `ai_task/preferences/set`, `assist_satellite/set_wake_words` y que `assist_pipeline/run` no está; los alias resuelven a él; el índice lo menciona; las huellas de los temas existentes no cambian; no nombra `ha_list_exposed_entities` si esa tool no está registrada) y después el tema en `hermes/src/hermes/tools/guide.py` (en español; ver plan, «Diseño»), con su línea en las instrucciones del servidor si la familia está activa y en la lista de temas del docstring de `hermes_guide` (FR-013)

### Banco de Core

- [x] T013 [US1] [US2] [US3] `tests/banco/test_banco_conversacion.py` (marcador `banco`, helpers de la 010): crear con tools ya probadas un `input_text` de apoyo y una automatización con `trigger: conversation` y la frase centinela cuya acción escribe en él; `ha_list_conversation_sentences(search=…)` la lista (sondeo hasta que aparece); `ha_list_conversation_agents` trae `conversation.home_assistant` como integrado y, con `include_language_scores=true`, `preferred_language`; `ha_debug_conversation` → `match: true`, `source: "trigger"` y una frase sin sentido → `match: false`; el lector ve el `input_text` sin cambios; `ha_process_conversation` sin token → vista previa con `recognition` y el lector sigue sin ver cambios; con el token → el lector ve el valor escrito; el mismo token otra vez → rechazado; `ha_read_ws_command("conversation/process", …)` → `use_dedicated_tool`; limpieza (automatización e `input_text`) en `finally` (FR-014, SC-003, SC-005)
- [x] T014 [US4] `tests/banco/ha_config/configuration.yaml`: `assist_pipeline:` y `ai_task:` con comentario del porqué (y `llm:` si `llm/api/list` responde `unknown_command`); `tests/banco/test_banco_assist.py`: lecturas por `ha_read_ws_command` de `assist_pipeline/pipeline/list`, `language/list`, `device/list`, `pipeline_debug/list` (con el id del preferido), `tts/engine/list`, `stt/engine/list`, `llm/api/list` y `ai_task/preferences/get`; `tts/engine/voices` y `wake_word/info` con un id inexistente llegan a HA (error de HA, no rechazo de Hermes); por `ha_call_ws_command` en dos pasos: crear un pipeline de prueba (con el `example` de la tabla), actualizarlo, marcarlo preferido, devolver el preferido original y borrarlo, con el lector comprobando cada efecto; `ai_task/preferences/set` con los valores actuales y lectura de vuelta. Un fallo real de HA en un comando concreto es un hallazgo: `xfail` estricto que espera ese fallo, registrado en `XFAIL_PERMITIDOS_023` de `tests/banco/cobertura_023.py` y sumado a `XFAIL_DEL_JOB` (el job no admite otros). Si una integración entera no carga sin internet, se quita de la configuración (que el resto del banco no se resienta), esas pruebas pasan a unitarios y la causa queda escrita en el test, en el commit y en la hoja de ruta (FR-009, FR-014, SC-005)
- [x] T015 [US5] `tests/banco/cobertura_023.py` (`PROBADAS_023 = {"ha_process_conversation"}` y `XFAIL_PERMITIDOS_023` —vacío salvo hallazgo de T014—, docstring como `cobertura_015.py`); sumarlo a la unión del invariante (`tests/test_banco_cobertura_escrituras.py` y `cobertura_escrituras.py`) y a `TOOLS_EXIGIDAS_DEL_JOB`; si `tests/test_banco_cobertura.py` tiene la clase de lecturas del programa, añadir las tres de lectura; fila `ha_process_conversation | banco de Core | ok | spec 023; disparador de frase del banco` en la matriz de `docs/HOJA-DE-RUTA.md`; entrada `"ha_process_conversation": {"text": A, "agent_id": A, "language": A, "conversation_id": A, "device_id": A}` en `tests/test_confirmation_args_inventory.py` con su línea en el docstring (FR-014)

### Cierre

- [x] T016 Control negativo, anotando recuentos: (a) quitar `device_id` del dict del token → cae su caso de T005; (b) no comprobar el agente (emitir token con un `agent_id` inexistente) → cae `agent_not_found`; (c) registrar `text` en el log → cae el centinela de log; (d) quitar `redact_extra` de `pipeline_debug/get` → cae el de T010; (e) dejar `conversation/process` en `deny` → caen T010 y `test_dedicadas_de_la_023`; (f) sacar `ha_process_conversation` de `PROBADAS_023` → cae el invariante nombrándola; (g) quitar `ha_process_conversation` de `_OPEN_WORLD` → cae el de hints; (h) tratar el plazo vencido como error normal → cae `outcome_unknown`. Restaurar y comprobar verde
- [x] T017 Documentación (FR-015): sección «Assist y conversación» en `## [1.2.0]` de `hermes/CHANGELOG.md` (cuatro tools, familia, dos pasos y aviso del agente externo, tabla de CAP-061…063 revisada con la `url` del audio tapada); recuento de tools (+4) y fila de la familia en `README.md`, `README.es.md` y `hermes/DOCS.md` (`tool_families_disabled`); `SECURITY.md`: `ha_process_conversation` siempre confirmada aunque el comando WS `conversation/process` no pase por la denylist de acciones; 023 «hecha» en la tabla del programa de `docs/HOJA-DE-RUTA.md` (con lo que no se pudo probar: otro agente y satélites, en unitarios); filas CAP-060…CAP-063 de la matriz de `specs/008-cobertura-total/plan.md` con las tools, entradas y ficheros de test definitivos
- [x] T018 Suite completa (los 6 fallos conocidos y ninguno más); revisión del diff buscando datos personales e identificadores de modelos (principio VIII); commit(s) en español con la línea base de T001, el resultado de la regeneración de T011 y los recuentos de T016; marcar las tareas hechas en este fichero

## Notas de la implementación

- **T001**: la rama ya contenía `feat/cobertura-total` (el merge no trajo
  nada: la 017 aún no estaba integrada). La 021 no está integrada: el tema
  `conversation` no nombra sus tools; la referencia cruzada se completa al
  integrar. Línea base: 3611 passed, 111 skipped, 6 failed (los conocidos).
- **T011**: regenerada en su sitio, idéntica; desde cero en un temporal, las
  cinco entradas de CAP-060 salen iguales.
- **T013 (desviación)**: el efecto se observa con un `input_boolean` de
  apoyo (helper ya probado del banco, `SesionEscrituras.input_boolean`), no
  con un `input_text`: mismo papel y menos código.
- **T014**: además de `assist_pipeline:` y `ai_task:`, se carga `llm:` (no
  admite parámetros y vacío no avisa). `ai_task:` por YAML deja el aviso
  `config_entry_only_ai_task` del dominio `homeassistant` en Repairs: ningún
  test del banco cuenta los avisos de ese dominio. Sin hallazgos:
  `XFAIL_PERMITIDOS_023` vacío.
- **T015 (añadido)**: las tres de lectura (`LECTURAS_023`) también se exigen
  por ejecución en el job, como las de la 029.
- **Hallazgo del supervisor (`tts_proxy`)**: además del `redact_extra` de
  `pipeline_debug/get`, las genéricas tapan cualquier `/api/tts_proxy/<token>`
  en sus respuestas (`_RE_TTS_PROXY`), con test centinela.
- **T016**: los ocho controles negativos caen donde se espera (recuentos en
  el commit) y se restauraron.

## Dependencias

- T002–T007 antes de T008–T009; T010 antes de T011; T012 tras T008; T013–T015 tras T008–T011; T016–T018 al final.
- [P]: T002–T007 entre sí; T010 con T012 (ficheros distintos).
