# Modelo de datos: configuración del sistema (021)

Formas de respuesta, errores y entradas de la tabla. Datos de ejemplo
ficticios. Contratos de argumentos y hints en
[contracts/tools.md](contracts/tools.md).

## Catálogo de familias (`tool_families.py`)

| Familia | Descripción (inglés, DOCS y log) | Módulo | Tramo |
|---|---|---|---|
| `core_config` | Core configuration: name, location, units, time zone, currency, country, language and URLs. | `core_config` | a |
| `assistant_exposure` | Which entities Assist, conversation agents and the cloud voice assistants can see and control. | `assistant_exposure` | a |
| `users` | Home Assistant users: list, create without credentials, edit and delete. Never passwords or tokens. | `users` | b |
| `core_network` | Core network adapters and HTTP server configuration (port, SSL, reverse proxy). | `core_network` | c |

Las cuatro: `desde="1.2.0"`, desactivables, activas por defecto.

## Tabla de clasificación (`command_table.py`)

Forma de las `dedicated` (la que escribe el generador):
`E("dedicated", "cubierto por <tool>", "<familia>", tool="<tool>", cap="CAP-NNN")`.

| Comando | Categoría | Tool / motivo | Familia | CAP | Tramo |
|---|---|---|---|---|---|
| `config/core/update` | dedicated | `ha_update_core_config` | `core_config` | CAP-053 | a |
| `config/core/detect` | read, `open_world=True` | «propone ubicación, unidades, zona horaria, moneda y país consultando un servicio externo de geolocalización por IP; no guarda nada» | `generic_commands` | CAP-053 | a |
| `homeassistant/expose_entity` | dedicated | `ha_set_entity_exposure` | `assistant_exposure` | CAP-055 | a |
| `homeassistant/expose_entity/list` | dedicated | `ha_list_exposed_entities` | `assistant_exposure` | CAP-055 | a |
| `homeassistant/expose_new_entities/get` | dedicated | `ha_list_exposed_entities` | `assistant_exposure` | CAP-055 | a |
| `homeassistant/expose_new_entities/set` | dedicated | `ha_set_expose_new_entities` | `assistant_exposure` | CAP-055 | a |
| `config/auth/list` | dedicated | `ha_list_users` | `users` | CAP-056 | b |
| `config/auth/create` | dedicated | `ha_create_user` | `users` | CAP-056 | b |
| `config/auth/update` | dedicated | `ha_update_user` | `users` | CAP-056 | b |
| `config/auth/delete` | dedicated | `ha_delete_user` | `users` | CAP-056 | b |
| `auth/refresh_tokens` | deny | «solo devuelve las sesiones del usuario de la propia conexión (el de Hermes), no las de otros usuarios; revisado en la spec 021» | `generic_commands` | CAP-056 | b |
| `network/configure` | dedicated | `ha_update_network_config` | `core_network` | CAP-069 | c |
| `http/config/configure` | dedicated | `ha_update_http_config` | `core_network` | CAP-069 | c |
| `http/config/promote` | dedicated | `ha_promote_http_config` | `core_network` | CAP-069 | c |
| `analytics/preferences` | confirm, `open_world=True` (nuevo) | motivo de la 011 sin cambios | `generic_commands` | CAP-074 | c |

Sin cambios: `analytics`, `labs/list` (`read`), `labs/update` (`confirm`),
`get_config`, `auth/current_user` (`deny`, clase B: Hermes lo usa por dentro
y la genérica lo sigue rechazando), `config/auth_provider/homeassistant/*` y
los `auth/*` de clase D.

Test de la clase A (`tests/test_command_table.py`):

- `_POR_LA_TABLA["config/core/detect"] = "spec 021: FR-071 de la 008 la deja
  `read` en la tabla; consulta un servicio externo de geolocalización y no
  guarda nada"`.
- `_DENY_TRAS_REVISION["auth/refresh_tokens"] = "spec 021: solo da las
  sesiones del usuario de la conexión; research R-5"` (excepción nueva, mismo
  patrón: la clave tiene que ser de la spec que la revisa y la entrada `deny`
  con un motivo que no sea «pendiente»).

Generador: las doce `dedicated` en `_DEDICADAS_INICIALES` (bloque comentado
«021»).

## Respuestas de las tools

Toda vista previa: `{"confirmation_token", "expires_in_seconds", "preview"}`
de `create_confirmation_token`. Toda confirmación con estado cambiado:
el error de `ESTADO_CAMBIADO` de `resolve_confirmation_token` (pide otra
vista previa).

### `ha_get_core_config`

