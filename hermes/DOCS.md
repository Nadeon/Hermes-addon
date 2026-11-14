# Hermes

Servidor MCP que expone tu Home Assistant a Claude: 216 herramientas para leer
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
documentadas en el README.

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
borra el resto tras cada uno correcto. Solo toca los que Hermes anotó al
crearlos; los anteriores a 1.1.0 se borran a mano con `sv_delete_backup`. El
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
| `response_max_bytes` | `131072` (128 KiB) | `524288` (512 KiB) | Tamaño máximo de la respuesta de una tool. Por encima, la tool recorta y lo indica |
| `wait_for_event_max_seconds` | `90` | `220` | Espera máxima que admite `ha_wait_for_event` |

**Si tenías valores guardados.** La interfaz guarda el valor por defecto
aunque nadie lo toque, así que un `response_max_bytes` de `1048576` (el defecto
anterior, 1 MiB) se trata como no personalizado y pasa a `131072`. Un valor
por encima de `524288`, o un `wait_for_event_max_seconds` por encima de `220`,
se recorta al máximo. En los dos casos el add-on arranca igual y lo anota en el
log (`config_legacy_default_replaced` o `config_value_clamped`, con el valor
guardado y el aplicado). Si necesitas respuestas más grandes, sube
`response_max_bytes` hasta `524288`.

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
| `log_redact_network` | `true` | Sustituye en el log tu `public_hostname`, los nombres `*.ts.net` y las IPs (salvo las de loopback) por marcadores, para que puedas pegarlo al pedir ayuda. Desactívala solo para diagnosticar la red: el log lo avisa con `log_network_redaction_disabled`. Los secretos se redactan siempre |

## Problemas

El apartado *Si no arranca* del [README en español](https://github.com/Nadeon/Hermes-addon/blob/main/README.es.md#si-no-arranca)
recoge los mensajes de error concretos y
qué significa cada uno.

Para reportar un fallo de seguridad, **no abras un issue**: usa el
[formulario privado](https://github.com/Nadeon/Hermes-addon/security/advisories/new).
