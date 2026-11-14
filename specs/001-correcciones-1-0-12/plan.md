# Plan de implementación: Hermes 1.0.12 — correcciones frente a HA 2026.11

**Directorio**: `specs/001-correcciones-1-0-12` | **Fecha**: 2026-11-14 | **Spec**: [spec.md](./spec.md)

**Entrada**: especificación de `specs/001-correcciones-1-0-12/spec.md`.

**Rama de trabajo**: la que indique el mantenedor (spec-kit no crea ramas). Los
lotes se implementan en worktrees separados y se integran en esa rama.

## Resumen

Versión de solo arreglos. Corrige los 3 fallos con pérdida de datos (P1, P2,
P3), 6 rotos (R1–R6), 5 degradados (D1–D5) y los cosméticos C1–C6 y C8 de la
revisión de compatibilidad con HA 2026.11.1 y Supervisor 2026.11.0. El enfoque
técnico:

- Una **fase 0** pequeña y secuencial deja dos piezas compartidas: el código de
  error de Home Assistant en `HAConnectionError` y un helper que lee la versión
  de HA en tiempo de ejecución.
- Cuatro **lotes paralelos** (A Supervisor, B registros, C Lovelace, D
  automatizaciones/plantillas/servicios/HACS) que no comparten ningún fichero.
- Un **lote final de integración** con los ficheros compartidos (versión,
  CHANGELOG, guía, README, DOCS, hoja de ruta).

Detalles y alternativas en [research.md](./research.md); formas de respuesta en
[contracts/tools.md](./contracts/tools.md); estados y entidades en
[data-model.md](./data-model.md); validación en [quickstart.md](./quickstart.md).

## Contexto técnico

**Lenguaje/versión**: Python 3.13 (imagen `3.13-alpine3.23`).

**Dependencias principales**: SDK `mcp` 2.x (`MCPServer`), `aiohttp`, `pydantic` 2, `structlog`, `packaging` (ya declarada; se usa para comparar versiones de HA).

**Almacenamiento**: ficheros JSON en `/data` del add-on (`last_safety_backup.json`, `pending_jobs.json`). Sin base de datos.

**Pruebas**: `pytest` + `pytest-asyncio` + `aioresponses`, con los fakes de `tests/_ha_fixture.py` y los fakes locales de cada fichero de test. Comando: `.venv/bin/pytest` (ver `CONTRIBUTING.es.md:71-73`).

**Plataforma**: add-on de Home Assistant OS (amd64, aarch64); Home Assistant Core ≥ 2024.10.0 tras este cambio; Supervisor 2026.11.

**Tipo de proyecto**: servidor MCP (un solo paquete en `hermes/src/hermes/`, tests en `tests/`).

**Objetivos de rendimiento**: sin cambios; como mucho una llamada WS extra (`get_config`) en las tools que deciden por versión, y solo en la rama que lo necesita.

**Restricciones**: fail-closed en lo destructivo (principio III); vista previa veraz (IV); nombres y docstrings veraces (V); ningún dato personal (VIII); no tocar `.github/`, `hermes/Dockerfile` ni `hermes/build.yaml` (spec 002 en paralelo).

**Escala/alcance**: 186 tools hoy → 187 (se añade `ha_remove_device`). Unos 20 ficheros de código y 15 de tests.

## Comprobación contra la constitución

*Puerta: debe pasar antes de la fase 0 y repetirse tras el diseño.*

