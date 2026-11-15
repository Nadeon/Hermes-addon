"""Tests del ayudante de traducciones de Repairs (`tools/_translations.py`;
spec 016, tramo C, T030; FR-015, FR-021).

Home Assistant se simula con un `ws_send` falso que registra cada comando.
Datos ficticios (`banco_flujos`, `aviso_reparable`) y centinelas que no deben
salir en ningún texto.

Controles negativos comprobados (T044 a): sustituir los marcadores sin
redactarlos antes → 2 rojos (`test_marcador_con_centinela_tapado`,
`test_marcadores_del_paso_redactados`); dejar que un fallo de lectura se
propague → 3 (`test_fallo_de_get_config_no_lanza`,
`test_fallo_de_get_translations_no_lanza`, `test_unknown_command_no_lanza`).
"""

from __future__ import annotations

import unittest
from typing import Any

from hermes.ha import HAConnectionError
from hermes.tools import _translations as tr

_CENTINELA = "centinela-016"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJiYW5jbyJ9.c2lnbmF0dXJhLWRlLXBydWViYQ"

_RECURSOS = {
    "component.banco_flujos.issues.aviso_reparable.title": "Value {valor} to confirm",
    "component.banco_flujos.issues.aviso_reparable.description": "The value {valor} of {otro} must be confirmed.",
    "component.banco_flujos.issues.aviso_reparable.fix_flow.step.confirm.title": "Confirm {valor}",
    "component.banco_flujos.issues.aviso_reparable.fix_flow.step.confirm.description": "Submit to confirm.",
    "component.banco_flujos.issues.aviso_reparable.fix_flow.abort.ya_hecho": "Already done",
}


class _FakeHA:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.config: Any = {"language": "es"}
        self.recursos: Any = {"resources": dict(_RECURSOS)}
        self.error_config: HAConnectionError | None = None
        self.error_trad: Exception | None = None

    async def ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.sent.append(payload)
        if payload["type"] == "get_config":
            if self.error_config:
                raise self.error_config
            return self.config
        if payload["type"] == "frontend/get_translations":
            if self.error_trad:
                raise self.error_trad
            return self.recursos
        raise AssertionError(f"comando inesperado: {payload}")


class _Cliente:
    def __init__(self, fake: _FakeHA) -> None:
        self.ws_send = fake.ws_send


