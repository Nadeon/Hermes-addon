# Quickstart: validar la 009

Desde la raíz del worktree, en Git Bash (Windows) o en Linux:

```sh
export MSYS_NO_PATHCONV=1   # solo Windows
HERMES_CONFIG_BASE="<carpeta temporal propia>" \
  <python del .venv> -m pytest -q -p no:cacheprovider
```

Esperado: todo verde salvo, en Windows, los 6 fallos conocidos (finales de
línea, byte nulo y symlinks). La referencia final es el CI de Linux.

## Por requisito

| FR | Comprobación rápida |
|---|---|
| FR-001 | `pytest tests/test_redact_secrets.py -k "lineal or diferencial"`: 1 MiB de cada forma < 1 s; corpus igual a la 1.1.2 |
| FR-002 | `pytest tests/test_log_redact_network.py tests/test_ha_ws_reliability.py -k "url"`: hosts centinela tapados tras conectar y tras reconectar; aviso sin valores si `/api/config` falla |
| FR-003 | `pytest tests/test_call_service_security.py -k "auto_classify"`: el log no contiene el `entity_id` centinela |
| FR-004 | `pytest tests/test_log_redact_network.py -k "dashed or ip_guion"` |
| FR-005 | `pytest tests/test_tools_supervisor.py -k "addon_logs"` |
| FR-006 | `pytest tests/test_tools_history_logbook.py tests/test_response_limit.py -k "history"` |
| FR-007 | `pytest tests/test_tools_marketplace.py -k "removed"` |
| FR-008 | `pytest tests/test_tools_marketplace.py tests/test_tools_resolution.py -k "_ok"` |
| FR-009 | `pytest tests/test_security.py -k "barrido"` |
| FR-010 | `pytest tests/test_tools_supervisor.py -k "update_addon"` |
| FR-011 | `pytest tests/test_boot_shutdown_diagnostics.py -k "apagado or cancel"` |
| FR-012 | `pytest tests/test_addon_manifest.py` |

Los nombres de `-k` son orientativos: los fija cada tarea de
[tasks.md](tasks.md).

## Manual, tras publicar (no bloquea)

- Reiniciar el add-on con una `ha_wait_for_event` en vuelo y mirar el log: sin
  traza (R-7).
- `sv_get_addon_logs` del propio Hermes: `network_redacted: true`.
- `sv_update_addon` sobre Hermes: `self_update_not_supported`.
