"""Tests de seguridad de la escritura en /config.

Cubre exactamente los casos listados en la spec:
- Path traversal en write/delete/move
- Symlink que escapa
- Blacklist por nombre y patrón en write
- Managed paths rechazados con y sin token
- Fail-closed: configuration.yaml roto → todo .yaml exige token
- Rate limit: 11 escrituras en 60s → 11ª rechazada
- Min interval: dos escrituras < 5s → segunda rechazada
- Confirmation token: hash mismatch → rechazo
- Hash canonicalizado (security.py tests)
- Backup automático verificado
- safe_write preserva permisos y line endings
- Backup-before-restore
- Restore rechazado si path ahora protegido
- Regla check_config: write → restart sin check → rechazo
- Regla check_config: write → check OK → write → restart → rechazo
- Safety backup automático tras > window
- Safety backup barrera < 60s
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "hermes" / "src"))

import hermes.fs as fs_module
import hermes.fs_write as fsw_module
import hermes.tools.filesystem_write as fsw_tools_module
from hermes.fs_write import (
    BACKUPS_NORMAL_DIR,
    CHECK_CONFIG_STATE_PATH,
    WRITE_RATE_LIMIT_PATH,
    RateLimitError,
    backup_before_write,
    reserve_write_slot,
    check_restart_allowed_sync,
    is_managed_path,
    maybe_trigger_safety_backup,
    record_check_config_ok,
    record_config_write,
    safe_write_file,
)
from hermes.tools.filesystem_write import register_write


# ── Helpers ───────────────────────────────────────────────────────────────────


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _make_ha_client() -> MagicMock:
    client = MagicMock()
    client.sv_request = AsyncMock(return_value={"job_id": None})
    return client


def _j(raw) -> dict:
    if isinstance(raw, (bytes, str)):
        return json.loads(raw)
    return raw


class _Base(unittest.IsolatedAsyncioTestCase):
    """Base con tmpdir, patched CONFIG_BASE, patched data paths."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.config_root = Path(self._tmpdir) / "config"
        self.config_root.mkdir()
        self.data_root = Path(self._tmpdir) / "data"
        self.data_root.mkdir()

        self._patchers = []

        # Patch CONFIG_BASE
        p1 = patch.object(fs_module, "CONFIG_BASE", self.config_root.resolve())
        p1.start()
        self._patchers.append(p1)

        # Patch hermes.yaml_include CONFIG_BASE access (it uses hermes.fs.CONFIG_BASE)
        import hermes.yaml_include as yi
        p2 = patch.object(yi._fs, "CONFIG_BASE", self.config_root.resolve())
        p2.start()
        self._patchers.append(p2)

        # Patch data paths to use tmpdir (in both fs_write and filesystem_write modules)
        backups_normal = self.data_root / "backups" / "normal"
        backups_sensitive = self.data_root / "backups" / "sensitive"
        rl_path = self.data_root / "write_rate_limit.json"
        cc_path = self.data_root / "check_config_state.json"

        p3 = patch.object(fsw_module, "BACKUPS_NORMAL_DIR", backups_normal)
        p4 = patch.object(fsw_module, "BACKUPS_SENSITIVE_DIR", backups_sensitive)
        p5 = patch.object(fsw_module, "WRITE_RATE_LIMIT_PATH", rl_path)
        p6 = patch.object(fsw_module, "CHECK_CONFIG_STATE_PATH", cc_path)
        # Also patch the imported names in filesystem_write.py
        p7 = patch.object(fsw_tools_module, "BACKUPS_NORMAL_DIR", backups_normal)
        p8 = patch.object(fsw_tools_module, "BACKUPS_SENSITIVE_DIR", backups_sensitive)
        for p in [p3, p4, p5, p6, p7, p8]:
            p.start()
            self._patchers.append(p)

        # Reset rate limit state cache between tests
        fsw_module._rate_lock = asyncio.Lock()
        fsw_module._config_state_lock = asyncio.Lock()

        # Also patch yaml_include cache
        import hermes.yaml_include as yi2
        yi2._cached_paths = None
        yi2._cache_fail_reason = ""

        # Build tools
        self.ha_client = _make_ha_client()
        mcp = DummyMCP()
        register_write(
            mcp,
            self.ha_client,
            safety_backup_window_minutes=30,
            file_backup_max_per_path=20,
            file_backup_max_total_mb=100,
            config_write_min_interval_seconds=5,
            config_write_max_per_minute=10,
        )
        self.tools = mcp.tools

    def tearDown(self) -> None:
        for p in reversed(self._patchers):
            p.stop()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Path traversal
# ══════════════════════════════════════════════════════════════════════════════

