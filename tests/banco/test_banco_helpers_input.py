"""Banco de Core: las 23 tools de escritura de los `input_*` (spec 010, US2, T025).

Por dominio: crear en dos pasos, editar en dos pasos (HA reemplaza el elemento
en `<dominio>/update`; Hermes manda el actual con los cambios encima, y aquí se
comprueba en la HA real que lo no tocado sigue), cada acción sobre el valor
con su estado visto por el lector, y borrar en dos pasos.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

import pytest

from tests.banco.base_helpers import BancoHelpers, nombre_de_prueba

pytestmark = pytest.mark.banco


class TestInputBoolean(BancoHelpers):
    async def test_ciclo_completo(self) -> None:
        nombre = nombre_de_prueba("input_boolean")
        eid = f"input_boolean.{nombre}"
        async with self.sesion() as s:
            creado = await s.crear(
                "ha_create_or_update_input_boolean", "input_boolean",
                {"name": nombre, "icon": "mdi:flask"},
            )
            self.assertEqual(creado["icon"], "mdi:flask")
            editado = await s.editar(
                "ha_create_or_update_input_boolean", "input_boolean", nombre,
                {"icon": "mdi:test-tube"},
            )
            self.assertEqual(editado["name"], nombre)

            await s.accion("ha_set_input_boolean", entity_id=eid, value=True)
            await s.esperar_estado(eid, lambda e: e["state"] == "on", "encendido")
            await s.accion("ha_set_input_boolean", entity_id=eid, value=False)
            await s.esperar_estado(eid, lambda e: e["state"] == "off", "apagado")
            await s.accion("ha_toggle_input_boolean", entity_id=eid)
            await s.esperar_estado(eid, lambda e: e["state"] == "on", "invertido")

            await s.borrar("ha_delete_input_boolean", "input_boolean", nombre)


class TestInputButton(BancoHelpers):
    async def test_ciclo_completo(self) -> None:
        nombre = nombre_de_prueba("input_button")
        eid = f"input_button.{nombre}"
        async with self.sesion() as s:
            await s.crear(
                "ha_create_or_update_input_button", "input_button",
                {"name": nombre, "icon": "mdi:gesture-tap-button"},
            )
            editado = await s.editar(
                "ha_create_or_update_input_button", "input_button", nombre,
                {"icon": "mdi:button-pointer"},
            )
            self.assertEqual(editado["name"], nombre)

            antes = (await s.lector.estado(eid))["state"]
            await s.accion("ha_press_input_button", entity_id=eid)
            # El estado de un botón es la marca de tiempo de la última pulsación.
            await s.esperar_estado(eid, lambda e: e["state"] != antes, "pulsado")

            await s.borrar("ha_delete_input_button", "input_button", nombre)


class TestInputDatetime(BancoHelpers):
    async def test_ciclo_completo(self) -> None:
        nombre = nombre_de_prueba("input_datetime")
        eid = f"input_datetime.{nombre}"
        async with self.sesion() as s:
            creado = await s.crear(
                "ha_create_or_update_input_datetime", "input_datetime",
                {"name": nombre, "has_date": True, "has_time": True},
            )
            self.assertTrue(creado["has_date"])
            self.assertTrue(creado["has_time"])
            editado = await s.editar(
                "ha_create_or_update_input_datetime", "input_datetime", nombre,
                {"icon": "mdi:calendar-clock"},
            )
            self.assertTrue(editado["has_date"])
            self.assertTrue(editado["has_time"])

            await s.accion(
                "ha_set_input_datetime", entity_id=eid, datetime="2026-01-02 03:04:05"
            )
            await s.esperar_estado(
                eid, lambda e: e["state"] == "2026-01-02 03:04:05", "fecha y hora puestas"
            )

            await s.borrar("ha_delete_input_datetime", "input_datetime", nombre)


class TestInputNumber(BancoHelpers):
    async def test_ciclo_completo(self) -> None:
        nombre = nombre_de_prueba("input_number")
        eid = f"input_number.{nombre}"
        async with self.sesion() as s:
            creado = await s.crear(
                "ha_create_or_update_input_number", "input_number",
                {"name": nombre, "min": 0, "max": 100, "step": 5, "mode": "box"},
            )
            self.assertEqual((creado["min"], creado["max"], creado["step"]), (0, 100, 5))
            editado = await s.editar(
                "ha_create_or_update_input_number", "input_number", nombre,
                {"max": 200},
            )
            self.assertEqual((editado["min"], editado["step"]), (0, 5))

            await s.accion("ha_set_input_number", entity_id=eid, value=40)
            await s.esperar_estado(eid, lambda e: float(e["state"]) == 40, "a 40")
            await s.accion("ha_increment_input_number", entity_id=eid)
            await s.esperar_estado(eid, lambda e: float(e["state"]) == 45, "40 + step")
            await s.accion("ha_decrement_input_number", entity_id=eid)
            await s.esperar_estado(eid, lambda e: float(e["state"]) == 40, "45 − step")

            await s.borrar("ha_delete_input_number", "input_number", nombre)


class TestInputSelect(BancoHelpers):
    async def test_ciclo_completo(self) -> None:
        nombre = nombre_de_prueba("input_select")
        eid = f"input_select.{nombre}"
        async with self.sesion() as s:
            creado = await s.crear(
                "ha_create_or_update_input_select", "input_select",
                {"name": nombre, "options": ["uno", "dos", "tres"]},
            )
            self.assertEqual(creado["options"], ["uno", "dos", "tres"])
            editado = await s.editar(
                "ha_create_or_update_input_select", "input_select", nombre,
                {"icon": "mdi:format-list-bulleted"},
            )
            self.assertEqual(editado["options"], ["uno", "dos", "tres"])

            await s.accion("ha_set_input_select", entity_id=eid, option="dos")
            await s.esperar_estado(eid, lambda e: e["state"] == "dos", "opción dos")
            await s.accion("ha_cycle_input_select", entity_id=eid)
            await s.esperar_estado(eid, lambda e: e["state"] == "tres", "opción siguiente")
            await s.accion(
                "ha_set_input_select_options", entity_id=eid, options=["cuatro", "cinco"]
            )
            await s.esperar_estado(
                eid,
                lambda e: e["attributes"].get("options") == ["cuatro", "cinco"],
                "opciones nuevas",
            )

            await s.borrar("ha_delete_input_select", "input_select", nombre)


class TestInputText(BancoHelpers):
    async def test_ciclo_completo(self) -> None:
        nombre = nombre_de_prueba("input_text")
        eid = f"input_text.{nombre}"
        async with self.sesion() as s:
            creado = await s.crear(
                "ha_create_or_update_input_text", "input_text",
                {"name": nombre, "min": 0, "max": 50},
            )
            self.assertEqual(creado["max"], 50)
            editado = await s.editar(
                "ha_create_or_update_input_text", "input_text", nombre,
                {"max": 60},
            )
            self.assertEqual(editado["min"], 0)

            await s.accion("ha_set_input_text", entity_id=eid, value="hola banco")
            await s.esperar_estado(eid, lambda e: e["state"] == "hola banco", "texto puesto")

            await s.borrar("ha_delete_input_text", "input_text", nombre)
