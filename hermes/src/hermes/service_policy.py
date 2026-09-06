"""Política de servicios peligrosos, compartida por el cliente y las tools.

POR QUÉ EXISTE ESTE MÓDULO
--------------------------
La tool `ha_call_service` no es el único camino hacia el endpoint REST de
servicios: `HAClient.call_service` —el método de bajo nivel— es una segunda
puerta, y por ella entran decenas de llamadas repartidas por todo el árbol de
tools (`ha_run_script`, `ha_trigger_automation`, las tools de `reload`,
`ha_activate_scene`…).

Aplicar la política solo en la tool deja al guardia en la puerta principal
mientras las de servicio siguen abiertas: un objeto creado por una tool puede
acabar invocando un servicio de la denylist a través de otra, sin que nadie pida
confirmación por el efecto real. Por eso la comprobación vive en el punto por el
que pasa TODO el tráfico, no en una de las dos puertas.

Y vive en un módulo propio porque `hermes.tools.ha` importa de `hermes.ha`:
poner la política en la primera crearía un ciclo. Este módulo es neutral —no
importa nada de Hermes— y lo usan ambas capas.
"""

from __future__ import annotations


class DangerousServiceError(Exception):
    """Se intentó invocar un servicio de la denylist sin autorización explícita.

    La lanza `HAClient.call_service` cuando `allow_dangerous` es False, que es
    el valor por defecto: quien quiera ejecutar uno de estos servicios tiene que
    pedirlo a conciencia, y hoy el único camino que lo hace es la tool
    `ha_call_service`, después de validar su `confirmation_token`.
    """


# ── Denylist ─────────────────────────────────────────────────────────────────
# Servicios que siempre exigen confirmation_token.
# Formato: "domain.service" o "domain.*" (wildcard solo en service).

CALL_SERVICE_DENYLIST: frozenset[str] = frozenset({
    # Ejecución arbitraria
    "shell_command.*",
    "python_script.*",
    # Reloads que pueden activar YAML envenenado
    "homeassistant.reload_all",
    "homeassistant.reload_config_entry",
    "homeassistant.reload_core_config",
    "automation.reload", "script.reload", "scene.reload",
    "template.reload", "group.reload", "zone.reload",
    "person.reload", "tag.reload", "intent_script.reload",
    "frontend.reload_themes",
    "input_boolean.reload", "input_text.reload", "input_number.reload",
    "input_select.reload", "input_datetime.reload", "input_button.reload",
    "counter.reload", "timer.reload", "schedule.reload",
    "rest_command.reload", "shell_command.reload",
    "notify.reload", "lovelace.reload_resources",
    # MQTT
    "mqtt.publish", "mqtt.dump",
    # Host y core
    "homeassistant.restart", "homeassistant.stop",
    "hassio.host_reboot", "hassio.host_shutdown",
    # Add-ons (legacy + modern naming)
    "hassio.addon_install", "hassio.addon_uninstall",
    "hassio.addon_update", "hassio.addon_start",
    "hassio.addon_stop", "hassio.addon_restart",
    "hassio.addon_stdin",
    "hassio.app_install", "hassio.app_uninstall",
    "hassio.app_update", "hassio.app_start",
    "hassio.app_stop", "hassio.app_restart", "hassio.app_stdin",
    "hassio.supervisor_update", "hassio.core_update", "hassio.os_update",
    # Backups (ambos paths)
    "hassio.backup_full", "hassio.backup_partial",
    "hassio.restore_full", "hassio.restore_partial",
    "backup.create", "backup.create_automatic",
    # Destrucción
    "recorder.purge", "recorder.purge_entities",
    # Físico sensible
    "lock.unlock",
    "alarm_control_panel.alarm_disarm",
    "alarm_control_panel.alarm_arm_custom_bypass",
    # IA recursiva
    "conversation.process",
    # Ofuscación de rastros
    "logger.set_level", "system_log.clear",
    "persistent_notification.dismiss", "persistent_notification.dismiss_all",
    "homeassistant.set_location", "device_tracker.see",
    # Lo que se veta es el EFECTO, no una variante concreta del servicio:
    "lock.open",        # acciona el pestillo; más grave aún que lock.unlock
    "update.install",   # misma actualización que hassio.*_update, por otra vía
})


