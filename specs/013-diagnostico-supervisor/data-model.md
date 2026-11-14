# Modelo de datos: diagnóstico del Supervisor (013)

## Argumentos comunes de las tools de logs

| Argumento | Tipo | Por defecto | Regla (fail-closed, antes de llamar) | Tools |
|---|---|---|---|---|
| `lines` | `int` | 100 | se acota a [1, 1000] | todas las de logs |
| `boot` | `int \| str \| None` | `None` | entero de -999 a 999 (o texto con esa forma) → desplazamiento; 32 hex → identificador en minúsculas; si no → `invalid_argument` (`field: "boot"`) | Core, Supervisor, plugin, host, add-on |
| `latest` | `bool` | `False` | con `boot` → `invalid_argument` (`field: "latest"`) | Core, Supervisor, plugin, add-on |
| `identifier` | `str \| None` | `None` | `^[A-Za-z0-9_@-][A-Za-z0-9._@-]{0,63}$`; si no → `invalid_argument` (`field: "identifier"`) | host |
| `plugin` | `str` | — | `dns`, `audio` o `multicast`; si no → `invalid_argument` con la lista | plugin |

Ningún `detail` copia el valor rechazado; dice la regla.

## Ruta según los argumentos

| Tool | Sin `boot` ni `latest` | `latest` | `boot` |
|---|---|---|---|
| `sv_get_core_logs` | `/core/logs` | `/core/logs/latest` | `/core/logs/boots/{boot}` |
| `sv_get_supervisor_logs` | `/supervisor/logs` | `/supervisor/logs/latest` | `/supervisor/logs/boots/{boot}` |
| `sv_get_plugin_logs` | `/{plugin}/logs` | `/{plugin}/logs/latest` | `/{plugin}/logs/boots/{boot}` |
| `sv_get_addon_logs` | `/addons/{slug}/logs` (1.1.2) | `/addons/{slug}/logs/latest` | `/addons/{slug}/logs/boots/{boot}` |

`sv_get_host_logs`: `/host/logs`, `/host/logs/boots/{boot}`,
`/host/logs/identifiers/{identifier}`,
`/host/logs/boots/{boot}/identifiers/{identifier}`.

Siempre `params={"lines": str(lines)}` y `sv_request_text`.

## Respuesta de log

```json
{
  "source": "core",
  "route": "/core/logs/boots/{bootid}",
  "lines_requested": 100,
  "redacted": true,
  "logs": "…"
}
```

- `source`: `core`, `supervisor`, `dns`/`audio`/`multicast`, `host`.
- `route`: la plantilla (nunca el identificador de arranque concreto).
- `boot` (si se pidió): el valor normalizado; `identifier` (host, si se pidió).
- Si no cabe: `truncated: true`, `lines_returned`, `hint` (los de la 1.1.2).
- `sv_get_addon_logs`: forma de la 1.1.2 (`slug`, `lines_requested`,
  `redacted`, `logs`), más `route` y `boot`/`latest` solo si se usaron.

## Redacción

| Origen | `redact_secrets` | `redact_network` |
|---|---|---|
| Core, Supervisor, plugins | sí | no |
| Host sin `identifier`, o con un identificador ajeno a Hermes | sí | no |
| Host con `identifier` = `addon_<s>` o `app_<s>` y `_es_hermes(s)` | sí | sí |
| Add-on con `_es_hermes(slug)` (como en la 1.1.2) | sí | sí |

## Arranques (`sv_list_boots`)

Del Supervisor: `{"boots": {"0": "<id>", "-1": "<id>", …}}`. Hermes:

```json
{"count": 2, "items": [{"offset": 0, "boot_id": "<32 hex>"}, {"offset": -1, "boot_id": "<32 hex>"}], "truncated": false}
```

Orden por `offset` descendente (del actual al más antiguo).

## Identificadores (`sv_list_host_log_identifiers`)

`{"count", "items": [<str>, …] (ordenados), "truncated", "search"?}`.

## Servicios (`sv_list_host_services`)

`{"count", "items": [{"name", "description", "state"}], "truncated", "state"?}`.

## Uso de disco (`sv_get_disk_usage`)

Nodo: `{"id", "label", "used_bytes", "children"?: [...], "children_omitted"?,
"omitted_bytes"?}`; la raíz lleva además `total_bytes` y la respuesta, `disk` y
`max_depth`. Poda: por nodo, 20 hijos con más `used_bytes` (empate por `id`).
`disk`: `default` o `^[A-Za-z0-9_]{1,64}$`; `max_depth`: entero de 0 a 3.

