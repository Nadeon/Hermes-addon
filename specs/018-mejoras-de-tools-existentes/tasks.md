---

description: "Tareas de la sub-feature 018 — mejoras de tools existentes (Hermes 1.2.0)"
---

# Tareas: mejoras de tools existentes (018)

**Entrada**: `specs/018-mejoras-de-tools-existentes/` (spec.md, plan.md,
research.md, data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `CONFIRMATIONS_DIR` en
un `tempfile.TemporaryDirectory`, `DummyMCP` y `FakeWSSender` de
`tests/test_tools_lovelace.py`, `_make_ha_client`/`_register_ha_tools` de
`tests/test_call_service_security.py`, `structlog.testing.capture_logs`. Datos
ficticios (`panel-prueba`, `light.salon`, títulos de vista inventados,
centinelas de texto). Nada de la instalación real.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`.
Línea base en Windows antes de empezar (2026-11-14, punta `7870e5b`, la 011
completa): 2139 passed, 17 skipped, 6 failed (los 6 conocidos de Windows:
finales de línea, byte nulo y symlinks). Cada tramo termina con exactamente
esos 6 fallos en local; la referencia es el CI de Linux.

**Restricción del programa**: ningún test existente se modifica salvo los que
enumeran diferencias permitidas (`test_schemas_did_not_change` y
`SIN_TOKEN_A_PROPOSITO`) y los de textos de la guía que citen lo que cambia.
Si otro test existente cae, el cambio rompe la 1.1.2: se corrige el código, no
el test.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 guardado por vista, US2 denylist con respuesta
confirmada, US3 sobre común de listas.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado.

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **1** — guardado por vistas | **T001–T013** | `estado` opcional en el módulo de confirmaciones; `ha_save_lovelace_dashboard` con `view_index` y `view`; guía e `INSTRUCTIONS`; instantánea con su diferencia permitida; test de banco escrito; sección del CHANGELOG y `SECURITY.md` de la parte |
| **2** — denylist con token y sobre común | **T014–T026** | `ha_call_service_response` con `confirmation_token`; `sobre_de_lista` y test transversal; guía; instantánea y `SIN_TOKEN_A_PROPOSITO` vacío; banco de `conversation.process`; CHANGELOG, hoja de ruta, `SECURITY.md` y matriz de la 008 |

El tramo 2 va tras el 1 (comparten la sección del CHANGELOG y el test de la
instantánea de esquemas).

---

## Tramo 1 — guardado por vistas (US1)

### Preparación

- [x] T001 Línea base: suite completa sobre la punta de la rama; anotar el recuento en el mensaje del commit del tramo
- [x] T002 [US1] En `tests/test_tools_lovelace.py`, un generador de dashboard ficticio de tres vistas (`Inicio` sin `path`, `Cocina` con `path` y tarjetas, `Jardín` con `sections`) con claves de nivel superior `title` y `background`, y un `FakeWSSender` que guarde cada `lovelace/config/save` recibido y permita cambiar el documento devuelto entre llamadas. Sin cambiar los tests existentes

### Tests primero

- [x] T003 [P] [US1] `TestTokenAtadoAlEstado` en `tests/test_security.py` (FR-003, data-model «Estado ligado al token»): (a) sin `estado` en crear ni resolver → igual que hoy (mismo `action_hash`, sin `state_hash` en el fichero); (b) mismo estado → válido y `executing`; (c) estado distinto → `(False, ESTADO_CAMBIADO, {})` y el fichero sigue `pending` (se puede resolver después con el estado bueno); (d) token con `state_hash` resuelto sin `estado` → rechazo; (e) token sin `state_hash` resuelto con `estado` → rechazo; (f) dos estados iguales con claves en otro orden → misma huella; (g) `create_confirmation_token` con `estado` no añade nada a `confirm_with` ni a `omit_on_confirm`; (h) el fichero del token no contiene el estado, solo su huella (centinela en el estado)
- [x] T004 [P] [US1] `TestGuardarPorVista` en `tests/test_tools_lovelace.py` (FR-001…FR-006, FR-018): vista previa de la vista 1 → `mode`, `view_index`, `views_total`, `view_before`/`view_after` con recuentos, `view_unchanged`, `views_kept` 0 y 2 con título y ruta, `top_level_keys_kept` `["background", "title"]`, `diff`, `warning`, `confirm_with == ["confirmation_token", "url_path", "view_index"]`, `omit_on_confirm == ["view"]` y ningún `lovelace/config/save`; confirmar sin `view` → un `save` con el documento actual y solo la vista 1 cambiada (vistas 0 y 2 y claves superiores iguales por igualdad de objetos) y respuesta `{"result": "ok", "url_path", "view_index": 1}`; confirmar reenviando `view` idéntica → igual; reenviando otra → «does not match» sin `save`; documento cambiado entre los dos pasos (otra vista o una clave superior) → `dashboard_changed` sin `save`; vista idéntica a la actual → `view_unchanged: true`; errores sin token ni `save`: `config` + `view_index`, `remove_top_level_keys` + `view_index`, `view` sin `view_index`, `view_index` sin `view` en la vista previa, `view` no objeto, `view` con `views`, `view_index` `True` (`invalid_argument`), `-1` y `3` (`view_index_out_of_range` con `views_count`), `config_not_found` → `no_views`, documento de estrategia → `no_views`, modo YAML → `yaml_mode`, lectura fallida → `preview_unavailable`; al confirmar, lectura fallida → error de conexión y token aún pendiente; token de guardado completo usado por vista (y al revés) → rechazo sin `save`; tope de guardados lleno → `confirm_with` incluye `view`; el log capturado del guardado por vista no contiene un centinela puesto en la vista. Y una llamada sin los argumentos nuevos produce exactamente la misma vista previa (salvo el token) que antes del cambio
- [x] T005 [US1] Implementar `estado` en `create_confirmation_token` y `resolve_confirmation_token` y la constante `ESTADO_CAMBIADO` en `hermes/src/hermes/security.py` (research R-2; comentario con el porqué: la vista previa promete conservar algo que puede cambiar en 60 s). T003 en verde
- [x] T006 [P] [US1] Tests de instantánea y guía: en `tests/test_tools_registration.py::test_schemas_did_not_change`, añadir la diferencia permitida `ha_save_lovelace_dashboard` + `view_index` + `view` (opcionales; `required` igual), con comentario que cite FR-016 de la 018; un test nuevo en `TestArgumentosCambiadosAnteLaValidacionDelSdk`: `view` mandado como texto JSON llega como dict y omitido llega `None`, como `config`; en `tests/test_tools_guide.py`, el tema `lovelace` menciona `view_index` y `dashboard_changed`, e `INSTRUCTIONS` menciona el guardado de una sola vista (FR-007, FR-016)
- [x] T007 [US1] Control negativo de T005: quitar la comprobación de `state_hash` → caen (c), (d) y (e) de T003; quitar el guardado de `state_hash` → cae (b) o (d). Anotar recuentos para el commit. Restaurar y comprobar verde

### Implementación

- [x] T008 [US1] Guardado por vista en `hermes/src/hermes/tools/lovelace.py` según plan (Tramo 1, punto 2), data-model y contrato: firma con `view_index` y `view` al final; `_OMITIBLES_GUARDAR` sin cambios y `_OMITIBLES_VISTA = ("view",)` solo en el modo por vista; `_guardar_vista` con validación, lectura, resumen de vista (`_resumen_vista`, títulos y rutas recortados a 80 caracteres), vistas conservadas, token con `estado`, `dashboard_changed`, documento resultante validado, guardado y log sin contenido. El flujo completo de la 1.1.2 no cambia. T004 y T006 (parte de esquemas) en verde
- [x] T009 [US1] Docstrings de `ha_save_lovelace_dashboard` y `ha_get_lovelace_dashboard` (incluida la `hint` de `too_large`: «o guarda solo la vista con `view_index`»), tema `lovelace` de `hermes/src/hermes/tools/guide.py` y la trampa de Lovelace de `INSTRUCTIONS` (FR-007). T006 (parte de guía) en verde
- [x] T010 [P] [US1] Banco, parte Lovelace (FR-017, research R-5): `tests/banco/test_banco_mejoras.py` con `pytestmark = pytest.mark.banco` y el mismo `importorskip("tests.banco.base_helpers", reason=…)` que `tests/banco/test_banco_genericas.py`; docstring que diga que al integrar la 010 hacen falta `lovelace:` y `conversation:` en `tests/banco/ha_config/configuration.yaml`. Ciclo: crear dashboard de prueba con nombre aleatorio, guardar tres vistas y `title` (dos pasos), guardar la vista 1 por vista (dos pasos, sin reenviar `view`), leer con el lector `lovelace/config` directo a Core (añadir al lector un método público para un comando arbitrario si no lo tiene, al integrar) y comprobar vista 1 nueva y lo demás igual; vista previa por vista + guardado completo de otro documento + confirmación → `dashboard_changed` y el lector ve el guardado completo; borrar el dashboard en un `finally`
- [x] T011 [US1] Control negativo de T008: (a) fusionar sustituyendo `views` entera por `[view]` → caen las comprobaciones de vistas conservadas; (b) no pasar `estado` al resolver → cae `dashboard_changed`; (c) aceptar `config` junto a `view_index` → cae su caso; (d) sacar `view` de los omitibles → caen `omit_on_confirm` y la confirmación sin `view`; (e) usar una sola tupla `("config", "view")` para los dos modos → caen los tests existentes de `TestConfirmarSoloConTokenLovelace` (confirmación completa sin `config`). Anotar recuentos. Restaurar y comprobar verde
- [x] T012 [US1] Documentación (FR-019): en `hermes/CHANGELOG.md`, sección nueva `### Mejoras de tools existentes` dentro de `## [1.2.0] — <fecha de publicación>` (tras `### Sistema`) con la entrada del guardado por vista (qué hace, que conserva el resto, `dashboard_changed`, `view` omitible al confirmar); en `SECURITY.md`, el párrafo de documentos guardados junto al token incluye la vista de `ha_save_lovelace_dashboard` y el token atado al estado del dashboard
- [x] T013 Cierre del tramo 1: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII), commit con los recuentos de T007 y T011

