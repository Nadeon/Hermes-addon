---

description: "Tareas de la sub-feature 011 — política de comandos, genéricas y familias (Hermes 1.2.0)"
---

# Tareas: política de comandos, genéricas y familias (011)

**Entrada**: `specs/011-politica-de-comandos/` (spec.md, plan.md, research.md,
data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `CONFIRMATIONS_DIR` en
un `tempfile.TemporaryDirectory`, `DummyMCP`/`_RecordingMCP`, `AsyncMock` del
cliente, `structlog.testing.capture_logs`. Datos ficticios (`tag-ficticio-1`,
`light.salon`, `<slug>`, centinelas de texto). Nada de la instalación real.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" python -m pytest -q -p no:cacheprovider`.
Línea base en Windows antes de empezar (2026-11-14, punta `d75af3f`): 1925
passed, 16 skipped, 6 failed (los 6 conocidos de Windows: finales de línea,
byte nulo y symlinks). Cada tramo termina con exactamente esos 6 fallos en
local; la referencia es el CI de Linux.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 cola larga alcanzable, US2 ninguna vía se salta una
protección, US3 la tabla no se queda atrás, US4 nada cambia, US5 familias,
US6 guía.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado (un commit por tramo, o varios si el agente lo prefiere, pero el
tramo no se da por cerrado con la suite en rojo).

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **1** — enmienda, tabla, deriva y verbos | **T001–T017** | Constitución 1.2.0; inventario del Supervisor por ruta; `tool_families.py`, `command_policy.py` (guardas puras), `command_table.py` revisada; generador; tests de inventario, familias, política, generador y tabla en verde. Ninguna tool nueva todavía |
| **2** — las cuatro genéricas | **T018–T029** | `ha_read_ws_command`, `ha_call_ws_command`, `sv_read_api`, `sv_call_api` registradas (siempre, aún sin familias), anotadas y probadas; `INSTRUCTIONS` sin recuento; prueba en el banco de Core |
| **3** — familias, guía, extractor y documentación | **T030–T043** | Opción `tool_families_disabled`; registro por familias y SC-005; tema `generic_commands` y `search`; extractor; CHANGELOG, DOCS, SECURITY, README, hoja de ruta y matriz de la 008 |

El tramo 2 necesita el tramo 1 integrado; el 3, los dos anteriores.

---

## Tramo 1 — enmienda, tabla, deriva y verbos

### Preparación

- [X] T001 Línea base: ejecutar la suite completa sobre la punta de la rama y anotar el recuento en el mensaje del commit del tramo (referencia: CI de Linux)
- [X] T002 Enmiendas E-1 (principio IV) y E-2 (principio V) en `docs/PRINCIPIOS.md` y en `.specify/memory/constitution.md`, y E-3 (flujo, puerta 4) y E-4 (principio XI) en la constitución, con el texto de research R-9; constitución `**Version**: 1.2.0`, `**Last Amended**` a la fecha del commit y comentario de impacto de sincronización al principio (FR-024, SC-008). Va ANTES que cualquier código, en su propio commit o el primero del tramo: el código de los tramos 1 y 2 se apoya en el texto nuevo de IV y V

### Inventario normalizado (US3)

- [X] T003 [P] [US3] Tests en `tests/test_command_inventory.py` (deben fallar con el TSV actual): `core-ws.tsv` tiene 623 filas con `comando` único y con forma `^[a-z0-9_-]+(/[a-z0-9_-]+)*$`; `supervisor-rutas.tsv` tiene 254 filas con `(metodo, ruta)` único, `metodo` ∈ {GET, POST, PUT, DELETE, PATCH}, `ruta` con `/` inicial, sin comas, corchetes, espacios ni «(n)»; toda fila de clase A o C de los dos tiene `cap` con forma `CAP-NNN`; los recuentos por clase coinciden con los de la 008 (Core: 130 cubiertos, 147 A, 103 B, 192 C, 51 D; Supervisor, por ruta: 37 cubiertas, 130 A —incluida la «A (parcial)»—, 67 B, 20 D) (FR-006)
- [X] T004 [US3] Normalizar `specs/008-cobertura-total/inventario/supervisor-rutas.tsv` a una fila por método + plantilla (research R-3): separar `GET/POST`, expandir listas y variantes con corchetes, conservar `area`, `cobertura`, `clase`, `rol_admin`, `nota` y `cap` de la fila agrupada (la nota sin el «(n)»); `A (parcial)` se queda como está. Comprobar a mano contra el registro de rutas del Supervisor 2026.11.0 los grupos dudosos y anotarlo en el commit. T003 en verde

### Catálogo de familias (US5)

- [X] T005 [P] [US5] Tests en `tests/test_tool_families.py`: cada módulo de `hermes/src/hermes/tools/` que declara `@mcp.tool()` (por AST, como `test_tools_registration`) está en exactamente una familia y cada familia nombra módulos que existen; nombres únicos con forma `^[a-z][a-z0-9_]*$`; `base` existe, contiene `ping` y `guide` y es la única no desactivable; las familias de la 1.1.2 son las de research R-5 y suman las 216 tools; `generic_commands` existe con `desde="1.2.0"` y el módulo `generic_commands` (que aún no existe: la comprobación «cada familia nombra módulos que existen» lo admite ausente con una excepción explícita y comentada, que quita T025); `validar_desactivadas([])` → vacío; nombre desconocido → `ValueError` que nombra el valor y los válidos; `base` → `ValueError`; duplicados se ignoran (FR-019)
- [X] T006 [US5] `hermes/src/hermes/tool_families.py` según data-model (neutral, sin importar nada de Hermes; comentario con el porqué de `base`) (FR-019)

### Política: búsqueda, rutas y guardas (US2)

- [X] T007 [P] [US2] Tests en `tests/test_command_policy.py` con tablas inyectadas (`Entrada` de cada categoría): (a) `decidir` para cada fila de la tabla de data-model —sin entrada, `deny`, `dedicated` con familia activa y desactivada, `read` por la de escritura, `confirm` por la de lectura, `read`/`confirm` de familia desactivada, permitido—; (b) `casar_ruta`: literal frente a parámetro (gana el literal), empate → `None`, parámetro vacío, con `..`, `.`, más de 64 caracteres o caracteres fuera de `[A-Za-z0-9._-]` no casa, método distinto no casa; (c) `validar_ruta` rechaza sin `/` inicial, `//`, barra final, `\`, `..`, `%2e`, `%2E%2E`, `?`, `#`, control, `http://x/…`, `/core/api`, `/core/api/states`, `/homeassistant/api/x` (regla `core_proxy`); (d) el predicado `es_hermes` aplicado a `{app}` con `self`, el slug propio y `algo_hermes` → `path_not_allowed` regla `self_target`, y con otra app pasa; (e) `buscar_core` es exacto (sin prefijos ni mayúsculas) (FR-003, FR-004, FR-012)
- [X] T008 [US2] `hermes/src/hermes/command_policy.py`: `Entrada`, `Permitido`, `Rechazo`, `buscar_core`, `casar_ruta`, `validar_ruta` (reutiliza `_assert_safe_request_path` de `hermes.ha`), `decidir`; tablas por parámetro con la real por defecto; comentarios en español con el porqué de cada guarda (research R-6, R-7). T007 en verde

### Generador y tabla (US3)

- [X] T009 [P] [US3] Tests en `tests/test_generar_tabla.py` con inventarios de ejemplo pequeños en `tests/fixtures/inventario/` (una fila de cada caso de research R-4): primera generación aplica cada regla (cubierto → `dedicated` con la tool del mapa; cubierto sin tool en el mapa → `deny` «sin revisar»; B y D → `deny` con el motivo de la nota; A vía D/D+T/D+X → «pendiente de tool dedicada (spec NNN)» con el número correcto; A vía T → `read`/`confirm` por verbo y método; C → «pendiente de revisión (spec 025)»; `/core/api*` → `deny`); segunda generación con una entrada editada a mano la conserva byte a byte; fila nueva → `deny` «sin revisar (nuevo en …)»; fila desaparecida → se quita y se lista; la salida es determinista (dos ejecuciones, mismo texto) y es Python válido que se importa (FR-002, FR-007)
- [X] T010 [US3] `scripts/__init__.py`, `scripts/inventario/__init__.py` y `scripts/inventario/generar_tabla.py` (research R-2, R-4): lee los TSV de `specs/008-cobertura-total/inventario/` y la matriz CAP → sub-feature/vía (como constante revisada, copiada de `specs/008-cobertura-total/plan.md`), `_DEDICADAS_INICIALES` revisado a mano, escribe `hermes/src/hermes/command_table.py` (rutas por argumento para los tests). Docstring con el procedimiento de quickstart.md. T009 en verde
- [X] T011 [US3] Tests en `tests/test_command_table.py` sobre la tabla real (deben fallar antes de T012): (a) **deriva**: cada comando de `core-ws.tsv` y cada `(metodo, ruta)` de `supervisor-rutas.tsv` tiene entrada y cada entrada está en el inventario; el mensaje nombra cada diferencia (FR-006); (b) **verbos**: lista explícita de FR-005 en el test, tokenización por `/`, `_` y `-`, ninguna `read` con uno de esos verbos ni ruta `read` con método distinto de `GET`, salvo `_EXCEPCIONES_VERBOS` (dict clave → justificación, enumerado en el mensaje del test) (FR-005, SC-002); (c) A/C con CAP (FR-006); (d) **dedicadas**: toda `dedicated` nombra una tool del registro real con todas las familias activas (`_real_registry` de `test_tools_registration`) y su `family` es la de esa tool según `tool_families` (FR-023); (e) marcas: `tool` si y solo si `dedicated`; `one_shot` solo en `read` de Core; `response="text"` solo en el Supervisor; ninguna `read` con `open_world` (FR-018); (f) ningún motivo «sin revisar»; ningún motivo vacío; solo las cuatro categorías; familias existentes (FR-001, FR-006); (g) recuentos 623 y 254 (SC-001); (h) `TABLE_HA_CORE == HA_CORE_LAST_TESTED` y `TABLE_SUPERVISOR == "2026.11.0"`; (i) toda entrada `/core/api*` y `/homeassistant/api*` es `deny`; (j) toda fila C es `deny` «pendiente de revisión (spec 025)» y toda A de vía D/D+T/D+X es `deny` «pendiente de tool dedicada (spec NNN)» con el NNN de la matriz (FR-002)
- [X] T012 [US3] Generar `hermes/src/hermes/command_table.py` con el generador (primera vez) y dejarlo con `TABLE_HA_CORE`, `TABLE_SUPERVISOR` y la cabecera que explica que se genera y se revisa a mano (FR-001, FR-002)
- [X] T013 [P] [US1] Revisión manual de los 53 comandos de Core de vía T (CAP-058, 061, 062, 063, 065, 066, 067, 068, 070, 072, 073, 074) leyendo su manejador en el código de Core 2026.11.1: `read` solo si no cambia nada; `confirm` ante la duda; suscripciones `deny` salvo las de un solo mensaje, con `one_shot=True`; `redact_extra` donde la respuesta lleve datos sensibles con claves que los marcadores no cubren (p. ej. credenciales de aplicación, CAP-073); motivos claros. Cada `read` con verbo de escritura, a `_EXCEPCIONES_VERBOS` con su porqué (FR-002, FR-005)
- [X] T014 [P] [US1] Revisión manual de las rutas del Supervisor de vía T (CAP-088, 089, 091, 092, 094) con `supervisor/api/`: `GET` de solo lectura → `read`; el resto → `confirm`; logs de plugins → `response="text"`; credenciales de registros Docker con `redact_extra` si sus claves no las cubren los marcadores (FR-002)
- [X] T015 [US3] Revisión de lo cubierto y de lo `deny`: cada `dedicated` con la tool que de verdad lo usa (las de `ha.py`, colecciones de helpers, registros, Lovelace, Supervisor…), lo que solo usa Hermes por dentro como `deny` «uso interno de Hermes», y los motivos de B y D legibles para el cliente (en español, como los de la nota). T011 en verde
- [X] T016 Control negativo del tramo 1, anotando recuentos: (a) una entrada `read` con verbo de escritura (p. ej. pasar un `…/create` a `read`) → cae el test de verbos y lo nombra; (b) quitar una entrada → cae la deriva y la nombra; añadir una inventada → cae y la nombra; (c) una `dedicated` con una tool que no existe, y otra con la familia equivocada → caen; (d) una entrada «sin revisar» → cae; (e) en `decidir`, tratar `dedicated` como permitido → caen los tests de T007; sin la regla de literal sobre parámetro → cae el de precedencia; sin la guarda `core_proxy` → caen los de `/core/api`; (f) en el generador, conservar sin mirar si la fila sigue en el inventario → cae el de filas desaparecidas; (g) quitar un módulo de su familia, o ponerlo en dos → cae el de T005; dejar que `validar_desactivadas` acepte `base` → cae. Restaurar y comprobar verde
- [X] T017 Cierre del tramo 1: suite completa (exactamente los 6 fallos conocidos en Windows), revisión del diff buscando datos personales e identificadores de modelos (principio VIII), commit en español con los recuentos de T016 y la línea base de T001

---

## Tramo 2 — las cuatro genéricas (US1, US2)

Los tests de T018–T022 se escriben y se ven fallar antes de T023–T025.

- [ ] T018 [P] [US2] Tests en `tests/test_command_policy.py`, clase del resumen (`resumir_carga`): escalar corto visible; cadena de exactamente 64 caracteres visible y de 65 → `too_long` (sin contar comillas); número largo (más de 64 cifras en JSON) → `too_long`; clave sensible (`password`, `api_key`, `network-key`) → `sensitive`; hijo de un ancestro sensible (`credentials.username`) → `sensitive`; clave de `redact_extra` → `sensitive`; texto con un JWT o `password=x` dentro (cambia con `redact_secrets`) → `sensitive`; objeto y lista → `container` con sus hijos como filas; rutas `a.b[0].c`; tipos JSON (`integer` frente a `number`, `boolean`, `null`); `bytes` de cada fila y total; carga vacía → `rows` vacío; ningún valor tapado aparece en el resultado serializado (FR-010)
- [ ] T019 [P] [US1] [US2] Tests en `tests/test_tools_generic_commands.py`, `ha_read_ws_command` con tablas inyectadas y con entradas reales: `read` → un `ws_send` con `{"type", **payload}` y respuesta `result`; resultado lista → `{count, items, truncated}`; `dedicated`, `deny`, desconocido y `confirm` → su código y **ningún** `ws_send`; `type` inválido (mayúsculas, espacio, 129 caracteres) y `payload` no objeto o con `id`/`type` → `invalid_argument` sin `ws_send`, y el log capturado no copia el `type` inválido; `one_shot` → `ws_one_shot_subscription` con tope de 10 s y nunca `ws_send` (FR-016); error de HA `unknown_command` → `ha_command_failed` con `ha_code` y la pista de versión; error de HA cuyo mensaje repite un valor centinela de la carga → el centinela no aparece en la respuesta ni en el log; Core caído → error de conexión de siempre; respuesta con un centinela bajo `password` → tapado, y con un JWT en un texto → tapado; lista enorme recortada por el tope central con `truncated` (FR-003, FR-004, FR-008, FR-013, FR-014, FR-016, FR-017)
- [ ] T020 [P] [US2] Tests en `tests/test_tools_generic_commands.py`, `ha_call_ws_command`: sin token → vista previa de contracts/tools.md (comando, categoría, motivo, CAP, nota, resumen) y ningún `ws_send`; con token → un solo `ws_send` y `executed: true`; token de otro `type` o de otra carga (un valor anidado distinto) → «does not match» y ningún `ws_send`; token reutilizado → rechazado; vista previa mayor que `response_max_bytes` → `preview_too_large` sin token y sin fichero de token; entrada `read` → `wrong_generic_tool`; con centinela en la carga (`password`) y en la respuesta de HA: ni la vista previa, ni el error, ni el log capturado, ni los ficheros de `CONFIRMATIONS_DIR` (tras vista previa y tras confirmar) lo contienen; `cached_result` es `{"executed": true}`; el log tiene un `generic_command` por llamada con `outcome` y `payload_keys` de primer nivel y sin valores (FR-009, FR-015, FR-017, FR-025, SC-004, SC-006)
- [ ] T021 [P] [US1] [US2] Tests en `tests/test_tools_generic_commands.py`, Supervisor: `sv_read_api` con ruta `read` → `sv_request("GET", path)`; ruta de texto → `sv_request_text` y `lines` con las ÚLTIMAS líneas si no caben, con `redact_secrets` y `redact_network` aplicados; cada ruta inválida de T007(c) y cada `{app}` propio de T007(d) → `path_not_allowed` sin llamar al Supervisor; `sv_call_api` sin token → vista previa con `method`, `path`, `route`, `body_summary`; con token → una llamada; token con otro método, otra ruta concreta (misma plantilla) u otro cuerpo → rechazado; `sv_read_api` con ruta `confirm` → `wrong_generic_tool`; error del Supervisor → `supervisor_request_failed` redactado y sin los valores del cuerpo aunque el Supervisor los repita; el log lleva `route` (plantilla) y nunca la ruta concreta; centinela en el cuerpo y en la respuesta (FR-011, FR-012, FR-014, FR-015, FR-017, FR-025)
- [ ] T022 [P] [US4] Tests en `tests/test_tools_registration.py`: `_HINTS_SNAPSHOT` se documenta como la referencia de la 1.1.2; `test_hints_did_not_change` pasa a comprobar que las 216 siguen con los mismos hints y que las únicas tools de más son las cuatro genéricas; hints y títulos de las genéricas según contracts/tools.md; las de escritura toman `confirmation_token` (el invariante existente las cubre); ningún título existente cambia con `"api": "API"`; instantánea nueva `tests/fixtures/esquemas_1_1_2.json` (nombre → propiedades y `required` del esquema de entrada, generada del registro ANTES de añadir las genéricas, con la forma de generarla en un comentario) y test de que las 216 la cumplen (FR-018, FR-021)
- [ ] T023 [US2] `hermes/src/hermes/security.py`: alias público `es_clave_sensible = _looks_sensitive` con el porqué; `command_policy.resumir_carga(valor, redact_extra=())` según data-model (FR-010). T018 en verde
- [ ] T024 [US1] [US2] `hermes/src/hermes/tools/generic_commands.py` (research R-6, R-7): cuatro tools con `@ready`, docstrings en inglés que dicen que solo ejecutan lo que la tabla permite, las categorías, los dos pasos y cómo consultar la tabla (`hermes_guide`); `register(mcp, ha_client, *, response_max_bytes, familias_desactivadas=frozenset())`; `_es_hermes` de `tools/addons.py` como predicado; confirmación con `create_confirmation_token`/`resolve_confirmation_token` sin omitibles y `complete_confirmation_token(result={"executed": True})`; evento `generic_command`. T019–T021 en verde (FR-003, FR-004, FR-008, FR-009, FR-011…FR-017, FR-025)
- [ ] T025 [US4] `hermes/src/hermes/tools/_annotations.py` (nombres exactos en `_READ_ONLY_EXACT`, `_DESTRUCTIVE_EXACT`, `_NON_IDEMPOTENT_EXACT`, `_OPEN_WORLD`; `"api": "API"` en `_TITLE_WORDS`, con comentarios) y registro del módulo en `hermes/src/hermes/tools/__init__.py` con `response_max_bytes`; quitar de `tests/test_tool_families.py` la excepción del módulo ausente de T005. T022 en verde (FR-018, FR-021)
- [ ] T026 [US6] `hermes/src/hermes/tools/guide.py`: las `INSTRUCTIONS` dejan de dar un recuento de tools («~216» sería falso) y mencionan en una línea las genéricas y que dependen de la tabla; test en `tests/test_tools_guide.py` que lo comprueba (FR-022, principio V)
- [ ] T027 [US1] Banco de Core (con el marcador y los helpers de la 010): `ha_read_ws_command("tag/list")` contra HA Core 2026.11.1 real; `ha_call_ws_command("tag/create", …)` vista previa + confirmación y comprobación leyendo de vuelta con `tag/list`; limpieza con `tag/delete` por la genérica. Si la 010 no está integrada en la rama, la tarea queda pendiente con una nota en el commit y en `docs/HOJA-DE-RUTA.md` (S-01) (FR-008, FR-009; FR-015 de la 008)
- [ ] T028 Control negativo del tramo 2, anotando recuentos: (a) quitar la comprobación de categoría de la tool de lectura (ejecutar cualquier entrada) → caen los de `dedicated`/`deny`/`confirm`; (b) atar el token solo a `type` (sin `payload`) → cae el de otra carga; (c) mostrar el valor aunque la clave sea sensible → caen los del resumen y el centinela de la vista previa; (d) guardar la respuesta de HA en `cached_result` → cae el del fichero del token; (e) quitar la guarda `self_target` → caen los de `{app}` propio; (f) usar `ws_send` para `one_shot` → cae; (g) registrar el `path` concreto en vez de `route` → cae el del log. Restaurar y comprobar verde
- [ ] T029 Cierre del tramo 2: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII), commit con los recuentos de T028

