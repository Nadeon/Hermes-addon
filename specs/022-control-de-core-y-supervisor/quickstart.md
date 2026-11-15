# Validación rápida: control de Core y del Supervisor (022)

## Suite (Windows, Git Bash, desde la raíz del worktree)

```bash
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta-temporal-propia>)" \
  <python del .venv> -m pytest -q -p no:cacheprovider
```

Resultado esperado: los 6 fallos conocidos de Windows y ninguno más. Solo lo
de esta sub-feature:

```bash
<python del .venv> -m pytest -q -p no:cacheprovider \
  tests/test_tools_system_control.py tests/test_tools_resolution_fixes.py \
  tests/test_tools_control_tabla.py tests/test_tools_resolution.py \
  tests/test_command_table.py tests/test_tool_families.py \
  tests/test_tools_registration.py tests/test_tools_guide.py \
  tests/test_confirmation_args_inventory.py tests/test_matriz_pruebas.py \
  tests/test_banco_cobertura_escrituras.py
```

## Tabla

```bash
grep -c "spec 022" hermes/src/hermes/command_table.py      # 14 → 4 (tramo 1) → 0 (tramo 2)
<python del .venv> scripts/inventario/generar_tabla.py
git diff --exit-code hermes/src/hermes/command_table.py    # sin cambios (salvo finales de línea)
```

## A mano (sin instalación real)

Con un `DummyMCP` y el Supervisor simulado, en un script fuera del repositorio:

1. `sv_start_core()` con Core «parado» → vista previa; con el token → un
   `POST /core/start`.
2. `sv_set_core_options({"image": "x"})` → `not_allowed`, cero llamadas.
3. `sv_restart_supervisor()` con un job en curso → `jobs_in_progress`, cero
   llamadas.
4. `sv_apply_resolution_suggestion(<uuid de clear_full_backup>)` → la lista de
   backups a borrar; con una sugerencia `registry_login` → `no_fixup`.

Nunca contra la instalación real ni con las tools MCP de Hermes conectadas a
ella.

## Prueba en vivo (pendiente: VM de la 014)

Tandas de `docs/BANCO-SUPERVISOR.md`: tanda 1 (opciones de Core y del
Supervisor, ida y vuelta; recarga), tanda 3 (rebuild, start tras parar Core
desde la consola del host, restart y repair del Supervisor, una sugerencia
provocada). Resultado en la matriz de `docs/HOJA-DE-RUTA.md`.
