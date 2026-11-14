"""Tests de la validación de configuración (fortaleza de auth_password, etc.)."""

import os
import unittest
from unittest import mock

from hermes.config import MIN_AUTH_PASSWORD_LENGTH, HermesConfig, load_config

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

    def test_sugiere_el_hostname_corregido(self) -> None:
        """El error más común es pegar la URL del conector, con su `/mcp`.

        Decir "sin esquema ni path" es correcto pero deja al usuario deducir
        cuál era el valor bueno. Enseñárselo no.
        """
        casos = {
            "homeassistant.tail-abc123.ts.net/mcp": "homeassistant.tail-abc123.ts.net",
            "https://hermes.midominio.com/mcp": "hermes.midominio.com",
            "http://hermes.midominio.com": "hermes.midominio.com",
            "hermes.midominio.com/": "hermes.midominio.com",
            "hermes.midominio.com/mcp?x=1": "hermes.midominio.com",
        }
        for puesto, esperado in casos.items():
            with self.subTest(public_hostname=puesto):
                cfg = HermesConfig(
                    auth_password=FUERTE,
                    public_hostname=puesto,
                    supervisor_token="t",
                )
                with self.assertRaises(ValueError) as ctx:
                    cfg.validate()
                self.assertIn(repr(esperado), str(ctx.exception))

    def test_no_sugiere_nada_cuando_no_hay_nada_que_sugerir(self) -> None:
        """Si limpiarlo tampoco da un hostname válido, no se inventa uno."""
        for basura in ("no vale", "///", "http://"):
            with self.subTest(public_hostname=basura):
                cfg = HermesConfig(
                    auth_password=FUERTE,
                    public_hostname=basura,
                    supervisor_token="t",
                )
                with self.assertRaises(ValueError) as ctx:
                    cfg.validate()
                self.assertNotIn("seguramente querías", str(ctx.exception))


def _cargar(**entorno: str) -> HermesConfig:
    """`load_config()` con un entorno limpio de variables HERMES_*.

    Se vacían todas para que una variable del entorno de quien ejecuta la
    suite no cambie el resultado.
    """
    limpio = {k: v for k, v in os.environ.items() if not k.startswith("HERMES_")}
    limpio.update(entorno)
    with mock.patch.dict(os.environ, limpio, clear=True):
        return load_config()


class TestLimitesEfectivos(unittest.TestCase):
    """FR-032…FR-035: valores por defecto y máximos efectivos de los límites.

    El esquema de config.yaml no se estrecha (S-03): el Supervisor valida las
    opciones guardadas al arrancar y un valor fuera de rango dejaría sin
    arrancar a quien lo tenga guardado. Los máximos se aplican al cargar.
    """

    def test_response_max_bytes_por_defecto_es_128_kib(self) -> None:
        cfg = _cargar()
        self.assertEqual(cfg.response_max_bytes, 131_072)
        self.assertEqual(cfg.adjustments, [])
        self.assertEqual(HermesConfig().response_max_bytes, 131_072)

    def test_el_antiguo_valor_por_defecto_se_sustituye(self) -> None:
        """La interfaz guarda 1 048 576 aunque nadie lo haya tocado."""
        cfg = _cargar(HERMES_RESPONSE_MAX_BYTES="1048576")
        self.assertEqual(cfg.response_max_bytes, 131_072)
        self.assertEqual(
            cfg.adjustments,
            [{"option": "response_max_bytes", "configured": 1_048_576,
              "applied": 131_072, "reason": "legacy_default"}],
        )

    def test_un_valor_personalizado_bajo_el_maximo_se_respeta(self) -> None:
        for valor in (300_000, 524_288, 10_240):
            with self.subTest(valor=valor):
                cfg = _cargar(HERMES_RESPONSE_MAX_BYTES=str(valor))
                self.assertEqual(cfg.response_max_bytes, valor)
                self.assertEqual(cfg.adjustments, [])

    def test_response_max_bytes_por_encima_del_maximo_se_recorta(self) -> None:
        cfg = _cargar(HERMES_RESPONSE_MAX_BYTES="4000000")
        self.assertEqual(cfg.response_max_bytes, 524_288)
        self.assertEqual(
            cfg.adjustments,
            [{"option": "response_max_bytes", "configured": 4_000_000,
              "applied": 524_288, "reason": "above_cap"}],
        )

    def test_wait_for_event_max_seconds_por_encima_del_maximo_se_recorta(self) -> None:
        cfg = _cargar(HERMES_WAIT_EVENT_MAX_SECONDS="300")
        self.assertEqual(cfg.wait_for_event_max_seconds, 220)
        self.assertEqual(
            cfg.adjustments,
            [{"option": "wait_for_event_max_seconds", "configured": 300,
              "applied": 220, "reason": "above_cap"}],
        )

    def test_wait_for_event_max_seconds_dentro_del_maximo_se_respeta(self) -> None:
        for valor in (220, 90, 10):
            with self.subTest(valor=valor):
                cfg = _cargar(HERMES_WAIT_EVENT_MAX_SECONDS=str(valor))
                self.assertEqual(cfg.wait_for_event_max_seconds, valor)
                self.assertEqual(cfg.adjustments, [])

    def test_wait_for_event_max_seconds_por_defecto_es_90(self) -> None:
        self.assertEqual(_cargar().wait_for_event_max_seconds, 90)

    def test_los_dos_ajustes_se_anotan_a_la_vez(self) -> None:
        cfg = _cargar(HERMES_RESPONSE_MAX_BYTES="1048576",
                      HERMES_WAIT_EVENT_MAX_SECONDS="300")
        self.assertEqual(
            [a["option"] for a in cfg.adjustments],
            ["response_max_bytes", "wait_for_event_max_seconds"],
        )


class TestOpcionesNuevas(unittest.TestCase):
    """FR-023 y FR-044: interruptores de CIMD y de la redacción de red."""

    def test_activadas_por_defecto(self) -> None:
        cfg = _cargar()
        self.assertIs(cfg.oauth_cimd_enabled, True)
        self.assertIs(cfg.log_redact_network, True)
        self.assertIs(HermesConfig().oauth_cimd_enabled, True)
        self.assertIs(HermesConfig().log_redact_network, True)

    def test_false_en_el_entorno_las_desactiva(self) -> None:
        cfg = _cargar(HERMES_OAUTH_CIMD_ENABLED="false",
                      HERMES_LOG_REDACT_NETWORK="false")
        self.assertIs(cfg.oauth_cimd_enabled, False)
        self.assertIs(cfg.log_redact_network, False)

    def test_cada_una_se_lee_de_su_variable(self) -> None:
        cfg = _cargar(HERMES_OAUTH_CIMD_ENABLED="false")
        self.assertIs(cfg.oauth_cimd_enabled, False)
        self.assertIs(cfg.log_redact_network, True)
        cfg = _cargar(HERMES_LOG_REDACT_NETWORK="false")
        self.assertIs(cfg.oauth_cimd_enabled, True)
        self.assertIs(cfg.log_redact_network, False)


if __name__ == "__main__":
    unittest.main()
