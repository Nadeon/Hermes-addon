"""Tests de tool-level para hermes.tools.supervisor, addons y backups.

Usa un MockHAClient que implementa sv_request / sv_request_text.
No hace llamadas de red reales.
"""

from __future__ import annotations

import asyncio
import copy
import json
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from hermes.ha import HAConnectionError
from hermes.security import REDACTED_MARKER
from hermes.tools import addons as addons_mod


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
        # WebSocket con el Core: lista y sin respuestas configuradas.
        self.ready = True
        self._ws_responses: dict[str, Any] = {}
        self.ws_sent: list[dict[str, Any]] = []

    def set_ws_response(self, command_type: str, response: Any) -> None:
        self._ws_responses[command_type] = response

    async def ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.ws_sent.append(payload)
        resp = self._ws_responses.get(payload.get("type"))
        if resp is None:
            raise HAConnectionError(f"MockHAClient: no WS response for {payload.get('type')}")
        if isinstance(resp, Exception):
            raise resp
        return resp

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

    # `/core/info` real del Supervisor: no trae `state`. El test anterior se lo
    # inventaba ("state": "running"), y por eso nunca vio que la tool
    # devolvía siempre null en una instalación de verdad.
    _CORE_INFO_REAL = {
        "version": "2026.4.0",
        "version_latest": "2026.4.1",
        "update_available": True,
        "arch": "amd64",
        "machine": "generic-x86-64",
        "boot": True,
        "watchdog": True,
    }

    async def test_get_core_info_ok(self) -> None:
        self.client.set_sv_response("GET", "/core/info", dict(self._CORE_INFO_REAL))
        self.client.set_ws_response("get_config", {"state": "RUNNING", "version": "2026.4.0"})
        result = await self.tools["sv_get_core_info"]()
        self.assertEqual(result["version"], "2026.4.0")
        self.assertTrue(result["update_available"])

    async def test_get_core_info_state_comes_from_the_core(self) -> None:
        """`state` salía siempre null: se leía de `/core/info`, que no lo trae."""
        self.client.set_sv_response("GET", "/core/info", dict(self._CORE_INFO_REAL))
        for del_core, esperado in (("RUNNING", "running"), ("STARTING", "starting"),
                                   ("NOT_RUNNING", "not_running")):
            with self.subTest(del_core=del_core):
                self.client.set_ws_response("get_config", {"state": del_core})
                result = await self.tools["sv_get_core_info"]()
                self.assertEqual(result["state"], esperado)
        self.assertEqual(self.client.ws_sent[-1], {"type": "get_config"})

    async def test_get_core_info_state_unreachable_without_websocket(self) -> None:
        """Sin conexión con el Core (por ejemplo, reiniciando) no hay a quién
        preguntar; la tool lo dice en vez de devolver null ni colgarse."""
        self.client.set_sv_response("GET", "/core/info", dict(self._CORE_INFO_REAL))
        self.client.ready = False
        result = await self.tools["sv_get_core_info"]()
        self.assertEqual(result["state"], "unreachable")
        self.assertEqual(result["version"], "2026.4.0")
        self.assertEqual(self.client.ws_sent, [], "no debe intentar la WS si no está lista")

        self.client.ready = True
        self.client.set_ws_response("get_config", HAConnectionError("Timeout waiting"))
        result = await self.tools["sv_get_core_info"]()
        self.assertEqual(result["state"], "unreachable")

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
        # `GET /addons` solo devuelve add-ons INSTALADOS y sus objetos no
        # llevan clave `installed`: el mock anterior metía ahí una entrada de
        # store, una forma que el Supervisor nunca produce.
        self.client.set_sv_response("GET", "/addons", {
            "addons": [
                {"slug": "core_mosquitto", "name": "Mosquitto", "version": "6.5.2",
                 "version_latest": "6.5.2", "state": "started", "update_available": False,
                 "repository": "core", "description": "MQTT broker"},
            ]
        })
        result = await self.tools["sv_list_addons"](installed_only=True)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["addons"][0]["slug"], "core_mosquitto")
        self.assertEqual(result["source"], "/addons")

    async def test_list_addons_all_uses_store_endpoint(self) -> None:
        """installed_only=False tiene que ir al catálogo del store.

        Regresión: se pedía `/addons` en ambos casos y se filtraba por una
        clave `installed` inexistente, así que el parámetro no hacía nada y el
        catálogo del store no se veía nunca.
        """
        self.client.set_sv_response("GET", "/addons", {
            "addons": [
                {"slug": "core_mosquitto", "name": "Mosquitto", "version": "6.5.2",
                 "version_latest": "6.5.2", "state": "started", "update_available": False},
            ]
        })
        self.client.set_sv_response("GET", "/store/addons", {
            "addons": [
                {"slug": "core_mosquitto", "name": "Mosquitto", "version": "6.5.2",
                 "version_latest": "6.5.2", "update_available": False,
                 "installed": True, "available": True, "repository": "core"},
                {"slug": "core_deconz", "name": "deCONZ", "version": None,
                 "version_latest": "6.20.0", "update_available": False,
                 "installed": False, "available": True, "repository": "core"},
            ]
        })
        result = await self.tools["sv_list_addons"](installed_only=False)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["source"], "/store/addons")
        slugs = [a["slug"] for a in result["addons"]]
        self.assertIn("core_deconz", slugs)
        no_instalado = next(
            a for a in result["addons"] if a["slug"] == "core_deconz"
        )
        self.assertIs(no_instalado["installed"], False)
        self.assertIs(no_instalado["available"], True)

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
        # Las opciones se leen de /info: /options/config el Supervisor solo se
        # lo sirve al propio add-on. Este test mockeaba ese endpoint, así que
        # daba por buena una tool que en real devolvía 403 siempre.
        self.client.set_sv_response("GET", "/addons/core_mosquitto/info", {
            "slug": "core_mosquitto",
            "options": {
                "logins": [{"username": "homeassistant", "password": "s3cr3t0"}],
                "require_certificate": False,
            },
        })
        result = await self.tools["sv_get_addon_options"]("core_mosquitto")
        self.assertEqual(result["slug"], "core_mosquitto")
        self.assertIn("logins", result["options"])
        self.assertIs(result["options"]["require_certificate"], False)
        # Las opciones traen secretos en claro: no pueden salir tal cual.
        self.assertNotIn("s3cr3t0", json.dumps(result))

    async def test_set_addon_options_preview(self) -> None:
        # Igual que sv_get_addon_options: las opciones actuales salen de /info.
        # El endpoint /options/config el Supervisor lo reserva al propio add-on
        # (403 a cualquier otro), así que mockearlo daba por bueno un preview
        # que en real venía siempre vacío.
        self.client.set_sv_response("GET", "/addons/core_mosquitto/info", {
            "slug": "core_mosquitto",
            "options": {"require_certificate": False, "password": "s3cr3t0"},
        })
        result = await self.tools["sv_set_addon_options"](
            "core_mosquitto", '{"require_certificate": true}'
        )
        self.assertIn("confirmation_token", result)
        self.assertIn("preview", result)
        preview = result["preview"]
        self.assertEqual(preview["requested_changes"], {"require_certificate": True})
        self.assertEqual(
            preview["final_options"],
            {"require_certificate": True, "password": REDACTED_MARKER},
        )
        self.assertEqual(preview["changed_paths"], ["require_certificate"])
        # Regresión: el preview enseñaba current_options: None siempre.
        self.assertIs(preview["current_options"]["require_certificate"], False)
        # Y lo que lee de /info sigue teniendo que salir redactado.
        self.assertNotIn("s3cr3t0", json.dumps(result))

    async def test_set_addon_options_with_token(self) -> None:
        # Sin `options` en /info ya no hay token: ver
        # TestSetAddonOptionsConservaLoQueNoSeToca.
        self.client.set_sv_response("GET", "/addons/core_mosquitto/info", {"options": {}})
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
        # El Supervisor manda `size` YA en MB (round(size_bytes/1048576, 2)) y
        # `size_bytes` aparte. El mock anterior ponía bytes en `size`, una
        # forma que el Supervisor nunca envía, y tapaba el bug.
        self.client.set_sv_response("GET", "/backups", {
            "backups": [
                {"slug": "abc123", "name": "Full backup", "date": "2026-01-01T00:00:00Z",
                 "type": "full", "size": 500.0, "size_bytes": 1024 * 1024 * 500,
                 "protected": False},
            ]
        })
        result = await self.tools["sv_list_backups"]()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["backups"][0]["slug"], "abc123")
        self.assertAlmostEqual(result["backups"][0]["size_mb"], 500.0, places=0)

    async def test_list_backups_size_mb_without_size_bytes(self) -> None:
        """Sin `size_bytes`, `size` se interpreta como MB, no como bytes."""
        self.client.set_sv_response("GET", "/backups", {
            "backups": [
                {"slug": "def456", "name": "Partial", "type": "partial",
                 "size": 123.45, "protected": False},
            ]
        })
        result = await self.tools["sv_list_backups"]()
        self.assertAlmostEqual(result["backups"][0]["size_mb"], 123.45, places=2)

    async def test_list_backups_size_mb_missing(self) -> None:
        """Sin ningún campo de tamaño no se inventa un 0.0."""
        self.client.set_sv_response("GET", "/backups", {
            "backups": [{"slug": "ghi789", "name": "Sin tamaño", "type": "full"}]
        })
        result = await self.tools["sv_list_backups"]()
        self.assertIsNone(result["backups"][0]["size_mb"])

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


    async def test_pending_jobs_file_corrupt_does_not_lose_the_job(self) -> None:
        """Un pending_jobs.json que no es un objeto no puede tumbar el tracking.

        Regresión: `_load_jobs_sync` solo cubría JSONDecodeError, así que un
        documento válido pero no-dict (`[]`) hacía estallar `_track_job` con
        TypeError DESPUÉS del POST — backup lanzado, job_id perdido y token de
        confirmación sin cerrar.
        """
        addons_mod._PENDING_JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
        addons_mod._PENDING_JOBS_PATH.write_text("[]", encoding="utf-8")

        self.client.set_sv_response("POST", "/backups/new/full", {
            "job_id": "job_tras_fichero_corrupto"
        })
        result = await self.tools["sv_create_backup_full"]("Backup tras corrupción")
        self.assertEqual(result["job_id"], "job_tras_fichero_corrupto")

        listado = await self.tools["sv_list_pending_jobs"]()
        self.assertEqual(listado["count"], 1)
        self.assertEqual(listado["jobs"][0]["job_id"], "job_tras_fichero_corrupto")

    def test_load_jobs_sync_rejects_non_dict_documents(self) -> None:
        addons_mod._PENDING_JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
        for contenido in ("[]", "null", "42", '"texto"'):
            addons_mod._PENDING_JOBS_PATH.write_text(contenido, encoding="utf-8")
            self.assertEqual(addons_mod._load_jobs_sync(), {}, contenido)


