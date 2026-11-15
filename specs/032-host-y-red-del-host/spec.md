# Especificación: Hermes 1.2.0 — host y red del host (sub-feature 032)

**Directorio de la spec**: `specs/032-host-y-red-del-host`

**Creada**: 2026-11-15

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T021 de su `tasks.md` y cubre **CAP-086** (host y OS:
escritura) y **CAP-090** (red del host: escritura) con tools dedicadas, que son
**FR-081** y **FR-082** de la 008. Depende de la 013 (lecturas del host y del
OS, `sv_get_os_info`, `sv_get_swap`; la red se lee por la tabla), de la 011
(tabla, genéricas y familias), de la 014 (matriz y procedimiento del
Supervisor) y de la 033 (inventario de argumentos atados al token). El tramo 2
necesita además el **HMAC del `action_hash`** de la 019 (research R-9).

**Entrada**: `specs/008-cobertura-total/` (spec FR-081, FR-082 y transversales
FR-010, FR-012, FR-016, FR-018…FR-021, FR-023, FR-024; plan con la matriz de
trazabilidad; research CAP-085, CAP-086, CAP-089, CAP-090;
`inventario/supervisor-rutas.tsv`), el código de Hermes (`tools/supervisor.py`
con `sv_get_host_info` y `sv_reboot_host` de la 1.1.2; `tools/host_system.py`
de la 013; `command_table.py`, `tool_families.py`, `security.py`,
`tools/_annotations.py`, `tools/guide.py`), la spec 022 en curso (control de
Core y Supervisor, que no toca el host) y la 019 (montajes, `security.py` con
HMAC). Contrastado con el código del Supervisor 2026.11.0
(`supervisor/api/__init__.py`, `api/host.py`, `api/os.py`, `api/network.py`,
`host/control.py`, `host/network.py`, `host/const.py`, `os/manager.py`,
`dbus/network/setting/generate.py`).

## Clarificaciones

### Sesión 2026-11-15

Decisiones vinculantes del programa (ya están en la 008):

- CAP-086 y CAP-090 van por **tools dedicadas** (vía D): las siete rutas
  `POST /host/shutdown`, `/host/options`, `/os/config/swap`, `/os/boot-slot`,
  `/network/reload`, `/network/interface/{interface}/update` y
  `/network/interface/{interface}/vlan/{vlan}` pasan de `deny` «pendiente de
  tool dedicada (spec 032)» a `dedicated`.
- Apagar el host es **clase A** en el inventario (no D): se ofrece, con
  confirmación y el aviso de que **nadie puede encenderlo a distancia**
  (FR-081). La ranura de arranque avisa de que **reinicia en el OS anterior**.
- Editar una interfaz **nunca** sobre la interfaz por la que entra Hermes,
  porque el Supervisor no revierte solo (FR-082).
- Las tools nuevas van en **familias nuevas** de la 1.2.0 (FR-010 de la 008).
- Las `sv_*` nuevas se prueban con el **Supervisor simulado** y van a la matriz
  de la 014 como **VM / pendiente** (FR-016 de la 008).
- Las lecturas de red (`GET /network/info`, `/network/interface/{i}/info`,
  `/accesspoints`) son de la 013 y siguen `read` por `sv_read_api`; las del
  host y del OS (`sv_get_host_info`, `sv_get_os_info`, `sv_get_swap`) ya
  existen. No se duplican: las tools de esta sub-feature las leen por dentro
  para la vista previa.

Decisiones tomadas al especificar (no había a quién preguntar; se justifican
en [research.md](research.md)):

- P: ¿Una familia o dos? → R: **dos**: `host_control` (apagar, hostname, swap,
  ranura de arranque) y `host_network` (recargar, editar una interfaz, crear
  una VLAN). Quien no quiera que un agente toque la red puede quitarla sin
  perder el resto (research R-1).
