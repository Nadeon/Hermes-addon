"""Tests de ha_statistics_during_period y ha_list_statistic_ids con fake WS."""

from __future__ import annotations

import json
import unittest

from aiohttp import ClientSession

import hermes.tools.statistics as stats_mod
from tests._ha_fixture import make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_stat_points(n: int, base_ts: float = 1_712_000_000.0) -> list[dict]:
    """Genera n puntos estadísticos como los devuelve HA (timestamps float)."""
    return [
        {
            "start": base_ts + i * 3600.0,
            "end":   base_ts + (i + 1) * 3600.0,
            "mean":  20.0 + i * 0.5,
            "min":   18.0,
            "max":   23.0,
            "sum":   None,
            "state": None,
            "change": None,
        }
        for i in range(n)
    ]


def _make_statistic_ids(n: int) -> list[dict]:
    return [
        {
            "statistic_id": f"sensor.temp_{i}",
            "name": f"Temperature {i}",
            "source": "recorder",
            "unit_of_measurement": "°C",
            "has_mean": True,
            "has_sum": False,
        }
        for i in range(n)
    ]


# ── Tests ha_list_statistic_ids ───────────────────────────────────────────────

class TestListStatisticIds(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def _make_client(self, ws_result):
        client = make_ready_client(self.session, {})
        async def fake_ws_send(payload, timeout_seconds=30):
            return ws_result
        client.ws_send = fake_ws_send  # type: ignore[method-assign]
        return client

    async def test_basic(self) -> None:
        items = _make_statistic_ids(5)
        client = self._make_client(items)
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_statistic_ids"]()
        result = json.loads(raw)
        self.assertEqual(result["count"], 5)
        self.assertEqual(len(result["statistic_ids"]), 5)
        self.assertIn("statistic_id", result["statistic_ids"][0])
        self.assertIn("unit_of_measurement", result["statistic_ids"][0])

    async def test_filter_passed_in_payload(self) -> None:
        """statistic_type se incluye en el payload WS."""
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            return []
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        await mcp.tools["ha_list_statistic_ids"](statistic_type="mean")
        self.assertEqual(received[0].get("statistic_type"), "mean")

    async def test_empty_list(self) -> None:
        client = self._make_client([])
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_statistic_ids"]()
        result = json.loads(raw)
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["statistic_ids"], [])

    async def test_ws_error(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(payload, timeout_seconds=30):
            raise HAConnectionError("recorder offline")
        client.ws_send = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        raw = await mcp.tools["ha_list_statistic_ids"]()
        result = json.loads(raw)
        self.assertIn("error", result)


# ── Tests ha_statistics_during_period ────────────────────────────────────────

class TestStatisticsDuringPeriod(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def _make_client(self, ws_result):
        client = make_ready_client(self.session, {})
        async def fake_ws_send(payload, timeout_seconds=30):
            return ws_result
        client.ws_send = fake_ws_send  # type: ignore[method-assign]
        return client

    async def test_basic(self) -> None:
        points = _make_stat_points(3)
        client = self._make_client({"sensor.temp": points})
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        raw = await mcp.tools["ha_statistics_during_period"](["sensor.temp"])
        result = json.loads(raw)
        self.assertIn("statistics", result)
        self.assertIn("sensor.temp", result["statistics"])
        self.assertEqual(len(result["statistics"]["sensor.temp"]), 3)
        self.assertFalse(result["truncated"])

    async def test_timestamps_expanded_to_iso(self) -> None:
        """start y end se convierten de float a ISO 8601."""
        points = [{"start": 1_712_000_000.0, "end": 1_712_003_600.0, "mean": 20.0}]
        client = self._make_client({"sensor.temp": points})
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        raw = await mcp.tools["ha_statistics_during_period"](["sensor.temp"])
        result = json.loads(raw)
        pt = result["statistics"]["sensor.temp"][0]
        self.assertIn("2024", pt["start"])   # ISO string
        self.assertIn("T", pt["start"])
        self.assertIn("2024", pt["end"])

    async def test_covered_range(self) -> None:
        """covered_range cubre el primer start y el último end."""
        points = _make_stat_points(3, base_ts=1_712_000_000.0)
        client = self._make_client({"sensor.temp": points})
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        raw = await mcp.tools["ha_statistics_during_period"](["sensor.temp"])
        result = json.loads(raw)
        cr = result["covered_range"]
        self.assertIsNotNone(cr["start"])
        self.assertIsNotNone(cr["end"])
        # end debe ser mayor que start
        self.assertGreater(cr["end"], cr["start"])

    async def test_covered_range_empty(self) -> None:
        """Si HA no devuelve datos, covered_range tiene start=None, end=None."""
        client = self._make_client({})
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        raw = await mcp.tools["ha_statistics_during_period"](["sensor.inexistente"])
        result = json.loads(raw)
        self.assertIsNone(result["covered_range"]["start"])
        self.assertIsNone(result["covered_range"]["end"])

    async def test_granularity_in_response(self) -> None:
        """El campo granularity refleja el period solicitado."""
        client = self._make_client({})
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        raw = await mcp.tools["ha_statistics_during_period"](
            ["sensor.temp"], period="day"
        )
        result = json.loads(raw)
        self.assertEqual(result["granularity"], "day")

    async def test_truncation_by_count(self) -> None:
        """Más de _MAX_POINTS_PER_STATISTIC puntos → truncado por conteo."""
        from hermes.tools.statistics import _MAX_POINTS_PER_STATISTIC
        points = _make_stat_points(_MAX_POINTS_PER_STATISTIC + 50)
        client = self._make_client({"sensor.temp": points})
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        raw = await mcp.tools["ha_statistics_during_period"](["sensor.temp"])
        result = json.loads(raw)
        self.assertLessEqual(
            len(result["statistics"]["sensor.temp"]),
            _MAX_POINTS_PER_STATISTIC,
        )

    async def test_truncation_by_bytes(self) -> None:
        """response_max_bytes muy pequeño → truncado con truncated=True."""
        points = _make_stat_points(50)
        client = self._make_client({"sensor.temp": points})
        mcp = DummyMCP()
        stats_mod.register(mcp, client, response_max_bytes=500)
        raw = await mcp.tools["ha_statistics_during_period"](["sensor.temp"])
        result = json.loads(raw)
        self.assertTrue(result["truncated"])
        self.assertIsNotNone(result["truncated_at"])

    async def test_invalid_period(self) -> None:
        """period inválido → error estructurado sin llamar a WS."""
        client = self._make_client({})
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        raw = await mcp.tools["ha_statistics_during_period"](
            ["sensor.temp"], period="second"
        )
        result = json.loads(raw)
        self.assertEqual(result["error"], "invalid_period")
        self.assertIn("given", result)

    async def test_5minute_range_too_large(self) -> None:
        """5minute con rango >7 días → error range_too_large_for_5minute."""
        client = self._make_client({})
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        raw = await mcp.tools["ha_statistics_during_period"](
            ["sensor.temp"],
            period="5minute",
            hours_back=8 * 24.0,   # 8 días
        )
        result = json.loads(raw)
        self.assertEqual(result["error"], "range_too_large_for_5minute")
        self.assertIn("hint", result)

    async def test_5minute_valid_range(self) -> None:
        """5minute con rango ≤7 días → no error."""
        client = self._make_client({"sensor.temp": _make_stat_points(5)})
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        raw = await mcp.tools["ha_statistics_during_period"](
            ["sensor.temp"],
            period="5minute",
            hours_back=6 * 24.0,   # 6 días, dentro del límite
        )
        result = json.loads(raw)
        self.assertNotIn("error", result)
        self.assertIn("statistics", result)

    async def test_types_param_passed(self) -> None:
        """types se incluye en el payload WS."""
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            return {}
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        await mcp.tools["ha_statistics_during_period"](
            ["sensor.temp"], types=["mean", "min"]
        )
        self.assertEqual(received[0].get("types"), ["mean", "min"])

    async def test_units_param_passed(self) -> None:
        """units se incluye en el payload WS."""
        received: list[dict] = []
        client = make_ready_client(self.session, {})
        async def capture(payload, timeout_seconds=30):
            received.append(payload)
            return {}
        client.ws_send = capture  # type: ignore[method-assign]
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        await mcp.tools["ha_statistics_during_period"](
            ["sensor.temp"], units={"temperature": "°C"}
        )
        self.assertEqual(received[0].get("units"), {"temperature": "°C"})

    async def test_ws_error(self) -> None:
        from hermes.ha import HAConnectionError
        client = make_ready_client(self.session, {})
        async def boom(payload, timeout_seconds=30):
            raise HAConnectionError("recorder offline")
        client.ws_send = boom  # type: ignore[method-assign]
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        raw = await mcp.tools["ha_statistics_during_period"](["sensor.temp"])
        result = json.loads(raw)
        self.assertIn("error", result)

    async def test_empty_result(self) -> None:
        """HA devuelve {} → statistics vacío, covered_range None, sin error."""
        client = self._make_client({})
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        raw = await mcp.tools["ha_statistics_during_period"](["sensor.inexistente"])
        result = json.loads(raw)
        self.assertEqual(result["statistics"], {})
        self.assertFalse(result["truncated"])
        self.assertIsNone(result["covered_range"]["start"])

    async def test_timestamps_in_milliseconds(self) -> None:
        """HA a veces devuelve timestamps en milisegundos — deben convertirse a ISO."""
        base_ts_s = 1_712_000_000.0
        points = [
            {
                "start": base_ts_s * 1000,   # milisegundos
                "end":   (base_ts_s + 3600) * 1000,
                "mean":  20.0,
                "sum":   None,
            }
        ]
        client = self._make_client({"sensor.temp": points})
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        raw = await mcp.tools["ha_statistics_during_period"](["sensor.temp"])
        result = json.loads(raw)
        pt = result["statistics"]["sensor.temp"][0]
        # Debe ser ISO válido (año razonable, no 58246)
        self.assertIn("2024", pt["start"])
        self.assertIn("T", pt["start"])

    async def test_nan_fields_converted_to_none(self) -> None:
        """HA devuelve NaN en campos que no aplican — deben convertirse a None."""
        import math
        points = [
            {
                "start": 1_712_000_000.0,
                "end": 1_712_003_600.0,
                "mean": float("nan"),   # NaN → None
                "min": float("nan"),
                "max": float("nan"),
                "sum": 100.5,
                "state": None,
                "change": float("inf"),  # Inf → None
            }
        ]
        client = self._make_client({"sensor.energy": points})
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        # No debe lanzar ValueError por NaN/Inf
        raw = await mcp.tools["ha_statistics_during_period"](["sensor.energy"])
        result = json.loads(raw)  # Would raise if NaN leaked into JSON
        pt = result["statistics"]["sensor.energy"][0]
        self.assertIsNone(pt["mean"])
        self.assertIsNone(pt["change"])
        self.assertEqual(pt["sum"], 100.5)

    async def test_multiple_statistic_ids(self) -> None:
        """Múltiples statistic_ids → cada uno con su lista de puntos."""
        data = {
            "sensor.temp": _make_stat_points(3),
            "sensor.energy": _make_stat_points(3, base_ts=1_712_010_000.0),
        }
        client = self._make_client(data)
        mcp = DummyMCP()
        stats_mod.register(mcp, client)
        raw = await mcp.tools["ha_statistics_during_period"](
            ["sensor.temp", "sensor.energy"]
        )
        result = json.loads(raw)
        self.assertIn("sensor.temp", result["statistics"])
        self.assertIn("sensor.energy", result["statistics"])
