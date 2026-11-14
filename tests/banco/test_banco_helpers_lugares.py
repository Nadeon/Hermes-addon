"""Banco de Core: las 6 tools de escritura de `zone` y `person` (spec 010, US2, T027).

Zona en las coordenadas de ejemplo de la configuración por defecto de HA (las
mismas que `tests/banco/ha_config/configuration.yaml`), no las de nadie.
Persona con un nombre inventado. `ha_create_person` no pide confirmación (crear
no pisa nada); editar y borrar, sí. La persona del usuario del onboarding tiene
que seguir ahí al terminar.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

import pytest

from tests.banco.base_helpers import BancoHelpers, nombre_de_prueba, sin_error
from tests.banco.entorno import llamar

pytestmark = pytest.mark.banco

LATITUD = 32.87336
LONGITUD = -117.22743


class TestZone(BancoHelpers):
    async def test_ciclo_completo(self) -> None:
        nombre = nombre_de_prueba("zone")
        async with self.sesion() as s:
            creado = await s.crear(
                "ha_create_or_update_zone", "zone",
                {"name": nombre, "latitude": LATITUD, "longitude": LONGITUD, "radius": 100},
            )
            self.assertEqual(
                (creado["latitude"], creado["longitude"], creado["radius"]),
                (LATITUD, LONGITUD, 100),
            )
            editado = await s.editar(
                "ha_create_or_update_zone", "zone", nombre, {"radius": 250}
            )
            self.assertEqual((editado["latitude"], editado["longitude"]), (LATITUD, LONGITUD))
            await s.esperar_estado(
                f"zone.{nombre}", lambda e: e["attributes"].get("radius") == 250, "radio 250"
            )

            await s.recargar("ha_reload_zones", "zone", nombre)
            await s.borrar("ha_delete_zone", "zone", nombre)


class TestPerson(BancoHelpers):
    async def test_ciclo_completo(self) -> None:
        sufijo = nombre_de_prueba("person").rsplit("_", 1)[1]
        nombre = f"Persona Banco {sufijo}"
        id_ = f"persona_banco_{sufijo}"
        async with self.sesion() as s:
            # Las personas con usuario (la del onboarding) no se tocan.
            con_usuario = [p["id"] for p in await s.items("person") if p.get("user_id")]
            self.assertTrue(con_usuario, "falta la persona del usuario del onboarding")

            s.creados.append(("person", id_))
            creada = sin_error(
                "ha_create_person", await llamar(s.cliente, "ha_create_person", name=nombre)
            )
            self.assertEqual(creada["entity_id"], f"person.{id_}")
            elemento = await s.lector.esperar(
                lambda: s.item("person", id_),
                lambda e: e is not None,
                descripcion=f"person {id_} en person/list",
            )
            self.assertEqual(elemento["name"], nombre)

            editado = await s.editar(
                "ha_update_person", "person", id_, {"name": f"{nombre} editada"}
            )
            self.assertEqual(editado["device_trackers"], [])

            await s.borrar("ha_delete_person", "person", id_)

            siguen = [p["id"] for p in await s.items("person") if p.get("user_id")]
            self.assertEqual(siguen, con_usuario)
