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
expone más de doscientas tools sobre una casa entera, así que esa distinción importa.

Se aplican de forma centralizada tras registrar las tools (ver
`apply_tool_annotations`) en vez de repetir `annotations=...` en cada
decorador: una sola tabla, revisable de un vistazo y verificada por tests.

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
    # Genéricas de lectura (spec 011): solo ejecutan entradas `read` de la
    # tabla, y un test de la tabla impide que una `read` escriba o salga a
    # internet. Por nombre exacto: ningún prefijo las cubre.
    "ha_read_ws_command",
    "sv_read_api",
    # Spec 029 (CAP-049): `recorder/validate_statistics` solo calcula los
    # problemas y los devuelve; no corrige nada ni crea avisos en Repairs (eso
    # es `recorder/update_statistics_issues`, de la 020). Por nombre exacto:
    # ningún prefijo de lectura la cubre, y `ha_validate_` no debe pasar a
    # serlo (una futura `validate` podría escribir).
    "ha_validate_statistics",
    # Diagnóstico de Core (spec 012): validan y evalúan con los validadores de
    # HA y no guardan nada. Su nombre no tiene prefijo de lectura.
    "ha_validate_config",
    "ha_test_condition",
    # Blueprints (spec 017): HA sustituye las entradas y devuelve la
    # configuración resultante sin guardar nada (`saved: false`).
    "ha_preview_blueprint_substitution",
    # Targets (spec 017, tramo C): `extract_from_target` y `explain_target`
    # solo calculan qué abarca un target. Su nombre no tiene prefijo de
    # lectura; las `ha_list_*_for_target` y `ha_list_device_*` ya lo tienen.
    "ha_resolve_target",
    "ha_explain_target",
    # Espera de trigger (spec 017, tramo D): solo escucha. Es verdad porque
    # solo admite triggers de una lista cerrada de los que se sabe que solo
    # escuchan (research R-8); `webhook`, `conversation` o el `turn_on` de
    # una tele, que hacen algo más mientras existen, se rechazan.
    "ha_wait_for_trigger",
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
    # Excepción: `ha_reload_counters` ya no pide ni emite token desde la 033
    # (Core no tiene `counter.reload`; responde `not_supported`), pero sigue
    # aquí a propósito: FR-004 deja sus anotaciones sin cambios hasta que se
    # retire en la 1.3.0.
    "ha_run_script",              # ejecuta lo que el script contenga
    "ha_trigger_automation",      # dispara sus acciones, sean cuales sean
    "ha_reload_automations",      # materializa lo que haya en el YAML
    "ha_reload_counters",         # sin token desde la 033; ver arriba
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
    # Genéricas de escritura (spec 011): ejecutan cualquier entrada `confirm`
    # de la tabla (borrar, reiniciar, reconfigurar…), así que se asume lo
    # peor. Siempre piden confirmation_token.
    "ha_call_ws_command",
    "sv_call_api",
    # Diagnóstico de Core (spec 012): piden token y ocultan rastro. Bajar un
    # nivel de log o vaciar el log del sistema esconde lo que pasó; es la
    # misma razón por la que `logger.set_level` y `system_log.clear` están en
    # la denylist de `ha_call_service` («Ofuscación de rastros»).
    "ha_set_log_level",
    "ha_clear_system_log",
    # Y descartar una notificación persistente borra un aviso de HA que no se
    # recupera (`persistent_notification.dismiss` también está en la denylist).
    "ha_dismiss_persistent_notification",
    # Spec 033 (FR-006): `scene.create` reemplaza en silencio una escena
    # temporal con el mismo id; la tool lo pide confirmar con token. Antes se
    # anunciaba no destructiva (`----`, por el prefijo `ha_create_`) y su
    # descripción decía que una colisión daba error, que no es lo que hace HA.
    "ha_create_scene_from_current",
    # Spec 016: puede pedir token. Desactivar el sondeo recarga la integración
    # y deja sus entidades sin actualizar; desactivar las entidades nuevas hace
    # que lo que se añada entre deshabilitado. Invariante «pide token ⇔
    # destructiva». Idempotente: repetirla deja la entrada igual.
    "ha_update_config_entry",
    # Spec 016, tramo B (decisión del supervisor): cada paso pide token,
    # porque cualquier envío puede terminar el reconfigure, cambiar
    # credenciales o datos de conexión y recargar la integración.
    "ha_continue_reconfigure_flow",
    # Spec 016, tramo C: cada envío de un paso pide token, porque puede
    # aplicar el arreglo de una integración, con efectos propios de cada una,
    # y HA no dice antes qué paso es el último.
    "ha_continue_repair_fix",
    # Spec 016, tramo C (decisión del supervisor): la tool de la 1.1.2 pide
    # token en cada paso de un flujo `reauth`, que cambia las credenciales de
    # una entrada. Invariante «pide token ⇔ destructiva»: su hint cambia a
    # propósito (ver `_HINTS_CAMBIADOS_A_PROPOSITO` en
    # tests/test_tools_registration.py). Sigue idempotente, como en la 1.1.2.
    "ha_continue_config_entry_flow",
    # Montajes del Supervisor (spec 019). Piden token y su nombre no lo
    # delata: crear uno de backup puede pasar a ser el destino de TODOS los
    # backups (también los safety backups); editar desmonta y puede quitar
    # las credenciales; el montaje por defecto decide a dónde van los backups.
    # `sv_delete_mount` ya lo cubre el prefijo `sv_delete_`.
    "sv_create_mount",
    "sv_update_mount",
    "sv_set_default_backup_mount",
    # Spec 015: actualizar Core lo para y lo arranca en otra versión; si la
    # nueva no arranca, el Supervisor intenta volver atrás. Pide token y su
    # nombre no lo delata.
    "sv_update_core",
    # Spec 015, tramo 2: actualizar el OS reescribe la ranura de arranque
    # inactiva y se aplica al reiniciar el host; actualizar el Supervisor lo
    # reinicia. Las dos piden token.
    "sv_update_os", "sv_update_supervisor",
    # Tramo 3: instalar una entidad `update` cambia el firmware de un
    # dispositivo o la versión de una integración, sin vuelta atrás desde
    # Hermes. Pide token y su nombre no lo delata.
    "ha_install_update",
    # Spec 030: piden token. Añadir un repositorio mete código de terceros
    # sin revisar en la tienda (cadena de suministro); quitarlo deja sus apps
    # sin poder instalarse. Ninguna lo delata con el prefijo.
    "sv_add_store_repository",
    "sv_remove_store_repository",
    # Spec 030, tramo 2: reconstruir borra el contenedor y la imagen de la
    # app; si la construcción falla, la app queda sin poder arrancar.
    "sv_rebuild_addon",
    # Blueprints (spec 017): guardar crea o sobrescribe un fichero de
    # /config/blueprints y, al sobrescribir, HA recarga las automatizaciones
    # o scripts que lo usan; pide token (invariante «pide token ⇔
    # destructiva»). `ha_delete_blueprint` ya lo es por el prefijo
    # `ha_delete_`: borra un fichero que solo vuelve con un backup.
    "ha_save_blueprint",
    # Importar (spec 017, tramo B) guarda lo descargado igual que
    # `ha_save_blueprint`, y con `allow_override` sobrescribe y recarga.
    "ha_import_blueprint",
    # Spec 020 (CAP-050): reescriben el histórico de estadísticas y solo un
    # backup lo deshace (borrar filas o metadatos, convertir todos los
    # valores, cambiar la unidad guardada). Ningún prefijo las clasifica:
    # `ha_clear_`, `ha_change_` y `ha_update_` no son destructivos por nombre.
    "ha_clear_statistics",
    "ha_change_statistics_unit",
    "ha_update_statistics_metadata",
    # Spec 020, tramo 2: sumar a la suma de todas las filas desde una hora y
    # sobrescribir filas importando. Tampoco `ha_adjust_` ni `ha_import_`
    # son prefijos destructivos.
    "ha_adjust_statistics_sum",
    "ha_import_statistics",
    # Spec 020, tramo 3 (CAP-054): cada lista que recibe reemplaza ENTERA la
    # de HA, así que quita las fuentes o dispositivos que no se reenvían.
    # `ha_update_` no es prefijo destructivo. Repetirla con las mismas listas
    # deja el mismo estado (idempotente).
    "ha_update_energy_prefs",
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
    # Genéricas de escritura (spec 011): algunas entradas `confirm` salen a
    # internet (actualizar un plugin, calendarios remotos).
    "ha_call_ws_command",
    "sv_call_api",
    # Y la de lectura de Core: `media_source/browse_media` y `search_media`
    # consultan APIs externas cuando la fuente es remota (radio_browser,
    # google_photos, immich…). Una tool no puede decir que no sale a internet
    # si algún comando suyo lo hace (principio V; T047). `sv_read_api` no:
    # ninguna ruta `read` del Supervisor sale. tests/test_command_table.py
    # ata esta lista a las marcas `open_world` de la tabla.
    "ha_read_ws_command",
    # Spec 029 (T037): pedir `system_health/info` hace que HA ejecute los
    # callbacks de salud, y varios llaman a `async_check_can_reach_url`, que
    # hace un GET a internet (nube, Marketplace en GitHub, Spotify, NextDNS…).
    # Es de solo lectura, pero no puede decir que no sale.
    "ha_get_system_health",
    # Spec 015 (contracts/tools.md): actualizar Core descarga la imagen nueva,
    # y buscar actualizaciones descarga el registro de versiones y refresca los
    # repositorios de la tienda. Quien sale es el Supervisor, pero lo provoca
    # la tool (mismo criterio que sv_install_addon). `sv_check_for_updates` no
    # es de solo lectura (su prefijo no lo es) ni destructiva: no pide token.
    "sv_update_core", "sv_check_for_updates",
    # Tramo 2: descargan el bundle del OS o la imagen del Supervisor.
    "sv_update_os", "sv_update_supervisor",
    # Tramo 3: la integración descarga el firmware o la versión nueva; y
    # algunas piden las notas de versión a internet al leerlas.
    "ha_install_update", "ha_get_update_release_notes",
    # Spec 030: provocan descargas en el Supervisor. Añadir y reparar clonan
    # el repositorio; recargar hace `git pull` de todos. Quitar y listar no
    # salen (listar lee lo que el Supervisor ya tiene).
    "sv_add_store_repository",
    "sv_repair_store_repository",
    "sv_reload_store",
    # Reconstruir descarga la imagen base (al construir) o la imagen de la
    # app (con `force`). Leer el changelog, la documentación o la
    # disponibilidad no sale: el Supervisor lee su clon local.
    "sv_rebuild_addon",
    # Spec 017, tramo B: HA descarga el blueprint de la URL que da el agente
    # (foro, GitHub, gist o cualquier web). No abre el socket Hermes, pero la
    # descarga la provoca esta tool (mismo criterio que sv_install_addon).
    "ha_import_blueprint",
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
_NON_IDEMPOTENT_EXACT: frozenset[str] = frozenset({
    "ha_change_timer",
    # Genéricas de escritura (spec 011): entre lo que la tabla permite hay
    # creaciones y acciones que se acumulan; repetir no deja el mismo estado.
    "ha_call_ws_command",
    "sv_call_api",
    # Spec 016: cada llamada abre un flujo nuevo o avanza el flujo un paso;
    # repetirla no deja el mismo estado. Las de la 1.1.2
    # (`ha_start_config_entry_flow`, `ha_continue_*_flow`) no se tocan (D-4).
    "ha_start_subentry_flow",
    "ha_continue_subentry_flow",
    "ha_start_reconfigure_flow",
    "ha_continue_reconfigure_flow",
    # Tramo C: abrir un flujo de reparación (algunos terminan al abrirse) y
    # avanzarlo un paso.
    "ha_start_repair_fix",
    "ha_continue_repair_fix",
    # Spec 020: `adjustment` es un DELTA, como el de `ha_change_timer`.
    # Confirmar dos ajustes iguales suma dos veces; el token de un solo uso
    # evita el reintento con el mismo token, pero no una segunda vista previa.
    "ha_adjust_statistics_sum",
})

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
    # Spec 011: `sv_read_api` → «Read API (Supervisor)». Ninguna tool de la
    # 1.1.2 tiene `api` como palabra, así que no cambia ningún título.
    "api": "API",
    # Spec 013: `sv_get_os_info` → «Get OS info (Supervisor)». Ninguna tool
    # de la 1.1.2 tiene `os` como palabra (lo comprueba un test).
    "os": "OS",
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
