# Plan de implementación: diagnóstico de Core (012)

**Rama**: `feat/012-diagnostico-core` (no se crea ninguna) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md) | **Programa**: [008](../008-cobertura-total/plan.md), sub-feature 012, ola 2

## Resumen

Doce tools dedicadas nuevas en una familia nueva, `core_diagnostics`, para lo
que un administrador mira cuando algo falla en Home Assistant: el log del
sistema agrupado, el log de errores, los niveles de log (leer y fijar), la
validación de triggers, condiciones y acciones, la prueba de una condición,
los diagnósticos de integraciones y dispositivos y las notificaciones
persistentes. Tres modifican (fijar nivel, limpiar el log del sistema,
descartar una notificación) y van en dos pasos con vista previa. Nueve
comandos de la tabla de la 011 pasan de `deny` «pendiente» a `dedicated`. Todo
se prueba en unitarios y en el banco de Core. Dos tramos: A (logs, la base
común: familia, método de texto del cliente, tabla y generador) y B
(validación, diagnósticos, notificaciones y cierre de la documentación).

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x, aiohttp, structlog (sin dependencias nuevas) · **Almacenamiento**: solo los ficheros de token de `/data/pending_confirmations` (como hoy) · **Tests**: pytest con `unittest.IsolatedAsyncioTestCase`, `AsyncMock` del cliente, servidor aiohttp local para el método de texto; banco de Core de la 010 · **Plataforma**: add-on de HA OS.

**Restricciones**: fail-closed (III); dos pasos con token atado a todos los argumentos (IV); anotaciones verdaderas y por nombre exacto donde el prefijo no basta (V); control negativo (VII); repositorio público (VIII); cambios mínimos (IX).

**Escala**: 12 tools (3 que modifican), 4 módulos, 9 entradas de la tabla, 1 método nuevo en `HAClient`, 1 familia, 1 tema de guía.

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Lo que modifica va con vista previa que describe el efecto real (nivel anterior y nuevo, entradas que se borran, texto de la notificación). La denylist no cambia y ninguna tool nueva la rodea: las tres acciones protegidas solo se ejecutan tras su propio token. Las lecturas pasan por el tope y la redacción. | OK |
| II. Secretos | Mensajes del log, trazas, líneas, diagnósticos, errores de HA y notificaciones pasan por `redact_secrets` (y `redact_structure` donde hay estructura) antes de salir; el log de Hermes solo lleva recuentos, niveles y objetivos; test con centinela por tool, incluido el fichero del token (FR-017). | OK |
| III. Fail-closed | Lectura previa fallida → `preview_unavailable` sin token; forma de respuesta inesperada → error, nunca «vacío»; argumentos dudosos → `invalid_argument` sin llamar a HA; diagnóstico sin handler → sin descarga; las entradas de la tabla solo pasan a `dedicated` cuando la tool existe. | OK |
| IV. Dos pasos, token atado | `ha_set_log_level` ata `level` (normalizado antes), `integration`, `module` y `persistence`; `ha_dismiss_persistent_notification`, el id; `ha_clear_system_log`, la tool (sin argumentos) y su vista previa avisa de que lo que llegue antes de confirmar también se borra. Sin argumentos omitibles. | OK |
| V. Nombre y descripción | `ha_validate_config` y `ha_test_condition` de solo lectura por nombre exacto; las tres que piden token, destructivas por nombre exacto. Las respuestas dicen lo que no hacen: `not_validated`, `previous_level: null` con motivo, `error_log_unavailable` con la causa real. | OK |
| VI. Lo que no se puede probar | Las tres que modifican y las lecturas, en el banco contra HA 2026.11.1 real; lo que el banco no puede (diagnóstico de dispositivo con éxito, log de errores sin fichero en HA OS real) queda en unitarios y en la matriz de la 014 como pendiente manual. | OK |
| VII. Control negativo | Uno por comportamiento con riesgo, enumerados en las tareas T018 y T033 y anotados en el commit de cada tramo. | OK |
| VIII. Privacidad | Fixtures con `light.salon`, `<entry_id>`, `mqtt`, centinelas; revisión del diff en cada cierre de tramo. | OK |
| IX. Cambios mínimos | Solo las tools de las cuatro CAP; nada de la 029, la 013 ni la 017; las tools existentes no cambian (la guía añade un tema y una línea en `diagnostics`). Lo que falta y no es de esta CAP, a dudas (D-1…D-3). | OK |
| X. Comentarios en español | Comentarios y eventos del log como hoy; nombres y descripciones de tools en inglés. | OK |
| XI. Versionado | Sin subir versión (la 1.2.0 la fijó la 009); sección propia en `## [1.2.0]` del CHANGELOG. | OK |
| Flujo, puerta 4 | Suite y banco en verde en el CI al cerrar cada tramo. | OK |

