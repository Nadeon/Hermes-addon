# Contratos de las tools afectadas (1.0.12)

Hermes expone tools MCP; su contrato es el nombre, los parámetros y la forma de
la respuesta. Solo se listan los cambios. Lo que no aparece, no cambia.

## Nueva: `ha_remove_device`

Destructiva (`destructiveHint: true` por el prefijo `ha_remove_`), con
`confirmation_token`.

```text
ha_remove_device(device_id: str, confirmation_token: str | None = None)
```

Sin token:

```json
{
  "confirmation_token": "…",
  "preview": {
    "device_id": "<id>",
    "device_name": "…",
    "action": "delete_device",
    "method": "config/device_registry/remove | config/device_registry/remove_config_entry",
    "config_entry_id": "<solo con remove_config_entry>",
    "entities_count": 3,
    "warning": "Deletes this device from the device registry together with its 3 entity registry entries. The integration must allow manual removal; it may re-add the device if it discovers it again."
  }
}
```

Errores sin token (no se emite token):

| `error` | Cuándo |
|---|---|
| `not_found` | El dispositivo no existe. |
| `ha_version_unknown` | No se pudo leer la versión de Home Assistant. |
| `multiple_config_entries` | HA < 2026.9 y el dispositivo tiene más de una integración. `hint` remite a `ha_remove_device_from_config_entry` por integración. |

Con token válido: `{"result": "ok", "method": "…"}` o `{"error": "…"}`. Si el
método calculado al ejecutar difiere del de la preview:
`{"error": "ha_version_changed"}` y el token se marca como fallido.

## Cambia: `ha_remove_device_from_config_entry` (deprecada)

Mismos parámetros y mismo envío. La preview añade:

```json
{
  "deprecated": true,
  "replacement": "ha_remove_device",
  "warning": "DEPRECATED, will be removed before Home Assistant 2027.9. On Home Assistant 2026.9 or newer this DELETES THE WHOLE DEVICE if the config entry is the device's own; on older versions it removes the association, and the device is deleted if it was its last config entry."
}
```

## Cambia: `ha_update_entity_registry`

- `updates.aliases`: lista de `str | null`. `null` dentro de la lista se envía tal cual.
- `updates.aliases = null` → `{"error": "aliases must be a list; use [] to clear or [null] to keep only the computed name"}` sin llamar a HA.

## Cambia: `ha_get_entity_registry`

Entidad inexistente (código `not_found` de HA): `{"error": "not_found", "entity_id": "<id>"}`.

## Cambia: `ha_list_devices`, `ha_list_entities_registry`

`area_id` filtra por área efectiva (ver data-model.md). Forma de respuesta igual.

## Cambia: `ha_delete_lovelace_dashboard`

Antes de cualquier token:

| `error` | Cuándo |
|---|---|
| `cannot_delete_default_dashboard` | `url_path` nulo, `"lovelace"` o igual al panel por defecto. |
| `default_panel_unknown` | No se pudo determinar el panel por defecto. |

## Cambia: `ha_list_lovelace_dashboards`

Si existe `lovelace`: sin elemento sintético; `lovelace` con `is_default: true`.

## Cambia: `sv_get_job_status`

```json
{
  "job_id": "…", "name": "…", "done": true, "success": false,
  "errors": ["Not enough free space"],
  "progress": 100, "stage": null, "reference": "…", "child_jobs": []
}
```

`success`: `true` | `false` | `null` (no terminado).

## Cambia: `sv_list_pending_jobs`

`status` ∈ `running`, `done`, `failed`.

## Cambia: errores del safety backup en `fs_*`

`{"error": "safety_backup_failed", "detail": "<código>: …"}` con `<código>` ∈
`safety_backup_job_failed`, `safety_backup_in_progress`,
`safety_backup_state_unknown`, `safety_backup_timeout` (este último con el
`job_id` y la indicación de consultarlo con `sv_get_job_status`).

## Cambia: `sv_get_supervisor_info`, `sv_get_host_info`

Mismas claves; `machine`, `docker_version` y `kernel_version` rellenos.

## Cambia: `ha_render_template`

Éxito con avisos:

```json
{"result": "…", "listeners": {}, "warnings": ["'sensor' is undefined"]}
```

Timeout de HA o local: `{"error": "template_timeout", …}`.

## Cambia: `ha_list_services`

```text
ha_list_services(domain: str | None = None)
```

Con `domain`: solo ese dominio (o `[]`). Sin `domain`: igual que antes.

## Cambia: `ha_statistics_during_period`

`period: "year"` con HA < 2026.3: `{"error": "period_not_supported", "detail": "period 'year' requires Home Assistant 2026.3 or newer"}`.

## Cambia: `ha_hacs_*`

| `error` | Cuándo |
|---|---|
| `hacs_moved_to_marketplace` | `unknown_command` y HA ≥ 2026.11. `hint`: usar `ha_get_states(domain="update")`. |
| `hacs_not_installed` | `unknown_command` y HA anterior o versión desconocida. |

`ha_hacs_list_repositories(category)` acepta `template` y ya no `netdaemon`.

## Cambia: borrado de helpers, zonas y personas (`ha_delete_*`)

Id inexistente (código `not_found` de HA) → la respuesta `not_found` que ya
documentaban.
