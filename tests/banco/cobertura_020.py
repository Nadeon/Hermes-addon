"""Inventario de las escrituras de la spec 020 en el banco de Core.

Contrato de la 028 («Regla para las sub-features siguientes»): cada tool
nueva que modifica se ejecuta en el banco y va en `PROBADAS_020`, o en
`NO_EJECUTABLES_020` con un motivo concreto. Las dos listas se suman a la
unión de `tests/test_banco_cobertura_escrituras.py` y `PROBADAS_020` a lo que
el job exige por ejecución (`cobertura_escrituras.TOOLS_EXIGIDAS_DEL_JOB`).

Tramo 1: `ha_clear_statistics`, `ha_change_statistics_unit` y
`ha_update_statistics_metadata`, en `tests/banco/test_banco_estadisticas.py`
(el lector siembra las estadísticas y comprueba cada efecto).

Tramo 2: `ha_adjust_statistics_sum` e `ha_import_statistics`, en el mismo
fichero. `recorder/update_statistics_issues` va por `ha_call_ws_command`
(decisión D-3), que ya está en `PROBADAS_GENERICAS`; su caso también está
allí.

`MODULOS_020` son los módulos de la 020. `statistics_maintenance` entra en la
familia `recorder` de la 029, así que el test de los módulos de las familias
de la 029 (`tests/test_banco_cobertura.py`) los resta: las tools de la 020
se cuentan aquí, no en `PROBADAS_EN_BANCO_029`.

Tramo 3: `ha_update_energy_prefs` (familia `energy`) en
`tests/banco/test_banco_energia.py`. `ha_get_energy_prefs` solo lee, así que
no entra en el invariante de escrituras; va en `LECTURAS_020` (nombre fuera
de la convención `PROBADAS*`, que es de las escrituras) y también se exige
por ejecución en el job (FR-021). Entre las dos listas, exactamente lo que
registran `MODULOS_020` (`tests/test_banco_cobertura.py`).
"""

from __future__ import annotations

MODULOS_020: tuple[str, ...] = ("statistics_maintenance", "energy")

PROBADAS_020: frozenset[str] = frozenset({
    "ha_clear_statistics",
    "ha_change_statistics_unit",
    "ha_update_statistics_metadata",
    "ha_adjust_statistics_sum",
    "ha_import_statistics",
    "ha_update_energy_prefs",
})

# Lecturas de la 020 que el job también exige por ejecución.
LECTURAS_020: frozenset[str] = frozenset({"ha_get_energy_prefs"})

# Vacío: todas las de la 020 se ejecutan contra HA Core real en el banco.
NO_EJECUTABLES_020: dict[str, str] = {}
