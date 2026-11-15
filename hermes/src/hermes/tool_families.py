"""Catálogo de familias de tools (spec 011, FR-019).

POR QUÉ EXISTE ESTE MÓDULO
--------------------------
Con el programa de cobertura total, Hermes pasa de 216 tools a más de 300. Un
cliente con poco contexto, o un usuario que no usa Lovelace ni el Marketplace,
quiere poder apagar grupos enteros con una opción (`tool_families_disabled`).
Una familia agrupa módulos de `hermes/tools/` por área —las mismas áreas que
los temas de `hermes_guide`— para que el usuario entienda qué desactiva.

Es un módulo neutral, como `service_policy.py`: no importa nada de Hermes. Lo
usan `config.py` (para validar la opción al arrancar, sin importar las tools y
sin crear ciclos), el registro de tools y la tabla de comandos (la familia de
cada entrada).

Las familias de la 1.1.2 agrupan exactamente las 216 tools de esa versión; las
tools nuevas del programa van en familias de la 1.2.0 (FR-010 de la 008), de
modo que, desactivando todas las de la 1.2.0, la lista de tools vuelve a ser
la de la 1.1.2.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

_FORMA_NOMBRE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class Familia:
    """Un grupo de módulos de tools que se activa o desactiva junto."""

    nombre: str
    # En inglés: es lo que ve el usuario en DOCS.md y en el log de arranque.
    descripcion: str
    # Versión en la que aparece la familia («1.1.2» o «1.2.0»).
    desde: str
    desactivable: bool
    # Nombres de módulos de `hermes/tools/` (sin `.py`).
    modulos: tuple[str, ...]


_CATALOGO: tuple[Familia, ...] = (
    # `base` no se puede desactivar: sin `hermes_guide` el cliente no sabe usar
    # el resto de tools, y `ping` es la sonda de salud con la que el cliente
    # comprueba que Hermes responde. Apagarlas dejaría un servidor inutilizable
    # que además parecería caído.
    Familia("base", "Health check and the usage guide (always on).",
            "1.1.2", False, ("ping", "guide")),
    Familia("services", "States, services and actions.",
            "1.1.2", True, ("ha",)),
    Familia("automations", "Automations, scripts and scenes.",
            "1.1.2", True, ("automations", "scripts", "scenes")),
    Familia("helpers", "Helpers (input_*, counters, timers, schedules), zones and persons.",
            "1.1.2", True, (
                "input_boolean", "input_button", "input_datetime", "input_number",
                "input_select", "input_text", "counter", "timer", "schedule",
                "zones", "persons",
            )),
    Familia("events", "Fire and wait for events.",
            "1.1.2", True, ("events", "wait_for_event")),
    Familia("data", "Templates, history, logbook and statistics.",
            "1.1.2", True, ("templates", "history", "logbook", "statistics")),
    Familia("registries", "Area, category, device, entity, floor and label registries.",
            "1.1.2", True, (
                "registry_area", "registry_category", "registry_device",
                "registry_entity", "registry_floor", "registry_label",
            )),
    Familia("diagnostics", "Repairs, traces, related search and Supervisor resolution center.",
            "1.1.2", True, ("repairs", "traces", "search", "resolution")),
    Familia("config_entries", "Integrations (config entries) and their config and options flows.",
            "1.1.2", True, ("config_entries", "config_entry_flows")),
    Familia("filesystem", "Read and write files under /config.",
            "1.1.2", True, ("filesystem", "filesystem_write")),
    Familia("supervisor", "Add-ons, Core, host and Supervisor information and control.",
            "1.1.2", True, ("addons", "supervisor")),
    Familia("backups", "Supervisor backups and Home Assistant backup integration.",
            "1.1.2", True, ("backups", "ha_backups")),
    Familia("lovelace", "Lovelace dashboards and resources.",
            "1.1.2", True, ("lovelace",)),
    Familia("marketplace", "Marketplace and HACS (read only).",
            "1.1.2", True, ("marketplace", "hacs")),
    # Familias de la 1.2.0.
    Familia("generic_commands",
            "Generic tools that run Core WebSocket commands and Supervisor API "
            "routes allowed by Hermes' classification table.",
            "1.2.0", True, ("generic_commands",)),
    # Spec 013 (research R-1): logs de Core, del Supervisor, de los plugins y
    # del host, también de arranques anteriores. Una sola familia para todo el
    # diagnóstico del sistema porque es un mismo caso de uso y cabe en un tema
    # de la guía; va aparte de `supervisor` para que apagar las familias de la
    # 1.2.0 deje exactamente la lista de la 1.1.2 (FR-010 de la 008). El
    # módulo `host_system` (tramo 2: servicios del host, uso de disco, OS y
    # swap) es el otro lado del mismo diagnóstico y también solo lee.
    Familia("system_diagnostics",
            "Supervisor, Core, host and plugin logs; host services, disk "
            "usage, OS and swap (read only).",
            "1.2.0", True, ("system_logs", "host_system")),
    # Spec 029 (CAP-043): todo de solo lectura.
    Familia("system_status",
            "System health, pending restart state, integration setup times and "
            "manifests (read only).",
            "1.2.0", True, ("system_status",)),
    # Spec 029 (CAP-049). La familia es la del recorder entero, no solo de
    # sus lecturas: la 020 (CAP-050) añade el mantenimiento de estadísticas
    # (`statistics_maintenance`), que escribe con confirmación. Por eso la
    # descripción ya no dice «read only» (principio V), y quien apague
    # `recorder` apaga lo que lee y lo que escribe en la base de estadísticas.
    Familia("recorder",
            "Recorder status and long-term statistics: validation, metadata and "
            "maintenance (clear, change units, fix metadata, adjust sums, import; "
            "with confirmation).",
            "1.2.0", True, ("recorder_status", "statistics_maintenance")),
    # Spec 012: una sola familia para el diagnóstico de Core y no una por
    # módulo (research R-9): es un área y un tema de la guía, y partirla
    # daría opciones que nadie pediría. No es `diagnostics` (1.1.2: Repairs,
    # trazas, relaciones y resolución del Supervisor), que no cambia.
    Familia("core_diagnostics",
            "Home Assistant system log, error log and log levels, configuration "
            "validation, integration diagnostics and persistent notifications.",
            "1.2.0", True,
            ("core_logs", "core_validation", "integration_diagnostics",
             "persistent_notifications")),
    # Spec 020 (CAP-054): las preferencias del panel de energía. Familia
    # propia y no `recorder`: el panel es de la integración `energy`, que
    # puede no estar cargada aunque el recorder sí, y quien no usa el panel
    # puede apagarla sin perder el mantenimiento de estadísticas.
    Familia("energy",
            "Energy dashboard preferences: read and save (with confirmation).",
            "1.2.0", True, ("energy",)),
)

FAMILIAS: dict[str, Familia] = {f.nombre: f for f in _CATALOGO}

# Nombres antiguos de familias renombradas → nombre actual. Hoy vacío.
#
# POR QUÉ: `tool_families_disabled` se guarda en las opciones del add-on. Si
# una versión futura renombra una familia, quien tenga guardado el nombre
# viejo no puede quedarse sin arrancar al actualizar (el nombre «no existiría»)
# ni, peor aún, con la familia activa sin saberlo. Al renombrar, se añade aquí
# `"nombre_viejo": "nombre_nuevo"` y se mantiene al menos durante una versión
# mayor. Un alias nunca puede llevar a desactivar `base`: la comprobación de
# `desactivable` se hace sobre el nombre actual. Lo vigila
# tests/test_tool_families.py (`TestAliasDeFamilias`).
ALIAS: dict[str, str] = {}

_FAMILIA_DE_MODULO: dict[str, str] = {
    modulo: familia.nombre for familia in _CATALOGO for modulo in familia.modulos
}


def familia_de_modulo(modulo: str) -> str:
    """Nombre de la familia de un módulo de `hermes/tools/`.

    Lanza `KeyError` si el módulo no está en ninguna: un módulo sin familia no
    se podría desactivar, y los tests lo impiden.
    """
    return _FAMILIA_DE_MODULO[modulo]


def validar_desactivadas(
    nombres: Iterable[str],
    *,
    alias: Mapping[str, str] | None = None,
) -> frozenset[str]:
    """Valida la opción `tool_families_disabled` y devuelve el conjunto de
    nombres actuales.

    Fail-closed: un nombre desconocido o `base` lanza `ValueError` para que
    Hermes no arranque con una configuración que no hace lo que el usuario
    cree (por ejemplo, una errata que dejaría activa una familia que quería
    apagar). El mensaje nombra el valor inválido y los válidos. Los duplicados
    no son un error: se ignoran. Un nombre antiguo de `ALIAS` (o de `alias`,
    que solo pasan los tests) se traduce al actual antes de comprobarlo.
    """
    tabla_alias = ALIAS if alias is None else alias
    validos = sorted(n for n, f in FAMILIAS.items() if f.desactivable)
    resultado: set[str] = set()
    for nombre in nombres:
        if not isinstance(nombre, str) or not _FORMA_NOMBRE.match(nombre):
            raise ValueError(
                f"tool_families_disabled: nombre de familia inválido {nombre!r}. "
                f"Válidas: {', '.join(validos)}"
            )
        nombre = tabla_alias.get(nombre, nombre)
        if nombre not in FAMILIAS:
            raise ValueError(
                f"tool_families_disabled: la familia {nombre!r} no existe. "
                f"Válidas: {', '.join(validos)}"
            )
        if not FAMILIAS[nombre].desactivable:
            raise ValueError(
                f"tool_families_disabled: la familia {nombre!r} no se puede "
                f"desactivar (ping y hermes_guide son necesarios). "
                f"Válidas: {', '.join(validos)}"
            )
        resultado.add(nombre)
    return frozenset(resultado)
