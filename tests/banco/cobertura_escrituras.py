"""Inventario de las escrituras de Core en el banco (spec 028, FR-003, FR-004).

Invariante que comprueba `tests/test_banco_cobertura_escrituras.py` en la
suite normal (sin HA ni Docker):

    tools que MODIFICAN del registro de producción
      = cobertura.PROBADAS_EN_BANCO ∪ cobertura.NO_EJECUTABLES
        ∪ cobertura.FALLAN_EN_BANCO                                  (010, 46 + 1 + 0)
      ∪ cobertura.PROBADAS_GENERICAS ∪ cobertura.NO_EJECUTABLES_GENERICAS (011, 1 + 1)
      ∪ PROBADAS_028 ∪ NO_EJECUTABLES_028                            (028, 53)
      ∪ FUERA_DEL_BANCO                                              (24)
      ∪ cobertura_012.PROBADAS_012 ∪ cobertura_012.NO_EJECUTABLES_012  (012, 3)
      ∪ cobertura_021.PROBADAS_021 ∪ cobertura_021.NO_EJECUTABLES_021  (021, 6)

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

«Probada» quiere decir EJECUTADA (contrato de la 010): en el job, el plugin de
`tests/banco/obligatorio.py` exige que cada tool de `TOOLS_EXIGIDAS_DEL_JOB`
(las probadas de la 010, de las genéricas de la 011 y de la 028) se haya llamado con éxito dentro de un
test que ha pasado. Nombrarla en un fichero no basta. Una tool que falla contra
HA real no es probada: va a `FALLAN_EN_BANCO` (vacía desde la spec 033, que
arregló `ha_reload_counters`, el hallazgo de la 010).

Hallazgos de la 028 (`HALLAZGOS_028`): defectos de una tool que funciona por su
camino normal (por eso sigue en `PROBADAS_028` y se exige por ejecución), pero
que falla o es insegura con un argumento concreto. Cada uno tiene su test con
`xfail` estricto que espera ese fallo concreto, en `XFAIL_PERMITIDOS_028`; el
job no admite ningún otro `xfail`. Desde el tramo 2 de la spec 033 no queda
ninguno: los dos de la 028 están arreglados y sus tests ya no son `xfail`.
"""

from __future__ import annotations

from tests.banco import cobertura
from tests.banco.cobertura_012 import PROBADAS_012
from tests.banco.cobertura_021 import LECTURAS_021, PROBADAS_021

# Las 53 de la 028 (26 del tramo A y 27 del B): cada una la llama con éxito
# algún `tests/banco/test_banco_escrituras_*.py` que pasa (lo exige el job) y su
# efecto lo comprueba el lector independiente (salvo `ha_cancel_wait`, cuyo
# efecto vive en Hermes: research R-7 de la 028). Los dos hallazgos de la 028
# están arreglados por la spec 033: el token de `ha_run_script` y
# `ha_trigger_automation` sin `variables` (tramo 1) y
# `ha_create_scene_from_current` con `name` (tramo 2); sus tests ya no son
# `xfail`.
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

# Tool → hallazgo de la 028 (FR-007). La tool funciona por su camino normal
# (está en `PROBADAS_028` y su test lo ejecuta con éxito), pero el banco ha
# visto contra HA Core 2026.11.1 un defecto con un argumento concreto. Vacío
# desde el tramo 2 de la spec 033, que arregló `ha_create_scene_from_current`
# (con `name` Core respondía 400; ahora la tool responde `name_not_supported`
# sin llamar a HA, y pide token para reemplazar una escena temporal).
HALLAZGOS_028: dict[str, str] = {}

# Los `xfail` de la 028 que el job admite: id del test (como lo escribe pytest
# desde la raíz del repositorio) → tool de `HALLAZGOS_028` que documenta. Cada
# uno es estricto y espera una excepción concreta: si la tool se arregla, el
# test pasa y el job se pone en rojo para quitar la marca.
XFAIL_PERMITIDOS_028: dict[str, str] = {}

# Lo que el job del banco exige (`tests/banco/conftest.py`): todas las probadas
# por ejecución y todos los `xfail` de hallazgos listados. Una sub-feature
# nueva con tests en el banco suma aquí sus listas (la 012, `PROBADAS_012`).
TOOLS_EXIGIDAS_DEL_JOB: frozenset[str] = (
    cobertura.PROBADAS_EN_BANCO | cobertura.PROBADAS_GENERICAS | PROBADAS_028
    # Spec 029: lecturas, pero también se exigen por ejecución (FR-022).
    | cobertura.PROBADAS_EN_BANCO_029
    | PROBADAS_012
    # Spec 021: sus escrituras y sus lecturas, todas por ejecución.
    | PROBADAS_021 | LECTURAS_021
)
XFAIL_DEL_JOB: dict[str, str] = {**cobertura.XFAIL_PERMITIDOS, **XFAIL_PERMITIDOS_028}

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
