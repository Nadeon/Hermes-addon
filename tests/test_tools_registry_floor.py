"""Tests de las tools de plantas (floor registry) con un WS simulado.

El fake responde según el `type` del comando y apunta todo lo enviado: así se
puede comprobar no solo qué devuelve cada tool, sino también que la validación
corta ANTES de hablar con Home Assistant y que sin token no se borra nada.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from aiohttp import ClientSession

import hermes.tools.registry_floor as floor_mod
from hermes.ha import HAConnectionError
from tests._ha_fixture import make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


class FakeWS:
    """WS por `type`: un valor, una excepción o un callable(payload)."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.sent: list[dict] = []

    async def __call__(self, payload, timeout_seconds=30):
        self.sent.append(dict(payload))
        respuesta = self.routes.get(payload["type"], KeyError(payload["type"]))
        if isinstance(respuesta, BaseException):
            raise respuesta
        if callable(respuesta):
            return respuesta(payload)
        return respuesta

    def types(self) -> list[str]:
        return [p["type"] for p in self.sent]


FLOORS = [
    {"floor_id": "planta_a", "name": "Planta A", "level": 0, "icon": None, "aliases": []},
    {"floor_id": "planta_b", "name": "Planta B", "level": 1, "icon": None, "aliases": []},
]


def _areas(n_en_a: int, n_en_b: int = 1) -> list[dict]:
    areas = [
        {"area_id": f"area_a{i}", "name": f"Area A{i}", "floor_id": "planta_a", "labels": []}
        for i in range(n_en_a)
    ]
    areas += [
        {"area_id": f"area_b{i}", "name": f"Area B{i}", "floor_id": "planta_b", "labels": []}
        for i in range(n_en_b)
    ]
    return areas


def _rutas_borrado(**cambios: Any) -> dict[str, Any]:
    rutas: dict[str, Any] = {
        "config/floor_registry/list": FLOORS,
        "config/area_registry/list": _areas(2),
        "search/related": {"automation": ["automation.a"], "area": ["area_a0", "area_a1"]},
        "config/floor_registry/delete": None,
    }
    rutas.update(cambios)
    return rutas


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def _tools(self, routes: dict[str, Any]) -> tuple[dict, FakeWS]:
        client = make_ready_client(self.session, {})
        fake = FakeWS(routes)
        client.ws_send = fake  # type: ignore[method-assign]
        mcp = DummyMCP()
        floor_mod.register(mcp, client)
        return mcp.tools, fake


# ── ha_list_floors / ha_create_floor ─────────────────────────────────────────


class TestListCreateFloor(_Base):
    async def test_list(self) -> None:
        tools, fake = self._tools({"config/floor_registry/list": FLOORS})
        out = json.loads(await tools["ha_list_floors"]())
        self.assertEqual(fake.types(), ["config/floor_registry/list"])
        self.assertEqual(out["count"], 2)
        self.assertEqual([f["floor_id"] for f in out["floors"]], ["planta_a", "planta_b"])

    async def test_list_error(self) -> None:
        tools, _ = self._tools({"config/floor_registry/list": HAConnectionError("offline")})
        out = json.loads(await tools["ha_list_floors"]())
        self.assertIn("error", out)

    async def test_create_limpia_aliases_y_sin_token(self) -> None:
        creada = {"floor_id": "planta_baja", "name": "Planta baja", "level": 0, "aliases": ["pb"]}
        tools, fake = self._tools({"config/floor_registry/create": creada})
        out = json.loads(
            await tools["ha_create_floor"](name="Planta baja", level=0, aliases=["pb", " "])
        )
        self.assertEqual(out["floor_id"], "planta_baja")
        self.assertNotIn("confirmation_token", out)
        self.assertEqual(
            fake.sent,
            [{"type": "config/floor_registry/create", "name": "Planta baja",
              "level": 0, "aliases": ["pb"]}],
        )

    async def test_create_solo_campos_pasados(self) -> None:
        tools, fake = self._tools({"config/floor_registry/create": {"floor_id": "x"}})
        await tools["ha_create_floor"](name="X")
        self.assertEqual(fake.sent, [{"type": "config/floor_registry/create", "name": "X"}])

    async def test_create_duplicado_devuelve_error_sin_reintentar(self) -> None:
        tools, fake = self._tools({
            "config/floor_registry/create": HAConnectionError(
                "The name Planta A is already in use", code="invalid_info"
            )
        })
        out = json.loads(await tools["ha_create_floor"](name="Planta A"))
        self.assertIn("already in use", out["error"])
        self.assertEqual(len(fake.sent), 1)

    async def test_create_validacion_sin_ws(self) -> None:
        casos = [
            ({"name": ""}, "name"),
            ({"name": "   "}, "name"),
            ({"name": "X", "level": True}, "level"),
            ({"name": "X", "level": "1"}, "level"),
            ({"name": "X", "aliases": "x"}, "aliases"),
            ({"name": "X", "aliases": ["ok", 3]}, "aliases"),
            ({"name": "X", "icon": 5}, "icon"),
        ]
        for kwargs, campo in casos:
            with self.subTest(kwargs=kwargs):
                tools, fake = self._tools({})
                out = json.loads(await tools["ha_create_floor"](**kwargs))
                self.assertEqual(out["error"], "invalid_argument")
                self.assertEqual(out["field"], campo)
                self.assertEqual(fake.sent, [])


