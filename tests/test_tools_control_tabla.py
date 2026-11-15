"""Lo de la 022 que va por la tabla de comandos (spec 022, FR-013 a FR-016).

Las genéricas `sv_read_api` y `sv_call_api` con la tabla REAL de
`command_table.py` y el Supervisor simulado de
`tests/fixtures/supervisor_control.py`:

- las 7 rutas de CAP-084 con tool dedicada → `use_dedicated_tool` sin
  llamar al Supervisor, y con `system_control` desactivada,
  `family_disabled: true`;
- las estadísticas de Core y del Supervisor se leen por `sv_read_api`;
- `POST /host/reload` va en dos pasos por `sv_call_api`;
- `POST /core/stop` y los alias `/homeassistant/*` siguen rechazados.

Tramo 2 (T024): aplicar una sugerencia va a su tool (`resolution_fixes`);
los chequeos y el healthcheck van en dos pasos; las rutas de plugins
(CAP-091), Docker (CAP-092) y placas y hora (CAP-094) se recorren TODAS desde
la tabla real; la contraseña de un registro Docker no sale en la vista previa,
ni en el log, ni en un error del Supervisor que la repita (FR-079).

Controles negativos: con `/supervisor/restart` como `deny` en la tabla cae
`test_siete_rutas_hacia_su_tool` (T014 h); con un chequeo como `deny` cae
`test_chequeos_en_dos_pasos` (T028 i); sin tapar `password` en la vista previa
o en el error cae `TestRegistroDocker` (T028 h).
"""

from __future__ import annotations

import json
import re
import unittest
from typing import Any

from structlog.testing import capture_logs

from hermes import command_table as ct
from hermes.ha import HAConnectionError
from hermes.tools import generic_commands as mod
from tests.fixtures.supervisor_control import CENTINELA_SV, SupervisorDeControl

# Valores de ejemplo para los parámetros de las plantillas (ficticios).
_PARAMETROS = {"source": "input", "board": "rpi4", "hostname": "registro.example",
               "check": "free_space"}


def _concreta(plantilla: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: _PARAMETROS[m.group(1)], plantilla)


def _rutas(caps: tuple[str, ...], categoria: str) -> list[tuple[str, str]]:
    """Las rutas de la tabla REAL con esas CAP y esa categoría."""
    return sorted(k for k, e in ct.SUPERVISOR.items()
                  if e.cap in caps and e.category == categoria
                  and e.family == "generic_commands")

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


class TestSugerenciasYChequeos(_Base):
    async def test_aplicar_va_a_su_tool(self) -> None:
        r = await self.t["sv_call_api"]("POST", "/resolution/suggestion/" + "1" * 32)
        self.assertEqual((r["error"], r["tool"], r["family"]),
                         ("use_dedicated_tool", "sv_apply_resolution_suggestion",
                          "resolution_fixes"))
        self.assertFalse(r.get("family_disabled", False))
        self.assertEqual(self.sv.llamadas, [])

    async def test_chequeos_en_dos_pasos(self) -> None:
        for ruta, cuerpo in (("/resolution/check/free_space/run", None),
                             ("/resolution/check/free_space/options", {"enabled": False}),
                             ("/resolution/healthcheck", None)):
            with self.subTest(ruta=ruta):
                self.sv.formas[("POST", ruta)] = {}
                vista = await self.t["sv_call_api"]("POST", ruta, cuerpo)
                self.assertIn("confirmation_token", vista, vista)
                antes = len(self.sv.escrituras)
                r = await self.t["sv_call_api"](
                    "POST", ruta, cuerpo, confirmation_token=vista["confirmation_token"])
                self.assertIs(r["executed"], True, r)
                self.assertEqual([c["ruta"] for c in self.sv.escrituras[antes:]], [ruta])


