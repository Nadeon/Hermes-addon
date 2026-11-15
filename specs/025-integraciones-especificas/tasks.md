---
description: "Tareas de la sub-feature 025 — integraciones específicas por la tabla (Hermes 1.2.0)"
---

# Tareas: integraciones específicas por la tabla (025)

**Entrada**: `specs/025-integraciones-especificas/` (spec.md, plan.md,
research.md con la clasificación R-1, data-model.md, contracts/tools.md,
quickstart.md) y la paraguas `specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest`, `IsolatedAsyncioTestCase`, el `DummyMCP` y los
`AsyncMock` de `ws_send` y `ws_one_shot_subscription` de
`tests/test_tools_generic_commands.py`, `structlog.testing.capture_logs`.
Datos ficticios (`00:11:22:33:44:55:66:77`, `<device_id>`, `<entry_id>`,
`centinela-025`, `192.0.2.10`). Nada de la instalación real ni de las tools
MCP de Hermes.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" python -m pytest -q -p no:cacheprovider`.
Línea base en Windows al especificar (2026-11-15, `806a764`): 3835 passed,
126 skipped, 6 failed (los 6 conocidos). Cada tramo termina con exactamente
esos 6 fallos en local; la referencia es el CI de Linux.

**Fuente de la clasificación**: research.md R-1. El `reason` de cada entrada
es el texto de la columna «Motivo» tal cual; las marcas, las de la columna
«Marcas». No se reclasifica nada sin volver a leer el handler y actualizar
R-1 en el mismo commit.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 Z-Wave, US2 ZHA, US3 Matter y Thread, US4 el resto,
US5 guía, US6 tabla cerrada y generador.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado (uno o varios commits; el tramo no se cierra con la suite en rojo).

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **1** — mecanismo y Z-Wave JS | **T001–T017** | `redact_extra` de valor entero; `scripts/inventario/clase_c.py` y la rama de la clase C del generador; `test_command_table_clase_c.py` y `test_tools_generic_commands_clase_c.py`; las 55 `zwave_js/*` clasificadas; excepciones de verbos y mundo abierto; tema `zwave`; CHANGELOG y hoja de ruta parciales |
| **2** — ZHA, Matter, Thread y OTBR | **T018–T029** | Las 50 entradas clasificadas con los centinelas de claves de red; temas `zigbee` y `matter_thread`; CHANGELOG y hoja de ruta parciales |
| **3** — resto y cierre | **T030–T046** | Las 87 restantes; test estricto de «ninguna pendiente»; «sin revisar» en el generador y desde cero en las 192; tema `other_integrations`; banco; SECURITY, CHANGELOG, hoja de ruta y matriz de la 008 |

El tramo 2 necesita el 1 integrado; el 3, el 2.

---

## Tramo 1 — mecanismo y Z-Wave JS (US1, US5, US6)

### Preparación

- [x] T001 Comprobar que la rama sale de `feat/cobertura-total` con la 011
  entera (`806a764` o posterior) y tomar la línea base de la suite; si hay
  fallos distintos de los 6 conocidos, anotarlos antes de tocar nada.

### Redacción de valor entero (FR-008)

- [x] T002 [US2] Tests en `tests/test_tools_generic_commands_clase_c.py`,
  clase `TestRedaccionValorEntero` (con una tabla inyectada con
  `redact_extra=("k",)`): un objeto y una lista bajo `k` salen
  `***REDACTED***` enteros (ninguna clave interior en la respuesta); texto
  y número, tapados como hoy; cadena vacía y `None`, tal cual; una clave que
  no está en `redact_extra` se recorre como hoy;
  `logbook/get_action_calls` con su `code` sigue igual. Verlos en rojo.
