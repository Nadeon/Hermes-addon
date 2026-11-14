"""Tools de logs de Core (spec 012, tramo A; T006-T010).

`ha_list_system_log`, `ha_get_error_log`, `ha_get_log_levels`,
`ha_set_log_level` y `ha_clear_system_log`, con Home Assistant simulado
(`AsyncMock` de `ws_send`, `call_service` y `rest_get_text_tail`). Datos
ficticios: dominios `mqtt`/`demo`, el centinela `centinela-012` y un JWT de
prueba, que no pueden aparecer en ninguna respuesta, en el log de Hermes ni en
los ficheros de token.

Controles negativos (T018), comprobados y con recuentos en el commit:
(a) quitar `redact_secrets` de los mensajes del log del sistema → cae
`test_centinela_tapado_en_respuesta_y_log` (1); de las líneas del log de
errores → cae `test_lineas_redactadas` (1); (b) emitir el token sin leer
`logger/log_info` → caen 2 de `TestSetLogLevel`; enviar un comando ya en la
vista previa → caen 6; (c) atar el token sin `level` → cae
`test_token_con_otros_argumentos_rechazado`; sin normalizarlo → cae
`test_token_nivel_normalizado_antes_de_atar`; (d) devolver lista vacía
cuando la respuesta no es una lista → caen 2 (lista y limpieza); (e) tratar
el 404 como un error genérico → cae `test_404_error_log_unavailable`;
(i) quitar `logger.set_default_level` de la denylist → caen los dos de la
denylist.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from structlog.testing import capture_logs

import hermes.security as security
import hermes.tools.core_logs as mod
from hermes.ha import HAConnectionError
from hermes.service_policy import CALL_SERVICE_DENYLIST

_CENTINELA = "centinela-012"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJjZW50aW5lbGEifQ.c2lnbmF0dXJhLWZpY3RpY2lh"
_SECRETO = f"password={_CENTINELA}"


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _registro(nombre: str, *, nivel: str = "ERROR", ts: float = 1_700_000_000.0,
              mensaje: str = "fallo", excepcion: str = "", count: int = 1) -> dict[str, Any]:
    """Una entrada de `system_log/list` con la forma de Core 2026.11.1."""
    return {
        "name": nombre,
        "message": [mensaje],
        "level": nivel,
        "source": ["homeassistant/components/demo/__init__.py", 42],
        "timestamp": ts,
        "exception": excepcion,
        "count": count,
        "first_occurred": ts - 60,
    }


class _Base(unittest.IsolatedAsyncioTestCase):
    max_bytes = 131_072

    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.registros: list[Any] = []
        self.niveles: list[Any] = []
        self.enviados: list[dict[str, Any]] = []
        self.fallos: dict[str, HAConnectionError] = {}
        self.ha = MagicMock()
        self.ha.wait_ready = AsyncMock(return_value=True)
        self.ha.ws_send = AsyncMock(side_effect=self._ws_send)
        self.ha.call_service = AsyncMock(return_value=[])
        self.ha.rest_get_text_tail = AsyncMock(return_value=[])
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha, response_max_bytes=self.max_bytes)
        self.t = self.mcp.tools

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def _ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.enviados.append(payload)
        tipo = payload["type"]
        if tipo in self.fallos:
            raise self.fallos[tipo]
        if tipo == "system_log/list":
            return self.registros
        if tipo == "logger/log_info":
            return self.niveles
        if tipo in ("logger/integration_log_level", "logger/log_level"):
            return None
        raise AssertionError(f"comando inesperado: {payload}")

    def tipos(self) -> list[str]:
        return [p["type"] for p in self.enviados]

    def ficheros_de_tokens(self) -> str:
        return "".join(p.read_text(encoding="utf-8") for p in Path(self.temp_dir.name).glob("*"))


# ── ha_list_system_log (T006) ────────────────────────────────────────────────


class TestListSystemLog(_Base):
    async def test_transforma_cada_campo(self) -> None:
        self.registros = [_registro(
            "homeassistant.components.mqtt", nivel="WARNING", ts=1_700_000_000.5,
            mensaje="sin conexión", count=3,
            excepcion="Traceback (most recent call last):\n  File x\nValueError: malo\n")]
        r = await self.t["ha_list_system_log"]()
        self.assertEqual((r["count"], r["returned"], r["truncated"]), (1, 1, False))
        e = r["items"][0]
        self.assertEqual(e["level"], "WARNING")
        self.assertEqual(e["logger"], "homeassistant.components.mqtt")
        self.assertEqual(e["messages"], ["sin conexión"])
        self.assertEqual(e["source"], {"file": "homeassistant/components/demo/__init__.py", "line": 42})
        self.assertEqual(e["count"], 3)
        self.assertEqual(e["last_seen"], "2023-11-14T22:13:20.500000+00:00")
        self.assertEqual(e["first_seen"], "2023-11-14T22:12:20.500000+00:00")
        self.assertEqual(e["exception"], "ValueError: malo")
        self.assertTrue(e["exception_truncated"])
        self.assertEqual(r["_third_party_text"]["fields"], ["messages", "exception"])
        self.assertEqual(self.tipos(), ["system_log/list"])

    async def test_sin_traza(self) -> None:
        self.registros = [_registro("homeassistant.components.mqtt")]
        e = (await self.t["ha_list_system_log"]())["items"][0]
        self.assertIsNone(e["exception"])
        self.assertFalse(e["exception_truncated"])

    async def test_traza_entera_con_include_tracebacks(self) -> None:
        traza = "Traceback (most recent call last):\n  File x\nValueError: malo"
        self.registros = [_registro("homeassistant.components.mqtt", excepcion=traza)]
        e = (await self.t["ha_list_system_log"](include_tracebacks=True))["items"][0]
        self.assertEqual(e["exception"], traza)
        self.assertFalse(e["exception_truncated"])

    async def test_orden_por_last_seen_descendente(self) -> None:
        self.registros = [_registro(f"homeassistant.components.d{i}", ts=t)
                          for i, t in enumerate((100.0, 300.0, 200.0))]
        r = await self.t["ha_list_system_log"]()
        self.assertEqual([e["logger"] for e in r["items"]],
                         ["homeassistant.components.d1", "homeassistant.components.d2",
                          "homeassistant.components.d0"])

    async def test_filtro_por_nivel_sin_distinguir_mayusculas(self) -> None:
        self.registros = [_registro("a", nivel="ERROR"), _registro("b", nivel="WARNING")]
        for nivel in ("warning", "WARNING", "Warning"):
            r = await self.t["ha_list_system_log"](level=nivel)
            self.assertEqual([e["logger"] for e in r["items"]], ["b"], nivel)

    async def test_filtro_por_integracion(self) -> None:
        nombres = ["homeassistant.components.mqtt", "homeassistant.components.mqtt.client",
                   "custom_components.mqtt", "homeassistant.components.mqtt_room",
                   "homeassistant.core"]
        self.registros = [_registro(n, ts=100.0 - i) for i, n in enumerate(nombres)]
        r = await self.t["ha_list_system_log"](integration="mqtt")
        self.assertEqual([e["logger"] for e in r["items"]], nombres[:3])

    async def test_argumentos_invalidos_sin_llamar_a_ha(self) -> None:
        for kw, campo in (({"level": "verbose"}, "level"), ({"level": "NOTSET"}, "level"),
                          ({"integration": "Mqtt X"}, "integration"),
                          ({"integration": "../mqtt"}, "integration")):
            with self.subTest(kw=kw):
                r = await self.t["ha_list_system_log"](**kw)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", campo))
        self.ha.ws_send.assert_not_awaited()

    async def test_respuesta_que_no_es_lista_es_error(self) -> None:
        self.registros = {"entries": []}
        r = await self.t["ha_list_system_log"]()
        self.assertIn("error", r)
        self.assertNotIn("items", r)

    async def test_unknown_command_es_system_log_unavailable(self) -> None:
        self.fallos["system_log/list"] = HAConnectionError(
            "Unknown command.", code="unknown_command")
        r = await self.t["ha_list_system_log"]()
        self.assertEqual((r["error"], r["ha_code"]), ("system_log_unavailable", "unknown_command"))

    async def test_centinela_tapado_en_respuesta_y_log(self) -> None:
        self.registros = [_registro(
            "homeassistant.components.demo", mensaje=f"login fallido {_SECRETO} {_JWT}",
            excepcion=f"Traceback\nRuntimeError: {_SECRETO} {_JWT}")]
        for completo in (False, True):
            with capture_logs() as logs:
                r = await self.t["ha_list_system_log"](include_tracebacks=completo)
            texto = json.dumps(r, ensure_ascii=False)
            self.assertNotIn(_CENTINELA, texto)
            self.assertNotIn(_JWT, texto)
            self.assertIn("login fallido", texto)
            self.assertNotIn(_CENTINELA, json.dumps(logs, default=str))
            evento = next(e for e in logs if e["event"] == "ha_list_system_log_ok")
            self.assertEqual(evento["count"], 1)
            self.assertNotIn("login fallido", json.dumps(logs, default=str))

    async def test_recorte_a_response_max_bytes(self) -> None:
        self.max_bytes = 20_000
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha, response_max_bytes=self.max_bytes)
        self.registros = [_registro(f"homeassistant.components.d{i}", ts=float(i),
                                    mensaje="x" * 500) for i in range(200)]
        r = await self.mcp.tools["ha_list_system_log"]()
        self.assertTrue(r["truncated"])
        self.assertEqual(r["count"], 200)
        self.assertEqual(r["returned"], len(r["items"]))
        self.assertLess(r["returned"], 200)
        self.assertGreater(r["returned"], 0)
        self.assertEqual(r["_response_limit"]["returned"], r["returned"])
        self.assertEqual(r["_response_limit"]["total"], 200)
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False).encode()), self.max_bytes)
        # Se quedan las más recientes.
        self.assertEqual(r["items"][0]["logger"], "homeassistant.components.d199")


# ── ha_get_error_log (T007) ──────────────────────────────────────────────────


class TestGetErrorLog(_Base):
    async def test_lineas_acotadas(self) -> None:
        for pedidas, esperadas in ((0, 1), (-5, 1), (5000, 1000), (50, 50)):
            self.ha.rest_get_text_tail.reset_mock()
            r = await self.t["ha_get_error_log"](lines=pedidas)
            self.ha.rest_get_text_tail.assert_awaited_once_with("/error_log", lines=esperadas)
            self.assertEqual(r["lines_requested"], esperadas)
        self.ha.rest_get_text_tail.reset_mock()
        await self.t["ha_get_error_log"]()
        self.ha.rest_get_text_tail.assert_awaited_once_with("/error_log", lines=100)

    async def test_lineas_redactadas(self) -> None:
        self.ha.rest_get_text_tail.return_value = [
            "2026-11-14 INFO arranque", f"2026-11-14 ERROR {_SECRETO}", f"token {_JWT}"]
        with capture_logs() as logs:
            r = await self.t["ha_get_error_log"](lines=3)
        texto = json.dumps(r, ensure_ascii=False)
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn(_JWT, texto)
        self.assertTrue(r["redacted"])
        self.assertEqual(r["lines_returned"], 3)
        self.assertFalse(r["truncated"])
        self.assertTrue(r["log"].startswith("2026-11-14 INFO arranque\n"))
        # El log de Hermes no lleva líneas.
        self.assertNotIn("arranque", json.dumps(logs, default=str))

    async def test_sin_nada_que_redactar(self) -> None:
        self.ha.rest_get_text_tail.return_value = ["a", "b"]
        r = await self.t["ha_get_error_log"]()
        self.assertFalse(r["redacted"])
        self.assertEqual(r["log"], "a\nb\n")

    async def test_ultimas_lineas_que_caben(self) -> None:
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha, response_max_bytes=4_000)
        self.ha.rest_get_text_tail.return_value = [f"linea {i} " + "z" * 80 for i in range(300)]
        r = await self.mcp.tools["ha_get_error_log"](lines=300)
        self.assertTrue(r["truncated"])
        self.assertIn("hint", r)
        self.assertLess(r["lines_returned"], 300)
        self.assertTrue(r["log"].rstrip("\n").endswith("linea 299 " + "z" * 80))
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False).encode()), 4_000)

    async def test_404_error_log_unavailable(self) -> None:
        self.ha.rest_get_text_tail.side_effect = HAConnectionError("no", status=404)
        r = await self.t["ha_get_error_log"]()
        self.assertEqual(r["error"], "error_log_unavailable")
        self.assertIn("duplicate_log_file", r["detail"])
        self.assertIn("sv_get_core_logs", r["hint"])
        self.assertIn("core_diagnostics", r["hint"])

    async def test_otro_error_redactado(self) -> None:
        self.ha.rest_get_text_tail.side_effect = HAConnectionError(
            f"HA REST GET /error_log failed 500 {_SECRETO}", status=500)
        r = await self.t["ha_get_error_log"]()
        self.assertNotEqual(r["error"], "error_log_unavailable")
        self.assertNotIn(_CENTINELA, json.dumps(r))


# ── ha_get_log_levels (T008) ─────────────────────────────────────────────────


class TestGetLogLevels(_Base):
    async def test_nombres_de_nivel_y_orden(self) -> None:
        self.niveles = [{"domain": d, "level": n} for d, n in (
            ("zwave_js", 10), ("mqtt", 20), ("demo", 30), ("light", 40),
            ("sensor", 50), ("api", 0), ("raro", 15))]
        r = await self.t["ha_get_log_levels"]()
        self.assertEqual([i["domain"] for i in r["items"]],
                         ["api", "demo", "light", "mqtt", "raro", "sensor", "zwave_js"])
        niveles = {i["domain"]: (i["level"], i["level_value"]) for i in r["items"]}
        self.assertEqual(niveles["zwave_js"], ("DEBUG", 10))
        self.assertEqual(niveles["mqtt"], ("INFO", 20))
        self.assertEqual(niveles["demo"], ("WARNING", 30))
        self.assertEqual(niveles["light"], ("ERROR", 40))
        self.assertEqual(niveles["sensor"], ("CRITICAL", 50))
        self.assertEqual(niveles["api"], ("NOTSET", 0))
        self.assertEqual(niveles["raro"], ("LEVEL 15", 15))
        self.assertEqual(r["count"], 7)

    async def test_filtro_domain(self) -> None:
        self.niveles = [{"domain": "mqtt", "level": 30}, {"domain": "demo", "level": 30}]
        r = await self.t["ha_get_log_levels"](domain="mqtt")
        self.assertEqual([i["domain"] for i in r["items"]], ["mqtt"])

    async def test_domain_invalido(self) -> None:
        r = await self.t["ha_get_log_levels"](domain="homeassistant.components.mqtt")
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "domain"))
        self.ha.ws_send.assert_not_awaited()

    async def test_recorte(self) -> None:
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha, response_max_bytes=2_000)
        self.niveles = [{"domain": f"dominio_{i:03d}", "level": 30} for i in range(200)]
        r = await self.mcp.tools["ha_get_log_levels"]()
        self.assertTrue(r["truncated"])
        self.assertEqual(r["count"], 200)
        self.assertEqual(r["returned"], len(r["items"]))
        self.assertLessEqual(len(json.dumps(r).encode()), 2_000)


# ── ha_set_log_level (T009) ──────────────────────────────────────────────────


class TestSetLogLevel(_Base):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.niveles = [{"domain": "mqtt", "level": 30}]

    def _escrituras(self) -> list[dict[str, Any]]:
        return [p for p in self.enviados if p["type"] != "logger/log_info"]

    async def test_validacion_sin_llamar_a_ha(self) -> None:
        casos = [
            ({"level": "verbose", "integration": "mqtt"}, "level"),
            ({"level": "WARN", "integration": "mqtt"}, "level"),
            ({"level": "FATAL", "integration": "mqtt"}, "level"),
            ({"level": "DEBUG"}, "integration"),
            ({"level": "DEBUG", "integration": "mqtt", "module": "a.b"}, "integration"),
            ({"level": "DEBUG", "module": "con espacios"}, "module"),
            ({"level": "DEBUG", "module": "a" * 256}, "module"),
            ({"level": "DEBUG", "integration": "Mqtt"}, "integration"),
            ({"level": "DEBUG", "integration": "mqtt", "persistence": "always"}, "persistence"),
        ]
        for kw, campo in casos:
            with self.subTest(kw=kw):
                r = await self.t["ha_set_log_level"](**kw)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", campo))
        self.ha.ws_send.assert_not_awaited()

    async def test_vista_previa_de_integracion(self) -> None:
        for persistencia in ("none", "once", "permanent"):
            self.enviados.clear()
            r = await self.t["ha_set_log_level"](
                level="debug", integration="mqtt", persistence=persistencia)
            p = r["preview"]
            self.assertEqual(p["target"], {"type": "integration", "name": "mqtt"})
            self.assertEqual(p["previous_level"], "WARNING")
            self.assertIsNone(p["previous_level_note"])
            self.assertEqual(p["new_level"], "DEBUG")
            self.assertEqual(p["persistence"], persistencia)
            self.assertEqual(p["persistence_effect"], mod._PERSISTENCIAS[persistencia])
            self.assertIn("every logger of this integration", p["effect"])
            self.assertIsInstance(r["confirmation_token"], str)
            # Lee el nivel y NO escribe nada.
            self.assertEqual(self.tipos(), ["logger/log_info"])
        self.assertEqual(mod._PERSISTENCIAS["none"], "Until Home Assistant restarts.")

    async def test_vista_previa_integracion_no_cargada(self) -> None:
        r = await self.t["ha_set_log_level"](level="INFO", integration="demo")
        self.assertIsNone(r["preview"]["previous_level"])
        self.assertTrue(r["preview"]["previous_level_note"])
        self.assertIn("confirmation_token", r)

    async def test_vista_previa_notset(self) -> None:
        r = await self.t["ha_set_log_level"](level="notset", integration="mqtt")
        self.assertEqual(r["preview"]["new_level"], "NOTSET")
        self.assertIn("Removes the saved level", r["preview"]["effect"])

    async def test_vista_previa_de_modulo_sin_leer_niveles(self) -> None:
        r = await self.t["ha_set_log_level"](
            level="DEBUG", module="homeassistant.components.mqtt.client")
        p = r["preview"]
        self.assertEqual(p["target"], {"type": "module",
                                       "name": "homeassistant.components.mqtt.client"})
        self.assertIsNone(p["previous_level"])
        self.assertEqual(p["previous_level_note"],
                         "Home Assistant does not expose the level of a single module.")
        self.ha.ws_send.assert_not_awaited()

    async def test_confirmacion_de_integracion(self) -> None:
        args = {"level": "DEBUG", "integration": "mqtt", "persistence": "once"}
        vista = await self.t["ha_set_log_level"](**args)
        r = await self.t["ha_set_log_level"](**args, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r, {"result": "ok", "target": {"type": "integration", "name": "mqtt"},
                             "level": "DEBUG", "persistence": "once"})
        self.assertEqual(self._escrituras(), [{
            "type": "logger/integration_log_level", "integration": "mqtt",
            "level": "DEBUG", "persistence": "once"}])

    async def test_confirmacion_de_modulo(self) -> None:
        args = {"level": "WARNING", "module": "homeassistant.components.mqtt"}
        vista = await self.t["ha_set_log_level"](**args)
        await self.t["ha_set_log_level"](**args, confirmation_token=vista["confirmation_token"])
        self.assertEqual(self._escrituras(), [{
            "type": "logger/log_level", "module": "homeassistant.components.mqtt",
            "level": "WARNING", "persistence": "none"}])

    async def test_token_con_otros_argumentos_rechazado(self) -> None:
        base = {"level": "DEBUG", "integration": "mqtt", "persistence": "none"}
        vista = await self.t["ha_set_log_level"](**base)
        token = vista["confirmation_token"]
        for otros in (
            {**base, "level": "INFO"},
            {**base, "integration": "demo"},
            {"level": "DEBUG", "module": "mqtt", "persistence": "none"},
            {**base, "persistence": "permanent"},
        ):
            with self.subTest(otros=otros):
                r = await self.t["ha_set_log_level"](**otros, confirmation_token=token)
                self.assertIn("error", r)
        self.assertEqual(self._escrituras(), [])

    async def test_token_nivel_normalizado_antes_de_atar(self) -> None:
        vista = await self.t["ha_set_log_level"](level="debug", integration="mqtt")
        r = await self.t["ha_set_log_level"](
            level="DEBUG", integration="mqtt", confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["result"], "ok")

    async def test_token_reutilizado(self) -> None:
        args = {"level": "DEBUG", "integration": "mqtt"}
        vista = await self.t["ha_set_log_level"](**args)
        await self.t["ha_set_log_level"](**args, confirmation_token=vista["confirmation_token"])
        r = await self.t["ha_set_log_level"](**args, confirmation_token=vista["confirmation_token"])
        self.assertIn("error", r)
        self.assertEqual(len(self._escrituras()), 1)

    async def test_not_found_al_confirmar(self) -> None:
        args = {"level": "DEBUG", "integration": "mqtt"}
        vista = await self.t["ha_set_log_level"](**args)
        self.fallos["logger/integration_log_level"] = HAConnectionError(
            "Integration not found", code="not_found")
        r = await self.t["ha_set_log_level"](**args, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r, {"error": "not_found", "target": {"type": "integration", "name": "mqtt"}})
        fichero = json.loads(self.ficheros_de_tokens())
        self.assertEqual(fichero["state"], "failed")

    async def test_lectura_previa_fallida_sin_token(self) -> None:
        self.fallos["logger/log_info"] = HAConnectionError("caída")
        r = await self.t["ha_set_log_level"](level="DEBUG", integration="mqtt")
        self.assertEqual(r["error"], "preview_unavailable")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.ficheros_de_tokens(), "")

    async def test_error_de_ha_con_centinela(self) -> None:
        args = {"level": "DEBUG", "integration": "mqtt"}
        vista = await self.t["ha_set_log_level"](**args)
        self.fallos["logger/integration_log_level"] = HAConnectionError(f"fallo {_SECRETO} {_JWT}")
        with capture_logs() as logs:
            r = await self.t["ha_set_log_level"](
                **args, confirmation_token=vista["confirmation_token"])
        for texto in (json.dumps(r), json.dumps(vista), self.ficheros_de_tokens(),
                      json.dumps(logs, default=str)):
            self.assertNotIn(_CENTINELA, texto)
            self.assertNotIn(_JWT, texto)

    async def test_vista_previa_con_centinela_en_la_lectura(self) -> None:
        self.fallos["logger/log_info"] = HAConnectionError(f"caída {_SECRETO}")
        r = await self.t["ha_set_log_level"](level="DEBUG", integration="mqtt")
        self.assertNotIn(_CENTINELA, json.dumps(r))


# ── ha_clear_system_log (T010) ───────────────────────────────────────────────


class TestClearSystemLog(_Base):
    async def test_vista_previa(self) -> None:
        self.registros = [_registro("a", nivel="ERROR"), _registro("b", nivel="ERROR"),
                          _registro("c", nivel="WARNING")]
        r = await self.t["ha_clear_system_log"]()
        p = r["preview"]
        self.assertEqual(p["entries"], 3)
        self.assertEqual(p["by_level"], {"ERROR": 2, "WARNING": 1})
        self.assertEqual(p["effect"], mod._CLEAR_EFFECT)
        self.assertIn("Does not touch the log file", p["effect"])
        self.assertIn("confirmation_token", r)
        self.ha.call_service.assert_not_awaited()

    async def test_log_vacio_unchanged_sin_token(self) -> None:
        r = await self.t["ha_clear_system_log"]()
        self.assertEqual(r, {"result": "unchanged", "entries": 0})
        self.assertEqual(self.ficheros_de_tokens(), "")

    async def test_confirmacion(self) -> None:
        self.registros = [_registro("a")]
        vista = await self.t["ha_clear_system_log"]()
        r = await self.t["ha_clear_system_log"](confirmation_token=vista["confirmation_token"])
        self.assertEqual(r, {"result": "ok"})
        self.ha.call_service.assert_awaited_once_with(
            "system_log", "clear", {}, allow_dangerous=True)

    async def test_token_reutilizado_o_de_otra_tool(self) -> None:
        self.registros = [_registro("a")]
        vista = await self.t["ha_clear_system_log"]()
        await self.t["ha_clear_system_log"](confirmation_token=vista["confirmation_token"])
        r = await self.t["ha_clear_system_log"](confirmation_token=vista["confirmation_token"])
        self.assertIn("error", r)
        self.niveles = [{"domain": "mqtt", "level": 30}]
        otra = await self.t["ha_set_log_level"](level="DEBUG", integration="mqtt")
        r = await self.t["ha_clear_system_log"](confirmation_token=otra["confirmation_token"])
        self.assertIn("error", r)
        self.assertEqual(self.ha.call_service.await_count, 1)

    async def test_lectura_previa_fallida(self) -> None:
        self.fallos["system_log/list"] = HAConnectionError("caída")
        r = await self.t["ha_clear_system_log"]()
        self.assertEqual(r["error"], "preview_unavailable")
        self.assertNotIn("confirmation_token", r)

    async def test_lectura_previa_que_no_es_lista(self) -> None:
        self.registros = None
        r = await self.t["ha_clear_system_log"]()
        self.assertEqual(r["error"], "preview_unavailable")

    async def test_unknown_command_en_la_lectura_previa(self) -> None:
        self.fallos["system_log/list"] = HAConnectionError("Unknown command.", code="unknown_command")
        r = await self.t["ha_clear_system_log"]()
        self.assertEqual(r["error"], "system_log_unavailable")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.ficheros_de_tokens(), "")


class TestDenylistSinRegresion(unittest.TestCase):
    """FR-020: las tools dedicadas no relajan la denylist de `ha_call_service`.

    `logger.set_default_level` entra con la 012: bajar el nivel por defecto
    oculta rastros igual que `logger.set_level`. Control negativo comprobado:
    sin esa línea en `service_policy.py` cae `test_denylist_de_rastros`.
    """

    def test_denylist_de_rastros(self) -> None:
        for servicio in ("logger.set_level", "logger.set_default_level", "system_log.clear",
                         "persistent_notification.dismiss",
                         "persistent_notification.dismiss_all"):
            self.assertIn(servicio, CALL_SERVICE_DENYLIST)


class TestDenylistEnHaCallService(unittest.IsolatedAsyncioTestCase):
    """`ha_call_service` pide token para las acciones de nivel de log
    (FR-020 y extra del supervisor en el tramo A). Control negativo: sin
    `logger.set_default_level` en la denylist, la llamada se ejecuta a la
    primera y cae `test_set_default_level_pide_confirmacion`."""

    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    async def test_set_default_level_pide_confirmacion(self) -> None:
        from tests.test_call_service_security import _make_ha_client, _register_ha_tools

        for servicio in ("set_default_level", "set_level"):
            with self.subTest(servicio=servicio):
                ha = _make_ha_client()
                tools = _register_ha_tools(ha)
                r = await tools["ha_call_service"](
                    domain="logger", service=servicio,
                    service_data={"level": "critical"})
                self.assertIn("confirmation_token", r)
                ha.call_service.assert_not_called()
