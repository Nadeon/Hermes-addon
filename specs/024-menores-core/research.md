# Research: menores de Core (024)

Contrastado con el código de Core 2026.11.1 de la carpeta `fuentes` (solo
lectura) y con la rama `feat/024-menores-core` en `1752984` (293 tools; 009,
010, 011, 012, 013, 014, 015, 016, 018, 019, 027, 028, 029, 030 y 033
integradas).

## R-0 — Qué hay ya y qué falta

La 011 generó la tabla con estas CAP. Estado al especificar (33 entradas con
`cap` de esta sub-feature):

| CAP | Entradas | Estado en la tabla |
|---|---|---|
| CAP-059 | `camera/get_prefs`, `camera/update_prefs` | `deny` «pendiente (spec 024)» |
| CAP-065 | `calendar/event/update|delete`, `todo/item/move` | `confirm`, `open_world` |
| CAP-066 | `tag/list` · `tag/create|update|delete` | `read` · `confirm` (con ejemplos; ya en el banco de la 011) |
| CAP-067 | `browse_media`, `search_media` · `local_source/remove` · `resolve_media` | `read` `open_world` · `confirm` · `deny` (URL firmada) |
| CAP-070 | 4 lecturas · 3 escrituras | `read` · `confirm` |
| CAP-071 | `lovelace/config/delete`, `trace/contexts`, `frontend/get_themes`, `webhook/list`, `vacuum/get_segments`, `radio_frequency/list` | `deny` «pendiente (spec 024)» |
| CAP-072 | `image/list` · `image/update|delete` · `image/create` | `read` · `confirm` · `deny` (REST multipart) |
| CAP-073 | `application_credentials/list|config|config_entry` | `read` (`client_secret` por el marcador `secret`) |

Clase D que sigue `deny`: `application_credentials/create|update|delete`,
`webhook/handle`; `media_source/resolve_media` lo denegó la 011 por
coherencia con `auth/sign_path`. Clase B que sigue `deny`: las suscripciones
(`tag/subscribe`, `image/subscribe`, `calendar/event/subscribe`,
`todo/item/subscribe`, `application_credentials/subscribe`), `camera/stream`,
`camera/capabilities` y `camera/webrtc/*`.

Ningún comando de esta sub-feature empieza por `hassio/` ni `supervisor/`.
Las dos tools de imagen usan REST de Core (`/api/camera_proxy/…`,
`/api/image_proxy/…`) por el cliente de `ha.py`, como `/api/error_log`, no
por las genéricas: no tienen entrada en la tabla (las rutas `/core/api*` del
Supervisor siguen `deny` siempre).

**Ramas sin integrar revisadas** (`git diff 1752984...<rama>`): la 017
(`wait_for_trigger`, `blueprints`, `targets`…), la 020 (estadísticas), la 021
(usuarios, red y HTTP, analytics), la 022 (control de Core y Supervisor), la
023 (Assist), la 031 (backups) y la 032 (host). Ninguna toca cámaras,
`image_proxy`, `lovelace/config/delete` ni las entradas de la tabla de esta
sub-feature: no hay duplicados. Conflictos de fusión esperables solo en los
ficheros comunes (`tool_families.py`, `tools/__init__.py`, `guide.py`,
`_annotations.py`, `command_table.py`, `generar_tabla.py`, recuentos de los
README, CHANGELOG y hoja de ruta).

## R-1 — Tools y nombres

- `ha_get_camera_snapshot` y `ha_get_image_entity`: los nombres de la 008
  (research CAP-059). Prefijo `ha_get_` → solo lectura por
  `_READ_ONLY_PREFIXES`.
- `ha_reset_lovelace_dashboard_config`: el de la 008 (CAP-071). `ha_reset_`
  no es prefijo destructivo: va en `_DESTRUCTIVE_EXACT`. Idempotencia: la
  segunda llamada da `nothing_to_reset`, sin efecto; se declara como el resto
  de destructivas de Lovelace: `-DI-`, como
  `ha_delete_lovelace_dashboard`, sin `openWorldHint`.
- `ha_get_camera_prefs`, `ha_update_camera_prefs`, `ha_list_tags`,
  `ha_reorder_areas`… del research de la 008 **no** se crean: FR-085…FR-088
  los mandan a la tabla (la regla de reparto de la 008: lecturas y escrituras
  de bajo riesgo, por la tabla).

