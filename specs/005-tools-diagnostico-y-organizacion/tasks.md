---

description: "Tareas de Hermes 1.1.0 (spec 005), agrupadas en bloques paralelos"
---

# Tareas: Hermes 1.1.0 — tools de diagnóstico y organización

**Entrada**: `specs/005-tools-diagnostico-y-organizacion/` (spec.md, plan.md, research.md, data-model.md, contracts/tools.md, quickstart.md).

**Base**: 1.0.12 integrada (`HAConnectionError.code`, `ha_version.py`, safety backup corregido). Si falta, **parar** y avisar (spec S-01).

**Tests**: obligatorios. Cada tool nueva y la retención llevan tests escritos **antes** de su implementación y un **control negativo**: deshacer la guarda, ver caer el test, restaurar y dejar el recuento por escrito en el commit del bloque (principios VI y VII).

**Organización**: por **bloques** que pueden implementar agentes distintos, cada uno en su worktree, sin tocar los mismos ficheros. Las tareas llevan la historia de spec.md (US1…US9).

## Formato: `[ID] [P?] [Historia] Descripción`

- **[P]**: se puede hacer en paralelo con otras tareas del mismo bloque (ficheros distintos, sin dependencias pendientes). Las tareas que comparten fichero con otra anterior no llevan la marca: se hacen en orden.
- **[USn]**: historia de usuario de spec.md.
- Rutas relativas a la raíz del repositorio.

## Reparto de ficheros por bloque

Ningún fichero aparece en dos bloques. Si un bloque necesita cambiar un
fichero que no es suyo, **no lo toca**: lo anota en su informe para el bloque
de integración.

| Bloque | Ficheros que le pertenecen (código y tests) |
|---|---|
| **A — Plantas, etiquetas y categorías** | `hermes/src/hermes/tools/registry_floor.py` (nuevo), `hermes/src/hermes/tools/registry_label.py` (nuevo), `hermes/src/hermes/tools/registry_category.py` (nuevo), `tests/test_tools_registry_floor.py` (nuevo), `tests/test_tools_registry_label.py` (nuevo), `tests/test_tools_registry_category.py` (nuevo) |
| **B — Diagnóstico** | `hermes/src/hermes/tools/repairs.py` (nuevo), `hermes/src/hermes/tools/traces.py` (nuevo), `hermes/src/hermes/tools/search.py` (nuevo), `tests/test_tools_repairs.py` (nuevo), `tests/test_tools_traces.py` (nuevo), `tests/test_tools_search_related.py` (nuevo) |
| **C — Supervisor, backups de HA y retención** | `hermes/src/hermes/tools/resolution.py` (nuevo), `hermes/src/hermes/tools/ha_backups.py` (nuevo), `hermes/src/hermes/safety_retention.py` (nuevo), `hermes/src/hermes/fs_write.py` (solo `maybe_trigger_safety_backup`), `hermes/src/hermes/tools/filesystem_write.py` (solo `register_write` y las 5 llamadas a `maybe_trigger_safety_backup`), `hermes/src/hermes/tools/backups.py` (solo `sv_create_safety_backup`), `tests/test_tools_resolution.py` (nuevo), `tests/test_tools_ha_backups.py` (nuevo), `tests/test_safety_retention.py` (nuevo) |
| **Integración** (al final, tras fusionar A, B y C) | `hermes/src/hermes/tools/__init__.py`, `hermes/src/hermes/tools/_annotations.py`, `hermes/src/hermes/tools/guide.py`, `hermes/src/hermes/config.py`, `hermes/config.yaml`, `hermes/run.sh`, `hermes/CHANGELOG.md`, `hermes/DOCS.md`, `README.md`, `README.es.md`, `docs/HOJA-DE-RUTA.md`, `tests/test_tools_registration.py`, `tests/test_addon_manifest.py`, `tests/test_run_sh_options.py`, `tests/test_config_validation.py`, `tests/test_tools_guide.py` |

Notas de reparto:

- `hermes/src/hermes/ha_version.py`, `hermes/src/hermes/ha.py`, `hermes/src/hermes/security.py`, `tests/_ha_fixture.py`, `tests/test_fs_write_security.py` y `tests/test_tools_supervisor.py` **no los toca nadie** en esta spec. Los fakes de cada test construyen `HAConnectionError("…", code="…")` y parchean `ha_at_least` en el propio fichero de test.
- El bloque A llama a `search/related` por su cuenta (no importa `tools/search.py` del bloque B) (research R-A3).
- Dentro de los bloques A–C, las tools nuevas no están registradas: `tests/test_tools_registration.py` se excluye de su suite (`--ignore`) y vuelve en la integración (research R-0.3).
- `.github/`, `hermes/Dockerfile`, `hermes/build.yaml`, `hermes/src/hermes/__init__.py` y `version:` de `hermes/config.yaml` no se tocan (spec S-15).

---

## Fase 1: Preparación

**Objetivo**: entorno de pruebas y línea base sobre 1.0.12.

- [X] T001 Crear `.venv` con `hermes/requirements.txt` y `pytest pytest-asyncio aioresponses httpx` (quickstart.md); ejecutar `.venv/bin/pytest` y anotar los tests que pasan como línea base
- [X] T002 Comprobar que la base es 1.0.12: existen `HAConnectionError(..., code=...)` en `hermes/src/hermes/ha.py` y `ha_at_least` en `hermes/src/hermes/ha_version.py`, y `maybe_trigger_safety_backup` sondea `/jobs/{job_id}`; si no, parar (spec S-01). Cada bloque crea su worktree desde ese commit

