# Investigación: integraciones específicas por la tabla (025)

Fuentes leídas (sin ejecutar nada): el código de Home Assistant Core 2026.11.1
de cada integración de la clase C, el de Hermes en `806a764`
(`command_table.py`, `command_policy.py`, `tools/generic_commands.py`,
`ha.py`, `security.py`, `tools/guide.py`), el generador
`scripts/inventario/generar_tabla.py` con sus tests y la 008 (CAP-100…CAP-106,
FR-089, FR-090).

## R-1 Clasificación comando a comando

**Decisión**: la tabla de abajo, generada a partir de la lectura de cada
handler. Es la fuente para `command_table.py` y para el mapa del generador
(R-4): el texto de la columna «Motivo» es el `reason` exacto de la entrada; la
columna «Marcas» da `one_shot`, `open_world`, `redact_extra` y `example`.
Todas las entradas tienen familia `generic_commands` y conservan la CAP del
inventario.

**Recuento**: 192 comandos → **73 `read`, 57 `confirm`, 62 `deny`**.

| CAP | Integración | Comandos | `read` | `confirm` | `deny` | Tramo |
|---|---|---|---|---|---|---|
| CAP-100 | `zwave_js` | 55 | 18 | 13 | 24 | 1 |
| CAP-101 | `zha` | 28 | 13 | 10 | 5 | 2 |
| CAP-102 | `matter` | 11 | 3 | 1 | 7 | 2 |
| CAP-103 | `thread` (7), `otbr` (4) | 11 | 2 | 2 | 7 | 2 |
| CAP-104 | `mqtt` | 2 | 1 | 0 | 1 | 3 |
| CAP-105 | `usb` (3), `bluetooth` (4) | 7 | 4 | 0 | 3 | 3 |
| CAP-106 | resto (78) | 78 | 32 | 31 | 15 | 3 |
| | **Total** | **192** | **73** | **57** | **62** | |

Lo que el handler hace y por qué cada `deny` (notas de lectura):

- **Suscripciones de progreso en comandos de petición-respuesta**:
  `zwave_js/refresh_node_info`, `zha/devices/reconfigure`, `zha/devices/permit`
  (además activa el modo depuración del gateway, que solo se apaga al cancelar,
  y acepta `install_code`/`qr_code`, que son claves de enlace),
  `zwave_js/backup_nvm` (el resultado llega en un evento),
  `thread/discover_routers`. Todos guardan `connection.subscriptions[id]` y
  mandan eventos tras el resultado. La genérica usa `ws_send` y no cancela
  nada: la suscripción quedaría viva en la conexión WebSocket compartida de
  Hermes hasta reconectar. FR-009 de la 008 lo prohíbe.
- **No responden**: `zha/topology/update` (crea una tarea y no llama a
  `send_result`), `generic_camera/start_preview` (solo manda un evento, y
  depende de un flujo de la UI en curso).
- **Secretos devueltos**: `thread/get_dataset_tlv` (TLV con la clave de red),
  `esphome/get_encryption_key` (`noise_psk`), `sendspin/get_pairing_token`,
  `zwave_js/parse_qr_code_string` y `try_parse_dsk_from_qr_code_string` (DSK,
  cuyos 5 primeros dígitos son el PIN de S2), `matter/open_commissioning_window`
  (devuelve `setup_pin_code` y `setup_manual_code`),
  `insteon/config/get_modem_schema` (`build_hub_schema` pone la contraseña del
  hub como `default` del campo; la clave `default` no es sensible y saldría en
  claro).
- **Secretos introducidos**: `matter/commission*` (código de emparejamiento),
  `matter/set_thread` (dataset con clave), `matter/set_wifi_credentials`,
  `thread/add_dataset_tlv`, `zwave_js/validate_dsk_and_enter_pin`,
  `zwave_js/provision_smart_start_node` (DSK), `insteon/config/
  update_modem_config` (credenciales del hub), `knx/project_file_process`
  (contraseña del proyecto, y un `file_id` de una subida que MCP no hace).
- **Destruyen o reemplazan la red**: `zwave_js/hard_reset_controller`,
  `restore_nvm`, `remove_failed_node`, `replace_failed_node`,
  `zha/network/backups/restore`, `zha/network/change_channel`,
  `otbr/create_network` (reset de fábrica del router), `otbr/set_network`,
  `otbr/set_channel`, `thread/delete_dataset` (si es la única copia de las
  credenciales), `matter/remove_matter_fabric`.
- **Interactivo o físico**: inclusión y exclusión de Z-Wave
  (`add_node`, `remove_node`, S2, `subscribe_new_devices`), `insteon/device/add`.
- **Sin vista previa posible**: `zwave_js/invoke_cc_api` (cualquier método de
  cualquier clase de comando: también fijar códigos de cerradura o leerlos).
- **Firmware**: `zwave_js/abort_firmware_update` (abortar un flasheo a medias
  puede dejar el nodo inservible) y `subscribe_firmware_update_status`.
- **App móvil**: `mobile_app/push_notification_channel` sustituye el canal de
  la app real (`async_teardown` del registrado) y exige su `webhook_id`
  (credencial de hecho para Hermes, `webhook_id` es marcador sensible).

Lo no evidente en `read`/`confirm`:

- `zwave_js/network_neighbors` solo lee, pero APAGA la radio mientras recorre
  los nodos (`async_toggle_rf(False)`): `confirm`. En una red grande puede
  pasar del plazo de 30 s de `ws_send`: Hermes devuelve error de plazo, pero
  el handler sigue en una tarea protegida (`asyncio.shield`) que vuelve a
  encender la radio; la guía lo avisa.
- `zwave_js/get_raw_config_parameter`, `zha/devices/clusters/attributes/value`,
  `matter/ping_node`: generan tráfico de radio, pero no cambian nada: `read`.
