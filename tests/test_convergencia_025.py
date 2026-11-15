"""Convergencia de la 025 (T047-T049): los hallazgos de la revisión
independiente, cada uno con su escenario reproducido.

- `TestMarcadorEnLasGenericas` (T047, ALTO-1): `ha_call_ws_command` y
  `sv_call_api` rechazan, sin token y sin llamar a nada, una carga con el
  marcador de redacción. Escenario real de la revisión: leer
  `zha/configuration` (el código maestro sale tapado), cambiar otra opción y
  reenviar `data` entero a `zha/configuration/update`, cuyo handler
  (`websocket_update_zha_configuration`) REEMPLAZA la configuración propia
  con `msg["data"]`: se guardaba `***REDACTED***` como código de la alarma.
  En el Supervisor, `POST /docker/registries` (`create_registry`) sobrescribe
  el registro de ese servidor con el cuerpo, contraseña incluida.
- `TestSecretosAnidadosEnLosErrores` (T048, MEDIO-1): `_valores_secretos`
  vuelve a reconocer los valores de un objeto o una lista que `tapar_entero`
  tapa enteros, y el mensaje del Supervisor que nombra uno sale genérico.
- `TestMqttMensajesRecibidos` (T049, MEDIO-2): el `payload` de cada mensaje
  recibido de `mqtt/device/debug_info` sale tapado entero; topic, fecha, QoS
  y `retain` se conservan, y el `payload` de descubrimiento sigue visible.

Formas reales: `zha/websocket_api.py` (`websocket_get_configuration`:
`schemas` y `data` por sección), `supervisor/api/docker.py`
(`SCHEMA_DOCKER_REGISTRY`: `{servidor: {username, password}}`) y
`mqtt/debug_info.py` (`_info_for_entity`: `payload` es `str(msg.payload)`).

Controles negativos comprobados (revertir un momento, ver en rojo, restaurar):
- quitar la comprobación de `rutas_con_marcador` en `ha_call_ws_command` →
  caen `test_zha_configuration_leida_y_reenviada` y
  `test_marcador_en_clave_y_dentro_de_un_texto` (HA recibe el marcador); en
  `sv_call_api` → cae `test_sv_call_api_registro_docker`.
- quitar la rama nueva de `_valores_secretos` (marcador frente a objeto o
  lista) → caen los dos tests de `TestSecretosAnidadosEnLosErrores`.
- quitar `messages.payload` de `redact_extra` de `mqtt/device/debug_info` →
  cae `test_payload_recibido_tapado` (el código del teclado sale en claro).
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from structlog.testing import capture_logs

from hermes.security import REDACTED_MARKER
from hermes.tools.addons import _sin_valores_secretos, _valores_secretos, register
from hermes.security import redact_structure
from tests.fixtures.supervisor_tienda import SupervisorSimulado
from tests.test_tools_generic_commands import _Base

_CODIGO = "98765"


class _TablaReal(_Base):
    inyectadas = False


class TestMarcadorEnLasGenericas(_TablaReal):
    async def test_zha_configuration_leida_y_reenviada(self) -> None:
        self.ha.ws_send.return_value = {
            "schemas": {"zha_alarm_options": [
                {"name": "alarm_master_code", "default": "1234", "type": "string",
                 "required": True},
                {"name": "alarm_failed_tries", "default": 3, "type": "integer",
                 "required": True},
                {"name": "alarm_arm_requires_code", "default": False,
                 "type": "boolean", "required": True}]},
            "data": {"zha_alarm_options": {"alarm_master_code": _CODIGO,
                                           "alarm_failed_tries": 3,
                                           "alarm_arm_requires_code": False}},
        }
        leido = await self.t["ha_read_ws_command"]("zha/configuration")
        datos = leido["result"]["data"]
        self.assertEqual(datos["zha_alarm_options"]["alarm_master_code"], REDACTED_MARKER)
        datos["zha_alarm_options"]["alarm_failed_tries"] = 5  # lo que quiere el usuario
        self.ha.ws_send.reset_mock()

        with capture_logs() as logs:
            vista = await self.t["ha_call_ws_command"](
                "zha/configuration/update", {"data": datos})
        self.assertEqual(vista["error"], "redacted_value_in_payload")
        self.assertEqual(vista["paths"], ["data.zha_alarm_options.alarm_master_code"])
        self.assertIn("real value", vista["detail"])
        self.assertIn("remove that field", vista["detail"])
        self.assertNotIn("confirmation_token", vista)
        # Tampoco con un token en la mano: se rechaza antes de mirarlo.
        r = await self.t["ha_call_ws_command"](
            "zha/configuration/update", {"data": datos}, confirmation_token="cualquiera")
        self.assertEqual(r["error"], "redacted_value_in_payload")
        self.ha.ws_send.assert_not_awaited()
        self.assertIn("rejected:redacted_value_in_payload",
                      [e.get("outcome") for e in logs])

        # Con el código real (o sin la clave) sí se puede.
        datos["zha_alarm_options"]["alarm_master_code"] = _CODIGO
        vista = await self.t["ha_call_ws_command"]("zha/configuration/update", {"data": datos})
        self.assertIn("confirmation_token", vista)
        self.assertNotIn(_CODIGO, json.dumps(vista))

    async def test_marcador_en_clave_y_dentro_de_un_texto(self) -> None:
        casos = {
            "texto": ({"data": {"zha_options": {"x": f"pre{REDACTED_MARKER}post"}}},
                      ["data.zha_options.x"]),
            "clave": ({"data": {REDACTED_MARKER: 1}}, [f"data.{REDACTED_MARKER}"]),
            "lista": ({"data": {"l": ["ok", REDACTED_MARKER]}}, ["data.l[1]"]),
        }
        for nombre, (carga, rutas) in casos.items():
            with self.subTest(nombre):
                r = await self.t["ha_call_ws_command"]("zha/configuration/update", carga)
                self.assertEqual((r["error"], r["paths"]),
                                 ("redacted_value_in_payload", rutas))
        self.ha.ws_send.assert_not_awaited()

    async def test_sv_call_api_registro_docker(self) -> None:
        cuerpo = {"registry.example": {"username": "usuario",
                                       "password": REDACTED_MARKER}}
        for token in (None, "cualquiera"):
            with self.subTest(token=token):
                r = await self.t["sv_call_api"]("POST", "/docker/registries", cuerpo,
                                                confirmation_token=token)
                self.assertEqual(r["error"], "redacted_value_in_payload")
                self.assertEqual(r["paths"], ["registry.example.password"])
        self.ha.sv_request.assert_not_awaited()
        # Con la contraseña real, la vista previa de siempre (y sin ella).
        cuerpo["registry.example"]["password"] = "contraseña-real-025"
        vista = await self.t["sv_call_api"]("POST", "/docker/registries", cuerpo)
        self.assertIn("confirmation_token", vista)
        self.assertNotIn("contraseña-real-025", json.dumps(vista, ensure_ascii=False))


class _MCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


class TestSecretosAnidadosEnLosErrores(unittest.IsolatedAsyncioTestCase):
    _SLUG = "abcd1234_ejemplo"

    def test_objeto_y_lista_bajo_clave_sensible(self) -> None:
        # El escenario de la revisión: un secreto corto (< 4, el paso 2 no lo
        # sustituye) dentro de un objeto o una lista bajo una clave sensible.
        mensaje = "Option 'credentials' invalid for app x: abc"
        for opciones in ({"credentials": {"username": "u", "password": "abc"}},
                         {"passwords": ["abc", "xyz"]}):
            with self.subTest(opciones=opciones):
                self.assertIn("abc", _valores_secretos(opciones, redact_structure(opciones)))
                out = _sin_valores_secretos(mensaje, opciones)
                self.assertNotIn("abc", out)
                self.assertIn("could reveal a secret value", out)

    async def test_por_la_tool_al_validar(self) -> None:
        sv = SupervisorSimulado()
        mcp = _MCP()
        register(mcp, sv)
        actuales = {"credentials": {"username": "u", "password": "abc"}, "port": 8080}
        sv.respuesta("GET", f"/addons/{self._SLUG}/info", {"options": actuales})
        sv.respuesta("POST", f"/addons/{self._SLUG}/options/validate",
                     {"valid": False, "pwned": False,
                      "message": "Option 'credentials' invalid for app x: abc"})
        r = await mcp.tools["sv_set_addon_options"](self._SLUG, json.dumps({"port": "x"}))
        self.assertEqual(r.get("error"), "invalid_options", r)
        self.assertNotIn("abc", json.dumps(r))


class TestMqttMensajesRecibidos(_TablaReal):
    async def test_payload_recibido_tapado(self) -> None:
        # `_info_for_entity`: un teclado que publica en su topic de estado lo
        # que se ha tecleado. El `payload` es `str(msg.payload)`, texto libre.
        recibido = '{"action": "disarm", "action_code": "4321"}'
        self.ha.ws_send.return_value = {
            "entities": [{
                "entity_id": "alarm_control_panel.ficticia",
                "subscriptions": [{"topic": "casa/teclado/estado", "messages": [{
                    "payload": recibido, "qos": 1, "retain": False,
                    "time": "2026-11-15T00:00:00+00:00",
                    "topic": "casa/teclado/estado"}]}],
                "discovery_data": {
                    "topic": "homeassistant/alarm_control_panel/ficticia/config",
                    "payload": {"name": "ficticia", "state_topic": "casa/teclado/estado",
                                "code": "4321"}},
                "transmitted": [],
            }],
            "triggers": [{"discovery_data": {"topic": "homeassistant/device_automation/x/config",
                                             "payload": {"topic": "casa/boton"}},
                          "trigger_key": ["device_automation", "x"]}],
        }
        with capture_logs() as logs:
            r = await self.t["ha_read_ws_command"](
                "mqtt/device/debug_info", {"device_id": "<device_id>"})
        entidad = r["result"]["entities"][0]
        mensaje = entidad["subscriptions"][0]["messages"][0]
        self.assertEqual(mensaje, {"payload": REDACTED_MARKER, "qos": 1, "retain": False,
                                   "time": "2026-11-15T00:00:00+00:00",
                                   "topic": "casa/teclado/estado"})
        self.assertEqual(entidad["subscriptions"][0]["topic"], "casa/teclado/estado")
        # El descubrimiento (también bajo `payload`, pero fuera de
        # `messages`) sigue visible, con su `code` tapado.
        self.assertEqual(entidad["discovery_data"]["payload"]["state_topic"],
                         "casa/teclado/estado")
        self.assertEqual(entidad["discovery_data"]["payload"]["code"], REDACTED_MARKER)
        self.assertEqual(r["result"]["triggers"][0]["discovery_data"]["payload"],
                         {"topic": "casa/boton"})
        self.assertNotIn("4321", json.dumps(r))
        self.assertNotIn("4321", json.dumps(logs, default=str))
