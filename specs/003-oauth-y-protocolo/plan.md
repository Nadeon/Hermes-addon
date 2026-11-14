# Plan de implementación: Hermes 1.1.0 — OAuth moderno, límites de Claude, protocolo MCP y log sin datos de red

**Directorio**: `specs/003-oauth-y-protocolo` | **Fecha**: 2026-11-14 | **Spec**: [spec.md](./spec.md)

**Entrada**: especificación de `specs/003-oauth-y-protocolo/spec.md`.

**Rama de trabajo**: la que indique el mantenedor (spec-kit no crea ramas), con
1.0.12 ya fusionada. Los lotes se implementan en worktrees separados y se
integran en esa rama.

## Resumen

Parte de la 1.1.0 dedicada a OAuth, protocolo, límites y log. El enfoque:

- Una **fase 0** secuencial y pequeña deja la configuración lista: valores por
  defecto, máximos efectivos y las dos opciones nuevas (`oauth_cimd_enabled`,
  `log_redact_network`). Así ningún lote toca `config.py`, `config.yaml` ni
  `run.sh`.
- Tres **lotes paralelos** que no comparten ningún fichero:
  - **A — OAuth**: CIMD en un módulo nuevo `cimd.py` (descarga con defensa
    SSRF, validación, caché), `iss`, `scopes_supported` en el recurso,
    audiencia en los tokens, compatibilidad DCR.
  - **B — Protocolo MCP**: subclase del servidor MCP con `version` e `isError`,
    `title` centralizado, versiones de protocolo, `scope` en
    `WWW-Authenticate` y el test del primer byte.
  - **C — Redacción del log**: redactor de hostname e IPs para `structlog`, los
    loggers estándar y `sv_get_addon_logs`.
- Un **lote final de integración**: cableado en `__main__.py` y documentación
  (DOCS, README, CHANGELOG, hoja de ruta).

El estudio del temporizador de 60 s de Claude Code (research R-B5) concluye que
el SDK ya emite cabeceras y *pings* cada 15 s; la mitigación es un test que lo
fije a través de la pila de Hermes y la documentación de la salida si un proxy
almacena la respuesta.

Detalles y alternativas en [research.md](./research.md); formas de entrada y
salida en [contracts/](./contracts/); estados en
[data-model.md](./data-model.md); validación en [quickstart.md](./quickstart.md).

## Contexto técnico

**Lenguaje/versión**: Python 3.13.

**Dependencias principales**: SDK `mcp` 2.3.0 (`MCPServer`, Streamable HTTP *stateless*), `mcp-types` 2.3.0, `aiohttp` (ya declarada; cliente de la descarga CIMD con resolvedor propio), `starlette`, `uvicorn`, `structlog`, `sse-starlette` (dependencia del SDK). No se añade ninguna dependencia.

**Almacenamiento**: ficheros JSON en `/data/oauth/` (clientes DCR, códigos, tokens); la caché CIMD vive solo en memoria.

**Pruebas**: `pytest` + `pytest-asyncio` + `aioresponses` + `httpx`. La descarga CIMD se prueba con un resolvedor DNS falso y `aioresponses`; el primer byte, con la app ASGI completa y un `send` que anota tiempos.

**Plataforma**: add-on de Home Assistant OS, detrás de Tailscale Funnel o de un proxy inverso; Home Assistant ≥ 2024.10.0 (tras 1.0.12).

**Tipo de proyecto**: servidor MCP con AS/RS OAuth propio (un paquete en `hermes/src/hermes/`, tests en `tests/`).

**Objetivos de rendimiento**: una descarga CIMD por cliente cada hora como mucho en uso normal (caché); ≤ 5 s por descarga; redacción del log en tiempo lineal sobre cada línea.

**Restricciones**: sin rupturas para clientes DCR y tokens existentes (decisión); fail-closed en CIMD (principio III); nada de datos personales ni identificadores de modelos (VIII); no tocar el esquema de opciones (spec S-03); no cambiar nombres, parámetros ni *hints* de tools (V).

**Escala/alcance**: 11 ficheros de código y configuración (2 nuevos: `cimd.py` y `mcp_server.py`) y 6 ficheros de test nuevos; las ~187 tools de 1.0.12 cambian solo en `title` e `isError`, de forma centralizada.

