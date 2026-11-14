"""Banco de Core: validación, diagnósticos y notificaciones (spec 012, tramo B, T031).

Las siete tools del tramo B contra HA Core real, con el lector independiente
preparando cada caso y comprobando cada efecto directamente en Core:

- **Validación**: `ha_validate_config` con una automatización válida (sobre un
  `input_boolean` del lector) y con un disparador que no existe;
  `ha_test_condition` con una condición de estado sobre ese `input_boolean`,
  verdadera y falsa.
- **Diagnósticos**: el lector crea por REST una entrada de `local_calendar`
  (integración sin red ni hardware, con diagnóstico de entrada; research
  R-8) y la borra al cerrar. `ha_list_diagnostics_handlers` la lista;
  `ha_get_config_entry_diagnostics` devuelve su `data`, con y sin `keys`.
  `ha_get_device_diagnostics` solo en su camino `diagnostics_not_supported`,
  con un dispositivo de `kitchen_sink` (cargada por la 028): ninguna
  integración sin hardware ni nube ofrece diagnóstico de dispositivo en
  2026.11.1, así que su camino feliz queda en los unitarios y como pendiente
  manual en la matriz de la 008.
- **Notificaciones**: el lector crea una con un centinela en el mensaje;
  `ha_list_persistent_notifications` la ve con el centinela tapado; el
  descarte en dos pasos: tras la vista previa el lector la sigue viendo, tras
  confirmar ya no.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo
from tests.banco.entorno import llamar

pytestmark = pytest.mark.banco

_CENTINELA = "centinela-012"


# ── Validación ──────────────────────────────────────────────────────────────


class TestValidacion(BancoEscrituras):
    async def test_validate_config(self) -> None:
        async with self.sesion() as s:
            entidad = await s.input_boolean(f"banco_012_validar_{sufijo()}")
            valida = {
                "alias": "Banco 012", "mode": "single",
                "triggers": [{"trigger": "state", "entity_id": entidad, "to": "on"}],
                "conditions": [],
                "actions": [{"action": "input_boolean.turn_off",
                             "target": {"entity_id": entidad}}],
            }
            r = await s.accion("ha_validate_config", config=valida)
            self.assertEqual(r["triggers"], {"valid": True, "error": None})
            self.assertEqual(r["conditions"], {"valid": True, "error": None})
            self.assertEqual(r["actions"], {"valid": True, "error": None})
            self.assertEqual(r["not_validated"], ["alias", "mode"])
            self.assertIs(r["saved"], False)

            r = await s.accion("ha_validate_config",
                               triggers=[{"trigger": "no_existe_banco_012"}])
            self.assertIs(r["triggers"]["valid"], False)
            self.assertTrue(r["triggers"]["error"])

    async def test_test_condition(self) -> None:
        async with self.sesion() as s:
            entidad = await s.input_boolean(f"banco_012_condicion_{sufijo()}")
            apagado = {"condition": "state", "entity_id": entidad, "state": "off"}
            encendido = {"condition": "state", "entity_id": entidad, "state": "on"}
            self.assertEqual(await s.accion("ha_test_condition", condition=apagado),
                             {"result": True})
            self.assertEqual(await s.accion("ha_test_condition", condition=encendido),
                             {"result": False})


# ── Diagnósticos ────────────────────────────────────────────────────────────


async def _crear_calendario(s: SesionEscrituras) -> str:
    """Entrada de `local_calendar` creada por el lector (REST); se borra al cerrar."""
    nombre = f"Banco 012 {sufijo()}"
    estado, flujo = await s.lector.rest(
        "POST", "/api/config/config_entries/flow", {"handler": "local_calendar"})
    if estado != 200 or flujo.get("type") != "form":
        raise AssertionError(f"lector: no se pudo abrir el flujo de local_calendar: "
                             f"{estado} {flujo!r}")
    estado, fin = await s.lector.rest(
        "POST", f"/api/config/config_entries/flow/{flujo['flow_id']}",
        {"calendar_name": nombre, "import": "create_empty"})
    if estado != 200 or fin.get("type") != "create_entry":
        raise AssertionError(f"lector: el flujo de local_calendar no creó la entrada: "
                             f"{estado} {fin!r}")

    async def entradas() -> list[dict[str, Any]]:
        return await s.lector.comando({"type": "config_entries/get",
                                       "domain": "local_calendar"})

    async def borrar() -> None:
        for e in await entradas():
            if e.get("title") == nombre:
                await s.lector.rest("DELETE",
                                    f"/api/config/config_entries/entry/{e['entry_id']}")

    s.limpiezas.append(borrar)
    cargadas = await s.lector.esperar(
        entradas,
        lambda es: any(e.get("title") == nombre and e.get("state") == "loaded" for e in es),
        descripcion=f"entrada {nombre!r} de local_calendar cargada",
    )
    return next(e["entry_id"] for e in cargadas if e.get("title") == nombre)


class TestDiagnosticos(BancoEscrituras):
    async def test_diagnostico_de_entrada(self) -> None:
        async with self.sesion() as s:
            entry_id = await _crear_calendario(s)

            todos = await s.accion("ha_list_diagnostics_handlers")
            self.assertIn({"domain": "local_calendar", "config_entry": True, "device": False},
                          todos["items"])
            uno = await s.accion("ha_list_diagnostics_handlers", domain="local_calendar")
            self.assertEqual(uno["items"], [{"domain": "local_calendar",
                                             "config_entry": True, "device": False}])

            diag = await s.accion("ha_get_config_entry_diagnostics", entry_id=entry_id)
            self.assertEqual((diag["entry_id"], diag["domain"]), (entry_id, "local_calendar"))
            self.assertIn("timezone", diag["data"])
            self.assertNotIn("system_info", diag)
            self.assertEqual(diag["redacted_by"], ["home_assistant", "hermes"])

            solo = await s.accion("ha_get_config_entry_diagnostics", entry_id=entry_id,
                                  keys=["timezone"], include_system_info=True)
            self.assertEqual(list(solo["data"]), ["timezone"])
            self.assertEqual(solo["keys_returned"], ["timezone"])
            self.assertIn("home_assistant", solo["system_info"])

    async def test_dispositivo_sin_diagnostico(self) -> None:
        async with self.sesion() as s:
            entradas = await s.lector.comando({"type": "config_entries/get",
                                               "domain": "kitchen_sink"})
            ids = {e["entry_id"] for e in entradas}
            dispositivos = await s.lector.comando({"type": "config/device_registry/list"})
            dispositivo = next(d for d in dispositivos if d.get("config_entry_id") in ids)

            r = await llamar(s.cliente, "ha_get_device_diagnostics",
                             device_id=dispositivo["id"])
            self.assertEqual((r["error"], r["domain"], r["kind"]),
                             ("diagnostics_not_supported", "kitchen_sink", "device"))


# ── Notificaciones persistentes ─────────────────────────────────────────────


class TestNotificaciones(BancoEscrituras):
    async def test_lista_y_descarte(self) -> None:
        nid = f"banco_012_{sufijo()}"

        async def ids(s: SesionEscrituras) -> set[str]:
            notas = await s.lector.comando({"type": "persistent_notification/get"})
            return {n["notification_id"] for n in notas}

        async with self.sesion() as s:

            async def limpiar() -> None:
                await s.lector.comando({
                    "type": "call_service", "domain": "persistent_notification",
                    "service": "dismiss", "service_data": {"notification_id": nid},
                })

            s.limpiezas.append(limpiar)
            await s.lector.comando({
                "type": "call_service", "domain": "persistent_notification",
                "service": "create",
                "service_data": {"notification_id": nid, "title": "Banco 012",
                                 "message": f"aviso password={_CENTINELA}"},
            })
            await s.lector.esperar(lambda: ids(s), lambda v: nid in v,
                                   descripcion=f"notificación {nid} creada")

            lista = await s.accion("ha_list_persistent_notifications")
            self.assertNotIn(_CENTINELA, json.dumps(lista, ensure_ascii=False))
            nota = next(n for n in lista["items"] if n["notification_id"] == nid)
            self.assertEqual(nota["title"], "Banco 012")

            tool = "ha_dismiss_persistent_notification"
            vista = await s.vista(tool, notification_id=nid)
            self.assertEqual(vista["preview"]["title"], "Banco 012")
            self.assertNotIn(_CENTINELA, json.dumps(vista, ensure_ascii=False))
            # La vista previa no ha descartado nada.
            self.assertIn(nid, await ids(s))
            self.assertEqual(await s.confirmar(tool, vista, notification_id=nid),
                             {"result": "ok"})
            await s.lector.esperar(lambda: ids(s), lambda v: nid not in v,
                                   descripcion=f"notificación {nid} descartada")
