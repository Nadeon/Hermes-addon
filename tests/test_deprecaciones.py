"""Lo deprecado sigue en la 1.2.0 y lo que HA retira no rompe nada (spec 027).

FR-008: la 1.2.0 no retira nada (decisión 3 de la 008). Los cuatro alias
`ha_hacs_*` se retiran en la 1.3.0 y `ha_remove_device_from_config_entry`
sigue registrada y deprecada hasta antes de HA 2027.9.

FR-010: HA retira de los dispositivos `config_entries` y
`config_entries_subentries` en la 2027.8 y `primary_config_entry` en la
2027.10 (`homeassistant/helpers/device_registry.py`, 2026.11.1). Hermes usa
`config_entry_id` y deja `config_entries` como respaldo desde la 1.0.12; aquí
se fija con la forma que tendrán las respuestas.

FR-003: el valor por defecto de `oauth_cimd_allowed_hosts` no cambia (D-09
de la 008).

Controles negativos comprobados (T009; pasan a la primera porque fijan lo
que ya existe):
- `device_config_entries` ignorando `config_entry_id` → los 3 tests de
  `TestDispositivosSinCamposDeprecados` que cuentan o eligen en rojo (con la
  forma de 2027.10).
- `readOnlyHint` de `ha_hacs_info` cambiado a `False` en la copia del test →
  `test_anotaciones_iguales` en rojo.
- `oauth_cimd_allowed_hosts: ["claude.ai"]` en las opciones de `config.yaml`
  → `test_valor_por_defecto_en_config_yaml` en rojo.
"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from typing import Any
from unittest import mock
from unittest.mock import AsyncMock, patch

import yaml

from hermes.config import load_config
from hermes.tools import registry_device as device_mod
from hermes.tools.config_entries import _count_config_entry_dependents
from tests.test_tools_registration import _real_registry

_RAIZ = Path(__file__).resolve().parent.parent
_SRC = _RAIZ / "hermes" / "src" / "hermes"

# Anotaciones de hoy (1.1.2 y 1.2.0), copiadas a mano: si cambian, este test
# obliga a que sea una decisión explícita.
_ANOTACIONES = {
    "ha_hacs_get_repository": {
        "title": "HACS get repository (Home Assistant)", "read_only_hint": True,
        "destructive_hint": False, "idempotent_hint": True, "open_world_hint": False},
    "ha_hacs_info": {
        "title": "HACS info (Home Assistant)", "read_only_hint": True,
        "destructive_hint": False, "idempotent_hint": True, "open_world_hint": False},
    "ha_hacs_list_repositories": {
        "title": "HACS list repositories (Home Assistant)", "read_only_hint": True,
        "destructive_hint": False, "idempotent_hint": True, "open_world_hint": False},
    "ha_hacs_list_updates": {
        "title": "HACS list updates (Home Assistant)", "read_only_hint": True,
        "destructive_hint": False, "idempotent_hint": True, "open_world_hint": False},
    "ha_remove_device_from_config_entry": {
        "title": "Remove device from config entry (Home Assistant)",
        "read_only_hint": False, "destructive_hint": True,
        "idempotent_hint": True, "open_world_hint": False},
}

_ARGUMENTOS = {
    "ha_hacs_get_repository": (["repository_id"], ["repository_id"]),
    "ha_hacs_info": ([], []),
    "ha_hacs_list_repositories": (
        ["category", "installed_only", "limit", "search"], []),
    "ha_hacs_list_updates": ([], []),
    "ha_remove_device_from_config_entry": (
        ["config_entry_id", "confirmation_token", "device_id"],
        ["config_entry_id", "device_id"]),
}

_SUSTITUTAS = {
    "ha_hacs_get_repository": "ha_marketplace_get_repository",
    "ha_hacs_info": "ha_marketplace_info",
    "ha_hacs_list_repositories": "ha_marketplace_list_repositories",
    "ha_hacs_list_updates": "ha_marketplace_list_updates",
}


class TestDeprecadasSiguen(unittest.TestCase):
    """FR-008: con la configuración por defecto, las cinco siguen igual."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tools = _real_registry()

    def test_registradas_con_sus_argumentos(self) -> None:
        for nombre, (props, requeridos) in _ARGUMENTOS.items():
            with self.subTest(tool=nombre):
                self.assertIn(nombre, self.tools)
                params = self.tools[nombre].parameters
                self.assertEqual(sorted(params.get("properties", {})), props)
                self.assertEqual(sorted(params.get("required") or []), requeridos)

    def test_anotaciones_iguales(self) -> None:
        for nombre, esperadas in _ANOTACIONES.items():
            with self.subTest(tool=nombre):
                anot = self.tools[nombre].annotations
                self.assertEqual(anot.model_dump(exclude_none=True), esperadas)

    def test_los_alias_citan_la_1_3_0_y_su_sustituta(self) -> None:
        for alias, sustituta in _SUSTITUTAS.items():
            with self.subTest(tool=alias):
                texto = self.tools[alias].description or ""
                self.assertIn("DEPRECATED", texto)
                self.assertIn("1.3.0", texto)
                self.assertIn(sustituta, texto)

    def test_la_deprecada_cita_2027_9_y_ha_remove_device(self) -> None:
        texto = self.tools["ha_remove_device_from_config_entry"].description or ""
        self.assertIn("DEPRECATED", texto)
        self.assertIn("2027.9", texto)
        self.assertIn("ha_remove_device", texto.replace("ha_remove_device_from", ""))