Tras el diseño: sin cambios. Ninguna desviación que justificar.

## Diseño

### Tramo A — base común y logs (CAP-041)

1. **Familia** `core_diagnostics` en `tool_families.py` con `("core_logs",)`
   (el tramo B añade los otros tres módulos). Desactivable, `desde="1.2.0"`.
2. **Cliente**: `HAClient.rest_get_text_tail(path, *, lines, max_line_bytes=4096)`
   en `ha.py` (research R-2): `_assert_safe_request_path`, GET en flujo,
   `deque(maxlen=lines)`, líneas largas recortadas con marca, errores HTTP como
   `HAConnectionError(status=…)`, 30 s.
3. **`tools/core_logs.py`** con las cinco tools de data-model:
   - `ha_list_system_log`: `ws_send({"type": "system_log/list"})`, validar que
     es lista, transformar, filtrar, ordenar, redactar, `ajustar_lista_a_bytes`.
   - `ha_get_error_log`: `rest_get_text_tail("/error_log", lines=…)`,
     `redact_secrets` por línea, últimas que caben (reutilizar
     `_ultimas_lineas_que_caben` de `addons.py` moviéndolo a `_common.py` si
     hace falta compartirlo, sin cambiar su comportamiento).
   - `ha_get_log_levels`: `logger/log_info`.
   - `ha_set_log_level`: validación → (sin token) lectura de `logger/log_info`
     para el nivel previo si es integración → vista previa →
     `create_confirmation_token`; (con token) `validate_confirmation_token` →
     un `ws_send` → `complete_confirmation_token`.
   - `ha_clear_system_log`: (sin token) `system_log/list` → `unchanged` si
     vacío, si no vista previa; (con token) `call_service("system_log",
     "clear", {})`.
4. **Registro** en `tools/__init__.py` dentro de `if _activa("core_diagnostics")`
   con `response_max_bytes`; **anotaciones** de `ha_set_log_level` y
   `ha_clear_system_log` en `_DESTRUCTIVE_EXACT`.
5. **Tabla**: `system_log/list`, `logger/log_info`, `logger/log_level` y
   `logger/integration_log_level` a `dedicated` (data-model); el generador
   nombra las cuatro en `_DEDICADAS_INICIALES` y `_clasificar` consulta el mapa
   también para la clase A (research R-7); `test_clase_a_de_via_dedicada…`
   admite `dedicated`. Regenerar → `git diff` vacío en `command_table.py`.
6. **Guía**: tema `core_diagnostics` con la parte de logs y sus alias; una línea
   en `diagnostics`.
7. **Banco**: `system_log:` en la configuración del banco;
   `tests/banco/test_banco_core_logs.py`; `tests/banco/cobertura_012.py` con las
   dos tools del tramo; enganche al invariante (S-02 de la spec).
8. **Documentación parcial**: sección «Diagnóstico de Core» en `## [1.2.0]` del
   CHANGELOG con lo del tramo; fila 012 de la hoja de ruta «en curso (tramo A)».

### Tramo B — validación, diagnósticos y notificaciones (CAP-040, CAP-042, CAP-047)

1. **`tools/core_validation.py`**: `ha_validate_config` (mapeo de `config`,
   R-1) y `ha_test_condition`.
