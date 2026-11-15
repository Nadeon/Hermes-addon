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
    # Spec 031 (CAP-057): los backups de la integración `backup` de HA
    # (agentes, ajustes, crear, borrar y restaurar). Familia propia y no `backups` (1.1.2), para que apagar las
    # de la 1.2.0 deje la lista de la 1.1.2 (FR-010 de la 008).
    Familia("backup_integration",
            "Home Assistant backup integration: backup agents, automatic "
            "backup settings, and creating, deleting and restoring backups.",
            "1.2.0", True, ("ha_backup_settings", "ha_backup_actions",
                            "ha_backup_restore")),
    # Spec 016. Dos familias y no una (research R-8): quien no quiere que el
    # agente aplique arreglos de Repairs (`repair_flows`, tramo C) puede
    # quitarlos sin perder la gestión de integraciones, y al revés. No amplían
    # `config_entries` ni `diagnostics` porque FR-010 de la 008 exige familias
    # nuevas: desactivando las de la 1.2.0 tiene que quedar la lista de la
    # 1.1.2. El tramo B añadió `config_subentries` (subentries y reconfigure).
    Familia("integration_flows",
            "Discovered integrations, config entry preferences, config "
            "subentries and reconfigure flows.",
            "1.2.0", True, ("integration_setup", "config_subentries")),
    # Tramo C: los flujos de reparación. `ha_list_repairs` y
    # `ha_ignore_repair` siguen en `diagnostics` (sus textos traducidos son un
    # cambio de la 1.1.2, no tools nuevas).
    Familia("repair_flows",
            "Repairs issue details and fix flows.",
            "1.2.0", True, ("repair_flows",)),
    # Spec 019 (research R-1): montajes de red del Supervisor (CIFS, NFS y
    # disco local) y sus ajustes de backup. Una capacidad, una familia: quien
    # no tiene NAS ni discos externos la apaga entera. Va aparte de `backups`
    # para que apagar las familias de la 1.2.0 deje la lista de la 1.1.2
    # (FR-010 de la 008). `backup_settings` (tramo 2) va aquí y no en
    # `backups`: sus ajustes son a dónde van los backups y cuándo envejecen,
    # y `backups` es de la 1.1.2 y no puede ganar tools.
    Familia("mounts",
            "Supervisor network mounts (CIFS/NFS) and local disk mounts for "
            "backups, media and share, and the Supervisor's backup settings.",
            "1.2.0", True, ("mounts", "backup_settings")),
    # Spec 015 (research R-1): actualizar Core, OS, Supervisor y las entidades
    # `update` es un solo asunto para el usuario («mantener el sistema al
    # día»), así que va en UNA familia: con dos, apagar una dejaría media
    # funcionalidad sin que se entendiera por qué. Va aparte de `supervisor`
    # y `services` (familias de la 1.1.2) para que apagar las de la 1.2.0
    # deje la lista de la 1.1.2 (FR-010 de la 008). El tramo 3 añade el
    # módulo `update_entities` (las entidades `update` de Core).
    Familia("system_updates",
            "Check for and install updates of Core, OS, Supervisor and "
            "update entities.",
            "1.2.0", True, ("system_updates", "update_entities")),
    # Spec 030 (research R-1): la tienda de apps del Supervisor. Va aparte de
    # `supervisor` (familia de la 1.1.2) para que apagar las familias de la
    # 1.2.0 deje exactamente la lista de la 1.1.2 (FR-010 de la 008), y es una
    # sola familia para repositorios y fichas de apps porque es un mismo caso
    # de uso y un tema de la guía. Dos módulos, uno por tramo:
    # `store_repositories` (repositorios y recarga) y `store_apps` (changelog,
    # documentación, disponibilidad y reconstrucción).
    Familia("app_store",
            "App store: repositories, store reload, app changelog, "
            "documentation and availability, and app rebuild.",
            "1.2.0", True, ("store_repositories", "store_apps")),
    # Spec 017 (research R-10): los blueprints van solos y no en
    # `automations` (1.1.2), para que apagar las familias de la 1.2.0 deje la
    # lista de la 1.1.2 (FR-010 de la 008), y no con la ayuda para automatizar
    # (`automation_assist`) porque son otro caso de uso: estas escriben en
    # /config (guardar, importar y borrar ficheros), aquellas solo leen. Quien
    # no quiera que el cliente toque blueprints la apaga sin perder la ayuda.
    Familia("blueprints",
            "Automation, script and template blueprints: list, preview a "
            "substitution, save and delete.",
            "1.2.0", True, ("blueprints",)),
    # Spec 017 (research R-10): la ayuda para escribir automatizaciones, toda
    # de solo lectura: lo que ofrece un dispositivo (`device_automation`) y
    # qué abarca un target y qué se puede hacer con él (`targets`). No va en
    # `automations` (1.1.2) por FR-010 de la 008, ni con `blueprints`, que
    # escribe en /config. `wait_for_trigger` (tramo D) va aquí y no en
    # `events` (1.1.2) por lo mismo: FR-010 de la 008 pide familias nuevas
    # para las tools nuevas; comparte con `ha_wait_for_event` solo el gestor
    # de esperas.
    Familia("automation_assist",
            "Help to write automations: device triggers, conditions and "
            "actions, resolving a target and what can be done with it, and "
            "waiting once for a trigger (read only).",
            "1.2.0", True, ("device_automation", "targets", "wait_for_trigger")),
    # Spec 020 (CAP-054): las preferencias del panel de energía. Familia
    # propia y no `recorder`: el panel es de la integración `energy`, que
    # puede no estar cargada aunque el recorder sí, y quien no usa el panel
    # puede apagarla sin perder el mantenimiento de estadísticas.
    Familia("energy",
            "Energy dashboard preferences: read and save (with confirmation).",
            "1.2.0", True, ("energy",)),
    # Spec 022 (research R-1): arrancar, reconstruir y configurar Core, y
    # recargar, reiniciar, reparar y configurar el Supervisor. Familia propia
    # y no `supervisor` (1.1.2) para que apagar las de la 1.2.0 deje la lista
    # de la 1.1.2 (FR-010 de la 008), y para que quien no quiera que un
    # agente corte Core o el Supervisor la apague sin perder lo demás.
    Familia("system_control",
            "Start, rebuild and configure Home Assistant Core; reload, restart, "
            "repair and configure the Supervisor.",
            "1.2.0", True, ("system_control",)),
    # Spec 022, tramo 2 (research R-1): aplicar sugerencias del centro de
    # resolución. Familia propia y no `diagnostics` (1.1.2, que solo lee y
    # descarta) ni `system_control`: quien no quiera que un agente aplique
    # arreglos del Supervisor (algunos borran backups o reinician el host)
    # la apaga sola, sin perder el resto.
    Familia("resolution_fixes",
            "Apply Supervisor resolution suggestions after a preview that "
            "explains their effect.",
            "1.2.0", True, ("resolution_fixes",)),
    # Spec 021 (research R-9): la configuración del sistema va en familias
    # por área y por riesgo, para que quien quiera apagar lo de riesgo alto
    # (usuarios, red y HTTP, en los tramos b y c) lo haga sin perder el resto.
    # El tramo a trae dos: el núcleo y la exposición a asistentes (esta,
    # aparte, porque puede mandar entidades a la nube de un tercero).
    Familia("core_config",
            "Core configuration: name, location, units, time zone, currency, "
            "country, language and URLs.",
            "1.2.0", True, ("core_config",)),
    Familia("assistant_exposure",
            "Which entities Assist, conversation agents and the cloud voice "
            "assistants can see and control.",
            "1.2.0", True, ("assistant_exposure",)),
    # Tramo b: los usuarios, aparte y desactivables por su riesgo (crean,
    # editan y borran cuentas de la casa). Nunca contraseñas ni tokens.
    Familia("users",
            "Home Assistant users: list, create without credentials, edit and "
            "delete. Never passwords or tokens.",
            "1.2.0", True, ("users",)),
    # Tramo c: red y HTTP de Core, aparte por su riesgo (cambiar el HTTP
    # reinicia HA y puede dejarla inaccesible). No es la red del host, que es
    # del Supervisor (spec 032): solo lo que guarda Core.
    Familia("core_network",
            "Core network adapters and HTTP server configuration (port, SSL, "
            "reverse proxy).",
            "1.2.0", True, ("core_network",)),
    # Spec 032 (research R-1): apagar el host, el hostname, la swap y la
    # ranura de arranque. Una familia aparte de la red del host (tramo 2,
    # `host_network`) porque el riesgo es de otro orden: quien quiere que el
    # agente cambie la swap no tiene por qué darle la red. No va en
    # `supervisor` (1.1.2: FR-010 de la 008 pide familias nuevas) ni en
    # `system_diagnostics`, que solo lee y dejaría de decir verdad.
    Familia("host_control",
            "Shut down the host and change its hostname, swap and Home "
            "Assistant OS boot slot (all with confirmation).",
            "1.2.0", True, ("host_control",)),
    # Spec 032, tramo 2 (research R-1): la red del host (recargar, editar una
    # interfaz que no sea la de acceso, crear una VLAN). Familia propia porque
    # un error aquí puede dejar la casa sin acceso y el Supervisor no revierte:
    # quien no quiera darle la red al agente la quita sin perder el resto.
    Familia("host_network",
            "Host network: reload the network state, edit a secondary "
            "interface (never the primary one) and create VLANs (changes "
            "with confirmation).",
            "1.2.0", True, ("host_network",)),
    # Spec 023 (research R-1): Assist y conversación. Una familia y un módulo
    # porque es un solo caso de uso («usar y depurar Assist») y un tema de la
    # guía. Va aparte de `services` (familia de la 1.1.2, donde vive
    # `ha_call_service_response`) para que apagar las familias de la 1.2.0
    # deje exactamente la lista de la 1.1.2 (FR-010 de la 008). No es de
    # solo lectura: `ha_process_conversation` ejecuta, con confirmación.
    Familia("conversation",
            "Assist conversation agents, custom sentences, sentence analysis "
            "and sending a sentence to Assist (with confirmation).",
            "1.2.0", True, ("conversation",)),
    # Spec 024 (research R-3): la instantánea de una cámara y la imagen de una
    # entidad `image` van solas porque son las únicas tools que devuelven
    # imágenes, y una cámara puede enseñar el interior de la casa: quien no
    # quiera que el cliente MCP las vea apaga esta familia sin perder nada
    # más. No van en `services` (1.1.2) por FR-010 de la 008. Activa por
    # defecto: si debe venir apagada es la duda D-03 de la 008.
    Familia("cameras",
            "Camera snapshots and image entities (returns images).",
            "1.2.0", True, ("cameras",)),
    # Spec 024, tramo 2 (research R-3): restablecer un dashboard borra toda su
    # configuración guardada. Va en su propia familia porque la `lovelace` de
    # la 1.1.2 no puede ganar tools (FR-010 de la 008: apagando las familias
    # de la 1.2.0 vuelve la lista exacta de la 1.1.2), y así quien no quiera
    # que el cliente pueda vaciar un dashboard la apaga sola.
    Familia("dashboard_reset",
            "Reset a Lovelace dashboard to its auto-generated config.",
            "1.2.0", True, ("lovelace_reset",)),
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
