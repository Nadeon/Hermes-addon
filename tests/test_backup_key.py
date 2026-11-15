"""Clave de cifrado de los backups de HA (spec 031, tramo 2: T017; FR-011).

`leer_clave_de_backups` con `ws_send` simulado. La clave centinela no puede
salir en el `repr`, el `str` ni el log, y cada llamada vuelve a leer (sin
caché: un cambio de clave en HA se respeta en el siguiente uso).

Control negativo (T030 a), comprobado: con `ClaveDeBackups` sin su
`__repr__` propio (el del dataclass) cae `test_repr_y_str_no_la_sacan`.
"""

from __future__ import annotations

import unittest
from typing import Any

from structlog.testing import capture_logs

from hermes.backup_key import ClaveDeBackups, leer_clave_de_backups
from hermes.ha import HAConnectionError

_CENTINELA = "centinela-031"


class _HA:
    def __init__(self, respuesta: Any) -> None:
        self.respuesta = respuesta
        self.llamadas: list[tuple[dict[str, Any], int]] = []

    async def ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.llamadas.append((payload, timeout_seconds))
        if isinstance(self.respuesta, Exception):
            raise self.respuesta
        return self.respuesta


def _info(password: Any) -> dict[str, Any]:
    return {"config": {"create_backup": {"agent_ids": [], "password": password}}}


class TestLeerClave(unittest.IsolatedAsyncioTestCase):
    async def test_con_clave(self) -> None:
        ha = _HA(_info(_CENTINELA))
        with capture_logs() as logs:
            r = await leer_clave_de_backups(ha)
        self.assertEqual(r, ClaveDeBackups(clave=_CENTINELA, motivo=None))
        self.assertEqual(ha.llamadas[0][0], {"type": "backup/config/info"})
        # Plazo corto: va delante de crear un backup.
        self.assertLessEqual(ha.llamadas[0][1], 10)
        self.assertNotIn(_CENTINELA, repr(logs))

    async def test_sin_clave(self) -> None:
        for valor in (None, ""):
            with self.subTest(valor=valor):
                r = await leer_clave_de_backups(_HA(_info(valor)))
                self.assertEqual((r.clave, r.motivo), (None, "no_key_configured"))

    async def test_sin_integracion(self) -> None:
        r = await leer_clave_de_backups(
            _HA(HAConnectionError("Unknown command.", code="unknown_command")))
        self.assertEqual((r.clave, r.motivo), (None, "backup_integration_unavailable"))

    async def test_ha_inalcanzable(self) -> None:
        r = await leer_clave_de_backups(_HA(HAConnectionError("WebSocket no disponible")))
        self.assertEqual((r.clave, r.motivo), (None, "ha_unreachable"))

    async def test_respuesta_sin_config(self) -> None:
        for respuesta in ({}, None, {"config": "x"}, {"config": {"create_backup": 1}},
                          _info(123)):
            with self.subTest(respuesta=respuesta):
                r = await leer_clave_de_backups(_HA(respuesta))
                self.assertEqual((r.clave, r.motivo), (None, "backup_integration_unavailable"))

    async def test_repr_y_str_no_la_sacan(self) -> None:
        r = await leer_clave_de_backups(_HA(_info(_CENTINELA)))
        self.assertNotIn(_CENTINELA, repr(r))
        self.assertNotIn(_CENTINELA, str(r))
        self.assertNotIn(_CENTINELA, f"{r}")
        self.assertIn("<oculta>", repr(r))

    async def test_sin_cache(self) -> None:
        ha = _HA(_info(_CENTINELA))
        await leer_clave_de_backups(ha)
        ha.respuesta = _info("otra")
        r = await leer_clave_de_backups(ha)
        self.assertEqual(len(ha.llamadas), 2)
        self.assertEqual(r.clave, "otra")
