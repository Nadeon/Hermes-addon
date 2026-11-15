# Modelo de datos: control de Core y del Supervisor (022)

Nada nuevo se guarda en disco salvo los tokens de confirmación que ya guarda
`security.py`.

## Vista previa de interrupción (común a las tools que cortan algo)

```text
{
  "action": "start_core" | "rebuild_core" | "restart_supervisor" | "repair_supervisor",
  "interrupts": {
    "stops": [str],          # p. ej. ["Home Assistant Core"], ["Supervisor API", "Hermes' connection to Core"]
    "keeps_running": [str],  # p. ej. ["apps (add-ons)", "Home Assistant Core"]
    "duration": str          # "about 1-5 minutes", "about 30-90 seconds", "several minutes"
  },
  "hermes": str,             # qué le pasa a Hermes y cómo se recupera
  "warnings": [str],
  "blocked": str | null      # solo sv_rebuild_core (escrituras sin validar)
  ...                        # campos propios de cada tool (abajo)
}
```

## `sv_start_core`

| Paso | Lectura | Resultado |
|---|---|---|
| Estado | `GET /core/stats` (timeout 15 s) | responde → `running`; error del Supervisor `HomeAssistantNotRunningError` (`error_key` `homeassistant_not_running_error`, mensaje «Home Assistant is not running», `exceptions.py` de 2026.11.0) → `stopped`; otro error → `unknown` |
| Versión | `GET /core/info` → `version` | `null` si falla |
| Escrituras sin validar | `check_restart_allowed_sync()` | `warnings` (no bloquea) |

Vista previa: lo común + `core_state`, `version`. `running` → `{"error":
"already_running", "detail": …}` sin token; también al confirmar (token
completado sin éxito). Atados: `{}`; estado: `{"core_state": …}`.
Ejecución: `POST /core/start`, `timeout_seconds=600`.

## `sv_rebuild_core`

Argumentos: `safe_mode: bool = False` (otro tipo → `invalid_argument`).
Vista previa: lo común + `version`, `safe_mode` y su explicación («Core starts
in safe mode: custom integrations and YAML are not loaded»), `blocked` si
`check_restart_allowed_sync()` lo prohíbe (con la pista de
`sv_check_core_config`). Con `blocked`, el token se emite (como
`sv_restart_core`) pero la confirmación se rechaza con el motivo sin llamar.
Atados: `{"safe_mode"}`. Ejecución: `POST /core/rebuild` con
`{"safe_mode": <bool>}`, `timeout_seconds=600`.

## `sv_set_core_options`

| Clave | Tipo | Aviso |
|---|---|---|
| `boot` | bool | `false`: «after a host reboot Home Assistant stays stopped; start it with sv_start_core» |
| `watchdog` | bool | `false`: «the Supervisor will not restart Home Assistant if it crashes» |
| `backups_exclude_database` | bool | `true`: «backups will not include the recorder database (history)» |
| `duplicate_log_file` | bool | «applies the next time Core starts or is rebuilt» |
| `audio_input`, `audio_output` | str o `null` (≤ 128) | «applies the next time Core starts or is rebuilt» |

Rechazadas (`not_allowed`, con `allowed` y `reason`): `image`,
`refresh_token`, `port`, `ssl` (research R-3). Otra clave, vacío o tipo
equivocado → `invalid_argument` con `field`.

Vista previa:

```text
{"action": "set_core_options",
 "changes": {<clave>: {"current": …, "new": …}},
 "unchanged": [<clave>],
 "restart_needed": false,
 "warnings": [str]}
```

`changes` vacío → `no_changes` sin token. Atados: `{"options": <normalizado>}`;
estado: los valores actuales de las claves pedidas. Ejecución:
`POST /core/options` con solo las claves de `changes`.

## `sv_reload_supervisor`

Sin argumentos ni token. `POST /supervisor/reload` (timeout 120 s) →
`{"result": "ok", "note": "versions, secrets and system evaluation reloaded"}`.

## `sv_restart_supervisor` y `sv_repair_supervisor`

