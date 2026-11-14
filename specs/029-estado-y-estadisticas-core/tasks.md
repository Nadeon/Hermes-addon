---
description: "Tareas de la sub-feature 029 — estado del sistema y estadísticas de Core (Hermes 1.2.0)"
---

# Tareas: estado del sistema y estadísticas de Core (029)

**Entrada**: `specs/029-estado-y-estadisticas-core/` (spec.md, plan.md,
research.md, data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `DummyMCP` o
`_RecordingMCP`, `AsyncMock` de `ws_send`, `ws_one_shot_subscription` y
`ws_collect_subscription`, `structlog.testing.capture_logs`. Datos ficticios
(`light.salon`, `sensor.consumo`, `192.0.2.10`,
`homeassistant.tailXXXX.ts.net`, `centinela-029`, un JWT de prueba). Nada de
la instalación real ni de las tools MCP de Hermes.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" python -m pytest -q -p no:cacheprovider`.
Línea base en Windows al especificar (2026-11-14, punta `ab5098d`: la 011
hasta T037, sin la 009 ni la 010): 2126 passed, 17 skipped, 6 failed (los 6
conocidos). T001 la vuelve a tomar tras integrar las dependencias. Cada tramo
termina con exactamente esos 6 fallos en local; la referencia es el CI de
Linux.

**La implementación espera a la 011 completa** (y a la 009 y la 010 en la
base): ver plan.md, «Dependencias y momento de la implementación».

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 salud y estado, US2 arranque y manifiestos, US3
estadísticas y recorder, US4 auditoría, red y HTTP por la tabla, US5 nada se
rompe.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado (uno o varios commits; el tramo no se cierra con la suite en rojo).

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **1** — CAP-043, cliente y mecanismo de la tabla | **T001–T019** | `HAClient.ws_collect_subscription`; familia `system_status`; `ha_get_system_health`, `ha_get_system_state`, `ha_list_integration_setup_times`, `ha_list_integration_manifests`, `ha_get_integration_manifest` registradas, anotadas y probadas; cinco entradas de CAP-043 en `dedicated` con el generador al día; tema `system_status`; banco de las cinco; recuentos de README y DOCS, CHANGELOG y hoja de ruta parciales |
| **2** — CAP-049, CAP-058, CAP-068 y cierre | **T020–T035** | Familia `recorder`; `ha_validate_statistics`, `ha_get_statistics_metadata`, `ha_get_recorder_info`; cuatro entradas de CAP-049 en `dedicated`; `logbook/get_action_calls` con `code` tapado y ejemplo; tests de log de red y HTTP; temas completos; banco del resto; documentación final y matriz de la 008 |

El tramo 2 necesita el 1 integrado.

---

## Tramo 1 — CAP-043, cliente y mecanismo de la tabla (US1, US2, US5)

### Preparación

- [X] T001 Comprobar la base: la rama contiene la 009 (`version: "1.2.0"` en `hermes/config.yaml` y `## [1.2.0]` en `hermes/CHANGELOG.md`), la 010 (`tests/banco/base_helpers.py`) y la 011 entera (`scripts/inventario/extraer.py`, T043 cerrada); si falta algo, parar y avisar (no se implementa sobre una base incompleta). Anotar si la 012 está integrada (decide T002–T003). Línea base de la suite, anotada en el commit del tramo
  - **Hecho** (2026-11-14, tras `git merge --no-ff feat/cobertura-total`): la base tiene la 009 (`version: "1.2.0"`, `## [1.2.0]`), la 010 (`tests/banco/base_helpers.py`), la 011 entera (extractor, T043 cerrada) y la 028. La 012 NO está integrada: T002–T003 los hace la 029. Línea base en Windows: 2320 passed, 65 skipped, 6 failed (los 6 conocidos).

### Mecanismo de la tabla (solo si la 012 no lo integró; research R-7)

- [X] T002 [US5] Tests primero: en `tests/test_generar_tabla.py`, una fila A de vía D cuya clave está en `_DEDICADAS_INICIALES` sale `dedicated` con la familia de su tool en la primera generación; en `tests/test_command_table.py`, `test_clase_a_de_via_dedicada_pendiente_de_su_spec` admite `dedicated` con una tool de una familia `desde="1.2.0"` y sigue fallando con `read`/`confirm`. Si la 012 ya lo hizo, marcar la tarea como hecha por la 012 (FR-016)
- [X] T003 [US5] `scripts/inventario/generar_tabla.py`: `_clasificar` consulta `_DEDICADAS_INICIALES` para la clase A antes de la regla «pendiente de tool dedicada», con el diseño de la 012. T002 en verde (FR-016)
  - Hecho por la 029 (la 012 no estaba integrada), con el diseño de su research R-7: `_clasificar` consulta `_DEDICADAS_INICIALES` en la rama de la clase A antes de la regla «pendiente». La que se integre segunda conserva las claves de las dos (D-3). Control negativo: T002 en rojo antes de este cambio.

### Cliente: suscripción de varios mensajes

- [X] T004 [P] [US1] Tests en `tests/test_ha_ws_collect_subscription.py` con una WebSocket simulada (como los de `ws_one_shot_subscription`): (a) `result` + tres eventos con el último que cumple `terminado` → los tres en orden y `completo=True`; (b) eventos que nunca terminan → vuelve en el plazo TOTAL (no por evento: eventos cada 0,3 s con plazo 1 s no lo alargan) con lo recibido y `completo=False`; (c) `result` de error de HA → `HAConnectionError` con `code`; (d) WebSocket cerrada antes → `HAConnectionError` sin código; (e) en (a), (b), (c) y con la tarea cancelada, se manda `unsubscribe_events` del id y no queda nada registrado en el cliente; (f) `ws_one_shot_subscription` sigue con sus tests sin cambios (FR-002, SC-005)
- [X] T005 [US1] `hermes/src/hermes/ha.py`: `HAClient.ws_collect_subscription(payload, *, terminado, timeout_seconds)` según data-model, con comentarios del porqué (plazo total, cancelar siempre). T004 en verde (FR-002)

### Tests de las tools (antes del código)

- [X] T006 [P] [US1] Tests en `tests/test_tools_system_status.py`, `ha_get_system_health` con `ws_collect_subscription` simulado: inicial + `update` + `finish` → `complete: true`, fecha `{"type": "date"}` como texto ISO, `manage_url` conservado; pendiente sin actualización al vencer → `null`, en `pending` como `<dominio>.<clave>` y `complete: false`; `update` con `success: false` → en `failed`; `update` de un dominio desconocido → ignorado; `domain="cloud"` → solo ese; dominio que no está → `domain_not_found` con los disponibles; `timeout_seconds` 0,5 o 31 y `domain` inválido → `invalid_argument` sin llamar a HA; valor con `token=centinela-029` y JWT → tapados; `HAConnectionError(code="unknown_command")` → `system_health_not_loaded` (no `unsupported_by_ha_version`); respuesta mayor que el tope → dominios quitados por el final en `omitted_domains`, `truncated: true` y dentro del tope; un solo dominio que no cabe → `response_too_large`; Core caído → error de siempre; log capturado: `ha_get_system_health_ok` con recuentos y sin ningún valor, URL (`https://homeassistant.tailXXXX.ts.net`) ni IP (`192.0.2.10`) de la respuesta; se pasa el `timeout_seconds` pedido al cliente (FR-001, FR-018, FR-019, SC-004, SC-006)
- [X] T007 [P] [US1] Tests en `tests/test_tools_system_status.py`, `ha_get_system_state` con `ws_one_shot_subscription` simulado: devuelve los cinco campos de HA; `HAConnectionError(code="unknown_command")` → `unsupported_by_ha_version` con `ha_code` y la versión de la tabla; otro error de HA → redactado; Core caído → error de siempre (FR-003, FR-020)
- [X] T008 [P] [US2] Tests en `tests/test_tools_system_status.py`: `ha_list_integration_setup_times` ordena de más lenta a más rápida, `limit`, `min_seconds`, `total` y `total_seconds` sobre todas, `seconds` redondeado, `limit` 0 o 501 → `invalid_argument`, `unknown_command` → `unsupported_by_ha_version` (en las tres de este grupo); `ha_list_integration_manifests`: resumen de los diez campos (ausentes → `null`), orden por dominio, `custom_only`, `missing` con las pedidas que no vuelven, más de 100 nombres o uno inválido → `invalid_argument` sin llamar a HA, `_third_party_text` solo en las que no son de HA, recorte al tope con `truncated`; `ha_get_integration_manifest`: manifiesto completo, `not_found` de HA → `integration_not_found`, `_third_party_text` en una personalizada, un centinela en un campo sensible del manifiesto → tapado, nombre inválido → `invalid_argument`; log de las tres sin valores (FR-004…FR-007, FR-018, FR-019)
- [X] T009 [P] [US5] Tests en `tests/test_tool_families.py`: `system_status` existe, `desde="1.2.0"`, desactivable, con el módulo `system_status` y su descripción (FR-015)
- [X] T010 [P] [US5] Tests en `tests/test_tools_registration.py`: las cinco en `_HINTS_NUEVAS_1_2_0` con `R-I-` y su título; ninguna toma `confirmation_token`; con `system_status` desactivada no se registra ninguna y el resto no cambia (FR-015, FR-017, SC-001)

### Implementación

- [X] T011 [US1] [US2] `hermes/src/hermes/tools/system_status.py` con las cinco tools de contracts/tools.md: `register(mcp, ha_client, *, response_max_bytes)`, `@ready`, descripciones en inglés que dicen lo que hacen y lo que no, validación antes de llamar, redacción (`redact_structure` + `redact_secrets`), sobre común con `ajustar_lista_a_bytes`, recorte de la salud por dominios, `_third_party_text` como en `tools/marketplace.py`, log con recuentos. T006–T008 en verde (FR-001, FR-003…FR-007, FR-018…FR-020)
  - Desviación: las tools devuelven el objeto (`-> object`), como el resto de módulos (`marketplace.py`, `generic_commands.py`), no un `str` con `json.dumps`; el servidor serializa. Aviso 2 del supervisor: una salud realista de HA OS (diez dominios) mide unos 2,3 KB, menos de la mitad del tope MÍNIMO de `response_max_bytes` (10 KiB); el filtro `domain` (opcional) ya estaba en el contrato y se mantiene (`test_respuesta_tipica_cabe_en_el_tope_minimo`).
- [X] T012 [US5] `hermes/src/hermes/tool_families.py` (familia `system_status`) y `hermes/src/hermes/tools/__init__.py` (registro dentro de `if _activa("system_status")`). Las anotaciones salen de los prefijos (comprobarlo). T009 y T010 en verde (FR-015, FR-017)

### Tabla

- [X] T013 [P] [US5] Tests en `tests/test_tools_generic_commands.py`: `ha_read_ws_command` con cada uno de los cinco comandos de CAP-043 → `use_dedicated_tool` con su tool y sin `ws_send`; con `system_status` desactivada → `family_disabled: true` (FR-016)
- [X] T014 [US5] `hermes/src/hermes/command_table.py`: `system_health/info`, `subscribe_system_state`, `integration/setup_info`, `manifest/list` y `manifest/get` a `E("dedicated", "cubierto por <tool>", "system_status", tool=…, cap="CAP-043")` (data-model); las cinco claves en `_DEDICADAS_INICIALES` de `scripts/inventario/generar_tabla.py` (bloque comentado «029»); ejecutar el generador y comprobar que `git diff -- hermes/src/hermes/command_table.py` no cambia nada respecto a la edición a mano; anotarlo en el commit. T013 y `tests/test_command_table.py` en verde (FR-016)
  - Regeneración: `generar_tabla.py` sobre la tabla editada a mano → 0 nuevas, 0 quitadas, fichero idéntico byte a byte; generada desde cero en un temporal, las cinco entradas salen idénticas a las editadas. Test nuevo `test_dedicadas_de_la_029` en `tests/test_command_table.py` (forma exacta, clave en el mapa y solo los cuatro de CAP-049 «pendiente (spec 029)»).

### Guía

- [X] T015 [US1] [US2] Tests en `tests/test_tools_guide.py` (tema `system_status` con contenido, nombra las cinco tools y su alias `health`, `system_health`, `system_state`, `manifest`, `manifests`, `setup_times`, `urls` resuelven a él; el índice lo menciona; los temas de la 1.1.2 no cambian) y después el tema en `hermes/src/hermes/tools/guide.py` (en español, como los demás; dice que nada de esto modifica, cómo se lee la salud con pendientes y que para reiniciar está `sv_restart_core`) (FR-021)

### Banco de Core

- [X] T016 [US1] [US2] `tests/banco/ha_config/configuration.yaml`: `system_health:` y `network:` con comentario del porqué; `tests/banco/test_banco_estado_sistema.py` (marcador `banco`, helpers de la 010): salud con el dominio `homeassistant` y `version` 2026.11.1 y ninguna suscripción abierta tras responder (una segunda llamada responde igual); estado sin reinicio pendiente; tiempos con al menos `http`; `ha_list_integration_manifests(integrations=["input_boolean", "no_existe"])` con `input_boolean` de HA y `no_existe` en `missing`; `ha_get_integration_manifest("input_boolean")` con `is_built_in: true`; rechazo de `ha_read_ws_command("system_health/info")`. Si algo no arranca en el banco, anotarlo con el motivo en el test y en el commit (FR-022)
  - `Sesion` del banco (`tests/banco/base_helpers.py`) expone además `ha_client` (aditivo) para comprobar que la recogida no deja la suscripción registrada en el cliente. Pendiente de ver en el CI con HA real.
- [X] T017 [US5] `tests/banco/cobertura.py`: `PROBADAS_EN_BANCO_029` con las cinco; en `tests/test_banco_cobertura.py`, clase nueva: el conjunto es exactamente lo que registran los módulos de las familias de la 029 (`system_status` ahora; `recorder_status` en el tramo 2) y cada nombre aparece en algún `tests/banco/test_banco_*.py` (FR-022)
  - Además de la clase de cobertura, `PROBADAS_EN_BANCO_029` se suma a `TOOLS_EXIGIDAS_DEL_JOB` (`cobertura_escrituras.py`): el job las exige por EJECUCIÓN, no solo por nombre (tests de la 011 y la 028 que fijan esa unión, actualizados).

### Cierre del tramo 1

- [X] T018 Control negativo del tramo 1, anotando recuentos: (a) en `ws_collect_subscription`, plazo por evento en vez de total → cae (b) de T004; quitar el `unsubscribe` del `finally` → caen los de (e); (b) en `ha_get_system_health`, no mover lo pendiente a `pending` (dejar `{"type": "pending"}`) → caen los de pendientes; no redactar → cae el centinela; registrar la URL en el log → cae el de log; (c) no recortar por dominios → cae el del tope; (d) `_third_party_text` en todas → cae; (e) dejar `manifest/get` en `deny` → cae T013 y el de dedicadas; (f) quitar una tool de `PROBADAS_EN_BANCO_029` → cae T017. Restaurar y comprobar verde
  - Recuentos: (a) plazo por evento → 1 cae; sin `unsubscribe` en el `finally` → 5 caen; (b) pendientes sin mover → 4 caen; sin redactar → 1; respuesta en el log → 1; (c) sin recorte por dominios → 2; (d) `_third_party_text` en todas → 3; (e) `manifest/get` en `deny` → 2 de T013 + `test_dedicadas_de_la_029`; (f) sin `ha_get_system_state` en `PROBADAS_EN_BANCO_029` → 1. Todo restaurado y en verde.
- [X] T019 Documentación parcial y cierre: recuento de tools (+5) y fila de la familia en `README.md`, `README.es.md` y `hermes/DOCS.md` (`TestToolCountInDocs`); sección «Estado del sistema y estadísticas» en `## [1.2.0]` de `hermes/CHANGELOG.md` con lo del tramo; 029 «en curso» en `docs/HOJA-DE-RUTA.md`; suite completa (los 6 fallos conocidos y ninguno más); revisión del diff buscando datos personales e identificadores de modelos (principio VIII); commit en español con la línea base de T001, el resultado de T014 y los recuentos de T018 (FR-023)
  - Suite: 2383 passed, 70 skipped, 6 failed (los 6 conocidos). La matriz de la 008 se completa en T033 (tramo 2). Aviso 1 del supervisor: `logbook/get_action_calls` ya lleva `redact_extra=("code",)` y su centinela desde la 011; esa parte de T026–T027 queda hecha por la 011.

---

## Tramo 2 — CAP-049, CAP-058, CAP-068 y cierre (US3, US4, US5)

### Tests de las tools (antes del código)

- [X] T020 [P] [US5] Tests en `tests/test_tool_families.py` (familia `recorder`, `desde="1.2.0"`, desactivable, módulo `recorder_status`) y en `tests/test_tools_registration.py` (las tres en `_HINTS_NUEVAS_1_2_0` con `R-I-`; `ha_validate_statistics` de solo lectura por nombre exacto; con `system_status` y `recorder` desactivadas el conjunto es exactamente el de antes de la 029) (FR-015, FR-017, SC-001)
  - Línea base del tramo 2 (Windows, punta `13fccb8`): 2383 passed, 70 skipped, 6 failed (los 6 conocidos). `test_sin_las_dos_familias_es_la_lista_de_antes_de_la_029` compara con el registro completo menos las ocho.
- [X] T021 [P] [US3] Tests en `tests/test_tools_recorder_status.py`: `ha_validate_statistics` aplana `{id: [{type, data}]}` en items ordenados, `by_type` antes de filtrar, filtros `statistic_id` e `issue_type`, recorte con `truncated`, argumentos inválidos → `invalid_argument` sin llamar a HA, `unknown_command` → `recorder_not_loaded`; `ha_get_statistics_metadata` pide los ids sin repetir, devuelve `missing`, 0 o 101 ids o uno sin forma → `invalid_argument`, `unknown_command` → `recorder_not_loaded`; log de las dos sin ids ni valores (FR-008, FR-009, FR-011, FR-018, FR-019)
- [X] T022 [P] [US3] Tests en `tests/test_tools_recorder_status.py`, `ha_get_recorder_info`: los siete campos de `recorder/info`; con `entity_id` de una entidad que existe, `entity` con `recorded` y `recording_disabled_by` (`null` → `recorded: true`; `"user"` → `false`); entidad que no existe → `not_found` sin llamar a `recorder/entity_options/get`; `entity_id` inválido → `invalid_argument`; `unknown_command` en `recorder/info` → `recorder_not_loaded`; en `entity_options/get` → la información sale y `entity` lleva `unsupported_by_ha_version`; Core caído → error de siempre; log sin el `entity_id` (FR-010, FR-011, FR-019, FR-020)
  - Desviación de orden (TDD): el módulo T024 se escribió justo antes que estos tests; el rojo se comprobó con los controles negativos de T034 (c, d).
- [X] T023 [P] [US3] Tests en `tests/test_tools_generic_commands.py`: `ha_read_ws_command` con cada uno de los cuatro comandos de CAP-049 → `use_dedicated_tool` con su tool y sin `ws_send`; con `recorder` desactivada → `family_disabled: true` (FR-016)

### Implementación

- [X] T024 [US3] `hermes/src/hermes/tools/recorder_status.py` con las tres tools de contracts/tools.md (mismo patrón que `system_status.py`; `entity_exists` de `tools/_common.py`). T021 y T022 en verde (FR-008…FR-011, FR-018…FR-020)
- [X] T025 [US5] `tool_families.py` (familia `recorder`), `tools/__init__.py` (registro bajo `if _activa("recorder")`) y `tools/_annotations.py` (`ha_validate_statistics` en `_READ_ONLY_EXACT` con el porqué: valida, no corrige). T020 en verde (FR-015, FR-017)
  - La familia `recorder` es la del recorder entero, no solo de estas lecturas: la 020 (CAP-050) le añadirá el mantenimiento de estadísticas; ese día su descripción deja de decir «read only» y sus tools escritas entran en el banco por el invariante de `MODULOS_029`. Comentado en `tool_families.py`, `recorder_status.py`, `tests/banco/cobertura.py`, DOCS y README.

### Tabla y CAP-058, CAP-068

- [X] T026 [P] [US4] Tests en `tests/test_tools_generic_commands.py` con la tabla real: `ha_read_ws_command("logbook/get_action_calls", {...})` con una respuesta que lleva `service_data: {"code": "centinela-029"}` y `{"code": 4321}` → los dos tapados en la respuesta y ausentes del log, el resto de la llamada visible; `network`, `network/url` y `http/config` con respuestas que llevan `http://192.0.2.10:8123`, `https://homeassistant.tailXXXX.ts.net` y direcciones `192.0.2.x` → la respuesta las devuelve y el log capturado no contiene ninguna (FR-012, FR-013, SC-004, SC-006)
  - El tapado del `code` en la respuesta ya lo hizo la 011 (`redact_extra` y `test_action_calls_tapa_el_code`, aviso 1 del supervisor en T019); aquí solo se añade lo que faltaba: el log sin el `code`, el ejemplo y la red y el HTTP.
- [X] T027 [US4] [US5] `hermes/src/hermes/command_table.py`: las cuatro de CAP-049 a `dedicated` (data-model) y sus claves en `_DEDICADAS_INICIALES`; `logbook/get_action_calls` con `redact_extra=("code",)`, el `example` de data-model (revisado contra `logbook/websocket_api.py`) y el motivo nuevo; regenerar y comprobar que no cambia nada; ninguna entrada con «(spec 029)» (test nuevo en `tests/test_command_table.py`). T023 y T026 en verde (FR-012, FR-016, SC-002)
  - `redact_extra` y el motivo ya los dejó la 011 (su motivo ya dice lo que se tapa; no se cambia). Aquí: las cuatro de CAP-049 a `dedicated`, sus claves en `_DEDICADAS_INICIALES` y el `example` de `logbook/get_action_calls` (revisado contra `logbook/websocket_api.py`: `start_time` obligatorio, `end_time` opcional, texto ISO). Regenerar sobre la tabla editada: 0 nuevas, 0 quitadas, idéntica byte a byte; generada desde cero, las cuatro entradas salen iguales. `test_dedicadas_de_la_029` comprueba que no queda «(spec 029)» en ninguna de las dos tablas.

### Guía

- [X] T028 [P] [US3] [US4] Tests en `tests/test_tools_guide.py`: tema `recorder` con las tres tools y la auditoría (`logbook/get_action_calls` con `ha_read_ws_command`), alias `recorder_info`, `statistics_validation`, `action_calls`, `audit`; el índice lo menciona; `system_status` explica `network`, `network/url` y `http/config` y que Hermes aún no tiene tool para cambiarlos (la añade la 021, CAP-069, que actualizará ese texto); `hermes_guide(topic="generic_commands", search="action_calls")` muestra el ejemplo de la tabla; el alias `statistics` sigue en `data` (FR-014, FR-021)
- [X] T029 [US3] [US4] `hermes/src/hermes/tools/guide.py`: tema `recorder`, sección de red y HTTP en `system_status`, alias e índice. T028 en verde (FR-014, FR-021)
  - Además, la lista de temas del docstring de `hermes_guide` nombra `system_status` y `recorder` (el tramo 1 no la había tocado); y el alias `network` lleva a `system_status`.

### Banco de Core

- [X] T030 [US3] [US4] `tests/banco/ha_config/configuration.yaml`: `recorder:` y `logbook:` con comentario; `tests/banco/test_banco_recorder.py`: `ha_get_recorder_info` con `recording: true`; con el `entity_id` de un `input_boolean` creado por el lector, `recorded: true`; `ha_validate_statistics` responde con el sobre (quizá vacío); `ha_get_statistics_metadata(["sensor.no_existe"])` con el id en `missing`; tras `input_boolean.turn_on` por `ha_call_service`, `ha_read_ws_command("logbook/get_action_calls", …)` incluye esa llamada (si el banco no la graba, anotarlo); `network`, `network/url` y `http/config` responden por la genérica (FR-012, FR-013, FR-022)
  - `recorder:` y `logbook:` en el banco. Con el recorder cargado, `kitchen_sink` importa sus estadísticas de demostración: la de metadatos usa la primera que lista el lector. La auditoría usa `ha_call_service` y espera hasta 30 s (el recorder confirma cada 5 s). Pendiente de ver en el CI con HA real (T035).
- [X] T031 [US5] `PROBADAS_EN_BANCO_029` con las ocho y la clase de T017 con los dos módulos (FR-022, SC-003)

### Documentación y cierre

- [X] T032 Documentación final (FR-023): sección «Estado del sistema y estadísticas» completa en `## [1.2.0]` de `hermes/CHANGELOG.md` (ocho tools, dos familias, auditoría con `code` tapado, red y HTTP por la genérica); `hermes/DOCS.md` (las dos familias en la lista de `tool_families_disabled` y recuento); `README.md` y `README.es.md` sincronizados (+3 y filas de la familia); 029 «hecha» en la tabla del programa de `docs/HOJA-DE-RUTA.md`, y en la matriz de entornos de la 014 (si existe) las pruebas que solo se pueden hacer en vivo (salud con nube y Supervisor, reinicio pendiente, estadísticas con problemas)
  - Desviación: la matriz de entornos de la 014 no está en esta rama (la 014 se integró en `feat/cobertura-total` después de traerla en el tramo 1, y el encargo dice no volver a traerla). Las pruebas que solo se pueden hacer en vivo quedan nombradas en la fila de la 029 de la hoja de ruta y en quickstart.md; hay que pasarlas a la matriz al integrar.
- [X] T033 Matriz de trazabilidad de `specs/008-cobertura-total/plan.md`: filas CAP-043, CAP-049, CAP-058 y CAP-068 con las tools y entradas definitivas y los ficheros de test (`test_tools_system_status.py`, `test_tools_recorder_status.py`, `test_tools_generic_commands.py`, `tests/banco/test_banco_estado_sistema.py`, `tests/banco/test_banco_recorder.py`) (FR-023)
- [X] T034 Control negativo del tramo 2, anotando recuentos: (a) quitar `redact_extra` de `logbook/get_action_calls` → cae el centinela de T026; (b) registrar la respuesta de `network/url` en el log → cae; (c) no comprobar que la entidad existe → cae el de `not_found`; (d) no calcular `missing` → caen los de metadatos; (e) quitar `ha_validate_statistics` de `_READ_ONLY_EXACT` → cae el de hints; (f) dejar `recorder/info` en `deny` → caen T023 y el de «(spec 029)»; (g) quitar una tool de `PROBADAS_EN_BANCO_029` → cae T031. Restaurar y comprobar verde
  - Recuentos: (a) sin `redact_extra` → 3 caen (`test_action_calls_tapa_el_code`, `…_sin_code_en_el_log`, `…_tiene_ejemplo`); (b) respuesta en el log de la genérica → 3 subtests de `test_red_y_http_sin_urls_ni_ips_en_el_log`; (c) sin comprobar la entidad → 2 (`test_entidad_que_no_existe`, `test_log_sin_entity_id`); (d) sin `missing` → 4 de `TestMetadatos`; (e) sin `_READ_ONLY_EXACT` → 1 (`test_hints_y_titulos_de_las_nuevas`); (f) `recorder/info` en `deny` → `test_dedicadas_de_la_029` y 2 de `TestDedicadasDeLa029Recorder`; (g) sin `ha_get_recorder_info` en `PROBADAS_EN_BANCO_029` → 1 (`test_inventario_exacto`). Todo restaurado (diff idéntico) y en verde.
- [X] T035 Cierre del tramo 2: suite completa (los 6 fallos conocidos y ninguno más), CI en verde con el banco, revisión del diff (principio VIII), commit con los recuentos de T034 y el resultado de la regeneración de T027
  - Suite local: 2425 passed, 76 skipped, 6 failed (los 6 conocidos). CI de la rama en verde (run 43645907557): pytest 3.12 y 3.13 y banco de Core (57 passed, 3 xfailed; 51 antes del tramo: los 6 de `test_banco_recorder.py` pasan contra HA real y el job exige las ocho por ejecución). Diff revisado (principio VIII).

---

## Dependencias

- Tramo 1: T001 → resto. T002 → T003 (solo si la 012 no está). T004 → T005. T006…T010 en paralelo (T006 necesita la firma de T005); T011 tras T005…T008; T012 tras T009…T011. T013 → T014 (tras T012 y T003). T015 tras T011. T016 y T017 tras T014. T018, T019 al final.
- Tramo 2 (tras el tramo 1): T020…T023 en paralelo; T024 tras T021 y T022; T025 tras T020 y T024; T026 en paralelo con T020; T027 tras T023, T025 y T026; T028 → T029 (tras T027); T030 y T031 tras T027; T032, T033 tras todo; T034, T035 al final.

## Paralelo

- Tramo 1: T004, T006, T007, T008, T009, T010 (ficheros distintos o clases distintas del mismo fichero escritas en orden).
- Tramo 2: T020, T021, T022, T023, T026.

## Estrategia

MVP = tramo 1 (US1 y US2: la salud y el estado del sistema, lo de prioridad
alta). El tramo 2 añade las estadísticas (US3) y cierra lo que va por la tabla
(US4). US5 se comprueba en los dos.