## Comprobación contra la constitución

*Puerta: debe pasar antes de la fase 0 y repetirse tras el diseño.*

| Principio | Cómo se cumple | Estado |
|---|---|---|
| I. Seguridad primero | CIMD con defensa SSRF completa (sin redirecciones, sin direcciones especiales, conexión a la IP validada, tope de tamaño y tiempo, cupo global); consentimiento con el host real del cliente; audiencia comprobada en el RS. | OK |
| II. Secretos | El log de CIMD lleva solo motivo y host, nunca el documento; los secretos se siguen redactando aunque se desactive la redacción de red. | OK |
| III. Fail-closed | Cualquier duda en CIMD (forma, DNS, tamaño, JSON, `client_id`) rechaza; un fallo definitivo revoca los refresh del cliente; nunca se redirige un error. | OK |
| IV. Dos pasos | No se toca la confirmación; las vistas previas con `confirmation_token` no se marcan como error. | OK |
| V. Nombre y descripción veraces | Solo se añade `title`; nombres, parámetros, descripciones y *hints* no cambian (FR-043); `isError` hace que el resultado diga la verdad sobre el fallo. | OK |
| VI. Probar lo arreglado | Cada FR de comportamiento tiene su test (tasks.md, FR-050). El primer byte se fija con un test de la pila completa. | OK |
| VII. Control negativo | Cada bloque tiene su tarea de control negativo con lo que hay que deshacer (FR-050). | OK |
| VIII. Privacidad | Redacción de red por defecto; ejemplos con marcadores y rangos de documentación; grep de privacidad en cada lote (FR-051). | OK |
| IX. Cambios mínimos | `isError` y `title` centralizados en vez de tocar 37 ficheros de tools; R-LIM-5, `insufficient_scope`, orden de `tools/list` y topes en tools sin truncado quedan fuera (spec S-02). Desviación justificada: la opción `oauth_cimd_enabled` no estaba pedida (spec S-14). | OK, justificado |
| X. Comentarios en español con el porqué | Cada guarda nueva cita la amenaza (SSRF, rebinding, phishing) o la restricción externa (Supervisor, Claude Code). Mensajes al cliente en inglés. | OK |
| XI. Versión coherente | No se sube la versión en esta spec (FR-052); el CHANGELOG se rellena bajo `## [1.1.0] — AAAA-MM-DD`; README EN/ES sincronizados; DOCS.md cambia porque cambia la configuración. | OK |

Repetida tras el diseño (fase 1): sin cambios. La única desviación (opción no
pedida) está justificada arriba.

## Estructura del proyecto

### Documentación (esta funcionalidad)

```text
specs/003-oauth-y-protocolo/
├── spec.md
├── plan.md              # este fichero
├── research.md          # decisiones, alternativas y trazabilidad
├── data-model.md        # documento CIMD, caché, tokens, opciones, seudónimos
├── quickstart.md        # cómo validar
├── contracts/
│   ├── oauth.md         # metadatos, authorize, token, 401
│   └── mcp-y-log.md     # serverInfo, title, isError, transporte, log
├── checklists/requirements.md
└── tasks.md
```

### Código fuente (raíz del repositorio)

```text
hermes/
├── config.yaml                     # fase 0: valores por defecto y opciones nuevas
├── run.sh                          # fase 0: exporta las opciones
├── CHANGELOG.md                    # integración
├── DOCS.md                         # integración
└── src/hermes/
    ├── config.py                   # fase 0: máximos efectivos, adjustments, opciones nuevas
    ├── cimd.py                     # lote A (NUEVO)
    ├── oauth.py                    # lote A
    ├── mcp_server.py               # lote B (NUEVO)
    ├── middleware.py               # lote B
    ├── tools/_annotations.py       # lote B
    ├── logging_setup.py            # lote C
    ├── tools/addons.py             # lote C (solo sv_get_addon_logs)
    └── __main__.py                 # integración
tests/                              # cada test pertenece al lote de su código (tasks.md)
README.md, README.es.md             # integración
docs/HOJA-DE-RUTA.md                # integración
```

**Decisión de estructura**: se mantiene la estructura; se añaden
`hermes/src/hermes/cimd.py`, `hermes/src/hermes/mcp_server.py` y los tests
nuevos `tests/test_cimd.py`, `tests/test_oauth_cimd_flow.py`,
`tests/test_mcp_protocol.py`, `tests/test_first_byte.py`,
`tests/test_log_redact_network.py` y `tests/test_main_wiring.py`.

