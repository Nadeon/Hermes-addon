"""Banco de Core: analytics y labs por las genéricas (spec 021, tramo c, T048).

CAP-074 va por la tabla (FR-016): las cuatro entradas contra HA Core real,
sin activar ningún envío de datos (el contenedor tampoco tiene salida a
internet). `analytics` y `labs` están en `DEFAULT_INTEGRATIONS` de Core: se
cargan sin `default_config:`.

- `ha_read_ws_command("analytics")` y `("labs/list")` leen lo mismo que el
  lector.
- `ha_call_ws_command("analytics/preferences", {"preferences": {"base":
  false}})` en dos pasos: es el valor de un banco recién hecho, así que el
  lector comprueba que `base` sigue `false`.
- `labs/update` con la primera función de `labs/list`: se cambia y se
  restaura, comprobado por el lector (sin `create_backup`). Si la lista está
  vacía, el `not_found` real de una función inexistente (anotado en el test).

`config/core/detect` está en `test_banco_configuracion_sistema.py` (T014).
Solo corre en el job `banco-core` del CI.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras
from tests.banco.entorno import llamar

pytestmark = pytest.mark.banco


async def _labs(s: SesionEscrituras) -> list[dict[str, Any]]:
    return (await s.lector.comando({"type": "labs/list"}))["features"]


class TestAnalyticsYLabs(BancoEscrituras):
    async def test_analytics_se_lee_y_no_se_activa(self) -> None:
        async with self.sesion() as s:
            real = await s.lector.comando({"type": "analytics"})
            r = await llamar(s.cliente, "ha_read_ws_command", type="analytics")
            self.assertEqual(r["result"]["preferences"], real["preferences"])
            self.assertFalse(real["preferences"].get("base", False))

            carga = {"preferences": {"base": False}}
            vista = await s.vista("ha_call_ws_command", type="analytics/preferences",
                                  payload=carga)
            self.assertEqual(vista["preview"]["cap"], "CAP-074")
            r = await s.confirmar("ha_call_ws_command", vista,
                                  type="analytics/preferences", payload=carga)
            self.assertTrue(r["executed"])
            ahora = await s.lector.comando({"type": "analytics"})
            self.assertIs(ahora["preferences"].get("base"), False)

    async def test_labs_se_lee_y_se_cambia(self) -> None:
        async with self.sesion() as s:
            funciones = await _labs(s)
            r = await llamar(s.cliente, "ha_read_ws_command", type="labs/list")
            self.assertEqual(r["result"]["features"], funciones)

            if not funciones:
                # Sin funciones en pruebas cargadas: el `not_found` real de HA.
                carga = {"domain": "banco", "preview_feature": "inexistente",
                         "enabled": True}
                vista = await s.vista("ha_call_ws_command", type="labs/update",
                                      payload=carga)
                resultado = await s.cliente.call_tool("ha_call_ws_command", {
                    "type": "labs/update", "payload": carga,
                    "confirmation_token": vista["confirmation_token"]})
                self.assertTrue(getattr(resultado, "is_error", False))
                self.assertIn("not_found", resultado.content[0].text)
                return

            f = funciones[0]
            original = bool(f["enabled"])

            async def restaurar() -> None:
                await s.lector.comando({"type": "labs/update", "domain": f["domain"],
                                        "preview_feature": f["preview_feature"],
                                        "enabled": original})

            s.limpiezas.append(restaurar)

            def estado(lista: list[dict[str, Any]]) -> bool:
                return next(x["enabled"] for x in lista
                            if (x["domain"], x["preview_feature"])
                            == (f["domain"], f["preview_feature"]))

            for valor in (not original, original):
                carga = {"domain": f["domain"], "preview_feature": f["preview_feature"],
                         "enabled": valor}
                vista = await s.vista("ha_call_ws_command", type="labs/update",
                                      payload=carga)
                self.assertEqual(estado(await _labs(s)), not valor)
                r = await s.confirmar("ha_call_ws_command", vista, type="labs/update",
                                      payload=carga)
                self.assertTrue(r["executed"])
                await s.lector.esperar(
                    lambda: _labs(s), lambda lista, v=valor: estado(lista) is v,
                    descripcion=f"labs {f['domain']}.{f['preview_feature']} = {valor}",
                )
