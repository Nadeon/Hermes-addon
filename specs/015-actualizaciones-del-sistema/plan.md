# Plan de implementación: actualizaciones del sistema (015)

**Rama**: `feat/015-actualizaciones-del-sistema` (sale de la de la 011; se integra en `feat/cobertura-total`) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md) | **Paraguas**: [008](../008-cobertura-total/plan.md)

## Resumen

Ocho tools nuevas en una familia nueva, `system_updates`. Cinco del
Supervisor (CAP-080): listar lo que tiene actualización (Core, OS, Supervisor,
apps y plugins), buscar actualizaciones, y actualizar Core, OS y Supervisor
con una vista previa que no miente: versión de origen y de destino (atada al
token), notas (las que HA tiene en local, que para Core y Supervisor son
ninguna, y lo dice), backup (el parcial de Core del Supervisor; ninguno en OS y
Supervisor, y lo dice), qué se reinicia y cuándo se aplica, salud del sistema,
comprobación de la configuración de Core y los bloqueos que harían fallar la
actualización (sin token si hay alguno). La ejecución devuelve el job. Tres de
Core (CAP-064): listar las entidades `update`, leer sus notas e instalarlas
con vista previa; las de Core, OS, Supervisor y apps se encaminan a sus `sv_*`.
Ocho entradas de la tabla pasan a `dedicated`. `ha_call_service` sobre
`update.install` solo gana una pista. Tres tramos. Las `sv_*` se prueban con un
Supervisor simulado (prueba real pendiente en la VM de la 014); las `ha_*`, en
el banco de Core con una entidad `update` de plantilla.

Detalle y alternativas en [research.md](research.md); entidades y tabla en
[data-model.md](data-model.md); firmas, anotaciones y errores en
[contracts/tools.md](contracts/tools.md); validación en
[quickstart.md](quickstart.md).

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x, aiohttp, structlog, `packaging` (ya en `requirements.txt`; comparar versiones) — ninguna nueva · **Almacenamiento**: el de los tokens (`security.py`) y `pending_jobs.json` (`_track_job`) · **Tests**: pytest, `unittest.IsolatedAsyncioTestCase`, `DummyMCP`, un Supervisor simulado (el `MockHAClient` de `tests/test_tools_supervisor.py` ampliado: responde por método y ruta, registra cuerpo y espera, simula lentitud, 404 y corte), `structlog.testing.capture_logs`; banco de Core de la 010 (HA Core 2026.11.1 real) con `template:` · **Plataforma**: add-on de Home Assistant OS.

**Restricciones**: confirmación en dos pasos con el token atado a las versiones (IV); fail-closed: sin token ante un bloqueo, un argumento inválido o una entidad encaminada (III); vista previa que no anuncia lo que no ocurre (notas inexistentes, backup que no se hace) (IV, V); nada sale a internet desde Hermes (R-4); secretos tapados en notas y errores (II); las 216 tools de la 1.1.2 sin cambios de esquema ni anotaciones (FR-020 de la 008); la tienda (030), los plugins (022) y el backup de la integración (031) no se tocan.

**Escala**: 8 tools en 2 módulos nuevos (`tools/system_updates.py`, `tools/update_entities.py`); cambios en `tool_families.py`, `command_table.py` (8 líneas), `tools/__init__.py`, `tools/_annotations.py`, `tools/guide.py`, `tools/ha.py` (una `hint`), `tests/banco/ha_config/configuration.yaml`; 3 ficheros de test nuevos, una fixture del Supervisor simulado, un test del banco y su inventario de cobertura; ajustes en `tests/test_command_table.py`, `tests/test_tools_registration.py`, `tests/test_tool_families.py`, `tests/test_tools_guide.py` y `tests/test_call_service_security.py` (la `hint`); las anotaciones se prueban en `tests/test_tools_registration.py`.

## Comprobación de la constitución

