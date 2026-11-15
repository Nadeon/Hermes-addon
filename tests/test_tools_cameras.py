"""Cámaras e imágenes (spec 024, tramo 1; T004 y T005).

`ha_get_camera_snapshot` y `ha_get_image_entity` con `rest_get_image`
simulado: forma de la respuesta (`[dict, Image]`), petición a Core,
validación antes de pedir nada, mapa de errores, dimensiones de cabecera,
privacidad (ningún `access_token` ni URL firmada sale) y log. Datos
ficticios: `camera.entrada`, `image.qr_code`, `light.salon`, un PNG y un
JPEG mínimos generados aquí.

Controles negativos del tramo (T013), vistos en rojo y restaurados:
(b) aceptar cualquier `entity_id` (validación que siempre da `None`) → caen
`TestInstantanea.test_entity_id_invalido_sin_peticion` y
`TestImagen.test_entity_id_invalido_sin_peticion`;
(c) añadir los atributos del estado de la entidad a los metadatos → cae
`TestPrivacidadYLog.test_ningun_token_de_la_entidad_sale`;
(d) registrar la ruta y los parámetros en el evento del log → cae
`TestPrivacidadYLog.test_un_evento_por_llamada_sin_url_ni_bytes`.
"""

from __future__ import annotations

import json
import struct
import unittest
import zlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from mcp.server.mcpserver.utilities.types import Image
from structlog.testing import capture_logs

import hermes.tools.cameras as mod
from hermes.ha import HAConnectionError, ImageTooLargeError

_CENTINELA = "centinela-024"


