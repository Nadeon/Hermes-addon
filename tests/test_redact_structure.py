"""Las respuestas del Supervisor no pueden llevar secretos al cliente MCP.

Caso que motiva estos tests: `sv_get_addon("local_hermes")` puede devolva el
bloque `options` completo del add-on, con **`auth_password` en claro**. Esa
contraseña es el único secreto que protege la instalación entera, y es de larga
duración: quien la leyera conservaría el acceso aunque se revocaran todos los
tokens OAuth. Además acababa en el contexto del modelo y en las transcripciones.

El mismo agujero afectaba a cualquier add-on: `sv_get_addon("core_mosquitto")`
habría expuesto las credenciales de MQTT, y el de Tailscale su auth key.
"""

from __future__ import annotations

import unittest

from hermes.security import redact_structure


class TestRedactStructure(unittest.TestCase):
    def test_the_reported_leak(self) -> None:
        """Reproduce el caso exacto: options de local_hermes."""
        info = {
            "slug": "local_hermes",
            "version": "1.2.3",
            "state": "started",
            "options": {
                "auth_password": "PLACEHOLDER-NO-ES-UNA-CLAVE-REAL",
                "public_hostname": "casa.tail1234.ts.net",
                "network_mode": "tailscale",
            },
        }
        out = redact_structure(info)
        self.assertNotIn("PLACEHOLDER-NO-ES-UNA-CLAVE-REAL", str(out))
        self.assertEqual(out["options"]["auth_password"], "***REDACTED***")
        # Lo que no es secreto se conserva intacto.
        self.assertEqual(out["options"]["public_hostname"], "casa.tail1234.ts.net")
        self.assertEqual(out["options"]["network_mode"], "tailscale")
        self.assertEqual(out["version"], "1.2.3")

    def test_arbitrary_addon_option_names(self) -> None:
        """Las opciones las nombra el autor del add-on: hace falta subcadena."""
        for key in ("mqtt_password", "ts_authkey", "api_token", "client_secret",
                    "OPENAI_API_KEY", "db_passwd", "private_key", "passphrase",
                    "Authorization", "salt", "user_credentials"):
            out = redact_structure({key: "valor-secreto"})
            self.assertEqual(out[key], "***REDACTED***", f"no redactó {key}")

    def test_claves_de_red_de_addons(self) -> None:
        """WireGuard/Z-Wave/Zigbee no llaman "password" a sus secretos.

        Caso verificado: este dict salía entero sin redactar por
        `sv_get_addon_options`, con el material criptográfico en claro.
        """
        data = {
            "peers": [{"psk": "abc123"}],
            "network_key": "nk",
            "pre_shared_key": "p",
            "api-key": "k1",
        }
        out = redact_structure(data)
        self.assertEqual(out["peers"][0]["psk"], "***REDACTED***")
        self.assertEqual(out["network_key"], "***REDACTED***")
        self.assertEqual(out["pre_shared_key"], "***REDACTED***")
        self.assertEqual(out["api-key"], "***REDACTED***")
        self.assertNotIn("abc123", str(out))

    def test_variantes_con_guion(self) -> None:
        """El guion es solo otra grafía de la misma clave."""
        for key in ("api-key", "auth-token", "pre-shared-key", "network-key",
                    "private-key", "client-secret", "db-password"):
            out = redact_structure({key: "valor-secreto"})
            self.assertEqual(out[key], "***REDACTED***", f"no redactó {key}")

    def test_mas_nombres_de_clave_criptografica(self) -> None:
        for key in ("wg_psk", "zwave_network_key", "encryption_key",
                    "shared_key", "privkey"):
            out = redact_structure({key: "valor-secreto"})
            self.assertEqual(out[key], "***REDACTED***", f"no redactó {key}")

    def test_key_a_secas_no_se_redacta(self) -> None:
        """`key` suelta es demasiado común para tratarla como secreto."""
        data = {"key": "enter", "keyboard_layout": "es", "sort_key": "name",
                "key_path": "/ssl/cert.key"}
        self.assertEqual(redact_structure(data), data)

    def test_non_secret_keys_are_untouched(self) -> None:
        data = {"username": "nadeon", "host": "1.2.3.4", "port": 1883,
                "url": "https://ejemplo.com", "slug": "core_mosquitto"}
        self.assertEqual(redact_structure(data), data)

    def test_only_strings_are_redacted(self) -> None:
        """Un número o un booleano bajo una clave 'sensible' no es un secreto."""
        data = {"token_expiry_seconds": 3600, "use_password": True,
                "password_min_length": 12, "token": None}
        self.assertEqual(redact_structure(data), data)

    def test_empty_strings_survive(self) -> None:
        """Saber que una opción está SIN configurar es diagnóstico, no secreto."""
        out = redact_structure({"auth_password": "", "api_token": ""})
        self.assertEqual(out["auth_password"], "")
        self.assertEqual(out["api_token"], "")

    def test_nested_and_lists(self) -> None:
        data = {
            "addons": [
                {"slug": "a", "options": {"password": "p1"}},
                {"slug": "b", "options": {"nested": {"api_key": "k2"}}},
            ],
            "tokens": ["t1", "t2"],
        }
        out = redact_structure(data)
        self.assertEqual(out["addons"][0]["options"]["password"], "***REDACTED***")
        self.assertEqual(out["addons"][1]["options"]["nested"]["api_key"], "***REDACTED***")
        self.assertEqual(out["tokens"], ["***REDACTED***", "***REDACTED***"])
        self.assertEqual(out["addons"][0]["slug"], "a")

    def test_input_is_not_mutated(self) -> None:
        """La redacción devuelve una copia: el dato original sigue usable."""
        original = {"options": {"password": "secreto"}}
        redact_structure(original)
        self.assertEqual(original["options"]["password"], "secreto")

    def test_survives_odd_shapes(self) -> None:
        for value in (None, 42, "texto", [], {}, [1, "dos", None]):
            redact_structure(value)  # no debe lanzar


