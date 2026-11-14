# Validación rápida: Hermes 1.1.0 — diagnóstico y organización

## Requisitos

Sobre la rama con 1.0.12 integrada:

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r hermes/requirements.txt
.venv/bin/pip install pytest pytest-asyncio aioresponses httpx
```

## Por bloque

Dentro de un bloque, las tools nuevas aún no están registradas: los invariantes
de `tests/test_tools_registration.py` sobre ellas solo pasan tras la
integración (research R-0.3).

| Bloque | Comando | Qué demuestra |
|---|---|---|
| A | `.venv/bin/pytest tests/test_tools_registry_floor.py tests/test_tools_registry_label.py tests/test_tools_registry_category.py` | CRUD, validación y vistas previas veraces (FR-001…FR-010) |
| B | `.venv/bin/pytest tests/test_tools_repairs.py tests/test_tools_traces.py tests/test_tools_search_related.py` | Repairs, trazas resumidas y redactadas, relaciones (FR-011…FR-021) |
| C | `.venv/bin/pytest tests/test_tools_resolution.py tests/test_tools_ha_backups.py tests/test_safety_retention.py tests/test_fs_write_security.py` | Resolución sin aplicar, backups de HA sin contraseña, retención fail-closed (FR-022…FR-038); `test_fs_write_security.py` solo se ejecuta, no se edita (comprueba que el safety backup de 1.0.12 sigue igual) |
| Integración | `.venv/bin/pytest tests/test_tools_registration.py tests/test_addon_manifest.py tests/test_run_sh_options.py tests/test_config_validation.py tests/test_tools_guide.py` | Registro, anotaciones, opción nueva, guía (FR-039…FR-042) |

Suite de un bloque sin los invariantes de registro:

```bash
.venv/bin/pytest --ignore=tests/test_tools_registration.py
```

Suite completa (obligatoria tras la integración, principio VII):

```bash
.venv/bin/pytest
```

## Control negativo (principio VII)

Para cada tool o guarda: deshacer solo la guarda (revertir el hunk o
sustituirla por un camino que no la aplique), ejecutar el test, comprobar que
falla, restaurar y anotar «con la guarda quitada caen N tests» en el commit del
bloque. Las guardas de esta spec están enumeradas en tasks.md, una por tarea
de control negativo.

## Privacidad (principio VIII)

Antes de cada commit, sobre el diff:

```bash
git diff --cached | grep -nEi 'ts\.net|tail[0-9a-f]{4,}|([0-9]{1,3}\.){3}[0-9]{1,3}|auth_password: *[^<"]|@[a-z0-9-]+\.[a-z]{2,}|claude-|gpt-|/home/|/Users/'
```

Solo deben aparecer marcadores genéricos (`homeassistant.tailXXXX.ts.net`,
`192.0.2.x`, `<slug>`, `example.invalid`) o falsos positivos explicados. Los
centinelas de los tests (contraseña, `instance_id`, tokens) deben ser
claramente falsos (`SENTINEL-…`).

## Escenarios manuales opcionales (instalación de pruebas, no de producción)

1. `ha_create_label(name="prueba")`, asignarla a una entidad con `ha_update_entity_registry`, y `ha_delete_label` sin token: la vista previa nombra esa entidad.
2. `ha_list_traces(domain="automation", entity_id="automation.<una de prueba>")` y `ha_get_trace` de su último `run_id`: el resumen cabe holgado y no trae `config`.
3. `ha_get_backup_config`: aparece `password_set` y no aparece la contraseña.
4. `safety_backup_enabled: true`, `safety_backup_keep: 1`: dos escrituras separadas por más de la ventana dejan un solo `hermes-safety-*` creado por Hermes; un backup manual llamado `hermes-safety-manual` sigue ahí.
5. `sv_get_resolution` y, si hay un issue de prueba, `sv_dismiss_resolution_issue` sin token: la vista previa dice que puede reaparecer.
