"""El Supervisor caído en una llamada que lleva la clave de backups
(revisión final 1.2.0, BAJO-1).

`backup_key.resultado_redactado` relanza una copia tapada de la excepción. Con el
Supervisor caído, la de verdad es un `aiohttp.ClientConnectorError`: su
`__str__` lee `_conn_key`, y la copia rehecha con `type(exc)(*args)` (con el
`ConnectionKey` convertido en tupla simple) reventaba con `AttributeError`.
Cada tool acababa en un error falso o en el genérico del SDK.

El error es REAL: una petición de aiohttp a un puerto local cerrado, igual
que la del cliente al Supervisor (`HAClient.sv_request` no lo convierte).

Controles negativos, comprobados revirtiendo el código un momento:
- `backup_key.py` como en 001cc6c (`type(exc)(*args)` y `str(nueva)` fuera
  del `try`) → caen 12 de 13: todas salvo la de `OSError`, con
  «safety_backup_failed: 'tuple' object has no attribute 'ssl'»;
- `_tapar_valor` convirtiendo cualquier tupla en tupla simple → caen 9: las
  de clase y atributos, `sv_create_safety_backup`, las dos de restaurar y
  la de desinstalar (la copia cae a `RuntimeError` y ya no se captura);
- `sv_create_safety_backup` y `sv_restore_backup_*` capturando solo
  `HAConnectionError` → caen esas tres (sale la excepción y no el error).
"""

from __future__ import annotations

import asyncio
import json
import socket
import unittest
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import ClientSession
from multidict import CIMultiDict, CIMultiDictProxy
from structlog.testing import capture_logs
from yarl import URL

import hermes.tools.backups as backups_mod
from hermes import backup_key as bk
from hermes import security
from tests import test_safety_backup_encryption as base_seg
from tests.fixtures.marketplace_escritura import (
    ID_INSTALADO,
    MarketplaceSimulado,
)
from tests._ha_fixture import make_ready_client

_CLAVE = base_seg._CENTINELA


def _error_de_conexion_real() -> aiohttp.ClientConnectorError:
    """El `ClientConnectorError` que da aiohttp contra un puerto cerrado."""

    async def pedir() -> aiohttp.ClientConnectorError:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
        s.close()
        async with ClientSession() as sesion:
            try:
                await sesion.post(f"http://127.0.0.1:{puerto}/backups/new/full",
                                  json={"password": _CLAVE})
            except aiohttp.ClientConnectorError as exc:
                return exc
        raise AssertionError("el puerto cerrado aceptó la conexión")

    return asyncio.run(pedir())


_REAL: list[aiohttp.ClientConnectorError] = []


def setUpModule() -> None:
    # Una sola vez: en Windows rechazar la conexión tarda un par de segundos.
    _REAL.append(_error_de_conexion_real())


def _real() -> aiohttp.ClientConnectorError:
    return _REAL[0]


async def _tapada(exc: BaseException) -> BaseException:
    async def falla() -> Any:
        raise exc

    try:
        await bk.resultado_redactado(falla(), _CLAVE)
    except BaseException as tapada:  # noqa: BLE001
        return tapada
    raise AssertionError("no lanzó")


class TestCopiaTapada(unittest.IsolatedAsyncioTestCase):
    async def test_conserva_la_clase(self) -> None:
        tapada = await _tapada(_real())
        self.assertIs(type(tapada), aiohttp.ClientConnectorError)
        self.assertIsInstance(tapada, aiohttp.ClientError)
        self.assertIsInstance(tapada, OSError)

    async def test_se_puede_pintar_y_dice_lo_mismo(self) -> None:
        tapada = await _tapada(_real())
        self.assertEqual(str(tapada), str(_real()))
        self.assertTrue(str(tapada).startswith("Cannot connect to host 127.0.0.1:"))

    async def test_conserva_sus_atributos(self) -> None:
        original = _real()
        tapada = await _tapada(original)
        self.assertEqual((tapada.host, tapada.port, tapada.ssl),
                         (original.host, original.port, original.ssl))
        self.assertEqual((tapada.errno, tapada.strerror), (original.errno, original.strerror))
        self.assertIs(tapada.os_error, original.os_error)

    async def test_sin_la_original_encadenada(self) -> None:
        tapada = await _tapada(_real())
        self.assertIsNone(tapada.__context__)
        self.assertIsNone(tapada.__cause__)

    async def test_args_conservan_el_connection_key(self) -> None:
        tapada = await _tapada(_real())
        self.assertIs(type(tapada.args[0]), type(_real().args[0]))

    async def test_status_de_client_response_error(self) -> None:
        # Como la arma `ClientResponse.raise_for_status`: con su `RequestInfo`.
        url = URL("http://supervisor/backups/new/full")
        info = aiohttp.RequestInfo(url, "POST", CIMultiDictProxy(CIMultiDict()), url)
        original = aiohttp.ClientResponseError(
            info, (), status=502, message=f"Bad Gateway {_CLAVE}")
        tapada = await _tapada(original)
        self.assertIs(type(tapada), aiohttp.ClientResponseError)
        self.assertEqual(tapada.status, 502)
        self.assertNotIn(_CLAVE, str(tapada))

    async def test_oserror_con_la_clave_en_strerror(self) -> None:
        tapada = await _tapada(ConnectionRefusedError(111, f"refused {_CLAVE}"))
        self.assertIs(type(tapada), ConnectionRefusedError)
        self.assertEqual(tapada.errno, 111)
        self.assertNotIn(_CLAVE, str(tapada))
        self.assertNotIn(_CLAVE, repr(tapada.args))

    async def test_tupla_con_nombre_tapada(self) -> None:
        k = _real().args[0]._replace(host=f"h-{_CLAVE}")
        tapado = bk.tapar_clave(k, _CLAVE)
        self.assertIs(type(tapado), type(k))
        self.assertNotIn(_CLAVE, tapado.host)


