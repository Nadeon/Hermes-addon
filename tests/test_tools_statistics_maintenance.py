"""Mantenimiento de estadísticas de la familia `recorder` (spec 020, tramo 1).

T002–T006: `ha_clear_statistics`, `ha_change_statistics_unit` y
`ha_update_statistics_metadata` (FR-001…FR-003, FR-006…FR-008, FR-017…FR-019).

El doble de HA (T002) es un `AsyncMock` de `ws_send` que responde por `type`
de comando con metadatos configurables y registra todo lo enviado; los tokens
son los reales de `security.py` en una carpeta temporal. Datos ficticios
(`sensor.consumo`, `banco:externa`, `centinela-020`); nada de una instalación
real.

Controles negativos (T019), con recuentos en el commit del tramo:
- (a) quitar `end_time` del dict del token de `ha_clear_statistics` → cae
  `test_cambiar_cualquier_argumento_no_casa`;
- (b) no pasar `estado` → caen los de `ESTADO_CAMBIADO`;
- (c) quitar la comprobación de `source` → cae
  `test_fuente_externa_sin_token`;
- (d) enviar el comando en la vista previa → caen los que usan
  `_sin_escrituras`;
- (e) no redactar el error de HA → cae `test_error_de_ha_redactado`;
- (f) registrar los ids en el log → cae `test_log_sin_ids_ni_fechas`.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from structlog.testing import capture_logs

from hermes import security
from hermes.command_table import TABLE_HA_CORE
from hermes.ha import HAConnectionError
from hermes.tools import statistics_maintenance as mod

_CENTINELA = "centinela-020"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJh"

# Los comandos que escriben: ninguno puede salir en una vista previa.
_ESCRITURAS = {
    "recorder/clear_statistics",
    "recorder/change_statistics_unit",
    "recorder/update_statistics_metadata",
    "recorder/adjust_sum_statistics",
    "recorder/import_statistics",
}


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _meta(statistic_id: str, **cambios: Any) -> dict[str, Any]:
    base = {
        "statistic_id": statistic_id,
        "display_unit_of_measurement": "Wh",
        "has_mean": False,
        "mean_type": 0,
        "has_sum": True,
        "name": None,
        "source": "recorder",
        "statistics_unit_of_measurement": "Wh",
        "unit_class": "energy",
    }
    base.update(cambios)
    return base


class _Base(unittest.IsolatedAsyncioTestCase):
    """T002: el doble de HA del módulo."""

    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.metadatos: dict[str, dict[str, Any]] = {
            "sensor.consumo": _meta("sensor.consumo"),
            "sensor.solar": _meta("sensor.solar", statistics_unit_of_measurement="kWh",
                                  display_unit_of_measurement="kWh"),
            "banco:externa": _meta("banco:externa", source="banco"),
        }
        self.enviados: list[dict[str, Any]] = []
        self.fallos: dict[str, HAConnectionError] = {}
        self.ha = MagicMock()
        self.ha.wait_ready = AsyncMock(return_value=True)
        self.ha.ws_send = AsyncMock(side_effect=self._ws_send)
        mcp = DummyMCP()
        mod.register(mcp, self.ha, response_max_bytes=131_072)
        self.t = mcp.tools

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def _ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.enviados.append(payload)
        tipo = payload["type"]
        if tipo in self.fallos:
            raise self.fallos[tipo]
        if tipo == "recorder/get_statistics_metadata":
            return [dict(self.metadatos[s]) for s in payload["statistic_ids"]
                    if s in self.metadatos]
        if tipo == "recorder/statistics_during_period":
            return {}
        return None  # los comandos de escritura responden `result: null`

    def _escrituras(self) -> list[dict[str, Any]]:
        return [p for p in self.enviados if p["type"] in _ESCRITURAS]

    def _sin_escrituras(self) -> None:
        """Utilidad de T002: el paso no envió ningún comando de escritura."""
        self.assertEqual(self._escrituras(), [])


def _ha_error(codigo: str, texto: str = "fallo") -> HAConnectionError:
    return HAConnectionError(f"HA WS command failed: {texto}", code=codigo)


# ── ha_clear_statistics (T003) ───────────────────────────────────────────────

class TestBorrar(_Base):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.tool = self.t["ha_clear_statistics"]

    async def test_vista_previa_sin_rango(self) -> None:
        r = await self.tool(statistic_ids=["sensor.solar", "sensor.consumo"])
        self._sin_escrituras()
        self.assertIn("confirmation_token", r)
        p = r["preview"]
        self.assertEqual(p["action"], "clear_statistics")
        self.assertEqual(p["scope"], "entire")
        self.assertIs(p["removes_metadata"], True)
        self.assertIs(p["irreversible"], True)
        self.assertIn("backup", p["undo"])
        self.assertNotIn("effective_range", p)
        self.assertEqual([s["statistic_id"] for s in p["statistics"]],
                         ["sensor.consumo", "sensor.solar"])
        self.assertEqual(p["statistics"][1]["statistics_unit_of_measurement"], "kWh")
        self.assertEqual(set(p["statistics"][0]), {
            "statistic_id", "source", "name", "statistics_unit_of_measurement",
            "unit_class", "has_mean", "mean_type", "has_sum"})

    async def test_vista_previa_con_rango_efectivo(self) -> None:
        r = await self.tool(statistic_ids=["sensor.consumo"],
                            start_time="2026-03-01T12:00:00+02:00",
                            end_time="2026-03-01T15:00:00+02:00")
        self._sin_escrituras()
        p = r["preview"]
        self.assertEqual(p["scope"], "range")
        self.assertIs(p["removes_metadata"], False)
        self.assertEqual(p["requested_range"], {"start_time": "2026-03-01T10:00:00+00:00",
                                                "end_time": "2026-03-01T13:00:00+00:00"})
        self.assertEqual(p["effective_range"], {
            "hourly": {"after": "2026-03-01T09:00:00+00:00",
                       "before": "2026-03-01T13:00:00+00:00"},
            "five_minute": {"after": "2026-03-01T09:55:00+00:00",
                            "before": "2026-03-01T13:00:00+00:00"},
        })

    async def test_confirmacion_ordenada_sin_repetir_y_en_utc(self) -> None:
        args = {"statistic_ids": ["sensor.solar", "sensor.consumo", "sensor.solar"],
                "start_time": "2026-03-01T12:00:00+02:00",
                "end_time": "2026-03-01T15:00:00+02:00"}
        r = await self.tool(**args)
        # Los repetidos se piden una vez.
        self.assertEqual(self.enviados[0], {"type": "recorder/get_statistics_metadata",
                                            "statistic_ids": ["sensor.consumo", "sensor.solar"]})
        hecho = await self.tool(**args, confirmation_token=r["confirmation_token"])
        self.assertEqual(hecho, {"cleared": True, "statistic_ids_count": 2, "scope": "range"})
        self.assertEqual(self._escrituras(), [{
            "type": "recorder/clear_statistics",
            "statistic_ids": ["sensor.consumo", "sensor.solar"],
            "start_time": "2026-03-01T10:00:00+00:00",
            "end_time": "2026-03-01T13:00:00+00:00",
        }])

    async def test_confirmacion_sin_rango(self) -> None:
        r = await self.tool(statistic_ids=["banco:externa"])
        hecho = await self.tool(statistic_ids=["banco:externa"],
                                confirmation_token=r["confirmation_token"])
        self.assertEqual(hecho["scope"], "entire")
        self.assertEqual(self._escrituras(), [{"type": "recorder/clear_statistics",
                                               "statistic_ids": ["banco:externa"]}])

    async def test_id_desconocido_sin_token(self) -> None:
        r = await self.tool(statistic_ids=["sensor.consumo", "sensor.no_existe"])
        self.assertEqual(r["error"], "statistics_not_found")
        self.assertEqual(r["missing"], ["sensor.no_existe"])
        self.assertNotIn("confirmation_token", r)
        self._sin_escrituras()

    async def test_argumentos_invalidos_sin_llamar(self) -> None:
        casos = [
            {"statistic_ids": []},
            {"statistic_ids": [f"sensor.s{i}" for i in range(101)]},
            {"statistic_ids": ["Sensor Consumo"]},
            {"statistic_ids": "sensor.consumo"},
            {"statistic_ids": ["sensor.consumo"], "start_time": "2026-03-01T10:00:00+00:00"},
            {"statistic_ids": ["sensor.consumo"], "end_time": "2026-03-01T10:00:00+00:00"},
            {"statistic_ids": ["sensor.consumo"], "start_time": "2026-03-01T10:00:00+00:00",
             "end_time": "2026-03-01T10:00:00+00:00"},
            {"statistic_ids": ["sensor.consumo"], "start_time": "2026-03-01T11:00:00+00:00",
             "end_time": "2026-03-01T10:00:00+00:00"},
            {"statistic_ids": ["sensor.consumo"], "start_time": "2026-03-01T10:00:00",
             "end_time": "2026-03-01T11:00:00+00:00"},
            {"statistic_ids": ["sensor.consumo"], "start_time": "ayer",
             "end_time": "2026-03-01T11:00:00+00:00"},
        ]
        for caso in casos:
            with self.subTest(caso=caso):
                r = await self.tool(**caso)
                self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()

    async def test_cien_ids_es_el_maximo(self) -> None:
        for i in range(100):
            self.metadatos[f"sensor.s{i}"] = _meta(f"sensor.s{i}")
        r = await self.tool(statistic_ids=[f"sensor.s{i}" for i in range(100)])
        self.assertIn("confirmation_token", r)

    async def test_recorder_no_cargado(self) -> None:
        self.fallos["recorder/get_statistics_metadata"] = _ha_error("unknown_command")
        r = await self.tool(statistic_ids=["sensor.consumo"])
        self.assertEqual(r["error"], "recorder_not_loaded")

    async def test_timeout_de_ha(self) -> None:
        r = await self.tool(statistic_ids=["sensor.consumo"])
        self.fallos["recorder/clear_statistics"] = _ha_error("timeout", "clear_statistics timed out")
        hecho = await self.tool(statistic_ids=["sensor.consumo"],
                                confirmation_token=r["confirmation_token"])
        self.assertEqual(hecho["error"], "ha_timeout")
        self.assertIn("queue", hecho["detail"])

    async def test_error_de_ha_redactado(self) -> None:
        r = await self.tool(statistic_ids=["sensor.consumo"])
        self.fallos["recorder/clear_statistics"] = _ha_error(
            "home_assistant_error", f"token={_CENTINELA} bearer {_JWT}")
        hecho = await self.tool(statistic_ids=["sensor.consumo"],
                                confirmation_token=r["confirmation_token"])
        self.assertEqual(hecho["error"], "ha_command_failed")
        self.assertEqual(hecho["ha_code"], "home_assistant_error")
        self.assertEqual(hecho["table_ha_core"], TABLE_HA_CORE)
        texto = json.dumps(hecho)
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn(_JWT, texto)

    async def test_vista_previa_redactada(self) -> None:
        self.metadatos["sensor.consumo"]["name"] = f"password={_CENTINELA}"
        r = await self.tool(statistic_ids=["sensor.consumo"])
        self.assertNotIn(_CENTINELA, json.dumps(r))

    async def test_log_sin_ids_ni_fechas(self) -> None:
        args = {"statistic_ids": ["sensor.consumo", "sensor.no_existe"]}
        with capture_logs() as logs:
            await self.tool(**args)
            r = await self.tool(statistic_ids=["sensor.consumo"],
                                start_time="2026-03-01T10:00:00+00:00",
                                end_time="2026-03-01T11:00:00+00:00")
            await self.tool(statistic_ids=["sensor.consumo"],
                            start_time="2026-03-01T10:00:00+00:00",
                            end_time="2026-03-01T11:00:00+00:00",
                            confirmation_token=r["confirmation_token"])
        eventos = [e for e in logs if str(e.get("event", "")).startswith("ha_clear_statistics")]
        self.assertEqual([e["event"] for e in eventos],
                         ["ha_clear_statistics_failed", "ha_clear_statistics_preview",
                          "ha_clear_statistics_ok"])
        self.assertEqual(eventos[0]["missing"], 1)
        texto = json.dumps(logs, default=str)
        for prohibido in ("sensor.consumo", "sensor.no_existe", "2026-03-01"):
            self.assertNotIn(prohibido, texto)


# ── ha_change_statistics_unit (T004) ─────────────────────────────────────────

class TestCambiarUnidad(_Base):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.tool = self.t["ha_change_statistics_unit"]

    async def test_vista_previa(self) -> None:
        r = await self.tool(statistic_id="sensor.consumo", old_unit="Wh", new_unit="kWh")
        self._sin_escrituras()
        p = r["preview"]
        self.assertEqual(p["action"], "change_statistics_unit")
        self.assertEqual((p["old_unit"], p["new_unit"], p["unit_class"]), ("Wh", "kWh", "energy"))
        self.assertEqual(p["statistic"]["statistics_unit_of_measurement"], "Wh")
        self.assertEqual(p["converts"], ["mean", "min", "max", "state", "sum"])
        self.assertEqual(p["tables"], ["hourly", "five_minute"])
        self.assertEqual(p["scope"], "entire_history")
        self.assertIs(p["irreversible"], True)

    async def test_confirmacion_encolada(self) -> None:
        args = {"statistic_id": "sensor.consumo", "old_unit": "Wh", "new_unit": "kWh"}
        r = await self.tool(**args)
        hecho = await self.tool(**args, confirmation_token=r["confirmation_token"])
        self.assertIs(hecho["queued"], True)
        self.assertEqual(hecho["check_with"], "ha_get_statistics_metadata")
        self.assertIn("background", hecho["detail"])
        self.assertEqual(self._escrituras(), [{
            "type": "recorder/change_statistics_unit", "statistic_id": "sensor.consumo",
            "new_unit_of_measurement": "kWh", "old_unit_of_measurement": "Wh"}])

    async def test_fuente_externa_sin_token(self) -> None:
        r = await self.tool(statistic_id="banco:externa", old_unit="Wh", new_unit="kWh")
        self.assertEqual(r["error"], "not_supported_for_source")
        self.assertNotIn("confirmation_token", r)
        self._sin_escrituras()

    async def test_unidad_vieja_distinta_sin_token(self) -> None:
        r = await self.tool(statistic_id="sensor.solar", old_unit="Wh", new_unit="MWh")
        self.assertEqual(r["error"], "unit_mismatch")
        self.assertEqual(r["current_unit"], "kWh")
        self.assertNotIn("confirmation_token", r)
        self._sin_escrituras()

    async def test_misma_unidad_sin_llamar(self) -> None:
        r = await self.tool(statistic_id="sensor.consumo", old_unit="Wh", new_unit="Wh")
        self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()

    async def test_id_desconocido_sin_token(self) -> None:
        r = await self.tool(statistic_id="sensor.no_existe", old_unit="Wh", new_unit="kWh")
        self.assertEqual(r["error"], "statistics_not_found")
        self.assertNotIn("confirmation_token", r)

    async def test_argumentos_invalidos_sin_llamar(self) -> None:
        for caso in ({"statistic_id": "nada", "old_unit": "Wh", "new_unit": "kWh"},
                     {"statistic_id": "sensor.consumo", "old_unit": 3, "new_unit": "kWh"},
                     {"statistic_id": "sensor.consumo", "old_unit": "Wh", "new_unit": "x" * 65}):
            with self.subTest(caso=caso):
                self.assertEqual((await self.tool(**caso))["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()

    async def test_error_de_ha_al_confirmar(self) -> None:
        args = {"statistic_id": "sensor.consumo", "old_unit": "Wh", "new_unit": "kWh"}
        r = await self.tool(**args)
        self.fallos["recorder/change_statistics_unit"] = _ha_error(
            "home_assistant_error", "Can't convert Wh to kWh")
        hecho = await self.tool(**args, confirmation_token=r["confirmation_token"])
        self.assertEqual(hecho["error"], "ha_command_failed")
        self.assertEqual(hecho["ha_code"], "home_assistant_error")

    async def test_log_sin_ids_ni_unidades(self) -> None:
        args = {"statistic_id": "sensor.consumo", "old_unit": "Wh", "new_unit": "kWh"}
        with capture_logs() as logs:
            r = await self.tool(**args)
            await self.tool(**args, confirmation_token=r["confirmation_token"])
            await self.tool(statistic_id="banco:externa", old_unit="Wh", new_unit="kWh")
        texto = json.dumps(logs, default=str)
        for prohibido in ("sensor.consumo", "banco:externa", "kWh", '"Wh"'):
            self.assertNotIn(prohibido, texto)
        self.assertIn("ha_change_statistics_unit_ok", texto)


# ── ha_update_statistics_metadata (T005) ─────────────────────────────────────

class TestMetadatos(_Base):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.tool = self.t["ha_update_statistics_metadata"]

    async def test_vista_previa(self) -> None:
        r = await self.tool(statistic_id="sensor.consumo", unit_of_measurement="kWh",
                            unit_class="energy")
        self._sin_escrituras()
        p = r["preview"]
        self.assertEqual(p["current"], {"unit_of_measurement": "Wh", "unit_class": "energy"})
        self.assertEqual(p["new"], {"unit_of_measurement": "kWh", "unit_class": "energy"})
        self.assertIs(p["converts_values"], False)
        self.assertIn("ha_change_statistics_unit", p["hint"])

    async def test_confirmacion_siempre_con_unit_class(self) -> None:
        for clase in ("energy", None):
            with self.subTest(clase=clase):
                self.enviados.clear()
                args = {"statistic_id": "banco:externa", "unit_of_measurement": "kWh",
                        "unit_class": clase}
                r = await self.tool(**args)
                hecho = await self.tool(**args, confirmation_token=r["confirmation_token"])
                self.assertEqual(hecho, {"updated": True})
                self.assertEqual(self._escrituras(), [{
                    "type": "recorder/update_statistics_metadata",
                    "statistic_id": "banco:externa", "unit_of_measurement": "kWh",
                    "unit_class": clase}])

    async def test_id_desconocido(self) -> None:
        r = await self.tool(statistic_id="sensor.no_existe", unit_of_measurement="kWh",
                            unit_class="energy")
        self.assertEqual(r["error"], "statistics_not_found")
        self.assertNotIn("confirmation_token", r)

    async def test_timeout(self) -> None:
        args = {"statistic_id": "sensor.consumo", "unit_of_measurement": "kWh",
                "unit_class": "energy"}
        r = await self.tool(**args)
        self.fallos["recorder/update_statistics_metadata"] = _ha_error("timeout")
        hecho = await self.tool(**args, confirmation_token=r["confirmation_token"])
        self.assertEqual(hecho["error"], "ha_timeout")

    async def test_recorder_no_cargado(self) -> None:
        self.fallos["recorder/get_statistics_metadata"] = _ha_error("unknown_command")
        r = await self.tool(statistic_id="sensor.consumo", unit_of_measurement="kWh",
                            unit_class="energy")
        self.assertEqual(r["error"], "recorder_not_loaded")

    async def test_errores_de_ha(self) -> None:
        for codigo in ("invalid_format", "home_assistant_error"):
            with self.subTest(codigo=codigo):
                args = {"statistic_id": "sensor.consumo", "unit_of_measurement": "kWh",
                        "unit_class": "temperature"}
                r = await self.tool(**args)
                self.fallos["recorder/update_statistics_metadata"] = _ha_error(
                    codigo, f"Unsupported unit token={_CENTINELA}")
                hecho = await self.tool(**args, confirmation_token=r["confirmation_token"])
                self.assertEqual(hecho["error"], "ha_command_failed")
                self.assertEqual(hecho["ha_code"], codigo)
                self.assertEqual(hecho["table_ha_core"], TABLE_HA_CORE)
                self.assertNotIn(_CENTINELA, json.dumps(hecho))

    async def test_argumentos_invalidos_sin_llamar(self) -> None:
        for caso in ({"statistic_id": "x", "unit_of_measurement": "kWh", "unit_class": None},
                     {"statistic_id": "sensor.consumo", "unit_of_measurement": 1,
                      "unit_class": None},
                     {"statistic_id": "sensor.consumo", "unit_of_measurement": "kWh",
                      "unit_class": ""}):
            with self.subTest(caso=caso):
                self.assertEqual((await self.tool(**caso))["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()


# ── Token (T006) ─────────────────────────────────────────────────────────────

class TestToken(_Base):
    async def _no_casa(self, tool: str, previa: dict[str, Any], otra: dict[str, Any]) -> None:
        r = await self.t[tool](**previa)
        no = await self.t[tool](**otra, confirmation_token=r["confirmation_token"])
        self.assertIn("does not match", no["error"])
        self._sin_escrituras()

    async def test_cambiar_cualquier_argumento_no_casa(self) -> None:
        rango = {"start_time": "2026-03-01T10:00:00+00:00",
                 "end_time": "2026-03-01T13:00:00+00:00"}
        base = {"statistic_ids": ["sensor.consumo"], **rango}
        tool = "ha_clear_statistics"
        await self._no_casa(tool, base, {**base, "statistic_ids": ["sensor.solar"]})
        await self._no_casa(tool, base, {**base, "end_time": "2026-03-01T14:00:00+00:00"})
        await self._no_casa(tool, base, {**base, "start_time": "2026-03-01T09:00:00+00:00"})
        await self._no_casa(tool, base, {"statistic_ids": ["sensor.consumo"]})
        await self._no_casa(tool, {"statistic_ids": ["sensor.consumo"]}, base)

        tool = "ha_change_statistics_unit"
        base = {"statistic_id": "sensor.consumo", "old_unit": "Wh", "new_unit": "kWh"}
        await self._no_casa(tool, base, {**base, "new_unit": "MWh"})
        await self._no_casa(tool, base, {**base, "statistic_id": "sensor.solar",
                                         "old_unit": "kWh", "new_unit": "MWh"})

        tool = "ha_update_statistics_metadata"
        base = {"statistic_id": "sensor.consumo", "unit_of_measurement": "kWh",
                "unit_class": "energy"}
        await self._no_casa(tool, base, {**base, "unit_class": None})
        await self._no_casa(tool, base, {**base, "unit_of_measurement": "MWh"})
        await self._no_casa(tool, base, {**base, "statistic_id": "sensor.solar"})

    async def test_metadatos_cambiados_entre_medias(self) -> None:
        casos = [
            ("ha_clear_statistics", {"statistic_ids": ["sensor.consumo"]}),
            ("ha_change_statistics_unit",
             {"statistic_id": "sensor.consumo", "old_unit": "Wh", "new_unit": "kWh"}),
            ("ha_update_statistics_metadata",
             {"statistic_id": "sensor.consumo", "unit_of_measurement": "kWh",
              "unit_class": "energy"}),
        ]
        for tool, args in casos:
            for cambio in ("unidad", "borrada"):
                with self.subTest(tool=tool, cambio=cambio):
                    self.metadatos["sensor.consumo"] = _meta("sensor.consumo")
                    r = await self.t[tool](**args)
                    if cambio == "unidad":
                        self.metadatos["sensor.consumo"]["statistics_unit_of_measurement"] = "kWh"
                    else:
                        del self.metadatos["sensor.consumo"]
                    no = await self.t[tool](**args, confirmation_token=r["confirmation_token"])
                    self.assertEqual(no["error"], "statistics_changed")
                    self.assertEqual(no["detail"], security.ESTADO_CAMBIADO)
                    self._sin_escrituras()

    async def test_token_usado_dos_veces(self) -> None:
        args = {"statistic_ids": ["sensor.consumo"]}
        r = await self.t["ha_clear_statistics"](**args)
        await self.t["ha_clear_statistics"](**args, confirmation_token=r["confirmation_token"])
        otra = await self.t["ha_clear_statistics"](**args,
                                                   confirmation_token=r["confirmation_token"])
        self.assertIn("already used", otra["error"])
        self.assertEqual(len(self._escrituras()), 1)

    async def test_fechas_equivalentes_en_otra_zona_atan_lo_mismo(self) -> None:
        r = await self.t["ha_clear_statistics"](
            statistic_ids=["sensor.consumo"], start_time="2026-03-01T12:00:00+02:00",
            end_time="2026-03-01T15:00:00+02:00")
        hecho = await self.t["ha_clear_statistics"](
            statistic_ids=["sensor.consumo"], start_time="2026-03-01T10:00:00Z",
            end_time="2026-03-01T13:00:00Z", confirmation_token=r["confirmation_token"])
        self.assertIs(hecho["cleared"], True)

    async def test_lectura_fallida_al_confirmar_deja_el_token(self) -> None:
        """Fail-closed: sin estado legible no se ejecuta, y el token sigue
        pendiente para reintentar dentro de su TTL."""
        args = {"statistic_ids": ["sensor.consumo"]}
        r = await self.t["ha_clear_statistics"](**args)
        self.fallos["recorder/get_statistics_metadata"] = HAConnectionError("Core caído")
        no = await self.t["ha_clear_statistics"](**args, confirmation_token=r["confirmation_token"])
        self.assertIn("error", no)
        self._sin_escrituras()
        del self.fallos["recorder/get_statistics_metadata"]
        hecho = await self.t["ha_clear_statistics"](**args,
                                                    confirmation_token=r["confirmation_token"])
        self.assertIs(hecho["cleared"], True)

    async def test_respuesta_inesperada_falla_cerrada(self) -> None:
        self.ha.ws_send = AsyncMock(return_value={"no": "lista"})
        r = await self.t["ha_clear_statistics"](statistic_ids=["sensor.consumo"])
        self.assertNotIn("confirmation_token", r)
        self.assertIn("error", r)


# ── Tramo 2: ajustar la suma e importar (T021–T023) ──────────────────────────
#
# Controles negativos (T033), con recuentos en el commit del tramo:
# - (a) quitar `adjustment_unit` del dict del token → cae
#   `test_cambiar_ajuste_unidad_o_instante_no_casa` (1);
# - (b) no comprobar `has_sum` → cae `test_sin_suma_sin_token` (1);
# - (c) aceptar `start` con minutos → caen 3 casos de
#   `test_argumentos_invalidos_sin_llamar` de la importación;
# - (d) no declarar `stats` omitible → caen 4: `test_vista_previa_de_una_nueva`,
#   `test_confirmar_sin_stats_usa_lo_guardado`, `test_metadatos_cambiados_entre_medias`
#   y `test_tope_lleno_pide_reenviar_stats`.

_HORA = "2026-03-01T10:00:00+00:00"
_HORA_MS = 1772359200000.0  # 2026-03-01T10:00:00Z en milisegundos


class _BaseTramo2(_Base):
    """El doble de T002 más las filas de `statistics_during_period` y los
    estados de entidades (para el aviso de la importación)."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.filas: dict[str, list[dict[str, Any]]] = {}
        self.estados: dict[str, dict[str, Any]] = {}
        self.ha.get_state = AsyncMock(side_effect=lambda eid: self.estados.get(eid))

    async def _ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        if payload["type"] == "recorder/statistics_during_period":
            self.enviados.append(payload)
            if payload["type"] in self.fallos:
                raise self.fallos[payload["type"]]
            return {s: self.filas[s] for s in payload["statistic_ids"] if s in self.filas}
        return await super()._ws_send(payload, timeout_seconds)


