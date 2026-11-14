# Plan de implementación: montajes de red y ajustes de backup del Supervisor (019)

**Rama**: `feat/019-montajes-y-ajustes-de-backup` (sale de `feat/cobertura-total`, `cc92b4a`) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md)

**Entrada**: [spec.md](spec.md), la paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/plan.md) (CAP-083,
FR-066) y el código del Supervisor 2026.11.0.

## Resumen

Nueve tools dedicadas en una familia nueva, `mounts`, para los montajes de red
del Supervisor (listar, crear, editar, borrar, recargar y fijar el montaje por
defecto de backups) y sus ajustes de backup (`days_until_stale` y releer
backups), más `location` opcional en `sv_create_backup_full` y
`sv_create_backup_partial`. Crear, editar, borrar y el montaje por defecto van
en dos pasos con una vista previa que dice los efectos sobre los backups y el
montaje por defecto; las credenciales CIFS entran, se atan al token por su
hash y nunca salen. Las 9 rutas de CAP-083 pasan de `deny` «pendiente (spec
019)» a `dedicated`. Todo se prueba con el Supervisor simulado de la suite y
queda en la matriz de la 014 como VM / pendiente. Dos tramos (research R-12).

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x, aiohttp,
structlog (sin dependencias nuevas) · **Almacenamiento**: ninguno nuevo; el
fichero del token de siempre en `/data/pending_confirmations`, solo con el
`action_hash` · **Tests**: pytest con `unittest.IsolatedAsyncioTestCase`,
`DummyMCP`, `MockHAClient` (Supervisor simulado con la forma de 2026.11.0),
`structlog.testing.capture_logs`, `CONFIRMATIONS_DIR` temporal (lo pone
`tests/conftest.py`) · **Plataforma**: add-on de Home Assistant OS ·
**Tipo**: servidor MCP · **Rendimiento**: una o dos lecturas del Supervisor
por vista previa (`/mounts`, `/backups`); respuestas pequeñas, siempre bajo el
tope central · **Restricciones**: fail-closed, dos pasos con token atado,
anotaciones verdaderas, secretos fuera de todo retorno y log, repositorio
público · **Escala**: 9 tools nuevas (de las ~9 que estima la 008), 1
argumento opcional nuevo en 2 tools, 9 entradas de la tabla.