### Notas del tramo 1 (cierre)

- **Línea base** (T001, punta tras traer `feat/cobertura-total`, con la 009,
  la 010, la 011 y la 028): 2320 passed, 65 skipped, 6 failed (los 6 de
  Windows). Al cerrar: 2356 passed, 66 skipped (el banco), los mismos 6.
- **Desviación (orden de la comprobación del estado)**: el data-model ponía la
  comprobación de `state_hash` antes que la del `action_hash`; va justo
  después (y antes de `executing`, sin `await` entre medias). Así un token del
  otro modo (completo frente a por vista) da «does not match», como dicen los
  casos límite de la spec, en vez de un `dashboard_changed` engañoso. Las
  cuatro filas de la tabla del data-model se cumplen igual.
- **Desviación (nombres integrados)**: el test de la instantánea se llama
  `test_esquemas_de_la_1_1_2` (no `test_schemas_did_not_change`). El banco ya
  está integrado: `tests/banco/test_banco_mejoras.py` usa `BancoEscrituras` y
  el lector de la 028 (`lector.comando`) en vez del `importorskip` del plan, y
  no hace falta tocar `ha_config` (`frontend:` ya carga Lovelace). El «otro
  cliente» que cambia el dashboard entre los dos pasos es el lector.
- **Controles negativos** (T007, T011): recuentos en el mensaje del commit y
  en los docstrings de `TestTokenAtadoAlEstado` y `TestGuardarPorVista`.

