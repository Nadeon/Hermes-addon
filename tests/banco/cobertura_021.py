"""Inventario de las tools de la spec 021 en el banco de Core.

Contrato de la 028 («Regla para las sub-features siguientes»): cada tool
nueva que modifica se ejecuta en el banco y va en `PROBADAS_021`, o en
`NO_EJECUTABLES_021` con un motivo concreto. Las dos listas se suman a la
unión de `tests/test_banco_cobertura_escrituras.py`, y `PROBADAS_021 |
LECTURAS_021` a lo que el job exige por ejecución
(`cobertura_escrituras.TOOLS_EXIGIDAS_DEL_JOB`).

Tramo a (núcleo y exposición a asistentes), en
`tests/banco/test_banco_configuracion_sistema.py`: las tres que escriben y
las dos de lectura. Las de lectura no modifican (`readOnlyHint`) y no entran
en el invariante de escrituras, pero el job también las exige por ejecución
(como las de la 029). Tramo b (usuarios), en `tests/banco/test_banco_usuarios.py`:
las tres que escriben y la lista. El tramo c (red y HTTP) suma aquí las
suyas.
"""

from __future__ import annotations

PROBADAS_021: frozenset[str] = frozenset({
    "ha_update_core_config",
    "ha_set_entity_exposure",
    "ha_set_expose_new_entities",
    # Tramo b (usuarios), en `tests/banco/test_banco_usuarios.py`.
    "ha_create_user",
    "ha_update_user",
    "ha_delete_user",
})

# Vacío en el tramo a: las tres que escriben se ejecutan contra HA Core real.
NO_EJECUTABLES_021: dict[str, str] = {}

LECTURAS_021: frozenset[str] = frozenset({
    "ha_get_core_config",
    "ha_list_exposed_entities",
    "ha_list_users",
})
