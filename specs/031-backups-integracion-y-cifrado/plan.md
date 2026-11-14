# Plan de implementación: backups de la integración `backup` y safety backups cifrados (031)

**Rama**: `feat/031-backups-integracion-y-cifrado` (no se crea ninguna) | **Fecha**: 2026-11-15 | **Spec**: [spec.md](spec.md) | **Programa**: [008](../008-cobertura-total/plan.md), sub-feature 031, ola 3

## Resumen

Ocho tools dedicadas nuevas en la familia nueva `backup_integration`: dos de
lectura (agentes; ajustes de backup previos a actualizar) y seis con
confirmación (configuración de los backups automáticos, ajustes previos a
actualizar, crear, crear con los ajustes automáticos, restaurar y borrar).
Los ocho comandos que la 011 dejó en `deny` «pendiente de tool dedicada (spec
031)» pasan a `dedicated`. Restaurar lleva la vista previa más completa del
programa, con el token atado al backup en la ubicación elegida. Los safety
backups pasan a cifrarse con la clave de cifrado de los backups de Home
Assistant (la del kit de emergencia), según la opción nueva
`safety_backup_encryption`; la retención sigue podándolos y las
`sv_restore_*` usan esa clave cuando no se pasa contraseña. Cuatro tramos.

## Dependencias y momento de la implementación

- **Tramos 1 y 2**: la base de `feat/cobertura-total` basta (009, 010, 011,
  018, 028 y 029 integradas; estado atado de la 018; mecanismo de
  `_DEDICADAS_INICIALES` para la clase A de la 029).
- **Tramo 3** (restaurar, `password` atado al token): necesita el `action_hash`
  con HMAC de la **019** (`security.py`). T001 del tramo 3 lo comprueba; sin
  él, el tramo no empieza.
- **Tramo 4** (opción nueva): si la **027** está integrada, la opción va
  también a `hermes/translations/en.yaml` y `es.yaml`; si no, la tarea lo
  anota y lo hace quien integre la segunda. La **014** ya está: matriz de
  pruebas en `docs/HOJA-DE-RUTA.md`.
- Conflictos previsibles con la 019 en `tools/backups.py`
  (`sv_create_backup_*` con `location`; aquí, el safety backup y las
  `sv_restore_*`), `guide.py` (tema `backups`), `tool_families.py`,
  `command_table.py`, el recuento de los README y el CHANGELOG: sitios
  distintos de los mismos ficheros; se conservan los de las dos.

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x, aiohttp, structlog (ninguna nueva) · **Almacenamiento**: campo nuevo `encrypted` en `/data/safety_backups.json`; nada más (la clave no se guarda) · **Tests**: pytest con `unittest.IsolatedAsyncioTestCase`, `DummyMCP`/`_RecordingMCP`, `AsyncMock` de `ws_send` y `sv_request`, `structlog.testing.capture_logs`, `HERMES_CONFIG_BASE` propio; banco de Core de la 010 con el lector independiente · **Plataforma**: add-on de HA OS.

**Restricciones**: fail-closed (III); el token atado (IV); anotaciones verdaderas (V); control negativo (VII); repositorio público (VIII); cambios mínimos (IX); FR-020 de la 008 salvo lo que manda FR-068.

