---
description: "Tareas de la sub-feature 024 — menores de Core (Hermes 1.2.0)"
---

# Tareas: menores de Core (024)

**Entrada**: `specs/024-menores-core/` (spec.md, plan.md, research.md,
data-model.md, contracts/tools.md, quickstart.md) y la paraguas
`specs/008-cobertura-total/`.

**Tests**: obligatorios, escritos ANTES del código que prueban (TDD: se ven en
rojo y luego en verde) y con control negativo anotado (principio VII). Estilo
de los existentes: `unittest.IsolatedAsyncioTestCase`, `DummyMCP` o
`_RecordingMCP`, `AsyncMock` de `ws_send`, servidor aiohttp de prueba para el
REST (como los tests de `rest_get_text_tail`), `structlog.testing.capture_logs`.
Datos ficticios: `camera.entrada`, `image.qr_code`, `light.salon`,
`panel-pruebas`, `centinela-024`, un PNG y un JPEG generados en el propio
test (unos bytes con su cabecera), `192.0.2.10`,
`homeassistant.tailXXXX.ts.net`. Nada de la instalación real; ninguna llamada
a las tools MCP de Hermes conectadas.

**Suite** (desde la raíz del worktree, en Git Bash):
`export MSYS_NO_PATHCONV=1; HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`.
Línea base al especificar (2026-11-15, `feat/024-menores-core` en
`1752984`): 3611 passed, 111 skipped, 6 failed (los 6 conocidos de Windows).
Cada tramo anota su propia línea base al empezar y termina con exactamente
esos 6 fallos en local; la referencia es el CI de Linux.

**Requisito previo**: ninguno pendiente (la base tiene la 009–016, 018, 019,
027–030 y 033). Si otra sub-feature se ha integrado en `feat/cobertura-total`
antes de empezar un tramo, traerla primero (`git merge --no-ff`) y anotarlo.

## Formato: `[ID] [P?] [Historia] Descripción`

Historias de spec.md: US1 cámaras e imágenes, US2 restablecer un dashboard,
US3 lo menor por las genéricas, US4 nada de lo actual cambia.

## Tramos de implementación

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado.

| Tramo | Tareas | Resultado al cerrar |
|---|---|---|
| **1** — CAP-059 y datos por la tabla (CAP-065, 066, 067, 072) | **T001–T015** | `HAClient.rest_get_image`; familia `cameras` con `ha_get_camera_snapshot` y `ha_get_image_entity`; `camera/get_prefs` `read` y `camera/update_prefs` `confirm`; miniaturas tapadas en `browse_media`/`search_media`; 17 entradas fijadas por test; temas `cameras` y `core_minor` (parte); banco de las dos tools y de una entrada por CAP; documentación parcial |
| **2** — CAP-071, CAP-070, CAP-073 y cierre | **T016–T031** | familia `dashboard_reset` con `ha_reset_lovelace_dashboard_config`; `lovelace/config/delete` `dedicated`; cinco lecturas de CAP-071 `read`; motivo de `application_credentials/config_entry`; las 33 entradas fijadas; ninguna «spec 024»; sección en el tema `lovelace` y `core_minor` completo; banco, matriz de la 014, inventario de la 033; documentación final |

El tramo 2 necesita el tramo 1 integrado.

---

## Tramo 1 — CAP-059 y datos por la tabla

### Preparación

- [x] T001 Línea base: suite completa, anotar passed/skipped/failed y la punta; `grep -c "spec 024" hermes/src/hermes/command_table.py` da 8
- [x] T002 [P] [US4] Tests en `tests/test_tool_families.py`: `cameras` existe, `desde="1.2.0"`, desactivable, módulos `("cameras",)`, `familia_de_modulo("cameras") == "cameras"`; en `tests/test_config_validation.py`, `tool_families_disabled: [cameras]` es válido. Después, la familia en `hermes/src/hermes/tool_families.py` con un comentario del porqué (research R-3) (FR-013)

### Tests (escritos antes, en rojo)