## Decisiones técnicas por fichero

Las líneas son las de 1.0.11 más la spec 001; pueden moverse.

### Fase 0 — Configuración (secuencial, antes de abrir los lotes)

| Fichero:línea | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/config.py:197` y `:311` | Constantes `RESPONSE_MAX_BYTES_DEFAULT = 131_072`, `RESPONSE_MAX_BYTES_CAP = 524_288`, `RESPONSE_MAX_BYTES_LEGACY_DEFAULT = 1_048_576`, `WAIT_FOR_EVENT_MAX_SECONDS_CAP = 220`; el campo y `load_config` usan el valor por defecto nuevo. | FR-032 |
| `hermes/src/hermes/config.py` (`load_config`) | Tras leer el entorno: 1 048 576 → 131 072 con `reason: "legacy_default"`; > 524 288 → 524 288 y `wait_for_event_max_seconds` > 220 → 220 con `reason: "above_cap"`. Cada ajuste se añade a `adjustments: list[dict]` (campo nuevo, no lo rellena el usuario). Comentario del porqué (Supervisor valida opciones guardadas; la interfaz guarda todas). | FR-033…FR-035 |
| `hermes/src/hermes/config.py` (campos) | `oauth_cimd_enabled: bool = True` (`HERMES_OAUTH_CIMD_ENABLED`), `log_redact_network: bool = True` (`HERMES_LOG_REDACT_NETWORK`). | FR-023, FR-044 |
| `hermes/config.yaml:157` y `:118` | `options.response_max_bytes: 131072`; esquema sin cambios (comentario de por qué no se estrecha). Opciones nuevas en `schema` (`bool?`) y `options` (`true`). | FR-032, FR-023, FR-044 |
| `hermes/run.sh:67` y nuevas líneas | `cfg_default response_max_bytes 131072`; exportar `HERMES_OAUTH_CIMD_ENABLED` y `HERMES_LOG_REDACT_NETWORK` con `cfg_default … true`. | FR-032, FR-023, FR-044 |
| `tests/test_config_validation.py` | Por defecto 131 072; 1 048 576 → 131 072 + ajuste; 300 000 se respeta; 4 000 000 → 524 288; `wait` 300 → 220, 220 y 10 se respetan; opciones nuevas por defecto `True` y `false` leído. | FR-032…FR-035 |
| `tests/test_addon_manifest.py` | Coherencia `config.yaml` ↔ `config.py` ↔ `run.sh` de los valores por defecto y de las opciones nuevas; el esquema de `response_max_bytes` sigue admitiendo 1 048 576 (control de S-03). | FR-032, FR-023, FR-044 |
| `tests/test_run_sh_options.py` | `run.sh` exporta las dos opciones nuevas con su valor por defecto. | FR-023, FR-044 |

### Lote A — OAuth

| Fichero:línea | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/cimd.py` (nuevo) | `parse_client_id_url(url) -> str \| None` (motivo de rechazo o `None`): reglas de FR-002. `class _SafeResolver(AbstractResolver)` (research R-A2). `class CimdResolver` con `resolve(url) -> CimdClient`, excepciones `CimdTemporaryError`/`CimdInvalidError(reason)`, semáforo de 4 y ventana de 30/min, caché LRU de 64 con la vida de FR-016 y el uso de copia caducada de FR-017. `validate_document(url, raw) -> CimdClient` (FR-008…FR-010). `redirect_uri_matches(registered, requested) -> bool` (FR-011). Comentarios del porqué (borrador CIMD §6, RFC 6890, RFC 8252, rebinding). | FR-002, FR-004…FR-012, FR-016, FR-017 |
| `hermes/src/hermes/oauth.py:418-450` (`OAuthServer.__init__`) | Parámetro `cimd_enabled: bool = True` y `self._cimd = CimdResolver(...)`. | FR-023 |
| `hermes/src/hermes/oauth.py:526-537` | `scopes_supported: ["mcp"]` en el recurso protegido. | FR-028 |
| `hermes/src/hermes/oauth.py:571-584` | `client_id_metadata_document_supported` (si `cimd_enabled`) y `authorization_response_iss_parameter_supported: true`. | FR-001, FR-026 |
| `hermes/src/hermes/oauth.py` (método nuevo junto a `:559`) | `_check_cimd_client(client_id, redirect_uri) -> CimdClient \| HTMLResponse`: desactivado, forma, FR-003 (igual a `issuer`, a `_canonical_resource` o host = `public_hostname`), `resolve`, `redirect_uri_matches`; error → `_request_error_html` + `oauth_cimd_rejected`. | FR-003, FR-013, FR-014, FR-023, FR-024 |
| `hermes/src/hermes/oauth.py:686-714` (`authorize_get`) | Si `client_id` empieza por `https://`, `_check_cimd_client` antes de mostrar el formulario; pasar `client_kind`, host del `client_id` y loopback a `_login_html`. | FR-013, FR-014, FR-021 |
| `hermes/src/hermes/oauth.py:716-890` (`authorize_post`) | Para CIMD, `_check_cimd_client` antes del throttle y de la contraseña; saltar la lectura de `clients/<id>.json` y la comparación exacta de `:833`. El código guarda `client_kind` y `allow_refresh`. Sustituir el `RedirectResponse` de `:879-890` por `_redirect_to_client`, que añade `iss`. | FR-010, FR-013, FR-025, FR-027 |
| `hermes/src/hermes/oauth.py:205-217` (junto a `_append_query`) | `_redirect_to_client(redirect_uri, params)`: única forma de construir la redirección al cliente; siempre añade `iss=self._base_url`. | FR-025 |
| `hermes/src/hermes/oauth.py:933-1041` (`_token_auth_code`) | Access y refresh con `resource`; si `allow_refresh` es `False`, sin refresh token en disco ni en la respuesta. | FR-010, FR-030 |
| `hermes/src/hermes/oauth.py:1043-1200` (`_token_refresh`, `_issue_from_refresh`) | Cliente CIMD: `resolve` antes de emitir; `CimdInvalidError` → revocar refresh del cliente y 401 `invalid_client`; `CimdTemporaryError` → 503 `temporarily_unavailable`. `resource` heredado o canónico. | FR-015, FR-018, FR-019, FR-030, FR-031 |
| `hermes/src/hermes/oauth.py:349-400` (`_revoke_previous_sessions`) | No filtrar por `client_id` si empieza por `https://`; el tope global se mantiene. | FR-020 |
| `hermes/src/hermes/oauth.py` (función nueva junto a `:263`) | `_revoke_client_refresh_tokens(client_id) -> int`. | FR-018 |
| `hermes/src/hermes/oauth.py:1235-1253` (`validate_token`) | Rechazar si `resource` existe y difiere de `_canonical_resource`; aceptar si falta. | FR-030, FR-031 |
| `hermes/src/hermes/oauth.py:1341-1400` (`_login_html`) | Bloque de consentimiento CIMD: host del `client_id` como identidad, nombre declarado, destino sin puerto en loopback y aviso extra. DCR sin cambios. Todo con `html.escape`. | FR-021 |
| `hermes/src/hermes/oauth.py:588-680` (`register_client`) | Sin cambios de código; test de que el `client_id` sigue siendo UUID. | FR-022 |
| `tests/test_cimd.py` (nuevo) | Forma de URL; resolvedor (loopback, privadas, CGNAT, link-local, ULA, mapeadas, mezcla buena+mala, IP literal); sin redirecciones; 200 obligatorio; 5 120/5 121 bytes; timeout; JSON estricto; campos; `client_secret`; métodos; intersección de grants; caché (vida, no-store, LRU, sin errores, copia caducada < 24 h y ≥ 24 h); cupo; `redirect_uri_matches` (loopback con y sin puerto, path/query/esquema distintos, `localhost.evil`, `127.0.0.2`). | FR-002, FR-004…FR-012, FR-016, FR-017 |
| `tests/test_oauth_cimd_flow.py` (nuevo) | Flujo completo con el documento de Claude Code y puerto aleatorio; errores sin redirección ni contraseña; `client_id` propio; CIMD desactivado; consentimiento; `iss` en éxito; refresh con documento válido, inválido (revoca) y temporal (503); dos dispositivos con el mismo `client_id`; sin refresh si el documento no lo permite; `oauth_cimd_rejected` sin contenido del documento. | FR-001, FR-003, FR-010, FR-013…FR-015, FR-018…FR-021, FR-023…FR-027 |
| `tests/test_oauth_security.py` | DCR: `iss` en la redirección; metadatos; recurso con `scopes_supported`; token con `resource` distinto rechazado; tokens y códigos con formato 1.0.12 siguen valiendo y el refresh añade `resource`; `client_id` DCR UUID. | FR-022, FR-025, FR-026, FR-028, FR-030, FR-031 |
| `tests/test_oauth_diagnostics.py` | Solo si algún test existente compara el diccionario de metadatos completo o el `Location` exacto: actualizarlo para incluir los campos nuevos. | FR-001, FR-025 |