Lectura previa: `GET /jobs/info` → `jobs` con `done: false` (también hijos).
Alguno → `{"error": "jobs_in_progress", "jobs": [{"name", "progress",
"stage"}], "detail": …}` sin token; también al confirmar. Si `/jobs/info`
falla → `error` sin token (sin saber si hay jobs, no se reinicia: fail-closed).

Vista previa (restart): lo común con `stops` = Supervisor API y conexión de
Hermes con Core; `keeps_running` = Core y apps; `duration` ≈ 30–90 s;
`version` (`/supervisor/info`). Atados: `{}`; estado: `{"jobs": []}`.
Ejecución: `POST /supervisor/restart` (timeout 60 s); conexión cortada sin
`status` → `{"status": "started", "verify_with": "sv_get_supervisor_info"}`.

Vista previa (repair): `steps` = las cinco fases de `Core.repair` del
Supervisor 2026.11.0; `deletes` = «stopped containers, unused images, build
cache, unused volumes»; `downloads` = «missing images of plugins, apps and
Core»; `duration` = «several minutes». Ejecución: `POST /supervisor/repair`,
`timeout_seconds=900`; vence → `status: "started"`, `verify_with:
"sv_get_resolution"`.

## `sv_set_supervisor_options`

| Clave | Validación | Aviso |
|---|---|---|
| `timezone` | `^[A-Za-z][A-Za-z0-9_+\-/]{0,63}$` | «also changes the host time zone; Home Assistant's own time zone is a Core setting» |
| `country` | `^[A-Z]{2}$` | — |
| `logging` | `debug`, `info`, `warning`, `error`, `critical` | `debug`: «very verbose Supervisor log» |
| `auto_update` | bool | `false`: «once a newer Supervisor exists, installing or updating apps and updating Core are blocked until it is updated» |
| `diagnostics` | bool | `true`: «crash reports are sent to a third party (Sentry)» |

Rechazadas (`not_allowed`): `channel`, `debug`, `debug_block`,
`detect_blocking_io`, `feature_flags`, `addons_repositories`, `wait_boot`.
Misma forma de vista previa, `no_changes`, atados y estado que
`sv_set_core_options` (lectura de `/supervisor/info`). Ejecución:
`POST /supervisor/options` con las claves de `changes`.

## `sv_apply_resolution_suggestion`

Argumento: `suggestion_uuid` (32 hex o UUID con guiones; otro → 
`invalid_argument`, como `sv_dismiss_resolution_suggestion`).

Lecturas: `GET /resolution/info` (sugerencia y sus issues por `context` y
`reference`); según el par, `GET /backups`, `GET /addons/{reference}/info`.

Tabla de traducción (fuente: `resolution/fixups/*.py` del Supervisor
2026.11.0; `allowed` = se emite token):

