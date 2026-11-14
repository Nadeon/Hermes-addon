# Contrato: tools de montajes y ajustes de backup (019)

Familia `mounts` (módulos `mounts` y `backup_settings`), salvo `location`, que
se añade a dos tools de la familia `backups`. Descripciones al cliente en
inglés; comentarios en español. Todas pasan por el tope central de respuesta.

## Resumen

| Tool | Ruta(s) | Modifica | Token | Anotaciones | Módulo |
|---|---|---|---|---|---|
| `sv_list_mounts()` | GET `/mounts` | no | no | readOnly, idempotente | `mounts` |
| `sv_create_mount(...)` | GET `/mounts`; POST `/mounts` | sí | **sí** | destructive, no idempotente (prefijo `sv_create_`) | `mounts` |
| `sv_update_mount(...)` | GET `/mounts`, GET `/backups`; PUT `/mounts/{name}` | sí | **sí** | destructive, idempotente | `mounts` |
| `sv_delete_mount(name)` | GET `/mounts`, GET `/backups`; DELETE `/mounts/{name}` | sí | **sí** | destructive (prefijo `sv_delete_`), idempotente | `mounts` |
| `sv_reload_mount(name)` | POST `/mounts/{name}/reload`; GET `/mounts` | sí (rearma) | no | ni readOnly ni destructive, idempotente | `mounts` |
| `sv_set_default_backup_mount(name)` | GET `/mounts`; POST `/mounts/options` | sí | **sí** | destructive, idempotente | `mounts` |
| `sv_get_backup_settings()` | GET `/backups/info`, GET `/mounts` | no | no | readOnly, idempotente | `backup_settings` |
| `sv_set_backup_settings(days_until_stale)` | GET `/backups/info`; POST `/backups/options` | sí | no | ni readOnly ni destructive, idempotente | `backup_settings` |
| `sv_reload_backups()` | POST `/backups/reload`; GET `/backups` | sí (relee) | no | ni readOnly ni destructive, idempotente | `backup_settings` |
| `sv_create_backup_full(name, password=None, location=None)` | POST `/backups/new/full` | sí | no | sin cambios | `backups` |
| `sv_create_backup_partial(..., location=None)` | POST `/backups/new/partial` | sí | no | sin cambios | `backups` |

Ninguna es de mundo abierto: el Supervisor habla con un NAS de la red local,
no con internet. Títulos: los generados por `title_for` («Create mount
(Supervisor)», «Set default backup mount (Supervisor)»…); no hace falta
ninguna palabra nueva en `_TITLE_WORDS`.

`_DESTRUCTIVE_EXACT` gana `sv_create_mount`, `sv_update_mount` y
`sv_set_default_backup_mount` (con comentario: piden token; crear uno de
backup puede pasar a ser el destino por defecto de todos los backups; editar
desmonta y puede quitar credenciales; el por defecto decide a dónde van los
safety backups). `sv_reload_mount`, `sv_set_backup_settings` y
`sv_reload_backups` no encajan en ningún prefijo y no son idempotentes por
prefijo: no necesitan entrada nueva salvo comprobarlo en el test.

## Firmas

```python
async def sv_list_mounts() -> object

async def sv_create_mount(
    name: str,
    type: str,
    usage: str,
    server: str,
    share: str | None = None,
    path: str | None = None,
    port: int | None = None,
    version: str | None = None,
    read_only: bool = False,
    username: str | None = None,
    password: str | None = None,
    confirmation_token: str | None = None,
) -> object

async def sv_update_mount(
    name: str,
    type: str | None = None,
    usage: str | None = None,
    server: str | None = None,
    share: str | None = None,
    path: str | None = None,
    port: int | None = None,
    version: str | None = None,
    read_only: bool | None = None,
    username: str | None = None,
    password: str | None = None,
    confirmation_token: str | None = None,
) -> object

async def sv_delete_mount(name: str, confirmation_token: str | None = None) -> object
async def sv_reload_mount(name: str) -> object
async def sv_set_default_backup_mount(name: str | None, confirmation_token: str | None = None) -> object

async def sv_get_backup_settings() -> object
async def sv_set_backup_settings(days_until_stale: int) -> object
async def sv_reload_backups() -> object
```

