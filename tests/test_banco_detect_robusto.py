"""`comprobar_detect` del banco: acepta lo honesto y nada más (sin HA ni Docker).

`config/core/detect` consulta un servicio externo de geolocalización y el
contenedor del banco no tiene salida a internet. Casi siempre HA responde
enseguida con un objeto vacío, pero falló una vez en el CI por plazo agotado.
`tests/banco/test_banco_configuracion_sistema.py` acepta por eso dos caminos,
la respuesta de HA o un error limpio de Hermes, validados por
`comprobar_detect`. Aquí se comprueba que ese validador:

- acepta las respuestas REALES de Hermes, sacadas por el servidor MCP de
  Hermes (que marca `isError`) con la genérica registrada sobre la tabla real:
  la respuesta de HA, el plazo agotado del `ws_send` de verdad de `HAClient`
  y el fallo con código de HA;
- rechaza una excepción sin tratar dentro de la tool (otra vez por el
  servidor MCP real) y cada resultado que mienta.

Control negativo comprobado al escribirlo: con `comprobar_detect` reducido a
`return "respuesta"` (un validador que lo acepta todo) caen 8: los seis
`test_rechaza_*`, `test_plazo_agotado_real` y `test_fallo_con_codigo_de_ha`;
con la rama del plazo quitada cae solo `test_plazo_agotado_real`.
"""

from __future__ import annotations

import functools
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp import Client

from hermes.ha import HAClient, HAConnectionError
from hermes.mcp_server import build_mcp_server
from hermes.tools import generic_commands
from tests.banco.test_banco_configuracion_sistema import comprobar_detect

pytestmark = pytest.mark.anyio

_DETECT = {"type": "config/core/detect"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Salud:
    def set_ws_connected(self, _v: bool) -> None:
        pass


def _cliente_simulado(**ws_send: Any) -> MagicMock:
    c = MagicMock()
    c.wait_ready = AsyncMock(return_value=True)
    c.ws_send = AsyncMock(**ws_send)
    return c


async def _llamar(ha: Any) -> Any:
    """La llamada MCP real a la genérica, con la tabla de comandos real."""
    servidor = build_mcp_server("prueba")
    generic_commands.register(servidor, ha, response_max_bytes=131_072)
    async with Client(servidor) as cliente:
        return await cliente.call_tool("ha_read_ws_command", _DETECT)


def _falso(texto: str, *, is_error: bool) -> SimpleNamespace:
    return SimpleNamespace(is_error=is_error,
                           content=[SimpleNamespace(type="text", text=texto)])


# ── Lo honesto se acepta ─────────────────────────────────────────────────────

async def test_respuesta_vacia_de_ha() -> None:
    assert comprobar_detect(await _llamar(_cliente_simulado(return_value={}))) == "respuesta"


async def test_respuesta_con_datos_de_ha() -> None:
    datos = {"unit_system": "metric", "latitude": 40.4, "longitude": -3.7,
             "time_zone": "Europe/Madrid", "currency": "EUR", "country": "ES"}
    assert comprobar_detect(await _llamar(_cliente_simulado(return_value=datos))) == "respuesta"


async def test_plazo_agotado_real() -> None:
    """El `ws_send` de verdad de `HAClient`, con un socket que nunca contesta."""
    ha = HAClient(supervisor_base_url="http://supervisor", supervisor_token="t",
                  health_server=_Salud())

    class _WS:
        closed = False

        async def send_json(self, _payload: dict) -> None:
            pass

    ha._ws = _WS()
    ha._connected_event.set()
    # El mismo método con un plazo corto: el mensaje es el de producción.
    ha.ws_send = functools.partial(HAClient.ws_send, ha, timeout_seconds=0.05)
    assert comprobar_detect(await _llamar(ha)) == "plazo"


async def test_fallo_con_codigo_de_ha() -> None:
    # HA convierte un `TimeoutError` del manejador en el código `timeout`.
    exc = HAConnectionError("Timeout", code="timeout")
    assert comprobar_detect(await _llamar(_cliente_simulado(side_effect=exc))) == "fallo_ha"


# ── Lo que no es honesto se rechaza ──────────────────────────────────────────

async def test_rechaza_excepcion_sin_tratar() -> None:
    resultado = await _llamar(_cliente_simulado(side_effect=ValueError("roto")))
    assert resultado.is_error
    with pytest.raises(AssertionError, match="sin tratar"):
        comprobar_detect(resultado)


def test_rechaza_error_escondido_en_una_respuesta() -> None:
    r = {"command": "config/core/detect", "category": "read",
         "result": {"error": "no hay red"}}
    with pytest.raises(AssertionError, match="claves que detect no devuelve"):
        comprobar_detect(_falso(json.dumps(r), is_error=False))


def test_rechaza_error_sin_marcar() -> None:
    r = {"error": "Timeout waiting for HA WS response for command config/core/detect"}
    with pytest.raises(AssertionError, match="forma inesperada"):
        comprobar_detect(_falso(json.dumps(r), is_error=False))


def test_rechaza_plazo_de_otro_comando() -> None:
    r = {"error": "Timeout waiting for HA WS response for command get_config"}
    with pytest.raises(AssertionError, match="ni fallo de HA"):
        comprobar_detect(_falso(json.dumps(r), is_error=True))


def test_rechaza_comando_inexistente() -> None:
    r = {"error": "ha_command_failed", "detail": "Unknown command.",
         "ha_code": "unknown_command"}
    with pytest.raises(AssertionError, match="sí existe"):
        comprobar_detect(_falso(json.dumps(r), is_error=True))


def test_rechaza_otro_comando_en_la_respuesta() -> None:
    r = {"command": "get_config", "category": "read", "result": {}}
    with pytest.raises(AssertionError):
        comprobar_detect(_falso(json.dumps(r), is_error=False))
