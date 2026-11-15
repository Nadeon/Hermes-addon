# Plan de implementación: 033 — arreglos de tools existentes destapados por el banco

**Rama**: `feat/033-arreglos-del-banco` (sale de `feat/cobertura-total`) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md)

## Resumen

Siete tools de la 1.1.2 hacen algo distinto de lo que dicen, o lo dicen mal,
según el banco de pruebas de Core y las revisiones de la 010 y la 028. La más
grave es de seguridad: el token de `ha_trigger_automation` y `ha_run_script`
no ata `variables`. El resto son de honestidad (principio V): una recarga que
no existe en HA, una lectura que siempre devuelve `{}`, un `ctx` obligatorio
que nadie puede rellenar, una captura de escena que con `name` falla siempre y
que reemplaza escenas en silencio, una descripción que da una ruta equivocada
y un `amount` que da 500. Se arreglan sin quitar ninguna tool, con un test por
arreglo en la suite y en el banco y con su control negativo. Dos tramos: el 1,
seguridad; el 2, el resto. La investigación está en [research.md](research.md)
y las formas de respuesta en [contracts/tools.md](contracts/tools.md).

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x (MCPServer), aiohttp, structlog, pydantic 2 · **Almacenamiento**: tokens de confirmación en `/data` (sin cambios de formato) · **Tests**: pytest, `unittest.IsolatedAsyncioTestCase`, `DummyMCP` y simuladores de cada fichero; banco de Core (010/028) con HA Core 2026.11.1 real · **Plataforma**: add-on de HAOS.

**Restricciones**: nada de lo que funciona hoy se rompe (FR-020 de la 008); solo dos excepciones de esquema/anotación, escritas en los tests (FR-011); cambios mínimos; ninguna tool nueva ni familia nueva.

**Dependencias de otras sub-features** (S-01 de la spec):

- **011** — trae `tests/fixtures/esquemas_1_1_2.json` y `test_esquemas_de_la_1_1_2`. Si al implementar no está integrada, la excepción de esquema se escribe en el test de la 011 al integrarla (tarea de integración anotada en el tramo 2).
- **028** — trae la base del banco para automatizaciones, scripts y escenas (`tests/banco/base_escrituras.py`, `cobertura_escrituras.py`) y, en su convergencia, el script y la automatización restringidos inocuos (T033) y el `xfail` `HALLAZGO` de la escena con `name` (T032). Cada tramo empieza integrando la rama del programa si hace falta.

**Ola**: 2 (tras 011 y 028). Tamaño M, 2 tramos.

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | El tramo 1 cierra una vía para ejecutar un script restringido con variables no revisadas. El test de inventario impide que otra tool con token deje argumentos fuera (FR-003). | OK |
| II. Secretos | No toca secretos. Las `variables` que se enseñan en la vista previa las mandó el propio cliente, igual que `service_data` en `ha_call_service`; no se escriben en el log. | OK |
| III. Fail-closed | Lo que no se puede hacer se rechaza antes de llamar a HA (`not_supported`, `name_not_supported`, `entity_not_found`, `scene_exists`, `invalid_amount`). Ante la duda sobre el origen de una escena existente, dos pasos y comprobación posterior. | OK |
| IV. Dos pasos, token atado | El token de `guarded_entity_invoke` pasa a atar `variables` y la vista previa las enseña. `ha_create_scene_from_current` pide token cuando reemplaza, con una vista previa que dice lo que hará HA. | OK |
| V. Nombre y descripción | El objetivo de la spec: descripciones de siete tools corregidas; `ha_create_scene_from_current` pasa a `destructiveHint` porque puede reemplazar. Cada cambio de comportamiento cambia su docstring en el mismo commit. | OK |
| VI. Lo que no se puede probar | Cada arreglo tiene test unitario y test del banco contra HA 2026.11.1 real; el canario de `counter.reload` avisa si HA cambia. | OK |
| VII. Control negativo | Cada tarea de arreglo termina con su control negativo anotado (tasks). | OK |
| VIII. Privacidad | Marcadores genéricos (`script.ficticio`, `light.salon`, `counter.ficticio`); el banco genera nombres de prueba únicos. | OK |
| IX. Cambios mínimos | Solo las siete tools de las revisiones. Lo cercano que no se pidió (`ha_set_counter_value` con valores no múltiplos del `step`) queda como duda. | OK |
| X. Comentarios en español | Igual que hoy; mensajes al cliente en inglés. | OK |
| XI. Versionado | Sin cambio de versión: entra en la 1.2.0 (sección «Correcciones» del CHANGELOG). | OK |
| FR-020 de la 008 (compatibilidad) | Desviación justificada en dos puntos: `ctx` sale del esquema (era obligatorio y sin sentido; un `ctx` enviado se sigue aceptando) y `ha_create_scene_from_current` gana un argumento opcional y `destructiveHint` (la anotación anterior mentía). Recogido en el FR-099 de la 008 y en los tests. | OK, justificado |