class TestOpcionesDeAddon(unittest.IsolatedAsyncioTestCase):
    """`sv_get_addon_options` leía un endpoint que el Supervisor le negaba.

    Usaba /addons/{slug}/options/config, que HAOS reserva al add-on que se
    consulta a sí mismo: a cualquier otro le devuelve 403 "This can be only
    read by the app itself!". La tool no funcionaba con NINGÚN add-on, y su
    descripción prometía justo lo que no podía dar. Se detectó llamándola
    contra un Home Assistant en marcha, no en la suite.
    """

    def test_no_usa_el_endpoint_que_el_supervisor_niega(self) -> None:
        import inspect
        from hermes.tools import addons

        fuente = inspect.getsource(addons.register)
        bloque = fuente.split("async def sv_get_addon_options")[1]
        bloque = bloque.split("async def sv_set_addon_options")[0]
        self.assertNotIn(
            'sv_request("GET", f"/addons/{slug}/options/config")', bloque
        )
        self.assertIn('sv_request("GET", f"/addons/{slug}/info")', bloque)

    def test_redacta_las_opciones(self) -> None:
        """Las opciones traen los secretos del add-on en claro."""
        import inspect
        from hermes.tools import addons

        fuente = inspect.getsource(addons.register)
        bloque = fuente.split("async def sv_get_addon_options")[1]
        bloque = bloque.split("async def sv_set_addon_options")[0]
        self.assertIn("redact_structure(opciones)", bloque)


