---

description: "Tareas de la sub-feature 030 — tienda de apps (Hermes 1.2.0)"
---

# Tareas: tienda de apps (030)

**Entrada**: `specs/030-tienda-de-apps/` (spec.md, plan.md, research.md,
data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `DummyMCP`, un
`MockHAClient` (el de `tests/test_tools_supervisor.py`, ampliado en la
fixture para registrar método, ruta, `json_body` y `timeout_seconds`, y para
responder errores con `status`; distingue `sv_request` de `sv_request_text`) como **Supervisor simulado** con respuestas de la forma
del Supervisor 2026.11.0, y `structlog.testing.capture_logs`. Datos
ficticios: `https://example.com/repo-ficticio`, `abcd1234`,
`abcd1234_ejemplo`, `local_ejemplo`, centinelas de texto
(`centinela-clave-1`). Nada de la instalación real; ninguna llamada a las
tools MCP de Hermes conectadas.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`.
Línea base al especificar (2026-11-14, `feat/030-tienda-de-apps` en
`02beafc`): 2531 passed, 67 skipped, 6 failed (los 6 conocidos de Windows).
Cada tramo anota su propia línea base al empezar y termina con exactamente
esos 6 fallos en local; la referencia es el CI de Linux.

**Requisito previo (S-01)**: la 011 completa y la 014 integradas (lo están
en `02beafc`). Si la 015 o la 027 se han integrado en `feat/cobertura-total`
antes de empezar un tramo, traerlas primero (`git merge --no-ff`) y anotarlo.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 repositorios, US2 ficha de una app, US3
reconstruir y validar opciones, US4 nada de lo actual cambia.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado.

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **1** — repositorios y recarga (CAP-082, parte) | **T001–T014** | Familia `app_store` con `store_repositories`; `tools/_store.py` (puras); `sv_list_store_repositories`, `sv_add_store_repository`, `sv_remove_store_repository`, `sv_repair_store_repository`, `sv_reload_store`; 7 entradas a `dedicated`; tema de guía (parte); 4 tools en banco/matriz; CHANGELOG, DOCS, README y SECURITY (parte) |
| **2** — fichas, disponibilidad, reconstrucción y vistas previas (CAP-082 resto, CAP-093) | **T015–T028** | `store_apps` con `sv_get_addon_changelog`, `sv_get_addon_documentation`, `sv_get_addon_availability`, `sv_rebuild_addon`; vistas previas de `sv_install_addon`, `sv_update_addon` y `sv_set_addon_options`; 8 entradas a `dedicated` (ninguna «spec 030»); guía completa; `sv_rebuild_addon` en banco/matriz; documentación final y matriz de la 008 |

El tramo 2 necesita el tramo 1 integrado.

---

## Tramo 1 — repositorios y recarga (CAP-082, parte)

### Preparación

- [x] T001 Línea base: comprobar el requisito previo (S-01), ejecutar la suite y anotar passed/skipped/failed y la punta; comprobar que `grep -c "spec 030" hermes/src/hermes/command_table.py` da 15
- [x] T002 [P] [US4] Tests en `tests/test_tool_families.py`: `app_store` existe, `desde="1.2.0"`, desactivable, módulos `("store_repositories",)`, `familia_de_modulo("store_repositories") == "app_store"`; en `tests/test_config_validation.py`, `tool_families_disabled: [app_store]` es válido. Después, la familia en `hermes/src/hermes/tool_families.py` con un comentario del porqué (research R-1) (FR-015)

### Tests (escritos antes, en rojo)

- [x] T003 [P] [US1] Fixture `tests/fixtures/supervisor_tienda.py` (forma del Supervisor 2026.11.0, datos ficticios: `GET /store/repositories` con `core`, `local`, `a0d7b954` y `abcd1234` —este con `source` `https://usuario:centinela-clave-1@example.com/repo-ficticio`—, `GET /store/addons` con apps de cada uno, unas instaladas y otras no) y tests en `tests/test_tools_store_repositories.py` (`TestListar`) y `tests/test_store_comun.py` (puras de `tools/_store.py`): sobre `{count, items, truncated}`; `builtin` verdadero exactamente para los cinco `slug` integrados; `apps_count` e `installed_apps` por repositorio; orden; `_third_party_text` con `name`, `url`, `maintainer` y el aviso de `tools/marketplace.py`; la contraseña de `source`/`url` sale como `***REDACTED***` y el centinela no aparece en ninguna parte de la respuesta; `repository="abcd1234"` → `GET /store/repositories/abcd1234` y un solo objeto; 404 → `repository_not_found`; `repository` inválido (`"../x"`, `""`) → `invalid_identifier` sin llamada; `GET /store/addons` con error → lista con `apps_count: null` y `apps_unavailable`; lista grande recortada por `response_max_bytes` con `truncated` (FR-001, FR-017, FR-018, FR-019)
- [x] T004 [P] [US1] Tests en `tests/test_tools_store_repositories.py` (`TestAnadir`): URL válidas (`https://example.com/repo-ficticio`, con `#main`, con `#feature/x-1.2`, con espacios en los extremos) → vista previa; inválidas (`""`, `"   "`, `"ftp://example.com/x"`, `"file:///tmp/x"`, `"example.com/x"`, `"https://"`, `"https://example.com/a b"`, `"https://example.com/x#"`, `"https://example.com/x#rama con espacio"`, 2049 caracteres) → `invalid_argument` con `field: "repository"`, sin copiar el valor y **sin ninguna llamada**; ya añadida (misma URL en mayúsculas, `https://github.com/home-assistant/apps` y `…/addons`) → `repository_already_added` sin token y sin `POST`; vista previa con `repository` (contraseña tapada), `host`, `branch`, `credentials_hidden` (verdadero solo con contraseña), `warning` (contiene «Third-party», «not reviewed», que no instala nada) y token, sin `POST`; confirmación → `POST /store/repositories` con `{"repository": <URL exacta con la contraseña real>}` y `timeout_seconds` = `_LONG_OP_TIMEOUT`; respuesta con el repositorio releído y `_third_party_text`; error del Supervisor que repite la URL con la contraseña → `error` sin el centinela y token completado como fallido; token de otra URL → rechazado (FR-002, FR-018, FR-019)
- [x] T005 [P] [US1] Tests en `tests/test_tools_store_repositories.py` (`TestQuitar`, `TestReparar`, `TestRecargar`): quitar uno inexistente → `repository_not_found`; los cinco integrados → `builtin_repository`; uno con apps instaladas → `repository_in_use` con la lista (`slug`, `name`) y la pista de `sv_uninstall_addon`; en los tres, sin token y sin `DELETE`; vista previa con el repositorio, `apps_count`, `effect` y `_third_party_text`; confirmación → `DELETE /store/repositories/abcd1234`; si entre vista previa y confirmación aparece una app instalada de ese repositorio, el token no vale y no hay `DELETE` (`estado`); reparar → `POST /store/repositories/abcd1234/repair` sin token; `local` → `not_supported` sin llamada; inexistente → `repository_not_found` sin `POST`; recargar → `POST /store/reload` con la espera larga y la pista; errores del Supervisor redactados (FR-003, FR-004, FR-005, FR-018)
- [x] T006 [P] [US1] Tests del log en `tests/test_tools_store_repositories.py` con `capture_logs`: un evento `app_store_action` por llamada con `tool`, `outcome` y `repository` (slug); en añadir, nunca la URL, el servidor ni el centinela; en un rechazo, `outcome="rejected:<código>"` (FR-018)

### Implementación

- [x] T007 [US1] `hermes/src/hermes/tools/_store.py` (puras: `es_integrado`, `tapar_credenciales`, `texto_de_terceros`) y `hermes/src/hermes/tools/store_repositories.py`: `register(mcp, ha_client, *, response_max_bytes)`, `_validar_url_repositorio`, `_resumen_repositorio`, `_repositorios_y_apps`, cinco tools con docstrings en inglés según contracts/tools.md («app (add-on)»), vistas previas con `create_confirmation_token` (con `estado` en quitar), `validate_slug`, sobre común, redacción, evento de log. T003–T006 en verde (FR-001…FR-005, FR-017…FR-019, FR-021)
- [x] T008 [US1] [US4] Registro en `hermes/src/hermes/tools/__init__.py` dentro de la comprobación de la familia `app_store` (patrón de la 011/013); `hermes/src/hermes/tools/_annotations.py` según contracts/tools.md con su comentario. Tests en `tests/test_tools_registration.py`: las cinco registradas por defecto con las anotaciones exactas de contracts/tools.md; añadir y quitar con `confirmation_token`, reparar y recargar sin él; ninguna con `app_store` desactivada; SC-005 de la 011 en verde (con las familias 1.2.0 desactivadas, la lista y las anotaciones son las de la 1.1.2); recuentos y «las únicas tools de más» actualizados (FR-015, FR-016)
- [x] T009 [US1] [US4] Tests en `tests/test_command_table.py` y después `hermes/src/hermes/command_table.py`: las siete entradas del tramo 1 de data-model a `dedicated` con tool, familia `app_store`, `cap="CAP-082"` y motivo; iconos, logos y alias legados siguen `deny`; `sv_read_api("/store/repositories")` y `sv_call_api("POST", "/store/reload")` → `use_dedicated_tool` sin llamada, y con `app_store` desactivada, `family_disabled`; ejecutar `scripts/inventario/generar_tabla.py` y comprobar que la tabla no cambia (`git diff --exit-code`, salvo finales de línea); `grep -c "spec 030"` da 8 (FR-014)
- [x] T010 [US1] Guía: tests en `tests/test_tools_guide.py` (tema `app_store` con las cinco tools, el aviso de terceros al añadir, quitar exige desinstalar antes, reparar frente a recargar; alias `store`, `tienda`, `repositories`, `repository`, `repositorios`; el índice lo nombra; las instrucciones del servidor lo nombran solo con la familia activa; los temas de la 1.1.2 que no se tocan no cambian —huellas—); después, `hermes/src/hermes/tools/guide.py` (FR-020)
- [x] T011 [US1] Banco y matriz: `_SV_TIENDA` (motivo: la tienda y los repositorios solo existen en el Supervisor real, con internet; se prueba con simuladores y en la VM de la 014) en `FUERA_DEL_BANCO` de `tests/banco/cobertura_escrituras.py` para `sv_add_store_repository`, `sv_remove_store_repository`, `sv_repair_store_repository` y `sv_reload_store`; sus filas `VM` / `pendiente` en la matriz de `docs/HOJA-DE-RUTA.md` (orden alfabético); sus líneas en «Tools nuevas del programa» de `docs/BANCO-SUPERVISOR.md` (tanda 2, con la pauta de research «Pruebas en vivo» del plan). `tests/test_matriz_pruebas.py`, `tests/test_rutas_supervisor_rol.py` y los invariantes del banco en verde sin tocarlos (FR-022)
- [x] T012 Control negativo del tramo 1, anotando recuentos: (a) aceptar cualquier esquema en la URL → caen los de URL inválida; (b) no tapar la contraseña → caen los del centinela; (c) emitir token con apps instaladas → cae `repository_in_use`; (d) quitar `estado` del token → cae el de cambio entre vista previa y confirmación; (e) comparar URLs distinguiendo mayúsculas → cae el de ya añadida; (f) registrar la URL en el evento → cae el del log; (g) dejar `POST /store/repositories` como `deny` → cae el de la tabla. Restaurar y comprobar verde
- [x] T013 Documentación del tramo 1: sección «Tienda de apps» en `## [1.2.0] — <fecha de publicación>` de `hermes/CHANGELOG.md` (las cinco tools, familia nueva, aviso de terceros) y recuentos de la tabla del bloque de la 011; `hermes/DOCS.md`, familia `app_store` en la lista de `tool_families_disabled`; `README.md` y `README.es.md` (recuento de tools y familia, los dos iguales); `SECURITY.md`, viñeta de repositorios de la tienda en «Defence in depth»; `docs/HOJA-DE-RUTA.md`, estado de la 030 «en curso: tramo 1» (FR-023)
- [x] T014 Cierre del tramo 1: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII: nada de hostnames, IPs reales, slugs de una instalación, rutas `C:\`), commit con los recuentos de T012 y el resultado de la regeneración de T009


### Notas del tramo 1 (al cerrar)

- Línea base (T001): `feat/030-tienda-de-apps` con `feat/cobertura-total`
  traída (029 integrada, punta `8a101b7`): 2642 passed, 78 skipped, 6 failed
  (los 6 conocidos de Windows); `grep -c "spec 030"` daba 15. La 012, la 015,
  la 027 y la 033 no estaban integradas.
- Al cerrar: 2709 passed, 78 skipped, 6 failed (los mismos); `spec 030`, 8;
  regenerar la tabla con `scripts/inventario/generar_tabla.py` no cambia
  nada (0 entradas nuevas, 0 quitadas, fichero idéntico).
- Controles negativos (T012), tests que caen: (a) 2
  (`test_urls_invalidas_sin_llamada`, `TestLog.test_rechazo`); (b) 8 (los
  del centinela y del tapado); (c) 1 (`test_con_apps_instaladas_sin_token`);
  (d) 1 (`test_cambio_entre_vista_previa_y_confirmacion`); (e) 1
  (`test_ya_anadida_sin_token`, subtest de la URL en mayúsculas); (f) 1
  (`test_evento_de_anadir_sin_url`); (g) 4 (dos de `test_command_table.py`
  y dos de `test_tools_generic_commands.py`). Además: sin `@TEMA_TIENDA@`
  cae `TestTemaAppStore.test_indice_e_instrucciones`, y sin
  `sv_remove_store_repository` en `_DESTRUCTIVE_EXACT` caen 3 de
  `test_tools_registration.py` (entre ellos el invariante «pide token →
  destructiva»).
- Desviaciones: los tests de las genéricas con la tabla real (T009) van en
  `tests/test_tools_generic_commands.py`, que tiene el registro completo
  simulado; `tests/test_banco_cobertura_escrituras.py` fija recuentos (126
  tools que modifican y 24 en `FUERA_DEL_BANCO`) y pasa a 130 y 28 con su
  porqué; el bloque de la 011 del CHANGELOG daba recuentos de la tabla
  anteriores a la 029 (115/452 de Core): se ponen los reales (124/443 y
  64/136).
- Para la integración con la 033 (no integrada): filas de argumentos atados
  `sv_add_store_repository` → `repository` (la URL sin espacios en los
  extremos) y `sv_remove_store_repository` → `repository` (más `estado`:
  repositorio leído y apps instaladas).
- Duda para el final: una URL con un token como USUARIO y sin contraseña
  (`https://<token>@servidor/…`) sale tal cual, porque data-model dice que el
  usuario se conserva; la redacción general tampoco lo tapa.

---

## Tramo 2 — fichas, disponibilidad, reconstrucción y vistas previas (CAP-082 resto, CAP-093)

### Preparación

- [x] T015 Línea base del tramo 2 con el tramo 1 integrado; `grep -c "spec 030"` da 8; si la 027 está integrada, anotar que las descripciones de `tools/addons.py` ya dicen «app (add-on)» y partir de ellas

### Tests (escritos antes, en rojo)

- [x] T016 [P] [US2] Fixture (ampliar `tests/fixtures/supervisor_tienda.py`: ficha `GET /store/addons/{slug}` con y sin `documentation`, changelog y documentación de 50 000 caracteres con un centinela `password: centinela-clave-2` cerca del corte de 20 000, los textos exactos «No changelog found for app {slug}!» y «No documentation found for app {slug}!» con 200, y el mensaje de app inexistente con 200) y tests en `tests/test_tools_store_apps.py` (`TestChangelog`, `TestDocumentacion`): dos llamadas (ficha y texto) con `sv_request_text`; ficha 404/400 → `addon_not_found` sin pedir el texto; «No changelog found…» → `changelog_not_found`; `documentation: false` → `documentation_not_found` sin pedir el texto; trozos: `offset` 0, 20000 y 49990, `next_offset`, `truncated`, `total_chars`; `offset` fuera → `text: ""` y `truncated: false`; `offset=-1`, `max_chars=0` y `100001` → `invalid_argument` sin llamada; con `response_max_bytes` pequeño, la respuesta cabe; el centinela no sale en ningún trozo y `secrets_redacted: true`; `_third_party_text` con `name` y `text`; `version_latest` en la respuesta (FR-006, FR-007, FR-017…FR-019)
- [x] T017 [P] [US2] Tests en `tests/test_tools_store_apps.py` (`TestDisponibilidad`): disponible → `available: true`, `reason: null` y los campos de la ficha; 400 con «not supported on this platform…» → `available: false` y `reason` redactado; app inexistente → `addon_not_found`; nunca un `POST` (FR-008)
- [x] T018 [P] [US3] Tests en `tests/test_tools_store_apps.py` (`TestReconstruir`): con `GET /addons/{slug}/info` simulado, sin token y sin `POST`: inexistente (404) → `addon_not_found`; no instalada (el Supervisor devuelve la ficha de la tienda con `installed: false` y `state: "unknown"`) → `addon_not_installed`; `detached: true` → `addon_not_in_store`; `version` ≠ `version_latest` → `rebuild_version_changed` con las dos versiones; `build: false` sin `force` → `rebuild_not_supported` con la pista; vista previa con los campos de data-model y `effect` distinto para construir y para `force` sobre imagen; Hermes (`_es_hermes`) → `critical_warning`; confirmación → `POST /addons/{slug}/rebuild` con `{"force": false|true}` y la espera larga; `force` distinto al confirmar → token rechazado; error del Supervisor → `error` redactado y token fallido; evento `app_store_action` sin opciones ni textos (FR-012, FR-018)
- [x] T019 [P] [US2] [US3] [US4] Tests en `tests/test_tools_addons_tienda.py` (`TestInstalar`, `TestActualizar`, `TestSinVersion`, `TestValidarOpciones`, `TestDescripciones`): `sv_install_addon` → `addon_not_found`, `already_installed` y `addon_not_available` (con `reason`) sin token; vista previa con `name`, `version_latest`, `repository`, `build`, y `third_party_repository`/`warning` solo si el repositorio no es integrado; confirmación idéntica a la 1.1.2 (ruta, `json_body`, `timeout_seconds`); `sv_update_addon` → vista previa con `available` y `changelog_excerpt` (≤ 4000, redactado, `_third_party_text`); changelog que falla → `changelog_excerpt: null` y token; Hermes sigue con `self_update_not_supported` sin ninguna llamada; confirmación idéntica a la 1.1.2; `sv_set_addon_options` → `POST /addons/{slug}/options/validate` con las opciones finales sin envolver antes del token; `valid: false` con un mensaje que repite un secreto de las opciones (`Got 'centinela-clave-3'`) → `invalid_options` sin token, sin el centinela; `pwned: true` → `warning_pwned`; `pwned: null` → `pwned_check: "failed"`; error al validar → `validation.checked: false` y token; opciones finales `{}` → sin llamada a validar y `reason: "empty_options"`; confirmación idéntica a la 1.1.2 (no vuelve a validar); los esquemas de entrada de las tres coinciden con `tests/fixtures/esquemas_1_1_2.json`; las descripciones de instalar y actualizar dicen que es la versión de la tienda y no aceptan versión (FR-009…FR-011, FR-013, FR-021; SC-005)

### Implementación

- [x] T020 [US2] [US3] `hermes/src/hermes/tools/_store.py` (lecturas: `ficha_de_tienda`, `disponibilidad`, `texto_de_la_app`) y `hermes/src/hermes/tools/store_apps.py` (cuatro tools según contracts/tools.md); `store_apps` en la familia `app_store` y su descripción completa (`tool_families.py` y su test de T002); registro en `tools/__init__.py`; `sv_rebuild_addon` en `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD`. T016–T018 en verde (FR-006…FR-008, FR-012, FR-015…FR-019)
- [x] T021 [US2] [US3] [US4] `hermes/src/hermes/tools/addons.py`: vistas previas de `sv_install_addon`, `sv_update_addon` y `sv_set_addon_options` según data-model, con las lecturas de `tools/_store.py`; descripciones («a la versión de la tienda», validación en la vista previa, «app (add-on)» si la 027 no lo ha hecho); nada cambia con token. T019 en verde (FR-009…FR-011, FR-013, FR-021)
- [x] T022 [US2] [US3] Tests en `tests/test_command_table.py` y después `hermes/src/hermes/command_table.py`: las ocho entradas del tramo 2 de data-model a `dedicated` (tres con «el Supervisor 2026.11.0 ignora `{version}`» y la tool de la 1.1.2, familia `supervisor`); `sv_call_api("POST", "/store/addons/<slug>/install/1.0.0")` → `use_dedicated_tool` con `sv_install_addon`; ninguna entrada con «spec 030»; regenerar la tabla sin cambios (FR-011, FR-014)
- [x] T023 [US4] Tests en `tests/test_tools_registration.py` para las cuatro: registradas por defecto con las anotaciones de contracts/tools.md, `sv_rebuild_addon` con `confirmation_token` y `force`; ninguna con `app_store` desactivada; las tres de la 1.1.2 con las mismas anotaciones y esquemas; SC-005 de la 011 en verde; `TestDedicadas` en verde con todas las familias activas (FR-015, FR-016)
- [x] T024 [US2] [US3] Guía: tests en `tests/test_tools_guide.py` (el tema `app_store` nombra las nueve tools, que el changelog y la documentación son de la versión de la tienda y por trozos, la disponibilidad, reconstruir —local frente a `force` y qué pasa si falla— y que no se puede elegir versión, con la vuelta atrás por backup parcial; alias `changelog`, `documentation`, `rebuild`, `availability`; el tema `supervisor` remite a `app_store` y nombra la validación de opciones y las vistas previas de instalar y actualizar; `hermes_guide(topic="generic_commands", search="store")` lista las entradas `dedicated`); después, `hermes/src/hermes/tools/guide.py` (FR-011, FR-020)
- [x] T025 [US3] Banco y matriz de `sv_rebuild_addon`: `FUERA_DEL_BANCO` (motivo de apps), fila `VM` / `pendiente` y línea en la tanda 2 de `docs/BANCO-SUPERVISOR.md` (app local de prueba; con `force` sobre una de imagen); los tests de la matriz y del rol en verde (FR-022)
- [x] T026 Control negativo del tramo 2, anotando recuentos: (a) no reconocer «No changelog found…» → cae `changelog_not_found`; (b) redactar por trozos en vez de sobre el texto entero → cae el del centinela en el corte; (c) emitir token en `rebuild_version_changed` o sin `force` en una app de imagen → caen; (d) no validar opciones en la vista previa → caen los de `invalid_options`; (e) no quitar el secreto literal del mensaje de validación → cae el del centinela; (f) cambiar la petición de `sv_install_addon` con token (p. ej. sin `background`) → cae el de identidad con la 1.1.2; (g) dejar `POST /addons/{app}/rebuild` como `deny` → cae el de la tabla. Restaurar y comprobar verde
- [x] T027 Documentación final: completar la sección de la 030 en el CHANGELOG (cuatro tools, vistas previas de las tres de la 1.1.2, validación de opciones, la desviación de la versión concreta y que la prueba en vivo queda pendiente); `docs/HOJA-DE-RUTA.md`: estado «hecha» de la 030 con un resumen como el de la 013; `README.md` y `README.es.md` sincronizados (recuento y fila de apps); filas CAP-082 y CAP-093 de la matriz de `specs/008-cobertura-total/plan.md` con las tools y los ficheros de test, sin cambiar sus columnas de sub-feature ni de vía (las lee `_matriz_008`), y la desviación de FR-051 anotada en la fila de CAP-082 (FR-023)
- [x] T028 Cierre del tramo 2: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII), commit con los recuentos de T026 y el resultado de la regeneración de T022