Sin incógnitas abiertas: las decisiones están en [research.md](research.md)
(R-1…R-12).

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Las respuestas de montajes usan una **lista permitida** de claves y `redact_structure`, no la respuesta del Supervisor tal cual (FR-001); los errores pasan por la limpieza de credenciales y `redact_secrets` (FR-008, FR-010); las genéricas rechazan las 9 rutas hacia su tool (FR-015). | OK |
| II. Secretos | Usuario y contraseña CIFS nunca en respuesta, vista previa, error ni log (FR-008, FR-020); no se guardan en el fichero del token (no omitibles; solo el `action_hash`); se rechaza el marcador de redacción y los caracteres de control; centinelas en todos los caminos, también el directorio de tokens (FR-019, SC-004). El hash con la contraseña dentro es el compromiso ya aceptado de `fs_set_secret` y `sv_restore_backup_*` (S-04, research R-5). | OK |
| III. Fail-closed | Validación completa antes de escribir y sin copiar valores (FR-007, SC-003); formas inesperadas del Supervisor → `error` (FR-010); nombre que ya existe o que no existe → error sin token; `.cloud_backup` rechazado (FR-014); `disk` no se crea ni se edita y su `POST /mounts` deja de ser alcanzable por la genérica (research R-2). | OK |
| IV. Dos pasos, token atado | Crear, editar, borrar y el montaje por defecto en dos pasos (FR-002…FR-004, FR-006); el token ata todos los argumentos, incluida la contraseña, y la huella del estado que la vista previa describe (FR-009, research R-6); inventario de la 033 (FR-009). Vistas previas que dicen los efectos: montaje por defecto, backups que dejan de verse, credenciales que se quitan, remontaje (data-model). | OK |
| V. Nombre y descripción | Anotaciones por la tabla central: 4 destructivas ⇔ 4 con token; 2 de solo lectura por prefijo; 3 que modifican sin ser destructivas ni de solo lectura (FR-016); las descripciones dicen que editar sin credenciales las quita, que crear prueba la conexión y que `location` vacía usa el por defecto. Sin verbos de escritura en `read` (la tabla gana solo `dedicated`). | OK |
| VI. Lo que no se puede probar | Unitarios contra el Supervisor simulado con respuestas sacadas del código de 2026.11.0; el banco de Core no aplica (su Supervisor solo reenvía a Core). Las 7 que modifican van a la matriz como **VM / pendiente** con su línea en el procedimiento (FR-021, SC-008). | OK con pendiente declarado |
| VII. Control negativo | T016 y T030 con recuentos: lista permitida, omitibles, contraseña fuera del hash, huella, limpieza de errores, caracteres de control, aviso de credenciales, log con servidor, `dedicated`, carga sin `location`. | OK |
| VIII. Privacidad | Fixtures con `nas.local`, `192.0.2.10`, `backups`, centinelas de texto; el log no lleva servidor, recurso ni ruta (FR-020); revisión del diff en cada tramo. | OK |
| IX. Cambios mínimos | Un módulo nuevo por tramo; `sv_create_backup_*` gana un opcional sin tocar su camino por defecto; ningún cambio en `security.py`; la regla de clase A del test de la tabla ya admite `dedicated` (013) o se amplía igual; `disk`, la 031 y el HMAC del hash quedan fuera (dudas). | OK |
| X. Comentarios en español | Comentarios en español con el porqué; descripciones, errores al cliente y eventos en inglés. | OK |
| XI. Versionado | Sin subida de versión (la fijó la 009); sección propia en `## [1.2.0] — <fecha de publicación>` (E-4). | OK |
| Flujo, puerta 4 (CI) | Cada tramo deja la suite en verde en el CI de Linux (6 fallos conocidos en local). | OK |

**Tras el diseño**: sin cambios. Ninguna desviación sin justificar.

## Diseño

### Tramo 1 — montajes (CAP-083, `/mounts`)

- **Familia** `mounts` en `tool_families.py` con el módulo `mounts`; registro
  en `tools/__init__.py` bajo `_activa("mounts")`, después de `backups`.
- **Módulo** `hermes/src/hermes/tools/mounts.py`:
  - `_validar_*`: reglas de FR-007 sobre cada argumento y sobre el resultado
    fundido; devuelven la regla, nunca el valor.
  - `_montaje_publico(m)`: lista permitida (data-model) + `redact_structure`.
  - `_leer_estado()`: `GET /mounts` → `(por_defecto, {nombre: montaje})`;
    forma inesperada → error. `_backups_en(nombre)`: `GET /backups` → los que
    tienen el nombre en `locations` (con `only_here` si es la única).
  - `_huella(...)`: dict canónico de data-model; entra como `_estado` en el
    dict del hash (research R-6).
  - `_limpiar_error(texto, secretos)`: sustituye los valores literales y pasa
    por `redact_secrets`.
  - Las seis tools con el flujo de [contracts/tools.md](contracts/tools.md).
    `create_confirmation_token` **sin** `omitibles`.
- **Anotaciones**: `sv_create_mount`, `sv_update_mount` y
  `sv_set_default_backup_mount` a `_DESTRUCTIVE_EXACT`, con comentario.
- **Tabla**: las 6 entradas `/mounts*` a `dedicated` a mano (una línea cada
  una, como la 013) y regeneración sin cambios.
- **Inventario de la 033** si está en la rama (S-01).
- **Matriz de la 014**: 5 filas (`sv_create_mount`, `sv_update_mount`,
  `sv_delete_mount`, `sv_reload_mount`, `sv_set_default_backup_mount`) y sus
  líneas en «Tools nuevas del programa» del procedimiento (crear y recargar en
  la tanda 1; editar, borrar y el por defecto con instantánea antes).