- P: ¿Qué es «la interfaz por la que entra Hermes»? → R: la **principal**
  (`primary: true` en `/network/info`, la de la ruta por defecto) y, además,
  **la única conectada** si fuera otra. Hermes corre en la red interna de
  Docker y no ve la interfaz del cliente; la de la ruta por defecto es por la
  que llegan la LAN, el acceso remoto y el Funnel. Editarla se **rechaza
  fail-closed**, también si no se puede saber cuál es (research R-2).
- P: ¿`sv_reload_network` con token? → R: **no**. `POST /network/reload` solo
  vuelve a leer el estado de NetworkManager y fuerza la comprobación de
  conectividad: no cambia nada. Un token obligaría a anunciarla destructiva
  (invariante token ⇔ `destructiveHint`) y la vista previa tendría que
  inventarse un riesgo (principio V). Mismo criterio que `sv_reload_supervisor`
  (022) y `sv_reload_mount` (019). Desviación anotada respecto al texto de
  FR-082 de la 008 (research R-3; duda D-032-1).
- P: ¿Un bloque `ipv4`/`ipv6`/`wifi` parcial? → R: **no**: el Supervisor
  reemplaza el bloque entero y rellena lo que falta con valores por defecto
  (`ipv4` sin `method` pasa a `static` sin direcciones; `wifi` sin `auth` pasa
  a red abierta). Hermes exige los campos que deciden el resultado y rechaza
  combinaciones contradictorias antes de llamar (research R-4).
- P: ¿Exponer `force` de apagar (saltarse la migración de la base de datos en
  curso)? → R: **no**, igual que `sv_reboot_host` (research R-5).
- P: ¿Qué ata el token? → R: **todos los argumentos** (la PSK incluida) y la
  **huella del estado** que describe la vista previa (hostname actual, swap
  actual, ranuras, interfaz y su papel). Si cambia en los 60 s, no se ejecuta
  (research R-6).
- P: ¿La PSK? → R: entra, se envía al Supervisor y **nunca sale**: ni en la
  vista previa (solo `"psk": "set"`), ni en la respuesta, ni en errores, ni en
  el log, ni en el fichero del token (no es omitible; solo el HMAC de la
  acción) (research R-9).

### Decisiones del supervisor al validar la spec (para el cierre)

- **D-032-1**: `sv_reload_network` va **sin token**, porque solo vuelve a
  leer el estado. **Desviación literal de FR-082 de la 008**, que pide
  confirmación para las tres operaciones de red; se anota aquí para el
  cierre del programa.
- **D-032-2**: editar la interfaz principal, la única conectada o una
  interfaz cuando no se sabe cuál es la principal se rechaza **siempre**,
  sin token (fail-closed), también los cambios inocuos como `mdns`. El
  mensaje explica cómo hacerlo desde la interfaz de HA.
- **D-032-3**: una puerta de enlace en una interfaz secundaria o en una VLAN
  solo avisa (aviso fuerte de que puede quedarse con la ruta por defecto);
  hay token.

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es el administrador de Home Assistant que gestiona su sistema
desde un cliente MCP.

### Historia 1 — Apagar el equipo antes de moverlo o de un corte (Prioridad: P1)

Quien va a desenchufar el equipo quiere apagarlo bien, sin abrir la interfaz,
y saber antes que después nadie podrá encenderlo a distancia.

**Prueba independiente**: con el Supervisor simulado, `sv_shutdown_host` sin
token devuelve una vista previa con el aviso y un token sin llamar a nada que
escriba; con el token, un `POST /host/shutdown` con cuerpo vacío.

**Escenarios de aceptación**:

1. **Dado** el host en marcha, **cuando** el agente llama a
   `sv_shutdown_host()`, **entonces** recibe una vista previa que dice que se
   apagan el host, Home Assistant, todas las apps y el propio Hermes, que
   **nadie podrá encenderlo de forma remota** (hará falta acceso físico, o un
   enchufe o Wake-on-LAN que no dependan de este equipo) y que la conexión con
   Hermes se cortará; y un token.