**Escala**: 8 tools (6 modifican, 6 confirman), 3 módulos de tools, 1 módulo de Hermes (`backup_key.py`), 1 función pura (estimación de retención), 1 familia, 1 tema de guía y el de `backups` ampliado, 8 entradas de la tabla a `dedicated`, 1 opción del add-on, 4 tools existentes con un cambio compatible.

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Restaurar y borrar dejan de estar en `deny` solo con una tool cuya vista previa dice exactamente qué pasa. Crear confirma porque una copia completa de la casa puede salir a otro equipo o a la nube. La clave de cifrado nunca pasa por el cliente para crear ni para el safety backup; todo sale por lista blanca. | OK |
| II. Secretos | La clave de HA y `password` no salen en respuestas, vistas previas, errores, ficheros de token ni log; `ClaveDeBackups` tapa su `repr`; centinela en cada salida y en el banco (SC-002). `password` atado por HMAC (019), nunca guardado. Los safety backups, que llevan `secrets.yaml` y los tokens de las integraciones, pasan a ir cifrados. | OK |
| III. Fail-closed | Validación de cada argumento antes de llamar; agente desconocido, contenido que no está en el backup o base de datos que no cuadra → error sin token; `encrypt` sin clave → error; `required` sin clave bloquea; respuesta inesperada al leer la clave → sin clave; el estado cambia → no se ejecuta; restaurar sin respuesta nunca se da por bueno. | OK |
| IV. Dos pasos, token atado | Seis tools con token, atado a los argumentos y a la huella del estado que describe la vista previa (backup y ubicación al restaurar; ubicaciones al borrar; configuración y estimación al cambiar ajustes). Las vistas previas no prometen nada que no se ejecute: la retención va como estimación con sus reglas. | OK |
| V. Nombre y descripción | Crear con ajustes automáticos es otra tool porque borra; anotaciones por tabla central con su porqué (crear y restaurar de mundo abierto). `restore_started` en vez de un éxito inventado. Descripciones que dicen lo que no hacen (no cambian la clave; no esperan a que termine el backup). | OK |
| VI. Lo que no se puede probar | Cinco tools ejecutadas en el banco contra HA real con el efecto leído por el lector; la estimación de retención contrastada con el borrado real de HA. Restaurar y las de `hassio` quedan con motivo en `NO_EJECUTABLES_031`, en la matriz de la 014 y en quickstart como prueba en vivo. | OK |
| VII. Control negativo | Uno por comportamiento con riesgo en cada tramo (T015, T030, T045, T059), con recuentos en el commit. | OK |
| VIII. Privacidad | Fixtures con `hassio.nas_backups`, `cloud.cloud`, `core_mosquitto`, `192.0.2.x`, `centinela-031`; revisión del diff al cerrar cada tramo. | OK |
| IX. Cambios mínimos | Solo CAP-027 y CAP-057. Las `sv_create_backup_*` no cambian (la 019 les añade `location`). `ha_list_backups` gana un campo; las `sv_restore_*` solo cambian en el caso que hoy falla. | OK |
| X. Comentarios en español | Comentarios y eventos del log en español; descripciones al cliente en inglés y guía en español, como hoy. | OK |
| XI. Versionado | Sin subir versión (1.2.0 de la 009); sección propia en `## [1.2.0]`. | OK |
| Flujo, puerta 4 | Suite, banco, Semgrep y CodeQL en verde en el CI al cerrar cada tramo. | OK |

Tras el diseño: sin cambios. Desviaciones justificadas: el mecanismo de la
clave de FR-068 (research R-3, D-031-1) y los cuatro tramos (R-15, D-031-2).

## Diseño

### Tramo 1 — Agentes y ajustes (US1, US6)

1. Familia `backup_integration` con el módulo `ha_backup_settings` (los otros
   dos se añaden en sus tramos) y registro en `tools/__init__.py` bajo
   `if _activa("backup_integration")`.
2. `hermes/src/hermes/tools/ha_backup_settings.py`: `ha_list_backup_agents`,
   `ha_update_backup_config`, `ha_get_update_backup_settings`,
   `ha_set_update_backup_settings`. Reutiliza de `tools/ha_backups.py`
   `_config_permitida`, `_saneado`, `_comprobar_version` (se extraen a
   funciones de módulo si hace falta, sin cambiar su comportamiento).
3. `hermes/src/hermes/backup_retention_estimate.py`: `estimar_retencion`
   (función pura, data-model sección 4).
4. Anotaciones: `ha_update_backup_config` y `ha_set_update_backup_settings` en
   `_DESTRUCTIVE_EXACT`.
5. Tabla: `backup/agents/info`, `backup/config/update` y
   `hassio/update/config/*` a `dedicated`; claves en `_DEDICADAS_INICIALES`.
6. Guía: tema `backup_integration` con lo del tramo.
7. Banco: `backup:` en la configuración; `tests/banco/test_banco_backups_ajustes.py`;
   `tests/banco/cobertura_031.py` con `PROBADAS_031` y `NO_EJECUTABLES_031`
   iniciales, sumados al invariante y a `TOOLS_EXIGIDAS_DEL_JOB`.
8. Documentación parcial: recuento y familia en README y DOCS, CHANGELOG,
   hoja de ruta («en curso»), filas de la matriz de pruebas.

### Tramo 2 — Crear y borrar (US2, US4)

1. `hermes/src/hermes/backup_key.py`: `ClaveDeBackups`, `leer_clave_de_backups`.
2. `hermes/src/hermes/tools/ha_backup_actions.py`: `ha_create_backup`,
   `ha_create_automatic_backup`, `ha_delete_backup`; módulo añadido a la
   familia.
3. `ha_list_backups`: `last_action_event`.
4. Anotaciones: las dos de crear en `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD`;
   `ha_delete_backup` en `_OPEN_WORLD`.
5. Tabla: `backup/generate`, `backup/generate_with_automatic_settings` y
   `backup/delete` a `dedicated` (y sus filas del inventario, R-13).
6. Guía, banco (`test_banco_backups_acciones.py`), inventario, matriz,
   documentación parcial.

### Tramo 3 — Restaurar (US3, US5 restauración)

