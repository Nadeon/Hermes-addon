---
description: "Tareas de la sub-feature 021 — configuración del sistema (Hermes 1.2.0)"
---

# Tareas: configuración del sistema (021)

**Entrada**: `specs/021-configuracion-del-sistema/` (spec.md, plan.md,
research.md, data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `DummyMCP` o
`_RecordingMCP`, `AsyncMock` de `ws_send` que responde por `type` y FALLA si
recibe un comando de escritura que el test no espera,
`structlog.testing.capture_logs`. Datos ficticios (`light.salon`,
`lock.puerta`, `Invitada`, `192.0.2.10`, `homeassistant.tailXXXX.ts.net`,
`/ssl/fullchain.pem`, `centinela-021`). Nada de la instalación real ni de las
tools MCP de Hermes.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`.
Línea base en Windows al especificar (2026-11-15, punta `c4a57bf`): 2926
passed, 95 skipped, 6 failed (los 6 conocidos). Cada tramo termina con
exactamente esos 6 fallos en local; la referencia es el CI de Linux.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 núcleo, US2 exposición, US3 usuarios, US4 red y
HTTP, US5 analytics y labs, US6 nada se rompe.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado (uno o varios commits; el tramo no se cierra con la suite en rojo).
El b necesita el a integrado (comparte `cobertura_021.py`, el test de
`dedicadas_de_la_021` y el patrón de escritura); el c necesita el b.

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **a** — núcleo y exposición | **T001–T019** | Familias `core_config` y `assistant_exposure`; `ha_get_core_config`, `ha_update_core_config`, `ha_list_exposed_entities`, `ha_set_entity_exposure`, `ha_set_expose_new_entities` registradas, anotadas y probadas; cinco comandos a `dedicated` y `config/core/detect` a `read`; temas de la guía; banco con lector; `cobertura_021.py`; inventarios; documentación parcial |
| **b** — usuarios | **T020–T036** | Familia `users`; `ha_list_users`, `ha_create_user`, `ha_update_user`, `ha_delete_user` con protecciones (propietario, Hermes, sistema, último administrador) en vista previa y confirmación; cuatro comandos a `dedicated`; `auth/refresh_tokens` a `deny` revisado; tema `users`; banco con lector; inventarios; documentación parcial |
| **c** — red y HTTP, analytics y labs, cierre | **T037–T057** | Familia `core_network`; `ha_update_network_config`, `ha_update_http_config`, `ha_promote_http_config`; tres comandos a `dedicated`; `analytics/preferences` de mundo abierto; ninguna entrada «(spec 021)»; temas y `system_status` al día; banco de red, de la vista previa del HTTP y de CAP-074; inventarios; documentación final y matriz de la 008 |

---

## Tramo a — núcleo y exposición (US1, US2, US6)

### Preparación

- [x] T001 Comprobar la base (`git log` contiene `c4a57bf`; `tests/banco/cobertura_012.py`, `tests/test_matriz_pruebas.py`, `tests/test_confirmation_args_inventory.py` y el argumento `estado` de `create_confirmation_token` existen) y tomar la línea base de la suite; anotarla en el commit del tramo. Leer `tools/core_logs.py` (`ha_set_log_level`) y `tools/lovelace.py` (`estado=`) como patrón de escritura en dos pasos

### Tabla (tests primero)

- [x] T002 [P] [US6] Tests en `tests/test_command_table.py`: `test_dedicadas_de_la_021` con los cinco comandos del tramo a (`config/core/update` → `ha_update_core_config`/`core_config`; `homeassistant/expose_entity` → `ha_set_entity_exposure`, `expose_entity/list` y `expose_new_entities/get` → `ha_list_exposed_entities`, `expose_new_entities/set` → `ha_set_expose_new_entities`, los cuatro en `assistant_exposure`) con la forma exacta del generador (data-model) y su clave en `_DEDICADAS_INICIALES`; `config/core/detect` `read`, `open_world=True`, `cap="CAP-053"`, con su clave en `_POR_LA_TABLA` («spec 021: …»). En rojo (FR-003, FR-018)
- [x] T003 [P] [US6] Tests en `tests/test_tools_generic_commands.py`: `ha_call_ws_command`/`ha_read_ws_command` con cada uno de los cinco → `use_dedicated_tool` con su tool y sin `ws_send`; con su familia desactivada → `family_disabled: true`; `ha_read_ws_command("config/core/detect")` llama a HA y devuelve la respuesta redactada; el log no lleva coordenadas ni la zona horaria de la respuesta (FR-003, FR-018, FR-021)

### Tests de las tools (antes del código)

- [x] T004 [P] [US1] Tests en `tests/test_tools_core_config.py`, `ha_get_core_config`: de un `get_config` simulado salen los doce campos editables, `config_source` y `version` (nada de `components`, `allowlist_external_dirs`…); `unit_system` `metric`/`us_customary` desde el dict de HA y `null` + `unit_system_detail` si no cuadra; Core caído → error de siempre; log sin valores (FR-001, FR-020, FR-021)
- [x] T005 [P] [US1] Tests en `tests/test_tools_core_config.py`, `ha_update_core_config`: (a) cada validación de contracts → `invalid_argument` sin `ws_send` (sin campos; latitud 91; `unit_system="imperial"`; país `es`; moneda `eu`; URL con ruta; `update_units` sin `unit_system`); (b) vista previa solo con los campos pedidos, `before`/`after`, `unchanged` y cada código de aviso de data-model (uno por grupo de campos) y `yaml_source` con `config_source: yaml`; (c) valores iguales a los actuales → `no_changes` sin token; (d) sin token no se llama a `config/core/update`; (e) con token, una sola llamada con exactamente los campos pedidos (`""` → `null` en las URLs) y la respuesta con `applied` y la configuración releída; (f) con `time_zone` y más campos, dos llamadas: la zona SOLA y primero; si la zona falla (`invalid_info`) no hay segunda llamada y nada se da por aplicado; si la segunda falla, `result: "partial"` con `applied`/`failed` y la configuración releída; (g) estado cambiado entre vista previa y confirmación (otro `get_config`) → error de estado cambiado y ninguna escritura; (h) token de otra tool o con otros argumentos → rechazado; (i) error de HA con `centinela-021` → redactado; `unknown_command` → `unsupported_by_ha_version` con `ha_code`; log de vista previa y confirmación solo con nombres de campos (ni coordenadas, ni URLs, ni zona) (FR-002, FR-020, FR-021, SC-004, SC-006)
- [x] T006 [P] [US2] Tests en `tests/test_tools_assistant_exposure.py`: `ha_list_exposed_entities` → sobre común ordenado, `assistants` ordenados, filtros `assistant` y `domain` (inválidos → `invalid_argument`), cabecera `expose_new` de los tres asistentes y `total`, recorte al tope con `truncated`; `ha_set_entity_exposure` → validaciones (0 o 201 entidades, forma, asistente desconocido, `expose` no booleano, repetidos quitados antes de atar), entidad sin estado → `not_found` con `missing` y sin escritura, vista previa por asistente con `change`/`already`, aviso de cada asistente y `sensitive` (`lock.puerta`), `no_changes`, confirmación con una sola llamada `homeassistant/expose_entity` y `changed_entity_ids`, estado cambiado → nada, log sin `entity_id`; `ha_set_expose_new_entities` → `before`/`after`, aviso, `no_changes`, confirmación (FR-004…FR-006, FR-020, FR-021, SC-004)
- [x] T007 [P] [US6] Tests en `tests/test_tool_families.py` (`core_config` y `assistant_exposure`: `desde="1.2.0"`, desactivables, sus módulos y descripción) y en `tests/test_tools_registration.py` (las cinco en `_HINTS_NUEVAS_1_2_0`: `ha_get_core_config` y `ha_list_exposed_entities` `R-I-`, `ha_update_core_config` `-DI-`, `ha_set_entity_exposure` y `ha_set_expose_new_entities` `-DIO`, con título; las tres que escriben toman `confirmation_token`; con las dos familias desactivadas no se registra ninguna y el resto no cambia) (FR-017, FR-019, SC-001)

### Implementación

- [x] T008 [US1] `hermes/src/hermes/tools/core_config.py` con `ha_get_core_config` y `ha_update_core_config` según contracts y data-model: `register(mcp, ha_client, *, response_max_bytes)`, `@ready`, descripciones en inglés que dicen lo que hacen y lo que no, validación antes de llamar, `estado=` con los campos editables leídos, zona horaria primero, relectura tras escribir, redacción y log con nombres de campos. Comentarios del porqué (atomicidad de HA, fuente YAML). T004 y T005 en verde (FR-001, FR-002, FR-020, FR-021)
- [x] T009 [US2] `hermes/src/hermes/tools/assistant_exposure.py` con las tres tools: `entity_exists` de `tools/_common.py` antes de escribir (HA crearía una entrada huérfana), `sobre_de_lista` y `ajustar_lista_a_bytes`, `estado=` con la exposición leída de las entidades y asistentes pedidos, avisos por asistente, `sensitive`. T006 en verde (FR-004…FR-006)
- [x] T010 [US6] `hermes/src/hermes/tool_families.py` (familias `core_config` y `assistant_exposure`, con comentario del porqué de partirlas), `hermes/src/hermes/tools/__init__.py` (registro bajo `_activa`) y `hermes/src/hermes/tools/_annotations.py` (`ha_update_core_config`, `ha_set_entity_exposure`, `ha_set_expose_new_entities` en `_DESTRUCTIVE_EXACT`; las dos de exposición en `_OPEN_WORLD`; porqué en comentario). T007 en verde y el invariante «token ⇒ destructiva» de `test_tools_registration.py` sin tocar (FR-017, FR-019)

### Tabla

- [x] T011 [US6] `hermes/src/hermes/command_table.py`: los cinco comandos a `dedicated` (forma de data-model); sus claves en `_DEDICADAS_INICIALES` de `scripts/inventario/generar_tabla.py` (bloque comentado «021»); ejecutar el generador sobre la tabla editada y comprobar `git diff` vacío respecto a la edición a mano; generar desde cero en un temporal y comparar las cinco entradas; anotarlo en el commit (FR-018)
- [x] T012 [US1] `config/core/detect` a `read` con `open_world=True`, `cap="CAP-053"` y el motivo de data-model; `_POR_LA_TABLA` del test con su porqué. T002 y T003 en verde; `tests/test_command_table.py` entero en verde (incluido el que ata las marcas `open_world` a `_OPEN_WORLD`) (FR-003)

### Guía

- [x] T013 [US1] [US2] Tests en `tests/test_tools_guide.py` (temas `core_config` y `assistant_exposure` con contenido; nombran sus tools; `core_config` explica `ha_read_ws_command("config/core/detect")` y que sale a internet; `assistant_exposure` explica qué es cada asistente y que todo confirma; alias `location`, `units`, `time_zone` → `core_config` y `exposure`, `expose`, `voice`, `assist` → `assistant_exposure`; el índice los menciona; las huellas de `_HUELLAS_ANTES_DE_LA_013` no cambian) y después los temas en `hermes/src/hermes/tools/guide.py` y la lista del docstring de `hermes_guide` (FR-022)

### Banco de Core

- [x] T014 [US1] [US2] `tests/banco/test_banco_configuracion_sistema.py` (marcador `banco`, `BancoEscrituras` de `base_escrituras.py`, lector independiente): (a) `ha_get_core_config` coincide con `get_config` leído por el lector; (b) `ha_update_core_config(location_name=…, radius=…)` sin token → el lector ve la configuración igual y la vista previa lleva `yaml_source` (el banco tiene `homeassistant:` en YAML); con token → el lector ve los valores nuevos; restaurar en `finally` por la propia tool o el lector; (c) un `input_boolean` creado por el lector: `ha_set_entity_exposure` a `conversation` y `cloud.alexa` sin token → `expose_entity/list` del lector igual; con token → expuesto a los dos; ocultar y comprobar; (d) `ha_set_expose_new_entities("conversation", …)` cambiado y restaurado, comprobado con `expose_new_entities/get` del lector; (e) `ha_list_exposed_entities` incluye la entidad mientras está expuesta; (f) `ha_read_ws_command("config/core/detect")` responde un objeto (sin salida a internet, `{}`) y `ha_call_ws_command("config/core/update", …)` da `use_dedicated_tool`. Si algo falla contra HA real, `xfail` estricto con el error concreto (hallazgo) y anotado (FR-023, SC-003, SC-004)
- [x] T015 [US6] `tests/banco/cobertura_021.py` (docstring como `cobertura_012.py`): `PROBADAS_021` con `ha_update_core_config`, `ha_set_entity_exposure`, `ha_set_expose_new_entities`; `NO_EJECUTABLES_021 = {}`; `LECTURAS_021` con `ha_get_core_config` y `ha_list_exposed_entities`. Sumar `PROBADAS_021` y `NO_EJECUTABLES_021` a la unión de `tests/test_banco_cobertura_escrituras.py` y `PROBADAS_021 | LECTURAS_021` a `TOOLS_EXIGIDAS_DEL_JOB` de `tests/banco/cobertura_escrituras.py` (actualizar los tests que fijan esa unión) (FR-023)

### Inventarios y documentación

- [x] T016 [US6] Inventarios del programa: en `docs/HOJA-DE-RUTA.md`, entre los marcadores de la matriz de la 014, las filas `ha_update_core_config`, `ha_set_entity_exposure`, `ha_set_expose_new_entities` como `banco de Core | ok`; en `tests/test_confirmation_args_inventory.py`, sus tres entradas (todo `atado` salvo `confirmation_token`) y el recuento del docstring. `tests/test_matriz_pruebas.py`, `tests/test_confirmation_args_inventory.py` y `tests/test_allow_dangerous_inventario.py` en verde (FR-024)
- [x] T017 Documentación parcial: recuento de tools (+5) y filas de las dos familias en `README.md`, `README.es.md` y `hermes/DOCS.md` (`TestToolCountInDocs`, lista de `tool_families_disabled`); sección «Sistema» en `## [1.2.0]` de `hermes/CHANGELOG.md` con lo del tramo (sustituye el «_Pendiente_»); 021 «en curso» en la tabla del programa de `docs/HOJA-DE-RUTA.md` (FR-025)

### Cierre del tramo a

- [x] T018 Control negativo del tramo a, anotando recuentos: (a) mandar `time_zone` junto con el resto → caen los de (f) de T005; (b) no atar `estado` → cae el de estado cambiado (T005 g y T006); (c) no comprobar `entity_exists` → cae el de `not_found`; (d) quitar el aviso `yaml_source` → cae su test y el del banco; (e) registrar el valor de un campo en el log → cae el de log; (f) dejar `homeassistant/expose_entity` en `deny` → caen T002 y T003; (g) quitar `ha_set_entity_exposure` de `_OPEN_WORLD` → cae el de hints; (h) quitar `ha_update_core_config` de `PROBADAS_021` → cae el invariante de escrituras nombrándola. Restaurar y comprobar verde
- [x] T019 Cierre: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff buscando datos personales e identificadores de modelos (principio VIII), commit en español con la línea base de T001, la regeneración de T011 y los recuentos de T018

### Desviaciones y notas del tramo a

- **D-4, decidida por el supervisor**: ocultar no pide token (reduce la
  exposición); exponer sí. `ha_set_expose_new_entities` con `false` va sin
  token y con `true` con token. Por eso `ha_set_entity_exposure` y
  `ha_set_expose_new_entities` se anuncian `--IO` (no destructivas, de mundo
  abierto) y no `-DIO` como decían T007 y T010: una destructiva promete no
  actuar a la primera, y ocultar sí lo hace. El invariante «token ⇒
  destructiva» de `test_tools_registration.py` gana una excepción
  documentada, `TOKEN_SOLO_AL_AMPLIAR`, con su propio test (exactamente esas
  dos, siguen con token y su descripción dice cuándo no lo piden).
- Ocultar no responde `no_changes` aunque la entidad no salga en
  `expose_entity/list`: sin ajuste guardado puede estar expuesta por defecto
  (`expose_new` y dominio expuesto por defecto), así que siempre se manda y
  la respuesta es la de HA.
- Privacidad (decisión del supervisor): la confirmación de
  `ha_update_core_config` devuelve releídos solo los campos pedidos (no la
  configuración entera de data-model), y el fichero del token guarda solo
  `{"result", "applied"}` con nombres de campos.
- Sin campos, el `invalid_argument` de `ha_update_core_config` lleva
  `field: "fields"`.
- Errores de HA: `{"error": "ha_error", "ha_code", "detail"}` como dice
  data-model; `unknown_command` → `unsupported_by_ha_version` con
  `table_ha_core` (la forma de `system_status.py`).
- `test_tres_rutas_a_read` (013) comparaba `_READ_013` con TODO
  `_POR_LA_TABLA`; ahora con las claves «spec 013», porque la 021 añade
  `config/core/detect`.
- El tema `system_status` decía que Hermes no tenía tool para cambiar las
  URLs; ya la tiene (`ha_update_core_config`): una frase remite a ella. La
  red y el HTTP siguen para el tramo c.
- Banco: tras confirmar, HA pasa `config_source` a `storage` y solo vuelve a
  `yaml` al reiniciar (lo que dice el aviso); los valores se restauran, la
  fuente no puede. Ningún otro test la mira.

---

## Tramo b — usuarios (US3, US6)

### Preparación

- [x] T020 Línea base del tramo (suite) y comprobación de que el tramo a está integrado (`tests/banco/cobertura_021.py`, `test_dedicadas_de_la_021`)

### Tests de las tools (antes del código)

- [x] T021 [P] [US3] Tests en `tests/test_tools_users.py`, `ha_list_users`: de `config/auth/list` simulado (propietario, usuario de sistema «Supervisor» que es el de Hermes según `auth/current_user`, otro de sistema, un administrador, un usuario normal, uno inactivo con `system-admin`) salen los campos de data-model, `is_admin` (propietario o activo con `system-admin`: el inactivo no cuenta), `credential_types` solo con el tipo, `is_hermes`, `active_admins` (sin los de sistema); sin `include_system` no salen los de sistema salvo el de Hermes; `auth/current_user` falla → `is_hermes: null` y `hermes_user_known: false`; sobre común ordenado por nombre; respuesta sin ninguna clave de credencial aunque HA mande una de más (centinela); log sin nombres ni ids (FR-007, FR-020, FR-021)
- [x] T022 [P] [US3] Tests de las protecciones en `tests/test_tools_users.py` (con un `ws_send` que falla si recibe `config/auth/update|delete|create` sin esperarlo): `ha_update_user` y `ha_delete_user` sobre el propietario, el usuario de Hermes y uno de sistema → `protected_user` con `reasons` (todos los que aplican) y sin token; quitar `system-admin` o desactivar al único administrador activo no protegido (escenario sin propietario activo, construido a mano) → `last_admin`; `auth/current_user` falla → `preview_unavailable` en las tres que escriben; las protecciones se vuelven a comprobar al confirmar (el usuario pasa a ser el de Hermes, o a ser el último administrador, entre la vista previa y la confirmación → rechazo sin escritura) (FR-008, SC-005)
- [x] T023 [P] [US3] Tests de las escrituras en `tests/test_tools_users.py`: `ha_create_user` (validación de `name` y `group`; vista previa con `credentials: none…`, `grants_admin` con `system-admin`, `same_name`; confirmación con `config/auth/create` y `group_ids=[group]`, respuesta con la forma de la lista); `ha_update_user` (`user_id` sin forma de HA → `invalid_argument`; inexistente → `not_found`; vista previa con `changes`, `grants_admin`, `removes_admin`, `deactivates`, `restricts_remote` y `active_admins` antes/después; `no_changes`; confirmación con solo los campos dados; estado cambiado → nada); `ha_delete_user` (vista previa con `linked_persons` de `person/list`, `irreversible`, `active_admins`; confirmación con `config/auth/delete`); errores de HA (`no_delete_self`, `cannot_deactivate_owner`, `cannot_modify_system_generated`) traducidos y redactados; ninguna firma tiene argumento de contraseña ni de nombre de acceso; el fichero del token (en `CONFIRMATIONS_DIR` de la carpeta de tests) no contiene ningún valor de credencial (no hay ninguno que meter: el test lo fija con un centinela en la respuesta de HA) (FR-009…FR-012, SC-004, SC-006)

### Implementación

- [x] T024 [US3] `hermes/src/hermes/tools/users.py` con las cuatro tools según contracts y data-model: lectura de usuarios y de `auth/current_user` (uso interno, comentado: la entrada de la tabla sigue `deny` para la genérica), helper `_protecciones` llamado en la vista previa y al confirmar antes de escribir, `estado=` con el registro del usuario (y la lista de administradores activos), recuento de administradores, `person/list` para la vista previa de borrar, comentarios del porqué (lo que HA ya rechaza y lo que no; R-4 de research). T021…T023 en verde (FR-007…FR-012)
- [x] T025 [US6] Tests y luego `tool_families.py` (familia `users`), `tools/__init__.py` (registro), `_annotations.py` (`ha_create_user` y `ha_update_user` en `_DESTRUCTIVE_EXACT` con su porqué) y `_HINTS_NUEVAS_1_2_0` (`ha_list_users` `R-I-`, `ha_create_user` `-D--`, `ha_update_user` y `ha_delete_user` `-DI-`); con `users` desactivada no se registra ninguna (FR-017, FR-019, SC-001)

### Tabla

- [x] T026 [P] [US6] Tests en `tests/test_tools_generic_commands.py`: los cuatro `config/auth/*` → `use_dedicated_tool` sin `ws_send`; con `users` desactivada → `family_disabled: true`; `auth/refresh_tokens` y `config/auth_provider/homeassistant/admin_change_password` → rechazo `deny` sin `ws_send` (FR-012, FR-018)
- [x] T027 [US6] Tests en `tests/test_command_table.py`: `test_dedicadas_de_la_021` con los cuatro de CAP-056 (familia `users`); `_DENY_TRAS_REVISION` nuevo en el test de la clase A (claves de clase A de vía D que, tras leer el código, quedan `deny` con un motivo que no es «pendiente» y con la spec que lo revisa en el porqué), con `auth/refresh_tokens`; las cinco `config/auth_provider/homeassistant/*` y `auth/delete_refresh_token`, `auth/refresh_token_set_expiry` siguen `deny` (clase D, D-01) (FR-012, FR-018)
- [x] T028 [US6] `command_table.py`: los cuatro a `dedicated` y sus claves en `_DEDICADAS_INICIALES`; `auth/refresh_tokens` a `deny` con el motivo de data-model (y comentario del porqué encima: research R-5); regenerar y comprobar que no cambia nada; T026 y T027 en verde (FR-012, FR-018)

### Guía

- [x] T029 [US3] Tests y luego el tema `users` en `guide.py` (qué hace cada tool, que nada maneja contraseñas ni tokens, que el usuario creado no puede entrar hasta que una persona le dé credenciales en HA, las protecciones, que las sesiones no se pueden listar, que todo confirma); alias `user`, `accounts`; índice y docstring (FR-022)

### Banco de Core

- [x] T030 [US3] `tests/banco/test_banco_usuarios.py` (lector con `config/auth/list` directo a Core): (a) `ha_list_users` coincide con el lector y marca `is_hermes` y `is_owner` en el propietario del onboarding; (b) `ha_create_user` sin token → el lector no ve usuario nuevo; con token → lo ve sin credenciales y en `system-users`; (c) `ha_update_user`: renombrar, dar `system-admin` (vista previa con `grants_admin` y `active_admins` 1→2), quitarlo, `local_only`, desactivar; cada paso comprobado por el lector; (d) `ha_update_user` y `ha_delete_user` sobre el propietario (que en el banco es también el usuario de Hermes) → `protected_user` y el lector ve al propietario igual; (e) `ha_delete_user` del creado → el lector ya no lo ve; limpieza en `finally` por el lector si un paso falla; (f) `ha_call_ws_command("config/auth/delete", …)` → `use_dedicated_tool`. Hallazgos como `xfail` estricto (FR-023, SC-003, SC-005)
- [x] T031 [US6] `cobertura_021.py`: `ha_create_user`, `ha_update_user`, `ha_delete_user` en `PROBADAS_021`; `ha_list_users` en `LECTURAS_021` (FR-023)

### Inventarios, documentación y cierre

- [x] T032 [US6] Matriz de la 014 (tres filas `banco de Core | ok`) e inventario de argumentos atados (tres entradas) (FR-024)
- [x] T033 [P] [US3] Test de seguridad en `tests/test_tools_users.py`: por AST, ninguna tool de `users.py` tiene un argumento cuyo nombre contenga `password`, `secret` o `token` salvo `confirmation_token`; y, con `capture_logs`, una sesión completa (lista, crear, actualizar, borrar) no registra ningún nombre, id ni `username` (FR-012, FR-021, SC-006)
- [x] T034 Documentación parcial: recuento (+4) y fila de `users` en README, README.es y DOCS; sección «Sistema» del CHANGELOG con usuarios, las protecciones y que las sesiones no se pueden listar (FR-025)
- [x] T035 Control negativo del tramo b, anotando recuentos: (a) quitar la comprobación del usuario de Hermes → caen los de `protected_user` con `hermes` (unitarios y banco); (b) no recomprobar las protecciones al confirmar → cae el de T022 de cambio entre pasos; (c) contar inactivos como administradores → caen `active_admins` y `last_admin`; (d) `auth/current_user` fallido tratado como «no es Hermes» → cae `preview_unavailable`; (e) devolver `credentials` tal cual de HA → cae el centinela; (f) `auth/refresh_tokens` sin entrada en `_DENY_TRAS_REVISION` → cae el test de la clase A; (g) quitar `ha_delete_user` de `PROBADAS_021` → cae el invariante. Restaurar y comprobar verde
- [x] T036 Cierre: suite completa (los 6 conocidos), revisión del diff (principio VIII), commit con línea base, regeneración de T028 y recuentos de T035

### Desviaciones y notas del tramo b

- **Log con `user_id`** (decisión del supervisor): las escrituras registran el
  nombre de la tool, el paso, el resultado y el `user_id` (para auditar a quién
  se tocó); nunca nombres ni nombres de acceso. R-11 y T033 decían «ni ids»;
  T033 comprueba ahora que ningún id sale bajo otra clave que `user_id` y que
  la lista no registra ninguno.
- Usuarios protegidos: cualquier escritura sobre el propietario, el usuario
  de Hermes o uno de sistema es `protected_user` (FR-008), también renombrar o
  `local_only`. `last_admin` solo cuando el cambio le quita a la casa su
  último administrador activo (quitar el grupo, desactivar, borrar); renombrar
  al último administrador sí se puede.
- `ha_create_user` también lee `auth/current_user` y falla cerrado
  (`preview_unavailable`), como las otras dos; ata al token los ids con el
  mismo nombre (`same_name`).
- `linked_persons` va como `[{id, name}]` de `person/list` (almacenamiento y
  YAML), no como `entity_id`: `person/list` no da el `entity_id` y deducirlo
  podría mentir si se renombró. Sin la integración `person`, lista vacía.
- Errores de HA conocidos (`no_delete_self`, `cannot_*`, `not_found`) llevan
  además `explanation` en inglés; `detail` sigue siendo el texto de HA
  redactado.
- D-2 / D-27 (credenciales): Core 2026.11 tiene
  `config/auth_provider/homeassistant/create`, que añade usuario y contraseña
  a un usuario existente que no los tenga (`credentials_exist` si ya los
  tiene), pero no hay copia de la interfaz para comprobar que ofrezca hacerlo
  con un usuario creado sin ellos. La vista previa lo dice tal cual: la API
  existe, Hermes no la usa y no ha comprobado la interfaz; si no lo ofrece,
  borrar y crear desde Ajustes → Personas. Admitir credenciales no se
  implementa (D-27, para el final).
- Desde cero, el generador deja `auth/refresh_tokens` como `deny`
  «pendiente (spec 021)» (no está en `_DEDICADAS_INICIALES`): revisión manual,
  como `config/core/detect` en el tramo a. Las cuatro `dedicated`, iguales.

---

## Tramo c — red y HTTP, analytics y labs, cierre (US4, US5, US6)

### Preparación

- [x] T037 Línea base del tramo y comprobación de que el b está integrado; leer `fs_write.check_restart_allowed_sync` y su uso en `sv_restart_core`

### Tests de las tools (antes del código)

- [x] T038 [P] [US4] Tests en `tests/test_tools_core_network.py`, `ha_update_network_config`: adaptador inexistente o lista con repetidos o > 32 → `invalid_argument` con los disponibles y sin escritura; vista previa con `configured_adapters` y `enabled` antes/después (lista vacía → los `auto` de HA) y la nota de que no cambia dónde escucha HA; `no_changes`; confirmación con `network/configure` y `{"config": {"configured_adapters": [...]}}`; estado cambiado → nada; log sin nombres de adaptador ni direcciones (FR-013, SC-004)
- [x] T039 [P] [US4] Tests en `tests/test_tools_core_network.py`, `ha_update_http_config`: (a) validación (`changes` y `discard_pending` a la vez o ninguno; clave desconocida; tipos; `use_x_forwarded_for: true` sin proxies en el resultado) sin llamar a escribir; (b) fusión sobre la configuración ACTIVA (`stable`, `pending` o `default` según `active_config_type`), `null` quita la clave, metadatos (`created_at`, `error`, `error_message`) fuera; la confirmación manda el documento completo previsualizado; (c) un aviso por cada código de data-model, con el de `server_host` cuando la lista no incluye `0.0.0.0` ni `::`, y `pending_replaced` si hay pendiente; (d) bloqueo de reinicio activo → `restart_blocked` en la vista previa y al confirmar, sin escritura; (e) `discard_pending` → `config: null`, y sin pendiente → `no_changes`; (f) respuesta con `restart`, `next` y `config_check`; (g) `bind_failed`, `not_running` e `invalid_format` de HA → traducidos y redactados; (h) estado cambiado (otro `http/config`) → nada; (i) log sin puerto, hosts, rutas de certificado ni proxies (centinela `/ssl/fullchain.pem`, `192.0.2.10`); (j) `unknown_command` en `http/config` (HA anterior a 2026.11, sin la configuración HTTP en almacenamiento) → `unsupported_by_ha_version` con `ha_code` y la versión de la tabla, sin escritura (FR-014, FR-020, FR-021, SC-006)
- [x] T040 [P] [US4] Tests en `tests/test_tools_core_network.py`, `ha_promote_http_config`: sin pendiente, con `error` o con `active_config_type != "pending"` → `nothing_to_promote` con el motivo y sin token; vista previa con diff estable → pendiente, `revert_at` y la nota de recuperación; confirmación con `http/config/promote`; `not_allowed` de HA → traducido; estado cambiado → nada; `unknown_command` → `unsupported_by_ha_version` (FR-015, FR-020)

### Implementación

- [x] T041 [US4] `hermes/src/hermes/tools/core_network.py` con las tres tools según contracts y data-model; comentarios del porqué (HA rellena por defecto lo que falta; reinicio y prueba de 5 minutos; el Supervisor recibe el puerto nuevo al arrancar; el bloqueo de reinicio es el de `sv_restart_core`). T038…T040 en verde (FR-013…FR-015, FR-020, FR-021)
- [x] T042 [US6] Tests y luego `tool_families.py` (familia `core_network`, con comentario: no es la red del host de la 032), registro, `_annotations.py` (las tres en `_DESTRUCTIVE_EXACT` con su porqué) y `_HINTS_NUEVAS_1_2_0` (`-DI-`); con las cuatro familias de la 021 desactivadas, la lista de tools es exactamente la de antes de la 021 (`test_sin_las_familias_de_la_021_es_la_lista_de_antes`) (FR-017, FR-019, SC-001)

### Tabla y CAP-074

- [x] T043 [P] [US5] Tests en `tests/test_tools_generic_commands.py` con la tabla real: `ha_read_ws_command("analytics")` y `("labs/list")` leen; `ha_call_ws_command("analytics/preferences", {"preferences": {"base": false}})` y `("labs/update", {...})` piden token y, con él, llaman a HA con la carga exacta; en `tests/test_command_table.py`, `analytics/preferences` con `open_world=True` y las cuatro con `cap="CAP-074"` (FR-016)
- [x] T044 [US5] `command_table.py`: `analytics/preferences` con `open_world=True` y comentario del porqué encima (activar el envío manda datos a los servidores de Home Assistant). T043 en verde (FR-016)
- [x] T045 [US6] Tests y luego los tres de CAP-069 a `dedicated` (`network/configure` → `ha_update_network_config`, `http/config/configure` → `ha_update_http_config`, `http/config/promote` → `ha_promote_http_config`, familia `core_network`) con sus claves en `_DEDICADAS_INICIALES`; rechazo por la genérica; `test_dedicadas_de_la_021` completo con los doce y ninguna entrada «(spec 021)» en ninguna de las dos tablas; regenerar sobre la tabla editada (idéntica byte a byte) y desde cero en un temporal (las doce iguales) (FR-018, SC-002)

### Guía

- [x] T046 [US4] [US5] Tests y luego: tema `core_network` (las tres tools, la prueba de 5 minutos, los avisos, el bloqueo de reinicio, cómo leer con `ha_read_ws_command("network")` y `("http/config")`); sección «Analytics y labs» en `core_config` con las cuatro llamadas exactas; el tema `system_status` deja de decir que Hermes no tiene tool para cambiar la red y el HTTP y remite a `core_network` (actualizar su test de la 029); alias `http`, `ssl`, `port`, `proxy` y `network` → `core_network` (actualizar el test que fijaba `network` → `system_status`), `analytics`, `labs` → `core_config`; índice y docstring; las huellas de la 013 no cambian (FR-022)

### Banco de Core

- [x] T047 [US4] `tests/banco/test_banco_red_http.py`: (a) `ha_update_network_config` con los nombres de los adaptadores habilitados que lee el lector de `network`: sin token, el lector ve `configured_adapters` igual; con token, los ve; restaurar la lista previa en `finally`; (b) `ha_update_http_config(changes={"cors_allowed_origins": [...]})` sin token: vista previa con el documento fundido sobre el `http/config` real y el aviso de reinicio; el lector ve `http/config` idéntico antes y después (no se confirma: aplicar reiniciaría la HA del banco); (c) `ha_promote_http_config()` real → `nothing_to_promote` (el banco no tiene pendiente); (d) `ha_call_ws_command("http/config/configure", …)` → `use_dedicated_tool`. `cobertura_021.py`: `ha_update_network_config` en `PROBADAS_021`; `ha_update_http_config` y `ha_promote_http_config` en `NO_EJECUTABLES_021` con el motivo de research R-8 (FR-023, SC-003)
- [x] T048 [US5] `tests/banco/test_banco_analytics_labs.py`: `analytics` y `labs/list` por `ha_read_ws_command`; `analytics/preferences` con `{"base": false}` por `ha_call_ws_command` en dos pasos (el lector comprueba que `base` sigue `false`: no se activa ningún envío); `labs/update` con la primera función de `labs/list` (activar y desactivar, sin `create_backup`, comprobado por el lector) o, si la lista está vacía, su `not_found` real, anotado; `config/core/detect` ya está en T014 (FR-016, FR-023)

### Inventarios, documentación y cierre

- [x] T049 [US6] Matriz de la 014: `ha_update_network_config` `banco de Core | ok`; `ha_update_http_config` y `ha_promote_http_config` `VM | pendiente` con su nota y su línea en «Tandas de pruebas» de `docs/BANCO-SUPERVISOR.md` (cambiar el puerto o `cors_allowed_origins`, comprobar la reversión a los 5 minutos y la promoción); inventario de argumentos atados (tres entradas) (FR-024)
- [x] T050 Documentación final (FR-025): sección «Sistema» completa en `## [1.2.0]` de `hermes/CHANGELOG.md` (doce tools, cuatro familias, protecciones de usuarios, sesiones no listables, HTTP con reinicio y prueba, `config/core/detect` y CAP-074 por la tabla, `analytics/preferences` de mundo abierto, el cambio de texto y del alias `network` en la guía); `hermes/DOCS.md` (cuatro familias en `tool_families_disabled`, recuento); `README.md` y `README.es.md` sincronizados (+3 y fila de `core_network`); 021 «hecha» en la tabla del programa de `docs/HOJA-DE-RUTA.md`
- [x] T051 Matriz de trazabilidad de `specs/008-cobertura-total/plan.md`: filas CAP-053, CAP-055, CAP-056, CAP-069 y CAP-074 con las tools y entradas definitivas y los ficheros de test; en la fila de CAP-056, la desviación de las sesiones (research R-5) (FR-025)
- [x] T052 [P] [US6] Test de conjunto en `tests/test_tools_registration.py`: las nueve que escriben de la 021 toman `confirmation_token` y están en `_DESTRUCTIVE_EXACT` o en un prefijo destructivo; ninguna de las doce tiene argumentos de credenciales (AST, como T033 pero para los cuatro módulos) (FR-019, SC-006)
- [x] T053 Revisar `SECURITY.md`: si enumera tools que tocan accesos o credenciales, añadir las de `users` y `core_network` con una línea (sin cambiar la política); si no las enumera, nada (FR-025)
- [x] T054 Comprobación final de la tabla: ninguna entrada con «pendiente de tool dedicada (spec 021)»; generar desde cero y comparar las doce `dedicated`, `config/core/detect` y `auth/refresh_tokens` con la tabla (las dos últimas por sus excepciones del test); anotar el resultado (SC-002)
- [x] T055 Revisión del diff entero de la sub-feature (tres tramos) buscando datos personales, hostnames, IPs que no sean `192.0.2.x`, rutas `C:\` e identificadores de modelos (principio VIII)
- [x] T056 Control negativo del tramo c, anotando recuentos: (a) fundir sobre `stable` siempre → cae el de base `pending`; (b) no quitar los metadatos → cae el de documento enviado; (c) mandar solo los cambios (sin fundir) → cae; (d) sin bloqueo de reinicio al confirmar → cae `restart_blocked`; (e) sin el aviso `server_host` → cae; (f) promover sin comprobar `active_config_type` → cae; (g) quitar `open_world` de `analytics/preferences` → cae T043; (h) dejar `http/config/promote` en `deny` → caen T045 y el de «(spec 021)»; (i) mover `ha_update_http_config` de `NO_EJECUTABLES_021` a ninguna lista → cae el invariante. Restaurar y comprobar verde
- [x] T057 Cierre del tramo c: suite completa (los 6 conocidos), CI en verde con el banco, commit con línea base, regeneración de T045/T054 y recuentos de T056

### Desviaciones y notas del tramo c

- **D-3, decidida por el supervisor (fail-closed)**: `ha_update_http_config`
  rechaza sin token (`supervisor_lockout`) un `server_host` que deje fuera al
  Supervisor, y lo mira en el documento resultante (también si la base ya lo
  dejaba fuera). Comprobado en las fuentes: Core corre con la red del host
  (`network_mode="host"`) y el Supervisor le llega por la pasarela de su red
  interna, `http://172.30.32.1:<puerto>` (`DOCKER_IPV4_NETWORK_MASK[1]` de
  172.30.32.0/23), en IPv4. Valen `0.0.0.0` o `172.30.32.1`, o quitar la
  clave (HA escucha en `0.0.0.0` y `::`). Desviación del ejemplo del encargo:
  `::` sola NO vale, porque HA enlaza con `loop.create_server`, que pone
  `IPV6_V6ONLY` en los sockets IPv6 (no acepta IPv4); y de la red interna
  solo vale la pasarela (otra dirección de la /23 no es del host ni es a la
  que llama el Supervisor). Un nombre de host no se puede comprobar y se
  rechaza. T039 (c) pedía un aviso; ahora es este rechazo, y el aviso
  `server_host` queda para un cambio aceptado.