2. **`tools/integration_diagnostics.py`**: las tres tools (R-5), con la
   redacción doble (`_redactar` como `repairs.py`, o compartida en `_common.py`
   si ya hay dos usos) y el recorte propio por claves.
3. **`tools/persistent_notifications.py`**: listar y descartar (R-6).
4. **Familia** con los cuatro módulos; registro; anotaciones (`_READ_ONLY_EXACT`
   para validar y probar condición; `_DESTRUCTIVE_EXACT` para descartar).
5. **Tabla**: las otras cinco entradas; generador; regenerar idéntico.
6. **Guía** completa.
7. **Banco**: `diagnostics:` en la configuración;
   `tests/banco/test_banco_core_diagnostico.py` (validación, condición,
   diagnósticos, notificaciones); `ha_dismiss_persistent_notification` a
   `PROBADAS_012`.
8. **Documentación final**: CHANGELOG completo, hoja de ruta «hecha», README y
   README.es (lista de tools por área y recuento si lo llevan), DOCS (si la
   opción de familias enumera las familias), matriz de la 008 (filas CAP-040,
   CAP-041, CAP-042, CAP-047: tools y ficheros de test).

## Estructura de ficheros

```text
hermes/src/hermes/
├── ha.py                          # + rest_get_text_tail (A)
├── tool_families.py               # + core_diagnostics (A; módulos en B)
├── command_table.py               # 9 entradas a dedicated (A: 4, B: 5)
└── tools/
    ├── __init__.py                # registro bajo la familia (A, B)
    ├── _annotations.py            # nombres exactos (A, B)
    ├── _common.py                 # solo si se comparte un helper existente
    ├── guide.py                   # tema core_diagnostics (A, B)
    ├── core_logs.py               # nuevo (A)
    ├── core_validation.py         # nuevo (B)
    ├── integration_diagnostics.py # nuevo (B)
    └── persistent_notifications.py# nuevo (B)
scripts/inventario/generar_tabla.py  # _DEDICADAS_INICIALES y clase A (A, B)
tests/
├── test_ha_rest_text_tail.py      # nuevo (A)
├── test_tools_core_logs.py        # nuevo (A)
├── test_tools_core_validation.py  # nuevo (B)
├── test_tools_integration_diagnostics.py  # nuevo (B)
├── test_tools_persistent_notifications.py # nuevo (B)
├── test_tool_families.py          # familia (A, B)
├── test_tools_registration.py     # hints de las nuevas (A, B)
├── test_command_table.py          # vía D admite dedicated (A)
├── test_generar_tabla.py          # fila A en el mapa (A)
├── test_tools_guide.py            # tema y cobertura de tools (A, B)
├── test_tools_generic_commands.py # rechazo hacia la dedicada (A)
└── banco/
    ├── ha_config/configuration.yaml   # system_log: (A), diagnostics: (B)
    ├── cobertura_012.py               # nuevo (A, B)
    ├── test_banco_core_logs.py        # nuevo (A)
    └── test_banco_core_diagnostico.py # nuevo (B)
hermes/CHANGELOG.md, docs/HOJA-DE-RUTA.md, README.md, README.es.md,
hermes/DOCS.md, specs/008-cobertura-total/plan.md
```

## Trazabilidad (FR de la 012 → FR/CAP de la 008 → tareas → test)