**Alternativa descartada**: una tool `ha_list_webhooks` dedicada. La tabla
con la redacción estructural ya da lo útil (dominio, nombre, `local_only`) y
tapa el `webhook_id`.

## R-2 — Imágenes sin dependencias nuevas

Core 2026.11.1:

- `CameraImageView` (`/api/camera_proxy/{entity_id}`) acepta `width` y
  `height`; `_async_get_image` los pasa a la cámara y, si la imagen es JPEG,
  `scale_jpeg_camera_image` la reduce con TurboJPEG a un factor soportado
  (7/8 … 1/8) que deje ancho y alto **por encima** de lo pedido. Sin
  TurboJPEG, o si no es JPEG, devuelve el original. Cámara apagada → 503;
  entidad que no existe → 404 (con autenticación); fallo → 500.
- `ImageView` (`/api/image_proxy/{entity_id}`) no admite tamaño.
- Las dos se autentican con el `Authorization` del cliente (el token de
  Hermes por el proxy del Supervisor): no hace falta el `access_token` de la
  entidad, que es un secreto (los atributos `access_token` y
  `entity_picture?token=…`) y no se devuelve nunca.

Decisión: Hermes **no** añade Pillow (sin ruedas fiables en la imagen base,
más superficie; principio IX). Pide `width=max_width` y
`height=⌈max_width·9/16⌉` (16:9, el formato más común; con otra proporción
Core elige un factor que respeta los dos mínimos y la imagen queda algo
mayor) y aplica un tope fijo de **2 MiB** de bytes crudos
(`_MAX_IMAGE_BYTES`), independiente de `response_max_bytes` (que mide el
JSON de texto). En base64 son ~2,7 MB, por debajo del límite habitual de
imagen de los clientes MCP. La lectura es en flujo: al pasar del tope se
corta la conexión y se responde `image_too_large` con el tope, sin bytes. El
tope no es argumento: un cliente no debe poder pedir 50 MB.

Dimensiones: una función pura lee ancho y alto de la cabecera PNG (IHDR) y
JPEG (primer SOFn); si no puede, `null`. Solo para informar.

**SDK**: `mcp` 2.x convierte un `Image` (`mcp.server.mcpserver.utilities.types`)
o una lista que lo contenga en `ImageContent`, y un `dict` de la lista en
`TextContent` JSON (`func_metadata._convert_to_content`). La tool devuelve
`[metadatos, Image(data=…, format=…)]`. La implementación comprueba que
ningún envoltorio común de Hermes (tope de respuesta, redacción, registro)
serializa la lista entera a texto; si alguno lo hace, la imagen queda fuera
del envoltorio y se anota.

**Mundo abierto**: una cámara en la nube (Nest, Ring…) o una entidad `image`
que descarga de una URL salen a internet al pedir la imagen: las dos son
`openWorldHint` y lo dicen en la descripción.

## R-3 — Familias

`cameras` (módulo `cameras`: las dos de imagen) y `dashboard_reset` (módulo
`lovelace_reset`: restablecer). La familia `lovelace` de la 1.1.2 no gana
tools (FR-010 de la 008: desactivando las de la 1.2.0 vuelve la lista de la
1.1.2). Las dos activas por defecto (FR-010); la duda D-03 de la 008
(cámaras desactivadas por defecto) queda para el mantenedor.

## R-4 — Restablecer un dashboard

`lovelace/config/delete` (`require_admin`, `url_path` opcional) llama a
`LovelaceConfig.async_delete()`: en almacenamiento borra la configuración
guardada y el dashboard pasa a autogenerado; en YAML no está soportado
(`HomeAssistantError`). Es irreversible salvo backup.

Protección del principal: la misma de `ha_delete_lovelace_dashboard`
(`tools/lovelace.py`): `url_path` nulo o `"lovelace"` → rechazo antes de
mirar el token; `_default_panel` → si falla, `default_panel_unknown`; si
coincide, rechazo. Se repite con token (el panel puede cambiar en 60 s). Se
reutilizan `_default_panel`, `_get_dashboard_meta_by_url_path` y
`_count_cards` importándolas de `tools/lovelace.py`, sin cambiarlas.

Vista previa: `lovelace/config` con `url_path` → error `config_not_found` →
`nothing_to_reset` sin token. El token ata `url_path` y `estado` = la
configuración leída (spec 018); al confirmar se relee y
`resolve_confirmation_token(..., estado=…)` rechaza si cambió.