```json
{"location_name": "Casa", "latitude": 40.0, "longitude": -3.0,
 "elevation": 600, "radius": 100, "unit_system": "metric",
 "time_zone": "Europe/Madrid", "currency": "EUR", "country": "ES",
 "language": "es", "internal_url": null,
 "external_url": "https://homeassistant.tailXXXX.ts.net",
 "config_source": "storage", "version": "2026.11.1"}
```

`unit_system`: `metric` si `unit_system.temperature == "°C"` y longitud en
km; `us_customary` si °F; si no cuadra con ninguno, el dict de HA tal cual
bajo `unit_system_detail` y `unit_system: null`.

### `ha_update_core_config`

Vista previa:

```json
{"action": "update_core_config",
 "changes": {"time_zone": {"before": "Etc/UTC", "after": "Europe/Madrid"}},
 "unchanged": ["currency"],
 "update_units": false,
 "warnings": ["time_zone: time triggers, schedules and history use the new zone"],
 "config_source": "yaml"}
```

`warnings` (códigos y texto en inglés): `time_zone`, `unit_system`,
`update_units`, `location` (lat/long/radio/elevación: `zone.home`),
`urls` (apps móviles, enlaces y nube), `regional` (país, moneda, idioma),
`yaml_source` (la configuración viene de `configuration.yaml`: el cambio no
sobrevive a un reinicio).

Confirmación: `{"result": "ok", "applied": ["time_zone"], "config": {…como
ha_get_core_config…}}`; si la zona pasó y el resto no:
`{"result": "partial", "applied": ["time_zone"], "failed": ["currency"],
"error": "invalid_info", "detail": "…redactado…", "config": {…}}`.

Sin diferencias: `{"result": "no_changes"}` (sin token).

### `ha_list_exposed_entities`

```json
{"expose_new": {"conversation": true, "cloud.alexa": false,
                "cloud.google_assistant": false},
 "count": 2, "truncated": false,
 "items": [{"entity_id": "light.salon", "assistants": ["cloud.alexa", "conversation"]},
           {"entity_id": "lock.puerta", "assistants": ["conversation"]}]}
```

Orden por `entity_id`; `assistants` ordenados. Filtros `assistant` y `domain`
antes de recortar; `total` con las expuestas antes de filtrar.

### `ha_set_entity_exposure`

Vista previa:

```json
{"action": "set_entity_exposure", "expose": true,
 "by_assistant": {
   "cloud.alexa": {"change": ["light.salon", "lock.puerta"], "already": [],
                   "warning": "Amazon Alexa receives the state of these entities and can control them through Home Assistant Cloud."}},
 "sensitive": ["lock.puerta"]}
```

Confirmación: `{"result": "ok", "changed_entity_ids": [...]}`.
Sin cambios: `{"result": "no_changes"}`. Entidades que no existen:
`{"error": "not_found", "missing": [...]}`.

Avisos por asistente: `conversation` («Assist, every conversation agent
—including cloud LLM agents— and the MCP Server integration can see and
control them»), `cloud.alexa`, `cloud.google_assistant` (nube de Amazon o de
Google a través de Home Assistant Cloud; al ocultar: dejan de verlas).

### `ha_set_expose_new_entities`

Vista previa: `{"action": "set_expose_new_entities", "assistant":
"conversation", "before": false, "after": true, "warning": "…"}`;
confirmación `{"result": "ok", "assistant", "expose_new"}`.

### `ha_list_users`

```json
{"active_admins": 2, "hermes_user_known": true,
 "count": 2, "truncated": false,
 "items": [{"id": "abc123", "name": "Invitada", "username": null,
            "is_owner": false, "is_active": true, "is_admin": false,
            "local_only": false, "system_generated": false,
            "group_ids": ["system-users"], "credential_types": [],
            "is_hermes": false}]}
```

### Vista previa común de usuarios

```json
{"action": "update_user",
 "user": {"id": "abc123", "name": "Invitada", "is_admin": false,
          "is_active": true},
 "changes": {"group_ids": {"before": ["system-users"], "after": ["system-admin"]}},
 "grants_admin": true, "removes_admin": false, "deactivates": false,
 "restricts_remote": false,
 "active_admins": {"before": 1, "after": 2}}
```

`ha_create_user`: `{"action": "create_user", "name", "group", "local_only",
"grants_admin", "credentials": "none: this user cannot log in until a person
gives them a username and password in Home Assistant", "same_name": [ids]}`.
Confirmación: `{"result": "ok", "user": {…forma de la lista…}}`.

`ha_delete_user`: `{"action": "delete_user", "user": {…}, "linked_persons":
["person.invitada"], "irreversible": "…credentials and sessions are deleted;
cannot be undone", "active_admins": {…}}`. Confirmación `{"result": "ok",
"deleted": "<id>"}`.

