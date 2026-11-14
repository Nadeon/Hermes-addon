---

description: "Tareas de Hermes 1.0.12, agrupadas en lotes paralelos"
---

# Tareas: Hermes 1.0.12 — correcciones frente a HA 2026.11

**Entrada**: `specs/001-correcciones-1-0-12/` (spec.md, plan.md, research.md, data-model.md, contracts/tools.md, quickstart.md).

**Tests**: obligatorios. La constitución (principios VI y VII) exige un test de regresión por arreglo, escrito **antes** de la implementación, y un **control negativo**: deshacer el arreglo, ver caer el test y dejar el recuento por escrito.

**Organización**: por **lotes** que pueden implementar agentes distintos, cada uno en su worktree, sin tocar los mismos ficheros. Dentro de cada lote, las tareas llevan la etiqueta de la historia de usuario de spec.md (US1…US8) y el ID de la revisión (P1, R1…).

## Formato: `[ID] [P?] [Historia] Descripción`

- **[P]**: se puede hacer en paralelo con otras tareas del mismo lote (ficheros distintos, sin dependencias pendientes). Las tareas de test que comparten fichero con otra [P] anterior del lote no llevan la marca: se escriben en orden.
- **[USn]**: historia de usuario de spec.md.
- Rutas relativas a la raíz del repositorio.

## Reparto de ficheros por lote

Ningún fichero aparece en dos lotes. Si un lote necesita cambiar un fichero
que no es suyo, **no lo toca**: lo anota en su informe para el lote de
integración.

| Lote | Ficheros que le pertenecen (código y tests) |
|---|---|
| **Fase 0 — Fundación** (secuencial, antes de abrir los lotes) | `hermes/src/hermes/ha.py` (solo `HAConnectionError` y `_handle_ws_message`), `hermes/src/hermes/ha_version.py` (nuevo), `tests/test_ha_ws_error_code.py` (nuevo), `tests/test_ha_version.py` (nuevo), `tests/_ha_fixture.py` (solo si hiciera falta para los fakes; ningún otro lote lo edita) |
| **A — Supervisor, jobs y safety backup** | `hermes/src/hermes/fs_write.py`, `hermes/src/hermes/tools/backups.py`, `hermes/src/hermes/tools/supervisor.py`, `hermes/src/hermes/tools/addons.py`, `tests/test_fs_write_security.py`, `tests/test_tools_supervisor.py` |
| **B — Registros de entidades y dispositivos** | `hermes/src/hermes/tools/registry_entity.py`, `hermes/src/hermes/tools/registry_device.py`, `hermes/src/hermes/tools/registry_area.py`, `hermes/src/hermes/tools/config_entries.py`, `tests/test_tools_registry_entity.py`, `tests/test_tools_registry_device.py`, `tests/test_tools_registry_area.py`, `tests/test_tools_config_entries.py` |
| **C — Lovelace** | `hermes/src/hermes/tools/lovelace.py`, `tests/test_tools_lovelace.py` |
| **D — Automatizaciones, scripts, plantillas, errores WS, servicios, estadísticas y HACS** | `hermes/src/hermes/ha.py` (tras la fase 0: `ws_collection_delete` y `ws_one_shot_subscription`), `hermes/src/hermes/models/script.py`, `hermes/src/hermes/tools/templates.py`, `hermes/src/hermes/tools/ha.py`, `hermes/src/hermes/tools/statistics.py`, `hermes/src/hermes/tools/hacs.py`, `tests/test_tools_templates.py`, `tests/test_tools_counter.py`, `tests/test_tools_scripts.py`, `tests/test_tools_ha_services.py` (nuevo), `tests/test_tools_statistics.py`, `tests/test_tools_hacs.py` (nuevo), `tests/test_security_regressions.py` |
| **Integración** (al final, tras fusionar A–D) | `hermes/src/hermes/config.py`, `hermes/src/hermes/__init__.py`, `hermes/config.yaml`, `hermes/CHANGELOG.md`, `hermes/src/hermes/tools/guide.py`, `README.md`, `README.es.md`, `hermes/DOCS.md`, `docs/HOJA-DE-RUTA.md`, `tests/test_addon_manifest.py`, `tests/test_tools_guide.py` |

Notas de reparto:

- `hermes/src/hermes/ha.py` lo tocan la fase 0 y el lote D, pero **no a la vez**: la fase 0 se fusiona antes de abrir los lotes.
- `effective_area_id()` vive en `tools/registry_device.py` y lo importan `registry_entity.py` y `registry_area.py`: los tres son del lote B.
- `_job_errors()` vive en `tools/backups.py` y lo importa `fs_write.py`: ambos del lote A.
- `tools/_annotations.py`, `tools/_common.py`, `tools/filesystem_write.py`, `tests/test_tools_registration.py`, `.github/`, `hermes/Dockerfile` y `hermes/build.yaml` **no los toca nadie** en esta spec (los tres últimos son de la spec 002).
- Los fakes de WS de cada test simulan el código de error construyendo `HAConnectionError("…", code="not_found")` en el propio fichero de test, sin editar `tests/_ha_fixture.py`.

---

## Fase 1: Preparación

**Objetivo**: entorno de pruebas y línea base.

