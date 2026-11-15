"""Hermes — Tools MCP: registro centralizado.

Cada módulo de tools expone una función register(mcp) que recibe la
instancia MCPServer y registra sus tools. Este patrón escala a N módulos
sin variables globales ni boilerplate repetido.
"""

from __future__ import annotations


def register_all_tools(
    mcp: object,
    ha_client: object,
    fire_event_allowlist: list[str] | None = None,
    response_max_bytes: int | None = None,
    safety_backup_window_minutes: int | None = None,
    safety_backup_enabled: bool | None = None,
    file_backup_max_per_path: int | None = None,
    file_backup_max_total_mb: int | None = None,
    config_write_min_interval_seconds: int | None = None,
    config_write_max_per_minute: int | None = None,
    call_service_denylist_extra: list[str] | None = None,
    call_service_restricted_entities: list[str] | None = None,
    call_service_auto_classify: bool | None = None,
    wait_for_event_max_seconds: int | None = None,
    wait_for_event_max_concurrent: int | None = None,
    safety_backup_keep: int | None = None,
    tool_families_disabled: list[str] | None = None,
) -> None:
    """Registra todas las tools disponibles en el servidor MCP.

    Cada fase añade una línea aquí. `fire_event_allowlist` viene de las
    opciones del add-on; si `None`, se lee `HERMES_FIRE_EVENT_ALLOWLIST`
    del entorno vía `load_config()`. `response_max_bytes` controla el límite
    de truncado en las tools; si `None`, se lee de config.

    `tool_families_disabled` (spec 011, FR-020): familias de
    `tool_families.py` cuyas tools no se registran. Cada bloque de registro va
    dentro de `if _activa("<familia>")` con la familia de su módulo (lo
    comprueba un test por AST): un bloque nuevo sin esa comprobación se
    registraría aunque el usuario apagara su familia.
    """
    needs_cfg = (
        fire_event_allowlist is None
        or response_max_bytes is None
        or safety_backup_window_minutes is None
        or safety_backup_enabled is None
        or file_backup_max_per_path is None
        or file_backup_max_total_mb is None
        or config_write_min_interval_seconds is None
        or config_write_max_per_minute is None
        or call_service_denylist_extra is None
        or call_service_restricted_entities is None
        or call_service_auto_classify is None
        or wait_for_event_max_seconds is None
        or wait_for_event_max_concurrent is None
        or safety_backup_keep is None
        or tool_families_disabled is None
    )
    if needs_cfg:
        from hermes.config import load_config
        cfg = load_config()
        if fire_event_allowlist is None:
            fire_event_allowlist = cfg.fire_event_allowlist
        if response_max_bytes is None:
            response_max_bytes = cfg.response_max_bytes
        if safety_backup_window_minutes is None:
            safety_backup_window_minutes = cfg.safety_backup_window_minutes
        if safety_backup_enabled is None:
            safety_backup_enabled = cfg.safety_backup_enabled
        if file_backup_max_per_path is None:
            file_backup_max_per_path = cfg.file_backup_max_per_path
        if file_backup_max_total_mb is None:
            file_backup_max_total_mb = cfg.file_backup_max_total_mb
        if config_write_min_interval_seconds is None:
            config_write_min_interval_seconds = cfg.config_write_min_interval_seconds
        if config_write_max_per_minute is None:
            config_write_max_per_minute = cfg.config_write_max_per_minute
        if call_service_denylist_extra is None:
            call_service_denylist_extra = cfg.call_service_denylist_extra
        if call_service_restricted_entities is None:
            call_service_restricted_entities = cfg.call_service_restricted_entities
        if call_service_auto_classify is None:
            call_service_auto_classify = cfg.call_service_auto_classify_dangerous
        if wait_for_event_max_seconds is None:
            wait_for_event_max_seconds = cfg.wait_for_event_max_seconds
        if wait_for_event_max_concurrent is None:
            wait_for_event_max_concurrent = cfg.wait_for_event_max_concurrent
        if safety_backup_keep is None:
            safety_backup_keep = cfg.safety_backup_keep
        if tool_families_disabled is None:
            tool_families_disabled = cfg.tool_families_disabled

    # Se valida otra vez aquí y no solo en `HermesConfig.validate()`: quien
    # llame sin pasar por el arranque (tests, herramientas) tampoco debe poder
    # registrar con un nombre mal escrito ni apagar `base` (fail-closed).
    from hermes.tool_families import validar_desactivadas
    desactivadas = validar_desactivadas(tool_families_disabled or [])

    def _activa(familia: str) -> bool:
        return familia not in desactivadas

    # El tope vale para TODAS las tools, no solo para las que lo reciben
    # (spec 006): lo aplica el servidor al final de cada `tools/call`.
    from hermes.mcp_server import HermesMCPServer
    if isinstance(mcp, HermesMCPServer):
        mcp.response_max_bytes = response_max_bytes

    # ping y test_progress
    if _activa("base"):
        from hermes.tools.ping import register as register_ping
        register_ping(mcp)

    # Onboarding: guía de uso (hermes_guide) para el cliente MCP
    if _activa("base"):
        from hermes.tools.guide import register as register_guide
        register_guide(mcp)

    # estados y servicios de Home Assistant
    if _activa("services"):
        from hermes.tools.ha import register as register_ha_tools
        register_ha_tools(
            mcp,
            ha_client,
            call_service_denylist_extra=call_service_denylist_extra,
            call_service_restricted_entities=call_service_restricted_entities,
            call_service_auto_classify=call_service_auto_classify,
        )

    # automations via WS
    if _activa("automations"):
        from hermes.tools.automations import register as register_automation_tools
        register_automation_tools(mcp, ha_client)

    # scripts via REST
    if _activa("automations"):
        from hermes.tools.scripts import register as register_script_tools
        register_script_tools(mcp, ha_client)

    # scenes via REST
    if _activa("automations"):
        from hermes.tools.scenes import register as register_scene_tools
        register_scene_tools(mcp, ha_client)

    # helpers input_* + counter/timer/schedule via WS collection
    if _activa("helpers"):
        from hermes.tools.input_boolean import register as register_input_boolean
        register_input_boolean(mcp, ha_client)

        from hermes.tools.input_number import register as register_input_number
        register_input_number(mcp, ha_client)

        from hermes.tools.input_select import register as register_input_select
        register_input_select(mcp, ha_client)

        from hermes.tools.input_text import register as register_input_text
        register_input_text(mcp, ha_client)

        from hermes.tools.input_datetime import register as register_input_datetime
        register_input_datetime(mcp, ha_client)

        from hermes.tools.input_button import register as register_input_button
        register_input_button(mcp, ha_client)

        from hermes.tools.counter import register as register_counter
        register_counter(mcp, ha_client)

        from hermes.tools.timer import register as register_timer
        register_timer(mcp, ha_client)

        from hermes.tools.schedule import register as register_schedule
        register_schedule(mcp, ha_client)
    # Zonas, personas y disparo de eventos.
    if _activa("helpers"):
        from hermes.tools.zones import register as register_zones
        register_zones(mcp, ha_client)

        from hermes.tools.persons import register as register_persons
        register_persons(mcp, ha_client)

    if _activa("events"):
        from hermes.tools.events import register as register_events
        register_events(mcp, ha_client, fire_event_allowlist)

    # history, logbook, render_template, statistics
    if _activa("data"):
        from hermes.tools.templates import register as register_templates
        register_templates(mcp, ha_client)

        from hermes.tools.history import register as register_history
        register_history(mcp, ha_client, response_max_bytes=response_max_bytes)

        from hermes.tools.logbook import register as register_logbook
        register_logbook(mcp, ha_client, response_max_bytes=response_max_bytes)

        from hermes.tools.statistics import register as register_statistics
        register_statistics(mcp, ha_client, response_max_bytes=response_max_bytes)

    # registries (entity, device, area, floor, label, category)
    if _activa("registries"):
        from hermes.tools.registry_entity import register as register_registry_entity
        register_registry_entity(mcp, ha_client, response_max_bytes=response_max_bytes)

        from hermes.tools.registry_device import register as register_registry_device
        register_registry_device(mcp, ha_client, response_max_bytes=response_max_bytes)

        from hermes.tools.registry_area import register as register_registry_area
        register_registry_area(mcp, ha_client)

        from hermes.tools.registry_floor import register as register_registry_floor
        register_registry_floor(mcp, ha_client)

        from hermes.tools.registry_label import register as register_registry_label
        register_registry_label(mcp, ha_client)

        from hermes.tools.registry_category import register as register_registry_category
        register_registry_category(mcp, ha_client)

    # Diagnóstico: repairs, trazas y relaciones. Trazas y relaciones reciben
    # `response_max_bytes`: una traza larga pesa megas y `search/related` de
    # una integración grande, 200 ids por cada uno de 14 tipos.
    if _activa("diagnostics"):
        from hermes.tools.repairs import register as register_repairs
        register_repairs(mcp, ha_client)

        from hermes.tools.traces import register as register_traces
        register_traces(mcp, ha_client, response_max_bytes=response_max_bytes)

        from hermes.tools.search import register as register_search
        register_search(mcp, ha_client, response_max_bytes=response_max_bytes)

    # config entries y flows
    if _activa("config_entries"):
        from hermes.tools.config_entries import register as register_config_entries
        register_config_entries(mcp, ha_client, response_max_bytes=response_max_bytes)

        from hermes.tools.config_entry_flows import register as register_config_entry_flows
        register_config_entry_flows(mcp, ha_client)

    # filesystem /config (lectura)
    if _activa("filesystem"):
        from hermes.tools.filesystem import register as register_filesystem
        register_filesystem(mcp, response_max_bytes=response_max_bytes)

    # filesystem /config (escritura)
    if _activa("filesystem"):
        from hermes.tools.filesystem_write import register_write as register_filesystem_write
        register_filesystem_write(
            mcp,
            ha_client,
            safety_backup_window_minutes=safety_backup_window_minutes,
            safety_backup_enabled=safety_backup_enabled,
            file_backup_max_per_path=file_backup_max_per_path,
            file_backup_max_total_mb=file_backup_max_total_mb,
            config_write_min_interval_seconds=config_write_min_interval_seconds,
            config_write_max_per_minute=config_write_max_per_minute,
            safety_backup_keep=safety_backup_keep,
        )

    # Supervisor — add-ons, supervisor/host/core, backups
    if _activa("supervisor"):
        from hermes.tools.addons import register as register_addons
        register_addons(mcp, ha_client, response_max_bytes=response_max_bytes)

        from hermes.tools.supervisor import register as register_supervisor
        register_supervisor(mcp, ha_client)

    if _activa("backups"):
        from hermes.tools.backups import register as register_backups
        register_backups(
            mcp,
            ha_client,
            safety_backup_window_minutes=safety_backup_window_minutes,
        )

    # Spec 019: montajes de red y de disco del Supervisor (familia `mounts`,
    # 1.2.0). Va después de `backups` porque es donde acaban los backups.
    if _activa("mounts"):
        from hermes.tools.mounts import register as register_mounts
        register_mounts(mcp, ha_client)
        # Tramo 2: los ajustes de backup del Supervisor, misma familia.
        from hermes.tools.backup_settings import register as register_backup_settings
        register_backup_settings(mcp, ha_client)

    # Spec 032, tramo 1: apagar el host, hostname, swap y ranura de arranque
    # (familia `host_control`, 1.2.0). Todas confirman en dos pasos.
    if _activa("host_control"):
        from hermes.tools.host_control import register as register_host_control
        register_host_control(mcp, ha_client)

    # Spec 032, tramo 2: la red del host (familia `host_network`, 1.2.0):
    # recargar (sin token), editar una interfaz secundaria y crear una VLAN.
    if _activa("host_network"):
        from hermes.tools.host_network import register as register_host_network
        register_host_network(mcp, ha_client)

    # Centro de resolución del Supervisor (lee y descarta; aplicar una
    # sugerencia es de `resolution_fixes`, spec 022) y backups de la integración `backup` de HA, que ven todas
    # las ubicaciones y no solo las locales del Supervisor.
    if _activa("diagnostics"):
        from hermes.tools.resolution import register as register_resolution
        register_resolution(mcp, ha_client)

    if _activa("backups"):
        from hermes.tools.ha_backups import register as register_ha_backups
        register_ha_backups(mcp, ha_client, response_max_bytes=response_max_bytes)

    # Lovelace dashboards y resources.
    # Cada módulo hay que registrarlo aquí explícitamente. Olvidar una de
    # estas llamadas no da ningún error: el servidor arranca igual y sus tools
    # simplemente no existen para el cliente. Lo vigila un test.
    if _activa("lovelace"):
        from hermes.tools.lovelace import register as register_lovelace
        register_lovelace(mcp, ha_client, response_max_bytes=response_max_bytes)

    # Gestor de esperas compartido (spec 017, research R-8): `ha_wait_for_event`
    # y `ha_wait_for_trigger` cuentan en el MISMO cupo
    # (`wait_for_event_max_concurrent`); con dos gestores, el tope real sería
    # el doble del configurado. Se crea una sola vez, aunque alguna de las dos
    # familias esté apagada.
    from hermes.tools.wait_for_event import _WaitManager
    gestor_de_esperas = _WaitManager(max_concurrent=wait_for_event_max_concurrent)

    # wait_for_event, Marketplace y alias HACS
    if _activa("events"):
        from hermes.tools.wait_for_event import register as register_wait_for_event
        register_wait_for_event(
            mcp,
            ha_client,
            wait_for_event_max_seconds=wait_for_event_max_seconds,
            wait_for_event_max_concurrent=wait_for_event_max_concurrent,
            manager=gestor_de_esperas,
        )

    # El Marketplace va antes que los alias `ha_hacs_*` para que el cliente vea
    # primero las tools nuevas; los alias solo reenvían a sus funciones.
    if _activa("marketplace"):
        from hermes.tools.marketplace import register as register_marketplace
        register_marketplace(mcp, ha_client, response_max_bytes=response_max_bytes)

        from hermes.tools.hacs import register as register_hacs
        register_hacs(mcp, ha_client, response_max_bytes=response_max_bytes)

    # Diagnóstico del sistema (spec 013): logs de Core, del Supervisor, de los
    # plugins y del host, también de arranques anteriores. Solo leen. Reciben
    # `response_max_bytes` para devolver las ÚLTIMAS líneas que caben en vez
    # de que el guardián central cambie el log entero por un error.
    # Con ellos, servicios del host, uso de disco, OS y swap (tramo 2). Los
    # servicios recortan su lista a `response_max_bytes`; el uso de disco poda
    # a 20 hijos por nivel y, si aun así no cabe, pliega las carpetas más
    # pequeñas en `children_omitted`/`omitted_bytes` hasta caber, para que el
    # guardián central no quite ramas enteras sin cuadrar la suma.
    if _activa("system_diagnostics"):
        from hermes.tools.system_logs import register as register_system_logs
        register_system_logs(mcp, ha_client, response_max_bytes=response_max_bytes)

        from hermes.tools.host_system import register as register_host_system
        register_host_system(mcp, ha_client, response_max_bytes=response_max_bytes)

    # Estado del sistema de Core (spec 029, CAP-043): salud, reinicio
    # pendiente, tiempos de arranque y manifiestos. Solo lee.
    if _activa("system_status"):
        from hermes.tools.system_status import register as register_system_status
        register_system_status(mcp, ha_client, response_max_bytes=response_max_bytes)

    # El recorder y las estadísticas de largo plazo (spec 029, CAP-049):
    # estado, validación y metadatos; y el mantenimiento de estadísticas de
    # la 020.
    if _activa("recorder"):
        from hermes.tools.recorder_status import register as register_recorder_status
        register_recorder_status(mcp, ha_client, response_max_bytes=response_max_bytes)
        # Spec 020 (CAP-050): el mantenimiento de estadísticas, en la misma
        # familia (quien la apaga apaga lectura y escritura del recorder).
        from hermes.tools.statistics_maintenance import (
            register as register_statistics_maintenance,
        )
        register_statistics_maintenance(mcp, ha_client, response_max_bytes=response_max_bytes)
    # Preferencias del panel de energía (spec 020, CAP-054): leer y guardar,
    # esta última con confirmación. Recibe el tope porque las preferencias
    # son un documento que no se recorta (`response_too_large`).
    if _activa("energy"):
        from hermes.tools.energy import register as register_energy
        register_energy(mcp, ha_client, response_max_bytes=response_max_bytes)
    # Diagnóstico de Core (spec 012): logs y niveles de log, validación,
    # diagnósticos de integraciones y notificaciones persistentes. Reciben
    # `response_max_bytes` las que pueden devolver mucho: el log del sistema
    # guarda hasta 50 grupos con trazas enteras, el de errores hasta 1000
    # líneas y un diagnóstico de Z-Wave o ZHA ocupa varios MB.
    if _activa("core_diagnostics"):
        from hermes.tools.core_logs import register as register_core_logs
        register_core_logs(mcp, ha_client, response_max_bytes=response_max_bytes)

        from hermes.tools.core_validation import register as register_core_validation
        register_core_validation(mcp, ha_client)

        from hermes.tools.integration_diagnostics import (
            register as register_integration_diagnostics,
        )
        register_integration_diagnostics(mcp, ha_client, response_max_bytes=response_max_bytes)

        from hermes.tools.persistent_notifications import (
            register as register_persistent_notifications,
        )
        register_persistent_notifications(mcp, ha_client, response_max_bytes=response_max_bytes)
    # Integraciones más allá de instalarlas (spec 016): descubiertos,
    # dominios configurables y título y preferencias de una entrada.
    if _activa("integration_flows"):
        from hermes.tools.integration_setup import register as register_integration_setup
        register_integration_setup(mcp, ha_client, response_max_bytes=response_max_bytes)
        from hermes.tools.config_subentries import register as register_config_subentries
        register_config_subentries(mcp, ha_client, response_max_bytes=response_max_bytes)

    # Flujos de reparación de Repairs (spec 016, tramo C): el aviso con sus
    # datos internos y el arreglo con token en cada paso.
    if _activa("repair_flows"):
        from hermes.tools.repair_flows import register as register_repair_flows
        register_repair_flows(mcp, ha_client, response_max_bytes=response_max_bytes)
    # Actualizaciones del sistema (spec 015): listar, buscar y actualizar
    # Core con una vista previa que dice versiones, backup, bloqueos y
    # comprobación de configuración, y un token atado a las versiones.
    # Recibe `response_max_bytes` para recortar la lista de actualizaciones
    # (con muchas apps) en vez de que el guardián central la cambie por un
    # error.
    if _activa("system_updates"):
        from hermes.tools.system_updates import register as register_system_updates
        register_system_updates(mcp, ha_client, response_max_bytes=response_max_bytes)

        # Tramo 3: las entidades `update` de Core (firmware, integraciones,
        # HACS…), con el encaminamiento de las de la integración `hassio` a
        # las `sv_*` y el rechazo de la de Hermes.
        from hermes.tools.update_entities import register as register_update_entities
        register_update_entities(mcp, ha_client, response_max_bytes=response_max_bytes)

    # Tienda de apps del Supervisor (spec 030): repositorios y recarga (tramo
    # 1), fichas, disponibilidad y reconstrucción (tramo 2). Añadir y quitar
    # un repositorio y reconstruir una app piden confirmación; la lista y los
    # textos reciben `response_max_bytes` para recortarse (lista por el final
    # con `truncated`, textos por trozos con `next_offset`).
    if _activa("app_store"):
        from hermes.tools.store_apps import register as register_store_apps
        from hermes.tools.store_repositories import register as register_store_repositories
        register_store_repositories(mcp, ha_client, response_max_bytes=response_max_bytes)
        register_store_apps(mcp, ha_client, response_max_bytes=response_max_bytes)

    # Blueprints (spec 017, CAP-046): listar, ver la sustitución, guardar y
    # borrar. Guardar y borrar piden token. Reciben `response_max_bytes` la
    # lista (un blueprint por fichero, sin tope en HA) y la sustitución (una
    # configuración cortada no sirve: si no cabe, `response_too_large`).
    if _activa("blueprints"):
        from hermes.tools.blueprints import register as register_blueprints
        register_blueprints(mcp, ha_client, response_max_bytes=response_max_bytes)

    # Ayuda para escribir automatizaciones (spec 017, CAP-051 y CAP-052): lo
    # que ofrece un dispositivo y qué abarca un target. Solo lee. Reciben
    # `response_max_bytes` las dos: un dispositivo con muchas entidades (y
    # sus capacidades) o un área grande dan listas largas.
    if _activa("automation_assist"):
        from hermes.tools.device_automation import (
            register as register_device_automation,
        )
        register_device_automation(mcp, ha_client, response_max_bytes=response_max_bytes)

        from hermes.tools.targets import register as register_targets
        register_targets(mcp, ha_client, response_max_bytes=response_max_bytes)

        # Espera de trigger (spec 017, tramo D): mismo gestor y mismo tope
        # de segundos que `ha_wait_for_event`.
        from hermes.tools.wait_for_trigger import register as register_wait_for_trigger
        register_wait_for_trigger(
            mcp,
            ha_client,
            manager=gestor_de_esperas,
            wait_for_event_max_seconds=wait_for_event_max_seconds,
            response_max_bytes=response_max_bytes,
        )

    # Control de Core y del Supervisor (spec 022, CAP-084): arrancar,
    # reconstruir y configurar Core; recargar, reiniciar, reparar y
    # configurar el Supervisor. Todo lo que corta pide token.
    if _activa("system_control"):
        from hermes.tools.system_control import register as register_system_control
        register_system_control(mcp, ha_client, response_max_bytes=response_max_bytes)

    # Aplicar sugerencias del centro de resolución (spec 022, tramo 2,
    # CAP-087): con vista previa que traduce el efecto y token.
    if _activa("resolution_fixes"):
        from hermes.tools.resolution_fixes import register as register_resolution_fixes
        register_resolution_fixes(mcp, ha_client, response_max_bytes=response_max_bytes)

    # Configuración del sistema (spec 021, tramo a): el núcleo (nombre,
    # ubicación, unidades, zona horaria, URLs) y la exposición de entidades a
    # los asistentes de voz. Dos familias para poder apagar la exposición,
    # que puede mandar entidades a la nube de un tercero, sin perder el resto.
    if _activa("core_config"):
        from hermes.tools.core_config import register as register_core_config
        register_core_config(mcp, ha_client, response_max_bytes=response_max_bytes)

    if _activa("assistant_exposure"):
        from hermes.tools.assistant_exposure import register as register_assistant_exposure
        register_assistant_exposure(mcp, ha_client, response_max_bytes=response_max_bytes)

    # Usuarios (spec 021, tramo b): familia propia para poder apagar lo que
    # crea, edita y borra cuentas sin perder el resto de la configuración.
    if _activa("users"):
        from hermes.tools.users import register as register_users
        register_users(mcp, ha_client, response_max_bytes=response_max_bytes)

    # Red y HTTP de Core (spec 021, tramo c): familia propia, de riesgo alto
    # (cambiar el HTTP reinicia HA y puede dejarla inaccesible).
    if _activa("core_network"):
        from hermes.tools.core_network import register as register_core_network
        register_core_network(mcp, ha_client, response_max_bytes=response_max_bytes)

    # Assist y conversación (spec 023): agentes, frases de los disparadores,
    # análisis sin ejecutar y procesar una frase, esta siempre en dos pasos.
    if _activa("conversation"):
        from hermes.tools.conversation import register as register_conversation
        register_conversation(mcp, ha_client, response_max_bytes=response_max_bytes)

    # Genéricas (spec 011): la cola larga de Core y del Supervisor, solo lo
    # que la tabla de comandos permite. Van las últimas para que el cliente vea
    # antes las tools dedicadas, que son las que debe preferir.
    if _activa("generic_commands"):
        from hermes.tools.generic_commands import register as register_generic_commands
        # Reciben las familias desactivadas para no ser una vía hacia lo que
        # el usuario apagó (`use_dedicated_tool` con `family_disabled`, o
        # `family_disabled` si la entrada es de una familia apagada).
        register_generic_commands(
            mcp,
            ha_client,
            response_max_bytes=response_max_bytes,
            familias_desactivadas=desactivadas,
        )

    # Anotaciones MCP (readOnly / destructive / idempotent / openWorld).
    # Se aplican al final, sobre todo lo ya registrado, para que los clientes
    # puedan distinguir lo que solo lee de lo que borra o reinicia.
    from hermes.tools._annotations import apply_tool_annotations
    stats = apply_tool_annotations(mcp)
    import structlog
    _log = structlog.get_logger(__name__)
    if stats.get("annotated"):
        _log.info("tool_annotations_applied", **stats)
    else:
        # Registrar solo el caso bueno dejaría el malo sin rastro ninguno
        # en el arranque.
        _log.error("tool_annotations_missing", reason="no_tool_was_annotated", **stats)

    # Qué familias se apagaron y cuántas tools quedan: sin esto, una tool
    # «desaparecida» por la opción no dejaría rastro en el log del add-on.
    _log.info(
        "tool_families",
        disabled=sorted(desactivadas),
        tools_registered=_contar_tools(mcp),
    )


def _contar_tools(mcp: object) -> int:
    """Número de tools registradas (servidor real o doble de los tests)."""
    try:
        return len(mcp._tool_manager._tools)  # type: ignore[attr-defined]  # noqa: SLF001
    except AttributeError:
        return len(getattr(mcp, "tools", {}))
