# Contrato: superficie MCP y log de Hermes 1.1.0

## `serverInfo`

```json
{"name": "hermes", "version": "<__version__>"}
```

`version` deja de ser `""` (FR-039).

## `tools/list`

Cada tool añade `title` y `annotations.title` con el mismo valor (FR-040). El
resto no cambia (FR-043).

| `name` | `title` |
|---|---|
| `ha_get_state` | `Get state (Home Assistant)` |
| `ha_hacs_list_repositories` | `HACS list repositories (Home Assistant)` |
| `ha_save_lovelace_dashboard` | `Save Lovelace dashboard (Home Assistant)` |
| `fs_read_file` | `Read file (files)` |
| `sv_restart_core` | `Restart core (Supervisor)` |
| `ping` | `Ping` |
| `hermes_guide` | `Hermes guide` |

Los títulos exactos los fija la tabla de `tools/_annotations.py`; el test exige
que no estén vacíos y que sean únicos.

## `tools/call`

| Valor devuelto por la tool | Resultado |
|---|---|
| objeto sin clave `error` | `isError` ausente/`false` (como hoy) |
| objeto con `error` no nulo en el nivel superior | `isError: true`, mismo texto JSON (FR-041) |
| objeto con `confirmation_token` (vista previa) | `isError` ausente/`false` |
| excepción | `isError: true` (lo hace el SDK, como hoy) |

## Transporte

- POST `/mcp` con `Accept: application/json, text/event-stream`: si la tool
  tarda, la respuesta empieza con cabeceras `text/event-stream` y comentarios
  `: ping` cada 15 s hasta el resultado (FR-036).
- `MCP-Protocol-Version` desconocida: -32022 con `data.supported` igual a
  `HANDSHAKE_PROTOCOL_VERSIONS + MODERN_PROTOCOL_VERSIONS` (FR-042).

## Log (con `log_redact_network: true`)

Antes (1.0.12):

```json
{"event": "hermes_started", "public_hostname": "homeassistant.tailXXXX.ts.net", "tailscale_ip": "100.64.12.34", "supervisor_url": "http://172.30.32.2", "trusted_proxy_ips": ["127.0.0.1"]}
{"event": "http_request", "status": 401, "src_ip": "203.0.113.7"}
Invalid Host header: 198.51.100.9
```

Después (1.1.0):

```json
{"event": "hermes_started", "public_hostname": "<public_hostname>", "tailscale_ip": "<ip:tailnet:3fa2b1c9>", "supervisor_url": "http://<ip:private:0b7e44d1>", "trusted_proxy_ips": ["127.0.0.1"]}
{"event": "http_request", "status": 401, "src_ip": "<ip:other:9c01d2aa>"}
Invalid Host header: <ip:other:51e0c3f7>
```

Los hexadecimales cambian en cada arranque. `203.0.113.7` y `198.51.100.9` salen como `other` porque son rangos de documentación; una IP pública real sale como `public`. Con `log_redact_network: false` el
log es como en 1.0.12 y el arranque añade:

```json
{"event": "log_network_redaction_disabled", "level": "warning"}
```

Ajustes de configuración al arrancar:

```json
{"event": "config_legacy_default_replaced", "option": "response_max_bytes", "configured": 1048576, "applied": 131072}
{"event": "config_value_clamped", "option": "wait_for_event_max_seconds", "configured": 300, "applied": 220}
```

Rechazo de CIMD:

```json
{"event": "oauth_cimd_rejected", "reason": "special_use_address", "client_id_host": "interno.example"}
```

Motivos: `disabled`, `bad_url`, `self_reference`, `special_use_address`,
`fetch_failed`, `redirect`, `bad_status`, `too_large`, `bad_json`,
`bad_document`, `client_id_mismatch`, `redirect_uri_mismatch`, `rate_limited`.
