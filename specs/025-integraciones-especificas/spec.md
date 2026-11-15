# Especificación: Hermes 1.2.0 — integraciones específicas por la tabla (sub-feature 025)

**Directorio de la spec**: `specs/025-integraciones-especificas`

**Creada**: 2026-11-15

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T024 de su `tasks.md` y cubre **CAP-100 a CAP-106**
(clase C: comandos de integraciones concretas) **solo por la tabla de
clasificación**, sin tools nuevas (FR-089 y FR-090 de la 008), más los
transversales que le tocan (FR-001, FR-002, FR-004, FR-005, FR-009, FR-011,
FR-015, FR-019…FR-021, FR-023 y FR-024 de la 008). Ola 3, tamaño M. La 008 la
estimaba en 2 tramos; con los 192 comandos reales leídos uno a uno sale en
**3 tramos** (plan.md, «Tramos»).

**Entrada**: `specs/008-cobertura-total/` (spec, plan con la matriz de
trazabilidad, research CAP-100…CAP-106 e `inventario/core-ws.tsv`), la
sub-feature 011 (`command_table.py`, `command_policy.py`,
`tools/generic_commands.py`, el generador `scripts/inventario/generar_tabla.py`
y sus tests), el banco de la 010, el código de Hermes (`ha.py`, `security.py`,
`tools/guide.py`) y el código de Home Assistant Core 2026.11.1 de cada
integración (`zwave_js/api.py`, `zha/websocket_api.py`, `matter/api.py`,
`thread/websocket_api.py`, `otbr/websocket_api.py`, `mqtt/__init__.py`,
`usb/__init__.py`, `bluetooth/websocket_api.py`, `dhcp`, `ssdp`, `zeroconf`,
`insteon/api/`, `knx/websocket.py`, `lcn/websocket.py`, `esphome`, `dynalite`,
`lorawan`, `mobile_app`, `modbus`, `html5`, `generic`, `wyoming`), leído sin
ejecutar nada. La clasificación comando a comando, con el handler leído y el
motivo, está en [research.md](research.md), R-1.

**Fuera de esta sub-feature**: tools dedicadas para Z-Wave o ZHA (la 008 las
deja como posibles, «si se quiere», y no las asigna a ninguna sub-feature;
DESCARTADAS por el supervisor al validar la spec, D-3); cualquier comando de clase A, B o D; el Supervisor
(ningún comando de clase C es del Supervisor).

## Clarificaciones

### Sesión 2026-11-15

Decididas con la 008 y el código de HA, sin preguntar (modo autónomo):

- P: ¿Tools dedicadas? → R: No. La 008 asigna CAP-100…CAP-106 a la vía «T»
  (tabla) y su plan dice «Tabla para toda la clase C». Las tools que CAP-100
  menciona «si se quiere» no son de ningún FR.
- P: Cuando FR-089 y la nota de una CAP de research de la 008 no coinciden,
  ¿cuál manda? → R: FR-089 (lo que devuelve secretos, borra la red, restaura
  firmware o necesita una acción física o un PIN, `deny`) y lo que hace el
  handler de verdad. Las desviaciones de las notas de CAP están listadas y
  justificadas en research.md, R-3 (p. ej. `matter/open_commissioning_window`
  devuelve el código de emparejamiento: `deny`, no 2P; `notify/html5/appkey`
  devuelve la clave PÚBLICA: `read`, no secreto).
- P: ¿Qué es «suscripción de un solo mensaje» (FR-089, FR-009 de la 008)? →
  R: La que manda SIEMPRE, justo tras el resultado, UN mensaje con el estado
  completo, y no hay otro comando de lectura con los mismos datos. Esas van
  en `read` con `one_shot`. Las que mandan un mensaje por elemento, solo si
  hay datos, o nada hasta que algo cambia, `deny`. Las redundantes con un
  comando de lectura, `deny` remitiendo a él (research.md, R-2).
