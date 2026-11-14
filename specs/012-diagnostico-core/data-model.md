# Modelo de datos: diagnóstico de Core (012)

Formas de lo que entra y sale de las 12 tools. Los nombres de campo de las
respuestas están en inglés (lo ve el cliente); los comentarios del código, en
español.

## Módulos y familia

| Módulo (`hermes/src/hermes/tools/`) | Tools | Tramo |
|---|---|---|
| `core_logs.py` | `ha_list_system_log`, `ha_get_error_log`, `ha_get_log_levels`, `ha_set_log_level`, `ha_clear_system_log` | A |
| `core_validation.py` | `ha_validate_config`, `ha_test_condition` | B |
| `integration_diagnostics.py` | `ha_list_diagnostics_handlers`, `ha_get_config_entry_diagnostics`, `ha_get_device_diagnostics` | B |
| `persistent_notifications.py` | `ha_list_persistent_notifications`, `ha_dismiss_persistent_notification` | B |

Familia en `tool_families.py`:

```python
Familia("core_diagnostics",
        "Home Assistant system log, error log and log levels, configuration "
        "validation, integration diagnostics and persistent notifications.",
        "1.2.0", True,
        ("core_logs", "core_validation", "integration_diagnostics",
         "persistent_notifications"))
```

En el tramo A la familia nace con `("core_logs",)`; el tramo B añade los otros
tres módulos.

## Entrada del log del sistema (salida de `ha_list_system_log`)

| Campo | Origen en HA | Notas |
|---|---|---|
| `level` | `level` | `ERROR`, `WARNING`, `CRITICAL`… tal cual |
| `logger` | `name` | p. ej. `homeassistant.components.mqtt` |
| `messages` | `message` (lista) | cada uno con `redact_secrets` |
| `source` | `source` | `{"file": str, "line": int}` |
| `count` | `count` | |
| `first_seen` | `first_occurred` | ISO 8601 UTC |
| `last_seen` | `timestamp` | ISO 8601 UTC; orden descendente |
| `exception` | `exception` | redactada; sin `include_tracebacks`, solo la última línea no vacía (o `null` si no hay) |
| `exception_truncated` | — | `true` si se quitó parte de la traza |

Respuesta: `{"count", "items", "truncated", "_third_party_text": {"fields":
["messages", "exception"], "warning": …}}`. Con `truncated`, el bloque
`_response_limit` de siempre.

Filtros: `level` ∈ {DEBUG, INFO, WARNING, ERROR, CRITICAL} (sin distinguir
mayúsculas); `integration` con forma de dominio (`^[a-z0-9_]+$`).

## Log de errores (salida de `ha_get_error_log`)

```json
{"lines_requested": 100, "lines_returned": 100, "redacted": true,
 "log": "…", "truncated": false}
```

`lines` acotado a [1, 1000]. `max_line_bytes` del método nuevo: 4096 (una
línea más larga se corta con el sufijo ` …[line truncated]`). Si no cabe en
`response_max_bytes`, las últimas líneas que caben, `truncated: true`,
`lines_returned` y la pista (como `sv_get_addon_logs`).

Error sin fichero:

```json
{"error": "error_log_unavailable",
 "detail": "Home Assistant has no log file: under the Supervisor it logs to the journal unless 'duplicate_log_file' is enabled in Core options.",
 "hint": "See hermes_guide(topic='core_diagnostics') for how to read Core's log through the Supervisor."}
```

## Nivel de log

Entrada de `ha_get_log_levels`: `{"domain": str, "level": "DEBUG"|…|"LEVEL n",
"level_value": int}`, ordenada por `domain`; filtro `domain` exacto.

Argumentos de `ha_set_log_level` (todos atados al token):

| Argumento | Tipo | Regla |
|---|---|---|
| `level` | `str` | DEBUG, INFO, WARNING, ERROR, CRITICAL, NOTSET; se normaliza a mayúsculas ANTES de atar el token |
| `integration` | `str \| None` | forma de dominio |
| `module` | `str \| None` | `^[A-Za-z0-9_.]+$`, ≤ 255; exactamente uno de los dos |
| `persistence` | `str` | `none` (defecto), `once`, `permanent` |

Vista previa:

```json
{"target": {"type": "integration", "name": "mqtt"},
 "previous_level": "WARNING", "previous_level_note": null,
 "new_level": "DEBUG", "persistence": "none",
 "persistence_effect": "Until Home Assistant restarts.",
 "effect": "Sets the log level of every logger of this integration.",
 "confirmation_token": "…", "expires_in": 60}
```

Textos de `persistence_effect`: `none` → «Until Home Assistant restarts.»;
`once` → «Now and on the next start of Home Assistant; dropped after that.»;
`permanent` → «Saved: applied on every start until changed.». Con `NOTSET`,
`effect` dice que quita el ajuste guardado y el logger vuelve al nivel por
defecto. Para un módulo: `previous_level: null` y `previous_level_note`:
«Home Assistant does not expose the level of a single module.».