| `type` / `context` | `effect` | `interrupts` | `duration` | `reversible` | `allowed` |
|---|---|---|---|---|---|
| `clear_port_config` / `addon` | removes the conflicting port mapping and starts the app if it is stopped (a running app is not restarted and keeps the old mapping until its next restart) | nothing (a stopped app is started) | seconds | yes | sí |
| `disable_boot` / `addon` | the app no longer starts at boot | nothing | — | yes | sí |
| `execute_rebuild` / `addon` | rebuilds the app container | the app | minutes | yes | sí |
| `execute_remove` / `addon` | uninstalls the app and deletes its data | the app, permanently | — | **no** | sí |
| `execute_repair` / `addon` | downloads the app image again | nothing | minutes | yes | sí |
| `execute_restart` / `addon` | restarts the app | the app | seconds | yes | sí |
| `execute_start` / `addon` | starts the app | nothing | seconds | yes | sí |
| `execute_rebuild` / `core` | rebuilds the Home Assistant Core container | Home Assistant | 1–5 minutes | yes | sí |
| `execute_reload` / `mount` | remounts the mount | the mount | seconds | yes | sí |
| `execute_remove` / `mount` | removes the mount (remote data is kept) | the mount | — | no | sí |
| `move_local_data` / `mount` | moves local data out of the mount target and remounts | the mount | minutes | no | sí |
| `execute_rebuild` / `plugin` | rebuilds the plugin container | the plugin | seconds | yes | sí |
| `execute_reload` / `store` | reloads the store repository (internet) | nothing | seconds | yes | sí |
| `execute_remove` / `store` | removes the store repository | nothing | — | no | sí |
| `execute_reset` / `store` | clones the store repository again (internet) | nothing | seconds | yes | sí |
| `clear_full_backup` / `system` | deletes all full backups except the 2 newest, each from ALL its locations | nothing | — | **no** | sí |
| `create_full_backup` / `system` | creates a full backup | running apps with a cold backup mode, while each is copied; uses disk | minutes | yes | sí |
| `enable_ntp` / `system` | starts the time sync service | nothing | — | yes | sí |
| `execute_reboot` / `system` | reboots the host | everything, Hermes included | minutes | — | sí |
| `execute_rebuild` / `system` | rebuilds every container with a Docker config issue | the rebuilt containers | minutes | yes | sí (salvo Hermes) |
| `execute_reset` / `system` | clears the failed state of a systemd unit | nothing | — | yes | sí |
| `execute_restart` / `system` | restarts a systemd unit | that unit | seconds | yes | sí |
| `adopt_data_disk` / `system` | relabels data disks and reboots | everything | minutes | no | **no** (`not_allowed`) |
| `rename_data_disk` / `system` | relabels a conflicting data disk | — | — | no | **no** (`not_allowed`) |
| `execute_stop`, `execute_update`, `registry_login` (cualquier contexto) y cualquier otro par | — | — | — | — | **no** (`no_fixup`) |

Un par con `type` y `context` conocidos por el `SuggestionType`/`ContextType`
de 2026.11.0 pero fuera de la tabla → `no_fixup`; un `type` o `context` que
2026.11.0 no conoce → `unknown_effect`.

Vista previa:

```text
{"action": "apply_resolution_suggestion",
 "suggestion": {"uuid", "type", "context", "reference", "auto"},
 "issues": [{"uuid", "type", "context", "reference"}],
 "effect": str, "interrupts": str, "duration": str | null, "reversible": bool | null,
 "details": {                    # solo si aplica
   "backups_to_delete": [{"slug", "name", "date", "size",
                          "locations": [{"location", "kind", "where", "off_host"}]}],
   "off_host_copies_deleted": bool,
   "containers_to_rebuild": [{"context", "reference"}],
   "app": {"slug", "name", "state"}
 },
 "also_auto_applied": [{"uuid", "type", "context"}],   # otras sugerencias con auto: true
 "warnings": [str],
 "verify_with": "sv_get_resolution"}
```

`also_auto_applied`: el Supervisor, tras aplicar el fixup, lanza
`healthcheck()`, que ejecuta `run_autofix()` (`resolution/module.py`): las
demás sugerencias con `auto: true` pueden aplicarse también. La vista previa
lista las que hay ahora y avisa de que no es la lista completa: el healthcheck
ejecuta antes `check_system()`, que puede crear sugerencias automáticas nuevas
(T033). Si alguna de las conocidas apunta a Hermes, `targets_hermes`.

`clear_full_backup` (T031): `BackupManager.remove` sin `locations` borra cada
backup de todas sus ubicaciones. Cada elemento de `backups_to_delete` lleva
sus `locations` (de `/backups`: `None` → `local`; un nombre → montaje de red,
`off_host: true`). Si alguno está fuera del host, el primer aviso lo dice en
mayúsculas. Sin `locations` legible no hay token (fail-closed). `/backups` no
enseña la carpeta `.cloud_backup` (subidas a Home Assistant Cloud), que el
fixup sí cuenta y borra: la vista previa lo avisa siempre.

