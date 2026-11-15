# Plan de implementación: Assist y conversación (023)

**Rama**: `feat/023-assist-y-conversacion` (sale de `feat/cobertura-total`,
punta `1752984`, 293 tools) · **Spec**: [spec.md](spec.md) · **Paraguas**:
[008](../008-cobertura-total/plan.md), tarea T022, «S, 1 tramo».

## Resumen

Cuatro tools nuevas en una familia nueva, `conversation`: listar agentes
(con las puntuaciones de idioma del agente integrado bajo demanda), listar
las frases de los disparadores de frase, analizar frases sin ejecutarlas y
procesar una frase **con confirmación en dos pasos**. La vista previa de
procesar dice el agente, si es local, y, con el agente integrado, lo que HA
reconoce (intent y entidades objetivo) sin ejecutar nada; con otro agente,
avisa de que el texto sale hacia él y de que Hermes no puede prever qué hará.
Las cinco entradas «pendiente de tool dedicada (spec 023)» pasan a
`dedicated`. Las de pipelines, motores, AI Task y satélites siguen por la
tabla, revisadas: `pipeline_debug/get` tapa la `url` del audio (credencial
de hecho: HA la sirve sin autenticación) y el motivo de
`ai_task/preferences/set` dice la evaluación automática.

## Contexto técnico

**Lenguaje**: Python 3.13. **Dependencias**: las de Hermes; ninguna nueva.
**Pruebas**: pytest + `unittest` asíncrono con `ws_send` simulado; banco de
Core (HA Core 2026.11.1 real en el CI). **Plataforma**: add-on de HAOS;
tests en Windows y en el CI de Linux. **Restricciones**:
`response_max_bytes` (131072 por defecto), proxy WS del Supervisor (ningún
comando `hassio/`/`supervisor/`: ninguno lo es).

**Escala**: 4 tools en 1 módulo nuevo (`tools/conversation.py`); cambios en
`tool_families.py`, `tools/__init__.py`, `tools/_annotations.py`,
`tools/guide.py`, `command_table.py` (5 entradas a `dedicated` y 3
revisadas), `scripts/inventario/generar_tabla.py` (`_DEDICADAS_INICIALES`),
`tests/banco/ha_config/configuration.yaml`; un fichero de test unitario
nuevo, dos de banco y un inventario de banco; ajustes en los tests de
tabla, genéricas, familias, registro, guía, inventario de argumentos atados,
cobertura del banco y matriz; documentación.

**Línea base** (Windows, punta `1752984`, 2026-11-15): 3611 passed, 111
skipped, 6 failed (los 6 conocidos).

## Comprobación de la constitución

