# Plan de implementación: control de Core y del Supervisor (022)

**Rama**: `feat/022-control-de-core-y-supervisor` (sale de `feat/cobertura-total` en `c4a57bf`; se integra en `feat/cobertura-total`) | **Fecha**: 2026-11-15 | **Spec**: [spec.md](spec.md) | **Paraguas**: [008](../008-cobertura-total/plan.md)

## Resumen

Ocho tools nuevas del Supervisor en dos familias nuevas. `system_control`:
arrancar, reconstruir y fijar opciones de Core; recargar, reiniciar, reparar
y fijar opciones del Supervisor (CAP-084). `resolution_fixes`: aplicar una
sugerencia del centro de resolución con su efecto traducido (CAP-087
escritura). Todo lo que corta el servicio va en dos pasos con una vista previa
de qué se corta, qué no y cuánto; los rechazos fail-closed (Core ya en marcha,
jobs en curso, escrituras sin validar, sugerencias sin fixup o sobre Hermes)
no llaman. En la tabla, las 14 entradas «spec 022» se resuelven (8
`dedicated`, 2 `read`, 4 `confirm`); `/core/stop` y el canal del Supervisor
siguen cerrados. Las rutas de plugins, Docker, placas y hora (CAP-091, 092,
094) ya estaban clasificadas por la 011: se comprueban y se prueban. Dos
tramos. Prueba en vivo pendiente (VM de la 014).

Detalle y alternativas en [research.md](research.md); formas en
[data-model.md](data-model.md); firmas en
[contracts/tools.md](contracts/tools.md); validación en
[quickstart.md](quickstart.md).

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x, aiohttp, structlog (ninguna nueva) · **Almacenamiento**: solo los tokens de `security.py` · **Tests**: pytest, `unittest.IsolatedAsyncioTestCase`, `DummyMCP`, Supervisor simulado (fixture nueva `tests/fixtures/supervisor_control.py` sobre la de la 013) que registra método, ruta, cuerpo y `timeout_seconds`, `structlog.testing.capture_logs` · **Plataforma**: add-on de Home Assistant OS.

**Restricciones**: dos pasos para todo salvo `sv_reload_supervisor` (IV); listas cerradas de opciones y validación antes de llamar (III); errores redactados y log sin valores (II); las tools de la 1.1.2 sin cambios (FR-020 de la 008); `/core/stop` y `channel` cerrados (D-01).

**Escala**: 8 tools en 2 módulos nuevos (`tools/system_control.py`, `tools/resolution_fixes.py`); cambios en `tool_families.py`, `tools/__init__.py`, `tools/_annotations.py`, `command_table.py` (14 líneas), `scripts/inventario/generar_tabla.py` (`_DEDICADAS_INICIALES`), `tools/guide.py`, docstring de `tools/resolution.py`; tests nuevos (`test_tools_system_control.py`, `test_tools_resolution_fixes.py`, `test_tools_control_tabla.py`) y ajustes en `test_command_table.py`, `test_tools_registration.py`, `test_tool_families.py`, `test_tools_guide.py`, `test_tools_resolution.py`, `test_confirmation_args_inventory.py`, `tests/banco/cobertura_escrituras.py`.

## Comprobación de la constitución