Contra la constitución 1.2.0 (con las enmiendas E-1…E-4 de la 011).

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Actualizar es de lo más delicado: dedicadas con vista previa semántica (FR-003…FR-009, FR-013); bloqueos leídos antes de emitir token (FR-004); encaminamiento para que no haya dos caminos (FR-014); las rutas siguen fuera de las genéricas (`dedicated`, FR-016). | OK |
| II. Secretos | Notas, errores del Supervisor y de Core y detalle de `/core/check` con `redact_secrets`; JSON con `redact_structure`; log sin contenido ni `version` inválido; centinelas (FR-018, SC-005). | OK |
| III. Fail-closed | `version`/`entity_id` validados antes de llamar; bloqueos, versiones ilegibles, `not_haos`, `already_installed`, validaciones de `update.install` y entidades encaminadas → sin token (FR-004, FR-010, FR-013, FR-014, SC-003). | OK |
| IV. Dos pasos, token atado | Las cuatro que modifican con consecuencias piden token; el token se ata además a `from_version`/`to_version` resueltas y la ejecución envía la versión explícita (FR-008, SC-004). La vista previa dice que no hay notas o backup cuando no los hay (R-4, R-5). `sv_check_for_updates` no pide token: no borra, no interrumpe, no toca secretos (FR-002). | OK |
| V. Nombre y descripción | Anotaciones por nombre exacto donde el prefijo mentiría (`sv_update_*` y `ha_install_update` destructivas y de mundo abierto; `ha_get_update_release_notes` de mundo abierto; `sv_check_for_updates` no de solo lectura) (FR-017); descripciones con el orden, los bloqueos y el encaminamiento; la tabla gana `dedicated`, sin `read` nuevos. | OK |
| VI. Lo que no se puede probar | `ha_install_update` en el banco con HA Core real (FR-021, SC-006); las `sv_*` con el Supervisor simulado y **prueba real pendiente** en la VM de la 014 con casilla en la hoja de ruta (SC-009), como manda FR-016 de la 008. | OK con pendiente declarado |
| VII. Control negativo | Cada tramo cierra con su lista de controles y recuentos (T015, T028, T045). | OK |
| VIII. Privacidad | Fixtures con versiones y slugs ficticios (`<slug>`, `a0b1c2d3_ejemplo`), `light.salon`, nada de la instalación real; revisión del diff por tramo. | OK |
| IX. Cambios mínimos | Las tools existentes no cambian salvo una `hint` en la vista previa de `ha_call_service`; `_track_job`, `_es_hermes` y `job_errors` se reutilizan; `sv_update_addon` no se toca (030). | OK |
| X. Comentarios en español | Comentarios con el porqué; descripciones, errores y eventos en inglés. | OK |
| XI. Versionado | Sin subida de versión; sección propia en `## [1.2.0] — <fecha de publicación>` (E-4). | OK |

**Desviaciones de la 008, justificadas**: FR-049 pide «notas de la versión
recortadas» para Core, OS y Supervisor; HA no las tiene en local (R-4) y la
vista previa lo dice con la `release_url`. Se añade una tool que la 008 no
estimaba, `ha_list_updates` (R-9). `POST /refresh_updates` (clase B en el
inventario) pasa a `dedicated` porque es la ruta que usa la tool (R-2).

**Tras el diseño**: sin cambios en la tabla de cumplimiento.

## Diseño

### Común (tramo 1, en `tools/system_updates.py`)

- `_VERSION_RE = ^[0-9][0-9A-Za-z.]{0,31}$` y `_validar_version`.
- `_leer(ruta)`: `sv_request("GET", …)` que devuelve `(datos, None)` o
  `(None, motivo)` para que una lectura que falla quede como `unavailable` y
  no como dato vacío.
- `_salud()`: `/resolution/info` → `system_health`.
- `_plugins()`: `/{dns,audio,cli,observer,multicast}/info` → versión,
  `version_latest`, `update_available`.
- `_bloqueos(componente, …)`: los códigos de data-model; pura, con los datos ya
  leídos, para probarla sin simulador.
- `_notas_de_entidad(unique_id)`: si Core responde, `get_entries` del registro
  no sirve sin `entity_id`; se buscan los estados `update.*` y, con
  `config/entity_registry/get_entries`, el de plataforma `hassio` y ese
  `unique_id`; devuelve `release_url` y, para el OS, el aviso de reinicio por
  `update/release_notes`. Si Core no responde, `null` con el motivo. (Se
  comparte con `update_entities` en el tramo 3 como función de módulo.)
