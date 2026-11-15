# Plan de implementación: tienda de apps (030)

**Rama**: `feat/030-tienda-de-apps` (sale de `feat/cobertura-total`, punta
`02beafc`) · **Spec**: [spec.md](spec.md) · **Paraguas**:
[008](../008-cobertura-total/plan.md), tarea T014, «M, 2 tramos».

## Resumen

Nueve tools nuevas en una familia nueva, `app_store`: cinco para los
repositorios de la tienda y su recarga (listar, añadir y quitar con
confirmación, reparar, recargar) y cuatro para las apps (changelog,
documentación, disponibilidad y reconstrucción con confirmación). Tres tools
de la 1.1.2 mejoran su vista previa sin cambiar su esquema:
`sv_install_addon` (disponibilidad, ya instalada), `sv_update_addon`
(changelog y disponibilidad) y `sv_set_addon_options` (validación con el
Supervisor antes del token). Las 15 entradas «pendiente de tool dedicada
(spec 030)» de la tabla pasan a `dedicated`.

Hallazgo que cambia el alcance de la 008: el Supervisor 2026.11.0 **ignora
`{version}`** en `install/{version}`, `update/{version}` y
`GET /store/addons/{app}/{version}`. No se añade un argumento `version` que
mentiría; esas rutas apuntan a la tool sin versión (research R-2).

## Contexto técnico

**Lenguaje**: Python 3.13. **Dependencias**: las de Hermes (SDK MCP, aiohttp,
structlog); ninguna nueva. **Pruebas**: pytest + `unittest` asíncrono con un
Supervisor simulado (`MockHAClient`). **Plataforma**: add-on de HAOS; tests
en Windows y en el CI de Linux. **Restricciones**: `response_max_bytes`
(131072 por defecto), API v1 del Supervisor, rol `manager` como límite de
rutas (test de la 014).

**Escala**: 9 tools en 2 módulos nuevos (`tools/store_repositories.py`,
`tools/store_apps.py`) y un módulo común sin tools (`tools/_store.py`); cambios en `tools/addons.py` (vistas previas y
descripciones de tres tools), `tool_families.py`, `command_table.py` (15
líneas), `tools/__init__.py`, `tools/_annotations.py`, `tools/guide.py`,
`tests/banco/cobertura_escrituras.py`; una fixture y 4 ficheros de test
nuevos; ajustes en `tests/test_command_table.py`,
`tests/test_tools_registration.py`, `tests/test_tool_families.py`,
`tests/test_tools_guide.py`, `tests/test_tools_supervisor.py`; documentación
(`CHANGELOG`, `HOJA-DE-RUTA`, `BANCO-SUPERVISOR`, `DOCS`, `README`s,
`SECURITY.md`, matriz de la 008).

## Comprobación de la constitución

Contra la constitución 1.2.0 (con las enmiendas de la 011).

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Añadir un repositorio (entrada de código de terceros) y quitarlo piden dos pasos con vista previa que dice la URL exacta y el riesgo; los textos de terceros llevan `_third_party_text`; todas las respuestas pasan por `redact_secrets`/`redact_structure` o son campos elegidos; rutas validadas antes de interpolar (`validate_slug`); todas dentro del rol `manager` (FR-002, FR-003, FR-018, FR-019). | OK |
| II. Secretos | La contraseña de una URL con credenciales se tapa en vista previa, respuestas, errores y log; el mensaje de validación de opciones se redacta y se le quitan los valores secretos literales; el evento de log no lleva URL, textos ni opciones; centinelas en tests (FR-013, FR-018). | OK |
| III. Fail-closed | Argumentos inválidos sin llamada; todo lo que el Supervisor rechazaría (ya añadido, integrado, en uso, no disponible, ya instalada, no instalada, desligada, versión cambiada, imagen sin `force`, opciones inválidas) se rechaza sin token (SC-003). La validación de opciones que no se pudo hacer se dice (`checked: false`) y la escritura sigue validando en el Supervisor. | OK |
| IV. Dos pasos | `sv_add_store_repository`, `sv_remove_store_repository` y `sv_rebuild_addon` con token atado a los argumentos; quitar, además, al estado leído (`estado` de la 018). Reparar y recargar sin token, justificado (research R-6). Las vistas previas dicen el efecto real (borra imagen, deja de poder instalarse, código no revisado). | OK |
| V. Nombre y descripción | No hay argumento `version` porque el Supervisor lo ignora; las descripciones de instalar y actualizar dicen «la versión de la tienda»; anotaciones según contracts/tools.md (añadir y reconstruir, destructivas; las que provocan descargas, de mundo abierto); «app (add-on)» como la 027. | OK |
| VI. Lo que no se puede probar | Unitarios contra un Supervisor simulado con la forma de 2026.11.0. El banco de Core no puede ejecutar las cinco que modifican: van a `FUERA_DEL_BANCO`, a la matriz como `VM` / `pendiente` y a la tanda 2 del procedimiento (FR-022, SC-007). | OK con pendiente declarado |
| VII. Control negativo | T012 y T026 con recuentos: validación de URL, tapado de credenciales, rechazo por apps instaladas, estado del token, texto «No changelog found», trozos, rechazos de reconstrucción, validación de opciones, `dedicated` en la tabla. | OK |
| VIII. Privacidad | Fixtures con `https://example.com/repo-ficticio`, `abcd1234`, `<slug>`, `local_ejemplo`; nada de repositorios ni apps reales salvo los `slug` integrados, que son constantes públicas del Supervisor; revisión del diff en cada tramo. | OK |
| IX. Cambios mínimos | Las tres tools de la 1.1.2 solo cambian su vista previa y sus descripciones; ningún argumento nuevo; no se rechaza «sin actualización» en `sv_update_addon` (no lo pide la 008); se reutilizan `_es_hermes`, `_self_warning`, `_LONG_OP_TIMEOUT`, el sobre común y el formato de `_third_party_text`. | OK |
| X. Comentarios en español | Comentarios con el porqué en español; descripciones, errores y eventos en inglés. | OK |
| XI. Versionado | Sin subida de versión; sección propia en `## [1.2.0] — <fecha de publicación>`. | OK |