class TestCadaToolConElSupervisorCaido(base_seg._Base):
    def montar(self, ha: base_seg._HA) -> dict[str, Any]:
        mcp = base_seg._MCP()
        backups_mod.register(mcp, ha, safety_backup_encryption="auto")
        return mcp.tools

    async def test_safety_backup_automatico(self) -> None:
        ha = base_seg._HA(post=_real())
        with capture_logs() as logs:
            r = await self.automatico(ha, "auto")
        self.assertEqual(ha.posts[0][1]["password"], _CLAVE)
        self.assertEqual(r["error"], f"safety_backup_failed: {_real()}")
        self.sin_centinela(logs, r)

    async def test_sv_create_safety_backup(self) -> None:
        ha = base_seg._HA(post=_real())
        with capture_logs() as logs:
            r = await self.montar(ha)["sv_create_safety_backup"]()
        self.assertEqual(ha.posts[0][1]["password"], _CLAVE)
        self.assertEqual(r, {"error": str(_real())})
        self.sin_centinela(logs, r)

    async def _restaurar(self, nombre: str, **args: Any) -> None:
        ha = base_seg._HA(post=_real())
        t = self.montar(ha)
        vista = await t[nombre]("abc123", **args)
        token = vista["confirmation_token"]
        with capture_logs() as logs:
            r = await t[nombre]("abc123", **args, confirmation_token=token)
        self.assertEqual(ha.posts[-1][1]["password"], _CLAVE)
        self.assertEqual(r["error"], str(_real()))
        # El token queda cerrado como fallido, no en `executing` hasta caducar.
        estado = json.loads((Path(security.CONFIRMATIONS_DIR) / f"{token}.json")
                            .read_text("utf-8"))
        self.assertEqual(estado["state"], "failed")
        self.sin_centinela(logs, r)

    async def test_sv_restore_backup_full(self) -> None:
        await self._restaurar("sv_restore_backup_full")

    async def test_sv_restore_backup_partial(self) -> None:
        await self._restaurar("sv_restore_backup_partial", addons='["core_mosquitto"]')


class _Caido:
    """`sv_request` del Supervisor caído: lanza el error real de aiohttp."""

    def __init__(self) -> None:
        self.llamadas: list[dict[str, Any]] = []

    async def __call__(self, method: str, sv_path: str,
                       json_body: dict[str, Any] | None = None,
                       params: dict[str, str] | None = None,
                       timeout_seconds: float = 60.0) -> Any:
        self.llamadas.append({"method": method, "path": sv_path, "json_body": json_body})
        raise _real()


class TestDesinstalarConElSupervisorCaido(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.client = make_ready_client(self.session, {})
        self.ha = MarketplaceSimulado()
        self.sv = _Caido()

        async def ws(payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
            if payload["type"] == "backup/config/info":
                return base_seg._config_info()
            return await self.ha(payload, timeout_seconds)

        self.client.ws_send = ws  # type: ignore[method-assign]
        self.client.sv_request = self.sv  # type: ignore[method-assign]

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_desinstalar_responde_backup_failed(self) -> None:
        from hermes.tools import marketplace_manage as mm

        mcp = base_seg._MCP()
        mm.register(mcp, self.client, safety_backup_encryption="auto")
        t = mcp.tools["ha_marketplace_uninstall"]
        vista = await t(repository_id=ID_INSTALADO)
        token = vista["confirmation_token"]
        r = await t(repository_id=ID_INSTALADO, confirmation_token=token)
        self.assertEqual(self.sv.llamadas[0]["json_body"]["password"], _CLAVE)
        self.assertEqual(r["error"], "backup_failed")
        self.assertIs(r["sent_to_home_assistant"], False)
        self.assertIn("Cannot connect to host", r["detail"])
        self.assertEqual(self.ha.escrituras(), [])
        # El token no se queda bloqueado en `executing`.
        estado = json.loads((Path(security.CONFIRMATIONS_DIR) / f"{token}.json")
                            .read_text("utf-8"))
        self.assertEqual(estado["state"], "failed")
        self.assertNotIn(_CLAVE, json.dumps(r) + json.dumps(estado))


if __name__ == "__main__":
    unittest.main()
