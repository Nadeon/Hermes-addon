"""Fichas, disponibilidad y reconstrucción de apps de la tienda (spec 030,
tramo 2; T016–T018).

`sv_get_addon_changelog`, `sv_get_addon_documentation`,
`sv_get_addon_availability` y `sv_rebuild_addon` contra un Supervisor
simulado con la forma del 2026.11.0 (`tests/fixtures/supervisor_tienda.py`).
Se comprueba lo que Hermes pide (y lo que NO pide: un rechazo no llega a la
segunda lectura ni a la escritura), los trozos de texto, la redacción, el
token y el evento de log.

Controles negativos (T026, recuentos en `tasks.md`):
(a) no reconocer «No changelog found…» → cae `test_sin_changelog`;
(b) redactar por trozos en vez de sobre el texto entero → cae
    `test_trozos_y_centinela_en_el_corte`;
(c) emitir token en `rebuild_version_changed` o sin `force` en una app de
    imagen → caen `test_version_cambiada_sin_token` y
    `test_imagen_sin_force_sin_token`.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from structlog.testing import capture_logs

from hermes.ha import HAConnectionError
from hermes.tools.addons import _LONG_OP_TIMEOUT
from hermes.tools.marketplace import _THIRD_PARTY_WARNING
from hermes.tools.store_apps import register
from tests.fixtures.supervisor_tienda import (
    CENTINELA_DOC,
    LARGO_TEXTO,
    SupervisorSimulado,
    app_inexistente,
    error_400,
    ficha,
    no_changelog,
    no_documentacion,
    texto_largo,
)

_SLUG = "abcd1234_ejemplo"


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
        mcp = _MCP()
        register(mcp, self.sv, response_max_bytes=self.max_bytes)
        self.t = mcp.tools

    def ficha(self, slug: str = _SLUG, **campos: Any) -> dict[str, Any]:
        f = ficha(slug, **campos)
        self.sv.respuesta("GET", f"/store/addons/{slug}", f)
        return f

    def assertSin(self, valor: Any, *trozos: str) -> None:  # noqa: N802
        texto = json.dumps(valor, ensure_ascii=False)
        for trozo in trozos:
            self.assertNotIn(trozo, texto)


# ── Changelog (FR-006, FR-017, FR-018, FR-019) ────────────────────────────────


class TestChangelog(_Base):
    async def test_dos_lecturas_y_campos(self) -> None:
        self.ficha(name="Ejemplo", version_latest="2.0.0")
        self.sv.texto(f"/store/addons/{_SLUG}/changelog", "## 2.0.0\n- Cambio.\n")
        r = await self.t["sv_get_addon_changelog"](_SLUG)
        self.assertEqual(r["text"], "## 2.0.0\n- Cambio.\n")
        self.assertEqual((r["slug"], r["name"], r["version_latest"]),
                         (_SLUG, "Ejemplo", "2.0.0"))
        self.assertEqual((r["offset"], r["total_chars"], r["truncated"]),
                         (0, len("## 2.0.0\n- Cambio.\n"), False))
        self.assertNotIn("next_offset", r)
        self.assertIs(r["secrets_redacted"], False)
        self.assertEqual(r["_third_party_text"],
                         {"fields": ["name", "text"], "warning": _THIRD_PARTY_WARNING})
        self.assertEqual(self.sv.rutas(), [("GET", f"/store/addons/{_SLUG}"),
                                           ("GET", f"/store/addons/{_SLUG}/changelog")])
        self.assertEqual(self.sv.textos_pedidos(), [f"/store/addons/{_SLUG}/changelog"])

    async def test_ficha_inexistente_sin_pedir_el_texto(self) -> None:
        # 404 (lo que da el Supervisor 2026.11.0) y 400 (APIError genérico).
        for error in (None, error_400(f"/store/addons/{_SLUG}", "nope")):
            with self.subTest(error=error):
                self.sv = SupervisorSimulado()
                mcp = _MCP()
                register(mcp, self.sv)
                if error is not None:
                    self.sv.respuesta("GET", f"/store/addons/{_SLUG}", error)
                r = await mcp.tools["sv_get_addon_changelog"](_SLUG)
                self.assertEqual(r["error"], "addon_not_found")
                self.assertEqual(self.sv.textos_pedidos(), [])

    async def test_sin_changelog(self) -> None:
        self.ficha()
        self.sv.texto(f"/store/addons/{_SLUG}/changelog", no_changelog(_SLUG))
        r = await self.t["sv_get_addon_changelog"](_SLUG)
        self.assertEqual(r["error"], "changelog_not_found")
        self.assertNotIn("text", r)
        self.assertSin(r, "No changelog found")

    async def test_app_que_desaparece_con_200(self) -> None:
        self.ficha()
        self.sv.texto(f"/store/addons/{_SLUG}/changelog", app_inexistente(_SLUG))
        r = await self.t["sv_get_addon_changelog"](_SLUG)
        self.assertEqual(r["error"], "addon_not_found")

    async def test_trozos_y_centinela_en_el_corte(self) -> None:
        self.ficha()
        self.sv.texto(f"/store/addons/{_SLUG}/changelog", texto_largo())
        trozos = []
        for offset in (0, 20_000, 40_000):
            r = await self.t["sv_get_addon_changelog"](_SLUG, offset=offset)
            self.assertIs(r["secrets_redacted"], True)
            self.assertSin(r, CENTINELA_DOC)
            trozos.append(r)
        total = trozos[0]["total_chars"]
        self.assertLess(total, LARGO_TEXTO)  # el centinela se sustituyó entero
        self.assertEqual([len(t["text"]) for t in trozos[:2]], [20_000, 20_000])
        self.assertEqual([t.get("next_offset") for t in trozos], [20_000, 40_000, None])
        self.assertEqual([t["truncated"] for t in trozos], [True, True, False])
        self.assertEqual(sum(len(t["text"]) for t in trozos), total)
        # Cerca del final: lo que queda, sin `next_offset`.
        r = await self.t["sv_get_addon_changelog"](_SLUG, offset=total - 7)
        self.assertEqual((len(r["text"]), r["truncated"]), (7, False))
        self.assertNotIn("next_offset", r)

    async def test_offset_49990(self) -> None:
        self.ficha()
        self.sv.texto(f"/store/addons/{_SLUG}/changelog", texto_largo())
        r = await self.t["sv_get_addon_changelog"](_SLUG, offset=49_990)
        self.assertEqual(r["offset"], 49_990)
        self.assertEqual(len(r["text"]), max(0, r["total_chars"] - 49_990))
        self.assertIs(r["truncated"], False)

    async def test_offset_fuera_del_texto(self) -> None:
        self.ficha()
        self.sv.texto(f"/store/addons/{_SLUG}/changelog", "corto")
        r = await self.t["sv_get_addon_changelog"](_SLUG, offset=60_000)
        self.assertEqual((r["text"], r["truncated"], r["total_chars"]), ("", False, 5))
        self.assertNotIn("error", r)

    async def test_argumentos_invalidos_sin_llamada(self) -> None:
        for kwargs, campo in (({"offset": -1}, "offset"), ({"offset": True}, "offset"),
                              ({"offset": "3"}, "offset"), ({"max_chars": 0}, "max_chars"),
                              ({"max_chars": 100_001}, "max_chars"),
                              ({"max_chars": 2.5}, "max_chars")):
            with self.subTest(kwargs=kwargs):
                r = await self.t["sv_get_addon_changelog"](_SLUG, **kwargs)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", campo))
        r = await self.t["sv_get_addon_changelog"]("../x")
        self.assertEqual(r["error"], "invalid_identifier")
        self.assertEqual(self.sv.llamadas, [])

    async def test_max_chars(self) -> None:
        self.ficha()
        self.sv.texto(f"/store/addons/{_SLUG}/changelog", "abcdefghij")
        r = await self.t["sv_get_addon_changelog"](_SLUG, offset=2, max_chars=3)
        self.assertEqual((r["text"], r["next_offset"], r["truncated"]), ("cde", 5, True))

    async def test_error_del_supervisor_redactado(self) -> None:
        self.ficha()
        self.sv.texto(f"/store/addons/{_SLUG}/changelog", HAConnectionError(
            f"failed 500: password: {CENTINELA_DOC}", status=500))
        r = await self.t["sv_get_addon_changelog"](_SLUG)
        self.assertIn("error", r)
        self.assertSin(r, CENTINELA_DOC)

    async def test_la_ficha_tambien_se_redacta(self) -> None:
        self.ficha(name=f"Nombre password: {CENTINELA_DOC}")
        self.sv.texto(f"/store/addons/{_SLUG}/changelog", "x")
        self.assertSin(await self.t["sv_get_addon_changelog"](_SLUG), CENTINELA_DOC)


class TestChangelogRecortado(_Base):
    max_bytes = 4_000

    async def test_cabe_en_response_max_bytes(self) -> None:
        self.ficha()
        self.sv.texto(f"/store/addons/{_SLUG}/changelog", "á\"" * 30_000)
        r = await self.t["sv_get_addon_changelog"](_SLUG)
        tam = len(json.dumps(r, ensure_ascii=False).encode())
        self.assertLessEqual(tam, self.max_bytes)
        self.assertGreater(tam, self.max_bytes - 100)  # no se recorta de más
        self.assertIs(r["truncated"], True)
        self.assertEqual(r["next_offset"], len(r["text"]))


# ── Documentación (FR-007) ────────────────────────────────────────────────────


class TestDocumentacion(_Base):
    async def test_lee_la_documentacion(self) -> None:
        self.ficha()
        self.sv.texto(f"/store/addons/{_SLUG}/documentation", "# Docs\n")
        r = await self.t["sv_get_addon_documentation"](_SLUG)
        self.assertEqual(r["text"], "# Docs\n")
        self.assertEqual(self.sv.textos_pedidos(), [f"/store/addons/{_SLUG}/documentation"])

    async def test_ficha_sin_documentacion_no_pide_el_texto(self) -> None:
        self.ficha(documentation=False)
        r = await self.t["sv_get_addon_documentation"](_SLUG)
        self.assertEqual(r["error"], "documentation_not_found")
        self.assertEqual(self.sv.textos_pedidos(), [])

    async def test_texto_exacto_de_sin_documentacion(self) -> None:
        self.ficha()
        self.sv.texto(f"/store/addons/{_SLUG}/documentation", no_documentacion(_SLUG))
        r = await self.t["sv_get_addon_documentation"](_SLUG)
        self.assertEqual(r["error"], "documentation_not_found")

    async def test_centinela_en_la_documentacion(self) -> None:
        self.ficha()
        self.sv.texto(f"/store/addons/{_SLUG}/documentation", texto_largo())
        r = await self.t["sv_get_addon_documentation"](_SLUG, offset=19_995, max_chars=100)
        self.assertSin(r, CENTINELA_DOC, "centinela")
        self.assertIs(r["secrets_redacted"], True)


# ── Disponibilidad (FR-008) ───────────────────────────────────────────────────


class TestDisponibilidad(_Base):
    async def test_disponible(self) -> None:
        self.ficha(arch=["amd64"], build=True, repository="abcd1234")
        self.sv.respuesta("GET", f"/store/addons/{_SLUG}/availability", {})
        r = await self.t["sv_get_addon_availability"](_SLUG)
        self.assertIs(r["available"], True)
        self.assertIsNone(r["reason"])
        self.assertEqual((r["arch"], r["build"], r["repository"], r["version_latest"]),
                         (["amd64"], True, "abcd1234", "2.0.0"))
        for campo in ("installed", "version", "homeassistant", "stage", "advanced", "name"):
            self.assertIn(campo, r)
        self.assertEqual(r["_third_party_text"]["fields"], ["name"])

    async def test_no_disponible_con_motivo_redactado(self) -> None:
        self.ficha()
        mensaje = (f"App {_SLUG} not supported on this platform, supported "
                   f"architectures: armv7 password: {CENTINELA_DOC}")
        self.sv.respuesta("GET", f"/store/addons/{_SLUG}/availability",
                          error_400(f"/store/addons/{_SLUG}/availability", mensaje))
        r = await self.t["sv_get_addon_availability"](_SLUG)
        self.assertIs(r["available"], False)
        self.assertTrue(r["reason"].startswith(f"App {_SLUG} not supported on this platform"))
        self.assertSin(r, CENTINELA_DOC, "result")

    async def test_inexistente(self) -> None:
        r = await self.t["sv_get_addon_availability"](_SLUG)
        self.assertEqual(r["error"], "addon_not_found")
        self.assertEqual(self.sv.rutas(), [("GET", f"/store/addons/{_SLUG}")])

    async def test_error_que_no_es_400(self) -> None:
        self.ficha()
        self.sv.respuesta("GET", f"/store/addons/{_SLUG}/availability", HAConnectionError(
            f"failed 500: password: {CENTINELA_DOC}", status=500))
        r = await self.t["sv_get_addon_availability"](_SLUG)
        self.assertIn("error", r)
        self.assertNotIn("available", r)
        self.assertSin(r, CENTINELA_DOC)

    async def test_nunca_escribe(self) -> None:
        self.ficha()
        self.sv.respuesta("GET", f"/store/addons/{_SLUG}/availability", {})
        await self.t["sv_get_addon_availability"](_SLUG)
        await self.t["sv_get_addon_availability"]("ffff_otra")
        self.assertEqual(self.sv.escrituras(), [])


# ── Reconstruir (FR-012, FR-018) ──────────────────────────────────────────────

_LOCAL = "local_ejemplo"


def _info(**campos: Any) -> dict[str, Any]:
    base = {"slug": _LOCAL, "name": "Ejemplo local", "installed": True,
            "version": "1.0.0", "version_latest": "1.0.0", "detached": False,
            "build": True, "state": "started", "repository": "local",
            "options": {"password": "centinela-opcion"}}
    base.update(campos)
    return base


class TestReconstruir(_Base):
    def info(self, slug: str = _LOCAL, **campos: Any) -> None:
        self.sv.respuesta("GET", f"/addons/{slug}/info", _info(slug=slug, **campos))

    async def _sin_token(self, error: str, **kwargs: Any) -> dict[str, Any]:
        r = await self.t["sv_rebuild_addon"](_LOCAL, **kwargs)
        self.assertEqual(r.get("error"), error, r)
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras(), [])
        return r

    async def test_inexistente(self) -> None:
        await self._sin_token("addon_not_found")

    async def test_no_instalada(self) -> None:
        # El Supervisor responde con la ficha de la tienda.
        self.info(installed=False, version=None, state="unknown")
        await self._sin_token("addon_not_installed")

    async def test_desligada(self) -> None:
        self.info(detached=True)
        await self._sin_token("addon_not_in_store")

    async def test_version_cambiada_sin_token(self) -> None:
        self.info(version="1.0.0", version_latest="1.1.0")
        r = await self._sin_token("rebuild_version_changed")
        self.assertEqual((r["version"], r["version_latest"]), ("1.0.0", "1.1.0"))
        self.assertIn("sv_update_addon", r["detail"])

    async def test_imagen_sin_force_sin_token(self) -> None:
        self.info(build=False)
        r = await self._sin_token("rebuild_not_supported")
        self.assertIn("force=true", r["detail"])

    async def test_error_al_leer_sin_token(self) -> None:
        self.sv.respuesta("GET", f"/addons/{_LOCAL}/info",
                          HAConnectionError("failed 500: boom", status=500))
        r = await self.t["sv_rebuild_addon"](_LOCAL)
        self.assertIn("error", r)
        self.assertNotIn("confirmation_token", r)

    async def test_vista_previa_construida_en_local(self) -> None:
        self.info()
        r = await self.t["sv_rebuild_addon"](_LOCAL)
        p = r["preview"]
        self.assertEqual(p["action"], "rebuild_addon")
        self.assertEqual((p["slug"], p["name"], p["version"], p["state"], p["build"],
                          p["force"]), (_LOCAL, "Ejemplo local", "1.0.0", "started", True, False))
        self.assertIn("builds the image again locally", p["effect"])
        self.assertIn("/data", p["keeps"])
        self.assertIn("without an image", p["on_failure"])
        self.assertIn("previous state", p["state_after"])
        self.assertEqual(p["_third_party_text"]["fields"], ["name"])
        self.assertNotIn("critical_warning", p)
        self.assertIn("confirmation_token", r)
        self.assertSin(r, "centinela-opcion")
        self.assertEqual(self.sv.escrituras(), [])

    async def test_vista_previa_con_force_sobre_imagen(self) -> None:
        self.info(build=False)
        r = await self.t["sv_rebuild_addon"](_LOCAL, force=True)
        self.assertIn("downloads the same version of the image again", r["preview"]["effect"])
        self.assertIs(r["preview"]["force"], True)

    async def test_hermes_lleva_el_aviso(self) -> None:
        self.info(slug="local_hermes")
        r = await self.t["sv_rebuild_addon"]("local_hermes")
        self.assertIn("Hermes itself", r["preview"]["critical_warning"])
        self.assertIn("confirmation_token", r)

    async def test_aviso_por_el_slug_exacto(self) -> None:
        """D-13 (cierre de seguridad, remate): con el slug propio de
        `/addons/self/info`, reconstruir otra app `<x>_hermes` no avisa de que
        se reconstruye Hermes; el propio, sí. Sin poder leerlo, el sufijo
        (test de arriba: el simulado no tiene `/addons/self/info`).

        Control negativo comprobado: volver a `_self_warning(slug, …)` sin
        `es_hermes` → cae (avisa por `e5f6a7b8_hermes`)."""
        self.sv.respuesta("GET", "/addons/self/info", {"slug": "a1b2c3d4_hermes"})
        for slug, avisa in (("e5f6a7b8_hermes", False), ("a1b2c3d4_hermes", True)):
            with self.subTest(slug=slug):
                self.info(slug=slug)
                r = await self.t["sv_rebuild_addon"](slug)
                self.assertEqual("critical_warning" in r["preview"], avisa, r)
                self.assertIn("confirmation_token", r)

    async def test_confirmacion(self) -> None:
        for force, build in ((False, True), (True, False)):
            with self.subTest(force=force):
                self.sv = SupervisorSimulado()
                mcp = _MCP()
                register(mcp, self.sv)
                self.sv.respuesta("GET", f"/addons/{_LOCAL}/info", _info(build=build))
                self.sv.respuesta("POST", f"/addons/{_LOCAL}/rebuild", {})
                prev = await mcp.tools["sv_rebuild_addon"](_LOCAL, force=force)
                r = await mcp.tools["sv_rebuild_addon"](
                    _LOCAL, force=force, confirmation_token=prev["confirmation_token"])
                self.assertEqual(r, {"result": "ok", "slug": _LOCAL, "force": force})
                [post] = self.sv.escrituras()
                self.assertEqual((post["ruta"], post["json"], post["timeout"]),
                                 (f"/addons/{_LOCAL}/rebuild", {"force": force},
                                  _LONG_OP_TIMEOUT))

    async def test_force_distinto_al_confirmar(self) -> None:
        self.info(build=True)
        self.sv.respuesta("POST", f"/addons/{_LOCAL}/rebuild", {})
        prev = await self.t["sv_rebuild_addon"](_LOCAL, force=False)
        r = await self.t["sv_rebuild_addon"](_LOCAL, force=True,
                                             confirmation_token=prev["confirmation_token"])
        self.assertIn("does not match", r["error"])
        self.assertEqual(self.sv.escrituras(), [])

    async def test_error_del_supervisor(self) -> None:
        self.info()
        prev = await self.t["sv_rebuild_addon"](_LOCAL)
        self.sv.respuesta("POST", f"/addons/{_LOCAL}/rebuild", HAConnectionError(
            "failed 500: build failed password: centinela-build", status=500))
        r = await self.t["sv_rebuild_addon"](_LOCAL, confirmation_token=prev["confirmation_token"])
        self.assertIn("build failed", r["error"])
        self.assertIn("sv_get_addon", r["hint"])
        self.assertSin(r, "centinela-build")
        # El token quedó fallido: no vale para repetir.
        r2 = await self.t["sv_rebuild_addon"](_LOCAL, confirmation_token=prev["confirmation_token"])
        self.assertIn("error", r2)
        self.assertEqual(len(self.sv.escrituras()), 1)

    async def test_force_que_no_es_booleano(self) -> None:
        r = await self.t["sv_rebuild_addon"](_LOCAL, force="yes")
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "force"))
        self.assertEqual(self.sv.llamadas, [])


# ── Log (FR-018) ──────────────────────────────────────────────────────────────


class TestLog(_Base):
    async def test_eventos_sin_textos_ni_opciones(self) -> None:
        self.ficha()
        self.sv.texto(f"/store/addons/{_SLUG}/changelog", f"texto-secreto password: {CENTINELA_DOC}")
        self.sv.respuesta("GET", f"/store/addons/{_SLUG}/availability", {})
        self.sv.respuesta("GET", f"/addons/{_LOCAL}/info", _info())
        self.sv.respuesta("POST", f"/addons/{_LOCAL}/rebuild", {})
        with capture_logs() as logs:
            await self.t["sv_get_addon_changelog"](_SLUG)
            await self.t["sv_get_addon_availability"](_SLUG)
            prev = await self.t["sv_rebuild_addon"](_LOCAL)
            await self.t["sv_rebuild_addon"](_LOCAL, confirmation_token=prev["confirmation_token"])
            await self.t["sv_get_addon_documentation"]("ffff_otra")
        eventos = [e for e in logs if e.get("event") == "app_store_action"]
        self.assertEqual(
            [(e["tool"], e["outcome"], e["slug"]) for e in eventos],
            [("sv_get_addon_changelog", "ok", _SLUG),
             ("sv_get_addon_availability", "ok", _SLUG),
             ("sv_rebuild_addon", "preview", _LOCAL),
             ("sv_rebuild_addon", "ok", _LOCAL),
             ("sv_get_addon_documentation", "rejected:addon_not_found", "ffff_otra")])
        self.assertGreater(eventos[0]["bytes"], 0)
        texto = json.dumps(logs, default=str)
        for prohibido in (CENTINELA_DOC, "texto-secreto", "centinela-opcion"):
            self.assertNotIn(prohibido, texto)


if __name__ == "__main__":
    unittest.main()