- [x] T003 [P] [US1] Tests en `tests/test_ha_rest_get_image.py` con un servidor aiohttp de prueba: devuelve `(content_type sin parámetros, bytes)`; pasa los `params`; exactamente `max_bytes` → se devuelve; `max_bytes + 1` → `ImageTooLargeError` y la lectura se corta (el servidor ve la conexión cerrada antes de enviar el resto de un cuerpo de 10 MiB); 404/503/500 → `HAConnectionError` con `status` y sin el cuerpo en el mensaje (cuerpo con `centinela-024`); ruta insegura (`/api/../x`, `//x`) → rechazo sin petición; sesión no inicializada → `HAConnectionError` (FR-003)
- [x] T004 [P] [US1] Tests en `tests/test_tools_cameras.py` (`TestInstantanea`, `TestImagen`, `TestDimensiones`), con `rest_get_image` simulado: la respuesta es una lista `[dict, Image]` con `entity_id`, `content_type`, `bytes`, `width`, `height`, `requested_max_width`/`scaling` según data-model; la petición de la cámara es `/api/camera_proxy/camera.entrada` con `{"width": "640", "height": "360"}` por defecto y `320`/`180` con `max_width=320`; la de imagen, `/api/image_proxy/image.qr_code` sin `params`; `entity_id` inválidos (`"light.salon"`, `"camera."`, `"camera.x/../y"`, `"camera.X"`, `""`, `"image.qr"` en la de cámara) y `max_width` (63, 1921, `True`, `"640"`) → `invalid_argument` con `field` y **sin ninguna petición**; 404 → `not_found`; 503 → `camera_unavailable`/`image_unavailable`; 500 → `snapshot_failed` con `status`; `text/html` → `unsupported_content_type` sin imagen; `ImageTooLargeError` → `image_too_large` con `max_bytes: 2097152`; caída de HA → `ha_unavailable`; dimensiones de un PNG y un JPEG mínimos generados en el test, y `null` con bytes basura (la imagen se devuelve igual) (FR-001…FR-004)
- [x] T005 [P] [US1] Tests de privacidad y log en `tests/test_tools_cameras.py`: con un estado de la entidad en la caché que lleva `access_token: centinela-024` y `entity_picture: /api/camera_proxy/camera.entrada?token=centinela-024`, el centinela no aparece en ninguna parte de la respuesta (ni en el bloque de texto ni en errores); `capture_logs`: un evento `camera_image_read` por llamada con `tool`, `entity_id`, `bytes` y `outcome`, sin la URL, los parámetros ni los bytes; en un rechazo, `outcome="rejected:<código>"` (FR-004)

### Implementación