def _dispositivos(forma: str) -> list[dict[str, Any]]:
    """Los mismos dispositivos con la forma de HA 2026.11 o la de 2027.10.

    2027.10: sin `config_entries`, `config_entries_subentries` (2027.8) ni
    `primary_config_entry` (2027.10); solo `config_entry_id`.
    """
    base = [
        {"id": "dev_a", "name": "Device A", "name_by_user": None,
         "config_entry_id": "ce_1", "parent_device_id": None},
        {"id": "dev_b", "name": "Device B", "name_by_user": None,
         "config_entry_id": "ce_1", "parent_device_id": None},
        {"id": "dev_c", "name": "Device C", "name_by_user": None,
         "config_entry_id": "ce_2", "parent_device_id": None},
    ]
    if forma == "2027.10":
        return base
    viejos = []
    for d in base:
        viejos.append({
            **d,
            "config_entries": [d["config_entry_id"]],
            "config_entries_subentries": {d["config_entry_id"]: [None]},
            "primary_config_entry": d["config_entry_id"],
        })
    return viejos


class _Cliente:
    def __init__(self, devices: list[dict], entities: list[dict] | None = None) -> None:
        self.devices = devices
        self.entities = entities or []
        self.enviados: list[dict] = []

    async def ws_send(self, payload: dict, timeout_seconds: int = 30) -> Any:
        self.enviados.append(payload)
        tipo = payload.get("type")
        if tipo == "config/device_registry/list":
            return self.devices
        if tipo == "config/entity_registry/list":
            return self.entities
        return None


class TestDispositivosSinCamposDeprecados(unittest.IsolatedAsyncioTestCase):
    """FR-010: la forma de los dispositivos de HA 2027.8 y 2027.10."""

    async def test_recuento_de_las_vistas_previas_de_config_entries(self) -> None:
        # `_count_config_entry_dependents` es el recuento de las vistas previas
        # de `ha_disable_config_entry` y `ha_delete_config_entry`.
        for entrada, esperados in (("ce_1", 2), ("ce_2", 1), ("ce_x", 0)):
            with self.subTest(entrada=entrada):
                antes = await _count_config_entry_dependents(
                    _Cliente(_dispositivos("2026.11")), entrada)  # type: ignore[arg-type]
                despues = await _count_config_entry_dependents(
                    _Cliente(_dispositivos("2027.10")), entrada)  # type: ignore[arg-type]
                self.assertEqual(antes["devices"], esperados)
                self.assertEqual(despues, antes)

    async def test_plan_de_ha_remove_device_en_ha_antiguo(self) -> None:
        # HA anterior a 2026.9: `ha_remove_device` usa `remove_config_entry`
        # con la integración del dispositivo, que sale de `config_entry_id`.
        from aiohttp import ClientSession

        from tests._ha_fixture import make_ready_client

        class _DummyMCP:
            def __init__(self) -> None:
                self.tools: dict = {}

            def tool(self):
                def deco(fn):
                    self.tools[fn.__name__] = fn
                    return fn
                return deco

        import json

        for forma in ("2026.11", "2027.10"):
            with self.subTest(forma=forma):
                async with ClientSession() as session:
                    client = make_ready_client(session, {})
                    falso = _Cliente(_dispositivos(forma))
                    client.ws_send = falso.ws_send  # type: ignore[method-assign]
                    mcp = _DummyMCP()
                    device_mod.register(mcp, client)
                    with patch.object(device_mod, "ha_at_least",
                                      AsyncMock(return_value=False)):
                        primero = json.loads(await mcp.tools["ha_remove_device"]("dev_a"))
                preview = primero["preview"]
                self.assertEqual(preview["method"],
                                 "config/device_registry/remove_config_entry")
                self.assertEqual(preview["config_entry_id"], "ce_1")

    def test_device_config_entries_con_y_sin_los_campos(self) -> None:
        antes = [device_mod.device_config_entries(d) for d in _dispositivos("2026.11")]
        despues = [device_mod.device_config_entries(d) for d in _dispositivos("2027.10")]
        self.assertEqual(antes, despues)
        self.assertEqual(despues, [["ce_1"], ["ce_1"], ["ce_2"]])

    def test_hermes_no_lee_los_campos_que_ha_retira(self) -> None:
        patron = re.compile(r"primary_config_entry|config_entries_subentries")
        usos = [
            str(p.relative_to(_RAIZ))
            for p in _SRC.rglob("*.py")
            if patron.search(p.read_text(encoding="utf-8"))
        ]
        self.assertEqual(usos, [])


class TestCimdPorDefecto(unittest.TestCase):
    """FR-003: `oauth_cimd_allowed_hosts` sigue vacía por defecto (D-09)."""

    def test_valor_por_defecto_en_config_yaml(self) -> None:
        datos = yaml.safe_load((_RAIZ / "hermes" / "config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(datos["options"]["oauth_cimd_allowed_hosts"], [])

    def test_configuracion_cargada_sin_la_variable(self) -> None:
        limpio = {k: v for k, v in os.environ.items() if not k.startswith("HERMES_")}
        with mock.patch.dict(os.environ, limpio, clear=True):
            self.assertEqual(load_config().oauth_cimd_allowed_hosts, [])


if __name__ == "__main__":
    unittest.main()
