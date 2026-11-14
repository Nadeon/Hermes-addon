"""Tests de las tools de trazas (`ha_list_traces`, `ha_get_trace`).

Home Assistant se simula con un `ws_send` falso. Las trazas son sintéticas,
con la forma de `trace/list` y `trace/get` de HA, y llevan secretos centinela
que nunca deben salir en claro.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from aiohttp import ClientSession

import hermes.tools.traces as traces_mod
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


def _corta(run_id: str, start: str, **extra: Any) -> dict[str, Any]:
    base = {
        "domain": "automation",
        "item_id": "1700000000001",
        "run_id": run_id,
        "state": "stopped",
        "script_execution": "finished",
        "timestamp": {"start": start, "finish": start.replace("00Z", "05Z")},
        "last_step": "action/0",
        "trigger": "state of binary_sensor.demo",
    }
    base.update(extra)
    return base


def _relleno(n: int) -> dict[str, str]:
    """~n bytes repartidos en atributos de 200 caracteres con espacios.

    Imita los estados con muchos atributos que arrastran las variables de
    una traza real, en lugar de una sola cadena gigante.
    """
    return {f"attr_{i}": ("palabra " * 25)[:200] for i in range(n // 200)}


def _traza_completa(n_pasos: int = 3, *, relleno: int = 0) -> dict[str, Any]:
    pasos: dict[str, list[dict[str, Any]]] = {
        "trigger/0": [{
            "path": "trigger/0",
            "timestamp": "2026-11-10T10:00:00.000000+00:00",
            "changed_variables": {
                "this": {"entity_id": "automation.demo", "state": "on"},
                "trigger": {"access_token": "SENTINEL-AT"},
            },
        }],
    }
    for i in range(n_pasos):
        pasos[f"action/{i}"] = [{
            "path": f"action/{i}",
            "timestamp": f"2026-11-10T10:00:{i + 1:02d}.000000+00:00",
            "changed_variables": {
                "entity_picture": "/api/camera_proxy/camera.x?token=SENTINEL-T",
                "relleno": _relleno(relleno),
            },
            "result": {"params": {"domain": "light", "service": "turn_on"},
                       "detalle": "y" * 2000},
        }]
    return {
        "domain": "automation",
        "item_id": "1700000000001",
        "run_id": "run-1",
        "state": "stopped",
        "script_execution": "finished",
        "timestamp": {"start": "2026-11-10T10:00:00Z", "finish": "2026-11-10T10:00:09Z"},
        "last_step": f"action/{n_pasos - 1}",
        "trigger": "state of binary_sensor.demo",
        "trace": pasos,
        "config": {"id": "1700000000001", "alias": "Demo",
                   "actions": [{"action": "light.turn_on"}],
                   "variables": {"api_key": "SENTINEL-CFG"},
                   "relleno": _relleno(relleno)},
        "blueprint_inputs": {"input": "valor"},
        "context": {"id": "ctx-1", "user_id": "usr-1"},
    }


class _FakeHA:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.traces_list: list[dict[str, Any]] = []
        self.trace: Any = None
        self.registry: dict[str, dict[str, Any]] = {}
        self.trace_get_error: HAConnectionError | None = None

    async def ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.sent.append(payload)
        tipo = payload["type"]
        if tipo == "config/entity_registry/get":
            entry = self.registry.get(payload["entity_id"])
            if entry is None:
                raise HAConnectionError("Entity not found", code="not_found")
            return entry
        if tipo == "trace/list":
            return list(self.traces_list)
        if tipo == "trace/get":
            if self.trace_get_error is not None:
                raise self.trace_get_error
            return self.trace
        raise AssertionError(f"comando inesperado: {payload}")

    def de_tipo(self, tipo: str) -> list[dict[str, Any]]:
        return [p for p in self.sent if p["type"] == tipo]


class _Base(unittest.IsolatedAsyncioTestCase):
    response_max_bytes: int | None = None

    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        client = make_ready_client(self.session, {})
        self.fake = _FakeHA()
        client.ws_send = self.fake.ws_send  # type: ignore[method-assign]
        self.mcp = DummyMCP()
        if self.response_max_bytes is None:
            traces_mod.register(self.mcp, client)
        else:
            traces_mod.register(
                self.mcp, client, response_max_bytes=self.response_max_bytes
            )

    async def asyncTearDown(self) -> None:
        await self.session.close()


# ── ha_list_traces ───────────────────────────────────────────────────────────


class TestListTraces(_Base):
    def _cinco(self) -> list[dict[str, Any]]:
        return [
            _corta("r3", "2026-11-10T10:03:00Z"),
            _corta("r1", "2026-11-10T10:01:00Z"),
            _corta("r5", "2026-11-10T10:05:00Z", error="x" * 2000),
            _corta("r2", "2026-11-10T10:02:00Z"),
            _corta("r4", "2026-11-10T10:04:00Z", not_triggered=True),
        ]

    async def test_mas_recientes_primero_con_limite(self) -> None:
        self.fake.traces_list = self._cinco()
        res = json.loads(await self.mcp.tools["ha_list_traces"](
            domain="automation", item_id="1700000000001", limit=3))
        self.assertEqual([t["run_id"] for t in res["traces"]], ["r5", "r4", "r3"])
        self.assertEqual(res["count"], 3)
        self.assertEqual(res["total"], 5)
        t = res["traces"][0]
        self.assertEqual(t["start"], "2026-11-10T10:05:00Z")
        self.assertEqual(t["finish"], "2026-11-10T10:05:05Z")
        self.assertEqual(t["last_step"], "action/0")
        self.assertEqual(t["trigger"], "state of binary_sensor.demo")

    async def test_error_recortado_y_not_triggered_conservado(self) -> None:
        self.fake.traces_list = self._cinco()
        res = json.loads(await self.mcp.tools["ha_list_traces"](
            domain="automation", item_id="1700000000001", limit=5))
        por_id = {t["run_id"]: t for t in res["traces"]}
        self.assertLessEqual(len(por_id["r5"]["error"]), 300)
        self.assertIs(por_id["r4"]["not_triggered"], True)

    async def test_limites_invalidos(self) -> None:
        for limite in (0, 51):
            res = json.loads(await self.mcp.tools["ha_list_traces"](
                domain="automation", limit=limite))
            self.assertEqual(res["error"], "invalid_argument")
            self.assertEqual(res["field"], "limit")
        self.assertEqual(self.fake.sent, [])

    async def test_dominio_invalido(self) -> None:
        res = json.loads(await self.mcp.tools["ha_list_traces"](domain="scene"))
        self.assertEqual(res["error"], "invalid_argument")
        self.assertEqual(res["field"], "domain")
        self.assertEqual(self.fake.sent, [])

    async def test_entity_id_se_traduce_a_unique_id(self) -> None:
        self.fake.registry["automation.x"] = {
            "entity_id": "automation.x", "unique_id": "1700000000001"}
        self.fake.traces_list = self._cinco()
        await self.mcp.tools["ha_list_traces"](
            domain="automation", entity_id="automation.x")
        self.assertEqual(
            self.fake.de_tipo("config/entity_registry/get"),
            [{"type": "config/entity_registry/get", "entity_id": "automation.x"}],
        )
        self.assertEqual(
            self.fake.de_tipo("trace/list"),
            [{"type": "trace/list", "domain": "automation",
              "item_id": "1700000000001"}],
        )

    async def test_entity_id_de_otro_dominio(self) -> None:
        res = json.loads(await self.mcp.tools["ha_list_traces"](
            domain="automation", entity_id="script.x"))
        self.assertEqual(res["error"], "invalid_argument")
        self.assertEqual(self.fake.sent, [])

    async def test_item_id_y_entity_id_a_la_vez(self) -> None:
        res = json.loads(await self.mcp.tools["ha_list_traces"](
            domain="automation", item_id="1", entity_id="automation.x"))
        self.assertEqual(res["error"], "invalid_argument")
        self.assertEqual(self.fake.sent, [])

    async def test_entity_id_sin_entrada(self) -> None:
        res = json.loads(await self.mcp.tools["ha_list_traces"](
            domain="automation", entity_id="automation.fantasma"))
        self.assertEqual(res, {"error": "not_found", "entity_id": "automation.fantasma"})
        self.assertEqual(self.fake.de_tipo("trace/list"), [])

    async def test_sin_item_ni_entity_lista_el_dominio(self) -> None:
        self.fake.traces_list = self._cinco()
        res = json.loads(await self.mcp.tools["ha_list_traces"](
            domain="script", limit=2))
        self.assertEqual(
            self.fake.sent, [{"type": "trace/list", "domain": "script"}])
        self.assertEqual(res["count"], 2)

    async def test_secretos_en_error_redactados(self) -> None:
        self.fake.traces_list = [_corta(
            "r1", "2026-11-10T10:01:00Z",
            error="fallo en https://user:SENTINEL-P@example.invalid token=SENTINEL-X")]
        raw = await self.mcp.tools["ha_list_traces"](domain="automation")
        self.assertNotIn("SENTINEL-", raw)


# ── ha_get_trace ─────────────────────────────────────────────────────────────


class TestGetTrace(_Base):
    async def _get(self, **kw: Any) -> tuple[str, dict[str, Any]]:
        args = {"domain": "automation", "run_id": "run-1",
                "item_id": "1700000000001"}
        args.update(kw)
        raw = await self.mcp.tools["ha_get_trace"](**args)
        return raw, json.loads(raw)

    async def test_summary_sin_config_ni_variables(self) -> None:
        self.fake.trace = _traza_completa(3)
        raw, res = await self._get()
        for prohibido in ("config", "blueprint_inputs", "context"):
            self.assertNotIn(prohibido, res)
        self.assertNotIn("changed_variables", raw)
        self.assertNotIn("SENTINEL-", raw)
        self.assertEqual(res["run_id"], "run-1")
        self.assertEqual(res["state"], "stopped")
        self.assertFalse(res["truncated"])
        self.assertEqual(
            [p["path"] for p in res["steps"]],
            ["trigger/0", "action/0", "action/1", "action/2"],
        )
        paso = res["steps"][1]
        self.assertEqual(set(paso), {"path", "timestamp", "result", "error", "child_id"})
        self.assertIsInstance(paso["result"], str)
        self.assertLessEqual(len(paso["result"]), 500)
        self.assertEqual(
            self.fake.de_tipo("trace/get"),
            [{"type": "trace/get", "domain": "automation",
              "item_id": "1700000000001", "run_id": "run-1"}],
        )

    async def test_full_redactado(self) -> None:
        self.fake.trace = _traza_completa(3)
        raw, res = await self._get(detail="full")
        self.assertNotIn("SENTINEL-", raw)
        self.assertIn("config", res)
        self.assertIn("changed_variables", res["steps"][0])
        self.assertNotIn("blueprint_inputs", res)
        self.assertNotIn("context", res)
        self.assertFalse(res["truncated"])

    async def test_traza_enorme_full_dentro_del_limite(self) -> None:
        # Más de 1 MB en crudo: 40 pasos con 30 KB de variables cada uno.
        traza = _traza_completa(40, relleno=30_000)
        self.assertGreater(len(json.dumps(traza)), 1_000_000)
        self.fake.trace = traza
        raw, res = await self._get(detail="full")
        self.assertLessEqual(len(raw.encode("utf-8")), 65_536)
        self.assertTrue(res["truncated"])
        omitted = res["omitted"]
        con_vars = sum(1 for p in res["steps"] if "changed_variables" in p)
        # Todo paso conservado o lleva sus variables o cuenta como omitido.
        self.assertEqual(con_vars + omitted["changed_variables_steps"],
                         len(res["steps"]))
        self.assertEqual(len(res["steps"]) + omitted["steps"], 41)
        self.assertEqual(omitted["config"], "config" not in res)
        self.assertNotIn("SENTINEL-", raw)

    async def test_recorte_empieza_por_las_variables_de_los_ultimos_pasos(self) -> None:
        # ~90 KB: obliga a recortar, pero basta con quitar variables.
        traza = _traza_completa(12, relleno=6_000)
        self.fake.trace = traza
        raw, res = await self._get(detail="full")
        self.assertTrue(res["truncated"])
        con = [("changed_variables" in p) for p in res["steps"]]
        # Las variables que quedan son las de los primeros pasos.
        self.assertEqual(con, sorted(con, reverse=True))
        self.assertTrue(con[0])

    async def test_cadena_enorme_acotada_sin_secreto_a_medias(self) -> None:
        # Una URL con credenciales justo donde cae el tope por cadena: el
        # corte no puede dejar visible un trozo de la contraseña. El tope
        # (4096) cae dentro de «SENTINEL-CORTE».
        largo = "a " * 2036 + "https://user:SENTINEL-CORTE@example.invalid " + "b" * 50_000
        traza = _traza_completa(1)
        traza["trace"]["action/0"][0]["changed_variables"] = {"dato": largo}
        self.fake.trace = traza
        raw, res = await self._get(detail="full")
        self.assertNotIn("SENTINEL", raw)
        dato = res["steps"][1]["changed_variables"]["dato"]
        self.assertLess(len(dato), 4200)
        self.assertIn("chars omitted", dato)

    async def test_not_found_por_codigo(self) -> None:
        self.fake.trace_get_error = HAConnectionError(
            "The trace could not be found", code="not_found")
        _, res = await self._get(run_id="no-existe")
        self.assertEqual(res, {"error": "not_found", "run_id": "no-existe"})

    async def test_otro_error_no_es_not_found(self) -> None:
        self.fake.trace_get_error = HAConnectionError("caída", code="unknown_error")
        _, res = await self._get()
        self.assertNotEqual(res.get("error"), "not_found")
        self.assertIn("error", res)

    async def test_paso_con_forma_inesperada(self) -> None:
        traza = _traza_completa(2)
        traza["trace"]["action/9"] = "no soy una lista"
        traza["trace"]["action/8"] = [42, {"path": None, "timestamp": 5}]
        self.fake.trace = traza
        _, res = await self._get()
        self.assertGreaterEqual(len(res["steps"]), 3)
        self.assertGreaterEqual(res["unrecognized_steps"], 2)

    async def test_sin_trace(self) -> None:
        traza = _traza_completa(2)
        del traza["trace"]
        self.fake.trace = traza
        _, res = await self._get()
        self.assertEqual(res["steps"], [])
        self.assertTrue(res["steps_unavailable"])

    async def test_requiere_item_o_entity(self) -> None:
        raw = await self.mcp.tools["ha_get_trace"](
            domain="automation", run_id="run-1")
        self.assertEqual(json.loads(raw)["error"], "invalid_argument")
        self.assertEqual(self.fake.sent, [])

    async def test_detail_invalido(self) -> None:
        _, res = await self._get(detail="raw")
        self.assertEqual(res["error"], "invalid_argument")
        self.assertEqual(res["field"], "detail")
        self.assertEqual(self.fake.sent, [])

    async def test_entity_id_se_traduce(self) -> None:
        self.fake.registry["script.demo"] = {
            "entity_id": "script.demo", "unique_id": "demo"}
        traza = _traza_completa(1)
        traza["domain"] = "script"
        traza["item_id"] = "demo"
        self.fake.trace = traza
        raw = await self.mcp.tools["ha_get_trace"](
            domain="script", run_id="run-1", entity_id="script.demo")
        self.assertEqual(json.loads(raw)["item_id"], "demo")
        self.assertEqual(
            self.fake.de_tipo("trace/get")[0]["item_id"], "demo")


class TestGetTraceLimiteBajo(_Base):
    response_max_bytes = 20_000

    async def test_respeta_response_max_bytes(self) -> None:
        self.fake.trace = _traza_completa(40, relleno=30_000)
        raw = await self.mcp.tools["ha_get_trace"](
            domain="automation", run_id="run-1", item_id="1700000000001",
            detail="full")
        self.assertLessEqual(len(raw.encode("utf-8")), 20_000)
        self.assertTrue(json.loads(raw)["truncated"])

    async def test_summary_tambien_se_limita(self) -> None:
        self.fake.trace = _traza_completa(200)
        raw = await self.mcp.tools["ha_get_trace"](
            domain="automation", run_id="run-1", item_id="1700000000001")
        self.assertLessEqual(len(raw.encode("utf-8")), 20_000)
        res = json.loads(raw)
        self.assertTrue(res["truncated"])
        self.assertGreater(res["omitted"]["steps"], 0)


if __name__ == "__main__":
    unittest.main()
