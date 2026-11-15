"""Invariante de cobertura del banco de Core para los helpers (spec 010, FR-009)
y para las genéricas (spec 011, T027).

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
from unittest.mock import MagicMock, patch

from tests.banco.cobertura import (
    DOMINIOS_HELPERS,
    FALLAN_EN_BANCO,
    FAMILIA_GENERICAS,
    MODULOS_HELPERS,
    NO_EJECUTABLES,
    NO_EJECUTABLES_GENERICAS,
    PROBADAS_EN_BANCO,
    PROBADAS_GENERICAS,
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


def _registro_de_produccion(desactivadas: tuple[str, ...] = ()) -> dict[str, Any]:
    from hermes.__main__ import _build_mcp
    from hermes.config import HermesConfig

    # Sin la clasificación automática de `ha_call_service`: al registrarse
    # programa una tarea en el bucle, y este test es síncrono. No cambia qué
    # tools se registran.
    config = HermesConfig(
        call_service_auto_classify_dangerous=False,
        tool_families_disabled=list(desactivadas),
    )
    mcp = _build_mcp(config, MagicMock())
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


def _escrituras_genericas() -> set[str]:
    """Tools de la familia de las genéricas sin `readOnlyHint`.

    La familia se saca del registro de producción (lo que desaparece al
    apagarla), no de una lista de nombres: una genérica nueva entra sola.
    """
    todas = _registro_de_produccion()
    sin_familia = set(_registro_de_produccion((FAMILIA_GENERICAS,)))
    return {n for n, t in todas.items() if n not in sin_familia and not _solo_lectura(t)}


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

    def test_reload_counters_no_ejecutable_y_no_probada(self) -> None:
        # Spec 033 (FR-004, T029): ya no es un hallazgo (no falla: responde
        # `not_supported` sin llamar a HA), pero tampoco modifica nada que el
        # lector pueda comprobar, así que no cuenta como probada.
        self.assertNotIn("ha_reload_counters", PROBADAS_EN_BANCO)
        self.assertIn("not_supported", NO_EJECUTABLES["ha_reload_counters"])
        self.assertEqual(FALLAN_EN_BANCO, {})
        self.assertEqual(len(PROBADAS_EN_BANCO), 46)

    def test_ningun_xfail_en_el_banco_fuera_de_la_lista(self) -> None:
        """Spec 033 (T036): cada `xfail` que queda en `tests/banco/` está en
        la lista que admite el job, y viceversa. Hoy las dos están vacías: los
        tres hallazgos (el de la 010 y los dos de la 028) están arreglados.

        El plugin del job ya pone el job en rojo con un `xfail` de más; esto
        lo dice antes, en la suite normal, sin HA.

        Control negativo, comprobado y restaurado: volviendo a poner el
        `xfail` de `TestCounter.test_recarga`, este test cae nombrándolo.
        """
        import ast

        from tests.banco.cobertura_escrituras import XFAIL_DEL_JOB

        marcados: set[str] = set()
        for ruta in sorted((RAIZ / "tests" / "banco").glob("test_*.py")):
            arbol = ast.parse(ruta.read_text(encoding="utf-8"))
            for clase in (n for n in arbol.body if isinstance(n, ast.ClassDef)):
                for metodo in clase.body:
                    if not isinstance(metodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if any("xfail" in ast.unparse(d) for d in metodo.decorator_list):
                        marcados.add(
                            f"tests/banco/{ruta.name}::{clase.name}::{metodo.name}"
                        )
        self.assertEqual(marcados, set(XFAIL_DEL_JOB))
        self.assertEqual(XFAIL_DEL_JOB, {})



class TestCoberturaDeLasGenericas(unittest.TestCase):
    """Spec 011, T027: las genéricas de escritura, probadas en el banco o con motivo.

    Control negativo (T027), comprobado en local y restaurado: sacar
    `ha_call_ws_command` de `PROBADAS_GENERICAS` hace caer
    `test_inventario_exacto` nombrándola; ponerla también en
    `NO_EJECUTABLES_GENERICAS` hace caer `test_partes_disjuntas`; pasar al
    plugin del job solo `PROBADAS_EN_BANCO` hace caer
    `test_el_job_exige_las_probadas`.
    """

    def test_inventario_exacto(self) -> None:
        reales = _escrituras_genericas()
        declaradas = set(PROBADAS_GENERICAS) | set(NO_EJECUTABLES_GENERICAS)
        self.assertEqual(
            reales,
            declaradas,
            "inventario de las genéricas desalineado (tests/banco/cobertura.py): "
            f"de escritura sin declarar {sorted(reales - declaradas)}; declaradas "
            f"que no existen o son de solo lectura {sorted(declaradas - reales)}",
        )
        self.assertEqual(reales, {"ha_call_ws_command", "sv_call_api"})

    def test_partes_disjuntas(self) -> None:
        repetidas = sorted(set(PROBADAS_GENERICAS) & set(NO_EJECUTABLES_GENERICAS))
        self.assertFalse(repetidas, f"genéricas probadas y no ejecutables a la vez: {repetidas}")

    def test_motivos(self) -> None:
        self.assertEqual(
            NO_EJECUTABLES_GENERICAS["sv_call_api"],
            "Supervisor simulado; se prueba en la VM (spec 014)",
        )
        for tool, motivo in NO_EJECUTABLES_GENERICAS.items():
            self.assertTrue(str(motivo).strip(), tool)

    def test_el_job_exige_las_probadas(self) -> None:
        # El conftest del banco pasa al plugin del job las de los helpers y
        # las de las genéricas: si no, `ha_call_ws_command` quedaría «probada»
        # solo de nombre. Se registra el plugin como en el job y se mira qué
        # tools exige.
        from tests.banco import conftest
        from tests.banco.obligatorio import ComprobacionDelJob

        config = MagicMock()
        with patch.object(conftest.entorno, "_obligatorio", return_value=True):
            conftest.pytest_configure(config)
        plugin = config.pluginmanager.register.call_args.args[0]
        self.assertIsInstance(plugin, ComprobacionDelJob)
        # Desde la integración de la 028, la unión de las listas (y desde la
        # 012, también la suya).
        from tests.banco.cobertura_012 import PROBADAS_012
        from tests.banco.cobertura_020 import LECTURAS_020, PROBADAS_020
        from tests.banco.cobertura_escrituras import PROBADAS_028

        # Desde la 029, también sus lecturas.
        from tests.banco.cobertura import PROBADAS_EN_BANCO_029

        self.assertEqual(
            plugin.tools_exigidas,
            PROBADAS_EN_BANCO | PROBADAS_GENERICAS | PROBADAS_028 | PROBADAS_EN_BANCO_029
            | PROBADAS_012 | PROBADAS_020 | LECTURAS_020,
        )


if __name__ == "__main__":
    unittest.main()


class TestCoberturaDeLa029(unittest.TestCase):
    """Spec 029, T017 (FR-022): las tools de las familias de la 029 se
    ejecutan en el banco. `PROBADAS_EN_BANCO_029` es EXACTAMENTE lo que
    registran sus módulos (una tool nueva en ellos sin prueba en el banco hace
    caer el test nombrándola) y cada nombre aparece en algún
    `tests/banco/test_banco_*.py`. Que se ejecuta de verdad lo exige el job
    (`TOOLS_EXIGIDAS_DEL_JOB`).

    Controles negativos: quitar `ha_get_system_state` (T018 f) o
    `ha_get_recorder_info` (T034 g) de `PROBADAS_EN_BANCO_029` → cae
    `test_inventario_exacto` nombrándola."""

    def test_inventario_exacto(self) -> None:
        from tests.banco.cobertura import MODULOS_029, PROBADAS_EN_BANCO_029

        registradas: set[str] = set()
        for modulo in MODULOS_029:
            mod = importlib.import_module(f"hermes.tools.{modulo}")
            dummy = _DummyMCP()
            mod.register(dummy, MagicMock(), response_max_bytes=131_072)
            registradas.update(dummy.nombres)
        self.assertEqual(
            set(PROBADAS_EN_BANCO_029), registradas,
            f"sin probar en el banco: {sorted(registradas - PROBADAS_EN_BANCO_029)}; "
            f"declaradas que no registra ningún módulo de la 029: "
            f"{sorted(PROBADAS_EN_BANCO_029 - registradas)}")

    def test_modulos_de_las_familias_de_la_029(self) -> None:
        from hermes.tool_families import FAMILIAS
        from tests.banco.cobertura import MODULOS_029
        from tests.banco.cobertura_020 import MODULOS_020

        # T031: los módulos de las dos familias de la 029. La 020 añade
        # `statistics_maintenance` a `recorder`; sus tools se inventarían en
        # `cobertura_020.py`, así que sus módulos se restan aquí.
        self.assertEqual(
            set(MODULOS_029),
            (set(FAMILIAS["system_status"].modulos) | set(FAMILIAS["recorder"].modulos))
            - set(MODULOS_020))

    def test_cada_una_en_un_fichero_del_banco(self) -> None:
        from tests.banco.cobertura import PROBADAS_EN_BANCO_029

        textos = "\n".join(
            p.read_text(encoding="utf-8")
            for p in sorted((RAIZ / "tests" / "banco").glob("test_banco_*.py")))
        faltan = sorted(t for t in PROBADAS_EN_BANCO_029 if f'"{t}"' not in textos)
        self.assertEqual(faltan, [], f"sin test en tests/banco/: {faltan}")


class TestCoberturaDeLa020(unittest.TestCase):
    """Spec 020, T048 (FR-021, SC-005): `PROBADAS_020` (escrituras) y
    `LECTURAS_020` son EXACTAMENTE lo que registran `MODULOS_020`, y cada
    nombre aparece en algún `tests/banco/test_banco_*.py`. Que se ejecutan de
    verdad lo exige el job (`TOOLS_EXIGIDAS_DEL_JOB`).

    Control negativo (T050 f): quitar `ha_get_energy_prefs` de
    `LECTURAS_020` → cae `test_inventario_exacto` nombrándola."""

    def test_inventario_exacto(self) -> None:
        from tests.banco.cobertura_020 import LECTURAS_020, MODULOS_020, PROBADAS_020

        registradas: set[str] = set()
        for modulo in MODULOS_020:
            mod = importlib.import_module(f"hermes.tools.{modulo}")
            dummy = _DummyMCP()
            mod.register(dummy, MagicMock(), response_max_bytes=131_072)
            registradas.update(dummy.nombres)
        declaradas = set(PROBADAS_020) | set(LECTURAS_020)
        self.assertEqual(
            declaradas, registradas,
            f"sin probar en el banco: {sorted(registradas - declaradas)}; "
            f"declaradas que no registra ningún módulo de la 020: "
            f"{sorted(declaradas - registradas)}")
        self.assertFalse(set(PROBADAS_020) & set(LECTURAS_020))

    def test_modulos_de_la_020(self) -> None:
        from hermes.tool_families import FAMILIAS
        from tests.banco.cobertura_020 import MODULOS_020

        self.assertEqual(set(MODULOS_020),
                         {"statistics_maintenance"} | set(FAMILIAS["energy"].modulos))

    def test_cada_una_en_un_fichero_del_banco(self) -> None:
        from tests.banco.cobertura_020 import LECTURAS_020, PROBADAS_020

        textos = "\n".join(
            p.read_text(encoding="utf-8")
            for p in sorted((RAIZ / "tests" / "banco").glob("test_banco_*.py")))
        faltan = sorted(t for t in PROBADAS_020 | LECTURAS_020
                        if f'"{t}"' not in textos)
        self.assertEqual(faltan, [], f"sin test en tests/banco/: {faltan}")
