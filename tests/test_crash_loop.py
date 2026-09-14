"""La guarda de crash loop tiene que disparar antes de que el watchdog se rinda.

Tres cosas fallaban a la vez y, entre las tres, la guarda no llegó a saltar
nunca en el incidente real del 2026-09-06 (once arranques en dos minutos con
`config_validation_failed`):

  1. `check_crash_loop()` se llamaba dentro de `_boot`, DESPUÉS de
     `config.validate()` en `main()`. Una config inválida sale por `sys.exit(1)`
     antes, así que el caso que más reinicia en bucle —una opción mal puesta—
     no se contaba jamás.
  2. Un `startup_log.json` corrupto no se reescribía nunca: el fichero se
     quedaba ilegible para siempre y la guarda, desactivada para siempre.
  3. El umbral era `> CRASH_THRESHOLD`, o sea 12 arranques reales. El watchdog
     del Supervisor se rinde sobre el 10º-11º, así que la guarda siempre
     llegaba tarde.
"""

from __future__ import annotations

import inspect
import json
import time
import unittest
import unittest.mock as mock
from pathlib import Path
from tempfile import TemporaryDirectory

from hermes import crash_loop
from hermes.crash_loop import (
    CRASH_THRESHOLD,
    CRASH_WINDOW_SECONDS,
    RING_BUFFER_SIZE,
    check_crash_loop,
)


class TestCheckCrashLoop(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "startup_log.json"
        patcher = mock.patch.object(crash_loop, "STARTUP_LOG_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _escribir(self, entradas: list[float]) -> None:
        self.path.write_text(json.dumps(entradas), encoding="utf-8")

    def _leer(self) -> list[float]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    # ── Umbral ──────────────────────────────────────────────

    def test_el_arranque_numero_11_dispara(self) -> None:
        """10 entradas previas en la ventana = 11º arranque real."""
        ahora = time.time()
        self._escribir([ahora - i for i in range(CRASH_THRESHOLD)])

        with self.assertRaises(SystemExit) as ctx:
            check_crash_loop()

        self.assertEqual(ctx.exception.code, 1)

    def test_el_arranque_numero_10_todavia_no_dispara(self) -> None:
        ahora = time.time()
        self._escribir([ahora - i for i in range(CRASH_THRESHOLD - 1)])

        check_crash_loop()  # no debe salir

        self.assertEqual(len(self._leer()), CRASH_THRESHOLD)

    def test_al_disparar_no_escribe_nada(self) -> None:
        """Proteger el disco es el motivo de la guarda: no tocarlo al abortar."""
        ahora = time.time()
        entradas = [ahora - i for i in range(CRASH_THRESHOLD)]
        self._escribir(entradas)

        with self.assertRaises(SystemExit):
            check_crash_loop()

        self.assertEqual(self._leer(), entradas)

    def test_los_arranques_viejos_no_cuentan(self) -> None:
        """Fuera de la ventana de 5 minutos no hay crash loop que valga."""
        ahora = time.time()
        self._escribir(
            [ahora - CRASH_WINDOW_SECONDS - 10 - i for i in range(RING_BUFFER_SIZE)]
        )

        check_crash_loop()  # no debe salir

        self.assertEqual(len(self._leer()), RING_BUFFER_SIZE)

    # ── Fichero corrupto ────────────────────────────────────

    def test_un_fichero_corrupto_se_reescribe(self) -> None:
        """Antes se dejaba intacto y la guarda quedaba muerta para siempre."""
        self.path.write_text("{esto no es json", encoding="utf-8")

        check_crash_loop()

        entradas = self._leer()
        self.assertEqual(
            len(entradas), 1, "el fichero corrupto debe quedar como [ahora]"
        )
        self.assertAlmostEqual(entradas[0], time.time(), delta=30)

    def test_tras_reescribir_la_guarda_vuelve_a_contar(self) -> None:
        """El objetivo de reescribir: que el siguiente arranque ya sume."""
        self.path.write_text("\x00\x00 basura", encoding="utf-8")

        check_crash_loop()
        check_crash_loop()

        self.assertEqual(len(self._leer()), 2)

    def test_un_json_que_no_es_lista_tambien_se_recupera(self) -> None:
        self.path.write_text('{"arranques": 3}', encoding="utf-8")

        check_crash_loop()

        self.assertEqual(len(self._leer()), 1)

    # ── Registro normal ─────────────────────────────────────

    def test_sin_fichero_previo_crea_el_registro(self) -> None:
        check_crash_loop()
        self.assertEqual(len(self._leer()), 1)

    def test_el_ring_buffer_acota_el_fichero(self) -> None:
        ahora = time.time()
        # Entradas viejas (no disparan) pero muchas: el fichero no debe crecer.
        self._escribir(
            [ahora - CRASH_WINDOW_SECONDS - 100 - i for i in range(RING_BUFFER_SIZE + 5)]
        )

        check_crash_loop()

        self.assertLessEqual(len(self._leer()), RING_BUFFER_SIZE)


class TestOrdenDeArranque(unittest.TestCase):
    """El paso 2 debe ir ANTES de validar la config, no dentro de `_boot`."""

    def test_el_crash_loop_se_comprueba_antes_de_validar_la_config(self) -> None:
        import hermes.__main__ as main_mod

        fuente = inspect.getsource(main_mod.main)
        pos_crash = fuente.find("check_crash_loop()")
        pos_validate = fuente.find("config.validate()")

        self.assertNotEqual(
            pos_crash, -1, "check_crash_loop() debe llamarse desde main()"
        )
        self.assertNotEqual(pos_validate, -1)
        self.assertLess(
            pos_crash,
            pos_validate,
            "una config inválida sale por sys.exit(1) en main(): si el crash "
            "loop se comprueba después, el bucle por config_validation_failed "
            "no se cuenta nunca",
        )

    def test_boot_ya_no_comprueba_el_crash_loop(self) -> None:
        """Si siguiera ahí, se contaría dos veces por arranque."""
        import hermes.__main__ as main_mod

        fuente = inspect.getsource(main_mod._boot)
        self.assertNotIn("check_crash_loop()", fuente)


if __name__ == "__main__":
    unittest.main()
