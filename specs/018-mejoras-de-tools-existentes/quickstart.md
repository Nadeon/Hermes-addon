# Validación rápida: mejoras de tools existentes (018)

## Requisitos

- Worktree de la rama de la 018, `.venv` del checkout principal y una carpeta
  propia para `HERMES_CONFIG_BASE`.
- Nada de la instalación real: todo con tests (y el banco en el CI).

## Suite

Desde la raíz del worktree, en Git Bash:

```bash
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" \
  /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

Esperado en Windows: los 6 fallos conocidos (finales de línea, byte nulo y
symlinks) y nada más. Referencia: el CI de Linux.

## Escenarios

| Escenario | Dónde | Esperado |
|---|---|---|
| Guardar la vista 1 de un dashboard de tres vistas | `tests/test_tools_lovelace.py::TestGuardarPorVista` | Vista previa con `view_before`/`view_after`, `views_kept` [0, 2] y `top_level_keys_kept`; al confirmar sin `view`, `lovelace/config/save` recibe el actual con solo la vista 1 cambiada |
| El dashboard cambia entre vista previa y confirmación | `TestGuardarPorVista` | `dashboard_changed`, ningún `lovelace/config/save` |
| Mezclas y valores inválidos | `TestGuardarPorVista` | Códigos de [contracts/tools.md](contracts/tools.md), sin token ni escritura |
| Guardado completo sin cambios | `tests/test_tools_lovelace.py` (existentes, sin tocar) | Verdes como en la 1.1.2 |
| Token atado al estado | `tests/test_security.py::TestTokenAtadoAlEstado` | Las cuatro filas de la tabla de [data-model](data-model.md#estado-ligado-al-token-securitypy) |
| `conversation.process` sin y con token | `tests/test_call_service_security.py::TestCallServiceResponseConfirmacion` | Error de la 1.1.2 + token; con token, una ejecución y la respuesta |
| Sobre de lista y test transversal | `tests/test_sobre_de_lista.py` | Constructor, recorte central y control negativo sintético |
| Instantáneas | `tests/test_tools_registration.py` | Solo las tres propiedades opcionales nuevas; hints iguales; `SIN_TOKEN_A_PROPOSITO` vacío |
| Banco de Core | `tests/banco/test_banco_mejoras.py` (job `banco-core`) | Guardado por vista contra HA real y `conversation.process` confirmado |

## Control negativo (principio VII)

Para cada guarda nueva, quitarla un momento y ver el test en rojo:

- Fusión por vista que sustituye todo el documento → cae la comprobación de
  vistas conservadas.
- Sin comprobar `state_hash` → cae `dashboard_changed` (unitario y security).
- `ha_call_service_response` ejecutando sin token en denylist → cae «no
  ejecuta sin token».
- `cached_result` con la respuesta → cae el test del fichero del token.
- Test transversal sin el AST (siempre verde) → cae el control sintético.

Anotar en el commit «con la guarda quitada caen N tests».
