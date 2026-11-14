"""Reautenticación con token en `ha_continue_config_entry_flow` (spec 016,
tramo C; decisión del supervisor, FR-010d).

Un flujo `reauth` cambia las credenciales de una entrada, así que cada paso
que se envía pide token (principio IV), con vista previa de los campos y los
secretos tapados. HA SÍ lista los `reauth` en `config_entries/flow/progress`
(al contrario que los `reconfigure`): la tool mira ahí el `source` antes de
enviar. Si el flujo no aparece o no se puede saber su `source`, sigue como en
la 1.1.2 (riesgo aceptado por el supervisor).

Home Assistant se simula con un `ws_send` y un `_request_json` falsos.
Centinelas de secreto que no deben salir en ninguna respuesta, log ni fichero
de token.

Controles negativos comprobados (T044 h): no mirar el `source` → 11 rojos;
`POST` en la vista previa → 6; token sin `user_input` → 1
(`test_token_con_otro_user_input`); no tapar el selector de contraseña → 2.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from aiohttp import ClientSession
from structlog.testing import capture_logs

import hermes.security as security
import hermes.tools.config_entry_flows as mod
from hermes.ha import HAConnectionError
from hermes.tools import _reconfigure
from tests._ha_fixture import make_ready_client

_CENTINELA = "centinela-016"
_CENTINELA_PIN = "centinela-pin-016"
_RUTA = "/config/config_entries/flow"


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _en_curso(flow_id: str = "flujo-a", source: str = "reauth") -> dict[str, Any]:
    return {"flow_id": flow_id, "handler": "banco_flujos", "step_id": "reauth_confirm",
            "context": {"source": source, "entry_id": "entrada-1",
                        "unique_id": "u-1", "title_placeholders": {"name": "Banco"}}}


def _paso(step_id: str = "reauth_confirm", **kw: Any) -> dict[str, Any]:
    p = {
        "type": "form", "flow_id": "flujo-a", "handler": "banco_flujos",
        "step_id": step_id, "errors": None, "description_placeholders": None,
        "data_schema": [
            {"name": "usuario", "type": "string", "required": True},
            # Contraseña con nombre inocente: solo el selector la delata.
            {"name": "clave", "required": True,
             "selector": {"text": {"type": "password"}},
             "description": {"suggested_value": _CENTINELA_PIN}},
        ],
    }
    p.update(kw)
    return p


class _FakeHA:
    def __init__(self) -> None:
        self.ws: list[dict[str, Any]] = []
        self.rest: list[tuple[str, str, Any]] = []
        self.progreso: Any = [_en_curso(), _en_curso("flujo-d", "zeroconf")]
        self.error_progreso: HAConnectionError | None = None
        self.respuestas: dict[tuple[str, str], Any] = {
            ("GET", f"{_RUTA}/flujo-a"): _paso(),
            ("POST", f"{_RUTA}/flujo-a"): {"type": "abort", "flow_id": "flujo-a",
                                           "handler": "banco_flujos",
                                           "reason": "reauth_successful"},
            ("POST", f"{_RUTA}/flujo-d"): {"type": "create_entry", "flow_id": "flujo-d",
                                           "result": {"entry_id": "nueva"}},
            ("POST", f"{_RUTA}/flujo-x"): {"type": "form", "flow_id": "flujo-x",
                                           "step_id": "user"},
        }

    async def ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.ws.append(payload)
        if payload["type"] == "config_entries/flow/progress":
            if self.error_progreso:
                raise self.error_progreso
            return self.progreso
        raise AssertionError(f"comando inesperado: {payload}")

    async def request_json(self, method: str, path: str, json_body: Any = None,
                           params: dict[str, str] | None = None) -> Any:
        self.rest.append((method, path, json_body))
        r = self.respuestas.get((method, path))
        if isinstance(r, BaseException):
            raise r
        if r is not None:
            return r
        if method == "DELETE":
            return {"message": "Flow aborted"}
        raise AssertionError(f"ruta inesperada: {method} {path}")

    def posts(self) -> list[tuple[str, str, Any]]:
        return [r for r in self.rest if r[0] == "POST"]


class _Base(unittest.IsolatedAsyncioTestCase):
    datos = {"usuario": "banco", "clave": _CENTINELA_PIN, "password": _CENTINELA}

    async def asyncSetUp(self) -> None:
        _reconfigure.limpiar()
        self.session = ClientSession()
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        client = make_ready_client(self.session, {})
        self.fake = _FakeHA()
        client.ws_send = self.fake.ws_send  # type: ignore[method-assign]
        client._request_json = self.fake.request_json  # type: ignore[method-assign]
        self.mcp = DummyMCP()
        mod.register(self.mcp, client)
        self.tool = self.mcp.tools["ha_continue_config_entry_flow"]

    async def asyncTearDown(self) -> None:
        _reconfigure.limpiar()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()
        await self.session.close()

    async def llamar(self, flow_id: str = "flujo-a", user_input: Any = None,
                     token: str | None = None) -> Any:
        datos = self.datos if user_input is None else user_input
        return json.loads(await self.tool(flow_id, datos, token))

    def ficheros_de_tokens(self) -> str:
        return "".join(p.read_text(encoding="utf-8")
                       for p in Path(self.temp_dir.name).glob("*"))


class TestReauthPideToken(_Base):
    async def test_vista_previa_sin_post(self) -> None:
        r = await self.llamar()
        self.assertEqual(self.fake.ws, [{"type": "config_entries/flow/progress"}])
        self.assertIn(("GET", f"{_RUTA}/flujo-a", None), self.fake.rest)
        self.assertEqual(self.fake.posts(), [])
        self.assertIn("confirmation_token", r)
        p = r["preview"]
        self.assertEqual((p["flow_id"], p["source"], p["domain"], p["entry_id"], p["step_id"]),
                         ("flujo-a", "reauth", "banco_flujos", "entrada-1", "reauth_confirm"))
        self.assertEqual(p["user_input"]["usuario"], "banco")
        self.assertEqual(p["user_input"]["clave"], "***REDACTED***")
        self.assertEqual(p["secret_fields"], ["clave", "password"])
        self.assertEqual(p["unknown_fields"], ["password"])
        self.assertIn("credentials", p["effect"])

    async def test_confirmar_envia_un_post(self) -> None:
        token = (await self.llamar())["confirmation_token"]
        r = await self.llamar(token=token)
        self.assertEqual(self.fake.posts(), [("POST", f"{_RUTA}/flujo-a", self.datos)])
        self.assertEqual((r["type"], r["reason"], r["status"]),
                         ("abort", "reauth_successful", "ok"))

    async def test_sin_token_otra_vez_no_envia(self) -> None:
        await self.llamar()
        await self.llamar()
        self.assertEqual(self.fake.posts(), [])

    async def test_token_con_otro_user_input(self) -> None:
        token = (await self.llamar())["confirmation_token"]
        r = await self.llamar(user_input={"usuario": "otro", "clave": "x"}, token=token)
        self.assertIn("error", r)
        self.assertEqual(self.fake.posts(), [])

    async def test_paso_cambiado_entre_vista_y_confirmacion(self) -> None:
        token = (await self.llamar())["confirmation_token"]
        self.fake.respuestas[("GET", f"{_RUTA}/flujo-a")] = _paso(step_id="otro")
        r = await self.llamar(token=token)
        self.assertIn("error", r)
        self.assertEqual(self.fake.posts(), [])

    async def test_token_reutilizado(self) -> None:
        token = (await self.llamar())["confirmation_token"]
        await self.llamar(token=token)
        r = await self.llamar(token=token)
        self.assertIn("error", r)
        self.assertEqual(len(self.fake.posts()), 1)

    async def test_form_siguiente_vuelve_a_pedir_token(self) -> None:
        self.fake.respuestas[("POST", f"{_RUTA}/flujo-a")] = _paso(step_id="segundo")
        token = (await self.llamar())["confirmation_token"]
        r = await self.llamar(token=token)
        self.assertEqual(r["step_id"], "segundo")
        self.assertNotIn(_CENTINELA_PIN, json.dumps(r))
        self.assertIn("confirmation_token", r["continue_with"])

    async def test_flujo_que_ya_no_existe(self) -> None:
        self.fake.respuestas[("GET", f"{_RUTA}/flujo-a")] = HAConnectionError(
            "Invalid flow specified", status=404)
        r = await self.llamar()
        self.assertEqual(r["error"], "not_found")
        self.assertNotIn("confirmation_token", r)

    async def test_lectura_del_paso_que_falla(self) -> None:
        self.fake.respuestas[("GET", f"{_RUTA}/flujo-a")] = HAConnectionError("boom", status=500)
        r = await self.llamar()
        self.assertEqual(r["error"], "preview_unavailable")
        self.assertEqual(self.fake.posts(), [])

    async def test_marcador_de_redaccion_rechazado(self) -> None:
        r = await self.llamar(user_input={"clave": "***REDACTED***"})
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "user_input"))
        self.assertEqual(self.fake.posts(), [])

    async def test_centinelas_fuera_de_vista_log_y_token(self) -> None:
        with capture_logs() as logs:
            r = await self.llamar()
            await self.llamar(token=r["confirmation_token"])
        for c in (_CENTINELA, _CENTINELA_PIN):
            self.assertNotIn(c, json.dumps(r))
            self.assertNotIn(c, str(logs))
            self.assertNotIn(c, self.ficheros_de_tokens())


class TestOtrosFlujosComoEnLa112(_Base):
    async def test_descubrimiento_sin_token(self) -> None:
        r = await self.llamar(flow_id="flujo-d", user_input={})
        self.assertEqual(self.fake.posts(), [("POST", f"{_RUTA}/flujo-d", {})])
        self.assertEqual((r["type"], r["status"]), ("create_entry", "ok"))
        self.assertEqual(r["result"], {"entry_id": "nueva"})

    async def test_flujo_que_no_esta_en_progress(self) -> None:
        # Un flujo `user` (abierto con ha_start_config_entry_flow) no sale en
        # flow/progress: como en la 1.1.2.
        r = await self.llamar(flow_id="flujo-x", user_input={"a": 1})
        self.assertEqual(self.fake.posts(), [("POST", f"{_RUTA}/flujo-x", {"a": 1})])
        self.assertEqual(r["step_id"], "user")

    async def test_si_no_se_puede_leer_progress_como_en_la_112(self) -> None:
        self.fake.error_progreso = HAConnectionError("offline")
        r = await self.llamar(flow_id="flujo-a", user_input={"usuario": "b"})
        self.assertEqual(len(self.fake.posts()), 1)
        self.assertEqual(r["type"], "abort")

    async def test_progress_raro_como_en_la_112(self) -> None:
        self.fake.progreso = {"no": "lista"}
        await self.llamar(flow_id="flujo-a", user_input={"usuario": "b"})
        self.assertEqual(len(self.fake.posts()), 1)

    async def test_flow_id_invalido_sin_leer_nada(self) -> None:
        r = await self.llamar(flow_id="../x", user_input={})
        self.assertIn("error", r)
        self.assertEqual((self.fake.ws, self.fake.rest), ([], []))

    async def test_reconfigure_registrado_sigue_rechazado_sin_leer(self) -> None:
        _reconfigure.registrar("flujo-a", "entrada-1", "banco_flujos", "Banco")
        r = await self.llamar()
        self.assertEqual(r["error"], "use_dedicated_tool")
        self.assertEqual((self.fake.ws, self.fake.rest), ([], []))


if __name__ == "__main__":
    unittest.main()
