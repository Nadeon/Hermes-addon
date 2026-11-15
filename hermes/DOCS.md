# Hermes

Servidor MCP que expone tu Home Assistant a Claude: 284 herramientas para leer
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

El Marketplace (HACS hasta HA 2026.10) es de **solo lectura** para Hermes:
Claude puede consultar repositorios, actualizaciones y versiones, pero no
instalar ni aceptar nada ahí. Para actualizar algo usa su entidad `update`, que
pide confirmación como cualquier otra acción. El aviso de riesgos del
Marketplace lo tiene que aceptar una persona en la interfaz de Home Assistant,
con el usuario con el que se conecta Hermes; si no está aceptado, la
actualización falla y Claude te lo dirá.

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
| `system_diagnostics` | 11 | Logs de Core, del Supervisor, de los plugins y del journal del host, también de arranques anteriores; servicios del host, uso de disco, Home Assistant OS y swap (nueva en 1.2.0, solo lectura) |
| `system_status` | 5 | Salud del sistema, reinicio pendiente, tiempos de arranque y manifiestos de las integraciones; solo lectura (nueva en 1.2.0) |
| `recorder` | 3 | Estado del recorder, validación y metadatos de las estadísticas de largo plazo; hoy solo lectura (nueva en 1.2.0). El mantenimiento de estadísticas se sumará a esta familia |
| `core_diagnostics` | 12 | Log del sistema, log de errores y niveles de log, validación de configuración, diagnósticos de integraciones y notificaciones persistentes de Home Assistant (nueva en 1.2.0) |
| `integration_flows` | 12 | Integraciones descubiertas, dominios configurables por flujo, título y opciones de sistema de una integración, subentries y reconfigure de una integración (nueva en 1.2.0) |
| `repair_flows` | 4 | Un aviso de Repairs con sus datos internos y su flujo de reparación (nueva en 1.2.0) |
| `system_control` | 7 | Arrancar, reconstruir y configurar Home Assistant Core; recargar, reiniciar, reparar y configurar el Supervisor (nueva en 1.2.0; todo con confirmación salvo recargar; las opciones van por listas cerradas: `image`, `port`, `ssl`, `refresh_token` y el `channel` del Supervisor no se cambian) |
| `resolution_fixes` | 1 | Aplicar una sugerencia del centro de resolución del Supervisor (nueva en 1.2.0; siempre con confirmación y una vista previa que explica qué hace; se rechazan las que no tienen arreglo, las que tocan los discos de datos y las que apuntan al propio Hermes) |

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
`mounts`, `system_control` y `resolution_fixes`) desactivadas, la lista de tools es exactamente la de la 1.1.2.

### Tools genéricas

`ha_read_ws_command`, `ha_call_ws_command`, `sv_read_api` y `sv_call_api`
cubren lo que ninguna otra tool cubre: comandos WebSocket de Home Assistant y
rutas de la API del Supervisor. Solo ejecutan lo que permite la tabla de
comandos de Hermes, revisada a mano para Home Assistant 2026.11; lo demás se
rechaza sin llegar a Home Assistant. Las de escritura piden siempre
confirmación, con una vista previa de lo que se va a enviar. Claude puede
consultar la tabla con `hermes_guide(topic="generic_commands", search="…")`.

## Problemas

El apartado *Si no arranca* del [README en español](https://github.com/Nadeon/Hermes-addon/blob/main/README.es.md#si-no-arranca)
recoge los mensajes de error concretos y
qué significa cada uno.

Para reportar un fallo de seguridad, **no abras un issue**: usa el
[formulario privado](https://github.com/Nadeon/Hermes-addon/security/advisories/new).
