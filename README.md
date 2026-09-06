# Hermes — Home Assistant, completo, desde Claude

[![Tests](https://github.com/Nadeon/Hermes-addon/actions/workflows/tests.yml/badge.svg)](https://github.com/Nadeon/Hermes-addon/actions/workflows/tests.yml)
[![Licencia](https://img.shields.io/badge/licencia-PolyForm%20Noncommercial-blue)](LICENSE)

Hermes es un **add-on de Home Assistant** que expone tu instalación a Claude
como servidor **MCP** (Model Context Protocol, el estándar con el que Claude
habla con sistemas externos). Son **185 herramientas**: encender luces, escribir
automatizaciones, editar ficheros de `/config`, gestionar add-ons, crear
backups, consultar el histórico.

En la práctica: le pides a Claude «apaga las luces del salón», o «créame una
automatización que suba la persiana al amanecer pero no los domingos», y lo
hace — enseñándote antes qué va a tocar cuando la acción es destructiva.

Se instala añadiendo este repositorio a la tienda de add-ons de Home Assistant:
[cómo hacerlo](#instalación). Antes necesitas exponer Home Assistant a internet;
también está explicado abajo.

## Qué puede hacer — 185 herramientas

Los nombres son los que ve Claude. No hace falta que te los aprendas: hay una
herramienta, `hermes_guide`, que se los explica a Claude cuando los necesita.

| Familia | Nº | Qué cubre |
|---|---:|---|
| **Estado y servicios** | 7 | Leer estados, listar y llamar servicios, disparar eventos, renderizar plantillas Jinja |
| **Automatizaciones y scripts** | 14 | Crear, editar, borrar, activar, desactivar y ejecutar |
| **Escenas** | 7 | Incluido capturar el estado actual de la casa como escena nueva |
| **Helpers** | 59 | `input_boolean`, `input_number`, `input_select`, `input_text`, `input_button`, `input_datetime`, `counter`, `timer`, `schedule` |
| **Zonas y personas** | 10 | Zonas geográficas y seguimiento de personas |
| **Registros** | 13 | Entidades, dispositivos y áreas: renombrar, mover, ocultar, deshabilitar |
| **Integraciones** | 13 | Config entries y sus flujos de configuración, incluidos los de opciones |
| **Ficheros de `/config`** | 11 | Leer, escribir, mover, borrar, buscar, gestionar `secrets.yaml` y restaurar copias |
| **Lovelace** | 10 | Dashboards y recursos |
| **Add-ons** | 12 | Listar, instalar, arrancar, parar, actualizar, leer logs y estadísticas |
| **Backups** | 10 | Completos y parciales, crear y restaurar |
| **Supervisor y sistema** | 6 | Info del host y del core, validar configuración, reiniciar |
| **Histórico y estadísticas** | 4 | Histórico, logbook y estadísticas de largo plazo |
| **HACS** | 4 | Consultar repositorios y actualizaciones disponibles |
| **Espera de eventos** | 3 | Esperar a que ocurra algo, con filtros |
| **Utilidades** | 2 | `ping` y `hermes_guide` |

Hay una herramienta más, auxiliar, que solo se registra con `HERMES_DEV=1` y
que en una instalación normal no existe.

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
- Arquitectura `amd64` o `aarch64`, y Home Assistant **2024.1.0** o superior.

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

1. Instala el **add-on oficial de Tailscale** en HAOS.
2. Configura **`userspace_networking: false`**. Es obligatorio: sin eso no se
   crea la interfaz `tailscale0` y, en `network_mode: tailscale`, Hermes espera
   a que exista y no arranca.
3. Habilita **Funnel** y apúntalo al puerto de Hermes:
   ```
   tailscale funnel --bg 8765
   ```
4. En las opciones de Hermes:
   - `network_mode`: `tailscale`
   - `public_hostname`: el hostname que te da Funnel (ej.
     `homeassistant.tailXXXX.ts.net`), **sin esquema ni path**
   - `mcp_bind`: `127.0.0.1` (el add-on de Tailscale comparte la red del host,
     así que alcanza el loopback)

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

1. En Home Assistant: **Ajustes → Add-ons → Tienda de add-ons → ⋮ →
   Repositorios**, y pega:

   ```
   https://github.com/Nadeon/Hermes-addon
   ```

2. Cierra el diálogo. Hermes aparece en la tienda, en su propia sección.
   Ábrelo y pulsa **Instalar**.

   > La imagen viene precompilada para `amd64` y `aarch64`, así que instalar
   > son unos segundos: no se compila nada en tu equipo.

3. Rellena la configuración:
   - **`auth_password`** *(obligatorio)*: la contraseña con la que autorizarás a
     Claude. Mínimo 12 caracteres; genérala aleatoria con un gestor de
     contraseñas. Es el único secreto que protege tu casa.
   - **`public_hostname`** *(obligatorio)*: el hostname público, sin `https://`
     ni path final.
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
`/addons/hermes` en el host, por Samba o SSH. Aparecerá en **Local add-ons**
tras un *Comprobar actualizaciones*.

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
| `auth_password es demasiado corta` | Tiene menos de 12 caracteres. |
| `public_hostname no está configurado` | Falta el hostname. |
| `public_hostname inválido` | Lo has puesto con `https://` delante, con un path detrás, o con barras. Va solo el hostname. |
| `mcp_bind no puede estar vacío` | Has dejado la opción en blanco. Ponla a `127.0.0.1` o a `172.30.32.1`. |
| `SUPERVISOR_TOKEN no está disponible` | No estás en Home Assistant OS ni Supervised. Hermes es un add-on y necesita el Supervisor. |
| `network_mode inválido` | Solo se admiten `tailscale` y `reverse_proxy`. |
| El túnel da *connection refused* | `mcp_bind` no es alcanzable desde tu proxy. Si está en la red puente, usa `172.30.32.1`. |

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
> techo global. No es una vulnerabilidad —nada del sistema autoriza por IP, la
> IP solo alimenta el rate limit y los logs, y el freno anti-fuerza-bruta del
> login es global a propósito—, pero conviene saberlo: si tu proxy ya limita
> por IP, deja que lo haga él.

## Conectar Claude

1. En Claude, móvil o escritorio: **Configuración → Conectores → Añadir conector
   personalizado**.
2. Pega la URL de tu servidor:

   ```
   https://<tu_public_hostname>/mcp
   ```

3. Claude abre la página de autorización de Hermes. Introduce la
   `auth_password` que pusiste en la configuración del add-on.

4. Listo. A partir de ahí, pídele cosas en lenguaje normal.

> [!IMPORTANT]
> La pantalla de autorización te dice **qué cliente** pide acceso y **a qué
> dirección** irá el código. Léelo antes de aceptar: es la única defensa contra
> que alguien te haga llegar un enlace de autorización con su propio destino.

Lo que ocurre por debajo, si tienes curiosidad: Claude descubre los endpoints
OAuth a partir del `401` que devuelve Hermes, registra un cliente
automáticamente (RFC 7591), te manda al login, y a cambio de tu contraseña
obtiene un token. No hay que copiar ni pegar ninguna clave.

**Qué esperar la primera vez.** Al conectar, Hermes le entrega a Claude un
resumen de las familias de herramientas disponibles. Cuando necesita detalle de
un área concreta, Claude consulta `hermes_guide` por su cuenta — no tienes que
hacer nada.

## Opciones de configuración

| Opción | Default | Descripción |
|--------|---------|-------------|
| `auth_password` | _(obligatorio)_ | Contraseña del flujo OAuth (mínimo 12 caracteres, larga y aleatoria) |
| `public_hostname` | _(obligatorio)_ | Hostname público por el que se llega a Hermes, sin esquema ni path |
| `network_mode` | `tailscale` | Quién publica el hostname: `tailscale` (Funnel) o `reverse_proxy` (Cloudflare Tunnel, Nginx, Caddy…) |
| `mcp_bind` | `127.0.0.1` | Dirección donde escucha Hermes. Usa `172.30.32.1` si tu proxy corre en la red puente de HAOS |
| `log_level` | `info` | Nivel de log (`debug`/`info`/`warning`/`error`) |
| `safety_backup_enabled` | `false` | Backup **completo** de HAOS automático antes de escribir en `/config`. Desactivado por defecto (genera varios GB). El backup por-fichero se hace siempre |
| `mcp_max_requests_per_minute` | `120` | Rate limit global post-auth |
| `mcp_preauth_max_requests_per_minute_per_ip` | `20` | Rate limit pre-auth por IP. Solo aplica a la superficie pública (OAuth y discovery): las rutas protegidas las gobierna `mcp_max_requests_per_minute` una vez validado el token |
| `response_max_bytes` | `1048576` | Cap de respuesta por tool (1 MB) |
| `ha_ws_max_msg_size_bytes` | `4194304` | Cap de mensaje WS hacia HA (4 MB). Un resultado más grande cierra la WebSocket entera, no solo esa llamada: súbelo si usas `ha_get_history` con rangos amplios |
| `max_request_body_bytes` | `4194304` | Cap del cuerpo de una petición HTTP autenticada (4 MB). Los endpoints públicos de OAuth llevan su propio tope fijo de 64 KiB, que no depende de esta opción |
| `max_concurrent_requests` | `64` | Peticiones simultáneas que acepta el servidor. Acota la memoria máxima en vuelo (`max_concurrent_requests × max_request_body_bytes`). Claude lanza ráfagas de ~24 llamadas, así que 64 deja holgura |
| `wait_for_event_max_seconds` | `90` | Máximo timeout permitido para `ha_wait_for_event` (10–300) |
| `wait_for_event_max_concurrent` | `5` | Máximo de `ha_wait_for_event` simultáneos (1–20) |
| `safety_backup_window_minutes` | `30` | Si ya hay un backup completo más reciente que esto, no se hace otro |
| `file_backup_max_per_path` | `20` | Copias que se guardan de cada fichero antes de sobrescribirlo |
| `file_backup_max_total_mb` | `200` | Tope total del directorio de copias por fichero |
| `config_write_min_interval_seconds` | `5` | Segundos mínimos entre dos escrituras en `/config` |
| `config_write_max_per_minute` | `10` | Escrituras máximas por minuto en `/config` |
| `health_startup_grace_seconds` | `120` | Margen de arranque antes de que el watchdog considere que Hermes no levanta |
| `health_reconnect_tolerance_seconds` | `300` | Cuánto puede estar caída la WebSocket con HA antes de reportar `unhealthy` |

### Palancas de seguridad

Estas tres cambian **qué puede hacer Claude sin preguntarte**. Merece la pena leerlas:

| Opción | Default | Descripción |
|--------|---------|-------------|
| `call_service_denylist_extra` | `[]` | Servicios adicionales que exigirán confirmación explícita, además de los ~40 que ya trae Hermes. Formato `dominio.servicio`, admite comodín (`shell_command.*`) |
| `call_service_restricted_entities` | `[]` | Entidades concretas que exigirán confirmación aunque el servicio no esté vetado. Útil para `script.abrir_garaje` y compañía |
| `fire_event_allowlist` | `[]` | Tipos de evento que `ha_fire_event` puede disparar. Vacío significa que la herramienta está deshabilitada: hay que nombrar explícitamente cada evento permitido |
| `call_service_auto_classify_dangerous` | `true` | Al arrancar y al guardar, Hermes lee tus scripts y automatizaciones y marca automáticamente como restringidas las que invocan servicios peligrosos. Desactívalo solo si quieres gestionar la lista a mano |

Ver `config.yaml` para el schema completo con sus rangos válidos.

## Seguridad

- **OAuth 2.1 con PKCE obligatorio** (no bearer estático): tokens opacos
  hasheados (SHA-256), auth codes de un solo uso, revocación (RFC 7009).
- **Contraseña fuerte obligatoria**: `auth_password` ≥ 12 caracteres + throttle
  con backoff exponencial ante intentos fallidos (anti-fuerza-bruta).
- **DCR endurecido**: validación de `redirect_uris` y tope de clientes.
- **Tokens de confirmación** para toda acción destructiva.
- **Filesystem `/config`**: anti-traversal, blacklist de secretos, allowlist
  *default-deny* en `.storage/`, *managed paths*, backup antes de cada escritura.
- **Validación anti path-injection** de identificadores (slug, `entry_id`…)
  + guard central en el cliente HA.
- **Cabeceras de seguridad** (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, CSP) y límite de tamaño de cuerpo (incluido `chunked`).
- **Redacción de secretos** en todos los logs.
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

- `ha apps rebuild local_hermes` si tocaste `Dockerfile` o dependencias
- `ha apps restart local_hermes` si solo tocaste Python
- `ha apps logs local_hermes -f` para mirar el log

**`HERMES_DEV=1`** registra una herramienta auxiliar de diagnóstico que en una
instalación normal no se expone.

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

Un par de cosas que agradecerás saber antes de empezar:

- La suite se ejecuta con `pytest` desde la raíz, sin configurar nada más.
- Cada arreglo de seguridad lleva su test de regresión, y ese test debe **fallar
  si se deshace el arreglo**. Un test que pasa con la guarda desactivada no
  protege nada.
- Los `docstring` de las herramientas no son documentación decorativa: son lo
  que Claude lee para decidir cuál usar. Si el docstring miente, la herramienta
  está rota aunque el código funcione.

Para reportar un fallo de **seguridad** no abras un issue: usa el
[formulario privado](../../security/advisories/new). Ver [SECURITY.md](SECURITY.md).