- [x] T006 [US1] `hermes/src/hermes/ha.py`: `ImageTooLargeError` y `HAClient.rest_get_image` según data-model, con un comentario del porqué (research R-2: sin Pillow, lectura en flujo). T003 en verde (FR-003)
- [x] T007 [US1] `hermes/src/hermes/tools/cameras.py`: `register(mcp, ha_client, *, response_max_bytes)`, `_MAX_IMAGE_BYTES = 2 * 1024 * 1024`, validación, `_dimensiones`, las dos tools con las descripciones de contracts/tools.md, devolviendo `[dict, Image(data=…, format=…)]`. Comprobar con el registro real (`MCPServer`) que la llamada devuelve un `TextContent` y un `ImageContent` y que ningún envoltorio común (tope, redacción) serializa la imagen; si alguno lo hace, sacar la imagen del envoltorio y anotarlo. T004 y T005 en verde (FR-001…FR-004)
- [x] T008 [US1] [US4] Registro en `hermes/src/hermes/tools/__init__.py` dentro de la comprobación de la familia `cameras`; las dos en `_OPEN_WORLD` de `tools/_annotations.py` con su comentario; `_HINTS_NUEVAS_1_2_0` (`"R-IO"`). Tests en `tests/test_tools_registration.py`: registradas por defecto con esas anotaciones, sin `confirmation_token`; ninguna con `cameras` desactivada; SC-005 de la 011 en verde; recuentos y «las únicas tools de más» actualizados (FR-013, FR-015, FR-020)
- [x] T009 [US3] [US4] Tabla, tests primero en `tests/test_command_table.py` y `tests/test_tools_generic_commands.py`, después `hermes/src/hermes/command_table.py`: `camera/get_prefs` → `read` y `camera/update_prefs` → `confirm` con `open_world=True`, motivos de data-model, las dos en `_POR_LA_TABLA` con «spec 024: …»; `media_source/browse_media` y `search_media` con `redact_extra=("thumbnail",)` y motivo que lo dice (research R-6); clase `TestClasificacionDeLa024` con un diccionario esperado `clave → (categoría, open_world, redact_extra)` para las 17 entradas de CAP-059, 065, 066, 067 y 072 (incluidas `resolve_media` y `image/create` en `deny`); con la tabla real: `ha_read_ws_command("media_source/browse_media", …)` con una respuesta simulada de dos niveles con `thumbnail: "/api/motioneye/…?authSig=centinela-024"` → el centinela no sale; `ha_call_ws_command("camera/update_prefs", …)` → vista previa con token y sin `ws_send`; `ha_read_ws_command("camera/update_prefs")` → `wrong_generic_tool`; ejecutar `scripts/inventario/generar_tabla.py` y comprobar que la tabla no cambia (`git diff --exit-code`, salvo finales de línea); `grep -c "spec 024"` da 6 (FR-005, FR-009, FR-010, FR-014)
- [x] T010 [US1] [US3] Guía: tests en `tests/test_tools_guide.py` (tema `cameras`: las dos tools, privacidad, que Core solo escala JPEG, el tope de 2 MiB, las preferencias por la tabla con su ejemplo; tema `core_minor`: calendario y tareas —remotos salen a internet—, tags, medios —miniaturas tapadas, `resolve_media` denegado, `local_source/remove` irreversible—, imágenes subidas —subir no se puede—; alias `camera`, `cámaras`, `camaras`, `snapshot`, `image`, `imagen`, `minor`, `menores`; el índice los nombra; las instrucciones del servidor nombran `cameras` solo con la familia activa; las huellas de los temas que no se tocan no cambian); después, `hermes/src/hermes/tools/guide.py` (FR-016)
- [x] T011 [US1] [US3] Banco: imagen JPEG de prueba generada (sin fotos) en `tests/banco/ha_config/www/hermes_banco/camara.jpg` y un fichero borrable en `tests/banco/ha_config/media/banco_borrable.jpg`; en `configuration.yaml`, `media_source:`, `image_upload:` y `homeassistant: media_dirs: {local: /config/media}`, cada uno con su comentario; `tests/banco/test_banco_camaras.py` (crear una entrada `local_file` por el lector con la imagen de `www`, `ha_get_camera_snapshot` con éxito y `content_type` `image/jpeg`; `ha_get_image_entity("image.qr_code")` con `image/png`; borrar la entrada); `tests/banco/test_banco_menores_datos.py` (`local_calendar`: crear un evento por el lector, `calendar/event/update` y `calendar/event/delete` en dos pasos con la vista previa sin efecto comprobada por el lector; `local_todo`: dos tareas y `todo/item/move`; `image/list` e `image/delete` tras subir por REST con el lector; `media_source/browse_media` y `local_source/remove` del fichero borrable; `camera/get_prefs` y `camera/update_prefs` sobre la cámara `local_file`); `tests/banco/cobertura_024.py` con `MODULOS_024 = ("cameras",)` y `LECTURAS_EN_BANCO_024`; sumarlo a `TOOLS_EXIGIDAS_DEL_JOB` y a `test_el_job_exige_las_probadas`; `TestCoberturaDeLa024` en `tests/test_banco_cobertura.py` (lo registrado por los módulos = lo declarado; cada nombre en un `test_banco_*.py`). Lo que no arranque sin red se anota y se queda en unitarios (FR-017)
- [x] T012 [US3] Tests de las genéricas con la tabla real en `tests/test_tools_generic_commands.py` para el resto de entradas del tramo: `calendar/event/delete` y `todo/item/move` con vista previa `open_world`; `image/create` → rechazo `deny` con su motivo; `media_source/resolve_media` → `deny` (FR-009, FR-010)
- [x] T013 Control negativo del tramo 1, anotando recuentos: (a) no cortar la lectura al pasar el tope → cae el de 10 MiB; (b) aceptar cualquier `entity_id` → caen los de validación sin petición; (c) devolver los atributos del estado → caen los del centinela `access_token`; (d) registrar la URL en el log → cae el del log; (e) quitar `redact_extra` de `browse_media` → cae el del `authSig`; (f) dejar `camera/update_prefs` en `deny` → caen los de la tabla; (g) sacar `ha_get_camera_snapshot` de `LECTURAS_EN_BANCO_024` → cae `TestCoberturaDeLa024`. Restaurar y comprobar verde
- [x] T014 Documentación del tramo 1: sección «Menores de Core» en `## [1.2.0]` de `hermes/CHANGELOG.md` (las dos tools, familia, tope, preferencias por la tabla, miniaturas tapadas) y recuentos de la tabla del bloque de la 011; `hermes/DOCS.md`, familia `cameras` en `tool_families_disabled`; `README.md` y `README.es.md` (recuento y familia, iguales); `docs/HOJA-DE-RUTA.md`, estado de la 024 «en curso: tramo 1» (FR-019)
- [x] T015 Cierre del tramo 1: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII), commit con los recuentos de T013 y el resultado de la regeneración de T009

