"""Cierre del programa de cobertura total (spec 008, FR-098, T026).

Lo que el converge del programa comprobó a mano queda vigilado aquí, para que
un cambio posterior no lo deshaga en silencio:

- **la tabla, cerrada**: ninguna entrada con motivo «pendiente de tool
  dedicada», «pendiente de revisión», «sin revisar» ni «provisional»
  (FR-098, S-02). Los tests de cada sub-feature miran solo su «(spec NNN)»
  y `test_clase_a_de_via_dedicada_pendiente_de_su_spec` sigue admitiendo un
  «pendiente» válido; este es el único que lo prohíbe en toda la tabla;
- **la matriz de trazabilidad de `plan.md`, completa y verdadera**: cada CAP
  del catálogo de research tiene su fila con sub-feature, FR, vía y test, y
  todo lo que la fila cita existe: cada tool (`ha_*`, `sv_*`, `fs_*`) está
  registrada, cada fichero de test existe y cada clase o función de test que
  nombra está definida en `tests/`. Las únicas excepciones son nombres que la
  propia fila declara inexistentes (desviaciones aceptadas), con su motivo.

Control negativo (T026 de la 008), comprobado: con `ha_list_users` cambiado
por `ha_list_userz` en la fila CAP-056 de plan.md cae
`test_cada_tool_citada_existe` nombrándola; con un `deny` «pendiente de tool
dedicada (spec 021)» en `auth/refresh_tokens` cae
`test_ninguna_pendiente_ni_sin_revisar`; quitando la fila CAP-058 cae
`test_cada_cap_tiene_su_fila`.
"""

from __future__ import annotations

import ast
import pathlib
import re
import unittest

from hermes import command_table as ct

_RAIZ = pathlib.Path(__file__).resolve().parents[1]
_SPEC = _RAIZ / "specs" / "008-cobertura-total"

# Motivos que no pueden quedar en la tabla al cerrar el programa.
_MOTIVOS_ABIERTOS = (
    "pendiente de tool dedicada",
    "pendiente de revisión",
    "sin revisar",
    "provisional",
)

# Nombres con forma de tool que una fila de la matriz cita sin ser una tool
# registrada. Cada uno con su porqué; si la fila deja de citarlo, sobra.
_CITADOS_QUE_NO_SON_TOOLS: dict[tuple[str, str], str] = {
    ("CAP-027", "fs_write"):
        "es el módulo de las escrituras en /config (su safety backup "
        "automático), no una tool",
    ("CAP-075", "ha_marketplace_install"):
        "desviación de FR-091 (DV-1 de la 026): la fila dice que no existe",
    ("CAP-075", "ha_marketplace_set_version"):
        "desviación de FR-091 (DV-1 de la 026): la fila dice que no existe",
    ("CAP-075", "ha_marketplace_set_beta"):
        "desviación de FR-091 (DV-1 de la 026): la fila dice que no existe",
    ("CAP-075", "ha_marketplace_add_repository"):
        "desviación de FR-091 (DV-1 de la 026): la fila dice que no existe",
}

_VIAS = {"D", "T", "D+T", "D+X", "X", "X+M", "M"}


def _catalogo() -> set[str]:
    """Las CAP de research.md: viñetas `- **CAP-NNN — …**` y filas de tabla."""
    texto = (_SPEC / "research.md").read_text(encoding="utf-8")
    return set(re.findall(r"^(?:- \*\*|\| )(CAP-\d{3})\b", texto, re.M))


def _filas() -> dict[str, list[str]]:
    """Filas de la matriz de plan.md: CAP → [prio, sub-feature, FR, vía, test]."""
    texto = (_SPEC / "plan.md").read_text(encoding="utf-8")
    filas: dict[str, list[str]] = {}
    for cap, resto in re.findall(r"^\| (CAP-\d{3}) \|(.*)\|\s*$", texto, re.M):
        filas[cap] = [c.strip() for c in resto.split(" | ")]
    return filas


