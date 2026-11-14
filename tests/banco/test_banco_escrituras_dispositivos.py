"""Banco de Core: dispositivos, entidades y reparaciones (spec 028, tramo B, T019).

6 tools, todas en dos pasos:

- **Dispositivos** de `kitchen_sink` (la integración de demostración de Core,
  cargada en la HA del banco): `ha_update_device` cambia `name_by_user` y se
  restaura al terminar; `ha_remove_device` y
  `ha_remove_device_from_config_entry` borran cada uno un dispositivo
  distinto. Nunca `statistics_issues` (kitchen_sink no deja borrarlo) ni uno
  con dispositivos hijo (HA 2026.9+ los borraría con él). El borrado se
  comprueba justo después de confirmar: el flujo de opciones de kitchen_sink
  recarga la entrada y puede volver a crearlos.
- **Entidades**: un `input_boolean` del lector, renombrado con
  `ha_update_entity_registry` (`new_entity_id`) y luego quitado del registro
  con `ha_remove_entity_registry`.
- **Reparaciones**: `ha_ignore_repair` sobre un aviso de kitchen_sink; se
  vuelve a mostrar (`ignore=False`, también por Hermes) al terminar.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo
from tests.banco.lector import ErrorCore
from tests.banco.test_banco_escrituras_integraciones import (
    dispositivos_kitchen_sink,
    es_statistics_issues,
    exigir_kitchen_sink,
)

pytestmark = pytest.mark.banco


async def _dispositivo(s: SesionEscrituras, device_id: str) -> dict[str, Any] | None:
    return next(
        (
            d
            for d in await s.lector.comando({"type": "config/device_registry/list"})
            if d["id"] == device_id
        ),
        None,
    )


async def _borrables(s: SesionEscrituras) -> list[dict[str, Any]]:
    """Dispositivos de kitchen_sink que se pueden borrar sin arrastrar a otros."""
    todos = await s.lector.comando({"type": "config/device_registry/list"})
    padres = {d.get("via_device_id") for d in todos if d.get("via_device_id")}
    return [
        d
        for d in await dispositivos_kitchen_sink(s)
        if not es_statistics_issues(d) and d["id"] not in padres
    ]


async def _entidad(s: SesionEscrituras, entity_id: str) -> dict[str, Any] | None:
    try:
        return await s.lector.comando(
            {"type": "config/entity_registry/get", "entity_id": entity_id}
        )
    except ErrorCore as exc:
        if exc.codigo == "not_found":
            return None
        raise


class TestDispositivo(BancoEscrituras):
    async def test_editar_nombre(self) -> None:
        async with self.sesion() as s:
            await exigir_kitchen_sink(s)
            borrables = await _borrables(s)
            self.assertTrue(borrables, "kitchen_sink no tiene dispositivos que se puedan editar")
            device_id = borrables[0]["id"]

            async def restaurar() -> None:
                await s.lector.comando(
                    {
                        "type": "config/device_registry/update",
                        "device_id": device_id,
                        "name_by_user": None,
                    }
                )

            s.limpiezas.append(restaurar)
            antes = (await _dispositivo(s, device_id))["name_by_user"]
            nombre = f"banco_dispositivo_{sufijo()}"
            tool = "ha_update_device"
            args = {"device_id": device_id, "updates": {"name_by_user": nombre}}
            vista = await s.vista(tool, **args)
            self.assertEqual((await _dispositivo(s, device_id))["name_by_user"], antes)
            await s.confirmar(tool, vista, **args)
            self.assertEqual((await _dispositivo(s, device_id))["name_by_user"], nombre)

    async def test_borrar_dos_dispositivos(self) -> None:
        async with self.sesion() as s:
            entrada = await exigir_kitchen_sink(s)
            borrables = await _borrables(s)
            self.assertGreaterEqual(len(borrables), 2, f"borrables: {borrables!r}")
            primero, segundo = borrables[0]["id"], borrables[1]["id"]

            tool = "ha_remove_device"
            vista = await s.vista(tool, device_id=primero)
            self.assertIsNotNone(await _dispositivo(s, primero))
            await s.confirmar(tool, vista, device_id=primero)
            self.assertIsNone(await _dispositivo(s, primero))

            # En HA 2026.9+ este comando borra el dispositivo entero (alias del
            # borrado), y así lo anuncia la vista previa de Hermes.
            tool = "ha_remove_device_from_config_entry"
            args = {"device_id": segundo, "config_entry_id": entrada["entry_id"]}
            vista = await s.vista(tool, **args)
            self.assertIsNotNone(await _dispositivo(s, segundo))
            await s.confirmar(tool, vista, **args)
            self.assertIsNone(await _dispositivo(s, segundo))


class TestEntidad(BancoEscrituras):
    async def test_renombrar_y_quitar_del_registro(self) -> None:
        hexa = sufijo()
        async with self.sesion() as s:
            viejo = await s.input_boolean(f"banco_input_boolean_{hexa}")
            nuevo = f"input_boolean.banco_renombrado_{hexa}"

            tool = "ha_update_entity_registry"
            args = {"entity_id": viejo, "updates": {"new_entity_id": nuevo}}
            vista = await s.vista(tool, **args)
            self.assertIsNotNone(await _entidad(s, viejo))
            self.assertIsNone(await _entidad(s, nuevo))
            await s.confirmar(tool, vista, **args)
            self.assertIsNone(await _entidad(s, viejo))
            self.assertEqual((await _entidad(s, nuevo))["entity_id"], nuevo)

            tool = "ha_remove_entity_registry"
            vista = await s.vista(tool, entity_id=nuevo)
            self.assertIsNotNone(await _entidad(s, nuevo))
            await s.confirmar(tool, vista, entity_id=nuevo)
            self.assertIsNone(await _entidad(s, nuevo))


async def _aviso(s: SesionEscrituras, issue_id: str) -> dict[str, Any] | None:
    avisos = await s.lector.comando({"type": "repairs/list_issues"})
    return next(
        (
            i
            for i in avisos["issues"]
            if i["domain"] == "kitchen_sink" and i["issue_id"] == issue_id
        ),
        None,
    )


class TestReparacion(BancoEscrituras):
    async def test_ignorar_y_volver_a_mostrar(self) -> None:
        async with self.sesion() as s:
            await exigir_kitchen_sink(s)
            # Los avisos los crea kitchen_sink al cargar: se esperan con su
            # motivo en vez de dejar que `next` caiga con un StopIteration.
            avisos = await s.lector.esperar(
                lambda: s.lector.comando({"type": "repairs/list_issues"}),
                lambda r: any(
                    i["domain"] == "kitchen_sink" and not i["ignored"] for i in r["issues"]
                ),
                descripcion="entorno del banco: aviso de reparación de kitchen_sink sin ignorar",
            )
            issue_id = next(
                i["issue_id"]
                for i in avisos["issues"]
                if i["domain"] == "kitchen_sink" and not i["ignored"]
            )

            async def restaurar() -> None:
                await s.lector.comando(
                    {
                        "type": "repairs/ignore_issue",
                        "domain": "kitchen_sink",
                        "issue_id": issue_id,
                        "ignore": False,
                    }
                )

            s.limpiezas.append(restaurar)

            tool = "ha_ignore_repair"
            args = {"domain": "kitchen_sink", "issue_id": issue_id, "ignore": True}
            vista = await s.vista(tool, **args)
            self.assertFalse((await _aviso(s, issue_id))["ignored"])
            await s.confirmar(tool, vista, **args)
            self.assertTrue((await _aviso(s, issue_id))["ignored"])

            # Y de vuelta por Hermes: también en dos pasos.
            args["ignore"] = False
            vista = await s.vista(tool, **args)
            self.assertTrue((await _aviso(s, issue_id))["ignored"])
            await s.confirmar(tool, vista, **args)
            self.assertFalse((await _aviso(s, issue_id))["ignored"])
