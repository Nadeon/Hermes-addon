"""Detección del socket Unix y de la API `/v2` del Supervisor (spec 027, FR-011).

Se prepara sin activar nada: el Supervisor 2026.11.0 no inyecta
`SUPERVISOR_SOCKET` en las apps (`supervisor/docker/app.py`; solo Core lo
recibe en `docker/homeassistant.py`) y la `/v2` es una opción de desarrollo
que se monta aparte de la V1 (`supervisor/api/__init__.py`, `load()`). Las
formas de `GET /supervisor/info` salen de `supervisor/api/supervisor.py`,
`_info_data()` (`feature_flags`, objeto con cada opción y su valor).

Controles negativos comprobados:
- Un fallo de lectura tratado como `api_v2_enabled: False` → en rojo los dos
  casos de excepción de `test_fallos_dan_null_y_no_lanzan` y
  `test_respuesta_lenta`.
- Sin el `asyncio.wait_for` → `test_respuesta_lenta` en rojo (se queda
  esperando hasta el tope del test).
"""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from structlog.testing import capture_logs

import hermes.supervisor_platform as plataforma
from hermes.ha import HAClient, HAConnectionError
from hermes.supervisor_platform import (
    api_v2_activada,
    comprobar_plataforma,
    socket_ofrecido,
)

_CENTINELA = "/run/centinela-027.sock"


def _info(v2: bool | None) -> dict:
    """Respuesta de `/supervisor/info` con las opciones de 2026.11.0."""
    flags = {"app_drop_net_raw": False, "app_reduced_capabilities": False,
             "supervisor_websocket_v2_api": False}
    if v2 is not None:
        flags["supervisor_v2_api"] = v2
    return {"version": "2026.11.0", "channel": "stable", "feature_flags": flags}


def _cliente(respuesta=None, error: BaseException | None = None) -> MagicMock:
    cliente = MagicMock()
    if error is not None:
        cliente.sv_request = AsyncMock(side_effect=error)
    else:
        cliente.sv_request = AsyncMock(return_value=respuesta)
    return cliente


class TestSocketOfrecido(unittest.TestCase):

    def test_variantes(self) -> None:
        for entorno, esperado in (
            ({}, False),
            ({"SUPERVISOR_SOCKET": ""}, False),
            ({"SUPERVISOR_SOCKET": "   "}, False),
            ({"SUPERVISOR_SOCKET": "/run/supervisor/api/supervisor.sock"}, True),
        ):
            with self.subTest(entorno=entorno):
                self.assertIs(socket_ofrecido(entorno), esperado)


class TestApiV2Activada(unittest.TestCase):

    def test_variantes(self) -> None:
        for info, esperado in (
            ({"feature_flags": {"supervisor_v2_api": True}}, True),
            ({"feature_flags": {"supervisor_v2_api": False}}, False),
            ({"feature_flags": {"supervisor_v2_api": "true"}}, False),
            ({"feature_flags": {}}, False),
            ({"version": "2025.1.0"}, False),
            ({"feature_flags": ["supervisor_v2_api"]}, None),
            ("texto", None),
            (None, None),
            ([], None),
        ):
            with self.subTest(info=info):
                self.assertIs(api_v2_activada(info), esperado)


