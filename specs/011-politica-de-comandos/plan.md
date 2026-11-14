# Plan de implementación: política de comandos, genéricas y familias (011)

**Rama**: `feat/011-politica-de-comandos` (se integra en `feat/cobertura-total`) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md) | **Paraguas**: [008](../008-cobertura-total/plan.md)

## Resumen

Una tabla de clasificación (`command_table.py`, 623 comandos de Core y 254
rutas del Supervisor) generada desde los inventarios de la 008 y revisada a
mano, consultada por un módulo neutral de política (`command_policy.py`) que
decide fail-closed qué puede ejecutar cada una de las cuatro tools genéricas
nuevas (`ha_read_ws_command`, `ha_call_ws_command`, `sv_read_api`,
`sv_call_api`). Las de escritura confirman siempre con una vista previa que
resume la carga con una regla medible. Tests de verbos y de deriva; extractor y
generador versionados en `scripts/inventario/`. Familias de tools
desactivables con `tool_families_disabled` (todas activas por defecto; las
genéricas en una familia nueva). Guía con tema y consulta de la tabla. Antes
del código, enmiendas E-1…E-4 de la constitución. Tres tramos.

Detalle y alternativas en [research.md](research.md); entidades en
[data-model.md](data-model.md); formas de respuesta en
[contracts/tools.md](contracts/tools.md); validación en
[quickstart.md](quickstart.md).

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x (MCPServer), aiohttp, structlog, pydantic 2 (sin dependencias nuevas) · **Almacenamiento**: tokens de confirmación en `/data/pending_confirmations` (sin cambios) · **Tests**: pytest, `unittest.IsolatedAsyncioTestCase`, `DummyMCP`/`_RecordingMCP`, `AsyncMock` del cliente, `structlog.testing.capture_logs`; banco de Core de la 010 · **Plataforma**: add-on de Home Assistant OS.

**Restricciones**: fail-closed (III); token atado a tool, comando y carga (IV); anotaciones verdaderas (V); ningún valor de la carga en log, disco ni error (II); control negativo por guarda (VII); repositorio público (VIII); las 216 tools de la 1.1.2 sin cambios (FR-020 de la 008).

**Escala**: 4 tools nuevas; 3 módulos nuevos en el paquete (`command_policy.py`, `command_table.py`, `tool_families.py`) y uno de tools (`tools/generic_commands.py`); 3 scripts en `scripts/inventario/`; cambios en `tools/__init__.py`, `tools/_annotations.py`, `tools/guide.py`, `config.py`, `__main__.py`, `run.sh`, `config.yaml` y `security.py` (un alias público); unos 7 ficheros de test nuevos.

## Comprobación de la constitución

Contra la constitución 1.1.0 y, tras el tramo 1, contra la 1.2.0 con E-1…E-4.

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Las genéricas solo ejecutan lo que la tabla permite; lo dedicado se rechaza hacia su tool (no se saltan la protección del dashboard principal, la denylist ni la autoprotección); `/core/api*` y el propio Hermes siempre fuera; toda respuesta pasa por redacción y tope (FR-003, FR-012, FR-014). | OK |
| II. Secretos | Resumen de la carga con valores tapados por clave sensible, por patrón y por longitud; carga no omitible (no se escribe en `/data`); `cached_result` solo `{"executed": true}`; log solo con nombres de claves de primer nivel y bytes; centinela por genérica (FR-010, FR-015, FR-017, FR-025). | OK |
| III. Fail-closed | Lo no clasificado se rechaza; lo nuevo del inventario entra como `deny` «sin revisar»; clase C y lo pendiente de tool dedicada, `deny`; familia desconocida → no arranca; plantillas ambiguas → no clasificado; vista previa que no cabe → sin token (FR-002, FR-003, FR-007, FR-010, FR-012, FR-020). | OK |
| IV. Dos pasos, token atado | Las de escritura confirman **siempre**; token atado a tool + comando/método/ruta + carga completa; un solo uso; sin omitibles. La vista previa genérica no interpreta el efecto: lo cubre **E-1**, que se aplica en el tramo 1 antes del código (FR-009, FR-011, FR-024). | OK con E-1 |
| V. Nombre y descripción | Lectura y escritura separadas para que `readOnlyHint` sea verdad; anotaciones por nombre exacto (no heredan prefijos); test de verbos; ninguna `read` de mundo abierto; descripciones que dicen que dependen de la tabla. La honestidad depende de la tabla: lo cubre **E-2** (FR-005, FR-018, FR-024). | OK con E-2 |
| VI. Lo que no se puede probar | Unitarios para todas las guardas; lectura y escritura reales por la genérica en el banco de Core de la 010 (T027); el extractor se prueba con árboles mínimos y se contrasta a mano con el código real (T040). | OK |
| VII. Control negativo | Cada tramo tiene su tarea de control negativo con recuentos (T016, T028, T042). | OK |
| VIII. Privacidad | Datos ficticios (`tag-ficticio-1`, `light.salon`, `<slug>`), nada de la instalación del mantenedor en tabla, tests ni inventarios; revisión del diff por tramo. | OK |
| IX. Cambios mínimos | El registro solo se envuelve en comprobaciones de familia (no se reescribe); `_es_hermes` y `_looks_sensitive` se reutilizan sin cambiar su comportamiento; `hermes_guide` gana un argumento opcional; lo de otras sub-features queda `deny` pendiente. | OK |
| X. Comentarios en español | Comentarios y mensajes de arranque en español; descripciones, errores al cliente y eventos en inglés. | OK |
| XI. Versionado | Sin subida de versión (la hace la 009); sección en `## [1.2.0] — <fecha de publicación>`, que **E-4** legitima. | OK con E-4 |
| Flujo, puerta 4 | El banco de Core entra en los checks: lo nombra **E-3**. | OK con E-3 |

