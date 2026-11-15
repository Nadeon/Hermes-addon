"""Tools de exposición a asistentes (spec 021, tramo a; T006).

`ha_list_exposed_entities`, `ha_set_entity_exposure` y
`ha_set_expose_new_entities` con Home Assistant simulado (`AsyncMock` de
`ws_send` que responde por `type` y FALLA si recibe una escritura que el test
no espera; `get_state` para la existencia). Datos ficticios: `light.salon`,
`lock.puerta`, `switch.cafetera`.

Decisión D-4 del supervisor: exponer pide token; ocultar no (reduce lo
expuesto). `ha_set_expose_new_entities` con `false` va sin token y con `true`
con token.

Controles negativos (T018), comprobados y con recuentos en el commit:
(b) no atar `estado` → cae `test_estado_cambiado_no_escribe` (y el de
`ha_set_expose_new_entities`); (c) no comprobar `entity_exists` → cae
`test_entidad_inexistente_no_escribe`.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from structlog.testing import capture_logs

import hermes.security as security
import hermes.tools.assistant_exposure as mod
from hermes.ha import HAConnectionError


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class _Base(unittest.IsolatedAsyncioTestCase):
    max_bytes = 131_072

    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.expuestas: dict[str, dict[str, bool]] = {
            "light.salon": {"conversation": True, "cloud.alexa": True},
            "lock.puerta": {"conversation": True},
            "switch.cafetera": {"cloud.google_assistant": True},
        }
        self.nuevas = {"conversation": True, "cloud.alexa": False,
                       "cloud.google_assistant": False}
        self.existen = {"light.salon", "lock.puerta", "switch.cafetera", "light.cocina"}
        self.enviados: list[dict[str, Any]] = []
        self.escrituras_esperadas = 0
        self.fallo_escritura: HAConnectionError | None = None
        self.ha = MagicMock()
        self.ha.wait_ready = AsyncMock(return_value=True)
        self.ha.ws_send = AsyncMock(side_effect=self._ws_send)
        self.ha.get_state = AsyncMock(side_effect=self._get_state)
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha, response_max_bytes=self.max_bytes)
        self.t = self.mcp.tools

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def _get_state(self, entity_id: str) -> Any:
        return {"entity_id": entity_id, "state": "on"} if entity_id in self.existen else None

    async def _ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.enviados.append(payload)
        tipo = payload["type"]
        if tipo == "homeassistant/expose_entity/list":
            return {"exposed_entities": copy.deepcopy(self.expuestas)}
        if tipo == "homeassistant/expose_new_entities/get":
            return {"expose_new": self.nuevas[payload["assistant"]]}
        if tipo in ("homeassistant/expose_entity", "homeassistant/expose_new_entities/set"):
            if len(self.escrituras()) > self.escrituras_esperadas:
                raise AssertionError(f"escritura inesperada: {payload}")
            if self.fallo_escritura is not None:
                raise self.fallo_escritura
            if tipo == "homeassistant/expose_new_entities/set":
                self.nuevas[payload["assistant"]] = payload["expose_new"]
                return None
            cambiadas = []
            for eid in payload["entity_ids"]:
                antes = dict(self.expuestas.get(eid, {}))
                for a in payload["assistants"]:
                    if payload["should_expose"]:
                        self.expuestas.setdefault(eid, {})[a] = True
                    else:
                        self.expuestas.get(eid, {}).pop(a, None)
                if self.expuestas.get(eid, {}) != antes:
                    cambiadas.append(eid)
            return {"changed_entity_ids": cambiadas}
        raise AssertionError(f"comando inesperado: {payload}")

    def escrituras(self) -> list[dict[str, Any]]:
        return [p for p in self.enviados if p["type"] in (
            "homeassistant/expose_entity", "homeassistant/expose_new_entities/set")]


# ── ha_list_exposed_entities ─────────────────────────────────────────────────


class TestListExposedEntities(_Base):
    async def test_sobre_ordenado_y_cabecera(self) -> None:
        r = await self.t["ha_list_exposed_entities"]()
        self.assertEqual(r["expose_new"], self.nuevas)
        self.assertEqual((r["count"], r["total"], r["truncated"]), (3, 3, False))
        self.assertEqual(r["items"], [
            {"entity_id": "light.salon", "assistants": ["cloud.alexa", "conversation"]},
            {"entity_id": "lock.puerta", "assistants": ["conversation"]},
            {"entity_id": "switch.cafetera", "assistants": ["cloud.google_assistant"]},
        ])

    async def test_filtros(self) -> None:
        r = await self.t["ha_list_exposed_entities"](assistant="conversation")
        self.assertEqual([i["entity_id"] for i in r["items"]], ["light.salon", "lock.puerta"])
        self.assertEqual(r["total"], 3)
        r = await self.t["ha_list_exposed_entities"](domain="lock")
        self.assertEqual([i["entity_id"] for i in r["items"]], ["lock.puerta"])

    async def test_filtros_invalidos(self) -> None:
        for args, campo in (({"assistant": "siri"}, "assistant"),
                            ({"domain": "Light"}, "domain")):
            with self.subTest(args=args):
                r = await self.t["ha_list_exposed_entities"](**args)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", campo))
        self.ha.ws_send.assert_not_awaited()

    async def test_recorte(self) -> None:
        self.expuestas = {f"light.l{i:04d}": {"conversation": True} for i in range(2000)}
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha, response_max_bytes=4096)
        r = await self.mcp.tools["ha_list_exposed_entities"]()
        self.assertTrue(r["truncated"])
        self.assertLess(r["count"], 2000)
        self.assertEqual(r["_response_limit"]["total"], 2000)


# ── ha_set_entity_exposure ───────────────────────────────────────────────────


class TestSetEntityExposure(_Base):
    async def test_validaciones(self) -> None:
        casos = [
            ({"entity_ids": [], "assistants": ["conversation"], "expose": True}, "entity_ids"),
            ({"entity_ids": [f"light.l{i}" for i in range(201)],
              "assistants": ["conversation"], "expose": True}, "entity_ids"),
            ({"entity_ids": ["salon"], "assistants": ["conversation"], "expose": True},
             "entity_ids"),
            ({"entity_ids": ["light.salon"], "assistants": ["siri"], "expose": True},
             "assistants"),
            ({"entity_ids": ["light.salon"], "assistants": [], "expose": True}, "assistants"),
            ({"entity_ids": ["light.salon"], "assistants": ["conversation"], "expose": "yes"},
             "expose"),
        ]
        for args, campo in casos:
            with self.subTest(campo=campo):
                r = await self.t["ha_set_entity_exposure"](**args)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", campo))
        self.ha.ws_send.assert_not_awaited()

    async def test_entidad_inexistente_no_escribe(self) -> None:
        for expose in (True, False):
            with self.subTest(expose=expose):
                r = await self.t["ha_set_entity_exposure"](
                    ["light.salon", "light.fantasma"], ["conversation"], expose)
                self.assertEqual(r, {"error": "not_found", "missing": ["light.fantasma"]})
        self.assertEqual(self.escrituras(), [])

    async def test_vista_previa_por_asistente(self) -> None:
        r = await self.t["ha_set_entity_exposure"](
            ["lock.puerta", "light.cocina", "light.cocina"], ["cloud.alexa", "conversation"], True)
        p = r["preview"]
        self.assertEqual(p["by_assistant"]["cloud.alexa"]["change"],
                         ["light.cocina", "lock.puerta"])
        self.assertEqual(p["by_assistant"]["conversation"]["change"], ["light.cocina"])
        self.assertEqual(p["by_assistant"]["conversation"]["already"], ["lock.puerta"])
        self.assertIn("Amazon", p["by_assistant"]["cloud.alexa"]["warning"])
        self.assertIn("MCP Server", p["by_assistant"]["conversation"]["warning"])
        self.assertEqual(p["sensitive"], ["lock.puerta"])
        self.assertEqual(self.escrituras(), [])

    async def test_ya_expuestas_no_changes(self) -> None:
        r = await self.t["ha_set_entity_exposure"](["light.salon"], ["conversation"], True)
        self.assertEqual(r, {"result": "no_changes"})

    async def test_confirmacion_una_sola_llamada(self) -> None:
        self.escrituras_esperadas = 1
        args = (["lock.puerta", "light.cocina"], ["cloud.alexa"], True)
        vista = await self.t["ha_set_entity_exposure"](*args)
        r = await self.t["ha_set_entity_exposure"](
            *args, confirmation_token=vista["confirmation_token"])
        self.assertEqual(self.escrituras(), [{
            "type": "homeassistant/expose_entity",
            "entity_ids": ["light.cocina", "lock.puerta"],
            "assistants": ["cloud.alexa"], "should_expose": True}])
        self.assertEqual(r, {"result": "ok", "expose": True,
                             "changed_entity_ids": ["light.cocina", "lock.puerta"]})

    async def test_mismo_lote_en_otro_orden_vale(self) -> None:
        self.escrituras_esperadas = 1
        vista = await self.t["ha_set_entity_exposure"](
            ["lock.puerta", "light.cocina"], ["cloud.alexa"], True)
        r = await self.t["ha_set_entity_exposure"](
            ["light.cocina", "lock.puerta", "lock.puerta"], ["cloud.alexa"], True,
            confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["result"], "ok")

    async def test_estado_cambiado_no_escribe(self) -> None:
        args = (["light.cocina"], ["cloud.alexa"], True)
        vista = await self.t["ha_set_entity_exposure"](*args)
        self.expuestas["light.cocina"] = {"cloud.alexa": True}
        r = await self.t["ha_set_entity_exposure"](
            *args, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r, {"error": security.ESTADO_CAMBIADO})
        self.assertEqual(self.escrituras(), [])

    async def test_token_de_otro_lote(self) -> None:
        vista = await self.t["ha_set_entity_exposure"](["light.cocina"], ["cloud.alexa"], True)
        r = await self.t["ha_set_entity_exposure"](
            ["lock.puerta"], ["cloud.alexa"], True,
            confirmation_token=vista["confirmation_token"])
        self.assertIn("does not match", r["error"])
        self.assertEqual(self.escrituras(), [])

    async def test_ocultar_sin_token(self) -> None:
        """D-4: ocultar reduce lo expuesto y se aplica a la primera."""
        self.escrituras_esperadas = 1
        r = await self.t["ha_set_entity_exposure"](["light.salon"], ["cloud.alexa"], False)
        self.assertEqual(r, {"result": "ok", "expose": False,
                             "changed_entity_ids": ["light.salon"]})
        self.assertEqual(self.escrituras()[0]["should_expose"], False)
        self.assertEqual(list(Path(self.temp_dir.name).glob("*")), [])

    async def test_ocultar_se_manda_aunque_no_este_en_la_lista(self) -> None:
        """Sin ajuste guardado puede estar expuesta por defecto: se manda."""
        self.escrituras_esperadas = 1
        r = await self.t["ha_set_entity_exposure"](["light.cocina"], ["conversation"], False)
        self.assertEqual(r["result"], "ok")
        self.assertEqual(len(self.escrituras()), 1)

    async def test_error_de_ha(self) -> None:
        self.escrituras_esperadas = 1
        self.fallo_escritura = HAConnectionError("boom", code="home_assistant_error")
        r = await self.t["ha_set_entity_exposure"](["light.salon"], ["cloud.alexa"], False)
        self.assertEqual((r["error"], r["ha_code"]), ("ha_error", "home_assistant_error"))

    async def test_log_sin_entity_id(self) -> None:
        self.escrituras_esperadas = 2
        with capture_logs() as logs:
            args = (["lock.puerta"], ["cloud.alexa"], True)
            vista = await self.t["ha_set_entity_exposure"](*args)
            await self.t["ha_set_entity_exposure"](
                *args, confirmation_token=vista["confirmation_token"])
            await self.t["ha_set_entity_exposure"](["lock.puerta"], ["cloud.alexa"], False)
            await self.t["ha_set_entity_exposure"](["light.fantasma"], ["cloud.alexa"], False)
        texto = json.dumps(logs, default=str)
        for valor in ("lock.puerta", "puerta", "fantasma"):
            self.assertNotIn(valor, texto)


# ── ha_set_expose_new_entities ───────────────────────────────────────────────


class TestSetExposeNewEntities(_Base):
    async def test_activar_pide_token(self) -> None:
        self.escrituras_esperadas = 1
        vista = await self.t["ha_set_expose_new_entities"]("cloud.alexa", True)
        self.assertEqual(
            {k: vista["preview"][k] for k in ("before", "after", "assistant")},
            {"before": False, "after": True, "assistant": "cloud.alexa"})
        self.assertIn("Amazon", vista["preview"]["warning"])
        self.assertEqual(self.escrituras(), [])
        r = await self.t["ha_set_expose_new_entities"](
            "cloud.alexa", True, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r, {"result": "ok", "assistant": "cloud.alexa", "expose_new": True})
        self.assertEqual(self.escrituras(), [{
            "type": "homeassistant/expose_new_entities/set",
            "assistant": "cloud.alexa", "expose_new": True}])

    async def test_desactivar_sin_token(self) -> None:
        self.escrituras_esperadas = 1
        r = await self.t["ha_set_expose_new_entities"]("conversation", False)
        self.assertEqual(r, {"result": "ok", "assistant": "conversation", "expose_new": False})
        self.assertEqual(list(Path(self.temp_dir.name).glob("*")), [])

    async def test_sin_cambios(self) -> None:
        r = await self.t["ha_set_expose_new_entities"]("conversation", True)
        self.assertEqual(r, {"result": "no_changes"})
        self.assertEqual(self.escrituras(), [])

    async def test_validacion(self) -> None:
        r = await self.t["ha_set_expose_new_entities"]("siri", True)
        self.assertEqual(r["field"], "assistant")
        r = await self.t["ha_set_expose_new_entities"]("conversation", 1)
        self.assertEqual(r["field"], "expose_new")
        self.ha.ws_send.assert_not_awaited()

    async def test_estado_cambiado(self) -> None:
        vista = await self.t["ha_set_expose_new_entities"]("cloud.alexa", True)
        # Alguien lo activa entre los dos pasos: la confirmación lo relee y ya
        # no hay nada que hacer (no escribe ni gasta el token).
        self.nuevas["cloud.alexa"] = True
        r = await self.t["ha_set_expose_new_entities"](
            "cloud.alexa", True, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r, {"result": "no_changes"})
        self.assertEqual(self.escrituras(), [])


if __name__ == "__main__":
    unittest.main()
