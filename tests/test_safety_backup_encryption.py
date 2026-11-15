"""Safety backups cifrados con la clave de HA (spec 031, tramo 4: T049, T051).

`sv_create_safety_backup` y el safety backup automático de `fs_write` mandan
`password` al Supervisor con la clave de los backups de HA (la del kit de
emergencia, `backup/config/info`) según `safety_backup_encryption`:

- `auto`: con clave, cifrado; sin clave (sin configurar, sin integración o HA
  inalcanzable), sin cifrar, con `encryption_skipped_reason` y aviso en el log;
- `required`: sin clave no hay backup (`encryption_key_unavailable`; en el
  automático la escritura no se hace);
- `off`: como en la 1.1.2, sin leer la clave.

La clave (aquí, un centinela) no puede salir en ninguna respuesta, error,
fichero de estado (`last_safety_backup.json`, `safety_backups.json`,
`pending_jobs.json`), fichero de token ni log. La ventana, el límite duro y
el lock no cambian. Datos ficticios (`centinela-031`, `hassio.nas_backups`).

Controles negativos (T059), comprobados con los recuentos en el commit del
tramo: (a) `auto` sin mandar `password` con clave; (b) `required` que crea
sin clave; (c) la clave escrita en `last_safety_backup.json`.
"""

from __future__ import annotations

import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from structlog.testing import capture_logs

import hermes.safety_retention as sr
import hermes.tools.addons as addons_mod
import hermes.tools.backups as backups_mod
from hermes import security
from hermes.ha import HAConnectionError

_CENTINELA = "centinela-031"
_FALTA = object()


class _MCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, *a: Any, **k: Any):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def _config_info(password: Any = _CENTINELA) -> dict[str, Any]:
    return {"config": {
        "agents": {"hassio.nas_backups": {"protected": True, "retention": None}},
        "automatic_backups_configured": True,
        "create_backup": {"agent_ids": ["hassio.local"], "include_addons": None,
                          "include_all_addons": True, "include_database": True,
                          "include_folders": None, "name": None, "password": password},
        "last_attempted_automatic_backup": None,
        "last_completed_automatic_backup": None,
        "next_automatic_backup": None,
        "next_automatic_backup_additional": False,
        "retention": {"copies": 3, "days": None},
        "schedule": {"days": [], "recurrence": "daily", "time": "04:30:00"},
    }}


class _HA:
    """HA (WebSocket) y Supervisor (REST) simulados en un solo cliente.

    `ws` es la respuesta de cada comando WS (una excepción se lanza); los
    POST al Supervisor se graban con su cuerpo para comprobar `password`.
    """

    def __init__(self, ws: dict[str, Any] | None = None,
                 post: Any = None, jobs: dict[str, Any] | None = None) -> None:
        self.ws: dict[str, Any] = {"backup/config/info": _config_info()}
        self.ws.update(ws or {})
        self.post = post if post is not None else {"job_id": "job1"}
        self.jobs = jobs or {}
        self.enviados_ws: list[dict[str, Any]] = []
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.info_backup: dict[str, Any] = {
            "name": "hermes-safety-x", "date": "2026-11-14T04:30:12+00:00",
            "homeassistant": "2026.11.1", "protected": True}

    async def wait_ready(self, timeout: float = 5.0) -> bool:
        return True

    async def ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.enviados_ws.append(copy.deepcopy(payload))
        r = self.ws.get(payload["type"], _FALTA)
        if r is _FALTA:
            raise AssertionError(f"comando inesperado {payload['type']}")
        if isinstance(r, BaseException):
            raise r
        return copy.deepcopy(r)

    async def sv_request(self, method: str, path: str, json_body: Any = None,
                         params: Any = None, timeout_seconds: float = 60.0) -> Any:
        if method == "POST":
            self.posts.append((path, dict(json_body or {})))
            if isinstance(self.post, BaseException):
                raise self.post
            return copy.deepcopy(self.post)
        if method == "GET" and path.startswith("/jobs/"):
            return copy.deepcopy(self.jobs.get(path.rsplit("/", 1)[-1],
                                               {"done": True, "errors": []}))
        if method == "GET" and path.endswith("/info"):
            return copy.deepcopy(self.info_backup)
        if method == "GET" and path == "/backups":
            return {"backups": []}
        raise AssertionError(f"inesperado {method} {path}")

    def leyo_la_clave(self) -> bool:
        return any(p["type"] == "backup/config/info" for p in self.enviados_ws)


