# Contratos: control de Core y del Supervisor (022)

Formas detalladas en [data-model.md](../data-model.md). Descripciones al
cliente en inglés; comentarios en español.

## Firmas (esquema de entrada MCP)

```text
# Módulo system_control (familia system_control)
sv_start_core(confirmation_token: str | None = None)
sv_rebuild_core(safe_mode: bool = False, confirmation_token: str | None = None)
sv_set_core_options(options: dict[str, Any], confirmation_token: str | None = None)
sv_reload_supervisor()
sv_restart_supervisor(confirmation_token: str | None = None)
sv_repair_supervisor(confirmation_token: str | None = None)
sv_set_supervisor_options(options: dict[str, Any], confirmation_token: str | None = None)

# Módulo resolution_fixes (familia resolution_fixes)
sv_apply_resolution_suggestion(suggestion_uuid: str, confirmation_token: str | None = None)
```

`register(mcp, ha_client, *, response_max_bytes)` en cada módulo, registrado
en `tools/__init__.py` dentro de la comprobación de su familia (patrón de la
011).

## Anotaciones (research R-10)

| Tool | readOnly | destructive | idempotent | openWorld |
|---|---|---|---|---|
| `sv_start_core` | false | false | true | false |
| `sv_rebuild_core` | false | true | false | false |
| `sv_set_core_options` | false | true | true | false |
| `sv_reload_supervisor` | false | false | true | true |
| `sv_restart_supervisor` | false | true | false | false |
| `sv_repair_supervisor` | false | true | false | true |
| `sv_set_supervisor_options` | false | false | true | false |
| `sv_apply_resolution_suggestion` | false | true | false | true |

Títulos por `title_for` (sin palabras nuevas en `_TITLE_WORDS`).

## Descripciones (lo que tienen que decir)

- `sv_start_core`: starts Home Assistant Core when it is stopped; two steps;
  does nothing (`already_running`) if it already runs; Hermes keeps working
  while Core is down.
- `sv_rebuild_core`: recreates the Core container (Home Assistant is down for
  minutes); `safe_mode` loads no custom integrations; blocked like
  `sv_restart_core` while `/config` writes are not validated.
- `sv_set_core_options`: the six accepted keys; `image`, `refresh_token`,
  `port` and `ssl` are refused; nothing restarts now; some keys apply at the
  next start or rebuild.
- `sv_reload_supervisor`: no confirmation; refreshes versions (internet),
  secrets and the system evaluation; nothing is interrupted.
- `sv_restart_supervisor`: the Supervisor API and Hermes' connection to Core
  drop for about a minute; Core and apps keep running; refused while a
  Supervisor job runs.
- `sv_repair_supervisor`: what it deletes (stopped containers, unused images,
  build cache, unused volumes) and downloads; minutes; refused while a job
  runs.
- `sv_set_supervisor_options`: the five accepted keys; `channel` and the
  developer options are refused; warnings of `auto_update` and
  `diagnostics`.
- `sv_apply_resolution_suggestion`: applies a Supervisor suggestion after a
  preview that explains its effect; some delete data (an app, old full
  backups) or reboot the host; refuses suggestions that do nothing, that it
  cannot explain, that touch data disks or Hermes itself; the Supervisor may
  also apply its automatic fixes afterwards.

## Respuestas

| Tool | Sin token | Con token |
|---|---|---|
| Las de dos pasos | `{confirmation_token, expires_in_seconds, preview}` (forma de `create_confirmation_token`) | `{"result": "ok", …}` o `{"status": "started", "verify_with": …}` |
| `sv_reload_supervisor` | `{"result": "ok", "note"}` | — |

## Errores

Los de data-model («Errores»). Ningún rechazo llama a una ruta que escribe.
`invalid_confirmation_token` con el texto de `security.py`.

## Log

Eventos de data-model; nunca valores de opciones, `reference`, nombres de
backups ni el texto completo de un error.

## Genéricas (tabla)

| Llamada | Resultado |
|---|---|
| `sv_call_api("POST", "/core/start" \| "/core/rebuild" \| "/core/options" \| "/supervisor/reload" \| "/supervisor/restart" \| "/supervisor/repair" \| "/supervisor/options")` | `use_dedicated_tool` con la tool y `family: system_control` |
| `sv_call_api("POST", "/resolution/suggestion/<uuid>")` | `use_dedicated_tool` → `sv_apply_resolution_suggestion` (`resolution_fixes`) |
| `sv_read_api("/core/stats")`, `("/supervisor/stats")` | lectura |
| `sv_call_api("POST", "/host/reload" \| "/resolution/check/<c>/run" \| "/resolution/check/<c>/options" \| "/resolution/healthcheck")` | vista previa y token |
| `sv_call_api("POST", "/core/stop")`, `/homeassistant/*` | `command_denied` |
| CAP-091, CAP-092, CAP-094 | sin cambios (research R-8) |

## Guía

Tema `system_control` (alias `core_control`, `supervisor_control`,
`suggestions`, `fixups`): las 8 tools, qué cortan y cuánto, listas cerradas
de opciones, rechazos, rutas por la tabla (estadísticas, chequeos, host,
plugins, Docker, placas, NTP, con el aviso de que DNS y opciones de Docker
pueden dejar sin red a las apps) y la receta «Core no arranca». `diagnostics`
remite a `sv_apply_resolution_suggestion`; `supervisor`, a `system_control`.