**Punto de control**: se abren los bloques A, B y C en paralelo.

---

## Fase 2: Bloque A — Plantas, etiquetas y categorías (US1, US2)

**Objetivo**: CRUD de los tres registros con validación previa y borrados/ediciones en dos pasos con vistas previas veraces y fail-closed.

**Prueba independiente**: `.venv/bin/pytest tests/test_tools_registry_floor.py tests/test_tools_registry_label.py tests/test_tools_registry_category.py`.

### Plantas

- [X] T003 [P] [US1] Tests en `tests/test_tools_registry_floor.py` (estilo `tests/test_tools_registry_area.py`, `DummyMCP` y fake WS por `type`): `ha_list_floors` envía `config/floor_registry/list` y devuelve `count` y `floors`; `ha_create_floor(name="Planta baja", level=0, aliases=["pb", " "])` envía `config/floor_registry/create` con `aliases: ["pb"]`, sin token; un error de HA por nombre duplicado se devuelve como `{"error": …}` sin reintentar; `name` vacío, `level=True` o `level="1"` y `aliases="x"` → `invalid_argument` **sin ninguna llamada WS** (FR-001, FR-002, FR-009)
- [X] T004 [US1] Tests de `ha_update_floor` en el mismo fichero: sin token → preview con `current` y `proposed_changes` y token; `floor_id` inexistente → `not_found` sin token; lectura que lanza `HAConnectionError` → `preview_unavailable` sin token; clave desconocida en `updates` → `invalid_argument`; con token válido → `config/floor_registry/update` con solo los campos pedidos; token de otro `floor_id` → rechazado y sin envío (FR-003, FR-009)
- [X] T005 [US2] Tests de `ha_delete_floor` en el mismo fichero: con dos áreas de la planta, una de otra y `search/related` → `{"automation": ["automation.a"], "area": [...]}`, la preview trae `assignments_removed.areas` = las dos (ids y `count: 2`), `references_unresolved.automation` = `["automation.a"]`, `script`/`scene` a 0, y el `warning` con esos números; cada una de las tres lecturas fallando por separado (y una respuesta no lista) → `preview_unavailable` sin token; 60 áreas → 50 ids, `count: 60`, `truncated: true`; con token → `config/floor_registry/delete`; token emitido para otro `floor_id` o para `ha_update_floor` → rechazado sin envío; inexistente → `not_found` sin token (FR-004, FR-005, FR-008, FR-010)
- [X] T006 [US1] Crear `hermes/src/hermes/tools/registry_floor.py` con `register(mcp, ha_client)`, `_validate_floor_fields`, `ha_list_floors` y `ha_create_floor` según contracts/tools.md, con `@ready`, `-> object` y docstrings en el estilo de `registry_area.py` (FR-001, FR-002, FR-009)
- [X] T007 [US1] [US2] Añadir `ha_update_floor` y `ha_delete_floor` a `hermes/src/hermes/tools/registry_floor.py`: lectura de la entrada (fail-closed), `_impacto_planta()` (áreas + `search/related`), `_acotar(ids, 50)`, token atado a `floor_id` (+ `updates` normalizados), `complete_confirmation_token` en éxito y error; comentario del porqué de `preview_unavailable` (FR-003…FR-005, FR-008, FR-010)
- [X] T008 [US1] [US2] Control negativo de plantas, una guarda cada vez: (a) quitar la validación de `level` → cae T003; (b) emitir token aunque la entrada no exista → cae T004; (c) emitir token con `current: null` si la lectura falla → caen T004 y T005; (d) omitir `search/related` en el impacto → cae T005; (e) no acotar a 50 → cae T005. Restaurar y anotar «con la guarda quitada caen N tests» por guarda

### Etiquetas

- [X] T009 [P] [US1] Tests en `tests/test_tools_registry_label.py`: `ha_list_labels`; `ha_create_label` con `color="deep-orange"`, con `color="#1A2b3C"` y con `color="rojo"` / `"#12345"` (rechazados sin WS); `description` e `icon` opcionales llegan solo si se pasan (FR-001, FR-002, FR-009)
- [X] T010 [US1] Tests de `ha_update_label` en el mismo fichero: mismos casos que T004 con `label_id`, más color inválido en `updates` → `invalid_argument` sin WS (FR-003, FR-009)
- [X] T011 [US2] Tests de `ha_delete_label` en el mismo fichero: etiqueta en 1 área, 2 dispositivos y 3 entidades (y otras sin ella) + `search/related` con una automatización, un script y una escena → la preview enumera cada tipo con su recuento; cada una de las cinco lecturas fallando por separado → `preview_unavailable` sin token; etiqueta sin uso → recuentos a 0 y token emitido; con token → `config/label_registry/delete`; token de otro `label_id` → rechazado sin envío (FR-004, FR-006, FR-008)
- [X] T012 [US1] Crear `hermes/src/hermes/tools/registry_label.py` con `_THEME_COLORS`, `_validate_label_fields`, `ha_list_labels` y `ha_create_label` (FR-001, FR-002, FR-009)
- [X] T013 [US1] [US2] Añadir `ha_update_label` y `ha_delete_label` a `hermes/src/hermes/tools/registry_label.py` con `_impacto_etiqueta()` (área, dispositivo y entidad + `search/related`) (FR-003, FR-004, FR-006, FR-008, FR-010)
- [X] T014 [US1] [US2] Control negativo de etiquetas: (a) aceptar cualquier `color` → caen T009 y T010; (b) no contar dispositivos → cae T011; (c) emitir token si falla una lectura → cae T011; (d) emitir token sin entrada → cae T010. Restaurar y anotar

