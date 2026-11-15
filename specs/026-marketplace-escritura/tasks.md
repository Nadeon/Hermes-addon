---

description: "Tareas de la sub-feature 026 — escritura en el Marketplace (Hermes 1.2.0)"
---

# Tareas: escritura en el Marketplace (026)

**Entrada**: `specs/026-marketplace-escritura/` (spec.md, plan.md,
research.md, data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `DummyMCP` y el HA
simulado de `tests/test_tools_marketplace.py` (registra `type` y carga de cada
`ws_send` y responde errores con `code`), ampliado en la fixture con
`sv_request` (método, ruta, `json_body`, `timeout_seconds`) para los backups, y
`structlog.testing.capture_logs`. Datos ficticios: `ejemplo/tarjeta`,
`ejemplo/integracion`, `ejemplo/tarjeta-critica`, ids `"123456"`, `"234567"`,
`https://usuario:centinela-026@github.com/ejemplo/tarjeta`. Nada de la
instalación real; ninguna llamada a las tools MCP de Hermes conectadas.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`.
Línea base al especificar (2026-11-15, `feat/026-marketplace-escritura` en
`f108af0`): 3955 passed, 133 skipped, 6 failed (los 6 conocidos de Windows).
Cada tramo anota su propia línea base al empezar y termina con exactamente
esos 6 fallos en local; la referencia es el CI de Linux.

**Requisito previo (S-01)**: la 011, la 028 y la 030 integradas (lo están en
`f108af0`). Si otra sub-feature se ha integrado en `feat/cobertura-total`
antes de empezar un tramo y toca los ficheros comunes (`tool_families.py`,
`command_table.py`, `tools/__init__.py`, `_annotations.py`, `guide.py`,
`cobertura_escrituras.py`, matriz, CHANGELOG), traerla primero
(`git merge --no-ff`) y anotarlo.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 catálogo y avisos, US2 código instalado, US3 nada de
lo actual cambia.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado.

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **1** — catálogo y avisos | **T001–T015** | Familia `marketplace_manage`; `tools/_marketplace_write.py` (común); `ha_marketplace_acknowledge_critical`, `ha_marketplace_ignore_repository`, `ha_marketplace_remove_repository`, `ha_marketplace_refresh_repository`, `ha_marketplace_add_repository`; 6 entradas a `dedicated`; tema `marketplace_manage`; banco (reconocer ejecutado, cuatro no ejecutables, contrato de seis cargas) y matriz; inventario de la 033; CHANGELOG, DOCS, README y SECURITY (parte) |
| **2** — código instalado | **T016–T030** | Familia `marketplace_install`; backup previo; `ha_marketplace_install`, `ha_marketplace_uninstall`, `ha_marketplace_set_version`, `ha_marketplace_set_beta`; 4 entradas a `dedicated` (ninguna «spec 026»); textos de lectura (FR-018); tema `marketplace_install` y huella del tema `marketplace`; banco y matriz; documentación final y matriz de la 008 |

El tramo 2 necesita el tramo 1 integrado.

---

## Tramo 1 — catálogo y avisos (familia `marketplace_manage`)

### Preparación

- [ ] T001 Línea base: comprobar el requisito previo (S-01), ejecutar la suite y anotar passed/skipped/failed y la punta; comprobar que `grep -c "spec 026" hermes/src/hermes/command_table.py` da 10 y que la tabla regenerada no cambia antes de tocar nada
- [ ] T002 [P] [US3] Tests en `tests/test_tool_families.py`: `marketplace_manage` existe, `desde="1.2.0"`, desactivable, módulos `("marketplace_manage",)`, `familia_de_modulo("marketplace_manage") == "marketplace_manage"`, distinta de `marketplace`; en `tests/test_config_validation.py`, `tool_families_disabled: [marketplace_manage]` es válido. Después, la familia en `hermes/src/hermes/tool_families.py` con un comentario del porqué (research R-3) (FR-020)

### Tests (escritos antes, en rojo)

- [ ] T003 [P] [US1] Fixture `tests/fixtures/marketplace_escritura.py`: HA simulado con la forma de 2026.11.1 (`marketplace/info` con `warning_accepted` y `github_connected` configurables; `repositories/list` por categoría —responde solo la categoría pedida— con un personalizado no instalado `"234567"` `ejemplo/tarjeta` `plugin`, una integración instalada `"123456"` `ejemplo/integracion` con `domain: "ejemplo"` y `config_flow`, uno del catálogo por defecto no instalado; `repositories/removed` con una retirada normal y una `critical`; `critical/list` con `ejemplo/tarjeta-critica` sin reconocer y otra reconocida; `repositories/detect` → `{"categories": [...]}`; errores por código: `unknown_command`, `not_loaded`, `warning_not_accepted`, `github_not_connected`, `github_rate_limited`, `repository_not_found`, `core_repository`, `app_repository`, y un error cuyo texto repite `centinela-026`), y tests de funciones puras en `tests/test_marketplace_write_comun.py`: la guarda de `_WRITE_SUFFIXES` (un sufijo fuera → `RuntimeError` sin enviar); las cargas exactas de data-model para los seis comandos del tramo; validadores de `repository_id` (`"123456"`, `123456` → texto; `True`, `""`, `"../x"`, 65 caracteres → error), de `category` y de `owner/repo`; la URL de GitHub: válidas (`ejemplo/tarjeta`, `https://github.com/Ejemplo/Tarjeta` → `ejemplo/tarjeta`, con `.git`, con `/` final, con `www.`, con `usuario:clave@`, con espacios en los extremos) e inválidas (`http://github.com/a/b`, `https://gitlab.com/a/b`, `https://notgithub.com/a/b`, `https://github.com.example.com/a/b`, `https://github.com/a`, `https://github.com/a/b/tree/main`, `https://github.com/a/b?x=1`, `https://github.com/a/b#x`, `https://u:p/ss@github.com/a/b`, `.x/y`, 2049 caracteres) → `invalid_argument` con `field: "repository"` sin el valor en el `detail`; la traducción de códigos de HA de data-model «Errores» (FR-001, FR-002, FR-005, FR-006, FR-012)
- [ ] T004 [P] [US1] Tests en `tests/test_tools_marketplace_manage.py` (`TestReconocer`, `TestIgnorar`): reconocer → vista previa con la entrada, `reversible: false`, `_third_party_text` con `reason` y `link`, sin enviar `critical/acknowledge`; confirmación → `marketplace/critical/acknowledge` con `{"repository": "ejemplo/tarjeta-critica"}` y la entrada devuelta; `not_critical` y `already_acknowledged` sin token; si la entrada cambia entre vista previa y confirmación (pasa a reconocida), el token no vale y no se envía nada (`estado`); `repository` inválido → `invalid_argument` sin llamadas. Ignorar → vista previa con `removed` (`reason`, `removal_type` recortados y marcados), `reversible: false`; confirmación → `marketplace/repository/ignore` con el id; `repository_not_found`, `repository_not_removed` y `critical_repository` (con la pista de `ha_marketplace_acknowledge_critical`) sin token (FR-004, FR-005, FR-008, FR-009)
- [ ] T005 [P] [US1] Tests en `tests/test_tools_marketplace_manage.py` (`TestQuitar`, `TestRefrescar`): quitar el personalizado no instalado → vista previa y, con token, `marketplace/repositories/remove`; el instalado → `repository_installed` con la pista de `ha_marketplace_uninstall`; uno del catálogo por defecto → `not_custom_repository`; inexistente → `repository_not_found`; los tres sin token ni comando de escritura; si entre vista previa y confirmación pasa a instalado, el token no vale. Refrescar → vista previa con `contacts_github: true` y `backup.will_create: false`; confirmación → `marketplace/repository/refresh`; `github_rate_limited` al confirmar → explicado y token fallido (FR-004, FR-010, FR-011)
- [ ] T006 [P] [US1] Tests en `tests/test_tools_marketplace_manage.py` (`TestAnadir`): con aviso y GitHub → vista previa con la URL tapada (`***REDACTED***`), `full_name: "ejemplo/tarjeta"`, `credentials_hidden: true`, `credentials_sent: false`, `detected_categories`, `third_party: true` y el aviso, y `repositories/detect` enviado con `{"repository": "ejemplo/tarjeta"}`; confirmación → `marketplace/repositories/add` con `{"repository": "ejemplo/tarjeta", "category": "plugin"}` y el repositorio releído; aviso sin aceptar → `marketplace_warning_not_accepted` sin token y sin `detect` (el `detail` nombra al usuario del Supervisor, que Hermes nunca acepta y la interfaz del Marketplace); GitHub sin conectar → `github_not_connected` sin token; ya añadido → `repository_already_added`; categoría no detectada → `category_not_detected` con las detectadas; `core_repository` y `app_repository` sin token; token de otra URL con el mismo `owner/repo` → rechazado; el centinela `centinela-026` no aparece en la vista previa, la respuesta, ningún error (también el que lo repite), el fichero del token guardado ni ninguna carga enviada a HA (FR-003, FR-004, FR-006, FR-012; SC-004)
- [ ] T007 [P] [US1] Tests comunes en `tests/test_tools_marketplace_manage.py` (`TestComun`): para las cinco, `unknown_command` → `marketplace_write_unsupported` sin probar ningún `hacs/*`; `not_loaded` → `marketplace_not_loaded`; ningún `type` enviado empieza por `hassio/` o `supervisor/` ni es `marketplace/warning/accept` o `marketplace/github/connect`; la vista previa no envía ningún sufijo de escritura; evento `marketplace_write` con `tool`, `outcome` y `category`, y nunca el id, el `full_name`, la URL ni el centinela (`capture_logs`) (FR-001, FR-002, FR-007)

### Implementación

- [ ] T008 [US1] `hermes/src/hermes/tools/_marketplace_write.py` (común, sin tools; data-model «Comandos», «Validación», «URL», «Errores», «Evento») y `hermes/src/hermes/tools/marketplace_manage.py` (`register(mcp, ha_client, *, response_max_bytes)`, cinco tools con docstrings en inglés según contracts/tools.md, `create_confirmation_token`/`resolve_confirmation_token` con `estado` y `complete_confirmation_token`, salida por `tapar_en_estructura`). Reutiliza de `tools/marketplace.py` `_list_catalog`, `_summaries`, `_third_party`, `_trim`, `_REPOSITORY_ID_RE` y `MARKETPLACE_CATEGORIES` sin moverlos ni ampliar `_ALLOWED_SUFFIXES`. T003–T007 en verde (FR-001…FR-012)
- [ ] T009 [US1] [US3] Registro en `hermes/src/hermes/tools/__init__.py` dentro de la comprobación de la familia `marketplace_manage`; `hermes/src/hermes/tools/_annotations.py`: las cinco en `_DESTRUCTIVE_EXACT` y refrescar y añadir en `_OPEN_WORLD`, con el comentario de la regla del prefijo. Tests en `tests/test_tools_registration.py`: las cinco registradas por defecto con las anotaciones exactas de contracts/tools.md y con `confirmation_token`; ninguna con `marketplace_manage` desactivada; una tool ficticia `ha_marketplace_xyz` no recibe `readOnlyHint`; SC-005 de la 011 en verde (familias 1.2.0 desactivadas → lista y anotaciones de la 1.1.2); recuentos y «las únicas tools de más» actualizados (FR-020, FR-021)
- [ ] T010 [US1] Inventario de la 033: las cinco en `tests/test_confirmation_args_inventory.py` (todos sus argumentos `atado`; `repository` de añadir, la URL completa) con su párrafo de recuento; `tests/test_allow_dangerous_inventario.py` (018) en verde sin cambios porque ninguna lo usa (FR-024)
- [ ] T011 [US1] Tests en `tests/test_command_table.py` y `tests/test_generar_tabla.py`, y después `hermes/src/hermes/command_table.py` y `_DEDICADAS_INICIALES` de `scripts/inventario/generar_tabla.py`: las seis entradas del tramo 1 de data-model a `dedicated` con tool, familia `marketplace_manage`, `cap="CAP-075"` y motivo (`detect` con `_ConMatiz`); `github/connect` y `warning/accept` siguen `deny` clase D; `ha_call_ws_command("marketplace/repositories/add", …)` → `use_dedicated_tool` sin llamada, y con `marketplace_manage` desactivada, `family_disabled`; ejecutar el generador y comprobar que la tabla no cambia (`git diff --exit-code`, salvo finales de línea); `grep -c "spec 026"` da 4 (FR-019)
- [ ] T012 [US1] Guía: tests en `tests/test_tools_guide.py` (tema `marketplace_manage` —uno por familia nueva, FR-011 de la 008— con las cinco tools, la condición del aviso de riesgos y del usuario del Supervisor, que las credenciales de la URL no se envían, ignorar frente a reconocer, quitar solo personalizados no instalados; alias `marketplace write`, `hacs install`, `critical`, `custom repository`, `repositorio personalizado`; el índice lo nombra, con el mecanismo de marcadores `@TEMA_…@` del índice y de las instrucciones (019, 030) para que los temas existentes no cambien; las instrucciones del servidor lo nombran solo con la familia activa; los temas que no se tocan no cambian —huellas—); después, `hermes/src/hermes/tools/guide.py` (FR-022)
- [ ] T013 Control negativo del tramo 1, anotando recuentos: (a) quitar la guarda de `_WRITE_SUFFIXES` y enviar `warning/accept` desde una tool → cae el de la guarda; (b) no comprobar `warning_accepted` en la vista previa de añadir → caen los de `marketplace_warning_not_accepted`; (c) enviar la URL completa a HA en vez de `owner/repo` → cae el del centinela en las cargas; (d) no tapar la parte de usuario en la vista previa → caen los del centinela; (e) quitar `estado` del token de quitar → cae el de cambio entre vista previa y confirmación; (f) aceptar ignorar un no retirado → cae `repository_not_removed`; (g) añadir `ha_marketplace_` a `_READ_ONLY_PREFIXES` → cae el de la tool ficticia; (h) dejar `marketplace/repositories/add` como `deny` → cae el de la tabla. Restaurar y comprobar verde
- [ ] T014 [US1] Banco y matriz: `tests/banco/cobertura_026.py` (`MODULOS_026 = ("marketplace_manage",)` en el tramo 1; `PROBADAS_026 = {"ha_marketplace_acknowledge_critical"}`; `NO_EJECUTABLES_026` con ignorar, quitar, refrescar y añadir y el motivo de research R-11), sumado en `tests/test_banco_cobertura_escrituras.py` y en `TOOLS_EXIGIDAS_DEL_JOB` de `tests/banco/cobertura_escrituras.py` (y en `tests/test_banco_cobertura.py` si los módulos de familia lo exigen); semilla `tests/banco/ha_config/.storage/marketplace.critical` (formato `Store` v1, clave `marketplace.critical`, una entrada `ejemplo/tarjeta-critica` sin reconocer, `link` `https://example.com/aviso`) con un comentario en `tests/banco/ha_config/configuration.yaml` que diga por qué existe; `tests/banco/test_banco_marketplace.py`: (1) lee `marketplace/info` por el lector y anota el estado del Marketplace del banco; (2) reconoce el crítico con la tool (vista previa y token) y el lector ve `acknowledged: true` en `critical/list` y, si el aviso `critical_repository_ejemplo/tarjeta-critica` existía en Repairs, que ya no está; (3) contrato: el lector envía la carga de cada comando del tramo 1 (funciones `carga_*` del módulo común) con un repositorio inexistente y comprueba un error del manejador, nunca `invalid_format` ni `unknown_command` (salvo `critical/acknowledge`, que responde con éxito y la lista sin cambios). Filas en la matriz de `docs/HOJA-DE-RUTA.md` (orden alfabético): reconocer `banco de Core | ok`, las cuatro `instalación real | pendiente` con la nota «no ejecutable en el banco: <motivo de R-11>» (el test de la matriz admite, para un `NO_EJECUTABLES*`, «banco de Core / no ejecutable» o un entorno fuera del banco; la prueba que falta es la de una instalación real con internet). `tests/test_matriz_pruebas.py` y los invariantes del banco en verde. Si HA falla al reconocer, es un HALLAZGO (`xfail` estricto que espera ese fallo, patrón de la 028); si lo que falla es la semilla (el banco no la lee), reconocer pasa a `NO_EJECUTABLES_026` con ese motivo, sin `xfail`, y se anota en las notas (FR-023)
- [ ] T015 Documentación y cierre del tramo 1: sección «Escritura en el Marketplace» en `## [1.2.0] — <fecha de publicación>` de `hermes/CHANGELOG.md` (las cinco tools, familia nueva, credenciales de la URL, el hallazgo del aviso por usuario) y recuentos de la tabla del bloque de la 011; `hermes/DOCS.md` (familia `marketplace_manage` en `tool_families_disabled`); `README.md` y `README.es.md` (recuento de tools y familia, los dos iguales); `SECURITY.md` (viñeta de código de terceros del Marketplace en «Defence in depth»); `docs/HOJA-DE-RUTA.md`, estado de la 026 «en curso: tramo 1». Suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII), commit con los recuentos de T013 y el resultado de la regeneración de T011 (FR-025)

