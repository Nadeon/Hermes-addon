"""Crear y borrar backups con la integración de HA (spec 031, tramo 2: T019-T021).

`ha_create_backup`, `ha_create_automatic_backup` y `ha_delete_backup` con
`ws_send` simulado. Datos ficticios (`hassio.nas_backups`, `cloud.cloud`,
`192.0.2.10`, `centinela-031`).

`backup/config/info` devuelve la clave de cifrado de los backups EN CLARO, y
`ha_create_backup` la manda a HA como `password`: el centinela no puede salir
en ninguna vista previa, respuesta, error, log ni fichero de token.

Controles negativos (T030), comprobados:
- (b) metiendo la clave en `args` del token cae
  `test_la_clave_no_entra_en_el_token` (el fichero del token guarda solo la
  huella de los argumentos, así que el centinela no se ve en disco; por eso
  se espían los argumentos y el estado que recibe `security`) y
  `test_clave_rotada_entre_vista_y_confirmacion`;
- (c) sin validar `agent_ids` contra `backup/agents/info` cae
  `test_agente_desconocido`;
- (d) `ha_delete_backup` sin `estado=` caen
  `test_ubicacion_nueva_es_state_changed` y
  `test_contenido_cambiado_es_state_changed`; sin enmascarar `failed` cae
  `test_borrado_parcial_enmascarado`.
- (T065) sin `available_agents` en el estado de `ha_create_automatic_backup`
  cae `test_agentes_disponibles_cambiados` (los dos subtests);
- (T064) con el texto fijo «Home Assistant has no backup encryption key
  configured» cae `test_sin_clave_dice_el_motivo`.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from structlog.testing import capture_logs

from hermes import safety_retention, security
from hermes.ha import HAConnectionError
from hermes.tools import ha_backup_actions as mod
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

    def de_tipo(self, tipo: str) -> list[dict[str, Any]]:
        return [p for p in self.enviados if p["type"] == tipo]


def _config_info(password: Any = _CENTINELA, **cambios: Any) -> dict[str, Any]:
    config = {
        "agents": {
            "hassio.nas_backups": {"protected": True, "retention": None},
            "cloud.cloud": {"protected": False, "retention": None},
        },
        "automatic_backups_configured": True,
        "create_backup": {
            "agent_ids": ["hassio.local", "cloud.cloud"],
            "include_addons": None, "include_all_addons": True,
            "include_database": True, "include_folders": ["share"], "name": None,
            "password": password,
        },
        "last_attempted_automatic_backup": None,
        "last_completed_automatic_backup": None,
        "next_automatic_backup": None,
        "next_automatic_backup_additional": False,
        "retention": {"copies": 3, "days": None},
        "schedule": {"days": [], "recurrence": "daily", "time": "04:30:00"},
    }
    config.update(cambios)
    return {"config": config}


def _agents_info(*ids: str) -> dict[str, Any]:
    ids = ids or ("hassio.local", "hassio.nas_backups", "cloud.cloud")
    return {"agents": [{"agent_id": a, "name": a.split(".")[1]} for a in ids]}


def _backup(bid: str, dia: int, *, auto: bool = True, ha: bool = True,
            agentes: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "backup_id": bid, "name": f"Backup {bid}",
        "date": f"2026-11-{dia:02d}T04:30:00+00:00",
        "agents": agentes or {"hassio.local": {"protected": True, "size": 100}},
        "addons": [{"slug": "core_mosquitto", "name": "Mosquitto broker", "version": "6.5.1"}],
        "folders": ["share"], "database_included": True, "homeassistant_included": ha,
        "homeassistant_version": "2026.11.1", "with_automatic_settings": auto,
        "extra_metadata": {"instance_id": "SENTINEL-INSTANCE"},
    }


def _backup_info(*backups: dict[str, Any]) -> dict[str, Any]:
    if not backups:
        backups = tuple(_backup(f"b{i}", i) for i in range(1, 5))
    return {"backups": list(backups), "agent_errors": {}, "state": "idle"}


def _respuestas(**extra: Any) -> dict[str, Any]:
    r: dict[str, Any] = {
        "backup/config/info": _config_info(),
        "backup/agents/info": _agents_info(),
        "backup/info": _backup_info(),
        "backup/generate": {"backup_job_id": "job-1"},
        "backup/generate_with_automatic_settings": {"backup_job_id": "job-2"},
        "backup/details": {"backup": _backup("b1", 1, agentes={
            "hassio.local": {"protected": True, "size": 100},
            "cloud.cloud": {"protected": True, "size": 100}}), "agent_errors": {}},
        "backup/delete": {"agent_errors": {}},
    }
    r.update(extra)
    return r


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.original_ledger = safety_retention.LEDGER_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        security.CONFIRMATIONS_DIR = base / "tokens"
        safety_retention.LEDGER_PATH = base / "safety_backups.json"
        self._parches = [
            patch.object(hb, "ha_at_least", new=AsyncMock(return_value=True)),
        ]
        for p in self._parches:
            p.start()
        self.montar(_respuestas())

    def tearDown(self) -> None:
        for p in self._parches:
            p.stop()
        security.CONFIRMATIONS_DIR = self.original_dir
        safety_retention.LEDGER_PATH = self.original_ledger
        self.temp_dir.cleanup()

    def montar(self, respuestas: dict[str, Any]) -> None:
        self.ha = _HA(respuestas)
        mcp = _MCP()
        mod.register(mcp, self.ha)
        self.t = mcp.tools

    def ficheros(self) -> str:
        return "".join(p.read_text(encoding="utf-8")
                       for p in Path(self.temp_dir.name).rglob("*") if p.is_file())

    def sin_centinela(self, *cosas: Any) -> None:
        for c in cosas:
            self.assertNotIn(_CENTINELA, json.dumps(c, ensure_ascii=False, default=str))
        self.assertNotIn(_CENTINELA, self.ficheros())


# ── T019: ha_create_backup ──────────────────────────────────────────────────

class TestCreateBackupValidacion(_Base):
    async def _invalido(self, campo: str, **args: Any) -> None:
        args.setdefault("agent_ids", ["hassio.local"])
        r = await self.t["ha_create_backup"](**args)
        self.assertEqual(r.get("error"), "invalid_argument", r)
        self.assertEqual(r["field"], campo)

    async def test_argumentos_invalidos_sin_llamar_a_ha(self) -> None:
        await self._invalido("agent_ids", agent_ids=[])
        await self._invalido("agent_ids", agent_ids=[f"hassio.n{i}" for i in range(11)])
        await self._invalido("agent_ids", agent_ids=["sin punto"])
        await self._invalido("agent_ids", agent_ids=["hassio.local", "hassio.local"])
        await self._invalido("include_addons", include_all_addons=True,
                             include_addons=["core_mosquitto"])
        await self._invalido("include_folders", include_folders=["homeassistant"])
        await self._invalido("encrypt", encrypt="si")
        await self._invalido("name", name="")
        await self._invalido("include_homeassistant", include_homeassistant=False)
        self.assertEqual(self.ha.enviados, [])

    async def test_agente_desconocido(self) -> None:
        r = await self.t["ha_create_backup"](agent_ids=["hassio.local", "hassio.otro"])
        self.assertEqual(r["error"], "unknown_agent")
        self.assertEqual(r["agents"], ["hassio.otro"])
        self.assertEqual(r["available"], ["hassio.local", "hassio.nas_backups", "cloud.cloud"])
        self.assertNotIn("backup/generate", self.ha.tipos())

    async def test_apps_o_carpetas_sin_supervisor(self) -> None:
        self.montar(_respuestas(**{"backup/agents/info": _agents_info("backup.local")}))
        for args, campo in (({"include_all_addons": True}, "include_addons"),
                            ({"include_addons": ["core_mosquitto"]}, "include_addons"),
                            ({"include_folders": ["share"]}, "include_folders")):
            with self.subTest(args=args):
                r = await self.t["ha_create_backup"](agent_ids=["backup.local"], **args)
                self.assertEqual(r.get("error"), "invalid_argument", r)
                self.assertEqual(r["field"], campo)
        r = await self.t["ha_create_backup"](agent_ids=["backup.local"],
                                             include_homeassistant=False,
                                             include_folders=None, include_addons=["x"])
        self.assertEqual(r["error"], "invalid_argument")
        self.assertNotIn("backup/generate", self.ha.tipos())

    async def test_sin_clave(self) -> None:
        for password in (None, ""):
            with self.subTest(password=password):
                self.montar(_respuestas(**{"backup/config/info": _config_info(password)}))
                r = await self.t["ha_create_backup"](agent_ids=["hassio.local"])
                self.assertEqual(r["error"], "no_encryption_key")
                self.assertEqual(r["reason"], "no_key_configured")
                self.assertNotIn("confirmation_token", r)
        # Sin cifrar no hace falta clave.
        r = await self.t["ha_create_backup"](agent_ids=["hassio.local"], encrypt=False)
        self.assertIn("confirmation_token", r)

    async def test_sin_clave_dice_el_motivo(self) -> None:
        # T064: «no tiene clave» solo si es verdad.
        casos = {
            "no_key_configured": (_config_info(None), "has no backup encryption key"),
            "ha_unreachable": (HAConnectionError("WebSocket no disponible"),
                               "did not answer"),
        }
        for motivo, (respuesta, frase) in casos.items():
            with self.subTest(motivo=motivo):
                respuestas = _respuestas()
                self.montar(respuestas)
                # `_config` (la lista blanca) va antes que leer la clave: solo
                # la lectura de la clave ve el fallo.
                leer = mod.leer_clave_de_backups

                async def leer_fallando(ha):
                    ha.respuestas["backup/config/info"] = respuesta
                    try:
                        return await leer(ha)
                    finally:
                        ha.respuestas["backup/config/info"] = _config_info()

                with patch.object(mod, "leer_clave_de_backups", leer_fallando):
                    r = await self.t["ha_create_backup"](agent_ids=["hassio.local"])
                self.assertEqual(r["reason"], motivo)
                self.assertIn(frase, r["detail"])
                if motivo != "no_key_configured":
                    self.assertNotIn("has no backup encryption key", r["detail"])


class TestCreateBackup(_Base):
    async def test_vista_previa(self) -> None:
        with capture_logs() as logs:
            r = await self.t["ha_create_backup"](
                agent_ids=["hassio.local", "hassio.nas_backups", "cloud.cloud"],
                include_folders=["share", "ssl"], include_all_addons=True, name="Antes de migrar")
        self.assertNotIn("backup/generate", self.ha.tipos())
        p = r["preview"]
        self.assertEqual(p["action"], "create_backup")
        self.assertEqual(p["name"], "Antes de migrar")
        self.assertEqual(p["agents"], [
            {"agent_id": "hassio.local", "kind": "local", "encrypted": True},
            {"agent_id": "hassio.nas_backups", "kind": "mount", "encrypted": True},
            # protected: false en la configuración: HA descifra esa copia.
            {"agent_id": "cloud.cloud", "kind": "remote", "encrypted": False},
        ])
        self.assertEqual(p["content"], {"homeassistant": True, "database": True,
                                        "addons": "all", "folders": ["share", "ssl"]})
        self.assertEqual(len(p["warnings"]), 1)
        self.assertIn("UNENCRYPTED to cloud.cloud", p["warnings"][0])
        self.sin_centinela(r, logs)

    async def test_sin_cifrar_avisa_y_sin_base_de_datos(self) -> None:
        r = await self.t["ha_create_backup"](agent_ids=["hassio.nas_backups"], encrypt=False,
                                             include_database=False)
        p = r["preview"]
        self.assertEqual(p["agents"][0]["encrypted"], False)
        self.assertEqual(p["content"]["database"], False)
        self.assertEqual(len(p["warnings"]), 1)  # solo la base de datos: no es remoto
        self.assertIn("database", p["warnings"][0])

    async def test_confirmar_manda_la_clave(self) -> None:
        args = {"agent_ids": ["hassio.local"], "include_addons": ["core_mosquitto"]}
        with capture_logs() as logs:
            vista = await self.t["ha_create_backup"](**args)
            r = await self.t["ha_create_backup"](
                **args, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r, {"backup_job_id": "job-1", "status": "started",
                             "follow_with": mod._SEGUIMIENTO})
        enviado = self.ha.de_tipo("backup/generate")
        self.assertEqual(len(enviado), 1)
        self.assertEqual(enviado[0], {
            "type": "backup/generate", "agent_ids": ["hassio.local"],
            "include_homeassistant": True, "include_database": True,
            "include_all_addons": False, "include_addons": ["core_mosquitto"],
            "password": _CENTINELA,
        })
        # La clave se lee otra vez en la confirmación (sin caché).
        self.assertEqual(self.ha.tipos().count("backup/config/info"), 4)
        self.sin_centinela(vista, r, logs)

    async def test_la_clave_no_entra_en_el_token(self) -> None:
        # Sin la 019, la huella del token es un SHA-256 en disco: con la
        # clave dentro, se podría atacar sin conexión. Ni args ni estado.
        vistos: list[Any] = []
        crear, resolver = mod.create_confirmation_token, mod.resolve_confirmation_token

        async def espia_crear(tool, args, **kw):
            vistos.append((args, kw.get("estado")))
            return await crear(tool, args, **kw)

        async def espia_resolver(token, tool, args, **kw):
            vistos.append((args, kw.get("estado")))
            return await resolver(token, tool, args, **kw)

        args = {"agent_ids": ["hassio.local"]}
        with patch.object(mod, "create_confirmation_token", espia_crear),                 patch.object(mod, "resolve_confirmation_token", espia_resolver):
            vista = await self.t["ha_create_backup"](**args)
            await self.t["ha_create_backup"](**args,
                                             confirmation_token=vista["confirmation_token"])
        self.assertEqual(len(vistos), 2)
        self.assertNotIn(_CENTINELA, json.dumps(vistos, default=str))
        self.assertTrue(all(e["key_set"] is True for _, e in vistos))

    async def test_clave_rotada_entre_vista_y_confirmacion(self) -> None:
        # La clave se lee otra vez al confirmar y se usa la de ese momento;
        # como no entra en el hash, cambiarla no invalida el token.
        args = {"agent_ids": ["hassio.local"]}
        vista = await self.t["ha_create_backup"](**args)
        self.ha.respuestas["backup/config/info"] = _config_info("otra-clave")
        r = await self.t["ha_create_backup"](**args, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["status"], "started")
        self.assertEqual(self.ha.de_tipo("backup/generate")[0]["password"], "otra-clave")

    async def test_sin_cifrar_no_manda_password(self) -> None:
        args = {"agent_ids": ["hassio.local"], "encrypt": False}
        vista = await self.t["ha_create_backup"](**args)
        await self.t["ha_create_backup"](**args, confirmation_token=vista["confirmation_token"])
        self.assertNotIn("password", self.ha.de_tipo("backup/generate")[0])

    async def test_agentes_cambiados_es_state_changed(self) -> None:
        args = {"agent_ids": ["hassio.local"]}
        vista = await self.t["ha_create_backup"](**args)
        self.ha.respuestas["backup/agents/info"] = _agents_info("hassio.local", "cloud.cloud")
        r = await self.t["ha_create_backup"](**args, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "state_changed")
        self.assertNotIn("backup/generate", self.ha.tipos())

    async def test_cifrado_cambiado_es_state_changed(self) -> None:
        args = {"agent_ids": ["cloud.cloud"]}
        vista = await self.t["ha_create_backup"](**args)
        info = _config_info()
        info["config"]["agents"]["cloud.cloud"]["protected"] = True
        self.ha.respuestas["backup/config/info"] = info
        r = await self.t["ha_create_backup"](**args, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "state_changed")

    async def test_clave_quitada_antes_de_confirmar(self) -> None:
        args = {"agent_ids": ["hassio.local"]}
        vista = await self.t["ha_create_backup"](**args)
        self.ha.respuestas["backup/config/info"] = _config_info(None)
        r = await self.t["ha_create_backup"](**args, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "no_encryption_key")
        self.assertNotIn("backup/generate", self.ha.tipos())

    async def test_manager_ocupado_redactado_y_token_fallido(self) -> None:
        args = {"agent_ids": ["hassio.local"]}
        vista = await self.t["ha_create_backup"](**args)
        self.ha.respuestas["backup/generate"] = HAConnectionError(
            f"Backup manager busy: create_backup password={_CENTINELA}", code="home_assistant_error")
        with capture_logs() as logs:
            r = await self.t["ha_create_backup"](
                **args, confirmation_token=vista["confirmation_token"])
        self.assertIn("Backup manager busy", r["error"])
        self.sin_centinela(r, logs)
        token = json.loads((security.CONFIRMATIONS_DIR
                            / f"{vista['confirmation_token']}.json").read_text(encoding="utf-8"))
        self.assertEqual(token["state"], "failed")


# ── T020: ha_create_automatic_backup ────────────────────────────────────────

class TestCreateAutomaticBackup(_Base):
    async def test_sin_agentes(self) -> None:
        info = _config_info()
        info["config"]["create_backup"]["agent_ids"] = []
        self.montar(_respuestas(**{"backup/config/info": info}))
        r = await self.t["ha_create_automatic_backup"]()
        self.assertEqual(r["error"], "automatic_backups_not_configured")
        self.assertNotIn("confirmation_token", r)

    async def test_vista_previa_y_retencion_solo_por_copias(self) -> None:
        with capture_logs() as logs:
            r = await self.t["ha_create_automatic_backup"]()
        p = r["preview"]
        self.assertEqual(p["action"], "create_automatic_backup")
        self.assertEqual(p["agents"], [
            {"agent_id": "hassio.local", "kind": "local", "encrypted": True},
            {"agent_id": "cloud.cloud", "kind": "remote", "encrypted": False},
        ])
        self.assertEqual(p["content"], {"homeassistant": True, "database": True,
                                        "addons": "all", "folders": ["share"]})
        # copies=3 con cuatro automáticos: tras el nuevo quedan tres → b1 y b2.
        efecto = p["retention_effect"]
        self.assertTrue(efecto["estimate"])
        self.assertEqual([e["backup_id"] for e in efecto["would_delete"]], ["b1", "b2"])
        self.assertTrue(all(e["when"] == "after_next_automatic_backup"
                            for e in efecto["would_delete"]))
        self.assertTrue(any("UNENCRYPTED to cloud.cloud" in a for a in p["warnings"]))
        self.assertNotIn("backup/generate_with_automatic_settings", self.ha.tipos())
        self.sin_centinela(r, logs)

    async def test_sin_clave_no_cifra(self) -> None:
        self.montar(_respuestas(**{"backup/config/info": _config_info(None)}))
        r = await self.t["ha_create_automatic_backup"]()
        self.assertTrue(all(a["encrypted"] is False for a in r["preview"]["agents"]))
        self.assertTrue(any("NOT encrypted" in a for a in r["preview"]["warnings"]))

    async def test_confirmar(self) -> None:
        vista = await self.t["ha_create_automatic_backup"]()
        r = await self.t["ha_create_automatic_backup"](
            confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["backup_job_id"], "job-2")
        self.assertEqual(self.ha.de_tipo("backup/generate_with_automatic_settings"),
                         [{"type": "backup/generate_with_automatic_settings"}])

    async def test_configuracion_o_backups_cambiados(self) -> None:
        for clave, valor in (
            ("backup/config/info", _config_info(retention={"copies": 1, "days": None})),
            ("backup/info", _backup_info(*(_backup(f"b{i}", i) for i in range(1, 7)))),
        ):
            with self.subTest(cambia=clave):
                self.montar(_respuestas())
                vista = await self.t["ha_create_automatic_backup"]()
                self.ha.respuestas[clave] = valor
                r = await self.t["ha_create_automatic_backup"](
                    confirmation_token=vista["confirmation_token"])
                self.assertEqual(r["error"], "state_changed")
                self.assertNotIn("backup/generate_with_automatic_settings", self.ha.tipos())

    async def test_agentes_disponibles_cambiados(self) -> None:
        # T065: la vista previa enseña en qué destinos se guarda y cuáles se
        # saltan; si un agente de los ajustes desaparece (o vuelve) en los
        # 60 s del token, la confirmación no hace nada.
        for antes, despues in (
            (("hassio.local", "cloud.cloud"), ("hassio.local",)),
            (("hassio.local",), ("hassio.local", "cloud.cloud")),
        ):
            with self.subTest(antes=antes, despues=despues):
                self.montar(_respuestas(**{"backup/agents/info": _agents_info(*antes)}))
                vista = await self.t["ha_create_automatic_backup"]()
                self.assertIn("confirmation_token", vista)
                self.ha.respuestas["backup/agents/info"] = _agents_info(*despues)
                r = await self.t["ha_create_automatic_backup"](
                    confirmation_token=vista["confirmation_token"])
                self.assertEqual(r["error"], "state_changed")
                self.assertNotIn("backup/generate_with_automatic_settings", self.ha.tipos())
        # Un agente que no está en los ajustes no cambia nada.
        self.montar(_respuestas())
        vista = await self.t["ha_create_automatic_backup"]()
        self.ha.respuestas["backup/agents/info"] = _agents_info(
            "hassio.local", "hassio.nas_backups", "cloud.cloud", "backup.local")
        r = await self.t["ha_create_automatic_backup"](
            confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["status"], "started")


# ── T021: ha_delete_backup ──────────────────────────────────────────────────

class TestDeleteBackup(_Base):
    async def test_id_invalido(self) -> None:
        for malo in ("../x", "a/b", "", "a.b"):
            r = await self.t["ha_delete_backup"](backup_id=malo)
            self.assertEqual(r["error"], "invalid_argument")
        self.assertEqual(self.ha.enviados, [])

    async def test_no_existe(self) -> None:
        self.montar(_respuestas(**{"backup/details": {"backup": None, "agent_errors": {}}}))
        r = await self.t["ha_delete_backup"](backup_id="b9")
        self.assertEqual(r["error"], "not_found")
        self.assertNotIn("confirmation_token", r)

    async def test_agente_ilegible_falla_cerrado(self) -> None:
        self.montar(_respuestas(**{"backup/details": {
            "backup": _backup("b1", 1),
            "agent_errors": {"cloud.cloud": "Cannot reach https://192.0.2.10/ token=centinela-031"},
        }}))
        r = await self.t["ha_delete_backup"](backup_id="b1")
        self.assertEqual(r["error"], "backup_locations_unreadable")
        self.assertNotIn("confirmation_token", r)
        self.assertNotIn("192.0.2.10", json.dumps(r))
        self.sin_centinela(r)

    async def test_vista_previa(self) -> None:
        # b1 es el único backup con la configuración de HA, y un safety
        # backup de Hermes confirmado en la anotación.
        self.montar(_respuestas(**{"backup/info": _backup_info(
            _backup("b1", 1), _backup("b2", 2, ha=False))}))
        safety_retention.LEDGER_PATH.write_text(json.dumps({"version": 1, "entries": [
            {"name": "hermes-safety-20261101T043000Z", "slug": "b1",
             "confirmed_by": "sync_response", "launched_at": 1.0}]}), encoding="utf-8")
        r = await self.t["ha_delete_backup"](backup_id="b1")
        self.assertNotIn("backup/delete", self.ha.tipos())
        p = r["preview"]
        self.assertEqual(p["backup"], {
            "backup_id": "b1", "name": "Backup b1", "date": "2026-11-01T04:30:00+00:00",
            "homeassistant_version": "2026.11.1", "automatic": True,
            "hermes_safety_backup": True})
        self.assertTrue(p["deleted_from_all_locations"])
        self.assertEqual(p["locations"], [
            {"agent_id": "cloud.cloud", "kind": "remote", "size": 100, "protected": True},
            {"agent_id": "hassio.local", "kind": "local", "size": 100, "protected": True},
        ])
        self.assertEqual(p["lost"], {
            "homeassistant_configuration": True, "database": True,
            "addons": [{"slug": "core_mosquitto", "name": "Mosquitto broker",
                        "version": "6.5.1"}],
            "folders": ["share"]})
        texto = " ".join(p["warnings"])
        self.assertIn("only backup that includes the Home Assistant configuration", texto)
        self.assertIn("safety backup", texto)
        self.assertNotIn("SENTINEL-INSTANCE", json.dumps(r))

    async def test_no_es_safety_backup_sin_confirmar(self) -> None:
        safety_retention.LEDGER_PATH.write_text(json.dumps({"version": 1, "entries": [
            {"name": "hermes-safety-20261101T043000Z", "slug": "b1",
             "confirmed_by": None, "launched_at": 1.0}]}), encoding="utf-8")
        r = await self.t["ha_delete_backup"](backup_id="b1")
        self.assertFalse(r["preview"]["backup"]["hermes_safety_backup"])
        self.assertEqual(len(r["preview"]["warnings"]), 1)

    async def test_confirmar(self) -> None:
        vista = await self.t["ha_delete_backup"](backup_id="b1")
        r = await self.t["ha_delete_backup"](
            backup_id="b1", confirmation_token=vista["confirmation_token"])
        self.assertEqual(r, {"result": "ok", "deleted_from": ["cloud.cloud", "hassio.local"],
                             "failed": {}})
        self.assertEqual(self.ha.de_tipo("backup/delete"),
                         [{"type": "backup/delete", "backup_id": "b1"}])

    async def test_borrado_parcial_enmascarado(self) -> None:
        vista = await self.t["ha_delete_backup"](backup_id="b1")
        self.ha.respuestas["backup/delete"] = {"agent_errors": {
            "cloud.cloud": "Upload failed to https://192.0.2.10/x token=centinela-031"}}
        with capture_logs() as logs:
            r = await self.t["ha_delete_backup"](
                backup_id="b1", confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["result"], "partial")
        self.assertEqual(r["deleted_from"], ["hassio.local"])
        self.assertEqual(list(r["failed"]), ["cloud.cloud"])
        self.assertNotIn("192.0.2.10", json.dumps(r))
        self.sin_centinela(r, logs)

    async def test_falla_en_todas(self) -> None:
        vista = await self.t["ha_delete_backup"](backup_id="b1")
        self.ha.respuestas["backup/delete"] = {"agent_errors": {
            "cloud.cloud": "x", "hassio.local": "y"}}
        r = await self.t["ha_delete_backup"](
            backup_id="b1", confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "delete_failed")

    async def test_ubicacion_nueva_es_state_changed(self) -> None:
        vista = await self.t["ha_delete_backup"](backup_id="b1")
        detalles = _respuestas()["backup/details"]
        detalles["backup"]["agents"]["hassio.nas_backups"] = {"protected": True, "size": 100}
        self.ha.respuestas["backup/details"] = detalles
        r = await self.t["ha_delete_backup"](
            backup_id="b1", confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "state_changed")
        self.assertNotIn("backup/delete", self.ha.tipos())

    async def test_contenido_cambiado_es_state_changed(self) -> None:
        vista = await self.t["ha_delete_backup"](backup_id="b1")
        detalles = _respuestas()["backup/details"]
        detalles["backup"]["folders"] = ["share", "media"]
        self.ha.respuestas["backup/details"] = detalles
        r = await self.t["ha_delete_backup"](
            backup_id="b1", confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "state_changed")

    async def test_otro_backup_con_el_token(self) -> None:
        vista = await self.t["ha_delete_backup"](backup_id="b1")
        r = await self.t["ha_delete_backup"](
            backup_id="b2", confirmation_token=vista["confirmation_token"])
        self.assertIn("does not match", r["error"])
        self.assertNotIn("backup/delete", self.ha.tipos())


if __name__ == "__main__":
    unittest.main()
