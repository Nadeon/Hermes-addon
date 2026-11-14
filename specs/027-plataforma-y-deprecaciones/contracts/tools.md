# Contratos: plataforma y deprecaciones (027)

Ninguna tool nueva. Cambios en tools existentes, todos compatibles con la
1.1.2 (FR-020 de la 008): mismos nombres, argumentos y anotaciones.

## `sv_get_job_status(job_id)` — solo lectura (sin cambios de anotación)

Respuesta: la de siempre más `child_errors` (y `child_errors_truncated` si se
recortó).

```json
{
  "job_id": "<uuid>",
  "name": "backup_manager_full_backup",
  "done": true,
  "success": false,
  "errors": [],
  "child_errors": [
    {"job": "backup_store_apps", "message": "Can't create backup for <slug>"}
  ],
  "progress": 100,
  "stage": null,
  "reference": "<slug del backup>"
}
```

Descripción (texto que el cliente lee; en el idioma de la actual):

- `done` es `true` también cuando el job falla: mira `success`.
- `success` es `false` si hay **cualquier** entrada en `errors`: el Supervisor
  no distingue avisos de errores fatales.
- Los errores de los sub-jobs van en `child_errors` y **también** dan
  `success: false`, aunque `errors` esté vacío (D-1; la 1.1.2 daba `true`).
  Por ejemplo, una app que no se pudo guardar en un backup: el backup existe
  (`reference`) pero le falta esa app; compruébalo con `sv_get_backup`.
- Con errores, `reference` puede apuntar a algo que sí se creó.

## `ha_remove_device_from_config_entry(device_id, config_entry_id, confirmation_token?)` — destructiva (sin cambios)

Primer paso: sin cambios (vista previa con `deprecated`, `replacement` y el
aviso de 2027.9).

Segundo paso, nuevo caso: HA responde `unknown_command` →

```json
{"error": "command_removed_in_ha", "command": "config/device_registry/remove_config_entry",
 "replacement": "ha_remove_device", "detail": "…"}
```

Cualquier otro error, igual que hoy (`{"error": "<texto>"}`). La descripción
de la tool añade este error a lo que devuelve (principio V: el comportamiento y
su descripción cambian en el mismo commit).

## Tools de apps (`tools/addons.py`) — sin cambios de contrato

`sv_list_addons`, `sv_get_addon`, `sv_get_addon_options`,
`sv_set_addon_options`, `sv_start_addon`, `sv_stop_addon`, `sv_restart_addon`,
`sv_install_addon`, `sv_uninstall_addon`, `sv_update_addon`,
`sv_get_addon_logs`, `sv_get_addon_stats`: solo cambia el texto de la
descripción («app (add-on)»). Argumentos (`slug`…), respuestas y anotaciones,
idénticos.

## Guía (`hermes_guide`)

- Tema `supervisor`: «Sistema: apps (add-ons), host y core»; las líneas de las
  tools de apps; el aviso de `sv_get_job_status` (FR-001) y `child_errors`.
- Tema `backups`: la línea de jobs explica `success` y `child_errors`.
- Instrucciones del servidor, apartado 4 «Operaciones largas»: «Instalar o
  actualizar apps (add-ons)…» y una línea sobre `success` y `child_errors`.

## Arranque (no es una tool)

Tras el paso 8 (cliente de HA conectado) y antes del paso 9 (servidor MCP):
`await comprobar_plataforma(ha_client, os.environ)`, que nunca lanza y tarda
como mucho 10 s. Eventos en data-model.
