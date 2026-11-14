# Investigación: Hermes 1.1.0 — OAuth y protocolo

Fuentes: la investigación de límites de Claude, CIMD e `iss` (documento «10»),
la del ecosistema MCP («06»), el inventario de plataforma («02», secciones MCP y
OAuth), las APIs de HA para 1.1.0 («11», sección 8) y el informe de síntesis
(«00», §6 y §7), todos de noviembre de 2026. Se completó leyendo el código del
SDK `mcp` 2.3.0, `mcp-types` 2.3.0 y `sse-starlette` 3.7.0 instalados en un
entorno de pruebas, y el código de Hermes 1.0.11 + spec 001.

Formato: **Decisión** / **Por qué** / **Alternativas descartadas**.

## Trazabilidad

| Requisito de la investigación | Qué pide | FR de spec.md |
|---|---|---|
| R-LIM-1 | `response_max_bytes` por defecto 131 072 | FR-032, FR-034, FR-038 |
| R-LIM-2 | máximo ≤ 524 288 | FR-033, FR-038 |
| R-LIM-3 | máximo de `wait_for_event_max_seconds` ≤ 220 | FR-035, FR-038 |
| R-LIM-4 | temporizador de 60 s de Claude Code | FR-036, FR-037 |
| R-LIM-5 (opcional) | `_meta["anthropic/maxResultSizeChars"]` | fuera de alcance (S-02) |
| R-CIMD-1 | anunciar CIMD | FR-001, FR-023 |
| R-CIMD-2 | forma de la URL y descarga | FR-002, FR-004 |
| R-CIMD-3 | 5 120 bytes | FR-005 |
| R-CIMD-4 | SSRF y DNS rebinding | FR-006, FR-007 |
| R-CIMD-5 | validación del documento | FR-008, FR-009, FR-010 |
| R-CIMD-6 | `redirect_uri` y loopback | FR-011, FR-012, FR-013 |
| R-CIMD-7 | errores sin redirigir; `invalid_client`/503 | FR-014, FR-015, FR-018 |
| R-CIMD-8 | caché | FR-016, FR-017, FR-019 |
| R-CIMD-9 | `client_id` igual al propio | FR-003 |
| R-CIMD-10 | pantalla de consentimiento | FR-021 |
| R-CIMD-11 | DCR de respaldo | FR-020, FR-022 |
| R-ISS-1 | `iss` en toda redirección | FR-025, FR-027 |
| R-ISS-2 | anunciar `iss` | FR-026 |
| R-SCOPE-1 | `scopes_supported` en el recurso | FR-028 |
| R-SCOPE-2 | `scope` en `WWW-Authenticate` | FR-029 |
| R-AUD-1 | audiencia | FR-030, FR-031 |
| R-SRV-1 | `version` | FR-039 |
| R-SRV-2 | versiones de protocolo | FR-042 |
| R-SRV-3 | `isError` | FR-041 |
| R-SRV-4 | `title` | FR-040 |
| Decisión 10 + doc. 11 §8 | redacción de red en el log | FR-044 … FR-049 |

## Fase 0 — Configuración

### R-0.1 Recortar en el código, no en el esquema

- **Decisión**: el esquema de `config.yaml` se queda como está. `load_config()` aplica los máximos efectivos (`response_max_bytes` ≤ 524 288, `wait_for_event_max_seconds` ≤ 220) y anota cada ajuste en `HermesConfig.adjustments` (lista de `{option, configured, applied, reason}`). `__main__` los registra cuando el log ya está configurado (el log se configura después de cargar la configuración).
- **Por qué**: el Supervisor valida las opciones guardadas al arrancar; estrechar el rango dejaría sin arrancar a quien tenga guardado 1 048 576 o 300 (spec S-03). Registrar desde `load_config` no vale: se ejecuta antes de `setup_logging`.
- **Alternativas**: estrechar el esquema (rompe el arranque); avisar sin recortar (no cumple R-LIM-2/3).

### R-0.2 El antiguo valor por defecto