- [ ] T001 Crear el entorno `.venv` con `hermes/requirements.txt` y `pytest pytest-asyncio aioresponses httpx` según `CONTRIBUTING.es.md:71-73`, y ejecutar `.venv/bin/pytest`; anotar el número de tests que pasan como línea base en el informe del supervisor
- [ ] T002 Comprobar que el árbol de trabajo está limpio y en la rama indicada por el mantenedor; cada lote crea su worktree desde el commit con la fase 0 fusionada

---

## Fase 2: Fundación (fase 0, secuencial — BLOQUEA a todos los lotes)

**Objetivo**: que los errores WS conserven su código (FR-030, base de D1/C6/R3/P3) y que las tools puedan leer la versión de HA (base de P2, C8, R3).

- [X] T003 [P] Test de regresión en `tests/test_ha_ws_error_code.py`: un mensaje `{"type":"result","success":false,"error":{"code":"not_found","message":"Unable to find counter_id x"}}` procesado por `HAClient._handle_ws_message` debe resolver el future con un `HAConnectionError` cuyo `code == "not_found"`; sin `code` o con `error` no dict, `code is None`; el texto del mensaje no cambia (FR-030, D1)
- [X] T004 [P] Test en `tests/test_ha_version.py` para `ha_core_version` y `ha_at_least`: `"2026.11.1"`, `"2026.12.0.dev0"` (compara como 2026.12.0), `"landingpage"` → `None`, `HAConnectionError` → `None`, respuesta no dict → `None`; `ha_at_least(…, "2026.9.0")` devuelve `True`/`False`/`None`
- [X] T005 Añadir `code: str | None = None` a `HAConnectionError.__init__` en `hermes/src/hermes/ha.py:34-44` y propagar `error.get("code")` (solo si es `str`) en `_handle_ws_message`, `hermes/src/hermes/ha.py:526-536`, con comentario del porqué (D1)
- [X] T006 Crear `hermes/src/hermes/ha_version.py` con `ha_core_version(ha_client)` (WS `get_config`, `timeout_seconds=5`, `packaging.version.Version(...).base_version`) y `ha_at_least(ha_client, minimo)`, sin caché (research R-0.2, spec S-03)
- [X] T007 Control negativo de la fase 0: deshacer T005 y comprobar que cae T003; deshacer T006 (stub que devuelve `None` siempre) y comprobar que cae T004; restaurar y anotar «con la guarda quitada caen N tests»
- [X] T008 Ejecutar la suite completa; grep de privacidad del diff (quickstart.md); commit de la fase 0

**Punto de control**: fase 0 fusionada; se abren los lotes A, B, C y D en paralelo.

---

## Fase 3: Lote A — Supervisor, jobs y safety backup (US1, US7)

**Objetivo**: el safety backup automático funciona y no encadena backups; los jobs fallidos se ven como fallidos; los campos del Supervisor y del host llegan rellenos.

**Prueba independiente**: `.venv/bin/pytest tests/test_fs_write_security.py tests/test_tools_supervisor.py`.

### R2 — estado de jobs (US1)

- [X] T009 [P] [US1] Tests de regresión en `tests/test_tools_supervisor.py`: `sv_get_job_status` con `GET /jobs/{id}` → `{"done": true, "errors": [{"type": "BackupError", "message": "Not enough free space", "stage": null}]}` devuelve `success: false` y `errors: ["Not enough free space"]`; `done` sin errores → `success: true`; no terminado → `success: null`; `pending_jobs.json` queda con `status: "failed"`; `sv_list_pending_jobs` lo muestra `failed`; un `errors` con objetos sin `message` da `"unknown error"` (FR-006, FR-007)
- [X] T010 [US1] Añadir `_job_errors(data) -> list[str]` en `hermes/src/hermes/tools/backups.py` (solo `message` si es `str`, si no `"unknown error"`; recorte a 500 caracteres; `redact_secrets` de `hermes/src/hermes/security.py:377`) (research R-A3)
- [X] T011 [US1] En `sv_get_job_status`, `hermes/src/hermes/tools/backups.py:628-672`: añadir `errors` y `success`; en `:661-667` marcar `status = "failed"` si hay errores; actualizar docstrings de `sv_get_job_status` (`:630-643`) y `sv_list_pending_jobs` (`:674-690`) (FR-006, FR-007)
- [X] T012 [US1] Control negativo R2: deshacer T011 y comprobar que caen los tests de T009; restaurar y anotar el recuento

### R1 — safety backup automático (US1)