- `_comparar(a, b)`: `packaging.version.Version` con `InvalidVersion` →
  `None`.
- `_args_atados(args, origen, destino)`: `{**args, "_from_version": origen,
  "_to_version": destino}`.
- `_respuesta_token_invalido(error)`: el error de `security.py` más
  `preview_outdated: true` y la `hint`.

### Tramo 1 — listar, buscar y actualizar Core

- `tool_families.py`: familia `system_updates` (1.2.0, desactivable) con el
  módulo `system_updates`; el tramo 3 añade `update_entities`.
- `sv_list_available_updates`, `sv_check_for_updates` (con `timeout_seconds=120`
  en el `POST /refresh_updates`) y `sv_update_core` (vista previa con
  `POST /core/check` y `timeout_seconds=120`, sin `record_check_config_ok`;
  ejecución con `background: true` y `_track_job` importado de `tools/addons.py`).
- `_annotations.py`: `sv_update_core` en `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD`;
  `sv_check_for_updates` en `_OPEN_WORLD`.
- Tabla: `GET /available_updates`, `POST /refresh_updates`,
  `POST /reload_updates`, `POST /core/update` y `hassio/update/core` a
  `dedicated` a mano; regenerar y comprobar que no cambia. Si la 013 no está
  integrada, `test_clase_a_de_via_dedicada_pendiente_de_su_spec` admite
  `dedicated` (el mismo cambio que trae la 013).
- Guía: tema `updates` (listado, búsqueda, Core).
- CHANGELOG: sección «Actualizaciones del sistema» dentro de `### Supervisor`
  (parte).

### Tramo 2 — OS y Supervisor

- `_lanzar_en_segundo_plano(ruta, cuerpo, nombre_job)`: crea la tarea con
  `sv_request(…, timeout_seconds=1800)`, guarda su referencia en un conjunto
  del módulo (y la quita al terminar), registra `system_update_finished` o
  `system_update_failed`; busca el job en `/jobs/info` (cada 1 s, 10 s como
  mucho; el reloj y la espera inyectables para el test).
- `sv_update_os`, `sv_update_supervisor`.
- `_annotations.py`: las dos en `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD`; `"os":
  "OS"` si la 013 no lo trajo.
- Tabla: `POST /os/update` y `POST /supervisor/update` a `dedicated`.
- Guía: OS y Supervisor, orden recomendado, qué hacer tras el reinicio del
  Supervisor.

### Tramo 3 — entidades `update`, banco y cierre

- `tools/update_entities.py`: `ha_list_updates`, `ha_get_update_release_notes`
  (`ws_send({"type": "update/release_notes", "entity_id": …})`), y
  `ha_install_update` (validaciones de `update.install`, encaminamiento por
  registro, vista previa, `call_service("update", "install", …,
  allow_dangerous=True)` tras validar su token, `TimeoutError` →
  `status: running`).
- `tool_families.py`: `update_entities` en `system_updates`.
- `_annotations.py`: `ha_install_update` en `_DESTRUCTIVE_EXACT` y
  `_OPEN_WORLD`; `ha_get_update_release_notes` en `_OPEN_WORLD`.
- `tools/ha.py`: en la vista previa de `ha_call_service`, si
  `domain == "update"` y `service == "install"`, `hint` con
  `ha_install_update`.
- Tabla: `update/release_notes` a `dedicated`.
- Banco: `template:` con una entidad `update` en
  `tests/banco/ha_config/configuration.yaml` (comentada), un `input_text` y un
  `input_boolean` de apoyo; `tests/banco/test_banco_actualizaciones.py`;
  `tests/banco/cobertura_015.py` (`PROBADAS_015 = {"ha_install_update"}`,
  `NO_EJECUTABLES_015` con las cuatro `sv_*` que modifican y su motivo) sumado
  al invariante de escrituras que haya en la rama (el de la 010/028) o con su
  propio test.
- Guía completa; documentación final y matriz de la 008.

## Estructura de ficheros

