# Plan de implementación: Hermes 1.1.1 — correcciones de la 1.1.0

**Rama**: la de trabajo actual (no se crea ninguna) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md)

## Resumen

Tres arreglos pequeños y la documentación: el catálogo del Marketplace se pide
por categorías, un guardián central de tamaño en `HermesMCPServer.call_tool`
y dos argumentos de texto libre fuera del log.

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` (MCPServer), aiohttp, structlog · **Tests**: pytest, unittest asíncrono, cliente MCP en memoria · **Plataforma**: add-on de Home Assistant.

## Comprobación de la constitución

| Principio | Cumplimiento |
|---|---|
| I / III | El guardián es fail-closed: si no puede recortar, devuelve `response_too_large`, nunca algo por encima del tope. |
| II / VIII | El log deja de llevar argumentos libres. Tests y spec con datos ficticios (`192.0.2.x`, `00:00:5e:…`, `owner/repo`). |
| V | Docstring de `ha_get_states` y textos de DOCS/README con la forma truncada real. |
| VI / VII | Test previo de cada fallo, control negativo de cada guarda y suite completa. |
| IX | Solo los tres fallos y la documentación; lo demás va a «Fuera de alcance». |
| X | Comentarios en español con el porqué. |

## Investigación (research)

- **R-1 — Causa del fallo de updates.** `list_updates` y `get_repository` (y `list_repositories` sin `category`) envían `marketplace/repositories/list` sin `categories`. En HA 2026.11.1 (`websocket/repositories.py`) la respuesta es el resumen de 25 campos de cada repositorio del catálogo, incluidos `authors` y `topics`: miles de entradas. Pasa de `max_msg_size` (4 MiB) del cliente aiohttp, que entrega `WSMsgType.ERROR` y cierra; `_read_ws_messages` falla todas las peticiones pendientes con el texto genérico y la conexión se rehace. En vivo: sin categoría falla y deja `ha_ws_reconnect_failure`; con `integration` funciona. Descartado un parámetro no aceptado: el esquema solo tiene `categories` opcional y el comando sin él es válido.
- **R-2 — Filtro en el servidor.** HA solo filtra por `categories` (y por `last_fetched`). No hay filtro de instalados. Se pide una categoría por mensaje: `integration` primero (existe en las dos API y decide cuál hay), luego el resto de la API detectada. HACS 2.x acepta el mismo `categories`.
- **R-3 — Otros comandos grandes.** `config/entity_registry/list` (para `update_entity_id`) y los registros completos siguen siendo un mensaje; en instalaciones normales cabe y el live lo confirma. Se deja documentado como riesgo; no se toca `ha.py` (spec S-02).
- **R-4 — Por qué no se cumplía el límite.** No había mecanismo central: cada módulo recibía `response_max_bytes` por su cuenta y solo lo usaban history, logbook, statistics, registros de entidades y dispositivos, trazas, `search/related`, config entries, ficheros, backups de HA, Lovelace y Marketplace. Sin límite: `ha_get_states` y `ha_list_services` (`tools/ha.py`), automatizaciones, scripts, escenas, helpers, zonas, personas, áreas, plantas, etiquetas, categorías, repairs, flujos de config entries, plantillas, add-ons (`sv_get_addon_logs`, `sv_list_addons`), Supervisor, backups del Supervisor, resolución y `wait_for_event`. Además, el SDK serializa los `dict` con `indent=2`, así que hasta las tools que recortan pueden pasarse un poco del tope.
- **R-5 — Dónde va el guardián.** `HermesMCPServer.call_tool` es el único camino de `tools/call` y ya es donde se marca `isError`. El tope lo fija `register_all_tools`, que es quien resuelve el valor efectivo.
- **R-6 — Log.** 1.1.0 registra `pattern` en `fs_search_in_config_ok`, `fs_search_pattern_rejected`, `fs_search_timeout`, `fs_search_failed` y `fs_search_subprocess_killed`, y `template[:100]` en los cuatro eventos de `ha_render_template`. La redacción de red no puede reconocer una IP escrita como `192\.0\.2\.1`.

## Diseño

1. `tools/marketplace.py`: `_list_catalog(ha_client, category)` → `(api, lista)`; con categoría, un mensaje; sin ella, uno por categoría. Lo usan `list_repositories`, `get_repository` y `list_updates`.
2. `tools/_common.py`: `recortar_a_bytes(payload, max_bytes)` reutiliza `ajustar_lista_a_bytes`.
3. `mcp_server.py`: `HermesMCPServer.response_max_bytes` y `_limitar(result)` antes de marcar `isError`; `tools/__init__.py` lo asigna.
4. `tools/filesystem.py` y `tools/templates.py`: `pattern_len` / `template_len`.

## Ficheros

- Código: `hermes/src/hermes/tools/marketplace.py`, `hermes/src/hermes/mcp_server.py`, `hermes/src/hermes/tools/_common.py`, `hermes/src/hermes/tools/__init__.py`, `hermes/src/hermes/tools/ha.py` (docstring), `hermes/src/hermes/tools/filesystem.py`, `hermes/src/hermes/tools/templates.py`, `hermes/src/hermes/config.py`, `hermes/src/hermes/__init__.py`, `hermes/config.yaml`.
- Tests: `tests/test_tools_marketplace.py`, `tests/test_tools_hacs.py` (si su simulador lo necesita), `tests/test_response_limit.py` (nuevo), `tests/test_log_privacy_args.py` (nuevo).
- Docs: `hermes/CHANGELOG.md`, `hermes/DOCS.md`, `README.md`, `README.es.md`, `docs/HOJA-DE-RUTA.md`.