- [X] T013 [P] [US1] Tests de regresión en `tests/test_fs_write_security.py` (clase del safety backup, cerca de `:830-900`), con el Supervisor simulado devolviendo `{"job_id": "<uuid>"}` y `asyncio.sleep` parcheado: (a) sondea `/jobs/<uuid>` y nunca `/jobs/<uuid>/info`; (b) `done` y `errors` vacío → `None` y `last_safety_backup_at` actualizado; (c) `done` con errores → `safety_backup_job_failed` con el mensaje, sin actualizar la marca; (d) plazo agotado → error con el `job_id` y `pending_job_id`/`pending_started_at` guardados; (e) llamada siguiente con pendiente en curso → `safety_backup_in_progress` y **un solo** `POST /backups/new/full` en total; (f) pendiente terminado bien → `None` sin nuevo POST; (g) pendiente con errores o 404 → error, claves pendientes borradas y sin nuevo POST en esa llamada; (h) límite duro de 60 s medido también desde `pending_started_at`; (i) un 404 durante el sondeo termina con `safety_backup_state_unknown` y borra las claves pendientes. El test síncrono existente sin `job_id` se conserva (FR-001…FR-005)
- [X] T014 [US1] En `_save_safety_state`, `hermes/src/hermes/tools/backups.py:91-102`, hacer que un valor `None` borre la clave, para limpiar las claves pendientes (data-model.md)
- [X] T015 [US1] Reescribir el sondeo y la anotación de `maybe_trigger_safety_backup` en `hermes/src/hermes/fs_write.py:663-792` según plan.md (Lote A): resolver primero el pendiente; guardar `pending_job_id`, `pending_started_at` y `pending_backup_name` al recibir el `job_id`; sondear `/jobs/{job_id}` (`:767`); éxito = `done is True` y `errors` vacío (`:775-787`); errores con `_job_errors`; timeout (`:792`) con `job_id` y `poll_with: "sv_get_job_status"`; comentarios del porqué (FR-001…FR-005, spec S-01)
- [X] T016 [US1] Control negativo R1: restaurar por separado la ruta `/info`, el parseo de `state`/`error` y la anotación pendiente, ejecutar T013 cada vez y anotar cuántos tests caen con cada guarda quitada

### D4 y C3 — información del sistema y docstrings (US7)

- [X] T017 [US7] Tests de regresión en `tests/test_tools_supervisor.py`: `sv_get_supervisor_info` con `GET /info` → `{"machine": "generic-x86-64", "docker": "28.0.0"}` rellena `machine` y `docker_version`; `GET /info` con error → ambos `None` y el resto presente; `sv_get_host_info` con `kernel` rellena `kernel_version`; además, la descripción de `sv_get_host_info` menciona microsegundos y GiB, la de `sv_get_addon_stats` nombra `blk_read`/`blk_write` y no `disk_read`, y la de `sv_list_backups` explica que `location: null` es local (FR-008…FR-010)
- [X] T018 [US7] En `hermes/src/hermes/tools/supervisor.py:46-69`, leer `GET /info` en su propio `try` (con `redact_structure`) para `machine` y `docker_version`; en `:72-100`, `kernel_version` desde `kernel` y docstring `:76-79` con `boot_timestamp` en µs y `disk_*` en GiB (FR-008, FR-009)
- [X] T019 [US7] Corregir docstrings: `sv_get_addon_stats` en `hermes/src/hermes/tools/addons.py:912-929` (`blk_read`, `blk_write`, `cpu_usage`, `cpu_system_usage`, `online_cpus`, `memory_percent`) y `sv_list_backups` en `hermes/src/hermes/tools/backups.py:145-170` (`location: null` = local; `protected` de la primera ubicación) (FR-010, C3)
- [X] T020 [US7] Control negativo D4 y C3: deshacer T018 y luego T019 y comprobar que caen los tests de T017 correspondientes; restaurar y anotar el recuento

### Cierre del lote A

- [X] T021 Ejecutar `.venv/bin/pytest tests/test_fs_write_security.py tests/test_tools_supervisor.py` y la suite completa; grep de privacidad del diff; commit del lote con los recuentos de control negativo en el mensaje

**Punto de control**: US1 y US7 completas.

---

## Fase 4: Lote B — Registros de entidades y dispositivos (US2, US3)

**Objetivo**: alias sin corrupción, `not_found` veraz, borrado de dispositivos con nombre y preview veraces, dispositivos hijo en filtros y recuentos.

**Prueba independiente**: `.venv/bin/pytest tests/test_tools_registry_entity.py tests/test_tools_registry_device.py tests/test_tools_registry_area.py tests/test_tools_config_entries.py`.

### P1 + R6 + C1 — alias y nombre (US2)

- [X] T022 [P] [US2] Tests de regresión en `tests/test_tools_registry_entity.py`: `aliases: [null, "lámpara"]` llega a `config/entity_registry/update` como `[None, "lámpara"]`; `aliases: null` devuelve el error que nombra `[]` y `[null]` sin ninguna llamada WS; `aliases: [{"a": 1}]` se rechaza; `aliases: [3]` llega como `["3"]`; la descripción de `ha_update_entity_registry` ya no dice «null = limpiar», explica el `null` dentro de la lista y avisa de que `name` es solo la parte de la entidad desde HA 2026.11 (FR-011…FR-014)
- [X] T023 [US2] En `_validate_updates`, `hermes/src/hermes/tools/registry_entity.py:74-77`, conservar `None`, rechazar `aliases: null` y elementos lista/dict; actualizar el docstring de `ha_update_entity_registry` (`:250` `name` solo parte de la entidad desde HA 2026.11; `:260` semántica de `null` y de sustitución) (FR-011…FR-014)
- [X] T024 [US2] Control negativo P1/R6/C1: deshacer el cambio de `:74-77` y luego el del docstring, y comprobar que caen los tests de T022 correspondientes; restaurar y anotar el recuento

### C6 — `not_found` del registro de entidades (US2)