Tras el diseño: sin cambios.

## Diseño

### Tramo 1 — token atado (FR-001…FR-003, FR-010 parte)

- `tools/_common.py`, `guarded_entity_invoke`: el argumento `extra_data` se
  sustituye por `variables` explícito (los dos únicos llamadores pasan solo
  eso), `args = {"entity_id", "service", "variables"}` y la vista previa gana
  `"variables"`. Llamadores: `tools/automations.py` y `tools/scripts.py`, que
  dejan de envolver `variables` en un dict.
- `tests/test_confirmation_args_inventory.py` (nuevo): el inventario de
  argumentos atados de FR-003 (dict por tool, comprobación por AST contra las
  firmas de `@mcp.tool` con `confirmation_token`, motivos no vacíos).
- Tests de comportamiento: en `tests/test_security_regressions.py` (clase de
  `guarded_entity_invoke` existente) y en `tests/test_tools_scripts.py` /
  `tests/test_tools_automations.py` con `CONFIRMATIONS_DIR` temporal.
- Banco: test nuevo en el fichero de automatizaciones y scripts de la 028
  (`tests/banco/test_banco_escrituras_automatizacion.py`) con el script y la
  automatización restringidos de su T033: vista previa con variables,
  confirmación con otras (el lector no ve `script.turn_on` /
  `automation.trigger` ni el efecto) y confirmación correcta (el lector ve el
  servicio con las variables, por el evento `call_service` o por el efecto
  que usa la variable: por ejemplo, el script pone un `input_text` del lector
  al valor de la variable).

### Tramo 2 — honestidad (FR-004…FR-009, FR-010 resto, FR-011, FR-012)

- `tools/counter.py`:
  - `ha_reload_counters` devuelve el `not_supported` del contrato sin llamar a
    `guarded_reload`; docstring `DEPRECATED (removed in 1.3.0)`.
  - `_bulk_adjust` comprueba `step`, `minimum` y `maximum` de los atributos
    del estado ya leído antes de `set_value`; docstrings de increment y
    decrement con la regla.
- `tools/wait_for_event.py`: `ctx: Context` en la MISMA posición (primer
  argumento, sin valor por defecto, porque `event_type` no lo tiene), con
  `from mcp.server.mcpserver import Context` como `tools/ping.py`. Los tests
  existentes que llaman a la función directamente pasan `None` como primer
  argumento y siguen valiendo; el `hasattr` del keepalive se queda por eso.
- `tools/scenes.py`: `ha_create_scene_from_current` según research R-4;
  docstrings de las tres tools de R-5.
- `tools/_annotations.py`: `ha_create_scene_from_current` en
  `_DESTRUCTIVE_EXACT`.
- `tools/config_entry_flows.py`: `ha_get_config_entry_options` según el
  contrato.
- `tools/guide.py`: textos de R-9.
- Tests de registro (`tests/test_tools_registration.py`): `_HINTS_SNAPSHOT`
  con la línea de la escena y su comentario; excepciones en
  `test_esquemas_de_la_1_1_2`; test nuevo del esquema de
  `ha_wait_for_event` y de `context_kwarg`.
