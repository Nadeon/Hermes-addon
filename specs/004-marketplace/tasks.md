---

description: "Tareas de Hermes 1.1.0 — Marketplace de solo lectura, agrupadas en lotes"
---

# Tareas: Hermes 1.1.0 — Marketplace de solo lectura

**Entrada**: `specs/004-marketplace/` (spec.md, plan.md, research.md, data-model.md, contracts/tools.md, quickstart.md).

**Base**: la 1.0.12 fusionada (spec 001). No empezar sin ella (T002).

**Tests**: obligatorios. La constitución (principios VI y VII) exige un test de regresión por cambio, escrito **antes** de la implementación, y un **control negativo**: deshacer el cambio, ver caer el test y dejar el recuento por escrito.

**Organización**: por **lotes** con propiedad exclusiva de ficheros; dentro de cada lote, por historia de usuario (US1…US6 de spec.md).

## Formato: `[ID] [P?] [Historia] Descripción`

- **[P]**: se puede hacer en paralelo con otras tareas del mismo lote (ficheros distintos, sin dependencias pendientes).
- **[USn]**: historia de usuario de spec.md.
- Rutas relativas a la raíz del repositorio.

## Reparto de ficheros por lote

Ningún fichero aparece en dos lotes. Si un lote necesita cambiar un fichero que
no es suyo, **no lo toca**: lo anota en su informe.

| Lote | Ficheros que le pertenecen (código y tests) |
|---|---|
| **A — Núcleo `ha_marketplace_*`** | `hermes/src/hermes/tools/marketplace.py` (nuevo), `tests/test_tools_marketplace.py` (nuevo) |
| **B — Alias, registro y anotaciones** (tras A) | `hermes/src/hermes/tools/hacs.py`, `hermes/src/hermes/tools/__init__.py`, `hermes/src/hermes/tools/_annotations.py`, `tests/test_tools_hacs.py`, `tests/test_tools_wait_for_event.py`, `tests/test_tools_registration.py` |
| **C — Rutas obsoletas** (independiente) | `hermes/src/hermes/tools/lovelace.py` (solo el docstring de `ha_create_lovelace_resource`), `hermes/src/hermes/fs.py` (solo el comentario de `STORAGE_ALLOWLIST_PATTERNS`), `tests/test_tools_lovelace.py`, `tests/test_fs_security.py` |
| **D — Guía y documentación** (tras A y B) | `hermes/src/hermes/tools/guide.py`, `tests/test_tools_guide.py`, `README.md`, `README.es.md`, `hermes/DOCS.md`, `docs/HOJA-DE-RUTA.md`, `hermes/CHANGELOG.md` |

Notas de reparto:

- `hermes/src/hermes/ha.py`, `hermes/src/hermes/ha_version.py`,
  `hermes/src/hermes/service_policy.py`, `hermes/config.yaml`,
  `hermes/src/hermes/__init__.py` y `hermes/src/hermes/config.py` **no los toca
  nadie**: la detección usa lo que dejó la 1.0.12 y la versión la sube la
  integración de 1.1.0 (spec S-09).
- `tests/_ha_fixture.py` no se edita: los fakes de WS se construyen en cada
  fichero de test, con `HAConnectionError("…", code="unknown_command")`.
- El lote C no depende de A ni de B y puede ir en paralelo con A.

---

## Fase 1: Preparación

- [X] T001 Crear `.venv` según `CONTRIBUTING.es.md:68-73` y ejecutar `.venv/bin/pytest`; anotar el número de tests que pasan como línea base
- [X] T002 Comprobar que la base es la 1.0.12: `HAConnectionError` tiene `code` (`hermes/src/hermes/ha.py`), existe `hermes/src/hermes/ha_version.py` con `ha_at_least`, `tests/test_tools_hacs.py` existe y `hermes/src/hermes/tools/hacs.py` ya acepta `template` y usa `pending_upgrade` (001 FR-038, FR-039). Si falta algo, parar e informar; anotar las líneas reales de `hacs.py`, `lovelace.py:712` y `fs.py:159` si se han movido

---

## Fase 2: Fundación del lote A (BLOQUEA a las historias)

