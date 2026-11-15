# Validación rápida: tienda de apps (030)

## Suite (Windows, Git Bash, desde la raíz del worktree)

```bash
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" \
  /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

Solo lo de esta sub-feature:

```bash
… -m pytest -q -p no:cacheprovider tests/test_store_comun.py \
  tests/test_tools_store_repositories.py tests/test_tools_store_apps.py \
  tests/test_tools_addons_tienda.py tests/test_command_table.py \
  tests/test_tools_registration.py tests/test_tool_families.py \
  tests/test_tools_guide.py tests/test_matriz_pruebas.py \
  tests/test_rutas_supervisor_rol.py
```

Resultado esperado: los 6 fallos conocidos de Windows y ninguno más.

## Tabla

```bash
grep -c "spec 030" hermes/src/hermes/command_table.py   # 15 → 8 (tramo 1) → 0 (tramo 2)
python scripts/inventario/generar_tabla.py && git diff --exit-code hermes/src/hermes/command_table.py
```

## A mano (sin instalación real)

Con el `MockHAClient` de los tests, en un intérprete:

- `sv_add_store_repository("https://usuario:clave@example.com/repo")` → la
  vista previa enseña `https://usuario:***REDACTED***@example.com/repo` y el
  aviso de terceros; el simulado no ha recibido ningún `POST`.
- `sv_remove_store_repository("abcd1234")` con una app instalada de ese
  repositorio → `repository_in_use`, sin token.
- `sv_get_addon_changelog("abcd1234_ejemplo", offset=20000)` → el segundo
  trozo, con `next_offset`.

## Prueba en vivo (pendiente: VM de la 014 y cierre del programa)

La pauta está en el plan («Pruebas en vivo») y en la tanda 2 de
`docs/BANCO-SUPERVISOR.md`. Nunca contra la instalación real del
mantenedor sin instantánea.