`version`: `"auto"` pide la negociación automática (se envía `null`) en las
dos tools. En `sv_update_mount`, `None` significa «no se toca»; en
`sv_create_mount`, `None` equivale a `"auto"`. Es la única diferencia entre
«no pasado» y «nulo» que hace falta (research R-4); se dice en la
descripción.

## Flujo en dos pasos (las cuatro con token)

1. Validar argumentos (FR-007). Inválido → `{error: "invalid_argument",
   detail: <regla>}` sin llamar a nada. Con nombre de tipo no admitido →
   `unsupported_mount_type`.
2. Leer el estado (`GET /mounts`, y `GET /backups` en editar y borrar).
   Errores de existencia (`mount_exists`, `mount_not_found`,
   `not_a_backup_mount`) → error sin token.
3. Sin `confirmation_token`: construir la vista previa (data-model), calcular
   `_estado` y devolver `create_confirmation_token(tool, args | {"_estado":
   huella}, preview=…)` **sin `omitibles`**.
4. Con `confirmation_token`: volver a leer el estado, recalcular la huella y
   `validate_confirmation_token(token, tool, args | {"_estado": huella})`. Si
   falla: `{error: <el de security>, hint: "Arguments or the mount changed
   since the preview; request a new preview."}`.
5. Ejecutar la petición; `complete_confirmation_token(success=…)`; leer de
   vuelta y responder (data-model). Errores del Supervisor: limpiar
   credenciales literales + `redact_secrets`; en fallos de montaje, `hint`
   con `sv_get_resolution`.

`args` contiene **todos** los argumentos de la firma salvo
`confirmation_token`, con los valores tal cual se recibieron (también `None`).

## Inventario de la 033 (`tests/test_confirmation_args_inventory.py`)

```python
"sv_create_mount": {a: A for a in ("name", "type", "usage", "server", "share", "path",
                                    "port", "version", "read_only", "username", "password")},
"sv_update_mount": {…los mismos…},
"sv_delete_mount": {"name": A},
"sv_set_default_backup_mount": {"name": A},
```

Y `test_recuento` sube en 4 (82 → 86 sobre la punta de la 033; el número
exacto depende de lo integrado). Comentario: la huella `_estado` también entra
en el hash, aunque no es un argumento.

## Log (R-10)

| Evento | Campos |
|---|---|
| `sv_list_mounts_ok` | `count` |
| `sv_create_mount_preview` / `_ok` / `_error` | `mount`, `type`, `usage`, `credentials`, `error_kind` (en error) |
| `sv_update_mount_preview` / `_ok` / `_error` | `mount`, `changed` (nombres), `credentials`, `error_kind` |
| `sv_delete_mount_preview` / `_ok` / `_error` | `mount`, `usage`, `affected_backups` (número) |
| `sv_reload_mount_ok` / `_error` | `mount` |
| `sv_set_default_backup_mount_preview` / `_ok` | `from`, `to` (nombres) |
| `sv_get_backup_settings_ok` | — |
| `sv_set_backup_settings_ok` | `days_until_stale`, `previous` |
| `sv_reload_backups_ok` | `backups_count` |
| `sv_create_backup_*_started` | lo de la 1.1.2 + `location` |

Nunca: `server`, `share`, `path`, `username`, `password`, el texto del error.

## Genéricas

`sv_read_api` y `sv_call_api` sobre cualquiera de las 9 rutas → `{error:
"use_dedicated_tool", tool: <la de data-model>}` sin llamar al Supervisor
(comportamiento de la 011 para `dedicated`).
