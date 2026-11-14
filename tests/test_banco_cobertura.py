"""Invariante de cobertura del banco de Core para los helpers (spec 010, FR-009).

Suite normal (no necesita HA): toda tool que modifica de los 11 dominios de
helpers tiene que estar, o bien probada en el banco contra HA Core real, o
bien en `NO_EJECUTABLES` con su motivo, o bien en `FALLAN_EN_BANCO` con su
hallazgo. Una tool nueva que nadie ejecuta en el banco hace caer este test y
el mensaje la nombra.

Qué es «de escritura» lo dice la anotación `readOnlyHint` del registro de
producción (T045), no el prefijo del nombre: así entra también una escritura
de estos dominios que registre otro módulo.

Que cada tool de `PROBADAS_EN_BANCO` se EJECUTA de verdad no se comprueba
aquí buscando su nombre en los ficheros (T037): lo comprueba en el job el
plugin de `tests/banco/obligatorio.py`, con las tools llamadas con éxito en
tests que han pasado.

Control negativo (T028, anotado en el commit del tramo B): quitar una tool de
`PROBADAS_EN_BANCO` hace caer `test_inventario_exacto` nombrándola; añadir a
`NO_EJECUTABLES` una tool que no existe hace caer el mismo test; dejar vacío el
motivo de una entrada hace caer `test_motivos_no_vacios`.

Control negativo (T038 y T045), comprobado en local y restaurado: devolver
`ha_reload_counters` a `PROBADAS_EN_BANCO` hace caer `test_partes_disjuntas`
y `test_reload_counters_es_hallazgo_y_no_probada`; volver a `raises=AssertionError`
en su xfail hace caer `test_cada_hallazgo_con_su_xfail`; una tool de escritura
`ha_purgar_counters` registrada fuera de `MODULOS_HELPERS` hace caer
`test_inventario_exacto` nombrándola (con la clasificación anterior, por
módulo y prefijo, no entraba).
"""

from __future__ import annotations

import importlib
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from tests.banco.cobertura import (
    DOMINIOS_HELPERS,
    FALLAN_EN_BANCO,
    MODULOS_HELPERS,
    NO_EJECUTABLES,
    PROBADAS_EN_BANCO,
    XFAIL_PERMITIDOS,
)

RAIZ = Path(__file__).resolve().parent.parent


class _DummyMCP:
    """Recoge los nombres de las tools que registra un módulo."""

    def __init__(self) -> None:
        self.nombres: list[str] = []

    def tool(self, *args: object, **kwargs: object):
        def decorador(fn):
            self.nombres.append(fn.__name__)
            return fn

        return decorador


def _de_los_modulos_de_helpers() -> set[str]:
    nombres: set[str] = set()
    for modulo in MODULOS_HELPERS:
        mod = importlib.import_module(f"hermes.tools.{modulo}")
        dummy = _DummyMCP()
        mod.register(dummy, MagicMock())
        nombres.update(dummy.nombres)
    return nombres


def _registro_de_produccion() -> dict[str, Any]:
    from hermes.__main__ import _build_mcp
    from hermes.config import HermesConfig

    # Sin la clasificación automática de `ha_call_service`: al registrarse
    # programa una tarea en el bucle, y este test es síncrono. No cambia qué
    # tools se registran.
    mcp = _build_mcp(HermesConfig(call_service_auto_classify_dangerous=False), MagicMock())
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def _de_estos_dominios(nombre: str, de_los_modulos: set[str]) -> bool:
    # La registre el módulo del dominio o cualquier otro: basta con que el
    # nombre lleve el dominio (`ha_reload_counters`, `ha_set_input_select_options`…).
    return nombre in de_los_modulos or any(d in nombre for d in DOMINIOS_HELPERS)


def _solo_lectura(tool: Any) -> bool:
    return bool(tool.annotations is not None and tool.annotations.read_only_hint)


def _escrituras_de_helpers() -> set[str]:
    """Tools de estos dominios en el registro de producción sin `readOnlyHint`."""
    de_los_modulos = _de_los_modulos_de_helpers()
    return {
        nombre
        for nombre, tool in _registro_de_produccion().items()
        if _de_estos_dominios(nombre, de_los_modulos) and not _solo_lectura(tool)
    }