---

## Tramo 2 — denylist con token (US2) y sobre común (US3)

### Tests primero

- [ ] T014 [P] [US2] `TestCallServiceResponseConfirmacion` en `tests/test_call_service_security.py` (FR-008…FR-010): `conversation.process` sin token → `error == "service_in_denylist"`, `hint` que menciona `confirmation_token`, `confirmation_token`, `expires_in_seconds`, `preview` con `action == "call_service_response"` y los mismos `domain`, `service`, `service_data` y `reason` que daría `ha_call_service`, y `call_service_response` no llamado; confirmar con los mismos argumentos → llamado una vez y se devuelve su valor tal cual; segunda confirmación → «already used» sin llamar; otro `service_data` → rechazo sin llamar; token de `ha_call_service` usado aquí y token de aquí usado en `ha_call_service` → rechazo sin llamar; entidad restringida → `error == "entity_restricted"` + token + `restricted_entities`, y confirmado → llamado; servicio fuera de denylist con un token cualquiera → llamado a la primera; `service_data` inseguro → `unsafe_service_data` sin token; fallo de HA al confirmar → `ha_call_service_response_failed` y el token queda `failed`; el fichero del token tras confirmar no contiene un centinela puesto en la respuesta simulada (`cached_result == {"called": true}`). Los tests existentes `test_denylist_service_rejected_in_response_tool` y el de `entity_restricted` siguen sin cambios y en verde
- [ ] T015 [P] [US3] `tests/test_sobre_de_lista.py`, parte del constructor (FR-012, FR-015): `sobre_de_lista([a, b])` → `{"count": 2, "items": [a, b], "truncated": False}`; con cabecera y `truncated=True`; cabecera con `count`, `items` o `truncated` → `ValueError`; un sobre mayor que el tope pasado por `recortar_a_bytes` → `truncated: true`, `count == len(items)` y `_response_limit`; las genéricas devuelven lo mismo que antes del cambio (comparar con la forma de `contracts/tools.md` de la 011 para una lista)
- [ ] T016 [P] [US2] [US3] Tests de guía en `tests/test_tools_guide.py` (FR-011, FR-013): el índice (`hermes_guide()`) describe `count`, `items` y `truncated` y dice que las tools anteriores a la 1.2.0 conservan su forma; el tema `services` dice que `ha_call_service_response` acepta `confirmation_token` para la denylist; ningún texto de la guía ni de `INSTRUCTIONS` dice ya que `ha_call_service_response` «no admite» la denylist

