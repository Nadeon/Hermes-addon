"""La lista de compatibilidad con la 1.1.2 de la spec 008 y la fecha de la
1.2.0 (revisión final del programa, MEDIO-1 y el informativo del CHANGELOG).

La sección «Compatibilidad con la 1.1.2» de `specs/008-cobertura-total/spec.md`
dice que su lista de cambios de comportamiento sale de la entrada `## [1.2.0]`
del CHANGELOG. Los dos cierres (seguridad transversal y robustez) y la
revisión final cambiaron tools de la 1.1.2 sin pasar por esa lista.

Controles negativos, comprobados un momento con los ficheros de 001cc6c:
- con la spec de entonces caen
  `test_cada_tool_de_la_1_1_2_de_los_cierres_esta_en_la_lista` (faltaban
  `fs_set_secret`, `fs_write_file`, `ha_continue_options_flow`,
  `ha_start_options_flow`, `ha_update_entity_registry`…) y las cinco
  subpruebas de `test_los_cambios_de_los_cierres`;
- con el CHANGELOG de entonces cae `test_la_1_2_0_lleva_su_fecha`
  (`<fecha de publicación>`).
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
_SPEC = _RAIZ / "specs" / "008-cobertura-total" / "spec.md"
_CHANGELOG = _RAIZ / "hermes" / "CHANGELOG.md"
_ESQUEMAS = _RAIZ / "tests" / "fixtures" / "esquemas_1_1_2.json"


def _tramo(texto: str, desde: str, hasta: str) -> str:
    inicio = texto.index(desde)
    return texto[inicio:texto.index(hasta, inicio + len(desde))]


def _lista_de_la_spec() -> str:
    spec = _SPEC.read_text(encoding="utf-8")
    return _tramo(spec, "### Compatibilidad con la 1.1.2", "\n## ")


def _tools_de_la_1_1_2() -> set[str]:
    datos = json.loads(_ESQUEMAS.read_text(encoding="utf-8"))
    return set(datos["tools"] if "tools" in datos else datos)


def _cita(texto: str, nombre: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(nombre)}(?!\w)", texto) is not None


class TestListaDeCompatibilidad(unittest.TestCase):
    def test_cada_tool_de_la_1_1_2_de_los_cierres_esta_en_la_lista(self) -> None:
        changelog = _CHANGELOG.read_text(encoding="utf-8")
        entrada = _tramo(changelog, "## [1.2.0]", "\n## [1.1.2]")
        cierres = (_tramo(entrada, "### Cierre: seguridad transversal", "\n### ")
                   + entrada[entrada.index("### Cierre: robustez"):])
        lista = _lista_de_la_spec()
        citadas = sorted(t for t in _tools_de_la_1_1_2() if _cita(cierres, t))
        self.assertGreater(len(citadas), 5, citadas)
        faltan = [t for t in citadas if not _cita(lista, t)]
        self.assertEqual(faltan, [], "tools de la 1.1.2 de los cierres sin su viñeta")

    def test_los_cambios_de_los_cierres(self) -> None:
        lista = _lista_de_la_spec()
        for marca in ("`usuario:***@`", "`***REDACTED***`", "`sin_eco_del_supervisor`",
                      "D-13", "`HATimeoutError`"):
            with self.subTest(marca=marca):
                self.assertIn(marca, lista)


class TestFechaDeLa120(unittest.TestCase):
    def test_la_1_2_0_lleva_su_fecha(self) -> None:
        changelog = _CHANGELOG.read_text(encoding="utf-8")
        self.assertRegex(changelog, r"(?m)^## \[1\.2\.0\] — 2026-11-15$")
        self.assertNotIn("<fecha de publicación>",
                         _tramo(changelog, "## [1.2.0]", "\n## [1.1.2]"))


if __name__ == "__main__":
    unittest.main()
