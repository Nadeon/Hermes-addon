---

description: "Tareas de la sub-feature 017 — automatización asistida (Hermes 1.2.0)"
---

# Tareas: automatización asistida (017)

**Entrada**: `specs/017-automatizacion-asistida/` (spec.md, plan.md,
research.md, data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `CONFIRMATIONS_DIR` en
un `tempfile.TemporaryDirectory`, `DummyMCP`/`_RecordingMCP`, `AsyncMock` de
`ws_send` con respuestas por `type`, cola de suscripción simulada para las
esperas, `structlog.testing.capture_logs`. Datos ficticios (`light.salon`,
`<device_id>`, `https://example.com/blueprints/luz.yaml`, `centinela-017`, un
JWT de prueba). Nada de la instalación real ni de las tools MCP de Hermes.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" python -m pytest -q -p no:cacheprovider`.
Línea base en Windows al especificar (2026-11-14, punta `cc92b4a`, con la 009,
la 010, la 011, la 028 y la 014, sin la 012): 2357 passed, 65 skipped, 6
failed (los 6 conocidos). T001 la vuelve a tomar tras integrar la 012. Cada
tramo termina con exactamente esos 6 fallos en local; la referencia es el CI
de Linux.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 blueprints, US2 dispositivo, US3 targets, US4 espera
de trigger, US5 validar al guardar, US6 nada se rompe.

## Tramos de implementación

La 008 da 3 tramos; aquí son 4 porque el de blueprints no cabe con holgura en
un agente (research R-12). Cada tramo lo hace un agente nuevo, deja la suite
en verde y se commitea por separado (uno o varios commits; el tramo no se
cierra con la suite en rojo).

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **A** — base y blueprints locales | **T001–T016** | Familia `blueprints`; `ha_list_blueprints`, `ha_preview_blueprint_substitution`, `ha_save_blueprint`, `ha_delete_blueprint` registradas, anotadas y probadas; 4 entradas `blueprint/*` en `dedicated`; tema `blueprints` (parte local); banco con dos probadas y sus filas de la matriz; CHANGELOG y hoja de ruta parciales |
| **B** — importar | **T017–T025** | `ha_import_blueprint` (vista previa de terceros con huella, de mundo abierto); `blueprint/import` en `dedicated`; blueprint servido por la HA del banco y prueba de importación; tema `blueprints` completo |
| **C** — dispositivo y targets | **T026–T037** | Familia `automation_assist` (dos módulos); las 8 tools de lectura; 11 entradas en `dedicated`; tema `automation_assist` (parte de dispositivo y targets); lecturas en el banco |
| **D** — espera de trigger, validación al guardar y cierre | **T038–T054** | `HAClient.ws_subscribe_queue`; gestor de esperas compartido; `ha_wait_for_trigger`; `subscribe_trigger` reclasificado y en `dedicated`; validación en `ha_create_or_update_automation`/`_script`; banco; documentación final y matriz de la 008 |

Orden: A → B; C es independiente de A y B dentro de la 017 (puede ir en
paralelo con B si no se tocan a la vez los ficheros comunes); D necesita A
(sustitución) y la 012.

---

## Tramo A — base y blueprints locales (US1, US6)

### Preparación

- [x] T001 Comprobar las dependencias (S-01): la rama tiene integrada la 012 (`hermes/src/hermes/tools/core_validation.py` existe y `scripts/inventario/generar_tabla.py` consulta `_DEDICADAS_INICIALES` para la clase A). Si no, traerla por merge desde `feat/cobertura-total` cuando la tenga; si `feat/cobertura-total` aún no la tiene, PARAR y decirlo en el informe (la 008 pone a la 017 detrás de la 012). Ejecutar la suite y anotar la línea base en el mensaje del commit

### Familia (US6)

- [x] T002 [US6] Tests en `tests/test_tool_families.py`: `blueprints` existe, `desde="1.2.0"`, desactivable, con exactamente `("blueprints",)`; `validar_desactivadas(["blueprints"])` la acepta; el test de las 216 de la 1.1.2 sigue pasando sin tocarlo. Luego `Familia("blueprints", …)` en `hermes/src/hermes/tool_families.py`, bloque de la 1.2.0, con el comentario de por qué va sola (research R-10) (FR-011)

### Tests de blueprints locales (escritos antes de T008)

- [x] T003 [P] [US1] Tests de los helpers en `tests/test_tools_blueprints.py` (`TestRutasYYaml`): `_validar_ruta` acepta `homeassistant/motion_light.yaml` y `mio/luz` (→ `mio/luz.yaml`) y rechaza `../x`, `a/../b`, `/abs`, `\\x`, `c:/x`, `a\x00b`, `""`, 256 caracteres y segmentos con caracteres fuera de `[A-Za-z0-9._ -]`; `_validar_dominio` acepta los tres y rechaza `light`; `_cargar_yaml_blueprint` lee un blueprint con `!input` y una etiqueta desconocida sin fallar, rechaza YAML roto, uno que no es un mapa, uno sin `blueprint:` y uno de más de 256 KiB; `_metadatos` aplana entradas con secciones (`input: {sec: {input: {a: …}}}`) (FR-002, FR-003, research R-5)
- [x] T004 [P] [US1] Tests de `ha_list_blueprints`: sin `domain` pide `blueprint/list` para `automation`, `script` y `template` y junta; con `domain` solo ese; transformación de cada campo de data-model; elemento con `error` → error redactado (centinela tapado); orden; `_third_party_text`; dominio inválido → `invalid_argument` sin `ws_send`; respuesta que no es mapa → error, no lista vacía; muchos blueprints con `response_max_bytes` pequeño → sobre con `truncated` y `count` total (FR-001, FR-015, FR-016)
- [x] T005 [P] [US1] Tests de `ha_preview_blueprint_substitution`: un solo `ws_send` `blueprint/substitute` con `domain`, `path` final e `input`; devuelve `substituted_config` y `saved: false`; un valor de entrada con un centinela sale tapado (`redact_structure`); error de HA (`unknown_error` «Missing input…») → error redactado; ruta inválida → `invalid_argument` sin `ws_send`; resultado que no cabe → `response_too_large` (FR-005, FR-015, FR-016)
- [x] T006 [P] [US1] Tests de `ha_save_blueprint` (`TestGuardar`): (a) validación sin HA: dominio, ruta, YAML ilegible, sin `blueprint:`, `blueprint.domain` distinto del argumento, `yaml` ausente sin token; (b) vista previa: lee `blueprint/list`, no existe → vista previa de data-model con metadatos, tamaño y SHA-256, token, y NINGÚN `blueprint/save`; (c) existe sin `allow_override` → `already_exists` sin token ni fichero de token; con `allow_override` → `exists: true`, `used_by` de `search/related` y el aviso de recarga; (d) confirmación: un solo `blueprint/save` con `domain`, `path` final, `yaml` y `allow_override`; confirmación omitiendo `yaml` → guarda el previsualizado (spec 007); `yaml` reenviado distinto → rechazado; (e) token con otra ruta, otro dominio u otro `allow_override` → rechazado sin `blueprint/save`; reutilizado → rechazado; (f) HA `invalid_format` al guardar → error redactado y token completado con fallo; (g) lectura previa fallida → `preview_unavailable` sin token; (h) centinela en el YAML: no aparece en la vista previa (no repite el YAML), ni en el log (el log lleva dominio, ruta, tamaño y huella) (FR-003, FR-015, SC-003, SC-004)
- [x] T007 [P] [US1] Tests de `ha_delete_blueprint` (`TestBorrar`): (a) no existe en `blueprint/list` → `not_found` sin token; (b) `search/related` con `automation_blueprint` e `item_id` = ruta devuelve dos automatizaciones → `blueprint_in_use` con las dos, `used_by_count` y sin token ni `blueprint/delete`; con `script_blueprint` para el dominio `script`; (c) sin uso → vista previa de data-model con `effect` y token, sin `blueprint/delete`; (d) `template` → no llama a `search/related`, `used_by: null` con `used_by_note`, token; (e) `search/related` falla → `preview_unavailable` sin token; (f) confirmación → un solo `blueprint/delete`; HA responde `home_assistant_error` «Blueprint in use» → `blueprint_in_use` y token completado con fallo; otro error → redactado; (g) token de otra ruta o dominio → rechazado; (h) más de 50 consumidores → 50 ids y `used_by_count` exacto (FR-004, SC-003)

### Implementación

- [x] T008 [US1] `hermes/src/hermes/tools/blueprints.py` (research R-2…R-5, data-model, contracts): `register(mcp, ha_client, *, response_max_bytes)` con las cuatro tools del tramo, `@ready`, docstrings en inglés que dicen lo que hacen y lo que no; helpers de módulo de plan.md (tramo A, punto 2); dos pasos con `create_confirmation_token` (con `omitibles=("yaml",)` en guardar), `resolve_confirmation_token`/`validate_confirmation_token` y `complete_confirmation_token`; redacción; sobre con `ajustar_lista_a_bytes`; eventos de log sin contenido. El argumento `yaml` no puede tapar al módulo `yaml`: importarlo con otro nombre. Comentarios en español con el porqué. T003–T007 en verde (FR-001, FR-003…FR-005, FR-015, FR-016)
- [x] T009 [US6] Registro, anotaciones y matriz de pruebas, en el mismo cambio (el test de la matriz de la 014 exige la fila en cuanto la tool que modifica se registra): `register_blueprints` en `hermes/src/hermes/tools/__init__.py` dentro de `if _activa("blueprints")` con `response_max_bytes`; `ha_preview_blueprint_substitution` en `_READ_ONLY_EXACT` y `ha_save_blueprint`, `ha_delete_blueprint` en `_DESTRUCTIVE_EXACT` de `tools/_annotations.py` con los comentarios de contracts; filas de las dos en la matriz de `docs/HOJA-DE-RUTA.md` (`banco de Core`, `ok`). El `ok` lo sostiene el inventario de T012: T009 y T012 van en el MISMO commit, o `test_matriz_pruebas` queda en rojo entre los dos. Tests en `tests/test_tools_registration.py`: hints y títulos de las cuatro según contracts; con `blueprints` desactivada no aparece ninguna; las de la 1.1.2 sin cambios («pide token ⇔ destructiva» pasa sin excepciones nuevas) (FR-011, FR-013, FR-017, FR-018)

### Tabla y generador (US6)

- [x] T010 [US6] Tabla: (a) tests primero: en `tests/test_tools_generic_commands.py`, `ha_call_ws_command("blueprint/delete", …)` y `ha_read_ws_command("blueprint/list")` → `use_dedicated_tool` con su tool; con `blueprints` desactivada, `family_disabled: true`; (b) `scripts/inventario/generar_tabla.py`: `blueprint/list`, `blueprint/save`, `blueprint/delete` y `blueprint/substitute` en `_DEDICADAS_INICIALES` con un comentario «Blueprints (spec 017)»; (c) `hermes/src/hermes/command_table.py`: las cuatro a `E("dedicated", "cubierto por <tool>", "blueprints", tool=…, cap="CAP-046")`; (d) ejecutar el generador y comprobar que `git diff -- hermes/src/hermes/command_table.py` no cambia nada respecto a (c); anotarlo en el commit (FR-012, SC-002)

### Guía (US6)

- [x] T011 [US6] `hermes/src/hermes/tools/guide.py`: tema `blueprints` (alias `blueprint`) con la parte local de contracts (listar, sustituir, crear la automatización con `use_blueprint`, guardar en vez de `fs_write_file`, borrar y `blueprint_in_use`). Tests en `tests/test_tools_guide.py`: el tema existe con su alias; cada tool registrada de la familia `blueprints` aparece nombrada en él (test genérico por familia que los tramos B, C y D no tienen que tocar: recorre `blueprints` y `automation_assist`, la que exista); el índice lo lista (FR-014)

### Banco (US1)

- [x] T012 [US1] Inventario: `tests/banco/cobertura_017.py` con el docstring de la regla de la 028, `PROBADAS_017 = {"ha_save_blueprint", "ha_delete_blueprint"}` y `NO_EJECUTABLES_017 = {}`; sumada en `tests/test_banco_cobertura_escrituras.py` (unión de `test_todas_las_escrituras_clasificadas` y `test_listas_disjuntas`) y a `TOOLS_EXIGIDAS_DEL_JOB` de `tests/banco/cobertura_escrituras.py`. Control negativo: quitar `ha_delete_blueprint` de `PROBADAS_017` pone en rojo el invariante nombrándola (FR-017)
- [x] T013 [US1] `tests/banco/test_banco_blueprints.py` (marcador y base de la 010; lector independiente): `ha_list_blueprints` incluye `automation` `homeassistant/motion_light.yaml` y `script` `homeassistant/confirmable_notification.yaml`; `ha_preview_blueprint_substitution` de `motion_light` con entradas genéricas devuelve una configuración con `triggers`; `ha_save_blueprint` de un blueprint mínimo propio en `hermes_banco/guardado.yaml`: vista previa → el lector no lo ve → confirmación → el lector lo ve con su nombre; otra vez sin `allow_override` → `already_exists`; con `allow_override` y otro nombre → el lector ve el nuevo; `ha_delete_blueprint`: se crea con el lector (por `ha_create_or_update_automation` o la API de config) una automatización con `use_blueprint: {path: hermes_banco/guardado.yaml, …}` → `blueprint_in_use` con ella y el fichero sigue (lector) → se borra la automatización → vista previa → confirmación → el lector ya no lo ve. Limpieza en `tearDown` aunque falle (FR-017, SC-005)

### Documentación y cierre del tramo

- [x] T014 Documentación parcial: sección «Automatización asistida (spec 017)» en `## [1.2.0]` de `hermes/CHANGELOG.md` con las cuatro tools, la familia y las entradas de la tabla; fila 017 de la tabla del programa en `docs/HOJA-DE-RUTA.md` → «en curso (tramo A)» (FR-019)
- [x] T015 [US6] No regresión del tramo: `tests/test_tools_search_related.py`, `tests/test_tools_filesystem.py` y los de automatizaciones y scripts pasan sin tocarlos; con todas las familias de la 1.2.0 desactivadas, la lista de tools es la de la 1.1.2 (test existente) (FR-018)
- [x] T016 Cierre del tramo A: suite completa (los 6 fallos conocidos y nada más); controles negativos, cada uno visto en rojo y anotado en el commit: (1) `_validar_ruta` sin la comprobación de `..` → T003 en rojo; (2) vista previa de guardar que llama a `blueprint/save` → T006(b); (3) borrar sin consultar `search/related` → T007(b); (4) `blueprint_in_use` con token → T007(b); (5) sin `redact_secrets` en el error de `ha_list_blueprints` → T004; (6) `ha_delete_blueprint` fuera de `_DESTRUCTIVE_EXACT` → T009; (7) una entrada `blueprint/*` sin pasar a `dedicated` → T010 (o el test de deriva); (8) la fila de la matriz de `ha_save_blueprint` borrada → `test_matriz_pruebas` en rojo. Revisión del diff buscando datos personales e identificadores de modelo. Commit(s) del tramo (FR-020, SC-006, SC-007)

### Notas del tramo A (al implementarlo)

- **Línea base** (T001), tras traer `feat/cobertura-total` (con la 009, 010,
  011, 012, 013, 014, 018, 028 y 029; merge sin conflictos): 2786 passed, 88
  skipped, 6 failed (los 6 conocidos de Windows). Al cerrar el tramo: los
  mismos 6 fallos y nada más.
- **Desviación (T009)**: `ha_delete_blueprint` NO va en `_DESTRUCTIVE_EXACT`:
  ya es destructiva por el prefijo `ha_delete_`, así que el control negativo
  (6) se hace con `ha_save_blueprint`, que sí depende de la lista.
- **Desviación (T014)**: README, README.es y DOCS ya en este tramo y no en el
  D: el test de recuento de tools (255) y el de familias documentadas caen en
  cuanto se registran las tools.
- **Desviación (T008)**: `_full_path` se arma con `"/".join` y no con una
  f-string que empiece por `/`: el test de regresión de rutas
  (`test_every_module_that_builds_a_path_has_a_validator`) toma toda f-string
  así por una ruta de petición; esta solo se enseña en la vista previa.
- **Desviación (T003)**: las etiquetas locales del YAML (`!input`, `!secret`…)
  se leen como `{"tag": "!input", "value": …}`; las de Python
  (`!!python/…`) siguen rechazándose como en el `SafeLoader`.
- `yaml` de `ha_save_blueprint` se declara `str` exactamente (no
  `str | None`), como `content` de `fs_write_file`: el SDK MCP haría
  `json.loads` de un YAML en forma de flujo (test `TestEsquemaDelYaml`).
- Error de la sustitución: `substitution_failed` con `ha_code` y `detail`
  redactado; errores de HA al guardar y borrar: `save_failed` y
  `delete_failed` con lo mismo (los contratos solo decían «redactado»).
- Inventario de argumentos atados al token (033, aún no integrado en esta
  rama): al integrar hay que añadir `ha_save_blueprint` (`domain`, `path`,
  `yaml` omitible, `allow_override`: todos atados) y `ha_delete_blueprint`
  (`domain`, `path`: atados).

---

## Tramo B — importar (US1, US6)

### Tests (escritos antes de T020)

- [x] T017 [P] [US1] Tests de la vista previa de `ha_import_blueprint` en `tests/test_tools_blueprints.py` (`TestImportar`), con `blueprint/import` simulado: (a) `url` vacía o sin esquema `http(s)` → `invalid_argument` sin `ws_send`; `path` inválido → ídem; (b) vista previa con todos los campos de data-model: `importer` por patrón (foro, GitHub, gist, web de HA, genérico), `path` final (`<suggested_filename>.yaml` o el `path` dado), `full_path`, metadatos, entradas, `content` = `raw_data`, `content_bytes`, `content_sha256` correcto, `on_save`, `_third_party_text`; NINGÚN `blueprint/save`; (c) `validation_errors` no vacío → `invalid_blueprint` sin token; dominio `light` → `invalid_blueprint`; (d) `exists: true` sin `allow_override` → `already_exists` sin token; con `allow_override` → `used_by` y aviso de recarga; (e) `raw_data` que no cabe en `response_max_bytes` → `blueprint_too_large` sin token y sin recortar el YAML; (f) `raw_data` con un centinela → tapado en `content` con `content_redacted: true` y la nota; (g) errores de HA (`not_supported`, `timeout`, `unknown_error`, `invalid_format`) → `import_failed` con `ha_code` y `detail` redactado, sin token; (h) el log no lleva la URL con credenciales (`https://user:centinela-017@example.com/…`) ni el YAML (FR-002, FR-015, FR-016)
- [x] T018 [P] [US1] Tests de la confirmación: (a) mismo contenido → `blueprint/import` otra vez y un solo `blueprint/save` con `domain` de los metadatos, `path` final, `yaml` = `raw_data` ORIGINAL (no el tapado), `source_url` = `url` y `allow_override`; (b) contenido distinto en la segunda descarga → `content_changed` con la pista, sin `blueprint/save`; (c) sugerencia de ruta distinta (sin `path`) → `content_changed`; (d) token con otra `url`, otro `path` u otro `allow_override` → rechazado sin `blueprint/save`; reutilizado → rechazado; (e) la segunda descarga falla → `import_failed` sin guardar; (f) `blueprint/save` responde `already_exists` (carrera) → error y token completado con fallo; (g) el fichero del token no contiene el YAML (FR-002, SC-003, SC-004)

### Implementación

- [x] T019 [US1] `ha_import_blueprint` en `hermes/src/hermes/tools/blueprints.py` (research R-1, data-model): `_importador_de(url)` con los patrones de `importer.py` (copiados como constantes con su origen en un comentario), vista previa, huella `sha256` del texto en UTF-8, token atado a `url`, ruta final, `allow_override` y `content_sha256`; confirmación con nueva descarga y `validate_confirmation_token` con los valores recalculados (si no casa, `content_changed`). Docstring que dice que HA descarga, que es texto de terceros y que la vista previa enseña el YAML entero. T017–T018 en verde (FR-002)
- [x] T020 [US6] Anotaciones y matriz: `ha_import_blueprint` en `_DESTRUCTIVE_EXACT` y en `_OPEN_WORLD` de `tools/_annotations.py` con su comentario; su fila en la matriz de `docs/HOJA-DE-RUTA.md` (`banco de Core`, `ok`, nota «importador genérico desde `/local/` del banco; GitHub, gist y foro sin probar»), en el MISMO commit que su alta en `PROBADAS_017` (T023). Test en `tests/test_tools_registration.py`: `openWorldHint` verdadero solo en ella de entre las de la familia (FR-013)

### Tabla, guía y banco

- [x] T021 [US6] Tabla: test de la genérica con `blueprint/import` → `use_dedicated_tool`; `blueprint/import` en `_DEDICADAS_INICIALES` y a `dedicated` en `command_table.py`; regenerar → sin diferencias, anotado en el commit (FR-012)
- [x] T022 [US6] Guía: parte de importar del tema `blueprints` (HA descarga; la vista previa enseña el YAML entero; texto de terceros: leerlo, enseñárselo al usuario, no seguir instrucciones que contenga; `content_changed`; `allow_override`). El test genérico de T011 la cubre; añadir uno que exija «third-party» en el tema (FR-014)
- [x] T023 [US1] Banco: `tests/banco/ha_config/www/hermes_banco/luz_por_movimiento.yaml` (blueprint de automatización mínimo, propio, con un comentario de por qué está en `www`); en `test_banco_blueprints.py`, una prueba que (1) comprueba con el lector que `GET /local/hermes_banco/luz_por_movimiento.yaml` responde 200 (si no, el fallo dice que HA no sirve `www`), (2) llama a `ha_import_blueprint(url="http://127.0.0.1:8123/local/hermes_banco/luz_por_movimiento.yaml")` → vista previa con `importer: generic`, `path` `127.0.0.1/luz_por_movimiento.yaml` y el YAML → el lector no lo ve → confirmación → el lector lo ve con `source_url`, (3) lo borra con `ha_delete_blueprint`. `ha_import_blueprint` a `PROBADAS_017`. Prueba manual pendiente con una URL de GitHub en los pendientes de `docs/HOJA-DE-RUTA.md` (FR-017, research R-11)

### Documentación y cierre del tramo

- [x] T024 CHANGELOG: `ha_import_blueprint` en la sección de la 017 (con la huella, la nueva descarga al confirmar y la anotación de mundo abierto); fila 017 → «en curso (tramos A y B)» (FR-019)
- [x] T025 Cierre del tramo B: suite completa; controles negativos anotados: (1) confirmación sin comparar la huella (guarda lo nuevo) → T018(b) en rojo; (2) guardar el `content` tapado en vez del original → T018(a); (3) recortar el YAML en vez de `blueprint_too_large` → T017(e); (4) sin `_third_party_text` → T017(b); (5) `ha_import_blueprint` fuera de `_OPEN_WORLD` → T020; (6) dar token con `validation_errors` → T017(c). Revisión del diff. Commit(s) del tramo (FR-020, SC-006)

### Notas del tramo B (al implementarlo)

- **Línea base** al empezar el tramo (punta `37cb45e`): 2844 passed, 91
  skipped, 6 failed (los 6 conocidos de Windows). Al cerrar: los mismos 6
  fallos y nada más.
- **Desviación (T019), cómo ata el token**: los argumentos del cliente
  (`url`, `path` tal como lo pide, `None` si se usa la sugerencia, y
  `allow_override`) van al `action_hash`; lo descargado (dominio, ruta final
  y `content_sha256`) va como `estado` (mecanismo de la 018) y no al hash.
  Así un token de otra llamada da «does not match» y un contenido o una
  sugerencia distintos dan `content_changed` sin gastar el token. Ata lo
  mismo que decía data-model (URL, ruta final, sobrescribir y huella).
- **Consecuencia**: al confirmar, HA descarga ANTES de validar el token
  (hace falta la huella nueva para validarlo). Un token de otros argumentos
  cuesta una descarga de HA (solo lectura) y nunca guarda.
- **Sugerencia de ruta de HA que no pasa `_validar_ruta`** (sale de la URL o
  del autor): `invalid_argument` en `path` sin token, pidiendo `path`
  (fail-closed). `validation_errors` que no es lista: `invalid_blueprint`.
- **`exists`**: el de HA vale para la ruta sugerida; con `path`, manda
  `blueprint/list` (un fichero roto también cuenta).
- **`blueprint_too_large`** se mide con el sobre entero del token
  (`confirmation_token`, `expires_in_seconds`, `preview`), que es lo que sale.
- **Banco (T023)**: el blueprint de `www` es solo ASCII a propósito: HA lo
  lee con `resp.text()` y, sin charset, aiohttp adivina la codificación; con
  ASCII la huella del lector casa con la de HA en cualquier caso. La red del
  banco no se toca: 127.0.0.1 dentro del contenedor no pasa por la regla de
  `iptables` (solo corta lo que sale de la subred).
- **Control negativo (3)**: se hizo quitando la comprobación de tamaño (la
  vista previa sale con token aunque no quepa); cae `test_no_cabe_sin_token`.
- README, README.es y DOCS: 256 tools y la fila de `blueprints` con 5.
- Inventario de argumentos atados al token (033, aún no integrado en esta
  rama): al integrar hay que añadir `ha_import_blueprint` (`url`, `path`,
  `allow_override`: atados por el hash; dominio, ruta final y huella del
  contenido: atados como estado; nada omitible).

---

## Tramo C — dispositivo y targets (US2, US3, US6)

- [x] T026 [US6] Familia `automation_assist` (`desde="1.2.0"`, desactivable) con `("device_automation", "targets")`, tests primero en `tests/test_tool_families.py` (el tramo D añade `wait_for_trigger` y ajusta el test) (FR-011)

### Tests (escritos antes de T029 y T030)

- [x] T027 [P] [US2] Tests en `tests/test_tools_device_automation.py`: para cada tipo, un `ws_send` `device_automation/<tipo>/list` con `device_id`; lista devuelta tal cual en el sobre con `device_id`; `include_capabilities=true` → una llamada `…/capabilities` por elemento con la clave correcta (`trigger`, `condition`, `action`) y `capabilities` en cada uno; capacidades de un elemento que fallan → `capabilities_error` redactado y el resto sigue; 60 elementos → 50 llamadas y `capabilities_truncated: true`; `not_found` de HA → `not_found`; `device_id` vacío → `invalid_argument` sin `ws_send`; respuesta que no es lista → error; recorte por tamaño (FR-006, FR-015, FR-016)
- [x] T028 [P] [US3] Tests en `tests/test_tools_targets.py`: `_validar_target` (claves admitidas, texto o lista de textos no vacíos, `exclude` con las mismas claves, al menos una clave fuera de `exclude`, clave desconocida → `invalid_argument` nombrándola, solo `exclude` → `invalid_argument`); `ha_resolve_target` envía `extract_from_target` con `target`, `expand_group` y `primary_entities_only` y devuelve la forma de data-model ordenada; `ha_explain_target` con `explain_target` y sus valores por defecto; las tres de lista envían su comando y devuelven el sobre con nombres ordenados; `unknown_command` → `ha_version_unsupported` con la versión; recorte por tamaño con recuentos (FR-007, FR-008, FR-016)

### Implementación

- [x] T029 [US2] `hermes/src/hermes/tools/device_automation.py` (research R-6): `_listar` común y las tres tools con `@ready` y docstrings que dicen que el elemento se pega tal cual en la automatización y qué son las capacidades. T027 en verde (FR-006)
- [x] T030 [US3] `hermes/src/hermes/tools/targets.py` (research R-7): `_validar_target` y las cinco tools; docstrings que dicen que las listas dan nombres sin sus opciones y cómo se escribe un trigger por propósito. T028 en verde (FR-007, FR-008)
- [x] T031 [US6] Registro y anotaciones: los dos módulos en `tools/__init__.py` dentro de `if _activa("automation_assist")` con `response_max_bytes`; `ha_resolve_target` y `ha_explain_target` en `_READ_ONLY_EXACT` con comentario. Tests en `tests/test_tools_registration.py`: las ocho de solo lectura, ninguna de mundo abierto; con `automation_assist` desactivada no aparece ninguna (FR-011, FR-013)

### Tabla, guía y banco

- [x] T032 [US6] Tabla: tests de la genérica con `device_automation/trigger/list` y `get_services_for_target` → `use_dedicated_tool`; las 11 entradas en `_DEDICADAS_INICIALES` y a `dedicated` en `command_table.py` (data-model); regenerar → sin diferencias, anotado en el commit (FR-012)
- [x] T033 [US6] Guía: tema `automation_assist` (alias `device_automation`, `targets`) con la receta «automatización para un dispositivo» y la de target → por propósito → validar; el test genérico de T011 cubre sus tools (FR-014)
- [x] T034 [US2] [US3] Banco (lectura): `tests/banco/test_banco_automatizacion_asistida.py`: el lector busca un dispositivo de `kitchen_sink` con entidades; `ha_list_device_triggers/conditions/actions` con `include_capabilities=true` devuelven listas y capacidades con la forma de data-model; `ha_resolve_target` y `ha_explain_target` con su `device_id` devuelven sus entidades; las tres de lista por target devuelven nombres no vacíos para una entidad `light` de `kitchen_sink` (si la hay; si no, una `switch`) (FR-017)

### Documentación y cierre del tramo

- [x] T035 CHANGELOG: las ocho tools y la familia; fila 017 → «en curso (tramos A–C)» (FR-019)
- [x] T036 [US6] No regresión: `ha_search_related` y los registros sin cambios; con todas las familias de la 1.2.0 desactivadas, la lista de la 1.1.2 (FR-018)
- [x] T037 Cierre del tramo C: suite completa; controles negativos anotados: (1) capacidades sin tope → T027 (60 elementos); (2) `_validar_target` que acepta claves desconocidas → T028; (3) `unknown_command` como error opaco → T028; (4) una entrada de `device_automation/*` sin `dedicated` → T032. Revisión del diff. Commit(s) del tramo (FR-020, SC-006)


### Notas del tramo C (desviaciones y decisiones)

- **Línea base** al empezar (punta `997bb08`): 2871 passed, 92 skipped, 6
  failed (los 6 de Windows).
- **Sobre común y test transversal de la 018**: el AST busca la llamada a
  `sobre_de_lista` en la función de la tool; como las tres de dispositivo y
  las tres de lista por target comparten un helper, cada tool le pasa una
  lambda que llama a `sobre_de_lista` (comentado en los dos módulos).
- **`_validar_target`** rechaza también un `exclude` vacío y un `exclude`
  dentro de `exclude` (fail-closed: no excluye nada o HA no lo admite). Un
  `invalid_format` de HA (p. ej. un `entity_id` mal formado, que Hermes no
  valida) sale como `invalid_argument` en `target` con `ha_code`.
- **Errores de HA** distintos de `not_found`, `unknown_command` e
  `invalid_format`: `ha_command_failed` con `ha_code` y el detalle
  redactado; respuesta con forma inesperada: `unexpected_response`.
- **Resolver** añade `counts` (exactos) a la forma de data-model, para que
  el recorte no pierda los totales de las tres listas.
- **Elementos de dispositivo**: pasan por `redact_structure` +
  `redact_secrets` (FR-015); a `…/capabilities` se manda el elemento
  original de HA, no la copia redactada.
- **Banco (T034)**: `kitchen_sink` no crea luces; se usa su primer
  interruptor con dispositivo (triggers y condiciones por propósito
  `switch.turned_on` y `switch.is_on`). Las ocho solo leen: no entran en
  `PROBADAS_017` ni en lo que el job exige.
- **Matriz de la 008**: queda para el cierre (tramo D), como dice T054.
- Ninguna tool del tramo pide token: nada que añadir al inventario de
  argumentos atados (033).
- **Controles negativos (T037)**, vistos en rojo y restaurados: (1) tope de
  capacidades a 1000 → `test_tope_de_cincuenta`; (2) `_validar_target` sin
  la comprobación de clave → 6 fallos de `test_tools_targets.py`; (3)
  `unknown_command` sin traducir → `test_version_no_soportada`; (4)
  `device_automation/trigger/list` de vuelta a `deny` → 5 fallos (tabla,
  genéricas, generación desde cero); además, `ha_resolve_target` fuera de
  `_READ_ONLY_EXACT` → 2 fallos; sin el alias `targets` → test del tema;
  `targets` dentro de `automations` → 3 fallos de familias (SC-005).

---

## Tramo D — espera de trigger, validación al guardar y cierre (US4, US5, US6)

### Cliente y gestor de esperas

- [x] T038 [US4] Tests en `tests/test_ha_ws_subscribe_queue.py` (patrón de los tests de suscripción de `HAClient`): `ws_subscribe_queue(payload)` envía el payload con `id`, espera la confirmación, devuelve `(sub_id, cola, generación)` y los eventos llegan a la cola; error de HA en la confirmación → `HAConnectionError` con su `code` y sin cola ni future colgados, con `unsubscribe_events` enviado; plazo de confirmación → ídem; `ws_subscribe_events_queue("x")` envía exactamente `{"id", "type": "subscribe_events", "event_type": "x"}` como hoy. Luego el método en `hermes/src/hermes/ha.py` y `ws_subscribe_events_queue` delegando en él, con comentario. Los tests existentes de suscripciones pasan sin tocarlos (FR-009, FR-018)
- [x] T039 [US4] Tests en `tests/test_tools_wait_for_event.py`: `register` acepta un gestor; dos registros con el mismo gestor comparten cupo; `list_active` de una espera de evento devuelve exactamente las claves de hoy; de una de trigger, además `kind` y `trigger_platform`. Luego el cambio en `tools/wait_for_event.py` (parámetro opcional `manager`, campos opcionales en `_ActiveWait`) y en `tools/__init__.py` (un `_WaitManager` con `wait_for_event_max_concurrent`, creado una vez y pasado a los dos registros) (FR-009, FR-018)

### Espera de trigger

- [x] T040 [P] [US4] Tests en `tests/test_tools_wait_for_trigger.py` con una cola simulada (`ws_subscribe_queue` en `AsyncMock`): disparo → `matched: true` con `trigger` y `waited_seconds`; plazo → `timeout`; `ha_cancel_wait` → `cancelled` sin esperar al keepalive; sentinel → `ws_reconnect` con nota; `timeout_seconds` mayor que el máximo o menor que 1 → los mismos errores que `ha_wait_for_event`; cupo lleno (compartido con una espera de evento) → `too_many_waits`; lista cerrada de research R-8: `state` y `light.turned_on` (con `manifest/get` simulado `is_built_in: true`) → se suscribe; `webhook`, `conversation`, `samsungtv.turn_on`, `device` con `domain: webostv`, una plataforma sin punto que no está en la lista, `mi_custom.algo` (`is_built_in: false`) y un `manifest/get` que falla → `trigger_not_allowed` sin `ws_subscribe_queue`; la regla se aplica a cada elemento de una lista y a `trigger` y a `platform`; HA rechaza el trigger → `invalid_trigger` redactado y la espera no queda registrada; siempre `ws_unsubscribe_events_queue` al salir (también con excepción); `to_state` con `attributes.access_token` = centinela → tapado; disparo que no cabe → sin `from_state`/`to_state` y `truncated: true`; `variables` se pasan en el payload (FR-009, FR-015, FR-016)
- [x] T041 [US4] `hermes/src/hermes/tools/wait_for_trigger.py` (research R-8): `register(mcp, ha_client, *, manager, wait_for_event_max_seconds, response_max_bytes)` y `ha_wait_for_trigger`, reutilizando el bucle de espera de `ha_wait_for_event` (extraer a una función común de `wait_for_event.py` si se puede sin cambiar su comportamiento; si no, duplicar con un comentario). Docstring: un solo disparo, triggers rechazados y por qué, mismo tope que `ha_wait_for_event`. T040 en verde (FR-009)
- [x] T042 [US6] Familia, registro y anotaciones: `wait_for_trigger` en los módulos de `automation_assist` (y su test); registro dentro de `if _activa("automation_assist")` con el gestor compartido; `ha_wait_for_trigger` en `_READ_ONLY_EXACT` con el comentario de contracts. Test en `tests/test_tools_registration.py` (FR-011, FR-013)

### Validación al guardar

- [x] T043 [P] [US5] Tests en `tests/test_tools_validacion_al_guardar.py`: para `ha_create_or_update_automation` y `ha_create_or_update_script`: (a) parte inválida → `invalid_config` con el error por parte, redactado (centinela), sin token y sin fichero en `CONFIRMATIONS_DIR`; (b) todo válido → vista previa de hoy más `validation` con `validated` y `not_validated`, y token; (c) `use_blueprint` → `blueprint/substitute` con dominio `automation`/`script`, `path` e `input`, y `validate_config` con las partes del resultado; `via_blueprint` en la vista previa; (d) sustitución fallida → `blueprint_substitution_failed` sin token; (e) `validate_config` con `HAConnectionError` o respuesta que no es mapa → `validation_unavailable` sin token; (f) sin partes (solo `alias`) → sin `validate_config`, `validation` lo dice, token; (g) script con `sequence` → se valida como `actions`; (h) la confirmación NO llama a `validate_config` y guarda lo previsualizado (spec 007 sin cambios); (i) con `blueprints`, `automation_assist` y `core_diagnostics` desactivadas, valida igual (FR-010, FR-011)
- [x] T044 [US5] `hermes/src/hermes/tools/core_validation.py` (de la 012): sacar `partes_de_config` y `validar_partes` a funciones de módulo, usadas por `ha_validate_config` sin cambiar su comportamiento (sus tests de la 012 pasan sin tocarlos); en `tools/blueprints.py`, `sustituir(ha_client, dominio, use_blueprint)` compartida con `ha_preview_blueprint_substitution`; en `tools/automations.py` y `tools/scripts.py`, la validación en la rama de vista previa, con comentario del porqué (research R-9). Docstrings de las dos tools: la vista previa valida. T043 en verde (FR-010)

### Tabla, guía y banco

- [x] T045 [US6] Tabla e inventario: tests primero (`tests/test_generar_tabla.py`: la fila de `subscribe_trigger` del inventario es clase A con CAP-038 y sale `dedicated`; la genérica con `subscribe_trigger` → `use_dedicated_tool`); `specs/008-cobertura-total/inventario/core-ws.tsv`: `subscribe_trigger` a clase `A`, nota «Esperar a un trigger (un solo disparo)», `CAP-038` (research R-13); `subscribe_trigger` en `_DEDICADAS_INICIALES` y a `dedicated` en `command_table.py`; regenerar → sin diferencias, anotado en el commit. Comprobar que `tests/test_command_inventory.py` y el test de deriva siguen en verde (FR-012)
- [x] T046 [US6] Guía: espera de trigger en `automation_assist` (alias `wait_for_trigger`; frente a `ha_wait_for_event`; triggers rechazados; cancelación y qué pasa con `events` apagada); en el tema de automatizaciones, que la vista previa valida y remite a `blueprints` y `automation_assist` (FR-014)
- [x] T047 [US4] [US5] Banco: en `test_banco_automatizacion_asistida.py`, (1) espera de trigger de estado sobre un `input_boolean` del banco mientras el lector lo cambia → `matched: true` con `to_state.state`; (2) `ha_wait_for_trigger` con un trigger inválido → `invalid_trigger`; (3) `ha_create_or_update_automation` con un trigger inválido → `invalid_config` sin token, y el lector comprueba que `automation/config` no existe para ese id; (4) con `use_blueprint` de `homeassistant/motion_light.yaml` y una entrada que falta → `blueprint_substitution_failed` (FR-017, SC-005)

### Documentación final y cierre

- [x] T048 [US6] No regresión: los tests existentes de automatizaciones, scripts, `ha_wait_for_event`, `ha_list_active_waits`, `ha_cancel_wait` y de `ha_validate_config` pasan sin tocarlos (salvo los que esperaban una vista previa sin `validation`, que se amplían, no se cambian); la denylist no cambia (FR-018)
- [x] T049 CHANGELOG completo de la 017 en `## [1.2.0]` (blueprints, dispositivo, targets, espera de trigger, validación al guardar, familias, tabla, inventario reclasificado) (FR-019)
- [x] T050 `docs/HOJA-DE-RUTA.md`: fila 017 de la tabla del programa → «hecha»; en la lista de pendientes, quitar «Triggers y condiciones por propósito; resolución de targets (017)» y dejar la prueba manual de importación desde GitHub (FR-019)
- [x] T051 [P] `README.md` y `README.es.md` sincronizados (tools por área y recuento si lo llevan); `hermes/DOCS.md` si la opción de familias enumera las familias (`blueprints`, `automation_assist`) (FR-019)
- [x] T052 [P] Matriz de la 008 (`specs/008-cobertura-total/plan.md`): filas CAP-038, CAP-040, CAP-046, CAP-051 y CAP-052 con las tools y los ficheros de test (FR-019)
- [x] T053 Comprobación final: ninguna entrada «pendiente de tool dedicada (spec 017)» queda en `command_table.py`; cada FR de spec.md tiene su test (tabla de trazabilidad de plan.md al día); SC-001…SC-007 (FR-012, SC-006)
- [x] T054 Cierre del tramo D: suite completa; controles negativos anotados: (1) emitir token con una parte inválida → T043(a) en rojo; (2) dar token si `validate_config` falla → T043(e); (3) validar sin sustituir el blueprint → T043(c); (4) aceptar un trigger que no está en la lista cerrada (p. ej. quitar la comprobación de `is_built_in`) → T040; (5) gestor no compartido → T039 (cupo); (6) no cancelar la suscripción al salir → T040; (7) sin `redact_structure` en el disparo → T040; (8) `subscribe_trigger` de vuelta a clase B en el inventario → T045. Revisión del diff buscando datos personales e identificadores de modelo. Commit(s) del tramo (FR-020, SC-006, SC-007)

### Notas del tramo D (desviaciones y decisiones)

- **Línea base** al empezar (punta `d4c0475`): 2910 passed, 97 skipped, 6
  failed (los 6 de Windows). Al cerrar: 2987 passed, 103 skipped y los
  mismos 6 fallos.
- **Desviación (T041), bucle duplicado y no extraído**: `ha_wait_for_trigger`
  tiene su propio bucle de espera (mismo esquema que `ha_wait_for_event`) en
  vez de una función común en `wait_for_event.py`. La 033, ya integrada en
  `feat/cobertura-total` pero no en esta rama, reescribe justo ese bucle
  (`ctx: Context` y el `try` del aviso de progreso): extraerlo aquí daría un
  conflicto grande al integrar. `wait_for_event.py` solo cambia en lo
  mínimo (gestor inyectable, `kind` y `trigger_platform`). La espera de
  trigger ya nace con lo de la 033: `ctx: Context` (no sale en el esquema;
  test del esquema y de `context_kwarg`) y el aviso de progreso que no
  corta la espera si falla.
- **Lista cerrada (D-23)**: las plataformas sin punto de research R-8 se
  admiten sin consultar `manifest/get`; `<integración>.<nombre>` y `device`
  exigen `is_built_in: true` y no estar en las excluidas. Además, fail-closed:
  `device` sin `domain`, un elemento sin `trigger`/`platform` o con los dos,
  y un `manifest/get` que falla se rechazan. Las dos listas llevan en el
  código el aviso de revisarlas con cada versión de HA de referencia.
- **`trigger_platform`** en `ha_list_active_waits`: las plataformas de la
  lista, sin repetir, separadas por comas.
- **Disparo que no cabe** ni sin `from_state`/`to_state`: se queda con los
  valores simples del disparo (plataforma, `entity_id`, `id`…) y
  `truncated: true`.
- **Validación al guardar**: la función común es
  `core_validation.validar_al_guardar` (no estaba nombrada en el plan). Con
  `use_blueprint`, la ruta se manda a `blueprint/substitute` TAL CUAL se va
  a guardar (sin añadir `.yaml`): si HA no la encuentra al sustituir,
  tampoco al guardar. `not_validated` junta las claves de la configuración
  (sin `use_blueprint`) y las que añade el blueprint fuera de las partes.
  Una parte enviada sin resultado de HA da `validation_unavailable` (no se
  sabe si es válida). `invalid_config` con blueprint lleva `via_blueprint`.
- **D-22**: `validate_config` no mira `mode` ni el resto; la vista previa lo
  dice en `validation.not_validated` y la guía y el CHANGELOG también.
- **T048**: los tests existentes de vista previa de automatizaciones y
  scripts se amplían con un `validate_config` simulado que da por buena
  cada parte (su `ws_send` no existía); los de `ha_validate_config` de la
  012 pasan sin tocarlos.
- **Inventario de la 008**: con `subscribe_trigger` en clase A, el test de
  recuentos pasa a A 148 y B 102 (con su comentario).
- **Huella de la guía**: cambia la del tema `automations` (dice que la
  vista previa valida); actualizada en `test_tools_guide.py` y dicho en el
  CHANGELOG.
- **Banco (T047)**: la espera de trigger va contra un `input_boolean` creado
  por el lector, que lo apaga y enciende hasta que la tool responde (no se
  sabe cuándo queda suscrita). También un trigger fuera de la lista
  (`webhook`) y la vista previa con validación correcta (token y
  `validation`). Ninguna de estas tools es nueva escritura: no entran en
  `PROBADAS_017`.
- **Inventario de argumentos atados al token (033)**: `ha_wait_for_trigger`
  no pide token; la validación no cambia lo que atan los tokens de
  `ha_create_or_update_automation`/`_script`. Nada nuevo de este tramo.
- **Controles negativos (T054)**, vistos en rojo y restaurados: (1) token
  con una parte inválida → 5 fallos; (2) token si `validate_config` falla →
  4; (3) validar sin sustituir → 6; (4) sin mirar `is_built_in` → 2; (5)
  gestor no compartido → 2; (6) sin cancelar en el `finally` → 4; (7) sin
  `redact_structure` → 1; (8) `subscribe_trigger` de vuelta a B en el
  inventario → `test_subscribe_trigger_es_clase_a`, y a `deny` en la tabla →
  5. Además: sin `_ws_unsubscribe` en el rechazo de `ws_subscribe_queue`;
  `ctx: Any`; fuera de `_READ_ONLY_EXACT`; sin el párrafo de la guía.

## Dependencias

- T001 antes de todo. Dentro de cada tramo: tests → implementación →
  registro → tabla → guía → banco → documentación → cierre.
- B necesita A (rutas, `used_by`, metadatos, `cobertura_017.py`).
- C no necesita A ni B; si va en paralelo con B, el segundo en integrarse
  resuelve los conflictos de los ficheros comunes.
- D necesita A (sustitución) y la 012 (T001).

## Paralelismo

- Tramo A: T003–T007 en paralelo (mismo fichero de test, clases distintas).
- Tramo B: T017 y T018.
- Tramo C: T027 y T028; T029 y T030.
- Tramo D: T040 y T043; T051 y T052.

## Phase 5: Convergence

Revisión independiente del rango del tramo A al D. Comprobado sin hallazgos: la tabla regenerada idéntica (y desde cero, las 17 entradas de la 017 iguales a la tabla real), `subscribe_trigger` de B a A, las familias, la matriz de la 014, la cancelación de la suscripción con error, plazo, cancelación por `ha_cancel_wait` y cancelación de la tarea del cliente, el cupo compartido, `ctx` fuera del esquema, los triggers anidados (`{"triggers": […]}`, que HA aplana) rechazados sin suscribir, el token de importar atado a la huella y a la ruta final, y las rutas (`..`, absolutas, `\`, dominio fuera de la lista).

- [ ] T055 [ALTO] `ha_save_blueprint` e `ha_import_blueprint` dejan llegar a HA un YAML con etiquetas locales distintas de `!input` (`!env_var`, `!include`, `!include_dir_*`, `!secret`): `_CargadorBlueprint` las toma como opacas y la vista previa no las enseña ni las avisa (de una entrada solo sale `has_default`). HA las resuelve al leer el texto (`yaml_util.parse_yaml` en `blueprint/save` y en todos los importadores de `components/blueprint/importer.py`) y escribe el valor resuelto en el fichero (`Blueprint.yaml()` → `path.write_text`). Escenario: `default: !env_var SUPERVISOR_TOKEN` (o `!include /config/.storage/auth`) en una entrada usada como `message: !input x`; tras confirmar, el secreto queda en claro en `/config/blueprints/…` (legible con `fs_read_file`, fuera de la denylist) y sale en `ha_preview_blueprint_substitution` (`redact_structure` solo mira el nombre de la clave). Arreglo: lista blanca de etiquetas (solo `!input`) en el cargador; con otra, `invalid_argument` en guardar e `invalid_blueprint` sin token en importar (comprobado sobre `raw_data`, en la vista previa y al confirmar), nombrando la etiqueta y no su valor; descripción, guía y FR-003/FR-002 al día; tests con las cuatro etiquetas y control negativo per FR-015, Constitution II (contradicts)
- [ ] T056 [MEDIO] La lista cerrada de `ha_wait_for_trigger` admite el trigger de dispositivo `turn_on` de `philips_js` (integración de HA): `components/philips_js/device_trigger.py` lo engancha con `PluggableAction`, y mientras existe, `media_player` y `remote` de la tele anuncian `TURN_ON` y `async_turn_on` lo ejecuta (`media_player.py`, `supported_features` y `async_turn_on`), el mismo caso que `samsungtv`, `webostv` y `lg_netcast`. Comprobado con un test fuera del repo: se suscribe. `readOnlyHint` y la frase «solo escucha» no son verdad para él. Arreglo: `philips_js` en `_INTEGRACIONES_EXCLUIDAS`, en la descripción, la guía, el docstring del módulo y FR-009/research R-8; test como `test_dispositivo_webostv`; y dejar escrito en el docstring el criterio de revisión por versión (`grep PluggableAction` en `components/`, que hoy da exactamente estas cuatro y `webhook`) per FR-009, Constitution V (contradicts)
- [ ] T057 [MEDIO] **Decisión del supervisor.** La validación al guardar trata como `validation_unavailable` / `blueprint_substitution_failed` (sin token) un `unknown_command` de `validate_config` o de `blueprint/substitute`. El add-on declara HA ≥ 2024.10.0 y `blueprint/substitute` es posterior a la 1.1.2 en HA (no verificable aquí: las fuentes solo son de la 2026.11.1). En un HA sin él, guardar una automatización o un script con `use_blueprint`, que la 1.1.2 guardaba y HA acepta, queda bloqueado sin salida. El fail-closed no protege nada en ese caso: el `POST /api/config/automation|script/config/<id>` valida con las MISMAS funciones (`async_validate_config_item` con `raise_on_errors=True`, 400 si falla). Propuesta: con `unknown_command` (y solo con él), token con `validation: {"validated": [], "not_validated": [...], "note": "this Home Assistant cannot validate before saving; it validates when saving"}`, honesto por D-22; el resto de fallos sigue sin token. Test de los dos casos per FR-018, FR-010 (partial)
- [ ] T058 [BAJO] Las plataformas sin punto de `_PLATAFORMAS_SIN_PUNTO` que son integraciones (`template`, `sun`, `zone`, `geo_location`, `mqtt`, `tag`, `calendar`, `persistent_notification`) no pasan por `is_built_in`: HA carga su `trigger.py` con `async_get_integration`, que prefiere una integración personalizada con el mismo nombre. Así el `trigger: mqtt` de una `custom_components/mqtt` entra en una lista que dice excluir las personalizadas. Arreglo: la misma consulta de `manifest/get` para ellas (no para `state`, `numeric_state`, `event`, `time` y `time_pattern`, que HA traduce a `homeassistant`); test con una personalizada que sobrescribe `mqtt` per FR-009 (partial)
