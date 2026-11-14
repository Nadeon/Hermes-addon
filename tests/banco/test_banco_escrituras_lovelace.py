"""Banco de Core: las 7 tools de escritura de Lovelace (spec 028, tramo A, T011).

Un dashboard `banco-<hex>` (HA exige un guion en `url_path`) y un recurso con
ruta local `/local/banco-<hex>.js`: nunca una URL externa, porque el
contenedor no tiene salida a internet y porque el recurso solo se registra, no
se descarga. El lector comprueba cada cambio con los comandos WebSocket de
Lovelace directo a Core (`lovelace/dashboards/list`, `lovelace/config`,
`lovelace/resources/list`), y borra lo que quede al cerrar la sesión.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo
from tests.banco.lector import ErrorCore

pytestmark = pytest.mark.banco


async def _dashboard(s: SesionEscrituras, url_path: str) -> dict[str, Any] | None:
    for d in await s.lector.comando({"type": "lovelace/dashboards/list"}):
        if d.get("url_path") == url_path:
            return d
    return None


async def _recurso(s: SesionEscrituras, url: str) -> dict[str, Any] | None:
    for r in await s.lector.comando({"type": "lovelace/resources/list"}):
        if r.get("url") == url:
            return r
    return None


class TestDashboard(BancoEscrituras):
    async def test_ciclo_completo(self) -> None:
        hexa = sufijo()
        url_path = f"banco-{hexa}"
        async with self.sesion() as s:

            async def borrar() -> None:
                d = await _dashboard(s, url_path)
                if d is not None:
                    await s.lector.comando(
                        {"type": "lovelace/dashboards/delete", "dashboard_id": d["id"]}
                    )

            s.limpiezas.append(borrar)

            # Crear: sin token (creación no destructiva).
            await s.accion(
                "ha_create_lovelace_dashboard",
                url_path=url_path,
                title=f"Banco {hexa}",
                icon="mdi:test-tube",
            )
            creado = await s.lector.esperar(
                lambda: _dashboard(s, url_path), lambda d: d is not None,
                descripcion=f"{url_path} en lovelace/dashboards/list",
            )
            self.assertEqual(
                (creado["title"], creado["mode"], creado["show_in_sidebar"]),
                (f"Banco {hexa}", "storage", True),
            )

            # Metadatos: el título va directo; `show_in_sidebar` pide token.
            tool = "ha_update_lovelace_dashboard_metadata"
            await s.accion(tool, url_path=url_path, updates={"title": f"Banco {hexa} editado"})
            self.assertEqual((await _dashboard(s, url_path))["title"], f"Banco {hexa} editado")
            updates = {"show_in_sidebar": False}
            vista = await s.vista(tool, url_path=url_path, updates=updates)
            self.assertTrue((await _dashboard(s, url_path))["show_in_sidebar"])
            await s.confirmar(tool, vista, url_path=url_path, updates=updates)
            self.assertFalse((await _dashboard(s, url_path))["show_in_sidebar"])

            # Guardar la configuración, en dos pasos.
            config = {
                "title": f"Banco {hexa}",
                "views": [
                    {
                        "title": "Vista",
                        "path": "vista",
                        "cards": [{"type": "markdown", "content": "banco de pruebas"}],
                    }
                ],
            }
            tool = "ha_save_lovelace_dashboard"
            vista = await s.vista(tool, url_path=url_path, config=config)
            with self.assertRaises(ErrorCore) as ctx:
                await s.lector.comando({"type": "lovelace/config", "url_path": url_path})
            self.assertEqual(ctx.exception.codigo, "config_not_found")
            self.assertEqual(
                await s.confirmar(tool, vista, url_path=url_path, config=config),
                {"result": "ok", "url_path": url_path},
            )
            self.assertEqual(
                await s.lector.comando({"type": "lovelace/config", "url_path": url_path}),
                config,
            )

            # Borrar, en dos pasos.
            tool = "ha_delete_lovelace_dashboard"
            vista = await s.vista(tool, url_path=url_path)
            self.assertIsNotNone(await _dashboard(s, url_path))
            await s.confirmar(tool, vista, url_path=url_path)
            self.assertIsNone(await _dashboard(s, url_path))


class TestRecurso(BancoEscrituras):
    async def test_ciclo_completo(self) -> None:
        url = f"/local/banco-{sufijo()}.js"
        async with self.sesion() as s:

            async def borrar() -> None:
                r = await _recurso(s, url)
                if r is not None:
                    await s.lector.comando(
                        {"type": "lovelace/resources/delete", "resource_id": r["id"]}
                    )

            s.limpiezas.append(borrar)

            tool = "ha_create_lovelace_resource"
            vista = await s.vista(tool, url=url, res_type="module")
            self.assertIsNone(await _recurso(s, url))
            await s.confirmar(tool, vista, url=url, res_type="module")
            creado = await _recurso(s, url)
            self.assertIsNotNone(creado)
            self.assertEqual(creado["type"], "module")

            tool = "ha_update_lovelace_resource"
            updates = {"res_type": "css"}
            vista = await s.vista(tool, resource_id=creado["id"], updates=updates)
            self.assertEqual((await _recurso(s, url))["type"], "module")
            await s.confirmar(tool, vista, resource_id=creado["id"], updates=updates)
            self.assertEqual((await _recurso(s, url))["type"], "css")

            tool = "ha_delete_lovelace_resource"
            vista = await s.vista(tool, resource_id=creado["id"])
            self.assertIsNotNone(await _recurso(s, url))
            await s.confirmar(tool, vista, resource_id=creado["id"])
            self.assertIsNone(await _recurso(s, url))
