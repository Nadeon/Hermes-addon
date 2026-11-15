"""Inventario de cobertura del banco de la spec 015 (actualizaciones del sistema).

Lo suma el invariante de escrituras (`tests/test_banco_cobertura_escrituras.py`)
y lo descubre la matriz de la 014 (`tests/test_matriz_pruebas.py`) por la
convención de nombres.

Tramos 1 y 2: las cuatro tools que modifican son del Supervisor y no se pueden
ejecutar en el banco de Core, cuyo Supervisor solo simula y reenvía a Core
(research R-12). Se prueban en la suite normal con un Supervisor simulado
(`tests/fixtures/supervisor_actualizaciones.py`) y su prueba real queda
pendiente en la VM de la 014 (fila «VM / pendiente» de la matriz).

Tramo 3: `ha_install_update` está en `PROBADAS_015`: se ejecuta en el banco
(`tests/banco/test_banco_actualizaciones.py`) contra una entidad `update` de
la integración `template` de HA real, y el plugin del job
(`tests/banco/obligatorio.py`) exige que se llame con éxito (lo suma
`cobertura_escrituras.TOOLS_EXIGIDAS_DEL_JOB`). Su encaminamiento a las
`sv_*` y el rechazo de Hermes solo se prueban con simuladores: en el banco no
hay integración `hassio`.

Control negativo (T045 g): sacar `ha_install_update` de `PROBADAS_015` hace
caer `test_todas_las_escrituras_clasificadas` nombrándola.
"""

from __future__ import annotations

_SUPERVISOR_REAL = (
    "Supervisor real: el banco solo simula el Supervisor y reenvía a Core; "
    "prueba manual en la VM de la 014"
)

PROBADAS_015: frozenset[str] = frozenset({"ha_install_update"})

NO_EJECUTABLES_015: dict[str, str] = {
    "sv_check_for_updates": _SUPERVISOR_REAL,
    "sv_update_core": _SUPERVISOR_REAL,
    # Tramo 2.
    "sv_update_os": _SUPERVISOR_REAL,
    "sv_update_supervisor": _SUPERVISOR_REAL,
}