- [X] T025 [US2] Test de regresión en `tests/test_tools_registry_entity.py`: `config/entity_registry/get` que lanza `HAConnectionError("HA WS command failed: Entity not found", code="not_found")` → `{"error": "not_found", "entity_id": …}`; otro código → el error como hasta ahora (FR-015)
- [X] T026 [US2] En `ha_get_entity_registry`, `hermes/src/hermes/tools/registry_entity.py:218-230`, decidir `not_found` por `exc.code` (FR-015)
- [X] T027 [US2] Control negativo C6: deshacer T026 y comprobar que cae T025; anotar

### P2 — `ha_remove_device` y tool antigua deprecada (US3)

- [X] T028 [P] [US3] Tests de regresión en `tests/test_tools_registry_device.py` (con `ha_at_least` parcheado): (a) HA 2026.11 → preview `action: "delete_device"`, `method: "config/device_registry/remove"`, `entities_count` correcto y warning que dice que borra el dispositivo; con token envía `{"type": "config/device_registry/remove", "device_id": …}`; (b) HA 2026.8 con una integración → `method: "config/device_registry/remove_config_entry"` con esa `config_entry_id`; (c) HA 2026.8 con dos integraciones → `multiple_config_entries` sin token; (d) versión desconocida → `ha_version_unknown` sin token; (e) dispositivo inexistente → `not_found`; (f) versión distinta entre preview y ejecución → `ha_version_changed` y token fallido; (g) `classify("ha_remove_device")` de `hermes/src/hermes/tools/_annotations.py` es destructiva; (h) token de `ha_remove_device` no vale para otro `device_id` (FR-016…FR-018)
- [X] T029 [US3] Tests de regresión en `tests/test_tools_registry_device.py` para `ha_remove_device_from_config_entry`: preview con `deprecated: true`, `replacement: "ha_remove_device"` y warning que menciona el borrado del dispositivo entero en HA ≥ 2026.9; docstring con «DEPRECATED» y «2027.9»; el envío sigue siendo `config/device_registry/remove_config_entry` (FR-019)
- [X] T030 [US3] Implementar `ha_remove_device` en `hermes/src/hermes/tools/registry_device.py` (tras `:370`) según plan.md y contracts/tools.md, usando `ha_at_least` de `hermes/src/hermes/ha_version.py` con umbral `"2026.9.0"`; comentario del porqué (cambio de semántica en HA 2026.9, retirada en 2027.9) (FR-016…FR-018, research R-B2)
- [X] T031 [US3] Reescribir docstring y preview de `ha_remove_device_from_config_entry` en `hermes/src/hermes/tools/registry_device.py:290-325` (deprecada, retirada antes de HA 2027.9, efecto real según versión); sin cambiar el envío de `:343-348` (FR-019)
- [X] T032 [US3] Control negativo P2: (1) cambiar el umbral de versión de T030 o forzar siempre `remove_config_entry` y comprobar que caen los tests de T028; (2) restaurar el preview antiguo de T031 y comprobar que caen los de T029; anotar los recuentos

### D3 — dispositivos hijo, área efectiva y `config_entry_id` (US3)

- [X] T033 [US3] Tests de regresión en `tests/test_tools_registry_device.py`: hijo con `area_id: null` y `parent_device_id` de un padre en `salon` aparece en `ha_list_devices(area_id="salon")`; cadena de dos niveles; ciclo padre↔hijo no cuelga ni coincide; filtro `manufacturer` sin cambios (FR-020, FR-024)
- [X] T034 [US3] Tests de regresión en `tests/test_tools_registry_entity.py`: `ha_list_entities_registry(area_id="salon")` incluye una entidad sin área propia de un dispositivo en `salon` y una de un hijo cuyo padre está en `salon`; excluye una entidad con área propia distinta (FR-021, spec S-14)
- [X] T035 [P] [US3] Test de regresión en `tests/test_tools_registry_area.py`: la preview de `ha_delete_area("salon")` cuenta el hijo sin área propia y sus entidades (FR-022)
- [X] T036 [P] [US3] Tests de regresión en `tests/test_tools_config_entries.py`: la preview de `ha_disable_config_entry` y `ha_delete_config_entry` cuenta un hijo que solo tiene `config_entry_id`, y no cuenta dos veces un dispositivo con `config_entry_id` y `config_entries` (FR-023)
- [X] T037 [US3] Añadir `effective_area_id(device, by_id, max_depth=8)` en `hermes/src/hermes/tools/registry_device.py` (cerca de `:35`) y usarlo en el filtro de `:121-122`; actualizar docstrings `:1-14` y `:95-110` (`config_entry_id`, `parent_device_id`, hijos sin fabricante, `config_entries` retirable en 2027.8) (FR-020, FR-024)
- [X] T038 [US3] Filtro por área efectiva en `ha_list_entities_registry`, `hermes/src/hermes/tools/registry_entity.py:160-170` (leer el registro de dispositivos solo si se pasa `area_id`), con docstring (FR-021)
- [X] T039 [US3] Área efectiva en `_count_area_dependents`, `hermes/src/hermes/tools/registry_area.py:56-100` (FR-022)
- [X] T040 [US3] Recuento por `config_entry_id` con respaldo `config_entries`, sin duplicados, en `_count_config_entry_dependents`, `hermes/src/hermes/tools/config_entries.py:64-72` (FR-023)
- [X] T041 [US3] Control negativo D3: deshacer T037, T038, T039 y T040 uno a uno y comprobar que caen respectivamente T033, T034, T035 y T036; anotar los recuentos

