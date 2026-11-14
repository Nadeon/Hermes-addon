# Validación rápida: Hermes 1.0.12

## Requisitos

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r hermes/requirements.txt
.venv/bin/pip install pytest pytest-asyncio aioresponses httpx
```

## Suite completa

```bash
.venv/bin/pytest
```

Debe pasar entera (principio VII, SC-008).

## Por lote

| Lote | Comando | Qué demuestra |
|---|---|---|
| Fase 0 | `.venv/bin/pytest tests/test_ha_ws_error_code.py tests/test_ha_version.py` | Código de error y versión de HA (FR-030). |
| A | `.venv/bin/pytest tests/test_fs_write_security.py tests/test_tools_supervisor.py` | Safety backup con `job_id` real, jobs fallidos, campos del Supervisor (FR-001…FR-010). |
| B | `.venv/bin/pytest tests/test_tools_registry_entity.py tests/test_tools_registry_device.py tests/test_tools_registry_area.py tests/test_tools_config_entries.py` | Alias, `ha_remove_device`, dispositivos hijo (FR-011…FR-024). |
| C | `.venv/bin/pytest tests/test_tools_lovelace.py` | Dashboard principal protegido, lista, recursos (FR-025…FR-029). |
| D | `.venv/bin/pytest tests/test_tools_templates.py tests/test_tools_counter.py tests/test_tools_scripts.py tests/test_tools_ha_services.py tests/test_tools_statistics.py tests/test_tools_hacs.py tests/test_security_regressions.py` | Plantillas, `not_found`, `trace`, servicios, `year`, HACS, `perform_action` (FR-031…FR-040). |
| Integración | `.venv/bin/pytest tests/test_addon_manifest.py tests/test_tools_guide.py tests/test_tools_registration.py` | Versión 1.0.12, mínimo 2024.10.0, guía y registro de tools (FR-041…FR-044). |

## Control negativo (principio VII)

Para cada arreglo: deshacer solo el cambio de código (`git stash` del fichero
de código, o revertir el hunk), ejecutar el test de regresión, comprobar que
falla y anotar «con la guarda quitada caen N tests» en el commit del lote.

## Privacidad (principio VIII)

Antes de cada commit, sobre el diff:

```bash
git diff --cached | grep -nEi 'ts\.net|tail[0-9a-f]{4,}|([0-9]{1,3}\.){3}[0-9]{1,3}|auth_password: *[^<"]|@[a-z0-9-]+\.[a-z]{2,}|claude-|gpt-|/home/|/Users/'
```

Solo deben aparecer marcadores genéricos (`homeassistant.tailXXXX.ts.net`,
`192.0.2.x`, `<slug>`) o falsos positivos explicados.

## Escenarios manuales opcionales (instalación de pruebas, no de producción)

1. `safety_backup_enabled: true` → `fs_write_file` con token: termina tras el backup; `sv_list_pending_jobs` no muestra un segundo backup.
2. `ha_get_entity_registry` de una entidad, añadir un alias conservando el `null` y guardar: Assist sigue reconociendo la entidad por su nombre.
3. `ha_delete_lovelace_dashboard(url_path="lovelace")` → `cannot_delete_default_dashboard`, sin token.
4. `ha_remove_device(<id de un dispositivo de prueba>)` → la preview dice `delete_device` y el número de entidades.