_SIN_CLAVE = {
    "no_key_configured": _config_info(password=None),
    "backup_integration_unavailable": HAConnectionError(
        "Unknown command.", code="unknown_command"),
    "ha_unreachable": HAConnectionError("WebSocket no disponible"),
}


class _Base(unittest.IsolatedAsyncioTestCase):
    """Estado de Hermes en un directorio temporal y reloj controlado."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self._orig_dir = security.CONFIRMATIONS_DIR
        security.CONFIRMATIONS_DIR = self.base / "tokens"
        self._parches = [
            patch.object(sr, "LEDGER_PATH", self.base / "safety_backups.json"),
            patch.object(backups_mod, "_SAFETY_BACKUP_STATE_PATH",
                         self.base / "last_safety_backup.json"),
            patch.object(addons_mod, "_PENDING_JOBS_PATH", self.base / "pending_jobs.json"),
        ]
        for p in self._parches:
            p.start()
        self.reloj = [time.time()]

        async def _dormir(segundos: float) -> None:
            self.reloj[0] += segundos

        self._p_time = patch("time.time", side_effect=lambda: self.reloj[0])
        self._p_sleep = patch("asyncio.sleep", side_effect=_dormir)
        self._p_time.start()
        self._p_sleep.start()
        # El último safety backup, hace más de la ventana (30 min).
        backups_mod._save_safety_state({backups_mod._MARCA: self.reloj[0] - 31 * 60})

    def tearDown(self) -> None:
        self._p_sleep.stop()
        self._p_time.stop()
        for p in reversed(self._parches):
            p.stop()
        security.CONFIRMATIONS_DIR = self._orig_dir
        self._tmp.cleanup()

    def tool(self, ha: _HA, modo: str) -> Any:
        mcp = _MCP()
        backups_mod.register(mcp, ha, safety_backup_encryption=modo)
        return mcp.tools["sv_create_safety_backup"]

    async def automatico(self, ha: _HA, modo: str) -> Any:
        from hermes.fs_write import maybe_trigger_safety_backup

        return await maybe_trigger_safety_backup(
            ha, safety_backup_window_minutes=30, enabled=True, keep=0,
            encryption=modo)

    def entradas(self) -> list[dict[str, Any]]:
        ruta = self.base / "safety_backups.json"
        if not ruta.exists():
            return []
        return json.loads(ruta.read_text(encoding="utf-8"))["entries"]

    def ficheros(self) -> str:
        return "".join(p.read_text(encoding="utf-8")
                       for p in self.base.rglob("*") if p.is_file())

    def sin_centinela(self, logs: list[dict[str, Any]], *cosas: Any) -> None:
        for c in [*cosas, logs]:
            self.assertNotIn(_CENTINELA, json.dumps(c, ensure_ascii=False, default=str))
        self.assertNotIn(_CENTINELA, self.ficheros())


# ── T049: sv_create_safety_backup ───────────────────────────────────────────

class TestToolSafetyBackup(_Base):
    async def test_auto_con_clave_cifra(self) -> None:
        ha = _HA()
        with capture_logs() as logs, \
                patch.object(backups_mod, "_track_job", new=AsyncMock()) as track:
            r = await self.tool(ha, "auto")()
        [(ruta, cuerpo)] = ha.posts
        self.assertEqual(ruta, "/backups/new/full")
        self.assertEqual(cuerpo["password"], _CENTINELA)
        self.assertIs(r["encrypted"], True)
        self.assertIn("emergency kit", r["restore_note"])
        self.assertNotIn("encryption_skipped_reason", r)
        [e] = self.entradas()
        self.assertIs(e["encrypted"], True)
        self.assertNotIn(_CENTINELA, json.dumps(track.await_args.args, default=str))
        self.sin_centinela(logs, r)

    async def test_auto_sin_clave_crea_sin_cifrar_y_lo_dice(self) -> None:
        for motivo, respuesta in _SIN_CLAVE.items():
            with self.subTest(motivo=motivo):
                backups_mod._save_safety_state(
                    {backups_mod._MARCA: self.reloj[0] - 31 * 60})
                (self.base / "safety_backups.json").unlink(missing_ok=True)
                ha = _HA(ws={"backup/config/info": respuesta})
                with capture_logs() as logs, \
                        patch.object(backups_mod, "_track_job", new=AsyncMock()):
                    r = await self.tool(ha, "auto")()
                [(_, cuerpo)] = ha.posts
                self.assertNotIn("password", cuerpo)
                self.assertIs(r["encrypted"], False)
                self.assertEqual(r["encryption_skipped_reason"], motivo)
                self.assertIn("NOT encrypted", r["warning"])
                aviso = [l for l in logs if l["event"] == "safety_backup_unencrypted"]
                self.assertEqual(len(aviso), 1)
                self.assertEqual(aviso[0]["reason"], motivo)
                [e] = self.entradas()
                self.assertNotIn("encrypted", e)

    async def test_required_sin_clave_no_crea(self) -> None:
        for motivo, respuesta in _SIN_CLAVE.items():
            with self.subTest(motivo=motivo):
                antes = (self.base / "last_safety_backup.json").read_text(encoding="utf-8")
                ha = _HA(ws={"backup/config/info": respuesta})
                r = await self.tool(ha, "required")()
                self.assertEqual(ha.posts, [])
                self.assertEqual(r["error"], "encryption_key_unavailable")
                self.assertEqual(r["reason"], motivo)
                # No hubo intento: ni estado ni anotación cambian.
                self.assertEqual(
                    (self.base / "last_safety_backup.json").read_text(encoding="utf-8"), antes)
                self.assertEqual(self.entradas(), [])

    async def test_required_con_clave_cifra(self) -> None:
        ha = _HA()
        with patch.object(backups_mod, "_track_job", new=AsyncMock()):
            r = await self.tool(ha, "required")()
        self.assertEqual(ha.posts[0][1]["password"], _CENTINELA)
        self.assertIs(r["encrypted"], True)

    async def test_off_como_en_la_1_1_2(self) -> None:
        ha = _HA()
        with patch.object(backups_mod, "_track_job", new=AsyncMock()):
            r = await self.tool(ha, "off")()
        self.assertEqual(ha.posts, [("/backups/new/full",
                                     {"name": r["backup_name"], "background": True})])
        self.assertFalse(ha.leyo_la_clave())
        self.assertIs(r["encrypted"], False)
        self.assertNotIn("encryption_skipped_reason", r)

    async def test_por_defecto_del_register_es_off(self) -> None:
        # El arranque pasa siempre la opción (por defecto `auto`); quien
        # registra a mano sin ella obtiene la 1.1.2.
        ha = _HA()
        mcp = _MCP()
        backups_mod.register(mcp, ha)
        with patch.object(backups_mod, "_track_job", new=AsyncMock()):
            await mcp.tools["sv_create_safety_backup"]()
        self.assertFalse(ha.leyo_la_clave())

    async def test_error_del_supervisor_que_cita_la_clave_sale_tapado(self) -> None:
        ha = _HA(post=HAConnectionError(f"backup failed with password {_CENTINELA}"))
        with capture_logs() as logs:
            r = await self.tool(ha, "auto")()
        self.assertIn("error", r)
        self.sin_centinela(logs, r)

    async def test_ventana_y_limite_duro_no_leen_la_clave(self) -> None:
        for hace, motivo in ((10, "hard_limit"), (5 * 60, "within_window")):
            with self.subTest(motivo=motivo):
                backups_mod._save_safety_state({backups_mod._MARCA: self.reloj[0] - hace})
                ha = _HA()
                r = await self.tool(ha, "required")()
                self.assertIs(r["reused"], True)
                self.assertEqual(r["reason"], motivo)
                self.assertFalse(ha.leyo_la_clave())
                self.assertEqual(ha.posts, [])

    async def test_lock_ocupado_no_lee_la_clave(self) -> None:
        ha = _HA()
        with patch.object(sr, "acquire_safety_backup_lock", new=AsyncMock(return_value=False)):
            r = await self.tool(ha, "auto")()
        self.assertEqual(r, sr.SAFETY_LOCK_BUSY)
        self.assertFalse(ha.leyo_la_clave())


# ── T049: el safety backup automático (antes de escribir en /config) ───────

class TestSafetyBackupAutomatico(_Base):
    async def test_auto_con_clave_cifra_y_anota(self) -> None:
        ha = _HA(post={"job_id": "job1"}, jobs={"job1": {"done": True, "errors": [],
                                                       "reference": "aaaa0001"}})
        with capture_logs() as logs:
            r = await self.automatico(ha, "auto")
        self.assertIsNone(r)
        self.assertEqual(ha.posts[0][1]["password"], _CENTINELA)
        [e] = self.entradas()
        self.assertIs(e["encrypted"], True)
        disparo = [l for l in logs if l["event"] == "safety_backup_auto_trigger"]
        self.assertIs(disparo[0]["encrypted"], True)
        self.sin_centinela(logs, r)

    async def test_auto_respuesta_sincrona_tambien_anota_cifrado(self) -> None:
        ha = _HA(post={"slug": "deadbeef"})
        r = await self.automatico(ha, "auto")
        self.assertIsNone(r)
        [e] = self.entradas()
        self.assertIs(e["encrypted"], True)
        self.assertEqual(e["slug"], "deadbeef")

    async def test_auto_sin_clave_crea_sin_cifrar_y_avisa(self) -> None:
        for motivo, respuesta in _SIN_CLAVE.items():
            with self.subTest(motivo=motivo):
                # Fuera del límite de 60 s entre intentos (el subtest anterior
                # dejó uno) y con el último backup fuera de la ventana.
                self.reloj[0] += 120
                backups_mod._save_safety_state(
                    {backups_mod._MARCA: self.reloj[0] - 31 * 60})
                ha = _HA(ws={"backup/config/info": respuesta}, post={"slug": "deadbeef"})
                with capture_logs() as logs:
                    r = await self.automatico(ha, "auto")
                self.assertIsNone(r)
                self.assertNotIn("password", ha.posts[0][1])
                aviso = [l for l in logs if l["event"] == "safety_backup_unencrypted"]
                self.assertEqual([a["reason"] for a in aviso], [motivo])
                self.assertEqual(aviso[0]["origin"], "auto")

    async def test_required_sin_clave_bloquea_la_escritura(self) -> None:
        for motivo, respuesta in _SIN_CLAVE.items():
            with self.subTest(motivo=motivo):
                ha = _HA(ws={"backup/config/info": respuesta})
                with capture_logs() as logs:
                    r = await self.automatico(ha, "required")
                self.assertEqual(ha.posts, [])
                self.assertTrue(r["error"].startswith("encryption_key_unavailable"), r)
                self.assertIn("write was not made", r["error"])
                self.assertEqual(r["reason"], motivo)
                fallo = [l for l in logs
                         if l["event"] == "safety_backup_encryption_key_unavailable"]
                self.assertEqual(len(fallo), 1)

    async def test_required_sin_clave_la_tool_de_escritura_no_escribe(self) -> None:
        """La cadena completa: `fs_write_file` confirmado no escribe si el
        safety backup automático responde `encryption_key_unavailable`."""
        from hermes.tools import filesystem_write as fw

        ha = _HA(ws={"backup/config/info": _config_info(password=None)})
        mcp = _MCP()
        fw.register_write(mcp, ha, safety_backup_enabled=True,
                          safety_backup_encryption="required")
        escribir = AsyncMock()
        with patch.object(fw, "reserve_write_slot", new=AsyncMock()), \
             patch.object(fw, "resolve_confirmation_token",
                          new=AsyncMock(return_value=(
                              True, "", {"path": "notas.txt", "content": "hola"}))), \
             patch.object(fw, "complete_confirmation_token", new=AsyncMock()), \
             patch.object(fw, "backup_before_write", new=escribir):
            r = json.loads(await mcp.tools["fs_write_file"](
                "notas.txt", "hola", confirmation_token="t"))
        self.assertEqual(r["error"], "safety_backup_failed")
        self.assertIn("encryption_key_unavailable", r["detail"])
        escribir.assert_not_awaited()
        self.assertEqual(ha.posts, [])

    async def test_off_sin_leer_la_clave(self) -> None:
        ha = _HA(post={"slug": "deadbeef"})
        r = await self.automatico(ha, "off")
        self.assertIsNone(r)
        self.assertFalse(ha.leyo_la_clave())
        self.assertEqual(set(ha.posts[0][1]), {"name", "background"})
        [e] = self.entradas()
        self.assertNotIn("encrypted", e)

    async def test_error_del_post_que_cita_la_clave_sale_tapado(self) -> None:
        ha = _HA(post=HAConnectionError(f"rejected: password={_CENTINELA}"))
        with capture_logs() as logs:
            r = await self.automatico(ha, "auto")
        self.assertTrue(r["error"].startswith("safety_backup_failed"))
        self.sin_centinela(logs, r)

    async def test_ventana_y_limite_duro_no_leen_la_clave(self) -> None:
        for hace in (10, 5 * 60):
            with self.subTest(hace=hace):
                backups_mod._save_safety_state({backups_mod._MARCA: self.reloj[0] - hace})
                ha = _HA()
                self.assertIsNone(await self.automatico(ha, "required"))
                self.assertFalse(ha.leyo_la_clave())
                self.assertEqual(ha.posts, [])

    async def test_desactivado_no_lee_la_clave(self) -> None:
        from hermes.fs_write import maybe_trigger_safety_backup

        ha = _HA()
        r = await maybe_trigger_safety_backup(ha, 30, enabled=False, encryption="required")
        self.assertIsNone(r)
        self.assertFalse(ha.leyo_la_clave())

    def test_register_write_pasa_la_opcion_a_los_cinco_disparos(self) -> None:
        import inspect

        from hermes.tools import filesystem_write as fw

        fuente = inspect.getsource(fw.register_write)
        self.assertEqual(fuente.count("encryption=safety_backup_encryption"), 5)


# ── T051: transversal, el centinela fuera de todo ───────────────────────────

class TestCentinelaTransversal(_Base):
    """Una pasada por las seis tools de `backup_integration` (DV-1),
    `sv_create_safety_backup`, el safety backup automático y las
    `sv_restore_*`, con la clave centinela en HA: nada la saca."""

    def _respuestas(self) -> dict[str, Any]:
        backup = {
            "backup_id": "abc123", "name": "Automatic backup 2026.11.1",
            "date": "2026-11-14T04:30:12+00:00",
            "agents": {"hassio.local": {"protected": True, "size": 100},
                       "hassio.nas_backups": {"protected": True, "size": 100}},
            "addons": [{"slug": "core_mosquitto", "name": "Mosquitto broker",
                        "version": "6.5.1"}],
            "folders": ["share"], "database_included": True,
            "homeassistant_included": True, "homeassistant_version": "2026.11.1",
            "with_automatic_settings": True, "extra_metadata": {},
        }
        return {
            "backup/config/info": _config_info(),
            "backup/agents/info": {"agents": [
                {"agent_id": "hassio.local", "name": "local"},
                {"agent_id": "hassio.nas_backups", "name": "nas_backups"}]},
            "backup/info": {"backups": [backup], "agent_errors": {}, "state": "idle"},
            "backup/details": {"backup": backup, "agent_errors": {}},
            "backup/generate": {"backup_job_id": "job-g"},
            "backup/generate_with_automatic_settings": {"backup_job_id": "job-a"},
            "backup/delete": {"agent_errors": {}},
            "backup/config/update": {},
            "backup/restore": None,
        }

    async def test_ninguna_salida_lleva_la_clave(self) -> None:
        from hermes.tools import ha_backup_actions, ha_backup_restore, ha_backup_settings
        from hermes.tools import ha_backups as hb

        ha = _HA(ws=self._respuestas(), post={"job_id": "job1"},
                 jobs={"job1": {"done": True, "errors": [], "reference": "aaaa0001"}})
        mcp = _MCP()
        for mod in (ha_backup_settings, ha_backup_actions, ha_backup_restore):
            mod.register(mcp, ha)
        backups_mod.register(mcp, ha, safety_backup_encryption="auto")
        t = mcp.tools

        async def dos_pasos(nombre: str, **args: Any) -> list[Any]:
            vista = await t[nombre](**args)
            self.assertIn("confirmation_token", vista, f"{nombre}: {vista}")
            final = await t[nombre](**args, confirmation_token=vista["confirmation_token"])
            self.assertNotIn("error", final, f"{nombre}: {final}")
            return [vista, final]

        salidas: list[Any] = []
        with capture_logs() as logs, \
                patch.object(hb, "ha_at_least", new=AsyncMock(return_value=True)), \
                patch.object(backups_mod, "_track_job", new=AsyncMock()):
            salidas.append(await t["ha_list_backup_agents"]())
            salidas += await dos_pasos("ha_update_backup_config", retention={"copies": 4})
            salidas += await dos_pasos("ha_create_backup", agent_ids=["hassio.local"])
            salidas += await dos_pasos("ha_create_automatic_backup")
            salidas += await dos_pasos("ha_restore_backup", backup_id="abc123",
                                       agent_id="hassio.local")
            salidas += await dos_pasos("ha_delete_backup", backup_id="abc123")
            r = await t["sv_create_safety_backup"]()
            self.assertIs(r["encrypted"], True)
            salidas.append(r)
            self.reloj[0] += 31 * 60
            salidas.append(await self.automatico(ha, "auto"))
            salidas += await dos_pasos("sv_restore_backup_full", slug="abc123")
            salidas += await dos_pasos("sv_restore_backup_partial", slug="abc123",
                                       addons='["core_mosquitto"]')
        # La clave sí viajó a donde tenía que ir: los POST del Supervisor.
        self.assertTrue(all(c.get("password") == _CENTINELA for _, c in ha.posts), ha.posts)
        self.assertGreaterEqual(len(ha.posts), 4)
        self.sin_centinela(logs, *salidas)
