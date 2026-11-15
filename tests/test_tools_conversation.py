"""Tools de Assist y conversación (spec 023, T003, T004, T005 y T007).

`ha_list_conversation_agents`, `ha_list_conversation_sentences`,
`ha_debug_conversation` y `ha_process_conversation` con Home Assistant
simulado (`AsyncMock` de `ws_send` que responde por `type`). Datos ficticios:
`light.salon`, `conversation.ejemplo_llm`, la frase centinela, el centinela
`centinela-023` y un `device_id` de 32 hex inventado. Nada de la instalación
real.

Controles negativos (T016), comprobados y con recuentos en el commit:
- (a) quitar `device_id` del dict del token → cae
  `test_cambiar_un_argumento_invalida_el_token` (subcaso `device_id`);
- (b) no comprobar el agente → cae `test_agente_inexistente`;
- (c) registrar `text` en el log → cae `test_log_sin_datos`;
- (h) tratar el plazo vencido como error normal → cae
  `test_plazo_vencido_es_resultado_desconocido`.
"""

from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from structlog.testing import capture_logs

import hermes.security as security
import hermes.tools.conversation as mod
from hermes.ha import HAConnectionError

_CENTINELA = "centinela-023"
_FRASE = "frase centinela del banco"
_DISPOSITIVO = "0123456789abcdef0123456789abcdef"
_LLM = "conversation.ejemplo_llm"
_INTEGRADO = "conversation.home_assistant"


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _agentes() -> dict[str, Any]:
    return {"agents": [
        {"id": _LLM, "name": "Ejemplo LLM", "supported_languages": "*"},
        {"id": "conversation.a_otro", "name": "Otro", "supported_languages": ["en"]},
        {"id": _INTEGRADO, "name": "Home Assistant",
         "supported_languages": ["en", "es"]},
    ]}


def _intent(objetivos: int = 1) -> dict[str, Any]:
    return {
        "intent": {"name": "HassTurnOn"},
        "slots": {"name": "luz del salón"},
        "details": {"name": {"name": "name", "value": "luz del salón",
                             "text": "luz del salón"}},
        "targets": {f"light.salon_{i}" if i else "light.salon": {"matched": True}
                    for i in range(objetivos)},
        "match": True,
        "sentence_template": "enciende [la] {name}",
        "unmatched_slots": {},
        "source": "builtin",
    }


def _proceso(speech: str = "Hecho", **data: Any) -> dict[str, Any]:
    return {
        "response": {
            "speech": {"plain": {"speech": speech, "extra_data": None}},
            "card": {},
            "language": "es",
            "response_type": "action_done",
            "data": data or {"targets": [], "success": [
                {"type": "entity", "id": "light.salon", "name": "Salón"}], "failed": []},
        },
        "conversation_id": "01JCONVERSACIONFICTICIA",
        "continue_conversation": False,
    }


class _Base(unittest.IsolatedAsyncioTestCase):
    max_bytes = 131_072

    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.respuestas: dict[str, Any] = {
            "conversation/agent/list": _agentes(),
            "conversation/agent/homeassistant/language_scores": {
                "languages": {"es": {"cloud": 3, "focused_local": 2, "full_local": 3}},
                "preferred_language": "es"},
            "conversation/sentences/list": {"trigger_sentences": []},
            "conversation/agent/homeassistant/debug": {"results": [_intent()]},
            "conversation/process": _proceso(),
        }
        self.fallos: dict[str, HAConnectionError] = {}
        self.ha = MagicMock()
        self.ha.wait_ready = AsyncMock(return_value=True)
        self.ha.ws_send = AsyncMock(side_effect=self._ws_send)
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha, response_max_bytes=self.max_bytes)
        self.t = self.mcp.tools

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def _ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        tipo = payload["type"]
        if tipo in self.fallos:
            raise self.fallos[tipo]
        if tipo == "conversation/agent/homeassistant/debug" and \
                isinstance(self.respuestas[tipo], dict) and \
                self.respuestas[tipo].get("results") == [_intent()]:
            # Por defecto, una coincidencia por frase.
            return {"results": [_intent() for _ in payload["sentences"]]}
        return self.respuestas[tipo]

    def tipos(self) -> list[str]:
        return [c.args[0]["type"] for c in self.ha.ws_send.await_args_list]

    def tokens_en_disco(self) -> str:
        return "".join(p.read_text(encoding="utf-8")
                       for p in Path(self.temp_dir.name).glob("*"))