### Categorías

- [X] T015 [P] [US1] Tests en `tests/test_tools_registry_category.py`: `ha_list_categories(scope="automation")` envía `config/category_registry/list` con `scope`; `scope="dashboard"` → `invalid_argument` con los cuatro válidos y sin WS; `ha_create_category(scope="script", name="Riego")` (FR-001, FR-002, FR-009)
- [X] T016 [US1] Tests de `ha_update_category` en el mismo fichero: casos de T004 con `scope` + `category_id`; `updates` con `color` → `invalid_argument`; el token está atado también al `scope` (FR-003)
- [X] T017 [US2] Tests de `ha_delete_category` en el mismo fichero: cuatro entidades con `categories: {"automation": "<id>"}`, una con la misma id en `script` y otra sin categorías → la preview enumera solo las cuatro; lectura fallida → `preview_unavailable`; sin `references_unresolved`; con token → `config/category_registry/delete` con `scope`; token emitido para el mismo `category_id` en otro `scope` → rechazado sin envío (FR-004, FR-007, FR-008)
- [X] T018 [US1] Crear `hermes/src/hermes/tools/registry_category.py` con `_SCOPES`, validación, `ha_list_categories` y `ha_create_category` (FR-001, FR-002, FR-009)
- [X] T019 [US1] [US2] Añadir `ha_update_category` y `ha_delete_category` a `hermes/src/hermes/tools/registry_category.py` con `_impacto_categoria()` (FR-003, FR-004, FR-007, FR-008, FR-010)
- [X] T020 [US1] [US2] Control negativo de categorías: (a) quitar la validación de `scope` → cae T015; (b) contar la categoría sin mirar el `scope` → cae T017; (c) no atar el `scope` al token → cae T016. Restaurar y anotar

### Cierre del bloque A

- [X] T021 Ejecutar la prueba independiente del bloque y `.venv/bin/pytest --ignore=tests/test_tools_registration.py`; grep de privacidad del diff (quickstart.md); commit del bloque con los recuentos de control negativo en el mensaje

**Punto de control**: US1 y US2 completas a falta de registro.

---

## Fase 3: Bloque B — Diagnóstico (US3, US4, US5)

**Objetivo**: Repairs, trazas resumidas y redactadas con límite, y relaciones.

**Prueba independiente**: `.venv/bin/pytest tests/test_tools_repairs.py tests/test_tools_traces.py tests/test_tools_search_related.py`.

### Repairs (US3)

- [X] T022 [P] [US3] Tests en `tests/test_tools_repairs.py` para `ha_list_repairs`: tres issues (uno ignorado) → dos por defecto y tres con `include_ignored=true`; filtros `domain` y `severity`; `severity="info"` → `invalid_argument`; orden `critical`, `error`, `warning`; un `translation_placeholders` con `{"url": "https://user:SENTINEL-PASS@example.invalid", "token": "SENTINEL-TOKEN"}` sale sin `SENTINEL-` en ningún sitio; ningún campo fuera de los del contrato (FR-011, FR-012)
- [X] T023 [US3] Tests de `ha_ignore_repair` en el mismo fichero: issue no ignorado sin token → preview (`action: "ignore"`, gravedad, `breaks_in_ha_version`, «Reversible») y token, sin enviar `repairs/ignore_issue`; con token → envía `{domain, issue_id, ignore: true}`; ya ignorado con `ignore=true` → `unchanged` sin token ni envío; `ignore=false` sobre ignorado → preview `action: "unignore"`; inexistente → `not_found`; token emitido para otro `issue_id` → rechazado (FR-013)
- [X] T024 [US3] Crear `hermes/src/hermes/tools/repairs.py` con `register(mcp, ha_client)` y `ha_list_repairs` (`repairs/list_issues`, resumen por campos permitidos, `redact_structure` + `redact_secrets` en `translation_placeholders`) (FR-011, FR-012)
- [X] T025 [US3] Añadir `ha_ignore_repair` a `hermes/src/hermes/tools/repairs.py` (FR-013)
- [X] T026 [US3] Control negativo de Repairs: (a) devolver `translation_placeholders` sin redactar → cae T022; (b) emitir token aunque el estado ya sea el pedido → cae T023; (c) ejecutar sin token → cae T023. Restaurar y anotar

### Trazas (US4)

