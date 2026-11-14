"""Banco de Core: mejoras de tools existentes (spec 018, FR-017).

Tramo 1: `ha_save_lovelace_dashboard` guardando UNA vista contra la HA real.
Un dashboard `banco-<hex>` (HA exige un guion en `url_path`) con tres vistas
y `title`; se guarda la vista 1 por vista, en dos pasos y sin reenviar `view`,
y el lector (`lovelace/config` directo a Core) comprueba que solo cambió esa
vista. Después, una vista previa por vista, un guardado de otro cliente (el
lector) entre medias y la confirmación: `dashboard_changed`, y en Core queda
lo del otro cliente. El lector borra el dashboard al cerrar la sesión.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo
from tests.banco.entorno import confirmar

pytestmark = pytest.mark.banco


async def _dashboard(s: SesionEscrituras, url_path: str) -> dict[str, Any] | None:
    for d in await s.lector.comando({"type": "lovelace/dashboards/list"}):
        if d.get("url_path") == url_path:
            return d
    return None


async def _config(s: SesionEscrituras, url_path: str) -> Any:
    return await s.lector.comando({"type": "lovelace/config", "url_path": url_path})


def _tres_vistas(hexa: str) -> dict[str, Any]:
    return {
        "title": f"Banco {hexa}",
        "views": [
            {"title": "Inicio", "cards": [{"type": "markdown", "content": "inicio"}]},
            {"title": "Cocina", "path": "cocina",
             "cards": [{"type": "markdown", "content": "cocina"}]},
            {"title": "Jardín", "path": "jardin", "type": "sections",
             "sections": [{"type": "grid",
                           "cards": [{"type": "markdown", "content": "jardin"}]}]},
        ],
    }


class TestGuardadoPorVista(BancoEscrituras):
    async def test_guardar_una_vista_y_dashboard_changed(self) -> None:
        hexa = sufijo()
        url_path = f"banco-{hexa}"
        tool = "ha_save_lovelace_dashboard"
        async with self.sesion() as s:

            async def borrar() -> None:
                d = await _dashboard(s, url_path)
                if d is not None:
                    await s.lector.comando(
                        {"type": "lovelace/dashboards/delete", "dashboard_id": d["id"]}
                    )

            s.limpiezas.append(borrar)

            await s.accion("ha_create_lovelace_dashboard", url_path=url_path,
                           title=f"Banco {hexa}")
            await s.lector.esperar(
                lambda: _dashboard(s, url_path), lambda d: d is not None,
                descripcion=f"{url_path} en lovelace/dashboards/list",
            )

            # Documento de partida: tres vistas y `title`, guardado completo.
            inicial = _tres_vistas(hexa)
            vista = await s.vista(tool, url_path=url_path, config=inicial)
            await s.confirmar(tool, vista, url_path=url_path)
            self.assertEqual(await _config(s, url_path), inicial)

            # Guardar solo la vista 1, en dos pasos.
            nueva = {"title": "Cocina", "path": "cocina",
                     "cards": [{"type": "markdown", "content": "cocina"},
                               {"type": "markdown", "content": f"nueva {hexa}"}]}
            vista = await s.vista(tool, url_path=url_path, view_index=1, view=nueva)
            p = vista["preview"]
            self.assertEqual((p["mode"], p["view_index"], p["views_total"]),
                             ("single_view", 1, 3))
            self.assertEqual((p["view_before"]["cards"], p["view_after"]["cards"]), (1, 2))
            self.assertEqual([v["index"] for v in p["views_kept"]], [0, 2])
            self.assertEqual(p["top_level_keys_kept"], ["title"])
            self.assertEqual(vista["omit_on_confirm"], ["view"])
            # La vista previa no cambia nada en Core.
            self.assertEqual(await _config(s, url_path), inicial)
            # Confirmar sin reenviar `view`.
            self.assertEqual(
                await s.confirmar(tool, vista, url_path=url_path, view_index=1),
                {"result": "ok", "url_path": url_path, "view_index": 1},
            )
            guardado = await _config(s, url_path)
            esperado = {**inicial,
                        "views": [inicial["views"][0], nueva, inicial["views"][2]]}
            self.assertEqual(guardado, esperado)

            # Otro cliente guarda entre la vista previa y la confirmación:
            # `dashboard_changed`, y en Core queda lo del otro cliente.
            otra = {"title": "Cocina", "cards": []}
            vista = await s.vista(tool, url_path=url_path, view_index=1, view=otra)
            del_otro = {"title": f"Banco {hexa} (otro cliente)",
                        "views": [{"title": "Única", "cards": []},
                                  {"title": "Segunda", "cards": []}]}
            await s.lector.comando({"type": "lovelace/config/save",
                                    "url_path": url_path, "config": del_otro})
            self.assertEqual(await _config(s, url_path), del_otro)
            res = await confirmar(s.cliente, tool, vista, url_path=url_path, view_index=1)
            self.assertEqual(res.get("error"), "dashboard_changed", res)
            self.assertEqual(await _config(s, url_path), del_otro)
