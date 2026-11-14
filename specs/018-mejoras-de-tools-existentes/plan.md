# Plan de implementación: mejoras de tools existentes (018)

**Rama**: `feat/018-mejoras-de-tools-existentes` (sale de la 011 completa; se integra en `feat/cobertura-total`) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md) | **Paraguas**: [008](../008-cobertura-total/plan.md)

## Resumen

Tres mejoras sobre tools que ya existen, sin tools nuevas ni cambios en la
tabla de comandos:

1. **Guardado por vista** en `ha_save_lovelace_dashboard` (`view_index` y
   `view`, opcionales): el servidor sustituye una vista y conserva el resto;
   vista previa que dice qué vista cambia y qué se conserva; `view` omitible al
   confirmar; token atado también al estado del dashboard, con un argumento
   opcional nuevo `estado` en `create_confirmation_token` y
   `resolve_confirmation_token`.
2. **`ha_call_service_response` con `confirmation_token`** para la denylist y
   las entidades restringidas, con la vista previa de `ha_call_service`, de
   forma aditiva: la respuesta sin token conserva el `error` de la 1.1.2 y
   añade el token y la vista previa.
3. **Sobre común de listas**: constructor `sobre_de_lista` en
   `tools/_common.py`, usado por las genéricas; párrafo en el índice de la
   guía; test transversal por AST sobre las tools de lista nuevas.

Dos tramos, como fija la 008: (a) guardado por vistas; (b) denylist con token y
sobre común. Detalle en [research.md](research.md), entidades en
[data-model.md](data-model.md), contratos en
[contracts/tools.md](contracts/tools.md), validación en
[quickstart.md](quickstart.md).

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x, aiohttp, structlog, pydantic 2 (sin dependencias nuevas) · **Almacenamiento**: ficheros de token de `/data/pending_confirmations` (campo opcional nuevo `state_hash`; `stored_args` admite `view`) · **Tests**: pytest, `unittest.IsolatedAsyncioTestCase`, `DummyMCP`, `FakeWSSender` de `tests/test_tools_lovelace.py`, `AsyncMock` del cliente, `CONFIRMATIONS_DIR` en un temporal, `structlog.testing.capture_logs`; banco de Core de la 010 · **Plataforma**: add-on de Home Assistant OS.

**Restricciones**: nada de la 1.1.2 cambia sin los argumentos nuevos (FR-020 de la 008, instantáneas de esquemas y anotaciones); fail-closed (III); vista previa que no miente y token atado (IV); ningún contenido de vista ni respuesta de servicio en disco más allá de lo de la 1.1.2 ni en el log (II); control negativo por guarda (VII); repositorio público (VIII).

**Escala**: 0 tools nuevas, 0 familias, 0 entradas de tabla. Cambios en `security.py` (argumento opcional), `tools/lovelace.py`, `tools/ha.py`, `tools/_common.py`, `tools/generic_commands.py` (usa el constructor), `tools/guide.py`; tests en 5 ficheros existentes y 2 nuevos (`tests/test_sobre_de_lista.py`, `tests/banco/test_banco_mejoras.py`).

## Comprobación de la constitución

