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

Camino con token (T033): un script y una automatización cuya acción incluye
`input_boolean.reload` (denylist, inocuo en el banco) quedan restringidos al
guardarse (`classify_saved_config`), y `ha_run_script` y
`ha_trigger_automation` piden token: la vista previa no ejecuta nada (barrera
del lector) y la confirmación sí.

Los dos hallazgos de la 028 están arreglados por la spec 033 y ninguno de
estos tests es ya `xfail`:

- `ha_create_scene_from_current` con `name` fallaba siempre (T032 de la 028):
  ahora responde `name_not_supported` sin llamar a HA, crea sin token una
  escena temporal nueva, pide token para reemplazar una temporal y responde
  `scene_exists` ante una de `scenes.yaml` (tramo 2, T030: los cuatro
  `test_escena_desde_el_estado_*` de `TestEscena`).
- El de seguridad (el token de `ha_run_script` y `ha_trigger_automation` no
  cubría `variables`), en el tramo 1 de la 033: sus dos
  `test_el_token_ata_las_variables` comprueban contra HA real que confirmar
  con otras variables se rechaza sin ejecutar nada. Control negativo en el CI
  (T009, anotado en el commit): con `variables` fuera del hash, los dos caen
  en rojo.

Control negativo en el CI (T014, anotado en el commit del tramo A): con
`ha_activate_scene` mandando a `scene.turn_on` un `entity_id` que no existe,
`TestEscena.test_ciclo_completo` cae en rojo en el job `banco de Core`.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

import json

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo
from tests.banco.entorno import rechazo

pytestmark = pytest.mark.banco


def _encender(entity_id: str) -> dict[str, object]:
    return {"action": "input_boolean.turn_on", "target": {"entity_id": entity_id}}


# Servicio de la denylist que no hace daño en el banco (solo relee el YAML de
# `input_boolean`, que no tiene ninguno): basta para que Hermes restrinja el
# script o la automatización que lo llama.
_RECARGA_INOCUA: dict[str, object] = {"action": "input_boolean.reload"}

# Enciende el `input_boolean` que diga la variable `objetivo`: así el efecto
# de unas variables u otras se ve en entidades distintas del lector.
_ENCENDER_OBJETIVO: dict[str, object] = {
    "action": "input_boolean.turn_on",
    "target": {"entity_id": "{{ objetivo }}"},
}