### Lote B — Protocolo MCP

| Fichero:línea | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/mcp_server.py` (nuevo) | `class HermesMCPServer(MCPServer)` que sobrescribe `call_tool` (research R-B1) y `build_mcp_server(instructions) -> HermesMCPServer` con `name="hermes"`, `version=__version__`. Lista `_NOT_AN_ERROR` vacía salvo que la auditoría (R-B3) encuentre casos. | FR-039, FR-041 |
| `hermes/src/hermes/tools/_annotations.py:169-232` | `title_for(name)` con tabla de excepciones; `classify` añade `title`; `apply_tool_annotations` pone también `tool.title`. Ningún *hint* cambia. | FR-040, FR-043 |
| `hermes/src/hermes/middleware.py:24` y `:586` | Importar `HANDSHAKE_PROTOCOL_VERSIONS` y `MODERN_PROTOCOL_VERSIONS`; `self._supported = (*HANDSHAKE…, *MODERN…)`. | FR-042 |
| `hermes/src/hermes/middleware.py:300-313` (`OAuthBearerAuth.__init__`) | `challenge += ', scope="mcp"'`. | FR-029 |
| `tests/test_mcp_protocol.py` (nuevo) | `build_mcp_server` anuncia `version`; tool que devuelve `{"error": …}` → `is_error=True` con el mismo texto; vista previa con `confirmation_token` y resultado normal → no; excepción → `is_error` (comportamiento del SDK, control); test de auditoría que recorre las tools registradas con el fake de HA y no exige nada, solo documenta `_NOT_AN_ERROR`. | FR-039, FR-041 |
| `tests/test_tools_registration.py` | Todas las tools tienen `title` y `annotations.title` iguales, no vacíos y únicos; los *hints* son los de antes (instantánea de `classify` para todas las tools). | FR-040, FR-043 |
| `tests/test_middleware_connection.py` | `WWW-Authenticate` con `scope="mcp"`; `data.supported` igual a la tupla actual; el fuente de `middleware.py` no contiene `SUPPORTED_PROTOCOL_VERSIONS`. | FR-029, FR-042 |
| `tests/test_first_byte.py` (nuevo) | App Starlette con la misma pila de middlewares que `__main__` (o la función que la construya, si existe) y una tool de prueba que duerme 1 s; intervalo de *ping* del SDK y de `sse-starlette` parcheados a 0,2 s; con `MCP-Protocol-Version: 2025-11-25` y `2026-07-28`, el `send` registra `http.response.start` y un cuerpo `: ping` antes del resultado. | FR-036 |

### Lote C — Redacción del log

| Fichero:línea | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/logging_setup.py` (funciones nuevas) | `configure_network_redaction(enabled, public_hostname)`, `redact_network(text)` y helpers de clase y seudónimo (research R-C1). Estado inicial: desactivado (no cambia nada hasta que `setup_logging` lo active). | FR-045, FR-046, FR-049 |
| `hermes/src/hermes/logging_setup.py:186-207` (`setup_logging`) | Firma `setup_logging(level="info", *, redact_network=False, public_hostname="")`; processor `_redact_network_processor` tras `_redact_processor`; `logging.Filter` en los manejadores del logger raíz. | FR-045…FR-047 |
| `hermes/src/hermes/tools/addons.py:866-905` (`sv_get_addon_logs`) | Si `_es_hermes(slug)`, aplicar `redact_network` tras `redact_secrets`; docstring actualizado. | FR-048 |
| `tests/test_log_redact_network.py` (nuevo) | Hostname (mayúsculas, con puerto, en URL y en texto), `*.ts.net`, IPv4/IPv6 en campos, listas, diccionarios y texto; clases; loopback intacto; mismo seudónimo para la misma IP y distinto para otra; sal distinta entre configuraciones; falsos positivos (`2026.11.1`, `999.1.1.1`, `06:54:12`); logger `mcp.server.transport_security` con `Invalid Host header: 198.51.100.9`; desactivado → intacto y secretos aún redactados; `sv_get_addon_logs` de Hermes y de otro add-on. | FR-045…FR-049 |
| `tests/test_redact_secrets.py` | Sin cambios salvo que algún test fije la lista exacta de processors: actualizarlo. | FR-049 |

