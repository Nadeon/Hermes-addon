"""Tests para hermes.security.redact_secrets."""

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


if __name__ == "__main__":
    unittest.main()
