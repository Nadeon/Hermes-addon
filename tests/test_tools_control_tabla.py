"""Lo de la 022 que va por la tabla de comandos (spec 022, FR-013; tramo 1).

Las genéricas `sv_read_api` y `sv_call_api` con la tabla REAL de
`command_table.py` y el Supervisor simulado de
`tests/fixtures/supervisor_control.py`:

- las 7 rutas de CAP-084 con tool dedicada → `use_dedicated_tool` sin
  llamar al Supervisor, y con `system_control` desactivada,
  `family_disabled: true`;
- las estadísticas de Core y del Supervisor se leen por `sv_read_api`;
- `POST /host/reload` va en dos pasos por `sv_call_api`;
- `POST /core/stop` y los alias `/homeassistant/*` siguen rechazados.

Control negativo (T014 h): con `/supervisor/restart` como `deny` en la tabla
cae `test_siete_rutas_hacia_su_tool` (además del de test_command_table).
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from hermes.tools import generic_commands as mod
from tests.fixtures.supervisor_control import CENTINELA_SV, SupervisorDeControl

_DEDICADAS = {
    "/core/start": "sv_start_core",
    "/core/rebuild": "sv_rebuild_core",
    "/core/options": "sv_set_core_options",
    "/supervisor/reload": "sv_reload_supervisor",
    "/supervisor/restart": "sv_restart_supervisor",
    "/supervisor/repair": "sv_repair_supervisor",
    "/supervisor/options": "sv_set_supervisor_options",
}


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


class _Base(unittest.IsolatedAsyncioTestCase):
    desactivadas: frozenset[str] = frozenset()

    def setUp(self) -> None:
        self.sv = SupervisorDeControl()
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.sv, response_max_bytes=131_072,
                     familias_desactivadas=self.desactivadas)
        self.t = self.mcp.tools


class TestPorLaTabla(_Base):
    async def test_siete_rutas_hacia_su_tool(self) -> None:
        for ruta, tool in _DEDICADAS.items():
            with self.subTest(ruta=ruta):
                r = await self.t["sv_call_api"]("POST", ruta, {"boot": True})
                self.assertEqual((r["error"], r["tool"], r["family"]),
                                 ("use_dedicated_tool", tool, "system_control"))
                self.assertFalse(r.get("family_disabled", False))
                self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.llamadas, [])

    async def test_estadisticas_por_sv_read_api(self) -> None:
        self.sv.formas[("GET", "/supervisor/stats")] = {
            "cpu_percent": 0.5, "password": CENTINELA_SV}
        for ruta in ("/core/stats", "/supervisor/stats"):
            with self.subTest(ruta=ruta):
                r = await self.t["sv_read_api"](ruta)
                self.assertNotIn("error", r)
                self.assertIn("cpu_percent", json.dumps(r))
        self.assertNotIn(CENTINELA_SV, json.dumps(r))
        self.assertEqual([(c["metodo"], c["ruta"]) for c in self.sv.llamadas],
                         [("GET", "/core/stats"), ("GET", "/supervisor/stats")])

    async def test_recargar_el_host_en_dos_pasos(self) -> None:
        vista = await self.t["sv_call_api"]("POST", "/host/reload")
        self.assertIn("confirmation_token", vista)
        self.assertEqual(vista["preview"]["category"], "confirm")
        self.assertEqual(self.sv.escrituras, [])
        r = await self.t["sv_call_api"](
            "POST", "/host/reload", confirmation_token=vista["confirmation_token"])
        self.assertIs(r["executed"], True)
        self.assertEqual([c["ruta"] for c in self.sv.escrituras], ["/host/reload"])

    async def test_parar_core_y_alias_rechazados(self) -> None:
        for ruta in ("/core/stop", "/homeassistant/stop", "/homeassistant/start",
                     "/homeassistant/restart"):
            with self.subTest(ruta=ruta):
                r = await self.t["sv_call_api"]("POST", ruta)
                self.assertIn("error", r)
                self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.llamadas, [])


class TestFamiliaApagada(_Base):
    desactivadas = frozenset({"system_control"})

    async def test_family_disabled(self) -> None:
        for ruta, tool in _DEDICADAS.items():
            with self.subTest(ruta=ruta):
                r = await self.t["sv_call_api"]("POST", ruta)
                self.assertEqual((r["error"], r["tool"], r["family_disabled"]),
                                 ("use_dedicated_tool", tool, True))
        self.assertEqual(self.sv.llamadas, [])


if __name__ == "__main__":
    unittest.main()