2. **Dado** el token, **cuando** se confirma, **entonces** el Supervisor recibe
   `POST /host/shutdown` sin `force`, y la respuesta dice que el apagado está
   en marcha.
3. **Dado** una migración de la base de datos de HA en curso, **cuando** se
   confirma, **entonces** el error del Supervisor vuelve tal cual (redactado) y
   no se reintenta con `force`.
4. **Dado** que la conexión se corta tras enviar la orden, **entonces** la
   respuesta no dice «ok» ni «error» a secas: dice que el resultado no se puede
   saber y que, si el apagado siguió, el equipo no responderá.

---

### Historia 2 — Cambiar el nombre, la swap o volver al OS anterior (Prioridad: P1)

Quien administra el equipo quiere cambiar su hostname, ajustar la swap o, tras
una actualización de OS que va mal, arrancar en la ranura anterior.

**Prueba independiente**: con el Supervisor simulado, cada tool enseña el
antes y el después leídos del Supervisor, rechaza sin token lo inválido o lo
que no cambia nada y, con el token, envía la carga exacta.

**Escenarios de aceptación**:

1. **Dado** el hostname `homeassistant`, **cuando** se llama a
   `sv_set_hostname("casa-ha")`, **entonces** la vista previa enseña
   `homeassistant → casa-ha` y avisa de que cambia el nombre mDNS
   (`<hostname>.local`): enlaces, marcadores y certificados que usen el viejo
   dejan de funcionar. Con el token, `POST /host/options` con
   `{"hostname": "casa-ha"}`.
2. **Dado** un hostname inválido (`Casa HA`, `-ha`, 64 caracteres, un punto) o
   igual al actual, **entonces** `invalid_argument` o `no_change` sin token y
   sin llamar.
3. **Dado** HAOS 15 con swap `1G` y swappiness 1, **cuando** se llama a
   `sv_set_swap(swap_size="2G")`, **entonces** la vista previa enseña
   `1G → 2G`, el espacio libre del disco y que el Supervisor marcará un
   **reinicio necesario** (`reboot_required`); con el token, `POST
   /os/config/swap` con solo lo que se pasó.
4. **Dado** `swap_size` mayor que el disco libre, **entonces**
   `insufficient_disk` sin token; **dado** `swap_size="0"`, **entonces** la
   vista previa avisa de que desactiva la swap.
5. **Dado** un OS anterior a 15 o un sistema que no es HAOS (`GET
   /os/config/swap` responde que no existe), **entonces** `not_supported` sin
   token.
6. **Dado** ranuras A (activa, 17.0) y B (17.1, «bad»), **cuando** se llama a
   `sv_set_boot_slot("A")`, **entonces** `already_booted` sin token;
   **cuando** se llama con `"B"`, **entonces** la vista previa dice que el
   equipo **se reinicia ya** en el OS 17.1 de la ranura B, enseña su estado y
   avisa de que la ranura está marcada como mala; con el token, `POST
   /os/boot-slot` con `{"boot_slot": "B"}`.

---

### Historia 3 — Configurar una segunda interfaz o una VLAN sin quedarse fuera (Prioridad: P2)

Quien tiene una segunda interfaz (Wi-Fi de respaldo, una tarjeta para la red
IoT) o quiere una VLAN quiere configurarla desde el agente, viendo antes qué
cambia y con la garantía de que el agente no puede tocar la interfaz por la
que se llega a Home Assistant.

**Prueba independiente**: con el Supervisor simulado (una `eth0` principal y
conectada, una `wlan0` no principal), cada tool rechaza la principal sin
token, enseña el antes y el después de la otra, y con el token envía la carga
exacta; la PSK centinela no aparece en ninguna respuesta, vista previa, log ni
fichero del token.

**Escenarios de aceptación**:

1. **Dado** `eth0` principal, **cuando** se llama a
   `sv_update_network_interface("eth0", …)` con cualquier cambio, **entonces**
   `primary_interface` sin token ni llamada de escritura, con la explicación
   de que el Supervisor no revierte y la casa se quedaría sin acceso.
2. **Dado** `default` como nombre de interfaz, **entonces** `invalid_argument`:
   en el Supervisor es un alias de la principal.
3. **Dado** que `/network/info` no se puede leer, no trae ninguna interfaz
   principal o la interfaz pedida es la única conectada, **entonces** se
   rechaza (`primary_unknown`, `only_connected_interface`) sin token.
4. **Dado** `wlan0` no principal, **cuando** se llama con `wifi={"mode":
   "infrastructure", "auth": "wpa-psk", "ssid": "mi-red", "psk": <centinela>}`
   e `ipv4={"method": "auto"}`, **entonces** la vista previa enseña el antes
   (leído de `/network/interface/wlan0/info`) y el después, con `"psk":
   "set"`, y un **aviso fuerte**: el Supervisor no revierte, una
   configuración mala puede dejar esa interfaz sin red y, si toma la ruta por
   defecto, cortar el acceso. Con el token, `POST
   /network/interface/wlan0/update` con la carga exacta (la PSK incluida) y la
   respuesta con la interfaz leída de vuelta, sin PSK.
5. **Dado** `ipv4` sin `method`, `static` sin direcciones, `auto` con
   direcciones o `gateway`, `wifi` sin `auth` o sin `ssid`, `wpa-psk` sin
   `psk`, una PSK en una red abierta, una IP o una máscara mal formadas,
   **entonces** `invalid_argument` con la regla, sin el valor, sin token.
6. **Dado** un `gateway` en el cambio, **entonces** la vista previa avisa de
   que la ruta por defecto puede pasar a esta interfaz.
7. **Dado** `eth0` de tipo ethernet, **cuando** se llama a
   `sv_create_vlan("eth0", 20, ipv4={"method": "auto"})`, **entonces** la
   vista previa enseña la interfaz nueva `eth0.20`, su configuración y el aviso
   de que una puerta de enlace de esa VLAN (por DHCP o fija) puede quedarse con
   la ruta por defecto; con el token, `POST /network/interface/eth0/vlan/20`.
   Si `eth0.20` ya existe, o la madre no es ethernet, o el id está fuera de
   1–4094, error sin token.
8. **Dado** `sv_reload_network()`, **entonces** un `POST /network/reload` sin
   token y la respuesta dice que solo vuelve a leer el estado y la
   conectividad.

---

### Historia 4 — Nada de lo actual cambia (Prioridad: P1)

**Escenarios de aceptación**:

1. **Dado** `tool_families_disabled: [host_control, host_network]`,
   **entonces** ninguna de las siete tools se registra y la lista es la de
   antes de esta sub-feature.
2. **Dado** `sv_reboot_host`, `sv_get_host_info`, `sv_get_os_info` y
   `sv_get_swap`, **entonces** no cambian.
3. **Dado** `sv_call_api("POST", "/host/shutdown")` o cualquiera de las siete
   rutas, **entonces** `use_dedicated_tool` con su tool y sin llamada; con la
   familia desactivada, `family_disabled`.

### Casos límite

- El hostname actual no se puede leer (`/host/info` falla): error sin token,
  no vista previa a medias.
- Dos llamadas seguidas a `sv_set_swap` sin argumentos: `invalid_argument`
  («nada que cambiar»), no un `POST` vacío.
- Ranura pedida que no está en `boot_slots` o sin versión: `slot_unusable`.
- La interfaz pasa a ser la principal entre la vista previa y la confirmación:
  la huella del estado cambia y no se ejecuta.
- Interfaz VLAN cuya madre es la principal: se puede editar (no es la
  principal), con el mismo aviso fuerte.
