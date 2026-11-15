"""Preferencias del panel de energía, familia `energy` (spec 020, tramo 3).

T037–T039: `ha_get_energy_prefs` y `ha_update_energy_prefs` (FR-010…FR-012,
FR-017…FR-019).

El doble de HA (T039) sigue el código de Core 2026.11 consultado en
`homeassistant/components/energy/websocket_api.py` y `data.py`:
- `energy/get_prefs` responde `manager.data` o, si nunca se guardaron, el
  error `not_found` con el texto «No prefs»;
- `energy/save_prefs` (`EnergyManager.async_update`) parte de las
  preferencias por defecto si no había, reemplaza ENTERA cada lista que
  recibe, conserva las demás y responde `manager.data` (lo guardado);
- `energy/*` sin la integración cargada: `unknown_command`.
Las estadísticas conocidas las da `recorder/get_statistics_metadata`. Tokens
reales de `security.py` en una carpeta temporal. Datos ficticios
(`sensor.consumo`, `sensor.solar`, `centinela-020`).

Controles negativos (T050), con recuentos en el commit del tramo:
- (a) no pasar `estado` → caen los de `ESTADO_CAMBIADO`;
- (b) enviar las tres listas aunque solo llegue una → cae
  `test_confirmar_envia_solo_las_listas_recibidas`;
- (c) no tratar `not_found` → caen los de `configured: false`;
- (d) quitar `warnings` → caen los de avisos.
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

from hermes import security
from hermes.command_table import TABLE_HA_CORE
from hermes.ha import HAConnectionError
from hermes.security import ESTADO_CAMBIADO, REDACTED_MARKER
from hermes.tools import energy as mod

_CENTINELA = "centinela-020"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJh"

_RED = {"type": "grid", "stat_energy_from": "sensor.red_importada",
        "stat_energy_to": None, "stat_cost": None, "stat_compensation": None,
        "entity_energy_price": None, "number_energy_price": 0.15,
        "entity_energy_price_export": None, "number_energy_price_export": None,
        "cost_adjustment_day": 0.0}
_SOLAR = {"type": "solar", "stat_energy_from": "sensor.solar",
          "config_entry_solar_forecast": None}
_NEVERA = {"stat_consumption": "sensor.nevera", "name": "Nevera"}
_HORNO = {"stat_consumption": "sensor.horno"}


def _prefs() -> dict[str, Any]:
    return {"energy_sources": [copy.deepcopy(_RED), copy.deepcopy(_SOLAR)],
            "device_consumption": [copy.deepcopy(_NEVERA)],
            "device_consumption_water": []}


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _ha_error(codigo: str, texto: str = "fallo") -> HAConnectionError:
    return HAConnectionError(f"HA WS command failed: {texto}", code=codigo)


class _Base(unittest.IsolatedAsyncioTestCase):
    """T039: el doble de HA de la energía."""

    max_bytes = 131_072

    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.prefs: dict[str, Any] | None = _prefs()
        self.conocidas = {"sensor.red_importada", "sensor.solar", "sensor.nevera",
                          "sensor.horno"}
        self.enviados: list[dict[str, Any]] = []
        self.fallos: dict[str, HAConnectionError] = {}
        self.ha = MagicMock()
        self.ha.wait_ready = AsyncMock(return_value=True)
        self.ha.ws_send = AsyncMock(side_effect=self._ws_send)
        mcp = DummyMCP()
        mod.register(mcp, self.ha, response_max_bytes=self.max_bytes)
        self.t = mcp.tools

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def _ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.enviados.append(copy.deepcopy(payload))
        tipo = payload["type"]
        if tipo in self.fallos:
            raise self.fallos[tipo]
        if tipo == "energy/get_prefs":
            if self.prefs is None:
                raise _ha_error("not_found", "No prefs")
            return copy.deepcopy(self.prefs)
        if tipo == "energy/save_prefs":
            datos = (copy.deepcopy(self.prefs) if self.prefs is not None else
                     {"energy_sources": [], "device_consumption": [],
                      "device_consumption_water": []})
            for clave in mod._LISTAS:
                if clave in payload:
                    datos[clave] = copy.deepcopy(payload[clave])
            self.prefs = datos
            return copy.deepcopy(datos)
        if tipo == "recorder/get_statistics_metadata":
            return [{"statistic_id": s, "source": "recorder"}
                    for s in payload["statistic_ids"] if s in self.conocidas]
        raise AssertionError(f"comando inesperado {tipo}")

    def _guardados(self) -> list[dict[str, Any]]:
        return [p for p in self.enviados if p["type"] == "energy/save_prefs"]


# ── ha_get_energy_prefs (T037) ───────────────────────────────────────────────

class TestLeer(_Base):
    async def test_devuelve_las_preferencias(self) -> None:
        r = await self.t["ha_get_energy_prefs"]()
        self.assertEqual(r, {"configured": True, **_prefs()})
        self.assertEqual(self.enviados, [{"type": "energy/get_prefs"}])

    async def test_sin_preferencias_configured_false(self) -> None:
        # Control negativo (T050 c): sin tratar `not_found`, cae.
        self.prefs = None
        r = await self.t["ha_get_energy_prefs"]()
        self.assertEqual(r, {"configured": False, "energy_sources": [],
                             "device_consumption": [], "device_consumption_water": []})

    async def test_lista_de_agua_ausente_es_vacia(self) -> None:
        # Preferencias antiguas sin `device_consumption_water` (NotRequired).
        del self.prefs["device_consumption_water"]
        r = await self.t["ha_get_energy_prefs"]()
        self.assertEqual(r["device_consumption_water"], [])

    async def test_sin_la_integracion(self) -> None:
        self.fallos["energy/get_prefs"] = _ha_error("unknown_command")
        r = await self.t["ha_get_energy_prefs"]()
        self.assertEqual(r["error"], "energy_not_loaded")
        self.assertIn("default_config", r["detail"])

    async def test_secreto_en_un_nombre_redactado(self) -> None:
        self.prefs["device_consumption"][0]["name"] = f"Bearer {_JWT}"
        r = await self.t["ha_get_energy_prefs"]()
        self.assertNotIn(_JWT, json.dumps(r))

    async def test_documento_grande_no_se_recorta(self) -> None:
        self.prefs["device_consumption"] = [
            {"stat_consumption": f"sensor.dispositivo_{n}", "name": "x" * 200}
            for n in range(800)]
        r = await self.t["ha_get_energy_prefs"]()
        self.assertEqual(r["error"], "response_too_large")

    async def test_core_caido(self) -> None:
        self.fallos["energy/get_prefs"] = HAConnectionError("Not connected to HA")
        r = await self.t["ha_get_energy_prefs"]()
        self.assertEqual(r, {"error": "Not connected to HA"})

    async def test_log_sin_el_documento(self) -> None:
        with capture_logs() as logs:
            await self.t["ha_get_energy_prefs"]()
        texto = json.dumps(logs, default=str)
        self.assertNotIn("sensor.", texto)
        self.assertNotIn("Nevera", texto)
        self.assertEqual(logs[-1]["device_consumption"], 1)


# ── ha_update_energy_prefs (T038) ────────────────────────────────────────────

class TestGuardarValidacion(_Base):
    async def _invalido(self, **kwargs: Any) -> dict[str, Any]:
        r = await self.t["ha_update_energy_prefs"](**kwargs)
        self.assertEqual(r["error"], "invalid_argument", r)
        self.assertEqual(self.enviados, [])
        return r

    async def test_ninguna_lista(self) -> None:
        await self._invalido()

    async def test_lista_que_no_es_de_objetos(self) -> None:
        await self._invalido(device_consumption=["sensor.horno"])
        await self._invalido(energy_sources={"type": "solar"})

    async def test_fuente_de_tipo_desconocido(self) -> None:
        r = await self._invalido(energy_sources=[{"type": "eolica",
                                                  "stat_energy_from": "sensor.x"}])
        self.assertEqual(r["field"], "energy_sources")

    async def test_dispositivo_sin_stat_consumption(self) -> None:
        await self._invalido(device_consumption_water=[{"name": "Riego"}])

    async def test_valor_tapado_reenviado(self) -> None:
        await self._invalido(device_consumption=[
            {"stat_consumption": "sensor.horno", "name": REDACTED_MARKER}])


class TestGuardarVistaPrevia(_Base):
    async def test_solo_dispositivos_conserva_las_fuentes(self) -> None:
        r = await self.t["ha_update_energy_prefs"](device_consumption=[_HORNO])
        self.assertEqual(self._guardados(), [])
        self.assertIn("confirmation_token", r)
        p = r["preview"]
        self.assertEqual(p["kept"], ["energy_sources", "device_consumption_water"])
        self.assertEqual(list(p["changes"]), ["device_consumption"])
        c = p["changes"]["device_consumption"]
        self.assertEqual((c["before_count"], c["after_count"]), (1, 1))
        self.assertEqual(c["added"], [{"stat_consumption": "sensor.horno"}])
        self.assertEqual(c["removed"], [{"stat_consumption": "sensor.nevera"}])
        self.assertEqual(c["changed"], [])
        # Antes y después de la lista que cambia.
        self.assertEqual(p["current"], {"device_consumption": [_NEVERA]})
        self.assertEqual(p["new"], {"device_consumption": [_HORNO]})
        self.assertIs(p["removes_all_sources"], False)
        self.assertIs(p["irreversible"], False)
        # Avisa de que se quita un dispositivo.
        self.assertIn({"list": "device_consumption", "problem": "removes_items",
                       "count": 1, "detail": "1 element(s) of device_consumption will "
                       "be removed."}, p["warnings"])

    async def test_cambiado_por_su_identidad(self) -> None:
        red = dict(_RED, number_energy_price=0.2)
        r = await self.t["ha_update_energy_prefs"](energy_sources=[red, _SOLAR])
        c = r["preview"]["changes"]["energy_sources"]
        self.assertEqual(c["added"], [])
        self.assertEqual(c["removed"], [])
        self.assertEqual(c["changed"], [{"type": "grid",
                                         "stat_energy_from": "sensor.red_importada"}])
        self.assertEqual(r["preview"]["warnings"], [])

    async def test_quitar_todas_las_fuentes_lo_avisa(self) -> None:
        r = await self.t["ha_update_energy_prefs"](energy_sources=[])
        p = r["preview"]
        self.assertIs(p["removes_all_sources"], True)
        self.assertEqual(p["changes"]["energy_sources"]["removed"],
                         [{"type": "grid", "stat_energy_from": "sensor.red_importada"},
                          {"type": "solar", "stat_energy_from": "sensor.solar"}])
        self.assertEqual(self._guardados(), [])

    async def test_estadisticas_desconocidas_en_warnings(self) -> None:
        # Control negativo (T050 d): sin `warnings`, cae.
        r = await self.t["ha_update_energy_prefs"](device_consumption=[
            _NEVERA, {"stat_consumption": "sensor.nueva", "included_in_stat": "sensor.otra"}])
        avisos = [a for a in r["preview"]["warnings"] if a["problem"] == "unknown_statistic"]
        self.assertEqual(avisos, [{"statistic_id": "sensor.nueva", "problem": "unknown_statistic"},
                                  {"statistic_id": "sensor.otra", "problem": "unknown_statistic"}])

    async def test_sin_recorder_avisa_que_no_se_comprobo(self) -> None:
        self.fallos["recorder/get_statistics_metadata"] = _ha_error("unknown_command")
        r = await self.t["ha_update_energy_prefs"](device_consumption=[_HORNO])
        self.assertIn("confirmation_token", r)
        self.assertIn("statistics_not_checked",
                      [a["problem"] for a in r["preview"]["warnings"]])

    async def test_sin_preferencias_before_count_cero(self) -> None:
        self.prefs = None
        r = await self.t["ha_update_energy_prefs"](energy_sources=[_SOLAR])
        p = r["preview"]
        self.assertIs(p["configured"], False)
        c = p["changes"]["energy_sources"]
        self.assertEqual((c["before_count"], c["after_count"]), (0, 1))
        self.assertIs(p["removes_all_sources"], False)

    async def test_sin_poder_leer_no_hay_token(self) -> None:
        self.fallos["energy/get_prefs"] = _ha_error("home_assistant_error")
        r = await self.t["ha_update_energy_prefs"](device_consumption=[_HORNO])
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(r["error"], "ha_command_failed")

    async def test_sin_la_integracion(self) -> None:
        self.fallos["energy/get_prefs"] = _ha_error("unknown_command")
        r = await self.t["ha_update_energy_prefs"](device_consumption=[_HORNO])
        self.assertEqual(r["error"], "energy_not_loaded")


class TestGuardarConfirmacion(_Base):
    async def _vista(self, **kwargs: Any) -> str:
        r = await self.t["ha_update_energy_prefs"](**kwargs)
        return r["confirmation_token"]

    async def test_confirmar_envia_solo_las_listas_recibidas(self) -> None:
        # Control negativo (T050 b): enviar las tres listas → cae.
        token = await self._vista(device_consumption=[_NEVERA, _HORNO])
        r = await self.t["ha_update_energy_prefs"](
            device_consumption=[_NEVERA, _HORNO], confirmation_token=token)
        self.assertEqual(self._guardados(), [
            {"type": "energy/save_prefs", "device_consumption": [_NEVERA, _HORNO]}])
        self.assertIs(r["saved"], True)
        self.assertEqual(r["prefs"]["device_consumption"], [_NEVERA, _HORNO])
        # Las fuentes, conservadas por HA.
        self.assertEqual(r["prefs"]["energy_sources"], [_RED, _SOLAR])

    async def test_otra_lista_al_confirmar_no_casa(self) -> None:
        token = await self._vista(device_consumption=[_HORNO])
        for kwargs in ({"device_consumption": [_NEVERA]},
                       {"device_consumption": [_HORNO], "energy_sources": []},
                       {"device_consumption_water": [_HORNO]}):
            with self.subTest(kwargs=kwargs):
                r = await self.t["ha_update_energy_prefs"](**kwargs,
                                                           confirmation_token=token)
                self.assertIn("does not match", r["error"])
        self.assertEqual(self._guardados(), [])

    async def test_cambiadas_entre_medias(self) -> None:
        # Control negativo (T050 a): sin `estado`, cae.
        token = await self._vista(device_consumption=[_HORNO])
        self.prefs["energy_sources"].pop()  # alguien guarda desde la interfaz
        r = await self.t["ha_update_energy_prefs"](device_consumption=[_HORNO],
                                                   confirmation_token=token)
        self.assertEqual(r, {"error": "energy_prefs_changed", "detail": ESTADO_CAMBIADO})
        self.assertEqual(self._guardados(), [])

    async def test_guardadas_por_otro_tras_una_vista_sin_preferencias(self) -> None:
        self.prefs = None
        token = await self._vista(energy_sources=[_SOLAR])
        self.prefs = {"energy_sources": [_RED], "device_consumption": [],
                      "device_consumption_water": []}
        r = await self.t["ha_update_energy_prefs"](energy_sources=[_SOLAR],
                                                   confirmation_token=token)
        self.assertEqual(r["detail"], ESTADO_CAMBIADO)
        self.assertEqual(self._guardados(), [])

    async def test_sin_preferencias_primera_vez(self) -> None:
        self.prefs = None
        token = await self._vista(energy_sources=[_SOLAR])
        r = await self.t["ha_update_energy_prefs"](energy_sources=[_SOLAR],
                                                   confirmation_token=token)
        self.assertIs(r["saved"], True)
        self.assertEqual(r["prefs"]["energy_sources"], [_SOLAR])

    async def test_sin_poder_leer_al_confirmar_no_ejecuta(self) -> None:
        token = await self._vista(device_consumption=[_HORNO])
        self.fallos["energy/get_prefs"] = HAConnectionError("Not connected to HA")
        r = await self.t["ha_update_energy_prefs"](device_consumption=[_HORNO],
                                                   confirmation_token=token)
        self.assertEqual(r, {"error": "Not connected to HA"})
        self.assertEqual(self._guardados(), [])
        # El token sigue pendiente: se puede reintentar.
        del self.fallos["energy/get_prefs"]
        r = await self.t["ha_update_energy_prefs"](device_consumption=[_HORNO],
                                                   confirmation_token=token)
        self.assertIs(r["saved"], True)

    async def test_esquema_rechazado_por_ha_redactado(self) -> None:
        token = await self._vista(device_consumption=[_HORNO])
        self.fallos["energy/save_prefs"] = _ha_error(
            "invalid_format", f"extra keys not allowed {_CENTINELA} Bearer {_JWT}")
        r = await self.t["ha_update_energy_prefs"](device_consumption=[_HORNO],
                                                   confirmation_token=token)
        self.assertEqual((r["error"], r["ha_code"], r["table_ha_core"]),
                         ("ha_command_failed", "invalid_format", TABLE_HA_CORE))
        self.assertNotIn(_JWT, json.dumps(r))

    async def test_log_con_recuentos_y_sin_estadisticas(self) -> None:
        with capture_logs() as logs:
            token = await self._vista(device_consumption=[_NEVERA, _HORNO])
            await self.t["ha_update_energy_prefs"](device_consumption=[_NEVERA, _HORNO],
                                                   confirmation_token=token)
        texto = json.dumps(logs, default=str)
        self.assertNotIn("sensor.", texto)
        self.assertNotIn("Nevera", texto)
        eventos = {e["event"]: e for e in logs}
        self.assertEqual(eventos["ha_update_energy_prefs_preview"]["device_consumption"], 2)
        self.assertEqual(eventos["ha_update_energy_prefs_ok"]["device_consumption"], 2)


if __name__ == "__main__":
    unittest.main()
