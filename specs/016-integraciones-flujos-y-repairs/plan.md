# Plan de implementación: integraciones, flujos y Repairs (016)

**Rama**: `feat/016-integraciones-flujos-y-repairs` (no se crea ninguna) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md) | **Programa**: [008](../008-cobertura-total/plan.md), sub-feature 016, ola 2

## Resumen

Quince tools dedicadas nuevas en dos familias nuevas para administrar
integraciones más allá de instalarlas: lo que HA ha descubierto (listar,
ignorar), los dominios que se configuran por flujo, el título y las
preferencias de una entrada, las subentries (listar, crear y reconfigurar por
su flujo, renombrar, borrar) y el reconfigure de la entrada
(`integration_flows`); y los flujos de reparación de Repairs (ver el aviso con
sus datos, abrir el flujo, enviar cada paso con vista previa y token, abortar)
(`repair_flows`). Además, `ha_list_repairs` y `ha_ignore_repair` devuelven el
título y la descripción traducidos de los avisos (CAP-036) y la guía explica los
helpers por config entry (CAP-037). Siete comandos de la tabla de la 011 pasan
de `deny` «pendiente» a `dedicated`. Todo se prueba en unitarios y en el banco
de Core con una integración de prueba propia. Tres tramos, los de la 008: A
(descubiertas, preferencias y guía de helpers, con la base común), B
(subentries y reconfigure) y C (reparación y traducciones).

**Dependencia**: la rama sale de la 011 con su tramo 3 en curso. **La
implementación espera a que la 011 esté integrada** (genéricas, opción
`tool_families_disabled`, registro por familias y tabla revisada), junto con la
009 y la 010; T001 lo comprueba e integra (S-01 de la spec).

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x, aiohttp, structlog (sin dependencias nuevas) · **Almacenamiento**: solo los ficheros de token de `/data/pending_confirmations` (como hoy; sin argumentos guardados) · **Tests**: pytest con `unittest.IsolatedAsyncioTestCase`, `AsyncMock` de `ws_send` y `_request_json`; banco de Core de la 010 con una integración de prueba en su `/config` · **Plataforma**: add-on de HA OS.

**Restricciones**: fail-closed (III); dos pasos con token atado a todos los argumentos (IV); anotaciones verdaderas y por nombre exacto donde el prefijo no basta (V); control negativo (VII); repositorio público (VIII); cambios mínimos (IX).

**Escala**: 15 tools (11 que modifican; 3 con token), 3 módulos de tools y 1 ayudante, 2 tools existentes que ganan campos y 1 docstring corregida, 7 entradas de la tabla, 2 familias, 2 temas de guía y 3 secciones de guía tocadas, 1 integración de prueba del banco.

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Lo que borra o degrada va con vista previa que describe el efecto real: la subentry con sus entidades y dispositivos, la recarga y la pérdida de sondeo, el paso de reparación con lo que se envía. Los flujos `external`/`progress` (OAuth) se abortan como hoy. Las lecturas pasan por el tope y la redacción. Ninguna tool nueva rodea la tabla ni la denylist. | OK |
| II. Secretos | `title_placeholders`, `translation_placeholders`, datos internos de avisos, `user_input`, textos traducidos y errores de HA pasan por `redact_structure` y `redact_secrets`; el token no guarda argumentos; el log solo lleva ids, dominios, tipos y recuentos; centinela por tool (FR-021). | OK |
| III. Fail-closed | Lecturas previas fallidas → `preview_unavailable` sin token; forma inesperada → error, nunca «vacío»; comprobaciones previas (`not_found`, `cannot_ignore`, `subentry_type_not_supported`, `reconfigure_not_supported`, `not_fixable`, `flow_mismatch`) sin la llamada que modifica; las entradas de la tabla solo pasan a `dedicated` con su tool. Excepción razonada: las traducciones son decorativas y su fallo no tumba `ha_list_repairs` (fallar cerrado ahí rompería una tool que ya funciona, FR-020 de la 008); se informa con `translations_unavailable`. | OK |
| IV. Dos pasos, token atado | `ha_delete_subentry` ata `entry_id` y `subentry_id`; `ha_update_config_entry` ata los cuatro argumentos y pide token al desactivar el sondeo o las entidades nuevas; `ha_continue_repair_fix` ata `domain`, `issue_id`, `flow_id` y `user_input`, en **cada** paso porque HA no dice cuál aplica el arreglo. Sin omitibles. Abrir flujos, ignorar un descubrimiento y renombrar o reconfigurar van sin token, como dice la 008 y como los flujos de la 1.1.2 (D-2, D-3). | OK |
| V. Nombre y descripción | `ha_list_config_flow_domains` en lugar de reutilizar un nombre que ya mintió; la docstring de `ha_list_configured_domains` deja de afirmar algo falso; destructivas y no idempotentes por nombre exacto; las respuestas dicen lo que no se sabe (relación aviso–flujo, `finished_on_start`, `issue_still_present: null`). | OK |
| VI. Lo que no se puede probar | Las once que modifican, en el banco contra HA 2026.11.1 real con una integración de prueba; lo que el banco no pueda queda en unitarios y en la matriz de la 014 como pendiente manual (S-04). | OK |
| VII. Control negativo | Uno por comportamiento con riesgo, enumerados en T016, T029 y T044 y anotados en el commit de cada tramo. | OK |
| VIII. Privacidad | Fixtures con `<entry_id>`, `banco_flujos`, `light.salon`, centinelas; la integración de prueba sin datos de nadie; revisión del diff en cada cierre de tramo. | OK |
| IX. Cambios mínimos | Solo las cinco CAP; `ha_abort_subentry_flow` se añade porque sin él un flujo queda huérfano (research R-4); las tools existentes no cambian de esquema ni de hints; lo que falta y no es de estas CAP, a dudas (D-1…D-7). | OK |
| X. Comentarios en español | Comentarios y eventos del log como hoy; nombres, descripciones y textos al cliente en inglés. | OK |
| XI. Versionado | Sin subir versión (la 1.2.0 la fija la 009); sección propia en `## [1.2.0]` del CHANGELOG. | OK |
| Flujo, puerta 4 | Suite y banco en verde en el CI al cerrar cada tramo. | OK |