| Principio | Cómo se cumple | Estado |
|---|---|---|
| I. Seguridad primero | Los `errors` de jobs se devuelven saneados (solo `message`, recortado y pasado por `redact_secrets`); `sv_get_supervisor_info` sigue pasando por `redact_structure`. | OK |
| II. Secretos | Ningún mensaje nuevo incluye valores de configuración; los errores de jobs solo llevan el texto del Supervisor ya redactado. | OK |
| III. Fail-closed | `ha_remove_device` se niega sin versión; el borrado de dashboards se niega si no se sabe el panel por defecto; el safety backup bloquea la escritura en timeout o estado indeterminado. | OK |
| IV. Dos pasos y preview veraz | P2: preview que anuncia el borrado del dispositivo y el camino usado; P3: rechazo antes de emitir token; la tool antigua dice lo que hace. Tokens siguen atados a tool + argumentos. | OK |
| V. Nombre y descripción veraces | Tool nueva con nombre veraz; docstrings de C1, C3, D3, D4, P1/R6, P3 corregidos en el mismo cambio. Las anotaciones de `ha_remove_device` salen del prefijo `ha_remove_` (destructiva), sin tocar `_annotations.py`. | OK |
| VI. Probar lo arreglado | Cada FR tiene su test de regresión en el lote que lo implementa (ver tasks.md). | OK |
| VII. Control negativo | Cada lote tiene tareas «deshacer el arreglo y ver caer el test» y deja el recuento por escrito. | OK |
| VIII. Privacidad | Ejemplos con marcadores (`homeassistant.tailXXXX.ts.net`, `<slug>`); grep de datos personales y de identificadores de modelos antes de cada commit. | OK |
| IX. Cambios mínimos | Solo los IDs de la spec; C7, C9 y los riesgos de §2.5 quedan fuera (spec S-12). La única pieza nueva no pedida, `ha_version.py`, es la mínima para decidir por versión sin duplicar código en tres lotes. | OK, justificado |
| X. Comentarios en español con el porqué | Cada guarda nueva lleva el porqué (cambio de HA y versión). Descripciones vistas por el cliente, en inglés donde ya lo están. | OK |
| XI. Versión coherente | Lote de integración: 1.0.12 en `config.yaml`, `__init__.py` y `HA_CORE_LAST_TESTED_IN_HERMES`; CHANGELOG; README EN/ES sincronizados. | OK |

Repetida tras el diseño (fase 1): sin cambios; no hay violaciones que justificar.

## Estructura del proyecto

### Documentación (esta funcionalidad)

```text
specs/001-correcciones-1-0-12/
├── spec.md
├── plan.md              # este fichero
├── research.md          # decisiones técnicas y alternativas
├── data-model.md        # entidades y estados
├── quickstart.md        # cómo validar
├── contracts/tools.md   # formas de entrada y salida de las tools afectadas
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Código fuente (raíz del repositorio)

```text
hermes/
├── config.yaml                     # integración: version
├── CHANGELOG.md                    # integración
├── DOCS.md                         # integración (solo si cambia instalación/configuración)
└── src/hermes/
    ├── __init__.py                 # integración: __version__
    ├── config.py                   # integración: HA_CORE_MIN_SUPPORTED, HA_CORE_LAST_TESTED_IN_HERMES
    ├── ha.py                       # fase 0 (código de error) + lote D (delete por código, avisos de plantilla)
    ├── ha_version.py               # fase 0 (NUEVO)
    ├── fs_write.py                 # lote A
    ├── models/script.py            # lote D
    └── tools/
        ├── backups.py              # lote A
        ├── supervisor.py           # lote A
        ├── addons.py               # lote A (solo docstring)
        ├── registry_entity.py      # lote B
        ├── registry_device.py      # lote B
        ├── registry_area.py        # lote B
        ├── config_entries.py       # lote B
        ├── lovelace.py             # lote C
        ├── templates.py            # lote D
        ├── hacs.py                 # lote D
        ├── ha.py                   # lote D (ha_list_services, perform_action)
        ├── statistics.py           # lote D
        └── guide.py                # integración
