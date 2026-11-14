---

description: "Tareas de Hermes 1.1.2 (spec 007)"
---

# Tareas: Hermes 1.1.2 — confirmar solo con el token

**Entrada**: `specs/007-confirmar-con-token/` (spec.md, plan.md, research.md,
data-model.md, contracts/tools.md, quickstart.md).

**Tests**: obligatorios, escritos antes del arreglo y con control negativo
(principio VII). Estilo de los existentes: `unittest.IsolatedAsyncioTestCase`,
`CONFIRMATIONS_DIR` en un `tempfile.TemporaryDirectory`, `DummyMCP` y los
simuladores de HA de cada fichero. Datos ficticios (principio VIII).

## Formato: `[ID] [P?] [Historia] Descripción`

## Fase 1: Preparación

- [X] T001 Línea base: la suite completa pasa sobre la punta de la rama; anotar el recuento (referencia: CI de Linux)
- [X] T028 Enmienda del principio IV en `docs/PRINCIPIOS.md` y `.specify/memory/constitution.md` en el mismo cambio, con el texto de research R-9; constitución `**Version**: 1.1.0`, `**Last Amended**: 2026-11-14` (FR-013). Va ANTES que cualquier código: la constitución manda (Governance) y el código de las fases siguientes contradice el texto actual del principio IV

## Fase 2: Fundacional — guardar y resolver en `security.py` (bloquea todas las historias)

- [X] T002 Tests en `tests/test_security.py`, clase nueva `TestConfirmarSoloConToken`: (a) con `omitibles=("config",)` el fichero del token guarda `stored_args` con SOLO `config`, y un argumento no omitible con un valor centinela no aparece en el fichero; sin `omitibles`, el fichero es como en 1.1.1; (b) `resolve_confirmation_token` sin `config` devuelve `(True, "", resueltos)` con `resueltos` igual a los argumentos de la vista previa; (c) con todos los argumentos, mismo resultado (FR-004); (d) `config` distinto → «does not match this action» y el estado sigue `pending`; (e) argumento añadido → igual; (f) token de otra tool → igual; (g) omitido sin `stored_args` (fichero escrito sin él, como uno de 1.1.1) → «has no stored value for: config», estado `pending`, y después la llamada completa pasa (FR-005); (h) `""` y `{}` no son omisión; (i) dos `resolve` simultáneos con `asyncio.gather` → solo uno pasa (FR-012); control negativo que sí puede fallar: un `await asyncio.sleep(0)` entre la lectura del estado y la escritura de `executing` deja que las dos corrutinas lean `pending` y las dos pasan; (j) `validate_confirmation_token` conserva firma y resultados (FR-001…FR-005, FR-012)
- [X] T003 En `hermes/src/hermes/security.py`: parámetro `omitibles: tuple[str, ...] = ()` en `create_confirmation_token` que guarda `stored_args` y `stored_bytes` («Solo los omitibles de la tool presentes en la vista previa, con el valor que entró en el hash»); `resolve_confirmation_token(token, tool_name, args, *, omitibles=()) -> tuple[bool, str, dict[str, Any]]` (hash sobre los resueltos, sin `await` entre leer y escribir `executing`); `validate_confirmation_token` como envoltorio con `omitibles=()`. Comentarios en español con el porqué (R-3, R-4)
- [X] T004 Control negativo: con `security.py` de la punta anterior caen los tests de T002 salvo (c), (f) y (j); con la fusión pero sin recalcular el hash sobre los resueltos (aceptando lo guardado sin más) caen (d) y (e); con un `await asyncio.sleep(0)` entre leer el estado y escribir `executing` cae (i). Anotar recuentos

## Fase 3: Historia 1 — Guardar un documento grande con confirmación (P1) 🎯 MVP

**Objetivo**: las cinco tools confirman sin reenviar el documento.
**Prueba independiente**: dashboard de 41 KB → vista previa → confirmación con `url_path` + token → HA recibe el `config` de la vista previa.