- **Decisión**: `response_max_bytes == 1_048_576` se trata como «no personalizado» y se aplica 131 072, con `reason: "legacy_default"`.
- **Por qué**: la interfaz del Supervisor guarda todas las opciones al guardar la configuración (spec S-04), así que cambiar solo el valor por defecto no llegaría a casi nadie.
- **Alternativas**: recortar 1 048 576 a 524 288 (sigue por encima de lo que acepta claude.ai); migrar `options.json` (Hermes no debe reescribir sus propias opciones).

### R-0.3 Opciones nuevas

- **Decisión**: `oauth_cimd_enabled: "bool?"` (por defecto `true`) y `log_redact_network: "bool?"` (por defecto `true`), con `HERMES_OAUTH_CIMD_ENABLED` y `HERMES_LOG_REDACT_NETWORK` en `run.sh` y campos en `HermesConfig`. Se declaran en la fase 0 para que los lotes A y C no toquen los ficheros de configuración.

## Lote A — OAuth (CIMD, `iss`, audiencia, metadatos)

### R-A1 Módulo propio para CIMD

- **Decisión**: `hermes/src/hermes/cimd.py` con: `parse_client_id_url(url)` (FR-002), `CimdResolver` (descarga, SSRF, validación, caché, cupo) y `redirect_uri_matches(registered, requested)` (FR-011). `oauth.py` solo lo usa.
- **Por qué**: `oauth.py` tiene ~1 600 líneas; la descarga y la defensa SSRF se prueban mejor aisladas. El SDK no trae nada de CIMD del lado del servidor de autorización (doc. 10 §2.6).
- **Alternativas**: ampliar `oauth.py` (ilegible); usar `authlib` (no se usa hoy y no trae CIMD).

### R-A2 Defensa SSRF con un resolvedor propio de `aiohttp`

- **Decisión**: una subclase de `aiohttp.abc.AbstractResolver` que resuelve con `getaddrinfo` del bucle, rechaza la petición entera si **alguna** dirección no es global y devuelve solo las validadas, con `hostname` para SNI. Se usa en un `TCPConnector(resolver=…, use_dns_cache=False)` dedicado y con `trust_env=False` (sin proxies del entorno). Una IP literal en el host pasa por la misma comprobación. Clasificación con `ipaddress`: se rechaza si `not ip.is_global` o `ip.is_multicast`, o si es IPv6 que embebe IPv4 (`ipv4_mapped`, `6to4`, `teredo`) cuya IPv4 no es global; 100.64.0.0/10 no es global en `ipaddress`, así que la tailnet queda fuera.
- **Por qué**: la conexión va a la IP ya validada, sin segunda resolución: cierra el DNS rebinding (doc. 10, R-CIMD-4). `allow_redirects=False` evita la petición al destino redirigido que sí hace Home Assistant (doc. 10 §2.5).
- **Alternativas**: resolver y luego pedir por nombre (rebinding); pedir a la IP con `Host` manual (rompe SNI/verificación TLS); permitir red local como HA (lo prohíbe el borrador).

### R-A3 Lectura acotada y JSON estricto

- **Decisión**: `timeout=aiohttp.ClientTimeout(total=5)`, `read(5121)` por trozos hasta 5 121 bytes; si se leen más de 5 120, error `too_large`. `json.loads` con `object_pairs_hook` que rechaza claves duplicadas y `parse_constant` que rechaza `NaN`/`Infinity`; decodificación `utf-8` estricta (un BOM es error).
- **Por qué**: R-CIMD-3 y R-CIMD-5; mismo criterio que HA (no confiar en un prefijo truncado).

### R-A4 Caché y fallos temporales

- **Decisión**: diccionario en memoria, LRU de 64 entradas: `{url: (doc, fetched_at, expires_at)}`. Vida: `max-age` acotado a [300, 86 400]; 3 600 sin `max-age`; 300 con `no-store`/`no-cache`. Fallos **temporales** (red, timeout, 5xx, 429, cupo agotado) → si hay copia con menos de 24 h desde `fetched_at`, se usa; si no, `CimdTemporaryError`. Fallos **definitivos** (4xx salvo 429, 3xx, tamaño, JSON o contenido inválido, `client_id` distinto) → se borra la copia y `CimdInvalidError`; el llamador revoca los refresh tokens del cliente (FR-018).
- **Por qué**: el borrador pide respetar la caché HTTP con mínimo y máximo, no cachear errores y no perder la confianza por un fallo temporal (doc. 10 §2.2). Las cifras son supuestos (spec S-09).
- **Alternativas**: sin caché, como HA (una caída de claude.ai cortaría los refresh); caché en disco (otra superficie que sanear, sin necesidad).