# ── T003: agentes, frases y errores ───────────────────────────────────────────

class TestListarAgentes(_Base):
    async def test_orden_e_integrado(self) -> None:
        r = await self.t["ha_list_conversation_agents"]()
        ids = [a["id"] for a in r["items"]]
        self.assertEqual(ids, [_INTEGRADO, "conversation.a_otro", _LLM])
        self.assertEqual([a["is_default_agent"] for a in r["items"]], [True, False, False])
        self.assertEqual(r["items"][2]["supported_languages"], "*")
        self.assertEqual(r["items"][0]["supported_languages"], ["en", "es"])
        self.assertEqual((r["count"], r["truncated"]), (3, False))
        self.assertNotIn("default_agent_language_scores", r)
        self.ha.ws_send.assert_awaited_once_with({"type": "conversation/agent/list"})

    async def test_idioma_y_pais_solo_si_se_dan(self) -> None:
        await self.t["ha_list_conversation_agents"](language="es", country="ES")
        self.ha.ws_send.assert_awaited_once_with(
            {"type": "conversation/agent/list", "language": "es", "country": "ES"})

    async def test_puntuaciones_bajo_demanda(self) -> None:
        r = await self.t["ha_list_conversation_agents"](include_language_scores=True,
                                                        language="es")
        self.assertEqual(r["default_agent_language_scores"]["preferred_language"], "es")
        self.assertEqual(self.tipos(), ["conversation/agent/list",
                                        "conversation/agent/homeassistant/language_scores"])
        self.assertEqual(self.ha.ws_send.await_args_list[1].args[0]["language"], "es")

    async def test_argumentos_invalidos(self) -> None:
        for kw in ({"language": "español"}, {"language": "e"}, {"country": "ESP"},
                   {"country": "1"}, {"include_language_scores": "si"}):
            with self.subTest(kw=kw):
                r = await self.t["ha_list_conversation_agents"](**kw)
                self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()


class TestListarFrases(_Base):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.respuestas["conversation/sentences/list"] = {"trigger_sentences": [
            "Enciende la luz", "apaga todo", "enciende la luz", "Apaga todo", "apaga todo",
            "Buenas noches"]}

    async def test_ordenadas_sin_repetir(self) -> None:
        r = await self.t["ha_list_conversation_sentences"]()
        # Sin distinguir mayúsculas; entre dos que solo difieren en ellas, un
        # orden fijo (el de Python) para que la lista no baile.
        self.assertEqual(r["items"], ["Apaga todo", "apaga todo", "Buenas noches",
                                      "Enciende la luz", "enciende la luz"])
        self.assertEqual((r["total"], r["count"], r["truncated"]), (5, 5, False))

    async def test_search_y_limit(self) -> None:
        r = await self.t["ha_list_conversation_sentences"](search="APAGA")
        self.assertEqual(r["items"], ["Apaga todo", "apaga todo"])
        self.assertEqual(r["total"], 2)
        r = await self.t["ha_list_conversation_sentences"](limit=2)
        self.assertEqual((r["count"], r["total"], r["truncated"]), (2, 5, True))

    async def test_argumentos_invalidos(self) -> None:
        for kw in ({"search": ""}, {"search": "  "}, {"search": "x" * 201},
                   {"limit": 0}, {"limit": 501}, {"limit": True}, {"limit": "3"}):
            with self.subTest(kw=kw):
                r = await self.t["ha_list_conversation_sentences"](**kw)
                self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()


