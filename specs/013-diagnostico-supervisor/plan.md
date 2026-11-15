# Plan de implementación: diagnóstico del Supervisor (013)

**Rama**: `feat/013-diagnostico-supervisor` (sale de la de la 011; se integra en `feat/cobertura-total`) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md) | **Paraguas**: [008](../008-cobertura-total/plan.md)

## Resumen

Once tools nuevas de **solo lectura** en una familia nueva,
`system_diagnostics`: seis de logs (Core, Supervisor, plugins y host, también
de arranques anteriores, más la lista de arranques y de identificadores del
journal; CAP-081) y cinco de disco, host y OS (servicios del host, uso de disco
con profundidad acotada, información del OS, swap y discos candidatos a disco
de datos; CAP-085). `sv_get_addon_logs` gana `boot` y `latest` opcionales. En
la tabla de la 011, 28 rutas pasan a `dedicated` y tres a `read` (`/jobs/info`,
las sugerencias de un issue y `/host/disks`); las de hardware, seguridad,
Docker, hora y red ya eran `read` y ganan tests. La comprobación de integridad
sigue `deny` porque el Supervisor 2026.11 la eliminó. Nada escribe: el control
de Core y del Supervisor es de la 022. Dos tramos. La prueba en vivo queda
pendiente para la 014 o el cierre.

Detalle y alternativas en [research.md](research.md); entidades y tabla en
[data-model.md](data-model.md); firmas y respuestas en
[contracts/tools.md](contracts/tools.md); validación en
[quickstart.md](quickstart.md).

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x, aiohttp, structlog (sin dependencias nuevas) · **Almacenamiento**: ninguno nuevo · **Tests**: pytest, `unittest.IsolatedAsyncioTestCase`, `DummyMCP`, un `MockHAClient` como Supervisor simulado con respuestas de la forma del Supervisor 2026.11.0, `structlog.testing.capture_logs` · **Plataforma**: add-on de Home Assistant OS.

**Restricciones**: solo lectura (ninguna llamada distinta de `GET`); validación fail-closed antes de llamar (III); redacción de secretos en todo log devuelto y de red en el de Hermes (I, II); nada del contenido en el log de Hermes (II, VIII); las 216 tools de la 1.1.2 sin cambios salvo los dos argumentos opcionales de `sv_get_addon_logs` (FR-020 de la 008); la escritura es de la 022 y la 032.

**Escala**: 11 tools nuevas en 2 módulos nuevos (`tools/system_logs.py`, `tools/host_system.py`); cambios en `tools/addons.py` (`sv_get_addon_logs`), `tool_families.py`, `command_table.py` (31 líneas), `tools/__init__.py`, `tools/_annotations.py` (`"os": "OS"`), `tools/guide.py`; 3 ficheros de test nuevos y una fixture; ajustes en `tests/test_command_table.py`, `tests/test_tools_registration.py`, `tests/test_tool_families.py`, `tests/test_tools_guide.py` y la instantánea de esquemas.

## Comprobación de la constitución

