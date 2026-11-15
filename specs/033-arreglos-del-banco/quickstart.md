# Quickstart: validar la 033

Desde la raíz del worktree (Git Bash):

```
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" <python del .venv> -m pytest -q -p no:cacheprovider
```

En Windows fallan exactamente los 6 conocidos. El banco solo corre en el job
`banco de Core` del workflow `Tests` (CI de Linux).

## Por requisito

| FR | Dónde se ve | Qué esperar |
|---|---|---|
| FR-001, FR-002 | `tests/test_security_regressions.py`, `tests/test_tools_scripts.py`, `tests/test_tools_automations.py`; banco: `test_banco_escrituras_automatizacion.py` | vista previa con `variables`; otras variables → rechazo sin llamada; mismas → ejecución con ellas |
| FR-003 | `tests/test_confirmation_args_inventory.py` | las 79 tools con token clasificadas; quitar una entrada o añadir un argumento sin clasificar lo pone en rojo |
| FR-004 | `tests/test_tools_counter.py`; banco: `TestCounter.test_recarga` | `not_supported`, sin token ni llamada; Core sin `counter.reload` |
| FR-005 | `tests/test_tools_registration.py`, `tests/test_tools_wait_for_event.py`; banco | esquema sin `ctx`; progreso con un `Context` de prueba; llamada con `ctx` sobrante aceptada |
| FR-006 | `tests/test_tools_scenes.py`; banco | crear en un paso, reemplazar con token, `scene_exists`, `name_not_supported`, `entity_not_found` |
| FR-007 | `tests/test_tools_scenes.py` | ninguna docstring de escenas dice `.storage/core.scene_` |
| FR-008 | `tests/test_tools_config_entry_flows.py`; banco | `not_supported` con `domain`/`title`/`supports_options`, sin `options` |
| FR-009 | `tests/test_tools_counter.py`; banco: test de `amount` | `step` 3 desde 5 → `invalid_amount` y estado intacto; `step` 1 → igual que la 1.1.2 |
| FR-010 | job del banco | `FALLAN_EN_BANCO` vacío; ningún `xfail` de estas tools |
| FR-011 | `tests/test_tools_registration.py` | instantáneas de hints y esquemas en verde con las dos excepciones escritas |

## Manual, tras publicar (no bloquea)

- Con una instalación real: `ha_run_script` sobre un script restringido con
  variables, confirmar con otras y comprobar el rechazo.
- `ha_wait_for_event` de más de 30 s desde un cliente real: la conexión no se
  corta y se ven los avisos de progreso.