### Notas del tramo 1 (al cerrar)

(Las escribe el agente del tramo: línea base, desviaciones, recuentos del
control negativo, estado del Marketplace en el banco.)

---

## Tramo 2 — código instalado (familia `marketplace_install`)

### Preparación

- [ ] T016 Línea base del tramo 2 con el tramo 1 integrado; `grep -c "spec 026"` da 4; leer las notas del tramo 1 (estado del Marketplace en el banco)
- [ ] T017 [P] [US3] Tests en `tests/test_tool_families.py` y `tests/test_config_validation.py` para `marketplace_install` (como T002); después, la familia en `hermes/src/hermes/tool_families.py` (FR-020)

### Tests (escritos antes, en rojo)

- [ ] T018 [P] [US2] Fixture (ampliar `tests/fixtures/marketplace_escritura.py`: `manifest/get` con `is_built_in` configurable; `repository/releases` con una estable y una prerelease, y con `github_rate_limited`; `config_entries/get` con y sin entradas del `domain`; repositorios con `can_install: false`, con `status: "pending-restart"` al releer, de categoría `theme` y `template`; Supervisor simulado de `POST /backups/new/partial` que responde `{"slug": …}`, error, o tarda más que la espera) y tests puros en `tests/test_marketplace_write_comun.py`: cargas de instalar (sin `version`; con `version`; `confirm_replace_built_in` solo con `replace_built_in`), desinstalar, versión y betas; validador de `version` (`v1.2.3`, `main`, un commit → válidos; `""`, `"a b"`, `"x?y"`, `"#1"`, `"50%"`, `"a\\b"`, `".x"`, `"a/.b"`, 201 caracteres → error); `reinicio_probable` por categoría y por `config_flow`/cargada; nombre del backup con la forma `hermes_marketplace_<acción>_<AAAAMMDDTHHMMSSZ>` y sin el repositorio (FR-013…FR-017)
- [ ] T019 [P] [US2] Tests en `tests/test_tools_marketplace_install.py` (`TestInstalar`): con aviso → vista previa de data-model (`action` `install`/`reinstall`/`change_version`, `target_version`, `third_party`, `warning`, `replaces_built_in`, `restart`, `backup`, `_third_party_text`) y ningún comando de escritura; `version_check` solo con una versión distinta de la disponible (`in_releases`, `prerelease`; `checked: false` con `github_rate_limited`); sin aviso → `marketplace_warning_not_accepted` sin token y sin `manifest/get`; `cannot_install`, `repository_not_found` y `replaces_built_in` (sin `replace_built_in`) sin token; con `replace_built_in=true` la vista previa lo destaca y la carga lleva `confirm_replace_built_in: true`; confirmación → primero `POST /backups/new/partial` con `homeassistant: true`, `homeassistant_exclude_database: true`, `background: false`, nombre genérico y `timeout_seconds` = `_LONG_OP_TIMEOUT`, después `marketplace/repository/install`; respuesta con `restart_required` del `status` releído y `backup.slug`; backup con error o sin terminar → `backup_failed` (con `job_id` si lo hay), **sin** comando de instalar y token fallido; `backup=false` → sin backup y la vista previa lo avisa; versión instalada o disponible cambiada entre vista previa y confirmación → token rechazado sin backup ni comando; `warning_not_accepted`, `replaces_built_in`, `repository_busy` y `github_rate_limited` de HA al confirmar → traducidos y token fallido (FR-003, FR-004, FR-013, FR-017; SC-003, SC-005)
- [ ] T020 [P] [US2] Tests en `tests/test_tools_marketplace_install.py` (`TestDesinstalar`, `TestFijarVersion`, `TestBetas`): desinstalar → `repository_not_installed` y `repository_in_use` (con la pista de `ha_delete_config_entry`) sin token; vista previa con `removes` (con el recurso de Lovelace en `plugin`), `restart` y `backup`; funciona sin el aviso aceptado; confirmación → backup y `marketplace/repository/uninstall`; backup fallido → sin comando. Fijar versión → sin aviso, `marketplace_warning_not_accepted`; vista previa con `installed_version`, `available_version`, `new_selection`, `installs_nothing` y `next`; confirmación → `marketplace/repository/version`. Betas → igual con `show_beta`; `show_beta` no booleano → `invalid_argument` sin llamadas; confirmación → `marketplace/repository/beta` (FR-003, FR-014, FR-015, FR-016)
- [ ] T021 [P] [US2] Tests comunes de las cuatro (`TestComun`): `unknown_command` → `marketplace_write_unsupported` sin `hacs/*`; ningún `type` con `hassio/`/`supervisor/`, `warning/accept` ni `github/connect`; evento `marketplace_write` sin id, `full_name`, versión ni textos (FR-001, FR-007)
- [ ] T022 [P] [US3] Tests de los textos de lectura en `tests/test_tools_marketplace.py` y `tests/test_tools_hacs.py`: `how_to_update` y las descripciones de `ha_marketplace_list_updates` y `ha_hacs_list_updates` nombran `ha_marketplace_install`, ya no dicen «does not install anything» y conservan «update», «install», «confirmation_token» y «never accepts»; `_ALLOWED_SUFFIXES` no cambia y `TestOnlyAllowedCommands` sigue en verde; esquemas de entrada iguales a `tests/fixtures/esquemas_1_1_2.json` (FR-018)

