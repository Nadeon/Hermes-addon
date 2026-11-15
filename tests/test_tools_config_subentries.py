"""Tests de las tools de `config_subentries` (spec 016, tramo B; T018-T022b).

Home Assistant se simula con un `ws_send` y un `_request_json` falsos que
registran cada llamada. Datos ficticios (`banco_flujos`, `entrada-1`,
`sub-1`, `flujo-r1`) y centinelas de secreto que no deben salir en ninguna
respuesta, vista previa, log ni fichero de token.

Reconfigure (decisión del supervisor): cada paso pide token, la tool general
rechaza los `flow_id` que abrió Hermes y ninguna otra vía abre un reconfigure
(T022a, T022b).

Controles negativos comprobados (T029; rojos en este fichero salvo f):
(a) abrir el flujo de subentry sin comprobar el tipo → 1
    (`test_tipo_no_admitido_sin_post`);
(b) no abortar un `external`/`progress` → 2 (`TestSubentryFlow`);
(c) emitir el token sin leer los registros → 3, omitir los dispositivos → 1,
    borrar en la vista previa → 7 (`TestDeleteSubentry`);
(d) atar el token de borrar sin `subentry_id` → 1
    (`test_token_de_otra_subentry`);
(e) renombrar sin comprobar la entrada → 2 (`TestUpdateSubentry`);
(f) `config_entries/subentries/delete` en `deny` → 1 en
    `tests/test_tools_generic_commands.py`; sacar `ha_start_subentry_flow` de
    `_NON_IDEMPOTENT_EXACT` → 1 en `tests/test_tools_registration.py`;
(g) no registrar el reconfigure → 17; que la tool general no mire el
    registro → 2; `POST` en la vista previa del reconfigure → 10; token sin
    `step_id` → 1 (`test_paso_cambiado_entre_vista_y_confirmacion`); no mirar
    el selector de contraseña → 4; olvidar el caducado sin abortarlo → 3
    (`TestCaducidad`); `ha_start_config_entry_flow` con `entry_id` → 1
    (`TestOtrasViasNoAbrenReconfigure`); aceptar `***REDACTED***` en
    `user_input` → 1.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from aiohttp import ClientSession
from structlog.testing import capture_logs

import hermes.security as security
import hermes.tools.config_entry_flows as flujos_112
import hermes.tools.config_subentries as mod
from hermes.ha import HAConnectionError
from hermes.tools import _reconfigure
from tests._ha_fixture import make_ready_client

_CENTINELA = "centinela-016"
_CENTINELA_PIN = "centinela-pin-016"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJiYW5jbyJ9.c2lnbmF0dXJhLWRlLXBydWViYQ"

_RUTA_SUB = "/config/config_entries/subentries/flow"
_RUTA_FLUJOS = "/config/config_entries/flow"


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _entrada(**kw: Any) -> dict[str, Any]:
    e = {
        "entry_id": "entrada-1", "domain": "banco_flujos", "title": "Banco",
        "source": "user", "state": "loaded", "supports_reconfigure": True,
        "supported_subentry_types": {"elemento": {"supports_reconfigure": True},
                                     "fijo": {"supports_reconfigure": False}},
        "num_subentries": 1,
    }
    e.update(kw)
    return e


def _paso(step_id: str = "reconfigure", flow_id: str = "flujo-r1", **kw: Any) -> dict[str, Any]:
    p = {
        "type": "form", "flow_id": flow_id, "handler": "banco_flujos",
        "step_id": step_id, "errors": None, "description_placeholders": None,
        "data_schema": [
            {"name": "host", "type": "string", "required": True,
             "description": {"suggested_value": "192.0.2.10"}},
            # Contraseña con nombre inocente: solo el selector la delata.
            {"name": "clave_acceso", "required": True,
             "selector": {"text": {"type": "password"}},
             "description": {"suggested_value": _CENTINELA_PIN}},
            {"name": "password", "type": "string", "default": _CENTINELA},
        ],
    }
    p.update(kw)
    return p


class _FakeHA:
    def __init__(self) -> None:
        self.ws: list[dict[str, Any]] = []
        self.rest: list[tuple[str, str, Any]] = []
        self.entry: dict[str, Any] | None = _entrada()
        self.subs: Any = [{"subentry_id": "sub-1", "subentry_type": "elemento",
                           "title": "Elemento 1", "unique_id": None},
                          {"subentry_id": "sub-2", "subentry_type": "fijo",
                           "title": "Fijo", "unique_id": "u-2"}]
        self.entities: Any = [
            {"entity_id": "sensor.elemento_1", "name": None, "original_name": "Elemento 1",
             "config_entry_id": "entrada-1", "config_subentry_id": "sub-1"},
            {"entity_id": "sensor.otro", "name": "Otro",
             "config_entry_id": "entrada-1", "config_subentry_id": "sub-2"},
        ]
        self.devices: Any = [
            {"id": "disp-1", "name": "Elemento 1", "name_by_user": None,
             "config_entry_id": "entrada-1", "config_subentry_id": "sub-1"},
            # Forma de compatibilidad (config_entries_subentries).
            {"id": "disp-2", "name": "Compat", "name_by_user": None,
             "config_entries_subentries": {"entrada-1": ["sub-1"]}},
            {"id": "disp-3", "name": "Ajeno", "config_entry_id": "entrada-1",
             "config_subentry_id": "sub-2"},
        ]
        self.errores_ws: dict[str, HAConnectionError] = {}
        # Respuestas REST por (método, ruta): valor o excepción.
        self.respuestas: dict[tuple[str, str], Any] = {}

    async def ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.ws.append(payload)
        tipo = payload["type"]
        if tipo in self.errores_ws:
            raise self.errores_ws[tipo]
        if tipo == "config_entries/get_single":
            if self.entry is None:
                raise HAConnectionError("Config entry not found", code="not_found")
            return {"config_entry": dict(self.entry)}
        if tipo == "config_entries/subentries/list":
            return self.subs
        if tipo == "config_entries/subentries/update":
            return None
        if tipo == "config_entries/subentries/delete":
            return None
        if tipo == "config/entity_registry/list":
            return self.entities
        if tipo == "config/device_registry/list":
            return self.devices
        if tipo == "config_entries/flow/progress":
            # Tramo C: la tool general mira aquí si el flujo es un `reauth`.
            return []
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

    def tipos(self) -> list[str]:
        return [p["type"] for p in self.ws]

    def metodos(self, metodo: str) -> list[tuple[str, str, Any]]:
        return [r for r in self.rest if r[0] == metodo]


class _Base(unittest.IsolatedAsyncioTestCase):
    max_bytes = 131_072

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
        mod.register(self.mcp, client, response_max_bytes=self.max_bytes)
        # Las de la 1.1.2, en el mismo servidor: el rechazo de los
        # reconfigure se prueba sobre la tool real.
        flujos_112.register(self.mcp, client)
        self.t = self.mcp.tools

    async def asyncTearDown(self) -> None:
        _reconfigure.limpiar()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()
        await self.session.close()

    async def llamar(self, tool: str, *args: Any, **kwargs: Any) -> Any:
        return json.loads(await self.t[tool](*args, **kwargs))

    def ficheros_de_tokens(self) -> str:
        return "".join(p.read_text(encoding="utf-8")
                       for p in Path(self.temp_dir.name).glob("*"))


class TestRegistro(_Base):
    def test_registra_las_ocho(self) -> None:
        nuevas = {n for n in self.t if n in {
            "ha_list_config_subentries", "ha_start_subentry_flow",
            "ha_continue_subentry_flow", "ha_abort_subentry_flow",
            "ha_update_subentry", "ha_delete_subentry",
            "ha_start_reconfigure_flow", "ha_continue_reconfigure_flow"}}
        self.assertEqual(len(nuevas), 8)


# ── T018: ha_list_config_subentries ───────────────────────────────────────────


class TestListSubentries(_Base):
    async def test_forma_y_lecturas(self) -> None:
        r = await self.llamar("ha_list_config_subentries", "entrada-1")
        self.assertEqual(self.fake.tipos(),
                         ["config_entries/get_single", "config_entries/subentries/list"])
        self.assertEqual(r["entry_id"], "entrada-1")
        self.assertEqual(r["domain"], "banco_flujos")
        self.assertEqual(r["supported_subentry_types"]["elemento"],
                         {"supports_reconfigure": True})
        self.assertEqual((r["count"], r["truncated"]), (2, False))
        self.assertEqual(r["items"][0], {"subentry_id": "sub-1", "subentry_type": "elemento",
                                         "title": "Elemento 1", "unique_id": None})

    async def test_entrada_inexistente_sin_pedir_la_lista(self) -> None:
        self.fake.entry = None
        r = await self.llamar("ha_list_config_subentries", "entrada-1")
        self.assertEqual(r["error"], "not_found")
        self.assertEqual(self.fake.tipos(), ["config_entries/get_single"])

    async def test_respuesta_que_no_es_lista(self) -> None:
        self.fake.subs = {"no": "lista"}
        r = await self.llamar("ha_list_config_subentries", "entrada-1")
        self.assertEqual(r, {"error": "unexpected_response"})

    async def test_titulo_con_centinela_tapado(self) -> None:
        self.fake.subs = [{"subentry_id": "sub-1", "subentry_type": "elemento",
                           "title": f"token: {_CENTINELA} {_JWT}", "unique_id": None}]
        texto = await self.t["ha_list_config_subentries"]("entrada-1")
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn(_JWT, texto)

    async def test_entry_id_invalido(self) -> None:
        r = await self.llamar("ha_list_config_subentries", "../x")
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "entry_id"))
        self.assertEqual(self.fake.ws, [])


class TestListSubentriesRecorte(_Base):
    max_bytes = 1500

    async def test_sobre_recortado(self) -> None:
        self.fake.subs = [{"subentry_id": f"sub-{i:03d}", "subentry_type": "elemento",
                           "title": f"Elemento {i}", "unique_id": None} for i in range(60)]
        texto = await self.t["ha_list_config_subentries"]("entrada-1")
        r = json.loads(texto)
        self.assertTrue(r["truncated"])
        self.assertEqual(r["count"], 60)
        self.assertEqual(r["returned"], len(r["items"]))
        self.assertLessEqual(len(texto.encode()), self.max_bytes)


# ── T019: flujos de subentry ──────────────────────────────────────────────────


class TestSubentryFlow(_Base):
    async def test_abre_con_el_handler(self) -> None:
        self.fake.respuestas[("POST", _RUTA_SUB)] = _paso("user", flow_id="sf-1")
        r = await self.llamar("ha_start_subentry_flow", "entrada-1", "elemento")
        self.assertEqual(self.fake.metodos("POST"),
                         [("POST", _RUTA_SUB, {"handler": ["entrada-1", "elemento"]})])
        self.assertEqual(r["flow_id"], "sf-1")

    async def test_reconfigura_con_subentry_id(self) -> None:
        self.fake.respuestas[("POST", _RUTA_SUB)] = _paso("reconfigure", flow_id="sf-1")
        await self.llamar("ha_start_subentry_flow", "entrada-1", "elemento", "sub-1")
        self.assertEqual(self.fake.metodos("POST")[0][2],
                         {"handler": ["entrada-1", "elemento"], "subentry_id": "sub-1"})

    async def test_tipo_no_admitido_sin_post(self) -> None:
        r = await self.llamar("ha_start_subentry_flow", "entrada-1", "otro")
        self.assertEqual(r["error"], "subentry_type_not_supported")
        self.assertEqual(r["supported"], ["elemento", "fijo"])
        self.assertEqual(self.fake.rest, [])

    async def test_entrada_o_subentry_inexistente_sin_post(self) -> None:
        r = await self.llamar("ha_start_subentry_flow", "entrada-1", "elemento", "sub-9")
        self.assertEqual(r["error"], "not_found")
        self.fake.entry = None
        r = await self.llamar("ha_start_subentry_flow", "entrada-1", "elemento")
        self.assertEqual(r["error"], "not_found")
        self.assertEqual(self.fake.rest, [])

    async def test_subentry_de_otro_tipo(self) -> None:
        r = await self.llamar("ha_start_subentry_flow", "entrada-1", "elemento", "sub-2")
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "subentry_id"))
        self.assertEqual(self.fake.rest, [])

    async def test_tipo_sin_reconfigure(self) -> None:
        r = await self.llamar("ha_start_subentry_flow", "entrada-1", "fijo", "sub-2")
        self.assertEqual(r["error"], "reconfigure_not_supported")
        self.assertEqual(self.fake.rest, [])

    async def test_external_se_aborta(self) -> None:
        self.fake.respuestas[("POST", _RUTA_SUB)] = {"type": "external", "flow_id": "sf-1"}
        r = await self.llamar("ha_start_subentry_flow", "entrada-1", "elemento")
        self.assertEqual(r["error"], "non_automatable")
        self.assertIn(("DELETE", f"{_RUTA_SUB}/sf-1", None), self.fake.rest)

    async def test_progress_al_continuar_se_aborta(self) -> None:
        self.fake.respuestas[("POST", f"{_RUTA_SUB}/sf-1")] = {"type": "progress", "flow_id": "sf-1"}
        r = await self.llamar("ha_continue_subentry_flow", "sf-1", {"nombre": "x"})
        self.assertEqual(r["error"], "non_automatable")
        self.assertIn(("DELETE", f"{_RUTA_SUB}/sf-1", None), self.fake.rest)

    async def test_continue_y_create_entry(self) -> None:
        self.fake.respuestas[("POST", f"{_RUTA_SUB}/sf-1")] = {
            "type": "create_entry", "flow_id": "sf-1", "title": "Elemento 2",
            "result": "ok-de-ha"}
        r = await self.llamar("ha_continue_subentry_flow", "sf-1", {"nombre": "Elemento 2"})
        self.assertEqual(self.fake.metodos("POST"),
                         [("POST", f"{_RUTA_SUB}/sf-1", {"nombre": "Elemento 2"})])
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["result"], "ok-de-ha")  # no se pisa lo de HA

    async def test_abort(self) -> None:
        r = await self.llamar("ha_abort_subentry_flow", "sf-1")
        self.assertEqual(r, {"result": "ok"})
        self.assertEqual(self.fake.rest, [("DELETE", f"{_RUTA_SUB}/sf-1", None)])

    async def test_abort_404(self) -> None:
        self.fake.respuestas[("DELETE", f"{_RUTA_SUB}/sf-9")] = HAConnectionError("x", status=404)
        r = await self.llamar("ha_abort_subentry_flow", "sf-9")
        self.assertEqual(r["error"], "not_found")

    async def test_flow_id_invalido_sin_peticion(self) -> None:
        for malo in ("a/b", "..", "../x"):
            r = await self.llamar("ha_continue_subentry_flow", malo, {})
            self.assertEqual(r["error"], "invalid_argument")
            r = await self.llamar("ha_abort_subentry_flow", malo)
            self.assertEqual(r["error"], "invalid_argument")
        self.assertEqual(self.fake.rest, [])

    async def test_user_input_fuera_del_log(self) -> None:
        self.fake.respuestas[("POST", f"{_RUTA_SUB}/sf-1")] = _paso("user", flow_id="sf-1")
        with capture_logs() as logs:
            texto = await self.t["ha_continue_subentry_flow"](
                "sf-1", {"password": _CENTINELA, "nombre": "x"})
        self.assertNotIn(_CENTINELA, json.dumps(logs, default=str))
        # Y el valor sugerido de los campos secretos sale tapado.
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn(_CENTINELA_PIN, texto)


# ── T020: ha_update_subentry ──────────────────────────────────────────────────


class TestUpdateSubentry(_Base):
    async def test_camino_feliz_sin_token(self) -> None:
        r = await self.llamar("ha_update_subentry", "entrada-1", "sub-1", "Nuevo")
        self.assertEqual(r, {"result": "ok", "subentry_id": "sub-1", "title": "Nuevo"})
        updates = [p for p in self.fake.ws if p["type"] == "config_entries/subentries/update"]
        self.assertEqual(updates, [{"type": "config_entries/subentries/update",
                                    "entry_id": "entrada-1", "subentry_id": "sub-1",
                                    "title": "Nuevo"}])

    async def test_not_found_sin_update(self) -> None:
        r = await self.llamar("ha_update_subentry", "entrada-1", "sub-9", "Nuevo")
        self.assertEqual(r["error"], "not_found")
        self.fake.entry = None
        r = await self.llamar("ha_update_subentry", "entrada-1", "sub-1", "Nuevo")
        self.assertEqual(r["error"], "not_found")
        self.assertNotIn("config_entries/subentries/update", self.fake.tipos())

    async def test_mismo_titulo(self) -> None:
        r = await self.llamar("ha_update_subentry", "entrada-1", "sub-1", "Elemento 1")
        self.assertEqual(r, {"result": "unchanged"})
        self.assertNotIn("config_entries/subentries/update", self.fake.tipos())

    async def test_titulos_invalidos(self) -> None:
        for malo in ("", "  ", "x" * 256):
            r = await self.llamar("ha_update_subentry", "entrada-1", "sub-1", malo)
            self.assertEqual((r["error"], r["field"]), ("invalid_argument", "title"))
        self.assertEqual(self.fake.ws, [])


# ── T021: ha_delete_subentry ──────────────────────────────────────────────────


class TestDeleteSubentry(_Base):
    async def _vista(self) -> dict[str, Any]:
        r = await self.llamar("ha_delete_subentry", "entrada-1", "sub-1")
        self.assertIn("confirmation_token", r)
        self.assertNotIn("config_entries/subentries/delete", self.fake.tipos())
        return r

    async def test_vista_previa(self) -> None:
        p = (await self._vista())["preview"]
        self.assertEqual(p["entry"], {"entry_id": "entrada-1", "domain": "banco_flujos",
                                      "title": "Banco"})
        self.assertEqual(p["subentry"], {"subentry_id": "sub-1", "subentry_type": "elemento",
                                         "title": "Elemento 1"})
        self.assertEqual(p["entities"], {"count": 1, "truncated": False, "items": [
            {"entity_id": "sensor.elemento_1", "name": "Elemento 1"}]})
        # Las dos formas de dispositivo de research R-4; el de otra subentry no.
        self.assertEqual([d["id"] for d in p["devices"]["items"]], ["disp-1", "disp-2"])
        self.assertEqual(p["devices"]["count"], 2)
        self.assertIn("Not reversible", p["effect"])

    async def test_sin_entidades_ni_dispositivos(self) -> None:
        self.fake.entities, self.fake.devices = [], []
        p = (await self._vista())["preview"]
        self.assertEqual(p["entities"], {"count": 0, "items": [], "truncated": False})
        self.assertEqual(p["devices"], {"count": 0, "items": [], "truncated": False})

    async def test_recorte_a_50(self) -> None:
        self.fake.entities = [{"entity_id": f"sensor.e{i:03d}", "name": "e",
                               "config_entry_id": "entrada-1", "config_subentry_id": "sub-1"}
                              for i in range(70)]
        p = (await self._vista())["preview"]
        self.assertEqual((p["entities"]["count"], len(p["entities"]["items"]),
                          p["entities"]["truncated"]), (70, 50, True))

    async def test_inexistentes_sin_token(self) -> None:
        r = await self.llamar("ha_delete_subentry", "entrada-1", "sub-9")
        self.assertEqual(r["error"], "not_found")
        self.fake.entry = None
        r = await self.llamar("ha_delete_subentry", "entrada-1", "sub-1")
        self.assertEqual(r["error"], "not_found")
        self.assertEqual(self.ficheros_de_tokens(), "")

    async def test_lectura_de_registros_que_falla(self) -> None:
        for comando in ("config/entity_registry/list", "config/device_registry/list"):
            self.fake.errores_ws = {comando: HAConnectionError("caído")}
            r = await self.llamar("ha_delete_subentry", "entrada-1", "sub-1")
            self.assertEqual(r["error"], "preview_unavailable")
        self.assertEqual(self.ficheros_de_tokens(), "")

    async def test_confirmacion(self) -> None:
        token = (await self._vista())["confirmation_token"]
        r = await self.llamar("ha_delete_subentry", "entrada-1", "sub-1", token)
        self.assertEqual(r, {"result": "ok"})
        borrados = [p for p in self.fake.ws if p["type"] == "config_entries/subentries/delete"]
        self.assertEqual(borrados, [{"type": "config_entries/subentries/delete",
                                     "entry_id": "entrada-1", "subentry_id": "sub-1"}])

    async def test_token_de_otra_subentry(self) -> None:
        token = (await self._vista())["confirmation_token"]
        r = await self.llamar("ha_delete_subentry", "entrada-1", "sub-2", token)
        self.assertIn("error", r)
        self.assertNotIn("config_entries/subentries/delete", self.fake.tipos())

    async def test_token_reutilizado(self) -> None:
        token = (await self._vista())["confirmation_token"]
        await self.llamar("ha_delete_subentry", "entrada-1", "sub-1", token)
        r = await self.llamar("ha_delete_subentry", "entrada-1", "sub-1", token)
        self.assertIn("error", r)
        self.assertEqual(self.fake.tipos().count("config_entries/subentries/delete"), 1)

    async def test_not_found_al_confirmar(self) -> None:
        token = (await self._vista())["confirmation_token"]
        self.fake.errores_ws = {"config_entries/subentries/delete":
                                HAConnectionError("no", code="not_found")}
        r = await self.llamar("ha_delete_subentry", "entrada-1", "sub-1", token)
        self.assertEqual(r["error"], "not_found")
        estado = json.loads(self.ficheros_de_tokens())
        self.assertEqual(estado["state"], "failed")

    async def test_centinela_en_nombre_de_entidad(self) -> None:
        self.fake.entities[0]["name"] = f"password: {_CENTINELA}"
        with capture_logs() as logs:
            texto = await self.t["ha_delete_subentry"]("entrada-1", "sub-1")
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn(_CENTINELA, self.ficheros_de_tokens())
        self.assertNotIn(_CENTINELA, json.dumps(logs, default=str))


# ── T022: ha_start_reconfigure_flow ───────────────────────────────────────────


class TestStartReconfigure(_Base):
    async def test_camino_feliz_y_registro(self) -> None:
        self.fake.respuestas[("POST", _RUTA_FLUJOS)] = _paso()
        r = await self.llamar("ha_start_reconfigure_flow", "entrada-1")
        self.assertEqual(self.fake.metodos("POST"), [
            ("POST", _RUTA_FLUJOS, {"handler": "banco_flujos", "entry_id": "entrada-1"})])
        self.assertIn("ha_continue_reconfigure_flow", r["continue_with"])
        self.assertEqual(r["entry"], {"entry_id": "entrada-1", "domain": "banco_flujos",
                                      "title": "Banco"})
        self.assertIsNotNone(_reconfigure.buscar("flujo-r1"))

    async def test_secretos_sugeridos_tapados(self) -> None:
        self.fake.respuestas[("POST", _RUTA_FLUJOS)] = _paso()
        texto = await self.t["ha_start_reconfigure_flow"]("entrada-1")
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn(_CENTINELA_PIN, texto)
        # Lo que no es secreto sigue a la vista.
        self.assertIn("192.0.2.10", texto)

    async def test_inexistente(self) -> None:
        self.fake.entry = None
        r = await self.llamar("ha_start_reconfigure_flow", "entrada-1")
        self.assertEqual(r["error"], "not_found")
        self.assertEqual(self.fake.rest, [])

    async def test_no_admitido_sin_post(self) -> None:
        self.fake.entry = _entrada(supports_reconfigure=False)
        r = await self.llamar("ha_start_reconfigure_flow", "entrada-1")
        self.assertEqual(r["error"], "reconfigure_not_supported")
        self.assertEqual(self.fake.rest, [])

    async def test_external_se_aborta_sin_registro(self) -> None:
        self.fake.respuestas[("POST", _RUTA_FLUJOS)] = {"type": "external", "flow_id": "flujo-r1"}
        r = await self.llamar("ha_start_reconfigure_flow", "entrada-1")
        self.assertEqual(r["error"], "non_automatable")
        self.assertIn(("DELETE", f"{_RUTA_FLUJOS}/flujo-r1", None), self.fake.rest)
        self.assertIsNone(_reconfigure.buscar("flujo-r1"))

    async def test_abort_al_abrir_sin_registro(self) -> None:
        self.fake.respuestas[("POST", _RUTA_FLUJOS)] = {
            "type": "abort", "flow_id": "flujo-r1", "reason": "already_in_progress"}
        r = await self.llamar("ha_start_reconfigure_flow", "entrada-1")
        self.assertEqual(r["type"], "abort")
        self.assertIsNone(_reconfigure.buscar("flujo-r1"))


# ── T022a: ha_continue_reconfigure_flow y el registro ─────────────────────────


class _ConReconfigure(_Base):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.fake.respuestas[("POST", _RUTA_FLUJOS)] = _paso()
        await self.llamar("ha_start_reconfigure_flow", "entrada-1")
        self.fake.respuestas[("GET", f"{_RUTA_FLUJOS}/flujo-r1")] = _paso()
        self.fake.rest.clear()
        self.datos = {"host": "192.0.2.20", "clave_acceso": _CENTINELA_PIN,
                      "password": _CENTINELA}

    async def vista(self, datos: dict[str, Any] | None = None) -> dict[str, Any]:
        r = await self.llamar("ha_continue_reconfigure_flow", "flujo-r1",
                              self.datos if datos is None else datos)
        self.assertIn("confirmation_token", r, r)
        return r

    def posts(self) -> list[tuple[str, str, Any]]:
        return [x for x in self.fake.metodos("POST") if x[1] == f"{_RUTA_FLUJOS}/flujo-r1"]


class TestContinueReconfigureValidacion(_Base):
    async def test_validacion_sin_peticion(self) -> None:
        r = await self.llamar("ha_continue_reconfigure_flow", "a/b", {})
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "flow_id"))
        r = await self.llamar("ha_continue_reconfigure_flow", "flujo-r1", ["no"])
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "user_input"))
        self.assertEqual(self.fake.rest, [])

    async def test_marcador_de_redaccion_rechazado(self) -> None:
        _reconfigure.registrar("flujo-r1", "entrada-1", "banco_flujos", "Banco")
        for tool in ("ha_continue_reconfigure_flow", "ha_continue_subentry_flow"):
            r = await self.llamar(tool, "flujo-r1",
                                  {"password": security.REDACTED_MARKER, "host": "x"})
            self.assertEqual((r["error"], r["field"]), ("invalid_argument", "user_input"))
        self.assertEqual(self.fake.rest, [])

    async def test_flujo_fuera_del_registro(self) -> None:
        r = await self.llamar("ha_continue_reconfigure_flow", "otro-flujo", {"a": 1})
        self.assertEqual(r["error"], "not_a_reconfigure_flow")
        self.assertEqual(self.fake.rest, [])
        # T047: la pista lleva a abrir otro reconfigure, nunca a la vía
        # general, que lo enviaría sin token. Control negativo comprobado: con
        # la pista anterior («Other config flows continue with
        # ha_continue_config_entry_flow») cae este test.
        self.assertNotIn("ha_continue_config_entry_flow", r["hint"])
        self.assertIn("ha_start_reconfigure_flow", r["hint"])


class TestContinueReconfigureVista(_ConReconfigure):
    async def test_vista_previa_sin_post(self) -> None:
        r = await self.vista()
        p = r["preview"]
        self.assertEqual(self.fake.rest, [("GET", f"{_RUTA_FLUJOS}/flujo-r1", None)])
        self.assertEqual(p["entry"]["domain"], "banco_flujos")
        self.assertEqual(p["step_id"], "reconfigure")
        self.assertEqual(p["user_input"]["host"], "192.0.2.20")
        self.assertEqual(p["user_input"]["clave_acceso"], security.REDACTED_MARKER)
        self.assertEqual(p["user_input"]["password"], security.REDACTED_MARKER)
        self.assertEqual(p["secret_fields"], ["clave_acceso", "password"])
        self.assertEqual(p["unknown_fields"], [])
        self.assertIn("reloads", p["effect"])

    async def test_campos_desconocidos(self) -> None:
        p = (await self.vista({"host": "x", "extra": 1}))["preview"]
        self.assertEqual(p["unknown_fields"], ["extra"])

    async def test_flujo_404(self) -> None:
        self.fake.respuestas[("GET", f"{_RUTA_FLUJOS}/flujo-r1")] = HAConnectionError("x", status=404)
        r = await self.llamar("ha_continue_reconfigure_flow", "flujo-r1", self.datos)
        self.assertEqual(r["error"], "not_found")
        self.assertIsNone(_reconfigure.buscar("flujo-r1"))

    async def test_lectura_que_falla(self) -> None:
        self.fake.respuestas[("GET", f"{_RUTA_FLUJOS}/flujo-r1")] = HAConnectionError("caído", status=500)
        r = await self.llamar("ha_continue_reconfigure_flow", "flujo-r1", self.datos)
        self.assertEqual(r["error"], "preview_unavailable")
        self.assertEqual(self.ficheros_de_tokens(), "")
        self.assertEqual(self.posts(), [])

    async def test_centinelas_fuera_de_vista_log_y_tokens(self) -> None:
        with capture_logs() as logs:
            texto = await self.t["ha_continue_reconfigure_flow"]("flujo-r1", self.datos)
            token = json.loads(texto)["confirmation_token"]
            self.fake.respuestas[("POST", f"{_RUTA_FLUJOS}/flujo-r1")] = _paso("segundo")
            salida = await self.t["ha_continue_reconfigure_flow"]("flujo-r1", self.datos, token)
        for s in (_CENTINELA, _CENTINELA_PIN):
            self.assertNotIn(s, texto)
            self.assertNotIn(s, salida)
            self.assertNotIn(s, json.dumps(logs, default=str))
            self.assertNotIn(s, self.ficheros_de_tokens())


class TestContinueReconfigureConfirmacion(_ConReconfigure):
    async def test_un_solo_post_y_fin(self) -> None:
        token = (await self.vista())["confirmation_token"]
        self.fake.respuestas[("POST", f"{_RUTA_FLUJOS}/flujo-r1")] = {
            "type": "abort", "flow_id": "flujo-r1", "reason": "reconfigure_successful"}
        r = await self.llamar("ha_continue_reconfigure_flow", "flujo-r1", self.datos, token)
        self.assertEqual(self.posts(), [("POST", f"{_RUTA_FLUJOS}/flujo-r1", self.datos)])
        self.assertEqual(r["status"], "ok")
        self.assertIsNone(_reconfigure.buscar("flujo-r1"))

    async def test_paso_siguiente_pide_otro_token(self) -> None:
        token = (await self.vista())["confirmation_token"]
        self.fake.respuestas[("POST", f"{_RUTA_FLUJOS}/flujo-r1")] = _paso("segundo")
        r = await self.llamar("ha_continue_reconfigure_flow", "flujo-r1", self.datos, token)
        self.assertIn("ha_continue_reconfigure_flow", r["continue_with"])
        self.assertIsNotNone(_reconfigure.buscar("flujo-r1"))
        # El siguiente envío, sin token, vuelve a ser una vista previa.
        self.fake.respuestas[("GET", f"{_RUTA_FLUJOS}/flujo-r1")] = _paso("segundo")
        r = await self.llamar("ha_continue_reconfigure_flow", "flujo-r1", {"host": "y"})
        self.assertIn("confirmation_token", r)
        self.assertEqual(len(self.posts()), 1)

    async def test_http_400_redactado(self) -> None:
        token = (await self.vista())["confirmation_token"]
        self.fake.respuestas[("POST", f"{_RUTA_FLUJOS}/flujo-r1")] = HAConnectionError(
            f'failed 400: {{"errors": {{"password": "{_JWT}"}}}}', status=400)
        r = await self.llamar("ha_continue_reconfigure_flow", "flujo-r1", self.datos, token)
        self.assertNotIn(_JWT, json.dumps(r))
        self.assertEqual(json.loads(self.ficheros_de_tokens())["state"], "failed")

    async def test_token_con_otros_datos(self) -> None:
        token = (await self.vista())["confirmation_token"]
        otros = dict(self.datos, password="otra")
        r = await self.llamar("ha_continue_reconfigure_flow", "flujo-r1", otros, token)
        self.assertIn("error", r)
        self.assertEqual(self.posts(), [])

    async def test_token_de_otro_flujo(self) -> None:
        token = (await self.vista())["confirmation_token"]
        _reconfigure.registrar("flujo-r2", "entrada-1", "banco_flujos", "Banco")
        self.fake.respuestas[("GET", f"{_RUTA_FLUJOS}/flujo-r2")] = _paso(flow_id="flujo-r2")
        r = await self.llamar("ha_continue_reconfigure_flow", "flujo-r2", self.datos, token)
        self.assertIn("error", r)
        self.assertEqual(self.fake.metodos("POST"), [])

    async def test_paso_cambiado_entre_vista_y_confirmacion(self) -> None:
        token = (await self.vista())["confirmation_token"]
        self.fake.respuestas[("GET", f"{_RUTA_FLUJOS}/flujo-r1")] = _paso("otro_paso")
        r = await self.llamar("ha_continue_reconfigure_flow", "flujo-r1", self.datos, token)
        self.assertIn("error", r)
        self.assertEqual(self.posts(), [])

    async def test_token_reutilizado(self) -> None:
        token = (await self.vista())["confirmation_token"]
        self.fake.respuestas[("POST", f"{_RUTA_FLUJOS}/flujo-r1")] = _paso()
        await self.llamar("ha_continue_reconfigure_flow", "flujo-r1", self.datos, token)
        r = await self.llamar("ha_continue_reconfigure_flow", "flujo-r1", self.datos, token)
        self.assertIn("error", r)
        self.assertEqual(len(self.posts()), 1)


class TestToolGeneralRechazaReconfigure(_ConReconfigure):
    """T022a(f): la tool de la 1.1.2 no continúa un reconfigure de Hermes."""

    async def test_rechazado_sin_post(self) -> None:
        r = await self.llamar("ha_continue_config_entry_flow", "flujo-r1", self.datos)
        self.assertEqual((r["error"], r["tool"]),
                         ("use_dedicated_tool", "ha_continue_reconfigure_flow"))
        self.assertEqual(self.fake.rest, [])

    async def test_otro_flujo_como_en_la_1_1_2(self) -> None:
        self.fake.respuestas[("POST", f"{_RUTA_FLUJOS}/flujo-u1")] = {
            "type": "create_entry", "flow_id": "flujo-u1", "result": {"entry_id": "e2"}}
        r = await self.llamar("ha_continue_config_entry_flow", "flujo-u1", {"a": 1})
        self.assertEqual((r["status"], r["result"]), ("ok", {"entry_id": "e2"}))
        self.assertEqual(self.fake.rest, [("POST", f"{_RUTA_FLUJOS}/flujo-u1", {"a": 1})])

    async def test_abortar_lo_saca_del_registro(self) -> None:
        r = await self.llamar("ha_abort_config_entry_flow", "flujo-r1")
        self.assertEqual(r, {"result": "ok"})
        self.assertIsNone(_reconfigure.buscar("flujo-r1"))


class TestCaducidad(_ConReconfigure):
    """T022a(g): un caducado se aborta en HA y, mientras no, sigue rechazado."""

    def adelantar(self) -> Any:
        ahora = _reconfigure._ahora() + _reconfigure.CADUCIDAD_S + 1
        return patch.object(_reconfigure, "_ahora", return_value=ahora)

    async def test_dedicada_dice_expired_y_aborta(self) -> None:
        with self.adelantar():
            r = await self.llamar("ha_continue_reconfigure_flow", "flujo-r1", self.datos)
        self.assertEqual(r["error"], "expired")
        self.assertIn(("DELETE", f"{_RUTA_FLUJOS}/flujo-r1", None), self.fake.rest)
        self.assertIsNone(_reconfigure.buscar("flujo-r1"))
        self.assertEqual(self.posts(), [])

    async def test_abort_que_falla_lo_deja_rechazado(self) -> None:
        self.fake.respuestas[("DELETE", f"{_RUTA_FLUJOS}/flujo-r1")] = HAConnectionError(
            "caído", status=500)
        with self.adelantar():
            await self.llamar("ha_continue_reconfigure_flow", "flujo-r1", self.datos)
            r = await self.llamar("ha_continue_config_entry_flow", "flujo-r1", self.datos)
        self.assertEqual(r["error"], "use_dedicated_tool")
        self.assertIsNotNone(_reconfigure.buscar("flujo-r1"))
        self.assertEqual(self.posts(), [])

    async def test_abort_404_lo_olvida(self) -> None:
        self.fake.respuestas[("DELETE", f"{_RUTA_FLUJOS}/flujo-r1")] = HAConnectionError(
            "x", status=404)
        with self.adelantar():
            await self.llamar("ha_continue_reconfigure_flow", "flujo-r1", self.datos)
        self.assertIsNone(_reconfigure.buscar("flujo-r1"))

    async def test_abrir_otro_barre_los_caducados(self) -> None:
        self.fake.respuestas[("POST", _RUTA_FLUJOS)] = _paso(flow_id="flujo-r2")
        with self.adelantar():
            await self.llamar("ha_start_reconfigure_flow", "entrada-1")
        self.assertIn(("DELETE", f"{_RUTA_FLUJOS}/flujo-r1", None), self.fake.rest)
        self.assertIsNone(_reconfigure.buscar("flujo-r1"))
        self.assertIsNotNone(_reconfigure.buscar("flujo-r2"))


# ── T022b: ninguna otra vía abre un reconfigure (FR-010c) ─────────────────────


class TestOtrasViasNoAbrenReconfigure(_Base):
    async def test_start_config_entry_flow_solo_manda_handler(self) -> None:
        self.fake.respuestas[("POST", _RUTA_FLUJOS)] = {"type": "form", "flow_id": "u1"}
        for handler in ("banco_flujos", 'banco_flujos", "entry_id": "entrada-1'):
            await self.t["ha_start_config_entry_flow"](handler)
        cuerpos = [c for _, _, c in self.fake.metodos("POST")]
        self.assertEqual([set(c) for c in cuerpos], [{"handler"}, {"handler"}])

    async def test_start_subentry_flow_nunca_va_a_flujos_de_entrada(self) -> None:
        self.fake.respuestas[("POST", _RUTA_SUB)] = {"type": "form", "flow_id": "s1"}
        await self.llamar("ha_start_subentry_flow", "entrada-1", "elemento", "sub-1")
        self.assertEqual({p for _, p, _ in self.fake.rest}, {_RUTA_SUB})


class TestGenericasNoAbrenReconfigure(unittest.IsolatedAsyncioTestCase):
    """Con la tabla real: ningún comando WS abre flujos de configuración, y el
    proxy REST de Core del Supervisor está cerrado."""

    async def asyncSetUp(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from hermes.tools import generic_commands
        self.ha = MagicMock()
        self.ha.wait_ready = AsyncMock(return_value=True)
        self.ha.ws_send = AsyncMock(return_value={})
        self.ha.sv_request = AsyncMock(return_value={})
        self.ha.sv_request_text = AsyncMock(return_value="")
        self.mcp = DummyMCP()
        generic_commands.register(self.mcp, self.ha, response_max_bytes=131_072)
        self.t = self.mcp.tools

    def test_ningun_comando_ws_de_flujos_de_entrada_ejecutable(self) -> None:
        # En Core 2026.11.1 los flujos de configuración se abren solo por
        # REST. Si un día aparece un comando WS de flujos, tiene que llegar
        # revisado: ni `read` ni `confirm` sin pasar por aquí.
        from hermes.command_table import CORE_WS
        ejecutables = sorted(t for t, e in CORE_WS.items()
                             if t.startswith("config_entries/flow")
                             and e.category in ("read", "confirm"))
        self.assertEqual(ejecutables, [])

    async def test_comando_ws_no_clasificado(self) -> None:
        for tipo in ("config_entries/flow/init", "config_entries/flow/configure"):
            r = await self.t["ha_call_ws_command"](tipo, {"handler": "banco_flujos",
                                                          "entry_id": "entrada-1"})
            self.assertEqual(r["error"], "command_not_classified")
            r = await self.t["ha_read_ws_command"](tipo)
            self.assertEqual(r["error"], "command_not_classified")
        self.ha.ws_send.assert_not_awaited()

    async def test_proxy_rest_de_core_cerrado(self) -> None:
        for ruta in ("/core/api/config/config_entries/flow",
                     "/homeassistant/api/config/config_entries/flow",
                     "/core/api/config/config_entries/flow/flujo-r1"):
            r = await self.t["sv_call_api"]("POST", ruta, {"handler": "banco_flujos",
                                                           "entry_id": "entrada-1"})
            self.assertEqual((r["error"], r["rule"]), ("path_not_allowed", "core_proxy"))
            self.assertNotIn("confirmation_token", r)
        r = await self.t["sv_read_api"]("/core/api/config/config_entries/flow/flujo-r1")
        self.assertEqual(r["rule"], "core_proxy")
        self.ha.sv_request.assert_not_awaited()
        self.ha.sv_request_text.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
