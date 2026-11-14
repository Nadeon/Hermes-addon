---

description: "Tareas de Hermes 1.1.0 (OAuth, protocolo, límites y log), agrupadas en lotes paralelos"
---

# Tareas: Hermes 1.1.0 — OAuth moderno, límites de Claude, protocolo MCP y log sin datos de red

**Entrada**: `specs/003-oauth-y-protocolo/` (spec.md, plan.md, research.md, data-model.md, contracts/oauth.md, contracts/mcp-y-log.md, quickstart.md).

**Base**: rama con 1.0.12 (spec 001) ya fusionada.

**Tests**: obligatorios. La constitución (principios VI y VII) exige un test de regresión por cambio, escrito **antes** de la implementación, y un **control negativo**: deshacer el cambio, ver caer el test y dejar el recuento por escrito.

**Organización**: por **lotes** que pueden implementar agentes distintos, cada uno en su worktree, sin tocar los mismos ficheros. Las tareas llevan la etiqueta de la historia de usuario de spec.md (US1…US7) y los FR que cubren.

## Formato: `[ID] [P?] [Historia] Descripción`

- **[P]**: se puede hacer en paralelo con otras tareas del mismo lote (ficheros distintos, sin dependencias pendientes). Las tareas de test que comparten fichero con otra anterior del lote no llevan la marca: se escriben en orden.
- **[USn]**: historia de usuario de spec.md.
- Rutas relativas a la raíz del repositorio.

## Reparto de ficheros por lote

Ningún fichero aparece en dos lotes. Si un lote necesita cambiar un fichero
que no es suyo, **no lo toca**: lo anota en su informe para el lote de
integración.

| Lote | Ficheros que le pertenecen (código y tests) |
|---|---|
| **Fase 0 — Configuración** (secuencial, antes de abrir los lotes) | `hermes/src/hermes/config.py`, `hermes/config.yaml`, `hermes/run.sh`, `tests/test_config_validation.py`, `tests/test_addon_manifest.py`, `tests/test_run_sh_options.py` |
| **A — OAuth** (CIMD, `iss`, audiencia, metadatos) | `hermes/src/hermes/cimd.py` (nuevo), `hermes/src/hermes/oauth.py`, `tests/test_cimd.py` (nuevo), `tests/test_oauth_cimd_flow.py` (nuevo), `tests/test_oauth_security.py`, `tests/test_oauth_diagnostics.py` |
| **B — Protocolo MCP** | `hermes/src/hermes/mcp_server.py` (nuevo), `hermes/src/hermes/middleware.py`, `hermes/src/hermes/tools/_annotations.py`, `tests/test_mcp_protocol.py` (nuevo), `tests/test_first_byte.py` (nuevo), `tests/test_middleware_connection.py`, `tests/test_tools_registration.py` |
| **C — Redacción del log** | `hermes/src/hermes/logging_setup.py`, `hermes/src/hermes/tools/addons.py` (solo `sv_get_addon_logs`), `tests/test_log_redact_network.py` (nuevo), `tests/test_redact_secrets.py` |
| **Integración** (al final, tras fusionar A–C) | `hermes/src/hermes/__main__.py`, `tests/test_main_wiring.py` (nuevo), `hermes/DOCS.md`, `README.md`, `README.es.md`, `hermes/CHANGELOG.md`, `docs/HOJA-DE-RUTA.md` |

Notas de reparto:

- `tests/test_addon_manifest.py` es de la fase 0; la integración solo lo **ejecuta**.
- El `scope` de `WWW-Authenticate` es de OAuth pero vive en `middleware.py`: lo hace el lote B.
- `OAuthServer(cimd_enabled=…)`, `setup_logging(redact_network=…, public_hostname=…)` y `build_mcp_server(…)` se definen en A, C y B con valores por defecto que funcionan sin cableado; solo la integración edita `__main__.py`.
- `tools/wait_for_event.py`, `tools/guide.py`, el resto de `tools/*.py`, `.github/`, `hermes/Dockerfile` y `hermes/requirements.txt` **no los toca nadie** en esta spec.
- Los ejemplos de los tests usan `homeassistant.tailXXXX.ts.net`, `<slug>` e IPs de documentación (`192.0.2.x`, `198.51.100.x`, `203.0.113.x`); los rangos especiales se prueban con direcciones de ejemplo de cada rango (`10.0.0.5`, `100.64.0.7`, `169.254.1.1`, `fd00::1`, `::ffff:10.0.0.5`).

---

## Fase 1: Preparación

**Objetivo**: entorno de pruebas y línea base sobre 1.0.12.