Tras el diseño: sin cambios. Desviación justificada: la del principio III
sobre las traducciones (fila III).

## Diseño

### Tramo A — descubiertas, preferencias y guía de helpers (CAP-044, CAP-037)

1. **Familia** `integration_flows` en `tool_families.py` con
   `("integration_setup",)` (el tramo B añade `config_subentries`).
2. **`tools/integration_setup.py`** con las cuatro tools de data-model
   (research R-1…R-3): `register(mcp, ha_client, *, response_max_bytes)`;
   lecturas previas con `ws_send`; REST con `_request_json`; dos pasos de
   `ha_update_config_entry` con `create_confirmation_token`/
   `validate_confirmation_token`/`complete_confirmation_token`; redacción con un
   `_redactar` compartido (si hay dos usos, se mueve el de `repairs.py` a
   `_common.py` sin cambiar su comportamiento); sobre con
   `ajustar_lista_a_bytes`.
3. **Registro** en `tools/__init__.py` dentro de `if _activa("integration_flows")`;
   **anotaciones**: `ha_update_config_entry` en `_DESTRUCTIVE_EXACT`.
   Docstring de `ha_list_configured_domains` corregida.
4. **Tabla**: `config_entries/flow/progress`, `config_entries/ignore_flow` y
   `config_entries/update` a `dedicated`; generador y test de vía D si la 012
   no lo hizo ya (research R-7); regenerar → `git diff` vacío.
5. **Guía**: tema `integration_flows` (parte A) con sus alias; sección
   «Helpers por config entry» en `helpers`; línea en `config_entries`.
6. **Banco**: integración de prueba `banco_flujos` completa (la usan los tres
   tramos; research R-9) y `banco_flujos:` en la configuración;
   `tests/banco/test_banco_integraciones.py` (parte A);
   `tests/banco/cobertura_016.py`; enganche al invariante (S-02).
7. **Documentación parcial**: sección «Integraciones: flujos y Repairs
   (spec 016)» en `## [1.2.0]`; fila 016 de la hoja de ruta «en curso
   (tramo A)».

### Tramo B — subentries y reconfigure (CAP-045)

1. **`tools/config_subentries.py`**: siete tools (research R-4); reutiliza
   `_NON_AUTOMATABLE_TYPES`, la validación de `flow_id` y el abort best-effort
   de `config_entry_flows.py` (importándolos o moviendo lo compartido a un
   ayudante sin cambiar su comportamiento ni sus tests).
2. **Familia** con los dos módulos; registro; anotaciones
   (`_NON_IDEMPOTENT_EXACT` para `ha_start_subentry_flow`,
   `ha_continue_subentry_flow` y `ha_start_reconfigure_flow`).
3. **Tabla**: `config_entries/subentries/list|update|delete`; generador;
   regenerar idéntico.
4. **Guía**: tema `integration_flows` completo.
5. **Banco**: parte B de `test_banco_integraciones.py`; las siete a
   `PROBADAS_016` (las que modifican).
6. **Documentación parcial** y revisión del principio V.

### Tramo C — reparación y traducciones (CAP-048, CAP-036)

1. **`tools/_translations.py`** (research R-6): idioma de HA, lectura de
   `frontend/get_translations` para varios dominios en una llamada,
   sustitución de marcadores, recorte, y forma fail-soft.
2. **`tools/repairs.py`**: `ha_list_repairs` y `ha_ignore_repair` con textos
   (sin argumentos nuevos); docstring del módulo al día.
