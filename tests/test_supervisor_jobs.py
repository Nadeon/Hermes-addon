"""Errores de los sub-jobs del Supervisor (spec 027, FR-002, FR-017 y D-1).

El Supervisor 2026.11.0 guarda cada error en el job que lo captura y no lo
copia al padre (`supervisor/jobs/__init__.py`, `SupervisorJob.capture_error`;
`supervisor/api/jobs.py`, `_list_jobs`, que devuelve `child_jobs` con la misma
forma, recursiva). Un backup completo con una app que no se pudo guardar
(`supervisor/backups/backup.py`, `store_apps`, job `backup_store_apps`)
termina con `errors: []` en el job del backup y el error en el sub-job.

Aquí se prueban `child_job_errors` (el recorrido) y el sondeo del safety
backup de `fs_write.py`, que los cuenta como fallo para no escribir sin un
backup válido (principio III).

Controles negativos comprobados:
- `child_job_errors` devolviendo siempre `([], False)` → 14 en rojo (9 de
  `TestChildJobErrors` y 5 de `TestSondeoSubJobs`).
- `_evaluar_job` sin sumar los sub-jobs → los 5 de `TestSondeoSubJobs` que
  los miran en rojo (sub-job, sin nombre, recorte, centinela y escritura).
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from hermes.fs_write import _evaluar_job, maybe_trigger_safety_backup
from hermes.supervisor_jobs import (
    CHILD_ERRORS_MAX,
    CHILD_JOBS_MAX_DEPTH,
    JOB_ERROR_MAX_CHARS,
    child_job_errors,
    job_errors,
)
from tests.test_fs_write_security import _SupervisorDeJobs

_CENTINELA = "centinela-027"


def _sub(name, errores=None, hijos=None) -> dict:
    """Un sub-job con la forma de `_list_jobs` (solo los campos que importan)."""
    job: dict = {"name": name, "done": True, "errors": errores or []}
    if hijos is not None:
        job["child_jobs"] = hijos
    return job


def _err(mensaje: str) -> dict:
    return {"type": "BackupError", "message": mensaje, "stage": None}


def _cadena(niveles: int) -> dict:
    """Job con una cadena de `niveles` sub-jobs anidados, cada uno con un error."""
    hijo = None
    for n in range(niveles, 0, -1):
        hijo = _sub(f"nivel_{n}", [_err(f"fallo {n}")],
                    [hijo] if hijo is not None else None)
    return {"name": "padre", "done": True, "errors": [], "child_jobs": [hijo]}


class TestChildJobErrors(unittest.TestCase):

    def test_sin_child_jobs_no_hay_errores(self) -> None:
        self.assertEqual(child_job_errors({"done": True, "errors": []}), ([], False))
        self.assertEqual(child_job_errors({"child_jobs": []}), ([], False))
        self.assertEqual(child_job_errors(None), ([], False))
        self.assertEqual(child_job_errors("texto"), ([], False))

    def test_un_hijo_con_un_error(self) -> None:
        data = {"name": "backup_manager_full_backup", "done": True, "errors": [],
                "child_jobs": [_sub("backup_store_apps",
                                    [_err("Can't create backup for <slug>")])]}
        self.assertEqual(
            child_job_errors(data),
            ([{"job": "backup_store_apps",
               "message": "Can't create backup for <slug>"}], False),
        )

    def test_tres_niveles_en_orden_de_profundidad(self) -> None:
        data = {"name": "padre", "done": True, "errors": [], "child_jobs": [
            _sub("a", [_err("a1")], [
                _sub("a.a", [_err("aa1")], [_sub("a.a.a", [_err("aaa1")])]),
                _sub("a.b", [_err("ab1")]),
            ]),
            _sub("b", [_err("b1")]),
        ]}
        errores, recortado = child_job_errors(data)
        self.assertFalse(recortado)
        self.assertEqual([e["message"] for e in errores],
                         ["a1", "aa1", "aaa1", "ab1", "b1"])
        self.assertEqual([e["job"] for e in errores],
                         ["a", "a.a", "a.a.a", "a.b", "b"])

    def test_error_sin_message_es_unknown_error(self) -> None:
        data = {"child_jobs": [_sub("x", [{"type": "BackupError"}, {"message": 42},
                                          {"message": ""}, "suelto"])]}
        errores, _ = child_job_errors(data)
        self.assertEqual([e["message"] for e in errores], ["unknown error"] * 4)

    def test_mensaje_largo_se_recorta(self) -> None:
        errores, _ = child_job_errors({"child_jobs": [_sub("x", [_err("x" * 2000)])]})
        self.assertEqual(len(errores[0]["message"]), JOB_ERROR_MAX_CHARS)

    def test_centinela_tapado(self) -> None:
        data = {"child_jobs": [_sub("x", [_err(f"fallo: token={_CENTINELA}")])]}
        errores, _ = child_job_errors(data)
        self.assertNotIn(_CENTINELA, errores[0]["message"])
        self.assertIn("REDACTED", errores[0]["message"])

    def test_formas_raras_se_ignoran_sin_inventar_errores(self) -> None:
        for data in (
            {"child_jobs": "no es lista"},
            {"child_jobs": {"name": "x", "errors": [_err("no")]}},
            {"child_jobs": [None, 3, "texto", ["lista"]]},
            {"child_jobs": [{"name": "x", "errors": "no es lista"}]},
            {"child_jobs": [{"name": "x", "errors": None, "child_jobs": "raro"}]},
        ):
            with self.subTest(data=data):
                self.assertEqual(child_job_errors(data), ([], False))

    def test_tope_de_entradas(self) -> None:
        data = {"child_jobs": [_sub(f"app_{i}", [_err(f"fallo {i}")]) for i in range(25)]}
        errores, recortado = child_job_errors(data)
        self.assertEqual(len(errores), CHILD_ERRORS_MAX)
        self.assertTrue(recortado)
        self.assertEqual(errores[-1]["message"], f"fallo {CHILD_ERRORS_MAX - 1}")
        # Justo en el tope no hay recorte.
        justo = {"child_jobs": [_sub(f"a{i}", [_err("f")]) for i in range(CHILD_ERRORS_MAX)]}
        self.assertEqual(child_job_errors(justo)[1], False)

    def test_tope_de_niveles(self) -> None:
        errores, recortado = child_job_errors(_cadena(7))
        self.assertEqual(len(errores), CHILD_JOBS_MAX_DEPTH)
        self.assertEqual(errores[-1]["job"], f"nivel_{CHILD_JOBS_MAX_DEPTH}")
        self.assertTrue(recortado)
        # Cinco niveles exactos: todo revisado.
        self.assertEqual(child_job_errors(_cadena(CHILD_JOBS_MAX_DEPTH))[1], False)

    def test_sub_jobs_sin_errores_por_debajo_del_tope_tambien_recortan(self) -> None:
        # Que no se haya visto un error no quiere decir que no lo haya: el
        # sub-job del nivel 6 no se miró.
        hijo = _sub("nivel_6")
        for n in range(5, 0, -1):
            hijo = _sub(f"nivel_{n}", hijos=[hijo])
        self.assertEqual(child_job_errors({"child_jobs": [hijo]}), ([], True))

    def test_name_que_no_es_texto_da_job_null(self) -> None:
        errores, _ = child_job_errors({"child_jobs": [_sub(42, [_err("f")])]})
        self.assertEqual(errores, [{"job": None, "message": "f"}])

    def test_job_errors_sigue_mirando_solo_el_nivel_superior(self) -> None:
        data = {"done": True, "errors": [_err("propio")],
                "child_jobs": [_sub("x", [_err("del hijo")])]}
        self.assertEqual(job_errors(data), ["propio"])


# JWT centinela con la forma de uno real (cabecera, payload y firma base64url).
_JWT = ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJjZW50aW5lbGEtMDI3In0"
        ".c2VudGluZWxhLWZpcm1hLTAyNy1jZW50aW5lbGE")


class TestRedactarAntesDeRecortar(unittest.TestCase):
    """T028: un secreto que cruza el carácter 500 no sale a medias.

    Recortar antes de redactar dejaba un JWT cortado que ya no encajaba en el
    patrón: salían su cabecera y parte del payload. Se prueba en `errors`
    (`job_errors`) y en `child_errors` (`child_job_errors`), con el JWT
    empezando 5, 10 y 30 caracteres antes del corte.

    Control negativo comprobado: volver a `redact_secrets(mensaje[:500])` en
    `_redactar_y_recortar` → los dos tests en rojo en los tres cortes (sale
    `eyJh…`).
    """

    def _mensajes(self, antes: int) -> list[dict]:
        return [_err("x" * (JOB_ERROR_MAX_CHARS - antes) + " " + _JWT + " fin")]

    def test_errors_no_deja_el_jwt_a_medias(self) -> None:
        for antes in (5, 10, 30):
            with self.subTest(antes=antes):
                (mensaje,) = job_errors({"errors": self._mensajes(antes)})
                self.assertLessEqual(len(mensaje), JOB_ERROR_MAX_CHARS)
                self.assertNotIn("eyJ", mensaje)

    def test_child_errors_no_deja_el_jwt_a_medias(self) -> None:
        for antes in (5, 10, 30):
            with self.subTest(antes=antes):
                errores, _ = child_job_errors(
                    {"child_jobs": [_sub("backup_store_apps", self._mensajes(antes))]})
                self.assertLessEqual(len(errores[0]["message"]), JOB_ERROR_MAX_CHARS)
                self.assertNotIn("eyJ", errores[0]["message"])

    def test_el_jwt_entero_se_tapa(self) -> None:
        (mensaje,) = job_errors({"errors": [_err("fallo " + _JWT)]})
        self.assertNotIn("eyJ", mensaje)
        self.assertIn("REDACTED", mensaje)


class TestSondeoSubJobs(unittest.IsolatedAsyncioTestCase):
    """FR-017: el safety backup con un sub-job fallido no deja escribir (D-1)."""

    def test_evaluar_job_cuenta_los_sub_jobs(self) -> None:
        data = {"done": True, "errors": [],
                "child_jobs": [_sub("backup_store_apps", [_err("Can't back up <slug>")])]}
        self.assertEqual(_evaluar_job(data),
                         ("fallo", ["backup_store_apps: Can't back up <slug>"]))

    def test_evaluar_job_sub_job_sin_nombre(self) -> None:
        data = {"done": True, "errors": [], "child_jobs": [_sub(None, [_err("f")])]}
        self.assertEqual(_evaluar_job(data), ("fallo", ["sub-job: f"]))

    def test_evaluar_job_recortado_es_fallo(self) -> None:
        resultado, mensajes = _evaluar_job(_cadena(7))
        self.assertEqual(resultado, "fallo")
        self.assertIn("limit reached", mensajes[-1])

    def test_evaluar_job_sin_errores_sigue_siendo_ok(self) -> None:
        self.assertEqual(_evaluar_job({"done": True, "errors": []}), ("ok", []))
        self.assertEqual(
            _evaluar_job({"done": True, "errors": [], "child_jobs": [_sub("x")]}),
            ("ok", []))
        self.assertEqual(_evaluar_job({"done": False, "errors": [],
                                       "child_jobs": [_sub("x", [_err("f")])]}),
                         ("en_curso", []))

    def test_evaluar_job_centinela_tapado(self) -> None:
        data = {"done": True, "errors": [],
                "child_jobs": [_sub("x", [_err(f"password={_CENTINELA}")])]}
        resultado, mensajes = _evaluar_job(data)
        self.assertEqual(resultado, "fallo")
        self.assertNotIn(_CENTINELA, " ".join(mensajes))

    async def test_la_escritura_se_rechaza_sin_marca_de_backup_correcto(self) -> None:
        import hermes.tools.backups as backups

        async def _sin_espera(_segundos: float) -> None:
            return None

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            backups, "_SAFETY_BACKUP_STATE_PATH", Path(tmp) / "last_safety_backup.json"
        ), patch("asyncio.sleep", side_effect=_sin_espera):
            vieja = time.time() - 31 * 60
            backups._save_safety_state({backups._MARCA: vieja})
            job = {"name": "backup_manager_full_backup", "done": True, "errors": [],
                   "progress": 100, "reference": "<slug>",
                   "child_jobs": [_sub("backup_store_apps",
                                       [_err("Can't create backup for <slug>")])]}
            sv = _SupervisorDeJobs(lambda path: job)
            result = await maybe_trigger_safety_backup(
                sv, safety_backup_window_minutes=30, enabled=True)
            self.assertIsNotNone(result)
            self.assertIn("safety_backup_job_failed", result["error"])
            self.assertIn("backup_store_apps: Can't create backup", result["error"])
            # El backup incompleto no cuenta como el último correcto.
            self.assertEqual(backups._leer_marca(backups._load_safety_state()), vieja)


if __name__ == "__main__":
    unittest.main()
