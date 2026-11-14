"""Catálogo de familias de tools (spec 011, FR-019, T005).

Las familias agrupan los módulos de `hermes/tools/` para poder desactivarlas
con `tool_families_disabled`. Si un módulo con tools no estuviera en ninguna
familia, sus tools no se podrían desactivar (y el registro por familias del
tramo 3 las perdería); si estuviera en dos, desactivar una de ellas no las
quitaría. Por eso se comprueba por AST, como `test_tools_registration`, sobre
los módulos que declaran `@mcp.tool()` de verdad.

Control negativo (T005/T016 g): sacar `scenes` de `automations` → falla
`test_cada_modulo_con_tools_en_una_familia` nombrándolo; ponerlo además en
`helpers` → falla igual («en 2 familias»); dejar que `validar_desactivadas`
acepte `base` → falla `test_base_no_se_puede_desactivar`.
"""

from __future__ import annotations

import ast
import pathlib
import re
import unittest

from hermes import tool_families
from hermes.tool_families import FAMILIAS, familia_de_modulo, validar_desactivadas

_TOOLS_DIR = (
    pathlib.Path(__file__).resolve().parents[1] / "hermes" / "src" / "hermes" / "tools"
)

# Módulos que una familia puede nombrar aunque todavía no existan en disco.
# `generic_commands` lo crea el tramo 2 (T024); T025 quita esta excepción para
# que, desde entonces, una familia que nombre un módulo inexistente falle.
_MODULOS_AUN_NO_CREADOS = {"generic_commands"}

# Catálogo de la 1.1.2 (research R-5): familia → módulos.
_CATALOGO_1_1_2 = {
    "base": {"ping", "guide"},
    "services": {"ha"},
    "automations": {"automations", "scripts", "scenes"},
    "helpers": {
        "input_boolean", "input_button", "input_datetime", "input_number",
        "input_select", "input_text", "counter", "timer", "schedule", "zones",
        "persons",
    },
    "events": {"events", "wait_for_event"},
    "data": {"templates", "history", "logbook", "statistics"},
    "registries": {
        "registry_area", "registry_category", "registry_device",
        "registry_entity", "registry_floor", "registry_label",
    },
    "diagnostics": {"repairs", "traces", "search", "resolution"},
    "config_entries": {"config_entries", "config_entry_flows"},
    "filesystem": {"filesystem", "filesystem_write"},
    "supervisor": {"addons", "supervisor"},
    "backups": {"backups", "ha_backups"},
    "lovelace": {"lovelace"},
    "marketplace": {"marketplace", "hacs"},
}


def _es_tool(deco: ast.expr) -> bool:
    return (
        isinstance(deco, ast.Call)
        and getattr(getattr(deco, "func", None), "attr", "") == "tool"
    ) or (isinstance(deco, ast.Attribute) and deco.attr == "tool")


