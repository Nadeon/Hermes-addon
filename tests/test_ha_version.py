"""Tests de `hermes.ha_version` (FR-017, FR-018, FR-036, FR-038).

Varias tools tienen que decidir QUÉ comando usarán según la versión de Home
Assistant antes de ejecutar nada, para que la preview diga la verdad. Si la
versión no se puede leer, el helper devuelve `None` en vez de adivinar: la
tool decide entonces cómo negarse.
"""

from __future__ import annotations

import unittest
from typing import Any

from packaging.version import Version

from hermes.ha import HAConnectionError
from hermes.ha_version import ha_at_least, ha_core_version


class FakeHA:
    """Cliente mínimo: responde a `get_config` con lo que se le indique."""

    def __init__(self, respuesta: Any = None, error: Exception | None = None) -> None:
        self.respuesta = respuesta
        self.error = error
        self.llamadas: list[tuple[dict[str, Any], int]] = []

    async def ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.llamadas.append((payload, timeout_seconds))
        if self.error is not None:
            raise self.error
        return self.respuesta


class TestHaCoreVersion(unittest.IsolatedAsyncioTestCase):
    async def test_version_normal(self) -> None:
        ha = FakeHA({"version": "2026.11.1"})
        self.assertEqual(await ha_core_version(ha), Version("2026.11.1"))
        self.assertEqual(ha.llamadas, [({"type": "get_config"}, 5)])

    async def test_version_dev_compara_por_base(self) -> None:
        ha = FakeHA({"version": "2026.12.0.dev0"})
        self.assertEqual(await ha_core_version(ha), Version("2026.12.0"))

    async def test_version_no_parseable(self) -> None:
        self.assertIsNone(await ha_core_version(FakeHA({"version": "landingpage"})))

    async def test_error_ws(self) -> None:
        ha = FakeHA(error=HAConnectionError("caída"))
        self.assertIsNone(await ha_core_version(ha))

    async def test_respuesta_no_dict(self) -> None:
        self.assertIsNone(await ha_core_version(FakeHA(["2026.11.1"])))

    async def test_sin_campo_version(self) -> None:
        self.assertIsNone(await ha_core_version(FakeHA({"location_name": "x"})))


class TestHaAtLeast(unittest.IsolatedAsyncioTestCase):
    async def test_mayor_o_igual(self) -> None:
        self.assertIs(await ha_at_least(FakeHA({"version": "2026.11.1"}), "2026.9.0"), True)
        self.assertIs(await ha_at_least(FakeHA({"version": "2026.9.0"}), "2026.9.0"), True)

    async def test_dev_de_la_version_minima_cuenta(self) -> None:
        # Una .dev0 de 2026.9.0 ya trae el cambio: compara por base_version.
        self.assertIs(
            await ha_at_least(FakeHA({"version": "2026.9.0.dev0"}), "2026.9.0"), True
        )

    async def test_menor(self) -> None:
        self.assertIs(await ha_at_least(FakeHA({"version": "2026.8.3"}), "2026.9.0"), False)

    async def test_desconocida(self) -> None:
        self.assertIsNone(await ha_at_least(FakeHA({"version": "landingpage"}), "2026.9.0"))
        self.assertIsNone(
            await ha_at_least(FakeHA(error=HAConnectionError("x")), "2026.9.0")
        )

    async def test_sin_cache(self) -> None:
        # Spec S-03: HA puede actualizarse sin reiniciar Hermes; cada consulta
        # debe preguntar de nuevo.
        ha = FakeHA({"version": "2026.8.0"})
        self.assertIs(await ha_at_least(ha, "2026.9.0"), False)
        ha.respuesta = {"version": "2026.9.1"}
        self.assertIs(await ha_at_least(ha, "2026.9.0"), True)
        self.assertEqual(len(ha.llamadas), 2)


if __name__ == "__main__":
    unittest.main()
