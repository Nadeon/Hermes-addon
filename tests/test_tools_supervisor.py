"""Tests de tool-level para hermes.tools.supervisor, addons y backups.

Usa un MockHAClient que implementa sv_request / sv_request_text.
No hace llamadas de red reales.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from hermes.ha import HAConnectionError


# ── Helpers ────────────────────────────────────────────────────────────────────


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


class MockHAClient:
    """Mock de HAClient con sv_request / sv_request_text configurables."""

    def __init__(self) -> None:
        self._sv_responses: dict[tuple, Any] = {}
        self._sv_text_responses: dict[str, str] = {}

    def set_sv_response(self, method: str, path: str, response: Any) -> None:
        self._sv_responses[(method.upper(), path)] = response

    def set_sv_text_response(self, path: str, text: str) -> None:
        self._sv_text_responses[path] = text

    async def sv_request(
        self,
        method: str,
        sv_path: str,
        json_body: Any = None,
        params: Any = None,
        timeout_seconds: float = 60.0,
    ) -> Any:
        key = (method.upper(), sv_path)
        if key in self._sv_responses:
            resp = self._sv_responses[key]
            if isinstance(resp, Exception):
                raise resp
            return resp
        # Default: not found
        raise HAConnectionError(f"MockHAClient: no response configured for {method} {sv_path}")

    async def sv_request_text(
        self,
        sv_path: str,
        params: Any = None,
        timeout_seconds: float = 60.0,
    ) -> str:
        if sv_path in self._sv_text_responses:
            return self._sv_text_responses[sv_path]
        raise HAConnectionError(f"MockHAClient: no text response for {sv_path}")

    async def wait_ready(self, timeout: float = 5.0) -> bool:
        return True


def _j(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    return json.loads(raw)


# ══════════════════════════════════════════════════════════════════════════════
# Tools de Supervisor / Host / Core
# ══════════════════════════════════════════════════════════════════════════════

class TestSupervisorInfoTools(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        from hermes.tools.supervisor import register
        self.client = MockHAClient()
        mcp = DummyMCP()
        register(mcp, self.client)
        self.tools = mcp.tools

    async def test_get_supervisor_info_ok(self) -> None:
        self.client.set_sv_response("GET", "/supervisor/info", {
            "version": "2026.04.0",
            "channel": "stable",
            "healthy": True,
            "supported": False,
            "arch": "amd64",
        })
        result = await self.tools["sv_get_supervisor_info"]()
        self.assertEqual(result["version"], "2026.04.0")
        self.assertEqual(result["channel"], "stable")
        self.assertTrue(result["healthy"])

    async def test_get_supervisor_info_error(self) -> None:
        self.client.set_sv_response("GET", "/supervisor/info", HAConnectionError("timeout"))
        result = await self.tools["sv_get_supervisor_info"]()
        self.assertIn("error", result)

    async def test_get_host_info_ok(self) -> None:
        self.client.set_sv_response("GET", "/host/info", {
            "hostname": "homeassistant",
            "operating_system": "Home Assistant OS 14.2",
            "kernel_version": "6.6.1",
            "disk_total": 60 * 1024 * 1024 * 1024,
            "disk_free": 30 * 1024 * 1024 * 1024,
        })
        result = await self.tools["sv_get_host_info"]()
        self.assertEqual(result["hostname"], "homeassistant")
        self.assertIn("operating_system", result)

    async def test_get_core_info_ok(self) -> None:
        self.client.set_sv_response("GET", "/core/info", {
            "version": "2026.4.0",
            "version_latest": "2026.4.1",
            "update_available": True,
            "state": "running",
        })
        result = await self.tools["sv_get_core_info"]()
        self.assertEqual(result["version"], "2026.4.0")
        self.assertTrue(result["update_available"])

    async def test_check_core_config_ok(self) -> None:
        self.client.set_sv_response("POST", "/core/check", {})
        result = await self.tools["sv_check_core_config"]()
        self.assertEqual(result["result"], "ok")

    async def test_check_core_config_invalid(self) -> None:
        self.client.set_sv_response(
            "POST", "/core/check",
            HAConnectionError("Supervisor error: configuration is invalid")
        )
        result = await self.tools["sv_check_core_config"]()
        self.assertEqual(result["result"], "error")
        self.assertIn("invalid", result["details"])

    async def test_restart_core_preview(self) -> None:
        self.client.set_sv_response("GET", "/core/info", {"version": "2026.4.0"})
        result = await self.tools["sv_restart_core"]()
        self.assertIn("confirmation_token", result)
        self.assertIn("preview", result)
        self.assertIn("warning", result["preview"])

    async def test_restart_core_with_token(self) -> None:
        self.client.set_sv_response("GET", "/core/info", {"version": "2026.4.0"})
        # Get token
        preview_result = await self.tools["sv_restart_core"]()
        token = preview_result["confirmation_token"]

        self.client.set_sv_response("POST", "/core/restart", {})
        result = await self.tools["sv_restart_core"](confirmation_token=token)
        self.assertEqual(result.get("result"), "ok")

    async def test_restart_core_blocked_by_check_config_state(self) -> None:
        """Si hay escrituras sin validar, sv_restart_core debe bloquearse."""
        import tempfile
        import time

        import hermes.fs_write as fsw
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "check_config_state.json"
            # Use ISO strings (new format)
            write_ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            check_ts = "2020-01-01T00:00:00Z"
            state_path.write_text(json.dumps({
                "last_write_at": write_ts,
                "last_check_ok_at": check_ts,
            }), encoding="utf-8")

            with patch.object(fsw, "CHECK_CONFIG_STATE_PATH", state_path):
                self.client.set_sv_response("GET", "/core/info", {"version": "2026.4.0"})
                result = await self.tools["sv_restart_core"]()
                # Preview debe mostrar el bloqueo
                self.assertIn("blocked", result.get("preview", {}))

    async def test_reboot_host_preview(self) -> None:
        result = await self.tools["sv_reboot_host"]()
        self.assertIn("confirmation_token", result)
        self.assertIn("WARNING", result["preview"]["warning"])

    async def test_reboot_host_with_token(self) -> None:
        preview = await self.tools["sv_reboot_host"]()
        token = preview["confirmation_token"]
        self.client.set_sv_response("POST", "/host/reboot", {})
        result = await self.tools["sv_reboot_host"](confirmation_token=token)
        self.assertEqual(result["result"], "ok")


# ══════════════════════════════════════════════════════════════════════════════
# Tools de Add-ons
# ══════════════════════════════════════════════════════════════════════════════

class TestAddonTools(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        from hermes.tools.addons import register
        self.client = MockHAClient()
        mcp = DummyMCP()
        register(mcp, self.client)
        self.tools = mcp.tools

    async def test_list_addons_installed(self) -> None:
        self.client.set_sv_response("GET", "/addons", {
            "addons": [
                {"slug": "core_mosquitto", "name": "Mosquitto", "version": "6.5.2",
                 "version_latest": "6.5.2", "state": "started", "update_available": False,
                 "repository": "core", "description": "MQTT broker"},
                {"slug": "store_addon", "name": "StoreAddon", "version": None,
                 "state": None, "installed": False},
            ]
        })
        result = await self.tools["sv_list_addons"](installed_only=True)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["addons"][0]["slug"], "core_mosquitto")

    async def test_list_addons_all(self) -> None:
        self.client.set_sv_response("GET", "/addons", {
            "addons": [
                {"slug": "core_mosquitto", "name": "Mosquitto", "version": "6.5.2",
                 "version_latest": "6.5.2", "state": "started", "update_available": False},
                {"slug": "store_addon", "name": "StoreAddon", "version": None,
                 "state": None},
            ]
        })
        result = await self.tools["sv_list_addons"](installed_only=False)
        self.assertEqual(result["count"], 2)

    async def test_get_addon_ok(self) -> None:
        self.client.set_sv_response("GET", "/addons/core_mosquitto/info", {
            "slug": "core_mosquitto",
            "name": "Mosquitto broker",
            "version": "6.5.2",
            "state": "started",
        })
        result = await self.tools["sv_get_addon"]("core_mosquitto")
        self.assertEqual(result["slug"], "core_mosquitto")
        self.assertEqual(result["state"], "started")

    async def test_get_addon_not_found(self) -> None:
        self.client.set_sv_response(
            "GET", "/addons/nonexistent/info",
            HAConnectionError("Supervisor error: addon not found")
        )
        result = await self.tools["sv_get_addon"]("nonexistent")
        self.assertIn("error", result)

    async def test_get_addon_options_ok(self) -> None:
        self.client.set_sv_response("GET", "/addons/core_mosquitto/options/config", {
            "logins": [{"username": "homeassistant", "password": "foo"}],
            "require_certificate": False,
        })
        result = await self.tools["sv_get_addon_options"]("core_mosquitto")
        self.assertIn("logins", result)

    async def test_set_addon_options_preview(self) -> None:
        self.client.set_sv_response("GET", "/addons/core_mosquitto/options/config", {
            "require_certificate": False,
        })
        result = await self.tools["sv_set_addon_options"](
            "core_mosquitto", '{"require_certificate": true}'
        )
        self.assertIn("confirmation_token", result)
        self.assertIn("preview", result)
        self.assertEqual(result["preview"]["new_options"]["require_certificate"], True)

    async def test_set_addon_options_with_token(self) -> None:
        self.client.set_sv_response("GET", "/addons/core_mosquitto/options/config", {})
        preview = await self.tools["sv_set_addon_options"](
            "core_mosquitto", '{"require_certificate": true}'
        )
        token = preview["confirmation_token"]

        self.client.set_sv_response("POST", "/addons/core_mosquitto/options", {})
        result = await self.tools["sv_set_addon_options"](
            "core_mosquitto", '{"require_certificate": true}',
            confirmation_token=token
        )
        self.assertEqual(result["result"], "ok")

    async def test_set_addon_options_bad_json(self) -> None:
        result = await self.tools["sv_set_addon_options"](
            "core_mosquitto", "not-valid-json"
        )
        self.assertIn("error", result)

    async def test_start_addon_preview(self) -> None:
        self.client.set_sv_response("GET", "/addons/core_mosquitto/info", {"state": "stopped"})
        result = await self.tools["sv_start_addon"]("core_mosquitto")
        self.assertIn("confirmation_token", result)
        self.assertEqual(result["preview"]["action"], "start")

    async def test_stop_addon_preview(self) -> None:
        self.client.set_sv_response("GET", "/addons/core_mosquitto/info", {"state": "started"})
        result = await self.tools["sv_stop_addon"]("core_mosquitto")
        self.assertIn("confirmation_token", result)
        self.assertEqual(result["preview"]["action"], "stop")

    async def test_restart_addon_with_token(self) -> None:
        self.client.set_sv_response("GET", "/addons/core_mosquitto/info", {"state": "started"})
        preview = await self.tools["sv_restart_addon"]("core_mosquitto")
        token = preview["confirmation_token"]

        self.client.set_sv_response("POST", "/addons/core_mosquitto/restart", {})
        result = await self.tools["sv_restart_addon"]("core_mosquitto", confirmation_token=token)
        self.assertEqual(result["result"], "ok")

    async def test_hermes_self_warning_in_stop(self) -> None:
        """sv_stop_addon de Hermes mismo debe incluir WARNING en preview."""
        self.client.set_sv_response("GET", "/addons/local_hermes/info", {"state": "started"})
        result = await self.tools["sv_stop_addon"]("local_hermes")
        self.assertIn("warning", result["preview"])
        self.assertIn("WARNING", result["preview"]["warning"])

    async def test_install_addon_preview(self) -> None:
        result = await self.tools["sv_install_addon"]("abcd1234_ejemplo")
        self.assertIn("confirmation_token", result)

    async def test_install_addon_with_token_returns_job(self) -> None:
        preview = await self.tools["sv_install_addon"]("test_addon")
        token = preview["confirmation_token"]

        self.client.set_sv_response(
            "POST", "/store/addons/test_addon/install",
            {"job_id": "abc123def456"}
        )
        result = await self.tools["sv_install_addon"]("test_addon", confirmation_token=token)
        self.assertEqual(result["job_id"], "abc123def456")
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["poll_with"], "sv_get_job_status")

    async def test_uninstall_addon_preview_has_warning(self) -> None:
        self.client.set_sv_response("GET", "/addons/core_configurator/info", {
            "version": "6.0.0"
        })
        result = await self.tools["sv_uninstall_addon"]("core_configurator")
        self.assertIn("warning", result["preview"])
        self.assertIn("data", result["preview"]["warning"].lower())

    async def test_update_addon_preview_shows_versions(self) -> None:
        self.client.set_sv_response("GET", "/addons/core_mosquitto/info", {
            "version": "6.5.1", "version_latest": "6.5.2", "update_available": True
        })
        result = await self.tools["sv_update_addon"]("core_mosquitto")
        self.assertIn("confirmation_token", result)
        self.assertEqual(result["preview"]["current_version"], "6.5.1")
        self.assertEqual(result["preview"]["version_latest"], "6.5.2")

    async def test_get_addon_logs_no_secrets(self) -> None:
        self.client.set_sv_text_response(
            "/addons/core_mosquitto/logs",
            "2026-01-01 12:00:00: Connection from 192.168.1.1\n"
            "2026-01-01 12:00:01: Client disconnected\n"
        )
        result = await self.tools["sv_get_addon_logs"]("core_mosquitto")
        self.assertFalse(result["redacted"])
        self.assertIn("Connection from", result["logs"])

    async def test_get_addon_logs_redacts_password(self) -> None:
        self.client.set_sv_text_response(
            "/addons/core_mosquitto/logs",
            "password: mysecret123\nNormal log line\n"
        )
        result = await self.tools["sv_get_addon_logs"]("core_mosquitto")
        self.assertTrue(result["redacted"])
        self.assertNotIn("mysecret123", result["logs"])
        self.assertIn("***REDACTED***", result["logs"])

    async def test_get_addon_logs_default_100_lines(self) -> None:
        self.client.set_sv_text_response("/addons/core_samba/logs", "log line\n")
        result = await self.tools["sv_get_addon_logs"]("core_samba")
        self.assertEqual(result["lines_requested"], 100)

    async def test_get_addon_logs_clamps_to_1000(self) -> None:
        self.client.set_sv_text_response("/addons/core_samba/logs", "log\n")
        result = await self.tools["sv_get_addon_logs"]("core_samba", lines=9999)
        self.assertEqual(result["lines_requested"], 1000)

    async def test_get_addon_stats_ok(self) -> None:
        self.client.set_sv_response("GET", "/addons/core_mosquitto/stats", {
            "cpu_percent": 0.5,
            "memory_usage": 4096000,
            "memory_limit": 268435456,
            "network_tx": 1024,
            "network_rx": 2048,
        })
        result = await self.tools["sv_get_addon_stats"]("core_mosquitto")
        self.assertEqual(result["cpu_percent"], 0.5)
        self.assertIn("memory_usage", result)


# ══════════════════════════════════════════════════════════════════════════════
# Tools de Backups
# ══════════════════════════════════════════════════════════════════════════════

class TestBackupTools(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self._data_dir = Path(self._tmpdir) / "data"
        self._data_dir.mkdir()

        from hermes.tools.backups import register
        import hermes.tools.addons as addons_mod
        import hermes.tools.backups as backups_mod

        self._patch_jobs = patch.object(
            addons_mod, "_PENDING_JOBS_PATH",
            self._data_dir / "pending_jobs.json"
        )
        self._patch_safety = patch.object(
            backups_mod, "_SAFETY_BACKUP_STATE_PATH",
            self._data_dir / "last_safety_backup.json"
        )
        self._patch_jobs.start()
        self._patch_safety.start()

        self.client = MockHAClient()
        mcp = DummyMCP()
        register(mcp, self.client, safety_backup_window_minutes=30)
        self.tools = mcp.tools

    def tearDown(self) -> None:
        self._patch_jobs.stop()
        self._patch_safety.stop()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    async def test_list_backups_ok(self) -> None:
        self.client.set_sv_response("GET", "/backups", {
            "backups": [
                {"slug": "abc123", "name": "Full backup", "date": "2026-01-01T00:00:00Z",
                 "type": "full", "size": 1024 * 1024 * 500, "protected": False},
            ]
        })
        result = await self.tools["sv_list_backups"]()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["backups"][0]["slug"], "abc123")
        self.assertAlmostEqual(result["backups"][0]["size_mb"], 500.0, places=0)

    async def test_get_backup_ok(self) -> None:
        self.client.set_sv_response("GET", "/backups/abc123/info", {
            "slug": "abc123",
            "name": "Full backup",
            "homeassistant": "2026.4.0",
        })
        result = await self.tools["sv_get_backup"]("abc123")
        self.assertEqual(result["slug"], "abc123")

    async def test_create_backup_full_returns_job(self) -> None:
        self.client.set_sv_response("POST", "/backups/new/full", {
            "job_id": "job_full_abc123"
        })
        result = await self.tools["sv_create_backup_full"]("Test backup")
        self.assertEqual(result["job_id"], "job_full_abc123")
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["poll_with"], "sv_get_job_status")

    async def test_create_backup_partial_returns_job(self) -> None:
        self.client.set_sv_response("POST", "/backups/new/partial", {
            "job_id": "job_partial_xyz"
        })
        result = await self.tools["sv_create_backup_partial"](
            "Partial backup",
            addons='["core_mosquitto"]',
        )
        self.assertEqual(result["job_id"], "job_partial_xyz")

    async def test_create_backup_partial_bad_addons_json(self) -> None:
        result = await self.tools["sv_create_backup_partial"](
            "Bad backup", addons="not-json"
        )
        self.assertIn("error", result)

    async def test_create_safety_backup_first_time(self) -> None:
        self.client.set_sv_response("POST", "/backups/new/full", {
            "job_id": "safety_job_001"
        })
        result = await self.tools["sv_create_safety_backup"]()
        self.assertFalse(result["reused"])
        self.assertEqual(result["job_id"], "safety_job_001")

    async def test_create_safety_backup_within_window_reuses(self) -> None:
        import time as _time
        self.client.set_sv_response("POST", "/backups/new/full", {
            "job_id": "safety_job_001"
        })
        # Primer backup
        first = await self.tools["sv_create_safety_backup"]()
        self.assertFalse(first["reused"])

        # Inmediatamente después — debe reusar
        second = await self.tools["sv_create_safety_backup"]()
        self.assertTrue(second["reused"])

    async def test_delete_backup_preview(self) -> None:
        self.client.set_sv_response("GET", "/backups/abc123/info", {
            "name": "Old backup", "date": "2025-01-01T00:00:00Z", "type": "full"
        })
        result = await self.tools["sv_delete_backup"]("abc123")
        self.assertIn("confirmation_token", result)
        self.assertEqual(result["preview"]["action"], "delete")

    async def test_delete_backup_with_token(self) -> None:
        self.client.set_sv_response("GET", "/backups/abc123/info", {
            "name": "Old backup", "date": "2025-01-01T00:00:00Z", "type": "full"
        })
        preview = await self.tools["sv_delete_backup"]("abc123")
        token = preview["confirmation_token"]

        self.client.set_sv_response("DELETE", "/backups/abc123", {})
        result = await self.tools["sv_delete_backup"]("abc123", confirmation_token=token)
        self.assertEqual(result["result"], "ok")

    async def test_restore_backup_full_preview_has_critical_warning(self) -> None:
        self.client.set_sv_response("GET", "/backups/abc123/info", {
            "name": "Full backup", "date": "2025-01-01T00:00:00Z",
            "homeassistant": "2025.1.0"
        })
        result = await self.tools["sv_restore_backup_full"]("abc123")
        self.assertIn("WARNING", result["preview"]["warning"])
        self.assertIn("PERMANENTLY LOST", result["preview"]["warning"])

    async def test_restore_backup_partial_preview(self) -> None:
        self.client.set_sv_response("GET", "/backups/abc123/info", {"name": "Partial"})
        result = await self.tools["sv_restore_backup_partial"]("abc123")
        self.assertIn("confirmation_token", result)

    async def test_get_job_status_running(self) -> None:
        self.client.set_sv_response("GET", "/jobs/job_abc123", {
            "name": "backup_full",
            "done": False,
            "progress": 45,
            "stage": "creating_archive",
        })
        result = await self.tools["sv_get_job_status"]("job_abc123")
        self.assertFalse(result["done"])
        self.assertEqual(result["progress"], 45)
        self.assertEqual(result["stage"], "creating_archive")

    async def test_get_job_status_done(self) -> None:
        self.client.set_sv_response("GET", "/jobs/job_abc123", {
            "name": "backup_full",
            "done": True,
            "progress": 100,
            "reference": "deadbeef",
        })
        result = await self.tools["sv_get_job_status"]("job_abc123")
        self.assertTrue(result["done"])
        self.assertEqual(result["reference"], "deadbeef")

    async def test_list_pending_jobs_empty(self) -> None:
        result = await self.tools["sv_list_pending_jobs"]()
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["jobs"], [])

    async def test_list_pending_jobs_after_create(self) -> None:
        self.client.set_sv_response("POST", "/backups/new/full", {
            "job_id": "pending_test_job"
        })
        await self.tools["sv_create_backup_full"]("Test for pending jobs")
        result = await self.tools["sv_list_pending_jobs"]()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["jobs"][0]["job_id"], "pending_test_job")


if __name__ == "__main__":
    unittest.main()

class TestSelfProtectionWorksWhereverItIsInstalled(unittest.TestCase):
    """El aviso de "esto te deja sin acceso" tiene que saltar siempre.

    El slug del add-on lo decide el Supervisor y depende de dónde está
    instalado: en una carpeta local es `local_hermes`; instalado desde un
    repositorio es `<hash del repo>_hermes`, con un hash distinto por
    repositorio. Comparar contra `local_hermes` a secas —que es lo que hacía—
    significa que el aviso previo a `sv_stop_addon` y `sv_uninstall_addon` no
    saltaba para nadie salvo en una instalación local.

    Es decir: funcionaba en la máquina donde se escribió y en ninguna otra.
    """

    def test_it_recognises_itself_however_it_was_installed(self) -> None:
        from hermes.tools.addons import _es_hermes

        for slug in ("local_hermes", "hermes", "a1b2c3d4_hermes",
                     "5f8e2b1a_hermes", "LOCAL_HERMES"):
            with self.subTest(slug=slug):
                self.assertTrue(_es_hermes(slug), f"no se reconoce a sí mismo: {slug}")

    def test_it_does_not_claim_other_addons(self) -> None:
        from hermes.tools.addons import _es_hermes

        for slug in ("core_mosquitto", "a0d7b954_tailscale", "local_otracosa",
                     "hermes_helper", "esphome"):
            with self.subTest(slug=slug):
                self.assertFalse(_es_hermes(slug), f"reclama un add-on ajeno: {slug}")

    def test_the_warning_reaches_the_caller(self) -> None:
        from hermes.tools.addons import _self_warning

        aviso = _self_warning("a1b2c3d4_hermes", "Stopping")
        self.assertIsNotNone(aviso, "sin aviso al pararse a sí mismo")
        self.assertIn("unavailable", aviso)
        self.assertIsNone(_self_warning("core_mosquitto", "Stopping"))