**Objetivo**: detección de la API, proyección, validación y lista cerrada de comandos en `hermes/src/hermes/tools/marketplace.py`.

**Prueba independiente**: `.venv/bin/pytest tests/test_tools_marketplace.py -k "detect or summary or allowed or validate"`.

- [X] T003 [P] Tests de detección en `tests/test_tools_marketplace.py` (llamando a `_ws_read` con un `ws_send` simulado por tipo de comando): (a) `marketplace/info` responde → `("marketplace", …)` y no se envía `hacs/info`; (b) `not_loaded` → `marketplace_not_loaded` y 0 comandos `hacs/*`; (c) `unknown_command` y luego `hacs/info` responde → `("hacs", …)`; (d) los dos `unknown_command` con `ha_at_least` parcheado a `True` → `marketplace_unavailable`, a `False` y a `None` → `hacs_not_installed`; (e) otro código (`unauthorized`) → `{"error": "unauthorized", "detail": …}` sin `hacs/*`; (f) `HAConnectionError` sin código → `ha_error`; (g) dos llamadas seguidas repiten la detección (sin caché); (h) ningún `detail` contiene «update Hermes» (FR-001…FR-006)
- [X] T004 [P] Tests de proyección y validación en `tests/test_tools_marketplace.py`: `_summary` de un repo con campos extra (`local_path`, `authors`, `country`, `state`, `topics`) devuelve exactamente los 17 de data-model.md; `can_download` de HACS sale como `can_install`; campos ausentes → `None`; `description` de 1000 caracteres sale con 300; elementos no dict se descartan; `_third_party` lleva `fields` y `warning`; validación de `category`, `limit`, `search` y `repository_id` según la tabla de data-model.md (FR-009, FR-010, FR-016, FR-017)
- [X] T005 [P] Test de la lista cerrada en `tests/test_tools_marketplace.py`: `_ws_read` con un sufijo fuera de `_ALLOWED_SUFFIXES` (`repository/info`, `repository/install`, `warning/accept`) lanza error antes de enviar nada; `_ALLOWED_SUFFIXES` es exactamente el de research R-11 (FR-019)
- [X] T006 Crear `hermes/src/hermes/tools/marketplace.py` con las constantes, `_ApiError` y `_ws_read` según plan.md (lote A) y data-model.md (transiciones), usando `HAConnectionError.code` y `ha_at_least(ha_client, "2026.11.0")` de `hermes/src/hermes/ha_version.py`; comentarios del porqué: no caer a HACS con `not_loaded` (bloqueado en HA ≥ 2026.11), sin caché (001 S-03), lista cerrada (FR-019)
- [X] T007 Añadir `_summary`, `_trim`, `_third_party` y los validadores en `hermes/src/hermes/tools/marketplace.py` (FR-009, FR-010, FR-016, FR-017)
- [X] T008 Control negativo de la fundación: por separado, (1) quitar la rama `not_loaded` (que caiga a HACS), (2) añadir una caché de API, (3) devolver el repo sin proyectar, (4) quitar la guarda de `_ALLOWED_SUFFIXES`; ejecutar T003–T005 cada vez, restaurar y anotar «con la guarda quitada caen N tests»

**Punto de control**: la detección y la proyección están probadas.

---

## Fase 3: Historia 1 — Instalado y actualizaciones con el Marketplace (Prioridad: P1) 🎯 MVP

**Objetivo**: `ha_marketplace_info`, `ha_marketplace_list_repositories` y `ha_marketplace_list_updates` funcionan en HA ≥ 2026.11.

**Prueba independiente**: `.venv/bin/pytest tests/test_tools_marketplace.py -k "info or list_repositories or list_updates"` con `api: "marketplace"`.