tests/                              # cada test pertenece al lote de su código (ver tasks.md)
README.md, README.es.md             # integración
docs/HOJA-DE-RUTA.md                # integración
```

**Decisión de estructura**: se mantiene la estructura existente; solo se añade
`hermes/src/hermes/ha_version.py` y tres ficheros de test nuevos
(`tests/test_ha_version.py`, `tests/test_tools_hacs.py`,
`tests/test_tools_ha_services.py`) más `tests/test_ha_ws_error_code.py`.

## Decisiones técnicas por fichero

Las líneas son las de 1.0.11 (commit de la spec). Pueden moverse al editar.

### Fase 0 — Fundación (secuencial, antes de abrir los lotes)

| Fichero:línea | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/ha.py:34-44` | `HAConnectionError.__init__(*args, status=None, code=None)`; atributo `code: str \| None`. Compatible hacia atrás. | FR-030 |
| `hermes/src/hermes/ha.py:526-536` | `_handle_ws_message`: si `error` es dict, pasar `code=error.get("code")` (solo si es `str`) al construir `HAConnectionError`. El mensaje de texto no cambia. | FR-030 |
| `hermes/src/hermes/ha_version.py` (nuevo) | `async def ha_core_version(ha_client) -> Version \| None`: `ws_send({"type": "get_config"}, timeout_seconds=5)`, lee `version`, parsea con `packaging.version.Version` y devuelve `Version(v.base_version)`; `None` ante cualquier error o forma inesperada. `async def ha_at_least(ha_client, minimo: str) -> bool \| None`. Sin caché (spec S-03). | FR-017, FR-018, FR-036, FR-038 |
| `tests/test_ha_ws_error_code.py` (nuevo) | Mensaje `result` con `success: false` y `error.code` → la excepción lleva `code`; sin `code` → `None`. | FR-030 |
| `tests/test_ha_version.py` (nuevo) | Versión normal, `.dev0`, `landingpage`, error WS, respuesta no dict. | FR-017/018 |

### Lote A — Supervisor, jobs y safety backup

