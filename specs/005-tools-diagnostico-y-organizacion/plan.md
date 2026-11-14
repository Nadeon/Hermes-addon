# Plan de implementación: Hermes 1.1.0 — tools de diagnóstico y organización

**Directorio**: `specs/005-tools-diagnostico-y-organizacion` | **Fecha**: 2026-11-14 | **Spec**: [spec.md](./spec.md)

**Entrada**: especificación de `specs/005-tools-diagnostico-y-organizacion/spec.md`.

**Rama de trabajo**: la que indique el mantenedor (spec-kit no crea ramas),
encima de 1.0.12 ya integrada. Los bloques se implementan en worktrees
separados y se integran en esa rama.

## Resumen

Añade 23 tools y una opción, sin cambiar el comportamiento de las tools
existentes salvo la anotación de `sv_create_safety_backup` en la retención:

- **Organización** (12 tools): CRUD de plantas, etiquetas y categorías, con
  borrados y ediciones en dos pasos y vistas previas que distinguen lo que Home
  Assistant limpiará de lo que dejará de resolver.
- **Diagnóstico** (5 tools): Repairs (leer e ignorar con confirmación), trazas
  resumidas, redactadas y con límite de tamaño, y `search/related`.
- **Supervisor y backups** (6 tools): resolución del Supervisor (leer y
  descartar, nunca aplicar) y backups de la integración `backup` de Home
  Assistant con lista blanca y la contraseña siempre fuera.
- **Retención** (opción `safety_backup_keep`): poda de los safety backups que
  Hermes lanzó y confirmó, fail-closed, tras cada safety backup automático
  correcto.

Tres bloques paralelos que no comparten ficheros y un bloque de integración al
final. Detalles y alternativas en [research.md](./research.md); formas de
respuesta en [contracts/tools.md](./contracts/tools.md); entidades y estados
en [data-model.md](./data-model.md); validación en
[quickstart.md](./quickstart.md).

## Contexto técnico

**Lenguaje/versión**: Python 3.13 (imagen `3.13-alpine3.23`).

**Dependencias principales**: SDK `mcp` 2.x (`MCPServer`), `aiohttp`, `pydantic` 2, `structlog`, `packaging`. Ninguna nueva.

**Base**: 1.0.12 — `HAConnectionError.code`, `hermes/src/hermes/ha_version.py` (`ha_at_least`), safety backup con `GET /jobs/{id}` y anotación pendiente en `last_safety_backup.json`.

**Almacenamiento**: ficheros JSON en `/data`. Nuevo: `/data/safety_backups.json` (anotación de safety backups). Sin base de datos.

**Pruebas**: `pytest` + `pytest-asyncio` + `aioresponses`, con `tests/_ha_fixture.py` (`make_ready_client`) y un `DummyMCP` local por fichero, como `tests/test_tools_registry_area.py`. Las respuestas del Supervisor se simulan con `aioresponses` o sustituyendo `sv_request`, como `tests/test_tools_supervisor.py`. Comando: `.venv/bin/pytest`.

**Plataforma**: add-on de Home Assistant OS (amd64, aarch64); Home Assistant Core ≥ 2024.10.0; Supervisor 2026.11.

**Tipo de proyecto**: servidor MCP (un paquete en `hermes/src/hermes/`, tests en `tests/`).

**Objetivos de rendimiento**: una llamada WS por lectura; las vistas previas de borrado hacen como mucho 4 lecturas (tres registros y `search/related`); la poda, una lectura y hasta 5 borrados.

**Restricciones**: fail-closed en vistas previas y retención (principio III); vista previa veraz (IV); nombres y anotaciones veraces (V); nada en crudo hacia el cliente (I, II); ningún dato personal (VIII); no tocar `.github/`, `hermes/Dockerfile` ni `hermes/build.yaml`; no subir la versión (spec S-15).

**Escala/alcance**: 23 tools nuevas (187 tras 1.0.12 → 210 solo con esta spec; el recuento final de 1.1.0 lo da el registro). 9 módulos nuevos o tocados en código, 9 ficheros de test nuevos y 5 existentes en integración.

## Comprobación contra la constitución