def _tools_por_modulo() -> dict[str, list[str]]:
    """Módulo de `hermes/tools/` → nombres de sus funciones `@mcp.tool()`."""
    out: dict[str, list[str]] = {}
    for path in sorted(_TOOLS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        nombres = [
            n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(_es_tool(d) for d in n.decorator_list)
        ]
        if nombres:
            out[path.stem] = nombres
    return out


class TestCatalogo(unittest.TestCase):
    def test_cada_modulo_con_tools_en_una_familia(self) -> None:
        problemas = []
        for modulo in sorted(_tools_por_modulo()):
            familias = [f.nombre for f in FAMILIAS.values() if modulo in f.modulos]
            if len(familias) != 1:
                problemas.append(f"{modulo}: en {len(familias)} familias {familias}")
        self.assertEqual(problemas, [], "\n".join(problemas))

    def test_cada_familia_nombra_modulos_que_existen(self) -> None:
        existentes = {p.stem for p in _TOOLS_DIR.glob("*.py")}
        faltan = sorted(
            f"{f.nombre}: {m}" for f in FAMILIAS.values() for m in f.modulos
            if m not in existentes and m not in _MODULOS_AUN_NO_CREADOS
        )
        self.assertEqual(faltan, [], f"módulos inexistentes: {faltan}")

    def test_ningun_modulo_en_dos_familias(self) -> None:
        todos = [m for f in FAMILIAS.values() for m in f.modulos]
        repetidos = sorted({m for m in todos if todos.count(m) > 1})
        self.assertEqual(repetidos, [])

    def test_nombres_unicos_y_con_forma(self) -> None:
        for clave, familia in FAMILIAS.items():
            self.assertEqual(clave, familia.nombre)
            self.assertRegex(familia.nombre, r"^[a-z][a-z0-9_]*$")
            self.assertTrue(familia.descripcion.strip(), familia.nombre)
            self.assertIn(familia.desde, {"1.1.2", "1.2.0"}, familia.nombre)

    def test_base_contiene_ping_y_guide_y_es_la_unica_fija(self) -> None:
        self.assertIn("base", FAMILIAS)
        self.assertLessEqual({"ping", "guide"}, set(FAMILIAS["base"].modulos))
        fijas = sorted(f.nombre for f in FAMILIAS.values() if not f.desactivable)
        self.assertEqual(fijas, ["base"])

    def test_familias_de_la_1_1_2(self) -> None:
        de_1_1_2 = {
            f.nombre: set(f.modulos) for f in FAMILIAS.values() if f.desde == "1.1.2"
        }
        self.assertEqual(de_1_1_2, _CATALOGO_1_1_2)

    def test_las_familias_de_la_1_1_2_suman_las_216_tools(self) -> None:
        por_modulo = _tools_por_modulo()
        nombres = {
            t for f in FAMILIAS.values() if f.desde == "1.1.2"
            for m in f.modulos for t in por_modulo.get(m, [])
        }
        # `test_progress` solo se registra con HERMES_DEV: no es de las 216.
        nombres.discard("test_progress")
        self.assertEqual(len(nombres), 216)

    def test_generic_commands_es_de_la_1_2_0(self) -> None:
        familia = FAMILIAS["generic_commands"]
        self.assertEqual(familia.desde, "1.2.0")
        self.assertTrue(familia.desactivable)
        self.assertEqual(familia.modulos, ("generic_commands",))

    def test_familia_de_modulo(self) -> None:
        self.assertEqual(familia_de_modulo("scenes"), "automations")
        self.assertEqual(familia_de_modulo("guide"), "base")
        self.assertEqual(familia_de_modulo("generic_commands"), "generic_commands")
        with self.assertRaises(KeyError):
            familia_de_modulo("no_existe")

    def test_neutral_no_importa_nada_de_hermes(self) -> None:
        # Lo importa config.py: si importara tools/ habría ciclos.
        arbol = ast.parse(pathlib.Path(tool_families.__file__).read_text(encoding="utf-8"))
        importados: list[str] = []
        for n in ast.walk(arbol):
            if isinstance(n, ast.Import):
                importados += [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                importados.append("." * n.level + (n.module or ""))
        self.assertEqual([m for m in importados if m.startswith(("hermes", "."))], [])


class TestValidarDesactivadas(unittest.TestCase):
    def test_vacia(self) -> None:
        self.assertEqual(validar_desactivadas([]), frozenset())

    def test_validas_y_duplicados(self) -> None:
        self.assertEqual(
            validar_desactivadas(["lovelace", "marketplace", "lovelace"]),
            frozenset({"lovelace", "marketplace"}),
        )

    def test_nombre_desconocido(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            validar_desactivadas(["lovelace", "familia_inventada"])
        msg = str(ctx.exception)
        self.assertIn("familia_inventada", msg)
        # Nombra las válidas para que el usuario corrija sin leer el código.
        self.assertIn("lovelace", msg)
        self.assertIn("generic_commands", msg)

    def test_base_no_se_puede_desactivar(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            validar_desactivadas(["base"])
        self.assertIn("base", str(ctx.exception))

    def test_forma_invalida(self) -> None:
        with self.assertRaises(ValueError):
            validar_desactivadas(["Lovelace"])


if __name__ == "__main__":
    unittest.main()
