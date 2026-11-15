# Modelo de datos: actualizaciones del sistema (015)

Nada se guarda en disco salvo lo que ya guardan los tokens de confirmación
(`security.py`) y los jobs en vuelo (`pending_jobs.json` de `tools/addons.py`).

## Actualización disponible (`sv_list_available_updates`, `sv_check_for_updates`)

| Campo | Origen | Notas |
|---|---|---|
| `type` | `update_type` de `/available_updates`, o `plugin` | `core`, `os`, `supervisor`, `addon`, `plugin` |
| `name` | `name` (apps) o fijo (`Home Assistant Core`, `Home Assistant Operating System`, `Home Assistant Supervisor`, `<plugin> plugin`) | texto de terceros en las apps |
| `slug` | apps: de `panel_path` (`/update-available/<slug>`) contrastado con `/supervisor/info` → `addons[].slug`; plugins: el nombre | `null` en core, os, supervisor |
| `installed_version` | `/core/info`, `/os/info`, `/supervisor/info` (y sus `addons[]`), `/{plugin}/info` | `null` si la lectura falla |
| `latest_version` | `version_latest` | |
| `update_with` | `sv_update_core`, `sv_update_os`, `sv_update_supervisor`, `sv_update_addon`, `"sv_call_api POST /<plugin>/update"`, o `null` | `null` solo para Hermes |
| `note` | opcional | Hermes: «update Hermes from the Home Assistant UI»; plugins: «the Supervisor updates plugins automatically and before a Core update» |

Sobre: `{count, items, truncated}` más `auto_update` (del Supervisor), `channel`
y `_third_party_text` (`name` de las apps). Orden: supervisor, core, os,
plugins, apps (el orden en que conviene actualizar).

Lecturas que fallan: `partial: true` y `unavailable: [<ruta>]`; nunca una
lista vacía como si no hubiera actualizaciones.

## Vista previa de `sv_update_core` / `sv_update_os` / `sv_update_supervisor`

```text
{
  "action": "update_core" | "update_os" | "update_supervisor",
  "component": "core" | "os" | "supervisor",
  "from_version": str,
  "to_version": str,
  "downgrade": bool,
  "release_notes": {
    "available": bool,             # false en los tres: HA no tiene notas en local (R-4)
    "text": str | null,            # solo OS: el aviso de reinicio que da su entidad
    "reason": str | null,          # por qué no hay notas
    "release_url": str | null      # del estado de la entidad update, si Core responde
  },
  "backup": {
    "will_create": bool,
    "possible": bool,
    "kind": str | null,            # "partial backup of Home Assistant Core (no apps)"
    "name": str | null,            # "core_<from_version>"
    "location": str | null,        # "default Supervisor backup location"
    "exclude_database": bool | null,
    "hint": str | null             # OS: crear uno antes con sv_create_backup_full/partial
  },
  "restarts": {
    "components": [str],           # ["core"], [], ["supervisor"]
    "description": str,
    "after": str | null            # OS: "reboot the host with sv_reboot_host to apply it"
  },
  "system_health": {
    "unhealthy": [str], "unsupported": [str],
    "issues": [{"type": str, "context": str}],
    "unavailable": bool
  },
  "config_check": {"result": "ok" | "error" | "timeout" | "unavailable", "details": str | null},   # solo Core
  "plugins_to_update_first": [str],   # solo Core, con auto_update activo
  "blocked": [{"code": str, "message": str}],
  "warnings": [str]
}
```

Códigos de `blocked` (FR-004):

| Código | Tools | Condición leída | Del Supervisor |
|---|---|---|---|
| `unhealthy` | core, os | `/resolution/info` → `unhealthy` no vacío | `HEALTHY` |
| `supervisor_update_pending` | core, os | `/supervisor/info` → `update_available` | `SUPERVISOR_UPDATED` |
| `plugins_outdated` | core | algún `/{plugin}/info` con `update_available` y `auto_update` del Supervisor `false` | `PLUGINS_UPDATED` |
| `low_disk_space` | core | `/host/info` → `disk_free` < 2 (GB) | `FREE_SPACE` |
| `reboot_pending` | os | `/os/info` → `version_pending == to_version` | `HassOSUpdatePendingRebootError` |
| `config_invalid` | core | `POST /core/check` responde error | regla de Hermes |
| `config_check_failed` | core | `POST /core/check` vence (120 s) o no responde | regla de Hermes |

Errores sin vista previa (sin token, sin llamar a la ruta de actualización):
`invalid_argument`, `already_installed` (`to_version == from_version`),
`no_update_available` (Supervisor sin actualización; Core/OS sin `version` y
sin `version_latest` distinta), `not_haos` (`/os/info` 404),
`versions_unavailable` (no se pudo leer la versión actual o la de destino).

`warnings` fijos: «the Supervisor also checks internet access when it runs»
(core, os); `downgrade` explicado si `to_version < from_version` (comparación
con `packaging.version` si las dos son versiones válidas; si no, `null` y un
aviso de que no se pudo comparar).

### Argumentos atados al token

`{"version": <arg>, "backup": <arg>, "_from_version": <leída>,
"_to_version": <resuelta>}` (core); `{"version", "_from_version",
"_to_version"}` (os); `{"_from_version", "_to_version"}` (supervisor).

## Resultado de la ejecución