- [X] T005 [P] [US1] Tests en `tests/test_tools_lovelace.py`: dashboard ficticio de ~41 KB, confirmación sin `config` → un `lovelace/config/save` con el `config` exacto; lo mismo con un dashboard ficticio de ~1 MB (SC-001); igual con `url_path=None`; con todos los argumentos sigue funcionando; sin token y sin `config` → `invalid_argument` con `field: "config"` y sin token; `url_path` en modo YAML se sigue rechazando al confirmar sin `config`
- [X] T006 [P] [US1] Tests en `tests/test_fs_write_security.py`: confirmación sin `content` escribe el contenido de la vista previa; `content=""` escribe un fichero vacío (no es omisión); sin token y sin `content` → `invalid_argument` (`field: "content"`) en texto JSON, como el resto de respuestas de la tool
- [X] T007 [P] [US1] Tests en `tests/test_tools_automations.py`: confirmación sin `config` guarda la configuración normalizada de la vista previa; sin token y sin `config` → `invalid_argument`
- [X] T008 [P] [US1] Tests en `tests/test_tools_scripts.py`: lo mismo que T007 para `ha_create_or_update_script`
- [X] T009 [P] [US1] Tests en `tests/test_tools_scenes.py`: lo mismo para una escena existente; escena nueva sin `config` → `invalid_argument` y no se guarda nada
- [X] T010 [P] [US1] Test en `tests/test_tools_registration.py` sobre el registro real: en el esquema de entrada de las cinco tools el documento no está en `required` y el destino sí (`url_path`, `path`, `automation_id`, `script_id`, `scene_id`) (FR-006)
- [X] T011 [P] [US1] `hermes/src/hermes/tools/lovelace.py`: `_OMITIBLES_GUARDAR = ("config",)` con comentario; `config: dict[str, Any] | None = None`; `invalid_argument` sin token y sin `config`; `_validate_dashboard_config` solo si viene; `args` sin `config` si no viene; `create_confirmation_token(..., omitibles=…)`; en la confirmación, `resolve_confirmation_token` y `config` de los resueltos; `remove_top_level_keys` NO es omitible; docstring con la línea de la omisión (FR-002, FR-006)
- [X] T012 [P] [US1] `hermes/src/hermes/tools/filesystem_write.py`: lo mismo con `content: str | None = None` (omisión solo con `None`); el contenido escrito sale de los resueltos; docstring (FR-002, FR-006)
- [X] T013 [P] [US1] `hermes/src/hermes/tools/automations.py`: lo mismo con `config`; `AutomationConfig.model_validate` solo si viene; `normalized_config` de los resueltos al confirmar; docstring
- [X] T014 [P] [US1] `hermes/src/hermes/tools/scripts.py`: lo mismo con `ScriptConfig`; docstring
- [X] T015 [P] [US1] `hermes/src/hermes/tools/scenes.py`: lo mismo con `SceneConfig`; la rama de escena nueva exige `config`; docstring
- [X] T016 [US1] Control negativo: con las cinco tools de la punta anterior (documento obligatorio) caen los tests de T005…T010; anotar recuento

## Fase 4: Historia 2 — El agente sabe que puede omitir el documento (P1)

**Objetivo**: la vista previa, el guardián, la guía y las descripciones lo dicen.
**Prueba independiente**: la vista previa de cada tool trae `confirm_with`, `omit_on_confirm` y `confirm_hint`, también recortada.