Contra la constitución 1.2.0 (con las enmiendas E-1…E-4 de la 011).

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Solo `GET`; cada respuesta pasa por una decisión explícita: logs con `redact_secrets` (y `redact_network` si son de Hermes, también por el journal del host), respuestas JSON con `redact_structure`, uso de disco podado, listas con el sobre común; las rutas por la tabla pasan por las guardas de la 011 (FR-008, FR-009, FR-012, FR-017…FR-020). | OK |
| II. Secretos | Centinelas en los cinco orígenes de log (FR-024); el log de Hermes lleva plantilla de ruta, recuentos y bytes, nunca contenido ni `boot`/`identifier`/`search` (FR-010); los errores del Supervisor salen redactados (FR-016). | OK |
| III. Fail-closed | `boot`, `latest`+`boot`, `identifier`, `plugin`, `disk` y `max_depth` se validan antes de llamar y se rechazan sin llamar (SC-003); errores del Supervisor como error, nunca como respuesta vacía (FR-016); la integridad sigue `deny`. | OK |
| IV. Dos pasos | No aplica: ninguna tool modifica nada. Ninguna toma `confirmation_token` (FR-021). La escritura de CAP-084/087 es de la 022. | N/A |
| V. Nombre y descripción | `sv_get_`/`sv_list_` son de lectura y lo son; títulos correctos (`OS`); las descripciones dicen que el log se redacta y se recorta por el principio, el límite de `max_depth` y la poda, y que sin journal el Supervisor ignora `boot`/`latest` en su propio log (FR-002, FR-021). La tabla gana tres `read` sin verbo de escritura (test de verbos). | OK |
| VI. Lo que no se puede probar | Unitarios contra un Supervisor simulado con la forma de 2026.11.0; las genéricas con las rutas reales de la tabla; el banco de Core no aplica (su Supervisor solo reenvía a Core y aquí nada modifica). Prueba en vivo **pendiente** para la 014 o el cierre, con su casilla en la hoja de ruta (FR-025, SC-007). | OK con pendiente declarado |
| VII. Control negativo | T013 y T027 con recuentos: validación de `boot`, redacción de red del host, recorte por el final, poda, `dedicated` en la tabla, log sin direcciones. | OK |
| VIII. Privacidad | Fixtures con `192.0.2.x`, `02:00:00:00:00:01`, `red-ficticia`, `<slug>`, ids de arranque inventados; revisión del diff en cada tramo. | OK |
| IX. Cambios mínimos | `sv_get_addon_logs` gana dos opcionales sin tocar su camino por defecto; `_ultimas_lineas_que_caben` y `_es_hermes` se reutilizan desde `tools/addons.py` sin moverlas; la regla del test de la tabla se amplía, no se reescribe; nada de escritura. | OK |
| X. Comentarios en español | Comentarios en español con el porqué; descripciones, errores al cliente y eventos en inglés. | OK |
| XI. Versionado | Sin subida de versión (1.2.0 la fija la 009); sección propia en `## [1.2.0] — <fecha de publicación>` (E-4). | OK |

**Desviación de la 008, justificada**: FR-047 pedía `confirm` para
`POST /security/integrity`; el Supervisor 2026.11.0 la eliminó (410 Gone) y
queda `deny` (research R-6). **Lectura de la 008 aplicada**: `GET /host/disks`
va por la tabla como lectura menor de CAP-085 (research R-5).

**Tras el diseño**: sin cambios en la tabla de cumplimiento.

## Diseño

### Tramo 1 — logs del sistema (CAP-081)

- `tool_families.py`: familia `system_diagnostics` (1.2.0, desactivable) con
  el módulo `system_logs`; el tramo 2 añade `host_system` cuando lo crea (así
  `test_cada_familia_nombra_modulos_que_existen` pasa en cada tramo sin
  excepciones). Test propio en `tests/test_tool_families.py`, como el de
  `generic_commands`.
- `tools/system_logs.py`: `register(mcp, ha_client, *, response_max_bytes)`;
  validadores comunes (`_validar_boot`, `_validar_identifier`, combinación con
  `latest`), construcción de ruta según data-model, `sv_request_text` con
  `params={"lines": …}`, redacción, `_ultimas_lineas_que_caben` y
  `_es_hermes` importados de `tools/addons.py`, evento
  `system_diagnostics_read`. Seis tools.
- `tools/addons.py`: `sv_get_addon_logs` con `boot` y `latest` usando los
  mismos validadores (importados de `system_logs`, o en un módulo común
  `tools/_logs.py` si importar de `system_logs` crea un ciclo); camino por
  defecto intacto.
- Registro en `tools/__init__.py` dentro de la comprobación de familia de la
  011; anotaciones por prefijo (sin cambios) y `"os": "OS"` en el tramo 2.
- Tabla: 23 entradas de logs a `dedicated` (data-model), a mano; regenerar y
  comprobar que no cambia. `test_clase_a_de_via_dedicada_pendiente_de_su_spec`
  admite `dedicated`.
- Guía: tema `system_diagnostics` con las seis tools y alias; `supervisor`
  menciona `boot`/`latest`.
- Instantánea de esquemas de la 011: diferencia permitida en
  `sv_get_addon_logs`.

