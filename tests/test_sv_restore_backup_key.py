"""`sv_restore_backup_*` con la clave de HA (spec 031, tramo 3: T037, FR-015).

Sin `password`, un backup protegido se restaura con la clave de cifrado de los
backups de HA (la del kit de emergencia), que `backup/config/info` devuelve en
claro. La vista previa dice `password_source`, nunca el valor; el centinela
no sale en la vista previa, la respuesta, el log ni el directorio de tokens.
Con `password`, todo sigue como en la 1.1.2.

Control negativo (T045 f), comprobado: sin mandar la clave en el POST de
`sv_restore_backup_full` cae `test_protegido_sin_password_usa_la_clave`
(subtest «full»).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from structlog.testing import capture_logs

import hermes.tools.addons as addons_mod
import hermes.tools.backups as backups_mod
from hermes import security
from hermes.ha import HAConnectionError

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
    def __init__(self, protegido: Any = True, clave: Any = _CENTINELA) -> None:
        self.info: Any = {"name": "Full backup", "date": "2026-11-14T04:30:12+00:00",
                          "homeassistant": "2026.11.1", "protected": protegido}
        self.config: Any = {"config": {"create_backup": {"password": clave}}}
        self.posts: list[tuple[str, Any]] = []
        self.ws: list[str] = []
        self.error_post: HAConnectionError | None = None

    async def wait_ready(self, timeout: float = 5.0) -> bool:
        return True

    async def ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.ws.append(payload["type"])
        assert payload["type"] == "backup/config/info", payload
        if isinstance(self.config, Exception):
            raise self.config
        return self.config

    async def sv_request(self, method: str, path: str, json_body: Any = None,
                         params: Any = None, timeout_seconds: float = 60.0) -> Any:
        if method == "GET" and path.endswith("/info"):
            if isinstance(self.info, Exception):
                raise self.info
            return self.info
        if method == "POST":
            self.posts.append((path, dict(json_body or {})))
            if self.error_post is not None:
                raise self.error_post
            return {"job_id": "job-r1"}
        raise AssertionError(f"inesperado {method} {path}")


_TOOLS = {
    "full": ("sv_restore_backup_full", {}),
    "partial": ("sv_restore_backup_partial", {"addons": '["core_mosquitto"]'}),
}


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self._orig_dir = security.CONFIRMATIONS_DIR
        security.CONFIRMATIONS_DIR = base / "tokens"
        self._parches = [
            patch.object(addons_mod, "_PENDING_JOBS_PATH", base / "pending_jobs.json"),
            patch.object(backups_mod, "_SAFETY_BACKUP_STATE_PATH",
                         base / "last_safety_backup.json"),
        ]
        for p in self._parches:
            p.start()
        self.montar(_HA())

    def tearDown(self) -> None:
        for p in self._parches:
            p.stop()
        security.CONFIRMATIONS_DIR = self._orig_dir
        self._tmp.cleanup()

    def montar(self, ha: _HA) -> None:
        self.ha = ha
        mcp = _MCP()
        backups_mod.register(mcp, ha)
        self.t = mcp.tools

    async def ciclo(self, cual: str, **extra: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        nombre, args = _TOOLS[cual]
        args = {**args, **extra}
        vista = await self.t[nombre]("abc123", **args)
        r = await self.t[nombre]("abc123", confirmation_token=vista["confirmation_token"],
                                 **args)
        return vista, r

    def ficheros(self) -> str:
        return "".join(p.read_text(encoding="utf-8")
                       for p in Path(self._tmp.name).rglob("*") if p.is_file())


class TestClaveDeHA(_Base):
    async def test_protegido_sin_password_usa_la_clave(self) -> None:
        for cual in _TOOLS:
            with self.subTest(cual):
                self.montar(_HA())
                with capture_logs() as logs:
                    vista, r = await self.ciclo(cual)
                self.assertEqual(vista["preview"]["password_source"], "backup_encryption_key")
                self.assertEqual(r["job_id"], "job-r1")
                [(_, cuerpo)] = self.ha.posts
                self.assertEqual(cuerpo["password"], _CENTINELA)
                for cosa in (vista, r, logs):
                    self.assertNotIn(_CENTINELA, json.dumps(cosa, default=str))
                self.assertNotIn(_CENTINELA, self.ficheros())

    async def test_sin_clave_en_ha(self) -> None:
        for cual in _TOOLS:
            with self.subTest(cual):
                self.montar(_HA(clave=None))
                vista, r = await self.ciclo(cual)
                p = vista["preview"]
                self.assertEqual(p["password_source"], "backup_encryption_key_unavailable")
                self.assertEqual(p["password_source_reason"], "no_key_configured")
                self.assertIn("unless you pass password", p["password_warning"])
                [(_, cuerpo)] = self.ha.posts
                self.assertNotIn("password", cuerpo)

    async def test_con_password_como_hoy(self) -> None:
        for cual in _TOOLS:
            with self.subTest(cual):
                self.montar(_HA())
                vista, r = await self.ciclo(cual, password="la-del-cliente")
                self.assertEqual(vista["preview"]["password_source"], "provided")
                [(_, cuerpo)] = self.ha.posts
                self.assertEqual(cuerpo["password"], "la-del-cliente")
                # Ni siquiera se lee la clave.
                self.assertEqual(self.ha.ws, [])

    async def test_no_protegido(self) -> None:
        for cual in _TOOLS:
            with self.subTest(cual):
                self.montar(_HA(protegido=False))
                vista, _ = await self.ciclo(cual)
                self.assertEqual(vista["preview"]["password_source"], "not_needed")
                [(_, cuerpo)] = self.ha.posts
                self.assertNotIn("password", cuerpo)
                self.assertEqual(self.ha.ws, [])

    async def test_info_ilegible(self) -> None:
        # Sin `/info` no se sabe si está protegido: como en la 1.1.2, sin
        # contraseña, y la vista previa lo dice.
        ha = _HA()
        ha.info = HAConnectionError("Supervisor error: boom")
        self.montar(ha)
        vista, _ = await self.ciclo("full")
        self.assertEqual(vista["preview"]["password_source"], "unknown")
        self.assertNotIn("password", self.ha.posts[0][1])

    async def test_contrasena_rechazada_da_la_pista(self) -> None:
        for cual in _TOOLS:
            with self.subTest(cual):
                ha = _HA()
                ha.error_post = HAConnectionError(
                    f"Supervisor error: Invalid password for backup abc123 ({_CENTINELA})")
                self.montar(ha)
                vista, r = await self.ciclo(cual)
                self.assertIn("Invalid password", r["error"])
                self.assertIn("older key", r["hint"])
                self.assertNotIn(_CENTINELA, json.dumps(r))
                self.assertNotIn(_CENTINELA, self.ficheros())
        # Con password del cliente, sin la pista de la clave de HA.
        ha = _HA()
        ha.error_post = HAConnectionError("Supervisor error: Invalid password for backup")
        self.montar(ha)
        _, r = await self.ciclo("full", password="otra")
        self.assertNotIn("hint", r)

    async def test_clave_quitada_entre_vista_y_confirmacion(self) -> None:
        vista = await self.t["sv_restore_backup_full"]("abc123")
        self.ha.config = {"config": {"create_backup": {"password": None}}}
        r = await self.t["sv_restore_backup_full"](
            "abc123", confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "state_changed")
        self.assertEqual(self.ha.posts, [])


if __name__ == "__main__":
    unittest.main()