Contra la constitución 1.2.0.

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Procesar una frase (ejecuta intents y automatizaciones, como la acción `conversation.process`, que ya está en la denylist) va **siempre** en dos pasos con una vista previa que dice qué reconoce HA y a qué agente va el texto; analizar no ejecuta; las genéricas no pueden saltárselo (`dedicated`); la `url` del audio de `pipeline_debug/get` deja de salir (FR-004, FR-008, FR-009). | OK |
| II. Secretos | Respuestas por `redact_structure` + `redact_secrets` (un LLM puede repetir cualquier texto); `url` y `token` del audio tapados; el token guarda solo el hash (el texto no llega a `/data`); el log nunca lleva frases, respuestas, `conversation_id`, ids de agentes que no sean el integrado ni entidades; centinelas (FR-011, SC-004). | OK |
| III. Fail-closed | Argumentos inválidos y agente inexistente se rechazan sin token y sin llamar a `process`; un plazo vencido no se presenta como «no ejecutado» (`outcome_unknown`) y consume el token; `unknown_command` → `conversation_not_loaded`; lo nuevo en la tabla sigue entrando como `deny` (FR-005, FR-012). | OK |
| IV. Dos pasos | `ha_process_conversation` con token atado a los cinco argumentos que cambian el efecto (`text`, `agent_id`, `language`, `conversation_id`, `device_id`), fila en el inventario de la 033. La vista previa no miente: dice que con otro agente no se puede prever y que un disparador de frase ejecuta su automatización entera. No se ata a `estado`: no promete conservar nada (research R-2). | OK |
| V. Nombre y descripción | Descripciones que dicen que procesar ejecuta, que el texto puede salir a un servicio externo y que analizar no ejecuta; las frases listadas son solo las de disparadores; anotaciones honestas (destructiva, no idempotente y de mundo abierto por el peor caso); `local: "unknown"` en vez de afirmar lo que Hermes no sabe; la guía no nombra tools de la 021 si no están (FR-006, FR-007, FR-013). | OK |
| VI. Lo que no se puede probar | `ha_process_conversation` se ejecuta en el banco contra HA real con un disparador de frase y el lector independiente; las entradas de CAP-061 y CAP-062, en el banco por las genéricas; el camino «otro agente» y CAP-063 (no hay LLM ni satélites en el banco), en unitarios, y se dice (FR-014). | OK con límite declarado |
| VII. Control negativo | T016 con recuentos: token sin `device_id`, `agent_not_found` desactivado, log con el texto, `url` sin tapar, entrada en `deny`, tool fuera de `PROBADAS_023`, anotación sin mundo abierto. | OK |
| VIII. Privacidad | Datos ficticios (`light.salon`, `conversation.ejemplo_llm`, frase centinela, `centinela-023`); revisión del diff. | OK |
| IX. Cambios mínimos | Ninguna tool existente cambia; `language_scores` se pliega en una tool en lugar de crear una quinta; el tema `services` no se toca; no se duplica la exposición (021). | OK |
| X. Comentarios en español | Comentarios con el porqué en español; descripciones, errores y eventos en inglés. | OK |
| XI. Versionado | Sin subida de versión; sección propia en `## [1.2.0]`. | OK |

**Tras el diseño**: sin cambios en la tabla de cumplimiento.

## Diseño (un tramo)

- `tool_families.py`: familia `conversation` (data-model), con comentario del
  porqué (una familia, un caso de uso; aparte de `services` por FR-010).
- `tools/conversation.py` (docstring «POR QUÉ ASÍ» como `system_status.py`):
  - funciones puras con test: `_validar_*` (data-model), `_agentes(resp)`
    (orden, `is_default_agent`), `_reconocimiento(frase, resultado)` (forma
    de data-model, tope de 50 objetivos), `_respuesta_de_proceso(resultado,
    max_bytes)` (campos elegidos, redacción, recorte de `speech` y de
    `data`);
  - lecturas comunes: `_listar_agentes(language, country)` y
    `_analizar(frases, language, device_id)`, que usan las dos tools de
    lectura y la vista previa;
  - las cuatro tools según contracts/tools.md;
  - `ha_process_conversation`: valida → (sin token) agentes →
    `agent_not_found` o vista previa (con `_analizar` si es el integrado) →
    `create_confirmation_token`; (con token) `validate_confirmation_token`
    → `ws_send({"type": "conversation/process", …}, timeout_seconds=90)` →
    `complete_confirmation_token` → respuesta; `HAConnectionError` sin
    código de HA (plazo vencido o conexión caída) → `outcome_unknown`;
  - errores de HA: `unknown_command` → `conversation_not_loaded`;
    `unauthorized` → `unauthorized`; el resto redactado (`ha_error`);
  - log: un evento por tool con recuentos (research R-4).
- `tools/__init__.py`: registro bajo `if _activa("conversation")`.
- `tools/_annotations.py`: `ha_debug_conversation` en `_READ_ONLY_EXACT`;
  `ha_process_conversation` en `_DESTRUCTIVE_EXACT`, `_NON_IDEMPOTENT_EXACT`
  y `_OPEN_WORLD`; con el porqué.
