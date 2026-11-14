# Contratos de las tools nuevas (1.1.0, spec 005)

Hermes expone tools MCP; su contrato es el nombre, los parámetros, las
anotaciones y la forma de la respuesta. Las descripciones que ve el cliente
van en inglés; los ejemplos usan marcadores, no datos reales.

Convenciones comunes:

- Las `ha_*` devuelven JSON serializado (`-> object`, como `registry_area.py`); las `sv_*`, un diccionario.
- Error de Home Assistant sin más detalle: `{"error": "<mensaje>"}`; con código conocido se traduce como se indica en cada tool.
- Error de versión (común): `{"error": "ha_version_unsupported", "feature": "<qué>", "required": "<x.y.z>", "current": "<x.y.z>|null"}`.
- Validación: `{"error": "invalid_argument", "field": "<campo>", "detail": "<regla>"}` sin llamar a Home Assistant.
- Identificadores: `{"error": "invalid_identifier", "detail": "…"}`.
- Confirmación: sin token → `{"confirmation_token": "…", "preview": {…}}`; con token inválido → `{"error": "<motivo>"}`; con token válido → resultado.

## Resumen y anotaciones

| Tool | readOnly | destructive | idempotent | Token | Mínimo HA |
|---|:-:|:-:|:-:|:-:|---|
| `ha_list_floors` | ✓ | | ✓ | | — |
| `ha_create_floor` | | | ✗ | | — |
| `ha_update_floor` | | ✓ | ✓ | ✓ | — |
| `ha_delete_floor` | | ✓ | ✓ | ✓ | — |
| `ha_list_labels` | ✓ | | ✓ | | — |
| `ha_create_label` | | | ✗ | | — |
| `ha_update_label` | | ✓ | ✓ | ✓ | — |
| `ha_delete_label` | | ✓ | ✓ | ✓ | — |
| `ha_list_categories` | ✓ | | ✓ | | — |
| `ha_create_category` | | | ✗ | | — |
| `ha_update_category` | | ✓ | ✓ | ✓ | — |
| `ha_delete_category` | | ✓ | ✓ | ✓ | — |
| `ha_list_repairs` | ✓ | | ✓ | | — |
| `ha_ignore_repair` | | ✓ | ✓ | ✓ (si cambia) | — |
| `ha_list_traces` | ✓ | | ✓ | | — |
| `ha_get_trace` | ✓ | | ✓ | | — |
| `ha_search_related` | ✓ | | ✓ | | 2026.10 solo con `include_disabled_entities` |
| `sv_get_resolution` | ✓ | | ✓ | | — |
| `sv_dismiss_resolution_issue` | | ✓ | ✓ | ✓ | — |
| `sv_dismiss_resolution_suggestion` | | ✓ | ✓ | ✓ | — |
| `ha_list_backups` | ✓ | | ✓ | | 2025.1 |
| `ha_get_backup` | ✓ | | ✓ | | 2025.1 |
| `ha_get_backup_config` | ✓ | | ✓ | | 2025.1 |

`openWorldHint` es falso en todas: ninguna sale de la instalación.

---

## Plantas

```text
ha_list_floors()
ha_create_floor(name: str, level: int | None = None, icon: str | None = None, aliases: list[str] | None = None)
ha_update_floor(floor_id: str, updates: dict, confirmation_token: str | None = None)
ha_delete_floor(floor_id: str, confirmation_token: str | None = None)
```

- `ha_list_floors` → `{"count": n, "floors": [{"floor_id", "name", "level", "icon", "aliases"}, …]}`.
- `ha_create_floor` → la entrada creada (`floor_id` generado por HA). Nombre duplicado → `{"error": "<mensaje de HA>"}`.
- `ha_update_floor`: `updates` admite `name`, `level`, `icon`, `aliases`; otra clave → `invalid_argument`; vacío → `{"error": "updates is empty"}`. Preview: `{"floor_id", "current": {…}, "proposed_changes": {…}}`. Con token: `{"result": "ok", …entrada…}`.
- `ha_delete_floor` preview:

```json
{
  "floor_id": "planta_baja",
  "current": {"floor_id": "planta_baja", "name": "Planta baja", "level": 0},
  "impact": {
    "assignments_removed": {"areas": {"count": 2, "ids": ["salon", "cocina"], "truncated": false}},
    "references_unresolved": {"automation": {"count": 1, "ids": ["automation.luces_planta_baja"]},
                              "script": {"count": 0, "ids": []}},
    "related_unaffected": {"automation": {"count": 3, "ids": ["automation.luz_cocina", "…"]},
                           "script": {"count": 0, "ids": []}, "scene": {"count": 1, "ids": ["scene.cena"]}}
  },
  "warning": "Deleting this floor sets floor_id to null on 2 areas. 1 automation and 0 scripts use this floor as a target and will no longer match it; Home Assistant does not edit them. 3 automations, 0 scripts and 1 scene are only related (through its areas, devices or entities) and keep working. References written inside templates are not detected."
}
```