- [X] T009 [P] [US1] Tests en `tests/test_tools_marketplace.py` (vía `register` con `DummyMCP` y `make_ready_client`, como en `tests/test_tools_wait_for_event.py:318-330`): (a) `ha_marketplace_info` devuelve los 10 campos de FR-007 con `api: "marketplace"` y descarta extras; (b) `ha_marketplace_list_repositories()` sobre 3 instalados y 3000 no instalados devuelve los 3 ordenados por `full_name`, `total: 3`, `truncated: false`; (c) `installed_only=False, limit=50` sobre 3003 → 50 elementos, `total: 3003`, `truncated: true` y la respuesta serializada pesa menos de 50 KB (SC-004); (d) `search="card"` filtra sin distinguir mayúsculas por `full_name`, `name` y `description`; (e) `category="integration"` envía `{"type": "marketplace/repositories/list", "categories": ["integration"]}`; (f) `category="netdaemon"` → `invalid_category` sin ninguna llamada WS; (g) la respuesta lleva `_third_party_text` (FR-007, FR-008, FR-009, FR-017)
- [X] T010 [P] [US1] Tests de `ha_marketplace_list_updates` en `tests/test_tools_marketplace.py`: (a) instalado con `pending_upgrade: true` y versiones iguales como texto → aparece; (b) instalado con `pending_upgrade: false` y versiones distintas → no aparece; (c) no instalado con `pending_upgrade: true` → no aparece; (d) `update_entity_id` sale de `config/entity_registry/list` (entrada `update.example`, `platform: "marketplace"`, `unique_id: "123456"`), y una entrada de otra plataforma con el mismo `unique_id` no cuenta; (e) registro que falla → `update_entity_id: null` y la tool no falla; (f) sin actualizaciones no se pide el registro; (g) `how_to_update` nombra `update.install`, `confirmation_token` y que Hermes no acepta el aviso; (h) la descripción de la tool dice lo mismo (FR-012, FR-020)
- [X] T011 [US1] Implementar `info`, `list_repositories`, `_update_entity_ids` y `list_updates` en `hermes/src/hermes/tools/marketplace.py`, y registrar `ha_marketplace_info`, `ha_marketplace_list_repositories` y `ha_marketplace_list_updates` en `register()` con docstrings en inglés según contracts/tools.md (FR-007, FR-008, FR-012, FR-020)
- [X] T012 [US1] Control negativo US1: (1) volver a la comparación de versiones como texto ignorando `pending_upgrade`, (2) `installed_only=False` por defecto, (3) quitar el recorte de `limit`, (4) quitar `how_to_update`; ejecutar T009–T010 cada vez, restaurar y anotar

**Punto de control**: US1 completa; es el MVP de la versión.

---

## Fase 4: Historia 2 — Respaldo a HACS en HA ≤ 2026.10 (Prioridad: P1)

**Objetivo**: las mismas tools con HACS, y errores claros sin ninguna de las dos API.

**Prueba independiente**: `.venv/bin/pytest tests/test_tools_marketplace.py -k hacs`.

- [X] T013 [US2] Tests en `tests/test_tools_marketplace.py` con `marketplace/*` → `unknown_command` y `hacs/*` → datos: (a) `ha_marketplace_info` → `api: "hacs"`, `github_connected: null`, `warning_accepted: null`, sin `country`/`debug`/`dev`; (b) `ha_marketplace_list_repositories` → `api: "hacs"` y `can_install` desde `can_download`; (c) `category="appdaemon"` se envía a `hacs/repositories/list`; (d) con el Marketplace, `category="appdaemon"` → `invalid_category` con `valid` = las 4 del Marketplace; (e) `ha_marketplace_list_updates` con un HACS sin `pending_upgrade` compara versiones (`1.0.0` frente a `1.1.0` aparece; iguales no); (f) `update_entity_id` con `platform: "hacs"`; (g) HA sin ninguna API y versión 2026.10 → `hacs_not_installed` (FR-003, FR-004, FR-009, FR-012, FR-016)
- [X] T014 [US2] Ajustar en `hermes/src/hermes/tools/marketplace.py` lo que T013 encuentre (rechazo de categorías solo de HACS con el Marketplace; `pending_upgrade` ausente; plataforma del registro según `api`) (FR-009, FR-012)
- [X] T015 [US2] Control negativo US2: (1) quitar el rechazo de categorías solo de HACS, (2) quitar la comparación de respaldo cuando falta `pending_upgrade`, (3) buscar siempre la plataforma `marketplace`; ejecutar T013, restaurar y anotar

