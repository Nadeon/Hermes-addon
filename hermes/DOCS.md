# Hermes

Servidor MCP que expone tu Home Assistant a Claude: 185 herramientas para leer
estados, llamar servicios, escribir automatizaciones, editar `/config`,
gestionar add-ons y backups.

## Antes de instalar

Hermes **no habla TLS** y no se publica solo en internet. Necesitas algo delante
que termine el TLS y le haga proxy: Tailscale Funnel, Cloudflare Tunnel o un
proxy inverso clásico. La opción `network_mode` le dice con cuál cuenta.

Necesitas además un plan de pago de Claude: los Custom Connectors, que es como
se conecta Hermes, no están en el plan gratuito.

La guía completa —las tres formas de exponerlo, con sus comandos— está en el
[README del repositorio](https://github.com/Nadeon/Hermes-addon/blob/main/README.es.md).

## Configuración mínima

Dos opciones son obligatorias y sin ellas el add-on no arranca:

| Opción | Qué es |
|---|---|
| `auth_password` | La contraseña con la que autorizarás a Claude. Mínimo 12 caracteres, y se rechaza si es adivinable —repetitiva, una tirada del teclado, de las más usadas o con «hermes» dentro—. Genérala con `openssl rand -base64 18` o con tu gestor de contraseñas. Es el único secreto que protege tu casa: no reutilices ninguna |
| `public_hostname` | El hostname público por el que se llega a Hermes, **sin** `https://` y **sin** path final |

Y una que conviene revisar:

| Opción | Default | Qué es |
|---|---|---|
| `network_mode` | `tailscale` | `tailscale` si usas Funnel; `reverse_proxy` para cualquier otra cosa |

El resto de opciones, con sus valores por defecto y qué hace cada una, están
documentadas en el README.

## Conectar Claude

1. Arranca el add-on y comprueba en el log que aparece `hermes_started`.
2. En Claude: **Configuración → Conectores → Añadir conector personalizado**.
3. Pega `https://<tu_public_hostname>/mcp`.
4. Claude abre una página de autorización. Introduce tu `auth_password`.

La pantalla de autorización te dice **qué cliente** pide acceso y **a dónde**
irá el código. Léelo: es la única defensa contra que alguien te mande un enlace
de autorización propio.

## Qué esperar

Las acciones destructivas no se ejecutan a la primera. Devuelven una vista
previa de lo que van a hacer y un token; solo se ejecutan cuando Claude vuelve a
llamarlas con ese token. Verás a Claude enseñarte el cambio antes de aplicarlo.

## Problemas

El apartado *Si no arranca* del [README en español](https://github.com/Nadeon/Hermes-addon/blob/main/README.es.md#si-no-arranca)
recoge los mensajes de error concretos y
qué significa cada uno.

Para reportar un fallo de seguridad, **no abras un issue**: usa el
[formulario privado](https://github.com/Nadeon/Hermes-addon/security/advisories/new).