| Tool | Petición | Respuesta |
|---|---|---|
| `sv_update_core` | `POST /core/update` `{version, backup, background: true}`, espera 60 s | `{job_id, status: "running", poll_with: "sv_get_job_status", from_version, to_version}`; sin `job_id`: `{result: "ok", …}` |
| `sv_update_os` | tarea de fondo `POST /os/update` `{version}`, espera 1800 s; búsqueda de `os_manager_update` 10 s | `{job_id, status: "running", poll_with, after: "reboot…"}` o `{status: "started", verify_with: "sv_get_os_info"}` |
| `sv_update_supervisor` | tarea de fondo `POST /supervisor/update`, espera 1800 s; búsqueda de `supervisor_update` 10 s | `{job_id, status: "running", poll_with, note: "the job disappears when the Supervisor restarts; verify with sv_get_supervisor_info"}` o `{status: "started", verify_with: "sv_get_supervisor_info"}` |

`_track_job(job_id, {"op": "update_<component>", "from": …, "to": …})`.
Evento de log `system_update_started` (tool, componente, versiones, job
encontrado o no) y `system_update_finished` / `system_update_failed` desde la
tarea de fondo (error redactado y recortado a 500 caracteres).

## Entidad `update` (`ha_list_updates`)

| Campo | Origen |
|---|---|
| `entity_id` | estado |
| `title`, `installed_version`, `latest_version`, `skipped_version`, `in_progress`, `update_percentage`, `auto_update`, `release_url`, `device_class` | atributos del estado |
| `release_summary` | atributo, recortado a 300 caracteres (texto de terceros) |
| `state` | `on` (hay actualización), `off` |
| `supports` | `supported_features`: 1 `install`, 2 `specific_version`, 4 `progress`, 8 `backup`, 16 `release_notes` (`UpdateEntityFeature` de Core 2026.11.1) |
| `platform` | registro (`config/entity_registry/get_entries`) |
| `install_with` | `ha_install_update`, o la tool de FR-014, o `null` (Hermes) |

Sobre `{count, items, truncated}` y `_third_party_text`
(`title`, `release_summary`).

## Vista previa de `ha_install_update`

```text
{
  "action": "install_update",
  "entity_id": str, "title": str | null, "platform": str | null,
  "from_version": str, "to_version": str, "downgrade": bool | null,
  "release_notes": {"available": bool, "text": str | null, "truncated": bool,
                    "release_summary": str | null, "release_url": str | null},
  "backup": {"requested": bool, "supported": bool,
             "note": "the integration <platform> makes the backup; how depends on it"},
  "warnings": [str],            # firmware: "do not power off the device"
  "_third_party_text": {...}
}
```

Atados al token: `{"entity_id", "version", "backup", "_from_version",
"_to_version"}`.

Encaminamiento (sin token):
`{"error": "use_dedicated_tool", "tool": "sv_update_core", "arguments":
{"version": …, "backup": …}, "detail": …}`; OS: `arguments: {"version"}` y,
si se pidió `backup`, nota de que `sv_update_os` no hace backup; Supervisor:
`arguments: {}`; app: `sv_update_addon` con `{"slug"}`; Hermes:
`{"error": "self_update_not_supported", "detail": …}` (texto de la 009).

## Entradas de la tabla que cambian (FR-016)

Formato de la 011: `E(categoría, motivo, familia, tool=…, cap=…)`. Familia de
todas: `system_updates`.

| Clave | Antes | Después | CAP |
|---|---|---|---|
| `update/release_notes` | `deny` «pendiente de tool dedicada (spec 015)» | `dedicated` «cubierto por ha_get_update_release_notes» | CAP-064 |
| `hassio/update/core` | `dedicated` → `ha_call_service` (familia `services`) | `dedicated` «cubierto por sv_update_core (la misma actualización por el Supervisor, con vista previa)» | — (cubierto) |
| `("GET", "/available_updates")` | `deny` pendiente (015) | `dedicated` «cubierto por sv_list_available_updates» | CAP-080 |
| `("POST", "/reload_updates")` | `deny` pendiente (015) | `dedicated` «cubierto por sv_check_for_updates (que usa /refresh_updates: recarga también la tienda)» | CAP-080 |
| `("POST", "/refresh_updates")` | `deny` alias (clase B) | `dedicated` «cubierto por sv_check_for_updates» | — (clase B) |
| `("POST", "/core/update")` | `deny` pendiente (015) | `dedicated` «cubierto por sv_update_core» | CAP-080 |
| `("POST", "/os/update")` | `deny` pendiente (015) | `dedicated` «cubierto por sv_update_os» | CAP-080 |
| `("POST", "/supervisor/update")` | `deny` pendiente (015) | `dedicated` «cubierto por sv_update_supervisor» | CAP-080 |

Sin cambios: `hassio/update/addon` (`sv_update_addon`), `hassio/update/config/*`
(031), `("POST", "/homeassistant/update")` y
`("GET", "/supervisor/available_updates")` (alias, `deny`),
`("POST", "/{audio,cli,dns,multicast,observer}/update")` (`confirm`, 022).

## Familia

`Familia("system_updates", "Check for and install updates of Core, OS,
Supervisor and update entities.", "1.2.0", True, ("system_updates",
"update_entities"))`. El tramo 1 la crea con `system_updates`; el tramo 3
añade `update_entities` cuando crea el módulo.
