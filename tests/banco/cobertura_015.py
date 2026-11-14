"""Inventario de cobertura del banco de la spec 015 (actualizaciones del sistema).

Lo suma el invariante de escrituras (`tests/test_banco_cobertura_escrituras.py`)
y lo descubre la matriz de la 014 (`tests/test_matriz_pruebas.py`) por la
convención de nombres.

Tramo 1: las dos tools que modifican son del Supervisor y no se pueden
ejecutar en el banco de Core, cuyo Supervisor solo simula y reenvía a Core
(research R-12). Se prueban en la suite normal con un Supervisor simulado
(`tests/fixtures/supervisor_actualizaciones.py`) y su prueba real queda
pendiente en la VM de la 014 (fila «VM / pendiente» de la matriz).

El tramo 3 añade `ha_install_update` a `PROBADAS_015` (ejecutada en el banco
con una entidad `update` de plantilla) y las `sv_*` del tramo 2 a
`NO_EJECUTABLES_015`.
"""

from __future__ import annotations

_SUPERVISOR_REAL = (
    "Supervisor real: el banco solo simula el Supervisor y reenvía a Core; "
    "prueba manual en la VM de la 014"
)

PROBADAS_015: frozenset[str] = frozenset()

NO_EJECUTABLES_015: dict[str, str] = {
    "sv_check_for_updates": _SUPERVISOR_REAL,
    "sv_update_core": _SUPERVISOR_REAL,
}
