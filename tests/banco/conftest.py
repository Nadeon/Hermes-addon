"""Configuración de pytest para `tests/banco/` (spec 010, FR-007, FR-009).

Solo en el job del banco (`HERMES_BANCO_OBLIGATORIO=1`) registra la
comprobación de fin de sesión de `tests/banco/obligatorio.py`: con ella, un
salto, un `xfail` fuera de la lista de hallazgos, un test sin el marcador o
deseleccionado, o una tool del inventario que no se ha ejecutado con éxito,
ponen el job en rojo. En la suite normal no hace nada: ahí los tests del banco
se saltan con su motivo, como debe ser.
"""

from __future__ import annotations

from pathlib import Path

from tests.banco import entorno
from tests.banco.cobertura import PROBADAS_EN_BANCO, XFAIL_PERMITIDOS
from tests.banco.obligatorio import ComprobacionDelJob


def pytest_configure(config) -> None:  # type: ignore[no-untyped-def]
    if not entorno._obligatorio():
        return
    config.pluginmanager.register(
        ComprobacionDelJob(
            carpeta=Path(__file__).resolve().parent,
            xfail_permitidos=XFAIL_PERMITIDOS,
            tools_exigidas=PROBADAS_EN_BANCO,
            tomar_tools_del_test=entorno.tomar_tools_del_test,
        ),
        "banco-obligatorio",
    )
