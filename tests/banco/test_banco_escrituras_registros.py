"""Banco de Core: áreas, plantas, etiquetas y categorías (spec 028, tramo B, T018).

12 tools, una clase por registro. Cada test hace el ciclo completo por
Hermes: `ha_create_*` (sin token), `ha_update_*` en dos pasos (tras la vista
previa el nombre no ha cambiado; tras confirmar, sí) y `ha_delete_*` en dos
pasos (fuera de la lista). El lector comprueba cada paso con
`config/<registro>_registry/list` directo a Core y borra lo que quede al
cerrar la sesión. Las categorías van en el scope `automation`.

Nombres `banco_<registro>_<hex>`: únicos, para que un resto de un test caído
no choque con otro (HA rechaza nombres duplicados).

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo
from tests.banco.lector import ErrorCore

pytestmark = pytest.mark.banco


class _CicloRegistro(BancoEscrituras):
    """Ciclo crear → editar → borrar de un registro; las subclases dicen cuál."""

    registro: str = ""  # area, floor, label o category
    # Las tres tools, escritas enteras: el invariante de la 028 busca cada
    # nombre entre comillas en los tests del banco.
    tools: tuple[str, str, str] = ("", "", "")
    extra_crear: dict[str, Any] = {}  # campos además del nombre, comprobados en la lista
    scope: dict[str, Any] = {}  # solo categorías: {"scope": "automation"}

    @property
    def clave(self) -> str:
        return f"{self.registro}_id"

    async def _lista(self, s: SesionEscrituras) -> list[dict[str, Any]]:
        return await s.lector.comando(
            {"type": f"config/{self.registro}_registry/list", **self.scope}
        )

    async def _entrada(self, s: SesionEscrituras, id_: str) -> dict[str, Any] | None:
        return next((e for e in await self._lista(s) if e.get(self.clave) == id_), None)

    async def _por_nombre(self, s: SesionEscrituras, nombre: str) -> dict[str, Any] | None:
        return next((e for e in await self._lista(s) if e.get("name") == nombre), None)

    async def ciclo(self) -> None:
        nombre = f"banco_{self.registro}_{sufijo()}"
        async with self.sesion() as s:

            async def borrar() -> None:
                entrada = await self._por_nombre(s, nombre) or await self._por_nombre(
                    s, f"{nombre}_editado"
                )
                if entrada is not None:
                    try:
                        await s.lector.comando(
                            {
                                "type": f"config/{self.registro}_registry/delete",
                                **self.scope,
                                self.clave: entrada[self.clave],
                            }
                        )
                    except ErrorCore:
                        pass

            s.limpiezas.append(borrar)

            # Crear: sin token (no se pierde nada).
            creado = await s.accion(
                self.tools[0], **self.scope, name=nombre, **self.extra_crear
            )
            id_ = creado[self.clave]
            entrada = await self._entrada(s, id_)
            self.assertIsNotNone(entrada, f"{id_} no está en la lista de Core")
            self.assertEqual(entrada["name"], nombre)
            for campo, valor in self.extra_crear.items():
                self.assertEqual(entrada[campo], valor, campo)

            # Editar, en dos pasos.
            tool = self.tools[1]
            args = {**self.scope, self.clave: id_, "updates": {"name": f"{nombre}_editado"}}
            vista = await s.vista(tool, **args)
            self.assertEqual((await self._entrada(s, id_))["name"], nombre)
            await s.confirmar(tool, vista, **args)
            self.assertEqual((await self._entrada(s, id_))["name"], f"{nombre}_editado")

            # Borrar, en dos pasos.
            tool = self.tools[2]
            args = {**self.scope, self.clave: id_}
            vista = await s.vista(tool, **args)
            self.assertIsNotNone(await self._entrada(s, id_))
            await s.confirmar(tool, vista, **args)
            self.assertIsNone(await self._entrada(s, id_))


class TestArea(_CicloRegistro):
    registro = "area"
    tools = ("ha_create_area", "ha_update_area", "ha_delete_area")
    extra_crear = {"icon": "mdi:test-tube"}

    async def test_ciclo_completo(self) -> None:
        await self.ciclo()


class TestPlanta(_CicloRegistro):
    registro = "floor"
    tools = ("ha_create_floor", "ha_update_floor", "ha_delete_floor")
    extra_crear = {"level": 3}

    async def test_ciclo_completo(self) -> None:
        await self.ciclo()


class TestEtiqueta(_CicloRegistro):
    registro = "label"
    tools = ("ha_create_label", "ha_update_label", "ha_delete_label")
    extra_crear = {"color": "teal"}

    async def test_ciclo_completo(self) -> None:
        await self.ciclo()


class TestCategoria(_CicloRegistro):
    registro = "category"
    tools = ("ha_create_category", "ha_update_category", "ha_delete_category")
    extra_crear = {"icon": "mdi:test-tube"}
    scope = {"scope": "automation"}

    async def test_ciclo_completo(self) -> None:
        await self.ciclo()
