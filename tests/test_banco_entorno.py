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
import json
import logging
import os
import socket
import unittest
from typing import Any
from unittest import mock

import aiohttp
import structlog

from tests.banco import entorno, onboarding
from tests.banco.core_doble import CoreDoble
from tests.banco.lector import ErrorCore, Lector


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


class _Corte(BaseException):
    """Como la excepción de pytest-timeout: no es `Exception`."""


class TestCorteDelTopePorTest(unittest.TestCase):
    """T041: el tope por test de pytest corta la espera del onboarding con una
    excepción que no es `Exception`. El fallo tiene que quedar anotado, para
    que el test siguiente no repita el onboarding (403 «already done»).

    Control negativo (T041), comprobado en local y restaurado: sin la rama
    `except BaseException` de `obtener_entorno`, la segunda llamada vuelve a
    crear el entorno y cae `test_el_fallo_queda_anotado_sin_reintentar`.
    """

    def setUp(self) -> None:
        entorno._reiniciar()

    def tearDown(self) -> None:
        entorno._reiniciar()

    def test_el_fallo_queda_anotado_sin_reintentar(self) -> None:
        intentos: list[str] = []

        async def crear(core_url: str, secretos: list[str]) -> entorno.EntornoBanco:
            intentos.append(core_url)
            raise _Corte()

        url = f"http://127.0.0.1:{_puerto_cerrado()}"
        with mock.patch.dict(os.environ, {**_sin_variables(), entorno.VAR_URL: url}, clear=True), \
                mock.patch.object(entorno, "_crear", crear):
            primero = _excepcion_de(entorno.exigir_banco)
            segundo = _excepcion_de(entorno.obtener_entorno)
        # El corte sigue su camino (pytest lo informa como su timeout)...
        self.assertIs(type(primero), _Corte)
        # ...y el siguiente test ve la causa, sin un segundo onboarding.
        self.assertIs(type(segundo), AssertionError)
        self.assertIn("_Corte", str(segundo))
        self.assertIn("tope por test", str(segundo))
        self.assertEqual(len(intentos), 1)


class TestRegistroDelArranque(unittest.IsolatedAsyncioTestCase):
    """T042 (FR-012): el log de la creación del entorno —el onboarding, que
    pasa una sola vez y antes de cualquier test del banco— se captura con sus
    secretos para que el test de humo lo compruebe contra HA real.

    Control negativo (T042), comprobado en local y restaurado: sin
    `anotar(acceso)` en el onboarding cae
    `test_secretos_del_arranque_y_ninguno_en_el_log` (faltan secretos); sin el
    manejador de logging en `_capturar_arranque` cae
    `test_la_captura_ve_lo_que_se_registra`.
    """

    def setUp(self) -> None:
        entorno._reiniciar()

    def tearDown(self) -> None:
        entorno._reiniciar()

    async def _arrancar(self) -> entorno.EntornoBanco:
        async with CoreDoble() as core:
            with mock.patch.dict(os.environ, {**_sin_variables(), entorno.VAR_URL: core.url}, clear=True), \
                    mock.patch.object(entorno, "INTERVALO", 0.01):
                return await asyncio.to_thread(entorno.exigir_banco)

    async def test_secretos_del_arranque_y_ninguno_en_el_log(self) -> None:
        self.assertIsNone(entorno.registro_del_arranque())
        uno = await self._arrancar()
        registro = entorno.registro_del_arranque()
        assert registro is not None
        # Usuario, contraseña, código, token de acceso, de larga duración y de add-on.
        self.assertEqual(len(registro.secretos), 6)
        self.assertIn(uno.token_core, registro.secretos)
        self.assertIn(uno.token_addon, registro.secretos)
        self.assertGreater(registro.eventos, 0, "el onboarding registra sus pasos")
        for secreto in registro.secretos:
            self.assertNotIn(secreto, registro.log)
            self.assertNotIn(secreto, repr(registro))

    async def test_la_captura_ve_lo_que_se_registra(self) -> None:
        # Si el onboarding registrase el token (por stdlib o por structlog),
        # el registro lo vería: la comprobación de arriba no pasa en vacío.
        original = onboarding._token_larga_duracion

        async def chivato(session: Any, core_url: str, token: str) -> str:
            resultado = await original(session, core_url, token)
            logging.getLogger("banco.chivato").debug("acceso %s", token)
            structlog.get_logger("banco.chivato").info("larga", token=resultado)
            return resultado

        with mock.patch.object(onboarding, "_token_larga_duracion", chivato):
            uno = await self._arrancar()
        registro = entorno.registro_del_arranque()
        assert registro is not None
        self.assertIn(uno.token_core, registro.log)
        self.assertIn(registro.secretos[3], registro.log)


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


