"""Tools de validación de Core (spec 012, tramo B; T020).

`ha_validate_config` y `ha_test_condition` con Home Assistant simulado
(`AsyncMock` de `ws_send`). Datos ficticios: `light.salon`, el centinela
`centinela-012` y un JWT de prueba, que no pueden salir en ninguna respuesta.

Controles negativos (T033 a y f), comprobados y con recuentos en el commit:
aceptar `config` y partes a la vez → cae `test_config_y_partes_a_la_vez`;
no informar `not_validated` (lista vacía siempre) → caen
`test_config_de_automatizacion` y `test_config_de_script`.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import hermes.tools.core_validation as mod
from hermes.ha import HAConnectionError

_CENTINELA = "centinela-012"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJjZW50aW5lbGEifQ.c2lnbmF0dXJhLWZpY3RpY2lh"

_TRIGGER = {"trigger": "state", "entity_id": "light.salon", "to": "on"}
_CONDICION = {"condition": "state", "entity_id": "light.salon", "state": "on"}
_ACCION = {"action": "light.turn_off", "target": {"entity_id": "light.salon"}}


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.enviados: list[dict[str, Any]] = []
        self.respuesta: Any = None
        self.fallo: HAConnectionError | None = None
        self.ha = MagicMock()
        self.ha.wait_ready = AsyncMock(return_value=True)
        self.ha.ws_send = AsyncMock(side_effect=self._ws_send)
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha)
        self.t = self.mcp.tools

    async def _ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.enviados.append(payload)
        if self.fallo is not None:
            raise self.fallo
        if payload["type"] == "validate_config" and self.respuesta is None:
            return {k: {"valid": True, "error": None}
                    for k in ("triggers", "conditions", "actions") if k in payload}
        return self.respuesta


class TestValidateConfig(_Base):
    async def test_tres_partes_un_solo_envio(self) -> None:
        r = await self.t["ha_validate_config"](
            triggers=[_TRIGGER], conditions=[_CONDICION], actions=[_ACCION])
        self.assertEqual(self.enviados, [{"type": "validate_config", "triggers": [_TRIGGER],
                                          "conditions": [_CONDICION], "actions": [_ACCION]}])
        for parte in ("triggers", "conditions", "actions"):
            self.assertEqual(r[parte], {"valid": True, "error": None})
        self.assertIs(r["saved"], False)
        self.assertEqual(r["not_validated"], [])

    async def test_solo_las_partes_enviadas(self) -> None:
        r = await self.t["ha_validate_config"](conditions=_CONDICION)
        self.assertEqual(self.enviados, [{"type": "validate_config", "conditions": _CONDICION}])
        self.assertNotIn("triggers", r)
        self.assertNotIn("actions", r)

    async def test_config_de_automatizacion(self) -> None:
        config = {"alias": "Apagar", "mode": "single", "id": "1",
                  "triggers": [_TRIGGER], "conditions": [], "actions": [_ACCION]}
        r = await self.t["ha_validate_config"](config=config)
        self.assertEqual(self.enviados, [{"type": "validate_config", "triggers": [_TRIGGER],
                                          "conditions": [], "actions": [_ACCION]}])
        self.assertEqual(r["not_validated"], ["alias", "id", "mode"])
        self.assertIs(r["saved"], False)

    async def test_config_en_singular(self) -> None:
        config = {"alias": "x", "trigger": _TRIGGER, "condition": _CONDICION, "action": _ACCION}
        await self.t["ha_validate_config"](config=config)
        self.assertEqual(self.enviados, [{"type": "validate_config", "triggers": _TRIGGER,
                                          "conditions": _CONDICION, "actions": _ACCION}])

    async def test_config_de_script(self) -> None:
        config = {"alias": "Script", "mode": "queued", "fields": {}, "sequence": [_ACCION]}
        r = await self.t["ha_validate_config"](config=config)
        self.assertEqual(self.enviados, [{"type": "validate_config", "actions": [_ACCION]}])
        self.assertEqual(r["not_validated"], ["alias", "fields", "mode"])
        self.assertEqual(r["actions"], {"valid": True, "error": None})

    async def test_parte_invalida(self) -> None:
        self.respuesta = {"triggers": {"valid": False, "error": "Invalid trigger 'nope'"}}
        r = await self.t["ha_validate_config"](triggers={"trigger": "nope"})
        self.assertEqual(r["triggers"], {"valid": False, "error": "Invalid trigger 'nope'"})

    async def test_errores_de_argumentos_sin_envio(self) -> None:
        casos = [
            {"config": {"trigger": _TRIGGER, "triggers": [_TRIGGER]}},
            {"config": {"action": _ACCION, "sequence": [_ACCION]}},
            {},
            {"config": ["no", "objeto"]},
            {"config": {"alias": "sin partes"}},
        ]
        for kwargs in casos:
            with self.subTest(kwargs=kwargs):
                r = await self.t["ha_validate_config"](**kwargs)
                self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()

    async def test_config_y_partes_a_la_vez(self) -> None:
        r = await self.t["ha_validate_config"](config={"triggers": [_TRIGGER]},
                                               actions=[_ACCION])
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "config"))
        self.ha.ws_send.assert_not_awaited()

    async def test_error_de_ha_redactado(self) -> None:
        self.respuesta = {"actions": {"valid": False,
                                      "error": f"bad value password={_CENTINELA} {_JWT}"}}
        r = await self.t["ha_validate_config"](actions=[_ACCION])
        self.assertFalse(r["actions"]["valid"])
        self.assertNotIn(_CENTINELA, str(r))
        self.assertNotIn(_JWT, str(r))

    async def test_fallo_de_conexion_redactado(self) -> None:
        self.fallo = HAConnectionError(f"caída token: {_CENTINELA}")
        r = await self.t["ha_validate_config"](actions=[_ACCION])
        self.assertIn("error", r)
        self.assertNotIn(_CENTINELA, str(r))

    async def test_respuesta_que_no_es_objeto(self) -> None:
        self.respuesta = ["raro"]
        r = await self.t["ha_validate_config"](actions=[_ACCION])
        self.assertIn("error", r)


class TestTestCondition(_Base):
    async def test_resultado_tal_cual(self) -> None:
        self.respuesta = {"result": True}
        r = await self.t["ha_test_condition"](condition=_CONDICION)
        self.assertEqual(r, {"result": True})
        self.assertEqual(self.enviados, [{"type": "test_condition", "condition": _CONDICION}])

    async def test_template_errors_y_variables(self) -> None:
        self.respuesta = {"result": False, "template_errors": ["'x' is undefined"]}
        r = await self.t["ha_test_condition"](
            condition={"condition": "template", "value_template": "{{ x }}"},
            variables={"y": 1})
        self.assertEqual(r, {"result": False, "template_errors": ["'x' is undefined"]})
        self.assertEqual(self.enviados[0]["variables"], {"y": 1})

    async def test_argumentos_invalidos_sin_envio(self) -> None:
        for kwargs in ({"condition": "state"}, {"condition": [_CONDICION]},
                       {"condition": _CONDICION, "variables": ["x"]}):
            with self.subTest(kwargs=kwargs):
                r = await self.t["ha_test_condition"](**kwargs)
                self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()

    async def test_invalid_format(self) -> None:
        self.fallo = HAConnectionError(f"Invalid condition password={_CENTINELA}",
                                       code="invalid_format")
        r = await self.t["ha_test_condition"](condition=_CONDICION)
        self.assertEqual(r["error"], "invalid_condition")
        self.assertIn("Invalid condition", r["detail"])
        self.assertNotIn(_CENTINELA, r["detail"])

    async def test_home_assistant_error(self) -> None:
        self.fallo = HAConnectionError(f"Fallo {_JWT}", code="home_assistant_error")
        r = await self.t["ha_test_condition"](condition=_CONDICION)
        self.assertEqual(r["error"], "condition_error")
        self.assertNotIn(_JWT, r["detail"])

    async def test_core_caido(self) -> None:
        self.fallo = HAConnectionError("WebSocket no conectado")
        r = await self.t["ha_test_condition"](condition=_CONDICION)
        self.assertEqual(r, {"error": "WebSocket no conectado"})


if __name__ == "__main__":
    unittest.main()