- **Guía**: tema `mounts` (parte de montajes) con sus alias.

### Tramo 2 — ajustes de backup y `location`

- **Módulo** `hermes/src/hermes/tools/backup_settings.py` con
  `sv_get_backup_settings`, `sv_set_backup_settings` y `sv_reload_backups`;
  la familia gana el módulo.
- **`location`** en `tools/backups.py`: un validador común para las dos
  tools; la clave solo se añade a la carga si se pasa; respuesta y evento con
  `location`. Excepción anotada en `test_esquemas_de_la_1_1_2`.
- **Tabla**: las 3 entradas `/backups/{info,options,reload}` a `dedicated`;
  ninguna «spec 019».
- **Matriz**: 2 filas (`sv_set_backup_settings`, `sv_reload_backups`) y sus
  líneas; la de `sv_create_backup_*` dice que se prueba `location`.
- **Guía** completa (ajustes y `location` en `backups`) y **documentación**:
  CHANGELOG, DOCS, README, hoja de ruta y fila CAP-083 de la 008.

## Estructura de ficheros

```text
specs/019-montajes-y-ajustes-de-backup/
├── spec.md · plan.md · research.md · data-model.md · quickstart.md · tasks.md
├── contracts/tools.md
└── checklists/requirements.md

hermes/src/hermes/
├── tool_families.py              # familia `mounts` (T002, T020)
├── command_table.py              # 9 entradas a `dedicated` (T012, T027)
└── tools/
    ├── __init__.py               # registro bajo `_activa("mounts")` (T011, T025)
    ├── _annotations.py           # 3 en _DESTRUCTIVE_EXACT (T011)
    ├── mounts.py                 # NUEVO, tramo 1 (T010)
    ├── backup_settings.py        # NUEVO, tramo 2 (T025)
    ├── backups.py                # `location` (T026)
    └── guide.py                  # tema `mounts`; `backups` con `location` (T015, T029)

tests/
├── fixtures/supervisor_montajes.py      # NUEVO: respuestas simuladas (T003)
├── test_tools_mounts.py                 # NUEVO (T004–T009)
├── test_tools_backup_settings.py        # NUEVO (T021–T023)
├── test_tools_supervisor.py             # `location` (T024)
├── test_tool_families.py · test_config_validation.py   (T002, T020)
├── test_tools_registration.py           # hints, títulos, familia, esquemas (T011, T026)
├── test_command_table.py · test_tools_generic_commands.py   (T012, T027)
├── test_confirmation_args_inventory.py  # si existe (033) (T013)
├── test_matriz_pruebas.py               # sin cambios: la matriz y el procedimiento (T014, T028)
└── test_tools_guide.py                  (T015, T029)

docs/HOJA-DE-RUTA.md · docs/BANCO-SUPERVISOR.md · hermes/CHANGELOG.md ·
hermes/DOCS.md · README.md · README.es.md · specs/008-cobertura-total/plan.md
```

## Trazabilidad (FR de la 019 → FR/CAP de la 008 → tarea → test)

