# Quickstart: validar estadísticas y energía (020)

Para quien implementa o revisa un tramo. Nada de esto usa las tools MCP de
Hermes conectadas a una instalación real.

## Requisitos previos

- Worktree de la rama `feat/020-estadisticas-y-energia` y el `.venv` del
  checkout principal.
- Una carpeta propia para `HERMES_CONFIG_BASE`.

## Suite

```bash
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" \
  /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

Ficheros propios: `tests/test_tools_statistics_maintenance.py`,
`tests/test_tools_energy.py`; y los transversales que cambian:
`test_command_table.py`, `test_generar_tabla.py`,
`test_tools_generic_commands.py`, `test_tool_families.py`,
`test_tools_registration.py`, `test_tools_guide.py`,
`test_confirmation_args_inventory.py`, `test_banco_cobertura_escrituras.py`,
`test_matriz_pruebas.py`. En Windows, exactamente los 6 fallos conocidos.

## Banco de Core

Corre en el CI (job `banco-core`), no en local. Ficheros:
`tests/banco/test_banco_estadisticas.py` (tramos 1 y 2) y
`tests/banco/test_banco_energia.py` (tramo 3), con el inventario
`tests/banco/cobertura_020.py`. El job exige cada tool de `PROBADAS_020` (y
`ha_get_energy_prefs`) llamada con éxito en un test que pasa.

## Tabla

```bash
/c/Proyectos/Hermes-addon/.venv/Scripts/python.exe scripts/inventario/generar_tabla.py
git diff --exit-code -- hermes/src/hermes/command_table.py
```

Tras editar la tabla a mano y añadir las claves al mapa, regenerar no cambia
nada. `grep "spec 020" hermes/src/hermes/command_table.py` no encuentra nada
al cerrar el tramo 3.

## Comprobaciones a mano

- `hermes_guide(topic="recorder")` explica lectura y mantenimiento;
  `hermes_guide(topic="energy")`, las dos tools y las cuatro lecturas.
- La vista previa de cada tool dice qué estadísticas y qué periodo toca (o
  qué listas de energía cambian) y que solo se deshace con un backup.

## Pendiente manual (tras publicar)

En la instalación real, con backup reciente: una vista previa de cada tool
sin confirmar (no cambia nada) y, en una estadística de prueba, un ciclo
completo. No es requisito del programa.