*Puerta: debe pasar antes de la fase 0 y repetirse tras el diseño.*

| Principio | Cómo se cumple | Estado |
|---|---|---|
| I. Seguridad primero | Backups de HA por lista blanca; trazas y Repairs redactados; resolución pasada por `redact_structure`; `issue_data` no se expone. | OK |
| II. Secretos | `create_backup.password` nunca sale (`password_set`); tests con centinelas (contraseña, `instance_id`, `access_token`, `?token=`) que deben dar 0 apariciones. | OK |
| III. Fail-closed | Vistas previas sin datos completos → sin token; retención: cualquier duda → no borra; anotación ilegible → no borra; versión por debajo del mínimo → error sin llamar. | OK |
| IV. Dos pasos y preview veraz | Borrados y ediciones de registros, `ha_ignore_repair` y descartes del Supervisor con token atado a tool + argumentos; las vistas previas separan «asignación que HA quita» de «referencia que deja de resolver». **Desviación**: la poda de safety backups borra sin token (ver «Seguimiento de complejidad»). | OK, justificado |
| V. Nombre y descripción veraces | `ha_update_*` solo editan; `ha_search_related` en `_READ_ONLY_EXACT`; todo lo que pide token en `_DESTRUCTIVE_EXACT`; `sv_create_safety_backup` no poda (si podara, «create» mentiría) y su descripción dice que entra en la retención. | OK |
| VI. Probar lo arreglado | Cada tool y la retención tienen tests previos (tasks.md). | OK |
| VII. Control negativo | Una tarea de control negativo por tool o guarda, con recuento en el commit del bloque. Los commits de bloque no se publican; la suite completa pasa tras la integración (research R-0.3). | OK |
| VIII. Privacidad | Ejemplos con marcadores (`example.invalid`, `<slug>`); centinelas claramente falsos; grep de privacidad antes de cada commit. | OK |
| IX. Cambios mínimos | Solo lo de la spec; fuera: aplicar sugerencias, cifrado, flujos de reparación, `reorder`, validar asignaciones en tools existentes (spec S-14). `ha_update_area` no se toca aunque falle abierto en su vista previa. | OK |
| X. Comentarios en español con el porqué | Cada guarda nueva (lista blanca, centinela de retención, límite de trazas) lleva el porqué; descripciones al cliente en inglés. | OK |
| XI. Versión coherente | No se sube la versión (decisión de publicación); CHANGELOG bajo 1.1.0; README EN/ES sincronizados; DOCS con la opción nueva. | OK |

Repetida tras el diseño (fase 1): sin cambios; la única desviación está justificada abajo.

## Estructura del proyecto

### Documentación (esta funcionalidad)

```text
specs/005-tools-diagnostico-y-organizacion/
├── spec.md
├── plan.md              # este fichero
├── research.md          # decisiones técnicas y alternativas
├── data-model.md        # entidades, estados y anotación de safety backups
├── quickstart.md        # cómo validar
├── contracts/tools.md   # firmas, anotaciones y respuestas de las 23 tools
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Código fuente (raíz del repositorio)

```text
hermes/
├── config.yaml                       # integración: schema y default de safety_backup_keep
├── run.sh                            # integración: HERMES_SAFETY_BACKUP_KEEP
├── CHANGELOG.md                      # integración
├── DOCS.md                           # integración
└── src/hermes/
    ├── config.py                     # integración: campo safety_backup_keep
    ├── fs_write.py                   # bloque C: anotar y podar tras el éxito
    ├── safety_retention.py           # bloque C (NUEVO)
    └── tools/
        ├── __init__.py               # integración: registrar 8 módulos y pasar la opción
        ├── _annotations.py           # integración
        ├── guide.py                  # integración
        ├── registry_floor.py         # bloque A (NUEVO)
        ├── registry_label.py         # bloque A (NUEVO)
        ├── registry_category.py      # bloque A (NUEVO)
        ├── repairs.py                # bloque B (NUEVO)
        ├── traces.py                 # bloque B (NUEVO)
        ├── search.py                 # bloque B (NUEVO)
        ├── resolution.py             # bloque C (NUEVO)
        ├── ha_backups.py             # bloque C (NUEVO)
        ├── backups.py                # bloque C: sv_create_safety_backup anota
        └── filesystem_write.py       # bloque C: register_write(safety_backup_keep)