- [X] T001 Crear `.venv` con `hermes/requirements.txt` y `pytest pytest-asyncio aioresponses httpx` (quickstart.md) y ejecutar `.venv/bin/pytest`; anotar el número de tests que pasan como línea base
- [X] T002 Comprobar que el árbol está limpio, sobre la rama indicada por el mantenedor y con 1.0.12 fusionada (`HAConnectionError.code` y `hermes/src/hermes/ha_version.py` presentes); cada lote crea su worktree desde el commit con la fase 0 fusionada

---

## Fase 2: Fase 0 — Configuración (secuencial — BLOQUEA a todos los lotes)

**Objetivo**: valores por defecto y máximos efectivos de los límites (US4, US5) y las dos opciones nuevas, para que ningún lote toque la configuración.

**Prueba independiente**: `.venv/bin/pytest tests/test_config_validation.py tests/test_addon_manifest.py tests/test_run_sh_options.py`.

- [X] T003 [US4] Tests en `tests/test_config_validation.py`: sin `HERMES_RESPONSE_MAX_BYTES` → 131 072; `1048576` → 131 072 y `adjustments` con `reason: "legacy_default"`; `300000` → 300 000 sin ajuste; `4000000` → 524 288 con `reason: "above_cap"`; `524288` y `10240` se respetan (FR-032, FR-033, FR-034)
- [X] T004 [US5] Tests en `tests/test_config_validation.py`: `HERMES_WAIT_EVENT_MAX_SECONDS=300` → 220 con ajuste `above_cap`; `220`, `90` y `10` se respetan; por defecto 90. Más: `oauth_cimd_enabled` y `log_redact_network` valen `True` por defecto y `False` con `"false"` en el entorno (FR-035, FR-023, FR-044)
- [X] T005 [P] [US4] Tests en `tests/test_addon_manifest.py`: `options.response_max_bytes == 131072` y coincide con `config.py`; el esquema de `response_max_bytes` sigue admitiendo 1 048 576 y el de `wait_for_event_max_seconds` 300 (control del supuesto S-03); `oauth_cimd_enabled` y `log_redact_network` están en `schema` como `bool?` y en `options` como `true` (FR-032, FR-023, FR-044)
- [X] T006 [P] [US4] Tests en `tests/test_run_sh_options.py`: `run.sh` usa 131072 como valor por defecto de `response_max_bytes` y exporta `HERMES_OAUTH_CIMD_ENABLED` y `HERMES_LOG_REDACT_NETWORK` con `true` por defecto (FR-032, FR-023, FR-044)
- [X] T007 Implementar en `hermes/src/hermes/config.py` las constantes, el valor por defecto nuevo, los recortes y `adjustments` en `load_config`, y los campos `oauth_cimd_enabled` y `log_redact_network`, con el comentario del porqué (Supervisor valida opciones guardadas; la interfaz guarda todas) (plan, fase 0; FR-032…FR-035, FR-023, FR-044)
- [X] T008 Cambiar `options.response_max_bytes` a 131072 y añadir las dos opciones en `hermes/config.yaml` (esquema de los límites sin cambios, con comentario); en `hermes/run.sh`, valor por defecto 131072 y las dos exportaciones nuevas (FR-032, FR-023, FR-044)
- [X] T009 Control negativo de la fase 0: (1) quitar el recorte de `response_max_bytes`, (2) quitar la sustitución de 1 048 576, (3) quitar el recorte de `wait_for_event_max_seconds`, (4) restaurar 1048576 en `config.yaml` y `run.sh`; tras cada uno, comprobar qué tests de T003–T006 caen; restaurar y anotar «con la guarda quitada caen N tests»
- [X] T010 Ejecutar la suite completa; grep de privacidad del diff (quickstart.md); commit de la fase 0 con los recuentos

**Punto de control**: fase 0 fusionada; se abren los lotes A, B y C en paralelo.

---

## Fase 3: Lote A — OAuth (US1, US2, US3)

**Objetivo**: CIMD seguro con DCR de respaldo, `iss`, metadatos del recurso con `scopes_supported` y audiencia en los tokens, sin romper a nadie.

**Prueba independiente**: `.venv/bin/pytest tests/test_cimd.py tests/test_oauth_cimd_flow.py tests/test_oauth_security.py tests/test_oauth_diagnostics.py`.

### Forma de la URL y descarga segura (US3)

