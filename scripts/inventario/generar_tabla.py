"""Genera `hermes/src/hermes/command_table.py` desde los inventarios de la 008
(spec 011, FR-002, FR-007; research R-2 y R-4).

USO (mantenedor; nunca en el CI ni dentro del add-on)
-----------------------------------------------------
    python scripts/inventario/generar_tabla.py [--ha-core 2026.11.1]
        [--supervisor 2026.11.0] [--core TSV] [--supervisor-tsv TSV]
        [--salida command_table.py]

Procedimiento con una versión nueva de HA (quickstart.md de la 011):

1. Regenerar los dos TSV de `specs/008-cobertura-total/inventario/` con el
   extractor (`scripts/inventario/extraer.py`, tramo 3) y clasificar a mano
   las filas nuevas (clase, nota, CAP).
2. Ejecutar este generador con las versiones nuevas. Conserva tal cual (byte
   a byte, con sus comentarios) toda entrada cuya clave sigue en el
   inventario; añade cada fila nueva como `deny` con el motivo «sin revisar
   (nuevo en <versión>)», y quita las que ya no están. Imprime las dos listas.
3. Ejecutar la suite: `tests/test_command_table.py` falla nombrando lo «sin
   revisar» y lo que no cuadra. Clasificar cada entrada A MANO en la tabla.
4. Subir `HA_CORE_LAST_TESTED` en `hermes/config.py` a la misma versión.

POR QUÉ ASÍ
-----------
Después de la primera generación, la tabla es la fuente de verdad: se revisa
y se edita a mano, y regenerar nunca puede pisar una decisión de seguridad.
Lo nuevo entra como `deny`, así que, aunque nadie ejecute los tests, la
genérica lo rechaza (fail-closed); el test de «sin revisar» obliga a
clasificarlo antes de cerrar.

Primera generación (sin tabla previa), por fila (research R-4):
- cubierto → `dedicated` con la tool de `_DEDICADAS_INICIALES` (revisado a
  mano); `deny` «uso interno de Hermes» o el motivo que diga el mapa si
  ninguna tool lo expone; `deny` «sin revisar» si no está en el mapa;
- clase B y D → `deny` con el motivo de la nota;
- clase A con la clave en `_DEDICADAS_INICIALES` (su sub-feature ya creó la
  tool) → `dedicated` con esa tool, con el mismo constructor que «cubierto»
  (specs 012, 013 y 029; research R-7). Toda sub-feature que pase una fila A
  a `dedicated` la añade al mapa: `tests/test_generar_tabla.py` compara la
  generación desde cero con la tabla real en todas esas filas;
- clase A de una CAP de vía D, D+T o D+X → `deny` «pendiente de tool
  dedicada (spec NNN)» con la sub-feature de la matriz de la 008;
- clase A de vía T → `read` o `confirm` por verbo y método, PROVISIONAL hasta
  la revisión manual comando a comando (las suscripciones, `deny`);
- clase C → `deny` «pendiente de revisión (spec 025)»;
- `/core/api*` y `/homeassistant/api*` → `deny`, por encima de todo lo demás.

Solo lee texto (TSV y la tabla previa, por AST) y el árbol de tools por AST:
no importa ni ejecuta nada de lo que lee. Importa `hermes.tool_families`
(módulo neutral) para la familia de cada tool dedicada.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field

_RAIZ = pathlib.Path(__file__).resolve().parents[2]
_INVENTARIO = _RAIZ / "specs" / "008-cobertura-total" / "inventario"
_TOOLS = _RAIZ / "hermes" / "src" / "hermes" / "tools"
_SALIDA = _RAIZ / "hermes" / "src" / "hermes" / "command_table.py"

if str(_RAIZ / "hermes" / "src") not in sys.path:  # pragma: no cover - uso como script
    sys.path.insert(0, str(_RAIZ / "hermes" / "src"))

from hermes.tool_families import familia_de_modulo  # noqa: E402

HA_CORE_POR_DEFECTO = "2026.11.1"
SUPERVISOR_POR_DEFECTO = "2026.11.0"

FAMILIA_GENERICAS = "generic_commands"

# Marca de lo clasificado por verbo sin revisar comando a comando. La revisión
# manual (tareas T013 y T014 de la 011) la quita; un test impide cerrar el
# programa con ella.
PROVISIONAL = "clasificación provisional por verbo, pendiente de revisión manual"

# Verbos de escritura de FR-005 (copia; la lista de referencia está en
# tests/test_command_table.py y solo crece).
_VERBOS_ESCRITURA = frozenset({
    "create", "delete", "remove", "update", "set", "save", "install",
    "uninstall", "restart", "reload", "import", "clear", "adjust", "change",
    "configure", "reset", "move", "reorder", "enable", "disable", "ignore",
    "dismiss", "add", "promote", "run", "start", "stop",
})

_PREFIJOS_PROXY_CORE = ("/core/api", "/homeassistant/api")
_MOTIVO_PROXY = (
    "proxy de Core: llegaría a la API REST de Core saltándose la denylist y "
    "las guardas de las tools ha_* (siempre rechazado)"
)

# ── Matriz CAP → vía y sub-feature ───────────────────────────────────────────
# Copia revisada de la matriz de trazabilidad de specs/008-cobertura-total/
# plan.md (solo las CAP de vía D, T, D+T y D+X; X y M no tienen filas en los
# inventarios). Valor: (vía, sub-feature de la lectura, sub-feature de la
# escritura). Cuando la 008 da dos sub-features: CAP-040 es la validación de
# 012 (017 solo la usa al guardar) y CAP-087 lee en 013 y escribe en 022.
# tests/test_generar_tabla.py comprueba que la copia coincide con la 008.
MATRIZ: dict[str, tuple[str, str, str]] = {
    "CAP-038": ("D", "017", "017"),
    "CAP-040": ("D+X", "012", "012"),
    "CAP-041": ("D", "012", "012"),
    "CAP-042": ("D", "012", "012"),
    "CAP-043": ("D", "029", "029"),
    "CAP-044": ("D", "016", "016"),
    "CAP-045": ("D", "016", "016"),
    "CAP-046": ("D", "017", "017"),
    "CAP-047": ("D", "012", "012"),
    "CAP-048": ("D", "016", "016"),
    "CAP-049": ("D", "029", "029"),
    "CAP-050": ("D", "020", "020"),
    "CAP-051": ("D", "017", "017"),
    "CAP-052": ("D", "017", "017"),
    "CAP-053": ("D+T", "021", "021"),
    "CAP-054": ("D+T", "020", "020"),
    "CAP-055": ("D", "021", "021"),
    "CAP-056": ("D", "021", "021"),
    "CAP-057": ("D+T", "031", "031"),
    "CAP-058": ("T", "029", "029"),
    "CAP-059": ("D+T", "024", "024"),
    "CAP-060": ("D", "023", "023"),
    "CAP-061": ("T", "023", "023"),
    "CAP-062": ("T", "023", "023"),
    "CAP-063": ("T", "023", "023"),
    "CAP-064": ("D", "015", "015"),
    "CAP-065": ("T", "024", "024"),
    "CAP-066": ("T", "024", "024"),
    "CAP-067": ("T", "024", "024"),
    "CAP-068": ("T", "029", "029"),
    "CAP-069": ("D", "021", "021"),
    "CAP-070": ("T", "024", "024"),
    "CAP-071": ("D+T", "024", "024"),
    "CAP-072": ("T", "024", "024"),
    "CAP-073": ("T", "024", "024"),
    "CAP-074": ("T", "021", "021"),
    "CAP-075": ("D", "026", "026"),
    "CAP-080": ("D", "015", "015"),
    "CAP-081": ("D", "013", "013"),
    "CAP-082": ("D", "030", "030"),
    "CAP-083": ("D", "019", "019"),
    "CAP-084": ("D+T", "022", "022"),
    "CAP-085": ("D", "013", "013"),
    "CAP-086": ("D", "032", "032"),
    "CAP-087": ("D+T", "013", "022"),
    "CAP-088": ("T", "013", "013"),
    "CAP-089": ("T", "013", "013"),
    "CAP-090": ("D", "032", "032"),
    "CAP-091": ("T", "022", "022"),
    "CAP-092": ("T", "022", "022"),
    "CAP-093": ("D+X", "030", "030"),
    "CAP-094": ("T", "022", "022"),
    "CAP-100": ("T", "025", "025"),
    "CAP-101": ("T", "025", "025"),
    "CAP-102": ("T", "025", "025"),
    "CAP-103": ("T", "025", "025"),
    "CAP-104": ("T", "025", "025"),
    "CAP-105": ("T", "025", "025"),
    "CAP-106": ("T", "025", "025"),
}


# ── Lo cubierto hoy: comando o ruta → tool dedicada (revisado a mano) ────────


@dataclass(frozen=True)
class _Deny:
    """Lo cubierto que ninguna tool expone: `deny` con este motivo."""

    motivo: str


@dataclass(frozen=True)
class _ConMatiz:
    """Lo cubierto por una tool que no usa esa misma ruta o comando: el
    motivo dice cuál usa, para que el cliente no crea que son lo mismo
    (spec 015: `/reload_updates` y `hassio/update/core`). Sin esto, la
    generación desde cero perdería el matiz que la tabla revisada sí tiene.
    """

    tool: str
    matiz: str


@dataclass(frozen=True)
class _ConMotivo:
    """Lo cubierto por una tool con un motivo entero que no sigue la forma
    «cubierto por <tool> (<matiz>)» (spec 030: `GET /store` lo cubren dos
    tools, y las rutas con `{version}` las cubre la tool sin versión porque el
    Supervisor ignora `{version}`). Sin esto, la generación desde cero
    perdería el motivo que la tabla revisada sí tiene.
    """

    tool: str
    motivo: str


_INTERNO = _Deny("uso interno de Hermes")
_SUSCRIPCION_NO_USADA = _Deny(
    "suscripción/streaming: MCP es petición-respuesta (Hermes no la usa)"
)

# Solo sirve para la PRIMERA generación: la revisión manual (T015 de la 011)
# reclasificó después en command_table.py lo que la tool dedicada no expone
# igual (p. ej. `automation/config`, `frontend/get_system_data`, `GET /info`).
#
# Clave → nombre de la tool que lo cubre, o `_Deny`. Lo cubierto por una
# acción de HA va a `ha_call_service` (o a `ha_call_service_response` si la
# acción devuelve datos). La genérica rechaza estas entradas con
# `use_dedicated_tool`: la tool dedicada tiene la vista previa semántica, la
# denylist o las protecciones (dashboard principal, autoprotección de Hermes)
# que la genérica no tiene.
_DEDICADAS_INICIALES: dict[
    str | tuple[str, str], str | _Deny | _ConMatiz | _ConMotivo] = {
    # Automatizaciones y scripts: la config por entity_id la dan las tools de
    # lectura (que leen por REST); el comando WS lo usan los registros por dentro.
    "automation/config": "ha_get_automation",
    "script/config": "ha_get_script",
    # Backups de la integración y del Supervisor.
    "backup/config/info": "ha_get_backup_config",
    "backup/details": "ha_get_backup",
    "backup/info": "ha_list_backups",
    "backup/delete": "sv_delete_backup",
    "backup/restore": "sv_restore_backup_full",
    "backup/generate": "ha_call_service",
    "backup/generate_with_automatic_settings": "ha_call_service",
    "backup/subscribe_events": _SUSCRIPCION_NO_USADA,
    "cloud/subscribe_events": _SUSCRIPCION_NO_USADA,
    # Acciones de HA.
    "calendar/event/create": "ha_call_service",
    # 015: actualizar Core por el Supervisor, con la vista previa de la tool.
    "hassio/update/core": _ConMatiz(
        "sv_update_core",
        "la misma actualización por el Supervisor, con vista previa de "
        "versiones, backup y bloqueos"),
    "media_player/browse_media": "ha_call_service_response",
    "media_player/search_media": "ha_call_service_response",
    "recorder/statistic_during_period": "ha_call_service_response",
    "shopping_list/items": "ha_call_service_response",
    "shopping_list/items/add": "ha_call_service",
    "shopping_list/items/clear": "ha_call_service",
    "shopping_list/items/remove": "ha_call_service",
    "shopping_list/items/update": "ha_call_service",
    "todo/item/list": "ha_call_service_response",
    "weather/subscribe_forecast": "ha_call_service_response",
    # Núcleo del protocolo y equivalentes REST.
    "call_service": "ha_call_service",
    "get_services": "ha_list_services",
    "get_states": "ha_get_states",
    "fire_event": "ha_fire_event",
    "render_template": "ha_render_template",
    "subscribe_events": "ha_wait_for_event",
    "unsubscribe_events": _INTERNO,
    "get_config": _INTERNO,
    # Proxy WS hacia la API del Supervisor: por ahí se saltarían las guardas de
    # las tools sv_* y de las genéricas del Supervisor (autoprotección, proxy).
    "supervisor/api": _Deny(
        "proxy WS a la API del Supervisor: se saltaría las guardas de las "
        "tools sv_* (usar sv_read_api/sv_call_api)"
    ),
    "hassio/update/addon": "sv_update_addon",
    # Registros.
    "config/area_registry/create": "ha_create_area",
    "config/area_registry/delete": "ha_delete_area",
    "config/area_registry/list": "ha_list_areas",
    "config/area_registry/update": "ha_update_area",
    "config/category_registry/create": "ha_create_category",
    "config/category_registry/delete": "ha_delete_category",
    "config/category_registry/list": "ha_list_categories",
    "config/category_registry/update": "ha_update_category",
    "config/device_registry/list": "ha_list_devices",
    "config/device_registry/remove": "ha_remove_device",
    "config/device_registry/remove_config_entry": "ha_remove_device_from_config_entry",
    "config/device_registry/update": "ha_update_device",
    "config/entity_registry/get": "ha_get_entity_registry",
    "config/entity_registry/list": "ha_list_entities_registry",
    "config/entity_registry/remove": "ha_remove_entity_registry",
    "config/entity_registry/update": "ha_update_entity_registry",
    "config/floor_registry/create": "ha_create_floor",
    "config/floor_registry/delete": "ha_delete_floor",
    "config/floor_registry/list": "ha_list_floors",
    "config/floor_registry/update": "ha_update_floor",
    "config/label_registry/create": "ha_create_label",
    "config/label_registry/delete": "ha_delete_label",
    "config/label_registry/list": "ha_list_labels",
    "config/label_registry/update": "ha_update_label",
    # Integraciones.
    "config_entries/disable": "ha_disable_config_entry",
    "config_entries/get": "ha_list_config_entries",
    "config_entries/get_single": "ha_get_config_entry",
    # Spec 016 (tramo A, CAP-044): clase A de vía D con tool dedicada.
    "config_entries/flow/progress": "ha_list_discovered_integrations",
    "config_entries/ignore_flow": "ha_ignore_discovery",
    "config_entries/update": "ha_update_config_entry",
    # Spec 016 (tramo B, CAP-045).
    "config_entries/subentries/delete": "ha_delete_subentry",
    "config_entries/subentries/list": "ha_list_config_subentries",
    "config_entries/subentries/update": "ha_update_subentry",
    # Spec 016 (tramo C, CAP-048).
    "repairs/get_issue_data": "ha_get_repair",
    # Datos.
    "history/history_during_period": "ha_get_history",
    "logbook/get_events": "ha_get_logbook",
    "recorder/list_statistic_ids": "ha_list_statistic_ids",
    "recorder/statistics_during_period": "ha_statistics_during_period",
    "search/related": "ha_search_related",
    "trace/get": "ha_get_trace",
    "trace/list": "ha_list_traces",
    "repairs/ignore_issue": "ha_ignore_repair",
    "repairs/list_issues": "ha_list_repairs",
    # Lovelace.
    "frontend/get_system_data": "ha_list_lovelace_dashboards",
    "lovelace/config": "ha_get_lovelace_dashboard",
    "lovelace/config/save": "ha_save_lovelace_dashboard",
    "lovelace/dashboards/create": "ha_create_lovelace_dashboard",
    "lovelace/dashboards/delete": "ha_delete_lovelace_dashboard",
    "lovelace/dashboards/list": "ha_list_lovelace_dashboards",
    "lovelace/dashboards/update": "ha_update_lovelace_dashboard_metadata",
    "lovelace/resources/create": "ha_create_lovelace_resource",
    "lovelace/resources/delete": "ha_delete_lovelace_resource",
    "lovelace/resources/list": "ha_list_lovelace_resources",
    "lovelace/resources/update": "ha_update_lovelace_resource",
    # Marketplace (solo lectura).
    "marketplace/critical/list": "ha_marketplace_list_critical",
    "marketplace/info": "ha_marketplace_info",
    "marketplace/repositories/list": "ha_marketplace_list_repositories",
    "marketplace/repositories/removed": "ha_marketplace_list_removed",
    "marketplace/repository/releases": "ha_marketplace_list_releases",
    # Personas (create y update son tools distintas).
    "person/create": "ha_create_person",
    "person/delete": "ha_delete_person",
    "person/list": "ha_list_persons",
    "person/update": "ha_update_person",
    # 029: estado del sistema y estadísticas (clase A de vía D: el generador
    # consulta este mapa antes de la regla «pendiente»; research R-7).
    "system_health/info": "ha_get_system_health",
    "subscribe_system_state": "ha_get_system_state",
    "integration/setup_info": "ha_list_integration_setup_times",
    "manifest/list": "ha_list_integration_manifests",
    "manifest/get": "ha_get_integration_manifest",
    "recorder/info": "ha_get_recorder_info",
    "recorder/entity_options/get": "ha_get_recorder_info",
    "recorder/validate_statistics": "ha_validate_statistics",
    "recorder/get_statistics_metadata": "ha_get_statistics_metadata",
    # Diagnóstico de Core (spec 012). `logger/integration_log_level` es de
    # clase «cubierto» (por `logger.set_level`); las otras, de clase A con
    # vía D: `_clasificar` también consulta este mapa para ellas.
    "logger/integration_log_level": "ha_set_log_level",
    "logger/log_info": "ha_get_log_levels",
    "logger/log_level": "ha_set_log_level",
    "system_log/list": "ha_list_system_log",
    "validate_config": "ha_validate_config",
    "test_condition": "ha_test_condition",
    "diagnostics/list": "ha_list_diagnostics_handlers",
    "diagnostics/get": "ha_list_diagnostics_handlers",
    "persistent_notification/get": "ha_list_persistent_notifications",
    # Blueprints (spec 017), clase A de vía D: las cuatro del tramo A e
    # importar, del tramo B.
    "blueprint/list": "ha_list_blueprints",
    "blueprint/save": "ha_save_blueprint",
    "blueprint/delete": "ha_delete_blueprint",
    "blueprint/substitute": "ha_preview_blueprint_substitution",
    "blueprint/import": "ha_import_blueprint",
    # Ayuda para automatizar (spec 017, tramo C), clase A de vía D: lo que
    # ofrece un dispositivo (lista y capacidades van a la misma tool) y los
    # comandos de targets.
    "device_automation/trigger/list": "ha_list_device_triggers",
    "device_automation/trigger/capabilities": "ha_list_device_triggers",
    "device_automation/condition/list": "ha_list_device_conditions",
    "device_automation/condition/capabilities": "ha_list_device_conditions",
    "device_automation/action/list": "ha_list_device_actions",
    "device_automation/action/capabilities": "ha_list_device_actions",
    "extract_from_target": "ha_resolve_target",
    "explain_target": "ha_explain_target",
    "get_triggers_for_target": "ha_list_triggers_for_target",
    "get_conditions_for_target": "ha_list_conditions_for_target",
    "get_services_for_target": "ha_list_actions_for_target",
    # Espera de trigger (spec 017, tramo D): `subscribe_trigger` pasa de
    # clase B a A con CAP-038 en el inventario (research R-13); un solo
    # disparo, con lista cerrada de triggers.
    "subscribe_trigger": "ha_wait_for_trigger",
    # Restablecer un dashboard (spec 024, tramo 2), clase A de vía D+T
    # (CAP-071): la tool dedicada protege el principal y el panel por
    # defecto, que la genérica no puede.
    "lovelace/config/delete": "ha_reset_lovelace_dashboard_config",

    # ── Supervisor ──
    ("GET", "/addons"): "sv_list_addons",
    ("GET", "/addons/{app}/info"): "sv_get_addon",
    ("POST", "/addons/{app}/uninstall"): "sv_uninstall_addon",
    ("POST", "/addons/{app}/start"): "sv_start_addon",
    ("POST", "/addons/{app}/stop"): "sv_stop_addon",
    ("POST", "/addons/{app}/restart"): "sv_restart_addon",
    ("POST", "/addons/{app}/options"): "sv_set_addon_options",
    # bashio lee así las opciones de Hermes (solo `self`): no lo expone ninguna tool.
    ("GET", "/addons/{app}/options/config"): _INTERNO,
    ("GET", "/addons/{app}/stats"): "sv_get_addon_stats",
    ("GET", "/addons/{app}/logs"): "sv_get_addon_logs",
    ("GET", "/store/addons"): "sv_list_addons",
    ("GET", "/store/addons/{app}"): "sv_get_addon",
    ("POST", "/store/addons/{app}/install"): "sv_install_addon",
    ("POST", "/store/addons/{app}/update"): "sv_update_addon",
    ("GET", "/core/info"): "sv_get_core_info",
    ("POST", "/core/restart"): "sv_restart_core",
    ("POST", "/core/check"): "sv_check_core_config",
    ("GET", "/backups"): "sv_list_backups",
    ("POST", "/backups/new/partial"): "sv_create_backup_partial",
    ("POST", "/backups/new/full"): "sv_create_backup_full",
    ("GET", "/backups/{slug}/info"): "sv_get_backup",
    ("POST", "/backups/{slug}/restore/partial"): "sv_restore_backup_partial",
    ("POST", "/backups/{slug}/restore/full"): "sv_restore_backup_full",
    ("DELETE", "/backups/{slug}"): "sv_delete_backup",
    ("GET", "/host/info"): "sv_get_host_info",
    ("POST", "/host/reboot"): "sv_reboot_host",
    ("GET", "/supervisor/ping"): _INTERNO,
    ("GET", "/supervisor/info"): "sv_get_supervisor_info",
    ("GET", "/info"): "sv_get_supervisor_info",
    ("GET", "/jobs/{uuid}"): "sv_get_job_status",
    ("GET", "/resolution/info"): "sv_get_resolution",
    ("DELETE", "/resolution/suggestion/{suggestion}"): "sv_dismiss_resolution_suggestion",
    ("DELETE", "/resolution/issue/{issue}"): "sv_dismiss_resolution_issue",
    # 019: montajes del Supervisor y ajustes de backup (CAP-083), clase A de
    # vía D, por el mismo mecanismo que las de la 012 y la 029.
    ("GET", "/mounts"): "sv_list_mounts",
    ("POST", "/mounts"): "sv_create_mount",
    ("PUT", "/mounts/{mount}"): "sv_update_mount",
    ("DELETE", "/mounts/{mount}"): "sv_delete_mount",
    ("POST", "/mounts/{mount}/reload"): "sv_reload_mount",
    ("POST", "/mounts/options"): "sv_set_default_backup_mount",
    ("GET", "/backups/info"): "sv_get_backup_settings",
    ("POST", "/backups/options"): "sv_set_backup_settings",
    ("POST", "/backups/reload"): "sv_reload_backups",
    # 015: actualizaciones del sistema (CAP-080) y notas de versión de las
    # entidades `update` (CAP-064), clase A de vía D, por el mismo mecanismo.
    # `/refresh_updates` (clase B) no entra: la clase B no consulta el mapa,
    # y la tabla revisada la tiene `dedicated` (es la ruta que usa
    # `sv_check_for_updates`).
    ("GET", "/available_updates"): "sv_list_available_updates",
    ("POST", "/reload_updates"): _ConMatiz(
        "sv_check_for_updates",
        "que usa /refresh_updates: recarga también la tienda"),
    ("POST", "/core/update"): "sv_update_core",
    ("POST", "/os/update"): "sv_update_os",
    ("POST", "/supervisor/update"): "sv_update_supervisor",
    "update/release_notes": "ha_get_update_release_notes",
    # 013: logs del sistema (CAP-081) y disco, host y OS (CAP-085), clase A de
    # vía D, por el mismo mecanismo que las de la 012 y la 029.
    **{("GET", f"/{origen}/logs{sufijo}"): tool
       for origen, tool in (("core", "sv_get_core_logs"),
                            ("supervisor", "sv_get_supervisor_logs"),
                            ("dns", "sv_get_plugin_logs"),
                            ("audio", "sv_get_plugin_logs"),
                            ("multicast", "sv_get_plugin_logs"))
       for sufijo in ("", "/latest", "/boots/{bootid}")},
    ("GET", "/addons/{app}/logs/latest"): "sv_get_addon_logs",
    ("GET", "/addons/{app}/logs/boots/{bootid}"): "sv_get_addon_logs",
    ("GET", "/host/logs"): "sv_get_host_logs",
    ("GET", "/host/logs/boots/{bootid}"): "sv_get_host_logs",
    ("GET", "/host/logs/identifiers/{identifier}"): "sv_get_host_logs",
    ("GET", "/host/logs/boots/{bootid}/identifiers/{identifier}"): "sv_get_host_logs",
    ("GET", "/host/logs/identifiers"): "sv_list_host_log_identifiers",
    ("GET", "/host/logs/boots"): "sv_list_boots",
    ("GET", "/host/services"): "sv_list_host_services",
    ("GET", "/host/disks/{disk}/usage"): "sv_get_disk_usage",
    ("GET", "/os/info"): "sv_get_os_info",
    ("GET", "/os/config/swap"): "sv_get_swap",
    ("GET", "/os/datadisk/list"): "sv_list_datadisk_candidates",
    # 030: la tienda de apps (CAP-082) y la validación y reconstrucción de una
    # app (CAP-093), clase A de vía D y D+X, por el mismo mecanismo. Las tres
    # rutas con `{version}` van a la tool SIN versión de la 1.1.2: el
    # Supervisor 2026.11.0 ignora `{version}` (research R-2 de la 030).
    ("GET", "/store"): _ConMotivo(
        "sv_list_store_repositories",
        "cubierto por sv_list_store_repositories (repositorios) y sv_list_addons (apps)"),
    ("GET", "/store/repositories"): "sv_list_store_repositories",
    ("GET", "/store/repositories/{repository}"): _ConMotivo(
        "sv_list_store_repositories",
        "cubierto por sv_list_store_repositories(repository=…)"),
    ("POST", "/store/repositories"): "sv_add_store_repository",
    ("DELETE", "/store/repositories/{repository}"): "sv_remove_store_repository",
    ("POST", "/store/repositories/{repository}/repair"): "sv_repair_store_repository",
    ("POST", "/store/reload"): "sv_reload_store",
    ("GET", "/store/addons/{app}/changelog"): "sv_get_addon_changelog",
    ("GET", "/store/addons/{app}/documentation"): "sv_get_addon_documentation",
    ("GET", "/store/addons/{app}/availability"): "sv_get_addon_availability",
    ("GET", "/store/addons/{app}/{version}"): _ConMotivo(
        "sv_get_addon",
        "el Supervisor 2026.11.0 ignora `{version}` y devuelve la ficha actual: "
        "cubierto por sv_get_addon"),
    ("POST", "/store/addons/{app}/install/{version}"): _ConMotivo(
        "sv_install_addon",
        "el Supervisor 2026.11.0 ignora `{version}` e instala la de la tienda: "
        "cubierto por sv_install_addon"),
    ("POST", "/store/addons/{app}/update/{version}"): _ConMotivo(
        "sv_update_addon",
        "el Supervisor 2026.11.0 ignora `{version}` y actualiza a la de la tienda: "
        "cubierto por sv_update_addon"),
    ("POST", "/addons/{app}/options/validate"): _ConMatiz(
        "sv_set_addon_options", "valida en la vista previa"),
    ("POST", "/addons/{app}/rebuild"): "sv_rebuild_addon",
}

# Colecciones de helpers: list/create/update/delete con el mismo patrón de
# tools (`ha_list_<x>s`, `ha_create_or_update_<x>`, `ha_delete_<x>`).
for _dominio, _plural in (
    ("counter", "counters"), ("input_boolean", "input_booleans"),
    ("input_button", "input_buttons"), ("input_datetime", "input_datetimes"),
    ("input_number", "input_numbers"), ("input_select", "input_selects"),
    ("input_text", "input_texts"), ("schedule", "schedules"),
    ("timer", "timers"), ("zone", "zones"),
):
    _DEDICADAS_INICIALES[f"{_dominio}/list"] = f"ha_list_{_plural}"
    _DEDICADAS_INICIALES[f"{_dominio}/create"] = f"ha_create_or_update_{_dominio}"
    _DEDICADAS_INICIALES[f"{_dominio}/update"] = f"ha_create_or_update_{_dominio}"
    _DEDICADAS_INICIALES[f"{_dominio}/delete"] = f"ha_delete_{_dominio}"


# ── Lectura ──────────────────────────────────────────────────────────────────

Clave = str | tuple[str, str]


def _leer_tsv(ruta: pathlib.Path) -> list[dict[str, str]]:
    with ruta.open(encoding="utf-8", newline="") as f:
        return [
            {k: (v or "").strip() for k, v in fila.items()}
            for fila in csv.DictReader(f, delimiter="\t")
        ]


def _tools_por_nombre(tools_dir: pathlib.Path = _TOOLS) -> dict[str, str]:
    """Nombre de tool → familia, por AST (sin importar las tools)."""
    out: dict[str, str] = {}
    for path in sorted(tools_dir.glob("*.py")):
        arbol = ast.parse(path.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in nodo.decorator_list:
                if (
                    isinstance(deco, ast.Call)
                    and getattr(getattr(deco, "func", None), "attr", "") == "tool"
                ) or (isinstance(deco, ast.Attribute) and deco.attr == "tool"):
                    out[nodo.name] = familia_de_modulo(path.stem)
                    break
    return out


# ── Clasificación inicial ────────────────────────────────────────────────────


def _tokens(texto: str) -> set[str]:
    return set(re.split(r"[/_\-]", texto))


def _nota_limpia(nota: str) -> str:
    # Las notas del Supervisor empiezan por «Sí»/«No» (¿lo cubre Hermes?): para
    # el motivo que ve el cliente solo interesa el porqué.
    nota = re.sub(r"^(Sí|No)\b\s*", "", nota).strip()
    return nota


def _spec_pendiente(cap: str, escribe: bool) -> str:
    _via, lectura, escritura = MATRIZ[cap]
    return escritura if escribe else lectura


def _clasificar(
    clave: Clave,
    fila: dict[str, str],
    tools: dict[str, str],
) -> dict[str, object]:
    """Entrada inicial de una fila (reglas de research R-4)."""
    es_sv = isinstance(clave, tuple)
    texto = clave[1] if es_sv else clave
    metodo = clave[0] if es_sv else None
    clase = fila.get("clase", "")
    cap = fila.get("cap") or None
    nota = _nota_limpia(fila.get("nota", ""))
    base: dict[str, object] = {"family": FAMILIA_GENERICAS, "cap": cap}

    def deny(motivo: str) -> dict[str, object]:
        return {**base, "category": "deny", "reason": motivo}

    # El proxy de Core va antes que todo: aunque el inventario lo dé por
    # cubierto (Hermes lo usa por dentro), por la genérica sería una puerta
    # trasera a la API REST de Core.
    if es_sv and texto.startswith(_PREFIJOS_PROXY_CORE):
        return deny(_MOTIVO_PROXY)

    # Una fila cubierta por una tool dedicada, sea de clase «cubierto» o de
    # clase A cuya sub-feature ya creó su tool (specs 012, 013, 016 y 029;
    # research R-7): un solo constructor para las dos, para que una
    # generación desde cero dé la misma tabla que la revisada a mano.
    def dedicada(destino: str | _ConMatiz | _ConMotivo) -> dict[str, object]:
        if isinstance(destino, _ConMotivo):
            return {"category": "dedicated", "reason": destino.motivo,
                    "family": tools[destino.tool], "tool": destino.tool, "cap": cap}
        matiz = ""
        if isinstance(destino, _ConMatiz):
            matiz = f" ({destino.matiz})"
            destino = destino.tool
        # «(acción de HA)» solo si la cubre de verdad la acción genérica: una
        # fila cubierta por una acción que ya tiene tool dedicada (spec 012,
        # `logger/integration_log_level`) no se ejecuta como acción.
        de_accion = (fila.get("cobertura") == "accion-generica"
                     and destino.startswith("ha_call_service"))
        return {
            "category": "dedicated",
            "reason": (f"cubierto por {destino}" + (" (acción de HA)" if de_accion else "")
                       + matiz),
            "family": tools[destino],
            "tool": destino,
            "cap": cap,
        }

    if clase == "cubierto":
        destino = _DEDICADAS_INICIALES.get(clave)
        if destino is None:
            return deny("sin revisar")
        if isinstance(destino, _Deny):
            return deny(destino.motivo)
        return dedicada(destino)

    if clase == "B":
        return deny(f"{nota or 'sin utilidad para un cliente MCP'} (clase B)")
    if clase == "D":
        return deny(f"{nota or 'excluido por diseño'} (clase D)")
    if clase == "C":
        return deny("pendiente de revisión (spec 025)")
    if clase.startswith("A") and cap in MATRIZ:
        # Una fila A cuya sub-feature ya creó su tool está en el mapa (specs
        # 012 y 029, research R-7): se consulta antes que la regla
        # «pendiente», con el mismo constructor que las de clase «cubierto».
        destino = _DEDICADAS_INICIALES.get(clave)
        if isinstance(destino, (str, _ConMatiz, _ConMotivo)):
            return dedicada(destino)
        via = MATRIZ[cap][0]
        escribe = bool(_tokens(texto) & _VERBOS_ESCRITURA) or (es_sv and metodo != "GET")
        if via in ("D", "D+T", "D+X"):
            return deny(f"pendiente de tool dedicada (spec {_spec_pendiente(cap, escribe)})")
        etiqueta = nota or fila.get("area", "") or texto
        if not es_sv and "subscribe" in _tokens(texto):
            return deny(f"{etiqueta}: suscripción; {PROVISIONAL}")
        if escribe:
            return {**base, "category": "confirm",
                    "reason": f"{etiqueta}: escritura; {PROVISIONAL}"}
        return {**base, "category": "read",
                "reason": f"{etiqueta}: lectura; {PROVISIONAL}"}
    # Fila sin clase (nueva del extractor) o con una CAP fuera de la matriz.
    return deny("sin revisar")


# ── Escritura ────────────────────────────────────────────────────────────────

_ORDEN_KW = ("tool", "cap", "one_shot", "response", "redact_extra", "open_world", "example")
_POR_DEFECTO = {"tool": None, "cap": None, "one_shot": False, "response": "json",
                "redact_extra": (), "open_world": False, "example": None}


def _lit(valor: object) -> str:
    # JSON produce literales de cadena válidos en Python con comillas dobles,
    # sin depender de cómo `repr` elija las comillas. Pero `true`, `false` y
    # `null` no son Python: los booleanos y `None` (también dentro de un
    # `example` o de `redact_extra`) se escriben a mano.
    if valor is None or isinstance(valor, bool):
        return repr(valor)
    if isinstance(valor, dict):
        return "{" + ", ".join(f"{_lit(k)}: {_lit(v)}" for k, v in valor.items()) + "}"
    if isinstance(valor, (list, tuple)):
        cuerpo = ", ".join(_lit(v) for v in valor)
        if isinstance(valor, tuple):
            return f"({cuerpo},)" if len(valor) == 1 else f"({cuerpo})"
        return f"[{cuerpo}]"
    return json.dumps(valor, ensure_ascii=False)


def _clave_lit(clave: Clave) -> str:
    if isinstance(clave, tuple):
        return f"({_lit(clave[0])}, {_lit(clave[1])})"
    return _lit(clave)


def _render(clave: Clave, d: dict[str, object]) -> str:
    partes = [_lit(d["category"]), _lit(d["reason"]), _lit(d["family"])]
    for k in _ORDEN_KW:
        v = d.get(k, _POR_DEFECTO[k])
        if v != _POR_DEFECTO[k]:
            partes.append(f"{k}={_lit(v)}")
    return f"    {_clave_lit(clave)}: E({', '.join(partes)}),\n"


_CABECERA = '''"""Tabla de clasificación de los comandos WebSocket de Core y las rutas del
Supervisor para las tools genéricas (spec 011, FR-001, FR-002).