3. **`tools/repair_flows.py`**: cuatro tools (research R-5).
4. **Familia** `repair_flows`; registro; anotaciones
   (`ha_continue_repair_fix` en `_DESTRUCTIVE_EXACT` y `_NON_IDEMPOTENT_EXACT`;
   `ha_start_repair_fix` en `_NON_IDEMPOTENT_EXACT`).
5. **Tabla**: `repairs/get_issue_data` a `dedicated` y comentario en
   `frontend/get_translations`; generador; regenerar idéntico.
6. **Guía**: tema `repair_flows`; línea en `diagnostics`.
7. **Banco**: `tests/banco/test_banco_repairs.py`; las tres que modifican a
   `PROBADAS_016`.
8. **Documentación final**: CHANGELOG completo, hoja de ruta «hecha», README y
   README.es, DOCS (familias, si la opción las enumera), matriz de la 008 (filas
   CAP-036, CAP-037, CAP-044, CAP-045, CAP-048).

## Estructura de ficheros

```text
hermes/src/hermes/
├── tool_families.py             # + integration_flows (A, B), repair_flows (C)
├── command_table.py             # 7 entradas a dedicated (A: 3, B: 3, C: 1) + comentario (C)
└── tools/
    ├── __init__.py              # registro bajo las familias (A, B, C)
    ├── _annotations.py          # nombres exactos (A, B, C)
    ├── _common.py               # solo si se comparte un helper existente
    ├── _translations.py         # nuevo (C)
    ├── guide.py                 # temas integration_flows (A, B) y repair_flows (C); helpers (A)
    ├── config_entry_flows.py    # docstring de ha_list_configured_domains (A); compartir helpers de flujo (B) sin cambiar comportamiento
    ├── repairs.py               # textos traducidos (C)
    ├── integration_setup.py     # nuevo (A)
    ├── config_subentries.py     # nuevo (B)
    └── repair_flows.py          # nuevo (C)
scripts/inventario/generar_tabla.py   # _DEDICADAS_INICIALES y clase A (A, B, C)
tests/
├── test_tools_integration_setup.py   # nuevo (A)
├── test_tools_config_subentries.py   # nuevo (B)
├── test_translations.py              # nuevo (C)
├── test_tools_repairs.py             # textos (C)
├── test_tools_repair_flows.py        # nuevo (C)
├── test_tool_families.py             # familias (A, B, C)
├── test_tools_registration.py        # hints de las nuevas (A, B, C)
├── test_command_table.py             # vía D admite dedicated (A, si la 012 no lo hizo)
├── test_generar_tabla.py             # fila A en el mapa (A, ídem)
├── test_tools_guide.py               # temas y cobertura de tools (A, B, C)
├── test_tools_generic_commands.py    # rechazo hacia la dedicada (A, B, C)
└── banco/
    ├── ha_config/configuration.yaml           # banco_flujos: (A)
    ├── ha_config/custom_components/banco_flujos/  # nueva (A)
    ├── cobertura_016.py                       # nuevo (A, B, C)
    ├── test_banco_integraciones.py            # nuevo (A, B)
    └── test_banco_repairs.py                  # nuevo (C)
hermes/CHANGELOG.md, docs/HOJA-DE-RUTA.md, README.md, README.es.md,
hermes/DOCS.md, specs/008-cobertura-total/plan.md
```

## Trazabilidad (FR de la 016 → FR/CAP de la 008 → tareas → test)

