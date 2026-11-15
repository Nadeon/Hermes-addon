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

- [X] T001 Integrar en la rama lo que falta de las dependencias (S-01) desde `feat/cobertura-total` (009 y 010 integradas) y la 011 completa; la 013 si ya está integrada. Resolver conflictos sin cambiar comportamiento. Ejecutar la suite y anotar la línea base en el mensaje del commit. Comprobar que existen `self_update_not_supported` en `sv_update_addon`, `tests/banco/` con su inventario de cobertura, `sv_read_api`/`sv_call_api`/`ha_call_ws_command` y `tests/fixtures/esquemas_1_1_2.json`
- [X] T002 [P] [US5] Tests en `tests/test_tool_families.py`: `system_updates` existe, `desde="1.2.0"`, desactivable, con los módulos `("system_updates",)`, `familia_de_modulo("system_updates") == "system_updates"`; en `tests/test_config_validation.py`, `tool_families_disabled: [system_updates]` es válido. Después, la familia en `hermes/src/hermes/tool_families.py` con un comentario del porqué (research R-1) (FR-017)

### Tests primero (deben fallar)

- [X] T003 [P] [US2] Tests de las funciones puras en `tests/test_tools_system_updates.py` (`TestValidacion`, `TestBloqueos`): `_validar_version` acepta `2026.11.1`, `2026.12.0b1`, `16.3`, y rechaza vacío, espacios, `/`, `..`, 33 caracteres; `_bloqueos` devuelve cada código de data-model con sus datos y ninguno con un sistema sano; plugins desactualizados con `auto_update` activo → aviso y no bloqueo; `_comparar` con versiones inválidas → `None` (FR-004, FR-010)
- [X] T004 [P] [US1] Fixture `tests/fixtures/supervisor_actualizaciones.py` (Supervisor simulado, research R-12) y tests `TestListar`/`TestBuscar`: `sv_list_available_updates` con Core, una app, Hermes y un plugin desactualizados → elementos con `installed_version`, `latest_version`, `update_with` correctos, Hermes con `update_with: null` y nota, el plugin con la ruta de la tabla, orden supervisor → core → os → plugins → apps, sobre `{count, items, truncated}` y `_third_party_text`; sin HAOS (`/os/info` 404) → sin elemento `os` y sin error; una lectura que falla → `partial: true` y `unavailable`; solo peticiones `GET`. `sv_check_for_updates` → exactamente un `POST /refresh_updates` con `timeout_seconds=120` y después la lista; error del Supervisor → `error` redactado (FR-001, FR-002)
- [X] T005 [US2] Tests `TestVistaPreviaCore` y `TestUpdateCore` (vista previa): todos los bloques de data-model con los valores del simulado; `backup.name == "core_<from>"` y `exclude_database` de `/core/info`; `backup=False` → `will_create: false`; `release_notes.available: false` con la `release_url` del estado de la entidad de plataforma `hassio` y `unique_id` `home_assistant_core_version_latest`, y `null` con motivo si Core no responde; `config_check` con `POST /core/check` y `timeout_seconds=120`, y SIN escribir `check_config_state.json` (comprobar que el fichero no cambia); cada bloqueo (`unhealthy`, `supervisor_update_pending`, `plugins_outdated`, `low_disk_space`, `config_invalid`, `config_check_failed`) → `error: update_blocked` con la vista previa y sin `confirmation_token`; `already_installed`, `no_update_available`, `versions_unavailable`, `invalid_argument` → sin token; `version` menor → `downgrade: true` y aviso; en ningún caso hay `POST /core/update` (FR-003, FR-004, FR-005, FR-010)
- [X] T006 [US2] Tests `TestTokenAtado` y ejecución de `sv_update_core`: confirmar → exactamente un `POST /core/update` con `{"version": <to_version>, "backup": true, "background": true}` y respuesta `{job_id, status: "running", poll_with: "sv_get_job_status", from_version, to_version}`, job registrado con `_track_job`; sin `job_id` en la respuesta → `result: ok`; `version_latest` cambiada entre vista previa y confirmación → `preview_outdated: true`, ninguna llamada `POST` y el token sigue `pending` (se puede pedir otra vista previa sin esperar a que caduque); argumentos distintos → mismo rechazo; error del Supervisor al ejecutar → `error` redactado y token completado con fallo. Centinelas (`password: centinela-…`, un JWT) en el detalle de `/core/check` y en el error del Supervisor → no aparecen en la respuesta ni en el log capturado; el log tiene `system_update_started` con tool, versiones y `job_id` (FR-005, FR-008, FR-018)

### Implementación

