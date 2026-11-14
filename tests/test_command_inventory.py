"""Forma de los inventarios de la 008 de los que sale la tabla de comandos
(spec 011, FR-006, T003).

La tabla de clasificación (`hermes/command_table.py`) y su test de deriva
comparan claves: un comando de Core o un par (método, plantilla de ruta) del
Supervisor. Si el inventario agrupa varias rutas en una fila («GET/POST»,
listas con comas, variantes entre corchetes, «(n)»), la deriva no puede
compararse fila a fila y una ruta agrupada se quedaría sin clasificar sin que
nadie lo viera. Estos tests fijan una fila por clave y los recuentos por clase
que publicó la 008, para que una edición del TSV que pierda o duplique filas
falle aquí y no en producción.

Control negativo (T003): con el TSV agrupado de la 008 (217 filas) fallaban
el recuento de 254, la forma del método (`GET/POST`, `GET/POST/DELETE`) y la
forma de la ruta (comas, corchetes, espacios y «(n)»), y los recuentos por
clase (A 115, B 47, D 18). Tras normalizar (T004), verde.
"""

from __future__ import annotations

import collections
import csv
import pathlib
import re
import unittest

_INVENTARIO = (
    pathlib.Path(__file__).resolve().parents[1]
    / "specs" / "008-cobertura-total" / "inventario"
)

_FORMA_COMANDO = re.compile(r"^[a-z0-9_-]+(/[a-z0-9_-]+)*$")
_FORMA_CAP = re.compile(r"^CAP-\d{3}$")
_METODOS = {"GET", "POST", "PUT", "DELETE", "PATCH"}


def _leer(nombre: str) -> list[dict[str, str]]:
    with (_INVENTARIO / nombre).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _clase_core(fila: dict[str, str]) -> str:
    return fila["clase"]


def _clase_supervisor(fila: dict[str, str]) -> str:
    # «A (parcial)» (POST /supervisor/options) cuenta como A: la 008 la suma a
    # los 130 huecos de clase A del Supervisor.
    return "A" if fila["clase"].startswith("A") else fila["clase"]


class TestInventarioCore(unittest.TestCase):
    def setUp(self) -> None:
        self.filas = _leer("core-ws.tsv")

    def test_623_filas_con_comando_unico(self) -> None:
        self.assertEqual(len(self.filas), 623)
        comandos = [f["comando"] for f in self.filas]
        repetidos = sorted(c for c, n in collections.Counter(comandos).items() if n > 1)
        self.assertEqual(repetidos, [], f"comandos repetidos: {repetidos}")

    def test_forma_del_comando(self) -> None:
        malos = sorted(f["comando"] for f in self.filas
                       if not _FORMA_COMANDO.match(f["comando"]))
        self.assertEqual(malos, [], f"comandos con forma inválida: {malos}")

    def test_a_y_c_tienen_cap(self) -> None:
        sin_cap = sorted(f["comando"] for f in self.filas
                         if f["clase"] in {"A", "C"} and not _FORMA_CAP.match(f["cap"]))
        self.assertEqual(sin_cap, [], f"filas A/C sin CAP: {sin_cap}")

    def test_recuentos_por_clase_de_la_008(self) -> None:
        cuenta = collections.Counter(_clase_core(f) for f in self.filas)
        self.assertEqual(dict(cuenta), {
            "cubierto": 130, "A": 147, "B": 103, "C": 192, "D": 51,
        })


class TestInventarioSupervisor(unittest.TestCase):
    def setUp(self) -> None:
        self.filas = _leer("supervisor-rutas.tsv")

    def test_254_filas_con_metodo_y_ruta_unicos(self) -> None:
        self.assertEqual(len(self.filas), 254)
        claves = [(f["metodo"], f["ruta"]) for f in self.filas]
        repetidas = sorted(c for c, n in collections.Counter(claves).items() if n > 1)
        self.assertEqual(repetidas, [], f"claves repetidas: {repetidas}")

    def test_forma_del_metodo(self) -> None:
        malos = sorted({f["metodo"] for f in self.filas} - _METODOS)
        self.assertEqual(malos, [], f"métodos inválidos: {malos}")

    def test_forma_de_la_ruta(self) -> None:
        # Una ruta por fila: nada de listas, variantes ni recuentos agrupados.
        malas = sorted(
            f["ruta"] for f in self.filas
            if not f["ruta"].startswith("/")
            or any(c in f["ruta"] for c in ",[] ")
            or re.search(r"\(\d+\)", f["ruta"])
        )
        self.assertEqual(malas, [], f"rutas con forma inválida: {malas}")

    def test_a_y_c_tienen_cap(self) -> None:
        sin_cap = sorted(
            (f["metodo"], f["ruta"]) for f in self.filas
            if _clase_supervisor(f) in {"A", "C"} and not _FORMA_CAP.match(f["cap"])
        )
        self.assertEqual(sin_cap, [], f"filas A/C sin CAP: {sin_cap}")

    def test_recuentos_por_clase_de_la_008(self) -> None:
        cuenta = collections.Counter(_clase_supervisor(f) for f in self.filas)
        self.assertEqual(dict(cuenta), {"cubierto": 37, "A": 130, "B": 67, "D": 20})


if __name__ == "__main__":
    unittest.main()