| FR 016 | FR 008 | CAP | Tareas | Test |
|---|---|---|---|---|
| FR-001 | FR-053 | CAP-044 | T004, T008, T013 | `test_tools_integration_setup.py`; banco |
| FR-002 | FR-053 | CAP-044 | T005, T008, T013 | `test_tools_integration_setup.py`; banco |
| FR-003 | FR-053 | CAP-044 | T006, T008, T009, T013 | `test_tools_integration_setup.py`, `test_tools_registration.py`; banco |
| FR-004 | FR-053 | CAP-044 | T007, T008, T013 | `test_tools_integration_setup.py`; banco |
| FR-005 | FR-054 | CAP-045 | T018, T023, T027 | `test_tools_config_subentries.py`; banco |
| FR-006 | FR-054 | CAP-045 | T019, T023, T027 | `test_tools_config_subentries.py`; banco |
| FR-007 | FR-054 | CAP-045 | T019, T023, T027 | `test_tools_config_subentries.py`; banco |
| FR-008 | FR-054 | CAP-045 | T020, T023, T027 | `test_tools_config_subentries.py`; banco |
| FR-009 | FR-054 | CAP-045 | T021, T023, T027 | `test_tools_config_subentries.py`; banco |
| FR-010 | FR-054 | CAP-045 | T022, T023, T027 | `test_tools_config_subentries.py`; banco |
| FR-011 | FR-055 | CAP-048 | T034, T038, T042 | `test_tools_repair_flows.py`; banco |
| FR-012 | FR-055 | CAP-048 | T035, T038, T042 | `test_tools_repair_flows.py`; banco |
| FR-013 | FR-055 | CAP-048 | T036, T038, T042 | `test_tools_repair_flows.py`; banco |
| FR-014 | FR-055 | CAP-048 | T037, T038, T042 | `test_tools_repair_flows.py`; banco |
| FR-015 | FR-056 | CAP-036 | T030–T036, T042 | `test_translations.py`, `test_tools_repairs.py`, `test_tools_repair_flows.py`; banco |
| FR-016 | FR-057 | CAP-037 | T011 | `test_tools_guide.py` |
| FR-017 | FR-010 | CAP-004 | T002, T003, T024, T039 | `test_tool_families.py`, `test_tools_registration.py` |
| FR-018 | FR-012 | CAP-001 | T010, T025, T040 | `test_command_table.py`, `test_generar_tabla.py`, `test_tools_generic_commands.py` |
| FR-019 | FR-018 | CAP-023 | T009, T024, T039 | `test_tools_registration.py` |
| FR-020 | FR-011 | CAP-008 | T011, T026, T041 | `test_tools_guide.py` |
| FR-021 | FR-019 | — | T004–T007, T018–T022, T030–T036 | centinelas en cada fichero de tests |
| FR-022 | FR-018 | CAP-023 | T004, T006, T018, T021, T032, T034 | sobre y tope en cada fichero de tests |
| FR-023 | FR-015 | CAP-034 | T012, T013, T027, T042 | `tests/banco/*`, invariante de escrituras |
| FR-024 | FR-020 | CAP-030 | T009, T024, T032, T039 | `test_tools_registration.py`, `test_tools_repairs.py` |
| FR-025 | FR-023 | — | T014, T028, T043 | revisión en el cierre (T045) |
| FR-026 | FR-021 | — | T017, T029, T045 | revisión del diff |

## Tramos

Cada tramo lo hace un agente nuevo: deja la suite local con exactamente los 6
fallos conocidos de Windows, el CI de la rama en verde y termina en su propio
commit (o varios) con los recuentos de los controles negativos.

- **Tramo A — descubiertas, preferencias y guía de helpers** (T001–T017):
  familia `integration_flows`, `integration_setup.py` (4 tools), registro y
  anotaciones, docstring de `ha_list_configured_domains`, 3 entradas de la
  tabla y generador, guía (tema parcial, helpers, `config_entries`),
  integración de prueba del banco y su parte A, documentación parcial.
- **Tramo B — subentries y reconfigure** (T018–T029): `config_subentries.py`
  (7 tools), familia con dos módulos, 3 entradas de la tabla, guía completa del
  tema, banco B, documentación parcial.
- **Tramo C — reparación y traducciones** (T030–T045): `_translations.py`,
  textos en `repairs.py`, `repair_flows.py` (4 tools), familia `repair_flows`,
  1 entrada de la tabla y el comentario, tema `repair_flows`, banco C,
  documentación final y matriz de la 008.

Tamaño: A = 4 tools + base común + integración de prueba; B = 7 tools de un
mismo patrón; C = 4 tools + un ayudante + cambios en dos tools existentes. Si
el agente del tramo B ve que no le cabe, parte el tramo en B1 (T018, T019, T022,
T023 con las cuatro tools de flujo, y su parte de T024–T027) y B2 (lista,
renombrar y borrar), cada uno con su cierre.

## Riesgos

| Riesgo | Mitigación |
|---|---|
| La 011 (tramo 3), la 009 o la 010 no están en la rama al empezar | T001 las integra desde `feat/cobertura-total`; sin la 010, banco pendiente con nota (S-01) |
| Conflictos con la 012 en el generador, el test de vía D, `_annotations.py`, `guide.py`, `tool_families.py`, la tabla y el CHANGELOG | Cambios en bloques propios y comentados; el cambio del generador es el mismo diseño en las dos (research R-7) y lo hace la primera; se resuelve al integrar en orden de olas |
| El HA del banco no carga la integración de prueba o sus traducciones | Comprobado en T012 con un test de humo; si falla, camino feliz en unitarios y pendiente manual en la matriz de la 014 (S-04) |
| `GET` de un flujo repite el paso actual (research R-5) | Es lo que hace la interfaz; por convención de HA un paso sin datos solo enseña el formulario; se anota si el banco muestra otra cosa |
| La forma de los dispositivos por subentry en `config/device_registry/list` | La implementación acepta las dos formas de research R-4 y el banco lo comprueba |
| Coste de dos llamadas más en `ha_list_repairs` | Una sola de cada por respuesta, solo con los dominios de los avisos devueltos |