### Cierre del lote B

- [X] T042 Ejecutar los tests del lote y la suite completa; grep de privacidad del diff (los ejemplos de tests usan nombres genéricos como `salon`, `light.x`); commit del lote con los recuentos de control negativo

**Punto de control**: US2 y US3 completas.

---

## Fase 5: Lote C — Lovelace (US4)

**Objetivo**: el dashboard principal no se puede borrar; aparece una sola vez; recursos con el comando vigente.

**Prueba independiente**: `.venv/bin/pytest tests/test_tools_lovelace.py`.

### P3 — protección del dashboard principal (US4)

- [ ] T043 [US4] Comprobar en el código de Home Assistant (componente `frontend`, comandos `*_system_data`) la forma exacta de la respuesta de `frontend/get_system_data` con `key: "core"` y dónde va `default_panel`; dejarlo escrito como comentario en el test y, si difiere de research R-C1, actualizar research.md (spec S-04)
- [ ] T044 [P] [US4] Tests de regresión en `tests/test_tools_lovelace.py`: `ha_delete_lovelace_dashboard(url_path="lovelace")` → `cannot_delete_default_dashboard` sin `confirmation_token`, tanto sin token como con un token cualquiera; dashboard igual al `default_panel` → rechazado; `frontend/get_system_data` con error distinto de `unknown_command` o forma inesperada → `default_panel_unknown` para cualquier dashboard; con `unknown_command` → se puede borrar un dashboard extra que no sea `lovelace` (flujo de token normal); ninguna de las respuestas rechazadas contiene `confirmation_token`; las descripciones de las dos tools ya no dicen solo «el default no se puede borrar» y nombran `lovelace` y el panel por defecto (FR-025…FR-027)
- [ ] T045 [US4] Añadir `_default_panel(ha_client)` cerca de `hermes/src/hermes/tools/lovelace.py:130` y la guarda única al principio de `ha_delete_lovelace_dashboard`, `hermes/src/hermes/tools/lovelace.py:586-590`, antes de mirar el token y sin opción para saltársela; comentario del porqué (migración de HA 2026.2) (FR-025, FR-026)
- [ ] T046 [US4] Docstrings de `ha_list_lovelace_dashboards` (`hermes/src/hermes/tools/lovelace.py:159-170`) y `ha_delete_lovelace_dashboard` (`:577-585`): qué dashboards están protegidos y por qué (FR-027)
- [ ] T047 [US4] Control negativo P3: restaurar la guarda antigua (solo `url_path is None`) y después los docstrings antiguos, y comprobar que caen los tests de T044 correspondientes; anotar

### C2 — lista sin duplicado (US4)

- [ ] T048 [US4] Tests de regresión en `tests/test_tools_lovelace.py`: con un extra `url_path: "lovelace"`, la lista no tiene elemento con `url_path: null` y `lovelace` lleva `is_default: true`; sin `lovelace`, el sintético sigue (los tests existentes `:198-215` se conservan) (FR-028)
- [ ] T049 [US4] En `ha_list_lovelace_dashboards`, `hermes/src/hermes/tools/lovelace.py:172-186`, omitir el sintético si existe `lovelace` y marcarlo `is_default` (FR-028)
- [ ] T050 [US4] Control negativo C2: deshacer T049 y comprobar que cae T048; anotar

### `lovelace/resources/list` (US4)

- [ ] T051 [US4] Test de regresión en `tests/test_tools_lovelace.py`: `ha_list_lovelace_resources` envía `lovelace/resources/list` y nunca `lovelace/resources`; actualizar el fake de `:186` (FR-029)
- [ ] T052 [US4] Cambiar el comando en `hermes/src/hermes/tools/lovelace.py:685` (FR-029)
- [ ] T053 [US4] Control negativo: deshacer T052 y comprobar que cae T051; anotar

### Cierre del lote C

- [ ] T054 Ejecutar `tests/test_tools_lovelace.py` y la suite completa; grep de privacidad del diff; commit del lote con los recuentos

**Punto de control**: US4 completa.

---

## Fase 6: Lote D — Automatizaciones, scripts, plantillas, errores WS, servicios, estadísticas y HACS (US5, US6)

**Objetivo**: `trace` en scripts, `year` con versión, `not_found` por código, avisos de plantilla, timeout de HA, filtro de servicios, HACS con mensaje claro y `perform_action` documentado con verdad.

**Prueba independiente**: los ficheros de test del lote D (quickstart.md).

### R5 — `trace` en scripts (US5)

- [ ] T055 [P] [US5] Tests de regresión en `tests/test_tools_scripts.py`: `ha_create_or_update_script` con `{"sequence": [...], "trace": {"stored_traces": 20}}` pasa la validación y llega a HA con `trace` intacto; `trace` como lista → error de validación (FR-032)
- [ ] T056 [US5] `trace: dict[str, Any] | None = None` en `hermes/src/hermes/models/script.py:21` (FR-032)
- [ ] T057 [US5] Control negativo R5: deshacer T056 y comprobar que cae T055; anotar

### C8 — `period: "year"` según versión (US5)

