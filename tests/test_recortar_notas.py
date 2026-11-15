"""`scripts/recortar_notas.py`: las notas de una release caben en GitHub.

La release de la 1.2.0 falló con HTTP 422 porque sus notas pasaban de los
125 000 caracteres que admite GitHub. `etiquetar.yml` pasa ahora las notas por
este script antes de crear la release.

Control negativo (comprobado): con `recortar` devolviendo siempre las notas sin
tocar, caen 5 de 9: `test_recorta_y_enlaza_el_changelog`,
`test_cierra_un_bloque_de_codigo_abierto`, `test_una_sola_linea_enorme`,
`test_la_entrada_de_la_1_2_0_cabe` y `test_reescribe_el_fichero_solo_si_recorta`.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from scripts.recortar_notas import LIMITE, main, recortar

RAIZ = Path(__file__).resolve().parent.parent
CHANGELOG = RAIZ / "hermes" / "CHANGELOG.md"
WORKFLOW = RAIZ / ".github" / "workflows" / "etiquetar.yml"
URL = "https://github.com/propietario/repo"
# Lo que admite GitHub en el cuerpo de una release.
MAXIMO_GITHUB = 125_000


def _notas_del_changelog(version: str) -> str:
    """Lo mismo que saca el `awk` de `etiquetar.yml`: la sección sin cabecera."""
    salida, dentro = [], False
    for linea in CHANGELOG.read_text(encoding="utf-8").splitlines(keepends=True):
        if linea.startswith("## ["):
            dentro = linea.startswith(f"## [{version}]")
            continue
        if dentro:
            salida.append(linea)
    return "".join(salida)


class TestRecortar(unittest.TestCase):
    def test_las_notas_que_caben_no_se_tocan(self) -> None:
        notas = "### Correcciones\n\n- Algo.\n" * 100
        self.assertEqual(recortar(notas, "9.9.9", URL), notas)

    def test_recorta_y_enlaza_el_changelog(self) -> None:
        notas = "".join(f"- Línea {i} con acentos: áéíóú ñ.\n" for i in range(10_000))
        self.assertGreater(len(notas), LIMITE)
        recortadas = recortar(notas, "9.9.9", URL)
        self.assertLessEqual(len(recortadas), LIMITE)
        self.assertIn(f"({URL}/blob/v9.9.9/hermes/CHANGELOG.md)", recortadas)
        # Se corta en un salto de línea: lo que queda es un prefijo de las
        # notas que termina en línea completa.
        cuerpo = recortadas.split("\n\n---\n\n")[0]
        self.assertTrue(cuerpo.endswith("\n"))
        self.assertTrue(notas.startswith(cuerpo))

    def test_cierra_un_bloque_de_codigo_abierto(self) -> None:
        notas = "Antes\n```yaml\n" + "clave: valor\n" * 20_000 + "```\nDespués\n"
        recortadas = recortar(notas, "9.9.9", URL)
        self.assertLessEqual(len(recortadas), LIMITE)
        vallas = [l for l in recortadas.splitlines() if l.lstrip().startswith("```")]
        self.assertEqual(len(vallas) % 2, 0, "queda un bloque de código abierto")

    def test_una_sola_linea_enorme(self) -> None:
        recortadas = recortar("x" * (LIMITE * 2), "9.9.9", URL)
        self.assertLessEqual(len(recortadas), LIMITE)
        self.assertTrue(recortadas.startswith("x" * 1000))


class TestChangelogReal(unittest.TestCase):
    def test_la_entrada_de_la_1_2_0_cabe(self) -> None:
        notas = _notas_del_changelog("1.2.0")
        # Si algún día deja de pasar del límite, el test sigue valiendo, pero
        # ya no reproduce el fallo de la 1.2.0.
        self.assertGreater(len(notas), MAXIMO_GITHUB, "ya no reproduce el fallo")
        self.assertLessEqual(len(recortar(notas, "1.2.0", URL)), MAXIMO_GITHUB)

    def test_la_entrada_de_la_1_1_2_sale_igual(self) -> None:
        notas = _notas_del_changelog("1.1.2")
        self.assertTrue(notas.strip())
        self.assertEqual(recortar(notas, "1.1.2", URL), notas)


class TestMain(unittest.TestCase):
    def test_reescribe_el_fichero_solo_si_recorta(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            corta = Path(tmp) / "corta.md"
            corta.write_text("- Una línea.\n", encoding="utf-8")
            self.assertEqual(main(["x", str(corta), "9.9.9", URL]), 0)
            self.assertEqual(corta.read_text(encoding="utf-8"), "- Una línea.\n")

            larga = Path(tmp) / "larga.md"
            larga.write_text("- Línea.\n" * 20_000, encoding="utf-8")
            self.assertEqual(main(["x", str(larga), "9.9.9", URL]), 0)
            self.assertLessEqual(len(larga.read_text(encoding="utf-8")), LIMITE)

    def test_sin_argumentos_falla(self) -> None:
        self.assertEqual(main(["x"]), 2)


class TestWorkflow(unittest.TestCase):
    def test_etiquetar_recorta_antes_de_crear_la_release(self) -> None:
        texto = WORKFLOW.read_text(encoding="utf-8")
        recorte = texto.find("scripts/recortar_notas.py /tmp/notas.md")
        creacion = re.search(r"gh release create .*--notes-file /tmp/notas\.md", texto)
        self.assertGreaterEqual(recorte, 0, "etiquetar.yml no recorta las notas")
        self.assertIsNotNone(creacion)
        assert creacion is not None
        self.assertLess(recorte, creacion.start())


if __name__ == "__main__":
    unittest.main()