class TestAjustarSuma(_BaseTramo2):
    """T021 — `ha_adjust_statistics_sum` (FR-004, FR-006, FR-008, FR-017, FR-018)."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.tool = self.t["ha_adjust_statistics_sum"]
        self.args = {"statistic_id": "sensor.consumo", "start_time": "2026-03-01T12:00:00+02:00",
                     "adjustment": 500, "adjustment_unit": "Wh"}

    async def test_vista_previa_con_la_suma_antes_y_despues(self) -> None:
        self.filas["sensor.consumo"] = [{"start": _HORA_MS, "end": _HORA_MS + 3600000,
                                         "sum": 1200.0}]
        r = await self.tool(**self.args)
        self._sin_escrituras()
        p = r["preview"]
        self.assertEqual(p["action"], "adjust_statistics_sum")
        self.assertEqual(p["from"], _HORA)
        self.assertEqual((p["adjustment"], p["adjustment_unit"], p["statistics_unit"]),
                         (500, "Wh", "Wh"))
        self.assertEqual(p["sum_at_start"], {"before": 1200.0, "after": 1700.0})
        self.assertIn("twice", p["repeat_warning"])
        self.assertIs(p["irreversible"], True)
        self.assertIn("backup", p["undo"])
        lectura = [x for x in self.enviados if x["type"] == "recorder/statistics_during_period"]
        self.assertEqual(lectura, [{
            "type": "recorder/statistics_during_period", "statistic_ids": ["sensor.consumo"],
            "start_time": _HORA, "end_time": "2026-03-01T11:00:00+00:00",
            "period": "hour", "types": ["sum"]}])

    async def test_hora_con_minutos_lee_su_hora(self) -> None:
        self.filas["sensor.consumo"] = [{"start": _HORA_MS, "sum": 10.0}]
        r = await self.tool(**{**self.args, "start_time": "2026-03-01T10:25:00+00:00"})
        self.assertEqual(r["preview"]["from"], "2026-03-01T10:25:00+00:00")
        self.assertEqual(r["preview"]["sum_at_start"]["before"], 10.0)

    async def test_otra_unidad_solo_da_la_de_antes(self) -> None:
        self.filas["sensor.consumo"] = [{"start": _HORA_MS, "sum": 1200.0}]
        r = await self.tool(**{**self.args, "adjustment": 0.5, "adjustment_unit": "kWh"})
        self.assertEqual(r["preview"]["sum_at_start"], {"before": 1200.0})

    async def test_sin_fila_es_null(self) -> None:
        r = await self.tool(**self.args)
        self.assertIsNone(r["preview"]["sum_at_start"])
        self.assertIn("confirmation_token", r)

    async def test_confirmacion_encolada(self) -> None:
        r = await self.tool(**self.args)
        hecho = await self.tool(**self.args, confirmation_token=r["confirmation_token"])
        self.assertIs(hecho["queued"], True)
        self.assertEqual(hecho["check_with"], "ha_statistics_during_period")
        self.assertEqual(self._escrituras(), [{
            "type": "recorder/adjust_sum_statistics", "statistic_id": "sensor.consumo",
            "start_time": _HORA, "adjustment": 500,
            "adjustment_unit_of_measurement": "Wh"}])

    async def test_sin_suma_sin_token(self) -> None:
        self.metadatos["sensor.consumo"]["has_sum"] = False
        r = await self.tool(**self.args)
        self.assertEqual(r["error"], "statistic_has_no_sum")
        self.assertNotIn("confirmation_token", r)
        self._sin_escrituras()

    async def test_id_desconocido_sin_token(self) -> None:
        r = await self.tool(**{**self.args, "statistic_id": "sensor.no_existe"})
        self.assertEqual(r["error"], "statistics_not_found")
        self.assertNotIn("confirmation_token", r)

    async def test_argumentos_invalidos_sin_llamar(self) -> None:
        for cambio in ({"adjustment": 0}, {"adjustment": 0.0}, {"adjustment": float("nan")},
                       {"adjustment": float("inf")}, {"adjustment": True},
                       {"adjustment": "5"}, {"start_time": "2026-03-01T10:00:00"},
                       {"start_time": "ayer"}, {"statistic_id": "Sensor"},
                       {"adjustment_unit": 3}):
            with self.subTest(cambio=cambio):
                r = await self.tool(**{**self.args, **cambio})
                self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()

    async def test_unidades_invalidas_de_ha(self) -> None:
        r = await self.tool(**{**self.args, "adjustment_unit": "L"})
        self.fallos["recorder/adjust_sum_statistics"] = _ha_error(
            "invalid_units", "Can't convert Wh to L")
        hecho = await self.tool(**{**self.args, "adjustment_unit": "L"},
                                confirmation_token=r["confirmation_token"])
        self.assertEqual(hecho["error"], "ha_command_failed")
        self.assertEqual(hecho["ha_code"], "invalid_units")

    async def test_lectura_de_la_suma_fallida_sin_token(self) -> None:
        self.fallos["recorder/statistics_during_period"] = HAConnectionError("Core caído")
        r = await self.tool(**self.args)
        self.assertIn("error", r)
        self.assertNotIn("confirmation_token", r)

    async def test_log_sin_ids_ni_valores(self) -> None:
        self.filas["sensor.consumo"] = [{"start": _HORA_MS, "sum": 1234.5}]
        with capture_logs() as logs:
            r = await self.tool(**self.args)
            await self.tool(**self.args, confirmation_token=r["confirmation_token"])
            self.metadatos["sensor.solar"]["has_sum"] = False
            await self.tool(**{**self.args, "statistic_id": "sensor.solar"})
        texto = json.dumps(logs, default=str)
        for prohibido in ("sensor.consumo", "sensor.solar", "1234.5", "500", '"Wh"', "2026-03"):
            self.assertNotIn(prohibido, texto)
        self.assertIn("ha_adjust_statistics_sum_ok", texto)


def _metadata(statistic_id: str = "banco:importada", **cambios: Any) -> dict[str, Any]:
    base = {"statistic_id": statistic_id,
            "source": statistic_id.split(":")[0] if ":" in statistic_id else "recorder",
            "name": "Importada", "unit_of_measurement": "kWh", "unit_class": "energy",
            "mean_type": 0, "has_sum": True}
    base.update(cambios)
    return base


def _stats(n: int = 3, desde: str = "2026-03-01T12:00:00+02:00") -> list[dict[str, Any]]:
    from datetime import datetime, timedelta
    inicio = datetime.fromisoformat(desde)
    return [{"start": (inicio + timedelta(hours=i)).isoformat(), "state": float(i),
             "sum": float(i + 1)} for i in range(n)]


class TestImportar(_BaseTramo2):
    """T022 — `ha_import_statistics` (FR-005, FR-006, FR-017)."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.tool = self.t["ha_import_statistics"]

    async def test_vista_previa_de_una_nueva(self) -> None:
        r = await self.tool(metadata=_metadata(), stats=list(reversed(_stats())))
        self._sin_escrituras()
        p = r["preview"]
        self.assertEqual(p["action"], "import_statistics")
        self.assertEqual(p["statistic_id"], "banco:importada")
        self.assertIs(p["exists"], False)
        self.assertNotIn("current_metadata", p)
        self.assertEqual(p["new_metadata"]["unit_of_measurement"], "kWh")
        self.assertEqual((p["rows"], p["first_start"], p["last_start"]),
                         (3, _HORA, "2026-03-01T12:00:00+00:00"))
        self.assertEqual(p["overwritten_rows"], 0)
        self.assertNotIn("recorded_entity_warning", p)
        self.assertIs(p["irreversible"], True)
        # Resumen, no volcado: ninguna fila en la vista previa.
        self.assertNotIn("stats", p)
        self.assertEqual(r["omit_on_confirm"], ["stats"])
        self.assertIn("stats", r["confirm_hint"])

    async def test_vista_previa_de_una_que_existe_cuenta_las_sobrescritas(self) -> None:
        self.metadatos["banco:importada"] = _meta("banco:importada", source="banco",
                                                  statistics_unit_of_measurement="kWh")
        self.filas["banco:importada"] = [{"start": _HORA_MS}, {"start": _HORA_MS + 3600000},
                                         {"start": _HORA_MS - 3600000}]
        r = await self.tool(metadata=_metadata(), stats=_stats())
        p = r["preview"]
        self.assertIs(p["exists"], True)
        self.assertEqual(p["current_metadata"]["statistics_unit_of_measurement"], "kWh")
        self.assertEqual(p["overwritten_rows"], 2)
        lectura = [x for x in self.enviados if x["type"] == "recorder/statistics_during_period"]
        self.assertEqual(len(lectura), 1)
        self.assertEqual((lectura[0]["start_time"], lectura[0]["end_time"], lectura[0]["period"]),
                         (_HORA, "2026-03-01T13:00:00+00:00", "hour"))

    async def test_rango_largo_no_cuenta(self) -> None:
        self.metadatos["banco:importada"] = _meta("banco:importada", source="banco")
        stats = _stats(2)
        stats.append({"start": "2026-04-15T00:00:00+00:00", "sum": 9.0})
        r = await self.tool(metadata=_metadata(), stats=stats)
        p = r["preview"]
        self.assertIsNone(p["overwritten_rows"])
        self.assertIn("31 days", p["overwritten_rows_reason"])
        self.assertFalse([x for x in self.enviados
                          if x["type"] == "recorder/statistics_during_period"])

    async def test_aviso_si_es_de_una_entidad(self) -> None:
        self.estados["sensor.consumo"] = {"entity_id": "sensor.consumo", "state": "1"}
        r = await self.tool(metadata=_metadata("sensor.consumo"), stats=_stats())
        self.assertIn("recorder", r["preview"]["recorded_entity_warning"])

    async def test_confirmacion_normalizada(self) -> None:
        meta = _metadata()
        stats = list(reversed(_stats()))
        stats[0]["last_reset"] = "2026-03-01T02:00:00+02:00"
        r = await self.tool(metadata=meta, stats=stats)
        hecho = await self.tool(metadata=meta, stats=stats,
                                confirmation_token=r["confirmation_token"])
        self.assertEqual(hecho["queued"], True)
        self.assertEqual(hecho["rows"], 3)
        [enviado] = self._escrituras()
        self.assertEqual(enviado["type"], "recorder/import_statistics")
        self.assertEqual(enviado["metadata"], meta)
        self.assertNotIn("has_mean", enviado["metadata"])
        self.assertEqual([f["start"] for f in enviado["stats"]],
                         [_HORA, "2026-03-01T11:00:00+00:00", "2026-03-01T12:00:00+00:00"])
        self.assertEqual(enviado["stats"][2]["last_reset"], "2026-03-01T00:00:00+00:00")

    async def test_argumentos_invalidos_sin_llamar(self) -> None:
        stats = _stats()
        casos = [
            {"stats": [{**stats[0], "start": "2026-03-01T10:00:00"}]},
            {"stats": [{**stats[0], "start": "2026-03-01T10:30:00+00:00"}]},
            {"stats": [{**stats[0], "start": "2026-03-01T10:00:00+05:30"}]},
            {"stats": [stats[0], {**stats[0], "start": "2026-03-01T10:00:00Z"}]},
            {"stats": []},
            {"stats": [{"start": "2026-03-01T10:00:00Z", "sum": 1.0}] * 2},
            {"stats": [{**stats[0], "sum": float("nan")}]},
            {"stats": [{**stats[0], "sum": None}]},
            {"stats": [{**stats[0], "otra": 1}]},
            {"stats": [{"sum": 1.0}]},
            {"stats": None},
            {"stats": "no"},
            {"metadata": _metadata(mean_type=3)},
            {"metadata": {**_metadata(), "has_mean": False}},
            {"metadata": {**_metadata(), "otra": 1}},
            {"metadata": _metadata("sensor.x", source="banco")},
            {"metadata": _metadata("banco:x", source="otra")},
            {"metadata": {k: v for k, v in _metadata().items() if k != "has_sum"}},
            {"metadata": {k: v for k, v in _metadata().items() if k != "mean_type"}},
            {"metadata": _metadata("Nada")},
            {"metadata": "no"},
        ]
        for caso in casos:
            with self.subTest(caso=caso):
                args = {"metadata": _metadata(), "stats": stats, **caso}
                r = await self.tool(**args)
                self.assertEqual(r["error"], "invalid_argument", r)
        self.ha.ws_send.assert_not_awaited()

    async def test_limite_de_filas(self) -> None:
        r = await self.tool(metadata=_metadata(), stats=_stats(5001, "2026-01-01T00:00:00+00:00"))
        self.assertEqual(r["error"], "invalid_argument")
        self.assertIn("5000", r["detail"])
        self.ha.ws_send.assert_not_awaited()
        r = await self.tool(metadata=_metadata(), stats=_stats(5000, "2026-01-01T00:00:00+00:00"))
        self.assertIn("confirmation_token", r)

    async def test_error_de_ha_al_confirmar(self) -> None:
        args = {"metadata": _metadata(unit_class="temperature"), "stats": _stats()}
        r = await self.tool(**args)
        self.fallos["recorder/import_statistics"] = _ha_error(
            "home_assistant_error", f"Unsupported unit token={_CENTINELA}")
        hecho = await self.tool(**args, confirmation_token=r["confirmation_token"])
        self.assertEqual(hecho["error"], "ha_command_failed")
        self.assertNotIn(_CENTINELA, json.dumps(hecho))

    async def test_log_sin_ids_ni_valores(self) -> None:
        args = {"metadata": _metadata(), "stats": _stats()}
        with capture_logs() as logs:
            r = await self.tool(**args)
            await self.tool(**args, confirmation_token=r["confirmation_token"])
        texto = json.dumps(logs, default=str)
        for prohibido in ("banco:importada", "Importada", "2026-03", "kWh"):
            self.assertNotIn(prohibido, texto)
        self.assertIn("ha_import_statistics_ok", texto)