# ── ha_update_floor ──────────────────────────────────────────────────────────


class TestUpdateFloor(_Base):
    async def test_preview_con_current_y_token(self) -> None:
        tools, fake = self._tools({"config/floor_registry/list": FLOORS})
        out = json.loads(await tools["ha_update_floor"]("planta_a", {"name": "Nueva"}))
        self.assertIn("confirmation_token", out)
        self.assertEqual(out["preview"]["current"]["name"], "Planta A")
        self.assertEqual(out["preview"]["proposed_changes"], {"name": "Nueva"})
        self.assertNotIn("config/floor_registry/update", fake.types())

    async def test_inexistente_not_found_sin_token(self) -> None:
        tools, _ = self._tools({"config/floor_registry/list": FLOORS})
        out = json.loads(await tools["ha_update_floor"]("fantasma", {"name": "N"}))
        self.assertEqual(out["error"], "not_found")
        self.assertNotIn("confirmation_token", out)

    async def test_lectura_falla_preview_unavailable(self) -> None:
        tools, _ = self._tools({"config/floor_registry/list": HAConnectionError("offline")})
        out = json.loads(await tools["ha_update_floor"]("planta_a", {"name": "N"}))
        self.assertEqual(out["error"], "preview_unavailable")
        self.assertNotIn("confirmation_token", out)

    async def test_lectura_con_forma_rara_preview_unavailable(self) -> None:
        tools, _ = self._tools({"config/floor_registry/list": {"no": "lista"}})
        out = json.loads(await tools["ha_update_floor"]("planta_a", {"name": "N"}))
        self.assertEqual(out["error"], "preview_unavailable")
        self.assertNotIn("confirmation_token", out)

    async def test_clave_desconocida(self) -> None:
        tools, fake = self._tools({"config/floor_registry/list": FLOORS})
        out = json.loads(await tools["ha_update_floor"]("planta_a", {"color": "red"}))
        self.assertEqual(out["error"], "invalid_argument")
        self.assertEqual(out["field"], "color")
        self.assertEqual(fake.sent, [])

    async def test_updates_vacio(self) -> None:
        tools, fake = self._tools({})
        out = json.loads(await tools["ha_update_floor"]("planta_a", {}))
        self.assertEqual(out["error"], "updates is empty")
        self.assertEqual(fake.sent, [])

    async def test_identificador_invalido(self) -> None:
        tools, fake = self._tools({})
        out = json.loads(await tools["ha_update_floor"]("../x", {"name": "N"}))
        self.assertEqual(out["error"], "invalid_identifier")
        self.assertEqual(fake.sent, [])

    async def test_con_token_envia_solo_lo_pedido(self) -> None:
        tools, fake = self._tools({
            "config/floor_registry/list": FLOORS,
            "config/floor_registry/update": {"floor_id": "planta_a", "name": "Planta A", "level": 2},
        })
        token = json.loads(await tools["ha_update_floor"]("planta_a", {"level": 2}))[
            "confirmation_token"
        ]
        out = json.loads(
            await tools["ha_update_floor"]("planta_a", {"level": 2}, confirmation_token=token)
        )
        self.assertEqual(out["result"], "ok")
        self.assertEqual(out["level"], 2)
        self.assertEqual(
            fake.sent[-1],
            {"type": "config/floor_registry/update", "floor_id": "planta_a", "level": 2},
        )

    async def test_token_de_otra_planta_rechazado(self) -> None:
        tools, fake = self._tools({
            "config/floor_registry/list": FLOORS,
            "config/floor_registry/update": {},
        })
        token = json.loads(await tools["ha_update_floor"]("planta_a", {"name": "N"}))[
            "confirmation_token"
        ]
        out = json.loads(
            await tools["ha_update_floor"]("planta_b", {"name": "N"}, confirmation_token=token)
        )
        self.assertIn("error", out)
        self.assertNotIn("config/floor_registry/update", fake.types())


# ── ha_delete_floor ──────────────────────────────────────────────────────────