- **Pérdida de acceso** (decisión del supervisor): además de `warnings`, la
  vista previa lleva `access_risk` con un aviso claro cuando el cambio toca
  el puerto, `server_host`, el SSL, el proxy inverso, el bloqueo de IP o el
  perfil SSL. `base_url` no es una clave admitida (HA la quita del esquema):
  `invalid_argument`. Códigos de aviso extra respecto a data-model:
  `x_frame_options`.
- `restart_blocked` es un error sin token en la vista previa (no una vista
  previa con `blocked`, como `sv_restart_core`): el cambio reinicia HA y no
  tiene sentido emitir un token que no se podría usar. Al confirmar se vuelve
  a mirar y el token se da por fallido.
- `default_legacy_port`: la base es la de por defecto con el puerto 8123 (lo
  que HA usa en ese caso, `_DEFAULT_CONFIG_LEGACY_PORT`).
- Los diffs comparan valores efectivos (el del documento o el por defecto de
  `http/config`): quitar una clave que vale lo mismo que el defecto es
  `no_changes`.
- `ha_update_network_config`: `no_changes` compara conjuntos (el orden no
  cambia qué adaptadores se usan).
- Banco: `NO_EJECUTABLES_021` con las dos de HTTP; la vista previa de
  `ha_update_http_config` también se exige por ejecución
  (`VISTA_PREVIA_021` en `TOOLS_EXIGIDAS_DEL_JOB`). La de
  `ha_promote_http_config` en el banco solo puede ser su rechazo real, que no
  cuenta como llamada con éxito; su test lo comprueba igual.
