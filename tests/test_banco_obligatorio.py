"""Lo que el job del banco exige a la sesión de pytest (spec 010, T036, T037).

Se prueba el plugin de `tests/banco/obligatorio.py` de verdad, con pytest: se
monta un proyecto temporal con su propia carpeta de banco, se ejecuta
`pytest -m banco` en otro proceso (como el job) y se mira el código de salida
y el informe. Sin el plugin, todos estos casos salen con 0 (es lo que comprobó
la revisión: «1 passed, 1 skipped, 1 deselected, 1 xfailed → salida 0»).

Control negativo (T036 y T037), comprobado en local y restaurado:
  1. sin poner `session.exitstatus` en `pytest_sessionfinish`, caen
     `test_un_salto_solo_pone_el_job_en_rojo` y
     `test_todo_lo_que_no_vale_a_la_vez`;
  2. contando las tools de cualquier test (no solo de los que pasan), cae
     `test_todo_lo_que_no_vale_a_la_vez` (ya no nombra `ha_d`).
Además, en el CI (rama desechable) un `self.skipTest` en un test del banco
puso el job `banco de Core` en rojo; anotado en el commit.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

CONFTEST = """
from pathlib import Path

import registro
from tests.banco.obligatorio import ComprobacionDelJob

XFAIL_PERMITIDOS = {xfail!r}
EXIGIDAS = {exigidas!r}


def pytest_configure(config):
    config.pluginmanager.register(
        ComprobacionDelJob(
            carpeta=Path(__file__).resolve().parent / "banco",
            xfail_permitidos=XFAIL_PERMITIDOS,
            tools_exigidas=EXIGIDAS,
            tomar_tools_del_test=registro.tomar,
        ),
        "banco-obligatorio",
    )
"""

REGISTRO = """
_tools = set()


def anotar(tool):
    _tools.add(tool)


def tomar():
    tools = set(_tools)
    _tools.clear()
    return tools
"""

TEST_OK = """
import pytest
import registro

pytestmark = pytest.mark.banco


def test_a():
    registro.anotar("ha_a")


def test_b():
    registro.anotar("ha_b")
"""

TEST_HALLAZGO = """
import pytest
import registro

pytestmark = pytest.mark.banco


@pytest.mark.xfail(strict=True, raises=ValueError)
def test_hallazgo():
    registro.anotar("ha_c")
    raise ValueError("el fallo documentado")
"""

TEST_SALTA = """
import unittest

import pytest

pytestmark = pytest.mark.banco


class TestSalta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raise unittest.SkipTest("cualquier motivo")

    def test_x(self):
        pass
"""

TEST_SIN_MARCA = """
import registro


def test_sin_marca():
    # Con -m banco se deselecciona: no corre en ningún sitio.
    registro.anotar("ha_a")
"""

TEST_OTRO_XFAIL = """
import pytest
import registro

pytestmark = pytest.mark.banco


@pytest.mark.xfail(reason="no está en la lista")
def test_otro():
    registro.anotar("ha_d")
    raise AssertionError("otro fallo")
"""

PERMITIDO = {"banco/test_hallazgo.py::test_hallazgo": "ha_c"}


def _ejecutar(ficheros: dict[str, str], xfail: dict[str, str], exigidas: set[str]):
    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp)
        (raiz / "banco").mkdir()
        (raiz / "pytest.ini").write_text("[pytest]\nmarkers =\n    banco: banco\n", encoding="utf-8")
        (raiz / "conftest.py").write_text(
            CONFTEST.format(xfail=xfail, exigidas=sorted(exigidas)), encoding="utf-8"
        )
        (raiz / "registro.py").write_text(REGISTRO, encoding="utf-8")
        for nombre, codigo in ficheros.items():
            (raiz / "banco" / nombre).write_text(textwrap.dedent(codigo), encoding="utf-8")
        entorno = {
            k: v for k, v in os.environ.items() if not k.startswith(("HERMES_BANCO", "PYTEST_"))
        }
        entorno["PYTHONPATH"] = str(RAIZ)
        entorno["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-m", "banco", "-q", "-p", "no:cacheprovider", "-rs"],
            cwd=raiz,
            env=entorno,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )


class TestComprobacionDelJob(unittest.TestCase):
    def test_banco_completo_sale_con_0(self) -> None:
        # El hallazgo documentado sí se admite, porque está en la lista.
        resultado = _ejecutar(
            {"test_ok.py": TEST_OK, "test_hallazgo.py": TEST_HALLAZGO},
            PERMITIDO,
            {"ha_a", "ha_b"},
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("2 passed, 1 xfailed", resultado.stdout)
        self.assertNotIn("banco obligatorio", resultado.stdout)

    def test_un_salto_solo_pone_el_job_en_rojo(self) -> None:
        # El hallazgo ALTO de la revisión: un salto que no es la falta de URL.
        resultado = _ejecutar(
            {"test_ok.py": TEST_OK, "test_hallazgo.py": TEST_HALLAZGO, "test_salta.py": TEST_SALTA},
            PERMITIDO,
            {"ha_a", "ha_b"},
        )
        self.assertEqual(resultado.returncode, 1, resultado.stdout + resultado.stderr)
        self.assertIn("1 skipped", resultado.stdout)
        self.assertIn("tests del banco saltados", resultado.stdout)
        self.assertIn("test_salta.py::TestSalta::test_x", resultado.stdout)

    def test_todo_lo_que_no_vale_a_la_vez(self) -> None:
        resultado = _ejecutar(
            {
                "test_ok.py": TEST_OK,
                "test_salta.py": TEST_SALTA,
                "test_sin_marca.py": TEST_SIN_MARCA,
                "test_otro.py": TEST_OTRO_XFAIL,
            },
            # Un hallazgo de la lista que no se ha visto fallar (aquí, porque
            # su fichero no está).
            PERMITIDO,
            # `ha_d` solo se llama en un test xfail y `ha_e` en ninguno; `ha_a`
            # sí cuenta (test_ok pasa), aunque también se nombre en el
            # deseleccionado.
            {"ha_a", "ha_b", "ha_d", "ha_e"},
        )
        salida = resultado.stdout
        self.assertEqual(resultado.returncode, 1, salida + resultado.stderr)
        self.assertIn("banco obligatorio: el job falla", salida)
        self.assertIn("tests del banco saltados", salida)
        self.assertIn("xfail fuera de la lista", salida)
        self.assertIn("banco/test_otro.py::test_otro", salida)
        self.assertIn("que no se han visto fallar: ['banco/test_hallazgo.py::test_hallazgo']", salida)
        self.assertIn("sin el marcador `banco`: ['banco/test_sin_marca.py::test_sin_marca']", salida)
        self.assertIn("tests deseleccionados: ['banco/test_sin_marca.py::test_sin_marca']", salida)
        self.assertIn("con éxito: ['ha_d', 'ha_e']", salida)


if __name__ == "__main__":
    unittest.main()