Contra la constitución 1.2.0 (con las enmiendas E-1…E-4 de la 011).

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Cada tool decide qué envía: listas cerradas de opciones (sin `image`, `refresh_token`, `port`, `ssl`, `channel`, `debug*`, `feature_flags`); nunca `force` en el rebuild; sugerencias solo con fixup conocido; nada sobre el propio Hermes; las rutas por la tabla pasan por las guardas de la 011 (FR-003, FR-007, FR-010, FR-013…FR-015). | OK |
| II. Secretos | `refresh_token` nunca pasa por el cliente; la contraseña del registro Docker tapada en vista previa, log y errores (FR-016); el log lleva nombres de claves, nunca valores ni `reference` (FR-019); errores con `redact_secrets`. | OK |
| III. Fail-closed | Rechazos sin llamar: `already_running`, `no_changes`, `jobs_in_progress` (también si `/jobs/info` falla), `blocked`, `no_fixup`, `unknown_effect`, `not_allowed`, `targets_hermes`; se repiten al confirmar (FR-001…FR-011, SC-002). | OK |
| IV. Dos pasos | Siete tools con token que ata todo lo que cambia la acción (`safe_mode`, `options`, `suggestion_uuid`) y, como estado (018), lo leído en la vista previa (valores actuales, sugerencia, backups a borrar, contenedores, autofixes). `sv_reload_supervisor` sin token porque FR-076 lo dice y no corta nada. Fila en el inventario de la 033 (FR-021). | OK |
| V. Nombre y descripción | Vista previa con qué se corta, qué no y cuánto; `status: "started"` cuando no se sabe el final, nunca un ok inventado (FR-008); `no_fixup` porque el Supervisor respondería ok sin hacer nada; anotaciones de R-10; la guía, el README y el docstring de `resolution.py` dejan de decir «nunca aplica» (FR-012). | OK |
| VI. Lo que no se puede probar | Supervisor simulado con la forma de 2026.11.0; no hay banco del Supervisor; las 8 en `FUERA_DEL_BANCO` y en la matriz como `VM | pendiente`, con su línea en «Tandas de pruebas» (FR-021, SC-007). | OK con pendiente declarado |
| VII. Control negativo | Controles por tramo (T014, T028) con recuentos: listas cerradas, bloqueo del rebuild, jobs en curso, `already_running`, estado en el token, `no_fixup`, `targets_hermes`, `dedicated` en la tabla, contraseña del registro. | OK |
| VIII. Privacidad | Fixtures con `<slug>`, `registro.example`, uuids y fechas inventados, centinelas; revisión del diff en cada tramo. | OK |
| IX. Cambios mínimos | Sin tocar `sv_restart_core` ni `sv_reboot_host`; la ayuda de restart (`check_restart_allowed_sync`) y `_es_hermes` se reutilizan; sin tool para `/host/reload` ni para estadísticas; ninguna entrada de CAP-091/092/094 cambia. | OK |
| X. Comentarios en español | Comentarios con el porqué; descripciones, errores y eventos en inglés. | OK |
| XI. Versionado | Sin subida de versión; sección propia en `## [1.2.0] — <fecha de publicación>`. | OK |

**Desviaciones de la 008, justificadas**: ninguna de FR. Del research de la
008: las estadísticas no tienen tool (manda FR-076) y `/host/reload` va por la
tabla (FR-076 no le da tool). **Cambio de política de la 1.1.x**: Hermes
aplica sugerencias (FR-077), con los rechazos de research R-6.

**Tras el diseño**: sin cambios en la tabla de cumplimiento.

## Diseño

### Tramo 1 — control de Core y del Supervisor (CAP-084)

- `tool_families.py`: `system_control` (1.2.0, desactivable, módulo
  `system_control`), con comentario del porqué (R-1).
- `tools/system_control.py`: siete tools según data-model; ayudas internas
  `_vista_previa_opciones(actual, pedido, permitidas, rechazadas)` (diferencia,
  `no_changes`, `not_allowed`, `invalid_argument`) compartida por las dos de
  opciones, `_jobs_en_curso()` compartida por restart y repair,
  `_ejecutar_larga(ruta, cuerpo, timeout, verify_with)` (R-7). Reutiliza
  `check_restart_allowed_sync` de `fs_write.py` (como `tools/supervisor.py`).
- Registro en `tools/__init__.py` en la comprobación de familia; anotaciones
  en `_annotations.py` (R-10).
- Tabla: las 7 rutas a `dedicated` y `GET /core/stats`, `GET /supervisor/stats`
  a `read`, `POST /host/reload` a `confirm`; `_DEDICADAS_INICIALES` del
  generador con las 7; `_POR_LA_TABLA` con las 3; regenerar sin cambios.
- Guía: tema `system_control` (parte de Core y Supervisor) y una línea en
  `supervisor`; huellas.
- Invariantes: inventario de argumentos atados (6 con token),
  `FUERA_DEL_BANCO` (7), matriz de la 014 (7 filas), tanda 1 y tanda 3 de
  `docs/BANCO-SUPERVISOR.md`.