class TestTokenTramo2(_BaseTramo2):
    """T023 — el token de las dos (FR-005, FR-007, SC-003)."""

    async def _no_casa(self, tool: str, previa: dict[str, Any], otra: dict[str, Any]) -> None:
        r = await self.t[tool](**previa)
        no = await self.t[tool](**otra, confirmation_token=r["confirmation_token"])
        self.assertIn("does not match", no["error"])
        self._sin_escrituras()

    async def test_cambiar_ajuste_unidad_o_instante_no_casa(self) -> None:
        tool = "ha_adjust_statistics_sum"
        base = {"statistic_id": "sensor.consumo", "start_time": _HORA,
                "adjustment": 5, "adjustment_unit": "kWh"}
        await self._no_casa(tool, base, {**base, "adjustment": 6})
        await self._no_casa(tool, base, {**base, "adjustment_unit": "Wh"})
        await self._no_casa(tool, base, {**base, "start_time": "2026-03-01T11:00:00+00:00"})
        await self._no_casa(tool, base, {**base, "statistic_id": "sensor.solar"})

    async def test_ajuste_de_un_solo_uso(self) -> None:
        tool = self.t["ha_adjust_statistics_sum"]
        args = {"statistic_id": "sensor.consumo", "start_time": _HORA,
                "adjustment": 5, "adjustment_unit": "kWh"}
        r = await tool(**args)
        await tool(**args, confirmation_token=r["confirmation_token"])
        otra = await tool(**args, confirmation_token=r["confirmation_token"])
        self.assertIn("already used", otra["error"])
        self.assertEqual(len(self._escrituras()), 1)

    async def test_confirmar_sin_stats_usa_lo_guardado(self) -> None:
        tool = self.t["ha_import_statistics"]
        r = await tool(metadata=_metadata(), stats=_stats())
        self.assertEqual(r["confirm_with"], ["confirmation_token", "metadata"])
        hecho = await tool(metadata=_metadata(), confirmation_token=r["confirmation_token"])
        self.assertIs(hecho["queued"], True)
        self.assertEqual(hecho["rows"], 3)
        self.assertEqual(len(self._escrituras()[0]["stats"]), 3)

    async def test_stats_distinto_no_casa(self) -> None:
        otra = _stats()
        otra[1]["sum"] = 99.0
        await self._no_casa("ha_import_statistics",
                            {"metadata": _metadata(), "stats": _stats()},
                            {"metadata": _metadata(), "stats": otra})
        await self._no_casa("ha_import_statistics",
                            {"metadata": _metadata(), "stats": _stats()},
                            {"metadata": _metadata(name="Otra")})

    async def test_misma_fila_en_otra_zona_casa(self) -> None:
        tool = self.t["ha_import_statistics"]
        r = await tool(metadata=_metadata(), stats=_stats())
        hecho = await tool(metadata=_metadata(), stats=_stats(desde="2026-03-01T10:00:00Z"),
                           confirmation_token=r["confirmation_token"])
        self.assertIs(hecho["queued"], True)

    async def test_metadatos_cambiados_entre_medias(self) -> None:
        casos = [
            ("ha_adjust_statistics_sum", {"statistic_id": "sensor.consumo", "start_time": _HORA,
                                          "adjustment": 5, "adjustment_unit": "kWh"}),
            ("ha_import_statistics", {"metadata": _metadata("sensor.consumo"),
                                      "stats": _stats()}),
        ]
        for tool, args in casos:
            with self.subTest(tool=tool):
                self.metadatos["sensor.consumo"] = _meta("sensor.consumo")
                r = await self.t[tool](**args)
                self.metadatos["sensor.consumo"]["statistics_unit_of_measurement"] = "kWh"
                no = await self.t[tool](**args, confirmation_token=r["confirmation_token"])
                self.assertEqual(no["error"], "statistics_changed")
                self._sin_escrituras()
        # Importar una que no existía y que alguien crea entre medias.
        r = await self.t["ha_import_statistics"](metadata=_metadata(), stats=_stats())
        self.metadatos["banco:importada"] = _meta("banco:importada", source="banco")
        no = await self.t["ha_import_statistics"](metadata=_metadata(),
                                                  confirmation_token=r["confirmation_token"])
        self.assertEqual(no["error"], "statistics_changed")
        self._sin_escrituras()

    async def test_tope_lleno_pide_reenviar_stats(self) -> None:
        tool = self.t["ha_import_statistics"]
        original = security.CONFIRMATION_STORED_MAX_BYTES
        security.CONFIRMATION_STORED_MAX_BYTES = 10
        try:
            r = await tool(metadata=_metadata(), stats=_stats())
        finally:
            security.CONFIRMATION_STORED_MAX_BYTES = original
        self.assertNotIn("omit_on_confirm", r)
        self.assertIn("stats", r["confirm_hint"])
        no = await tool(metadata=_metadata(), confirmation_token=r["confirmation_token"])
        self.assertIn("no stored value for: stats", no["error"])
        self._sin_escrituras()
        hecho = await tool(metadata=_metadata(), stats=_stats(),
                           confirmation_token=r["confirmation_token"])
        self.assertIs(hecho["queued"], True)


if __name__ == "__main__":
    unittest.main()