- T053: `SECURITY.md` no enumera las tools que tocan accesos o credenciales;
  no se cambia.
- T054: desde cero, las doce `dedicated` salen iguales que en la tabla;
  `config/core/detect` y `auth/refresh_tokens` salen `deny` «pendiente (spec
  021)» (revisión manual, por sus excepciones del test) y
  `analytics/preferences` como la dejó la 011 (provisional de vía T revisada
  a mano). Ninguna entrada «(spec 021)» en la tabla real.
- Para el final: D-1 (sesiones), D-2/D-27 (credenciales en
  `ha_create_user`) y D-5 (familias de riesgo alto activas por defecto).

---

## Dependencias

- Tramo a: T001 → resto. T002, T003 en paralelo con T004…T007. T008 tras T004 y T005; T009 tras T006; T010 tras T007…T009; T011 tras T010 y T002; T012 tras T011 y T003. T013 tras T008 y T009. T014 y T015 tras T011. T016, T017 tras T014. T018, T019 al final.
- Tramo b (tras el a): T020 → resto. T021…T023 y T026 en paralelo; T024 tras T021…T023; T025 tras T024; T027 → T028 (tras T025); T029 tras T024; T030, T031 tras T028; T032, T033, T034 tras T030; T035, T036 al final.
- Tramo c (tras el b): T037 → resto. T038…T040 y T043 en paralelo; T041 tras T038…T040; T042 tras T041; T044 tras T043; T045 tras T042; T046 tras T041 y T044; T047, T048 tras T045; T049…T055 tras T047 y T048; T056, T057 al final.

