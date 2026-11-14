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

- [ ] T015 Línea base del tramo 2 con el tramo 1 integrado; `grep -c "spec 030"` da 8; si la 027 está integrada, anotar que las descripciones de `tools/addons.py` ya dicen «app (add-on)» y partir de ellas

### Tests (escritos antes, en rojo)

- [ ] T016 [P] [US2] Fixture (ampliar `tests/fixtures/supervisor_tienda.py`: ficha `GET /store/addons/{slug}` con y sin `documentation`, changelog y documentación de 50 000 caracteres con un centinela `password: centinela-clave-2` cerca del corte de 20 000, los textos exactos «No changelog found for app {slug}!» y «No documentation found for app {slug}!» con 200, y el mensaje de app inexistente con 200) y tests en `tests/test_tools_store_apps.py` (`TestChangelog`, `TestDocumentacion`): dos llamadas (ficha y texto) con `sv_request_text`; ficha 404/400 → `addon_not_found` sin pedir el texto; «No changelog found…» → `changelog_not_found`; `documentation: false` → `documentation_not_found` sin pedir el texto; trozos: `offset` 0, 20000 y 49990, `next_offset`, `truncated`, `total_chars`; `offset` fuera → `text: ""` y `truncated: false`; `offset=-1`, `max_chars=0` y `100001` → `invalid_argument` sin llamada; con `response_max_bytes` pequeño, la respuesta cabe; el centinela no sale en ningún trozo y `secrets_redacted: true`; `_third_party_text` con `name` y `text`; `version_latest` en la respuesta (FR-006, FR-007, FR-017…FR-019)
- [ ] T017 [P] [US2] Tests en `tests/test_tools_store_apps.py` (`TestDisponibilidad`): disponible → `available: true`, `reason: null` y los campos de la ficha; 400 con «not supported on this platform…» → `available: false` y `reason` redactado; app inexistente → `addon_not_found`; nunca un `POST` (FR-008)
- [ ] T018 [P] [US3] Tests en `tests/test_tools_store_apps.py` (`TestReconstruir`): con `GET /addons/{slug}/info` simulado, sin token y sin `POST`: inexistente (404) → `addon_not_found`; no instalada (el Supervisor devuelve la ficha de la tienda con `installed: false` y `state: "unknown"`) → `addon_not_installed`; `detached: true` → `addon_not_in_store`; `version` ≠ `version_latest` → `rebuild_version_changed` con las dos versiones; `build: false` sin `force` → `rebuild_not_supported` con la pista; vista previa con los campos de data-model y `effect` distinto para construir y para `force` sobre imagen; Hermes (`_es_hermes`) → `critical_warning`; confirmación → `POST /addons/{slug}/rebuild` con `{"force": false|true}` y la espera larga; `force` distinto al confirmar → token rechazado; error del Supervisor → `error` redactado y token fallido; evento `app_store_action` sin opciones ni textos (FR-012, FR-018)
- [ ] T019 [P] [US2] [US3] [US4] Tests en `tests/test_tools_addons_tienda.py` (`TestInstalar`, `TestActualizar`, `TestSinVersion`, `TestValidarOpciones`, `TestDescripciones`): `sv_install_addon` → `addon_not_found`, `already_installed` y `addon_not_available` (con `reason`) sin token; vista previa con `name`, `version_latest`, `repository`, `build`, y `third_party_repository`/`warning` solo si el repositorio no es integrado; confirmación idéntica a la 1.1.2 (ruta, `json_body`, `timeout_seconds`); `sv_update_addon` → vista previa con `available` y `changelog_excerpt` (≤ 4000, redactado, `_third_party_text`); changelog que falla → `changelog_excerpt: null` y token; Hermes sigue con `self_update_not_supported` sin ninguna llamada; confirmación idéntica a la 1.1.2; `sv_set_addon_options` → `POST /addons/{slug}/options/validate` con las opciones finales sin envolver antes del token; `valid: false` con un mensaje que repite un secreto de las opciones (`Got 'centinela-clave-3'`) → `invalid_options` sin token, sin el centinela; `pwned: true` → `warning_pwned`; `pwned: null` → `pwned_check: "failed"`; error al validar → `validation.checked: false` y token; opciones finales `{}` → sin llamada a validar y `reason: "empty_options"`; confirmación idéntica a la 1.1.2 (no vuelve a validar); los esquemas de entrada de las tres coinciden con `tests/fixtures/esquemas_1_1_2.json`; las descripciones de instalar y actualizar dicen que es la versión de la tienda y no aceptan versión (FR-009…FR-011, FR-013, FR-021; SC-005)

### Implementación

