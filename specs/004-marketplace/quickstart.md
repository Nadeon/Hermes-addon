# Validación: Hermes 1.1.0 — Marketplace de solo lectura

## Requisitos previos

- La 1.0.12 implementada (spec 001): `HAConnectionError.code`,
  `hermes/src/hermes/ha_version.py` y los cambios de `tools/hacs.py`.
- Entorno de pruebas según `CONTRIBUTING.es.md`:

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r hermes/requirements.txt pytest pytest-asyncio aioresponses httpx
```

## Pruebas automáticas

```bash
.venv/bin/pytest tests/test_tools_marketplace.py tests/test_tools_hacs.py \
  tests/test_tools_registration.py tests/test_fs_security.py \
  tests/test_tools_lovelace.py tests/test_tools_guide.py
.venv/bin/pytest            # suite completa (SC-008)
```

Resultados esperados, por escenario de la spec:

| Escenario | Qué comprobar | Contrato |
|---|---|---|
| Historia 1 | `api: "marketplace"`, lista de instalados ≤ 50, `pending_upgrade` manda, `not_loaded` sin `hacs/*` | [contracts/tools.md](./contracts/tools.md) |
| Historia 2 | caída a `hacs/*` con `unknown_command`, `can_install`, `hacs_not_installed` | idem |
| Historia 3 | detalle sin `repository/info`, releases, `github_rate_limited` | idem |
| Historia 4 | críticos y retirados con solo los campos documentados | [data-model.md](./data-model.md) |
| Historia 5 | alias con `_deprecated` y descripción `DEPRECATED` | idem |
| Historia 6 | `how_to_update`, guía, README sin «todavía no la soportan», ejemplo `/local/community/` | idem |

## Control negativo (principio VII)

Para cada cambio: deshacerlo, ejecutar su fichero de test, anotar cuántos tests
caen y restaurarlo. El recuento va al commit o al PR, p. ej.
«con la guarda de `not_loaded` quitada caen 3 tests».

## Prueba en vivo (opcional, instalación de prueba)

Con HA ≥ 2026.11, desde el cliente MCP:

1. `ha_marketplace_info()` → `api: "marketplace"`.
2. `ha_marketplace_list_updates()` → coincide con las entidades `update` de la
   plataforma `marketplace` que están en `on`.
3. `ha_marketplace_get_repository(<id>)` de un repositorio marcado como nuevo →
   sigue marcado como nuevo en la interfaz (no se escribió nada).

No pegar en issues ni en el PR nombres de repositorios, entidades ni ids de la
instalación (principio VIII).
