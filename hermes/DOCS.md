# Hermes

Servidor MCP que expone tu Home Assistant a Claude: 366 herramientas para leer
estados, llamar servicios, escribir automatizaciones, editar `/config`,
gestionar add-ons y backups.

## Antes de instalar

Hermes **no habla TLS** y no se publica solo en internet. Necesitas algo delante
que termine el TLS y le haga proxy: Tailscale Funnel, Cloudflare Tunnel o un
proxy inverso clásico. La opción `network_mode` le dice con cuál cuenta.

Hace falta Home Assistant **2024.10.0** o posterior: Hermes guarda las
automatizaciones con las claves en plural (`triggers`, `actions`), que las
versiones anteriores no entienden.

Necesitas además un plan de pago de Claude: los Custom Connectors, que es como
se conecta Hermes, no están en el plan gratuito.

La guía completa —las tres formas de exponerlo, con sus comandos— está en el
[README del repositorio](https://github.com/Nadeon/Hermes-addon/blob/main/README.es.md).

## Configuración mínima

Dos opciones son obligatorias y sin ellas el add-on no arranca:

| Opción | Qué es |
|---|---|
| `auth_password` | La contraseña con la que autorizarás a Claude. Mínimo 12 caracteres, y se rechaza si es adivinable —repetitiva, una tirada del abecedario, de los dígitos o del teclado, de las más usadas, o con «hermes», «homeassistant» o tu hostname dentro—. Genérala con `openssl rand -base64 18` o con tu gestor de contraseñas. Es el único secreto que protege tu casa: no reutilices ninguna |
| `public_hostname` | El hostname público por el que se llega a Hermes, **sin** `https://` y **sin** path final. Si no se sirve en el 443, con el puerto: con Tailscale Funnel se recomienda el 8443 (`homeassistant.tailXXXX.ts.net:8443`), para no chocar con `share_homeassistant: funnel`, que publica Home Assistant en el 443 |

Y una que conviene revisar:

| Opción | Default | Qué es |
|---|---|---|
| `network_mode` | `tailscale` | `tailscale` si usas Funnel; `reverse_proxy` para cualquier otra cosa |

El resto de opciones, con sus valores por defecto y qué hace cada una, están
documentadas en el README. La página de configuración de la app enseña además
el nombre y una descripción corta de cada opción, en inglés o en español.

## Conectar Claude

1. Arranca el add-on y comprueba en el log que aparece `hermes_started`.
2. En Claude: **Configuración → Conectores → Añadir conector personalizado**.
3. Pega `https://<tu_public_hostname>/mcp`, con el puerto si lo lleva (ej.
   `https://homeassistant.tailXXXX.ts.net:8443/mcp`).
4. Claude abre una página de autorización. Introduce tu `auth_password`.

La pantalla de autorización te dice **qué cliente** pide acceso y **a dónde**
irá el código. Léelo: es la única defensa contra que alguien te mande un enlace
de autorización propio.

## Qué esperar

Las acciones destructivas no se ejecutan a la primera. Devuelven una vista
previa de lo que van a hacer y un token; solo se ejecutan cuando Claude vuelve a
llamarlas con ese token. Verás a Claude enseñarte el cambio antes de aplicarlo.

Si activas `safety_backup_enabled`, cada escritura en `/config` espera a que
termine un backup completo de HAOS (como mucho uno cada
`safety_backup_window_minutes`). Si el backup falla, la escritura no se hace y
el error dice `safety_backup_job_failed` con el motivo que da el Supervisor.
Si Hermes no puede saber cómo acabó —el Supervisor no responde o ya no conoce
el job—, tampoco se escribe: `safety_backup_state_unknown`. Si el backup
tarda más de 5 minutos, la escritura se rechaza con `safety_backup_timeout` y
el `job_id`, que puedes seguir con `sv_get_job_status`. La escritura siguiente
comprueba ese mismo backup en vez de lanzar otro: si aún no ha terminado, se
rechaza con `safety_backup_in_progress`.

Con `safety_backup_enabled`, la opción `safety_backup_keep` (3 por defecto, 0
la desactiva) conserva solo los safety backups automáticos más recientes y
borra el resto tras cada uno correcto. Uno que terminó con errores en sus
sub-jobs (una app que no se pudo guardar) no cuenta entre los que se conservan
y se borra el primero. Solo toca los que Hermes anotó al crearlos; los anteriores a 1.1.0 se borran a mano con `sv_delete_backup`. El
detalle de qué borra y qué no está en el README.

**Safety backups cifrados (1.2.0).** Los safety backups (los automáticos y
los de `sv_create_safety_backup`) se cifran con la clave de los backups de Home
Assistant, la que te da su **kit de emergencia** al configurar los backups
automáticos. Hermes la lee de Home Assistant en cada backup y no la guarda en
ningún sitio ni la devuelve nunca. Así puedes restaurar un safety backup desde
la interfaz o la CLI de Home Assistant aunque Hermes esté roto; desde Claude,
`sv_restore_backup_full` sin `password` usa esa clave. Lo controla la opción
`safety_backup_encryption`:

| Valor | Con clave en Home Assistant | Sin clave (backups automáticos sin configurar, HA anterior a 2025.1 o caído) |
|---|---|---|
| `auto` (por defecto) | cifrado | **sin cifrar**: la respuesta lo dice (`encrypted: false`, `encryption_skipped_reason`) y el log lo avisa (`safety_backup_unencrypted`) |
| `required` | cifrado; un safety backup reciente sin cifrar no cuenta y se hace uno nuevo cifrado | no se hace el backup: `encryption_key_unavailable`, y la escritura en `/config` no se hace |
| `off` | sin cifrar, como antes de la 1.2.0 | sin cifrar |

Si cambias la clave en Home Assistant, los safety backups anteriores se abren
con la clave anterior (como los backups de Home Assistant): guarda el kit de
emergencia viejo o pásala como `password` al restaurar. La retención sigue
podando los safety backups que Hermes cifró; uno protegido que no creó Hermes
así no lo toca. Un valor que no sea uno de los tres impide arrancar.

La misma opción decide el cifrado del backup parcial que hace
`ha_marketplace_uninstall` antes de desinstalar: la vista previa dice si irá
cifrado (y que restaurarlo necesita la clave del kit de emergencia), y con
`required` y sin clave no hay backup y no se desinstala nada.

En el Marketplace (HACS hasta HA 2026.10) Claude puede consultar
repositorios, actualizaciones y versiones y, desde la 1.2.0 (familia
`marketplace_manage`), reconocer avisos críticos, ignorar repositorios
retirados, quitar repositorios personalizados no instalados, refrescar uno
desde GitHub y desinstalar uno instalado, siempre en dos pasos. Antes de
desinstalar, Hermes hace un backup parcial de la configuración de Home
Assistant sin la base de datos (sin cifrar); si el backup falla, no
desinstala nada. Hermes no reinicia Home Assistant: si hace falta, Claude te
lo dirá. No puede instalar, fijar versiones,
mostrar betas ni añadir repositorios, y nunca acepta nada: Home Assistant
exige que el aviso de riesgos del Marketplace lo haya aceptado el usuario de
Home Assistant que lo pide, y Hermes se conecta con el usuario del Supervisor,
que nadie puede usar en la interfaz. Hazlo desde la interfaz del Marketplace.
Por la misma razón, actualizar con la entidad `update` suele fallar desde
Hermes con ese motivo, y Claude te lo dirá.

**Carpetas /addons y /share (1.2.1).** Además de `/config`, Claude puede
trabajar con dos carpetas más (familia `addons_share`): `/addons`, donde
viven las apps locales (cada carpeta con un `config.yaml` es una app
`local_<slug>`), y `/share`, la carpeta compartida entre apps. Puede listar,
ver metadatos y leer texto; y escribir ficheros, crear carpetas, mover y
borrar, **siempre en dos pasos**. Las reglas:

- Las rutas pasan las mismas comprobaciones que en `/config`: nada de `..` ni
  de symlinks que salgan de la carpeta. Los ficheros con nombre sensible
  (`secrets.yaml`, claves, certificados, tokens, bases de datos) no se leen
  nunca; el resto se devuelve tal cual, sin redactar, como en `/config`.
- **No hay backup automático.** La vista previa lo dice y trae la llamada
  para hacer antes un backup parcial (`addons/local` o `share`). Lo que se
  borra o se sobrescribe aquí no se recupera desde Hermes.
- El token se ata a lo que vio la vista previa: si el fichero o la carpeta
  cambian antes de confirmar, no se hace nada. Una carpeta en la que otra app
  está escribiendo no se puede borrar sin parar antes esa app.
- En `/addons`, toda vista previa recuerda que el Supervisor construye y
  ejecuta lo que hay ahí. La carpeta de una app local **instalada** no se
  borra ni se mueve: hay que desinstalarla antes. Escribir dentro sí se
  puede; el cambio se aplica al reconstruir la app.
- La raíz de cada carpeta y los puntos de montaje (un NAS montado en
  `/share`) no se borran ni se mueven.
- Instalar, actualizar o reconstruir una app (`sv_install_addon`,
  `sv_update_addon`, `sv_rebuild_addon`) enseña en la vista previa los
  privilegios que pide (acceso completo al hardware, a Docker o a la red del
  host, AppArmor desactivado, carpetas con escritura…) y, para una app local,
  lo que declara su `config.yaml`. Si cambian antes de confirmar, no se hace
  nada.
- **Recarga la tienda después de tocar `/addons`.** El Supervisor instala,
  actualiza y reconstruye con su propia copia del `config.yaml`, la de la
  última recarga de la tienda. Si algo en `/addons` cambió después de la
  última recarga que lanzó Hermes, o Hermes no ha recargado desde que
  arrancó, instalar, actualizar o reconstruir una app local se rechaza sin
  token (`store_copy_stale`): pide a Claude que recargue la tienda
  (`sv_reload_store`) y vuelva a empezar. Para que el Supervisor relea las
  apps locales, Hermes cambia la fecha de la propia carpeta `/addons` justo
  antes de cada recarga que lanza (no toca ningún fichero). Si un
  `config.yaml` hace fallar la recarga entera (por ejemplo, una fecha
  imposible), también se rechaza, con su ruta: arréglalo o quítalo.

Para eso Hermes monta `/addons` **con escritura** desde la 1.2.1. Usa el tipo
de montaje `addons`, que el Supervisor da por heredado desde la 2026.07: al
arrancar Hermes, el log del Supervisor dice que usa el tipo heredado `addons`
en vez de `local_apps`. Es esperado y no afecta a nada; Hermes no usa
`local_apps` porque un Supervisor anterior a la 2026.07 no lo conoce y
rechazaría la app entera. Si no quieres que Claude toque esas carpetas, desactiva la familia
`addons_share` (ver «Familias de tools»): sus tools desaparecen, aunque el
montaje sigue.

## Límites y Claude Code

Los límites por defecto están alineados con lo que aceptan los clientes de
Claude:

| Opción | Defecto | Máximo efectivo | Qué es |
|---|---|---|---|
| `response_max_bytes` | `131072` (128 KiB) | `524288` (512 KiB) | Tamaño máximo de la respuesta de cualquier tool. Por encima, se recorta la lista más larga y se indica con `truncated: true` (una lista sola, como la de `ha_get_states`, llega como `{truncated, count, total, items}`); el historial y las estadísticas se recortan por el final y los logs de una app devuelven sus últimas líneas. Una vista previa de confirmación nunca pierde su `confirmation_token`: sus campos grandes se resumen (`_omitted`) y se marca `preview_truncated: true`. Si no hay lista de primer nivel que recortar, la respuesta es el error `response_too_large`: una configuración que se guarda de vuelta (un script, una automatización, una vista de Lovelace) nunca sale recortada por dentro |
| `ha_ws_max_msg_size_bytes` | `16777216` (16 MiB) | `16777216` | Tamaño máximo de un mensaje de la WebSocket con Home Assistant. Un mensaje mayor cierra la conexión entera (fallan todas las llamadas en curso y Hermes reconecta) y lo anota en el log como `ha_ws_message_too_big`. Bájalo solo si la memoria del equipo es muy justa |
| `wait_for_event_max_seconds` | `90` | `220` | Espera máxima que admite `ha_wait_for_event` |

**Si tenías valores guardados.** La interfaz guarda el valor por defecto
aunque nadie lo toque, así que un `response_max_bytes` de `1048576` (el defecto
anterior, 1 MiB) se trata como no personalizado y pasa a `131072`. Un valor
por encima de `524288`, o un `wait_for_event_max_seconds` por encima de `220`,
se recorta al máximo. En los dos casos el add-on arranca igual y lo anota en el
log (`config_legacy_default_replaced` o `config_value_clamped`, con el valor
guardado y el aplicado). Si necesitas respuestas más grandes, sube
`response_max_bytes` hasta `524288`. Lo mismo pasa con
`ha_ws_max_msg_size_bytes`: el `4194304` guardado (el defecto anterior, 4 MiB)
pasa a `16777216`; si lo habías puesto a propósito para ahorrar memoria,
escribe otro valor, por ejemplo `4194303`.

**Claude Code y las tools lentas.** Claude Code corta una llamada si no recibe
ningún byte en 60 s. Hermes responde en streaming y manda un *ping* cada 15 s,
así que una espera larga de `ha_wait_for_event` no se corta. Si el proxy de
delante almacena la respuesta entera antes de reenviarla, los *pings* no llegan
a tiempo: amplía el plazo en Claude Code con la variable `MCP_TOOL_TIMEOUT` (en
milisegundos) o con `timeout` en la entrada del servidor.

## Otras opciones de esta versión

| Opción | Defecto | Qué es |
|---|---|---|
| `oauth_cimd_enabled` | `true` | Acepta clientes que se identifican con una URL de metadatos (CIMD), como Claude Code. Desactívala solo si un cliente falla con CIMD: el registro dinámico (DCR) sigue funcionando igual |
| `oauth_cimd_allowed_hosts` | `[]` | Hosts cuyos documentos CIMD acepta Hermes (por ejemplo `claude.ai`, donde publica el suyo Claude Code). Vacía significa **cualquier host público**. Ver el aviso de abajo |
| `log_redact_network` | `true` | Sustituye en el log tu `public_hostname`, los hosts de `external_url` e `internal_url` de Home Assistant, los nombres `*.ts.net` y las IPs (salvo las de loopback, y también escritas como `ip-a-b-c-d`) por marcadores, para que puedas pegarlo al pedir ayuda. Desactívala solo para diagnosticar la red: el log lo avisa con `log_network_redaction_disabled`. Los secretos se redactan siempre |
| `tool_families_disabled` | `[]` | Familias de tools que Hermes no registra, para que el cliente cargue menos tools en su contexto. Vacía, están todas. Ver «Familias de tools» |
| `safety_backup_encryption` | `auto` | Cifrado de los safety backups con la clave de los backups de Home Assistant: `auto`, `required` u `off`. Ver «Safety backups cifrados» en «Qué esperar» |

**Aviso sobre `oauth_cimd_allowed_hosts`.** Con CIMD, quien abre la página de
autorización de Hermes elige la URL del documento del cliente, y no necesita la
contraseña para hacerlo. Hermes descarga esa URL **desde la IP de tu casa**, así
que el dueño del dominio elegido ve tu IP pública, la que un túnel como Funnel
oculta. Tu hostname público no es secreto: aparece en los registros públicos de
certificados. Con la lista vacía (el valor por defecto, para no romper ningún
cliente), cualquiera puede provocarlo. Para restringirlo, pon solo los hosts que
uses:

```yaml
oauth_cimd_allowed_hosts:
  - claude.ai
```

Así Hermes rechaza cualquier otro host sin descargar nada. Escribe solo el
nombre, sin `https://`, puerto ni ruta; una IP no vale, y un valor mal escrito
impide arrancar para que la lista no quede vacía por error. Si un cliente deja
de conectar, el evento `oauth_cimd_rejected` con motivo `host_not_allowed` del
log dice qué host añadir. Quitar un host de la lista también invalida los tokens
que ya tenían sus clientes, sin borrarlos: si lo vuelves a poner, siguen
valiendo.

Es la recomendación si solo usas Claude: claude.ai y Claude Code
publican su documento en el host `claude.ai`, y el inicio de sesión de claude.ai
con CIMD está comprobado en una instalación real. El valor por defecto sigue
vacío para no romper otros clientes. Cada descarga o uso de la caché deja en el
log el evento `oauth_cimd_document` con el resultado (`ok`, `cache` o `error`
con su motivo) y solo el host del `client_id`, nunca una IP.

### Familias de tools

Cada tool pertenece a una familia. Las que pongas en
`tool_families_disabled` no se registran: Claude no las ve y no las puede
usar, ni directamente ni a través de las tools genéricas.

| Familia | Tools | Qué agrupa |
|---|---|---|
| `base` | 2 | `ping` y `hermes_guide`. **No se puede desactivar**: sin la guía, Claude no sabe usar el resto |
| `services` | 5 | Estados, servicios y acciones (`ha_get_states`, `ha_call_service`…) |
| `automations` | 21 | Automatizaciones, scripts y escenas |
| `helpers` | 69 | Helpers (`input_*`, contadores, temporizadores, horarios), zonas y personas |
| `events` | 4 | Disparar y esperar eventos |
| `data` | 5 | Plantillas, historial, logbook y estadísticas |
| `registries` | 26 | Registros de áreas, categorías, dispositivos, entidades, plantas y etiquetas |
| `diagnostics` | 8 | Repairs, trazas, relaciones y centro de resolución del Supervisor |
| `config_entries` | 13 | Integraciones y sus flujos de configuración y opciones |
| `filesystem` | 11 | Leer y escribir ficheros de `/config` |
| `supervisor` | 18 | Add-ons, Core, host e información del Supervisor |
| `backups` | 13 | Backups del Supervisor y de la integración `backup` |
| `lovelace` | 10 | Dashboards y recursos de Lovelace |
| `marketplace` | 11 | Marketplace y alias `ha_hacs_*` (solo lectura) |
| `generic_commands` | 4 | Las tools genéricas (nueva en 1.2.0, ver abajo) |
| `mounts` | 9 | Montajes de red (CIFS y NFS) y de discos locales del Supervisor para backups, medios y `share`, el montaje por defecto de los backups y los ajustes de backup del Supervisor (`days_until_stale`, releer backups) (nueva en 1.2.0; crear, editar, borrar y el montaje por defecto, con confirmación; las credenciales nunca se devuelven) |
| `host_control` | 4 | Apagar el host y cambiar su hostname, la swap y la ranura de arranque de Home Assistant OS (nueva en 1.2.0; todo con confirmación y vista previa del estado actual; nadie puede encender el host a distancia después de apagarlo) |
| `host_network` | 3 | Red del host: releer su estado, editar una interfaz secundaria y crear VLAN (nueva en 1.2.0; los cambios, con confirmación y vista previa del antes y el después; la interfaz principal (y la tarjeta que la lleva si es una VLAN), la única conectada o cualquiera si no se sabe cuál es la principal o de qué depende se rechazan siempre; la clave Wi-Fi nunca se devuelve) |
| `system_diagnostics` | 11 | Logs de Core, del Supervisor, de los plugins y del journal del host, también de arranques anteriores; servicios del host, uso de disco, Home Assistant OS y swap (nueva en 1.2.0, solo lectura) |
| `system_status` | 5 | Salud del sistema, reinicio pendiente, tiempos de arranque y manifiestos de las integraciones; solo lectura (nueva en 1.2.0) |
| `recorder` | 8 | Estado del recorder, validación y metadatos de las estadísticas de largo plazo (lectura), y su mantenimiento con confirmación: borrar, convertir la unidad, corregir la unidad guardada, ajustar sumas e importar (nueva en 1.2.0) |
| `energy` | 2 | Preferencias del panel de energía: leerlas y guardarlas con confirmación; cada lista que se pasa reemplaza la suya y las demás se conservan (nueva en 1.2.0) |
| `core_diagnostics` | 12 | Log del sistema, log de errores y niveles de log, validación de configuración, diagnósticos de integraciones y notificaciones persistentes de Home Assistant (nueva en 1.2.0) |
| `integration_flows` | 12 | Integraciones descubiertas, dominios configurables por flujo, título y opciones de sistema de una integración, subentries y reconfigure de una integración (nueva en 1.2.0) |
| `repair_flows` | 4 | Un aviso de Repairs con sus datos internos y su flujo de reparación (nueva en 1.2.0) |
| `system_updates` | 8 | Qué tiene actualización (Core, OS, Supervisor, apps y plugins), buscar actualizaciones, actualizar Core, el OS y el Supervisor con vista previa, y las entidades `update` de Core (listar, notas de versión e instalar) (nueva en 1.2.0) |
| `app_store` | 9 | Tienda de apps del Supervisor: repositorios (listar, añadir y quitar en dos pasos, reparar y recargar la tienda), changelog y documentación de la versión de la tienda de una app, si se puede instalar en este sistema y reconstruir una app instalada (en dos pasos) (nueva en 1.2.0) |
| `blueprints` | 5 | Blueprints de automatizaciones, scripts y plantillas: listar, ver la sustitución con unas entradas, guardar, importar de una URL y borrar (nueva en 1.2.0) |
| `automation_assist` | 9 | Ayuda para escribir automatizaciones: triggers, condiciones y acciones de un dispositivo, qué abarca un target y qué admite, y esperar una vez a un trigger; solo lectura (nueva en 1.2.0) |
| `system_control` | 7 | Arrancar, reconstruir y configurar Home Assistant Core; recargar, reiniciar, reparar y configurar el Supervisor (nueva en 1.2.0; todo con confirmación salvo recargar; las opciones van por listas cerradas: `image`, `port`, `ssl`, `refresh_token` y el `channel` del Supervisor no se cambian) |
| `marketplace_manage` | 5 | Mantenimiento del Marketplace: reconocer avisos críticos, ignorar retirados, quitar personalizados no instalados, refrescar desde GitHub y desinstalar, con un backup parcial antes (nueva en 1.2.0; siempre con confirmación; no instala nada) |
| `resolution_fixes` | 1 | Aplicar una sugerencia del centro de resolución del Supervisor (nueva en 1.2.0; siempre con confirmación y una vista previa que explica qué hace; se rechazan las que no tienen arreglo, las que tocan los discos de datos y las que apuntan al propio Hermes) |
| `core_config` | 2 | Configuración general de Home Assistant: nombre, ubicación, unidades, zona horaria, moneda, país, idioma y URLs (nueva en 1.2.0) |
| `assistant_exposure` | 3 | Qué entidades ven y controlan Assist, los agentes conversacionales y los asistentes de voz de la nube (nueva en 1.2.0) |
| `users` | 4 | Usuarios de Home Assistant: listar, crear sin credenciales, editar y borrar; nunca contraseñas ni tokens (nueva en 1.2.0) |
| `core_network` | 3 | Adaptadores de red y servidor HTTP de Home Assistant (puerto, SSL, proxy inverso); cambiar el HTTP reinicia Home Assistant (nueva en 1.2.0) |
| `conversation` | 4 | Assist: agentes de conversación y sus idiomas, frases de los disparadores de frase, analizar frases sin ejecutarlas y mandar una frase a Assist, que la ejecuta (siempre en dos pasos; con un agente que no es el integrado, el texto puede salir a un servicio externo) (nueva en 1.2.0) |
| `backup_integration` | 6 | Backups de la integración `backup` de Home Assistant: dónde se guardan (agentes), la programación, la retención y el contenido de los automáticos, y crear, borrar y restaurar backups (nueva en 1.2.0). La clave de cifrado no sale ni se cambia aquí |
| `cameras` | 2 | Instantánea de una cámara e imagen de una entidad `image`, devueltas como imagen al cliente; solo lectura. Una cámara puede enseñar el interior de tu casa: desactívala si no quieres que Claude las vea (nueva en 1.2.0) |
| `dashboard_reset` | 1 | Restablecer un dashboard de Lovelace al autogenerado (borra su configuración guardada), en dos pasos; el dashboard principal y el panel por defecto están protegidos (nueva en 1.2.0) |
| `addons_share` | 7 | Ficheros de `/addons` (el código de las apps locales) y de `/share`: listar, ver metadatos y leer texto, con las mismas comprobaciones de ruta y los mismos nombres bloqueados que en `/config`; escribir, crear carpetas, mover y borrar, siempre en dos pasos, sin backup automático y sin borrar ni mover las apps locales instaladas ni los puntos de montaje (escribir dentro de una se admite, con aviso) (nueva en 1.2.1) |

Por ejemplo, si no usas Lovelace ni el Marketplace desde Claude:

```yaml
tool_families_disabled:
  - lovelace
  - marketplace
```

Un nombre que no esté en la tabla, o `base`, impide arrancar: el log dice qué
valor falla y cuáles valen. Al arrancar, el log anota `tool_families` con las
familias desactivadas y cuántas tools quedan. Con las familias nuevas de la
1.2.0 (`generic_commands`, `system_diagnostics`, `system_status`,
`recorder`, `core_diagnostics`, `integration_flows`, `repair_flows`,
`mounts`, `system_updates`, `app_store`, `blueprints`, `automation_assist`,
`energy`, `system_control`, `resolution_fixes`, `core_config`,
`assistant_exposure`, `users`, `core_network`, `host_control`,
`host_network`, `conversation`, `backup_integration`, `cameras`,
`dashboard_reset` y `marketplace_manage`) y la de la 1.2.1 (`addons_share`) desactivadas, la lista de tools es exactamente la de la 1.1.2; apagando solo `addons_share`, la de la 1.2.0.

### Tools genéricas

`ha_read_ws_command`, `ha_call_ws_command`, `sv_read_api` y `sv_call_api`
cubren lo que ninguna otra tool cubre: comandos WebSocket de Home Assistant y
rutas de la API del Supervisor. Solo ejecutan lo que permite la tabla de
comandos de Hermes, revisada a mano para Home Assistant 2026.11; lo demás se
rechaza sin llegar a Home Assistant. Las de escritura piden siempre
confirmación, con una vista previa de lo que se va a enviar. Claude puede
consultar la tabla con `hermes_guide(topic="generic_commands", search="…")`.

Las integraciones concretas (Z-Wave JS, ZHA, Matter, Thread, MQTT, USB, KNX,
Insteon, LCN, ESPHome…) no tienen tools propias: sus comandos van por estas
genéricas, clasificados uno a uno. Lo que devuelve o pide claves de red,
códigos de emparejamiento, tokens o contraseñas se rechaza o sale tapado. La
guía tiene un tema por grupo: `zwave`, `zigbee`, `matter_thread` y
`other_integrations`.

## Problemas

El apartado *Si no arranca* del [README en español](https://github.com/Nadeon/Hermes-addon/blob/main/README.es.md#si-no-arranca)
recoge los mensajes de error concretos y
qué significa cada uno.

Para reportar un fallo de seguridad, **no abras un issue**: usa el
[formulario privado](https://github.com/Nadeon/Hermes-addon/security/advisories/new).
