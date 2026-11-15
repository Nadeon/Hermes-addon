"""Inventario de argumentos atados al `confirmation_token` (spec 033, FR-003).

El token de una tool en dos pasos solo protege lo que ata: un argumento que
cambia el efecto y queda fuera del hash permite previsualizar una cosa y
confirmar otra (principio IV). Así pasó con `variables` en `ha_run_script` y
`ha_trigger_automation` hasta la 033.

Aquí cada argumento de cada tool con `confirmation_token` está clasificado:

- `"atado"`: entra en el dict que se pasa a `create_confirmation_token` y a
  `validate_confirmation_token` / `resolve_confirmation_token` (normalizado
  si la tool lo normaliza antes de enviarlo, u omitible en la confirmación si
  la tool lo resuelve desde lo guardado; en los dos casos el hash lo cubre);
- `"exento: <motivo>"`: no entra en el hash, con el motivo escrito.

El test comprueba por AST, sin importar nada, que el inventario cubre
EXACTAMENTE las funciones decoradas con `mcp.tool()` de
`hermes/src/hermes/tools/*.py` que tienen `confirmation_token`, y en cada una
EXACTAMENTE los argumentos de su firma. Es documental: no prueba el hash por
sí solo (eso lo hacen los tests de comportamiento de cada tool), pero obliga a
quien añade una tool con token, o un argumento a una que ya lo tiene, a decidir
y escribir si queda atado.

Regla para las sub-features siguientes: una tool nueva con
`confirmation_token` añade aquí su entrada, con todos sus argumentos, en el
mismo cambio. Si no lo hace, este test cae en su rama nombrando la tool o el
argumento.

Control negativo (T007), permanente en `TestControlNegativo`: sobre una copia
temporal de `tools/`, una tool nueva con token sin entrada y un argumento
nuevo en `ha_run_script` hacen que la comprobación falle nombrando los dos.

Contraste con el registro real (T037): el descubrimiento por AST se compara
además con las tools que publican `confirmation_token` en un `MCPServer` real
(`_real_registry()`), así que una tool con token registrada de otra forma
(`mcp.add_tool`, un subpaquete) tampoco se escapa.

Recuento: 95 tools (86 hasta la 021). La auditoría de la spec (research R-1) contaba 79 sobre
la punta de entonces; la 011 integró después `ha_call_ws_command` y
`sv_call_api`, que atan todo lo que envían, y el tramo 2 de la 033 dio token
a `ha_create_scene_from_current` (FR-006). Al integrar la 033 en la rama del
programa entraron las que llegaron después de su base, comprobadas en el
código: `ha_call_service_response` con token (018), `view_index` y `view` de
`ha_save_lovelace_dashboard` (guardado por vista, 018) y las tres de la 012
que confirman (`ha_set_log_level`, `ha_clear_system_log` y
`ha_dismiss_persistent_notification`). Todas atan todo lo que cambia la
acción; ningún hallazgo.

Spec 031, tramo 1: 87. Suma `ha_update_backup_config`, que ata todos sus
argumentos (además del estado leído en la vista previa, que va aparte con
`estado=`). `ha_set_update_backup_settings` entró y salió en el mismo tramo
(el proxy del Supervisor rechaza `hassio/*` a las apps).

Spec 031, tramo 2: 90. Suma `ha_create_backup`, `ha_create_automatic_backup`
y `ha_delete_backup`, que atan todos sus argumentos; además, el estado de la
vista previa (agentes y cifrado; configuración y retención; el backup y todas
sus ubicaciones) va aparte con `estado=`. La clave de cifrado de HA que manda
`ha_create_backup` no es un argumento: se lee en la confirmación y no entra
en el hash ni en el estado (que lleva solo `key_set`).

Recuento: 91 desde la integración de la 016, que trae cinco tools con token,
comprobadas en el código: `ha_update_config_entry` (ata los cuatro
argumentos tal como llegan), `ha_delete_subentry`,
`ha_continue_reconfigure_flow` y `ha_continue_repair_fix` (atan el flujo, el
paso actual que leen de HA al previsualizar y al confirmar, y el `user_input`
entero; la de Repairs, también el aviso), y `ha_continue_config_entry_flow`,
de la 1.1.2, que gana `confirmation_token` solo para los flujos `reauth`
(mismo esquema de atado que el reconfigure). Ningún hallazgo.

Recuento: 95 desde la integración de la 019 (T033), que trae cuatro tools
con token, comprobadas en el código: `sv_create_mount` y `sv_update_mount`
atan sus 13 argumentos tal como llegan (credenciales incluidas; desde la
019 el `action_hash` es un HMAC-SHA256 con una clave del proceso), y
`sv_delete_mount` y `sv_set_default_backup_mount`, `name`. El estado que
cambia la acción (el montaje actual, el por defecto y los backups
afectados) va además en el `estado` del token. Las otras cinco de la 019
no piden token. Ningún hallazgo.

Recuento: 99 desde la integración de la 015, que trae cuatro tools con
token, comprobadas en el código (`_args_atados` en `tools/system_updates.py`):
`sv_update_core` ata `version` y `backup`; `sv_update_os`, `version`;
`sv_update_supervisor` no tiene argumentos; y `ha_install_update` ata
`entity_id`, `version` y `backup`. Las cuatro atan además la versión de
origen y la de destino que resuelven al previsualizar (`_from_version` y
`_to_version`), releídas antes de validar al confirmar: si cambiaron, el
token no coincide y no se envía nada. Lo que se envía al confirmar sale de
lo atado (la versión de destino explícita, salvo en el Supervisor, que va
sin cuerpo por diseño de la 015, y en una entidad sin `specific_version`).
`sv_check_for_updates` no pide token. `ha_call_service` con `update.install`
sigue atando `domain`, `service` y `service_data` como en la 1.1.2. Ningún
hallazgo.

Recuento: 102 desde la integración de la 030, que trae tres tools con
token, comprobadas en el código: `sv_add_store_repository` ata
`repository`, la URL completa ya validada (credenciales y `#rama`
incluidas, aunque la vista previa las tape); `sv_remove_store_repository`,
`repository`, y además el repositorio y sus apps instaladas en el `estado`;
y `sv_rebuild_addon`, `slug` y `force`. La 030 cambia también tres de la
1.1.2 sin cambiar sus argumentos: `sv_install_addon` y `sv_update_addon`
siguen atando `slug` y ahora también la `version_latest` de la vista previa
en el `estado` (si la tienda ofrece otra al confirmar, `preview_outdated`);
`sv_set_addon_options` sigue atando `slug` y `options`.
`sv_repair_store_repository` y `sv_reload_store` no piden token. Ningún
hallazgo.

Recuento: 105 desde la integración de la 017, que trae tres tools con
token, comprobadas en el código (`tools/blueprints.py`):
`ha_save_blueprint` ata `domain`, `path` (normalizada, con `.yaml`),
`yaml` (omitible al confirmar: se resuelve desde lo guardado en la vista
previa y el hash lo cubre) y `allow_override`; `ha_delete_blueprint`,
`domain` y `path`; y `ha_import_blueprint`, `url`, `path` (la pedida) y
`allow_override`, más, en el `estado` del token, lo que HA descargó: el
dominio, la ruta final y la huella `content_sha256` (si cambia al volver a
descargar al confirmar, `content_changed` y no se guarda). Las otras once
de la 017 son de solo lectura y no piden token. La 017 cambia también dos
de la 1.1.2 sin cambiar sus argumentos: `ha_create_or_update_automation` y
`ha_create_or_update_script` validan con HA en la vista previa (sin token si
la configuración es inválida) y siguen atando su id y `config`. Ningún
hallazgo.

Recuento: 111 desde la integración de la 020, que trae seis tools con
token, comprobadas en el código (`tools/statistics_maintenance.py` y
`tools/energy.py`): `ha_clear_statistics` ata `statistic_ids` (ordenados y
sin repetir), `start_time` y `end_time` (en UTC, `None` si no llegan);
`ha_change_statistics_unit`, `statistic_id`, `old_unit` y `new_unit`;
`ha_update_statistics_metadata`, `statistic_id`, `unit_of_measurement` y
`unit_class`; `ha_adjust_statistics_sum`, la estadística, el instante en
UTC, la cantidad y la unidad; e `ha_import_statistics`, `metadata`
(normalizado) y `stats` (omitible al confirmar: se resuelve desde lo
guardado en la vista previa, normalizado y el hash cubre el documento
entero). Las cinco atan además los metadatos leídos en el `estado`.
`ha_update_energy_prefs` ata las tres listas (`None` las que no llegan: el
documento que se enviará entero) y, en el `estado`, las preferencias
leídas. `ha_get_energy_prefs` es de solo lectura. Ningún hallazgo.

Recuento: 118 desde la integración de la 022, que trae siete tools con
token, comprobadas en el código (`tools/system_control.py` y
`tools/resolution_fixes.py`): `sv_rebuild_core` ata `safe_mode`;
`sv_set_core_options` y `sv_set_supervisor_options`, `options` normalizado
(y, en el `estado`, los valores actuales de esas claves: si cambian antes de
confirmar, el token no coincide); `sv_start_core`, `sv_restart_supervisor` y
`sv_repair_supervisor` no tienen argumentos (su `estado` es el de Core o la
lista vacía de jobs en curso). `sv_apply_resolution_suggestion` ata
`suggestion_uuid` (normalizado, sin guiones) y, en el `estado`, el tipo, el
contexto y la referencia de la sugerencia, los backups a borrar con sus
ubicaciones, los contenedores a reconstruir y los arreglos automáticos que el
Supervisor aplicaría de paso (`also_auto_applied`). `sv_reload_supervisor`
no pide token (FR-076 de la 008). Ningún hallazgo.

Recuento: 127 desde la integración de la 021, que trae nueve tools con
token, comprobadas en el código. `ha_update_core_config` ata sus doce campos
(también los `None`: otra combinación es otra acción) y `update_units`, y en
el `estado` los campos editables y la fuente leídos de HA.
`ha_set_entity_exposure` ata `entity_ids` y `assistants` sin repetidos y
ordenados, y `expose`, y en el `estado` la exposición actual de esas
entidades en esos asistentes; `ha_set_expose_new_entities` ata `assistant`
y `expose_new`, y en el `estado` el valor leído. Las dos solo piden token al
exponer (`expose=true`, `expose_new=true`): ocultar se aplica a la primera,
sin token (excepción `TOKEN_SOLO_AL_AMPLIAR` de
tests/test_tools_registration.py). `ha_create_user` ata `name`, `group` y
`local_only` (ninguna toma credenciales) y, en el `estado`, los usuarios con
el mismo nombre; `ha_update_user` ata `user_id` y los cuatro campos (`None`
los que no llegan) y `ha_delete_user`, `user_id`; las dos, en el `estado`,
el usuario leído, quién es Hermes y el número de administradores activos,
releídos al confirmar. `ha_update_network_config` ata `configured_adapters`
y, en el `estado`, los adaptadores configurados, los habilitados y los
disponibles; `ha_update_http_config`, `changes` entero y `discard_pending`;
y `ha_promote_http_config` no tiene más argumento que el token. Las dos de
HTTP atan en el `estado` las dos ranuras (estable y pendiente) y con cuál
funciona HA. Ningún hallazgo.

Recuento: 133 desde la integración de la 032, que trae seis tools con
token, comprobadas en el código (`tools/host_control.py` y
`tools/host_network.py`). Tramo 1, cuatro:
`sv_shutdown_host` (solo `confirmation_token`, exento, como
`sv_reboot_host`: no tiene argumentos ni estado que describir),
`sv_set_hostname` (`hostname`), `sv_set_swap` (`swap_size` y `swappiness`,
los dos aunque no se pasen) y `sv_set_boot_slot` (`boot_slot`, normalizado
a mayúsculas antes del hash). Las tres últimas atan además la huella del
estado que describe la vista previa (hostname actual, swap actual, ranuras),
no el disco libre, que cambia solo.

Tramo 2, dos más:
`sv_update_network_interface` (`interface` y los seis bloques, la PSK
dentro de `wifi`) y `sv_create_vlan` (`interface`, `vlan_id` y los cuatro
bloques). Atan todo lo que envían, ya normalizado, y la huella de la
interfaz y su papel (sin la señal Wi-Fi ni `ready`). La PSK entra en el
hash y nunca en el fichero del token: no hay `omitibles` y el hash es el
HMAC de la 019. `sv_reload_network` no tiene token (D-032-1). Ningún
hallazgo.

Recuento: 134 desde la integración de la 023, que trae una tool con token,
comprobada en el código (`tools/conversation.py`): `ha_process_conversation`
ata los cinco argumentos que cambian el efecto (`text`, `agent_id`,
`language`, `conversation_id` y `device_id`) tal como llegan, `None`
incluido, que son justo los que manda a `conversation/process`; sin
omitibles ni `estado` (la vista previa no promete conservar nada). Si la
frase no llegó a salir (`sent is False`), el token se devuelve con
`release_confirmation_token` en vez de gastarse. Ningún hallazgo.

Recuento: 139 desde la integración de la 031, que trae cinco tools con
token, comprobadas en el código (`tools/ha_backup_settings.py`,
`tools/ha_backup_actions.py` y `tools/ha_backup_restore.py`):
`ha_update_backup_config` ata sus cinco argumentos tal como llegan y, en el
`estado`, la configuración leída (con `password_set`, nunca la clave) y los
backups que la retención estimó borrar; `ha_create_backup` ata sus ocho
argumentos y, en el `estado`, los agentes disponibles, si se cifra cada
destino y `key_set` (la clave de HA no es un argumento: se lee al confirmar y
no entra ni en el hash ni en el estado); `ha_create_automatic_backup` no
tiene argumentos y ata en el `estado` la configuración, lo que se estimó
borrar y los agentes disponibles de los destinos, leídos en los dos pasos
(T065); `ha_delete_backup` ata `backup_id` y, en el `estado`, el backup, su
contenido y TODAS sus ubicaciones con su tamaño y su cifrado; y
`ha_restore_backup` ata sus siete argumentos, `password` incluido (el
`action_hash` es el HMAC-SHA256 de la 019, así que el fichero del token no
permite atacarla sin conexión), y en el `estado` la huella del backup en esa
ubicación, su contenido y `password_source`. La 031 cambia también
`sv_restore_backup_full` y `sv_restore_backup_partial` sin cambiar sus
argumentos: siguen atando lo mismo y ganan el `estado` `password_source` (de
dónde sale la contraseña, nunca su valor). Ningún hallazgo.

Recuento: 140 desde la integración de la 024 (tramo 2), que trae una
tool con token, comprobada en el código (`tools/lovelace_reset.py`):
`ha_reset_lovelace_dashboard_config` ata `url_path` y, en el `estado` del
token, la configuración del dashboard leída en la vista previa (si cambia
antes de confirmar, `dashboard_changed` y no se borra nada). Las dos de
`cameras` (tramo 1) son de solo lectura y no piden token. Ningún hallazgo.

Recuento: 145 desde la integración de la 026, que trae cinco tools con
token, comprobadas en el código (`tools/marketplace_manage.py`). Tramo 1,
cuatro: `ha_marketplace_acknowledge_critical` ata `repository` (el
`owner/repo` tal como llega) y, en el `estado`, la entrada crítica leída
(`repository`, `reason`, `link`, `acknowledged`);
`ha_marketplace_ignore_repository`, `ha_marketplace_remove_repository` y
`ha_marketplace_refresh_repository` atan `repository_id` (normalizado a
texto) y, en el `estado`, el `full_name` y la categoría leídos (ignorar,
además, la entrada de retirados; quitar, además, `custom` e `installed`).
Tramo 2 (misma familia, decisión D-2): `ha_marketplace_uninstall` ata
`repository_id` (normalizado a texto) y `backup` (bool estricto: quien
previsualizó sin backup no confirma con él) y, en el `estado`, el
`full_name`, la categoría, la versión instalada, el `domain` y el
`local_path` leídos (si la carpeta o el dominio cambian antes de confirmar,
lo que la vista previa dice que se borra ya no es cierto y el token no
vale). Las que exigen el
aviso de riesgos (añadir, detectar, instalar, fijar versión, betas) no
existen (DESVIACIÓN DV-1 de la 026). Ninguna usa `allow_dangerous`. Ningún
hallazgo.

Recuento: 149 desde el tramo 2 de la 034 (1.2.1, `tools/folders_write.py`),
que trae las cuatro tools que modifican /addons y /share, comprobadas en el
código: `fs_write_file_in_folder` ata `folder`, `path` (normalizada y
relativa a la carpeta) y `content` (omitible al confirmar: se resuelve desde
lo guardado en la vista previa y el hash lo cubre);
`fs_create_dir_in_folder`, `folder` y `path`; `fs_move_in_folder`,
`folder`, `src` y `dst` (normalizadas sin seguir el último symlink); y
`fs_delete_in_folder`, `folder`, `path` y `recursive` (bool estricto). Las
cuatro atan además, en el `estado`, la huella de lo que la vista previa vio
(contenido de un fichero, destino de un symlink o el árbol entero de una
carpeta; en mover, la del origen y la del destino). Ningún hallazgo.

El tramo 3 de la 034 (privilegios, FR-023) no cambia ningún argumento ni el
recuento: `sv_install_addon` sigue atando `slug` y `sv_rebuild_addon`,
`slug` y `force`. Crece su `estado`: el de instalar pasa a ser
`{"version_latest", "privileges"}` y el de reconstruir, que no tenía,
`privileges` (el bloque de la vista previa sin notas ni motivos; al
confirmar se vuelve a leer con las mismas rutas GET y, si cambió,
`preview_outdated` sin enviar nada). Ningún hallazgo.

La convergencia 2 de la 034 (T053) tampoco cambia argumentos ni recuento:
`sv_update_addon` sigue atando `slug`, y su `estado` pasa de
`{"version_latest"}` a `{"version_latest", "privileges"}` (el mismo bloque
que reconstruir, con la ficha de la tienda, la app instalada y, para
`local_*`, su `config.*`; al confirmar se vuelve a leer con las mismas rutas
GET y, si cambió, `preview_outdated` sin enviar nada). Ningún hallazgo.
"""