**Punto de control**: US1 y US2 funcionan con las dos API.

---

## Fase 5: Historia 3 — Detalle de un repositorio y versiones (Prioridad: P2)

**Prueba independiente**: `.venv/bin/pytest tests/test_tools_marketplace.py -k "get_repository or releases"`.

- [X] T016 [P] [US3] Tests de `ha_marketplace_get_repository` en `tests/test_tools_marketplace.py`: (a) devuelve el resumen y `update_entity_id`; (b) los tipos enviados son solo `marketplace/repositories/list` y `config/entity_registry/list` (ni `repository/info` ni nada de GitHub); (c) id inexistente → `repository_not_found` con `repository_id`; (d) `repository_id="../x"` o de 65 caracteres → `invalid_argument` sin llamadas; (e) id numérico de HACS (`123`) coincide con `"123"` (FR-011)
- [X] T017 [P] [US3] Tests de `ha_marketplace_list_releases` en `tests/test_tools_marketplace.py`: (a) envía `{"type": "marketplace/repository/releases", "repository_id": "123456"}` y devuelve `tag`, `name`, `published_at`, `prerelease`, sin campos extra; (b) `limit=2` sobre 5 → 2; `limit=31` → `invalid_argument`; (c) `HAConnectionError(code="github_rate_limited")` → `github_rate_limited` con explicación; (d) `repository_not_found` de HA → `repository_not_found`; (e) con `unknown_command` cae a `hacs/repository/releases`; (f) la descripción dice que consulta GitHub (FR-013)
- [X] T018 [US3] Implementar `get_repository` y `list_releases` en `hermes/src/hermes/tools/marketplace.py` y registrar `ha_marketplace_get_repository` y `ha_marketplace_list_releases`; comentario del porqué de no usar `repository/info` (research R-02) (FR-011, FR-013)
- [X] T019 [US3] Control negativo US3: (1) cambiar `get_repository` para que envíe `marketplace/repository/info` (debe caer T016b y además T005), (2) quitar el mapeo de `github_rate_limited`, (3) quitar el tope de 30; restaurar y anotar

---

## Fase 6: Historia 4 — Críticos y retirados (Prioridad: P2)

**Prueba independiente**: `.venv/bin/pytest tests/test_tools_marketplace.py -k "critical or removed"`.

- [X] T020 [US4] Tests en `tests/test_tools_marketplace.py`: (a) `ha_marketplace_list_critical` con entradas con campos extra devuelve solo `repository`, `reason`, `link`, `acknowledged`, con `reason` recortado y `_third_party_text`; (b) `ha_marketplace_list_removed` devuelve además `removal_type`; (c) con `unknown_command` caen a `hacs/critical/list` y `hacs/repositories/removed`; (d) ninguna envía `critical/acknowledge` ni `repositories/clear_new`; (e) respuesta no lista → `unexpected_response` (FR-014, FR-015, FR-019)
- [X] T021 [US4] Implementar `list_critical` y `list_removed` en `hermes/src/hermes/tools/marketplace.py` y registrar `ha_marketplace_list_critical` y `ha_marketplace_list_removed` (FR-014, FR-015)
- [X] T022 [US4] Control negativo US4: devolver la entrada sin proyectar; ejecutar T020, restaurar y anotar

### Cierre del lote A

- [X] T023 Test transversal en `tests/test_tools_marketplace.py` (SC-003): ejecutar cada una de las 7 tools contra el fake con las dos API y comprobar que el conjunto de tipos enviados ⊆ R-11 (`marketplace/info`, `marketplace/repositories/list`, `marketplace/repository/releases`, `marketplace/critical/list`, `marketplace/repositories/removed`, sus `hacs/*`, `config/entity_registry/list`, `get_config`) (FR-019)
- [X] T024 Ejecutar `.venv/bin/pytest tests/test_tools_marketplace.py` y la suite completa; grep de privacidad del diff; commit del lote A con los recuentos de control negativo

**Punto de control**: las 7 tools existen en `marketplace.py`; todavía no se registran en el servidor (lo hace el lote B).

---

