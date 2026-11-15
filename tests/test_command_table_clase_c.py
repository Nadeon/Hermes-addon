"""La clase C de la tabla: comandos de integraciones concretas (spec 025).

FR-001…FR-007, FR-009, FR-011 y FR-012 de la 025; FR-089 de la 008. Tras el
tramo 3 cubre las 192 filas de la clase C del inventario. La clasificación comando a comando, con el handler
leído y el motivo, está en `specs/025-integraciones-especificas/research.md`,
R-1; aquí se fija para que una edición de la tabla no la cambie en silencio.

Reglas:
- `test_clasificacion`: cada comando revisado tiene la categoría y las marcas
  (`one_shot`, `open_world`, `redact_extra`, `example`) de R-1.
- `test_esperado_completo`: cada fila de clase C del inventario de un prefijo
  revisado está en `_ESPERADO`, y al revés (una integración se revisa entera).
- `test_ninguna_pendiente_de_la_025`: ninguna entrada de la tabla entera
  dice «spec 025».
- `test_ninguna_c_sin_revisar`: ninguna fila C dice «sin revisar» ni
  «pendiente de revisión» (lo nuevo de una versión futura de HA cae aquí).
- `test_motivos_concretos`: ningún motivo de lo revisado es un texto
  provisional («sin revisar», «pendiente de revisión/tool») (FR-007).
- `test_ningun_proxy`: ninguna entrada `hassio/*` ni `supervisor/*` de clase C
  en `read`/`confirm` (el proxy del Supervisor las rechaza).

Control negativo comprobado (tramo 3): devolver `wyoming/info` a «pendiente
de revisión (spec 025)» → caen `test_clasificacion`,
`test_ninguna_pendiente_de_la_025`, `test_ninguna_c_sin_revisar` y
`test_motivos_concretos` nombrándola.

Control negativo comprobado (tramo 2): pasar `thread/get_dataset_tlv` a
`read` → caen `test_clasificacion` y `test_recuento_del_tramo_2`; quitar
`stack_specific` de `zha/network/settings` → cae `test_redact_extra_de_las_claves`.

Control negativo comprobado (tramo 1): pasar `zwave_js/hard_reset_controller`
a `confirm` → cae `test_clasificacion` nombrándolo; quitar `redact_extra` de
`zwave_js/get_provisioning_entries` → cae igual; volver una entrada `zwave_js/`
a «pendiente de revisión (spec 025)» → caen `test_clasificacion`,
`test_ninguna_pendiente_de_la_025` y `test_motivos_concretos`.
"""

from __future__ import annotations

import csv
import pathlib
import re
import unittest

from hermes import command_table as ct

_RAIZ = pathlib.Path(__file__).resolve().parents[1]
_INVENTARIO = _RAIZ / "specs" / "008-cobertura-total" / "inventario"

# Prefijos de las integraciones revisadas: tras el tramo 3, todos los de la
# clase C del inventario (`test_revisadas_cubre_el_inventario` lo vigila).
_REVISADAS: frozenset[str] = frozenset({
    "bluetooth/", "dhcp/", "dynalite/", "esphome/", "generic_camera/",
    "insteon/", "knx/", "lcn/", "lorawan/", "matter/", "mobile_app/",
    "modbus/", "mqtt/", "notify/", "otbr/", "sendspin/", "ssdp/", "thread/",
    "usb/", "wyoming/", "zeroconf/", "zha/", "zwave_js/",
})