- [ ] T058 [P] [US5] Tests de regresión en `tests/test_tools_statistics.py` (con `ha_at_least` parcheado): `year` con HA 2026.2 → `period_not_supported` sin llamada a `recorder/statistics_during_period`; con 2026.3 → se envía; con versión desconocida → se envía; la descripción de `ha_list_statistic_ids` nombra `mean_type` y `statistics_unit_of_measurement` y no promete `unit_of_measurement` (FR-036, FR-037)
- [ ] T059 [US5] Guarda de versión en `ha_statistics_during_period`, `hermes/src/hermes/tools/statistics.py:254-260`, con `ha_at_least(…, "2026.3.0")`; docstring de `ha_list_statistic_ids` (`:124-160`) con los campos reales y `has_mean` deprecado (FR-036, FR-037)
- [ ] T060 [US5] Control negativo C8 y C3: deshacer la guarda y luego el docstring de T059 y comprobar que caen los tests de T058 correspondientes; anotar

### D1 — `not_found` por código en el borrado de colecciones (US6)

- [ ] T061 [P] [US6] Test de regresión en `tests/test_tools_counter.py`: `ha_delete_counter("counter.no_existe")` con token, cuando `counter/delete` lanza `HAConnectionError("HA WS command failed: Unable to find counter_id no_existe", code="not_found")`, devuelve la respuesta `not_found`; un error con otro código se propaga como error (FR-031)
- [ ] T062 [US6] En `ws_collection_delete`, `hermes/src/hermes/ha.py:858-875`, decidir por `exc.code == "not_found"` y quitar la búsqueda por texto (FR-031)
- [ ] T063 [US6] Control negativo D1: deshacer T062 y comprobar que cae T061; anotar

### D2 — avisos y timeout de plantillas (US6)

- [ ] T064 [P] [US6] Tests de regresión en `tests/test_tools_templates.py`: (a) `ws_one_shot_subscription(..., collect_warnings=True)` con un evento `{"error": "'x' is undefined", "level": "WARNING"}` seguido de `{"result": "ok", "listeners": {}}` devuelve el resultado con `warnings`; (b) `ha_render_template` en ese caso devuelve `result` y `warnings` y no `template_error`; (c) un evento `{"error": …, "level": "ERROR"}` sigue siendo `template_error`; (d) `HAConnectionError("HA WS command failed: Exceeded maximum execution time of 5s", code="template_error")` → `template_timeout`; (e) sin `collect_warnings`, el comportamiento de `ws_one_shot_subscription` no cambia (FR-033, FR-034)
- [ ] T065 [US6] Parámetro `collect_warnings` en `ws_one_shot_subscription`, `hermes/src/hermes/ha.py:649-717` (cola de eventos en lugar de future único cuando está activo; mismo plazo total; desuscripción garantizada), con comentario del porqué (FR-033, research R-D1)
- [ ] T066 [US6] En `hermes/src/hermes/tools/templates.py:94-133`, llamar con `collect_warnings=True`, devolver `warnings` y reconocer «Exceeded maximum execution time» como `template_timeout`; docstring `:44-82` (FR-033, FR-034)
- [ ] T067 [US6] Control negativo D2: deshacer T065/T066 por separado y comprobar que caen los tests de T064 correspondientes; anotar

### D5 — filtro `domain` en `ha_list_services` (US6)

- [ ] T068 [P] [US6] Tests de regresión en `tests/test_tools_ha_services.py` (nuevo): con `get_services()` simulado de tres dominios, `ha_list_services(domain="light")` devuelve solo `light`; `domain="no_existe"` → `[]`; sin `domain` → la lista completa como antes; la respuesta filtrada mide menos del 10 % de la completa en el fake (FR-035, SC-007)
- [ ] T069 [US6] Parámetro `domain` en `ha_list_services`, `hermes/src/hermes/tools/ha.py:460-466`, con docstring que recomienda usarlo (FR-035)
- [ ] T070 [US6] Control negativo D5: deshacer T069 y comprobar que cae T068; anotar

### R3 + C5 — HACS (US6)

- [ ] T071 [P] [US6] Tests de regresión en `tests/test_tools_hacs.py` (nuevo): con `hacs/info` que lanza `HAConnectionError("HA WS command failed: Unknown command.", code="unknown_command")` y HA 2026.11 → `hacs_moved_to_marketplace` con `hint` que nombra `ha_get_states(domain="update")`; con HA 2026.10 o versión desconocida → `hacs_not_installed`; ningún mensaje contiene «update Hermes»; lo mismo en las otras tres tools `ha_hacs_*`; `category="template"` aceptada y `"netdaemon"` rechazada; `ha_hacs_list_updates` usa `pending_upgrade: true` aunque las versiones coincidan en texto (FR-038, FR-039)
- [ ] T072 [US6] Helper `_hacs_error(ha_client, exc)` y su uso en `hermes/src/hermes/tools/hacs.py:49-54, 91, 118, 144`; `_VALID_CATEGORIES` y disclaimer en `:22-29`; `pending_upgrade` en `:150-160` (FR-038, FR-039)
- [ ] T073 [US6] Control negativo R3/C5: deshacer T072 y comprobar que caen los tests de T071; anotar

### C4 — `perform_action` (US6)