## Paralelo

- Tramo a: T002, T003, T004, T005, T006, T007.
- Tramo b: T021, T022, T023, T026 (y T033 tras T024).
- Tramo c: T038, T039, T040, T043 (y T052 tras T042).

## Estrategia

MVP = tramo a (US1 y US2: núcleo y exposición, prioridad P1 y riesgo
medio). El b añade los usuarios (P1, riesgo alto: va solo para que su
revisión no se mezcle con nada). El c añade red y HTTP (P2, riesgo alto con
salida de HA de la prueba de 5 minutos), cierra CAP-074 (P3) y la
documentación. US6 se comprueba en los tres.

---

## Fase 4: Convergencia

Revisión independiente del rango `c4a57bf..c9679b4`. Severidad entre corchetes.

- [x] T058 [MEDIO] La vista previa de `ha_promote_http_config` solo lleva el diff, `revert_at` y la nota de recuperación: no repite los avisos de acceso. Promover es el paso que hace permanente una configuración que puede haber dejado la casa fuera (p. ej. `server_host: ["172.30.32.1"]`, que pasa D-3 y deja sin acceso a la LAN): sin promover, HA vuelve sola a la estable en 5 minutos; promovida, pasa a ser también la de recuperación. Arreglo mínimo: en `core_network.py`, calcular los grupos del diff con `_GRUPO_HTTP` y añadir a la vista previa `warnings` (los mismos códigos de `_AVISOS_HTTP`) y `access_risk` cuando alguno sea de acceso, con un texto que diga que solo se promueve cuando el usuario haya comprobado que llega a HA; test con un pendiente de `server_host` y su control negativo per FR-015, FR-074 de la 008, principio V (partial)
- [x] T059 [BAJO] Con un pendiente en prueba, unos `changes` cuyo resultado es igual a la estable hacen que HA descarte el pendiente (`async_set_pending`: igual a `stable` → `None`) y reinicie con la estable; Hermes enseña el aviso de prueba de 5 minutos y responde `next` «promote it with ha_promote_http_config», que luego da `nothing_to_promote`. Arreglo mínimo: si el documento fundido (sin metadatos) es igual a `stable`, decirlo en la vista previa (vuelve a la estable, sin prueba) y en `next`; test per FR-014, principio V (partial)
- [x] T060 [BAJO] El porqué de D-3 (docstring de `core_network.py`, `_SIN_SUPERVISOR`, guía) dice que el Supervisor, y con él Hermes y todas las apps, llegan a Core por TCP en `172.30.32.1`. Con Core ≥ 2026.4 (`CORE_UNIX_SOCKET_MIN_VERSION` de `supervisor/homeassistant/api.py`) el Supervisor habla con Core por el socket Unix `SUPERVISOR_CORE_API_SOCKET`, que no depende de `server_host`; lo que sí corta un `server_host` sin `0.0.0.0` ni `172.30.32.1` son las apps que conectan directamente a `homeassistant:8123` desde la red `hassio`. El rechazo se mantiene (fail-closed); corregir el texto para que diga eso, sin afirmar que Hermes se quedaría fuera, per FR-014, FR-022, principio V (contradicts)
- [x] T061 [BAJO] La vista previa de `ha_update_network_config` solo da nombres de adaptadores: elegir solo adaptadores sin IPv4 o sin el `default` (p. ej. uno de Docker) degrada el descubrimiento y la detección de la IP de origen (`async_get_source_ip`) sin ningún aviso. Arreglo mínimo: aviso en la vista previa si los habilitados después no tienen ninguna IPv4 o no incluyen el adaptador `default` (los dos datos ya llegan en `network`); test per FR-013, FR-074 de la 008 (partial)

