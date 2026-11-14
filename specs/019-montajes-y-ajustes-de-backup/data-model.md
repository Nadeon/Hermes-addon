# Modelo de datos: montajes de red y ajustes de backup (019)

No hay almacenamiento nuevo: Hermes no guarda montajes ni ajustes; los lee y
los escribe en el Supervisor. Lo único que se escribe en `/data` es el fichero
del token de confirmación de siempre, con el `action_hash` y sin argumentos.

## Montaje (lo que devuelve Hermes)

Lista permitida de claves (FR-001). Cualquier otra que mande el Supervisor se
descarta antes de devolver.

| Clave | Tipo | Origen | Notas |
|---|---|---|---|
| `name` | str | `to_dict` | `^[A-Za-z0-9_]+$` (Hermes acepta 1–64 al escribir) |
| `type` | str | `to_dict` | `cifs`, `nfs` o `disk` |
| `usage` | str \| null | `to_dict` | `backup`, `media`, `share` |
| `read_only` | bool | `to_dict` | |
| `server` | str | red | CIFS y NFS |
| `port` | int | red | solo si no es el del protocolo |
| `share` | str | CIFS | |
| `version` | str \| null | CIFS | `1.0`, `2.0` o `null` (automático) |
| `path` | str | NFS | ruta exportada |
| `uuid`, `filesystem` | str | `disk` | solo lectura |
| `state` | str \| null | API | estado de la unidad systemd (`active`, `failed`…) |
| `user_path` | str \| null | API | ruta dentro de los contenedores (`/backup/<n>`, `/media/<n>`, `/share/<n>`) |

**Nunca**: `username`, `password` (ni ninguna otra clave fuera de la lista).

## Argumentos de escritura de un montaje

| Argumento | Crear | Editar | Regla (FR-007) |
|---|---|---|---|
| `name` | obligatorio | obligatorio (no cambia) | `^[A-Za-z0-9_]{1,64}$` |
| `type` | obligatorio | opcional | `cifs` \| `nfs`; otro → `unsupported_mount_type` |
| `usage` | obligatorio | opcional | `backup` \| `media` \| `share` |
| `server` | obligatorio | opcional | 1–253, sin `/`, `\`, espacios ni control |
| `share` | obligatorio en CIFS | opcional | sin `/`, `\` ni control; solo CIFS |
| `path` | obligatorio en NFS | opcional | absoluto, sin control; solo NFS |
| `port` | opcional | opcional | entero 1–65535, no booleano |
| `version` | opcional | opcional | `1.0` \| `2.0` \| `auto` \| `None`; `auto` = automático (se envía `null`); al crear, `None` = automático; al editar, `None` = no se toca; solo CIFS |
| `read_only` | `False` | opcional | booleano; `True` no con `backup` |
| `username` | opcional | opcional | con `password`; solo CIFS; sin control; ≠ `***REDACTED***` |
| `password` | opcional | opcional | con `username`; ídem |

Al editar, la validación se aplica al **resultado de fundir** lo actual con lo
pasado (R-4), además de a cada argumento pasado. Cambiar `type` exige los
campos obligatorios del tipo nuevo entre los argumentos.

## Estado de las credenciales en la vista previa

| Valor | Cuándo |
|---|---|
| `"set"` | crear CIFS con `username` y `password` |
| `"none"` | crear CIFS sin ellas (invitado) |
| `"replaced"` | editar CIFS con `username` y `password` |
| `"removed_if_present"` | editar CIFS sin ellas (con `credentials_warning`) |
| ausente | NFS |

## Huella del estado (`_estado`, R-6)

Diccionario canónico que entra en el hash junto con los argumentos. Sin
secretos (el Supervisor no los devuelve y la lista permitida los descartaría).

| Tool | Contenido |
|---|---|
| `sv_create_mount` | `{"default_backup_mount": <str \| null>}` |
| `sv_update_mount` | `{"mount": <montaje actual sin state ni user_path>, "default_backup_mount": …}` |
| `sv_delete_mount` | `{"mount": …, "default_backup_mount": …, "affected_backups": [<slug>…] ordenados}` |
| `sv_set_default_backup_mount` | `{"default_backup_mount": …, "target_usage": <uso del montaje pedido \| null>}` |

`state` y `user_path` no entran: el estado de la unidad cambia solo (un NAS
que se duerme) y no altera lo que la acción hace.

## Vistas previas

### `sv_create_mount`

```json
{
  "action": "create_mount",
  "mount": {"name": "nas_backups", "type": "cifs", "usage": "backup",
            "server": "nas.local", "share": "backups", "version": null,
            "read_only": false},
  "credentials": "set",
  "becomes_default_backup_mount": true,
  "reloads_backups": true,
  "note": "The Supervisor mounts it while creating it; if the server cannot be reached, nothing is created. Credentials are never shown or returned."
}
```

### `sv_update_mount`

```json
{
  "action": "update_mount",
  "mount": "nas_backups",
  "changes": {"server": {"from": "nas.local", "to": "nas2.local"}},
  "credentials": "removed_if_present",
  "credentials_warning": "The Supervisor replaces the whole mount configuration and never returns credentials, so Hermes cannot keep them. If this mount uses a username and password, they will be removed unless you pass both.",
  "remount": true,
  "stops_being_default_backup_mount": false,
  "affected_backups": {"count": 3, "only_here": 3, "items": [{"slug": "…", "name": "…", "date": "…"}], "truncated": false},
  "note": "The Supervisor unmounts and mounts it again."
}
```

`affected_backups` solo aparece si el montaje era de uso `backup` y cambia el
uso o el destino (`type`, `server`, `share`, `path`, `port`).

### `sv_delete_mount`

```json
{
  "action": "delete_mount",
  "mount": {"name": "nas_backups", "type": "cifs", "usage": "backup", "server": "nas.local", "share": "backups", "state": "active"},
  "is_default_backup_mount": true,
  "default_after": null,
  "affected_backups": {"count": 3, "only_here": 2, "items": [], "truncated": false},
  "warning": "2 backups are stored only on this mount: they disappear from the Supervisor's list and cannot be restored from Home Assistant until a mount pointing to the same place is created again. The files stay on the server. New backups without a location (including Hermes safety backups) will go to local storage."
}
```

Para uso `media` o `share`: `warning` dice que su contenido deja de estar en
`user_path` para Home Assistant y los add-ons.

### `sv_set_default_backup_mount`

```json
{"action": "set_default_backup_mount", "from": "nas_backups", "to": null,
 "note": "Backups created without a location, including Hermes safety backups, will go to local storage."}
