"""Banco de Core: config entries, flujos y el entorno de `kitchen_sink` (spec 028, tramo B).

- `TestEntornoKitchenSink` (T017): antes de probar ninguna tool, el lector
  comprueba que `kitchen_sink` cargó en la HA del banco con lo que necesitan
  las pruebas del tramo B (entrada `loaded`, avisos de reparación propios y
  dispositivos que se pueden borrar además de `statistics_issues`). Si esto
  cae, el resto del tramo no prueba nada: falla aquí con el motivo.
- `TestConfigEntryUptime` (T020): las 7 tools de flujos y config entries
  sobre una entrada de `uptime` que crean y borran las propias tools.
- `TestFlujoOpcionesKitchenSink` (T020): `ha_start_options_flow` y
  `ha_continue_options_flow` sobre la entrada de `kitchen_sink`.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras
from tests.banco.lector import ErrorCore

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


# ── T020: config entries y flujos ────────────────────────────────────────


async def _flujos_en_curso(s: SesionEscrituras) -> set[str]:
    return {f["flow_id"] for f in await s.lector.comando({"type": "config_entries/flow/progress"})}


async def _entrada(s: SesionEscrituras, entry_id: str) -> dict[str, Any] | None:
    try:
        respuesta = await s.lector.comando(
            {"type": "config_entries/get_single", "entry_id": entry_id}
        )
    except ErrorCore as exc:
        if exc.codigo == "not_found":
            return None
        raise
    return respuesta["config_entry"]


async def _sensor_uptime(s: SesionEscrituras, entry_id: str) -> str:
    """entity_id del sensor de la entrada de `uptime` (se busca en el registro:
    el nombre lo deriva HA del título)."""
    entidades = await s.lector.esperar(
        lambda: s.lector.comando({"type": "config/entity_registry/list"}),
        lambda r: any(e.get("config_entry_id") == entry_id for e in r),
        descripcion=f"entidad de la entrada {entry_id}",
    )
    return next(e["entity_id"] for e in entidades if e.get("config_entry_id") == entry_id)


class TestConfigEntryUptime(BancoEscrituras):
    """Ciclo de vida completo de una entrada de `uptime`, creada por las propias
    tools de flujo (research R-2): sin configuración, sin internet y con un
    sensor que guarda su hora de creación, así que una recarga se ve."""

    async def test_ciclo_completo(self) -> None:
        async with self.sesion() as s:

            async def borrar_uptime() -> None:
                # Pase lo que pase: `uptime` es de una sola instancia y un resto
                # haría fallar el siguiente test que la cree en el mismo banco.
                for e in await s.lector.comando(
                    {"type": "config_entries/get", "domain": "uptime"}
                ):
                    await s.lector.rest(
                        "DELETE", f"/api/config/config_entries/entry/{e['entry_id']}"
                    )

            s.limpiezas.append(borrar_uptime)

            # Abrir y abortar.
            abierto = await s.accion("ha_start_config_entry_flow", handler="uptime")
            self.assertEqual((abierto["type"], abierto["step_id"]), ("form", "user"))
            self.assertIn(abierto["flow_id"], await _flujos_en_curso(s))
            self.assertEqual(
                await s.accion("ha_abort_config_entry_flow", flow_id=abierto["flow_id"]),
                {"result": "ok"},
            )
            self.assertNotIn(abierto["flow_id"], await _flujos_en_curso(s))

            # Abrir otro y completarlo: entrada nueva, cargada.
            abierto = await s.accion("ha_start_config_entry_flow", handler="uptime")
            creado = await s.accion(
                "ha_continue_config_entry_flow", flow_id=abierto["flow_id"], user_input={}
            )
            self.assertEqual(creado["type"], "create_entry")
            entry_id = creado["result"]["entry_id"]
            await s.lector.esperar(
                lambda: _entrada(s, entry_id),
                lambda e: e is not None and e["state"] == "loaded",
                descripcion=f"entrada {entry_id} de uptime en estado loaded",
            )
            self.assertNotIn(abierto["flow_id"], await _flujos_en_curso(s))

            # Recargar: el sensor guarda la hora a la que se creó la entidad,
            # así que cambia. Por si el estado redondea a segundos, se deja
            # pasar más de uno antes de recargar.
            sensor = await _sensor_uptime(s, entry_id)
            antes = await s.esperar_estado(sensor, lambda e: e is not None, "existe")
            await asyncio.sleep(1.5)
            await s.accion("ha_reload_config_entry", entry_id=entry_id)
            await s.esperar_estado(
                sensor,
                lambda e: e is not None and e["state"] not in (antes["state"], "unavailable"),
                f"estado distinto de {antes['state']} tras recargar",
            )

            # Deshabilitar, en dos pasos.
            tool = "ha_disable_config_entry"
            vista = await s.vista(tool, entry_id=entry_id)
            self.assertIsNone((await _entrada(s, entry_id))["disabled_by"])
            await s.confirmar(tool, vista, entry_id=entry_id)
            deshabilitada = await _entrada(s, entry_id)
            self.assertEqual(
                (deshabilitada["disabled_by"], deshabilitada["state"]),
                ("user", "not_loaded"),
            )

            # Habilitar: directo.
            await s.accion("ha_enable_config_entry", entry_id=entry_id)
            habilitada = await s.lector.esperar(
                lambda: _entrada(s, entry_id),
                lambda e: e is not None and e["state"] == "loaded",
                descripcion=f"entrada {entry_id} otra vez loaded",
            )
            self.assertIsNone(habilitada["disabled_by"])

            # Borrar, en dos pasos.
            tool = "ha_delete_config_entry"
            vista = await s.vista(tool, entry_id=entry_id)
            self.assertIsNotNone(await _entrada(s, entry_id))
            await s.confirmar(tool, vista, entry_id=entry_id)
            self.assertIsNone(await _entrada(s, entry_id))


class TestFlujoOpcionesKitchenSink(BancoEscrituras):
    """Flujo de opciones de `kitchen_sink` (paso `options_1`, con una sección).

    Ninguna prueba deshabilita ni borra la entrada de kitchen_sink: la usan
    las de dispositivos y reparaciones.
    """

    async def test_abrir_y_completar(self) -> None:
        ruta = "/api/config/config_entries/options/flow"
        async with self.sesion() as s:
            entry_id = (await entrada_kitchen_sink(s))["entry_id"]
            modificada_antes = (await _entrada(s, entry_id))["modified_at"]

            abierto = await s.accion("ha_start_options_flow", entry_id=entry_id)
            self.assertEqual((abierto["type"], abierto["step_id"]), ("form", "options_1"))
            flow_id = abierto["flow_id"]

            async def abortar() -> None:
                await s.lector.rest("DELETE", f"{ruta}/{flow_id}")

            s.limpiezas.append(abortar)
            estado, paso = await s.lector.rest("GET", f"{ruta}/{flow_id}")
            self.assertEqual((estado, paso["step_id"]), (200, "options_1"))

            # Un entero aleatorio: así las opciones cambian siempre y HA
            # actualiza la entrada (si no cambian, no toca `modified_at`).
            valores = {"section_1": {"bool": True, "int": secrets.randbelow(9000) + 1000}}
            hecho = await s.accion(
                "ha_continue_options_flow", flow_id=flow_id, user_input=valores
            )
            self.assertEqual(hecho["type"], "create_entry")

            # Lo que ve el lector en Core: el flujo de Hermes ya no existe y la
            # entrada se ha modificado. Las opciones no salen por la API de
            # Core (`as_json_fragment` no las incluye) y el formulario de
            # kitchen_sink lee sus valores por defecto fuera de la sección,
            # así que un flujo nuevo no los enseña (desviación anotada en
            # tasks.md): el lector abre el suyo para ver que la entrada sigue
            # aceptando opciones y lo aborta.
            estado, _ = await s.lector.rest("GET", f"{ruta}/{flow_id}")
            self.assertEqual(estado, 404)
            self.assertGreater((await _entrada(s, entry_id))["modified_at"], modificada_antes)
            estado, propio = await s.lector.rest("POST", ruta, {"handler": entry_id})
            self.assertEqual((estado, propio["step_id"]), (200, "options_1"))
            estado, _ = await s.lector.rest("DELETE", f"{ruta}/{propio['flow_id']}")
            self.assertEqual(estado, 200)
