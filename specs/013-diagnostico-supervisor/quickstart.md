# Validación rápida: diagnóstico del Supervisor (013)

## Suite (Windows, Git Bash, desde la raíz del worktree)

```bash
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta-temporal-propia>)" \
  /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

Esperado: los 6 fallos conocidos de Windows y ninguno más. Referencia final:
el CI de Linux.

Solo lo de esta sub-feature:

```bash
… -m pytest -q -p no:cacheprovider tests/test_tools_system_logs.py \
  tests/test_tools_host_system.py tests/test_tools_diagnostico_tabla.py \
  tests/test_command_table.py tests/test_tools_registration.py \
  tests/test_tools_guide.py tests/test_tool_families.py
```

## Tabla

1. `python scripts/inventario/generar_tabla.py` → `git diff --exit-code
   hermes/src/hermes/command_table.py` sin cambios (la tabla regenerada es
   idéntica).
2. `grep -c "spec 013" hermes/src/hermes/command_table.py` → 0.

## A mano (sin instalación real)

- `hermes_guide("system_diagnostics")` y sus alias devuelven el tema.
- Con `tool_families_disabled: [system_diagnostics]` en el entorno de los
  tests, las 11 tools no aparecen y `sv_read_api("/core/logs")` sigue
  respondiendo `use_dedicated_tool` con `family_disabled: true`.

## Prueba en vivo (pendiente: 014 o cierre del programa)

Contra un Supervisor real (VM de la 014 o la instalación del mantenedor):

1. `sv_list_boots` y `sv_get_core_logs(boot=-1)`: el log del arranque anterior.
2. `sv_get_host_logs(identifier="kernel", lines=50)`.
3. `sv_get_plugin_logs("dns", latest=true)`.
4. `sv_get_addon_logs("<slug>", boot=0)` y con `latest=true`.
5. `sv_get_disk_usage(max_depth=2)`; `sv_get_os_info`; `sv_get_swap`;
   `sv_list_datadisk_candidates`; `sv_list_host_services(state="failed")`.
6. `sv_read_api` con `/jobs/info`, `/hardware/info`, `/network/info`.
7. Revisar que el log de Hermes no lleva contenido de los logs ni direcciones.

El resultado se anota en la matriz tool → entorno de `docs/HOJA-DE-RUTA.md`.
