"""Invariante de las escrituras en el banco de Core (spec 028, FR-003, FR-004).

Suite normal (no necesita HA): TODA tool que modifica del registro de
producción está en una de estas listas, sin solaparse: probada en el banco por
la 010 (helpers), probada en el banco por la 028, no ejecutable con su motivo,
o fuera del banco (`fs_*` y `sv_*`) con su motivo. Una tool nueva que modifica
y no está en ninguna hace caer `test_todas_las_escrituras_clasificadas`, que la
nombra. Contrato: `specs/028-pruebas-escrituras-core/contracts/`.

Control negativo (T008, anotado en el commit del tramo A): quitar
`ha_fire_event` de `PROBADAS_028` hace caer
`test_todas_las_escrituras_clasificadas` nombrándola; moverla a
`FUERA_DEL_BANCO` hace caer `test_fuera_del_banco_solo_fs_y_sv`; vaciar el
motivo de `sv_reboot_host` hace caer `test_motivos_no_vacios`; poner
`ha_get_state` en `PROBADAS_028` hace caer el primero («declaradas que no
modifican»).

Control negativo del cierre (T022, tramo B): quitar `ha_ignore_repair` de
`PROBADAS_028` hace caer `test_todas_las_escrituras_clasificadas`
nombrándola (y `test_recuento_028`: 52); dejarla en la lista y quitar su
nombre literal del test del banco hace caer
`test_cada_probada_aparece_en_un_test_del_banco`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from tests.banco import cobertura, cobertura_escrituras as c028

CARPETA_BANCO = Path(__file__).resolve().parent / "banco"


def _modifican() -> set[str]:
    """Tools del registro de producción sin `readOnlyHint` (research R-0)."""
    from hermes.__main__ import _build_mcp
    from hermes.config import HermesConfig
    from hermes.tools._annotations import classify

    # Sin la clasificación automática de `ha_call_service`: al registrarse
    # programa una tarea en el bucle, y este test es síncrono. No cambia qué
    # tools se registran (igual que en la 010).
    mcp = _build_mcp(HermesConfig(call_service_auto_classify_dangerous=False), MagicMock())
    return {
        t.name for t in mcp._tool_manager.list_tools() if not classify(t.name).read_only_hint
    }


def _listas() -> dict[str, set[str]]:
    """Cada lista del inventario con su nombre, para los mensajes de fallo."""
    return {
        "cobertura.PROBADAS_EN_BANCO (010)": set(cobertura.PROBADAS_EN_BANCO),
        "cobertura.NO_EJECUTABLES (010)": set(cobertura.NO_EJECUTABLES),
        "PROBADAS_028": set(c028.PROBADAS_028),
        "NO_EJECUTABLES_028": set(c028.NO_EJECUTABLES_028),
        "FUERA_DEL_BANCO": set(c028.FUERA_DEL_BANCO),
    }


class TestInventarioDeEscrituras(unittest.TestCase):
    def test_todas_las_escrituras_clasificadas(self) -> None:
        reales = _modifican()
        declaradas: set[str] = set().union(*_listas().values())
        sin_clasificar = sorted(reales - declaradas)
        no_modifican = sorted(declaradas - reales)
        self.assertFalse(
            sin_clasificar or no_modifican,
            "inventario de escrituras desalineado (tests/banco/cobertura_escrituras.py "
            "o el módulo de cobertura de su sub-feature): tools que modifican sin "
            f"clasificar: {sin_clasificar}; declaradas que no modifican o no existen: "
            f"{no_modifican}",
        )
        self.assertEqual(len(reales), 124)

    def test_listas_disjuntas(self) -> None:
        listas = _listas()
        nombres = list(listas)
        repetidas = []
        for i, a in enumerate(nombres):
            for b in nombres[i + 1:]:
                comunes = sorted(listas[a] & listas[b])
                if comunes:
                    repetidas.append(f"{comunes} en {a} y {b}")
        self.assertFalse(repetidas, f"tools en dos listas a la vez: {repetidas}")

    def test_fuera_del_banco_solo_fs_y_sv(self) -> None:
        otras = sorted(t for t in c028.FUERA_DEL_BANCO if not t.startswith(("fs_", "sv_")))
        self.assertFalse(
            otras,
            "FUERA_DEL_BANCO solo admite fs_* y sv_*; una ha_* que no se pueda "
            f"ejecutar va a NO_EJECUTABLES_028 con un motivo concreto: {otras}",
        )

    def test_motivos_no_vacios(self) -> None:
        sin_motivo = sorted(
            f"{nombre}: {tool}"
            for nombre, lista in (
                ("NO_EJECUTABLES_028", c028.NO_EJECUTABLES_028),
                ("FUERA_DEL_BANCO", c028.FUERA_DEL_BANCO),
            )
            for tool, motivo in lista.items()
            if not str(motivo).strip()
        )
        self.assertFalse(sin_motivo, f"tools sin motivo: {sin_motivo}")

    def test_recuento_028(self) -> None:
        total = len(c028.PROBADAS_028) + len(c028.NO_EJECUTABLES_028)
        self.assertEqual(total, 53, f"las listas de la 028 suman {total}, no 53")
        self.assertEqual(len(c028.FUERA_DEL_BANCO), 24)

    def test_cada_probada_aparece_en_un_test_del_banco(self) -> None:
        textos = "\n".join(
            p.read_text(encoding="utf-8")
            for p in sorted(CARPETA_BANCO.glob("test_banco_escrituras_*.py"))
        )
        self.assertTrue(textos, "no hay ficheros tests/banco/test_banco_escrituras_*.py")
        ausentes = sorted(t for t in c028.PROBADAS_028 if f'"{t}"' not in textos)
        self.assertFalse(
            ausentes, f"tools de PROBADAS_028 que ningún test del banco llama: {ausentes}"
        )


if __name__ == "__main__":
    unittest.main()
