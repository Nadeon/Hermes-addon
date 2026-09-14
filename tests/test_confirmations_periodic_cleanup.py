"""Los tokens de confirmación caducados también se barren con el add-on en pie.

Cada preview que el usuario no confirma deja un fichero en
`/data/pending_confirmations`. `cleanup_expired_confirmations()` los limpia,
pero solo se llamaba una vez, en el paso 7 del boot. Hermes se instala con
`boot: auto` y no se reinicia por su cuenta: un add-on que lleve meses
levantado acumulaba un fichero por cada preview sin confirmar, sin límite.

La limpieza periódica va en el lifespan, junto a la de OAuth, y con el mismo
periodo (una hora).
"""

from __future__ import annotations

import asyncio
import inspect
import unittest
import unittest.mock as mock

from hermes import __main__ as main_mod
from hermes.__main__ import (
    CONFIRMATIONS_CLEANUP_INTERVAL_SECONDS,
    _periodic_confirmations_cleanup,
)


class TestLimpiezaPeriodicaDeConfirmaciones(unittest.IsolatedAsyncioTestCase):
    async def _correr_un_rato(self, task: asyncio.Task[None], vueltas: int) -> None:
        """Cede el control lo justo para que la task dé `vueltas` iteraciones."""
        for _ in range(vueltas * 4):
            await asyncio.sleep(0)

    async def test_llama_a_la_limpieza_repetidamente(self) -> None:
        limpiar = mock.AsyncMock(return_value=0)
        with mock.patch.object(
            main_mod, "cleanup_expired_confirmations", limpiar
        ):
            task = asyncio.create_task(_periodic_confirmations_cleanup(0))
            await self._correr_un_rato(task, 3)
            task.cancel()
            desenlace = await asyncio.gather(task, return_exceptions=True)
            self.assertIsInstance(desenlace[0], asyncio.CancelledError)

        self.assertGreaterEqual(
            limpiar.await_count, 2, "la limpieza debe repetirse, no correr una vez"
        )

    async def test_espera_antes_de_la_primera_limpieza(self) -> None:
        """El paso 7 del boot ya limpia: la task no debe duplicarlo al arrancar."""
        limpiar = mock.AsyncMock(return_value=0)
        with mock.patch.object(
            main_mod, "cleanup_expired_confirmations", limpiar
        ):
            task = asyncio.create_task(
                _periodic_confirmations_cleanup(3600)
            )
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            en_curso = limpiar.await_count
            task.cancel()
            desenlace = await asyncio.gather(task, return_exceptions=True)
            self.assertIsInstance(desenlace[0], asyncio.CancelledError)

        self.assertEqual(en_curso, 0)

    async def test_un_fallo_no_mata_la_task(self) -> None:
        """Una limpieza que muere en silencio reproduce el bug original."""
        limpiar = mock.AsyncMock(side_effect=[OSError("disco lleno"), 2, 0])
        with mock.patch.object(
            main_mod, "cleanup_expired_confirmations", limpiar
        ):
            task = asyncio.create_task(_periodic_confirmations_cleanup(0))
            await self._correr_un_rato(task, 3)
            sigue_viva = not task.done()
            task.cancel()
            desenlace = await asyncio.gather(task, return_exceptions=True)
            self.assertIsInstance(desenlace[0], asyncio.CancelledError)

        self.assertTrue(sigue_viva)
        self.assertGreaterEqual(limpiar.await_count, 2)

    def test_el_periodo_es_de_una_hora(self) -> None:
        self.assertEqual(CONFIRMATIONS_CLEANUP_INTERVAL_SECONDS, 3600)

    def test_el_lifespan_arranca_y_cancela_la_task(self) -> None:
        """Sin esto la task no existiría en producción aunque funcione aquí.

        El lifespan se define dentro de `_boot` y montarlo entero exigiría
        levantar el servidor MCP; se comprueba sobre el código fuente.
        """
        fuente = inspect.getsource(main_mod._boot)
        self.assertIn("_periodic_confirmations_cleanup()", fuente)
        self.assertIn("confirmations_cleanup.cancel()", fuente)


if __name__ == "__main__":
    unittest.main()