class TestToolsApplyRedaction(unittest.TestCase):
    """Los sitios que devolvían la respuesta cruda del Supervisor."""

    @staticmethod
    def _src(rel: str) -> str:
        import pathlib
        return (pathlib.Path(__file__).resolve().parents[1] / rel).read_text(
            encoding="utf-8"
        )

    def test_addon_info_is_redacted(self) -> None:
        src = self._src("hermes/src/hermes/tools/addons.py")
        idx = src.index('f"/addons/{slug}/info"')
        # La redacción debe aplicarse en las líneas siguientes al fetch.
        self.assertIn("redact_structure", src[idx:idx + 400])

    def test_addon_options_is_redacted(self) -> None:
        """Las tools que DEVUELVEN datos de un add-on redactan sus secretos.

        Se comprueba por tool y no por posición del endpoint. Antes se miraba
        solo la primera aparición de `/options/config`; al moverse esa primera
        aparición, el test pasó a vigilar otra tool sin que nada lo delatara.

        `/addons/{slug}/info` se llama en más sitios (start, stop, update…),
        pero allí solo se extrae `state` para la vista previa: no sale ningún
        secreto, así que no entran en esta comprobación.
        """
        src = self._src("hermes/src/hermes/tools/addons.py")
        for tool in ("sv_get_addon", "sv_get_addon_options", "sv_set_addon_options"):
            inicio = src.index(f"async def {tool}(")
            resto = src[inicio + 1:]
            siguiente = resto.find("    @mcp.tool()")
            cuerpo = resto[:siguiente] if siguiente != -1 else resto
            self.assertIn(
                "redact_structure", cuerpo,
                f"{tool} devuelve datos del add-on sin redactar",
            )

    def test_system_info_tools_are_redacted(self) -> None:
        src = self._src("hermes/src/hermes/tools/supervisor.py")
        for endpoint in ("/supervisor/info", "/host/info", "/core/info"):
            idx = src.index(f'"{endpoint}"')
            window = src[max(0, idx - 200):idx + 100]
            self.assertIn("redact_structure", window, f"{endpoint} sin redactar")


if __name__ == "__main__":
    unittest.main()