- [ ] T020 [US2] [US3] `hermes/src/hermes/tools/_store.py` (lecturas: `ficha_de_tienda`, `disponibilidad`, `texto_de_la_app`) y `hermes/src/hermes/tools/store_apps.py` (cuatro tools según contracts/tools.md); `store_apps` en la familia `app_store` y su descripción completa (`tool_families.py` y su test de T002); registro en `tools/__init__.py`; `sv_rebuild_addon` en `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD`. T016–T018 en verde (FR-006…FR-008, FR-012, FR-015…FR-019)
- [ ] T021 [US2] [US3] [US4] `hermes/src/hermes/tools/addons.py`: vistas previas de `sv_install_addon`, `sv_update_addon` y `sv_set_addon_options` según data-model, con las lecturas de `tools/_store.py`; descripciones («a la versión de la tienda», validación en la vista previa, «app (add-on)» si la 027 no lo ha hecho); nada cambia con token. T019 en verde (FR-009…FR-011, FR-013, FR-021)
- [ ] T022 [US2] [US3] Tests en `tests/test_command_table.py` y después `hermes/src/hermes/command_table.py`: las ocho entradas del tramo 2 de data-model a `dedicated` (tres con «el Supervisor 2026.11.0 ignora `{version}`» y la tool de la 1.1.2, familia `supervisor`); `sv_call_api("POST", "/store/addons/<slug>/install/1.0.0")` → `use_dedicated_tool` con `sv_install_addon`; ninguna entrada con «spec 030»; regenerar la tabla sin cambios (FR-011, FR-014)
- [ ] T023 [US4] Tests en `tests/test_tools_registration.py` para las cuatro: registradas por defecto con las anotaciones de contracts/tools.md, `sv_rebuild_addon` con `confirmation_token` y `force`; ninguna con `app_store` desactivada; las tres de la 1.1.2 con las mismas anotaciones y esquemas; SC-005 de la 011 en verde; `TestDedicadas` en verde con todas las familias activas (FR-015, FR-016)
- [ ] T024 [US2] [US3] Guía: tests en `tests/test_tools_guide.py` (el tema `app_store` nombra las nueve tools, que el changelog y la documentación son de la versión de la tienda y por trozos, la disponibilidad, reconstruir —local frente a `force` y qué pasa si falla— y que no se puede elegir versión, con la vuelta atrás por backup parcial; alias `changelog`, `documentation`, `rebuild`, `availability`; el tema `supervisor` remite a `app_store` y nombra la validación de opciones y las vistas previas de instalar y actualizar; `hermes_guide(topic="generic_commands", search="store")` lista las entradas `dedicated`); después, `hermes/src/hermes/tools/guide.py` (FR-011, FR-020)
- [ ] T025 [US3] Banco y matriz de `sv_rebuild_addon`: `FUERA_DEL_BANCO` (motivo de apps), fila `VM` / `pendiente` y línea en la tanda 2 de `docs/BANCO-SUPERVISOR.md` (app local de prueba; con `force` sobre una de imagen); los tests de la matriz y del rol en verde (FR-022)
- [ ] T026 Control negativo del tramo 2, anotando recuentos: (a) no reconocer «No changelog found…» → cae `changelog_not_found`; (b) redactar por trozos en vez de sobre el texto entero → cae el del centinela en el corte; (c) emitir token en `rebuild_version_changed` o sin `force` en una app de imagen → caen; (d) no validar opciones en la vista previa → caen los de `invalid_options`; (e) no quitar el secreto literal del mensaje de validación → cae el del centinela; (f) cambiar la petición de `sv_install_addon` con token (p. ej. sin `background`) → cae el de identidad con la 1.1.2; (g) dejar `POST /addons/{app}/rebuild` como `deny` → cae el de la tabla. Restaurar y comprobar verde
- [ ] T027 Documentación final: completar la sección de la 030 en el CHANGELOG (cuatro tools, vistas previas de las tres de la 1.1.2, validación de opciones, la desviación de la versión concreta y que la prueba en vivo queda pendiente); `docs/HOJA-DE-RUTA.md`: estado «hecha» de la 030 con un resumen como el de la 013; `README.md` y `README.es.md` sincronizados (recuento y fila de apps); filas CAP-082 y CAP-093 de la matriz de `specs/008-cobertura-total/plan.md` con las tools y los ficheros de test, sin cambiar sus columnas de sub-feature ni de vía (las lee `_matriz_008`), y la desviación de FR-051 anotada en la fila de CAP-082 (FR-023)
- [ ] T028 Cierre del tramo 2: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII), commit con los recuentos de T026 y el resultado de la regeneración de T022

---

## Dependencias y paralelismo

- T002–T006 en paralelo (ficheros distintos); T007 tras T003–T006; T008 y
  T009 tras T007; T010 y T011 en paralelo tras T008.
- T016–T019 en paralelo; T020 tras T016–T018; T021 tras T019 y T020; T022
  y T023 tras T020 y T021; T024 y T025 en paralelo tras T023.
- Fuera de esta sub-feature: la 015 y la 027 tocan los mismos ficheros
  comunes (plan, «Dependencias»).