### Implementación

- [ ] T017 [US2] `ha_call_service_response` con `confirmation_token` en `hermes/src/hermes/tools/ha.py` según plan (Tramo 2, punto 1) y contrato; helper de vista previa compartido con `ha_call_service` sin cambiar la de esta (sus tests existentes siguen verdes); docstring nuevo. T014 en verde
- [ ] T018 [US3] `sobre_de_lista` en `hermes/src/hermes/tools/_common.py` y `_respuesta` de `hermes/src/hermes/tools/generic_commands.py` usándolo. T015 y los tests de la 011 en verde
- [ ] T019 [US3] Test transversal en `tests/test_sobre_de_lista.py` (FR-014, research R-4): una función `incumplen(fuentes, nuevas)` que, por AST de los módulos de `hermes/src/hermes/tools/`, devuelve las tools de `nuevas` con nombre `ha_list_*` o `sv_list_*` cuya función no llama a `sobre_de_lista`; el test aplica `nuevas = registro real − tests/fixtures/esquemas_1_1_2.json − EXCEPCIONES_SOBRE` y exige `[]`, con un mensaje que nombra el constructor; otro test exige que cada clave de `EXCEPCIONES_SOBRE` sea una tool registrada y nueva. Control negativo dentro del propio fichero: una fuente sintética con `@mcp.tool()` `ha_list_algo` que devuelve una lista suelta → `incumplen` la señala; con `return sobre_de_lista(...)` → no
- [ ] T020 [US2] En `tests/test_tools_registration.py`: añadir la diferencia permitida `ha_call_service_response` + `confirmation_token` a `test_schemas_did_not_change`, y vaciar `SIN_TOKEN_A_PROPOSITO` cambiando su comentario (ya acepta token; la excepción deja de hacer falta) (FR-016)
- [ ] T021 [US2] [US3] Guía en `hermes/src/hermes/tools/guide.py`: párrafo «Listas» en `_OVERVIEW` y línea de `ha_call_service_response` en el tema `services` (FR-011, FR-013). T016 en verde
- [ ] T022 [P] [US2] Banco, parte de conversación en `tests/banco/test_banco_mejoras.py` (FR-017): `ha_call_service_response("conversation", "process", {"text": "<frase ficticia>", "language": "en"})` sin token → `service_in_denylist` con token y vista previa; confirmado → respuesta con la forma de `conversation.process` (`response` con `response_type`). Sin entidades no acciona nada
- [ ] T023 Control negativo del tramo 2: (a) ejecutar sin token en la denylist → caen los «no llamado»; (b) atar el token a `ha_call_service` en vez de a su nombre → cae el de tokens cruzados; (c) guardar la respuesta en `cached_result` → cae el del centinela; (d) `sobre_de_lista` con `count` fijo a 0 → cae el constructor; (e) `incumplen` que devuelve siempre `[]` → cae el control sintético. Anotar recuentos. Restaurar y comprobar verde