tests/                                # cada test pertenece al bloque de su código (tasks.md)
README.md, README.es.md, docs/HOJA-DE-RUTA.md   # integración
```

**Decisión de estructura**: un módulo por familia, como `registry_area.py`.
Las tools de organización van en tres módulos (y no en uno) para que cada uno
tenga el tamaño de `registry_area.py` y sus tests se lean solos.

## Decisiones técnicas por fichero

Las líneas son las de 1.0.11; tras 1.0.12 pueden haberse movido. Se citan para
orientar, no como contrato.

### Bloque A — Plantas, etiquetas y categorías

| Fichero | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/tools/registry_floor.py` (nuevo) | `register(mcp, ha_client)` con `ha_list_floors`, `ha_create_floor`, `ha_update_floor`, `ha_delete_floor`. `_validate_floor_fields` (como `_validate_area_fields`, `registry_area.py:32-53`, pero rechazando claves desconocidas). Vista previa de borrado: `config/floor_registry/list` (entrada actual), `config/area_registry/list` (áreas con `floor_id`), `search/related {item_type: "floor"}` (automation/script/scene); cualquier fallo → `preview_unavailable`. Listas de ids acotadas a 50 (`_acotar(ids)` local). Con token: `config/floor_registry/delete`; `complete_confirmation_token` en éxito y error. | FR-001…FR-005, FR-008…FR-010 |
| `hermes/src/hermes/tools/registry_label.py` (nuevo) | Ídem para etiquetas; `_THEME_COLORS` (26) y `#rrggbb`. Vista previa: `config/label_registry/list`, `config/area_registry/list`, `config/device_registry/list`, `config/entity_registry/list` (`label_id in labels`) y `search/related {item_type: "label"}`. | FR-001…FR-004, FR-006, FR-008…FR-010 |
| `hermes/src/hermes/tools/registry_category.py` (nuevo) | Ídem con `scope` obligatorio en los cuatro comandos; `_SCOPES = {"automation", "script", "scene", "helpers"}`. Vista previa: `config/category_registry/list {scope}` y `config/entity_registry/list` (`categories.get(scope) == category_id`). | FR-001…FR-004, FR-007…FR-010 |
| `tests/test_tools_registry_floor.py`, `tests/test_tools_registry_label.py`, `tests/test_tools_registry_category.py` (nuevos) | Fake WS por comando; ver tasks.md. | idem |

### Bloque B — Diagnóstico

