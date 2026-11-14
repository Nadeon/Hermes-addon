"""Piezas comunes de la tienda de apps (spec 030, `tools/_store.py`; T003).

Funciones puras: repositorios integrados, `slug` de un repositorio, tapado de
credenciales en URL y mensajes, y el marcador de texto de terceros.

Control negativo (T012 b, recuento en el commit del tramo 1): devolver la URL
sin tapar en `tapar_credenciales` → caen `test_tapa_la_contrasena`,
`test_conserva_el_resto` y los del centinela de
`tests/test_tools_store_repositories.py`.
"""

from __future__ import annotations

import unittest

from hermes.security import REDACTED_MARKER
from hermes.tools import _store
from hermes.tools.marketplace import _THIRD_PARTY_WARNING


class TestIntegrados(unittest.TestCase):
    def test_los_cinco_del_supervisor(self) -> None:
        self.assertEqual(_store.REPOSITORIOS_INTEGRADOS,
                         {"core", "local", "a0d7b954", "5c53de3b", "d5369777"})
        for slug in _store.REPOSITORIOS_INTEGRADOS:
            self.assertTrue(_store.es_integrado(slug))
        for slug in ("abcd1234", "CORE", "", "local_ejemplo"):
            self.assertFalse(_store.es_integrado(slug), slug)

    def test_slug_como_el_supervisor(self) -> None:
        # `sha1(url.lower())[:8]` sobre la cadena entera, rama incluida.
        import hashlib

        url = "https://Example.com/Repo-Ficticio#main"
        self.assertEqual(_store.slug_de_repositorio(url),
                         hashlib.sha1(url.lower().encode()).hexdigest()[:8])
        self.assertEqual(_store.slug_de_repositorio(url),
                         _store.slug_de_repositorio(url.lower()))
        self.assertNotEqual(_store.slug_de_repositorio(url),
                            _store.slug_de_repositorio("https://example.com/repo-ficticio"))


class TestTaparCredenciales(unittest.TestCase):
    def test_tapa_la_contrasena(self) -> None:
        url = "https://usuario:centinela-clave-1@example.com/repo-ficticio"
        tapada = _store.tapar_credenciales(url)
        self.assertEqual(
            tapada, f"https://usuario:{REDACTED_MARKER}@example.com/repo-ficticio")
        self.assertNotIn("centinela-clave-1", tapada)
        self.assertEqual(_store.contrasena_de_url(url), "centinela-clave-1")

    def test_conserva_el_resto(self) -> None:
        url = "https://usuario:clave@example.com:8443/a/b.git#feature/x-1.2"
        self.assertEqual(
            _store.tapar_credenciales(url),
            f"https://usuario:{REDACTED_MARKER}@example.com:8443/a/b.git#feature/x-1.2")

    def test_sin_contrasena_no_cambia(self) -> None:
        for url in ("https://example.com/repo-ficticio",
                    "https://usuario@example.com/repo-ficticio",
                    "https://usuario:@example.com/x", "core", "local", ""):
            with self.subTest(url=url):
                self.assertEqual(_store.tapar_credenciales(url), url)
                self.assertIsNone(_store.contrasena_de_url(url))

    def test_lo_que_no_es_texto(self) -> None:
        self.assertIsNone(_store.tapar_credenciales(None))
        self.assertEqual(_store.tapar_credenciales(3), 3)

    def test_url_que_no_se_analiza_pasa_por_la_redaccion(self) -> None:
        # Un puerto imposible hace fallar a `urlsplit` en algunos accesos; un
        # corchete sin cerrar, siempre. Aun así no sale la clave.
        url = "https://usuario:centinela-clave-1@[example.com/x"
        self.assertNotIn("centinela-clave-1", _store.tapar_credenciales(url))


class TestRedactarMensaje(unittest.TestCase):
    def test_sustitucion_literal_de_la_contrasena(self) -> None:
        url = "https://usuario:centinela-clave-1@example.com/repo-ficticio"
        # El Supervisor repite la clave fuera de la forma de una URL.
        msg = "Can't retrieve data from example.com due to auth centinela-clave-1"
        self.assertNotIn("centinela-clave-1", _store.redactar_mensaje(msg, url))
        self.assertIn(REDACTED_MARKER, _store.redactar_mensaje(msg, url))

    def test_descodificada_tambien(self) -> None:
        url = "https://usuario:clave%40rara@example.com/x"
        msg = "error con clave@rara y con clave%40rara"
        out = _store.redactar_mensaje(msg, url)
        self.assertNotIn("clave@rara", out)
        self.assertNotIn("clave%40rara", out)

    def test_sin_url_redaccion_general(self) -> None:
        msg = "failed for https://usuario:centinela-clave-1@example.com/x"
        self.assertNotIn("centinela-clave-1", _store.redactar_mensaje(msg))


class TestTextoDeTerceros(unittest.TestCase):
    def test_formato_del_marketplace(self) -> None:
        self.assertEqual(
            _store.texto_de_terceros(["name", "url", "maintainer"]),
            {"fields": ["name", "url", "maintainer"], "warning": _THIRD_PARTY_WARNING})


if __name__ == "__main__":
    unittest.main()
