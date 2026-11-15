# Guía rápida: Assist y conversación (023)

## Suite local (Git Bash, desde la raíz del worktree)

```bash
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" \
  /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

Solo lo de esta sub-feature:

```bash
python -m pytest -q -p no:cacheprovider tests/test_tools_conversation.py \
  tests/test_command_table.py tests/test_tools_generic_commands.py \
  tests/test_tool_families.py tests/test_tools_registration.py \
  tests/test_tools_guide.py tests/test_confirmation_args_inventory.py \
  tests/test_banco_cobertura_escrituras.py tests/test_matriz_pruebas.py
```

## Tabla

```bash
python scripts/inventario/generar_tabla.py   # sobre la tabla editada: 0 nuevas, 0 quitadas
git diff --exit-code -- hermes/src/hermes/command_table.py
```

## Banco de Core

Corre en el CI (job `banco-core`, marcador `banco`):
`tests/banco/test_banco_conversacion.py` (CAP-060) y
`tests/banco/test_banco_assist.py` (CAP-061 y CAP-062).

## Uso desde un cliente (en una instalación de prueba, no en la real)

1. `ha_list_conversation_agents()` → qué agentes hay.
2. `ha_debug_conversation(sentences=["enciende la luz del salón"])` → qué
   entendería HA, sin ejecutar.
3. `ha_process_conversation(text="enciende la luz del salón")` → vista
   previa y token; repetir con `confirmation_token` para ejecutar.
4. Pipelines: `ha_read_ws_command("assist_pipeline/pipeline/list")`.
