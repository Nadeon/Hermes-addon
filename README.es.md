# Hermes — Home Assistant, completo, desde Claude

> Read this in: [English](README.md) | [Español](README.es.md)

[![Tests](https://github.com/Nadeon/Hermes-addon/actions/workflows/tests.yml/badge.svg)](https://github.com/Nadeon/Hermes-addon/actions/workflows/tests.yml)
[![Licencia](https://img.shields.io/badge/licencia-PolyForm%20Noncommercial-blue)](LICENSE)

Hermes es un **add-on de Home Assistant** que expone tu instalación a Claude
como servidor **MCP** (Model Context Protocol, el estándar con el que Claude
habla con sistemas externos). Son **351 herramientas**: encender luces, escribir
automatizaciones, editar ficheros de `/config`, gestionar add-ons, crear
backups, consultar el histórico.

> Desde Home Assistant 2026.2, la interfaz llama a los add-ons **aplicaciones**
> (*Apps* en inglés). Esta guía mantiene el término «add-on», igual que el
> nombre del repositorio y la API del Supervisor.

En la práctica: le pides a Claude «apaga las luces del salón», o «créame una
automatización que suba la persiana al amanecer pero no los domingos», y lo
hace — enseñándote antes qué va a tocar cuando la acción es destructiva.

Se instala añadiendo este repositorio a la tienda de add-ons de Home Assistant:
[cómo hacerlo](#instalación). Antes necesitas exponer Home Assistant a internet;
también está explicado abajo.

## Qué puede hacer — 351 herramientas

Los nombres son los que ve Claude. No hace falta que te los aprendas: hay una
herramienta, `hermes_guide`, que se los explica a Claude cuando los necesita.

| Familia | Nº | Qué cubre |
|---|---:|---|
| **Estado y servicios** | 7 | Leer estados, listar y llamar servicios, disparar eventos, renderizar plantillas Jinja |
| **Automatizaciones y scripts** | 14 | Crear, editar, borrar, activar, desactivar y ejecutar. Desde la 1.2.0, la vista previa de crear o editar la valida Home Assistant (triggers, condiciones y acciones, también a través de un blueprint) y no da token de confirmación si Home Assistant la rechazaría |
| **Escenas** | 7 | Incluido capturar el estado actual de la casa como escena nueva |
| **Helpers** | 59 | `input_boolean`, `input_number`, `input_select`, `input_text`, `input_button`, `input_datetime`, `counter`, `timer`, `schedule` |
| **Zonas y personas** | 10 | Zonas geográficas y seguimiento de personas |
| **Registros** | 26 | Entidades, dispositivos, áreas, plantas, etiquetas y categorías: renombrar, mover, ocultar, deshabilitar, borrar. Al borrar una planta o una etiqueta, la vista previa dice qué automatizaciones y scripts la usan como destino y dejarán de funcionar, aparte de los que solo están relacionados |
| **Integraciones** | 13 | Config entries y sus flujos de configuración, incluidos los de opciones |
| **Ficheros de `/config`** | 11 | Leer, escribir, mover, borrar, buscar, gestionar `secrets.yaml` y restaurar copias |
| **Lovelace** | 10 | Dashboards y recursos |
| **Add-ons** | 12 | Listar, instalar, arrancar, parar, actualizar, leer logs (también de arranques anteriores) y estadísticas |
| **Backups** | 13 | Completos y parciales, crear (también en un montaje de backup elegido) y restaurar. Además, de solo lectura, los backups de la integración `backup` de Home Assistant (HA 2025.1 o posterior) en todas sus ubicaciones (local, red, nube) y su configuración sin la contraseña de cifrado |
| **Supervisor y sistema** | 6 | Info del host y del core, validar configuración, reiniciar |
| **Montajes** | 9 | Montajes de red del Supervisor (CIFS y NFS) y de discos locales para backups, medios y `share`: listar, crear, editar, borrar, volver a comprobar y elegir el montaje por defecto de los backups, siempre con vista previa. También los ajustes de backup del Supervisor (cuándo un backup cuenta como viejo) y releer los backups de todas las ubicaciones. Las credenciales CIFS entran pero nunca salen (ni en respuestas, vistas previas, errores ni logs) |
| **Control de Core y del Supervisor** | 7 | Arrancar Home Assistant Core cuando está parado, reconstruirlo (también en modo seguro) y cambiar sus opciones del Supervisor (arranque, watchdog, audio…); recargar, reiniciar y reparar el Supervisor y cambiar sus opciones (zona horaria, país, log, actualización automática, diagnósticos). Todo lo que corta algo dice qué se corta, cuánto y qué le pasa a Hermes, y pide confirmación (recargar no); las opciones van por listas cerradas. Familia `system_control`, nueva en 1.2.0 |
| **Control del host** | 4 | Apagar el host y cambiar su hostname, la swap y la ranura de arranque de Home Assistant OS (por ejemplo, volver al OS anterior tras una actualización que va mal). Siempre con vista previa del estado actual y confirmación; la de apagar avisa de que nadie podrá encender el equipo a distancia. Familia `host_control`, nueva en 1.2.0 |
| **Red del host** | 3 | Releer el estado de la red del host, editar una interfaz secundaria (un Wi-Fi de respaldo, una segunda tarjeta) y crear VLAN. La interfaz principal (y la tarjeta que la lleva, si es una VLAN), la única conectada, o cualquiera si no se sabe cuál es la principal o de qué depende, se rechazan siempre, para que el agente no pueda cortarte el acceso; cada cambio enseña la interfaz antes y después con un aviso fuerte (el Supervisor no revierte), y la clave Wi-Fi nunca se devuelve ni va al log. Familia `host_network`, nueva en 1.2.0 |
| **Diagnóstico del sistema** | 11 | De solo lectura: logs de Home Assistant Core, del Supervisor, de los plugins (`dns`, `audio`, `multicast`) y del journal del host, también de arranques anteriores, con los secretos redactados; los identificadores y arranques del journal; servicios del host, qué llena el disco, versión y slots de Home Assistant OS, swap y discos candidatos a disco de datos |
| **Actualizaciones del sistema** | 8 | Qué tiene actualización (Core, OS, Supervisor, apps y plugins), buscar actualizaciones y actualizar Core, el OS y el Supervisor: la vista previa dice versiones, backup, qué se reinicia (el OS solo se aplica al reiniciar el host), salud del sistema y, en Core, la comprobación de la configuración, y no da token si el Supervisor la rechazaría. Entidades `update` (firmware de dispositivos, integraciones, HACS): listarlas, leer sus notas e instalarlas con versiones, notas y backup en la vista previa; las de Core, OS, Supervisor y apps se mandan a sus tools, y Hermes nunca se actualiza a sí mismo |
| **Histórico y estadísticas** | 4 | Histórico, logbook y estadísticas de largo plazo |
| **Diagnóstico** | 8 | Avisos de Reparaciones (listar, con su título y descripción como los enseña la interfaz, e ignorar), trazas de automatizaciones y scripts, qué está relacionado con un elemento y el centro de resolución del Supervisor (leer y descartar issues y sugerencias; aplicarlas, en la fila siguiente) |
| **Arreglos del centro de resolución** | 1 | Aplicar una sugerencia del Supervisor tras una vista previa que explica qué hace (qué corta, si se puede deshacer, qué backups completos borraría, qué arreglos automáticos aplica el Supervisor de paso), siempre con confirmación. Se rechazan las que no tienen arreglo, las que Hermes no sabe explicar, las que tocan los discos de datos y las que apuntan al propio Hermes. Familia `resolution_fixes`, nueva en 1.2.0 |
| **Marketplace (antes HACS)** | 11 | De solo lectura: estado, repositorios, actualizaciones disponibles, versiones publicadas y repositorios críticos o retirados. Detecta en cada llamada si Home Assistant trae el Marketplace integrado (2026.11 o posterior) o HACS 2.x. Las actualizaciones se instalan con la entidad `update`, con confirmación. Las 4 tools `ha_hacs_*` siguen como alias deprecados hasta 1.3.0 |
| **Espera de eventos** | 3 | Esperar a que ocurra algo, con filtros |
| **Utilidades** | 2 | `ping` y `hermes_guide` |
| **Estado del sistema** | 5 | De solo lectura: el informe de salud del sistema (lo que enseña Ajustes → Sistema → Reparaciones → Información del sistema), si Home Assistant o el host piden reinicio, cuánto tardó cada integración en arrancar y los manifiestos de las integraciones. Familia `system_status`, nueva en 1.2.0 |
| **Recorder** | 8 | Si el recorder está grabando (y si se graba una entidad), los problemas que Home Assistant ve en las estadísticas de largo plazo y los metadatos de las estadísticas que nombres (de solo lectura); y el mantenimiento de estadísticas con vista previa y confirmación: borrarlas (enteras o un periodo), convertir su unidad, corregir la unidad guardada, ajustar una suma e importar estadísticas horarias. Familia `recorder`, nueva en 1.2.0 |
| **Energía** | 2 | Leer la configuración del panel de energía (fuentes, dispositivos eléctricos y de agua) y guardarla con vista previa y confirmación: cada lista que pasas reemplaza esa lista, las demás se conservan, y la vista previa dice qué entra y qué sale. Familia `energy`, nueva en 1.2.0 |
| **Diagnóstico de Core** | 12 | El log del sistema de Home Assistant (errores agrupados, y limpiarlo), el log de errores en bruto cuando HA escribe uno, los niveles de log (leerlos y subir una integración a DEBUG para depurarla), validar automatizaciones y scripts antes de guardarlos, probar una condición, los diagnósticos de integraciones y dispositivos, y las notificaciones persistentes (listarlas y descartarlas) |
| **Flujos de integraciones** | 12 | Integraciones descubiertas (listar e ignorar), los dominios que se configuran por flujo, el título y las opciones de sistema de una integración (sondeo y entidades nuevas; desactivarlas pide confirmación), las subentries (añadir, reconfigurar, renombrar; borrar pide confirmación) y reconfigurar una integración (cada paso pide confirmación) |
| **Flujos de reparación** | 4 | Un aviso de Reparaciones con sus datos internos (redactados) y su flujo de reparación: abrirlo, enviar cada paso (cada paso pide confirmación) o abortarlo |
| **Tienda de apps** | 9 | Los repositorios de la tienda de apps del Supervisor: listarlos (con sus apps y cuáles están instaladas), añadir uno (código de terceros: en dos pasos, con la URL exacta en la vista previa y las credenciales de la URL tapadas), quitar uno (en dos pasos; se rechaza si es integrado o tiene apps instaladas), repararlo y recargar la tienda. El changelog y la documentación de la versión de la tienda de una app (texto de terceros, redactado, por trozos), si se puede instalar en este sistema y reconstruir una app instalada (en dos pasos). Instalar, actualizar y cambiar opciones comprueban antes: disponibilidad, changelog y validación de las opciones por el Supervisor. Familia `app_store`, nueva en 1.2.0 |
| **Blueprints** | 5 | Listar los blueprints de automatizaciones, scripts y plantillas, ver la configuración que da un blueprint con unas entradas, guardar uno que escribas, importar uno de una URL (lo descarga Home Assistant; la vista previa enseña el YAML entero y solo se guarda si no ha cambiado) y borrar uno que nadie use (guardar, importar y borrar, con confirmación). Familia `blueprints`, nueva en 1.2.0 |
| **Ayuda para automatizar** | 9 | Solo lectura: los triggers, condiciones y acciones de dispositivo que ofrece un dispositivo (listos para pegar en una automatización, con sus campos extra), qué abarca de verdad un target (entidades, dispositivos, áreas, plantas, etiquetas) y por qué, los nombres de los triggers, condiciones y acciones que le sirven, y esperar una vez a que salte un trigger (solo los que se sabe que solo escuchan). Familia `automation_assist`, nueva en 1.2.0 |
| **Configuración del núcleo** | 2 | Leer y cambiar la configuración general de Home Assistant (nombre, ubicación, unidades, zona horaria, moneda, país, idioma y URLs), con vista previa del antes y el después. Familia `core_config`, nueva en 1.2.0 |
| **Exposición a asistentes** | 3 | Qué entidades ven y controlan Assist, los agentes conversacionales (también la integración MCP Server) y Alexa o Google Assistant a través de Home Assistant Cloud: listarlas, exponerlas (con confirmación) y ocultarlas. Familia `assistant_exposure`, nueva en 1.2.0 |
| **Usuarios** | 4 | Listar los usuarios de Home Assistant y crearlos (sin credenciales), editarlos y borrarlos, con confirmación. Nunca contraseñas ni tokens; el propietario, el usuario de Hermes, los de sistema y el último administrador están protegidos. Familia `users`, nueva en 1.2.0 |
| **Red y HTTP de Core** | 3 | Qué adaptadores de red usa Home Assistant para descubrir dispositivos, y su servidor HTTP (puerto, SSL, proxy inverso, bloqueo de IP), con confirmación. Cambiar el HTTP reinicia Home Assistant y deja la configuración nueva 5 minutos a prueba hasta promoverla; un `server_host` que dejaría fuera a las apps que conectan directamente se rechaza. Familia `core_network`, nueva en 1.2.0 |
| **Assist y conversación** | 4 | Los agentes de conversación de Assist y sus idiomas (solo del integrado se sabe que funciona en local), las frases de los disparadores de frase de las automatizaciones, analizar frases con el agente integrado sin ejecutarlas (intent y entidades objetivo) y mandar una frase a Assist, que la ejecuta: siempre en dos pasos, con una vista previa de lo que reconoce Home Assistant o, con otro agente (un LLM en la nube), el aviso de que el texto se le envía. Familia `conversation`, nueva en 1.2.0 |
| **Backups de Home Assistant** | 6 | Dónde puede guardar Home Assistant sus backups (local, almacenamiento de red, nube) con su cifrado y su retención; la programación, la retención y el contenido de los backups automáticos; y crear backups (a medida o con los ajustes automáticos, cifrados con la clave de Home Assistant) borrarlos de todas sus ubicaciones y restaurarlos desde cualquiera (con una vista previa completa de lo que se sobrescribe; un backup cifrado sin contraseña usa la clave de Home Assistant). Todo lo que cambia algo, en dos pasos y con una estimación de los backups que borraría la retención. La clave de cifrado nunca sale de Home Assistant ni se cambia aquí. Familia `backup_integration`, nueva en 1.2.0 |
| **Comandos genéricos** | 4 | `ha_read_ws_command`, `ha_call_ws_command`, `sv_read_api` y `sv_call_api`: lo que ninguna otra tool cubre, y solo lo que permite la tabla de comandos de Hermes (las escrituras, siempre en dos pasos) |

Hay una herramienta más, auxiliar, que solo se registra con `HERMES_DEV=1` y
que en una instalación normal no existe.

Si a tu cliente le pesan tantas herramientas, apaga grupos enteros con la
opción `tool_families_disabled` (por ejemplo `lovelace` o `marketplace`); la
lista de familias está en [DOCS.md](hermes/DOCS.md). `ping` y `hermes_guide`
están siempre, y apagando las familias nuevas de la 1.2.0
(`generic_commands`, `system_diagnostics`, `system_status`, `recorder`,
`core_diagnostics`, `integration_flows`, `repair_flows`, `mounts`,
`system_updates`, `app_store`, `blueprints`, `automation_assist`, `energy`,
`system_control`, `resolution_fixes`, `core_config`,
`assistant_exposure`, `users`, `core_network`, `host_control`,
`host_network`, `conversation` y `backup_integration`)
tienes exactamente la lista de herramientas de la 1.1.2.

Las herramientas destructivas devuelven, en la primera llamada, una vista previa
y un `confirmation_token`. No hacen nada hasta que se les vuelve a llamar con
ese token. Es lo que impide que un malentendido acabe reiniciando tu casa.

## Qué necesitas

- **Home Assistant OS o Supervised.** Hermes es un add-on y necesita el
  Supervisor: no funciona en HA Container ni en HA Core.
- **Exponer Home Assistant a internet**, para que Claude llegue. Hermes no lo
  hace por ti; la siguiente sección explica las tres formas de conseguirlo.
- **Un plan de pago de Claude.** Los Custom Connectors, que es como se conecta
  Hermes, no están disponibles en el plan gratuito.
- Arquitectura `amd64` o `aarch64`, y Home Assistant **2024.10.0** o superior. Hermes guarda las
  automatizaciones con las claves en plural (`triggers`, `actions`), que Home
  Assistant solo entiende desde la 2024.10. El add-on lo declara, así que con
  una Home Assistant anterior el Supervisor se niega a instalarlo o actualizarlo.

## Cómo se expone Hermes a internet

Hermes **no habla TLS**: escucha HTTP plano en un puerto local y da por hecho
que algo delante termina el TLS y le hace proxy. Ese "algo" es cosa tuya, y la
opción **`network_mode`** le dice a Hermes con cuál cuenta:

| `network_mode` | Quién publica el hostname | Puertos abiertos en el router |
|---|---|---|
| `tailscale` *(por defecto)* | Add-on de Tailscale con Funnel | Ninguno |
| `reverse_proxy` | Cloudflare Tunnel, Nginx Proxy Manager, Caddy… | Ninguno con un túnel; **443** con proxy clásico |

Lo único que Hermes necesita, sea cual sea la opción, es:

1. Un **hostname público con HTTPS** que llegue hasta él (`public_hostname`).
2. Que ese proxy reenvíe a **`mcp_bind`:8765** en HTTP plano.

> [!IMPORTANT]
> Hermes queda accesible desde internet y su única barrera es la contraseña de
> `auth_password`. Genera una larga y aleatoria. Un túnel (Tailscale o
> Cloudflare) es más seguro que abrir el 443 del router, porque no expone
> ningún puerto de tu red.

### Opción A — Tailscale Funnel *(la más sencilla)*

No abre ningún puerto del router y el certificado lo gestiona Tailscale.
Es la opción con la que Hermes está más probado.

1. Instala el **add-on de Tailscale** en HAOS. Es el add-on comunitario
   (repositorio Home Assistant Community Add-ons, `a0d7b954`), no uno oficial,
   aunque la tienda lo muestra por defecto.
2. Configura **`userspace_networking: false`**. Es obligatorio: sin eso no se
   crea la interfaz `tailscale0` y, en `network_mode: tailscale`, Hermes espera
   a que exista y no arranca.
3. Habilita **Funnel** y apúntalo al puerto de Hermes. El comando se ejecuta
   **dentro del contenedor del add-on de Tailscale**: ahí viven el binario
   `tailscale` y el socket de `tailscaled`, y como ese add-on comparte la red
   del host, desde dentro `127.0.0.1:8765` es Hermes. Ninguna opción del
   add-on sirve: `share_homeassistant` solo publica Home Assistant y
   `services` expone otros puertos solo dentro de la tailnet (Serve), no a
   internet (Funnel).

   El add-on de Tailscale no tiene terminal en la interfaz de HA. La forma
   más directa de llegar a él:
   1. Instala **Advanced SSH & Web Terminal** (el de la comunidad; el oficial
      "Terminal & SSH" no da acceso a Docker).
   2. En su pestaña **Información**, desactiva **Modo de protección**. Sin
      eso no hay comando `docker`. Puedes volver a activarlo al terminar.
   3. Desde su terminal web:
      ```
      docker exec -it addon_a0d7b954_tailscale tailscale funnel --bg --https=8443 8765
      docker exec -it addon_a0d7b954_tailscale tailscale funnel status
      ```
      Si el nombre del contenedor no coincide, `docker ps | grep tailscale`
      lo da. `funnel status` debe listar `https://<hostname>:8443` apuntando
      a `http://127.0.0.1:8765`.

   **Por qué 8443 y no 443.** Funnel solo admite los puertos 443, 8443 y
   10000. La opción `share_homeassistant: funnel` del add-on de Tailscale
   publica Home Assistant en el 443 por defecto, en la misma ruta `/`, y un
   segundo Funnel en el mismo puerto y ruta sustituye al primero: gana el
   último que se configuró y el otro deja de responder. Con Hermes en el 8443
   (o el 10000) no chocan nunca, ni ahora ni si activas esa opción más
   adelante. Si no usas `share_homeassistant: funnel`, el 443 sigue valiendo:
   `tailscale funnel --bg 8765` y un `public_hostname` sin puerto.

   Cuatro cosas a saber:
   - **Funnel tiene que estar permitido en tu tailnet**: HTTPS habilitado y
     el atributo `funnel` en la política de acceso. Si no lo está, el comando
     imprime un enlace al panel de Tailscale para activarlo; no falla en
     silencio.
   - **El Funnel vive en el estado de `tailscaled`, no en las opciones del
     add-on**, así que la interfaz de HA no lo muestra. Sobrevive a reinicios
     y actualizaciones del add-on, pero no a reinstalarlo. Si algún día Hermes
     deja de ser alcanzable tras tocar Tailscale, lo primero es
     `tailscale funnel status`.
     Una excepción en las actualizaciones: la primera vez que arranca un
     add-on de Tailscale 0.14.0 o posterior, ejecuta una sola vez
     `tailscale serve reset`, que borra toda la configuración de Serve y
     Funnel, también esta. Si configuraste el Funnel con una versión anterior
     y luego actualizaste, vuelve a lanzar el comando
     `funnel --bg --https=8443 8765`. No vuelve a ocurrir.
   - `--bg` es lo que lo hace persistente. Sin él, el Funnel dura lo que dure
     el comando en primer plano.
   - **Hermes y `share_homeassistant: funnel` tienen que ir en puertos
     distintos.** Esa opción publica Home Assistant con `tailscale funnel
     --https=<share_on_port> --set-path=/`, y `share_on_port` vale `443` por
     defecto. Con Hermes en el 8443, déjalo en 443 (o usa el 10000); solo no
     lo pongas en 8443. Notarás que han chocado porque `tailscale funnel
     status` muestra `/` en el puerto de Hermes apuntando al de Home Assistant
     (`8123` por defecto) en vez de a `http://127.0.0.1:8765`.
4. En las opciones de Hermes:
   - `network_mode`: `tailscale`
   - `public_hostname`: el hostname que te da Funnel **seguido del puerto**
     (ej. `homeassistant.tailXXXX.ts.net:8443`), **sin esquema ni path**. Con
     el Funnel en el 443, el hostname solo.
   - `mcp_bind`: `127.0.0.1` (el add-on de Tailscale comparte la red del host,
     así que alcanza el loopback)

   La URL del conector en Claude será
   `https://homeassistant.tailXXXX.ts.net:8443/mcp`.

**Pasar una instalación existente del 443 al 8443.** El puerto forma parte de
la dirección que usa Claude y de las URL de OAuth que anuncia Hermes, así que
hay que volver a añadir el conector:

1. Quita el Funnel viejo y crea el nuevo, desde el mismo terminal:
   ```
   docker exec -it addon_a0d7b954_tailscale tailscale funnel --https=443 off
   docker exec -it addon_a0d7b954_tailscale tailscale funnel --bg --https=8443 8765
   ```
   Si también publicas Home Assistant con `share_homeassistant: funnel`, sáltate
   la primera línea: el 443 pasa a ser de Home Assistant. Reinicia el add-on
   de Tailscale para que lo vuelva a publicar.
2. En las opciones de Hermes, cambia `public_hostname` a
   `homeassistant.tailXXXX.ts.net:8443` y reinicia el add-on.
3. En Claude, quita el conector de Hermes y vuelve a añadirlo con
   `https://homeassistant.tailXXXX.ts.net:8443/mcp`. Autorízalo con tu
   `auth_password`.

---

### Opción B — Cloudflare Tunnel *(recomendada si no usas Tailscale)*

Mismo modelo que Funnel —sin abrir puertos— pero con tu propio dominio. Es
gratis y permite además poner Cloudflare Access delante como segunda barrera.

1. Instala un add-on de **Cloudflared** en HAOS y complétalo con tu dominio.
2. Añade una *ingress rule* que apunte a Hermes. La dirección depende de la red
   del add-on de Cloudflared:
   - Si comparte la red del host (`host_network: true`) → `http://127.0.0.1:8765`
   - Si está en la red puente de HAOS → `http://172.30.32.1:8765`
3. En las opciones de Hermes:
   - `network_mode`: `reverse_proxy`
   - `public_hostname`: tu dominio (ej. `hermes.midominio.com`)
   - `mcp_bind`: **`127.0.0.1`** si el túnel comparte red de host, o
     **`172.30.32.1`** si está en la red puente

> [!WARNING]
> Este es el punto donde más gente se atasca. Con `mcp_bind: 127.0.0.1` el
> puerto solo existe en el *loopback del host*: un add-on que corra en la red
> puente **no puede alcanzarlo** y verás errores de conexión rechazada en el
> túnel. Si tu proxy no comparte la red del host, usa `172.30.32.1`.

---

### Opción C — Proxy inverso clásico (Nginx Proxy Manager, Caddy…)

Válida si ya tienes un dominio propio y un proxy montado. A cambio, **exige
abrir el puerto 443** de tu router: tu Home Assistant queda directamente
expuesto a internet, así que es la opción con más superficie de ataque.

1. Monta el proxy (add-on de **Nginx Proxy Manager**, **Caddy**, o uno externo)
   con un certificado válido para tu dominio (Let's Encrypt, DuckDNS…).
2. Crea un host que haga proxy de **todas** las rutas (`/`) hacia
   `http://<mcp_bind>:8765`. No restrinjas a `/mcp`: Hermes sirve también los
   endpoints de OAuth y de discovery (`/.well-known/…`, `/authorize`, `/token`,
   `/register`, `/revoke`) y sin ellos el cliente no puede autenticarse.
3. Asegúrate de que el proxy **no reescribe el `Host`**: Hermes valida esa
   cabecera contra `public_hostname` como protección anti DNS-rebinding.
4. Reenvía el 443 del router al proxy.
5. En las opciones de Hermes:
   - `network_mode`: `reverse_proxy`
   - `public_hostname`: tu dominio
   - `mcp_bind`: la dirección que alcance tu proxy (`127.0.0.1` si comparte red
     de host; `172.30.32.1` desde la red puente)

> [!CAUTION]
> No pongas `mcp_bind: 0.0.0.0` salvo que sepas exactamente lo que haces: eso
> publica Hermes **en HTTP plano** en toda tu red local, sin cifrar, saltándose
> el TLS del proxy.

---

## Instalación

1. En Home Assistant: **Configuración → Aplicaciones → Instalar aplicación →
   ⋮ → Repositorios** (antes de HA 2026.2: **Configuración → Complementos →
   Tienda de complementos → ⋮ → Repositorios**), y pega:

   ```
   https://github.com/Nadeon/Hermes-addon
   ```

2. Cierra el diálogo. Hermes aparece en la tienda, en su propia sección.
   Ábrelo y pulsa **Instalar**.

   > La imagen viene precompilada para `amd64` y `aarch64`, así que instalar
   > son unos segundos: no se compila nada en tu equipo.

3. Rellena la configuración:
   - **`auth_password`** *(obligatorio)*: la contraseña con la que autorizarás a
     Claude. Mínimo 12 caracteres, y Hermes comprueba además que no sea
     adivinable: rechaza las repetitivas, las tiradas del abecedario, de los
     dígitos o del teclado, las de las listas más usadas y las que llevan dentro
     «hermes», «homeassistant» o tu propio hostname.
     Genérala con tu gestor de contraseñas, o con `openssl rand -base64 18`.
     Es el único secreto que protege tu casa.
   - **`public_hostname`** *(obligatorio)*: el hostname público, sin `https://`
     ni path final. Si no se sirve en el 443, añade el puerto
     (`homeassistant.tailXXXX.ts.net:8443`).
   - **`network_mode`**: `tailscale` o `reverse_proxy`, según la opción que
     hayas montado arriba.
   - **`mcp_bind`**: `127.0.0.1` por defecto; cámbialo solo si tu proxy no
     comparte la red del host.

4. Arranca el add-on y mira el log. Si todo va bien verás una línea
   `hermes_started` con el modo elegido:
   ```json
   {"event": "hermes_started", "network_mode": "tailscale", "mcp_bind": "127.0.0.1", ...}
   ```

Cuando haya una versión nueva, Home Assistant te avisa en la propia tienda y se
actualiza con un clic.

<details>
<summary>Instalarlo a mano, sin añadir el repositorio</summary>

Si prefieres no añadir un repositorio de terceros a tu Home Assistant, copia
**el contenido de la carpeta `hermes/`** (no la raíz del repositorio) a
`/addons/hermes` en el host, por Samba o SSH. Aparecerá en **Local apps**
(**Local add-ons** en versiones anteriores) tras un *Buscar actualizaciones*.

Instalado así no recibes avisos de versión nueva: cada actualización es volver a
copiar los ficheros.

Esta es también la vía si quieres **construir la imagen tú mismo** en vez de
descargar la publicada: borra la línea `image:` de `config.yaml` y el Supervisor
compilará desde el `Dockerfile`. Sobre Alpine son entre cinco y diez minutos en
un x86, y bastante más en una Raspberry Pi, porque `pydantic-core`, `aiohttp` y
`cryptography` se compilan desde fuente.

</details>

### Si no arranca

| Síntoma en el log | Causa probable |
|---|---|
| `No Tailscale CGNAT IP … found` | Estás en `network_mode: tailscale` sin el add-on de Tailscale listo, o con `userspace_networking: true`. Corrígelo o cambia a `reverse_proxy`. |
| `auth_password no está configurado` | Falta la contraseña. |
| `auth_password no es lo bastante fuerte` | Es corta, repetitiva, una tirada del abecedario, de los dígitos o del teclado, una de las más usadas, o lleva dentro «hermes», «homeassistant», «hassio», «supervisor» o tu propio hostname. El mensaje dice qué regla incumple. |
| `public_hostname no está configurado` | Falta el hostname. |
| `public_hostname inválido` | Lo has puesto con `https://` delante, con un path detrás, o con barras. Va solo el hostname. |
| `trusted_proxy_ips contiene un valor que no es una IP ni una red` | Una errata en esa lista. Escribe IPs sueltas (`172.30.32.2`) o rangos CIDR (`172.30.32.0/23`). |
| `SUPERVISOR_TOKEN no está disponible` | No estás en Home Assistant OS ni Supervised. Hermes es un add-on y necesita el Supervisor. |
| `network_mode inválido` | Solo se admiten `tailscale` y `reverse_proxy`. |
| `HA core … < minimum supported 2024.10.0` | Tu Home Assistant es demasiado antiguo. Actualízalo. |
| `No se puede escuchar el health en …` | Otro proceso ocupa el puerto 8766, o falta la red puente de HAOS. El mensaje termina con una pista de cuál de las dos. |
| `Crash loop detectado` | Hermes arrancó 10 veces en 5 minutos y se detuvo solo. Corrige la causa que aparece antes en el log y arranca el add-on a mano. Los reinicios manuales también cuentan. |
| El túnel da *connection refused* | `mcp_bind` no es alcanzable desde tu proxy. Si está en la red puente, usa `172.30.32.1`. Un `mcp_bind` en blanco se convierte sin aviso en `127.0.0.1`. |

`ha_core_version_untested` es solo un aviso: tu Home Assistant es más nuevo que
la última versión con la que se comprobó Hermes. Hermes sigue funcionando.


### Llamadas que fallan en ráfaga (502)

Medido en septiembre de 2026 contra una instalación real, desde Claude Code, con
Hermes 1.0.5 y 1.0.8:

- Cuando un cliente lanza **6 o más llamadas en paralelo**, entre el 15 % y el
  30 % vuelven con un `502` generado por Cloudflare para `api.anthropic.com`
  («origin returned an invalid or incomplete response»), en el mismo segundo
  que las que sí entran.
- Esas llamadas **nunca llegan a Hermes**: no aparecen en su log, y el log de
  Tailscale no registra ningún error de proxy para ellas.
- Las llamadas sueltas, y las ráfagas de hasta 4, no fallaron nunca. Hermes
  responde cada una en 3 a 15 ms.

No es un fallo de Hermes ni de tu red: la pérdida ocurre entre el proxy de
conectores de Anthropic y el ingress de Funnel. En claude.ai, que hace una
llamada cada vez, no se nota. Cómo distinguirlo de un problema real: una llamada
fallida que **sí** está en el log de Hermes es de Hermes; una que **no** está,
nunca llegó. Busca una línea `http_request` con estado 4xx/5xx, y también
`auth_rejected`, `rate_limit_pre_auth`, `rate_limit_post_auth`,
`auth_failure_flood` y `body_too_large`: esos rechazos ocurren antes de que la
petición llegue a registrarse como `http_request`. Para aislar el lado de
Funnel, lanza 8 `curl` en paralelo desde fuera de tu red contra
`https://<public_hostname>/.well-known/oauth-protected-resource`, sin pasar del
límite pre-auth de 20 por minuto: si fallan, es Funnel; si no, es aguas arriba.

> [!IMPORTANT]
> **El rate limit por IP se comporta distinto en cada modo.** uvicorn solo hace
> caso a `X-Forwarded-For` si la conexión llega desde `127.0.0.1`. Con
> `tailscale`, tailscaled hace proxy desde el loopback y reescribe esa cabecera
> con la IP real del cliente, así que el límite por IP funciona de verdad
> (comprobable en el log: los escáneres de internet aparecen con su IP
> pública, y una cabecera falsificada a mano se ignora).
>
> Con `reverse_proxy` y `mcp_bind` en la red puente (`172.30.32.1`), la conexión
> ya no llega desde el loopback: uvicorn ignora la cabecera y **todas** las
> peticiones se ven con la IP del proxy, así que el cubo por IP pasa a ser un
> techo global. El freno anti-fuerza-bruta del login sale peor parado: bloquea
> cada IP tras 5 contraseñas fallidas, y si todas las peticiones se ven con la
> IP del proxy, **5 fallos de cualquiera bloquean el login a todos, tú
> incluido**, con una espera que crece hasta 5 minutos por escalón. No es una
> vulnerabilidad —nada del sistema autoriza por IP, la IP solo alimenta los
> límites y los logs—, pero es una denegación de servicio al alcance de
> cualquiera. Configura `trusted_proxy_ips` (abajo) y desaparece.
>
> **`trusted_proxy_ips` devuelve los límites por IP en ese modo.** Pon ahí la
> dirección de tu proxy, o el rango donde vive (`172.30.32.0/23` es la red
> puente de HAOS entera), y Hermes vuelve a creerse su `X-Forwarded-For`: el
> cubo pre-auth, el de fallos de autenticación y el freno del login vuelven a
> contar cliente a cliente. Confía en lo mínimo: cualquiera dentro de un rango
> de confianza puede falsificar la IP del cliente —lo que solo desvirtúa los
> límites y los logs, nunca la autorización—.

### Claude Code corta las llamadas lentas a los 60 s

Claude Code abandona una llamada si no recibe ningún byte en 60 segundos.
Hermes responde en streaming y manda un *ping* cada 15 s, así que una espera
larga de `ha_wait_for_event` no se corta. Si el proxy de delante almacena la
respuesta entera antes de reenviarla, los *pings* llegan tarde: amplía el plazo
en Claude Code con la variable de entorno `MCP_TOOL_TIMEOUT` (en milisegundos)
o con `timeout` en la entrada del servidor.

## Conectar Claude

1. En Claude, móvil o escritorio: **Configuración → Conectores → Añadir conector
   personalizado**.
2. Pega la URL de tu servidor:

   ```
   https://<tu_public_hostname>/mcp
   ```

   `public_hostname` lleva el puerto cuando lo hay: con el Funnel de Tailscale
   en el 8443 es `https://homeassistant.tailXXXX.ts.net:8443/mcp`.

3. Claude abre la página de autorización de Hermes. Introduce la
   `auth_password` que pusiste en la configuración del add-on.

4. Listo. A partir de ahí, pídele cosas en lenguaje normal.

> [!IMPORTANT]
> La pantalla de autorización te dice **qué cliente** pide acceso y **a qué
> dirección** irá el código. Léelo antes de aceptar: es la única defensa contra
> que alguien te haga llegar un enlace de autorización con su propio destino.

Lo que ocurre por debajo, si tienes curiosidad: Claude descubre los endpoints
OAuth a partir del `401` que devuelve Hermes, se identifica, te manda al login,
y a cambio de tu contraseña obtiene un token. No hay que copiar ni pegar
ninguna clave. Los clientes que publican un documento de metadatos (CIMD), como
Claude Code, se identifican con la URL de ese documento: Hermes lo descarga, lo
comprueba, y la pantalla de autorización muestra el host de esa URL. Los demás
registran un cliente automáticamente (RFC 7591), como hasta ahora. Cada
redirección de vuelta al cliente lleva el parámetro `iss` (RFC 9207), para que
el cliente sepa que la respuesta viene de Hermes.

**Cuánto dura.** Cada autorización vale **7 días**: Claude renueva su acceso cada
hora dentro de esa semana, pero cuando se agota el conector vuelve a pedirte la
contraseña. Puede haber hasta 5 autorizaciones vivas a la vez (móvil,
escritorio…); la sexta cierra la que lleva más tiempo sin usarse.

**Cerrar todas las sesiones.** Cambia `auth_password` y reinicia el add-on: al
arrancar, Hermes detecta la contraseña nueva y cierra todas las sesiones
abiertas, así que cada cliente tiene que autorizarse otra vez con ella. En el
log aparece `oauth_sessions_revoked_password_changed`. Desde la 1.0.11; en
versiones anteriores las sesiones seguían vivas hasta cumplir sus 7 días.

**Qué esperar la primera vez.** Al conectar, Hermes le entrega a Claude un
resumen de las familias de herramientas disponibles. Cuando necesita detalle de
un área concreta, Claude consulta `hermes_guide` por su cuenta — no tienes que
hacer nada.

## Opciones de configuración

La página de configuración de la app enseña el nombre y una descripción corta
de cada opción, en inglés o en español (`hermes/translations/`). El detalle
completo está aquí abajo.

| Opción | Default | Descripción |
|--------|---------|-------------|
| `auth_password` | _(obligatorio)_ | Contraseña del flujo OAuth. Mínimo 12 caracteres y se comprueba que no sea adivinable: Hermes no arranca con una débil |
| `public_hostname` | _(obligatorio)_ | Hostname público por el que se llega a Hermes, sin esquema ni path. Con un puerto distinto del 443, inclúyelo (`host:8443`) |
| `network_mode` | `tailscale` | Quién publica el hostname: `tailscale` (Funnel) o `reverse_proxy` (Cloudflare Tunnel, Nginx, Caddy…) |
| `mcp_bind` | `127.0.0.1` | Dirección donde escucha Hermes. Usa `172.30.32.1` si tu proxy corre en la red puente de HAOS |
| `trusted_proxy_ips` | `[]` | Proxies cuyo `X-Forwarded-For` se cree, como IPs sueltas o rangos CIDR (`172.30.32.0/23` es la red puente de HAOS). Vacío significa confiar solo en `127.0.0.1`, lo que con `reverse_proxy` convierte todos los límites por IP en un único cubo global. Quien esté dentro de un rango de confianza puede falsificar la IP del cliente (solo afecta a límites y logs, nunca a la autorización) |
| `log_level` | `info` | Nivel de log (`debug`/`info`/`warning`/`error`) |
| `tool_families_disabled` | `[]` | Familias de herramientas que Hermes no registra, para que el cliente cargue menos: `services`, `automations`, `helpers`, `events`, `data`, `registries`, `diagnostics`, `config_entries`, `filesystem`, `supervisor`, `backups`, `lovelace`, `marketplace`, `generic_commands`, `system_diagnostics`, `system_status`, `recorder`, `core_diagnostics`, `integration_flows`, `repair_flows`, `mounts`, `system_updates`, `app_store`, `blueprints`, `automation_assist`, `energy`, `system_control`, `resolution_fixes`, `core_config`, `assistant_exposure`, `users`, `core_network`, `host_control`, `host_network`, `conversation` y `backup_integration`. `base` (`ping` y `hermes_guide`) no se puede desactivar. Un nombre desconocido, o `base`, impide arrancar y el log dice qué valor falla y cuáles valen |
| `log_redact_network` | `true` | Sustituye en el log tu `public_hostname`, los hosts de `external_url` e `internal_url` de Home Assistant, los nombres `*.ts.net` y las IPs que no sean de loopback (también escritas como `ip-a-b-c-d`) por marcadores, para que puedas pegarlo al pedir ayuda. Desactívala solo para diagnosticar la red: el log lo avisa con `log_network_redaction_disabled`. Los secretos se redactan siempre |
| `oauth_cimd_enabled` | `true` | Acepta clientes que se identifican con una URL de metadatos (CIMD), como Claude Code. Desactívala solo si un cliente falla con CIMD: el registro dinámico (DCR) sigue funcionando igual |
| `oauth_cimd_allowed_hosts` | `[]` | Hosts cuyos documentos CIMD acepta Hermes (p. ej. `claude.ai`, donde publica el suyo Claude Code). Vacía significa **cualquier host público**: cada descarga sale de la IP de tu casa hacia un host que cualquiera puede elegir sin la contraseña. Pon solo los hosts que uses; ver `hermes/DOCS.md` |
| `safety_backup_enabled` | `false` | Backup **completo** de HAOS automático antes de escribir en `/config`. Desactivado por defecto (genera varios GB). El backup por-fichero se hace siempre. Si el backup falla, o Hermes no puede saber si terminó, la escritura no se hace (`safety_backup_job_failed`, `safety_backup_state_unknown`) |
| `safety_backup_encryption` | `auto` | Cifrado de los safety backups (nuevo en 1.2.0) con la clave de los backups de Home Assistant, la de su kit de emergencia: Hermes la lee de Home Assistant en cada backup y nunca la guarda ni la devuelve, y puedes restaurarlos desde Home Assistant aunque Hermes esté roto. `auto`: cifrados si Home Assistant tiene clave y, si no, sin cifrar y dicho en la respuesta y en el log. `required`: sin clave no hay safety backup (`encryption_key_unavailable`) y la escritura no se hace; un safety backup reciente sin cifrar no cuenta. `off`: sin cifrar, como en la 1.1.2. Cualquier otro valor impide arrancar |
| `mcp_max_requests_per_minute` | `120` | Rate limit global post-auth |
| `mcp_preauth_max_requests_per_minute_per_ip` | `20` | Rate limit pre-auth por IP. Aplica a la superficie pública (OAuth y discovery), y el mismo valor acota por IP las peticiones a rutas protegidas que llegan sin token o con uno inválido. Las válidas las gobierna `mcp_max_requests_per_minute` |
| `response_max_bytes` | `131072` | Cap de respuesta de cualquier tool (128 KiB); por encima se recorta y se indica con `truncated: true`. Máximo efectivo `524288` (512 KiB): un valor guardado mayor se recorta. Súbelo hasta ahí si las respuestas te llegan truncadas |
| `ha_ws_max_msg_size_bytes` | `16777216` | Cap de mensaje WS hacia HA (16 MiB). Un resultado más grande cierra la WebSocket entera, no solo esa llamada, y deja `ha_ws_message_too_big` en el log. Un `4194304` guardado (el defecto anterior) se trata como no personalizado y pasa a 16 MiB |
| `max_request_body_bytes` | `4194304` | Cap del cuerpo de una petición HTTP autenticada (4 MB). Los endpoints públicos de OAuth llevan su propio tope fijo de 64 KiB, que no depende de esta opción |
| `max_concurrent_requests` | `64` | Peticiones simultáneas que acepta el servidor. Acota la memoria máxima en vuelo (`max_concurrent_requests × max_request_body_bytes`). Claude lanza ráfagas de ~24 llamadas, así que 64 deja holgura |
| `wait_for_event_max_seconds` | `90` | Máximo timeout permitido para `ha_wait_for_event` (10–220; un valor guardado por encima de 220 se recorta) |
| `wait_for_event_max_concurrent` | `5` | Máximo de `ha_wait_for_event` simultáneos (1–20) |
| `safety_backup_keep` | `3` | Retención de los safety backups automáticos (0–50). Tras cada uno correcto, Hermes conserva este número de los más recientes y borra el resto, como mucho 5 por vez. Un safety backup que terminó con errores en sus sub-jobs (una app que no se pudo guardar) está incompleto: no cuenta entre los que se conservan y se borra el primero. Solo borra los que él mismo anotó al crearlos: nunca uno tuyo, aunque se llame `hermes-safety-…`, ni uno protegido con contraseña (salvo los que el propio Hermes cifró con la clave de Home Assistant, desde la 1.2.0), parcial o copiado a otra ubicación. `0` la desactiva. Solo actúa con `safety_backup_enabled` |
| `safety_backup_window_minutes` | `30` | Si Hermes hizo su propio backup de seguridad hace menos de esto, no se hace otro. Los backups hechos a mano o por otras herramientas no cuentan. Mientras se hace, la escritura espera hasta 5 minutos, y se cancela si el backup falla |
| `file_backup_max_per_path` | `20` | Copias que se guardan de cada fichero antes de sobrescribirlo |
| `file_backup_max_total_mb` | `200` | Tope total del directorio de copias por fichero |
| `config_write_min_interval_seconds` | `5` | Segundos mínimos entre dos escrituras en `/config` |
| `config_write_max_per_minute` | `10` | Escrituras máximas por minuto en `/config` |
| `health_startup_grace_seconds` | `120` | Margen de arranque **por paso**, no total: los pasos 4 (Tailscale), 6 (`/core/info`) y 8 (WebSocket de HA) pueden usar cada uno el presupuesto entero |
| `health_reconnect_tolerance_seconds` | `300` | Cuánto puede estar caída la WebSocket con HA antes de que `/health` diga `degraded_long` en vez de `degraded`. Nunca devuelve 503: reiniciar no arregla una caída de Core, y el bucle de reconexión se recupera solo |

> [!NOTE]
> **Si tenías valores guardados.** La interfaz del add-on guarda el valor por
> defecto aunque no lo hayas tocado, así que un `response_max_bytes` de
> `1048576` (el defecto anterior, 1 MiB) se trata como no personalizado y pasa
> a `131072`. Un valor por encima de `524288`, o un
> `wait_for_event_max_seconds` por encima de `220`, se recorta al máximo. El
> add-on arranca igual y lo anota en el log con
> `config_legacy_default_replaced` o `config_value_clamped`, con el valor
> guardado y el aplicado. Estos límites son los que aceptan los clientes de
> Claude.

### Palancas de seguridad

Estas cuatro cambian **qué puede hacer Claude sin preguntarte**. Merece la pena leerlas:

| Opción | Default | Descripción |
|--------|---------|-------------|
| `call_service_denylist_extra` | `[]` | Servicios adicionales que exigirán confirmación explícita, además de los ~70 que ya trae Hermes. Formato `dominio.servicio`, admite comodín (`shell_command.*`) |
| `call_service_restricted_entities` | `[]` | Entidades concretas que exigirán confirmación aunque el servicio no esté vetado. Útil para `script.abrir_garaje` y compañía |
| `fire_event_allowlist` | `[]` | Tipos de evento que `ha_fire_event` puede disparar. Vacío significa que la herramienta está deshabilitada: hay que nombrar explícitamente cada evento permitido |
| `call_service_auto_classify_dangerous` | `true` | Al arrancar y tras recargar scripts o automatizaciones desde Hermes, Hermes lee tus scripts y automatizaciones y marca automáticamente como restringidas las que invocan servicios peligrosos (la lista de serie más `call_service_denylist_extra`). Desactivarla solo apaga esas dos revisiones: los scripts y automatizaciones que se guardan desde Hermes (`ha_create_or_update_script`, `ha_create_or_update_automation`) se revisan siempre y se restringen si son peligrosos, aunque la opción esté desactivada |

Ver `config.yaml` para el schema completo con sus rangos válidos.

## Seguridad

- **OAuth 2.1 con PKCE obligatorio** (no bearer estático): tokens opacos
  hasheados (SHA-256), auth codes de un solo uso, revocación (RFC 7009).
- **Contraseña fuerte obligatoria**: `auth_password` ≥ 12 caracteres, filtro de calidad + throttle
  con backoff exponencial ante intentos fallidos (anti-fuerza-bruta).
- **DCR endurecido**: validación de `redirect_uris` y tope de clientes.
- **Tokens de confirmación** para toda acción destructiva.
- **Herramientas genéricas gobernadas por una tabla fail-closed**:
  `ha_read_ws_command`, `ha_call_ws_command`, `sv_read_api` y `sv_call_api`
  solo ejecutan los comandos y rutas que permite la tabla de comandos de
  Hermes; lo demás, el proxy de Core del Supervisor y cualquier ruta dirigida
  al propio Hermes se rechazan antes de llegar a Home Assistant. Las escrituras
  pasan siempre por una vista previa y un token.
- **Filesystem `/config`**: anti-traversal, blacklist de secretos, allowlist
  *default-deny* en `.storage/`, *managed paths*, backup antes de cada escritura.
- **Validación anti path-injection** de identificadores (slug, `entry_id`…)
  + guard central en el cliente HA.
- **Cabeceras de seguridad** (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, CSP) y límite de tamaño de cuerpo (incluido `chunked`).
- **Redacción de secretos** en todos los logs.
- **Redacción de red** en el log (`log_redact_network`, activa por defecto):
  tu hostname y tus IPs se sustituyen por marcadores, para poder compartirlo.
- **Rate limit** global tras autenticar, y un techo aparte para la superficie
  pública (OAuth y discovery). Los fallos de autenticación tienen su propio
  cubo, para que alguien sin credenciales no pueda gastarte el tuyo.
- **CORS cerrado** (no hay `Access-Control-Allow-Origin`).
- **Escucha solo donde le digas** (`mcp_bind`, por defecto `127.0.0.1`): nunca
  se publica en la red directamente, siempre hay un proxy delante.

Modelo de amenaza, supuestos y limitaciones conocidas: ver [SECURITY.md](SECURITY.md).
Bajo qué reglas está escrito todo esto: [docs/PRINCIPIOS.md](docs/PRINCIPIOS.md).

## Limitaciones conocidas

- **No hay streaming de eventos.** `ha_wait_for_event` espera **un** evento con
  timeout; no existe una suscripción continua que empuje eventos a Claude.
- **Caché de schema en los clientes MCP.** Algunos clientes (la app de Claude en
  móvil y escritorio) cachean la lista de herramientas tras el primer
  `initialize` y no detectan cambios del servidor entre versiones. Síntoma: tras
  actualizar Hermes, el cliente sigue listando las herramientas antiguas.
  Solución: desconecta el conector, elimínalo y vuelve a añadirlo. No hay
  arreglo posible en el servidor.
- **Un solo usuario.** El modelo de autorización asume un dueño. Varios clientes
  MCP simultáneos comparten el mismo cupo de peticiones.
- **`network_mode: reverse_proxy` está menos rodado que `tailscale`.** Tiene sus
  tests, pero recibe mucho menos uso real. Si algo falla, un issue con el log de
  arranque se agradece.
- **Las sugerencias del Supervisor solo se aplican con vista previa y
  confirmación.** Hasta la 1.1.x Hermes no las aplicaba nunca. Desde la 1.2.0
  lo hace `sv_apply_resolution_suggestion`, pero solo tras una vista previa
  que dice qué hace el arreglo (algunos borran una app o backups completos
  antiguos, o reinician el host) y con un token atado a la sugerencia y a los
  arreglos automáticos que el Supervisor aplicaría de paso. Rechaza sin token
  las que no tienen arreglo, las que no sabe explicar, las que tocan los
  discos de datos y las que apuntan al propio Hermes. Apaga la familia
  `resolution_fixes` si no lo quieres en absoluto.
- **Los safety backups solo van cifrados si Home Assistant tiene clave de
  cifrado de backups.** Desde la 1.2.0 usan la clave de Home Assistant (la de
  su kit de emergencia), que existe en cuanto se configuran los backups
  automáticos. Sin ella, con el valor por defecto `safety_backup_encryption:
  auto`, se hacen sin contraseña y Hermes lo dice; pon `required` para
  bloquear las escrituras en su lugar.
- **Los safety backups anteriores a 1.1.0 no se podan.** Hermes no los anotó, así
  que la retención no los distingue de los tuyos: bórralos con
  `sv_delete_backup` si ya no los necesitas.

## Arquitectura

```
Claude (móvil/escritorio)
    │
    │ HTTPS  (el TLS lo termina el proxy, nunca Hermes)
    ▼
Tailscale Funnel          ─┐
Cloudflare Tunnel          ├─►  <mcp_bind>:8765  ──►  Hermes (HTTP plano)
Nginx Proxy Manager/Caddy ─┘                              │
                                                          ├── OAuth 2.1 (/.well-known/*, /oauth/*)
                                                          ├── MCP Streamable HTTP (/mcp)
                                                          └── WS a HA core + REST a Supervisor
```

- **TLS**: siempre lo termina el proxy de delante; Hermes habla HTTP plano y
  nunca gestiona certificados. Cuál de los tres sea es cosa de `network_mode`.
- **Bind**: `mcp_bind` (por defecto `127.0.0.1`). Solo alcanzable desde el
  propio host, salvo que se apunte a la red puente de HAOS (`172.30.32.1`)
  para proxies que no comparten la red del host.
- **Host header**: se valida contra `public_hostname` (anti DNS-rebinding), así
  que el proxy no debe reescribirlo.
- **Auth**: OAuth 2.1 con PKCE, DCR, tokens cortos, revocación.
- **Health**: Endpoint separado en `172.30.32.1:8766` para el watchdog del Supervisor.

## Desarrollo

La suite se ejecuta sin desplegar nada ni tener Home Assistant delante:

```bash
python -m venv .venv
.venv/bin/pip install -r hermes/requirements.txt
.venv/bin/pip install pytest pytest-asyncio aioresponses httpx
.venv/bin/pytest
```

En Windows, `.venv\Scripts\` en vez de `.venv/bin/`.

Las dependencias de test van aparte a propósito: `hermes/requirements.txt` es lo
que el add-on necesita para **arrancar**, no para probarse. `pytest.ini` fija las
rutas de importación, así que no hace falta exportar `PYTHONPATH`.

**Estructura**: la raíz es un repositorio de add-ons de Home Assistant
(`repository.yaml`), y el add-on entero vive en `hermes/`. El código Python está
en `hermes/src/hermes/`, y los tests en `tests/` en la raíz.

**Probar cambios en un Home Assistant de verdad**: copia el contenido de `hermes/` a
`/addons/hermes` en el host y **borra la línea `image:`** del `config.yaml` que
dejes ahí — si no, el Supervisor se descarga la imagen publicada en vez de
construir tus cambios. Después:

- `ha apps rebuild local_hermes` tras cualquier cambio, Python incluido: el
  código se copia dentro de la imagen, así que un simple reinicio sigue
  ejecutando el antiguo
- `ha apps logs local_hermes -f` para mirar el log

**`HERMES_DEV=1`** registra una herramienta auxiliar de diagnóstico que en una
instalación normal no se expone.

Más detalle, y las convenciones que se espera que siga un pull request, en
[CONTRIBUTING.es.md](CONTRIBUTING.es.md).

## Licencia

**PolyForm Noncommercial 1.0.0**. © 2026 Nadeon.

**Puedes** usar, estudiar, modificar y compartir Hermes, y construir sobre él,
para cualquier fin **no comercial**: en tu casa, para aprender, para investigar,
o dentro de una organización sin ánimo de lucro.

**Tienes que** conservar el aviso de autoría del [LICENSE](LICENSE) en cualquier
copia que distribuyas, para que quien la reciba sepa de dónde viene. Esa es la
atribución que exige la licencia. Mencionarlo en un README, un artículo o un
vídeo se agradece, pero lo que la licencia obliga es a que el aviso viaje con el
código.

**No puedes** ganar dinero con ello: ni vendiéndolo, ni ofreciéndolo como
servicio de pago, ni incorporándolo a un producto comercial. Para uso comercial,
pregunta.

No es una licencia open source: no cumple la definición de la OSI justamente por
esa restricción, y es a propósito.

Texto completo en [LICENSE](LICENSE).

## Contribuir

Las mejoras son bienvenidas: issues y pull requests. Al abrir un pull request
aceptas que tu contribución se publique bajo esta misma licencia.

Lee [CONTRIBUTING.es.md](CONTRIBUTING.es.md) antes de empezar: cubre el flujo de
ramas y pull requests, cómo reportar una incidencia, y las tres convenciones que
más comentarios de revisión generan. La participación se rige por nuestro
[Código de Conducta](CODE_OF_CONDUCT.md) *(en inglés)*.

Para reportar un fallo de **seguridad** no abras un issue: usa el
[formulario privado](../../security/advisories/new). Ver [SECURITY.md](SECURITY.md)
*(en inglés)*.
