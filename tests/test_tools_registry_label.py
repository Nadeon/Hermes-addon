"""Tests de las tools de etiquetas (label registry) con un WS simulado."""

from __future__ import annotations

import json
import unittest
from typing import Any

from aiohttp import ClientSession

import hermes.tools.registry_label as label_mod
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


LABELS = [
    {"label_id": "etiqueta_a", "name": "Etiqueta A", "color": "red", "icon": None, "description": None},
    {"label_id": "etiqueta_b", "name": "Etiqueta B", "color": None, "icon": None, "description": None},
]

AREAS = [
    {"area_id": "area_1", "labels": ["etiqueta_a"]},
    {"area_id": "area_2", "labels": ["etiqueta_b"]},
    {"area_id": "area_3", "labels": []},
]
DEVICES = [
    {"id": "dev_1", "labels": ["etiqueta_a"]},
    {"id": "dev_2", "labels": ["etiqueta_a", "etiqueta_b"]},
    {"id": "dev_3", "labels": []},
]
ENTITIES = [
    {"entity_id": "light.uno", "labels": ["etiqueta_a"]},
    {"entity_id": "light.dos", "labels": ["etiqueta_a"]},
    {"entity_id": "sensor.tres", "labels": ["etiqueta_a", "etiqueta_b"]},
    {"entity_id": "sensor.cuatro", "labels": ["etiqueta_b"]},
    {"entity_id": "sensor.cinco", "labels": []},
]
RELATED = {
    "automation": ["automation.a"],
    "script": ["script.s"],
    "scene": ["scene.e"],
    "entity": ["light.uno"],
}


def _rutas_borrado(**cambios: Any) -> dict[str, Any]:
    rutas: dict[str, Any] = {
        "config/label_registry/list": LABELS,
        "config/area_registry/list": AREAS,
        "config/device_registry/list": DEVICES,
        "config/entity_registry/list": ENTITIES,
        "search/related": RELATED,
        "config/label_registry/delete": None,
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
        label_mod.register(mcp, client)
        return mcp.tools, fake


# ── ha_list_labels / ha_create_label ─────────────────────────────────────────


class TestListCreateLabel(_Base):
    async def test_list(self) -> None:
        tools, fake = self._tools({"config/label_registry/list": LABELS})
        out = json.loads(await tools["ha_list_labels"]())
        self.assertEqual(fake.types(), ["config/label_registry/list"])
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["labels"][0]["label_id"], "etiqueta_a")

    async def test_create_color_de_tema(self) -> None:
        tools, fake = self._tools({"config/label_registry/create": {"label_id": "x"}})
        out = json.loads(await tools["ha_create_label"](name="X", color="deep-orange"))
        self.assertEqual(out["label_id"], "x")
        self.assertEqual(
            fake.sent,
            [{"type": "config/label_registry/create", "name": "X", "color": "deep-orange"}],
        )

    async def test_create_color_hex(self) -> None:
        tools, fake = self._tools({"config/label_registry/create": {"label_id": "x"}})
        await tools["ha_create_label"](name="X", color="#1A2b3C")
        self.assertEqual(fake.sent[0]["color"], "#1A2b3C")

    async def test_create_color_invalido_sin_ws(self) -> None:
        for color in ("rojo", "#12345", "#1234567", "1A2B3C", "#GGGGGG", 7):
            with self.subTest(color=color):
                tools, fake = self._tools({})
                out = json.loads(await tools["ha_create_label"](name="X", color=color))
                self.assertEqual(out["error"], "invalid_argument")
                self.assertEqual(out["field"], "color")
                self.assertEqual(fake.sent, [])

    async def test_create_opcionales_solo_si_se_pasan(self) -> None:
        tools, fake = self._tools({"config/label_registry/create": {"label_id": "x"}})
        await tools["ha_create_label"](name="X")
        self.assertEqual(fake.sent[-1], {"type": "config/label_registry/create", "name": "X"})
        await tools["ha_create_label"](name="X", icon="mdi:tag", description="Algo")
        self.assertEqual(
            fake.sent[-1],
            {"type": "config/label_registry/create", "name": "X",
             "icon": "mdi:tag", "description": "Algo"},
        )

    async def test_create_nombre_vacio(self) -> None:
        tools, fake = self._tools({})
        out = json.loads(await tools["ha_create_label"](name=" "))
        self.assertEqual(out["error"], "invalid_argument")
        self.assertEqual(out["field"], "name")
        self.assertEqual(fake.sent, [])