from __future__ import annotations

import ast
import shutil
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
TOOLS = RAIZ / "hermes" / "src" / "hermes" / "tools"

A = "atado"
TOKEN = "exento: es el propio token; no puede formar parte de su hash"

# Grupos para no repetir; el dict final se arma abajo.
# Los 13 argumentos de `sv_create_mount` y `sv_update_mount` (spec 019).
_CAMPOS_MONTAJE = (
    "name", "type", "usage", "server", "share", "path", "port", "version",
    "read_only", "username", "password", "device", "uuid",
)
_RECARGAS = (
    "ha_reload_automations",
    "ha_reload_counters",
    "ha_reload_scenes",
    "ha_reload_schedules",
    "ha_reload_scripts",
    "ha_reload_timers",
    "ha_reload_zones",
    "sv_reboot_host",
    "sv_restart_core",
)
_HELPERS = (
    "counter",
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "schedule",
    "timer",
    "zone",
)
_ADDONS = (
    "sv_install_addon",
    "sv_restart_addon",
    "sv_start_addon",
    "sv_stop_addon",
    "sv_uninstall_addon",
    "sv_update_addon",
)

INVENTARIO: dict[str, dict[str, str]] = {
    # ── servicios, comandos genéricos, scripts y automatizaciones ───────
    "ha_call_service": {"domain": A, "service": A, "service_data": A},
    # Spec 018: mismo hash que `ha_call_service` (normalizado en minúsculas),
    # pero atado a ESTA tool.
    "ha_call_service_response": {"domain": A, "service": A, "service_data": A},
    "ha_call_ws_command": {"type": A, "payload": A},
    "sv_call_api": {"method": A, "path": A, "body": A},
    # `variables` atadas desde la 033 (`guarded_entity_invoke`).
    "ha_run_script": {"script_id": A, "variables": A},
    "ha_trigger_automation": {"automation_id": A, "variables": A},
    "ha_create_or_update_automation": {"automation_id": A, "config": A},
    "ha_create_or_update_script": {"script_id": A, "config": A},
    "ha_create_or_update_scene": {"scene_id": A, "config": A},
    "ha_delete_automation": {"automation_id": A},
    "ha_delete_script": {"script_id": A},
    "ha_delete_scene": {"scene_id": A},
    # Spec 033 (FR-006): el token solo hace falta para reemplazar una escena
    # temporal. `scene_id` va normalizado (sin `scene.`), como se envía.
    "ha_create_scene_from_current": {
        "scene_id": A,
        "entity_ids": A,
        "name": "exento: con valor se rechaza (name_not_supported) antes de emitir o validar el token",
    },
    # ── helpers y personas (colecciones) ────────────────────────────────
    **{f"ha_create_or_update_{h}": {"entity_id": A, "config": A} for h in _HELPERS},
    **{f"ha_delete_{h}": {"entity_id": A} for h in _HELPERS},
    "ha_update_person": {"entity_id": A, "config": A},
    "ha_delete_person": {"entity_id": A},
    # ── recargas y reinicios: no tienen más argumento que el token ──────
    **{t: {} for t in _RECARGAS},
    # ── Lovelace ─────────────────────────────────────────────────────────
    # Spec 018: en el guardado por vista atan `url_path`, `view_index` y
    # `view` (omitible al confirmar), y además el documento leído (`estado`).
    # `config` y `remove_top_level_keys` no se pueden mezclar con la vista
    # (`invalid_argument` antes de tocar el token).
    "ha_save_lovelace_dashboard": {
        "url_path": A,
        "config": A,
        "remove_top_level_keys": A,
        "view_index": A,
        "view": A,
    },
    "ha_update_lovelace_dashboard_metadata": {"url_path": A, "updates": A},
    "ha_delete_lovelace_dashboard": {"url_path": A},
    "ha_create_lovelace_resource": {"url": A, "res_type": A},
    "ha_update_lovelace_resource": {"resource_id": A, "updates": A},
    "ha_delete_lovelace_resource": {"resource_id": A},
    # ── registros ───────────────────────────────────────────────────────
    "ha_update_area": {"area_id": A, "updates": A},
    "ha_delete_area": {"area_id": A},
    "ha_update_floor": {"floor_id": A, "updates": A},
    "ha_delete_floor": {"floor_id": A},
    "ha_update_label": {"label_id": A, "updates": A},
    "ha_delete_label": {"label_id": A},
    "ha_update_category": {"scope": A, "category_id": A, "updates": A},
    "ha_delete_category": {"scope": A, "category_id": A},
    "ha_update_device": {"device_id": A, "updates": A},
    "ha_remove_device": {"device_id": A},
    "ha_remove_device_from_config_entry": {"device_id": A, "config_entry_id": A},
    "ha_update_entity_registry": {"entity_id": A, "updates": A},
    "ha_remove_entity_registry": {"entity_id": A},
    # ── config entries y reparaciones ───────────────────────────────────
    "ha_disable_config_entry": {"entry_id": A},
    "ha_delete_config_entry": {"entry_id": A},
    "ha_ignore_repair": {"domain": A, "issue_id": A, "ignore": A},
    # ── integraciones: flujos y Repairs (spec 016) ──────────────────────
    # Los cuatro tal como llegan; el comando solo envía lo que cambia
    # respecto a la entrada, que se relee al confirmar.
    "ha_update_config_entry": {
        "entry_id": A,
        "title": A,
        "pref_disable_polling": A,
        "pref_disable_new_entities": A,
    },
    "ha_delete_subentry": {"entry_id": A, "subentry_id": A},
    # Atan además el `step_id` actual, que se lee de HA al previsualizar y
    # al confirmar: si el paso cambió, el token no vale y no se envía nada.
    "ha_continue_reconfigure_flow": {"flow_id": A, "user_input": A},
    # `user_input` ausente se normaliza a `{}` antes de atarlo.
    "ha_continue_repair_fix": {"domain": A, "issue_id": A, "flow_id": A, "user_input": A},
    # De la 1.1.2: el token solo se pide en los flujos `reauth` (los demás
    # se envían sin token, como antes) y ata el flujo, el paso y el
    # `user_input` entero, como el reconfigure.
    "ha_continue_config_entry_flow": {"flow_id": A, "user_input": A},
    # ── diagnóstico de Core (spec 012) ──────────────────────────────────
    # `level` va normalizado (en mayúsculas) antes de atarlo.
    "ha_set_log_level": {"level": A, "integration": A, "module": A, "persistence": A},
    "ha_clear_system_log": {},
    "ha_dismiss_persistent_notification": {"notification_id": A},
    # ── mantenimiento de estadísticas (spec 020) ────────────────────────
    # Atados normalizados como se envían: ids ordenados y sin repetir, fechas
    # en UTC. Además, el `estado` (metadatos leídos) ata el token.
    "ha_clear_statistics": {"statistic_ids": A, "start_time": A, "end_time": A},
    "ha_change_statistics_unit": {"statistic_id": A, "old_unit": A, "new_unit": A},
    "ha_update_statistics_metadata": {
        "statistic_id": A,
        "unit_of_measurement": A,
        "unit_class": A,
    },
    "ha_adjust_statistics_sum": {
        "statistic_id": A,
        "start_time": A,
        "adjustment": A,
        "adjustment_unit": A,
    },
    # `stats` omitible al confirmar (lo guarda el token) y normalizado:
    # `start` en UTC, filas ordenadas. El hash cubre el documento entero.
    "ha_import_statistics": {"metadata": A, "stats": A},
    # ── panel de energía (spec 020, tramo 3) ────────────────────────────
    # Las tres listas: la que no llega va como `None`, así que mandarla al
    # confirmar también cambia la acción. Además ata el `estado`.
    "ha_update_energy_prefs": {
        "energy_sources": A,
        "device_consumption": A,
        "device_consumption_water": A,
    },
    # ── configuración del sistema (spec 021, tramo a) ───────────────────
    # Todo atado; `entity_ids` y `assistants` van sin repetidos y ordenados
    # antes de atarlos. Ocultar (`expose=false`, `expose_new=false`) no pide
    # token (decisión D-4): no hay nada que atar en ese camino.
    "ha_update_core_config": {
        "location_name": A, "latitude": A, "longitude": A, "elevation": A,
        "radius": A, "unit_system": A, "time_zone": A, "currency": A,
        "country": A, "language": A, "internal_url": A, "external_url": A,
        "update_units": A,
    },
    "ha_set_entity_exposure": {"entity_ids": A, "assistants": A, "expose": A},
    "ha_set_expose_new_entities": {"assistant": A, "expose_new": A},
    # Usuarios (spec 021, tramo b): todo atado. Ninguna toma credenciales
    # (FR-012): no hay contraseña ni nombre de acceso que atar ni guardar.
    "ha_create_user": {"name": A, "group": A, "local_only": A},
    "ha_update_user": {"user_id": A, "name": A, "is_active": A, "group": A,
                       "local_only": A},
    "ha_delete_user": {"user_id": A},
    # Red y HTTP (spec 021, tramo c): todo atado. `changes` entero (el
    # documento que se manda sale de fundirlo) y `discard_pending`; promover
    # no tiene más argumento que el token.
    "ha_update_network_config": {"configured_adapters": A},
    "ha_update_http_config": {"changes": A, "discard_pending": A},
    "ha_promote_http_config": {},
    # ── backups de la integración `backup` (spec 031) ───────────────────
    # Se atan tal como llegan; lo que se manda a HA (completado con la
    # configuración actual) lo ata además el estado de la vista previa.
    "ha_update_backup_config": {
        "schedule": A,
        "retention": A,
        "agents": A,
        "create_backup": A,
        "automatic_backups_configured": A,
    },
    "ha_create_backup": {
        "agent_ids": A,
        "include_homeassistant": A,
        "include_database": A,
        "include_addons": A,
        "include_all_addons": A,
        "include_folders": A,
        "name": A,
        "encrypt": A,
    },
    "ha_create_automatic_backup": {},
    "ha_delete_backup": {"backup_id": A},
    # Spec 031, tramo 3: `password` también atado (HMAC de la 019); la clave
    # de HA no es un argumento y no entra.
    "ha_restore_backup": {
        "backup_id": A,
        "agent_id": A,
        "restore_homeassistant": A,
        "restore_database": A,
        "restore_addons": A,
        "restore_folders": A,
        "password": A,
    },
    # ── Supervisor ──────────────────────────────────────────────────────
    **{t: {"slug": A} for t in _ADDONS},
    # Spec 030: instalar y actualizar atan además la `version_latest` de la
    # vista previa en el `estado`.
    "sv_set_addon_options": {"slug": A, "options": A},
    "sv_delete_backup": {"slug": A},
    "sv_restore_backup_full": {"slug": A, "password": A},
    "sv_restore_backup_partial": {
        "slug": A,
        "addons": A,
        "folders": A,
        "password": A,
        "include_homeassistant": A,
    },
    "sv_dismiss_resolution_issue": {"issue_uuid": A},
    "sv_dismiss_resolution_suggestion": {"suggestion_uuid": A},
    # ── montajes del Supervisor (spec 019, T033) ────────────────────────
    # Crear y editar atan los 13 argumentos tal como llegan, credenciales
    # incluidas (el hash es HMAC con la clave del proceso, así que el
    # fichero del token no sirve para probar contraseñas). Editar fusiona
    # con el montaje actual, que va en el `estado` del token: si cambió
    # entre la vista previa y la confirmación, no se envía nada.
    **{t: {c: A for c in _CAMPOS_MONTAJE} for t in ("sv_create_mount", "sv_update_mount")},
    # El montaje y el por defecto (y en el borrado, los backups afectados)
    # van además en el `estado`.
    "sv_delete_mount": {"name": A},
    "sv_set_default_backup_mount": {"name": A},
    # ── actualizaciones del sistema (spec 015) ──────────────────────────
    # Las cuatro atan, además de sus argumentos, la versión de origen y la
    # de destino resueltas (`_args_atados`: `_from_version`, `_to_version`),
    # releídas antes de validar al confirmar.
    "sv_update_core": {"version": A, "backup": A},
    "sv_update_os": {"version": A},
    "sv_update_supervisor": {},
    "ha_install_update": {"entity_id": A, "version": A, "backup": A},
    # ── tienda de apps (spec 030) ───────────────────────────────────────
    # `repository` es la URL completa ya validada: el token se ata a ella
    # con sus credenciales, aunque la vista previa las tape. Quitar ata
    # además el repositorio y sus apps instaladas en el `estado`.
    "sv_add_store_repository": {"repository": A},
    "sv_remove_store_repository": {"repository": A},
    "sv_rebuild_addon": {"slug": A, "force": A},
    # ── blueprints (spec 017) ───────────────────────────────────────────
    # Guardar: `yaml` es omitible al confirmar (`resolve_confirmation_token`
    # con `omitibles`), pero el hash lo cubre. Importar ata además, en el
    # `estado`, el dominio, la ruta final y la huella de lo descargado.
    "ha_save_blueprint": {"domain": A, "path": A, "yaml": A, "allow_override": A},
    "ha_delete_blueprint": {"domain": A, "path": A},
    "ha_import_blueprint": {"url": A, "path": A, "allow_override": A},
    # ── control de Core y del Supervisor (spec 022, tramo 1) ────────────
    "sv_start_core": {},
    "sv_rebuild_core": {"safe_mode": A},
    "sv_set_core_options": {"options": A},
    "sv_restart_supervisor": {},
    "sv_repair_supervisor": {},
    "sv_set_supervisor_options": {"options": A},
    # ── aplicar sugerencias (spec 022, tramo 2) ─────────────────────────
    # El uuid normalizado; la sugerencia, los backups a borrar, los
    # contenedores y los arreglos automáticos van en el `estado`.
    "sv_apply_resolution_suggestion": {"suggestion_uuid": A},
    # ── host y OS (spec 032, tramo 1) ───────────────────────────────────
    # Apagar no tiene argumentos: solo el token, exento como en
    # `sv_reboot_host`. Las otras tres atan lo que envían (`boot_slot` ya en
    # mayúsculas) y, en el `estado` del token, la huella de lo que la vista
    # previa describe: el hostname, la swap o las ranuras actuales.
    "sv_shutdown_host": {},
    "sv_set_hostname": {"hostname": A},
    "sv_set_swap": {"swap_size": A, "swappiness": A},
    "sv_set_boot_slot": {"boot_slot": A},
    # ── red del host (spec 032, tramo 2) ────────────────────────────────
    # Todo atado tal como se envía (bloques normalizados). La PSK va dentro
    # de `wifi`: entra en el HMAC del token y no se guarda (sin omitibles).
    # El `estado` del token es la huella de la interfaz, la principal y las
    # conectadas.
    "sv_update_network_interface": {
        "interface": A, "ipv4": A, "ipv6": A, "wifi": A, "enabled": A,
        "mdns": A, "llmnr": A,
    },
    "sv_create_vlan": {
        "interface": A, "vlan_id": A, "ipv4": A, "ipv6": A, "mdns": A, "llmnr": A,
    },
    # Spec 023.
    "ha_process_conversation": {"text": A, "agent_id": A, "language": A,
                                "conversation_id": A, "device_id": A},
    # ── restablecer un dashboard (spec 024, tramo 2) ────────────────────
    # Ata además, en el `estado`, la configuración leída en la vista previa.
    "ha_reset_lovelace_dashboard_config": {"url_path": A},
    # ── mantenimiento del Marketplace (spec 026, tramo 1) ───────────────
    # Lo leído en la vista previa (la entrada crítica o retirada, el
    # `full_name`, la categoría, `custom`, `installed`) va en el `estado`.
    "ha_marketplace_acknowledge_critical": {"repository": A},
    "ha_marketplace_ignore_repository": {"repository_id": A},
    "ha_marketplace_remove_repository": {"repository_id": A},
    "ha_marketplace_refresh_repository": {"repository_id": A},
    # Tramo 2: `backup` cambia lo que se hace al confirmar; el `estado` ata
    # además la versión instalada, el `domain` y el `local_path` leídos.
    "ha_marketplace_uninstall": {"repository_id": A, "backup": A},
    # ── ficheros ────────────────────────────────────────────────────────
    "fs_write_file": {"path": A, "content": A},
    "fs_delete_file": {"path": A},
    "fs_move_file": {"src": A, "dst": A, "overwrite": A},
    "fs_restore_file_backup": {"path": A, "timestamp": A},
    "fs_set_secret": {"key": A, "value": A},
    # ── /addons y /share (spec 034, tramo 2) ────────────────────────────
    # Rutas normalizadas y relativas a la carpeta; el `estado` ata además la
    # huella de lo que la vista previa vio.
    "fs_write_file_in_folder": {"folder": A, "path": A, "content": A},
    "fs_create_dir_in_folder": {"folder": A, "path": A},
    "fs_move_in_folder": {"folder": A, "src": A, "dst": A},
    "fs_delete_in_folder": {"folder": A, "path": A, "recursive": A},
}
# `confirmation_token` está en todas y nunca entra en su propio hash.
for _args in INVENTARIO.values():
    _args["confirmation_token"] = TOKEN