### Tramo 2 — disco, host y OS (CAP-085) y lo que va por la tabla

- `tools/host_system.py`: cinco tools; `sv_get_disk_usage` con validación de
  `disk`/`max_depth`, `params={"max_depth": …}`, `timeout_seconds=75` y poda;
  errores con pista en `/os/*` 404.
- `_annotations.py`: `"os": "OS"` en `_TITLE_WORDS` con un test de que ningún
  título de la 1.1.2 cambia.
- Tabla: 5 entradas a `dedicated`; `/jobs/info`,
  `/resolution/issue/{issue}/suggestions` y `/host/disks` a `read` con motivo y
  CAP; `_POR_LA_TABLA` en el test de la tabla con el porqué de las tres.
- Tests de las genéricas con las rutas de CAP-087 (lectura), CAP-088 y
  CAP-089 contra el simulado; `POST /security/integrity` sin llamada; log sin
  direcciones de red.
- Guía completa (tools de disco y OS, rutas por `sv_read_api`).
- Documentación: CHANGELOG, hoja de ruta (estado y pendiente en vivo),
  README/README.es, DOCS (familia), matriz de la 008.

## Estructura de ficheros

```text
hermes/src/hermes/
├── tool_families.py           # familia system_diagnostics (tramo 1)
├── command_table.py           # 23 dedicated (tramo 1); 5 dedicated + 3 read (tramo 2)
└── tools/
    ├── system_logs.py         # nuevo (tramo 1)
    ├── host_system.py         # nuevo (tramo 2)
    ├── addons.py              # sv_get_addon_logs: boot y latest (tramo 1)
    ├── __init__.py            # registro (tramos 1 y 2)
    ├── _annotations.py        # "os": "OS" (tramo 2)
    └── guide.py               # tema system_diagnostics (tramos 1 y 2)
tests/fixtures/supervisor_diagnostico.py      # respuestas simuladas (tramos 1 y 2)
tests/test_tools_system_logs.py               # tramo 1
tests/test_tools_host_system.py               # tramo 2
tests/test_tools_diagnostico_tabla.py         # genéricas con rutas de la 013 (tramo 2)
tests/test_command_table.py, test_tools_registration.py, test_tool_families.py,
      test_tools_guide.py, test_tools_supervisor.py, fixtures/esquemas_1_1_2.json   # ajustes
hermes/CHANGELOG.md, hermes/DOCS.md, README.md, README.es.md,
docs/HOJA-DE-RUTA.md, specs/008-cobertura-total/plan.md                         # documentación
```

## Trazabilidad (FR de la 013 → FR/CAP de la 008 → tarea → test)

| FR 013 | FR 008 | CAP | Tareas | Test |
|---|---|---|---|---|
| FR-001 | FR-044 | 081 | T003, T007 | `test_tools_system_logs.py` |
| FR-002 | FR-044 | 081 | T003, T007 | ídem |
| FR-003 | FR-044 | 081 | T003, T007 | ídem |
| FR-004 | FR-044 | 081 | T004, T007 | ídem |
| FR-005 | FR-044, FR-018 | 081 | T004, T007 | ídem |
| FR-006 | FR-044, FR-018 | 081 | T004, T007 | ídem |
| FR-007 | FR-044, FR-020 | 081 | T005, T008 | `test_tools_system_logs.py`, `test_tools_supervisor.py` |
| FR-008 | FR-044 | 081 | T003, T004, T007 | `test_tools_system_logs.py` (validación) |
| FR-009 | FR-044, FR-019 | 081, 010 | T004, T005, T007, T008 | ídem (redacción, recorte) |
| FR-010 | FR-019 | 081, 085 | T006, T007, T017 | ídem (log capturado) |
| FR-011 | FR-045 | 085 | T016, T019 | `test_tools_host_system.py` |
| FR-012 | FR-045 | 085 | T016, T019 | ídem (poda, validación, espera) |
| FR-013 | FR-045 | 085 | T016, T019 | ídem |
| FR-014 | FR-045 | 085 | T016, T019 | ídem |
| FR-015 | FR-045 | 085 | T016, T019 | ídem |
| FR-016 | FR-045 | 085 | T003, T017, T019 | ídem (errores y pistas) |
| FR-017 | FR-012, FR-044, FR-045 | 001, 081, 085 | T009, T010, T022 | `test_command_table.py` (dedicadas, regla de clase A) |
| FR-018 | FR-046 | 087, 085 | T018, T022, T023 | `test_command_table.py`, `test_tools_diagnostico_tabla.py` |
| FR-019 | FR-047 | 088 | T018, T023 | `test_tools_diagnostico_tabla.py` |
| FR-020 | FR-048 | 089 | T018, T023 | ídem (log sin direcciones) |
| FR-021 | FR-010, FR-018 | 004 | T002, T011, T019–T021, T024 | `test_tool_families.py`, `test_tools_registration.py` |
| FR-022 | FR-020 | 030 | T005, T011 | `test_tools_registration.py` (esquemas, hints) |
| FR-023 | FR-011, FR-018 | 008 | T012, T025 | `test_tools_guide.py` |
| FR-024 | FR-019 | 081 | T003–T005, T007 | `test_tools_system_logs.py` (centinelas) |
| FR-025 | FR-016, FR-021, FR-023, FR-024 | — | T014, T026 | revisión del diff (documental) |

