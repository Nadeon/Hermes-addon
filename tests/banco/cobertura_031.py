"""Inventario de la spec 031 en el banco de Core (FR-022; contrato de la 028).

Cada tool nueva que modifica se ejecuta en el banco y va en `PROBADAS_031`, o
en `NO_EJECUTABLES_031` con un motivo concreto. Las dos listas se suman a la
unión de `tests/test_banco_cobertura_escrituras.py`, y `PROBADAS_031` y
`LECTURAS_EN_BANCO_031` a lo que el job exige por ejecución
(`cobertura_escrituras.TOOLS_EXIGIDAS_DEL_JOB`).

Tramo 1 (agentes y ajustes), en `tests/banco/test_banco_backups_ajustes.py`:
`ha_update_backup_config` modifica y se ejecuta; `ha_list_backup_agents` solo
lee, pero se exige igual por ejecución (como las de la 029).
`ha_get_update_backup_settings` también solo lee, y en el banco solo se puede
probar su `supervisor_integration_unavailable`, que es un error y no cuenta
como ejecución: no se exige.
"""

from __future__ import annotations

PROBADAS_031: frozenset[str] = frozenset({
    "ha_update_backup_config",
})

# Lecturas que el job exige por ejecución; no entran en el invariante de
# escrituras (no modifican) ni en la matriz de pruebas.
LECTURAS_EN_BANCO_031: frozenset[str] = frozenset({
    "ha_list_backup_agents",
})

NO_EJECUTABLES_031: dict[str, str] = {
    "ha_set_update_backup_settings": (
        "necesita la integración hassio, que solo carga con Supervisor; el banco "
        "es Core sin Supervisor (`hassio/update/config/update` no existe); VM de "
        "la 014"
    ),
}
