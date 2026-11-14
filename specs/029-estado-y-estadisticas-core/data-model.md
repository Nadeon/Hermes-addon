# Modelo de datos: estado del sistema y estadísticas de Core (029)

Sin almacenamiento nuevo: nada se guarda en `/data`. Lo que sigue son las
estructuras que entran y salen de las tools y los cambios en los catálogos de
la 011.

## Catálogo de familias (`tool_families.py`)

| Familia | Descripción (DOCS y log de arranque) | Desde | Desactivable | Módulos |
|---|---|---|---|---|
| `system_status` | System health, pending restart state, integration setup times and manifests (read only). | 1.2.0 | sí | `system_status` |
| `recorder` | Recorder status and long-term statistics validation and metadata (read only). | 1.2.0 | sí | `recorder_status` |

## Tabla de clasificación (`command_table.py`)

Nueve entradas de `deny` «pendiente de tool dedicada (spec 029)» a
`dedicated`. Forma (la que escribe el generador):
`E("dedicated", "cubierto por <tool>", "<familia>", tool="<tool>", cap="<CAP>")`.

| Comando | Tool | Familia | CAP |
|---|---|---|---|
| `system_health/info` | `ha_get_system_health` | `system_status` | CAP-043 |
| `subscribe_system_state` | `ha_get_system_state` | `system_status` | CAP-043 |
| `integration/setup_info` | `ha_list_integration_setup_times` | `system_status` | CAP-043 |
| `manifest/list` | `ha_list_integration_manifests` | `system_status` | CAP-043 |
| `manifest/get` | `ha_get_integration_manifest` | `system_status` | CAP-043 |
| `recorder/info` | `ha_get_recorder_info` | `recorder` | CAP-049 |
| `recorder/entity_options/get` | `ha_get_recorder_info` | `recorder` | CAP-049 |
| `recorder/validate_statistics` | `ha_validate_statistics` | `recorder` | CAP-049 |
| `recorder/get_statistics_metadata` | `ha_get_statistics_metadata` | `recorder` | CAP-049 |

Entradas `read` que se quedan `read` (vía T):

| Comando | Cambio | CAP |
|---|---|---|
| `logbook/get_action_calls` | `redact_extra=("code",)`; `example={"start_time": "2026-01-01T00:00:00+00:00", "end_time": "2026-01-01T06:00:00+00:00"}`; motivo: «auditoría de llamadas a acciones en un intervalo; los `code` de `service_data` (alarmas, cerraduras) salen tapados; solo lee» | CAP-058 |
| `network` | ninguno | CAP-068 |
| `network/url` | ninguno | CAP-068 |
| `http/config` | ninguno | CAP-068 |

Generador (`scripts/inventario/generar_tabla.py`): las nueve claves en
`_DEDICADAS_INICIALES` (bloque comentado «029: estado del sistema y
estadísticas»). La consulta del mapa para la clase A antes de la regla
«pendiente» es la de la 012 (research R-7).

## Cliente (`ha.py`)

`HAClient.ws_collect_subscription(payload: dict, *, terminado: Callable[[Any],
bool], timeout_seconds: float) -> tuple[list[Any], bool]`

- Reserva id, registra el future del `result` y la cola de eventos bajo
  `_ws_request_lock`, manda `{"id", **payload}`.
- Espera el `result` (dentro del plazo total); si es error de HA,
  `HAConnectionError(code=…)`.
- Acumula eventos en orden; para cuando `terminado(evento)` o vence el plazo
  total (`completo=False`).
- `finally`: quita el registro y llama a `_ws_unsubscribe(id)` siempre.
- WebSocket no disponible o cerrada a mitad: `HAConnectionError` sin código.

## Respuestas de las tools

Todas con `json.dumps(..., ensure_ascii=False)`, redactadas con
`redact_structure` + `redact_secrets` en los textos y al tope de
`response_max_bytes`.

### `ha_get_system_health`

```text
{
  "complete": bool,
  "domains": {
    "<dominio>": {"info": {"<clave>": <valor>}, "manage_url": "<ruta>"?}
  },
  "pending": ["<dominio>.<clave>", ...],   # sin valor al vencer el plazo
  "failed":  ["<dominio>.<clave>", ...],   # HA los dio por fallidos
  "truncated": bool,
  "omitted_domains": ["<dominio>", ...]    # solo si truncated
}
```

