"""Tests de tool-level para hermes.tools.filesystem.

Usa tmp_path para crear un /config falso y monkeypatch de CONFIG_BASE.
No requiere HAClient ni fixtures de red.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import hermes.fs as fs_module
from hermes.tools.filesystem import register


# ── Helpers ───────────────────────────────────────────────────────────────────


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _j(raw: str | dict) -> dict:
    if isinstance(raw, dict):
        return raw
    return json.loads(raw)


def _make_tools(tmp_root: Path, response_max_bytes: int = 1_048_576) -> dict:
    mcp = DummyMCP()
    register(mcp, response_max_bytes=response_max_bytes)
    return mcp.tools


# ══════════════════════════════════════════════════════════════════════════════
# fs_read_file
# ══════════════════════════════════════════════════════════════════════════════

class TestFsReadFile(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self.root = Path(self._tmpdir) / "config"
        self.root.mkdir()
        self._patcher = patch.object(fs_module, "CONFIG_BASE", self.root.resolve())
        self._patcher.start()
        self.tools = _make_tools(self.root)

    def tearDown(self) -> None:
        self._patcher.stop()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    async def test_reads_utf8_file(self) -> None:
        (self.root / "automations.yaml").write_bytes(b"automation: []\n")
        result = _j(await self.tools["fs_read_file"]("automations.yaml"))
        self.assertEqual(result["path"], "automations.yaml")
        self.assertIn("automation: []", result["content"])
        self.assertEqual(result["encoding"], "utf-8")
        self.assertEqual(result["line_count"], 1)
        self.assertIsNone(result.get("truncated"))

    async def test_reads_with_absolute_path(self) -> None:
        (self.root / "scripts.yaml").write_text("script: {}", encoding="utf-8")
        result = _j(await self.tools["fs_read_file"]("/config/scripts.yaml"))
        self.assertEqual(result["path"], "scripts.yaml")
        self.assertIn("script", result["content"])

    async def test_traversal_returns_error(self) -> None:
        result = _j(await self.tools["fs_read_file"]("../../etc/passwd"))
        self.assertEqual(result["error"], "traversal")

    async def test_blacklisted_returns_error(self) -> None:
        (self.root / "secrets.yaml").write_text("api_key: hunter2", encoding="utf-8")
        result = _j(await self.tools["fs_read_file"]("secrets.yaml"))
        self.assertEqual(result["error"], "blacklisted")

    async def test_not_found_returns_error(self) -> None:
        result = _j(await self.tools["fs_read_file"]("nonexistent.yaml"))
        self.assertEqual(result["error"], "not_found")

    async def test_directory_returns_error(self) -> None:
        (self.root / "subdir").mkdir()
        result = _j(await self.tools["fs_read_file"]("subdir"))
        self.assertEqual(result["error"], "is_directory")
        self.assertIn("fs_list_dir", result.get("hint", ""))

    async def test_binary_file_returns_error(self) -> None:
        (self.root / "data.bin").write_bytes(b"\x00\x01\x02binary data")
        result = _j(await self.tools["fs_read_file"]("data.bin"))
        self.assertEqual(result["error"], "binary_file")

    async def test_utf8_bom_file(self) -> None:
        content = "homeassistant:\n  name: Home\n"
        bom_content = b"\xef\xbb\xbf" + content.encode("utf-8")
        (self.root / "bom.yaml").write_bytes(bom_content)
        result = _j(await self.tools["fs_read_file"]("bom.yaml"))
        self.assertEqual(result["encoding"], "utf-8-bom")
        self.assertTrue(result["content"].startswith("homeassistant:"))

    async def test_truncation_at_line_boundary(self) -> None:
        tiny_tools = _make_tools(self.root, response_max_bytes=512)
        lines = [f"line_{i}: value_{i}\n" for i in range(200)]
        (self.root / "big.yaml").write_text("".join(lines), encoding="utf-8")
        result = _j(await tiny_tools["fs_read_file"]("big.yaml"))
        self.assertTrue(result.get("truncated"))
        self.assertIn("truncated_at_line", result)
        self.assertEqual(result["line_count"], 200)
        self.assertIn("fs_read_file_lines", result.get("hint", ""))

    async def test_storage_allowlist_ok(self) -> None:
        storage = self.root / ".storage"
        storage.mkdir()
        (storage / "core.entity_registry").write_text('{"entities": []}', encoding="utf-8")
        result = _j(await self.tools["fs_read_file"](".storage/core.entity_registry"))
        self.assertIsNone(result.get("error"))
        self.assertIn("entities", result["content"])

    async def test_storage_unknown_rejected(self) -> None:
        storage = self.root / ".storage"
        storage.mkdir()
        (storage / "random_unknown").write_text("{}", encoding="utf-8")
        result = _j(await self.tools["fs_read_file"](".storage/random_unknown"))
        self.assertEqual(result["error"], "blacklisted")

    async def test_key_file_rejected(self) -> None:
        (self.root / "server.key").write_text("-----BEGIN PRIVATE KEY-----", encoding="utf-8")
        result = _j(await self.tools["fs_read_file"]("server.key"))
        self.assertEqual(result["error"], "blacklisted")


# ══════════════════════════════════════════════════════════════════════════════
# fs_read_file_lines
# ══════════════════════════════════════════════════════════════════════════════

class TestFsReadFileLines(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self.root = Path(self._tmpdir) / "config"
        self.root.mkdir()
        self._patcher = patch.object(fs_module, "CONFIG_BASE", self.root.resolve())
        self._patcher.start()
        self.tools = _make_tools(self.root)

    def tearDown(self) -> None:
        self._patcher.stop()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    async def test_reads_all_lines(self) -> None:
        (self.root / "test.yaml").write_bytes(b"line1\nline2\nline3\n")
        result = _j(await self.tools["fs_read_file_lines"]("test.yaml", offset=0, limit=10))
        self.assertEqual(result["total_lines"], 3)
        self.assertEqual(result["returned_lines"], 3)
        self.assertEqual(len(result["lines"]), 3)
        self.assertIn("line1", result["lines"][0])

    async def test_pagination_offset(self) -> None:
        lines = [f"line{i}\n" for i in range(10)]
        (self.root / "paged.yaml").write_bytes("".join(lines).encode("utf-8"))
        result = _j(await self.tools["fs_read_file_lines"]("paged.yaml", offset=5, limit=3))
        self.assertEqual(result["offset"], 5)
        self.assertEqual(result["returned_lines"], 3)
        self.assertIn("line5", result["lines"][0])

    async def test_offset_beyond_end(self) -> None:
        (self.root / "short.yaml").write_text("only one line\n", encoding="utf-8")
        result = _j(await self.tools["fs_read_file_lines"]("short.yaml", offset=100, limit=10))
        self.assertEqual(result["returned_lines"], 0)
        self.assertEqual(result["lines"], [])

    async def test_limit_clamped_to_max(self) -> None:
        (self.root / "test.yaml").write_text("a\n", encoding="utf-8")
        result = _j(await self.tools["fs_read_file_lines"]("test.yaml", offset=0, limit=99999))
        self.assertEqual(result["limit"], 5000)

    async def test_blacklisted_rejected(self) -> None:
        (self.root / "secrets.yaml").write_text("secret: xxx", encoding="utf-8")
        result = _j(await self.tools["fs_read_file_lines"]("secrets.yaml"))
        self.assertEqual(result["error"], "blacklisted")

    async def test_traversal_rejected(self) -> None:
        result = _j(await self.tools["fs_read_file_lines"]("../../etc/passwd"))
        self.assertEqual(result["error"], "traversal")


# ══════════════════════════════════════════════════════════════════════════════
# fs_list_dir
# ══════════════════════════════════════════════════════════════════════════════

class TestFsListDir(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self.root = Path(self._tmpdir) / "config"
        self.root.mkdir()
        self._patcher = patch.object(fs_module, "CONFIG_BASE", self.root.resolve())
        self._patcher.start()
        self.tools = _make_tools(self.root)

    def tearDown(self) -> None:
        self._patcher.stop()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    async def test_lists_root(self) -> None:
        (self.root / "automations.yaml").write_text("", encoding="utf-8")
        (self.root / "configuration.yaml").write_text("", encoding="utf-8")
        result = _j(await self.tools["fs_list_dir"]("."))
        self.assertEqual(result["path"], ".")
        names = {e["name"] for e in result["entries"]}
        self.assertIn("automations.yaml", names)
        self.assertIn("configuration.yaml", names)

    async def test_secrets_shown_blacklisted(self) -> None:
        (self.root / "secrets.yaml").write_text("key: val", encoding="utf-8")
        result = _j(await self.tools["fs_list_dir"]("."))
        secrets_entry = next(
            (e for e in result["entries"] if e["name"] == "secrets.yaml"), None
        )
        self.assertIsNotNone(secrets_entry)
        self.assertTrue(secrets_entry["is_blacklisted"])

    async def test_regular_file_not_blacklisted(self) -> None:
        (self.root / "automations.yaml").write_text("", encoding="utf-8")
        result = _j(await self.tools["fs_list_dir"]("."))
        auto_entry = next(
            (e for e in result["entries"] if e["name"] == "automations.yaml"), None
        )
        self.assertIsNotNone(auto_entry)
        self.assertFalse(auto_entry["is_blacklisted"])

    async def test_traversal_rejected(self) -> None:
        result = _j(await self.tools["fs_list_dir"]("../../etc"))
        self.assertEqual(result["error"], "traversal")

    async def test_not_a_directory(self) -> None:
        (self.root / "file.yaml").write_text("", encoding="utf-8")
        result = _j(await self.tools["fs_list_dir"]("file.yaml"))
        self.assertEqual(result["error"], "not_a_directory")

    async def test_not_found(self) -> None:
        result = _j(await self.tools["fs_list_dir"]("nonexistent"))
        self.assertEqual(result["error"], "not_found")

    async def test_entry_fields(self) -> None:
        (self.root / "test.yaml").write_text("x: 1", encoding="utf-8")
        result = _j(await self.tools["fs_list_dir"]("."))
        entry = next(e for e in result["entries"] if e["name"] == "test.yaml")
        self.assertEqual(entry["type"], "file")
        self.assertIsNotNone(entry["size_bytes"])
        self.assertIsNotNone(entry["modified"])

    async def test_recursive_lists_subdir(self) -> None:
        sub = self.root / "packages"
        sub.mkdir()
        (sub / "lights.yaml").write_text("", encoding="utf-8")
        result = _j(await self.tools["fs_list_dir"](".", recursive=True, max_depth=2))
        names = {e["name"] for e in result["entries"]}
        self.assertIn("packages", names)
        self.assertIn("lights.yaml", names)

    async def test_storage_dir_listed_with_flags(self) -> None:
        storage = self.root / ".storage"
        storage.mkdir()
        (storage / "core.entity_registry").write_text("{}", encoding="utf-8")
        (storage / "random_unknown").write_text("{}", encoding="utf-8")
        result = _j(await self.tools["fs_list_dir"](".storage"))
        names = {e["name"] for e in result["entries"]}
        self.assertIn("core.entity_registry", names)
        self.assertIn("random_unknown", names)
        er = next(e for e in result["entries"] if e["name"] == "core.entity_registry")
        rn = next(e for e in result["entries"] if e["name"] == "random_unknown")
        self.assertFalse(er["is_blacklisted"])
        self.assertTrue(rn["is_blacklisted"])


# ══════════════════════════════════════════════════════════════════════════════
# fs_search_in_config
# ══════════════════════════════════════════════════════════════════════════════

class TestFsSearchInConfig(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self.root = Path(self._tmpdir) / "config"
        self.root.mkdir()
        self._patcher = patch.object(fs_module, "CONFIG_BASE", self.root.resolve())
        self._patcher.start()
        self.tools = _make_tools(self.root)

    def tearDown(self) -> None:
        self._patcher.stop()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    async def test_finds_pattern(self) -> None:
        (self.root / "configuration.yaml").write_text(
            "homeassistant:\n  name: My Home\ninfluxdb:\n  host: localhost\n",
            encoding="utf-8",
        )
        result = _j(await self.tools["fs_search_in_config"]("influxdb"))
        self.assertGreaterEqual(result["count"], 1)
        self.assertEqual(result["matches"][0]["path"], "configuration.yaml")
        self.assertEqual(result["matches"][0]["line_number"], 3)
        self.assertIn("influxdb", result["matches"][0]["match"].lower())

    async def test_case_insensitive_default(self) -> None:
        (self.root / "test.yaml").write_text("Homeassistant:\n  Name: Test\n", encoding="utf-8")
        result = _j(await self.tools["fs_search_in_config"]("homeassistant"))
        self.assertGreaterEqual(result["count"], 1)

    async def test_case_sensitive_option(self) -> None:
        (self.root / "test.yaml").write_text("Homeassistant:\nhomeassistant:\n", encoding="utf-8")
        result = _j(await self.tools["fs_search_in_config"]("Homeassistant", case_sensitive=True))
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["matches"][0]["line_number"], 1)

    async def test_no_matches(self) -> None:
        (self.root / "test.yaml").write_text("foo: bar\n", encoding="utf-8")
        result = _j(await self.tools["fs_search_in_config"]("zzznomatch"))
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["matches"], [])

    async def test_secrets_not_searched(self) -> None:
        (self.root / "secrets.yaml").write_text("api_key: hunter2\n", encoding="utf-8")
        (self.root / "configuration.yaml").write_text("foo: bar\n", encoding="utf-8")
        result = _j(await self.tools["fs_search_in_config"]("hunter2"))
        self.assertEqual(result["count"], 0)
        self.assertGreaterEqual(result["skipped_files"], 1)

    async def test_token_file_not_searched(self) -> None:
        (self.root / "access_token.txt").write_text("token: secret123\n", encoding="utf-8")
        result = _j(await self.tools["fs_search_in_config"]("secret123", glob="**/*.txt"))
        self.assertEqual(result["count"], 0)
        self.assertGreaterEqual(result["skipped_files"], 1)

    async def test_invalid_regex_returns_error(self) -> None:
        result = _j(await self.tools["fs_search_in_config"]("[invalid(regex"))
        self.assertEqual(result["error"], "invalid_pattern")

    async def test_custom_glob(self) -> None:
        (self.root / "test.json").write_text('{"key": "value"}', encoding="utf-8")
        (self.root / "test.yaml").write_text("key: value\n", encoding="utf-8")
        result_json = _j(await self.tools["fs_search_in_config"]("key", glob="**/*.json"))
        result_yaml = _j(await self.tools["fs_search_in_config"]("key", glob="**/*.yaml"))
        json_paths = {m["path"] for m in result_json["matches"]}
        yaml_paths = {m["path"] for m in result_yaml["matches"]}
        self.assertIn("test.json", json_paths)
        self.assertNotIn("test.yaml", json_paths)
        self.assertIn("test.yaml", yaml_paths)

    async def test_searched_files_count(self) -> None:
        (self.root / "a.yaml").write_text("key: val\n", encoding="utf-8")
        (self.root / "b.yaml").write_text("other: stuff\n", encoding="utf-8")
        result = _j(await self.tools["fs_search_in_config"]("key"))
        self.assertGreaterEqual(result["searched_files"], 1)


# ══════════════════════════════════════════════════════════════════════════════
# fs_stat
# ══════════════════════════════════════════════════════════════════════════════

class TestFsStat(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self.root = Path(self._tmpdir) / "config"
        self.root.mkdir()
        self._patcher = patch.object(fs_module, "CONFIG_BASE", self.root.resolve())
        self._patcher.start()
        self.tools = _make_tools(self.root)

    def tearDown(self) -> None:
        self._patcher.stop()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    async def test_stat_regular_file(self) -> None:
        (self.root / "test.yaml").write_text("x: 1", encoding="utf-8")
        result = _j(await self.tools["fs_stat"]("test.yaml"))
        self.assertEqual(result["type"], "file")
        self.assertIsNotNone(result["size_bytes"])
        self.assertIsNotNone(result["modified"])
        self.assertFalse(result["is_blacklisted"])
        self.assertEqual(result["path"], "test.yaml")

    async def test_stat_directory(self) -> None:
        sub = self.root / "subdir"
        sub.mkdir()
        result = _j(await self.tools["fs_stat"]("subdir"))
        self.assertEqual(result["type"], "dir")
        self.assertIsNone(result["size_bytes"])

    async def test_stat_blacklisted_shows_metadata(self) -> None:
        (self.root / "secrets.yaml").write_text("key: val", encoding="utf-8")
        result = _j(await self.tools["fs_stat"]("secrets.yaml"))
        # fs_stat shows metadata even for blacklisted files
        self.assertIsNone(result.get("error"))
        self.assertTrue(result["is_blacklisted"])
        self.assertEqual(result["type"], "file")

    async def test_stat_not_found(self) -> None:
        result = _j(await self.tools["fs_stat"]("nonexistent.yaml"))
        self.assertEqual(result["error"], "not_found")

    async def test_stat_traversal_rejected(self) -> None:
        result = _j(await self.tools["fs_stat"]("../../etc/passwd"))
        self.assertEqual(result["error"], "traversal")

    async def test_stat_storage_file(self) -> None:
        storage = self.root / ".storage"
        storage.mkdir()
        (storage / "core.entity_registry").write_text("{}", encoding="utf-8")
        result = _j(await self.tools["fs_stat"](".storage/core.entity_registry"))
        self.assertFalse(result["is_blacklisted"])
        self.assertTrue(result["is_managed_path"])

    async def test_stat_config_base(self) -> None:
        result = _j(await self.tools["fs_stat"]("."))
        self.assertEqual(result["type"], "dir")
