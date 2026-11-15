"""La clase C de la tabla: comandos de integraciones concretas (spec 025).

FR-001 (y FR-002…FR-006 en los tramos siguientes), FR-007, FR-009 y FR-011 de
la 025; FR-089 de la 008. La clasificación comando a comando, con el handler
leído y el motivo, está en `specs/025-integraciones-especificas/research.md`,
R-1; aquí se fija para que una edición de la tabla no la cambie en silencio.

Reglas:
- `test_clasificacion`: cada comando revisado tiene la categoría y las marcas
  (`one_shot`, `open_world`, `redact_extra`, `example`) de R-1.
- `test_esperado_completo`: cada fila de clase C del inventario de un prefijo
  revisado está en `_ESPERADO`, y al revés (una integración se revisa entera).
- `test_ninguna_pendiente_de_la_025`: ninguna entrada de un prefijo revisado
  dice «spec 025». En el tramo 3, sin filtro: la tabla entera.
- `test_motivos_concretos`: ningún motivo de lo revisado dice «pendiente» ni
  «sin revisar» (FR-007).
- `test_ningun_proxy`: ninguna entrada `hassio/*` ni `supervisor/*` de clase C
  en `read`/`confirm` (el proxy del Supervisor las rechaza).

Control negativo comprobado (tramo 1): pasar `zwave_js/hard_reset_controller`
a `confirm` → cae `test_clasificacion` nombrándolo; quitar `redact_extra` de
`zwave_js/get_provisioning_entries` → cae igual; volver una entrada `zwave_js/`
a «pendiente de revisión (spec 025)» → caen `test_clasificacion`,
`test_ninguna_pendiente_de_la_025` y `test_motivos_concretos`.
"""

from __future__ import annotations

import csv
import pathlib
import unittest

from hermes import command_table as ct

_RAIZ = pathlib.Path(__file__).resolve().parents[1]
_INVENTARIO = _RAIZ / "specs" / "008-cobertura-total" / "inventario"

# Prefijos de las integraciones ya revisadas. Crece por tramos: el 2 añade
# `zha/`, `matter/`, `thread/` y `otbr/`; el 3, el resto.
_REVISADAS: frozenset[str] = frozenset({"zwave_js/"})

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
}


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
        self.assertEqual(len(_ESPERADO), 55)

    def test_ninguna_pendiente_de_la_025(self) -> None:
        malas = sorted(k for k, e in ct.CORE_WS.items()
                       if revisada(k) and "spec 025" in e.reason)
        self.assertEqual(malas, [])

    def test_motivos_concretos(self) -> None:
        malas = sorted(
            f"{k}: {e.reason!r}" for k, e in ct.CORE_WS.items()
            if k in _ESPERADO and ("pendiente" in e.reason or "sin revisar" in e.reason
                                   or len(e.reason) < 15))
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


if __name__ == "__main__":
    unittest.main()
