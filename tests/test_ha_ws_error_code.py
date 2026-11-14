"""Regresión FR-030 (D1): los errores WS conservan el `code` de Home Assistant.

Antes, `_handle_ws_message` convertía la respuesta de error en un
`HAConnectionError` que solo llevaba el texto. Quien capturaba el error tenía
que buscar subcadenas («not found», «Unable to find»…) para distinguir un
recurso inexistente de una caída real, y eso se rompe en cuanto HA cambia una
frase. El código (`not_found`, `unknown_command`…) es la parte estable del
protocolo, así que debe llegar intacto en `exc.code`.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from hermes.ha import HAClient, HAConnectionError


def _cliente_con_pendiente() -> tuple[HAClient, asyncio.Future]:
    # Saltamos __init__: solo hace falta el diccionario de respuestas
    # pendientes para que `_handle_ws_message` resuelva el future.
    cliente = HAClient.__new__(HAClient)
    future: asyncio.Future = asyncio.get_running_loop().create_future()
    cliente._pending_ws_responses = {7: future}
    return cliente, future


async def _error_de(mensaje_error: Any) -> HAConnectionError:
    cliente, future = _cliente_con_pendiente()
    await cliente._handle_ws_message({
        "type": "result",
        "id": 7,
        "success": False,
        "error": mensaje_error,
    })
    exc = future.exception()
    assert isinstance(exc, HAConnectionError), exc
    return exc


class TestCodigoDeErrorWS(unittest.IsolatedAsyncioTestCase):
    async def test_conserva_el_codigo_not_found(self) -> None:
        exc = await _error_de({
            "code": "not_found",
            "message": "Unable to find counter_id x",
        })
        self.assertEqual(exc.code, "not_found")
        # El texto no cambia: hay código y logs que todavía lo muestran.
        self.assertEqual(
            str(exc), "HA WS command failed: Unable to find counter_id x"
        )

    async def test_sin_code_queda_en_none(self) -> None:
        exc = await _error_de({"message": "algo falló"})
        self.assertIsNone(exc.code)
        self.assertEqual(str(exc), "HA WS command failed: algo falló")

    async def test_error_no_dict_deja_code_en_none(self) -> None:
        exc = await _error_de("texto suelto")
        self.assertIsNone(exc.code)
        self.assertEqual(str(exc), "HA WS command failed: texto suelto")

    async def test_code_que_no_es_texto_se_descarta(self) -> None:
        # Un código con forma rara no debe colarse como si fuera fiable.
        exc = await _error_de({"code": 404, "message": "x"})
        self.assertIsNone(exc.code)

    def test_constructor_compatible_hacia_atras(self) -> None:
        exc = HAConnectionError("fallo", status=404)
        self.assertEqual(exc.status, 404)
        self.assertIsNone(exc.code)
        self.assertEqual(
            HAConnectionError("fallo", code="not_found").code, "not_found"
        )


if __name__ == "__main__":
    unittest.main()