### Lote de integración (al final, tras fusionar A–C)

| Fichero:línea | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/__main__.py:575-588` | `setup_logging(config.log_level, redact_network=config.log_redact_network, public_hostname=config.public_hostname)`; registrar `config.adjustments` (`config_legacy_default_replaced` / `config_value_clamped`); si la redacción está desactivada, `log_network_redaction_disabled`. | FR-033…FR-035, FR-044, FR-049 |
| `hermes/src/hermes/__main__.py:218-222` | `OAuthServer(…, cimd_enabled=config.oauth_cimd_enabled)`. | FR-023 |
| `hermes/src/hermes/__main__.py:255-258` | `mcp = build_mcp_server(INSTRUCTIONS)`. | FR-039, FR-041 |
| `tests/test_main_wiring.py` (nuevo) | Con `load_config` y el arranque parcheados: `setup_logging` recibe la opción y el hostname; los ajustes se registran; `OAuthServer` recibe `cimd_enabled`; el servidor MCP es `HermesMCPServer` con `version`. | FR-023, FR-039, FR-044, FR-049 |
| `hermes/DOCS.md` | Sección «Límites y Claude Code»: 128 KiB por defecto y hasta 512 KiB, 220 s, temporizador de 60 s y cómo ampliarlo, opciones `oauth_cimd_enabled` y `log_redact_network`. | FR-037, FR-038 |
| `README.md`, `README.es.md` (tabla de opciones `:395-404` y problemas) | Valores y rangos efectivos, opciones nuevas, nota «si tenías valores guardados», CIMD/DCR en la sección de conexión, temporizador de Claude Code. Sincronizados. | FR-037, FR-038 |
| `hermes/CHANGELOG.md` | Entradas bajo `## [1.1.0] — AAAA-MM-DD` (crear la sección si falta, con el formato del principio XI; la fecha definitiva la fija la publicación). | FR-038, FR-052 |
| `docs/HOJA-DE-RUTA.md` | Marcar CIMD, `iss`, límites, protocolo y la redacción del log (C9/decisión 10) como hechos en 1.1.0; dejar pendiente la prueba manual del primer byte si no se hizo. | FR-052 |