- [ ] T011 [P] [US3] Tests en `tests/test_cimd.py` para `parse_client_id_url`: acepta `https://claude.ai/oauth/claude-code-client-metadata` y `https://example.com:443/c`; rechaza `http://`, sin path, path `/`, `#frag`, `?q=1`, `user@host`, segmentos `.`/`..` (también codificados `%2e`), puerto 8443, más de 2 048 caracteres (FR-002)
- [ ] T012 [US3] Tests en `tests/test_cimd.py` para el resolvedor seguro con `getaddrinfo` falso: rechaza `127.0.0.1`, `10.0.0.5`, `172.16.0.1`, `192.168.1.1`, `100.64.0.7`, `169.254.1.1`, `0.0.0.0`, `224.0.0.1`, `::1`, `fd00::1`, `fe80::1`, `::ffff:10.0.0.5`, `2002:0a00:0005::1` (6to4 de una privada) y una respuesta con una pública y una privada; acepta una lista solo de públicas y devuelve esas mismas direcciones con `hostname` para SNI; una IP literal especial en la URL se rechaza sin resolver; 0 conexiones abiertas en los rechazos (FR-006)
- [ ] T013 [US3] Tests en `tests/test_cimd.py` para la descarga (con `aioresponses`): envía `Accept: application/json`; 301/302/307 → `CimdInvalidError("redirect")` sin pedir la URL de destino; 404 → inválido; 500/503/429 → temporal; cuerpo de 5 120 bytes se acepta y de 5 121 se rechaza (`too_large`); timeout total de 5 s → temporal; con 4 descargas en vuelo la quinta espera, y la descarga 31 en un minuto → temporal `rate_limited` sin conexión (FR-004, FR-005, FR-007)
- [ ] T014 [US3] Implementar en `hermes/src/hermes/cimd.py` `parse_client_id_url`, `_SafeResolver`, la sesión `aiohttp` (`TCPConnector(resolver=…, use_dns_cache=False)`, `trust_env=False`, `allow_redirects=False`, `ClientTimeout(total=5)`), la lectura acotada y el cupo (semáforo de 4, 30/min), con comentarios del porqué (SSRF, rebinding, borrador CIMD §6) (research R-A2, R-A3, R-A5)
- [ ] T015 [US3] Control negativo: (1) devolver todas las direcciones sin filtrar en el resolvedor, (2) `allow_redirects=True`, (3) quitar el tope de bytes, (4) quitar el cupo, (5) aceptar `http://` en `parse_client_id_url`; tras cada uno, comprobar que caen los tests correspondientes de T011–T013; restaurar y anotar

### Validación del documento, caché y `redirect_uri` (US1)

- [ ] T016 [US1] Tests en `tests/test_cimd.py` para `validate_document`: el documento real de Claude Code (data-model.md) es válido con `allow_refresh=True`; inválidos: `client_id` con barra final o en mayúsculas, sin `client_name`, `client_name` de 201 caracteres, `redirect_uris` vacío, con fragmento, relativo, `javascript:`, 11 entradas, `client_secret` presente, `token_endpoint_auth_method: "client_secret_basic"`, `grant_types: ["client_credentials"]`, `response_types: ["token"]`, `NaN`, BOM, no UTF-8, raíz lista, claves duplicadas; `grant_types` ausente → válido con `allow_refresh=False` (FR-008, FR-009, FR-010)
- [ ] T017 [US1] Tests en `tests/test_cimd.py` para la caché y `redirect_uri_matches`: segunda resolución dentro de la vida no descarga; `max-age=60` → 300 s; `max-age=999999` → 86 400 s; sin `max-age` → 3 600 s; `no-store` → 300 s; un 500 tras caducar devuelve la copia si tiene < 24 h y error temporal si tiene ≥ 24 h; un 404 o un documento inválido tras caducar borra la copia y lanza `CimdInvalidError`; un error nunca queda en caché; la entrada 65 expulsa la más antigua. `redirect_uri_matches`: `http://localhost/callback` casa con `http://localhost:41000/callback` y con `http://localhost/callback`; `http://127.0.0.1/callback` con `http://127.0.0.1:53127/callback`; `http://[::1]/cb` con `http://[::1]:9/cb`; no casan path distinto, query distinta, `https://localhost:1/callback`, `http://localhost.evil.example:1/callback`, `http://127.0.0.2:1/callback`, `localhost` contra `127.0.0.1`; fuera de loopback, igualdad exacta (FR-011, FR-012, FR-016, FR-017)
- [ ] T018 [US1] Implementar en `hermes/src/hermes/cimd.py` `validate_document`, `CimdResolver.resolve` con la caché LRU y las reglas de vida y de copia caducada, y `redirect_uri_matches` (research R-A3, R-A4; data-model.md)
- [ ] T019 [US1] Control negativo: (1) comparar `client_id` sin distinguir mayúsculas, (2) cachear errores, (3) ignorar el puerto también fuera de loopback, (4) comparar loopback con igualdad exacta (el caso de Claude Code); comprobar que caen los tests de T016–T017; restaurar y anotar

### Flujo de autorización y tokens con CIMD (US1)