**Desviación de la 008, justificada**: FR-051 pedía instalar o actualizar una
versión concreta; el Supervisor 2026.11.0 no lo permite (research R-2).
**Lectura de la 008 aplicada**: `sv_check_addon_availability` se llama
`sv_get_addon_availability` (research R-1).

**Tras el diseño**: sin cambios en la tabla de cumplimiento.

## Diseño

### Tramo 1 — repositorios y recarga (CAP-082, parte)

- `tool_families.py`: familia `app_store` (1.2.0, desactivable) con el
  módulo `store_repositories` y una descripción que solo nombra repositorios
  y recarga; el tramo 2 añade `store_apps` y completa la descripción
  (data-model «Familia»).
- `tools/_store.py` (módulo sin tools, como `tools/_logs.py` de la 013):
  funciones puras compartidas por los dos módulos y por `tools/addons.py`,
  con su test: `es_integrado(slug)` con los cinco `slug` del Supervisor
  2026.11.0, `tapar_credenciales(url)` y `texto_de_terceros(campos)` (el
  formato de `_third_party_text`). Existir aparte evita el ciclo
  `addons` ↔ `store_apps` del tramo 2.
- `tools/store_repositories.py`: `register(mcp, ha_client, *,
  response_max_bytes)`. Funciones puras con su test:
  `_validar_url_repositorio` (data-model), `_resumen_repositorio`. Lectura
  común `_repositorios_y_apps()` (`GET /store/repositories` +
  `GET /store/addons`).
  Cinco tools según contracts/tools.md. Vistas previas con
  `create_confirmation_token` (`estado` en quitar). `texto_de_terceros`
  reutiliza `_THIRD_PARTY_WARNING` de `tools/marketplace.py` (o del módulo
  común si la 015 lo movió, S-05). `_LONG_OP_TIMEOUT` importado de `tools/addons.py`. Evento
  `app_store_action`.
- `tools/_annotations.py`: `sv_add_store_repository` y
  `sv_remove_store_repository` en `_DESTRUCTIVE_EXACT`;
  `sv_add_store_repository`, `sv_repair_store_repository` y
  `sv_reload_store` en `_OPEN_WORLD`; con un comentario del porqué.
- `tools/__init__.py`: registro dentro de la comprobación de la familia
  (patrón de la 011/013).
- `command_table.py`: las siete entradas del tramo 1 a `dedicated` a mano;
  regenerar sin cambios.
- `tools/guide.py`: tema `app_store` (parte de repositorios), alias, índice,
  instrucciones del servidor con la familia activa.
- Banco y matriz: `_SV_TIENDA` en `tests/banco/cobertura_escrituras.py` para
  las cuatro tools que modifican; filas `VM` / `pendiente` en la matriz;
  líneas en «Tools nuevas del programa» de `docs/BANCO-SUPERVISOR.md`
  (añadir y quitar un repositorio de prueba, reparar, recargar).