- [X] T027 [P] [US4] Tests en `tests/test_tools_traces.py` para `ha_list_traces`: cinco trazas desordenadas → las `limit` más recientes primero; `limit=0` y `limit=51` → `invalid_argument`; `domain="scene"` → `invalid_argument`; `entity_id="automation.x"` → `config/entity_registry/get` y `trace/list` con `item_id` = su `unique_id`; `entity_id` de otro dominio, o `item_id` y `entity_id` a la vez → `invalid_argument`; `entity_id` sin entrada (código `not_found`) → `not_found`; `error` de 2 000 caracteres → recortado a 300; `not_triggered` se conserva; sin `item_id` ni `entity_id` → `trace/list` solo con `domain` y el mismo `limit` (FR-014, FR-015)
- [X] T028 [US4] Tests de `ha_get_trace` en el mismo fichero: `summary` sin `config`, `blueprint_inputs`, `context` ni `changed_variables`, y con `steps` (`path`, `timestamp`, `result` ≤ 500, `error`, `child_id`); `full` con `changed_variables` que contienen `{"access_token": "SENTINEL-AT"}` y `entity_picture: "/api/camera_proxy/camera.x?token=SENTINEL-T"` → sin `SENTINEL-` en la respuesta; una traza sintética de más de 1 MB con `detail="full"` → JSON ≤ 65 536 bytes, `truncated: true` y `omitted` coherente; con `response_max_bytes=20000` → ≤ 20 000; `trace/get` con código `not_found` → `{"error": "not_found", "run_id": …}`; un paso con forma inesperada no rompe el resumen (FR-016…FR-019)
- [X] T029 [US4] Crear `hermes/src/hermes/tools/traces.py` con `register(mcp, ha_client, response_max_bytes=1_048_576)`, `_resolver_item_id` y `ha_list_traces` (FR-014, FR-015)
- [X] T030 [US4] Añadir `ha_get_trace` a `hermes/src/hermes/tools/traces.py` con `_resumen`, `_completo` (redacción), `_ajustar_a_limite` y `_TRACE_MAX_BYTES = 65536`; comentario del porqué del orden de recorte (FR-016…FR-019)
- [X] T031 [US4] Control negativo de trazas: (a) quitar la redacción de `full` → cae T028; (b) quitar `_ajustar_a_limite` → cae T028; (c) incluir `config` en `summary` → cae T028; (d) no traducir `entity_id` → cae T027; (e) no ordenar por inicio → cae T027. Restaurar y anotar

### Relaciones (US5)

- [X] T032 [P] [US5] Tests en `tests/test_tools_search_related.py`: envía `search/related` con `item_type`/`item_id` y **sin** `include_disabled_entities` cuando es `false`; agrupa y cuenta; `item_type="room"` → `invalid_argument` con los 14 tipos, sin WS; 250 ids de un tipo → 200, `counts` = 250, `truncated: true`; `include_disabled_entities=true` con `ha_at_least` parcheado: `False` → `ha_version_unsupported` (`required: "2026.10.0"`) sin WS; `True` → se envía; `None` → se envía y un `invalid_format` se traduce a `ha_version_unsupported` con `current: null` (FR-020, FR-021, FR-039)
- [X] T033 [US5] Crear `hermes/src/hermes/tools/search.py` con `register(mcp, ha_client)`, `_ITEM_TYPES` y `ha_search_related` (FR-020, FR-021)
- [X] T034 [US5] Control negativo de relaciones: (a) enviar siempre `include_disabled_entities` → cae T032; (b) quitar la comprobación de versión → cae T032; (c) quitar la validación de `item_type` → cae T032. Restaurar y anotar

### Cierre del bloque B

- [X] T035 Ejecutar la prueba independiente y `.venv/bin/pytest --ignore=tests/test_tools_registration.py`; grep de privacidad; commit del bloque con los recuentos

**Punto de control**: US3, US4 y US5 completas a falta de registro.

---

## Fase 4: Bloque C — Supervisor, backups de HA y retención (US6, US7, US8)

**Objetivo**: resolución del Supervisor sin aplicar nada; backups de HA sin secretos; retención inequívoca y fail-closed.

**Prueba independiente**: `.venv/bin/pytest tests/test_tools_resolution.py tests/test_tools_ha_backups.py tests/test_safety_retention.py tests/test_fs_write_security.py`.

### Resolución del Supervisor (US6)

- [X] T036 [P] [US6] Tests en `tests/test_tools_resolution.py` para `sv_get_resolution` con `GET /resolution/info` simulado: devuelve las cinco listas con los campos del contrato; un `reference` con `"password=SENTINEL"` en un campo sensible sale redactado; error del Supervisor → `{"error": …}` (FR-022)
- [X] T037 [US6] Tests de `sv_dismiss_resolution_issue` y `sv_dismiss_resolution_suggestion` en el mismo fichero: uuid inválido (`"../x"`) → `invalid_identifier` sin petición; uuid ausente de `/resolution/info` → `not_found` sin token; preview con tipo, contexto, referencia y, en la sugerencia, el texto de que **no** se aplica; con token → exactamente un `DELETE /resolution/issue/{uuid}` (o `/suggestion/{uuid}`) y ningún `POST`; si el `DELETE` responde 404 (desapareció tras la preview) → error del Supervisor y el token queda gastado (`complete_confirmation_token(success=False)`) (FR-023, FR-025)
- [X] T038 [US6] Test de guarda en el mismo fichero: recorre con `ast` `hermes/src/hermes/tools/*.py` y falla si alguna llamada a `sv_request` usa `"POST"` con una ruta que contenga `/resolution/suggestion/` (FR-024)
- [X] T039 [US6] Crear `hermes/src/hermes/tools/resolution.py` con `register(mcp, ha_client)` y `sv_get_resolution` (FR-022)
- [X] T040 [US6] Añadir `sv_dismiss_resolution_issue` y `sv_dismiss_resolution_suggestion` a `hermes/src/hermes/tools/resolution.py` (FR-023, FR-025)
- [X] T041 [US6] Control negativo de resolución: (a) quitar `validate_identifier` → cae T037; (b) emitir token sin buscar el uuid → cae T037; (c) añadir temporalmente un `sv_request("POST", f"/resolution/suggestion/{uuid}")` → cae T038; (d) quitar `redact_structure` → cae T036. Restaurar y anotar