- [ ] T020 [P] [US1] Tests en `tests/test_oauth_cimd_flow.py` (con `CimdResolver` simulado o `aioresponses` y el documento de Claude Code): metadatos con `client_id_metadata_document_supported: true` y sin él con `cimd_enabled=False`; GET `/oauth/authorize` con `redirect_uri=http://localhost:41000/callback` → 200 con `claude.ai` como identidad, «Claude Code» como nombre declarado, destino `http://localhost` y aviso de loopback; POST con la contraseña → 302 con `code`, `state` e `iss`; canje del código con PKCE → tokens; `client_id` `https://` con documento caído, inválido, `redirect_uri` no registrado o CIMD desactivado → 400 HTML sin `Location`, sin formulario de contraseña y sin contar como fallo de login; `client_id` igual al `issuer`, al recurso o con el host propio → 400; cada rechazo registra `oauth_cimd_rejected` con motivo y host y sin el cuerpo del documento (FR-001, FR-003, FR-013, FR-014, FR-021, FR-023, FR-024)
- [ ] T021 [US1] Tests en `tests/test_oauth_cimd_flow.py` para tokens: documento sin `refresh_token` en `grant_types` → canje sin `refresh_token`; refresh con documento válido → 200; refresh con documento que ahora da 404 o `client_id` distinto → 401 `invalid_client` y los refresh del cliente revocados; refresh con fallo temporal sin copia → 503 `temporarily_unavailable`; autorizar dos veces el mismo `client_id` CIMD deja vivas las dos sesiones, y el tope global de sesiones se sigue aplicando (FR-010, FR-015, FR-018, FR-019, FR-020)
- [ ] T022 [US1] Implementar en `hermes/src/hermes/oauth.py`: `cimd_enabled` en `__init__`, metadatos CIMD, `_check_cimd_client`, CIMD en `authorize_get` y `authorize_post` (antes del throttle y de la contraseña), `client_kind` y `allow_refresh` en el código, y el bloque de consentimiento CIMD de `_login_html` (todo con `html.escape`) (plan, lote A; research R-A6, R-A9)
- [ ] T023 [US1] Implementar en `hermes/src/hermes/oauth.py`: sin refresh si `allow_refresh` es falso; `resolve` en el refresh de clientes CIMD con 401/503; `_revoke_client_refresh_tokens`; `_revoke_previous_sessions` sin filtro por `client_id` para `https://…` (research R-A7)
- [ ] T024 [US1] Control negativo: (1) volver a la comparación exacta de `:833` para CIMD, (2) redirigir con `error=` en vez de mostrar la página, (3) emitir refresh siempre, (4) quitar la revocación por documento inválido, (5) filtrar sesiones por `client_id` también en CIMD; comprobar que caen los tests de T020–T021; restaurar y anotar

### `iss` (US2)

- [ ] T025 [P] [US2] Tests en `tests/test_oauth_security.py`: la redirección de éxito de un cliente DCR lleva `iss` igual, carácter a carácter, al `issuer` de los metadatos (también con `public_hostname` `homeassistant.tailXXXX.ts.net:8443`); un `redirect_uri` con query propia conserva su query y añade `iss` una sola vez; los metadatos anuncian `authorization_response_iss_parameter_supported: true`; PKCE ausente, `resource` ajeno, cliente desconocido y `redirect_uri` no registrado no producen ninguna respuesta 3xx (FR-025, FR-026, FR-027)
- [ ] T026 [US2] Implementar `_redirect_to_client` en `hermes/src/hermes/oauth.py` como único constructor de redirecciones al cliente, usarlo en `authorize_post` y añadir el campo a los metadatos (research R-A8)
- [ ] T027 [US2] Control negativo: (1) construir la redirección sin `iss`, (2) usar `self._base_url + "/"` como `iss`, (3) quitar el campo de los metadatos; comprobar que caen los tests de T025 (y el `iss` de T020); restaurar y anotar

### Recurso protegido, audiencia y compatibilidad (US2)

- [ ] T028 [US2] Tests en `tests/test_oauth_security.py`: el recurso protegido anuncia `scopes_supported: ["mcp"]`; los tokens emitidos llevan `resource` canónico en disco; `validate_token` rechaza un access token con `resource` `https://otro.example/mcp`; un access token y un refresh token escritos con el formato de 1.0.12 (sin `resource`) se aceptan, y el refresh emite tokens con `resource`; un código vivo de 1.0.12 (sin `client_kind`) se canjea como DCR con refresh; `register_client` sigue devolviendo un UUID y comparando el `redirect_uri` con igualdad exacta (FR-022, FR-028, FR-030, FR-031)
- [ ] T029 [US2] Implementar en `hermes/src/hermes/oauth.py`: `scopes_supported` en `protected_resource_metadata`; `resource` en access y refresh de `_token_auth_code` y `_issue_from_refresh` (heredado o canónico); comprobación en `validate_token` que acepta la ausencia (plan, lote A)
- [ ] T030 [US2] Control negativo: (1) no comprobar `resource` en `validate_token`, (2) rechazar tokens sin `resource`, (3) quitar `scopes_supported`; comprobar qué tests de T028 caen en cada caso (el (2) debe romper la compatibilidad); restaurar y anotar
- [ ] T031 [US2] (FR-001, FR-025) Revisar `tests/test_oauth_diagnostics.py` y `tests/test_oauth_security.py` por comparaciones exactas de metadatos o de `Location` que fallen con los campos nuevos y actualizarlas sin perder lo que comprueban