### R-A5 Cupo de descargas

- **Decisión**: `asyncio.Semaphore(4)` y una ventana deslizante de 30 descargas por minuto en el `CimdResolver`. Agotado el cupo → fallo temporal sin conexión.
- **Por qué**: `/oauth/authorize` es público; el límite pre-auth por IP (20/min) no acota a quien rota IPs. Así Hermes no sirve de amplificador.

### R-A6 Dónde se valida en el flujo

- **Decisión**: en `authorize_get` y en `authorize_post`, **antes** de mirar la contraseña, si el `client_id` empieza por `https://`: `oauth_cimd_enabled`, `parse_client_id_url`, FR-003, `resolve`, `redirect_uri_matches`. Cualquier fallo → `_request_error_html` (400) con un motivo genérico; nunca redirección. El cliente DCR mantiene el orden de 1.0.12 (contraseña y luego cliente).
- **Por qué**: FR-013/FR-014. Un error del cliente no debe costar un intento de contraseña, igual que PKCE (comentario en `oauth.py`).

### R-A7 Código, tokens y sesiones

- **Decisión**: el código guarda `client_kind` (`"cimd"`/`"dcr"`) y `allow_refresh`. El canje devuelve `refresh_token` solo si `allow_refresh` (DCR: siempre, como hoy). Access y refresh guardan `resource = self._canonical_resource`; `_issue_from_refresh` lo copia o, si falta, pone el canónico. `validate_token` rechaza si `resource` existe y difiere. En el refresh de un cliente CIMD se llama a `resolve` (caché) antes de emitir: `CimdInvalidError` → `invalid_client` 401 y revocación; `CimdTemporaryError` → 503 `temporarily_unavailable`. `_revoke_previous_sessions` no filtra por `client_id` cuando este empieza por `https://`.
- **Por qué**: FR-010, FR-015, FR-019, FR-020, FR-030, FR-031. El `client_id` de CIMD es el mismo en todos los dispositivos del dueño.
- **Alternativas**: comparar audiencia solo en el AS (no cumple el MUST del RS, doc. 10 §4.2); exigir `resource` en tokens viejos (rompe la decisión de no forzar reautorizaciones).

### R-A8 `iss`

- **Decisión**: un único método `_redirect_to_client(redirect_uri, params)` que añade `iss=self._base_url` y es el único que construye `RedirectResponse` hacia el cliente. Metadatos con `authorization_response_iss_parameter_supported: true`. `issuer` y `iss` salen de `self._base_url`.
- **Por qué**: RFC 9207 y spec MCP 2026-07-28 (SHOULD, MUST anunciarlo); borrador CIMD (MUST). Un único constructor impide que una redirección futura de error salga sin `iss`. Hoy Hermes no redirige ningún error; FR-027 lo mantiene.

### R-A9 Pantalla de consentimiento

- **Decisión**: `_login_html` recibe `client_kind`, el host del `client_id` y si el destino es loopback. Para CIMD: «**claude.ai** (se presenta como «Claude Code») solicita acceso…», destino `http://localhost` sin puerto, y un aviso extra si es loopback. Todo pasa por `html.escape`. DCR, como en 1.0.12.
- **Por qué**: R-CIMD-10; `client_name` es autodeclarado y no puede ser la identidad.

## Lote B — Protocolo MCP

### R-B1 `version` y `isError` en una subclase del servidor

