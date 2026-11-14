---
description: "Tareas de la sub-feature 031 — backups de la integración backup y safety backups cifrados (Hermes 1.2.0)"
---

# Tareas: backups de la integración `backup` y safety backups cifrados (031)

**Entrada**: `specs/031-backups-integracion-y-cifrado/` (spec.md, plan.md,
research.md, data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `DummyMCP` o
`_RecordingMCP`, `AsyncMock` de `ws_send` y `sv_request`,
`structlog.testing.capture_logs`. Datos ficticios (`hassio.local`,
`hassio.nas_backups`, `cloud.cloud`, `core_mosquitto`, `192.0.2.10`,
`homeassistant.tailXXXX.ts.net`, `centinela-031`). Nada de la instalación real
ni de las tools MCP de Hermes.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" python -m pytest -q -p no:cacheprovider`.
Línea base en Windows al especificar (2026-11-15, punta `8a101b7`): 2642
passed, 78 skipped, 6 failed (los 6 conocidos). Cada tramo termina con
exactamente esos 6 fallos en local; la referencia es el CI de Linux.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 configurar los backups automáticos, US2 crear, US3
restaurar, US4 borrar, US5 safety backups cifrados, US6 nada se rompe.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado (uno o varios commits; el tramo no se cierra con la suite en rojo).
La 008 preveía dos tramos; son cuatro (research R-15, duda D-031-2).

| Tramo | Tareas | Cubre |
|---|---|---|
| **1** — Agentes y ajustes | **T001–T016** | Familia `backup_integration` (módulo `ha_backup_settings`); `ha_list_backup_agents`, `ha_update_backup_config`, `ha_get_update_backup_settings`, `ha_set_update_backup_settings`; estimación de retención; 4 entradas a `dedicated`; tema de la guía; `backup:` en el banco e inventario `cobertura_031.py`; documentación parcial |
| **2** — Crear y borrar | **T017–T031** | `backup_key.py`; `ha_create_backup`, `ha_create_automatic_backup`, `ha_delete_backup` (módulo `ha_backup_actions`); `last_action_event` en `ha_list_backups`; 3 entradas a `dedicated` y sus filas del inventario; banco con la retención real |
| **3** — Restaurar | **T032–T046** | `HAConnectionError.sent`; `ha_restore_backup` (módulo `ha_backup_restore`); `sv_restore_backup_*` con la clave de HA; `backup/restore` a `dedicated`; banco de la vista previa y la contraseña incorrecta. Necesita la 019 (HMAC) |
| **4** — Safety backups cifrados y cierre | **T047–T060** | Opción `safety_backup_encryption`; safety backups (tool y automático) cifrados; retención de los cifrados; tema `backups`; documentación final y matriz de la 008 |

Cada tramo necesita el anterior integrado.

---

## Tramo 1 — Agentes y ajustes (US1, US6)

### Preparación

- [ ] T001 Comprobar la base: la rama contiene la 018 (`estado=` en `create_confirmation_token`/`resolve_confirmation_token` de `hermes/src/hermes/security.py`) y el mecanismo de la clase A de la 029 en `scripts/inventario/generar_tabla.py` (`_clasificar` consulta `_DEDICADAS_INICIALES` antes de la regla «pendiente»); si falta algo, parar y avisar. Anotar si la 019 y la 027 están integradas (deciden T032 y T050). Línea base de la suite, anotada en el commit del tramo

### Tests (antes del código)

- [ ] T002 [P] [US1] Tests en `tests/test_backup_retention_estimate.py` para `estimar_retencion` (data-model sección 4): solo backups con `with_automatic_settings`; global por copias (`copies=3` con cinco automáticos → los tres más antiguos con `after_next_automatic_backup`); global por días (con `ahora` fijo, los anteriores a `days` con `within_24h`); los dos a `None` → nada; retención por agente que sustituye a la global en ese agente (y `days=None` en el agente → ese agente no borra por días); un backup que sale por las dos reglas va una vez con `within_24h`; fechas ilegibles → no se estiman (fail-closed: no aparecen); orden por fecha. Casos copiados de las reglas de `backup/config.py` de HA 2026.11.1 con referencia en el docstring (FR-003)
- [ ] T003 [P] [US1] Tests en `tests/test_tools_ha_backup_settings.py`, `ha_list_backup_agents` con `ws_send` simulado (`backup/agents/info` y `backup/config/info`): `kind` de `backup.local`, `hassio.local`, `hassio.nas_backups` y `cloud.cloud`; `protected`/`retention` de la configuración y por defecto (`true`, `null`) si el agente no tiene entrada; `used_by_automatic_backups`; la contraseña centinela de `backup/config/info` no está en la respuesta ni en el log; HA < 2025.1 → `ha_version_unsupported`; `unknown_command` → `backup_integration_unavailable`; recorte con `truncated` (FR-001, FR-019, FR-020)
- [ ] T004 [P] [US1] Tests en `tests/test_tools_ha_backup_settings.py`, `ha_update_backup_config`: sin argumentos → `invalid_argument`; clave desconocida en cualquier nivel → `invalid_argument` con su nombre; `create_backup.password` (y `password` en `agents.<id>`) → `invalid_argument` sin el valor en la respuesta ni el log y sin llamar a HA; `days` repetido, `recurrence` desconocida, `time` sin forma, `copies: 0`, `include_all_addons` con `include_addons` → `invalid_argument`; la vista previa (sin token) no llama a `backup/config/update`, trae `current` y `resulting` sin contraseña y con `password_set`, `changed` correcto con la fusión de data-model sección 3 (`schedule: {"time": "04:30"}` manda el `schedule` completo con la `recurrence` y los `days` actuales, no `never`; `retention: {"copies": 3}` conserva `days`; un `null` explícito se manda; `create_backup` fundido; agentes por separado), los avisos de data-model sección 3 y `retention_effect` con `estimate: true`; con token, `backup/config/update` recibe exactamente lo pasado; configuración cambiada entre vista previa y confirmación (otro `retention`) → `state_changed` sin llamar a `update`; error de HA → redactado y token fallido (FR-002, FR-003, FR-019, FR-020)
- [ ] T005 [P] [US1] Tests en `tests/test_tools_ha_backup_settings.py`, `ha_get_update_backup_settings` (tres campos; `unknown_command` → `supervisor_integration_unavailable`) y `ha_set_update_backup_settings` (al menos uno; `add_on_backup_retain_copies` 0 o 101 → `invalid_argument`; vista previa con `current`, `resulting`, `changed` y el aviso al bajar las copias; con token, `hassio/update/config/update` con lo pasado; estado cambiado → `state_changed`) (FR-004)
- [ ] T006 [P] [US6] Tests en `tests/test_tool_families.py` (familia `backup_integration`, `desde="1.2.0"`, desactivable, con el módulo `ha_backup_settings`) y en `tests/test_tools_registration.py` (las cuatro en `_HINTS_NUEVAS_1_2_0`: `ha_list_backup_agents` y `ha_get_update_backup_settings` `R-I-`, `ha_update_backup_config` y `ha_set_update_backup_settings` `-DI-`, con sus títulos; las dos que modifican toman `confirmation_token`; con la familia desactivada no se registra ninguna y el resto no cambia) (FR-016, FR-018)

### Implementación

- [ ] T007 [US1] `hermes/src/hermes/backup_retention_estimate.py` con `estimar_retencion` (función pura, comentarios del porqué y de qué regla de HA reproduce cada rama). T002 en verde (FR-003)
- [ ] T008 [US1] `hermes/src/hermes/tools/ha_backup_settings.py` con las cuatro tools de contracts/tools.md: `register(mcp, ha_client, *, response_max_bytes)`, `@ready`, comprobación de versión y `_saneado`/`_config_permitida` de `tools/ha_backups.py` (reutilizadas, no copiadas), validación antes de llamar, vistas previas de data-model secciones 1, 3 y 5 con `estado=`, log con recuentos y sin valores. T003–T005 en verde (FR-001, FR-002, FR-004, FR-019, FR-020)
- [ ] T009 [US6] `hermes/src/hermes/tool_families.py` (familia `backup_integration` con `ha_backup_settings`), `hermes/src/hermes/tools/__init__.py` (registro bajo `if _activa("backup_integration")`) y `hermes/src/hermes/tools/_annotations.py` (`ha_update_backup_config` y `ha_set_update_backup_settings` en `_DESTRUCTIVE_EXACT` con el porqué: la retención borra backups; los ajustes previos deciden si hay copia antes de actualizar). T006 en verde (FR-016, FR-018, FR-023)

### Tabla

- [ ] T010 [P] [US6] Tests en `tests/test_tools_generic_commands.py`: `ha_read_ws_command`/`ha_call_ws_command` con `backup/agents/info`, `backup/config/update`, `hassio/update/config/info` y `hassio/update/config/update` → `use_dedicated_tool` con su tool y sin `ws_send`; con `backup_integration` desactivada → `family_disabled: true` (FR-017)
- [ ] T011 [US6] `hermes/src/hermes/command_table.py`: las cuatro entradas de data-model sección 13 (con `cap="CAP-057"`); sus claves en `_DEDICADAS_INICIALES` de `scripts/inventario/generar_tabla.py` (bloque comentado «031»); regenerar sobre la tabla editada (0 nuevas, 0 quitadas, idéntica byte a byte) y desde cero en un temporal (las cuatro salen iguales); anotarlo en el commit. Test nuevo `test_dedicadas_de_la_031` en `tests/test_command_table.py` (forma exacta y clave en el mapa). T010 en verde (FR-017)

### Guía

- [ ] T012 [US1] Tests en `tests/test_tools_guide.py` (tema `backup_integration` con contenido; nombra las cuatro tools; alias `backup_agents`, `backup_config`, `backup_schedule`, `backup_retention` resuelven a él; el índice lo menciona; `backup` sigue llevando a `backups`; los temas de la 1.1.2 no cambian) y después el tema en `hermes/src/hermes/tools/guide.py` (en español: cuándo estas y cuándo las `sv_*`, la retención y su estimación, que la clave de cifrado no sale ni se cambia aquí) (FR-021)

### Banco de Core

- [ ] T013 [US1] `tests/banco/ha_config/configuration.yaml`: `backup:` con comentario del porqué (agente `backup.local`, `/config/backups` del temporal, sin internet); `tests/banco/test_banco_backups_ajustes.py` (marcador `banco`, base de la 028): `ha_list_backup_agents` incluye `backup.local` con `kind: local`; `ha_update_backup_config` cambia `schedule` (`daily`, `04:30`) y `retention` (`copies: 2`) y el lector lo lee con `backup/config/info`; la vista previa no cambia nada (lector antes y después); `ha_get_update_backup_settings` → `supervisor_integration_unavailable`; rechazo de `ha_call_ws_command("backup/config/update")`. Limpieza: el lector deja la configuración como estaba (FR-022)
- [ ] T014 [US6] `tests/banco/cobertura_031.py` con `PROBADAS_031` (`ha_update_backup_config`; solo las que modifican), `LECTURAS_EN_BANCO_031` (`ha_list_backup_agents`; como `PROBADAS_EN_BANCO_029`, va solo a `TOOLS_EXIGIDAS_DEL_JOB`) y `NO_EJECUTABLES_031` (`ha_set_update_backup_settings`: «necesita la integración hassio, que solo carga con Supervisor; el banco es Core sin Supervisor; VM de la 014»); sumar `PROBADAS_031` y `NO_EJECUTABLES_031` a la unión del invariante de `tests/test_banco_cobertura_escrituras.py`, y `PROBADAS_031` y `LECTURAS_EN_BANCO_031` a `TOOLS_EXIGIDAS_DEL_JOB` de `tests/banco/cobertura_escrituras.py` (y a los tests que fijan esa unión); filas de las dos que modifican en la matriz de pruebas de `docs/HOJA-DE-RUTA.md` (`ha_update_backup_config`: banco de Core, ok; `ha_set_update_backup_settings`: VM, pendiente) y su línea en «Tandas de pruebas» de `docs/BANCO-SUPERVISOR.md` (FR-022)

### Cierre del tramo 1

- [ ] T015 Control negativo del tramo 1, anotando recuentos: (a) en `estimar_retencion`, no filtrar `with_automatic_settings` → caen los de T002; contar `copies` en vez de `copies - 1` → cae; (b) en `ha_update_backup_config`, dejar pasar `create_backup.password` → cae el de T004; copiar `password` a `current` → cae el centinela; no pasar `estado=` → cae `state_changed`; (c) `ha_set_update_backup_settings` fuera de `_DESTRUCTIVE_EXACT` → cae el de hints e `test_every_tool_that_asks_for_a_token_says_it_is_destructive`; (d) dejar `backup/config/update` en `deny` → caen T010 y `test_dedicadas_de_la_031`; (e) quitar `ha_update_backup_config` de `PROBADAS_031` → cae el invariante. Restaurar y comprobar verde
- [ ] T016 Documentación parcial y cierre (FR-024): recuento de tools (+4) y fila de la familia en `README.md`, `README.es.md` y `hermes/DOCS.md` (`TestToolCountInDocs`; `backup_integration` en la lista de `tool_families_disabled`); sección «Backups de Home Assistant» en `## [1.2.0]` de `hermes/CHANGELOG.md` con lo del tramo; 031 «en curso» en `docs/HOJA-DE-RUTA.md`; suite completa (los 6 conocidos y ninguno más); revisión del diff buscando datos personales e identificadores de modelos; commit en español con la línea base de T001, la regeneración de T011 y los recuentos de T015

---

## Tramo 2 — Crear y borrar (US2, US4, US5 clave)

### Tests (antes del código)

- [ ] T017 [P] [US5] Tests en `tests/test_backup_key.py` para `leer_clave_de_backups` (data-model sección 6): clave → `ClaveDeBackups(clave=…, motivo=None)`; `password` `None` o `""` → `no_key_configured`; `unknown_command` → `backup_integration_unavailable`; `HAConnectionError` sin código → `ha_unreachable`; respuesta sin `config` → `backup_integration_unavailable`; `repr()` y `str()` no contienen el centinela; ninguna llamada deja el centinela en el log; dos llamadas leen dos veces (sin caché) (FR-011)
- [ ] T018 [P] [US2] Tests en `tests/test_tools_ha_backups.py`: `ha_list_backups` devuelve `last_action_event` con los cuatro escalares; claves extra del evento (`agent_id`, `uploaded_bytes`) no salen; evento ausente → `null`; el resto de la respuesta no cambia (los tests existentes siguen sin tocar) (FR-010, FR-023)
- [ ] T019 [P] [US2] Tests en `tests/test_tools_ha_backup_actions.py`, `ha_create_backup`: `agent_ids` vacío, con más de 10 o con forma inválida → `invalid_argument`; un agente que no está en `backup/agents/info` → `unknown_agent` con `available`; `include_all_addons` con `include_addons` → `invalid_argument`; carpeta desconocida → `invalid_argument`; apps o carpetas sin `hassio.local` entre los agentes → `invalid_argument`; `encrypt=True` sin clave → `no_encryption_key` sin token; vista previa (data-model sección 7) sin llamar a `backup/generate`, con `kind` y `encrypted` de cada agente (`encrypt` y su `protected`; sin entrada de configuración, cifrado) y el aviso de agente remoto sin cifrar; con token, `backup/generate` recibe la clave centinela como `password` y la respuesta trae `backup_job_id` y `follow_with`; el centinela no está en la vista previa, la respuesta, el log ni el directorio de tokens; los agentes cambian entre vista previa y confirmación → `state_changed`; `Backup manager busy` → error redactado y token fallido (FR-005, FR-011, FR-019, FR-020)
- [ ] T020 [P] [US2] Tests en `tests/test_tools_ha_backup_actions.py`, `ha_create_automatic_backup`: sin `create_backup.agent_ids` → `automatic_backups_not_configured` sin token; vista previa con agentes, contenido, `encrypted` (= `password_set`) y `retention_effect` solo con `after_next_automatic_backup`; con token, `backup/generate_with_automatic_settings` y `backup_job_id`; configuración o backups cambiados → `state_changed` (FR-006, FR-003)
- [ ] T021 [P] [US4] Tests en `tests/test_tools_ha_backup_actions.py`, `ha_delete_backup`: id inválido → `invalid_argument`; `backup/details` sin backup → `not_found` sin token; vista previa (data-model sección 9) con todas las ubicaciones, `automatic`, `hermes_safety_backup` (id confirmado en una anotación de prueba en el `HERMES_CONFIG_BASE` propio) y el aviso de único backup con configuración; con token, `backup/delete` y respuesta `ok`; con `agent_errors` en un agente → `partial`, `deleted_from` y `failed` con el error enmascarado (`192.0.2.10` y un `token=centinela-031` no salen); una ubicación nueva entre vista previa y confirmación → `state_changed` (FR-009, FR-019)

### Implementación

- [ ] T022 [US5] `hermes/src/hermes/backup_key.py` (data-model sección 6) con comentarios del porqué (research R-3: por qué esta clave, por qué sin caché, por qué se tapa el `repr`). T017 en verde (FR-011)
- [ ] T023 [US2] [US4] `hermes/src/hermes/tools/ha_backup_actions.py` con las tres tools de contracts/tools.md (mismo patrón que `ha_backup_settings.py`; `estimar_retencion` de T007; `hermes_safety_backup` con una lectura pública nueva y de solo lectura de la anotación en `safety_retention.py`, que no toma el lock de escritura ni repara nada; la clave solo dentro de la confirmación, nunca en `args` ni en `estado`, que lleva `key_set`). T019–T021 en verde (FR-005, FR-006, FR-009, FR-019, FR-020)
- [ ] T024 [US2] `hermes/src/hermes/tools/ha_backups.py`: `last_action_event` por lista blanca en `ha_list_backups` y su descripción. T018 en verde (FR-010, FR-023)
- [ ] T025 [US6] `tool_families.py` (módulo `ha_backup_actions`), `tools/__init__.py`, `_annotations.py` (`ha_create_backup` y `ha_create_automatic_backup` en `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD`; `ha_delete_backup` en `_OPEN_WORLD`; cada una con su porqué) y `tests/test_tools_registration.py` (las tres en `_HINTS_NUEVAS_1_2_0`: `-D-O`, `-D-O`, `-DIO`) (FR-016, FR-018)

### Tabla

- [ ] T026 [P] [US6] Tests en `tests/test_tools_generic_commands.py`: `backup/generate`, `backup/generate_with_automatic_settings` y `backup/delete` por la genérica → `use_dedicated_tool` con su tool (el motivo ya no habla de `ha_call_service`) (FR-017)
- [ ] T027 [US6] `command_table.py`: las tres entradas de data-model sección 13 (sin `cap`), sin los comentarios de «hasta la tool dedicada de la 031»; en `specs/008-cobertura-total/inventario/core-ws.tsv`, sus filas con cobertura `si` y la nota con la tool nueva (research R-13); claves de `_DEDICADAS_INICIALES` hacia las tools nuevas; regenerar (idéntica; desde cero, iguales y sin « (acción de HA)»); `test_dedicadas_de_la_031` ampliado. T026 en verde (FR-017)

### Guía y banco

- [ ] T028 [US2] [US4] Tests y tema `backup_integration` ampliado en `guide.py`: crear (con `encrypt`, `follow_with` y `ha_list_backups`), crear con ajustes automáticos (borra por retención), borrar (todas las ubicaciones); alias `create_backup`, `delete_backup` (FR-021)
- [ ] T029 [US2] [US4] [US5] `tests/banco/test_banco_backups_acciones.py`: el lector fija una clave centinela con `backup/config/update` (`create_backup.password`) y la restaura al cerrar; `leer_clave_de_backups` con el `ha_client` de la sesión la devuelve; `ha_create_backup(agent_ids=["backup.local"])` con y sin `encrypt` → el backup aparece (lector, `backup/info`) con `protected` correcto, siguiéndolo con `ha_list_backups` hasta `state: idle`; con `ha_update_backup_config` (`create_backup.agent_ids: ["backup.local"]`, `retention.copies: 1`) y dos `ha_create_automatic_backup`, la vista previa del segundo estima borrar el primero y el lector ve que HA lo borra; `ha_delete_backup` del resto (lector: ya no están); ninguna respuesta ni el log capturado contienen el centinela. Añadir las tres a `PROBADAS_031` y sus filas (banco de Core, ok) a la matriz (FR-003, FR-011, FR-022, SC-002, SC-005)

### Cierre del tramo 2

- [ ] T030 Control negativo del tramo 2, anotando recuentos: (a) `ClaveDeBackups` sin `__repr__` propio → cae T017; (b) meter la clave en `args` del token → cae el centinela del directorio de tokens; (c) no validar `agent_ids` contra HA → cae `unknown_agent`; (d) `ha_delete_backup` sin `estado=` → cae `state_changed`; no enmascarar `failed` → cae; (e) `last_action_event` copiado entero → cae T018; (f) `ha_create_backup` fuera de `_OPEN_WORLD` → cae el de hints; (g) `backup/delete` en `deny` → caen T026 y `test_dedicadas_de_la_031`. Restaurar y comprobar verde
- [ ] T031 Documentación parcial y cierre: recuento (+3), CHANGELOG, DOCS y README; suite completa; revisión del diff; commit con los recuentos de T030 y la regeneración de T027 (FR-024)

---

## Tramo 3 — Restaurar (US3, US5 restauración)

### Preparación

- [ ] T032 Comprobar que la 019 está integrada: `compute_action_hash` de `security.py` es HMAC-SHA256 con clave en memoria (commit «action_hash con HMAC-SHA256 y clave en memoria (019)»). Si no, parar y avisar: sin él, `password` atado al token deja en disco un SHA-256 atacable sin conexión (research R-8). Línea base

### Tests (antes del código)

- [ ] T033 [P] [US3] Tests del cliente (en el fichero de tests de `ws_send` que exista, o `tests/test_ha_ws_send_sent.py`): `HAConnectionError.sent` es `False` cuando el WebSocket no está o falla `send_json`, y `True` en el timeout tras enviar y cuando la conexión cae con la petición pendiente; el resto de errores no cambia (FR-008)
- [ ] T034 [P] [US3] Tests en `tests/test_tools_ha_backup_restore.py`, vista previa de `ha_restore_backup` (data-model sección 8) con `backup/details`, `backup/agents/info` y `backup/config/info` simulados: todos los datos de FR-007 (data-model sección 8); `agent_id` ausente con el backup en `hassio.local` y `cloud.cloud` → elige `hassio.local` y `also_in`; solo en remotos → `agent_id_required` con la lista; `agent_id` donde no está → `not_found`; `restore_addons` o `restore_folders` que no están → `not_in_backup`; `restore_database` por defecto = `database_included`; con `hassio.local` presente, distinto con `restore_homeassistant` → `invalid_argument`, y sin él (Core sin Supervisor) se admite; `restore_database` sin `restore_homeassistant` → `invalid_argument`; nada que restaurar → `invalid_argument`; apps o carpetas sin `hassio.local` presente → `invalid_argument`; `password_source` en sus cuatro valores; avisos de reinicio, descarga remota y Hermes sustituido (`_HERMES_SLUG` en `restore_addons`); `password` y la clave centinela no están en la vista previa, el log ni el directorio de tokens; vista previa que no cabe en el tope → `response_too_large` sin token (FR-007, FR-019, FR-020)
- [ ] T035 [P] [US3] Tests en `tests/test_tools_ha_backup_restore.py`, token atado: con token y el backup cambiado en ese agente (fecha, una app de más, otra versión, `protected`, tamaño, ya no está) → `state_changed` sin `backup/restore`, uno por dato; otro `password` en la confirmación → token inválido; mismos argumentos → `backup/restore` con `agent_id`, listas, `restore_database` resuelto y `password` (el dado o la clave de HA leída en la confirmación) (FR-007, SC-003)
- [ ] T036 [P] [US3] Tests en `tests/test_tools_ha_backup_restore.py`, resultado: respuesta de HA → `completed`; error `password_incorrect` → `password_incorrect` y token fallido; `backup_not_found` → idem; otro error → `restore_failed` redactado; `HAConnectionError(sent=True)` (timeout o caída) → `restore_started` con `check_with` y token completado con ese resultado; `HAConnectionError(sent=False)` → error y token fallido; nunca `completed` sin respuesta (FR-008)
- [ ] T037 [P] [US5] Tests en `tests/test_sv_restore_backup_key.py`: `sv_restore_backup_full` y `_partial` sin `password` sobre un backup `protected: true` → vista previa con `password_source: backup_encryption_key` y, al confirmar, el POST lleva la clave centinela; sin clave en HA → `backup_encryption_key_unavailable` en la vista previa y el POST sin `password` (como hoy); con `password` → `provided` y el POST con ese (como hoy); no protegido → `not_needed`; «Invalid password for backup» → el error añade la pista de la clave anterior; el centinela no sale en la vista previa, la respuesta, el log ni el directorio de tokens; `tests/test_tools_supervisor.py` sigue verde sin cambios (FR-015, FR-023)

### Implementación

- [ ] T038 [US3] `hermes/src/hermes/ha.py`: atributo `sent` en `HAConnectionError` (por defecto `False`) y `ws_send` que lo pone a `True` tras enviar (comentario del porqué: research R-6). `hermes/src/hermes/tools/ha_backup_restore.py` con `ha_restore_backup` (contracts/tools.md; plazo de 30 s; `_HERMES_SLUG` de `tools/addons.py`). T033–T036 en verde (FR-007, FR-008)
- [ ] T039 [US5] `hermes/src/hermes/tools/backups.py`: `password_source` y la clave de HA en `sv_restore_backup_full`/`_partial` (`backup_key.py`); descripciones al día. T037 en verde (FR-015, FR-023)
- [ ] T040 [US6] `tool_families.py` (módulo `ha_backup_restore`), `tools/__init__.py`, `_annotations.py` (`ha_restore_backup` en `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD` con el porqué) y `tests/test_tools_registration.py` (`-DIO`) (FR-016, FR-018)

### Tabla, guía y banco

- [ ] T041 [P] [US6] Test en `tests/test_tools_generic_commands.py`: `backup/restore` por la genérica → `use_dedicated_tool` con `ha_restore_backup` (FR-017)
- [ ] T042 [US6] `command_table.py`: `backup/restore` a `dedicated` (data-model sección 13) sin su comentario de «hasta la tool dedicada»; fila del inventario (cobertura `si`, nota); `_DEDICADAS_INICIALES`; regenerar (idéntica; desde cero, igual); `test_dedicadas_de_la_031` comprueba que no queda «(spec 031)» en ninguna tabla. T041 en verde (FR-017, SC-001)
- [ ] T043 [US3] Tests y tema `backup_integration` completo en `guide.py`: restaurar (qué se sobrescribe, elegir ubicación, `password` y la clave de HA, `restore_started` y cómo comprobarlo, que Core se reinicia); alias `restore_backup`, `restore` (si `restore` no lo usa ya otro tema; si lo usa, no se toca) (FR-021)
- [ ] T044 [US3] `tests/banco/test_banco_backups_restaurar.py`: con la clave centinela fijada por el lector, `ha_create_backup` cifrado; vista previa de `ha_restore_backup(backup_id, agent_id="backup.local", restore_database=…)` con los datos de FR-007 (`kind: local`, `password_source: backup_encryption_key`); con `restore_addons` → `invalid_argument` (sin Supervisor); confirmación con `password="incorrecta"` → `password_incorrect` y HA sigue respondiendo sin haberse reiniciado (el lector, con la misma conexión abierta antes, lee `backup/info` después); nunca una restauración con éxito. `NO_EJECUTABLES_031` gana `ha_restore_backup` («restaurar escribe .HA_RESTORE y reinicia Core; el banco no sobrevive al reinicio; se prueban la vista previa, el token y la contraseña incorrecta, que HA comprueba antes; VM de la 014»); fila de la matriz (VM, pendiente, «instantánea antes») y su línea en «Tandas de pruebas» (FR-022)

### Cierre del tramo 3

- [ ] T045 Control negativo del tramo 3, anotando recuentos: (a) `sent` siempre `True` → cae el de orden no enviada; (b) quitar un dato de la huella (p. ej. las apps) → cae su caso de T035; (c) devolver `completed` en el timeout → cae T036; (d) no comprobar `not_in_backup` → cae; (e) `password` en la vista previa → cae el centinela; (f) `sv_restore_backup_full` sin la clave → cae T037; (g) `backup/restore` en `deny` → caen T041 y `test_dedicadas_de_la_031`. Restaurar y comprobar verde
- [ ] T046 Documentación parcial y cierre: recuento (+1), CHANGELOG (restaurar y `sv_restore_*` con la clave), DOCS y README; suite completa; revisión del diff; commit con los recuentos de T045 (FR-024)

---

## Tramo 4 — Safety backups cifrados y cierre (US5, US6)

### Preparación

- [ ] T047 Línea base; anotar si la 027 está integrada (`hermes/translations/`)

### Tests (antes del código)

- [ ] T048 [P] [US5] Tests de la opción: `tests/test_addon_manifest.py` (schema `list(auto|required|off)?` y opción `auto`), `tests/test_run_sh_options.py` (`HERMES_SAFETY_BACKUP_ENCRYPTION`), `tests/test_config_validation.py` (valor desconocido → `ValueError` al arrancar; por defecto `auto`), `tests/test_main_wiring.py` (llega a las tools de backups y a `fs_write`); y, si la 027 está, el de traducciones (FR-012)
- [ ] T049 [P] [US5] Tests en `tests/test_safety_backup_encryption.py` con `sv_request` y `ws_send` simulados, para `sv_create_safety_backup` y para `maybe_trigger_safety_backup`: `auto` con clave → POST `/backups/new/full` con `password` centinela y respuesta `encrypted: true`; `auto` sin clave (cada uno de los tres motivos) → POST sin `password`, `encrypted: false`, `encryption_skipped_reason` y aviso en el log sin valores; `required` sin clave → sin POST, `encryption_key_unavailable` (en el automático, la escritura devuelve ese error); `off` → POST como en la 1.1.2 sin leer la clave; el centinela no está en `last_safety_backup.json`, `safety_backups.json`, `pending_jobs.json`, el directorio de tokens ni el log; la ventana, el límite duro y el lock no cambian (FR-013, FR-011, SC-002)
- [ ] T050 [P] [US5] Tests en `tests/test_safety_retention.py`: `record_launch(..., encrypted=True)` lo guarda; la poda borra un safety backup `protected: true` con `encrypted: true` como uno sin proteger; uno `protected: true` sin `encrypted` (o con `false`) sigue excluido con `protected`; anotaciones antiguas sin el campo se leen igual (FR-014)
- [ ] T051 [P] [US5] Test transversal en `tests/test_safety_backup_encryption.py`: con la clave centinela en HA, una pasada por las ocho tools de la familia, `sv_create_safety_backup`, el safety backup automático y las `sv_restore_*` (simuladas) deja el centinela fuera de toda respuesta, vista previa, error, fichero bajo `HERMES_CONFIG_BASE` y log capturado (FR-011, FR-019, SC-002)

### Implementación

- [ ] T052 [US5] Opción `safety_backup_encryption`: `hermes/config.yaml` (schema con comentario del porqué y opción `auto`), `hermes/run.sh`, `hermes/src/hermes/config.py` (campo, validación y lectura de entorno), `hermes/src/hermes/__main__.py` y `tools/__init__.py` (cableado hasta `tools/backups.py` y `fs_write`); traducciones en `hermes/translations/en.yaml` y `es.yaml` si la 027 está (si no, anotarlo para quien integre la segunda). T048 en verde (FR-012)
- [ ] T053 [US5] `tools/backups.py` (`_crear_safety_backup`) y `fs_write.py` (`_maybe_trigger_safety_backup`): `leer_clave_de_backups` según la opción, `password` en el POST, `encrypted` en la respuesta y en `record_launch`, aviso en el log con el motivo (sin valores); descripción de `sv_create_safety_backup` al día. T049 en verde (FR-013, FR-023)
- [ ] T054 [US5] `hermes/src/hermes/safety_retention.py`: `record_launch(..., encrypted: bool = False)` y `_motivo_exclusion` según data-model sección 12, con comentario del porqué (research R-5). T050 en verde (FR-014)

### Guía, documentación y cierre

- [ ] T055 [US5] Tests y tema `backups` de `guide.py`: los safety backups van cifrados con la clave de HA según `safety_backup_encryption`; restaurarlos con `sv_restore_backup_full` sin `password` o desde la interfaz con el kit de emergencia; si se cambió la clave, la anterior; la retención los sigue podando (FR-021)
- [ ] T056 Documentación final (FR-024): sección «Backups de Home Assistant» completa en `## [1.2.0]` de `hermes/CHANGELOG.md` (ocho tools, familia, tabla, safety backups cifrados y la opción, `sv_restore_*` con la clave, `last_action_event`); `hermes/DOCS.md` (opción `safety_backup_encryption` con sus tres valores, qué pasa al cambiar la clave en HA, y la familia); `README.md` y `README.es.md` sincronizados; `SECURITY.md` (la clave de HA: se lee, se usa y se descarta; nunca en disco ni en el log); `docs/HOJA-DE-RUTA.md`: 031 «hecha» en la tabla del programa, «Cifrado de los safety backups (031)» fuera de lo pendiente, y las pruebas en vivo de quickstart.md en los pendientes manuales
- [ ] T057 [US6] Test en `tests/test_tools_registration.py`: con `tool_families_disabled: ["backup_integration"]` el registro es exactamente el de antes de la 031 (nombres, anotaciones y argumentos), y con la configuración por defecto las tools de la 1.1.2 no cambian salvo la descripción de `ha_list_backups`, `sv_create_safety_backup` y las `sv_restore_*` (FR-023, SC-006)
- [ ] T058 Matriz de trazabilidad de `specs/008-cobertura-total/plan.md`: filas CAP-027 (FR-068; `sv_create_safety_backup`, safety backup automático, `safety_retention`; `test_safety_backup_encryption.py`, `test_safety_retention.py`, `test_sv_restore_backup_key.py`) y CAP-057 (FR-067; las ocho tools; `test_tools_ha_backup_*.py`, `test_backup_retention_estimate.py`, `tests/banco/test_banco_backups_*.py`) (FR-024)
- [ ] T059 Control negativo del tramo 4, anotando recuentos: (a) `auto` sin mandar `password` con clave → cae T049; (b) `required` que crea sin clave → cae; (c) escribir `password` en `last_safety_backup.json` → cae el centinela de T049/T051; (d) `_motivo_exclusion` sin la excepción de `encrypted` → cae T050; admitir `protected` sin `encrypted` → cae; (e) valor desconocido de la opción aceptado → cae T048. Restaurar y comprobar verde
- [ ] T060 Cierre del tramo 4: suite completa (los 6 conocidos y ninguno más), CI en verde con el banco, revisión del diff (principio VIII), commit con los recuentos de T059

---

## Dependencias

- Tramo 1: T001 → resto. T002…T006 en paralelo. T007 tras T002; T008 tras T003…T005 y T007; T009 tras T006 y T008. T010 → T011 (tras T009). T012 tras T008. T013 y T014 tras T011. T015, T016 al final.
- Tramo 2 (tras el 1): T017…T021 en paralelo; T022 tras T017; T023 tras T019…T022; T024 tras T018; T025 tras T023. T026 → T027 (tras T025). T028 tras T023. T029 tras T027. T030, T031 al final.
- Tramo 3 (tras el 2 y con la 019): T032 → resto. T033…T037 en paralelo; T038 tras T033…T036; T039 tras T037; T040 tras T038. T041 → T042 (tras T040). T043 tras T038. T044 tras T042. T045, T046 al final.
- Tramo 4 (tras el 3): T047 → resto. T048…T051 en paralelo (T051 escrita ahora, en verde tras T053). T052 tras T048; T053 tras T049 y T052; T054 tras T050. T055 tras T053. T056, T057, T058 tras todo. T059, T060 al final.

## Paralelo

- Tramo 1: T002, T003, T004, T005, T006.
- Tramo 2: T017, T018, T019, T020, T021.
- Tramo 3: T033, T034, T035, T036, T037.
- Tramo 4: T048, T049, T050, T051.

## Estrategia

MVP = tramos 1 y 2 (US1, US2 y US4: configurar, crear y borrar con la
integración, lo que hoy no se puede hacer desde Hermes). El tramo 3 cumple el
compromiso más delicado de la 011 (restaurar) y el 4 cierra CAP-027. US6 se
comprueba en todos.