## OS

- Todas las respuestas JSON pasan por `redact_structure` (FR-016).
- `sv_get_os_info`: la respuesta de `/os/info` (objeto).
- `sv_get_swap`: la de `/os/config/swap` (`swap_size`, `swappiness`).
- `sv_list_datadisk_candidates`: `{"count", "items": <disks>, "truncated",
  "devices": [...]}`.

## Error

- Argumento: `{"error": "invalid_argument", "field", "detail"}`.
- Supervisor: `{"error": <mensaje redactado>}` y, en `/os/*` con 404,
  `"hint": "Requires Home Assistant OS (swap needs OS 15 or newer)."`.

## Evento de log

`system_diagnostics_read` con `tool`, `route` (plantilla), `lines` (logs),
`bytes`, `redacted` (logs), `count` (listas) y `outcome` (`ok`, `error`,
`invalid_argument`). Nunca contenido, identificador de arranque, `identifier`
inválido, `search` ni datos de la respuesta.

## Entradas de la tabla que cambian

### A `dedicated` (28)

| Ruta (todas `GET`) | Tool | Familia |
|---|---|---|
| `/core/logs`, `/core/logs/latest`, `/core/logs/boots/{bootid}` | `sv_get_core_logs` | `system_diagnostics` |
| `/supervisor/logs`, `/supervisor/logs/latest`, `/supervisor/logs/boots/{bootid}` | `sv_get_supervisor_logs` | `system_diagnostics` |
| `/dns/logs`, `/dns/logs/latest`, `/dns/logs/boots/{bootid}`, ídem `/audio` y `/multicast` (9) | `sv_get_plugin_logs` | `system_diagnostics` |
| `/host/logs`, `/host/logs/boots/{bootid}`, `/host/logs/identifiers/{identifier}`, `/host/logs/boots/{bootid}/identifiers/{identifier}` | `sv_get_host_logs` | `system_diagnostics` |
| `/host/logs/identifiers` | `sv_list_host_log_identifiers` | `system_diagnostics` |
| `/host/logs/boots` | `sv_list_boots` | `system_diagnostics` |
| `/addons/{app}/logs/latest`, `/addons/{app}/logs/boots/{bootid}` | `sv_get_addon_logs` | `supervisor` |
| `/host/services` | `sv_list_host_services` | `system_diagnostics` |
| `/host/disks/{disk}/usage` | `sv_get_disk_usage` | `system_diagnostics` |
| `/os/info` | `sv_get_os_info` | `system_diagnostics` |
| `/os/config/swap` | `sv_get_swap` | `system_diagnostics` |
| `/os/datadisk/list` | `sv_list_datadisk_candidates` | `system_diagnostics` |

Motivo: «cubierto por `<tool>`», como las demás `dedicated`. Conservan su
`cap` (CAP-081 o CAP-085): son clase A en el inventario y
`test_a_y_c_con_su_cap` exige que la CAP de la tabla sea la del inventario.
El inventario (TSV) no cambia: la deriva compara claves, y la tabla es la
fuente de verdad tras la primera generación.

### A `read` (3), familia `generic_commands`, con su CAP

| Ruta | CAP | Motivo |
|---|---|---|
| `GET /jobs/info` | CAP-087 | todos los jobs del Supervisor (nombre, progreso, estado, errores, hijos) y si se ignoran condiciones; solo lee |
| `GET /resolution/issue/{issue}/suggestions` | CAP-087 | sugerencias que arreglan un issue del centro de resolución; solo lee |
| `GET /host/disks` | CAP-085 | discos locales con particiones montables (para crear montajes); solo lee |

### Sin cambios, con test nuevo

`read`: `GET /hardware/info`, `/hardware/audio`, `/security/info`,
`/docker/info`, `/time/info` (CAP-088); `/network/info`,
`/network/interface/{interface}/info`,
`/network/interface/{interface}/accesspoints` (CAP-089). `deny`:
`POST /security/integrity` (eliminada en 2026.11).

## Familia

`Familia("system_diagnostics", "Supervisor, Core, host and plugin logs; host
services, disk usage, OS and swap (read only).", "1.2.0", True,
("system_logs", "host_system"))`.
