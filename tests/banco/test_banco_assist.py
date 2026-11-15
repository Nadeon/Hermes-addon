"""Banco de Core: pipelines, motores y AI Task por las genéricas (spec 023,
T014; FR-009, FR-014, SC-005).

CAP-061 y CAP-062 no tienen tools dedicadas: van por `ha_read_ws_command` y
`ha_call_ws_command` según la tabla. La configuración del banco carga
`assist_pipeline:` (con `tts`, `stt` y `wake_word`), `ai_task:` y `llm:`.

- Lecturas: pipelines, idiomas, dispositivos, ejecuciones de depuración del
  preferido, motores de TTS y STT, APIs de LLM y preferencias de AI Task.
- `tts/engine/voices` y `wake_word/info` con un id que no existe llegan a HA:
  responde `not_found` (error de HA, no rechazo de Hermes).
- Escrituras en dos pasos, con el lector independiente comprobando cada
  efecto: crear un pipeline de prueba (con el `example` de la tabla),
  actualizarlo, marcarlo preferido, devolver el preferido original y
  borrarlo; fijar las preferencias de AI Task a sus valores actuales.

El pipeline se borra y el preferido se restaura al cerrar (limpieza del
lector), pase lo que pase. CAP-063 (satélites) no se prueba aquí: el banco
no tiene ninguno (unitarios en `tests/test_tools_generic_commands.py`).
Solo corre en el job `banco-core` del CI.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from hermes import command_table as ct
from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo

pytestmark = pytest.mark.banco

_LEER = "ha_read_ws_command"
_LLAMAR = "ha_call_ws_command"


async def _rechazo(s: SesionEscrituras, tool: str, **args: Any) -> dict[str, Any]:
    resultado = await s.cliente.call_tool(tool, args)
    assert getattr(resultado, "is_error", False), f"{tool}: se esperaba un rechazo"
    return json.loads(resultado.content[0].text)


async def _escribir(s: SesionEscrituras, tipo: str, carga: dict[str, Any]) -> Any:
    """`ha_call_ws_command` en dos pasos; devuelve lo que contestó HA."""
    vista = await s.vista(_LLAMAR, type=tipo, payload=carga)
    hecho = await s.confirmar(_LLAMAR, vista, type=tipo, payload=carga)
    assert hecho["executed"] is True, hecho
    return hecho.get("result")


class TestAssistPorLasGenericas(BancoEscrituras):
    async def test_lecturas(self) -> None:
        async with self.sesion() as s:
            pipelines = await s.accion(_LEER, type="assist_pipeline/pipeline/list")
            preferido = pipelines["result"]["preferred_pipeline"]
            self.assertTrue(preferido, pipelines)
            for tipo, carga in (
                ("assist_pipeline/language/list", {}),
                ("assist_pipeline/device/list", {}),
                ("assist_pipeline/pipeline_debug/list", {"pipeline_id": preferido}),
                ("assist_pipeline/pipeline/get", {}),
                ("tts/engine/list", {}),
                ("stt/engine/list", {}),
                ("llm/api/list", {}),
                ("ai_task/preferences/get", {}),
            ):
                with self.subTest(tipo=tipo):
                    r = await s.accion(_LEER, type=tipo, payload=carga)
                    self.assertEqual((r["command"], r["category"]), (tipo, "read"))
            for tipo, carga in (
                ("tts/engine/voices", {"engine_id": "tts.banco_no_existe", "language": "es"}),
                ("wake_word/info", {"entity_id": "wake_word.banco_no_existe"}),
            ):
                with self.subTest(tipo=tipo):
                    r = await _rechazo(s, _LEER, type=tipo, payload=carga)
                    self.assertEqual((r["error"], r["ha_code"]),
                                     ("ha_command_failed", "not_found"), r)

    async def test_ciclo_de_un_pipeline(self) -> None:
        async with self.sesion() as s:
            antes = await s.lector.comando({"type": "assist_pipeline/pipeline/list"})
            original = antes["preferred_pipeline"]

            async def restaurar() -> None:
                actual = await s.lector.comando({"type": "assist_pipeline/pipeline/list"})
                if actual["preferred_pipeline"] != original:
                    await s.lector.comando({"type": "assist_pipeline/pipeline/set_preferred",
                                            "pipeline_id": original})
                for p in actual["pipelines"]:
                    if p["name"].startswith("Banco pipeline "):
                        await s.lector.comando({"type": "assist_pipeline/pipeline/delete",
                                                "pipeline_id": p["id"]})

            s.limpiezas.append(restaurar)

            nombre = f"Banco pipeline {sufijo()}"
            ejemplo = ct.CORE_WS["assist_pipeline/pipeline/create"].example
            carga = {**ejemplo, "name": nombre, "language": "en",
                     "conversation_language": "en"}
            creado = await _escribir(s, "assist_pipeline/pipeline/create", carga)
            pid = creado["id"]
            lista = await s.lector.comando({"type": "assist_pipeline/pipeline/list"})
            self.assertIn(nombre, [p["name"] for p in lista["pipelines"]])

            nuevo = f"{nombre} editado"
            await _escribir(s, "assist_pipeline/pipeline/update",
                            {**carga, "pipeline_id": pid, "name": nuevo})
            leido = await s.lector.comando({"type": "assist_pipeline/pipeline/get",
                                            "pipeline_id": pid})
            self.assertEqual(leido["name"], nuevo)

            await _escribir(s, "assist_pipeline/pipeline/set_preferred", {"pipeline_id": pid})
            lista = await s.lector.comando({"type": "assist_pipeline/pipeline/list"})
            self.assertEqual(lista["preferred_pipeline"], pid)

            await _escribir(s, "assist_pipeline/pipeline/set_preferred",
                            {"pipeline_id": original})
            await _escribir(s, "assist_pipeline/pipeline/delete", {"pipeline_id": pid})
            lista = await s.lector.comando({"type": "assist_pipeline/pipeline/list"})
            self.assertEqual(lista["preferred_pipeline"], original)
            self.assertNotIn(pid, [p["id"] for p in lista["pipelines"]])

    async def test_preferencias_de_ai_task(self) -> None:
        async with self.sesion() as s:
            actuales = await s.lector.comando({"type": "ai_task/preferences/get"})
            campos = ("gen_data_entity_id", "gen_image_entity_id", "evaluate_entity_id",
                      "allow_automatic_evaluation")
            carga = {k: actuales[k] for k in campos if k in actuales}
            self.assertTrue(carga, actuales)
            await _escribir(s, "ai_task/preferences/set", carga)
            despues = await s.lector.comando({"type": "ai_task/preferences/get"})
            self.assertEqual(despues, actuales)
