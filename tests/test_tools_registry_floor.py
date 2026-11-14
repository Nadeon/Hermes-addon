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


# Forma REAL de `search/related` para una planta con áreas (HA 2026.11.1,
# `components/search/__init__.py`, `_async_search_floor`): además de lo que
# usa `floor_id`, por cada área llama a `_async_search_area(entry_point=False)`
# y añade lo que apunta al área, a sus dispositivos y a sus entidades, las
# escenas que contienen esas entidades y las entidades `automation.*` que
# están asignadas al área. Un mock que solo devolviera «lo que apunta a la
# planta» es lo que escondió el fallo A-1 de la revisión de 1.1.0.
RELATED_PLANTA = {
    "area": ["area_a0", "area_a1"],
    "device": ["dev_cocina"],
    "entity": ["light.cocina", "light.salon", "automation.asignada_al_area"],
    "config_entry": ["entry_luces"],
    "automation": [
        "automation.luz_cocina",
        "automation.luces_planta",
        "automation.area_salon",
        "automation.varias_plantas",
        "automation.asignada_al_area",
        "automation.trigger_planta",
        "automation.otra_planta",
        "automation.blueprint_planta",
        "automation.no_cargada",
    ],
    "script": ["script.cocina", "script.apagar_planta"],
    "scene": ["scene.cena"],
}

# `raw_config` de cada una, como lo devuelven `automation/config` y
# `script/config`.
CONFIGS_PLANTA: dict[str, dict] = {
    # Apuntan a la planta: dejan de funcionar.
    "automation.luces_planta": {
        "id": "1", "triggers": [{"trigger": "time", "at": "20:00:00"}],
        "actions": [{"action": "light.turn_on", "target": {"floor_id": "planta_a"}}],
    },
    "automation.varias_plantas": {
        "id": "2", "triggers": [],
        "actions": [{"choose": [{"conditions": [], "sequence": [
            {"action": "light.turn_off",
             "target": {"floor_id": ["planta_b", "planta_a"]}},
        ]}]}],
    },
    "automation.trigger_planta": {
        "id": "3",
        "triggers": [{"trigger": "light.turned_on", "target": {"floor_id": "planta_a"}}],
        "actions": [{"action": "notify.notify", "data": {"message": "x"}}],
    },
    "automation.blueprint_planta": {
        "id": "4", "use_blueprint": {"path": "ficticio/luces.yaml",
                                     "input": {"planta": "planta_a"}},
    },
    "script.apagar_planta": {
        "sequence": [{"action": "light.turn_off", "target": {"floor_id": "planta_a"}}],
    },
    # Solo relacionadas a través de áreas, dispositivos o entidades: siguen.
    "automation.luz_cocina": {
        "id": "5", "triggers": [],
        "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.cocina"}}],
    },
    "automation.area_salon": {
        "id": "6", "triggers": [],
        "actions": [{"action": "light.turn_on", "target": {"area_id": "area_a1"}}],
    },
    "automation.asignada_al_area": {
        "id": "7", "triggers": [],
        "actions": [{"action": "switch.turn_on", "target": {"entity_id": "switch.ficticio"}}],
    },
    "automation.otra_planta": {
        "id": "8", "triggers": [],
        "actions": [{"action": "light.turn_on",
                     "target": {"area_id": "area_a0", "floor_id": "planta_b"}}],
    },
    "script.cocina": {
        "sequence": [{"action": "light.turn_off", "target": {"entity_id": "light.cocina"}}],
    },
}


def _leer_config(payload: dict) -> dict:
    entity_id = payload["entity_id"]
    if entity_id not in CONFIGS_PLANTA:
        # Lo que responde HA para una entidad que no está cargada.
        raise HAConnectionError("Entity not found", code="not_found")
    return {"config": CONFIGS_PLANTA[entity_id]}


