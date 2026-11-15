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

    def test_booleanos_y_none_se_conservan(self) -> None:
        """Un booleano o `None` bajo una clave sensible no lleva secreto: dice
        si algo está activado o configurado, que es diagnóstico útil.

        Hasta la 025 también se conservaban los números (`token_expiry_seconds`).
        Desde la 025 (D-2, hallazgo H-1) un número bajo una clave sensible se
        tapa: un PIN o una clave numérica no se distinguen de una duración por
        el tipo, y el criterio es «la clave es sensible → el valor entero»."""
        data = {"use_password": True, "token": None, "has_secret": False}
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
        # Desde la 025 la lista entera bajo una clave sensible es un solo
        # marcador: ni siquiera cuántos secretos hay (antes, uno por elemento).
        self.assertEqual(out["tokens"], "***REDACTED***")
        self.assertEqual(out["addons"][0]["slug"], "a")

    def test_input_is_not_mutated(self) -> None:
        """La redacción devuelve una copia: el dato original sigue usable."""
        original = {"options": {"password": "secreto"}}
        redact_structure(original)
        self.assertEqual(original["options"]["password"], "secreto")

    def test_survives_odd_shapes(self) -> None:
        for value in (None, 42, "texto", [], {}, [1, "dos", None]):
            redact_structure(value)  # no debe lanzar


# Forma REAL de la copia de la red de ZHA (`backup.as_dict()` de zigpy, que
# devuelven `zha/network/settings` y `zha/network/backups/*` en
# `homeassistant/components/zha/websocket_api.py`): `network_key` NO es un
# texto sino un objeto con la clave (`KeyData`, 16 bytes en hexadecimal con dos
# puntos) y sus contadores; `partner_ieee` va DENTRO (por eso
# `zha/diagnostics.py` lista a la vez `network_key` y `partner_ieee` en
# `KEYS_TO_REDACT`, y su `async_redact_data` tapa el valor entero).
_CLAVE_ZHA = "c0:ff:ee:02:50:25:de:ad:be:ef:00:11:22:33:44:55"
_RED_ZHA = {
    "network_info": {
        "extended_pan_id": "00:11:22:33:44:55:66:77",
        "pan_id": "1A2B",
        "channel": 15,
        "security_level": 5,
        "network_key": {
            "key": _CLAVE_ZHA,
            "tx_counter": 202501,
            "rx_counter": 0,
            "seq": 0,
            "partner_ieee": "ff:ff:ff:ff:ff:ff:ff:ff",
        },
    },
}

# Forma REAL de las claves S0/S2 de Z-Wave JS: opciones de la app Z-Wave JS
# que escribe la integración (`homeassistant/components/zwave_js/const.py`,
# `CONF_ADDON_S0_LEGACY_KEY`… y `__init__.py`, `addon_config`), 16 bytes en
# 32 caracteres hexadecimales. `sv_get_addon_options` las devuelve tal cual.
# Ninguna se llama `password` ni `network_key`: hasta la 025 salían en claro.
_OPCIONES_ZWAVE = {
    "device": "/dev/serial/by-id/usb-ficticio-if00",
    "s0_legacy_key": "0025C0FFEE0000000000000000000A00",
    "s2_access_control_key": "0025C0FFEE0000000000000000000A01",
    "s2_authenticated_key": "0025C0FFEE0000000000000000000A02",
    "s2_unauthenticated_key": "0025C0FFEE0000000000000000000A03",
    "lr_s2_access_control_key": "0025C0FFEE0000000000000000000A04",
    "lr_s2_authenticated_key": "0025C0FFEE0000000000000000000A05",
    "network_key": "0025C0FFEE0000000000000000000A06",
    "log_level": "info",
}