- [X] T017 [P] [US2] Tests: en `tests/test_security.py`, `create_confirmation_token` con omitibles devuelve `confirm_with` (lista ordenada con `confirmation_token`), `omit_on_confirm` y `confirm_hint`, y sin omitibles no los devuelve; en cada test de vista previa de T005…T009, los tres campos con los valores de `contracts/tools.md` (en Lovelace, `remove_top_level_keys` en `confirm_with` si se usó); en `tests/test_response_limit.py`, una vista previa de `ha_save_lovelace_dashboard` por encima del tope conserva los tres campos y el token, y una de `fs_delete_file` no trae ninguno (FR-007)
- [X] T018 [US2] `hermes/src/hermes/security.py`: los tres campos en la respuesta de `create_confirmation_token` cuando hay `omitibles` (FR-007)
- [X] T019 [P] [US2] `hermes/src/hermes/tools/_common.py`: `confirm_with`, `omit_on_confirm` y `confirm_hint` en `intocables` y en el mínimo de último recurso de `_recortar_vista_previa`, con el porqué (FR-007)
- [X] T020 [P] [US2] `hermes/src/hermes/tools/guide.py`: `INSTRUCTIONS` punto 1 y temas `security`, `files` y `workflows` según `contracts/tools.md`; test en `tests/test_tools_guide.py`: ya no dice «MISMOS argumentos» y menciona `omit_on_confirm` (FR-008)
- [X] T021 [US2] Control negativo: sin T018 caen los tests de campos; sin T019 cae el del guardián; con la guía de la punta anterior cae el de la guía. Anotar

## Fase 5: Historia 3 — El token sigue atado a la acción (P1)

**Objetivo**: comprobar por las tools reales que ningún token ejecuta otra cosa.
**Prueba independiente**: cada intento de desvío se rechaza y no llega nada a HA ni a `/config`.

- [X] T022 [US3] Tests por las tools: `ha_save_lovelace_dashboard` con token de `url_path: "panel-a"` confirmado con `"panel-b"` (con y sin `config`) → «does not match», ningún `lovelace/config/save`; `config` distinto → igual; `remove_top_level_keys` añadido en la confirmación → igual; `fs_write_file` con otro `path` → igual y el fichero no cambia; token de `ha_save_lovelace_dashboard` usado en `ha_create_or_update_automation` → igual; tras cada rechazo, el token sigue sirviendo para la acción correcta (en `tests/test_tools_lovelace.py`, `tests/test_fs_write_security.py` y `tests/test_tools_automations.py`) (SC-002)
- [X] T023 [US3] Control negativo: con `resolve_confirmation_token` que rellena desde lo guardado TODOS los argumentos (también los enviados) caen los de `config` distinto; con una fusión que omite el destino del hash caen los de otro destino. Anotar

## Fase 6: Historia 4 — El documento no se queda en disco ni en el log (P2)

**Objetivo**: borrado al completar, fallar y caducar; tope; nada en el log.
**Prueba independiente**: tras cada final de token, ningún fichero del directorio de confirmaciones contiene el centinela; el log tampoco.

- [X] T024 [P] [US4] Tests en `tests/test_security.py`: `complete_confirmation_token` (éxito y fallo) quita `stored_args` y `stored_bytes` y conserva `state` y `cached_result`/`cached_error`; un token caducado lo borra `resolve`; `create_confirmation_token` barre los caducados con documento; con `CONFIRMATION_STORED_MAX_BYTES` parcheado a un valor pequeño, el token se emite sin `stored_args`, sin `omit_on_confirm`, con `confirm_with` completo y se registra `confirmation_args_not_stored` con `reason="storage_cap"`; con el log capturado (structlog) en vista previa, confirmación, tope y caducidad, el centinela no aparece. En `tests/test_fs_write_security.py`: tras escribir, ningún fichero de `CONFIRMATIONS_DIR` contiene el contenido. En `tests/test_confirmations_periodic_cleanup.py`: el intervalo es 60, y la limpieza periódica solo registra `confirmations_cleaned` cuando ha limpiado algo (> 0), para que una limpieza cada 60 s no llene el log (FR-009…FR-011)
- [X] T025 [US4] `hermes/src/hermes/security.py`: `_barrer_caducados()` síncrona usada por `cleanup_expired_confirmations` y por `create_confirmation_token`; `CONFIRMATION_STORED_MAX_BYTES = 16 * 1024 * 1024`, comparado con la suma de los bytes de los documentos guardados en los tokens vigentes (`stored_bytes`, sumado en el mismo barrido) más los del documento nuevo; degradado de FR-011 con `confirmation_args_not_stored` (solo `tool`, `reason`, `keys`, `bytes`); `complete_confirmation_token` quita `stored_args` y `stored_bytes` (FR-009…FR-011)
- [X] T026 [US4] `hermes/src/hermes/__main__.py`: `CONFIRMATIONS_CLEANUP_INTERVAL_SECONDS = 60` con el porqué; actualizar la aserción de 3600 en `tests/test_confirmations_periodic_cleanup.py` explicando el cambio (FR-009)
- [X] T027 [US4] Control negativo: sin el borrado en `complete` caen los de disco; sin el tope cae el de `storage_cap`; con el intervalo en 3600 cae el suyo; registrando `confirmations_cleaned` también con 0 cae el del log. Anotar

