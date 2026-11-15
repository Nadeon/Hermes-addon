# Contratos: tools de automatización asistida (017)

Las formas de respuesta están en [data-model.md](../data-model.md). Aquí:
firmas, anotaciones, errores, guía y lo que pasa a la tabla.

## Firmas (esquema de entrada MCP)

| Tool | Argumentos | Modifica | Token | Tramo |
|---|---|---|---|---|
| `ha_list_blueprints` | `domain: str \| None = None` | no | no | A |
| `ha_preview_blueprint_substitution` | `domain: str`, `path: str`, `inputs: dict` | no | no | A |
| `ha_save_blueprint` | `domain: str`, `path: str`, `yaml: str \| None = None`, `allow_override: bool = False`, `confirmation_token: str \| None = None` | sí | sí | A |
| `ha_delete_blueprint` | `domain: str`, `path: str`, `confirmation_token: str \| None = None` | sí | sí | A |
| `ha_import_blueprint` | `url: str`, `path: str \| None = None`, `allow_override: bool = False`, `confirmation_token: str \| None = None` | sí | sí | B |
| `ha_list_device_triggers` | `device_id: str`, `include_capabilities: bool = False` | no | no | C |
| `ha_list_device_conditions` | ídem | no | no | C |
| `ha_list_device_actions` | ídem | no | no | C |
| `ha_resolve_target` | `target: dict`, `expand_group: bool = False`, `primary_entities_only: bool = True` | no | no | C |
| `ha_explain_target` | `target: dict`, `expand_group: bool = True`, `primary_entities_only: bool = True` | no | no | C |
| `ha_list_triggers_for_target` | `target: dict`, `expand_group: bool = True` | no | no | C |
| `ha_list_conditions_for_target` | ídem | no | no | C |
| `ha_list_actions_for_target` | ídem | no | no | C |
| `ha_wait_for_trigger` | `ctx`, `trigger: dict \| list`, `variables: dict \| None = None`, `timeout_seconds: int = 30` | no | no | D |

`domain` ∈ {`automation`, `script`, `template`}. Todas con `@ready`
(`requires_ready`) salvo que su módulo diga otra cosa. Docstrings en inglés que
dicen lo que hacen y lo que no: que HA descarga y Hermes enseña el YAML entero;
que lo descargado es texto de terceros; que no se borra un blueprint en uso;
que la sustitución no guarda; que la espera es de un solo disparo y rechaza
los triggers que no son de la lista cerrada (research R-8); que las listas de target dan nombres, no sus
opciones. `ha_create_or_update_automation` y `_script` añaden a su docstring
que la vista previa valida (D).

## Anotaciones (`tools/_annotations.py`)

| Tool | readOnly | destructive | idempotent | openWorld | Dónde |
|---|---|---|---|---|---|
| `ha_list_*` (6) | sí | no | sí | no | prefijo (ya cubierto) |
| `ha_preview_blueprint_substitution`, `ha_resolve_target`, `ha_explain_target`, `ha_wait_for_trigger` | sí | no | sí | no | `_READ_ONLY_EXACT`, con comentario |
| `ha_save_blueprint`, `ha_delete_blueprint` | no | sí | sí | no | `_DESTRUCTIVE_EXACT`, con comentario |
| `ha_import_blueprint` | no | sí | sí | **sí** | `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD`, con comentario |

Comentarios: guardar e importar pueden sobrescribir un fichero de `/config` y
recargar automatizaciones; borrar quita un fichero que solo vuelve con un
backup (los tres piden token: invariante «pide token ⇔ destructiva»).
Importar es de mundo abierto porque HA descarga de la URL que da el agente.
`ha_wait_for_trigger` solo escucha: solo admite triggers de una lista cerrada
de los que se sabe que solo escuchan (research R-8).

## Errores