# Comando → (categoría, marcas distintas del valor por defecto). R-1.
_ESPERADO: dict[str, tuple[str, set[str]]] = {
    "zwave_js/abort_firmware_update": ("deny", set()),
    "zwave_js/add_node": ("deny", set()),
    "zwave_js/backup_nvm": ("deny", set()),
    "zwave_js/begin_rebuilding_routes": ("confirm", set()),
    "zwave_js/cancel_secure_bootstrap_s2": ("deny", set()),
    "zwave_js/check_for_config_updates": ("read", {"open_world"}),
    "zwave_js/data_collection_status": ("read", set()),
    "zwave_js/get_config_parameters": ("read", set()),
    "zwave_js/get_log_config": ("read", set()),
    "zwave_js/get_node_firmware_update_capabilities": ("read", set()),
    "zwave_js/get_provisioning_entries": ("read", {"redact_extra"}),
    "zwave_js/get_raw_config_parameter": ("read", set()),
    "zwave_js/grant_security_classes": ("deny", set()),
    "zwave_js/hard_reset_controller": ("deny", set()),
    "zwave_js/install_config_update": ("confirm", {"open_world"}),
    "zwave_js/invoke_cc_api": ("deny", set()),
    "zwave_js/is_any_ota_firmware_update_in_progress": ("read", set()),
    "zwave_js/is_node_firmware_update_in_progress": ("read", set()),
    "zwave_js/lookup_device": ("read", set()),
    "zwave_js/network_neighbors": ("confirm", set()),
    "zwave_js/network_status": ("read", set()),
    "zwave_js/node_alerts": ("read", set()),
    "zwave_js/node_capabilities": ("read", set()),
    "zwave_js/node_metadata": ("read", set()),
    "zwave_js/node_status": ("read", set()),
    "zwave_js/parse_qr_code_string": ("deny", set()),
    "zwave_js/provision_smart_start_node": ("deny", set()),
    "zwave_js/rebuild_node_routes": ("confirm", {"example"}),
    "zwave_js/refresh_node_cc_values": ("confirm", set()),
    "zwave_js/refresh_node_info": ("deny", set()),
    "zwave_js/refresh_node_values": ("confirm", set()),
    "zwave_js/remove_failed_node": ("deny", set()),
    "zwave_js/remove_node": ("deny", set()),
    "zwave_js/replace_failed_node": ("deny", set()),
    "zwave_js/restore_nvm": ("deny", set()),
    "zwave_js/set_config_parameter": ("confirm", {"example"}),
    "zwave_js/set_raw_config_parameter": ("confirm", set()),
    "zwave_js/stop_exclusion": ("confirm", set()),
    "zwave_js/stop_inclusion": ("confirm", set()),
    "zwave_js/stop_rebuilding_routes": ("confirm", set()),
    "zwave_js/subscribe_config_parameter_updates": ("deny", set()),
    "zwave_js/subscribe_controller_statistics": ("read", {"one_shot"}),
    "zwave_js/subscribe_firmware_update_status": ("deny", set()),
    "zwave_js/subscribe_log_updates": ("deny", set()),
    "zwave_js/subscribe_new_devices": ("deny", set()),
    "zwave_js/subscribe_node_statistics": ("read", {"one_shot"}),
    "zwave_js/subscribe_node_status": ("deny", set()),
    "zwave_js/subscribe_rebuild_routes_progress": ("deny", set()),
    "zwave_js/subscribe_s2_inclusion": ("deny", set()),
    "zwave_js/supports_feature": ("read", set()),
    "zwave_js/try_parse_dsk_from_qr_code_string": ("deny", set()),
    "zwave_js/unprovision_smart_start_node": ("deny", set()),
    "zwave_js/update_data_collection_preference": ("confirm", set()),
    "zwave_js/update_log_config": ("confirm", set()),
    "zwave_js/validate_dsk_and_enter_pin": ("deny", set()),
    # Tramo 2 — ZHA (CAP-101): 13 read, 10 confirm, 5 deny.
    "zha/configuration": ("read", {"redact_extra"}),
    "zha/configuration/update": ("confirm", {"redact_extra"}),
    "zha/device": ("read", set()),
    "zha/devices": ("read", set()),
    "zha/devices/bind": ("confirm", {"example"}),
    "zha/devices/bindable": ("read", set()),
    "zha/devices/clusters": ("read", set()),
    "zha/devices/clusters/attributes": ("read", set()),
    "zha/devices/clusters/attributes/value": ("read", set()),
    "zha/devices/clusters/commands": ("read", set()),
    "zha/devices/groupable": ("read", set()),
    "zha/devices/permit": ("deny", set()),
    "zha/devices/reconfigure": ("deny", set()),
    "zha/devices/unbind": ("confirm", set()),
    "zha/group": ("read", set()),
    "zha/group/add": ("confirm", {"example"}),
    "zha/group/members/add": ("confirm", set()),
    "zha/group/members/remove": ("confirm", set()),
    "zha/group/remove": ("confirm", set()),
    "zha/groups": ("read", set()),
    "zha/groups/bind": ("confirm", set()),
    "zha/groups/unbind": ("confirm", set()),
    "zha/network/backups/create": ("confirm", {"redact_extra"}),
    "zha/network/backups/list": ("read", {"redact_extra"}),
    "zha/network/backups/restore": ("deny", set()),
    "zha/network/change_channel": ("deny", set()),
    "zha/network/settings": ("read", {"redact_extra"}),
    "zha/topology/update": ("deny", set()),
    # Matter (CAP-102): 3 read, 1 confirm, 7 deny.
    "matter/commission": ("deny", set()),
    "matter/commission_on_network": ("deny", set()),
    "matter/interview_node": ("confirm", set()),
    "matter/network_topology": ("read", set()),
    "matter/node_diagnostics": ("read", set()),
    "matter/open_commissioning_window": ("deny", set()),
    "matter/ping_node": ("read", set()),
    "matter/remove_matter_fabric": ("deny", set()),
    "matter/set_thread": ("deny", set()),
    "matter/set_wifi_credentials": ("deny", set()),
    "matter/subscribe_network_topology": ("deny", set()),
    # Thread y OTBR (CAP-103): 2 read, 2 confirm, 7 deny.
    "otbr/create_network": ("deny", set()),
    "otbr/info": ("read", {"redact_extra"}),
    "otbr/set_channel": ("deny", set()),
    "otbr/set_network": ("deny", set()),
    "thread/add_dataset_tlv": ("deny", set()),
    "thread/delete_dataset": ("deny", set()),
    "thread/discover_routers": ("deny", set()),
    "thread/get_dataset_tlv": ("deny", set()),
    "thread/list_datasets": ("read", set()),
    "thread/set_preferred_border_agent": ("confirm", set()),
    "thread/set_preferred_dataset": ("confirm", {"example"}),
    # Tramo 3 — MQTT (CAP-104): 1 read, 0 confirm, 1 deny.
    "mqtt/device/debug_info": ("read", {"redact_extra", "example"}),
    "mqtt/subscribe": ("deny", set()),
    # USB y Bluetooth (CAP-105): 4 read, 0 confirm, 3 deny.
    "bluetooth/subscribe_advertisements": ("read", {"one_shot"}),
    "bluetooth/subscribe_connection_allocations": ("deny", set()),
    "bluetooth/subscribe_scanner_details": ("deny", set()),
    "bluetooth/subscribe_scanner_state": ("deny", set()),
    "usb/list_serial_integrations": ("read", set()),
    "usb/list_serial_ports": ("read", {"example"}),
    "usb/scan": ("read", set()),
    # El resto (CAP-106): 32 read, 31 confirm, 15 deny.
    "dhcp/subscribe_discovery": ("read", {"one_shot"}),
    "dynalite/get-config": ("read", set()),
    "dynalite/save-config": ("confirm", set()),
    "esphome/get_device_capabilities": ("read", set()),
    "esphome/get_device_wizard": ("read", set()),
    "esphome/get_encryption_key": ("deny", set()),
    "generic_camera/start_preview": ("deny", set()),
    "insteon/aldb/add_default_links": ("confirm", set()),
    "insteon/aldb/change": ("confirm", set()),
    "insteon/aldb/create": ("confirm", set()),
    "insteon/aldb/get": ("read", set()),
    "insteon/aldb/load": ("confirm", set()),
    "insteon/aldb/notify": ("deny", set()),
    "insteon/aldb/notify_all": ("read", {"one_shot"}),
    "insteon/aldb/reset": ("confirm", set()),
    "insteon/aldb/write": ("confirm", set()),
    "insteon/config/device_override/add": ("confirm", set()),
    "insteon/config/device_override/remove": ("confirm", set()),
    "insteon/config/get": ("read", set()),
    "insteon/config/get_broken_links": ("read", set()),
    "insteon/config/get_modem_schema": ("deny", set()),
    "insteon/config/get_unknown_devices": ("read", set()),
    "insteon/config/update_modem_config": ("deny", set()),
    "insteon/device/add": ("deny", set()),
    "insteon/device/add/cancel": ("confirm", set()),
    "insteon/device/add_x10": ("confirm", set()),
    "insteon/device/get": ("read", set()),
    "insteon/device/remove": ("confirm", set()),
    "insteon/properties/change": ("confirm", set()),
    "insteon/properties/get": ("read", set()),
    "insteon/properties/load": ("confirm", set()),
    "insteon/properties/reset": ("confirm", set()),
    "insteon/properties/write": ("confirm", set()),
    "insteon/scene/delete": ("confirm", set()),
    "insteon/scene/get": ("read", set()),
    "insteon/scene/save": ("confirm", set()),
    "insteon/scenes/get": ("read", set()),
    "knx/create_device": ("confirm", set()),
    "knx/create_entity": ("confirm", set()),
    "knx/delete_entity": ("confirm", set()),
    "knx/delete_expose": ("confirm", set()),
    "knx/get_base_data": ("read", set()),
    "knx/get_entities_by_group": ("read", set()),
    "knx/get_entity_config": ("read", set()),
    "knx/get_expose_config": ("read", set()),
    "knx/get_expose_groups": ("read", set()),
    "knx/get_knx_project": ("read", set()),
    "knx/get_schema": ("read", set()),
    "knx/get_time_server_config": ("read", set()),
    "knx/group_monitor_info": ("read", set()),
    "knx/group_telegrams": ("read", set()),
    "knx/project_file_process": ("deny", set()),
    "knx/project_file_remove": ("confirm", set()),
    "knx/query_telegrams": ("read", set()),
    "knx/subscribe_telegrams": ("deny", set()),
    "knx/update_entity": ("confirm", set()),
    "knx/update_expose": ("confirm", set()),
    "knx/update_time_server_config": ("confirm", set()),
    "knx/validate_entity": ("read", set()),
    "knx/validate_expose": ("read", set()),
    "lcn/devices": ("read", set()),
    "lcn/devices/add": ("confirm", set()),
    "lcn/devices/delete": ("confirm", set()),
    "lcn/devices/scan": ("confirm", set()),
    "lcn/entities": ("read", set()),
    "lcn/entities/add": ("confirm", set()),
    "lcn/entities/delete": ("confirm", set()),
    "lorawan/devices/list": ("read", set()),
    "lorawan/devices/subscribe": ("deny", set()),
    "mobile_app/push_notification_channel": ("deny", set()),
    "mobile_app/push_notification_confirm": ("deny", set()),
    "modbus/connections/list": ("read", set()),
    "notify/html5/appkey": ("read", set()),
    "sendspin/get_pairing_token": ("deny", set()),
    "sendspin/subscribe_clients": ("deny", set()),
    "ssdp/subscribe_discovery": ("deny", set()),
    "wyoming/info": ("read", set()),
    "zeroconf/subscribe_discovery": ("deny", set()),
}