- P: ¿Un comando de petición-respuesta que además registra una suscripción
  de progreso (eventos tras el resultado) puede ir en `confirm`? → R: No. La
  genérica usa `ws_send`, que no cierra la suscripción: quedaría abierta en la
  conexión compartida (FR-009 de la 008). Van a `deny` con ese motivo
  (`zwave_js/refresh_node_info`, `zha/devices/reconfigure`,
  `zha/devices/permit`…). Abrirlas exigiría cambiar la genérica: duda D-1.
- P: ¿Cómo se tapa un secreto que viene dentro de un objeto (la clave de red
  de ZHA viaja como `network_key: {"key": "…"}`)? → R: Hoy `redact_extra`
  solo tapa valores escalares bajo la clave; un objeto se recorre y su `key`
  interior sale en claro. Esta sub-feature cambia la redacción de las
  genéricas para que una clave de `redact_extra` tape su valor ENTERO, sea
  del tipo que sea (FR-008). Por decisión del supervisor (D-2), el mismo
  criterio se aplica también a `redact_structure` y a todas las claves
  sensibles por nombre (FR-008b).
- P: ¿Cuántos tramos? → R: Tres: (1) mecanismo y Z-Wave JS (55); (2) ZHA,
  Matter, Thread y OTBR (50); (3) el resto (87) y el cierre. Partir el tramo
  (b) de la 008 en dos deja cada tramo por debajo de 90 entradas.
- P: ¿Cómo cuadra el generador? → R: Un mapa de datos con la clasificación
  revisada de la clase C, fuera del paquete (`scripts/inventario/clase_c.py`),
  que la generación desde cero consulta; un test compara, en las 192 filas,
  la generación desde cero con la tabla real. La regeneración en su sitio ya
  conserva las entradas byte a byte (research.md, R-4).

## Escenarios de usuario y pruebas *(obligatorio)*

El usuario es un cliente MCP que administra una instalación con redes
de dispositivos (Z-Wave, Zigbee, Matter, Thread) o integraciones con panel
propio (KNX, Insteon, LCN…), y el mantenedor que revisa la tabla.

### Historia 1 — Diagnosticar y ajustar una red Z-Wave (Prioridad: P1)

El usuario pregunta por qué un nodo Z-Wave va lento o cómo cambiar un
parámetro de un dispositivo. El cliente lee el estado de la red y del nodo,
sus parámetros y sus estadísticas por `ha_read_ws_command`, y cambia un
parámetro o reconstruye las rutas del nodo por `ha_call_ws_command` en dos
pasos. Nunca puede incluir ni excluir nodos, ni reiniciar el controlador, ni
leer el DSK ni el PIN de S2.

**Por qué esta prioridad**: Z-Wave JS es la integración con más comandos (55)
y la de más valor de la clase C (CAP-100, prioridad media).

**Prueba independiente**: con la tabla del tramo 1 y `ws_send` simulado,
`zwave_js/network_status` se ejecuta por la genérica de lectura;
`zwave_js/set_config_parameter` devuelve vista previa y token y solo con el
token llega a HA; `zwave_js/hard_reset_controller` se rechaza sin llamar a HA.

**Escenarios de aceptación**:

1. **Dado** un `entry_id` de Z-Wave JS, **Cuando** el cliente pide
   `ha_read_ws_command("zwave_js/network_status", {"entry_id": …})`,
   **Entonces** recibe el estado del cliente, del controlador y de los nodos.
2. **Dado** un nodo, **Cuando** pide `zwave_js/subscribe_node_statistics`,
   **Entonces** recibe UN mensaje de estadísticas y la suscripción se cancela
   (no queda abierta).
3. **Dado** un nodo, **Cuando** pide `ha_call_ws_command(
   "zwave_js/set_config_parameter", {...})` sin token, **Entonces** recibe
   vista previa con el motivo de la tabla y un token, y HA no recibe nada.
4. **Dado** cualquier comando de inclusión, SmartStart, NVM, firmware,
   reset o `invoke_cc_api`, **Cuando** se pide por cualquier genérica,
   **Entonces** se rechaza con `command_denied` y su motivo, sin llamar a HA.
5. **Dado** un nodo preaprovisionado, **Cuando** el cliente lee
   `zwave_js/get_provisioning_entries`, **Entonces** el `dsk` sale tapado.

---