```

`items` de `affected_backups`: como mucho 20, ordenados por fecha
descendente; `truncated` dice si hay más.

## Respuestas

| Tool | Respuesta |
|---|---|
| `sv_list_mounts` | `{default_backup_mount, count, items: [Montaje], truncated}` |
| `sv_create_mount` / `sv_update_mount` (con token) | `{result: "ok", mount: Montaje, default_backup_mount}` |
| `sv_delete_mount` (con token) | `{result: "ok", deleted: <name>, default_backup_mount}` |
| `sv_reload_mount` | `{result: "ok", mount: Montaje}` |
| `sv_set_default_backup_mount` (con token) | `{result: "ok", default_backup_mount}` |
| `sv_get_backup_settings` | `{days_until_stale, default_backup_mount, backup_mounts: [{name, state}]}` |
| `sv_set_backup_settings` | `{result: "ok", days_until_stale, previous}` |
| `sv_reload_backups` | `{result: "ok", backups_count}` |
| `sv_create_backup_*` con `location` | lo de la 1.1.2 más `location` (lo pedido) |
| error | `{error: <código o mensaje redactado>, detail?, hint?}` |

## Ubicación de backup (`location`, FR-014)

`str | list[str] | None`. Cada valor: `.local` o `^[A-Za-z0-9_]{1,64}$`.
`.cloud_backup` → `invalid_argument`. Lista: 1 o más, sin repetidos. `None`:
la clave no se envía.

## Entradas de la tabla que pasan a `dedicated` (FR-015)

Familia `mounts`, `cap="CAP-083"`, motivo «cubierto por `<tool>`».

| Método | Ruta | Tool |
|---|---|---|
| GET | `/mounts` | `sv_list_mounts` |
| POST | `/mounts` | `sv_create_mount` |
| PUT | `/mounts/{mount}` | `sv_update_mount` |
| DELETE | `/mounts/{mount}` | `sv_delete_mount` |
| POST | `/mounts/{mount}/reload` | `sv_reload_mount` |
| POST | `/mounts/options` | `sv_set_default_backup_mount` |
| GET | `/backups/info` | `sv_get_backup_settings` |
| POST | `/backups/options` | `sv_set_backup_settings` |
| POST | `/backups/reload` | `sv_reload_backups` |

Tramo 1: las 6 de `/mounts`. Tramo 2: las 3 de `/backups`. Recuento de la
tabla del Supervisor: `dedicated` +9, `deny` −9.
