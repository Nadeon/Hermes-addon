"""Tools de diagnóstico de integraciones (spec 012, tramo B; T022).

`ha_list_diagnostics_handlers`, `ha_get_config_entry_diagnostics` y
`ha_get_device_diagnostics` con Home Assistant simulado (`AsyncMock` de
`ws_send` y `_request_json`). Datos ficticios: `<entry_id>` como `entrada1`,
el dominio `mqtt`, el centinela `centinela-012` y un JWT de prueba.

Controles negativos (T033 b, c y d), comprobados y con recuentos en el
commit: descargar sin comprobar el handler → caen
`test_sin_handler_de_entrada_no_descarga` y
`test_sin_handler_de_dispositivo_no_descarga`; devolver el diagnóstico sin
mirar el tope → cae `test_demasiado_grande`; quitar `redact_structure` → caen
`test_centinelas_tapados` y `test_centinela_tapado`; tomar la dueña de `config_entries[0]` → cae
`test_duena_por_config_entry_id`.
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from structlog.testing import capture_logs

import hermes.tools.integration_diagnostics as mod
from hermes.ha import HAConnectionError

_CENTINELA = "centinela-012"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJjZW50aW5lbGEifQ.c2lnbmF0dXJhLWZpY3RpY2lh"


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _diagnostico(data: Any = None) -> dict[str, Any]:
    """Respuesta de la descarga con la forma de Core 2026.11.1."""
    return {
        "home_assistant": {"version": "2026.11.1"},
        "custom_components": {},
        "integration_manifest": {"domain": "mqtt"},
        "setup_times": {},
        "data": data if data is not None else {"config": {"broker": "192.0.2.10"},
                                               "subscriptions": [1, 2]},
        "issues": [],
    }


class _Base(unittest.IsolatedAsyncioTestCase):
    max_bytes = 131_072

    async def asyncSetUp(self) -> None:
        self.enviados: list[dict[str, Any]] = []
        self.entradas = {"entrada1": {"entry_id": "entrada1", "domain": "mqtt",
                                      "title": "Broker"},
                         "entrada2": {"entry_id": "entrada2", "domain": "otro",
                                      "title": "Otro"}}
        self.handlers = {"mqtt": {"config_entry": True, "device": True},
                         "demo": {"config_entry": True, "device": False}}
        self.dispositivos: list[dict[str, Any]] = [
            {"id": "disp1", "config_entry_id": "entrada1",
             "config_entries": ["entrada2", "entrada1"]},
            {"id": "huerfano", "config_entry_id": None, "config_entries": []},
        ]
        self.descarga: Any = _diagnostico()
        self.fallos: dict[str, HAConnectionError] = {}
        self.ha = MagicMock()
        self.ha.wait_ready = AsyncMock(return_value=True)
        self.ha.ws_send = AsyncMock(side_effect=self._ws_send)
        self.ha._request_json = AsyncMock(side_effect=self._rest)
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha, response_max_bytes=self.max_bytes)
        self.t = self.mcp.tools

    async def _ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.enviados.append(payload)
        tipo = payload["type"]
        if tipo in self.fallos:
            raise self.fallos[tipo]
        if tipo == "diagnostics/list":
            return [{"domain": d, "handlers": h} for d, h in self.handlers.items()]
        if tipo == "diagnostics/get":
            h = self.handlers.get(payload["domain"])
            if h is None:
                raise HAConnectionError("Domain not supported", code="not_found")
            return {"domain": payload["domain"], "handlers": h}
        if tipo == "config_entries/get_single":
            e = self.entradas.get(payload["entry_id"])
            if e is None:
                raise HAConnectionError("Config entry not found", code="not_found")
            return {"config_entry": e}
        if tipo == "config/device_registry/list":
            return self.dispositivos
        raise AssertionError(f"comando inesperado: {payload}")

    async def _rest(self, method: str, path: str, *a: Any, **k: Any) -> Any:
        if isinstance(self.descarga, Exception):
            raise self.descarga
        return self.descarga

    def tipos(self) -> list[str]:
        return [p["type"] for p in self.enviados]


class TestListHandlers(_Base):
    async def test_sin_dominio(self) -> None:
        r = await self.t["ha_list_diagnostics_handlers"]()
        self.assertEqual(self.tipos(), ["diagnostics/list"])
        self.assertEqual(r["count"], 2)
        self.assertEqual(r["items"], [
            {"domain": "demo", "config_entry": True, "device": False},
            {"domain": "mqtt", "config_entry": True, "device": True},
        ])

    async def test_con_dominio(self) -> None:
        r = await self.t["ha_list_diagnostics_handlers"](domain="mqtt")
        self.assertEqual(self.enviados, [{"type": "diagnostics/get", "domain": "mqtt"}])
        self.assertEqual(r["items"], [{"domain": "mqtt", "config_entry": True, "device": True}])

    async def test_dominio_sin_plataforma(self) -> None:
        r = await self.t["ha_list_diagnostics_handlers"](domain="sin_diag")
        self.assertEqual((r["error"], r["domain"]), ("diagnostics_not_supported", "sin_diag"))

    async def test_unknown_command(self) -> None:
        self.fallos["diagnostics/list"] = HAConnectionError("Unknown command.",
                                                            code="unknown_command")
        r = await self.t["ha_list_diagnostics_handlers"]()
        self.assertEqual((r["error"], r["ha_code"]), ("diagnostics_unavailable", "unknown_command"))

    async def test_dominio_con_forma_invalida(self) -> None:
        r = await self.t["ha_list_diagnostics_handlers"](domain="Mqtt X")
        self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()


class TestConfigEntryDiagnostics(_Base):
    async def test_entrada_inexistente(self) -> None:
        r = await self.t["ha_get_config_entry_diagnostics"](entry_id="nada")
        self.assertEqual((r["error"], r["entry_id"]), ("not_found", "nada"))
        self.ha._request_json.assert_not_awaited()

    async def test_sin_handler_de_entrada_no_descarga(self) -> None:
        self.handlers["mqtt"] = {"config_entry": False, "device": True}
        r = await self.t["ha_get_config_entry_diagnostics"](entry_id="entrada1")
        self.assertEqual((r["error"], r["domain"], r["kind"]),
                         ("diagnostics_not_supported", "mqtt", "config_entry"))
        self.ha._request_json.assert_not_awaited()

    async def test_dominio_sin_plataforma_no_descarga(self) -> None:
        r = await self.t["ha_get_config_entry_diagnostics"](entry_id="entrada2")
        self.assertEqual((r["error"], r["domain"]), ("diagnostics_not_supported", "otro"))
        self.ha._request_json.assert_not_awaited()

    async def test_camino_feliz(self) -> None:
        r = await self.t["ha_get_config_entry_diagnostics"](entry_id="entrada1")
        self.ha._request_json.assert_awaited_once_with(
            "GET", "/diagnostics/config_entry/entrada1")
        self.assertEqual((r["entry_id"], r["domain"]), ("entrada1", "mqtt"))
        self.assertEqual(r["data"], {"config": {"broker": "192.0.2.10"},
                                     "subscriptions": [1, 2]})
        self.assertEqual(r["issues"], [])
        self.assertNotIn("system_info", r)
        self.assertNotIn("home_assistant", r)
        self.assertNotIn("device_id", r)
        self.assertEqual(r["keys_returned"], ["config", "subscriptions"])
        self.assertEqual(r["redacted_by"], ["home_assistant", "hermes"])

    async def test_con_system_info(self) -> None:
        r = await self.t["ha_get_config_entry_diagnostics"](
            entry_id="entrada1", include_system_info=True)
        self.assertEqual(sorted(r["system_info"]), ["custom_components", "home_assistant",
                                                    "integration_manifest", "setup_times"])

    async def test_keys_validas(self) -> None:
        r = await self.t["ha_get_config_entry_diagnostics"](
            entry_id="entrada1", keys=["subscriptions"])
        self.assertEqual(r["data"], {"subscriptions": [1, 2]})
        self.assertEqual(r["keys_returned"], ["subscriptions"])

    async def test_key_inexistente(self) -> None:
        r = await self.t["ha_get_config_entry_diagnostics"](entry_id="entrada1", keys=["nope"])
        self.assertEqual(r["error"], "invalid_argument")
        self.assertEqual(r["available_keys"], ["config", "subscriptions"])

    async def test_keys_con_forma_invalida(self) -> None:
        for keys in ([], "config", [1]):
            with self.subTest(keys=keys):
                r = await self.t["ha_get_config_entry_diagnostics"](entry_id="entrada1",
                                                                    keys=keys)
                self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()

    async def test_demasiado_grande(self) -> None:
        self.descarga = _diagnostico({"grande": "x" * 200_000, "chica": {"a": 1}})
        r = await self.t["ha_get_config_entry_diagnostics"](entry_id="entrada1")
        self.assertEqual(r["error"], "response_too_large")
        self.assertEqual(r["max_bytes"], self.max_bytes)
        tamanos = {d["key"]: d["bytes"] for d in r["data_keys"]}
        self.assertGreater(tamanos["grande"], 200_000)
        self.assertLess(tamanos["chica"], 100)
        self.assertIn("keys=", r["hint"])
        self.assertLess(len(json.dumps(r)), self.max_bytes)
        # Con `keys` sí cabe.
        r = await self.t["ha_get_config_entry_diagnostics"](entry_id="entrada1",
                                                            keys=["chica"])
        self.assertEqual(r["data"], {"chica": {"a": 1}})

    async def test_centinelas_tapados(self) -> None:
        self.descarga = _diagnostico({"config": {"token": _CENTINELA,
                                                 "nota": f"cabecera {_JWT}"}})
        self.descarga["issues"] = [{"issue_id": "x",
                                    "translation_placeholders": {"url": f"x {_JWT}"},
                                    "detalle": f"password={_CENTINELA}"}]
        with capture_logs() as logs:
            r = await self.t["ha_get_config_entry_diagnostics"](entry_id="entrada1")
        texto = json.dumps(r)
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn(_JWT, texto)
        self.assertEqual(r["data"]["config"]["token"], "***REDACTED***")
        self.assertNotIn(_CENTINELA, str(logs))
        self.assertNotIn("192.0.2", str(logs))

    async def test_entry_id_con_ruta(self) -> None:
        for entry_id in ("a/b", "..", "a b", ""):
            with self.subTest(entry_id=entry_id):
                r = await self.t["ha_get_config_entry_diagnostics"](entry_id=entry_id)
                self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()

    async def test_error_de_descarga_redactado(self) -> None:
        self.descarga = HAConnectionError(f"failed 500: token: {_CENTINELA}", status=500)
        r = await self.t["ha_get_config_entry_diagnostics"](entry_id="entrada1")
        self.assertIn("error", r)
        self.assertNotIn(_CENTINELA, str(r))

    async def test_el_log_no_lleva_datos(self) -> None:
        with capture_logs() as logs:
            await self.t["ha_get_config_entry_diagnostics"](entry_id="entrada1")
        self.assertEqual([e["event"] for e in logs], ["ha_get_config_entry_diagnostics_ok"])
        self.assertNotIn("broker", str(logs))


class TestDeviceDiagnostics(_Base):
    async def test_duena_por_config_entry_id(self) -> None:
        r = await self.t["ha_get_device_diagnostics"](device_id="disp1")
        self.ha._request_json.assert_awaited_once_with(
            "GET", "/diagnostics/config_entry/entrada1/device/disp1")
        self.assertEqual((r["entry_id"], r["domain"], r["device_id"]),
                         ("entrada1", "mqtt", "disp1"))
        self.assertIn({"type": "config_entries/get_single", "entry_id": "entrada1"},
                      self.enviados)

    async def test_dispositivo_inexistente(self) -> None:
        r = await self.t["ha_get_device_diagnostics"](device_id="nada")
        self.assertEqual((r["error"], r["device_id"]), ("not_found", "nada"))
        self.ha._request_json.assert_not_awaited()

    async def test_sin_config_entry_id(self) -> None:
        r = await self.t["ha_get_device_diagnostics"](device_id="huerfano")
        self.assertEqual(r["error"], "diagnostics_not_supported")
        self.assertIn("config_entry_id", r["reason"])
        self.ha._request_json.assert_not_awaited()

    async def test_sin_handler_de_dispositivo_no_descarga(self) -> None:
        self.handlers["mqtt"] = {"config_entry": True, "device": False}
        r = await self.t["ha_get_device_diagnostics"](device_id="disp1")
        self.assertEqual((r["error"], r["kind"]), ("diagnostics_not_supported", "device"))
        self.ha._request_json.assert_not_awaited()

    async def test_device_id_con_ruta(self) -> None:
        r = await self.t["ha_get_device_diagnostics"](device_id="../x")
        self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()

    async def test_centinela_tapado(self) -> None:
        self.descarga = _diagnostico({"nodo": {"network_key": _CENTINELA}})
        r = await self.t["ha_get_device_diagnostics"](device_id="disp1")
        self.assertNotIn(_CENTINELA, json.dumps(r))


if __name__ == "__main__":
    unittest.main()
