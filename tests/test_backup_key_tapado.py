"""La clave de los backups de HA no sale en ningún texto (spec 031, T061, FR-011).

La clave solo viaja a HA o al Supervisor dentro de una carga, y lo único que
puede devolverla es la respuesta a esa carga. `backup_key.resultado_redactado` es el
ÚNICO punto que la tapa: envuelve la llamada que la lleva, y la excepción y el
resultado salen ya tapados hacia la respuesta de la tool, el log, el fichero
del token y los ficheros de /data.

Los errores se fabrican con el código REAL de `HAClient`, no a mano:

- HA: un marco `result` con `success: false` y `code: home_assistant_error`
  entra por `_handle_ws_message`, que lo convierte en «HA WS command failed:
  <mensaje>» (así manda HA un `HomeAssistantError`: `async_handle_exception`
  de `websocket_api/connection.py`, 2026.11.1).
- Supervisor: un 400 con el cuerpo de `api_return_error` (`{"result":"error",
  "message":...}`, compacto, como lo escribe orjson en `utils/json.py`,
  2026.11.0) entra por `_parse_sv_response`, que lo cita tal cual: ahí la
  clave va ESCAPADA en JSON si lleva comillas o barras.
- Supervisor con un cuerpo que no es JSON: «Supervisor returned invalid JSON:
  <repr>», con la clave escapada como `repr`.
- Recortada: `humanize_error` de voluptuous (lo usa `api_validate` del
  Supervisor) corta el `repr` del valor a 500 caracteres y pone «...».

El mensaje que cita la clave SIN `password=` delante es el del escenario de la
revisión: «cannot encrypt with key <clave>».

Controles negativos, comprobados:
- `resultado_redactado` devolviendo la excepción original (sin tapar) → caen los seis
  de `TestCadaCaminoConErroresReales` y los de `TestSinSecretos`;
- `ha_create_backup` llamando a `ws_send` sin `resultado_redactado` → cae
  `test_ha_create_backup` (la respuesta y el fichero del token llevan la clave);
- sin las formas escapadas en `_formas` → caen `test_escapada_en_json` y
  `test_escapada_en_repr`; sin `_tapar_cortada` → cae `test_cortada`.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

from structlog.testing import capture_logs

import hermes.tools.backups as backups_mod
from hermes import backup_key as bk
from hermes.ha import HAClient, HAConnectionError
from tests import test_safety_backup_encryption as base_seg

_CLAVE = "centinela-031"
# Con comillas y barra: así la forma escapada (JSON, `repr`) no es la clave tal cual.
_CLAVE_RARA = 'centinela"031\\x'
_MENSAJE = "cannot encrypt with key {}"


async def error_ws_real(mensaje: str, code: str = "home_assistant_error") -> HAConnectionError:
    """El error que `HAClient.ws_send` lanza ante ese marco de HA."""
    cliente = HAClient.__new__(HAClient)
    cliente._pending_ws_responses = {}
    futuro = asyncio.get_running_loop().create_future()
    cliente._pending_ws_responses[7] = futuro
    await cliente._handle_ws_message({
        "id": 7, "type": "result", "success": False,
        "error": {"code": code, "message": mensaje},
    })
    exc = futuro.exception()
    assert isinstance(exc, HAConnectionError)
    return exc


class _Resp:
    def __init__(self, status: int, texto: str, path: str) -> None:
        self.status = status
        self.method = "POST"
        self.url = f"http://supervisor{path}"
        self._texto = texto

    async def text(self) -> str:
        return self._texto


async def error_supervisor_real(mensaje: str, path: str = "/backups/new/full",
                                *, json_valido: bool = True) -> HAConnectionError:
    """El error que `HAClient.sv_request` lanza ante esa respuesta."""
    if json_valido:
        cuerpo = json.dumps({"result": "error", "message": mensaje},
                            ensure_ascii=False, separators=(",", ":"))
        status = 400
    else:
        cuerpo, status = mensaje, 200
    cliente = HAClient.__new__(HAClient)
    try:
        await cliente._parse_sv_response(_Resp(status, cuerpo, path))
    except HAConnectionError as exc:
        return exc
    raise AssertionError("no lanzó")


class TestTaparClave(unittest.IsolatedAsyncioTestCase):
    def test_sin_prefijo_y_con_prefijo(self) -> None:
        for texto in (f"cannot encrypt with key {_CLAVE}", f"bad password={_CLAVE}, retry"):
            with self.subTest(texto=texto):
                tapado = bk.tapar_clave(texto, _CLAVE)
                self.assertNotIn(_CLAVE, tapado)
                self.assertIn("***", tapado)

    async def test_escapada_en_json(self) -> None:
        exc = await error_supervisor_real(_MENSAJE.format(_CLAVE_RARA))
        self.assertNotIn(_CLAVE_RARA, str(exc))  # va escapada en el cuerpo
        self.assertIn(json.dumps(_CLAVE_RARA)[1:-1], str(exc))
        tapado = bk.tapar_clave(str(exc), _CLAVE_RARA)
        self.assertNotIn(json.dumps(_CLAVE_RARA)[1:-1], tapado)
        self.assertNotIn("centinela", tapado)

    async def test_escapada_en_repr(self) -> None:
        exc = await error_supervisor_real(_MENSAJE.format(_CLAVE_RARA), json_valido=False)
        self.assertIn(repr(_CLAVE_RARA)[1:-1], str(exc))
        self.assertNotIn("centinela", bk.tapar_clave(str(exc), _CLAVE_RARA))

    def test_cortada(self) -> None:
        # Al final del texto, y como la recorta `humanize_error` («...»)
        # dentro del cuerpo JSON del Supervisor, con el cierre detrás.
        recortado_voluptuous = f"Got '{_CLAVE[:9]}..."
        for texto in (f"cannot encrypt with key {_CLAVE[:-3]}",
                      json.dumps({"result": "error", "message": recortado_voluptuous})):
            with self.subTest(texto=texto):
                self.assertNotIn(_CLAVE[:6], bk.tapar_clave(texto, _CLAVE))
        # Un final que solo coincide en tres caracteres no se toca.
        self.assertEqual(bk.tapar_clave("abc cen", _CLAVE), "abc cen")

    def test_estructuras_y_sin_secreto(self) -> None:
        valor = {"a": [f"k {_CLAVE}", (1, _CLAVE)], _CLAVE: None}
        self.assertNotIn(_CLAVE, json.dumps(bk.tapar_clave(valor, _CLAVE), default=str))
        self.assertIs(bk.tapar_clave(valor, None), valor)


class TestSinSecretos(unittest.IsolatedAsyncioTestCase):
    async def test_error_real_de_ha_sale_tapado_y_con_sus_datos(self) -> None:
        original = await error_ws_real(_MENSAJE.format(_CLAVE))
        original.sent = True

        async def falla() -> Any:
            raise original

        with self.assertRaises(HAConnectionError) as ctx:
            await bk.resultado_redactado(falla(), _CLAVE)
        exc = ctx.exception
        self.assertNotIn(_CLAVE, str(exc))
        self.assertTrue(str(exc).startswith("HA WS command failed: cannot encrypt"))
        self.assertEqual((exc.code, exc.status, exc.sent),
                         ("home_assistant_error", None, True))
        # Sin la original encadenada: una traza no puede enseñarla.
        self.assertIsNone(exc.__context__)
        self.assertIsNone(exc.__cause__)

    async def test_otro_tipo_de_excepcion(self) -> None:
        async def falla() -> Any:
            raise TimeoutError(f"timeout sending {_CLAVE}")

        with self.assertRaises(TimeoutError) as ctx:
            await bk.resultado_redactado(falla(), _CLAVE)
        self.assertNotIn(_CLAVE, str(ctx.exception))

    async def test_resultado_tapado(self) -> None:
        async def ok() -> Any:
            return {"job_id": "j1", "echo": _CLAVE}

        self.assertEqual(await bk.resultado_redactado(ok(), _CLAVE),
                         {"job_id": "j1", "echo": "***"})


class TestCadaCaminoConErroresReales(base_seg._Base):
    """Cada llamada que lleva la clave, con el error real de HA o del
    Supervisor citándola sin prefijo: ni la respuesta, ni el log, ni el
    fichero del token, ni ningún fichero de /data la llevan."""

    def montar_todo(self, ha: base_seg._HA) -> dict[str, Any]:
        from hermes.tools import ha_backup_actions, ha_backup_restore

        mcp = base_seg._MCP()
        ha_backup_actions.register(mcp, ha)
        ha_backup_restore.register(mcp, ha)
        backups_mod.register(mcp, ha, safety_backup_encryption="auto")
        return mcp.tools

    async def dos_pasos(self, t: dict[str, Any], nombre: str, *pos: Any, **args: Any) -> Any:
        vista = await t[nombre](*pos, **args)
        self.assertIn("confirmation_token", vista, vista)
        return await t[nombre](*pos, **args, confirmation_token=vista["confirmation_token"])

    async def comprobar(self, logs: list[dict[str, Any]], r: Any) -> None:
        self.assertIn("error", json.dumps(r, default=str), r)
        self.sin_centinela(logs, r)

    async def _ws(self, comando: str, nombre: str, **args: Any) -> None:
        from hermes.tools import ha_backups as hb

        respuestas = base_seg.TestCentinelaTransversal._respuestas(self)
        respuestas[comando] = await error_ws_real(_MENSAJE.format(_CLAVE))
        ha = base_seg._HA(ws=respuestas)
        t = self.montar_todo(ha)
        with capture_logs() as logs, \
                patch.object(hb, "ha_at_least", new=AsyncMock(return_value=True)):
            r = await self.dos_pasos(t, nombre, **args)
        self.assertEqual(ha.enviados_ws[-1].get("type"), comando)
        await self.comprobar(logs, r)

    async def test_ha_create_backup(self) -> None:
        await self._ws("backup/generate", "ha_create_backup", agent_ids=["hassio.local"])

    async def test_ha_restore_backup(self) -> None:
        await self._ws("backup/restore", "ha_restore_backup", backup_id="abc123",
                       agent_id="hassio.local")

    async def _sv(self, nombre: str, *pos: Any, **args: Any) -> None:
        ha = base_seg._HA()
        ha.post = await error_supervisor_real(_MENSAJE.format(_CLAVE))
        t = self.montar_todo(ha)
        with capture_logs() as logs:
            r = await self.dos_pasos(t, nombre, *pos, **args)
        self.assertEqual(ha.posts[-1][1]["password"], _CLAVE)
        await self.comprobar(logs, r)

    async def test_sv_restore_backup_full(self) -> None:
        await self._sv("sv_restore_backup_full", "abc123")

    async def test_sv_restore_backup_partial(self) -> None:
        await self._sv("sv_restore_backup_partial", "abc123", addons='["core_mosquitto"]')

    async def test_sv_create_safety_backup(self) -> None:
        ha = base_seg._HA()
        ha.post = await error_supervisor_real(_MENSAJE.format(_CLAVE))
        t = self.montar_todo(ha)
        with capture_logs() as logs:
            r = await t["sv_create_safety_backup"]()
        self.assertEqual(ha.posts[0][1]["password"], _CLAVE)
        await self.comprobar(logs, r)

    async def test_safety_backup_automatico(self) -> None:
        ha = base_seg._HA()
        ha.post = await error_supervisor_real(_MENSAJE.format(_CLAVE))
        with capture_logs() as logs:
            r = await self.automatico(ha, "auto")
        self.assertEqual(ha.posts[0][1]["password"], _CLAVE)
        self.assertTrue(r["error"].startswith("safety_backup_failed"), r)
        await self.comprobar(logs, r)


if __name__ == "__main__":
    unittest.main()