- `zwave_js/check_for_config_updates` pregunta por internet:
  `read` con `open_world`; `install_config_update` descarga: `confirm` con
  `open_world`.
- `zwave_js/network_status` devuelve `ws_server_url` (dirección interna del
  servidor Z-Wave JS, sin credenciales): `read`. La redacción de textos de la
  genérica tapa una URL con contraseña si la hubiera.
- `zha/configuration` devuelve las opciones de la entrada con
  `zha_alarm_options.alarm_master_code`, el código maestro del panel de
  alarma de ZHA (`CONF_ZHA_ALARM_SCHEMA` de `zha/helpers.py`;
  `zha/diagnostics.py` lo tapa con `CONF_ALARM_MASTER_CODE`). Ningún
  marcador lo reconoce: `redact_extra=("alarm_master_code",)` en la lectura
  y en `zha/configuration/update`, cuya vista previa resume la carga con las
  mismas claves (hallazgo del tramo 2; no cambia la categoría).
- `notify/html5/appkey` devuelve la clave PÚBLICA VAPID: no es secreta.
- `insteon/config/get` devuelve `config_entry.data`; en un hub v2 lleva
  `password`, que tapa el marcador `password` de `redact_structure`.
- `mqtt/device/debug_info` devuelve, por entidad, el `payload` de descubrimiento
  (un objeto: el de una alarma o una cerradura MQTT puede llevar `code`) y los
  mensajes ENVIADOS por HA (`transmitted`, texto: el comando de armar una
  alarma puede llevar el código dentro, y `redact_secrets` no reconoce
  `code`). `redact_extra=("code", "transmitted")`: el `code` del
  descubrimiento y la lista entera de enviados, tapados (valor entero, R-5);
  los mensajes recibidos (`subscriptions`) siguen visibles, que es lo útil
  para depurar.
- `dynalite/save-config` reemplaza los datos de la entrada: el motivo lo dice.
- `lcn/devices/scan` escanea y además escribe los módulos encontrados en la
  entrada: `confirm`.
- `insteon/aldb/load` y `properties/load` releen del dispositivo y guardan el
  fichero de Insteon en `/config`: `confirm`.

<!-- Tabla generada a partir de la lectura de los handlers. -->

#### CAP-100

