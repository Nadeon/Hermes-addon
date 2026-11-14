"""Banco de Core: las 18 tools de escritura de `counter`, `timer` y `schedule`
(spec 010, US2, T026).

Igual que los `input_*`, y además: las recargas (`<dominio>.reload` visto en el
bus una sola vez y el helper de almacenamiento sigue), `ha_finish_timer` por el
evento `timer.finished` (el estado `idle` solo no lo distingue de cancelar) y
`ha_change_timer` sobre un temporizador activo, con `remaining` menor.

HALLAZGO: `ha_reload_counters` falla contra HA real (no existe `counter.reload`
en Core 2026.11.1); va en `TestCounter.test_recarga` como `xfail` estricto que
solo admite ese fallo, y en `FALLAN_EN_BANCO` (no cuenta como probada).

Control negativo en el CI (T030, anotado en el commit del tramo B): con
`ha_increment_counter` llamando a `counter.decrement`, `TestCounter` cae en rojo
en el job `banco de Core`.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

import pytest

from tests.banco.base_helpers import (
    BancoHelpers,
    ServicioInexistente,
    errores_de_tools,
    es_servicio_inexistente,
    nombre_de_prueba,
    sin_error,
)
from tests.banco.entorno import confirmar, llamar

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

    # HALLAZGO del banco (tramo B), pendiente de arreglo en la spec 033: HA
    # Core 2026.11.1 no tiene el servicio `counter.reload` (la integración
    # `counter` solo registra increment, decrement, reset y set_value).
    # `ha_reload_counters` llama a `counter.reload`, Core responde 400 y la
    # tool falla. Por eso la tool está en `FALLAN_EN_BANCO` y no cuenta como
    # probada.
    #
    # El `xfail` espera SOLO ese fallo (`ServicioInexistente`): la vista previa
    # se comprueba en positivo, y el error de la confirmación solo se convierte
    # en `ServicioInexistente` si la causa (registrada por el servidor MCP) es
    # el 400 de Core a `/services/counter/reload` y el lector ve que Core no
    # tiene ese servicio. Cualquier otro fallo (vista previa rota,
    # lector que no llega, otro error) deja el test en rojo. Estricto: si la
    # tool se arregla, pasa y el job se pone en rojo para quitar la marca y
    # moverla a `PROBADAS_EN_BANCO`.
    @pytest.mark.xfail(
        strict=True,
        raises=ServicioInexistente,
        reason="HA Core 2026.11.1 no tiene counter.reload: ha_reload_counters recibe 400 (spec 033)",
    )
    async def test_recarga(self) -> None:
        tool = "ha_reload_counters"
        nombre = nombre_de_prueba("counter")
        async with self.sesion() as s:
            s.creados.append(("counter", nombre))
            await s.lector.crear("counter", {"name": nombre, "initial": 1})
            await s.esperar_estado(f"counter.{nombre}", lambda e: True, "creado por el lector")
            vista = sin_error(tool, await llamar(s.cliente, tool))
            if vista["preview"]["service"] != "counter.reload":
                raise AssertionError(f"{tool}: vista previa inesperada {vista['preview']!r}")
            servicios = await s.lector.servicios()
            with errores_de_tools() as errores:
                try:
                    sin_error(tool, await confirmar(s.cliente, tool, vista))
                except AssertionError as exc:
                    if es_servicio_inexistente(errores, servicios, "counter", "reload"):
                        raise ServicioInexistente(str(exc)) from None
                    raise


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