SE GENERA con scripts/inventario/generar_tabla.py desde los inventarios de
specs/008-cobertura-total/inventario/ y SE REVISA A MANO: después de la primera
generación, esta tabla es la fuente de verdad. Regenerar conserva cada entrada
revisada tal cual (con sus comentarios), añade lo nuevo como `deny` «sin
revisar» y quita lo que ya no existe.

Una entrada por línea y en orden de clave, para que una reclasificación sea
una línea del diff. Cada excepción del test de verbos y cada decisión no
evidente lleva un comentario con el porqué encima de su entrada.

Categorías: `dedicated` (la genérica la rechaza hacia su tool), `read` (solo
`ha_read_ws_command`/`sv_read_api`), `confirm` (solo `ha_call_ws_command`/
`sv_call_api`, siempre en dos pasos) y `deny`. Lo que no está, se rechaza.
Las comprobaciones están en tests/test_command_table.py.
"""

from __future__ import annotations

from hermes.command_policy import Entrada as E

'''


def _bloque(nombre: str) -> re.Pattern[str]:
    return re.compile(
        rf"^{nombre}: [^\n]*= \{{\n(?P<cuerpo>.*?)^\}}\n", re.M | re.S
    )


def _leer_tabla_previa(texto: str, nombre: str) -> dict[Clave, str]:
    """Clave → texto exacto de la entrada (con los comentarios de encima).

    Se lee por AST, sin importar el fichero. Una entrada puede ocupar varias
    líneas (p. ej. con un `example`); se acumulan hasta que el trozo es un
    elemento de diccionario válido.
    """
    m = _bloque(nombre).search(texto)
    if not m:
        raise ValueError(f"la tabla previa no tiene el bloque {nombre}")
    out: dict[Clave, str] = {}
    pendiente: list[str] = []   # comentarios que preceden a la entrada
    trozo: list[str] = []
    for linea in m.group("cuerpo").splitlines(keepends=True):
        if not trozo:
            if not linea.strip():
                continue
            if linea.lstrip().startswith("#"):
                pendiente.append(linea)
                continue
        trozo.append(linea)
        try:
            arbol = ast.parse("{\n" + "".join(trozo) + "}", mode="eval")
        except SyntaxError:
            continue
        nodo = arbol.body
        assert isinstance(nodo, ast.Dict) and len(nodo.keys) == 1
        clave = ast.literal_eval(nodo.keys[0])  # type: ignore[arg-type]
        if isinstance(clave, list):  # pragma: no cover - defensa
            clave = tuple(clave)
        out[clave] = "".join(pendiente) + "".join(trozo)
        pendiente, trozo = [], []
    if trozo:
        raise ValueError(f"entrada sin cerrar en {nombre}: {''.join(trozo)[:80]!r}")
    return out


def _version_previa(texto: str, nombre: str) -> str | None:
    m = re.search(rf'^{nombre} = "([^"]+)"$', texto, re.M)
    return m.group(1) if m else None


@dataclass
class Resultado:
    nuevas: list[Clave] = field(default_factory=list)
    quitadas: list[Clave] = field(default_factory=list)


def generar(
    core_tsv: pathlib.Path,
    supervisor_tsv: pathlib.Path,
    salida: pathlib.Path,
    *,
    ha_core: str,
    supervisor: str,
    tools_dir: pathlib.Path = _TOOLS,
) -> Resultado:
    """Escribe la tabla en `salida` y devuelve qué entró y qué salió."""
    core = {f["comando"]: f for f in _leer_tsv(core_tsv)}
    sv = {(f["metodo"], f["ruta"]): f for f in _leer_tsv(supervisor_tsv)}
    tools = _tools_por_nombre(tools_dir)

    previa_core: dict[Clave, str] | None = None
    previa_sv: dict[Clave, str] | None = None
    if salida.exists():
        texto = salida.read_text(encoding="utf-8")
        previa_core = _leer_tabla_previa(texto, "CORE_WS")
        previa_sv = _leer_tabla_previa(texto, "SUPERVISOR")

    resultado = Resultado()

    def bloque(filas: dict, previa: dict[Clave, str] | None, version: str) -> str:
        lineas: list[str] = []
        for clave in sorted(filas):
            if previa is not None and clave in previa:
                lineas.append(previa[clave])
                continue
            resultado.nuevas.append(clave)
            if previa is None:
                d = _clasificar(clave, filas[clave], tools)
            else:
                d = {"category": "deny", "reason": f"sin revisar (nuevo en {version})",
                     "family": FAMILIA_GENERICAS, "cap": filas[clave].get("cap") or None}
            lineas.append(_render(clave, d))
        if previa is not None:
            # Solo se conserva lo que sigue en el inventario: una entrada de un
            # comando que HA ya no tiene clasificaría algo que nadie revisa.
            resultado.quitadas.extend(sorted(k for k in previa if k not in filas))
        return "".join(lineas)

    cuerpo_core = bloque(core, previa_core, ha_core)
    cuerpo_sv = bloque(sv, previa_sv, supervisor)
    texto = (
        _CABECERA
        + f'TABLE_HA_CORE = "{ha_core}"\n'
        + f'TABLE_SUPERVISOR = "{supervisor}"\n\n'
        + "CORE_WS: dict[str, E] = {\n" + cuerpo_core + "}\n\n"
        + "SUPERVISOR: dict[tuple[str, str], E] = {\n" + cuerpo_sv + "}\n"
    )
    salida.write_text(texto, encoding="utf-8", newline="\n")
    return resultado


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--core", type=pathlib.Path, default=_INVENTARIO / "core-ws.tsv")
    p.add_argument("--supervisor-tsv", type=pathlib.Path,
                   default=_INVENTARIO / "supervisor-rutas.tsv")
    p.add_argument("--salida", type=pathlib.Path, default=_SALIDA)
    p.add_argument("--ha-core", default=None)
    p.add_argument("--supervisor", default=None)
    args = p.parse_args(argv)

    previo = args.salida.read_text(encoding="utf-8") if args.salida.exists() else ""
    ha_core = args.ha_core or _version_previa(previo, "TABLE_HA_CORE") or HA_CORE_POR_DEFECTO
    supervisor = (args.supervisor or _version_previa(previo, "TABLE_SUPERVISOR")
                  or SUPERVISOR_POR_DEFECTO)
    r = generar(args.core, args.supervisor_tsv, args.salida,
                ha_core=ha_core, supervisor=supervisor)
    print(f"Tabla escrita en {args.salida} (Core {ha_core}, Supervisor {supervisor}).")
    print(f"Entradas nuevas ({len(r.nuevas)}):")
    for k in r.nuevas:
        print(f"  + {k}")
    print(f"Entradas quitadas ({len(r.quitadas)}):")
    for k in r.quitadas:
        print(f"  - {k}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