### Tramo 2 — sugerencias (CAP-087 escritura) y lo que va por la tabla

- `tool_families.py`: `resolution_fixes`.
- `tools/resolution_fixes.py`: `sv_apply_resolution_suggestion` con la tabla
  de traducción como constante (`_FIXUPS: dict[tuple[str, str], Efecto]`), el
  conjunto de tipos y contextos de 2026.11.0 para distinguir `no_fixup` de
  `unknown_effect`, detalles (`/backups`, `/addons/{slug}/info`), rechazos y
  estado del token.
- `tests/test_tools_resolution.py`: la guarda pasa a «solo
  `resolution_fixes.py`»; docstring de `tools/resolution.py` y tema
  `diagnostics` actualizados.
- Tabla: la sugerencia a `dedicated`; los tres chequeos a `confirm` con
  `_POR_LA_TABLA`; ninguna «spec 022»; regenerar sin cambios.
- `tests/test_tools_control_tabla.py`: estadísticas, host, chequeos y todas
  las rutas de CAP-091/092/094 por las genéricas con la tabla real y el
  Supervisor simulado; contraseña del registro (FR-016); `/core/stop`,
  alias y `channel` cerrados (FR-014).
- Guía completa, documentación final y matriz de la 008.

## Estructura de ficheros

```text
hermes/src/hermes/
├── tool_families.py                 # + system_control, resolution_fixes
├── command_table.py                 # 14 líneas
├── tools/
│   ├── __init__.py                  # registro de los dos módulos
│   ├── _annotations.py              # R-10
│   ├── guide.py                     # tema system_control; diagnostics, supervisor
│   ├── resolution.py                # solo el docstring
│   ├── system_control.py            # NUEVO (tramo 1)
│   └── resolution_fixes.py          # NUEVO (tramo 2)
scripts/inventario/generar_tabla.py  # _DEDICADAS_INICIALES (+8)
tests/
├── fixtures/supervisor_control.py   # NUEVO
├── test_tools_system_control.py     # NUEVO (tramo 1)
├── test_tools_resolution_fixes.py   # NUEVO (tramo 2)
├── test_tools_control_tabla.py      # NUEVO (tramos 1 y 2)
├── test_tools_resolution.py         # guarda
├── test_command_table.py, test_tools_registration.py, test_tool_families.py,
│   test_tools_guide.py, test_confirmation_args_inventory.py
└── banco/cobertura_escrituras.py    # FUERA_DEL_BANCO
docs/HOJA-DE-RUTA.md, docs/BANCO-SUPERVISOR.md, hermes/CHANGELOG.md,
hermes/DOCS.md, README.md, README.es.md, specs/008-cobertura-total/plan.md
```

## Trazabilidad (FR de la 022 → FR/CAP de la 008 → tarea → test)