`targets_hermes`: contexto `addon` con `_es_hermes(reference)`, o
`execute_rebuild`/`system` con Hermes en `containers_to_rebuild`.
Atados: `{"suggestion_uuid"}`; estado: `{"type", "context", "reference",
"backups_to_delete": [[slug, [locations]]], "containers_to_rebuild": [...],
"also_auto_applied": [uuids]}`. Al confirmar:
releer y repetir los rechazos; estado distinto → `suggestion_changed`.
Ejecución: `POST /resolution/suggestion/{uuid}` (timeout 900 s; vence →
`status: "started"`). Respuesta: `{"result": "ok", "effect", "verify_with"}`.

## Errores

`{"error": <código>, "detail": str, …}`: `invalid_argument` (`field`),
`not_allowed` (`field`, `allowed`, `reason`), `already_running`,
`no_changes`, `jobs_in_progress` (`jobs`), `suggestion_not_found`,
`no_fixup`, `unknown_effect`, `targets_hermes`, `suggestion_changed`,
`invalid_confirmation_token`, `supervisor_request_failed` (texto del
Supervisor por `redact_secrets`, recortado a 500 caracteres).

## Eventos de log

`system_control_preview`, `system_control_done`, `system_control_rejected`
(campos: `tool`, `route`, `keys` —nombres de claves, nunca valores—,
`outcome`, `code`) y `resolution_fix_preview`, `resolution_fix_done`,
`resolution_fix_rejected` (`suggestion_type`, `context`, `outcome`, `code`;
nunca `reference`).

## Entradas de la tabla que cambian (14)

| Clave | Antes | Después | Familia | CAP |
|---|---|---|---|---|
| `POST /core/start` | deny (022) | `dedicated` → `sv_start_core` | `system_control` | CAP-084 |
| `POST /core/rebuild` | deny (022) | `dedicated` → `sv_rebuild_core` | `system_control` | CAP-084 |
| `POST /core/options` | deny (022) | `dedicated` → `sv_set_core_options` | `system_control` | CAP-084 |
| `POST /supervisor/reload` | deny (022) | `dedicated` → `sv_reload_supervisor` | `system_control` | CAP-084 |
| `POST /supervisor/restart` | deny (022) | `dedicated` → `sv_restart_supervisor` | `system_control` | CAP-084 |
| `POST /supervisor/repair` | deny (022) | `dedicated` → `sv_repair_supervisor` | `system_control` | CAP-084 |
| `POST /supervisor/options` | deny (022) | `dedicated` → `sv_set_supervisor_options` | `system_control` | CAP-084 |
| `POST /resolution/suggestion/{suggestion}` | deny (022) | `dedicated` → `sv_apply_resolution_suggestion` | `resolution_fixes` | CAP-087 |
| `GET /core/stats` | deny (022) | `read` «CPU, memoria, red y disco del contenedor de Core; solo lee» | `generic_commands` | CAP-084 |
| `GET /supervisor/stats` | deny (022) | `read` «CPU, memoria, red y disco del contenedor del Supervisor; solo lee» | `generic_commands` | CAP-084 |
| `POST /host/reload` | deny (022) | `confirm` «refresca la información del host; no corta nada» | `generic_commands` | CAP-084 |
| `POST /resolution/check/{check}/run` | deny (022) | `confirm` «ejecuta ya un chequeo del centro de resolución» | `generic_commands` | CAP-087 |
| `POST /resolution/check/{check}/options` | deny (022) | `confirm` «activa o desactiva un chequeo (`enabled`); desactivarlo oculta ese problema» | `generic_commands` | CAP-087 |
| `POST /resolution/healthcheck` | deny (022) | `confirm` «relanza todos los chequeos y puede aplicar los arreglos automáticos del Supervisor» | `generic_commands` | CAP-087 |

Sin cambios, con test: `POST /core/stop` y `/homeassistant/*` (`deny`); las
rutas de CAP-091, CAP-092 y CAP-094 (research R-8).

## Familias

| Nombre | Desde | Desactivable | Módulos |
|---|---|---|---|
| `system_control` | 1.2.0 | sí | `system_control` |
| `resolution_fixes` | 1.2.0 | sí | `resolution_fixes` |
