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
        "el proxy WebSocket del Supervisor rechaza con «Unauthorized» todo "
        "comando `hassio/*` que mande una app (HALLAZGO de la 031, el mismo que "
        "`DENEGADAS_POR_EL_PROXY_031`); además, el banco es Core sin la "
        "integración hassio; VM de la 014"
    ),
}

# HALLAZGO del tramo 1 (CI del banco, 2026-11-15): las dos tools de
# `hassio/update/config/*` no pueden funcionar desde un add-on. Hermes habla
# con Core por el proxy WebSocket del Supervisor, y el Supervisor 2026.11.0
# (`supervisor/api/proxy.py`, `DENIED_WS_TYPE_PREFIXES`) rechaza todo comando
# `supervisor/*` y `hassio/*` que mande una app: solo el frontend de HA puede
# usarlos. El simulado del banco copia esa regla, y por eso
# `ha_get_update_backup_settings` responde «HA WS command failed:
# Unauthorized» y no `supervisor_integration_unavailable`. No es un fallo de
# HA ni del banco: es la spec (FR-004) la que suponía que el comando llegaba.
# Decidir qué se hace con las dos tools queda para el supervisor del programa.
# El nombre no empieza por `HALLAZGOS`: esa convención (matriz de la 014) es
# de tools que modifican y están probadas, y esta lee.
DENEGADAS_POR_EL_PROXY_031: dict[str, str] = {
    "ha_get_update_backup_settings": (
        "HALLAZGO (spec 031): el proxy WebSocket del Supervisor rechaza "
        "`hassio/update/config/info` (Unauthorized) a las apps"
    ),
    "ha_set_update_backup_settings": (
        "HALLAZGO (spec 031): el proxy WebSocket del Supervisor rechaza "
        "`hassio/update/config/update` (Unauthorized) a las apps"
    ),
}

# Los `xfail` de la 031 que el job admite: id del test → tool que documenta.
# Estricto y con su excepción concreta: si el comando empieza a llegar, el
# test pasa y el job se pone en rojo para quitar la marca.
XFAIL_PERMITIDOS_031: dict[str, str] = {
    "tests/banco/test_banco_backups_ajustes.py::TestAgentesYAjustes::test_ajustes_previos_a_actualizar_sin_supervisor": "ha_get_update_backup_settings",
}
