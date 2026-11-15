"""Tests de las tools de mantenimiento del Marketplace (spec 026, tramo 1;
FR-001…FR-011 tras la DESVIACIÓN DV-1).

HA simulado con la forma de 2026.11.1 (`tests/fixtures/marketplace_escritura.py`).
Datos ficticios (`ejemplo/*`).

Controles negativos (T013), comprobados revirtiendo el código un momento:
- (e) quitar `estado=estado` de `create_confirmation_token` en
  `ha_marketplace_remove_repository` → cae
  `TestQuitar.test_cambio_entre_vista_y_confirmacion` (1 failed);
- (f) aceptar ignorar un no retirado (sin el rechazo
  `repository_not_removed`) → cae `TestIgnorar.test_no_retirado` (1 failed);
- (i) no rechazar `already_acknowledged` → caen
  `TestReconocer.test_ya_reconocido` y
  `test_reconocido_entre_vista_y_confirmacion` (2 failed);
- (j) mandar a HA el nombre que escribió el cliente en vez del guardado →
  cae `TestReconocer.test_vista_y_confirmacion` (1 failed).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from aiohttp import ClientSession
from structlog.testing import capture_logs

import hermes.security as security
from hermes.tools import marketplace_manage as mm
from tests._ha_fixture import make_ready_client
from tests.fixtures.marketplace_escritura import (
    ID_CATALOGO,
    ID_CRITICO,
    ID_INSTALADO,
    ID_PERSONALIZADO,
    MarketplaceSimulado,
    error,
)

_LECTURAS = {"marketplace/repositories/list", "marketplace/repositories/removed",
             "marketplace/critical/list"}


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.client = make_ready_client(self.session, {})
        self.ha = MarketplaceSimulado()
        self.client.ws_send = self.ha  # type: ignore[method-assign]
        self.mcp = DummyMCP()
        mm.register(self.mcp, self.client)

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def call(self, tool: str, **kwargs: Any) -> Any:
        return await self.mcp.tools[tool](**kwargs)

    async def vista_y_confirmar(self, tool: str, **kwargs: Any) -> tuple[Any, Any]:
        antes = len(self.ha.escrituras())
        vista = await self.call(tool, **kwargs)
        self.assertIn("confirmation_token", vista, vista)
        self.assertEqual(len(self.ha.escrituras()), antes, "la vista previa escribió")
        hecho = await self.call(tool, **kwargs, confirmation_token=vista["confirmation_token"])
        return vista, hecho

    def assert_sin_escrituras(self) -> None:
        self.assertEqual(self.ha.escrituras(), [])


# ── Reconocer ────────────────────────────────────────────────────────────────


class TestReconocer(_Base):
    T = "ha_marketplace_acknowledge_critical"

    async def test_vista_y_confirmacion(self) -> None:
        # El cliente escribe en minúsculas; HA lo guarda con mayúsculas y lo
        # compara con `==`: se envía el guardado.
        vista, hecho = await self.vista_y_confirmar(self.T, repository="ejemplo/tarjeta-critica")
        p = vista["preview"]
        self.assertEqual(p["entry"], {"repository": "Ejemplo/Tarjeta-Critica",
                                      "reason": "Roba el token",
                                      "link": "https://example.com/aviso",
                                      "acknowledged": False})
        self.assertIs(p["reversible"], False)
        self.assertIs(p["third_party"], True)
        self.assertEqual(p["_third_party_text"]["fields"], ["entry.reason", "entry.link"])
        self.assertEqual(self.ha.escrituras(), [
            {"type": "marketplace/critical/acknowledge",
             "repository": "Ejemplo/Tarjeta-Critica"}])
        self.assertEqual(hecho["result"], "ok")
        self.assertIs(hecho["entry"]["acknowledged"], True)

    async def test_no_critico(self) -> None:
        r = await self.call(self.T, repository="ejemplo/tarjeta")
        self.assertEqual(r["error"], "not_critical")
        self.assertNotIn("confirmation_token", r)
        self.assert_sin_escrituras()

    async def test_ya_reconocido(self) -> None:
        r = await self.call(self.T, repository="ejemplo/otra-critica")
        self.assertEqual(r["error"], "already_acknowledged")
        self.assert_sin_escrituras()

    async def test_reconocido_entre_vista_y_confirmacion(self) -> None:
        vista = await self.call(self.T, repository="ejemplo/tarjeta-critica")
        self.ha.criticos[0]["acknowledged"] = True
        r = await self.call(self.T, repository="ejemplo/tarjeta-critica",
                            confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "already_acknowledged")
        self.assert_sin_escrituras()

    async def test_motivo_cambiado_entre_vista_y_confirmacion(self) -> None:
        vista = await self.call(self.T, repository="ejemplo/tarjeta-critica")
        self.ha.criticos[0]["reason"] = "Otro motivo"
        r = await self.call(self.T, repository="ejemplo/tarjeta-critica",
                            confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], security.ESTADO_CAMBIADO)
        self.assert_sin_escrituras()

    async def test_repository_invalido(self) -> None:
        for malo in ("ejemplo", "https://github.com/a/b", "", 5):
            with self.subTest(malo=malo):
                r = await self.call(self.T, repository=malo)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "repository"))
        self.assertEqual(self.ha.enviados, [])


# ── Ignorar ──────────────────────────────────────────────────────────────────


class TestIgnorar(_Base):
    T = "ha_marketplace_ignore_repository"

    async def test_vista_y_confirmacion(self) -> None:
        self.ha.retirados[0]["reason"] = "r" * 500
        vista, hecho = await self.vista_y_confirmar(self.T, repository_id=ID_INSTALADO)
        p = vista["preview"]
        self.assertEqual(p["removed"]["removal_type"], "archived")
        self.assertEqual(len(p["removed"]["reason"]), 300)
        self.assertIn("removed.reason", p["_third_party_text"]["fields"])
        self.assertIs(p["reversible"], False)
        self.assertIs(p["backup"]["will_create"], False)
        self.assertEqual(p["repository"]["full_name"], "ejemplo/integracion")
        self.assertEqual(self.ha.escrituras(), [
            {"type": "marketplace/repository/ignore", "repository": ID_INSTALADO}])
        self.assertEqual(hecho["result"], "ok")
        self.assertIn("ejemplo/integracion", self.ha.ignorados)

    async def test_entero_como_id(self) -> None:
        vista = await self.call(self.T, repository_id=int(ID_INSTALADO))
        self.assertIn("confirmation_token", vista)

    async def test_no_encontrado(self) -> None:
        r = await self.call(self.T, repository_id="999999")
        self.assertEqual(r["error"], "repository_not_found")
        self.assert_sin_escrituras()

    async def test_no_retirado(self) -> None:
        r = await self.call(self.T, repository_id=ID_PERSONALIZADO)
        self.assertEqual(r["error"], "repository_not_removed")
        self.assertNotIn("confirmation_token", r)
        self.assert_sin_escrituras()

    async def test_critico(self) -> None:
        r = await self.call(self.T, repository_id=ID_CRITICO)
        self.assertEqual(r["error"], "critical_repository")
        self.assertIn("ha_marketplace_acknowledge_critical", r["detail"])
        self.assert_sin_escrituras()

    async def test_motivo_cambiado_entre_vista_y_confirmacion(self) -> None:
        vista = await self.call(self.T, repository_id=ID_INSTALADO)
        self.ha.retirados[0]["removal_type"] = "removed"
        r = await self.call(self.T, repository_id=ID_INSTALADO,
                            confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], security.ESTADO_CAMBIADO)
        self.assert_sin_escrituras()


# ── Quitar ───────────────────────────────────────────────────────────────────


class TestQuitar(_Base):
    T = "ha_marketplace_remove_repository"

    async def test_vista_y_confirmacion(self) -> None:
        vista, hecho = await self.vista_y_confirmar(self.T, repository_id=ID_PERSONALIZADO)
        p = vista["preview"]
        self.assertIs(p["repository"]["custom"], True)
        self.assertIs(p["in_default_catalog"], False)
        self.assertIs(p["reviewed_by_home_assistant"], False)
        self.assertEqual(self.ha.escrituras(), [
            {"type": "marketplace/repositories/remove", "repository": ID_PERSONALIZADO}])
        self.assertEqual(hecho["result"], "ok")
        self.assertNotIn(ID_PERSONALIZADO, [r["id"] for r in self.ha.repos])

    async def test_instalado(self) -> None:
        self.ha.repo(ID_INSTALADO)["custom"] = True
        r = await self.call(self.T, repository_id=ID_INSTALADO)
        self.assertEqual(r["error"], "repository_installed")
        self.assertIn("Uninstall", r["detail"])
        self.assert_sin_escrituras()

    async def test_del_catalogo(self) -> None:
        r = await self.call(self.T, repository_id=ID_CATALOGO)
        self.assertEqual(r["error"], "not_custom_repository")
        self.assert_sin_escrituras()

    async def test_no_encontrado(self) -> None:
        r = await self.call(self.T, repository_id="999999")
        self.assertEqual(r["error"], "repository_not_found")
        self.assert_sin_escrituras()

    async def test_instalado_entre_vista_y_confirmacion(self) -> None:
        vista = await self.call(self.T, repository_id=ID_PERSONALIZADO)
        self.ha.repo(ID_PERSONALIZADO)["installed"] = True
        r = await self.call(self.T, repository_id=ID_PERSONALIZADO,
                            confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "repository_installed")
        self.assert_sin_escrituras()

    async def test_cambio_entre_vista_y_confirmacion(self) -> None:
        # Renombrado en GitHub entre la vista previa y la confirmación: lo que
        # se previsualizó ya no es lo que se quitaría.
        vista = await self.call(self.T, repository_id=ID_PERSONALIZADO)
        self.ha.repo(ID_PERSONALIZADO)["full_name"] = "otro/tarjeta"
        r = await self.call(self.T, repository_id=ID_PERSONALIZADO,
                            confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], security.ESTADO_CAMBIADO)
        self.assert_sin_escrituras()

    async def test_error_de_ha_al_confirmar_gasta_el_token(self) -> None:
        vista = await self.call(self.T, repository_id=ID_PERSONALIZADO)
        self.ha.errores["marketplace/repositories/remove"] = error("repository_installed")
        token = vista["confirmation_token"]
        r = await self.call(self.T, repository_id=ID_PERSONALIZADO, confirmation_token=token)
        self.assertEqual(r["error"], "repository_installed")
        datos = json.loads((Path(security.CONFIRMATIONS_DIR) / f"{token}.json").read_text("utf-8"))
        self.assertEqual(datos["state"], "failed")


# ── Refrescar ────────────────────────────────────────────────────────────────


class TestRefrescar(_Base):
    T = "ha_marketplace_refresh_repository"

    async def test_vista_y_confirmacion(self) -> None:
        vista, hecho = await self.vista_y_confirmar(self.T, repository_id=ID_CATALOGO)
        p = vista["preview"]
        self.assertIs(p["contacts_github"], True)
        self.assertIs(p["backup"]["will_create"], False)
        self.assertIs(p["in_default_catalog"], True)
        self.assertEqual(self.ha.escrituras(), [
            {"type": "marketplace/repository/refresh", "repository": ID_CATALOGO}])
        self.assertEqual(hecho["repository"]["available_version"], "1.3.0")

    async def test_limite_de_github_al_confirmar(self) -> None:
        vista = await self.call(self.T, repository_id=ID_CATALOGO)
        self.ha.errores["marketplace/repository/refresh"] = error("github_rate_limited")
        token = vista["confirmation_token"]
        r = await self.call(self.T, repository_id=ID_CATALOGO, confirmation_token=token)
        self.assertEqual(r["error"], "github_rate_limited")
        self.assertIn("try again later", r["detail"])
        datos = json.loads((Path(security.CONFIRMATIONS_DIR) / f"{token}.json").read_text("utf-8"))
        self.assertEqual(datos["state"], "failed")

    async def test_renombrado_entre_vista_y_confirmacion(self) -> None:
        vista = await self.call(self.T, repository_id=ID_CATALOGO)
        self.ha.repo(ID_CATALOGO)["category"] = "plugin"
        r = await self.call(self.T, repository_id=ID_CATALOGO,
                            confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], security.ESTADO_CAMBIADO)
        self.assert_sin_escrituras()

    async def test_token_de_otro_repositorio(self) -> None:
        vista = await self.call(self.T, repository_id=ID_CATALOGO)
        r = await self.call(self.T, repository_id=ID_PERSONALIZADO,
                            confirmation_token=vista["confirmation_token"])
        self.assertIn("does not match", r["error"])
        self.assert_sin_escrituras()


# ── Común a las cuatro ───────────────────────────────────────────────────────


_CASOS = (
    ("ha_marketplace_acknowledge_critical", {"repository": "ejemplo/tarjeta-critica"}),
    ("ha_marketplace_ignore_repository", {"repository_id": ID_INSTALADO}),
    ("ha_marketplace_remove_repository", {"repository_id": ID_PERSONALIZADO}),
    ("ha_marketplace_refresh_repository", {"repository_id": ID_CATALOGO}),
)


class TestComun(_Base):
    async def test_sin_marketplace_no_prueba_hacs(self) -> None:
        for tool, args in _CASOS:
            with self.subTest(tool=tool):
                self.ha.enviados.clear()
                for tipo in _LECTURAS:
                    self.ha.errores[tipo] = error("unknown_command")
                r = await self.call(tool, **args)
                self.assertEqual(r["error"], "marketplace_write_unsupported")
                self.assertEqual([t for t in self.ha.tipos if not t.startswith("marketplace/")], [])

    async def test_no_cargado(self) -> None:
        # `critical/list` no usa el decorador de HA: nunca responde
        # `not_loaded`. Las otras tres leen la lista, que sí.
        self.ha.errores["marketplace/repositories/list"] = error("not_loaded")
        for tool, args in _CASOS[1:]:
            with self.subTest(tool=tool):
                r = await self.call(tool, **args)
                self.assertEqual(r["error"], "marketplace_not_loaded")
        self.assert_sin_escrituras()

    async def test_solo_comandos_permitidos(self) -> None:
        for tool, args in _CASOS:
            with self.subTest(tool=tool):
                await self.vista_y_confirmar(tool, **args)
        prohibidos = {"marketplace/warning/accept", "marketplace/github/connect"}
        for tipo in self.ha.tipos:
            self.assertFalse(tipo.startswith(("hassio/", "supervisor/")), tipo)
            self.assertNotIn(tipo, prohibidos)
        escritos = {p["type"] for p in self.ha.escrituras()}
        self.assertEqual(escritos, {
            "marketplace/critical/acknowledge", "marketplace/repository/ignore",
            "marketplace/repositories/remove", "marketplace/repository/refresh"})

    async def test_evento_sin_datos_del_repositorio(self) -> None:
        with capture_logs() as logs:
            for tool, args in _CASOS:
                await self.vista_y_confirmar(tool, **args)
            await self.call("ha_marketplace_remove_repository", repository_id=ID_CATALOGO)
        eventos = [e for e in logs if e.get("event") == "marketplace_write"]
        self.assertEqual(len(eventos), 9)
        for e in eventos:
            self.assertEqual(set(e) - {"log_level"}, {"event", "tool", "outcome", "category"})
        self.assertIn("rejected:not_custom_repository", [e["outcome"] for e in eventos])
        texto = json.dumps(logs, default=str)
        for dato in ("ejemplo", "Ejemplo", ID_INSTALADO, ID_PERSONALIZADO, ID_CATALOGO,
                     "example.com", "Roba el token"):
            self.assertNotIn(dato, texto)

    async def test_url_con_credenciales_en_un_texto_de_terceros(self) -> None:
        # `link` y `reason` los escribe el catálogo: una URL con la parte de
        # usuario no sale nunca tal cual (`tapar_en_estructura`).
        self.ha.criticos[0]["link"] = "https://usuario:centinela-026@example.com/x"
        vista = await self.call("ha_marketplace_acknowledge_critical",
                                repository="ejemplo/tarjeta-critica")
        self.assertNotIn("centinela-026", json.dumps(vista))
        self.assertIn("***REDACTED***", vista["preview"]["entry"]["link"])

    async def test_ha_caido_al_leer(self) -> None:
        from hermes.ha import HAConnectionError

        self.ha.errores["marketplace/repositories/list"] = HAConnectionError("WS down")
        r = await self.call("ha_marketplace_refresh_repository", repository_id=ID_CATALOGO)
        self.assertEqual(r["error"], "ha_error")
        self.assert_sin_escrituras()


if __name__ == "__main__":
    unittest.main()