`references_unresolved` sale de leer la configuración (`automation/config`, `script/config`) de cada automatización y script que devuelve `search/related`: cuenta si usa `floor_id` con esta planta en cualquier nivel (acciones, disparadores, condiciones); si es un blueprint, si el id aparece como valor de alguna entrada. `not_found` al leerla = no está cargada → `related_unaffected`. Cualquier otro fallo → `preview_unavailable`. Las escenas nunca apuntan a una planta.

Errores sin token: `not_found`, `preview_unavailable` (con `detail`: qué lectura falló). Con token: `{"result": "ok"}`.

## Etiquetas

```text
ha_list_labels()
ha_create_label(name: str, color: str | None = None, icon: str | None = None, description: str | None = None)
ha_update_label(label_id: str, updates: dict, confirmation_token: str | None = None)
ha_delete_label(label_id: str, confirmation_token: str | None = None)
```

- `updates` admite `name`, `color`, `icon`, `description`.
- `color`: `primary, accent, disabled, red, pink, purple, deep-purple, indigo, blue, light-blue, cyan, teal, green, light-green, lime, yellow, amber, orange, deep-orange, brown, light-grey, grey, dark-grey, blue-grey, black, white` o `#rrggbb`.
- `ha_delete_label` preview: `impact.assignments_removed` con `areas`, `devices` y `entities`; `impact.references_unresolved` con `automation` y `script` (las que usan `label_id` de destino, mismo método que en plantas); `impact.related_unaffected` con `automation`, `script` y `scene` (las que solo llevan la etiqueta o están relacionadas: siguen funcionando); `warning` con los recuentos.

## Categorías

```text
ha_list_categories(scope: str)
ha_create_category(scope: str, name: str, icon: str | None = None)
ha_update_category(scope: str, category_id: str, updates: dict, confirmation_token: str | None = None)
ha_delete_category(scope: str, category_id: str, confirmation_token: str | None = None)
```

- `scope` ∈ `automation`, `script`, `scene`, `helpers`; otro → `invalid_argument` con la lista.
- `updates` admite `name`, `icon`.
- `ha_delete_category` preview: `impact.assignments_removed.entities` (entidades con `categories[scope] == category_id`); sin `references_unresolved` (las categorías no se usan como destino).

---

## Repairs

```text
ha_list_repairs(include_ignored: bool = False, domain: str | None = None, severity: str | None = None)
ha_ignore_repair(domain: str, issue_id: str, ignore: bool = True, confirmation_token: str | None = None)
```

`ha_list_repairs`:

```json
{
  "count": 1,
  "issues": [{
    "domain": "<integración>", "issue_id": "<id>", "issue_domain": "<dominio>",
    "severity": "error", "is_fixable": false, "breaks_in_ha_version": "2027.3.0",
    "created": "2026-11-01T10:00:00+00:00", "ignored": false, "dismissed_version": null,
    "translation_key": "<clave>", "translation_placeholders": {"url": "https://***:***@example.invalid"},
    "learn_more_url": "https://www.home-assistant.io/…"
  }]
}
```

`severity` ∈ `critical`, `error`, `warning`; otra → `invalid_argument`.

`ha_ignore_repair` sin token: `not_found` | `{"result": "unchanged", "ignored": <bool>}` | preview:

```json
{"domain": "…", "issue_id": "…", "severity": "warning", "breaks_in_ha_version": null,
 "action": "ignore",
 "effect": "Hides this issue from Repairs. Reversible: call again with ignore=false."}
```

Con token: `{"result": "ok", "ignored": true}`.

---

## Trazas

```text
ha_list_traces(domain: str, item_id: str | None = None, entity_id: str | None = None, limit: int = 10)
ha_get_trace(domain: str, run_id: str, item_id: str | None = None, entity_id: str | None = None, detail: str = "summary")
```

- `domain` ∈ `automation`, `script`; `limit` 1–50; `detail` ∈ `summary`, `full`.
- `item_id` y `entity_id` son excluyentes; en `ha_get_trace` uno de los dos es obligatorio. `entity_id` de otro dominio → `invalid_argument`; sin entrada en el registro → `{"error": "not_found", "entity_id": …}`.

`ha_list_traces` → `{"count": n, "total": m, "traces": [{"run_id", "item_id", "state", "script_execution", "start", "finish", "last_step", "trigger", "error", "not_triggered"}]}` (más recientes primero; `trigger` y `error` ≤ 300 caracteres y redactados).

`ha_get_trace` (`summary`):

