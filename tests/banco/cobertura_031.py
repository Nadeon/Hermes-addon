"""Inventario de la spec 031 en el banco de Core (FR-022; contrato de la 028).

Cada tool nueva que modifica se ejecuta en el banco y va en `PROBADAS_031`, o
en `NO_EJECUTABLES_031` con un motivo concreto. Las dos listas se suman a la
unión de `tests/test_banco_cobertura_escrituras.py`, y `PROBADAS_031` y
`LECTURAS_EN_BANCO_031` a lo que el job exige por ejecución
(`cobertura_escrituras.TOOLS_EXIGIDAS_DEL_JOB`).

Tramo 1 (agentes y ajustes), en `tests/banco/test_banco_backups_ajustes.py`:
`ha_update_backup_config` modifica y se ejecuta; `ha_list_backup_agents` solo
lee, pero se exige igual por ejecución (como las de la 029).

Tramo 2 (crear y borrar), en `tests/banco/test_banco_backups_acciones.py`:
`ha_create_backup`, `ha_create_automatic_backup` (con la retención borrando
de verdad) y `ha_delete_backup` se ejecutan en el agente `backup.local`.
"""

from __future__ import annotations

PROBADAS_031: frozenset[str] = frozenset({
    "ha_update_backup_config",
    # Tramo 2.
    "ha_create_backup",
    "ha_create_automatic_backup",
    "ha_delete_backup",
})

# Lecturas que el job exige por ejecución; no entran en el invariante de
# escrituras (no modifican) ni en la matriz de pruebas.
LECTURAS_EN_BANCO_031: frozenset[str] = frozenset({
    "ha_list_backup_agents",
})

# Las tools de `hassio/update/config/*` (ajustes del backup previo a
# actualizar) se quitaron en el tramo 1: el proxy WebSocket del Supervisor
# 2026.11.0 rechaza con «Unauthorized» todo `hassio/*` y `supervisor/*` que
# mande una app (`DENIED_WS_TYPE_PREFIXES`), así que no podían funcionar.
NO_EJECUTABLES_031: dict[str, str] = {}

# Los `xfail` de la 031 que el job admite: id del test → tool que documenta.
# Vacío: el único que hubo era el de esas tools quitadas.
XFAIL_PERMITIDOS_031: dict[str, str] = {}
