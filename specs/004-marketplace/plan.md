# Plan de implementación: Hermes 1.1.0 — Marketplace de solo lectura

**Directorio**: `specs/004-marketplace` | **Fecha**: 2026-11-14 | **Spec**: [spec.md](./spec.md)

**Entrada**: especificación de `specs/004-marketplace/spec.md`.

**Rama de trabajo**: la que indique el mantenedor (spec-kit no crea ramas). Se
implementa **encima de la 1.0.12** ya fusionada.

## Resumen

Las tools de HACS dejaron de funcionar en HA ≥ 2026.11 porque HACS se integró en
Home Assistant como el Marketplace, con comandos `marketplace/*`. Esta versión
añade siete tools `ha_marketplace_*` de solo lectura que detectan en cada llamada
si hay Marketplace o HACS (por el código de error), normalizan la respuesta a una
proyección fija y marcan el texto de terceros. Las cuatro `ha_hacs_*` pasan a ser
alias deprecados que llaman al mismo código. Nunca se envía un comando que
escriba: tampoco `repository/info`, que quita la marca «nuevo» y sale a GitHub.
Se corrigen el ejemplo `/hacsfiles/` de Lovelace y el comentario de
`.storage/hacs.*`, y se pone al día la documentación.

Detalles y alternativas en [research.md](./research.md); formas en
[contracts/tools.md](./contracts/tools.md); entidades y validación en
[data-model.md](./data-model.md); validación en [quickstart.md](./quickstart.md).

## Contexto técnico

**Lenguaje/versión**: Python 3.13.

**Dependencias principales**: SDK `mcp` 2.x, `aiohttp`, `structlog`, `packaging` (vía `ha_version.py`). Ninguna nueva.

**Almacenamiento**: ninguno nuevo; todo se lee de HA en cada llamada.

**Pruebas**: `pytest` + `pytest-asyncio`, con `DummyMCP` y `make_ready_client` de los tests existentes y `ws_send` simulado con `AsyncMock` (`side_effect` por tipo de comando). Comando: `.venv/bin/pytest`.

**Plataforma**: add-on de HA OS; HA Core ≥ 2024.10.0 (tras 1.0.12). Marketplace en HA ≥ 2026.11; HACS 2.x en HA ≤ 2026.10.

**Tipo de proyecto**: servidor MCP (`hermes/src/hermes/`, tests en `tests/`).

**Objetivos de rendimiento**: en HA ≥ 2026.11, un comando WS por tool (dos en `get_repository` y en `list_updates` con resultados, por el registro de entidades). En HA ≤ 2026.10, uno más (el `marketplace/*` que falla).

**Restricciones**: solo lectura estricta (FR-019); nada en crudo (principio I); anotaciones veraces (V); ningún dato personal (VIII).

**Escala/alcance**: +7 tools (las 4 `ha_hacs_*` se mantienen). Tras 1.0.12 hay 186 registradas en una instalación normal (el README dice 185 antes de `ha_remove_device`); tras esta spec, 193. El recuento exacto se toma del registro al implementar. Unos 8 ficheros de código y documentación y 6 de tests.

## Comprobación contra la constitución

*Puerta: debe pasar antes de la fase 0 y repetirse tras el diseño.*

| Principio | Cómo se cumple | Estado |
|---|---|---|
| I. Seguridad primero | Proyección fija de 17 campos (FR-016); texto de terceros recortado y marcado (FR-017); sin README. | OK |
| II. Secretos | No se lee ni se devuelve nada de la config entry (donde vive el token de GitHub); `.storage/marketplace.*` sigue bloqueado (FR-024). | OK |
| III. Fail-closed | Lista cerrada de comandos con guarda en tiempo de ejecución (R-11); con `not_loaded` no se prueba HACS; respuestas con forma inesperada → `unexpected_response`; `marketplace.*` no se abre sin verificar. | OK |
| IV. Dos pasos | No hay acciones destructivas nuevas. La actualización sigue por `update.install` con `confirmation_token` (denylist existente). | OK (no aplica) |
| V. Nombre y descripción veraces | No se usa `repository/info` para poder anunciar `readOnlyHint` sin mentir (R-02); solo `list_releases` es `openWorldHint`; los alias dejan de ser `openWorldHint` y su descripción dice que están deprecados. Docstrings y anotaciones en el mismo cambio. | OK |
| VI. Probar lo arreglado | Test por requisito, incluido el de comandos permitidos (SC-003). | OK |
| VII. Control negativo | Tarea de control negativo al final de cada fase, con recuento. | OK |
| VIII. Privacidad | Ejemplos `owner/repo`, ids ficticios, `update.example`; grep antes del commit. | OK |
| IX. Cambios mínimos | Solo lo que pide la spec. Fuera: escritura, README, notas de versión, `marketplace.*` en `fs`, subida de versión (S-09, S-10). `search` es la única pieza no listada en la propuesta original; se justifica en R-06. | OK, justificado |
| X. Comentarios en español con el porqué | Cada guarda (no `repository/info`, no HACS con `not_loaded`, lista cerrada) lleva su porqué. Descripciones de tools en inglés. | OK |
| XI. Versión coherente | README EN/ES sincronizados; DOCS, CHANGELOG y hoja de ruta en el mismo cambio. La subida a 1.1.0 es de la integración de la versión (S-09). | OK |