| Fichero:línea | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/fs_write.py:663-792` (`maybe_trigger_safety_backup`) | `_MARCA` sigue significando «último safety backup **correcto**»; lo pendiente va en claves aparte (`pending_job_id`, `pending_started_at`, `pending_backup_name`; ver data-model.md). (1) Lo primero, si hay `pending_job_id`: `GET /jobs/{id}`; terminado sin errores → `_MARCA = ahora`, borrar las claves pendientes y seguir (ya hay backup reciente, no se lanza otro); en curso → `{"error": "safety_backup_in_progress", "job_id": …}`; terminado con errores, 404 o forma rara → borrar las claves pendientes y devolver `safety_backup_job_failed` / `safety_backup_state_unknown` sin lanzar otro. (2) El límite duro de 60 s se mide desde el más reciente de `_MARCA` y `pending_started_at` (o el último intento), para que un fallo no permita lanzar backups seguidos. (3) Tras el `POST /backups/new/full` con `job_id`, guardar en el acto las claves pendientes. (4) Sondeo en `:767`: `/jobs/{job_id}` (sin `/info`); un error transitorio sigue sondeando, pero un 404 (`exc.status == 404`) termina con `safety_backup_state_unknown` y borra las claves pendientes. (5) Parseo `:775-787`: éxito = `done is True` y `errors` vacío → `_MARCA = ahora` y borrar pendientes; `done` con errores → borrar pendientes y `safety_backup_job_failed` con los mensajes saneados. (6) Timeout `:792`: las claves pendientes quedan guardadas; error con `job_id` y `poll_with: "sv_get_job_status"`. *Nota (revisión independiente, M2/M3): en (1), «`_MARCA = ahora`» era un error de la spec; el pendiente terminado bien toma `_MARCA = pending_started_at` y, si es más antiguo que la ventana, devuelve `safety_backup_stale` sin escribir. En curso con más de 2 h → `safety_backup_state_unknown` con `hint` y se borra el pendiente.* | FR-001…FR-005 |
| `hermes/src/hermes/tools/backups.py:91-102` (`_save_safety_state`) | Hoy funde con `update`; añadir que un valor `None` borre la clave, para poder limpiar las pendientes. `sv_create_safety_backup` (`:303-380`) no cambia (research R-A2). | FR-003, FR-004 |
| `hermes/src/hermes/tools/backups.py` (nuevo helper privado junto a `:105`) | `_job_errors(data) -> list[str]`: de `data["errors"]` toma `message` si es `str`, si no `"unknown error"`; recorta cada mensaje (p. ej. 500 caracteres) y lo pasa por `redact_secrets`. Lo usan `fs_write.py` y `sv_get_job_status`. | FR-002, FR-006 |
| `hermes/src/hermes/tools/backups.py:628-672` (`sv_get_job_status`) | Añadir `errors` y `success` (`True` si `done` y sin errores; `False` si `done` con errores; `None` si no `done`). En `:661-667`, `status = "failed"` si hay errores. Docstring `:630-643` actualizado. | FR-006, FR-007 |
| `hermes/src/hermes/tools/backups.py:674-700` (`sv_list_pending_jobs`) | Docstring: `status` puede ser `running`, `done` o `failed`. | FR-007 |
| `hermes/src/hermes/tools/backups.py:145-170` (`sv_list_backups`) | Solo docstring: `location: null` = local; `protected` de la primera ubicación. | FR-010 |
| `hermes/src/hermes/tools/supervisor.py:46-69` | Tras `/supervisor/info`, `GET /info` en su propio `try`: `machine` ← `info["machine"]`, `docker_version` ← `info["docker"]`; si falla, `None` en ambos. `redact_structure` en ambas respuestas. | FR-008 |
| `hermes/src/hermes/tools/supervisor.py:72-100` | `kernel_version` ← `data.get("kernel")`; docstring `:76-79`: `boot_timestamp` entero en µs, `disk_*` en GiB. | FR-009 |
| `hermes/src/hermes/tools/addons.py:912-929` | Solo docstring de `sv_get_addon_stats` (`blk_read`, `blk_write`, `cpu_usage`, `memory_percent`…). | FR-010 |
| `tests/test_fs_write_security.py` (clase del safety backup, `:830-900`) | Tests nuevos con `job_id` real: ruta `/jobs/{id}`; `done`+`errors` vacío → None; `done`+errores → error y no escribe; timeout → marca pendiente guardada; siguiente llamada con pendiente en curso/terminado/fallido. El test síncrono existente se conserva. | FR-001…FR-005 |
| `tests/test_tools_supervisor.py` | `sv_get_job_status` con errores → `success: false`, `errors`, `pending_jobs` `failed`; `sv_get_supervisor_info` con `/info`; `/info` caído; `sv_get_host_info` con `kernel`. | FR-006…FR-009 |

### Lote B — Registros de entidades y dispositivos

| Fichero:línea | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/tools/registry_entity.py:74-77` | `aliases`: `None` → error `aliases must be a list; use [] to clear or [null] to keep only the computed name`; lista → `[a if a is None else str(a) for a in v]`, rechazando `list`/`dict` dentro. | FR-011, FR-012 |
| `hermes/src/hermes/tools/registry_entity.py:250, 260` | Docstring de `name` (solo parte de la entidad desde 2026.11) y de `aliases` (null = nombre calculado; la lista sustituye; conservar el null). | FR-013, FR-014 |
| `hermes/src/hermes/tools/registry_entity.py:218-230` | `except HAConnectionError as exc`: si `exc.code == "not_found"` → `{"error": "not_found", "entity_id": …}`. | FR-015 |
| `hermes/src/hermes/tools/registry_entity.py:160-170` | Filtro `area_id`: entidad con `area_id == X`, o `area_id` nulo y `device_id` cuyo área efectiva es X (lee `config/device_registry/list` solo si se pasa `area_id`). Docstring. | FR-021 |
| `hermes/src/hermes/tools/registry_device.py` (helper nuevo cerca de `:35`) | `effective_area_id(device, by_id, max_depth=8)`: área propia; si nula y hay `parent_device_id`, la del padre; corta en ciclo o profundidad. Lo importan `registry_entity.py` y `registry_area.py` (mismo lote). | FR-020…FR-022 |
| `hermes/src/hermes/tools/registry_device.py:121-126` | Filtro `area_id` con área efectiva; `manufacturer` sin cambios. Docstrings `:1-14` y `:95-110`: `config_entry_id`, `parent_device_id`, hijos sin fabricante, `config_entries` deprecado en 2027.8. | FR-020, FR-024 |
| `hermes/src/hermes/tools/registry_device.py` (tool nueva tras `:370`) | `ha_remove_device(device_id, confirmation_token=None)`. Sin token: leer el dispositivo (`config/device_registry/list`, buscar por id; no existe → `not_found`), contar entidades (`config/entity_registry/list`, `device_id`), versión con `ha_at_least(…, "2026.9.0")`: `None` → `{"error": "ha_version_unknown"}` sin token; `True` → método `remove`; `False` → si el dispositivo tiene exactamente una integración (`config_entry_id` o `config_entries`) método `remove_config_entry` con esa id, si no `{"error": "multiple_config_entries"}` sin token. Preview: `action: "delete_device"`, `method`, `entities_count`, `warning` veraz. Con token: los args atados son solo `device_id`; se recalcula el método y si difiere del de la preview → error y token marcado como fallido. Envía `config/device_registry/remove {device_id}` o `config/device_registry/remove_config_entry {device_id, config_entry_id}`. | FR-016…FR-018 |
| `hermes/src/hermes/tools/registry_device.py:290-348` | `ha_remove_device_from_config_entry`: docstring con `DEPRECATED` (retirada antes de HA 2027.9; en HA ≥ 2026.9 borra el dispositivo entero si la integración es la suya; usar `ha_remove_device`). Preview `:320-325`: `deprecated: true`, `replacement: "ha_remove_device"`, `warning` veraz. El envío no cambia. | FR-019 |
| `hermes/src/hermes/tools/registry_area.py:56-100` (`_count_area_dependents`) | Contar dispositivos por área efectiva (un hijo sin área cuenta en el área de su padre) y sus entidades heredadas. | FR-022 |
| `hermes/src/hermes/tools/config_entries.py:64-72` | `devices_count`: dispositivo cuenta si `d.get("config_entry_id") == entry_id` **o** `entry_id in d.get("config_entries") or []`, una sola vez. | FR-023 |
| `tests/test_tools_registry_entity.py` | `[null, "x"]` llega intacto; `null` rechazado sin llamada WS; `not_found` por código; filtro de área heredada. | FR-011…FR-015, FR-021 |
| `tests/test_tools_registry_device.py` | `ha_remove_device` (≥ 2026.9, < 2026.9 una entry, varias entries, versión desconocida, no existe, método cambia entre preview y ejecución, anotación destructiva); tool antigua deprecada; filtro de área con hijo y con ciclo. | FR-016…FR-020, FR-024 |
| `tests/test_tools_registry_area.py` | Preview de `ha_delete_area` cuenta hijos sin área propia. | FR-022 |
| `tests/test_tools_config_entries.py` | Recuento con hijo (`config_entry_id`) y con dispositivo que tiene ambos campos (no se duplica). | FR-023 |