## Fase 7: Historia 5 — Alias `ha_hacs_*`, registro y anotaciones (Prioridad: P2) — lote B, tras A

**Prueba independiente**: `.venv/bin/pytest tests/test_tools_hacs.py tests/test_tools_registration.py tests/test_tools_wait_for_event.py`.

- [X] T025 [P] [US5] Tests en `tests/test_tools_hacs.py`: sustituir los casos de `hacs_moved_to_marketplace` de la 1.0.12 por: (a) con el Marketplace simulado, cada `ha_hacs_*` devuelve lo mismo que su `ha_marketplace_*` más `_deprecated` con el nombre nuevo; (b) ya no aparece `hacs_moved_to_marketplace` ni `_disclaimer`; (c) HA ≤ 2026.10 sin HACS → `hacs_not_installed`; (d) la descripción de cada alias empieza por `DEPRECATED` y nombra la sustituta y `1.3.0`; (e) `ha_hacs_list_repositories` acepta `installed_only`, `search` y `limit`. Mover aquí los casos útiles de `TestHACSTools` (`tests/test_tools_wait_for_event.py:318-415`) adaptados a la forma nueva (FR-021, FR-022)
- [X] T026 [P] [US5] Tests en `tests/test_tools_registration.py`: las 7 `ha_marketplace_*` y las 4 `ha_hacs_*` están registradas en el servidor; todas `read_only_hint` y no `destructive_hint`; `open_world_hint` solo en `ha_marketplace_list_releases`; cambiar `:349` (`ha_hacs_list_repositories` deja de ser de mundo abierto) y añadir `ha_marketplace_info` a la lista de `:291-298`; un nombre hipotético `ha_marketplace_install` NO es de solo lectura (FR-018, SC-006)
- [X] T027 [US5] Reescribir `hermes/src/hermes/tools/hacs.py` como módulo de alias según plan.md (lote B); quitar `TestHACSTools` y el import de `hacs_mod` de `tests/test_tools_wait_for_event.py` (FR-021, FR-022)
- [X] T028 [US5] Registrar `marketplace` antes de `hacs` en `hermes/src/hermes/tools/__init__.py:215-225` (FR-021)
- [X] T029 [US5] En `hermes/src/hermes/tools/_annotations.py`: las siete `ha_marketplace_*` por nombre exacto en `_READ_ONLY_EXACT` (`:45-55`), no como prefijo (fail-closed); en `_OPEN_WORLD` (`:113-128`), quitar los cuatro `ha_hacs_*` y añadir `ha_marketplace_list_releases`, con el porqué (ya no salen a GitHub) (FR-018)
- [X] T030 [US5] Control negativo US5: (1) quitar `_deprecated`, (2) dejar los `ha_hacs_*` en `_OPEN_WORLD`, (3) no registrar `marketplace` en `__init__.py`, (4) clasificar por el prefijo `ha_marketplace_` en vez de por nombre exacto; ejecutar T025–T026 cada vez, restaurar y anotar
- [X] T031 Ejecutar la suite completa; grep de privacidad; commit del lote B con los recuentos

---

## Fase 8: Historia 6 (parte de código) — Rutas obsoletas (Prioridad: P3) — lote C, independiente

**Prueba independiente**: `.venv/bin/pytest tests/test_tools_lovelace.py tests/test_fs_security.py`.

- [X] T032 [P] [US6] Test en `tests/test_tools_lovelace.py`: la descripción de `ha_create_lovelace_resource` contiene `/local/community/` (FR-023)
- [X] T033 [P] [US6] Tests en `tests/test_fs_security.py`, junto a `test_hacs_variant_allowed` (`:356`): `.storage/marketplace.repositories` y `.storage/marketplace.common` → `check_blacklisted` bloqueado (FR-024)
- [X] T034 [US6] Cambiar el ejemplo de `url` en `hermes/src/hermes/tools/lovelace.py:712` a `"/local/community/card/card.js"` y mencionar que `/hacsfiles/` sigue funcionando (FR-023)
- [X] T035 [US6] Reescribir el comentario de `"hacs.*"` en `hermes/src/hermes/fs.py:159`: solo existe en HA ≤ 2026.10; `marketplace.*` no se abre hasta verificar su contenido (spec S-07). Sin cambio de código (FR-024)
- [X] T036 [US6] Control negativo lote C: deshacer T034 y comprobar que cae T032; añadir temporalmente `"marketplace.*"` a `STORAGE_ALLOWLIST_PATTERNS` y comprobar que cae T033; restaurar y anotar
- [X] T037 Ejecutar la suite completa; grep de privacidad; commit del lote C con los recuentos

