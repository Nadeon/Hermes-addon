"""Las limpiezas de las respuestas, JUNTAS (integración de la 025).

Al integrar la 025 en la rama del programa coinciden en el mismo camino cinco
limpiezas que nacieron por separado:

- 023: `_RE_TTS_PROXY` tapa el token del audio en `/api/tts_proxy/…` y en
  `media-source://tts/-stream-/…` en cualquier respuesta de las genéricas;
- 024: el VALOR de cada `webhook_id` se tapa en toda la respuesta
  (`valores_de_credencial` + `tapar_valores`), y `media_source` tapa la
  miniatura (`thumbnail`, firmada con `authSig`) por `redact_extra`;
- 025: bajo una clave sensible se tapa el valor ENTERO (`tapar_entero`), las
  claves S0/S2 de Z-Wave son marcadores, `redact_extra` admite `padre.hija`
  y `alarm_master_code`, y `addons._valores_secretos` reconoce los objetos
  tapados enteros.

Cada una tiene sus centinelas en su propio fichero; aquí se ejercitan en UNA
respuesta para vigilar que el orden en que se aplican no anula ninguna: el
`webhook_id` se busca sobre el dato en bruto (antes de que `redact_secrets` o
`tapar_entero` cambien el texto que lo contiene), `tapar_entero` decide por la
clave antes de recorrer, y `_RE_TTS_PROXY` va sobre el texto ya pasado por
`redact_secrets`.

Formas reales (Core 2026.11.1): `zha/websocket_api.py` y `backup.as_dict()` de
zigpy (`network_key: {"key", "tx_counter", …}`), `zha/helpers.py`
(`zha_alarm_options.alarm_master_code`), `mqtt/debug_info.py`
(`messages[].payload` y `discovery_data.payload`), `onvif/event_manager.py`
(id `onvif` + `token_hex(6)`, registrado también como nombre),
`tts/__init__.py` (`ResultStream.url` y `media_source_id`),
`zwave_js/const.py` (`s0_legacy_key`, `s2_*_key`) y `media_source` (miniatura
con `authSig`).

Controles negativos comprobados (revertir un momento, ver en rojo, restaurar):
- `_redactar` sin `_RE_TTS_PROXY` → caen `test_una_respuesta_con_todo` y
  `test_por_la_generica_de_verdad` (el token del audio sale en claro);
- `_redactar_respuesta` sin `tapar_valores` → caen `test_una_respuesta_con_todo`
  y `test_por_la_generica_de_verdad` (el id de ONVIF sale en `name`);
- sin la rama de `tapar_entero` (en `_redactar` y en `_redact_por_clave`,
  dejando solo los textos) → caen `test_una_respuesta_con_todo`,
  `test_redact_structure_de_las_dedicadas` y `test_por_la_generica_de_verdad`
  (la clave de red sale dentro de `network_key.key`).
"""

from __future__ import annotations

import json
import unittest

from hermes import command_table as ct
from hermes.security import REDACTED_MARKER, redact_structure
from hermes.tools.addons import _valores_secretos
from hermes.tools.generic_commands import _extra, _redactar_respuesta
from tests.test_tools_generic_commands import _Base

# Centinelas: ninguno puede aparecer en la salida.
_CLAVE_RED = "2ccade80d5b8e4b8a4cf7cbe2b1f0a11"
_TCLK = "5a6967426565416c6c69616e63653039"
_HASHED_TCLK = "e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6"
_CODIGO_ALARMA = "98765"
_CODIGO_TECLADO = "code=4321"
_WEBHOOK = "onvif0a1b2c3d4e5f"
_TOKEN_AUDIO = "Cn7tInElA023xYzAbCdEfG.mp3"
_AUTHSIG = "authSig=eyJhbGciOiJIUzI1NiJ9.centinela"
_S2 = "0123456789ABCDEF0123456789ABCDEF"
_S0 = "FEDCBA9876543210FEDCBA9876543210"