### Backups de Home Assistant (US7)

- [X] T042 [P] [US7] Tests en `tests/test_tools_ha_backups.py` para `ha_list_backups` con `ha_at_least` parcheado: `False` → `ha_version_unsupported` (`feature: "backup"`, `required: "2025.1.0"`) y **ningún** envío WS; `None` + `HAConnectionError(code="unknown_command")` → `backup_integration_unavailable`; `True` → `backup/info`; respuesta con `extra_metadata.instance_id = "SENTINEL-INSTANCE"` y un campo desconocido `"secret_field": "SENTINEL-X"` → ninguno aparece; `agent_errors` con `"smb://user:SENTINEL-P@192.0.2.10/backups"` → sin la contraseña ni la IP; orden más reciente primero; `limit` 1–100 (FR-026, FR-027, FR-029, FR-030, FR-039)
- [X] T043 [US7] Tests de `ha_get_backup` en el mismo fichero: `backup/details {backup_id}`; `backup: null` → `not_found`; `backup_id` inválido → `invalid_identifier` sin WS; misma lista blanca que T042; versión antigua → error sin WS (FR-026, FR-027, FR-029)
- [X] T044 [US7] Tests de `ha_get_backup_config` en el mismo fichero: `create_backup.password = "SENTINEL-PASSWORD"` → `password_set: true` y la cadena `SENTINEL-PASSWORD` no aparece en el JSON serializado; `password: null` y `""` → `password_set: false`; un campo nuevo `create_backup.encryption_key = "SENTINEL-K"` no aparece; versión antigua → error sin WS (FR-026…FR-028)
- [X] T045 [US7] Crear `hermes/src/hermes/tools/ha_backups.py` con `register(mcp, ha_client)`, `_comprobar_version`, `_backup_permitido`, `_mascara_red`, `_errores_agentes` y `ha_list_backups`; comentario del porqué de la lista blanca (FR-026, FR-027, FR-029, FR-030)
- [X] T046 [US7] Añadir `ha_get_backup`, `_config_permitida` y `ha_get_backup_config` a `hermes/src/hermes/tools/ha_backups.py` (FR-026…FR-028)
- [X] T047 [US7] Control negativo de backups de HA: (a) devolver `config` con `redact_structure` en vez de lista blanca → cae T044 (`encryption_key` u otro campo nuevo); (b) copiar `password` → cae T044; (c) quitar la comprobación de versión → caen T042–T044; (d) devolver `extra_metadata` → cae T042; (e) quitar `_mascara_red` → cae T042. Restaurar y anotar

### Retención de los safety backups (US8)