1. Comprobar que la 019 (HMAC) está integrada.
2. `HAConnectionError.sent` y `ws_send` que lo marca (R-6).
3. `hermes/src/hermes/tools/ha_backup_restore.py`: `ha_restore_backup`.
4. `sv_restore_backup_full`/`_partial`: `password_source` y la clave de HA.
5. Anotaciones (`_DESTRUCTIVE_EXACT`, `_OPEN_WORLD`), tabla (`backup/restore`),
   guía, banco (`test_banco_backups_restaurar.py`), `NO_EJECUTABLES_031`,
   matriz, documentación parcial.

### Tramo 4 — Safety backups cifrados y cierre (US5, US6)

1. Opción `safety_backup_encryption`: `config.yaml`, `run.sh`, `config.py`,
   `__main__.py`/`tools/__init__.py` (cableado), traducciones (si la 027
   está), DOCS.
2. `sv_create_safety_backup` y `fs_write._maybe_trigger_safety_backup` con la
   clave según la opción; respuesta `encrypted`.
3. `safety_retention`: `record_launch(..., encrypted=)` y
   `_motivo_exclusion`.
4. Tema `backups` de la guía; `SECURITY.md`.
5. Documentación final: CHANGELOG, hoja de ruta («hecha» y fuera de
   pendientes), README, DOCS, matriz de la 008.

## Estructura de ficheros

```text
hermes/
├── config.yaml                            # opción safety_backup_encryption (4)
├── run.sh                                 # su variable de entorno (4)
├── translations/en.yaml, es.yaml          # si la 027 está (4)
└── src/hermes/
    ├── backup_key.py                      # NUEVO (2)
    ├── backup_retention_estimate.py       # NUEVO (1)
    ├── config.py                          # safety_backup_encryption (4)
    ├── __main__.py                        # cableado de la opción (4)
    ├── ha.py                              # HAConnectionError.sent (3)
    ├── fs_write.py                        # safety backup cifrado (4)
    ├── safety_retention.py                # encrypted en la anotación (4)
    ├── tool_families.py                   # backup_integration (1, 2, 3)
    ├── command_table.py                   # 8 entradas dedicated (1, 2, 3)
    └── tools/
        ├── __init__.py                    # registro (1, 2, 3); opción (4)
        ├── _annotations.py                # (1, 2, 3)
        ├── guide.py                       # backup_integration (1, 2, 3), backups (4)
        ├── ha_backups.py                  # last_action_event (2)
        ├── backups.py                     # sv_restore_* (3), safety (4)
        ├── ha_backup_settings.py          # NUEVO (1)
        ├── ha_backup_actions.py           # NUEVO (2)
        └── ha_backup_restore.py           # NUEVO (3)
scripts/inventario/generar_tabla.py        # _DEDICADAS_INICIALES (1, 2, 3)
specs/008-cobertura-total/inventario/core-ws.tsv  # 4 filas «cubierto» (2, 3)
tests/
├── test_backup_retention_estimate.py      # NUEVO (1)
├── test_tools_ha_backup_settings.py       # NUEVO (1)
├── test_backup_key.py                     # NUEVO (2)
├── test_tools_ha_backup_actions.py        # NUEVO (2)
├── test_tools_ha_backup_restore.py        # NUEVO (3)
├── test_sv_restore_backup_key.py          # NUEVO (3)
├── test_safety_backup_encryption.py       # NUEVO (4)
├── test_tools_ha_backups.py               # last_action_event (2)
├── test_safety_retention.py               # cifrados (4)
├── test_ha_*.py del cliente               # sent (3)
├── test_tool_families.py, test_tools_registration.py, test_tools_generic_commands.py,
│   test_command_table.py, test_generar_tabla.py, test_tools_guide.py (1, 2, 3)
├── test_addon_manifest.py, test_run_sh_options.py, test_config_validation.py,
│   test_main_wiring.py (4)
└── banco/
    ├── ha_config/configuration.yaml       # backup: (1)
    ├── cobertura_031.py                   # NUEVO (1, 2, 3)
    ├── cobertura_escrituras.py            # unión y TOOLS_EXIGIDAS_DEL_JOB (1)
    ├── test_banco_backups_ajustes.py      # NUEVO (1)
    ├── test_banco_backups_acciones.py     # NUEVO (2)
    └── test_banco_backups_restaurar.py    # NUEVO (3)
tests/test_banco_cobertura_escrituras.py   # suma de la 031 (1)
hermes/CHANGELOG.md, hermes/DOCS.md, README.md, README.es.md, SECURITY.md,
docs/HOJA-DE-RUTA.md, specs/008-cobertura-total/plan.md      # (1–3 parcial, 4)
```

## Trazabilidad