def is_in_denylist(domain: str, service: str, denylist: frozenset[str]) -> bool:
    """¿Está `domain.service` en la denylist? Soporta wildcard en el servicio."""
    if f"{domain}.{service}" in denylist:
        return True
    return f"{domain}.*" in denylist


# ── Entidades auto-restringidas ──────────────────────────────────────────────
# Scripts y automatizaciones cuyo contenido invoca servicios de la denylist.
# Se rellena al arrancar y tras cada creación o recarga.

_auto_restricted: set[str] = set()


def get_auto_restricted_entities() -> frozenset[str]:
    """Snapshot del set de entidades auto-restringidas."""
    return frozenset(_auto_restricted)


def set_auto_restricted_entities(entity_ids: set[str]) -> None:
    """Reemplaza el set completo (lo llama la re-clasificación)."""
    _auto_restricted.clear()
    _auto_restricted.update(entity_ids)


def add_auto_restricted_entity(entity_id: str) -> None:
    """Añade una entidad recién detectada como peligrosa."""
    _auto_restricted.add(entity_id)


# ── ¿Apunta esta llamada a una entidad restringida? ──────────────────────────

# Claves con las que HA permite apuntar a entidades SIN nombrarlas: no se pueden
# resolver desde aquí sin consultar los registros.
_INDIRECT_TARGET_KEYS: frozenset[str] = frozenset(
    {"area_id", "device_id", "label_id", "floor_id"}
)

# Comodín de Home Assistant: alcanza todas las entidades del dominio.
_MATCH_ALL = "all"


def _collect_entity_ids(data: dict) -> set[str]:
    """Extrae los entity_id de un service_data, normalizando como HA.

    `cv.entity_ids` de Home Assistant parte por comas, hace strip y pasa a
    minúsculas. Hay que normalizar igual antes de comparar contra el set de
    restringidas: una igualdad exacta contra el campo `entity_id` tal cual vería
    `"script.inocuo, script.peligroso"` como UN literal que no está en el set,
    mientras HA ejecuta los dos.
    """
    found: set[str] = set()
    for container in (data, data.get("target") or {}):
        if not isinstance(container, dict):
            continue
        raw = container.get("entity_id")
        if raw is None:
            continue
        values = [raw] if isinstance(raw, str) else list(raw or [])
        for value in values:
            if not isinstance(value, str):
                continue
            for piece in value.split(","):
                piece = piece.strip().lower()
                if piece:
                    found.add(piece)
    return found


def targets_restricted_entity(
    domain: str, data: dict, restricted: frozenset[str]
) -> bool:
    """¿Puede esta llamada alcanzar una entidad restringida?

    Falla cerrado ante lo que no puede resolver:

    - `entity_id: all` es el comodín de HA y alcanza todo el dominio.
    - `area_id` / `device_id` / `label_id` / `floor_id` apuntan a entidades sin
      nombrarlas; resolverlos exigiría consultar los registros. Ignorarlos sería
      un hueco, así que se exige confirmación **cuando el dominio de la llamada
      coincide con el de alguna entidad restringida**. Así una llamada a
      `script.turn_on` por área sí la pide, y un `light.turn_on` por área no,
      que sería ruido inútil.
    """
    if not restricted or not isinstance(data, dict):
        return False

    entity_ids = _collect_entity_ids(data)
    if entity_ids & restricted:
        return True

    domain_lower = domain.strip().lower()
    restricted_domains = {e.split(".", 1)[0] for e in restricted if "." in e}

    if _MATCH_ALL in entity_ids and domain_lower in restricted_domains:
        return True

    has_indirect = any(
        key in container
        for container in (data, data.get("target") or {})
        if isinstance(container, dict)
        for key in _INDIRECT_TARGET_KEYS
    )
    return has_indirect and domain_lower in restricted_domains