- [X] T048 [P] [US8] Tests de la anotación en `tests/test_safety_retention.py` (con `LEDGER_PATH` en `tmp_path`): `record_launch` añade la entrada con `slug: null`; con `slug` síncrono queda confirmada (`sync_response`); `confirm_from_job` confirma solo con `done is True`, `errors` vacío y `reference` texto, y elimina la entrada si hay errores; fichero corrupto → se lee como vacío y **no** se sobrescribe al leer; más de 100 entradas → se descartan primero las no confirmadas más antiguas; escritura atómica (FR-032)
- [X] T049 [US8] Tests de `apply_retention` en el mismo fichero, con `GET /backups` y `GET /jobs/{id}` simulados y registro de cada `DELETE`: (a) `keep=3` y cinco confirmados → borra los dos más antiguos, del más antiguo al más reciente; (b) un backup del usuario llamado `hermes-safety-20261101T000000Z` sin anotar → ni se borra ni cuenta; (c) `hermes-safety-manual` → nunca; (d) anotado con slug cuyo backup tiene otro nombre → excluido y motivo registrado; (e) `protected: true` → excluido; (f) `locations` con dos elementos → excluido; (g) `type: "partial"` → excluido; (h) `date` ilegible → excluido; (i) `GET /backups` falla o devuelve algo que no es lista → 0 `DELETE`; (j) primer `DELETE` falla → no hay segundo; (k) doce sobrantes → 5 `DELETE`; (l) `keep=0` → 0 peticiones; (m) confirmación por nombre único y fecha a menos de 10 min; dos backups con ese nombre, o fecha a más de 10 min → sin confirmar y sin borrar; (n) no confirmada de más de 7 días → sale de la anotación sin borrarse; (o) `apply_retention` nunca lanza excepción; (p) el evento de log `safety_backup_retention_done` trae borrados, conservados y exclusiones (FR-033…FR-037)
- [X] T050 [US8] Tests de los enganches en el mismo fichero: (a) `maybe_trigger_safety_backup(..., keep=1)` con un job que termina bien anota la entrada `origin: "auto"`, la confirma por `reference` y llama a `apply_retention` una vez; (b) con el job terminado con errores no llama a la retención y la escritura se rechaza como en 1.0.12; (c) si `apply_retention` falla, `maybe_trigger_safety_backup` sigue devolviendo `None` (la escritura continúa); (d) pendiente de 1.0.12 resuelto como correcto en la llamada siguiente → también aplica la retención; (e) `sv_create_safety_backup` anota `origin: "tool"` y **no** hace ningún `DELETE`; su descripción menciona `safety_backup_keep`; (f) `register_write(..., safety_backup_keep=2)` pasa `keep=2` a `maybe_trigger_safety_backup` desde `fs_write_file` (FR-031, FR-032, FR-034, FR-035, FR-038)
- [X] T051 [US8] Crear `hermes/src/hermes/safety_retention.py` con `LEDGER_PATH`, `_lock`, `_cargar`/`_guardar` atómicos, `record_launch` y `confirm_from_job`; comentarios del porqué (anotación propia = identificación inequívoca) (FR-032)
- [X] T052 [US8] Añadir `apply_retention(ha_client, keep)` a `hermes/src/hermes/safety_retention.py` con `_NOMBRE_RE`, `_es_candidato`, confirmación por nombre único y fecha, orden, `_MAX_BORRADOS = 5`, limpieza de la anotación y evento de log; captura total de excepciones (FR-033…FR-037)
- [X] T053 [US8] Enganchar en `maybe_trigger_safety_backup` de `hermes/src/hermes/fs_write.py`: parámetro `keep: int = 0`, `record_launch(origin="auto")` al recibir `job_id` o `slug`, `confirm_from_job` + `apply_retention(ha_client, keep)` en cada camino de éxito confirmado de 1.0.12, eliminar la entrada si el job falla; sin cambiar los retornos (FR-032, FR-034, FR-035)
- [X] T054 [US8] En `hermes/src/hermes/tools/filesystem_write.py`, parámetro `safety_backup_keep: int = 3` en `register_write` y `keep=safety_backup_keep` en las 5 llamadas a `maybe_trigger_safety_backup` (FR-031, FR-034)
- [X] T055 [US8] En `sv_create_safety_backup` de `hermes/src/hermes/tools/backups.py`, `record_launch(name, job_id, origin="tool", slug=slug)` tras el `POST` y docstring con la retención (FR-032, FR-038)
- [X] T056 [US8] Control negativo de la retención, una guarda cada vez: (a) identificar solo por prefijo de nombre → caen T049 (b, c); (b) quitar la comprobación de la anotación → cae T049 (b); (c) quitar `protected`, `locations` y `type` → caen T049 (e, f, g); (d) borrar aunque `GET /backups` falle (lista vacía como «nada que conservar») → cae T049 (i); (e) no parar en el primer fallo → cae T049 (j); (f) quitar `_MAX_BORRADOS` → cae T049 (k); (g) dejar que la excepción de la retención se propague → cae T050 (c); (h) podar en `sv_create_safety_backup` → cae T050 (e); (i) aceptar dos candidatos por nombre → cae T049 (m). Restaurar y anotar el recuento de cada una

### Cierre del bloque C

- [X] T057 Ejecutar la prueba independiente y `.venv/bin/pytest --ignore=tests/test_tools_registration.py`; comprobar que `tests/test_fs_write_security.py` sigue pasando sin editarlo; grep de privacidad; commit del bloque con los recuentos

**Punto de control**: US6, US7 y US8 completas a falta de registro y de la opción.

---

## Fase 5: Bloque de integración (US9, tras fusionar A, B y C)

**Objetivo**: registrar y anotar las 23 tools, añadir la opción, la guía y la documentación, y dejar la suite completa en verde.

**Prueba independiente**: `.venv/bin/pytest tests/test_tools_registration.py tests/test_addon_manifest.py tests/test_run_sh_options.py tests/test_config_validation.py tests/test_tools_guide.py` y después `.venv/bin/pytest`.