| Comando | Categoría | Marcas | Motivo (texto de la tabla) |
|---|---|---|---|
| `zwave_js/abort_firmware_update` | `deny` | — | firmware: abortar un flasheo a medias puede dejar el nodo inservible; se hace desde la UI |
| `zwave_js/add_node` | `deny` | — | inclusión o exclusión interactiva: eventos, pulsar un botón del dispositivo y S2; se hace desde la UI |
| `zwave_js/backup_nvm` | `deny` | — | copia de la NVM del controlador por eventos de progreso (el resultado llega en un evento, no en la respuesta) |
| `zwave_js/begin_rebuilding_routes` | `confirm` | — | reconstruye las rutas de toda la red (largo, mucho tráfico de radio) |
| `zwave_js/cancel_secure_bootstrap_s2` | `deny` | — | inclusión o exclusión interactiva: eventos, pulsar un botón del dispositivo y S2; se hace desde la UI |
| `zwave_js/check_for_config_updates` | `read` | `open_world` | pregunta por internet si hay base de datos de dispositivos nueva; solo lee |
| `zwave_js/data_collection_status` | `read` | — | si se envían estadísticas de uso a Z-Wave JS; solo lee |
| `zwave_js/get_config_parameters` | `read` | — | parámetros de configuración de un nodo con su valor y metadatos; solo lee |
| `zwave_js/get_log_config` | `read` | — | configuración del log del driver Z-Wave JS; solo lee |
| `zwave_js/get_node_firmware_update_capabilities` | `read` | — | qué admite un nodo para actualizar firmware; solo lee |
| `zwave_js/get_provisioning_entries` | `read` | `redact_extra=dsk` | nodos preaprovisionados por SmartStart; el `dsk` (incluye el PIN de S2) sale tapado |
| `zwave_js/get_raw_config_parameter` | `read` | — | pide al nodo el valor de un parámetro sin definición (tráfico de radio, no cambia nada) |
| `zwave_js/grant_security_classes` | `deny` | — | inclusión o exclusión interactiva: eventos, pulsar un botón del dispositivo y S2; se hace desde la UI |
| `zwave_js/hard_reset_controller` | `deny` | — | reset de fábrica del controlador: borra la red entera |
| `zwave_js/install_config_update` | `confirm` | `open_world` | descarga e instala la base de datos de dispositivos nueva |
| `zwave_js/invoke_cc_api` | `deny` | — | llamada arbitraria a una clase de comando: puede escribir cualquier cosa (códigos de cerradura, seguridad) y no tiene vista previa útil |
| `zwave_js/is_any_ota_firmware_update_in_progress` | `read` | — | si algún nodo está actualizando firmware; solo lee |
| `zwave_js/is_node_firmware_update_in_progress` | `read` | — | si un nodo está actualizando firmware; solo lee |
| `zwave_js/lookup_device` | `read` | — | busca un modelo en la base de datos de dispositivos local de Z-Wave JS; solo lee |
| `zwave_js/network_neighbors` | `confirm` | — | lee la tabla de vecinos de todos los nodos APAGANDO la radio mientras dura (puede colgar controladores antiguos) |
| `zwave_js/network_status` | `read` | — | estado de la red Z-Wave: cliente, controlador y nodos (sin claves); solo lee |
| `zwave_js/node_alerts` | `read` | — | avisos de la base de datos de dispositivos para un nodo; solo lee |
| `zwave_js/node_capabilities` | `read` | — | clases de comando de cada endpoint de un nodo; solo lee |
| `zwave_js/node_metadata` | `read` | — | instrucciones de inclusión, exclusión y reset del fabricante y enlace a su base de datos; solo lee |
| `zwave_js/node_status` | `read` | — | estado de un nodo (vivo, dormido, listo, seguridad); solo lee |
| `zwave_js/parse_qr_code_string` | `deny` | — | devuelve el DSK del código QR (incluye el PIN de S2) |
| `zwave_js/provision_smart_start_node` | `deny` | — | SmartStart: lleva el DSK del código QR (incluye el PIN de S2); se hace desde la UI |
| `zwave_js/rebuild_node_routes` | `confirm` | ejemplo `{"device_id": "<device_id>"}` | reconstruye las rutas de un nodo |
| `zwave_js/refresh_node_cc_values` | `confirm` | — | vuelve a pedir al nodo los valores de una clase de comando |
| `zwave_js/refresh_node_info` | `deny` | — | reentrevista el nodo y registra una suscripción de progreso en la conexión compartida que la genérica no cierra |
| `zwave_js/refresh_node_values` | `confirm` | — | vuelve a pedir al nodo todos sus valores (tráfico de radio) |
| `zwave_js/remove_failed_node` | `deny` | — | quita un nodo a la fuerza de la red, sin vuelta atrás |
| `zwave_js/remove_node` | `deny` | — | inclusión o exclusión interactiva: eventos, pulsar un botón del dispositivo y S2; se hace desde la UI |
| `zwave_js/replace_failed_node` | `deny` | — | sustituye un nodo fallido: inclusión interactiva con eventos y sin vuelta atrás |
| `zwave_js/restore_nvm` | `deny` | — | sobrescribe la NVM del controlador: cambia la red entera |
| `zwave_js/set_config_parameter` | `confirm` | ejemplo `{"device_id": "<device_id>", "property": 3, "value": 1}` | cambia un parámetro de configuración de un nodo |
| `zwave_js/set_raw_config_parameter` | `confirm` | — | escribe un parámetro sin definición en el nodo (lee antes el valor con get_raw_config_parameter) |
| `zwave_js/stop_exclusion` | `confirm` | — | detiene una exclusión en curso |
| `zwave_js/stop_inclusion` | `confirm` | — | detiene una inclusión en curso |
| `zwave_js/stop_rebuilding_routes` | `confirm` | — | detiene la reconstrucción de rutas de la red |
| `zwave_js/subscribe_config_parameter_updates` | `deny` | — | suscripción/streaming sin primer mensaje con el estado: MCP es petición-respuesta |
| `zwave_js/subscribe_controller_statistics` | `read` | `one_shot` | estadísticas del controlador: un solo mensaje y se cancela |
| `zwave_js/subscribe_firmware_update_status` | `deny` | — | suscripción/streaming sin primer mensaje con el estado: MCP es petición-respuesta |
| `zwave_js/subscribe_log_updates` | `deny` | — | suscripción/streaming sin primer mensaje con el estado: MCP es petición-respuesta |
| `zwave_js/subscribe_new_devices` | `deny` | — | inclusión o exclusión interactiva: eventos, pulsar un botón del dispositivo y S2; se hace desde la UI |
| `zwave_js/subscribe_node_statistics` | `read` | `one_shot` | estadísticas de un nodo (RSSI, rutas, fallos): un solo mensaje y se cancela |
| `zwave_js/subscribe_node_status` | `deny` | — | suscripción/streaming sin primer mensaje con el estado: MCP es petición-respuesta |
| `zwave_js/subscribe_rebuild_routes_progress` | `deny` | — | suscripción/streaming sin primer mensaje con el estado: MCP es petición-respuesta |
| `zwave_js/subscribe_s2_inclusion` | `deny` | — | inclusión o exclusión interactiva: eventos, pulsar un botón del dispositivo y S2; se hace desde la UI |
| `zwave_js/supports_feature` | `read` | — | si el controlador admite una función (p. ej. SmartStart); solo lee |
| `zwave_js/try_parse_dsk_from_qr_code_string` | `deny` | — | devuelve el DSK del código QR (incluye el PIN de S2) |
| `zwave_js/unprovision_smart_start_node` | `deny` | — | SmartStart: lleva el DSK del código QR (incluye el PIN de S2); se hace desde la UI |
| `zwave_js/update_data_collection_preference` | `confirm` | — | activa o desactiva el envío de estadísticas de uso a Z-Wave JS |
| `zwave_js/update_log_config` | `confirm` | — | cambia el nivel o el destino del log del driver Z-Wave JS |
| `zwave_js/validate_dsk_and_enter_pin` | `deny` | — | introduce el PIN de S2 de una inclusión: secreto y acción física |

#### CAP-101