- **Decisión**: `hermes/src/hermes/mcp_server.py` con `HermesMCPServer(MCPServer)` y una fábrica `build_mcp_server(instructions)` que pasa `version=__version__`. La subclase sobrescribe `call_tool(name, arguments, context)`: llama al padre y, si el resultado es un `CallToolResult` sin `is_error`, con un único `TextContent` cuyo JSON es un objeto con la clave `error` en el nivel superior y sin `confirmation_token`, devuelve una copia con `is_error=True` y el mismo contenido. Un `error` con valor `null` no cuenta.
- **Por qué**: `_handle_call_tool` del SDK llama a `self.call_tool` (SDK `server.py:437-456`), y `convert_result` deja pasar un `CallToolResult` tal cual (`func_metadata.py:204-207`). Así se cubren las ~367 respuestas `{"error": …}` sin tocar 37 ficheros de tools (principio IX). Las excepciones ya salen con `is_error=True` (`server.py:456`).
- **Alternativas**: cambiar cada `return {"error": …}` por una excepción (cientos de cambios y pierde el JSON estructurado); envolver `tool.fn` (rompe la detección del parámetro `ctx`).

### R-B2 `title` centralizado

- **Decisión**: `title_for(name)` en `tools/_annotations.py`: quita el prefijo (`ha_`, `fs_`, `sv_`), separa por `_`, pone en mayúscula la primera palabra y aplica una tabla de excepciones (`hacs`→`HACS`, `lovelace`→`Lovelace`, `ws`→`WS`, `id`→`ID`, …) y un sufijo de área (« (Home Assistant)», « (files)», « (Supervisor)»). `apply_tool_annotations` pone el mismo valor en `tool.title` y en `ToolAnnotations(title=…)`. Un test exige `title` no vacío y único en todas las tools.
- **Por qué**: una tabla, como las anotaciones (principio V: un solo sitio revisable). `Tool.title` existe en el SDK (`tools/base.py:40`) y `annotations.title` tiene precedencia en la spec.

### R-B3 Tools que devuelven `error` junto a datos

- **Decisión**: la tarea de auditoría hace `grep` de los `return` con `"error"` en el nivel superior acompañados de datos de éxito. Si aparece alguna (resultado parcial), se documenta en el test como excepción explícita en una lista `_NOT_AN_ERROR` de `mcp_server.py`, nunca cambiando la forma de la respuesta.
- **Por qué**: spec S-10; marcar como error un resultado útil confundiría al cliente.

### R-B4 Versiones de protocolo

- **Decisión**: `from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSIONS` y `self._supported = (*HANDSHAKE_PROTOCOL_VERSIONS, *MODERN_PROTOCOL_VERSIONS)`. Test: igual a la tupla actual y sin el alias en el código fuente.
- **Por qué**: el alias está marcado «Deprecated … Kept as the union for v1.x compatibility» (`mcp_types/version.py:44-48`).

### R-B5 Temporizador de 60 s hasta el primer byte (Claude Code)

- **Hallazgo** (lectura del código instalado):
  - Versiones del handshake (≤ 2025-11-25), `stateless_http=True`, `json_response=False`: `StreamableHTTPServerTransport._handle_post_request` crea un `EventSourceResponse` y lo arranca «this will send headers immediately»; `sse-starlette` envía `http.response.start` antes de iterar y un comentario `: ping` cada `DEFAULT_PING_INTERVAL = 15` s.
  - 2026-07-28: `_streamable_http_modern.handle_modern_request` espera hasta `_SSE_PING_INTERVAL = 15.0` s; si la tool no ha terminado ni ha emitido una notificación, envía las cabeceras SSE y `: ping` cada 15 s.
  - `ha_wait_for_event` ya emite `report_progress` cada 15 s (`_KEEPALIVE_INTERVAL`), que adelanta el compromiso a SSE si el cliente manda `progressToken`.
  - Los middlewares de Hermes son `BaseHTTPMiddleware` (reenvían en streaming tras `http.response.start`) o ASGI puros; `LoggingMiddleware` solo almacena cuerpos de respuestas ≥ 400.
