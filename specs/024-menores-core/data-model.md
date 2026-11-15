# Modelo de datos: menores de Core (024)

## Cliente: `HAClient.rest_get_image`

```text
async def rest_get_image(path: str, *, params: dict[str, str] | None = None,
                         max_bytes: int) -> tuple[str, bytes]
```

- `_assert_safe_request_path(path)` como `_request_json`.
- GET a `{rest_base_url}{path}` con plazo total de 30 s; lee en trozos de
  64 KiB y, si el acumulado pasa de `max_bytes`, deja de leer y lanza
  `ImageTooLargeError(max_bytes)` (subclase de `HAConnectionError`).
- Estado ≥ 400 → `HAConnectionError(..., status=…)` sin el cuerpo (puede ser
  HTML con datos de la instalación).
- Devuelve `(content_type, bytes)`; `content_type` sin parámetros
  (`image/jpeg`).

## Imagen leída (respuesta de las dos tools de `cameras`)

Lista de dos bloques: un `dict` (→ `TextContent` JSON) y un `Image`.

| Campo | Tipo | Notas |
|---|---|---|
| `entity_id` | str | el validado |
| `content_type` | str | de Core, `image/*` |
| `bytes` | int | crudos, ≤ 2 MiB |
| `width`, `height` | int \| null | de la cabecera PNG/JPEG |
| `requested_max_width` | int | solo cámara |
| `scaling` | str | cámara: «requested from Home Assistant; it only scales JPEG»; imagen: «not scaled: Home Assistant serves the original» |

Errores (`{"error": código, …}`, sin imagen): `invalid_argument` (con
`field`), `not_found`, `camera_unavailable` / `image_unavailable`,
`snapshot_failed` (con `status`), `unsupported_content_type`,
`image_too_large` (con `max_bytes`), `ha_unavailable`.

Validación: `^camera\.[a-z0-9_]+$` y `^image\.[a-z0-9_]+$`;
`max_width` entero 64…1920 (booleanos rechazados).

Log: evento `camera_image_read` con `tool`, `entity_id`, `bytes`,
`outcome`; nunca la URL, los parámetros ni los bytes.

## Restablecimiento (`ha_reset_lovelace_dashboard_config`)

Argumentos: `url_path: str` (si llega nulo o vacío, se trata como el principal), `confirmation_token: str | None`.

Orden (fail-closed):

1. `url_path` nulo, vacío o `"lovelace"` → `cannot_reset_default_dashboard`.
2. `_default_panel` → error → `default_panel_unknown`; igual → rechazo.
3. Sin token: `_get_dashboard_meta_by_url_path` → `None` → `not_found`;
   `mode == "yaml"` → `yaml_mode_dashboard`; `lovelace/config` →
   `config_not_found` → `nothing_to_reset`; otra forma → 
   `preview_unavailable`.
4. Vista previa:

| Campo | Valor |
|---|---|
| `url_path`, `title`, `mode` | de la metadata |
| `views`, `cards` | recuento de la configuración leída (`_count_cards`) |
| `effect` | «deletes the stored config; the dashboard becomes auto-generated» |
| `warning` | irreversible salvo backup |
| `recovery` | copiar antes con `ha_get_lovelace_dashboard`, restaurar con `ha_save_lovelace_dashboard` |

   `create_confirmation_token("ha_reset_lovelace_dashboard_config",
   {"url_path": url_path}, preview=…, estado=config_leída)`.
5. Con token: pasos 1 y 2 otra vez; metadata (`None` → `not_found` y token
   completado); relectura; `resolve_confirmation_token(..., estado=…)`;
   `lovelace/config/delete` con `url_path`; resultado
   `{"result": "ok", "url_path", "views_removed", "cards_removed"}`.

Inventario de la 033: `url_path` → atado (más `estado`: configuración leída).

## Tabla (cambios)

| Clave | Antes | Después |
|---|---|---|
| `lovelace/config/delete` | `deny` pendiente | `dedicated` → `ha_reset_lovelace_dashboard_config`, familia `dashboard_reset`, CAP-071 |
| `camera/get_prefs` | `deny` pendiente | `read`: preferencias de stream (precarga y orientación) |
| `camera/update_prefs` | `deny` pendiente | `confirm`, `open_world`: precarga del stream (las cámaras en la nube mantienen tráfico a internet) y orientación |
| `trace/contexts` | `deny` pendiente | `read` |
| `frontend/get_themes` | `deny` pendiente | `read` |
| `webhook/list` | `deny` pendiente | `read`: «el webhook_id sale tapado» |
| `vacuum/get_segments` | `deny` pendiente | `read`, `open_world` |
| `radio_frequency/list` | `deny` pendiente | `read` |
| `media_source/browse_media`, `search_media` | `read`, `open_world` | + `redact_extra=("thumbnail",)` y motivo |
| `application_credentials/config_entry` | `read` | motivo honesto (id tapado) |

El resto de las 33 queda igual. Familia de todas las de la tabla:
`generic_commands`.

## Familias

| Familia | Desde | Desactivable | Módulos | Descripción (inglés) |
|---|---|---|---|---|
| `cameras` | 1.2.0 | sí | `cameras` | «Camera snapshots and image entities (returns images).» |
| `dashboard_reset` | 1.2.0 | sí | `lovelace_reset` | «Reset a Lovelace dashboard to its auto-generated config.» |

## Banco

`tests/banco/cobertura_024.py`: `MODULOS_024 = ("cameras", "lovelace_reset")`,
`PROBADAS_024 = {"ha_reset_lovelace_dashboard_config"}` (se suma al invariante
de escrituras y al job), `LECTURAS_EN_BANCO_024 = {"ha_get_camera_snapshot",
"ha_get_image_entity"}` (se suma al job). `PROBADAS_024 ∪
LECTURAS_EN_BANCO_024` = lo que registran los dos módulos.