def _definidos_en_tests() -> set[str]:
    nombres: set[str] = set()
    for p in (_RAIZ / "tests").rglob("*.py"):
        arbol = ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(arbol):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nombres.add(n.name)
    return nombres


def _registro() -> set[str]:
    from tests.test_tools_registration import _real_registry

    return set(_real_registry())


class TestTablaCerrada(unittest.TestCase):
    def test_ninguna_pendiente_ni_sin_revisar(self) -> None:
        abiertas = sorted(
            f"{k}: {e.reason}"
            for tabla in (ct.CORE_WS, ct.SUPERVISOR)
            for k, e in tabla.items()
            if any(m in e.reason.lower() for m in _MOTIVOS_ABIERTOS)
        )
        self.assertEqual(abiertas, [], "\n".join(abiertas))


class TestMatrizDeTrazabilidad(unittest.TestCase):
    def test_cada_cap_tiene_su_fila(self) -> None:
        catalogo = _catalogo()
        filas = _filas()
        # 96 CAP (spec 008, «Entrada»); si el catálogo no se leyera, el test
        # no probaría nada.
        self.assertEqual(len(catalogo), 96)
        self.assertEqual(
            (sorted(catalogo - set(filas)), sorted(set(filas) - catalogo)), ([], []),
            "CAP sin fila en la matriz / filas sin CAP en el catálogo")

    def test_cada_fila_completa(self) -> None:
        malas = []
        for cap, celdas in _filas().items():
            if len(celdas) != 5:
                malas.append(f"{cap}: {len(celdas)} columnas")
                continue
            _prio, sub, fr, via, test = celdas
            if not re.fullmatch(r"\d{3}(, \d{3})*", sub):
                malas.append(f"{cap}: sub-feature {sub!r}")
            if not re.search(r"FR-\d{3}", fr):
                malas.append(f"{cap}: FR {fr!r}")
            if via not in _VIAS:
                malas.append(f"{cap}: vía {via!r}")
            # Toda fila cita un test o, si es manual o documental, la hoja de
            # ruta o un documento (SC-002).
            if not re.search(r"tests/|Test\w+|test_\w+", test) and not (
                    "M" in via and ("hoja de ruta" in test or "docs/" in test)):
                malas.append(f"{cap}: sin test ni entrada de la hoja de ruta")
        self.assertEqual(malas, [], "\n".join(malas))

    def test_cada_tool_citada_existe(self) -> None:
        registro = _registro()
        malas, usadas = [], set()
        for cap, celdas in _filas().items():
            for nombre in re.findall(r"`((?:ha|sv|fs)_[a-z0-9_]+)`", celdas[-1]):
                if (cap, nombre) in _CITADOS_QUE_NO_SON_TOOLS:
                    usadas.add((cap, nombre))
                elif nombre not in registro:
                    malas.append(f"{cap}: {nombre}")
        self.assertEqual(malas, [], "tools citadas que no están registradas:\n"
                         + "\n".join(malas))
        self.assertEqual(sorted(set(_CITADOS_QUE_NO_SON_TOOLS) - usadas), [],
                         "excepciones que ninguna fila cita ya")

    def test_cada_test_citado_existe(self) -> None:
        definidos = _definidos_en_tests()
        malas = []
        for cap, celdas in _filas().items():
            for cita in re.findall(r"`([^`]+)`", celdas[-1]):
                if re.fullmatch(r"tests/[\w/]+\.py", cita):
                    if not (_RAIZ / cita).is_file():
                        malas.append(f"{cap}: no existe {cita}")
                elif re.fullmatch(r"(?:Test\w+|test_\w+)(?:\.test_\w+)?\*?", cita):
                    for parte in cita.rstrip("*").split("."):
                        if cita.endswith("*"):
                            ok = any(d.startswith(parte) for d in definidos)
                        else:
                            ok = parte in definidos
                        if not ok:
                            malas.append(f"{cap}: no está definido {parte}")
        self.assertEqual(malas, [], "\n".join(malas))


if __name__ == "__main__":
    unittest.main()