```json
{
  "run_id": "…", "domain": "automation", "item_id": "…",
  "state": "stopped", "script_execution": "error",
  "start": "…", "finish": "…", "last_step": "action/1",
  "trigger": "state of binary_sensor.puerta", "error": "…",
  "steps": [{"path": "trigger/0", "timestamp": "…", "result": "{…≤500…}", "error": null, "child_id": null}],
  "truncated": false
}
```

`full` añade `steps[].changed_variables` y `config`. Si no cabe en `min(65536, response_max_bytes)`: `"truncated": true, "omitted": {"changed_variables_steps": n, "config": bool, "steps": n}`. `run_id` inexistente (código `not_found`) → `{"error": "not_found", "run_id": …}`.

---

## Relaciones

```text
ha_search_related(item_type: str, item_id: str, include_disabled_entities: bool = False)
```

`item_type` ∈ `area, automation, automation_blueprint, config_entry, device, entity, floor, group, integration, label, person, scene, script, script_blueprint`.

```json
{"item_type": "entity", "item_id": "light.salon",
 "related": {"automation": ["automation.x"], "scene": ["scene.y"], "area": ["salon"]},
 "counts": {"automation": 1, "scene": 1, "area": 1}, "truncated": false}
```

Como mucho 200 ids por tipo; si la respuesta pasa de `response_max_bytes`, el tope baja por igual para todos los tipos (100, 50, 20, 10, 5, 1, 0) hasta que quepa, con `truncated: true` y `counts` exactos (revisión de 1.1.0, M-1). `include_disabled_entities=true` con HA < 2026.10 → `ha_version_unsupported` (`feature: "include_disabled_entities"`, `required: "2026.10.0"`).

---

## Resolución del Supervisor

```text
sv_get_resolution()
sv_dismiss_resolution_issue(issue_uuid: str, confirmation_token: str | None = None)
sv_dismiss_resolution_suggestion(suggestion_uuid: str, confirmation_token: str | None = None)
```

`sv_get_resolution` → `{"unsupported": […], "unhealthy": […], "issues": [{"uuid", "type", "context", "reference", "reference_extra"}], "suggestions": [{"uuid", "type", "context", "reference", "reference_extra", "auto"}], "checks": [{"slug", "enabled"}]}`.

Preview de `sv_dismiss_resolution_suggestion`:

```json
{"suggestion_uuid": "<uuid>", "type": "clear_full_backup", "context": "system", "reference": null,
 "action": "dismiss",
 "effect": "Removes this suggestion from the Supervisor without applying it. It may come back on the next check if the condition persists. Hermes never applies Supervisor suggestions."}
```

Sin token: `not_found` si el uuid no está en `/resolution/info`. Con token: `{"result": "ok"}`.

---

## Backups de Home Assistant

```text
ha_list_backups(limit: int = 20)
ha_get_backup(backup_id: str)
ha_get_backup_config()
```

- Mínimo 2025.1.0 (`feature: "backup"`). Versión desconocida → se llama; `unknown_command` → `{"error": "backup_integration_unavailable", "detail": "The Home Assistant backup integration is not available on this installation."}`.
- `ha_list_backups` → `{"count": n, "total": m, "truncated": bool, "backups": [backup…], "last_attempted_automatic_backup", "last_completed_automatic_backup", "next_automatic_backup", "state", "agent_errors": {agent_id: "<mensaje redactado>"}}`. `limit` 1–100. Si la respuesta pasa de `response_max_bytes`, se quitan los backups más antiguos y `truncated: true` (revisión de 1.1.0, M-1). Con HA 2025.1.x, que da `agent_ids` y `protected`/`size` en el nivel superior, `agents` se construye a partir de ellos (B-4).
- `ha_get_backup` → `{"backup": backup, "agent_errors": {…}}`; `backup: null` → `{"error": "not_found", "backup_id": …}`.
- `ha_get_backup_config` → `{"config": config}` con `create_backup.password_set` y **sin** `password`.

`backup` y `config`: listas blancas de data-model.md.

---

## Cambios en tools existentes

| Tool | Cambio |
|---|---|
| `sv_create_safety_backup` | Anota el backup lanzado en la anotación de Hermes. Su descripción dice que entra en la retención `safety_backup_keep`, que se aplica tras cada safety backup automático correcto. Respuesta sin cambios. |
| `fs_write_file` y demás escrituras en `/config` | Sin cambios de firma ni de respuesta. Con `safety_backup_enabled`, tras un safety backup automático correcto se aplica la retención; su resultado solo va al log. |

## Opción nueva

| Opción | Schema | Defecto | Efecto |
|---|---|---|---|
| `safety_backup_keep` | `int(0,50)?` | `3` | Safety backups de Hermes que se conservan tras cada safety backup automático correcto. 0 = no podar. Nunca toca backups que Hermes no haya anotado y confirmado. |