### Cierre del lote A

- [ ] T032 Ejecutar los tests del lote y la suite completa; grep de privacidad del diff (la URL pública del documento de Claude Code es la única URL real permitida); commit del lote con los recuentos de control negativo

**Punto de control**: US1, US2 y US3 completas.

---

## Fase 4: Lote B — Protocolo MCP (US5, US7)

**Objetivo**: `version`, `title`, `isError`, versiones de protocolo sin alias deprecado, `scope` en el 401 y el primer byte fijado por un test.

**Prueba independiente**: `.venv/bin/pytest tests/test_mcp_protocol.py tests/test_first_byte.py tests/test_middleware_connection.py tests/test_tools_registration.py`.

### `version` e `isError` (US7)

- [X] T033 [P] [US7] Tests en `tests/test_mcp_protocol.py`: `build_mcp_server("…")` tiene `name == "hermes"` y `version == hermes.__version__`; con una tool de prueba registrada en ese servidor, `call_tool` de una que devuelve `{"error": "not_found", "entity_id": "light.x"}` da `is_error=True` y el mismo texto JSON que sin la subclase; `{"preview": …, "confirmation_token": "t"}` y `{"ok": true}` no llevan `is_error`; una excepción sigue dando `is_error=True` (control del SDK); una respuesta con `error: null` o `error` anidado no se marca (FR-039, FR-041)
- [X] T034 [US7] Crear `hermes/src/hermes/mcp_server.py` con `HermesMCPServer.call_tool` y `build_mcp_server`, con comentario del porqué (spec MCP: errores de ejecución en el resultado; un solo sitio para ~367 respuestas) (research R-B1)
- [X] T035 [US7] Auditoría R-B3: buscar en `hermes/src/hermes/tools/` los `return` con `"error"` en el nivel superior junto a datos de éxito; si hay alguno, añadirlo a `_NOT_AN_ERROR` en `mcp_server.py` con su motivo y un test en `tests/test_mcp_protocol.py`; si no, dejarlo escrito en el informe del lote
- [X] T036 [US7] Control negativo: (1) devolver el resultado del padre sin tocar, (2) marcar también las vistas previas, (3) quitar `version=`; comprobar que caen los tests de T033; restaurar y anotar

### `title` (US7)

- [X] T037 [P] [US7] Tests en `tests/test_tools_registration.py`: tras registrar todas las tools, cada una tiene `title` no vacío, igual a `annotations.title`, y todos son distintos; ejemplos de contracts/mcp-y-log.md; los cuatro *hints* de cada tool son iguales a los de una instantánea tomada antes del cambio (FR-040, FR-043)
- [X] T038 [US7] Implementar `title_for` y su tabla de excepciones en `hermes/src/hermes/tools/_annotations.py`; `classify` añade `title` y `apply_tool_annotations` pone `tool.title` (research R-B2)
- [X] T039 [US7] Control negativo: (1) no poner `tool.title`, (2) quitar el sufijo de área (provoca duplicados si los hay; si no, quitar la tabla de excepciones y comprobar el ejemplo de HACS); comprobar que caen los tests de T037; restaurar y anotar

### Versiones de protocolo y `WWW-Authenticate` (US7)

- [X] T040 [P] [US7] Tests en `tests/test_middleware_connection.py`: el 401 de `/mcp` lleva `WWW-Authenticate` con `realm`, `resource_metadata` y `scope="mcp"`; `data.supported` del -32022 es igual a `(*HANDSHAKE_PROTOCOL_VERSIONS, *MODERN_PROTOCOL_VERSIONS)`; el fuente de `hermes/src/hermes/middleware.py` no contiene `SUPPORTED_PROTOCOL_VERSIONS` (FR-029, FR-042)
- [X] T041 [US7] Implementar en `hermes/src/hermes/middleware.py` la importación nueva y `scope="mcp"` en el *challenge* (plan, lote B)
- [X] T042 [US7] Control negativo: restaurar el alias y quitar `scope`; comprobar que caen los tests de T040; restaurar y anotar

### Primer byte (US5)

