"""Banco de Core: Assist y conversación (spec 023, T013; FR-014, SC-003, SC-005).

Contra el agente integrado de HA Core real (`conversation.home_assistant`,
cargado por `conversation:` en la configuración del banco desde la 018). El
banco no tiene entidades expuestas que un intent pueda accionar, así que el
efecto observable lo da un DISPARADOR DE FRASE: el test crea con tools ya
probadas un `input_boolean` de apoyo (apagado) y una automatización con
`trigger: conversation` y una frase centinela cuya acción lo enciende.

- `ha_list_conversation_sentences(search=…)` lista la frase (sondeo hasta que
  HA registra el disparador).
- `ha_list_conversation_agents` trae el integrado, y con
  `include_language_scores=true`, `preferred_language`.
- `ha_debug_conversation`: la frase → `match: true`, `source: "trigger"`; una
  frase sin sentido → `match: false`. Analizar no ejecuta: el lector sigue
  viendo el `input_boolean` apagado.
- `ha_process_conversation`: la vista previa trae `recognition` con el
  disparador y no ejecuta (barrera del lector: ningún `input_boolean.turn_on`
  en el bus); la confirmación sí (el lector lo ve encendido); el mismo token
  otra vez se rechaza.
- `ha_read_ws_command("conversation/process", …)` → `use_dedicated_tool`.

La automatización y el `input_boolean` se borran al cerrar (limpieza del
lector), pase lo que pase. Solo corre en el job `banco-core` del CI.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo
from tests.banco.base_helpers import _devolver
from tests.banco.entorno import llamar

pytestmark = pytest.mark.banco

_INTEGRADO = "conversation.home_assistant"


def _palabra() -> str:
    """Una palabra aleatoria solo de letras: con cifras, el reconocedor de
    frases podría leerlas como un número y no casar la plantilla."""
    return "".join(secrets.choice("bcdfghjklmnpqrstvwxz") for _ in range(8))


async def _rechazo(s: SesionEscrituras, tool: str, **args: Any) -> dict[str, Any]:
    """Una llamada que DEBE rechazarse (mismo patrón que
    `test_banco_actualizaciones._rechazo`)."""
    resultado = await s.cliente.call_tool(tool, args)
    assert getattr(resultado, "is_error", False), f"{tool}: se esperaba un rechazo"
    return json.loads(resultado.content[0].text)


class TestConversacion(BancoEscrituras):
    async def test_disparador_de_frase_de_punta_a_punta(self) -> None:
        hexa = sufijo()
        aid = f"banco_automation_conversacion_{hexa}"
        frase = f"frase centinela del banco {_palabra()}"
        async with self.sesion() as s:
            ib = await s.input_boolean(f"banco_input_boolean_conversacion_{hexa}")
            config = {
                "alias": aid,
                "description": "disparador de frase del banco (spec 023)",
                "triggers": [{"trigger": "conversation", "command": [frase]}],
                "actions": [{"action": "input_boolean.turn_on",
                             "target": {"entity_id": ib}}],
                "mode": "single",
            }
            s.limpiar_config("automation", aid)
            tool = "ha_create_or_update_automation"
            vista = await s.vista(tool, automation_id=aid, config=config)
            await s.confirmar(tool, vista, automation_id=aid, config=config)

            # Frases: HA registra el disparador al cargar la automatización.
            async def frases() -> list[str]:
                r = await llamar(s.cliente, "ha_list_conversation_sentences",
                                 search=frase)
                return r["items"]

            await s.lector.esperar(frases, lambda v: frase in v,
                                   descripcion="la frase del disparador en la lista")

            agentes = await s.accion("ha_list_conversation_agents",
                                     include_language_scores=True)
            self.assertEqual(agentes["items"][0]["id"], _INTEGRADO, agentes)
            self.assertIs(agentes["items"][0]["is_default_agent"], True)
            self.assertIn("preferred_language", agentes["default_agent_language_scores"])

            analisis = await s.accion("ha_debug_conversation",
                                      sentences=[frase, "xq zzv wkk plorf"])
            disparo, nada = analisis["results"]
            self.assertEqual((disparo["match"], disparo["source"]), (True, "trigger"),
                             analisis)
            self.assertIs(nada["match"], False, analisis)
            self.assertEqual((await s.lector.estado(ib))["state"], "off")

            proceso = "ha_process_conversation"
            await s.preparar_barrera()
            async with s.lector.servicios_llamados() as vistos:
                vista = await s.vista(proceso, text=frase)
                p = vista["preview"]
                self.assertEqual(p["agent"]["id"], _INTEGRADO)
                self.assertIs(p["agent"]["local"], True)
                self.assertEqual((p["recognition"]["checked"], p["recognition"]["source"]),
                                 (True, "trigger"), p)
                # La vista previa no ha ejecutado nada (barrera del lector).
                await s.barrera(vistos)
                self.assertNotIn(("input_boolean", "turn_on"), vistos)
                self.assertEqual((await s.lector.estado(ib))["state"], "off")

                r = await s.confirmar(proceso, vista, text=frase)
                self.assertIs(r["success"], True, r)
                await s.lector.esperar(
                    lambda: _devolver(vistos),
                    lambda v: ("input_boolean", "turn_on") in v,
                    descripcion="input_boolean.turn_on en el bus",
                )
            await s.esperar_estado(ib, lambda e: e is not None and e["state"] == "on",
                                   "encendido por la automatización")

            # El mismo token no vale dos veces.
            otra = await _rechazo(s, proceso, text=frase,
                                  confirmation_token=vista["confirmation_token"])
            self.assertIn("error", otra)

            # La genérica no es un atajo hacia el proceso sin vista previa.
            generica = await _rechazo(s, "ha_read_ws_command", type="conversation/process",
                                      payload={"text": frase})
            self.assertEqual((generica["error"], generica["tool"]),
                             ("use_dedicated_tool", proceso))
