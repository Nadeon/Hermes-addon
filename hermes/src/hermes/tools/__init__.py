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

    # Centro de resolución del Supervisor (lee y descarta; nunca aplica
    # sugerencias) y backups de la integración `backup` de HA, que ven todas
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

    # wait_for_event, Marketplace y alias HACS
    if _activa("events"):
        from hermes.tools.wait_for_event import register as register_wait_for_event
        register_wait_for_event(
            mcp,
            ha_client,
            wait_for_event_max_seconds=wait_for_event_max_seconds,
            wait_for_event_max_concurrent=wait_for_event_max_concurrent,
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
