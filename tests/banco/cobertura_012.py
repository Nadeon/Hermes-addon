"""Inventario de las escrituras de la spec 012 en el banco de Core.

Contrato de la 028 («Regla para las sub-features siguientes»): cada tool
nueva que modifica se ejecuta en el banco y va en `PROBADAS_012`, o en
`NO_EJECUTABLES_012` con un motivo concreto. Las dos listas se suman a la
unión de `tests/test_banco_cobertura_escrituras.py` y `PROBADAS_012` a lo que
el job exige por ejecución (`cobertura_escrituras.TOOLS_EXIGIDAS_DEL_JOB`).

Tramo A (logs): `ha_set_log_level` y `ha_clear_system_log`, las dos en
`tests/banco/test_banco_core_logs.py`. Tramo B:
`ha_dismiss_persistent_notification`, en
`tests/banco/test_banco_core_diagnostico.py`. Las otras seis del tramo B no
modifican (`readOnlyHint`) y no entran en el invariante, aunque también se
ejecutan en ese fichero.
"""

from __future__ import annotations

PROBADAS_012: frozenset[str] = frozenset({
    "ha_set_log_level",
    "ha_clear_system_log",
    "ha_dismiss_persistent_notification",
})

# Vacío: todas las de la 012 se ejecutan contra HA Core real en el banco.
NO_EJECUTABLES_012: dict[str, str] = {}
