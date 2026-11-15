"""Agentes y ajustes de los backups de HA (spec 031, tramo 1: T003, T004, T005).

`ha_list_backup_agents`, `ha_update_backup_config`,
`ha_get_update_backup_settings` y `ha_set_update_backup_settings` con
`ws_send` simulado. Datos ficticios (`hassio.nas_backups`, `cloud.cloud`,
`centinela-031`).

`backup/config/info` devuelve la clave de cifrado de los backups EN CLARO: el
centinela de esa clave no puede salir en ninguna respuesta, vista previa,
error, log ni fichero de token.

Control negativo (T015 b), comprobado: dejando pasar `create_backup.password`
(sin su comprobación en `_dict` y con `password` entre las claves admitidas)
cae `test_password_rechazado_sin_valor`; solo sin la comprobación no cae
nada, porque la clave desconocida se rechaza igual (defensa en profundidad).
Copiando `password` a `current` cae `test_vista_previa_sin_llamar_a_update`
por el centinela. Sin `estado=` al crear y al resolver el token de
`ha_update_backup_config` caen `test_estado_cambiado` y
`test_backups_cambiados`.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from packaging.version import Version
from structlog.testing import capture_logs

from hermes import security
from hermes.ha import HAConnectionError
from hermes.tools import ha_backup_settings as mod
from hermes.tools import ha_backups as hb

_CENTINELA = "centinela-031"


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
        self.enviados.append(copy.deepcopy(payload))
        r = self.respuestas.get(payload["type"])
        if isinstance(r, Exception):
            raise r
        if r is None:
            raise AssertionError(f"comando inesperado {payload['type']}")
        return copy.deepcopy(r)

    def tipos(self) -> list[str]:
        return [p["type"] for p in self.enviados]


def _config_info(**cambios: Any) -> dict[str, Any]:
    config = {
        "agents": {
            "hassio.nas_backups": {"protected": True, "retention": {"copies": 10, "days": None}},
            "cloud.cloud": {"protected": True, "retention": None},
        },
        "automatic_backups_configured": True,
        "create_backup": {
            "agent_ids": ["hassio.local", "hassio.nas_backups"],
            "include_addons": None, "include_all_addons": True,
            "include_database": True, "include_folders": None, "name": None,
            "password": _CENTINELA,
        },
        "last_attempted_automatic_backup": "2026-11-14T04:30:00+00:00",
        "last_completed_automatic_backup": "2026-11-14T04:31:00+00:00",
        "next_automatic_backup": "2026-11-15T04:30:00+00:00",
        "next_automatic_backup_additional": False,
        "retention": {"copies": 5, "days": None},
        "schedule": {"days": [], "recurrence": "daily", "time": "04:30:00"},
    }
    config.update(cambios)
    return {"config": config}


def _agents_info() -> dict[str, Any]:
    return {"agents": [
        {"agent_id": "hassio.local", "name": "local"},
        {"agent_id": "hassio.nas_backups", "name": "nas_backups"},
        {"agent_id": "backup.local", "name": "backup"},
        {"agent_id": "cloud.cloud", "name": "Home Assistant Cloud"},
    ]}


def _auto(bid: str, dia: int) -> dict[str, Any]:
    return {
        "backup_id": bid, "name": f"Automatic backup {bid}",
        "date": f"2026-11-{dia:02d}T04:30:00+00:00",
        "agents": {"hassio.local": {"protected": True, "size": 10}},
        "with_automatic_settings": True,
    }


def _backup_info(n: int = 4) -> dict[str, Any]:
    return {"backups": [_auto(f"b{i}", i) for i in range(1, n + 1)], "agent_errors": {}}


def _respuestas(**extra: Any) -> dict[str, Any]:
    r = {
        "backup/config/info": _config_info(),
        "backup/agents/info": _agents_info(),
        "backup/info": _backup_info(),
        "backup/config/update": None,
        "hassio/update/config/info": {
            "core_backup_before_update": True,
            "add_on_backup_before_update": True,
            "add_on_backup_retain_copies": 3,
        },
        "hassio/update/config/update": None,
    }
    r.update(extra)
    return r


class _Base(unittest.IsolatedAsyncioTestCase):
    version: bool | None = True

    def setUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self._parches = [
            patch.object(hb, "ha_at_least", new=AsyncMock(side_effect=lambda *a: self.version)),
            patch.object(hb, "ha_core_version", new=AsyncMock(return_value=Version("2024.12.3"))),
        ]
        for p in self._parches:
            p.start()
        self.montar(_respuestas())

    def tearDown(self) -> None:
        for p in self._parches:
            p.stop()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    def montar(self, respuestas: dict[str, Any], max_bytes: int = 131_072) -> None:
        # `None` en `_respuestas` es «comando que responde null»: _HA lo
        # trataría como inesperado, así que se cambia por {}.
        self.ha = _HA({k: ({} if v is None else v) for k, v in respuestas.items()})
        mcp = _MCP()
        mod.register(mcp, self.ha, response_max_bytes=max_bytes)
        self.t = mcp.tools

    def ficheros_de_token(self) -> str:
        return "".join(p.read_text(encoding="utf-8")
                       for p in Path(self.temp_dir.name).glob("*.json"))

    def sin_centinela(self, *cosas: Any) -> None:
        for c in cosas:
            self.assertNotIn(_CENTINELA, json.dumps(c, ensure_ascii=False, default=str))
        self.assertNotIn(_CENTINELA, self.ficheros_de_token())


# ── T003: ha_list_backup_agents ─────────────────────────────────────────────

class TestListBackupAgents(_Base):
    async def test_agentes_con_kind_y_configuracion(self) -> None:
        with capture_logs() as logs:
            r = await self.t["ha_list_backup_agents"]()
        self.assertEqual(r["count"], 4)
        self.assertFalse(r["truncated"])
        por_id = {a["agent_id"]: a for a in r["items"]}
        self.assertEqual(por_id["hassio.local"], {
            "agent_id": "hassio.local", "name": "local", "kind": "local",
            "protected": True, "retention": None, "used_by_automatic_backups": True,
        })
        self.assertEqual(por_id["backup.local"]["kind"], "local")
        self.assertEqual(por_id["hassio.nas_backups"]["kind"], "mount")
        self.assertEqual(por_id["hassio.nas_backups"]["retention"], {"copies": 10, "days": None})
        self.assertTrue(por_id["hassio.nas_backups"]["used_by_automatic_backups"])
        self.assertEqual(por_id["cloud.cloud"]["kind"], "remote")
        self.assertFalse(por_id["cloud.cloud"]["used_by_automatic_backups"])
        # Orden de HA.
        self.assertEqual([a["agent_id"] for a in r["items"]],
                         ["hassio.local", "hassio.nas_backups", "backup.local", "cloud.cloud"])
        self.sin_centinela(r, logs)

    async def test_protected_false_de_la_configuracion(self) -> None:
        info = _config_info()
        info["config"]["agents"]["cloud.cloud"]["protected"] = False
        self.montar(_respuestas(**{"backup/config/info": info}))
        r = await self.t["ha_list_backup_agents"]()
        por_id = {a["agent_id"]: a for a in r["items"]}
        self.assertFalse(por_id["cloud.cloud"]["protected"])

    async def test_version_antigua(self) -> None:
        self.version = False
        r = await self.t["ha_list_backup_agents"]()
        self.assertEqual(r["error"], "ha_version_unsupported")
        self.assertEqual(self.ha.enviados, [])

    async def test_sin_integracion(self) -> None:
        self.montar(_respuestas(**{"backup/agents/info": HAConnectionError(
            "Unknown command.", code="unknown_command")}))
        r = await self.t["ha_list_backup_agents"]()
        self.assertEqual(r["error"], "backup_integration_unavailable")

    async def test_recorte(self) -> None:
        muchos = {"agents": [{"agent_id": f"hassio.nas_{i:03d}", "name": "x" * 200}
                             for i in range(60)]}
        self.montar(_respuestas(**{"backup/agents/info": muchos}), max_bytes=3000)
        r = await self.t["ha_list_backup_agents"]()
        self.assertTrue(r["truncated"])
        self.assertEqual(r["count"], len(r["items"]))
        self.assertLess(r["count"], 60)


# ── T004: ha_update_backup_config ───────────────────────────────────────────

class TestUpdateBackupConfigValidacion(_Base):
    async def _invalido(self, campo: str, **args: Any) -> dict[str, Any]:
        with capture_logs() as logs:
            r = await self.t["ha_update_backup_config"](**args)
        self.assertEqual(r.get("error"), "invalid_argument", r)
        self.assertEqual(r["field"], campo)
        self.assertEqual(self.ha.enviados, [], "no se llama a HA con argumentos inválidos")
        self.sin_centinela(r, logs)
        return r

    async def test_sin_argumentos(self) -> None:
        await self._invalido("arguments")

    async def test_password_rechazado_sin_valor(self) -> None:
        await self._invalido("create_backup.password",
                             create_backup={"password": _CENTINELA})
        await self._invalido("agents.hassio.nas_backups.password",
                             agents={"hassio.nas_backups": {"password": _CENTINELA}})
        await self._invalido("schedule.password", schedule={"password": _CENTINELA})

    async def test_claves_desconocidas(self) -> None:
        await self._invalido("schedule.when", schedule={"when": "now"})
        await self._invalido("retention.weeks", retention={"weeks": 1})
        await self._invalido("agents.cloud.cloud.encrypted",
                             agents={"cloud.cloud": {"encrypted": True}})
        await self._invalido("create_backup.agents", create_backup={"agents": []})
        await self._invalido("agents.cloud.cloud.retention.weeks",
                             agents={"cloud.cloud": {"retention": {"weeks": 1}}})

    async def test_valores_invalidos(self) -> None:
        await self._invalido("schedule.days", schedule={"days": ["mon", "mon"]})
        await self._invalido("schedule.days", schedule={"days": ["lunes"]})
        await self._invalido("schedule.recurrence", schedule={"recurrence": "weekly"})
        await self._invalido("schedule.time", schedule={"time": "4:30 am"})
        await self._invalido("schedule.time", schedule={"time": "25:00"})
        await self._invalido("retention.copies", retention={"copies": 0})
        await self._invalido("retention.days", retention={"days": True})
        await self._invalido("create_backup.include_addons",
                             create_backup={"include_all_addons": True,
                                            "include_addons": ["core_mosquitto"]})
        await self._invalido("create_backup.include_folders",
                             create_backup={"include_folders": ["homeassistant"]})
        await self._invalido("agents", agents={"no tiene punto": {"protected": True}})
        await self._invalido("agents", agents={})
        await self._invalido("automatic_backups_configured", automatic_backups_configured="yes")


class TestUpdateBackupConfig(_Base):
    async def test_vista_previa_sin_llamar_a_update(self) -> None:
        with capture_logs() as logs:
            r = await self.t["ha_update_backup_config"](
                schedule={"time": "05:15"}, retention={"copies": 3})
        self.assertNotIn("backup/config/update", self.ha.tipos())
        self.assertIn("confirmation_token", r)
        p = r["preview"]
        self.assertEqual(p["action"], "update_backup_config")
        # Fusión: la recurrencia y los días actuales se conservan (no `never`),
        # y `days` de la retención también.
        self.assertEqual(p["sends"]["schedule"],
                         {"recurrence": "daily", "days": [], "time": "05:15:00"})
        self.assertEqual(p["sends"]["retention"], {"copies": 3, "days": None})
        self.assertEqual(p["resulting"]["schedule"]["recurrence"], "daily")
        self.assertEqual(p["changed"], ["schedule.time", "retention.copies"])
        self.assertTrue(p["current"]["create_backup"]["password_set"])
        self.assertNotIn("password", p["current"]["create_backup"])
        self.assertNotIn("password", p["resulting"]["create_backup"])
        self.assertTrue(p["resulting"]["create_backup"]["password_set"])
        # Estimación: cuatro automáticos y 3 copias → los dos más antiguos
        # tras el próximo automático.
        efecto = p["retention_effect"]
        self.assertTrue(efecto["estimate"])
        self.assertEqual([e["backup_id"] for e in efecto["would_delete"]], ["b1", "b2"])
        self.assertEqual({e["when"] for e in efecto["would_delete"]},
                         {"after_next_automatic_backup"})
        self.assertFalse(efecto["truncated"])
        self.sin_centinela(r, logs)

    async def test_null_explicito_se_respeta(self) -> None:
        r = await self.t["ha_update_backup_config"](
            schedule={"time": None}, retention={"copies": None})
        p = r["preview"]
        self.assertEqual(p["sends"]["schedule"],
                         {"recurrence": "daily", "days": [], "time": None})
        self.assertEqual(p["sends"]["retention"], {"copies": None, "days": None})
        self.assertEqual(p["retention_effect"]["would_delete"], [])

    async def test_create_backup_y_agentes(self) -> None:
        r = await self.t["ha_update_backup_config"](
            create_backup={"include_database": False},
            agents={"hassio.nas_backups": {"retention": {"days": 30}},
                    "cloud.cloud": {"protected": False}})
        p = r["preview"]
        self.assertEqual(p["sends"]["create_backup"], {"include_database": False})
        # La retención del agente se completa con su valor actual (copies 10).
        self.assertEqual(p["sends"]["agents"]["hassio.nas_backups"],
                         {"retention": {"copies": 10, "days": 30}})
        self.assertEqual(p["sends"]["agents"]["cloud.cloud"], {"protected": False})
        self.assertFalse(p["resulting"]["create_backup"]["include_database"])
        self.assertTrue(p["resulting"]["create_backup"]["include_all_addons"])
        self.assertEqual(p["changed"], [
            "agents.cloud.cloud.protected", "agents.hassio.nas_backups.retention",
            "create_backup.include_database",
        ])
        self.assertTrue(any("cloud.cloud will NOT be encrypted" in w for w in p["warnings"]))

    async def test_avisos_never_y_agente_inexistente(self) -> None:
        r = await self.t["ha_update_backup_config"](
            schedule={"recurrence": "never"},
            create_backup={"agent_ids": ["hassio.local", "hassio.otro_nas"]})
        avisos = " ".join(r["preview"]["warnings"])
        self.assertIn("turned off", avisos)
        self.assertIn("hassio.otro_nas", avisos)
        self.assertNotIn("hassio.local,", avisos)

    async def test_confirmar_manda_lo_de_la_vista_previa(self) -> None:
        args = {"schedule": {"time": "05:15"}, "retention": {"copies": 3}}
        vista = await self.t["ha_update_backup_config"](**args)
        with capture_logs() as logs:
            r = await self.t["ha_update_backup_config"](
                **args, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r, {"result": "ok", "changed": ["schedule.time", "retention.copies"]})
        enviado = [p for p in self.ha.enviados if p["type"] == "backup/config/update"]
        self.assertEqual(enviado, [{"type": "backup/config/update", **vista["preview"]["sends"]}])
        self.sin_centinela(r, logs)

    async def test_token_de_otros_argumentos(self) -> None:
        vista = await self.t["ha_update_backup_config"](retention={"copies": 3})
        r = await self.t["ha_update_backup_config"](
            retention={"copies": 1}, confirmation_token=vista["confirmation_token"])
        self.assertIn("does not match", r["error"])
        self.assertNotIn("backup/config/update", self.ha.tipos())

    async def test_estado_cambiado(self) -> None:
        args = {"schedule": {"time": "05:15"}}
        vista = await self.t["ha_update_backup_config"](**args)
        # Otra retención en HA entre la vista previa y la confirmación.
        self.ha.respuestas["backup/config/info"] = _config_info(
            retention={"copies": 2, "days": None})
        r = await self.t["ha_update_backup_config"](
            **args, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "state_changed")
        self.assertNotIn("backup/config/update", self.ha.tipos())

    async def test_backups_cambiados(self) -> None:
        args = {"retention": {"copies": 3}}
        vista = await self.t["ha_update_backup_config"](**args)
        self.ha.respuestas["backup/info"] = _backup_info(n=6)
        r = await self.t["ha_update_backup_config"](
            **args, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "state_changed")

    async def test_error_de_ha_redactado_y_token_fallido(self) -> None:
        args = {"retention": {"copies": 3}}
        vista = await self.t["ha_update_backup_config"](**args)
        self.ha.respuestas["backup/config/update"] = HAConnectionError(
            "smb://usuario:clave@192.0.2.10/backups token=centinela-031",
            code="unknown_error")
        r = await self.t["ha_update_backup_config"](
            **args, confirmation_token=vista["confirmation_token"])
        self.assertNotIn("192.0.2.10", r["error"])
        self.sin_centinela(r)
        token = json.loads(
            (Path(self.temp_dir.name) / f"{vista['confirmation_token']}.json").read_text())
        self.assertEqual(token["state"], "failed")


# ── T005: ha_get_update_backup_settings y ha_set_update_backup_settings ────

class TestUpdateBackupSettings(_Base):
    async def test_leer(self) -> None:
        r = await self.t["ha_get_update_backup_settings"]()
        self.assertEqual(r, {"core_backup_before_update": True,
                             "add_on_backup_before_update": True,
                             "add_on_backup_retain_copies": 3})

    async def test_sin_hassio(self) -> None:
        self.montar(_respuestas(**{"hassio/update/config/info": HAConnectionError(
            "Unknown command.", code="unknown_command")}))
        r = await self.t["ha_get_update_backup_settings"]()
        self.assertEqual(r["error"], "supervisor_integration_unavailable")
        r = await self.t["ha_set_update_backup_settings"](core_backup_before_update=False)
        self.assertEqual(r["error"], "supervisor_integration_unavailable")

    async def test_validacion(self) -> None:
        for args, campo in (({}, "arguments"),
                            ({"add_on_backup_retain_copies": 0}, "add_on_backup_retain_copies"),
                            ({"add_on_backup_retain_copies": 101}, "add_on_backup_retain_copies"),
                            ({"add_on_backup_retain_copies": True}, "add_on_backup_retain_copies"),
                            ({"core_backup_before_update": "no"}, "core_backup_before_update")):
            with self.subTest(args=args):
                r = await self.t["ha_set_update_backup_settings"](**args)
                self.assertEqual(r["error"], "invalid_argument")
                self.assertEqual(r["field"], campo)
        self.assertEqual(self.ha.enviados, [])

    async def test_vista_previa_y_confirmacion(self) -> None:
        args = {"add_on_backup_retain_copies": 1, "core_backup_before_update": False}
        vista = await self.t["ha_set_update_backup_settings"](**args)
        p = vista["preview"]
        self.assertNotIn("hassio/update/config/update", self.ha.tipos())
        self.assertEqual(p["current"]["add_on_backup_retain_copies"], 3)
        self.assertEqual(p["resulting"], {"core_backup_before_update": False,
                                          "add_on_backup_before_update": True,
                                          "add_on_backup_retain_copies": 1})
        self.assertEqual(p["changed"], ["core_backup_before_update",
                                        "add_on_backup_retain_copies"])
        avisos = " ".join(p["warnings"])
        self.assertIn("newest 1", avisos)
        self.assertIn("Updating Core will no longer make a backup first", avisos)
        r = await self.t["ha_set_update_backup_settings"](
            **args, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["result"], "ok")
        self.assertEqual(self.ha.enviados[-1], {"type": "hassio/update/config/update",
                                                "core_backup_before_update": False,
                                                "add_on_backup_retain_copies": 1})

    async def test_estado_cambiado(self) -> None:
        args = {"add_on_backup_retain_copies": 1}
        vista = await self.t["ha_set_update_backup_settings"](**args)
        self.ha.respuestas["hassio/update/config/info"] = {
            "core_backup_before_update": False, "add_on_backup_before_update": True,
            "add_on_backup_retain_copies": 3}
        r = await self.t["ha_set_update_backup_settings"](
            **args, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "state_changed")
        self.assertNotIn("hassio/update/config/update", self.ha.tipos())


if __name__ == "__main__":
    unittest.main()
