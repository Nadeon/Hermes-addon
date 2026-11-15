# Plan de implementación: estadísticas y energía (020)

**Rama**: `feat/020-estadisticas-y-energia` (no se crea ninguna) | **Fecha**: 2026-11-15 | **Spec**: [spec.md](spec.md) | **Programa**: [008](../008-cobertura-total/plan.md), sub-feature 020, ola 3, tarea T018

## Resumen

Siete tools dedicadas nuevas. Cinco de mantenimiento de estadísticas (CAP-050)
en un módulo nuevo de la familia `recorder` de la 029, todas en dos pasos con
una vista previa que dice exactamente qué estadísticas y qué periodo se tocan,
con el token atado a los argumentos normalizados y a los metadatos leídos. Dos
de energía (CAP-054) en una familia nueva `energy`: leer las preferencias y
guardarlas en dos pasos con diferencias por lista, como Lovelace. En la tabla,
siete comandos pasan a `dedicated`, las cuatro lecturas de energía a `read` y
`recorder/update_statistics_issues` a `confirm`. Todo se prueba en el banco de
Core con estadísticas que siembra el lector. Tres tramos.

## Dependencias y momento de la implementación

La base ya tiene todo lo que hace falta: la 011 (tabla, familias, genéricas,
generador), la 029 (familia `recorder`, `recorder_status.py`, tema de la
guía), la 010 y la 028 (banco e inventario de escrituras), la 014 (matriz), la
018 (`estado` del token, sobre de lista) y la 033 (inventario de argumentos
atados). No depende de ninguna sub-feature pendiente. La 019 (HMAC de los
tokens, en camino) no cambia el uso de `create_confirmation_token`; si se
integra antes, nada cambia aquí.

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x, aiohttp, structlog (sin dependencias nuevas) · **Almacenamiento**: el de los tokens de `security.py` (con `stored_args` de `stats` al importar) · **Tests**: pytest con `unittest.IsolatedAsyncioTestCase`, `AsyncMock` de `ws_send` con respuestas por comando, `structlog.testing.capture_logs`, `HERMES_CONFIG_BASE` propio para los tokens; banco de Core de la 010 · **Plataforma**: add-on de HA OS.

**Restricciones**: fail-closed (III); dos pasos con token atado (IV); anotaciones y vistas previas verdaderas (V); control negativo (VII); repositorio público (VIII); cambios mínimos (IX); FR-020 de la 008 (nada de lo actual cambia salvo la descripción de la familia `recorder` y su tema de la guía, anunciados por la 029).

