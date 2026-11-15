"""Banco de Core: cámaras e imágenes (spec 024, tramo 1, T011).

Las dos tools de la familia `cameras` solo leen, así que no entran en el
invariante de escrituras; se ejecutan aquí contra HA Core 2026.11.1 real (a
través del Supervisor simulado, como en producción) y se contrastan con lo
que se sembró:

- el lector crea por el flujo de configuración una cámara `local_file` con el
  JPEG gris de `ha_config/www/hermes_banco/camara.jpg` (generado por
  `tests/banco/imagen_de_prueba.py`, sin fotos) y la borra al cerrar;
  `ha_get_camera_snapshot` devuelve exactamente esos bytes como bloque de
  imagen `image/jpeg`, con sus metadatos (16×16: más pequeña que lo pedido,
  Core no la escala);
- `ha_get_image_entity` con la entidad `image` de `kitchen_sink`
  (`image.qr_code`, buscada en el registro por el lector): un PNG;
- una cámara que no existe da `not_found` (el 404 de Core), sin imagen.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras
from tests.banco.entorno import rechazo
from tests.banco.imagen_de_prueba import jpeg_gris

pytestmark = pytest.mark.banco

# Ruta del JPEG versionado dentro del /config de la HA del banco.
_FICHERO_CAMARA = "/config/www/hermes_banco/camara.jpg"


async def crear_entrada_por_flujo(
    s: SesionEscrituras, dominio: str, datos: dict[str, Any],
) -> str:
    """Entrada de `dominio` creada por el lector con el flujo `user` (REST),
    que se borra al cerrar la sesión. Devuelve su `entry_id` cuando está
    cargada."""
    async def entradas() -> list[dict[str, Any]]:
        return await s.lector.comando({"type": "config_entries/get", "domain": dominio})

    antes = {e["entry_id"] for e in await entradas()}
    estado, flujo = await s.lector.rest(
        "POST", "/api/config/config_entries/flow", {"handler": dominio})
    if estado != 200 or flujo.get("type") != "form":
        raise AssertionError(f"lector: no se pudo abrir el flujo de {dominio}: "
                             f"{estado} {flujo!r}")
    estado, fin = await s.lector.rest(
        "POST", f"/api/config/config_entries/flow/{flujo['flow_id']}", datos)
    if estado != 200 or fin.get("type") != "create_entry":
        raise AssertionError(f"lector: el flujo de {dominio} no creó la entrada: "
                             f"{estado} {fin!r}")
    # El id sale de la lista de entradas (la nueva), no de la forma de la
    # respuesta del flujo.
    nuevas = {e["entry_id"] for e in await entradas()} - antes
    if len(nuevas) != 1:
        raise AssertionError(f"lector: se esperaba una entrada nueva de {dominio}: {nuevas!r}")
    entry_id = nuevas.pop()

    async def borrar() -> None:
        await s.lector.rest("DELETE", f"/api/config/config_entries/entry/{entry_id}")

    s.limpiezas.append(borrar)
    await s.lector.esperar(
        entradas,
        lambda es: any(e.get("entry_id") == entry_id and e.get("state") == "loaded"
                       for e in es),
        descripcion=f"entrada de {dominio} cargada",
    )
    return entry_id


async def entidad_de_la_entrada(s: SesionEscrituras, entry_id: str, dominio: str) -> str:
    """`entity_id` de la entidad de `dominio` de una entrada (registro del lector)."""
    entidades = await s.lector.esperar(
        lambda: s.lector.comando({"type": "config/entity_registry/list"}),
        lambda es: any(e.get("config_entry_id") == entry_id
                       and e["entity_id"].startswith(f"{dominio}.") for e in es),
        descripcion=f"entidad {dominio} de la entrada {entry_id}",
    )
    return next(e["entity_id"] for e in entidades
                if e.get("config_entry_id") == entry_id
                and e["entity_id"].startswith(f"{dominio}."))


async def camara_local_file(s: SesionEscrituras) -> str:
    """Cámara `local_file` con el JPEG del banco; devuelve su `entity_id`."""
    entry_id = await crear_entrada_por_flujo(
        s, "local_file", {"file_path": _FICHERO_CAMARA})
    entidad = await entidad_de_la_entrada(s, entry_id, "camera")
    await s.esperar_estado(entidad, lambda e: e is not None and e["state"] != "unavailable",
                           "cámara disponible")
    return entidad


class TestCamaras(BancoEscrituras):
    async def test_instantanea_de_la_camara(self) -> None:
        async with self.sesion() as s:
            entidad = await camara_local_file(s)
            meta, imagen = await s.accion("ha_get_camera_snapshot", entity_id=entidad)
            esperado = jpeg_gris(16)
            self.assertEqual(meta["entity_id"], entidad)
            self.assertEqual(meta["content_type"], "image/jpeg")
            self.assertEqual(meta["bytes"], len(esperado))
            self.assertEqual((meta["width"], meta["height"]), (16, 16))
            self.assertEqual(meta["requested_max_width"], 640)
            self.assertEqual(imagen["_image"], "image/jpeg")
            self.assertEqual(imagen["_bytes"], esperado)
            # Ninguna URL firmada ni el token de la entidad en los metadatos.
            self.assertNotIn("token", repr(meta))

    async def test_camara_que_no_existe(self) -> None:
        async with self.sesion() as s:
            r = await rechazo(s.cliente, "ha_get_camera_snapshot",
                              entity_id="camera.no_existe_banco_024")
            self.assertEqual(r["error"], "not_found")

    async def test_imagen_de_kitchen_sink(self) -> None:
        async with self.sesion() as s:
            entidades = await s.lector.comando({"type": "config/entity_registry/list"})
            candidatas = sorted(
                e["entity_id"] for e in entidades
                if e.get("platform") == "kitchen_sink" and e["entity_id"].startswith("image."))
            self.assertTrue(candidatas, "kitchen_sink no ha creado ninguna entidad image")
            meta, imagen = await s.accion("ha_get_image_entity", entity_id=candidatas[0])
            self.assertEqual(meta["content_type"], "image/png")
            self.assertEqual(imagen["_image"], "image/png")
            self.assertTrue(imagen["_bytes"].startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(meta["bytes"], len(imagen["_bytes"]))
            self.assertNotIn("requested_max_width", meta)