| Fichero | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/tools/repairs.py` (nuevo) | `ha_list_repairs` (`repairs/list_issues` → resumen, filtros, orden por gravedad, `translation_placeholders` con `redact_structure` + `redact_secrets`) y `ha_ignore_repair` (lee la lista; `not_found`/`unchanged` sin token; preview; `repairs/ignore_issue`). | FR-011…FR-013 |
| `hermes/src/hermes/tools/traces.py` (nuevo) | `register(mcp, ha_client, response_max_bytes=…)`. `_resolver_item_id(domain, item_id, entity_id)` con `config/entity_registry/get` → `unique_id`. `ha_list_traces` (`trace/list`, orden por `timestamp.start` desc, `limit`). `ha_get_trace` (`trace/get`; `_resumen(trace)`, `_completo(trace)`, `_ajustar_a_limite(doc, limite)` con el orden de recorte de research R-B2; `not_found` por `exc.code`). `_TRACE_MAX_BYTES = 65536`. | FR-014…FR-019 |
| `hermes/src/hermes/tools/search.py` (nuevo) | `register(mcp, ha_client)`. `_ITEM_TYPES` (14). `ha_search_related`: validación; con `include_disabled_entities` → `ha_at_least(…, "2026.10.0")`; `False` → `ha_version_unsupported`; `None` → envía y traduce `invalid_format`. Recorte a 200 por tipo. | FR-020, FR-021 |
| `tests/test_tools_repairs.py`, `tests/test_tools_traces.py`, `tests/test_tools_search_related.py` (nuevos) | Ver tasks.md. | idem |

### Bloque C — Supervisor, backups de HA y retención

| Fichero | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/tools/resolution.py` (nuevo) | `register(mcp, ha_client)`. `sv_get_resolution` (`GET /resolution/info`, normalizado y `redact_structure`). `sv_dismiss_resolution_issue` / `sv_dismiss_resolution_suggestion` (`validate_identifier`; preview buscando el uuid en `/resolution/info`; `DELETE /resolution/issue/{uuid}` o `/resolution/suggestion/{uuid}`). Ningún `POST` a `/resolution/suggestion/`. | FR-022…FR-025 |
| `hermes/src/hermes/tools/ha_backups.py` (nuevo) | `register(mcp, ha_client)`. `_comprobar_version()` con `ha_at_least(…, "2025.1.0")`. `_backup_permitido(b)` y `_config_permitida(c)` por lista blanca (data-model.md); `password_set`; `_mascara_red(texto)` (IPv4, IPv6, host de URL) + `redact_secrets` + recorte a 300 para `agent_errors`; `redact_structure` final. `unknown_command` → `backup_integration_unavailable`. | FR-026…FR-030 |
| `hermes/src/hermes/safety_retention.py` (nuevo) | `LEDGER_PATH = Path("/data/safety_backups.json")`; `_lock = asyncio.Lock()`; `async def record_launch(name, job_id, origin, slug=None)`; `async def confirm_from_job(job_id, job_data)` (solo `done is True`, `errors` vacío, `reference` texto); `async def apply_retention(ha_client, keep) -> dict` (algoritmo de data-model.md; nunca lanza: captura todo, registra `safety_backup_retention_*` y devuelve un resumen); `_NOMBRE_RE` con los dos formatos; `_MAX_BORRADOS = 5`; `_VENTANA_NOMBRE_S = 600`; `_CADUCIDAD_SIN_CONFIRMAR_S = 7 * 86400`; `_MAX_ENTRADAS = 100`. | FR-031…FR-037 |
| `hermes/src/hermes/fs_write.py` (`maybe_trigger_safety_backup`) | Parámetro nuevo `keep: int = 0`. Tras recibir `job_id` (o `slug` síncrono): `record_launch(..., origin="auto")`. En cada camino de éxito confirmado de 1.0.12 (sondeo terminado sin errores; pendiente resuelto como correcto en la llamada siguiente): `confirm_from_job(...)` y después `await apply_retention(ha_client, keep)`. Job terminado con errores: se elimina la entrada. Nada de esto cambia el valor de retorno ni bloquea la escritura. | FR-032, FR-034, FR-035 |
| `hermes/src/hermes/tools/filesystem_write.py` (`register_write`, `:150-158` y las 5 llamadas a `maybe_trigger_safety_backup`: `:279`, `:451`, `:630`, `:786`, `:1098`) | Parámetro `safety_backup_keep: int = 3` y `keep=safety_backup_keep` en cada llamada. | FR-031, FR-034 |
| `hermes/src/hermes/tools/backups.py` (`sv_create_safety_backup`, `:303-371`) | Tras el `POST`, `record_launch(name, job_id, origin="tool", slug=slug)`; docstring con la retención (FR-038). Sin poda aquí (research R-C3). | FR-032, FR-038 |
| `tests/test_tools_resolution.py`, `tests/test_tools_ha_backups.py`, `tests/test_safety_retention.py` (nuevos) | Ver tasks.md. Los tests del enganche en `fs_write.py` y en `sv_create_safety_backup` van en `test_safety_retention.py` para no editar `test_fs_write_security.py` ni `test_tools_supervisor.py`. | FR-022…FR-038 |

### Bloque de integración (al final, tras fusionar A, B y C)

