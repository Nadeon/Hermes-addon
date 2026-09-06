"""Tests de la validación de configuración (fortaleza de auth_password, etc.)."""

import unittest

from hermes.config import MIN_AUTH_PASSWORD_LENGTH, HermesConfig

# Password de prueba que pasa la política: longitud de sobra, caracteres
# variados y sin tiradas seguidas. Antes estos tests usaban "x" * 12, que
# afirmaba que doce equis eran una password fuerte.
FUERTE = "T7qm-Zx4Vk9bRw2s"


class TestConfigValidation(unittest.TestCase):
    def _cfg(self, password: str) -> HermesConfig:
        return HermesConfig(
            auth_password=password,
            public_hostname="hermes.tail-abc123.ts.net",
            supervisor_token="supervisor-token",
        )

    def test_rejects_empty_password(self) -> None:
        with self.assertRaises(ValueError):
            self._cfg("").validate()

    def test_rejects_short_password(self) -> None:
        with self.assertRaises(ValueError):
            self._cfg("short").validate()
        with self.assertRaises(ValueError):
            self._cfg("T7qm-Zx4Vk"[: MIN_AUTH_PASSWORD_LENGTH - 1]).validate()

    def test_rejects_weak_password_of_valid_length(self) -> None:
        """El mínimo de longitud no basta: 12 caracteres pueden ser basura."""
        for floja in ("x" * MIN_AUTH_PASSWORD_LENGTH, "123456789012",
                      "password1234", "qwertyuiop12", "HermesSegura1"):
            with self.subTest(password=floja), self.assertRaises(ValueError):
                self._cfg(floja).validate()

    def test_error_never_quotes_the_password(self) -> None:
        """El mensaje va al log del add-on: no puede llevar el valor dentro.

        Se prueban las dos reglas cuyo mensaje se acerca más a repetir lo que
        el usuario escribió: la de las palabras del contexto y la del hostname.
        """
        for secreta in ("MiHermesSegura7", "Kq7abc123ZxWm", "Zq7mK" * 3):
            with self.subTest(password=secreta):
                with self.assertRaises(ValueError) as ctx:
                    self._cfg(secreta).validate()
                self.assertNotIn(secreta, str(ctx.exception))
                self.assertNotIn(secreta.lower(), str(ctx.exception).lower())

    def test_accepts_strong_password(self) -> None:
        # No debe lanzar.
        self._cfg(FUERTE).validate()
        self._cfg("dq7HmZ2xVw9K").validate()

    def test_requires_hostname(self) -> None:
        cfg = HermesConfig(
            auth_password=FUERTE,
            public_hostname="",
            supervisor_token="t",
        )
        with self.assertRaises(ValueError):
            cfg.validate()

    def test_requires_supervisor_token(self) -> None:
        cfg = HermesConfig(
            auth_password=FUERTE,
            public_hostname="h.ts.net",
            supervisor_token="",
        )
        with self.assertRaises(ValueError):
            cfg.validate()


if __name__ == "__main__":
    unittest.main()
