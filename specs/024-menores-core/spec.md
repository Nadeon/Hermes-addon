# Especificación: Hermes 1.2.0 — menores de Core (sub-feature 024)

**Directorio de la spec**: `specs/024-menores-core`

**Creada**: 2026-11-15

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T023 de su `tasks.md` y cubre **CAP-059** (cámaras e
imágenes) y **CAP-071** (lecturas y ajustes menores de la UI) con tools
dedicadas y tabla, y **CAP-065** (calendario y tareas), **CAP-066** (tags),
**CAP-067** (navegación de medios), **CAP-070** (registros: orden e ids),
**CAP-072** (imágenes subidas) y **CAP-073** (credenciales de aplicación) por
la tabla: FR-085…FR-088 de la 008. Depende de la 011 (tabla, genéricas y
familias) y del banco de la 010.

**Entrada**: `specs/008-cobertura-total/` (spec, plan con la matriz,
research CAP-059…CAP-073 e `inventario/core-ws.tsv`), la tabla
`hermes/src/hermes/command_table.py` (con las entradas que la 011 ya
clasificó para estas CAP), `scripts/inventario/generar_tabla.py`,
`tool_families.py`, `tools/lovelace.py` (`_default_panel`,
`_get_dashboard_meta_by_url_path`, `_count_cards`, protección del principal
de `ha_delete_lovelace_dashboard`), `tools/generic_commands.py`
(`_redactar`, `redact_extra`), `security.py` (`create_confirmation_token` con
`estado`, `redact_structure` y el marcador `webhook_id`), `ha.py`
(`_request_json`, `rest_get_text_tail`, `_assert_safe_request_path`) y el
código de Core 2026.11.1: `camera/__init__.py` (`CameraImageView`,
`_async_get_image`, `camera/get_prefs|update_prefs`), `camera/img_util.py`,
`image/__init__.py` (`ImageView`), `lovelace/websocket.py`
(`lovelace/config/delete`), `trace/websocket_api.py`,
`frontend/__init__.py`, `webhook/__init__.py`, `vacuum/websocket.py`,
`radio_frequency/websocket_api.py`, `media_source/http.py`,
`motioneye/media_source.py`, `application_credentials/__init__.py`,
`kitchen_sink/image.py`, `local_file/config_flow.py` y `template/vacuum.py`.

## Clarificaciones

### Sesión 2026-11-15

Decisiones vinculantes del programa (en la 008 y la 011):

- CAP-059 es de prioridad **media** y privada: la instantánea de una cámara y
  la imagen de una entidad `image` van por **tools dedicadas** que devuelven
  `ImageContent` (FR-085); las preferencias de cámara van por la tabla
  (`read`/`confirm`).
- CAP-071: restablecer la configuración de un dashboard va por **tool
  dedicada con confirmación** y con la misma protección del dashboard
  principal que el resto de tools de Lovelace (FR-086); contextos de trazas,
  temas, webhooks, segmentos de aspiradores y radiofrecuencia quedan `read`.
- CAP-065, CAP-066, CAP-067, CAP-070, CAP-072 y CAP-073 van **solo por la
  tabla** (FR-087, FR-088). La 011 ya las clasificó al generar la tabla; esta
  sub-feature las revisa contra Core 2026.11.1, corrige lo que no cuadra y
  las prueba.
- Las tools nuevas van en **familias nuevas** de la 1.2.0 (FR-010), activas
  por defecto (la duda D-03 de la 008 sobre las cámaras la decide el
  mantenedor al cerrar el programa).
- Lo que la 008 clasificó en **clase D** sigue `deny`
  (`application_credentials/create|update|delete`,
  `media_source/resolve_media`, `webhook/handle`).

Decisiones tomadas al especificar (no había a quién preguntar; se justifican
en [research.md](research.md)):

- P: ¿Cómo se reduce la imagen sin dependencias nuevas? → R: la cámara la
  pide reducida a Core (`?width=&height=` de `/api/camera_proxy`, que Core
  escala si es JPEG); `/api/image_proxy` no escala. Hermes no añade Pillow:
  lee en flujo con un tope fijo de bytes y, si la imagen lo supera, responde
  `image_too_large` sin devolver nada (R-2).
- P: ¿Nombres? → R: los de la 008: `ha_get_camera_snapshot`,
  `ha_get_image_entity` y `ha_reset_lovelace_dashboard_config` (R-1). Las
  otras tools que el research de la 008 citaba para estas CAP
  (`ha_get_camera_prefs`, `ha_list_tags`…) no se crean: su spec las manda a
  la tabla.