- Respuesta de forma inesperada del Supervisor en cualquier lectura previa:
  `error`, nunca una vista previa inventada.
- El cliente pide `force` para apagar: no existe el argumento; la descripción
  lo dice.

## Requisitos *(obligatorio)*

### Requisitos funcionales

#### Host y OS (CAP-086, FR-081 de la 008) — tramo 1

- **FR-001**: `sv_shutdown_host(confirmation_token=None)` apaga el host con
  `POST /host/shutdown` en dos pasos. Vista previa: qué se apaga (host, Core,
  todas las apps, Hermes), el aviso de que **nadie puede encenderlo de forma
  remota** y de que la conexión se cortará. Sin `force`: si hay una migración
  de la base de datos, el error del Supervisor vuelve redactado. (FR-081,
  CAP-086)
- **FR-002**: `sv_set_hostname(hostname, confirmation_token=None)` cambia el
  hostname con `POST /host/options` `{"hostname": …}`. Valida una etiqueta DNS
  (RFC 1123: minúsculas, dígitos y `-`, 1–63, sin `-` al principio ni al
  final); igual al actual → `no_change`. Vista previa: actual → nuevo y el
  aviso del nombre mDNS. (FR-081, CAP-086)
- **FR-003**: `sv_set_swap(swap_size=None, swappiness=None,
  confirmation_token=None)` cambia la swap con `POST /os/config/swap` y solo
  las claves pasadas. `swap_size` con la forma del Supervisor
  (`^\d+([KMG](i?B)?|B)?$`), `swappiness` entero 0–200 (no `bool`); ninguna
  → `invalid_argument`; mismos valores que los actuales → `no_change`. Vista
  previa: actual → nuevo (leído de `GET /os/config/swap`), disco libre (de
  `GET /host/info`), aviso de reinicio necesario y, con `0`, de que desactiva
  la swap. Tamaño mayor que el disco libre → `insufficient_disk`. Sin swap
  configurable (404 del Supervisor) → `not_supported`. (FR-081, CAP-086)
- **FR-004**: `sv_set_boot_slot(boot_slot, confirmation_token=None)` con
  `boot_slot` `"A"` o `"B"` marca la ranura y **reinicia** con `POST
  /os/boot-slot` `{"boot_slot": …}`. Vista previa (de `GET /os/info`): ranura
  actual y su versión, ranura destino con versión, estado y `status`, el aviso
  de que el equipo se reinicia ya en otro OS y cómo volver. Ranura ya activa →
  `already_booted`; ausente o sin versión → `slot_unusable`; destino marcado
  como malo → aviso explícito en la vista previa. Sin HAOS → `not_supported`.
  (FR-081, CAP-086)

#### Red del host (CAP-090, FR-082 de la 008) — tramo 2

- **FR-005**: `sv_reload_network()` llama a `POST /network/reload` **sin
  token**; la descripción dice que solo vuelve a leer el estado y la
  conectividad. (FR-082, CAP-090; desviación razonada en research R-3)
- **FR-006**: `sv_update_network_interface(interface, ipv4=None, ipv6=None,
  wifi=None, enabled=None, mdns=None, llmnr=None, confirmation_token=None)`
  edita una interfaz con `POST /network/interface/{interface}/update` en dos
  pasos. Al menos un cambio. Vista previa: `before` (la interfaz leída de
  `GET /network/interface/{interface}/info`, en su forma pública: sin `mac`
  ni PSK), `after` (lo que se
  envía, con `"psk": "set"`), el papel de la interfaz (principal, conectada,
  otras conectadas) y el **aviso fuerte** de pérdida de acceso. Respuesta:
  la interfaz leída de vuelta. (FR-082, CAP-090)
