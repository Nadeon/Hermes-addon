# Contratos: tools de diagnóstico del Supervisor (013)

Las descripciones que ve el cliente van en inglés (principio X); los ejemplos
usan datos ficticios (principio VIII).

## Firmas (esquema de entrada MCP)

```text
# Módulo system_logs (familia system_diagnostics)
sv_get_core_logs(lines: int = 100, boot: int | str | None = None, latest: bool = False) -> object
sv_get_supervisor_logs(lines: int = 100, boot: int | str | None = None, latest: bool = False) -> object
sv_get_plugin_logs(plugin: str, lines: int = 100, boot: int | str | None = None, latest: bool = False) -> object
sv_get_host_logs(lines: int = 100, boot: int | str | None = None, identifier: str | None = None) -> object
sv_list_host_log_identifiers(search: str | None = None) -> object
sv_list_boots() -> object

# Módulo host_system (familia system_diagnostics)
sv_list_host_services(state: str | None = None) -> object
sv_get_disk_usage(disk: str = "default", max_depth: int = 1) -> object
sv_get_os_info() -> object
sv_get_swap() -> object
sv_list_datadisk_candidates() -> object

# Existente (familia supervisor): dos argumentos opcionales nuevos
sv_get_addon_logs(slug: str, lines: int = 100, boot: int | str | None = None, latest: bool = False) -> object
```

## Anotaciones

Todas: `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`,
`openWorldHint: false` (por los prefijos `sv_get_`/`sv_list_`, que ya son de
solo lectura). Ninguna toma `confirmation_token`. Títulos:

| Tool | Título |
|---|---|
| `sv_get_core_logs` | `Get core logs (Supervisor)` |
| `sv_get_supervisor_logs` | `Get supervisor logs (Supervisor)` |
| `sv_get_plugin_logs` | `Get plugin logs (Supervisor)` |
| `sv_get_host_logs` | `Get host logs (Supervisor)` |
| `sv_list_host_log_identifiers` | `List host log identifiers (Supervisor)` |
| `sv_list_boots` | `List boots (Supervisor)` |
| `sv_list_host_services` | `List host services (Supervisor)` |
| `sv_get_disk_usage` | `Get disk usage (Supervisor)` |
| `sv_get_os_info` | `Get OS info (Supervisor)` (`"os": "OS"` en `_TITLE_WORDS`) |
| `sv_get_swap` | `Get swap (Supervisor)` |
| `sv_list_datadisk_candidates` | `List datadisk candidates (Supervisor)` |

`"os": "OS"` no cambia el título de ninguna tool de la 1.1.2 (ninguna tiene la
palabra `os`); un test lo comprueba.

## Descripciones (lo que tienen que decir)

- Logs: qué log es, que los secretos salen redactados, que si no cabe se
  devuelven las ÚLTIMAS líneas, qué es `boot` (0 = arranque actual, -1 = el
  anterior; o un id de `sv_list_boots`) y `latest` (solo desde el último
  arranque del contenedor), que no se pueden combinar.
- `sv_get_supervisor_logs`: además, que sin journal el Supervisor devuelve el
  log de su contenedor y no aplica `boot` ni `latest`.
- `sv_get_host_logs`: `identifier` de `sv_list_host_log_identifiers`; sin él,
  los servicios por defecto del host; no hay `latest`.
- `sv_get_plugin_logs`: `plugin` es `dns`, `audio` o `multicast`.
- `sv_get_disk_usage`: `disk` = `default` o el nombre de un montaje; `max_depth`
  0–3, con los niveles que da el Supervisor (disco del sistema: 0 y 1 dan sus
  zonas fijas, 2 y 3 añaden uno y dos niveles de carpetas; montaje: 0 y 1 solo
  totales, 2 y 3 dan uno y dos niveles); poda a 20 hijos por nivel y, si no
  cabe en `response_max_bytes`, pliega las carpetas más pequeñas con
  `truncated: true` (T029, T032); un montaje lento puede tardar hasta un
  minuto.
- `sv_get_os_info`, `sv_get_swap`, `sv_list_datadisk_candidates`: requieren
  Home Assistant OS (la swap, OS 15 o posterior); solo leen.
- `sv_get_addon_logs`: añade `boot` y `latest` sin cambiar lo demás.

## Respuestas

Log (Core, Supervisor, plugin, host):

```json
{"source": "host", "route": "/host/logs/boots/{bootid}/identifiers/{identifier}",
 "boot": -1, "identifier": "kernel", "lines_requested": 100, "redacted": false,
 "logs": "… kernel: usb 1-1: new device …\n"}
```