### Lote C — Lovelace

| Fichero:línea | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/tools/lovelace.py` (helper nuevo cerca de `:130`) | `_default_panel(ha_client) -> tuple[str \| None, str \| None]` (valor, error): `ws_send({"type": "frontend/get_system_data", "key": "core"})`; extrae `default_panel` de la forma real (comprobar en el código de HA, research R-C1); `HAConnectionError` con `code == "unknown_command"` → `(None, None)` (HA sin la función); otro error o forma rara → `(None, "default_panel_unknown")`. | FR-025, FR-026 |
| `hermes/src/hermes/tools/lovelace.py:586-590` | Guarda única antes de todo (y antes de mirar el token): `url_path` nulo o `"lovelace"` → `cannot_delete_default_dashboard`; leer `_default_panel`: error → `{"error": "default_panel_unknown", …}`; igual al `url_path` → `cannot_delete_default_dashboard`. Sin opción para saltárselo. | FR-025, FR-026 |
| `hermes/src/hermes/tools/lovelace.py:167, 579-580` | Docstrings: qué está protegido y por qué (migración de HA 2026.2). | FR-027 |
| `hermes/src/hermes/tools/lovelace.py:172-186` | Si algún extra tiene `url_path == "lovelace"`, no añadir el sintético y marcar ese con `is_default: True`; si no, como hasta ahora. | FR-028 |
| `hermes/src/hermes/tools/lovelace.py:685` | `{"type": "lovelace/resources/list"}`. | FR-029 |
| `tests/test_tools_lovelace.py` | `:186` pasa a `lovelace/resources/list` y se añade el test de regresión; borrado de `lovelace`, del panel por defecto, con panel indeterminado y con `unknown_command`; nunca se emite token; lista sin duplicado. | FR-025…FR-029 |

### Lote D — Automatizaciones, scripts, plantillas, errores WS, servicios, estadísticas y HACS

| Fichero:línea | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/ha.py:858-875` (`ws_collection_delete`) | `except HAConnectionError as exc: if exc.code == "not_found": return False; raise`. Se quita la búsqueda por texto. | FR-031 |
| `hermes/src/hermes/ha.py:649-717` (`ws_one_shot_subscription`) | Parámetro nuevo `collect_warnings: bool = False`. Con `True`, los eventos `{"error", "level": "WARNING"}` sin `result` se acumulan y se sigue esperando (cola en vez de future único, dentro del mismo plazo total); devuelve el primer evento con `result` o con error no WARNING, con `"warnings": [...]` añadido. Con `False`, comportamiento idéntico al actual. | FR-033 |
| `hermes/src/hermes/tools/templates.py:94-133` | Llamar con `collect_warnings=True`; respuesta de éxito con `warnings` si hay; timeout: `"Timeout" in str(exc)` **o** `"Exceeded maximum execution time" in str(exc)` → `template_timeout`. Docstring `:44-82`. | FR-033, FR-034 |
| `hermes/src/hermes/models/script.py:21` | `trace: dict[str, Any] \| None = None`. | FR-032 |
| `hermes/src/hermes/tools/ha.py:460-466` (`ha_list_services`) | `domain: str \| None = None`; filtra la lista `[{domain, services}]` por `domain`; sin coincidencias → `[]`. Docstring recomienda el filtro. | FR-035 |
| `hermes/src/hermes/tools/ha.py:161-167` | Comentario: `perform_action` no es clave de HA; se mantiene como defensa en profundidad (solo falsos positivos). | FR-040 |
| `hermes/src/hermes/tools/statistics.py:254-260` | Si `period == "year"` y `ha_at_least(…, "2026.3.0") is False` → `{"error": "period_not_supported", "detail": "period 'year' requires Home Assistant 2026.3 or newer"}`; `None` → seguir. | FR-036 |
| `hermes/src/hermes/tools/statistics.py:124-160` | Docstring de `ha_list_statistic_ids` con los campos reales y `has_mean` deprecado. | FR-037 |
| `hermes/src/hermes/tools/hacs.py:22-29` | `_VALID_CATEGORIES = {"integration", "plugin", "theme", "python_script", "appdaemon", "template"}`; disclaimer sin «update Hermes». | FR-039 |
| `hermes/src/hermes/tools/hacs.py` (helper nuevo) + `:49-54, 91, 118, 144` | `_hacs_error(ha_client, exc)`: si `exc.code == "unknown_command"`: `ha_at_least(…, "2026.11.0")` `True` → `{"error": "hacs_moved_to_marketplace", "hint": "HACS is built into Home Assistant as the Marketplace since 2026.11. Pending updates: ha_get_states(domain='update')."}`; `False`/`None` → `{"error": "hacs_not_installed", …}`; otro código → mensaje actual. | FR-038 |
| `hermes/src/hermes/tools/hacs.py:150-160` | `ha_hacs_list_updates`: si el repo trae `pending_upgrade` (bool), usarlo; si no, la comparación actual. | FR-039 |
| `tests/test_tools_templates.py` | `ws_one_shot_subscription(collect_warnings=True)` con aviso + resultado; plantilla con aviso devuelve resultado y `warnings`; timeout de HA → `template_timeout`. | FR-033, FR-034 |
| `tests/test_tools_counter.py` | `ha_delete_counter` de un id inexistente con error `code: "not_found"` y mensaje «Unable to find…» → `not_found`. | FR-031 |
| `tests/test_tools_scripts.py` | `trace` dict aceptado; lista rechazada. | FR-032 |
| `tests/test_tools_ha_services.py` (nuevo) | Filtro `domain`; dominio inexistente; sin filtro igual que antes. | FR-035 |
| `tests/test_tools_statistics.py` | `year` con 2026.2 → error; con 2026.3 → pasa; versión desconocida → pasa. | FR-036 |
| `tests/test_tools_hacs.py` (nuevo) | `unknown_command` con 2026.11 y con 2026.10; categorías; `pending_upgrade`. | FR-038, FR-039 |
| `tests/test_security_regressions.py:211-212` | Renombrar/redocumentar el test de `perform_action` como defensa en profundidad (sigue esperando `True`). | FR-040 |

