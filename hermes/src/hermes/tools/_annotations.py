"""Anotaciones MCP (`ToolAnnotations`) para las tools de Hermes.

El protocolo MCP permite que cada tool declare *hints* de comportamiento:

    read_only_hint    no modifica nada
    destructive_hint  puede destruir datos o interrumpir el servicio
    idempotent_hint   repetirla deja el mismo estado final
    open_world_hint   habla con sistemas externos (internet), no solo con HA

Nota sobre los nombres: en el SDK 2.x los campos pasaron de camelCase
(`readOnlyHint`) a snake_case. Es solo el nombre del atributo en Python; el
JSON que viaja al cliente sigue siendo camelCase, como exige la spec, porque
pydantic serializa por alias.

Los clientes las usan para decidir la experiencia de permisos: autorizar sin
preguntar lo que solo lee, y avisar antes de lo que borra o reinicia. Hermes
expone ~210 tools sobre una casa entera, así que esa distinción importa.

Se aplican de forma centralizada tras registrar las tools (ver
`apply_tool_annotations`) en vez de repetir `annotations=...` en 211
decoradores: una sola tabla, revisable de un vistazo y verificada por tests.

Nota de la spec: son *hints*, no garantías. La seguridad real de Hermes no
depende de esto, sino de la denylist, los confirmation tokens y el sandbox de
`/config`. Aquí solo se le dice la verdad al cliente sobre lo que hace cada tool.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

from mcp.types import ToolAnnotations

# ── Solo lectura ──────────────────────────────────────────────────────────────
# Prefijos que nunca modifican estado.
_READ_ONLY_PREFIXES: tuple[str, ...] = (
    "ha_get_", "ha_list_", "sv_get_", "sv_list_",
    "fs_read_", "fs_list_", "fs_stat", "fs_search_",
    "ha_hacs_",
)
_READ_ONLY_EXACT: frozenset[str] = frozenset({
    "ping",
    "test_progress",
    "hermes_guide",
    "ha_render_template",
    "ha_statistics_during_period",
    "ha_wait_for_event",      # bloquea a la espera, pero no cambia nada
    # `search/related` solo consulta el grafo de relaciones de HA; su nombre
    # no encaja con ningún prefijo de lectura.
    "ha_search_related",
    # Marketplace (spec 004): por nombre exacto y NO por el prefijo
    # `ha_marketplace_`. Si un día se añade una tool que instala o acepta el
    # aviso de riesgos con ese prefijo, heredaría `readOnlyHint` sin que nadie
    # lo decidiera: fail-closed, la que no esté aquí no se anuncia inofensiva.
    "ha_marketplace_info",
    "ha_marketplace_list_repositories",
    "ha_marketplace_get_repository",
    "ha_marketplace_list_updates",
    "ha_marketplace_list_releases",
    "ha_marketplace_list_critical",
    "ha_marketplace_list_removed",
    # Dos que parecen encajar aquí y no encajan: sv_check_core_config y
    # sv_get_job_status escriben. Ver _NOT_READ_ONLY_EXACT más abajo.
})

# ── Destructivas ──────────────────────────────────────────────────────────────
# Pérdida de datos o interrupción del servicio. Todas exigen confirmation_token.
_DESTRUCTIVE_PREFIXES: tuple[str, ...] = (
    "ha_delete_", "ha_remove_", "sv_delete_", "sv_uninstall_", "sv_restore_",
    "fs_delete_",
    # Un upsert sobre un id que ya existe REEMPLAZA la configuración entera.
    "ha_create_or_update_",
)
# Estas cumplen el criterio del módulo —«puede destruir datos o interrumpir el
# servicio»— sin que su nombre lo delate:
#
#   ha_disable_config_entry   deshabilita una integración entera, con sus
#                             entidades y sus devices. Hacerlo con Z-Wave,
#                             Zigbee o la alarma deja la casa sin control.
#   ha_update_entity_registry renombrar el entity_id rompe en silencio toda
#                             automatización, script, escena y tarjeta que
#                             apunte al id viejo.
#   ha_update_device          `disabled_by` deshabilita el device Y todas sus
#                             entidades: un solo id se lleva decenas por delante.
#   ha_create_or_update_*     `config_save` REEMPLAZA la configuración completa,
#                             no hace merge; el propio preview enseña
#                             {"current": …, "new": …} porque sabe que pisa algo.
_DESTRUCTIVE_EXACT: frozenset[str] = frozenset({
    "ha_disable_config_entry",
    "ha_update_entity_registry",
    "ha_update_device",
    "fs_write_file",              # sobrescribe el fichero entero
    "fs_move_file",               # puede pisar el destino
    "fs_restore_file_backup",     # sobrescribe el estado actual
    "fs_set_secret",              # reescribe secrets.yaml
    "ha_save_lovelace_dashboard", # reemplaza la config completa del dashboard
    "sv_restart_core",
    "sv_reboot_host",
    "sv_restart_addon",
    "sv_stop_addon",
    "sv_set_addon_options",       # puede dejar un add-on sin arrancar
    "ha_call_service",            # servicio arbitrario: asumir lo peor
    "ha_call_service_response",
    # Estas piden `confirmation_token`, que es la señal de que quien las
    # escribió las consideró consecuentes. Si una herramienta se hace confirmar
    # y a la vez se anuncia inofensiva, el cliente la trata como inocua y solo
    # descubre lo contrario al llamarla. El invariante lo vigila un test.
    "ha_run_script",              # ejecuta lo que el script contenga
    "ha_trigger_automation",      # dispara sus acciones, sean cuales sean
    "ha_reload_automations",      # materializa lo que haya en el YAML
    "ha_reload_counters",
    "ha_reload_scenes",
    "ha_reload_schedules",
    "ha_reload_scripts",
    "ha_reload_timers",
    "ha_reload_zones",
    "ha_update_area",             # renombrar un área reordena la casa entera
    "ha_update_person",
    "ha_create_lovelace_resource",   # carga JS en cada navegador que abra HA
    "ha_update_lovelace_resource",
    "ha_update_lovelace_dashboard_metadata",
    "sv_start_addon",
    "sv_install_addon",
    "sv_update_addon",            # puede romper un add-on que funcionaba
    # Spec 005: se hacen confirmar y su nombre no lo delata.
    "ha_update_floor",            # renombrarla cambia cómo la llaman Assist y la UI
    "ha_update_label",            # la etiqueta la usan automatizaciones y tarjetas
    "ha_update_category",         # reorganiza automatizaciones, scripts o helpers
    "ha_ignore_repair",           # oculta un aviso de HA que puede ser importante
    # Ocultan un aviso del Supervisor (instalación no saludable, sugerencia
    # pendiente): quien lo descarta deja de verlo aunque el problema siga.
    "sv_dismiss_resolution_issue",
    "sv_dismiss_resolution_suggestion",
})

# ── Mundo abierto ─────────────────────────────────────────────────────────────
# Salen de la instalación local (descargas, repositorios remotos).
_OPEN_WORLD: frozenset[str] = frozenset({
    "sv_install_addon", "sv_update_addon",
    # Un resource Lovelace con URL externa hace que CADA navegador que abra HA
    # descargue y ejecute JavaScript de un tercero, que puede robar el token de
    # HA del navegador. Mismo criterio que sv_install_addon: quien descarga no
    # es Hermes, pero la descarga la provoca esta tool.
    "ha_create_lovelace_resource", "ha_update_lovelace_resource",
    # De todo el Marketplace, solo las versiones publicadas se piden a GitHub
    # (a través de HA). El resto, y los alias `ha_hacs_*`, leen lo que HA ya
    # tiene en memoria; antes de 1.1.0 los alias se anunciaban de mundo abierto
    # porque `ha_hacs_get_repository` pedía `repository/info`, que sí sale.
    "ha_marketplace_list_releases",
})

# ── No idempotentes ───────────────────────────────────────────────────────────
# Repetirlas cambia el resultado (acumulan o alternan).
_NON_IDEMPOTENT_PREFIXES: tuple[str, ...] = (
    "ha_increment_", "ha_decrement_", "ha_toggle_", "ha_cycle_",
    "ha_create_", "ha_press_", "ha_fire_", "ha_trigger_", "ha_run_",
    "sv_create_",
)

# `ha_change_timer` mapea a `timer.change`, y su docstring dice que `duration` es
# un DELTA: llamarla dos veces suma dos veces, igual que ha_increment_counter. No
# encaja con ningún prefijo, así que hay que marcarla a mano. Un cliente que
# reintente tras un timeout de red duplicaría el delta: es el caso de uso
# canónico de idempotent_hint.
_NON_IDEMPOTENT_EXACT: frozenset[str] = frozenset({"ha_change_timer"})

# Excepción: un upsert SÍ es idempotente (repetirlo con la misma config deja el
# mismo estado). Empieza por `ha_create_`, así que hay que sacarlo a mano.
_IDEMPOTENT_OVERRIDE_PREFIXES: tuple[str, ...] = ("ha_create_or_update_",)


# Excepciones a los prefijos de solo lectura. El prefijo es una heurística
# cómoda pero ciega: estas dos escriben pese a llamarse `sv_get_*` / `sv_check_*`.
_NOT_READ_ONLY_EXACT: frozenset[str] = frozenset({
    # El POST /core/check solo valida, pero acto seguido se escribe
    # check_config_state.json y con ello se LEVANTA el bloqueo que impide
    # reiniciar HA con configuración sin validar: anunciarla read_only sería
    # mentir sobre una decisión de seguridad.
    "sv_check_core_config",
    # Además del GET, escribe pending_jobs.json cuando el job ha terminado.
    # Impacto bajo —contabilidad interna—, pero read_only tiene que significar
    # que no modifica NADA.
    "sv_get_job_status",
})


# ── Título legible ────────────────────────────────────────────────────────────
# El cliente enseña `title` al usuario en lugar del nombre técnico. Se genera
# del nombre, igual que los hints, para que haya un solo sitio que revisar y
# ninguna tool se quede sin título al añadirla (FR-040). El prefijo pasa a ser
# un sufijo de área: sin él, `sv_get_backup` y una futura `ha_get_backup`
# tendrían el mismo título y el usuario no sabría cuál está autorizando.
_TITLE_AREAS: tuple[tuple[str, str], ...] = (
    ("ha_", " (Home Assistant)"),
    ("fs_", " (files)"),
    ("sv_", " (Supervisor)"),
)

# Palabras que no se escriben como salen del nombre: siglas y nombres propios.
_TITLE_WORDS: dict[str, str] = {
    "hacs": "HACS",
    "lovelace": "Lovelace",
    "hermes": "Hermes",
    "id": "ID",
    "ids": "IDs",
    "ws": "WS",
    # «addon» es como se escribe en el código; Home Assistant lo llama add-on.
    "addon": "add-on",
    "addons": "add-ons",
}


def title_for(name: str) -> str:
    """Título en inglés para una tool: `ha_get_state` → `Get state (Home Assistant)`."""
    rest, suffix = name, ""
    for prefix, area in _TITLE_AREAS:
        if name.startswith(prefix):
            rest, suffix = name[len(prefix):], area
            break
    words = [_TITLE_WORDS.get(w, w) for w in rest.split("_") if w]
    if words:
        # Solo la primera letra: así una sigla de la tabla (`HACS`) no cambia.
        words[0] = words[0][:1].upper() + words[0][1:]
    return " ".join(words) + suffix


def _starts_with(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name.startswith(p) for p in prefixes)


def classify(name: str) -> ToolAnnotations:
    """Devuelve las anotaciones que corresponden a una tool por su nombre."""
    read_only = name not in _NOT_READ_ONLY_EXACT and (
        name in _READ_ONLY_EXACT or _starts_with(name, _READ_ONLY_PREFIXES)
    )
    destructive = (
        not read_only
        and (name in _DESTRUCTIVE_EXACT or _starts_with(name, _DESTRUCTIVE_PREFIXES))
    )
    if name in _NON_IDEMPOTENT_EXACT:
        idempotent = False
    elif read_only or _starts_with(name, _IDEMPOTENT_OVERRIDE_PREFIXES):
        idempotent = True
    else:
        idempotent = not _starts_with(name, _NON_IDEMPOTENT_PREFIXES)

    return ToolAnnotations(
        title=title_for(name),
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=name in _OPEN_WORLD,
    )


def apply_tool_annotations(mcp: Any) -> dict[str, int]:
    """Aplica las anotaciones a todas las tools ya registradas en `mcp`.

    Se llama al final de `register_all_tools`. Devuelve un recuento por
    categoría, útil para el log de arranque y para los tests.
    """
    try:
        tools = mcp._tool_manager._tools  # noqa: SLF001
    except AttributeError:
        # Esto depende de un detalle interno del SDK. Si un día lo renombran,
        # NINGUNA tool queda anotada y el cliente pierde la única señal que
        # tiene para distinguir lo que solo lee de lo que borra o reinicia.
        # Las protecciones de verdad —tokens de confirmación, denylist— viven
        # en el servidor y siguen en pie, así que no se aborta el arranque;
        # pero tiene que verse, y por eso es un error y no un debug.
        logger.error(
            "tool_annotations_unavailable",
            reason="tool_manager_registry_missing",
            mcp_type=type(mcp).__name__,
            impact="ninguna tool lleva readOnlyHint/destructiveHint",
        )
        return {"annotated": 0, "read_only": 0, "destructive": 0}

    if not tools:
        logger.warning(
            "tool_annotations_no_tools",
            reason="empty_tool_registry",
            mcp_type=type(mcp).__name__,
        )

    stats = {"annotated": 0, "read_only": 0, "destructive": 0}
    for name, tool in tools.items():
        ann = classify(name)
        tool.annotations = ann
        # El mismo valor en la tool y en sus anotaciones: la spec da
        # precedencia a `annotations.title`, pero hay clientes que solo leen
        # el `title` de la tool.
        tool.title = ann.title
        stats["annotated"] += 1
        if ann.read_only_hint:
            stats["read_only"] += 1
        if ann.destructive_hint:
            stats["destructive"] += 1
    return stats
