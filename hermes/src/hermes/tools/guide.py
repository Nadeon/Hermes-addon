"""Hermes — Onboarding del cliente MCP.

Dos mecanismos para que el cliente (Claude) sepa qué herramientas usar y cuándo:

1. `INSTRUCTIONS`: texto que el servidor entrega en el `initialize` del MCP
   (vía `MCPServer(instructions=...)`). Viaja en el contexto del modelo, así que
   se reserva para lo que NO se deduce del nombre de la tool: el protocolo de
   confirmación en dos pasos, las trampas que cuestan caro y cómo no malgastar
   contexto. El modelo acierta la herramienta casi siempre solo con la lista
   de nombres, así que enumerar las familias aquí sería gastar tokens en
   información redundante.

2. Tool `hermes_guide(topic)`: guía detallada bajo demanda. Claude la invoca
   cuando necesita profundizar en un área concreta (filesystem, backups, etc.)
   o un flujo completo (`hermes_guide("workflows")`).
"""

from __future__ import annotations

# ── Resumen entregado al conectar (initialize) ────────────────────────────────

INSTRUCTIONS = """\
Controlas Home Assistant a través de Hermes: ~186 tools con prefijo `ha_`
(Home Assistant), `fs_` (ficheros de /config) y `sv_` (sistema: add-ons, host,
backups). Los nombres son predecibles —`ha_list_*`, `ha_get_*`, `ha_update_*`,
`sv_restart_*`, `fs_read_*`…— así que normalmente sabrás cuál usar leyendo la
lista. Lo que sigue es lo que NO se deduce del nombre.

1) CONFIRMACIÓN EN DOS PASOS
Las acciones destructivas devuelven, en la primera llamada, un `preview` y un
`confirmation_token` en vez de ejecutarse. Eso NO es un error: es el paso de
revisión. Repite la MISMA llamada con los MISMOS argumentos añadiendo
`confirmation_token` para ejecutar. Caduca en ~60 s y sirve una sola vez.
Enseña al usuario lo que dice el `preview` antes de confirmar algo grave
(borrados, reinicios, restauración de backups).

2) TRAMPAS QUE CUESTAN CARO
- `ha_create_or_update_*` sirve para crear Y para editar (automatizaciones,
  scripts, escenas y helpers). Al crear un helper, HA deriva su id de
  slugify(name): pasa el `name` que quieras como identificador.
- `ha_update_*` (área, dispositivo, entidad, persona, recurso Lovelace) solo
  edita algo que YA existe; no lo crea.
- Para reiniciar HA usa `sv_restart_core`, NO `ha_call_service`
  ("homeassistant","restart"): sv_restart_core comprueba antes que la
  configuración esté validada.
- `ha_save_lovelace_dashboard` REEMPLAZA el dashboard entero: lee antes con
  `ha_get_lovelace_dashboard`, modifica el documento y guárdalo completo.
- Para quitar una integración, `ha_disable_config_entry` es reversible;
  `ha_delete_config_entry` borra también sus entidades y dispositivos.
- Edita automatizaciones con `ha_create_or_update_automation`, no escribiendo
  `automations.yaml` con `fs_write_file` (te saltas validación y recarga).
- Los flujos de integración que piden login externo (OAuth) no son
  automatizables: Hermes los aborta e informa.
- `ha_wait_for_event` espera UNA vez en esta conversación; para un aviso
  permanente, crea una automatización.

3) NO GASTES CONTEXTO
- `ha_get_states` SIEMPRE con `domain`; sin filtro devuelve la casa entera.
- Para contar o agregar, `ha_render_template` resuelve dentro de HA y devuelve
  solo el resultado.
- Acota history, logbook y estadísticas por entidad y por fechas.
- Si una respuesta llega truncada, filtra más; no repitas la misma llamada.

4) OPERACIONES LARGAS
Instalar/actualizar add-ons y crear/restaurar backups devuelven `job_id`.
Consulta el progreso con `sv_get_job_status(job_id)` en vez de reintentar.

5) SI DUDAS
`hermes_guide(tema)` da la guía de un área (services, automations, helpers,
events, data, registries, config_entries, filesystem, supervisor, backups,
lovelace, security) y `hermes_guide("workflows")` recetas paso a paso. Sin
argumentos devuelve el índice.
"""


# ── Guía detallada por tema ───────────────────────────────────────────────────