- **Decisión**: no hace falta código nuevo de *keepalive*: el SDK ya lo hace. La mitigación concreta es (1) un test de regresión que pase una tool lenta por la pila completa de middlewares con el intervalo de *ping* del SDK parcheado a 0,2 s, para las dos familias de versión, y compruebe que llegan cabeceras y un *ping* antes del resultado (FR-036), de modo que un middleware futuro que almacene la respuesta rompa el test; y (2) documentar la salida si el proxy de delante almacena la respuesta (FR-037).
- **Pendiente** (no verificable aquí): si Tailscale Funnel reenvía la respuesta en streaming. Prueba manual en quickstart.md.
- **Alternativas**: responder antes con un resultado provisional (rompe el protocolo); bajar el intervalo de *ping* del SDK (no hace falta: 15 s < 60 s).

## Lote C — Redacción del log

### R-C1 Un redactor de red único

- **Decisión**: en `logging_setup.py`, `configure_network_redaction(enabled, public_hostname)` guarda el estado del módulo (sal aleatoria `secrets.token_bytes(16)`), y `redact_network(text)` hace, en orden: (1) sustituir el `public_hostname` (sin puerto, sin distinguir mayúsculas) por `<public_hostname>`; (2) `[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.ts\.net` → `<redacted>.ts.net`; (3) candidatos IPv4 (`\b\d{1,3}(\.\d{1,3}){3}\b`) e IPv6 (secuencias de hex y `:` con al menos dos `:`, opcionalmente entre corchetes) validados con `ipaddress`; los válidos y no loopback → `<ip:CLASE:HHHHHHHH>` (`hmac.new(sal, ip.packed, sha256).hexdigest()[:8]`). Clase, en este orden: `tailnet` (100.64.0.0/10 y `fd7a:115c:a1e0::/48`), `link-local`, `private` (RFC 1918 y `fc00::/7`, enumerados: `is_private` de `ipaddress` también incluye los rangos de documentación), `public` (`is_global`), `other`.
- **Por qué**: doc. 11 §8 propone marcar el /24; un seudónimo con sal no filtra nada y conserva la correlación (spec S-12). Validar con `ipaddress` evita falsos positivos (`2026.11.1`, `999.1.1.1`, horas `06:54:12`).
- **Alternativas**: conservar el /24 (sigue identificando al proveedor y la zona); hash sin sal (reversible por fuerza bruta en IPv4).

### R-C2 Dónde se aplica

- **Decisión**: (a) un processor `_redact_network_processor` justo después de `_redact_processor`, recursivo sobre `str`, `list` y `dict`; (b) un `logging.Filter` en el manejador raíz que formatea `record.getMessage()`, lo redacta y deja `record.args = None` — cubre `mcp.server.transport_security`, `uvicorn` y `aiohttp`; (c) `sv_get_addon_logs` aplica `redact_network` al texto cuando el slug es el de Hermes y la opción está activa.
- **Por qué**: el aviso `Invalid Host header` del SDK va por `logging` estándar, no por `structlog` (doc. 11 §8).

### R-C3 Opción desactivada

- **Decisión**: con `enabled=False`, `redact_network` devuelve el texto tal cual y el processor/filtro no hacen nada. `__main__` registra `log_network_redaction_disabled` (warning). Los secretos se siguen redactando por `_redact_processor`, que no cambia.

## Integración

### R-I1 Cableado en `__main__`

- **Decisión**: `setup_logging(level, redact_network=config.log_redact_network, public_hostname=config.public_hostname)`; registrar `config.adjustments`; `OAuthServer(…, cimd_enabled=config.oauth_cimd_enabled)`; `build_mcp_server(INSTRUCTIONS)` en vez de `MCPServer("hermes", …)`.
- **Por qué**: un solo dueño de `__main__.py` evita conflictos entre lotes; cada lote deja valores por defecto que funcionan sin el cableado (`cimd_enabled=True`, redacción desactivada hasta que se configure, `build_mcp_server` probado por su cuenta).

### R-I2 Documentación

- **Decisión**: DOCS.md (sección «Límites y Claude Code»), tabla de opciones de los dos README (valores, rangos efectivos, opciones nuevas, nota de migración), CHANGELOG bajo `## [1.1.0] — AAAA-MM-DD` (creando la sección si no existe; la fecha definitiva la fija la publicación), `docs/HOJA-DE-RUTA.md` (marcar CIMD, `iss`, límites, protocolo y C9/decisión 10 como hechos en 1.1.0).
