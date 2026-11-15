---

description: "Tareas de la sub-feature 022 — control de Core y del Supervisor (Hermes 1.2.0)"
---

# Tareas: control de Core y del Supervisor (022)

**Entrada**: `specs/022-control-de-core-y-supervisor/` (spec.md, plan.md,
research.md, data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `DummyMCP`, el
Supervisor simulado de la 013 (`tests/fixtures/supervisor_diagnostico.py`)
ampliado en `tests/fixtures/supervisor_control.py` para registrar método,
ruta, cuerpo y `timeout_seconds`, simular «Core no corre», jobs en curso,
cortes de conexión sin `status` y tiempos vencidos;
`structlog.testing.capture_logs`. Datos ficticios (`<slug>`,
`registro.example`, uuids, fechas y tamaños inventados, centinelas). Nada de
la instalación real. **Ningún rechazo puede producir una llamada que
escribe**: cada test de rechazo cuenta las llamadas `POST` del simulado.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" <python del .venv> -m pytest -q -p no:cacheprovider`.
Línea base al especificar (2026-11-15, punta `c4a57bf`): 2926 passed, 95
skipped, 6 failed (los 6 conocidos de Windows). Cada tramo anota su propia
línea base al empezar y termina con exactamente esos 6 fallos en local; la
referencia es el CI de Linux.

**Requisito previo (S-01)**: 011, 013, 014, 018 y 033 integradas (están en
`c4a57bf`): `sv_read_api`/`sv_call_api`, `SupervisorSimulado`, matriz de
pruebas, `estado` en `create_confirmation_token`, inventario de argumentos
atados. Si falta algo, el agente se detiene y lo anota.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 recuperar Core, US2 opciones de Core y del
Supervisor, US3 recargar, reiniciar y reparar el Supervisor, US4 aplicar
sugerencias, US5 el resto por la tabla, US6 nada de lo actual cambia.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado.

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **1** — control de Core y del Supervisor (CAP-084) | **T001–T016** | Familia `system_control` con `sv_start_core`, `sv_rebuild_core`, `sv_set_core_options`, `sv_reload_supervisor`, `sv_restart_supervisor`, `sv_repair_supervisor`, `sv_set_supervisor_options`; 7 `dedicated`, 2 `read` (estadísticas), 1 `confirm` (`/host/reload`); tema de guía (parte); CHANGELOG, DOCS, README y matriz de la 014 (parte) |
| **2** — sugerencias (CAP-087 escritura) y la tabla (CAP-087, 091, 092, 094) | **T017–T029** | Familia `resolution_fixes` con `sv_apply_resolution_suggestion`; 1 `dedicated` y 3 `confirm` (chequeos); tests de plugins, Docker, placas y hora; guarda de sugerencias reescrita; guía y documentación completas; ninguna «spec 022»; matriz de la 008 |

El tramo 2 necesita el tramo 1 integrado. Si el tramo 1 no cabe en el
contexto de un agente, se corta tras T009 + T012 (las siete tools con su
registro) y T010, T011, T013 y T015 pasan al principio del tramo 2; el
supervisor del programa lo decide.

---

## Tramo 1 — control de Core y del Supervisor (CAP-084)

### Preparación

- [x] T001 Línea base: comprobar el requisito previo (S-01), ejecutar la suite y anotar passed/skipped/failed y la punta; comprobar que `grep -c "spec 022" hermes/src/hermes/command_table.py` da 14
- [x] T002 [P] [US6] Tests en `tests/test_tool_families.py`: `system_control` existe, `desde="1.2.0"`, desactivable, módulos `("system_control",)`, `familia_de_modulo("system_control") == "system_control"`; en `tests/test_config_validation.py`, `tool_families_disabled: [system_control]` es válido. En rojo hasta T008 (FR-017)

### Tests de las tools (escritos antes, en rojo)

- [x] T003 [P] [US1] Fixture `tests/fixtures/supervisor_control.py` y tests en `tests/test_tools_system_control.py` (`TestStartCore`, `TestRebuildCore`, `TestOperacionesLargas` para start y rebuild): `sv_start_core` con Core parado (simulado: `/core/stats` responde el error de «not running») → vista previa con `core_state: "stopped"`, `version`, `interrupts`, `hermes` y token; con el token, un `POST /core/start` con `timeout_seconds=600`; Core en marcha → `already_running` sin token y sin `POST`; Core que pasa a en marcha entre vista previa y confirmación → `already_running` al confirmar y sin `POST`; `/core/stats` con otro error → `core_state: "unknown"` y token; escrituras sin validar → aviso, no bloqueo. `sv_rebuild_core`: vista previa con `safe_mode` explicado; `safe_mode` no booleano → `invalid_argument` sin llamar; token emitido con `safe_mode=true` y confirmado con `false` → token inválido sin `POST`; con escrituras sin validar (`check_restart_allowed_sync` → `False`) → `blocked` en la vista previa y, al confirmar, el motivo sin `POST`; con el token, `POST /core/rebuild` con `{"safe_mode": …}` y nunca `force`; tiempo vencido → `status: "started"` y `verify_with: "sv_get_core_info"`; error del Supervisor con un centinela → `error` sin el centinela (FR-001, FR-002, FR-008)
- [x] T004 [P] [US2] Tests `TestSetCoreOptions` en `tests/test_tools_system_control.py`: diferencia por clave con `/core/info`; `unchanged`; cada aviso de data-model (`boot=false`, `watchdog=false`, `backups_exclude_database=true`, `duplicate_log_file`, audio); `image`, `refresh_token`, `port`, `ssl` → `not_allowed` con `allowed` y `reason` sin llamar; clave desconocida, `{}`, `"boot": "no"`, `audio_input` de 129 caracteres → `invalid_argument` con `field` sin llamar; todo igual → `no_changes` sin token; con el token, `POST /core/options` con SOLO las claves que cambian; `options` distinto al confirmar → token inválido; valor actual cambiado entre vista previa y confirmación → rechazo de estado sin `POST` (FR-003)
- [x] T005 [P] [US3] Tests `TestReloadSupervisor`, `TestRestartSupervisor`, `TestRepairSupervisor` y `TestOperacionesLargas` (restart, repair) en `tests/test_tools_system_control.py`: `sv_reload_supervisor` → un `POST /supervisor/reload` sin token; `sv_restart_supervisor` → vista previa con `stops` (API del Supervisor y conexión con Core), `keeps_running` (Core y apps), `duration`, `hermes`; un job `done: false` (también como hijo) en `/jobs/info` → `jobs_in_progress` con sus nombres, sin token y sin `POST`, y lo mismo al confirmar si aparece después; `/jobs/info` que falla → `error` sin token; con el token, `POST /supervisor/restart`; corte de conexión sin `status` → `status: "started"` con `verify_with: "sv_get_supervisor_info"`; error con `status` 400 → `error` redactado. `sv_repair_supervisor`: vista previa con `steps`, `deletes`, `downloads` y `duration`; mismo rechazo de jobs; `POST /supervisor/repair` con `timeout_seconds=900`; vencido → `status: "started"` con `verify_with: "sv_get_resolution"` (FR-004, FR-005, FR-006, FR-008)
- [x] T006 [P] [US2] Tests `TestSetSupervisorOptions` en `tests/test_tools_system_control.py`: diferencia con `/supervisor/info`; validación (`timezone` `"Europe/Madrid"` vale y `"../x"`, `""`, 65 caracteres no; `country` `"ES"` vale y `"es"`, `"ESP"` no; `logging` fuera de la lista no; booleanos) → `invalid_argument` sin llamar; `channel`, `debug`, `debug_block`, `detect_blocking_io`, `feature_flags`, `addons_repositories`, `wait_boot` → `not_allowed` sin llamar; avisos de `auto_update=false`, `timezone`, `diagnostics=true`, `logging=debug`; `no_changes`; con el token, `POST /supervisor/options` con solo las claves que cambian; estado cambiado → rechazo sin `POST` (FR-007)
- [x] T007 [P] [US1] [US2] [US3] Tests `TestLog` en `tests/test_tools_system_control.py` con `capture_logs`: un evento `system_control_preview`/`_done`/`_rejected` por llamada con `tool`, `route`, `keys` (nombres) y `outcome`/`code`; nunca los valores de `timezone`, `country` ni `audio_*`, ni el texto de un error con centinela; respuestas por `redact_structure` (centinela bajo `password` en `/core/info` simulado → tapado) (FR-019)

### Implementación

- [x] T008 [US1] [US2] `hermes/src/hermes/tools/system_control.py` (parte de Core): `register(mcp, ha_client, *, response_max_bytes)`, ayudas `_vista_previa_opciones` y `_ejecutar_larga` (research R-7) con su porqué, `sv_start_core`, `sv_rebuild_core` (reutiliza `check_restart_allowed_sync` como `tools/supervisor.py`), `sv_set_core_options`, con docstrings en inglés según contracts/tools.md; familia `system_control` en `hermes/src/hermes/tool_families.py` con comentario (research R-1); registro en `hermes/src/hermes/tools/__init__.py` dentro de la comprobación de familia. T002, T003, T004 y la parte de Core de T007 en verde (FR-001…FR-003, FR-008, FR-017, FR-019)
- [x] T009 [US3] [US2] `tools/system_control.py` (parte del Supervisor): `_jobs_en_curso`, `sv_reload_supervisor`, `sv_restart_supervisor`, `sv_repair_supervisor`, `sv_set_supervisor_options`. T005, T006 y T007 en verde (FR-004…FR-008, FR-019)
- [x] T010 [US5] Tests en `tests/test_command_table.py` (`TestEntradasDeLa022`, parte 1): las 7 rutas de data-model a `dedicated` con su tool, familia `system_control` y `cap="CAP-084"`; `GET /core/stats` y `GET /supervisor/stats` `read` y `POST /host/reload` `confirm` (familia `generic_commands`, `cap="CAP-084"`) con su entrada «spec 022: porqué» en `_POR_LA_TABLA`; `POST /core/stop` y `/homeassistant/*` siguen `deny`. Tests en `tests/test_tools_control_tabla.py` (nuevo): `sv_call_api` sobre las 7 → `use_dedicated_tool` sin llamada y, con `system_control` desactivada, `family_disabled: true`; `sv_read_api("/core/stats")` y `("/supervisor/stats")` → un `GET` y respuesta redactada; `sv_call_api("POST", "/host/reload")` → vista previa y token, y con el token la llamada (FR-013)
- [x] T011 [US5] `hermes/src/hermes/command_table.py`: las 10 entradas de T010, una línea cada una, con motivo y comentario encima de las 3 por la tabla; las 7 dedicadas en `_DEDICADAS_INICIALES` de `scripts/inventario/generar_tabla.py`; ejecutar el generador y comprobar que la tabla no cambia (`git diff --exit-code`, salvo finales de línea); `grep -c "spec 022"` da 4. T010 en verde y `TestDedicadas` en verde (FR-013)
- [x] T012 [US6] Registro, anotaciones e invariantes: tests en `tests/test_tools_registration.py` (`TestControl022`): las 7 registradas por defecto y ninguna con la familia desactivada; hints de research R-10 (ninguna `readOnly`; `sv_rebuild_core`, `sv_set_core_options`, `sv_restart_supervisor`, `sv_repair_supervisor` destructivas; `sv_rebuild_core`, `sv_restart_supervisor`, `sv_repair_supervisor` no idempotentes; `sv_reload_supervisor` y `sv_repair_supervisor` de mundo abierto); SC-005 de la 011 en verde y recuentos actualizados. Después `hermes/src/hermes/tools/_annotations.py` (`_DESTRUCTIVE_EXACT`, `_NON_IDEMPOTENT_EXACT`, `_OPEN_WORLD`, con comentario). Filas de las 6 con token en `tests/test_confirmation_args_inventory.py` (`safe_mode` y `options` atados; las sin argumentos, vacías) y recuento del docstring; las 7 en `FUERA_DEL_BANCO` de `tests/banco/cobertura_escrituras.py` (motivo nuevo `_SV_CONTROL`: «controla Core o el Supervisor: el Supervisor del banco es un simulado que solo reenvía a Core y no sobreviviría; se prueba con simuladores y en la VM de la 014»); 7 filas `VM | pendiente` en la matriz de `docs/HOJA-DE-RUTA.md` y sus líneas en «Tandas de pruebas» de `docs/BANCO-SUPERVISOR.md` (tanda 1: las dos de opciones y la recarga; tanda 3: start, rebuild, restart y repair) (FR-017, FR-018, FR-021)
- [x] T013 [US1] [US2] [US3] Guía: tests en `tests/test_tools_guide.py` (`TestTemaSystemControl`: el tema nombra las 7 tools, qué corta cada una y cuánto, las listas cerradas, `jobs_in_progress`, `already_running`, el bloqueo del rebuild, las estadísticas y `/host/reload` por la tabla y la receta «Core no arranca»; alias `core_control`, `supervisor_control`; el índice lo nombra; `supervisor` remite a `system_control`); después, `hermes/src/hermes/tools/guide.py` (tema en español y lista de temas del docstring de `hermes_guide`) y la huella de `supervisor` en el test de huellas (FR-020)
- [x] T014 Control negativo del tramo 1, anotando recuentos: (a) aceptar `image` en `sv_set_core_options` → cae; (b) aceptar `channel` en `sv_set_supervisor_options` → cae; (c) quitar el bloqueo de escrituras sin validar del rebuild → cae; (d) no consultar `/jobs/info` antes de reiniciar → cae; (e) no comprobar `already_running` al confirmar → cae; (f) no pasar los valores actuales como `estado` → cae el de estado cambiado; (g) devolver `error` en vez de `started` al vencer el tiempo → cae; (h) dejar `/supervisor/restart` como `deny` → caen el de la tabla y el de la genérica; (i) registrar el valor de `timezone` en el evento → cae. Restaurar y comprobar verde
- [x] T015 Documentación del tramo 1: sección «Control de Core y del Supervisor» en `## [1.2.0] — <fecha de publicación>` de `hermes/CHANGELOG.md` (las siete tools, qué cortan, listas cerradas, familia nueva, estadísticas y `/host/reload` por la tabla, `/core/stop` y `channel` siguen cerrados, prueba en vivo pendiente); `hermes/DOCS.md`, familia `system_control` en la lista de `tool_families_disabled`; `docs/HOJA-DE-RUTA.md`, fila de la 022 en la tabla del programa «en curso (tramo 1 hecho)»; `README.md` y `README.es.md` sincronizados (recuento de tools según el registro y fila de la familia)
- [x] T016 Cierre del tramo 1: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII: nada de hostnames, IPs reales, slugs, rutas `C:\`, identificadores de modelos), commit con los recuentos de T014 y el resultado de la regeneración de T011

### Notas del tramo 1 (al implementarlo)

- **Línea base** (T001), tras traer `feat/cobertura-total` (016 y 019) sin
  conflictos: 3263 passed, 106 skipped, 6 failed (los 6 de Windows);
  `grep -c "spec 022"` = 14. Al cerrar: 4. Requisito previo S-01 presente.
- **T014, recuentos** (cada mutación con sus clases de test, restaurada y en
  verde): (a) 2 failed; (b) 1; (c) 1; (d) 9; (e) 1; (f) 2; (g) 3; (h) 4
  (tabla y genérica); (i) 2. Además: quitar `sv_rebuild_core` de
  `_NON_IDEMPOTENT_EXACT` → 2 failed; quitar `jobs_in_progress` y la línea del
  índice del tema → 2 failed.
- **T011**: el generador deja la tabla idéntica (salvo finales de línea).
- **Desviación (T012, R-10)**: `sv_start_core` y `sv_set_supervisor_options`
  se anuncian destructivas (R-10 las daba no destructivas). Piden token, y el
  invariante del proyecto «pide token ⇔ destructiva»
  (`test_every_tool_that_asks_for_a_token_says_it_is_destructive`) no admite
  excepciones; anunciar de más es el lado seguro. `sv_restart_core` (1.1.2)
  no se toca.
- **Desviación (rechazos al confirmar)**: `already_running` y
  `jobs_in_progress` al confirmar no gastan el token (caduca solo en 60 s) y
  no llaman a nada que escriba; el rebuild bloqueado sí lo cierra, como
  `sv_restart_core`.
- **Desviación (vista previa honesta)**: `sv_restart_supervisor` responde
  siempre `status: "started"` (también si el Supervisor contesta), porque
  esa respuesta solo dice que empezó a reiniciarse (decisión del supervisor
  del programa: no afirmar que acabó bien).
- **Desviación (invariantes no previstos en el plan)**: las ayudas comunes de
  `system_control` reciben la ruta como variable, así que se declaran en
  `LLAMADAS_DECLARADAS` de `tests/test_rutas_supervisor_rol.py` (todas caben
  en `manager`); `test_tres_rutas_a_read` de la 013 pasa de igualdad a
  inclusión con `_POR_LA_TABLA`, que ahora tiene también las de la 022; las
  instrucciones del servidor nombran el tema `system_control` solo con su
  familia activa (`@TEMA_CONTROL@`, como `mounts`). El tema `supervisor` no
  tiene huella en el test de huellas: no había nada que actualizar.
- **Desviación (TDD)**: los tests y el módulo se escribieron en la misma
  pasada; el rojo de cada comportamiento con riesgo está comprobado con los
  controles negativos de T014.

---

## Tramo 2 — sugerencias (CAP-087 escritura) y la tabla (CAP-087, 091, 092, 094)

### Preparación

- [x] T017 Línea base del tramo (suite, punta, `grep -c "spec 022"` = 4); tests en `tests/test_tool_families.py` y `tests/test_config_validation.py` para `resolution_fixes` (1.2.0, desactivable, módulo `resolution_fixes`), en rojo hasta T021 (FR-017)

### Tests (escritos antes, en rojo)

- [x] T018 [P] [US4] Fixture (ampliar `tests/fixtures/supervisor_control.py`: `/resolution/info` con sugerencias e issues de cada par de data-model, `/backups` con 4 completos y 1 parcial de fechas distintas, `/addons/<slug>/info`) y tests en `tests/test_tools_resolution_fixes.py` (`TestTraduccion`, `TestLog`): cada par con fixup de la tabla de data-model da su `effect`, `interrupts`, `duration`, `reversible` y token (un subtest por par: SC-003); `clear_full_backup` lista los 2 más antiguos de los 4 completos (nunca el parcial) y con 2 completos dice que no borrará nada; `execute_rebuild`/`system` lista los contenedores de las otras sugerencias `execute_rebuild`; contexto `addon` trae nombre y estado de la app; `also_auto_applied` lista las demás con `auto: true` y avisa; `issues` ligados; con el token, un `POST /resolution/suggestion/<uuid>` (timeout 900 s) y respuesta con `effect` y `verify_with`; error del fixup → `error` redactado; evento `resolution_fix_*` con `suggestion_type`, `context` y `outcome`, nunca `reference` (FR-009, FR-019)
- [x] T019 [P] [US4] Tests `TestRechazos` y `TestTokenYEstado` en `tests/test_tools_resolution_fixes.py`: uuid con forma inválida → `invalid_argument`; inexistente → `suggestion_not_found`; `execute_stop`, `execute_update`, `registry_login` y un par conocido sin fixup (`execute_reboot`/`addon`) → `no_fixup`; `type` o `context` que 2026.11.0 no conoce → `unknown_effect`; `adopt_data_disk` y `rename_data_disk` → `not_allowed`; contexto `addon` con el slug de Hermes (los cuatro formatos de `_es_hermes`), `execute_rebuild`/`system` con Hermes entre lo reconstruido y una autofix sobre Hermes → `targets_hermes`; todos sin token y sin `POST`. Token: otro `suggestion_uuid` → inválido; la sugerencia desaparece → `suggestion_not_found`; cambia `reference`, la lista de backups o la de autofixes → `suggestion_changed`; en los tres, sin `POST` (FR-010, FR-011)
- [x] T020 [P] [US4] [US6] `tests/test_tools_resolution.py`: `TestNuncaAplicaSugerencias` pasa a `TestSoloResolutionFixesAplica` (el detector AST se queda; la lista de hallazgos solo puede tener `resolution_fixes.py`; el caso positivo con un fichero temporal sigue); `sv_dismiss_resolution_suggestion` y `sv_get_resolution` no cambian (US6) (FR-012)

### Implementación

- [x] T021 [US4] `hermes/src/hermes/tools/resolution_fixes.py`: `_FIXUPS` (tabla de data-model, con la versión del Supervisor en el comentario), tipos y contextos de 2026.11.0, lecturas de detalle, rechazos (antes de emitir y otra vez al confirmar), `estado` del token, `_ejecutar_larga` (importada de `system_control` o movida a un módulo común si crea un ciclo), evento de log y docstring en inglés según contracts/tools.md; familia `resolution_fixes` en `tool_families.py` y registro en `tools/__init__.py`. T017, T018 y T019 en verde (FR-009…FR-011, FR-017, FR-019)
- [x] T022 [US4] `hermes/src/hermes/tools/resolution.py`: solo el docstring del módulo y de `sv_get_resolution`/`sv_dismiss_resolution_suggestion` («to apply one, use sv_apply_resolution_suggestion»); tema `diagnostics` de la guía con la misma idea y su huella en `tests/test_tools_guide.py`. T020 en verde (FR-012, FR-020)
- [x] T023 [US4] [US5] Tests en `tests/test_command_table.py` (`TestEntradasDeLa022`, parte 2) y después `command_table.py`: `POST /resolution/suggestion/{suggestion}` `dedicated` → `sv_apply_resolution_suggestion` (`resolution_fixes`, `cap="CAP-087"`); `POST /resolution/check/{check}/run`, `/options` y `POST /resolution/healthcheck` `confirm` con los motivos de data-model (el de healthcheck dice que puede aplicar los arreglos automáticos) y su «spec 022: porqué» en `_POR_LA_TABLA`; la dedicada en `_DEDICADAS_INICIALES`; regenerar sin cambios; `grep -c "spec 022"` = 0 (FR-013)
- [x] T024 [US5] Tests en `tests/test_tools_control_tabla.py` con la tabla real y el Supervisor simulado (`TestPorLaTabla`, `TestRegistroDocker`, `TestSigueCerrado`): `sv_call_api("POST", "/resolution/suggestion/<uuid>")` → `use_dedicated_tool` y con `resolution_fixes` desactivada `family_disabled: true`; los tres chequeos → vista previa, token y llamada; CAP-091: `GET /{dns,audio,multicast,observer,cli}/{info,stats}` por `sv_read_api` y cada `POST` de plugins de la tabla (`update`, `restart`, `reset`, `reload`, `options`, `profile`, `volume`, `mute`, `default`) por `sv_call_api` con vista previa y token; CAP-094: `GET /os/boards/{green,yellow,raspberrypi/firmware,<board>}` y los tres `POST` y `POST /time/options`; CAP-092: `GET /docker/registries`, `POST /docker/options`, `DELETE /docker/registries/registro.example` y `POST /docker/registries` con `{"registro.example": {"username": "u", "password": <centinela>}}` → el centinela no está en la vista previa, ni en los eventos capturados, ni en el `error` cuando el simulado devuelve un 400 que repite el cuerpo; `POST /core/stop`, `POST /homeassistant/stop` → `command_denied` sin llamada; `POST /supervisor/options` con `channel` → `use_dedicated_tool` y la tool lo rechaza con `not_allowed`. Si algo de CAP-091/092/094 falla, es la tabla o la genérica de la 011: se arregla con su control negativo y se anota (FR-014, FR-015, FR-016)
- [x] T025 [US6] Registro, anotaciones e invariantes de `sv_apply_resolution_suggestion`: en `tests/test_tools_registration.py`, registrada por defecto, no con `resolution_fixes` desactivada, destructiva, no idempotente, de mundo abierto; SC-005 de la 011; `_annotations.py`; fila en `tests/test_confirmation_args_inventory.py` (`suggestion_uuid` atado) y recuento; `FUERA_DEL_BANCO` (`_SV_AVISOS`); fila `VM | pendiente` en la matriz y su línea en la tanda 3 de `docs/BANCO-SUPERVISOR.md` (sugerencia provocada) (FR-017, FR-018, FR-021)
- [x] T026 [US4] [US5] Guía: tests en `tests/test_tools_guide.py` y después `guide.py`: el tema `system_control` añade `sv_apply_resolution_suggestion` (traducción, rechazos, autofixes), los chequeos y el healthcheck por la tabla, plugins, Docker (con el aviso de que DNS y opciones de Docker pueden dejar sin red a las apps), placas y NTP; alias `suggestions`, `fixups`; `hermes_guide(topic="generic_commands", search="resolution")` lista los chequeos como `confirm` (FR-020)
- [x] T027 Documentación final: completar la sección de la 022 en el CHANGELOG (aplicar sugerencias y el cambio de política de la 1.1.x, chequeos por la tabla, CAP-091/092/094 sin cambios y probadas); `docs/HOJA-DE-RUTA.md`, fila de la 022 «hecha» con el resumen; `README.md` y `README.es.md` sincronizados (fila de Diagnostics y la sección de seguridad ya no dicen «never applied»; recuento; familia `resolution_fixes`); `hermes/DOCS.md`, familia `resolution_fixes` (`SECURITY.md` no menciona las sugerencias: comprobado al especificar, no se toca); filas CAP-084, CAP-087, CAP-091, CAP-092 y CAP-094 de la matriz de `specs/008-cobertura-total/plan.md` con tools, rutas de la tabla y ficheros de test, sin cambiar sub-feature ni vía (FR-022)
- [x] T028 Control negativo del tramo 2, anotando recuentos: (a) quitar `no_fixup` (dejar pasar `execute_stop`) → cae; (b) quitar `targets_hermes` → caen sus subtests; (c) no repetir los rechazos al confirmar → cae; (d) no pasar la lista de backups como `estado` → cae `suggestion_changed`; (e) traducir mal un par (`clear_full_backup` como reversible) → cae su subtest; (f) permitir `adopt_data_disk` → cae; (g) añadir un `POST /resolution/suggestion/` en `resolution.py` → cae la guarda; (h) dejar la contraseña del registro fuera de las claves sensibles (o quitar el ocultado) → cae `TestRegistroDocker`; (i) dejar un chequeo como `deny` → caen el de la tabla y el de la genérica. Restaurar y comprobar verde
- [x] T029 Cierre del tramo 2: suite completa (los 6 fallos conocidos y ninguno más), `grep -c "spec 022" hermes/src/hermes/command_table.py` = 0, regeneración sin cambios, revisión del diff (principio VIII), commit con los recuentos de T028

### Notas del tramo 2 (al implementarlo)

- **Línea base** (T017), punta `199917b`: 3323 passed, 106 skipped, 6 failed
  (los 6 de Windows); `grep -c "spec 022"` = 4. Al cerrar: 0. Suite final:
  3368 passed, 106 skipped, los mismos 6 failed.
- **T028, recuentos** (cada mutación restaurada y en verde): (a) 5 failed
  (los subtests de `test_sin_fixup` y el de log); (b) 5 (subtests de
  `test_apunta_a_hermes` y `test_rechazos_al_confirmar`); (c) 2; (d) 1; (e) 2;
  (f) 1; (g) 1 (la guarda); (h) 1 (`test_vista_previa_y_log`; el error ya lo
  tapa `redact_secrets`); (i) 3 (tabla, genérica y la regla de la clase A).
- **T023**: el generador deja la tabla idéntica (salvo finales de línea).
- **Decisión del supervisor (identificar a Hermes)**: Hermes se reconoce por
  el slug EXACTO de `GET /addons/self/info`, nunca por `_es_hermes` (que
  acepta el sufijo `_hermes`). T019 pedía «los cuatro formatos de
  `_es_hermes`»: en su lugar, el slug exacto en los tres caminos (contexto
  `addon`, contenedores de `execute_rebuild`/`system` y arreglos
  automáticos), y un test de que otra app `<x>_hermes` SÍ recibe token. Si
  `/addons/self/info` falla cuando hay una app en juego, no hay token
  (fail-closed).
- **Desviación (rechazos al confirmar)**: como en el tramo 1, un rechazo al
  confirmar (`targets_hermes`, `suggestion_not_found`, `suggestion_changed`…)
  no gasta el token (caduca solo) y no llama a nada que escriba.
- **Desviación (`_ejecutar_larga`)**: es un cierre dentro de `register` de
  `system_control`; `resolution_fixes` importa solo `_es_corte` y `_detalle`
  y hace su propio `POST`, con la ruta literal en la llamada para que la
  guarda AST de `test_tools_resolution.py` la vea.
- **Desviación (invariantes no previstos)**: la ayuda `leer` de
  `resolution_fixes` recibe la ruta como variable: declarada en
  `LLAMADAS_DECLARADAS` de `tests/test_rutas_supervisor_rol.py`.
- **Arreglo de paso**: el tramo 1 dejó texto con mojibake («estadÃ­sticas»)
  en `tests/test_command_table.py` y en la fila de la 022 de
  `docs/HOJA-DE-RUTA.md`; corregido.
- **Desviación (TDD)**: tests y módulo en la misma pasada; el rojo de cada
  comportamiento con riesgo está comprobado con los controles de T028.

---

## Dependencias

- Tramo 1: T001 → T002…T007 (en paralelo) → T008 → T009 → T012 (registro: sin él, `TestDedicadas` no encuentra las tools) → T010 → T011 → T013; T014, T015 y T016 al final.
- Tramo 2 (tras el tramo 1): T017 → T018…T020 en paralelo → T021 → T022 → T025 → T023 → T024 → T026; T027, T028 y T029 al final.

## Paralelismo

- Tramo 1: T003, T004, T005, T006 y T007 (clases de test distintas del mismo fichero: escribirlas en orden si un solo agente; en paralelo solo si van a ficheros distintos).
- Tramo 2: T018, T019 y T020.

## Estrategia

MVP = tramo 1: recuperar Core sin la interfaz y controlar el Supervisor, que
es la parte de prioridad media de CAP-084. El tramo 2 añade aplicar
sugerencias con su efecto traducido y deja probado lo que va por la tabla.
Todo sale en la 1.2.0 con el resto del programa; la prueba en vivo queda para
la VM de la 014.

## Fase 3: Convergencia

- [x] T030 MEDIO — Corregir la traducción de `clear_port_config`/`addon` en `_FIXUPS` de `hermes/src/hermes/tools/resolution_fixes.py`: el fixup del Supervisor 2026.11.0 (`app_clear_port_config.py`) quita el mapeo del puerto y llama a `app.start()`, que ARRANCA la app si estaba parada y no reinicia la que ya corre (el cambio de puerto no se aplica hasta su próximo reinicio); la vista previa dice «the app restarts if it is running». Test por subtest de `TestTraduccion` con control negativo per FR-009 (contradicts)
- [x] T031 MEDIO — En la vista previa de `clear_full_backup`/`system`, decir que cada backup se borra de TODAS sus ubicaciones (local, montajes de red y la carpeta de copias en la nube: `BackupManager.remove` sin `locations`) e incluir `locations` en cada elemento de `details.backups_to_delete` (y en el texto del efecto y la guía); test con un backup en dos ubicaciones per FR-009 (partial)
- [x] T032 BAJO — `_es_corte` (`hermes/src/hermes/tools/system_control.py`) trata como corte cualquier `HAConnectionError` sin `status` que no empiece por «Supervisor error:», también «Cliente HTTP de HA no inicializado.», cuando la petición ni salió: la respuesta dice `status: "started"` y «The request was sent». Distinguir ese caso (error sin token gastado o nota honesta) en `system_control` y `resolution_fixes`; test con control negativo per FR-008 (contradicts)
- [x] T033 BAJO — El aviso de `also_auto_applied` (`resolution_fixes.py`) y la guía dan la lista por completa, pero `healthcheck()` ejecuta antes `check_system()`, que puede crear sugerencias automáticas nuevas que el Supervisor aplica en la misma llamada; decir que la lista es la de ahora y que los chequeos pueden añadir otras per FR-009 (partial)
- [x] T034 BAJO — Completar los avisos de `sv_set_supervisor_options` (`_avisos_supervisor`) y su descripción: `auto_update=false` con un Supervisor más nuevo marca la instalación como no soportada (`supervisor_version`) y bloquea también OS, plugins y tienda; `auto_update=true` con versión nueva hace que el Supervisor se actualice y reinicie solo (Hermes pierde la conexión un rato); `diagnostics` cambia también los diagnósticos del OS Agent per FR-007 (partial)
- [x] T035 BAJO — `create_full_backup`/`system` dice `interrupts: "nothing (uses disk space)"`, pero `do_backup_full` para durante la copia las apps con `backup: cold`; decirlo en `interrupts` per FR-009 (partial)

Notas de la convergencia:

- T031: `/backups` del Supervisor 2026.11.0 no enseña la carpeta
  `.cloud_backup` (`Backup.locations` la omite si hay otra ubicación y
  `_list_backups` omite los backups que solo están ahí), pero el fixup la
  cuenta y la borra. Es una carpeta del host para las subidas a Home Assistant
  Cloud, no una copia fuera de casa; las copias ya subidas a la nube no las
  borra el Supervisor. La vista previa lo avisa siempre y marca como «fuera
  del host» solo los montajes de red.
- T032: `HAConnectionError` gana `sent` (`False` = la petición no salió); el
  cliente lo pone en sus errores de «no inicializado». Además, una conexión
  que no se establece (`aiohttp.ClientConnectorError`) tampoco es un corte.
- T035: la API del Supervisor no expone el modo de backup de cada app
  (`backup_mode` no sale en `/addons/{slug}/info`): la vista previa avisa sin
  poder listarlas.
