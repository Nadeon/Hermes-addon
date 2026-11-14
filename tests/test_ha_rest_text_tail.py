"""`HAClient.rest_get_text_tail` (spec 012, FR-004, T004).

El fichero de log de Core (`GET /api/error_log`) puede ocupar cientos de MB:
el método lo lee en flujo y solo guarda las últimas líneas. Se prueba contra
un servidor aiohttp local de los tests (sin red ni HA), con cuerpos
fabricados aquí.

Control negativo (T018 f), comprobado y anotado en el commit del tramo A:
acumular el cuerpo entero sin `maxlen` (`deque()` sin límite) → caen 3:
`test_ultimas_lineas_de_un_cuerpo_grande`, `test_sin_maxlen_no_se_guarda_todo`
y `test_cuerpo_sin_salto_final`.
"""

from __future__ import annotations

import unittest
from typing import Any

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from hermes.ha import HAConnectionError
from tests._ha_fixture import make_ready_client

_MARCA = " …[line truncated]"


class TestRestGetTextTail(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.cuerpo: bytes = b""
        self.estado = 200
        self.peticiones: list[str] = []

        async def manejador(request: web.Request) -> web.StreamResponse:
            self.peticiones.append(request.path)
            if self.estado != 200:
                return web.Response(status=self.estado, text="cuerpo del error")
            resp = web.StreamResponse()
            await resp.prepare(request)
            # En trozos pequeños, para que las líneas crucen los límites.
            for i in range(0, len(self.cuerpo), 7_001):
                await resp.write(self.cuerpo[i:i + 7_001])
            await resp.write_eof()
            return resp

        app = web.Application()
        app.router.add_get("/core/api/{tail:.*}", manejador)
        self.server = TestServer(app)
        await self.server.start_server()
        self.session = ClientSession()
        self.client = make_ready_client(self.session)
        base = str(self.server.make_url("")).rstrip("/")
        self.client._rest_base_url = f"{base}/core/api"

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await self.server.close()

    async def _leer(self, **kw: Any) -> list[str]:
        kw.setdefault("lines", 100)
        return await self.client.rest_get_text_tail("/error_log", **kw)

    async def test_ultimas_lineas_de_un_cuerpo_grande(self) -> None:
        self.cuerpo = "".join(f"linea {i}\n" for i in range(5000)).encode()
        lineas = await self._leer(lines=100)
        self.assertEqual(lineas, [f"linea {i}" for i in range(4900, 5000)])
        self.assertEqual(self.peticiones, ["/core/api/error_log"])

    async def test_sin_maxlen_no_se_guarda_todo(self) -> None:
        self.cuerpo = "".join(f"l{i}\n" for i in range(3000)).encode()
        self.assertEqual(len(await self._leer(lines=10)), 10)

    async def test_cuerpo_sin_salto_final(self) -> None:
        self.cuerpo = b"uno\ndos\ntres"
        self.assertEqual(await self._leer(lines=2), ["dos", "tres"])

    async def test_finales_de_linea_crlf(self) -> None:
        self.cuerpo = b"uno\r\ndos\r\n"
        self.assertEqual(await self._leer(), ["uno", "dos"])

    async def test_linea_larga_recortada_con_marca(self) -> None:
        larga = b"x" * 10_000
        self.cuerpo = b"antes\n" + larga + b"\ndespues\n"
        lineas = await self._leer(max_line_bytes=4096)
        self.assertEqual(lineas[0], "antes")
        self.assertEqual(lineas[1], "x" * 4096 + _MARCA)
        self.assertEqual(lineas[2], "despues")

    async def test_linea_larga_al_final_sin_salto(self) -> None:
        self.cuerpo = b"a\n" + b"y" * 9000
        lineas = await self._leer(max_line_bytes=100)
        self.assertEqual(lineas, ["a", "y" * 100 + _MARCA])

    async def test_utf8_invalido_no_rompe(self) -> None:
        self.cuerpo = "mañana\n".encode() + b"\xff\xfe roto\n"
        lineas = await self._leer()
        self.assertEqual(lineas[0], "mañana")
        self.assertIn("roto", lineas[1])

    async def test_cuerpo_vacio(self) -> None:
        self.cuerpo = b""
        self.assertEqual(await self._leer(), [])

    async def test_404_con_su_estado(self) -> None:
        self.estado = 404
        with self.assertRaises(HAConnectionError) as ctx:
            await self._leer()
        self.assertEqual(ctx.exception.status, 404)
        # El cuerpo del error no viaja en el mensaje: en esta ruta podría ser
        # el propio log.
        self.assertNotIn("cuerpo del error", str(ctx.exception))

    async def test_500_con_su_estado(self) -> None:
        self.estado = 500
        with self.assertRaises(HAConnectionError) as ctx:
            await self._leer()
        self.assertEqual(ctx.exception.status, 500)

    async def test_ruta_con_traversal_rechazada_sin_peticion(self) -> None:
        with self.assertRaises(HAConnectionError):
            await self.client.rest_get_text_tail("/../error_log", lines=10)
        self.assertEqual(self.peticiones, [])

    async def test_cliente_sin_sesion(self) -> None:
        self.client._session = None
        with self.assertRaises(HAConnectionError):
            await self._leer()
        self.assertEqual(self.peticiones, [])


if __name__ == "__main__":
    unittest.main()
