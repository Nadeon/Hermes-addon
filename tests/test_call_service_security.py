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


if __name__ == "__main__":
    unittest.main()
