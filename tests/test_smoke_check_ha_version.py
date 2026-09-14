"""`smoke_check_ha_core_version`: qué se reintenta y qué aborta el arranque.

El paso 6 del boot pregunta al Supervisor por la versión del core y reintenta
con backoff durante `health_startup_grace_seconds`. El bucle solo reintentaba
errores de transporte (`aiohttp.ClientError`, `asyncio.TimeoutError`), pero un
core a medio arrancar contesta 200 con cosas que no son una versión:

  - `version: "landingpage"` mientras el onboarding no ha terminado →
    `packaging.version.InvalidVersion`.
  - un cuerpo que no es JSON válido → `json.JSONDecodeError`.
  - un cuerpo que no es un objeto → `AttributeError` al hacer `.get`.

Ninguna de las tres se capturaba: se escapaban del bucle, subían hasta `_boot`
y mataban el arranque en el primer intento, aunque el core estuviera listo dos
segundos después. Lo que sí debe seguir abortando de inmediato es una versión
legible por debajo del mínimo: esa no mejora esperando.
"""

from __future__ import annotations

import asyncio
import unittest
import unittest.mock as mock

from aioresponses import aioresponses

from hermes.network import smoke_check_ha_core_version

# Referencia al sleep de verdad: los tests parchean `hermes.network.asyncio.sleep`
# y alguno necesita seguir pudiendo dormir de verdad.
real_sleep = asyncio.sleep

BASE = "http://supervisor"
INFO_URL = f"{BASE}/core/info"