class TestErroresDeHA(_Base):
    async def test_unknown_command_en_las_cuatro(self) -> None:
        for tipo in ("conversation/agent/list", "conversation/sentences/list",
                     "conversation/agent/homeassistant/debug"):
            self.fallos[tipo] = HAConnectionError("Unknown command.", code="unknown_command")
        llamadas = {
            "ha_list_conversation_agents": {},
            "ha_list_conversation_sentences": {},
            "ha_debug_conversation": {"sentences": ["hola"]},
            "ha_process_conversation": {"text": "hola"},
        }
        for tool, kw in llamadas.items():
            with self.subTest(tool=tool):
                r = await self.t[tool](**kw)
                self.assertEqual(r["error"], "conversation_not_loaded")
                self.assertNotIn("confirmation_token", r)
        self.assertNotIn("conversation/process", self.tipos())

    async def test_unauthorized_en_frases(self) -> None:
        self.fallos["conversation/sentences/list"] = HAConnectionError(
            "Unauthorized", code="unauthorized")
        r = await self.t["ha_list_conversation_sentences"]()
        self.assertEqual(r["error"], "unauthorized")

    async def test_otro_error_redactado(self) -> None:
        self.fallos["conversation/agent/list"] = HAConnectionError(
            f"fallo raro token={_CENTINELA}", code="home_assistant_error")
        r = await self.t["ha_list_conversation_agents"]()
        self.assertEqual((r["error"], r["ha_code"]), ("ha_error", "home_assistant_error"))
        self.assertNotIn(_CENTINELA, json.dumps(r))

    async def test_log_sin_frases_ni_agentes(self) -> None:
        self.respuestas["conversation/sentences/list"] = {"trigger_sentences": [_FRASE]}
        with capture_logs() as logs:
            await self.t["ha_list_conversation_agents"]()
            await self.t["ha_list_conversation_sentences"](search="centinela")
            await self.t["ha_debug_conversation"](sentences=[_FRASE])
        texto = json.dumps(logs, default=str)
        for prohibido in (_FRASE, "centinela", _LLM, "Ejemplo LLM", "light.salon"):
            self.assertNotIn(prohibido, texto)


# ── T004: analizar ────────────────────────────────────────────────────────────

