"""Banco de Core: mantenimiento de estadísticas (spec 020, tramo 1, T015).

Las tres tools de `statistics_maintenance` del tramo 1 contra HA Core real,
con el lector independiente (directo a Core, sin Hermes) sembrando las
estadísticas y comprobando cada efecto:

- **Siembra**: el lector importa con `recorder/import_statistics` una
  estadística de entidad (`sensor.banco_<sufijo>_energia`, `source:
  recorder`, kWh, clase `energy`, con suma, 24 filas horarias de hace dos
  días) y una externa (`banco:<sufijo>_externa`), y espera a verlas con
  `recorder/statistics_during_period` (el import va por la cola del
  recorder). Al cerrar, las borra con `recorder/clear_statistics`, pase lo
  que pase. No hay entidad con ese id, así que el lector lee los valores tal
  como están guardados (sin conversión a la unidad de un estado).
- **Borrar** (`ha_clear_statistics`): con un rango de 3 horas la vista previa
  no cambia nada (el lector sigue viendo las 24 filas) y, tras confirmar, el
  lector no ve ninguna fila dentro del rango efectivo que dio la vista previa
  (21 o menos). Sin rango, la externa desaparece de
  `recorder/list_statistic_ids`.
- **Cambiar la unidad** (`ha_change_statistics_unit`) kWh → Wh: la vista
  previa no cambia nada; la confirmación responde `queued: true` y el lector,
  con un sondeo acotado (decisión D-1: Hermes no espera a la cola), ve la
  unidad `Wh` y la suma ×1000. Sobre la externa, `not_supported_for_source`
  sin token.
- **Metadatos** (`ha_update_statistics_metadata`) a `MWh`/`energy`: el lector
  ve la unidad nueva y los MISMOS valores (no convierte).

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
Inventario: `tests/banco/cobertura_020.py`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo

pytestmark = pytest.mark.banco

# El recorder confirma en la base cada pocos segundos (`commit_interval`):
# lo encolado puede tardar en verse.
_ESPERA = 30.0
_FILAS = 24


def _inicio() -> datetime:
    """La primera hora sembrada: en punto, hace dos días (UTC)."""
    ahora = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return ahora - timedelta(days=2)


async def _rechazo(s: SesionEscrituras, tool: str, **args: Any) -> dict[str, Any]:
    """Llama a una tool que DEBE rechazar y devuelve su `{"error": …}`."""
    resultado = await s.cliente.call_tool(tool, args)
    assert getattr(resultado, "is_error", False), f"{tool}: se esperaba un rechazo"
    return json.loads(resultado.content[0].text)


async def _filas(s: SesionEscrituras, statistic_id: str, inicio: datetime) -> list[dict[str, Any]]:
    """Filas horarias de la siembra según el lector (vacío si no hay)."""
    datos = await s.lector.comando({
        "type": "recorder/statistics_during_period",
        "start_time": (inicio - timedelta(hours=2)).isoformat(),
        "end_time": (inicio + timedelta(hours=_FILAS + 2)).isoformat(),
        "statistic_ids": [statistic_id],
        "period": "hour",
        "types": ["sum", "state"],
    })
    return list((datos or {}).get(statistic_id) or [])


async def _metadatos(s: SesionEscrituras, statistic_id: str) -> dict[str, Any] | None:
    lista = await s.lector.comando(
        {"type": "recorder/get_statistics_metadata", "statistic_ids": [statistic_id]})
    return next((m for m in lista or [] if m.get("statistic_id") == statistic_id), None)


async def _sembrar(s: SesionEscrituras, statistic_id: str, source: str,
                   inicio: datetime) -> None:
    """Importa 24 filas horarias con el lector y espera a verlas; las borra al cerrar."""

    async def limpiar() -> None:
        await s.lector.comando({"type": "recorder/clear_statistics",
                                "statistic_ids": [statistic_id]})

    s.limpiezas.append(limpiar)
    await s.lector.comando({
        "type": "recorder/import_statistics",
        "metadata": {
            "statistic_id": statistic_id, "source": source, "name": None,
            "unit_of_measurement": "kWh", "unit_class": "energy",
            "mean_type": 0, "has_sum": True,
        },
        "stats": [{"start": (inicio + timedelta(hours=i)).isoformat(),
                   "state": float(i), "sum": float(i + 1)} for i in range(_FILAS)],
    })
    await s.lector.esperar(lambda: _filas(s, statistic_id, inicio),
                           lambda filas: len(filas) == _FILAS,
                           descripcion=f"{_FILAS} filas sembradas", timeout=_ESPERA)


def _ms(fecha: str) -> float:
    return datetime.fromisoformat(fecha).timestamp() * 1000


class TestBorrarEstadisticas(BancoEscrituras):
    async def test_borrar_un_rango_y_una_entera(self) -> None:
        tool = "ha_clear_statistics"
        marca = sufijo()
        propia, externa = f"sensor.banco_{marca}_energia", f"banco:{marca}_externa"
        inicio = _inicio()
        async with self.sesion() as s:
            await _sembrar(s, propia, "recorder", inicio)
            await _sembrar(s, externa, "banco", inicio)

            args = {"statistic_ids": [propia],
                    "start_time": (inicio + timedelta(hours=10)).isoformat(),
                    "end_time": (inicio + timedelta(hours=13)).isoformat()}
            vista = await s.vista(tool, **args)
            p = vista["preview"]
            self.assertEqual(p["scope"], "range")
            self.assertEqual([x["statistic_id"] for x in p["statistics"]], [propia])
            efectivo = p["effective_range"]["hourly"]
            # La vista previa no ha borrado nada.
            self.assertEqual(len(await _filas(s, propia, inicio)), _FILAS)

            hecho = await s.confirmar(tool, vista, **args)
            self.assertEqual(hecho, {"cleared": True, "statistic_ids_count": 1, "scope": "range"})
            despues, antes = _ms(efectivo["after"]), _ms(efectivo["before"])
            filas = await s.lector.esperar(
                lambda: _filas(s, propia, inicio),
                lambda f: not any(despues < x["start"] < antes for x in f),
                descripcion="sin filas dentro del rango efectivo", timeout=_ESPERA)
            self.assertLessEqual(len(filas), _FILAS - 3)
            self.assertGreater(len(filas), 0)

            vista = await s.vista(tool, statistic_ids=[externa])
            self.assertIs(vista["preview"]["removes_metadata"], True)
            self.assertIsNotNone(await _metadatos(s, externa))
            await s.confirmar(tool, vista, statistic_ids=[externa])
            await s.lector.esperar(
                lambda: s.lector.comando({"type": "recorder/list_statistic_ids"}),
                lambda lista: externa not in {x["statistic_id"] for x in lista},
                descripcion="la externa fuera de list_statistic_ids", timeout=_ESPERA)


class TestUnidadesYMetadatos(BancoEscrituras):
    async def test_cambiar_la_unidad_convierte(self) -> None:
        tool = "ha_change_statistics_unit"
        marca = sufijo()
        propia, externa = f"sensor.banco_{marca}_energia", f"banco:{marca}_externa"
        inicio = _inicio()
        async with self.sesion() as s:
            await _sembrar(s, propia, "recorder", inicio)
            await _sembrar(s, externa, "banco", inicio)
            antes = {x["start"]: x["sum"] for x in await _filas(s, propia, inicio)}

            args = {"statistic_id": propia, "old_unit": "kWh", "new_unit": "Wh"}
            vista = await s.vista(tool, **args)
            self.assertEqual(vista["preview"]["unit_class"], "energy")
            self.assertEqual((await _metadatos(s, propia))["statistics_unit_of_measurement"], "kWh")

            hecho = await s.confirmar(tool, vista, **args)
            self.assertIs(hecho["queued"], True)
            # D-1: la tool no espera a la cola; el lector sondea con plazo.
            await s.lector.esperar(
                lambda: _metadatos(s, propia),
                lambda m: m is not None and m["statistics_unit_of_measurement"] == "Wh",
                descripcion="unidad Wh guardada", timeout=_ESPERA)
            despues = {x["start"]: x["sum"] for x in await _filas(s, propia, inicio)}
            self.assertEqual(set(despues), set(antes))
            for inicio_fila, suma in antes.items():
                self.assertAlmostEqual(despues[inicio_fila], suma * 1000, places=3)

            no = await _rechazo(s, tool, statistic_id=externa, old_unit="kWh", new_unit="Wh")
            self.assertEqual(no["error"], "not_supported_for_source")
            self.assertNotIn("confirmation_token", no)

    async def test_metadatos_sin_convertir(self) -> None:
        tool = "ha_update_statistics_metadata"
        propia = f"sensor.banco_{sufijo()}_energia"
        inicio = _inicio()
        async with self.sesion() as s:
            await _sembrar(s, propia, "recorder", inicio)
            antes = {x["start"]: x["sum"] for x in await _filas(s, propia, inicio)}

            args = {"statistic_id": propia, "unit_of_measurement": "MWh", "unit_class": "energy"}
            vista = await s.vista(tool, **args)
            self.assertEqual(vista["preview"]["current"],
                             {"unit_of_measurement": "kWh", "unit_class": "energy"})
            self.assertEqual((await _metadatos(s, propia))["statistics_unit_of_measurement"], "kWh")

            self.assertEqual(await s.confirmar(tool, vista, **args), {"updated": True})
            meta = await s.lector.esperar(
                lambda: _metadatos(s, propia),
                lambda m: m is not None and m["statistics_unit_of_measurement"] == "MWh",
                descripcion="unidad MWh guardada", timeout=_ESPERA)
            self.assertEqual(meta["unit_class"], "energy")
            despues = {x["start"]: x["sum"] for x in await _filas(s, propia, inicio)}
            self.assertEqual(despues, antes)
