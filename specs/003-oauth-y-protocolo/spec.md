# Especificación: Hermes 1.1.0 — OAuth moderno, límites de Claude, protocolo MCP y log sin datos de red

**Directorio de la spec**: `specs/003-oauth-y-protocolo`

**Creada**: 2026-11-14

**Estado**: Lista para implementar (después de 1.0.12)

**Entrada**: descripción del mantenedor: «Para 1.1.0: CIMD con DCR de respaldo; `iss` (RFC 9207); `scopes_supported` y `scope` en `WWW-Authenticate`; comprobación de audiencia; `response_max_bytes` por defecto en 128 KiB y máximo ≤ 512 KiB; máximo de `wait_for_event` ≤ 220 s; estudiar el temporizador de 60 s de Claude Code; `title`, `version`, `isError` y migración de `SUPPORTED_PROTOCOL_VERSIONS`; redacción de hostname e IPs en el log por defecto, con opción para desactivarla».

**Base**: esta spec se implementa **encima de 1.0.12** (`specs/001-correcciones-1-0-12/`),
que se da por implementada: `HAConnectionError.code`, `hermes/src/hermes/ha_version.py`,
`ha_remove_device`, etc.

**Trazabilidad**: cada requisito cita entre corchetes el identificador de la
investigación de límites de Claude, CIMD e `iss` (documento «10» de la revisión
de noviembre de 2026): `R-CIMD-n`, `R-ISS-n`, `R-SCOPE-n`, `R-AUD-1`, `R-LIM-n`,
`R-SRV-n`. Los de la redacción del log citan la decisión 10 y la sección 8 del
documento «11». La correspondencia completa está en
[research.md](./research.md#trazabilidad).

## Clarificaciones

### Sesión 2026-11-14

No se ha preguntado al mantenedor: estaba ausente y había dejado decisiones
tomadas. Las dudas se resolvieron así:

- P: ¿CIMD ya o esperar? → R: **en 1.1.0, con DCR de respaldo** (decisión del mantenedor).
- P: ¿Se baja `response_max_bytes`? → R: **sí**, a 128 KiB por defecto y con un máximo efectivo de 512 KiB (decisión del mantenedor).
- P: ¿Se redactan hostname e IPs en el log? → R: **sí, por defecto**, con una opción para desactivarlo al depurar (decisión 10 del mantenedor).
- P: ¿Puede un cambio obligar a reautorizar a los clientes ya conectados? → R: **no**: los clientes DCR existentes y sus tokens siguen valiendo (decisión del mantenedor).
- P: Quien tiene guardado `response_max_bytes: 1048576` o `wait_for_event_max_seconds` > 220, ¿se le impide arrancar? → R: no; el valor se recorta al máximo al cargar y se avisa en el log. Ver Supuestos S-03 y S-04.
- P: ¿Se valida el `redirect_uri` de loopback ignorando el puerto también en clientes DCR? → R: no; solo en CIMD, que es donde el documento no puede llevar puerto. Ver Supuesto S-08.
- P: ¿Cómo se mitiga el temporizador de 60 s hasta el primer byte de Claude Code? → R: el SDK ya envía las cabeceras y *pings* SSE cada 15 s; se exige un test que lo demuestre a través de toda la pila de Hermes y se documenta la salida para el caso de un proxy que almacene la respuesta. Ver Supuesto S-11.

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es quien administra su Home Assistant a través de un cliente MCP
(claude.ai, Claude Desktop, Claude Code u otro). Las historias van por
prioridad.

### Historia 1 — Conectar Claude Code con CIMD (Prioridad: P1)

Claude Code se identifica con la URL de su documento de metadatos
(`https://claude.ai/oauth/claude-code-client-metadata`) en lugar de registrarse
con DCR, y recibe el código en `http://localhost:<puerto>/callback` o
`http://127.0.0.1:<puerto>/callback`, con un puerto que cambia en cada intento.
Hoy Hermes no anuncia CIMD y compara el `redirect_uri` con igualdad exacta, así
que un cliente con CIMD no podría terminar el flujo.

**Por qué esta prioridad**: la spec MCP vigente depreca DCR y Claude prefiere
CIMD en cuanto el servidor lo anuncia; sin una validación de loopback correcta,
anunciarlo rompería Claude Code.

**Prueba independiente**: con un servidor de documentos simulado que devuelve
el documento de Claude Code, una autorización con `client_id` igual a esa URL y
`redirect_uri=http://127.0.0.1:53127/callback` termina con un código canjeable,
y el canje con PKCE devuelve tokens.

**Escenarios de aceptación**:

1. **Dado** el documento de Claude Code accesible, **cuando** el cliente pide `/oauth/authorize` con su URL como `client_id` y `http://localhost:41000/callback`, **entonces** Hermes muestra la pantalla de consentimiento con el host `claude.ai` como identidad y `localhost` como destino, con el aviso de destino local.
2. **Dado** lo mismo, **cuando** el dueño introduce la contraseña, **entonces** Hermes redirige a `http://localhost:41000/callback?code=…&state=…&iss=https%3A%2F%2F<public_hostname>` y el canje del código en `/oauth/token` devuelve tokens.
3. **Dado** un `redirect_uri` de loopback con otro path (`/otro`) o con `https`, **cuando** se pide autorización, **entonces** se rechaza con una página de error y sin redirigir.
4. **Dado** que el documento no se puede descargar, **cuando** se pide autorización, **entonces** Hermes muestra una página de error que explica que no pudo verificar al cliente, sin redirigir.
5. **Dado** dos instalaciones de Claude Code autorizadas con la misma URL de cliente, **cuando** se autoriza la segunda, **entonces** la sesión de la primera sigue viva.

---

### Historia 2 — Nada se rompe para quien ya está conectado (Prioridad: P1)

claude.ai y Claude Desktop pueden seguir usando DCR. Quien ya autorizó un
cliente antes de actualizar no tiene que volver a hacerlo.

**Por qué esta prioridad**: una actualización que desconecta a todos los
usuarios es peor que no actualizar (decisión del mantenedor).

**Prueba independiente**: con un cliente DCR y unos tokens escritos en disco con
el formato de 1.0.12 (sin `resource`), el access token se acepta, el refresh
rota y un registro DCR nuevo sigue funcionando.

**Escenarios de aceptación**:

1. **Dado** un access token emitido por 1.0.12, **cuando** el cliente llama a `/mcp`, **entonces** la llamada se acepta hasta que el token caduque.
2. **Dado** un refresh token emitido por 1.0.12, **cuando** el cliente lo canjea, **entonces** recibe tokens nuevos, que ya llevan `resource`.
3. **Dado** un cliente que se registra por DCR, **cuando** completa el flujo, **entonces** funciona como en 1.0.12, con `iss` añadido en la redirección.
4. **Dado** `oauth_cimd_enabled: false`, **cuando** un cliente lee los metadatos, **entonces** no se anuncia CIMD y el cliente usa DCR.

---

### Historia 3 — Hermes no se puede usar para atacar la red de casa (Prioridad: P1)

Con CIMD, Hermes descarga URL que le da un desconocido sin autenticar. Si no se
protege, alguien podría hacer que Hermes pida `http://192.168.1.1/…`, la API del
Supervisor o un servicio de la tailnet (SSRF).

**Por qué esta prioridad**: es una superficie nueva, pública y sin contraseña
delante (principios I y III).

**Prueba independiente**: con un resolvedor DNS simulado, URLs cuyo host
resuelve a loopback, red privada, link-local, CGNAT (100.64.0.0/10), ULA o
direcciones mapeadas se rechazan sin abrir ninguna conexión.

**Escenarios de aceptación**:

1. **Dado** un `client_id` `https://interno.example/doc` que resuelve a `10.0.0.5` o a `100.64.0.7`, **cuando** se pide autorización, **entonces** no se abre ninguna conexión a la dirección privada y se muestra el error.
2. **Dado** un documento que responde con una redirección 302, **cuando** se descarga, **entonces** no se sigue y se rechaza.
3. **Dado** un documento de 6 000 bytes, **cuando** se descarga, **entonces** se rechaza por tamaño.
4. **Dado** un servidor que tarda más de 5 s, **cuando** se descarga, **entonces** se aborta y el error no se guarda en caché.
5. **Dado** una ráfaga de autorizaciones con `client_id` distintos, **cuando** se supera el cupo global de descargas, **entonces** Hermes deja de descargar y responde un error temporal.

---

### Historia 4 — Las respuestas caben en lo que Claude acepta (Prioridad: P2)

claude.ai acepta unos 150 000 caracteres por resultado y Claude Code guarda en
un fichero los de más de 50 000. Hoy el tope de Hermes es 1 MiB, así que su
truncado nunca actúa antes que el del cliente.

**Por qué esta prioridad**: el truncado de Hermes es controlado y avisa; el del
cliente, no.

**Prueba independiente**: con la configuración por defecto, `response_max_bytes`
vale 131 072; con 1 048 576 guardado (el antiguo valor por defecto) también; con
2 000 000 queda en 524 288 y el log lo dice.

**Escenarios de aceptación**:

1. **Dado** una instalación nueva, **cuando** arranca, **entonces** `response_max_bytes` efectivo es 131 072.
2. **Dado** `response_max_bytes: 1048576` guardado, **cuando** arranca, **entonces** el valor efectivo es 131 072 y el log lo explica.
3. **Dado** `response_max_bytes: 300000`, **cuando** arranca, **entonces** se respeta.
4. **Dado** `response_max_bytes: 4000000`, **cuando** arranca, **entonces** el efectivo es 524 288 y el log avisa del recorte.

---

### Historia 5 — Las esperas largas no se cortan (Prioridad: P2)

`ha_wait_for_event` espera hasta 90 s por defecto. claude.ai corta a los 240 s y
Claude Code, en HTTP, a los 60 s si no ha recibido ningún byte.

**Por qué esta prioridad**: una espera cortada por el cliente pierde el
resultado sin que nadie lo sepa.

**Prueba independiente**: con la pila de middlewares de Hermes y un intervalo de
*ping* acortado en el test, una tool que tarda más que ese intervalo empieza a
emitir bytes antes de terminar, con las dos familias de versión de protocolo.

**Escenarios de aceptación**:

1. **Dado** `wait_for_event_max_seconds: 300` guardado, **cuando** arranca, **entonces** el máximo efectivo es 220 y el log avisa.
2. **Dado** una llamada a una tool que tarda más que el intervalo de *ping*, **cuando** el cliente pide `text/event-stream`, **entonces** recibe las cabeceras y al menos un *ping* antes del resultado.
3. **Dado** el README y DOCS, **cuando** un usuario de Claude Code busca por qué se corta una espera, **entonces** encuentra el temporizador de 60 s y cómo subirlo.

---

### Historia 6 — Un log que se puede pegar en un issue (Prioridad: P2)

La gente pega el log de Hermes en issues públicos. Hoy salen enteros el hostname
público, la IP de la tailnet, la IP real de cada cliente y los avisos del SDK
con la cabecera `Host` recibida.

**Por qué esta prioridad**: el repositorio es público (principio VIII) y el log
es lo que más se comparte.

**Prueba independiente**: con `log_redact_network` por defecto, ninguna línea
emitida en el arranque, en una petición rechazada ni en el aviso de `Host`
inválido del SDK contiene el hostname configurado ni una IP que no sea de
loopback.

**Escenarios de aceptación**:

1. **Dado** la opción por defecto, **cuando** Hermes arranca, **entonces** `hermes_started` muestra `<public_hostname>` y seudónimos en lugar de IPs.
2. **Dado** dos peticiones de la misma IP, **cuando** se registran, **entonces** llevan el mismo seudónimo, y otra IP lleva otro.
3. **Dado** un escáner que manda `Host: 192.0.2.7`, **cuando** el SDK registra el aviso, **entonces** la línea sale redactada.
4. **Dado** `log_redact_network: false`, **cuando** Hermes arranca, **entonces** el log muestra los valores reales y un aviso de que la redacción de red está desactivada; los secretos siguen redactados.

---

### Historia 7 — El cliente ve un servidor MCP bien descrito (Prioridad: P3)

Los clientes muestran el nombre legible de cada tool, la versión del servidor y
marcan como error las llamadas fallidas.

**Por qué esta prioridad**: mejora la experiencia y la claridad de los
permisos, pero no rompe nada hoy.

**Prueba independiente**: `tools/list` devuelve `title` en todas las tools; la
respuesta del servidor lleva `version` igual a la de Hermes; una tool que
devuelve `{"error": …}` sale con `isError: true`.

**Escenarios de aceptación**:

1. **Dado** cualquier tool, **cuando** se listan, **entonces** tiene un `title` no vacío y único.
2. **Dado** el servidor, **cuando** el cliente lo descubre, **entonces** `serverInfo.version` coincide con `__version__`.
3. **Dado** una tool que responde `{"error": "not_found", …}`, **cuando** se llama, **entonces** el resultado lleva `isError: true` y el mismo texto.
4. **Dado** una vista previa con `confirmation_token`, **cuando** se llama, **entonces** el resultado no lleva `isError: true`.

---

### Casos límite

- `client_id` con forma de URL pero `http://`, con `#fragmento`, con `user@host`, con path `/` o con segmentos `.`/`..`: se rechaza sin descargar nada.
- `client_id` que resuelve a varias direcciones y alguna es especial: se rechaza entero (no se elige la buena).
- `client_id` que es una IP literal pública (`https://203.0.113.5/doc`): se trata igual que un nombre; si es especial, se rechaza.
- Documento con `client_id` que difiere solo en la barra final o en mayúsculas: se rechaza (igualdad simple de cadenas, sin normalizar).
- Documento con `NaN`, BOM, JSON no UTF-8, raíz que no es objeto, claves duplicadas o `redirect_uris` vacío: inválido; no se cachea.
- Documento con `token_endpoint_auth_method: "client_secret_basic"` o con `client_secret`: inválido.
- Documento que antes era válido y en la recarga devuelve 404 o un `client_id` distinto: se borra de la caché y se revocan los refresh tokens de ese cliente; si devuelve 5xx o se agota el tiempo, se usa la copia válida mientras tenga menos de 24 h.
- `redirect_uri` `http://localhost/callback` sin puerto o con el puerto 80: también vale (el puerto se ignora en loopback).
- `redirect_uri` `http://localhost.evil.example:1234/callback` o `http://127.0.0.2/callback`: no es loopback según la regla; comparación exacta, que falla.
- `client_id` igual al `issuer` de Hermes, a su recurso o con el host de Hermes: se rechaza.
- `public_hostname` con puerto (`homeassistant.tailXXXX.ts.net:8443`): el `iss` lleva el puerto, igual que el `issuer`.
- Una IP dentro de un texto libre (un mensaje de excepción, la URL del Supervisor): se redacta igual que en un campo.
- Números con forma de IP que no lo son (`999.1.1.1`) o versiones de tres partes (`2026.11.1`): no se tocan.
- `wait_for_event_max_seconds` entre 10 y 220: se respeta tal cual.
- El dueño cambia `public_hostname`: los tokens emitidos por 1.1.0 llevan el recurso antiguo y se rechazan (hay que reautorizar, como corresponde a un recurso distinto); los emitidos antes de 1.1.0, sin `resource`, siguen valiendo hasta caducar.

## Requisitos *(obligatorio)*

### Requisitos funcionales

**CIMD — descubrimiento y forma del `client_id`**

- **FR-001** [R-CIMD-1]: Con CIMD activado, los metadatos del servidor de autorización DEBEN incluir `"client_id_metadata_document_supported": true`, mantener `"none"` en `token_endpoint_auth_methods_supported` y mantener `registration_endpoint` (DCR de respaldo).
- **FR-002** [R-CIMD-2]: Un `client_id` que empieza por `https://` DEBE tratarse como URL de un documento de metadatos. Solo se acepta si es una URL absoluta `https` con host, sin userinfo, sin fragmento, sin query, con path distinto de `/`, sin segmentos `.` ni `..`, sin puerto o con el 443, y de 2 048 caracteres como mucho. Si no cumple, se rechaza sin descargar nada.
- **FR-003** [R-CIMD-9]: Hermes DEBE rechazar un `client_id` igual a su `issuer`, igual a su recurso protegido (`<base>/mcp`) o cuyo host sea su propio `public_hostname`.

**CIMD — descarga segura**

- **FR-004** [R-CIMD-2]: La descarga DEBE ser un GET con `Accept: application/json`, sin seguir redirecciones (cualquier 3xx es error), aceptando solo el estado 200 y con un tiempo total máximo de 5 s.
- **FR-005** [R-CIMD-3]: Se DEBEN leer como máximo 5 120 bytes del cuerpo; llegar al límite DEBE contar como error, sin intentar interpretar el prefijo.
- **FR-006** [R-CIMD-4]: Antes de conectar, Hermes DEBE resolver el host y rechazar la URL si **alguna** dirección resuelta es de uso especial (RFC 6890: loopback, privadas, link-local, CGNAT 100.64.0.0/10 —que incluye la tailnet—, ULA, multicast, reservadas, no especificadas, de documentación y las IPv6 que embeben IPv4 de esos rangos). La conexión DEBE ir a una de las direcciones ya validadas, sin una segunda resolución (contra el DNS rebinding), conservando el nombre para TLS y para la cabecera `Host`.
- **FR-007** [R-CIMD-4]: Hermes DEBE acotar las descargas: como mucho 4 simultáneas y 30 por minuto en total. Por encima, la petición se trata como fallo temporal sin descargar.

**CIMD — validación del documento**

- **FR-008** [R-CIMD-5]: El documento DEBE ser JSON UTF-8 válido (sin `NaN` ni `Infinity`, sin claves duplicadas), cuya raíz sea un objeto con: `client_id` exactamente igual, carácter a carácter, a la URL descargada; `client_name` texto no vacío de 200 caracteres como mucho; `redirect_uris` lista de 1 a 10 URI absolutas, sin fragmento, de 2 048 caracteres como mucho y sin esquemas peligrosos (`javascript`, `data`, `vbscript`, `file`).
- **FR-009** [R-CIMD-5]: El documento NO DEBE contener `client_secret` ni `client_secret_expires_at`, y su `token_endpoint_auth_method`, si lo trae, DEBE ser `none`; en otro caso es inválido.
- **FR-010** [R-CIMD-5]: `grant_types` (por defecto `["authorization_code"]`) DEBE incluir `authorization_code` y `response_types` (por defecto `["code"]`) DEBE incluir `code`. Hermes solo DEBE emitir refresh token a un cliente CIMD si su `grant_types` incluye `refresh_token`.

**CIMD — `redirect_uri`**

- **FR-011** [R-CIMD-6]: El `redirect_uri` de un cliente CIMD DEBE coincidir exactamente con uno de los del documento, salvo en loopback: si el registrado y el pedido usan `http` y su host es `localhost`, `127.0.0.1` o `[::1]` (el mismo en los dos), el puerto se ignora y el resto (esquema, host, path y query) DEBE coincidir exactamente.
- **FR-012** [R-CIMD-6]: El documento real de Claude Code (`redirect_uris` `http://localhost/callback` y `http://127.0.0.1/callback`, sin puerto) DEBE funcionar con cualquier puerto en el `redirect_uri` de la petición.
- **FR-013** [R-CIMD-6]: El `redirect_uri` se DEBE validar antes de mostrar el formulario de contraseña (GET) y otra vez al recibirla (POST); el código se emite solo si las dos validaciones pasan.

**CIMD — errores, caché y sesiones**

- **FR-014** [R-CIMD-7]: Si el documento no se puede obtener o es inválido, `/oauth/authorize` NO DEBE redirigir al cliente: DEBE mostrar una página de error que diga que no se pudo verificar al cliente y el motivo genérico (inalcanzable, inválido, no permitido), sin pedir la contraseña.
- **FR-015** [R-CIMD-7]: En `/oauth/token`, un cliente CIMD cuyo documento es inválido DEBE recibir `invalid_client` (HTTP 401); si el fallo es temporal (red, tiempo, 5xx, cupo de descargas) y no hay copia válida en caché, DEBE recibir HTTP 503 con `temporarily_unavailable`.
- **FR-016** [R-CIMD-8]: Los documentos válidos DEBEN guardarse en una caché en memoria con una vida igual al `max-age` de `Cache-Control` acotado entre 5 min y 24 h (1 h si no hay `max-age`; 5 min con `no-store` o `no-cache`), de 64 entradas como mucho. Los errores y los documentos inválidos NO DEBEN cachearse.
- **FR-017** [R-CIMD-8]: Si una recarga falla de forma temporal, Hermes DEBE seguir usando la última copia válida mientras tenga menos de 24 h desde su descarga.
- **FR-018** [R-CIMD-7]: Si una recarga devuelve un documento inválido, un 404/410 o un `client_id` distinto, Hermes DEBE borrar la copia de la caché y revocar los refresh tokens emitidos a ese `client_id` (con sus access tokens).
- **FR-019** [R-CIMD-8]: El token endpoint DEBE comprobar, a través de la caché, el documento del cliente CIMD al canjear un refresh token. Al canjear un código NO se vuelve a comprobar: el código se emitió tras validar el documento, vive 60 s y está atado al cliente por PKCE.
- **FR-020** [R-CIMD-11]: Autorizar un cliente CIMD NO DEBE revocar las sesiones vivas de otros dispositivos que comparten el mismo `client_id`; solo se aplica el tope global de sesiones vivas que ya existe.

**CIMD — pantalla de consentimiento y convivencia con DCR**

- **FR-021** [R-CIMD-10]: Para un cliente CIMD, la pantalla de consentimiento DEBE mostrar como identidad el **host del `client_id`**, el `client_name` marcado como «nombre declarado por el cliente» y el destino (`esquema://host` del `redirect_uri`, sin puerto en loopback). Si el destino es loopback, DEBE añadir un aviso de que el código irá a una aplicación de ese mismo dispositivo.
- **FR-022** [R-CIMD-11]: DCR DEBE seguir funcionando como en 1.0.12: los `client_id` que genera siguen siendo UUID (nunca `https://…`), sus clientes y tokens existentes siguen valiendo, y su `redirect_uri` se sigue comparando con igualdad exacta.
- **FR-023**: DEBE existir la opción `oauth_cimd_enabled` (por defecto `true`). Con `false`, los metadatos no anuncian CIMD y un `client_id` `https://…` se rechaza con una página que explica que CIMD está desactivado; DCR no cambia.
- **FR-024**: Cada rechazo de CIMD DEBE dejar en el log un evento `oauth_cimd_rejected` con el motivo (código corto) y el host del `client_id`, nunca el contenido del documento.

**`iss` (RFC 9207)**

- **FR-025** [R-ISS-1]: Toda redirección de `/oauth/authorize` al cliente, de éxito o de error, DEBE llevar el parámetro `iss` con exactamente el mismo valor que `issuer` en `/.well-known/oauth-authorization-server`, construidos ambos desde la misma variable.
- **FR-026** [R-ISS-2]: Los metadatos del servidor de autorización DEBEN incluir `"authorization_response_iss_parameter_supported": true`.
- **FR-027** [R-ISS-1]: Los errores detectados antes de validar el cliente y su `redirect_uri` NO DEBEN redirigir (RFC 6749 §4.1.2.1); se siguen mostrando como página o JSON de error, como en 1.0.12.

**Metadatos del recurso, `WWW-Authenticate` y audiencia**

- **FR-028** [R-SCOPE-1]: Los metadatos del recurso protegido DEBEN incluir `"scopes_supported": ["mcp"]`.
- **FR-029** [R-SCOPE-2]: El `WWW-Authenticate` de los 401 de `/mcp` DEBE incluir `scope="mcp"`, además de `realm` y `resource_metadata`.
- **FR-030** [R-AUD-1]: Los access y refresh tokens emitidos a partir de 1.1.0 DEBEN guardar `resource` (el recurso canónico), y el refresh DEBE heredarlo. La validación del access token DEBE rechazar un token cuyo `resource` sea distinto del recurso canónico.
- **FR-031** [Decisión: sin rupturas]: Un token sin `resource` (emitido antes de 1.1.0) DEBE seguir aceptándose hasta su caducidad, y su refresh DEBE emitir tokens que ya lo lleven. Ningún cliente DCR ni token existente se invalida por la actualización.

**Límites alineados con Claude**

- **FR-032** [R-LIM-1]: El valor por defecto de `response_max_bytes` DEBE ser 131 072 en `config.yaml`, en `config.py` y en `run.sh`.
- **FR-033** [R-LIM-2]: El valor efectivo de `response_max_bytes` NO DEBE superar 524 288: un valor mayor se recorta al cargar la configuración y se registra el evento `config_value_clamped` con la opción, el valor configurado y el aplicado.
- **FR-034** [R-LIM-1]: Un `response_max_bytes` igual a 1 048 576 (el valor por defecto anterior, que la interfaz guarda aunque nadie lo haya tocado) DEBE tratarse como no personalizado y aplicar 131 072, con el evento `config_legacy_default_replaced`.
- **FR-035** [R-LIM-3]: El valor efectivo de `wait_for_event_max_seconds` NO DEBE superar 220: un valor mayor se recorta al cargar con `config_value_clamped`. El valor por defecto sigue siendo 90.
- **FR-036** [R-LIM-4]: Una petición POST a `/mcp` que acepta `text/event-stream` y cuya tool tarda más que el intervalo de *keepalive* del SDK DEBE empezar a emitir bytes (cabeceras y *pings*) antes de terminar, al pasar por toda la pila de middlewares de Hermes y con las dos familias de versión de protocolo (las del handshake y 2026-07-28). Ningún middleware de Hermes puede almacenar la respuesta completa de una petición correcta.
- **FR-037** [R-LIM-4]: DOCS.md y los dos README DEBEN explicar el temporizador de 60 s hasta el primer byte de Claude Code, que Hermes envía *pings* cada 15 s, y cómo ampliarlo en Claude Code (`MCP_TOOL_TIMEOUT` o `timeout` en la entrada del servidor) si el proxy de delante almacena la respuesta.
- **FR-038** [R-LIM-1, R-LIM-3]: DOCS.md, los dos README y el CHANGELOG DEBEN explicar los nuevos valores por defecto y máximos, qué pasa con quien tiene valores guardados (1 048 576 pasa a 131 072; por encima de 524 288 o de 220 se recorta) y cómo subir `response_max_bytes` hasta 524 288 si lo necesita.

**Protocolo MCP**

- **FR-039** [R-SRV-1]: El servidor MCP DEBE anunciar `version` igual a `__version__` en `serverInfo` (y en los metadatos de servidor de cada resultado, si el SDK los emite).
- **FR-040** [R-SRV-4]: Todas las tools DEBEN tener un `title` legible en inglés, no vacío y único, generado de forma centralizada a partir del nombre (con excepciones explícitas para siglas y nombres propios), presente tanto en la tool como en sus anotaciones.
- **FR-041** [R-SRV-3]: El resultado de una tool cuyo valor devuelto es un objeto con la clave `error` en el nivel superior y un valor distinto de `null` DEBE salir con `isError: true`, con el mismo contenido de texto que hoy. Las vistas previas con `confirmation_token` y los resultados sin `error` NO DEBEN marcarse.
- **FR-042** [R-SRV-2]: El middleware de versión de protocolo DEBE obtener las versiones admitidas de `HANDSHAKE_PROTOCOL_VERSIONS` y `MODERN_PROTOCOL_VERSIONS`, no del alias deprecado `SUPPORTED_PROTOCOL_VERSIONS`, y el conjunto resultante DEBE ser el mismo que hoy.
- **FR-043** [Principio V]: Los nombres, parámetros, descripciones y *hints* (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) de las tools NO DEBEN cambiar por esta spec.

**Redacción del log (decisión 10)**

- **FR-044** [Decisión 10]: DEBE existir la opción `log_redact_network` (por defecto `true`).
- **FR-045** [Decisión 10; doc. 11 §8]: Con la opción activa, toda línea de log DEBE sustituir el `public_hostname` configurado (sin distinguir mayúsculas, con o sin puerto) por `<public_hostname>` y cualquier nombre `*.ts.net` por `<redacted>.ts.net`, en cualquier campo o texto libre (incluidos `event`, `error`, URLs y trazas).
- **FR-046** [Decisión 10; doc. 11 §8]: Con la opción activa, toda dirección IPv4 o IPv6 válida que aparezca en cualquier campo o texto (`src_ip`, `peer_ip`, `ip`, `tailscale_ip`, `trusted_proxy_ips`, `supervisor_url`, `ws_url`, `Host`, `X-Forwarded-For`, `origin`…) DEBE sustituirse por un seudónimo `<ip:CLASE:HHHHHHHH>`, donde `CLASE` es `tailnet`, `link-local`, `private` (RFC 1918 y ULA), `public` u `other` y `HHHHHHHH` son 8 hexadecimales de un HMAC con una sal aleatoria por proceso. Las de loopback (`127.0.0.0/8`, `::1`) no se tocan.
- **FR-047** [Decisión 10; doc. 11 §8]: La misma redacción DEBE aplicarse a los mensajes de los loggers estándar de Python que salen por el log del add-on (los avisos `Invalid Host header`/`Invalid Origin header` del SDK de MCP, `uvicorn` y `aiohttp`).
- **FR-048** [Doc. 11 §8]: Con la opción activa, `sv_get_addon_logs` sobre el slug del propio Hermes DEBE aplicar la misma redacción de red a las líneas devueltas (cubre las escritas antes de actualizar).
- **FR-049** [Decisión 10]: Con `log_redact_network: false`, no se redacta ningún dato de red, se sigue redactando todo secreto como en 1.0.12, y el arranque DEBE registrar un aviso `log_network_redaction_disabled`.

**Calidad y publicación**

- **FR-050** [Principios VI, VII]: Cada requisito de comportamiento DEBE tener un test que falle sin el cambio; el control negativo («con la guarda quitada caen N tests») DEBE quedar escrito en el commit o en el PR.
- **FR-051** [Principio VIII]: Ningún fichero, test ni ejemplo DEBE contener datos de una instalación concreta ni identificadores de modelos de IA; los ejemplos usan `homeassistant.tailXXXX.ts.net`, `<slug>` y `192.0.2.x`/`198.51.100.x`/`203.0.113.x`.
- **FR-052** [Principio XI]: El CHANGELOG DEBE recoger los cambios de esta spec en la entrada `## [1.1.0] — AAAA-MM-DD` (la fecha la fija la publicación); la subida de versión la decide la publicación de 1.1.0, no esta spec.

### Revisión de seguridad de 1.1.0 (añadidos y cambios)

La revisión independiente de 1.1.0 (un ALTO, dos MEDIO y trece BAJO) cambia o
amplía estos requisitos. Donde contradicen a uno anterior, mandan estos.

- **FR-053** [ALTO-1; amplía FR-002]: El host del `client_id` DEBE ser un nombre DNS: en minúsculas al comparar, con al menos dos etiquetas, un TLD que empieza por letra y sin punto final. Se rechaza (`ip_host`) cualquier host con `:` o numérico en cualquier forma que acepte `inet_aton` (`127.1`, `10.1`, `2130706433`, `0177.0.0.1`, `0x7f.1`, `127.0.0.1.`) y (`bad_host`) cualquier otro que no sea un nombre DNS (`localhost`, `claude.ai.`). La descarga DEBE repetir la comprobación antes de conectar (defensa en profundidad): ninguna IP literal llega a la librería HTTP.
- **FR-054** [MEDIO-1]: DEBE existir la opción `oauth_cimd_allowed_hosts`, lista de nombres DNS, vacía por defecto. Vacía significa cualquier host público (el comportamiento de FR-002…FR-007). Con hosts, un `client_id` cuyo host (normalizado: minúsculas, sin punto final) no está en la lista se rechaza con `host_not_allowed` ANTES de descargar y de gastar cupo. Una entrada que no es un nombre DNS, o un valor ilegible, DEBE impedir arrancar: nunca puede acabar en lista vacía. Decisión del valor por defecto: el documento de Claude Code (`claude.ai`) está verificado, pero el host del documento CIMD de los clientes alojados de Claude (claude.ai, Desktop, móvil) no está documentado; una lista por defecto podría dejar fuera a un cliente legítimo, así que se deja vacía y DOCS.md y SECURITY.md explican el riesgo (la descarga revela la IP pública de casa) y cómo restringirlo. La petición NO DEBE llevar la versión de Hermes en el `User-Agent`.
- **FR-055** [MEDIO-2; amplía FR-007 y FR-016]: Además del cupo global, DEBE haber un cupo de 10 descargas por minuto por IP de origen en las peticiones anónimas (`/oauth/authorize`). Un cliente «conocido» —con el que el dueño ya inició sesión con contraseña correcta, o cuyo refresh token válido se está canjeando— NO DEBE gastar cupo al recargar su documento, y su entrada de caché NO DEBE expulsarla la de un cliente anónimo (hasta 16 clientes conocidos).
- **FR-056** [BAJO-6; cambia FR-018]: Solo un documento inválido, un `client_id` distinto o un 404/410 revocan los refresh tokens y borran la copia de la caché. Un 401/403, otro 4xx, un 3xx, una dirección prohibida o una codificación no pedida rechazan la petición pero, en el token endpoint, responden 503 `temporarily_unavailable` sin revocar ni borrar la copia.
- **FR-057** [BAJO-9; amplía FR-023]: Con `oauth_cimd_enabled: false`, o si el host de un cliente CIMD sale de `oauth_cimd_allowed_hosts`, sus access tokens dejan de validar y sus códigos pendientes no se canjean (401 `invalid_client`), sin borrar nada.
- **FR-058** [BAJO-3; matiza FR-024]: Si el `client_id` no tiene una forma válida, `oauth_cimd_rejected` NO DEBE registrar su host (lo elige quien llama).
- **FR-059** [BAJO-4, BAJO-5, BAJO-7, BAJO-8]: La descarga pide `Accept-Encoding: identity`, no descomprime y rechaza un cuerpo con otra codificación; el DNS de CIMD usa un pool de hilos propio; son también de uso especial las IPv4 traducidas (`::ffff:0:0:0/96`), `fec0::/10` y `5f00::/16`; un `redirect_uri` pedido con caracteres de control no casa con ninguno registrado.
- **FR-060** [BAJO-1, BAJO-2; amplía FR-046 y FR-048]: `sv_get_addon_logs("self")` es el log de Hermes y DEBE redactarse como tal. La redacción DEBE cubrir también los prefijos IPv6 que acaban en `::`, las IPv4 precedidas de `_` o de un escape `\n`/`\t`/`\r` y las IPv4 con ceros a la izquierda.

### Entidades clave

- **Documento de metadatos del cliente (CIMD)**: JSON público en la URL que es el `client_id`: `client_id`, `client_name`, `redirect_uris`, y opcionalmente `grant_types`, `response_types`, `token_endpoint_auth_method`, `client_uri`, `logo_uri`.
- **Entrada de caché CIMD**: documento válido ya normalizado, momento de descarga, momento de caducidad. Vive solo en memoria.
- **Cliente DCR**: el registro de 1.0.12 en `/data/oauth/clients/<uuid>.json`; no cambia.
- **Código de autorización**: añade `client_kind` (`dcr` o `cimd`) y, para CIMD, si el cliente admite refresh.
- **Token (access/refresh)**: añade `resource`; los antiguos sin `resource` siguen valiendo.
- **Opciones del add-on**: `response_max_bytes` (por defecto 131 072, efectivo ≤ 524 288), `wait_for_event_max_seconds` (efectivo ≤ 220), `oauth_cimd_enabled` (nuevo, `true`), `log_redact_network` (nuevo, `true`).
- **Seudónimo de IP**: `<ip:CLASE:HHHHHHHH>`, estable dentro de un proceso, distinto entre arranques.

Detalle en [data-model.md](./data-model.md).

## Criterios de éxito *(obligatorio)*

### Resultados medibles

- **SC-001**: El flujo completo de Claude Code con CIMD (documento real, puerto aleatorio, `localhost` y `127.0.0.1`) termina con tokens en el 100 % de las pruebas.
- **SC-002**: El 100 % de las URL de las pruebas que resuelven a una dirección de uso especial se rechazan con 0 conexiones abiertas hacia ellas.
- **SC-003**: El 100 % de las redirecciones de autorización de las pruebas llevan `iss` idéntico al `issuer` de los metadatos.
- **SC-004**: Los clientes y tokens con el formato de 1.0.12 siguen funcionando: 0 reautorizaciones forzadas en las pruebas de compatibilidad.
- **SC-005**: Con la configuración por defecto o con el antiguo 1 048 576 guardado, ninguna respuesta truncada por Hermes pasa de 131 072 bytes; con cualquier valor guardado, de 524 288.
- **SC-006**: Ningún `wait_for_event` efectivo puede durar más de 220 s, y una tool lenta emite su primer byte antes del primer intervalo de *keepalive* más un margen de 1 s en las pruebas.
- **SC-007**: Con la opción por defecto, 0 líneas del log de las pruebas contienen el hostname configurado o una IP que no sea de loopback.
- **SC-008**: El 100 % de las tools tienen `title`; `serverInfo.version` coincide con `__version__`; el 100 % de los resultados de prueba con `error` en el nivel superior salen con `isError: true` y 0 vistas previas lo hacen.
- **SC-009**: Cada cambio de comportamiento tiene al menos un test que falla con el cambio deshecho, y el recuento queda escrito.
- **SC-010**: La búsqueda de datos personales e identificadores de modelos de IA en el diff da 0 coincidencias.

## Supuestos

- **S-01** (base): 1.0.12 está implementada y fusionada; las líneas citadas en el plan son las de 1.0.11 más los cambios de la spec 001, y pueden moverse.
- **S-02** (alcance): quedan fuera de esta spec el Marketplace, repairs, traces, backups de HA y plantas/etiquetas (otras specs de 1.1.0), la subida de versión, `_meta["anthropic/maxResultSizeChars"]` (R-LIM-5, opcional), el orden estable de `tools/list`, la respuesta 403 `insufficient_scope`, OIDC Discovery, la caducidad de `logo_uri` y el tope de tamaño en tools que hoy no truncan (por ejemplo `ha_get_states` sin filtro).
- **S-03** (esquema de opciones): el esquema de `config.yaml` **no se estrecha** (`response_max_bytes` sigue en `int(10240,10485760)` y `wait_for_event_max_seconds` en `int(10,300)`). El Supervisor valida las opciones guardadas al arrancar y un valor fuera de rango impediría arrancar a quien lo tenga guardado. El máximo efectivo se aplica en el código. Estrechar el esquema queda para una versión posterior.
- **S-04** (antiguo valor por defecto): la interfaz del Supervisor guarda todas las opciones al guardar la configuración, y `auth_password` obliga a guardarla, así que casi todas las instalaciones tienen `response_max_bytes: 1048576` guardado sin haberlo elegido. Por eso 1 048 576 exacto se trata como «no personalizado». Quien de verdad quiera más de 128 KiB pone otro valor (hasta 524 288). No verificado en una instalación real.
- **S-05** (tiempo de descarga): 5 s, como Home Assistant; el borrador CIMD no fija ninguna cifra. Los endpoints OAuth de Claude esperan 10 s.
- **S-06** (tamaño): 5 120 bytes, lo que recomienda el borrador CIMD; el documento de Claude Code ocupa unos 330 bytes. Home Assistant usa 10 240.
- **S-07** (puerto del `client_id`): se aceptan solo URL sin puerto o con el 443, para que el AS no sirva para sondear puertos internos. El borrador no lo exige.
- **S-08** (loopback en DCR): la regla de puerto variable se aplica solo a clientes CIMD. Un cliente DCR registra el `redirect_uri` con su puerto real, así que hoy funciona; ampliar la regla a DCR no lo pide nadie y cambiaría un comportamiento estable.
- **S-09** (caché): 1 h sin `max-age`, entre 5 min y 24 h con él, y 5 min con `no-store`/`no-cache`. El borrador pide mínimo y máximo sin dar cifras. Una copia caducada solo se usa ante fallos temporales y durante 24 h desde su descarga.
- **S-10** (`isError`): la regla es «objeto con clave `error` en el nivel superior». Si alguna tool devuelve `error` junto a datos útiles (resultados parciales), el plan la revisa; ver research.md R-B3.
- **S-11** (temporizador de Claude Code): según el código del SDK `mcp` 2.3.0, con `stateless_http=True` y sin `json_response`, el camino de las versiones del handshake envía las cabeceras SSE al empezar y un *ping* cada 15 s (`sse-starlette`), y el de 2026-07-28 se compromete a SSE a los 15 s y sigue con *pings* cada 15 s. Los middlewares `BaseHTTPMiddleware` de Hermes reenvían en streaming. Lo que no se ha podido verificar es si Tailscale Funnel u otro proxy almacenan la respuesta: queda una prueba manual con Claude Code (quickstart.md) y la salida documentada (FR-037).
- **S-12** (seudónimos de IP): HMAC-SHA-256 con una sal aleatoria por proceso, recortado a 8 hexadecimales: sirve para correlacionar dentro de un arranque y no permite recuperar la IP ni correlacionar entre arranques. Se deja la clase (`public`, `private`, `tailnet`…) porque ayuda a diagnosticar sin identificar.
- **S-13** (loopback en el log): `127.0.0.1` y `::1` se dejan tal cual: son iguales en todas las instalaciones y son la pista principal para diagnosticar el proxy de Tailscale.
- **S-14** (opción de CIMD): `oauth_cimd_enabled` no estaba en la petición; se añade como interruptor de emergencia para volver a DCR sin bajar de versión si un cliente falla con CIMD.
- **S-15** (validación de `iss` por Claude): la documentación de Claude no dice si valida `iss`; se emite porque la spec MCP lo recomienda y el borrador CIMD lo exige.
- **S-16** (URL del CIMD de claude.ai): no está documentada; claude.ai y Desktop pueden seguir usando DCR (callback `https://claude.ai/api/mcp/auth_callback`), que no cambia.