class TestDeleteFloor(_Base):
    async def test_preview_veraz(self) -> None:
        tools, fake = self._tools(_rutas_borrado())
        out = json.loads(await tools["ha_delete_floor"]("planta_a"))
        self.assertIn("confirmation_token", out)
        preview = out["preview"]
        self.assertEqual(preview["current"]["floor_id"], "planta_a")
        areas = preview["impact"]["assignments_removed"]["areas"]
        self.assertEqual(areas, {"count": 2, "ids": ["area_a0", "area_a1"], "truncated": False})
        refs = preview["impact"]["references_unresolved"]
        self.assertEqual(refs["automation"]["ids"], ["automation.a"])
        self.assertEqual(refs["automation"]["count"], 1)
        self.assertEqual(refs["script"]["count"], 0)
        self.assertEqual(refs["scene"]["count"], 0)
        # Las áreas que devuelve search/related no se cuelan como referencias.
        self.assertNotIn("area", refs)
        self.assertIn("2 areas", preview["warning"])
        self.assertIn("1 automation", preview["warning"])
        self.assertIn("0 scripts", preview["warning"])
        self.assertIn("0 scenes", preview["warning"])
        related = [p for p in fake.sent if p["type"] == "search/related"]
        self.assertEqual(related[0]["item_type"], "floor")
        self.assertEqual(related[0]["item_id"], "planta_a")
        self.assertNotIn("config/floor_registry/delete", fake.types())

    async def test_cada_lectura_fallando_preview_unavailable(self) -> None:
        for comando in ("config/floor_registry/list", "config/area_registry/list", "search/related"):
            for fallo in (HAConnectionError("offline"), "no es una lista ni un dict"):
                with self.subTest(comando=comando, fallo=fallo):
                    tools, fake = self._tools(_rutas_borrado(**{comando: fallo}))
                    out = json.loads(await tools["ha_delete_floor"]("planta_a"))
                    self.assertEqual(out["error"], "preview_unavailable")
                    self.assertIn("detail", out)
                    self.assertNotIn("confirmation_token", out)
                    self.assertNotIn("config/floor_registry/delete", fake.types())

    async def test_areas_que_no_son_lista(self) -> None:
        tools, _ = self._tools(_rutas_borrado(**{"config/area_registry/list": {"a": 1}}))
        out = json.loads(await tools["ha_delete_floor"]("planta_a"))
        self.assertEqual(out["error"], "preview_unavailable")

    async def test_related_con_tipo_no_lista(self) -> None:
        tools, _ = self._tools(_rutas_borrado(**{"search/related": {"automation": "x"}}))
        out = json.loads(await tools["ha_delete_floor"]("planta_a"))
        self.assertEqual(out["error"], "preview_unavailable")

    async def test_acota_a_50(self) -> None:
        tools, _ = self._tools(_rutas_borrado(**{"config/area_registry/list": _areas(60)}))
        out = json.loads(await tools["ha_delete_floor"]("planta_a"))
        areas = out["preview"]["impact"]["assignments_removed"]["areas"]
        self.assertEqual(areas["count"], 60)
        self.assertEqual(len(areas["ids"]), 50)
        self.assertTrue(areas["truncated"])

    async def test_con_token_borra(self) -> None:
        tools, fake = self._tools(_rutas_borrado())
        token = json.loads(await tools["ha_delete_floor"]("planta_a"))["confirmation_token"]
        out = json.loads(await tools["ha_delete_floor"]("planta_a", confirmation_token=token))
        self.assertEqual(out, {"result": "ok"})
        self.assertEqual(
            fake.sent[-1], {"type": "config/floor_registry/delete", "floor_id": "planta_a"}
        )

    async def test_token_de_otra_planta_rechazado(self) -> None:
        tools, fake = self._tools(_rutas_borrado())
        token = json.loads(await tools["ha_delete_floor"]("planta_a"))["confirmation_token"]
        out = json.loads(await tools["ha_delete_floor"]("planta_b", confirmation_token=token))
        self.assertIn("error", out)
        self.assertNotIn("config/floor_registry/delete", fake.types())

    async def test_token_de_update_rechazado(self) -> None:
        tools, fake = self._tools(_rutas_borrado())
        token = json.loads(await tools["ha_update_floor"]("planta_a", {"name": "N"}))[
            "confirmation_token"
        ]
        out = json.loads(await tools["ha_delete_floor"]("planta_a", confirmation_token=token))
        self.assertIn("error", out)
        self.assertNotIn("config/floor_registry/delete", fake.types())

    async def test_inexistente_not_found(self) -> None:
        tools, fake = self._tools(_rutas_borrado())
        out = json.loads(await tools["ha_delete_floor"]("fantasma"))
        self.assertEqual(out["error"], "not_found")
        self.assertNotIn("confirmation_token", out)
        self.assertNotIn("config/floor_registry/delete", fake.types())

    async def test_error_de_ha_al_borrar(self) -> None:
        tools, _ = self._tools(_rutas_borrado())
        token = json.loads(await tools["ha_delete_floor"]("planta_a"))["confirmation_token"]
        tools2, _ = self._tools(
            _rutas_borrado(**{"config/floor_registry/delete": HAConnectionError("boom")})
        )
        out = json.loads(await tools2["ha_delete_floor"]("planta_a", confirmation_token=token))
        self.assertIn("boom", out["error"])


if __name__ == "__main__":
    unittest.main()
