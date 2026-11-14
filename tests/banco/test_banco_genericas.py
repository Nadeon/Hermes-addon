"""Banco de Core: las genéricas de Core contra HA Core 2026.11.1 real
(spec 011, T027; FR-008, FR-009; FR-015 de la 008).

Ciclo completo de un tag solo por las genéricas: leer con
`ha_read_ws_command("tag/list")`, crear con `ha_call_ws_command("tag/create")`
en dos pasos y borrar con `ha_call_ws_command("tag/delete")` en dos pasos. El
efecto lo comprueba el lector independiente (directo a Core, sin Hermes), y
además se lee de vuelta por la genérica de lectura.

Corre en el job `banco-core` como los demás (`-m banco`). La configuración de
HA del banco carga `tag:`, porque los comandos `tag/*` solo existen con la
integración cargada.

Inventario (`tests/banco/cobertura.py`): `ha_call_ws_command` es de
`PROBADAS_GENERICAS`, así que el job exige que este test la llame con éxito y
pase; `sv_call_api` está en `NO_EJECUTABLES_GENERICAS` (el Supervisor del
banco es simulado). La lectura, `ha_read_ws_command`, se ejecuta aquí también,
pero el inventario, como el de los helpers, solo exige las escrituras.
"""

from __future__ import annotations

import secrets

import pytest

from tests.banco.base_helpers import BancoHelpers, sin_error
from tests.banco.entorno import confirmar, llamar

pytestmark = pytest.mark.banco

_LEER = "ha_read_ws_command"
_LLAMAR = "ha_call_ws_command"


def _ids(respuesta: dict) -> set[str]:
    return {t.get("id") for t in respuesta["items"]}


class TestGenericasConTags(BancoHelpers):
    async def test_ciclo_de_un_tag_por_las_genericas(self) -> None:
        tag_id = f"banco_tag_{secrets.token_hex(4)}"
        nombre = f"Banco genéricas {tag_id[-8:]}"
        async with self.sesion() as s:
            # Lectura: `read`, sin dos pasos, con el sobre de lista.
            antes = sin_error(_LEER, await llamar(s.cliente, _LEER, type="tag/list"))
            self.assertEqual(antes["command"], "tag/list")
            self.assertEqual(antes["category"], "read")
            self.assertNotIn(tag_id, _ids(antes))

            # Crear: la vista previa no toca HA.
            carga = {"tag_id": tag_id, "name": nombre}
            vista = sin_error(_LLAMAR, await llamar(
                s.cliente, _LLAMAR, type="tag/create", payload=carga))
            p = vista["preview"]
            self.assertEqual((p["command"], p["category"]), ("tag/create", "confirm"))
            filas = {f["path"]: f for f in p["payload_summary"]["rows"]}
            self.assertEqual(filas["tag_id"]["value"], tag_id)
            self.assertIsNone(await s.item("tag", tag_id),
                              "la vista previa creó el tag sin token")
            # Se apunta antes de confirmar: la limpieza del lector lo borra si
            # el test cae a medias.
            s.creados.append(("tag", tag_id))
            hecho = sin_error(_LLAMAR, await confirmar(
                s.cliente, _LLAMAR, vista, type="tag/create", payload=carga))
            self.assertIs(hecho["executed"], True)
            creado = await s.lector.esperar(
                lambda: s.item("tag", tag_id), lambda e: e is not None,
                descripcion=f"{tag_id} en tag/list (lector)",
            )
            self.assertEqual(creado.get("name"), nombre)

            # Leer de vuelta por la genérica.
            despues = sin_error(_LEER, await llamar(s.cliente, _LEER, type="tag/list"))
            self.assertIn(tag_id, _ids(despues))

            # La de lectura no ejecuta lo que escribe, y no toca HA.
            rechazo = await llamar(s.cliente, _LEER, type="tag/delete",
                                   payload={"tag_id": tag_id})
            self.assertEqual(rechazo.get("error"), "wrong_generic_tool")
            self.assertIsNotNone(await s.item("tag", tag_id))

            # Borrar por la genérica, en dos pasos.
            vista = sin_error(_LLAMAR, await llamar(
                s.cliente, _LLAMAR, type="tag/delete", payload={"tag_id": tag_id}))
            self.assertIsNotNone(await s.item("tag", tag_id),
                                 "la vista previa borró el tag sin token")
            sin_error(_LLAMAR, await confirmar(
                s.cliente, _LLAMAR, vista, type="tag/delete", payload={"tag_id": tag_id}))
            await s.lector.esperar(
                lambda: s.item("tag", tag_id), lambda e: e is None,
                descripcion=f"{tag_id} fuera de tag/list (lector)",
            )
