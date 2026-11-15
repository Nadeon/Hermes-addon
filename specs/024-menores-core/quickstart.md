# Quickstart: menores de Core (024)

Para comprobar a mano tras implementar (con un Home Assistant de pruebas,
nunca con el de nadie).

1. `ha_get_camera_snapshot(entity_id="camera.entrada", max_width=320)` →
   texto con `content_type`, `bytes`, `width`, `height` e imagen visible en
   el cliente.
2. `ha_get_image_entity(entity_id="image.qr_code")` → imagen PNG sin reducir.
3. `ha_get_camera_snapshot(entity_id="light.salon")` → `invalid_argument`
   sin petición.
4. `ha_reset_lovelace_dashboard_config(url_path="panel-pruebas")` → vista
   previa con vistas y tarjetas; repetir con el token → `result: ok`;
   `ha_get_lovelace_dashboard(url_path="panel-pruebas")` → sin
   configuración guardada.
5. `ha_reset_lovelace_dashboard_config(url_path="lovelace")` →
   `cannot_reset_default_dashboard`.
6. `ha_read_ws_command("webhook/list")` → `webhook_id` como
   `***REDACTED***`.
7. `ha_call_ws_command("camera/update_prefs", {"entity_id":
   "camera.entrada", "preload_stream": false})` → vista previa y token.
8. `ha_call_ws_command("lovelace/config/delete", {})` →
   `use_dedicated_tool`.
9. `hermes_guide(topic="cameras")` y `hermes_guide(topic="core_minor")`.

Suite (Git Bash, desde la raíz del worktree):

```
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" /c/Proyectos/Hermes-addon/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```