---

## Tramo 2 — CAP-071, CAP-070, CAP-073 y cierre

### Preparación

- [x] T016 Línea base del tramo 2 con el tramo 1 integrado; `grep -c "spec 024"` da 6 — Hecho: 3892 passed, 134 skipped, 6 failed (los conocidos) en `139f905`; `grep -c "spec 024"` daba 6.

### Tests (escritos antes, en rojo)

- [x] T017 [P] [US3] Tests de las genéricas con la tabla real en `tests/test_tools_generic_commands.py`: `webhook/list` con `webhook_id: centinela-024` → el centinela no sale y `domain`, `name`, `local_only` sí; `application_credentials/list` con `client_secret: centinela-024` → no sale; `application_credentials/config_entry` → `***REDACTED***` y el motivo lo dice; `vacuum/get_segments` → `read` con `open_world`; `ha_call_ws_command("lovelace/config/delete", {})` → `use_dedicated_tool` con `ha_reset_lovelace_dashboard_config` sin llamada, y con `dashboard_reset` desactivada, `family_disabled`; `config/area_registry/reorder` → vista previa y token (FR-008, FR-011, FR-012, FR-014)
- [x] T018 [P] [US4] Tests en `tests/test_tool_families.py` y `tests/test_config_validation.py` para `dashboard_reset` (módulos `("lovelace_reset",)`); después, la familia (FR-013)
- [x] T019 [P] [US2] Tests en `tests/test_tools_lovelace_reset.py` (`TestProteccion`, `TestRechazos`), con `ws_send` simulado: `url_path` `None`, `""` y `"lovelace"` → `cannot_reset_default_dashboard` sin token y sin ninguna llamada, también con un token; `default_panel` igual al `url_path` → rechazo; lectura del `default_panel` que falla → `default_panel_unknown` sin token; dashboard que no existe → `not_found`; modo YAML → `yaml_mode_dashboard`; `lovelace/config` con `config_not_found` → `nothing_to_reset`; forma inesperada → `preview_unavailable`; en todos, ningún `lovelace/config/delete` (FR-006)
- [x] T020 [P] [US2] Tests en `tests/test_tools_lovelace_reset.py` (`TestVistaPrevia`, `TestConfirmacion`): vista previa con `url_path`, `title`, `mode`, `views`, `cards`, `effect`, `warning`, `recovery` y token, sin borrar; confirmación → `lovelace/config/delete` con `{"url_path": "panel-pruebas"}` exacto y resultado con `views_removed`/`cards_removed`; token de otro `url_path` → rechazado; configuración cambiada entre vista previa y confirmación → token rechazado por estado y sin borrar; el `default_panel` pasa a ser ese dashboard entre los dos pasos → rechazo con token; dashboard borrado entre los dos pasos → `not_found` y token completado; error de Core → `error` redactado y token fallido (FR-006, FR-007)
- [x] T021 [P] [US2] Tests del log en `tests/test_tools_lovelace_reset.py` con `capture_logs`: un evento por llamada con `tool`, `url_path` y `outcome`, sin la configuración del dashboard (con `centinela-024` en una tarjeta) (FR-007)

### Implementación