### Historia 2 — Gestionar Zigbee (ZHA) sin poner en riesgo la red (Prioridad: P1)

El usuario quiere ver sus dispositivos y grupos Zigbee, vincular un mando a
una bombilla o crear un grupo. El cliente lee por la genérica de lectura y
escribe en dos pasos. Puede leer los ajustes de la red y sus copias, pero las
claves de red y de enlace salen tapadas; nunca restaura una copia ni cambia
de canal.

**Por qué esta prioridad**: ZHA es la segunda integración de la clase C
(CAP-101, prioridad media) y sus lecturas de red llevan la clave de la red.

**Prueba independiente**: `zha/network/settings` con una respuesta simulada
que lleva una clave centinela en `network_info.network_key.key`, en
`tc_link_key`, en `key_table` y en `stack_specific`: ninguna aparece en la
respuesta de la genérica.

**Escenarios de aceptación**:

1. **Dado** ZHA cargado, **Cuando** el cliente pide `zha/devices`, **Entonces**
   recibe la lista de dispositivos.
2. **Dado** dos IEEE, **Cuando** pide `zha/devices/bind`, **Entonces** va en
   dos pasos con vista previa.
3. **Dado** la red Zigbee, **Cuando** pide `zha/network/settings` o
   `zha/network/backups/list`, **Entonces** el canal y el PAN salen y las
   claves salen tapadas enteras, también las que vienen dentro de objetos.
4. **Dado** `zha/network/backups/restore`, `zha/network/change_channel` o
   `zha/devices/permit`, **Entonces** se rechaza con su motivo; el de
   `permit` remite a la acción `zha.permit` por `ha_call_service`.

---

### Historia 3 — Matter y Thread sin exponer credenciales (Prioridad: P2)

El usuario quiere saber la topología de su red Matter/Thread, diagnosticar un
nodo o elegir el dataset Thread preferido. Puede leer y reentrevistar; nunca
obtiene la clave de red Thread, un código de emparejamiento Matter ni la
contraseña Wi-Fi, ni crea o cambia la red.

**Por qué esta prioridad**: CAP-102 y CAP-103 son de prioridad baja, pero son
las de secretos más delicados (claves de red, códigos de emparejamiento).

**Prueba independiente**: `otbr/info` con un `active_dataset_tlvs` centinela
no lo devuelve; `thread/get_dataset_tlv` y `matter/open_commissioning_window`
se rechazan sin llamar a HA.

**Escenarios de aceptación**:

1. **Dado** Matter, **Cuando** el cliente pide `matter/network_topology` o
   `matter/node_diagnostics`, **Entonces** los recibe.
2. **Dado** un dataset, **Cuando** pide `thread/set_preferred_dataset`,
   **Entonces** va en dos pasos.
3. **Dado** `otbr/info`, **Entonces** el dataset activo sale tapado.
4. **Dado** cualquier comando que devuelve o introduce una clave de red, un
   código de emparejamiento o una contraseña, **Entonces** `command_denied`.

---

### Historia 4 — El resto de integraciones por la genérica (Prioridad: P2)

El usuario de KNX, Insteon, LCN, MQTT, ESPHome, USB, Bluetooth, Dynalite o
LoRaWAN pide lo que hoy solo hace su panel: ver los telegramas KNX, los
enlaces de un dispositivo Insteon, los mensajes MQTT de un dispositivo, los
puertos serie o los equipos vistos por DHCP. Lee por la genérica y escribe en
dos pasos lo que se puede escribir con seguridad; las claves de ESPHome, los
tokens de Sendspin y lo que necesita subir ficheros o pulsar un botón, nunca.

**Por qué esta prioridad**: 87 comandos de baja prioridad (CAP-104…CAP-106),
cada uno útil a pocos usuarios.

**Prueba independiente**: `insteon/config/get` con una contraseña centinela
no la devuelve; `esphome/get_encryption_key` se rechaza; `dhcp/
subscribe_discovery` usa la lectura de un solo mensaje.

**Escenarios de aceptación**:

1. **Dado** un dispositivo MQTT, **Cuando** el cliente pide
   `mqtt/device/debug_info`, **Entonces** recibe sus topics y los mensajes
   recibidos; el `code` y los mensajes enviados salen tapados.
