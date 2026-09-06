"""Tests de las señales que hacen diagnosticable el flujo OAuth.

Nacen de un fallo real: un cliente recibía la redirección con su código y no
volvía nunca a canjearlo. En el log eso no dejaba **ningún** rastro —ni un
error, ni un aviso—, así que era indistinguible de que nunca hubiera llegado a
autorizarse. Y el fallo de login usaba el mismo mensaje para tres causas
distintas, así que la pantalla decía "contraseña incorrecta" con la contraseña
buena.

Un log que nadie comprueba se pudre igual que el código, así que estas señales
llevan test.
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from hermes import oauth as oauth_mod


class TestMotivoDelFalloDeLogin(unittest.TestCase):
    """Los tres caminos que devuelven "Authentication failed" se distinguen."""

    def test_los_tres_motivos_existen_en_el_codigo(self) -> None:
        """bad_password, unknown_client y redirect_uri_mismatch, por separado."""
        import inspect

        fuente = inspect.getsource(oauth_mod.OAuthServer.authorize_post)
        for motivo in ("bad_password", "unknown_client", "redirect_uri_mismatch"):
            with self.subTest(motivo=motivo):
                self.assertIn(f'reason="{motivo}"', fuente)

    def test_la_respuesta_al_cliente_sigue_siendo_la_misma(self) -> None:
        """El motivo va al log, nunca a la pantalla.

        Distinguirlos en el log es seguro porque los tres se comprueban después
        de validar la password. Distinguirlos en pantalla sería regalar
        información a quien todavía no ha pasado esa puerta.
        """
        import inspect

        fuente = inspect.getsource(oauth_mod.OAuthServer.authorize_post)
        self.assertEqual(
            fuente.count('error="Authentication failed. Please try again."'),
            3,
            "los tres caminos deben seguir devolviendo el mismo texto",
        )


class TestDestinoDeLaRedireccion(unittest.TestCase):
    def test_se_registra_el_host_pero_nunca_la_url_entera(self) -> None:
        """La URL de redirección lleva el código dentro: no puede ir al log."""
        import inspect

        fuente = inspect.getsource(oauth_mod.OAuthServer.authorize_post)
        self.assertIn("redirect_host=urlparse(redirect_uri).netloc", fuente)
        self.assertNotIn("redirect_url=redirect_url", fuente)
        self.assertNotIn("url=redirect_url", fuente)

    def test_se_registra_si_venia_state(self) -> None:
        import inspect

        fuente = inspect.getsource(oauth_mod.OAuthServer.authorize_post)
        self.assertIn("has_state=bool(state)", fuente)


class TestCodigoEmitidoYNoCanjeado(unittest.TestCase):
    """El caso que no dejaba rastro: se emite el código y nadie vuelve."""

    def setUp(self) -> None:
        oauth_mod._ensure_dirs()
        for f in oauth_mod._CODES_DIR.glob("*.json"):
            f.unlink()

    def _escribir_codigo(self, client_id: str, *, caducado: bool) -> None:
        ahora = time.time()
        oauth_mod._atomic_write(
            oauth_mod._CODES_DIR / f"{client_id}.json",
            {
                "code": "x",
                "client_id": client_id,
                "expires_at": ahora - 10 if caducado else ahora + 300,
            },
        )

    def test_avisa_cuando_un_codigo_caduca_sin_canjear(self) -> None:
        self._escribir_codigo("cliente-que-no-volvio", caducado=True)
        servidor = oauth_mod.OAuthServer.__new__(oauth_mod.OAuthServer)

        with patch.object(oauth_mod.logger, "warning") as aviso:
            oauth_mod.OAuthServer._cleanup_expired(servidor)

        eventos = [c.args[0] for c in aviso.call_args_list if c.args]
        self.assertIn("oauth_code_expired_unused", eventos)
        kwargs = next(c.kwargs for c in aviso.call_args_list
                      if c.args and c.args[0] == "oauth_code_expired_unused")
        self.assertEqual(kwargs["count"], 1)
        self.assertIn("cliente-que-no-volvio", kwargs["client_ids"])

    def test_no_avisa_de_los_codigos_todavia_vivos(self) -> None:
        self._escribir_codigo("cliente-en-curso", caducado=False)
        servidor = oauth_mod.OAuthServer.__new__(oauth_mod.OAuthServer)

        with patch.object(oauth_mod.logger, "warning") as aviso:
            oauth_mod.OAuthServer._cleanup_expired(servidor)

        eventos = [c.args[0] for c in aviso.call_args_list if c.args]
        self.assertNotIn("oauth_code_expired_unused", eventos)

    def test_el_aviso_no_lleva_el_codigo_dentro(self) -> None:
        """El aviso identifica al cliente, nunca el secreto que se le dio."""
        self._escribir_codigo("cliente-x", caducado=True)
        servidor = oauth_mod.OAuthServer.__new__(oauth_mod.OAuthServer)

        with patch.object(oauth_mod.logger, "warning") as aviso:
            oauth_mod.OAuthServer._cleanup_expired(servidor)

        kwargs = next(c.kwargs for c in aviso.call_args_list
                      if c.args and c.args[0] == "oauth_code_expired_unused")
        self.assertNotIn("code", kwargs)
        self.assertNotIn("x", str(kwargs.get("client_ids", [])).replace("cliente-x", ""))


if __name__ == "__main__":
    unittest.main()
