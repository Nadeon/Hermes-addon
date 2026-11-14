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

- **R-7 — Revisión de la 1.1.1.** B-1: history y statistics ajustaban el `{id: [puntos]}` al tope y lo envolvían después (60-150 bytes más); el guardián no veía lista arriba y devolvía `response_too_large` en 159/200 y 50/50 casos simulados. Además devolvían `json.dumps` con `ensure_ascii` por defecto, más largo que lo medido. A-1: `create_confirmation_token` anida la vista previa en `preview`, así que el guardián la sustituía entera por el error y se perdía el token. M-1: logbook, registros y config entries con el mismo problema de envoltorio; el guardián quitaba más y dejaba `count`/`truncated_at` viejos. M-2: un log es un texto. M-3: el único tope efectivo de mensaje WS es el de Hermes (el Supervisor reenvía hasta 64 MiB). `fs_read_file` reservaba 2 KiB fijos sin contar el escapado JSON.
- **R-8 — CIMD.** claude.ai usa CIMD en producción (`client_id` en el host `claude.ai`, comprobado en vivo), pero `CimdResolver.resolve` no registraba nada salvo los rechazos y la copia caducada.

## Diseño

1. `tools/marketplace.py`: `_list_catalog(ha_client, category)` → `(api, lista)`; con categoría, un mensaje; sin ella, uno por categoría. Lo usan `list_repositories`, `get_repository` y `list_updates`.
2. `tools/_common.py`: `recortar_a_bytes(payload, max_bytes)` reutiliza `ajustar_lista_a_bytes`.
3. `mcp_server.py`: `HermesMCPServer.response_max_bytes` y `_limitar(result)` antes de marcar `isError`; `tools/__init__.py` lo asigna.
4. `tools/filesystem.py` y `tools/templates.py`: `pattern_len` / `template_len`.
5. `tools/history.py`, `statistics.py`: `_envolver(...)` arma la respuesta completa y el recorte la mide entera. `logbook.py`, `registry_entity.py`, `registry_device.py`, `config_entries.py`: `ajustar_lista_a_bytes` con la respuesta completa. `filesystem.py` (`fs_read_file`): coste escapado por línea y verificación final. `addons.py`: `_ultimas_lineas_que_caben`.
6. `tools/_common.py`: en `recortar_a_bytes`, ruta de vista previa (`_recortar_vista_previa`) antes que ninguna otra; `_recortar_dict_de_listas`; `_corregir_recuentos`; pista propia del error.
7. `config.py` / `config.yaml` / `run.sh` / `__main__.py`: `WS_MAX_MSG_SIZE_DEFAULT` y `_LEGACY_DEFAULT` con su pista; `ha.py`: `_mensaje_demasiado_grande` y `ha_ws_message_too_big`.
8. `cimd.py`: `oauth_cimd_document` en `CimdResolver.resolve`. `marketplace.py`: `_ws_read(..., api=)` y `category` en el error.

- **R-9 — Verificación de la 1.1.1.** N-1: `_recortar_dict_de_listas` miraba solo la forma «todo listas», que también tienen un script sin `alias` (`{"sequence": [...]}`) y una vista de Lovelace (`{"cards": [...]}`, con `top_level_keys` vacío en un dashboard solo con `views`); salían recortados con `is_error: false` y se podían guardar. N-2: los topes por cantidad no tocaban `truncated`. N-3: history y statistics reserializaban la respuesta entera por cada punto quitado (20 × 500 estados: unos 60 s de CPU con el bucle de eventos bloqueado).

## Diseño de la verificación

9. `mcp_server.py`: lista blanca `RECORTE_ANIDADO` por nombre de tool; `_limitar(..., recortar_anidadas)` y `recortar_a_bytes(..., recortar_anidadas=False)`: por defecto no se mira nada anidado (fail-closed).
10. `tools/_common.py`: `recortar_grupos_a_bytes`, el bucle lineal que ya usaba la red de seguridad, compartido por `_recortar_dict_de_listas`, `history.py` y `statistics.py`.
11. `history.py`, `statistics.py`, `logbook.py`: `ya_recortado` cuando el tope por cantidad quitó algo; la respuesta se mide ya con `truncated_at`.

## Ficheros

- Código: `hermes/src/hermes/tools/marketplace.py`, `hermes/src/hermes/mcp_server.py`, `hermes/src/hermes/tools/_common.py`, `hermes/src/hermes/tools/__init__.py`, `hermes/src/hermes/tools/ha.py` (docstring), `hermes/src/hermes/tools/filesystem.py`, `hermes/src/hermes/tools/templates.py`, `hermes/src/hermes/config.py`, `hermes/src/hermes/__init__.py`, `hermes/config.yaml`.
- Tests: `tests/test_tools_marketplace.py`, `tests/test_tools_hacs.py` (si su simulador lo necesita), `tests/test_response_limit.py` (nuevo), `tests/test_log_privacy_args.py` (nuevo).
- Revisión de 1.1.1: `hermes/src/hermes/tools/{history,statistics,logbook,registry_entity,registry_device,config_entries,filesystem,filesystem_write,addons,guide,marketplace,__init__}.py`, `hermes/src/hermes/{ha,cimd,config,__main__,mcp_server}.py`, `hermes/run.sh`; tests en `tests/test_response_limit.py`, `test_ha_ws_reliability.py`, `test_config_validation.py`, `test_run_sh_options.py`, `test_main_wiring.py`, `test_cimd.py` y `test_tools_marketplace.py`; docs en `SECURITY.md` además de los de abajo.
- Docs: `hermes/CHANGELOG.md`, `hermes/DOCS.md`, `README.md`, `README.es.md`, `docs/HOJA-DE-RUTA.md`.
