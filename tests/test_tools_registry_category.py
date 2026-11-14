"""Tests de las tools de categorías (category registry) con un WS simulado.

Las categorías viven en un `scope`: la misma `category_id` puede existir en dos
scopes distintos y son cosas diferentes. Varios tests comprueban justo eso,
porque confundir scopes daría una vista previa falsa o un token reutilizable.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from aiohttp import ClientSession

import hermes.tools.registry_category as cat_mod
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


CAT_ID = "01JCATEGORIAPRUEBA0000000A"


def _categorias(payload: dict) -> list[dict]:
    # Misma id en dos scopes: cada scope tiene su propio registro.
    if payload.get("scope") in ("automation", "script"):
        return [{"category_id": CAT_ID, "name": f"Cat {payload['scope']}", "icon": None}]
    return []


ENTITIES = [
    {"entity_id": f"automation.a{i}", "categories": {"automation": CAT_ID}} for i in range(4)
] + [
    {"entity_id": "script.s1", "categories": {"script": CAT_ID}},
    {"entity_id": "automation.sin", "categories": {}},
    {"entity_id": "light.sin_campo"},
]


def _rutas(**cambios: Any) -> dict[str, Any]:
    rutas: dict[str, Any] = {
        "config/category_registry/list": _categorias,
        "config/entity_registry/list": ENTITIES,
        "config/category_registry/delete": None,
        "config/category_registry/update": {"category_id": CAT_ID, "name": "N"},
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
        cat_mod.register(mcp, client)
        return mcp.tools, fake


# ── ha_list_categories / ha_create_category ──────────────────────────────────


class TestListCreateCategory(_Base):
    async def test_list_envia_scope(self) -> None:
        tools, fake = self._tools(_rutas())
        out = json.loads(await tools["ha_list_categories"](scope="automation"))
        self.assertEqual(fake.sent, [{"type": "config/category_registry/list", "scope": "automation"}])
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["scope"], "automation")
        self.assertEqual(out["categories"][0]["category_id"], CAT_ID)

    async def test_scope_invalido_sin_ws(self) -> None:
        for herramienta, kwargs in (
            ("ha_list_categories", {"scope": "dashboard"}),
            ("ha_create_category", {"scope": "dashboard", "name": "X"}),
            ("ha_update_category", {"scope": "dashboard", "category_id": CAT_ID, "updates": {"name": "N"}}),
            ("ha_delete_category", {"scope": "dashboard", "category_id": CAT_ID}),
        ):
            with self.subTest(herramienta=herramienta):
                tools, fake = self._tools(_rutas())
                out = json.loads(await tools[herramienta](**kwargs))
                self.assertEqual(out["error"], "invalid_argument")
                self.assertEqual(out["field"], "scope")
                for valido in ("automation", "script", "scene", "helpers"):
                    self.assertIn(valido, out["detail"])
                self.assertEqual(fake.sent, [])

    async def test_create(self) -> None:
        tools, fake = self._tools({"config/category_registry/create": {"category_id": "nueva", "name": "Riego"}})
        out = json.loads(await tools["ha_create_category"](scope="script", name="Riego"))
        self.assertEqual(out["category_id"], "nueva")
        self.assertNotIn("confirmation_token", out)
        self.assertEqual(
            fake.sent, [{"type": "config/category_registry/create", "scope": "script", "name": "Riego"}]
        )

    async def test_create_nombre_vacio(self) -> None:
        tools, fake = self._tools({})
        out = json.loads(await tools["ha_create_category"](scope="script", name=""))
        self.assertEqual(out["error"], "invalid_argument")
        self.assertEqual(out["field"], "name")
        self.assertEqual(fake.sent, [])


# ── ha_update_category ───────────────────────────────────────────────────────


class TestUpdateCategory(_Base):
    async def test_preview(self) -> None:
        tools, fake = self._tools(_rutas())
        out = json.loads(await tools["ha_update_category"]("automation", CAT_ID, {"name": "N"}))
        self.assertIn("confirmation_token", out)
        self.assertEqual(out["preview"]["current"]["name"], "Cat automation")
        self.assertEqual(out["preview"]["scope"], "automation")
        self.assertEqual(out["preview"]["proposed_changes"], {"name": "N"})
        self.assertNotIn("config/category_registry/update", fake.types())

    async def test_inexistente_en_ese_scope(self) -> None:
        tools, _ = self._tools(_rutas())
        out = json.loads(await tools["ha_update_category"]("scene", CAT_ID, {"name": "N"}))
        self.assertEqual(out["error"], "not_found")
        self.assertNotIn("confirmation_token", out)

    async def test_lectura_falla(self) -> None:
        tools, _ = self._tools(_rutas(**{"config/category_registry/list": HAConnectionError("x")}))
        out = json.loads(await tools["ha_update_category"]("automation", CAT_ID, {"name": "N"}))
        self.assertEqual(out["error"], "preview_unavailable")
        self.assertNotIn("confirmation_token", out)

    async def test_color_no_admitido(self) -> None:
        tools, fake = self._tools(_rutas())
        out = json.loads(await tools["ha_update_category"]("automation", CAT_ID, {"color": "red"}))
        self.assertEqual(out["error"], "invalid_argument")
        self.assertEqual(out["field"], "color")
        self.assertEqual(fake.sent, [])

    async def test_con_token(self) -> None:
        tools, fake = self._tools(_rutas())
        token = json.loads(await tools["ha_update_category"]("automation", CAT_ID, {"name": "N"}))[
            "confirmation_token"
        ]
        out = json.loads(
            await tools["ha_update_category"]("automation", CAT_ID, {"name": "N"}, confirmation_token=token)
        )
        self.assertEqual(out["result"], "ok")
        self.assertEqual(
            fake.sent[-1],
            {"type": "config/category_registry/update", "scope": "automation",
             "category_id": CAT_ID, "name": "N"},
        )

    async def test_token_atado_al_scope(self) -> None:
        tools, fake = self._tools(_rutas())
        token = json.loads(await tools["ha_update_category"]("automation", CAT_ID, {"name": "N"}))[
            "confirmation_token"
        ]
        out = json.loads(
            await tools["ha_update_category"]("script", CAT_ID, {"name": "N"}, confirmation_token=token)
        )
        self.assertIn("error", out)
        self.assertNotIn("config/category_registry/update", fake.types())


# ── ha_delete_category ───────────────────────────────────────────────────────


class TestDeleteCategory(_Base):
    async def test_preview_solo_entidades_del_scope(self) -> None:
        tools, fake = self._tools(_rutas())
        out = json.loads(await tools["ha_delete_category"]("automation", CAT_ID))
        self.assertIn("confirmation_token", out)
        impact = out["preview"]["impact"]
        ents = impact["assignments_removed"]["entities"]
        self.assertEqual(ents["count"], 4)
        self.assertEqual(ents["ids"], [f"automation.a{i}" for i in range(4)])
        self.assertNotIn("script.s1", ents["ids"])
        self.assertNotIn("references_unresolved", impact)
        self.assertIn("4 entities", out["preview"]["warning"])
        self.assertNotIn("config/category_registry/delete", fake.types())

    async def test_lectura_fallida(self) -> None:
        for comando in ("config/category_registry/list", "config/entity_registry/list"):
            for fallo in (HAConnectionError("offline"), "forma rara"):
                with self.subTest(comando=comando, fallo=fallo):
                    tools, fake = self._tools(_rutas(**{comando: fallo}))
                    out = json.loads(await tools["ha_delete_category"]("automation", CAT_ID))
                    self.assertEqual(out["error"], "preview_unavailable")
                    self.assertNotIn("confirmation_token", out)
                    self.assertNotIn("config/category_registry/delete", fake.types())

    async def test_categories_con_forma_rara(self) -> None:
        entidades = [{"entity_id": "automation.x", "categories": ["no", "dict"]}]
        tools, _ = self._tools(_rutas(**{"config/entity_registry/list": entidades}))
        out = json.loads(await tools["ha_delete_category"]("automation", CAT_ID))
        self.assertEqual(out["error"], "preview_unavailable")

    async def test_con_token_borra_con_scope(self) -> None:
        tools, fake = self._tools(_rutas())
        token = json.loads(await tools["ha_delete_category"]("automation", CAT_ID))["confirmation_token"]
        out = json.loads(
            await tools["ha_delete_category"]("automation", CAT_ID, confirmation_token=token)
        )
        self.assertEqual(out, {"result": "ok"})
        self.assertEqual(
            fake.sent[-1],
            {"type": "config/category_registry/delete", "scope": "automation", "category_id": CAT_ID},
        )

    async def test_token_de_otro_scope_rechazado(self) -> None:
        tools, fake = self._tools(_rutas())
        token = json.loads(await tools["ha_delete_category"]("automation", CAT_ID))["confirmation_token"]
        out = json.loads(
            await tools["ha_delete_category"]("script", CAT_ID, confirmation_token=token)
        )
        self.assertIn("error", out)
        self.assertNotIn("config/category_registry/delete", fake.types())

    async def test_inexistente(self) -> None:
        tools, _ = self._tools(_rutas())
        out = json.loads(await tools["ha_delete_category"]("scene", CAT_ID))
        self.assertEqual(out["error"], "not_found")
        self.assertNotIn("confirmation_token", out)


if __name__ == "__main__":
    unittest.main()
