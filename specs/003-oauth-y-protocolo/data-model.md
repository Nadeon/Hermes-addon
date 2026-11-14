# Modelo de datos: Hermes 1.1.0 — OAuth y protocolo

Los ejemplos usan marcadores: `homeassistant.tailXXXX.ts.net` como
`public_hostname`, IPs de documentación (`192.0.2.x`, `198.51.100.x`,
`203.0.113.x`).

## Documento de metadatos del cliente (CIMD)

Lo publica el cliente en la URL que usa como `client_id`. Hermes lo descarga y
lo valida (FR-002…FR-010).

| Campo | Obligatorio | Regla |
|---|---|---|
| `client_id` | sí | igual, carácter a carácter, a la URL descargada |
| `client_name` | sí | texto no vacío, ≤ 200 caracteres; **autodeclarado**: no es identidad |
| `redirect_uris` | sí | lista de 1 a 10 URI absolutas, sin fragmento, ≤ 2 048 caracteres, sin `javascript`/`data`/`vbscript`/`file` |
| `grant_types` | no (`["authorization_code"]`) | debe incluir `authorization_code`; `refresh_token` habilita el refresh |
| `response_types` | no (`["code"]`) | debe incluir `code` |
| `token_endpoint_auth_method` | no (`none`) | solo `none` |
| `client_secret`, `client_secret_expires_at` | prohibidos | su presencia invalida el documento |
| resto (`client_uri`, `logo_uri`…) | no | se ignoran |

Ejemplo real (Claude Code, descargado el 2026-11-14):

```json
{"client_id":"https://claude.ai/oauth/claude-code-client-metadata","client_name":"Claude Code",
 "client_uri":"https://claude.ai","redirect_uris":["http://localhost/callback","http://127.0.0.1/callback"],
 "grant_types":["authorization_code","refresh_token"],"response_types":["code"],"token_endpoint_auth_method":"none"}
```

## Entrada de la caché CIMD (memoria)

| Campo | Significado |
|---|---|
| `url` | clave; la URL del `client_id` tal cual |
| `client_name`, `redirect_uris`, `allow_refresh` | lo único que Hermes usa del documento |
| `fetched_at` | momento de la descarga correcta |
| `expires_at` | `fetched_at` + vida (FR-016) |

Estados y transiciones (por URL):

```text
(sin entrada) --descarga válida--> VIGENTE
VIGENTE --pasa expires_at--> CADUCADA
CADUCADA --recarga válida--> VIGENTE
CADUCADA --fallo temporal y fetched_at < 24 h--> CADUCADA (se usa)
CADUCADA --fallo temporal y fetched_at ≥ 24 h--> (sin entrada) + error temporal
VIGENTE/CADUCADA --fallo definitivo--> (sin entrada) + revocar refresh del cliente
(sin entrada) --cualquier fallo--> (sin entrada)   # los errores no se cachean
```

Tope: 64 entradas, se expulsa la usada hace más tiempo.

Fallos **temporales**: error de red o DNS, timeout, 5xx, 429, cupo de descargas
agotado. Fallos **definitivos**: forma de URL inválida, dirección especial,
3xx, 4xx (salvo 429), tamaño, JSON o contenido inválido, `client_id` distinto.

## Cliente DCR (`/data/oauth/clients/<uuid>.json`)

Sin cambios respecto a 1.0.12. `client_id` UUID; comparación exacta del
`redirect_uri`.

## Código de autorización (`/data/oauth/codes/<hash>.json`)

Campos nuevos (los de 1.0.12 no cambian):

| Campo | Valor |
|---|---|
| `client_kind` | `"cimd"` o `"dcr"`; si falta (código emitido por 1.0.12 y aún vivo), `"dcr"` |
| `allow_refresh` | `true`/`false`; si falta, `true` |

## Tokens (`/data/oauth/tokens/<hash>.json`)

Campo nuevo en access y refresh: `resource` (`https://homeassistant.tailXXXX.ts.net/mcp`).

| Token | `resource` | Resultado de la validación |
|---|---|---|
| emitido por 1.1.0 | canónico | válido hasta caducar |
| emitido por 1.1.0 | otro valor | **rechazado** |
| emitido por ≤ 1.0.12 | ausente | válido hasta caducar (FR-031) |

El refresh hereda `resource` o, si falta, pone el canónico.

## Opciones del add-on

| Opción | Esquema (`config.yaml`) | Por defecto | Efectivo |
|---|---|---|---|
| `response_max_bytes` | `int(10240,10485760)?` (sin cambios) | **131072** (antes 1048576) | `1048576` → 131072; `> 524288` → 524288; resto tal cual |
| `wait_for_event_max_seconds` | `int(10,300)?` (sin cambios) | 90 | `> 220` → 220 |
| `oauth_cimd_enabled` | `bool?` (nueva) | `true` | — |
| `log_redact_network` | `bool?` (nueva) | `true` | — |

Cada ajuste se anota en `HermesConfig.adjustments`:

```json
{"option": "response_max_bytes", "configured": 1048576, "applied": 131072, "reason": "legacy_default"}
{"option": "wait_for_event_max_seconds", "configured": 300, "applied": 220, "reason": "above_cap"}
```

y se registra como `config_legacy_default_replaced` (`legacy_default`) o
`config_value_clamped` (`above_cap`).

## Seudónimo de IP en el log

Forma: `<ip:CLASE:HHHHHHHH>`.

| CLASE | Rangos (se comprueban en este orden) |
|---|---|
| `tailnet` | `100.64.0.0/10`, `fd7a:115c:a1e0::/48` |
| `link-local` | `169.254.0.0/16`, `fe80::/10` |
| `private` | `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `fc00::/7` |
| `public` | `is_global` de `ipaddress` |
| `other` | el resto (documentación, reservadas, multicast…) |

`HHHHHHHH`: 8 hexadecimales de HMAC-SHA-256(sal por proceso, bytes de la IP).
Loopback (`127.0.0.0/8`, `::1`) no se toca.