def _png(ancho: int, alto: int) -> bytes:
    """PNG mínimo válido de `ancho`×`alto` (escala de grises, 8 bits)."""
    def trozo(tipo: bytes, datos: bytes) -> bytes:
        return (struct.pack(">I", len(datos)) + tipo + datos
                + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", ancho, alto, 8, 0, 0, 0, 0)
    filas = b"".join(b"\x00" + b"\x80" * ancho for _ in range(alto))
    return (b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", ihdr)
            + trozo(b"IDAT", zlib.compress(filas)) + trozo(b"IEND", b""))


def _jpeg(ancho: int, alto: int) -> bytes:
    """Cabecera JPEG con APP0 y SOF0: basta para leer las dimensiones."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, alto, ancho, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.ha = MagicMock()
        self.ha.wait_ready = AsyncMock(return_value=True)
        self.ha.rest_get_image = AsyncMock(return_value=("image/jpeg", _jpeg(640, 360)))
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha, response_max_bytes=131_072)

    async def _snap(self, **kw: Any) -> Any:
        kw.setdefault("entity_id", "camera.entrada")
        return await self.mcp.tools["ha_get_camera_snapshot"](**kw)

    async def _img(self, **kw: Any) -> Any:
        kw.setdefault("entity_id", "image.qr_code")
        return await self.mcp.tools["ha_get_image_entity"](**kw)


class TestInstantanea(_Base):
    async def test_respuesta_y_peticion_por_defecto(self) -> None:
        r = await self._snap()
        self.assertIsInstance(r, list)
        self.assertEqual(len(r), 2)
        meta, imagen = r
        self.assertEqual(meta, {
            "entity_id": "camera.entrada", "content_type": "image/jpeg",
            "bytes": len(_jpeg(640, 360)), "width": 640, "height": 360,
            "requested_max_width": 640,
            "scaling": "requested from Home Assistant; it only scales JPEG",
        })
        self.assertIsInstance(imagen, Image)
        contenido = imagen.to_image_content()
        self.assertEqual(contenido.mime_type, "image/jpeg")
        self.ha.rest_get_image.assert_awaited_once_with(
            "/camera_proxy/camera.entrada",
            params={"width": "640", "height": "360"},
            max_bytes=2 * 1024 * 1024,
        )

    async def test_max_width_pide_alto_9_16(self) -> None:
        await self._snap(max_width=320)
        self.assertEqual(self.ha.rest_get_image.await_args.kwargs["params"],
                         {"width": "320", "height": "180"})
        await self._snap(max_width=100)  # 56,25 → 57 (redondeo hacia arriba)
        self.assertEqual(self.ha.rest_get_image.await_args.kwargs["params"],
                         {"width": "100", "height": "57"})

    async def test_entity_id_invalido_sin_peticion(self) -> None:
        for valor in ("light.salon", "camera.", "camera.x/../y", "camera.X", "",
                      "image.qr", None, 3, "camera.a?b=1"):
            with self.subTest(entity_id=valor):
                r = await self._snap(entity_id=valor)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "entity_id"))
        self.ha.rest_get_image.assert_not_awaited()

    async def test_max_width_invalido_sin_peticion(self) -> None:
        for valor in (63, 1921, True, "640", 640.0, None):
            with self.subTest(max_width=valor):
                r = await self._snap(max_width=valor)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "max_width"))
        self.ha.rest_get_image.assert_not_awaited()

    async def test_limites_validos(self) -> None:
        for valor in (64, 1920):
            with self.subTest(max_width=valor):
                self.assertIsInstance(await self._snap(max_width=valor), list)

    async def test_errores_de_core(self) -> None:
        casos = (
            (HAConnectionError("x", status=404), {"error": "not_found", "entity_id": "camera.entrada"}),
            (HAConnectionError("x", status=503), {"error": "camera_unavailable", "entity_id": "camera.entrada"}),
            (HAConnectionError("x", status=500), {"error": "snapshot_failed", "status": 500, "entity_id": "camera.entrada"}),
            (HAConnectionError("caída"), {"error": "ha_unavailable"}),
        )
        for exc, esperado in casos:
            with self.subTest(esperado=esperado["error"]):
                self.ha.rest_get_image.side_effect = exc
                self.assertEqual(await self._snap(), esperado)

    async def test_caida_de_aiohttp(self) -> None:
        import asyncio

        import aiohttp

        for exc in (aiohttp.ClientConnectionError("x"), asyncio.TimeoutError()):
            with self.subTest(exc=type(exc).__name__):
                self.ha.rest_get_image.side_effect = exc
                self.assertEqual(await self._snap(), {"error": "ha_unavailable"})

    async def test_demasiado_grande(self) -> None:
        self.ha.rest_get_image.side_effect = ImageTooLargeError(2 * 1024 * 1024)
        r = await self._snap()
        self.assertIsInstance(r, dict)
        self.assertEqual(r["error"], "image_too_large")
        self.assertEqual(r["max_bytes"], 2097152)

    async def test_tipo_que_no_es_imagen(self) -> None:
        for tipo in ("text/html", "", "application/octet-stream", "image/"):
            with self.subTest(tipo=tipo):
                self.ha.rest_get_image.return_value = (tipo, b"<html>hola</html>")
                r = await self._snap()
                self.assertIsInstance(r, dict)
                self.assertEqual(r["error"], "unsupported_content_type")


class TestImagen(_Base):
    async def test_respuesta_y_peticion_sin_params(self) -> None:
        self.ha.rest_get_image.return_value = ("image/png", _png(3, 2))
        meta, imagen = await self._img()
        self.assertEqual(meta, {
            "entity_id": "image.qr_code", "content_type": "image/png",
            "bytes": len(_png(3, 2)), "width": 3, "height": 2,
            "scaling": "not scaled: Home Assistant serves the original",
        })
        self.assertNotIn("requested_max_width", meta)
        self.assertEqual(imagen.to_image_content().mime_type, "image/png")
        self.ha.rest_get_image.assert_awaited_once_with(
            "/image_proxy/image.qr_code", params=None, max_bytes=2 * 1024 * 1024)

    async def test_entity_id_invalido_sin_peticion(self) -> None:
        for valor in ("camera.entrada", "image.", "image.a/../b", "image.QR", "", None):
            with self.subTest(entity_id=valor):
                r = await self._img(entity_id=valor)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "entity_id"))
        self.ha.rest_get_image.assert_not_awaited()

    async def test_503_es_image_unavailable(self) -> None:
        self.ha.rest_get_image.side_effect = HAConnectionError("x", status=503)
        self.assertEqual((await self._img())["error"], "image_unavailable")

    async def test_demasiado_grande(self) -> None:
        self.ha.rest_get_image.side_effect = ImageTooLargeError(2 * 1024 * 1024)
        self.assertEqual((await self._img())["error"], "image_too_large")


class TestDimensiones(unittest.TestCase):
    def test_png(self) -> None:
        self.assertEqual(mod._dimensiones(_png(17, 5)), (17, 5))

    def test_jpeg(self) -> None:
        self.assertEqual(mod._dimensiones(_jpeg(1280, 720)), (1280, 720))

    def test_basura_y_truncadas(self) -> None:
        for datos in (b"", b"basura", b"\xff\xd8\xff", _png(4, 4)[:18],
                      _jpeg(10, 10)[:10], b"\xff\xd8\x00\x00\x00\x00"):
            with self.subTest(datos=datos[:12]):
                self.assertEqual(mod._dimensiones(datos), (None, None))


class TestBytesBasura(_Base):
    async def test_imagen_ilegible_se_devuelve_igual(self) -> None:
        self.ha.rest_get_image.return_value = ("image/webp", b"RIFF....WEBPVP8 ")
        meta, imagen = await self._snap()
        self.assertEqual((meta["width"], meta["height"]), (None, None))
        self.assertEqual(imagen.to_image_content().mime_type, "image/webp")


class TestPrivacidadYLog(_Base):
    """FR-004: ninguna URL firmada ni token de la entidad sale; el log no
    lleva la URL, los parámetros ni los bytes."""

    def setUp(self) -> None:
        super().setUp()
        # Estado de la entidad como lo tendría la caché de Hermes: con su
        # `access_token` y un `entity_picture` firmado.
        estado = {
            "entity_id": "camera.entrada", "state": "idle",
            "attributes": {
                "access_token": _CENTINELA,
                "entity_picture": f"/api/camera_proxy/camera.entrada?token={_CENTINELA}",
            },
        }
        self.ha.get_state = AsyncMock(return_value=estado)
        self.ha.state_cache = {"camera.entrada": estado}
        self.ha._state_cache = {"camera.entrada": estado}

    def _texto(self, r: Any) -> str:
        bloques = r if isinstance(r, list) else [r]
        return json.dumps([b for b in bloques if isinstance(b, dict)], ensure_ascii=False)

    async def test_ningun_token_de_la_entidad_sale(self) -> None:
        r = await self._snap()
        self.assertNotIn(_CENTINELA, self._texto(r))
        self.assertNotIn("token", self._texto(r))
        for exc in (HAConnectionError("x", status=404),
                    HAConnectionError(f"GET /camera_proxy?token={_CENTINELA}", status=500),
                    HAConnectionError(f"caída {_CENTINELA}")):
            with self.subTest(exc=str(exc.status)):
                self.ha.rest_get_image.side_effect = exc
                self.assertNotIn(_CENTINELA, self._texto(await self._snap()))

    async def test_un_evento_por_llamada_sin_url_ni_bytes(self) -> None:
        with capture_logs() as logs:
            await self._snap(max_width=320)
        eventos = [e for e in logs if e["event"] == "camera_image_read"]
        self.assertEqual(len(eventos), 1)
        e = eventos[0]
        self.assertEqual(
            {k: e[k] for k in ("tool", "entity_id", "bytes", "outcome")},
            {"tool": "ha_get_camera_snapshot", "entity_id": "camera.entrada",
             "bytes": len(_jpeg(640, 360)), "outcome": "ok"})
        texto = repr(logs)
        for prohibido in ("camera_proxy", "320", "180", "width", "\\xff\\xd8"):
            self.assertNotIn(prohibido, texto)

    async def test_rechazo_en_el_log(self) -> None:
        with capture_logs() as logs:
            await self._snap(entity_id="light.salon")
            self.ha.rest_get_image.side_effect = HAConnectionError("x", status=503)
            await self._img()
        resultados = [e["outcome"] for e in logs if e["event"] == "camera_image_read"]
        self.assertEqual(resultados, ["rejected:invalid_argument",
                                      "rejected:image_unavailable"])
