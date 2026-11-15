"""Tests de seguridad para ha_call_service — denylist, sanitización,
auto-clasificación."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "hermes" / "src"))

import hermes.fs as fs_module
from hermes.service_policy import targets_restricted_entity
from hermes.tools.ha import (
    CALL_SERVICE_DENYLIST,
    _auto_restricted,
    _is_in_denylist,
    auto_classify_dangerous,
    get_auto_restricted_entities,
    sanitize_service_data,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _make_ha_client(call_result: object = None) -> MagicMock:
    client = MagicMock()
    client.is_ready = True
    client.call_service = AsyncMock(return_value=call_result or {"result": "ok"})
    client.call_service_response = AsyncMock(return_value={"result": "ok"})
    client.get_states = AsyncMock(return_value=[])
    client.get_state = AsyncMock(return_value={})
    client.get_services = AsyncMock(return_value={})
    client.fire_event = AsyncMock(return_value={})

    # Spec 026, T032: `switch|homeassistant.turn_on…` lee el registro para
    # saber si alcanza un interruptor «pre-release» del Marketplace. Aquí no
    # hay ninguno (formas reales: `list_for_display` da `entities` con `ei` y
    # `pl`; `get_entries` un dict por entity_id).
    async def _registro(payload: dict, timeout_seconds: int = 30) -> object:
        if payload.get("type") == "config/entity_registry/list_for_display":
            return {"entity_categories": {}, "entities": []}
        if payload.get("type") == "config/entity_registry/get_entries":
            return {eid: None for eid in payload.get("entity_ids", [])}
        raise AssertionError(f"unexpected ws_send: {payload.get('type')}")

    client.ws_send = AsyncMock(side_effect=_registro)
    return client


def _register_ha_tools(ha_client: object = None, **kwargs) -> dict:
    from hermes.tools.ha import register
    if ha_client is None:
        ha_client = _make_ha_client()
    mcp = DummyMCP()
    # Patch requires_ready to be a passthrough
    with patch("hermes.tools.ha.requires_ready", return_value=lambda fn: fn):
        register(mcp, ha_client, **kwargs)
    return mcp.tools


# ══════════════════════════════════════════════════════════════════════════════
# 1. Denylist patterns
# ══════════════════════════════════════════════════════════════════════════════

class TestDenylistPatterns(unittest.TestCase):
    def test_homeassistant_restart_in_denylist(self) -> None:
        self.assertTrue(_is_in_denylist("homeassistant", "restart", CALL_SERVICE_DENYLIST))

    def test_shell_command_wildcard(self) -> None:
        self.assertTrue(_is_in_denylist("shell_command", "my_script", CALL_SERVICE_DENYLIST))
        self.assertTrue(_is_in_denylist("shell_command", "another_cmd", CALL_SERVICE_DENYLIST))

    def test_python_script_wildcard(self) -> None:
        self.assertTrue(_is_in_denylist("python_script", "my_script", CALL_SERVICE_DENYLIST))

    def test_lock_unlock_in_denylist(self) -> None:
        self.assertTrue(_is_in_denylist("lock", "unlock", CALL_SERVICE_DENYLIST))

    def test_alarm_disarm_in_denylist(self) -> None:
        self.assertTrue(
            _is_in_denylist("alarm_control_panel", "alarm_disarm", CALL_SERVICE_DENYLIST)
        )

    def test_recorder_purge_in_denylist(self) -> None:
        self.assertTrue(_is_in_denylist("recorder", "purge", CALL_SERVICE_DENYLIST))

    def test_light_turn_on_not_in_denylist(self) -> None:
        self.assertFalse(_is_in_denylist("light", "turn_on", CALL_SERVICE_DENYLIST))

    def test_switch_toggle_not_in_denylist(self) -> None:
        self.assertFalse(_is_in_denylist("switch", "toggle", CALL_SERVICE_DENYLIST))

    def test_mqtt_publish_in_denylist(self) -> None:
        self.assertTrue(_is_in_denylist("mqtt", "publish", CALL_SERVICE_DENYLIST))

    def test_backup_create_in_denylist(self) -> None:
        self.assertTrue(_is_in_denylist("backup", "create", CALL_SERVICE_DENYLIST))

    def test_automation_reload_in_denylist(self) -> None:
        self.assertTrue(_is_in_denylist("automation", "reload", CALL_SERVICE_DENYLIST))


# ══════════════════════════════════════════════════════════════════════════════
# 2. ha_call_service requires token for denylist services
# ══════════════════════════════════════════════════════════════════════════════

class TestCallServiceDenylist(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.ha_client = _make_ha_client()
        self.tools = _register_ha_tools(self.ha_client)

    async def test_homeassistant_restart_requires_token(self) -> None:
        result = await self.tools["ha_call_service"](
            domain="homeassistant",
            service="restart",
        )
        # Should return a confirmation_token, not call the service
        self.assertIn("confirmation_token", result)
        self.ha_client.call_service.assert_not_called()

    async def test_shell_command_requires_token(self) -> None:
        result = await self.tools["ha_call_service"](
            domain="shell_command",
            service="my_script",
        )
        self.assertIn("confirmation_token", result)
        self.ha_client.call_service.assert_not_called()

    async def test_light_turn_on_no_token_needed(self) -> None:
        result = await self.tools["ha_call_service"](
            domain="light",
            service="turn_on",
            service_data={"entity_id": "light.kitchen"},
        )
        # Should call the service directly
        self.ha_client.call_service.assert_called_once()

    async def test_denylist_with_wrong_token_rejected(self) -> None:
        result = await self.tools["ha_call_service"](
            domain="homeassistant",
            service="restart",
            confirmation_token="invalid-token-xyz",
        )
        self.assertIn("error", result)

    async def test_denylist_extra_from_config(self) -> None:
        tools = _register_ha_tools(
            call_service_denylist_extra=["custom_domain.dangerous_service"]
        )
        result = await tools["ha_call_service"](
            domain="custom_domain",
            service="dangerous_service",
        )
        self.assertIn("confirmation_token", result)


_SLUG_PROPIO = "a1b2c3d4_hermes"


def _cliente_con_registro(registro: dict, slug: object = _SLUG_PROPIO) -> MagicMock:
    """Cliente simulado con registro de entidades (`get_entries`) y
    `/addons/self/info`. `registro` es `{entity_id: entrada}`; una entidad
    ausente sale como `None`, igual que en Core. `slug` puede ser una
    excepción (slug propio ilegible)."""
    client = _make_ha_client()

    async def ws_send(payload: dict, timeout_seconds: int = 30) -> object:
        client.ws_llamadas.append(payload)
        if isinstance(registro, BaseException):
            raise registro
        return {e: registro.get(e) for e in payload["entity_ids"]}

    async def sv_request(method: str, path: str, **kw: object) -> object:
        if isinstance(slug, BaseException):
            raise slug
        return {"slug": slug}

    client.ws_llamadas = []
    client.ws_send = ws_send
    client.sv_request = sv_request
    return client


def _hassio(unique_id: str) -> dict:
    return {"platform": "hassio", "unique_id": unique_id}


class TestUpdateInstallPorCallService(unittest.IsolatedAsyncioTestCase):
    """Spec 015, T051 (decisión del supervisor sobre el H5 de la revisión):
    `ha_call_service("update", "install", …)` ya no salta D-1 ni D-3.

    - objetivo que no es una lista explícita de `entity_id` → rechazo sin
      token (`use_dedicated_tool` hacia `ha_install_update`);
    - la entidad de Hermes (registro: `hassio` + `<slug propio>_version_latest`)
      → `self_update_not_supported`; una de `hassio` con el slug propio
      ilegible → `self_check_unavailable`;
    - Core, OS y Supervisor → `use_dedicated_tool` hacia su `sv_*`;
    - el resto (otras apps, firmware…) sigue como en la 1.1.2.

    Todo se comprueba en la vista previa Y en la confirmación, y nunca se
    llama a `call_service`. Controles negativos (comprobados): (a) quitar la
    llamada a `comprobar_update_install` de `ha_call_service` → todos los
    rechazos en rojo (sale token); (b) aceptar `area_id` en
    `_entidades_explicitas` → `test_objetivo_indirecto` en rojo; (c) no
    comprobar en la confirmación → `test_registro_cambia_antes_de_confirmar`
    en rojo.
    """

    def setUp(self) -> None:
        import hermes.security as security

        self.tmp = tempfile.TemporaryDirectory()
        self._parche = patch.object(security, "CONFIRMATIONS_DIR", Path(self.tmp.name))
        self._parche.start()
        self.registro = {
            "update.hermes_renombrada": _hassio(f"{_SLUG_PROPIO}_version_latest"),
            "update.core_renombrada": _hassio("home_assistant_core_version_latest"),
            "update.os_renombrada": _hassio("home_assistant_os_version_latest"),
            "update.sup_renombrada": _hassio("home_assistant_supervisor_version_latest"),
            "update.otra_app": _hassio("b0c1d2e3_ejemplo_version_latest"),
            "update.otro_hermes": _hassio("b9c8d7e6_hermes_version_latest"),
            "update.hassio_rara": _hassio("algo_desconocido"),
            "update.firmware": {"platform": "zha", "unique_id": "x"},
        }

    def tearDown(self) -> None:
        self._parche.stop()
        self.tmp.cleanup()

    def herramientas(self, **kw: object) -> tuple[MagicMock, dict]:
        cliente = _cliente_con_registro(kw.pop("registro", self.registro), **kw)
        return cliente, _register_ha_tools(cliente)

    async def rechazo(self, datos: dict, error: str, **kw: object) -> dict:
        cliente, tools = self.herramientas(**kw)
        r = await tools["ha_call_service"](domain="update", service="install",
                                           service_data=datos)
        self.assertEqual(r.get("error"), error, r)
        self.assertNotIn("confirmation_token", r)
        # Ni con un token: se rechaza antes de mirarlo.
        r2 = await tools["ha_call_service"](domain="update", service="install",
                                            service_data=datos,
                                            confirmation_token="x" * 32)
        self.assertEqual(r2.get("error"), error, r2)
        cliente.call_service.assert_not_called()
        return r

    async def test_objetivo_indirecto(self) -> None:
        for datos in ({"area_id": "salon"}, {"device_id": "abc"}, {"label_id": "l"},
                      {"floor_id": "p"}, {"entity_id": "all"}, {"entity_id": "none"},
                      {}, {"target": {"area_id": "salon"}},
                      {"entity_id": "update.firmware", "area_id": "salon"},
                      {"target": {"entity_id": "update.firmware", "device_id": "d"}},
                      {"target": "update.firmware"}, {"entity_id": 5},
                      {"entity_id": ["update.firmware", 3]}, {"entity_id": " , "}):
            with self.subTest(datos=datos):
                r = await self.rechazo(datos, "use_dedicated_tool")
                self.assertEqual(r["tool"], "ha_install_update")

    async def test_hermes(self) -> None:
        for datos in ({"entity_id": "update.hermes_renombrada"},
                      {"entity_id": "update.firmware, UPDATE.HERMES_RENOMBRADA"},
                      {"target": {"entity_id": ["update.hermes_renombrada"]}},
                      # Hermes manda aunque haya otra que se remitiría.
                      {"entity_id": ["update.core_renombrada", "update.hermes_renombrada"]}):
            with self.subTest(datos=datos):
                r = await self.rechazo(datos, "self_update_not_supported")
                self.assertEqual(r["entity_id"], "update.hermes_renombrada")
                self.assertIn("Home Assistant UI", r["detail"])

    async def test_slug_propio_ilegible(self) -> None:
        for eid in ("update.hermes_renombrada", "update.otra_app"):
            with self.subTest(eid=eid):
                await self.rechazo({"entity_id": eid}, "self_check_unavailable",
                                   slug=ConnectionError("sin supervisor"))

    async def test_core_os_supervisor_a_su_tool(self) -> None:
        for eid, tool in (("update.core_renombrada", "sv_update_core"),
                          ("update.os_renombrada", "sv_update_os"),
                          ("update.sup_renombrada", "sv_update_supervisor")):
            with self.subTest(eid=eid):
                r = await self.rechazo({"entity_id": [eid, "update.firmware"]},
                                       "use_dedicated_tool")
                self.assertEqual((r["tool"], r["entity_id"]), (tool, eid))

    async def test_hassio_no_reconocida(self) -> None:
        await self.rechazo({"entity_id": "update.hassio_rara"}, "unsupported_entity")

    async def test_registro_ilegible(self) -> None:
        await self.rechazo({"entity_id": "update.firmware"}, "registry_unavailable",
                           registro=ConnectionError("caído"))

    async def test_el_resto_como_en_la_1_1_2(self) -> None:
        for datos in ({"entity_id": "update.firmware"},
                      {"entity_id": ["update.firmware", "update.otra_app"], "backup": True},
                      # Otra app con sufijo `_hermes`: no es Hermes.
                      {"entity_id": "update.otro_hermes"},
                      # Fuera del registro: no es de `hassio`.
                      {"target": {"entity_id": "update.sin_registro"}}):
            with self.subTest(datos=datos):
                cliente, tools = self.herramientas()
                r = await tools["ha_call_service"](domain="update", service="install",
                                                   service_data=datos)
                self.assertIn("confirmation_token", r)
                r = await tools["ha_call_service"](
                    domain="update", service="install", service_data=datos,
                    confirmation_token=r["confirmation_token"])
                self.assertEqual(r, {"result": "ok"})
                cliente.call_service.assert_awaited_once_with(
                    "update", "install", datos, allow_dangerous=True)

    async def test_registro_cambia_antes_de_confirmar(self) -> None:
        # Se comprueba otra vez al confirmar: el registro manda en ese momento.
        registro = dict(self.registro)
        cliente, tools = self.herramientas(registro=registro)
        datos = {"entity_id": "update.firmware"}
        r = await tools["ha_call_service"](domain="update", service="install",
                                           service_data=datos)
        registro["update.firmware"] = _hassio(f"{_SLUG_PROPIO}_version_latest")
        r = await tools["ha_call_service"](domain="update", service="install",
                                           service_data=datos,
                                           confirmation_token=r["confirmation_token"])
        self.assertEqual(r["error"], "self_update_not_supported")
        cliente.call_service.assert_not_called()

    async def test_otros_servicios_no_leen_el_registro(self) -> None:
        cliente, tools = self.herramientas()
        await tools["ha_call_service"](domain="update", service="skip",
                                       service_data={"area_id": "salon"})
        await tools["ha_call_service"](domain="light", service="turn_on",
                                       service_data={"entity_id": "light.salon"})
        self.assertEqual(cliente.ws_llamadas, [])

    async def test_call_service_response_no_admite_update_install(self) -> None:
        # T051, punto 7: `ha_call_service_response` rechaza la denylist sin
        # flujo de token, y `update.install` está en la denylist base, que la
        # configuración solo puede ampliar.
        cliente, tools = self.herramientas()
        r = await tools["ha_call_service_response"](
            domain="update", service="install",
            service_data={"entity_id": "update.hermes_renombrada"})
        self.assertEqual(r["error"], "service_in_denylist")
        cliente.call_service_response.assert_not_called()


class TestHintUpdateInstall(unittest.IsolatedAsyncioTestCase):
    """Spec 015, FR-015 (T037): `ha_call_service("update", "install", …)` no
    cambia de comportamiento (sigue pidiendo token y, con él, llama igual que
    en la 1.1.2); solo su vista previa gana una `hint` hacia
    `ha_install_update`, que enseña versiones, notas y backup.

    Control negativo (T045 f): sin la `hint` cae `test_vista_previa_con_hint`.
    """

    def setUp(self) -> None:
        import hermes.security as security

        self.tmp = tempfile.TemporaryDirectory()
        self._parche = patch.object(security, "CONFIRMATIONS_DIR", Path(self.tmp.name))
        self._parche.start()
        self.ha_client = _cliente_con_registro({})
        self.tools = _register_ha_tools(self.ha_client)
        self.datos = {"entity_id": "update.firmware_ficticio"}

    def tearDown(self) -> None:
        self._parche.stop()
        self.tmp.cleanup()

    async def test_vista_previa_con_hint(self) -> None:
        r = await self.tools["ha_call_service"](
            domain="update", service="install", service_data=self.datos)
        self.assertIn("confirmation_token", r)
        self.assertIn("ha_install_update", r["preview"]["hint"])
        self.assertEqual(r["preview"]["service"], "install")
        self.ha_client.call_service.assert_not_called()

    async def test_con_token_igual_que_en_la_1_1_2(self) -> None:
        r = await self.tools["ha_call_service"](
            domain="update", service="install", service_data=self.datos)
        r = await self.tools["ha_call_service"](
            domain="update", service="install", service_data=self.datos,
            confirmation_token=r["confirmation_token"])
        self.assertEqual(r, {"result": "ok"})
        self.ha_client.call_service.assert_awaited_once_with(
            "update", "install", self.datos, allow_dangerous=True)

    async def test_otro_servicio_sin_hint(self) -> None:
        for dominio, servicio in (("homeassistant", "restart"), ("update", "skip")):
            with self.subTest(servicio=f"{dominio}.{servicio}"):
                r = await self.tools["ha_call_service"](domain=dominio, service=servicio)
                if "preview" in r:
                    self.assertNotIn("hint", r["preview"])


# ══════════════════════════════════════════════════════════════════════════════
# 3. Sanitización de service_data
# ══════════════════════════════════════════════════════════════════════════════

class TestSanitizeServiceData(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.config_root = Path(self._tmpdir) / "config"
        self.config_root.mkdir()
        self._patcher = patch.object(fs_module, "CONFIG_BASE", self.config_root.resolve())
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_safe_data_passes(self) -> None:
        ok, err = sanitize_service_data({"entity_id": "light.kitchen", "brightness": 100})
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_file_path_to_secrets_rejected(self) -> None:
        ok, err = sanitize_service_data({"file": "secrets.yaml"})
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_nested_photo_to_secrets_rejected(self) -> None:
        ok, err = sanitize_service_data({
            "data": {
                "photo": "secrets.yaml",
            }
        })
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_deep_nested_attachment_to_secrets_rejected(self) -> None:
        ok, err = sanitize_service_data({
            "data": {
                "inner": {
                    "attachment": "secrets.yaml",
                }
            }
        })
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_list_with_photo_to_secrets_rejected(self) -> None:
        ok, err = sanitize_service_data({
            "attachments": [
                {"file": "secrets.yaml"}
            ]
        })
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_depth_limit(self) -> None:
        # Deeply nested but safe
        deep = {}
        current = deep
        for i in range(12):
            current["nested"] = {}
            current = current["nested"]
        current["file"] = "secrets.yaml"
        ok, err = sanitize_service_data(deep)
        # Should be rejected due to depth limit
        self.assertFalse(ok)

    async def test_unsafe_data_rejected_by_ha_call_service(self) -> None:
        ha_client = _make_ha_client()
        tools = _register_ha_tools(ha_client)

        result = await tools["ha_call_service"](
            domain="notify",
            service="telegram",
            service_data={"file": "secrets.yaml"},
        )
        self.assertEqual(result.get("error"), "unsafe_service_data")
        ha_client.call_service.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# 4. Auto-clasificación de scripts/automations peligrosos
# ══════════════════════════════════════════════════════════════════════════════

class TestAutoClassification(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.config_root = Path(self._tmpdir) / "config"
        self.config_root.mkdir()
        self._patcher = patch.object(fs_module, "CONFIG_BASE", self.config_root.resolve())
        self._patcher.start()
        # Clear auto_restricted set
        _auto_restricted.clear()

    def tearDown(self) -> None:
        self._patcher.stop()
        _auto_restricted.clear()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    async def test_script_with_shell_command_marked_restricted(self) -> None:
        scripts_yaml = self.config_root / "scripts.yaml"
        scripts_yaml.write_text(
            """
