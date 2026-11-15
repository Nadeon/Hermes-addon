# Modelo de datos: carpetas /addons y /share (034)

No hay datos persistentes nuevos: solo los tokens de confirmación de siempre
(`/data/confirmations/`, con `state_hash` cuando la tool pasa `estado`).

## Carpeta

| Campo | `addons` | `share` |
|---|---|---|
| Raíz (defecto) | `/addons` (`HERMES_ADDONS_BASE`) | `/share` (`HERMES_SHARE_BASE`) |
| Alias absoluto admitido | `/addons/…` | `/share/…` |
| Nombre en un backup parcial (v1) | `addons/local` | `share` |
| Aviso en las vistas previas | sí (FR-018) | no |
| Comprobación de apps locales | sí (FR-019) | no |
| Puntos de montaje posibles | no (se comprueban igual) | sí (`/share/<nombre>`) |

## Huella (estado atado al token)

```text
fichero ≤ 64 MiB   {"kind": "file", "sha256": "<64 hex>"}
fichero > 64 MiB   {"kind": "file", "size": N, "mtime_ns": N, "ino": N}
symlink            {"kind": "symlink", "target": "<destino literal>"}
ausente            {"kind": "absent"}
carpeta            {"kind": "dir", "sha256": "<de la lista canónica>", "entries": N}
                   lista canónica: [[ruta_rel_posix, tipo, tamaño, mtime_ns], …] ordenada
```

El estado completo de cada tool (lo que se pasa a `estado=`):

| Tool | `estado` |
|---|---|
| `fs_write_file_in_folder` | `{"target": huella(path)}` |
| `fs_create_dir_in_folder` | `{"target": huella(path)}` (tiene que ser `absent`) |
| `fs_move_in_folder` | `{"src": huella(src), "dst": huella(dst)}` |
| `fs_delete_in_folder` | `{"target": huella(path)}` |
| `sv_install_addon` | `{"version_latest": …, "privileges": bloque}` |
| `sv_rebuild_addon` | `{"privileges": bloque}` |

En `addons`, el resultado de la comprobación de apps instaladas NO va en el
estado: se repite entera al confirmar (FR-017), que es más estricto.

## Argumentos atados (inventario de la 033)

| Tool | Argumento | Clasificación |
|---|---|---|
| `fs_write_file_in_folder` | `folder`, `path` (normalizada), `content` | atado (`content` omitible al confirmar) |
| `fs_create_dir_in_folder` | `folder`, `path` | atado |
| `fs_move_in_folder` | `folder`, `src`, `dst` | atado |
| `fs_delete_in_folder` | `folder`, `path`, `recursive` | atado |

## Recuento de una carpeta (vista previa de borrar y mover)

```json
{"files": 12, "dirs": 3, "symlinks": 0, "total_bytes": 40960,
 "sample": ["Dockerfile", "config.yaml", "rootfs/run.sh", "…"],
 "sample_truncated": false}
```

`total_bytes` suma el tamaño de los ficheros regulares (no sigue symlinks).
La muestra son las 20 primeras rutas relativas en el orden de la lista
canónica.

## Índice de apps locales

```text
{"local_<slug>": {"dir": "<ruta relativa a /addons de la carpeta de la app>",
                  "config": "<ruta relativa del config.*>"}}
ilegibles: ["<ruta relativa de cada config.* sin slug o que no se puede leer>"]
```

Se construye recorriendo la raíz de `addons` con las reglas de
`store/data.py` (R-4). Instaladas: `{a["slug"] for a in GET /addons → addons
if slug.startswith("local_")}`. Huérfanas: instaladas `local_*` que no están
en el índice.

## Bloque `privileges`

```json
{
  "store": {"apparmor": true, "auth_api": false, "docker_api": false,
            "full_access": false, "hassio_api": true, "hassio_role": "default",
            "homeassistant_api": false, "host_network": false, "host_pid": false,
            "ingress": true, "rating": 6, "signed": false},
  "installed": {"...": "solo sv_rebuild_addon: campos de /addons/{slug}/info"},
  "declared_in_folder": {"config": "ejemplo/config.yaml",
                         "map": [{"type": "share", "read_only": false}],
                         "privileged": [], "devices": [], "ports": {},
                         "note": "The Supervisor uses its own copy until the store is reloaded."},
  "elevated": ["map:share (read-write)"]
}
```

Si una fuente no se pudo leer, su clave vale `null` y hay
`unavailable: {"store": "<motivo redactado>"}`. Si no hay ninguna fuente,
`privileges: null` con `privileges_unavailable`.

## Errores (sin token)

`invalid_argument`, `folder_unavailable`, `traversal`, `blacklisted` (solo
leer), `not_found`, `is_directory`, `not_a_directory`, `already_exists`,
`destination_exists`, `destination_parent_missing`, `invalid_destination`,
`root_protected`, `mount_point`, `directory_not_empty`,
`too_large_to_preview`, `installed_app`, `installed_check_failed`,
`installed_check_inconclusive`.

Al confirmar, además: los de `security.py` (token caducado, usado, no casa)
y `ESTADO_CAMBIADO` (con `preview_outdated: true` y la pista de pedir otra
vista previa), `io_error` y `partial`.