- [x] T003 [US2] En `hermes/src/hermes/tools/generic_commands.py`,
  `_redactar`: si `clave.lower()` está en `extra` y el valor es un `Mapping`
  o una lista, devolver `REDACTED_MARKER` antes de recorrerlo; comentario del
  porqué (H-1 de research.md). Actualizar el comentario del campo
  `redact_extra` de `Entrada` en `command_policy.py`. T002 en verde. Control
  negativo: quitar la comprobación → caen los casos de objeto y lista;
  restaurar y anotarlo en el test.

### Generador (FR-012)

- [x] T004 [US6] Tests en `tests/test_generar_tabla.py`: (a) con
  `mock.patch.dict(gt.CLASE_C, {"demo/radio/reset": {...}})`, la fila C del
  fixture sale con la categoría, el motivo y las marcas del mapa; (b)
  `test_desde_cero_clase_c_igual_que_la_tabla`: generar desde cero con los
  inventarios reales y comparar, en cada fila de clase C cuyo comando
  empiece por un prefijo de `_REVISADAS` (importado de
  `tests/test_command_table_clase_c.py`), `category`, `reason`, `family`,
  `tool`, `cap`, `one_shot`, `redact_extra`, `open_world` y `example` con la
  tabla real, y que el número de filas comparadas es el esperado (55 en este
  tramo). `test_clase_c` (fila fuera del mapa) sigue esperando «pendiente de
  revisión (spec 025)». Verlos en rojo.
- [x] T005 [US6] Crear `scripts/inventario/clase_c.py` (docstring con el
  porqué: research.md R-4; `CLASE_C: dict[str, dict[str, object]] = {}`) y,
  en `generar_tabla.py`, importarlo y cambiar la rama `if clase == "C"` de
  `_clasificar`: si la clave está en el mapa, `{**base, **CLASE_C[clave]}`;
  si no, el `deny` de hoy. Actualizar la viñeta de la clase C de la
  docstring del generador. El caso (a) de T004 en verde.

### Tests de la tabla y de la ejecución (FR-001, FR-007, FR-009, FR-011)

- [x] T006 [P] [US1] Crear `tests/test_command_table_clase_c.py` (docstring
  con los FR y la regla de cada test): `_ESPERADO` con las 55 entradas
  `zwave_js/*` de R-1 (comando → categoría y marcas: `one_shot`,
  `redact_extra`, `open_world`, `example` sí/no), `_REVISADAS =
  frozenset({"zwave_js/"})`; `test_clasificacion` (subtest por comando),
  `test_ninguna_pendiente_de_la_025` (ninguna entrada de un prefijo revisado
  dice «spec 025»), `test_motivos_concretos` (ningún motivo de lo revisado
  contiene «pendiente» ni «sin revisar»), `test_ningun_proxy` (ninguna
  entrada `hassio/*` ni `supervisor/*` de clase C en `read`/`confirm`) y
  `test_esperado_completo` (cada fila C del inventario de un prefijo revisado
  está en `_ESPERADO` y al revés). Verlos en rojo.
- [x] T007 [P] [US1] En `tests/test_tools_generic_commands_clase_c.py`,
  clase `TestZwave`: `zwave_js/network_status` y `get_config_parameters`
  llegan a `ws_send` con su carga; `subscribe_controller_statistics` y
  `subscribe_node_statistics` llegan a `ws_one_shot_subscription` y nunca a
  `ws_send`; `set_config_parameter` sin token devuelve `preview` y
  `confirmation_token` sin llamar a HA, con token llama una vez;
  `network_neighbors` va por `ha_call_ws_command` (por la de lectura,
  `wrong_generic_tool`); `hard_reset_controller`, `add_node`,
  `validate_dsk_and_enter_pin`, `invoke_cc_api`, `parse_qr_code_string`,
  `refresh_node_info`, `restore_nvm` y `subscribe_log_updates` se rechazan
  con `command_denied` por las dos genéricas sin llamar a HA; centinela de
  `get_provisioning_entries` (un `dsk` centinela no aparece en la respuesta
  ni en el log capturado). Verlos en rojo.