my_dangerous_script:
  alias: Dangerous Script
  sequence:
    - service: shell_command.run_something
      data: {}
""",
            encoding="utf-8",
        )

        restricted = await auto_classify_dangerous(CALL_SERVICE_DENYLIST)
        self.assertIn("script.my_dangerous_script", restricted)
        self.assertIn("script.my_dangerous_script", get_auto_restricted_entities())

    async def test_safe_script_not_restricted(self) -> None:
        scripts_yaml = self.config_root / "scripts.yaml"
        scripts_yaml.write_text(
            """
my_safe_script:
  alias: Safe Script
  sequence:
    - service: light.turn_on
      data:
        entity_id: light.kitchen
""",
            encoding="utf-8",
        )

        restricted = await auto_classify_dangerous(CALL_SERVICE_DENYLIST)
        self.assertNotIn("script.my_safe_script", restricted)

    async def test_script_with_service_template_marked_restricted(self) -> None:
        scripts_yaml = self.config_root / "scripts.yaml"
        scripts_yaml.write_text(
            """
template_script:
  alias: Template Script
  sequence:
    - service_template: "{{ 'shell_command.' + states('input_text.cmd') }}"
""",
            encoding="utf-8",
        )

        restricted = await auto_classify_dangerous(CALL_SERVICE_DENYLIST)
        self.assertIn("script.template_script", restricted)

    async def test_automation_with_dangerous_service_restricted(self) -> None:
        automations_yaml = self.config_root / "automations.yaml"
        automations_yaml.write_text(
            """