| Comando | Categoría | Marcas | Motivo (texto de la tabla) |
|---|---|---|---|
| `zha/configuration` | `read` | `redact_extra=alarm_master_code` | opciones de ZHA y su esquema; el código maestro de la alarma sale tapado; solo lee |
| `zha/configuration/update` | `confirm` | `redact_extra=alarm_master_code` | cambia las opciones de ZHA y recarga la integración; el código maestro de la alarma sale tapado en la vista previa |
| `zha/device` | `read` | — | un dispositivo Zigbee; solo lee |
| `zha/devices` | `read` | — | dispositivos Zigbee con su información; solo lee |
| `zha/devices/bind` | `confirm` | ejemplo `{"source_ieee": "00:11:22:33:44:55:66:77", "target_ieee": "00:11:22:33:44:55:66:88"}` | vincula dos dispositivos Zigbee |
| `zha/devices/bindable` | `read` | — | dispositivos a los que se puede vincular uno; solo lee |
| `zha/devices/clusters` | `read` | — | clústeres de un dispositivo; solo lee |
| `zha/devices/clusters/attributes` | `read` | — | atributos de un clúster; solo lee |
| `zha/devices/clusters/attributes/value` | `read` | — | lee un atributo del dispositivo por radio; no cambia nada |
| `zha/devices/clusters/commands` | `read` | — | comandos de un clúster; solo lee |
| `zha/devices/groupable` | `read` | — | dispositivos que admiten grupos; solo lee |
| `zha/devices/permit` | `deny` | — | abre la red con modo depuración y eventos que la genérica no cierra, y acepta códigos de instalación (claves); para permitir uniones, la acción zha.permit por ha_call_service |
| `zha/devices/reconfigure` | `deny` | — | reconfigura el nodo y registra una suscripción de progreso en la conexión compartida que la genérica no cierra |
| `zha/devices/unbind` | `confirm` | — | desvincula dos dispositivos Zigbee |
| `zha/group` | `read` | — | un grupo Zigbee; solo lee |
| `zha/group/add` | `confirm` | ejemplo `{"group_name": "Salón", "members": [{"ieee": "00:11:22:33:44:55:66:77", "endpoint_id": 1}]}` | crea un grupo Zigbee |
| `zha/group/members/add` | `confirm` | — | añade miembros a un grupo Zigbee |
| `zha/group/members/remove` | `confirm` | — | quita miembros de un grupo Zigbee |
| `zha/group/remove` | `confirm` | — | borra grupos Zigbee |
| `zha/groups` | `read` | — | grupos Zigbee; solo lee |
| `zha/groups/bind` | `confirm` | — | vincula un dispositivo a un grupo |
| `zha/groups/unbind` | `confirm` | — | desvincula un dispositivo de un grupo |
| `zha/network/backups/create` | `confirm` | `redact_extra=network_key,tc_link_key,key_table,stack_specific` | crea una copia de la red Zigbee (5-30 s); las claves salen tapadas en la respuesta |
| `zha/network/backups/list` | `read` | `redact_extra=network_key,tc_link_key,key_table,stack_specific` | copias de la red Zigbee guardadas; las claves de red y de enlace salen tapadas |
| `zha/network/backups/restore` | `deny` | — | restaura una copia de la red Zigbee: cambia la red entera y lleva sus claves |
| `zha/network/change_channel` | `deny` | — | migra la red Zigbee a otro canal: los dispositivos que no sigan se pierden |
| `zha/network/settings` | `read` | `redact_extra=network_key,tc_link_key,key_table,stack_specific` | ajustes de la red Zigbee (canal, PAN, radio); las claves de red y de enlace salen tapadas |
| `zha/topology/update` | `deny` | — | no envía respuesta nunca: la genérica esperaría hasta el plazo |

#### CAP-102

| Comando | Categoría | Marcas | Motivo (texto de la tabla) |
|---|---|---|---|
| `matter/commission` | `deny` | — | commissioning: lleva el código de emparejamiento (PIN) del dispositivo |
| `matter/commission_on_network` | `deny` | — | commissioning: lleva el código de emparejamiento (PIN) del dispositivo |
| `matter/interview_node` | `confirm` | — | reentrevista un nodo Matter |
| `matter/network_topology` | `read` | — | topología de la red Matter/Thread (refresh=true la vuelve a medir); no cambia nada |
| `matter/node_diagnostics` | `read` | — | diagnóstico de red de un nodo Matter; solo lee |
| `matter/open_commissioning_window` | `deny` | — | devuelve el código de emparejamiento que da control del dispositivo a otro ecosistema; se hace desde la UI |
| `matter/ping_node` | `read` | — | hace ping a un nodo Matter; no cambia nada |
| `matter/remove_matter_fabric` | `deny` | — | quita un fabric de un dispositivo: otro ecosistema pierde su control, sin vuelta atrás |
| `matter/set_thread` | `deny` | — | fija el dataset Thread del servidor Matter: lleva la clave de red |
| `matter/set_wifi_credentials` | `deny` | — | fija la contraseña Wi-Fi del servidor Matter |
| `matter/subscribe_network_topology` | `deny` | — | suscripción; la misma topología la da matter/network_topology |

#### CAP-103

| Comando | Categoría | Marcas | Motivo (texto de la tabla) |
|---|---|---|---|
| `otbr/create_network` | `deny` | — | reset de fábrica del router de borde y red Thread nueva |
| `otbr/info` | `read` | `redact_extra=active_dataset_tlvs` | routers de borde OpenThread (canal, PAN, URL); el dataset activo (con la clave de red) sale tapado |
| `otbr/set_channel` | `deny` | — | migra la red Thread a otro canal |
| `otbr/set_network` | `deny` | — | cambia la red Thread del router de borde |
| `thread/add_dataset_tlv` | `deny` | — | introduce un dataset con la clave de red Thread |
| `thread/delete_dataset` | `deny` | — | borra las credenciales guardadas de una red Thread: sin otra copia, la red no se recupera |
| `thread/discover_routers` | `deny` | — | descubrimiento mDNS de routers por eventos que la genérica no cierra |
| `thread/get_dataset_tlv` | `deny` | — | devuelve el dataset en TLV, que incluye la clave de red Thread |
| `thread/list_datasets` | `read` | — | datasets Thread guardados (sin la clave de red) y cuál es el preferido; solo lee |
| `thread/set_preferred_border_agent` | `confirm` | — | cambia el router de borde preferido de un dataset |
| `thread/set_preferred_dataset` | `confirm` | ejemplo `{"dataset_id": "<dataset_id>"}` | cambia el dataset Thread preferido (red que usarán los dispositivos nuevos) |

#### CAP-104