**Escala**: 7 tools (6 que modifican, las 6 con token), 2 módulos nuevos, 1 familia nueva y 1 cambiada, 1 tema nuevo y 1 ampliado, 12 entradas de la tabla (7 `dedicated`, 4 `read`, 1 `confirm`), 6 filas en la matriz de la 014 y en el inventario de argumentos atados.

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Las seis escrituras piden token siempre; la genérica sigue rechazando los siete comandos dedicados (`use_dedicated_tool`), también con su familia apagada; `update_statistics_issues` solo por la genérica de escritura (token). Ninguna llama a servicios (la denylist no cambia). | OK |
| II. Secretos | Respuestas, vistas previas y errores de HA por `redact_structure` + `redact_secrets`; log sin ids, valores ni documento; los `stats` guardados con el token solo en el almacén de tokens (como el documento de Lovelace) y con su tope. Centinelas en tests (SC-004). | OK |
| III. Fail-closed | Argumentos inválidos → `invalid_argument` sin llamar a HA; ids inexistentes → `statistics_not_found` sin token; los casos en que HA respondería éxito sin hacer nada (fuente, unidad, sin suma) se rechazan antes; `unknown_command` → error explícito; sin `estado` igual en la confirmación no se ejecuta. | OK |
| IV. Dos pasos, token atado | Las seis: vista previa sin efecto (lector en el banco), token atado a TODOS los argumentos normalizados como se envían y a `estado` (metadatos o preferencias); `stats` omitible solo como documento guardado. Inventario de la 033 con sus seis filas, sin exentos. Vistas previas que dicen qué ids, qué periodo (el efectivo de HA, con el solape), qué cambia y que solo un backup lo deshace. | OK |
| V. Nombre y descripción | Anotaciones por nombre exacto con su porqué (los prefijos no clasifican estas); `ha_adjust_statistics_sum` no idempotente. `queued: true` donde HA solo encola; «no convierte valores» en metadatos; «reemplaza la lista entera» en energía. La familia `recorder` deja de decir «read only». | OK |
| VI. Lo que no se puede probar | Las siete y las cinco entradas de la tabla se ejecutan en el banco contra HA 2026.11.1 real; el efecto lo comprueba el lector, con estadísticas sembradas por él. `NO_EJECUTABLES_020` vacío. | OK |
| VII. Control negativo | Uno por comportamiento con riesgo en el cierre de cada tramo (T019, T033, T050): token sin un argumento, sin `estado`, sin comprobación previa, vista previa con efecto, redacción, tabla e inventarios. | OK |
| VIII. Privacidad | Fixtures con `sensor.consumo`, `sensor.solar`, `banco:importada`, `centinela-020`; nada de la instalación real; revisión del diff en cada cierre. | OK |
| IX. Cambios mínimos | Solo CAP-050 y CAP-054; `recorder_status.py`, `statistics.py` y las tools de la 1.1.2 no cambian; el tema `data` (huella) tampoco. Tres tramos en vez de dos (desviación anotada abajo). | OK |
| X. Comentarios en español | Comentarios y eventos del log en español; descripciones al cliente en inglés y guía en español, como hoy. | OK |
| XI. Versionado | Sin subir versión (1.2.0 la fijó la 009); sección propia en `## [1.2.0]`. | OK |
| Flujo, puerta 4 | Suite, banco y Semgrep en verde en el CI al cerrar cada tramo. | OK |

Tras el diseño: sin cambios. Desviación justificada: **3 tramos** en vez de
los 2 que da la 008 (ver «Tramos»).

## Diseño

### Patrón común de las cinco de CAP-050 (`statistics_maintenance.py`)

Un ayudante privado del módulo hace los pasos comunes, para que cada tool solo
escriba su validación, su vista previa y su comando:

1. Validar la forma (reutiliza `_STATISTIC_ID_RE` y `_error_ha` de
   `recorder_status.py`; fechas con `datetime.fromisoformat` y zona
   obligatoria, normalizadas a UTC ISO).
2. Leer metadatos (`recorder/get_statistics_metadata`) → comprobaciones
   previas (R-2) → `estado` = metadatos ordenados por id.
3. Sin token: construir la vista previa, redactarla, comprobar el tope y
   `create_confirmation_token(tool, args_normalizados, preview, estado=…)`.
4. Con token: volver a leer metadatos y `resolve_confirmation_token(…,
   estado=…)`; enviar el comando; `complete_confirmation_token` con el
   resultado; traducir errores (`timeout` → `ha_timeout`).

### Tramo 1 — Borrar, cambiar la unidad y editar metadatos (CAP-050, parte)

`ha_clear_statistics`, `ha_change_statistics_unit`,
`ha_update_statistics_metadata`; el ayudante común; el módulo registrado en
la familia `recorder` (descripción nueva); anotaciones; tres entradas a
`dedicated` con sus claves en el generador; inventario de argumentos atados;
banco (siembra del lector, vista previa sin efecto, efecto) con
`cobertura_020.py` y su suma al invariante y al job; matriz de la 014 (tres
filas); guía `recorder` (parte); CHANGELOG parcial.

### Tramo 2 — Ajustar sumas, importar y avisos (CAP-050, resto)

