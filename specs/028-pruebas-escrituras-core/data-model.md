# Modelo de datos: pruebas de las escrituras de Core en el banco (spec 028)

No hay datos persistentes nuevos en Hermes. Lo que sigue son las piezas que la
028 añade al banco de la 010 y sus reglas. Las de la 010 (variables del banco,
entorno, credenciales, Supervisor simulado) no cambian:
[data-model de la 010](../010-banco-de-pruebas-core/data-model.md).

## Inventario de escrituras (`tests/banco/cobertura_escrituras.py`)

| Campo | Tipo | Regla |
|---|---|---|
| `PROBADAS_028` | frozenset | las tools de la tabla de abajo que ya se ejecutan en el banco (26 tras el tramo A, 53 tras el B) |
| `NO_EJECUTABLES_028` | dict tool → motivo | `ha_*` que no se pueden ejecutar en el banco; vacío hoy |
| `FUERA_DEL_BANCO` | dict tool → motivo | las 5 `fs_*` y las 19 `sv_*` de la tabla de exclusiones; solo prefijos `fs_` y `sv_` |
| `PENDIENTES_TRAMO_B` | dict tool → motivo | solo entre el tramo A y el B: las 27 del tramo B; el tramo B lo vacía y lo borra |

**Invariante** (FR-003; lo comprueba `tests/test_banco_cobertura_escrituras.py`):

```
modifican(registro de producción)
  = cobertura.PROBADAS_EN_BANCO ∪ cobertura.NO_EJECUTABLES      (010, 47)
  ∪ PROBADAS_028 ∪ NO_EJECUTABLES_028 ∪ PENDIENTES_TRAMO_B       (028, 53)
  ∪ FUERA_DEL_BANCO                                              (24)
```

- `modifican(…)` = tools del registro de `_build_mcp(HermesConfig(…), MagicMock())`
  con `classify(nombre).read_only_hint` falso.
- Las partes son disjuntas dos a dos.
- `FUERA_DEL_BANCO` solo tiene nombres `fs_*` o `sv_*`.
- Ningún motivo vacío.
- `|PROBADAS_028 ∪ NO_EJECUTABLES_028 ∪ PENDIENTES_TRAMO_B| = 53`.
- Cada nombre de `PROBADAS_028` aparece entre comillas en algún
  `tests/banco/test_banco_escrituras_*.py`.

## Configuración de HA del banco (`tests/banco/ha_config/`)

| Fichero | Cambio | Tramo |
|---|---|---|
| `configuration.yaml` | `automation: !include automations.yaml`, `script: !include scripts.yaml`, `scene: !include scenes.yaml`, `frontend:` | A |
| `automations.yaml` | nuevo, `[]` | A |
| `scripts.yaml` | nuevo, `{}` | A |
| `scenes.yaml` | nuevo, `[]` | A |
| `configuration.yaml` | `kitchen_sink:` | B |

## Lector (`tests/banco/lector.py`, ampliación)

| Operación | Cómo |
|---|---|
| `comando(mensaje)` | cualquier comando WebSocket; devuelve `result` o lanza `ErrorCore` |
| `rest(metodo, ruta, cuerpo=None)` | REST directo a Core con el token de larga duración; devuelve `(estado, cuerpo)` |

Las operaciones existentes no cambian.

## Recursos compartidos de prueba

| Recurso | Quién lo crea | Regla |
|---|---|---|
| config entry de `kitchen_sink` | HA al arrancar (importación por YAML) | nadie la borra ni la deshabilita |
| dispositivos de `kitchen_sink` | la integración | cada test que borra uno usa uno distinto; nunca `statistics_issues` |
| avisos de reparación de `kitchen_sink` | la integración | el test que ignora uno lo deja como estaba al terminar |
| config entry de `uptime` | el test de flujos, con las tools | se borra al terminar, pase lo que pase |
| `input_boolean`, `schedule` de apoyo | el lector | nombres únicos; los borra el lector al cerrar la sesión |

## Las 53 tools y cómo se comprueba su efecto

