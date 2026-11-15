"""Las tres tools de la familia `recorder` (spec 029, CAP-049; T021–T022).

FR-008…FR-011, FR-018…FR-020. El cliente de HA es un doble con `AsyncMock`
(`ws_send`, `get_state`): lo que importa es qué se le pide, qué se devuelve y
qué queda en el log. Datos ficticios (`sensor.consumo`, `light.salon`,
`kitchen_sink:gas_ficticio`, `centinela-029`); nada de una instalación real.

Controles negativos (T034 c–d), con recuentos en el commit del tramo:
- no comprobar que la entidad existe → cae `test_entidad_que_no_existe`;
- no calcular `missing` → caen los de metadatos que lo miran.
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from structlog.testing import capture_logs

from hermes.command_table import TABLE_HA_CORE
from hermes.ha import HAConnectionError
from hermes.tools import recorder_status as mod

_CENTINELA = "centinela-029"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJh"
_TOPE = 131_072


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _cliente() -> MagicMock:
    c = MagicMock()
    c.wait_ready = AsyncMock(return_value=True)
    c.ws_send = AsyncMock(return_value=[])
    c.get_state = AsyncMock(return_value={"entity_id": "sensor.consumo", "state": "1"})
    return c


def _tools(cliente: MagicMock, tope: int = _TOPE) -> dict[str, Any]:
    mcp = DummyMCP()
    mod.register(mcp, cliente, response_max_bytes=tope)
    return mcp.tools


def _sin_comando() -> HAConnectionError:
    return HAConnectionError("HA WS command failed: Unknown command.", code="unknown_command")


def _eventos(logs: list[dict[str, Any]], tool: str) -> list[dict[str, Any]]:
    return [e for e in logs if str(e.get("event", "")).startswith(tool)]


class TestRegistro(unittest.TestCase):
    def test_registra_las_tres(self) -> None:
        self.assertEqual(set(_tools(_cliente())), {
            "ha_validate_statistics", "ha_get_statistics_metadata", "ha_get_recorder_info"})


# ── ha_validate_statistics (T021) ────────────────────────────────────────────

def _problemas() -> dict[str, Any]:
    return {
        "sensor.zeta": [{"type": "units_changed",
                         "data": {"statistic_id": "sensor.zeta",
                                  "state_unit": "kWh", "metadata_unit": "Wh"}}],
        "sensor.alfa": [
            {"type": "state_class_removed", "data": {"statistic_id": "sensor.alfa"}},
            {"type": "entity_no_longer_recorded", "data": {"statistic_id": "sensor.alfa"}},
        ],
        "sensor.consumo": [{"type": "units_changed",
                            "data": {"statistic_id": "sensor.consumo",
                                     "nota": f"token={_CENTINELA}"}}],
        "sensor.vacio": [],
    }


class TestValidarEstadisticas(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.ha = _cliente()
        self.ha.ws_send.return_value = _problemas()
        self.t = _tools(self.ha)
        self.tool = self.t["ha_validate_statistics"]

    async def test_aplana_y_ordena(self) -> None:
        r = await self.tool()
        self.ha.ws_send.assert_awaited_once_with({"type": "recorder/validate_statistics"})
        self.assertEqual(
            [(i["statistic_id"], i["type"]) for i in r["items"]],
            [("sensor.alfa", "entity_no_longer_recorded"),
             ("sensor.alfa", "state_class_removed"),
             ("sensor.consumo", "units_changed"),
             ("sensor.zeta", "units_changed")])
        self.assertEqual(r["count"], 4)
        self.assertIs(r["truncated"], False)
        self.assertEqual(r["items"][3]["data"]["state_unit"], "kWh")
        self.assertEqual(r["by_type"], {"entity_no_longer_recorded": 1,
                                        "state_class_removed": 1, "units_changed": 2})

    async def test_filtros_y_by_type_antes_de_filtrar(self) -> None:
        r = await self.tool(issue_type="units_changed")
        self.assertEqual([i["statistic_id"] for i in r["items"]],
                         ["sensor.consumo", "sensor.zeta"])
        self.assertEqual(r["by_type"]["state_class_removed"], 1)
        r = await self.tool(statistic_id="sensor.alfa")
        self.assertEqual(r["count"], 2)
        r = await self.tool(statistic_id="sensor.alfa", issue_type="units_changed")
        self.assertEqual((r["count"], r["items"]), (0, []))
        self.assertEqual(sum(r["by_type"].values()), 4)

    async def test_sin_problemas(self) -> None:
        self.ha.ws_send.return_value = {}
        r = await self.tool()
        self.assertEqual(r, {"count": 0, "truncated": False, "by_type": {}, "items": []})

    async def test_redactado(self) -> None:
        r = await self.tool()
        self.assertNotIn(_CENTINELA, json.dumps(r))

    async def test_recorte_al_tope(self) -> None:
        self.ha.ws_send.return_value = {
            f"sensor.s{i:04d}": [{"type": "units_changed",
                                  "data": {"statistic_id": f"sensor.s{i:04d}", "x": "y" * 40}}]
            for i in range(400)
        }
        r = _tools(self.ha, tope=10_240)["ha_validate_statistics"]
        out = await r()
        self.assertIs(out["truncated"], True)
        self.assertLess(out["count"], 400)
        self.assertEqual(out["count"], len(out["items"]))
        self.assertEqual(out["by_type"], {"units_changed": 400})
        self.assertLessEqual(len(json.dumps(out, ensure_ascii=False).encode()), 10_240)

    async def test_argumentos_invalidos_sin_llamar(self) -> None:
        for args in ({"statistic_id": "Sensor.X"}, {"statistic_id": "sin_separador"},
                     {"statistic_id": ""}, {"statistic_id": 3},
                     {"issue_type": "Units-Changed"}, {"issue_type": "x" * 65}):
            with self.subTest(args=args):
                r = await self.tool(**args)
                self.assertEqual(r["error"], "invalid_argument")
                self.assertEqual(r["field"], next(iter(args)))
        self.ha.ws_send.assert_not_awaited()

    async def test_id_externo_valido(self) -> None:
        r = await self.tool(statistic_id="kitchen_sink:gas_ficticio")
        self.assertNotIn("error", r)

    async def test_recorder_no_cargado(self) -> None:
        self.ha.ws_send.side_effect = _sin_comando()
        r = await self.tool()
        self.assertEqual((r["error"], r["ha_code"]), ("recorder_not_loaded", "unknown_command"))
        self.assertIn("recorder:", r["detail"])

    async def test_otro_error_de_ha_redactado(self) -> None:
        self.ha.ws_send.side_effect = HAConnectionError(
            f"HA WS command failed: boom {_JWT}", code="home_assistant_error")
        r = await self.tool()
        self.assertEqual((r["error"], r["ha_code"]), ("ha_command_failed", "home_assistant_error"))
        self.assertNotIn(_JWT, json.dumps(r))

    async def test_core_caido(self) -> None:
        self.ha.ws_send.side_effect = HAConnectionError("WebSocket no disponible.")
        r = await self.tool()
        self.assertIn("WebSocket no disponible", r["error"])

    async def test_log_sin_ids_ni_valores(self) -> None:
        with capture_logs() as logs:
            await self.tool(statistic_id="sensor.consumo")
        texto = json.dumps(logs, default=str)
        for prohibido in ("sensor.consumo", "sensor.alfa", "kWh", _CENTINELA):
            self.assertNotIn(prohibido, texto)
        ev = _eventos(logs, "ha_validate_statistics")
        self.assertEqual(ev[-1]["event"], "ha_validate_statistics_ok")
        self.assertEqual((ev[-1]["count"], ev[-1]["issues"]), (1, 4))


# ── ha_get_statistics_metadata (T021) ────────────────────────────────────────

def _meta(sid: str, **extra: Any) -> dict[str, Any]:
    return {"statistic_id": sid, "name": None, "source": sid.split(".")[0].split(":")[0],
            "has_mean": False, "mean_type": 0, "has_sum": True,
            "statistics_unit_of_measurement": "kWh",
            "display_unit_of_measurement": "kWh", "unit_class": "energy", **extra}


class TestMetadatos(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.ha = _cliente()
        self.ha.ws_send.return_value = [
            _meta("sensor.consumo", name=f"Consumo token={_CENTINELA}"),
            _meta("kitchen_sink:gas_ficticio"),
        ]
        self.tool = _tools(self.ha)["ha_get_statistics_metadata"]

    async def test_pide_sin_repetir_y_devuelve_missing(self) -> None:
        r = await self.tool(["sensor.consumo", "sensor.no_existe", "sensor.consumo",
                             "kitchen_sink:gas_ficticio"])
        self.ha.ws_send.assert_awaited_once_with({
            "type": "recorder/get_statistics_metadata",
            "statistic_ids": ["sensor.consumo", "sensor.no_existe",
                              "kitchen_sink:gas_ficticio"]})
        self.assertEqual(r["missing"], ["sensor.no_existe"])
        self.assertEqual([i["statistic_id"] for i in r["items"]],
                         ["kitchen_sink:gas_ficticio", "sensor.consumo"])
        self.assertEqual(r["count"], 2)
        self.assertIs(r["truncated"], False)
        # Lo que da HA, sin quitar campos.
        self.assertEqual(set(r["items"][0]), set(_meta("x.y")))

    async def test_todas_missing(self) -> None:
        self.ha.ws_send.return_value = []
        r = await self.tool(["sensor.no_existe"])
        self.assertEqual((r["count"], r["missing"]), (0, ["sensor.no_existe"]))

    async def test_redactado(self) -> None:
        r = await self.tool(["sensor.consumo"])
        self.assertNotIn(_CENTINELA, json.dumps(r))

    async def test_argumentos_invalidos_sin_llamar(self) -> None:
        for ids in ([], [f"sensor.s{i}" for i in range(101)], ["Sensor.X"],
                    ["sensor.ok", "mal"], "sensor.consumo", [None], None):
            with self.subTest(ids=ids):
                r = await self.tool(ids)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "statistic_ids"))
        self.ha.ws_send.assert_not_awaited()

    async def test_cien_es_el_maximo(self) -> None:
        r = await self.tool([f"sensor.s{i}" for i in range(100)])
        self.assertNotIn("error", r)
        self.assertEqual(len(r["missing"]), 100)

    async def test_recorder_no_cargado(self) -> None:
        self.ha.ws_send.side_effect = _sin_comando()
        r = await self.tool(["sensor.consumo"])
        self.assertEqual(r["error"], "recorder_not_loaded")

    async def test_log_sin_ids(self) -> None:
        with capture_logs() as logs:
            await self.tool(["sensor.consumo", "sensor.no_existe"])
        texto = json.dumps(logs, default=str)
        for prohibido in ("sensor.consumo", "sensor.no_existe", "kitchen_sink", _CENTINELA):
            self.assertNotIn(prohibido, texto)
        ev = _eventos(logs, "ha_get_statistics_metadata")[-1]
        self.assertEqual((ev["requested"], ev["missing"]), (2, 1))


# ── ha_get_recorder_info (T022) ──────────────────────────────────────────────

_INFO = {"backlog": 0, "db_in_default_location": True, "max_backlog": 65000,
         "migration_in_progress": False, "migration_is_live": False,
         "recording": True, "thread_running": True}


class TestInfoDelRecorder(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.ha = _cliente()
        self.respuestas: dict[str, Any] = {
            "recorder/info": dict(_INFO),
            "recorder/entity_options/get": {"recording_disabled_by": None},
        }

        async def ws_send(msg: dict[str, Any]) -> Any:
            valor = self.respuestas[msg["type"]]
            if isinstance(valor, BaseException):
                raise valor
            return valor

        self.ha.ws_send.side_effect = ws_send
        self.tool = _tools(self.ha)["ha_get_recorder_info"]

    def tipos(self) -> list[str]:
        return [c.args[0]["type"] for c in self.ha.ws_send.await_args_list]

    async def test_los_siete_campos(self) -> None:
        r = await self.tool()
        self.assertEqual(r, _INFO)
        self.assertEqual(self.tipos(), ["recorder/info"])
        self.ha.get_state.assert_not_awaited()

    async def test_entidad_grabada(self) -> None:
        r = await self.tool(entity_id="sensor.consumo")
        self.ha.get_state.assert_awaited_once_with("sensor.consumo")
        self.assertEqual(r["entity"], {"entity_id": "sensor.consumo", "recorded": True,
                                       "recording_disabled_by": None})
        self.assertEqual(self.ha.ws_send.await_args_list[1].args[0],
                         {"type": "recorder/entity_options/get", "entity_id": "sensor.consumo"})

    async def test_entidad_no_grabada(self) -> None:
        self.respuestas["recorder/entity_options/get"] = {"recording_disabled_by": "user"}
        r = await self.tool(entity_id="light.salon")
        self.assertEqual(r["entity"], {"entity_id": "light.salon", "recorded": False,
                                       "recording_disabled_by": "user"})

    async def test_entidad_que_no_existe(self) -> None:
        # Control negativo (T034 c): sin la comprobación, HA diría
        # `recorded: true` de una entidad mal escrita y este test cae.
        self.ha.get_state.return_value = None
        r = await self.tool(entity_id="sensor.no_existe")
        self.assertEqual(r, {"error": "not_found", "entity_id": "sensor.no_existe"})
        self.assertNotIn("recorder/entity_options/get", self.tipos())

    async def test_entity_id_invalido(self) -> None:
        for eid in ("salon", "Light.Salon", "", "light.salon; x", 3):
            with self.subTest(eid=eid):
                r = await self.tool(entity_id=eid)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "entity_id"))
        self.ha.ws_send.assert_not_awaited()
        self.ha.get_state.assert_not_awaited()

    async def test_recorder_no_cargado(self) -> None:
        self.respuestas["recorder/info"] = _sin_comando()
        r = await self.tool()
        self.assertEqual(r["error"], "recorder_not_loaded")

    async def test_entity_options_desconocido_solo_en_entity(self) -> None:
        self.respuestas["recorder/entity_options/get"] = _sin_comando()
        r = await self.tool(entity_id="sensor.consumo")
        self.assertEqual(r["recording"], True)
        self.assertEqual(r["entity"]["error"], "unsupported_by_ha_version")
        self.assertEqual(r["entity"]["entity_id"], "sensor.consumo")
        self.assertEqual(r["entity"]["table_ha_core"], TABLE_HA_CORE)
        self.assertNotIn("recorded", r["entity"])

    async def test_core_caido(self) -> None:
        self.respuestas["recorder/info"] = HAConnectionError("WebSocket no disponible.")
        r = await self.tool()
        self.assertIn("WebSocket no disponible", r["error"])
        # Y en la comprobación de la entidad: no se toma por `not_found`.
        self.ha.get_state.side_effect = HAConnectionError("HA no responde.")
        r = await self.tool(entity_id="sensor.consumo")
        self.assertIn("HA no responde", r["error"])

    async def test_log_sin_entity_id(self) -> None:
        with capture_logs() as logs:
            await self.tool(entity_id="sensor.consumo")
            self.ha.get_state.return_value = None
            await self.tool(entity_id="light.salon")
        texto = json.dumps(logs, default=str)
        self.assertNotIn("sensor.consumo", texto)
        self.assertNotIn("light.salon", texto)
        eventos = [e["event"] for e in _eventos(logs, "ha_get_recorder_info")]
        self.assertEqual(eventos, ["ha_get_recorder_info_ok", "ha_get_recorder_info_failed"])


if __name__ == "__main__":
    unittest.main()