### Notas del tramo 2 (al cerrar)

- Línea base (T015): `feat/030-tienda-de-apps` en `7c42e1e` (tramo 1
  integrado, sin traer `feat/cobertura-total`): 2709 passed, 78 skipped,
  6 failed (los 6 conocidos de Windows); `grep -c "spec 030"` daba 8. La
  027 no está integrada: las descripciones de `sv_install_addon`,
  `sv_update_addon` y `sv_set_addon_options` siguen en español y ganan
  «app (add-on)» en su primera línea (riesgo de fusión con la 027, S-04).
- Al cerrar: 2789 passed, 78 skipped, 6 failed (los mismos); `spec 030`, 0;
  regenerar la tabla con `scripts/inventario/generar_tabla.py` no cambia
  nada (0 entradas nuevas, 0 quitadas, fichero idéntico).
- Controles negativos (T026), tests que caen (subtests incluidos, sobre los
  ficheros de la 030, la tabla, las genéricas y `test_tools_supervisor.py`):
  (a) no reconocer «No … found» → 3 (`TestChangelog.test_sin_changelog`,
  `TestDocumentacion.test_texto_exacto_de_sin_documentacion`,
  `TestActualizar.test_sin_changelog`); (b) redactar por trozos → 2 (los
  dos del centinela en el corte); (c) token con `rebuild_version_changed`
  → 1, token de imagen sin `force` → 1; (d) no validar opciones → 6 (toda
  `TestValidarOpciones` salvo la confirmación); (e) no quitar el secreto
  literal → 2; (f) instalar sin `background` → 1
  (`TestInstalar.test_confirmacion_identica_a_la_1_1_2`); (g)
  `POST /addons/{app}/rebuild` como `deny` → 4 (dos de
  `tests/test_command_table.py` y dos subtests de
  `test_tramo_2_hacia_su_tool`). Extras del supervisor: token sin
  actualización → 1 (`test_sin_actualizacion_sin_token`); tapar solo la
  contraseña → 5 (`tests/test_store_comun.py`); sin
  `tapar_usuario_en_texto` → 2; sin `@_tapar_salida` → 1. Restaurado:
  todo verde.