| FR (031) | FR (008) | CAP | Tareas | Test |
|---|---|---|---|---|
| FR-001 | FR-067 | CAP-057 | T003, T008 | `test_tools_ha_backup_settings.py` |
| FR-002 | FR-067 | CAP-057 | T004, T008 | `test_tools_ha_backup_settings.py` |
| FR-003 | FR-067 | CAP-057 | T002, T007, T029 | `test_backup_retention_estimate.py`, banco |
| FR-004 | FR-067 | CAP-057 | T005, T008 | `test_tools_ha_backup_settings.py` |
| FR-005 | FR-067 | CAP-057 | T019, T023 | `test_tools_ha_backup_actions.py` |
| FR-006 | FR-067 | CAP-057 | T020, T023 | `test_tools_ha_backup_actions.py` |
| FR-007 | FR-067, FR-018 | CAP-057 | T034, T035, T038 | `test_tools_ha_backup_restore.py` |
| FR-008 | FR-018 | CAP-057 | T033, T036, T038 | `test_tools_ha_backup_restore.py`, tests del cliente |
| FR-009 | FR-067, FR-018 | CAP-057 | T021, T023 | `test_tools_ha_backup_actions.py` |
| FR-010 | FR-067, FR-020 | CAP-057 | T018, T024 | `test_tools_ha_backups.py` |
| FR-011 | FR-019, FR-068 | CAP-027 | T017, T022, T029, T051 | `test_backup_key.py`, banco |
| FR-012 | FR-068, FR-023 | CAP-027 | T048, T052 | `test_addon_manifest.py`, `test_run_sh_options.py`, `test_config_validation.py`, `test_main_wiring.py` |
| FR-013 | FR-068 | CAP-027 | T049, T053 | `test_safety_backup_encryption.py` |
| FR-014 | FR-068 | CAP-027 | T050, T054 | `test_safety_retention.py` |
| FR-015 | FR-068 | CAP-027 | T037, T039 | `test_sv_restore_backup_key.py` |
| FR-016 | FR-010 | CAP-004 | T006, T009, T025, T040 | `test_tool_families.py`, `test_tools_registration.py` |
| FR-017 | FR-012 | CAP-001 | T010, T011, T026, T027, T041, T042 | `test_command_table.py`, `test_generar_tabla.py`, `test_tools_generic_commands.py` |
| FR-018 | FR-018 | — | T006, T009, T025, T040 | `test_tools_registration.py` |
| FR-019 | FR-018, FR-019, FR-021 | CAP-011 | T003…T005, T019…T021, T034, T051 | ídem (log capturado y centinelas) |
| FR-020 | FR-018 | — | T003…T005, T019…T021, T034 | ídem |
| FR-021 | FR-011 | CAP-008 | T012, T028, T043, T055 | `test_tools_guide.py` |
| FR-022 | FR-015, FR-016 | CAP-034 | T013, T014, T029, T044 | `tests/banco/test_banco_backups_*.py`, `test_banco_cobertura_escrituras.py`, `test_matriz_pruebas.py` |
| FR-023 | FR-020 | — | T009, T024, T039, T053, T057 | `test_tools_registration.py`, `test_tools_supervisor.py`, `test_fs_write_security.py` |
| FR-024 | FR-021, FR-023, FR-024 | — | T016, T031, T046, T056, T058 | `TestToolCountInDocs`, `test_matriz_pruebas.py`; revisión |

## Tramos

| Tramo | Tareas | Tools | Entradas de la tabla |
|---|---|---|---|
| 1 — Agentes y ajustes | T001–T016 | 4 | 4 a `dedicated` |
| 2 — Crear y borrar | T017–T031 | 3 (+ `last_action_event`) | 3 a `dedicated` |
| 3 — Restaurar | T032–T046 | 1 (+ `sv_restore_*` con la clave) | 1 a `dedicated` |
| 4 — Safety backups cifrados y cierre | T047–T060 | 0 (cambios en `sv_create_safety_backup` y `fs_write`) | — |

Cada tramo cabe en el contexto de un agente y deja la suite en verde: el 1,
cuatro tools de ajustes y una función pura; el 2, tres tools y un módulo
pequeño; el 3, una tool con la vista previa larga y un cambio pequeño en dos
tools existentes; el 4, una opción, dos llamadas al Supervisor, la retención y
la documentación final.

## Riesgos

- **La estimación de retención no coincide con HA**: se reproduce su código de
  2026.11.1 y se contrasta en el banco con un borrado real; se presenta como
  estimación.
- **Restaurar no responde**: `restore_started` honesto; el banco no puede
  probar el camino feliz (VM de la 014).
- **Distinguir enviado de no enviado** necesita tocar `HAClient` (aditivo,
  `sent`); si la 029 u otra cambia `ws_send`, se integra encima.
- **Conflictos con la 019** en `tools/backups.py`, `guide.py` y la
  documentación: sitios distintos; se conservan los de las dos.
- **Clave de HA rotada**: los safety backups anteriores necesitan la clave
  anterior; el error de contraseña lo dice y DOCS lo explica.