class TestLeer(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fake = _FakeHA()
        self.cliente = _Cliente(self.fake)

    async def test_idioma_y_una_sola_llamada_con_los_dominios(self) -> None:
        textos = await tr.leer(self.cliente, ["hue", "banco_flujos", "hue"])
        self.assertEqual(textos.language, "es")
        self.assertFalse(textos.unavailable)
        self.assertEqual(
            self.fake.sent,
            [{"type": "get_config"},
             {"type": "frontend/get_translations", "language": "es",
              "category": "issues", "integration": ["banco_flujos", "hue"]}],
        )

    async def test_sin_language_es_ingles(self) -> None:
        self.fake.config = {"version": "2026.11.1"}
        textos = await tr.leer(self.cliente, ["banco_flujos"])
        self.assertEqual(textos.language, "en")
        self.assertEqual(self.fake.sent[1]["language"], "en")

    async def test_sin_dominios_no_llama(self) -> None:
        textos = await tr.leer(self.cliente, [])
        self.assertEqual(self.fake.sent, [])
        self.assertFalse(textos.unavailable)

    async def test_fallo_de_get_config_no_lanza(self) -> None:
        self.fake.error_config = HAConnectionError("offline")
        textos = await tr.leer(self.cliente, ["banco_flujos"])
        self.assertTrue(textos.unavailable)
        self.assertEqual(textos.resources, {})
        self.assertEqual([p["type"] for p in self.fake.sent], ["get_config"])

    async def test_fallo_de_get_translations_no_lanza(self) -> None:
        self.fake.error_trad = HAConnectionError("boom")
        textos = await tr.leer(self.cliente, ["banco_flujos"])
        self.assertTrue(textos.unavailable)
        self.assertEqual(textos.resources, {})

    async def test_unknown_command_no_lanza(self) -> None:
        self.fake.error_trad = HAConnectionError("Unknown command.", code="unknown_command")
        textos = await tr.leer(self.cliente, ["banco_flujos"])
        self.assertTrue(textos.unavailable)

    async def test_respuesta_rara_es_no_disponible(self) -> None:
        self.fake.recursos = ["no", "es", "un", "objeto"]
        textos = await tr.leer(self.cliente, ["banco_flujos"])
        self.assertTrue(textos.unavailable)


class TestTextos(unittest.TestCase):
    def setUp(self) -> None:
        self.textos = tr.Textos(language="es", resources=dict(_RECURSOS), unavailable=False)
        self.aviso = {"domain": "banco_flujos", "issue_id": "aviso_reparable",
                      "translation_key": "aviso_reparable",
                      "translation_placeholders": {"valor": "42"}}

    def test_claves(self) -> None:
        self.assertEqual(tr.clave_aviso("d", "k", "title"), "component.d.issues.k.title")
        self.assertEqual(tr.clave_paso("d", "k", "confirm", "description"),
                         "component.d.issues.k.fix_flow.step.confirm.description")
        self.assertEqual(tr.clave_abort("d", "k", "motivo"),
                         "component.d.issues.k.fix_flow.abort.motivo")

    def test_aviso_con_marcadores_sustituidos_y_desconocidos_intactos(self) -> None:
        t = tr.textos_del_aviso(self.textos, self.aviso)
        self.assertEqual(t["title"], "Value 42 to confirm")
        self.assertEqual(t["description"], "The value 42 of {otro} must be confirmed.")
        self.assertFalse(t["description_truncated"])

    def test_sin_translation_key_no_hay_texto(self) -> None:
        aviso = dict(self.aviso, translation_key=None)
        t = tr.textos_del_aviso(self.textos, aviso)
        self.assertEqual((t["title"], t["description"]), (None, None))

    def test_no_disponibles_sin_texto(self) -> None:
        textos = tr.Textos(language=None, resources={}, unavailable=True)
        t = tr.textos_del_aviso(textos, self.aviso)
        self.assertEqual((t["title"], t["description"], t["description_truncated"]),
                         (None, None, False))

    def test_recorte_de_la_descripcion(self) -> None:
        clave = tr.clave_aviso("banco_flujos", "aviso_reparable", "description")
        self.textos.resources[clave] = "x" * 1500
        t = tr.textos_del_aviso(self.textos, self.aviso, recorte=1000)
        self.assertEqual(len(t["description"]), 1000)
        self.assertTrue(t["description_truncated"])
        entero = tr.textos_del_aviso(self.textos, self.aviso)
        self.assertEqual(len(entero["description"]), 1500)
        self.assertFalse(entero["description_truncated"])

    def test_marcador_con_centinela_tapado(self) -> None:
        aviso = dict(self.aviso, translation_placeholders={"valor": "1", "password": _CENTINELA})
        clave = tr.clave_aviso("banco_flujos", "aviso_reparable", "description")
        self.textos.resources[clave] = "Clave {password} y valor {valor}"
        t = tr.textos_del_aviso(self.textos, aviso)
        self.assertNotIn(_CENTINELA, str(t))
        self.assertIn("valor 1", t["description"])

    def test_texto_traducido_con_secreto_tapado(self) -> None:
        clave = tr.clave_aviso("banco_flujos", "aviso_reparable", "title")
        self.textos.resources[clave] = f"Token {_JWT}"
        t = tr.textos_del_aviso(self.textos, self.aviso)
        self.assertNotIn(_JWT, str(t))

    def test_texto_del_paso_de_fix_flow(self) -> None:
        t = tr.texto_del_paso(self.textos, self.aviso, "confirm", None)
        self.assertEqual(t, {"title": "Confirm 42", "description": "Submit to confirm.",
                             "source": "fix_flow"})

    def test_texto_del_paso_sin_texto_usa_el_del_aviso(self) -> None:
        t = tr.texto_del_paso(self.textos, self.aviso, "otro_paso", None)
        self.assertEqual(t["source"], "issue")
        self.assertEqual(t["title"], "Value 42 to confirm")

    def test_texto_del_paso_sin_nada(self) -> None:
        textos = tr.Textos(language=None, resources={}, unavailable=True)
        t = tr.texto_del_paso(textos, self.aviso, "confirm", None)
        self.assertEqual(t, {"title": None, "description": None, "source": None})

    def test_marcadores_del_paso_redactados(self) -> None:
        clave = tr.clave_paso("banco_flujos", "aviso_reparable", "confirm", "description")
        self.textos.resources[clave] = "Clave {token}"
        t = tr.texto_del_paso(self.textos, self.aviso, "confirm", {"token": _CENTINELA})
        self.assertNotIn(_CENTINELA, str(t))

    def test_texto_del_abort(self) -> None:
        self.assertEqual(tr.texto_del_abort(self.textos, self.aviso, "ya_hecho"), "Already done")
        self.assertIsNone(tr.texto_del_abort(self.textos, self.aviso, "otro"))

    def test_marca_de_terceros(self) -> None:
        marca = tr.marca_terceros(["title", "description"])
        self.assertEqual(marca["fields"], ["title", "description"])
        self.assertIn("third parties", marca["warning"])


if __name__ == "__main__":
    unittest.main()