class _ClienteQueGraba(MockHAClient):
    """MockHAClient que además apunta cada petición con su cuerpo."""

    def __init__(self) -> None:
        super().__init__()
        self.peticiones: list[tuple[str, str, Any]] = []

    async def sv_request(
        self,
        method: str,
        sv_path: str,
        json_body: Any = None,
        params: Any = None,
        timeout_seconds: float = 60.0,
    ) -> Any:
        self.peticiones.append((method.upper(), sv_path, copy.deepcopy(json_body)))
        return await super().sv_request(method, sv_path, json_body, params, timeout_seconds)

    def enviadas(self, slug: str) -> list[dict[str, Any]]:
        """Opciones que se han mandado al Supervisor para `slug`, en orden."""
        return [
            cuerpo["options"] for metodo, ruta, cuerpo in self.peticiones
            if metodo == "POST" and ruta == f"/addons/{slug}/options"
        ]

    def lecturas(self, ruta: str) -> int:
        return sum(1 for metodo, r, _ in self.peticiones if metodo == "GET" and r == ruta)


# Forma de las opciones de Zigbee2MQTT tal como las devuelve /info. La IP es de
# documentación (RFC 5737): lo que importa es que es un valor que el usuario
# configuró y que no coincide con ningún valor por defecto.
_Z2M_SLUG = "45df7312_zigbee2mqtt"
_Z2M_SECRETO = "contrasena-mqtt-de-verdad"
_Z2M = {
    "data_path": "/config/zigbee2mqtt",
    "socat": {"enabled": False, "master": "pty,raw,echo=0,link=/tmp/ttyZ2M,mode=777"},
    "mqtt": {
        "server": "mqtt://core-mosquitto:1883",
        "user": "addons",
        "password": _Z2M_SECRETO,
    },
    "serial": {"port": "tcp://192.0.2.10:7638", "adapter": "zstack"},
}
# `schema` de /info (la schema_ui del Supervisor) con una obligatoria arriba.
_Z2M_SCHEMA = [
    {"name": "data_path", "type": "string", "required": True},
    {"name": "serial", "type": "schema", "optional": True, "multiple": False,
     "schema": [{"name": "port", "type": "string", "optional": True}]},
]