| Fichero | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/tools/__init__.py` | Registrar `registry_floor`, `registry_label`, `registry_category`, `repairs`, `traces` (con `response_max_bytes`), `search`, `resolution` y `ha_backups`; parámetro `safety_backup_keep` en `register_all_tools` (de `cfg.safety_backup_keep` si es `None`) y pasarlo a `register_write`. | FR-031, FR-040 |
| `hermes/src/hermes/tools/_annotations.py` | `_DESTRUCTIVE_EXACT` += `ha_update_floor`, `ha_update_label`, `ha_update_category`, `ha_ignore_repair`, `sv_dismiss_resolution_issue`, `sv_dismiss_resolution_suggestion`; `_READ_ONLY_EXACT` += `ha_search_related`; comentario del porqué de cada una. | FR-040 |
| `hermes/src/hermes/config.py` | `safety_backup_keep: int = 3`; `load_config`: `_env_int("HERMES_SAFETY_BACKUP_KEEP", 3)`; `validate()`: fuera de 0–50 → error de arranque (principio III). | FR-031 |
| `hermes/config.yaml` | `schema`: `safety_backup_keep: "int(0,50)?"`; `options`: `safety_backup_keep: 3`. | FR-031 |
| `hermes/run.sh` | `export HERMES_SAFETY_BACKUP_KEEP="$(cfg_default safety_backup_keep 3)"`. | FR-031 |
| `hermes/src/hermes/tools/guide.py` | Temas `registries` (plantas, etiquetas, categorías), `backups` (backups de HA, retención) y uno nuevo `diagnostics` (Repairs, trazas, relaciones, resolución), con alias; recuento de tools. | FR-041 |
| `README.md`, `README.es.md` | Tabla «What it can do» / «Qué puede hacer» (familias nuevas o ampliadas, número real de tools); tabla de opciones con `safety_backup_keep`; limitaciones (no aplica sugerencias; safety backups sin cifrar; anteriores a 1.1.0 no se podan). | FR-042 |
| `hermes/DOCS.md` | Número de tools y una línea sobre `safety_backup_keep` remitiendo al README. | FR-042 |
| `docs/HOJA-DE-RUTA.md` | Marcar hecho lo de esta spec en 1.1.0; pendientes: cifrado de safety backups, aplicar sugerencias, flujos de Repairs, traducciones de issues. | FR-042 |
| `hermes/CHANGELOG.md` | Entradas `### Added` bajo `## [1.1.0]`. | FR-042 |
| `tests/test_tools_registration.py` | Las 23 tools registradas; anotaciones de contracts/tools.md; los invariantes existentes pasan. | FR-040 |
| `tests/test_addon_manifest.py`, `tests/test_run_sh_options.py`, `tests/test_config_validation.py` | Opción declarada con default 3 y rango 0–50; `run.sh` la exporta (0 no cae al default); `validate()` rechaza fuera de rango. | FR-031 |
| `tests/test_tools_guide.py` | El tema `diagnostics` existe y nombra las tools; `backups` menciona `safety_backup_keep`. | FR-041 |

## Seguimiento de complejidad

| Desviación | Por qué hace falta | Alternativa más simple descartada |
|---|---|---|
| La poda de safety backups borra sin `confirmation_token` (principio IV) | La pide el dueño al configurar `safety_backup_keep` en el add-on, fuera del canal MCP; un token por poda obligaría al cliente a confirmar algo que no ha pedido y, si no confirmara, los backups se acumularían (el problema que se resuelve). Se acota: solo backups de Hermes anotados y confirmados, nunca menos de N, máx. 5 por ejecución, fail-closed ante cualquier duda, rastro en el log, `0` la desactiva. Mismo precedente que `file_backup_max_per_path`. | Pedir token (no hay quién lo pida en mitad de una escritura); no podar (se llena el disco). |
| Una anotación propia en `/data/safety_backups.json` | Sin ella, la única identificación sería el nombre, y un nombre lo puede repetir cualquiera: no sería inequívoca. | Filtrar por prefijo `hermes-safety-` (borraría backups ajenos). |
| Invariantes de registro en rojo dentro de los bloques | El reparto pedido deja el registro y las anotaciones en la integración; dentro de un bloque, las tools nuevas aún no están registradas. | Fase 0 que registre módulos vacíos (contradice el reparto y toca el registro dos veces). |
| Llamada a `search/related` duplicada en el bloque A | Evita que el bloque A dependa del módulo del bloque B en paralelo. | Importar de `tools/search.py` (dependencia entre bloques paralelos). |
