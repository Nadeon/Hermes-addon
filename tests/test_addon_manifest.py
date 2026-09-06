"""Tests del manifiesto del add-on (`hermes/config.yaml`).

El manifiesto lo valida el Supervisor, no Python, así que un error aquí no lo
detecta ninguna otra prueba: aparece al instalar, en la máquina de otro.

El caso que motivó estos tests: `auth_password` y `public_hostname` estaban
declaradas como `password` y `str` —obligatorias— pero `options:` les daba `""`
por defecto. Una cadena vacía es un valor VÁLIDO para esos dos tipos, así que el
Supervisor daba la opción por configurada y dejaba arrancar el add-on sin
contraseña. Las dos guardas de tiempo de ejecución (`run.sh` y `config.validate`)
paraban el arranque, pero el error salía en el log en vez de en el formulario.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

from hermes.password_policy import MIN_AUTH_PASSWORD_LENGTH

CONFIG = Path(__file__).resolve().parent.parent / "hermes" / "config.yaml"

# Copiado literal del Supervisor (supervisor/apps/options.py). Un elemento de
# schema que no case con esto hace que el Supervisor rechace el add-on entero.
RE_SCHEMA_ELEMENT = re.compile(
    r"^(?:"
    r"|bool"
    r"|email"
    r"|url"
    r"|port"
    r"|device(?:\((?P<filter>subsystem=[a-z]+)\))?"
    r"|str(?:\((?P<s_min>\d+)?,(?P<s_max>\d+)?\))?"
    r"|password(?:\((?P<p_min>\d+)?,(?P<p_max>\d+)?\))?"
    r"|int(?:\((?P<i_min>-?\d+)?,(?P<i_max>-?\d+)?\))?"
    r"|float(?:\((?P<f_min>-?\d*\.?\d+)?,(?P<f_max>-?\d*\.?\d+)?\))?"
    r"|match\((?P<match>.*)\)"
    r"|list\((?P<list>.+)\)"
    r")\??$"
)

# Opciones sin las que Hermes no puede funcionar.
OBLIGATORIAS = ("auth_password", "public_hostname")


class TestManifiesto(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifiesto = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        cls.schema = cls.manifiesto["schema"]
        cls.options = cls.manifiesto["options"]

    def test_todo_el_schema_lo_entiende_el_supervisor(self) -> None:
        """Un tipo mal escrito hace que el Supervisor rechace el add-on entero."""
        for clave, tipo in self.schema.items():
            with self.subTest(opcion=clave):
                if isinstance(tipo, list):        # listas: se valida su elemento
                    tipo = tipo[0]
                self.assertRegex(str(tipo), RE_SCHEMA_ELEMENT)

    def test_las_obligatorias_no_traen_valor_por_defecto(self) -> None:
        """`null` es lo que marca una opción como obligatoria; `""` no.

        Con una cadena vacía la opción ya tiene valor, el Supervisor no pide
        nada, y el add-on se puede arrancar sin configurar.
        """
        for clave in OBLIGATORIAS:
            with self.subTest(opcion=clave):
                self.assertIn(clave, self.options)
                self.assertIsNone(
                    self.options[clave],
                    f"{clave} tiene un valor por defecto, así que el Supervisor "
                    f"la da por configurada y deja arrancar sin ella",
                )

    def test_las_obligatorias_no_son_opcionales_en_el_schema(self) -> None:
        """Un `?` al final las volvería opcionales."""
        for clave in OBLIGATORIAS:
            with self.subTest(opcion=clave):
                self.assertFalse(
                    str(self.schema[clave]).endswith("?"),
                    f"{clave} está marcada como opcional en el schema",
                )

    def test_el_schema_rechaza_la_cadena_vacia(self) -> None:
        """Sin longitud mínima, "" pasa la validación del Supervisor."""
        for clave in OBLIGATORIAS:
            with self.subTest(opcion=clave):
                m = RE_SCHEMA_ELEMENT.match(str(self.schema[clave]))
                assert m is not None
                minimo = m.group("p_min") or m.group("s_min")
                self.assertIsNotNone(
                    minimo,
                    f"{clave} no exige longitud mínima, así que \"\" es válida "
                    f"para el Supervisor",
                )
                self.assertGreaterEqual(int(minimo), 1)

    def test_el_minimo_del_schema_coincide_con_el_del_codigo(self) -> None:
        """Si divergen, el formulario y el arranque exigen cosas distintas."""
        m = RE_SCHEMA_ELEMENT.match(str(self.schema["auth_password"]))
        assert m is not None
        self.assertEqual(
            int(m.group("p_min")),
            MIN_AUTH_PASSWORD_LENGTH,
            "el mínimo del schema del add-on y MIN_AUTH_PASSWORD_LENGTH han "
            "divergido",
        )

    def test_la_version_es_semver(self) -> None:
        """El workflow de publicación compara el tag con este campo."""
        self.assertRegex(str(self.manifiesto["version"]), r"^\d+\.\d+\.\d+$")

    def test_toda_opcion_por_defecto_esta_declarada_en_el_schema(self) -> None:
        """Una opción en `options` que no esté en `schema` la rechaza HA."""
        for clave in self.options:
            with self.subTest(opcion=clave):
                self.assertIn(clave, self.schema)


if __name__ == "__main__":
    unittest.main()