_OVERVIEW = """\
# Guía de Hermes

Hermes da control completo de Home Assistant. Llama `hermes_guide("<tema>")`
para el detalle de un área. Temas disponibles:

- `services`       — leer estados y llamar servicios (el día a día)
- `automations`    — automations, scripts y scenes
- `helpers`        — input_*, counter, timer, schedule, zone, person
- `events`         — disparar y esperar eventos
- `data`           — history, logbook, templates, estadísticas
- `registries`     — entidades, dispositivos, áreas
- `config_entries` — integraciones y sus flujos de configuración
- `filesystem`     — leer y escribir ficheros de /config
- `supervisor`     — add-ons, host y core de HAOS
- `backups`        — crear, restaurar y gestionar backups
- `lovelace`       — dashboards y recursos del frontend
- `security`       — confirmation tokens, denylist y límites
- `workflows`      — recetas paso a paso para tareas completas

Regla transversal: las acciones destructivas usan confirmación en dos pasos
(preview + `confirmation_token`). Ver `hermes_guide("security")`.
"""

_GUIDE: dict[str, str] = {
    "overview": _OVERVIEW,
    "services": """\
# Estados y servicios

El núcleo del día a día.

- `ha_get_states(domain="light", compact=True)` — lista estados. SIEMPRE filtra
  por `domain` salvo que necesites todo (la lista completa es enorme).
- `ha_get_state("light.cocina")` — estado de una entidad concreta.
- `ha_list_services()` — qué servicios existen y sus campos.
- `ha_call_service(domain, service, service_data)` — ejecuta una acción.
- `ha_call_service_response(...)` — para servicios que devuelven datos
  (return_response). No admite servicios de la denylist.

Ejemplos:
- Encender una luz al 80 %:
  `ha_call_service("light", "turn_on",
   {"entity_id": "light.cocina", "brightness_pct": 80})`
- Poner el clima en 21°:
  `ha_call_service("climate", "set_temperature",
   {"entity_id": "climate.salon", "temperature": 21})`
- Varias entidades a la vez: `"entity_id": ["switch.a", "switch.b"]`.

Flujo: `ha_get_states(domain)` para encontrar la entidad → `ha_call_service`.
Servicios peligrosos piden confirmation_token (ver `security`).
""",
    "automations": """\
# Automations, scripts y scenes

- Automations: `ha_list_automations`, `ha_get_automation(entity_id)`,
  `ha_create_or_update_automation` (crea o edita; token), `ha_trigger_automation`,
  `ha_enable/disable_automation`, `ha_delete_automation` (token),
  `ha_reload_automations`.
- Scripts: `ha_list_scripts`, `ha_get_script`, `ha_create_or_update_script` (token),
  `ha_run_script`, `ha_delete_script` (token), `ha_reload_scripts`.
- Scenes: `ha_list_scenes`, `ha_get_scene`, `ha_create_or_update_scene` (token),
  `ha_activate_scene`, `ha_create_scene_from_current`, `ha_delete_scene` (token).

Ejemplo (crear/editar una automatización — devuelve preview + token, repite con
el token para aplicar):
  `ha_create_or_update_automation("automation.luz_noche", {
     "alias": "Luz noche",
     "trigger": [{"platform": "sun", "event": "sunset"}],
     "action": [{"service": "light.turn_on",
                 "target": {"entity_id": "light.salon"}}]})`

Tras crear/editar, HA recarga sola (no hace falta `reload` manual). Si un
script/automation llama a un servicio peligroso, Hermes lo marca como
restringido y su ejecución pedirá confirmación.
""",
    "helpers": """\
# Helpers (entidades auxiliares)

input_boolean, input_number, input_select, input_text, input_datetime,
input_button, counter, timer, schedule, zone, person.

Para cada tipo hay `ha_list_*`, `ha_get_*`, `ha_create_or_update_*` (crea o
edita, token), `ha_delete_*` (token) y acciones (`ha_set_*`, `ha_toggle_*`,
`ha_increment_*`, `ha_start_timer`, etc.).

Ojo: `ha_create_or_update_input_number` cambia la CONFIGURACIÓN del helper
(nombre, mínimo, máximo); `ha_set_input_number` cambia su VALOR actual.

Ejemplos:
- Fijar un input_number: `ha_set_input_number("input_number.umbral", 25)`
- Arrancar un timer 5 min: `ha_start_timer("timer.cocina", "00:05:00")`

Gotcha: al crear, HA deriva el `object_id` de `slugify(name)`. Si el id
resultante no coincide con el que pediste, la respuesta te da el id real. Pasa
un `name` cuyo slug sea el object_id deseado.
""",
    "events": """\
# Eventos

- `ha_fire_event(event_type, event_data)` — dispara un evento en el bus. Sólo
  para tipos en el allowlist configurado (`fire_event_allowlist`).
- `ha_wait_for_event(event_type, filters, timeout_seconds)` — ESPERA bloqueante
  hasta que ocurra un evento que cumpla los filtros (dot-path con operadores
  `>`, `<`, `>=`, `<=`, `!=`). Útil para sincronizar con algo del mundo real.
- `ha_list_active_waits()` / `ha_cancel_wait(wait_id)` — gestionar esperas.

Ejemplo (esperar a que se abra una puerta, máx 60 s):
  `ha_wait_for_event("state_changed",
   {"data.entity_id": "binary_sensor.puerta", "data.new_state.state": "on"}, 60)`

El timeout y la concurrencia están limitados por config
(`wait_for_event_max_seconds`, `wait_for_event_max_concurrent`).
""",
    "data": """\
# Datos: history, logbook, templates, estadísticas

- `ha_render_template("{{ states('sensor.x') }}")` — evalúa Jinja2 en HA. Ideal
  para cálculos o consultas puntuales sin adivinar el estado.
- `ha_get_history(entity_id, start, end)` — series temporales de estado.
- `ha_get_logbook(...)` — eventos legibles (quién/qué cambió).
- `ha_statistics_during_period(...)` / `ha_list_statistic_ids()` — estadísticas
  de largo plazo (energía, etc.).

Ejemplo (cuántos sensores hay disponibles):
  `ha_render_template("{{ states.sensor
   | selectattr('state','!=','unavailable') | list | length }}")`

Respuestas potencialmente grandes: acota siempre por entidad y rango de fechas.
""",
    "registries": """\
# Registries: entidades, dispositivos, áreas

- Entidades: `ha_list_entities_registry`, `ha_get_entity_registry`,
  `ha_update_entity_registry` (renombrar, ocultar, mover de área…),
  `ha_remove_entity_registry`.
- Dispositivos: `ha_list_devices`, `ha_get_device`, `ha_update_device`,
  `ha_remove_device_from_config_entry`.
- Áreas: `ha_list_areas`, `ha_get_area`, `ha_create_area`, `ha_update_area`,
  `ha_delete_area`.

Ejemplo (mover una entidad a un área):
  `ha_update_entity_registry("light.cocina", {"area_id": "cocina"})`

El registro es la "fuente de la verdad" de nombres, áreas y visibilidad. Para
reorganizar la casa (asignar entidades/dispositivos a áreas) trabaja aquí.
""",
    "config_entries": """\
# Integraciones (config entries y flows)

- Entries: `ha_list_config_entries`, `ha_get_config_entry`,
  `ha_reload_config_entry`, `ha_disable/enable_config_entry`,
  `ha_delete_config_entry` (token — borra la integración y sus entidades).
- Config flows (instalar/configurar): `ha_list_configured_domains`,
  `ha_start_config_entry_flow`, `ha_continue_config_entry_flow`,
  `ha_abort_config_entry_flow`.
- Options flows: `ha_get_config_entry_options`, `ha_start_options_flow`,
  `ha_continue_options_flow`.

Los flujos `external` (OAuth de la integración) y `progress` NO son
automatizables: Hermes los aborta y lo indica. Para deshabilitar de forma
reversible usa `disable`, no `delete`. Ver el flujo completo en
`hermes_guide("workflows")`.
""",
    "filesystem": """\
# Ficheros de /config

Lectura:
- `fs_read_file(path)`, `fs_read_file_lines(path, start, end)`,
  `fs_list_dir(path)`, `fs_search_in_config(query)`, `fs_stat(path)`.

Escritura (TODAS requieren confirmation_token):
- `fs_write_file(path, content)` — crea/sobrescribe. Hace backup del original.
- `fs_delete_file(path)`, `fs_move_file(src, dst)`.
- `fs_set_secret(key, value)` — escribe en secrets.yaml (nunca se devuelve su
  contenido).
- `fs_list_file_backups(path)` / `fs_restore_file_backup(path, timestamp)`.

Ejemplo (lee y luego escribe, segunda llamada con el token del preview):
  `fs_read_file("automations.yaml")` →
  `fs_write_file("automations.yaml", nuevo_contenido)` (preview) →
  `fs_write_file(..., confirmation_token="…")` (aplica).

Seguridad: anti-traversal (no se sale de /config), secretos en blacklist
(secrets.yaml, *.key, *.db…), `.storage/` es default-deny y NO se escribe (usa
las tools `ha_*` correspondientes). Cada escritura hace un backup por-fichero,
reversible con `fs_restore_file_backup`.
""",
    "supervisor": """\
# Sistema: add-ons, host y core (Supervisor)

- Add-ons: `sv_list_addons`, `sv_get_addon(slug)`, `sv_get_addon_options`,
  `sv_set_addon_options` (token), `sv_start/stop/restart_addon` (token),
  `sv_install/uninstall/update_addon` (token, asíncrono → `job_id`),
  `sv_get_addon_logs` (secretos redactados), `sv_get_addon_stats`.
- Supervisor/host/core: `sv_get_supervisor_info`, `sv_get_host_info`,
  `sv_get_core_info`, `sv_check_core_config`, `sv_restart_core` (token),
  `sv_reboot_host` (token).

Cuidado con el propio Hermes (`local_hermes`): pararlo/desinstalarlo te deja sin
acceso; el preview lo advierte. Operaciones largas devuelven `job_id`: pollea
con `sv_get_job_status(job_id)` hasta `done`.
""",
    "backups": """\
# Backups

- Listar/ver: `sv_list_backups`, `sv_get_backup(slug)`.
- Crear (asíncrono, devuelven `job_id`): `sv_create_backup_full`,
  `sv_create_backup_partial`, `sv_create_safety_backup` (full bajo demanda con
  cooldown).
- Borrar/restaurar (token): `sv_delete_backup`, `sv_restore_backup_full`
  (¡sobrescribe TODO!), `sv_restore_backup_partial`.
- Jobs: `sv_get_job_status(job_id)`, `sv_list_pending_jobs`.

Nota: el backup FULL automático antes de escribir en /config está DESACTIVADO
por defecto (`safety_backup_enabled`), porque genera varios GB. Las escrituras
siguen teniendo backup por-fichero. Si quieres un backup completo antes de algo
gordo, créalo tú con `sv_create_safety_backup` (ver `workflows`).
""",
    "lovelace": """\
# Lovelace (dashboards y recursos)

- Dashboards: `ha_list_lovelace_dashboards`, `ha_get_lovelace_dashboard`,
  `ha_create_lovelace_dashboard`, `ha_save_lovelace_dashboard` (escribe la
  config completa), `ha_update_lovelace_dashboard_metadata`,
  `ha_delete_lovelace_dashboard`.
- Recursos (JS/CSS del frontend): `ha_list_lovelace_resources`,
  `ha_create_lovelace_resource`, `ha_update_lovelace_resource`,
  `ha_delete_lovelace_resource`.

`save_dashboard` reemplaza TODA la config del dashboard: lee primero con
`get_lovelace_dashboard`, modifica el documento y guárdalo completo (si no,
borras el resto de tarjetas).
""",
    "security": """\
# Seguridad: confirmación, denylist y límites

Confirmación en dos pasos: las acciones destructivas devuelven un `preview` +
`confirmation_token` en la primera llamada. Revisa el preview y repite la
llamada con el token (un solo uso, ~60 s) para ejecutar.

Servicios peligrosos (denylist): `shell_command.*`, `python_script.*`,
`homeassistant.restart/stop`, `*.reload`, `mqtt.publish`, `hassio.*`,
`backup.*`, `recorder.purge`, `lock.unlock`,
`alarm_control_panel.alarm_disarm`, `logger.set_level`… exigen token. Además, los
campos de `service_data` que parezcan rutas a ficheros sensibles se rechazan.

Otros límites: escritura en /config con rate limit (intervalo mínimo + máx/min),
respuestas truncadas por tamaño, y `/config` con anti-traversal + blacklist de
secretos. Si algo te pide confirmación, es por diseño: confirma sólo lo que el
usuario quiere.
""",
    "workflows": """\
# Flujos completos (recetas paso a paso)

CONTROLAR ALGO
1. `ha_get_states(domain="light")` para localizar la entidad.
2. `ha_call_service("light", "turn_on", {"entity_id": "light.cocina"})`.

CREAR UNA AUTOMATIZACIÓN
1. Define trigger/condition/action.
2. `ha_create_or_update_automation(entity_id, config)` → devuelve preview + token.
3. Repite con `confirmation_token` para aplicar (HA recarga sola).
4. Pruébala: `ha_trigger_automation(entity_id)` y revisa el resultado.

CAMBIO SEGURO EN /config
1. `fs_read_file("configuration.yaml")` (o el fichero a tocar).
2. `fs_write_file(path, nuevo_contenido)` → preview (hace backup) → repite con
   token para aplicar.
3. `sv_check_core_config()` para validar que la config sigue siendo correcta.
4. Recarga lo afectado (`ha_reload_automations`, …) o, si hace falta,
   `sv_restart_core()` (token). Si algo va mal: `fs_restore_file_backup`.

INSTALAR UNA INTEGRACIÓN
1. `ha_start_config_entry_flow(domain)` → devuelve `flow_id` y un `step`.
2. `ha_continue_config_entry_flow(flow_id, {campos del formulario})`.
3. Repite el paso 2 hasta `type: create_entry`. Si pide auth externa
   (`external`), no es automatizable: el flujo se aborta.

BACKUP ANTES DE ALGO GORDO
1. `sv_create_safety_backup()` → devuelve `job_id`.
2. `sv_get_job_status(job_id)` hasta `done: true`.
3. Procede con el cambio. Para deshacer del todo: `sv_restore_backup_full`.

DIAGNOSTICAR POR QUÉ ALGO NO FUNCIONA
1. `ha_get_state(entity_id)` — estado y atributos actuales.
2. `ha_get_history(entity_id, start, end)` / `ha_get_logbook(...)` — qué pasó.
3. Si es una automatización: `ha_get_automation(entity_id)` para revisar su
   lógica; `sv_get_addon_logs(slug)` para los logs de la integración/add-on.
""",
}

