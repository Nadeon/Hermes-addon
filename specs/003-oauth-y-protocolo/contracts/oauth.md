# Contrato: endpoints OAuth de Hermes 1.1.0

`<base>` = `https://homeassistant.tailXXXX.ts.net` (con `:puerto` si
`public_hostname` lo lleva). Solo se listan los cambios respecto a 1.0.12.

## `GET /.well-known/oauth-authorization-server` (y `/…/mcp`)

```json
{
  "issuer": "<base>",
  "authorization_endpoint": "<base>/oauth/authorize",
  "token_endpoint": "<base>/oauth/token",
  "registration_endpoint": "<base>/oauth/register",
  "revocation_endpoint": "<base>/oauth/revoke",
  "response_types_supported": ["code"],
  "grant_types_supported": ["authorization_code", "refresh_token"],
  "code_challenge_methods_supported": ["S256"],
  "token_endpoint_auth_methods_supported": ["none"],
  "scopes_supported": ["mcp"],
  "client_id_metadata_document_supported": true,
  "authorization_response_iss_parameter_supported": true
}
```

- `client_id_metadata_document_supported` solo aparece con `oauth_cimd_enabled: true` (FR-001, FR-023).
- `authorization_response_iss_parameter_supported` aparece siempre (FR-026).

## `GET /.well-known/oauth-protected-resource` (y `/…/mcp`)

```json
{
  "resource": "<base>/mcp",
  "authorization_servers": ["<base>"],
  "bearer_methods_supported": ["header"],
  "scopes_supported": ["mcp"]
}
```

## 401 de `/mcp`

```text
WWW-Authenticate: Bearer realm="hermes", resource_metadata="<base>/.well-known/oauth-protected-resource/mcp", scope="mcp"
```

## `GET /oauth/authorize` con `client_id` CIMD

Parámetros como en 1.0.12. Si `client_id` empieza por `https://`:

| Situación | Respuesta |
|---|---|
| CIMD desactivado | 400 HTML: «Client ID Metadata Documents are disabled on this server» |
| URL con forma inválida, igual al propio `issuer`/recurso/host | 400 HTML: «client_id is not an acceptable metadata document URL» |
| dirección especial | 400 HTML: «client metadata document host is not allowed» |
| descarga fallida (temporal) | 400 HTML: «could not retrieve the client metadata document; try again later» |
| documento inválido o `client_id` distinto | 400 HTML: «client metadata document is invalid» |
| `redirect_uri` no casa | 400 HTML: «redirect_uri is not registered for this client» |
| todo correcto | 200 HTML: formulario con host del `client_id`, nombre declarado, destino y, si es loopback, aviso |

Ningún caso de error redirige ni pide contraseña (FR-014). Los mensajes van en
inglés, dentro de `_request_error_html`, como los de PKCE de 1.0.12.

## `POST /oauth/authorize`

- CIMD: repite la validación de cliente y `redirect_uri` **antes** de la contraseña (FR-013); un fallo devuelve la misma página 400 y no cuenta como intento de login.
- Éxito (DCR y CIMD):

```text
HTTP/1.1 302 Found
Location: <redirect_uri>?code=<code>&state=<state>&iss=https%3A%2F%2Fhomeassistant.tailXXXX.ts.net
```

`iss` va siempre, y con el valor exacto de `issuer` (FR-025). Hermes no
redirige ningún error (FR-027).

## `POST /oauth/token`

| Caso | Respuesta |
|---|---|
| `authorization_code` de cliente CIMD con `allow_refresh: false` | 200 sin `refresh_token` |
| `refresh_token` de cliente CIMD, documento válido (caché o descarga) | 200 como en 1.0.12 |
| ídem, documento inválido / 404 / `client_id` distinto | 401 `{"error": "invalid_client"}` y refresh tokens del cliente revocados |
| ídem, fallo temporal sin copia válida | 503 `{"error": "temporarily_unavailable"}` |
| DCR | sin cambios |

Los tokens emitidos llevan `resource` en disco; la respuesta JSON no cambia.

## Validación del bearer en `/mcp`

| Token en disco | Resultado |
|---|---|
| `resource` igual al canónico | aceptado |
| `resource` distinto | 401 (como un token desconocido) |
| sin `resource` (≤ 1.0.12) | aceptado hasta caducar |