2. **Dado** Insteon, **Cuando** pide `insteon/aldb/write`, **Entonces** va en
   dos pasos.
3. **Dado** `insteon/config/get` de un hub con contraseña, **Entonces** la
   contraseña sale tapada; `insteon/config/get_modem_schema` (que la lleva
   como valor por defecto) se rechaza.
4. **Dado** `esphome/get_encryption_key` o `sendspin/get_pairing_token`,
   **Entonces** `command_denied`.

---

### Historia 5 — La guía dice qué se puede y qué no, por integración (Prioridad: P1)

El cliente pregunta a `hermes_guide` cómo trabajar con Z-Wave, Zigbee,
Matter/Thread o el resto. Cada tema dice qué se hace por la genérica (con los
comandos más útiles y sus cargas), qué está rechazado y por qué, y qué se hace
por otra vía (la acción `zha.permit`, las de `zwave_js.*`, la UI). Los temas
existentes no cambian.

**Por qué esta prioridad**: FR-090; sin la guía, el cliente no sabe que estos
comandos existen ni cómo se llaman.

**Prueba independiente**: los cuatro temas y sus alias existen, nombran sus
comandos y no prometen nada que la tabla rechace; las huellas de los temas
existentes siguen iguales.

**Escenarios de aceptación**:

1. **Dado** `hermes_guide("zwave")` (o `zwave_js`, `z-wave`), **Entonces**
   lista lecturas y escrituras con cargas de ejemplo y lo rechazado.
2. **Dado** un comando que la guía cita como disponible, **Entonces** la tabla
   lo tiene en `read` o `confirm`; uno que cita como rechazado, en `deny`.
3. **Dado** `hermes_guide("generic_commands", search="zha")`, **Entonces**
   lista las 28 entradas de ZHA con su categoría y, si la tiene, su ejemplo.

---

### Historia 6 — La tabla queda cerrada y el generador cuadra (Prioridad: P1)

El mantenedor regenera la tabla (en su sitio o desde cero) y obtiene la misma
clasificación de la clase C. No queda ninguna entrada «pendiente de revisión
(spec 025)».

**Por qué esta prioridad**: FR-001, FR-002 y FR-005 de la 008; sin esto, la
próxima versión de HA desharía la revisión.

**Prueba independiente**: test que falla si queda alguna entrada con
«spec 025» en su motivo, en la tabla o en una generación desde cero; test que
compara la generación desde cero con la tabla en las 192 filas.

**Escenarios de aceptación**:

1. **Dado** el final del tramo 3, **Entonces** ninguna entrada de la tabla ni
   de una generación desde cero dice «spec 025».
2. **Dado** el generador sin tabla previa, **Entonces** cada fila de clase C
   sale con la misma categoría, motivo y marcas que la tabla revisada.
3. **Dado** una fila de clase C nueva (de otra versión de HA), **Entonces**
   entra como `deny` «sin revisar» y el test de «sin revisar» la nombra.

### Casos límite

- Un comando `read` de una integración que no está cargada: HA responde con
  error (`not_found`, `not_loaded`); la genérica lo devuelve como
  `ha_command_failed` con `ha_code` (comportamiento de la 011, sin cambios).
- Una lectura `one_shot` cuyo primer mensaje no llega en plazo: error de plazo
  y la suscripción se cancela igual (comportamiento de la 011). Por eso solo
  van en `one_shot` las que mandan siempre un mensaje.
- `zha/topology/update` no responde nunca: `deny` (la genérica esperaría
  hasta el plazo).
- `zwave_js/network_neighbors` apaga la radio mientras lee: `confirm`, con el
  motivo que lo dice, aunque solo lea.
- `insteon/config/get` lleva `password`: lo tapa el marcador `password` de
  `redact_structure`, sin `redact_extra`; el centinela lo comprueba.
- Respuestas grandes (`knx/get_knx_project`, `bluetooth/subscribe_advertisements`):
  el tope central de las genéricas las recorta y lo dice (FR-008 de la 008).