Recortado:

```json
{"source": "core", "route": "/core/logs", "lines_requested": 1000, "redacted": true,
 "logs": "…", "truncated": true, "lines_returned": 412,
 "hint": "Only the last lines that fit in response_max_bytes are shown. Ask for fewer lines instead of repeating the same call."}
```

`sv_get_addon_logs` sin `boot` ni `latest`: exactamente la de la 1.1.2.
Con ellos:

```json
{"slug": "<slug>", "lines_requested": 100, "redacted": false,
 "route": "/addons/{app}/logs/latest", "latest": true, "logs": "…"}
```

Arranques:

```json
{"count": 3, "truncated": false, "items": [
  {"offset": 0, "boot_id": "0123456789abcdef0123456789abcdef"},
  {"offset": -1, "boot_id": "fedcba9876543210fedcba9876543210"},
  {"offset": -2, "boot_id": "00112233445566778899aabbccddeeff"}]}
```

Identificadores: `{"count": 2, "truncated": false, "items": ["kernel", "systemd-journald"]}`
(con `"search"` si se filtró).

Servicios: `{"count": 1, "truncated": false, "state": "failed", "items": [
{"name": "servicio-ficticio.service", "description": "…", "state": "failed"}]}`.

Uso de disco:

```json
{"disk": "default", "max_depth": 1, "id": "root", "label": "Root",
 "total_bytes": 32000000000, "used_bytes": 20000000000,
 "children": [
   {"id": "homeassistant", "label": "homeassistant", "used_bytes": 9000000000},
   {"id": "backup", "label": "backup", "used_bytes": 6000000000},
   {"id": "system", "label": "System", "used_bytes": 3000000000}]}
```

OS: la respuesta de `/os/info` o `/os/config/swap` tras `redact_structure` (objeto);
candidatos: `{"count", "truncated", "items": <disks>, "devices": [...]}`.

## Errores

```json
{"error": "invalid_argument", "field": "boot", "detail": "boot must be an integer offset between -999 and 999 or a 32-character hexadecimal boot ID."}
{"error": "invalid_argument", "field": "latest", "detail": "latest and boot cannot be combined."}
{"error": "invalid_argument", "field": "identifier", "detail": "identifier must be 1-64 characters of letters, digits, '.', '_', '@' or '-', not starting with '.'."}
{"error": "invalid_argument", "field": "plugin", "detail": "plugin must be one of: dns, audio, multicast."}
{"error": "invalid_argument", "field": "max_depth", "detail": "max_depth must be between 0 and 3."}
{"error": "invalid_argument", "field": "disk", "detail": "disk must be 'default' or a mount name (letters, digits and '_')."}
{"error": "Supervisor GET /os/config/swap failed 404: …",
 "hint": "Requires Home Assistant OS (swap needs OS 15 or newer)."}
```

El `detail` nunca copia el valor rechazado; el mensaje del Supervisor pasa por
`redact_secrets`.

## Log

```text
system_diagnostics_read tool=sv_get_host_logs route=/host/logs/boots/{bootid}
                        lines=100 bytes=5120 redacted=false outcome=ok
```

`outcome` ∈ {`ok`, `error`, `invalid_argument`}. Nunca el contenido, el
identificador de arranque, `identifier` ni `search`.

## Genéricas (tabla)

- `sv_read_api("/jobs/info")`, `("/resolution/issue/<uuid>/suggestions")`,
  `("/host/disks")`, `("/hardware/info")`, `("/hardware/audio")`,
  `("/security/info")`, `("/docker/info")`, `("/time/info")`,
  `("/network/info")`, `("/network/interface/eth0/info")`,
  `("/network/interface/wlan0/accesspoints")` → se ejecutan (forma de la 011).
- `sv_read_api("/core/logs")` y cualquier otra ruta de las 28 →
  `use_dedicated_tool` con su tool.
- `sv_call_api("POST", "/security/integrity")` → `command_denied` con el motivo
  de la tabla; ninguna llamada al Supervisor.

## Guía

`hermes_guide("system_diagnostics")` (alias `system_logs`, `supervisor_logs`,
`host_logs`, `boots`, `disk`, `storage`, `os`, `jobs`): las 11 tools, `boot` y
`latest`, cómo encontrar un arranque o un identificador, qué llena el disco, y
las rutas que se leen con `sv_read_api` (jobs, sugerencias, hardware,
seguridad, Docker, hora, red, discos montables). Ninguno de esos alias existe
hoy; `logs` no se usa para no chocar con el log de Core de la 012.