# Textos de lo que aún no se ha clasificado a mano: «sin revisar» (generador),
# «pendiente de revisión» (la 025 y la vía T) y «pendiente de tool dedicada».
_PROVISIONAL = re.compile(r"sin revisar|pendiente de (revisión|tool)")


def _filas_c() -> dict[str, dict[str, str]]:
    with (_INVENTARIO / "core-ws.tsv").open(encoding="utf-8", newline="") as f:
        return {fila["comando"]: fila for fila in csv.DictReader(f, delimiter="\t")
                if fila["clase"] == "C"}


def revisada(comando: str) -> bool:
    return comando.startswith(tuple(_REVISADAS))


def _marcas(e) -> set[str]:
    marcas = set()
    if e.one_shot:
        marcas.add("one_shot")
    if e.open_world:
        marcas.add("open_world")
    if e.redact_extra:
        marcas.add("redact_extra")
    if e.example is not None:
        marcas.add("example")
    return marcas


class TestClaseC(unittest.TestCase):
    def test_clasificacion(self) -> None:
        for comando, (categoria, marcas) in _ESPERADO.items():
            with self.subTest(comando=comando):
                e = ct.CORE_WS[comando]
                self.assertEqual((e.category, _marcas(e)), (categoria, marcas))
                self.assertEqual(e.family, "generic_commands")
                self.assertIsNone(e.tool)

    def test_esperado_completo(self) -> None:
        filas = {k for k in _filas_c() if revisada(k)}
        self.assertEqual(sorted(filas - set(_ESPERADO)), [], "revisadas sin _ESPERADO")
        self.assertEqual(sorted(set(_ESPERADO) - filas), [], "_ESPERADO fuera de clase C")
        self.assertEqual(len(_ESPERADO), 192)

    def test_revisadas_cubre_el_inventario(self) -> None:
        """Cada fila de clase C del inventario cae en un prefijo revisado."""
        self.assertEqual(sorted(k for k in _filas_c() if not revisada(k)), [])

    def test_ninguna_pendiente_de_la_025(self) -> None:
        """FR-007, tras el tramo 3: ninguna entrada de la tabla ENTERA (Core y
        Supervisor, de cualquier clase) remite ya a la 025.

        Control negativo comprobado: devolver `wyoming/info` a «pendiente de
        revisión (spec 025)» → cae nombrándola (y también
        `test_clasificacion` y `test_motivos_concretos`)."""
        malas = sorted(str(k) for tabla in (ct.CORE_WS, ct.SUPERVISOR)
                       for k, e in tabla.items() if "spec 025" in e.reason)
        self.assertEqual(malas, [])

    def test_ninguna_c_sin_revisar(self) -> None:
        """FR-012: ninguna fila de clase C queda «sin revisar» ni «pendiente
        de revisión» (lo que una versión nueva de HA añada entra así y cae
        aquí nombrándolo)."""
        malas = sorted(k for k in _filas_c() if _PROVISIONAL.search(ct.CORE_WS[k].reason))
        self.assertEqual(malas, [])

    def test_motivos_concretos(self) -> None:
        # «pendiente de» y no «pendiente» a secas: varios motivos de Insteon
        # dicen, con razón, que un cambio queda pendiente hasta escribirlo
        # (`insteon/aldb/change`, «pendiente hasta aldb/write»).
        malas = sorted(
            f"{k}: {e.reason!r}" for k, e in ct.CORE_WS.items()
            if k in _ESPERADO and (_PROVISIONAL.search(e.reason) or len(e.reason) < 15))
        self.assertEqual(malas, [])

    def test_ningun_proxy(self) -> None:
        abiertas = sorted(
            k for k in _filas_c()
            if k.startswith(("hassio/", "supervisor/"))
            and ct.CORE_WS[k].category in ("read", "confirm"))
        self.assertEqual(abiertas, [])

    def test_recuento_de_zwave(self) -> None:
        """R-1: 18 `read`, 13 `confirm` y 24 `deny` (FR-001)."""
        cuenta: dict[str, int] = {}
        for k, e in ct.CORE_WS.items():
            if k.startswith("zwave_js/"):
                cuenta[e.category] = cuenta.get(e.category, 0) + 1
        self.assertEqual(cuenta, {"read": 18, "confirm": 13, "deny": 24})

    def test_recuento_del_tramo_2(self) -> None:
        """R-1: ZHA 13/10/5, Matter 3/1/7, Thread y OTBR 2/2/7 (FR-002…FR-004)."""
        grupos = {"zha/": "zha", "matter/": "matter", "thread/": "thread", "otbr/": "thread"}
        cuenta: dict[str, dict[str, int]] = {}
        for k, e in ct.CORE_WS.items():
            for prefijo, grupo in grupos.items():
                if k.startswith(prefijo):
                    c = cuenta.setdefault(grupo, {})
                    c[e.category] = c.get(e.category, 0) + 1
        self.assertEqual(cuenta, {
            "zha": {"read": 13, "confirm": 10, "deny": 5},
            "matter": {"read": 3, "confirm": 1, "deny": 7},
            "thread": {"read": 2, "confirm": 2, "deny": 7},
        })

    def test_recuento_del_tramo_3(self) -> None:
        """R-1: MQTT 1/0/1, USB y Bluetooth 4/0/3, el resto 32/31/15
        (FR-005, FR-006)."""
        cuenta: dict[str, dict[str, int]] = {}
        for k, fila in _filas_c().items():
            if fila["cap"] in ("CAP-104", "CAP-105", "CAP-106"):
                c = cuenta.setdefault(fila["cap"], {})
                cat = ct.CORE_WS[k].category
                c[cat] = c.get(cat, 0) + 1
        self.assertEqual(cuenta, {
            "CAP-104": {"read": 1, "deny": 1},
            "CAP-105": {"read": 4, "deny": 3},
            "CAP-106": {"read": 32, "confirm": 31, "deny": 15},
        })

    def test_recuento_total(self) -> None:
        """R-1: las 192 de la clase C, 73 `read`, 57 `confirm` y 62 `deny`."""
        cuenta: dict[str, int] = {}
        for k in _filas_c():
            cat = ct.CORE_WS[k].category
            cuenta[cat] = cuenta.get(cat, 0) + 1
        self.assertEqual(cuenta, {"read": 73, "confirm": 57, "deny": 62})

    def test_redact_extra_de_las_claves(self) -> None:
        """R-6: qué claves tapa cada entrada; el valor ENTERO (FR-008)."""
        claves_zha = ("network_key", "tc_link_key", "key_table", "stack_specific")
        esperado = {
            "zha/network/settings": claves_zha,
            "zha/network/backups/list": claves_zha,
            "zha/network/backups/create": claves_zha,
            "zha/configuration": ("alarm_master_code",),
            "zha/configuration/update": ("alarm_master_code",),
            "otbr/info": ("active_dataset_tlvs",),
            "mqtt/device/debug_info": ("code", "transmitted", "messages.payload"),
        }
        for comando, claves in esperado.items():
            with self.subTest(comando=comando):
                self.assertEqual(ct.CORE_WS[comando].redact_extra, claves)

    def test_permit_remite_a_la_accion(self) -> None:
        """R-3: `zha/devices/permit` se rechaza, pero su motivo dice cómo
        permitir uniones sin la genérica."""
        motivo = ct.CORE_WS["zha/devices/permit"].reason
        self.assertIn("zha.permit", motivo)
        self.assertIn("ha_call_service", motivo)


if __name__ == "__main__":
    unittest.main()