- Una carga de escritura con un valor sensible por nombre (p. ej. una clave):
  la vista previa lo tapa (comportamiento de la 011). Ninguna entrada
  `confirm` de esta sub-feature tiene un secreto como carga esperada.
- Los motivos de los `deny` no llevan valores de la carga (FR-003 de la 008).

## Requisitos *(obligatorio)*

### Requisitos funcionales

Cada uno cita su FR y su CAP de la 008. La clasificación exacta de cada
comando (categoría, marcas y texto del motivo) es la de research.md, R-1, y
forma parte de estos requisitos.

#### Clasificación por integración (FR-089 de la 008)

- **FR-001**: Los 55 comandos `zwave_js/*` quedan clasificados como dice
  research.md R-1: 18 `read` (dos de ellos `one_shot` y uno de mundo abierto),
  13 `confirm` (uno de mundo abierto) y 24 `deny` (inclusión, exclusión, S2,
  SmartStart, DSK, nodos fallidos, reset y NVM del controlador, firmware,
  `invoke_cc_api` y suscripciones). `get_provisioning_entries` tapa `dsk`
  (CAP-100; FR-089, FR-019).
- **FR-002**: Los 28 comandos `zha/*` quedan clasificados como dice R-1: 13
  `read`, 10 `confirm` y 5 `deny`. `network/settings`, `network/backups/list`
  y `network/backups/create` tapan `network_key`, `tc_link_key`, `key_table`
  y `stack_specific` enteros; `configuration` y `configuration/update`
  tapan `alarm_master_code` (hallazgo del tramo 2) (CAP-101; FR-089, FR-019).
- **FR-003**: Los 11 comandos `matter/*` quedan como dice R-1: 3 `read`, 1
  `confirm` (`interview_node`) y 7 `deny` (commissioning, código de
  emparejamiento, fabric, dataset Thread, Wi-Fi y la suscripción redundante)
  (CAP-102; FR-089, FR-019).
- **FR-004**: Los 7 `thread/*` y los 4 `otbr/*` quedan como dice R-1: 2
  `read`, 2 `confirm` y 7 `deny`. Ninguna respuesta de Hermes contiene la
  clave de red Thread: `thread/get_dataset_tlv` es `deny` y `otbr/info` tapa
  `active_dataset_tlvs` (CAP-103; FR-089, FR-019).
- **FR-005**: `mqtt/*`, `usb/*` y `bluetooth/*` quedan como dice R-1: 5 `read`
  (una `one_shot`) y 4 `deny`. `mqtt/device/debug_info` tapa el `code` del
  descubrimiento y la lista entera de mensajes enviados (`transmitted`), donde
  puede viajar el código de una alarma o una cerradura (CAP-104, CAP-105;
  FR-089, FR-019).
- **FR-006**: Los 78 comandos de CAP-106 (Insteon, KNX, LCN, ESPHome y
  Sendspin, Dynalite, LoRaWAN, descubrimiento DHCP/SSDP/zeroconf, app móvil,
  Modbus, HTML5, cámara genérica, Wyoming) quedan como dice R-1: 32 `read`
  (dos `one_shot`), 31 `confirm` y 15 `deny` (CAP-106; FR-089, FR-019).

#### Criterios comunes (FR-089, FR-009 y FR-019 de la 008)

- **FR-007**: Toda entrada de clase C cumple: (a) `read` solo si el handler
  solo lee, sin secretos en la respuesta o con ellos tapados por la tabla, y
  con `open_world` si sale a internet; (b) `confirm` para escrituras que la
  genérica puede hacer con seguridad en dos pasos; (c) `deny` para lo que
  devuelve o introduce secretos, borra o reemplaza la red o la NVM, toca
  firmware, necesita una acción física, un PIN o subir un fichero, no responde,
  o deja una suscripción abierta; (d) suscripciones en `deny` salvo las de un
  solo mensaje de R-2, que van en `read` con `one_shot`. Cada motivo es
  concreto (dice qué hace o por qué se rechaza) y ningún motivo dice «pendiente»
  (CAP-100…CAP-106; FR-089, FR-009).
