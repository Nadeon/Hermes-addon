# Modelo de datos: automatización asistida (017)

Formas de entrada y salida de las tools, entradas de la tabla, familias e
inventario del banco. Las firmas y anotaciones están en
[contracts/tools.md](contracts/tools.md).

## Sobre común de listas

`{"count": int, "items": [...], "truncated": bool}` ajustado a
`response_max_bytes` con `ajustar_lista_a_bytes` de `tools/_common.py`
(`count` es el total antes de recortar).

## Blueprints

### Elemento de `ha_list_blueprints`

```json
{
  "domain": "automation",
  "path": "homeassistant/motion_light.yaml",
  "name": "Motion-activated Light",
  "description": "…",
  "author": "…",
  "source_url": "https://…",
  "min_version": "2024.6.0",
  "inputs": ["motion_entity", "light_target", "no_motion_wait"]
}
```

Error de carga: `{"domain", "path", "error": "<redactado>"}`. Orden: dominio,
ruta. Envoltorio: sobre común más
`"_third_party_text": {"fields": ["name", "description", "author"], "warning": …}`.
`inputs` aplana las secciones de entradas de HA (`input: {sección: {input: {…}}}`).

### Vista previa de `ha_import_blueprint`

```json
{
  "action": "import_blueprint",
  "source_url": "https://example.com/blueprints/luz.yaml",
  "importer": "generic",
  "domain": "automation",
  "path": "example.com/luz.yaml",
  "full_path": "/config/blueprints/automation/example.com/luz.yaml",
  "exists": false,
  "used_by": null,
  "metadata": {"name": "…", "description": "…", "author": "…", "min_version": null},
  "inputs": [{"name": "motion_entity", "label": "…", "description": "…", "has_default": false}],
  "validation_errors": [],
  "content": "blueprint:\n  name: …",
  "content_bytes": 1234,
  "content_sha256": "<64 hex>",
  "content_redacted": false,
  "on_save": "Home Assistant re-serialises the YAML and adds source_url to its metadata; automations using it are not changed.",
  "_third_party_text": {"fields": ["metadata", "inputs", "content", "validation_errors"], "warning": "…"}
}
```

- `importer`: `community`, `github`, `gist`, `homeassistant_website` o
  `generic`, con los patrones de `importer.py` (informativo).
- `exists: true` (solo con `allow_override=true`; sin él, error) →
  `used_by` como en el borrado, y `on_save` añade que HA recargará a los que
  lo usan.
- Token: `create_confirmation_token("ha_import_blueprint", {"url", "path", "allow_override", "content_sha256"}, preview=…)`.
  `path` es la final, con `.yaml`.

### Vista previa de `ha_save_blueprint`

`{"action": "save_blueprint", "domain", "path", "full_path", "exists",
"used_by", "metadata", "inputs", "content_bytes", "content_sha256"}`; token
con `{"domain", "path", "yaml", "allow_override"}` y `omitibles=("yaml",)`.

### Vista previa de `ha_delete_blueprint`

```json
{
  "action": "delete_blueprint",
  "domain": "automation",
  "path": "example.com/luz.yaml",
  "full_path": "/config/blueprints/automation/example.com/luz.yaml",
  "metadata": {"name": "…", "source_url": "…"},
  "used_by": {"automation": [], "script": []},
  "effect": "Deletes the file. It can only be recovered from a backup."
}
```

Para `template`: `"used_by": null, "used_by_note": "Home Assistant does not expose which templates use a blueprint; it refuses the deletion if one does."`.

### `used_by`

`search/related` con `item_type` `automation_blueprint` o `script_blueprint` e
`item_id` = ruta → `{"automation": [entity_ids]}` o `{"script": [entity_ids]}`;
hasta 50 ids por tipo con `used_by_count` exacto (los recortados no cambian la
decisión: con uno basta para `blueprint_in_use`).

### `ha_preview_blueprint_substitution`

`{"domain", "path", "substituted_config": {…}, "saved": false}`; si no cabe,
`response_too_large` con el tamaño.

## Dispositivo

### Elemento de `ha_list_device_{triggers,conditions,actions}`

El diccionario de HA tal cual (es lo que se pega en la automatización), más,
con `include_capabilities=true`:

- `"capabilities": {"extra_fields": [...]}`, o
- `"capabilities_error": "<redactado>"`.

Envoltorio: sobre común más `"device_id"` y, si se pidieron,
`"capabilities_truncated": bool` (más de 50 elementos).

## Targets

### `target` de entrada

```json
{"entity_id": "light.salon", "area_id": ["salon"], "exclude": {"label_id": "nocturna"}}
```

Claves: `entity_id`, `device_id`, `area_id`, `floor_id`, `label_id` (texto o
lista de textos no vacíos) y `exclude` (mismas claves). Al menos una clave
fuera de `exclude`.

### `ha_resolve_target`

`{"entities": [...], "devices": [...], "areas": [...], "missing": {"devices": [], "areas": [], "floors": [], "labels": []}}`,
listas ordenadas. Si no cabe, se recortan las listas con
`recortar_a_bytes` y `truncated: true` con los recuentos.

### `ha_explain_target`

`{"includes": [{"type", "id", "entities", "referenced_areas", "referenced_devices"}], "excludes": [{"type", "id", "removed": [...]}]}`
como HA, con el mismo recorte.

