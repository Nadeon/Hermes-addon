"""Banco de Core: servicios, eventos y esperas (spec 028, tramo A, T010).

- `ha_call_service` por sus dos caminos: directo (`input_boolean.turn_on`) y
  en dos pasos con un servicio de la denylist que no hace daño en el banco,
  `input_boolean.reload` (solo relee el YAML de `input_boolean`, que no tiene
  ninguno). Nunca `homeassistant.restart` ni `homeassistant.stop`: el banco no
  sobreviviría y no prueban nada que no pruebe este.
- `ha_call_service_response` con `schedule.get_schedule` (Core la registra
  como de respuesta obligatoria) sobre un horario creado por el lector.
- `ha_fire_event` con Hermes configurado con ese tipo de evento en
  `fire_event_allowlist` (sin él la tool rechaza todo): el lector, suscrito a
  ese tipo, lo recibe con los datos enviados.
- `ha_cancel_wait`: la espera vive en Hermes y el lector no la ve (research
  R-7 de la 028). La comprobación es la propia espera: termina mucho antes de
  su tope con `reason: cancelled` y deja de estar entre las activas; después,
  un evento que dispara el lector ya no la cambia.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from tests.banco.base_escrituras import BancoEscrituras, sufijo
from tests.banco.base_helpers import _devolver
from tests.banco.entorno import llamar

pytestmark = pytest.mark.banco


class TestLlamarServicio(BancoEscrituras):
    async def test_directo(self) -> None:
        async with self.sesion() as s:
            ib = await s.input_boolean(f"banco_input_boolean_{sufijo()}")
            respuesta = await s.accion(
                "ha_call_service",
                domain="input_boolean",
                service="turn_on",
                service_data={"entity_id": ib},
            )
            self.assertNotIn("confirmation_token", json.dumps(respuesta))
            await s.esperar_estado(ib, lambda e: e is not None and e["state"] == "on", "encendido")

    async def test_en_dos_pasos_con_la_denylist(self) -> None:
        tool = "ha_call_service"
        args = {"domain": "input_boolean", "service": "reload"}
        async with self.sesion() as s:
            async with s.lector.servicios_llamados() as vistos:
                vista = await s.vista(tool, **args)
                self.assertEqual(
                    (vista["preview"]["domain"], vista["preview"]["service"]),
                    ("input_boolean", "reload"),
                )
                await s.confirmar(tool, vista, **args)
                await s.lector.esperar(
                    lambda: _devolver(vistos),
                    lambda v: ("input_boolean", "reload") in v,
                    descripcion="input_boolean.reload en el bus",
                )
            # Los eventos llegan en orden: si la vista previa hubiera llamado al
            # servicio, se habrían visto dos.
            self.assertEqual(vistos.count(("input_boolean", "reload")), 1)

    async def test_con_respuesta(self) -> None:
        nombre = f"banco_schedule_{sufijo()}"
        franjas = [{"from": "07:00:00", "to": "09:00:00"}]
        async with self.sesion() as s:
            creado = await s.lector.crear("schedule", {"name": nombre, "monday": franjas})
            s.limpiezas.append(lambda: s.lector.borrar("schedule", creado["id"]))
            eid = f"schedule.{creado['id']}"
            await s.esperar_estado(eid, lambda e: e is not None, "creado")

            respuesta = await s.accion(
                "ha_call_service_response",
                domain="schedule",
                service="get_schedule",
                service_data={"entity_id": eid},
            )
            # REST de Core: {"changed_states": [...], "service_response": {eid: {...}}}.
            horario = respuesta["service_response"][eid]
            self.assertEqual(horario["monday"], [{"from": "07:00:00", "to": "09:00:00"}])
            self.assertEqual(horario["tuesday"], [])


class TestEvento(BancoEscrituras):
    async def test_disparar_evento(self) -> None:
        tipo = f"banco_evento_{sufijo()}"
        datos = {"origen": "banco", "numero": 7}
        # El tipo tiene que estar en la allowlist ANTES de registrar las tools.
        async with self.sesion(fire_event_allowlist=[tipo]) as s:
            async with s.lector.eventos(tipo) as vistos:
                respuesta = await s.accion("ha_fire_event", event_type=tipo, event_data=datos)
                self.assertEqual((respuesta["result"], respuesta["event_type"]), ("ok", tipo))
                await s.lector.esperar(
                    lambda: _devolver(vistos), bool, descripcion=f"{tipo} en el bus"
                )
        self.assertEqual(vistos, [datos])


class TestCancelarEspera(BancoEscrituras):
    async def test_cancelar_espera(self) -> None:
        tipo = f"banco_espera_{sufijo()}"
        async with self.sesion() as s:
            bucle = asyncio.get_running_loop()
            # `ctx` sale como argumento obligatorio en el esquema de
            # ha_wait_for_event (anotado `Any`, no `Context`): se pasa vacío.
            espera = asyncio.ensure_future(
                llamar(s.cliente, "ha_wait_for_event", ctx={}, event_type=tipo, timeout_seconds=60)
            )
            try:
                activas = await s.lector.esperar(
                    lambda: llamar(s.cliente, "ha_list_active_waits"),
                    lambda r: any(w["event_type"] == tipo for w in r["waits"]),
                    descripcion=f"espera de {tipo} activa",
                )
                wait_id = next(w["wait_id"] for w in activas["waits"] if w["event_type"] == tipo)

                inicio = bucle.time()
                self.assertEqual(
                    await s.accion("ha_cancel_wait", wait_id=wait_id),
                    {"result": "ok", "wait_id": wait_id},
                )
                resultado = await asyncio.wait_for(espera, timeout=10)
                self.assertLess(bucle.time() - inicio, 10)
                self.assertEqual((resultado["matched"], resultado["reason"]), (False, "cancelled"))
                self.assertLess(resultado["waited_seconds"], 60)

                activas = await llamar(s.cliente, "ha_list_active_waits")
                self.assertFalse([w for w in activas["waits"] if w["wait_id"] == wait_id])
                # El lector dispara el evento: la espera ya terminó y no lo recoge.
                await s.lector.comando({"type": "fire_event", "event_type": tipo})
                self.assertEqual(
                    await llamar(s.cliente, "ha_cancel_wait", wait_id=wait_id),
                    {"error": "not_found", "wait_id": wait_id},
                )
                self.assertEqual(resultado["reason"], "cancelled")
            finally:
                if not espera.done():
                    espera.cancel()
                    await asyncio.gather(espera, return_exceptions=True)