### `ha_update_network_config`

Vista previa: `{"action": "update_network_config",
"configured_adapters": {"before": [], "after": ["eth0"]},
"enabled": {"before": ["eth0", "wlan0"], "after": ["eth0"]},
"note": "Changes discovery and the addresses Home Assistant announces; it
does not change the address or port Home Assistant listens on."}`.
Confirmación: `{"result": "ok", "configured_adapters": [...]}`.

### `ha_update_http_config`

Vista previa:

```json
{"action": "update_http_config", "base": "stable",
 "pending_replaced": false,
 "new_config": {"server_port": 8443, "ip_ban_enabled": true, "…": "…"},
 "changes": {"server_port": {"before": 8123, "after": 8443}},
 "restart": "Home Assistant restarts to apply this. It runs the new configuration on trial: if nobody promotes it with ha_promote_http_config within 5 minutes, or if it fails to start, Home Assistant goes back to the stable configuration and restarts again.",
 "warnings": [{"code": "port", "detail": "…"}]}
```

Códigos de aviso: `port`, `server_host` (Supervisor, Hermes y apps),
`ssl` (HTTPS obligatorio; `http://` deja de funcionar), `reverse_proxy`,
`ip_ban`, `cors`, `ssl_profile`, `pending_replaced`.

Confirmación: `{"result": "ok", "restart": true, "next": "…promote within 5
minutes…", "config_check": "…if configuration.yaml is invalid Home Assistant
refuses to restart; the change then applies on the next restart"}`.
`discard_pending`: vista previa con `pending` actual y si reinicia.

### `ha_promote_http_config`

Vista previa: `{"action": "promote_http_config", "changes": {…estable →
pendiente…}, "revert_at": "2026-11-15T10:05:00+00:00", "note": "The promoted
configuration becomes the one recovery mode uses."}`. Confirmación
`{"result": "ok"}`.

## Errores

| `error` | Cuándo | Llama a HA |
|---|---|---|
| `invalid_argument` (`field`, `detail`) | forma o rango inválido; lote vacío o > 200; adaptador inexistente; clave HTTP desconocida; `changes` y `discard_pending` a la vez | no |
| `not_found` (`missing`) | entidad, usuario o función inexistente | lectura sí, escritura no |
| `protected_user` (`reasons`: lista con todos los que aplican de `owner`, `hermes`, `system_generated`; en el banco el propietario es también el usuario de Hermes) | escritura sobre un usuario protegido | lectura sí, escritura no |
| `last_admin` | el cambio deja cero administradores activos | lectura sí, escritura no |
| `preview_unavailable` | no se pudo leer lo necesario para la vista previa (incluido `auth/current_user`) | — |
| `no_changes` (en `result`) | nada que cambiar | lectura sí |
| `nothing_to_promote` (`reason`) | sin pendiente, con error o HA sin funcionar con ella | lectura sí |
| `restart_blocked` | bloqueo de reinicio de Hermes (`sv_check_core_config`) | no |
| `ha_error` (`ha_code`, `detail` redactado) | `invalid_format` (esquema de HA), `invalid_info`, `bind_failed`, `not_running`, `not_allowed`, `no_delete_self`, `cannot_*` | sí |
| `unsupported_by_ha_version` (`ha_code`, `table_version`) | `unknown_command` | sí |
| error de conexión de siempre | Core caído | — |

## Inventarios del programa

- `tests/banco/cobertura_021.py`:
  - `PROBADAS_021`: las siete que escriben y se ejecutan con efecto
    (`ha_update_core_config`, `ha_set_entity_exposure`,
    `ha_set_expose_new_entities`, `ha_create_user`, `ha_update_user`,
    `ha_delete_user`, `ha_update_network_config`);
  - `NO_EJECUTABLES_021`: `ha_update_http_config` y `ha_promote_http_config`,
    con su motivo (R-8 de research);
  - `LECTURAS_021`: `ha_get_core_config`, `ha_list_exposed_entities`,
    `ha_list_users` (no entran en el invariante de escrituras, como las de la
    029, pero el job las exige por ejecución).
  - `PROBADAS_021 | LECTURAS_021` se suman a `TOOLS_EXIGIDAS_DEL_JOB`;
    `PROBADAS_021` y `NO_EJECUTABLES_021`, a la unión del invariante de
    escrituras.
- Matriz de la 014: nueve filas; siete `banco de Core | ok`, dos
  `VM | pendiente` con su línea en «Tandas de pruebas».
- Argumentos atados (033): nueve entradas, todos los argumentos `atado`
  salvo `confirmation_token`.
