"""Los errores HTTP del Supervisor llevan el `status` en la excepción.

`_parse_sv_response` y `sv_request_text` construían el `HAConnectionError` solo
con el texto. Quien necesitaba distinguir un 404 —por ejemplo, el sondeo del
safety backup ante un job que el Supervisor ya olvidó— tenía que buscar
« failed 404:» dentro del mensaje. Las peticiones REST al Core ya pasaban
`status=resp.status`; las del Supervisor deben hacer lo mismo.
"""

from __future__ import annotations

import unittest

from hermes.fs_write import _es_404
from hermes.ha import HAClient, HAConnectionError


class _Resp:
    """Lo mínimo de `aiohttp.ClientResponse` que leen los parseadores."""

    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self.method = "GET"
        self.url = "http://supervisor/jobs/abc"
        self._text = text

    async def text(self) -> str:
        return self._text


class TestStatusDelSupervisor(unittest.IsolatedAsyncioTestCase):
    async def test_parse_sv_response_lleva_el_status(self) -> None:
        cliente = HAClient.__new__(HAClient)
        with self.assertRaises(HAConnectionError) as ctx:
            await cliente._parse_sv_response(
                _Resp(404, '{"result": "error", "message": "Job does not exist"}')
            )
        self.assertEqual(ctx.exception.status, 404)

    async def test_error_de_aplicacion_sin_status_http(self) -> None:
        # `result: error` con 200 no es un error HTTP: no se inventa status.
        cliente = HAClient.__new__(HAClient)
        with self.assertRaises(HAConnectionError) as ctx:
            await cliente._parse_sv_response(
                _Resp(200, '{"result": "error", "message": "x"}')
            )
        self.assertIsNone(ctx.exception.status)


class TestEs404(unittest.TestCase):
    def test_decide_por_status(self) -> None:
        self.assertTrue(_es_404(HAConnectionError("lo que sea", status=404)))
        self.assertFalse(_es_404(HAConnectionError("lo que sea", status=500)))

    def test_no_depende_del_texto(self) -> None:
        # Con el status disponible, un mensaje que «parece» un 404 no basta.
        self.assertFalse(_es_404(HAConnectionError("x failed 404: y")))


if __name__ == "__main__":
    unittest.main()
