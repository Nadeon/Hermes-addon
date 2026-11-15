# Quickstart: validar la configuración del sistema (021)

Cómo comprobar la sub-feature al cerrar cada tramo. Nada de esto usa la
instalación real ni las tools MCP de Hermes.

## Requisitos previos

- Worktree de la rama `feat/021-configuracion-del-sistema` con el tramo
  integrado; `.venv` del checkout principal; una carpeta propia para
  `HERMES_CONFIG_BASE`.

## Suite

```bash
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" \
  /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

Esperado en Windows: solo los 6 fallos conocidos. Ficheros de la 021:

```bash
python -m pytest -q -p no:cacheprovider tests/test_tools_core_config.py \
  tests/test_tools_assistant_exposure.py tests/test_tools_users.py \
  tests/test_tools_core_network.py tests/test_command_table.py \
  tests/test_tools_generic_commands.py tests/test_tool_families.py \
  tests/test_tools_registration.py tests/test_tools_guide.py \
  tests/test_confirmation_args_inventory.py tests/test_matriz_pruebas.py \
  tests/test_banco_cobertura_escrituras.py
```

## Banco de Core

En el CI (job del banco). Ficheros: `tests/banco/test_banco_configuracion_sistema.py`
(a), `tests/banco/test_banco_usuarios.py` (b), `tests/banco/test_banco_red_http.py`
y `tests/banco/test_banco_analytics_labs.py` (c). El job exige por ejecución
`PROBADAS_021 | LECTURAS_021` de `tests/banco/cobertura_021.py`.

## Tabla

```bash
python scripts/inventario/generar_tabla.py
git diff --stat -- hermes/src/hermes/command_table.py   # vacío
grep -c "spec 021)" hermes/src/hermes/command_table.py  # 0 al cerrar el tramo c
```

## Comprobaciones a mano

- Con `tool_families_disabled: [core_config, assistant_exposure, users,
  core_network]` la lista de tools es la de antes de la 021.
- `hermes_guide(topic="users")`, `("core_network")`, `("network")` → el tema
  nuevo; `("system_status")` remite a `core_network`.
- Ninguna vista previa ni log de los tests lleva contraseñas, tokens,
  coordenadas, URLs, nombres de usuario ni rutas de certificados.

## Pendiente manual (tras publicar o en la VM de la 014)

- `ha_update_http_config` aplicado (por ejemplo, `cors_allowed_origins` o el
  puerto): HA reinicia, Hermes vuelve a conectar, la configuración queda
  pendiente con `revert_at`; sin promover, HA vuelve a la estable a los 5
  minutos; con `ha_promote_http_config`, queda estable.
- `ha_list_users` en un HA OS real marca como `is_hermes` el usuario de
  sistema del Supervisor, y las escrituras sobre él se rechazan.
- Exposición a `cloud.alexa` con Home Assistant Cloud activo (sincroniza con
  Amazon).