- P: ¿Familias? → R: `cameras` (módulo `cameras`) y `dashboard_reset`
  (módulo `lovelace_reset`). La de Lovelace de la 1.1.2 no se toca (R-3).
- P: ¿El restablecimiento protege también el dashboard elegido como panel por
  defecto? → R: sí, como `ha_delete_lovelace_dashboard`, y falla cerrado si
  no puede leerlo (R-4).
- P: ¿Qué pasa con `media_source/browse_media`, que la 011 dejó `read`, si
  alguna fuente firma sus miniaturas? → R: es un **hallazgo**: la fuente de
  motionEye firma la miniatura con `async_sign_path` (5 min). La entrada
  sigue `read`, pero con `redact_extra=("thumbnail",)` en `browse_media` y
  `search_media` (R-6).
- P: ¿`application_credentials/config_entry`? → R: su único dato
  (`application_credentials_id`) sale tapado por la redacción general (la
  clave contiene `credential`); la entrada sigue `read`, pero su motivo pasa a
  decirlo (principio V, R-7).

## Escenarios de usuario y pruebas *(obligatorio)*

### Historia 1 — Ver qué enseña una cámara o una entidad imagen (prioridad: P1)

Un usuario pregunta «¿hay alguien en la entrada?» y el cliente MCP tiene que
ver la imagen de la cámara, no sus atributos.

**Por qué esta prioridad**: es la única CAP de prioridad media de la
sub-feature y lo que hoy no se puede hacer con ninguna tool ni por la tabla
(la imagen va por REST).

**Prueba independiente**: con una cámara `local_file` en el banco, la tool
devuelve una imagen y sus metadatos; con una entidad que no existe, un error
sin llamada a Core.

**Escenarios de aceptación**:

1. **Dado** `camera.entrada` encendida, **cuando** se llama
   `ha_get_camera_snapshot(entity_id="camera.entrada")`, **entonces** la
   respuesta trae un bloque de texto con `entity_id`, `content_type`, `bytes`
   y las dimensiones si se pueden leer, y un bloque `ImageContent`.
2. **Dado** `max_width=320`, **cuando** se pide, **entonces** Hermes pide a
   Core `?width=320&height=180` y lo dice en la respuesta como petición, no
   como garantía (Core solo escala JPEG).
3. **Dado** una cámara apagada (503), inexistente (404) o que falla (500),
   **cuando** se pide, **entonces** `camera_unavailable`, `not_found` o
   `snapshot_failed`, sin imagen.
4. **Dado** una imagen mayor que el tope, **cuando** se lee, **entonces**
   Hermes corta la lectura y responde `image_too_large` con el tope.
5. **Dado** `image.qr_code`, **cuando** se llama
   `ha_get_image_entity(entity_id="image.qr_code")`, **entonces** lo mismo
   con `/api/image_proxy`.
6. **Dado** `entity_id="light.salon"` o `"camera.x/../y"`, **cuando** se
   llama, **entonces** `invalid_argument` sin ninguna petición.

---

### Historia 2 — Restablecer un dashboard (prioridad: P2)

El usuario quiere tirar la configuración de un dashboard extra y volver a la
autogenerada.

**Prueba independiente**: en el banco, un dashboard creado con
`ha_create_lovelace_dashboard` y guardado con una vista vuelve a no tener
configuración guardada tras confirmar.

**Escenarios de aceptación**:

1. **Dado** el dashboard `panel-pruebas` con dos vistas, **cuando** se llama
   sin token, **entonces** vista previa con el título, vistas y tarjetas que
   se pierden, que es irreversible y cómo copiarlo antes, y un token.
2. **Dado** el token, **cuando** se repite con él, **entonces** Core recibe
   `lovelace/config/delete` con `url_path` y el dashboard queda sin
   configuración guardada.
3. **Dado** `url_path=null`, `"lovelace"` o el `default_panel`, **cuando** se
   llama, con o sin token, **entonces** `cannot_reset_default_dashboard` sin
   token y sin borrar nada; si el `default_panel` no se puede leer,
   `default_panel_unknown`.
4. **Dado** un dashboard en modo YAML, sin configuración guardada o que no
   existe, **entonces** `yaml_mode_dashboard`, `nothing_to_reset` o
   `not_found`, sin token.
