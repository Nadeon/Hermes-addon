"""La clase C por las genéricas de Core (spec 025; FR-001, FR-008, FR-009).

Dos partes:
- `TestRedaccionValorEntero` (FR-008): una clave de `redact_extra` tapa su
  valor ENTERO, sea del tipo que sea, con una tabla inyectada. Desde la D-2
  del supervisor, lo mismo vale para las claves sensibles por nombre
  (`redact_structure`, hallazgo H-1).
- `TestZwave` (FR-001, FR-009): entradas reales de la tabla `zwave_js/*`
  con `ws_send` y `ws_one_shot_subscription` simulados.

Datos ficticios (`<device_id>`, `<entry_id>`, centinelas `…025…`). La forma
de las respuestas es la de los handlers de HA Core 2026.11.1
(`homeassistant/components/zwave_js/api.py`).

Controles negativos comprobados:
- quitar en `_redactar` el tapado entero de objetos y listas → caen
  `test_objeto_entero` y `test_lista_entera` (el resto sigue en verde).
- pasar `zwave_js/hard_reset_controller` a `confirm` → cae
  `test_rechazos_sin_llamar_a_ha` (y la clasificación de la tabla).
- quitar `redact_extra` de `zwave_js/get_provisioning_entries` → cae
  `test_provisioning_tapa_el_dsk`.
- quitar `one_shot` de `zwave_js/subscribe_node_statistics` → cae
  `test_estadisticas_un_solo_mensaje`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from structlog.testing import capture_logs

from hermes.command_policy import Entrada
from tests.test_tools_generic_commands import _Base

_CENTINELA = "centinela-025-C0FFEE"


def _e(category: str, **kw: Any) -> Entrada:
    kw.setdefault("reason", f"motivo {category}")
    kw.setdefault("family", "generic_commands")
    return Entrada(category=category, **kw)


class _Inyectada(_Base):
    """La tabla de `_Base` más una entrada con `redact_extra=("k",)`."""

    async def asyncSetUp(self) -> None:
        from tests import test_tools_generic_commands as base

        self._core_original = dict(base._CORE)
        base._CORE["demo/claves"] = _e("read", redact_extra=("k",))
        await super().asyncSetUp()

    async def asyncTearDown(self) -> None:
        from tests import test_tools_generic_commands as base

        base._CORE.clear()
        base._CORE.update(self._core_original)
        await super().asyncTearDown()

    async def leer(self, respuesta: Any) -> dict[str, Any]:
        self.ha.ws_send.return_value = respuesta
        return await self.t["ha_read_ws_command"]("demo/claves", {})


class TestRedaccionValorEntero(_Inyectada):
    async def test_objeto_entero(self) -> None:
        r = await self.leer({"k": {"key": _CENTINELA, "n": 1}, "otro": 2})
        self.assertEqual(r["result"], {"k": "***REDACTED***", "otro": 2})
        self.assertNotIn(_CENTINELA, json.dumps(r))

    async def test_lista_entera(self) -> None:
        r = await self.leer({"k": [{"key": _CENTINELA}, "x"]})
        self.assertEqual(r["result"], {"k": "***REDACTED***"})

    async def test_texto_y_numero_como_hoy(self) -> None:
        r = await self.leer({"k": _CENTINELA})
        self.assertEqual(r["result"], {"k": "***REDACTED***"})
        r = await self.leer({"k": 1234})
        self.assertEqual(r["result"], {"k": "***REDACTED***"})

    async def test_vacio_y_none_tal_cual(self) -> None:
        r = await self.leer({"k": ""})
        self.assertEqual(r["result"], {"k": ""})
        r = await self.leer({"k": None})
        self.assertEqual(r["result"], {"k": None})

    async def test_clave_no_extra_se_recorre(self) -> None:
        r = await self.leer({"otra": {"key": "visible", "password": _CENTINELA}})
        self.assertEqual(r["result"], {"otra": {"key": "visible",
                                                "password": "***REDACTED***"}})

    async def test_clave_sensible_por_nombre_tambien_entera(self) -> None:
        """D-2: la genérica sigue el mismo criterio que `redact_structure`."""
        r = await self.leer({"network_key": {"key": _CENTINELA, "seq": 0}})
        self.assertEqual(r["result"], {"network_key": "***REDACTED***"})

    async def test_logbook_sigue_igual(self) -> None:
        """La única entrada previa con `redact_extra` recibe escalares: no
        cambia (el test de la 011, `test_action_calls_tapa_el_code`, la
        prueba con la tabla real)."""
        from hermes import command_table as ct

        self.assertEqual(ct.CORE_WS["logbook/get_action_calls"].redact_extra, ("code",))


class TestZwave(_Base):
    inyectadas = False

    async def test_network_status_por_la_de_lectura(self) -> None:
        self.ha.ws_send.return_value = {"client": {"connected": True}, "controller": {}}
        r = await self.t["ha_read_ws_command"](
            "zwave_js/network_status", {"entry_id": "<entry_id>"})
        self.ha.ws_send.assert_awaited_once_with(
            {"type": "zwave_js/network_status", "entry_id": "<entry_id>"})
        self.assertEqual(r["category"], "read")
        self.assertEqual(r["result"]["client"], {"connected": True})

    async def test_get_config_parameters(self) -> None:
        self.ha.ws_send.return_value = {"2-112-0-3": {"property": 3, "value": 1}}
        await self.t["ha_read_ws_command"](
            "zwave_js/get_config_parameters", {"device_id": "<device_id>"})
        self.ha.ws_send.assert_awaited_once_with(
            {"type": "zwave_js/get_config_parameters", "device_id": "<device_id>"})

    async def test_estadisticas_un_solo_mensaje(self) -> None:
        for comando, carga in (
            ("zwave_js/subscribe_controller_statistics", {"entry_id": "<entry_id>"}),
            ("zwave_js/subscribe_node_statistics", {"device_id": "<device_id>"}),
        ):
            with self.subTest(comando=comando):
                self.ha.ws_one_shot_subscription.reset_mock()
                self.ha.ws_one_shot_subscription.return_value = {
                    "event": "statistics updated", "source": "node", "rtt": 30}
                r = await self.t["ha_read_ws_command"](comando, carga)
                self.ha.ws_one_shot_subscription.assert_awaited_once()
                self.assertEqual(self.ha.ws_one_shot_subscription.await_args.args[0],
                                 {"type": comando, **carga})
                self.assertEqual(r["result"]["rtt"], 30)
        self.ha.ws_send.assert_not_awaited()

    async def test_set_config_parameter_en_dos_pasos(self) -> None:
        carga = {"device_id": "<device_id>", "property": 3, "value": 1}
        vista = await self.t["ha_call_ws_command"]("zwave_js/set_config_parameter", carga)
        self.assertIn("preview", vista)
        self.assertIn("confirmation_token", vista)
        self.ha.ws_send.assert_not_awaited()
        self.ha.ws_send.return_value = {"status": "accepted"}
        r = await self.t["ha_call_ws_command"](
            "zwave_js/set_config_parameter", carga,
            confirmation_token=vista["confirmation_token"])
        self.ha.ws_send.assert_awaited_once_with(
            {"type": "zwave_js/set_config_parameter", **carga})
        self.assertTrue(r["executed"])

    async def test_network_neighbors_por_la_de_escritura(self) -> None:
        """Solo lee, pero apaga la radio mientras dura: `confirm` (R-1)."""
        r = await self.t["ha_read_ws_command"](
            "zwave_js/network_neighbors", {"entry_id": "<entry_id>"})
        self.assertEqual((r["error"], r["use_tool"]),
                         ("wrong_generic_tool", "ha_call_ws_command"))
        vista = await self.t["ha_call_ws_command"](
            "zwave_js/network_neighbors", {"entry_id": "<entry_id>"})
        self.assertIn("radio", vista["preview"]["reason"].lower())
        self.ha.ws_send.assert_not_awaited()

    async def test_rechazos_sin_llamar_a_ha(self) -> None:
        for comando in (
            "zwave_js/hard_reset_controller", "zwave_js/add_node",
            "zwave_js/validate_dsk_and_enter_pin", "zwave_js/invoke_cc_api",
            "zwave_js/parse_qr_code_string", "zwave_js/refresh_node_info",
            "zwave_js/restore_nvm", "zwave_js/subscribe_log_updates",
        ):
            for tool in ("ha_read_ws_command", "ha_call_ws_command"):
                with self.subTest(comando=comando, tool=tool):
                    r = await self.t[tool](comando, {"entry_id": "<entry_id>"})
                    self.assertEqual(r["error"], "command_denied")
                    self.assertTrue(r["reason"])
        self.ha.ws_send.assert_not_awaited()
        self.ha.ws_one_shot_subscription.assert_not_awaited()
        self.assertEqual(list(Path(self.temp_dir.name).glob("*")), [])

    async def test_provisioning_tapa_el_dsk(self) -> None:
        # Forma de `ProvisioningEntry.to_dict()`: las claves que valida
        # `PLANNED_PROVISIONING_ENTRY_SCHEMA` de zwave_js/api.py (`dsk`,
        # `securityClasses`, `status`, `requestedSecurityClasses`). El DSK son
        # ocho grupos de cinco dígitos; los cinco primeros son el PIN de S2.
        dsk = "20251-02500-12345-54321-11111-22222-33333-44444"
        self.ha.ws_send.return_value = [{
            "dsk": dsk, "securityClasses": [0, 1], "status": 0,
            "requestedSecurityClasses": [0, 1], "protocol": 0,
        }]
        with capture_logs() as logs:
            r = await self.t["ha_read_ws_command"](
                "zwave_js/get_provisioning_entries", {"entry_id": "<entry_id>"})
        self.assertEqual(r["items"][0]["dsk"], "***REDACTED***")
        self.assertEqual(r["items"][0]["securityClasses"], [0, 1])
        for trozo in (dsk, "20251"):
            self.assertNotIn(trozo, json.dumps(r))
            self.assertNotIn(trozo, json.dumps(logs, default=str))