### Documentación y cierre

- [ ] T024 Documentación (FR-011, FR-019): en `hermes/CHANGELOG.md`, sección `### Mejoras de tools existentes` de la 1.2.0, entradas de `ha_call_service_response` (confirmación para la denylist y las entidades restringidas, respuesta sin token con el mismo `error` y el token añadido) y del sobre común en las tools nuevas; en `docs/HOJA-DE-RUTA.md`, estado de la 018 en la tabla «Programa de cobertura total (spec 008)» («hecha salvo el banco, preparado y que se valida al integrar la 010») y el problema 21 «Parcial (1.2.0: sobre común en las tools nuevas; las existentes, duda D-07)»; en `SECURITY.md`, la denylist pide confirmación también en `ha_call_service_response`
- [ ] T025 Matriz de trazabilidad de `specs/008-cobertura-total/plan.md`: filas CAP-019, CAP-020 y CAP-023 con los nombres y ficheros de test definitivos (`TestGuardarPorVista`, `TestTokenAtadoAlEstado`, `TestCallServiceResponseConfirmacion`, `tests/test_sobre_de_lista.py`, `tests/banco/test_banco_mejoras.py` pendiente de la 010)
- [ ] T026 Cierre del tramo 2: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII), commit con los recuentos de T023

---

## Dependencias

- Tramo 1: T001 → T002 → T003…T006. T003 → T005 → T007. T004 y T006 → T008 (necesita T005) → T009 → T011. T010 en cualquier momento tras T002. T012 tras T008. T013 el último.
- Tramo 2 (tras el tramo 1): T014, T015, T016 en paralelo. T014 → T017. T015 → T018 → T019. T020 con T017. T016 → T021. T022 tras T017. T023 tras T017…T021. T024, T025 tras T023. T026 el último.

## Paralelismo

- Tramo 1: T003, T004 y T006 (ficheros de test distintos); T010.
- Tramo 2: T014, T015 y T016; T022.

## Estrategia

MVP = tramo 1 (CAP-019, la única de prioridad alta: evita perder tarjetas al
reescribir un dashboard grande). El tramo 2 desbloquea la 023 (CAP-020) y fija
la forma de las listas para las sub-features de tools nuevas (CAP-023). Todo
sale en la 1.2.0 con el resto del programa.
