"""Traducciones de las opciones de la app (spec 027, FR-006, FR-016, SC-004).

El Supervisor lee `translations/*.yaml` junto a `config.yaml` y enseña en la
página de configuración el nombre y la descripción de cada opción en el idioma
del usuario. Un fichero que no valida lo ignora con un aviso en SU log, sin
que nadie se entere: este test impide publicarlo.

Forma que acepta el Supervisor 2026.11.0 (`supervisor/apps/validate.py`),
copiada aquí sin importar nada del Supervisor:

    SCHEMA_TRANSLATION_CONFIGURATION = vol.Schema(
        {
            vol.Required(ATTR_NAME): str,
            vol.Optional(ATTR_DESCRIPTON): vol.Maybe(str),
            vol.Optional(ATTR_FIELDS): {str: vol.Self},
        },
        extra=vol.REMOVE_EXTRA,
    )
    SCHEMA_APP_TRANSLATIONS = vol.Schema(
        {
            vol.Optional(ATTR_CONFIGURATION): {str: SCHEMA_TRANSLATION_CONFIGURATION},
            vol.Optional(ATTR_NETWORK): {str: str},
        },
        extra=vol.REMOVE_EXTRA,
    )

Hermes es más estricto: `description` obligatoria y no vacía, y las claves de
`configuration` exactamente las del `schema` de `config.yaml`.

Control negativo comprobado (T018): borrar `log_level` de `es.yaml` →
`test_claves_iguales_que_el_esquema` en rojo.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

_HERMES = Path(__file__).resolve().parent.parent / "hermes"
_IDIOMAS = ("en", "es")

# Marcadores genéricos que sí pueden aparecer (DOCS.md usa los mismos).
_HOSTS_PERMITIDOS = {"homeassistant.tailXXXX.ts.net", "claude.ai"}
_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b|\b[0-9a-f]{0,4}:[0-9a-f]{0,4}:[0-9a-f:]+\b", re.I)
# Un nombre con punto y un dominio de primer nivel de letras (`algo.ts.net`).
# No casa con nombres de opciones, rutas de tools ni `input_*`.
_HOST_RE = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}\b", re.I)
_EXTENSIONES = re.compile(r"\.(?:md|yaml|yml|json|py|db|key)$", re.I)


def _esquema() -> set[str]:
    config = yaml.safe_load((_HERMES / "config.yaml").read_text(encoding="utf-8"))
    return set(config["schema"])


def _traduccion(idioma: str) -> dict:
    return yaml.safe_load(
        (_HERMES / "translations" / f"{idioma}.yaml").read_text(encoding="utf-8"))


def _textos(idioma: str) -> list[str]:
    salida: list[str] = []
    for entrada in _traduccion(idioma)["configuration"].values():
        salida.extend([entrada["name"], entrada["description"]])
    return salida


class TestTraducciones(unittest.TestCase):

    def test_existen_los_dos_idiomas(self) -> None:
        for idioma in _IDIOMAS:
            self.assertTrue((_HERMES / "translations" / f"{idioma}.yaml").is_file(), idioma)

    def test_forma_que_acepta_el_supervisor(self) -> None:
        for idioma in _IDIOMAS:
            with self.subTest(idioma=idioma):
                datos = _traduccion(idioma)
                self.assertIsInstance(datos, dict)
                self.assertIn("configuration", datos)
                self.assertLessEqual(set(datos), {"configuration", "network"})
                self.assertIsInstance(datos["configuration"], dict)
                for opcion, entrada in datos["configuration"].items():
                    self.assertIsInstance(entrada, dict, opcion)
                    self.assertLessEqual(set(entrada), {"name", "description", "fields"},
                                         opcion)
                    for campo in ("name", "description"):
                        self.assertIsInstance(entrada.get(campo), str, f"{opcion}.{campo}")
                        self.assertTrue(entrada[campo].strip(), f"{opcion}.{campo}")

    def test_claves_iguales_que_el_esquema(self) -> None:
        esquema = _esquema()
        self.assertEqual(len(esquema), 31)
        for idioma in _IDIOMAS:
            with self.subTest(idioma=idioma):
                self.assertEqual(set(_traduccion(idioma)["configuration"]), esquema)

    def test_dicen_app_y_no_add_on(self) -> None:
        for idioma in _IDIOMAS:
            for texto in _textos(idioma):
                with self.subTest(idioma=idioma, texto=texto[:40]):
                    self.assertNotRegex(texto.lower(), r"add-?on")

    def test_sin_datos_de_una_instalacion(self) -> None:
        for idioma in _IDIOMAS:
            for texto in _textos(idioma):
                with self.subTest(idioma=idioma, texto=texto[:40]):
                    self.assertIsNone(_IP_RE.search(texto), "IP")
                    self.assertNotIn("C:\\", texto)
                    for host in _HOST_RE.findall(texto):
                        if _EXTENSIONES.search(host):
                            continue
                        self.assertIn(host, _HOSTS_PERMITIDOS)


if __name__ == "__main__":
    unittest.main()
