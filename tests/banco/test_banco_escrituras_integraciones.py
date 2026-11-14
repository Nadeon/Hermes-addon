"""Banco de Core: config entries, flujos y el entorno de `kitchen_sink` (spec 028, tramo B).

- `TestEntornoKitchenSink` (T017): antes de probar ninguna tool, el lector
  comprueba que `kitchen_sink` cargó en la HA del banco con lo que necesitan
  las pruebas del tramo B (entrada `loaded`, avisos de reparación propios y
  dispositivos que se pueden borrar además de `statistics_issues`). Si esto
  cae, el resto del tramo no prueba nada: falla aquí con el motivo.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras

pytestmark = pytest.mark.banco


async def entrada_kitchen_sink(s: SesionEscrituras) -> dict[str, Any] | None:
    """La config entry de `kitchen_sink` que importa su YAML, o None."""
    entradas = await s.lector.comando({"type": "config_entries/get", "domain": "kitchen_sink"})
    return entradas[0] if entradas else None


async def dispositivos_kitchen_sink(s: SesionEscrituras) -> list[dict[str, Any]]:
    """Dispositivos del registro con un identificador de `kitchen_sink`."""
    return [
        d
        for d in await s.lector.comando({"type": "config/device_registry/list"})
        if any(i[0] == "kitchen_sink" for i in d.get("identifiers", []))
    ]


def es_statistics_issues(dispositivo: dict[str, Any]) -> bool:
    # El único dispositivo de kitchen_sink que su integración no deja borrar
    # (`async_remove_config_entry_device` devuelve False): ninguna prueba lo usa.
    return ["kitchen_sink", "statistics_issues"] in dispositivo.get("identifiers", [])


class TestEntornoKitchenSink(BancoEscrituras):
    async def test_kitchen_sink_cargada(self) -> None:
        async with self.sesion() as s:
            # La entrada se importa en una tarea tras el arranque: se espera.
            entrada = await s.lector.esperar(
                lambda: entrada_kitchen_sink(s),
                lambda e: e is not None and e["state"] == "loaded",
                descripcion="config entry de kitchen_sink en estado loaded",
            )
            self.assertIsNone(entrada["disabled_by"])

            avisos = await s.lector.esperar(
                lambda: s.lector.comando({"type": "repairs/list_issues"}),
                lambda r: any(i["domain"] == "kitchen_sink" for i in r["issues"]),
                descripcion="avisos de reparación de kitchen_sink",
            )
            self.assertTrue(any(i["domain"] == "kitchen_sink" for i in avisos["issues"]))

            dispositivos = await dispositivos_kitchen_sink(s)
            borrables = [d for d in dispositivos if not es_statistics_issues(d)]
            # Hacen falta al menos dos: uno para `ha_remove_device` y otro
            # para `ha_remove_device_from_config_entry`.
            self.assertGreaterEqual(
                len(borrables), 2, f"dispositivos de kitchen_sink: {dispositivos!r}"
            )
