---

description: "Tareas de Hermes 1.1.1 (spec 006)"
---

# Tareas: Hermes 1.1.1 — correcciones de la 1.1.0

**Entrada**: `specs/006-correcciones-1-1-1/` (spec.md, plan.md).

**Tests**: obligatorios, escritos antes del arreglo y con control negativo (principio VII).

## Formato: `[ID] [P?] [Historia] Descripción`

## Fase 1: Preparación

- [X] T001 Línea base: la suite pasa entera (1838 tests) sobre 1.1.0; al cerrar la primera ronda, 1853
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

## Fase 7: Revisión independiente de la 1.1.1 (historia 4)

- [X] T017 [US4] Tests por el servidor real en `tests/test_response_limit.py`: history (3000 puntos, varios topes), statistics (5 × 400), logbook (paginación), registros de entidades y dispositivos y config entries (recuentos), `fs_read_file` de líneas cortas, `sv_get_addon_logs` de 1000 líneas, `fs_delete_file` de un fichero de más de 200 KB (token y borrado); en unidad, vista previa con token, `{id: [puntos]}`, objeto con más campos, recuentos y pista del error; recorrido de todas las tools con un `{id: [puntos]}` cerca del tope y una vista previa con token (FR-009…FR-014)
- [X] T018 [US4] Recorte con el envoltorio en `history.py`, `statistics.py`, `logbook.py`, `registry_entity.py`, `registry_device.py`, `config_entries.py` y `filesystem.py`; últimas líneas en `addons.py` (FR-009, FR-013)
- [X] T019 [US4] Guardián en `tools/_common.py`: vista previa sin perder el token, `{id: [puntos]}`, recuentos y pista del error; docstrings de `mcp_server.py` y `fs_delete_file` y guía `security` (FR-010…FR-013)
- [X] T020 [US4] `ha_ws_max_msg_size_bytes` a 16 MiB con defecto heredado en `config.py`, `config.yaml`, `run.sh` y `__main__.py`; `ha_ws_message_too_big` en `ha.py`; tests en `test_config_validation.py`, `test_run_sh_options.py`, `test_main_wiring.py` y `test_ha_ws_reliability.py` (FR-015)
- [X] T021 [US4] `oauth_cimd_document` en `cimd.py` con test en `test_cimd.py`; Marketplace con HACS sin reintentos y con `category` en el error, con tests en `test_tools_marketplace.py` (FR-016, FR-017)
- [X] T022 Control negativo. **Resultado**: sin ningún arreglo de esta fase (código, `config.yaml` y `run.sh` de la punta anterior) caen 22 de los 25 tests nuevos (los otros 3 son controles que deben pasar igual); sin los arreglos de las tools caen 6 (history, statistics, logbook, registros, `fs_read_file` y logs); sin el guardián nuevo caen otros 6 (borrado grande, vista previa, `{id: [puntos]}`, recuentos, pista y recorrido)
- [X] T023 [P] Docs: `hermes/DOCS.md` (opción `ha_ws_max_msg_size_bytes`, previews y logs, CIMD de claude.ai y recomendación), `SECURITY.md`, `README.md`, `README.es.md`, `hermes/CHANGELOG.md` `[1.1.1]` y `docs/HOJA-DE-RUTA.md` (pruebas hechas con la 1.1.0 y pendientes) (FR-017)
- [X] T024 Suite completa (1878 tests), revisión del diff buscando datos personales e identificadores de modelos, y commit

BAJO que quedan, con su motivo: L-4 (restos de texto libre en el log: no llevan datos de red y la revisión los da por aceptables) y L-5 (lista de un solo elemento tratada como su elemento, separadores no compactos y escapado JSON-RPC: solo hacen que se recorte de más, nunca de menos ni con datos falsos). Complementos de M-3 fuera de alcance: esquema a 64 MiB, `minimal_response` y `list_for_display`.

## Fase 8: Verificación independiente de la 1.1.1

- [X] T025 [US4] Tests en `tests/test_response_limit.py`: `ha_get_script` de 3000 pasos y vista de Lovelace de 1500 cards por el servidor real dan `response_too_large`; el dashboard entero que cabe sale intacto y el que no da `too_large` con `top_level`; la red anidada solo con `recortar_anidadas`; el guardián solo recorta listas anidadas en `RECORTE_ANIDADO`; topes por cantidad con `truncated`; recorte de history y statistics en menos de 5 s de CPU (FR-018…FR-020)
- [X] T026 [US4] Lista blanca `RECORTE_ANIDADO` en `mcp_server.py` y `recortar_anidadas` en `tools/_common.py` (FR-018)
- [X] T027 [US4] `recortar_grupos_a_bytes` en `tools/_common.py`, usado en `history.py` y `statistics.py` (FR-019); `ya_recortado` en `history.py`, `statistics.py` y `logbook.py` (FR-020)
- [X] T028 Control negativo con el código de 0533c73. **Resultado**: caen 6 de los 7 tests nuevos (el del dashboard entero es un control que debe pasar igual): el script sale con 1464 de 3000 pasos y la vista recortada, ambos con `is_error: false`; los topes por cantidad salen con `truncated: false`; el recorte de 20 × 500 estados tarda unos 70 s de CPU (después, 0,08 s)
- [X] T029 CHANGELOG `[1.1.1]` y hoja de ruta; suite completa, revisión del diff buscando datos personales e identificadores de modelos, y commit