| FR 019 | FR 008 | CAP | Tareas | Test |
|---|---|---|---|---|
| FR-001 | FR-066, FR-018, FR-019 | 083 | T004, T010 | `test_tools_mounts.py` (`TestListar`) |
| FR-002 | FR-066 | 083 | T005, T010 | ídem (`TestCrear`) |
| FR-003 | FR-066 | 083 | T006, T010 | ídem (`TestEditar`) |
| FR-004 | FR-066 | 083 | T007, T010 | ídem (`TestBorrar`) |
| FR-005 | FR-066 | 083 | T008, T010 | ídem (`TestRecargar`) |
| FR-006 | FR-066 | 083 | T008, T010 | ídem (`TestPorDefecto`) |
| FR-007 | FR-066 | 083 | T005, T006, T010 | ídem (`TestValidacion`) |
| FR-008 | FR-019, FR-066 | 083 | T005, T009, T010 | ídem (`TestSecretos`) |
| FR-009 | FR-018, FR-066 | 083 | T005–T008, T010, T013 | ídem (`TestTokenAtado`), `test_confirmation_args_inventory.py` |
| FR-010 | FR-066 | 083 | T005, T008, T010 | ídem (errores y pistas) |
| FR-011 | FR-066 | 083 | T021, T025 | `test_tools_backup_settings.py` |
| FR-012 | FR-066 | 083 | T022, T025 | ídem |
| FR-013 | FR-066 | 083 | T023, T025 | ídem |
| FR-014 | FR-066, FR-020 | 083 | T024, T026 | `test_tools_supervisor.py` (`TestUbicacionDelBackup`) |
| FR-015 | FR-012, FR-066 | 001, 083 | T012, T027 | `test_command_table.py`, `test_tools_generic_commands.py` |
| FR-016 | FR-010, FR-018 | 004 | T002, T011, T020, T025 | `test_tool_families.py`, `test_tools_registration.py` |
| FR-017 | FR-020 | 030 | T026 | `test_tools_registration.py` (esquemas) |
| FR-018 | FR-011, FR-018 | 008 | T015, T029 | `test_tools_guide.py` |
| FR-019 | FR-019 | 083 | T009 | `test_tools_mounts.py` (`TestSecretos`) |
| FR-020 | FR-019 | 083 | T009, T022 | `test_tools_mounts.py`, `test_tools_backup_settings.py` (log capturado) |
| FR-021 | FR-016 | 006 | T014, T028 | `test_matriz_pruebas.py` |
| FR-022 | FR-016, FR-021, FR-023, FR-024 | — | T017, T031 | revisión del diff (documental) |

## Tramos

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado; el 2 necesita el 1 integrado.

| Tramo | Contenido | Tareas |
|---|---|---|
| 1 | Línea base, familia, fixtures, 6 tools de montajes con secretos y token atado al estado, anotaciones, 6 `dedicated`, inventario de la 033, matriz y procedimiento (5), guía de montajes, CHANGELOG/DOCS/README (parte), control negativo | T001–T018 |
| 2 | 3 tools de ajustes de backup, `location` en `sv_create_backup_*`, 3 `dedicated`, matriz y procedimiento (2), guía completa, documentación completa y fila de la 008, control negativo | T019–T032 |

## Pruebas en vivo (pendiente declarado)

En la VM de la 014 (`docs/BANCO-SUPERVISOR.md`), con un recurso CIFS y uno NFS
de prueba (un contenedor Samba o NFS en la misma red de la VM): crear con y
sin credenciales, editar con y sin ellas, crear un backup con `location`,
borrar el montaje con ese backup y comprobar la vista previa, fijar y quitar el
por defecto, `days_until_stale` y releer backups. Cada fila de la matriz pasa
de `pendiente` a `ok` o `falla` con la nota que exige la 014.

## Dependencias

- 011 (tabla, genéricas, familias, `esquemas_1_1_2.json`) y 014 (matriz y
  procedimiento): integradas en la base.
- 033 (inventario de argumentos atados): puede no estar; S-01.
- 013 no es necesaria: `GET /host/disks` y `sv_get_disk_usage` no se tocan.
- 031: no se pisa, pero las dos tocan `tools/backups.py` (la 031, los safety
  backups cifrados; la 019, `location` en dos tools). Al integrar, conflicto
  posible solo de texto.

## Riesgos

- **Recuento del inventario de la 033 y de la tabla**: otras sub-features
  suben los mismos números (`test_recuento`, recuentos por categoría). Se
  resuelve al integrar; cada tramo anota los suyos.
- **Forma real del Supervisor**: las respuestas simuladas salen del código
  leído; si la VM enseña otra cosa (por ejemplo, `state` con otro vocabulario),
  se corrige en el cierre del programa.
- **Contraseñas débiles y el hash**: riesgo residual documentado (research
  R-5); duda para el final.
