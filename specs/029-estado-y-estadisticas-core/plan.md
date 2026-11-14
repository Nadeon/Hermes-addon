# Plan de implementación: estado del sistema y estadísticas de Core (029)

**Rama**: `feat/029-estado-y-estadisticas-core` (no se crea ninguna) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md) | **Programa**: [008](../008-cobertura-total/plan.md), sub-feature 029, ola 2

## Resumen

Ocho tools dedicadas nuevas, todas de solo lectura, en dos familias nuevas:
`system_status` (salud del sistema, estado de reinicio, tiempos de arranque y
manifiestos; CAP-043) y `recorder` (validación y metadatos de estadísticas y
estado del recorder; CAP-049). Nueve comandos de la tabla de la 011 pasan de
`deny` «pendiente (spec 029)» a `dedicated`. Las cuatro entradas `read` de
CAP-058 (auditoría de llamadas a acciones) y CAP-068 (red y HTTP de Core) se
quedan en la tabla, con tema en la guía, prueba en el banco y, la auditoría,
con el `code` de las alarmas tapado. Un método nuevo del cliente recoge
suscripciones de varios mensajes con tope de tiempo. Dos tramos: 1 (CAP-043,
el método del cliente y el mecanismo de la tabla) y 2 (CAP-049, CAP-058,
CAP-068 y el cierre de la documentación).

## Dependencias y momento de la implementación

**La implementación espera a la 011 completa.** Al especificar, esta rama
tiene la 011 hasta T037 (tramos 1 y 2 y parte del 3: familias, opción y
guía); le faltan el extractor y la documentación (T038–T043). Tampoco tiene
la 009 (versión 1.2.0 y la entrada `## [1.2.0]` del CHANGELOG) ni el banco de
la 010. T001 comprueba, antes de nada, que la rama de la 029 se ha rebasado
sobre una base con la 009, la 010 y la 011 enteras; si no, el tramo no
empieza. La relación con la 012 (en paralelo, ola 2) está en research R-7:
mismo cambio del generador y del test de la clase A; la segunda que se integre
resuelve el conflicto.

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x, aiohttp, structlog (sin dependencias nuevas) · **Almacenamiento**: ninguno nuevo · **Tests**: pytest con `unittest.IsolatedAsyncioTestCase`, `AsyncMock` de `ws_send`, `ws_one_shot_subscription` y `ws_collect_subscription`, WebSocket simulada para el método nuevo del cliente (como los tests de `ws_one_shot_subscription`), `structlog.testing.capture_logs`; banco de Core de la 010 · **Plataforma**: add-on de HA OS.

**Restricciones**: fail-closed (III); anotaciones verdaderas (V); control negativo (VII); repositorio público (VIII); cambios mínimos (IX); FR-020 de la 008 (nada de lo actual cambia).

