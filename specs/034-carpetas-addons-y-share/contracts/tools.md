# Contratos: tools de /addons y /share (034)

Descripciones, errores y respuestas al cliente en inglés (como el resto de
tools); comentarios del código en español.

## Firmas (esquema de entrada MCP)

```python
# Módulo folders (familia addons_share), tramo 1
fs_list_dir_in_folder(folder: str, path: str = ".", recursive: bool = False, max_depth: int = 3)
fs_stat_in_folder(folder: str, path: str)
fs_read_file_in_folder(folder: str, path: str, offset: int = 0, limit: int = 500)

# Módulo folders_write (familia addons_share), tramo 2
fs_write_file_in_folder(folder: str, path: str, content: str = None, confirmation_token: str | None = None)
fs_create_dir_in_folder(folder: str, path: str, confirmation_token: str | None = None)
fs_move_in_folder(folder: str, src: str, dst: str, confirmation_token: str | None = None)
fs_delete_in_folder(folder: str, path: str, recursive: bool = False, confirmation_token: str | None = None)

# Existentes: MISMO esquema de entrada; solo cambia la vista previa (tramo 3)
sv_install_addon(slug, confirmation_token=None)            # familia supervisor
sv_rebuild_addon(slug, force=False, confirmation_token=None)  # familia app_store
# Convergencia 2 (T053): MISMO esquema de entrada; cambia la vista previa
sv_update_addon(slug, confirmation_token=None)             # familia supervisor
```

`content` se anota `str` (no `str | None`), como en `fs_write_file`: el SDK
hace `json.loads` de todo argumento de texto cuya anotación no es
exactamente `str`, y un `.json` llegaría convertido en dict.

`folder` se valida a mano (`"addons"` o `"share"`) y no con `Literal`, para
que el error sea el `invalid_argument` común y no una validación del SDK.

## Anotaciones

| Tool | readOnly | destructive | idempotent | openWorld | Cómo |
|---|---|---|---|---|---|
| `fs_list_dir_in_folder` | sí | no | sí | no | prefijo `fs_list_` |
| `fs_stat_in_folder` | sí | no | sí | no | prefijo `fs_stat` |
| `fs_read_file_in_folder` | sí | no | sí | no | prefijo `fs_read_` |
| `fs_write_file_in_folder` | no | sí | sí | no | `_DESTRUCTIVE_EXACT` |
| `fs_create_dir_in_folder` | no | sí | sí | no | `_DESTRUCTIVE_EXACT` |
| `fs_move_in_folder` | no | sí | sí | no | `_DESTRUCTIVE_EXACT` |
| `fs_delete_in_folder` | no | sí | sí | no | prefijo `fs_delete_` |

## Respuestas

### `fs_list_dir_in_folder`

```json
{"folder": "share", "path": ".", "count": 2, "truncated": false,
 "items": [{"name": "configs", "type": "dir", "size_bytes": null,
            "modified": "2026-11-15T10:00:00+00:00", "is_blacklisted": false},
           {"name": "configs/app.yaml", "type": "file", "size_bytes": 120,
            "modified": "…", "is_blacklisted": false}]}
```

Con `truncated: true`, `hint` («More than 500 entries; use a more specific
path»).

### `fs_stat_in_folder`

```json
{"folder": "addons", "path": "ejemplo", "type": "dir", "size_bytes": null,
 "modified": "…", "is_blacklisted": false, "is_mount_point": false,
 "app": {"slug": "local_ejemplo", "installed": false}}
```

`app` solo en `addons` y solo si la ruta es la carpeta de una app del
índice; `installed: null` si el Supervisor no respondió.

### `fs_read_file_in_folder`

```json
{"folder": "addons", "path": "ejemplo/config.yaml", "size_bytes": 812,
 "encoding": "utf-8", "offset": 0, "returned_lines": 30, "total_lines": 30,
 "lines": ["name: Ejemplo\n", "…"], "truncated": false}
```

Con más líneas: `truncated: true`, `next_offset` y `hint`. `total_lines` es
`null` si el fichero mide más de 4 MiB. Binario:

```json
{"folder": "share", "path": "foto.jpg", "size_bytes": 20480, "binary": true,
 "content": null, "hint": "Binary file: only metadata is returned."}
```

### Vista previa común (las cuatro que modifican)

```json
{"confirmation_token": "…", "expires_in_seconds": 60,
 "preview": {"action": "delete", "folder": "addons", "path": "ejemplo",
             "type": "dir", "recursive": true,
             "contents": {"files": 12, "dirs": 3, "symlinks": 0, "total_bytes": 40960,
                          "sample": ["…"], "sample_truncated": false},
             "warning": "/addons holds the code of local apps: the Supervisor builds and runs what is here.",
             "backup": null, "reversible": false,
             "backup_hint": "To keep a copy first: sv_create_backup_partial(folders='[\"addons/local\"]').",
             "state_bound": "The token is bound to the current state; any change before confirming cancels it."}}
```

Específico de cada una:

- escribir: `exists`, `current_size_bytes`, `current_sha256_12`,
  `new_size_bytes`, `new_sha256_12`, `is_blacklisted`, `inside_installed_app`
  (si aplica), y las pistas `confirm_with`/`omit_on_confirm` de siempre;