class TestAnalizar(_Base):
    async def test_en_orden_y_formas(self) -> None:
        self.respuestas["conversation/agent/homeassistant/debug"] = {"results": [
            _intent(),
            None,
            {"match": True, "source": "trigger", "sentence_template": _FRASE},
            {**_intent(), "source": "custom", "file": "es/mias.yaml"},
        ]}
        r = await self.t["ha_debug_conversation"](
            sentences=["enciende la luz", "blablá", _FRASE, "propia"], language="es",
            device_id=_DISPOSITIVO)
        a, b, c, d = r["results"]
        self.assertEqual((a["sentence"], a["intent"], a["match"], a["source"]),
                         ("enciende la luz", "HassTurnOn", True, "builtin"))
        self.assertEqual(a["targets"], {"light.salon": {"matched": True}})
        self.assertEqual((a["targets_total"], a["targets_truncated"]), (1, False))
        self.assertEqual(b, {"sentence": "blablá", "match": False, "recognized": False})
        self.assertEqual(c, {"sentence": _FRASE, "match": True, "source": "trigger",
                             "sentence_template": _FRASE, "note": mod.NOTA_DISPARADOR})
        self.assertEqual(d["file"], "es/mias.yaml")
        self.ha.ws_send.assert_awaited_once_with({
            "type": "conversation/agent/homeassistant/debug",
            "sentences": ["enciende la luz", "blablá", _FRASE, "propia"],
            "language": "es", "device_id": _DISPOSITIVO})

    async def test_tope_de_50_objetivos(self) -> None:
        self.respuestas["conversation/agent/homeassistant/debug"] = {"results": [_intent(60)]}
        r = await self.t["ha_debug_conversation"](sentences=["enciende todo"])
        res = r["results"][0]
        self.assertEqual(len(res["targets"]), 50)
        self.assertEqual((res["targets_total"], res["targets_truncated"]), (60, True))
        self.assertIn("light.salon", res["targets"])

    async def test_respuesta_mayor_que_el_tope(self) -> None:
        resultados = [_intent(50)] * 20
        completa = mod.ajustar_analisis(
            [mod.reconocimiento(f"f{i}", r) for i, r in enumerate(resultados)], 10**9)
        tam = len(json.dumps(completa, ensure_ascii=False).encode())
        recortada = mod.ajustar_analisis(completa["results"], tam // 2)
        self.assertLessEqual(len(json.dumps(recortada, ensure_ascii=False).encode()), tam // 2)
        primero = recortada["results"][0]
        self.assertLess(len(primero["targets"]), 50)
        self.assertTrue(primero["targets_truncated"])
        self.assertEqual(primero["targets_total"], 50)
        # Por el final: se conservan los primeros.
        self.assertIn("light.salon", primero["targets"])
        muy_poco = mod.ajustar_analisis(completa["results"], 200)
        self.assertEqual(muy_poco["error"], "response_too_large")

    async def test_argumentos_invalidos(self) -> None:
        for kw in ({"sentences": []}, {"sentences": ["a"] * 21}, {"sentences": [""]},
                   {"sentences": ["x" * 501]}, {"sentences": "hola"},
                   {"sentences": ["hola"], "device_id": "ABC"},
                   {"sentences": ["hola"], "device_id": _DISPOSITIVO.upper()},
                   {"sentences": ["hola"], "language": "es es"}):
            with self.subTest(kw=kw):
                r = await self.t["ha_debug_conversation"](**kw)
                self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()

    async def test_nunca_procesa(self) -> None:
        await self.t["ha_debug_conversation"](sentences=["enciende la luz", _FRASE])
        self.assertNotIn("conversation/process", self.tipos())


# ── T005: procesar ────────────────────────────────────────────────────────────

class TestProcesarVistaPrevia(_Base):
    async def test_sin_token_no_procesa(self) -> None:
        for kw in ({}, {"agent_id": _INTEGRADO}):
            with self.subTest(kw=kw):
                v = await self.t["ha_process_conversation"](
                    text="enciende la luz", language="es", device_id=_DISPOSITIVO, **kw)
                p = v["preview"]
                self.assertIn("confirmation_token", v)
                self.assertEqual(p["agent"]["id"], _INTEGRADO)
                self.assertIs(p["agent"]["is_default_agent"], True)
                self.assertIs(p["agent"]["local"], True)
                self.assertIs(p["recognition"]["checked"], True)
                self.assertEqual(p["recognition"]["intent"], "HassTurnOn")
                self.assertEqual(p["recognition"]["targets"], {"light.salon": {"matched": True}})
                self.assertEqual(p["language"], "es")
                self.assertEqual(p["warnings"], [])
        debug = [c.args[0] for c in self.ha.ws_send.await_args_list
                 if c.args[0]["type"] == "conversation/agent/homeassistant/debug"]
        self.assertEqual(debug[0], {"type": "conversation/agent/homeassistant/debug",
                                    "sentences": ["enciende la luz"], "language": "es",
                                    "device_id": _DISPOSITIVO})
        self.assertNotIn("conversation/process", self.tipos())

    async def test_disparador_de_frase(self) -> None:
        self.respuestas["conversation/agent/homeassistant/debug"] = {"results": [
            {"match": True, "source": "trigger", "sentence_template": _FRASE}]}
        v = await self.t["ha_process_conversation"](text=_FRASE)
        p = v["preview"]
        self.assertEqual(p["recognition"], {"checked": True, "match": True,
                                            "source": "trigger", "sentence_template": _FRASE})
        self.assertEqual(p["warnings"], [mod.NOTA_DISPARADOR])
        self.assertEqual(p["language"], "default (Home Assistant's language)")
        self.assertIs(p["continues_conversation"], False)

    async def test_sin_coincidencia_emite_token(self) -> None:
        self.respuestas["conversation/agent/homeassistant/debug"] = {"results": [None]}
        v = await self.t["ha_process_conversation"](text="blablá")
        self.assertIn("confirmation_token", v)
        self.assertIs(v["preview"]["recognition"]["match"], False)
        self.assertEqual(v["preview"]["warnings"], [mod.NOTA_SIN_COINCIDENCIA])

    async def test_debug_que_falla(self) -> None:
        self.fallos["conversation/agent/homeassistant/debug"] = HAConnectionError(
            f"boom token={_CENTINELA}", code="home_assistant_error")
        v = await self.t["ha_process_conversation"](text="enciende la luz")
        self.assertIn("confirmation_token", v)
        self.assertIs(v["preview"]["recognition"]["checked"], False)
        self.assertNotIn(_CENTINELA, json.dumps(v))

    async def test_otro_agente(self) -> None:
        v = await self.t["ha_process_conversation"](text="enciende la luz", agent_id=_LLM,
                                                    conversation_id="01JPREVIA")
        p = v["preview"]
        self.assertEqual(p["agent"], {"id": _LLM, "name": "Ejemplo LLM",
                                      "is_default_agent": False, "local": "unknown"})
        self.assertNotIn("recognition", p)
        self.assertEqual(p["warnings"], [mod.AVISO_AGENTE_EXTERNO])
        self.assertIs(p["continues_conversation"], True)
        self.assertNotIn("conversation/agent/homeassistant/debug", self.tipos())

    async def test_agente_inexistente(self) -> None:
        r = await self.t["ha_process_conversation"](text="hola", agent_id="conversation.no_hay")
        self.assertEqual(r["error"], "agent_not_found")
        self.assertEqual(r["available_agents"],
                         [_INTEGRADO, "conversation.a_otro", _LLM])
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(list(Path(self.temp_dir.name).glob("*")), [])

    async def test_argumentos_invalidos(self) -> None:
        for kw in ({"text": ""}, {"text": "   "}, {"text": "x" * 2001},
                   {"text": "hola", "agent_id": "con espacio"},
                   {"text": "hola", "agent_id": "x" * 256},
                   {"text": "hola", "language": "es_"},
                   {"text": "hola", "conversation_id": "a\nb"},
                   {"text": "hola", "device_id": "1234"}):
            with self.subTest(kw=kw):
                r = await self.t["ha_process_conversation"](**kw)
                self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()


class TestProcesarToken(_Base):
    _ARGS = {"text": "enciende la luz", "agent_id": None, "language": None,
             "conversation_id": None, "device_id": None}

    async def _vista(self, **args: Any) -> str:
        return (await self.t["ha_process_conversation"](**args))["confirmation_token"]

    async def test_token_valido_y_de_un_solo_uso(self) -> None:
        args = {**self._ARGS, "language": "es", "device_id": _DISPOSITIVO}
        token = await self._vista(**args)
        r = await self.t["ha_process_conversation"](**args, confirmation_token=token)
        self.assertIs(r["success"], True)
        otra = await self.t["ha_process_conversation"](**args, confirmation_token=token)
        self.assertIn("error", otra)
        self.assertEqual(self.tipos().count("conversation/process"), 1)

    async def test_cambiar_un_argumento_invalida_el_token(self) -> None:
        base = {"text": "enciende la luz", "agent_id": _LLM, "language": "es",
                "conversation_id": "01JA", "device_id": _DISPOSITIVO}
        cambios = {"text": "abre la puerta", "agent_id": _INTEGRADO, "language": "en",
                   "conversation_id": "01JB",
                   "device_id": "fedcba9876543210fedcba9876543210"}
        for campo, valor in cambios.items():
            with self.subTest(campo=campo):
                token = await self._vista(**base)
                r = await self.t["ha_process_conversation"](
                    **{**base, campo: valor}, confirmation_token=token)
                self.assertIn("error", r)
                self.assertNotIn("success", r)
        # De `None` a un valor, uno a uno.
        for campo, valor in (("agent_id", _LLM), ("language", "es"),
                             ("conversation_id", "01JA"), ("device_id", _DISPOSITIVO)):
            with self.subTest(de_none=campo):
                token = await self._vista(**self._ARGS)
                r = await self.t["ha_process_conversation"](
                    **{**self._ARGS, campo: valor}, confirmation_token=token)
                self.assertIn("error", r)
        self.assertNotIn("conversation/process", self.tipos())

    async def test_el_fichero_del_token_no_lleva_el_texto(self) -> None:
        await self._vista(**{**self._ARGS, "text": f"di {_CENTINELA}"})
        self.assertTrue(self.tokens_en_disco())
        self.assertNotIn(_CENTINELA, self.tokens_en_disco())


class TestProcesarConfirmado(_Base):
    async def _confirmar(self, **args: Any) -> Any:
        v = await self.t["ha_process_conversation"](**args)
        return await self.t["ha_process_conversation"](
            **args, confirmation_token=v["confirmation_token"])

    async def test_envia_solo_lo_dado_con_90_s(self) -> None:
        r = await self._confirmar(text="enciende la luz", language="es")
        llamada = [c for c in self.ha.ws_send.await_args_list
                   if c.args[0]["type"] == "conversation/process"][0]
        self.assertEqual(llamada.args[0], {"type": "conversation/process",
                                           "text": "enciende la luz", "language": "es"})
        self.assertEqual(llamada.kwargs, {"timeout_seconds": 90})
        self.assertEqual(r, {
            "success": True, "response_type": "action_done", "speech": "Hecho",
            "speech_truncated": False,
            "data": {"targets": [], "success": [
                {"type": "entity", "id": "light.salon", "name": "Salón"}], "failed": []},
            "language": "es", "conversation_id": "01JCONVERSACIONFICTICIA",
            "continue_conversation": False})

    async def test_speech_largo_recortado(self) -> None:
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha, response_max_bytes=4096)
        self.t = self.mcp.tools
        self.respuestas["conversation/process"] = _proceso(speech="bla " * 5000)
        r = await self._confirmar(text="cuéntame algo", agent_id=_LLM)
        self.assertIs(r["speech_truncated"], True)
        self.assertTrue(r["speech"].startswith("bla bla"))
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False).encode()), 4096)

    async def test_centinela_tapado(self) -> None:
        self.respuestas["conversation/process"] = _proceso(
            speech=f"tu clave es password={_CENTINELA}",
            success=[{"type": "entity", "id": "light.salon", "token": _CENTINELA}],
            failed=[])
        r = await self._confirmar(text="dime la clave", agent_id=_LLM)
        self.assertNotIn(_CENTINELA, json.dumps(r))

    async def test_plazo_vencido_es_resultado_desconocido(self) -> None:
        self.fallos["conversation/process"] = HAConnectionError(
            "Timeout waiting for HA WS response for command conversation/process")
        args = {"text": "abre la puerta"}
        v = await self.t["ha_process_conversation"](**args)
        token = v["confirmation_token"]
        r = await self.t["ha_process_conversation"](**args, confirmation_token=token)
        self.assertEqual(r, {"error": "outcome_unknown",
                             "detail": mod.DETALLE_RESULTADO_DESCONOCIDO})
        self.assertIn("may have been processed anyway", r["detail"])
        # El token queda consumido: un reintento no puede ejecutar dos veces.
        del self.fallos["conversation/process"]
        otra = await self.t["ha_process_conversation"](**args, confirmation_token=token)
        self.assertNotIn("success", otra)
        self.assertEqual(self.tipos().count("conversation/process"), 1)

    async def test_sin_conexion_antes_de_enviar_no_gasta_el_token(self) -> None:
        # T020: la conexión falla ANTES de enviar (`ws_send` sin WebSocket,
        # `sent=False`): la frase seguro que no salió. Ni `outcome_unknown`
        # ni token gastado: el mismo token sirve cuando vuelve la conexión.
        # Control negativo comprobado: sin la rama `exc.sent is False`, la
        # respuesta es `outcome_unknown` y el reintento da «failed»; sin
        # `release_confirmation_token`, el reintento da «executing».
        self.fallos["conversation/process"] = HAConnectionError(
            "WebSocket no disponible para envío de comandos.", sent=False)
        args = {"text": "abre la puerta"}
        v = await self.t["ha_process_conversation"](**args)
        token = v["confirmation_token"]
        r = await self.t["ha_process_conversation"](**args, confirmation_token=token)
        self.assertNotEqual(r.get("error"), "outcome_unknown")
        self.assertIn("WebSocket no disponible", r["error"])
        self.assertIs(r["sent"], False)
        self.assertEqual(r["note"], mod.NOTA_NO_ENVIADO)
        del self.fallos["conversation/process"]
        otra = await self.t["ha_process_conversation"](**args, confirmation_token=token)
        self.assertIs(otra["success"], True)

    async def test_error_de_ha(self) -> None:
        self.fallos["conversation/process"] = HAConnectionError(
            f"Agent fallo token={_CENTINELA}", code="home_assistant_error")
        args = {"text": "abre la puerta"}
        v = await self.t["ha_process_conversation"](**args)
        token = v["confirmation_token"]
        r = await self.t["ha_process_conversation"](**args, confirmation_token=token)
        self.assertEqual(r["error"], "ha_error")
        self.assertNotIn(_CENTINELA, json.dumps(r))
        del self.fallos["conversation/process"]
        otra = await self.t["ha_process_conversation"](**args, confirmation_token=token)
        self.assertNotIn("success", otra)

    async def test_log_sin_datos(self) -> None:
        with capture_logs() as logs:
            await self._confirmar(text=_FRASE, conversation_id="01JCONVERSACIONPEDIDA",
                                  agent_id=_LLM)
            await self._confirmar(text=_FRASE)
        procesadas = [e for e in logs if e.get("event") == "conversation_processed"]
        self.assertEqual(len(procesadas), 2)
        self.assertEqual([e["is_default_agent"] for e in procesadas], [False, True])
        self.assertEqual(procesadas[0]["response_type"], "action_done")
        self.assertEqual((procesadas[0]["success_count"], procesadas[0]["failed_count"]),
                         (1, 0))
        texto = json.dumps(logs, default=str)
        for prohibido in (_FRASE, "Hecho", "01JCONVERSACION", _LLM, "light.salon"):
            self.assertNotIn(prohibido, texto)


# ── T007: descripciones ───────────────────────────────────────────────────────

class TestDescripciones(_Base):
    def _doc(self, tool: str) -> str:
        return " ".join(inspect.getdoc(self.t[tool]).split())

    def test_procesar(self) -> None:
        doc = self._doc("ha_process_conversation")
        for palabra in ("EXECUTE", "confirmation_token", "external", "ha_debug_conversation",
                        "cannot predict"):
            self.assertIn(palabra, doc)

    def test_analizar(self) -> None:
        self.assertIn("WITHOUT executing anything", self._doc("ha_debug_conversation"))

    def test_frases(self) -> None:
        doc = self._doc("ha_list_conversation_sentences")
        self.assertIn("sentence triggers", doc)
        self.assertIn("does not include Home Assistant's built-in sentences", doc)

    def test_agentes(self) -> None:
        self.assertIn("only that one is known to run locally",
                      self._doc("ha_list_conversation_agents"))


if __name__ == "__main__":
    unittest.main()