| FR 012 | FR 008 | CAP | Tareas | Test |
|---|---|---|---|---|
| FR-001 | FR-036 | CAP-040 | T020, T021, T031 | `test_tools_core_validation.py`; banco |
| FR-002 | FR-036 | CAP-040 | T020, T021, T031 | `test_tools_core_validation.py`; banco |
| FR-003 | FR-037 | CAP-041 | T006, T011, T015 | `test_tools_core_logs.py`; banco |
| FR-004 | FR-037 | CAP-041 | T004, T005, T007, T011, T015 | `test_ha_rest_text_tail.py`, `test_tools_core_logs.py`; banco |
| FR-005 | FR-037 | CAP-041 | T008, T011, T015 | `test_tools_core_logs.py`; banco |
| FR-006 | FR-037 | CAP-041 | T009, T011, T015 | `test_tools_core_logs.py`; banco |
| FR-007 | FR-037 | CAP-041 | T010, T011, T015 | `test_tools_core_logs.py`; banco |
| FR-008 | FR-038 | CAP-042 | T022, T023, T031 | `test_tools_integration_diagnostics.py`; banco |
| FR-009 | FR-038 | CAP-042 | T022, T023, T031 | `test_tools_integration_diagnostics.py`; banco |
| FR-010 | FR-038 | CAP-042 | T022, T023, T031 | `test_tools_integration_diagnostics.py`; banco (camino de error) |
| FR-011 | FR-039 | CAP-047 | T024, T025, T031 | `test_tools_persistent_notifications.py`; banco |
| FR-012 | FR-039 | CAP-047 | T024, T025, T031 | `test_tools_persistent_notifications.py`; banco |
| FR-013 | FR-010 | CAP-004 | T002, T003, T012, T026 | `test_tool_families.py`, `test_tools_registration.py` |
| FR-014 | FR-012 | CAP-001 | T013, T028 | `test_command_table.py`, `test_generar_tabla.py`, `test_tools_generic_commands.py` |
| FR-015 | FR-018 | CAP-023 | T012, T026 | `test_tools_registration.py` |
| FR-016 | FR-011 | CAP-008 | T014, T029 | `test_tools_guide.py` |
| FR-017 | FR-019 | — | T006–T010, T020, T022, T024 | centinelas en cada fichero de tests |
| FR-018 | FR-018 | CAP-023 | T006, T008, T022, T024 | sobre y tope en cada fichero de tests |
| FR-019 | FR-015 | CAP-034 | T015, T031 | `tests/banco/*`, invariante de escrituras |
| FR-020 | FR-020 | CAP-030 | T010, T012, T026 | `test_tools_registration.py`, `test_call_service_security.py` |
| FR-021 | FR-023 | — | T016, T032 | revisión en el cierre (T034) |
| FR-022 | FR-021 | — | T019, T034 | revisión del diff |

## Tramos

Cada tramo lo hace un agente nuevo: deja la suite local con exactamente los 6
fallos conocidos de Windows, el CI de la rama en verde y termina en su propio
commit (o varios) con los recuentos de los controles negativos.

- **Tramo A — base común y logs** (T001–T019): familia, método de texto,
  `core_logs.py` (5 tools), registro y anotaciones, 4 entradas de la tabla y
  generador, guía (parte de logs), banco de logs, documentación parcial.
- **Tramo B — validación, diagnósticos y notificaciones** (T020–T034): tres
  módulos (7 tools), registro y anotaciones, 5 entradas de la tabla, guía
  completa, banco del resto, documentación final y matriz de la 008.

## Riesgos

| Riesgo | Mitigación |
|---|---|
| La 011 (tramos 2 y 3), la 009 o la 010 no están en la rama al empezar | T001 las integra desde `feat/cobertura-total`; sin la 010, banco pendiente con nota (S-01) |
| `ha_get_error_log` casi siempre da `error_log_unavailable` en HA OS real | Dicho en la descripción, el error y la guía; duda D-1 para el mantenedor |
| Un diagnóstico enorme agota memoria al parsearlo | `_request_json` ya lo carga entero (como cualquier REST); el tope de mensaje de HA y el tiempo de 30 s lo acotan; se anota si el banco muestra otra cosa |
| El banco no tiene integración sin red con diagnóstico | R-8: se elige en el tramo B; si ninguna sirve, unitarios y pendiente manual en la matriz de la 014 |
| Conflictos con otras sub-features en `_annotations.py`, `guide.py`, `tool_families.py`, la tabla y el CHANGELOG | Cambios en bloques propios y comentados; se resuelven al integrar en `feat/cobertura-total` en orden de olas |
