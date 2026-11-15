"""Registro de los flujos que abre Hermes (spec 016, T048; decisión del
supervisor, cierre fail-closed de FR-010c).

`ha_continue_config_entry_flow` solo continúa un flujo que abrió
`ha_start_config_entry_flow` en esta instancia de Hermes o que HA lista en
`config_entries/flow/progress` (descubiertos y `reauth`). El flujo normal,
abrir y continuar en la misma instancia, sigue igual que en la 1.1.2: un solo
`POST` por paso y nada más.

Home Assistant se simula con un `ws_send` y un `_request_json` falsos.

Controles negativos comprobados: sin `_flujos_propios.registrar` en
`ha_start_config_entry_flow` caen 3 (`test_dos_pasos_y_entrada_creada`,
`test_menu_sigue_registrado`, `test_un_paso_renueva_la_caducidad`); sin la
caducidad, `test_caducado_se_rechaza`; sin el límite, los 2 de `test_limite*`.
El rechazo de los desconocidos, en `test_tools_config_entry_flows_reauth.py`
(`TestFlujoDesconocidoRechazado`).
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import patch

from aiohttp import ClientSession

import hermes.tools.config_entry_flows as mod
from hermes.tools import _flujos_propios
from tests._ha_fixture import make_ready_client

_RUTA = "/config/config_entries/flow"


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _form(flow_id: str, step_id: str) -> dict[str, Any]:
    return {"type": "form", "flow_id": flow_id, "handler": "demo",
            "step_id": step_id, "data_schema": [], "errors": None}


class _FakeHA:
    def __init__(self) -> None:
        self.ws: list[dict[str, Any]] = []
        self.rest: list[tuple[str, str, Any]] = []
        self.progreso: list[dict[str, Any]] = []
        self.inicio: Any = _form("flujo-u", "user")
        self.pasos: list[Any] = []

    async def ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.ws.append(payload)
        if payload["type"] == "config_entries/flow/progress":
            return self.progreso
        raise AssertionError(f"comando inesperado: {payload}")

    async def request_json(self, method: str, path: str, json_body: Any = None,
                           params: dict[str, str] | None = None) -> Any:
        self.rest.append((method, path, json_body))
        if method == "POST" and path == _RUTA:
            return self.inicio
        if method == "POST":
            return self.pasos.pop(0)
        if method == "DELETE":
            return {"message": "Flow aborted"}
        raise AssertionError(f"ruta inesperada: {method} {path}")


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        _flujos_propios.limpiar()
        self.session = ClientSession()
        client = make_ready_client(self.session, {})
        self.fake = _FakeHA()
        client.ws_send = self.fake.ws_send  # type: ignore[method-assign]
        client._request_json = self.fake.request_json  # type: ignore[method-assign]
        self.mcp = DummyMCP()
        mod.register(self.mcp, client)

    async def asyncTearDown(self) -> None:
        _flujos_propios.limpiar()
        await self.session.close()

    async def llamar(self, tool: str, *args: Any) -> Any:
        return json.loads(await self.mcp.tools[tool](*args))

    async def abrir(self) -> str:
        r = await self.llamar("ha_start_config_entry_flow", "demo")
        return r["flow_id"]

    def adelantar(self) -> Any:
        ahora = _flujos_propios._ahora() + _flujos_propios.CADUCIDAD_S + 1
        return patch.object(_flujos_propios, "_ahora", return_value=ahora)


class TestAbrirYContinuarComoEnLa112(_Base):
    async def test_dos_pasos_y_entrada_creada(self) -> None:
        flow_id = await self.abrir()
        self.fake.pasos = [
            _form(flow_id, "confirm"),
            {"type": "create_entry", "flow_id": flow_id, "result": {"entry_id": "e1"}},
        ]
        r1 = await self.llamar("ha_continue_config_entry_flow", flow_id, {"host": "192.0.2.1"})
        r2 = await self.llamar("ha_continue_config_entry_flow", flow_id, {})
        self.assertEqual(r1["step_id"], "confirm")
        self.assertEqual((r2["type"], r2["status"], r2["result"]),
                         ("create_entry", "ok", {"entry_id": "e1"}))
        # Exactamente lo de la 1.1.2: un POST para abrir y uno por paso, sin
        # ninguna lectura WS.
        self.assertEqual(self.fake.rest, [
            ("POST", _RUTA, {"handler": "demo"}),
            ("POST", f"{_RUTA}/{flow_id}", {"host": "192.0.2.1"}),
            ("POST", f"{_RUTA}/{flow_id}", {}),
        ])
        self.assertEqual(self.fake.ws, [])
        # Terminado: sale del registro.
        self.assertFalse(_flujos_propios.conocido(flow_id))

    async def test_menu_sigue_registrado(self) -> None:
        self.fake.inicio = {"type": "menu", "flow_id": "flujo-m", "step_id": "user",
                            "menu_options": ["a", "b"]}
        flow_id = await self.abrir()
        self.assertTrue(_flujos_propios.conocido(flow_id))

    async def test_abort_lo_olvida(self) -> None:
        flow_id = await self.abrir()
        self.fake.pasos = [{"type": "abort", "flow_id": flow_id, "reason": "already_configured"}]
        await self.llamar("ha_continue_config_entry_flow", flow_id, {})
        self.assertFalse(_flujos_propios.conocido(flow_id))

    async def test_abortar_lo_olvida(self) -> None:
        flow_id = await self.abrir()
        self.assertEqual(await self.llamar("ha_abort_config_entry_flow", flow_id),
                         {"result": "ok"})
        self.assertFalse(_flujos_propios.conocido(flow_id))
        r = await self.llamar("ha_continue_config_entry_flow", flow_id, {})
        self.assertEqual(r["error"], "unknown_flow")

    async def test_no_automatable_no_se_registra(self) -> None:
        self.fake.inicio = {"type": "external", "flow_id": "flujo-o", "url": "x"}
        await self.llamar("ha_start_config_entry_flow", "demo")
        self.assertFalse(_flujos_propios.conocido("flujo-o"))

    async def test_create_entry_al_abrir_no_se_registra(self) -> None:
        self.fake.inicio = {"type": "create_entry", "flow_id": "flujo-c",
                            "result": {"entry_id": "e1"}}
        await self.llamar("ha_start_config_entry_flow", "demo")
        self.assertFalse(_flujos_propios.conocido("flujo-c"))


class TestCaducidadYLimite(_Base):
    async def test_caducado_se_rechaza(self) -> None:
        flow_id = await self.abrir()
        with self.adelantar():
            r = await self.llamar("ha_continue_config_entry_flow", flow_id, {})
        self.assertEqual((r["error"], r["reason"]), ("unknown_flow", "not_opened_by_hermes"))
        self.assertEqual([x for x in self.fake.rest if x[1] != _RUTA], [])

    async def test_un_paso_renueva_la_caducidad(self) -> None:
        flow_id = await self.abrir()
        self.fake.pasos = [_form(flow_id, "confirm")]
        medio = _flujos_propios._ahora() + _flujos_propios.CADUCIDAD_S / 2 + 1
        with patch.object(_flujos_propios, "_ahora", return_value=medio):
            await self.llamar("ha_continue_config_entry_flow", flow_id, {})
        luego = medio + _flujos_propios.CADUCIDAD_S / 2 + 1
        with patch.object(_flujos_propios, "_ahora", return_value=luego):
            self.assertTrue(_flujos_propios.conocido(flow_id))

    def test_limite(self) -> None:
        for i in range(_flujos_propios.LIMITE + 5):
            _flujos_propios.registrar(f"f{i}")
        self.assertEqual(len(_flujos_propios._REGISTRO), _flujos_propios.LIMITE)
        # Se olvidan los de uso más antiguo; el último sigue.
        self.assertTrue(_flujos_propios.conocido(f"f{_flujos_propios.LIMITE + 4}"))

    def test_limite_olvida_primero_los_caducados(self) -> None:
        _flujos_propios.registrar("viejo")
        with self.adelantar():
            for i in range(_flujos_propios.LIMITE):
                _flujos_propios.registrar(f"f{i}")
            self.assertNotIn("viejo", _flujos_propios._REGISTRO)
            self.assertEqual(len(_flujos_propios._REGISTRO), _flujos_propios.LIMITE)


class TestOtrosOrigenes(_Base):
    async def test_descubierto_sin_abrirlo_hermes(self) -> None:
        # Un descubrimiento lo lista HA: se continúa sin token, como en la 1.1.2.
        self.fake.progreso = [{"flow_id": "flujo-d", "handler": "demo", "step_id": "confirm",
                               "context": {"source": "zeroconf", "unique_id": "u"}}]
        self.fake.pasos = [{"type": "create_entry", "flow_id": "flujo-d",
                            "result": {"entry_id": "e2"}}]
        r = await self.llamar("ha_continue_config_entry_flow", "flujo-d", {})
        self.assertEqual(r["status"], "ok")
        self.assertEqual(self.fake.ws, [{"type": "config_entries/flow/progress"}])

    async def test_abierto_en_otra_instancia(self) -> None:
        # Tras reiniciar Hermes (registro vacío), un flujo `user` o
        # `reconfigure` de antes no se puede continuar.
        r = await self.llamar("ha_continue_config_entry_flow", "flujo-antes", {"a": 1})
        self.assertEqual(r["error"], "unknown_flow")
        self.assertEqual(self.fake.rest, [])


if __name__ == "__main__":
    unittest.main()