- [x] T008 [US1] En `tests/test_command_table.py`: añadir a
  `_EXCEPCIONES_VERBOS` `zwave_js/is_node_firmware_update_in_progress`,
  `zwave_js/is_any_ota_firmware_update_in_progress` y
  `zwave_js/get_node_firmware_update_capabilities` con su justificación;
  añadir `zwave_js/check_for_config_updates` a `_READ_QUE_SALEN`; cambiar
  `test_clase_c_pendiente_de_la_025` para que solo lo exija en las filas C
  que no empiezan por un prefijo de `_REVISADAS`. Verlos en rojo donde
  corresponda.

### Tabla y mapa (FR-001, FR-010, FR-014)

- [x] T009 [US1] En `hermes/src/hermes/command_table.py`, las 55 entradas
  `zwave_js/*` con la categoría, el motivo y las marcas de R-1, una por
  línea (o bloque con `example`), en su sitio de orden; comentario encima de
  las tres excepciones de verbos, de `network_neighbors`, de
  `get_provisioning_entries` y de las dos `one_shot` (data-model.md). Las
  mismas 55 en `CLASE_C`, con los mismos textos.
- [x] T010 [US1] T006 y T007 en verde. Control negativo: pasar
  `zwave_js/hard_reset_controller` a `confirm` → caen `test_clasificacion` y
  el rechazo de T007; quitar `redact_extra` de `get_provisioning_entries` →
  cae el centinela; quitar `one_shot` de `subscribe_node_statistics` → cae
  su test. Restaurar y anotarlo en el commit.
- [x] T011 [US1] T008 en verde, más `TestMundoAbierto`, `TestEstructura`
  (`test_ejemplos`, `test_marcas`, `test_a_y_c_con_su_cap`) y los hints de
  `tests/test_tools_registration.py` sin cambios en las genéricas. Control
  negativo: quitar una excepción de verbos → cae `TestVerbos` nombrándola.
- [x] T012 [US6] T004 (b) en verde. Control negativo: quitar
  `zwave_js/node_status` de `CLASE_C` → cae el test de desde cero
  nombrándolo; cambiar su motivo en el mapa → cae igual. Restaurar y
  anotarlo.

### Guía (FR-013)

- [x] T013 [US5] En `tests/test_tools_guide.py`, clase
  `TestTemasDeIntegraciones`: `zwave` y sus alias (`zwave_js`, `z-wave`,
  `z_wave`) devuelven el mismo texto; el tema tiene las secciones
  `POR LA GENÉRICA`, `RECHAZADO` y `OTRA VÍA`; nombra `ha_read_ws_command`,
  `ha_call_ws_command`, `generic_commands` y `search=`; cruce con la tabla:
  cada comando `zwave_js/…` entre comillas invertidas de la sección
  disponible está en `read`/`confirm`, y de la rechazada, en `deny`; el
  índice nombra `zwave`. Verlos en rojo.
- [x] T014 [US5] En `hermes/src/hermes/tools/guide.py`: tema `zwave` con el
  contenido de research.md R-7 (lecturas útiles con su carga, escrituras en
  dos pasos con `set_config_parameter` y `rebuild_node_routes`, rechazado por
  grupos, acciones `zwave_js.*` por `ha_call_service` y la UI para
  inclusión, SmartStart, NVM y firmware; aviso de que `network_neighbors`
  apaga la radio y puede pasar del plazo); alias; una línea en `_OVERVIEW`;
  `zwave` en la docstring de `hermes_guide`. T013 en verde. Control negativo:
  citar `zwave_js/add_node` como disponible → cae el cruce; restaurar.
  Las huellas de los temas existentes no cambian.

### Cierre del tramo 1