`ha_adjust_statistics_sum` (lectura de la suma en esa hora) e
`ha_import_statistics` (`omitibles=("stats",)`, recuento de filas
sobrescritas acotado a 31 días); `update_statistics_issues` a `confirm` en la
tabla y en `_POR_LA_TABLA`; dos entradas más a `dedicated`; anotaciones (no
idempotente); inventario, banco, matriz (dos filas más), guía `recorder`
completa.

### Tramo 3 — Energía y cierre (CAP-054)

Familia `energy` y `tools/energy.py` con las dos tools; `energy/get_prefs` y
`energy/save_prefs` a `dedicated`; las cuatro lecturas a `read` (con el
`example` de consumo fósil) en `_POR_LA_TABLA`; `energy:` en el banco;
`test_banco_energia.py`; matriz (una fila); tema `energy`; documentación
final (README, DOCS, HOJA-DE-RUTA, CHANGELOG, matriz de la 008).

## Estructura de ficheros

```text
hermes/src/hermes/
├── tools/
│   ├── statistics_maintenance.py   # NUEVO (1, 2)
│   ├── energy.py                   # NUEVO (3)
│   ├── __init__.py                 # registro bajo _activa("recorder") / ("energy") (1, 3)
│   ├── _annotations.py             # exactas + _HINTS_NUEVAS_1_2_0 (1, 2, 3)
│   └── guide.py                    # tema recorder (1, 2), tema energy (3)
├── tool_families.py                # recorder: módulo y descripción (1); energy (3)
└── command_table.py                # 7 dedicated, 4 read, 1 confirm (1, 2, 3)
scripts/inventario/generar_tabla.py # _DEDICADAS_INICIALES, bloque «020» (1, 2, 3)
tests/
├── test_tools_statistics_maintenance.py   # NUEVO (1, 2)
├── test_tools_energy.py                   # NUEVO (3)
├── test_command_table.py, test_generar_tabla.py, test_tools_generic_commands.py,
├── test_tool_families.py, test_tools_registration.py, test_tools_guide.py,
├── test_confirmation_args_inventory.py, test_banco_cobertura_escrituras.py
└── banco/
    ├── ha_config/configuration.yaml        # energy: (3)
    ├── cobertura_020.py                    # NUEVO (1)
    ├── cobertura_escrituras.py             # TOOLS_EXIGIDAS_DEL_JOB (1, 3)
    ├── test_banco_estadisticas.py          # NUEVO (1, 2)
    └── test_banco_energia.py               # NUEVO (3)
hermes/CHANGELOG.md, hermes/DOCS.md, README.md, README.es.md,
docs/HOJA-DE-RUTA.md (programa y matriz-pruebas), specs/008-cobertura-total/plan.md
```

## Trazabilidad