```text
hermes/src/hermes/
├── tool_families.py           # familia system_updates (tramo 1), update_entities (tramo 3)
├── command_table.py           # 5 dedicated (t1), 2 (t2), 1 (t3)
└── tools/
    ├── system_updates.py      # nuevo (tramos 1 y 2)
    ├── update_entities.py     # nuevo (tramo 3)
    ├── __init__.py            # registro (tramos 1 y 3)
    ├── _annotations.py        # exactas (tramos 1, 2 y 3); "os": "OS" si falta (tramo 2)
    ├── ha.py                  # hint en ha_call_service (tramo 3)
    └── guide.py               # tema updates (tramos 1–3)
tests/fixtures/supervisor_actualizaciones.py      # Supervisor simulado (tramos 1 y 2)
tests/test_tools_system_updates.py                # tramos 1 y 2
tests/test_tools_update_entities.py               # tramo 3
tests/banco/ha_config/configuration.yaml          # template: update (tramo 3)
tests/banco/test_banco_actualizaciones.py         # tramo 3
tests/banco/cobertura_015.py (+ su test si hace falta)   # tramo 3
tests/test_command_table.py, test_tools_registration.py, test_tool_families.py,
      test_tools_guide.py, test_call_service_security.py (hint)               # ajustes
hermes/CHANGELOG.md, hermes/DOCS.md, README.md, README.es.md,
docs/HOJA-DE-RUTA.md, specs/008-cobertura-total/plan.md                    # documentación
```

## Trazabilidad (FR de la 015 → FR/CAP de la 008 → tarea → test)

| FR 015 | FR 008 | CAP | Tareas | Test |
|---|---|---|---|---|
| FR-001 | FR-049, FR-018 | 080 | T004, T007 | `test_tools_system_updates.py` (`TestListar`) |
| FR-002 | FR-049 | 080 | T004, T007 | ídem (`TestBuscar`) |
| FR-003 | FR-049 | 080 | T005, T008, T018, T020 | ídem (`TestVistaPreviaCore`, `…Os`, `…Supervisor`) |
| FR-004 | FR-049 | 080 | T003, T005, T008, T018 | ídem (`TestBloqueos`) |
| FR-005 | FR-049 | 080 | T005, T008 | ídem (`TestUpdateCore`) |
| FR-006 | FR-049 | 080 | T018, T020 | ídem (`TestUpdateOs`) |
| FR-007 | FR-049 | 080 | T018, T020 | ídem (`TestUpdateSupervisor`) |
| FR-008 | FR-049 | 080 | T006, T008, T019, T020, T034 | ídem (`TestTokenAtado`), `test_tools_update_entities.py` |
| FR-009 | FR-049 | 080 | T019, T021 | ídem (`TestSegundoPlano`) |
| FR-010 | FR-049 | 080 | T003, T005, T007, T008 | ídem (`TestValidacion`) |
| FR-011 | FR-050, FR-018 | 064 | T031, T035 | `test_tools_update_entities.py` (`TestListarEntidades`) |
| FR-012 | FR-050 | 064 | T031, T035 | ídem (`TestNotas`) |
| FR-013 | FR-050 | 064 | T032, T034, T035, T041 | ídem (`TestInstalar`), banco |
| FR-014 | FR-050 | 064, 080 | T033, T035 | ídem (`TestEncaminar`) |
| FR-015 | FR-050, FR-020 | 064 | T037 | `test_call_service_security.py` (`TestHintUpdateInstall`) |
| FR-016 | FR-012, FR-049, FR-050 | 001 | T010, T011, T012, T022, T023, T027, T038, T039 | `test_command_table.py`, genéricas |
| FR-017 | FR-010, FR-018 | 004 | T002, T009, T024, T035, T036 | `test_tool_families.py`, `test_tools_registration.py`, anotaciones |
| FR-018 | FR-019 | 080, 064 | T006, T019, T034 | centinelas en los dos ficheros de test |
| FR-019 | FR-020 | 030 | T009, T037, T040 | `test_tools_registration.py` (esquemas 1.1.2) |
| FR-020 | FR-011, FR-018 | 008 | T013, T025, T042 | `test_tools_guide.py` |
| FR-021 | FR-015, FR-016 | 034 | T041, T043 | `tests/banco/test_banco_actualizaciones.py`, `cobertura_015.py` |
| FR-022 | FR-016, FR-021, FR-023, FR-024 | — | T014, T026, T044 | revisión del diff (documental) |