async def _token_ata_variables(  # type: ignore[no-untyped-def]
    test, s, tool: str, servicio: tuple[str, str], id_args: dict[str, str], aprobado: str, otro: str
) -> None:
    """Spec 033, FR-001/FR-002, contra HA real.

    1. La vista previa con `objetivo=aprobado` enseña esas variables y no
       ejecuta nada (barrera del lector).
    2. La confirmación con `objetivo=otro` es un error de token: el lector no
       ve el servicio y los dos `input_boolean` siguen apagados.
    3. La confirmación con las variables de la vista previa se ejecuta: el
       lector ve el servicio una vez y `aprobado` encendido, `otro` no.
    """
    await s.preparar_barrera()
    async with s.lector.servicios_llamados() as vistos:
        vista = await s.vista(tool, **id_args, variables={"objetivo": aprobado})
        test.assertEqual(vista["preview"]["variables"], {"objetivo": aprobado})

        # Llamada directa, no `llamar`: Hermes marca con `isError` toda
        # respuesta `{"error": …}` y aquí el rechazo es lo esperado.
        resultado = await s.cliente.call_tool(
            tool,
            {**id_args, "variables": {"objetivo": otro}, "confirmation_token": vista["confirmation_token"]},
        )
        test.assertTrue(getattr(resultado, "is_error", False), f"{tool}: se esperaba un rechazo")
        respuesta = json.loads(resultado.content[0].text)
        test.assertIn("does not match", str(respuesta.get("error")), respuesta)
        await s.barrera(vistos)
        test.assertNotIn(servicio, vistos)
        for ib in (aprobado, otro):
            test.assertEqual((await s.lector.estado(ib))["state"], "off", ib)

        await s.confirmar(tool, vista, **id_args, variables={"objetivo": aprobado})
        await s.esperar_estado(
            aprobado, lambda e: e is not None and e["state"] == "on", "encendido tras confirmar"
        )
        await s.barrera(vistos)
    test.assertEqual(vistos.count(servicio), 1)
    test.assertEqual((await s.lector.estado(otro))["state"], "off")


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


    async def test_disparar_restringida_con_token(self) -> None:
        # T033: camino con token de `ha_trigger_automation` contra HA real.
        hexa = sufijo()
        aid = f"banco_automation_{hexa}"
        eid = f"automation.{aid}"
        async with self.sesion() as s:
            ib = await s.input_boolean(f"banco_input_boolean_{hexa}")
            config = {
                "alias": aid,
                "triggers": [{"trigger": "event", "event_type": f"banco_evento_{hexa}"}],
                "actions": [_RECARGA_INOCUA, _encender(ib)],
                "mode": "single",
            }
            s.limpiar_config("automation", aid)
            vista = await s.vista("ha_create_or_update_automation", automation_id=aid, config=config)
            await s.confirmar("ha_create_or_update_automation", vista, automation_id=aid, config=config)
            await s.esperar_estado(eid, lambda e: e is not None and e["state"] == "on", "creada")

            tool = "ha_trigger_automation"
            await s.preparar_barrera()
            async with s.lector.servicios_llamados() as vistos:
                vista = await s.vista(tool, automation_id=eid)
                self.assertEqual(vista["preview"]["entity_id"], eid)
                await s.barrera(vistos)
                self.assertNotIn(("automation", "trigger"), vistos)
                self.assertEqual((await s.lector.estado(ib))["state"], "off")
                await s.confirmar(tool, vista, automation_id=eid)
                await s.esperar_estado(
                    ib, lambda e: e is not None and e["state"] == "on", "encendido tras confirmar"
                )
            self.assertEqual(vistos.count(("automation", "trigger")), 1)

    async def test_el_token_ata_las_variables(self) -> None:
        # Spec 033 (T008): lo mismo que en `TestScript`, por
        # `ha_trigger_automation` (pasa por la misma función).
        hexa = sufijo()
        aid = f"banco_automation_{hexa}"
        eid = f"automation.{aid}"
        async with self.sesion() as s:
            aprobado = await s.input_boolean(f"banco_input_boolean_{hexa}_a")
            otro = await s.input_boolean(f"banco_input_boolean_{hexa}_b")
            config = {
                "alias": aid,
                "triggers": [{"trigger": "event", "event_type": f"banco_evento_{hexa}"}],
                "actions": [_RECARGA_INOCUA, _ENCENDER_OBJETIVO],
                "mode": "single",
            }
            s.limpiar_config("automation", aid)
            vista = await s.vista("ha_create_or_update_automation", automation_id=aid, config=config)
            await s.confirmar("ha_create_or_update_automation", vista, automation_id=aid, config=config)
            await s.esperar_estado(eid, lambda e: e is not None and e["state"] == "on", "creada")
            await _token_ata_variables(
                self,
                s,
                "ha_trigger_automation",
                ("automation", "trigger"),
                {"automation_id": eid},
                aprobado,
                otro,
            )


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


    async def _script_restringido(self, s, sid: str, secuencia: list) -> None:  # type: ignore[no-untyped-def]
        """Crea con Hermes un script cuya secuencia llama a la denylist."""
        config = {"alias": sid, "sequence": [_RECARGA_INOCUA, *secuencia], "mode": "single"}
        s.limpiar_config("script", sid)
        vista = await s.vista("ha_create_or_update_script", script_id=sid, config=config)
        await s.confirmar("ha_create_or_update_script", vista, script_id=sid, config=config)
        await s.esperar_estado(
            f"script.{sid}", lambda e: e is not None and e["state"] == "off", "creado"
        )

    async def test_ejecutar_restringido_con_token(self) -> None:
        # T033: camino con token de `ha_run_script` contra HA real.
        hexa = sufijo()
        sid = f"banco_script_{hexa}"
        async with self.sesion() as s:
            ib = await s.input_boolean(f"banco_input_boolean_{hexa}")
            await self._script_restringido(s, sid, [_encender(ib)])

            tool = "ha_run_script"
            await s.preparar_barrera()
            async with s.lector.servicios_llamados() as vistos:
                vista = await s.vista(tool, script_id=sid)
                self.assertEqual(vista["preview"]["entity_id"], f"script.{sid}")
                await s.barrera(vistos)
                self.assertNotIn(("script", "turn_on"), vistos)
                self.assertEqual((await s.lector.estado(ib))["state"], "off")
                await s.confirmar(tool, vista, script_id=sid)
                await s.esperar_estado(
                    ib, lambda e: e is not None and e["state"] == "on", "encendido tras confirmar"
                )
            self.assertEqual(vistos.count(("script", "turn_on")), 1)

    async def test_el_token_ata_las_variables(self) -> None:
        # Spec 033 (T008): antes era el `xfail` HALLAZGO de la 028
        # (`test_hallazgo_token_sin_variables`). El token de un script
        # restringido ata `variables`: confirmar con otras se rechaza sin que
        # HA vea nada, y con las de la vista previa se ejecuta con ellas.
        hexa = sufijo()
        sid = f"banco_script_{hexa}"
        async with self.sesion() as s:
            aprobado = await s.input_boolean(f"banco_input_boolean_{hexa}_a")
            otro = await s.input_boolean(f"banco_input_boolean_{hexa}_b")
            await self._script_restringido(s, sid, [_ENCENDER_OBJETIVO])
            await _token_ata_variables(
                self, s, "ha_run_script", ("script", "turn_on"), {"script_id": sid}, aprobado, otro
            )


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

    # ── ha_create_scene_from_current (spec 033, tramo 2, T030) ──────────
    # `scene.create` crea escenas TEMPORALES: sin fichero ni registro; se
    # quitan con `scene.delete`. Su atributo `entity_id` es la lista de
    # entidades capturadas, que es lo que el lector compara.

    @staticmethod
    def _borrar_temporal(s: SesionEscrituras, eid: str):  # type: ignore[no-untyped-def]
        async def borrar() -> None:
            await s.lector.comando(
                {"type": "call_service", "domain": "scene", "service": "delete",
                 "target": {"entity_id": eid}}
            )

        return borrar

    async def test_escena_desde_el_estado_actual(self) -> None:
        hexa = sufijo()
        scid = f"banco_scene_{hexa}"
        eid = f"scene.{scid}"
        tool = "ha_create_scene_from_current"
        async with self.sesion() as s:
            ib = await s.input_boolean(f"banco_input_boolean_{hexa}")
            s.limpiezas.append(self._borrar_temporal(s, eid))
            respuesta = await s.accion(tool, scene_id=scid, entity_ids=[ib])
            self.assertEqual(
                (respuesta["result"], respuesta["scene_id"], respuesta["replaced"],
                 respuesta["temporary"]),
                ("ok", eid, False, True),
            )
            estado = await s.esperar_estado(eid, lambda e: e is not None, "creada desde el estado actual")
            self.assertEqual(estado["attributes"].get("entity_id"), [ib])
            # Temporal: sin `id` de configuración.
            self.assertNotIn("id", estado["attributes"])

    async def test_escena_desde_el_estado_reemplazo_con_token(self) -> None:
        hexa = sufijo()
        scid = f"banco_scene_{hexa}"
        eid = f"scene.{scid}"
        tool = "ha_create_scene_from_current"
        async with self.sesion() as s:
            ib1 = await s.input_boolean(f"banco_input_boolean_{hexa}_1")
            ib2 = await s.input_boolean(f"banco_input_boolean_{hexa}_2")
            s.limpiezas.append(self._borrar_temporal(s, eid))
            await s.accion(tool, scene_id=scid, entity_ids=[ib1])
            await s.esperar_estado(
                eid, lambda e: e is not None and e["attributes"].get("entity_id") == [ib1], "temporal con ib1"
            )

            # Ya existe y es temporal: Core la reemplazaría en silencio, así
            # que la tool pide token y la vista previa no toca nada.
            vista = await s.vista(tool, scene_id=scid, entity_ids=[ib1, ib2])
            self.assertEqual(vista["preview"]["current_entities"], [ib1])
            self.assertEqual(vista["preview"]["new_entities"], [ib1, ib2])
            self.assertEqual((await s.lector.estado(eid))["attributes"].get("entity_id"), [ib1])

            respuesta = await s.confirmar(tool, vista, scene_id=scid, entity_ids=[ib1, ib2])
            self.assertEqual((respuesta["result"], respuesta["replaced"]), ("ok", True))
            await s.esperar_estado(
                eid,
                lambda e: e is not None and sorted(e["attributes"].get("entity_id") or []) == sorted([ib1, ib2]),
                "reemplazada con ib1 e ib2",
            )

    async def test_escena_desde_el_estado_sobre_una_de_configuracion(self) -> None:
        hexa = sufijo()
        scid = f"banco_scene_{hexa}"
        eid = f"scene.{scid}"
        async with self.sesion() as s:
            ib1 = await s.input_boolean(f"banco_input_boolean_{hexa}_1")
            ib2 = await s.input_boolean(f"banco_input_boolean_{hexa}_2")
            s.limpiar_config("scene", scid)
            config = {"name": scid, "entities": {ib1: "on"}}
            self.assertEqual(
                await s.accion("ha_create_or_update_scene", scene_id=scid, config=config),
                {"result": "ok"},
            )
            antes = await s.esperar_estado(
                eid, lambda e: e is not None and e["attributes"].get("id") == scid, "de scenes.yaml"
            )
            # Core no la tocaría (solo avisa en el log): la tool lo dice antes.
            r = await rechazo(s.cliente, "ha_create_scene_from_current", scene_id=scid, entity_ids=[ib2])
            self.assertEqual((r.get("error"), r.get("scene_id")), ("scene_exists", eid), r)
            self.assertNotIn("confirmation_token", r)
            despues = await s.lector.estado(eid)
            self.assertEqual(despues["attributes"], antes["attributes"])
            self.assertEqual(await s.config_guardada("scene", scid), (200, {"id": scid, **config}))

    async def test_escena_desde_el_estado_con_nombre(self) -> None:
        # Antes era el `xfail` HALLAZGO de la 028 (T032): `scene.create` no
        # admite `name` y Core respondía 400. Ahora la tool lo rechaza sin
        # llamar a HA (barrera del lector: ningún `scene.create` en el bus).
        hexa = sufijo()
        scid = f"banco_scene_{hexa}"
        eid = f"scene.{scid}"
        async with self.sesion() as s:
            ib = await s.input_boolean(f"banco_input_boolean_{hexa}")
            await s.preparar_barrera()
            async with s.lector.servicios_llamados() as vistos:
                r = await rechazo(
                    s.cliente, "ha_create_scene_from_current",
                    scene_id=scid, entity_ids=[ib], name=f"Escena del banco {hexa}",
                )
                self.assertEqual(r.get("error"), "name_not_supported", r)
                self.assertIn("ha_create_or_update_scene", r["hint"])
                await s.barrera(vistos)
            self.assertNotIn(("scene", "create"), vistos)
            self.assertIsNone(await s.lector.estado(eid))