- Extras del supervisor del programa (no estaban en la spec):
  - a) `sv_update_addon` de una app instalada sin actualización responde
    `already_up_to_date` con `version` y SIN token (antes daba token y una
    nota). Si `/info` no se puede leer o la app no tiene versión instalada,
    sigue como en la 1.1.2. Contradice la alternativa descartada de
    research R-3 y el principio IX del plan; lo pidió el supervisor.
  - b) la parte de usuario de la URL (`usuario:clave@`, `usuario@`,
    `token@`) se tapa ENTERA (`https://***REDACTED***@…`) en las cinco
    tools de repositorios (vistas previas, respuestas, errores, también el
    texto del Supervisor y el token suelto que repita) y nunca va al log.
    Tres capas: `tapar_credenciales`, la sustitución literal en
    `redactar_mensaje` (trozos de 4 caracteres o más; recargar relee los
    repositorios para conocer sus credenciales) y `@_tapar_salida` sobre
    todo lo que devuelven. `credentials_hidden` es verdadero con cualquier
    parte de usuario. El token sigue atado a la URL completa. Cierra la duda
    del tramo 1. Cambia `data-model` («el usuario se conserva»).
- Desviaciones: `sv_install_addon` con la tienda ilegible (no 404/400) da
  token con `store_check.checked: false` (fail-open, como la 1.1.2 y como
  `validation.checked: false`; los tests de la 1.1.2 lo exigen); la vista
  previa de reconstruir lleva además `state_after`; `sv_rebuild_addon` no
  relee `/info` al confirmar (el Supervisor vuelve a comprobar); las tres
  tools de la 1.1.2 con rutas `{version}` y la de validar entran en
  `_DE_LA_1_1_2_AMPLIADAS` de `tests/test_command_table.py`; los recuentos
  del bloque de la 011 del CHANGELOG pasan a 72/128 del Supervisor.
