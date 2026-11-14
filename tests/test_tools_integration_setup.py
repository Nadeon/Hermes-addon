"""Tests de las tools de `integration_setup` (spec 016, tramo A; T004-T007).

Home Assistant se simula con un `ws_send` y un `_request_json` falsos que
registran cada llamada. Los datos son ficticios: dominios (`hue`,
`banco_flujos`), ids (`flow-1`, `entrada-1`) y secretos centinela que no deben
salir en ninguna respuesta, en el log ni en los ficheros de token.

Controles negativos comprobados (T016; recuentos también en el commit):
(a) quitar la redacción de `title_placeholders` en la lista → cae 1
    (`TestListDiscovered.test_centinela_y_jwt_tapados`);
(b) llamar a `ignore_flow` sin comprobar `unique_id` → cae 1
    (`TestIgnoreDiscovery.test_sin_unique_id_cannot_ignore`);
(c) enviar el `update` en la vista previa → caen 8 de
    `TestUpdateConfigEntryToken` («ningún config_entries/update»); emitir un
    token cuando falla la lectura previa → cae 1 (`test_lectura_previa_que_falla`);
(d) pedir token siempre → caen 5 de `TestUpdateConfigEntrySinToken`; no
    pedirlo al desactivar el sondeo → caen 7 de `TestUpdateConfigEntryToken`;
(e) atar el token sin `title` → cae 1 (`test_token_de_otro_titulo_rechazado`);
(f) devolver lista vacía si la respuesta no es lista → cae 1
    (`TestListDiscovered.test_respuesta_que_no_es_lista`);
(j) la docstring anterior de `ha_list_configured_domains` → cae 1
    (`TestDocstringDeConfiguredDomains.test_ya_no_miente`).
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
import hermes.tools.integration_setup as mod
from hermes.ha import HAConnectionError
from tests._ha_fixture import make_ready_client

_CENTINELA = "centinela-016"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJiYW5jbyJ9.c2lnbmF0dXJhLWRlLXBydWViYQ"


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _flujo(flow_id: str, domain: str, *, source: str = "zeroconf",
           unique_id: str | None = "uid-ficticio", name: str | None = "Hue Bridge",
           step_id: str | None = "confirm", **ctx_extra: Any) -> dict[str, Any]:
    ctx: dict[str, Any] = {"source": source, **ctx_extra}
    if unique_id is not None:
        ctx["unique_id"] = unique_id
    if name is not None:
        ctx["title_placeholders"] = {"name": name}
    flujo: dict[str, Any] = {"flow_id": flow_id, "handler": domain, "context": ctx}
    if step_id is not None:
        flujo["step_id"] = step_id
    return flujo


def _entrada(*, title: str = "Banco", state: str = "loaded",
             polling: bool = False, new_entities: bool = False) -> dict[str, Any]:
    return {
        "entry_id": "entrada-1", "domain": "banco_flujos", "title": title,
        "source": "user", "state": state, "supports_options": False,
        "pref_disable_polling": polling, "pref_disable_new_entities": new_entities,
        "disabled_by": None,
    }


class _FakeHA:
    """Simula los comandos WS y la ruta REST que usan las cuatro tools."""

    def __init__(self) -> None:
        self.ws: list[dict[str, Any]] = []
        self.rest: list[tuple[str, str, Any]] = []
        self.progress: Any = []
        self.progress_error: HAConnectionError | None = None
        self.ignore_error: HAConnectionError | None = None
        self.entry: dict[str, Any] | None = _entrada()
        self.get_single_error: HAConnectionError | None = None
        self.update_error: HAConnectionError | None = None
        self.handlers: Any = ["zeta", "banco_flujos", "hue"]

    async def ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.ws.append(payload)
        tipo = payload["type"]
        if tipo == "config_entries/flow/progress":
            if self.progress_error is not None:
                raise self.progress_error
            return self.progress
        if tipo == "config_entries/ignore_flow":
            if self.ignore_error is not None:
                raise self.ignore_error
            return None
        if tipo == "config_entries/get_single":
            if self.get_single_error is not None:
                raise self.get_single_error
            if self.entry is None:
                raise HAConnectionError("Config entry not found", code="not_found")
            return {"config_entry": dict(self.entry)}
        if tipo == "config_entries/update":
            if self.update_error is not None:
                raise self.update_error
            assert self.entry is not None
            nuevo = dict(self.entry)
            nuevo.update({k: v for k, v in payload.items()
                          if k not in ("type", "entry_id")})
            self.entry = nuevo
            return {"config_entry": dict(nuevo), "require_restart": False}
        raise AssertionError(f"comando inesperado: {payload}")

    async def request_json(self, method: str, path: str, json_body: Any = None,
                           params: dict[str, str] | None = None) -> Any:
        self.rest.append((method, path, params))
        if path == "/config/config_entries/flow_handlers":
            return self.handlers
        raise AssertionError(f"ruta inesperada: {method} {path}")

    def tipos(self) -> list[str]:
        return [p["type"] for p in self.ws]


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
        self.assertEqual(sorted(self.t), [
            "ha_ignore_discovery", "ha_list_config_flow_domains",
            "ha_list_discovered_integrations", "ha_update_config_entry",
        ])


# ── T004: ha_list_discovered_integrations ─────────────────────────────────────


class TestListDiscovered(_Base):
    async def test_campos_y_orden(self) -> None:
        self.fake.progress = [
            _flujo("flow-b", "hue", discovery_key={"domain": "zeroconf"}),
            _flujo("flow-c", "banco_flujos", source="reauth", unique_id=None,
                   name=None, step_id="reauth_confirm", entry_id="entrada-1"),
            _flujo("flow-a", "hue"),
        ]
        r = await self.llamar("ha_list_discovered_integrations")
        self.assertEqual(self.fake.ws, [{"type": "config_entries/flow/progress"}])
        self.assertEqual((r["count"], r["truncated"]), (3, False))
        self.assertEqual([(i["domain"], i["flow_id"]) for i in r["items"]],
                         [("banco_flujos", "flow-c"), ("hue", "flow-a"), ("hue", "flow-b")])
        primero, segundo = r["items"][0], r["items"][1]
        self.assertEqual(primero, {
            "flow_id": "flow-c", "domain": "banco_flujos", "source": "reauth",
            "step_id": "reauth_confirm", "name": None, "title_placeholders": None,
            "ignorable": False,
        })
        self.assertEqual(segundo, {
            "flow_id": "flow-a", "domain": "hue", "source": "zeroconf",
            "step_id": "confirm", "name": "Hue Bridge",
            "title_placeholders": {"name": "Hue Bridge"}, "ignorable": True,
        })
        # Ni el valor de unique_id ni el contexto entero.
        texto = json.dumps(r)
        self.assertNotIn("uid-ficticio", texto)
        self.assertNotIn("discovery_key", texto)
        self.assertNotIn("entrada-1", texto)

    async def test_filtro_domain(self) -> None:
        self.fake.progress = [_flujo("flow-a", "hue"), _flujo("flow-b", "otra")]
        r = await self.llamar("ha_list_discovered_integrations", domain="hue")
        self.assertEqual([i["flow_id"] for i in r["items"]], ["flow-a"])
        self.assertEqual(r["count"], 1)

    async def test_domain_invalido_sin_llamar(self) -> None:
        r = await self.llamar("ha_list_discovered_integrations", domain="Hue X")
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "domain"))
        self.assertEqual(self.fake.ws, [])

    async def test_respuesta_que_no_es_lista(self) -> None:
        self.fake.progress = {"flows": []}
        r = await self.llamar("ha_list_discovered_integrations")
        self.assertEqual(r["error"], "unexpected_response")
        self.assertNotIn("items", r)

    async def test_error_de_ha_redactado(self) -> None:
        self.fake.progress_error = HAConnectionError(f"fallo con token {_JWT}")
        with capture_logs() as logs:
            r = await self.llamar("ha_list_discovered_integrations")
        self.assertIn("error", r)
        self.assertNotIn(_JWT, json.dumps(r))
        self.assertNotIn(_JWT, json.dumps(logs, default=str))

    async def test_centinela_y_jwt_tapados(self) -> None:
        flujo = _flujo("flow-a", "hue", name=f"Puente {_JWT}")
        flujo["context"]["title_placeholders"]["password"] = _CENTINELA
        flujo["context"]["title_placeholders"]["url"] = f"http://u:{_CENTINELA}@192.0.2.10/"
        self.fake.progress = [flujo]
        with capture_logs() as logs:
            r = await self.llamar("ha_list_discovered_integrations")
        texto = json.dumps(r)
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn(_JWT, texto)
        self.assertIn("JWT_REDACTED", r["items"][0]["name"])
        registro = json.dumps(logs, default=str)
        self.assertNotIn(_CENTINELA, registro)
        self.assertNotIn(_JWT, registro)


class TestListDiscoveredRecorte(_Base):
    max_bytes = 2_000

    async def test_sobre_recortado_con_recuentos(self) -> None:
        self.fake.progress = [
            _flujo(f"flow-{n:03d}", "hue", name=f"Puente número {n}") for n in range(60)
        ]
        r = json.loads(await self.t["ha_list_discovered_integrations"]())
        self.assertTrue(r["truncated"])
        self.assertEqual(r["count"], 60)
        self.assertEqual(r["returned"], len(r["items"]))
        self.assertLess(r["returned"], 60)
        self.assertGreater(r["returned"], 0)
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False).encode()), self.max_bytes)


# ── T005: ha_ignore_discovery ────────────────────────────────────────────────


class TestIgnoreDiscovery(_Base):
    async def test_camino_feliz_con_titulo_por_defecto(self) -> None:
        self.fake.progress = [_flujo("flow-a", "hue")]
        r = await self.llamar("ha_ignore_discovery", flow_id="flow-a")
        self.assertEqual(self.fake.tipos(),
                         ["config_entries/flow/progress", "config_entries/ignore_flow"])
        self.assertEqual(self.fake.ws[1], {"type": "config_entries/ignore_flow",
                                           "flow_id": "flow-a", "title": "Hue Bridge"})
        self.assertEqual((r["result"], r["flow_id"], r["domain"], r["title"]),
                         ("ok", "flow-a", "hue", "Hue Bridge"))
        self.assertIn("ha_delete_config_entry", r["undo_hint"])
        self.assertIn("ignore", r["undo_hint"])

    async def test_titulo_pasado(self) -> None:
        self.fake.progress = [_flujo("flow-a", "hue")]
        r = await self.llamar("ha_ignore_discovery", flow_id="flow-a", title="Puente viejo")
        self.assertEqual(self.fake.ws[1]["title"], "Puente viejo")
        self.assertEqual(r["title"], "Puente viejo")

    async def test_sin_nombre_usa_el_dominio(self) -> None:
        self.fake.progress = [_flujo("flow-a", "hue", name=None)]
        await self.llamar("ha_ignore_discovery", flow_id="flow-a")
        self.assertEqual(self.fake.ws[1]["title"], "hue")

    async def test_flujo_que_no_esta(self) -> None:
        self.fake.progress = [_flujo("flow-a", "hue")]
        r = await self.llamar("ha_ignore_discovery", flow_id="flow-z")
        self.assertEqual((r["error"], r["flow_id"]), ("not_found", "flow-z"))
        self.assertEqual(self.fake.tipos(), ["config_entries/flow/progress"])

    async def test_sin_unique_id_cannot_ignore(self) -> None:
        self.fake.progress = [_flujo("flow-a", "banco_flujos", source="reauth", unique_id=None)]
        r = await self.llamar("ha_ignore_discovery", flow_id="flow-a")
        self.assertEqual((r["error"], r["reason"]), ("cannot_ignore", "no_unique_id"))
        self.assertEqual(self.fake.tipos(), ["config_entries/flow/progress"])

    async def test_titulos_invalidos(self) -> None:
        for titulo in ("", "   ", "x" * 256):
            with self.subTest(titulo=titulo[:5]):
                r = await self.llamar("ha_ignore_discovery", flow_id="flow-a", title=titulo)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "title"))
        self.assertEqual(self.fake.ws, [])

    async def test_flow_id_invalidos(self) -> None:
        for flow_id in ("a/b", "..", "../x", ""):
            with self.subTest(flow_id=flow_id):
                r = await self.llamar("ha_ignore_discovery", flow_id=flow_id)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "flow_id"))
        self.assertEqual(self.fake.ws, [])

    async def test_ha_responde_not_found_al_ignorar(self) -> None:
        self.fake.progress = [_flujo("flow-a", "hue")]
        self.fake.ignore_error = HAConnectionError("Config entry not found", code="not_found")
        r = await self.llamar("ha_ignore_discovery", flow_id="flow-a")
        self.assertEqual((r["error"], r["flow_id"]), ("not_found", "flow-a"))

    async def test_error_de_ha_con_centinela_tapado(self) -> None:
        self.fake.progress = [_flujo("flow-a", "hue")]
        self.fake.ignore_error = HAConnectionError(f"fallo password={_CENTINELA}")
        with capture_logs() as logs:
            r = await self.llamar("ha_ignore_discovery", flow_id="flow-a")
        self.assertIn("error", r)
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertNotIn(_CENTINELA, json.dumps(logs, default=str))

    async def test_titulo_por_defecto_redactado_en_la_respuesta(self) -> None:
        self.fake.progress = [_flujo("flow-a", "hue", name=f"Puente {_JWT}")]
        with capture_logs() as logs:
            r = await self.llamar("ha_ignore_discovery", flow_id="flow-a")
        self.assertNotIn(_JWT, json.dumps(r))
        self.assertNotIn(_JWT, json.dumps(logs, default=str))


# ── T006: ha_list_config_flow_domains ────────────────────────────────────────


class TestConfigFlowDomains(_Base):
    async def test_sin_tipo(self) -> None:
        r = await self.llamar("ha_list_config_flow_domains")
        self.assertEqual(self.fake.rest,
                         [("GET", "/config/config_entries/flow_handlers", None)])
        self.assertEqual(r, {"count": 3, "truncated": False, "type": None,
                             "items": ["banco_flujos", "hue", "zeta"]})

    async def test_tipo_helper(self) -> None:
        self.fake.handlers = ["template", "group", "derivative"]
        r = await self.llamar("ha_list_config_flow_domains", type="helper")
        self.assertEqual(self.fake.rest,
                         [("GET", "/config/config_entries/flow_handlers", {"type": "helper"})])
        self.assertEqual((r["type"], r["items"]), ("helper", ["derivative", "group", "template"]))

    async def test_tipo_desconocido_sin_llamar(self) -> None:
        r = await self.llamar("ha_list_config_flow_domains", type="widget")
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "type"))
        self.assertEqual(self.fake.rest, [])

    async def test_respuesta_que_no_es_lista(self) -> None:
        self.fake.handlers = {"domains": []}
        r = await self.llamar("ha_list_config_flow_domains")
        self.assertEqual(r["error"], "unexpected_response")


class TestConfigFlowDomainsRecorte(_Base):
    max_bytes = 600

    async def test_sobre_recortado(self) -> None:
        self.fake.handlers = [f"dominio_{n:03d}" for n in range(200)]
        r = await self.llamar("ha_list_config_flow_domains")
        self.assertTrue(r["truncated"])
        self.assertEqual((r["count"], r["returned"]), (200, len(r["items"])))
        self.assertLessEqual(len(json.dumps(r).encode()), self.max_bytes)


class TestDocstringDeConfiguredDomains(unittest.TestCase):
    """Principio V (research R-2): la docstring de `ha_list_configured_domains`
    afirmaba que no existe una lista de dominios configurables; existe, y la
    expone `ha_list_config_flow_domains`. Control negativo comprobado: con la
    docstring anterior → cae."""

    def test_ya_no_miente(self) -> None:
        import ast
        import inspect

        import hermes.tools.config_entry_flows as flows

        arbol = ast.parse(inspect.getsource(flows))
        funcion = next(n for n in ast.walk(arbol)
                       if isinstance(n, ast.AsyncFunctionDef)
                       and n.name == "ha_list_configured_domains")
        doc = ast.get_docstring(funcion) or ""
        self.assertIn("ha_list_config_flow_domains", doc)
        self.assertNotIn("No existe un comando HA", doc)
        self.assertNotIn("No existe un comando WS/REST", inspect.getsource(flows))


# ── T007: ha_update_config_entry ─────────────────────────────────────────────


class TestUpdateConfigEntryValidacion(_Base):
    async def test_nada_pedido(self) -> None:
        r = await self.llamar("ha_update_config_entry", entry_id="entrada-1")
        self.assertEqual(r["error"], "invalid_argument")
        self.assertEqual(self.fake.ws, [])

    async def test_titulos_invalidos(self) -> None:
        for titulo in ("", "  ", "x" * 256):
            with self.subTest(titulo=titulo[:5]):
                r = await self.llamar("ha_update_config_entry", entry_id="entrada-1",
                                      title=titulo)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "title"))
        self.assertEqual(self.fake.ws, [])

    async def test_booleanos_de_verdad(self) -> None:
        for campo in ("pref_disable_polling", "pref_disable_new_entities"):
            for valor in ("true", 1, 0):
                with self.subTest(campo=campo, valor=valor):
                    r = await self.llamar("ha_update_config_entry", entry_id="entrada-1",
                                          **{campo: valor})
                    self.assertEqual((r["error"], r["field"]), ("invalid_argument", campo))
        self.assertEqual(self.fake.ws, [])

    async def test_entry_id_invalido(self) -> None:
        for entry_id in ("a/b", "..", ""):
            with self.subTest(entry_id=entry_id):
                r = await self.llamar("ha_update_config_entry", entry_id=entry_id,
                                      title="Nuevo")
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "entry_id"))
        self.assertEqual(self.fake.ws, [])


class TestUpdateConfigEntryLectura(_Base):
    async def test_inexistente(self) -> None:
        self.fake.entry = None
        r = await self.llamar("ha_update_config_entry", entry_id="entrada-1", title="Nuevo")
        self.assertEqual((r["error"], r["entry_id"]), ("not_found", "entrada-1"))
        self.assertEqual(self.fake.tipos(), ["config_entries/get_single"])

    async def test_sin_cambios(self) -> None:
        r = await self.llamar("ha_update_config_entry", entry_id="entrada-1",
                              title="Banco", pref_disable_polling=False)
        self.assertEqual(r, {"result": "unchanged"})
        self.assertNotIn("config_entries/update", self.fake.tipos())

    async def test_lectura_previa_que_falla(self) -> None:
        self.fake.get_single_error = HAConnectionError(f"caída password={_CENTINELA}")
        r = await self.llamar("ha_update_config_entry", entry_id="entrada-1",
                              pref_disable_polling=True)
        self.assertEqual(r["error"], "preview_unavailable")
        self.assertNotIn("confirmation_token", r)
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertNotIn("config_entries/update", self.fake.tipos())
        self.assertEqual(self.ficheros_de_tokens(), "")


class TestUpdateConfigEntrySinToken(_Base):
    async def test_solo_titulo(self) -> None:
        r = await self.llamar("ha_update_config_entry", entry_id="entrada-1", title="Nuevo")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.fake.tipos(),
                         ["config_entries/get_single", "config_entries/update"])
        self.assertEqual(self.fake.ws[1], {"type": "config_entries/update",
                                           "entry_id": "entrada-1", "title": "Nuevo"})
        self.assertEqual((r["result"], r["require_restart"], r["reloaded"]), ("ok", False, False))
        self.assertEqual(r["config_entry"]["title"], "Nuevo")

    async def test_solo_lo_que_cambia(self) -> None:
        # El título es el mismo: no viaja.
        await self.llamar("ha_update_config_entry", entry_id="entrada-1",
                          title="Banco", pref_disable_new_entities=False,
                          pref_disable_polling=False)
        self.fake.entry = _entrada(polling=True)
        r = await self.llamar("ha_update_config_entry", entry_id="entrada-1",
                              title="Banco", pref_disable_polling=False)
        self.assertEqual(self.fake.ws[-1], {"type": "config_entries/update",
                                            "entry_id": "entrada-1",
                                            "pref_disable_polling": False})
        self.assertNotIn("confirmation_token", r)

    async def test_reactivar_sondeo_recarga_si_esta_cargada(self) -> None:
        self.fake.entry = _entrada(polling=True)
        r = await self.llamar("ha_update_config_entry", entry_id="entrada-1",
                              pref_disable_polling=False)
        self.assertEqual((r["result"], r["reloaded"]), ("ok", True))
        self.fake.entry = _entrada(polling=True, state="not_loaded")
        r = await self.llamar("ha_update_config_entry", entry_id="entrada-1",
                              pref_disable_polling=False)
        self.assertEqual((r["result"], r["reloaded"]), ("ok", False))

    async def test_reactivar_entidades_nuevas(self) -> None:
        self.fake.entry = _entrada(new_entities=True)
        r = await self.llamar("ha_update_config_entry", entry_id="entrada-1",
                              pref_disable_new_entities=False)
        self.assertEqual(r["result"], "ok")
        self.assertEqual(self.fake.ws[-1]["pref_disable_new_entities"], False)

    async def test_not_found_al_actualizar(self) -> None:
        self.fake.update_error = HAConnectionError("Config entry not found", code="not_found")
        r = await self.llamar("ha_update_config_entry", entry_id="entrada-1", title="Nuevo")
        self.assertEqual((r["error"], r["entry_id"]), ("not_found", "entrada-1"))


class TestUpdateConfigEntryToken(_Base):
    async def _vista(self, **kw: Any) -> dict[str, Any]:
        r = await self.llamar("ha_update_config_entry", entry_id="entrada-1", **kw)
        self.assertIn("confirmation_token", r, r)
        self.assertNotIn("config_entries/update", self.fake.tipos())
        return r

    async def test_desactivar_sondeo_cargada(self) -> None:
        r = await self._vista(pref_disable_polling=True)
        p = r["preview"]
        self.assertEqual((p["entry_id"], p["domain"], p["state"]),
                         ("entrada-1", "banco_flujos", "loaded"))
        self.assertEqual(p["pref_disable_polling"], {"current": False, "new": True})
        self.assertEqual(p["pref_disable_new_entities"], {"current": False, "new": False})
        self.assertEqual(p["title"], {"current": "Banco", "new": "Banco"})
        efectos = " ".join(p["effects"])
        self.assertIn("reloads this integration now", efectos)
        self.assertIn("stops polling", efectos)
        self.assertIn("homeassistant.update_entity", efectos)

    async def test_desactivar_sondeo_no_cargada(self) -> None:
        self.fake.entry = _entrada(state="not_loaded")
        r = await self._vista(pref_disable_polling=True)
        efectos = " ".join(r["preview"]["effects"])
        self.assertIn("does not reload it now", efectos)
        self.assertNotIn("reloads this integration now", efectos)

    async def test_desactivar_entidades_nuevas(self) -> None:
        r = await self._vista(pref_disable_new_entities=True)
        efectos = " ".join(r["preview"]["effects"])
        self.assertIn("created disabled", efectos)
        self.assertNotIn("stops polling", efectos)

    async def test_confirmacion_un_solo_update(self) -> None:
        r = await self._vista(pref_disable_polling=True, title="Nuevo")
        hecho = await self.llamar("ha_update_config_entry", entry_id="entrada-1",
                                  pref_disable_polling=True, title="Nuevo",
                                  confirmation_token=r["confirmation_token"])
        updates = [p for p in self.fake.ws if p["type"] == "config_entries/update"]
        self.assertEqual(updates, [{"type": "config_entries/update", "entry_id": "entrada-1",
                                    "title": "Nuevo", "pref_disable_polling": True}])
        self.assertEqual((hecho["result"], hecho["reloaded"]), ("ok", True))

    async def test_token_de_otro_titulo_rechazado(self) -> None:
        r = await self._vista(pref_disable_polling=True, title="Nuevo")
        otro = await self.llamar("ha_update_config_entry", entry_id="entrada-1",
                                 pref_disable_polling=True, title="Otro",
                                 confirmation_token=r["confirmation_token"])
        self.assertIn("does not match", otro["error"])
        self.assertNotIn("config_entries/update", self.fake.tipos())

    async def test_token_de_otra_preferencia_rechazado(self) -> None:
        r = await self._vista(pref_disable_polling=True)
        otro = await self.llamar("ha_update_config_entry", entry_id="entrada-1",
                                 pref_disable_polling=True, pref_disable_new_entities=True,
                                 confirmation_token=r["confirmation_token"])
        self.assertIn("does not match", otro["error"])
        self.assertNotIn("config_entries/update", self.fake.tipos())

    async def test_token_reutilizado(self) -> None:
        r = await self._vista(pref_disable_polling=True)
        await self.llamar("ha_update_config_entry", entry_id="entrada-1",
                          pref_disable_polling=True,
                          confirmation_token=r["confirmation_token"])
        # La entrada vuelve a como estaba: el token gastado no puede servir.
        self.fake.entry = _entrada()
        otra = await self.llamar("ha_update_config_entry", entry_id="entrada-1",
                                 pref_disable_polling=True,
                                 confirmation_token=r["confirmation_token"])
        self.assertIn("already used", otra["error"])
        self.assertEqual(self.fake.tipos().count("config_entries/update"), 1)

    async def test_centinela_del_titulo_fuera_de_tokens_y_log(self) -> None:
        titulo = f"Banco password={_CENTINELA}"
        with capture_logs() as logs:
            r = await self._vista(pref_disable_polling=True, title=titulo)
            await self.llamar("ha_update_config_entry", entry_id="entrada-1",
                              pref_disable_polling=True, title=titulo,
                              confirmation_token=r["confirmation_token"])
        self.assertNotIn(_CENTINELA, json.dumps(r["preview"]))
        self.assertNotIn(_CENTINELA, self.ficheros_de_tokens())
        self.assertNotIn(_CENTINELA, json.dumps(logs, default=str))
        # Lo que se envía a HA es el título tal cual (no el tapado).
        self.assertEqual(self.fake.ws[-1]["title"], titulo)


if __name__ == "__main__":
    unittest.main()
