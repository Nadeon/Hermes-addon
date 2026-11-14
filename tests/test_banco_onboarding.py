"""Onboarding automático del banco de pruebas de Core (spec 010, FR-003, FR-012).

Se prueba contra el doble de Core (`tests/banco/core_doble.py`), sin Docker:
el orden de los pasos, el `client_id`/`redirect_uri` que acepta indieauth, la
espera a `state: RUNNING`, el error con paso y código sin cuerpo, y que
ninguna credencial generada acaba en el log ni en un mensaje de error.

Control negativo (T007), comprobado en local y restaurado:
  1. sin la espera a `RUNNING` cae `test_espera_a_running_y_falla_si_no_llega`
     (y `test_espera_a_running`);
  2. copiando el cuerpo de la respuesta en el error cae
     `test_error_con_paso_y_estado_sin_cuerpo`;
  3. con `client_id` sin barra final cae `test_client_id_y_redirect_uri`.
"""

from __future__ import annotations

import logging
import secrets
import unittest
from unittest import mock

import structlog

from tests.banco.core_doble import CoreDoble
from tests.banco.onboarding import BancoNoDisponible, CredencialesCore, preparar_core


class TestPrepararCore(unittest.IsolatedAsyncioTestCase):
    async def test_pasos_en_orden_y_token_de_larga_duracion(self) -> None:
        async with CoreDoble() as core:
            cred = await preparar_core(core.url, intervalo=0.01)
        self.assertEqual(
            core.registro.pasos,
            ["users", "token", "core_config", "analytics", "integration"],
        )
        # El token final es uno de larga duración pedido por WebSocket.
        tipos = [c.get("type") for c in core.registro.ws_comandos]
        self.assertEqual(tipos, ["auth/long_lived_access_token"])
        self.assertEqual(core.registro.ws_comandos[0]["lifespan"], 1)
        self.assertTrue(cred.token_core)
        self.assertEqual(cred.version_core, "2026.11.1")

    async def test_client_id_y_redirect_uri(self) -> None:
        async with CoreDoble() as core:
            await preparar_core(core.url, intervalo=0.01)
        integracion = core.registro.integracion
        # indieauth exige mismo esquema y netloc; el client_id es la URL base
        # con barra final, como lo manda el frontend de HA.
        self.assertEqual(integracion["client_id"], core.url + "/")
        self.assertEqual(integracion["redirect_uri"], core.url + "/?auth_callback=1")

    async def test_espera_a_running(self) -> None:
        async with CoreDoble(sondeos_not_running=3) as core:
            await preparar_core(core.url, intervalo=0.01)
        self.assertGreaterEqual(core.registro.sondeos_config, 4)

    async def test_espera_a_running_y_falla_si_no_llega(self) -> None:
        async with CoreDoble(sondeos_not_running=10_000) as core:
            with self.assertRaises(BancoNoDisponible) as ctx:
                await preparar_core(core.url, timeout_running=0.3, intervalo=0.01)
        self.assertEqual(ctx.exception.paso, "running")
        self.assertIn("running", str(ctx.exception))
        # Sin token de larga duración: se para antes.
        self.assertEqual(core.registro.ws_comandos, [])

    async def test_http_que_no_responde(self) -> None:
        async with CoreDoble() as core:
            url = core.url
        # El doble ya está parado: el puerto está cerrado.
        with self.assertRaises(BancoNoDisponible) as ctx:
            await preparar_core(url, timeout_http=0.3, intervalo=0.01)
        self.assertEqual(ctx.exception.paso, "espera_http")

    async def test_error_con_paso_y_estado_sin_cuerpo(self) -> None:
        async with CoreDoble(fallos={"analytics": 403}) as core:
            with self.assertRaises(BancoNoDisponible) as ctx:
                await preparar_core(core.url, intervalo=0.01)
        self.assertEqual(ctx.exception.paso, "analytics")
        self.assertEqual(ctx.exception.estado, 403)
        self.assertIn("analytics", str(ctx.exception))
        self.assertIn("403", str(ctx.exception))
        self.assertNotIn("cuerpo-del-error", str(ctx.exception))

    async def test_usuario_ya_hecho_es_un_fallo(self) -> None:
        async with CoreDoble() as core:
            await preparar_core(core.url, intervalo=0.01)
            with self.assertRaises(BancoNoDisponible) as ctx:
                await preparar_core(core.url, intervalo=0.01)
        self.assertEqual((ctx.exception.paso, ctx.exception.estado), ("users", 403))

    async def test_fallo_del_token_de_larga_duracion(self) -> None:
        async with CoreDoble(fallos={"long_lived": 1}) as core:
            with self.assertRaises(BancoNoDisponible) as ctx:
                await preparar_core(core.url, intervalo=0.01)
        self.assertEqual(ctx.exception.paso, "long_lived")
        self.assertNotIn("cuerpo-del-error", str(ctx.exception))


class TestSinCredencialesEnElLog(unittest.IsolatedAsyncioTestCase):
    """FR-012: ni la contraseña ni los tokens salen en el log ni en errores."""

    async def _con_centinelas(self, **doble: object) -> tuple[list[str], list, str, str]:
        generados: list[str] = []
        original_urlsafe = secrets.token_urlsafe
        original_hex = secrets.token_hex

        def centinela_urlsafe(n: int | None = None) -> str:
            valor = original_urlsafe(n)
            generados.append(valor)
            return valor

        def centinela_hex(n: int | None = None) -> str:
            valor = original_hex(n)
            generados.append(valor)
            return valor

        error = ""
        with self.assertLogs(level=logging.DEBUG) as caplog, \
                structlog.testing.capture_logs() as eventos, \
                mock.patch("secrets.token_urlsafe", centinela_urlsafe), \
                mock.patch("secrets.token_hex", centinela_hex):
            # Se parchea el módulo `secrets` entero: así quedan anotados tanto
            # lo que genera el onboarding (usuario, contraseña) como lo que
            # emite el doble (código y tokens), que hace de Core.
            logging.getLogger("banco-centinela").debug("inicio")
            async with CoreDoble(**doble) as core:  # type: ignore[arg-type]
                try:
                    await preparar_core(core.url, intervalo=0.01)
                except BancoNoDisponible as exc:
                    error = str(exc)
        texto_log = "\n".join(caplog.output) + "\n" + repr(eventos)
        return generados, eventos, texto_log, error

    async def test_arranque_completo(self) -> None:
        generados, eventos, texto_log, _ = await self._con_centinelas()
        # Contraseña, usuario, código, token de acceso y de larga duración.
        self.assertGreaterEqual(len(generados), 4)
        self.assertTrue(eventos, "el onboarding debería registrar sus pasos")
        for valor in generados:
            self.assertNotIn(valor, texto_log)

    async def test_fallo_a_mitad(self) -> None:
        generados, _, texto_log, error = await self._con_centinelas(fallos={"integration": 500})
        self.assertIn("integration", error)
        for valor in generados:
            self.assertNotIn(valor, texto_log)
            self.assertNotIn(valor, error)

    async def test_repr_de_credenciales_sin_token(self) -> None:
        cred = CredencialesCore(token_core="token-secreto-de-prueba", version_core="2026.11.1")
        self.assertNotIn("token-secreto-de-prueba", repr(cred))
        self.assertNotIn("token-secreto-de-prueba", str(cred))
        self.assertIn("2026.11.1", repr(cred))


if __name__ == "__main__":
    unittest.main()
