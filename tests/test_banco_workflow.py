"""El job del banco de Core en el CI (spec 010, FR-001, FR-010, FR-011).

El banco solo corre en GitHub Actions; lo que sí se puede comprobar en
cualquier máquina es que el workflow lo declara como se ha decidido: imagen
fijada por digest con la misma versión que `HA_CORE_LAST_TESTED`, check con
nombre estable y sin `continue-on-error`, obligatoriedad activa, topes y
diagnóstico. Si alguien sube `HA_CORE_LAST_TESTED` sin cambiar la imagen (o al
revés), este test lo dice.

Control negativo (T016), comprobado en local y restaurado:
  1. `HA_IMAGEN` solo con etiqueta, sin digest → cae `test_imagen_por_digest_y_version`;
  2. etiqueta `2026.11.0` → cae el mismo;
  3. `continue-on-error: true` → cae `test_identidad_del_job`;
  4. sin `HERMES_BANCO_OBLIGATORIO` en el paso → cae `test_paso_que_ejecuta_el_banco`.
"""

from __future__ import annotations

import configparser
import re
import unittest
from pathlib import Path
from typing import Any

import yaml

from hermes.config import HA_CORE_LAST_TESTED

RAIZ = Path(__file__).resolve().parent.parent
WORKFLOW = RAIZ / ".github" / "workflows" / "tests.yml"
PATRON_IMAGEN = re.compile(
    r"^ghcr\.io/home-assistant/home-assistant:(?P<tag>[0-9.]+)@sha256:[0-9a-f]{64}$"
)


def _job() -> dict[str, Any]:
    datos = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return datos["jobs"]["banco-core"]


def _pasos() -> list[dict[str, Any]]:
    return _job()["steps"]


class TestJobBancoCore(unittest.TestCase):
    def test_identidad_del_job(self) -> None:
        job = _job()
        self.assertEqual(job["name"], "banco de Core")
        self.assertEqual(job["runs-on"], "ubuntu-latest")
        self.assertNotIn("continue-on-error", job)
        self.assertLessEqual(int(job["timeout-minutes"]), 20)
        for paso in job["steps"]:
            self.assertNotIn("continue-on-error", paso, paso.get("name"))

    def test_imagen_por_digest_y_version(self) -> None:
        imagen = _job()["env"]["HA_IMAGEN"]
        coincidencia = PATRON_IMAGEN.match(imagen)
        self.assertIsNotNone(coincidencia, f"HA_IMAGEN sin la forma <repo>:<versión>@sha256:<64 hex>: {imagen}")
        self.assertEqual(coincidencia["tag"], HA_CORE_LAST_TESTED)  # type: ignore[index]

    def test_paso_que_ejecuta_el_banco(self) -> None:
        pasos = [p for p in _pasos() if "pytest -m banco" in str(p.get("run", ""))]
        self.assertEqual(len(pasos), 1, "tiene que haber exactamente un paso con `pytest -m banco`")
        paso = pasos[0]
        self.assertIn("--timeout=120", paso["run"])
        self.assertIn("tests/banco", paso["run"])
        env = paso.get("env", {})
        self.assertTrue(env.get("HERMES_BANCO_HA_URL"))
        self.assertEqual(env.get("HERMES_BANCO_OBLIGATORIO"), "1")
        self.assertNotIn("if", paso)

    def test_descarga_con_reintentos(self) -> None:
        pasos = [p for p in _pasos() if "docker pull" in str(p.get("run", ""))]
        self.assertEqual(len(pasos), 1)
        intentos = re.search(r"for intento in ([0-9 ]+);", pasos[0]["run"])
        self.assertIsNotNone(intentos)
        self.assertGreaterEqual(len(intentos[1].split()), 3)  # type: ignore[index]

    def test_logs_si_falla_y_limpieza_siempre(self) -> None:
        pasos = _pasos()
        logs = [p for p in pasos if "docker logs" in str(p.get("run", ""))]
        self.assertEqual([p.get("if") for p in logs], ["failure()"])
        limpieza = [p for p in pasos if "docker rm -f" in str(p.get("run", ""))]
        self.assertEqual([p.get("if") for p in limpieza], ["always()"])

    def test_contenedor_sin_salida_y_puerto_solo_local(self) -> None:
        texto = "\n".join(str(p.get("run", "")) for p in _pasos())
        self.assertIn("DOCKER-USER", texto)
        self.assertIn("-p 127.0.0.1:8123:8123", texto)
        self.assertIn("tiene salida a internet", texto)
        # T040: la comprobación es `tests/banco/sin_salida.py` (TCP a IP
        # literal), no una petición HTTP que un 429 o un 5xx darían por buena.
        pasos = [p for p in _pasos() if "sin_salida.py" in str(p.get("run", ""))]
        self.assertEqual(len(pasos), 1)
        self.assertRegex(
            pasos[0]["run"],
            r"docker exec -i ha-banco python3 - (\d+\.\d+\.\d+\.\d+:\d+ )+< tests/banco/sin_salida\.py",
        )
        self.assertNotIn("urllib", texto)

    def test_permisos_de_solo_lectura(self) -> None:
        # T044: declarado en el workflow, sin depender del valor por defecto
        # del repositorio; y ningún job lo amplía.
        datos = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        self.assertEqual(datos.get("permissions"), {"contents": "read"})
        for nombre, job in datos["jobs"].items():
            self.assertNotIn("permissions", job, nombre)

    def test_marcador_banco_registrado(self) -> None:
        ini = configparser.ConfigParser()
        ini.read(RAIZ / "pytest.ini", encoding="utf-8")
        marcadores = ini["pytest"]["markers"]
        self.assertRegex(marcadores, r"(?m)^\s*banco:")


if __name__ == "__main__":
    unittest.main()