Contra la constitución 1.2.0 (con E-1…E-4).

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | El guardado por vista reduce el riesgo de borrar tarjetas por reconstruir mal un documento grande; la acción peligrosa con respuesta sigue exigiendo confirmación (la denylist no se relaja, se le añade la vía confirmada) (FR-001, FR-008). | OK |
| II. Secretos | `view` se guarda junto al token con las reglas de la 1.1.2 (tope, borrado al completar o caducar); la respuesta de una acción confirmada no se escribe en el token (`{"called": true}`); el log nuevo lleva solo `url_path`, `view_index`, dominio y servicio (FR-009, FR-018). | OK |
| III. Fail-closed | Mezclas de argumentos, índice fuera de rango, dashboard sin vistas o ilegible → error sin token; dashboard cambiado → `dashboard_changed` sin guardar; token sin `state_hash` resuelto con estado (o al revés) → rechazo; la respuesta sin token de `ha_call_service_response` sigue siendo un rechazo para un cliente de la 1.1.2 (FR-003, FR-005, FR-008). | OK |
| IV. Dos pasos, token atado | Guardado por vista siempre en dos pasos; token atado a tool, argumentos y estado del dashboard; vista previa que dice exactamente qué vista cambia y qué se conserva y que la confirmación se rechazará si algo cambia; `ha_call_service_response` atado a su propio nombre (un token de `ha_call_service` no vale) (FR-002, FR-003, FR-009). | OK |
| V. Nombre y descripción | Docstrings de las dos tools, guía (`lovelace`, `services`, índice) e `INSTRUCTIONS` cambian en el mismo commit que el comportamiento; las anotaciones (`-DI-`) ya eran verdad y no cambian; `SIN_TOKEN_A_PROPOSITO` queda vacío porque ya no hace falta la excepción (FR-007, FR-011, FR-016). | OK |
| VI. Lo que no se puede probar | Unitarios con el cliente simulado y banco con HA Core 2026.11.1 real para el guardado por vista y `conversation.process` (FR-017). | OK |
| VII. Control negativo | Una tarea de control negativo por tramo, con las guardas de [quickstart](quickstart.md#control-negativo-principio-vii) (SC-007). | OK |
| VIII. Privacidad | Fixtures con marcadores genéricos (`panel-prueba`, `light.salon`, textos ficticios); sin datos de la prueba en vivo (el «134 KB» es una cifra, no un dato de la instalación) (FR-021 de la 008). | OK |
| IX. Cambios mínimos | Sin tools nuevas; las dos tools ganan solo argumentos opcionales; `security.py` gana un argumento opcional; las listas de la 1.1.2 no se tocan; lo que no pide la 008 va a «Dudas para el final» (DF-1…DF-3) o a «Fuera de alcance» (guarda en `HAClient.call_service_response`). | OK |
| X. Comentarios en español | Comentarios y docstrings internos en español con el porqué; descripciones al cliente, códigos de error y eventos de log en inglés. | OK |
| XI. Versionado | Sin cambio de versión (la 1.2.0 la puso la 009); sección propia en `## [1.2.0]` del CHANGELOG. | OK |
| Flujo, puerta 4 | El banco de Core ejecuta los tests nuevos del banco al integrar la 010. | OK |

Tras el diseño: sin desviaciones.

## Diseño

### Tramo 1 — guardado por vistas (FR-001…FR-007, FR-016 parcial, FR-017 parcial, FR-018)

1. **`security.py`**: `create_confirmation_token(..., estado: Any = None)` y
   `resolve_confirmation_token(..., estado: Any = None)`. Con `estado`, el
   token guarda `state_hash = compute_action_hash("estado", {"estado": estado})`.
   Al resolver, tras leer el fichero y comprobar caducidad y estado pendiente,
   y **antes** de la comprobación del `action_hash`: si `state_hash` del token
   o `estado` está presente y las huellas no coinciden → `(False,
   ESTADO_CAMBIADO, {})` sin tocar el fichero. Constante pública
   `ESTADO_CAMBIADO` con un texto en inglés que diga que el objetivo cambió
   desde la vista previa. `validate_confirmation_token` no cambia.
2. **`tools/lovelace.py`**:
   - `_OMITIBLES_GUARDAR = ("config",)` no cambia; constante nueva
     `_OMITIBLES_VISTA = ("view",)` solo para el modo por vista (una tupla
     común rompería las confirmaciones completas: `resolve_confirmation_token`
     rechaza si falta un omitible que no se guardó; ver data-model).
   - `ha_save_lovelace_dashboard` gana `view_index: int | None = None` y
     `view: dict[str, Any] | None = None` **al final** de la firma (no cambia
     el orden de los existentes). Si llega cualquiera de los dos, se delega en
     un helper interno `_guardar_vista(...)` antes de tocar el flujo completo;
     sin ellos el código de la 1.1.2 no cambia.
   - `_guardar_vista`: validación (contrato), detección de YAML como hoy,
     lectura del actual (`config_not_found` → `no_views`; otro fallo →
     `preview_unavailable` en la vista previa o el error de conexión al
     confirmar), comprobación de `views` lista y rango, resumen
     (`_resumen_vista`, `_vistas_conservadas`), `create_confirmation_token(...,
     omitibles=_OMITIBLES_VISTA, estado=actual)`; al confirmar,
     `resolve_confirmation_token(..., estado=actual)` → con
     `ESTADO_CAMBIADO`, `{"error": "dashboard_changed", "url_path", "view_index",
     "detail"}`; con ok, documento resultante, `_validate_dashboard_config`,
     `lovelace/config/save`, `complete_confirmation_token`.
   - Docstrings de `ha_save_lovelace_dashboard` y `ha_get_lovelace_dashboard`
     y la `hint` de `too_large` mencionan el guardado por vista.
   - Log: `ha_save_lovelace_dashboard_view_ok` / `_view_failed` con
     `url_path` y `view_index`.
3. **`tools/guide.py`**: tema `lovelace` (guardar una vista, conservación,
   `dashboard_changed`) y la trampa de `INSTRUCTIONS` («REEMPLAZA el
   dashboard entero» → «o solo una vista con `view_index`»).
4. **Tests** (antes del código): `TestGuardarPorVista` en
   `tests/test_tools_lovelace.py`; `TestTokenAtadoAlEstado` en
   `tests/test_security.py`; instantánea de esquemas con la diferencia de
   `ha_save_lovelace_dashboard`; guía; banco (parte Lovelace de
   `tests/banco/test_banco_mejoras.py`).
5. **CHANGELOG**: sección `### Mejoras de tools existentes` en `## [1.2.0]`
   con la entrada del guardado por vista; `SECURITY.md` (los documentos
   guardados junto al token incluyen `view`).

### Tramo 2 — denylist con token y sobre común (FR-008…FR-015, FR-016…FR-019 resto)

1. **`tools/ha.py`**: `ha_call_service_response(..., confirmation_token: str |
   None = None)`. Orden: sanitización → `in_denylist` y `entity_is_restricted`
   (mismas funciones que `ha_call_service`) → si hace falta token: sin token,
   `create_confirmation_token("ha_call_service_response", args, preview)` y se
   devuelve `{"error": <código 1.1.2>, "hint": <nueva>, **token}`; con token,
   `validate_confirmation_token`, `call_service_response`,
   `complete_confirmation_token(result={"called": True})` y la respuesta; un
   fallo de HA → `ha_call_service_response_failed` como hoy y token `failed`.
   La construcción de la vista previa se comparte con `ha_call_service` con un
   helper interno (`_vista_previa_servicio(accion, ...)`) para que no
   diverjan; el `action` de `ha_call_service` sigue siendo `call_service`.
   Docstring nuevo (acepta token para la denylist; la denylist no se relaja).
2. **`tools/_common.py`**: `sobre_de_lista(items, *, truncated=False,
   **cabecera)`; rechaza (`ValueError`, error de programación) una cabecera con
   `count`, `items` o `truncated`. **`tools/generic_commands.py`**:
   `_respuesta` lo usa.
3. **`tools/guide.py`**: párrafo «Listas» en `_OVERVIEW`; tema `services`
   (`ha_call_service_response` con token para la denylist); `INSTRUCTIONS` si
   lo menciona (hoy no).
4. **Tests** (antes del código): `TestCallServiceResponseConfirmacion` en
   `tests/test_call_service_security.py`; `tests/test_sobre_de_lista.py`
   (constructor, recorte central, transversal AST con su control sintético);
   instantánea de esquemas con la diferencia de `ha_call_service_response`;
   `SIN_TOKEN_A_PROPOSITO` vacío; guía; banco (parte `conversation.process`).
5. **Documentación**: CHANGELOG (entradas de US2 y US3 en la sección del
   tramo 1); `docs/HOJA-DE-RUTA.md` (018 hecha, salvo el banco hasta integrar
   la 010; problema 21 «Parcial»); `SECURITY.md` (denylist con respuesta
   confirmada); matriz de la 008 (CAP-019, CAP-020, CAP-023 con tests
   definitivos).

## Estructura de ficheros

```text
specs/018-mejoras-de-tools-existentes/
├── spec.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md
├── contracts/tools.md
└── checklists/requirements.md

hermes/src/hermes/
├── security.py                  # estado opcional en crear/resolver (T1)
└── tools/
    ├── lovelace.py              # guardado por vista (T1)
    ├── ha.py                    # ha_call_service_response con token (T2)
    ├── _common.py               # sobre_de_lista (T2)
    ├── generic_commands.py      # usa sobre_de_lista (T2)
    └── guide.py                 # lovelace, INSTRUCTIONS (T1); índice, services (T2)

tests/
├── test_security.py             # TestTokenAtadoAlEstado (T1)
├── test_tools_lovelace.py       # TestGuardarPorVista (T1)
├── test_call_service_security.py# TestCallServiceResponseConfirmacion (T2)
├── test_sobre_de_lista.py       # nuevo (T2)
├── test_tools_registration.py   # diferencias permitidas; SIN_TOKEN_A_PROPOSITO (T1, T2)
├── test_tools_guide.py          # textos de la guía (T1, T2)
└── banco/test_banco_mejoras.py  # nuevo, marca banco (T1 Lovelace, T2 conversación)

hermes/CHANGELOG.md, SECURITY.md, docs/HOJA-DE-RUTA.md,
specs/008-cobertura-total/plan.md (matriz)
```

README, README.es y DOCS no cambian: no hay opciones nuevas y no listan los
argumentos de estas tools.

## Trazabilidad (FR de la 018 → FR/CAP de la 008 → tareas)

| FR 018 | FR 008 | CAP | Tareas |
|---|---|---|---|
| FR-001 | FR-063 | CAP-019 | T004, T008 |
| FR-002 | FR-063, FR-018 | CAP-019 | T004, T008 |
| FR-003 | FR-063, FR-020 | CAP-019 | T003, T005, T007, T008 |
| FR-004 | FR-063 | CAP-019 | T004, T008 |
| FR-005 | FR-063 | CAP-019 | T004, T008 |
| FR-006 | FR-020 | CAP-019 | T004, T008 |
| FR-007 | FR-018 | CAP-019 | T006, T009 |
| FR-008 | FR-064, FR-020 | CAP-020 | T014, T017 |
| FR-009 | FR-064, FR-019 | CAP-020 | T014, T017 |
| FR-010 | FR-020 | CAP-020 | T014, T017 |
| FR-011 | FR-018, FR-023 | CAP-020 | T016, T021, T024 |
| FR-012 | FR-018, FR-065 | CAP-023 | T015, T018 |
| FR-013 | FR-065 | CAP-023 | T016, T021 |
| FR-014 | FR-065 | CAP-023 | T015, T019 |
| FR-015 | FR-020 | CAP-023 | T015, T019 |
| FR-016 | FR-020 | CAP-019, CAP-020 | T006, T020 |
| FR-017 | FR-015 | CAP-019, CAP-020 | T010, T022 |
| FR-018 | FR-019 | CAP-019 | T004, T008 |
| FR-019 | FR-023, FR-098 | CAP-019, CAP-020, CAP-023 | T012, T024, T025 |

## Tramos

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **1** — guardado por vistas | T001–T013 | `estado` en el módulo de confirmaciones; `ha_save_lovelace_dashboard` con `view_index`/`view`; guía e `INSTRUCTIONS`; instantánea con la diferencia permitida; test de banco escrito (se salta hasta integrar la 010); CHANGELOG y SECURITY de la parte |
| **2** — denylist con token y sobre común | T014–T026 | `ha_call_service_response` con token; `sobre_de_lista` y test transversal; guía; instantánea y `SIN_TOKEN_A_PROPOSITO`; banco de `conversation.process`; CHANGELOG, HOJA-DE-RUTA, SECURITY y matriz de la 008 |

El tramo 2 necesita el 1 integrado solo por la sección del CHANGELOG y por la
instantánea de esquemas (los dos editan el mismo test); el código no depende.

## Riesgos

- **Sub-features con tools de lista implementadas antes de integrar la 018**:
  el test transversal las señalará al integrar; el mensaje dice qué
  constructor usar (research R-4).
- **Conflictos en `tests/test_tools_registration.py`** con otras sub-features
  que añadan diferencias permitidas a la instantánea: cada una añade su
  entrada; se resuelven a mano al integrar.
- **`INSTRUCTIONS` y temas de la guía editados por varias sub-features**:
  cambios de una o dos líneas, localizados.
- **Banco no integrado en esta rama**: el test del banco se valida al
  integrar la 010 (como la T027 de la 011); hasta entonces se salta con su
  motivo, y la matriz lo dice.