| FR 022 | FR/CAP 008 | Tareas | Test |
|---|---|---|---|
| FR-001 | FR-076 / CAP-084 | T003, T008 | `test_tools_system_control.py::TestStartCore` |
| FR-002 | FR-076 / CAP-084 | T003, T008 | `::TestRebuildCore` |
| FR-003 | FR-076 / CAP-084 | T004, T008 | `::TestSetCoreOptions` |
| FR-004 | FR-076 / CAP-084 | T005, T009 | `::TestReloadSupervisor` |
| FR-005 | FR-076 / CAP-084 | T005, T009 | `::TestRestartSupervisor` |
| FR-006 | FR-076 / CAP-084 | T005, T009 | `::TestRepairSupervisor` |
| FR-007 | FR-076 / CAP-084 | T006, T009 | `::TestSetSupervisorOptions` |
| FR-008 | FR-076 / CAP-084 | T003, T005, T008, T009 | `::TestOperacionesLargas` |
| FR-009 | FR-077 / CAP-087 | T018, T021 | `test_tools_resolution_fixes.py::TestTraduccion` |
| FR-010 | FR-077 / CAP-087 | T019, T021 | `::TestRechazos` |
| FR-011 | FR-077 / CAP-087 | T019, T021 | `::TestTokenYEstado` |
| FR-012 | FR-077 | T020, T022 | `test_tools_resolution.py::TestSoloResolutionFixesAplica`, `test_tools_guide.py` |
| FR-013 | FR-076, FR-077 | T010, T011, T023 | `test_command_table.py::TestEntradasDeLa022` |
| FR-014 | FR-076; D-01 | T024 | `test_tools_control_tabla.py::TestSigueCerrado` |
| FR-015 | FR-078…FR-080 / CAP-091, 092, 094 | T024 | `test_tools_control_tabla.py::TestPorLaTabla` |
| FR-016 | FR-079 / CAP-092 | T024 | `::TestRegistroDocker` |
| FR-017 | FR-010, FR-012 de la 008 | T002, T012, T017, T025 | `test_tool_families.py`, `test_tools_registration.py` |
| FR-018 | principio V | T012, T025 | `test_tools_registration.py::TestControl022` |
| FR-019 | principio II | T007, T018 | `::TestLog` en los dos ficheros nuevos |
| FR-020 | FR-023 de la 008 | T013, T026 | `test_tools_guide.py::TestTemaSystemControl` |
| FR-021 | FR-016, FR-017 de la 008 | T012, T025 | `test_confirmation_args_inventory.py`, `test_banco_cobertura_escrituras.py`, `test_matriz_pruebas.py` |
| FR-022 | FR-023 de la 008 | T015, T027 | `test_matriz_pruebas.py`, revisión |

Columnas de la matriz de `specs/008-cobertura-total/plan.md` que se
actualizan al cerrar (sin cambiar sub-feature ni vía): CAP-084, CAP-087,
CAP-091, CAP-092, CAP-094.

## Tramos

| Tramo | Tareas | Resultado |
|---|---|---|
| 1 | T001–T016 | Familia `system_control` con 7 tools; 7 `dedicated`, 2 `read`, 1 `confirm`; guía y documentación del tramo |
| 2 | T017–T029 | Familia `resolution_fixes` con `sv_apply_resolution_suggestion`; sugerencia `dedicated` y 3 chequeos `confirm`; tests de CAP-091/092/094; guía y documentación final; ninguna «spec 022» |

## Pruebas en vivo (pendiente declarado)

En la VM de la 014 (`docs/BANCO-SUPERVISOR.md`): tanda 1 —
`sv_set_core_options` (`backups_exclude_database` ida y vuelta),
`sv_set_supervisor_options` (`country`), `sv_reload_supervisor`; tanda 3, una
por instantánea — `sv_rebuild_core`, parar Core desde la consola del host y
`sv_start_core`, `sv_restart_supervisor` (Hermes se reconecta),
`sv_repair_supervisor`, y `sv_apply_resolution_suggestion` con una sugerencia
provocada (por ejemplo, un repositorio de la tienda roto → `execute_reset`).

## Dependencias

- Requisito previo: 013 integrada (fixture y `/jobs/info` `read`), 018
  (`estado` en el token), 033 (inventario de argumentos), 014 (matriz). Todo
  está en `c4a57bf`.
- Al integrar: 015 y 030 tocan la misma tabla, la guía y `tool_families.py`
  (familias `system_updates` y `app_store`; la 019, `mounts`): conflictos de
  líneas, no de diseño. Ninguna de ellas toca `tools/resolution.py` ni
  `tests/test_tools_resolution.py` (comprobado con `git diff`).

## Riesgos

- **Una sugerencia que el Supervisor resuelve distinto de lo leído**: el
  fixup actúa sobre lo que hay al aplicar (p. ej. los backups de ese momento);
  el estado del token reduce la ventana a 60 s, no la elimina. Se dice en la
  vista previa.
- **Supervisor de otra versión**: fixups nuevos → `unknown_effect`
  (fail-closed); un fixup que cambie de efecto no se detecta: la tabla de
  traducción cita la versión.
- **El reinicio del Supervisor corta Hermes**: probado con el simulado (corte
  de conexión → `started`); en vivo, pendiente.