5. **Dado** que la configuración cambia entre la vista previa y la
   confirmación, **cuando** se confirma, **entonces** el token no vale y no
   se borra nada.

---

### Historia 3 — Lo menor de Core por las genéricas (prioridad: P3)

Preferencias de cámara, temas, webhooks, contextos de trazas, segmentos de
aspiradores, radiofrecuencia, calendario y tareas, tags, medios, orden de
áreas y plantas, ids automáticos, imágenes subidas y credenciales de
aplicación, con `ha_read_ws_command` o `ha_call_ws_command`.

**Prueba independiente**: cada entrada tiene un test de su clasificación y
cada familia de entradas, al menos una ejecución en el banco.

**Escenarios de aceptación**:

1. **Dado** `ha_read_ws_command("webhook/list")`, **entonces** la lista con
   `domain`, `name`, `local_only` y `allowed_methods`, y cada `webhook_id`
   tapado.
2. **Dado** `ha_call_ws_command("camera/update_prefs", …)`, **entonces**
   vista previa con token antes de cambiar nada.
3. **Dado** `ha_read_ws_command("media_source/browse_media", …)` con una
   miniatura firmada, **entonces** la miniatura sale tapada.
4. **Dado** `ha_read_ws_command("application_credentials/list")`,
   **entonces** ningún `client_secret` sale.
5. **Dado** `ha_call_ws_command("lovelace/config/delete", …)`, **entonces**
   `use_dedicated_tool` con `ha_reset_lovelace_dashboard_config`.

---

### Historia 4 — Nada de lo actual cambia (prioridad: P1)

**Escenarios de aceptación**:

1. **Dado** las familias `cameras` y `dashboard_reset` desactivadas,
   **entonces** sus tools no se registran y la lista vuelve a la de antes.
2. **Dado** la configuración por defecto, **entonces** las tools de la 1.1.2
   tienen los mismos nombres, anotaciones y argumentos (SC-005 de la 011).

### Casos límite

- Cámara con `use_stream_for_stills` sin stream: Core responde 500 →
  `snapshot_failed`.
- Respuesta de Core sin `Content-Type` de imagen (p. ej. HTML de error con
  200): `unsupported_content_type`, sin imagen.
- Imagen exactamente en el tope: se devuelve; un byte más: `image_too_large`.
- Cabecera de imagen ilegible (no PNG ni JPEG): `width`/`height` nulos, la
  imagen se devuelve igual.
- El dashboard se borra entre la vista previa y la confirmación:
  `not_found` y el token se completa.
- `lovelace/config/delete` sobre un dashboard sin configuración: Core da
  `config_not_found`; la vista previa lo detecta antes (`nothing_to_reset`).
- Un `vacuum` sin `CLEAN_AREA`: Core responde `not_supported`; la genérica lo
  devuelve redactado.

## Requisitos *(obligatorio)*

### Requisitos funcionales

#### CAP-059 — cámaras e imágenes

- **FR-001**: `ha_get_camera_snapshot(entity_id, max_width=640)` devuelve la
  instantánea de una entidad `camera.*` por `GET /api/camera_proxy/{entity_id}`
  con `width=max_width` y `height=⌈max_width·9/16⌉`, como un bloque de
  metadatos y un `ImageContent`. `max_width` entre 64 y 1920
  (FR-085 de la 008, CAP-059).
- **FR-002**: `ha_get_image_entity(entity_id)` devuelve la imagen de una
  entidad `image.*` por `GET /api/image_proxy/{entity_id}`, con la misma
  forma; dice que Core no la escala (FR-085, CAP-059).
- **FR-003**: Las dos leen la imagen en flujo con un método nuevo del
  cliente (`HAClient.rest_get_image`) y un tope fijo de 2 MiB: si se supera,
  cortan y responden `image_too_large` sin devolver bytes. Mapean 404 →
  `not_found`, 503 → `camera_unavailable`/`image_unavailable`, otros ≥400 →
  `snapshot_failed`, `Content-Type` que no es `image/*` →
  `unsupported_content_type` (FR-085, FR-018 de la 008).
- **FR-004**: `entity_id` se valida con el patrón de su dominio antes de
  ninguna petición (`invalid_argument`). La respuesta nunca incluye
  `access_token`, `entity_picture` ni la URL pedida; el log solo lleva
  `entity_id`, `bytes` y el resultado, nunca la imagen ni la URL (FR-019,
  CAP-059).