## Riesgos

- **CIMD rompe a un cliente real**: interruptor `oauth_cimd_enabled: false` (FR-023) y DCR intacto.
- **`iss` mal formado**: un cliente que valide `iss` rechazaría todas las autorizaciones. Mitigación: un único constructor y test de igualdad exacta con `issuer`, también con `public_hostname` con puerto.
- **`isError` en una respuesta útil**: auditoría R-B3 y lista explícita de excepciones.
- **Recorte de opciones**: el log dice qué valor se aplicó; la documentación explica cómo pedir más hasta 512 KiB.
- **Proxy que almacena la respuesta**: no se puede arreglar desde Hermes; queda documentado (FR-037) y en la prueba manual.

## Seguimiento de complejidad

| Desviación | Por qué hace falta | Alternativa más simple descartada porque… |
|---|---|---|
| Opción `oauth_cimd_enabled` no pedida | Interruptor para volver a DCR sin bajar de versión si un cliente falla con CIMD | Bajar de versión pierde el resto de 1.1.0 |
| Subclase del servidor MCP (`mcp_server.py`) | `isError` en un solo sitio para ~367 respuestas | Tocar 37 ficheros de tools rompe el principio IX y es difícil de revisar |
| Módulo nuevo `cimd.py` | Aislar la superficie SSRF para probarla a fondo | Meterlo en `oauth.py` (1 600 líneas) lo haría ilegible |