- `command_table.py`: cinco entradas de CAP-060 a `dedicated` y tres
  revisadas de CAP-061/CAP-062 (data-model) a mano; las cinco claves en
  `_DEDICADAS_INICIALES` (bloque «023»); regenerar sin cambios.
- `tools/guide.py`: tema `conversation` (en español): las cuatro tools; que
  procesar ejecuta y confirma; el aviso del agente externo; qué controla
  Assist (la exposición; nombra las tools de la 021 solo si están en la
  rama); `ha_call_service_response` con `conversation.process` sigue
  existiendo pero la vía recomendada es `ha_process_conversation`;
  pipelines, motores, AI Task y satélites por las genéricas, con el ejemplo
  de crear pipeline y lo que sigue rechazado (`assist_pipeline/run`, audio).
  Alias: `assist`, `voice`, `conversation_agents`, `sentences`, `intents`,
  `pipelines`, `assist_pipeline`, `tts`, `stt`, `wake_word`, `satellite`,
  `ai_task`, `llm` (los que choquen con alias existentes se quitan y se
  dice en el commit). Índice e instrucciones del servidor con la familia
  activa, como las demás familias de la 1.2.0. Ningún tema existente cambia
  (sus huellas siguen).
- Banco: `configuration.yaml` con `assist_pipeline:` y `ai_task:` (y `llm:`
  si hace falta), con comentario; `tests/banco/test_banco_conversacion.py`
  y `tests/banco/test_banco_assist.py` (research R-6);
  `tests/banco/cobertura_023.py` con `PROBADAS_023`, sumado a la unión del
  invariante y a `TOOLS_EXIGIDAS_DEL_JOB`.
- Inventarios: fila de `ha_process_conversation` en
  `tests/test_confirmation_args_inventory.py` (los cinco atados) y en la
  matriz de la 014 (`banco de Core | ok`). No toca el de `allow_dangerous`
  (el comando WS no pasa por la denylist del cliente, que guarda las
  acciones).
- Documentación: CHANGELOG, hoja de ruta, README, DOCS, `SECURITY.md` (la
  tool confirma siempre aunque el comando WS no pase por la denylist de
  acciones), matriz de la 008.

## Estructura de ficheros

```text
hermes/src/hermes/
├── tool_families.py                 # familia conversation
├── command_table.py                 # 5 a dedicated, 3 revisadas
└── tools/
    ├── __init__.py                  # registro por familia
    ├── _annotations.py              # exactas: lectura, destructiva, no idempotente, mundo abierto
    ├── conversation.py              # 4 tools
    └── guide.py                     # tema conversation
scripts/inventario/generar_tabla.py  # _DEDICADAS_INICIALES (bloque 023)
tests/
├── test_tools_conversation.py       # unitarios de las 4 tools
├── test_command_table.py, test_tools_generic_commands.py,
├── test_tool_families.py, test_tools_registration.py, test_tools_guide.py,
├── test_confirmation_args_inventory.py, test_banco_cobertura_escrituras.py,
├── test_banco_cobertura.py, test_matriz_pruebas.py (sin cambios de código)
└── banco/
    ├── ha_config/configuration.yaml
    ├── cobertura_023.py
    ├── cobertura_escrituras.py      # unión y TOOLS_EXIGIDAS_DEL_JOB
    ├── test_banco_conversacion.py
    └── test_banco_assist.py
docs/HOJA-DE-RUTA.md, hermes/CHANGELOG.md, hermes/DOCS.md, README.md,
README.es.md, SECURITY.md, specs/008-cobertura-total/plan.md (matriz)
```

## Trazabilidad (FR de la 023 → FR/CAP de la 008 → tarea → test)

