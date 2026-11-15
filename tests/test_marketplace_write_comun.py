"""Funciones puras del módulo común de escritura del Marketplace (spec 026,
tramo 1; FR-001, FR-002, FR-006).

Control negativo (T013 a): con la guarda de `_WRITE_SUFFIXES` quitada de
`ws_escritura`, `test_guarda_de_escritura` cae (se envía `warning/accept`).
"""

from __future__ import annotations

import unittest

from aiohttp import ClientSession

from hermes.ha import HAConnectionError
from hermes.tools import _marketplace_write as mw
from hermes.tools._logs import ArgumentoInvalido
from tests._ha_fixture import make_ready_client
from tests.fixtures.marketplace_escritura import MarketplaceSimulado, error


class TestListasCerradas(unittest.TestCase):
    def test_escrituras_del_tramo_1(self) -> None:
        # Solo las cuatro que no exigen el aviso de riesgos (DV-1). Ninguna
        # de las prohibidas (clase D) ni de las que lo exigen.
        self.assertEqual(mw._WRITE_SUFFIXES, {
            "critical/acknowledge", "repository/ignore",
            "repositories/remove", "repository/refresh",
        })
        prohibidas = {"warning/accept", "github/connect", "repositories/add",
                      "repositories/detect", "repository/install",
                      "repository/version", "repository/beta"}
        self.assertFalse(prohibidas & (mw._WRITE_SUFFIXES | mw._READ_SUFFIXES))

    def test_lecturas_sin_escrituras(self) -> None:
        self.assertEqual(mw._READ_SUFFIXES, {
            "repositories/list", "repositories/removed", "critical/list"})
        self.assertFalse(mw._READ_SUFFIXES & mw._WRITE_SUFFIXES)