class TestValorEnteroBajoClaveSensible(unittest.TestCase):
    """Spec 025, D-2 (hallazgo H-1): si la clave es sensible, se tapa su
    valor ENTERO, sea texto, número, objeto o lista. Antes solo se tapaban
    textos: un objeto se recorría y lo que llevaba dentro bajo una clave
    inocente (`key`) salía en claro.

    Control negativo comprobado: volver a tapar solo textos en
    `redact_structure` → caen `test_clave_de_red_zha_con_su_forma_real`,
    `test_objeto_y_lista_enteros` y `test_numero`; quitar los marcadores
    S0/S2 de `_SENSITIVE_KEY_MARKERS` → cae `test_claves_s0_s2_de_zwave`.
    """

    def test_clave_de_red_zha_con_su_forma_real(self) -> None:
        out = redact_structure(_RED_ZHA)
        self.assertNotIn(_CLAVE_ZHA, str(out))
        self.assertNotIn("202501", str(out))
        self.assertEqual(out["network_info"]["network_key"], "***REDACTED***")
        # Lo que no es secreto sigue visible.
        self.assertEqual(out["network_info"]["channel"], 15)
        self.assertEqual(out["network_info"]["pan_id"], "1A2B")

    def test_claves_s0_s2_de_zwave(self) -> None:
        out = redact_structure({"options": _OPCIONES_ZWAVE})["options"]
        self.assertNotIn("0025C0FFEE", str(out))
        for clave in _OPCIONES_ZWAVE:
            if clave.endswith("_key"):
                self.assertEqual(out[clave], "***REDACTED***", clave)
        self.assertEqual(out["device"], _OPCIONES_ZWAVE["device"])
        self.assertEqual(out["log_level"], "info")

    def test_objeto_y_lista_enteros(self) -> None:
        data = {"credentials": {"username": "u", "pin": "centinela-025"},
                "api_tokens": [{"name": "n", "value": "centinela-025"}]}
        out = redact_structure(data)
        self.assertEqual(out, {"credentials": "***REDACTED***",
                               "api_tokens": "***REDACTED***"})

    def test_numero(self) -> None:
        out = redact_structure({"encryption_key": 202512345, "pin_secret": 1.5})
        self.assertEqual(out, {"encryption_key": "***REDACTED***",
                               "pin_secret": "***REDACTED***"})

    def test_vacios_se_conservan(self) -> None:
        """Como la cadena vacía: un objeto o una lista vacíos dicen «sin
        configurar» y no revelan nada."""
        data = {"network_key": {}, "api_tokens": [], "password": "", "token": None}
        self.assertEqual(redact_structure(data), data)

    def test_clave_no_sensible_se_sigue_recorriendo(self) -> None:
        data = {"options": {"nested": [{"password": "p", "host": "h"}]}}
        out = redact_structure(data)
        self.assertEqual(out["options"]["nested"][0],
                         {"password": "***REDACTED***", "host": "h"})


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


class TestValorDelWebhookIdEnTodaLaRespuesta(unittest.TestCase):
    """T032 de la 024: el valor de un `webhook_id` se tapa en cualquier campo,
    no solo bajo su clave. Forma real: el trigger de una traza de webhook
    (`components/webhook/trigger.py`: `{"platform": "webhook", "webhook_id":
    …, "description": "webhook"}`) y la `config` de la automatización, cuya
    plantilla puede comparar el id.

    Control negativo: sin `tapar_valores` en `redact_structure`, cae
    (comprobado).
    """

    _ID = "onvif0123456789ab"

    def test_repetido_en_otros_campos(self) -> None:
        traza = {
            "trigger": {"platform": "webhook", "webhook_id": self._ID,
                        "description": "webhook"},
            "config": {"triggers": [{"trigger": "webhook", "webhook_id": self._ID}],
                       "conditions": [{"condition": "template", "value_template":
                                       f"{{{{ trigger.webhook_id == '{self._ID}' }}}}"}],
                       "alias": self._ID},
            self._ID: {"name": self._ID},
        }
        out = redact_structure(traza)
        self.assertNotIn(self._ID, repr(out))
        self.assertEqual(out["config"]["alias"], "***REDACTED***")
        self.assertEqual(out["trigger"]["description"], "webhook")

    def test_id_corto_solo_entero(self) -> None:
        # Un id de menos de 4 caracteres no se busca como subcadena: taparía
        # media respuesta.
        out = redact_structure({"webhook_id": "ab", "name": "ab", "alias": "cabina"})
        self.assertEqual(out, {"webhook_id": "***REDACTED***",
                               "name": "***REDACTED***", "alias": "cabina"})


if __name__ == "__main__":
    unittest.main()