- [x] T022 [US2] `hermes/src/hermes/tools/lovelace_reset.py` según data-model, importando de `tools/lovelace.py` sin cambiarlo; `create_confirmation_token(..., estado=…)` y `resolve_confirmation_token(..., estado=…)`. T019–T021 en verde (FR-006, FR-007)
- [x] T023 [US2] [US4] Registro bajo `dashboard_reset`; `ha_reset_lovelace_dashboard_config` en `_DESTRUCTIVE_EXACT` con su comentario; `_HINTS_NUEVAS_1_2_0`; tests en `tests/test_tools_registration.py` (registrada con `confirmation_token`, anotaciones de contracts/tools.md, invariante «pide token → destructiva», ninguna con la familia desactivada, SC-005); fila `"ha_reset_lovelace_dashboard_config": {"url_path": A}` en `tests/test_confirmation_args_inventory.py` con el `estado` en su comentario y el recuento; `tests/test_allow_dangerous_inventario.py` en verde sin tocarlo (FR-015, FR-018, FR-020)
- [x] T024 [US3] [US4] Tabla: tests primero en `tests/test_command_table.py`, después `command_table.py` y `scripts/inventario/generar_tabla.py`: `lovelace/config/delete` → `dedicated` hacia la tool, familia `dashboard_reset`, `cap="CAP-071"` (y su clave en `_DEDICADAS_INICIALES`); `trace/contexts`, `frontend/get_themes`, `webhook/list` («el webhook_id sale tapado»), `vacuum/get_segments` (`open_world=True`) y `radio_frequency/list` → `read`, en `_POR_LA_TABLA`; motivo nuevo de `application_credentials/config_entry` (research R-7); `TestClasificacionDeLa024` con las 33 entradas; ninguna clave de la sub-feature empieza por `hassio/` ni `supervisor/`; `grep -c "spec 024"` da 0; regenerar sin cambios. T017 en verde (FR-008, FR-011, FR-012, FR-014)
- [x] T025 [US2] [US3] Guía: tests en `tests/test_tools_guide.py` (el tema `lovelace` gana la sección «Restablecer» —qué hace, que es irreversible, la protección del principal, cómo copiar antes— y su huella nueva en `_HUELLAS`, con el porqué; `core_minor` completo con temas, webhooks —id tapado—, contextos de trazas, segmentos —salen a internet en algunas integraciones—, radiofrecuencia, orden de áreas y plantas, ids automáticos y credenciales —`client_secret` nunca sale, crear y borrar no se puede—; alias `reset`, `restablecer`, `webhooks`, `themes`, `temas`; `hermes_guide(topic="generic_commands", search="lovelace/config/delete")` da `dedicated`); después, `guide.py` (FR-016, FR-020)
- [x] T026 [US2] [US3] Banco y matriz: en `configuration.yaml`, `application_credentials:` y un `vacuum` de plantilla con `segments` y `clean_segments` (sin red), con sus comentarios; `tests/banco/test_banco_menores_ui.py`: restablecer un dashboard creado con `ha_create_lovelace_dashboard` y guardado por el lector (vista previa sin efecto comprobada, confirmación, el lector ve `config_not_found`; `lovelace` rechazado sin token); `trace/contexts` tras disparar una automatización; `frontend/get_themes`; `webhook/list` con una automatización de disparador `webhook` (id tapado); `vacuum/get_segments`; `radio_frequency/list`; `config/entity_registry/settings/get`, `get_automatic_entity_ids`, `config/area_registry/reorder` (orden restaurado al final) y `config/device_registry/list_linked_devices`; `application_credentials/config` y `list`. `PROBADAS_024` en `cobertura_024.py` y en la unión de `tests/test_banco_cobertura_escrituras.py` (recuentos con su porqué); `MODULOS_024` con `lovelace_reset`; fila `ha_reset_lovelace_dashboard_config` | banco de Core en la matriz de `docs/HOJA-DE-RUTA.md` (orden alfabético); `tests/test_matriz_pruebas.py` en verde (FR-017, FR-018) — Desviación: el banco ejecuta además `application_credentials/list` (vacía: crear credenciales es clase D); el centinela del `client_secret` queda en los unitarios con la forma real.
- [x] T027 [US3] Si el banco destapa un fallo real de Core en alguna de estas entradas, es un HALLAZGO: `xfail` estricto que espera ese fallo concreto, en `XFAIL_PERMITIDOS`, anotado aquí y en la hoja de ruta; si no hay, anotar «sin hallazgos» (FR-017) — Sin hallazgos.
- [x] T028 [US4] Comprobar que las tools de la 1.1.2 y las ya integradas de la 1.2.0 no cambian (SC-005 de la 011, `tests/fixtures/esquemas_1_1_2.json` si aplica) y que las huellas de los temas no tocados siguen iguales (FR-020)
- [x] T029 Control negativo del tramo 2, anotando recuentos: (a) quitar la guarda del principal → caen los de `TestProteccion`; (b) no fallar cerrado sin `default_panel` → cae `default_panel_unknown`; (c) emitir el token sin `estado` → cae el de configuración cambiada; (d) no repetir la guarda con token → cae el del panel cambiado entre pasos; (e) dejar `lovelace/config/delete` en `deny` → caen los de la tabla; (f) sacar `webhook_id` de los marcadores → cae el centinela de `webhook/list` (restaurar enseguida); (g) quitar la fila de la 033 → cae su inventario. Restaurar y comprobar verde — Recuentos: (a) 6 subtests; (b) 3; (c) 5; (d) 4; (e) 8 (tabla, genéricas, generador desde cero y guía); (f) 1; (g) 3. Restaurado y en verde.
- [x] T030 Documentación final: completar la sección de la 024 en el CHANGELOG (la tool de restablecer, las lecturas de CAP-071, el hallazgo de las miniaturas y el motivo de `config_entry`); `docs/HOJA-DE-RUTA.md`: estado «hecha» de la 024 con un resumen; `README.md` y `README.es.md` sincronizados (recuento y familias); `hermes/DOCS.md` (familia `dashboard_reset`); `SECURITY.md` (miniaturas y `webhook_id` tapados por la tabla); filas CAP-059, 065, 066, 067, 070, 071, 072 y 073 de la matriz de `specs/008-cobertura-total/plan.md` con las tools o entradas y los ficheros de test, sin cambiar sus columnas de sub-feature ni de vía (FR-019)
- [x] T031 Cierre del tramo 2: suite completa (los 6 fallos conocidos y ninguno más), revisión del diff (principio VIII), commit con los recuentos de T029 y el resultado de la regeneración de T024 — Suite: 3931 passed, 141 skipped, 6 failed (los conocidos de Windows). Regeneración idéntica.