# ── ha_update_label ──────────────────────────────────────────────────────────


class TestUpdateLabel(_Base):
    async def test_preview(self) -> None:
        tools, fake = self._tools({"config/label_registry/list": LABELS})
        out = json.loads(await tools["ha_update_label"]("etiqueta_a", {"color": "blue"}))
        self.assertIn("confirmation_token", out)
        self.assertEqual(out["preview"]["current"]["color"], "red")
        self.assertEqual(out["preview"]["proposed_changes"], {"color": "blue"})
        self.assertNotIn("config/label_registry/update", fake.types())

    async def test_inexistente_not_found(self) -> None:
        tools, _ = self._tools({"config/label_registry/list": LABELS})
        out = json.loads(await tools["ha_update_label"]("fantasma", {"name": "N"}))
        self.assertEqual(out["error"], "not_found")
        self.assertNotIn("confirmation_token", out)

    async def test_lectura_falla(self) -> None:
        tools, _ = self._tools({"config/label_registry/list": HAConnectionError("offline")})
        out = json.loads(await tools["ha_update_label"]("etiqueta_a", {"name": "N"}))
        self.assertEqual(out["error"], "preview_unavailable")
        self.assertNotIn("confirmation_token", out)

    async def test_clave_desconocida(self) -> None:
        tools, fake = self._tools({"config/label_registry/list": LABELS})
        out = json.loads(await tools["ha_update_label"]("etiqueta_a", {"level": 1}))
        self.assertEqual(out["error"], "invalid_argument")
        self.assertEqual(fake.sent, [])

    async def test_color_invalido_en_updates(self) -> None:
        tools, fake = self._tools({"config/label_registry/list": LABELS})
        out = json.loads(await tools["ha_update_label"]("etiqueta_a", {"color": "rojo"}))
        self.assertEqual(out["error"], "invalid_argument")
        self.assertEqual(out["field"], "color")
        self.assertEqual(fake.sent, [])

    async def test_con_token(self) -> None:
        tools, fake = self._tools({
            "config/label_registry/list": LABELS,
            "config/label_registry/update": {"label_id": "etiqueta_a", "color": None},
        })
        token = json.loads(await tools["ha_update_label"]("etiqueta_a", {"color": None}))[
            "confirmation_token"
        ]
        out = json.loads(
            await tools["ha_update_label"]("etiqueta_a", {"color": None}, confirmation_token=token)
        )
        self.assertEqual(out["result"], "ok")
        self.assertEqual(
            fake.sent[-1],
            {"type": "config/label_registry/update", "label_id": "etiqueta_a", "color": None},
        )

    async def test_token_de_otra_etiqueta(self) -> None:
        tools, fake = self._tools({"config/label_registry/list": LABELS})
        token = json.loads(await tools["ha_update_label"]("etiqueta_a", {"name": "N"}))[
            "confirmation_token"
        ]
        out = json.loads(
            await tools["ha_update_label"]("etiqueta_b", {"name": "N"}, confirmation_token=token)
        )
        self.assertIn("error", out)
        self.assertNotIn("config/label_registry/update", fake.types())


# ── ha_delete_label ──────────────────────────────────────────────────────────


