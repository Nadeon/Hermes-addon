---

description: "Tareas de la sub-feature 027 — plataforma y deprecaciones (Hermes 1.2.0)"
---

# Tareas: plataforma y deprecaciones (027)

**Entrada**: `specs/027-plataforma-y-deprecaciones/` (spec.md, plan.md,
research.md, data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Los
tests que fijan un comportamiento que ya existe (T008, parte de T014) pasan a
la primera; para ellos el control negativo es lo que demuestra que sirven.
Estilo de los existentes: `unittest.IsolatedAsyncioTestCase`,
`CONFIRMATIONS_DIR` en un `tempfile.TemporaryDirectory`, `DummyMCP`,
`_real_registry` de `tests/test_tools_registration.py`, `AsyncMock` de
`ws_send` y `sv_request`, `structlog.testing.capture_logs`. Datos ficticios
(`<slug>`, `<uuid>`, `light.salon`, `centinela-027`). Nada de la instalación
real ni de las tools MCP de Hermes; nada del código de HA o del Supervisor se
importa ni se ejecuta (las formas esperadas se copian en el test con el
fichero de origen en un comentario).

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" <python del .venv> -m pytest -q -p no:cacheprovider`.
Línea base en Windows al especificar (2026-11-14, punta `7870e5b`, con la 011
hasta su tramo 3 y sin la 009 ni la 010): 2139 passed, 17 skipped, 6 failed
(los 6 conocidos). T001 la vuelve a tomar tras integrar las dependencias. Cada
tramo termina con exactamente esos 6 fallos en local; la referencia es el CI
de Linux. Tras integrar `feat/cobertura-total` (009, 010, 011, 028 y 014) al
empezar el tramo A: 2357 passed, 65 skipped, 6 failed; al cerrarlo: 2409
passed, 65 skipped, 6 failed (los mismos). Registro por defecto: 221 tools,
igual antes y después del tramo. Tramo B: al empezar, 2409 passed, 65
skipped, 6 failed; al cerrarlo, 2429 passed, 65 skipped, 6 failed (los mismos
6); tabla regenerada sin cambios.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 jobs, US2 deprecaciones, US3 plataforma del
Supervisor, US4 apps, US5 documentación para quien mantiene Hermes.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado (uno o varios commits; el tramo no se cierra con la suite en rojo).

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **A** — código y tests | **T001–T016** | `child_job_errors` y `child_errors` en `sv_get_job_status` con su descripción, contados en `success` y en el sondeo del safety backup (D-1); `command_removed_in_ha` en `ha_remove_device_from_config_entry`; `supervisor_platform.py` cableado en el arranque; tests de deprecaciones (lo deprecado sigue, forma de los dispositivos de 2027.8/2027.10, CIMD por defecto) y guardas del SDK; tabla y lista de tools sin cambios |
| **B** — textos, traducciones y documentación | **T017–T027** | `translations/en.yaml` y `es.yaml`; descripciones de las tools de apps; guía (jobs y apps); `DOCS.md` y README; hoja de ruta (deprecaciones, CIMD, `outputSchema` y vía nativa, socket y `/v2`, estado de la 027); CHANGELOG; matriz de la 008 |

B no depende del código de A salvo para citar sus tests en la documentación
(T024–T026); si B empieza antes de cerrar A, deja esas citas para el final.

---

## Tramo A — código y tests (US1, US2, US3, US5)

### Preparación

- [x] T001 Integrar en la rama lo que falta de las dependencias (S-01; plan, «Dependencias y orden»): la 009 (entrada `## [1.2.0]` y versión 1.2.0), la 010 (banco) y la 011 completa, por merge desde `feat/cobertura-total` o desde sus ramas según lo que esté integrado; resolver conflictos sin cambiar comportamiento. Ejecutar la suite y anotar la línea base en el mensaje del commit, y guardar en el commit el número de tools registradas con la configuración por defecto (para T016). Si la 010 no está disponible, seguir: la 027 no añade pruebas de banco

### Jobs del Supervisor (US1)

- [x] T002 [P] [US1] Tests en `tests/test_supervisor_jobs.py` (nuevo), clase `TestChildJobErrors`, de `child_job_errors` según data-model: sin `child_jobs` → `([], False)`; un hijo con un error → `[{job, message}]`; tres niveles anidados en orden de profundidad; error sin `message` → `"unknown error"`; mensaje de 2000 caracteres → 500; centinela `token=centinela-027` tapado; `child_jobs` que no es lista, entradas que no son objetos y `errors` que no es lista → ignorados sin inventar nada; 25 errores → 20 y `True`; 7 niveles → se para en 5 y `True`; `name` que no es texto → `job: null`; y `job_errors` con la misma entrada sigue dando solo los del nivel superior (FR-002, FR-016)
- [x] T003 [US1] `hermes/src/hermes/supervisor_jobs.py`: `CHILD_ERRORS_MAX = 20`, `CHILD_JOBS_MAX_DEPTH = 5` y `child_job_errors(data)` con recorrido iterativo (pila) y comentario del porqué (research R-1: los errores de un sub-job no suben al padre). `job_errors` sin cambios. T002 en verde. **Control negativo**: devolver siempre `([], False)` → T002 en rojo; anotarlo en el test y en el commit (FR-002)
- [x] T004 [P] [US1] Tests en `tests/test_tools_supervisor.py`, clase `TestJobStatusSubJobs`, con el `MockHAClient` del fichero: job terminado sin errores propios y con un error en un sub-job → `success: false` (D-1), `errors: []` y `child_errors` con el sub-job, y el seguimiento local lo marca `failed`; job con error propio → `success: false` como antes; job sin `child_jobs` → `child_errors: []`, `success: true` y el resto de campos idénticos a la respuesta actual; job en curso → `success: null`; recorte → `child_errors_truncated: true` y `success: false` (y ausente si no hay recorte); centinela tapado; y la descripción contiene: que `done` es `true` también al fallar, que cualquier entrada en `errors` da `success: false`, que el Supervisor no distingue avisos de fatales, que los errores de sub-jobs van en `child_errors` y también dan `success: false`, y `sv_get_backup`. Los tests existentes de `sv_get_job_status` no se tocan (FR-001, FR-002, SC-002)
- [x] T005 [US1] `hermes/src/hermes/tools/backups.py`, `sv_get_job_status`: añadir `child_errors` (y `child_errors_truncated`) con `child_job_errors`, y contarlos en `success` y en el seguimiento local (D-1, arreglo); nueva descripción según contracts/tools.md, en el idioma de la actual. T004 en verde. **Control negativo**: quitar la línea que añade `child_errors` → T004 en rojo; calcular `success` sin los sub-jobs → T004 en rojo; anotarlo (FR-001, FR-002)
- [x] T005a [P] [US1] Tests en `tests/test_supervisor_jobs.py`, clase `TestSondeoSubJobs`, de `fs_write._evaluar_job` y del camino completo de `maybe_trigger_safety_backup` con un job pendiente: job terminado sin errores propios y con un error en un sub-job → `("fallo", ["<sub-job>: <mensaje>"])` y la escritura se rechaza con `safety_backup_job_failed` (sin marca de backup correcto); recorte → fallo con la línea del recorte; sin sub-jobs ni errores → `("ok", [])` como antes; centinela tapado en el mensaje (FR-017, D-1)
- [x] T005b [US1] `hermes/src/hermes/fs_write.py`, `_evaluar_job`: sumar los errores de `child_job_errors` (y el recorte) a los del job, con comentario del porqué (principio III: no se escribe sin un backup válido). `safety_retention.py` sin cambios. T005a en verde. **Control negativo**: no mirar los sub-jobs → T005a en rojo; anotarlo (FR-017)

### Deprecaciones (US2)

- [x] T006 [P] [US2] Tests en `tests/test_tools_registry_device.py`, clase `TestComandoRetiradoEnHA`: al confirmar con un token válido, `ws_send` de `config/device_registry/remove_config_entry` lanza `HAConnectionError(code="unknown_command")` → respuesta `command_removed_in_ha` con `command`, `replacement: "ha_remove_device"` y `detail`; `ws_send` se llamó una sola vez con ese comando (nunca con `config/device_registry/remove`); el mismo token ya no sirve (gastado como fallido); `HAConnectionError` con otro código, o con el mismo texto y `code=None`, da `{"error": "<texto>"}` como hoy; el primer paso no cambia; la descripción de la tool nombra `command_removed_in_ha` y `ha_remove_device` (FR-009)
- [x] T007 [US2] `hermes/src/hermes/tools/registry_device.py`, `ha_remove_device_from_config_entry`: en el `except HAConnectionError` del segundo paso, si `exc.code == "unknown_command"`, completar el token con `success=False, error="command_removed_in_ha"` y devolver el error de data-model; el log `ha_remove_device_from_config_entry_ws_error` lleva también `code`. La descripción de la tool (apartado de lo que devuelve) añade `command_removed_in_ha` en el mismo commit (principio V). Comentario del porqué (research R-4: no se reintenta con otro comando porque el token se dio para este efecto). T006 en verde. **Control negativo**: quitar la comprobación del código → T006 en rojo; anotarlo (FR-009)
- [x] T008 [P] [US2] Tests en `tests/test_deprecaciones.py` (nuevo): `TestDeprecadasSiguen` con `_real_registry()` y la configuración por defecto: los cuatro `ha_hacs_*` y `ha_remove_device_from_config_entry` registrados, con sus argumentos y sus anotaciones iguales a las de hoy (copiadas en el test: `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint` y `title`); las descripciones de los alias citan la 1.3.0 y su sustituta; la de la tool deprecada, 2027.9 y `ha_remove_device`. `TestDispositivosSinCamposDeprecados`: con dispositivos sin `config_entries`, `config_entries_subentries` ni `primary_config_entry`, la vista previa de `ha_delete_config_entry` cuenta los mismos dispositivos que con los campos, y el plan de `ha_remove_device` con HA anterior a 2026.9 elige la misma entrada (por `config_entry_id`); ningún `.py` de `hermes/src` contiene `primary_config_entry` ni `config_entries_subentries`. `TestCimdPorDefecto`: `options.oauth_cimd_allowed_hosts` de `hermes/config.yaml` es `[]` y la configuración cargada sin la variable de entorno da `[]` (FR-003, FR-008, FR-010)
- [x] T009 [US2] **Controles negativos** de T008 (pasan a la primera porque fijan lo que ya existe): cambiar un momento `device_config_entries` para que ignore `config_entry_id` → `TestDispositivosSinCamposDeprecados` en rojo; cambiar la anotación copiada de un alias → `TestDeprecadasSiguen` en rojo; poner `["claude.ai"]` como valor por defecto en `config.yaml` → `TestCimdPorDefecto` en rojo. Restaurar y anotar en el test y en el commit (FR-016)

### Plataforma del Supervisor (US3)

- [x] T010 [P] [US3] Tests en `tests/test_supervisor_platform.py` (nuevo): `socket_ofrecido` con la variable ausente, vacía, con espacios y con una ruta; `api_v2_activada` con `{"feature_flags": {"supervisor_v2_api": true}}`, `false`, sin la clave, sin `feature_flags`, `feature_flags` que no es objeto, y algo que no es objeto (data-model: `true`, `false`, `false`, `false`, `null`, `null`); `comprobar_plataforma` con `sv_request` simulado en las cuatro combinaciones: un evento `supervisor_platform` (info) con los tres campos y un aviso por cada cosa detectada, ninguno si no hay nada; `sv_request` llamado una sola vez con `("GET", "/supervisor/info")` y nunca con una ruta que empiece por `/v2`; `HAConnectionError`, una excepción cualquiera, una respuesta lenta (tope bajado en el test) y una respuesta que no es objeto → `api_v2_enabled: null`, evento `supervisor_platform_check_failed` (debug) con su `reason` y sin el texto del error, y la función no lanza; `asyncio.CancelledError` sí se propaga; con `SUPERVISOR_SOCKET=/run/centinela-027.sock`, el centinela no aparece en ningún evento; la URL base del cliente no cambia (FR-011, SC-003, SC-005)
- [x] T011 [US3] `hermes/src/hermes/supervisor_platform.py` (nuevo) según plan y data-model, con docstring en español que cite research R-2 y R-3 (por qué detectar sin usar). T010 en verde. **Control negativo**: tratar un fallo de lectura como `api_v2_enabled: False` → T010 en rojo; quitar el `wait_for` → el caso lento en rojo; anotarlo (FR-011)
- [x] T012 [P] [US3] Tests en `tests/test_main_wiring.py`, `TestArranqueComprobarPlataforma` (o funciones sueltas como el resto del fichero): el código de `_boot` llama a `comprobar_plataforma(ha_client, os.environ)` después de `_connect_ha_ws` y antes de `_build_mcp` (por posición en el código fuente, como los tests de cableado existentes), y fuera de cualquier `try` que pueda abortar el arranque (FR-011)
- [x] T013 [US3] `hermes/src/hermes/__main__.py`: la llamada tras el paso 8, con comentario del porqué (preparar sin activar; la función nunca lanza). T012 en verde (FR-011)

### SDK y `outputSchema` (US5)

- [x] T014 [P] [US5] Tests en `tests/test_sdk_deprecaciones.py` (nuevo): `TestSinDeprecacionesDelSdk`: con `warnings.catch_warnings(record=True)` y `simplefilter("always")`, importar cada módulo de `hermes` (salvo `__main__`), construir el servidor con `_build_mcp` de `__main__` y la configuración de prueba de `tests/test_main_wiring.py`, listar las tools y llamar a `ping`; ningún aviso `MCPDeprecationWarning` (de `mcp.shared.exceptions`) ni `DeprecationWarning`/`PendingDeprecationWarning` con fichero de origen en `mcp`, `mcp_types` o `hermes`; ningún `.py` de `hermes/src` contiene `SUPPORTED_PROTOCOL_VERSIONS`. `TestOutputSchemaDeclarado`: las tools con `outputSchema` son exactamente `{"ping", "hermes_guide"}`. `TestTopeDelSdk`: la línea de `mcp` de `hermes/requirements.txt` tiene `<3` (FR-004, FR-005)
- [x] T015 [US5] **Control negativo** de T014: emitir un `MCPDeprecationWarning` en `register` de `tools/ping.py` → `TestSinDeprecacionesDelSdk` en rojo; cambiar `ping` a `-> object` → `TestOutputSchemaDeclarado` en rojo. Restaurar y anotar. Si T014 encuentra un aviso real, corregir el uso en Hermes en este tramo y anotarlo (FR-005)

### Cierre del tramo A

- [x] T016 Cierre: con la configuración por defecto se registran las mismas tools que en T001 (mismo número y nombres; los tests de registro y de esquemas de la 1.1.2 sin tocar); regenerar la tabla con `scripts/inventario/generar_tabla.py` y comprobar `git diff --exit-code hermes/src/hermes/command_table.py`; suite con exactamente los 6 fallos conocidos; revisión del diff buscando datos personales; commit(s) del tramo con los controles negativos de T003, T005, T005b, T007, T009, T011 y T015 en el mensaje (FR-014, FR-016, SC-001, SC-006, SC-007)

---

## Tramo B — textos, traducciones y documentación (US1, US4, US5)

### Traducciones (US4)

- [x] T017 [P] [US4] Tests en `tests/test_translations.py` (nuevo): existen `hermes/translations/en.yaml` y `es.yaml`; cada uno es un objeto con solo `configuration` (y, si acaso, `network`); sus claves son exactamente las de `schema` de `hermes/config.yaml`; cada entrada tiene `name` y `description` de texto no vacío y nada más que `name`, `description` y `fields` (forma de `SCHEMA_TRANSLATION_CONFIGURATION` de `supervisor/apps/validate.py` 2026.11.0, copiada en un comentario); ningún texto contiene «add-on» ni «addon» sin distinguir mayúsculas; ninguno contiene una IP, un hostname que no sea un marcador (`homeassistant.tailXXXX.ts.net`, `claude.ai`) ni una ruta `C:\` (FR-006, FR-016, SC-004)
- [x] T018 [US4] Crear `hermes/translations/en.yaml` (inglés) y `es.yaml` (español) con las 31 opciones, textos derivados de la tabla de opciones de `hermes/DOCS.md` y «app» donde hablen del objeto. T017 en verde. **Control negativo**: borrar una opción de `es.yaml` → T017 en rojo; anotarlo (FR-006)

### Descripciones y guía (US1, US4)

- [x] T019 [P] [US4] Tests en `tests/test_tools_supervisor.py`, clase `TestTerminologiaApps`: la descripción de cada una de las doce tools de `tools/addons.py` contiene «app»; los nombres y argumentos siguen siendo los del fixture `tests/fixtures/esquemas_1_1_2.json` (el test de esquemas existente lo cubre; aquí solo se comprueba que las doce están en él) (FR-007)
- [x] T020 [US4] `hermes/src/hermes/tools/addons.py`: descripciones con «app (add-on)» en la primera mención y «app» donde hablen del objeto; sin tocar nombres, argumentos ni lógica. T019 en verde (FR-007)
- [x] T021 [P] [US1] [US4] Tests en `tests/test_tools_guide.py`: `TestGuiaJobs`: el tema `backups`, el tema `supervisor` y las instrucciones del servidor dicen que cualquier entrada en `errors` da `success: false` y nombran `child_errors`; `TestGuiaApps`: el título del tema `supervisor` y el apartado 4 de las instrucciones dicen «apps (add-ons)», y el tema sigue nombrando las doce tools de apps (FR-001, FR-007)
- [x] T022 [US1] [US4] `hermes/src/hermes/tools/guide.py`: instrucciones del servidor (apartado 4) y temas `supervisor` y `backups` según contracts/tools.md. T021 en verde; los tests de guía existentes siguen pasando (tamaño de las instrucciones incluido, si lo hay) (FR-001, FR-007)

### Documentación (US4, US5)

- [x] T023 [US4] `hermes/DOCS.md`, `README.md` y `README.es.md`: en las descripciones de opciones, «app» donde dicen «add-on» hablando del objeto (no en el nombre del repositorio ni en los enlaces) y una línea sobre las traducciones de la página de configuración; los dos README sincronizados (FR-007, FR-015)
- [x] T024 [US5] `docs/HOJA-DE-RUTA.md`: tabla «Deprecaciones con fecha» según research R-8, con los tests de A; hosts CIMD conocidos y cómo averiguar otro (research R-7) junto a la entrada de `oauth_cimd_allowed_hosts`; resumen de `outputSchema` y de la vía nativa de MCP con la recomendación (research R-6); en «1.3.0 y posteriores», apartado del socket Unix y la `/v2` con los pasos de research R-2 y la tabla de rutas de research R-3, y la nota de que la deriva solo vigila la V1; fecha de retirada de los alias (1.3.0) y de la tool deprecada (como tarde antes de HA 2027.9, D-08); estado de la 027 en la tabla del programa («hecha», con lo que hace) y los puntos de la 027 en la lista de lo que ahora es del programa (FR-003, FR-004, FR-005, FR-008, FR-012, FR-013, FR-015)
- [x] T025 [US5] `hermes/CHANGELOG.md`: sección `### Plataforma y deprecaciones` dentro de `## [1.2.0]` (el tramo A ya la creó con lo suyo: `child_errors` y `success`, safety backup, nada se retira, `command_removed_in_ha`, socket y `/v2`, guarda del SDK; B añade traducciones y «app» y revisa el resto): `child_errors` y la descripción de `sv_get_job_status`, `success: false` con errores en sub-jobs y el sondeo del safety backup que los cuenta (D-1, arreglo); `command_removed_in_ha`; detección del socket y de la `/v2` al arrancar (evento y avisos); traducciones de las opciones y término «app»; nada se retira en la 1.2.0 (alias hasta la 1.3.0; la tool deprecada sigue); guarda de deprecaciones del SDK (FR-015)
- [x] T026 [US5] `specs/008-cobertura-total/plan.md`, matriz de trazabilidad: filas CAP-025, CAP-026 y CAP-028…CAP-033 con vía, tests (clases y ficheros de A y B) y entradas de la hoja de ruta, como las de la 011 (FR-015, SC-008)

### Extras del supervisor en el tramo B

- [x] TB-1 (seguridad) `sv_get_job_status` devolvía `child_jobs` en bruto: un
  secreto en el error de un sub-job salía por ahí aunque `child_errors` lo
  tapara. `supervisor_jobs.redact_child_jobs` (`redact_structure` más
  `redact_secrets` en cada texto). Test:
  `TestJobStatusSubJobs.test_centinela_anidado_no_sale_en_ninguna_parte`.
  Control negativo: `child_jobs` sin redactar → en rojo
- [x] TB-2 `tools/ha.py` lanzaba la auto-clasificación con
  `asyncio.ensure_future`, que sin bucle en marcha da `DeprecationWarning`
  (error en 3.14). `_lanzar_o_aplazar`: el bucle en marcha si lo hay; si no,
  la tarea se aplaza y la lanza el lifespan (`lanzar_tareas_aplazadas`). Test:
  `tests/test_tareas_aplazadas.py`. Control negativo: `ensure_future` de
  vuelta → en rojo

### Desviaciones del tramo B

- T019: el test de nombres y argumentos no se duplica; se comprueba que las
  doce tools están en `esquemas_1_1_2.json`, que ya fija sus argumentos.
- T022: además del apartado 4, la introducción de las instrucciones y el
  índice de la guía dicen «apps (add-ons)», para no mezclar los dos términos
  en el mismo texto. El tema `supervisor` nombra ahora las doce tools por su
  nombre completo (antes `sv_start/stop/restart_addon`).
- T023: en las tablas de opciones solo había dos «add-on» hablando del objeto
  (`tool_families_disabled` en `README.md` y `response_max_bytes` en
  `DOCS.md`). El resto de «add-on» de los documentos no es de la 027
  (principio IX).

### Cierre del tramo B

- [x] T027 Cierre: tabla regenerada sin cambios (`git diff --exit-code hermes/src/hermes/command_table.py`); suite con exactamente los 6 fallos conocidos; revisión del diff buscando datos personales (traducciones, README, hoja de ruta); commit(s) del tramo con el control negativo de T018 en el mensaje; anotar en `checklists/requirements.md` las dudas que sigan abiertas (FR-014, FR-016, SC-006, SC-007)

---

## Dependencias y orden

- T001 antes de todo.
- Tramo A: T002→T003, T004→T005 (T005 necesita T003), T005a→T005b (necesita T003), T006→T007, T008→T009,
  T010→T011, T012→T013 (T013 necesita T011), T014→T015; los bloques son
  independientes entre sí. T016 al final.
- Tramo B: T017→T018, T019→T020, T021→T022; T023 en paralelo; T024–T026 tras
  cerrar A (citan sus tests); T027 al final.

## Paralelo

- Tests marcados [P] de un mismo tramo en paralelo (ficheros distintos, salvo
  T004 y T019, que comparten `tests/test_tools_supervisor.py` pero van en
  tramos distintos).

## Cobertura

| FR | Tareas |
|---|---|
| FR-001 | T004, T005, T021, T022 |
| FR-002 | T002, T003, T004, T005 |
| FR-003 | T008, T009, T024 |
| FR-004 | T014, T015, T024 |
| FR-005 | T014, T015, T024 |
| FR-006 | T017, T018 |
| FR-007 | T019, T020, T021, T022, T023 |
| FR-008 | T008, T009, T024 |
| FR-009 | T006, T007 |
| FR-010 | T008, T009 |
| FR-011 | T010, T011, T012, T013 |
| FR-012 | T024 |
| FR-013 | T024 |
| FR-014 | T016, T027 |
| FR-015 | T023, T024, T025, T026 |
| FR-016 | T002, T009, T010, T016, T017, T027 |
| FR-017 | T005a, T005b |

---

## Fase 3: Convergencia

Revisión independiente (2026-11-14) sobre `65d6795..26af251`. Todos los FR
(FR-001…FR-017) tienen código y test; lo que sigue son los hallazgos de la
revisión que hay que arreglar.

- [ ] T028 [BAJO] `child_errors` (y `errors`, por la misma función) recorta el mensaje a 500 caracteres ANTES de pasar `redact_secrets`: un secreto que cruza el corte deja de reconocerse y sale a medias (un JWT cortado deja ver su cabecera y parte del payload; `child_jobs`, que no se recorta, sí lo tapa entero). Arreglo: en `hermes/src/hermes/supervisor_jobs.py`, `redact_secrets(mensaje)[:JOB_ERROR_MAX_CHARS]` en `_mensaje` y en `job_errors`; test con un JWT centinela que cruce el carácter 500 en `tests/test_supervisor_jobs.py`, con control negativo per FR-002, FR-016, Constitution II (contradicts)
- [ ] T029 [BAJO] La descripción de `call_service_auto_classify_dangerous` en `hermes/translations/en.yaml` y `es.yaml` («Turn it off only to manage the list by hand» / «Desactívalo solo para gestionar la lista a mano») da a entender que con `false` no se clasifica nada, pero `classify_saved_config` (`tools/ha.py`, llamada desde `ha_create_or_update_script` y `ha_create_or_update_automation`) marca como restringidos los guardados peligrosos con la opción en `false`; la opción solo apaga la clasificación del arranque y tras un `reload` por `ha_call_service`. Arreglo: decir eso en las dos traducciones (y en la fila de `README.md`/`README.es.md` de la que salen, sincronizadas) per FR-006, Constitution V (contradicts)