- [ ] T074 [P] [US6] Redocumentar el test de `tests/test_security_regressions.py:211-212` como defensa en profundidad (no alias de HA) y añadir un test que compruebe que `action` (la clave real) sí se detecta (FR-040)
- [ ] T075 [US6] Corregir el comentario de `hermes/src/hermes/tools/ha.py:161-167` (FR-040, research R-D7)
- [ ] T076 [US6] Control negativo C4: quitar `action` de `_SERVICE_CALL_KEYS` en `hermes/src/hermes/tools/ha.py:167` y comprobar que cae el test nuevo de T074; restaurar y anotar

### Cierre del lote D

- [ ] T077 Ejecutar los tests del lote D y la suite completa; grep de privacidad del diff; commit del lote con los recuentos

**Punto de control**: US5 (salvo R4) y US6 completas.

---

## Fase 7: Integración (US5 R4, US8) — tras fusionar A, B, C y D

**Objetivo**: versión mínima, versión 1.0.12, guía, README, CHANGELOG y hoja de ruta coherentes.

**Prueba independiente**: `.venv/bin/pytest tests/test_addon_manifest.py tests/test_tools_guide.py` y la suite completa.

- [ ] T078 Fusionar los lotes A, B, C y D en la rama de trabajo (sin conflictos esperados: no comparten ficheros) y ejecutar la suite completa
- [ ] T079 [P] [US5] Test de regresión en `tests/test_addon_manifest.py`: `HA_CORE_MIN_SUPPORTED == "2024.10.0"` (FR-041, R4)
- [ ] T080 [P] [US8] Test de regresión en `tests/test_tools_guide.py`: la guía de automatizaciones no contiene `"platform":` ni `"service":` y la de registros menciona `ha_remove_device` (FR-042, C4)
- [ ] T081 [US5] `HA_CORE_MIN_SUPPORTED = "2024.10.0"` en `hermes/src/hermes/config.py:27`, con el comentario del porqué (plurales de automatizaciones desde HA 2024.10) (FR-041)
- [ ] T082 [US8] Guía en `hermes/src/hermes/tools/guide.py`: ejemplo `:145-146` con `triggers`/`trigger:` y `actions`/`action:`; `:212-214` con `ha_remove_device` y la antigua marcada como deprecada; `:23` con el número aproximado de tools actualizado (FR-042)
- [ ] T083 Control negativo de integración: deshacer T081 y T082 y comprobar que caen T079 y T080; anotar
- [ ] T084 [US8] Versión 1.0.12 en `hermes/config.yaml:7`, `hermes/src/hermes/__init__.py:6` y `HA_CORE_LAST_TESTED_IN_HERMES` en `hermes/src/hermes/config.py:41`; `HA_CORE_LAST_TESTED` se queda en `2026.11.1` (FR-044, spec S-11)
- [ ] T085 [US8] Entrada `## [1.0.12] — 2026-11-14` al principio de `hermes/CHANGELOG.md`, con una sección `### Fixed` por arreglo (qué fallaba, por qué y desde qué versión de HA), `### Added` para `ha_remove_device` y `### Deprecated` para `ha_remove_device_from_config_entry` (FR-044)
- [ ] T086 [P] [US8] `README.md` y `README.es.md`, sincronizados: versión mínima 2024.10.0 (`README.md:63, 278`; `README.es.md:65, 283`); opción de Tailscale Funnel (`README.md:87-150`; `README.es.md:89-152`) recomendando `tailscale funnel --bg --https=8443 8765` (o 10000), `public_hostname: homeassistant.tailXXXX.ts.net:8443`, URL del conector `https://homeassistant.tailXXXX.ts.net:8443/mcp`, cómo pasar de 443 a 8443 (quitar el Funnel viejo, crear el nuevo, cambiar `public_hostname`, volver a añadir el conector) y que 443 sigue valiendo si no se usa `share_homeassistant: funnel`; solo marcadores genéricos (FR-041, FR-043)
- [ ] T087 [P] [US8] Revisar `hermes/DOCS.md`: actualizar solo si menciona la versión mínima, el puerto del Funnel o la URL del conector (FR-043)
- [ ] T088 [P] [US8] `docs/HOJA-DE-RUTA.md`: revisión sobre 1.0.12; marcar como corregidos los problemas 1–5, 7–20 y 22 de la tabla `:30-61`, el 6 como mitigado (mensaje claro; la migración al Marketplace es de 1.1.0) y dejar 21 y 23 pendientes; sustituir la recomendación provisional `:62-66`; corregir el párrafo de Tailscale `:89-93` (Funnel de Hermes en 8443/10000); mover el plan de 1.0.12 a «hecho» (FR-045)
- [ ] T089 Ejecutar la suite completa (SC-008); comprobar a mano que README.md y README.es.md dicen lo mismo; grep de privacidad e identificadores de modelos de IA sobre todo el diff de la versión (SC-009); commit de integración

**Punto de control**: US5 y US8 completas; versión 1.0.12 lista para revisión del mantenedor.

---

## Fase 8: Cierre transversal

- [ ] T090 Recorrer quickstart.md completo y la tabla de trazabilidad de abajo; cada FR-001…FR-047 tiene su tarea y su test con control negativo anotado (SC-006)
- [ ] T091 Redactar la descripción del PR para el mantenedor: arreglos, recuentos de control negativo por lote, supuestos de la spec (S-01…S-14) y lo que queda fuera (C7, C9, §2.5, Marketplace, CI). Sin push ni fusión: lo decide el mantenedor (principio XI)

---

## Dependencias y orden de ejecución