class TestComprobarPlataforma(unittest.IsolatedAsyncioTestCase):

    async def _comprobar(self, cliente, entorno=None):
        with capture_logs() as logs:
            evento = await comprobar_plataforma(cliente, entorno or {})
        return evento, logs

    async def test_cuatro_combinaciones(self) -> None:
        for socket in (False, True):
            for v2 in (False, True):
                with self.subTest(socket=socket, v2=v2):
                    cliente = _cliente(_info(v2))
                    entorno = {"SUPERVISOR_SOCKET": _CENTINELA} if socket else {}
                    evento, logs = await self._comprobar(cliente, entorno)
                    self.assertEqual(evento, {"transport": "tcp",
                                              "unix_socket_offered": socket,
                                              "api_v2_enabled": v2})
                    nombres = [l["event"] for l in logs]
                    self.assertEqual(nombres.count("supervisor_platform"), 1)
                    plat = next(l for l in logs if l["event"] == "supervisor_platform")
                    self.assertEqual(plat["log_level"], "info")
                    self.assertEqual(
                        "supervisor_unix_socket_offered" in nombres, socket)
                    self.assertEqual("supervisor_api_v2_enabled" in nombres, v2)
                    for aviso in logs:
                        if aviso["event"] in ("supervisor_unix_socket_offered",
                                              "supervisor_api_v2_enabled"):
                            self.assertEqual(aviso["log_level"], "warning")
                    socket_aviso = [l for l in logs
                                    if l["event"] == "supervisor_unix_socket_offered"]
                    if socket_aviso:
                        self.assertIn("TCP", socket_aviso[0]["message"])
                    v2_aviso = [l for l in logs if l["event"] == "supervisor_api_v2_enabled"]
                    if v2_aviso:
                        self.assertIn("V1", v2_aviso[0]["message"])
                    self.assertNotIn("supervisor_platform_check_failed", nombres)
                    # Una sola lectura, de la V1; nunca una ruta de la `/v2`.
                    cliente.sv_request.assert_awaited_once()
                    args = cliente.sv_request.await_args.args
                    self.assertEqual(args, ("GET", "/supervisor/info"))
                    self.assertFalse(args[1].startswith("/v2"))
                    # La ruta del socket no sale en el log.
                    self.assertNotIn("centinela-027", json.dumps(logs, default=str))

    async def test_fallos_dan_null_y_no_lanzan(self) -> None:
        for nombre, cliente, motivo in (
            ("ha", _cliente(error=HAConnectionError(
                "GET http://supervisor/supervisor/info failed: token=centinela-027",
                status=500)), "error"),
            ("cualquiera", _cliente(error=RuntimeError("centinela-027")), "error"),
            ("no_objeto", _cliente(["no", "es", "objeto"]), "unexpected_response"),
            ("flags_raras", _cliente({"feature_flags": "raro"}), "unexpected_response"),
        ):
            with self.subTest(caso=nombre):
                evento, logs = await self._comprobar(cliente)
                self.assertIsNone(evento["api_v2_enabled"])
                fallo = [l for l in logs if l["event"] == "supervisor_platform_check_failed"]
                self.assertEqual(len(fallo), 1)
                self.assertEqual(fallo[0]["reason"], motivo)
                self.assertEqual(fallo[0]["log_level"], "debug")
                self.assertNotIn("centinela-027", json.dumps(logs, default=str))
                self.assertNotIn("supervisor_api_v2_enabled", [l["event"] for l in logs])

    async def test_respuesta_lenta(self) -> None:
        async def lenta(*_a, **_k):
            await asyncio.sleep(5)
            return _info(True)

        cliente = MagicMock()
        cliente.sv_request = lenta
        with patch.object(plataforma, "TIMEOUT_S", 0.05):
            evento, logs = await asyncio.wait_for(self._comprobar(cliente), timeout=2)
        self.assertIsNone(evento["api_v2_enabled"])
        fallo = [l for l in logs if l["event"] == "supervisor_platform_check_failed"]
        self.assertEqual(fallo[0]["reason"], "timeout")

    async def test_la_cancelacion_se_propaga(self) -> None:
        with self.assertRaises(asyncio.CancelledError):
            await comprobar_plataforma(_cliente(error=asyncio.CancelledError()), {})

    async def test_la_url_base_del_cliente_no_cambia(self) -> None:
        cliente = HAClient(supervisor_base_url="http://supervisor",
                           supervisor_token="token-de-prueba",
                           health_server=MagicMock())
        antes = (cliente._supervisor_base_url, cliente._rest_base_url, cliente._ws_url)
        with patch.object(cliente, "sv_request", AsyncMock(return_value=_info(True))):
            await comprobar_plataforma(cliente, {"SUPERVISOR_SOCKET": _CENTINELA})
        self.assertEqual(
            (cliente._supervisor_base_url, cliente._rest_base_url, cliente._ws_url), antes)


if __name__ == "__main__":
    unittest.main()
