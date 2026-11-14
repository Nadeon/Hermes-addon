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

from hermes import __version__
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

    def test_la_version_del_codigo_coincide_con_la_del_manifiesto(self) -> None:
        """Son dos números escritos a mano en sitios distintos, y se separaron.

        `__version__` seguía anunciando 0.38.0 mientras el manifiesto subía tres
        veces, así que la pantalla de login, el endpoint /health y las líneas de
        arranque del log anunciaban una versión que no era la instalada. Eso
        rompe lo que piden SECURITY.md y CONTRIBUTING.md al reportar un fallo:
        que digas qué versión ejecutas.

        No se derivan una de otra porque config.yaml no entra en la imagen —el
        Dockerfile copia solo src/ y run.sh—, así que la sincronía la sostiene
        este test.
        """
        self.assertEqual(
            __version__,
            str(self.manifiesto["version"]),
            "hermes/src/hermes/__init__.py y hermes/config.yaml declaran "
            "versiones distintas",
        )

    def test_la_version_de_ha_probada_se_revisa_en_cada_release(self) -> None:
        """La 1.0.10 salió con HA_CORE_LAST_TESTED en 2026.9.0, dos versiones
        de Home Assistant por detrás: todas las instalaciones al día avisaban
        en cada arranque de una versión "no probada" que funcionaba bien.

        La regla de subirla en cada release vivía en un comentario. Este test
        no puede saber contra qué HA se probó, pero sí obliga a que alguien lo
        decida: la pareja HA_CORE_LAST_TESTED_IN_HERMES tiene que coincidir
        con la versión que se publica.
        """
        from hermes.config import HA_CORE_LAST_TESTED_IN_HERMES

        self.assertEqual(
            HA_CORE_LAST_TESTED_IN_HERMES,
            __version__,
            "Nueva versión de Hermes sin revisar HA_CORE_LAST_TESTED en "
            "hermes/src/hermes/config.py: compruébala contra la HA actual y "
            "súbela, o deja la versión de HA y actualiza solo la pareja",
        )

    def test_la_version_minima_de_ha_es_2024_10(self) -> None:
        """Regresión FR-041 (R4): la mínima declarada era 2024.1.0, pero Hermes
        guarda las automatizaciones con las claves en plural (`triggers`,
        `conditions`, `actions`), que HA solo entiende desde 2024.10. Con una
        HA 2024.1–2024.9 el arranque no avisaba y las automatizaciones no se
        podían guardar.
        """
        from hermes.config import HA_CORE_MIN_SUPPORTED

        self.assertEqual(HA_CORE_MIN_SUPPORTED, "2024.10.0")

    def test_el_manifiesto_declara_la_misma_version_minima_de_ha(self) -> None:
        """M4: sin la clave `homeassistant`, el Supervisor instalaba la
        actualización en una HA 2024.1–2024.9 y el add-on no arrancaba
        (`HA core … < minimum supported`). Con ella, el Supervisor rechaza la
        actualización. Las dos versiones no se pueden separar.
        """
        from hermes.config import HA_CORE_MIN_SUPPORTED

        valor = self.manifiesto.get("homeassistant")
        self.assertIsInstance(valor, str, "debe ser una cadena de versión")
        self.assertEqual(valor, HA_CORE_MIN_SUPPORTED)
        # Entre comillas: el Supervisor la valida como `version_tag`.
        texto = CONFIG.read_text(encoding="utf-8")
        self.assertRegex(
            texto, rf'(?m)^homeassistant: "{re.escape(HA_CORE_MIN_SUPPORTED)}"'
        )

    def test_toda_opcion_por_defecto_esta_declarada_en_el_schema(self) -> None:
        """Una opción en `options` que no esté en `schema` la rechaza HA."""
        for clave in self.options:
            with self.subTest(opcion=clave):
                self.assertIn(clave, self.schema)

    def test_response_max_bytes_por_defecto_coincide_con_el_codigo(self) -> None:
        """FR-032: 131 072 en config.yaml y en config.py."""
        from hermes.config import RESPONSE_MAX_BYTES_DEFAULT, HermesConfig

        self.assertEqual(self.options["response_max_bytes"], 131_072)
        self.assertEqual(RESPONSE_MAX_BYTES_DEFAULT, 131_072)
        self.assertEqual(HermesConfig().response_max_bytes,
                         self.options["response_max_bytes"])

    def test_el_esquema_de_los_limites_no_se_estrecha(self) -> None:
        """Control de S-03: el Supervisor valida las opciones guardadas.

        Quien tenga guardado 1 048 576 o 300 no podría arrancar si el esquema
        dejara de admitirlos; el máximo efectivo se aplica en el código.
        """
        casos = {"response_max_bytes": 1_048_576,
                 "wait_for_event_max_seconds": 300}
        for clave, guardado in casos.items():
            with self.subTest(opcion=clave):
                m = RE_SCHEMA_ELEMENT.match(str(self.schema[clave]))
                assert m is not None
                self.assertLessEqual(int(m.group("i_min")), guardado)
                self.assertGreaterEqual(int(m.group("i_max")), guardado)

    def test_opciones_nuevas_declaradas_y_activadas(self) -> None:
        """FR-023 y FR-044: opcionales en el esquema y `true` por defecto."""
        for clave in ("oauth_cimd_enabled", "log_redact_network"):
            with self.subTest(opcion=clave):
                self.assertEqual(self.schema.get(clave), "bool?")
                self.assertIs(self.options.get(clave), True)

    def test_safety_backup_keep_declarada_con_su_rango(self) -> None:
        """Spec 005, FR-031: 0–50 y 3 por defecto. Sin ella en el esquema, el
        Supervisor rechaza el `options` que la incluye y el add-on no arranca;
        sin el `?`, quien actualice sin tocarla no podría guardar."""
        self.assertEqual(self.schema.get("safety_backup_keep"), "int(0,50)?")
        self.assertEqual(self.options.get("safety_backup_keep"), 3)

    def test_arranca_despues_del_core_de_home_assistant(self) -> None:
        """`startup: services` arrancaba Hermes ANTES que el core de HA.

        El Supervisor arranca por fases (supervisor/core.py): initialize →
        system → services → Home Assistant Core → application. El paso 8 del
        boot de Hermes necesita el WebSocket del core dentro de
        `health_startup_grace_seconds`, así que en la fase `services` —con el
        core todavía sin levantar— un arranque en frío sobre hardware lento
        agotaba el plazo y el add-on moría con error.

        `application` es la única fase posterior al core.
        """
        self.assertEqual(
            self.manifiesto["startup"],
            "application",
            "Hermes debe arrancar en la fase posterior al core de HA",
        )

    def test_el_rol_deja_leer_las_opciones_de_otros_add_ons(self) -> None:
        """Sin rol `manager` o `admin`, `sv_set_addon_options` borraría opciones.

        `POST /addons/{slug}/options` sustituye las opciones guardadas, así que
        la tool lee las actuales de `/addons/{slug}/info` y mezcla los cambios
        encima. El Supervisor solo incluye ahí las opciones si quien pregunta
        tiene rol `manager` o `admin` (`info_data` en supervisor/api/apps.py); a
        cualquier otro le manda `options: {}`. Con un rol menor, la mezcla
        partiría de `{}` y enviaría solo los cambios: todo lo demás, secretos
        incluidos, se perdería. La tool se niega cuando ve `{}` con opciones
        obligatorias en el schema, pero un add-on sin obligatorias pasaría.
        """
        self.assertIn(
            self.manifiesto.get("hassio_role"),
            ("manager", "admin"),
            "sin rol manager/admin, /info oculta las opciones de los add-ons",
        )


if __name__ == "__main__":
    unittest.main()