Desviaciones del tramo 1 (anotadas al hacerlo):
- T002–T003 ampliadas por la D-2 del supervisor: la redacción de valor
  entero se aplica también a `redact_structure` y a las claves sensibles por
  nombre (`security.tapar_entero`, usado por `redact_structure`, `_redactar`
  de las genéricas y `_limpio` de `device_automation` y `system_status`), con
  centinelas de la forma real de la clave de red de ZHA y de las claves
  S0/S2 de Z-Wave en `tests/test_redact_structure.py`. Las S0/S2 no estaban
  cubiertas por ningún marcador: se añaden (hallazgo del tramo).
  `test_only_strings_are_redacted` y la lista de `test_nested_and_lists`
  cambian de expectativa (números y listas bajo clave sensible, tapados).
- T004 (b) va en la clase `TestClaseAConToolDedicada` de
  `tests/test_generar_tabla.py`, junto al desde cero de la clase A.
- T008: `test_clase_c_pendiente_de_la_025` importa `revisada` de
  `tests/test_command_table_clase_c.py` para no duplicar `_REVISADAS`.

- [x] T015 Suite completa: exactamente los 6 fallos conocidos.
- [x] T016 [P] `hermes/CHANGELOG.md`: sección «Integraciones específicas» en
  `## [1.2.0]` (mecanismo de redacción, mapa del generador, Z-Wave JS con su
  recuento 18/13/24 y el tema `zwave`); `docs/HOJA-DE-RUTA.md`: la 025 «en
  curso (tramo 1 de 3)».
- [x] T017 Revisar el diff buscando datos personales, rutas `C:\…` e
  identificadores de modelos; commit(s) del tramo con los controles
  negativos de T003, T010, T011, T012 y T014 en el mensaje.

---

## Tramo 2 — ZHA, Matter, Thread y OTBR (US2, US3, US5, US6)

- [x] T018 Comprobar que la rama tiene el tramo 1 y tomar la línea base.
- [x] T019 [P] [US2] [US3] En `tests/test_command_table_clase_c.py`: añadir
  a `_ESPERADO` las 50 entradas de `zha/*`, `matter/*`, `thread/*` y `otbr/*`
  de R-1 y a `_REVISADAS` sus cuatro prefijos. Verlos en rojo (y
  `test_clase_c_pendiente_de_la_025` deja de exigirlo en ellos).
- [x] T020 [P] [US2] [US3] En `tests/test_tools_generic_commands_clase_c.py`,
  clases `TestZha` y `TestMatterThread`: una lectura, una escritura en dos
  pasos y los rechazos de cada integración (`zha/devices/permit`,
  `zha/topology/update`, `zha/network/backups/restore`,
  `zha/network/change_channel`, `matter/open_commissioning_window`,
  `matter/set_wifi_credentials`, `thread/get_dataset_tlv`,
  `thread/delete_dataset`, `otbr/create_network`); el motivo de
  `zha/devices/permit` nombra `zha.permit`. Centinelas: `zha/network/settings`,
  `zha/network/backups/list` y `zha/network/backups/create` con la forma de
  zigpy (centinela distinto en `network_key.key`, `tc_link_key.key`,
  `key_table[0].key` y `stack_specific.ezsp.hashed_tclk`) y el canal y el PAN
  visibles; `otbr/info` con un `active_dataset_tlvs` centinela bajo una clave
  de dirección extendida; respuesta y log. Verlos en rojo.
- [x] T021 [US2] [US3] En `command_table.py` y en `CLASE_C`, las 50
  entradas de R-1 con sus marcas y ejemplos; comentarios encima de las tres
  de ZHA con `redact_extra` (por qué el valor entero), de `zha/devices/permit`
  y de `otbr/info`.
- [x] T022 [US2] ZHA en verde. Control negativo: quitar `stack_specific` de
  `redact_extra` de `zha/network/settings` → cae su centinela; volver T003 a
  recorrer objetos → caen los centinelas de `network_key` y `key_table`.
  Restaurar y anotarlo.
- [x] T023 [US3] Matter, Thread y OTBR en verde. Control negativo: quitar
  `redact_extra` de `otbr/info` → cae el centinela; pasar
  `thread/get_dataset_tlv` a `read` → caen la clasificación y el rechazo.