### `ha_list_{triggers,conditions,actions}_for_target`

Sobre común de nombres ordenados (`["light.turned_on", …]`).

## Espera de trigger

Respuestas de `ha_wait_for_trigger`:

| Caso | Forma |
|---|---|
| disparo | `{"matched": true, "trigger": {…}, "waited_seconds": n}` (+ `"truncated": true` si se quitaron `from_state`/`to_state`) |
| plazo | `{"matched": false, "reason": "timeout", "waited_seconds": n}` |
| cancelada | `{"matched": false, "reason": "cancelled", "waited_seconds": n}` |
| reconexión | `{"matched": false, "reason": "ws_reconnect", "waited_seconds": n, "note": …}` |
| error | `{"error": "invalid_trigger", "detail": …}`, `{"error": "trigger_not_allowed", "detail": …, "hint": …}` y los de `ha_wait_for_event` (`too_many_waits`, plazo) |

Entrada de `ha_list_active_waits` para una espera de trigger:
`{"wait_id", "kind": "trigger", "trigger_platform", "started_at_iso", "timeout_at_iso", "elapsed_seconds"}`.
Las de eventos no cambian.

## Validación al guardar

Vista previa de `ha_create_or_update_automation` y `_script`: la de hoy más

```json
"validation": {"validated": ["triggers", "actions"], "not_validated": ["alias", "mode"], "via_blueprint": null}
```

(`via_blueprint`: la ruta si se sustituyó). Errores sin token:

| Código | Contenido |
|---|---|
| `invalid_config` | `{"parts": {"triggers": "<error redactado>"}, "hint": …}` |
| `blueprint_substitution_failed` | `{"detail": "<redactado>", "blueprint": "<ruta>"}` |
| `validation_unavailable` | `{"detail": "<redactado>", "hint": "…try again when Home Assistant responds"}` |

## Familias (`tool_families.py`)

| Familia | Desde | Desactivable | Módulos |
|---|---|---|---|
| `blueprints` | 1.2.0 | sí | `blueprints` |
| `automation_assist` | 1.2.0 | sí | `device_automation`, `targets`, `wait_for_trigger` |

## Tabla (`command_table.py`)

| Comando | Tool | Familia | CAP |
|---|---|---|---|
| `blueprint/list` | `ha_list_blueprints` | `blueprints` | CAP-046 |
| `blueprint/import` | `ha_import_blueprint` | `blueprints` | CAP-046 |
| `blueprint/save` | `ha_save_blueprint` | `blueprints` | CAP-046 |
| `blueprint/delete` | `ha_delete_blueprint` | `blueprints` | CAP-046 |
| `blueprint/substitute` | `ha_preview_blueprint_substitution` | `blueprints` | CAP-046 |
| `device_automation/trigger/list` | `ha_list_device_triggers` | `automation_assist` | CAP-051 |
| `device_automation/trigger/capabilities` | `ha_list_device_triggers` | `automation_assist` | CAP-051 |
| `device_automation/condition/list` | `ha_list_device_conditions` | `automation_assist` | CAP-051 |
| `device_automation/condition/capabilities` | `ha_list_device_conditions` | `automation_assist` | CAP-051 |
| `device_automation/action/list` | `ha_list_device_actions` | `automation_assist` | CAP-051 |
| `device_automation/action/capabilities` | `ha_list_device_actions` | `automation_assist` | CAP-051 |
| `extract_from_target` | `ha_resolve_target` | `automation_assist` | CAP-052 |
| `explain_target` | `ha_explain_target` | `automation_assist` | CAP-052 |
| `get_triggers_for_target` | `ha_list_triggers_for_target` | `automation_assist` | CAP-052 |
| `get_conditions_for_target` | `ha_list_conditions_for_target` | `automation_assist` | CAP-052 |
| `get_services_for_target` | `ha_list_actions_for_target` | `automation_assist` | CAP-052 |
| `subscribe_trigger` | `ha_wait_for_trigger` | `automation_assist` | CAP-038 |

Forma: `E("dedicated", "cubierto por <tool>", "<familia>", tool="<tool>", cap="<CAP>")`.
Tramo A: `list`, `save`, `delete`, `substitute`; B: `import`; C: las 11 de
dispositivo y targets; D: `subscribe_trigger` (con la fila del inventario).

## Inventario del banco (`tests/banco/cobertura_017.py`)

```python
PROBADAS_017: frozenset[str] = frozenset({
    "ha_save_blueprint", "ha_delete_blueprint",   # tramo A
    "ha_import_blueprint",                        # tramo B
})
NO_EJECUTABLES_017: dict[str, str] = {}
```

Sumada a la unión de `tests/test_banco_cobertura_escrituras.py`, a la de
`test_listas_disjuntas` y a `TOOLS_EXIGIDAS_DEL_JOB` de
`tests/banco/cobertura_escrituras.py` (la que usa el plugin de
`tests/banco/obligatorio.py`). Filas de la matriz de pruebas
(`docs/HOJA-DE-RUTA.md`): las tres con `banco de Core`, `ok`; la de
`ha_import_blueprint` con la nota «importador genérico desde `/local/` del
banco; GitHub, gist y foro sin probar (pendiente manual)».
