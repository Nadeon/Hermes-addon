"""Tests de la política de calidad de `auth_password`.

Dos propiedades importan aquí, y tiran en direcciones opuestas:

- que atrape lo adivinable, porque el freno anti-fuerza-bruta del login deja un
  techo de unos 2.000 intentos al día y eso solo es suficiente si la password
  no está entre las que se prueban primero;
- que NO rechace lo legítimo, porque un falso positivo deja al dueño sin poder
  arrancar el add-on. Por eso hay un test estadístico contra passwords
  generadas al azar, y no solo una lista de ejemplos escogidos a mano.
"""

import random
import string
import unittest

from hermes.password_policy import (
    MIN_AUTH_PASSWORD_LENGTH,
    MIN_CARACTERES_DISTINTOS,
    motivo_debil,
)

HOSTNAME = "hermes.tail-abc123.ts.net"


class TestPasswordsDebiles(unittest.TestCase):
    def _rechaza(self, password: str) -> str:
        motivo = motivo_debil(password, public_hostname=HOSTNAME)
        self.assertIsNotNone(motivo, f"deberia rechazar {password!r}")
        return motivo or ""

    def test_demasiado_corta(self) -> None:
        self.assertIn("mínimo", self._rechaza("dq7HmZ2xVw"))

    def test_pocos_caracteres_distintos(self) -> None:
        self.assertIn("distintos", self._rechaza("x" * MIN_AUTH_PASSWORD_LENGTH))
        self.assertIn("distintos", self._rechaza("ababababababab"))

    def test_unidad_repetida(self) -> None:
        # Cinco caracteres distintos, para que no la pare la regla de variedad
        # y se vea que es esta la que actua.
        self.assertIn("repetido", self._rechaza("Zq7mK" * 3))

    def test_tirada_seguida(self) -> None:
        for p in ("123456789012", "abcdefghijkl", "qwertyuiop12",
                  "987654321098", "micasa123456"):
            with self.subTest(password=p):
                self.assertIn("tirada", self._rechaza(p))

    def test_caracteres_estrenados_en_orden(self) -> None:
        """`112233445566` estrena del 1 al 6 en orden, sin tirada contigua."""
        self.assertIn("orden", self._rechaza("112233445566"))

    def test_passwords_conocidas(self) -> None:
        for p in ("password1234", "Password1234", "1q2w3e4r5t6y",
                  "contraseña123", "administrator"):
            with self.subTest(password=p):
                self.assertIn("más usadas", self._rechaza(p))

    def test_palabras_del_contexto(self) -> None:
        self.assertIn("hermes", self._rechaza("MiHermesSegura7"))
        self.assertIn("hassio", self._rechaza("Kq7mHassioZx4V"))

    def test_trozo_del_hostname(self) -> None:
        self.assertIn("hostname", self._rechaza("Kq7abc123ZxWm"))

    def test_el_motivo_nunca_cita_la_password(self) -> None:
        """Principio II: el motivo acaba en el log; la password no puede ir."""
        for p in ("x" * 14, "123456789012", "password1234", "Zq7m" * 4,
                  "MiHermesSegura7", "Kq7abc123ZxWm", "112233445566"):
            with self.subTest(password=p):
                motivo = self._rechaza(p)
                self.assertNotIn(p.lower(), motivo.lower())


class TestPasswordsFuertes(unittest.TestCase):
    def test_ejemplos_legitimos(self) -> None:
        for p in ("T7qm-Zx4Vk9bRw2s", "dq7HmZ2xVw9K",
                  "correcto-caballo-bateria-grapa-7", "Zk4$mQ9!wR2vLx8p"):
            with self.subTest(password=p):
                self.assertIsNone(
                    motivo_debil(p, public_hostname=HOSTNAME),
                    f"no deberia rechazar {p!r}",
                )

    def test_sin_falsos_positivos_sobre_passwords_generadas(self) -> None:
        """Lo que sale de un gestor de contraseñas tiene que pasar.

        Semilla fija para que el resultado no dependa de la suerte del día. El
        umbral es 0,1%: medido sobre 100.000 muestras por alfabeto, el peor
        caso real es el 0,018% de los números de 16 dígitos que contienen por
        casualidad una tirada de seis dígitos seguidos.
        """
        rnd = random.Random(20260906)
        alfabetos = {
            "alfanumerico-12": (string.ascii_letters + string.digits, 12),
            "alfanumerico-16": (string.ascii_letters + string.digits, 16),
            "con-simbolos-16": (string.ascii_letters + string.digits + "!@#$%*-_=+", 16),
            "hexadecimal-32": ("0123456789abcdef", 32),
            "base64-24": (string.ascii_letters + string.digits + "+/", 24),
        }
        for nombre, (alfabeto, largo) in alfabetos.items():
            with self.subTest(alfabeto=nombre):
                muestras = 5_000
                rechazadas = sum(
                    1
                    for _ in range(muestras)
                    if motivo_debil(
                        "".join(rnd.choice(alfabeto) for _ in range(largo)),
                        public_hostname=HOSTNAME,
                    )
                )
                self.assertLessEqual(
                    rechazadas / muestras, 0.001,
                    f"{nombre}: rechaza {rechazadas} de {muestras} legitimas",
                )

    def test_el_umbral_de_variedad_es_el_calibrado(self) -> None:
        """Si alguien sube MIN_CARACTERES_DISTINTOS, que sepa lo que cuesta.

        Con 6 empezaria a rechazar hexadecimal legitimo (0,25% medido); con 5
        no hay falsos positivos en ningun alfabeto realista.
        """
        self.assertEqual(MIN_CARACTERES_DISTINTOS, 5)


if __name__ == "__main__":
    unittest.main()