- [X] T058 [P] [US9] Tests en `tests/test_tools_registration.py`: las 23 tools de contracts/tools.md están registradas; `ha_search_related`, `ha_list_*`, `ha_get_*` y `sv_get_resolution` nuevas son de solo lectura; las nueve con token son destructivas; `ha_create_floor`, `ha_create_label` y `ha_create_category` no son destructivas ni idempotentes; ninguna es `open_world`; los invariantes existentes (toda tool registrada, token ⇒ destructiva, destructiva ⇒ token, excepción única) siguen pasando (FR-040)
- [X] T059 [P] [US9] Tests de la opción: en `tests/test_addon_manifest.py`, `safety_backup_keep` está en `schema` como `int(0,50)?` y en `options` con 3; en `tests/test_run_sh_options.py`, `run.sh` exporta `HERMES_SAFETY_BACKUP_KEEP` y `0` no cae al default; en `tests/test_config_validation.py`, `load_config` lee la variable (3 por defecto) y `validate()` rechaza -1 y 51 (FR-031)
- [X] T060 [P] [US9] Tests en `tests/test_tools_guide.py`: el tema `diagnostics` existe, tiene alias (`repairs`, `traces`, `resolution`) y nombra `ha_list_repairs`, `ha_get_trace`, `ha_search_related` y `sv_get_resolution`; `registries` nombra `ha_delete_label`; `backups` nombra `ha_get_backup_config` y `safety_backup_keep` (FR-041)
- [X] T061 [US9] En `hermes/src/hermes/tools/__init__.py`, registrar los ocho módulos nuevos (`traces` con `response_max_bytes`) y añadir `safety_backup_keep` a `register_all_tools` (leído de `cfg.safety_backup_keep` si es `None`) y a `register_write` (FR-031, FR-040)
- [X] T062 [US9] En `hermes/src/hermes/tools/_annotations.py`, añadir a `_DESTRUCTIVE_EXACT` las seis tools con token que no tienen prefijo destructivo y a `_READ_ONLY_EXACT` `ha_search_related`, con el porqué de cada una (research R-I1) (FR-040)
- [X] T063 [US9] Opción `safety_backup_keep`: campo y `validate()` en `hermes/src/hermes/config.py`, `schema` y `options` en `hermes/config.yaml`, `export` en `hermes/run.sh` (FR-031)
- [X] T064 [US9] En `hermes/src/hermes/tools/guide.py`, tema `diagnostics` con alias, ampliar `registries` y `backups`, y actualizar el recuento de tools del índice al del registro real (FR-041)
- [X] T065 [US9] (Hecho: (a)–(e) caen como se espera; además, quitar el cableado de `safety_backup_keep` → caen los 2 tests de cableado, quitar su comprobación en `validate()` → caen 2, poner un recuento de tools desfasado en un README → cae el test del recuento, y quitar `sv_dismiss_resolution_issue` de `_DESTRUCTIVE_EXACT` → caen 3) Control negativo de la integración: (a) quitar el registro de un módulo nuevo → cae T058; (b) quitar `ha_ignore_repair` de `_DESTRUCTIVE_EXACT` → caen T058 y el invariante token ⇒ destructiva; (c) quitar `ha_search_related` de `_READ_ONLY_EXACT` → cae T058; (d) quitar la opción del `schema` → cae T059; (e) quitar el tema `diagnostics` → cae T060. Restaurar y anotar
- [X] T066 [P] [US9] `README.md` y `README.es.md` sincronizados: tabla de capacidades con las familias nuevas o ampliadas (registros con plantas, etiquetas y categorías; diagnóstico; backups de HA) y el número real de tools; fila de `safety_backup_keep` en la tabla de opciones (qué borra, qué nunca borra, 0 = desactivado, solo con `safety_backup_enabled`); limitaciones conocidas: no se aplican sugerencias del Supervisor, safety backups sin cifrar, los anteriores a 1.1.0 no se podan (cómo borrarlos con `sv_delete_backup`) (FR-042)
- [X] T067 [P] [US9] `hermes/DOCS.md`: número de tools y una línea sobre `safety_backup_keep` remitiendo al README (FR-042)
- [X] T068 [P] [US9] `docs/HOJA-DE-RUTA.md`: en 1.1.0, marcar como hecho Repairs, resolución, trazas, `search/related`, backups de HA, retención y plantas/etiquetas/categorías; añadir como pendientes el cifrado de safety backups, aplicar sugerencias del Supervisor (con confirmación), flujos de reparación y traducciones de issues (FR-042)
- [X] T069 [P] [US9] `hermes/CHANGELOG.md`: entradas `### Added` bajo `## [1.1.0]` (crear el encabezado si no existe, sin subir `version`) con cada familia de tools, la opción y el porqué (FR-042, spec S-15) — Hecho en la integración final de 1.1.0, que fundió las notas de los tres bloques en el CHANGELOG y las borró
- [X] T070 Ejecutar `.venv/bin/pytest` completo (debe pasar entero); grep de privacidad e identificadores de modelos sobre el diff completo de la spec; revisar que ningún ejemplo de la documentación use datos reales (FR-044, SC-009)
- [X] T071 (Hecho en el commit de la 1.1.0) Commit de integración con el resumen de los recuentos de control negativo de todos los bloques; informe al mantenedor con lo pendiente de verificar de research.md

**Punto de control**: suite completa en verde; spec lista para publicar con el resto de 1.1.0.

---

## Dependencias y orden de ejecución

### Entre fases

- **Fase 1** (T001–T002): sin dependencias; bloquea a todos.
- **Bloques A, B y C** (fases 2, 3 y 4): dependen solo de la fase 1; **en paralelo** entre sí.
- **Integración** (fase 5): depende de que A, B y C estén fusionados.

### Dentro de cada bloque

1. Tests (fallan porque la tool no existe).
2. Implementación (los tests pasan).
3. Control negativo (deshacer la guarda, ver caer el test, restaurar, anotar).

Las tareas de test de un mismo fichero van en orden (T003→T004→T005); las de
ficheros distintos de un mismo bloque pueden ir a la vez (T003, T009, T015).

### Paralelismo

```bash
# Tras la fase 1, abrir tres worktrees y lanzar un agente por bloque:
Agente A: T003–T021 (ficheros del bloque A)
Agente B: T022–T035 (ficheros del bloque B)
Agente C: T036–T057 (ficheros del bloque C)
# Después, un agente de integración: T058–T071
```

---

## Estrategia de implementación

1. Fase 1.
2. Bloques A (P1: organización y borrados veraces) y C (P1: backups de HA sin secretos) primero si no hay tres agentes; B después.
3. Cada bloque se fusiona en cuanto pasa su prueba independiente y la suite sin `tests/test_tools_registration.py`.
4. Integración y suite completa. La versión la sube el mantenedor al publicar 1.1.0.

---

## Tools nuevas: test previo, implementación y control negativo