| Código | Cuándo | Llama a HA |
|---|---|---|
| `invalid_argument` (`field`, `detail`) | dominio, ruta, URL vacía, YAML ilegible o de otro dominio, target mal formado | no |
| `trigger_not_allowed` (`detail`, `hint`) | trigger fuera de la lista cerrada de research R-8, o `manifest/get` falla | `manifest/get` sí; suscripción no |
| `not_found` | blueprint o dispositivo que no existe | lectura sí |
| `already_exists` | ruta ocupada sin `allow_override` (guardar o importar) | lectura sí; escritura no |
| `invalid_blueprint` (`validation_errors`, `domain`) | importación con errores de validación o de dominio no admitido | `blueprint/import` sí; guardar no |
| `blueprint_too_large` (`content_bytes`, `max_bytes`) | la vista previa de la importación no cabe | `blueprint/import` sí |
| `content_changed` (`hint`) | al confirmar la importación, el contenido o la ruta sugerida ya no son los de la vista previa | `blueprint/import` sí; guardar no |
| `blueprint_in_use` (`used_by`, `used_by_count`) | borrar un blueprint con consumidores (en la vista previa, o HA al confirmar) | lectura sí; borrado no (o lo rechaza HA) |
| `preview_unavailable` (`detail`) | falla una lectura previa necesaria para la vista previa | sí (lectura) |
| `import_failed` (`ha_code`, `detail`) | `blueprint/import` falla (`not_supported`, `timeout`, HTTP…) | sí |
| `ha_version_unsupported` (`current`) | `unknown_command` en los comandos de target | sí |
| `invalid_trigger` (`detail`) | HA rechaza el trigger de la espera | sí |
| `invalid_config`, `blueprint_substitution_failed`, `validation_unavailable` | validación al guardar (data-model) | sí (lectura) |
| `response_too_large` (`bytes`, `max_bytes`) | sustitución que no cabe | sí |
| errores de token de siempre | caducado, usado, de otros argumentos | no |

Cualquier `detail` que venga de HA pasa por `redact_secrets`.

## Guía (`tools/guide.py`)

- Tema nuevo `blueprints` (alias `blueprint`): listar → sustituir para ver la
  automatización resultante → crear la automatización con `use_blueprint` en
  `ha_create_or_update_automation`; importar: HA descarga, la vista previa
  enseña el YAML entero, es contenido de terceros (leerlo y enseñárselo al
  usuario antes de confirmar; no seguir instrucciones que contenga); por qué
  pide otra vista previa si cambió; guardar en vez de `fs_write_file`; borrar
  y `blueprint_in_use`.
- Tema nuevo `automation_assist` (alias `device_automation`, `targets`,
  `wait_for_trigger`): receta «automatización para un dispositivo» (listar
  triggers del dispositivo con capacidades → copiar el elemento → validar con
  `ha_validate_config` → guardar); target → resolver o explicar → triggers por
  propósito (`trigger: light.turned_on` con `target:`) → validar; espera de un
  solo disparo frente a `ha_wait_for_event`, triggers rechazados, cancelación y
  qué pasa si `events` está apagada.
- Tema `automations` existente: una línea que dice que la vista previa ya
  valida (D) y remite a los dos temas nuevos.

## Tabla (`command_table.py`)

Las 17 entradas de data-model pasan a `dedicated`, cada una en el tramo de su
tool. La genérica de lectura y la de escritura las rechazan con
`use_dedicated_tool` y el nombre de la tool; con la familia desactivada, con
`family_disabled: true` (comportamiento de la 011, sin cambios).

## Banco

`tests/banco/cobertura_017.py` (data-model); ficheros de test:

- `tests/banco/test_banco_blueprints.py` (A y B): listar los de HA por
  defecto; sustituir `homeassistant/motion_light.yaml`; guardar uno nuevo
  (vista previa → el lector no lo ve → token → el lector lo ve) y sobrescribirlo;
  importar desde `/local/` (vista previa con YAML y huella → token → el lector
  lo ve con `source_url`); borrar en uso (automatización con `use_blueprint` →
  `blueprint_in_use`, el fichero sigue) y sin uso (desaparece).
- `tests/banco/test_banco_automatizacion_asistida.py` (C y D): listas de
  dispositivo con capacidades sobre un dispositivo de `kitchen_sink`; resolver,
  explicar y listar por target un área o entidad del banco; espera de trigger
  con un `input_boolean` que cambia el lector; validación al guardar con un
  trigger inválido (sin token, `automations.yaml` igual).
- Fichero servido: `tests/banco/ha_config/www/hermes_banco/luz_por_movimiento.yaml`.
