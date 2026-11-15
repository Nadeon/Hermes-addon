"""Banco de Core: preferencias del panel de energía (spec 020, tramo 3, T047).

`ha_get_energy_prefs` y `ha_update_energy_prefs` contra HA Core real (con
`energy:` en `ha_config/configuration.yaml`), con el lector independiente
(directo a Core, sin Hermes) leyendo `energy/get_prefs` antes y después:

- **Siembra**: el lector importa una estadística de energía
  (`sensor.banco_<sufijo>_consumo`, kWh, con suma) y una de intensidad de CO2
  (`sensor.banco_<sufijo>_co2`, %, con media) y espera a verlas. Las borra al
  cerrar.
- **Leer**: `ha_get_energy_prefs` da lo mismo que el lector (o
  `configured: false` si el banco no tenía preferencias).
- **Guardar** `device_consumption=[<la sembrada>]`: la vista previa no cambia
  nada (el lector ve lo de antes) y no avisa de esa estadística (existe);
  tras confirmar, el lector ve el dispositivo y las fuentes intactas.
- **Cambiadas entre medias**: otra vista previa, el lector guarda otra cosa
  y la confirmación responde `energy_prefs_changed` sin guardar.
- **Las cuatro lecturas** por `ha_read_ws_command` responden;
  `energy/fossil_energy_consumption` con las dos estadísticas sembradas.
- **Limpieza**: el lector vuelve a guardar las tres listas de antes. Si el
  banco no tenía preferencias, guarda las tres vacías: HA no tiene comando
  para borrarlas, y unas preferencias vacías son, para el panel y para los
  demás tests (ninguno lee la energía), lo mismo que no tenerlas.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
Inventario: `tests/banco/cobertura_020.py`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo
from tests.banco.lector import ErrorCore

pytestmark = pytest.mark.banco

_ESPERA = 30.0
_FILAS = 6
_LISTAS = ("energy_sources", "device_consumption", "device_consumption_water")


def _inicio() -> datetime:
    ahora = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return ahora - timedelta(days=2)


async def _prefs(s: SesionEscrituras) -> dict[str, Any] | None:
    """Preferencias según el lector; `None` si nunca se guardaron."""
    try:
        return await s.lector.comando({"type": "energy/get_prefs"})
    except ErrorCore as exc:
        if exc.codigo == "not_found":
            return None
        raise


def _listas(prefs: dict[str, Any] | None) -> dict[str, list[Any]]:
    return {n: list((prefs or {}).get(n) or []) for n in _LISTAS}


async def _filas(s: SesionEscrituras, statistic_id: str, inicio: datetime) -> list[Any]:
    datos = await s.lector.comando({
        "type": "recorder/statistics_during_period",
        "start_time": inicio.isoformat(),
        "end_time": (inicio + timedelta(hours=_FILAS)).isoformat(),
        "statistic_ids": [statistic_id], "period": "hour"})
    return list((datos or {}).get(statistic_id) or [])


async def _sembrar(s: SesionEscrituras, statistic_id: str, inicio: datetime, *,
                   co2: bool) -> None:
    async def limpiar() -> None:
        await s.lector.comando({"type": "recorder/clear_statistics",
                                "statistic_ids": [statistic_id]})

    s.limpiezas.append(limpiar)
    if co2:
        metadata = {"statistic_id": statistic_id, "source": "recorder", "name": None,
                    "unit_of_measurement": "%", "unit_class": None,
                    "mean_type": 1, "has_sum": False}
        stats = [{"start": (inicio + timedelta(hours=i)).isoformat(),
                  "mean": 40.0, "min": 40.0, "max": 40.0} for i in range(_FILAS)]
    else:
        metadata = {"statistic_id": statistic_id, "source": "recorder", "name": None,
                    "unit_of_measurement": "kWh", "unit_class": "energy",
                    "mean_type": 0, "has_sum": True}
        stats = [{"start": (inicio + timedelta(hours=i)).isoformat(),
                  "state": float(i), "sum": float(i + 1)} for i in range(_FILAS)]
    await s.lector.comando({"type": "recorder/import_statistics",
                            "metadata": metadata, "stats": stats})
    await s.lector.esperar(lambda: _filas(s, statistic_id, inicio),
                           lambda filas: len(filas) == _FILAS,
                           descripcion=f"{_FILAS} filas sembradas", timeout=_ESPERA)


class TestPreferenciasDeEnergia(BancoEscrituras):
    async def test_leer_guardar_y_cambiadas_entre_medias(self) -> None:
        tool = "ha_update_energy_prefs"
        marca = sufijo()
        consumo, co2 = f"sensor.banco_{marca}_consumo", f"sensor.banco_{marca}_co2"
        inicio = _inicio()
        async with self.sesion() as s:
            await _sembrar(s, consumo, inicio, co2=False)
            await _sembrar(s, co2, inicio, co2=True)
            antes = await _prefs(s)

            async def restaurar() -> None:
                await s.lector.comando({"type": "energy/save_prefs", **_listas(antes)})

            s.limpiezas.append(restaurar)

            # Leer: lo mismo que el lector.
            leido = await s.accion("ha_get_energy_prefs")
            self.assertEqual(leido, {"configured": antes is not None, **_listas(antes)})

            # Guardar un dispositivo: la vista previa no cambia nada.
            dispositivo = {"stat_consumption": consumo}
            vista = await s.vista(tool, device_consumption=[dispositivo])
            p = vista["preview"]
            self.assertEqual(p["kept"], ["energy_sources", "device_consumption_water"])
            self.assertEqual(p["new"], {"device_consumption": [dispositivo]})
            self.assertEqual([a for a in p["warnings"] if a["problem"] == "unknown_statistic"],
                             [])
            self.assertEqual(_listas(await _prefs(s)), _listas(antes))

            hecho = await s.confirmar(tool, vista, device_consumption=[dispositivo])
            self.assertIs(hecho["saved"], True)
            self.assertEqual(hecho["prefs"]["device_consumption"], [dispositivo])
            despues = _listas(await _prefs(s))
            self.assertEqual(despues["device_consumption"], [dispositivo])
            self.assertEqual(despues["energy_sources"], _listas(antes)["energy_sources"])

            # Cambiadas por otro entre la vista previa y la confirmación.
            vista = await s.vista(tool, device_consumption=[])
            await s.lector.comando({"type": "energy/save_prefs",
                                    "device_consumption_water": [dispositivo]})
            resultado = await s.cliente.call_tool(
                tool, {"device_consumption": [],
                       "confirmation_token": vista["confirmation_token"]})
            self.assertTrue(getattr(resultado, "is_error", False))
            error = json.loads(resultado.content[0].text)
            self.assertEqual(error["error"], "energy_prefs_changed")
            # No se guardó: el dispositivo sigue ahí.
            self.assertEqual(_listas(await _prefs(s))["device_consumption"], [dispositivo])

            # Las cuatro lecturas de energía por la genérica de lectura.
            lecturas = {
                "energy/validate": None,
                "energy/info": None,
                "energy/solar_forecast": None,
                "energy/fossil_energy_consumption": {
                    "start_time": inicio.isoformat(),
                    "end_time": (inicio + timedelta(hours=_FILAS)).isoformat(),
                    "energy_statistic_ids": [consumo], "co2_statistic_id": co2,
                    "period": "hour"},
            }
            for comando, carga in lecturas.items():
                with self.subTest(comando=comando):
                    args: dict[str, Any] = {"type": comando}
                    if carga is not None:
                        args["payload"] = carga
                    r = await s.accion("ha_read_ws_command", **args)
                    self.assertIsInstance(r.get("result"), dict, r)