| Comando | Categoría | Marcas | Motivo (texto de la tabla) |
|---|---|---|---|
| `mqtt/device/debug_info` | `read` | `redact_extra=code,transmitted`; ejemplo `{"device_id": "<device_id>"}` | topics, suscripciones, descubrimiento y últimos mensajes recibidos de un dispositivo MQTT; los mensajes enviados y el `code` de alarmas y cerraduras salen tapados |
| `mqtt/subscribe` | `deny` | — | suscripción/streaming sin primer mensaje con el estado: MCP es petición-respuesta |

#### CAP-105

| Comando | Categoría | Marcas | Motivo (texto de la tabla) |
|---|---|---|---|
| `bluetooth/subscribe_advertisements` | `read` | `one_shot` | anuncios Bluetooth vistos: un solo mensaje con todos y se cancela |
| `bluetooth/subscribe_connection_allocations` | `deny` | — | solo emite si hay asignaciones: sin datos, la lectura de un mensaje acabaría en error de plazo |
| `bluetooth/subscribe_scanner_details` | `deny` | — | solo emite si hay escáneres: sin datos, la lectura de un mensaje acabaría en error de plazo |
| `bluetooth/subscribe_scanner_state` | `deny` | — | un mensaje por escáner: leer solo el primero daría un estado incompleto |
| `usb/list_serial_integrations` | `read` | — | integraciones que se configuran con un puerto serie; solo lee |
| `usb/list_serial_ports` | `read` | ejemplo `{"include_usage": true}` | puertos serie y dongles (y, con include_usage, quién los usa); solo lee |
| `usb/scan` | `read` | — | pide un nuevo escaneo USB; puede hacer aparecer integraciones descubiertas, no configura nada |

#### CAP-106

