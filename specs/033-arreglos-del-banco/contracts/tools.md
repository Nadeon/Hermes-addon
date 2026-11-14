# Contratos: respuestas que cambian en la 033

Formas JSON de las tools tocadas. Lo que no aparece aquí no cambia respecto a
la 1.1.2. Los textos de `message`, `reason` y `hint` van en inglés (como el
resto de mensajes al cliente); su redacción exacta es del implementador, el
contenido mínimo es el que se indica.

## `ha_run_script(script_id, variables=None, confirmation_token=None)` y `ha_trigger_automation(automation_id, variables=None, confirmation_token=None)` (FR-001, FR-002)

Solo cambia el camino de una entidad restringida. Argumentos atados al token:

```json
{"entity_id": "script.ficticio", "service": "script.turn_on", "variables": {"modo": "suave"}}
```

`variables` vale `null` si no se pasó. Vista previa (sin token):

```json
{
  "confirmation_token": "<uuid>",
  "expires_in_seconds": 60,
  "preview": {
    "action": "script.turn_on",
    "entity_id": "script.ficticio",
    "variables": {"modo": "suave"},
    "reason": "Esta entidad está restringida: …"
  }
}
```

Confirmación con argumentos distintos: el error de token que no coincide de
siempre (`validate_confirmation_token`), sin llamada a HA. Confirmación
correcta: la respuesta de HA, como hoy.

## `ha_reload_counters(confirmation_token=None)` (FR-004)

Siempre, con o sin token, sin llamar a HA ni emitir o gastar tokens:

```json
{
  "error": "not_supported",
  "message": "Home Assistant has no counter.reload service: …",
  "hint": "Counters created from the UI or with Hermes apply on save; YAML counters are read when Home Assistant restarts.",
  "_deprecated": "ha_reload_counters is deprecated and will be removed in 1.3.0; …"
}
```

## `ha_wait_for_event(event_type, filters=None, timeout_seconds=30)` (FR-005)

Esquema publicado: propiedades `event_type`, `filters`, `timeout_seconds`;
obligatorio solo `event_type`. Un `ctx` recibido del cliente se ignora.
Respuestas sin cambios. Durante la espera, notificaciones de progreso
`progress`/`total`/`message` cada intervalo de keepalive.

## `ha_create_scene_from_current(scene_id, entity_ids, name=None, confirmation_token=None)` (FR-006)

| Caso | Respuesta | ¿Llama a HA? |
|---|---|---|
| `name` no nulo | `{"error": "name_not_supported", "message": "scene.create does not accept a name …", "hint": "use ha_create_or_update_scene for a named, persistent scene", "_deprecated": "the name argument … removed in 1.3.0"}` | no |
| alguna entidad no existe | `{"error": "entity_not_found", "entity_ids": ["light.inexistente"]}` | no (solo lecturas) |
| la escena existe y no es temporal | `{"error": "scene_exists", "scene_id": "scene.fiesta", "message": "… Home Assistant would keep it and ignore the request …"}` | no (solo lecturas) |
| la escena existe y es temporal, sin token | vista previa (abajo) | no (solo lecturas) |
| no existe, o temporal con token válido | `{"result": "ok", "scene_id": "scene.fiesta", "entity_ids": [...], "replaced": false|true, "temporary": true, "ha_response": <respuesta de HA de la 1.1.2>}` | sí |
| tras `scene.create` la escena no tiene esas entidades | `{"error": "scene_not_created", "scene_id": "scene.fiesta", "seen_entity_ids": [...] | null}` | sí |

Vista previa del reemplazo:

```json
{
  "confirmation_token": "<uuid>",
  "expires_in_seconds": 60,
  "preview": {
    "action": "scene.create",
    "scene_id": "scene.fiesta",
    "current_entities": ["light.salon"],
    "new_entities": ["light.salon", "light.cocina"],
    "effect": "Replaces the temporary scene. Temporary scenes are lost when Home Assistant restarts or scenes are reloaded."
  }
}
```

Argumentos atados: `{"scene_id": "<object_id normalizado>", "entity_ids": [...]}`.
Hoy la respuesta de éxito es la de `call_service` de HA; la nueva la conserva
entera en `ha_response` y añade lo comprobado.

Anotaciones: `readOnlyHint=false`, `destructiveHint=true`,
`idempotentHint=false`, `openWorldHint=false`.

## `ha_get_config_entry_options(entry_id)` (FR-008)

Entry existente:

```json
{
  "error": "not_supported",
  "entry_id": "<id>",
  "domain": "demo",
  "title": "Demo",
  "supports_options": true,
  "message": "Home Assistant does not expose config entry options through its API.",
  "hint": "Start ha_start_options_flow to see the form (many integrations prefill the current values), then ha_abort_config_entry_flow.",
  "_deprecated": "ha_get_config_entry_options is deprecated and will be removed in 1.3.0; …"
}
```

La clave `options` desaparece. `not_found` y los errores de conexión, como en
la 1.1.2. Como hoy, la respuesta es una cadena JSON.

## `ha_increment_counter(entity_id, amount=None)` y `ha_decrement_counter(entity_id, amount=None)` (FR-009)

Sin `amount`: sin cambios. Con `amount` y valor resultante no válido, sin
llamar a `set_value`:

```json
{
  "error": "invalid_amount",
  "reason": "not_multiple_of_step",
  "entity_id": "counter.ficticio",
  "current": 5,
  "target": 8,
  "step": 3,
  "minimum": null,
  "maximum": null,
  "hint": "Home Assistant only accepts values that are multiples of step and within minimum/maximum. Call without amount to move one step, or use ha_set_counter_value with a valid value."
}
```

`reason` es `not_multiple_of_step` o `out_of_range`. Con valor válido, la
respuesta de HA de siempre.
