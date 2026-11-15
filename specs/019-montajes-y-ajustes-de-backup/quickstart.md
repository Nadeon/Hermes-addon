# Quickstart: montajes de red y ajustes de backup (019)

Cómo comprobar la sub-feature al terminar cada tramo. Todo en local, con el
Supervisor simulado; la prueba real es la VM de la 014.

## Suite

Desde la raíz del worktree, en Git Bash:

```bash
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" \
  <python del .venv del checkout principal> -m pytest -q -p no:cacheprovider
```

Esperado: solo los 6 fallos conocidos de Windows. Los ficheros de esta
sub-feature:

```bash
python -m pytest -q -p no:cacheprovider \
  tests/test_tools_mounts.py tests/test_tools_backup_settings.py \
  tests/test_tools_supervisor.py tests/test_command_table.py \
  tests/test_tool_families.py tests/test_tools_registration.py \
  tests/test_tools_guide.py tests/test_matriz_pruebas.py \
  tests/test_tools_generic_commands.py
```

Y, si la 033 está integrada, `tests/test_confirmation_args_inventory.py`.

## Tabla

```bash
grep -c "spec 019" hermes/src/hermes/command_table.py   # 0 al cerrar el tramo 2 (3 tras el tramo 1)
python scripts/inventario/generar_tabla.py && git diff --exit-code hermes/src/hermes/command_table.py
```

## Secretos (a mano, además de los tests)

```bash
grep -rn "CENTINELA" "$(cygpath -u <carpeta propia>)"   # nada en el directorio de tokens ni en logs
git diff | grep -nE "192\.168\.|tail[0-9a-f]{4}\.ts\.net|C:\\\\"   # nada (principio VIII)
```

## Recorrido con un cliente (VM de la 014, pendiente)

1. `sv_list_mounts` → lista vacía o la de la VM.
2. `sv_create_mount` de un recurso CIFS de prueba con usuario y contraseña de
   prueba: la vista previa no los enseña; confirmar; `ha mounts info` lo
   muestra; el log de Hermes no los tiene.
3. `sv_create_backup_partial(..., location="<montaje>")` y `sv_list_backups`.
4. `sv_update_mount` sin credenciales: la vista previa avisa; no confirmar.
5. `sv_delete_mount`: la vista previa cuenta el backup del paso 3.
6. `sv_set_backup_settings(days_until_stale=7)` y `sv_get_backup_settings`.