**Alternativa descartada**: permitir restablecer el principal con una
opción. La 008 pide «la misma protección»; vaciar la pantalla de inicio es
justo lo que `ha_delete_lovelace_dashboard` impide.

## R-5 — Lecturas de CAP-071

| Comando | Core | Decisión |
|---|---|---|
| `trace/contexts` | `require_admin`; `domain`+`item_id` opcionales; contexto → `run_id`, `domain`, `item_id` | `read` |
| `frontend/get_themes` | temas, `default_theme`, `default_dark_theme` | `read` |
| `webhook/list` | `require_admin`; `webhook_id`, `domain`, `name`, `local_only`, `allowed_methods` | `read`; el `webhook_id` lo tapa `redact_structure` (marcador `webhook_id` de `security.py`): es una credencial de hecho |
| `vacuum/get_segments` | `require_admin`; `not_found`/`not_supported`; `async_get_segments` (Roborock Q7 refresca el mapa por red) | `read`, `open_world` |
| `radio_frequency/list` | `require_admin`; transmisores y receptores con rangos y modulaciones | `read` |

Las siete (con las dos de cámara) van a `_POR_LA_TABLA` de
`tests/test_command_table.py` con «spec 024: …», que es como la 013 dejó
lecturas de CAP de vía D+T en la tabla. El generador conserva el texto
revisado de cada entrada; `lovelace/config/delete` entra en
`_DEDICADAS_INICIALES` para que una generación desde cero dé lo mismo.

## R-6 — Hallazgo: miniaturas firmadas en `browse_media`

`motioneye/media_source.py` construye la miniatura de cada vídeo con
`async_sign_path(..., timedelta(minutes=5), use_content_user=True)`: una URL
con `authSig` que da acceso al medio sin token durante cinco minutos. Es lo
mismo que la 011 denegó en `resolve_media`. `browse_media` y
`search_media` siguen `read` (navegar es útil y lo demás no está firmado),
con `redact_extra=("thumbnail",)`: la genérica tapa la clave a cualquier
profundidad (`_redactar` de `tools/generic_commands.py`). Una miniatura no le
sirve a un cliente MCP. El motivo de las dos entradas lo dice.

`grep async_sign_path` en `components/` no da otras fuentes de medios
(`media_player/browse_media.py` firma las de reproductores, que no pasan por
estos comandos).

## R-7 — Credenciales de aplicación

`application_credentials/list` (colección) devuelve `client_secret` en claro;
el marcador `secret` lo tapa. `config_entry` devuelve
`{"application_credentials_id": …}` y la clave contiene `credential`, así
que también sale tapado: la entrada no puede prometer «id de la credencial».
Se cambia su motivo («dice si una integración usa una credencial de
aplicación; el id sale tapado por la redacción general»), sin tocar la
redacción.

## R-8 — Banco

- Cámara: `local_file` solo se configura por flujo (sin YAML). El test crea
  la entrada por el lector (`config_entries/flow`) con
  `/config/www/hermes_banco/camara.jpg` (JPEG de prueba versionado en
  `tests/banco/ha_config/www/hermes_banco/`; `www` está en
  `allowlist_external_dirs` por defecto) y la borra al terminar.
- Imagen: `image.qr_code` de `kitchen_sink` (PNG de la propia integración).
- Restablecer: dashboard creado con `ha_create_lovelace_dashboard`, guardado
  con una vista por el lector, restablecido; el lector ve `config_not_found`.
- Tabla: `local_calendar` y `local_todo` (entradas creadas y borradas por el
  lector, como la de diagnósticos de la 012), `media_source:` con
  `media_dirs` en `/config/media` y un fichero versionado borrable,
  `image_upload:` (subida REST por el lector), `application_credentials:`,
  un `vacuum` de plantilla con `segments`/`clean_segments`, `webhook` por una
  automatización con disparador `webhook`, `radio_frequency` de
  `kitchen_sink`.
- Lo que no arranque sin red se queda en unitarios y se anota (supuesto de
  la spec).

## R-9 — Pruebas en vivo

Nada del Supervisor. Pendiente manual tras publicar (matriz de la 014, sin
fila nueva porque las de imagen no modifican): una cámara real JPEG y otra
en la nube para ver la reducción y el tope.