### Tramo 2 — fichas, disponibilidad, reconstrucción y vistas previas (CAP-082 resto, CAP-093)

- `tools/_store.py` gana las lecturas comunes: `ficha_de_tienda(slug)`,
  `disponibilidad(slug)` y `texto_de_la_app(slug, tipo)` (detección de los
  textos «No … found», redacción sobre el texto entero y corte por trozos).
- `tools/store_apps.py`: `sv_get_addon_changelog`,
  `sv_get_addon_documentation`, `sv_get_addon_availability` y
  `sv_rebuild_addon`, sobre esas lecturas. `store_apps` entra en la
  familia.
- `tools/addons.py`: la vista previa de `sv_install_addon` usa
  `ficha_de_tienda` y `disponibilidad`; la de `sv_update_addon` añade el
  principio del changelog con `texto_de_la_app`; la de
  `sv_set_addon_options` llama a `options/validate` con las opciones
  finales. Descripciones: «a la versión de la tienda» y «app (add-on)».
- `_annotations.py`: `sv_rebuild_addon` en `_DESTRUCTIVE_EXACT` y
  `_OPEN_WORLD`.
- `command_table.py`: las ocho entradas restantes; ninguna «spec 030».
- Guía completa (fichas, reconstrucción, sin versión concreta) y el tema
  `supervisor` actualizado.
- Banco y matriz: `sv_rebuild_addon`.
- Documentación final y matriz de la 008.

## Estructura de ficheros

```text
hermes/src/hermes/
├── tool_families.py               # familia app_store (T1), módulo store_apps (T2)
├── command_table.py               # 7 entradas (T1) + 8 (T2) a dedicated
└── tools/
    ├── __init__.py                # registro por familia
    ├── _annotations.py            # destructivas y mundo abierto
    ├── _store.py                  # comunes sin tools: puras (T1), lecturas (T2)
    ├── store_repositories.py      # (T1) 5 tools
    ├── store_apps.py              # (T2) 4 tools
    ├── addons.py                  # (T2) vistas previas de install/update/set_options
    └── guide.py                   # tema app_store
tests/
├── fixtures/supervisor_tienda.py  # Supervisor simulado (forma 2026.11.0)
├── test_store_comun.py               # (T1) funciones puras de _store.py
├── test_tools_store_repositories.py   # (T1)
├── test_tools_store_apps.py           # (T2)
├── test_tools_addons_tienda.py        # (T2) vistas previas de la 1.1.2
├── test_command_table.py, test_tools_registration.py, test_tool_families.py,
├── test_tools_guide.py, test_matriz_pruebas.py (sin cambios de código)
└── banco/cobertura_escrituras.py  # FUERA_DEL_BANCO
docs/HOJA-DE-RUTA.md, docs/BANCO-SUPERVISOR.md, hermes/CHANGELOG.md,
hermes/DOCS.md, README.md, README.es.md, SECURITY.md,
specs/008-cobertura-total/plan.md (matriz)
```

## Trazabilidad (FR de la 030 → FR/CAP de la 008 → tarea → test)