def _rutas_borrado(**cambios: Any) -> dict[str, Any]:
    rutas: dict[str, Any] = {
        "config/floor_registry/list": FLOORS,
        "config/area_registry/list": _areas(2),
        "search/related": RELATED_PLANTA,
        "automation/config": _leer_config,
        "script/config": _leer_config,
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
        # Solo lo que usa `floor_id: planta_a` (acciones, disparadores o un
        # blueprint que recibe la planta) deja de funcionar.
        self.assertEqual(refs["automation"]["ids"], [
            "automation.blueprint_planta", "automation.luces_planta",
            "automation.trigger_planta", "automation.varias_plantas",
        ])
        self.assertEqual(refs["automation"]["count"], 4)
        self.assertEqual(refs["script"]["ids"], ["script.apagar_planta"])
        # Una escena no puede apuntar a una planta.
        self.assertNotIn("scene", refs)
        self.assertNotIn("area", refs)
        rel = preview["impact"]["related_unaffected"]
        self.assertEqual(rel["automation"]["ids"], [
            "automation.area_salon", "automation.asignada_al_area",
            "automation.luz_cocina", "automation.no_cargada", "automation.otra_planta",
        ])
        self.assertEqual(rel["script"]["ids"], ["script.cocina"])
        self.assertEqual(rel["scene"]["ids"], ["scene.cena"])
        warning = preview["warning"]
        self.assertIn("2 areas", warning)
        self.assertIn("4 automations and 1 script use this floor", warning)
        self.assertIn("5 automations, 1 script and 1 scene", warning)
        self.assertIn("keep working", warning)
        self.assertIn("templates", warning)
        related = [p for p in fake.sent if p["type"] == "search/related"]
        self.assertEqual(related[0]["item_type"], "floor")
        self.assertEqual(related[0]["item_id"], "planta_a")
        self.assertNotIn("config/floor_registry/delete", fake.types())

    async def test_relacionadas_por_area_no_cuentan_como_rotas(self) -> None:
        """Regresión A-1: treinta automatizaciones que solo encienden luces
        de las áreas de la planta NO dejan de funcionar al borrarla."""
        ids = [f"automation.cocina_{i}" for i in range(30)]
        configs = {
            i: {"id": i, "triggers": [], "actions": [
                {"action": "light.turn_on", "target": {"entity_id": "light.cocina"}}]}
            for i in ids
        }
        tools, _ = self._tools(_rutas_borrado(**{
            "search/related": {"area": ["area_a0"], "entity": ["light.cocina"],
                               "automation": ids, "scene": ["scene.cena"]},
            "automation/config": lambda p: {"config": configs[p["entity_id"]]},
        }))
        out = json.loads(await tools["ha_delete_floor"]("planta_a"))
        impact = out["preview"]["impact"]
        self.assertEqual(impact["references_unresolved"]["automation"]["count"], 0)
        self.assertEqual(impact["related_unaffected"]["automation"]["count"], 30)
        self.assertIn("0 automations and 0 scripts use this floor", out["preview"]["warning"])

    async def test_cada_lectura_fallando_preview_unavailable(self) -> None:
        comandos = ("config/floor_registry/list", "config/area_registry/list",
                    "search/related", "automation/config", "script/config")
        for comando in comandos:
            for fallo in (HAConnectionError("offline"), "no es una lista ni un dict"):
                with self.subTest(comando=comando, fallo=fallo):
                    tools, fake = self._tools(_rutas_borrado(**{comando: fallo}))
                    out = json.loads(await tools["ha_delete_floor"]("planta_a"))
                    self.assertEqual(out["error"], "preview_unavailable")
                    self.assertIn("detail", out)
                    self.assertNotIn("confirmation_token", out)
                    self.assertNotIn("config/floor_registry/delete", fake.types())

    async def test_config_sin_clave_config_preview_unavailable(self) -> None:
        tools, _ = self._tools(_rutas_borrado(**{"automation/config": {"otra": 1}}))
        out = json.loads(await tools["ha_delete_floor"]("planta_a"))
        self.assertEqual(out["error"], "preview_unavailable")
        self.assertNotIn("confirmation_token", out)

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