- [X] T043 [P] [US5] Test en `tests/test_first_byte.py`: app Starlette con la pila de middlewares de `__main__` en su orden (`SecurityHeadersMiddleware`, `RateLimitPreAuth`, `OAuthBearerAuth` con un validador falso, `BodySizeLimitMiddleware`, `RateLimitPostAuth`, `RequestIdMiddleware`, `LoggingMiddleware`, `McpProtocolVersionMiddleware`) y `build_mcp_server` montado con `stateless_http=True`; una tool de prueba que duerme 1 s; `sse_starlette.EventSourceResponse.DEFAULT_PING_INTERVAL` y `mcp.server._streamable_http_modern._SSE_PING_INTERVAL` parcheados a 0,2 s; para `MCP-Protocol-Version: 2025-11-25` (con `initialize` previo si el camino lo exige) y `2026-07-28`, un `send` que anota tiempos registra `http.response.start` con `text/event-stream` y un cuerpo que empieza por `:` antes de 0,5 s, y el resultado al final (FR-036)
- [X] T044 [US5] Si T043 falla por algún middleware de Hermes, corregir ese middleware en `hermes/src/hermes/middleware.py` para que no almacene respuestas correctas; si pasa sin cambios (lo esperado según research R-B5), dejarlo escrito en el informe del lote
- [X] T045 [US5] Control negativo de T043: montar la app del test con `json_response=True` o insertar un middleware que almacene el cuerpo, y comprobar que el test falla; anotar

### Cierre del lote B

- [X] T046 Ejecutar los tests del lote y la suite completa; grep de privacidad del diff; commit del lote con los recuentos de control negativo

**Punto de control**: US7 completa y la parte de código de US5.

---

## Fase 5: Lote C — Redacción del log (US6)

**Objetivo**: ni el hostname ni IPs que no sean de loopback en el log por defecto, con opción para desactivarlo.

**Prueba independiente**: `.venv/bin/pytest tests/test_log_redact_network.py tests/test_redact_secrets.py`.

- [X] T047 [P] [US6] Tests en `tests/test_log_redact_network.py` para `redact_network` tras `configure_network_redaction(True, "homeassistant.tailXXXX.ts.net")`: el hostname en minúsculas, mayúsculas, con `:8443` y dentro de una URL → `<public_hostname>`; `otro.tailYYYY.ts.net` → `<redacted>.ts.net`; `203.0.113.7` → `<ip:other:…>` (documentación), `1.1.1.1` (resolvedor DNS público conocido; único caso de IP pública real permitido en tests) → `<ip:public:…>`, `172.30.32.2` → `private`, `100.64.0.7` → `tailnet`, `10.0.0.5` → `private`, `169.254.1.1` → `link-local`, `fd7a:115c:a1e0::1` → `tailnet`, `[2001:db8::1]:443` redactada; `127.0.0.1` y `::1` intactos; misma IP → mismo seudónimo; otra IP → otro; tras reconfigurar, otro seudónimo; `2026.11.1`, `999.1.1.1`, `06:54:12` y `v1.2.3.4-beta` (si no es IP válida) intactos (FR-045, FR-046)
- [X] T048 [US6] Tests en `tests/test_log_redact_network.py` para la integración en el log: tras `setup_logging("info", redact_network=True, public_hostname=…)`, un evento con `public_hostname`, `src_ip`, `trusted_proxy_ips` (lista), un `dict` anidado y `error` con texto libre sale redactado; `logging.getLogger("mcp.server.transport_security").warning("Invalid Host header: %s", "198.51.100.9")` sale redactado; con `redact_network=False` todo sale intacto salvo los secretos (`password=…`, `Bearer …`), que se siguen redactando (FR-045…FR-047, FR-049)
- [X] T049 [US6] Tests en `tests/test_log_redact_network.py` para `sv_get_addon_logs` con el Supervisor simulado: slug de Hermes (`local_hermes` y `<hash>_hermes`) con la redacción activa → sin hostname ni IPs; otro slug → solo redacción de secretos, como en 1.0.12; redacción desactivada → sin cambios (FR-048)
- [X] T050 [US6] Implementar en `hermes/src/hermes/logging_setup.py` `configure_network_redaction`, `redact_network`, `_redact_network_processor`, el `logging.Filter` y la firma nueva de `setup_logging`, con comentarios del porqué (issues públicos, decisión 10, avisos del SDK por `logging` estándar) (research R-C1, R-C2, R-C3)
- [X] T051 [US6] Aplicar `redact_network` en `sv_get_addon_logs` de `hermes/src/hermes/tools/addons.py` cuando `_es_hermes(slug)`, y actualizar su docstring (FR-048)
- [X] T052 [US6] Control negativo: (1) quitar el processor, (2) quitar el filtro de `logging`, (3) no excluir loopback, (4) hash sin sal (comprobar el test de reconfiguración), (5) quitar la llamada en `sv_get_addon_logs`; comprobar que caen los tests de T047–T049; restaurar y anotar
- [X] T053 Ejecutar los tests del lote y la suite completa; grep de privacidad del diff; commit del lote con los recuentos

