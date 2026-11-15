"""Banco de Core: ayuda para automatizar (spec 017, tramo C, T034).

Las ocho tools de `automation_assist` solo leen, así que no entran en el
invariante de escrituras; se ejecutan aquí contra HA Core 2026.11.1 real para
comprobar que funcionan con las formas de verdad y, donde se puede, se
contrastan con el lector independiente (directo a Core, sin Hermes):

- el lector busca en el registro de entidades un interruptor de
  `kitchen_sink` que tenga dispositivo (la integración de demostración no
  crea luces; los interruptores tienen triggers, condiciones y acciones de
  dispositivo y triggers y condiciones por propósito);
- `ha_list_device_triggers/conditions/actions` con `include_capabilities`
  devuelven lo mismo que `device_automation/<tipo>/list` del lector, cada
  elemento con `capabilities.extra_fields`; un `device_id` que no existe da
  `not_found`;
- `ha_resolve_target` y `ha_explain_target` con ese `device_id` incluyen la
  entidad del interruptor, y lo que resuelve Hermes es lo que resuelve el
  lector;
- las tres de lista por target, con la entidad, devuelven los mismos nombres
  que el lector, ordenados, y no vacíos (`switch.turned_on`, `switch.is_on`,
  `switch.turn_on`);
- las genéricas rechazan esos comandos hacia su tool dedicada.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.banco.base_helpers import BancoHelpers, sin_error
from tests.banco.entorno import llamar

pytestmark = pytest.mark.banco


async def _rechazo(cliente: Any, tool: str, **args: Any) -> dict[str, Any]:
    """Llama a una tool que DEBE rechazar y devuelve su `{"error": …}`."""
    resultado = await cliente.call_tool(tool, args)
    assert getattr(resultado, "is_error", False), f"{tool}: se esperaba un rechazo"
    return json.loads(resultado.content[0].text)


async def _interruptor(s: Any) -> tuple[str, str]:
    """`(entity_id, device_id)` de un interruptor de `kitchen_sink`, según el
    registro de entidades que lee el lector."""
    entidades = await s.lector.comando({"type": "config/entity_registry/list"})
    candidatos = sorted(
        (e["entity_id"], e["device_id"]) for e in entidades
        if e.get("platform") == "kitchen_sink" and e.get("device_id")
        and e["entity_id"].startswith("switch.") and not e.get("disabled_by"))
    assert candidatos, "kitchen_sink no ha creado ningún interruptor con dispositivo"
    return candidatos[0]


class TestDispositivo(BancoHelpers):
    async def test_listas_con_capacidades(self) -> None:
        async with self.sesion() as s:
            entidad, dispositivo = await _interruptor(s)
            for tipo, tool in (("trigger", "ha_list_device_triggers"),
                               ("condition", "ha_list_device_conditions"),
                               ("action", "ha_list_device_actions")):
                with self.subTest(tool=tool):
                    r = sin_error(tool, await llamar(
                        s.cliente, tool, device_id=dispositivo, include_capabilities=True))
                    directo = await s.lector.comando(
                        {"type": f"device_automation/{tipo}/list", "device_id": dispositivo})
                    self.assertTrue(directo, f"{tipo}: el lector no ve ninguno")
                    self.assertEqual(r["device_id"], dispositivo)
                    self.assertEqual((r["count"], r["truncated"]), (len(directo), False))
                    self.assertIs(r["capabilities_truncated"], False)
                    # Cada elemento es el de HA tal cual, más sus capacidades.
                    sin_caps = [{k: v for k, v in i.items() if k != "capabilities"}
                                for i in r["items"]]
                    self.assertEqual(sin_caps, directo)
                    for item in r["items"]:
                        self.assertNotIn("capabilities_error", item)
                        self.assertIsInstance(item["capabilities"].get("extra_fields", []), list)
                    self.assertIn(dispositivo, {i["device_id"] for i in r["items"]})
            # Los triggers de un interruptor admiten la duración `for`.
            r = await llamar(s.cliente, "ha_list_device_triggers",
                             device_id=dispositivo, include_capabilities=True)
            campos = {c.get("name") for i in r["items"]
                      for c in i["capabilities"].get("extra_fields", [])}
            self.assertIn("for", campos)
            self.assertTrue(entidad)

    async def test_dispositivo_que_no_existe(self) -> None:
        async with self.sesion() as s:
            r = await _rechazo(s.cliente, "ha_list_device_triggers",
                               device_id="00000000000000000000000000000000")
            self.assertEqual(r["error"], "not_found")


class TestTargets(BancoHelpers):
    async def test_resolver_y_explicar(self) -> None:
        async with self.sesion() as s:
            entidad, dispositivo = await _interruptor(s)
            target = {"device_id": dispositivo}

            tool = "ha_resolve_target"
            r = sin_error(tool, await llamar(s.cliente, tool, target=target))
            self.assertIn(entidad, r["entities"])
            self.assertIn(dispositivo, r["devices"])
            directo = await s.lector.comando(
                {"type": "extract_from_target", "target": target})
            self.assertEqual(r["entities"], sorted(directo["referenced_entities"]))
            self.assertEqual(r["devices"], sorted(directo["referenced_devices"]))
            self.assertIs(r["truncated"], False)
            # Una referencia que no existe sale en `missing`.
            r = sin_error(tool, await llamar(
                s.cliente, tool, target={"area_id": "no_existe_017"}))
            self.assertEqual((r["entities"], r["missing"]["areas"]), ([], ["no_existe_017"]))

            tool = "ha_explain_target"
            r = sin_error(tool, await llamar(s.cliente, tool, target=target))
            self.assertEqual([(i["type"], i["id"]) for i in r["includes"]],
                             [("device", dispositivo)])
            self.assertIn(entidad, r["includes"][0]["entities"])
            self.assertEqual(r["excludes"], [])

    async def test_por_proposito(self) -> None:
        async with self.sesion() as s:
            entidad, _ = await _interruptor(s)
            target = {"entity_id": entidad}
            for tool, comando, esperado in (
                ("ha_list_triggers_for_target", "get_triggers_for_target", "switch.turned_on"),
                ("ha_list_conditions_for_target", "get_conditions_for_target", "switch.is_on"),
                ("ha_list_actions_for_target", "get_services_for_target", "switch.turn_on"),
            ):
                with self.subTest(tool=tool):
                    r = sin_error(tool, await llamar(s.cliente, tool, target=target))
                    directo = await s.lector.comando({"type": comando, "target": target})
                    self.assertEqual(r["items"], sorted(directo))
                    self.assertIn(esperado, r["items"])
                    self.assertEqual((r["count"], r["truncated"]), (len(directo), False))

    async def test_las_genericas_rechazan_hacia_la_dedicada(self) -> None:
        async with self.sesion() as s:
            r = await _rechazo(s.cliente, "ha_read_ws_command",
                               type="get_services_for_target",
                               payload={"target": {"entity_id": "switch.x"}})
            self.assertEqual((r["error"], r["tool"]),
                             ("use_dedicated_tool", "ha_list_actions_for_target"))
