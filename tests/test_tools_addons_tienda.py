"""Vistas previas de la tienda en tres tools de la 1.1.2 (spec 030, tramo 2;
T019): `sv_install_addon`, `sv_update_addon` y `sv_set_addon_options`.

Ganan comprobaciones y campos en la vista previa; ningún argumento nuevo y,
con un token válido, la MISMA petición que en la 1.1.2 (SC-005). Contra el
Supervisor simulado de `tests/fixtures/supervisor_tienda.py`.

Controles negativos (T026, recuentos en `tasks.md`):
(d) no validar opciones en la vista previa → caen los de `invalid_options`;
(e) no quitar el secreto literal del mensaje de validación → cae
    `test_invalidas_sin_token_y_sin_el_secreto`;
(f) cambiar la petición de `sv_install_addon` con token (sin `background`)
    → cae `test_confirmacion_identica_a_la_1_1_2` de `TestInstalar`;
extra a) emitir token cuando no hay actualización → cae
    `test_sin_actualizacion_sin_token`.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from hermes.ha import HAConnectionError
from hermes.security import create_confirmation_token
from hermes.tools.addons import _LONG_OP_TIMEOUT, register
from hermes.tools.marketplace import _THIRD_PARTY_WARNING
from tests.fixtures.supervisor_tienda import (
    CENTINELA_DOC,
    CENTINELA_OPCION,
    SupervisorSimulado,
    error_400,
    ficha,
    no_changelog,
)

_SLUG = "abcd1234_ejemplo"
_CORE = "core_ejemplo"


class _MCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sv = SupervisorSimulado()
        mcp = _MCP()
        register(mcp, self.sv)
        self.t = mcp.tools

    def assertSin(self, valor: Any, *trozos: str) -> None:  # noqa: N802
        texto = json.dumps(valor, ensure_ascii=False)
        for trozo in trozos:
            self.assertNotIn(trozo, texto)


# ── Instalar (FR-009) ─────────────────────────────────────────────────────────


class TestInstalar(_Base):
    def tienda(self, slug: str = _SLUG, disponible: Any = True, **campos: Any) -> None:
        self.sv.respuesta("GET", f"/store/addons/{slug}", ficha(slug, **campos))
        ruta = f"/store/addons/{slug}/availability"
        self.sv.respuesta("GET", ruta, {} if disponible is True else disponible)

    async def _sin_token(self, error: str) -> dict[str, Any]:
        r = await self.t["sv_install_addon"](_SLUG)
        self.assertEqual(r.get("error"), error, r)
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras(), [])
        return r

    async def test_no_esta_en_la_tienda(self) -> None:
        await self._sin_token("addon_not_found")

    async def test_ya_instalada(self) -> None:
        self.tienda(installed=True, version="2.0.0")
        r = await self._sin_token("already_installed")
        self.assertIn("sv_update_addon", r["detail"])

    async def test_no_disponible_con_motivo(self) -> None:
        motivo = f"App {_SLUG} not supported on this platform, supported architectures: armv7"
        self.tienda(disponible=error_400(f"/store/addons/{_SLUG}/availability", motivo))
        r = await self._sin_token("addon_not_available")
        self.assertEqual(r["reason"], motivo)

    async def test_vista_previa_de_terceros(self) -> None:
        self.tienda(name="Ejemplo", version_latest="2.0.0", build=True)
        r = await self.t["sv_install_addon"](_SLUG)
        p = r["preview"]
        # Los campos de la 1.1.2 siguen.
        self.assertEqual((p["slug"], p["action"]), (_SLUG, "install"))
        self.assertIn("note", p)
        self.assertEqual((p["name"], p["version_latest"], p["repository"], p["build"]),
                         ("Ejemplo", "2.0.0", "abcd1234", True))
        self.assertIs(p["third_party_repository"], True)
        self.assertIn("third-party", p["warning"])
        self.assertEqual(p["_third_party_text"],
                         {"fields": ["name"], "warning": _THIRD_PARTY_WARNING})
        self.assertIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras(), [])

    async def test_vista_previa_de_un_repositorio_integrado(self) -> None:
        self.tienda(_CORE, repository="core")
        r = await self.t["sv_install_addon"](_CORE)
        self.assertNotIn("third_party_repository", r["preview"])
        self.assertNotIn("warning", r["preview"])

    async def test_tienda_que_no_responde_deja_el_token(self) -> None:
        # Como en la 1.1.2: el Supervisor vuelve a comprobar al instalar.
        self.sv.respuesta("GET", f"/store/addons/{_SLUG}",
                          HAConnectionError("failed 500: boom", status=500))
        r = await self.t["sv_install_addon"](_SLUG)
        self.assertIn("confirmation_token", r)
        self.assertIs(r["preview"]["store_check"]["checked"], False)

    async def test_confirmacion_identica_a_la_1_1_2(self) -> None:
        self.tienda()
        prev = await self.t["sv_install_addon"](_SLUG)
        self.sv.respuesta("POST", f"/store/addons/{_SLUG}/install", {"job_id": "abc123"})
        n = len(self.sv.llamadas)
        r = await self.t["sv_install_addon"](_SLUG, confirmation_token=prev["confirmation_token"])
        self.assertEqual(r["job_id"], "abc123")
        # La misma petición que en la 1.1.2. Antes, solo se relee la ficha
        # para comprobar la versión atada al token (T031); la disponibilidad
        # no se vuelve a pedir.
        [ficha_, post] = self.sv.llamadas[n:]
        self.assertEqual((ficha_["metodo"], ficha_["ruta"]), ("GET", f"/store/addons/{_SLUG}"))
        self.assertEqual((post["metodo"], post["ruta"], post["json"], post["timeout"]),
                         ("POST", f"/store/addons/{_SLUG}/install", {"background": True},
                          _LONG_OP_TIMEOUT))


# ── Actualizar (FR-010 y extra a del supervisor) ──────────────────────────────


class TestActualizar(_Base):
    def info(self, slug: str = _SLUG, **campos: Any) -> None:
        base = {"slug": slug, "version": "1.0.0", "version_latest": "2.0.0",
                "update_available": True, "detached": False}
        base.update(campos)
        self.sv.respuesta("GET", f"/addons/{slug}/info", base)

    async def test_vista_previa_con_changelog_y_disponibilidad(self) -> None:
        self.info()
        self.sv.respuesta("GET", f"/store/addons/{_SLUG}/availability", {})
        changelog = f"## 2.0.0\npassword: {CENTINELA_DOC}\n" + "x" * 6000
        self.sv.texto(f"/store/addons/{_SLUG}/changelog", changelog)
        r = await self.t["sv_update_addon"](_SLUG)
        p = r["preview"]
        # Los campos de la 1.1.2 siguen.
        self.assertEqual((p["current_version"], p["version_latest"], p["update_available"]),
                         ("1.0.0", "2.0.0", True))
        self.assertEqual((p["available"], p["reason"]), (True, None))
        self.assertTrue(p["changelog_excerpt"].startswith("## 2.0.0"))
        self.assertEqual(len(p["changelog_excerpt"]), 4000)
        self.assertIs(p["changelog_truncated"], True)
        self.assertEqual(p["_third_party_text"]["fields"], ["changelog_excerpt"])
        self.assertSin(r, CENTINELA_DOC)
        self.assertIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras(), [])

    async def test_changelog_que_falla_no_impide_el_token(self) -> None:
        self.info()
        self.sv.texto(f"/store/addons/{_SLUG}/changelog",
                      HAConnectionError(f"failed 500: password: {CENTINELA_DOC}", status=500))
        r = await self.t["sv_update_addon"](_SLUG)
        self.assertIsNone(r["preview"]["changelog_excerpt"])
        self.assertIn("changelog_unavailable", r["preview"])
        self.assertIn("confirmation_token", r)
        self.assertSin(r, CENTINELA_DOC)

    async def test_sin_changelog(self) -> None:
        self.info()
        self.sv.texto(f"/store/addons/{_SLUG}/changelog", no_changelog(_SLUG))
        r = await self.t["sv_update_addon"](_SLUG)
        self.assertIsNone(r["preview"]["changelog_excerpt"])
        self.assertSin(r, "No changelog found")
        self.assertIn("confirmation_token", r)

    async def test_no_disponible_se_dice(self) -> None:
        self.info()
        motivo = "App requires Home Assistant 2099.1.0"
        self.sv.respuesta("GET", f"/store/addons/{_SLUG}/availability",
                          error_400(f"/store/addons/{_SLUG}/availability", motivo))
        r = await self.t["sv_update_addon"](_SLUG)
        self.assertEqual((r["preview"]["available"], r["preview"]["reason"]), (False, motivo))

    async def test_sin_actualizacion_sin_token(self) -> None:
        # Extra a: nada que confirmar; dice la versión instalada.
        self.info(version="2.0.0", version_latest="2.0.0", update_available=False)
        r = await self.t["sv_update_addon"](_SLUG)
        self.assertEqual(r["error"], "already_up_to_date")
        self.assertEqual(r["version"], "2.0.0")
        self.assertNotIn("confirmation_token", r)
        # Solo la lectura de la ficha instalada: ni changelog ni disponibilidad.
        self.assertEqual(self.sv.rutas(), [("GET", f"/addons/{_SLUG}/info")])

    async def test_sin_poder_leer_la_ficha_sigue_como_en_la_1_1_2(self) -> None:
        self.sv.respuesta("GET", f"/addons/{_SLUG}/info",
                          HAConnectionError("failed 500: boom", status=500))
        r = await self.t["sv_update_addon"](_SLUG)
        self.assertIn("confirmation_token", r)
        self.assertIsNone(r["preview"]["current_version"])

    async def test_hermes_sin_ninguna_llamada(self) -> None:
        r = await self.t["sv_update_addon"]("local_hermes")
        self.assertEqual(r["error"], "self_update_not_supported")
        # D-13 (cierre de seguridad): solo la lectura del slug propio.
        self.assertEqual([c for c in self.sv.llamadas
                          if (c["metodo"], c["ruta"]) != ("GET", "/addons/self/info")], [])

    async def test_confirmacion_identica_a_la_1_1_2(self) -> None:
        self.info()
        prev = await self.t["sv_update_addon"](_SLUG)
        self.sv.respuesta("POST", f"/store/addons/{_SLUG}/update", {"job_id": "def456"})
        n = len(self.sv.llamadas)
        r = await self.t["sv_update_addon"](_SLUG, confirmation_token=prev["confirmation_token"])
        self.assertEqual(r["job_id"], "def456")
        # La misma petición que en la 1.1.2, precedida de la relectura de la
        # versión atada al token (T031) y, desde la convergencia 2 de la 034
        # (T053), de los privilegios (la ficha de la tienda): solo lecturas.
        *lecturas, post = self.sv.llamadas[n:]
        self.assertEqual([(c["metodo"], c["ruta"]) for c in lecturas],
                         [("GET", f"/addons/{_SLUG}/info"), ("GET", f"/store/addons/{_SLUG}")])
        self.assertEqual((post["metodo"], post["ruta"], post["json"], post["timeout"]),
                         ("POST", f"/store/addons/{_SLUG}/update", {"background": True},
                          _LONG_OP_TIMEOUT))

    async def test_un_token_sin_version_ya_no_vale(self) -> None:
        # Convergencia (T031): un token emitido sin la versión atada (el de
        # una vista previa de la 1.1.2) no dice qué versión se vio, así que
        # ya no vale: `preview_outdated` y nada se envía. Los argumentos son
        # los mismos; basta con pedir otra vista previa.
        self.info()
        tok = await create_confirmation_token("sv_update_addon", {"slug": _SLUG},
                                              preview={"slug": _SLUG})
        self.sv.respuesta("POST", f"/store/addons/{_SLUG}/update", {})
        r = await self.t["sv_update_addon"](_SLUG, confirmation_token=tok["confirmation_token"])
        self.assertIs(r.get("preview_outdated"), True, r)
        self.assertEqual(self.sv.escrituras(), [])


# ── Validar opciones (FR-013) ─────────────────────────────────────────────────


class TestValidarOpciones(_Base):
    _ACTUALES = {"a": 1, "password": CENTINELA_OPCION, "mqtt": {"user": "u"}}

    def setUp(self) -> None:
        super().setUp()
        self.sv.respuesta("GET", f"/addons/{_SLUG}/info", {"options": self._ACTUALES})
        self.validar = f"/addons/{_SLUG}/options/validate"

    def validacion(self, valor: Any) -> None:
        self.sv.respuesta("POST", self.validar, valor)

    def _validaciones(self) -> list[dict[str, Any]]:
        return [c for c in self.sv.llamadas if c["ruta"] == self.validar]

    async def test_valida_las_opciones_finales_sin_envolver(self) -> None:
        self.validacion({"message": "", "valid": True, "pwned": False})
        r = await self.t["sv_set_addon_options"](_SLUG, '{"a": 2}')
        self.assertEqual(r["preview"]["validation"],
                         {"checked": True, "valid": True, "pwned": False})
        [v] = self._validaciones()
        self.assertEqual((v["metodo"], v["json"]),
                         ("POST", {**self._ACTUALES, "a": 2}))
        self.assertIn("confirmation_token", r)
        self.assertSin(r, CENTINELA_OPCION)

    async def test_invalidas_sin_token_y_sin_el_secreto(self) -> None:
        self.validacion({
            "valid": False, "pwned": False,
            "message": (f"expected int for dictionary value @ data['password']. "
                        f"Got '{CENTINELA_OPCION}'"),
        })
        r = await self.t["sv_set_addon_options"](_SLUG, '{"a": "dos"}')
        self.assertEqual(r["error"], "invalid_options")
        self.assertIn("expected int", r["message"])
        # Desde la convergencia (T029) no sale nada desde «Got».
        self.assertIn("values not shown", r["message"])
        self.assertEqual(r["changed_paths"], ["a"])
        self.assertNotIn("confirmation_token", r)
        self.assertSin(r, CENTINELA_OPCION)
        self.assertFalse(any(c["ruta"] == f"/addons/{_SLUG}/options"
                             for c in self.sv.escrituras()))

    async def test_pwned(self) -> None:
        self.validacion({"message": "", "valid": True, "pwned": True})
        r = await self.t["sv_set_addon_options"](_SLUG, '{"a": 2}')
        self.assertIn("Have I Been Pwned", r["preview"]["warning_pwned"])
        self.assertIn("confirmation_token", r)

    async def test_pwned_sin_comprobar(self) -> None:
        self.validacion({"message": "", "valid": True, "pwned": None})
        r = await self.t["sv_set_addon_options"](_SLUG, '{"a": 2}')
        self.assertEqual(r["preview"]["pwned_check"], "failed")
        self.assertIsNone(r["preview"]["validation"]["pwned"])

    async def test_error_al_validar_deja_el_token(self) -> None:
        self.validacion(HAConnectionError(
            f"failed 500: boom con {CENTINELA_OPCION}", status=500))
        r = await self.t["sv_set_addon_options"](_SLUG, '{"a": 2}')
        self.assertIs(r["preview"]["validation"]["checked"], False)
        self.assertIn("boom", r["preview"]["validation"]["reason"])
        self.assertIn("confirmation_token", r)
        self.assertSin(r, CENTINELA_OPCION)

    async def test_opciones_finales_vacias_no_se_validan(self) -> None:
        self.sv.respuesta("GET", f"/addons/{_SLUG}/info", {"options": {"a": 1}})
        r = await self.t["sv_set_addon_options"](_SLUG, '{"a": null}')
        self.assertEqual(r["preview"]["validation"],
                         {"checked": False, "reason": "empty_options"})
        self.assertEqual(self._validaciones(), [])
        self.assertIn("confirmation_token", r)

    async def test_confirmacion_identica_a_la_1_1_2(self) -> None:
        self.validacion({"message": "", "valid": True, "pwned": False})
        prev = await self.t["sv_set_addon_options"](_SLUG, '{"a": 2}')
        self.sv.respuesta("POST", f"/addons/{_SLUG}/options", {})
        n = len(self.sv.llamadas)
        r = await self.t["sv_set_addon_options"](
            _SLUG, '{"a": 2}', confirmation_token=prev["confirmation_token"])
        self.assertEqual(r, {"result": "ok", "slug": _SLUG})
        # Relee las actuales y envía; no vuelve a validar.
        self.assertEqual(
            [(c["metodo"], c["ruta"]) for c in self.sv.llamadas[n:]],
            [("GET", f"/addons/{_SLUG}/info"), ("POST", f"/addons/{_SLUG}/options")])
        self.assertEqual(self.sv.llamadas[-1]["json"],
                         {"options": {**self._ACTUALES, "a": 2}})


# ── Sin versión concreta y descripciones (FR-011, FR-021; SC-005) ─────────────


class TestSinVersion(unittest.TestCase):
    def test_esquemas_de_la_1_1_2(self) -> None:
        import pathlib

        from tests.test_tools_registration import _real_registry

        ruta = pathlib.Path(__file__).resolve().parent / "fixtures" / "esquemas_1_1_2.json"
        esperado = json.loads(ruta.read_text(encoding="utf-8"))
        tools = _real_registry()
        for nombre in ("sv_install_addon", "sv_update_addon", "sv_set_addon_options"):
            with self.subTest(nombre=nombre):
                params = tools[nombre].parameters
                self.assertEqual(
                    {"properties": sorted(params.get("properties", {})),
                     "required": sorted(params.get("required", []))},
                    esperado[nombre])
                self.assertNotIn("version", params.get("properties", {}))


class TestDescripciones(_Base):
    def test_instalar_y_actualizar_dicen_la_version_de_la_tienda(self) -> None:
        for nombre in ("sv_install_addon", "sv_update_addon"):
            with self.subTest(nombre=nombre):
                doc = " ".join(self.t[nombre].__doc__.split())
                self.assertIn("app (add-on)", doc)
                self.assertIn("versión que ofrece la tienda", doc)
                self.assertIn("no se puede elegir otra", doc)

    def test_opciones_dice_que_valida(self) -> None:
        doc = self.t["sv_set_addon_options"].__doc__
        self.assertIn("app (add-on)", doc)
        self.assertIn("invalid_options", doc)

    def test_actualizar_dice_ya_al_dia(self) -> None:
        self.assertIn("already_up_to_date", self.t["sv_update_addon"].__doc__)


if __name__ == "__main__":
    unittest.main()
