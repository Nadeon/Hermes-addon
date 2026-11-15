"""`HAClient.rest_get_image` (spec 024, FR-003, T003).

Las instantáneas de cámara (`/api/camera_proxy/…`) y las imágenes de las
entidades `image` (`/api/image_proxy/…`) son binarias y Core no les pone
tope. El método las lee en flujo con un tope fijo de bytes y, si se pasa,
corta la lectura y lanza `ImageTooLargeError` sin devolver nada (research
R-2: sin Pillow, la imagen no se recorta a medias). Se prueba contra un
servidor aiohttp local de los tests, sin red ni HA.

Control negativo (T013 a), comprobado y anotado en el commit del tramo 1:
acumular el cuerpo entero y comprobar el tope solo al final (sin cortar la
lectura) → cae `test_pasado_el_tope_se_corta_la_lectura` (el servidor llega
a enviar los 10 MiB).
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from hermes.ha import HAConnectionError, ImageTooLargeError
from tests._ha_fixture import make_ready_client

_CENTINELA = "centinela-024"
_TROZO = 64 * 1024


class TestRestGetImage(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.cuerpo: bytes = b""
        self.estado = 200
        self.tipo = "image/jpeg"
        self.peticiones: list[tuple[str, dict[str, str]]] = []
        self.enviados = 0
        self.terminado = asyncio.Event()

        async def manejador(request: web.Request) -> web.StreamResponse:
            self.peticiones.append((request.path, dict(request.query)))
            if self.estado != 200:
                return web.Response(
                    status=self.estado,
                    text=f"<html>{_CENTINELA}</html>",
                    content_type="text/html",
                )
            resp = web.StreamResponse()
            resp.headers["Content-Type"] = self.tipo
            await resp.prepare(request)
            try:
                for i in range(0, len(self.cuerpo), _TROZO):
                    await resp.write(self.cuerpo[i:i + _TROZO])
                    self.enviados = i + len(self.cuerpo[i:i + _TROZO])
                    # Cede el turno para que el cliente pueda cortar a tiempo.
                    await asyncio.sleep(0)
                await resp.write_eof()
            except (ConnectionResetError, ConnectionError, asyncio.CancelledError):
                pass
            finally:
                self.terminado.set()
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

    async def _leer(self, path: str = "/camera_proxy/camera.entrada",
                    **kw: Any) -> tuple[str, bytes]:
        kw.setdefault("max_bytes", 1000)
        return await self.client.rest_get_image(path, **kw)

    async def test_devuelve_tipo_sin_parametros_y_bytes(self) -> None:
        self.cuerpo = b"\xff\xd8" + b"x" * 500
        self.tipo = "image/jpeg; charset=binary"
        tipo, datos = await self._leer()
        self.assertEqual(tipo, "image/jpeg")
        self.assertEqual(datos, self.cuerpo)
        self.assertEqual(self.peticiones, [("/core/api/camera_proxy/camera.entrada", {})])

    async def test_pasa_los_params(self) -> None:
        self.cuerpo = b"abc"
        await self._leer(params={"width": "640", "height": "360"})
        self.assertEqual(self.peticiones[0][1], {"width": "640", "height": "360"})

    async def test_exactamente_el_tope_se_devuelve(self) -> None:
        self.cuerpo = b"y" * 1000
        _, datos = await self._leer(max_bytes=1000)
        self.assertEqual(len(datos), 1000)

    async def test_un_byte_mas_que_el_tope_se_rechaza(self) -> None:
        self.cuerpo = b"y" * 1001
        with self.assertRaises(ImageTooLargeError) as ctx:
            await self._leer(max_bytes=1000)
        self.assertEqual(ctx.exception.max_bytes, 1000)
        # Es un fallo de HA para quien solo captura `HAConnectionError`.
        self.assertIsInstance(ctx.exception, HAConnectionError)

    async def test_pasado_el_tope_se_corta_la_lectura(self) -> None:
        # 10 MiB con un tope de 128 KiB: el cliente deja de leer y cierra;
        # el servidor no llega a enviar el cuerpo entero.
        self.cuerpo = b"z" * (10 * 1024 * 1024)
        with self.assertRaises(ImageTooLargeError):
            await self._leer(max_bytes=128 * 1024)
        await asyncio.wait_for(self.terminado.wait(), timeout=10)
        self.assertLess(self.enviados, len(self.cuerpo))

    async def test_errores_http_con_estado_y_sin_cuerpo(self) -> None:
        for estado in (404, 503, 500):
            with self.subTest(estado=estado):
                self.estado = estado
                with self.assertRaises(HAConnectionError) as ctx:
                    await self._leer()
                self.assertEqual(ctx.exception.status, estado)
                self.assertNotIsInstance(ctx.exception, ImageTooLargeError)
                # El cuerpo de un error puede ser HTML con datos de la
                # instalación: no viaja en el mensaje.
                self.assertNotIn(_CENTINELA, str(ctx.exception))

    async def test_ruta_insegura_sin_peticion(self) -> None:
        for ruta in ("/api/../x", "//x", "camera_proxy/x", "/x?token=1", "/x%2e%2e"):
            with self.subTest(ruta=ruta):
                with self.assertRaises(HAConnectionError):
                    await self._leer(ruta)
        self.assertEqual(self.peticiones, [])

    async def test_sesion_no_inicializada(self) -> None:
        self.client._session = None
        with self.assertRaises(HAConnectionError):
            await self._leer()
        self.assertEqual(self.peticiones, [])
