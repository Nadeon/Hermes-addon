"""Tests para hermes.security.redact_secrets."""

import random
import re
import time
import unittest

from hermes.security import redact_secrets


class TestRedactSecrets(unittest.TestCase):
    """Tests de la función redact_secrets."""

    # ── Casos básicos ───────────────────────────────────────────────────────

    def test_empty_string(self):
        assert redact_secrets("") == ""

    def test_no_secrets(self):
        line = "2026-01-01 12:00:00: Connection accepted from 192.168.1.1"
        assert redact_secrets(line) == line

    # ── Patrón 3: key: value ────────────────────────────────────────────────

    def test_password_colon(self):
        raw = "password: secret123"
        result = redact_secrets(raw)
        assert "secret123" not in result
        assert "***REDACTED***" in result
        assert "password" in result

    def test_password_equals(self):
        raw = "password=secret123"
        result = redact_secrets(raw)
        assert "secret123" not in result
        assert "***REDACTED***" in result

    def test_token_colon(self):
        raw = "token: abc123xyz"
        result = redact_secrets(raw)
        assert "abc123xyz" not in result
        assert "***REDACTED***" in result

    def test_api_key(self):
        raw = "api_key: my-super-secret-key"
        result = redact_secrets(raw)
        assert "my-super-secret-key" not in result

    def test_client_secret(self):
        raw = "client_secret: verysecret"
        result = redact_secrets(raw)
        assert "verysecret" not in result

    def test_access_token(self):
        raw = "access_token: tok_abc123"
        result = redact_secrets(raw)
        assert "tok_abc123" not in result

    def test_case_insensitive(self):
        raw = "PASSWORD: hunter2"
        result = redact_secrets(raw)
        assert "hunter2" not in result

    def test_mosquitto_password_line(self):
        """Simula una línea de log de Mosquitto con password en claro."""
        raw = "listener 1883\npassword_file /mosquitto/config/passwd\npassword: mypassword"
        result = redact_secrets(raw)
        assert "mypassword" not in result

    # ── Patrón 2: basic auth en URL ─────────────────────────────────────────

    def test_basic_auth_http(self):
        raw = "Connecting to http://admin:superpassword@192.168.1.1:3000/api"
        result = redact_secrets(raw)
        assert "superpassword" not in result
        assert "***" in result
        assert "admin" in result  # username se mantiene
        assert "192.168.1.1" in result  # host se mantiene

    def test_basic_auth_https(self):
        raw = "mysql://user:pass@host:3306/db"
        result = redact_secrets(raw)
        assert "pass" not in result or "***" in result
        # Acepta resultado: mysql://user:***@host:3306/db
        assert "user" in result
        assert "host" in result

    def test_basic_auth_no_false_positive(self):
        """Una URL sin basic auth no debe ser modificada."""
        raw = "https://api.example.com/endpoint"
        assert redact_secrets(raw) == raw

    # ── Patrón 1: JWT ────────────────────────────────────────────────────────

    def test_jwt_redacted(self):
        jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0"
            ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        raw = f"Authorization: Bearer {jwt}"
        result = redact_secrets(raw)
        assert jwt not in result
        assert "***JWT_REDACTED***" in result

    def test_jwt_in_log_line(self):
        jwt = (
            "eyJhbGciOiJSUzI1NiJ9"
            ".eyJpc3MiOiJoYSIsImlhdCI6MTYwMH0"
            ".signature_here_abc123"
        )
        raw = f"2026-01-01 token={jwt} user=admin"
        result = redact_secrets(raw)
        assert jwt not in result

    def test_partial_jwt_not_redacted(self):
        """Dos partes de JWT (sin tercera) no deben ser redactadas."""
        partial = "eyJhbGci.eyJzdWIi"  # solo 2 partes
        raw = f"debug {partial} end"
        result = redact_secrets(raw)
        # No debe modificarlo (no es un JWT válido)
        assert result == raw

    # ── Múltiples secretos en un texto ──────────────────────────────────────

    def test_multiple_patterns(self):
        raw = (
            "password: hunter2\n"
            "token: abc123\n"
            "No secrets here: just normal log\n"
        )
        result = redact_secrets(raw)
        assert "hunter2" not in result
        assert "abc123" not in result
        assert "No secrets here: just normal log" in result

    def test_multiline_grafana_log(self):
        """Simula un log de Grafana con token en una línea."""
        raw = (
            "t=2026-01-01T00:00:00Z level=info msg=Login user=admin\n"
            "t=2026-01-01T00:00:01Z level=debug api_key=grafana_sa_token_secretvalue\n"
            "t=2026-01-01T00:00:02Z level=info msg=Dashboard loaded id=1\n"
        )
        result = redact_secrets(raw)
        assert "secretvalue" not in result
        assert "grafana_sa_token_" not in result or "***REDACTED***" in result

    # ── No debería tocar líneas inocentes ────────────────────────────────────

    def test_no_modification_of_normal_log(self):
        normal = "2026-01-01 Connected to MQTT broker at 192.168.1.1:1883"
        assert redact_secrets(normal) == normal

    def test_preserves_structure(self):
        """Los saltos de línea se preservan."""
        raw = "line1\nline2\nline3"
        result = redact_secrets(raw)
        assert result.count("\n") == 2