- [X] T007 [US1] `hermes/src/hermes/tools/system_updates.py`: `register(mcp, ha_client, *, response_max_bytes)`, los comunes de plan.md (`_validar_version`, `_leer`, `_salud`, `_plugins`, `_bloqueos`, `_notas_de_entidad`, `_comparar`, `_args_atados`, `_respuesta_token_invalido`), `sv_list_available_updates` y `sv_check_for_updates` según contracts/tools.md, con comentarios del porqué (research R-2, R-9, R-12). T003 y T004 en verde (FR-001, FR-002, FR-004, FR-010)
- [X] T008 [US2] `sv_update_core` en el mismo módulo: vista previa, bloqueos sin token, token atado a versiones (research R-3), ejecución con `background: true`, `_track_job` y `job_errors` reutilizados de `tools/addons.py` y `supervisor_jobs.py` (sin moverlos), eventos de log sin contenido. T005 y T006 en verde (FR-003…FR-005, FR-008, FR-010, FR-018)
- [X] T009 [US5] Registro en `hermes/src/hermes/tools/__init__.py` dentro de la comprobación de la familia `system_updates` (patrón de la 011), con `response_max_bytes`; `_annotations.py`: `sv_update_core` en `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD`, `sv_check_for_updates` en `_OPEN_WORLD`, con comentario. Tests en `tests/test_tools_registration.py`: las tres registradas por defecto con las anotaciones de contracts/tools.md (`sv_check_for_updates` no `readOnlyHint`); ninguna con la familia desactivada; con las familias de la 1.2.0 desactivadas la lista es la de la 1.1.2 (SC-005 de la 011); la instantánea `esquemas_1_1_2.json` sin diferencias nuevas; actualizar los recuentos y la comprobación «las únicas tools de más» (FR-017, FR-019)

### Tabla

- [X] T010 [US2] Tests en `tests/test_command_table.py`: `GET /available_updates`, `POST /refresh_updates`, `POST /reload_updates`, `POST /core/update` y `hassio/update/core` son `dedicated` con su tool de data-model, familia `system_updates` y la CAP del inventario en las de clase A; `/homeassistant/update` y `/supervisor/available_updates` siguen `deny`. Si la 013 no está integrada, `test_clase_a_de_via_dedicada_pendiente_de_su_spec` admite `dedicated` (el mismo cambio que la 013, para que la fusión sea trivial) (FR-016)
- [X] T011 [US2] `hermes/src/hermes/command_table.py`: las 5 entradas a mano, una línea cada una, con «cubierto por `<tool>`» (y el porqué de `/reload_updates` y `hassio/update/core`, data-model), familia y CAP; ejecutar `scripts/inventario/generar_tabla.py` y comprobar que la tabla no cambia (`git diff --exit-code`); anotarlo en el commit. T010 y `TestDedicadas` en verde (necesita T009) (FR-016)
- [X] T012 [P] [US2] Tests en `tests/test_tools_generic_commands.py` (o un fichero nuevo `tests/test_tools_actualizaciones_tabla.py`): `sv_read_api("/available_updates")`, `sv_call_api("POST", "/core/update")`, `sv_call_api("POST", "/refresh_updates")` y `ha_call_ws_command("hassio/update/core", …)` → `use_dedicated_tool` con la tool correcta y ninguna llamada, también con `system_updates` desactivada (FR-016)

### Guía, documentación y cierre del tramo 1

