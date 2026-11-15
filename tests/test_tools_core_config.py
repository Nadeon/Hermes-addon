"""Tools de la configuración del núcleo (spec 021, tramo a; T004 y T005).

`ha_get_core_config` y `ha_update_core_config` con Home Assistant simulado
(`AsyncMock` de `ws_send` que responde por `type` y FALLA si recibe un
`config/core/update` que el test no espera). Datos ficticios: la ubicación
de ejemplo de HA, `homeassistant.tailXXXX.ts.net` y el centinela
`centinela-021`, que no puede aparecer en ninguna respuesta, en el log de
Hermes ni en los ficheros de token.

Controles negativos (T018), comprobados y con recuentos en el commit:
(a) mandar `time_zone` junto con el resto → caen los de la zona primero
(`TestZonaHorariaPrimero`, 3); (b) no atar `estado` → cae
`test_estado_cambiado_no_escribe`; (d) quitar el aviso `yaml_source` → cae
`test_aviso_yaml`; (e) registrar el valor de un campo en el log → cae
`test_log_sin_valores`.
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
import hermes.tools.core_config as mod
from hermes.ha import HAConnectionError

_CENTINELA = "centinela-021"
_URL = "https://homeassistant.tailXXXX.ts.net"

_METRIC = {"length": "km", "accumulated_precipitation": "mm", "area": "m²",
           "mass": "g", "pressure": "Pa", "temperature": "°C", "volume": "L",
           "wind_speed": "m/s"}
_US = {**_METRIC, "length": "mi", "temperature": "°F"}

_CONFIG = {
    "allowlist_external_dirs": ["/config/www"],
    "allowlist_external_urls": [],
    "components": ["api", "http"],
    "config_dir": "/config",
    "config_source": "storage",
    "country": "US",
    "currency": "USD",
    "debug": False,
    "elevation": 430,
    "external_url": None,
    "internal_url": None,
    "language": "en",
    "latitude": 32.87336,
    "location_name": "Casa",
    "logging": {},
    "longitude": -117.22743,
    "radius": 100,
    "recovery_mode": False,
    "safe_mode": False,
    "state": "RUNNING",
    "time_zone": "Etc/UTC",
    "unit_system": _METRIC,
    "version": "2026.11.1",
    "whitelist_external_dirs": ["/config/www"],
}


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.config = copy.deepcopy(_CONFIG)
        self.enviados: list[dict[str, Any]] = []
        # Errores de `config/core/update` por orden de llamada (None = ok).
        self.fallos_update: list[HAConnectionError | None] = []
        self.fallo_get: HAConnectionError | None = None
        self.escrituras_esperadas = 0
        self.ha = MagicMock()
        self.ha.wait_ready = AsyncMock(return_value=True)
        self.ha.ws_send = AsyncMock(side_effect=self._ws_send)
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha, response_max_bytes=131_072)
        self.t = self.mcp.tools

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def _ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.enviados.append(payload)
        tipo = payload["type"]
        if tipo == "get_config":
            if self.fallo_get is not None:
                raise self.fallo_get
            return copy.deepcopy(self.config)
        if tipo == "config/core/update":
            n = len(self.updates())
            if n > self.escrituras_esperadas:
                raise AssertionError(f"escritura inesperada: {payload}")
            if n <= len(self.fallos_update) and self.fallos_update[n - 1] is not None:
                raise self.fallos_update[n - 1]
            for k, v in payload.items():
                if k in mod.CAMPOS and k != "unit_system":
                    self.config[k] = v
            if payload.get("unit_system") == "us_customary":
                self.config["unit_system"] = _US
            self.config["config_source"] = "storage"
            return None
        raise AssertionError(f"comando inesperado: {payload}")

    def updates(self) -> list[dict[str, Any]]:
        return [p for p in self.enviados if p["type"] == "config/core/update"]

    def ficheros_de_tokens(self) -> str:
        return "".join(p.read_text(encoding="utf-8") for p in Path(self.temp_dir.name).glob("*"))

    async def confirmar(self, **args: Any) -> Any:
        vista = await self.t["ha_update_core_config"](**args)
        self.assertIn("confirmation_token", vista, vista)
        return await self.t["ha_update_core_config"](
            **args, confirmation_token=vista["confirmation_token"])


# ── ha_get_core_config (T004) ────────────────────────────────────────────────


class TestGetCoreConfig(_Base):
    async def test_solo_los_editables(self) -> None:
        r = await self.t["ha_get_core_config"]()
        self.assertEqual(set(r), {*mod.CAMPOS, "config_source", "version"})
        self.assertEqual(r["unit_system"], "metric")
        self.assertEqual((r["latitude"], r["time_zone"], r["version"]),
                         (32.87336, "Etc/UTC", "2026.11.1"))
        self.assertNotIn("components", r)
        self.assertNotIn("allowlist_external_dirs", r)

    async def test_us_customary(self) -> None:
        self.config["unit_system"] = _US
        r = await self.t["ha_get_core_config"]()
        self.assertEqual(r["unit_system"], "us_customary")

    async def test_unidades_que_no_cuadran(self) -> None:
        self.config["unit_system"] = {**_METRIC, "temperature": "°F"}
        r = await self.t["ha_get_core_config"]()
        self.assertIsNone(r["unit_system"])
        self.assertEqual(r["unit_system_detail"]["temperature"], "°F")

    async def test_core_caido(self) -> None:
        self.fallo_get = HAConnectionError("Home Assistant not connected")
        r = await self.t["ha_get_core_config"]()
        self.assertEqual(r, {"error": "Home Assistant not connected"})

    async def test_log_sin_valores(self) -> None:
        with capture_logs() as logs:
            await self.t["ha_get_core_config"]()
        texto = json.dumps(logs, default=str)
        for valor in ("32.87336", "Etc/UTC", "Casa"):
            self.assertNotIn(valor, texto)


# ── ha_update_core_config: validación (T005 a) ───────────────────────────────


class TestValidacion(_Base):
    async def test_cada_caso_sin_llamar_a_ha(self) -> None:
        casos = [
            ({}, "fields"),
            ({"latitude": 91}, "latitude"),
            ({"longitude": -181.5}, "longitude"),
            ({"latitude": True}, "latitude"),
            # Cierre 1.2.0: lanzaba `OverflowError` (control negativo comprobado).
            ({"latitude": 10**400}, "latitude"),
            ({"elevation": 1.5}, "elevation"),
            ({"radius": -1}, "radius"),
            ({"unit_system": "imperial"}, "unit_system"),
            ({"country": "es"}, "country"),
            ({"currency": "eu"}, "currency"),
            ({"language": "Español"}, "language"),
            ({"time_zone": "Europe/ Madrid"}, "time_zone"),
            ({"external_url": f"{_URL}/lovelace"}, "external_url"),
            ({"internal_url": "ftp://192.0.2.10"}, "internal_url"),
            ({"location_name": ""}, "location_name"),
            ({"update_units": True}, "update_units"),
            ({"currency": "EUR", "update_units": True}, "update_units"),
        ]
        for args, campo in casos:
            with self.subTest(args=args):
                r = await self.t["ha_update_core_config"](**args)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", campo))
        self.ha.ws_send.assert_not_awaited()

    async def test_urls_validas(self) -> None:
        for url in (_URL, "http://192.0.2.10:8123", f"{_URL}/", ""):
            with self.subTest(url=url):
                r = await self.t["ha_update_core_config"](external_url=url)
                self.assertNotIn("error", r)


# ── Vista previa (T005 b, c, d) ──────────────────────────────────────────────


class TestVistaPrevia(_Base):
    async def test_antes_y_despues_solo_de_lo_pedido(self) -> None:
        r = await self.t["ha_update_core_config"](
            time_zone="Europe/Madrid", currency="USD", location_name="Casa nueva")
        p = r["preview"]
        self.assertEqual(p["changes"], {
            "time_zone": {"before": "Etc/UTC", "after": "Europe/Madrid"},
            "location_name": {"before": "Casa", "after": "Casa nueva"},
        })
        self.assertEqual(p["unchanged"], ["currency"])
        # Nada de lo que no se pidió (la ubicación de la casa) sale.
        texto = json.dumps(r)
        self.assertNotIn("32.87336", texto)
        self.assertEqual(p["config_source"], "storage")
        # Sin token no se escribe.
        self.assertEqual(self.updates(), [])

    async def test_un_aviso_por_grupo(self) -> None:
        casos = {
            "time_zone": {"time_zone": "Europe/Madrid"},
            "unit_system": {"unit_system": "us_customary"},
            "update_units": {"unit_system": "us_customary", "update_units": True},
            "location": {"radius": 250},
            "urls": {"external_url": _URL},
            "regional": {"language": "es"},
        }
        for codigo, args in casos.items():
            with self.subTest(codigo=codigo):
                r = await self.t["ha_update_core_config"](**args)
                avisos = r["preview"]["warnings"]
                self.assertTrue(any(a.startswith(f"{codigo}:") for a in avisos), avisos)
                self.assertFalse(any(a.startswith("yaml_source:") for a in avisos))

    async def test_aviso_yaml(self) -> None:
        self.config["config_source"] = "yaml"
        r = await self.t["ha_update_core_config"](radius=250)
        self.assertTrue(any(a.startswith("yaml_source:") for a in r["preview"]["warnings"]))
        self.assertEqual(r["preview"]["config_source"], "yaml")

    async def test_sin_cambios_sin_token(self) -> None:
        r = await self.t["ha_update_core_config"](
            latitude=32.87336, currency="USD", internal_url="")
        self.assertEqual(r, {"result": "no_changes"})
        self.assertEqual(list(Path(self.temp_dir.name).glob("*")), [])

    async def test_update_units_cuenta_como_cambio(self) -> None:
        r = await self.t["ha_update_core_config"](unit_system="metric", update_units=True)
        self.assertIn("confirmation_token", r)
        self.assertEqual(r["preview"]["changes"], {})

    async def test_lectura_fallida(self) -> None:
        self.fallo_get = HAConnectionError("Home Assistant not connected")
        r = await self.t["ha_update_core_config"](radius=10)
        self.assertEqual(r["error"], "preview_unavailable")


# ── Confirmación (T005 e, g, h) ──────────────────────────────────────────────


class TestConfirmacion(_Base):
    async def test_una_llamada_con_lo_pedido(self) -> None:
        self.escrituras_esperadas = 1
        r = await self.confirmar(currency="EUR", radius=100, external_url="")
        self.assertEqual(self.updates(), [{
            "type": "config/core/update", "currency": "EUR", "radius": 100,
            "external_url": None,
        }])
        self.assertEqual(r["result"], "ok")
        self.assertEqual(r["applied"], ["currency", "external_url", "radius"])
        # La configuración releída, solo de lo pedido.
        self.assertEqual(r["config"], {
            "currency": "EUR", "external_url": None, "radius": 100,
            "config_source": "storage", "version": "2026.11.1"})

    async def test_update_units_va_en_la_llamada(self) -> None:
        self.escrituras_esperadas = 1
        r = await self.confirmar(unit_system="us_customary", update_units=True)
        self.assertEqual(self.updates(), [{
            "type": "config/core/update", "unit_system": "us_customary",
            "update_units": True}])
        self.assertEqual(r["config"]["unit_system"], "us_customary")

    async def test_estado_cambiado_no_escribe(self) -> None:
        vista = await self.t["ha_update_core_config"](currency="EUR")
        self.config["country"] = "ES"  # otro cambio entre los dos pasos
        r = await self.t["ha_update_core_config"](
            currency="EUR", confirmation_token=vista["confirmation_token"])
        self.assertEqual(r, {"error": security.ESTADO_CAMBIADO})
        self.assertEqual(self.updates(), [])

    async def test_token_de_otros_argumentos(self) -> None:
        vista = await self.t["ha_update_core_config"](currency="EUR")
        r = await self.t["ha_update_core_config"](
            currency="GBP", confirmation_token=vista["confirmation_token"])
        self.assertIn("does not match", r["error"])
        self.assertEqual(self.updates(), [])

    async def test_token_de_otra_tool(self) -> None:
        otro = await security.create_confirmation_token("ha_set_log_level", {"currency": "EUR"})
        r = await self.t["ha_update_core_config"](
            currency="EUR", confirmation_token=otro["confirmation_token"])
        self.assertIn("error", r)
        self.assertEqual(self.updates(), [])

    async def test_error_de_ha_redactado(self) -> None:
        self.escrituras_esperadas = 1
        self.fallos_update = [HAConnectionError(
            f"invalid_info: bad value password={_CENTINELA}", code="invalid_info")]
        r = await self.confirmar(currency="EUR")
        self.assertEqual((r["error"], r["ha_code"]), ("ha_error", "invalid_info"))
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertNotIn(_CENTINELA, self.ficheros_de_tokens())

    async def test_comando_desconocido(self) -> None:
        self.escrituras_esperadas = 1
        self.fallos_update = [HAConnectionError("Unknown command.", code="unknown_command")]
        r = await self.confirmar(currency="EUR")
        self.assertEqual((r["error"], r["ha_code"]),
                         ("unsupported_by_ha_version", "unknown_command"))

    async def test_fichero_del_token_sin_valores(self) -> None:
        self.escrituras_esperadas = 1
        await self.confirmar(latitude=40.5, longitude=-3.25, external_url=_URL)
        texto = self.ficheros_de_tokens()
        for valor in ("40.5", "-3.25", "tailXXXX", "32.87336"):
            self.assertNotIn(valor, texto)

    async def test_log_sin_valores(self) -> None:
        self.escrituras_esperadas = 2
        with capture_logs() as logs:
            await self.t["ha_update_core_config"](latitude=40.5)
            await self.confirmar(latitude=40.5, time_zone="Europe/Madrid",
                                 external_url=_URL)
        texto = json.dumps(logs, default=str)
        for valor in ("40.5", "Europe/Madrid", "tailXXXX", "32.87336", "Etc/UTC"):
            self.assertNotIn(valor, texto)
        self.assertTrue(any(e.get("fields") for e in logs))


# ── Zona horaria sola y primero (T005 f) ─────────────────────────────────────


class TestZonaHorariaPrimero(_Base):
    async def test_dos_llamadas_la_zona_primero(self) -> None:
        self.escrituras_esperadas = 2
        r = await self.confirmar(time_zone="Europe/Madrid", currency="EUR")
        self.assertEqual(self.updates(), [
            {"type": "config/core/update", "time_zone": "Europe/Madrid"},
            {"type": "config/core/update", "currency": "EUR"},
        ])
        self.assertEqual(r["applied"], ["time_zone", "currency"])

    async def test_zona_invalida_no_hay_segunda(self) -> None:
        self.escrituras_esperadas = 1
        self.fallos_update = [HAConnectionError(
            "Received invalid time zone Mars/Base", code="invalid_info")]
        r = await self.confirmar(time_zone="Mars/Base", currency="EUR")
        self.assertEqual(len(self.updates()), 1)
        self.assertEqual((r["error"], r["ha_code"]), ("ha_error", "invalid_info"))
        self.assertNotIn("applied", r)

    async def test_falla_la_segunda_parcial(self) -> None:
        self.escrituras_esperadas = 2
        self.fallos_update = [None, HAConnectionError(
            "bad currency", code="invalid_info")]
        r = await self.confirmar(time_zone="Europe/Madrid", currency="EUR")
        self.assertEqual(r["result"], "partial")
        self.assertEqual((r["applied"], r["failed"]), (["time_zone"], ["currency"]))
        self.assertEqual(r["error"], "invalid_info")
        self.assertEqual(r["config"]["time_zone"], "Europe/Madrid")

    async def test_solo_la_zona_una_llamada(self) -> None:
        self.escrituras_esperadas = 1
        await self.confirmar(time_zone="Europe/Madrid")
        self.assertEqual(self.updates(), [
            {"type": "config/core/update", "time_zone": "Europe/Madrid"}])


# ── URL con credenciales (revisión final 1.2.0, BAJO-2) ─────────────────────
# Control negativo, comprobado: con `redact_structure` (solo por clave) en las
# tres salidas, como antes, caen las tres de esta clase.

_URL_CON_CLAVE = "https://usuario:centinela-021@homeassistant.tailXXXX.ts.net"
_URL_TAPADA = "https://usuario:***@homeassistant.tailXXXX.ts.net"


class TestUrlConCredenciales(_Base):
    async def test_al_leer_sale_tapada(self) -> None:
        # `get_config` de HA 2026.11.1 da las URLs tal cual las guarda.
        self.config["external_url"] = _URL_CON_CLAVE
        self.config["internal_url"] = "http://usuario:centinela-021@192.0.2.10:8123"
        r = await self.t["ha_get_core_config"]()
        self.assertEqual(r["external_url"], _URL_TAPADA)
        self.assertEqual(r["internal_url"], "http://usuario:***@192.0.2.10:8123")
        self.assertNotIn("centinela-021", json.dumps(r))

    async def test_vista_previa_tapa_el_antes(self) -> None:
        self.config["external_url"] = _URL_CON_CLAVE
        vista = await self.t["ha_update_core_config"](external_url="")
        cambio = vista["preview"]["changes"]["external_url"]
        self.assertEqual(cambio, {"before": _URL_TAPADA, "after": None})
        self.assertNotIn("centinela-021", json.dumps(vista) + self.ficheros_de_tokens())

    async def test_confirmacion_tapa_lo_releido(self) -> None:
        self.escrituras_esperadas = 1
        vista = await self.t["ha_update_core_config"](external_url=_URL_CON_CLAVE)
        self.assertEqual(vista["preview"]["changes"]["external_url"]["after"], _URL_TAPADA)
        r = await self.t["ha_update_core_config"](
            external_url=_URL_CON_CLAVE, confirmation_token=vista["confirmation_token"])
        # A HA se le manda la de verdad; al cliente vuelve tapada.
        self.assertEqual(self.updates()[0]["external_url"], _URL_CON_CLAVE)
        self.assertEqual(r["config"]["external_url"], _URL_TAPADA)
        self.assertNotIn("centinela-021", json.dumps(r) + self.ficheros_de_tokens())


if __name__ == "__main__":
    unittest.main()