class TestRedactSecretsEdgeCases(unittest.TestCase):
    """Casos borde del redactor."""

    def test_key_without_value(self):
        """Clave sin valor — no debe crashear."""
        raw = "password:"
        # Puede o no redactar, pero no debe lanzar excepción
        result = redact_secrets(raw)
        assert isinstance(result, str)

    def test_very_long_value(self):
        """Valor muy largo (cert PEM simulado en una línea) debe redactarse."""
        raw = "password: " + "A" * 2000
        result = redact_secrets(raw)
        assert "A" * 2000 not in result

    def test_unicode_preserved(self):
        """Texto unicode sin secretos se preserva."""
        raw = "Conexión aceptada desde 192.168.1.1 — usuario: pepe"
        assert redact_secrets(raw) == raw


# ── FR-001 (009): redacción lineal ─────────────────────────────────────────

_MIB = 1024 * 1024


def _repetir(trozo: str, tam: int = _MIB) -> str:
    """`trozo` repetido hasta `tam` caracteres, sin espacios."""
    return (trozo * (tam // len(trozo) + 1))[:tam]


class TestRedaccionLineal(unittest.TestCase):
    """FR-001: 1 MiB de cada forma adversaria se redacta en menos de 1 s.

    Medido en la 1.1.2: 30 KB de estas formas tardaban 0,4–0,6 s en
    `_BASIC_AUTH_URL_RE`, `_JWT_RE` o `_JSON_SECRET_RE` (cuadráticas: cada
    posición de una racha recorría la racha entera), y `sv_get_addon_logs`
    redacta en el bucle de eventos, así que un log así bloqueaba Hermes. Con
    1 MiB, la 1.1.2 tardaría minutos; lo lineal, decenas de milisegundos. El
    umbral de 1 s es holgado a propósito para no ser frágil en un runner lento.

    Control negativo (T007): con las tres expresiones de la 1.1.2 caen los
    cinco tests de esta clase.
    """

    LIMITE_S = 1.0

    def _medir(self, texto: str) -> None:
        inicio = time.perf_counter()
        redact_secrets(texto)
        tardado = time.perf_counter() - inicio
        self.assertLess(
            tardado, self.LIMITE_S,
            f"redact_secrets tardó {tardado:.2f} s con 1 MiB",
        )

    def test_letras_sin_esquema(self):
        self._medir(_repetir("a"))

    def test_letras_y_puntos(self):
        self._medir(_repetir("a."))

    def test_esquema_y_usuario_sin_arroba(self):
        self._medir(_repetir("a://b:c"))

    def test_muchos_inicios_de_jwt(self):
        self._medir(_repetir("eyJ"))

    def test_clave_json_sin_cierre(self):
        self._medir('"' + _repetir("password", _MIB - 1))


# Copia literal de las tres expresiones y de `redact_secrets` de la 1.1.2, como
# referencia del test diferencial. Las otras dos expresiones no cambian, así
# que se importan.
from hermes.security import _BARE_SECRET_RE, _SECRET_KEY_RE  # noqa: E402

_BASIC_AUTH_URL_RE_112 = re.compile(
    r"([a-zA-Z][a-zA-Z0-9+\-.]*://[^:/@\s]+)"  # scheme://user
    r"(:)([^@\s]+)"                              # :password
    r"(@)",                                      # @host separator
)

_JWT_RE_112 = re.compile(
    r"eyJ[A-Za-z0-9_\-]{2,}\.[A-Za-z0-9_\-]{2,}\.[A-Za-z0-9_\-]{2,}"
)

_JSON_SECRET_RE_112 = re.compile(
    r'("(?:[A-Za-z0-9_.-]*(?:password|passwd|passphrase|secret|token|api[_-]?key|'
    r'auth[_-]?key|credential|private[_-]?key)[A-Za-z0-9_.-]*)"\s*:\s*")([^"]*)(")',
    re.IGNORECASE,
)


def _redact_secrets_112(text: str) -> str:
    if not text:
        return text
    text = _JWT_RE_112.sub("***JWT_REDACTED***", text)
    text = _JSON_SECRET_RE_112.sub(r"\1***REDACTED***\3", text)
    text = _BASIC_AUTH_URL_RE_112.sub(r"\1\2***\4", text)
    text = _SECRET_KEY_RE.sub(r"\1\2***REDACTED***", text)
    text = _BARE_SECRET_RE.sub(r"\1***REDACTED***", text)
    return text


_FRAGMENTOS = (
    "eyJ", "eyJ", ".", ".", "://", ":", ":", "@", "@", '"', '"', "password",
    "token", "api_key", "=", " ", "a", "b", "Z", "x", "9", "0", "-", "_",
    "PassWord", "\t", "/", "+",
)


def _corpus(n: int = 6000) -> list[str]:
    """Textos de 1–80 caracteres hechos de fragmentos, con semilla fija."""
    rnd = random.Random(2026)
    textos = []
    for _ in range(n):
        objetivo = rnd.randint(1, 80)
        trozos: list[str] = []
        largo = 0
        while largo < objetivo:
            t = rnd.choice(_FRAGMENTOS)
            trozos.append(t)
            largo += len(t)
        textos.append("".join(trozos)[:objetivo])
    return textos


class TestRedaccionDiferencial(unittest.TestCase):
    """FR-001 / S-01: la redacción lineal da exactamente lo mismo que la 1.1.2.

    Sin excepciones: en todo el corpus la salida es idéntica (no redacta más ni
    menos). Una variante con lookbehind (`(?<![A-Za-z0-9_-])eyJ…`) sería lineal
    pero dejaría `xeyJ…` sin redactar; este test y el de los casos fijos la
    detectan.

    Control negativo (T007): con la variante lookbehind en `_JWT_RE`, cae.
    """

    def test_corpus_aleatorio(self):
        distintos = 0
        for texto in _corpus():
            esperado = _redact_secrets_112(texto)
            obtenido = redact_secrets(texto)
            if obtenido != esperado:
                distintos += 1
                with self.subTest(texto=texto):
                    self.assertEqual(obtenido, esperado)
        self.assertEqual(distintos, 0)

    def test_casos_fijos(self):
        casos = [
            "xeyJhbGc.eyJzdWIi.c2lnbmF0",
            "eyJab.cd.ef eyJxx.yy.zz",
            "eyJeyJab.cd.ef",
            "eyJa.bb.cc eyJab.c.dd eyJab.cd.e",
            "ab.eyJab.cd.ef.gh",
            "http://user:pass@host https://u:p@h",
            "9http://user:pass@host",
            "1+a.b-c://u:p:q@h",
            "a://b://c@d",
            "a://b:c a://b:c@d",
            "ftp://u:p\n@h",
            '"password": "x", "api_key":"y" "TOKEN" : "z"',
            '"passwordpassword" x "password": "v"',
            '"a"password": "v"',
            '"secretos":"' ,
            '"PaSsWoRd_hash" :\t"abc"',
        ]
        for texto in casos:
            with self.subTest(texto=texto):
                self.assertEqual(redact_secrets(texto), _redact_secrets_112(texto))


if __name__ == "__main__":
    unittest.main()