- **FR-005**: `camera/get_prefs` pasa a `read` y `camera/update_prefs` a
  `confirm` con `open_world` (precargar el stream de una cámara en la nube
  mantiene tráfico hacia internet) y un motivo que lo dice (FR-085,
  CAP-059).

#### CAP-071 — lecturas y ajustes menores de la UI

- **FR-006**: `ha_reset_lovelace_dashboard_config(url_path,
  confirmation_token=None)` borra la configuración guardada de un dashboard
  (`lovelace/config/delete`) en dos pasos. Rechaza, con y sin token, el
  principal (`url_path` nulo o `"lovelace"`) y el `default_panel`
  (`cannot_reset_default_dashboard`) y falla cerrado si no puede leer el
  `default_panel` (`default_panel_unknown`); rechaza sin token los
  dashboards que no existen (`not_found`), los de modo YAML
  (`yaml_mode_dashboard`) y los que no tienen configuración guardada
  (`nothing_to_reset`) (FR-086, CAP-071).
- **FR-007**: La vista previa dice título, modo, vistas y tarjetas que se
  pierden, que es irreversible y que `ha_get_lovelace_dashboard` permite
  copiarla antes; el token ata `url_path` y, con `estado`, la configuración
  leída: si cambia antes de confirmar, no se borra nada (FR-086, FR-018).
- **FR-008**: `trace/contexts`, `frontend/get_themes`, `webhook/list` (con
  cada `webhook_id` tapado por la redacción estructural),
  `vacuum/get_segments` (`open_world`: algunas integraciones consultan el
  aspirador o su nube) y `radio_frequency/list` pasan a `read` con su motivo
  (FR-086, CAP-071).

#### CAP-065, CAP-066, CAP-067, CAP-070, CAP-072 y CAP-073 — por la tabla

- **FR-009**: Las entradas de calendario y tareas (`calendar/event/update`,
  `calendar/event/delete`, `todo/item/move`: `confirm` con `open_world`),
  tags (`tag/list` `read`; `tag/create|update|delete` `confirm`) e imágenes
  subidas (`image/list` `read`; `image/update|delete` `confirm`;
  `image/create` `deny` porque va por REST multipart) quedan como están y
  tienen un test que fija su clasificación (FR-087; CAP-065, CAP-066,
  CAP-072).
- **FR-010**: Navegación de medios: `media_source/browse_media` y
  `media_source/search_media` siguen `read` con `open_world` y ganan
  `redact_extra=("thumbnail",)` y un motivo que lo dice;
  `media_source/local_source/remove` sigue `confirm`;
  `media_source/resolve_media` sigue `deny` (URL firmada) (FR-087, CAP-067).
- **FR-011**: Registros: `config/area_registry/reorder`,
  `config/floor_registry/reorder` y `config/entity_registry/settings/update`
  `confirm`; `config/entity_registry/get_automatic_entity_ids`,
  `config/entity_registry/settings/get`,
  `config/device_registry/list_linked_devices` y
  `config/device_registry/list_composite_splits` `read`; con test de su
  clasificación (FR-087, CAP-070).
- **FR-012**: Credenciales de aplicación: `application_credentials/list`,
  `config` y `config_entry` `read`, ningún `client_secret` en la respuesta
  (centinela), el motivo de `config_entry` dice que el id sale tapado, y
  `create`, `update` y `delete` siguen `deny` (clase D) (FR-088, FR-019,
  CAP-073).

#### Transversales

- **FR-013**: Familias nuevas de la 1.2.0, desactivables y activas por
  defecto: `cameras` (módulo `cameras`) y `dashboard_reset` (módulo
  `lovelace_reset`) (FR-010 de la 008).
- **FR-014**: `lovelace/config/delete` pasa a `dedicated` hacia
  `ha_reset_lovelace_dashboard_config` por el mecanismo del generador
  (`_DEDICADAS_INICIALES`); las siete entradas de FR-005 y FR-008 entran en
  `_POR_LA_TABLA` con «spec 024: …»; ninguna entrada queda «pendiente de tool
  dedicada (spec 024)»; regenerar la tabla no la cambia; ninguna tool ni
  entrada usa comandos `hassio/` ni `supervisor/` (FR-012 de la 008).