- **FR-007**: **Guarda de la interfaz de acceso**, antes de la vista previa y
  otra vez antes de enviar: se rechaza sin token y sin escribir si la
  interfaz es la principal (`primary_interface`), si es la única conectada
  (`only_connected_interface`), si `/network/info` no se puede leer, no tiene
  ninguna principal o tiene una forma inesperada (`primary_unknown`), o si el
  nombre es `default`. (FR-082, CAP-090)
- **FR-008**: **Validación de los bloques** antes de llamar (el Supervisor
  reemplaza cada bloque entero): `ipv4`/`ipv6` exigen `method`
  (`auto`/`static`/`disabled`); `static` exige al menos una dirección con
  prefijo; `auto` y `disabled` no admiten `address` ni `gateway`; direcciones,
  `gateway` y `nameservers` de la familia correcta; `route_metric` entero;
  `addr_gen_mode` e `ip6_privacy` de su vocabulario. `wifi` exige `mode`,
  `auth` (`open`/`wep`/`wpa-psk`) y `ssid` (1–32 bytes); `wpa-psk` y `wep`
  exigen `psk` (con `wpa-psk`, 8–63 caracteres o 64 hexadecimales); `open`
  no la admite. `enabled` booleano; `mdns`/`llmnr` de
  `default`/`off`/`resolve`/`announce`. Claves desconocidas → error. Los
  mensajes dicen la regla, nunca el valor. (FR-082, CAP-090)
- **FR-009**: `sv_create_vlan(interface, vlan_id, ipv4=None, ipv6=None,
  mdns=None, llmnr=None, confirmation_token=None)` crea `<interface>.<id>`
  con `POST /network/interface/{interface}/vlan/{vlan_id}` en dos pasos.
  `vlan_id` entero 1–4094 (no `bool`); la madre existe y es `ethernet`; la
  VLAN no existe ya (`vlan_exists`). Bloques con FR-008 (por defecto, el
  Supervisor usa `auto`). Vista previa: madre, nombre nuevo, configuración y
  el aviso de que la puerta de enlace de la VLAN puede quedarse con la ruta
  por defecto. Crear sobre la madre principal se permite: no edita la madre
  (research R-2). (FR-082, CAP-090)
- **FR-010**: **La PSK nunca sale**: ni en la vista previa, la respuesta, los
  errores (se sustituye el valor literal y se pasa por `redact_secrets`), el
  log ni el fichero del token (sin `omitibles`; solo el HMAC de la 019). Se
  rechaza una PSK con caracteres de control o igual al marcador de redacción.
  (FR-019 y FR-082 de la 008)

#### Comunes

- **FR-011**: El token de las seis tools con confirmación ata **todos** sus
  argumentos y la **huella del estado** de la vista previa (`estado=` de
  `create_confirmation_token`, 018): hostname actual; swap actual; `boot` y
  `boot_slots`; la configuración de la interfaz (sin campos que fluctúan:
  `wifi.signal`, `ready`), su papel y la lista de interfaces conectadas. El
  disco libre no entra (cambia solo); `insufficient_disk` se vuelve a
  comprobar al confirmar. Si
  cambia, no se ejecuta y se pide otra vista previa. Entradas en el
  inventario de la 033. (FR-018 de la 008, principio IV)
- **FR-012**: El log solo lleva la tool, el resultado, nombres de claves que
  cambian y la interfaz (nombre de dispositivo, como `wlan0`); **nunca**
  hostname, IP, puerta de enlace, DNS, SSID, MAC ni PSK. (FR-019 de la 008,
  principio VIII)
- **FR-013**: Errores del Supervisor redactados; formas inesperadas → `error`;
  si la conexión se corta **después** de enviar `shutdown`, `boot-slot` o un
  cambio de red, la respuesta dice `outcome: "unknown"` con una pista para
  comprobarlo (`verify_with`), no «ok» ni un error a secas. (FR-020 de la 008)
