"""La clase C por las genéricas de Core (spec 025; FR-001, FR-008, FR-009).

Partes:
- `TestRedaccionValorEntero` (FR-008): una clave de `redact_extra` tapa su
  valor ENTERO, sea del tipo que sea, con una tabla inyectada. Desde la D-2
  del supervisor, lo mismo vale para las claves sensibles por nombre
  (`redact_structure`, hallazgo H-1).
- `TestZwave` (FR-001, FR-009): entradas reales de la tabla `zwave_js/*`
  con `ws_send` y `ws_one_shot_subscription` simulados.
- `TestZha` y `TestMatterThread` (FR-002…FR-004, FR-009; tramo 2): una
  lectura, una escritura en dos pasos, los rechazos y los centinelas de las
  claves de red Zigbee y Thread y del código de la alarma de ZHA.
- `TestResto` (FR-005, FR-006, FR-009; tramo 3): MQTT, USB, Bluetooth y el
  resto, con los centinelas de la contraseña del hub Insteon y del código de
  alarma de MQTT.

Datos ficticios (`<device_id>`, `<entry_id>`, centinelas `…025…`). La forma
de las respuestas es la de los handlers de HA Core 2026.11.1
(`homeassistant/components/zwave_js/api.py`, `zha/websocket_api.py`,
`matter/api.py`, `thread/websocket_api.py` y `otbr/websocket_api.py`; las
del tramo 3, en el docstring de `TestResto`).

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



# ── Tramo 2: ZHA, Matter, Thread y OTBR (FR-002…FR-004, FR-009) ───────────────

# Forma REAL de `NetworkBackup.as_dict()` de zigpy, que devuelven
# `zha/network/settings` (bajo `settings`), `zha/network/backups/list` (una por
# copia) y `zha/network/backups/create` (bajo `backup`) en
# `homeassistant/components/zha/websocket_api.py`. Las claves (`KeyData`, 16
# bytes en hexadecimal con dos puntos) van DENTRO de objetos bajo
# `network_key`, `tc_link_key` y cada elemento de `key_table`; el material
# propio de la radio va en `stack_specific` (en EZSP, `hashed_tclk`). Lo mismo
# lee `zha/repairs/network_settings_inconsistent.py`
# (`network_info.tc_link_key.key`, `network_info.network_key.key`). Un
# centinela distinto en cada sitio: si uno se escapa, se sabe cuál.
_NK = "c0:ff:ee:02:50:25:00:00:00:00:00:00:00:00:00:01"
_TCLK = "c0:ff:ee:02:50:25:00:00:00:00:00:00:00:00:00:02"
_KT = "c0:ff:ee:02:50:25:00:00:00:00:00:00:00:00:00:03"
_HASHED = "c0ffee02502500000000000000000004"
_CENTINELAS_ZHA = (_NK, _TCLK, _KT, _HASHED, "c0:ff:ee:02:50:25", "c0ffee025025")


def _copia_zigpy() -> dict[str, Any]:
    def clave(k: str, contador: int) -> dict[str, Any]:
        return {"key": k, "tx_counter": contador, "rx_counter": 0, "seq": 0,
                "partner_ieee": "00:11:22:33:44:55:66:77"}

    return {
        "version": 1,
        "backup_time": "2026-11-15T00:00:00+00:00",
        "network_info": {
            "extended_pan_id": "00:11:22:33:44:55:66:99",
            "pan_id": "1A2B",
            "nwk_update_id": 0,
            "nwk_manager_id": "0000",
            "channel": 15,
            "channel_mask": [15],
            "security_level": 5,
            "network_key": clave(_NK, 202501),
            "tc_link_key": clave(_TCLK, 202502),
            "key_table": [clave(_KT, 202503)],
            "children": [],
            "nwk_addresses": {},
            "stack_specific": {"ezsp": {"hashed_tclk": _HASHED}},
            "metadata": {"ezsp": {"stack_version": 8}},
            "source": "bellows@0.0.0",
        },
        "node_info": {"nwk": "0x0000", "ieee": "00:11:22:33:44:55:66:00",
                      "logical_type": "coordinator"},
    }


class TestZha(_Base):
    """FR-002. Control negativo comprobado: quitar `stack_specific` de
    `redact_extra` de `zha/network/settings` → cae
    `test_network_settings_tapa_las_claves` (sale `hashed_tclk`); volver
    `_redactar` a recorrer los objetos bajo `redact_extra` → caen los tres
    centinelas de la red (`tc_link_key.key` y `key_table[0].key` en claro);
    quitar `redact_extra` de `zha/configuration` → cae
    `test_configuration_tapa_el_codigo_de_la_alarma`."""

    inyectadas = False

    async def test_devices_por_la_de_lectura(self) -> None:
        self.ha.ws_send.return_value = [{"ieee": "00:11:22:33:44:55:66:77",
                                         "name": "ficticio", "lqi": 200}]
        r = await self.t["ha_read_ws_command"]("zha/devices")
        self.ha.ws_send.assert_awaited_once_with({"type": "zha/devices"})
        self.assertEqual(r["category"], "read")
        self.assertEqual(r["items"][0]["lqi"], 200)

    async def test_bind_en_dos_pasos(self) -> None:
        carga = {"source_ieee": "00:11:22:33:44:55:66:77",
                 "target_ieee": "00:11:22:33:44:55:66:88"}
        vista = await self.t["ha_call_ws_command"]("zha/devices/bind", carga)
        self.assertIn("preview", vista)
        self.ha.ws_send.assert_not_awaited()
        self.ha.ws_send.return_value = None
        r = await self.t["ha_call_ws_command"](
            "zha/devices/bind", carga, confirmation_token=vista["confirmation_token"])
        self.ha.ws_send.assert_awaited_once_with({"type": "zha/devices/bind", **carga})
        self.assertTrue(r["executed"])

    async def test_rechazos_sin_llamar_a_ha(self) -> None:
        for comando in ("zha/devices/permit", "zha/devices/reconfigure",
                        "zha/topology/update", "zha/network/backups/restore",
                        "zha/network/change_channel"):
            for tool in ("ha_read_ws_command", "ha_call_ws_command"):
                with self.subTest(comando=comando, tool=tool):
                    r = await self.t[tool](comando, {"ieee": "00:11:22:33:44:55:66:77"})
                    self.assertEqual(r["error"], "command_denied")
                    self.assertTrue(r["reason"])
        self.ha.ws_send.assert_not_awaited()
        self.ha.ws_one_shot_subscription.assert_not_awaited()
        self.assertEqual(list(Path(self.temp_dir.name).glob("*")), [])

    async def test_permit_remite_a_zha_permit(self) -> None:
        r = await self.t["ha_call_ws_command"]("zha/devices/permit", {"duration": 60})
        self.assertEqual(r["error"], "command_denied")
        self.assertIn("zha.permit", r["reason"])

    def _sin_centinelas(self, r: dict[str, Any], logs: list[dict]) -> None:
        for trozo in _CENTINELAS_ZHA:
            self.assertNotIn(trozo, json.dumps(r, default=str))
            self.assertNotIn(trozo, json.dumps(logs, default=str))

    def _red_tapada(self, info: dict[str, Any]) -> None:
        for clave in ("network_key", "tc_link_key", "key_table", "stack_specific"):
            self.assertEqual(info[clave], "***REDACTED***", clave)
        # Lo útil para diagnosticar sigue visible.
        self.assertEqual(info["channel"], 15)
        self.assertEqual(info["pan_id"], "1A2B")
        self.assertEqual(info["extended_pan_id"], "00:11:22:33:44:55:66:99")

    async def test_network_settings_tapa_las_claves(self) -> None:
        self.ha.ws_send.return_value = {
            "radio_type": "ezsp",
            "device": {"path": "/dev/ttyUSB0", "baudrate": 115200, "flow_control": None},
            "settings": _copia_zigpy(),
        }
        with capture_logs() as logs:
            r = await self.t["ha_read_ws_command"]("zha/network/settings")
        self._red_tapada(r["result"]["settings"]["network_info"])
        self.assertEqual(r["result"]["radio_type"], "ezsp")
        self._sin_centinelas(r, logs)

    async def test_backups_list_tapa_las_claves(self) -> None:
        self.ha.ws_send.return_value = [_copia_zigpy(), _copia_zigpy()]
        with capture_logs() as logs:
            r = await self.t["ha_read_ws_command"]("zha/network/backups/list")
        self.assertEqual(len(r["items"]), 2)
        for copia in r["items"]:
            self._red_tapada(copia["network_info"])
        self._sin_centinelas(r, logs)

    async def test_backups_create_tapa_las_claves(self) -> None:
        vista = await self.t["ha_call_ws_command"]("zha/network/backups/create", {})
        self.ha.ws_send.assert_not_awaited()
        self.ha.ws_send.return_value = {"backup": _copia_zigpy(), "is_complete": True}
        with capture_logs() as logs:
            r = await self.t["ha_call_ws_command"](
                "zha/network/backups/create", {},
                confirmation_token=vista["confirmation_token"])
        self.assertTrue(r["executed"])
        self._red_tapada(r["result"]["backup"]["network_info"])
        self.assertTrue(r["result"]["is_complete"])
        self._sin_centinelas(r, logs)

    async def test_configuration_tapa_el_codigo_de_la_alarma(self) -> None:
        """Hallazgo del tramo 2: `zha/configuration` devuelve las opciones de
        la entrada con `zha_alarm_options.alarm_master_code`, el código maestro
        del panel de alarma de ZHA (`CONF_ZHA_ALARM_SCHEMA` de `zha/helpers.py`;
        `zha/diagnostics.py` lo tapa). Ningún marcador lo reconoce:
        `redact_extra` lo tapa, en la respuesta y en la vista previa de
        `zha/configuration/update`."""
        codigo = "20250257"
        opciones = {"alarm_master_code": codigo, "alarm_failed_tries": 3,
                    "alarm_arm_requires_code": False}
        self.ha.ws_send.return_value = {
            "schemas": {"zha_alarm_options": [
                {"name": "alarm_master_code", "default": "1234", "type": "string",
                 "required": True},
            ]},
            "data": {"zha_alarm_options": dict(opciones)},
        }
        with capture_logs() as logs:
            r = await self.t["ha_read_ws_command"]("zha/configuration")
        leidas = r["result"]["data"]["zha_alarm_options"]
        self.assertEqual(leidas["alarm_master_code"], "***REDACTED***")
        self.assertEqual(leidas["alarm_failed_tries"], 3)
        carga = {"data": {"zha_alarm_options": dict(opciones)}}
        with capture_logs() as logs2:
            vista = await self.t["ha_call_ws_command"]("zha/configuration/update", carga)
        self.assertIn("confirmation_token", vista)
        self.ha.ws_send.assert_awaited_once()  # solo la lectura
        for registro in (r, vista, logs, logs2):
            self.assertNotIn(codigo, json.dumps(registro, default=str))


class TestMatterThread(_Base):
    """FR-003 y FR-004. Control negativo comprobado: quitar `redact_extra` de
    `otbr/info` → cae `test_otbr_info_tapa_el_dataset`; pasar
    `thread/get_dataset_tlv` a `read` → cae `test_rechazos_sin_llamar_a_ha`
    (y la clasificación de la tabla)."""

    inyectadas = False

    async def test_lecturas(self) -> None:
        self.ha.ws_send.return_value = {"node_id": 5, "network_type": "thread",
                                        "available": True}
        r = await self.t["ha_read_ws_command"](
            "matter/node_diagnostics", {"device_id": "<device_id>"})
        self.ha.ws_send.assert_awaited_once_with(
            {"type": "matter/node_diagnostics", "device_id": "<device_id>"})
        self.assertEqual(r["result"]["network_type"], "thread")
        self.ha.ws_send.reset_mock()
        # Forma de `thread/list_datasets` (`thread/websocket_api.py`): sin el TLV.
        self.ha.ws_send.return_value = {"datasets": [{
            "channel": 15, "created": "2026-11-15T00:00:00+00:00",
            "dataset_id": "<dataset_id>", "extended_pan_id": "0011223344556699",
            "network_name": "red-ficticia", "pan_id": "1a2b", "preferred": True,
            "preferred_border_agent_id": None, "preferred_extended_address": None,
            "source": "Google"}]}
        r = await self.t["ha_read_ws_command"]("thread/list_datasets")
        self.ha.ws_send.assert_awaited_once_with({"type": "thread/list_datasets"})
        self.assertEqual(r["result"]["datasets"][0]["channel"], 15)

    async def test_escrituras_en_dos_pasos(self) -> None:
        for comando, carga in (
            ("matter/interview_node", {"device_id": "<device_id>"}),
            ("thread/set_preferred_dataset", {"dataset_id": "<dataset_id>"}),
        ):
            with self.subTest(comando=comando):
                self.ha.ws_send.reset_mock()
                vista = await self.t["ha_call_ws_command"](comando, carga)
                self.assertIn("confirmation_token", vista)
                self.ha.ws_send.assert_not_awaited()
                self.ha.ws_send.return_value = None
                r = await self.t["ha_call_ws_command"](
                    comando, carga, confirmation_token=vista["confirmation_token"])
                self.ha.ws_send.assert_awaited_once_with({"type": comando, **carga})
                self.assertTrue(r["executed"])

    async def test_rechazos_sin_llamar_a_ha(self) -> None:
        for comando in ("matter/open_commissioning_window", "matter/set_wifi_credentials",
                        "matter/commission", "matter/set_thread",
                        "thread/get_dataset_tlv", "thread/delete_dataset",
                        "thread/add_dataset_tlv", "otbr/create_network"):
            for tool in ("ha_read_ws_command", "ha_call_ws_command"):
                with self.subTest(comando=comando, tool=tool):
                    r = await self.t[tool](comando, {"device_id": "<device_id>"})
                    self.assertEqual(r["error"], "command_denied")
                    self.assertTrue(r["reason"])
        self.ha.ws_send.assert_not_awaited()
        self.ha.ws_one_shot_subscription.assert_not_awaited()
        self.assertEqual(list(Path(self.temp_dir.name).glob("*")), [])

    async def test_otbr_info_tapa_el_dataset(self) -> None:
        # Forma REAL de `otbr/info` (`otbr/websocket_api.py`, `websocket_info`):
        # un objeto por router con la dirección extendida (8 bytes en hex) como
        # CLAVE, y `active_dataset_tlvs` = `dataset_tlvs.hex()`, el dataset
        # activo en TLV de MeshCoP. Lleva el PSKc (tipo 0x04) y la clave de red
        # (tipo 0x05), 16 bytes cada uno: se tapa el dataset ENTERO. El
        # centinela es un TLV con esa forma: canal (00 03 00 000f), PAN
        # (01 02 1a2b), PSKc (04 10 …) y clave de red (05 10 …).
        pskc = "c0ffee025025000000000000000000aa"
        clave_red = "c0ffee025025000000000000000000bb"
        tlvs = "000300000f" + "01021a2b" + "0410" + pskc + "0510" + clave_red
        self.ha.ws_send.return_value = {"0011223344556677": {
            "active_dataset_tlvs": tlvs,
            "border_agent_id": "00112233445566778899aabbccddeeff",
            "channel": 15,
            "extended_address": "0011223344556677",
            "extended_pan_id": "0011223344556699",
            "url": "http://core-openthread-border-router:8081",
        }}
        with capture_logs() as logs:
            r = await self.t["ha_read_ws_command"]("otbr/info")
        router = r["result"]["0011223344556677"]
        self.assertEqual(router["active_dataset_tlvs"], "***REDACTED***")
        self.assertEqual(router["channel"], 15)
        self.assertEqual(router["extended_pan_id"], "0011223344556699")
        for trozo in (tlvs, pskc, clave_red, "c0ffee025025"):
            self.assertNotIn(trozo, json.dumps(r))
            self.assertNotIn(trozo, json.dumps(logs, default=str))



# ── Tramo 3: MQTT, USB, Bluetooth y el resto (FR-005, FR-006, FR-009) ─────────


class TestResto(_Base):
    """FR-005 y FR-006 (CAP-104…CAP-106). Formas de los handlers de HA Core
    2026.11.1: `mqtt/__init__.py` y `mqtt/debug_info.py`, `usb/__init__.py`,
    `bluetooth/websocket_api.py`, `dhcp/websocket_api.py`,
    `insteon/api/*.py`, `knx/websocket.py`, `lcn/websocket.py` y
    `dynalite/panel.py`.

    Controles negativos comprobados: pasar `esphome/get_encryption_key` a
    `read` → cae `test_rechazos_sin_llamar_a_ha` (y la clasificación de la
    tabla); renombrar `password` del centinela de Insteon a `pass_hub`, que no
    es marcador → cae `test_insteon_config_tapa_la_contrasena_del_hub` (lo tapa
    el marcador y no otra cosa); quitar `transmitted` de `redact_extra` de
    `mqtt/device/debug_info` → cae `test_mqtt_debug_info_tapa_el_codigo`."""

    inyectadas = False

    async def test_usb_list_serial_ports_con_su_ejemplo(self) -> None:
        from hermes import command_table as ct

        ejemplo = ct.CORE_WS["usb/list_serial_ports"].example
        self.assertEqual(ejemplo, {"include_usage": True})
        # Forma de `_async_serialize_port` más `consumers` y
        # `discovery_flows` (con include_usage).
        self.ha.ws_send.return_value = [{
            "device": "/dev/ttyUSB0", "resolved_device": "/dev/ttyUSB0",
            "serial_number": "0001", "manufacturer": "ficticio",
            "description": "dongle", "interface_description": None,
            "interface_num": None, "matching_integrations": ["zha"],
            "present": True, "vid": "10C4", "pid": "EA60",
            "consumers": [], "discovery_flows": [],
        }]
        r = await self.t["ha_read_ws_command"]("usb/list_serial_ports", ejemplo)
        self.ha.ws_send.assert_awaited_once_with(
            {"type": "usb/list_serial_ports", "include_usage": True})
        self.assertEqual(r["category"], "read")
        self.assertEqual(r["items"][0]["device"], "/dev/ttyUSB0")

    async def test_suscripciones_de_un_solo_mensaje(self) -> None:
        for comando, primero in (
            ("bluetooth/subscribe_advertisements", {"add": []}),
            ("dhcp/subscribe_discovery", {"add": [{
                "mac_address": "00:11:22:33:44:55", "hostname": "ficticio",
                "ip_address": "192.0.2.10"}]}),
            ("insteon/aldb/notify_all", {"type": "status", "is_loading": False}),
        ):
            with self.subTest(comando=comando):
                self.ha.ws_one_shot_subscription.reset_mock()
                self.ha.ws_one_shot_subscription.return_value = primero
                r = await self.t["ha_read_ws_command"](comando)
                self.ha.ws_one_shot_subscription.assert_awaited_once()
                self.assertEqual(self.ha.ws_one_shot_subscription.await_args.args[0],
                                 {"type": comando})
                self.assertEqual(r["result"], primero)
        self.ha.ws_send.assert_not_awaited()

    async def test_escrituras_en_dos_pasos(self) -> None:
        for comando, carga in (
            ("insteon/aldb/write", {"device_address": "1a2b3c"}),
            ("knx/create_entity", {"platform": "switch", "data": {
                "entity": {"name": "ficticio"},
                "knx": {"ga_switch": {"write": "1/1/1"}}}}),
            ("lcn/devices/scan", {"entry_id": "<entry_id>"}),
            ("dynalite/save-config", {"entry_id": "<entry_id>", "config": {
                "host": "192.0.2.10", "port": 12345}}),
        ):
            with self.subTest(comando=comando):
                self.ha.ws_send.reset_mock()
                vista = await self.t["ha_call_ws_command"](comando, carga)
                self.assertIn("preview", vista)
                self.assertIn("confirmation_token", vista)
                self.ha.ws_send.assert_not_awaited()
                self.ha.ws_send.return_value = None
                r = await self.t["ha_call_ws_command"](
                    comando, carga, confirmation_token=vista["confirmation_token"])
                self.ha.ws_send.assert_awaited_once_with({"type": comando, **carga})
                self.assertTrue(r["executed"])

    async def test_rechazos_sin_llamar_a_ha(self) -> None:
        for comando in (
            "esphome/get_encryption_key", "sendspin/get_pairing_token",
            "insteon/config/get_modem_schema", "insteon/config/update_modem_config",
            "knx/project_file_process", "mobile_app/push_notification_channel",
            "generic_camera/start_preview", "ssdp/subscribe_discovery",
            "mqtt/subscribe",
        ):
            for tool in ("ha_read_ws_command", "ha_call_ws_command"):
                with self.subTest(comando=comando, tool=tool):
                    r = await self.t[tool](comando, {"entry_id": "<entry_id>"})
                    self.assertEqual(r["error"], "command_denied")
                    self.assertTrue(r["reason"])
        self.ha.ws_send.assert_not_awaited()
        self.ha.ws_one_shot_subscription.assert_not_awaited()
        self.assertEqual(list(Path(self.temp_dir.name).glob("*")), [])

    async def test_insteon_config_tapa_la_contrasena_del_hub(self) -> None:
        # Forma REAL de `websocket_get_config` (`insteon/api/config.py`):
        # `modem_config` es `config_entry.data`; en un hub v2, las claves de
        # `build_hub_schema` (`host`, `port`, `hub_version`, `username`,
        # `password`). La contraseña la tapa el marcador `password` de la
        # redacción por nombre, sin `redact_extra`.
        self.ha.ws_send.return_value = {
            "modem_config": {"host": "192.0.2.10", "port": 25105, "hub_version": 2,
                             "username": "usuario-ficticio", "password": _CENTINELA},
            "x10_config": [{"housecode": "a", "unitcode": 1, "platform": "light"}],
            "override_config": [{"address": "1a2b3c", "cat": 2, "subcat": 0}],
        }
        with capture_logs() as logs:
            r = await self.t["ha_read_ws_command"]("insteon/config/get")
        modem = r["result"]["modem_config"]
        self.assertEqual(modem["password"], "***REDACTED***")
        self.assertEqual((modem["hub_version"], modem["port"]), (2, 25105))
        self.assertEqual(r["result"]["override_config"][0]["cat"], 2)
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertNotIn(_CENTINELA, json.dumps(logs, default=str))

    async def test_mqtt_debug_info_tapa_el_codigo(self) -> None:
        # Forma REAL de `info_for_device` (`mqtt/debug_info.py`): por entidad,
        # `subscriptions` y `transmitted` (topic y mensajes con `payload` en
        # texto) y `discovery_data` (`topic` y el `payload` de descubrimiento,
        # un objeto). El de una alarma MQTT lleva `code`
        # (`alarm_control_panel.py`, `CONF_CODE`) y, si su
        # `command_template` usa `code`, el mensaje de armar que HA publica lo
        # lleva dentro del texto (`variables = {"action": …, "code": …}`).
        codigo = "20250258"
        self.ha.ws_send.return_value = {
            "entities": [{
                "entity_id": "alarm_control_panel.ficticia",
                "subscriptions": [{"topic": "casa/alarma/estado", "messages": [{
                    "payload": "armed_away", "qos": 0, "retain": True,
                    "time": "2026-11-15T00:00:00+00:00",
                    "topic": "casa/alarma/estado"}]}],
                "discovery_data": {
                    "topic": "homeassistant/alarm_control_panel/ficticia/config",
                    "payload": {"name": "ficticia", "state_topic": "casa/alarma/estado",
                                "command_topic": "casa/alarma/set", "code": codigo,
                                "command_template":
                                    '{"action": "{{ action }}", "code": "{{ code }}"}'},
                },
                "transmitted": [{"topic": "casa/alarma/set", "messages": [{
                    "payload": '{"action": "ARM_AWAY", "code": "' + codigo + '"}',
                    "qos": 0, "retain": False, "time": "2026-11-15T00:00:00+00:00",
                    "topic": "casa/alarma/set"}]}],
            }],
            "triggers": [],
        }
        with capture_logs() as logs:
            r = await self.t["ha_read_ws_command"](
                "mqtt/device/debug_info", {"device_id": "<device_id>"})
        entidad = r["result"]["entities"][0]
        self.assertEqual(entidad["discovery_data"]["payload"]["code"], "***REDACTED***")
        self.assertEqual(entidad["transmitted"], "***REDACTED***")
        # De lo recibido se ve el topic, pero no el contenido: es texto libre
        # del dispositivo y puede llevar un código (convergencia, T049; el
        # escenario del teclado está en `tests/test_convergencia_025.py`).
        self.assertEqual(entidad["subscriptions"][0]["messages"][0]["payload"],
                         "***REDACTED***")
        self.assertEqual(entidad["subscriptions"][0]["messages"][0]["topic"],
                         "casa/alarma/estado")
        self.assertEqual(entidad["discovery_data"]["payload"]["state_topic"],
                         "casa/alarma/estado")
        self.assertNotIn(codigo, json.dumps(r))
        self.assertNotIn(codigo, json.dumps(logs, default=str))
