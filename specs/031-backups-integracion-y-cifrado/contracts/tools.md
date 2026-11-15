# Contrato de las tools (031)

Familia `backup_integration` (1.2.0, desactivable). Todas con `@ready`
(`requires_ready`), comprobación de versión (HA ≥ 2025.1, como
`tools/ha_backups.py`) y descripciones en inglés que dicen lo que hacen y lo
que no. Las que modifican: dos pasos con `create_confirmation_token` /
`resolve_confirmation_token` (estado atado, 018) y `complete_confirmation_token`.
Formas de datos en [data-model.md](../data-model.md).

Errores comunes: `invalid_argument` (con `field`, sin repetir valores
sensibles), `ha_version_unsupported`, `backup_integration_unavailable`
(`unknown_command`), `state_changed` (la huella del estado no coincide: otra
vista previa), el error de conexión de siempre, y el de HA redactado.

## Módulo `ha_backup_settings` (tramo 1)

### `ha_list_backup_agents() -> object`

Solo lee (`backup/agents/info` + `backup/config/info`). Sección 1 del
data-model. Nunca devuelve la contraseña.

### `ha_update_backup_config(schedule=None, retention=None, agents=None, create_backup=None, automatic_backups_configured=None, confirmation_token=None) -> object`

Sin token: vista previa (sección 3) y token. Con token: `backup/config/update`
con exactamente lo pasado. Rechaza `password` en cualquier nivel. La
descripción dice que la clave de cifrado no se puede cambiar aquí (interfaz de
HA) y que la retención puede borrar backups automáticos.

### `ha_get_update_backup_settings() -> object`

Solo lee (`hassio/update/config/info`). `unknown_command` →
`supervisor_integration_unavailable`.

### `ha_set_update_backup_settings(core_backup_before_update=None, add_on_backup_before_update=None, add_on_backup_retain_copies=None, confirmation_token=None) -> object`

Sección 5. Al menos un valor. Con token: `hassio/update/config/update`.

## Módulo `ha_backup_actions` (tramo 2)

### `ha_create_backup(agent_ids, include_homeassistant=True, include_database=True, include_addons=None, include_all_addons=False, include_folders=None, name=None, encrypt=True, confirmation_token=None) -> object`

Sección 7. Valida `agent_ids` contra `backup/agents/info` (error
`unknown_agent` con `available`). `encrypt=True` sin clave →
`no_encryption_key` (sin token). Con token: lee la clave otra vez (si
`encrypt`) y manda `backup/generate` con `password`; devuelve `backup_job_id`.
La clave nunca entra en los argumentos del token, en la vista previa ni en el
log.

### `ha_create_automatic_backup(confirmation_token=None) -> object`

Sección 7. Sin agentes en los ajustes → `automatic_backups_not_configured`.
Con token: `backup/generate_with_automatic_settings`; devuelve
`backup_job_id`. La descripción dice que, al terminar, HA aplica la retención y
puede borrar backups automáticos antiguos.

### `ha_delete_backup(backup_id, confirmation_token=None) -> object`

Sección 9. `backup/details` sin backup → `not_found` (sin token). Con token:
`backup/delete`; respuesta con `deleted_from` y `failed`.

## Módulo `ha_backup_restore` (tramo 3)

### `ha_restore_backup(backup_id, agent_id=None, restore_homeassistant=True, restore_database=None, restore_addons=None, restore_folders=None, password=None, confirmation_token=None) -> object`

Sección 8. Comprobaciones previas de research R-6. `password` entra en el
hash del token (HMAC de la 019) y en ningún otro sitio. Con token: lee la clave
si `password_source` es `backup_encryption_key`, manda `backup/restore` con un
plazo de 30 s y responde según FR-008 (`completed`, `restore_started` o
error). La descripción dice qué se sobrescribe, que Core se reinicia, que lo
posterior al backup se pierde y que el resultado puede ser `restore_started`.

## Cambios en tools existentes

| Tool | Cambio | Tramo |
|---|---|---|
| `ha_list_backups` | + `last_action_event` (sección 10) | 2 |
| `sv_restore_backup_full`, `sv_restore_backup_partial` | sin `password` y backup `protected` → clave de HA; `password_source` en la vista previa; error de contraseña con la pista de la clave anterior | 3 |
| `sv_create_safety_backup` | `password` según `safety_backup_encryption`; `encrypted` (y `encryption_skipped_reason`) en la respuesta; `encryption_key_unavailable` con `required` | 4 |
| (interna) safety backup automático de `fs_write` | ídem; con `required` sin clave, la escritura no se hace | 4 |

Ningún argumento existente cambia de nombre, tipo ni significado.
