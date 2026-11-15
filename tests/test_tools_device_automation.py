"""Automatizaciones de dispositivo (spec 017, tramo C; T027).

`ha_list_device_triggers`, `ha_list_device_conditions` y
`ha_list_device_actions` con Home Assistant simulado (`AsyncMock` de
`ws_send` con respuestas por `type`). Datos ficticios: `<device_id>` de
prueba, `light.salon`, el centinela `centinela-017` y un JWT de prueba, que
no pueden salir en ninguna respuesta ni en el log de Hermes (FR-015).

Control negativo del cierre del tramo (T037, 1), visto en rojo y restaurado:
sin el tope de 50 capacidades → cae
`TestCapacidades.test_tope_de_cincuenta` (60 llamadas en vez de 50 y sin
`capabilities_truncated`).
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from structlog.testing import capture_logs

import hermes.tools.device_automation as mod
from hermes.ha import HAConnectionError

_CENTINELA = "centinela-017"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJjZW50aW5lbGEifQ.c2lnbmF0dXJhLWZpY3RpY2lh"
_DEVICE = "0123456789abcdef0123456789abcdef"

_TOOLS = {
    "trigger": "ha_list_device_triggers",
    "condition": "ha_list_device_conditions",
    "action": "ha_list_device_actions",
}


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _elemento(tipo: str, n: int = 0) -> dict[str, Any]:
    clave = "trigger" if tipo == "trigger" else ("condition" if tipo == "condition" else None)
    base: dict[str, Any] = {
        "device_id": _DEVICE, "domain": "light",
        "entity_id": "fedcba9876543210fedcba9876543210", "type": f"turned_on_{n}",
        "metadata": {"secondary": False},
    }
    if clave == "trigger":
        base["trigger"] = "device"
    elif clave == "condition":
        base["condition"] = "device"
    return base


class _Base(unittest.IsolatedAsyncioTestCase):
    max_bytes = 131_072

    async def asyncSetUp(self) -> None:
        self.respuestas: dict[str, Any] = {}
        for tipo in _TOOLS:
            self.respuestas[f"device_automation/{tipo}/list"] = [
                _elemento(tipo, 0), _elemento(tipo, 1)]
            self.respuestas[f"device_automation/{tipo}/capabilities"] = {
                "extra_fields": [{"name": "for", "optional": True, "type": "positive_time_period_dict"}]}
        self.enviados: list[dict[str, Any]] = []
        self.ha = MagicMock()
        self.ha.wait_ready = AsyncMock(return_value=True)
        self.ha.ws_send = AsyncMock(side_effect=self._ws_send)
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha, response_max_bytes=self.max_bytes)
        self.t = self.mcp.tools

    async def _ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.enviados.append(payload)
        r = self.respuestas[payload["type"]]
        if isinstance(r, BaseException):
            raise r
        if callable(r):
            return r(payload)
        return r


class TestListar(_Base):
    async def test_cada_tipo_envia_su_comando_y_devuelve_la_lista_tal_cual(self) -> None:
        for tipo, tool in _TOOLS.items():
            with self.subTest(tipo=tipo):
                self.enviados.clear()
                r = await self.t[tool](device_id=_DEVICE)
                self.assertEqual(self.enviados, [
                    {"type": f"device_automation/{tipo}/list", "device_id": _DEVICE}])
                self.assertEqual(r["device_id"], _DEVICE)
                self.assertEqual((r["count"], r["truncated"]), (2, False))
                self.assertEqual(r["items"], [_elemento(tipo, 0), _elemento(tipo, 1)])
                # Sin capacidades pedidas, ni la marca ni la clave.
                self.assertNotIn("capabilities_truncated", r)
                self.assertNotIn("capabilities", r["items"][0])

    async def test_lista_vacia_no_es_error(self) -> None:
        self.respuestas["device_automation/trigger/list"] = []
        r = await self.t["ha_list_device_triggers"](device_id=_DEVICE, include_capabilities=True)
        self.assertEqual((r["count"], r["items"], r["capabilities_truncated"]), (0, [], False))

    async def test_device_id_vacio_sin_llamar(self) -> None:
        for valor in ("", "   ", None, 5):
            with self.subTest(valor=valor):
                r = await self.t["ha_list_device_actions"](device_id=valor)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "device_id"))
        r = await self.t["ha_list_device_actions"](device_id=_DEVICE, include_capabilities="yes")
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "include_capabilities"))
        self.ha.ws_send.assert_not_awaited()

    async def test_no_encontrado(self) -> None:
        self.respuestas["device_automation/condition/list"] = HAConnectionError(
            "Device not found", code="not_found")
        r = await self.t["ha_list_device_conditions"](device_id=_DEVICE)
        self.assertEqual(r, {"error": "not_found", "device_id": _DEVICE})

    async def test_respuesta_que_no_es_lista(self) -> None:
        for valor in (None, {"a": 1}, "x"):
            with self.subTest(valor=valor):
                self.respuestas["device_automation/trigger/list"] = valor
                r = await self.t["ha_list_device_triggers"](device_id=_DEVICE)
                self.assertEqual(r["error"], "unexpected_response")

    async def test_error_de_ha_redactado_y_conexion(self) -> None:
        self.respuestas["device_automation/action/list"] = HAConnectionError(
            f"boom password={_CENTINELA} {_JWT}", code="home_assistant_error")
        with capture_logs() as logs:
            r = await self.t["ha_list_device_actions"](device_id=_DEVICE)
        self.assertEqual((r["error"], r["ha_code"]), ("ha_command_failed", "home_assistant_error"))
        texto = json.dumps(r) + json.dumps(logs, default=str)
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn(_JWT, texto)
        self.respuestas["device_automation/action/list"] = HAConnectionError("WS cerrada")
        r = await self.t["ha_list_device_actions"](device_id=_DEVICE)
        self.assertEqual(r, {"error": "WS cerrada"})


class TestCapacidades(_Base):
    async def test_una_llamada_por_elemento_con_su_clave(self) -> None:
        for tipo, tool in _TOOLS.items():
            with self.subTest(tipo=tipo):
                self.enviados.clear()
                r = await self.t[tool](device_id=_DEVICE, include_capabilities=True)
                caps = [p for p in self.enviados if p["type"].endswith("/capabilities")]
                self.assertEqual(caps, [
                    {"type": f"device_automation/{tipo}/capabilities", tipo: _elemento(tipo, 0)},
                    {"type": f"device_automation/{tipo}/capabilities", tipo: _elemento(tipo, 1)},
                ])
                self.assertIs(r["capabilities_truncated"], False)
                for item in r["items"]:
                    self.assertEqual(item["capabilities"]["extra_fields"][0]["name"], "for")

    async def test_fallo_de_un_elemento_no_tumba_la_lista(self) -> None:
        def caps(p: dict[str, Any]) -> Any:
            if p["trigger"]["type"] == "turned_on_0":
                raise HAConnectionError(f"bad token={_CENTINELA}", code="invalid_format")
            return {"extra_fields": []}

        self.respuestas["device_automation/trigger/capabilities"] = caps
        r = await self.t["ha_list_device_triggers"](device_id=_DEVICE, include_capabilities=True)
        primero, segundo = r["items"]
        self.assertNotIn("capabilities", primero)
        self.assertIn("capabilities_error", primero)
        self.assertNotIn(_CENTINELA, primero["capabilities_error"])
        self.assertEqual(segundo["capabilities"], {"extra_fields": []})

    async def test_tope_de_cincuenta(self) -> None:
        self.respuestas["device_automation/action/list"] = [
            _elemento("action", n) for n in range(60)]
        r = await self.t["ha_list_device_actions"](device_id=_DEVICE, include_capabilities=True)
        llamadas = [p for p in self.enviados if p["type"].endswith("/capabilities")]
        self.assertEqual(len(llamadas), 50)
        self.assertIs(r["capabilities_truncated"], True)
        self.assertEqual(r["count"], 60)
        self.assertTrue(all("capabilities" in i for i in r["items"][:50]))
        self.assertFalse(any("capabilities" in i for i in r["items"][50:]))

    async def test_capacidades_redactadas(self) -> None:
        self.respuestas["device_automation/trigger/capabilities"] = {
            "extra_fields": [{"name": "code", "default": f"password={_CENTINELA}"}],
            "password": _CENTINELA,
        }
        with capture_logs() as logs:
            r = await self.t["ha_list_device_triggers"](device_id=_DEVICE, include_capabilities=True)
        texto = json.dumps(r) + json.dumps(logs, default=str)
        self.assertNotIn(_CENTINELA, texto)


class TestRecorte(_Base):
    max_bytes = 4_000

    async def test_recorte_por_tamano(self) -> None:
        self.respuestas["device_automation/trigger/list"] = [
            _elemento("trigger", n) for n in range(100)]
        r = await self.t["ha_list_device_triggers"](device_id=_DEVICE)
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False).encode()), self.max_bytes)
        self.assertIs(r["truncated"], True)
        self.assertLess(r["count"], 100)
        self.assertEqual(r["count"], len(r["items"]))
        self.assertEqual(r["_response_limit"]["total"], 100)
        self.assertEqual(r["device_id"], _DEVICE)


if __name__ == "__main__":
    unittest.main()