def _es_tool(funcion: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    return any(ast.unparse(d).startswith("mcp.tool") for d in funcion.decorator_list)


def firmas_con_token(carpeta: Path) -> dict[str, list[str]]:
    """Tool → argumentos de su firma, para las que tienen `confirmation_token`."""
    firmas: dict[str, list[str]] = {}
    for fichero in sorted(carpeta.glob("*.py")):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"), filename=str(fichero))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.AsyncFunctionDef, ast.FunctionDef)) and _es_tool(nodo):
                a = nodo.args
                nombres = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
                if "confirmation_token" in nombres:
                    firmas[nodo.name] = nombres
    return firmas


def problemas(carpeta: Path, inventario: dict[str, dict[str, str]]) -> list[str]:
    """Diferencias entre las firmas de `carpeta` y el inventario, legibles."""
    firmas = firmas_con_token(carpeta)
    salida: list[str] = []
    for tool in sorted(set(firmas) - set(inventario)):
        salida.append(f"{tool}: tiene confirmation_token y no está en el inventario")
    for tool in sorted(set(inventario) - set(firmas)):
        salida.append(f"{tool}: está en el inventario y no es una tool con confirmation_token")
    for tool in sorted(set(firmas) & set(inventario)):
        firma, inv = set(firmas[tool]), set(inventario[tool])
        for arg in sorted(firma - inv):
            salida.append(f"{tool}.{arg}: argumento sin clasificar (atado o exento con motivo)")
        for arg in sorted(inv - firma):
            salida.append(f"{tool}.{arg}: en el inventario pero no en la firma")
    for tool, args in sorted(inventario.items()):
        for arg, valor in sorted(args.items()):
            if valor == A:
                continue
            motivo = valor.removeprefix("exento:").strip() if valor.startswith("exento:") else ""
            if not motivo:
                salida.append(f"{tool}.{arg}: {valor!r} no es «atado» ni «exento: <motivo>»")
    return salida


def firmas_publicadas(registro: dict) -> dict[str, list[str]]:
    """Tool → argumentos de su esquema publicado, para las que publican
    `confirmation_token`, sobre el registro real de un `MCPServer`."""
    firmas: dict[str, list[str]] = {}
    for nombre, tool in registro.items():
        propiedades = list((tool.parameters or {}).get("properties", {}))
        if "confirmation_token" in propiedades:
            firmas[nombre] = propiedades
    return firmas


def diferencias_con_el_registro(
    por_ast: dict[str, list[str]], publicadas: dict[str, list[str]]
) -> list[str]:
    """Lo que el descubrimiento por AST no ve del registro real, y al revés."""
    salida: list[str] = []
    for tool in sorted(set(publicadas) - set(por_ast)):
        salida.append(f"{tool}: publica confirmation_token y el AST no la encuentra")
    for tool in sorted(set(por_ast) - set(publicadas)):
        salida.append(f"{tool}: el AST la encuentra y el registro no publica su token")
    for tool in sorted(set(por_ast) & set(publicadas)):
        # `ctx` lo inyecta el SDK y no sale en el esquema publicado.
        ast_args = set(por_ast[tool]) - {"ctx"}
        if ast_args != set(publicadas[tool]):
            salida.append(
                f"{tool}: argumentos distintos (AST {sorted(ast_args)}, "
                f"registro {sorted(publicadas[tool])})"
            )
    return salida


class TestInventarioDeArgumentosAtados(unittest.TestCase):
    def test_cubre_exactamente_las_tools_con_token_y_sus_argumentos(self) -> None:
        self.assertEqual(problemas(TOOLS, INVENTARIO), [])

    def test_recuento(self) -> None:
        # 79 de la auditoría de la 033 + 2 genéricas de la 011 + la escena
        # desde el estado actual (tramo 2 de la 033) + `ha_call_service_response`
        # (018) + las tres de la 012 que confirman + las cinco de la 016 + las
        # cuatro de montajes de la 019 + las cuatro de la 015 + las tres de la 030
        # + las tres de la 017 + las seis de la 020
        # + las seis del tramo 1 de la 022 y la del tramo 2 + las nueve de la
        # 021 + las cuatro del host de la 032 y las dos de su red (tramo 2)
        # + la de la 023 (`ha_process_conversation`) + las cinco de la 031
        # (ajustes, crear, crear con los ajustes automáticos, borrar y
        # restaurar backups de HA) + la de restablecer un dashboard de la 024 + las cuatro del tramo 1 de la 026
        # y la del tramo 2 (desinstalar) + las cuatro que modifican /addons y
        # /share (034, tramo 2).
        self.assertEqual(len(firmas_con_token(TOOLS)), 149)

    def test_el_token_siempre_exento_y_lo_demas_atado_o_con_motivo(self) -> None:
        for tool, args in INVENTARIO.items():
            self.assertEqual(args.get("confirmation_token"), TOKEN, tool)

    def test_el_ast_ve_lo_mismo_que_el_registro_real(self) -> None:
        # T037 (B1 de la revisión): el inventario descubre las tools por AST
        # de `tools/*.py` y decoradores `mcp.tool…`. Una tool con token
        # registrada de otra forma (`mcp.add_tool`, un subpaquete, otro
        # módulo) se le escaparía; el registro real de un `MCPServer` no.
        # Control negativo, comprobado y restaurado: registrando
        # `ha_create_scene_from_current` con `registrar = mcp.tool` y
        # `@registrar()`, el AST deja de verla y este test cae nombrándola.
        from tests.test_tools_registration import _real_registry

        publicadas = firmas_publicadas(_real_registry())
        self.assertEqual(
            diferencias_con_el_registro(firmas_con_token(TOOLS), publicadas), []
        )
        self.assertEqual(len(publicadas), 149)

    def test_las_variables_de_las_entidades_restringidas_quedan_atadas(self) -> None:
        # El hallazgo que origina este inventario (spec 033, FR-001).
        self.assertEqual(INVENTARIO["ha_run_script"]["variables"], A)
        self.assertEqual(INVENTARIO["ha_trigger_automation"]["variables"], A)


class TestControlNegativo(unittest.TestCase):
    """T007: el inventario cae, nombrándolos, ante una tool nueva con token sin
    entrada y ante un argumento nuevo de una tool existente."""

    def test_tool_y_argumento_nuevos_sin_clasificar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copia = Path(tmp) / "tools"
            shutil.copytree(TOOLS, copia)
            scripts = copia / "scripts.py"
            fuente = scripts.read_text(encoding="utf-8")
            viejo = "        variables: dict[str, Any] | None = None,\n        confirmation_token"
            self.assertEqual(fuente.count(viejo), 1)
            fuente = fuente.replace(
                viejo,
                "        variables: dict[str, Any] | None = None,\n"
                "        modo: str | None = None,\n"
                "        confirmation_token",
            )
            scripts.write_text(fuente, encoding="utf-8")
            (copia / "zz_nueva.py").write_text(
                "def register(mcp):\n"
                "    @mcp.tool()\n"
                "    async def ha_tool_ficticia(entity_id: str,"
                " confirmation_token: str | None = None) -> object:\n"
                "        return None\n",
                encoding="utf-8",
            )
            salida = problemas(copia, INVENTARIO)
        self.assertEqual(
            salida,
            [
                "ha_tool_ficticia: tiene confirmation_token y no está en el inventario",
                "ha_run_script.modo: argumento sin clasificar (atado o exento con motivo)",
            ],
        )

    def test_tool_registrada_fuera_del_ast(self) -> None:
        # T037: control negativo permanente de la comparación con el
        # registro. Una tool con token que solo está en el registro (como si
        # se hubiera registrado con `mcp.add_tool`) y un argumento que solo
        # está en el esquema publicado salen nombrados.
        por_ast = firmas_con_token(TOOLS)
        publicadas = {t: list(a) for t, a in por_ast.items()}
        publicadas["ha_tool_por_add_tool"] = ["entity_id", "confirmation_token"]
        publicadas["ha_run_script"].append("modo")
        self.assertEqual(
            diferencias_con_el_registro(por_ast, publicadas),
            [
                "ha_tool_por_add_tool: publica confirmation_token y el AST no la encuentra",
                "ha_run_script: argumentos distintos (AST "
                f"{sorted(por_ast['ha_run_script'])}, registro "
                f"{sorted(publicadas['ha_run_script'])})",
            ],
        )

    def test_motivo_vacio(self) -> None:
        inventario = {t: dict(a) for t, a in INVENTARIO.items()}
        inventario["ha_run_script"]["variables"] = "exento:  "
        salida = problemas(TOOLS, inventario)
        self.assertEqual(len(salida), 1)
        self.assertIn("ha_run_script.variables", salida[0])


if __name__ == "__main__":
    unittest.main()
