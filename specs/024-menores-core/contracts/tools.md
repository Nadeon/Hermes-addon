# Contratos de las tools: menores de Core (024)

Descripciones en inglés (como el resto de tools); el texto final lo fija la
implementación sin cambiar lo que dice. Anotaciones: R = readOnlyHint,
D = destructiveHint, I = idempotentHint, O = openWorldHint.

## `ha_get_camera_snapshot` — familia `cameras` — `R-IO`

```text
ha_get_camera_snapshot(entity_id: str, max_width: int = 640) -> list[dict | Image]
```

> Returns a still image of what a camera sees right now (an MCP image block)
> plus its metadata. PRIVACY: this is the live view of the camera. Home
> Assistant is asked for an image about `max_width` pixels wide (64–1920);
> it only scales JPEG, so the image may be larger. Images over 2 MiB are not
> returned (`image_too_large`). Cloud cameras fetch the image from the
> internet. Stream preferences (preload, orientation) go through
> `ha_read_ws_command("camera/get_prefs")` /
> `ha_call_ws_command("camera/update_prefs")`.

Petición: `GET /api/camera_proxy/{entity_id}?width=W&height=⌈W·9/16⌉`.

## `ha_get_image_entity` — familia `cameras` — `R-IO`

```text
ha_get_image_entity(entity_id: str) -> list[dict | Image]
```

> Returns the current image of an `image.*` entity (an MCP image block) plus
> its metadata. Home Assistant serves it unscaled; images over 2 MiB are not
> returned (`image_too_large`). Some image entities download it from the
> internet.

Petición: `GET /api/image_proxy/{entity_id}`.

## `ha_reset_lovelace_dashboard_config` — familia `dashboard_reset` — `-DI-` (como `ha_delete_lovelace_dashboard`: repetirla no tiene más efecto)

```text
ha_reset_lovelace_dashboard_config(url_path: str, confirmation_token: str | None = None) -> dict
```

> Deletes the stored config of a storage-mode Lovelace dashboard so it goes
> back to the auto-generated one. Irreversible (except from a backup): copy
> it first with `ha_get_lovelace_dashboard`. **Always requires
> `confirmation_token`**: the first call returns a preview with the views and
> cards that would be lost. The main dashboard (`lovelace`) and the default
> panel are always protected (`cannot_reset_default_dashboard`); if the
> default panel cannot be read nothing is reset. YAML dashboards cannot be
> reset.

Comando: `lovelace/config/delete` con `url_path`. Errores:
`cannot_reset_default_dashboard`, `default_panel_unknown`, `not_found`,
`yaml_mode_dashboard`, `nothing_to_reset`, `preview_unavailable`, los del
token (incluido el de estado cambiado).

## Por la tabla (genéricas)

| Comando | Genérica | Categoría | Notas |
|---|---|---|---|
| `camera/get_prefs` | `ha_read_ws_command` | read | `{"entity_id": "camera.entrada"}` |
| `camera/update_prefs` | `ha_call_ws_command` | confirm, O | `preload_stream`, `orientation` |
| `trace/contexts` | `ha_read_ws_command` | read | `domain`+`item_id` opcionales |
| `frontend/get_themes` | `ha_read_ws_command` | read | |
| `webhook/list` | `ha_read_ws_command` | read | `webhook_id` tapado |
| `vacuum/get_segments` | `ha_read_ws_command` | read, O | `entity_id` |
| `radio_frequency/list` | `ha_read_ws_command` | read | |
| CAP-065/066/067/070/072/073 | según R-0 | sin cambios salvo R-6 y R-7 | |