- Para la integración con la 033 (no integrada), filas de argumentos atados
  al token de TODAS las tools con token de la 030:
  `sv_add_store_repository` → `repository` (URL completa, credenciales
  incluidas, sin espacios en los extremos); `sv_remove_store_repository` →
  `repository` (+ `estado`: repositorio leído y apps instaladas);
  `sv_rebuild_addon` → `slug`, `force`; y sin cambios respecto a la 1.1.2:
  `sv_install_addon` → `slug`, `sv_update_addon` → `slug`,
  `sv_set_addon_options` → `slug`, `options`.

---

## Dependencias y paralelismo

- T002–T006 en paralelo (ficheros distintos); T007 tras T003–T006; T008 y
  T009 tras T007; T010 y T011 en paralelo tras T008.
- T016–T019 en paralelo; T020 tras T016–T018; T021 tras T019 y T020; T022
  y T023 tras T020 y T021; T024 y T025 en paralelo tras T023.
- Fuera de esta sub-feature: la 015 y la 027 tocan los mismos ficheros
  comunes (plan, «Dependencias»).

---

## Fase 3: Convergencia

Revisión independiente y converge (2026-11-15) sobre la punta `0faa885`.
Severidad entre corchetes. Cada hallazgo se verificó con un script fuera del
repositorio contra el Supervisor simulado y el código del Supervisor 2026.11.0.