class TestLectorGenerico(unittest.IsolatedAsyncioTestCase):
    """`comando` y `rest` del lector (spec 028, T003): las comprobaciones de
    automatizaciones, scripts, escenas y Lovelace leen comandos WebSocket y
    rutas REST que no son de helpers.

    Control negativo (T005, anotado en el commit del tramo A): `rest` sin la
    cabecera `Authorization` de la sesión hace caer
    `test_rest_llega_con_el_token_de_core`; `comando` devolviendo el mensaje
    entero en vez de `result` hace caer `test_comando_ida_y_vuelta`.
    """

    async def asyncSetUp(self) -> None:
        self.core = CoreDoble(token_core="token-lector")
        await self.core.__aenter__()

    async def asyncTearDown(self) -> None:
        await self.core.__aexit__(None, None, None)

    async def test_comando_ida_y_vuelta(self) -> None:
        async with Lector(self.core.url, "token-lector") as lector:
            resultado = await lector.comando({"type": "lovelace/dashboards/list"})
        self.assertEqual(resultado["eco"], "lovelace/dashboards/list")
        self.assertEqual(resultado["datos"]["type"], "lovelace/dashboards/list")
        self.assertEqual(
            [c["type"] for c in self.core.registro.ws_comandos], ["lovelace/dashboards/list"]
        )

    async def test_comando_con_error_lanza_error_core(self) -> None:
        async with Lector(self.core.url, "token-lector") as lector:
            with self.assertRaises(ErrorCore) as ctx:
                await lector.comando({"type": "eco/error"})
        self.assertEqual(ctx.exception.codigo, "eco_error")

    async def test_rest_llega_con_el_token_de_core(self) -> None:
        async with Lector(self.core.url, "token-lector") as lector:
            estado_get, cuerpo_get = await lector.rest("GET", "/api/eco/x")
            estado_post, cuerpo_post = await lector.rest("POST", "/api/eco/x", {"a": 1})
            estado_del, cuerpo_del = await lector.rest("DELETE", "/api/eco/x")
        self.assertEqual((estado_get, estado_post, estado_del), (200, 200, 200))
        self.assertEqual(
            [(c["metodo"], c["ruta"]) for c in (cuerpo_get, cuerpo_post, cuerpo_del)],
            [("GET", "x"), ("POST", "x"), ("DELETE", "x")],
        )
        self.assertEqual(json.loads(cuerpo_post["cuerpo"]), {"a": 1})
        self.assertEqual(cuerpo_post["content_type"], "application/json")
        self.assertEqual(
            [r["token"] for r in self.core.registro.rest], ["token-lector"] * 3
        )
        self.assertNotIn("token-lector", repr(lector))

    async def test_rest_devuelve_el_estado_de_error(self) -> None:
        async with Lector(self.core.url, "token-lector") as lector:
            estado, _ = await lector.rest("GET", "/api/states/no_existe.x")
        self.assertEqual(estado, 404)


