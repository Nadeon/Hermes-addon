"""Argumentos de texto libre fuera del log (spec 006, historia 3).

Hasta 1.1.0 el evento `fs_search_in_config_ok` guardaba el `pattern` en claro
y, en una instalación real, dejó IPs de la LAN y prefijos MAC escritos como
regex (`192\\.0\\.2\\.10`), que la redacción de red no puede reconocer.
`ha_render_template` guardaba los 100 primeros caracteres de la plantilla, con
nombres de entidades de la casa. Desde 1.1.1 solo se registra la longitud.

Todos los valores son ficticios: IP de documentación (RFC 5737) y MAC del
rango de documentación (RFC 7042).
"""

from __future__ import annotations

import inspect
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import ClientSession
from structlog.testing import capture_logs

import hermes.fs as fs_module
import hermes.tools.filesystem as fs_tools
import hermes.tools.templates as templates_mod
from hermes.ha import HAConnectionError
from tests._ha_fixture import make_ready_client

_IP = r"192\.0\.2\.10"
_MAC = "00:00:5e:00:53:01"
_PATRON = f"{_IP}|{_MAC}"
_ENTIDAD = "sensor.test_privado"


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _texto(logs: list[dict]) -> str:
    return repr(logs)


class TestFsSearchNoRegistraElPatron(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.root = Path(self._tmp) / "config"
        self.root.mkdir()
        (self.root / "configuration.yaml").write_text(
            "host: 192.0.2.10\nmac: 00:00:5e:00:53:01\n", encoding="utf-8"
        )
        self._p = patch.object(fs_module, "CONFIG_BASE", self.root.resolve())
        self._p.start()
        mcp = DummyMCP()
        fs_tools.register(mcp, response_max_bytes=1_048_576)
        self.search = mcp.tools["fs_search_in_config"]

    def tearDown(self) -> None:
        self._p.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _sin_patron(self, logs: list[dict], evento: str) -> None:
        texto = _texto(logs)
        self.assertNotIn("192", texto)
        self.assertNotIn("00:53:01", texto)
        entrada = next(e for e in logs if e.get("event") == evento)
        self.assertNotIn("pattern", entrada)
        self.assertIsInstance(entrada.get("pattern_len"), int)

    async def test_busqueda_correcta(self) -> None:
        with capture_logs() as logs:
            await self.search(_PATRON)
        self._sin_patron(logs, "fs_search_in_config_ok")

    async def test_patron_rechazado(self) -> None:
        with capture_logs() as logs:
            await self.search(f"(a+)+{_IP}")
        self._sin_patron(logs, "fs_search_pattern_rejected")

    async def test_timeout_y_fallo(self) -> None:
        for respuesta, evento in (
            ({"error": "search_timeout", "detail": "t"}, "fs_search_timeout"),
            ({"error": "search_failed", "detail": "d"}, "fs_search_failed"),
        ):
            with self.subTest(evento=evento), patch.object(
                fs_tools, "_run_scan_in_subprocess", return_value=dict(respuesta)
            ), capture_logs() as logs:
                await self.search(_PATRON)
                self._sin_patron(logs, evento)

    def test_ningun_evento_del_modulo_lleva_el_patron(self) -> None:
        """Incluye `fs_search_subprocess_killed`, que no se puede provocar
        sin esperar al plazo real del subproceso."""
        fuente = inspect.getsource(fs_tools)
        llamadas = re.findall(r"logger\.\w+\(.*?\)", fuente, flags=re.DOTALL)
        self.assertTrue(llamadas)
        for llamada in llamadas:
            self.assertNotRegex(llamada, r"\bpattern\s*=", llamada)


class TestRenderTemplateNoRegistraLaPlantilla(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def _render(self, comportamiento) -> list[dict]:
        client = make_ready_client(self.session, {})

        async def falso(payload, event_timeout_seconds=10.0, collect_warnings=False):
            return comportamiento()

        client.ws_one_shot_subscription = falso  # type: ignore[method-assign]
        mcp = DummyMCP()
        templates_mod.register(mcp, client)
        with capture_logs() as logs:
            await mcp.tools["ha_render_template"](f"{{{{ states('{_ENTIDAD}') }}}}")
        return logs

    async def test_ningun_camino_registra_la_plantilla(self) -> None:
        def ok():
            return {"result": "on", "listeners": {}}

        def error():
            return {"error": "UndefinedError", "level": "ERROR"}

        def timeout():
            raise HAConnectionError("Timeout waiting for subscription event")

        def ws_error():
            raise HAConnectionError("HA WS command failed: boom")

        for nombre, comportamiento, evento in (
            ("ok", ok, "ha_render_template_ok"),
            ("error", error, "ha_render_template_error"),
            ("timeout", timeout, "ha_render_template_timeout"),
            ("ws_error", ws_error, "ha_render_template_ws_error"),
        ):
            with self.subTest(camino=nombre):
                logs = await self._render(comportamiento)
                self.assertNotIn(_ENTIDAD, _texto(logs))
                entrada = next(e for e in logs if e.get("event") == evento)
                self.assertNotIn("template", entrada)
                self.assertIsInstance(entrada.get("template_len"), int)
