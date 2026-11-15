"""Banco de Core: lo menor de Core por las genéricas (spec 024, tramo 1, T011).

Una ejecución por CAP de las que van por la tabla en este tramo, por
`ha_read_ws_command` / `ha_call_ws_command` contra HA Core 2026.11.1 real, con
el efecto comprobado por el lector independiente y la vista previa sin efecto:

- CAP-065 (calendario y tareas): una entrada de `local_calendar` con un
  evento creado por el lector; `calendar/event/update` y
  `calendar/event/delete` en dos pasos. Una de `local_todo` con dos tareas;
  `todo/item/move` de la segunda al principio, en dos pasos.
- CAP-072 (imágenes subidas): el lector sube el JPEG gris del banco por
  `/api/image/upload`; `image/list` lo ve y `image/delete` lo borra en dos
  pasos.
- CAP-067 (medios): `media_source/browse_media` ve el JPEG borrable de
  `ha_config/media/` y `media_source/local_source/remove` lo borra en dos
  pasos (el `media_dirs` del banco apunta a esa carpeta).
- CAP-059 (preferencias de cámara): `camera/get_prefs` y
  `camera/update_prefs` (orientación) sobre una cámara `local_file`.

CAP-066 (tags) ya la ejecuta la 011 en `test_banco_genericas.py`.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo
from tests.banco.imagen_de_prueba import jpeg_gris
from tests.banco.test_banco_camaras import (
    camara_local_file,
    crear_entrada_por_flujo,
    entidad_de_la_entrada,
)

pytestmark = pytest.mark.banco

_LEER = "ha_read_ws_command"
_LLAMAR = "ha_call_ws_command"
_BORRABLE = "media-source://media_source/local/banco_borrable.jpg"


class TestCalendarioYTareas(BancoEscrituras):
    async def test_evento_editar_y_borrar(self) -> None:
        async with self.sesion() as s:
            entry_id = await crear_entrada_por_flujo(
                s, "local_calendar",
                {"calendar_name": f"Banco 024 {sufijo()}", "import": "create_empty"})
            calendario = await entidad_de_la_entrada(s, entry_id, "calendar")
            inicio = datetime(2030, 1, 1, 10, tzinfo=timezone.utc)
            fin = inicio + timedelta(hours=1)
            await s.lector.comando({
                "type": "calendar/event/create", "entity_id": calendario,
                "event": {"summary": "Evento del banco", "dtstart": inicio.isoformat(),
                          "dtend": fin.isoformat()}})

            async def eventos() -> list[dict[str, Any]]:
                # Con `Z` y no `+00:00`: en una query, `+` se lee como espacio.
                desde = (inicio - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
                hasta = (fin + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
                estado, cuerpo = await s.lector.rest(
                    "GET", f"/api/calendars/{calendario}?start={desde}&end={hasta}")
                assert estado == 200, (estado, cuerpo)
                return cuerpo

            [evento] = await s.lector.esperar(
                eventos, lambda es: len(es) == 1, descripcion="el evento sembrado")
            uid = evento["uid"]

            carga = {"entity_id": calendario, "uid": uid,
                     "event": {"summary": "Evento cambiado", "dtstart": inicio.isoformat(),
                               "dtend": fin.isoformat()}}
            vista = await s.vista(_LLAMAR, type="calendar/event/update", payload=carga)
            self.assertEqual(vista["preview"]["cap"], "CAP-065")
            self.assertEqual([e["summary"] for e in await eventos()], ["Evento del banco"])
            await s.confirmar(_LLAMAR, vista, type="calendar/event/update", payload=carga)
            await s.lector.esperar(
                eventos, lambda es: [e["summary"] for e in es] == ["Evento cambiado"],
                descripcion="evento cambiado")

            carga = {"entity_id": calendario, "uid": uid}
            vista = await s.vista(_LLAMAR, type="calendar/event/delete", payload=carga)
            self.assertEqual(len(await eventos()), 1)
            await s.confirmar(_LLAMAR, vista, type="calendar/event/delete", payload=carga)
            await s.lector.esperar(eventos, lambda es: es == [], descripcion="evento borrado")

    async def test_mover_una_tarea(self) -> None:
        async with self.sesion() as s:
            entry_id = await crear_entrada_por_flujo(
                s, "local_todo", {"todo_list_name": f"Banco 024 {sufijo()}"})
            lista = await entidad_de_la_entrada(s, entry_id, "todo")
            for texto in ("uno", "dos"):
                await s.lector.comando({
                    "type": "call_service", "domain": "todo", "service": "add_item",
                    "target": {"entity_id": lista}, "service_data": {"item": texto}})

            async def tareas() -> list[dict[str, Any]]:
                r = await s.lector.comando({"type": "todo/item/list", "entity_id": lista})
                return r["items"]

            sembradas = await s.lector.esperar(
                tareas, lambda ts: [t["summary"] for t in ts] == ["uno", "dos"],
                descripcion="las dos tareas sembradas")
            carga = {"entity_id": lista, "uid": sembradas[1]["uid"]}
            vista = await s.vista(_LLAMAR, type="todo/item/move", payload=carga)
            self.assertEqual(vista["preview"]["cap"], "CAP-065")
            self.assertEqual([t["summary"] for t in await tareas()], ["uno", "dos"])
            await s.confirmar(_LLAMAR, vista, type="todo/item/move", payload=carga)
            await s.lector.esperar(
                tareas, lambda ts: [t["summary"] for t in ts] == ["dos", "uno"],
                descripcion="la segunda tarea, primera")


class TestImagenesSubidas(BancoEscrituras):
    async def test_listar_y_borrar(self) -> None:
        async with self.sesion() as s:
            estado, item = await s.lector.subir(
                "/api/image/upload", "file", f"banco_024_{sufijo()}.jpg", jpeg_gris(16),
                "image/jpeg")
            self.assertEqual(estado, 200, item)
            image_id = item["id"]

            async def limpiar() -> None:
                try:
                    await s.lector.comando({"type": "image/delete", "image_id": image_id})
                except Exception:  # noqa: BLE001 — ya borrada por el test
                    pass

            s.limpiezas.append(limpiar)

            async def ids() -> set[str]:
                return {i["id"] for i in await s.lector.comando({"type": "image/list"})}

            r = await s.accion(_LEER, type="image/list")
            self.assertIn(image_id, [i.get("id") for i in r["items"]])

            carga = {"image_id": image_id}
            vista = await s.vista(_LLAMAR, type="image/delete", payload=carga)
            self.assertEqual(vista["preview"]["cap"], "CAP-072")
            self.assertIn(image_id, await ids())
            await s.confirmar(_LLAMAR, vista, type="image/delete", payload=carga)
            await s.lector.esperar(ids, lambda v: image_id not in v,
                                   descripcion="imagen subida borrada")


class TestMedios(BancoEscrituras):
    async def test_navegar_y_borrar_un_fichero_local(self) -> None:
        async with self.sesion() as s:
            async def visible() -> bool:
                r = await s.lector.comando({
                    "type": "media_source/browse_media",
                    "media_content_id": "media-source://media_source/local/"})
                return _BORRABLE in json.dumps(r)

            r = await s.accion(_LEER, type="media_source/browse_media",
                               payload={"media_content_id": "media-source://media_source/local/"})
            self.assertIn(_BORRABLE, json.dumps(r))

            carga = {"media_content_id": _BORRABLE}
            vista = await s.vista(_LLAMAR, type="media_source/local_source/remove",
                                  payload=carga)
            self.assertEqual(vista["preview"]["cap"], "CAP-067")
            self.assertTrue(await visible())
            await s.confirmar(_LLAMAR, vista, type="media_source/local_source/remove",
                              payload=carga)
            await s.lector.esperar(visible, lambda v: v is False,
                                   descripcion="fichero de medios borrado")


class TestPreferenciasDeCamara(BancoEscrituras):
    async def test_leer_y_cambiar_la_orientacion(self) -> None:
        async with self.sesion() as s:
            camara = await camara_local_file(s)

            async def prefs() -> dict[str, Any]:
                return await s.lector.comando({"type": "camera/get_prefs", "entity_id": camara})

            r = await s.accion(_LEER, type="camera/get_prefs", payload={"entity_id": camara})
            self.assertEqual(r["result"], await prefs())
            self.assertEqual(r["result"]["orientation"], 1)

            carga = {"entity_id": camara, "orientation": 3}
            vista = await s.vista(_LLAMAR, type="camera/update_prefs", payload=carga)
            self.assertEqual(vista["preview"]["cap"], "CAP-059")
            self.assertEqual((await prefs())["orientation"], 1)
            await s.confirmar(_LLAMAR, vista, type="camera/update_prefs", payload=carga)
            await s.lector.esperar(prefs, lambda p: p["orientation"] == 3,
                                   descripcion="orientación cambiada")