- crear carpeta: `creates_parents` (lista de las que faltan); `reversible:
  true`;
- mover: `src`, `dst`, `type`, `contents` si es carpeta,
  `inside_installed_app` del origen o del destino si aplica;
- borrar: `type`, `size_bytes` o `contents`, `inside_installed_app` si
  aplica.

### Confirmación

```json
{"result": "ok", "action": "delete", "folder": "addons", "path": "ejemplo",
 "deleted": {"files": 12, "dirs": 4, "symlinks": 0}}
```

Escribir: `{"result": "ok", "path": …, "bytes_written": N}`; crear:
`{"result": "ok", "path": …, "created": [...]}`; mover: `{"result": "ok",
"src": …, "dst": …}`. Borrado a medias: `{"error": "partial", "partial":
true, "remaining": {"files": …, "dirs": …}, "detail": …}`.

Estado cambiado:

```json
{"error": "<ESTADO_CAMBIADO>", "preview_outdated": true,
 "hint": "The target changed since the preview. Nothing was done; request a new preview."}
```

### Rechazo por app instalada

```json
{"error": "installed_app", "slug": "local_ejemplo", "path": "ejemplo",
 "hint": "Uninstall the app first with sv_uninstall_addon(slug='local_ejemplo')."}
```

### `sv_install_addon` / `sv_rebuild_addon`

La vista previa gana `privileges` (data-model.md). Si cambia antes de
confirmar: el mismo rechazo `preview_outdated` que ya da `sv_install_addon`
por versión, con la pista al día («the store version or the app's
privileges changed»). El token solo guarda una huella del estado, así que
no se dice cuál de los dos cambió. El resto de la respuesta, igual.

### `sv_update_addon` (convergencia 2, T053)

Como `sv_rebuild_addon`: la vista previa gana `privileges` (`store`,
`installed`, `elevated` y, para `local_*`, `declared_in_folder`) y el token
ata `{"version_latest", "privileges"}`. Para `local_*`, `store_copy_stale`
sin token en la vista previa y al confirmar, bajo el candado de `/addons`.

### `store_copy_stale`, `ignored_config_files` y `folder_busy` (convergencia 2)

- `store_copy_stale` (instalar, actualizar y reconstruir una `local_*`): si
  cualquier entrada de `/addons`, a cualquier profundidad y con la raíz,
  tiene una fecha posterior al inicio de la última recarga lanzada por
  Hermes menos 2 s (T051); `reason` dice qué cambió lo último.
- `ignored_config_files`: `{"files": [{"path", "reason"}], "count", "note"}`
  en la vista previa, con los `config.*` que el Supervisor salta (T055); no
  bloquean. Desde la convergencia 4 (T062), solo los que salta seguro: los
  que no puede leer como YAML o JSON, los que no son un mapa y los que no
  tienen `name`. Uno con `name` que su esquema rechazaría va con los que
  tumban la recarga (puede tumbarla). Los que tumban la recarga (una excepción que el Supervisor no
  captura) no salen aquí: `store_copy_stale` con su ruta y la pista de
  arreglarlos o quitarlos (convergencia 3, T059).
- Convergencia 3: `store_copy_stale` también si `GET /jobs/info` tiene un
  job de recarga de la tienda sin terminar (`store_manager_reload`,
  `store_manager_add_repository`, `store_manager_update_repositories`, a
  cualquier profundidad del árbol) o no responde (T058). Las cuatro vías de
  recarga marcan antes la raíz de `/addons` (`os.utime`, fecha mayor que la
  que tenía y que la hora actual) y solo anotan si la marca se puso y no
  había ni hay una recarga en curso; la marca anotada (valor exacto en ns)
  no cuenta como cambio (T057).
- Convergencia 4 (T060): `store_copy_stale` también si el recorrido de
  `/addons` (el que imita a `get_latest_mtime`) encuentra algo que puede
  hacer fallar el del Supervisor: una ruta que, medida bajo
  `/data/apps/local/`, pase de `TOPE_RUTA_EN_EL_SUPERVISOR` (3840 bytes:
  `PATH_MAX` 4096 menos 256 de margen), un symlink roto, en bucle, que pasa
  por un fichero o que apunta fuera de `/addons`, o cualquier error al
  listar o mirar una entrada; `reason` dice cuál y dónde.
  `fs_write_file_in_folder`, `fs_create_dir_in_folder` y
  `fs_move_in_folder` responden en `addons`, sin token, `{"error":
  "path_too_long", "path", "detail", "hint"}` si la ruta (o, al mover una
  carpeta, lo que cuelga de ella) pasa de ese tope.
- `folder_busy`: `{"error": "folder_busy", "folder", "detail"}` (y `slug` en
  las `sv_*`) si el candado de la carpeta no se consigue en
  `ESPERA_MAX_CANDADO_S` (15 s); el token no se gasta (T056).

## Errores al cliente

Siempre `{"error": "<código>", …}` con `detail` o `hint` en inglés que dice
la regla, nunca el contenido de un fichero.
