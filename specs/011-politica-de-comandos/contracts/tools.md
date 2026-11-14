# Contratos: genéricas, guía y opción de familias (011)

Las descripciones que ve el cliente van en inglés (principio X); los ejemplos
usan datos ficticios (principio VIII).

## Firmas (esquema de entrada MCP)

```text
ha_read_ws_command(type: str, payload: dict | None = None) -> object
ha_call_ws_command(type: str, payload: dict | None = None,
                   confirmation_token: str | None = None) -> object
sv_read_api(path: str) -> object
sv_call_api(method: str, path: str, body: dict | None = None,
            confirmation_token: str | None = None) -> object
hermes_guide(topic: str | None = None, search: str | None = None) -> str
```

## Anotaciones

| Tool | readOnly | destructive | idempotent | openWorld | Título |
|---|---|---|---|---|---|
| `ha_read_ws_command` | sí | no | sí | no | `Read WS command (Home Assistant)` |
| `ha_call_ws_command` | no | sí | no | sí | `Call WS command (Home Assistant)` |
| `sv_read_api` | sí | no | sí | no | `Read API (Supervisor)` |
| `sv_call_api` | no | sí | no | sí | `Call API (Supervisor)` |

`hermes_guide` no cambia de anotaciones.

## Respuestas

Lectura de Core, resultado objeto o escalar:

```json
{"command": "tag/list", "category": "read", "result": {"…": "…"}}
```

Resultado lista (sobre común, recortable por el tope central):

```json
{"command": "tag/list", "category": "read", "count": 2,
 "items": [{"id": "tag-ficticio-1"}, {"id": "tag-ficticio-2"}], "truncated": false}
```

Supervisor: `method`, `path` (concreta) y `route` (plantilla) en lugar de
`command`. Ruta de texto:

```json
{"method": "GET", "path": "/dns/logs", "route": "/dns/logs", "category": "read",
 "count": 120, "lines": ["…"], "truncated": true}
```

Vista previa de `ha_call_ws_command` (sin token):

```json
{
  "confirmation_token": "…",
  "expires_in_seconds": 60,
  "preview": {
    "tool": "ha_call_ws_command",
    "command": "tag/create",
    "category": "confirm",
    "reason": "Tags: create",
    "cap": "CAP-066",
    "note": "This preview shows exactly what will be sent to Home Assistant. It does not interpret the effect of the command.",
    "payload_summary": {
      "bytes": 74, "keys": 3,
      "rows": [
        {"path": "tag_id", "type": "string", "bytes": 17, "value": "tag-ficticio-3"},
        {"path": "name", "type": "string", "bytes": 15, "value": "Llavero azul"},
        {"path": "api_key", "type": "string", "bytes": 20, "hidden": "sensitive"}
      ]
    }
  }
}
```

`sv_call_api`: igual con `method`, `path`, `route` y `body_summary`.

Ejecución confirmada: la misma forma que la lectura con `"executed": true`.

## Errores

Todos con `{"error": <código>, "detail": <texto en inglés>}` más los campos de
la tabla de data-model.md. Ejemplos:

```json
{"error": "use_dedicated_tool", "detail": "lovelace/config/save has a dedicated tool.",
 "tool": "ha_save_lovelace_dashboard", "family": "lovelace", "family_disabled": false}
{"error": "command_denied", "detail": "debug_console/run is not allowed.",
 "reason": "Python arbitrario dentro de HA (clase D)"}
{"error": "command_not_classified", "detail": "This command is not in Hermes' command table.",
 "hint": "hermes_guide(topic='generic_commands', search=…) lists what is available."}
{"error": "wrong_generic_tool", "detail": "tag/create needs confirmation.", "use_tool": "ha_call_ws_command"}
{"error": "path_not_allowed", "detail": "…", "rule": "core_proxy"}
{"error": "preview_too_large", "detail": "…", "payload_bytes": 400000, "keys": 9000}
{"error": "ha_command_failed", "detail": "…", "ha_code": "unknown_command",
 "hint": "The installed Home Assistant does not know this command; Hermes' table is for 2026.11.1."}
```

El `detail` nunca copia valores de la carga ni un `type`/`path` con forma
inválida: el mensaje de HA o del Supervisor pasa por `redact_secrets` y cada
valor de texto de la carga de 4 o más caracteres se sustituye por `***`.

## Log

Un evento por llamada:

```text
generic_command tool=ha_call_ws_command command=tag/create category=confirm
                outcome=preview payload_keys=["api_key","name","tag_id"] payload_bytes=74
```

`outcome` ∈ {`executed`, `preview`, `rejected:<código>`, `failed`}. Nunca
valores, nunca la ruta concreta del Supervisor (solo `route`).

## Guía

- `hermes_guide("generic_commands")` (alias `commands`, `generic`, `ws`,
  `api`, `table`): cuándo usar una genérica, categorías, códigos de rechazo,
  dos pasos, cómo buscar.
- `hermes_guide("generic_commands", search="tag")`: tabla Markdown con hasta
  50 filas `clave | categoría | tool dedicada o motivo | ejemplo`; si hay más,
  «N more: refine the search».
- `search` sin `topic` o con otro tema: se ignora y se responde el tema (sin
  error), y el texto lo dice.

## Opción

```yaml
# hermes/config.yaml
schema:
  tool_families_disabled:
    - "str?"
options:
  tool_families_disabled: []
```

Arranque con un nombre inválido: `ValueError` con un mensaje en español, como
los demás de `HermesConfig.validate()`:
`tool_families_disabled: la familia 'xxx' no existe. Válidas: automations,
backups, …` (o `la familia 'base' no se puede desactivar`). Log de arranque:
`tool_families disabled=[…] tools_registered=N`.
