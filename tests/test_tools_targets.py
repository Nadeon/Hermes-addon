"""Targets y triggers/condiciones/acciones por propósito (spec 017, tramo C;
T028).

`_validar_target`, `ha_resolve_target`, `ha_explain_target` y las tres de
lista por target con Home Assistant simulado. Datos ficticios
(`light.salon`, el área `salon`, `<device_id>` de prueba).

Controles negativos del cierre del tramo (T037), vistos en rojo y
restaurados:
(2) `_validar_target` que acepta claves desconocidas → caen
`TestValidarTarget.test_clave_desconocida` y
`TestResolver.test_target_invalido_sin_llamar`;
(3) `unknown_command` devuelto como error opaco (sin traducir) → cae
`TestListasPorTarget.test_version_no_soportada`.
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from packaging.version import Version

import hermes.tools.targets as mod
from hermes.ha import HAConnectionError

_DEVICE = "0123456789abcdef0123456789abcdef"


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class TestValidarTarget(unittest.TestCase):
    def test_validos(self) -> None:
        for target in (
            {"entity_id": "light.salon"},
            {"entity_id": ["light.salon", "light.cocina"]},
            {"area_id": "salon", "exclude": {"label_id": "nocturna"}},
            {"device_id": [_DEVICE], "floor_id": "planta_baja", "label_id": ["x"]},
            {"area_id": "salon", "exclude": {"entity_id": ["light.salon"], "area_id": "b"}},
        ):
            with self.subTest(target=target):
                self.assertIsNone(mod._validar_target(target))

    def test_clave_desconocida(self) -> None:
        r = mod._validar_target({"entity_id": "light.salon", "zona": "x"})
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "target.zona"))
        self.assertIn("zona", r["detail"])
        r = mod._validar_target({"area_id": "salon", "exclude": {"zona": "x"}})
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "target.exclude.zona"))
        # `exclude` dentro de `exclude` tampoco.
        r = mod._validar_target({"area_id": "salon", "exclude": {"exclude": {"area_id": "x"}}})
        self.assertEqual(r["field"], "target.exclude.exclude")

    def test_valores_invalidos(self) -> None:
        for target, campo in (
            ({"entity_id": ""}, "target.entity_id"),
            ({"entity_id": "  "}, "target.entity_id"),
            ({"entity_id": []}, "target.entity_id"),
            ({"entity_id": ["light.salon", ""]}, "target.entity_id"),
            ({"entity_id": 3}, "target.entity_id"),
            ({"area_id": ["salon", None]}, "target.area_id"),
            ({"area_id": "salon", "exclude": "x"}, "target.exclude"),
            ({"area_id": "salon", "exclude": {}}, "target.exclude"),
            ({"area_id": "salon", "exclude": {"label_id": []}}, "target.exclude.label_id"),
        ):
            with self.subTest(target=target):
                r = mod._validar_target(target)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", campo))

    def test_vacio_o_solo_exclude(self) -> None:
        for target in ({}, None, "light.salon", ["light.salon"],
                       {"exclude": {"entity_id": "light.salon"}}):
            with self.subTest(target=target):
                r = mod._validar_target(target)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "target"))


class _Base(unittest.IsolatedAsyncioTestCase):
    max_bytes = 131_072

    async def asyncSetUp(self) -> None:
        self.respuestas: dict[str, Any] = {
            "extract_from_target": {
                "referenced_entities": ["light.salon", "light.cocina", "switch.b"],
                "referenced_devices": [_DEVICE],
                "referenced_areas": ["salon"],
                "missing_devices": [],
                "missing_areas": ["no_existe", "a_tampoco"],
                "missing_floors": [],
                "missing_labels": ["z"],
            },
            "explain_target": {
                "includes": [{"type": "area", "id": "salon",
                              "entities": ["light.cocina", "light.salon"],
                              "referenced_areas": [], "referenced_devices": [_DEVICE]}],
                "excludes": [{"type": "label", "id": "nocturna",
                              "removed": [{"type": "entity", "id": "light.salon",
                                           "entities": ["light.salon"]}]}],
            },
            "get_triggers_for_target": ["light.turned_on", "light.turned_off", "light.brightness_changed"],
            "get_conditions_for_target": ["light.is_on", "light.is_off"],
            "get_services_for_target": ["light.turn_on", "homeassistant.turn_off", "light.toggle"],
        }
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
        return r


_TARGET = {"area_id": "salon", "exclude": {"label_id": "nocturna"}}


class TestResolver(_Base):
    async def test_envia_y_ordena(self) -> None:
        r = await self.t["ha_resolve_target"](target=_TARGET)
        self.assertEqual(self.enviados, [{
            "type": "extract_from_target", "target": _TARGET,
            "expand_group": False, "primary_entities_only": True}])
        self.assertEqual(r["entities"], ["light.cocina", "light.salon", "switch.b"])
        self.assertEqual(r["devices"], [_DEVICE])
        self.assertEqual(r["areas"], ["salon"])
        self.assertEqual(r["missing"], {"devices": [], "areas": ["a_tampoco", "no_existe"],
                                        "floors": [], "labels": ["z"]})
        self.assertEqual(r["counts"], {"entities": 3, "devices": 1, "areas": 1})
        self.assertIs(r["truncated"], False)

    async def test_argumentos(self) -> None:
        await self.t["ha_resolve_target"](target=_TARGET, expand_group=True,
                                          primary_entities_only=False)
        self.assertEqual((self.enviados[0]["expand_group"],
                          self.enviados[0]["primary_entities_only"]), (True, False))
        r = await self.t["ha_resolve_target"](target=_TARGET, expand_group="si")
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "expand_group"))

    async def test_target_invalido_sin_llamar(self) -> None:
        r = await self.t["ha_resolve_target"](target={"zona": "salon"})
        self.assertEqual(r["error"], "invalid_argument")
        r = await self.t["ha_resolve_target"](target={"exclude": {"area_id": "salon"}})
        self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()

    async def test_invalid_format_de_ha(self) -> None:
        self.respuestas["extract_from_target"] = HAConnectionError(
            "Entity ID salon is an invalid entity ID", code="invalid_format")
        r = await self.t["ha_resolve_target"](target={"entity_id": "salon"})
        self.assertEqual((r["error"], r["field"], r["ha_code"]),
                         ("invalid_argument", "target", "invalid_format"))

    async def test_respuesta_inesperada(self) -> None:
        self.respuestas["extract_from_target"] = ["x"]
        r = await self.t["ha_resolve_target"](target=_TARGET)
        self.assertEqual(r["error"], "unexpected_response")


class TestExplicar(_Base):
    async def test_envia_con_sus_valores_por_defecto(self) -> None:
        r = await self.t["ha_explain_target"](target=_TARGET)
        self.assertEqual(self.enviados, [{
            "type": "explain_target", "target": _TARGET,
            "expand_group": True, "primary_entities_only": True}])
        self.assertEqual(r["includes"], self.respuestas["explain_target"]["includes"])
        self.assertEqual(r["excludes"], self.respuestas["explain_target"]["excludes"])
        self.assertIs(r["truncated"], False)

    async def test_target_invalido_sin_llamar(self) -> None:
        r = await self.t["ha_explain_target"](target={})
        self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()


class TestListasPorTarget(_Base):
    _TRES = {
        "ha_list_triggers_for_target": "get_triggers_for_target",
        "ha_list_conditions_for_target": "get_conditions_for_target",
        "ha_list_actions_for_target": "get_services_for_target",
    }

    async def test_envian_su_comando_y_ordenan(self) -> None:
        for tool, comando in self._TRES.items():
            with self.subTest(tool=tool):
                self.enviados.clear()
                r = await self.t[tool](target={"entity_id": "light.salon"})
                self.assertEqual(self.enviados, [{
                    "type": comando, "target": {"entity_id": "light.salon"},
                    "expand_group": True}])
                self.assertEqual(r["items"], sorted(self.respuestas[comando]))
                self.assertEqual((r["count"], r["truncated"]),
                                 (len(self.respuestas[comando]), False))
        await self.t["ha_list_triggers_for_target"](
            target={"entity_id": "light.salon"}, expand_group=False)
        self.assertIs(self.enviados[-1]["expand_group"], False)

    async def test_target_invalido_sin_llamar(self) -> None:
        for tool in self._TRES:
            with self.subTest(tool=tool):
                r = await self.t[tool](target={"entity_id": "light.salon", "otra": "x"})
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "target.otra"))
        self.ha.ws_send.assert_not_awaited()

    async def test_version_no_soportada(self) -> None:
        for tool, comando in self._TRES.items():
            with self.subTest(tool=tool):
                self.respuestas[comando] = HAConnectionError("Unknown command.",
                                                             code="unknown_command")
                with patch.object(mod, "ha_core_version",
                                  AsyncMock(return_value=Version("2025.1.0"))):
                    r = await self.t[tool](target={"entity_id": "light.salon"})
                self.assertEqual((r["error"], r["current"]),
                                 ("ha_version_unsupported", "2025.1.0"))
        self.respuestas["explain_target"] = HAConnectionError("x", code="unknown_command")
        with patch.object(mod, "ha_core_version", AsyncMock(return_value=None)):
            r = await self.t["ha_explain_target"](target=_TARGET)
        self.assertEqual((r["error"], r["current"]), ("ha_version_unsupported", None))

    async def test_respuesta_que_no_es_lista(self) -> None:
        self.respuestas["get_services_for_target"] = {"a": 1}
        r = await self.t["ha_list_actions_for_target"](target={"entity_id": "light.salon"})
        self.assertEqual(r["error"], "unexpected_response")

    async def test_conexion(self) -> None:
        self.respuestas["get_triggers_for_target"] = HAConnectionError("WS cerrada")
        r = await self.t["ha_list_triggers_for_target"](target={"entity_id": "light.salon"})
        self.assertEqual(r, {"error": "WS cerrada"})


class TestRecorte(_Base):
    max_bytes = 2_000

    async def test_listas_por_target(self) -> None:
        self.respuestas["get_services_for_target"] = [f"dominio.accion_{n:03d}" for n in range(300)]
        r = await self.t["ha_list_actions_for_target"](target={"entity_id": "light.salon"})
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False).encode()), self.max_bytes)
        self.assertIs(r["truncated"], True)
        self.assertEqual(r["count"], len(r["items"]))
        self.assertEqual(r["_response_limit"]["total"], 300)

    async def test_resolver_con_recuentos(self) -> None:
        self.respuestas["extract_from_target"]["referenced_entities"] = [
            f"light.luz_{n:03d}" for n in range(300)]
        r = await self.t["ha_resolve_target"](target=_TARGET)
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False).encode()), self.max_bytes)
        self.assertIs(r["truncated"], True)
        self.assertLess(len(r["entities"]), 300)
        self.assertEqual(r["counts"]["entities"], 300)
        self.assertEqual(r["_response_limit"]["total"], 300)

    async def test_explicar(self) -> None:
        self.respuestas["explain_target"]["includes"] = [
            {"type": "entity", "id": f"light.luz_{n:03d}", "entities": [f"light.luz_{n:03d}"],
             "referenced_areas": [], "referenced_devices": []} for n in range(100)]
        r = await self.t["ha_explain_target"](target=_TARGET)
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False).encode()), self.max_bytes)
        self.assertIs(r["truncated"], True)
        self.assertEqual(r["_response_limit"]["total"], 100)


if __name__ == "__main__":
    unittest.main()