- Valor `{"type": "date", "value": iso}` → `iso`.
- Valor `{"type": "pending"}` sin actualización → `null` y en `pending`.
- Actualización `success: false` → `null` y en `failed`.
- Valor `{"type": "failed", "error": …}` de una clave, en el inicial o en una
  actualización con `success: true` (`hassio.healthy`/`supported` con el
  Supervisor «Unhealthy»/«Unsupported», `async_check_can_reach_url` sin
  llegar) → se deja tal cual y `<dominio>.<clave>` va en `failed` (T036).
- Valor `{"error": {"type": "failed", …}}` de un dominio entero (timeout del
  callback en HA) → se deja tal cual y el dominio va en `failed` como
  `<dominio>.*`.

### `ha_get_system_state`

```text
{
  "home_assistant_restart_required": bool,
  "home_assistant_restart_sources": [str],
  "home_assistant_restart_dismissed": bool,
  "host_reboot_required": bool,
  "host_reboot_dismissed": bool
}
```

### `ha_list_integration_setup_times`

```text
{"count": n, "items": [{"domain": str, "seconds": float}], "truncated": bool,
 "total": N, "total_seconds": float}
```

`truncated: true` si `limit` o el tope de bytes dejaron fuera alguna de las
que pasan `min_seconds` (que es un filtro, no un recorte).

### `ha_list_integration_manifests`

```text
{"count": n, "truncated": bool, "missing": [str],
 "items": [{"domain", "name", "integration_type", "iot_class",
            "quality_scale", "version", "is_built_in", "overwrites_built_in",
            "config_flow", "documentation",
            "_third_party_text"?: {"fields": [...], "warning": "..."}}]}
```

Campos ausentes en el manifiesto → `null`. `_third_party_text` solo si
`is_built_in` es falso; `fields`: `name`, `documentation`.

### `ha_get_integration_manifest`

El manifiesto completo de HA (con `is_built_in` y `overwrites_built_in`), más
`_third_party_text` (`fields`: `name`, `documentation`, `issue_tracker`,
`codeowners`) si no es de HA.

### `ha_validate_statistics`

```text
{"count": n, "truncated": bool, "by_type": {"<tipo>": k},
 "items": [{"statistic_id": str, "type": str, "data": {...}}]}
```

### `ha_get_statistics_metadata`

```text
{"count": n, "truncated": bool, "missing": [str],
 "items": [{"statistic_id", "name", "source", "has_mean", "mean_type",
            "has_sum", "statistics_unit_of_measurement",
            "display_unit_of_measurement", "unit_class"}]}
```

Se devuelve lo que da HA para cada id (sin quitar campos); la lista es la
de `async_list_statistic_ids`.

### `ha_get_recorder_info`

```text
{"recording": bool, "thread_running": bool, "backlog": int,
 "max_backlog": int, "migration_in_progress": bool,
 "migration_is_live": bool, "db_in_default_location": bool,
 "entity"?: {"entity_id": str, "recorded": bool,
             "recording_disabled_by": null | str}
           | {"entity_id": str, "error": "unsupported_by_ha_version", ...}}
```

## Errores

| Código | Cuándo |
|---|---|
| `invalid_argument` | argumento fuera de rango o con forma inválida (sin llamar a HA) |
| `domain_not_found` | `ha_get_system_health(domain=…)` con un dominio que no está |
| `integration_not_found` | `manifest/get` responde `not_found` |
| `not_found` | `ha_get_recorder_info(entity_id=…)` de una entidad que no existe |
| `recorder_not_loaded` | `unknown_command` en un comando del recorder (sin `recorder:` cargado) |
| `system_health_not_loaded` | `unknown_command` en `system_health/info` (sin `system_health:` cargado) |
| `unsupported_by_ha_version` | `unknown_command` en un comando de núcleo: `subscribe_system_state`, `integration/setup_info`, `manifest/*` (o en `entity`) |
| `response_too_large` | un manifiesto suelto o una salud de un solo dominio que no caben |
| `{"error": "<mensaje>"}` | fallo de conexión con Core, como el resto de tools |

Todo error lleva el detalle de HA pasado por `redact_secrets`.
