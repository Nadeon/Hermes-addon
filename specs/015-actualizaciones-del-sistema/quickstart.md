# Quickstart: validar las actualizaciones del sistema (015)

## 1. Suite y banco (cada tramo)

Desde la raíz del worktree, en Git Bash:

```text
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

Exactamente los 6 fallos conocidos de Windows. El banco (tramo 3) corre en el
job `banco-core` del CI: `tests/banco/test_banco_actualizaciones.py`.

## 2. Comprobaciones rápidas con el Supervisor simulado

- `sv_update_core()` con el Supervisor con actualización pendiente → `blocked`
  con `supervisor_update_pending`, sin `confirmation_token`, sin
  `POST /core/update` en las llamadas registradas.
- `sv_update_core()` sano → vista previa con `from_version`, `to_version`,
  `backup.name == "core_<from>"`, `config_check.result == "ok"`; confirmación →
  una sola llamada `POST /core/update` con `version` explícita y
  `background: true`.
- Cambiar `version_latest` entre vista previa y confirmación → `preview_outdated`
  y ninguna llamada `POST`.
- `sv_read_api("/available_updates")` y `sv_call_api("POST", "/core/update")`
  → `use_dedicated_tool` con la tool.

## 3. Prueba real (pendiente manual: VM con HAOS de la 014)

Con instantánea previa de la VM y Hermes instalado como app local. Anotar el
resultado en la matriz tool → entorno de `docs/HOJA-DE-RUTA.md`.

1. `sv_check_for_updates` → lista con lo que la interfaz de HA enseña en
   Ajustes → Actualizaciones.
2. `sv_list_available_updates` → mismas versiones que `ha_list_updates` para
   las entidades de Core, OS y Supervisor.
3. Si hay Supervisor nuevo: `sv_update_supervisor` → vista previa → confirmar
   → `job_id` o `started`; comprobar con `sv_get_supervisor_info` que cambió la
   versión y que Core y las apps no se reiniciaron (uptime).
4. `sv_update_core(version=<una anterior a la instalada>)` → vista previa con
   `downgrade` y el backup → confirmar → seguir el `job_id` → Core vuelve en la
   versión pedida; el backup `core_<versión>` aparece en `sv_list_backups`.
   Volver a la versión de partida igual.
5. `sv_update_os` → vista previa → confirmar → `version_pending` en
   `sv_get_os_info` y el aviso `reboot_required` en `sv_get_resolution`;
   `sv_reboot_host` → la VM arranca en la versión nueva.
6. `ha_install_update` sobre la entidad de Core → `use_dedicated_tool`.
7. Restaurar la instantánea.