- id: "dangerous_auto"
  alias: Dangerous Automation
  trigger: []
  action:
    - service: homeassistant.restart
""",
            encoding="utf-8",
        )

        restricted = await auto_classify_dangerous(CALL_SERVICE_DENYLIST)
        # Should have automation entity
        automation_entities = [e for e in restricted if e.startswith("automation.")]
        self.assertGreater(len(automation_entities), 0)

    async def test_script_alias_service_requires_token(self) -> None:
        """HA registra un servicio `script.<object_id>` por script: llamarlo no
        lleva entity_id, y así un script clasificado como peligroso se
        ejecutaba sin token."""
        _auto_restricted.add("script.dangerous_script")
        ha_client = _make_ha_client()
        tools = _register_ha_tools(ha_client, call_service_auto_classify=False)

        result = await tools["ha_call_service"](domain="script", service="dangerous_script")
        self.assertIn("confirmation_token", result)
        ha_client.call_service.assert_not_called()

    async def test_homeassistant_turn_on_all_requires_token(self) -> None:
        _auto_restricted.add("script.dangerous_script")
        ha_client = _make_ha_client()
        tools = _register_ha_tools(ha_client, call_service_auto_classify=False)

        result = await tools["ha_call_service"](
            domain="homeassistant", service="turn_on", service_data={"entity_id": "all"}
        )
        self.assertIn("confirmation_token", result)
        ha_client.call_service.assert_not_called()

    async def test_response_tool_refuses_restricted_script(self) -> None:
        """`ha_call_service_response` no consultaba las entidades restringidas."""
        _auto_restricted.add("script.dangerous_script")
        ha_client = _make_ha_client()
        tools = _register_ha_tools(ha_client, call_service_auto_classify=False)

        result = await tools["ha_call_service_response"](
            domain="script", service="dangerous_script"
        )
        self.assertEqual(result.get("error"), "entity_restricted")
        ha_client.call_service_response.assert_not_called()

    async def test_auto_restricted_entity_requires_token(self) -> None:
        # Mark an entity as restricted
        _auto_restricted.add("script.dangerous_script")

        ha_client = _make_ha_client()
        tools = _register_ha_tools(
            ha_client,
            call_service_restricted_entities=["script.dangerous_script"],
            call_service_auto_classify=False,
        )

        result = await tools["ha_call_service"](
            domain="script",
            service="turn_on",
            service_data={"entity_id": "script.dangerous_script"},
        )
        self.assertIn("confirmation_token", result)
        ha_client.call_service.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# 5. ha_call_service_response: denylist → hint to use ha_call_service
# ══════════════════════════════════════════════════════════════════════════════

class TestClasificacionSinEntityId(unittest.IsolatedAsyncioTestCase):
    """FR-003 (009): la clasificación automática no escribe `entity_id` al log.

    El log se pega en issues públicos y el id de una automatización sale de su
    alias, que nombra la casa. La restricción sigue funcionando igual.

    Control negativo (T015): con `new=new_entities` de vuelta en
    `auto_classify_restricted`, cae `test_escaneo_sin_entity_id`; con
    `entity_id=entity_id` en `auto_classify_on_save`, cae
    `test_al_guardar_sin_entity_id`.
    """

    CENTINELA = "automation.ficticia"

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.config_root = Path(self._tmpdir) / "config"
        self.config_root.mkdir()
        self._patcher = patch.object(fs_module, "CONFIG_BASE", self.config_root.resolve())
        self._patcher.start()
        _auto_restricted.clear()

    def tearDown(self) -> None:
        self._patcher.stop()
        _auto_restricted.clear()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _sin_centinela(self, eventos: list[dict]) -> None:
        texto = json.dumps(eventos, default=str)
        self.assertNotIn(self.CENTINELA, texto)
        self.assertNotIn("ficticia", texto)

    async def test_escaneo_sin_entity_id(self) -> None:
        from structlog.testing import capture_logs

        (self.config_root / "automations.yaml").write_text(
            """