---

## Tramo 3 — familias, guía, extractor y documentación (US3, US4, US5, US6)

- [ ] T030 [P] [US5] Tests de la opción: en `tests/test_config_validation.py`, `tool_families_disabled` por defecto `[]`; lista con un nombre desconocido → `ValueError` en español que nombra el valor y los válidos; con `base` → `ValueError`; en `tests/test_run_sh_options.py`, `run.sh` exporta `HERMES_TOOL_FAMILIES_DISABLED` con `jq -c '.tool_families_disabled // []'`; en `tests/test_addon_manifest.py`, la opción está en `schema` (`- "str?"`) y en `options` (`[]`) (FR-020, US4 escenario 1)
- [ ] T031 [US5] `hermes/config.yaml` (esquema con comentario, opciones), `hermes/run.sh`, `hermes/src/hermes/config.py` (campo, lectura de entorno, `validate()` con `tool_families.validar_desactivadas`) y `hermes/src/hermes/__main__.py` (pasa la opción a `register_all_tools`). T030 en verde (FR-020)
- [ ] T032 [P] [US4] [US5] Tests en `tests/test_tools_registration.py`: (a) desactivar cada familia desactivable, una a una, quita exactamente las tools de sus módulos y ninguna más; (b) **SC-005**: con todas las familias `desde="1.2.0"` desactivadas, el conjunto de nombres es exactamente `_HINTS_SNAPSHOT` y los hints coinciden; (c) por defecto, `_HINTS_SNAPSHOT` ⊆ registro con los mismos hints; (d) por AST, cada llamada `register_*` de `register_all_tools` está dentro de una comprobación de su familia y la familia coincide con `familia_de_modulo`; (e) el log de arranque `tool_families` lleva las desactivadas y el número de tools; (f) los esquemas de entrada de las 216 siguen cumpliendo `esquemas_1_1_2.json`, con una única diferencia permitida y comentada: `search` opcional (fuera de `required`) en `hermes_guide` (FR-020, FR-021, SC-005)
- [ ] T033 [P] [US5] Tests en `tests/test_tools_generic_commands.py` con familias desactivadas: comando `dedicated` cuya tool es de una familia desactivada → `use_dedicated_tool` con `family_disabled: true` y sin llamar a HA; entrada `read`/`confirm` con una familia desactivada (tabla inyectada) → `family_disabled`; con `generic_commands` desactivada, las cuatro no se registran (FR-003, FR-004, US5 escenario 2)
- [ ] T034 [US5] `register_all_tools(..., tool_families_disabled=None)` en `hermes/src/hermes/tools/__init__.py`: lectura de la opción como las demás, cada bloque dentro de `if _activa("<familia>")` (sin reescribir el registro), familias desactivadas a `generic_commands.register`, log `tool_families`. Actualizar `_do_register` de los tests si hace falta. T032 y T033 en verde (FR-020, FR-021)
- [ ] T035 [P] [US6] Tests en `tests/test_tools_guide.py`: tema `generic_commands` con contenido y alias (`commands`, `generic`, `ws`, `api`, `table`); el índice lo menciona; `search="tag"` lista entradas de tags con categoría y tool o motivo; una entrada con `example` lo muestra y una sin él no inventa ninguno; búsqueda sin resultados → mensaje con cómo buscar; más de 50 resultados → 50 filas y «refine the search»; `search` con otro tema se ignora y lo dice; sin `search`, los temas de la 1.1.2 devuelven lo mismo que antes (FR-022, US4 escenario 3)
- [ ] T036 [US6] `hermes/src/hermes/tools/guide.py`: tema, alias, argumento `search` (docstring en inglés), consulta con `command_policy` (research R-8). T035 en verde (FR-022)
- [ ] T037 [US6] Ejemplos de carga (`example`) revisados contra el código de Core en las entradas `read`/`confirm` más útiles (al menos `tag/list`, `tag/create`, `tag/update`, `tag/delete`) en `command_table.py`, con datos ficticios (FR-001, FR-022)
- [ ] T038 [P] [US3] Tests en `tests/test_extractor_inventario.py` con árboles mínimos en `tests/fixtures/inventario/` (código inventado, no copiado de HA): un componente con `@websocket_command({vol.Required("type"): "demo/listar"})`, otro con el tipo en una constante importada de otro módulo, un `BASE_COMMAND_MESSAGE_SCHEMA.extend`, una colección de almacenamiento expandida por prefijo (`demo_coleccion/list|create|update|delete`); un `supervisor/api/__init__.py` mínimo con `web.get`/`web.post` y una ruta con parámetro. Comprobar: comandos y rutas extraídos; fusión con un TSV previo que conserva las columnas manuales; filas nuevas con columnas manuales vacías; el extractor no importa el código leído (un módulo de ejemplo que lanza al importarse no hace fallar la extracción) (FR-007)
- [ ] T039 [US3] `scripts/inventario/extraer.py` (método de research R-0 de la 008, solo AST y texto). T038 en verde (FR-007)
- [ ] T040 [US3] Comprobación manual: ejecutar el extractor contra el código local de Core 2026.11.1 y del Supervisor 2026.11.0 (nunca en el CI) y comprobar que los dos TSV no cambian (o explicar cada diferencia y corregir extractor o inventario); anotar el resultado en el commit (FR-007, quickstart)
- [ ] T041 Documentación (FR-026): sección «Política y genéricas» en `## [1.2.0] — <fecha de publicación>` de `hermes/CHANGELOG.md` (tabla, genéricas, familias, guía, enmiendas); `hermes/DOCS.md` con `tool_families_disabled` y la lista de familias; `SECURITY.md` con la tabla fail-closed, las genéricas y lo que nunca hacen; `README.md` y `README.es.md` sincronizados (genéricas y familias); estado de la 011 en la tabla «Programa de cobertura total (spec 008)» de `docs/HOJA-DE-RUTA.md`; filas CAP-001…004, 007 y 008 de la matriz de trazabilidad de `specs/008-cobertura-total/plan.md` con los nombres definitivos y los ficheros de test
- [ ] T042 Control negativo del tramo 3, anotando recuentos: (a) no validar la opción → caen los de nombre desconocido y `base`; (b) registrar una familia aunque esté desactivada → caen (a) y SC-005 de T032; (c) no pasar las familias desactivadas a las genéricas → cae el de `family_disabled: true`; (d) en la guía, inventar un ejemplo cuando no hay → cae; (e) el extractor que importa el módulo leído → cae el de importación. Restaurar y comprobar verde
- [ ] T043 Cierre del tramo 3: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII), commit con los recuentos de T042 y el resultado de T040