| Comando | Categoría | Marcas | Motivo (texto de la tabla) |
|---|---|---|---|
| `dhcp/subscribe_discovery` | `read` | `one_shot` | equipos vistos por DHCP (MAC, nombre, IP): un solo mensaje con todos y se cancela |
| `dynalite/get-config` | `read` | — | configuración de los puentes Dynalite; solo lee |
| `dynalite/save-config` | `confirm` | — | REEMPLAZA la configuración entera de un puente Dynalite (lee antes con dynalite/get-config) |
| `esphome/get_device_capabilities` | `read` | — | capacidades de un dispositivo ESPHome (proxys Bluetooth, Z-Wave y serie); solo lee |
| `esphome/get_device_wizard` | `read` | — | asistente de configuración de un dispositivo ESPHome; solo lee |
| `esphome/get_encryption_key` | `deny` | — | devuelve la clave de cifrado de la API de ESPHome |
| `generic_camera/start_preview` | `deny` | — | vista previa de un flujo de configuración de la UI: no envía respuesta, solo un evento |
| `insteon/aldb/add_default_links` | `confirm` | — | escribe en el dispositivo los enlaces por defecto |
| `insteon/aldb/change` | `confirm` | — | cambia un registro de la ALDB (pendiente hasta aldb/write) |
| `insteon/aldb/create` | `confirm` | — | añade un registro a la ALDB (pendiente hasta aldb/write) |
| `insteon/aldb/get` | `read` | — | base de datos de enlaces (ALDB) de un dispositivo; solo lee |
| `insteon/aldb/load` | `confirm` | — | vuelve a leer la ALDB del dispositivo y la guarda en el fichero de Insteon |
| `insteon/aldb/notify` | `deny` | — | suscripción/streaming sin primer mensaje con el estado: MCP es petición-respuesta |
| `insteon/aldb/notify_all` | `read` | `one_shot` | si alguna ALDB se está cargando: un solo mensaje y se cancela |
| `insteon/aldb/reset` | `confirm` | — | descarta los cambios pendientes de la ALDB |
| `insteon/aldb/write` | `confirm` | — | escribe en el dispositivo los cambios pendientes de su ALDB |
| `insteon/config/device_override/add` | `confirm` | — | añade un override de dispositivo |
| `insteon/config/device_override/remove` | `confirm` | — | quita un override de dispositivo |
| `insteon/config/get` | `read` | — | configuración del módem, X10 y overrides; la contraseña del hub sale tapada |
| `insteon/config/get_broken_links` | `read` | — | enlaces rotos; solo lee |
| `insteon/config/get_modem_schema` | `deny` | — | el esquema del hub lleva la contraseña como valor por defecto |
| `insteon/config/get_unknown_devices` | `read` | — | dispositivos desconocidos; solo lee |
| `insteon/config/update_modem_config` | `deny` | — | introduce las credenciales del hub y reconecta el módem |
| `insteon/device/add` | `deny` | — | modo de enlace con eventos y pulsar el botón del dispositivo |
| `insteon/device/add/cancel` | `confirm` | — | cancela el modo de enlace |
| `insteon/device/add_x10` | `confirm` | — | añade un dispositivo X10 |
| `insteon/device/get` | `read` | — | un dispositivo Insteon; solo lee |
| `insteon/device/remove` | `confirm` | — | quita un dispositivo Insteon (con remove_all_refs, también sus enlaces en los demás) |
| `insteon/properties/change` | `confirm` | — | cambia una propiedad (pendiente hasta properties/write) |
| `insteon/properties/get` | `read` | — | propiedades de un dispositivo y su esquema; solo lee |
| `insteon/properties/load` | `confirm` | — | vuelve a leer las propiedades del dispositivo y las guarda |
| `insteon/properties/reset` | `confirm` | — | descarta las propiedades pendientes |
| `insteon/properties/write` | `confirm` | — | escribe en el dispositivo las propiedades pendientes |
| `insteon/scene/delete` | `confirm` | — | borra una escena Insteon (escribe en los dispositivos) |
| `insteon/scene/get` | `read` | — | una escena Insteon; solo lee |
| `insteon/scene/save` | `confirm` | — | crea o cambia una escena Insteon (escribe en los dispositivos) |
| `insteon/scenes/get` | `read` | — | escenas Insteon; solo lee |
| `knx/create_device` | `confirm` | — | crea un dispositivo KNX en el registro |
| `knx/create_entity` | `confirm` | — | crea una entidad KNX |
| `knx/delete_entity` | `confirm` | — | borra una entidad KNX |
| `knx/delete_expose` | `confirm` | — | borra una exposición |
| `knx/get_base_data` | `read` | — | estado de la conexión KNX y datos del proyecto; solo lee |
| `knx/get_entities_by_group` | `read` | — | entidades por dirección de grupo; solo lee |
| `knx/get_entity_config` | `read` | — | configuración de una entidad KNX; solo lee |
| `knx/get_expose_config` | `read` | — | configuración de una exposición; solo lee |
| `knx/get_expose_groups` | `read` | — | exposiciones configuradas; solo lee |
| `knx/get_knx_project` | `read` | — | proyecto ETS cargado (grande); solo lee |
| `knx/get_schema` | `read` | — | esquema de una plataforma; solo lee |
| `knx/get_time_server_config` | `read` | — | configuración del servidor de hora; solo lee |
| `knx/group_monitor_info` | `read` | — | telegramas recientes del monitor de grupo; solo lee |
| `knx/group_telegrams` | `read` | — | último telegrama de cada dirección de grupo; solo lee |
| `knx/project_file_process` | `deny` | — | necesita subir un fichero y la contraseña del proyecto ETS |
| `knx/project_file_remove` | `confirm` | — | quita el proyecto ETS cargado |
| `knx/query_telegrams` | `read` | — | telegramas guardados con filtros; solo lee |
| `knx/subscribe_telegrams` | `deny` | — | suscripción/streaming sin primer mensaje con el estado: MCP es petición-respuesta |
| `knx/update_entity` | `confirm` | — | cambia una entidad KNX |
| `knx/update_expose` | `confirm` | — | crea o cambia una exposición (envía telegramas al bus) |
| `knx/update_time_server_config` | `confirm` | — | cambia el servidor de hora KNX (envía telegramas al bus) |
| `knx/validate_entity` | `read` | — | valida una configuración de entidad sin guardarla |
| `knx/validate_expose` | `read` | — | valida una configuración de exposición sin guardarla |
| `lcn/devices` | `read` | — | módulos LCN configurados; solo lee |
| `lcn/devices/add` | `confirm` | — | añade un módulo LCN |
| `lcn/devices/delete` | `confirm` | — | quita un módulo LCN y sus entidades |
| `lcn/devices/scan` | `confirm` | — | escanea el bus LCN y añade a la configuración los módulos encontrados |
| `lcn/entities` | `read` | — | entidades LCN configuradas; solo lee |
| `lcn/entities/add` | `confirm` | — | añade una entidad LCN |
| `lcn/entities/delete` | `confirm` | — | quita una entidad LCN |
| `lorawan/devices/list` | `read` | — | dispositivos LoRaWAN y sus conexiones; solo lee |
| `lorawan/devices/subscribe` | `deny` | — | suscripción; los mismos datos los da lorawan/devices/list |
| `mobile_app/push_notification_channel` | `deny` | — | canal de notificaciones de la app móvil: suplantaría el de la app y necesita su webhook_id |
| `mobile_app/push_notification_confirm` | `deny` | — | protocolo interno de la app móvil (necesita su webhook_id) |
| `modbus/connections/list` | `read` | — | conexiones Modbus y sus unidades; solo lee |
| `notify/html5/appkey` | `read` | — | clave PÚBLICA VAPID de las notificaciones HTML5 (la privada no sale); solo lee |
| `sendspin/get_pairing_token` | `deny` | — | devuelve el token de emparejamiento Sendspin (secreto de larga duración) |
| `sendspin/subscribe_clients` | `deny` | — | suscripción que solo sirve para pedir tokens de emparejamiento |
| `ssdp/subscribe_discovery` | `deny` | — | un mensaje por dispositivo: leer solo el primero daría una lista incompleta |
| `wyoming/info` | `read` | — | servicios Wyoming (STT, TTS, wake word) de cada entrada; solo lee |
| `zeroconf/subscribe_discovery` | `deny` | — | un mensaje por servicio: leer solo el primero daría una lista incompleta |

## R-2 Suscripciones: cuáles son «de un solo mensaje»

**Decisión**: `read` con `one_shot` solo si el handler manda, SIEMPRE y justo
tras el resultado, UN evento con el estado completo y no hay un comando de
lectura que dé lo mismo. Son cinco:

| Comando | Primer mensaje |
|---|---|
| `zwave_js/subscribe_controller_statistics` | `send_result` y un `event_message` con las estadísticas del controlador |
| `zwave_js/subscribe_node_statistics` | ídem, del nodo |
| `bluetooth/subscribe_advertisements` | un evento `add` con todos los anuncios acumulados (aunque la lista esté vacía) |
| `dhcp/subscribe_discovery` | un evento `add` con todas las direcciones conocidas |
| `insteon/aldb/notify_all` | un evento `status` con `is_loading` |

**Descartadas**, con su porqué:

- Un evento por elemento (el `one_shot` leería solo el primero):
  `bluetooth/subscribe_scanner_state`, `ssdp/subscribe_discovery`,
  `zeroconf/subscribe_discovery`.
- Evento solo si hay datos (sin datos, la lectura acabaría en error de plazo,
  no en una lista vacía; la respuesta mentiría): `bluetooth/
  subscribe_connection_allocations`, `bluetooth/subscribe_scanner_details`,
  `zwave_js/subscribe_rebuild_routes_progress`,
  `zwave_js/subscribe_firmware_update_status`.
