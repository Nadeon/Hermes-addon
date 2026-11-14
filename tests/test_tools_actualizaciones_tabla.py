"""Las genéricas rechazan las rutas de actualización hacia sus tools (spec 015,
tramos 1 y 2, FR-016; T012 y T027).

Con la TABLA REAL de `command_table.py`: `GET /available_updates`,
`POST /core/update`, `POST /refresh_updates`, `POST /reload_updates`,
`hassio/update/core` y, desde el tramo 2, `POST /os/update` y
`POST /supervisor/update` responden `use_dedicated_tool` con la tool de la 015 y
sin llamar a nada, también con la familia `system_updates` apagada (entonces
con `family_disabled: true`): una genérica nunca es la puerta trasera de una
actualización sin la vista previa de la tool dedicada.

Control negativo (T015 g): con `/core/update` de vuelta a `deny`, el caso de
`sv_call_api` cae (sale `command_denied`).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from hermes import security
from hermes.tools import generic_commands as mod
from tests.fixtures.supervisor_actualizaciones import SupervisorActualizaciones

_CASOS: tuple[tuple[str, tuple[Any, ...], str], ...] = (
    ("sv_read_api", ("/available_updates",), "sv_list_available_updates"),
    ("sv_call_api", ("POST", "/core/update"), "sv_update_core"),
    ("sv_call_api", ("POST", "/refresh_updates"), "sv_check_for_updates"),
    ("sv_call_api", ("POST", "/reload_updates"), "sv_check_for_updates"),
    ("ha_call_ws_command", ("hassio/update/core", {"backup": False}), "sv_update_core"),
    # Tramo 2 (T027).
    ("sv_call_api", ("POST", "/os/update"), "sv_update_os"),
    ("sv_call_api", ("POST", "/supervisor/update"), "sv_update_supervisor"),
)


class _MCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


class _Base(unittest.IsolatedAsyncioTestCase):
    desactivadas: frozenset[str] = frozenset()

    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.sv = SupervisorActualizaciones()
        mcp = _MCP()
        mod.register(mcp, self.sv, response_max_bytes=131_072,
                     familias_desactivadas=self.desactivadas)
        self.t = mcp.tools

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def comprobar(self, family_disabled: bool) -> None:
        for generica, args, tool in _CASOS:
            with self.subTest(generica=generica, args=args[:2]):
                r = await self.t[generica](*args)
                self.assertEqual(r.get("error"), "use_dedicated_tool", r)
                self.assertEqual(r["tool"], tool)
                self.assertIs(r["family_disabled"], family_disabled)
                self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.llamadas, [])
        self.assertEqual(self.sv.ws_llamadas, [])


class TestRechazoHaciaSuTool(_Base):
    async def test_dedicadas(self) -> None:
        await self.comprobar(family_disabled=False)


class TestConLaFamiliaApagada(_Base):
    desactivadas = frozenset({"system_updates"})

    async def test_family_disabled(self) -> None:
        await self.comprobar(family_disabled=True)


if __name__ == "__main__":
    unittest.main()