- id: "1700000000000"
  alias: Ficticia
  trigger: []
  action:
    - service: shell_command.algo
""",
            encoding="utf-8",
        )
        with capture_logs() as eventos:
            restricted = await auto_classify_dangerous(CALL_SERVICE_DENYLIST)
        self.assertIn(self.CENTINELA, restricted)
        self.assertIn(self.CENTINELA, get_auto_restricted_entities())
        ev = [e for e in eventos if e.get("event") == "auto_classify_restricted"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["count"], len(restricted))
        self.assertEqual(ev[0]["new_count"], len(restricted))
        self.assertNotIn("new", ev[0])
        self._sin_centinela(eventos)

    async def test_al_guardar_sin_entity_id(self) -> None:
        from structlog.testing import capture_logs

        from hermes.tools.ha import classify_saved_config

        config = {
            "alias": "Ficticia",
            "triggers": [],
            "actions": [{"action": "shell_command.algo"}],
        }
        with capture_logs() as eventos:
            self.assertTrue(classify_saved_config(self.CENTINELA, config))
        self.assertIn(self.CENTINELA, get_auto_restricted_entities())
        ev = [e for e in eventos if e.get("event") == "auto_classify_on_save"]
        self.assertEqual(len(ev), 1)
        self.assertIs(ev[0]["restricted"], True)
        self.assertEqual(ev[0]["count"], 1)
        self.assertNotIn("entity_id", ev[0])
        self._sin_centinela(eventos)


class TestCallServiceResponseDenylist(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.ha_client = _make_ha_client()
        self.tools = _register_ha_tools(self.ha_client)

    async def test_denylist_service_rejected_in_response_tool(self) -> None:
        result = await self.tools["ha_call_service_response"](
            domain="homeassistant",
            service="restart",
        )
        self.assertEqual(result.get("error"), "service_in_denylist")
        self.ha_client.call_service_response.assert_not_called()

    async def test_safe_service_allowed_in_response_tool(self) -> None:
        result = await self.tools["ha_call_service_response"](
            domain="weather",
            service="get_forecasts",
            service_data={"entity_id": "weather.home", "type": "daily"},
        )
        self.ha_client.call_service_response.assert_called_once()



# ══════════════════════════════════════════════════════════════════════════════
# 6. targets_restricted_entity: alias por servicio y dominio homeassistant
# ══════════════════════════════════════════════════════════════════════════════

class TestTargetsRestrictedEntity(unittest.TestCase):
    R = frozenset({"script.evil", "automation.evil"})

    def test_script_alias_service_is_the_target(self) -> None:
        self.assertTrue(targets_restricted_entity("script", {}, self.R, service="evil"))
        self.assertTrue(targets_restricted_entity("Script", {}, self.R, service=" Evil "))
        self.assertFalse(targets_restricted_entity("script", {}, self.R, service="benign"))

    def test_homeassistant_fanout_reaches_every_domain(self) -> None:
        self.assertTrue(targets_restricted_entity(
            "homeassistant", {"entity_id": "all"}, self.R, service="turn_on"))
        self.assertTrue(targets_restricted_entity(
            "homeassistant", {"area_id": "salon"}, self.R, service="turn_off"))
        self.assertTrue(targets_restricted_entity(
            "homeassistant", {"target": {"device_id": "abc"}}, self.R, service="toggle"))
        self.assertFalse(targets_restricted_entity(
            "homeassistant", {"entity_id": "light.x"}, self.R, service="turn_on"))

    def test_unrelated_domain_stays_free(self) -> None:
        self.assertFalse(targets_restricted_entity(
            "light", {"entity_id": "all"}, self.R, service="turn_on"))
        self.assertFalse(targets_restricted_entity(
            "light", {"area_id": "salon"}, self.R, service="turn_on"))

    def test_without_service_argument_behaviour_is_unchanged(self) -> None:
        self.assertTrue(targets_restricted_entity(
            "script", {"entity_id": "script.evil"}, self.R))
        self.assertTrue(targets_restricted_entity(
            "script", {"entity_id": "all"}, self.R))
        self.assertFalse(targets_restricted_entity("script", {}, self.R))


# ══════════════════════════════════════════════════════════════════════════════
# 7. ha_call_service_response con confirmation_token (spec 018, US2)
# ══════════════════════════════════════════════════════════════════════════════

# Centinela en la respuesta simulada de HA: no puede acabar en el fichero del
# token (`/data` entra en los backups del add-on; principio II).
_CENTINELA_RESPUESTA = "centinela-respuesta-018"


class TestCallServiceResponseConfirmacion(unittest.IsolatedAsyncioTestCase):
    """FR-008…FR-010 de la 018: la denylist y las entidades restringidas piden
    token también en `ha_call_service_response`.

    Sin token, la respuesta de la 1.1.2 (`error` y `hint`) MÁS el token y la
    vista previa (aditivo: un cliente de la 1.1.2 sigue viendo un rechazo).
    Con token, se ejecuta una vez y se devuelve la respuesta de HA tal cual;
    en el fichero del token solo queda `{"called": true}`.

    Control negativo (T023), con los fallos de este fichero:
    (a) ejecutar a la primera aunque esté en la denylist → 11 (los 8 de aquí
    que esperan «no llamado» o un token, los dos de la 1.1.2
    `test_denylist_service_rejected_in_response_tool` y
    `test_response_tool_refuses_restricted_script`, y
    `test_la_tool_confirmada_pasa_la_guarda`, donde la guarda del cliente
    para la llamada: la defensa en profundidad hace su trabajo);
    (b) atar el token a `ha_call_service` → cae `test_tokens_cruzados`;
    (c) guardar la respuesta en `cached_result` → cae
    `test_el_fichero_del_token_no_guarda_la_respuesta`;
    (g) confirmar sin `allow_dangerous=True` → caen
    `test_confirmado_autoriza_la_capa_de_cliente` y, con el cliente real,
    `TestGuardaDeClienteConRespuesta.test_la_tool_confirmada_pasa_la_guarda`.
    """

    ARGS = {"domain": "conversation", "service": "process",
            "service_data": {"text": "turn on the kitchen light", "language": "en"}}

    async def asyncSetUp(self) -> None:
        import hermes.security as security

        self._security = security
        self._dir_original = security.CONFIRMATIONS_DIR
        self._tmp = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self._tmp.name)
        _auto_restricted.clear()
        self.ha_client = _make_ha_client()
        self.respuesta_ha = {
            "changed_states": [],
            "service_response": {"response": {"response_type": "action_done",
                                              "speech": _CENTINELA_RESPUESTA}},
        }
        self.ha_client.call_service_response = AsyncMock(return_value=self.respuesta_ha)
        self.tools = _register_ha_tools(self.ha_client, call_service_auto_classify=False)

    async def asyncTearDown(self) -> None:
        self._security.CONFIRMATIONS_DIR = self._dir_original
        self._tmp.cleanup()
        _auto_restricted.clear()

    def _fichero(self, token: str) -> dict:
        ruta = self._security.CONFIRMATIONS_DIR / f"{token}.json"
        return json.loads(ruta.read_text(encoding="utf-8"))

    async def test_sin_token_no_ejecuta_y_da_token(self) -> None:
        res = await self.tools["ha_call_service_response"](**self.ARGS)
        self.assertEqual(res["error"], "service_in_denylist")
        self.assertIn("confirmation_token", res["hint"])
        self.assertIsInstance(res["confirmation_token"], str)
        self.assertGreater(res["expires_in_seconds"], 0)
        self.ha_client.call_service_response.assert_not_called()
        self.ha_client.call_service.assert_not_called()
        # La vista previa es la de ha_call_service salvo `action`.
        de_cs = await self.tools["ha_call_service"](**self.ARGS)
        self.assertEqual(res["preview"], dict(de_cs["preview"], action="call_service_response"))
        self.assertEqual(
            res["preview"],
            {"action": "call_service_response", "domain": "conversation",
             "service": "process", "service_data": self.ARGS["service_data"],
             "reason": "Service 'conversation.process' requires confirmation "
                       "(denylist match)."},
        )
        self.ha_client.call_service.assert_not_called()

    async def test_confirmado_ejecuta_una_vez_y_devuelve_la_respuesta(self) -> None:
        vista = await self.tools["ha_call_service_response"](**self.ARGS)
        token = vista["confirmation_token"]
        res = await self.tools["ha_call_service_response"](
            **self.ARGS, confirmation_token=token)
        self.assertIs(res, self.respuesta_ha)
        self.ha_client.call_service_response.assert_called_once()
        # Una segunda confirmación con el mismo token no vuelve a llamar.
        otra = await self.tools["ha_call_service_response"](
            **self.ARGS, confirmation_token=token)
        self.assertIn("already used", otra["error"])
        self.ha_client.call_service_response.assert_called_once()

    async def test_confirmado_autoriza_la_capa_de_cliente(self) -> None:
        """La tool le dice al cliente que la llamada ya está confirmada: sin
        eso, la guarda de denylist de `HAClient.call_service_response` la
        rechazaría."""
        vista = await self.tools["ha_call_service_response"](**self.ARGS)
        await self.tools["ha_call_service_response"](
            **self.ARGS, confirmation_token=vista["confirmation_token"])
        self.ha_client.call_service_response.assert_called_once_with(
            "conversation", "process", self.ARGS["service_data"], allow_dangerous=True)

    async def test_fuera_de_denylist_no_autoriza_la_capa_de_cliente(self) -> None:
        """Ni con un token cualquiera: fuera de la denylist se llama a la
        primera y sin `allow_dangerous` (el token se ignora)."""
        args = {"domain": "weather", "service": "get_forecasts",
                "service_data": {"entity_id": "weather.casa", "type": "daily"}}
        res = await self.tools["ha_call_service_response"](
            **args, confirmation_token="00000000-0000-4000-8000-000000000000")
        self.assertIs(res, self.respuesta_ha)
        self.ha_client.call_service_response.assert_called_once_with(
            "weather", "get_forecasts", args["service_data"])

    async def test_otros_datos_rechazan(self) -> None:
        vista = await self.tools["ha_call_service_response"](**self.ARGS)
        res = await self.tools["ha_call_service_response"](
            domain="conversation", service="process",
            service_data={"text": "unlock the front door", "language": "en"},
            confirmation_token=vista["confirmation_token"])
        self.assertIn("does not match", res["error"])
        self.ha_client.call_service_response.assert_not_called()

    async def test_tokens_cruzados(self) -> None:
        # Token de ha_call_service usado aquí.
        de_cs = await self.tools["ha_call_service"](**self.ARGS)
        res = await self.tools["ha_call_service_response"](
            **self.ARGS, confirmation_token=de_cs["confirmation_token"])
        self.assertIn("does not match", res["error"])
        self.ha_client.call_service_response.assert_not_called()
        # Token de aquí usado en ha_call_service.
        de_csr = await self.tools["ha_call_service_response"](**self.ARGS)
        res = await self.tools["ha_call_service"](
            **self.ARGS, confirmation_token=de_csr["confirmation_token"])
        self.assertIn("does not match", res["error"])
        self.ha_client.call_service.assert_not_called()
        self.ha_client.call_service_response.assert_not_called()

    async def test_entidad_restringida_pide_token(self) -> None:
        _auto_restricted.add("script.peligroso")
        args = {"domain": "script", "service": "turn_on",
                "service_data": {"entity_id": "script.peligroso"}}
        res = await self.tools["ha_call_service_response"](**args)
        self.assertEqual(res["error"], "entity_restricted")
        self.assertIn("confirmation_token", res["hint"])
        self.assertEqual(res["preview"]["action"], "call_service_response")
        self.assertEqual(res["preview"]["restricted_entities"], ["script.peligroso"])
        self.assertIn("auto-restricted entity", res["preview"]["reason"])
        self.ha_client.call_service_response.assert_not_called()
        confirmado = await self.tools["ha_call_service_response"](
            **args, confirmation_token=res["confirmation_token"])
        self.assertIs(confirmado, self.respuesta_ha)
        self.ha_client.call_service_response.assert_called_once()

    async def test_datos_inseguros_sin_token(self) -> None:
        res = await self.tools["ha_call_service_response"](
            domain="conversation", service="process",
            service_data={"text": "x", "file": "secrets.yaml"})
        self.assertEqual(res["error"], "unsafe_service_data")
        self.assertNotIn("confirmation_token", res)
        self.ha_client.call_service_response.assert_not_called()

    async def test_fallo_de_ha_al_confirmar(self) -> None:
        from hermes.ha import HAConnectionError

        self.ha_client.call_service_response = AsyncMock(
            side_effect=HAConnectionError("HA caído"))
        vista = await self.tools["ha_call_service_response"](**self.ARGS)
        token = vista["confirmation_token"]
        res = await self.tools["ha_call_service_response"](
            **self.ARGS, confirmation_token=token)
        self.assertEqual(res["error"], "ha_call_service_response_failed")
        self.assertIn("HA caído", res["details"])
        self.assertEqual(self._fichero(token)["state"], "failed")

    async def test_el_fichero_del_token_no_guarda_la_respuesta(self) -> None:
        vista = await self.tools["ha_call_service_response"](**self.ARGS)
        token = vista["confirmation_token"]
        await self.tools["ha_call_service_response"](**self.ARGS, confirmation_token=token)
        datos = self._fichero(token)
        self.assertEqual(datos["state"], "completed")
        self.assertEqual(datos["cached_result"], {"called": True})
        ruta = self._security.CONFIRMATIONS_DIR / f"{token}.json"
        self.assertNotIn(_CENTINELA_RESPUESTA, ruta.read_text(encoding="utf-8"))


class TestGuardaDeClienteConRespuesta(unittest.IsolatedAsyncioTestCase):
    """Defensa en profundidad (018): `HAClient.call_service_response` tiene la
    misma guarda de denylist que `call_service`. Solo la levanta la tool, con
    un token ya validado (`allow_dangerous=True`).

    Control negativo: (f) sin la comprobación en `call_service_response`
    caen `test_servicio_vetado_no_llega_al_endpoint` y
    `test_mayusculas_y_espacios_no_la_eluden`; (g) la tool sin
    `allow_dangerous=True` → cae `test_la_tool_confirmada_pasa_la_guarda`.
    """

    class _Espia:
        def __init__(self) -> None:
            self.llegadas: list[str] = []

        async def _request_json(self, method, path, json_body=None, params=None):
            self.llegadas.append(path)
            return {"ok": True}

    async def test_servicio_vetado_no_llega_al_endpoint(self) -> None:
        from hermes.ha import HAClient
        from hermes.service_policy import DangerousServiceError

        for dominio, servicio in (("conversation", "process"), ("shell_command", "x"),
                                  ("homeassistant", "restart"), ("script", "reload")):
            espia = self._Espia()
            with self.assertRaises(DangerousServiceError, msg=f"{dominio}.{servicio}"):
                await HAClient.call_service_response(espia, dominio, servicio, None)
            self.assertEqual(espia.llegadas, [], f"{dominio}.{servicio} llegó a HA")

    async def test_mayusculas_y_espacios_no_la_eluden(self) -> None:
        from hermes.ha import HAClient
        from hermes.service_policy import DangerousServiceError

        with self.assertRaises(DangerousServiceError):
            await HAClient.call_service_response(self._Espia(), " Conversation ", "PROCESS")

    async def test_servicio_inofensivo_pasa(self) -> None:
        from hermes.ha import HAClient

        espia = self._Espia()
        await HAClient.call_service_response(espia, "weather", "get_forecasts", None)
        self.assertEqual(espia.llegadas, ["/services/weather/get_forecasts"])

    async def test_autorizacion_explicita(self) -> None:
        from hermes.ha import HAClient

        espia = self._Espia()
        await HAClient.call_service_response(
            espia, "conversation", "process", {"text": "x"}, allow_dangerous=True)
        self.assertEqual(espia.llegadas, ["/services/conversation/process"])

    async def test_la_tool_confirmada_pasa_la_guarda(self) -> None:
        """La tool con la guarda del cliente de verdad: sin token no llega a
        HA; con su token, sí, una vez. Ningún otro camino la levanta."""
        import hermes.security as security
        from hermes.ha import HAClient

        original = security.CONFIRMATIONS_DIR
        with tempfile.TemporaryDirectory() as tmp:
            security.CONFIRMATIONS_DIR = Path(tmp)
            try:
                espia = self._Espia()
                cliente = _make_ha_client()

                async def real(*a, **k):
                    return await HAClient.call_service_response(espia, *a, **k)

                cliente.call_service_response = real
                tools = _register_ha_tools(cliente, call_service_auto_classify=False)
                args = {"domain": "conversation", "service": "process",
                        "service_data": {"text": "x"}}
                vista = await tools["ha_call_service_response"](**args)
                self.assertEqual(espia.llegadas, [])
                res = await tools["ha_call_service_response"](
                    **args, confirmation_token=vista["confirmation_token"])
                self.assertEqual(res, {"ok": True})
                self.assertEqual(espia.llegadas, ["/services/conversation/process"])
            finally:
                security.CONFIRMATIONS_DIR = original


class TestClasificarAlGuardarConLaDenylistExtra(unittest.TestCase):
    """Al guardar, se clasifica con la denylist EFECTIVA (base + extra).

    `classify_saved_config` usaba solo la de base: un script que llamaba a un
    servicio vetado SOLO por `call_service_denylist_extra` se guardaba sin
    restringir, aunque `ha_call_service` sí lo vetaba (revisión de la 027).

    Control negativo comprobado: volver a `CALL_SERVICE_DENYLIST` en
    `classify_saved_config` → `test_servicio_solo_en_la_extra_se_restringe` en
    rojo.
    """

    SERVICIO = "input_boolean.turn_on"
    CONFIG = {"sequence": [{"action": "input_boolean.turn_on"}]}

    def setUp(self) -> None:
        from hermes import service_policy

        service_policy.set_auto_restricted_entities(set())
        self.assertFalse(_is_in_denylist("input_boolean", "turn_on", CALL_SERVICE_DENYLIST),
                         "el servicio de prueba tiene que estar SOLO en la extra")

    def tearDown(self) -> None:
        from hermes import service_policy

        # Deja la denylist de guardado como la de base para los demás tests.
        _register_ha_tools(call_service_auto_classify=False)
        service_policy.set_auto_restricted_entities(set())

    def test_servicio_solo_en_la_extra_se_restringe(self) -> None:
        from hermes.tools.ha import classify_saved_config

        _register_ha_tools(call_service_denylist_extra=[self.SERVICIO],
                           call_service_auto_classify=False)
        self.assertTrue(classify_saved_config("script.extra", self.CONFIG))
        self.assertIn("script.extra", get_auto_restricted_entities())

    def test_sin_la_extra_no_se_restringe(self) -> None:
        from hermes.tools.ha import classify_saved_config

        _register_ha_tools(call_service_auto_classify=False)
        self.assertFalse(classify_saved_config("script.extra", self.CONFIG))
        self.assertNotIn("script.extra", get_auto_restricted_entities())

    def test_la_base_sigue_restringiendo_con_extra(self) -> None:
        from hermes.tools.ha import classify_saved_config

        _register_ha_tools(call_service_denylist_extra=[self.SERVICIO],
                           call_service_auto_classify=False)
        self.assertTrue(classify_saved_config(
            "script.base", {"sequence": [{"action": "shell_command.algo"}]}))

if __name__ == "__main__":
    unittest.main()


class TestLecturaDelObjetivoCompartida(unittest.TestCase):
    """Integración de la 026: la guarda de `update.install` (015, T051) y la
    del interruptor «pre-release» del Marketplace (026, T032) leen el objetivo
    con UNA sola función (`leer_objetivo`), para que una misma llamada no se
    entienda de dos maneras. Fija lo que da cada forma en las dos.

    Control negativo (comprobado): quitar en `leer_objetivo` la comprobación
    de `all` → caen los dos subtests de `{"entity_id": "all"}` (y los de
    `TestUpdateInstallPorCallService.test_objetivo_indirecto`)."""

    FORMAS: tuple[tuple[dict, bool, list[str] | None], ...] = (
        # (datos, indirecto para la 026, lista explícita para la 015)
        ({"entity_id": "switch.a, SWITCH.B"}, False, ["switch.a", "switch.b"]),
        ({"target": {"entity_id": ["switch.a"]}}, False, ["switch.a"]),
        ({}, False, None),
        ({"entity_id": "none"}, False, None),
        ({"entity_id": "all"}, True, None),
        ({"entity_id": "switch.a, all"}, True, None),
        ({"area_id": "salon"}, True, None),
        ({"target": {"label_id": "l"}}, True, None),
        ({"target": "switch.a"}, True, None),
        ({"entity_id": 5}, True, None),
        ({"entity_id": ["switch.a", 3]}, True, None),
    )

    def test_las_dos_guardas_leen_igual(self) -> None:
        from hermes.tools._marketplace_write import _objetivo_indirecto
        from hermes.tools.update_entities import _entidades_explicitas, leer_objetivo

        for datos, indirecto, explicitas in self.FORMAS:
            with self.subTest(datos=datos):
                self.assertEqual(leer_objetivo(datos)[0], indirecto)
                self.assertEqual(_objetivo_indirecto(datos), indirecto)
                self.assertEqual(_entidades_explicitas(datos), explicitas)