- Redundantes: `matter/subscribe_network_topology` (= `matter/
  network_topology`), `lorawan/devices/subscribe` (= `lorawan/devices/list`).
- Sin primer mensaje: el resto de `subscribe_*`, `insteon/aldb/notify`,
  `mqtt/subscribe`, `knx/subscribe_telegrams`; `sendspin/subscribe_clients`
  solo sirve para pedir tokens de emparejamiento (`deny`).

**Alternativas**: dejar todas en `deny` (pierde las estadísticas de Z-Wave,
que ningún otro comando da) o aceptar las condicionales (el error de plazo
diría «fallo» cuando la verdad es «no hay nada»; principio V).

## R-3 Desviaciones respecto a las notas de CAP de la research de la 008

FR-089 manda sobre la nota orientativa de cada CAP. Donde no coinciden:

| CAP | Nota de la 008 | Decisión | Por qué |
|---|---|---|---|
| CAP-100 | `refresh_node_*` con 2P | `refresh_node_values` y `refresh_node_cc_values` `confirm`; `refresh_node_info` `deny` | este último deja una suscripción de progreso abierta (R-1) |
| CAP-101 | `permit` y `reconfigure` con 2P | `deny` | suscripción que la genérica no cierra; `permit` además deja el modo depuración y acepta claves de enlace. Para permitir uniones existe la acción `zha.permit` (`ha_call_service`) |
| CAP-102 | `open_commissioning_window` con 2P | `deny` | devuelve el código de emparejamiento (secreto; FR-089) |
| CAP-103 | `discover_routers` por la genérica de lectura | `deny` | suscripción mDNS sin primer mensaje |
| CAP-103 | `get_dataset_tlv`: `deny` o redactado | `deny` | redactar el TLV dejaría la respuesta vacía |
| CAP-105 | `usb/scan` por la genérica | `read` | solo pide un escaneo; no configura nada |
| CAP-106 | `notify/html5/appkey` secreto, `deny` | `read` | devuelve la clave pública VAPID, no la privada |

Además, `matter/network_topology` y `zwave_js/network_neighbors`, que la 008 no
cita, quedan `read` y `confirm` respectivamente (R-1).

## R-4 El generador y la clase C

**Situación**: la regeneración EN SU SITIO conserva byte a byte cada entrada
cuya clave sigue en el inventario (`_leer_tabla_previa`), así que la revisión
de la 025 sobrevive a una versión nueva de HA sin cambiar nada. La generación
DESDE CERO (sin tabla previa) aplica `_clasificar`, que hoy da a toda fila de
clase C `deny` «pendiente de revisión (spec 025)»; tras la 025 no cuadraría
con la tabla.

**Decisión**: un módulo de datos nuevo, `scripts/inventario/clase_c.py`, con
`CLASE_C: dict[str, dict]` (comando → `category`, `reason` y, si las tiene,
`one_shot`, `redact_extra`, `open_world`, `example`). En `_clasificar`, la
rama de la clase C consulta el mapa: si la clave está, devuelve
`{**base, **CLASE_C[clave]}` (familia `generic_commands` y CAP del inventario
vienen de `base`); si no, `deny`. El texto del `deny` de lo no revisado es
«pendiente de revisión (spec 025)» mientras dura la 025 (tramos 1 y 2: el
test de la 011 sigue exigiéndolo en las integraciones aún no revisadas) y
«sin revisar» desde el tramo 3, para que el test de «sin revisar» nombre
cualquier fila C nueva de una versión futura. Un test nuevo de
`tests/test_generar_tabla.py` genera desde cero con los inventarios reales y
compara, en cada fila de clase C, `category`, `reason`, `family`, `tool`,
`cap`, `one_shot`, `redact_extra`, `open_world` y `example` con la tabla
real. `_render` ya escribe todas esas marcas.

**Por qué un módulo aparte y no `_DEDICADAS_INICIALES`**: ese mapa solo
admite tools o `deny`, no `read`/`confirm` con marcas, y 192 entradas
enterrarían el resto de `generar_tabla.py`. El módulo solo lo importa el
generador (fuera de `hermes/src`).

**Alternativas**: (a) dejar que desde cero salga «pendiente» como las de
clase A de vía T salen PROVISIONALES (precedente de la 011): rechazado, el
supervisor pide que desde cero cuadre; (b) añadir columnas al inventario TSV:
obliga a cambiar el extractor y mezcla la clasificación de Hermes con el
inventario de HA.

## R-5 Redacción de objetos con `redact_extra` (hallazgo H-1)

**Hallazgo H-1**: `redact_structure` (security.py) y `_redactar`
(generic_commands.py) recorren diccionarios y listas y SOLO sustituyen valores
escalares bajo una clave sensible. Con `{"network_key": {"key": "…",
"tx_counter": 1}}` la clave `network_key` es sensible, pero su valor es un
objeto: se recorre, `key` no es sensible y la clave de red sale en claro. Es
justo la forma de `zha/network/settings` y de los backups de zigpy
(`network_info.network_key`, `tc_link_key`, `key_table[]` y
`stack_specific.{ezsp,zstack,…}` con material de claves que depende de la
radio).

**Decisión**: en `_redactar` de las genéricas, si la clave está en
`redact_extra` y el valor es un objeto o una lista, se devuelve
`***REDACTED***` entero, antes de recorrerlo. Los escalares siguen como hoy
(texto no vacío y números tapados; cadena vacía y `None`, tal cual). Así `redact_extra=(
"network_key", "tc_link_key", "key_table", "stack_specific")` tapa todo lo
sensible de ZHA sin conocer la estructura interior de cada radio. La única
entrada actual con `redact_extra` (`logbook/get_action_calls`, `code`) recibe
escalares: no cambia. Test con control negativo (volver al recorrido → cae el
centinela de `stack_specific`).