Repetida tras el diseño (fase 1): sin cambios; no hay violaciones que justificar.

## Estructura del proyecto

### Documentación (esta funcionalidad)

```text
specs/004-marketplace/
├── spec.md
├── plan.md              # este fichero
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/tools.md
├── checklists/requirements.md
└── tasks.md
```

### Código fuente (raíz del repositorio)

```text
hermes/
├── CHANGELOG.md                    # lote D
├── DOCS.md                         # lote D
└── src/hermes/
    ├── fs.py                       # lote C (solo comentario de :159)
    └── tools/
        ├── __init__.py             # lote B (registro)
        ├── _annotations.py         # lote B
        ├── marketplace.py          # lote A (NUEVO)
        ├── hacs.py                 # lote B (alias)
        ├── lovelace.py             # lote C (solo docstring de :712)
        └── guide.py                # lote D
tests/
├── test_tools_marketplace.py       # lote A (NUEVO)
├── test_tools_hacs.py              # lote B (de la 1.0.12)
├── test_tools_wait_for_event.py    # lote B (quitar TestHACSTools)
├── test_tools_registration.py      # lote B
├── test_fs_security.py             # lote C
├── test_tools_lovelace.py          # lote C
└── test_tools_guide.py             # lote D
README.md, README.es.md, docs/HOJA-DE-RUTA.md   # lote D
```

**Decisión de estructura**: un módulo nuevo `tools/marketplace.py` con la lógica
y las siete tools; `tools/hacs.py` queda como módulo de alias que importa las
funciones de `marketplace.py`. Así el alias no puede divergir y el test de la
1.0.12 (`tests/test_tools_hacs.py`) sigue teniendo su módulo.

## Cambios por fichero

### Lote A — Núcleo `ha_marketplace_*`

| Fichero | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/tools/marketplace.py` (nuevo) | Constantes: `MARKETPLACE_CATEGORIES = {"integration","plugin","template","theme"}`, `HACS_ONLY_CATEGORIES = {"appdaemon","python_script"}`, `SUMMARY_FIELDS` (17), `_ALLOWED_SUFFIXES = {"info","repositories/list","repository/releases","critical/list","repositories/removed"}`, `_THIRD_PARTY_WARNING`. | FR-009, FR-016, FR-019 |
| idem | `class _ApiError(Exception)` con `payload: dict`. `async def _ws_read(ha_client, suffix, extra=None) -> tuple[str, Any]`: si `suffix not in _ALLOWED_SUFFIXES` → `RuntimeError` (guarda; nunca debería ocurrir). Envía `marketplace/<suffix>`; `HAConnectionError`/`TimeoutError`: `code == "not_loaded"` → `_ApiError(marketplace_not_loaded)`; `code == "unknown_command"` → `hacs/<suffix>`; en el segundo, `unknown_command` → `ha_at_least(ha_client, "2026.11.0")`: `True` → `marketplace_unavailable`, si no `hacs_not_installed`; otro código → `{"error": code or "ha_error", "detail": str(exc)}`. Comentario del porqué de cada rama (research R-01). | FR-001…FR-006 |
| idem | `_summary(repo)`, `_trim(text, 300)`, `_third_party(fields)`, `_validate_*` (categoría, limit, search, repository_id según data-model.md). | FR-008…FR-010, FR-016, FR-017 |
| idem | `async def _update_entity_ids(ha_client, api) -> dict[str, str]`: `config/entity_registry/list`, filtra `entity_id` `update.*`, `platform == api`, mapea `str(unique_id)` → `entity_id`; ante error devuelve `{}`. | FR-011, FR-012 |
| idem | Funciones públicas `async def info(ha_client)`, `list_repositories(ha_client, category, installed_only, search, limit)`, `get_repository(ha_client, repository_id)`, `list_updates(ha_client)`, `list_releases(ha_client, repository_id, limit)`, `list_critical(ha_client)`, `list_removed(ha_client)`, que devuelven el dict del contrato (los `_ApiError` se convierten en su `payload`). `list_repositories` con Marketplace y categoría de `HACS_ONLY_CATEGORIES` → `invalid_category`. `list_releases` mapea `github_rate_limited` y `repository_not_found`. | FR-007…FR-015, FR-020 |
| idem | `register(mcp, ha_client)`: siete `@mcp.tool()` + `@ready` con docstrings en inglés; `ha_marketplace_info` aclara `warning_accepted`; `list_updates` incluye la receta de `update.install` y el aviso; `list_releases` dice que consulta GitHub. | FR-007, FR-013, FR-020 |
| `tests/test_tools_marketplace.py` (nuevo) | Ver tasks.md (fases 3–6). Incluye un fake de `ws_send` que registra los tipos enviados para SC-003. | todos los de A |

### Lote B — Alias, registro y anotaciones (tras A)

| Fichero | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/tools/hacs.py` | Se reescribe como módulo de alias: quita `_HACS_DISCLAIMER`, `_VALID_CATEGORIES`, el helper de errores de la 1.0.12 y el código propio; registra `ha_hacs_info`, `ha_hacs_list_repositories`, `ha_hacs_get_repository`, `ha_hacs_list_updates` con la misma firma que las nuevas, llamando a `marketplace.info/…` y añadiendo `_deprecated`. Docstrings `DEPRECATED (removed in 1.3.0): use ha_marketplace_…`. | FR-021, FR-022 |
| `hermes/src/hermes/tools/__init__.py:215-225` | Registrar `marketplace` antes de `hacs`; comentario. | FR-021 |
| `hermes/src/hermes/tools/_annotations.py:45-55, 113-128` | Las siete `ha_marketplace_*` por nombre exacto en `_READ_ONLY_EXACT` (no como prefijo: una tool de escritura futura con ese prefijo se anunciaría de solo lectura; fail-closed); en `_OPEN_WORLD`, quitar los cuatro `ha_hacs_*` y añadir `ha_marketplace_list_releases`, con el porqué. | FR-018 |
| `tests/test_tools_hacs.py` | Sustituir los tests de `hacs_moved_to_marketplace` (1.0.12) por los de alias; conservar `hacs_not_installed`. | FR-021, FR-022 |
| `tests/test_tools_wait_for_event.py:318-415` | Quitar `TestHACSTools` y el import de `hacs_mod` (sus casos pasan a `test_tools_hacs.py`; afirman `_disclaimer`, que desaparece). | FR-021 |
| `tests/test_tools_registration.py:294, 349` | Anotaciones de las 11 tools; `ha_hacs_list_repositories` ya no es `openWorldHint`; `ha_marketplace_list_releases` sí. | FR-018 |

