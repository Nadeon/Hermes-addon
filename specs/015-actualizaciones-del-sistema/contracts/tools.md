# Contratos: tools de actualizaciones del sistema (015)

Nombres, argumentos y descripciones al cliente en inglés; comentarios del
código en español. Las formas de las respuestas están en
[data-model.md](../data-model.md).

## Firmas (esquema de entrada MCP)

```text
# Módulo system_updates (familia system_updates)
sv_list_available_updates() -> object
sv_check_for_updates() -> object
sv_update_core(version: str | None = None, backup: bool = True, confirmation_token: str | None = None) -> object
sv_update_os(version: str | None = None, confirmation_token: str | None = None) -> object
sv_update_supervisor(confirmation_token: str | None = None) -> object

# Módulo update_entities (familia system_updates)
ha_list_updates(include_up_to_date: bool = False) -> object
ha_get_update_release_notes(entity_id: str) -> object
ha_install_update(entity_id: str, version: str | None = None, backup: bool = False, confirmation_token: str | None = None) -> object

# Existente (familia services): mismo esquema
ha_call_service(...)   # domain="update", service="install": preview["hint"] y,
                       # desde T051, los rechazos sin token de abajo
```

`sv_update_core` tiene `backup=True` por defecto (el Supervisor hace un backup
parcial de Core). `ha_install_update` tiene `backup=False`, el valor por
defecto de `update.install` en Core.

## Anotaciones (`tools/_annotations.py`)

| Tool | readOnly | destructive | idempotent | openWorld | Cómo |
|---|---|---|---|---|---|
| `sv_list_available_updates` | sí | no | sí | no | prefijo `sv_list_` |
| `sv_check_for_updates` | no | no | sí | **sí** | `_OPEN_WORLD` (descarga el registro de versiones y refresca los repositorios de la tienda) |
| `sv_update_core` | no | **sí** | sí | **sí** | `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD` |
| `sv_update_os` | no | **sí** | sí | **sí** | ídem |
| `sv_update_supervisor` | no | **sí** | sí | **sí** | ídem |
| `ha_list_updates` | sí | no | sí | no | prefijo `ha_list_` |
| `ha_get_update_release_notes` | sí | no | sí | **sí** | prefijo `ha_get_` y `_OPEN_WORLD` (algunas integraciones piden las notas a internet al leerlas) |
| `ha_install_update` | no | **sí** | sí | **sí** | `_DESTRUCTIVE_EXACT` y `_OPEN_WORLD` |

Idempotentes: repetir la actualización a la misma versión deja el mismo
estado (la segunda la rechaza el Supervisor o Core como «ya instalada»).

Títulos (`title_for`): `List available updates (Supervisor)`, `Check for
updates (Supervisor)`, `Update core (Supervisor)`, `Update OS (Supervisor)`,
`Update supervisor (Supervisor)`, `List updates (Home Assistant)`, `Get update
release notes (Home Assistant)`, `Install update (Home Assistant)`. Necesita
`"os": "OS"` en `_TITLE_WORDS` (lo añade la 013; si no está integrada, el
tramo 2 lo añade con su test de que ningún título de la 1.1.2 cambia).

## Descripciones (lo que tienen que decir)

- `sv_list_available_updates`: qué lista (Core, OS, Supervisor, apps y
  plugins) con versión instalada y disponible y la tool para cada una; que la
  información es la que el Supervisor tiene en caché y se refresca con
  `sv_check_for_updates`; que las entidades `update` de dispositivos e
  integraciones están en `ha_list_updates`; el orden recomendado.
- `sv_check_for_updates`: que pide al Supervisor buscar actualizaciones
  (registro de versiones y repositorios de la tienda, sale a internet) y
  devuelve la lista; no pide token.
- `sv_update_core`: dos pasos; qué dice la vista previa (versiones, backup
  parcial de Core, reinicio de Core y vuelta atrás si no arranca, salud,
  comprobación de configuración, bloqueos); que sin token no hay vista previa
  con bloqueos; que el token está atado a la versión de destino; que devuelve
  `job_id` para `sv_get_job_status`.
- `sv_update_os`: dos pasos; solo Home Assistant OS; se instala en la ranura
  inactiva y se aplica al reiniciar el host con `sv_reboot_host`; no hace
  backup.
- `sv_update_supervisor`: dos pasos; el Supervisor se reinicia solo; Core y las
  apps no; las `sv_*` fallan un minuto; sin versión concreta ni backup.
- `ha_list_updates`: entidades `update` con actualización (o todas con
  `include_up_to_date`), qué admiten y con qué tool se instalan.
- `ha_get_update_release_notes`: notas de una entidad `update`, redactadas,
  recortadas y como texto de terceros; si no las admite, resumen y URL.
- `ha_install_update`: dos pasos; vista previa con versiones, notas, backup y
  avisos; que Core, OS, Supervisor y apps se encaminan a sus `sv_*`; que si la
  instalación tarda, sigue en HA y se sigue con `ha_list_updates`.

## Respuestas de error

Todas con `{"error": <código>, "detail": <texto en inglés>}` y, cuando ayuda,
`hint`. Ninguna emite `confirmation_token`.

| Código | Cuándo |
|---|---|
| `invalid_argument` | `version` o `entity_id` con forma inválida (sin copiar el valor) |
| `update_blocked` | `blocked` no vacío; lleva `preview` completa |
| `already_installed` | destino igual a la versión instalada |
| `no_update_available` | sin destino distinto de la instalada |
| `not_haos` | `/os/info` responde 404 |
| `versions_unavailable` | no se pudo leer versión actual o de destino |
| `entity_not_found` | `entity_id` sin estado |
| `specific_version_not_supported`, `backup_not_supported`, `update_in_progress` | validaciones de `update.install` |
| `update_in_progress` | `sv_update_os`: ya hay un job `os_manager_update` sin terminar (T047); lleva `job_id` y `poll_with` |
| `use_dedicated_tool` | entidad de la plataforma `hassio` (FR-014); en `ha_call_service` con `update.install`, también un objetivo que no es una lista explícita de `entity_id` (hacia `ha_install_update`, T051) |
| `self_update_not_supported` | entidad de la app Hermes (también por `ha_call_service`, T051) |
| `self_check_unavailable`, `registry_unavailable` | no se pudo leer el slug propio o el registro de entidades (fail-closed) |
| `unsupported_entity` | entidad de `hassio` no reconocida, u otra app con slug `*_hermes` que `sv_update_addon` rechazaría (D-13, T048) |
| error del token | el de `security.py`, más `preview_outdated: true` y `hint` en las cuatro que atan versiones |

Los mensajes del Supervisor y de Core pasan por `redact_secrets` y se recortan a
500 caracteres.

## Guía (`hermes_guide`)

Tema `updates` (alias `update`, `upgrade`): orden
recomendado (Supervisor → Core → OS y `sv_reboot_host`), qué bloquea y por
qué, token atado a la versión, seguimiento por `job_id` y qué hacer tras el
reinicio del Supervisor, encaminamiento de las entidades `update`, que las
apps siguen con `sv_update_addon` y los plugins por `sv_call_api`. El tema
`supervisor` añade una línea que remite a `updates`.