---

## Fase 9: Historia 6 (documentación) — Guía y documentos (Prioridad: P3) — lote D, tras A y B

**Prueba independiente**: `.venv/bin/pytest tests/test_tools_guide.py` y revisión manual de los documentos.

- [X] T038 [P] [US6] Tests en `tests/test_tools_guide.py`: `hermes_guide("marketplace")` y `hermes_guide("hacs")` devuelven el tema, que nombra las 7 tools, `update.install`, `confirmation_token`, el aviso por usuario y la advertencia de texto de terceros; el índice menciona `marketplace` (FR-028)
- [X] T039 [US6] Añadir el tema `marketplace` y el alias `hacs` en `hermes/src/hermes/tools/guide.py`; actualizar el recuento aproximado de `:23` con el número real de tools registradas y el índice de temas (`:71`) (FR-028)
- [X] T040 [US6] Control negativo de la guía: quitar el tema y comprobar que cae T038; restaurar y anotar
- [X] T041 [P] [US6] `README.md` (`:10`, `:24`, fila `:44`) y `README.es.md` (equivalentes, fila `:46`), sincronizados: familia «Marketplace (formerly HACS)» / «Marketplace (antes HACS)» con las 7 tools, de solo lectura, detección automática y alias `ha_hacs_*` deprecados hasta 1.3.0; quitar «do not support it yet» / «todavía no la soportan»; recuento total al día; ejemplos solo con marcadores (FR-025)
- [X] T042 [P] [US6] `hermes/DOCS.md`, sección «Qué esperar»: un párrafo sobre el Marketplace (solo lectura; actualizar con las entidades `update` y confirmación; el aviso de riesgos lo acepta una persona en la interfaz) (FR-026)
- [X] T043 [P] [US6] `docs/HOJA-DE-RUTA.md`: estado de compatibilidad (`:20-22`) sin «no funcionan»; problemas 6 y 19 (`:44`, `:57`) resueltos en 1.1.0; plan de 1.1.0 (`:126-129`) con el Marketplace hecho; escritura en 1.2.x (`:141`) sin cambios (FR-027)
- [X] T044 [US6] (Hecho en `specs/004-marketplace/notas-changelog.md`: la cabecera `## [1.1.0]` y la copia al CHANGELOG las hace la integración final) `hermes/CHANGELOG.md`: en `## [1.1.0]` (crear la cabecera si no existe; la fecha la fija la integración), `### Added` con las 7 tools, `### Changed` con la forma nueva de las respuestas (`api`, sin `_disclaimer`), `installed_only=True` por defecto y `openWorldHint` de los alias, `### Deprecated` con los 4 alias (retirada en 1.3.0) y `### Fixed` con el ejemplo de Lovelace; explicar el porqué (HA 2026.11) (FR-029)
- [X] T045 Comprobar a mano que README.md y README.es.md dicen lo mismo; suite completa; grep de privacidad e identificadores de modelos de IA; commit del lote D

---

## Fase 10: Cierre transversal

