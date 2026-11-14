"""Banco de Core: las 15 tools de escritura de automatizaciones, scripts y
escenas (spec 028, tramo A, T009).

Cada clase trabaja sobre un `input_boolean` creado por el lector: la acción de
la automatización, la secuencia del script y la escena lo encienden. Así el
efecto de disparar, ejecutar o activar se ve en el estado de una entidad que
Hermes no ha tocado, y las acciones son inocuas: `input_boolean.turn_on` no
está en la denylist, de modo que Hermes no marca la automatización ni el
script como restringidos y `ha_trigger_automation` y `ha_run_script` van por
su camino directo (sin token). El camino con token de esas dos tools es el de
`ha_call_service` con una entidad restringida, que no se mezcla aquí.

La configuración guardada se lee directo de Core
(`/api/config/<dominio>/config/<id>`, la misma ruta que usa el editor de HA) y
la entidad por `/api/states`. HA guarda y luego recarga en segundo plano
(`post_write_hook` en una tarea): por eso, antes de abrir la ventana que cuenta
las recargas, se espera a ver en la entidad el efecto de la última escritura;
si no, la recarga de esa escritura podría caer dentro de la ventana.

Control negativo en el CI (T014, anotado en el commit del tramo A): con
`ha_activate_scene` mandando a `scene.turn_on` un `entity_id` que no existe,
`TestEscena.test_ciclo_completo` cae en rojo en el job `banco de Core`.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

import pytest

from tests.banco.base_escrituras import BancoEscrituras, sufijo

pytestmark = pytest.mark.banco


def _encender(entity_id: str) -> dict[str, object]:
    return {"action": "input_boolean.turn_on", "target": {"entity_id": entity_id}}


class TestAutomatizacion(BancoEscrituras):
    async def test_ciclo_completo(self) -> None:
        hexa = sufijo()
        aid = f"banco_automation_{hexa}"
        eid = f"automation.{aid}"
        async with self.sesion() as s:
            ib = await s.input_boolean(f"banco_input_boolean_{hexa}")
            config = {
                "alias": aid,
                "description": "automatización del banco",
                "triggers": [{"trigger": "event", "event_type": f"banco_evento_{hexa}"}],
                "actions": [_encender(ib)],
                "mode": "single",
            }

            # Crear, en dos pasos: la vista previa no escribe nada en HA.
            s.limpiar_config("automation", aid)
            tool = "ha_create_or_update_automation"
            vista = await s.vista(tool, automation_id=aid, config=config)
            self.assertIsNone(vista["preview"]["current"])
            self.assertEqual((await s.config_guardada("automation", aid))[0], 404)
            self.assertEqual(
                await s.confirmar(tool, vista, automation_id=aid, config=config),
                {"result": "ok"},
            )
            estado, guardada = await s.config_guardada("automation", aid)
            self.assertEqual(estado, 200)
            self.assertEqual(guardada, {"id": aid, **config})
            await s.esperar_estado(
                eid,
                lambda e: e is not None and e["state"] == "on" and e["attributes"].get("id") == aid,
                "creada y activa",
            )

            # Editar: la configuración se REEMPLAZA (sin `description`), no se mezcla.
            nueva = {
                "alias": f"{aid}_editada",
                "triggers": config["triggers"],
                "actions": config["actions"],
                "mode": "single",
            }
            vista = await s.vista(tool, automation_id=aid, config=nueva)
            self.assertEqual(vista["preview"]["current"], guardada)
            self.assertEqual(await s.config_guardada("automation", aid), (200, guardada))
            await s.confirmar(tool, vista, automation_id=aid, config=nueva)
            self.assertEqual(await s.config_guardada("automation", aid), (200, {"id": aid, **nueva}))
            # La recarga de HA tras guardar ha terminado cuando la entidad
            # enseña el alias nuevo (mismo entity_id: va por unique_id).
            await s.esperar_estado(
                eid,
                lambda e: e is not None and e["attributes"].get("friendly_name") == nueva["alias"],
                "recargada con el alias nuevo",
            )

            await s.accion("ha_disable_automation", automation_id=eid)
            await s.esperar_estado(eid, lambda e: e is not None and e["state"] == "off", "desactivada")
            await s.accion("ha_enable_automation", automation_id=eid)
            await s.esperar_estado(eid, lambda e: e is not None and e["state"] == "on", "activada")

            # Disparar: camino directo (acción inocua); enciende el input_boolean.
            respuesta = await s.accion("ha_trigger_automation", automation_id=eid)
            self.assertNotIn("confirmation_token", str(respuesta))
            await s.esperar_estado(ib, lambda e: e is not None and e["state"] == "on", "encendido por la automatización")

            await s.recarga_vista_una_vez("ha_reload_automations", "automation")
            await s.esperar_estado(eid, lambda e: e is not None, "sigue tras recargar")

            # Borrar, en dos pasos.
            tool = "ha_delete_automation"
            vista = await s.vista(tool, automation_id=eid)
            self.assertEqual(vista["preview"]["current"]["id"], aid)
            self.assertEqual((await s.config_guardada("automation", aid))[0], 200)
            await s.confirmar(tool, vista, automation_id=eid)
            self.assertEqual((await s.config_guardada("automation", aid))[0], 404)
            await s.esperar_estado(eid, lambda e: e is None, "sin estado tras borrar")


class TestScript(BancoEscrituras):
    async def test_ciclo_completo(self) -> None:
        hexa = sufijo()
        sid = f"banco_script_{hexa}"
        eid = f"script.{sid}"
        async with self.sesion() as s:
            ib = await s.input_boolean(f"banco_input_boolean_{hexa}")
            config = {"alias": sid, "sequence": [_encender(ib)], "mode": "single"}

            s.limpiar_config("script", sid)
            tool = "ha_create_or_update_script"
            vista = await s.vista(tool, script_id=sid, config=config)
            self.assertIsNone(vista["preview"]["current"])
            self.assertEqual((await s.config_guardada("script", sid))[0], 404)
            self.assertEqual(
                await s.confirmar(tool, vista, script_id=sid, config=config), {"result": "ok"}
            )
            self.assertEqual(await s.config_guardada("script", sid), (200, config))
            # La entidad aparece cuando ha terminado la recarga de HA tras guardar.
            await s.esperar_estado(eid, lambda e: e is not None and e["state"] == "off", "creado")

            respuesta = await s.accion("ha_run_script", script_id=sid)
            self.assertNotIn("confirmation_token", str(respuesta))
            await s.esperar_estado(ib, lambda e: e is not None and e["state"] == "on", "encendido por el script")

            await s.recarga_vista_una_vez("ha_reload_scripts", "script")
            await s.esperar_estado(eid, lambda e: e is not None, "sigue tras recargar")

            tool = "ha_delete_script"
            vista = await s.vista(tool, script_id=eid)
            self.assertEqual(vista["preview"]["current"], config)
            self.assertEqual((await s.config_guardada("script", sid))[0], 200)
            await s.confirmar(tool, vista, script_id=eid)
            self.assertEqual((await s.config_guardada("script", sid))[0], 404)
            await s.esperar_estado(eid, lambda e: e is None, "sin estado tras borrar")


class TestEscena(BancoEscrituras):
    async def test_ciclo_completo(self) -> None:
        hexa = sufijo()
        scid = f"banco_scene_{hexa}"
        eid = f"scene.{scid}"
        async with self.sesion() as s:
            ib = await s.input_boolean(f"banco_input_boolean_{hexa}")
            config = {"name": scid, "icon": "mdi:test-tube", "entities": {ib: "on"}}

            # Crear: una escena NUEVA se guarda directa, sin token (así lo dice
            # la descripción de la tool); editar una existente pide token.
            s.limpiar_config("scene", scid)
            tool = "ha_create_or_update_scene"
            respuesta = await s.accion(tool, scene_id=scid, config=config)
            self.assertEqual(respuesta, {"result": "ok"})
            estado, guardada = await s.config_guardada("scene", scid)
            self.assertEqual((estado, guardada), (200, {"id": scid, **config}))
            await s.esperar_estado(
                eid,
                lambda e: e is not None and e["attributes"].get("id") == scid,
                "creada",
            )

            # Editar en dos pasos: la configuración se reemplaza (sin `icon`).
            nueva = {"name": f"{scid}_editada", "entities": {ib: "on"}}
            vista = await s.vista(tool, scene_id=scid, config=nueva)
            self.assertEqual(vista["preview"]["current"], guardada)
            self.assertEqual(await s.config_guardada("scene", scid), (200, guardada))
            await s.confirmar(tool, vista, scene_id=scid, config=nueva)
            self.assertEqual(await s.config_guardada("scene", scid), (200, {"id": scid, **nueva}))
            await s.esperar_estado(
                eid,
                lambda e: e is not None and e["attributes"].get("friendly_name") == nueva["name"],
                "recargada con el nombre nuevo",
            )

            # Activar: el input_boolean está apagado y la escena lo enciende.
            self.assertEqual((await s.lector.estado(ib))["state"], "off")
            await s.accion("ha_activate_scene", scene_id=eid)
            await s.esperar_estado(ib, lambda e: e is not None and e["state"] == "on", "encendido por la escena")

            await s.recarga_vista_una_vez("ha_reload_scenes", "scene")
            await s.esperar_estado(eid, lambda e: e is not None, "sigue tras recargar")

            tool = "ha_delete_scene"
            vista = await s.vista(tool, scene_id=eid)
            self.assertEqual(vista["preview"]["current"]["id"], scid)
            self.assertEqual((await s.config_guardada("scene", scid))[0], 200)
            await s.confirmar(tool, vista, scene_id=eid)
            self.assertEqual((await s.config_guardada("scene", scid))[0], 404)
            await s.esperar_estado(eid, lambda e: e is None, "sin estado tras borrar")

    async def test_escena_desde_el_estado_actual(self) -> None:
        hexa = sufijo()
        scid = f"banco_scene_{hexa}"
        eid = f"scene.{scid}"
        async with self.sesion() as s:
            ib = await s.input_boolean(f"banco_input_boolean_{hexa}")

            async def borrar_escena() -> None:
                # Las escenas de `scene.create` no se guardan en ningún fichero:
                # se quitan con `scene.delete`.
                await s.lector.comando(
                    {"type": "call_service", "domain": "scene", "service": "delete",
                     "target": {"entity_id": eid}}
                )

            s.limpiezas.append(borrar_escena)
            # Sin `name`: el esquema de `scene.create` de Core 2026.11.1 no lo admite.
            await s.accion("ha_create_scene_from_current", scene_id=scid, entity_ids=[ib])
            estado = await s.esperar_estado(eid, lambda e: e is not None, "creada desde el estado actual")
            self.assertEqual(estado["attributes"].get("entity_id"), [ib])