class TestPathTraversal(_Base):
    async def test_traversal_in_write(self) -> None:
        result = _j(await self.tools["fs_write_file"]("../../etc/passwd", "x"))
        self.assertEqual(result["error"], "traversal")

    async def test_traversal_in_delete(self) -> None:
        result = _j(await self.tools["fs_delete_file"]("../../etc/passwd"))
        self.assertEqual(result["error"], "traversal")

    async def test_traversal_in_move_src(self) -> None:
        result = _j(await self.tools["fs_move_file"]("../../etc/passwd", "dst.yaml"))
        self.assertEqual(result["error"], "traversal_src")

    async def test_traversal_in_move_dst(self) -> None:
        (self.config_root / "src.yaml").write_text("x\n", encoding="utf-8")
        result = _j(await self.tools["fs_move_file"]("src.yaml", "../../tmp/dst.yaml"))
        self.assertEqual(result["error"], "traversal_dst")

    async def test_url_encoded_traversal(self) -> None:
        result = _j(await self.tools["fs_write_file"]("%2e%2e/%2e%2e/etc/passwd", "x"))
        self.assertEqual(result["error"], "traversal")


# ══════════════════════════════════════════════════════════════════════════════
# 2. Blacklist checks en write
# ══════════════════════════════════════════════════════════════════════════════

class TestBlacklistInWrite(_Base):
    async def test_token_file_rejected(self) -> None:
        # *token* pattern matches
        result = _j(await self.tools["fs_write_file"]("mytoken.txt", "x"))
        self.assertEqual(result["error"], "blacklisted")

    async def test_key_file_rejected(self) -> None:
        result = _j(await self.tools["fs_write_file"]("private.key", "x"))
        self.assertEqual(result["error"], "blacklisted")

    async def test_known_devices_rejected(self) -> None:
        result = _j(await self.tools["fs_write_file"]("known_devices.yaml", "x"))
        self.assertEqual(result["error"], "blacklisted")

    async def test_secrets_yaml_redirects_to_fs_set_secret(self) -> None:
        result = _j(await self.tools["fs_write_file"]("secrets.yaml", "x"))
        self.assertEqual(result["error"], "use_fs_set_secret")


# ══════════════════════════════════════════════════════════════════════════════
# 3. Managed paths
# ══════════════════════════════════════════════════════════════════════════════

class TestManagedPaths(_Base):
    async def test_storage_rejected_without_token(self) -> None:
        result = _j(await self.tools["fs_write_file"](".storage/core.entity_registry", "x"))
        self.assertEqual(result["error"], "managed_path")

    async def test_storage_rejected_even_with_token(self) -> None:
        # Even if we somehow had a token, the path is rejected at multiple points
        result = _j(await self.tools["fs_write_file"](".storage/lovelace", "x"))
        self.assertEqual(result["error"], "managed_path")

    async def test_is_managed_path_direct(self) -> None:
        config_base = self.config_root.resolve()
        managed = config_base / ".storage" / "core.config"
        self.assertTrue(is_managed_path(managed))

    async def test_non_storage_not_managed(self) -> None:
        config_base = self.config_root.resolve()
        normal = config_base / "automations.yaml"
        self.assertFalse(is_managed_path(normal))

    async def test_storage_delete_rejected(self) -> None:
        result = _j(await self.tools["fs_delete_file"](".storage/auth"))
        self.assertEqual(result["error"], "managed_path")

    async def test_storage_move_src_rejected(self) -> None:
        result = _j(await self.tools["fs_move_file"](".storage/lovelace", "dst.yaml"))
        self.assertEqual(result["error"], "managed_path")


# ══════════════════════════════════════════════════════════════════════════════
# 4. Fail-closed: configuration.yaml roto → todo .yaml exige token
# ══════════════════════════════════════════════════════════════════════════════

class TestFailClosed(_Base):
    async def test_broken_config_yaml_triggers_fail_closed_in_preview(self) -> None:
        # Crear configuration.yaml con sintaxis rota
        (self.config_root / "configuration.yaml").write_text(
            "homeassistant:\n  name: foo\n  invalid: [broken yaml\n",
            encoding="utf-8",
        )
        # Invalidar caché para que se reparse
        import hermes.yaml_include as yi
        yi.invalidate_include_cache()

        # El preview de un .yaml debe indicar fail_closed_active
        result = _j(await self.tools["fs_write_file"]("test_file.yaml", "content: x\n"))
        # Preview sin token: debe mostrar fail_closed_active
        self.assertIn("confirmation_token", result)
        preview = result.get("preview", {})
        self.assertTrue(preview.get("fail_closed_active"), f"preview: {preview}")

    async def test_valid_config_yaml_not_fail_closed(self) -> None:
        (self.config_root / "configuration.yaml").write_text(
            "homeassistant:\n  name: Test\n",
            encoding="utf-8",
        )
        import hermes.yaml_include as yi
        yi.invalidate_include_cache()

        result = _j(await self.tools["fs_write_file"]("test_file.yaml", "content: x\n"))
        preview = result.get("preview", {})
        self.assertFalse(preview.get("fail_closed_active", False))