| FR 030 | 008 | Tareas | Test |
|---|---|---|---|
| FR-001 | FR-051 / CAP-082 | T003, T007 | `tests/test_tools_store_repositories.py` (`TestListar`) |
| FR-002 | FR-051 / CAP-082 | T004, T007 | ídem (`TestAnadir`) |
| FR-003 | FR-051 / CAP-082 | T005, T007 | ídem (`TestQuitar`) |
| FR-004 | FR-051 / CAP-082 | T005, T007 | ídem (`TestReparar`) |
| FR-005 | FR-051 / CAP-082 | T005, T007 | ídem (`TestRecargar`) |
| FR-006 | FR-051 / CAP-082 | T016, T020 | `tests/test_tools_store_apps.py` (`TestChangelog`) |
| FR-007 | FR-051 / CAP-082 | T016, T020 | ídem (`TestDocumentacion`) |
| FR-008 | FR-051 / CAP-082 | T017, T020 | ídem (`TestDisponibilidad`) |
| FR-009 | FR-051 / CAP-082 | T019, T021 | `tests/test_tools_addons_tienda.py` (`TestInstalar`) |
| FR-010 | FR-051 / CAP-082 | T019, T021 | ídem (`TestActualizar`) |
| FR-011 | FR-051 / CAP-082 | T019, T021, T022, T024 | ídem (`TestSinVersion`), `tests/test_command_table.py`, `tests/test_tools_guide.py` |
| FR-012 | FR-052 / CAP-093 | T018, T020 | `tests/test_tools_store_apps.py` (`TestReconstruir`) |
| FR-013 | FR-052 / CAP-093 | T019, T021 | `tests/test_tools_addons_tienda.py` (`TestValidarOpciones`) |
| FR-014 | FR-012, FR-051, FR-052 | T009, T022 | `tests/test_command_table.py` |
| FR-015 | FR-010 | T002, T008, T020, T023 | `tests/test_tool_families.py`, `tests/test_tools_registration.py` |
| FR-016 | FR-018, FR-020 | T008, T023 | `tests/test_tools_registration.py` |
| FR-017 | FR-018 | T003, T016 | los de FR-001, FR-006, FR-007 |
| FR-018 | FR-019 | T003–T006, T016–T019 | centinelas y `capture_logs` en los tres ficheros |
| FR-019 | CAP-082 | T003–T005, T016–T019 | ídem |
| FR-020 | FR-011, FR-018 | T010, T024 | `tests/test_tools_guide.py` |
| FR-021 | FR-018 | T019, T021 | `TestTerminologiaApps` (027) si está integrada; si no, `TestDescripciones` en `tests/test_tools_addons_tienda.py` |
| FR-022 | FR-016 | T011, T025 | `tests/test_matriz_pruebas.py`, `tests/banco/` (invariantes) |
| FR-023 | FR-022, FR-023 | T013, T027 | `TestToolCountInDocs`, `TestFamiliasEnLaDocumentacion`, `_matriz_008` |

## Tramos

| Tramo | Tareas | Cubre |
|---|---|---|
| 1 | T001–T014 | Familia, `store_repositories` (5 tools), 7 entradas, guía (parte), banco y matriz de 4 tools, documentación (parte) |
| 2 | T015–T028 | `store_apps` (4 tools), `_store.py`, vistas previas de las 3 tools de la 1.1.2, 8 entradas, guía completa, banco y matriz de `sv_rebuild_addon`, documentación final y matriz de la 008 |

El tramo 2 necesita el tramo 1 integrado.

## Pruebas en vivo (pendiente declarado)

En la VM de la 014 (tanda 2, con instantánea): añadir un repositorio de
prueba público y comprobar la vista previa y `ha store repositories`;
quitarlo; intentar quitar uno con una app instalada (rechazo sin token);
reparar; recargar; leer el changelog y la documentación de una app oficial;
disponibilidad de una app de otra arquitectura; reconstruir una app local
de prueba; `sv_set_addon_options` con una opción inválida (sin token);
`sv_install_addon` de una app no disponible (sin token). La matriz las
lista como `VM` / `pendiente`.

## Dependencias

- 011 (tabla, genéricas, familias) y 014 (matriz y procedimiento): en la
  rama.
- 015 (en paralelo): toca `tools/__init__.py`, `tool_families.py`,
  `command_table.py`, `tools/guide.py`, `tools/_annotations.py` y quizá el
  formato de `_third_party_text`. Choques de fusión esperables en líneas
  vecinas, no de diseño; la 015 no toca `sv_update_addon` (lo deja a la 030).
- 027 (en paralelo): reescribe las descripciones de `tools/addons.py` y el
  tema `supervisor` de la guía. El tramo 2 de la 030 toca las de
  `sv_install_addon`, `sv_update_addon` y `sv_set_addon_options`: al
  integrar, se combinan las dos (riesgo anotado).
- 026 depende de esta (patrón de textos de terceros).

## Riesgos

- **Fusión con la 027 y la 015** (arriba). Mitigación: el tramo 2 se hace
  sobre la rama con la 027 integrada si ya lo está, y los cambios en
  `addons.py` se limitan a las vistas previas y a una frase de cada
  descripción.
- **El texto «No changelog found…» cambia** en una versión futura del
  Supervisor: el texto de error saldría como changelog. Mitigación: la ficha
  se lee antes (la app existe) y el test fija el texto de 2026.11.0; la
  deriva del Supervisor se revisa al subir de versión.
- **Lista de repositorios integrados** fija: si el Supervisor añade otro, la
  vista previa de quitarlo emitiría token y el Supervisor lo rechazaría
  (error claro, nada se rompe). Se anota en la guía de mantenimiento del
  inventario.
- **Timeouts**: añadir, recargar y reconstruir pueden tardar más de 300 s en
  un sistema lento; el error lo dice y la operación sigue en el Supervisor.
