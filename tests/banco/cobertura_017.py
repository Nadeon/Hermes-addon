"""Inventario de las escrituras de la spec 017 en el banco de Core.

Contrato de la 028 («Regla para las sub-features siguientes»): cada tool
nueva que modifica se ejecuta en el banco y va en `PROBADAS_017`, o en
`NO_EJECUTABLES_017` con un motivo concreto. Las dos listas se suman a la
unión de `tests/test_banco_cobertura_escrituras.py` y `PROBADAS_017` a lo que
el job exige por ejecución (`cobertura_escrituras.TOOLS_EXIGIDAS_DEL_JOB`).

Tramo A (blueprints locales): `ha_save_blueprint` y `ha_delete_blueprint`, en
`tests/banco/test_banco_blueprints.py`, con el efecto comprobado por el lector
(`blueprint/list` directo a Core). `ha_list_blueprints` y
`ha_preview_blueprint_substitution` no modifican (`readOnlyHint`) y no entran
en el invariante, aunque también se ejecutan en ese fichero.

Tramo B (importar): `ha_import_blueprint`, en el mismo fichero, importando
desde `/local/` de la propia HA del banco (que no tiene salida a internet):
importador genérico. Los de GitHub, gist y foro, prueba manual pendiente.
"""

from __future__ import annotations

PROBADAS_017: frozenset[str] = frozenset({
    "ha_save_blueprint",
    "ha_delete_blueprint",
    "ha_import_blueprint",
})

# Vacío: todas las de la 017 se ejecutan contra HA Core real en el banco.
NO_EJECUTABLES_017: dict[str, str] = {}