### Implementación

- [ ] T023 [US2] `hermes/src/hermes/tools/_marketplace_write.py` (backup previo, reinicio probable, cargas, validador de versión) y `hermes/src/hermes/tools/marketplace_install.py` (cuatro tools según contracts/tools.md); registro en `tools/__init__.py` con la familia; las cuatro en `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD`. T018–T021 en verde (FR-001…FR-007, FR-013…FR-017, FR-021)
- [ ] T024 [US3] `hermes/src/hermes/tools/marketplace.py` (`_HOW_TO_UPDATE` y descripción de `ha_marketplace_list_updates`) y `hermes/src/hermes/tools/hacs.py` (descripción de `ha_hacs_list_updates`), solo textos. T022 en verde (FR-018)
- [ ] T025 [US2] [US3] Registro, inventario y tabla: tests en `tests/test_tools_registration.py` (las cuatro con las anotaciones de contracts/tools.md y `confirmation_token`; ninguna con `marketplace_install` desactivada; SC-005 de la 011; `TestDedicadas` con todas las familias activas); las cuatro en `tests/test_confirmation_args_inventory.py`; tests en `tests/test_command_table.py`/`tests/test_generar_tabla.py` y después las cuatro entradas del tramo 2 a `dedicated` (familia `marketplace_install`) en `command_table.py` y en `_DEDICADAS_INICIALES`; ninguna entrada con «spec 026»; regenerar la tabla sin cambios (FR-019, FR-020, FR-021, FR-024)
- [ ] T026 [US2] [US3] Guía: tests en `tests/test_tools_guide.py` (tema nuevo `marketplace_install` con las cuatro tools, la condición del aviso y del usuario del Supervisor, el backup parcial sin base de datos y qué pasa si falla, el reinicio y que Hermes no reinicia, `replace_built_in`; el índice lo nombra y las instrucciones del servidor solo con su familia activa; el tema `marketplace` ya no dice que Hermes no instala nada y remite a `marketplace_manage` y `marketplace_install`; su huella actualizada en la tabla de huellas con el comentario de la 026; alias `install`, `uninstall`, `instalar`, `desinstalar`, `hacs install`); después, `hermes/src/hermes/tools/guide.py` (FR-018, FR-022)
- [ ] T027 [US2] Banco y matriz: `MODULOS_026` con `marketplace_install`; las cuatro en `NO_EJECUTABLES_026` con el motivo; contrato del banco con las cuatro cargas del tramo 2 (con un repositorio inexistente: `warning_not_accepted` o `repository_not_found`, nunca `invalid_format` ni `unknown_command`); sus filas `instalación real | pendiente` con la nota del motivo en la matriz (orden alfabético); los tests de la matriz y del banco en verde (FR-023)
- [ ] T028 Control negativo del tramo 2, anotando recuentos: (a) enviar el comando de instalar aunque el backup falle → cae el de `backup_failed`; (b) no comprobar el aviso en la vista previa de instalar → caen los de `marketplace_warning_not_accepted`; (c) mandar `confirm_replace_built_in: true` siempre → cae el de la carga; (d) quitar `available_version` del `estado` → cae el del cambio de versión; (e) no rechazar `repository_in_use` → cae el de desinstalar; (f) dejar el texto «does not install anything» en `how_to_update` → cae el de FR-018; (g) dejar `marketplace/repository/install` como `deny` → cae el de la tabla; (h) incluir el `full_name` en el nombre del backup → cae el de la forma del nombre. Restaurar y comprobar verde
- [ ] T029 Documentación final: completar la sección de la 026 en el CHANGELOG (las cuatro tools, backup previo, reinicio, `replace_built_in`, textos de lectura, prueba en vivo pendiente); `docs/HOJA-DE-RUTA.md`: estado «hecha» de la 026 con un resumen como el de la 030 y la viñeta de pendientes de la 026 con las pruebas en vivo de research R-12 y la duda D-1; `hermes/DOCS.md` y `README.md`/`README.es.md` sincronizados (recuento y las dos familias); fila CAP-075 de la matriz de `specs/008-cobertura-total/plan.md` con las tools y los ficheros de test, sin cambiar sus columnas de sub-feature ni de vía (las lee `_matriz_008`), y la limitación de R-2 anotada (FR-025)
- [ ] T030 Cierre del tramo 2: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII), commit con los recuentos de T028 y el resultado de la regeneración de T025

