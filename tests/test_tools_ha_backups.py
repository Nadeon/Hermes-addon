"""Tests de los backups de Home Assistant (spec 005, US7).

`backup/config/info` devuelve en claro la contraseña de cifrado de los
backups automáticos, y `backup/info` el `instance_id` de la instalación y
mensajes de error que pueden nombrar el NAS del usuario. Por eso las tres
tools construyen su respuesta con una lista blanca: un campo que HA añada
mañana no sale hasta que alguien decida que puede salir.
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

from packaging.version import Version

from hermes.ha import HAConnectionError
from hermes.tools import ha_backups as mod


class _MCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, *a: Any, **k: Any):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


class _HA:
    def __init__(self, respuestas: dict[str, Any]) -> None:
        self.respuestas = respuestas
        self.enviados: list[dict[str, Any]] = []

    async def wait_ready(self, timeout: float = 5.0) -> bool:
        return True

    async def ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.enviados.append(payload)
        r = self.respuestas.get(payload["type"])
        if isinstance(r, Exception):
            raise r
        if r is None:
            raise AssertionError(f"comando inesperado {payload['type']}")
        return r


def _backup(backup_id: str, date: str, **extra: Any) -> dict[str, Any]:
    b = {
        "backup_id": backup_id, "name": f"Backup {backup_id}", "date": date,
        "agents": {"backup.local": {"protected": False, "size": 1234, "x": "SENTINEL-AG"}},
        "addons": [{"slug": "core_x", "name": "X", "version": "1.0", "icon": True}],
        "folders": ["media"],
        "database_included": True, "homeassistant_included": True,
        "homeassistant_version": "2026.11.1",
        "failed_agent_ids": [], "failed_addons": [], "failed_folders": [],
        "with_automatic_settings": True,
        "extra_metadata": {"instance_id": "SENTINEL-INSTANCE", "with_automatic_settings": True},
        "secret_field": "SENTINEL-X",
    }
    b.update(extra)
    return b


def _info(backups: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    datos = {
        "backups": backups if backups is not None else [
            _backup("aaaa0001", "2026-11-01T08:00:00+00:00"),
            _backup("aaaa0003", "2026-11-03T08:00:00+00:00"),
            _backup("aaaa0002", "2026-11-02T08:00:00+00:00"),
        ],
        "agent_errors": {},
        "last_attempted_automatic_backup": "2026-11-03T08:00:00+00:00",
        "last_completed_automatic_backup": "2026-11-03T08:00:00+00:00",
        "next_automatic_backup": "2026-11-04T08:00:00+00:00",
        "next_automatic_backup_additional": False,
        "state": "idle",
        "last_action_event": {"secret": "SENTINEL-EV"},
    }
    datos.update(extra)
    return datos


def _config(**create: Any) -> dict[str, Any]:
    cb = {"agent_ids": ["backup.local"], "include_addons": None,
          "include_all_addons": True, "include_database": True,
          "include_folders": None, "name": None, "password": "SENTINEL-PASSWORD"}
    cb.update(create)
    return {"config": {
        "agents": {"backup.local": {"protected": True,
                                    "retention": {"copies": 3, "days": None}}},
        "automatic_backups_configured": True,
        "create_backup": cb,
        "last_attempted_automatic_backup": None,
        "last_completed_automatic_backup": None,
        "retention": {"copies": 3, "days": None},
        "schedule": {"days": ["mon"], "recurrence": "custom_days", "state": "never",
                     "time": None},
        "next_automatic_backup": None,
        "next_automatic_backup_additional": False,
        "unknown_new_field": "SENTINEL-NEW",
    }}


class _Base(unittest.IsolatedAsyncioTestCase):
    version: bool | None = True

    def setUp(self) -> None:
        self._p = [
            patch.object(mod, "ha_at_least", new=AsyncMock(side_effect=lambda *a: self.version)),
            patch.object(mod, "ha_core_version", new=AsyncMock(return_value=Version("2024.12.3"))),
        ]
        for p in self._p:
            p.start()

    def tearDown(self) -> None:
        for p in self._p:
            p.stop()

    async def _llamar(self, ha: _HA, tool: str, **kw: Any) -> dict[str, Any]:
        mcp = _MCP()
        mod.register(mcp, ha)
        return json.loads(await mcp.tools[tool](**kw))

    def _sin_backup_ws(self, ha: _HA) -> None:
        self.assertEqual([p for p in ha.enviados if p["type"].startswith("backup/")], [])


class TestVersion(_Base):
    async def test_old_version_is_rejected_without_ws(self) -> None:
        self.version = False
        for tool, kw in (("ha_list_backups", {}), ("ha_get_backup", {"backup_id": "aaaa0001"}),
                         ("ha_get_backup_config", {})):
            ha = _HA({})
            r = await self._llamar(ha, tool, **kw)
            self.assertEqual(r, {"error": "ha_version_unsupported", "feature": "backup",
                                 "required": "2025.1.0", "current": "2024.12.3"}, tool)
            self.assertEqual(ha.enviados, [])

    async def test_unknown_version_calls_and_translates_unknown_command(self) -> None:
        self.version = None
        for tool, kw in (("ha_list_backups", {}), ("ha_get_backup", {"backup_id": "aaaa0001"}),
                         ("ha_get_backup_config", {})):
            err = HAConnectionError("Unknown command.", code="unknown_command")
            ha = _HA({"backup/info": err, "backup/details": err, "backup/config/info": err})
            r = await self._llamar(ha, tool, **kw)
            self.assertEqual(r["error"], "backup_integration_unavailable", tool)
            self.assertEqual(len(ha.enviados), 1)

    async def test_other_ha_error(self) -> None:
        ha = _HA({"backup/info": HAConnectionError("boom")})
        r = await self._llamar(ha, "ha_list_backups")
        self.assertEqual(r, {"error": "boom"})


class TestListBackups(_Base):
    async def test_calls_backup_info_and_whitelists(self) -> None:
        ha = _HA({"backup/info": _info()})
        r = await self._llamar(ha, "ha_list_backups")
        self.assertEqual(ha.enviados, [{"type": "backup/info"}])
        texto = json.dumps(r)
        for s in ("SENTINEL-INSTANCE", "SENTINEL-X", "SENTINEL-AG", "SENTINEL-EV",
                  "extra_metadata", "instance_id", "secret_field"):
            self.assertNotIn(s, texto)
        b = r["backups"][0]
        self.assertEqual(set(b), {
            "backup_id", "name", "date", "agents", "addons", "folders",
            "database_included", "homeassistant_included", "homeassistant_version",
            "failed_agent_ids", "failed_addons", "failed_folders", "with_automatic_settings"})
        self.assertEqual(b["agents"], {"backup.local": {"protected": False, "size": 1234}})
        self.assertEqual(b["addons"], [{"slug": "core_x", "name": "X", "version": "1.0"}])
        self.assertEqual(r["state"], "idle")
        self.assertEqual(r["next_automatic_backup"], "2026-11-04T08:00:00+00:00")
        self.assertEqual(r["last_attempted_automatic_backup"], "2026-11-03T08:00:00+00:00")
        self.assertEqual(r["last_completed_automatic_backup"], "2026-11-03T08:00:00+00:00")

    async def test_newest_first_with_limit_and_total(self) -> None:
        ha = _HA({"backup/info": _info()})
        r = await self._llamar(ha, "ha_list_backups", limit=2)
        self.assertEqual([b["backup_id"] for b in r["backups"]], ["aaaa0003", "aaaa0002"])
        self.assertEqual((r["count"], r["total"]), (2, 3))

    async def test_limit_bounds(self) -> None:
        for malo in (0, 101, -1, "5", True):
            ha = _HA({"backup/info": _info()})
            r = await self._llamar(ha, "ha_list_backups", limit=malo)
            self.assertEqual(r["error"], "invalid_argument", malo)
            self.assertEqual(r["field"], "limit")
            self.assertEqual(ha.enviados, [])
        for bueno in (1, 100):
            r = await self._llamar(_HA({"backup/info": _info()}), "ha_list_backups", limit=bueno)
            self.assertIn("backups", r)

    async def test_agent_errors_are_masked(self) -> None:
        info = _info(agent_errors={
            "hassio.nas": "Cannot reach smb://user:SENTINEL-P@192.0.2.10/backups",
            "cloud.x": "failed at [2001:db8::1] and nas.example.lan:445 " + "z" * 400,
            "raro": {"password": "SENTINEL-D"},
        })
        r = await self._llamar(_HA({"backup/info": info}), "ha_list_backups")
        texto = json.dumps(r)
        for s in ("SENTINEL-P", "SENTINEL-D", "192.0.2.10", "2001:db8::1", "user:"):
            self.assertNotIn(s, texto)
        self.assertIn("<host>", r["agent_errors"]["hassio.nas"])
        self.assertLessEqual(len(r["agent_errors"]["cloud.x"]), 300)
        self.assertIn("<ip>", r["agent_errors"]["cloud.x"])

    async def test_ipv4_without_url_is_masked(self) -> None:
        info = _info(agent_errors={"a": "timeout talking to 192.0.2.44 port 445"})
        r = await self._llamar(_HA({"backup/info": info}), "ha_list_backups")
        self.assertNotIn("192.0.2.44", json.dumps(r))

    async def test_unexpected_shape(self) -> None:
        r = await self._llamar(_HA({"backup/info": ["x"]}), "ha_list_backups")
        self.assertIn("error", r)


class TestGetBackup(_Base):
    async def test_details_whitelisted(self) -> None:
        ha = _HA({"backup/details": {"backup": _backup("aaaa0001", "2026-11-01T08:00:00+00:00"),
                                     "agent_errors": {"a": "at 192.0.2.7"}}})
        r = await self._llamar(ha, "ha_get_backup", backup_id="aaaa0001")
        self.assertEqual(ha.enviados, [{"type": "backup/details", "backup_id": "aaaa0001"}])
        self.assertEqual(r["backup"]["backup_id"], "aaaa0001")
        texto = json.dumps(r)
        for s in ("SENTINEL-INSTANCE", "SENTINEL-X", "192.0.2.7"):
            self.assertNotIn(s, texto)

    async def test_null_backup_is_not_found(self) -> None:
        ha = _HA({"backup/details": {"backup": None, "agent_errors": {}}})
        r = await self._llamar(ha, "ha_get_backup", backup_id="aaaa0009")
        self.assertEqual(r, {"error": "not_found", "backup_id": "aaaa0009"})

    async def test_invalid_id_no_ws(self) -> None:
        for malo in ("../x", "a/b", "", "a" * 300):
            ha = _HA({})
            r = await self._llamar(ha, "ha_get_backup", backup_id=malo)
            self.assertEqual(r["error"], "invalid_identifier")
            self.assertEqual(ha.enviados, [])


class TestGetBackupConfig(_Base):
    async def test_password_never_leaves_and_password_set(self) -> None:
        ha = _HA({"backup/config/info": _config()})
        r = await self._llamar(ha, "ha_get_backup_config")
        self.assertEqual(ha.enviados, [{"type": "backup/config/info"}])
        texto = json.dumps(r)
        self.assertNotIn("SENTINEL-PASSWORD", texto)
        self.assertNotIn('"password"', texto)
        self.assertNotIn("SENTINEL-NEW", texto)
        cb = r["config"]["create_backup"]
        self.assertIs(cb["password_set"], True)
        self.assertEqual(cb["agent_ids"], ["backup.local"])
        self.assertEqual(r["config"]["retention"], {"copies": 3, "days": None})
        self.assertEqual(r["config"]["agents"]["backup.local"],
                         {"protected": True, "retention": {"copies": 3, "days": None}})
        self.assertEqual(r["config"]["schedule"]["recurrence"], "custom_days")

    async def test_password_empty_or_null(self) -> None:
        for valor in (None, ""):
            ha = _HA({"backup/config/info": _config(password=valor)})
            r = await self._llamar(ha, "ha_get_backup_config")
            self.assertIs(r["config"]["create_backup"]["password_set"], False, valor)

    async def test_new_sensitive_field_does_not_leave(self) -> None:
        ha = _HA({"backup/config/info": _config(encryption_key="SENTINEL-K")})
        r = await self._llamar(ha, "ha_get_backup_config")
        self.assertNotIn("SENTINEL-K", json.dumps(r))
        self.assertNotIn("encryption_key", json.dumps(r))

    async def test_name_with_secret_looking_text_is_redacted(self) -> None:
        ha = _HA({"backup/config/info": _config(name="nightly password=SENTINEL-N")})
        r = await self._llamar(ha, "ha_get_backup_config")
        self.assertNotIn("SENTINEL-N", json.dumps(r))



class TestListBackupsRespetaTope(_Base):
    """Regresión M-1: cien backups con muchos add-ons no pasan del tope."""

    async def test_recorta_por_bytes(self) -> None:
        addons = [{"slug": f"addon_ficticio_{i}", "name": f"Add-on {i}", "version": "1.0"}
                  for i in range(30)]
        backups = [_backup(f"b{i:07d}", f"2026-10-{1 + i % 28:02d}T08:00:00+00:00",
                           addons=addons) for i in range(100)]
        ha = _HA({"backup/info": _info(backups)})
        mcp = _MCP()
        mod.register(mcp, ha, response_max_bytes=16384)
        texto = await mcp.tools["ha_list_backups"](limit=100)
        self.assertLessEqual(len(texto.encode()), 16384)
        res = json.loads(texto)
        self.assertTrue(res["truncated"])
        self.assertEqual(res["total"], 100)
        self.assertEqual(res["count"], len(res["backups"]))
        self.assertGreater(res["count"], 0)
        self.assertLess(res["count"], 100)
        # Los campos de arriba no se pierden al recortar.
        self.assertEqual(res["state"], "idle")

    async def test_sin_recorte(self) -> None:
        res = await self._llamar(_HA({"backup/info": _info()}), "ha_list_backups")
        self.assertFalse(res["truncated"])
        self.assertEqual(res["count"], 3)


class TestBackupsHA2025_1(_Base):
    """Regresión B-4: HA 2025.1.x da `agent_ids` y `protected`/`size` arriba."""

    async def test_agent_ids_sin_agents(self) -> None:
        b = _backup("aaaa0009", "2026-01-05T08:00:00+00:00",
                    agent_ids=["backup.local", "hassio.ficticio"], protected=True, size=4096)
        del b["agents"]
        res = await self._llamar(_HA({"backup/info": _info([b])}), "ha_list_backups")
        self.assertEqual(res["backups"][0]["agents"], {
            "backup.local": {"protected": True, "size": 4096},
            "hassio.ficticio": {"protected": True, "size": 4096},
        })


if __name__ == "__main__":
    unittest.main()