**Escala**: 8 tools (0 que modifican), 2 módulos, 1 método nuevo en `HAClient`, 2 familias, 2 temas de guía, 9 entradas de la tabla a `dedicated` y 1 entrada `read` con `redact_extra` y ejemplo.

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Ninguna tool modifica nada ni pide token; la denylist no cambia. Los textos de manifiestos personalizados van marcados como de terceros. La genérica sigue rechazando los nueve comandos (`use_dedicated_tool`), incluso con su familia apagada. | OK |
| II. Secretos | Respuestas por `redact_structure` + `redact_secrets`; errores de HA redactados; el `code` de las llamadas a acciones tapado por la tabla (`redact_extra`), que la 011 prometía y no cumplía; log sin valores. Centinelas en salud, manifiesto, error de HA y auditoría (SC-004). | OK |
| III. Fail-closed | Argumentos inválidos → `invalid_argument` sin llamar a HA; la recogida de salud tiene plazo total y cancela siempre; una entidad que no existe → `not_found` en vez de «se graba»; comandos desconocidos → error explícito; los comandos solo pasan a `dedicated` cuando la tool existe (test de la 011). | OK |
| IV. Dos pasos, token atado | No aplica: nada modifica. Ninguna de las ocho acepta `confirmation_token` y el invariante de registro (`test_every_destructive_tool_takes_a_confirmation_token` y su recíproco) lo vigila. | N/A |
| V. Nombre y descripción | Prefijos de lectura salvo `ha_validate_statistics`, de lectura por nombre exacto con su porqué (valida, no corrige). Las respuestas dicen lo que no hicieron: `complete: false` y `pending`, `missing`, `omitted_domains`, `truncated`. La descripción de `ha_get_statistics_metadata` remite a `ha_list_statistic_ids` y la de `ha_validate_statistics` dice que no crea avisos. El motivo de `logbook/get_action_calls` pasa a decir exactamente qué tapa. | OK |
| VI. Lo que no se puede probar | Las ocho y las cuatro entradas `read` se ejecutan en el banco contra HA 2026.11.1 real. Lo que el banco no puede (una salud con la nube o el Supervisor, un reinicio pendiente, estadísticas con problemas) queda en unitarios y como prueba manual tras publicar en la matriz de la 014. | OK |
| VII. Control negativo | Uno por comportamiento con riesgo (T018 y T034): plazo total, cancelación, redacción, `missing`, `not_found`, tabla y cobertura del banco. Anotados en el commit de cada tramo. | OK |
| VIII. Privacidad | Fixtures con `light.salon`, `sensor.consumo`, `192.0.2.x`, `homeassistant.tailXXXX.ts.net`, `centinela-029`; revisión del diff en cada cierre de tramo; test de log sin URLs ni IPs (SC-006). | OK |
| IX. Cambios mínimos | Solo las cuatro CAP; nada de la 012, la 020 ni la 021. `ws_one_shot_subscription`, `tools/statistics.py` y los temas de la 1.1.2 no cambian. El cambio del generador es el de la 012, no uno propio. | OK |
| X. Comentarios en español | Comentarios y eventos del log en español; nombres, descripciones y guía al cliente como hoy (descripciones en inglés, guía en español). | OK |
| XI. Versionado | Sin subir versión (la fijó la 009); sección propia en `## [1.2.0]`. | OK |
| Flujo, puerta 4 | Suite, banco, Semgrep y CodeQL en verde en el CI al cerrar cada tramo. | OK |

Tras el diseño: sin cambios. Ninguna desviación que justificar.

## Diseño

### Tramo 1 — CAP-043, el cliente y la tabla

1. **Mecanismo de la tabla** (research R-7): si la 012 está integrada, nada;
   si no, `_clasificar` consulta `_DEDICADAS_INICIALES` también para la clase
   A antes de la regla «pendiente», y
   `test_clase_a_de_via_dedicada_pendiente_de_su_spec` admite `dedicated`
   hacia una tool de una familia de la 1.2.0.
2. **Cliente**: `HAClient.ws_collect_subscription` (data-model).
3. **Familia** `system_status` con el módulo `system_status`.
4. **`tools/system_status.py`** con las cinco tools de contracts/tools.md:
   - `ha_get_system_health`: `ws_collect_subscription({"type":
     "system_health/info"}, terminado=evento tipo finish, timeout_seconds)`;
     fusión del inicial con las actualizaciones; normalización de valores;
     redacción; recorte por dominios.
   - `ha_get_system_state`: `ws_one_shot_subscription({"type":
     "subscribe_system_state"})`.
   - `ha_list_integration_setup_times`, `ha_list_integration_manifests`,
     `ha_get_integration_manifest`: `ws_send` y transformación;
     `ajustar_lista_a_bytes` en las listas.
5. **Registro** en `tools/__init__.py` dentro de `if _activa("system_status")`;
   anotaciones (los prefijos bastan); `_HINTS_NUEVAS_1_2_0`.
6. **Tabla**: las cinco entradas de CAP-043 a `dedicated`, sus claves en
   `_DEDICADAS_INICIALES`, regenerar y comprobar que no cambia nada.
