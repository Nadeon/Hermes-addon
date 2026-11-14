"""Entorno y lector independiente del banco de Core (spec 010, FR-007, FR-008, FR-012).

Sin Docker: el entorno se prueba contra el doble de Core
(`tests/banco/core_doble.py`). `obtener_entorno()` es síncrona y bloquea hasta
que su hilo termina el onboarding; como el doble vive en el bucle del test, se
llama con `asyncio.to_thread` para no bloquear ese bucle.

Control negativo (T013), comprobado en local y restaurado:
  1. ignorando `HERMES_BANCO_OBLIGATORIO` cae `test_obligatorio_sin_url_falla`;
  2. reintentando el onboarding en cada llamada cae
     `test_onboarding_fallido_repite_el_fallo_sin_reintentar`;
  3. con el token en `repr` cae `test_doble_sano_mismo_objeto_y_repr_sin_tokens`.
"""

from __future__ import annotations

import asyncio
import os
import socket
import unittest
from unittest import mock

import aiohttp

from tests.banco import entorno
from tests.banco.core_doble import CoreDoble
from tests.banco.lector import Lector


def _sin_variables() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in (entorno.VAR_URL, entorno.VAR_OBLIGATORIO)}


def _excepcion_de(funcion) -> BaseException | None:
    """Lo que lanza `funcion`, sea lo que sea.

    `assertRaises(AssertionError)` no sirve para «falla, nunca salta»: un
    `SkipTest` se le escaparía y el test saldría saltado en vez de en rojo.
    """
    try:
        funcion()
    except BaseException as exc:  # noqa: BLE001
        return exc
    return None


def _puerto_cerrado() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestSaltoOFallo(unittest.TestCase):
    def setUp(self) -> None:
        entorno._reiniciar()

    def tearDown(self) -> None:
        entorno._reiniciar()

    def test_sin_url_se_salta_con_motivo(self) -> None:
        with mock.patch.dict(os.environ, _sin_variables(), clear=True):
            with self.assertRaises(unittest.SkipTest) as ctx:
                entorno.exigir_banco()
        self.assertIn("HERMES_BANCO_HA_URL", str(ctx.exception))
        self.assertIn("banco-core", str(ctx.exception))

    def test_obligatorio_distinto_de_1_sigue_saltando(self) -> None:
        with mock.patch.dict(os.environ, {**_sin_variables(), entorno.VAR_OBLIGATORIO: "0"}, clear=True):
            with self.assertRaises(unittest.SkipTest):
                entorno.exigir_banco()

    def test_obligatorio_sin_url_falla(self) -> None:
        with mock.patch.dict(os.environ, {**_sin_variables(), entorno.VAR_OBLIGATORIO: "1"}, clear=True):
            lanzada = _excepcion_de(entorno.exigir_banco)
        self.assertIs(type(lanzada), AssertionError)
        self.assertIn("HERMES_BANCO_HA_URL", str(lanzada))
        self.assertIn("banco-core", str(lanzada))

    def test_ha_inalcanzable_falla_nunca_salta(self) -> None:
        url = f"http://127.0.0.1:{_puerto_cerrado()}"
        with mock.patch.dict(os.environ, {**_sin_variables(), entorno.VAR_URL: url}, clear=True), \
                mock.patch.object(entorno, "TIMEOUT_HTTP", 0.3), \
                mock.patch.object(entorno, "INTERVALO", 0.01):
            lanzada = _excepcion_de(entorno.exigir_banco)
        self.assertIs(type(lanzada), AssertionError)
        self.assertIn("espera_http", str(lanzada))