| Tool | Bloque | Test previo | Implementación | Control negativo (guarda que se deshace) |
|---|---|---|---|---|
| `ha_list_floors` | A | T003 | T006 | T008 (stub que devuelve lista vacía: cae T003) |
| `ha_create_floor` | A | T003 | T006 | T008 (a) validación de `level` |
| `ha_update_floor` | A | T004 | T007 | T008 (b) `not_found`, (c) fail-closed |
| `ha_delete_floor` | A | T005 | T007 | T008 (c) fail-closed, (d) referencias, (e) acotado |
| `ha_list_labels` | A | T009 | T012 | T014 (stub vacío: cae T009) |
| `ha_create_label` | A | T009 | T012 | T014 (a) color |
| `ha_update_label` | A | T010 | T013 | T014 (a) color, (d) `not_found` |
| `ha_delete_label` | A | T011 | T013 | T014 (b) dispositivos, (c) fail-closed |
| `ha_list_categories` | A | T015 | T018 | T020 (a) `scope` |
| `ha_create_category` | A | T015 | T018 | T020 (a) `scope` |
| `ha_update_category` | A | T016 | T019 | T020 (c) `scope` en el token |
| `ha_delete_category` | A | T017 | T019 | T020 (b) `scope` en el impacto |
| `ha_list_repairs` | B | T022 | T024 | T026 (a) redacción |
| `ha_ignore_repair` | B | T023 | T025 | T026 (b) `unchanged`, (c) token |
| `ha_list_traces` | B | T027 | T029 | T031 (d) `entity_id`, (e) orden |
| `ha_get_trace` | B | T028 | T030 | T031 (a) redacción, (b) límite, (c) resumen |
| `ha_search_related` | B | T032 | T033 | T034 (a) parámetro, (b) versión, (c) tipos |
| `sv_get_resolution` | C | T036 | T039 | T041 (d) redacción |
| `sv_dismiss_resolution_issue` | C | T037 | T040 | T041 (a) uuid, (b) `not_found` |
| `sv_dismiss_resolution_suggestion` | C | T037, T038 | T040 | T041 (a), (b), (c) `POST` prohibido |
| `ha_list_backups` | C | T042 | T045 | T047 (c) versión, (d) `extra_metadata`, (e) máscara de red |
| `ha_get_backup` | C | T043 | T046 | T047 (c) versión |
| `ha_get_backup_config` | C | T044 | T046 | T047 (a) lista blanca, (b) contraseña |
| Retención (`safety_backup_keep`) | C + integración | T048–T050, T059 | T051–T055, T063 | T056 (a)–(i), T065 (d) |

---

## Trazabilidad FR → tareas

| FR | Bloque | Test | Implementación | Control negativo |
|---|---|---|---|---|
| FR-001, FR-002 | A | T003, T009, T015 | T006, T012, T018 | T008, T014, T020 |
| FR-003 | A | T004, T010, T016 | T007, T013, T019 | T008, T014, T020 |
| FR-004 | A | T005, T011, T017 | T007, T013, T019 | T008, T014, T020 |
| FR-005 | A | T005 | T007 | T008 |
| FR-006 | A | T011 | T013 | T014 |
| FR-007 | A | T017 | T019 | T020 |
| FR-008 | A | T005, T011, T017 | T007, T013, T019 | T008, T014 |
| FR-009 | A | T003, T009, T010, T015, T016 | T006, T012, T018 | T008, T014, T020 |
| FR-010 | A | T005 | T007, T013, T019 | T008 |
| FR-011, FR-012 | B | T022 | T024 | T026 |
| FR-013 | B | T023 | T025 | T026 |
| FR-014, FR-015 | B | T027 | T029 | T031 |
| FR-016…FR-019 | B | T028 | T030 | T031 |
| FR-020, FR-021 | B | T032 | T033 | T034 |
| FR-022 | C | T036 | T039 | T041 |
| FR-023, FR-025 | C | T037 | T040 | T041 |
| FR-024 | C | T038 | T040 | T041 |
| FR-026, FR-027 | C | T042, T043, T044 | T045, T046 | T047 |
| FR-028 | C | T044 | T046 | T047 |
| FR-029, FR-030 | C | T042, T043 | T045, T046 | T047 |
| FR-031 | C + integración | T050, T059 | T054, T061, T063 | T065 |
| FR-032 | C | T048, T050 | T051, T053, T055 | T056 |
| FR-033…FR-037 | C | T049 | T052 | T056 |
| FR-034, FR-035 (enganche) | C | T050 | T053, T054 | T056 |
| FR-038 | C | T050 | T055 | T056 |
| FR-039 | B, C | T032, T042–T044 | T033, T045, T046 | T034, T047 |
| FR-040 | Integración | T058 | T061, T062 | T065 |
| FR-041 | Integración | T060 | T064 | T065 |
| FR-042 | Integración | — (documentación) | T066–T069 | — |
| FR-043 | Todos | — | todas las tareas de control negativo | T008, T014, T020, T026, T031, T034, T041, T047, T056, T065 |
| FR-044 | Todos | — | T021, T035, T057, T070 | — |

## Notas

- [P] = ficheros distintos y sin dependencias pendientes.
- Cada bloque deja en su commit «con la guarda quitada caen N tests» por guarda.
- Ningún bloque empuja ni fusiona a `main`; eso lo decide el mantenedor.
- Los centinelas de los tests empiezan por `SENTINEL-` y las IPs de ejemplo son de `192.0.2.0/24`.