- **FR-008**: En las respuestas de las cuatro genéricas, una clave de
  `redact_extra` tapa su valor ENTERO con `***REDACTED***` también cuando es
  un objeto o una lista; ninguna clave interior de ese valor sale. Los
  escalares bajo esas claves y lo que no está en `redact_extra` se redactan
  como hoy (la cadena vacía y `null` se conservan). La única entrada actual con
  `redact_extra` (`logbook/get_action_calls`, `code`) sigue igual (FR-019,
  FR-020 de la 008; principio II).
- **FR-008b** (decisión D-2 del supervisor): `redact_structure` y las
  redacciones locales que la copian (`_redactar` de las genéricas, `_limpio`
  de `device_automation` y `system_status`) tapan ENTERO el valor de una
  clave sensible por nombre, sea texto, número, objeto o lista; `None`, los
  booleanos y lo vacío se conservan. Las claves S0/S2 de Z-Wave JS
  (`s0_legacy_key`, `s2_access_control_key`, `s2_authenticated_key`,
  `s2_unauthenticated_key` y las `lr_s2_…`) son marcadores sensibles. Test
  con control negativo y centinelas con la forma real de la clave de red de
  ZHA y de las claves de Z-Wave (FR-019, FR-020 de la 008; principio II).
- **FR-009**: Cada entrada `read` o `confirm` nueva tiene un test de
  clasificación que la nombra; cada entrada que tapa un secreto, un test con
  valor centinela de extremo a extremo por la genérica (respuesta y log); cada
  `one_shot`, un test de que se ejecuta con la lectura de un solo mensaje
  (FR-019, FR-009 de la 008; SC-002, SC-008).
- **FR-010**: Las tres lecturas `zwave_js/*_firmware_update_*` que contienen
  el verbo `update` y solo leen son excepciones explícitas del test de verbos,
  con su justificación en el test y un comentario en la tabla (FR-004 de la
  008; SC-003).

#### Tabla y generador (FR-001, FR-002 y FR-005 de la 008)

- **FR-011**: Al terminar, ninguna entrada de la tabla, ni de una generación
  desde cero con los inventarios reales, tiene «spec 025» en su motivo. Un test
  lo comprueba y nombra cada una (FR-002 de la 008; SC-001).
- **FR-012**: La generación desde cero de la tabla da, en cada una de las 192
  filas de clase C, la misma categoría, motivo, familia, CAP y marcas
  (`one_shot`, `redact_extra`, `open_world`, `example`) que la tabla revisada;
  una fila de clase C que no está en el mapa revisado sale `deny` «sin
  revisar». La regeneración en su sitio sigue conservando cada entrada byte a
  byte. Un test compara las 192 filas (FR-001, FR-002, FR-005 de la 008).

#### Guía (FR-090 y FR-011 de la 008)

- **FR-013**: `hermes_guide` tiene cuatro temas nuevos: `zwave` (CAP-100),
  `zigbee` (CAP-101), `matter_thread` (CAP-102, CAP-103) y
  `other_integrations` (CAP-104…CAP-106), con alias por integración. Cada
  tema dice que va por las genéricas (y que no existe si la familia
  `generic_commands` está desactivada), lista los comandos más útiles con su
  carga, lo rechazado con su porqué, la vía alternativa cuando la hay y cómo
  buscar el resto con `search=`. El índice los nombra. Ningún tema cita como
  disponible un comando que la tabla no tenga en `read`/`confirm` (test).
  Los temas existentes no cambian: sus huellas siguen iguales (FR-090, FR-011
  de la 008; principio V).
- **FR-014**: Los ejemplos de carga de R-1 van en la tabla (`example=`), con
  datos ficticios, y la búsqueda de la guía los enseña (FR-011 de la 008).

#### Transversales

- **FR-015**: Ninguna tool nueva, ninguna familia nueva y ninguna anotación
  cambia: las genéricas siguen anunciando mundo abierto porque ya lo hacían, y
  `TestMundoAbierto` incluye la lectura nueva de mundo abierto (FR-010,
  FR-018, FR-020 de la 008).
- **FR-016**: Banco: lo que pueda cargarse sin hardware ni red en el banco de
  Core se ejecuta allí por la genérica (`usb/list_serial_ports` y
  `usb/list_serial_integrations` si `usb:` arranca en el contenedor); lo demás
  se prueba con unitarios y queda anotado como no ejecutable en el banco, con
  su motivo, en la matriz de la 008 (FR-015 de la 008; principio VI).