- [x] T029 [CRÍTICO] `sv_set_addon_options`: la vista previa deja extraer el valor de una opción secreta (también la `auth_password` del propio Hermes) sin token. El validador del Supervisor (`vol.Schema(vol.All(dict, AppOptions))`, `apps/options.py`) lanza `vol.Invalid` en la RAÍZ, así que `humanize_error` responde «<error>. Got <repr() de TODAS las opciones>», cortado a 497 caracteres + `...`; `_sin_valores_secretos` (`tools/addons.py`) solo sustituye el valor COMPLETO y literal, de modo que (a) un cliente alarga una opción anterior al secreto e invalida otra para que el corte caiga dentro y recibe el secreto menos su último carácter en `invalid_options.message`, y (b) un secreto con `\`, salto de línea o las dos comillas sale escapado por `repr()` y tampoco se encuentra. Quitar del mensaje (y de `validation.reason`) todo lo que va desde «. Got » hasta el final de cada línea, conservando el texto del error del Supervisor, la sustitución literal y `redact_secrets`; tests con el corte dentro del secreto y con `\`/`\n`/comillas, con su control negativo, per FR-013, FR-018 y Constitución II (contradicts)
- [x] T030 [ALTO, código de la 1.1.2, fuera del diff de la 030: decide el supervisor del programa] `sv_set_addon_options` con token: si el guardado falla (`AppConfigurationInvalidError`, «App … has invalid options: <humanize_error>» y `validation_error` en el cuerpo), devuelve `{"error": str(exc)}` y lo guarda como `cached_error` en el fichero del token, con el `repr()` de todas las opciones EN CLARO. Tras la 030 solo pasa si la validación de la vista previa no se pudo hacer, pero el docstring nuevo se apoya en que «el guardado vuelve a validar». Pasar el error por la misma limpieza de T029, sin cambiar la forma `{"error": …}`, con test, per FR-013, FR-018 y Constitución II (partial)
- [x] T031 [MEDIO] `sv_update_addon`: la vista previa enseña `version_latest` y el principio del changelog de ESA versión, pero el token solo ata `slug`; si la tienda publica otra versión en los 60 s del token (recarga automática o `sv_reload_store`), la confirmación actualiza a una versión que nadie vio. Atar el token también a `version_latest` con `estado` (spec 018: `create_confirmation_token(..., estado={"version_latest": latest})` y, al confirmar, releer `/addons/{slug}/info` y `resolve_confirmation_token(..., estado=…)`, fail-closed si no se puede leer), sin cambiar argumentos ni la petición; lo mismo en `sv_install_addon` con la `version_latest` de la ficha. Ajustar `test_un_token_de_la_1_1_2_sigue_valiendo` y añadir el test de la carrera con su control negativo, per FR-009, FR-010 y principio V (partial)
- [x] T032 [BAJO] `sv_update_addon` de una app desligada de la tienda (`detached`: el Supervisor da `update_available: false`) responde `already_up_to_date` («already at the version the store offers»), que es falso; con `detached: true` responder `addon_not_in_store` sin token (el Supervisor rechazaría con `AppNotInStoreError`), con test, per FR-010 y principio V (contradicts)
- [x] T033 [BAJO] `hermes/DOCS.md`: la fila de `app_store` en la tabla de familias dice 5 tools y solo repositorios; son 9 (fichas, disponibilidad y reconstrucción), como ya dicen `README.md` y `README.es.md`, per FR-023 (partial)
- [x] T034 [BAJO] Formas raras de URL de repositorio: `https://u:p/ss@servidor/r` pasa la validación (`urlsplit` toma `u` como servidor y `p` como puerto), la vista previa enseña `host: "u"`, `credentials_hidden: false` y el usuario sin tapar; y en un texto con una URL desconocida, `https://u:p@ss@servidor/…` deja `ss@` sin tapar porque `_RE_USUARIO_EN_TEXTO` para en la primera `@`. Rechazar en `validar_url_repositorio` la URL cuyo `partes.port` lance `ValueError` y dejar que el patrón llegue hasta la última `@` antes de la `/` (`[^\s/'"<>]+@`), con tests, per FR-002 y FR-018 (partial)
- [x] T035 [BAJO] `sv_install_addon` con la tienda ilegible: el token sale con `store_check: {checked: false, reason}` (aceptable, como la 1.1.2 y `validation.checked: false`), pero la vista previa no dice que tampoco se sabe si la app es de un repositorio de terceros, y la descripción promete que «lo avisa». Añadir a `store_check` una nota de que no se comprobaron disponibilidad, instalación previa ni origen del repositorio, con test, per FR-009 y principio V (partial)

