"""Banco de Core: las 18 tools de escritura de `counter`, `timer` y `schedule`
(spec 010, US2, T026).

Igual que los `input_*`, y además: las recargas (`<dominio>.reload` visto en el
bus una sola vez y el helper de almacenamiento sigue), `ha_finish_timer` por el
evento `timer.finished` (el estado `idle` solo no lo distingue de cancelar) y
`ha_change_timer` sobre un temporizador activo, con `remaining` menor.

`ha_reload_counters` (spec 033, FR-004): Core 2026.11.1 no tiene
`counter.reload`, así que la tool responde `not_supported` sin llamar a HA.
No modifica nada y no puede ser «probada»: está en `NO_EJECUTABLES` con su
motivo. `TestCounter.test_recarga` es su canario (research R-2 de la 033):
si un HA futuro añade `counter.reload`, cae y avisa de que la tool puede
volver a hacer su trabajo. Antes era un `xfail` HALLAZGO (el 400 de Core).

`amount` de increment/decrement y `ha_set_counter_value` (spec 033, FR-009 y
extra del supervisor): `TestCounter.test_valores_que_ha_rechaza` comprueba
contra HA real que un valor que no es múltiplo del `step`, o que sale de los
límites, da `invalid_amount` / `invalid_value` y el contador no cambia (antes,
el 500 genérico de Core), y que el camino válido sigue funcionando.

Control negativo en el CI (T030, anotado en el commit del tramo B): con
`ha_increment_counter` llamando a `counter.decrement`, `TestCounter` cae en rojo
en el job `banco de Core`.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

import pytest

from tests.banco.base_helpers import (
    BancoHelpers,
    nombre_de_prueba,
)
from tests.banco.entorno import llamar

pytestmark = pytest.mark.banco


def _segundos(texto: str) -> int:
    """`H:MM:SS` (formato de `remaining` en HA) a segundos."""
    horas, minutos, segundos = (int(p) for p in texto.split(":"))
    return horas * 3600 + minutos * 60 + segundos


class TestCounter(BancoHelpers):
    async def test_ciclo_completo(self) -> None:
        nombre = nombre_de_prueba("counter")
        eid = f"counter.{nombre}"
        async with self.sesion() as s:
            creado = await s.crear(
                "ha_create_or_update_counter", "counter",
                {"name": nombre, "initial": 5, "step": 2, "minimum": 0, "maximum": 100},
            )
            self.assertEqual((creado["initial"], creado["step"]), (5, 2))
            await s.esperar_estado(eid, lambda e: e["state"] == "5", "valor inicial")
            editado = await s.editar(
                "ha_create_or_update_counter", "counter", nombre, {"step": 3}
            )
            self.assertEqual((editado["initial"], editado["maximum"]), (5, 100))
            await s.esperar_estado(
                eid, lambda e: e["attributes"].get("step") == 3, "step 3 en la entidad"
            )

            await s.accion("ha_increment_counter", entity_id=eid)
            await s.esperar_estado(eid, lambda e: e["state"] == "8", "5 + step")
            await s.accion("ha_decrement_counter", entity_id=eid)
            await s.esperar_estado(eid, lambda e: e["state"] == "5", "8 − step")
            # HA exige que el valor sea múltiplo del `step` (3): si no, 500.
            await s.accion("ha_set_counter_value", entity_id=eid, value=21)
            await s.esperar_estado(eid, lambda e: e["state"] == "21", "a 21")
            await s.accion("ha_reset_counter", entity_id=eid)
            await s.esperar_estado(eid, lambda e: e["state"] == "5", "vuelta a initial")

            await s.borrar("ha_delete_counter", "counter", nombre)

    # Canario de `counter.reload` (spec 033, T029; research R-2). Core
    # 2026.11.1 no lo tiene y la tool responde `not_supported` siempre, con o
    # sin token, sin llamar a HA. El lector comprueba las dos cosas: que Core
    # sigue sin el servicio (si lo añade, este test cae y avisa) y que la tool
    # no ha llamado a ningún servicio (barrera: una llamada propia del lector
    # vista en el bus; los eventos llegan en orden).
    async def test_recarga(self) -> None:
        tool = "ha_reload_counters"
        nombre = nombre_de_prueba("counter")
        eid = f"counter.{nombre}"
        async with self.sesion() as s:
            servicios = await s.lector.servicios()
            self.assertNotIn(
                "reload", servicios.get("counter") or {},
                "Core tiene ya counter.reload: ha_reload_counters puede volver a recargar "
                "(spec 033, research R-2)",
            )
            creado = await s.lector.crear("counter", {"name": nombre, "initial": 1})
            s.creados.append(("counter", creado["id"]))
            await s.esperar_estado(eid, lambda e: e["state"] == "1", "creado por el lector")
            async with s.lector.servicios_llamados() as vistos:
                for args in ({}, {"confirmation_token": "00000000-0000-4000-8000-000000000000"}):
                    respuesta = await llamar(s.cliente, tool, **args)
                    self.assertEqual(respuesta["error"], "not_supported", respuesta)
                    self.assertIn("1.3.0", respuesta["_deprecated"])
                    self.assertNotIn("confirmation_token", respuesta)
                await s.lector.comando(
                    {"type": "call_service", "domain": "counter", "service": "increment",
                     "target": {"entity_id": eid}}
                )
                await s.lector.esperar(
                    lambda: _devolver(vistos),
                    lambda v: ("counter", "increment") in v,
                    descripcion="barrera del lector (counter.increment) en el bus",
                )
            # Solo la barrera: ni `counter.reload` ni ninguna otra llamada de
            # `counter` por parte de Hermes.
            self.assertEqual([v for v in vistos if v[0] == "counter"], [("counter", "increment")])

    # `amount` y `ha_set_counter_value` (spec 033, T025; extra del supervisor).
    # HA solo acepta en `counter.set_value` un valor múltiplo del `step` y
    # dentro de los límites; si no, Core responde 500 (research R-7). La tool
    # lo comprueba antes y el contador no cambia. Como `set_value` es
    # síncrono en el REST de Core, si Hermes lo hubiera llamado el estado ya
    # habría cambiado (o la tool habría fallado) al volver la respuesta.
    async def test_valores_que_ha_rechaza(self) -> None:
        async with self.sesion() as s:
            nombre = nombre_de_prueba("counter")
            eid = f"counter.{nombre}"
            creado = await s.lector.crear("counter", {"name": nombre, "initial": 5, "step": 3})
            s.creados.append(("counter", creado["id"]))
            await s.esperar_estado(eid, lambda e: e["state"] == "5", "initial 5, step 3")

            r = await llamar(s.cliente, "ha_increment_counter", entity_id=eid, amount=3)
            self.assertEqual(
                (r.get("error"), r.get("reason"), r.get("target")),
                ("invalid_amount", "not_multiple_of_step", 8), r,
            )
            self.assertEqual((await s.lector.estado(eid))["state"], "5")
            r = await llamar(s.cliente, "ha_set_counter_value", entity_id=eid, value=7)
            self.assertEqual(
                (r.get("error"), r.get("reason")), ("invalid_value", "not_multiple_of_step"), r
            )
            self.assertEqual((await s.lector.estado(eid))["state"], "5")

            # Camino válido: a 6 (múltiplo de 3) y `amount` 3 → 9.
            await s.accion("ha_set_counter_value", entity_id=eid, value=6)
            await s.esperar_estado(eid, lambda e: e["state"] == "6", "a 6")
            await s.accion("ha_increment_counter", entity_id=eid, amount=3)
            await s.esperar_estado(eid, lambda e: e["state"] == "9", "6 + 3")

            nombre = nombre_de_prueba("counter")
            eid = f"counter.{nombre}"
            creado = await s.lector.crear(
                "counter", {"name": nombre, "initial": 9, "step": 1, "maximum": 10}
            )
            s.creados.append(("counter", creado["id"]))
            await s.esperar_estado(eid, lambda e: e["state"] == "9", "initial 9, máximo 10")
            r = await llamar(s.cliente, "ha_increment_counter", entity_id=eid, amount=5)
            self.assertEqual((r.get("error"), r.get("reason")), ("invalid_amount", "out_of_range"), r)
            r = await llamar(s.cliente, "ha_set_counter_value", entity_id=eid, value=11)
            self.assertEqual((r.get("error"), r.get("reason")), ("invalid_value", "out_of_range"), r)
            self.assertEqual((await s.lector.estado(eid))["state"], "9")


class TestTimer(BancoHelpers):
    async def test_ciclo_completo(self) -> None:
        nombre = nombre_de_prueba("timer")
        eid = f"timer.{nombre}"
        async with self.sesion() as s:
            creado = await s.crear(
                "ha_create_or_update_timer", "timer",
                {"name": nombre, "duration": "0:30:00"},
            )
            # HA guarda la duración con su propio formato (`H:MM:SS`); se manda
            # ya así para poder comparar lo guardado con lo pedido.
            self.assertEqual(creado["duration"], "0:30:00")
            editado = await s.editar(
                "ha_create_or_update_timer", "timer", nombre, {"duration": "1:00:00"}
            )
            self.assertEqual(editado["name"], nombre)
            await s.esperar_estado(
                eid, lambda e: e["attributes"].get("duration") == "1:00:00", "duración 1 h"
            )

            await s.accion("ha_start_timer", entity_id=eid)
            activo = await s.esperar_estado(eid, lambda e: e["state"] == "active", "activo")
            restante = _segundos(activo["attributes"]["remaining"])
            # Restar 10 minutos: sumar por encima de la duración lo rechaza HA.
            await s.accion("ha_change_timer", entity_id=eid, duration="-00:10:00")
            await s.esperar_estado(
                eid,
                lambda e: _segundos(e["attributes"]["remaining"]) <= restante - 590,
                "remaining 10 min menor",
            )
            await s.accion("ha_pause_timer", entity_id=eid)
            await s.esperar_estado(eid, lambda e: e["state"] == "paused", "en pausa")
            await s.accion("ha_cancel_timer", entity_id=eid)
            await s.esperar_estado(eid, lambda e: e["state"] == "idle", "cancelado")

            await s.accion("ha_start_timer", entity_id=eid, duration="00:05:00")
            await s.esperar_estado(eid, lambda e: e["state"] == "active", "activo otra vez")
            async with s.lector.eventos("timer.finished") as terminados:
                await s.accion("ha_finish_timer", entity_id=eid)
                await s.esperar_estado(eid, lambda e: e["state"] == "idle", "terminado")
                await s.lector.esperar(
                    lambda: _devolver(terminados),
                    lambda v: any(d.get("entity_id") == eid for d in v),
                    descripcion=f"timer.finished de {eid}",
                )

            await s.recargar("ha_reload_timers", "timer", nombre)
            await s.borrar("ha_delete_timer", "timer", nombre)


class TestSchedule(BancoHelpers):
    async def test_ciclo_completo(self) -> None:
        nombre = nombre_de_prueba("schedule")
        franjas = [{"from": "07:00:00", "to": "09:00:00"}]
        async with self.sesion() as s:
            creado = await s.crear(
                "ha_create_or_update_schedule", "schedule",
                {"name": nombre, "monday": franjas},
            )
            self.assertEqual(creado["monday"], franjas)
            nuevas = [{"from": "18:00:00", "to": "20:00:00"}]
            editado = await s.editar(
                "ha_create_or_update_schedule", "schedule", nombre, {"tuesday": nuevas}
            )
            self.assertEqual(editado["monday"], franjas)

            await s.recargar("ha_reload_schedules", "schedule", nombre)
            await s.borrar("ha_delete_schedule", "schedule", nombre)


async def _devolver(valor: object) -> object:
    return valor