### Notas de la convergencia

- T058: la vista previa de promover lleva `warnings` (los mismos códigos de
  aplicar) y `access_risk` con un texto propio (promover hace permanente la
  configuración; que Hermes siga funcionando no prueba nada). Aviso nuevo
  `server_host_internal_only` (solo la pasarela o loopback: la red de casa
  se queda fuera), también al aplicar. D-3 se comprueba también al promover,
  antes del token: vale para la vista previa y para la confirmación.
- T059: `_vuelta_a_estable` da `yes` si lo fundido es igual a la estable sin
  metadatos (lo que compara `async_set_pending`), `maybe` si solo es igual
  contando los valores de `default` (HA compara tras rellenar su esquema) y
  `no` en otro caso. La vista previa lleva `trial` (`false`/`null`/`true`) y
  su `restart`; la respuesta, su `next`. En `yes` no sale `pending_replaced`.
- T060: comprobado en las fuentes: `CORE_UNIX_SOCKET_MIN_VERSION` y
  `api_url`/`ws_url` por socket (`supervisor/homeassistant/api.py`), el proxy
  de las apps usa esa misma API (`api/proxy.py`), `homeassistant` resuelve a
  la pasarela (`plugins/dns.py`) y Core abre el socket con
  `SUPERVISOR_CORE_API_SOCKET` (`http/__init__.py`). Corregidos el docstring,
  `_SIN_SUPERVISOR`, el aviso `server_host`, el docstring de la tool, la guía
  y el CHANGELOG. El código de error sigue siendo `supervisor_lockout`. La
  `spec.md` conserva el texto original (histórico).
- T061: avisos `no_ipv4` y `default_adapter_excluded` en la vista previa de
  red; el banco comprueba que salen con la forma real de `network`.
- Controles negativos (en `tests/test_tools_core_network.py`): sin los avisos
  al promover caen 2; sin D-3 al promover, 1; sin `server_host_internal_only`,
  3 (con subtests); sin la vuelta a la estable, 2; con el texto viejo de
  D-3, 1; sin los avisos de red, 2; con la guía de antes, 1 en
  `tests/test_tools_guide.py`.

- *Nota posterior (integración en la rama del programa, ajuste del
  supervisor)*: el código de error `supervisor_lockout` que citan T053 y la
  desviación D-3 de arriba (texto histórico) pasa a llamarse `apps_lockout`
  en el código, los tests, la guía, el CHANGELOG y los README: lo que se
  corta son las apps que conectan directamente, no el Supervisor. Test:
  `test_el_codigo_dice_que_se_corta_a_las_apps` en
  `tests/test_tools_core_network.py`.