- [x] T024 [US6] `test_desde_cero_clase_c_igual_que_la_tabla` en verde con 105
  filas comparadas (actualizar el recuento esperado).
- [x] T025 [US5] En `TestTemasDeIntegraciones`, los temas `zigbee` (alias
  `zha`) y `matter_thread` (alias `matter`, `thread`, `otbr`) con las mismas
  comprobaciones que T013. Verlos en rojo.
- [x] T026 [US5] En `guide.py`, los temas `zigbee` (con `zha.permit` por
  `ha_call_service` en `OTRA VÍA` y las claves tapadas explicadas) y
  `matter_thread` (sin códigos de emparejamiento ni claves; commissioning y
  redes desde la UI); alias; índice; docstring. T025 en verde; huellas
  iguales.
- [x] T027 Suite completa: exactamente los 6 fallos conocidos.
- [x] T028 [P] CHANGELOG (ZHA, Matter, Thread y OTBR con sus recuentos y los
  temas) y hoja de ruta («en curso (tramo 2 de 3)»).
- [x] T029 Revisar el diff (privacidad); commit(s) con los controles
  negativos de T022 y T023.

Desviaciones del tramo 2 (anotadas al hacerlo):
- T021: al releer los handlers, `zha/configuration` devuelve las opciones
  de la entrada con `zha_alarm_options.alarm_master_code` (código maestro de
  la alarma de ZHA; `zha/diagnostics.py` lo tapa) y ningún marcador lo
  reconoce. Se añade `redact_extra=("alarm_master_code",)` a
  `zha/configuration` y a `zha/configuration/update` (su vista previa resume
  la carga con las mismas claves), sin cambiar la categoría; R-1, R-6 y
  FR-002 actualizados. Las entradas que tapan secretos pasan de 7 a 9 (SC-002
  y la tabla de R-6 las cuentan en el tramo 3).
- T020: los rechazos de ZHA prueban también `zha/devices/reconfigure`;
  los de Matter y Thread, `matter/commission`, `matter/set_thread` y
  `thread/add_dataset_tlv`. Test nuevo de `test_command_table_clase_c.py`:
  `test_redact_extra_de_las_claves` (qué claves tapa cada entrada) y
  `test_permit_remite_a_la_accion`.
- T025: `_TEMAS` de `TestTemasDeIntegraciones` pasa a una tupla de
  prefijos por tema (el de `matter_thread` tiene tres).

---

## Tramo 3 — resto y cierre (US4, US5, US6)

- [x] T030 Comprobar que la rama tiene el tramo 2 y tomar la línea base.
- [x] T031 [P] [US4] En `tests/test_command_table_clase_c.py`: añadir a
  `_ESPERADO` las 87 restantes de R-1 (CAP-104, CAP-105 y CAP-106) y dejar
  `_REVISADAS` con todos los prefijos de clase C del inventario. Verlos en
  rojo.
- [x] T032 [P] [US4] En `tests/test_tools_generic_commands_clase_c.py`,
  clase `TestResto`: `mqtt/device/debug_info` y `usb/list_serial_ports`
  (con su ejemplo) por la de lectura; `bluetooth/subscribe_advertisements`,
  `dhcp/subscribe_discovery` e `insteon/aldb/notify_all` por
  `ws_one_shot_subscription`; `insteon/aldb/write`, `knx/create_entity`,
  `lcn/devices/scan` y `dynalite/save-config` en dos pasos; rechazos de
  `esphome/get_encryption_key`, `sendspin/get_pairing_token`,
  `insteon/config/get_modem_schema`, `insteon/config/update_modem_config`,
  `knx/project_file_process`, `mobile_app/push_notification_channel`,
  `generic_camera/start_preview`, `ssdp/subscribe_discovery` y
  `mqtt/subscribe`; centinelas de `insteon/config/get` (contraseña del hub
  bajo `modem_config.password`, tapada por el marcador) y de
  `mqtt/device/debug_info` (código de alarma en
  `discovery_data.payload.code` y dentro del texto de un mensaje de
  `transmitted`; los de `subscriptions` siguen visibles). Verlos en rojo.