class TestSmokeCheckVersionHA(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # El backoff real (2 s y subiendo) haría estos tests eternos.
        self._sleep = mock.patch(
            "hermes.network.asyncio.sleep", new=mock.AsyncMock(return_value=None)
        )
        self.sleep_mock = self._sleep.start()
        self.addCleanup(self._sleep.stop)

    async def _check(self, grace: int = 30) -> str:
        return await smoke_check_ha_core_version(
            supervisor_base_url=BASE,
            supervisor_token="token",
            min_supported="2024.1.0",
            last_tested="2026.9.0",
            grace_seconds=grace,
        )

    async def test_landingpage_se_reintenta_y_acaba_bien(self) -> None:
        """El core sirve "landingpage" mientras arranca; no es un error fatal."""
        with aioresponses() as m:
            m.get(INFO_URL, status=200, payload={"data": {"version": "landingpage"}})
            m.get(INFO_URL, status=200, payload={"data": {"version": "2026.9.0"}})
            version = await self._check()
        self.assertEqual(version, "2026.9.0")

    async def test_cuerpo_que_no_es_json_se_reintenta(self) -> None:
        with aioresponses() as m:
            m.get(
                INFO_URL,
                status=200,
                body="<html>502 Bad Gateway</html>",
                content_type="application/json",
            )
            m.get(INFO_URL, status=200, payload={"data": {"version": "2026.9.0"}})
            version = await self._check()
        self.assertEqual(version, "2026.9.0")

    async def test_cuerpo_que_no_es_un_objeto_se_reintenta(self) -> None:
        """Una lista o una cadena reventaban con AttributeError en `.get`."""
        with aioresponses() as m:
            m.get(INFO_URL, status=200, payload=["no", "soy", "un", "objeto"])
            m.get(INFO_URL, status=200, payload={"data": {"version": "2026.9.0"}})
            version = await self._check()
        self.assertEqual(version, "2026.9.0")

    async def test_data_que_no_es_un_objeto_se_reintenta(self) -> None:
        with aioresponses() as m:
            m.get(INFO_URL, status=200, payload={"data": "todavía no"})
            m.get(INFO_URL, status=200, payload={"data": {"version": "2026.9.0"}})
            version = await self._check()
        self.assertEqual(version, "2026.9.0")

    async def test_version_ilegible_hasta_el_final_da_runtime_error(self) -> None:
        """Si nunca llega una versión buena, el error es el del deadline.

        Lo importante es CUÁL es el error: `InvalidVersion` (lo que salía antes)
        se escapaba del bucle y mataba el boot sin reintentar nada; ahora el
        único fallo posible es el de agotar el periodo de gracia.
        """
        # Aquí el sleep sí frena un poco, o el bucle daría decenas de miles de
        # vueltas contra el doble HTTP durante el segundo de gracia.
        async def _frenar(*_a: object, **_k: object) -> None:
            await real_sleep(0.05)

        self.sleep_mock.side_effect = _frenar
        with aioresponses() as m:
            m.get(
                INFO_URL,
                status=200,
                payload={"data": {"version": "landingpage"}},
                repeat=True,
            )
            with self.assertRaises(RuntimeError) as ctx:
                await self._check(grace=1)
        mensaje = str(ctx.exception)
        self.assertIn("grace period", mensaje)
        self.assertIn("InvalidVersion", mensaje)

    async def test_version_por_debajo_del_minimo_aborta_de_inmediato(self) -> None:
        """Esta sí es fatal: esperar no va a actualizar Home Assistant."""
        with aioresponses() as m:
            m.get(INFO_URL, status=200, payload={"data": {"version": "2023.1.0"}})
            with self.assertRaises(RuntimeError) as ctx:
                await self._check()
        self.assertIn("minimum supported", str(ctx.exception))
        # Y sin dormir: no se ha reintentado.
        self.sleep_mock.assert_not_awaited()

    async def test_version_correcta_al_primer_intento(self) -> None:
        with aioresponses() as m:
            m.get(INFO_URL, status=200, payload={"version": "2026.9.0"})
            version = await self._check()
        self.assertEqual(version, "2026.9.0")


class TestVersionQueNoEsCadena(unittest.IsolatedAsyncioTestCase):
    """`Version()` solo acepta cadenas: con otra cosa lanza `TypeError`.

    `TypeError` no estaba en el except del bucle de reintentos, así que un
    `/core/info` que devolviera `version: 2026` —perfectamente posible: un JSON
    o un YAML sin comillas lo entrega como entero— mataba el arranque entero en
    el primer intento, con una traza que no señala a nada reconocible.

    Un número es una versión legible en cuanto se convierte; cualquier otro tipo
    se trata como "todavía no hay versión" y se reintenta, igual que el campo
    vacío.
    """

    def setUp(self) -> None:
        self._sleep = mock.patch(
            "hermes.network.asyncio.sleep", new=mock.AsyncMock(return_value=None)
        )
        self.sleep_mock = self._sleep.start()
        self.addCleanup(self._sleep.stop)

    async def _check(self, grace: int = 30) -> str:
        return await smoke_check_ha_core_version(
            supervisor_base_url=BASE,
            supervisor_token="token",
            min_supported="2024.1.0",
            last_tested="2026.9.0",
            grace_seconds=grace,
        )

    async def test_un_entero_se_convierte_en_vez_de_reventar(self) -> None:
        with aioresponses() as m:
            m.get(INFO_URL, status=200, payload={"data": {"version": 2026}})
            version = await self._check()
        self.assertEqual(version, "2026")
        # Y sin reintentar: la versión era buena desde el primer momento.
        self.sleep_mock.assert_not_awaited()

    async def test_un_decimal_tambien_se_convierte(self) -> None:
        with aioresponses() as m:
            m.get(INFO_URL, status=200, payload={"data": {"version": 2026.9}})
            version = await self._check()
        self.assertEqual(version, "2026.9")

    async def test_un_entero_por_debajo_del_minimo_sigue_abortando(self) -> None:
        """Convertir no puede ablandar la comprobación que sí es fatal."""
        with aioresponses() as m:
            m.get(INFO_URL, status=200, payload={"data": {"version": 2023}})
            with self.assertRaises(RuntimeError) as ctx:
                await self._check()
        self.assertIn("minimum supported", str(ctx.exception))

    async def test_un_tipo_que_no_es_version_se_reintenta(self) -> None:
        """Una lista, un objeto o un booleano: el core aún no está listo."""
        for basura in ([2026], {"major": 2026}, True):
            with self.subTest(valor=basura):
                with aioresponses() as m:
                    m.get(INFO_URL, status=200, payload={"data": {"version": basura}})
                    m.get(
                        INFO_URL,
                        status=200,
                        payload={"data": {"version": "2026.9.0"}},
                    )
                    version = await self._check()
                self.assertEqual(version, "2026.9.0")

    async def test_el_error_del_deadline_dice_de_que_tipo_era(self) -> None:
        async def _frenar(*_a: object, **_k: object) -> None:
            await real_sleep(0.05)

        self.sleep_mock.side_effect = _frenar
        with aioresponses() as m:
            m.get(INFO_URL, status=200, payload={"data": {"version": [2026]}}, repeat=True)
            with self.assertRaises(RuntimeError) as ctx:
                await self._check(grace=1)
        self.assertIn("list", str(ctx.exception))



if __name__ == "__main__":
    unittest.main()