### Dependencias entre fases

- **Fase 1 (preparación)**: sin dependencias.
- **Fase 2 (fase 0)**: depende de la 1. **Bloquea** a todos los lotes.
- **Fases 3–6 (lotes A, B, C, D)**: dependen solo de la fase 2. **Se ejecutan en paralelo**, cada una en su worktree.
- **Fase 7 (integración)**: depende de que A, B, C y D estén fusionados.
- **Fase 8**: depende de la 7.

### Dependencias entre historias

- US1, US7 (lote A), US2, US3 (lote B), US4 (lote C) y US6 (lote D) son independientes entre sí.
- US5 se reparte: R5 y C8 en el lote D; R4 en integración.
- US8 depende de todas (documenta lo que hicieron).

### Dentro de cada arreglo

1. Test de regresión (falla contra 1.0.11).
2. Implementación (el test pasa).
3. Control negativo (deshacer, ver caer el test, restaurar, anotar el recuento).

### Paralelismo

- Lotes A, B, C y D a la vez, en cuatro worktrees.
- Dentro de un lote, las tareas de test marcadas [P] de arreglos distintos se pueden escribir a la vez si están en ficheros distintos; las que comparten fichero de test se hacen en orden.

---

## Ejemplo en paralelo

```bash
# Tras fusionar la fase 0, abrir cuatro worktrees y lanzar un agente por lote:
Agente A: tareas T009–T021 (ficheros del lote A)
Agente B: tareas T022–T042 (ficheros del lote B)
Agente C: tareas T043–T054 (ficheros del lote C)
Agente D: tareas T055–T077 (ficheros del lote D)
# Después, un agente de integración: T078–T091
```

---

## Estrategia de implementación

### Primero lo que pierde datos

1. Fases 1 y 2.
2. Lotes B (P1, P2) y C (P3) y lote A (R1, R2): son las historias P1.
3. Validar cada uno con su prueba independiente.

### Entrega incremental

Cada lote se puede fusionar en cuanto pasa su prueba independiente y la suite
completa. La versión no se publica hasta el lote de integración.

---

## Trazabilidad FR → tareas

| FR | ID | Lote | Test | Implementación | Control negativo |
|---|---|---|---|---|---|
| FR-001…FR-005 | R1 | A | T013 | T014, T015 | T016 |
| FR-006, FR-007 | R2 | A | T009 | T010, T011 | T012 |
| FR-008, FR-009 | D4 | A | T017 | T018 | T020 |
| FR-010 | C3 | A | T017 | T019 | T020 |
| FR-011, FR-012 | P1, R6 | B | T022 | T023 | T024 |
| FR-013, FR-014 | P1, R6, C1 | B | T022 | T023 | T024 |
| FR-015 | C6 | B | T025 | T026 | T027 |
| FR-016…FR-018 | P2 | B | T028 | T030 | T032 |
| FR-019 | P2 | B | T029 | T031 | T032 |
| FR-020, FR-024 | D3 | B | T033 | T037 | T041 |
| FR-021 | D3 | B | T034 | T038 | T041 |
| FR-022 | D3 | B | T035 | T039 | T041 |
| FR-023 | D3 | B | T036 | T040 | T041 |
| FR-025, FR-026 | P3 | C | T043, T044 | T045 | T047 |
| FR-027 | P3 | C | T044 | T046 | T047 |
| FR-028 | C2 | C | T048 | T049 | T050 |
| FR-029 | lovelace/resources | C | T051 | T052 | T053 |
| FR-030 | D1 | Fase 0 | T003, T004 | T005, T006 | T007 |
| FR-031 | D1 | D | T061 | T062 | T063 |
| FR-032 | R5 | D | T055 | T056 | T057 |
| FR-033, FR-034 | D2 | D | T064 | T065, T066 | T067 |
| FR-035 | D5 | D | T068 | T069 | T070 |
| FR-036 | C8 | D | T058 | T059 | T060 |
| FR-037 | C3 | D | T058 | T059 | T060 |
| FR-038, FR-039 | R3, C5 | D | T071 | T072 | T073 |
| FR-040 | C4 | D | T074 | T075 | T076 |
| FR-041 | R4 | Integración | T079 | T081, T086 | T083 |
| FR-042 | C4 | Integración | T080 | T082 | T083 |
| FR-043 | Decisión 12 | Integración | — (documentación) | T086, T087 | — |
| FR-044 | XI | Integración | test de coherencia existente en `tests/test_addon_manifest.py` | T084, T085 | — |
| FR-045 | XI | Integración | — (documentación) | T088 | — |
| FR-046 | VI, VII | Todos | — | todas las tareas de control negativo | T090 |
| FR-047 | VIII | Todos | — | T008, T021, T042, T054, T077, T089 | — |

Los arreglos que solo cambian una descripción (FR-010, FR-013, FR-014,
FR-027, FR-037) también llevan test: el principio V trata una descripción que
miente como un fallo, y el VI exige un test por fallo corregido. El test
comprueba los hechos clave de la descripción (campos reales, versión, qué está
protegido), no el texto literal.

## Notas

- [P] = ficheros distintos y sin dependencias pendientes.
- Cada lote deja en su commit «con la guarda quitada caen N tests» por arreglo.
- Ningún lote empuja ni fusiona a `main`; eso lo decide el mantenedor.
