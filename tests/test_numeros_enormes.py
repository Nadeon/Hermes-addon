"""Enteros enormes (`10**400`, JSON válido) en las tools (cierre de
robustez de la 1.2.0).

No caben en un float: `math.isfinite(x)` y `float(x)` lanzan
`OverflowError`, que tumbaba la tool en vez de dar un error de argumento o
tratar el valor como no numérico. Los casos que pasan por una tool entera
están en sus propios ficheros (`ha_get_system_health`,
`ha_list_integration_setup_times`, `ha_update_core_config`, `sv_set_swap`);
aquí van los auxiliares que no tienen una entrada cómoda.

Control negativo comprobado: con la versión anterior de cada función (sin
`es_numero_finito` ni `OverflowError` en el `except`), cada caso lanza
`OverflowError`.
"""

from __future__ import annotations

import unittest

from hermes.tools import backups, core_logs, statistics, templates, wait_for_event
from hermes.tools._validation import es_numero_finito

_ENORME = 10**400


class TestEsNumeroFinito(unittest.TestCase):
    def test_casos(self) -> None:
        for valor, esperado in ((1, True), (1.5, True), (_ENORME, False),
                                (-_ENORME, False), (float("inf"), False),
                                (float("nan"), False), (True, False), ("1", False),
                                (None, False)):
            with self.subTest(valor=type(valor).__name__):
                self.assertIs(es_numero_finito(valor), esperado)


class TestAuxiliares(unittest.TestCase):
    def test_estadisticas_dejan_el_valor_tal_cual(self) -> None:
        punto = statistics._expand_stat_point(
            {"start": _ENORME, "end": 1.0e300, "mean": _ENORME})
        # Ninguno es una fecha representable: van tal cual, sin excepción.
        self.assertEqual(punto, {"start": _ENORME, "end": 1.0e300, "mean": _ENORME})
        # Y una fecha normal se sigue convirtiendo.
        self.assertTrue(statistics._expand_stat_point({"start": 0})["start"]
                        .startswith("1970-01-01"))

    def test_marca_de_backup(self) -> None:
        self.assertEqual(backups._leer_marca({"last_safety_backup_at": _ENORME}), 0)

    def test_tamano_de_backup(self) -> None:
        self.assertIsNone(backups._size_mb({"size_bytes": _ENORME, "size": _ENORME}))

    def test_marca_de_tiempo_del_log(self) -> None:
        self.assertEqual(core_logs._marca_tiempo({"timestamp": _ENORME}), float("-inf"))

    def test_timeout_de_plantilla(self) -> None:
        self.assertEqual(templates._clamp_timeout(_ENORME), templates._RENDER_TIMEOUT_MIN)

    def test_filtro_de_espera(self) -> None:
        self.assertFalse(wait_for_event._compare_value(_ENORME, ">1"))


if __name__ == "__main__":
    unittest.main()
