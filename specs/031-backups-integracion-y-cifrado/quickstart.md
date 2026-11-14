# Quickstart: comprobar la 031

## Suite normal (Windows, Git Bash, desde la raíz del worktree)

```
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" python -m pytest -q -p no:cacheprovider
```

Ficheros de la 031:

- `tests/test_tools_ha_backup_settings.py` (tramo 1)
- `tests/test_backup_retention_estimate.py` (tramo 1)
- `tests/test_backup_key.py` (tramo 2)
- `tests/test_tools_ha_backup_actions.py` (tramo 2)
- `tests/test_tools_ha_backup_restore.py` (tramo 3)
- `tests/test_sv_restore_backup_key.py` (tramo 3; las `sv_restore_*` tienen hoy
  sus tests en `tests/test_tools_supervisor.py`, que no cambian)
- `tests/test_safety_backup_encryption.py` (tramo 4)
- los existentes que cambian: `test_tools_ha_backups.py`,
  `test_safety_retention.py`, `test_tools_supervisor.py` y
  `test_fs_write_security.py` (sin cambios de lo que ya prueban; con
  `safety_backup_encryption: off` en los que fijan la carga exacta del POST,
  si hace falta), `test_tool_families.py`,
  `test_tools_registration.py`, `test_tools_generic_commands.py`,
  `test_command_table.py`, `test_generar_tabla.py`, `test_tools_guide.py`,
  `test_banco_cobertura_escrituras.py`, `test_matriz_pruebas.py`,
  `test_addon_manifest.py`, `test_run_sh_options.py`,
  `test_config_validation.py`, `test_main_wiring.py`.

Al terminar cada tramo fallan exactamente los 6 conocidos de Windows.

## Banco de Core (solo en el CI, job `banco-core`)

- `tests/banco/test_banco_backups_ajustes.py` (tramo 1): agentes
  (`backup.local`), configuración (programación, retención) leída de vuelta
  por el lector, `supervisor_integration_unavailable` de
  `ha_get_update_backup_settings`.
- `tests/banco/test_banco_backups_acciones.py` (tramo 2): crear (con y sin
  cifrar, clave centinela fijada por el lector), seguir con `ha_list_backups`,
  crear con ajustes automáticos con `copies: 1` y ver que HA borra el que la
  estimación decía, borrar, y la clave leída de HA real que no aparece en
  ninguna respuesta ni en el log.
- `tests/banco/test_banco_backups_restaurar.py` (tramo 3): vista previa, token
  atado (cambiar el backup → `state_changed`) y contraseña incorrecta →
  `password_incorrect` con HA vivo después. Nunca una restauración con éxito.

## Pruebas en vivo (VM de la 014 o instalación real, tras publicar)

- `ha_set_update_backup_settings` y `ha_get_update_backup_settings` con la
  integración `hassio`.
- `ha_restore_backup` desde `hassio.local` y desde un agente remoto
  (instantánea antes).
- Safety backup cifrado con la clave de HA y su restauración por
  `sv_restore_backup_full` sin `password`, y desde la interfaz de HA con el kit
  de emergencia.
- `safety_backup_encryption: required` con HA sin clave: la escritura en
  `/config` no se hace.