class TestCoberturaDelBanco(unittest.TestCase):
    def test_once_dominios_y_modulos(self) -> None:
        self.assertEqual(len(DOMINIOS_HELPERS), 11)
        self.assertEqual(len(MODULOS_HELPERS), 11)

    def test_modulos_registrados_en_produccion(self) -> None:
        faltan = _de_los_modulos_de_helpers() - set(_registro_de_produccion())
        self.assertFalse(
            faltan, f"tools de helpers que no están en el registro de producción: {sorted(faltan)}"
        )

    def test_toda_tool_anotada(self) -> None:
        # Sin anotación no se sabría si escribe (`_solo_lectura` la trataría
        # como escritura); mejor que no haya ninguna.
        sin_anotar = sorted(n for n, t in _registro_de_produccion().items() if t.annotations is None)
        self.assertFalse(sin_anotar, f"tools sin anotaciones MCP: {sin_anotar}")

    def test_inventario_exacto(self) -> None:
        reales = _escrituras_de_helpers()
        declaradas = set(PROBADAS_EN_BANCO) | set(NO_EJECUTABLES) | set(FALLAN_EN_BANCO)
        sin_probar = sorted(reales - declaradas)
        inexistentes = sorted(declaradas - reales)
        self.assertFalse(
            sin_probar or inexistentes,
            "inventario del banco desalineado (tests/banco/cobertura.py): "
            "tools de escritura de helpers que no están en PROBADAS_EN_BANCO, "
            f"NO_EJECUTABLES ni FALLAN_EN_BANCO: {sin_probar}; tools declaradas que "
            f"no existen o son de solo lectura: {inexistentes}",
        )
        self.assertEqual(len(reales), 47)

    def test_partes_disjuntas(self) -> None:
        partes = {
            "PROBADAS_EN_BANCO": set(PROBADAS_EN_BANCO),
            "NO_EJECUTABLES": set(NO_EJECUTABLES),
            "FALLAN_EN_BANCO": set(FALLAN_EN_BANCO),
        }
        nombres = list(partes)
        for i, a in enumerate(nombres):
            for b in nombres[i + 1 :]:
                repetidas = sorted(partes[a] & partes[b])
                self.assertFalse(repetidas, f"tools a la vez en {a} y {b}: {repetidas}")

    def test_motivos_no_vacios(self) -> None:
        for nombre, tabla in (("NO_EJECUTABLES", NO_EJECUTABLES), ("FALLAN_EN_BANCO", FALLAN_EN_BANCO)):
            sin_motivo = sorted(t for t, motivo in tabla.items() if not str(motivo).strip())
            self.assertFalse(sin_motivo, f"{nombre} sin motivo: {sin_motivo}")

    def test_cada_hallazgo_con_su_xfail(self) -> None:
        # T038: cada tool de FALLAN_EN_BANCO tiene su xfail en la lista del
        # job, y cada xfail de la lista documenta una tool de FALLAN_EN_BANCO
        # y apunta a un test que existe, estricto y con una excepción concreta.
        self.assertEqual(set(XFAIL_PERMITIDOS.values()), set(FALLAN_EN_BANCO))
        for nodeid in XFAIL_PERMITIDOS:
            ruta, clase, metodo = nodeid.split("::")
            self.assertTrue((RAIZ / ruta).is_file(), nodeid)
            modulo = importlib.import_module(ruta.removesuffix(".py").replace("/", "."))
            prueba = getattr(getattr(modulo, clase), metodo)
            marcas = [m for m in getattr(prueba, "pytestmark", []) if m.name == "xfail"]
            self.assertEqual(len(marcas), 1, nodeid)
            self.assertIs(marcas[0].kwargs.get("strict"), True, nodeid)
            excepcion = marcas[0].kwargs.get("raises")
            self.assertNotIn(excepcion, (None, AssertionError, Exception, BaseException), nodeid)

    def test_reload_counters_es_hallazgo_y_no_probada(self) -> None:
        self.assertNotIn("ha_reload_counters", PROBADAS_EN_BANCO)
        self.assertIn("spec 033", FALLAN_EN_BANCO["ha_reload_counters"])
        self.assertEqual(len(PROBADAS_EN_BANCO), 46)


if __name__ == "__main__":
    unittest.main()