---

## Dependencias

- Tramo 1: T001 → T002 → resto. T003 → T004. T005 → T006. T007 → T008. T009 → T010 (necesita T006 para las familias). T011 necesita T006 y T008; T012 necesita T010 y T011; T013, T014 y T015 tras T012 (T013 y T014 en paralelo). T016 tras T015. T017 el último.
- Tramo 2 (tras el tramo 1): T018…T022 en paralelo; T023 tras T018; T024 tras T019…T021 y T023; T025 tras T022 y T024; T026 tras T025; T027 tras T025 (y la 010); T028, T029 al final.
- Tramo 3 (tras el tramo 2): T030 → T031; T032 y T033 → T034 (necesita T031); T035 → T036; T037 tras T036; T038 → T039 → T040; T041 tras todo lo anterior; T042, T043 al final.

## Paralelismo

- Tramo 1: T003, T005, T007 y T009 (ficheros de test distintos); T013 y T014.
- Tramo 2: T018…T022.
- Tramo 3: T030, T032, T033, T035 y T038.

## Estrategia

MVP de la sub-feature = tramos 1 y 2: la cola larga alcanzable por las
genéricas, fail-closed y con la tabla vigilada por los tests de deriva y de
verbos. El tramo 3 añade el control del contexto (familias), el
descubrimiento (guía) y la regeneración (extractor), y cierra la
documentación. Todo sale en la 1.2.0 con el resto del programa.