- **FR-014**: Las siete rutas de la tabla pasan a `dedicated` con su tool,
  familia y CAP, por el mecanismo del generador (`_DEDICADAS_INICIALES`), y la
  tabla sale idéntica al regenerar. `grep -c "spec 032"` = 0 al cerrar.
  (FR-012 de la 008)
- **FR-015**: Familias nuevas `host_control` (módulo `host_control`) y
  `host_network` (módulo `host_network`), «desde» 1.2.0, desactivables, en
  `tool_families_disabled`. (FR-010 de la 008)
- **FR-016**: Anotaciones honestas: las seis con token en `_DESTRUCTIVE_EXACT`;
  `sv_reload_network` ni de solo lectura ni destructiva, idempotente;
  `sv_create_vlan` no idempotente (prefijo `sv_create_`). Títulos legibles.
  (FR-018 de la 008, principio V)
- **FR-017**: Tema de la guía `host_control` (alias `hostname`, `swap`,
  `boot_slot`, `shutdown`, `host_network`, `network_config`, `vlan`, `wifi`)
  con las siete tools, la guarda de la interfaz principal, que la red se lee
  con `sv_read_api("/network/info")` y que encender el host no se puede a
  distancia; entrada en el índice. Huella actualizada de cada tema existente
  que cambie. (FR-011 de la 008)
- **FR-018**: Matriz de la 014: siete filas `VM` / `pendiente` con su nota y su
  línea en «Tools nuevas del programa» de `docs/BANCO-SUPERVISOR.md`.
  (FR-016 de la 008)
- **FR-019**: Pruebas con el Supervisor simulado (fixtures con la forma de
  2026.11.0) y solo datos genéricos: `192.0.2.x`, `2001:db8::/32`,
  `aa:bb:cc:dd:ee:ff`, «mi-red», `casa-ha`, PSK centinela. (FR-019 y FR-021
  de la 008)
- **FR-020**: Documentación en el mismo cambio: sección en `## [1.2.0]` del
  CHANGELOG, estado en la hoja de ruta, familias en DOCS y en los dos README,
  filas CAP-086 y CAP-090 de la matriz de la 008. (FR-023, FR-024 de la 008)

### Entidades clave

- **Vista previa de host**: acción, antes → después, avisos, huella.
- **Interfaz** (forma v1 del Supervisor): `interface`, `type`, `enabled`,
  `connected`, `primary`, `mac`, `ipv4`, `ipv6`, `wifi` (sin PSK), `vlan`,
  `mdns`, `llmnr`. Ver [data-model.md](data-model.md).

## Criterios de éxito *(obligatorio)*

- **SC-001**: Las 7 tools existen en sus dos familias con las anotaciones de
  FR-016; el invariante destructiva ⇔ token sigue en verde.
- **SC-002**: Ninguna llamada de escritura al Supervisor sobre la interfaz
  principal, la única conectada o con la principal desconocida, en ningún
  test (control negativo: quitar la guarda → caen).
- **SC-003**: La PSK centinela no aparece en ninguna salida, log ni fichero de
  `CONFIRMATIONS_DIR` en todos los caminos (vista previa, confirmación, error).
- **SC-004**: Un token no ejecuta si cambia un argumento o el estado.
- **SC-005**: Con las dos familias desactivadas, la lista de tools es la de
  antes; las 7 rutas son `dedicated`; regenerar la tabla no la cambia.
- **SC-006**: Siete filas nuevas en la matriz de la 014, todas `VM` /
  `pendiente`; suite en verde (6 fallos conocidos en Windows).

## Supuestos

- Se usa la API v1 del Supervisor (`/network/interface/{i}/update`), la que
  Hermes llama hoy; la v2 (`/network/interfaces/{name}/config`) es de la
  plataforma (027) y no entra.
- Borrar una VLAN no tiene ruta en la v1: queda fuera (research R-8).
- `sv_reboot_host` no cambia; reiniciar no es de esta sub-feature.
- La prueba real es en la VM de la 014 (pendiente declarado).