# Aliases hacia los temas canónicos.
_ALIASES: dict[str, str] = {
    "index": "overview",
    "help": "overview",
    "states": "services",
    "service": "services",
    "entities": "services",
    "scripts": "automations",
    "scenes": "automations",
    "automation": "automations",
    "input": "helpers",
    "counter": "helpers",
    "timer": "helpers",
    "person": "helpers",
    "zone": "helpers",
    "event": "events",
    "wait": "events",
    "history": "data",
    "logbook": "data",
    "templates": "data",
    "statistics": "data",
    "registry": "registries",
    "areas": "registries",
    "devices": "registries",
    "integrations": "config_entries",
    "config_entry": "config_entries",
    "flows": "config_entries",
    "fs": "filesystem",
    "files": "filesystem",
    "config": "filesystem",
    "addons": "supervisor",
    "addon": "supervisor",
    "host": "supervisor",
    "core": "supervisor",
    "system": "supervisor",
    "backup": "backups",
    "dashboards": "lovelace",
    "dashboard": "lovelace",
    "confirmation": "security",
    "denylist": "security",
    "workflow": "workflows",
    "recipes": "workflows",
    "recetas": "workflows",
    "howto": "workflows",
}


def register(mcp: object) -> None:
    """Registra la tool `hermes_guide` en la instancia MCP."""

    @mcp.tool()
    async def hermes_guide(topic: str | None = None) -> str:
        """Guía de uso de Hermes: qué herramientas hay y cuándo usarlas.

        Llama sin argumentos (o con `topic="overview"`) para el índice de temas.
        Pasa un `topic` para la guía detallada de un área, o
        `topic="workflows"` para recetas paso a paso de tareas completas.

        Args:
            topic (str, opcional): Tema. Uno de: overview, services, automations,
                helpers, events, data, registries, config_entries, filesystem,
                supervisor, backups, lovelace, security, workflows. Acepta alias
                comunes (p. ej. "addons" → supervisor, "files" → filesystem).

        Returns:
            La guía del tema en Markdown. Si el tema no existe, devuelve el
            índice con la lista de temas válidos.
        """
        if not topic:
            return _OVERVIEW
        key = topic.strip().lower()
        key = _ALIASES.get(key, key)
        if key in _GUIDE:
            return _GUIDE[key]
        valid = ", ".join(sorted(_GUIDE))
        return (
            f"Tema '{topic}' no reconocido.\n\nTemas disponibles: {valid}.\n\n"
            + _OVERVIEW
        )