«2P» = se ejecuta en dos pasos y se comprueba que la vista previa no cambia HA.
«2P cond.» = la tool solo pide token con ciertos argumentos; se prueba con los
que lo piden. «Lector» = qué lee el lector independiente.

### Tramo A — automatización, ejecución, eventos y Lovelace (26)

| Grupo | Tool | 2P | Efecto comprobado por el lector |
|---|---|---|---|
| automation | `ha_create_or_update_automation` | sí | `GET /api/config/automation/config/<id>` devuelve la configuración pedida y existe `automation.<x>`; al editar, la configuración queda **reemplazada** |
| automation | `ha_disable_automation` | no | estado `off` |
| automation | `ha_enable_automation` | no | estado `on` |
| automation | `ha_trigger_automation` | sí | el `input_boolean` de su acción pasa a `on` |
| automation | `ha_reload_automations` | sí | `automation.reload` visto una vez en el bus; la automatización sigue |
| automation | `ha_delete_automation` | sí | la configuración da 404 y la entidad desaparece |
| script | `ha_create_or_update_script` | sí | `GET /api/config/script/config/<id>` con la configuración; existe `script.<id>` |
| script | `ha_run_script` | sí | el `input_boolean` de su secuencia pasa a `on` |
| script | `ha_reload_scripts` | sí | `script.reload` visto una vez; el script sigue |
| script | `ha_delete_script` | sí | la configuración da 404 y la entidad desaparece |
| scene | `ha_create_or_update_scene` | sí | `GET /api/config/scene/config/<id>` con sus entidades; existe la entidad de la escena |
| scene | `ha_activate_scene` | no | el `input_boolean` de la escena pasa al estado guardado (`on`) |
| scene | `ha_create_scene_from_current` | no | existe `scene.<id>` con el `input_boolean` en sus atributos `entity_id` |
| scene | `ha_reload_scenes` | sí | `scene.reload` visto una vez; la escena sigue |
| scene | `ha_delete_scene` | sí | la configuración da 404 y la entidad desaparece |
| servicio | `ha_call_service` | directo y 2P | directo: `input_boolean.turn_on` → `on`; 2P con `input_boolean.reload`: vista previa sin la llamada en el bus, confirmación con una |
| servicio | `ha_call_service_response` | no | `schedule.get_schedule` sobre un horario del lector: la respuesta trae su `entity_id` y sus franjas |
| evento | `ha_fire_event` | no | el lector, suscrito a `banco_evento_<hex>`, lo recibe con los datos enviados |
| espera | `ha_cancel_wait` | no | (en Hermes, research R-7) la espera termina con `reason: cancelled` en menos de 10 s y deja de estar en `ha_list_active_waits` |
| lovelace | `ha_create_lovelace_dashboard` | no | `lovelace/dashboards/list` lo tiene con su `url_path` y título |
| lovelace | `ha_update_lovelace_dashboard_metadata` | 2P cond. | con `show_in_sidebar` (pide token): el cambio aparece en la lista |
| lovelace | `ha_save_lovelace_dashboard` | sí | `lovelace/config` con su `url_path` devuelve exactamente lo guardado |
| lovelace | `ha_delete_lovelace_dashboard` | sí | fuera de la lista |
| lovelace | `ha_create_lovelace_resource` | sí | `lovelace/resources` tiene `/local/banco-<hex>.js` con su tipo |
| lovelace | `ha_update_lovelace_resource` | sí | el tipo o la URL cambian |
| lovelace | `ha_delete_lovelace_resource` | sí | fuera de la lista |

Total A: automation 6, script 4, scene 5, servicio 2, evento 1, espera 1,
lovelace 7 = **26**.

### Tramo B — registros, integraciones y reparaciones (27)

