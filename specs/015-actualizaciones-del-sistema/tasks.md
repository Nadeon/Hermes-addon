---

description: "Tareas de la sub-feature 015 — actualizaciones del sistema (Hermes 1.2.0)"
---

# Tareas: actualizaciones del sistema (015)

**Entrada**: `specs/015-actualizaciones-del-sistema/` (spec.md, plan.md,
research.md, data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `DummyMCP`,
`structlog.testing.capture_logs`. **Supervisor simulado**: el `MockHAClient`
de `tests/test_tools_supervisor.py` ampliado en
`tests/fixtures/supervisor_actualizaciones.py` para responder por método y
ruta con las formas del Supervisor 2026.11.0 (research R-12), registrar
método, ruta, cuerpo y `timeout_seconds`, y simular 404, lentitud y corte de
conexión. **Core simulado** para las `ha_*`: estados, registro
(`config/entity_registry/get_entries`), `update/release_notes` y
`call_service`. Datos ficticios (`<slug>`, `a0b1c2d3_ejemplo`, versiones
inventadas, centinelas de texto). **Nunca una actualización real.**

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`.
Línea base al especificar (2026-11-14, rama de la 011, punta `2d53a0a`):
2139 passed, 17 skipped, 6 failed (los 6 conocidos de Windows). Cada tramo
anota su propia línea base al empezar y termina con exactamente esos 6 fallos
en local; la referencia es el CI de Linux.

**Requisito previo (S-01)**: la 009, la 010, la 011 completa y, si está, la
013, integradas en la rama (T001). Si falta algo de la 009, la 010 o la 011 al
empezar un tramo, el agente se detiene y lo anota.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 saber qué actualizar, US2 actualizar Core, US3 OS y
Supervisor, US4 entidades `update`, US5 nada de lo actual cambia.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado. Cada uno necesita el anterior integrado.

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **1** — listar, buscar y actualizar Core (CAP-080) | **T001–T016** | Familia `system_updates` con `system_updates`; `sv_list_available_updates`, `sv_check_for_updates`, `sv_update_core`; 5 entradas a `dedicated`; tema `updates` (parte); CHANGELOG (parte) |
| **2** — OS y Supervisor (CAP-080) | **T017–T029** | `sv_update_os`, `sv_update_supervisor` con ejecución en segundo plano y búsqueda del job; 2 entradas a `dedicated`; título `OS`; guía y CHANGELOG |
| **3** — entidades `update` (CAP-064), banco y cierre | **T030–T046** | Módulo `update_entities`: `ha_list_updates`, `ha_get_update_release_notes`, `ha_install_update`; `hint` en `ha_call_service`; `update/release_notes` a `dedicated`; banco con entidad de plantilla e inventario de cobertura; documentación final y matriz; ninguna entrada «pendiente (spec 015)» |

---

## Tramo 1 — listar, buscar y actualizar Core (CAP-080)

### Preparación

- [ ] T001 Integrar en la rama lo que falta de las dependencias (S-01) desde `feat/cobertura-total` (009 y 010 integradas) y la 011 completa; la 013 si ya está integrada. Resolver conflictos sin cambiar comportamiento. Ejecutar la suite y anotar la línea base en el mensaje del commit. Comprobar que existen `self_update_not_supported` en `sv_update_addon`, `tests/banco/` con su inventario de cobertura, `sv_read_api`/`sv_call_api`/`ha_call_ws_command` y `tests/fixtures/esquemas_1_1_2.json`
- [ ] T002 [P] [US5] Tests en `tests/test_tool_families.py`: `system_updates` existe, `desde="1.2.0"`, desactivable, con los módulos `("system_updates",)`, `familia_de_modulo("system_updates") == "system_updates"`; en `tests/test_config_validation.py`, `tool_families_disabled: [system_updates]` es válido. Después, la familia en `hermes/src/hermes/tool_families.py` con un comentario del porqué (research R-1) (FR-017)

### Tests primero (deben fallar)

- [ ] T003 [P] [US2] Tests de las funciones puras en `tests/test_tools_system_updates.py` (`TestValidacion`, `TestBloqueos`): `_validar_version` acepta `2026.11.1`, `2026.12.0b1`, `16.3`, y rechaza vacío, espacios, `/`, `..`, 33 caracteres; `_bloqueos` devuelve cada código de data-model con sus datos y ninguno con un sistema sano; plugins desactualizados con `auto_update` activo → aviso y no bloqueo; `_comparar` con versiones inválidas → `None` (FR-004, FR-010)
- [ ] T004 [P] [US1] Fixture `tests/fixtures/supervisor_actualizaciones.py` (Supervisor simulado, research R-12) y tests `TestListar`/`TestBuscar`: `sv_list_available_updates` con Core, una app, Hermes y un plugin desactualizados → elementos con `installed_version`, `latest_version`, `update_with` correctos, Hermes con `update_with: null` y nota, el plugin con la ruta de la tabla, orden supervisor → core → os → plugins → apps, sobre `{count, items, truncated}` y `_third_party_text`; sin HAOS (`/os/info` 404) → sin elemento `os` y sin error; una lectura que falla → `partial: true` y `unavailable`; solo peticiones `GET`. `sv_check_for_updates` → exactamente un `POST /refresh_updates` con `timeout_seconds=120` y después la lista; error del Supervisor → `error` redactado (FR-001, FR-002)
- [ ] T005 [US2] Tests `TestVistaPreviaCore` y `TestUpdateCore` (vista previa): todos los bloques de data-model con los valores del simulado; `backup.name == "core_<from>"` y `exclude_database` de `/core/info`; `backup=False` → `will_create: false`; `release_notes.available: false` con la `release_url` del estado de la entidad de plataforma `hassio` y `unique_id` `home_assistant_core_version_latest`, y `null` con motivo si Core no responde; `config_check` con `POST /core/check` y `timeout_seconds=120`, y SIN escribir `check_config_state.json` (comprobar que el fichero no cambia); cada bloqueo (`unhealthy`, `supervisor_update_pending`, `plugins_outdated`, `low_disk_space`, `config_invalid`, `config_check_failed`) → `error: update_blocked` con la vista previa y sin `confirmation_token`; `already_installed`, `no_update_available`, `versions_unavailable`, `invalid_argument` → sin token; `version` menor → `downgrade: true` y aviso; en ningún caso hay `POST /core/update` (FR-003, FR-004, FR-005, FR-010)
- [ ] T006 [US2] Tests `TestTokenAtado` y ejecución de `sv_update_core`: confirmar → exactamente un `POST /core/update` con `{"version": <to_version>, "backup": true, "background": true}` y respuesta `{job_id, status: "running", poll_with: "sv_get_job_status", from_version, to_version}`, job registrado con `_track_job`; sin `job_id` en la respuesta → `result: ok`; `version_latest` cambiada entre vista previa y confirmación → `preview_outdated: true`, ninguna llamada `POST` y el token sigue `pending` (se puede pedir otra vista previa sin esperar a que caduque); argumentos distintos → mismo rechazo; error del Supervisor al ejecutar → `error` redactado y token completado con fallo. Centinelas (`password: centinela-…`, un JWT) en el detalle de `/core/check` y en el error del Supervisor → no aparecen en la respuesta ni en el log capturado; el log tiene `system_update_started` con tool, versiones y `job_id` (FR-005, FR-008, FR-018)

### Implementación

- [ ] T007 [US1] `hermes/src/hermes/tools/system_updates.py`: `register(mcp, ha_client, *, response_max_bytes)`, los comunes de plan.md (`_validar_version`, `_leer`, `_salud`, `_plugins`, `_bloqueos`, `_notas_de_entidad`, `_comparar`, `_args_atados`, `_respuesta_token_invalido`), `sv_list_available_updates` y `sv_check_for_updates` según contracts/tools.md, con comentarios del porqué (research R-2, R-9, R-12). T003 y T004 en verde (FR-001, FR-002, FR-004, FR-010)
- [ ] T008 [US2] `sv_update_core` en el mismo módulo: vista previa, bloqueos sin token, token atado a versiones (research R-3), ejecución con `background: true`, `_track_job` y `job_errors` reutilizados de `tools/addons.py` y `supervisor_jobs.py` (sin moverlos), eventos de log sin contenido. T005 y T006 en verde (FR-003…FR-005, FR-008, FR-010, FR-018)
- [ ] T009 [US5] Registro en `hermes/src/hermes/tools/__init__.py` dentro de la comprobación de la familia `system_updates` (patrón de la 011), con `response_max_bytes`; `_annotations.py`: `sv_update_core` en `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD`, `sv_check_for_updates` en `_OPEN_WORLD`, con comentario. Tests en `tests/test_tools_registration.py`: las tres registradas por defecto con las anotaciones de contracts/tools.md (`sv_check_for_updates` no `readOnlyHint`); ninguna con la familia desactivada; con las familias de la 1.2.0 desactivadas la lista es la de la 1.1.2 (SC-005 de la 011); la instantánea `esquemas_1_1_2.json` sin diferencias nuevas; actualizar los recuentos y la comprobación «las únicas tools de más» (FR-017, FR-019)

### Tabla

- [ ] T010 [US2] Tests en `tests/test_command_table.py`: `GET /available_updates`, `POST /refresh_updates`, `POST /reload_updates`, `POST /core/update` y `hassio/update/core` son `dedicated` con su tool de data-model, familia `system_updates` y la CAP del inventario en las de clase A; `/homeassistant/update` y `/supervisor/available_updates` siguen `deny`. Si la 013 no está integrada, `test_clase_a_de_via_dedicada_pendiente_de_su_spec` admite `dedicated` (el mismo cambio que la 013, para que la fusión sea trivial) (FR-016)
- [ ] T011 [US2] `hermes/src/hermes/command_table.py`: las 5 entradas a mano, una línea cada una, con «cubierto por `<tool>`» (y el porqué de `/reload_updates` y `hassio/update/core`, data-model), familia y CAP; ejecutar `scripts/inventario/generar_tabla.py` y comprobar que la tabla no cambia (`git diff --exit-code`); anotarlo en el commit. T010 y `TestDedicadas` en verde (necesita T009) (FR-016)
- [ ] T012 [P] [US2] Tests en `tests/test_tools_generic_commands.py` (o un fichero nuevo `tests/test_tools_actualizaciones_tabla.py`): `sv_read_api("/available_updates")`, `sv_call_api("POST", "/core/update")`, `sv_call_api("POST", "/refresh_updates")` y `ha_call_ws_command("hassio/update/core", …)` → `use_dedicated_tool` con la tool correcta y ninguna llamada, también con `system_updates` desactivada (FR-016)

### Guía, documentación y cierre del tramo 1

- [ ] T013 [US1] [US2] Tema `updates` en `hermes/src/hermes/tools/guide.py` (alias `update`, `upgrade`): listado, búsqueda y Core (bloqueos, backup, token atado, `job_id`); el tema `supervisor` remite a `updates`. Tests en `tests/test_tools_guide.py`: el tema existe, cita las tres tools registradas y los alias resuelven (FR-020)
- [ ] T014 Documentación del tramo 1: sección «Actualizaciones del sistema» dentro de `### Supervisor` en `## [1.2.0] — <fecha de publicación>` de `hermes/CHANGELOG.md` (las tres tools, la familia, las 5 entradas y la desviación de las notas de R-4); `hermes/DOCS.md`, familia `system_updates` en la lista de `tool_families_disabled` (FR-022)
- [ ] T015 Control negativo del tramo 1, anotando recuentos: (a) emitir token con `blocked` no vacío → cae; (b) no atar `_to_version` al token → cae el de versión cambiada; (c) enviar `/core/update` sin `version` → cae; (d) escribir `check_config_state.json` en la vista previa → cae; (e) quitar `redact_secrets` del detalle de `/core/check` → caen los centinelas; (f) usar `/reload_updates` en vez de `/refresh_updates` → cae; (g) dejar `/core/update` como `deny` → cae el de dedicadas. Restaurar y comprobar verde
- [ ] T016 Cierre del tramo 1: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII: nada de hostnames, IPs reales, slugs reales, rutas `C:\`), commit con los recuentos de T015 y el resultado de la regeneración de T011

---

## Tramo 2 — OS y Supervisor (CAP-080)

- [ ] T017 Línea base del tramo (suite) y comprobación de que el tramo 1 está integrado; anotarla en el commit
- [ ] T018 [P] [US3] Tests `TestUpdateOs` y `TestUpdateSupervisor` (vista previa) en `tests/test_tools_system_updates.py`: OS → bloques de data-model, `restarts.components == []`, `after` con `sv_reboot_host`, `backup.will_create: false` con la pista, `release_notes.text` con el aviso de reinicio de la entidad del OS si Core responde; `/os/info` 404 → `not_haos` sin token y sin `POST`; `version_pending == to_version` → `reboot_pending`; Supervisor pendiente o sistema no saludable → `update_blocked`. Supervisor → sin argumento `version` en el esquema; `update_available: false` → `no_update_available`; `restarts.components == ["supervisor"]`, descripción con «Core and apps are not restarted»; `backup.possible: false`. Ninguna llamada `POST` en las vistas previas (FR-003, FR-004, FR-006, FR-007)
- [ ] T019 [US3] Tests `TestSegundoPlano` y token de OS/Supervisor: confirmar OS → un `POST /os/update` con `{"version": <to_version>}` y `timeout_seconds=1800` lanzado en una tarea de fondo; con un job `os_manager_update` no terminado en `/jobs/info` → `job_id`, `poll_with` y `_track_job`; sin él tras la espera (reloj inyectado, sin dormir de verdad) → `status: started` y `verify_with: sv_get_os_info`; Supervisor → `POST /supervisor/update` sin cuerpo, job `supervisor_update`, nota de que el job desaparece al reiniciarse; corte de conexión en la tarea de fondo → evento `system_update_finished`/`failed` sin excepción sin recoger y la respuesta ya devuelta no cambia; error de la tarea de fondo con un centinela → log redactado; la referencia de la tarea se guarda y se suelta al terminar; versión cambiada → `preview_outdated` sin `POST` (FR-008, FR-009, FR-018)
- [ ] T020 [US3] `sv_update_os` y `sv_update_supervisor` en `tools/system_updates.py` (vista previa, bloqueos, token atado). T018 en verde (FR-003, FR-004, FR-006, FR-007, FR-008)
- [ ] T021 [US3] `_lanzar_en_segundo_plano` y la búsqueda del job (plan.md, research R-7), con comentario del porqué de la referencia guardada y de no esperar en primer plano. T019 en verde (FR-009)
- [ ] T022 Tests en `tests/test_command_table.py`: `POST /os/update` y `POST /supervisor/update` `dedicated` con su tool, familia y CAP-080 (FR-016)
- [ ] T023 `command_table.py`: las 2 entradas a mano; regenerar y comprobar que no cambia; anotarlo en el commit. T022 en verde (FR-016)
- [ ] T024 [US5] Registro de las dos (ya dentro de la familia) y `_annotations.py`: las dos en `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD`; si la 013 no trajo `"os": "OS"` en `_TITLE_WORDS`, añadirlo con un test de que ningún título de la 1.1.2 cambia. Tests en `tests/test_tools_registration.py`: anotaciones y títulos (`Update OS (Supervisor)`) (FR-017)
- [ ] T025 [US3] Guía: tema `updates` con OS y Supervisor, el orden recomendado (Supervisor → Core → OS y reiniciar el host) y qué hacer tras el reinicio del Supervisor; test en `tests/test_tools_guide.py` (FR-020)
- [ ] T026 Documentación del tramo 2: CHANGELOG (las dos tools, las 2 entradas, OS sin backup y sin reinicio automático) (FR-022)
- [ ] T027 [P] Tests de las genéricas: `sv_call_api("POST", "/os/update")` y `("POST", "/supervisor/update")` → `use_dedicated_tool` sin llamada (FR-016)
- [ ] T028 Control negativo del tramo 2, anotando recuentos: (a) esperar la petición en primer plano → cae el de respuesta inmediata; (b) no guardar la referencia de la tarea → cae; (c) emitir token sin HAOS → cae; (d) no detectar `reboot_pending` → cae; (e) tratar el corte de conexión como error → cae; (f) quitar la redacción del error de fondo → cae el centinela. Restaurar y comprobar verde
- [ ] T029 Cierre del tramo 2: suite completa (los 6 conocidos), revisión del diff, commit con los recuentos de T028

---

## Tramo 3 — entidades `update` (CAP-064), banco y cierre

- [ ] T030 Línea base del tramo y comprobación de que los tramos 1 y 2 están integrados y de que el banco de la 010 corre en el CI de la rama
- [ ] T031 [P] [US4] Tests `TestListarEntidades` y `TestNotas` en `tests/test_tools_update_entities.py` (Core simulado): `ha_list_updates` → solo `state: on` por defecto, todas con `include_up_to_date`; `supports` decodificado de `supported_features` (1, 2, 4, 8, 16); `install_with` según plataforma y `unique_id` (una sola petición `config/entity_registry/get_entries`); `release_summary` recortado y `_third_party_text`; sobre común. `ha_get_update_release_notes` → texto redactado (centinela), recortado con `truncated` al tope y como texto de terceros; entidad sin `RELEASE_NOTES` → `supported: false` con `release_summary` y `release_url` y sin llamar a `update/release_notes`; `entity_id` inválido → `invalid_argument` sin llamar (FR-011, FR-012, FR-018)
- [ ] T032 [US4] Tests `TestInstalar`: sin actualización y sin `version` → `no_update_available`; `version` sin `SPECIFIC_VERSION` → `specific_version_not_supported`; `backup` sin `BACKUP` → `backup_not_supported`; `in_progress` → `update_in_progress`; entidad inexistente → `entity_not_found`; todos sin token y sin `call_service`. Vista previa con `from_version`, `to_version`, notas a 1500 caracteres (o el resumen), `backup` con la nota de la integración, aviso de firmware con `device_class: firmware`. Confirmar → un `call_service("update", "install", {"entity_id", "version": <to_version>, "backup"}, allow_dangerous=True)`; espera vencida (`TimeoutError`) → `status: running` y pista de `ha_list_updates` (FR-013)
- [ ] T033 [US4] Tests `TestEncaminar`: entidades de plataforma `hassio` con `unique_id` de Core, OS y Supervisor → `use_dedicated_tool` con `sv_update_core`/`sv_update_os`/`sv_update_supervisor` y los argumentos de data-model (OS con `backup=true` → la nota); `<slug>_version_latest` → `sv_update_addon` con `slug`; la de Hermes → `self_update_not_supported`; un `entity_id` renombrado se encamina igual (se decide por el registro); ninguna emite token ni llama a `call_service` (FR-014)
- [ ] T034 [US4] Tests de token y secretos de `ha_install_update`: `latest_version` cambiada entre vista previa y confirmación → `preview_outdated` sin `call_service`; centinela en las notas y en el error de Core → no aparece en la vista previa, la respuesta ni el log (FR-008, FR-013, FR-018)
- [ ] T035 [US4] `hermes/src/hermes/tools/update_entities.py` con las tres tools según contracts/tools.md (con el comentario del porqué de `allow_dangerous=True` tras validar el token propio y de la espera, research R-11); `update_entities` en la familia `system_updates` (`tool_families.py` y su test de T002). T031–T034 en verde (FR-011…FR-014, FR-017)
- [ ] T036 [US5] Registro en `tools/__init__.py` y `_annotations.py`: `ha_install_update` en `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD`, `ha_get_update_release_notes` en `_OPEN_WORLD`. Tests en `tests/test_tools_registration.py`: las tres con sus anotaciones; ninguna con la familia desactivada (FR-017)
- [ ] T037 [US5] Test `TestHintUpdateInstall` en `tests/test_call_service_security.py`: `ha_call_service("update", "install", …)` sin token → la vista previa de siempre más `hint` con `ha_install_update`; con token → mismo comportamiento que en la 1.1.2; otro servicio → sin `hint`. Después, la `hint` en `tools/ha.py` (FR-015, FR-019)
- [ ] T038 Tests en `tests/test_command_table.py`: `update/release_notes` `dedicated` con `ha_get_update_release_notes`, familia y CAP-064; ninguna entrada de la tabla con «spec 015» en el motivo; `ha_read_ws_command("update/release_notes", …)` → `use_dedicated_tool` sin llamada (FR-016)
- [ ] T039 `command_table.py`: la entrada a mano; regenerar y comprobar que no cambia; anotarlo en el commit. T038 en verde (FR-016)
- [ ] T040 [US5] Comprobación de FR-019 y SC-007: con `tool_families_disabled` con todas las familias de la 1.2.0, la lista y las anotaciones son las de la 1.1.2; la instantánea `esquemas_1_1_2.json` sin diferencias nuevas (FR-019)
- [ ] T041 [US4] Banco: en `tests/banco/ha_config/configuration.yaml`, `template:` con una entidad `update` (`installed_version` desde un `input_text` de apoyo, `latest_version` fija, `specific_version: true`, `backup: true`, acción `install` que escribe la versión pedida —`specific_version` o la última— en el `input_text` y `backup` en un `input_boolean`), con comentario del porqué (research R-12). `tests/banco/test_banco_actualizaciones.py` con la base y el lector de la 010: `ha_list_updates` la ve con `supports` correcto; `ha_get_update_release_notes` → `supported: false` con el resumen; `ha_install_update` vista previa → el lector no ve cambios → confirmación → el lector ve la versión nueva y la entidad `off`; con `version` concreta y `backup=true` → el lector ve esa versión y el `input_boolean` encendido; limpieza al cerrar (FR-013, FR-021, SC-006)
- [ ] T042 [US1] [US4] Guía completa: tema `updates` con las entidades `update`, el encaminamiento y la `hint` de `ha_call_service`; test en `tests/test_tools_guide.py` (FR-020)
- [ ] T043 Inventario de cobertura del banco: `tests/banco/cobertura_015.py` con `PROBADAS_015 = {"ha_install_update"}` y `NO_EJECUTABLES_015` con `sv_check_for_updates`, `sv_update_core`, `sv_update_os` y `sv_update_supervisor` y el motivo («Supervisor real: el banco solo simula el Supervisor y reenvía a Core; prueba manual en la VM de la 014»), sumado al invariante de escrituras que haya en la rama (010/028) o con su propio `tests/test_banco_cobertura_015.py`: toda tool que modifica de la familia `system_updates` (por `readOnlyHint` del registro de producción) está en una de las dos partes; el plugin de `tests/banco/obligatorio.py` exige que `ha_install_update` se ejecute con éxito (FR-021)
- [ ] T044 Documentación final: CHANGELOG (sección completa: 8 tools, familia, 8 entradas de la tabla, encaminamiento, `hint`, desviaciones de R-4 y R-9); `docs/HOJA-DE-RUTA.md`: la 015 → «hecha», con lo probado en el banco y la prueba real de las cuatro `sv_*` que modifican como pendiente manual en la VM de la 014 (quickstart.md, paso 3), y el punto «Actualizar Core, OS y Supervisor con vista previa útil» como resuelto; `README.md` y `README.es.md` sincronizados (tools nuevas por áreas y recuento si lo llevan); `hermes/DOCS.md`; `specs/008-cobertura-total/plan.md`: filas CAP-064 y CAP-080 de la matriz con las tools y los ficheros de test, sin cambiar las columnas que lee `_matriz_008` (sub-feature y vía), y los hallazgos de research R-13 (FR-022)
- [ ] T045 Control negativo del tramo 3, anotando recuentos: (a) no encaminar la entidad de Core → cae; (b) decidir por `entity_id` en vez de por el registro → cae el del renombrado; (c) emitir token con `backup` sin soporte → cae; (d) no atar `_to_version` → cae; (e) tratar el `TimeoutError` como error → cae; (f) quitar la `hint` → cae; (g) sacar `ha_install_update` de `PROBADAS_015` → cae el inventario. Restaurar y comprobar verde
- [ ] T046 Cierre del tramo 3: suite completa (los 6 conocidos), CI de la rama y banco en verde, revisión del diff (principio VIII, FR-021 de la 008), commit con los recuentos de T045

## Dependencias y paralelismo

- T001 antes de todo. T002 antes de T009. T003 y T004 en paralelo; T005 y T006
  después de T004 (usan la fixture). T007 tras T003/T004; T008 tras T005/T006.
  T009 antes de T011 (`TestDedicadas` necesita las tools registradas). T012 en
  paralelo con T013 y T014.
- Tramo 2: T018 y T019 antes de T020/T021; T020 antes de T023 (`TestDedicadas`); T027 en
  paralelo con T025/T026.
- Tramo 3: T031–T034 antes de T035; T036 antes de T039; T041 necesita T035 y
  T036; T043 tras T041.