- **FR-015**: Anotaciones honestas: las dos de imagen, solo lectura y mundo
  abierto; la de restablecer, `-DI-` (destructiva e idempotente, como
  `ha_delete_lovelace_dashboard`) y de mundo cerrado. Registro en `tools/__init__.py`
  bajo sus familias y en `_HINTS_NUEVAS_1_2_0` (FR-018, FR-020).
- **FR-016**: Guía: tema nuevo `cameras` (las dos tools, el tope, la
  reducción que hace Core y las preferencias por la tabla), tema nuevo
  `core_minor` (las entradas `read`/`confirm` de estas CAP con sus
  advertencias) y una sección de restablecer en el tema `lovelace`, con su
  huella actualizada (FR-011 de la 008).
- **FR-017**: Banco: `ha_reset_lovelace_dashboard_config` se ejecuta contra
  Core real con el lector y la vista previa sin efecto; las dos de imagen
  también (cámara `local_file` y `image.qr_code` de `kitchen_sink`); y cada
  CAP de la tabla tiene al menos un comando ejecutado por las genéricas
  (FR-014, FR-015 de la 008).
- **FR-018**: Invariantes del programa: fila de la tool que modifica en la
  matriz de la 014; fila en el inventario de argumentos atados de la 033
  (`url_path` atado, más `estado`); el inventario de `allow_dangerous` de la
  018 sigue verde (ninguna tool nueva lo acepta); ninguna lista nueva fuera
  de `sobre_de_lista` (FR-015, FR-018).
- **FR-019**: Documentación en el mismo cambio: sección propia en
  `## [1.2.0]` del CHANGELOG, estado de la 024 en `docs/HOJA-DE-RUTA.md`,
  `hermes/DOCS.md` (familias), `README.md` y `README.es.md` (recuento),
  `SECURITY.md` si cambia la redacción de la tabla, y las filas de la matriz
  de la 008 (FR-023, FR-024 de la 008).
- **FR-020**: Nada de lo actual cambia: las tools de la 1.1.2 y las ya
  integradas en la 1.2.0 conservan nombres, anotaciones y argumentos; el
  tema `lovelace` solo gana una sección (FR-020 de la 008).

### Entidades clave

- **Imagen leída**: tipo de contenido, bytes y dimensiones de cabecera.
- **Restablecimiento**: `url_path`, configuración leída (huella), resumen.
- **Entrada de la tabla**: categoría, motivo, `open_world`, `redact_extra`.

## Criterios de éxito *(obligatorio)*

- **SC-001**: Las 3 tools nuevas se registran con todas las familias
  activas y desaparecen con sus familias desactivadas (SC-005 de la 011 en
  verde).
- **SC-002**: `grep -c "spec 024" hermes/src/hermes/command_table.py` da 0 y
  regenerar la tabla no cambia nada.
- **SC-003**: Cada una de las 33 entradas con `cap` CAP-059, CAP-065,
  CAP-066, CAP-067, CAP-070, CAP-071, CAP-072 o CAP-073 tiene su categoría,
  `open_world` y `redact_extra` fijados por un test.
- **SC-004**: Ningún centinela (`client_secret`, `webhook_id`, `authSig` de
  una miniatura, `access_token` de cámara) aparece en una respuesta, vista
  previa, error ni log.
- **SC-005**: En el banco, la tool que modifica y las dos de imagen se
  ejecutan con éxito y cada CAP de la tabla tiene una ejecución; 0 `xfail`
  nuevos salvo hallazgo documentado.
- **SC-006**: La suite acaba con los 6 fallos conocidos de Windows y ninguno
  más; el CI de Linux en verde.

## Supuestos

- El banco puede cargar `local_file` (por su flujo de configuración, con una
  imagen versionada en `www/`), `local_calendar`, `local_todo`,
  `media_source`, `image_upload`, `application_credentials` y un `vacuum` de
  plantilla con segmentos sin internet; si alguno no arranca, esa prueba
  queda en unitarios y se anota.
- Core 2026.11.1 no escala `image_proxy`; la reducción de cámara depende de
  TurboJPEG en la imagen de Core y de que la cámara dé JPEG.

## Fuera de alcance

- Vídeo, streams, WebRTC y `camera/capabilities` (clase B, siguen `deny`).
- Subir imágenes (`image/create` y la subida REST de `image_upload`).
- Crear, cambiar o borrar credenciales de aplicación (clase D).
- Cambiar la opción por defecto de las familias (duda D-03 de la 008).