class TestSetAddonOptionsConservaLoQueNoSeToca(unittest.IsolatedAsyncioTestCase):
    """`sv_set_addon_options` enviaba solo lo que pasaba el llamante.

    El Supervisor no mezcla: `POST /addons/{slug}/options` sustituye las
    opciones guardadas por las recibidas. La tool prometía «pasa solo los
    campos que quieres cambiar; el resto se mantiene», y hacía lo contrario:
    para poner `{"watchdog": "default"}` en Zigbee2MQTT se habrían perdido el
    puerto serie y la contraseña de MQTT, que el llamante ni siquiera puede
    reponer porque solo la ve redactada.
    """

    def setUp(self) -> None:
        from hermes.tools.addons import register
        self.client = _ClienteQueGraba()
        mcp = DummyMCP()
        register(mcp, self.client)
        self.tool = mcp.tools["sv_set_addon_options"]
        self.info = f"/addons/{_Z2M_SLUG}/info"
        self._info({"options": copy.deepcopy(_Z2M), "schema": _Z2M_SCHEMA})
        self.client.set_sv_response("POST", f"/addons/{_Z2M_SLUG}/options", {})

    def _info(self, respuesta: Any) -> None:
        self.client.set_sv_response("GET", self.info, respuesta)

    async def _aplicar(self, opciones: str) -> tuple[dict, dict]:
        """Preview + confirmación. Devuelve (preview, resultado)."""
        preview = await self.tool(_Z2M_SLUG, opciones)
        self.assertIn("confirmation_token", preview, preview)
        resultado = await self.tool(
            _Z2M_SLUG, opciones, confirmation_token=preview["confirmation_token"]
        )
        return preview, resultado

    async def test_cambiar_una_opcion_de_primer_nivel_conserva_el_resto(self) -> None:
        _, resultado = await self._aplicar('{"watchdog": "default"}')
        self.assertEqual(resultado["result"], "ok")
        self.assertEqual(self.client.enviadas(_Z2M_SLUG), [{**_Z2M, "watchdog": "default"}])
        # Nunca el endpoint que el Supervisor reserva al propio add-on.
        self.assertFalse(any("options/config" in r for _, r, _ in self.client.peticiones))

    async def test_cambiar_una_clave_anidada_conserva_sus_hermanas(self) -> None:
        await self._aplicar('{"mqtt": {"user": "otro"}}')
        [enviado] = self.client.enviadas(_Z2M_SLUG)
        self.assertEqual(enviado["mqtt"], {**_Z2M["mqtt"], "user": "otro"})
        self.assertEqual(enviado["serial"], _Z2M["serial"])
        self.assertEqual(enviado["socat"], _Z2M["socat"])

    async def test_un_secreto_no_tocado_se_envia_con_su_valor_real(self) -> None:
        await self._aplicar('{"serial": {"adapter": "ember"}}')
        [enviado] = self.client.enviadas(_Z2M_SLUG)
        self.assertEqual(enviado["mqtt"]["password"], _Z2M_SECRETO)
        self.assertNotIn(REDACTED_MARKER, json.dumps(enviado))

    async def test_una_referencia_secret_se_reenvia_sin_resolver(self) -> None:
        # /info devuelve `!secret x` tal cual; reenviarlo conserva la referencia
        # en vez de guardar el secreto en claro.
        opciones = copy.deepcopy(_Z2M)
        opciones["mqtt"]["password"] = "!secret z2m_mqtt"
        self._info({"options": opciones, "schema": _Z2M_SCHEMA})
        await self._aplicar('{"watchdog": "default"}')
        [enviado] = self.client.enviadas(_Z2M_SLUG)
        self.assertEqual(enviado["mqtt"]["password"], "!secret z2m_mqtt")

    async def test_rechaza_el_marcador_de_redaccion_a_cualquier_nivel(self) -> None:
        casos = {
            '{"auth_password": "***REDACTED***"}': ["auth_password"],
            '{"mqtt": {"password": "***REDACTED***"}}': ["mqtt.password"],
            '{"logins": [{"username": "a", "password": "***REDACTED***"}]}':
                ["logins[0].password"],
        }
        for opciones, rutas in casos.items():
            with self.subTest(opciones=opciones):
                resultado = await self.tool(_Z2M_SLUG, opciones)
                self.assertEqual(resultado["error"], "redacted_value")
                self.assertEqual(resultado["paths"], rutas)
                self.assertNotIn("confirmation_token", resultado)
        self.assertEqual(self.client.peticiones, [])

    async def test_el_preview_no_filtra_secretos(self) -> None:
        resultado = await self.tool(_Z2M_SLUG, '{"mqtt": {"password": "nueva-secreta"}}')
        preview = resultado["preview"]
        volcado = json.dumps(resultado)
        self.assertNotIn(_Z2M_SECRETO, volcado)
        self.assertNotIn("nueva-secreta", volcado)
        # Lo que no es secreto sí se ve, para saber qué se va a enviar.
        self.assertEqual(preview["final_options"]["serial"], _Z2M["serial"])
        self.assertEqual(preview["final_options"]["mqtt"]["password"], REDACTED_MARKER)
        self.assertEqual(preview["current_options"]["mqtt"]["user"], "addons")
        self.assertEqual(preview["changed_paths"], ["mqtt.password"])

    async def test_la_confirmacion_relee_las_opciones_actuales(self) -> None:
        opciones = '{"watchdog": "default"}'
        preview = await self.tool(_Z2M_SLUG, opciones)
        # Entre el preview y la confirmación alguien cambia el adaptador.
        cambiadas = copy.deepcopy(_Z2M)
        cambiadas["serial"]["adapter"] = "ember"
        self._info({"options": cambiadas, "schema": _Z2M_SCHEMA})

        await self.tool(_Z2M_SLUG, opciones, confirmation_token=preview["confirmation_token"])

        self.assertEqual(self.client.lecturas(self.info), 2)
        [enviado] = self.client.enviadas(_Z2M_SLUG)
        self.assertEqual(enviado["serial"]["adapter"], "ember")
        self.assertEqual(enviado["watchdog"], "default")

    async def test_null_quita_la_opcion(self) -> None:
        preview, _ = await self._aplicar('{"serial": {"adapter": null}}')
        self.assertEqual(preview["preview"]["changed_paths"], ["serial.adapter"])
        [enviado] = self.client.enviadas(_Z2M_SLUG)
        self.assertEqual(enviado["serial"], {"port": _Z2M["serial"]["port"]})

    async def test_sin_opciones_actuales_no_se_envia_nada(self) -> None:
        for respuesta in ({"slug": _Z2M_SLUG}, {"options": None}, HAConnectionError("caído")):
            with self.subTest(respuesta=respuesta):
                self._info(respuesta)
                resultado = await self.tool(_Z2M_SLUG, '{"watchdog": "default"}')
                self.assertIn("error", resultado)
                self.assertNotIn("confirmation_token", resultado)
        self.assertEqual(self.client.enviadas(_Z2M_SLUG), [])

    async def test_opciones_ocultas_por_el_supervisor_no_se_mezclan(self) -> None:
        """Sin rol manager/admin, /info manda `options: {}` y el schema entero.

        Mezclar sobre ese `{}` enviaría solo los cambios y borraría todo lo
        demás: el fallo original por otra puerta. Con una obligatoria en el
        schema, `{}` no puede ser legítimo.
        """
        anidada = [{"name": "mqtt", "type": "schema", "optional": True, "multiple": False,
                    "schema": [{"name": "server", "type": "string", "required": True}]}]
        for schema in (_Z2M_SCHEMA, anidada):
            with self.subTest(schema=schema):
                self._info({"options": {}, "schema": schema})
                resultado = await self.tool(_Z2M_SLUG, '{"watchdog": "default"}')
                self.assertEqual(resultado["error"], "current_options_unavailable")
                self.assertNotIn("confirmation_token", resultado)
        self.assertEqual(self.client.enviadas(_Z2M_SLUG), [])

    async def test_opciones_ocultas_entre_preview_y_confirmacion(self) -> None:
        preview = await self.tool(_Z2M_SLUG, '{"watchdog": "default"}')
        self._info({"options": {}, "schema": _Z2M_SCHEMA})
        resultado = await self.tool(
            _Z2M_SLUG, '{"watchdog": "default"}',
            confirmation_token=preview["confirmation_token"],
        )
        self.assertEqual(resultado["error"], "current_options_unavailable")
        self.assertEqual(self.client.enviadas(_Z2M_SLUG), [])

    async def test_opciones_vacias_sin_obligatorias_si_se_envian(self) -> None:
        # Un add-on cuyas opciones son todas opcionales y sin valor por defecto
        # sí puede tener `{}` de verdad: ahí no hay nada que perder.
        opcional = [{"name": "log_level", "type": "string", "optional": True}]
        for schema in (opcional, None):
            with self.subTest(schema=schema):
                self._info({"options": {}, "schema": schema})
                await self._aplicar('{"log_level": "debug"}')
        self.assertEqual(
            self.client.enviadas(_Z2M_SLUG), [{"log_level": "debug"}, {"log_level": "debug"}]
        )

    async def test_si_la_relectura_falla_en_la_confirmacion_no_se_envia_nada(self) -> None:
        preview = await self.tool(_Z2M_SLUG, '{"watchdog": "default"}')
        self._info({"slug": _Z2M_SLUG})
        resultado = await self.tool(
            _Z2M_SLUG, '{"watchdog": "default"}',
            confirmation_token=preview["confirmation_token"],
        )
        self.assertEqual(resultado["error"], "current_options_unavailable")
        self.assertEqual(self.client.enviadas(_Z2M_SLUG), [])

    async def test_el_token_sigue_atado_a_los_mismos_argumentos(self) -> None:
        preview = await self.tool(_Z2M_SLUG, '{"watchdog": "default"}')
        resultado = await self.tool(
            _Z2M_SLUG, '{"watchdog": "disabled"}',
            confirmation_token=preview["confirmation_token"],
        )
        self.assertIn("does not match", resultado["error"])
        self.assertEqual(self.client.enviadas(_Z2M_SLUG), [])

    async def test_options_tiene_que_ser_un_objeto(self) -> None:
        for opciones in ('["watchdog"]', '"default"', "null"):
            with self.subTest(opciones=opciones):
                resultado = await self.tool(_Z2M_SLUG, opciones)
                self.assertEqual(resultado["error"], "invalid_options")
        self.assertEqual(self.client.peticiones, [])


