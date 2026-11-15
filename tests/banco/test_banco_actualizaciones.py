"""Banco de Core: entidades `update` (spec 015, tramo 3, T041; FR-013, FR-021).

Contra la entidad `update.banco_firmware` de la integración `template` de la
configuración del banco (`ha_config/configuration.yaml`): su versión instalada
es el `input_text.banco_update_instalada` y su acción `install` escribe ahí la
versión pedida y en `input_text.banco_update_backup` si se pidió backup. Hermes
instala; el lector independiente, directo a Core, comprueba.

- `ha_list_updates` la ve con su `supports` y `install_with`.
- `ha_get_update_release_notes`: la plantilla no tiene notas → `supported:
  false` con el resumen, sin preguntar a Core.
- `ha_install_update`: la vista previa no instala (barrera del lector: ningún
  `update.install` en el bus y la versión sigue igual); la confirmación
  instala la última (el lector ve 2.0.0 y la entidad `off`); con `version`
  concreta y `backup=true`, esa versión y el backup.
- `ha_call_service` con `update.install` (T051): por área se rechaza sin
  tocar HA; con la entidad nombrada sigue como en la 1.1.2 e instala.

Cada test deja los `input_text` como estaban al cerrar (limpieza del lector),
pase lo que pase. Solo corre en el job `banco-core` del CI.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras
from tests.banco.base_helpers import _devolver
from tests.banco.entorno import llamar

pytestmark = pytest.mark.banco

ENTIDAD = "update.banco_firmware"
INSTALADA = "input_text.banco_update_instalada"
BACKUP = "input_text.banco_update_backup"
INICIAL = "1.0.0"
ULTIMA = "2.0.0"


async def _poner(s: SesionEscrituras, entity_id: str, valor: str) -> None:
    """`input_text.set_value` por el lector (sin Hermes)."""
    await s.lector.comando({
        "type": "call_service", "domain": "input_text", "service": "set_value",
        "target": {"entity_id": entity_id}, "service_data": {"value": valor},
    })


async def _preparar(s: SesionEscrituras) -> None:
    """Estado de partida (1.0.0, sin backup) y su restauración al cerrar."""

    async def restaurar() -> None:
        await _poner(s, INSTALADA, INICIAL)
        await _poner(s, BACKUP, "no")

    s.limpiezas.append(restaurar)
    await restaurar()
    await s.esperar_estado(
        ENTIDAD,
        lambda e: e is not None and e["state"] == "on"
        and e["attributes"].get("installed_version") == INICIAL,
        f"instalada {INICIAL} y con actualización",
    )
    await _hermes_ve(s, INICIAL)


async def _rechazo(s: SesionEscrituras, tool: str, **args: Any) -> dict[str, Any]:
    """Una llamada que DEBE rechazarse: Hermes marca con `isError` toda
    respuesta `{"error": …}` y `llamar` la convertiría en fallo (mismo patrón
    que `test_banco_genericas._rechazo`)."""
    resultado = await s.cliente.call_tool(tool, args)
    assert getattr(resultado, "is_error", False), f"{tool}: se esperaba un rechazo"
    return json.loads(resultado.content[0].text)


async def _hermes_ve(s: SesionEscrituras, instalada: str) -> None:
    """Espera a que HERMES (su caché de estados, que se actualiza por la
    WebSocket) vea la entidad con esa versión instalada: lo que ve el lector
    puede ir unos milisegundos por delante, y la vista previa lee de Hermes."""

    async def leer() -> str | None:
        lista = await llamar(s.cliente, "ha_list_updates", include_up_to_date=True)
        for i in lista.get("items") or []:
            if i.get("entity_id") == ENTIDAD:
                return i.get("installed_version")
        return None

    await s.lector.esperar(leer, lambda v: v == instalada,
                           descripcion=f"Hermes ve {ENTIDAD} con {instalada}")


class TestEntidadesUpdate(BancoEscrituras):
    async def test_listar_y_notas(self) -> None:
        async with self.sesion() as s:
            await _preparar(s)
            lista = await s.accion("ha_list_updates")
            item = next((i for i in lista["items"] if i["entity_id"] == ENTIDAD), None)
            self.assertIsNotNone(item, lista)
            self.assertEqual(item["supports"], {
                "install": True, "specific_version": True, "progress": False,
                "backup": True, "release_notes": False})
            self.assertEqual((item["installed_version"], item["latest_version"]),
                             (INICIAL, ULTIMA))
            self.assertEqual(item["platform"], "template")
            self.assertEqual(item["install_with"], "ha_install_update")

            notas = await s.accion("ha_get_update_release_notes", entity_id=ENTIDAD)
            self.assertIs(notas["supported"], False)
            self.assertEqual(notas["release_summary"], "Version de prueba del banco")

    async def test_instalar_la_ultima(self) -> None:
        tool = "ha_install_update"
        async with self.sesion() as s:
            await _preparar(s)
            await s.preparar_barrera()
            async with s.lector.servicios_llamados() as vistos:
                vista = await s.vista(tool, entity_id=ENTIDAD)
                p = vista["preview"]
                self.assertEqual((p["from_version"], p["to_version"]), (INICIAL, ULTIMA))
                self.assertTrue(any("power off" in a for a in p["warnings"]))
                # La vista previa no ha instalado: nada en el bus y la versión
                # sigue igual (T031 de la 028).
                await s.barrera(vistos)
                self.assertNotIn(("update", "install"), vistos)
                estado = await s.lector.estado(INSTALADA)
                self.assertEqual(estado["state"], INICIAL)

                r = await s.confirmar(tool, vista, entity_id=ENTIDAD)
                self.assertEqual(r.get("result"), "ok", r)
                await s.lector.esperar(
                    lambda: _devolver(vistos),
                    lambda v: ("update", "install") in v,
                    descripcion="update.install en el bus",
                )
            self.assertEqual(vistos.count(("update", "install")), 1)
            await s.esperar_estado(INSTALADA, lambda e: e is not None and e["state"] == ULTIMA,
                                   f"versión {ULTIMA}")
            await s.esperar_estado(
                ENTIDAD,
                lambda e: e is not None and e["state"] == "off"
                and e["attributes"].get("installed_version") == ULTIMA,
                "al día",
            )
            backup = await s.lector.estado(BACKUP)
            self.assertEqual(backup["state"], "no")

    async def test_version_concreta_con_backup(self) -> None:
        tool = "ha_install_update"
        args = {"entity_id": ENTIDAD, "version": "1.5.0", "backup": True}
        async with self.sesion() as s:
            await _preparar(s)
            vista = await s.vista(tool, **args)
            p = vista["preview"]
            self.assertEqual(p["to_version"], "1.5.0")
            self.assertEqual((p["backup"]["requested"], p["backup"]["supported"]),
                             (True, True))
            estado = await s.lector.estado(INSTALADA)
            self.assertEqual(estado["state"], INICIAL)
            # El token está atado a los argumentos: con otra versión no vale y
            # no se instala nada (ni se gasta el token).
            otra = await _rechazo(s, tool, **{**args, "version": "1.6.0"},
                                  confirmation_token=vista["confirmation_token"])
            self.assertIs(otra.get("preview_outdated"), True, otra)
            estado = await s.lector.estado(INSTALADA)
            self.assertEqual(estado["state"], INICIAL)
            r = await s.confirmar(tool, vista, **args)
            self.assertEqual(r.get("result"), "ok", r)
            await s.esperar_estado(INSTALADA, lambda e: e is not None and e["state"] == "1.5.0",
                                   "versión 1.5.0")
            await s.esperar_estado(BACKUP, lambda e: e is not None and e["state"] == "si",
                                   "backup pedido")

    async def test_rechazo_sin_token_de_lo_que_core_rechazaria(self) -> None:
        async with self.sesion() as s:
            await _preparar(s)
            # Al día y sin versión: `no_update_available`, sin token.
            await _poner(s, INSTALADA, ULTIMA)
            await s.esperar_estado(ENTIDAD, lambda e: e is not None and e["state"] == "off",
                                   "al día")
            await _hermes_ve(s, ULTIMA)
            r = await _rechazo(s, "ha_install_update", entity_id=ENTIDAD)
            self.assertEqual(r.get("error"), "no_update_available", r)
            self.assertNotIn("confirmation_token", r)

    async def test_call_service_update_install(self) -> None:
        """T051: `ha_call_service("update", "install", …)` por área se
        rechaza sin tocar HA (`use_dedicated_tool` hacia `ha_install_update`):
        ni token, ni `update.install` en el bus, ni cambio de versión. Con la
        entidad nombrada (no es de `hassio`) sigue como en la 1.1.2: token y
        la misma llamada, que instala. El registro de entidades que consulta
        Hermes es el de Core real."""
        tool = "ha_call_service"
        async with self.sesion() as s:
            await _preparar(s)
            await s.preparar_barrera()
            async with s.lector.servicios_llamados() as vistos:
                r = await _rechazo(s, tool, domain="update", service="install",
                                   service_data={"area_id": "banco_area_inexistente"})
                self.assertEqual((r.get("error"), r.get("tool")),
                                 ("use_dedicated_tool", "ha_install_update"), r)
                self.assertNotIn("confirmation_token", r)
                await s.barrera(vistos)
                self.assertNotIn(("update", "install"), vistos)
                estado = await s.lector.estado(INSTALADA)
                self.assertEqual(estado["state"], INICIAL)

                datos = {"entity_id": ENTIDAD}
                vista = await s.vista(tool, domain="update", service="install",
                                      service_data=datos)
                await s.confirmar(tool, vista, domain="update", service="install",
                                  service_data=datos)
            await s.esperar_estado(INSTALADA, lambda e: e is not None and e["state"] == ULTIMA,
                                   f"versión {ULTIMA} por ha_call_service")
