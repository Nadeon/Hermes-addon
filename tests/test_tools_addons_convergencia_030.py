"""Convergencia de la 030 (T029-T032, T035): fugas de opciones por el texto
del Supervisor y versión atada al token en instalar y actualizar.

Contra el Supervisor simulado de `tests/fixtures/supervisor_tienda.py`, con
los mensajes construidos como los construye el Supervisor 2026.11.0:
`humanize_error(options, ex)` con el `vol.Invalid` en la RAÍZ añade «. Got
<repr() de TODAS las opciones>», cortado a 497 caracteres + `...`
(`api/apps.py`, `apps/options.py`); y el guardado rechazado lanza
`AppConfigurationInvalidError` («App … has invalid options: …», con
`validation_error` en `extra_fields`).

Controles negativos (comprobados al escribirlos; recuentos en el commit):
(a) no cortar en «Got» en `_texto_sin_eco` → caen los de
    `TestFugaPorElMensaje` con corte y escapes;
(b) devolver y guardar `str(exc)` al fallar el guardado (como la 1.1.2) →
    cae `TestErrorAlGuardar`;
(c) emitir el token sin `estado` en `sv_update_addon` / `sv_install_addon`
    → caen los de la carrera de `TestVersionAtada`;
(d) volver a `already_up_to_date` sin mirar `detached` → cae
    `test_desligada_no_dice_que_esta_al_dia`;
(e) quitar la nota de `store_check` → cae
    `test_tienda_ilegible_dice_lo_que_no_se_sabe`.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from structlog.testing import capture_logs

from hermes import security
from hermes.ha import HAConnectionError
from hermes.tools.addons import _texto_sin_eco, register
from tests.fixtures.supervisor_tienda import SupervisorSimulado, ficha

_SLUG = "abcd1234_ejemplo"
_SECRETO = "Xq7-centinela-de-prueba-9Lm2"


class _MCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def humanize(opciones: dict[str, Any], error: str) -> str:
    """`humanize_error` de voluptuous con el error en la raíz, como el
    Supervisor 2026.11.0: el repr() de todas las opciones, cortado a 500."""
    got = repr(opciones)
    if len(got) > 500:
        got = got[:497] + "..."
    return f"{error}. Got {got}"


def error_al_guardar(slug: str, opciones: dict[str, Any]) -> HAConnectionError:
    """El 400 de `POST /addons/{slug}/options` con opciones inválidas."""
    validacion = humanize(opciones, f"Type error for option 'port' in Ejemplo ({slug})")
    cuerpo = json.dumps({
        "result": "error",
        "message": f"App {slug} has invalid options: {validacion}",
        "error_key": "app_configuration_invalid_error",
        "extra_fields": {"app": slug, "validation_error": validacion},
    })
    return HAConnectionError(
        f"Supervisor REST POST http://supervisor/addons/{slug}/options failed 400: {cuerpo}",
        status=400)


def trozos(secreto: str, largo: int = 6) -> list[str]:
    """Todos los trozos de `largo` caracteres del secreto y de sus formas
    escapadas: si aparece cualquiera, se ha colado algo."""
    formas = {secreto, repr(secreto)[1:-1], json.dumps(secreto)[1:-1],
              json.dumps(repr(secreto)[1:-1])[1:-1]}
    out = []
    for f in formas:
        out += [f[i:i + largo] for i in range(len(f) - largo + 1)]
    return out


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sv = SupervisorSimulado()
        mcp = _MCP()
        register(mcp, self.sv)
        self.t = mcp.tools

    def assertSinSecreto(self, valor: Any, secreto: str = _SECRETO) -> None:  # noqa: N802
        for texto in (json.dumps(valor, ensure_ascii=False), json.dumps(valor),
                      valor if isinstance(valor, str) else ""):
            self.assertNotIn(secreto, texto)
            self.assertNotIn(secreto[:-1], texto)
            for trozo in trozos(secreto):
                self.assertNotIn(trozo, texto)


# ── T029: la vista previa de sv_set_addon_options ─────────────────────────────


class TestFugaPorElMensaje(_Base):
    _ACTUALES = {"log_level": "info", "banner": "hola", "auth_password": _SECRETO,
                 "port": 8080}

    def setUp(self) -> None:
        super().setUp()
        self.sv.respuesta("GET", f"/addons/{_SLUG}/info", {"options": self._ACTUALES})

    async def _invalidas(self, cambios: dict[str, Any], mensaje: str) -> dict[str, Any]:
        self.sv.respuesta("POST", f"/addons/{_SLUG}/options/validate",
                          {"valid": False, "pwned": False, "message": mensaje})
        r = await self.t["sv_set_addon_options"](_SLUG, json.dumps(cambios))
        self.assertEqual(r.get("error"), "invalid_options", r)
        self.assertNotIn("confirmation_token", r)
        return r

    async def test_corte_dentro_del_secreto(self) -> None:
        # El escenario de la revisión: se alarga `banner` para que el corte de
        # voluptuous caiga en cualquier punto del secreto, y se invalida
        # `port` para que el Supervisor responda con el mensaje.
        base = repr({**self._ACTUALES, "banner": ""}).index(_SECRETO)
        for k in range(1, len(_SECRETO) + 1):
            with self.subTest(k=k):
                cambios = {"banner": "b" * (497 - base - k), "port": "no-es-un-numero"}
                mensaje = humanize({**self._ACTUALES, **cambios},
                                   f"Type error for option 'port' in Ejemplo ({_SLUG})")
                # El escenario es el de la revisión: el secreto está cortado.
                self.assertIn(_SECRETO[:k], mensaje)
                r = await self._invalidas(cambios, mensaje)
                self.assertSinSecreto(r)
                self.assertIn("Type error for option 'port'", r["message"])
                # Nada desde «Got»: ni siquiera las claves de las opciones.
                self.assertNotIn("Got", r["message"])
                self.assertNotIn("'banner'", r["message"])

    async def test_escapes(self) -> None:
        secretos = {
            "barra": "ab\\cd-SECRETO-barra-1",
            "salto": "-----BEGIN PRIVATE KEY-----\nMIIEvSECRETOsalto2\n-----END PRIVATE KEY-----",
            "comillas": "it's\"SECRETO-comillas-3",
        }
        for nombre, secreto in secretos.items():
            with self.subTest(nombre=nombre):
                actuales = {"a": "x", "password": secreto}
                self.sv.respuesta("GET", f"/addons/{_SLUG}/info", {"options": actuales})
                mensaje = humanize({**actuales, "b": None},
                                   f"Missing required option 'b' in Ejemplo ({_SLUG})")
                r = await self._invalidas({"b": None}, mensaje)
                self.assertSinSecreto(r, secreto)

    def test_ecos_fuera_de_got(self) -> None:
        # Sin «Got»: el valor entero o escapado en cualquier punto, y cortado
        # al final (un cuerpo HTTP recortado por otro).
        for secreto in ("ab\\cd-SECRETO-barra-1", "it's\"SECRETO-comillas-3",
                        "linea1\nSECRETO-salto-linea2", _SECRETO):
            opciones = {"password": secreto}
            escapado = repr(secreto)[1:-1]
            casos = [
                f"boom {secreto} y más",
                f"boom {escapado} y más",
                f"boom {json.dumps(secreto)} y más",
                f"boom: {escapado[:-1]}",
                f"boom: {secreto[:-1]}...",
            ]
            for caso in casos:
                with self.subTest(caso=caso):
                    self.assertSinSecreto(_texto_sin_eco(caso, opciones), secreto)

    def test_todas_las_opciones_no_solo_las_secretas(self) -> None:
        out = _texto_sin_eco("valor raro mi-servidor-mqtt aquí",
                                    {"host": "mi-servidor-mqtt"})
        self.assertNotIn("mi-servidor-mqtt", out)

    def test_si_queda_un_trozo_mensaje_generico(self) -> None:
        # Un trozo de en medio del secreto que ninguna forma reconoce: no se
        # arriesga nada y solo salen las claves que fallan.
        opciones = {"password": _SECRETO, "port": "x"}
        mensaje = (f"Type error for option 'port' in Ejemplo ({_SLUG}) cerca de "
                   f"{_SECRETO[3:20]}")
        out = _texto_sin_eco(mensaje, opciones)
        self.assertSinSecreto(out)
        self.assertIn("data['port']", out)
        self.assertNotIn("Ejemplo", out)

    def test_el_generico_no_inventa_claves(self) -> None:
        opciones = {"password": _SECRETO}
        out = _texto_sin_eco(f"option 'no-es-clave' {_SECRETO[2:15]}", opciones)
        self.assertNotIn("no-es-clave", out)
        self.assertSinSecreto(out)

    async def test_error_al_validar_tambien(self) -> None:
        # `validation.reason` (la validación no se pudo hacer): misma limpieza.
        base = repr({**self._ACTUALES, "banner": ""}).index(_SECRETO)
        cambios = {"banner": "b" * (497 - base - 27)}
        texto = humanize({**self._ACTUALES, **cambios}, "boom")
        self.sv.respuesta("POST", f"/addons/{_SLUG}/options/validate",
                          HAConnectionError(f"failed 500: {texto}", status=500))
        r = await self.t["sv_set_addon_options"](_SLUG, json.dumps(cambios))
        self.assertIs(r["preview"]["validation"]["checked"], False)
        self.assertSinSecreto(r)


# ── T030: el error del guardado (código de la 1.1.2) ──────────────────────────


class TestErrorAlGuardar(_Base):
    _ACTUALES = {"log_level": "info", "auth_password": _SECRETO, "port": 8080}

    async def test_ni_en_la_respuesta_ni_en_disco_ni_en_el_log(self) -> None:
        self.sv.respuesta("GET", f"/addons/{_SLUG}/info", {"options": self._ACTUALES})
        # La validación de la vista previa no se pudo hacer: el token sale.
        self.sv.respuesta("POST", f"/addons/{_SLUG}/options/validate",
                          HAConnectionError("failed 500: boom", status=500))
        prev = await self.t["sv_set_addon_options"](_SLUG, '{"port": "x"}')
        token = prev["confirmation_token"]
        finales = {**self._ACTUALES, "port": "x"}
        self.sv.respuesta("POST", f"/addons/{_SLUG}/options", error_al_guardar(_SLUG, finales))
        with capture_logs() as eventos:
            r = await self.t["sv_set_addon_options"](
                _SLUG, '{"port": "x"}', confirmation_token=token)
        self.assertEqual(set(r), {"error"})
        self.assertIn("has invalid options", r["error"])
        self.assertSinSecreto(r)
        self.assertSinSecreto(eventos)
        # En disco: el fichero del token (y cualquier otro) sin ningún trozo.
        ficheros = list(security.CONFIRMATIONS_DIR.glob("*"))
        self.assertTrue(any(f.name == f"{token}.json" for f in ficheros))
        for f in ficheros:
            with self.subTest(fichero=f.name):
                self.assertSinSecreto(f.read_text(encoding="utf-8"))
        guardado = json.loads((security.CONFIRMATIONS_DIR / f"{token}.json")
                              .read_text(encoding="utf-8"))
        self.assertEqual(guardado["cached_error"], r["error"])


# ── T031 y T032: actualizar ───────────────────────────────────────────────────


class TestVersionAtada(_Base):
    def info(self, **campos: Any) -> None:
        base = {"slug": _SLUG, "version": "1.0.0", "version_latest": "2.0.0",
                "update_available": True, "detached": False}
        base.update(campos)
        self.sv.respuesta("GET", f"/addons/{_SLUG}/info", base)

    def tienda(self, **campos: Any) -> None:
        self.sv.respuesta("GET", f"/store/addons/{_SLUG}", ficha(_SLUG, **campos))
        self.sv.respuesta("GET", f"/store/addons/{_SLUG}/availability", {})

    def _estado_del_token(self, token: str) -> str:
        fichero = security.CONFIRMATIONS_DIR / f"{token}.json"
        return json.loads(fichero.read_text(encoding="utf-8"))["state"]

    async def _carrera(self, tool: str, cambiar: Any, ruta_post: str) -> None:
        prev = await self.t[tool](_SLUG)
        self.assertEqual(prev["preview"]["version_latest"], "2.0.0")
        cambiar()
        self.sv.respuesta("POST", ruta_post, {"job_id": "abc"})
        token = prev["confirmation_token"]
        r = await self.t[tool](_SLUG, confirmation_token=token)
        self.assertIs(r.get("preview_outdated"), True, r)
        self.assertEqual(r["version_latest"], "3.0.0")
        self.assertEqual(self.sv.escrituras(), [])
        # Sin gastar el token: el cliente pide otra vista previa.
        self.assertEqual(self._estado_del_token(token), "pending")

    async def test_actualizar_la_tienda_cambia_de_version(self) -> None:
        self.info()
        await self._carrera("sv_update_addon", lambda: self.info(version_latest="3.0.0"),
                            f"/store/addons/{_SLUG}/update")

    async def test_instalar_la_tienda_cambia_de_version(self) -> None:
        self.tienda()
        await self._carrera("sv_install_addon", lambda: self.tienda(version_latest="3.0.0"),
                            f"/store/addons/{_SLUG}/install")

    async def test_misma_version_confirma(self) -> None:
        # Control: con la misma versión, la petición de la 1.1.2.
        self.info()
        prev = await self.t["sv_update_addon"](_SLUG)
        self.sv.respuesta("POST", f"/store/addons/{_SLUG}/update", {"job_id": "abc"})
        r = await self.t["sv_update_addon"](_SLUG, confirmation_token=prev["confirmation_token"])
        self.assertEqual(r["job_id"], "abc")

    async def test_sin_poder_releer_no_se_actualiza(self) -> None:
        # Fail-closed: la vista previa vio 2.0.0 y al confirmar no se sabe.
        self.info()
        prev = await self.t["sv_update_addon"](_SLUG)
        self.sv.respuesta("GET", f"/addons/{_SLUG}/info",
                          HAConnectionError("failed 500: boom", status=500))
        self.sv.respuesta("POST", f"/store/addons/{_SLUG}/update", {"job_id": "abc"})
        r = await self.t["sv_update_addon"](_SLUG, confirmation_token=prev["confirmation_token"])
        self.assertIs(r.get("preview_outdated"), True, r)
        self.assertEqual(self.sv.escrituras(), [])

    async def test_desligada_no_dice_que_esta_al_dia(self) -> None:
        # T032: `detached` da `update_available: false` en el Supervisor.
        self.info(update_available=False, version_latest="1.0.0", detached=True)
        r = await self.t["sv_update_addon"](_SLUG)
        self.assertNotEqual(r.get("error"), "already_up_to_date")
        # Como en la 1.1.2, con token; pero diciendo la verdad.
        self.assertIn("confirmation_token", r)
        p = r["preview"]
        self.assertEqual((p["in_store"], p["update_status"]), (False, "not_in_store"))
        self.assertIn("no longer in the store", p["note"])

    async def test_sin_saber_si_esta_en_la_tienda_tampoco(self) -> None:
        self.info(update_available=False, version_latest="1.0.0", detached=None)
        r = await self.t["sv_update_addon"](_SLUG)
        self.assertNotEqual(r.get("error"), "already_up_to_date")
        self.assertIsNone(r["preview"]["in_store"])

    async def test_en_la_tienda_y_al_dia(self) -> None:
        self.info(update_available=False, version_latest="1.0.0")
        r = await self.t["sv_update_addon"](_SLUG)
        self.assertEqual(r["error"], "already_up_to_date")


# ── T035: instalar con la tienda ilegible ─────────────────────────────────────


class TestTiendaIlegible(_Base):
    async def test_tienda_ilegible_dice_lo_que_no_se_sabe(self) -> None:
        self.sv.respuesta("GET", f"/store/addons/{_SLUG}",
                          HAConnectionError("failed 500: boom", status=500))
        r = await self.t["sv_install_addon"](_SLUG)
        self.assertIn("confirmation_token", r)
        p = r["preview"]
        self.assertIs(p["store_check"]["checked"], False)
        nota = p["store_check"]["note"]
        self.assertIn("third-party repository", nota)
        self.assertIn("available", nota)
        self.assertIsNone(p["third_party_repository"])


if __name__ == "__main__":
    unittest.main()
