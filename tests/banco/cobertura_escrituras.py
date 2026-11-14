"""Inventario de las escrituras de Core en el banco (spec 028, FR-003, FR-004).

Invariante que comprueba `tests/test_banco_cobertura_escrituras.py` en la
suite normal (sin HA ni Docker):

    tools que MODIFICAN del registro de producción
      = cobertura.PROBADAS_EN_BANCO ∪ cobertura.NO_EJECUTABLES      (010, 47)
      ∪ PROBADAS_028 ∪ NO_EJECUTABLES_028                            (028, 53)
      ∪ FUERA_DEL_BANCO                                              (24)

«Modifica» = sin `readOnlyHint` en la tabla central de anotaciones
(`hermes/src/hermes/tools/_annotations.py`): es la misma definición que ve el
cliente, y no la del prefijo (`ha_wait_for_event` lee sin ser `ha_get_*`;
`sv_check_core_config` escribe aunque lo parezca). Las partes son disjuntas y
ningún motivo puede estar vacío. Así, una tool que modifica HA no puede entrar
en Hermes sin ejecutarse contra HA Core real o sin decir por qué no se puede.

Regla para las sub-features siguientes (contrato de la 028): la que añada una
tool que modifica la ejecuta en el banco y la pone en su propia lista de
probadas, en su propio módulo `tests/banco/cobertura_<NNN>.py`; si no se puede
ejecutar en el banco, la pone en su lista de no ejecutables con un motivo
concreto (o en `FUERA_DEL_BANCO` si es `fs_*` o `sv_*`). Después suma su lista
a la unión del test del invariante (una línea). Si no lo hace, el test cae en
su rama nombrando la tool.

El inventario de los helpers es de la 010 (`tests/banco/cobertura.py`) y no se
toca desde aquí: se importa y se suma.
"""

from __future__ import annotations

# Las 53 de la 028 (26 del tramo A y 27 del B): cada una la llama algún
# `tests/banco/test_banco_escrituras_*.py` y su efecto lo comprueba el lector
# independiente (salvo `ha_cancel_wait`, cuyo efecto vive en Hermes: research
# R-7 de la 028).
PROBADAS_028: frozenset[str] = frozenset(
    {
        # automation (6)
        "ha_create_or_update_automation",
        "ha_disable_automation",
        "ha_enable_automation",
        "ha_trigger_automation",
        "ha_reload_automations",
        "ha_delete_automation",
        # script (4)
        "ha_create_or_update_script",
        "ha_run_script",
        "ha_reload_scripts",
        "ha_delete_script",
        # scene (5)
        "ha_create_or_update_scene",
        "ha_activate_scene",
        "ha_create_scene_from_current",
        "ha_reload_scenes",
        "ha_delete_scene",
        # servicios y eventos (3)
        "ha_call_service",
        "ha_call_service_response",
        "ha_fire_event",
        # esperas (1)
        "ha_cancel_wait",
        # Lovelace (7)
        "ha_create_lovelace_dashboard",
        "ha_update_lovelace_dashboard_metadata",
        "ha_save_lovelace_dashboard",
        "ha_delete_lovelace_dashboard",
        "ha_create_lovelace_resource",
        "ha_update_lovelace_resource",
        "ha_delete_lovelace_resource",
        # registros: áreas, plantas, etiquetas y categorías (12)
        "ha_create_area",
        "ha_update_area",
        "ha_delete_area",
        "ha_create_floor",
        "ha_update_floor",
        "ha_delete_floor",
        "ha_create_label",
        "ha_update_label",
        "ha_delete_label",
        "ha_create_category",
        "ha_update_category",
        "ha_delete_category",
        # dispositivos, entidades y reparaciones (6)
        "ha_update_device",
        "ha_remove_device",
        "ha_remove_device_from_config_entry",
        "ha_update_entity_registry",
        "ha_remove_entity_registry",
        "ha_ignore_repair",
        # config entries y flujos (9)
        "ha_reload_config_entry",
        "ha_disable_config_entry",
        "ha_enable_config_entry",
        "ha_delete_config_entry",
        "ha_start_config_entry_flow",
        "ha_continue_config_entry_flow",
        "ha_abort_config_entry_flow",
        "ha_start_options_flow",
        "ha_continue_options_flow",
    }
)

# `ha_*` que no se pueden ejecutar en el banco → motivo concreto (qué falta:
# hardware, internet, nube o Supervisor). Vacío: todas se ejecutan.
NO_EJECUTABLES_028: dict[str, str] = {}

_FS = (
    "no habla con HA: escribe en el /config de Hermes, que en el banco es una "
    "carpeta del runner distinta de la de HA; FR-014 de la 008 es solo para "
    "ha_*, y la suite normal la ejecuta contra un sistema de ficheros real"
)
_SV_BACKUPS = (
    "backups, trabajos y validación del Supervisor: el Supervisor del banco es "
    "un simulado que solo reenvía a Core; se prueba con simuladores en la "
    "suite normal y en la VM de la 014"
)
_SV_ADDONS = (
    "add-ons: necesitan el Supervisor real (y la tienda, con internet); se "
    "prueba con simuladores en la suite normal y en la VM de la 014"
)
_SV_REINICIOS = (
    "reinicia Core o el host: no existe en el Supervisor simulado y el banco "
    "no sobreviviría; se prueba con simuladores y en la VM de la 014"
)
_SV_AVISOS = (
    "avisos del Supervisor: solo existen en el Supervisor real; se prueba con "
    "simuladores en la suite normal y en la VM de la 014"
)

# Solo `fs_*` y `sv_*`: una `ha_*` que no se pueda ejecutar va a
# `NO_EJECUTABLES_028` con su motivo, nunca aquí (lo vigila el invariante).
FUERA_DEL_BANCO: dict[str, str] = {
    "fs_write_file": _FS,
    "fs_delete_file": _FS,
    "fs_move_file": _FS,
    "fs_restore_file_backup": _FS,
    "fs_set_secret": _FS,
    "sv_check_core_config": _SV_BACKUPS,
    "sv_get_job_status": _SV_BACKUPS,
    "sv_create_backup_full": _SV_BACKUPS,
    "sv_create_backup_partial": _SV_BACKUPS,
    "sv_create_safety_backup": _SV_BACKUPS,
    "sv_delete_backup": _SV_BACKUPS,
    "sv_restore_backup_full": _SV_BACKUPS,
    "sv_restore_backup_partial": _SV_BACKUPS,
    "sv_install_addon": _SV_ADDONS,
    "sv_uninstall_addon": _SV_ADDONS,
    "sv_update_addon": _SV_ADDONS,
    "sv_start_addon": _SV_ADDONS,
    "sv_stop_addon": _SV_ADDONS,
    "sv_restart_addon": _SV_ADDONS,
    "sv_set_addon_options": _SV_ADDONS,
    "sv_restart_core": _SV_REINICIOS,
    "sv_reboot_host": _SV_REINICIOS,
    "sv_dismiss_resolution_issue": _SV_AVISOS,
    "sv_dismiss_resolution_suggestion": _SV_AVISOS,
}