class TestMezclarOpciones(unittest.TestCase):
    """Reglas de `_mezclar_opciones`, sin pasar por la tool."""

    def test_las_listas_se_sustituyen_enteras(self) -> None:
        from hermes.tools.addons import _mezclar_opciones
        actuales = {"logins": [{"username": "a", "password": "x"}], "anonymous": False}
        finales = _mezclar_opciones(actuales, {"logins": [{"username": "b", "password": "y"}]})
        self.assertEqual(finales["logins"], [{"username": "b", "password": "y"}])
        self.assertIs(finales["anonymous"], False)

    def test_no_modifica_las_entradas(self) -> None:
        from hermes.tools.addons import _mezclar_opciones
        actuales = copy.deepcopy(_Z2M)
        cambios = {"mqtt": {"user": "otro"}, "serial": None}
        _mezclar_opciones(actuales, cambios)
        self.assertEqual(actuales, _Z2M)
        self.assertEqual(cambios, {"mqtt": {"user": "otro"}, "serial": None})

    def test_un_objeto_nuevo_no_arrastra_los_null(self) -> None:
        # El Supervisor rechaza `null` como valor: un objeto que aún no existía
        # tampoco puede llevarlo dentro.
        from hermes.tools.addons import _mezclar_opciones
        finales = _mezclar_opciones({}, {"tls": {"cert": "c.pem", "key": None}})
        self.assertEqual(finales, {"tls": {"cert": "c.pem"}})


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
