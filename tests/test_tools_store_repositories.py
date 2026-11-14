"""Repositorios de la tienda de apps (spec 030, tramo 1; T003–T006).

`sv_list_store_repositories`, `sv_add_store_repository`,
`sv_remove_store_repository`, `sv_repair_store_repository` y
`sv_reload_store` contra un Supervisor simulado con la forma del 2026.11.0
(`tests/fixtures/supervisor_tienda.py`). Se comprueba lo que Hermes MANDA (y
lo que NO manda: un rechazo no llega al Supervisor), las vistas previas, el
token, la redacción de las credenciales de una URL y el evento de log.

Controles negativos (T012), con recuentos en el commit del tramo:
(a) aceptar cualquier esquema en la URL → cae `test_urls_invalidas_sin_llamada`;
(b) no tapar la contraseña → caen los del centinela;
(c) emitir token con apps instaladas → cae `test_con_apps_instaladas_sin_token`;
(d) quitar `estado` del token → cae `test_cambio_entre_vista_previa_y_confirmacion`;
(e) comparar URLs distinguiendo mayúsculas → cae `test_ya_anadida_sin_token`;
(f) registrar la URL en el evento → cae `test_evento_de_anadir_sin_url`.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from structlog.testing import capture_logs

from hermes.ha import HAConnectionError
from hermes.security import REDACTED_MARKER
from hermes.tools.addons import _LONG_OP_TIMEOUT
from hermes.tools.marketplace import _THIRD_PARTY_WARNING
from hermes.tools.store_repositories import register
from tests.fixtures.supervisor_tienda import (
    APPS,
    CENTINELA_CLAVE,
    REPOSITORIOS,
    URL_CON_CLAVE,
    URL_FICTICIA,
    SupervisorSimulado,
    apps_con_instalada,
    tienda_normal,
)


class _MCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


class _Base(unittest.IsolatedAsyncioTestCase):
    max_bytes = 131_072

    def setUp(self) -> None:
        self.sv = SupervisorSimulado()
        tienda_normal(self.sv)
        mcp = _MCP()
        register(mcp, self.sv, response_max_bytes=self.max_bytes)
        self.t = mcp.tools

    def assertSinCentinela(self, valor: Any) -> None:  # noqa: N802
        self.assertNotIn(CENTINELA_CLAVE, json.dumps(valor, ensure_ascii=False))


# ── Listar (FR-001, FR-017, FR-018, FR-019) ───────────────────────────────────


class TestListar(_Base):
    async def test_sobre_y_campos(self) -> None:
        r = await self.t["sv_list_store_repositories"]()
        self.assertEqual(r["count"], len(REPOSITORIOS))
        self.assertEqual(r["count"], len(r["items"]))
        self.assertIs(r["truncated"], False)
        por_slug = {i["slug"]: i for i in r["items"]}
        self.assertEqual(set(por_slug), {x["slug"] for x in REPOSITORIOS})
        for item in r["items"]:
            self.assertEqual(
                set(item), {"slug", "name", "source", "url", "maintainer",
                            "builtin", "apps_count", "installed_apps"})
        self.assertEqual(r["_third_party_text"],
                         {"fields": ["name", "url", "maintainer"],
                          "warning": _THIRD_PARTY_WARNING})
        self.assertEqual(self.sv.rutas(), [("GET", "/store/repositories"),
                                           ("GET", "/store/addons")])

    async def test_builtin_exactamente_los_integrados(self) -> None:
        r = await self.t["sv_list_store_repositories"]()
        self.assertEqual({i["slug"] for i in r["items"] if i["builtin"]},
                         {"core", "local", "a0d7b954"})
        self.assertIs(next(i for i in r["items"] if i["slug"] == "abcd1234")["builtin"], False)

    async def test_recuentos_por_repositorio(self) -> None:
        r = await self.t["sv_list_store_repositories"]()
        por_slug = {i["slug"]: i for i in r["items"]}
        self.assertEqual(por_slug["core"]["apps_count"], 2)
        self.assertEqual(por_slug["core"]["installed_apps"], ["core_ejemplo"])
        self.assertEqual(por_slug["abcd1234"]["apps_count"], 2)
        self.assertEqual(por_slug["abcd1234"]["installed_apps"], [])
        self.assertEqual(por_slug["local"]["installed_apps"], ["local_ejemplo"])

    async def test_orden_integrados_primero_y_por_slug(self) -> None:
        r = await self.t["sv_list_store_repositories"]()
        self.assertEqual([i["slug"] for i in r["items"]],
                         ["a0d7b954", "core", "local", "abcd1234"])

    async def test_centinela_tapado(self) -> None:
        r = await self.t["sv_list_store_repositories"]()
        self.assertSinCentinela(r)
        privado = next(i for i in r["items"] if i["slug"] == "abcd1234")
        tapada = f"https://usuario:{REDACTED_MARKER}@example.com/repo-ficticio"
        self.assertEqual(privado["source"], tapada)
        self.assertEqual(privado["url"], tapada)

    async def test_uno_por_slug(self) -> None:
        r = await self.t["sv_list_store_repositories"](repository="abcd1234")
        self.assertEqual(r["repository"]["slug"], "abcd1234")
        self.assertEqual(r["repository"]["apps_count"], 2)
        self.assertNotIn("items", r)
        self.assertEqual(r["_third_party_text"]["fields"],
                         ["repository.name", "repository.url", "repository.maintainer"])
        self.assertSinCentinela(r)
        self.assertEqual(self.sv.rutas()[0], ("GET", "/store/repositories/abcd1234"))

    async def test_uno_que_no_existe(self) -> None:
        r = await self.t["sv_list_store_repositories"](repository="ffff0000")
        self.assertEqual(r["error"], "repository_not_found")
        self.assertIn("sv_list_store_repositories", r["detail"])

    async def test_slug_invalido_sin_llamada(self) -> None:
        for valor in ("../x", "", "a/b", " "):
            with self.subTest(valor=valor):
                r = await self.t["sv_list_store_repositories"](repository=valor)
                self.assertEqual(r["error"], "invalid_identifier")
        self.assertEqual(self.sv.llamadas, [])

    async def test_catalogo_que_falla_no_impide_la_lista(self) -> None:
        self.sv.respuesta("GET", "/store/addons", HAConnectionError(
            f"Supervisor failed 500: boom {URL_CON_CLAVE}", status=500))
        r = await self.t["sv_list_store_repositories"]()
        self.assertEqual(r["count"], len(REPOSITORIOS))
        for item in r["items"]:
            self.assertIsNone(item["apps_count"])
            self.assertIsNone(item["installed_apps"])
        self.assertIn("boom", r["apps_unavailable"])
        self.assertSinCentinela(r)

    async def test_error_al_listar_redactado(self) -> None:
        self.sv.respuesta("GET", "/store/repositories", HAConnectionError(
            f"Supervisor failed 500: {URL_CON_CLAVE}", status=500))
        r = await self.t["sv_list_store_repositories"]()
        self.assertIn("error", r)
        self.assertSinCentinela(r)


class TestListarRecortado(_Base):
    max_bytes = 2_000

    async def test_lista_grande_recortada(self) -> None:
        muchos = [
            {"slug": f"{i:08x}", "name": "R" * 200, "source": f"https://example.com/r{i}",
             "url": f"https://example.com/r{i}", "maintainer": "M" * 100}
            for i in range(40)
        ]
        self.sv.respuesta("GET", "/store/repositories", muchos)
        r = await self.t["sv_list_store_repositories"]()
        self.assertIs(r["truncated"], True)
        self.assertEqual(r["count"], len(r["items"]))
        self.assertLess(r["count"], 40)
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False).encode()), self.max_bytes)


# ── Añadir (FR-002, FR-018, FR-019) ───────────────────────────────────────────


_VALIDAS = (
    URL_FICTICIA,
    f"{URL_FICTICIA}#main",
    f"{URL_FICTICIA}#feature/x-1.2",
    f"  {URL_FICTICIA}  ",
)

_INVALIDAS = (
    "", "   ", "ftp://example.com/x", "file:///tmp/x", "example.com/x",
    "https://", "https://example.com/a b", "https://example.com/x#",
    "https://example.com/x#rama con espacio",
    "https://example.com/" + "a" * 2029,  # 2049 caracteres
)


class TestAnadir(_Base):
    async def test_urls_validas_dan_vista_previa(self) -> None:
        for url in _VALIDAS:
            with self.subTest(url=url):
                r = await self.t["sv_add_store_repository"](url)
                self.assertIn("confirmation_token", r, r)
                self.assertEqual(r["preview"]["repository"], url.strip())
        self.assertEqual(self.sv.escrituras(), [])

    async def test_urls_invalidas_sin_llamada(self) -> None:
        self.assertEqual(len(_INVALIDAS[-1]), 2049)
        for url in _INVALIDAS:
            with self.subTest(url=url[:40]):
                r = await self.t["sv_add_store_repository"](url)
                self.assertEqual(r["error"], "invalid_argument")
                self.assertEqual(r["field"], "repository")
                self.assertNotIn("confirmation_token", r)
                if url.strip():
                    self.assertNotIn(url.strip(), r["detail"])
        self.assertEqual(self.sv.llamadas, [])

    async def test_ya_anadida_sin_token(self) -> None:
        # La del repositorio privado en mayúsculas (el Supervisor compara sin
        # distinguirlas: el slug es el hash de la URL en minúsculas) y las dos
        # que el Supervisor traduce a `core`.
        for url, slug in ((URL_CON_CLAVE.upper().replace("HTTPS", "https"), "abcd1234"),
                          ("https://github.com/home-assistant/apps", "core"),
                          ("https://github.com/home-assistant/addons", "core"),
                          ("https://github.com/hassio-addons/repository", "a0d7b954")):
            with self.subTest(url=url):
                r = await self.t["sv_add_store_repository"](url)
                self.assertEqual(r.get("error"), "repository_already_added", r)
                self.assertEqual(r["repository"], slug)
                self.assertNotIn("confirmation_token", r)
                self.assertSinCentinela(r)
        self.assertEqual(self.sv.escrituras(), [])

    async def test_vista_previa(self) -> None:
        url = "https://usuario:otra-clave-2@example.com/nuevo#main"
        r = await self.t["sv_add_store_repository"](url)
        p = r["preview"]
        self.assertEqual(p["action"], "add_store_repository")
        self.assertEqual(p["repository"],
                         f"https://usuario:{REDACTED_MARKER}@example.com/nuevo#main")
        self.assertEqual(p["host"], "example.com")
        self.assertEqual(p["branch"], "main")
        self.assertIs(p["credentials_hidden"], True)
        for palabra in ("Third-party", "not reviewed", "does not install"):
            self.assertIn(palabra, p["warning"])
        self.assertIn("Nothing is downloaded", p["note"])
        self.assertNotIn("otra-clave-2", json.dumps(r))
        self.assertEqual(self.sv.escrituras(), [])

    async def test_vista_previa_sin_credenciales(self) -> None:
        r = await self.t["sv_add_store_repository"]("https://example.com/nuevo")
        self.assertIs(r["preview"]["credentials_hidden"], False)
        self.assertIsNone(r["preview"]["branch"])

    async def test_confirmacion(self) -> None:
        url = "https://usuario:otra-clave-2@example.com/nuevo"
        nuevo = {"slug": "ffff0001", "name": "Nuevo", "source": url, "url": url,
                 "maintainer": "Alguien"}
        prev = await self.t["sv_add_store_repository"](f"  {url} ")
        self.sv.respuesta("POST", "/store/repositories", {})
        self.sv.secuencia("GET", "/store/repositories",
                          [REPOSITORIOS + [nuevo]])
        r = await self.t["sv_add_store_repository"](url, prev["confirmation_token"])
        post = self.sv.escrituras()
        self.assertEqual(len(post), 1)
        self.assertEqual((post[0]["ruta"], post[0]["json"], post[0]["timeout"]),
                         ("/store/repositories", {"repository": url}, _LONG_OP_TIMEOUT))
        self.assertEqual(r["result"], "ok")
        self.assertEqual(r["repository"]["slug"], "ffff0001")
        self.assertEqual(r["repository"]["url"],
                         f"https://usuario:{REDACTED_MARKER}@example.com/nuevo")
        self.assertEqual(r["_third_party_text"]["fields"],
                         ["repository.name", "repository.url", "repository.maintainer"])
        self.assertIn("sv_install_addon", r["next"])
        self.assertNotIn("otra-clave-2", json.dumps(r))

    async def test_confirmacion_sin_releer(self) -> None:
        prev = await self.t["sv_add_store_repository"]("https://example.com/nuevo")
        self.sv.respuesta("POST", "/store/repositories", {})
        self.sv.respuesta("GET", "/store/repositories", HAConnectionError("x", status=500))
        r = await self.t["sv_add_store_repository"]("https://example.com/nuevo",
                                                     prev["confirmation_token"])
        self.assertEqual(r["result"], "ok")
        self.assertIsNone(r["repository"])
        self.assertIn("sv_list_store_repositories", r["hint"])

    async def test_error_del_supervisor_sin_centinela(self) -> None:
        url = f"https://usuario:{CENTINELA_CLAVE}@example.com/otro"
        prev = await self.t["sv_add_store_repository"](url)
        self.sv.respuesta("POST", "/store/repositories", HAConnectionError(
            f"Supervisor REST POST failed 400: Can't retrieve data from {url} "
            f"due to auth {CENTINELA_CLAVE}", status=400))
        r = await self.t["sv_add_store_repository"](url, prev["confirmation_token"])
        self.assertIn("error", r)
        self.assertIn("Can't retrieve data", r["error"])
        self.assertSinCentinela(r)
        # El token quedó fallido: no vale para repetir.
        r2 = await self.t["sv_add_store_repository"](url, prev["confirmation_token"])
        self.assertIn("error", r2)
        self.assertEqual(len(self.sv.escrituras()), 1)

    async def test_token_de_otra_url(self) -> None:
        prev = await self.t["sv_add_store_repository"]("https://example.com/uno")
        self.sv.respuesta("POST", "/store/repositories", {})
        r = await self.t["sv_add_store_repository"]("https://example.com/dos",
                                                    prev["confirmation_token"])
        self.assertIn("does not match", r["error"])
        self.assertEqual(self.sv.escrituras(), [])

    async def test_error_al_leer_en_la_vista_previa(self) -> None:
        self.sv.respuesta("GET", "/store/repositories", HAConnectionError(
            f"boom {URL_CON_CLAVE}", status=500))
        r = await self.t["sv_add_store_repository"](URL_CON_CLAVE.replace("ficticio", "x"))
        self.assertIn("error", r)
        self.assertNotIn("confirmation_token", r)
        self.assertSinCentinela(r)


# ── Quitar (FR-003) ───────────────────────────────────────────────────────────


class TestQuitar(_Base):
    async def test_inexistente(self) -> None:
        r = await self.t["sv_remove_store_repository"]("ffff0000")
        self.assertEqual(r["error"], "repository_not_found")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras(), [])

    async def test_integrados(self) -> None:
        for slug in ("core", "local", "a0d7b954", "5c53de3b", "d5369777"):
            self.sv.respuesta("GET", f"/store/repositories/{slug}",
                              {"slug": slug, "name": "x", "source": slug,
                               "url": slug, "maintainer": "x"})
            with self.subTest(slug=slug):
                r = await self.t["sv_remove_store_repository"](slug)
                self.assertEqual(r["error"], "builtin_repository")
                self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras(), [])

    async def test_con_apps_instaladas_sin_token(self) -> None:
        self.sv.respuesta("GET", "/store/addons",
                          {"addons": apps_con_instalada("abcd1234_ejemplo")})
        r = await self.t["sv_remove_store_repository"]("abcd1234")
        self.assertEqual(r["error"], "repository_in_use")
        self.assertEqual(r["installed_apps"], [{"slug": "abcd1234_ejemplo", "name": "Ejemplo"}])
        self.assertIn("sv_uninstall_addon", r["detail"])
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras(), [])

    async def test_catalogo_que_falla_sin_token(self) -> None:
        # Sin saber qué apps están instaladas no se puede prometer nada.
        self.sv.respuesta("GET", "/store/addons", HAConnectionError("x", status=500))
        r = await self.t["sv_remove_store_repository"]("abcd1234")
        self.assertIn("error", r)
        self.assertNotIn("confirmation_token", r)

    async def test_vista_previa(self) -> None:
        r = await self.t["sv_remove_store_repository"]("abcd1234")
        p = r["preview"]
        self.assertEqual(p["action"], "remove_store_repository")
        self.assertEqual(p["repository"]["slug"], "abcd1234")
        self.assertEqual(p["apps_count"], 2)
        self.assertIn("no longer be installable", p["effect"])
        self.assertEqual(p["_third_party_text"]["fields"],
                         ["repository.name", "repository.url", "repository.maintainer"])
        self.assertSinCentinela(r)
        self.assertEqual(self.sv.escrituras(), [])

    async def test_confirmacion(self) -> None:
        prev = await self.t["sv_remove_store_repository"]("abcd1234")
        self.sv.respuesta("DELETE", "/store/repositories/abcd1234", {})
        r = await self.t["sv_remove_store_repository"]("abcd1234", prev["confirmation_token"])
        self.assertEqual(r, {"result": "ok", "repository": "abcd1234"})
        self.assertEqual([(c["metodo"], c["ruta"]) for c in self.sv.escrituras()],
                         [("DELETE", "/store/repositories/abcd1234")])

    async def test_cambio_entre_vista_previa_y_confirmacion(self) -> None:
        prev = await self.t["sv_remove_store_repository"]("abcd1234")
        # Entre medias, alguien instala una app del repositorio.
        self.sv.respuesta("GET", "/store/addons",
                          {"addons": apps_con_instalada("abcd1234_otra")})
        self.sv.respuesta("DELETE", "/store/repositories/abcd1234", {})
        r = await self.t["sv_remove_store_repository"]("abcd1234", prev["confirmation_token"])
        self.assertIn("error", r)
        self.assertIn("changed", r["error"])
        self.assertEqual(self.sv.escrituras(), [])

    async def test_error_del_supervisor_redactado(self) -> None:
        prev = await self.t["sv_remove_store_repository"]("abcd1234")
        self.sv.respuesta("DELETE", "/store/repositories/abcd1234", HAConnectionError(
            f"Can't remove '{URL_CON_CLAVE}'. It's used by installed apps", status=400))
        r = await self.t["sv_remove_store_repository"]("abcd1234", prev["confirmation_token"])
        self.assertIn("Can't remove", r["error"])
        self.assertSinCentinela(r)

    async def test_token_de_otro_repositorio(self) -> None:
        otro = {"slug": "ffff0002", "name": "Otro", "source": "https://example.com/o",
                "url": "https://example.com/o", "maintainer": "x"}
        self.sv.respuesta("GET", "/store/repositories/ffff0002", otro)
        prev = await self.t["sv_remove_store_repository"]("ffff0002")
        r = await self.t["sv_remove_store_repository"]("abcd1234", prev["confirmation_token"])
        self.assertIn("does not match", r["error"])
        self.assertEqual(self.sv.escrituras(), [])

    async def test_slug_invalido(self) -> None:
        r = await self.t["sv_remove_store_repository"]("../x")
        self.assertEqual(r["error"], "invalid_identifier")
        self.assertEqual(self.sv.llamadas, [])


# ── Reparar y recargar (FR-004, FR-005) ───────────────────────────────────────


class TestReparar(_Base):
    async def test_repara_sin_token(self) -> None:
        self.sv.respuesta("POST", "/store/repositories/abcd1234/repair", {})
        r = await self.t["sv_repair_store_repository"]("abcd1234")
        self.assertEqual(r, {"result": "ok", "repository": "abcd1234"})
        post = self.sv.escrituras()
        self.assertEqual([(c["metodo"], c["ruta"]) for c in post],
                         [("POST", "/store/repositories/abcd1234/repair")])
        self.assertEqual(post[0]["timeout"], _LONG_OP_TIMEOUT)

    async def test_local_no_se_repara(self) -> None:
        r = await self.t["sv_repair_store_repository"]("local")
        self.assertEqual(r["error"], "not_supported")
        self.assertEqual(self.sv.llamadas, [])

    async def test_inexistente_sin_post(self) -> None:
        r = await self.t["sv_repair_store_repository"]("ffff0000")
        self.assertEqual(r["error"], "repository_not_found")
        self.assertEqual(self.sv.escrituras(), [])

    async def test_error_redactado(self) -> None:
        self.sv.respuesta("POST", "/store/repositories/abcd1234/repair", HAConnectionError(
            f"Can't retrieve data from {URL_CON_CLAVE}", status=400))
        r = await self.t["sv_repair_store_repository"]("abcd1234")
        self.assertIn("error", r)
        self.assertSinCentinela(r)

    async def test_slug_invalido(self) -> None:
        r = await self.t["sv_repair_store_repository"]("a/b")
        self.assertEqual(r["error"], "invalid_identifier")
        self.assertEqual(self.sv.llamadas, [])


class TestRecargar(_Base):
    async def test_recarga(self) -> None:
        self.sv.respuesta("POST", "/store/reload", {})
        r = await self.t["sv_reload_store"]()
        self.assertEqual(r["result"], "ok")
        self.assertIn("sv_list_addons(installed_only=false)", r["hint"])
        post = self.sv.escrituras()
        self.assertEqual([(c["metodo"], c["ruta"], c["timeout"]) for c in post],
                         [("POST", "/store/reload", _LONG_OP_TIMEOUT)])

    async def test_error_redactado(self) -> None:
        self.sv.respuesta("POST", "/store/reload", HAConnectionError(
            f"failed 500: {URL_CON_CLAVE}", status=500))
        r = await self.t["sv_reload_store"]()
        self.assertIn("error", r)
        self.assertSinCentinela(r)


# ── Log (FR-018) ──────────────────────────────────────────────────────────────


class TestLog(_Base):
    def _eventos(self, logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [e for e in logs if e.get("event") == "app_store_action"]

    async def test_un_evento_por_llamada(self) -> None:
        self.sv.respuesta("POST", "/store/reload", {})
        self.sv.respuesta("POST", "/store/repositories/abcd1234/repair", {})
        with capture_logs() as logs:
            await self.t["sv_list_store_repositories"]()
            await self.t["sv_reload_store"]()
            await self.t["sv_repair_store_repository"]("abcd1234")
            await self.t["sv_remove_store_repository"]("abcd1234")
        eventos = self._eventos(logs)
        self.assertEqual(
            [(e["tool"], e["outcome"]) for e in eventos],
            [("sv_list_store_repositories", "ok"), ("sv_reload_store", "ok"),
             ("sv_repair_store_repository", "ok"),
             ("sv_remove_store_repository", "preview")])
        self.assertEqual(eventos[0]["count"], len(REPOSITORIOS))
        self.assertEqual(eventos[2]["repository"], "abcd1234")
        self.assertEqual(eventos[3]["repository"], "abcd1234")

    async def test_rechazo(self) -> None:
        with capture_logs() as logs:
            await self.t["sv_remove_store_repository"]("core")
            await self.t["sv_repair_store_repository"]("local")
            await self.t["sv_add_store_repository"]("ftp://example.com/x")
        self.assertEqual([e["outcome"] for e in self._eventos(logs)],
                         ["rejected:builtin_repository", "rejected:not_supported",
                          "rejected:invalid_argument"])

    async def test_evento_de_anadir_sin_url(self) -> None:
        url = f"https://usuario:{CENTINELA_CLAVE}@servidor-ficticio.example.com/nuevo"
        self.sv.respuesta("POST", "/store/repositories", {})
        with capture_logs() as logs:
            prev = await self.t["sv_add_store_repository"](url)
            await self.t["sv_add_store_repository"](url, prev["confirmation_token"])
            await self.t["sv_add_store_repository"](URL_CON_CLAVE)
        eventos = self._eventos(logs)
        self.assertEqual([e["outcome"] for e in eventos],
                         ["preview", "ok", "rejected:repository_already_added"])
        texto = json.dumps(logs, default=str)
        for prohibido in (CENTINELA_CLAVE, "servidor-ficticio", "example.com", "nuevo"):
            self.assertNotIn(prohibido, texto)
        for e in eventos:
            self.assertRegex(e.get("repository", ""), r"^[0-9a-z]+$")


class TestSinNombresDeApps(_Base):
    async def test_catalogo_de_la_fixture(self) -> None:
        # Comprobación de la fixture: cada app es de un repositorio listado.
        slugs = {r["slug"] for r in REPOSITORIOS}
        self.assertTrue(all(a["repository"] in slugs for a in APPS))


if __name__ == "__main__":
    unittest.main()
