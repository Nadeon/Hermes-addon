"""Tests de la validación de configuración (fortaleza de auth_password, etc.)."""

import unittest

from hermes.config import MIN_AUTH_PASSWORD_LENGTH, HermesConfig


class TestConfigValidation(unittest.TestCase):
    def _cfg(self, password: str) -> HermesConfig:
        return HermesConfig(
            auth_password=password,
            public_hostname="hermes.tail-xxxx.ts.net",
            supervisor_token="supervisor-token",
        )

    def test_rejects_empty_password(self) -> None:
        with self.assertRaises(ValueError):
            self._cfg("").validate()

    def test_rejects_short_password(self) -> None:
        with self.assertRaises(ValueError):
            self._cfg("short").validate()
        with self.assertRaises(ValueError):
            self._cfg("x" * (MIN_AUTH_PASSWORD_LENGTH - 1)).validate()

    def test_accepts_strong_password(self) -> None:
        # No debe lanzar.
        self._cfg("x" * MIN_AUTH_PASSWORD_LENGTH).validate()
        self._cfg("a-long-random-passphrase-9f3a").validate()

    def test_requires_hostname(self) -> None:
        cfg = HermesConfig(
            auth_password="x" * MIN_AUTH_PASSWORD_LENGTH,
            public_hostname="",
            supervisor_token="t",
        )
        with self.assertRaises(ValueError):
            cfg.validate()

    def test_requires_supervisor_token(self) -> None:
        cfg = HermesConfig(
            auth_password="x" * MIN_AUTH_PASSWORD_LENGTH,
            public_hostname="h.ts.net",
            supervisor_token="",
        )
        with self.assertRaises(ValueError):
            cfg.validate()


if __name__ == "__main__":
    unittest.main()