### Notas del converge (arreglos)

Decisiones del supervisor del programa, aplicadas tal cual. Tests en
`tests/test_tools_addons_convergencia_030.py` (nuevo), `tests/test_store_comun.py`
y `tests/test_tools_store_repositories.py`; controles negativos comprobados
(revertir un momento la parte del código, ver el rojo, restaurar):

- T029 y T030: `_sin_valores_secretos` (`tools/addons.py`) corta en «Got»,
  tapa los valores de TODAS las opciones (enteros, escapados por `repr()` y
  JSON, cortados al final) y, si queda un trozo de 6 caracteres de un
  secreto, devuelve un mensaje genérico con solo `data['clave']`. Se aplica
  al mensaje y a `validation.reason` de la validación, al error del guardado
  (respuesta y `cached_error` del fichero del token) y al error de leer las
  opciones. El error del guardado no se escribe en el log. Controles: la
  limpieza de antes → 50 rojos (con subtests: corte en cada punto del secreto
  y escapes); sin cortar en «Got» → 29; sin el genérico → 4; el error del
  guardado en claro → 1 (respuesta, log y disco).
- T031: el token de `sv_update_addon` y el de `sv_install_addon` atan
  `estado={"version_latest": …}` (spec 018); al confirmar se relee
  (`/addons/{slug}/info` o la ficha de la tienda; `None` si no se puede) y,
  si no casa, `preview_outdated: true` con la versión nueva, sin gastar el
  token ni enviar nada. Argumentos y petición, los de la 1.1.2; la
  confirmación hace ahora una lectura antes del POST. Un token sin versión
  atada ya no vale (`test_un_token_sin_version_ya_no_vale` sustituye a
  `test_un_token_de_la_1_1_2_sigue_valiendo`). Control: aceptar el estado
  cambiado → 4 rojos.
- T032: `already_up_to_date` solo con `detached: false`. Desligada: como la
  1.1.2, con token, pero la vista previa dice `in_store: false`,
  `update_status: "not_in_store"` y que el Supervisor no la actualizará; sin
  `detached`, `in_store: null`. Control → 2 rojos.
- T033: fila de `app_store` en `hermes/DOCS.md` con 9 tools (los README ya lo
  decían).
- T034: `validar_url_repositorio` rechaza un puerto no numérico
  (`https://u:p/ss@servidor/r`), y `_RE_USUARIO_EN_TEXTO` llega hasta la
  última `@` antes de la `/`. Controles → 1 y 2 rojos.
- T035: con la tienda ilegible, `store_check.note` dice que no se sabe si la
  app está disponible, instalada ni si es de terceros, y
  `third_party_repository: null`. Control → 1 rojo.