## Tramos

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado. Los IDs están en [tasks.md](tasks.md).

| Tramo | Contenido | Tareas |
|---|---|---|
| 1 | Línea base, familia, seis tools de logs, `boot`/`latest` en `sv_get_addon_logs`, 23 entradas a `dedicated`, guía (logs), instantánea de esquemas, CHANGELOG y DOCS (parte), control negativo | T001–T015 |
| 2 | Cinco tools de disco, host y OS, título `OS`, 5 `dedicated` + 3 `read`, tests de las genéricas (jobs, sugerencias, hardware, seguridad, Docker, hora, red, integridad), guía completa, documentación y matriz, control negativo | T016–T028 |

## Pruebas en vivo (pendiente declarado)

En el banco de la 010 el Supervisor es simulado y solo reenvía a Core: ninguna
tool `sv_*` de esta sub-feature se puede ejecutar ahí. Se prueban con
unitarios contra un Supervisor simulado. La prueba contra un Supervisor real
(los pasos de [quickstart.md](quickstart.md)) queda **pendiente para la 014 o
para el cierre del programa**, con su casilla en la matriz tool → entorno de
`docs/HOJA-DE-RUTA.md` (FR-016 y SC-011 de la 008). Como ninguna modifica,
tampoco entran en el inventario «ninguna tool que modifica sin probar en el
banco».

## Dependencias

- **009** integrada: `redact_secrets` lineal (CAP-010), necesaria con logs de
  1000 líneas.
- **011** completa (tramos 1–3): tabla y política (ya en la rama), genéricas
  `sv_read_api`/`sv_call_api` (tramo 2 de la 011, para T023), registro por
  familias, opción `tool_families_disabled`, instantánea
  `esquemas_1_1_2.json` y tema `generic_commands` de la guía (tramo 3 de la
  011). Al escribir esta spec, la rama tiene solo el tramo 1 de la 011: la
  implementación empieza cuando la 011 esté entera en la rama (S-01).

## Riesgos

- **Forma real distinta de la simulada**: las respuestas simuladas salen del
  código del Supervisor 2026.11.0; la prueba en vivo pendiente lo cierra.
- **Choque con otras sub-features** en `tools/__init__.py`, `_annotations.py`,
  `guide.py`, `tool_families.py`, `command_table.py`, `tests/test_command_table.py`
  y el CHANGELOG (la 012 y la 029 van en la misma ola): cambios por líneas
  separadas y una sección propia del CHANGELOG; la regla del test de la tabla
  se amplía de forma que otras sub-features solo añadan claves.
- **Supervisor sin journal**: su propio log cae al del contenedor sin `boot` ni
  `latest`; Hermes no lo puede detectar y lo dice la descripción.
- **Árbol de disco enorme**: poda a 20 hijos por nivel y profundidad máxima 3.