### Lote C — Rutas obsoletas (independiente)

| Fichero | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/tools/lovelace.py:712` | Ejemplo `"/local/community/card/card.js"`; mencionar que `/hacsfiles/` sigue funcionando. | FR-023 |
| `hermes/src/hermes/fs.py:159` | Comentario: `hacs.*` solo existe en HA ≤ 2026.10; `marketplace.*` no se abre hasta verificar su contenido. Sin cambio de código. | FR-024 |
| `tests/test_tools_lovelace.py` | La descripción de `ha_create_lovelace_resource` contiene `/local/community/`. | FR-023 |
| `tests/test_fs_security.py:356` | Junto a `test_hacs_variant_allowed`: `.storage/marketplace.repositories` y `.storage/marketplace.common` bloqueados. | FR-024 |

### Lote D — Guía y documentación (tras A y B)

| Fichero | Cambio | FR |
|---|---|---|
| `hermes/src/hermes/tools/guide.py` | Tema `marketplace` (tools, detección, `update.install` con token, aviso por usuario, texto de terceros); alias de tema `hacs` → `marketplace`; recuento `~186` → el real; mención en el índice. | FR-028 |
| `tests/test_tools_guide.py` | `hermes_guide("marketplace")` y `hermes_guide("hacs")` devuelven el tema y nombran `update.install`. | FR-028 |
| `README.md:10, 24, 44`, `README.es.md` (equivalentes) | Fila «Marketplace (antes HACS)» con 7 + 4 alias; recuento total; quitar «do not support it yet» / «todavía no la soportan». | FR-025 |
| `hermes/DOCS.md` (sección «Qué esperar») | Párrafo del Marketplace. | FR-026 |
| `docs/HOJA-DE-RUTA.md:20-22, 44, 57, 126-129, 141` | Problemas 6 y 19 resueltos en 1.1.0; estado de compatibilidad al día; escritura en 1.2.x. | FR-027 |
| `hermes/CHANGELOG.md` | Entrada en `## [1.1.0]` (crear la cabecera si no existe; la fecha la pone la integración). | FR-029 |

## Riesgos

- **Tamaño del catálogo**: si supera `ha_ws_max_msg_size_bytes`, la lista falla
  con un error de HA (S-06). Mitigación: `category`; medir en vivo.
- **API no declarada estable para terceros**: los nombres de campo pueden cambiar;
  `_summary` usa `.get()` y devuelve `null` para lo que falte.
- **Cambio de contrato de los alias** (S-05): anunciado en el CHANGELOG.
- **Dependencia de la 1.0.12**: si `HAConnectionError.code` o `ha_version.py` no
  están, la detección no funciona; los tests de la fase 2 lo comprueban primero.

## Seguimiento de complejidad

| Decisión | Por qué hace falta | Alternativa más simple descartada |
|---|---|---|
| Lista cerrada de comandos con guarda en tiempo de ejecución | Hace comprobable «solo lectura» (FR-019, SC-003) y falla cerrado si alguien añade un comando de escritura por error. | Confiar en la revisión: no es un invariante verificado (principio VI). |
| `update_entity_id` por el registro de entidades | Permite el detalle y las actualizaciones sin `repository/info` (R-02). | `repository/info`: escribe y sale a GitHub. |