**Punto de control**: US6 completa.

---

## Fase 6: Integración (tras fusionar A, B y C)

**Objetivo**: cablear las piezas en el arranque y documentar los cambios (US4, US5, US6, FR-037, FR-038, FR-052).

**Prueba independiente**: `.venv/bin/pytest tests/test_main_wiring.py tests/test_addon_manifest.py` y la suite completa.

- [ ] T054 [P] Tests en `tests/test_main_wiring.py`, con la configuración y los servicios externos parcheados: `setup_logging` recibe `redact_network` y `public_hostname` de la configuración; cada entrada de `config.adjustments` produce `config_legacy_default_replaced` o `config_value_clamped`; con `log_redact_network: false` se registra `log_network_redaction_disabled`; `OAuthServer` recibe `cimd_enabled`; el servidor MCP es `HermesMCPServer` con `version` igual a `__version__` (FR-023, FR-033…FR-035, FR-039, FR-044, FR-049)
- [ ] T055 Cablear en `hermes/src/hermes/__main__.py`: `setup_logging(…)` con las opciones, registro de `adjustments` y del aviso, `OAuthServer(…, cimd_enabled=…)` y `build_mcp_server(INSTRUCTIONS)` (plan, integración; research R-I1)
- [ ] T056 Control negativo: deshacer cada cableado de T055 y comprobar que cae el test correspondiente de T054; restaurar y anotar
- [ ] T057 [P] `hermes/DOCS.md`: sección «Límites y Claude Code» (128 KiB por defecto y hasta 512 KiB, 1 048 576 guardado pasa a 131 072, máximo de espera 220 s, temporizador de 60 s hasta el primer byte, *pings* cada 15 s y cómo ampliarlo en Claude Code) y las opciones `oauth_cimd_enabled` y `log_redact_network` (FR-037, FR-038)
- [ ] T058 [P] `README.md` y `README.es.md`, sincronizados: tabla de opciones (`response_max_bytes` 131072 con máximo efectivo 524288, `wait_for_event_max_seconds` 10–220, opciones nuevas), nota «si tenías valores guardados», CIMD/DCR en la conexión de Claude, temporizador de Claude Code en problemas (FR-037, FR-038)
- [ ] T059 [P] `hermes/CHANGELOG.md`: entradas bajo `## [1.1.0] — AAAA-MM-DD` (crear la sección si falta, con el formato del principio XI) para CIMD, `iss`, metadatos, audiencia, límites, protocolo y redacción del log, con la migración de valores (FR-038, FR-052)
- [ ] T060 [P] `docs/HOJA-DE-RUTA.md`: marcar como hechos en 1.1.0 CIMD, `iss`, límites, protocolo y la redacción de red del log (C9/decisión 10); anotar como pendiente la prueba manual del primer byte si no se hizo (FR-052)
- [ ] T061 Pruebas manuales de quickstart.md en una instalación de pruebas (Claude Code con CIMD, primer byte con 90 s, claude.ai, actualización con conector autorizado, log); anotar el resultado y, si Claude Code corta a los 60 s, completar DOCS.md y la hoja de ruta (FR-036, FR-037)
- [ ] T062 Suite completa; grep de privacidad e identificadores de modelos de IA sobre el diff entero de la spec; resumen de los recuentos de control negativo de todos los lotes en el commit o el PR; commit de integración (FR-050, FR-051)

---

## Dependencias y orden de ejecución

- **Fase 1** → **Fase 2 (fase 0)** → **Lotes A, B y C en paralelo** → **Integración**.
- Dentro de cada bloque: test → implementación → control negativo.
- A, B y C no comparten ficheros; ninguno depende del código de otro (los valores por defecto de sus firmas nuevas funcionan sin cableado).
- T043 usa `build_mcp_server` (T034) del mismo lote.
- T061 necesita una instalación de pruebas; si no la hay, se deja pendiente en la hoja de ruta y no bloquea el commit.

### Ejemplo de ejecución en paralelo

```text
# Tras la fase 0:
Agente A: T011–T032 (ficheros del lote A)
Agente B: T033–T046 (ficheros del lote B)
Agente C: T047–T053 (ficheros del lote C)
# Después, un agente de integración: T054–T062
```

---

## Estrategia de implementación

### Primero lo que protege

1. Fases 1 y 2.
2. Lote A (US1, US2, US3, todas P1) y, en paralelo, B y C.
3. Validar cada lote con su prueba independiente.