### Lote de integración (al final, tras fusionar A–D)

| Fichero:línea | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/config.py:27` | `HA_CORE_MIN_SUPPORTED = "2024.10.0"` con comentario del porqué (plurales de automatizaciones). | FR-041 |
| `hermes/src/hermes/config.py:41` | `HA_CORE_LAST_TESTED_IN_HERMES = "1.0.12"`; `HA_CORE_LAST_TESTED` sigue en `2026.11.1` (spec S-11). | FR-044 |
| `hermes/src/hermes/__init__.py:6`, `hermes/config.yaml:7` | `1.0.12`. | FR-044 |
| `hermes/CHANGELOG.md:3` | Entrada `## [1.0.12] — 2026-11-14`, con una sección `### Fixed` por arreglo y el porqué. | FR-044 |
| `hermes/src/hermes/tools/guide.py:145-146` | Ejemplo con `triggers: [{"trigger": "sun", …}]` y `actions: [{"action": "light.turn_on", …}]`. | FR-042 |
| `hermes/src/hermes/tools/guide.py:23, 212-214` | `~187 tools`; añadir `ha_remove_device` (y marcar la antigua como deprecada). | FR-042 |
| `hermes/src/hermes/tools/_annotations.py:17, 20` | No se toca: «~186» es aproximado y el fichero no es de ningún lote. (Anotado para no tocarlo de paso.) | — |
| `README.md:63, 278`, `README.es.md:65, 283` | Versión mínima 2024.10.0. | FR-041 |
| `README.md:87-150`, `README.es.md:89-152` | Funnel recomendado en 8443 (o 10000): `tailscale funnel --bg --https=8443 8765`, `public_hostname: homeassistant.tailXXXX.ts.net:8443`, URL del conector con `:8443/mcp`; cómo migrar desde 443; 443 sigue valiendo si no se usa `share_homeassistant: funnel`. | FR-043 |
| `hermes/DOCS.md` | Solo si menciona la URL del conector o el puerto del Funnel; hoy no (comprobado con grep), así que en principio sin cambios. | FR-043 |
| `docs/HOJA-DE-RUTA.md:7, 30-66, 89-93, 96-118` | Estado tras 1.0.12: problemas corregidos, recomendación de Funnel en 8443/10000 (hoy dice lo contrario en `:89-93`), lo que queda para 1.1.0. | FR-045 |
| `tests/test_addon_manifest.py` | Comprobación de que `HA_CORE_MIN_SUPPORTED == "2024.10.0"` (la pareja de versiones ya la vigila este fichero). | FR-041, FR-044 |
| `tests/test_tools_guide.py` | El ejemplo de la guía no contiene `"platform":` ni `"service":`. | FR-042 |

## Seguimiento de complejidad

| Desviación | Por qué hace falta | Alternativa más simple descartada |
|---|---|---|
| Fase 0 secuencial antes de los lotes paralelos | Lotes B, C y D necesitan `HAConnectionError.code` y B y D la versión de HA; si cada lote los añadiera, editarían el mismo `ha.py` en paralelo. | Que cada lote compare textos o lea la versión a su manera: duplica código y reintroduce D1. |
| Módulo nuevo `ha_version.py` | La preview de P2 debe saber qué comando se usará **antes** de ejecutar (principio IV); C8 y R3 necesitan lo mismo. | Probar el comando nuevo y caer al viejo con `unknown_command`: la preview no podría decir qué hará. |