class TestLlamar(unittest.IsolatedAsyncioTestCase):
    """`llamar` (tramo B): un error de la tool es un fallo del test, y una lista
    devuelta por la tool (un bloque por elemento, o ninguno) se reconstruye."""

    @staticmethod
    def _cliente(content: list[str], is_error: bool = False) -> mock.MagicMock:
        resultado = mock.MagicMock(
            content=[mock.MagicMock(text=t) for t in content], is_error=is_error
        )
        cliente = mock.MagicMock()
        cliente.call_tool = mock.AsyncMock(return_value=resultado)
        return cliente

    async def test_error_de_la_tool_falla(self) -> None:
        cliente = self._cliente(["Error executing tool ha_x"], is_error=True)
        with self.assertRaises(AssertionError) as ctx:
            await entorno.llamar(cliente, "ha_x")
        self.assertIn("ha_x", str(ctx.exception))

    async def test_listas(self) -> None:
        self.assertEqual(await entorno.llamar(self._cliente([]), "ha_x"), [])
        self.assertEqual(
            await entorno.llamar(self._cliente(['{"a": 1}', '{"b": 2}']), "ha_x"),
            [{"a": 1}, {"b": 2}],
        )
        self.assertEqual(await entorno.llamar(self._cliente(['{"a": 1}']), "ha_x"), {"a": 1})

    async def test_registro_de_tools_llamadas_con_exito(self) -> None:
        # T037: solo cuenta lo que termina bien; un error de la tool o una
        # respuesta `{"error": …}` no. Control negativo (comprobado y
        # restaurado): anotando antes de mirar `is_error`, este test cae.
        entorno.tomar_tools_del_test()
        await entorno.llamar(self._cliente(['{"result": "ok"}']), "ha_bien")
        with self.assertRaises(AssertionError):
            await entorno.llamar(self._cliente(["Error executing tool ha_mal"], is_error=True), "ha_mal")
        await entorno.llamar(self._cliente(['{"error": "token caducado"}']), "ha_con_error")
        self.assertEqual(entorno.tomar_tools_del_test(), {"ha_bien"})
        self.assertEqual(entorno.tomar_tools_del_test(), set())


class TestServicioInexistente(unittest.TestCase):
    """T038: el `xfail` de `ha_reload_counters` solo admite el 400 de Core a
    `/services/counter/reload` con el servicio ausente en Core.

    Control negativo (T038), comprobado en local y restaurado: sin mirar los
    servicios de Core en `es_servicio_inexistente` cae
    `test_solo_el_400_del_servicio_que_core_no_tiene`.
    """

    @staticmethod
    def _fallo(estado: int, ruta: str = "/core/api/services/counter/reload") -> BaseException:
        from hermes.ha import HAConnectionError

        causa = HAConnectionError(
            f"HA REST POST http://127.0.0.1:1{ruta} failed {estado}: 400: Bad Request", status=estado
        )
        # Lo que registra el SDK de MCP: el error genérico, con la causa detrás.
        envoltorio = RuntimeError("Error executing tool ha_reload_counters")
        envoltorio.__cause__ = causa
        return envoltorio

    def test_solo_el_400_del_servicio_que_core_no_tiene(self) -> None:
        from tests.banco.base_helpers import es_servicio_inexistente

        sin_reload = {"counter": {"increment": {}, "decrement": {}}}
        con_reload = {"counter": {"increment": {}, "reload": {}}}
        self.assertTrue(es_servicio_inexistente([self._fallo(400)], sin_reload, "counter", "reload"))
        # Si Core sí tiene el servicio, el 400 es otra cosa.
        self.assertFalse(es_servicio_inexistente([self._fallo(400)], con_reload, "counter", "reload"))
        self.assertFalse(es_servicio_inexistente([self._fallo(500)], sin_reload, "counter", "reload"))
        self.assertFalse(
            es_servicio_inexistente(
                [self._fallo(400, "/core/api/services/counter/increment")], sin_reload, "counter", "reload"
            )
        )
        self.assertFalse(es_servicio_inexistente([], sin_reload, "counter", "reload"))
        self.assertFalse(
            es_servicio_inexistente([AssertionError("vista previa inesperada")], sin_reload, "counter", "reload")
        )

    def test_errores_de_tools_recoge_lo_que_registra_el_sdk(self) -> None:
        from tests.banco.base_helpers import errores_de_tools

        fallo = self._fallo(400)
        with errores_de_tools() as errores:
            try:
                raise fallo
            except RuntimeError:
                logging.getLogger("mcp.server.mcpserver.server").exception("Tool %r raised", "ha_x")
        self.assertEqual(errores, [fallo])


if __name__ == "__main__":
    unittest.main()
