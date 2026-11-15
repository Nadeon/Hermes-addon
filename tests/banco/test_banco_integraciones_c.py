"""Banco de Core: la clase C por las genéricas contra HA Core 2026.11.1 real
(spec 025, T040; FR-006, FR-009, FR-011; research R-8).

Ninguna integración de la clase C arranca en el banco sin hardware ni red
salvo `usb`, que lista los puertos serie del sistema (en el contenedor no hay
ninguno: la lista sale vacía y no se exige nada de su contenido). La
configuración del banco carga `usb:` para esto. Lo demás de la clase C se
prueba con unitarios (`tests/test_tools_generic_commands_clase_c.py`) y queda
en la matriz de la 008 como «unitario; sin hardware en el banco».

Qué se comprueba contra HA real:
- `usb/list_serial_ports` y `usb/list_serial_integrations` por
  `ha_read_ws_command` devuelven una lista con el sobre de lista, la misma
  que lee el lector independiente directo a Core;
- `zwave_js/hard_reset_controller` y `thread/get_dataset_tlv` se rechazan con
  `command_denied` por las dos genéricas, sin llegar a HA;
- `zha/devices`, `read` en la tabla pero sin ZHA cargado, devuelve
  `ha_command_failed` con `ha_code` `unknown_command` y la pista de versión.

Ninguna tool nueva: `ha_read_ws_command` y `ha_call_ws_command` ya están en el
inventario del banco (`tests/banco/cobertura.py`).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.banco.base_helpers import BancoHelpers, sin_error
from tests.banco.entorno import llamar

pytestmark = pytest.mark.banco

_LEER = "ha_read_ws_command"
_LLAMAR = "ha_call_ws_command"


async def _error(cliente: Any, tool: str, **args: Any) -> dict[str, Any]:
    """Llama a una tool que DEBE devolver `{"error": …}` y lo devuelve.

    No sirve `llamar`: Hermes marca con `isError` toda respuesta de error y
    `llamar` la convierte en fallo del test; aquí el error es lo esperado.
    """
    resultado = await cliente.call_tool(tool, args)
    assert getattr(resultado, "is_error", False), f"{tool}: se esperaba un error"
    return json.loads(resultado.content[0].text)


class TestClaseCEnElBanco(BancoHelpers):
    async def test_usb_por_la_generica_de_lectura(self) -> None:
        async with self.sesion() as s:
            for comando, carga in (
                ("usb/list_serial_ports", None),
                ("usb/list_serial_ports", {"include_usage": True}),
                ("usb/list_serial_integrations", None),
            ):
                with self.subTest(comando=comando, carga=carga):
                    args: dict[str, Any] = {"type": comando}
                    if carga is not None:
                        args["payload"] = carga
                    r = sin_error(_LEER, await llamar(s.cliente, _LEER, **args))
                    self.assertEqual((r["command"], r["category"]), (comando, "read"))
                    self.assertIsInstance(r["items"], list)
                    # El lector, directo a Core y sin Hermes, ve la misma lista
                    # (sin exigir puertos: en el contenedor no hay).
                    directo = await s.lector.comando({"type": comando, **(carga or {})})
                    self.assertIsInstance(directo, list)
                    self.assertEqual(len(r["items"]), len(directo))
            # La lista de integraciones no depende del hardware: la de Hermes
            # y la del lector son la misma, elemento a elemento.
            integraciones = sin_error(_LEER, await llamar(
                s.cliente, _LEER, type="usb/list_serial_integrations"))
            directo = await s.lector.comando({"type": "usb/list_serial_integrations"})
            self.assertEqual(integraciones["items"], directo)
            self.assertTrue(all(isinstance(d, str) for d in directo))

    async def test_rechazos_contra_ha_real(self) -> None:
        async with self.sesion() as s:
            for comando in ("zwave_js/hard_reset_controller", "thread/get_dataset_tlv"):
                for tool in (_LEER, _LLAMAR):
                    with self.subTest(comando=comando, tool=tool):
                        r = await _error(s.cliente, tool, type=comando,
                                         payload={"entry_id": "<entry_id>"})
                        self.assertEqual(r["error"], "command_denied")
                        self.assertTrue(r.get("reason"))

    async def test_integracion_no_cargada_da_unknown_command(self) -> None:
        async with self.sesion() as s:
            r = await _error(s.cliente, _LEER, type="zha/devices")
            self.assertEqual(r["error"], "ha_command_failed")
            self.assertEqual(r["ha_code"], "unknown_command")
            self.assertIn("2026.11.1", r["hint"])