_CENTINELAS = (_CLAVE_RED, _TCLK, _HASHED_TCLK, _CODIGO_ALARMA, _CODIGO_TECLADO,
               _WEBHOOK, "Cn7tInElA023", "centinela", _S2, _S0)


def _respuesta() -> dict:
    """Un documento con todas las formas a la vez."""
    return {
        # 025: objeto bajo clave sensible (marcador `network_key`) y claves
        # de la copia de ZHA por `redact_extra`.
        "backup": {
            "network_key": {"key": _CLAVE_RED, "tx_counter": 1234, "rx_counter": 0,
                            "seq": 0, "partner_ieee": "00:00:00:00:00:00:00:00"},
            "tc_link_key": {"key": _TCLK, "tx_counter": 9, "partner_ieee":
                            "00:11:22:33:44:55:66:77"},
            "key_table": [{"key": _TCLK, "partner_ieee": "00:11:22:33:44:55:66:88"}],
            "stack_specific": {"ezsp": {"hashed_tclk": _HASHED_TCLK}},
            "channel": 15,
        },
        # 025: `alarm_master_code` por `redact_extra`.
        "data": {"zha_alarm_options": {"alarm_master_code": _CODIGO_ALARMA,
                                       "alarm_failed_tries": 3,
                                       "alarm_arm_requires_code": False}},
        # 025: `padre.hija` — el payload recibido se tapa, el de descubrimiento no.
        "mqtt": {
            "messages": [{"topic": "zigbee2mqtt/teclado", "payload": _CODIGO_TECLADO,
                          "qos": 0, "retain": False}],
            "discovery_data": {"payload": {"name": "Teclado"}, "topic": "homeassistant/x"},
        },
        # 024: el id de ONVIF repetido como nombre y en una plantilla.
        "webhooks": [{"webhook_id": _WEBHOOK, "domain": "onvif", "name": _WEBHOOK,
                      "local_only": False}],
        "condicion": f"{{{{ trigger.webhook_id == '{_WEBHOOK}' }}}}",
        # 023: el token del audio en las dos formas.
        "tts_output": {"media_id": f"media-source://tts/-stream-/{_TOKEN_AUDIO}",
                       "nota": f"oye /api/tts_proxy/{_TOKEN_AUDIO} ya",
                       "mime_type": "audio/mpeg"},
        # 024: la miniatura firmada.
        "children": [{"title": "foto", "thumbnail": f"/api/media_proxy/x?{_AUTHSIG}",
                      "media_class": "image"}],
        # 025: claves S0/S2 de Z-Wave (marcadores nuevos).
        "zwave": {"s2_access_control_key": _S2, "s0_legacy_key": _S0,
                  "lr_s2_authenticated_key": _S2, "device": "/dev/ttyUSB0"},
    }


def _extras_reales() -> frozenset[str]:
    """La unión de los `redact_extra` REALES de la tabla que intervienen."""
    comandos = ("zha/network/backups/list", "zha/configuration",
                "mqtt/device/debug_info", "media_source/browse_media",
                "assist_pipeline/pipeline_debug/get")
    out: frozenset[str] = frozenset()
    for c in comandos:
        out |= _extra(ct.CORE_WS[c])
    return out


