"""Converge de la 026 (escritura del Marketplace): T031-T037.

Formas reales sacadas de HA Core 2026.11.1 (`components/marketplace` y
`helpers/entity_registry.py`): la entrada del registro de una entidad es
`RegistryEntry.as_partial_dict` (`platform`, `unique_id`, `translation_key`…)
y `config/entity_registry/list_for_display` da `entities` con `ei` y `pl`.
El interruptor «pre-release» es `RepositoryPreReleaseSwitchEntity`
(plataforma `marketplace`, `translation_key: "pre-release"`,
`entity_category: "config"`, `unique_id` = id del repositorio). Datos
ficticios (`ejemplo/*`, `light.salon`).

Controles negativos, comprobados revirtiendo el código un momento:
- T031: sin la línea que pone `warning_marketplace_install` en la vista previa
  de automatizaciones → caen `TestAvisoAutomatizacion.test_*_avisa` (y lo
  mismo en scripts); `menciona_update_install` devolviendo siempre False →
  caen todos los `TestMencionaUpdateInstall.test_detecta_*`.
- T032: sin `bool(interruptores_beta)` en `needs_token` → caen
  `test_interruptor_del_marketplace_pide_token` y `test_homeassistant_turn_on`;
  sin el rechazo del objetivo indirecto → cae `test_indirecto_con_interruptores`.
- T034/T035: con el texto anterior caen `test_ignorar_dice_lo_del_aviso` y
  `test_quitar_dice_lo_de_github`.
- T036: sin `local_path` en el `estado` → cae `test_ruta_cambiada_invalida_el_token`.
- T037: sin `_resultado_desconocido` (el `ha_error` de antes) → caen los
  `test_plazo_agotado_*`.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import ClientSession
from aioresponses import aioresponses

import hermes.security as security
import hermes.tools.automations as automations_module
import hermes.tools.scripts as scripts_module
from hermes.ha import HAConnectionError, HATimeoutError
from hermes.tools import marketplace_manage as mm
from hermes.tools.ha import menciona_update_install
from tests._ha_fixture import make_ready_client
from tests.fixtures.marketplace_escritura import (
    ID_INSTALADO,
    ID_PERSONALIZADO,
    SLUG,
    MarketplaceSimulado,
    SupervisorSimulado,
    error,
)
from tests.test_tools_validacion_al_guardar import _AUTOMATIZACION, _SCRIPT, FakeWS


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


# ── T031: aviso de `update.install` en automatizaciones y scripts ────────────

_INSTALAR = {"action": "update.install",
             "target": {"entity_id": "update.ejemplo_integracion_update"},
             "data": {"version": "main"}}


class TestMencionaUpdateInstall(unittest.TestCase):
    def test_detecta_action(self) -> None:
        self.assertTrue(menciona_update_install({"actions": [_INSTALAR]}))

    def test_detecta_service_historico_y_mayusculas(self) -> None:
        self.assertTrue(menciona_update_install(
            {"sequence": [{"service": " Update.Install ", "entity_id": "update.x"}]}))

    def test_detecta_anidado(self) -> None:
        config = {"actions": [{"choose": [{"conditions": [], "sequence": [
            {"if": [], "then": [{"parallel": [_INSTALAR]}]}]}]}]}
        self.assertTrue(menciona_update_install(config))

    def test_detecta_plantillas_que_lo_nombran(self) -> None:
        self.assertTrue(menciona_update_install(
            {"actions": [{"action": "{{ 'update.' ~ 'install' }}"}]}))
        self.assertTrue(menciona_update_install(
            {"actions": [{"service_template": "update.{{ 'install' }}"}]}))

    def test_no_avisa_de_lo_demas(self) -> None:
        for config in (
            {"actions": [{"action": "update.skip", "target": {"entity_id": "update.x"}}]},
            {"actions": [{"action": "light.turn_on", "target": {"entity_id": "light.salon"}}]},
            {"actions": [{"action": "{{ 'light.turn_' ~ 'on' }}"}]},
            # Un nombre de entidad con «install» no es la acción.
            {"actions": [{"action": "switch.turn_on",
                          "target": {"entity_id": "switch.install_mode"}}]},
        ):
            with self.subTest(config=config):
                self.assertFalse(menciona_update_install(config))


class _BaseGuardar:
    C: dict[str, Any] = {}

    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.session = ClientSession()
        cache = {"automation.cocina": {"entity_id": "automation.cocina", "state": "on",
                                       "attributes": {"id": "1689"}}}
        self.ha_client = make_ready_client(self.session, cache)
        self.ha_client.ws_send = FakeWS()
        self.mcp = DummyMCP()
        automations_module.register(self.mcp, self.ha_client)
        scripts_module.register(self.mcp, self.ha_client)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def vista_previa(self, config: dict) -> dict:
        with aioresponses() as m:
            m.get(self.C["url"], status=404, body="no")
            return await self.mcp.tools[self.C["tool"]](self.C["id"], config)

    def con_acciones(self, acciones: list[dict]) -> dict:
        config = dict(self.C["valida"])
        config["actions" if "actions" in config else "sequence"] = acciones
        return config

    async def test_action_avisa(self) -> None:
        r = await self.vista_previa(self.con_acciones([_INSTALAR]))
        self.assertIn("confirmation_token", r, r)
        aviso = r["preview"]["warning_marketplace_install"]
        for palabra in ("update.install", "without a Home Assistant user", "ANY person",
                        "third-party code", "Marketplace"):
            self.assertIn(palabra, aviso)

    async def test_service_avisa(self) -> None:
        r = await self.vista_previa(self.con_acciones(
            [{"service": "update.install", "target": {"entity_id": "update.x"}}]))
        self.assertIn("warning_marketplace_install", r["preview"])

    async def test_sin_update_install_no_avisa(self) -> None:
        r = await self.vista_previa(self.C["valida"])
        self.assertIn("confirmation_token", r)
        self.assertNotIn("warning_marketplace_install", r["preview"])


class TestAvisoAutomatizacion(_BaseGuardar, unittest.IsolatedAsyncioTestCase):
    C = _AUTOMATIZACION


class TestAvisoScript(_BaseGuardar, unittest.IsolatedAsyncioTestCase):
    C = _SCRIPT


# ── T032: interruptor «pre-release» por `ha_call_service` ────────────────────

_INTERRUPTOR = "switch.ejemplo_integracion_pre_release"


def _entrada(entity_id: str, platform: str) -> dict[str, Any]:
    """`RegistryEntry.as_partial_dict` de HA 2026.11.1."""
    return {
        "area_id": None, "categories": {}, "config_entry_id": "01JCONFIGENTRY",
        "config_subentry_id": None, "created_at": 1763000000.0,
        "device_id": "0123456789abcdef", "disabled_by": None,
        "entity_category": "config" if platform == "marketplace" else None,
        "entity_id": entity_id, "hidden_by": None, "icon": None,
        "id": "a1b2c3d4", "labels": [], "modified_at": 1763000000.0, "name": None,
        "next_name_part": None, "options": {}, "original_name": None,
        "platform": platform,
        "translation_key": "pre-release" if platform == "marketplace" else None,
        "unique_id": ID_INSTALADO if platform == "marketplace" else "xyz",
    }


class _Registro:
    def __init__(self, entradas: dict[str, dict[str, Any]], falla: bool = False) -> None:
        self.entradas = entradas
        self.falla = falla
        self.enviados: list[dict[str, Any]] = []

    async def __call__(self, payload: dict, timeout_seconds: int = 30) -> Any:
        self.enviados.append(payload)
        if self.falla:
            raise HAConnectionError("WebSocket no disponible para envío de comandos.")
        if payload["type"] == "config/entity_registry/get_entries":
            return {eid: self.entradas.get(eid) for eid in payload["entity_ids"]}
        if payload["type"] == "config/entity_registry/list_for_display":
            return {"entity_categories": {"0": "config", "1": "diagnostic"},
                    "entities": [{"ei": e["entity_id"], "pl": e["platform"]}
                                 for e in self.entradas.values()]}
        raise AssertionError(f"unexpected ws_send: {payload['type']}")


class TestInterruptorBeta(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    def tools(self, registro: _Registro) -> tuple[dict, MagicMock]:
        from hermes.tools.ha import register

        client = MagicMock()
        client.is_ready = True
        client.call_service = AsyncMock(return_value=[])
        client.ws_send = registro
        mcp = DummyMCP()
        with patch("hermes.tools.ha.requires_ready", return_value=lambda fn: fn):
            register(mcp, client, call_service_auto_classify=False)
        return mcp.tools, client

    def registro(self, falla: bool = False) -> _Registro:
        return _Registro({
            _INTERRUPTOR: _entrada(_INTERRUPTOR, "marketplace"),
            "switch.cafetera": _entrada("switch.cafetera", "tplink"),
        }, falla=falla)

    async def test_interruptor_del_marketplace_pide_token(self) -> None:
        tools, client = self.tools(self.registro())
        data = {"entity_id": _INTERRUPTOR}
        r = await tools["ha_call_service"]("switch", "turn_on", data)
        self.assertIn("confirmation_token", r, r)
        p = r["preview"]
        self.assertEqual(p["marketplace_prerelease_switches"], [_INTERRUPTOR])
        for palabra in ("BETA", "third-party code", "risk warning", "installs nothing"):
            self.assertIn(palabra, p["warning_marketplace_beta"])
        self.assertIn("pre-release", p["reason"])
        client.call_service.assert_not_called()
        # Con el token, la llamada de siempre.
        r = await tools["ha_call_service"]("switch", "turn_on", data,
                                           confirmation_token=r["confirmation_token"])
        client.call_service.assert_awaited_once_with("switch", "turn_on", data,
                                                     allow_dangerous=True)

    async def test_turn_off_toggle_y_target(self) -> None:
        tools, client = self.tools(self.registro())
        for servicio, data in (("turn_off", {"entity_id": [_INTERRUPTOR]}),
                               ("toggle", {"target": {"entity_id": _INTERRUPTOR.upper()}}),
                               ("turn_on", {"entity_id": f"switch.cafetera, {_INTERRUPTOR}"})):
            with self.subTest(servicio=servicio, data=data):
                r = await tools["ha_call_service"]("switch", servicio, data)
                self.assertIn("confirmation_token", r, r)
        client.call_service.assert_not_called()

    async def test_homeassistant_turn_on(self) -> None:
        tools, client = self.tools(self.registro())
        r = await tools["ha_call_service"]("homeassistant", "turn_on",
                                           {"entity_id": _INTERRUPTOR})
        self.assertIn("confirmation_token", r, r)
        client.call_service.assert_not_called()

    async def test_otro_interruptor_sigue_como_en_la_1_1_2(self) -> None:
        tools, client = self.tools(self.registro())
        r = await tools["ha_call_service"]("switch", "turn_on", {"entity_id": "switch.cafetera"})
        self.assertNotIn("confirmation_token", r)
        client.call_service.assert_awaited_once_with(
            "switch", "turn_on", {"entity_id": "switch.cafetera"})

    async def test_indirecto_con_interruptores(self) -> None:
        tools, client = self.tools(self.registro())
        for data in ({"area_id": "salon"}, {"target": {"device_id": "abc"}},
                     {"target": {"label_id": "x"}}, {"entity_id": "all"},
                     {"floor_id": "planta_baja"}):
            with self.subTest(data=data):
                r = await tools["ha_call_service"]("switch", "turn_on", data)
                self.assertEqual(r["error"], "use_entity_ids")
                self.assertNotIn("confirmation_token", r)
        client.call_service.assert_not_called()

    async def test_indirecto_sin_interruptores_sigue(self) -> None:
        registro = _Registro({"switch.cafetera": _entrada("switch.cafetera", "tplink")})
        tools, client = self.tools(registro)
        await tools["ha_call_service"]("switch", "turn_on", {"area_id": "salon"})
        client.call_service.assert_awaited_once()

    async def test_registro_ilegible_fail_closed(self) -> None:
        tools, client = self.tools(self.registro(falla=True))
        for data in ({"entity_id": _INTERRUPTOR}, {"area_id": "salon"}):
            with self.subTest(data=data):
                r = await tools["ha_call_service"]("switch", "turn_on", data)
                self.assertEqual(r["error"], "registry_unavailable")
        client.call_service.assert_not_called()

    async def test_otros_dominios_no_leen_el_registro(self) -> None:
        registro = self.registro()
        tools, _ = self.tools(registro)
        await tools["ha_call_service"]("light", "turn_on", {"entity_id": "light.salon"})
        await tools["ha_call_service"]("switch", "turn_on", {"entity_id": "light.salon"})
        self.assertEqual(registro.enviados, [])


# ── T034-T037: los bajos ─────────────────────────────────────────────────────


class _BaseMarketplace(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.client = make_ready_client(self.session, {})
        self.ha = MarketplaceSimulado()
        self.sv = SupervisorSimulado(self.ha)
        self.client.ws_send = self.ha  # type: ignore[method-assign]
        self.client.sv_request = self.sv  # type: ignore[method-assign]
        self.mcp = DummyMCP()
        mm.register(self.mcp, self.client)

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def call(self, tool: str, **kwargs: Any) -> Any:
        return await self.mcp.tools[tool](**kwargs)


class TestBajos(_BaseMarketplace):
    async def test_ignorar_dice_lo_del_aviso(self) -> None:
        r = await self.call("ha_marketplace_ignore_repository", repository_id=ID_INSTALADO)
        aviso = r["preview"]["repairs_issue"]
        for palabra in ("NOT deleted now", "restarts", "not created again"):
            self.assertIn(palabra, aviso)

    async def test_quitar_dice_lo_de_github(self) -> None:
        r = await self.call("ha_marketplace_remove_repository", repository_id=ID_PERSONALIZADO)
        self.assertIn("GitHub connected", r["preview"]["effect"])

    async def test_desinstalar_avisa_de_la_ruta(self) -> None:
        r = await self.call("ha_marketplace_uninstall", repository_id=ID_INSTALADO)
        self.assertIn("recompute", r["preview"]["removes"]["path_note"])

    async def test_ruta_cambiada_invalida_el_token(self) -> None:
        r = await self.call("ha_marketplace_uninstall", repository_id=ID_INSTALADO)
        self.ha.repo(ID_INSTALADO)["local_path"] = "/config/custom_components/otra"
        hecho = await self.call("ha_marketplace_uninstall", repository_id=ID_INSTALADO,
                                confirmation_token=r["confirmation_token"])
        self.assertEqual(hecho["error"], security.ESTADO_CAMBIADO)
        self.assertEqual(self.sv.llamadas, [])
        self.assertNotIn("marketplace/repository/uninstall", self.ha.tipos)

    async def test_dominio_cambiado_invalida_el_token(self) -> None:
        r = await self.call("ha_marketplace_uninstall", repository_id=ID_INSTALADO)
        self.ha.repo(ID_INSTALADO)["domain"] = "otro"
        hecho = await self.call("ha_marketplace_uninstall", repository_id=ID_INSTALADO,
                                confirmation_token=r["confirmation_token"])
        self.assertEqual(hecho["error"], security.ESTADO_CAMBIADO)

    async def _desinstalar_con(self, exc: BaseException) -> dict[str, Any]:
        r = await self.call("ha_marketplace_uninstall", repository_id=ID_INSTALADO)
        self.ha.errores["marketplace/repository/uninstall"] = exc
        return await self.call("ha_marketplace_uninstall", repository_id=ID_INSTALADO,
                               confirmation_token=r["confirmation_token"])

    async def test_plazo_agotado_resultado_desconocido(self) -> None:
        # Lo que lanza `HAClient.ws_send` al agotar el plazo en esta rama.
        hecho = await self._desinstalar_con(HAConnectionError(
            "Timeout waiting for HA WS response for command marketplace/repository/uninstall"))
        self.assertEqual(hecho["error"], "outcome_unknown")
        self.assertIn("sent", hecho)
        self.assertIsNone(hecho["sent"])
        self.assertIn("MAY have happened", hecho["detail"])
        self.assertIn("ha_marketplace_get_repository", hecho["hint"])
        self.assertEqual(hecho["backup"]["slug"], SLUG)

    async def test_plazo_agotado_con_sent_true(self) -> None:
        # Contrato de `sent` de la 022/031 (el cliente marca `True` tras enviar).
        hecho = await self._desinstalar_con(HAConnectionError("Timeout", sent=True))
        self.assertEqual((hecho["error"], hecho["sent"]), ("outcome_unknown", True))

    async def test_plazo_agotado_timeouterror(self) -> None:
        hecho = await self._desinstalar_con(TimeoutError())
        self.assertEqual(hecho["error"], "outcome_unknown")

    # Cierre de robustez 1.2.0: el plazo agotado sale del cliente como
    # `HATimeoutError` (`HAConnectionError` y `TimeoutError` a la vez, `sent`
    # en `None`). Tiene que seguir leyéndose como plazo, no como error. Aquí
    # también pasaría sin `TimeoutError` en sus bases (sin `status` ni `code`
    # ya se lee como corte); el control negativo de esa herencia lo dan
    # `sv_update_core` y `ha_install_update`.
    async def test_plazo_agotado_con_el_plazo_del_cliente(self) -> None:
        hecho = await self._desinstalar_con(HATimeoutError("plazo"))
        self.assertEqual(hecho["error"], "outcome_unknown")
        self.assertIsNone(hecho["sent"])

    async def test_no_enviado_no_es_desconocido(self) -> None:
        hecho = await self._desinstalar_con(HAConnectionError("no salió", sent=False))
        self.assertEqual(hecho["error"], "ha_error")
        self.assertIs(hecho["sent"], False)

    async def test_error_de_ha_no_es_desconocido(self) -> None:
        hecho = await self._desinstalar_con(error("uninstall_failed", "Uninstall failed"))
        self.assertEqual(hecho["error"], "uninstall_failed")
        self.assertNotIn("sent", hecho)


if __name__ == "__main__":
    unittest.main()