| Grupo | Tool | 2P | Efecto comprobado por el lector |
|---|---|---|---|
| area | `ha_create_area` | no | `config/area_registry/list` la tiene con su nombre |
| area | `ha_update_area` | sí | nombre nuevo |
| area | `ha_delete_area` | sí | fuera de la lista |
| floor | `ha_create_floor` | no | `config/floor_registry/list` con su nombre y nivel |
| floor | `ha_update_floor` | sí | nombre nuevo |
| floor | `ha_delete_floor` | sí | fuera de la lista |
| label | `ha_create_label` | no | `config/label_registry/list` con su nombre y color |
| label | `ha_update_label` | sí | nombre nuevo |
| label | `ha_delete_label` | sí | fuera de la lista |
| category | `ha_create_category` | no | `config/category_registry/list` (scope `automation`) la tiene |
| category | `ha_update_category` | sí | nombre nuevo |
| category | `ha_delete_category` | sí | fuera de la lista |
| device | `ha_update_device` | sí | `config/device_registry/list`: `name_by_user` nuevo en un dispositivo de `kitchen_sink` (se restaura al terminar) |
| device | `ha_remove_device` | sí | el dispositivo elegido ya no está en el registro |
| device | `ha_remove_device_from_config_entry` | sí | otro dispositivo de `kitchen_sink` ya no está (en 2026.11 el comando borra el dispositivo) |
| entity | `ha_update_entity_registry` | sí | `config/entity_registry/get`: con `new_entity_id`, el `entity_id` nuevo existe y el viejo no |
| entity | `ha_remove_entity_registry` | sí | `config/entity_registry/get` del `input_boolean` del lector da `not_found` |
| repairs | `ha_ignore_repair` | sí | `repairs/list_issues`: el aviso elegido con `ignored: true`; al terminar, `ignore=False` lo restaura |
| config entry | `ha_reload_config_entry` | no | el estado del sensor de `uptime` cambia |
| config entry | `ha_disable_config_entry` | sí | `config_entries/get`: `disabled_by: user` |
| config entry | `ha_enable_config_entry` | no | otra vez `loaded` y `disabled_by: null` |
| config entry | `ha_delete_config_entry` | sí | la entrada no existe |
| flujo | `ha_start_config_entry_flow` | no | `config_entries/flow/progress` tiene el flujo de `uptime` |
| flujo | `ha_continue_config_entry_flow` | no | entrada nueva de `uptime` en `config_entries/get` |
| flujo | `ha_abort_config_entry_flow` | no | el flujo ya no está en curso |
| flujo | `ha_start_options_flow` | no | flujo de opciones de `kitchen_sink` con el paso `options_1` |
| flujo | `ha_continue_options_flow` | no | el lector abre su propio flujo de opciones y ve los valores nuevos como actuales; lo aborta |

Total B: area 3, floor 3, label 3, category 3, device 3, entity 2, repairs 1,
config entry 4, flujo 5 = **27**.

## Fuera del banco (24)

| Tools | Motivo |
|---|---|
| `fs_write_file`, `fs_delete_file`, `fs_move_file`, `fs_restore_file_backup`, `fs_set_secret` | No hablan con HA: escriben en el `/config` de Hermes, que en el banco es una carpeta del runner distinta de la de HA. FR-014 de la 008 es solo `ha_*`. La suite normal las ejecuta contra un sistema de ficheros real. |
| `sv_check_core_config`, `sv_get_job_status`, `sv_create_backup_full`, `sv_create_backup_partial`, `sv_create_safety_backup`, `sv_delete_backup`, `sv_restore_backup_full`, `sv_restore_backup_partial` | Backups, trabajos y validación del Supervisor: el del banco es simulado y solo reenvía a Core. Simuladores en la suite normal; VM de la 014. |
| `sv_install_addon`, `sv_uninstall_addon`, `sv_update_addon`, `sv_start_addon`, `sv_stop_addon`, `sv_restart_addon`, `sv_set_addon_options` | Add-ons: necesitan el Supervisor real (y la tienda, con internet). Simuladores; VM de la 014. |
| `sv_restart_core`, `sv_reboot_host` | Reinician Core o el host: no existen en el simulado y el banco no sobreviviría. Simuladores; VM de la 014. |
| `sv_dismiss_resolution_issue`, `sv_dismiss_resolution_suggestion` | Avisos del Supervisor: solo existen en el Supervisor real. Simuladores; VM de la 014. |

En `FUERA_DEL_BANCO` cada tool lleva su motivo propio (puede ser el de su
fila).