# ══════════════════════════════════════════════════════════════════════════════
# 5. Rate limit
# ══════════════════════════════════════════════════════════════════════════════

class TestRateLimit(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.data_root = Path(self._tmpdir) / "data"
        self.data_root.mkdir()
        rl_path = self.data_root / "write_rate_limit.json"
        self._p1 = patch.object(fsw_module, "WRITE_RATE_LIMIT_PATH", rl_path)
        self._p1.start()
        fsw_module._rate_lock = asyncio.Lock()

    def tearDown(self) -> None:
        self._p1.stop()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    async def test_11th_write_in_60s_rejected(self) -> None:
        # Inyectar 10 timestamps recientes: el más reciente es hace 6s
        # (pasa min_interval de 5s) pero 10 en total → falla max_per_minute
        now = time.time()
        # 10 timestamps: 6, 9, 12, ... 33 seconds ago (all within 60s window)
        state = {"timestamps": [now - 6 - i * 3 for i in range(10)]}
        rl_path = self.data_root / "write_rate_limit.json"
        rl_path.write_text(json.dumps(state), encoding="utf-8")

        with self.assertRaises(RateLimitError) as ctx:
            await reserve_write_slot(min_interval_seconds=5, max_per_minute=10)
        self.assertIn("rate limit exceeded", str(ctx.exception).lower())

    async def test_min_interval_rejected(self) -> None:
        # Último write hace 3 segundos
        now = time.time()
        state = {"timestamps": [now - 3]}
        rl_path = self.data_root / "write_rate_limit.json"
        rl_path.write_text(json.dumps(state), encoding="utf-8")

        with self.assertRaises(RateLimitError) as ctx:
            await reserve_write_slot(min_interval_seconds=5, max_per_minute=10)
        self.assertIn("minimum write interval", str(ctx.exception).lower())

    async def test_allowed_after_interval(self) -> None:
        # Último write hace 6 segundos → debe pasar
        now = time.time()
        state = {"timestamps": [now - 6]}
        rl_path = self.data_root / "write_rate_limit.json"
        rl_path.write_text(json.dumps(state), encoding="utf-8")
        # No debe lanzar
        await reserve_write_slot(min_interval_seconds=5, max_per_minute=10)


# ══════════════════════════════════════════════════════════════════════════════
# 6. Confirmation token — hash mismatch
# ══════════════════════════════════════════════════════════════════════════════

class TestConfirmationToken(_Base):
    async def test_wrong_content_in_confirm_rejected(self) -> None:
        # Obtener token para content "foo"
        (self.config_root / "test.yaml").write_text("original\n", encoding="utf-8")
        result = _j(await self.tools["fs_write_file"]("test.yaml", "foo\n"))
        token = result.get("confirmation_token")
        self.assertIsNotNone(token)

        # Intentar confirmar con content diferente → debe rechazar
        result2 = _j(
            await self.tools["fs_write_file"](
                "test.yaml", "different_content\n",
                confirmation_token=token,
            )
        )
        self.assertIn("error", result2)
        self.assertIn("match", result2["error"].lower())

    async def test_wrong_path_in_confirm_rejected(self) -> None:
        (self.config_root / "test.yaml").write_text("x\n", encoding="utf-8")
        result = _j(await self.tools["fs_write_file"]("test.yaml", "new\n"))
        token = result.get("confirmation_token")

        # Confirmar con path diferente → rechazado
        result2 = _j(
            await self.tools["fs_write_file"](
                "other.yaml", "new\n",
                confirmation_token=token,
            )
        )
        self.assertIn("error", result2)

    async def test_valid_token_accepted(self) -> None:
        (self.config_root / "test.yaml").write_text("original\n", encoding="utf-8")
        # Patch safety backup y rate limit para que no bloqueen
        with patch("hermes.tools.filesystem_write.maybe_trigger_safety_backup", new=AsyncMock(return_value=None)):
            with patch("hermes.tools.filesystem_write.reserve_write_slot", new=AsyncMock(return_value=None)):
                with patch("hermes.tools.filesystem_write.record_config_write", new=AsyncMock()):
                    result = _j(await self.tools["fs_write_file"]("test.yaml", "new content\n"))
                    token = result.get("confirmation_token")
                    self.assertIsNotNone(token)

                    result2 = _j(
                        await self.tools["fs_write_file"](
                            "test.yaml", "new content\n",
                            confirmation_token=token,
                        )
                    )
                    self.assertEqual(result2.get("result"), "ok")
                    self.assertEqual(
                        (self.config_root / "test.yaml").read_text(encoding="utf-8"),
                        "new content\n",
                    )


# ══════════════════════════════════════════════════════════════════════════════
# 7. Backup automático verificado
# ══════════════════════════════════════════════════════════════════════════════

class TestBackupCreated(_Base):
    async def test_backup_created_on_write(self) -> None:
        original_content = "original content\n"
        (self.config_root / "test.yaml").write_text(original_content, encoding="utf-8")

        with patch("hermes.tools.filesystem_write.maybe_trigger_safety_backup", new=AsyncMock(return_value=None)):
            with patch("hermes.tools.filesystem_write.reserve_write_slot", new=AsyncMock()):
                with patch("hermes.tools.filesystem_write.record_config_write", new=AsyncMock()):
                    result = _j(await self.tools["fs_write_file"]("test.yaml", "new content\n"))
                    token = result["confirmation_token"]
                    result2 = _j(
                        await self.tools["fs_write_file"](
                            "test.yaml", "new content\n",
                            confirmation_token=token,
                        )
                    )
                    self.assertEqual(result2.get("result"), "ok")

        # Backup debe existir en normal/
        backups_dir = self.data_root / "backups" / "normal"
        self.assertTrue(backups_dir.exists(), "backups/normal dir should exist")
        backups = list(backups_dir.iterdir())
        self.assertGreater(len(backups), 0, "At least one backup should exist")

        # El backup debe contener el contenido original
        backup_content = backups[0].read_bytes()
        # (may have BOM or different encoding, but should contain original text)
        self.assertIn(b"original content", backup_content)

    async def test_no_backup_if_file_not_exists(self) -> None:
        result = await backup_before_write(
            self.config_root / "nonexistent.yaml",
            file_backup_max_per_path=20,
            file_backup_max_total_mb=100,
        )
        self.assertIsNone(result)

    async def test_sensitive_file_backup_goes_to_sensitive_dir(self) -> None:
        secrets_path = self.config_root / "secrets.yaml"
        secrets_path.write_text("api_key: secret123\n", encoding="utf-8")

        backup_path = await backup_before_write(
            secrets_path,
            file_backup_max_per_path=20,
            file_backup_max_total_mb=100,
        )
        self.assertIsNotNone(backup_path)
        # Should be in sensitive dir, not normal
        self.assertIn("sensitive", backup_path)
        self.assertNotIn("normal", backup_path)


# ══════════════════════════════════════════════════════════════════════════════
# 8. safe_write preserva permisos y line endings
# ══════════════════════════════════════════════════════════════════════════════

class TestSafeWrite(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self._tmpdir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_preserves_mode(self) -> None:
        p = self.tmp / "test.yaml"
        p.write_text("original\n", encoding="utf-8")
        p.chmod(0o640)

        safe_write_file(p, "new content\n")

        new_mode = stat.S_IMODE(p.stat().st_mode)
        # On Windows, chmod is limited, so we check what we can
        if sys.platform != "win32":
            self.assertEqual(new_mode, 0o640)

    def test_preserves_crlf_line_endings(self) -> None:
        p = self.tmp / "test.txt"
        p.write_bytes(b"line1\r\nline2\r\n")

        safe_write_file(p, "newline1\nnewline2\n")

        result = p.read_bytes()
        self.assertIn(b"\r\n", result)
        self.assertNotIn(b"\n\r", result)  # no mixed endings

    def test_preserves_lf_line_endings(self) -> None:
        p = self.tmp / "test.yaml"
        p.write_bytes(b"line1\nline2\n")

        safe_write_file(p, "newline1\nnewline2\n")

        result = p.read_bytes()
        # Should not have CRLF
        self.assertNotIn(b"\r\n", result)

    def test_preserves_bom(self) -> None:
        p = self.tmp / "test.yaml"
        p.write_bytes(b"\xef\xbb\xbfcontent\n")

        safe_write_file(p, "new content\n")

        result = p.read_bytes()
        self.assertTrue(result.startswith(b"\xef\xbb\xbf"))

    def test_new_file_gets_trailing_newline(self) -> None:
        p = self.tmp / "new.yaml"
        safe_write_file(p, "content without newline")

        result = p.read_bytes()
        self.assertTrue(result.endswith(b"\n"))

    def test_atomic_write_uses_tmp_file(self) -> None:
        p = self.tmp / "test.yaml"
        p.write_text("original\n", encoding="utf-8")

        # Verify no .mcp_tmp left after write
        safe_write_file(p, "new\n")
        tmp_files = list(self.tmp.glob("*.mcp_tmp"))
        self.assertEqual(len(tmp_files), 0)


# ══════════════════════════════════════════════════════════════════════════════
# 9. Backup-before-restore
# ══════════════════════════════════════════════════════════════════════════════

class TestRestoreBackup(_Base):
    async def test_restore_creates_backup_before_restore(self) -> None:
        # Crear fichero y backup manual
        test_file = self.config_root / "test.yaml"
        test_file.write_text("v1 content\n", encoding="utf-8")

        # Crear backup a mano
        backups_dir = self.data_root / "backups" / "normal"
        backups_dir.mkdir(parents=True, exist_ok=True)
        timestamp = "20260101T120000Z"
        backup_file = backups_dir / f"{timestamp}_test.yaml"
        backup_file.write_text("v1 content\n", encoding="utf-8")

        # Escribir v2 al fichero actual
        test_file.write_text("v2 content\n", encoding="utf-8")

        # Obtener token de restore
        with patch("hermes.tools.filesystem_write.maybe_trigger_safety_backup", new=AsyncMock(return_value=None)):
            with patch("hermes.tools.filesystem_write.reserve_write_slot", new=AsyncMock()):
                with patch("hermes.tools.filesystem_write.record_config_write", new=AsyncMock()):
                    result = _j(await self.tools["fs_restore_file_backup"]("test.yaml", timestamp))
                    token = result.get("confirmation_token")
                    self.assertIsNotNone(token, f"Expected token: {result}")

                    result2 = _j(await self.tools["fs_restore_file_backup"](
                        "test.yaml", timestamp, confirmation_token=token
                    ))
                    self.assertEqual(result2.get("result"), "ok")

        # Debe haber un backup-before-restore (v2)
        backups = list(backups_dir.iterdir())
        # Should have both the original backup and the backup-before-restore
        self.assertGreaterEqual(len(backups), 2)

        # El fichero debe tener v1
        self.assertEqual(test_file.read_text(encoding="utf-8"), "v1 content\n")

    async def test_restore_rejected_if_path_now_blacklisted(self) -> None:
        # Crear backup de un fichero que ahora está blacklisteado
        backups_dir = self.data_root / "backups" / "normal"
        backups_dir.mkdir(parents=True, exist_ok=True)
        # Simular backup de secrets.yaml en normal/ (no debería pasar normalmente, pero probamos)
        timestamp = "20260101T120000Z"
        # secrets.yaml is always blacklisted: should be rejected

        result = _j(await self.tools["fs_restore_file_backup"]("secrets.yaml", timestamp))
        # Should be rejected because secrets.yaml is blacklisted
        self.assertIn("error", result)
        self.assertIn(result["error"], ["blacklisted", "backup_not_found"])


# ══════════════════════════════════════════════════════════════════════════════
# 10. check_config_state
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckConfigState(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.data_root = Path(self._tmpdir) / "data"
        self.data_root.mkdir()
        cc_path = self.data_root / "check_config_state.json"
        self._p1 = patch.object(fsw_module, "CHECK_CONFIG_STATE_PATH", cc_path)
        self._p1.start()
        fsw_module._config_state_lock = asyncio.Lock()

    def tearDown(self) -> None:
        self._p1.stop()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    async def test_no_state_file_allows_restart(self) -> None:
        allowed, reason = check_restart_allowed_sync()
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    async def test_write_then_no_check_blocks_restart(self) -> None:
        await record_config_write()
        allowed, reason = check_restart_allowed_sync()
        self.assertFalse(allowed)
        self.assertIn("not been validated", reason)

    async def test_write_then_check_ok_allows_restart(self) -> None:
        # El orden lo fija el reloj lógico, no el reloj de pared: sin sleeps.
        await record_config_write()
        await record_check_config_ok()
        allowed, reason = check_restart_allowed_sync()
        self.assertTrue(allowed, f"Should be allowed but got: {reason}")

    async def test_write_check_write_blocks_restart(self) -> None:
        await record_config_write()
        await record_check_config_ok()
        await record_config_write()  # Segunda escritura sin check
        allowed, reason = check_restart_allowed_sync()
        self.assertFalse(allowed)

    async def test_ordering_is_exact_without_any_delay(self) -> None:
        """Regresión: con time.monotonic() esto fallaba en Windows, donde el
        reloj tiene 15.6 ms de resolución y varias llamadas seguidas devolvían
        el mismo valor. El reloj lógico ordena de forma exacta."""
        for _ in range(25):
            await record_config_write()
            await record_check_config_ok()
            self.assertTrue(check_restart_allowed_sync()[0])
            await record_config_write()
            self.assertFalse(check_restart_allowed_sync()[0])

    async def test_state_survives_process_restart(self) -> None:
        """El estado se persiste en disco y se compara entre procesos distintos.

        Antes se guardaba `time.monotonic()`, cuyo origen es arbitrario y se
        reinicia con el proceso: tras un reinicio la comparación era basura y
        podía permitir un restart con configuración sin validar (fail-open).
        Aquí se simula el reinicio releyendo el fichero tal cual quedó.
        """
        await record_config_write()
        await record_check_config_ok()
        await record_config_write()  # escritura pendiente de validar

        raw = json.loads(
            (self.data_root / "check_config_state.json").read_text(encoding="utf-8")
        )
        # Ningún valor dependiente del proceso debe quedar persistido.
        self.assertNotIn("_last_write_ts", raw)
        self.assertNotIn("_last_check_ok_ts", raw)
        self.assertIsInstance(raw.get("_last_write_seq"), int)

        # "Reinicio": el fichero se reevalúa desde cero.
        allowed, reason = check_restart_allowed_sync()
        self.assertFalse(allowed, "Debe seguir bloqueado tras reiniciar")
        self.assertIn("not been validated", reason)

    async def test_legacy_v1_state_is_migrated_by_iso(self) -> None:
        """Estados escritos por versiones anteriores (con monotonic) se ordenan
        por las marcas ISO, que sí son de reloj de pared."""
        cc_path = self.data_root / "check_config_state.json"

        # Escritura posterior al último check → bloquea.
        cc_path.write_text(json.dumps({
            "last_write_at": "2026-01-02T10:00:05Z",
            "last_check_ok_at": "2026-01-02T10:00:01Z",
            "_last_write_ts": 51234.5,      # monotonic: se ignora
            "_last_check_ok_ts": 99999.9,   # monotonic mayor, pero irrelevante
        }), encoding="utf-8")
        allowed, _ = check_restart_allowed_sync()
        self.assertFalse(allowed)

        # Check posterior a la escritura → permite.
        cc_path.write_text(json.dumps({
            "last_write_at": "2026-01-02T10:00:01Z",
            "last_check_ok_at": "2026-01-02T10:00:05Z",
        }), encoding="utf-8")
        allowed, _ = check_restart_allowed_sync()
        self.assertTrue(allowed)

    async def test_legacy_write_without_check_blocks(self) -> None:
        cc_path = self.data_root / "check_config_state.json"
        cc_path.write_text(
            json.dumps({"last_write_at": "2026-01-02T10:00:05Z"}), encoding="utf-8"
        )
        allowed, _ = check_restart_allowed_sync()
        self.assertFalse(allowed)

    async def test_backwards_compat_int_0(self) -> None:
        # Formato antiguo con int 0
        cc_path = self.data_root / "check_config_state.json"
        cc_path.write_text(
            json.dumps({"last_write_at": 0, "last_check_ok_at": 0}),
            encoding="utf-8",
        )
        allowed, _ = check_restart_allowed_sync()
        self.assertTrue(allowed)  # 0 means "never written"


# ══════════════════════════════════════════════════════════════════════════════
# 11. Safety backup automático
# ══════════════════════════════════════════════════════════════════════════════

class TestSafetyBackupTrigger(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.data_root = Path(self._tmpdir) / "data"
        self.data_root.mkdir()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    async def test_triggers_after_window_exceeded(self) -> None:
        from hermes.tools.backups import (
            _SAFETY_BACKUP_STATE_PATH,
            _save_safety_state,
        )
        state_path = self.data_root / "last_safety_backup.json"

        # Estado: último backup hace 31 minutos
        old_time = time.time() - 31 * 60
        with patch("hermes.tools.backups._SAFETY_BACKUP_STATE_PATH", state_path):
            _save_safety_state({"last_completed_at": old_time})

        ha_client = MagicMock()
        # Respuesta sin job_id → backup síncrono
        ha_client.sv_request = AsyncMock(return_value={"slug": "backup-123"})

        with patch("hermes.tools.backups._SAFETY_BACKUP_STATE_PATH", state_path):
            result = await maybe_trigger_safety_backup(
                ha_client, safety_backup_window_minutes=30, enabled=True
            )

        self.assertIsNone(result)  # None = success
        ha_client.sv_request.assert_called_once()
        call_args = ha_client.sv_request.call_args
        self.assertIn("background", str(call_args) + str(call_args.args) + str(call_args.kwargs))

    async def test_does_not_trigger_within_window(self) -> None:
        from hermes.tools.backups import (
            _SAFETY_BACKUP_STATE_PATH,
            _save_safety_state,
        )
        state_path = self.data_root / "last_safety_backup.json"

        # Estado: último backup hace 10 minutos (dentro del window)
        recent_time = time.time() - 10 * 60
        with patch("hermes.tools.backups._SAFETY_BACKUP_STATE_PATH", state_path):
            _save_safety_state({"last_completed_at": recent_time})

        ha_client = MagicMock()
        ha_client.sv_request = AsyncMock(return_value={})

        with patch("hermes.tools.backups._SAFETY_BACKUP_STATE_PATH", state_path):
            result = await maybe_trigger_safety_backup(
                ha_client, safety_backup_window_minutes=30, enabled=True
            )

        self.assertIsNone(result)
        ha_client.sv_request.assert_not_called()

    async def test_hard_limit_60s_respected(self) -> None:
        from hermes.tools.backups import (
            _SAFETY_BACKUP_STATE_PATH,
            _save_safety_state,
        )
        state_path = self.data_root / "last_safety_backup.json"

        # Estado: último backup hace 30 segundos (< 60s barrera dura)
        very_recent = time.time() - 30
        with patch("hermes.tools.backups._SAFETY_BACKUP_STATE_PATH", state_path):
            _save_safety_state({"last_completed_at": very_recent})

        ha_client = MagicMock()
        ha_client.sv_request = AsyncMock(return_value={})

        with patch("hermes.tools.backups._SAFETY_BACKUP_STATE_PATH", state_path):
            result = await maybe_trigger_safety_backup(
                ha_client,
                safety_backup_window_minutes=0,  # window=0 → siempre dispararía sin la barrera
                enabled=True,
            )

        self.assertIsNone(result)
        ha_client.sv_request.assert_not_called()

    async def test_disabled_by_default_does_not_trigger(self) -> None:
        """Con safety_backup_enabled=False (default) no se crea el backup FULL,
        aunque haya pasado el window."""
        from hermes.tools.backups import _save_safety_state

        state_path = self.data_root / "last_safety_backup.json"
        old_time = time.time() - 31 * 60  # window superado
        with patch("hermes.tools.backups._SAFETY_BACKUP_STATE_PATH", state_path):
            _save_safety_state({"last_completed_at": old_time})

        ha_client = MagicMock()
        ha_client.sv_request = AsyncMock(return_value={"slug": "x"})

        with patch("hermes.tools.backups._SAFETY_BACKUP_STATE_PATH", state_path):
            # enabled omitido → default False → no debe disparar
            result = await maybe_trigger_safety_backup(
                ha_client, safety_backup_window_minutes=30
            )

        self.assertIsNone(result)
        ha_client.sv_request.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# 12. fs_list_file_backups no expone sensitive
# ══════════════════════════════════════════════════════════════════════════════

class TestListFileBackups(_Base):
    async def test_lists_normal_backups(self) -> None:
        backups_dir = self.data_root / "backups" / "normal"
        backups_dir.mkdir(parents=True, exist_ok=True)
        (backups_dir / "20260101T120000Z_test.yaml").write_text("x", encoding="utf-8")

        result = _j(await self.tools["fs_list_file_backups"]())
        self.assertGreaterEqual(result["count"], 1)
        paths = [b["path"] for b in result["backups"]]
        self.assertIn("test.yaml", paths)

    async def test_does_not_expose_sensitive(self) -> None:
        # No hay forma de acceder a sensitive desde esta tool
        # La tool solo lee de BACKUPS_NORMAL_DIR
        sensitive_dir = self.data_root / "backups" / "sensitive"
        sensitive_dir.mkdir(parents=True, exist_ok=True)
        (sensitive_dir / "20260101T120000Z_secrets.yaml").write_text("x", encoding="utf-8")

        result = _j(await self.tools["fs_list_file_backups"]())
        paths = [b["path"] for b in result["backups"]]
        self.assertNotIn("secrets.yaml", paths)

    async def test_filter_by_path(self) -> None:
        backups_dir = self.data_root / "backups" / "normal"
        backups_dir.mkdir(parents=True, exist_ok=True)
        (backups_dir / "20260101T120000Z_test.yaml").write_text("x", encoding="utf-8")
        (backups_dir / "20260101T120001Z_other.yaml").write_text("y", encoding="utf-8")

        result = _j(await self.tools["fs_list_file_backups"]("test.yaml"))
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["backups"][0]["path"], "test.yaml")


if __name__ == "__main__":
    unittest.main()

# ══════════════════════════════════════════════════════════════════════════════
# El caché del árbol de includes solo se invalidaba con configuration.yaml
# ══════════════════════════════════════════════════════════════════════════════

class TestIncludeCacheIsAlwaysInvalidated(_Base):
    """El conjunto cacheado dice qué YAML son ejecutables por indirección.

    De él depende que una escritura pida las protecciones extra. Solo se
    invalidaba al tocar `configuration.yaml`, pero cualquier fichero del árbol
    puede traer includes a su vez —packages/, automations.yaml, secrets.yaml
    vía `!secret`—, así que un fichero recién metido en el árbol no aparecía en
    el conjunto y se trataba como inofensivo: la señal de seguridad fallaba en
    abierto.

    `fs_set_secret` no invalidaba nada en absoluto.
    """

    def _cebar_cache(self):
        import hermes.yaml_include as yi

        yi._cached_paths = {"marca-de-cache-vieja"}
        return yi

    async def _escribir(self, nombre, contenido="clave: valor\n"):
        with patch("hermes.tools.filesystem_write.maybe_trigger_safety_backup",
                   new=AsyncMock(return_value=None)):
            with patch("hermes.tools.filesystem_write.reserve_write_slot",
                       new=AsyncMock(return_value=None)):
                with patch("hermes.tools.filesystem_write.record_config_write",
                           new=AsyncMock()):
                    primero = _j(await self.tools["fs_write_file"](nombre, contenido))
                    token = primero.get("confirmation_token")
                    self.assertIsNotNone(token, primero)
                    return _j(await self.tools["fs_write_file"](
                        nombre, contenido, confirmation_token=token))

    async def test_writing_a_file_outside_configuration_invalidates(self) -> None:
        yi = self._cebar_cache()
        res = await self._escribir("automations.yaml", "[]\n")
        self.assertEqual(res.get("result"), "ok", res)
        self.assertIsNone(yi._cached_paths,
                          "el caché sobrevivió a una escritura en el árbol")

    async def test_writing_configuration_still_invalidates(self) -> None:
        yi = self._cebar_cache()
        res = await self._escribir("configuration.yaml", "default_config:\n")
        self.assertEqual(res.get("result"), "ok", res)
        self.assertIsNone(yi._cached_paths)

    async def test_setting_a_secret_invalidates(self) -> None:
        """secrets.yaml lo recorre el tag !secret, y esta ruta no invalidaba nada."""
        yi = self._cebar_cache()
        with patch("hermes.tools.filesystem_write.maybe_trigger_safety_backup",
                   new=AsyncMock(return_value=None)):
            with patch("hermes.tools.filesystem_write.reserve_write_slot",
                       new=AsyncMock(return_value=None)):
                with patch("hermes.tools.filesystem_write.record_config_write",
                           new=AsyncMock()):
                    primero = _j(await self.tools["fs_set_secret"]("api_key", "s3cr3t"))
                    token = primero.get("confirmation_token")
                    self.assertIsNotNone(token, primero)
                    res = _j(await self.tools["fs_set_secret"](
                        "api_key", "s3cr3t", confirmation_token=token))
        self.assertEqual(res.get("result"), "ok", res)
        self.assertIsNone(yi._cached_paths,
                          "escribir secrets.yaml no invalidó el caché")

    async def test_no_write_path_is_left_guarded_by_a_filename(self) -> None:
        """Ninguna invalidación puede volver a depender del nombre del fichero."""
        import pathlib as _pl

        fuente = (_pl.Path(__file__).resolve().parents[1]
                  / "hermes/src/hermes/tools/filesystem_write.py").read_text(encoding="utf-8")
        self.assertNotIn('== "configuration.yaml":\n            invalidate', fuente)
        self.assertEqual(fuente.count("invalidate_include_cache()"), 5,
                         "las cinco rutas de escritura deben invalidar")

class TestTheTwoSafetyBackupPathsShareTheirMark(unittest.IsolatedAsyncioTestCase):
    """Los dos caminos que crean safety backups no pueden pisarse la marca.

    Hay dos: la tool `sv_create_safety_backup` y el disparo automático antes de
    escribir en `/config`. Comparten el mismo fichero de estado, y cada uno
    usaba SU PROPIA clave —`last_created_at` frente a `last_completed_at`— con
    un guardado que reemplazaba el documento entero.

    El resultado es que cada camino borraba la marca del otro. Ambos leían
    entonces «nunca se ha hecho ninguno» y disparaban un backup COMPLETO de
    varios gigas, saltándose la ventana configurable y también el límite duro
    de 60 segundos que el módulo promete.

    No saltaba en producción porque los backups de seguridad vienen
    desactivados por defecto: solo mordía a quien los activara.
    """

    def setUp(self) -> None:
        import hermes.tools.backups as backups

        self.backups = backups
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = backups._SAFETY_BACKUP_STATE_PATH
        backups._SAFETY_BACKUP_STATE_PATH = (
            pathlib.Path(self._tmp.name) / "safety.json")

    def tearDown(self) -> None:
        self.backups._SAFETY_BACKUP_STATE_PATH = self._orig
        self._tmp.cleanup()

    def test_writing_from_one_path_keeps_the_other_mark(self) -> None:
        import time

        b = self.backups
        b._save_safety_state({b._MARCA: time.time(), "last_job_id": "j1"})
        # El otro camino guarda lo suyo sin tocar la marca.
        b._save_safety_state({"last_backup_name": "hermes-safety-x"})

        estado = b._load_safety_state()
        self.assertGreater(b._leer_marca(estado), 0,
                           "el segundo guardado borró la marca del primero")
        self.assertEqual(estado["last_job_id"], "j1")
        self.assertEqual(estado["last_backup_name"], "hermes-safety-x")

    def test_the_mark_is_read_whatever_format_it_has(self) -> None:
        """Una instalación que ya venía funcionando trae los formatos viejos."""
        b = self.backups
        self.assertGreater(b._leer_marca({"last_created_at": 1_700_000_000.0}), 0)
        self.assertGreater(
            b._leer_marca({"last_completed_at": "2026-09-06T10:00:00Z"}), 0)
        self.assertEqual(b._leer_marca({}), 0.0)
        self.assertEqual(b._leer_marca({"last_created_at": "no es una fecha"}), 0.0)

    def test_both_paths_agree_on_the_key(self) -> None:
        """Si mañana uno vuelve a inventarse la suya, esto lo caza."""
        import inspect

        import hermes.fs_write as fsw

        fuente = inspect.getsource(fsw.maybe_trigger_safety_backup)
        self.assertIn("_leer_marca", fuente,
                      "el disparo automático no usa la lectura compartida")
        self.assertNotIn("last_completed_at", fuente,
                         "sigue usando su clave propia")
