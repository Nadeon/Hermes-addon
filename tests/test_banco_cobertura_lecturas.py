"""Invariante de las LECTURAS nuevas de Core en el banco (T031 de la 008, SC-006).

Suite normal (no necesita HA): toda `ha_*` con `readOnlyHint` de una familia
de la 1.2.0 la exige el job del banco por EJECUCIÓN (está en
`TOOLS_EXIGIDAS_DEL_JOB`, que pasa a `tests/banco/obligatorio.py`) o está en
`NO_EJECUTABLES_LECTURAS` con su motivo concreto. Una lectura nueva que no
esté en ninguna hace caer `test_todas_las_lecturas_nuevas_exigidas`, que la
nombra. El inventario: `tests/banco/cobertura_lecturas.py`.

Control negativo (comprobado): quitar `ha_list_blueprints` de
`LECTURAS_EN_BANCO` hace caer `test_todas_las_lecturas_nuevas_exigidas`
nombrándola (y `test_recuento`); ponerla también en
`NO_EJECUTABLES_LECTURAS` hace caer `test_disjuntas`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from tests.banco import cobertura_lecturas as cl
from tests.banco.cobertura_escrituras import TOOLS_EXIGIDAS_DEL_JOB

RAIZ = Path(__file__).resolve().parent.parent


def _lecturas_nuevas_de_core() -> set[str]:
    """`ha_*` del registro de producción con `readOnlyHint`, de una familia
    de la 1.2.0 (las de la 1.1.2 no cambian: SC-005)."""
    from hermes.__main__ import _build_mcp
    from hermes.config import HermesConfig
    from hermes.tool_families import FAMILIAS, familia_de_modulo
    from hermes.tools._annotations import classify

    # Sin la clasificación automática de `ha_call_service`, como en la 028:
    # programa una tarea en el bucle y este test es síncrono.
    mcp = _build_mcp(HermesConfig(call_service_auto_classify_dangerous=False), MagicMock())
    return {
        t.name for t in mcp._tool_manager.list_tools()
        if t.name.startswith("ha_")
        and classify(t.name).read_only_hint
        and FAMILIAS[familia_de_modulo(t.fn.__module__.rsplit(".", 1)[-1])].desde == "1.2.0"
    }


class TestInventarioDeLecturas(unittest.TestCase):
    def test_todas_las_lecturas_nuevas_exigidas(self) -> None:
        reales = _lecturas_nuevas_de_core()
        cubiertas = set(TOOLS_EXIGIDAS_DEL_JOB) | set(cl.NO_EJECUTABLES_LECTURAS)
        self.assertEqual(
            sorted(reales - cubiertas), [],
            "lecturas nuevas de Core que el job del banco no exige por ejecución "
            "ni están en NO_EJECUTABLES_LECTURAS (tests/banco/cobertura_lecturas.py)",
        )
        # Lo declarado aquí son lecturas nuevas de Core de verdad.
        declaradas = set(cl.LECTURAS_EN_BANCO) | set(cl.NO_EJECUTABLES_LECTURAS)
        self.assertEqual(sorted(declaradas - reales), [])

    def test_disjuntas(self) -> None:
        self.assertEqual(sorted(set(TOOLS_EXIGIDAS_DEL_JOB) & set(cl.NO_EJECUTABLES_LECTURAS)),
                         [])

    def test_motivos_concretos(self) -> None:
        for tool, motivo in cl.NO_EJECUTABLES_LECTURAS.items():
            self.assertGreater(len(motivo.strip()), 40, tool)

    def test_el_job_las_exige(self) -> None:
        self.assertLessEqual(set(cl.LECTURAS_EN_BANCO), set(TOOLS_EXIGIDAS_DEL_JOB))

    def test_cada_una_se_llama_en_su_fichero(self) -> None:
        # Comprobación textual de apoyo (la que vale es la de ejecución del
        # job): el fichero que dice el inventario existe y nombra la tool.
        for tool, fichero in cl._DONDE.items():
            with self.subTest(tool=tool):
                texto = (RAIZ / "tests" / "banco" / fichero).read_text(encoding="utf-8")
                self.assertIn(f'"{tool}"', texto)

    def test_recuento(self) -> None:
        # 45 lecturas nuevas de Core: 18 que ya exigían sus sub-features (020,
        # 021, 023, 024, 029 y 031), las 26 de `LECTURAS_EN_BANCO` y 1 no
        # ejecutable. Si cambia, que sea a propósito.
        reales = _lecturas_nuevas_de_core()
        self.assertEqual(len(reales), 45)
        self.assertEqual(len(cl.LECTURAS_EN_BANCO), 26)
        self.assertEqual(len(cl.NO_EJECUTABLES_LECTURAS), 1)


if __name__ == "__main__":
    unittest.main()
