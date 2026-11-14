"""Invariante de cobertura del banco de Core para los helpers (spec 010, FR-009).

Suite normal (no necesita HA): toda tool que modifica de los 11 dominios de
helpers tiene que estar, o bien probada en el banco contra HA Core real, o bien
en `NO_EJECUTABLES` con su motivo. Una tool nueva que nadie ejecuta en el banco
hace caer este test y el mensaje la nombra.

Control negativo (T028, anotado en el commit del tramo B): quitar una tool de
`PROBADAS_EN_BANCO` hace caer `test_inventario_exacto` nombrándola; añadir a
`NO_EJECUTABLES` una tool que no existe hace caer el mismo test; dejar vacío el
motivo de una entrada hace caer `test_motivos_no_vacios`.
"""

from __future__ import annotations

import importlib
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from tests.banco.cobertura import (
    DOMINIOS_HELPERS,
    MODULOS_HELPERS,
    NO_EJECUTABLES,
    PROBADAS_EN_BANCO,
)

CARPETA_BANCO = Path(__file__).resolve().parent / "banco"


class _DummyMCP:
    """Recoge los nombres de las tools que registra un módulo."""

    def __init__(self) -> None:
        self.nombres: list[str] = []

    def tool(self, *args: object, **kwargs: object):
        def decorador(fn):
            self.nombres.append(fn.__name__)
            return fn

        return decorador


def _escrituras_de_helpers() -> set[str]:
    """Tools de los módulos de helpers que no son `ha_list_*` ni `ha_get_*`."""
    nombres: set[str] = set()
    for modulo in MODULOS_HELPERS:
        mod = importlib.import_module(f"hermes.tools.{modulo}")
        dummy = _DummyMCP()
        mod.register(dummy, MagicMock())
        nombres.update(dummy.nombres)
    return {n for n in nombres if not n.startswith(("ha_list_", "ha_get_"))}


def _registro_de_produccion() -> set[str]:
    from hermes.__main__ import _build_mcp
    from hermes.config import HermesConfig

    # Sin la clasificación automática de `ha_call_service`: al registrarse
    # programa una tarea en el bucle, y este test es síncrono. No cambia qué
    # tools se registran.
    mcp = _build_mcp(HermesConfig(call_service_auto_classify_dangerous=False), MagicMock())
    return {t.name for t in mcp._tool_manager.list_tools()}


class TestCoberturaDelBanco(unittest.TestCase):
    def test_once_dominios_y_modulos(self) -> None:
        self.assertEqual(len(DOMINIOS_HELPERS), 11)
        self.assertEqual(len(MODULOS_HELPERS), 11)

    def test_escrituras_registradas_en_produccion(self) -> None:
        faltan = _escrituras_de_helpers() - _registro_de_produccion()
        self.assertFalse(
            faltan, f"tools de helpers que no están en el registro de producción: {sorted(faltan)}"
        )

    def test_inventario_exacto(self) -> None:
        reales = _escrituras_de_helpers()
        declaradas = set(PROBADAS_EN_BANCO) | set(NO_EJECUTABLES)
        sin_probar = sorted(reales - declaradas)
        inexistentes = sorted(declaradas - reales)
        self.assertFalse(
            sin_probar or inexistentes,
            "inventario del banco desalineado (tests/banco/cobertura.py): "
            f"tools de helpers sin probar en el banco ni en NO_EJECUTABLES: {sin_probar}; "
            f"tools declaradas que no existen: {inexistentes}",
        )
        self.assertEqual(len(reales), 47)

    def test_partes_disjuntas(self) -> None:
        repetidas = sorted(set(PROBADAS_EN_BANCO) & set(NO_EJECUTABLES))
        self.assertFalse(
            repetidas, f"tools a la vez probadas y no ejecutables: {repetidas}"
        )

    def test_motivos_no_vacios(self) -> None:
        sin_motivo = sorted(
            t for t, motivo in NO_EJECUTABLES.items() if not str(motivo).strip()
        )
        self.assertFalse(sin_motivo, f"NO_EJECUTABLES sin motivo: {sin_motivo}")

    def test_cada_probada_aparece_en_un_test_del_banco(self) -> None:
        textos = "\n".join(
            p.read_text(encoding="utf-8")
            for p in sorted(CARPETA_BANCO.glob("test_banco_helpers_*.py"))
        )
        self.assertTrue(textos, "no hay ficheros tests/banco/test_banco_helpers_*.py")
        ausentes = sorted(t for t in PROBADAS_EN_BANCO if f'"{t}"' not in textos)
        self.assertFalse(
            ausentes,
            f"tools de PROBADAS_EN_BANCO que ningún test del banco llama: {ausentes}",
        )
