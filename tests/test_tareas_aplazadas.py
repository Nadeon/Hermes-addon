"""Las tareas de fondo de `tools/ha.py` no dependen de un bucle en marcha.

`register` lanzaba la auto-clasificación con `asyncio.ensure_future`, que sin
bucle en marcha cae en `get_event_loop()`: `DeprecationWarning` en Python
3.13 (error en 3.14) y una tarea en un bucle que nadie ejecuta. Ahora usa el
bucle en marcha si lo hay y, si no, aplaza la tarea al lifespan del servidor
(`lanzar_tareas_aplazadas`). En el add-on `_build_mcp` corre dentro de
`_boot`, con el bucle en marcha, y la tarea sale en el acto, como antes.

Control negativo comprobado: con `asyncio.ensure_future(_boot_classify())`
de vuelta en `register` → `test_construir_el_servidor_fuera_de_un_bucle`
en rojo (el aviso de `get_event_loop` y nada aplazado).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import hermes.tools.ha as ha_mod

_RAIZ = Path(__file__).resolve().parent.parent

# En un intérprete nuevo: los avisos de un módulo solo salen la primera vez,
# y la suite ya ha importado y registrado todo.
_SONDA = r'''
import asyncio, json, warnings
from unittest.mock import AsyncMock, MagicMock, patch

import hermes.__main__ as main_mod
import hermes.tools.ha as ha_mod
from hermes.config import HermesConfig

config = HermesConfig(auth_password="x" * 20,
                      public_hostname="homeassistant.tailXXXX.ts.net",
                      supervisor_token="token-de-prueba")
with warnings.catch_warnings(record=True) as avisos:
    warnings.simplefilter("always")
    # Fuera de cualquier bucle, a propósito.
    main_mod._build_mcp(config, MagicMock())
aplazadas = len(ha_mod._tareas_aplazadas)

clasificar = AsyncMock(return_value=[])
async def arrancar():
    with patch.object(ha_mod, "auto_classify_dangerous", clasificar):
        lanzadas = ha_mod.lanzar_tareas_aplazadas()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return lanzadas
lanzadas = asyncio.run(arrancar())
print("SONDA=" + json.dumps({
    "avisos": [f"{a.category.__name__}: {a.message} ({a.filename})" for a in avisos],
    "aplazadas": aplazadas,
    "lanzadas": lanzadas,
    "clasificaciones": clasificar.await_count,
    "quedan": len(ha_mod._tareas_aplazadas),
}))
'''


class _MCP:
    def tool(self, *args, **kwargs):
        return lambda fn: fn


class TestTareasDeFondo(unittest.TestCase):

    def test_construir_el_servidor_fuera_de_un_bucle(self) -> None:
        entorno = dict(os.environ)
        entorno.pop("HERMES_DEV", None)
        entorno["PYTHONPATH"] = os.pathsep.join(
            [str(_RAIZ / "hermes" / "src"), str(_RAIZ)])
        r = subprocess.run([sys.executable, "-c", _SONDA], cwd=_RAIZ, env=entorno,
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=180)
        linea = next((l for l in r.stdout.splitlines() if l.startswith("SONDA=")), None)
        self.assertTrue(r.returncode == 0 and linea,
                        f"la sonda falló:\n{r.stdout[-2000:]}\n{r.stderr[-3000:]}")
        sonda = json.loads(linea[len("SONDA="):])
        # Ningún aviso al construir el servidor sin bucle.
        self.assertEqual(sonda["avisos"], [])
        # La auto-clasificación no se pierde: queda aplazada y sale al arrancar.
        self.assertEqual(sonda["aplazadas"], 1)
        self.assertEqual(sonda["lanzadas"], 1)
        self.assertEqual(sonda["clasificaciones"], 1)
        self.assertEqual(sonda["quedan"], 0)

    def test_dentro_del_bucle_sale_en_el_acto(self) -> None:
        """El comportamiento del add-on: con el bucle en marcha, nada se aplaza."""
        clasificar = AsyncMock(return_value=[])

        async def registrar() -> None:
            with patch.object(ha_mod, "auto_classify_dangerous", clasificar):
                ha_mod.register(_MCP(), MagicMock())
                self.assertEqual(ha_mod._tareas_aplazadas, [])
                await asyncio.sleep(0)
                await asyncio.sleep(0)

        with patch.object(ha_mod, "_tareas_aplazadas", []):
            asyncio.run(registrar())
        self.assertEqual(clasificar.await_count, 1)

    def test_sin_auto_clasificacion_no_se_aplaza_nada(self) -> None:
        with patch.object(ha_mod, "_tareas_aplazadas", []):
            ha_mod.register(_MCP(), MagicMock(), call_service_auto_classify=False)
            self.assertEqual(ha_mod._tareas_aplazadas, [])

    def test_ningun_ensure_future_en_tools_ha(self) -> None:
        # Solo código: el comentario que explica el cambio la nombra.
        lineas = [l for l in Path(ha_mod.__file__).read_text(encoding="utf-8").splitlines()
                  if "ensure_future(" in l and not l.lstrip().startswith("#")]
        self.assertEqual(lineas, [])

    def test_el_lifespan_lanza_las_aplazadas(self) -> None:
        import inspect

        import hermes.__main__ as main_mod

        fuente = inspect.getsource(main_mod._boot)
        lifespan = fuente[fuente.index("async def lifespan"):]
        self.assertIn("lanzar_tareas_aplazadas()", lifespan[:lifespan.index("yield")])


if __name__ == "__main__":
    unittest.main()