- [X] T046 Fusionar A, B, C y D en la rama de trabajo (sin conflictos esperados: no comparten ficheros); suite completa (SC-008)
- [X] T047 Recorrer quickstart.md y la tabla de trazabilidad; cada FR con comportamiento tiene test y control negativo anotado (SC-007)
- [X] T048 Grep final del diff de la spec: hostnames reales, IPs, slugs, nombres de repositorios o entidades de una instalación concreta e identificadores de modelos de IA → 0 coincidencias (SC-009, FR-031)
- [X] T049 (descripción actualizada por el supervisor en la PR #18) Redactar la descripción del PR: tools nuevas, alias, recuentos de control negativo por lote, supuestos S-01…S-10 y lo que queda fuera (escritura, README del repositorio, notas de versión, `.storage/marketplace.*`, subida de versión). Sin push ni fusión: lo decide el mantenedor (principio XI)

---

## Dependencias y orden de ejecución

### Entre fases

- **Fase 1**: sin dependencias; T002 bloquea todo si la 1.0.12 no está.
- **Fase 2** (fundación del lote A): bloquea las fases 3–6.
- **Fases 3–6** (lote A): en orden de prioridad; US3 y US4 son independientes entre sí tras la fase 2.
- **Fase 7** (lote B): depende del lote A (importa sus funciones).
- **Fase 8** (lote C): solo depende de la fase 1; puede ir en paralelo con A.
- **Fase 9** (lote D): depende de A y B (documenta nombres y recuentos).
- **Fase 10**: depende de todas.

### Entre historias

- US1 es el MVP; US2 reutiliza la misma detección; US3 y US4 son independientes.
- US5 necesita US1–US4 (los alias llaman a esas funciones).
- US6 se reparte entre los lotes C (código) y D (documentación).

### Dentro de cada cambio

1. Test de regresión (falla contra la 1.0.12).
2. Implementación (el test pasa).
3. Control negativo (deshacer, ver caer el test, restaurar, anotar el recuento).

### Paralelismo

```bash
# Dos worktrees a la vez:
Agente A: T003–T024 (lote A)
Agente C: T032–T037 (lote C)
# Después, en orden:
Agente B: T025–T031 (lote B)
Agente D: T038–T045 (lote D)
# Cierre: T046–T049
```

---

## Estrategia de implementación

1. Fases 1 y 2.
2. Fase 3 (US1): con esto ya funciona lo más usado en HA ≥ 2026.11, pero las tools
   no se ven hasta registrarlas (lote B). Si hay que entregar antes, adelantar
   T028 y T029 justo después de la fase 3.
3. Fases 4–6, luego B, C y D.

---

## Trazabilidad FR → tareas

| FR | Lote | Test | Implementación | Control negativo |
|---|---|---|---|---|
| FR-001…FR-006 | A | T003 | T006 | T008 |
| FR-007 | A | T009, T013 | T011 | T012 |
| FR-008 | A | T009 | T011 | T012 |
| FR-009 | A | T004, T009, T013 | T007, T014 | T015 |
| FR-010 | A | T004, T009, T017 | T007 | T012, T019 |
| FR-011 | A | T016 | T018 | T019 |
| FR-012 | A | T010, T013 | T011, T014 | T012, T015 |
| FR-013 | A | T017 | T018 | T019 |
| FR-014, FR-015 | A | T020 | T021 | T022 |
| FR-016, FR-017 | A | T004, T009, T020 | T007 | T008, T022 |
| FR-018 | B | T026 | T029 | T030 |
| FR-019 | A | T005, T016, T020, T023 | T006 | T008, T019 |
| FR-020 | A | T010 | T011 | T012 |
| FR-021, FR-022 | B | T025, T026 | T027, T028 | T030 |
| FR-023 | C | T032 | T034 | T036 |
| FR-024 | C | T033 | T035 | T036 |
| FR-025 | D | revisión manual (T045) | T041 | — (documentación) |
| FR-026 | D | revisión manual (T045) | T042 | — (documentación) |
| FR-027 | D | revisión manual (T045) | T043 | — (documentación) |
| FR-028 | D | T038 | T039 | T040 |
| FR-029 | D | revisión manual (T045) | T044 | — (documentación) |
| FR-030 | todos | — | controles negativos | T008, T012, T015, T019, T022, T030, T036, T040 |
| FR-031 | todos | T048 | — | — |

## Revisión de corrección de 1.1.0

- [X] T900 M-1: `ha_marketplace_list_repositories`, `list_updates`, `list_critical` y `list_removed` (y sus alias `ha_hacs_*`) recortan por `response_max_bytes`; las tres últimas añaden `total` y `truncated`
- [X] T901 B-2: `ha_marketplace_list_releases` añade una pista de reintento cuando HA responde `unknown` (límite de GitHub con cuenta conectada)