## Fase 7: Principios, versión y documentación

- [X] T029 [P] Versión 1.1.2 en `hermes/config.yaml`, `hermes/src/hermes/__init__.py` y `HA_CORE_LAST_TESTED_IN_HERMES` de `hermes/src/hermes/config.py` (FR-014)
- [X] T030 [P] `hermes/CHANGELOG.md`: `## [1.1.2] — 2026-11-14` al estilo de la 1.1.1, con «Fixed» (caducidad de las confirmaciones con documentos grandes, con las cifras de la prueba en vivo) y «Changed» (documento opcional al confirmar en las cinco tools, campos nuevos de la vista previa, limpieza cada 60 s, tope de 16 MiB) (FR-014)
- [X] T031 [P] `SECURITY.md`: junto a «bound to the tool and its arguments», que los documentos de la vista previa se guardan en el almacenamiento del add-on hasta completar o caducar (como mucho 60 s después) y nunca en el log (FR-014)
- [X] T032 [P] `docs/HOJA-DE-RUTA.md`: «Problemas conocidos de 1.1.1» pasa a resuelto en 1.1.2 (confirmar solo con el token); revisión 1.1.2 en la cabecera; en «Pruebas manuales pendientes», guardar en vivo el dashboard de ~41 KB y un `fs_write_file` grande confirmando sin el documento (quickstart.md) (FR-014, SC-005)
- [X] T033 Comprobar con `grep` que `README.md`, `README.es.md` y `hermes/DOCS.md` no dicen que haya que repetir los argumentos; si alguno lo dijera, corregirlo en el mismo cambio (FR-014)

## Fase 8: Cierre

- [X] T034 Suite completa, revisión del diff buscando datos personales e identificadores de modelos (principio VIII) y commit con los recuentos de los controles negativos (T004, T016, T021, T023, T027)

## Dependencias

- Fase 2 bloquea todas las historias (`resolve_confirmation_token` y `omitibles`).
- US1 (Fase 3) depende de la Fase 2. US2 depende de la Fase 2 y usa los tests de vista previa de US1. US3 depende de US1 (va por las tools). US4 depende de la Fase 2 y de T018: el test del tope (T024) comprueba `confirm_with` completo y la ausencia de `omit_on_confirm`, que añade T018. T025 toca `security.py`, igual que T003 y T018: van en serie.
- T028 (enmienda del principio IV) va en la Fase 1, antes que cualquier código. El resto de la Fase 7 en cualquier momento tras la Fase 2; T034 al final.

## Paralelismo

- Fase 3: T005…T010 en paralelo (ficheros de test distintos); después T011…T015 en paralelo (una tool por fichero).
- Fase 4: T019 y T020 en paralelo con T018.
- Fase 7: T029…T032 en paralelo.

## Estrategia

MVP = Fases 1–3 (las cinco tools confirman sin el documento). US2 es
imprescindible para que un cliente real lo aproveche; US3 y US4 cierran la
seguridad. Se publica todo junto como 1.1.2.