- [x] T033 [US4] En `command_table.py` y en `CLASE_C`, las 87 entradas de
  R-1 con sus marcas y ejemplos; comentarios de `insteon/config/get`,
  `insteon/config/get_modem_schema`, `notify/html5/appkey`, las tres
  `one_shot` y las suscripciones descartadas por R-2.
- [x] T034 [US4] CAP-104 y CAP-105 en verde.
- [x] T035 [US4] CAP-106 en verde. Control negativo: pasar
  `esphome/get_encryption_key` a `read` → caen la clasificación y el
  rechazo; renombrar `password` del centinela de Insteon a `pass_hub` (que
  no es marcador) → cae el centinela, lo que demuestra que lo tapa el
  marcador y no otra cosa; quitar `transmitted` de `redact_extra` de
  `mqtt/device/debug_info` → cae su centinela. Restaurar y anotarlo.
- [x] T036 [US6] `test_ninguna_pendiente_de_la_025` sin filtro (la tabla
  entera) y borrar `test_clase_c_pendiente_de_la_025` de
  `tests/test_command_table.py` (y el control negativo de su docstring, que
  pasa al test nuevo). Control negativo: devolver una entrada cualquiera a
  «pendiente de revisión (spec 025)» → cae nombrándola.
- [x] T037 [US6] En `generar_tabla.py`, la fila C fuera del mapa pasa a
  `deny("sin revisar")`; docstring. En `test_generar_tabla.py`,
  `test_clase_c` espera «sin revisar»; el desde cero compara las 192 filas y
  comprueba además que ninguna entrada generada dice «spec 025». Control
  negativo: volver al texto anterior → caen los dos.
- [x] T038 [US5] En `TestTemasDeIntegraciones`, el tema `other_integrations`
  y sus alias (`mqtt`, `usb`, `bluetooth`, `knx`, `insteon`, `lcn`,
  `esphome`, `dynalite`, `lorawan`, `modbus`, `wyoming`) con las mismas
  comprobaciones. Verlos en rojo.
- [x] T039 [US5] En `guide.py`, el tema `other_integrations` (por
  integración: lo útil por la genérica, lo rechazado y por qué); alias;
  índice; docstring. T038 en verde; huellas iguales.
- [x] T040 [US4] Banco: `usb:` en `tests/banco/ha_config/configuration.yaml`
  (comentario del porqué) y `tests/banco/test_banco_integraciones_c.py`
  (`pytestmark = pytest.mark.banco`): `usb/list_serial_ports` y
  `usb/list_serial_integrations` por `ha_read_ws_command` devuelven una
  lista (sin exigir puertos); `zwave_js/hard_reset_controller` y
  `thread/get_dataset_tlv` se rechazan con `command_denied` también contra HA
  real; `zha/devices` sin ZHA cargado devuelve `ha_command_failed` con
  `ha_code` `unknown_command` y la pista de versión. Comprobar que el resto
  del banco sigue verde con `usb:` cargado (arranque y avisos del log).
- [x] T041 [US4] Comprobar en el CI (job `banco-core`) que T040 pasa. Si
  `usb` no arranca en el contenedor: `xfail` estricto que espera ese fallo
  concreto (hallazgo), con su motivo. Anotar en la matriz de la 008 qué se
  ejecuta en el banco y qué queda en unitarios («sin hardware en el banco»).
- [x] T042 [P] `SECURITY.md`, viñeta de las genéricas: `redact_extra` tapa
  el valor entero, y los comandos de integraciones que devuelven o
  introducen claves de red, DSK, códigos de emparejamiento o tokens se
  rechazan o se tapan.
