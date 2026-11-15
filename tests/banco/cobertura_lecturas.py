"""Inventario de las LECTURAS nuevas de Core en el banco (T031 de la 008, SC-006).

Las escrituras tienen su invariante desde la 028
(`tests/test_banco_cobertura_escrituras.py`): toda tool que modifica se
ejecuta en el banco o dice por qué no. Las lecturas nuevas de la 1.2.0 solo
lo tenían en algunas sub-features (la 020, 021, 023, 024, 029 y 031 suman
sus listas de lecturas a `TOOLS_EXIGIDAS_DEL_JOB`); el resto se ejecutaba en
`tests/banco/` sin que nada impidiera que dejara de hacerlo.

Invariante que comprueba `tests/test_banco_cobertura_lecturas.py` en la suite
normal (sin HA ni Docker):

    `ha_*` con `readOnlyHint` de una familia de la 1.2.0
      ⊆ TOOLS_EXIGIDAS_DEL_JOB ∪ NO_EJECUTABLES_LECTURAS

y las dos partes son disjuntas. `LECTURAS_EN_BANCO` son las que no sumaba
ninguna sub-feature: se suman aquí a lo que el job exige por EJECUCIÓN
(`tests/banco/obligatorio.py`), así que en el job cada una tiene que haberse
llamado con éxito dentro de un test que ha pasado.

Solo Core (`ha_*`). Las `sv_*` de lectura se prueban con el Supervisor
simulado o con mocks y van a la matriz de la 014 («VM / pendiente»): el
Supervisor del banco no es el real.
"""

from __future__ import annotations

# Lecturas nuevas de Core que ejecuta el banco y que ninguna sub-feature sumaba
# a lo exigido por ejecución → el fichero donde se ejecutan.
_DONDE: dict[str, str] = {
    # Spec 011: la genérica de lectura (sus escrituras ya estaban).
    "ha_read_ws_command": "test_banco_genericas.py",
    # Spec 012: logs, diagnóstico, validación y notificaciones.
    "ha_get_error_log": "test_banco_core_logs.py",
    "ha_get_log_levels": "test_banco_core_logs.py",
    "ha_list_system_log": "test_banco_core_logs.py",
    "ha_list_diagnostics_handlers": "test_banco_core_diagnostico.py",
    "ha_get_config_entry_diagnostics": "test_banco_core_diagnostico.py",
    "ha_list_persistent_notifications": "test_banco_core_diagnostico.py",
    "ha_test_condition": "test_banco_core_diagnostico.py",
    "ha_validate_config": "test_banco_core_diagnostico.py",
    # Spec 015: entidades `update`.
    "ha_list_updates": "test_banco_actualizaciones.py",
    "ha_get_update_release_notes": "test_banco_actualizaciones.py",
    # Spec 016: flujos de integraciones y reparaciones.
    "ha_list_discovered_integrations": "test_banco_integraciones.py",
    "ha_list_config_flow_domains": "test_banco_integraciones.py",
    "ha_list_config_subentries": "test_banco_integraciones.py",
    "ha_get_repair": "test_banco_repairs.py",
    # Spec 017: blueprints y automatización asistida.
    "ha_list_blueprints": "test_banco_blueprints.py",
    "ha_preview_blueprint_substitution": "test_banco_blueprints.py",
    "ha_list_device_triggers": "test_banco_automatizacion_asistida.py",
    "ha_list_device_conditions": "test_banco_automatizacion_asistida.py",
    "ha_list_device_actions": "test_banco_automatizacion_asistida.py",
    "ha_resolve_target": "test_banco_automatizacion_asistida.py",
    "ha_explain_target": "test_banco_automatizacion_asistida.py",
    "ha_list_triggers_for_target": "test_banco_automatizacion_asistida.py",
    "ha_list_conditions_for_target": "test_banco_automatizacion_asistida.py",
    "ha_list_actions_for_target": "test_banco_automatizacion_asistida.py",
    "ha_wait_for_trigger": "test_banco_automatizacion_asistida.py",
}

LECTURAS_EN_BANCO: frozenset[str] = frozenset(_DONDE)

# Lecturas nuevas de Core que no se pueden ejecutar CON ÉXITO en el banco →
# motivo concreto. El banco ejecuta igualmente su camino de rechazo.
NO_EJECUTABLES_LECTURAS: dict[str, str] = {
    "ha_get_device_diagnostics": (
        "ninguna integración sin hardware ni nube ofrece diagnóstico de "
        "dispositivo en HA 2026.11.1 (el de `kitchen_sink` no lo tiene): el "
        "banco solo ejecuta su camino `diagnostics_not_supported` "
        "(test_banco_core_diagnostico.py) y el camino feliz queda en los "
        "unitarios y en la matriz de pruebas en vivo"
    ),
}