class TestDeleteLabel(_Base):
    async def test_preview_por_tipo(self) -> None:
        tools, fake = self._tools(_rutas_borrado())
        out = json.loads(await tools["ha_delete_label"]("etiqueta_a"))
        self.assertIn("confirmation_token", out)
        impact = out["preview"]["impact"]
        asign = impact["assignments_removed"]
        self.assertEqual(asign["areas"], {"count": 1, "ids": ["area_1"], "truncated": False})
        self.assertEqual(asign["devices"]["count"], 2)
        self.assertEqual(asign["devices"]["ids"], ["dev_1", "dev_2"])
        self.assertEqual(asign["entities"]["count"], 3)
        self.assertEqual(asign["entities"]["ids"], ["light.uno", "light.dos", "sensor.tres"])
        refs = impact["references_unresolved"]
        self.assertEqual(refs["automation"]["ids"], ["automation.a"])
        self.assertEqual(refs["script"]["ids"], ["script.s"])
        self.assertEqual(refs["scene"]["ids"], ["scene.e"])
        self.assertNotIn("entity", refs)
        warning = out["preview"]["warning"]
        for trozo in ("1 area", "2 devices", "3 entities", "1 automation", "1 script", "1 scene"):
            self.assertIn(trozo, warning)
        related = [p for p in fake.sent if p["type"] == "search/related"]
        self.assertEqual((related[0]["item_type"], related[0]["item_id"]), ("label", "etiqueta_a"))
        self.assertNotIn("config/label_registry/delete", fake.types())

    async def test_cada_lectura_fallando(self) -> None:
        comandos = (
            "config/label_registry/list",
            "config/area_registry/list",
            "config/device_registry/list",
            "config/entity_registry/list",
            "search/related",
        )
        for comando in comandos:
            for fallo in (HAConnectionError("offline"), "forma rara"):
                with self.subTest(comando=comando, fallo=fallo):
                    tools, fake = self._tools(_rutas_borrado(**{comando: fallo}))
                    out = json.loads(await tools["ha_delete_label"]("etiqueta_a"))
                    self.assertEqual(out["error"], "preview_unavailable")
                    self.assertNotIn("confirmation_token", out)
                    self.assertNotIn("config/label_registry/delete", fake.types())

    async def test_labels_con_forma_rara(self) -> None:
        dispositivos = [{"id": "dev_1", "labels": "etiqueta_a"}]
        tools, _ = self._tools(_rutas_borrado(**{"config/device_registry/list": dispositivos}))
        out = json.loads(await tools["ha_delete_label"]("etiqueta_a"))
        self.assertEqual(out["error"], "preview_unavailable")

    async def test_sin_uso_recuentos_a_cero_y_token(self) -> None:
        etiquetas = LABELS + [{"label_id": "sin_uso", "name": "Sin uso"}]
        tools, _ = self._tools(_rutas_borrado(**{
            "config/label_registry/list": etiquetas,
            "search/related": {},
        }))
        out = json.loads(await tools["ha_delete_label"]("sin_uso"))
        self.assertIn("confirmation_token", out)
        impact = out["preview"]["impact"]
        for tipo in ("areas", "devices", "entities"):
            self.assertEqual(impact["assignments_removed"][tipo]["count"], 0)
        for tipo in ("automation", "script", "scene"):
            self.assertEqual(impact["references_unresolved"][tipo]["count"], 0)

    async def test_con_token_borra(self) -> None:
        tools, fake = self._tools(_rutas_borrado())
        token = json.loads(await tools["ha_delete_label"]("etiqueta_a"))["confirmation_token"]
        out = json.loads(await tools["ha_delete_label"]("etiqueta_a", confirmation_token=token))
        self.assertEqual(out, {"result": "ok"})
        self.assertEqual(
            fake.sent[-1], {"type": "config/label_registry/delete", "label_id": "etiqueta_a"}
        )

    async def test_token_de_otra_etiqueta(self) -> None:
        tools, fake = self._tools(_rutas_borrado())
        token = json.loads(await tools["ha_delete_label"]("etiqueta_a"))["confirmation_token"]
        out = json.loads(await tools["ha_delete_label"]("etiqueta_b", confirmation_token=token))
        self.assertIn("error", out)
        self.assertNotIn("config/label_registry/delete", fake.types())

    async def test_inexistente(self) -> None:
        tools, _ = self._tools(_rutas_borrado())
        out = json.loads(await tools["ha_delete_label"]("fantasma"))
        self.assertEqual(out["error"], "not_found")
        self.assertNotIn("confirmation_token", out)


if __name__ == "__main__":
    unittest.main()