### Entrega incremental

Cada lote se puede fusionar en cuanto pasa su prueba independiente y la suite
completa. Nada se publica hasta la integración y la publicación de 1.1.0.

---

## Trazabilidad FR → tareas

| FR | Origen | Lote | Test | Implementación | Control negativo |
|---|---|---|---|---|---|
| FR-001 | R-CIMD-1 | A | T020, T031 | T022 | T024 |
| FR-002 | R-CIMD-2 | A | T011 | T014 | T015 |
| FR-003 | R-CIMD-9 | A | T020 | T022 | T024 |
| FR-004, FR-005 | R-CIMD-2, R-CIMD-3 | A | T013 | T014 | T015 |
| FR-006 | R-CIMD-4 | A | T012 | T014 | T015 |
| FR-007 | R-CIMD-4 | A | T013 | T014 | T015 |
| FR-008, FR-009 | R-CIMD-5 | A | T016 | T018 | T019 |
| FR-010 | R-CIMD-5 | A | T016, T021 | T018, T023 | T019, T024 |
| FR-011, FR-012 | R-CIMD-6 | A | T017 | T018 | T019 |
| FR-013, FR-014 | R-CIMD-6, R-CIMD-7 | A | T020 | T022 | T024 |
| FR-015 | R-CIMD-7 | A | T021 | T023 | T024 |
| FR-016, FR-017 | R-CIMD-8 | A | T017 | T018 | T019 |
| FR-018, FR-019 | R-CIMD-7, R-CIMD-8 | A | T021 | T023 | T024 |
| FR-020 | R-CIMD-11 | A | T021 | T023 | T024 |
| FR-021 | R-CIMD-10 | A | T020 | T022 | T024 |
| FR-022 | R-CIMD-11 | A | T028 | — (sin cambio de código) | T030 |
| FR-023 | S-14 | Fase 0, A, Integración | T004–T006, T020, T054 | T007, T008, T022, T055 | T009, T024, T056 |
| FR-024 | R-CIMD-7 | A | T020 | T022 | T024 |
| FR-025, FR-026, FR-027 | R-ISS-1, R-ISS-2 | A | T025, T020, T031 | T026 | T027 |
| FR-028 | R-SCOPE-1 | A | T028 | T029 | T030 |
| FR-029 | R-SCOPE-2 | B | T040 | T041 | T042 |
| FR-030, FR-031 | R-AUD-1, decisión | A | T028 | T029 | T030 |
| FR-032 | R-LIM-1 | Fase 0 | T003, T005, T006 | T007, T008 | T009 |
| FR-033, FR-034 | R-LIM-1, R-LIM-2 | Fase 0, Integración | T003, T054 | T007, T055 | T009, T056 |
| FR-035 | R-LIM-3 | Fase 0, Integración | T004, T054 | T007, T055 | T009, T056 |
| FR-036 | R-LIM-4 | B | T043 | T044 | T045 |
| FR-037 | R-LIM-4 | Integración | — (documentación; prueba manual T061) | T057, T058, T061 | — |
| FR-038 | R-LIM-1, R-LIM-3 | Integración | — (documentación) | T057, T058, T059 | — |
| FR-039 | R-SRV-1 | B, Integración | T033, T054 | T034, T055 | T036, T056 |
| FR-040 | R-SRV-4 | B | T037 | T038 | T039 |
| FR-041 | R-SRV-3 | B | T033 | T034, T035 | T036 |
| FR-042 | R-SRV-2 | B | T040 | T041 | T042 |
| FR-043 | Principio V | B | T037 | T038 | T039 |
| FR-044 | Decisión 10 | Fase 0, Integración | T004–T006, T054 | T007, T008, T055 | T009, T056 |
| FR-045, FR-046 | Decisión 10, doc. 11 §8 | C | T047, T048 | T050 | T052 |
| FR-047 | Decisión 10, doc. 11 §8 | C | T048 | T050 | T052 |
| FR-048 | Doc. 11 §8 | C | T049 | T051 | T052 |
| FR-049 | Decisión 10 | C, Integración | T048, T054 | T050, T055 | T052, T056 |
| FR-050 | VI, VII | Todos | — | todas las tareas de control negativo | T062 |
| FR-051 | VIII | Todos | — | T010, T032, T046, T053, T062 | — |
| FR-052 | XI | Integración | — (documentación) | T059, T060 | — |

## Notas

- [P] = ficheros distintos y sin dependencias pendientes.
- Cada lote deja en su commit «con la guarda quitada caen N tests» por cambio.
- Ningún lote empuja ni fusiona a `main`; eso lo decide el mantenedor.
- La versión no se sube en esta spec (FR-052): la fija la publicación de 1.1.0 junto con las demás specs de esa versión.