- [X] T013 [US1] [US2] Tema `updates` en `hermes/src/hermes/tools/guide.py` (alias `update`, `upgrade`): listado, búsqueda y Core (bloqueos, backup, token atado, `job_id`); el tema `supervisor` remite a `updates`. Tests en `tests/test_tools_guide.py`: el tema existe, cita las tres tools registradas y los alias resuelven (FR-020)
- [X] T014 Documentación del tramo 1: sección «Actualizaciones del sistema» dentro de `### Supervisor` en `## [1.2.0] — <fecha de publicación>` de `hermes/CHANGELOG.md` (las tres tools, la familia, las 5 entradas y la desviación de las notas de R-4); `hermes/DOCS.md`, familia `system_updates` en la lista de `tool_families_disabled` (FR-022)
- [X] T015 Control negativo del tramo 1, anotando recuentos: (a) emitir token con `blocked` no vacío → cae; (b) no atar `_to_version` al token → cae el de versión cambiada; (c) enviar `/core/update` sin `version` → cae; (d) escribir `check_config_state.json` en la vista previa → cae; (e) quitar `redact_secrets` del detalle de `/core/check` → caen los centinelas; (f) usar `/reload_updates` en vez de `/refresh_updates` → cae; (g) dejar `/core/update` como `deny` → cae el de dedicadas. Restaurar y comprobar verde
- [X] T016 Cierre del tramo 1: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII: nada de hostnames, IPs reales, slugs reales, rutas `C:\`), commit con los recuentos de T015 y el resultado de la regeneración de T011

### Notas del tramo 1 (desviaciones y decisiones)

- **Línea base** tras la fusión (T001): 2451 passed, 65 skipped, 6 failed (los
  6 de Windows). La rama del programa traía la 009, 010, 011, 028, 014 y 013;
  la 018 aún no estaba integrada.
- **`hassio/update/core`** ya no era `dedicated` hacia `ha_call_service` (lo
  cambió el T046 de la 011 a `deny` «pendiente (spec 015)»). Pasa a
  `dedicated` hacia `sv_update_core`; `TestPistasYMotivos` de
  `tests/test_command_table.py` se adapta (la otra entrada de T046 sigue
  igual). La regla de `test_clase_a_de_via_dedicada_pendiente_de_su_spec` ya
  admitía `dedicated` (la trajo la 013): sin cambios.
- **D-3 (decisión del supervisor)**: la configuración de Core inválida o sin
  comprobar bloquea siempre, sin argumento para saltarlo.
- **D-1 (decisión del supervisor)**: en `sv_list_available_updates` la app de
  Hermes sale con `update_with: null` y la nota de actualizarla desde la
  interfaz. El rechazo de la entidad `update` de Hermes en
  `ha_install_update` es del tramo 3.
- **Código de error** de un fallo del Supervisor al buscar o al actualizar:
  `supervisor_error` con `detail` redactado (el contrato no nombraba uno).
  `sv_check_for_updates` añade `refreshed: true` a la lista.
- **Descripción de la familia**: la final de data-model (nombra ya OS,
  Supervisor y las entidades `update`, que llegan en los tramos 2 y 3).
- **Guía**: además del tema y los alias, las instrucciones del servidor
  nombran el tema `updates` solo con la familia activa (como la 013 con
  `system_diagnostics`).
- **Matriz de la 014**: `sv_check_for_updates` y `sv_update_core` entran como
  «VM / pendiente», con su línea en «Tandas de pruebas» de
  `docs/BANCO-SUPERVISOR.md`.
- **Inventario del banco, adelantado de T043**: el invariante de escrituras
  de la 028 ya exige clasificar toda tool que modifica, así que el tramo 1
  crea `tests/banco/cobertura_015.py` con `PROBADAS_015` vacía y
  `NO_EJECUTABLES_015` con `sv_check_for_updates` y `sv_update_core` (motivo
  de T043), sumado en `tests/test_banco_cobertura_escrituras.py` (128 tools
  que modifican). El tramo 3 añade `ha_install_update` y el tramo 2, las
  suyas. Control negativo: sin `sv_update_core` en la lista → cae el
  invariante.
- **Rol del Supervisor (014)**: las lecturas por `_leer(ha_client, ruta)` van
  declaradas en `LLAMADAS_DECLARADAS` de `tests/test_rutas_supervisor_rol.py`;
  todas caben en `manager`. Las rutas de los plugins están escritas enteras
  (`_RUTA_INFO_PLUGIN`), sin interpolar, como pide
  `test_every_module_that_builds_a_path_has_a_validator`.
- **Inventario de argumentos atados de la 033**
  (`tests/test_confirmation_args_inventory.py`): no está integrado en la rama.
  Al integrarlo, `sv_update_core` entra con `{"version": atado, "backup":
  atado}` (las versiones de origen y destino se atan además dentro de la
  tool, research R-3).
- **Control negativo (T015)**, con los tests de la 015, la tabla, el registro
  y la guía: (a) token con `blocked` → 6 rojos; (b) sin `_to_version` → 1;
  (c) `/core/update` sin `version` → 2; (d) escribir `check_config_state.json`
  → 2; (e) sin `redact_secrets` en el detalle → 3; (f) `/reload_updates` en
  vez de `/refresh_updates` → 2; (g) `/core/update` de vuelta a `deny` → 4
  (tabla, las dos genéricas y el registro con la familia apagada); (h) sin el
  alias `upgrade` → 2 subtests. Además, sin la fila de `sv_update_core` en la
  matriz → cae `test_una_fila_por_tool_que_modifica`. Todo restaurado y en
  verde.

---

## Tramo 2 — OS y Supervisor (CAP-080)

- [X] T017 Línea base del tramo (suite) y comprobación de que el tramo 1 está integrado; anotarla en el commit
- [X] T018 [P] [US3] Tests `TestUpdateOs` y `TestUpdateSupervisor` (vista previa) en `tests/test_tools_system_updates.py`: OS → bloques de data-model, `restarts.components == []`, `after` con `sv_reboot_host`, `backup.will_create: false` con la pista, `release_notes.text` con el aviso de reinicio de la entidad del OS si Core responde; `/os/info` 404 → `not_haos` sin token y sin `POST`; `version_pending == to_version` → `reboot_pending`; Supervisor pendiente o sistema no saludable → `update_blocked`. Supervisor → sin argumento `version` en el esquema; `update_available: false` → `no_update_available`; `restarts.components == ["supervisor"]`, descripción con «Core and apps are not restarted»; `backup.possible: false`. Ninguna llamada `POST` en las vistas previas (FR-003, FR-004, FR-006, FR-007)
- [X] T019 [US3] Tests `TestSegundoPlano` y token de OS/Supervisor: confirmar OS → un `POST /os/update` con `{"version": <to_version>}` y `timeout_seconds=1800` lanzado en una tarea de fondo; con un job `os_manager_update` no terminado en `/jobs/info` → `job_id`, `poll_with` y `_track_job`; sin él tras la espera (reloj inyectado, sin dormir de verdad) → `status: started` y `verify_with: sv_get_os_info`; Supervisor → `POST /supervisor/update` sin cuerpo, job `supervisor_update`, nota de que el job desaparece al reiniciarse; corte de conexión en la tarea de fondo → evento `system_update_finished`/`failed` sin excepción sin recoger y la respuesta ya devuelta no cambia; error de la tarea de fondo con un centinela → log redactado; la referencia de la tarea se guarda y se suelta al terminar; versión cambiada → `preview_outdated` sin `POST` (FR-008, FR-009, FR-018)
- [X] T020 [US3] `sv_update_os` y `sv_update_supervisor` en `tools/system_updates.py` (vista previa, bloqueos, token atado). T018 en verde (FR-003, FR-004, FR-006, FR-007, FR-008)
- [X] T021 [US3] `_lanzar_en_segundo_plano` y la búsqueda del job (plan.md, research R-7), con comentario del porqué de la referencia guardada y de no esperar en primer plano. T019 en verde (FR-009)
- [X] T022 Tests en `tests/test_command_table.py`: `POST /os/update` y `POST /supervisor/update` `dedicated` con su tool, familia y CAP-080 (FR-016)
- [X] T023 `command_table.py`: las 2 entradas a mano; regenerar y comprobar que no cambia; anotarlo en el commit. T022 en verde (FR-016)
- [X] T024 [US5] Registro de las dos (ya dentro de la familia) y `_annotations.py`: las dos en `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD`; si la 013 no trajo `"os": "OS"` en `_TITLE_WORDS`, añadirlo con un test de que ningún título de la 1.1.2 cambia. Tests en `tests/test_tools_registration.py`: anotaciones y títulos (`Update OS (Supervisor)`) (FR-017)
- [X] T025 [US3] Guía: tema `updates` con OS y Supervisor, el orden recomendado (Supervisor → Core → OS y reiniciar el host) y qué hacer tras el reinicio del Supervisor; test en `tests/test_tools_guide.py` (FR-020)
- [X] T026 Documentación del tramo 2: CHANGELOG (las dos tools, las 2 entradas, OS sin backup y sin reinicio automático) (FR-022)
- [X] T027 [P] Tests de las genéricas: `sv_call_api("POST", "/os/update")` y `("POST", "/supervisor/update")` → `use_dedicated_tool` sin llamada (FR-016)
- [X] T028 Control negativo del tramo 2, anotando recuentos: (a) esperar la petición en primer plano → cae el de respuesta inmediata; (b) no guardar la referencia de la tarea → cae; (c) emitir token sin HAOS → cae; (d) no detectar `reboot_pending` → cae; (e) tratar el corte de conexión como error → cae; (f) quitar la redacción del error de fondo → cae el centinela. Restaurar y comprobar verde
- [X] T029 Cierre del tramo 2: suite completa (los 6 conocidos), revisión del diff, commit con los recuentos de T028

### Notas del tramo 2 (desviaciones y decisiones)

- **Línea base** (T017): 2517 passed, 65 skipped, 6 failed (los 6 de
  Windows), con el tramo 1 en la rama (`d10682d`).
- **`"os": "OS"`** ya estaba en `_TITLE_WORDS` (lo trajo la 013): sin cambio;
  el título `Update OS (Supervisor)` se comprueba en el registro.
- **Vista previa del OS**: `restarts.components == []` (instalar no reinicia
  nada, data-model), pero la descripción, `after`, el primer aviso de
  `warnings`, la descripción de la tool y la guía dicen sin rodeos que el OS
  solo se aplica al reiniciar el host y que eso reinicia todo, Hermes
  incluido. Si ya hay otra versión pendiente de reinicio, se avisa de que la
  nueva la sustituye en la ranura inactiva. `backup.possible: false` y la
  pista de `sv_create_backup_full`/`partial` (D-2 no se implementa). Sin
  `config_check` ni `plugins_to_update_first` (solo Core).
- **Vista previa del Supervisor**: añade `channel` (la spec lo pide, el
  data-model no lo listaba). `update_available: false` → `no_update_available`.
  Nada la bloquea (el job no tiene condiciones, R-6); un sistema no saludable
  se enseña en `system_health` sin bloquear.
- **Notas**: `_url_de_notas` se parte en `_entidad_de_notas` (devuelve además
  el `entity_id`) y `_notas_con_texto`, que pide `update/release_notes` a esa
  entidad para el OS (el aviso de reinicio). `_resolver_destino` reúne la
  resolución de versiones de Core, OS y Supervisor (los mensajes de Core no
  cambian).
- **Segundo plano** (R-7): `_lanzar_en_segundo_plano` nunca termina con
  excepción (devuelve `{"outcome": ok | connection_lost | timeout | failed}`)
  para que nada salga sin redactar como «Task exception was never
  retrieved». Un corte de conexión o la espera de 1800 s vencida van al log
  como `system_update_finished` (no es un fallo: el Supervisor sigue con
  `shield`); un error del Supervisor, como `system_update_failed` con el
  detalle redactado y recortado. Decisión añadida: si la petición de fondo
  termina ANTES de encontrar el job, la tool lo dice ya: rechazo →
  `supervisor_error` redactado y token completado con fallo; éxito →
  `result: ok`; corte → `status: started`. La búsqueda cede el turno una vez
  antes de mirar `/jobs/info` y busca también entre los `child_jobs`; un job
  ya terminado con el mismo nombre no cuenta.
- **Confirmación**: como en Core, no repite la lectura de bloqueos; si el
  Supervisor la rechaza (p. ej. `reboot_pending` entre medias), se ve como
  `supervisor_error` dentro de la búsqueda.
- **Rol del Supervisor (014)**: `/jobs/info` añadida a las lecturas de
  `_leer` y la petición de fondo (`peticion`, con las rutas fijas
  `/os/update` y `/supervisor/update`) declarada en `LLAMADAS_DECLARADAS`;
  todas caben en `manager`.
- **Inventario del banco**: `sv_update_os` y `sv_update_supervisor` en
  `NO_EJECUTABLES_015` (130 tools que modifican); en la matriz de la 014 como
  «VM / pendiente», con su línea en «Tandas de pruebas» de
  `docs/BANCO-SUPERVISOR.md`.
- **Recuento de tools**: 236 en README, README.es y DOCS (la fila «System
  updates» pasa a 5).
- **Inventario de argumentos atados de la 033**
  (`tests/test_confirmation_args_inventory.py`): sigue sin estar en la rama.
  Al integrarlo, filas nuevas: `sv_update_os` con `{"version": atado}` y
  `sv_update_supervisor` sin argumentos atados (`{}`); en las dos, las
  versiones de origen y destino se atan además dentro de la tool (R-3).
- **Control negativo (T028)**, con los tests de la 015, la tabla, las
  genéricas, el registro y la guía: (a) esperar la petición en primer plano
  → 9 rojos; (b) sin guardar la referencia → 5; (c) token sin HAOS → 1;
  (d) sin `reboot_pending` → 2; (e) corte tratado como error → 2; (f) sin
  redactar el error de fondo → 2; (g) `/os/update` de vuelta a `deny` → 2
  tests y 2 subtests (tabla, registro con la familia apagada y la genérica).
  Todo restaurado y en verde.

---

## Tramo 3 — entidades `update` (CAP-064), banco y cierre

- [X] T030 Línea base del tramo y comprobación de que los tramos 1 y 2 están integrados y de que el banco de la 010 corre en el CI de la rama
- [X] T031 [P] [US4] Tests `TestListarEntidades` y `TestNotas` en `tests/test_tools_update_entities.py` (Core simulado): `ha_list_updates` → solo `state: on` por defecto, todas con `include_up_to_date`; `supports` decodificado de `supported_features` (1, 2, 4, 8, 16); `install_with` según plataforma y `unique_id` (una sola petición `config/entity_registry/get_entries`); `release_summary` recortado y `_third_party_text`; sobre común. `ha_get_update_release_notes` → texto redactado (centinela), recortado con `truncated` al tope y como texto de terceros; entidad sin `RELEASE_NOTES` → `supported: false` con `release_summary` y `release_url` y sin llamar a `update/release_notes`; `entity_id` inválido → `invalid_argument` sin llamar (FR-011, FR-012, FR-018)
- [X] T032 [US4] Tests `TestInstalar`: sin actualización y sin `version` → `no_update_available`; `version` sin `SPECIFIC_VERSION` → `specific_version_not_supported`; `backup` sin `BACKUP` → `backup_not_supported`; `in_progress` → `update_in_progress`; entidad inexistente → `entity_not_found`; todos sin token y sin `call_service`. Vista previa con `from_version`, `to_version`, notas a 1500 caracteres (o el resumen), `backup` con la nota de la integración, aviso de firmware con `device_class: firmware`. Confirmar → un `call_service("update", "install", {"entity_id", "version": <to_version>, "backup"}, allow_dangerous=True)`; espera vencida (`TimeoutError`) → `status: running` y pista de `ha_list_updates` (FR-013)
- [X] T033 [US4] Tests `TestEncaminar`: entidades de plataforma `hassio` con `unique_id` de Core, OS y Supervisor → `use_dedicated_tool` con `sv_update_core`/`sv_update_os`/`sv_update_supervisor` y los argumentos de data-model (OS con `backup=true` → la nota); `<slug>_version_latest` → `sv_update_addon` con `slug`; la de Hermes → `self_update_not_supported`; un `entity_id` renombrado se encamina igual (se decide por el registro); ninguna emite token ni llama a `call_service` (FR-014)
- [X] T034 [US4] Tests de token y secretos de `ha_install_update`: `latest_version` cambiada entre vista previa y confirmación → `preview_outdated` sin `call_service`; centinela en las notas y en el error de Core → no aparece en la vista previa, la respuesta ni el log (FR-008, FR-013, FR-018)
- [X] T035 [US4] `hermes/src/hermes/tools/update_entities.py` con las tres tools según contracts/tools.md (con el comentario del porqué de `allow_dangerous=True` tras validar el token propio y de la espera, research R-11); `update_entities` en la familia `system_updates` (`tool_families.py` y su test de T002). T031–T034 en verde (FR-011…FR-014, FR-017)
- [X] T036 [US5] Registro en `tools/__init__.py` y `_annotations.py`: `ha_install_update` en `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD`, `ha_get_update_release_notes` en `_OPEN_WORLD`. Tests en `tests/test_tools_registration.py`: las tres con sus anotaciones; ninguna con la familia desactivada (FR-017)
- [X] T037 [US5] Test `TestHintUpdateInstall` en `tests/test_call_service_security.py`: `ha_call_service("update", "install", …)` sin token → la vista previa de siempre más `hint` con `ha_install_update`; con token → mismo comportamiento que en la 1.1.2; otro servicio → sin `hint`. Después, la `hint` en `tools/ha.py` (FR-015, FR-019)
- [X] T038 Tests en `tests/test_command_table.py`: `update/release_notes` `dedicated` con `ha_get_update_release_notes`, familia y CAP-064; ninguna entrada de la tabla con «spec 015» en el motivo; `ha_read_ws_command("update/release_notes", …)` → `use_dedicated_tool` sin llamada (FR-016)
- [X] T039 `command_table.py`: la entrada a mano; regenerar y comprobar que no cambia; anotarlo en el commit. T038 en verde (FR-016)
- [X] T040 [US5] Comprobación de FR-019 y SC-007: con `tool_families_disabled` con todas las familias de la 1.2.0, la lista y las anotaciones son las de la 1.1.2; la instantánea `esquemas_1_1_2.json` sin diferencias nuevas (FR-019)
- [X] T041 [US4] Banco: en `tests/banco/ha_config/configuration.yaml`, `template:` con una entidad `update` (`installed_version` desde un `input_text` de apoyo, `latest_version` fija, `specific_version: true`, `backup: true`, acción `install` que escribe la versión pedida —`specific_version` o la última— en el `input_text` y `backup` en un `input_boolean`), con comentario del porqué (research R-12). `tests/banco/test_banco_actualizaciones.py` con la base y el lector de la 010: `ha_list_updates` la ve con `supports` correcto; `ha_get_update_release_notes` → `supported: false` con el resumen; `ha_install_update` vista previa → el lector no ve cambios → confirmación → el lector ve la versión nueva y la entidad `off`; con `version` concreta y `backup=true` → el lector ve esa versión y el `input_boolean` encendido; limpieza al cerrar (FR-013, FR-021, SC-006)
- [X] T042 [US1] [US4] Guía completa: tema `updates` con las entidades `update`, el encaminamiento y la `hint` de `ha_call_service`; test en `tests/test_tools_guide.py` (FR-020)
- [X] T043 Inventario de cobertura del banco: `tests/banco/cobertura_015.py` con `PROBADAS_015 = {"ha_install_update"}` y `NO_EJECUTABLES_015` con `sv_check_for_updates`, `sv_update_core`, `sv_update_os` y `sv_update_supervisor` y el motivo («Supervisor real: el banco solo simula el Supervisor y reenvía a Core; prueba manual en la VM de la 014»), sumado al invariante de escrituras que haya en la rama (010/028) o con su propio `tests/test_banco_cobertura_015.py`: toda tool que modifica de la familia `system_updates` (por `readOnlyHint` del registro de producción) está en una de las dos partes; el plugin de `tests/banco/obligatorio.py` exige que `ha_install_update` se ejecute con éxito (FR-021)
- [X] T044 Documentación final: CHANGELOG (sección completa: 8 tools, familia, 8 entradas de la tabla, encaminamiento, `hint`, desviaciones de R-4 y R-9); `docs/HOJA-DE-RUTA.md`: la 015 → «hecha», con lo probado en el banco y la prueba real de las cuatro `sv_*` que modifican como pendiente manual en la VM de la 014 (quickstart.md, paso 3), y el punto «Actualizar Core, OS y Supervisor con vista previa útil» como resuelto; `README.md` y `README.es.md` sincronizados (tools nuevas por áreas y recuento si lo llevan); `hermes/DOCS.md`; `specs/008-cobertura-total/plan.md`: filas CAP-064 y CAP-080 de la matriz con las tools y los ficheros de test, sin cambiar las columnas que lee `_matriz_008` (sub-feature y vía), y los hallazgos de research R-13 (FR-022)
- [X] T045 Control negativo del tramo 3, anotando recuentos: (a) no encaminar la entidad de Core → cae; (b) decidir por `entity_id` en vez de por el registro → cae el del renombrado; (c) emitir token con `backup` sin soporte → cae; (d) no atar `_to_version` → cae; (e) tratar el `TimeoutError` como error → cae; (f) quitar la `hint` → cae; (g) sacar `ha_install_update` de `PROBADAS_015` → cae el inventario. Restaurar y comprobar verde
- [X] T046 Cierre del tramo 3: suite completa (los 6 conocidos), CI de la rama y banco en verde, revisión del diff (principio VIII, FR-021 de la 008), commit con los recuentos de T045

### Notas del tramo 3 (desviaciones y decisiones)

- **Línea base** (T030): 2549 passed, 65 skipped, 6 failed (los 6 de
  Windows), con los tramos 1 y 2 en la rama (`35741e7`). El banco de la 010
  corre en el CI de la rama (job `banco-core`).
- **D-1 (decisión del supervisor), criterio estricto**: la entidad de una
  app es la de Hermes solo si su slug (`<slug>_version_latest` del registro,
  plataforma `hassio`) es IGUAL al `slug` de `GET /addons/self/info`, leído
  una vez y guardado. No se usa `_es_hermes` (cualquier `*_hermes`, duda
  D-13) ni el HOSTNAME. Si no se puede leer: `self_check_unavailable` sin
  token, con cómo actualizar Hermes (fail-closed). `self_update_not_supported`
  dice que se haga desde la interfaz de HA o con la actualización automática
  del add-on. En `ha_list_updates`, `install_with: null` con nota en los dos
  casos. `sv_list_available_updates` (tramo 1) sigue con `_es_hermes`: es
  informativa y no emite token; queda como duda para el final.
- **Errores añadidos al contrato** (todos sin token): `install_not_supported`
  (Core exige `INSTALL` para `update.install`), `registry_unavailable` (sin
  registro no se sabe si es de `hassio`: fail-closed), `unsupported_entity`
  (entidad de `hassio` con un `unique_id` desconocido), `self_check_unavailable`
  (D-1), `versions_unavailable` y `core_error` (error de Core, redactado).
- **Versión sin `SPECIFIC_VERSION`**: T032 pedía mandar siempre
  `version: <to_version>`, pero Core rechaza cualquier `version` en una
  entidad que no la admite (`specific_version_not_supported`). Se manda sin
  ella; el token está atado a la última releída justo antes.
- **`version` de `ha_install_update`**: regla más ancha que la de las `sv_*`
  (`^[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}$`, sin `..`): el firmware lleva a veces
  `v` delante o guiones. Va en el cuerpo del servicio, no en una ruta.
- **Banco**: la entidad de plantilla escribe el backup en un segundo
  `input_text` (`banco_update_backup`, «si»/«no») en vez de en un
  `input_boolean`, para que `input_boolean.reload` (test de la 028) siga sin
  YAML que releer. Se prueban además el token atado a la versión (otra
  versión → `preview_outdated` sin efecto) y el rechazo sin token de
  `no_update_available`. `TOOLS_EXIGIDAS_DEL_JOB` suma `PROBADAS_015`.
- **Tabla**: `update/release_notes` a `dedicated`; regenerada con
  `scripts/inventario/generar_tabla.py`: idéntica byte a byte. Ninguna
  entrada «spec 015» (test nuevo).
- **Matriz de la 014**: `ha_install_update` → «banco de Core / ok».
- **Recuento de tools**: 239 en README, README.es y DOCS (la fila de la
  familia pasa a 8; la de DOCS se había quedado en 3).
- **Inventario de argumentos atados de la 033**
  (`tests/test_confirmation_args_inventory.py`): sigue sin estar en la rama.
  Al integrarlo: `ha_install_update` con `{"entity_id": atado, "version":
  atado, "backup": atado}` (más `_from_version`/`_to_version` dentro de la
  tool).
- **Control negativo (T045)**, con los tests de la 015, la tabla, el
  registro, la matriz y el inventario: (a) sin encaminar Core → 5 rojos;
  (b) decidir por `entity_id` → 1 (el del renombrado); (c) token con
  `backup` sin soporte → 1; (d) sin atar `_to_version` → 2; (e)
  `TimeoutError` como error → 1; (f) sin la `hint` → 1; (g) sin
  `ha_install_update` en `PROBADAS_015` → 3 (inventario y matriz); además
  (h) Hermes por sufijo `_hermes` → 1; (i) sin slug propio, no fail-closed
  → 2 subtests; (j) `update/release_notes` de vuelta a `deny` → 3 tests y 2
  subtests. Todo restaurado y en verde.

---

## Dependencias y paralelismo

- T001 antes de todo. T002 antes de T009. T003 y T004 en paralelo; T005 y T006
  después de T004 (usan la fixture). T007 tras T003/T004; T008 tras T005/T006.
  T009 antes de T011 (`TestDedicadas` necesita las tools registradas). T012 en
  paralelo con T013 y T014.
- Tramo 2: T018 y T019 antes de T020/T021; T020 antes de T023 (`TestDedicadas`); T027 en
  paralelo con T025/T026.
- Tramo 3: T031–T034 antes de T035; T036 antes de T039; T041 necesita T035 y
  T036; T043 tras T041.

## Fase 4: Convergencia

Añadida por la revisión independiente y `speckit-converge` sobre la punta de la
rama (067d330). Severidad entre corchetes. Cada arreglo con su test de
regresión y su control negativo (principio VII).

- [X] T047 [MEDIO] `sv_update_os` toma por suyo un job ajeno: si ya hay un `os_manager_update` sin terminar (lanzado desde la interfaz o por otra llamada), la vista previa emite token, la confirmación lanza `POST /os/update`, `_buscar_job` encuentra ese job en `/jobs/info` antes de que vuelva el rechazo del Supervisor (`JobConcurrency.REJECT`) y responde `status: running` con el `job_id` ajeno y el `to_version` de la vista previa; el rechazo solo queda en el log y el token se marca completado con éxito (comprobado con el Supervisor simulado). Arreglo mínimo: la vista previa lee `/jobs/info` y, con un job de ese nombre sin terminar, bloquea con `update_in_progress` sin token (fail-closed); y al confirmar se apuntan antes de lanzar los `uuid` de los jobs con ese nombre ya en curso y `_job_en_curso` los excluye. En el Supervisor no hace falta excluir (su `update` es `detach` y comparte la tarea en curso) per FR-009, FR-004, principio V (partial)
- [X] T048 [BAJO] Coherencia del criterio de Hermes (D-13) entre las tools de la familia: `sv_list_available_updates` marca como Hermes cualquier app `*_hermes` (`_es_hermes`) y dice «Hermes cannot update itself», mientras `ha_list_updates` y `ha_install_update` (slug exacto de `/addons/self/info`) mandan esa misma app a `sv_update_addon`, que la rechaza con `self_update_not_supported` (comprobado: encaminamiento sin salida para `<slug>_hermes` que no es Hermes). Solo afecta a la información (el sufijo bloquea de más, nunca de menos). Arreglo mínimo: sacar `_slug_propio` a un sitio común; en `_listar`, Hermes = slug exacto (si no se puede leer, caer a `_es_hermes`); y para una app con `_es_hermes(slug)` que no es la propia, en las tres tools `update_with`/`install_with` null con una nota honesta («`sv_update_addon` rechaza los slugs que terminan en `_hermes` (D-13); actualízala desde la interfaz de HA») en vez de remitir a una tool que la rechaza. Cambiar `_es_hermes` en `sv_update_addon` queda para la decisión de D-13 per FR-001, FR-014, principio V (contradicts)
- [X] T049 [BAJO] `ha_get_update_release_notes` recorta las notas por bytes UTF-8 crudos (`max_bytes - 4096`), pero lo que viaja es JSON: comillas, barras, saltos de línea y tabuladores se escapan y ocupan más. Con notas de terceros cargadas de escapes la respuesta pasa del tope (comprobado: 254 321 bytes con tope 131 072) y el guardián central la cambia por un error, así que no se ven las notas. Arreglo mínimo: recortar midiendo `len(json.dumps(texto, ensure_ascii=False).encode())` (búsqueda binaria sobre la longitud) o dejar el texto en `max_bytes // 2` per FR-012, FR-018 de la 008 (partial)
- [X] T050 [BAJO] El docstring de `tools/system_updates.py` promete que al log «nunca» va «el texto de un error», pero la tarea de fondo de OS y Supervisor registra `system_update_failed` con `detail` (el error del Supervisor, redactado y recortado). Alinear: quitar `detail` del log (basta `status` y `error_type`) o corregir el docstring para que diga lo que hace per FR-018, principio V (contradicts)
- [X] T051 [MEDIO, decisión del supervisor sobre el H5 de la revisión] `ha_call_service("update", "install", …)` permitía saltarse D-1 (Hermes se actualiza a sí mismo por Core, que llama al Supervisor como Core y burla su protección propia) y D-3 (Core sin comprobar la configuración). Arreglo fail-closed, solo para `update.install`, en la vista previa y en la confirmación: objetivo = lista explícita de `entity_id` (si no, `use_dedicated_tool` → `ha_install_update`); cada entidad por el registro (`comprobar_update_install`, que reutiliza el encaminamiento de `ha_install_update`); Hermes → `self_update_not_supported` (slug propio ilegible con alguna app de `hassio` → `self_check_unavailable`); Core/OS/Supervisor → `use_dedicated_tool` hacia su `sv_*`; `hassio` no reconocida → `unsupported_entity` (fail-closed, como en `ha_install_update`); el resto, igual que en la 1.1.2. `ha_call_service_response` ya rechazaba `update.install` (denylist, sin token): test de regresión. Banco: `test_call_service_update_install` (por área se rechaza sin tocar HA; con la entidad nombrada, token e instalación). Desviación aceptada por el supervisor: cambio de comportamiento de una tool de la 1.1.2 (esquema igual), en CHANGELOG, guía, descripción y `SECURITY.md` per D-1, D-3, FR-015

Notas de la convergencia:

- T047: el Supervisor y Core no tienen la carrera (Core devuelve su `job_id`
  o el error; `supervisor_update` es `detach` y la API comparte la tarea en
  curso). Solo el OS excluye los jobs previos; si no se pueden leer antes de
  lanzar, no se adopta ningún job (`started`).
- T048: `_es_hermes` (sufijo) sigue en `sv_update_addon` y en las tools de
  otras sub-features (009 `addons.py`, genéricas `generic_commands.py`, logs
  `system_logs.py`): fuera del alcance de la 015 (D-13).