7. **Guía**: tema `system_status` (las cinco tools; la red y el HTTP se
   añaden en el tramo 2) con alias e índice.
8. **Banco**: `system_health:` y `network:` en la configuración; las cinco en
   `tests/banco/test_banco_estado_sistema.py`; `PROBADAS_EN_BANCO_029` con
   las cinco y su test de cobertura.
9. **Documentación parcial**: recuento y tablas de los README y DOCS (lo
   exige `TestToolCountInDocs`), CHANGELOG y hoja de ruta («en curso»).

### Tramo 2 — CAP-049, CAP-058, CAP-068 y cierre

1. **Familia** `recorder` con el módulo `recorder_status`.
2. **`tools/recorder_status.py`** con las tres tools: `ws_send` a los
   comandos del recorder; `entity_exists` antes de
   `recorder/entity_options/get`; `recorder_not_loaded` y
   `unsupported_by_ha_version`.
3. **Anotaciones**: `ha_validate_statistics` en `_READ_ONLY_EXACT`.
4. **Tabla**: las cuatro de CAP-049 a `dedicated`; `logbook/get_action_calls`
   con `redact_extra`, ejemplo y motivo nuevo.
5. **Tests de CAP-058 y CAP-068** por la genérica: centinela `code` y log sin
   URLs ni IPs.
6. **Guía**: tema `recorder` (tres tools y la auditoría) y sección de red y
   HTTP en `system_status`.
7. **Banco**: `recorder:` y `logbook:`; las tres tools y las cuatro entradas
   `read` en `tests/banco/test_banco_recorder.py`; `PROBADAS_EN_BANCO_029`
   completo.
8. **Documentación final**: CHANGELOG, hoja de ruta («hecha»), README, DOCS
   (familias de `tool_families_disabled`), matriz de la 008.

## Estructura de ficheros

```text
hermes/src/hermes/
├── ha.py                         # ws_collect_subscription (1)
├── tool_families.py              # system_status (1), recorder (2)
├── command_table.py              # 9 entradas dedicated (1, 2); get_action_calls (2)
└── tools/
    ├── __init__.py               # registro bajo las familias (1, 2)
    ├── _annotations.py           # ha_validate_statistics en _READ_ONLY_EXACT (2)
    ├── guide.py                  # temas system_status (1, 2) y recorder (2)
    ├── system_status.py          # NUEVO: 5 tools (1)
    └── recorder_status.py        # NUEVO: 3 tools (2)
scripts/inventario/generar_tabla.py   # claves en _DEDICADAS_INICIALES (1, 2)
tests/
├── test_ha_ws_collect_subscription.py # NUEVO (1)
├── test_tools_system_status.py        # NUEVO (1)
├── test_tools_recorder_status.py      # NUEVO (2)
├── test_tools_generic_commands.py     # rechazos de los 9 y CAP-058/068 (1, 2)
├── test_command_table.py              # (si no lo hizo la 012) clase A dedicada (1)
├── test_generar_tabla.py              # (si no lo hizo la 012) mapa para clase A (1)
├── test_tool_families.py              # las dos familias (1, 2)
├── test_tools_registration.py         # _HINTS_NUEVAS_1_2_0, SC-001 (1, 2)
├── test_tools_guide.py                # temas y alias (1, 2)
├── test_banco_cobertura.py            # PROBADAS_EN_BANCO_029 (1, 2)
└── banco/
    ├── cobertura.py                   # PROBADAS_EN_BANCO_029 (1, 2)
    ├── ha_config/configuration.yaml   # system_health, network (1); recorder, logbook (2)
    ├── test_banco_estado_sistema.py   # NUEVO (1)
    └── test_banco_recorder.py         # NUEVO (2)
hermes/CHANGELOG.md, hermes/DOCS.md, README.md, README.es.md,
docs/HOJA-DE-RUTA.md, specs/008-cobertura-total/plan.md   # (1 parcial, 2)
```

## Trazabilidad