**Ampliación (D-2, decisión del supervisor al validar la spec)**: el mismo
criterio se aplica a `redact_structure` (security.py) y a sus copias locales
(`_limpio` de `device_automation` y `system_status`): si la clave es sensible
por nombre, el valor ENTERO, sea texto, número, objeto o lista (`None`,
booleanos y vacíos se conservan; `security.tapar_entero`). En el tramo 1 se
vio además que las claves S0/S2 de Z-Wave (`s0_legacy_key`, `s2_*_key`,
`lr_s2_*_key`, opciones de la app Z-Wave JS según `zwave_js/const.py`) no
contenían ningún marcador: se añaden a `_SENSITIVE_KEY_MARKERS`. La suite
entera no cambió ningún resultado de tools existentes con el arreglo.

## R-6 Entradas que tapan secretos y sus centinelas

| Entrada | Dónde va el secreto | Cómo se tapa | Centinela del test |
|---|---|---|---|
| `zwave_js/get_provisioning_entries` | `[].dsk` | `redact_extra=("dsk",)` | `"12345-centinela-025"` |
| `zha/network/settings` | `settings.network_info.network_key.key`, `tc_link_key.key`, `key_table[].key`, `stack_specific.*` | `redact_extra` de cuatro claves (R-5) | uno distinto en cada sitio |
| `zha/network/backups/list` | ídem por cada copia | ídem | ídem |
| `zha/network/backups/create` | `backup.network_info.*` | ídem | ídem |
| `zha/configuration` y `zha/configuration/update` | `data.zha_alarm_options.alarm_master_code` (respuesta y carga) | `redact_extra=("alarm_master_code",)` (hallazgo del tramo 2) | código centinela de ocho dígitos |
| `otbr/info` | `<ext_addr>.active_dataset_tlvs` | `redact_extra=("active_dataset_tlvs",)` | TLV hex centinela |
| `insteon/config/get` | `modem_config.password` | marcador `password` (sin `redact_extra`) | `"centinela-025"` |
| `mqtt/device/debug_info` | `entities[].discovery_data.payload.code`, `entities[].transmitted[].messages[].payload` | `redact_extra=("code", "transmitted")` | código de alarma centinela en los dos sitios |

Cada test recorre la respuesta de la genérica y el log capturado
(`structlog.testing.capture_logs`) y comprueba que el centinela no aparece en
ninguno (SC-008 de la 008).

## R-7 Guía

**Decisión**: cuatro temas nuevos en `_GUIDE`, uno por grupo de la 008:
`zwave` (alias `zwave_js`, `z-wave`, `z_wave`), `zigbee` (alias `zha`),
`matter_thread` (alias `matter`, `thread`, `otbr`) y `other_integrations`
(alias `mqtt`, `usb`, `bluetooth`, `knx`, `insteon`, `lcn`, `esphome`,
`dynalite`, `lorawan`, `modbus`, `wyoming`). Ningún alias choca con los
existentes (`integrations`, `discovery`, `network` y `devices` ya apuntan a
otros temas y no se tocan). Una línea por tema en el índice (`_OVERVIEW`, que
no tiene huella) y en la enumeración de temas de la descripción de
`hermes_guide`. No se tocan `generic_commands` ni ningún otro tema (sus huellas
siguen). Cada tema:

1. dice que todo va por `ha_read_ws_command` / `ha_call_ws_command` y que no
   existe con la familia `generic_commands` desactivada;
2. lista las lecturas más útiles con su carga y las escrituras en dos pasos;
3. lista lo rechazado agrupado por motivo;
4. da la vía alternativa: Z-Wave, las acciones `zwave_js.*`
   (`set_config_parameter`, `refresh_value`, `ping`) por `ha_call_service`;
   ZHA, `zha.permit` por `ha_call_service`; inclusión, commissioning y
   firmware, la UI de HA;
5. remite a `hermes_guide("generic_commands", search="<integración>")` para
   el resto.

Un test cruza los comandos citados en cada tema con la tabla: los que el
tema presenta como disponibles están en `read`/`confirm` y los que presenta
como rechazados, en `deny` (principio V).

## R-8 Banco

**Decisión**: ninguna integración de la clase C arranca en el banco de Core
sin hardware o red salvo, quizá, `usb` (lista puertos serie del sistema; en el
contenedor saldría vacía). El tramo 3 añade `usb:` a
`tests/banco/ha_config/configuration.yaml` y prueba por la genérica
`usb/list_serial_ports` y `usb/list_serial_integrations`. Si `usb` no arranca
en el contenedor (falta de `/sys` o de `pyudev`), es un HALLAZGO del banco:
`xfail` estricto que espera ese fallo, anotado. Todo lo demás se prueba con
unitarios (`ws_send` y `ws_one_shot_subscription` simulados) y queda en la
matriz de la 008 como «unitario; sin hardware en el banco».

`dynalite`, `wyoming`, `thread`, `html5` y `modbus` son de entrada de
configuración o necesitan red: no se intentan.

## R-9 Tramos

**Decisión**: tres tramos en vez de los dos de la 008.

| Tramo | Contenido | Entradas |
|---|---|---|
| 1 | Mecanismo (R-4, R-5, test progresivo de «pendiente») y Z-Wave JS; tema `zwave` | 55 |
| 2 | ZHA, Matter, Thread y OTBR; temas `zigbee` y `matter_thread` | 50 |
| 3 | MQTT, USB, Bluetooth y el resto de CAP-106; tema `other_integrations`; banco de `usb`; test final estricto; documentación | 87 |

Con dos tramos, el segundo tendría 137 entradas con sus tests y tres temas de
guía: demasiado para el contexto de un agente.