| FR 023 | 008 | Tareas | Test |
|---|---|---|---|
| FR-001 | FR-083 / CAP-060 | T003, T008 | `tests/test_tools_conversation.py` (`TestListarAgentes`) |
| FR-002 | FR-083 / CAP-060 | T003, T008 | ídem (`TestListarFrases`) |
| FR-003 | FR-083 / CAP-060 | T004, T008 | ídem (`TestAnalizar`) |
| FR-004 | FR-083 / CAP-060 | T005, T008 | ídem (`TestProcesarVistaPrevia`, `TestProcesarToken`) |
| FR-005 | FR-083 / CAP-060 | T005, T008 | ídem (`TestProcesarConfirmado`) |
| FR-006 | FR-083 | T007, T008 | `tests/test_tools_conversation.py` (`TestDescripciones`) |
| FR-007 | FR-018 | T006, T009 | `tests/test_tools_registration.py` (`_HINTS_NUEVAS_1_2_0`) |
| FR-008 | FR-012, FR-083 | T010, T011 | `tests/test_command_table.py` (`test_dedicadas_de_la_023`), `tests/test_tools_generic_commands.py` |
| FR-009 | FR-084 / CAP-061…063 | T010, T011, T014 | `tests/test_tools_generic_commands.py` (`TestAssistPorLaTabla`), `tests/banco/test_banco_assist.py` |
| FR-010 | FR-010 | T002, T006, T009 | `tests/test_tool_families.py`, `tests/test_tools_registration.py` |
| FR-011 | FR-019 | T003–T005, T008 | centinelas y `capture_logs` en `tests/test_tools_conversation.py` |
| FR-012 | FR-020 | T003–T005, T008 | ídem (`TestErroresDeHA`) |
| FR-013 | FR-011, FR-018 | T012 | `tests/test_tools_guide.py` |
| FR-014 | FR-014, FR-016, FR-084 | T013–T015 | `tests/banco/test_banco_conversacion.py`, `tests/banco/test_banco_assist.py`, `tests/test_banco_cobertura_escrituras.py`, `tests/test_matriz_pruebas.py`, `tests/test_confirmation_args_inventory.py` |
| FR-015 | FR-022, FR-023 | T017 | `TestToolCountInDocs`, `TestFamiliasEnLaDocumentacion`, `_matriz_008` |

## Tramos

| Tramo | Tareas | Cubre |
|---|---|---|
| 1 | T001–T018 | Familia, `tools/conversation.py` (4 tools), anotaciones, 5 entradas a `dedicated` y 3 revisadas, guía, banco (CAP-060, CAP-061, CAP-062), unitarios de CAP-063, inventarios, documentación y matriz de la 008 |

Un tramo (S en la 008). Si el agente se queda sin contexto, el corte natural
es tras T012 (tools, tabla y guía en verde) y el banco y la documentación en
un segundo commit del mismo tramo.

## Dependencias

- 011, 010, 028, 014, 033 y 018: en la rama.
- 021 (en paralelo, sin integrar): exposición. El tema `conversation` la
  nombra solo si está en la rama; la que se integre segunda completa la
  referencia cruzada en la guía (riesgo de fusión en `tools/guide.py`,
  `tool_families.py`, `command_table.py` y `tools/__init__.py`: líneas
  vecinas, no diseño).
- Ninguna sub-feature depende de esta.

## Riesgos

- **`assist_pipeline:` o `ai_task:` no arrancan en el banco** sin internet:
  el test lo deja como hallazgo (`xfail` estricto con la causa) o, si la
  integración entera no carga, esas pruebas pasan a unitarios con el motivo
  escrito; la tool `ha_process_conversation` no depende de ellos.
- **El disparador de frase tarda** en registrarse tras crear la automatización:
  el test espera con el sondeo del lector (como la 029 con el logbook).
- **Formato de `debug` cambia** en otra versión de HA: el test unitario fija
  el de 2026.11.1 y el banco lo comprueba contra la real.
- **Respuestas largas de un LLM**: recorte de `speech` probado en unitarios.