Comando enviado al confirmar: `{"type": "logger/integration_log_level",
"integration", "level", "persistence"}` o `{"type": "logger/log_level",
"module", "level", "persistence"}`. Resultado: `{"result": "ok", "target",
"level", "persistence"}`. HA `not_found` → `{"error": "not_found", "target"}`.

## Limpieza del log del sistema

Vista previa: `{"entries": n, "by_level": {"ERROR": a, "WARNING": b, …},
"effect": "Empties the system log shown in Settings > System > Logs. Does not
touch the log file or the Supervisor journal. Entries logged before you confirm
are removed too.", "confirmation_token", "expires_in"}`. Log vacío →
`{"result": "unchanged", "entries": 0}`. Token sin argumentos (atado a la
tool). Al confirmar: `call_service("system_log", "clear", {})` →
`{"result": "ok"}`.

## Validación

Argumentos de `ha_validate_config`: `config: dict | None`, `triggers`,
`conditions`, `actions` (cualquier JSON). Respuesta:

```json
{"triggers": {"valid": false, "error": "…"},
 "conditions": {"valid": true, "error": null},
 "not_validated": ["alias", "mode"], "saved": false}
```

Solo aparecen las partes enviadas. `ha_test_condition(condition: dict,
variables: dict | None)` → `{"result": bool, "template_errors": [...]}` (la
clave solo si HA la da). Errores: `invalid_condition` (`invalid_format` de HA)
y `condition_error` (`home_assistant_error`), con `detail` redactado.

## Diagnósticos

`ha_list_diagnostics_handlers(domain=None)` → sobre con `{"domain",
"config_entry": bool, "device": bool}`. Dominio sin plataforma → `{"error":
"diagnostics_not_supported", "domain"}`.

`ha_get_config_entry_diagnostics(entry_id, keys=None, include_system_info=False)`
y `ha_get_device_diagnostics(device_id, keys=None, include_system_info=False)`:

```json
{"entry_id": "<entry_id>", "domain": "<dominio>", "device_id": "<solo en dispositivo>",
 "data": {…}, "issues": […], "system_info": {…},
 "keys_returned": ["…"], "redacted_by": ["home_assistant", "hermes"]}
```

- `system_info` solo con `include_system_info=true`: `home_assistant`,
  `custom_components`, `integration_manifest`, `setup_times`.
- `keys`: lista de claves de primer nivel de `data`; una que no exista →
  `invalid_argument` con las disponibles.
- Si no cabe: `{"error": "response_too_large", "data_keys": [{"key",
  "bytes"}], "max_bytes", "hint": "Request fewer keys with keys=[...]"}`.
- Comprobaciones previas: entrada (`config_entries/get_single`) → `not_found`;
  `diagnostics/get` de su dominio → `diagnostics_not_supported` si no hay
  handler del tipo; dispositivo (`config/device_registry/list`) → `not_found`
  o, sin `config_entry_id`, `diagnostics_not_supported` con `reason`.

## Notificación persistente

Entrada de `ha_list_persistent_notifications`: `{"notification_id", "title",
"message", "created_at"}` (texto redactado), ordenada por `created_at`
descendente, con `_third_party_text` sobre `title` y `message`.

Vista previa de `ha_dismiss_persistent_notification(notification_id)`:
`{"notification_id", "title", "message", "message_truncated", "created_at",
"effect": "Removes this notification from Home Assistant. It cannot be
restored.", "confirmation_token", "expires_in"}`. Mensaje recortado a 2000
caracteres. Al confirmar: relectura; si ya no está → `{"result":
"already_dismissed"}`; si está, `call_service("persistent_notification",
"dismiss", {"notification_id"})` → `{"result": "ok"}`.

## Entradas de la tabla (FR-014)

| Clave | Tool | CAP |
|---|---|---|
| `validate_config` | `ha_validate_config` | CAP-040 |
| `test_condition` | `ha_test_condition` | CAP-040 |
| `system_log/list` | `ha_list_system_log` | CAP-041 |
| `logger/log_info` | `ha_get_log_levels` | CAP-041 |
| `logger/log_level` | `ha_set_log_level` | CAP-041 |
| `logger/integration_log_level` | `ha_set_log_level` | — (fila «cubierto» del inventario) |
| `diagnostics/list` | `ha_list_diagnostics_handlers` | CAP-042 |
| `diagnostics/get` | `ha_list_diagnostics_handlers` | CAP-042 |
| `persistent_notification/get` | `ha_list_persistent_notifications` | CAP-047 |

Forma: `E("dedicated", "cubierto por <tool>", "core_diagnostics",
tool="<tool>", cap="CAP-0NN")`. Tramo A: las cuatro de `logger/` y
`system_log/list`; tramo B: las otras cuatro.

## Log de Hermes

Un evento por tool y resultado: `<tool>_ok` con recuentos (`count`,
`returned`, `lines_returned`, `entries`), `level`, `persistence`, tipo de
objetivo y dominio; `<tool>_error` con el código de error. Nunca mensajes,
líneas, trazas, títulos, datos de diagnóstico ni ids de notificación.