- Banco:
  - `tests/banco/cobertura.py`: `ha_reload_counters` de `FALLAN_EN_BANCO` a
    `NO_EJECUTABLES`; `XFAIL_PERMITIDOS` sin su test; docstrings y recuentos
    («47 de 47» pasa a «46 probadas + 1 no ejecutable con motivo»).
  - `tests/banco/test_banco_helpers_tiempo.py`: `test_recarga` sin `xfail`,
    como canario (R-2); test nuevo de `amount` con `step` 3.
  - `tests/banco/cobertura_escrituras.py`: quitar la entrada de la escena de
    `HALLAZGOS_028` / `XFAIL_PERMITIDOS_028` si existe.
  - Escenas, espera y opciones: en los ficheros del banco de la 028 que ya
    prueban esas familias (automatización/escenas, servicios/eventos,
    integraciones).
- Documentación: CHANGELOG, `docs/HOJA-DE-RUTA.md` (deprecaciones y fila
  033), matriz de la 008.

### Lo que no cambia

Formato de los tokens, `security.py`, la denylist y la clasificación de
entidades restringidas, la tabla de comandos (ninguna tool nueva ni comando
nuevo: no hay entradas que pasar a `dedicated`), las familias y las demás
tools.

## Tramos de implementación

| Tramo | Tareas | Cubre | Commit |
|---|---|---|---|
| **1** — token atado | T001–T011 | FR-001, FR-002, FR-003, FR-010 (tokens), FR-012 (su parte), FR-013 | uno, con el recuento de controles negativos |
| **2** — honestidad | T012–T036 | FR-004…FR-009, FR-010 (resto), FR-011, FR-012, FR-013 | uno, o uno por historia si el agente lo prefiere; la suite en verde en cada uno |

Cada tramo deja la suite en verde, el banco en verde en el CI y se puede
commitear por separado. El tramo 2 no depende del código del tramo 1 (tocan
funciones distintas), pero va después para que el CHANGELOG y la matriz se
escriban en orden.

## Riesgos

- **Integración con la 011 y la 028** (S-01): si no están, el agente integra la
  rama del programa primero y resuelve conflictos en `tests/banco/` y
  `tests/test_tools_registration.py`. Lo anota en el commit.
- **El banco tarda más**: los tests nuevos son pocos y reutilizan sesiones; el
  canario de recarga ya existía. Riesgo bajo.
- **Comprobación posterior de la escena con carreras**: `scene.create` es
  bloqueante en el REST de Core y escribe el estado antes de responder; si un
  runner lento lo viera tarde, el test del banco usa `esperar_estado` (sin
  pausas fijas, FR-008 de la 010) y la tool hace una sola lectura (sin
  reintentos que oculten un fallo).
- **Otras sub-features que añaden tokens**: el inventario de FR-003 cae en
  cuanto una rama añade `confirmation_token` a una tool (por ejemplo, la 018
  en `ha_call_service_response`, FR-064 de la 008). Es lo que se busca: la
  sub-feature que se integre después añade su entrada al inventario al
  resolver la integración. El docstring del test lo explica.
- **Clientes que dependían del `{}` de las opciones**: devolvía datos falsos;
  el error es la corrección.

## Ficheros

- `specs/033-arreglos-del-banco/`: `spec.md`, `plan.md`, `research.md`,
  `contracts/tools.md`, `quickstart.md`, `tasks.md`,
  `checklists/requirements.md`. Sin `data-model.md`: no hay entidades nuevas
  (las de la spec son conceptos ya existentes).
- Código: `hermes/src/hermes/tools/{_common,automations,scripts,counter,wait_for_event,scenes,config_entry_flows,_annotations,guide}.py`.
- Tests: `tests/test_confirmation_args_inventory.py` (nuevo),
  `tests/test_security_regressions.py`, `tests/test_tools_{scripts,automations,counter,wait_for_event,scenes,config_entry_flows,registration}.py`,
  `tests/banco/{cobertura,cobertura_escrituras}.py`,
  `tests/banco/test_banco_helpers_tiempo.py` y los ficheros del banco de la
  028 que correspondan.
- Docs: `hermes/CHANGELOG.md`, `docs/HOJA-DE-RUTA.md`,
  `specs/008-cobertura-total/plan.md` (matriz).