- [x] T043 [P] `hermes/CHANGELOG.md`: sección «Integraciones específicas»
  completa (recuento final 73/57/62, desviaciones de R-3, aviso de que una
  versión nueva de HA exige volver a leer los handlers de la clase C que
  cambien); `docs/HOJA-DE-RUTA.md`: la 025 «hecha» con el recuento (sin
  tools nuevas, no hay filas en la matriz de la 014) y, en «Pruebas manuales
  pendientes», la prueba con hardware de quickstart.md; matriz de
  `specs/008-cobertura-total/plan.md`: filas CAP-100…CAP-106 con los tests
  (`test_command_table_clase_c.py`, `test_tools_generic_commands_clase_c.py`
  y, CAP-105, el banco), y la fila de la 025 en la tabla de sub-features
  del mismo plan (3 tramos en vez de 2, y el total de tramos del programa).
- [x] T044 Comprobar que README, README.es y DOCS no cambian (mismo número
  de tools; `TestToolCountInDocs` en verde).
- [ ] T045 Suite completa: exactamente los 6 fallos conocidos; CI de Linux en
  verde (tests, banco, Semgrep, CodeQL).
- [x] T046 Revisar el diff entero de la 025 (privacidad, rutas, modelos);
  commit(s) con los controles negativos de T035, T036 y T037; marcar T024
  de `specs/008-cobertura-total/tasks.md` como hecha.

Desviaciones del tramo 3 (anotadas al hacerlo):
- T030–T033: los handlers de las 87 se volvieron a leer en `fuentes`
  (decisión del supervisor) y la clasificación de R-1 se mantiene entera; no
  aparece ninguna entrada nueva que tape secretos, así que SC-002 queda en
  nueve (spec.md actualizada). La tabla y el mapa se escribieron con un
  script de un solo uso que lee R-1 y usa `_render` del generador, para que
  el texto y las marcas salgan idénticos en los dos sitios; por eso los
  tests de T031–T032 se vieron en rojo con los controles negativos de T035
  y no antes del código.
- T031: `test_motivos_concretos` (tramo 1) buscaba «pendiente» a secas, y
  siete motivos de Insteon dicen con razón que un cambio queda «pendiente
  hasta aldb/write» o «las propiedades pendientes». Se cambia a una regex de
  los textos provisionales («sin revisar», «pendiente de revisión/tool»), que
  comparte con el test nuevo `test_ninguna_c_sin_revisar`. Tests nuevos:
  `test_revisadas_cubre_el_inventario`, `test_recuento_del_tramo_3` y
  `test_recuento_total`.
- T036: el control negativo del generador (T037) solo tira `test_clase_c`:
  el desde cero real no cae con eso solo porque las 192 están en el mapa; su
  comprobación de «spec 025» cae si además una fila sale del mapa
  (comprobado quitando `wyoming/info`).
- T040: el banco lee también `usb/list_serial_ports` con `include_usage` y
  compara con el lector independiente (misma longitud; `list_serial_integrations`,
  la misma lista).
- T044: por decisión del supervisor, README, README.es y DOCS sí cambian:
  una frase dice que las genéricas cubren la clase C (sin tools nuevas; el
  recuento de tools no cambia).

---

## Dependencias

- T001 → T002…T014 (en el tramo 1, T002–T003, T004–T005 y T006–T008 en
  paralelo; T009 necesita T005; T010–T012 necesitan T009).
- Tramo 2 necesita el 1 integrado; tramo 3, el 2.
- T036 y T037 (cierre estricto) solo cuando las 192 están en la tabla (T033).

## Paralelo

Dentro de cada tramo: los tests de la tabla, de la ejecución y de la guía
([P]) se escriben en paralelo; la documentación ([P]) también. La tabla y el
mapa se editan en un solo paso para no desincronizarlos.

## Estrategia

MVP = tramo 1: el mecanismo y Z-Wave JS ya dan valor y fijan el patrón que los
tramos 2 y 3 repiten. Al terminar el tramo 3 corre el converge de la 025
(`speckit-converge` sobre este directorio) antes de integrar en
`feat/cobertura-total`.