### Notas del tramo 2 (al cerrar)

(Las escribe el agente del tramo.)

---

## Inventario de argumentos atados (referencia para T010 y T025)

- `ha_marketplace_acknowledge_critical` → `repository`
- `ha_marketplace_ignore_repository` → `repository_id`
- `ha_marketplace_remove_repository` → `repository_id`
- `ha_marketplace_refresh_repository` → `repository_id`
- `ha_marketplace_add_repository` → `repository` (URL completa), `category`
- `ha_marketplace_install` → `repository_id`, `version`, `replace_built_in`, `backup`
- `ha_marketplace_uninstall` → `repository_id`, `backup`
- `ha_marketplace_set_version` → `repository_id`, `version`
- `ha_marketplace_set_beta` → `repository_id`, `show_beta`

Todos `atado`; ninguno exento.

---

## Dependencias y paralelismo

- T002–T007 en paralelo (ficheros distintos); T008 tras T003–T007; T009,
  T010 y T011 tras T008; T012 y T014 en paralelo tras T009.
- T017–T022 en paralelo; T023 tras T017–T021; T024 tras T022; T025 tras
  T023; T026 y T027 en paralelo tras T025.
- Fuera de esta sub-feature: cualquier otra que se integre a la vez toca los
  ficheros comunes de «Requisito previo».