**Enmiendas que aplica esta sub-feature** (tarea T002, primer commit del
tramo 1, antes de cualquier código): E-1 (IV) y E-2 (V) en
`docs/PRINCIPIOS.md` y en `.specify/memory/constitution.md`; E-3 (flujo,
puerta 4) y E-4 (XI) solo en la constitución. Texto en research R-9.
Constitución **1.1.0 → 1.2.0** (MINOR por E-3), `Last Amended` a la fecha del
commit y comentario de impacto de sincronización al principio del fichero.

**Tras el diseño**: sin cambios en la tabla. Ninguna desviación sin justificar.

## Diseño

### Tramo 1 — tabla, deriva, verbos y enmienda

1. **Enmienda** (T002): texto de R-9.
2. **Inventario del Supervisor normalizado** (T004): 254 filas, una por
   método + plantilla, mismas columnas.
3. **`hermes/src/hermes/tool_families.py`** (T006): `Familia`, `FAMILIAS`
   (catálogo de research R-5 más `generic_commands` con `desde="1.2.0"`),
   `familia_de_modulo()`, `validar_desactivadas()`. Neutral: no importa nada de
   Hermes.
4. **`hermes/src/hermes/command_policy.py`** (T008): `Entrada`; `buscar_core(type)`;
   `casar_ruta(method, path) -> tuple[clave, Entrada] | None` (R-7);
   `validar_ruta(path)` (reutiliza `_assert_safe_request_path` de `ha.py` y
   añade `\`, `//`, barra final, esquema y host, proxy de Core);
   `decidir(tool, entrada, familias_desactivadas, familia_de_tool,
   es_hermes=None) -> Permitido | Rechazo` (tabla de data-model). Las tablas
   se pasan como parámetro con valor por defecto la real, para probar con
   tablas inyectadas.
5. **`scripts/inventario/generar_tabla.py`** (T010; con `scripts/__init__.py`
   y `scripts/inventario/__init__.py` para poder importarlo desde los tests):
   reglas de research R-4 y fusión de R-2; `_DEDICADAS_INICIALES` revisado a
   mano; salida determinista.
6. **`hermes/src/hermes/command_table.py`** (T012): generado y revisado; cada
   excepción del test de verbos con su comentario.
7. **Tests de la tabla** (T011): deriva, verbos, CAP, `dedicated` → tool
   existente con la misma familia (FR-023), marcas, recuentos, versiones.

### Tramo 2 — las cuatro genéricas

1. **`security.py`**: alias público `es_clave_sensible = _looks_sensitive`
   (sin cambiar la función).
2. **`command_policy.resumir_carga(valor, redact_extra) -> dict`** (FR-010).
3. **`hermes/src/hermes/tools/generic_commands.py`**: `register(mcp,
   ha_client, *, response_max_bytes, familias_desactivadas=frozenset())`; las
   cuatro tools con `@ready`; guardas por `decidir`; ejecución según R-6;
   respuesta redactada con `redact_structure` (+ `redact_extra`) y
   `redact_secrets` en los textos; texto por líneas con `redact_secrets` y
   `redact_network`, recortado desde el final; vista previa medida con
   `tam_json` frente a `response_max_bytes`; `create_confirmation_token` /
   `resolve_confirmation_token` / `complete_confirmation_token(result=
   {"executed": True})`; evento `generic_command`.
4. **`tools/__init__.py`**: registra el módulo (sin comprobación de familia
   todavía; la añade el tramo 3) con `response_max_bytes`.
5. **`tools/_annotations.py`**: las dos de lectura en `_READ_ONLY_EXACT`; las
   dos de escritura en `_DESTRUCTIVE_EXACT`, `_NON_IDEMPOTENT_EXACT` y
   `_OPEN_WORLD`; `"api": "API"` en `_TITLE_WORDS` (no cambia ningún título
   existente: lo comprueba la instantánea).
6. **`tests/test_tools_registration.py`**: `_HINTS_SNAPSHOT` pasa a ser la
   referencia de la 1.1.2 (se documenta en el test); `test_hints_did_not_change`
   comprueba que esas 216 siguen con los mismos hints y que las únicas tools
   extra son las cuatro genéricas con los hints de contracts/tools.md.

### Tramo 3 — familias, guía, extractor y documentación

1. **Opción** (`config.yaml`, `run.sh`, `config.py`, `__main__.py`):
   `tool_families_disabled` según data-model.
2. **`register_all_tools(..., tool_families_disabled=None)`**: si es `None`, se
   lee de `load_config()` como las demás; cada bloque de registro va dentro de
   `if _activa("<familia>")`; las genéricas reciben las familias desactivadas;
   log `tool_families` con las desactivadas y el número de tools registradas.
   Test por AST: cada `register_*` de `register_all_tools` está dentro de una
   comprobación de familia y la familia coincide con `familia_de_modulo`.
3. **`tools/guide.py`**: tema `generic_commands` y alias; argumento `search`;
   índice y `INSTRUCTIONS` sin recuento de tools; consulta de la tabla con
   `command_policy` (R-8).
4. **`scripts/inventario/extraer.py`**: Core por AST (claves `type` de
   `websocket_command` y de los esquemas `BASE_COMMAND_MESSAGE_SCHEMA.extend`,
   constantes resueltas entre módulos, colecciones de almacenamiento
   expandidas por prefijo), Supervisor desde el registro de rutas de
   `supervisor/api/__init__.py`; conserva las columnas manuales; nunca importa
   ni ejecuta el código leído (el método de research R-0 de la 008).
5. **Documentación**: CHANGELOG, DOCS, SECURITY, README, hoja de ruta y matriz
   de la 008 (FR-026).

## Estructura de ficheros

```text
hermes/src/hermes/
├── command_policy.py          # nuevo (tramo 1; resumen de la carga en el tramo 2)
├── command_table.py           # nuevo, generado y revisado (tramo 1)
├── tool_families.py           # nuevo (tramo 1)
├── security.py                # alias es_clave_sensible (tramo 2)
├── config.py                  # opción (tramo 3)
├── __main__.py                # pasa la opción (tramo 3)
└── tools/
    ├── generic_commands.py    # nuevo (tramo 2)
    ├── __init__.py            # registro (tramo 2) y familias (tramo 3)
    ├── _annotations.py        # tramo 2
    └── guide.py               # tramo 3
hermes/config.yaml, hermes/run.sh          # tramo 3
scripts/__init__.py, scripts/inventario/__init__.py
scripts/inventario/generar_tabla.py        # tramo 1
scripts/inventario/extraer.py              # tramo 3
specs/008-cobertura-total/inventario/supervisor-rutas.tsv   # normalizado (tramo 1)
tests/test_command_inventory.py, test_tool_families.py,
      test_command_policy.py, test_generar_tabla.py, test_command_table.py   # tramo 1
tests/test_tools_generic_commands.py                         # tramo 2
tests/test_extractor_inventario.py, tests/fixtures/inventario/          # tramo 3
```

## Trazabilidad (FR de la 011 → FR/CAP de la 008 → tarea → test)

| FR 011 | FR 008 | CAP | Tareas | Test |
|---|---|---|---|---|
| FR-001 | FR-001 | 001 | T011, T012, T037 | `test_command_table.py` (estructura, recuentos, versiones) |
| FR-002 | FR-002 | 001 | T009, T010, T012–T015 | `test_generar_tabla.py`, `test_command_table.py` (reglas) |
| FR-003 | FR-003 | 001–003 | T007, T008, T019–T021, T033 | `test_command_policy.py`, `test_tools_generic_commands.py` |
| FR-004 | FR-003, FR-006, FR-007, FR-010 | 001–004 | T007, T008, T019, T033, T034 | ídem |
| FR-005 | FR-004 | 001 | T011, T013 | `test_command_table.py` (verbos) |
| FR-006 | FR-005 | 007 | T003, T004, T011 | `test_command_inventory.py`, `test_command_table.py` (deriva) |
| FR-007 | FR-005 | 007 | T009, T010, T038–T040 | `test_generar_tabla.py`, `test_extractor_inventario.py` |
| FR-008 | FR-006 | 002 | T019, T024, T027 | `test_tools_generic_commands.py`, banco |
| FR-009 | FR-006 | 002 | T020, T024, T027 | ídem |
| FR-010 | FR-006 | 002 | T018, T020, T023 | `test_command_policy.py` (resumen), genéricas |
| FR-011 | FR-007 | 003 | T021, T024 | genéricas (Supervisor) |
| FR-012 | FR-007 | 003 | T007, T008, T021 | `test_command_policy.py` (rutas), genéricas |
| FR-013 | FR-006 | 002 | T019, T024 | genéricas |
| FR-014 | FR-008 | 002, 003 | T019, T021, T024 | genéricas |
| FR-015 | FR-008 | 002, 003 | T020, T021, T024 | genéricas (log capturado) |
| FR-016 | FR-009 | 002 | T019, T024 | genéricas (`one_shot`) |
| FR-017 | casos límite | 002, 003 | T019–T021, T024 | genéricas |
| FR-018 | FR-006, FR-007, FR-018 | 002, 003 | T011, T022, T025 | `test_tools_registration.py`, `test_command_table.py` (marcas) |
| FR-019 | FR-010 | 004 | T005, T006 | `test_tool_families.py` |
| FR-020 | FR-010 | 004 | T030–T032, T034 | `test_config_validation.py`, `test_run_sh_options.py`, `test_addon_manifest.py`, `test_tools_registration.py` |
| FR-021 | FR-010, FR-020 | 004 | T022, T025, T032, T034 | `test_tools_registration.py` (SC-005) |
| FR-022 | FR-011 | 008 | T026, T035–T037 | `test_tools_guide.py` |
| FR-023 | FR-012 | 001 | T011, T015 | `test_command_table.py` (dedicadas) |
| FR-024 | plan 008 (E-1…E-4) | — | T002 | revisión del diff (documental) |
| FR-025 | FR-019 | 002, 003 | T020, T021 | genéricas (centinelas) |
| FR-026 | FR-021, FR-023, FR-024 | — | T041 | revisión del diff (documental) |

## Tramos

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado. Los IDs están en [tasks.md](tasks.md).

| Tramo | Contenido | Tareas |
|---|---|---|
| 1 | Línea base, enmienda E-1…E-4, inventario normalizado, familias (catálogo), política (guardas puras), generador y tabla, tests de deriva, verbos y dedicadas | T001–T017 |
| 2 | Resumen de la carga, las cuatro genéricas, anotaciones, registro, `INSTRUCTIONS`, banco de Core | T018–T029 |
| 3 | Opción de familias, registro por familias y SC-005, guía y consulta, ejemplos, extractor, documentación | T030–T043 |

## Riesgos

- **Mala clasificación en vía T**: revisión uno a uno con el código de HA, test
  de verbos, `confirm` ante la duda y prueba en el banco (S-04).
- **Tabla grande en el diff** (877 líneas): una línea por entrada y orden
  alfabético; el tramo 1 lo revisa por grupos y lo anota en el commit.
- **Choque con otras sub-features** en `tools/__init__.py`, `_annotations.py`,
  `guide.py` y el CHANGELOG: se integra por olas (la 011 es la ola 1); las
  sub-features siguientes ya parten de la tabla y de las familias.
- **La 010 sin integrar** al empezar el tramo 2: T027 queda pendiente de la
  010 y se anota (S-01).