class TestLimpiezasJuntas(unittest.TestCase):
    def test_una_respuesta_con_todo(self) -> None:
        r = _redactar_respuesta(_respuesta(), _extras_reales())
        texto = json.dumps(r, ensure_ascii=False)
        for c in _CENTINELAS:
            with self.subTest(centinela=c):
                self.assertNotIn(c, texto)
        # Lo que no es secreto se sigue viendo, y cada limpieza deja su forma.
        self.assertEqual(r["backup"]["network_key"], REDACTED_MARKER)
        self.assertEqual(r["backup"]["channel"], 15)
        self.assertEqual(r["data"]["zha_alarm_options"]["alarm_failed_tries"], 3)
        self.assertEqual(r["mqtt"]["messages"][0]["topic"], "zigbee2mqtt/teclado")
        self.assertEqual(r["mqtt"]["messages"][0]["payload"], REDACTED_MARKER)
        self.assertEqual(r["mqtt"]["discovery_data"]["payload"], {"name": "Teclado"})
        self.assertEqual(r["webhooks"][0]["domain"], "onvif")
        self.assertEqual(r["webhooks"][0]["name"], REDACTED_MARKER)
        self.assertIn("trigger.webhook_id ==", r["condicion"])
        self.assertEqual(r["tts_output"]["media_id"],
                         f"media-source://tts/-stream-/{REDACTED_MARKER}")
        self.assertIn(f"/api/tts_proxy/{REDACTED_MARKER}", r["tts_output"]["nota"])
        self.assertEqual(r["tts_output"]["mime_type"], "audio/mpeg")
        self.assertEqual(r["children"][0]["thumbnail"], REDACTED_MARKER)
        self.assertEqual(r["children"][0]["title"], "foto")
        self.assertEqual(r["zwave"]["device"], "/dev/ttyUSB0")

    def test_redact_structure_de_las_dedicadas(self) -> None:
        """Las dedicadas usan `redact_structure`: `tapar_entero`, los
        marcadores S0/S2 y el valor del `webhook_id` en toda la respuesta."""
        doc = _respuesta()
        r = redact_structure(doc)
        texto = json.dumps(r, ensure_ascii=False)
        for c in (_CLAVE_RED, _WEBHOOK, _S2, _S0):
            with self.subTest(centinela=c):
                self.assertNotIn(c, texto)
        self.assertEqual(r["backup"]["network_key"], REDACTED_MARKER)
        self.assertEqual(r["zwave"]["s2_access_control_key"], REDACTED_MARKER)
        self.assertEqual(r["webhooks"][0]["name"], REDACTED_MARKER)
        self.assertEqual(r["backup"]["channel"], 15)

    def test_valores_secretos_de_las_opciones_de_una_app(self) -> None:
        """`addons._valores_secretos` (arreglo de la 025) sobre lo que deja
        `redact_structure` ya con la limpieza del `webhook_id` de la 024: los
        valores del objeto tapado entero y los S2 cuentan como secretos."""
        opciones = {"network_key": {"key": _CLAVE_RED, "tx_counter": 7},
                    "s2_authenticated_key": _S2, "webhook_id": _WEBHOOK,
                    "device": "/dev/ttyUSB0"}
        secretos = _valores_secretos(opciones, redact_structure(opciones))
        for c in (_CLAVE_RED, "7", _S2, _WEBHOOK):
            with self.subTest(secreto=c):
                self.assertIn(c, secretos)
        self.assertNotIn("/dev/ttyUSB0", secretos)


class TestPorLaGenericaDeVerdad(_Base):
    """La misma mezcla por `ha_read_ws_command` con la tabla real: solo
    `mqtt/device/debug_info` aporta su `redact_extra`; todo lo transversal
    (023, 024 y 025) se aplica igual."""

    inyectadas = False

    async def test_por_la_generica_de_verdad(self) -> None:
        doc = _respuesta()
        self.ha.ws_send.return_value = doc
        r = await self.t["ha_read_ws_command"](
            "mqtt/device/debug_info", {"device_id": "0123456789abcdef"})
        self.assertNotIn("error", r)
        texto = json.dumps(r, ensure_ascii=False)
        # Transversales: sin `redact_extra` de por medio.
        for c in (_CLAVE_RED, _WEBHOOK, "Cn7tInElA023", _S2, _S0, _CODIGO_TECLADO):
            with self.subTest(centinela=c):
                self.assertNotIn(c, texto)
        res = r["result"]
        self.assertEqual(res["mqtt"]["discovery_data"]["payload"], {"name": "Teclado"})
        self.assertEqual(res["webhooks"][0]["domain"], "onvif")


if __name__ == "__main__":
    unittest.main()
