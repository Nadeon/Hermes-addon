---

description: "Tareas de la sub-feature 016 — integraciones: flujos y Repairs (Hermes 1.2.0)"
---

# Tareas: integraciones, flujos y Repairs (016)

**Entrada**: `specs/016-integraciones-flujos-y-repairs/` (spec.md, plan.md,
research.md, data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `CONFIRMATIONS_DIR` en
un `tempfile.TemporaryDirectory`, `DummyMCP`/`_RecordingMCP`, `AsyncMock` de
`ws_send` y `_request_json`, `structlog.testing.capture_logs`. Datos ficticios
(`<entry_id>`, `banco_flujos`, `hue`, `light.salon`, `centinela-016` bajo una
clave `password`, un JWT de prueba). Nada de la instalación real ni de las
tools MCP de Hermes.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" python -m pytest -q -p no:cacheprovider`.
Línea base en Windows al especificar (2026-11-14, punta `ab5098d`: la 011
hasta su tramo 3 en curso, sin la 009 ni la 010 integradas): 2126 passed, 17
skipped, 6 failed (los 6 conocidos). T001 la vuelve a tomar tras integrar las
dependencias. Cada tramo termina con exactamente esos 6 fallos en local; la
referencia es el CI de Linux.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 descubiertos, US2 ajustar una integración, US3
subentries, US4 arreglar con Repairs, US5 textos de los avisos, US6 helpers
por config entry, US7 nada se rompe.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado (uno o varios commits; el tramo no se cierra con la suite en rojo).
**Ninguno empieza antes de que la 011 esté integrada** (S-01; T001).

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **A** — descubiertas, preferencias y guía de helpers | **T001–T017** | Familia `integration_flows` (con `integration_setup`); `ha_list_discovered_integrations`, `ha_ignore_discovery`, `ha_list_config_flow_domains`, `ha_update_config_entry` registradas, anotadas y probadas; docstring de `ha_list_configured_domains` corregida; 3 entradas en `dedicated` con el generador al día; tema `integration_flows` (parte A), sección de helpers por config entry; integración de prueba `banco_flujos` y banco A; CHANGELOG y hoja de ruta parciales |
| **B** — subentries y reconfigure | **T018–T029** | `ha_list_config_subentries`, `ha_start_subentry_flow`, `ha_continue_subentry_flow`, `ha_abort_subentry_flow`, `ha_update_subentry`, `ha_delete_subentry`, `ha_start_reconfigure_flow`; 3 entradas en `dedicated`; tema completo; banco B |
| **C** — reparación y traducciones | **T030–T045** | `_translations.py`; textos en `ha_list_repairs` y `ha_ignore_repair`; `ha_get_repair`, `ha_start_repair_fix`, `ha_continue_repair_fix`, `ha_abort_repair_fix` en la familia `repair_flows`; `repairs/get_issue_data` en `dedicated`; tema `repair_flows`; banco C; documentación final y matriz de la 008 |

El tramo B necesita el A integrado; el C, el A (familia, banco) y no el B.
Si el tramo B no cabe en un agente, se parte como dice plan.md («Tramos»).

---

## Tramo A — descubiertas, preferencias y guía de helpers (US1, US2, US6, US7)

### Preparación

- [ ] T001 Integrar en la rama lo que falta de las dependencias (S-01): la 011 entera (genéricas, tabla revisada, opción `tool_families_disabled`, registro por familias, tema `generic_commands`), la 009 (redacción lineal y `## [1.2.0]`), la 010 (banco) y, si están, la 028 (invariante de escrituras) y la 012 (cambio del generador), por merge desde `feat/cobertura-total` o desde sus ramas según lo que esté integrado; resolver conflictos sin cambiar comportamiento. Ejecutar la suite y anotar la línea base en el mensaje del commit. Si la 011 no está integrada, NO seguir: avisar al supervisor. Si la 010 no está, seguir y marcar T012–T013 como pendientes (nota en el commit y en `docs/HOJA-DE-RUTA.md`)

### Familia (US7)

- [ ] T002 [P] [US7] Tests en `tests/test_tool_families.py`: `integration_flows` existe, `desde="1.2.0"`, desactivable, con exactamente los módulos del tramo (`integration_setup`); `validar_desactivadas(["integration_flows"])` la acepta; el test existente de SC-005 (familias de la 1.2.0 desactivadas → las 216 de la 1.1.2) sigue pasando sin tocarlo (FR-017)
- [ ] T003 [US7] `hermes/src/hermes/tool_families.py`: `Familia("integration_flows", …)` según data-model, en el bloque de la 1.2.0, con comentario del porqué de dos familias (research R-8). T002 en verde (FR-017)

### Tests de las tools del tramo (escritos antes de T008)

- [ ] T004 [P] [US1] Tests de `ha_list_discovered_integrations` en `tests/test_tools_integration_setup.py`: un solo `ws_send({"type": "config_entries/flow/progress"})`; campos de data-model (`name` de `title_placeholders.name` o `null`; `ignorable` según `unique_id`, sin devolver su valor ni el `context` entero); orden por dominio y `flow_id`; filtro `domain`; `domain="Hue X"` → `invalid_argument` sin `ws_send`; respuesta que no es lista → `unexpected_response`, no lista vacía; centinela y JWT en `title_placeholders` → tapados en la respuesta y ausentes del log capturado; muchos flujos con `response_max_bytes` pequeño → sobre con `truncated: true` y recuentos coherentes (FR-001, FR-021, FR-022)
- [ ] T005 [P] [US1] Tests de `ha_ignore_discovery`: lee `flow/progress` y después un solo `ws_send` con `config_entries/ignore_flow`, `flow_id` y el título (el pasado, o `title_placeholders.name`, o el dominio); flujo que no está → `not_found` sin `ignore_flow`; sin `unique_id` → `cannot_ignore` (`reason: "no_unique_id"`) sin `ignore_flow`; `title` vacío o de 256 caracteres → `invalid_argument`; `flow_id` con `/` o `..` → `invalid_argument`; HA responde `not_found` al ignorar → `not_found`; respuesta con `undo_hint`; error de HA con un centinela → tapado (FR-002, FR-021)
- [ ] T006 [P] [US2] [US6] Tests de `ha_list_config_flow_domains`: `GET /config/config_entries/flow_handlers` sin y con `?type=helper` (por `_request_json`, ruta segura); `type="widget"` → `invalid_argument` sin llamar; lista ordenada y en el sobre; respuesta que no es lista → `unexpected_response`. Y un test de texto: la docstring de `ha_list_configured_domains` ya no afirma que no exista la lista y nombra `ha_list_config_flow_domains` (FR-003, FR-022)
- [ ] T007 [P] [US2] Tests de `ha_update_config_entry`: (a) validación sin llamar a HA: nada pedido, `title` vacío o de 256, booleanos que no son `bool`, `entry_id` inválido; (b) lectura previa `config_entries/get_single`: inexistente → `not_found`; valores iguales → `unchanged` sin `config_entries/update`; (c) solo título, o volver a activar sondeo o entidades → un solo `config_entries/update` con solo los campos que cambian, SIN token, y respuesta con `config_entry`, `require_restart` y `reloaded` (verdadero al reactivar el sondeo de una entrada `loaded`, falso al cambiar solo el título); (d) `pref_disable_polling=true` con la entrada `loaded` → vista previa con actual/nuevo, estado, efecto de recarga y de sondeo, token y NINGÚN `config_entries/update`; con la entrada `not_loaded`, el efecto dice que no se recarga ahora; (e) `pref_disable_new_entities=true` → vista previa con su efecto; (f) confirmación → un solo `config_entries/update`; token con otro título u otra preferencia → rechazado sin enviar; token reutilizado → rechazado; (g) lectura previa que falla → `preview_unavailable` sin token; (h) centinela en el título → no está en los ficheros de `CONFIRMATIONS_DIR` ni en el log (FR-004, FR-021, SC-003, SC-004)

### Implementación

- [ ] T008 [US1] [US2] `hermes/src/hermes/tools/integration_setup.py` (research R-1…R-3, data-model): `register(mcp, ha_client, *, response_max_bytes)` con las cuatro tools, `@ready`, docstrings en inglés que dicen lo que hacen y lo que no (ignorar se deshace borrando la entrada `ignore`; cuándo pide token `ha_update_config_entry` y qué pasa al desactivar el sondeo), dos pasos con `create_confirmation_token`/`validate_confirmation_token`/`complete_confirmation_token`, redacción (reutilizando el `_redactar` de `repairs.py`, movido a `_common.py` si se comparte, sin cambiar su comportamiento ni sus tests), sobre con `ajustar_lista_a_bytes`, eventos de log de data-model. Comentarios en español con el porqué. T004–T007 en verde (FR-001…FR-004, FR-021, FR-022)
- [ ] T009 [US7] Registro, anotaciones y docstring: `register_integration_setup` en `hermes/src/hermes/tools/__init__.py` dentro de `if _activa("integration_flows")`, con `response_max_bytes`; `ha_update_config_entry` en `_DESTRUCTIVE_EXACT` de `tools/_annotations.py` con el comentario de contracts/tools.md; docstring de `ha_list_configured_domains` (y la nota del módulo `config_entry_flows.py`) corregida según research R-2, sin tocar nombre, argumentos ni anotaciones. Tests en `tests/test_tools_registration.py`: hints y títulos de las cuatro según contracts/tools.md; con `integration_flows` desactivada no aparece ninguna; las de la 1.1.2 sin cambios (los invariantes existentes, incluidos «pide token ⇔ destructiva», `test_flow_handlers_tool_renamed_to_what_it_does` y `test_esquemas_de_la_1_1_2`, pasan sin excepciones nuevas) (FR-003, FR-017, FR-019, FR-024)

### Tabla y generador (US7)

- [ ] T010 [US7] Tabla: (a) tests primero: en `tests/test_tools_generic_commands.py`, `ha_read_ws_command("config_entries/flow/progress")` → `use_dedicated_tool` con `ha_list_discovered_integrations` y, con `integration_flows` desactivada, `family_disabled: true`; `ha_call_ws_command("config_entries/update", …)` → `use_dedicated_tool` sin token ni llamada; si la 012 no lo hizo ya (S-03): en `tests/test_generar_tabla.py`, una fila A de vía D cuya clave está en `_DEDICADAS_INICIALES` sale `dedicated` con la familia de su tool en la primera generación, y en `tests/test_command_table.py`, `test_clase_a_de_via_dedicada_pendiente_de_su_spec` admite `dedicated` con una tool de una familia `desde="1.2.0"` y sigue fallando con `read`/`confirm`; (b) `scripts/inventario/generar_tabla.py`: las tres claves en `_DEDICADAS_INICIALES` y, si falta, la consulta del mapa para la clase A antes de la regla «pendiente» (research R-7); (c) `hermes/src/hermes/command_table.py`: `config_entries/flow/progress`, `config_entries/ignore_flow` y `config_entries/update` a `E("dedicated", "cubierto por <tool>", "integration_flows", tool=…, cap="CAP-044")`; (d) ejecutar el generador y comprobar que `git diff -- hermes/src/hermes/command_table.py` no cambia nada respecto a (c); anotarlo en el commit (FR-018, SC-002)

### Guía (US6, US7)

- [ ] T011 [US6] [US7] `hermes/src/hermes/tools/guide.py`: tema `integration_flows` con la parte A de contracts/tools.md (descubiertos: listar, configurar con `ha_continue_config_entry_flow`, ignorar y deshacer; dominios configurables; título y preferencias, qué pide token y por qué) y alias `discovery`, `discovered`; sección «Helpers por config entry» en `helpers` (FR-016: `ha_list_config_flow_domains(type="helper")`, `ha_start_config_entry_flow("template")` → `ha_continue_config_entry_flow` con un ejemplo de menú y formulario, `ha_list_config_entries(type_filter="helper")`, flujos de opciones, `ha_delete_config_entry`; qué hacer con la familia desactivada); línea en `config_entries` que remite al tema nuevo. Tests en `tests/test_tools_guide.py`: el tema existe con sus alias; cada tool registrada de `integration_flows` aparece nombrada en él (test genérico que B no tiene que tocar); el índice lo lista; `helpers` nombra las cinco tools de la receta y la guía no nombra ninguna tool que no exista (FR-016, FR-020)

### Banco (US1, US2)

- [ ] T012 [US1] [US2] [US3] [US4] Integración de prueba del banco (research R-9): `tests/banco/ha_config/custom_components/banco_flujos/` con `manifest.json` (`config_flow: true`, `version`, `iot_class: "local_push"`, sin requisitos), `__init__.py` (`async_setup` con `banco_flujos:` abre un flujo de descubrimiento con `unique_id` fijo y crea dos avisos reparables con `translation_key` y marcadores (uno para arreglar y otro para abortar); `async_setup_entry` reenvía a `sensor`), `config_flow.py` (paso de descubrimiento con confirmación, `user` con un campo, `reconfigure` que actualiza `data` y recarga, `async_get_supported_subentry_types` con `elemento` y sus pasos `user` y `reconfigure`), `sensor.py` (un sensor por subentry con `config_subentry_id`), `repairs.py` (formulario de confirmación con un campo opcional) y `translations/en.json` (textos del aviso, de su `fix_flow` y del flujo, con marcadores); comentario en cada fichero: es configuración del banco, nunca se empaqueta ni llega al add-on. `banco_flujos:` en `tests/banco/ha_config/configuration.yaml` con comentario. Un test de humo del banco: la integración carga (el lector ve su descubrimiento y sus dos avisos). Comprobación de privacidad: textos genéricos (FR-023, FR-026, S-04)
- [ ] T013 [US1] [US2] `tests/banco/test_banco_integraciones.py` (parte A, con el marcador y la base de la 010): `ha_list_discovered_integrations` ve el descubrimiento con `ignorable: true`; `ha_ignore_discovery` → el lector ve una entrada `source: "ignore"` con ese título y el descubrimiento ya no está; limpieza: el lector borra la entrada y (si HA lo redescubre) lo anota; `ha_list_config_flow_domains` incluye `banco_flujos` y, con `type="helper"`, `template`; el lector crea una entrada por el flujo `user`; `ha_update_config_entry` cambia el título sin token (el lector lo ve); con `pref_disable_polling=true` la vista previa no cambia nada (el lector lo comprueba) y con el token sí; `ha_update_config_entry` con `pref_disable_new_entities=true` igual; limpieza. `tests/banco/cobertura_016.py` con `PROBADAS_016 = {ha_ignore_discovery, ha_update_config_entry}` y `NO_EJECUTABLES_016 = {}`, sumada a la unión de `tests/test_banco_cobertura_escrituras.py` de la 028 o, si no está integrada, con `tests/test_banco_cobertura_016.py` propio (S-02). Si la 010 no está, pendiente con nota (S-01) (FR-023, SC-005)

### Documentación y cierre del tramo

- [ ] T014 Documentación parcial: sección «Integraciones: flujos y Repairs (spec 016)» en `## [1.2.0]` de `hermes/CHANGELOG.md` con las cuatro tools, la familia, las tres entradas de la tabla, la docstring corregida y la guía de helpers; fila 016 de la tabla del programa en `docs/HOJA-DE-RUTA.md` → «en curso (tramo A)» (FR-025)
- [ ] T015 [US7] Revisión del principio V: leer cada docstring y el tema de la guía contra lo que hace el código (cuándo pide token `ha_update_config_entry`, qué se deshace y cómo al ignorar, que la lista de dominios incluye integraciones personalizadas); corregir lo que no cuadre
- [ ] T016 Control negativo del tramo A, anotando recuentos: (a) quitar la redacción de `title_placeholders` → cae el centinela de T004; (b) llamar a `ignore_flow` sin comprobar `unique_id` → cae el de `cannot_ignore` de T005; (c) emitir token sin leer la entrada / enviar el `update` en la vista previa → caen los de T007(d); (d) pedir token también al cambiar solo el título → cae T007(c); no pedirlo al desactivar el sondeo → cae T007(d); (e) atar el token sin `title` → cae T007(f); (f) devolver lista vacía si la respuesta no es lista → cae T004; (g) dejar `config_entries/update` en `deny` → cae el de la genérica de T010; quitar la consulta del mapa (si la hizo este tramo) → cae el del generador; (h) sacar `integration_setup` de la familia → cae T002; quitar `ha_update_config_entry` de `_DESTRUCTIVE_EXACT` → cae el invariante de registro. Restaurar y comprobar verde
- [ ] T017 Cierre del tramo A: suite completa (exactamente los 6 fallos conocidos en Windows), CI de la rama y banco en verde, revisión del diff buscando datos personales e identificadores de modelos (principio VIII, FR-026), commit en español con la línea base de T001 y los recuentos de T016 (SC-006, SC-007)

---

## Tramo B — subentries y reconfigure (US2, US3, US7)

Los tests de cada tool se escriben y se ven fallar antes de T023.

- [ ] T018 [P] [US3] Tests de `ha_list_config_subentries` en `tests/test_tools_config_subentries.py`: lee `config_entries/get_single` (tipos admitidos) y `config_entries/subentries/list`; forma de data-model; entrada inexistente → `not_found` sin pedir la lista; respuesta que no es lista → `unexpected_response`; título con un centinela → tapado; sobre y recorte (FR-005, FR-021, FR-022)
- [ ] T019 [P] [US3] Tests de `ha_start_subentry_flow`, `ha_continue_subentry_flow` y `ha_abort_subentry_flow`: cuerpo `{"handler": [entry_id, tipo]}` (y `subentry_id` si viene) a `/config/config_entries/subentries/flow`; tipo no admitido → `subentry_type_not_supported` con `supported` y sin POST; entrada o subentry inexistente → `not_found` sin POST; subentry de otro tipo → `invalid_argument`; tipo sin reconfigure con `subentry_id` → `reconfigure_not_supported`; resultado `external` o `progress` → `DELETE` del flujo y `non_automatable`; continue a `/config/config_entries/subentries/flow/<flow_id>` con `user_input`; `create_entry` → `status: "ok"` sin pisar campos de HA; abort → `DELETE` y `{"result": "ok"}`; `flow_id` con `/` o `..` → `invalid_argument` sin petición; `user_input` con un centinela → no aparece en el log capturado (FR-006, FR-007, FR-021)
- [ ] T020 [P] [US3] Tests de `ha_update_subentry`: lecturas previas de la entrada y de la lista; `not_found` de cada una sin `update`; mismo título → `unchanged` sin `update`; título vacío o de 256 → `invalid_argument`; camino feliz → un solo `config_entries/subentries/update` con `title`; sin token (FR-008)
- [ ] T021 [P] [US3] Tests de `ha_delete_subentry`: vista previa con la entrada, la subentry, las entidades (de `config/entity_registry/list` filtradas por entrada y subentry) y los dispositivos (las dos formas de research R-4), con `count` y recorte a 50 con `truncated`, el texto de efecto de data-model, token y NINGÚN `config_entries/subentries/delete`; subentry sin entidades ni dispositivos → listas vacías con `count: 0`; entrada o subentry inexistente → `not_found` sin token; lectura de registros que falla → `preview_unavailable` sin token; confirmación → un solo `delete` y `{"result": "ok"}`; token con otro `subentry_id` → rechazado; token reutilizado → rechazado; HA `not_found` al confirmar → `not_found` y token completado con fallo; centinela en el nombre de una entidad → tapado y ausente de `CONFIRMATIONS_DIR` (FR-009, FR-021, FR-022, SC-003, SC-004)
- [ ] T022 [P] [US2] Tests de `ha_start_reconfigure_flow`: lee la entrada; inexistente → `not_found`; `supports_reconfigure: false` → `reconfigure_not_supported` sin POST; camino feliz → `POST /config/config_entries/flow` con `{"handler": <dominio>, "entry_id": <entry_id>}` y respuesta con `continue_with`; `external` → `DELETE` y `non_automatable` (FR-010)
- [ ] T023 [US2] [US3] `hermes/src/hermes/tools/config_subentries.py` según research R-4 y data-model, reutilizando de `config_entry_flows.py` la validación de `flow_id`, `_NON_AUTOMATABLE_TYPES` y el abort best-effort (importados o movidos a un ayudante común sin cambiar su comportamiento ni sus tests); docstrings en inglés (qué borra HA con una subentry, que el reconfigure de la entrada se sigue con `ha_continue_config_entry_flow`). T018–T022 en verde (FR-005…FR-010)
- [ ] T024 [P] [US7] Familia, registro y anotaciones: `integration_flows` con `("integration_setup", "config_subentries")`; registro bajo la familia; `_NON_IDEMPOTENT_EXACT` con `ha_start_subentry_flow`, `ha_continue_subentry_flow` y `ha_start_reconfigure_flow` y su comentario. Tests en `tests/test_tool_families.py` y `tests/test_tools_registration.py`: módulos de la familia; hints y títulos de las siete según contracts/tools.md (`ha_delete_subentry` destructiva por prefijo; `ha_update_subentry` y `ha_abort_subentry_flow` no destructivas); con la familia desactivada no aparece ninguna de las 11; las de la 1.1.2 sin cambios (FR-017, FR-019, FR-024, SC-001)
- [ ] T025 [US7] Tabla: `config_entries/subentries/list`, `…/update` y `…/delete` a `dedicated` (data-model) en `command_table.py` y en `_DEDICADAS_INICIALES`; regenerar y comprobar que no cambia nada; test de la genérica con `config_entries/subentries/delete` → `use_dedicated_tool` con `ha_delete_subentry` (FR-018, SC-002)
- [ ] T026 [US3] Guía: completar el tema `integration_flows` (subentries: tipos, crear, reconfigurar, renombrar, borrar con token y qué se lleva; reconfigure de la entrada; flujos OAuth abortados e informados) y alias `subentries`, `subentry`, `reconfigure`; el test genérico de T011 cubre las 11 (FR-020)
- [ ] T027 [US2] [US3] Banco, parte B de `tests/banco/test_banco_integraciones.py`: sobre una entrada de `banco_flujos` creada por el lector, `ha_list_config_subentries` ve `elemento` entre los tipos; `ha_start_subentry_flow` → `ha_continue_subentry_flow` crea una subentry (el lector la ve y ve su sensor en el registro de entidades); con `subentry_id`, el mismo flujo la reconfigura (el lector ve el cambio); otro flujo abierto y `ha_abort_subentry_flow` (el lector no ve subentry nueva); `ha_update_subentry` cambia el título; `ha_delete_subentry` → la vista previa enumera el sensor y no borra nada (el lector lo comprueba) → con el token, el lector ya no ve ni la subentry ni el sensor; `ha_start_reconfigure_flow` → `ha_continue_config_entry_flow` cambia los datos de la entrada (el lector los ve); limpieza. Las cinco que modifican a `PROBADAS_016` (FR-023, SC-005)
- [ ] T028 Documentación parcial (CHANGELOG: las siete tools y las tres entradas; hoja de ruta → «en curso (tramo B)») y revisión del principio V de las siete tools y del tema, como T015 (FR-025)
- [ ] T029 Control negativo y cierre del tramo B, anotando recuentos: (a) abrir el flujo sin comprobar el tipo → cae el de `subentry_type_not_supported` sin POST; (b) no abortar un resultado `external` → cae el de `non_automatable`; (c) emitir token sin leer los registros / omitir los dispositivos → caen los de T021; borrar en la vista previa → cae el de «ningún delete»; (d) atar el token sin `subentry_id` → cae el de otro `subentry_id`; (e) enviar `subentries/update` sin comprobar la entrada → cae el de `not_found` de T020; (f) dejar `config_entries/subentries/delete` en `deny` → cae el de la genérica; quitar `ha_start_subentry_flow` de `_NON_IDEMPOTENT_EXACT` → cae el de hints. Restaurar; suite completa (los 6 conocidos), CI y banco en verde, revisión del diff (principio VIII, FR-026), commit con los recuentos (SC-006, SC-007)

---

## Tramo C — reparación y traducciones (US4, US5, US7)

- [ ] T030 [P] [US5] Tests en `tests/test_translations.py` del ayudante `_translations.py`: idioma de `get_config` (`language`; ausente → `en`); una sola llamada `frontend/get_translations` con `category: "issues"` y solo los dominios pedidos (sin duplicados); claves `component.<dominio>.issues.<clave>.title|description` y de `fix_flow.step.<paso>` y `fix_flow.abort.<motivo>`; sustitución de `{marcador}` con los valores ya redactados y marcadores desconocidos intactos; recorte de la descripción a 1000 con `description_truncated`; sin `translation_key` → sin texto; fallo de `get_config` o de `get_translations` (o `unknown_command`) → resultado vacío con `translations_unavailable: true`, sin lanzar; centinela en un marcador y en un texto traducido → tapado (FR-015, FR-021)
- [ ] T031 [US5] `hermes/src/hermes/tools/_translations.py` según research R-6: funciones puras para claves, sustitución y recorte, y una función asíncrona que lee idioma y textos en dos llamadas; comentario del porqué del fail-soft (principio III, fila de plan.md). T030 en verde (FR-015)
- [ ] T032 [P] [US5] [US7] Tests en `tests/test_tools_repairs.py`: `ha_list_repairs` conserva todos los campos y el orden de la 1.1.2 y añade `title`, `description` y `description_truncated` por aviso y `language`, `translations_unavailable` y `_third_party_text` en la raíz; una sola lectura de traducciones con los dominios de los avisos devueltos (no de los filtrados); traducción que falla → la misma lista con `title`/`description` nulos; marcador con un centinela → tapado en el texto; `ha_ignore_repair` sin token → la vista previa trae `title`; con token, sin lecturas de traducciones; el esquema de entrada de las dos tools es el de la 1.1.2 (FR-015, FR-022, FR-024)
- [ ] T033 [US5] `hermes/src/hermes/tools/repairs.py`: textos en `ha_list_repairs` y en la vista previa de `ha_ignore_repair` con el ayudante; docstrings y nota del módulo al día (los flujos de reparación y `get_issue_data` ya no están fuera de alcance: los cubre `repair_flows`); sin argumentos nuevos. T032 en verde (FR-015, FR-024)
- [ ] T034 [P] [US4] Tests de `ha_get_repair` en `tests/test_tools_repair_flows.py`: busca en `repairs/list_issues` (incluidos los ignorados) y lee `repairs/get_issue_data`; inexistente → `not_found` sin `get_issue_data`; resumen igual al de `ha_list_repairs` con texto entero; `issue_data` redactado por clave (`password`) y por patrón (JWT en un texto); `issue_data` mayor que el tope → `{"keys", "size_bytes"}` e `issue_data_truncated: true`, nunca JSON cortado; `unknown_issue` en `get_issue_data` → `not_found`; `_third_party_text` presente (FR-011, FR-015, FR-021, FR-022)
- [ ] T035 [P] [US4] Tests de `ha_start_repair_fix`: aviso inexistente → `not_found` y no reparable → `not_fixable`, los dos sin POST; camino feliz → `POST /repairs/issues/fix` con `{"handler": domain, "issue_id": …}` y respuesta con `issue`, `step_text` (`source: "fix_flow"`, o `"issue"` si no hay texto del paso) y `finished_on_start: false`; resultado `create_entry` al abrir → `finished_on_start: true` e `issue_still_present` leído de nuevo; `abort` al abrir → `finished_on_start: true`, `reason` y `reason_text`; `external`/`progress` → `DELETE` y `non_automatable` (FR-012, FR-015)
- [ ] T036 [P] [US4] Tests de `ha_continue_repair_fix`: (a) validación sin llamar: `flow_id` inválido, `user_input` que no es objeto; (b) vista previa: `GET /repairs/issues/fix/<flow_id>`, lectura del aviso, texto del paso, `user_input` redactado (centinela bajo `password`), efecto y nota de data-model, token y NINGÚN POST; flujo de otro dominio → `flow_mismatch` sin token; aviso inexistente o flujo inexistente (404) → `not_found` sin token; lectura que falla → `preview_unavailable`; (c) confirmación → un solo POST con `user_input`; `create_entry` → `status: "ok"` e `issue_still_present` (`false` si ya no está; `null` con `issue_check_error` si la relectura falla); `form` siguiente → su `step_text` y la indicación de nueva vista previa; HTTP 400 con `errors` → error redactado y token completado con fallo; (d) token con otro `flow_id`, otro `issue_id` u otro `user_input` → rechazado sin POST; reutilizado → rechazado; (e) ni la vista previa, ni el log capturado, ni los ficheros de `CONFIRMATIONS_DIR` contienen el centinela (FR-013, FR-015, FR-021, SC-003, SC-004)
- [ ] T037 [P] [US4] Tests de `ha_abort_repair_fix`: `DELETE /repairs/issues/fix/<flow_id>` y `{"result": "ok"}`; 404 → `not_found`; `flow_id` inválido → `invalid_argument` sin petición (FR-014)
- [ ] T038 [US4] `hermes/src/hermes/tools/repair_flows.py` según research R-5 y data-model, reutilizando la validación de `flow_id`, `_NON_AUTOMATABLE_TYPES`, el abort best-effort, el `_redactar` y la lectura de avisos de `repairs.py` (sin duplicarlos); docstrings en inglés (cada paso pide token y por qué; abrir puede terminar el flujo en algunas integraciones; la relación aviso–flujo). T034–T037 en verde (FR-011…FR-014)
- [ ] T039 [P] [US7] Familia, registro y anotaciones: `Familia("repair_flows", …)` con `("repair_flows",)`; registro bajo la familia; `ha_continue_repair_fix` en `_DESTRUCTIVE_EXACT` y `_NON_IDEMPOTENT_EXACT`; `ha_start_repair_fix` en `_NON_IDEMPOTENT_EXACT`, con sus comentarios. Tests en `tests/test_tool_families.py` y `tests/test_tools_registration.py`: familia y módulo; hints y títulos de las cuatro; con la familia desactivada no aparece ninguna y `ha_list_repairs` sigue (es de `diagnostics`); con todas las familias de la 1.2.0 desactivadas, las 216 de la 1.1.2 (FR-017, FR-019, FR-024, SC-001)
- [ ] T040 [US7] Tabla: `repairs/get_issue_data` a `dedicated` hacia `ha_get_repair` (familia `repair_flows`, `cap="CAP-048"`) en `command_table.py` y en `_DEDICADAS_INICIALES`; comentario encima de `frontend/get_translations` (Hermes lo usa por dentro para CAP-036; sigue `deny` para las genéricas); regenerar y comprobar que no cambia nada; test de la genérica con `repairs/get_issue_data` → `use_dedicated_tool` (FR-018, SC-002)
- [ ] T041 [US4] Guía: tema `repair_flows` (contracts/tools.md) con alias `repair_fix`, `fix` y la receta «arreglar un aviso de Repairs»; línea en `diagnostics` que remite a él y menciona los textos de `ha_list_repairs`. Tests: tema, alias, cada tool de la familia nombrada, índice (FR-020)
- [ ] T042 [US4] [US5] `tests/banco/test_banco_repairs.py`: el aviso reparable de `banco_flujos` sale en `ha_list_repairs` con `title` y `description` de `translations/en.json` y los marcadores sustituidos; `ha_get_repair` con `issue_data`; `ha_start_repair_fix` → `step_text` del paso; `ha_continue_repair_fix` sin token → el lector ve que el aviso sigue; con el token → el lector ya no ve el aviso e `issue_still_present: false`; sobre el segundo aviso, `ha_start_repair_fix` y `ha_abort_repair_fix` → el aviso sigue. Las tres que modifican a `PROBADAS_016` (FR-015, FR-023, SC-005)
- [ ] T043 Documentación final: CHANGELOG (sección de la 016 completa: 15 tools, 2 familias, 7 entradas de la tabla, textos traducidos en Repairs, guía de helpers, docstring corregida); hoja de ruta → «hecha» con lo probado en el banco y los pendientes manuales (quickstart.md); `README.md` y `README.es.md` sincronizados (tools nuevas en la lista por áreas y el recuento si lo llevan); `hermes/DOCS.md` si la opción `tool_families_disabled` enumera familias; `specs/008-cobertura-total/plan.md`: filas CAP-036, CAP-037, CAP-044, CAP-045 y CAP-048 de la matriz con las tools y los ficheros de test, sin cambiar las columnas que lee `_matriz_008` (sub-feature y vía) (FR-025)
- [ ] T044 Revisión del principio V de las tools del tramo y del tema (como T015) y control negativo del tramo C, anotando recuentos: (a) no redactar los marcadores antes de sustituir → cae el centinela de T030; lanzar si falla `get_translations` → cae el fail-soft de T030/T032; (b) quitar un campo de la 1.1.2 en `ha_list_repairs` → cae T032; (c) abrir el flujo sin comprobar `is_fixable` → cae T035; (d) hacer el POST en la vista previa → cae el de «ningún POST» de T036; no comprobar el dominio del flujo → cae `flow_mismatch`; atar el token sin `user_input` → cae T036(d); (e) guardar `user_input` sin redactar en la vista previa → cae T036(e); (f) devolver `issue_data` sin mirar el tope → cae T034; (g) dejar `repairs/get_issue_data` en `deny` → cae el de la genérica; quitar `ha_continue_repair_fix` de `_DESTRUCTIVE_EXACT` → cae el invariante de registro. Restaurar y comprobar verde
- [ ] T045 Cierre del tramo C: suite completa (los 6 fallos conocidos y ninguno más), CI de la rama y banco en verde, revisión del diff (principio VIII, FR-026), commit con los recuentos de T044 (SC-006, SC-007)

---

## Dependencias

- T001 antes que todo (y la 011 integrada). T002→T003; T004–T007 (en
  paralelo) → T008; T008→T009→T010→T011; T012→T013 (tras T009 y la 010);
  T014–T017 al final del tramo.
- Tramo B tras el A integrado: T018–T022 en paralelo → T023 → T024 → T025,
  T026; T027 tras T024; T028, T029 al final.
- Tramo C tras el A integrado (no necesita el B): T030→T031; T032→T033 (tras
  T031); T034–T037 en paralelo → T038 (tras T031 y T033); T039 tras T038;
  T040, T041 tras T039; T042 tras T039; T043–T045 al final.

## Paralelismo

- Tramo A: T002 y T004–T007 a la vez (T004–T007 escriben clases separadas en
  `test_tools_integration_setup.py`).
- Tramo B: T018–T022 a la vez (clases separadas en
  `test_tools_config_subentries.py`).
- Tramo C: T030, T032 y T034–T037 a la vez (ficheros o clases separados).

## Estrategia

MVP = tramo A: el agente ya ve y atiende lo descubierto, ajusta el título y las
preferencias de una integración y sabe crear helpers por config entry. El B
añade subentries y reconfigure (lo que más piden las integraciones nuevas de
HA). El C añade los arreglos de Repairs y el texto de los avisos.

## Notas del tramo

(Las rellena cada agente al cerrar su tramo: desviaciones, hallazgos en el
banco, decisiones.)