| FR (020) | FR (008) | CAP | Tareas | Test |
|---|---|---|---|---|
| FR-001 | FR-069 | CAP-050 | T003, T008 | `test_tools_statistics_maintenance.py` |
| FR-002 | FR-069 | CAP-050 | T004, T008 | ídem |
| FR-003 | FR-069 | CAP-050 | T005, T008 | ídem |
| FR-004 | FR-069 | CAP-050 | T021, T024 | ídem |
| FR-005 | FR-069 | CAP-050 | T022, T024 | ídem |
| FR-006 | FR-069 | CAP-050 | T003–T005, T021, T022, T015, T030 | ídem; banco |
| FR-007 | FR-069 | CAP-050 | T006, T009, T023, T026 | ídem; `test_confirmation_args_inventory.py` |
| FR-008 | FR-069 | CAP-050 | T003–T005, T021 | `test_tools_statistics_maintenance.py` |
| FR-009 | FR-069, FR-012 | CAP-050 | T027, T028, T030 | `test_command_table.py`, `test_tools_generic_commands.py`; banco |
| FR-010 | FR-070 | CAP-054 | T037, T040 | `test_tools_energy.py` |
| FR-011 | FR-070 | CAP-054 | T038, T040 | ídem |
| FR-012 | FR-070 | CAP-054 | T038, T040, T042 | ídem; `test_confirmation_args_inventory.py` |
| FR-013 | FR-070, FR-011 | CAP-054 | T043, T044 | `test_command_table.py`, `test_tools_generic_commands.py` |
| FR-014 | FR-010 | CAP-004 | T007, T010, T036, T041 | `test_tool_families.py`, `test_tools_registration.py` |
| FR-015 | FR-012 | CAP-001 | T011, T012, T027, T028, T043, T044 | `test_command_table.py`, `test_generar_tabla.py`, `test_tools_generic_commands.py` |
| FR-016 | FR-018 | — | T007, T010, T025, T036, T041 | `test_tools_registration.py` |
| FR-017 | FR-018, FR-019 | — | T003–T005, T021, T022, T037, T038 | tests de las tools |
| FR-018 | FR-019, FR-021 | CAP-011 | T003–T005, T021, T022, T037, T038 | ídem (log capturado) |
| FR-019 | FR-020 | — | T003, T005, T037 | ídem |
| FR-020 | FR-011, FR-018 | CAP-008 | T013, T014, T029, T045, T046 | `test_tools_guide.py` |
| FR-021 | FR-014, FR-015 | CAP-034 | T015–T017, T030, T031, T047, T048 | `tests/banco/test_banco_*.py`, `test_banco_cobertura_escrituras.py`, `test_matriz_pruebas.py` |
| FR-022 | FR-023, FR-024 | — | T020, T034, T049, T051 | `TestToolCountInDocs`, `test_matriz_pruebas.py`; revisión |

## Tramos

| Tramo | Tareas | Tools | Entradas de la tabla |
|---|---|---|---|
| 1 — borrar, unidad y metadatos | T001–T020 | 3 (las 3 modifican) | 3 a `dedicated` |
| 2 — sumas, importación y avisos | T021–T035 | 2 (las 2 modifican) | 2 a `dedicated`; `update_statistics_issues` a `confirm` |
| 3 — energía y cierre | T036–T052 | 2 (1 modifica) | 2 a `dedicated`; 4 a `read` |

La 008 da 2 tramos a la 020. Se usan 3 porque cada tool de CAP-050 tiene su
vista previa, sus comprobaciones previas, su prueba en el banco con siembra y
su fila en tres inventarios: cinco en un tramo, más la energía en otro, no
caben con holgura en el contexto de un agente (requisito del programa). El
tramo 1 hace además el ayudante común y el inventario del banco, que los
otros dos solo amplían. Duda D-2.

## Riesgos

- **El recorder encola y el banco lee antes de tiempo**: el lector sondea con
  plazo (`esperar`), nunca pausas fijas; `commit_interval` de 5 s.
- **Siembra que interfiere con la 029**: estadísticas propias con sufijo de
  prueba, borradas al final; las de `kitchen_sink` no se tocan. Una
  estadística `sensor.banco_…` sin entidad puede salir en
  `ha_validate_statistics`: el test de la 029 compara con el lector y sigue
  valiendo.
- **Energía compartida**: el banco tiene una sola configuración de energía; el
  test la lee antes, la restaura al final con el lector y ningún otro test la
  usa.
- **Tope de `stored_args`** al importar 5000 filas: si no cabe, el token se
  emite sin documento y la confirmación pide reenviar `stats` (comportamiento
  de la 018, `confirm_hint` lo dice).
- **Conflictos con otras sub-features de la ola 3** en `command_table.py`,
  `generar_tabla.py`, `_annotations.py`, `tool_families.py`, `guide.py`,
  `tools/__init__.py`, README, CHANGELOG e inventarios del banco: sitios
  distintos de los mismos ficheros; la segunda que se integre conserva los de
  las dos.
