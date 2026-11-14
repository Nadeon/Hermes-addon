"""Hermes no usa nada que el SDK `mcp` marque como deprecado (spec 027, FR-004, FR-005).

El SDK 2.x avisa de lo deprecado con `MCPDeprecationWarning`
(`mcp/shared/exceptions.py`), que hereda de `UserWarning` y NO de
`DeprecationWarning`: un filtro que solo mire `DeprecationWarning` no lo ve.
La guarda vigila las dos familias.

La comprobación corre en un intérprete nuevo: en la suite, otros tests ya han
importado los módulos de Hermes y los avisos que se emiten al importar no
volverían a salir.

Controles negativos comprobados (T015):
- `warnings.warn("x", MCPDeprecationWarning)` en `register` de
  `tools/ping.py` → `test_sin_avisos_de_deprecacion` en rojo.
- `warnings.warn("x", DeprecationWarning)` en el mismo sitio → el mismo
  test en rojo.
- `ping` anotada `-> object` → `test_tools_con_output_schema` en rojo.

Al escribirla, la guarda vio un `DeprecationWarning` de `tools/ha.py`
(`asyncio.ensure_future` sin bucle en marcha): la sonda construía el servidor
fuera del bucle. En el add-on `_build_mcp` corre dentro de `_boot`, con el
bucle en marcha, y no avisa; la sonda hace ya lo mismo.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
_SRC = _RAIZ / "hermes" / "src" / "hermes"

# Se ejecuta con `python -c` en un proceso aparte. Imprime una línea JSON con
# los avisos y las tools que declaran `outputSchema`.
_SONDA = r'''
import asyncio, importlib, json, os, pkgutil, sys, warnings
from unittest.mock import MagicMock

warnings.simplefilter("always")
with warnings.catch_warnings(record=True) as avisos:
    warnings.simplefilter("always")
    import hermes
    for mod in pkgutil.walk_packages(hermes.__path__, "hermes."):
        if mod.name == "hermes.__main__":
            continue
        importlib.import_module(mod.name)
    import hermes.__main__ as main_mod
    from hermes.config import HermesConfig

    config = HermesConfig(auth_password="x" * 20,
                          public_hostname="homeassistant.tailXXXX.ts.net",
                          supervisor_token="token-de-prueba")
    async def usar():
        # Dentro del bucle, como en `_boot`: el registro programa tareas
        # (`asyncio.ensure_future`) y fuera de un bucle Python avisaría de
        # algo que en el add-on no pasa.
        mcp = main_mod._build_mcp(config, MagicMock())
        tools = await mcp.list_tools()
        await mcp.call_tool("ping", {})
        return tools

    tools = asyncio.run(usar())

from mcp.shared.exceptions import MCPDeprecationWarning

salida = {
    "avisos": [
        {"categoria": a.category.__name__,
         "mcp": issubclass(a.category, MCPDeprecationWarning),
         "deprecacion": issubclass(a.category, (DeprecationWarning,
                                                PendingDeprecationWarning)),
         "fichero": a.filename.replace("\\", "/"),
         "mensaje": str(a.message)[:300]}
        for a in avisos
    ],
    "output_schema": sorted(
        t.name for t in tools
        if (getattr(t, "outputSchema", None) or getattr(t, "output_schema", None))
    ),
}
print("SONDA=" + json.dumps(salida))
'''

_ORIGENES = re.compile(r"/(mcp|mcp_types|hermes)/")


def _sondear() -> dict:
    entorno = dict(os.environ)
    entorno.pop("HERMES_DEV", None)  # configuración por defecto
    entorno["PYTHONPATH"] = os.pathsep.join(
        [str(_RAIZ / "hermes" / "src"), str(_RAIZ)])
    r = subprocess.run([sys.executable, "-c", _SONDA], cwd=_RAIZ, env=entorno,
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=180)
    linea = next((l for l in r.stdout.splitlines() if l.startswith("SONDA=")), None)
    assert r.returncode == 0 and linea, f"la sonda falló:\n{r.stdout[-2000:]}\n{r.stderr[-3000:]}"
    return json.loads(linea[len("SONDA="):])


class TestSinDeprecacionesDelSdk(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.sonda = _sondear()

    def test_sin_avisos_de_deprecacion(self) -> None:
        malos = [
            a for a in self.sonda["avisos"]
            if a["mcp"] or (a["deprecacion"] and _ORIGENES.search(a["fichero"]))
        ]
        self.assertEqual(malos, [])

    def test_ningun_fichero_nombra_la_constante_deprecada(self) -> None:
        # El middleware usa ya las tuplas nuevas del SDK desde la spec 003.
        usos = [str(p.relative_to(_RAIZ)) for p in _SRC.rglob("*.py")
                if "SUPPORTED_PROTOCOL_VERSIONS" in p.read_text(encoding="utf-8")]
        self.assertEqual(usos, [])

    # ── FR-004: qué tools declaran `outputSchema` ─────────────

    def test_tools_con_output_schema(self) -> None:
        # Solo las dos de prosa (`-> str`), cuyo esquema infiere el SDK.
        # Cambiarlo es una decisión explícita (duda D-3 de la 027).
        self.assertEqual(self.sonda["output_schema"], ["hermes_guide", "ping"])


class TestTopeDelSdk(unittest.TestCase):

    def test_requirements_mantiene_el_tope_menor_que_3(self) -> None:
        lineas = [
            l.strip() for l in
            (_RAIZ / "hermes" / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if re.match(r"^mcp\s*[<>=~!]", l.strip())
        ]
        self.assertEqual(len(lineas), 1, lineas)
        self.assertIn("<3", lineas[0].replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
