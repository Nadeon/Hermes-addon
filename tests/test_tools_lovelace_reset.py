"""Tests de `ha_reset_lovelace_dashboard_config` (spec 024, tramo 2, CAP-071).

`ws_send` simulado con respuestas por tipo de comando, con la forma real de
Core 2026.11.1:

- `lovelace/dashboards/list`: lista de dicts con `id`, `url_path`, `title`,
  `icon`, `mode` (`storage`/`yaml`), `show_in_sidebar`, `require_admin`.
- `lovelace/config` de un dashboard sin configuración guardada: error
  `config_not_found` (`_handle_errors` de `components/lovelace/websocket.py`).
- `frontend/get_system_data` con `key: "core"`: `{"value": {"default_panel": …}}`.

Controles negativos (T029, anotados en el commit del tramo 2):
(a) quitar la guarda del principal → caen los de `TestProteccion`;
(b) no fallar cerrado sin `default_panel` → cae
    `test_panel_por_defecto_ilegible_falla_cerrado`;
(c) emitir el token sin `estado` → cae
    `test_configuracion_cambiada_rechaza_el_token`;
(d) no repetir la guarda con token → cae
    `test_panel_por_defecto_cambiado_entre_pasos`.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from aiohttp import ClientSession
from structlog.testing import capture_logs

from hermes import security
from hermes.ha import HAConnectionError
import hermes.tools.lovelace_reset as mod

from tests._ha_fixture import make_ready_client

_CENTINELA = "centinela-024"
_TOOL = "ha_reset_lovelace_dashboard_config"


class _DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


_PANEL = {
    "id": "panel_pruebas", "url_path": "panel-pruebas", "title": "Panel de pruebas",
    "icon": "mdi:test-tube", "mode": "storage", "show_in_sidebar": True,
    "require_admin": False,
}
_YAML = {
    "id": "panel-yaml", "url_path": "panel-yaml", "title": "Panel YAML",
    "icon": None, "mode": "yaml", "show_in_sidebar": True, "require_admin": False,
}
_PRINCIPAL = {
    "id": "lovelace", "url_path": "lovelace", "title": "Overview",
    "icon": "mdi:view-dashboard", "mode": "storage", "show_in_sidebar": True,
    "require_admin": False,
}

# Dos vistas: 2 tarjetas en la primera; 1 tarjeta en una sección y 1 insignia
# en la segunda (`_count_cards` cuenta tarjetas, secciones e insignias).
_CONFIG = {
    "title": "Panel de pruebas",
    "views": [
        {"title": "Inicio", "cards": [
            {"type": "entities", "entities": ["light.salon"]},
            {"type": "markdown", "content": f"nota {_CENTINELA}"},
        ]},
        {"title": "Salón", "type": "sections", "badges": [{"entity": "light.salon"}],
         "sections": [{"type": "grid", "cards": [{"type": "tile", "entity": "light.salon"}]}]},
    ],
}


class _WS:
    def __init__(self) -> None:
        self.respuestas: dict[str, Any] = {}
        self.llamadas: list[dict[str, Any]] = []

    async def __call__(self, payload: dict, timeout_seconds: int = 30) -> Any:
        self.llamadas.append(dict(payload))
        r = self.respuestas.get(payload.get("type"))
        if isinstance(r, Exception):
            raise r
        if r is None:
            raise HAConnectionError(f"sin respuesta para {payload.get('type')!r}")
        return r

    def de(self, tipo: str) -> list[dict[str, Any]]:
        return [c for c in self.llamadas if c.get("type") == tipo]


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._dir_original = security.CONFIRMATIONS_DIR
        self._tmp = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self._tmp.name)
        self.session = ClientSession()
        self.ha = make_ready_client(self.session)
        self.ws = _WS()
        self.ha.ws_send = self.ws
        self.ws.respuestas.update({
            "lovelace/dashboards/list": [_PRINCIPAL, _PANEL, _YAML],
            "lovelace/config": json.loads(json.dumps(_CONFIG)),
            "frontend/get_system_data": {"value": {"default_panel": "lovelace"}},
            # Core responde sin datos (`send_result` con `None`); el simulado
            # trata `None` como «sin respuesta configurada».
            "lovelace/config/delete": {},
        })
        mcp = _DummyMCP()
        mod.register(mcp, self.ha, response_max_bytes=131_072)
        self.tool = mcp.tools[_TOOL]

    async def asyncTearDown(self) -> None:
        await self.session.close()
        security.CONFIRMATIONS_DIR = self._dir_original
        self._tmp.cleanup()

    def assert_sin_borrar(self) -> None:
        self.assertEqual(self.ws.de("lovelace/config/delete"), [])

    async def vista_previa(self) -> dict[str, Any]:
        r = await self.tool("panel-pruebas")
        self.assertIn("confirmation_token", r, r)
        return r


class TestProteccion(_Base):
    async def test_principal_rechazado_sin_token_y_sin_llamadas(self) -> None:
        for url_path in (None, "", "lovelace"):
            for token in (None, "00000000-0000-4000-8000-000000000000"):
                with self.subTest(url_path=url_path, token=token):
                    self.ws.llamadas.clear()
                    r = await self.tool(url_path, confirmation_token=token)
                    self.assertEqual(r["error"], "cannot_reset_default_dashboard")
                    self.assertNotIn("confirmation_token", r)
                    self.assertEqual(self.ws.llamadas, [])

    async def test_panel_por_defecto_rechazado(self) -> None:
        self.ws.respuestas["frontend/get_system_data"] = {
            "value": {"default_panel": "panel-pruebas"}}
        r = await self.tool("panel-pruebas")
        self.assertEqual(r["error"], "cannot_reset_default_dashboard")
        self.assertNotIn("confirmation_token", r)
        self.assert_sin_borrar()

    async def test_panel_por_defecto_ilegible_falla_cerrado(self) -> None:
        for fallo in (HAConnectionError("caído", code="unknown_error"),
                      {"value": {"default_panel": 42}}, ["raro"]):
            with self.subTest(fallo=fallo):
                self.ws.respuestas["frontend/get_system_data"] = fallo
                r = await self.tool("panel-pruebas")
                self.assertEqual(r["error"], "default_panel_unknown")
                self.assertNotIn("confirmation_token", r)
                self.assertEqual(self.ws.de("lovelace/config"), [])
        self.assert_sin_borrar()


class TestRechazos(_Base):
    async def test_no_existe(self) -> None:
        r = await self.tool("no-existe")
        self.assertEqual(r["error"], "not_found")
        self.assertNotIn("confirmation_token", r)
        self.assert_sin_borrar()

    async def test_modo_yaml(self) -> None:
        r = await self.tool("panel-yaml")
        self.assertEqual(r["error"], "yaml_mode_dashboard")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.ws.de("lovelace/config"), [])
        self.assert_sin_borrar()

    async def test_sin_configuracion_guardada(self) -> None:
        self.ws.respuestas["lovelace/config"] = HAConnectionError(
            "lovelace/config failed: config_not_found: No config found.",
            code="config_not_found")
        r = await self.tool("panel-pruebas")
        self.assertEqual(r["error"], "nothing_to_reset")
        self.assertNotIn("confirmation_token", r)
        self.assert_sin_borrar()

    async def test_forma_inesperada(self) -> None:
        for raro in (["no", "es", "un", "dict"], "texto",
                     HAConnectionError("caído", code="unknown_error")):
            with self.subTest(raro=raro):
                self.ws.respuestas["lovelace/config"] = raro
                r = await self.tool("panel-pruebas")
                self.assertEqual(r["error"], "preview_unavailable")
                self.assertNotIn("confirmation_token", r)
        self.assert_sin_borrar()


class TestVistaPrevia(_Base):
    async def test_vista_previa_sin_borrar(self) -> None:
        r = await self.vista_previa()
        p = r["preview"]
        self.assertEqual(
            {k: p[k] for k in ("url_path", "title", "mode", "views", "cards")},
            {"url_path": "panel-pruebas", "title": "Panel de pruebas", "mode": "storage",
             "views": 2, "cards": 4})
        self.assertIn("auto-generated", p["effect"])
        self.assertIn("Irreversible", p["warning"])
        self.assertIn("ha_get_lovelace_dashboard", p["recovery"])
        self.assertIn("ha_save_lovelace_dashboard", p["recovery"])
        self.assert_sin_borrar()

    async def test_ni_la_vista_previa_ni_el_token_llevan_la_configuracion(self) -> None:
        # El token guarda solo la huella del estado (spec 018), nunca el
        # dashboard: /data entra en los backups.
        r = await self.vista_previa()
        self.assertNotIn(_CENTINELA, json.dumps(r, ensure_ascii=False))
        fichero = Path(self._tmp.name) / f"{r['confirmation_token']}.json"
        contenido = fichero.read_text(encoding="utf-8")
        self.assertNotIn(_CENTINELA, contenido)
        self.assertNotIn("light.salon", contenido)
        datos = json.loads(contenido)
        self.assertIn("state_hash", datos)
        self.assertNotIn("stored_args", datos)

    async def test_estrategia_sin_vistas(self) -> None:
        # T034: lo que se borra es la estrategia, y la vista previa lo dice
        # (con su `type`) en vez de «0 vistas y 0 tarjetas» a secas.
        # Control negativo: sin el bloque `if estrategia is not None` de la
        # vista previa, cae por la falta de `strategy` (comprobado).
        self.ws.respuestas["lovelace/config"] = {
            "strategy": {"type": "original-states", "hidden_areas": ["garaje"]}}
        r = await self.vista_previa()
        p = r["preview"]
        self.assertEqual((p["views"], p["cards"]), (0, 0))
        self.assertEqual(p["strategy"], "original-states")
        self.assertIn("strategy", p["warning"])
        self.assertNotIn("every view and card", p["warning"])
        self.assertNotIn("garaje", json.dumps(r))
        res = await self.tool("panel-pruebas", confirmation_token=r["confirmation_token"])
        self.assertEqual(res["strategy_removed"], "original-states")

    async def test_estrategia_sin_tipo_legible(self) -> None:
        self.ws.respuestas["lovelace/config"] = {"strategy": "rara"}
        r = await self.vista_previa()
        self.assertIs(r["preview"]["strategy"], True)

    async def test_sin_estrategia_no_hay_campo(self) -> None:
        r = await self.vista_previa()
        self.assertNotIn("strategy", r["preview"])


class TestListaDeDashboardsIlegible(_Base):
    """T033: si `lovelace/dashboards/list` falla, nunca `not_found` ni un
    resultado falso; sin token y sin gastar el token.

    Control negativo: volver a `_get_dashboard_meta_by_url_path` (que da
    `None` también ante el fallo) → caen los dos tests (comprobado).
    """

    _FALLOS = (HAConnectionError("caído", code="unknown_error"),
               HAConnectionError("timeout"), {"no": "es una lista"})

    async def test_vista_previa(self) -> None:
        for fallo in self._FALLOS:
            with self.subTest(fallo=fallo):
                self.ws.respuestas["lovelace/dashboards/list"] = fallo
                r = await self.tool("panel-pruebas")
                self.assertEqual(r["error"], "dashboards_unavailable")
                self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.ws.de("lovelace/config"), [])
        self.assert_sin_borrar()

    async def test_confirmacion_no_gasta_el_token(self) -> None:
        r = await self.vista_previa()
        token = r["confirmation_token"]
        self.ws.respuestas["lovelace/dashboards/list"] = HAConnectionError(
            "caído", code="unknown_error")
        res = await self.tool("panel-pruebas", confirmation_token=token)
        self.assertEqual(res["error"], "dashboards_unavailable")
        self.assertNotIn("result", res)
        self.assert_sin_borrar()
        datos = json.loads((Path(self._tmp.name) / f"{token}.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(datos["state"], "pending")
        # Al volver la lista, el mismo token vale.
        self.ws.respuestas["lovelace/dashboards/list"] = [_PRINCIPAL, _PANEL, _YAML]
        res = await self.tool("panel-pruebas", confirmation_token=token)
        self.assertEqual(res["result"], "ok")


class TestConfirmacion(_Base):
    async def test_confirmar_borra_con_el_url_path_exacto(self) -> None:
        r = await self.vista_previa()
        res = await self.tool("panel-pruebas", confirmation_token=r["confirmation_token"])
        self.assertEqual(res, {"result": "ok", "url_path": "panel-pruebas",
                               "views_removed": 2, "cards_removed": 4})
        self.assertEqual(self.ws.de("lovelace/config/delete"),
                         [{"type": "lovelace/config/delete", "url_path": "panel-pruebas"}])
        # Un solo uso.
        otra = await self.tool("panel-pruebas", confirmation_token=r["confirmation_token"])
        self.assertIn("already used", otra["error"])
        self.assertEqual(len(self.ws.de("lovelace/config/delete")), 1)

    async def test_token_de_otro_url_path(self) -> None:
        otro = dict(_PANEL, id="otro", url_path="otro-panel")
        self.ws.respuestas["lovelace/dashboards/list"] = [_PRINCIPAL, _PANEL, otro]
        r = await self.vista_previa()
        res = await self.tool("otro-panel", confirmation_token=r["confirmation_token"])
        self.assertIn("does not match", res["error"])
        self.assert_sin_borrar()

    async def test_configuracion_cambiada_rechaza_el_token(self) -> None:
        r = await self.vista_previa()
        cambiada = json.loads(json.dumps(_CONFIG))
        cambiada["views"][0]["cards"].append({"type": "button", "entity": "light.salon"})
        self.ws.respuestas["lovelace/config"] = cambiada
        res = await self.tool("panel-pruebas", confirmation_token=r["confirmation_token"])
        self.assertEqual(res["error"], "dashboard_changed")
        self.assert_sin_borrar()
        # El token no se gasta: con la configuración de la vista previa vale.
        self.ws.respuestas["lovelace/config"] = json.loads(json.dumps(_CONFIG))
        res = await self.tool("panel-pruebas", confirmation_token=r["confirmation_token"])
        self.assertEqual(res["result"], "ok")

    async def test_panel_por_defecto_cambiado_entre_pasos(self) -> None:
        r = await self.vista_previa()
        self.ws.respuestas["frontend/get_system_data"] = {
            "value": {"default_panel": "panel-pruebas"}}
        res = await self.tool("panel-pruebas", confirmation_token=r["confirmation_token"])
        self.assertEqual(res["error"], "cannot_reset_default_dashboard")
        self.assert_sin_borrar()

    async def test_dashboard_borrado_entre_pasos(self) -> None:
        r = await self.vista_previa()
        self.ws.respuestas["lovelace/dashboards/list"] = [_PRINCIPAL]
        res = await self.tool("panel-pruebas", confirmation_token=r["confirmation_token"])
        self.assertEqual(res, {"result": "not_found", "url_path": "panel-pruebas"})
        self.assert_sin_borrar()
        datos = json.loads((Path(self._tmp.name) / f"{r['confirmation_token']}.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(datos["state"], "completed")

    async def test_desaparecido_no_gasta_el_token_de_otra_accion(self) -> None:
        # Un token de otra tool con un url_path que no existe: «does not
        # match» y el token sigue pendiente.
        ajeno = await security.create_confirmation_token(
            "ha_delete_lovelace_dashboard", {"url_path": "no-existe"})
        res = await self.tool("no-existe", confirmation_token=ajeno["confirmation_token"])
        self.assertIn("does not match", res["error"])
        datos = json.loads((Path(self._tmp.name) / f"{ajeno['confirmation_token']}.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(datos["state"], "pending")

    async def test_restablecido_entre_pasos(self) -> None:
        r = await self.vista_previa()
        self.ws.respuestas["lovelace/config"] = HAConnectionError(
            "lovelace/config failed: config_not_found: No config found.",
            code="config_not_found")
        res = await self.tool("panel-pruebas", confirmation_token=r["confirmation_token"])
        self.assertEqual(res["result"], "nothing_to_reset")
        self.assert_sin_borrar()

    async def test_error_de_core_redactado_y_token_fallido(self) -> None:
        r = await self.vista_previa()
        self.ws.respuestas["lovelace/config/delete"] = HAConnectionError(
            f"lovelace/config/delete failed: error: password={_CENTINELA}", code="error")
        res = await self.tool("panel-pruebas", confirmation_token=r["confirmation_token"])
        self.assertIn("error", res)
        self.assertNotIn(_CENTINELA, json.dumps(res))
        datos = json.loads((Path(self._tmp.name) / f"{r['confirmation_token']}.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(datos["state"], "failed")
        self.assertNotIn(_CENTINELA, json.dumps(datos))


class TestLog(_Base):
    async def test_un_evento_por_llamada_sin_la_configuracion(self) -> None:
        with capture_logs() as logs:
            r = await self.vista_previa()
            await self.tool("panel-pruebas", confirmation_token=r["confirmation_token"])
            await self.tool("lovelace")
        eventos = [e for e in logs if e["event"] == "lovelace_dashboard_reset"]
        self.assertEqual([(e["tool"], e["url_path"], e["outcome"]) for e in eventos], [
            (_TOOL, "panel-pruebas", "preview"),
            (_TOOL, "panel-pruebas", "ok"),
            (_TOOL, "lovelace", "rejected:cannot_reset_default_dashboard"),
        ])
        texto = json.dumps(logs, default=str, ensure_ascii=False)
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn("light.salon", texto)


if __name__ == "__main__":
    unittest.main()
