"""Inventario de la spec 016 en el banco de Core (contrato de la 028, S-02).

Las tools de la 016 que modifican HA se ejecutan en el banco
(`tests/banco/test_banco_integraciones.py` y, en el tramo C,
`tests/banco/test_banco_repairs.py`) contra HA Core real, con la integración
de prueba `banco_flujos` (`tests/banco/ha_config/custom_components/`), y su
efecto lo comprueba el lector independiente.

`PROBADAS_016` se suma a la unión del invariante
(`tests/test_banco_cobertura_escrituras.py`) y a `TOOLS_EXIGIDAS_DEL_JOB`
(`tests/banco/cobertura_escrituras.py`): el job exige que cada una se haya
llamado con éxito dentro de un test que pasa. Cada tramo de la 016 añade aquí
las suyas.
"""

from __future__ import annotations

# Tramo A (T013): las dos que modifican. Las dos de lectura
# (`ha_list_discovered_integrations`, `ha_list_config_flow_domains`) también
# se ejecutan en el banco, pero el invariante es de las que modifican.
# Tramo B (T027): las siete que modifican. `ha_list_config_subentries`
# también se ejecuta. El reconfigure se prueba con token en cada paso y con
# el rechazo de `ha_continue_config_entry_flow` (decisión del supervisor).
# Tramo C (T042): las tres de los flujos de reparación
# (`tests/banco/test_banco_repairs.py`); `ha_get_repair` y los textos de
# `ha_list_repairs` también se ejecutan. La reautenticación con token de
# `ha_continue_config_entry_flow` (1.1.2, ya en el inventario de la 010) se
# prueba en `TestReauth` de `test_banco_integraciones.py`.
PROBADAS_016: frozenset[str] = frozenset(
    {
        "ha_ignore_discovery",
        "ha_update_config_entry",
        "ha_start_subentry_flow",
        "ha_continue_subentry_flow",
        "ha_abort_subentry_flow",
        "ha_update_subentry",
        "ha_delete_subentry",
        "ha_start_reconfigure_flow",
        "ha_continue_reconfigure_flow",
        "ha_start_repair_fix",
        "ha_continue_repair_fix",
        "ha_abort_repair_fix",
    }
)

# `ha_*` de la 016 que no se pueden ejecutar en el banco → motivo. Vacío.
NO_EJECUTABLES_016: dict[str, str] = {}