class TestEntornoContraElDoble(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        entorno._reiniciar()

    def tearDown(self) -> None:
        entorno._reiniciar()

    async def test_onboarding_fallido_repite_el_fallo_sin_reintentar(self) -> None:
        async with CoreDoble(fallos={"users": 500}) as core:
            with mock.patch.dict(os.environ, {**_sin_variables(), entorno.VAR_URL: core.url}, clear=True), \
                    mock.patch.object(entorno, "INTERVALO", 0.01):
                primero = await asyncio.to_thread(_excepcion_de, entorno.exigir_banco)
                segundo = await asyncio.to_thread(_excepcion_de, entorno.obtener_entorno)
        self.assertIs(type(primero), AssertionError)
        self.assertIs(type(segundo), AssertionError)
        self.assertIn("users", str(primero))
        self.assertIn("500", str(primero))
        self.assertEqual(str(primero), str(segundo))
        self.assertEqual(core.registro.pasos.count("users"), 1)

    async def test_doble_sano_mismo_objeto_y_repr_sin_tokens(self) -> None:
        async with CoreDoble() as core:
            with mock.patch.dict(os.environ, {**_sin_variables(), entorno.VAR_URL: core.url + "/"}, clear=True), \
                    mock.patch.object(entorno, "INTERVALO", 0.01):
                uno = await asyncio.to_thread(entorno.exigir_banco)
                dos = await asyncio.to_thread(entorno.obtener_entorno)
                self.assertIs(uno, dos)
                self.assertEqual(uno.core_url, core.url)
                self.assertEqual(uno.version_core, "2026.11.1")
                for texto in (repr(uno), str(uno)):
                    self.assertNotIn(uno.token_addon, texto)
                    self.assertNotIn(uno.token_core, texto)
                self.assertNotEqual(uno.token_addon, uno.token_core)
                # El simulado del entorno responde y exige el token de add-on.
                async with aiohttp.ClientSession() as s:
                    async with s.get(f"{uno.supervisor_url}/supervisor/ping") as r:
                        self.assertEqual(r.status, 200)
                    async with s.get(
                        f"{uno.supervisor_url}/core/info",
                        headers={"Authorization": f"Bearer {uno.token_addon}"},
                    ) as r:
                        self.assertEqual((await r.json())["data"]["version"], "2026.11.1")
                    async with s.get(
                        f"{uno.supervisor_url}/core/info",
                        headers={"Authorization": f"Bearer {uno.token_core}"},
                    ) as r:
                        self.assertEqual(r.status, 401)
        self.assertEqual(core.registro.pasos.count("users"), 1)


class TestLector(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.core = CoreDoble(
            token_core="token-lector",
            estados={"input_boolean.banco_x": {"entity_id": "input_boolean.banco_x", "state": "on"}},
        )
        await self.core.__aenter__()

    async def asyncTearDown(self) -> None:
        await self.core.__aexit__(None, None, None)

    async def test_habla_directo_con_core_con_el_token_de_core(self) -> None:
        async with Lector(self.core.url, "token-lector") as lector:
            await lector.listar("input_boolean")
            creado = await lector.crear("counter", {"name": "banco_counter_1"})
        self.assertEqual(self.core.registro.ws_tokens, ["token-lector"])
        tipos = [c["type"] for c in self.core.registro.ws_comandos]
        self.assertEqual(tipos, ["input_boolean/list", "counter/create"])
        self.assertEqual(creado["datos"]["name"], "banco_counter_1")
        self.assertNotIn("token-lector", repr(Lector(self.core.url, "token-lector")))

    async def test_estado_y_404_como_none(self) -> None:
        async with Lector(self.core.url, "token-lector") as lector:
            self.assertEqual((await lector.estado("input_boolean.banco_x"))["state"], "on")
            self.assertIsNone(await lector.estado("input_boolean.no_existe"))

    async def test_esperar_por_sondeo_y_fallo_con_el_ultimo_valor(self) -> None:
        async with Lector(self.core.url, "token-lector") as lector:
            async def cambiar() -> None:
                await asyncio.sleep(0.3)
                self.core.estados["input_boolean.banco_x"]["state"] = "off"

            tarea = asyncio.ensure_future(cambiar())
            valor = await lector.esperar(
                lambda: lector.estado("input_boolean.banco_x"),
                lambda e: e is not None and e["state"] == "off",
                timeout=5,
            )
            await tarea
            self.assertEqual(valor["state"], "off")
            with self.assertRaises(AssertionError) as ctx:
                await lector.esperar(
                    lambda: lector.estado("input_boolean.banco_x"),
                    lambda e: e["state"] == "on",
                    descripcion="volver a on",
                    timeout=0.5,
                )
        self.assertIn("volver a on", str(ctx.exception))
        self.assertIn("'off'", str(ctx.exception))

    async def test_servicios_llamados(self) -> None:
        async with Lector(self.core.url, "token-lector") as lector:
            async with lector.servicios_llamados() as vistos:
                await lector.esperar(lambda: asyncio.sleep(0, vistos), bool, timeout=5)
        self.assertEqual(vistos, [("eco", "prueba")])
        tipos = [c["type"] for c in self.core.registro.ws_comandos]
        self.assertEqual(tipos, ["subscribe_events", "unsubscribe_events"])

    async def test_eventos_de_un_tipo(self) -> None:
        # Tramo B: `ha_finish_timer` se comprueba por el evento `timer.finished`.
        async with Lector(self.core.url, "token-lector") as lector:
            async with lector.eventos("timer.finished") as vistos:
                await lector.esperar(lambda: asyncio.sleep(0, vistos), bool, timeout=5)
        self.assertEqual(vistos, [{"domain": "eco", "service": "prueba"}])
        suscripcion = self.core.registro.ws_comandos[0]
        self.assertEqual(suscripcion["type"], "subscribe_events")
        self.assertEqual(suscripcion["event_type"], "timer.finished")

    async def test_borrar_lo_que_no_existe_no_es_error(self) -> None:
        async with Lector(self.core.url, "token-lector") as lector:
            await lector.borrar("input_boolean", "no_existe_1")
            await lector.borrar("input_boolean", "banco_input_boolean_1")
        self.assertEqual(
            [c.get("input_boolean_id") for c in self.core.registro.ws_comandos],
            ["no_existe_1", "banco_input_boolean_1"],
        )


if __name__ == "__main__":
    unittest.main()