class TestPluginsDockerPlacas(_Base):
    """CAP-091, CAP-092 y CAP-094 (research R-8): sin cambios en la tabla, y
    cada ruta funciona por su genérica."""

    def test_hay_rutas(self) -> None:
        # Si la tabla perdiera las rutas, los recorridos de abajo no probarían
        # nada.
        self.assertGreaterEqual(len(_rutas(("CAP-091",), "read")), 10)
        self.assertGreaterEqual(len(_rutas(("CAP-091",), "confirm")), 15)
        self.assertGreaterEqual(len(_rutas(("CAP-092",), "confirm")), 3)
        self.assertGreaterEqual(len(_rutas(("CAP-094",), "confirm")), 4)

    async def test_lecturas(self) -> None:
        for _metodo, plantilla in _rutas(("CAP-091", "CAP-092", "CAP-094"), "read"):
            ruta = _concreta(plantilla)
            with self.subTest(ruta=ruta):
                self.sv.formas[("GET", ruta)] = {"version": "1.0.0"}
                r = await self.t["sv_read_api"](ruta)
                self.assertNotIn("error", r, r)
        self.assertEqual(self.sv.escrituras, [])

    async def test_escrituras_en_dos_pasos(self) -> None:
        for metodo, plantilla in _rutas(("CAP-091", "CAP-092", "CAP-094"), "confirm"):
            ruta = _concreta(plantilla)
            with self.subTest(ruta=(metodo, ruta)):
                self.sv.formas[(metodo, ruta)] = {}
                vista = await self.t["sv_call_api"](metodo, ruta, {})
                self.assertIn("confirmation_token", vista, vista)
                antes = len(self.sv.escrituras)
                r = await self.t["sv_call_api"](
                    metodo, ruta, {}, confirmation_token=vista["confirmation_token"])
                self.assertIs(r["executed"], True, r)
                self.assertEqual(
                    [(c["metodo"], c["ruta"]) for c in self.sv.escrituras[antes:]],
                    [(metodo, ruta)])


class TestRegistroDocker(_Base):
    """FR-079: la contraseña de un registro Docker no sale por ningún lado."""

    _CUERPO = {"registro.example": {"username": "u", "password": CENTINELA_SV}}

    async def test_vista_previa_y_log(self) -> None:
        self.sv.formas[("POST", "/docker/registries")] = {}
        with capture_logs() as eventos:
            vista = await self.t["sv_call_api"]("POST", "/docker/registries", self._CUERPO)
            self.assertIn("confirmation_token", vista)
            r = await self.t["sv_call_api"]("POST", "/docker/registries", self._CUERPO,
                                            confirmation_token=vista["confirmation_token"])
        self.assertIs(r["executed"], True)
        self.assertNotIn(CENTINELA_SV, json.dumps(vista, default=str))
        self.assertNotIn(CENTINELA_SV, json.dumps(r, default=str))
        self.assertNotIn(CENTINELA_SV, json.dumps(eventos, default=str))
        # Al Supervisor sí le llega, que es quien la necesita.
        self.assertEqual(self.sv.escrituras[-1]["json"], self._CUERPO)

    async def test_error_que_repite_el_cuerpo(self) -> None:
        self.sv.errores[("POST", "/docker/registries")] = HAConnectionError(
            "Supervisor REST POST http://supervisor/docker/registries failed 400: "
            + json.dumps({"result": "error", "message": f"bad body {self._CUERPO}"}),
            status=400)
        with capture_logs() as eventos:
            vista = await self.t["sv_call_api"]("POST", "/docker/registries", self._CUERPO)
            r = await self.t["sv_call_api"]("POST", "/docker/registries", self._CUERPO,
                                            confirmation_token=vista["confirmation_token"])
        self.assertIn("error", r)
        self.assertNotIn(CENTINELA_SV, json.dumps(r, default=str))
        self.assertNotIn(CENTINELA_SV, json.dumps(eventos, default=str))

    async def test_quitar_un_registro(self) -> None:
        self.sv.formas[("DELETE", "/docker/registries/registro.example")] = {}
        vista = await self.t["sv_call_api"]("DELETE", "/docker/registries/registro.example")
        r = await self.t["sv_call_api"]("DELETE", "/docker/registries/registro.example",
                                        confirmation_token=vista["confirmation_token"])
        self.assertIs(r["executed"], True)


class TestSigueCerrado(_Base):
    async def test_canal_del_supervisor(self) -> None:
        # `channel` no se abre por la genérica: la ruta es de la dedicada, que
        # lo rechaza con `not_allowed` (test_tools_system_control).
        r = await self.t["sv_call_api"]("POST", "/supervisor/options", {"channel": "dev"})
        self.assertEqual((r["error"], r["tool"]),
                         ("use_dedicated_tool", "sv_set_supervisor_options"))
        self.assertEqual(self.sv.llamadas, [])

    async def test_parar_core(self) -> None:
        for ruta in ("/core/stop", "/homeassistant/stop"):
            with self.subTest(ruta=ruta):
                r = await self.t["sv_call_api"]("POST", ruta)
                self.assertEqual(r["error"], "command_denied")
        self.assertEqual(self.sv.llamadas, [])


class TestFamiliaApagadaResolution(_Base):
    desactivadas = frozenset({"resolution_fixes"})

    async def test_aplicar_con_la_familia_apagada(self) -> None:
        r = await self.t["sv_call_api"]("POST", "/resolution/suggestion/" + "1" * 32)
        self.assertEqual((r["tool"], r["family_disabled"]),
                         ("sv_apply_resolution_suggestion", True))
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