## Tramos

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado. La 008 estimaba 2 tramos; son 3 porque la vista previa de Core
(bloqueos, comprobación de configuración, token atado) y la ejecución en
segundo plano del OS y del Supervisor no caben con las entidades `update` y el
banco en dos agentes. Los IDs están en [tasks.md](tasks.md).

| Tramo | Contenido | Tareas |
|---|---|---|
| 1 | Línea base, familia, Supervisor simulado, comunes, `sv_list_available_updates`, `sv_check_for_updates`, `sv_update_core`, 5 entradas a `dedicated`, guía (parte), CHANGELOG (parte), control negativo | T001–T016 |
| 2 | `sv_update_os`, `sv_update_supervisor`, ejecución en segundo plano y búsqueda del job, 2 entradas a `dedicated`, título `OS`, guía, CHANGELOG, control negativo | T017–T029 |
| 3 | `ha_list_updates`, `ha_get_update_release_notes`, `ha_install_update` con encaminamiento, `hint` de `ha_call_service`, 1 entrada a `dedicated`, banco con entidad de plantilla e inventario de cobertura, guía completa, documentación y matriz, control negativo | T030–T046 |

## Pruebas: qué se prueba dónde

| Entorno | Qué |
|---|---|
| Unitarios con Supervisor simulado | Las 5 `sv_*`: vistas previas, bloqueos, token atado, peticiones exactas, segundo plano, búsqueda del job, cortes, redacción |
| Unitarios con Core simulado | Las 3 `ha_*`: validaciones, encaminamiento por registro, notas, espera vencida, redacción |
| Banco de Core (HA Core 2026.11.1 real) | `ha_install_update` (vista previa sin efecto, confirmación, `version`, `backup`), `ha_list_updates`, `ha_get_update_release_notes` (sin notas), con el lector independiente |
| VM con HAOS (014, manual) | Las 4 `sv_*` que modifican y `sv_check_for_updates` contra un Supervisor real (quickstart.md, paso 3) |

## Dependencias

- **009**: rechazo de `sv_update_addon` sobre Hermes (`self_update_not_supported`)
  y `## [1.2.0]` del CHANGELOG.
- **010**: banco de Core, su lector y su inventario de cobertura con el plugin
  que exige la ejecución (`tests/banco/obligatorio.py`).
- **011** completa: tabla y política, genéricas (para comprobar el rechazo
  `use_dedicated_tool`), registro por familias, `tool_families_disabled`,
  instantánea `esquemas_1_1_2.json`.
- **013** (la 008 la pone como dependencia): `"os": "OS"`, `/jobs/info` y la
  regla del test de la tabla que admite `dedicated`. Si no está integrada, la
  015 hace los dos cambios mínimos y lo anota (S-01).
- Al especificar, la rama solo tiene la 011: el tramo 1 empieza integrando lo
  que falta desde `feat/cobertura-total` (T001).

## Riesgos

- **Forma real distinta de la simulada**: las respuestas salen del código del
  Supervisor 2026.11.0; la prueba manual en la VM lo cierra.
- **Tarea de fondo que se pierde** si Hermes se reinicia durante una
  actualización del OS o del Supervisor: el Supervisor la protege con `shield`
  y sigue; Hermes solo pierde el log del final. Dicho en la respuesta
  (`verify_with`).
- **Comprobación de configuración lenta** (decenas de segundos) en la vista
  previa: espera de 120 s y bloqueo si vence; el TTL del token empieza después.
- **Choques de fusión** con la 013, 019, 022 y 030 en `tools/__init__.py`,
  `_annotations.py`, `guide.py`, `tool_families.py`, `command_table.py`,
  `tests/test_command_table.py`, la configuración del banco (`template:` lo
  puede añadir también la 028) y el CHANGELOG: cambios por líneas separadas y
  sección propia.
- **`ha_install_update` tras la espera**: la instalación sigue en Core; la
  respuesta lo dice y no se reintenta sola.
