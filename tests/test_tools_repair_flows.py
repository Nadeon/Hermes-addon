"""Tests de las tools de `repair_flows` (spec 016, tramo C; T034-T037).

Home Assistant se simula con un `ws_send` y un `_request_json` falsos que
registran cada llamada. Datos ficticios (`banco_flujos`, `aviso_reparable`,
`flujo-1`) y centinelas de secreto que no deben salir en ninguna respuesta,
vista previa, log ni fichero de token.

Controles negativos comprobados (T044; rojos en este fichero salvo g):
(c) abrir el flujo sin comprobar `is_fixable` → 1
    (`test_no_reparable_sin_post`);
(d) `POST` en la vista previa → 10; no comprobar el dominio del flujo → 2
    (`test_flujo_de_otro_dominio*`); token sin `user_input` → 1
    (`test_token_con_otro_user_input`);
(e) `user_input` sin redactar en la vista previa → 2
    (`test_centinela_*`);
(f) `issue_data` sin mirar el tope → 1 (`test_issue_data_grande`);
(g) `repairs/get_issue_data` en `deny` → 1 en
    `tests/test_tools_generic_commands.py`; sacar `ha_continue_repair_fix` de
    `_DESTRUCTIVE_EXACT` → 2 en `tests/test_tools_registration.py`.
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
import hermes.tools.repair_flows as mod
from hermes.ha import HAConnectionError
from tests._ha_fixture import make_ready_client

_CENTINELA = "centinela-016"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJiYW5jbyJ9.c2lnbmF0dXJhLWRlLXBydWViYQ"
_RUTA = "/repairs/issues/fix"


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _aviso(issue_id: str, **kw: Any) -> dict[str, Any]:
    a = {
        "domain": "banco_flujos", "issue_id": issue_id, "issue_domain": "banco_flujos",
        "severity": "warning", "is_fixable": True, "breaks_in_ha_version": None,
        "created": "2026-11-01T10:00:00+00:00", "ignored": False,
        "dismissed_version": None, "translation_key": issue_id,
        "translation_placeholders": {"valor": "42"}, "learn_more_url": None,
    }
    a.update(kw)
    return a


_RECURSOS = {
    "component.banco_flujos.issues.aviso_reparable.title": "Value {valor} to confirm",
    "component.banco_flujos.issues.aviso_reparable.description": "The value {valor} must be confirmed.",
    "component.banco_flujos.issues.aviso_reparable.fix_flow.step.confirm.title": "Confirm the value",
    "component.banco_flujos.issues.aviso_reparable.fix_flow.step.confirm.description": "Submit to confirm {valor}.",
    "component.banco_flujos.issues.aviso_reparable.fix_flow.abort.ya_hecho": "Already done",
}


def _paso(step_id: str = "confirm", **kw: Any) -> dict[str, Any]:
    p = {
        "type": "form", "flow_id": "flujo-1", "handler": "banco_flujos",
        "step_id": step_id, "errors": None, "description_placeholders": None,
        "last_step": None, "preview": None,
        "data_schema": [
            {"name": "nota", "optional": True, "type": "string"},
            {"name": "clave", "optional": True,
             "selector": {"text": {"type": "password"}}},
        ],
    }
    p.update(kw)
    return p


class _FakeHA:
    def __init__(self) -> None:
        self.ws: list[dict[str, Any]] = []
        self.rest: list[tuple[str, str, Any]] = []
        self.issues: list[dict[str, Any]] = [
            _aviso("aviso_reparable"),
            _aviso("aviso_fijo", is_fixable=False),
            _aviso("aviso_ignorado", ignored=True, dismissed_version="2026.11.0"),
        ]
        self.issue_data: Any = {"origen": "banco", "password": _CENTINELA,
                                "nota": f"token {_JWT}"}
        self.recursos: dict[str, str] = dict(_RECURSOS)
        self.errores_ws: dict[str, HAConnectionError] = {}
        # Tras el POST que termina el flujo, el aviso desaparece de la lista.
        self.borrar_al_terminar = True
        self.respuestas: dict[tuple[str, str], Any] = {
            ("POST", _RUTA): _paso(),
            ("GET", f"{_RUTA}/flujo-1"): _paso(),
            ("POST", f"{_RUTA}/flujo-1"): {
                "type": "create_entry", "flow_id": "flujo-1", "handler": "banco_flujos",
                "description": None, "description_placeholders": None,
            },
        }

    async def ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.ws.append(payload)
        tipo = payload["type"]
        if tipo in self.errores_ws:
            raise self.errores_ws[tipo]
        if tipo == "repairs/list_issues":
            return {"issues": [dict(i) for i in self.issues]}
        if tipo == "repairs/get_issue_data":
            if not any(i["issue_id"] == payload["issue_id"] for i in self.issues):
                raise HAConnectionError("Issue not found", code="unknown_issue")
            return {"issue_data": self.issue_data}
        if tipo == "get_config":
            return {"language": "es"}
        if tipo == "frontend/get_translations":
            return {"resources": self.recursos}
        raise AssertionError(f"comando inesperado: {payload}")

    async def request_json(self, method: str, path: str, json_body: Any = None,
                           params: dict[str, str] | None = None) -> Any:
        self.rest.append((method, path, json_body))
        r = self.respuestas.get((method, path))
        if isinstance(r, BaseException):
            raise r
        if r is not None:
            if (method == "POST" and isinstance(r, dict)
                    and r.get("type") == "create_entry" and self.borrar_al_terminar):
                self.issues = [i for i in self.issues if i["issue_id"] != "aviso_reparable"]
            return r
        if method == "DELETE":
            return {"message": "Flow aborted"}
        raise AssertionError(f"ruta inesperada: {method} {path}")

    def tipos(self) -> list[str]:
        return [p["type"] for p in self.ws]

    def posts(self) -> list[tuple[str, str, Any]]:
        return [r for r in self.rest if r[0] == "POST"]


class _Base(unittest.IsolatedAsyncioTestCase):
    max_bytes = 131_072

    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        client = make_ready_client(self.session, {})
        self.fake = _FakeHA()
        client.ws_send = self.fake.ws_send  # type: ignore[method-assign]
        client._request_json = self.fake.request_json  # type: ignore[method-assign]
        self.mcp = DummyMCP()
        mod.register(self.mcp, client, response_max_bytes=self.max_bytes)
        self.t = self.mcp.tools

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()
        await self.session.close()

    async def llamar(self, tool: str, *args: Any, **kwargs: Any) -> Any:
        return json.loads(await self.t[tool](*args, **kwargs))

    def ficheros_de_tokens(self) -> str:
        return "".join(p.read_text(encoding="utf-8")
                       for p in Path(self.temp_dir.name).glob("*"))


class TestRegistro(_Base):
    def test_registra_las_cuatro(self) -> None:
        self.assertEqual(set(self.t), {"ha_get_repair", "ha_start_repair_fix",
                                       "ha_continue_repair_fix", "ha_abort_repair_fix"})


# ── T034: ha_get_repair ───────────────────────────────────────────────────────


class TestGetRepair(_Base):
    async def test_resumen_texto_y_datos(self) -> None:
        r = await self.llamar("ha_get_repair", "banco_flujos", "aviso_reparable")
        self.assertEqual(self.fake.tipos()[:2],
                         ["repairs/list_issues", "repairs/get_issue_data"])
        self.assertEqual(self.fake.ws[1], {"type": "repairs/get_issue_data",
                                           "domain": "banco_flujos",
                                           "issue_id": "aviso_reparable"})
        aviso = r["issue"]
        self.assertEqual((aviso["domain"], aviso["issue_id"], aviso["severity"]),
                         ("banco_flujos", "aviso_reparable", "warning"))
        self.assertEqual(aviso["title"], "Value 42 to confirm")
        self.assertEqual(aviso["description"], "The value 42 must be confirmed.")
        self.assertEqual(r["issue_data"]["origen"], "banco")
        self.assertFalse(r["issue_data_truncated"])
        self.assertEqual((r["language"], r["translations_unavailable"]), ("es", False))
        self.assertIn("_third_party_text", r)

    async def test_mismo_resumen_que_la_lista_con_texto_entero(self) -> None:
        clave = "component.banco_flujos.issues.aviso_reparable.description"
        self.fake.recursos[clave] = "z" * 1500
        r = await self.llamar("ha_get_repair", "banco_flujos", "aviso_reparable")
        self.assertEqual(len(r["issue"]["description"]), 1500)
        self.assertFalse(r["issue"]["description_truncated"])

    async def test_ignorados_tambien(self) -> None:
        r = await self.llamar("ha_get_repair", "banco_flujos", "aviso_ignorado")
        self.assertTrue(r["issue"]["ignored"])

    async def test_inexistente_sin_get_issue_data(self) -> None:
        r = await self.llamar("ha_get_repair", "banco_flujos", "no_existe")
        self.assertEqual(r["error"], "not_found")
        self.assertNotIn("repairs/get_issue_data", self.fake.tipos())

    async def test_unknown_issue_es_not_found(self) -> None:
        self.fake.errores_ws["repairs/get_issue_data"] = HAConnectionError(
            "Issue not found", code="unknown_issue")
        r = await self.llamar("ha_get_repair", "banco_flujos", "aviso_reparable")
        self.assertEqual(r["error"], "not_found")

    async def test_datos_redactados_por_clave_y_por_patron(self) -> None:
        with capture_logs() as logs:
            texto = await self.t["ha_get_repair"]("banco_flujos", "aviso_reparable")
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn(_JWT, texto)
        self.assertNotIn(_CENTINELA, str(logs))
        self.assertEqual(json.loads(texto)["issue_data"]["origen"], "banco")

    async def test_argumentos_invalidos(self) -> None:
        r = await self.llamar("ha_get_repair", "", "aviso_reparable")
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "domain"))
        self.assertEqual(self.fake.ws, [])


class TestGetRepairTope(_Base):
    max_bytes = 4096

    async def test_issue_data_grande(self) -> None:
        self.fake.issue_data = {"a": "x" * 10_000, "b": 1}
        texto = await self.t["ha_get_repair"]("banco_flujos", "aviso_reparable")
        r = json.loads(texto)  # nunca un JSON cortado
        self.assertTrue(r["issue_data_truncated"])
        self.assertEqual(r["issue_data"]["keys"], ["a", "b"])
        self.assertGreater(r["issue_data"]["size_bytes"], 10_000)
        self.assertLessEqual(len(texto.encode("utf-8")), self.max_bytes)


# ── T035: ha_start_repair_fix ─────────────────────────────────────────────────


class TestStartRepairFix(_Base):
    async def test_inexistente_sin_post(self) -> None:
        r = await self.llamar("ha_start_repair_fix", "banco_flujos", "no_existe")
        self.assertEqual(r["error"], "not_found")
        self.assertEqual(self.fake.posts(), [])

    async def test_no_reparable_sin_post(self) -> None:
        r = await self.llamar("ha_start_repair_fix", "banco_flujos", "aviso_fijo")
        self.assertEqual(r["error"], "not_fixable")
        self.assertEqual(self.fake.posts(), [])

    async def test_camino_feliz(self) -> None:
        r = await self.llamar("ha_start_repair_fix", "banco_flujos", "aviso_reparable")
        self.assertEqual(self.fake.posts(),
                         [("POST", _RUTA, {"handler": "banco_flujos",
                                           "issue_id": "aviso_reparable"})])
        self.assertEqual((r["type"], r["flow_id"], r["step_id"]), ("form", "flujo-1", "confirm"))
        self.assertEqual(r["issue"], {"domain": "banco_flujos", "issue_id": "aviso_reparable",
                                      "title": "Value 42 to confirm"})
        self.assertEqual(r["step_text"], {"title": "Confirm the value",
                                          "description": "Submit to confirm 42.",
                                          "source": "fix_flow"})
        self.assertFalse(r["finished_on_start"])
        self.assertIn("ha_continue_repair_fix", r["continue_with"])
        self.assertIn("_third_party_text", r)

    async def test_sin_texto_del_paso_usa_el_del_aviso(self) -> None:
        self.fake.respuestas[("POST", _RUTA)] = _paso(step_id="otro")
        r = await self.llamar("ha_start_repair_fix", "banco_flujos", "aviso_reparable")
        self.assertEqual(r["step_text"]["source"], "issue")
        self.assertEqual(r["step_text"]["title"], "Value 42 to confirm")

    async def test_create_entry_al_abrir(self) -> None:
        self.fake.respuestas[("POST", _RUTA)] = {
            "type": "create_entry", "flow_id": "flujo-1", "handler": "banco_flujos"}
        self.fake.issues = [i for i in self.fake.issues if i["issue_id"] != "x"]
        self.fake.borrar_al_terminar = True
        r = await self.llamar("ha_start_repair_fix", "banco_flujos", "aviso_reparable")
        self.assertTrue(r["finished_on_start"])
        self.assertEqual((r["type"], r["status"]), ("create_entry", "ok"))
        self.assertFalse(r["issue_still_present"])
        # Se relee la lista después del POST.
        self.assertEqual(self.fake.tipos().count("repairs/list_issues"), 2)

    async def test_abort_al_abrir(self) -> None:
        self.fake.respuestas[("POST", _RUTA)] = {
            "type": "abort", "flow_id": "flujo-1", "handler": "banco_flujos",
            "reason": "ya_hecho", "description_placeholders": None}
        r = await self.llamar("ha_start_repair_fix", "banco_flujos", "aviso_reparable")
        self.assertTrue(r["finished_on_start"])
        self.assertEqual((r["reason"], r["reason_text"]), ("ya_hecho", "Already done"))

    async def test_externo_se_aborta(self) -> None:
        for tipo in ("external", "progress"):
            self.fake.rest.clear()
            self.fake.respuestas[("POST", _RUTA)] = {
                "type": tipo, "flow_id": "flujo-1", "handler": "banco_flujos"}
            r = await self.llamar("ha_start_repair_fix", "banco_flujos", "aviso_reparable")
            self.assertEqual((r["error"], r["type"]), ("non_automatable", tipo))
            self.assertIn(("DELETE", f"{_RUTA}/flujo-1", None), self.fake.rest)

    async def test_error_de_ha_redactado(self) -> None:
        self.fake.respuestas[("POST", _RUTA)] = HAConnectionError(
            f"400: bad {_JWT}", status=400)
        texto = await self.t["ha_start_repair_fix"]("banco_flujos", "aviso_reparable")
        self.assertIn("error", json.loads(texto))
        self.assertNotIn(_JWT, texto)


# ── T036: ha_continue_repair_fix ──────────────────────────────────────────────


class TestContinueRepairFix(_Base):
    datos = {"nota": "vale", "password": _CENTINELA}

    async def vista(self, user_input: Any = None, **kw: Any) -> dict[str, Any]:
        datos = self.datos if user_input is None else user_input
        return await self.llamar("ha_continue_repair_fix", kw.get("domain", "banco_flujos"),
                                 kw.get("issue_id", "aviso_reparable"),
                                 kw.get("flow_id", "flujo-1"), datos)

    async def confirmar(self, token: str, user_input: Any = None, **kw: Any) -> dict[str, Any]:
        datos = self.datos if user_input is None else user_input
        return await self.llamar("ha_continue_repair_fix", kw.get("domain", "banco_flujos"),
                                 kw.get("issue_id", "aviso_reparable"),
                                 kw.get("flow_id", "flujo-1"), datos, token)

    # (a) validación sin llamar
    async def test_flow_id_invalido(self) -> None:
        r = await self.vista(flow_id="a/b")
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "flow_id"))
        self.assertEqual((self.fake.ws, self.fake.rest), ([], []))

    async def test_user_input_que_no_es_objeto(self) -> None:
        r = await self.vista(user_input=["no"])
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "user_input"))
        self.assertEqual((self.fake.ws, self.fake.rest), ([], []))

    async def test_user_input_por_defecto_vacio(self) -> None:
        r = await self.llamar("ha_continue_repair_fix", "banco_flujos",
                              "aviso_reparable", "flujo-1")
        self.assertEqual(r["preview"]["user_input"], {})

    # (b) vista previa
    async def test_vista_previa_sin_post(self) -> None:
        r = await self.vista()
        self.assertIn(("GET", f"{_RUTA}/flujo-1", None), self.fake.rest)
        self.assertEqual(self.fake.posts(), [])
        p = r["preview"]
        self.assertEqual(p["issue"], {"domain": "banco_flujos", "issue_id": "aviso_reparable",
                                      "title": "Value 42 to confirm", "severity": "warning"})
        self.assertEqual((p["flow_id"], p["step_id"]), ("flujo-1", "confirm"))
        self.assertEqual(p["step_text"]["source"], "fix_flow")
        self.assertEqual(p["user_input"]["nota"], "vale")
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertIn("may apply the fix", p["effect"])
        self.assertIn("issue shown is the one given", p["note"])
        self.assertIn("confirmation_token", r)

    async def test_flujo_de_otro_dominio(self) -> None:
        self.fake.respuestas[("GET", f"{_RUTA}/flujo-1")] = _paso(handler="hue")
        r = await self.vista()
        self.assertEqual((r["error"], r["flow_domain"]), ("flow_mismatch", "hue"))
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.fake.posts(), [])

    async def test_flujo_de_otro_dominio_al_confirmar(self) -> None:
        token = (await self.vista())["confirmation_token"]
        self.fake.respuestas[("GET", f"{_RUTA}/flujo-1")] = _paso(handler="hue")
        r = await self.confirmar(token)
        self.assertEqual(r["error"], "flow_mismatch")
        self.assertEqual(self.fake.posts(), [])

    async def test_aviso_inexistente(self) -> None:
        r = await self.vista(issue_id="no_existe")
        self.assertEqual(r["error"], "not_found")
        self.assertNotIn("confirmation_token", r)

    async def test_flujo_inexistente(self) -> None:
        self.fake.respuestas[("GET", f"{_RUTA}/flujo-1")] = HAConnectionError(
            "Invalid flow specified", status=404)
        r = await self.vista()
        self.assertEqual(r["error"], "not_found")
        self.assertNotIn("confirmation_token", r)

    async def test_lectura_que_falla(self) -> None:
        self.fake.respuestas[("GET", f"{_RUTA}/flujo-1")] = HAConnectionError("boom", status=500)
        r = await self.vista()
        self.assertEqual(r["error"], "preview_unavailable")
        self.fake.respuestas[("GET", f"{_RUTA}/flujo-1")] = _paso()
        self.fake.errores_ws["repairs/list_issues"] = HAConnectionError("offline")
        r = await self.vista()
        self.assertEqual(r["error"], "preview_unavailable")
        self.assertEqual(self.fake.posts(), [])

    # (c) confirmación
    async def test_confirmar_create_entry(self) -> None:
        token = (await self.vista())["confirmation_token"]
        r = await self.confirmar(token)
        self.assertEqual(self.fake.posts(), [("POST", f"{_RUTA}/flujo-1", self.datos)])
        self.assertEqual((r["type"], r["status"]), ("create_entry", "ok"))
        self.assertIs(r["issue_still_present"], False)

    async def test_confirmar_y_el_aviso_sigue(self) -> None:
        self.fake.borrar_al_terminar = False
        token = (await self.vista())["confirmation_token"]
        r = await self.confirmar(token)
        self.assertIs(r["issue_still_present"], True)

    async def test_relectura_que_falla(self) -> None:
        token = (await self.vista())["confirmation_token"]
        llamadas = {"n": 0}
        original = self.fake.ws_send

        async def ws(payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
            if payload["type"] == "repairs/list_issues" and self.fake.posts():
                raise HAConnectionError("offline")
            llamadas["n"] += 1
            return await original(payload, timeout_seconds)

        self.t = {}
        mcp = DummyMCP()
        client = make_ready_client(self.session, {})
        client.ws_send = ws  # type: ignore[method-assign]
        client._request_json = self.fake.request_json  # type: ignore[method-assign]
        mod.register(mcp, client, response_max_bytes=self.max_bytes)
        self.t = mcp.tools
        r = await self.confirmar(token)
        self.assertIsNone(r["issue_still_present"])
        self.assertIn("issue_check_error", r)

    async def test_form_siguiente(self) -> None:
        self.fake.respuestas[("POST", f"{_RUTA}/flujo-1")] = _paso(step_id="segundo")
        token = (await self.vista())["confirmation_token"]
        r = await self.confirmar(token)
        self.assertEqual((r["type"], r["step_id"]), ("form", "segundo"))
        self.assertIn("step_text", r)
        self.assertIn("new preview", r["continue_with"])

    async def test_error_400_redactado_y_token_gastado(self) -> None:
        self.fake.respuestas[("POST", f"{_RUTA}/flujo-1")] = HAConnectionError(
            f"400: {{'errors': {{'nota': 'bad {_JWT}'}}}}", status=400)
        token = (await self.vista())["confirmation_token"]
        texto = await self.t["ha_continue_repair_fix"](
            "banco_flujos", "aviso_reparable", "flujo-1", self.datos, token)
        self.assertIn("error", json.loads(texto))
        self.assertNotIn(_JWT, texto)
        r = await self.confirmar(token)
        self.assertIn("error", r)
        self.assertEqual(len(self.fake.posts()), 1)

    # (d) token atado
    async def test_token_con_otro_flow_id(self) -> None:
        self.fake.respuestas[("GET", f"{_RUTA}/flujo-2")] = _paso(flow_id="flujo-2")
        token = (await self.vista())["confirmation_token"]
        r = await self.confirmar(token, flow_id="flujo-2")
        self.assertIn("error", r)
        self.assertEqual(self.fake.posts(), [])

    async def test_token_con_otro_issue_id(self) -> None:
        self.fake.issues.append(_aviso("otro_aviso"))
        token = (await self.vista())["confirmation_token"]
        r = await self.confirmar(token, issue_id="otro_aviso")
        self.assertIn("error", r)
        self.assertEqual(self.fake.posts(), [])

    async def test_token_con_otro_user_input(self) -> None:
        token = (await self.vista())["confirmation_token"]
        r = await self.confirmar(token, user_input={"nota": "otra"})
        self.assertIn("error", r)
        self.assertEqual(self.fake.posts(), [])

    async def test_paso_cambiado_entre_vista_y_confirmacion(self) -> None:
        token = (await self.vista())["confirmation_token"]
        self.fake.respuestas[("GET", f"{_RUTA}/flujo-1")] = _paso(step_id="otro")
        r = await self.confirmar(token)
        self.assertIn("error", r)
        self.assertEqual(self.fake.posts(), [])

    async def test_token_reutilizado(self) -> None:
        self.fake.borrar_al_terminar = False
        token = (await self.vista())["confirmation_token"]
        await self.confirmar(token)
        r = await self.confirmar(token)
        self.assertIn("error", r)
        self.assertEqual(len(self.fake.posts()), 1)

    async def test_marcador_de_redaccion_rechazado(self) -> None:
        r = await self.vista(user_input={"clave": "***REDACTED***"})
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "user_input"))

    # (e) centinelas
    async def test_centinela_fuera_de_la_vista_del_log_y_del_token(self) -> None:
        datos = {"nota": "vale", "password": _CENTINELA, "clave": "centinela-pin-016"}
        with capture_logs() as logs:
            r = await self.vista(user_input=datos)
            await self.confirmar(r["confirmation_token"], user_input=datos)
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertNotIn("centinela-pin-016", json.dumps(r))
        self.assertEqual(r["preview"]["user_input"]["clave"], "***REDACTED***")
        self.assertNotIn(_CENTINELA, str(logs))
        self.assertNotIn(_CENTINELA, self.ficheros_de_tokens())
        self.assertNotIn("centinela-pin-016", self.ficheros_de_tokens())

    async def test_centinela_en_la_respuesta_del_paso(self) -> None:
        siguiente = _paso(step_id="segundo")
        siguiente["data_schema"][1]["description"] = {"suggested_value": _CENTINELA}
        self.fake.respuestas[("POST", f"{_RUTA}/flujo-1")] = siguiente
        token = (await self.vista())["confirmation_token"]
        texto = await self.t["ha_continue_repair_fix"](
            "banco_flujos", "aviso_reparable", "flujo-1", self.datos, token)
        self.assertNotIn(_CENTINELA, texto)


# ── T037: ha_abort_repair_fix ─────────────────────────────────────────────────


class TestAbortRepairFix(_Base):
    async def test_aborta(self) -> None:
        r = await self.llamar("ha_abort_repair_fix", "flujo-1")
        self.assertEqual(r, {"result": "ok"})
        self.assertEqual(self.fake.rest, [("DELETE", f"{_RUTA}/flujo-1", None)])

    async def test_404(self) -> None:
        self.fake.respuestas[("DELETE", f"{_RUTA}/flujo-1")] = HAConnectionError(
            "Invalid flow specified", status=404)
        r = await self.llamar("ha_abort_repair_fix", "flujo-1")
        self.assertEqual(r["error"], "not_found")

    async def test_flow_id_invalido(self) -> None:
        r = await self.llamar("ha_abort_repair_fix", "../x")
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "flow_id"))
        self.assertEqual(self.fake.rest, [])


if __name__ == "__main__":
    unittest.main()