---

## Dependencias y paralelismo

- T002–T005 en paralelo; T006 tras T003; T007 tras T004–T006; T008 y T009
  tras T007; T010–T012 en paralelo tras T009.
- T017–T021 en paralelo; T022 tras T018–T021; T023 y T024 tras T022; T025 y
  T026 en paralelo tras T024; T027 tras T026.
- Fuera de esta sub-feature: la 017, 020, 021, 022, 023, 031 y 032 tocan los
  mismos ficheros comunes (plan, «Dependencias»).

---

## Fase 3: Convergencia

Revisión independiente y converge (2026-11-15) sobre la punta `8bc6fb5`.
Severidad entre corchetes. Cada hallazgo se verificó con un script fuera del
repositorio contra el código de Core 2026.11.1.

- [x] T032 [MEDIO] `webhook/list` deja salir el `webhook_id` en claro bajo `name`: la integración ONVIF de Core lo registra con el id como nombre (`components/onvif/event_manager.py`: `webhook.async_register(hass, DOMAIN, webhook_id, webhook_id, …)`, con `webhook_id = f"onvif{secrets.token_hex(6)}"`), así que la respuesta lleva `"webhook_id": "***REDACTED***"` y `"name": "onvif…"` con el mismo valor, y quien lo tenga inyecta eventos ONVIF sin autenticarse. Tapar en `webhook/list` cualquier valor de texto del elemento que contenga su `webhook_id` (no solo la clave), sin perder el `name` cuando no lo contiene; añadir a `test_webhook_list_tapa_el_id` el elemento con la forma REAL de ONVIF (`name` igual al id), con su control negativo, y que el motivo de la tabla, la guía (`core_minor`) y `SECURITY.md` sigan diciendo la verdad, per FR-008 y principio V (partial)
- [x] T033 [BAJO] `ha_reset_lovelace_dashboard_config`: si `lovelace/dashboards/list` falla (error de Core o forma inesperada; `_list_extra_dashboards` devuelve `[]`), la vista previa responde `not_found` y, en la confirmación, `{"result": "not_found"}` dando el token por completado con éxito, aunque el dashboard exista. Distinguir el fallo de lectura (p. ej. `preview_unavailable`, con el token pendiente para reintentar en su plazo) de un dashboard que de verdad no está, con tests de los dos pasos, per FR-006 y principio V (partial)
- [x] T034 [BAJO] Vista previa de restablecer un dashboard de estrategia (`{"strategy": {...}}` sin `views`): dice `views: 0` y `cards: 0` con el aviso «every view and card listed here is lost», pero lo que se borra es la configuración de la estrategia. Decirlo en la vista previa (p. ej. `strategy: true` o el `type` de la estrategia) con un test, per FR-007 y principio V (partial)