| FR (029) | FR (008) | CAP | Tareas | Test |
|---|---|---|---|---|
| FR-001 | FR-040 | CAP-043 | T006, T011 | `test_tools_system_status.py` |
| FR-002 | FR-040, FR-020 | CAP-043 | T004, T005 | `test_ha_ws_collect_subscription.py` |
| FR-003 | FR-040 | CAP-043 | T007, T011 | `test_tools_system_status.py` |
| FR-004 | FR-040 | CAP-043 | T008, T011 | `test_tools_system_status.py` |
| FR-005 | FR-040 | CAP-043 | T008, T011 | `test_tools_system_status.py` |
| FR-006 | FR-040 | CAP-043 | T008, T011 | `test_tools_system_status.py` |
| FR-007 | FR-018 | CAP-043 | T008, T011 | `test_tools_system_status.py` |
| FR-008 | FR-041 | CAP-049 | T021, T024 | `test_tools_recorder_status.py` |
| FR-009 | FR-041 | CAP-049 | T021, T024 | `test_tools_recorder_status.py` |
| FR-010 | FR-041 | CAP-049 | T022, T024 | `test_tools_recorder_status.py` |
| FR-011 | FR-041 | CAP-049 | T022, T024 | `test_tools_recorder_status.py` |
| FR-012 | FR-042, FR-019 | CAP-058 | T026, T027 | `test_tools_generic_commands.py`, `test_command_table.py` |
| FR-013 | FR-043 | CAP-068 | T026 | `test_tools_generic_commands.py` |
| FR-014 | FR-042, FR-043, FR-011 | CAP-058, CAP-068 | T028, T029 | `test_tools_guide.py` |
| FR-015 | FR-010 | CAP-004 | T009, T012, T020, T025 | `test_tool_families.py`, `test_tools_registration.py` |
| FR-016 | FR-012 | CAP-001 | T002, T003, T013, T014, T023, T027 | `test_command_table.py`, `test_generar_tabla.py`, `test_tools_generic_commands.py` |
| FR-017 | FR-018 | — | T010, T012, T020, T025 | `test_tools_registration.py` |
| FR-018 | FR-018, FR-019 | — | T006, T008, T021, T022 | `test_tools_system_status.py`, `test_tools_recorder_status.py` |
| FR-019 | FR-019, FR-021 | CAP-011 | T006, T008, T021, T022 | ídem (log capturado) |
| FR-020 | FR-020 | — | T007, T022 | ídem |
| FR-021 | FR-011, FR-018 | CAP-008 | T015, T028, T029 | `test_tools_guide.py` |
| FR-022 | FR-015 | CAP-034 | T016, T017, T030, T031 | `tests/banco/test_banco_*.py`, `test_banco_cobertura.py` |
| FR-023 | FR-023, FR-024 | — | T019, T032, T033 | `TestToolCountInDocs`; revisión |

## Tramos

| Tramo | Tareas | Tools | Entradas de la tabla |
|---|---|---|---|
| 1 — CAP-043, cliente y mecanismo de la tabla | T001–T019 | 5 | 5 a `dedicated` |
| 2 — CAP-049, CAP-058, CAP-068 y cierre | T020–T035 | 3 | 4 a `dedicated`; `logbook/get_action_calls` |

Cada tramo cabe en el contexto de un agente: el 1 tiene cinco tools sencillas
más un método del cliente; el 2, tres tools, cuatro entradas `read` ya
existentes y la documentación.

## Riesgos

- **Conflicto con la 012** en `generar_tabla.py`, `test_command_table.py`,
  `tools/__init__.py`, `tool_families.py`, `guide.py`, el recuento de los
  README y el CHANGELOG: cambios en sitios distintos de los mismos ficheros;
  se resuelve conservando los de las dos (duda D-3).
- **El banco no graba `call_service`** o `network:` no arranca sin red: se
  anota y la prueba de esa entrada queda en unitarios (supuesto de la spec).
- **Salud con muchos dominios** mayor que el tope: recorte por dominios con
  `omitted_domains`; `domain=` para pedir uno.