class TestGuardas(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.client = make_ready_client(self.session, {})
        self.ha = MarketplaceSimulado()
        self.client.ws_send = self.ha  # type: ignore[method-assign]

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_guarda_de_escritura(self) -> None:
        for sufijo in ("warning/accept", "github/connect", "repository/install",
                       "repositories/add", "repositories/list"):
            with self.subTest(sufijo=sufijo):
                with self.assertRaises(RuntimeError):
                    await mw.ws_escritura(self.client, sufijo, {"repository": "1"})
        self.assertEqual(self.ha.enviados, [])

    async def test_guarda_de_lectura(self) -> None:
        with self.assertRaises(RuntimeError):
            await mw.ws_lectura(self.client, "repository/ignore", {"repository": "1"})
        self.assertEqual(self.ha.enviados, [])

    async def test_nunca_cae_a_hacs(self) -> None:
        self.ha.errores["marketplace/critical/list"] = error("unknown_command")
        with self.assertRaises(mw.ErrorMarketplace) as ctx:
            await mw.criticos(self.client)
        self.assertEqual(ctx.exception.payload["error"], "marketplace_write_unsupported")
        self.assertEqual([t for t in self.ha.tipos if t.startswith("hacs/")], [])

    async def test_lista_por_categoria_y_se_para(self) -> None:
        repo = await mw.repositorio_por_id(self.client, "123456")
        self.assertEqual(repo["full_name"], "ejemplo/integracion")
        # `integration` va primero y basta un mensaje; nunca sin categorías.
        self.assertEqual(self.ha.enviados, [
            {"type": "marketplace/repositories/list", "categories": ["integration"]}])
        self.assertIsNone(await mw.repositorio_por_id(self.client, "999"))
        self.assertTrue(all("categories" in p for p in self.ha.enviados))


class TestCargas(unittest.TestCase):
    def test_cargas_exactas(self) -> None:
        self.assertEqual(mw.carga_reconocer("Ejemplo/Tarjeta-Critica"),
                         {"repository": "Ejemplo/Tarjeta-Critica"})
        self.assertEqual(mw.carga_ignorar("123456"), {"repository": "123456"})
        self.assertEqual(mw.carga_quitar("234567"), {"repository": "234567"})
        self.assertEqual(mw.carga_refrescar("345678"), {"repository": "345678"})


class TestValidacion(unittest.TestCase):
    def test_repository_id(self) -> None:
        self.assertEqual(mw.validar_repository_id("123456"), "123456")
        self.assertEqual(mw.validar_repository_id(123456), "123456")
        for malo in (True, False, "", "../x", "a" * 65, "12 34", None, 1.5):
            with self.subTest(malo=malo):
                with self.assertRaises(ArgumentoInvalido) as ctx:
                    mw.validar_repository_id(malo)
                self.assertEqual(ctx.exception.campo, "repository_id")

    def test_full_name(self) -> None:
        for bueno in ("ejemplo/tarjeta", "Ejemplo-1/tarjeta.js", "a/b_c-d.e"):
            with self.subTest(bueno=bueno):
                self.assertEqual(mw.validar_full_name(bueno), bueno)
        for malo in ("", "ejemplo", "ejemplo/", "/tarjeta", "a/b/c", "a b/c",
                     "ejemplo/.oculto", "https://github.com/a/b",
                     "a" * 40 + "/b", "a/" + "b" * 101, 5, None):
            with self.subTest(malo=malo):
                with self.assertRaises(ArgumentoInvalido) as ctx:
                    mw.validar_full_name(malo)
                self.assertEqual(ctx.exception.campo, "repository")


class TestTraduccion(unittest.TestCase):
    def test_codigos(self) -> None:
        casos = {
            "unknown_command": "marketplace_write_unsupported",
            "not_loaded": "marketplace_not_loaded",
            "github_rate_limited": "github_rate_limited",
            "repository_not_found": "repository_not_found",
            "repository_installed": "repository_installed",
        }
        for code, esperado in casos.items():
            with self.subTest(code=code):
                self.assertEqual(mw.traducir(error(code))["error"], esperado)
        otro = mw.traducir(error("home_assistant_error", "boom"))
        self.assertEqual((otro["error"], otro["ha_code"]), ("ha_error", "home_assistant_error"))
        self.assertEqual(mw.traducir(TimeoutError())["error"], "ha_error")
        self.assertNotIn("ha_code", mw.traducir(HAConnectionError("WS down")))

    def test_el_detalle_va_redactado(self) -> None:
        # Un error de HA que repite una URL con credenciales: se tapa la parte
        # de usuario antes de responder (FR-006).
        exc = error("home_assistant_error",
                    "fallo en https://usuario:centinela-026@github.com/ejemplo/x")
        detalle = mw.traducir(exc)["detail"]
        self.assertNotIn("centinela-026", detalle)
        self.assertNotIn("usuario", detalle)


class TestFormas(unittest.TestCase):
    def test_textos_de_terceros_recortados(self) -> None:
        largo = "x" * 1000
        e = mw.entrada_retirada({"repository": "a/b", "reason": largo,
                                 "removal_type": largo, "link": largo})
        self.assertEqual({len(e["reason"]), len(e["removal_type"]), len(e["link"])}, {300})
        c = mw.entrada_critica({"repository": "a/b", "reason": largo, "link": None,
                                "acknowledged": False})
        self.assertEqual((len(c["reason"]), c["link"], c["acknowledged"]), (300, None, False))

    def test_resumen_sin_ruta_local(self) -> None:
        from tests.fixtures.marketplace_escritura import repositorios_base

        r = mw.resumen(repositorios_base()[0])
        self.assertEqual(set(r), {"id", "full_name", "name", "category", "custom",
                                  "installed", "installed_version", "available_version"})

    def test_terceros(self) -> None:
        self.assertIs(mw.terceros(True)["in_default_catalog"], False)
        self.assertIs(mw.terceros(False)["in_default_catalog"], True)
        self.assertIsNone(mw.terceros(None)["in_default_catalog"])
        t = mw.terceros(True)
        self.assertIs(t["third_party"], True)
        self.assertIs(t["reviewed_by_home_assistant"], False)
        self.assertIn("not reviewed by Home Assistant nor by Hermes", t["warning"])

    def test_buscar_por_nombre_sin_mayusculas(self) -> None:
        entradas = [{"repository": "Ejemplo/Tarjeta-Critica"}]
        self.assertIs(mw.buscar_por_nombre(entradas, "ejemplo/tarjeta-critica"), entradas[0])
        self.assertIsNone(mw.buscar_por_nombre(entradas, "ejemplo/otra"))
        self.assertIsNone(mw.buscar_por_nombre(entradas, None))


if __name__ == "__main__":
    unittest.main()