- **FR-017**: Documentación en el mismo cambio: sección «Integraciones
  específicas» en `## [1.2.0]` de `hermes/CHANGELOG.md`; estado de la 025 en
  la tabla del programa de `docs/HOJA-DE-RUTA.md` y la prueba con hardware en
  sus «Pruebas manuales pendientes»; filas CAP-100…CAP-106 de la matriz de la
  008 con sus tests; la viñeta de las genéricas de `SECURITY.md`
  dice que `redact_extra` tapa el valor entero y que los secretos de las
  integraciones se rechazan o se tapan. README y DOCS no cambian (no hay
  tools ni opciones nuevas) (FR-021, FR-023, FR-024 de la 008).

### Entidades clave

- **Entrada de la tabla** (`Entrada` de `command_policy.py`): categoría,
  motivo, familia `generic_commands`, CAP y marcas. Sin campos nuevos.
- **Mapa revisado de la clase C** (`scripts/inventario/clase_c.py`): comando →
  categoría, motivo y marcas; solo lo lee el generador.
- **Tema de la guía**: texto estático en `_GUIDE` con alias.

## Criterios de éxito *(obligatorio)*

- **SC-001**: 192 de 192 comandos de clase C clasificados con motivo concreto;
  0 «pendiente de revisión (spec 025)» en la tabla y en una generación desde
  cero. Recuento final: 73 `read`, 57 `confirm`, 62 `deny`.
- **SC-002**: 0 valores centinela (claves de red Zigbee/Thread, DSK,
  contraseña del hub Insteon, código de alarma MQTT, código maestro de la
  alarma de ZHA) en respuestas, vistas previas, errores o log de las
  genéricas en los tests de las nueve entradas que tapan secretos (siete al
  especificar; el tramo 2 añadió `zha/configuration` y
  `zha/configuration/update`; el tramo 3, al releer los handlers, ninguna).
- **SC-003**: 130 de 130 entradas `read`/`confirm` nuevas nombradas por un
  test de clasificación; 5 de 5 `one_shot` probadas con la lectura de un solo
  mensaje.
- **SC-004**: 0 comandos `hassio/*` o `supervisor/*` en `read` o `confirm`
  (ninguno es de clase C; `TestProxyDelSupervisor` sigue en verde).
- **SC-005**: 192 de 192 filas de clase C iguales entre la generación desde
  cero y la tabla.
- **SC-006**: 4 temas nuevos; 0 huellas de temas existentes cambiadas.
- **SC-007**: la suite termina con exactamente los 6 fallos conocidos de
  Windows tras cada tramo, y el CI de Linux (tests, banco, Semgrep, CodeQL) en
  verde.

## Supuestos

- La base de la rama tiene la 011 entera, la 009, la 010 y la 033
  (`feat/cobertura-total` en `806a764`, 307 tools).
- Los handlers de HA Core 2026.11.1 leídos en `fuentes/core` son los del
  banco y los de la versión con la que se publica la tabla.
- El token de Hermes es de administrador (casi todos estos comandos piden
  `require_admin`).
- Ninguna de estas integraciones carga en el banco sin hardware o red salvo,
  quizá, `usb`; si `usb:` no arranca en el contenedor, se anota y queda en
  unitarios.

## Dudas para el final

- **D-1** (queda para el final, decisión del supervisor): Varias escrituras útiles registran una suscripción de progreso
  (`zwave_js/refresh_node_info`, `zha/devices/reconfigure`,
  `zha/devices/permit`) y quedan en `deny` porque la genérica no la cierra.
  ¿Merece la pena una marca nueva de la tabla («cerrar tras el resultado»)
  en otra sub-feature?
- **D-2** — RESUELTA por el supervisor: SÍ, se corrige `redact_structure`
  globalmente en el tramo 1 (FR-008b).
- **D-3** — RESUELTA por el supervisor: DESCARTADAS. La genérica cubre lo
  mismo; no van a la hoja de ruta.
