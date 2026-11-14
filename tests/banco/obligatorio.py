"""Lo que el job del banco exige a la sesión de pytest (spec 010, FR-007, FR-009).

En el job (`HERMES_BANCO_OBLIGATORIO=1`) el banco no puede quedar en verde sin
haberse ejecutado entero. pytest sale con 0 aunque haya tests saltados,
`xfail`, o ficheros deseleccionados por `-m banco`, así que este plugin lo
comprueba al final de la sesión y, si algo falta, pone la salida a 1 y dice
qué:

- un test saltado (por cualquier motivo, no solo por falta de la URL);
- un `xfail` que no está en la lista explícita de hallazgos documentados, o un
  hallazgo de esa lista que no se ha visto fallar como se esperaba;
- un test de la carpeta del banco sin el marcador `banco` (con `-m banco` se
  deselecciona y no correría en ningún sitio) o un test deseleccionado;
- una tool de las que el inventario da por probadas que no se ha llamado con
  éxito dentro de un test que haya pasado. Esto es lo que hace que el
  invariante de cobertura sea de EJECUCIÓN y no de texto: el nombre de la tool
  en un comentario, en un test saltado o en uno que falla no cuenta.

Lo registra `tests/banco/conftest.py` solo en el job. Es una clase con sus
dependencias inyectadas para poder probarla en la suite normal con un
proyecto de pytest temporal (`tests/test_banco_obligatorio.py`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import pytest

MARCADOR = "banco"


class ComprobacionDelJob:
    def __init__(
        self,
        carpeta: Path,
        xfail_permitidos: Mapping[str, str],
        tools_exigidas: Iterable[str],
        tomar_tools_del_test: Callable[[], set[str]],
    ) -> None:
        self.carpeta = carpeta.resolve()
        self.xfail_permitidos = dict(xfail_permitidos)
        self.tools_exigidas = frozenset(tools_exigidas)
        self.tomar_tools_del_test = tomar_tools_del_test
        self.saltados: list[str] = []
        self.xfail_no_permitidos: list[str] = []
        self.xfail_vistos: set[str] = set()
        self.sin_marcador: list[str] = []
        self.deseleccionados: list[str] = []
        self.tools_probadas: set[str] = set()
        self.problemas: list[str] = []

    # ── Recolección ──────────────────────────────────────────────────────
    def _en_el_banco(self, item: Any) -> bool:
        ruta = Path(str(item.path)).resolve()
        return ruta.name.startswith("test_") and self.carpeta in ruta.parents

    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(self, items: list[Any]) -> None:
        # `tryfirst`: antes de que `-m banco` los quite de la lista.
        for item in items:
            if self._en_el_banco(item) and item.get_closest_marker(MARCADOR) is None:
                self.sin_marcador.append(item.nodeid)

    def pytest_deselected(self, items: list[Any]) -> None:
        self.deseleccionados.extend(item.nodeid for item in items)

    # ── Ejecución ────────────────────────────────────────────────────────
    def pytest_runtest_logstart(self, nodeid: str, location: Any) -> None:
        # Lo que haya quedado de un test anterior no se atribuye a este.
        self.tomar_tools_del_test()

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.skipped:
            if hasattr(report, "wasxfail"):
                if report.nodeid in self.xfail_permitidos:
                    self.xfail_vistos.add(report.nodeid)
                else:
                    self.xfail_no_permitidos.append(report.nodeid)
            else:
                self.saltados.append(report.nodeid)
        if report.when == "call":
            tools = self.tomar_tools_del_test()
            # Solo cuenta lo que se llamó en un test que ha pasado: ahí se
            # comprobó también el efecto con el lector.
            if report.passed and not hasattr(report, "wasxfail"):
                self.tools_probadas |= tools

    # ── Cierre ───────────────────────────────────────────────────────────
    def calcular_problemas(self) -> list[str]:
        problemas: list[str] = []
        if self.saltados:
            problemas.append(f"tests del banco saltados: {sorted(set(self.saltados))}")
        if self.xfail_no_permitidos:
            problemas.append(
                "xfail fuera de la lista de hallazgos documentados "
                f"(XFAIL_PERMITIDOS): {sorted(set(self.xfail_no_permitidos))}"
            )
        no_vistos = sorted(set(self.xfail_permitidos) - self.xfail_vistos)
        if no_vistos:
            problemas.append(
                f"hallazgos de XFAIL_PERMITIDOS que no se han visto fallar: {no_vistos}"
            )
        if self.sin_marcador:
            problemas.append(
                f"tests del banco sin el marcador `{MARCADOR}`: {sorted(set(self.sin_marcador))}"
            )
        if self.deseleccionados:
            problemas.append(f"tests deseleccionados: {sorted(set(self.deseleccionados))}")
        sin_ejecutar = sorted(self.tools_exigidas - self.tools_probadas)
        if sin_ejecutar:
            problemas.append(
                "tools que el inventario da por probadas (PROBADAS_EN_BANCO de la "
                "010, PROBADAS_028…) que ningún test que haya pasado llamó con "
                f"éxito: {sin_ejecutar}"
            )
        return problemas

    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionfinish(self, session: Any, exitstatus: int) -> None:
        self.problemas = self.calcular_problemas()
        if self.problemas and session.exitstatus == 0:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(self, terminalreporter: Any) -> None:
        if not self.problemas:
            return
        terminalreporter.section("banco obligatorio: el job falla", sep="=", red=True)
        for problema in self.problemas:
            terminalreporter.line(problema, red=True)
