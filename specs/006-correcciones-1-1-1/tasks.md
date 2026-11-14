---

description: "Tareas de Hermes 1.1.1 (spec 006)"
---

# Tareas: Hermes 1.1.1 — correcciones de la 1.1.0

**Entrada**: `specs/006-correcciones-1-1-1/` (spec.md, plan.md).

**Tests**: obligatorios, escritos antes del arreglo y con control negativo (principio VII).

## Formato: `[ID] [P?] [Historia] Descripción`

## Fase 1: Preparación

- [X] T001 Línea base: la suite pasa entera (1838 tests) sobre 1.1.0; al cerrar, 1853
- [X] T002 Reproducir en vivo, en lectura: `ha_hacs_list_repositories` sin categoría falla y deja `ha_ws_reconnect_failure`; con `category="integration"` funciona (plan R-1)

## Fase 2: Historia 1 — Marketplace por categorías (P1)

- [X] T003 [US1] El simulador `FakeHA` de `tests/test_tools_marketplace.py` filtra `*/repositories/list` por `categories` como HA 2026.11.1; tests nuevos: `list_updates`, `get_repository` y `list_repositories` sin categoría nunca envían el comando sin `categories`, juntan todas las categorías sin duplicados y, con HACS, piden también `appdaemon` y `python_script` (FR-001, FR-002)
- [X] T004 [US1] `_list_catalog` en `hermes/src/hermes/tools/marketplace.py` y uso en las tres funciones (FR-001)
- [X] T005 [US1] Control negativo: volver a pedir el catálogo entero → caen los tests de T003; anotar el recuento. **Resultado**: con `marketplace.py` de 1.1.0 caen 25 (incluidos subtests) en `test_tools_marketplace.py` y `test_tools_hacs.py`

## Fase 3: Historia 2 — Límite de respuesta central (P1)

- [X] T006 [US2] `tests/test_response_limit.py`: `ha_get_states` con ~245 KB de sensores por el cliente MCP en memoria cabe en 128 KiB y trae `truncated`; recorrido de TODAS las tools registradas con tres formas de resultado grande (lista, objeto con lista, texto) por `HermesMCPServer.call_tool`; un resultado pequeño sale idéntico; `response_too_large` sale con `isError` (FR-003…FR-006)
- [X] T007 [US2] `recortar_a_bytes` en `hermes/src/hermes/tools/_common.py`
- [X] T008 [US2] Guardián en `hermes/src/hermes/mcp_server.py` y asignación del tope en `hermes/src/hermes/tools/__init__.py`; docstring de `ha_get_states` en `hermes/src/hermes/tools/ha.py`
- [X] T009 [US2] Control negativo: quitar el guardián → caen los tests de T006; anotar. **Resultado**: sin fijar el tope en el servidor caen 2 (`test_ha_get_states_respeta_el_tope_y_lo_dice` y `test_ninguna_tool_registrada_pasa_del_tope`)

## Fase 4: Historia 3 — Log sin argumentos libres (P2)

- [X] T010 [US3] `tests/test_log_privacy_args.py`: patrón con IP y MAC ficticias y plantilla con un `entity_id` ficticio no aparecen en el log (éxito, rechazo y error); sí `pattern_len` / `template_len` (FR-007)
- [X] T011 [US3] `pattern_len` en `hermes/src/hermes/tools/filesystem.py` y `template_len` en `hermes/src/hermes/tools/templates.py`
- [X] T012 [US3] Control negativo: volver a registrar el patrón → caen los tests de T010; anotar. **Resultado**: con `filesystem.py` y `templates.py` de 1.1.0 caen 9 (incluidos subtests)

## Fase 5: Versión y documentación

- [X] T013 [P] Versión 1.1.1 en `hermes/config.yaml`, `hermes/src/hermes/__init__.py` y `HA_CORE_LAST_TESTED_IN_HERMES` en `hermes/src/hermes/config.py` (FR-008)
- [X] T014 [P] `hermes/CHANGELOG.md`: `## [1.1.1] — 2026-11-14` con Fixed; `hermes/DOCS.md`, `README.md` y `README.es.md`: el límite vale para todas las tools y cómo se avisa
- [X] T015 [P] `docs/HOJA-DE-RUTA.md`: estado 1.1.1 y pruebas manuales pendientes (tools nuevas con un cliente que no tenga la lista cacheada, CIMD con un cliente nuevo y desde claude.ai)

## Fase 6: Cierre

- [X] T016 Suite completa, revisión del diff buscando datos personales e identificadores de modelos, y los dos commits
