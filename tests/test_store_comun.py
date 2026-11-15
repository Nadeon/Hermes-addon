"""Piezas comunes de la tienda de apps (spec 030, `tools/_store.py`; T003).

Funciones puras: repositorios integrados, `slug` de un repositorio, tapado de
credenciales en URL y mensajes, y el marcador de texto de terceros.

Control negativo (T012 b, recuento en el commit del tramo 1): devolver la URL
sin tapar en `tapar_credenciales` → caen los de tapado y los del centinela
de `tests/test_tools_store_repositories.py`. Tramo 2 (extra b, parte de
usuario entera): tapar solo la contraseña, como en el tramo 1 → caen 5
(`test_tapa_usuario_y_contrasena`, `test_conserva_el_resto` y tres subtests
de `test_tapa_un_token_como_usuario`); sin `tapar_usuario_en_texto` en
`redactar_mensaje` → caen 2 (`test_trozo_muy_corto_no_se_sustituye_suelto`
y un subtest de `test_sin_url_tambien_se_tapa`). Recuentos en `tasks.md`.
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
    """La parte de usuario se tapa ENTERA (extra b del supervisor del
    programa, tramo 2): `usuario:clave@`, `usuario@` y `token@`."""

    def test_tapa_usuario_y_contrasena(self) -> None:
        url = "https://usuario:centinela-clave-1@example.com/repo-ficticio"
        tapada = _store.tapar_credenciales(url)
        self.assertEqual(tapada, f"https://{REDACTED_MARKER}@example.com/repo-ficticio")
        self.assertNotIn("centinela-clave-1", tapada)
        self.assertNotIn("usuario", tapada)
        self.assertEqual(_store.credenciales_de_url(url), "usuario:centinela-clave-1")

    def test_tapa_un_token_como_usuario(self) -> None:
        # La forma de GitHub y GitLab para un repositorio privado: el secreto
        # es el usuario y no hay `:`. Era la duda del tramo 1.
        for url in ("https://centinela-token-9@example.com/repo-ficticio",
                    "https://usuario@example.com/repo-ficticio",
                    "https://usuario:@example.com/repo-ficticio"):
            with self.subTest(url=url):
                self.assertEqual(_store.tapar_credenciales(url),
                                 f"https://{REDACTED_MARKER}@example.com/repo-ficticio")
                self.assertIsNotNone(_store.credenciales_de_url(url))

    def test_conserva_el_resto(self) -> None:
        url = "https://usuario:clave@example.com:8443/a/b.git#feature/x-1.2"
        self.assertEqual(
            _store.tapar_credenciales(url),
            f"https://{REDACTED_MARKER}@example.com:8443/a/b.git#feature/x-1.2")

    def test_sin_credenciales_no_cambia(self) -> None:
        for url in ("https://example.com/repo-ficticio",
                    "https://example.com/a@b", "core", "local", ""):
            with self.subTest(url=url):
                self.assertEqual(_store.tapar_credenciales(url), url)
                self.assertIsNone(_store.credenciales_de_url(url))

    def test_lo_que_no_es_texto(self) -> None:
        self.assertIsNone(_store.tapar_credenciales(None))
        self.assertEqual(_store.tapar_credenciales(3), 3)

    def test_url_que_no_se_analiza_se_tapa_igual(self) -> None:
        # Un corchete sin cerrar hace fallar a `urlsplit`; aun así no sale
        # ninguna de las dos formas.
        for url in ("https://usuario:centinela-clave-1@[example.com/x",
                    "https://centinela-token-9@[example.com/x"):
            with self.subTest(url=url):
                tapada = _store.tapar_credenciales(url)
                self.assertNotIn("centinela", tapada)
                self.assertIn(REDACTED_MARKER, tapada)


class TestTaparEnTexto(unittest.TestCase):
    def test_cualquier_url_del_texto(self) -> None:
        texto = ("fallo con https://centinela-token-9@example.com/a y con "
                 "git+ssh://u:centinela-clave-1@example.com/b; https://example.com/c")
        out = _store.tapar_usuario_en_texto(texto)
        self.assertNotIn("centinela", out)
        self.assertIn(f"https://{REDACTED_MARKER}@example.com/a", out)
        self.assertIn(f"git+ssh://{REDACTED_MARKER}@example.com/b", out)
        self.assertIn("https://example.com/c", out)

    def test_estructura(self) -> None:
        valor = {"a": ["x https://centinela-token-9@example.com/r", 3, None],
                 "https://k@example.com": {"b": "nada"}}
        out = _store.tapar_en_estructura(valor)
        self.assertNotIn("centinela", str(out))
        self.assertEqual(out["a"][1:], [3, None])
        # Las claves no se tocan (son nombres de campo de Hermes).
        self.assertIn("https://k@example.com", out)


class TestRedactarMensaje(unittest.TestCase):
    def test_sustitucion_literal_de_las_credenciales(self) -> None:
        url = "https://usuario-largo:centinela-clave-1@example.com/repo-ficticio"
        # El Supervisor repite la clave y el usuario fuera de la forma de una URL.
        msg = ("Can't retrieve data from example.com due to auth "
               "usuario-largo / centinela-clave-1")
        out = _store.redactar_mensaje(msg, url)
        self.assertNotIn("centinela-clave-1", out)
        self.assertNotIn("usuario-largo", out)
        self.assertIn(REDACTED_MARKER, out)

    def test_token_como_usuario_literal(self) -> None:
        url = "https://centinela-token-9@example.com/repo-ficticio"
        out = _store.redactar_mensaje("auth failed for centinela-token-9", url)
        self.assertNotIn("centinela-token-9", out)

    def test_descodificada_tambien(self) -> None:
        url = "https://usuario:clave%40rara@example.com/x"
        msg = "error con clave@rara y con clave%40rara"
        out = _store.redactar_mensaje(msg, url)
        self.assertNotIn("clave@rara", out)
        self.assertNotIn("clave%40rara", out)

    def test_trozo_muy_corto_no_se_sustituye_suelto(self) -> None:
        # `git` en mitad de un mensaje no es un secreto; dentro de la URL sí
        # se tapa.
        url = "https://git@example.com/x"
        out = _store.redactar_mensaje(f"git clone failed: {url}", url)
        self.assertTrue(out.startswith("git clone failed"))
        self.assertIn(f"https://{REDACTED_MARKER}@example.com/x", out)

    def test_sin_url_tambien_se_tapa(self) -> None:
        for msg in ("failed for https://usuario:centinela-clave-1@example.com/x",
                    "failed for https://centinela-token-9@example.com/x"):
            with self.subTest(msg=msg):
                self.assertNotIn("centinela", _store.redactar_mensaje(msg))


class TestTextoDeTerceros(unittest.TestCase):
    def test_formato_del_marketplace(self) -> None:
        self.assertEqual(
            _store.texto_de_terceros(["name", "url", "maintainer"]),
            {"fields": ["name", "url", "maintainer"], "warning": _THIRD_PARTY_WARNING})


if __name__ == "__main__":
    unittest.main()
