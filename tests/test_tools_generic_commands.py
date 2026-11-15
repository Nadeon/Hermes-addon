"""Las cuatro tools genéricas (spec 011, T019–T021; FR-003, FR-004, FR-008,
FR-009, FR-011…FR-017, FR-025).

Con tablas inyectadas (lo que se prueba es cómo aplican la decisión) y con
entradas reales de la tabla (`tag/*`, `lovelace/config/save`…). El cliente de
HA es un doble con `AsyncMock`: lo que importa es qué se le pide y qué no.
Datos ficticios y centinelas de texto; nada de la instalación real.

Controles negativos (T028, recuentos en el commit del tramo 2):
- (a) sin la comprobación de categoría en la de lectura → caen los de
  `dedicated`/`deny`/`confirm`.
- (b) token atado solo a `type` → cae `test_token_de_otra_carga`.
- (c) valor visible bajo clave sensible → cae el centinela de la vista previa.
- (d) respuesta de HA en `cached_result` → cae `test_fichero_del_token_sin_respuesta`.
- (e) sin la guarda `self_target` → caen los de `{app}` propio.
- (f) `ws_send` para `one_shot` → cae `test_one_shot`.
- (g) `path` concreto en el log → cae `test_log_con_plantilla_y_sin_ruta`.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from structlog.testing import capture_logs

from hermes import security
from hermes.command_policy import Entrada
from hermes.ha import HAConnectionError
from hermes.tools import generic_commands as mod
from hermes.tools._common import recortar_a_bytes

_CENTINELA = "centinela-secreto-0xC0FFEE"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJh"


def _e(category: str, **kw: Any) -> Entrada:
    kw.setdefault("reason", f"motivo {category}")
    kw.setdefault("family", "generic_commands")
    if category == "dedicated":
        kw.setdefault("tool", "ha_get_demo")
    return Entrada(category=category, **kw)


_CORE = {
    "demo/list": _e("read", cap="CAP-066"),
    "demo/una_vez": _e("read", one_shot=True),
    "demo/create": _e("confirm", reason="Demo: create", cap="CAP-066",
                      redact_extra=("pin",)),
    "demo/update": _e("confirm", reason="Demo: update"),
    "demo/secreto": _e("deny", reason="devuelve una clave (clase D)"),
    "demo/dedicada": _e("dedicated", tool="ha_get_demo", family="lovelace"),
}

_SV = {
    ("GET", "/demo/info"): _e("read", redact_extra=("pin",)),
    ("GET", "/demo/logs"): _e("read", response="text"),
    ("GET", "/addons/{app}/info"): _e("read"),
    ("POST", "/addons/{app}/restart"): _e("confirm", reason="reinicia una app"),
    ("POST", "/demo/opciones"): _e("confirm", reason="cambia opciones", cap="CAP-088"),
    ("GET", "/demo/escribe"): _e("confirm", reason="GET que escribe"),
    ("GET", "/demo/denegada"): _e("deny", reason="no"),
    ("GET", "/demo/dedicada"): _e("dedicated", tool="sv_get_demo", family="supervisor"),
    # El proxy de Core se rechaza aunque la tabla dijera `read`.
    ("GET", "/core/api/states"): _e("read"),
}


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _cliente() -> MagicMock:
    c = MagicMock()
    c.wait_ready = AsyncMock(return_value=True)
    c.ws_send = AsyncMock(return_value={})
    c.ws_one_shot_subscription = AsyncMock(return_value={})
    c.sv_request = AsyncMock(return_value={})
    c.sv_request_text = AsyncMock(return_value="")
    return c


class _Base(unittest.IsolatedAsyncioTestCase):
    max_bytes = 131_072
    inyectadas = True

    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.ha = _cliente()
        self.mcp = DummyMCP()
        kw: dict[str, Any] = {}
        if self.inyectadas:
            kw = {"tabla_core": _CORE, "tabla_supervisor": _SV}
        mod.register(self.mcp, self.ha, response_max_bytes=self.max_bytes, **kw)
        self.t = self.mcp.tools

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    def ficheros_de_tokens(self) -> str:
        return "".join(
            p.read_text(encoding="utf-8")
            for p in Path(self.temp_dir.name).glob("*")
        )

    def eventos(self, logs: list[dict]) -> list[dict]:
        return [e for e in logs if e.get("event") == "generic_command"]


# ── ha_read_ws_command (T019) ────────────────────────────────────────────────

class TestLecturaCore(_Base):
    async def test_read_ejecuta_un_ws_send(self) -> None:
        self.ha.ws_send.return_value = {"a": 1}
        r = await self.t["ha_read_ws_command"]("demo/list", {"filtro": "x"})
        self.ha.ws_send.assert_awaited_once()
        self.assertEqual(self.ha.ws_send.await_args.args[0],
                         {"type": "demo/list", "filtro": "x"})
        self.assertEqual(r, {"command": "demo/list", "category": "read", "result": {"a": 1}})

    async def test_sin_payload(self) -> None:
        await self.t["ha_read_ws_command"]("demo/list")
        self.assertEqual(self.ha.ws_send.await_args.args[0], {"type": "demo/list"})

    async def test_resultado_lista(self) -> None:
        self.ha.ws_send.return_value = [{"id": "tag-ficticio-1"}, {"id": "tag-ficticio-2"}]
        r = await self.t["ha_read_ws_command"]("demo/list")
        self.assertEqual(r, {
            "command": "demo/list", "category": "read", "count": 2,
            "items": [{"id": "tag-ficticio-1"}, {"id": "tag-ficticio-2"}],
            "truncated": False,
        })

    async def test_rechazos_sin_llamar_a_ha(self) -> None:
        casos = {
            "demo/dedicada": "use_dedicated_tool",
            "demo/secreto": "command_denied",
            "demo/inexistente": "command_not_classified",
            "demo/create": "wrong_generic_tool",
        }
        for tipo, codigo in casos.items():
            with self.subTest(tipo=tipo):
                r = await self.t["ha_read_ws_command"](tipo, {})
                self.assertEqual(r["error"], codigo)
                self.assertIn("detail", r)
        self.ha.ws_send.assert_not_awaited()
        self.ha.ws_one_shot_subscription.assert_not_awaited()

    async def test_campos_de_los_rechazos(self) -> None:
        r = await self.t["ha_read_ws_command"]("demo/dedicada")
        self.assertEqual((r["tool"], r["family"], r["family_disabled"]),
                         ("ha_get_demo", "lovelace", False))
        r = await self.t["ha_read_ws_command"]("demo/secreto")
        self.assertEqual(r["reason"], "devuelve una clave (clase D)")
        r = await self.t["ha_read_ws_command"]("demo/create")
        self.assertEqual(r["use_tool"], "ha_call_ws_command")
        r = await self.t["ha_read_ws_command"]("demo/inexistente")
        self.assertIn("hermes_guide", r["hint"])

    async def test_type_invalido(self) -> None:
        malos = ("Tag/List", "tag list", "a" * 129, "", "tag//list", "/tag", "tag/",
                 "tag/list\n", "tagñ/list")
        for tipo in malos:
            with self.subTest(tipo=tipo), capture_logs() as logs:
                r = await self.t["ha_read_ws_command"](tipo)
                self.assertEqual(r["error"], "invalid_argument")
                self.assertEqual(r["field"], "type")
                if len(tipo) > 3:
                    self.assertNotIn(tipo, json.dumps(r))
                    self.assertNotIn(tipo, json.dumps(logs, default=str))
        self.ha.ws_send.assert_not_awaited()

    async def test_type_de_128_vale(self) -> None:
        r = await self.t["ha_read_ws_command"]("a" * 128)
        self.assertEqual(r["error"], "command_not_classified")

    async def test_type_no_texto(self) -> None:
        r = await self.t["ha_read_ws_command"](123)  # type: ignore[arg-type]
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "type"))

    async def test_payload_invalido(self) -> None:
        for payload in ("x", [1], 3, {"id": 1}, {"type": "otro/comando"}):
            with self.subTest(payload=payload):
                r = await self.t["ha_read_ws_command"]("demo/list", payload)
                self.assertEqual(r["error"], "invalid_argument")
                self.assertEqual(r["field"], "payload")
        self.ha.ws_send.assert_not_awaited()

    async def test_one_shot(self) -> None:
        self.ha.ws_one_shot_subscription.return_value = {"valor": 1}
        r = await self.t["ha_read_ws_command"]("demo/una_vez", {"x": 1})
        self.ha.ws_send.assert_not_awaited()
        self.ha.ws_one_shot_subscription.assert_awaited_once()
        llamada = self.ha.ws_one_shot_subscription.await_args
        self.assertEqual(llamada.args[0], {"type": "demo/una_vez", "x": 1})
        self.assertLessEqual(llamada.kwargs["event_timeout_seconds"], 10)
        self.assertEqual(r["result"], {"valor": 1})

    async def test_unknown_command(self) -> None:
        self.ha.ws_send.side_effect = HAConnectionError(
            "HA WS command failed: Unknown command.", code="unknown_command")
        r = await self.t["ha_read_ws_command"]("demo/list")
        self.assertEqual(r["error"], "ha_command_failed")
        self.assertEqual(r["ha_code"], "unknown_command")
        self.assertIn("2026.11.1", r["hint"])

    async def test_error_de_ha_que_repite_la_carga(self) -> None:
        self.ha.ws_send.side_effect = HAConnectionError(
            f"HA WS command failed: invalid value {_CENTINELA} for filtro",
            code="invalid_format")
        with capture_logs() as logs:
            r = await self.t["ha_read_ws_command"]("demo/list", {"filtro": _CENTINELA})
        self.assertEqual(r["error"], "ha_command_failed")
        self.assertEqual(r["ha_code"], "invalid_format")
        self.assertIn("***", r["detail"])
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertNotIn(_CENTINELA, json.dumps(logs, default=str))
        self.assertEqual(self.eventos(logs)[0]["outcome"], "failed")

    async def test_core_caido(self) -> None:
        self.ha.ws_send.side_effect = HAConnectionError(
            "WebSocket no disponible para envío de comandos.")
        r = await self.t["ha_read_ws_command"]("demo/list")
        self.assertIn("WebSocket no disponible", r["error"])

    async def test_respuesta_redactada(self) -> None:
        self.ha.ws_send.return_value = {
            "password": _CENTINELA, "nota": f"Bearer {_JWT}", "pin": "x",
            "lista": [{"api_key": _CENTINELA}],
        }
        r = await self.t["ha_read_ws_command"]("demo/list")
        texto = json.dumps(r)
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn(_JWT, texto)

    async def test_lista_enorme_recortada_por_el_tope_central(self) -> None:
        self.ha.ws_send.return_value = [{"id": f"tag-ficticio-{i}"} for i in range(5000)]
        r = await self.t["ha_read_ws_command"]("demo/list")
        recortada = recortar_a_bytes(r, 4096)
        self.assertTrue(recortada["truncated"])
        self.assertEqual(recortada["count"], len(recortada["items"]))
        self.assertLess(recortada["count"], 5000)

    async def test_log_sin_valores(self) -> None:
        with capture_logs() as logs:
            await self.t["ha_read_ws_command"]("demo/list", {"b": _CENTINELA, "a": 1})
        ev = self.eventos(logs)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["tool"], "ha_read_ws_command")
        self.assertEqual(ev[0]["command"], "demo/list")
        self.assertEqual(ev[0]["outcome"], "executed")
        self.assertEqual(ev[0]["payload_keys"], ["a", "b"])
        self.assertNotIn(_CENTINELA, json.dumps(logs, default=str))

    async def test_log_de_rechazo(self) -> None:
        with capture_logs() as logs:
            await self.t["ha_read_ws_command"]("demo/secreto")
        self.assertEqual(self.eventos(logs)[0]["outcome"], "rejected:command_denied")


class TestLecturaCoreTablaReal(_Base):
    inyectadas = False

    async def test_tag_list(self) -> None:
        self.ha.ws_send.return_value = [{"id": "tag-ficticio-1", "name": "Llavero"}]
        r = await self.t["ha_read_ws_command"]("tag/list")
        self.assertEqual(r["count"], 1)
        self.ha.ws_send.assert_awaited_once_with({"type": "tag/list"})

    async def test_action_calls_tapa_el_code(self) -> None:
        # T044: `logbook/get_action_calls` devuelve el `service_data` de cada
        # llamada; el `code` de un `alarm_disarm` o un `lock.unlock` sale
        # tapado, sea texto o número. Control negativo comprobado: sin
        # `redact_extra=("code",)` en la entrada de la tabla, este test cae
        # (el texto y el número salen en claro).
        self.ha.ws_send.return_value = [
            {"when": 1.0, "domain": "alarm_control_panel", "service": "alarm_disarm",
             "service_data": {"entity_id": "alarm_control_panel.casa",
                              "code": _CENTINELA}},
            {"when": 2.0, "domain": "lock", "service": "unlock",
             "service_data": {"entity_id": "lock.puerta", "code": 918273}},
        ]
        r = await self.t["ha_read_ws_command"](
            "logbook/get_action_calls", {"start_time": "2026-01-01T00:00:00Z"}
        )
        texto = json.dumps(r)
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn("918273", texto)
        datos = [i["service_data"] for i in r["items"]]
        self.assertEqual([d["code"] for d in datos], [security.REDACTED_MARKER] * 2)
        # Lo demás sigue a la vista: solo se tapa el código.
        self.assertEqual(datos[1]["entity_id"], "lock.puerta")

    async def test_action_calls_sin_code_en_el_log(self) -> None:
        # Spec 029, T026 (FR-012, SC-004): el `code` tapado tampoco llega al
        # log (la genérica registra solo las claves de la carga), y el resto
        # de la llamada sigue visible en la respuesta. El tapado en la
        # respuesta lo prueba ya `test_action_calls_tapa_el_code` (011).
        # Control negativo (T034 a): sin `redact_extra` en la entrada, cae
        # aquí la respuesta (centinela y número en claro).
        self.ha.ws_send.return_value = [
            {"when": 1.0, "domain": "alarm_control_panel", "service": "alarm_disarm",
             "service_data": {"entity_id": "alarm_control_panel.casa", "code": _CENTINELA}},
            {"when": 2.0, "domain": "lock", "service": "unlock",
             "service_data": {"entity_id": "lock.puerta", "code": 4321}},
        ]
        with capture_logs() as logs:
            r = await self.t["ha_read_ws_command"](
                "logbook/get_action_calls",
                {"start_time": "2026-01-01T00:00:00+00:00",
                 "end_time": "2026-01-01T06:00:00+00:00"})
        texto = json.dumps(r)
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn("4321", texto)
        self.assertEqual([i["service"] for i in r["items"]], ["alarm_disarm", "unlock"])
        self.assertEqual(r["items"][0]["service_data"]["entity_id"], "alarm_control_panel.casa")
        en_log = json.dumps(logs, default=str)
        self.assertNotIn(_CENTINELA, en_log)
        self.assertNotIn("4321", en_log)
        self.assertEqual(self.eventos(logs)[0]["payload_keys"], ["end_time", "start_time"])

    async def test_action_calls_tiene_ejemplo(self) -> None:
        # Spec 029, T027 (FR-012): el ejemplo de la tabla, revisado contra
        # `logbook/websocket_api.py` (`start_time` obligatorio, `end_time`
        # opcional, los dos como texto ISO).
        from hermes.command_table import CORE_WS

        e = CORE_WS["logbook/get_action_calls"]
        self.assertEqual((e.category, e.redact_extra), ("read", ("code",)))
        self.assertEqual(set(e.example), {"start_time", "end_time"})

    async def test_red_y_http_sin_urls_ni_ips_en_el_log(self) -> None:
        # Spec 029, T026 (FR-013, SC-006): `network`, `network/url` y
        # `http/config` siguen `read`; la respuesta trae URLs y direcciones
        # y el log de la genérica no lleva ninguna.
        # Control negativo (T034 b): registrar la respuesta en el log -> cae.
        url_ext = "https://homeassistant.tailXXXX.ts.net"
        url_int = "http://192.0.2.10:8123"
        respuestas = {
            "network": {"adapters": [{"name": "eth0", "enabled": True,
                                      "ipv4": [{"address": "192.0.2.10",
                                                "network_prefix": 24}]}],
                        "configured_adapters": [], "ipv4_address": "192.0.2.10"},
            "network/url": {"internal": url_int, "external": url_ext, "cloud": None},
            "http/config": {"stable": {"server_host": ["192.0.2.11"],
                                       "trusted_proxies": ["192.0.2.0/24"]},
                            "pending": None, "default": {"server_port": 8123}},
        }
        for comando, respuesta in respuestas.items():
            with self.subTest(comando=comando):
                self.ha.ws_send.reset_mock()
                self.ha.ws_send.return_value = respuesta
                with capture_logs() as logs:
                    r = await self.t["ha_read_ws_command"](comando)
                self.ha.ws_send.assert_awaited_once_with({"type": comando})
                self.assertNotIn("error", r)
                self.assertEqual(r["result"], respuesta)
                en_log = json.dumps(logs, default=str)
                for prohibido in ("192.0.2.", "tailXXXX", url_ext, url_int, "eth0"):
                    self.assertNotIn(prohibido, en_log)
                self.assertEqual(self.eventos(logs)[0]["outcome"], "executed")

    async def test_reales_rechazadas(self) -> None:
        casos = {
            "lovelace/config/save": "use_dedicated_tool",
            "backup/restore": "command_denied",
            "tag/create": "wrong_generic_tool",
            "comando/que/no/existe": "command_not_classified",
        }
        for tipo, codigo in casos.items():
            with self.subTest(tipo=tipo):
                self.assertEqual((await self.t["ha_read_ws_command"](tipo))["error"], codigo)
        r = await self.t["ha_read_ws_command"]("lovelace/config/save")
        self.assertEqual(r["tool"], "ha_save_lovelace_dashboard")
        self.ha.ws_send.assert_not_awaited()


# ── ha_call_ws_command (T020) ────────────────────────────────────────────────

class TestEscrituraCore(_Base):
    async def _vista(self, tipo: str = "demo/create", payload: Any = None) -> dict:
        payload = {"tag_id": "tag-ficticio-3", "name": "Llavero azul"} if payload is None else payload
        return await self.t["ha_call_ws_command"](tipo, payload)

    async def test_vista_previa(self) -> None:
        r = await self._vista(payload={
            "tag_id": "tag-ficticio-3", "name": "Llavero azul", "api_key": _CENTINELA})
        self.ha.ws_send.assert_not_awaited()
        self.assertIn("confirmation_token", r)
        self.assertEqual(r["expires_in_seconds"], 60)
        p = r["preview"]
        self.assertEqual(p["tool"], "ha_call_ws_command")
        self.assertEqual(p["command"], "demo/create")
        self.assertEqual(p["category"], "confirm")
        self.assertEqual(p["reason"], "Demo: create")
        self.assertEqual(p["cap"], "CAP-066")
        self.assertIn("does not interpret", p["note"])
        filas = {f["path"]: f for f in p["payload_summary"]["rows"]}
        self.assertEqual(filas["name"]["value"], "Llavero azul")
        self.assertEqual(filas["api_key"]["hidden"], "sensitive")
        self.assertNotIn(_CENTINELA, json.dumps(r))

    async def test_redact_extra_en_la_vista_previa(self) -> None:
        r = await self._vista(payload={"pin": "1234"})
        self.assertEqual(r["preview"]["payload_summary"]["rows"][0]["hidden"], "sensitive")

    async def test_confirmar_ejecuta_una_vez(self) -> None:
        payload = {"tag_id": "tag-ficticio-3", "name": "Llavero azul"}
        vista = await self._vista(payload=payload)
        self.ha.ws_send.return_value = {"id": "tag-ficticio-3"}
        r = await self.t["ha_call_ws_command"](
            "demo/create", payload, confirmation_token=vista["confirmation_token"])
        self.ha.ws_send.assert_awaited_once_with({"type": "demo/create", **payload})
        self.assertEqual(r, {"command": "demo/create", "category": "confirm",
                             "executed": True, "result": {"id": "tag-ficticio-3"}})

    async def test_confirmar_resultado_lista(self) -> None:
        vista = await self._vista(payload={})
        self.ha.ws_send.return_value = [1, 2]
        r = await self.t["ha_call_ws_command"](
            "demo/create", {}, confirmation_token=vista["confirmation_token"])
        self.assertEqual((r["executed"], r["count"], r["items"]), (True, 2, [1, 2]))

    async def test_token_de_otro_type(self) -> None:
        payload = {"name": "x"}
        vista = await self._vista(payload=payload)
        r = await self.t["ha_call_ws_command"](
            "demo/update", payload, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "invalid_confirmation_token")
        self.assertIn("does not match", r["detail"])
        self.ha.ws_send.assert_not_awaited()

    async def test_token_de_otra_carga(self) -> None:
        vista = await self._vista(payload={"a": {"b": [1, 2]}})
        r = await self.t["ha_call_ws_command"](
            "demo/create", {"a": {"b": [1, 3]}},
            confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "invalid_confirmation_token")
        self.assertIn("does not match", r["detail"])
        self.ha.ws_send.assert_not_awaited()

    async def test_token_reutilizado(self) -> None:
        vista = await self._vista(payload={})
        token = vista["confirmation_token"]
        await self.t["ha_call_ws_command"]("demo/create", {}, confirmation_token=token)
        r = await self.t["ha_call_ws_command"]("demo/create", {}, confirmation_token=token)
        self.assertEqual(r["error"], "invalid_confirmation_token")
        self.assertEqual(self.ha.ws_send.await_count, 1)

    async def test_vista_previa_demasiado_grande(self) -> None:
        carga = {f"clave_{i}": i for i in range(5000)}
        r = await self._vista(payload=carga)
        self.assertEqual(r["error"], "preview_too_large")
        self.assertEqual(r["keys"], 5000)
        self.assertEqual(r["payload_bytes"], len(json.dumps(carga).encode()))
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(list(Path(self.temp_dir.name).glob("*")), [])
        self.ha.ws_send.assert_not_awaited()

    async def test_read_por_la_de_escritura(self) -> None:
        r = await self.t["ha_call_ws_command"]("demo/list", {})
        self.assertEqual((r["error"], r["use_tool"]), ("wrong_generic_tool", "ha_read_ws_command"))
        self.assertEqual(list(Path(self.temp_dir.name).glob("*")), [])

    async def test_rechazos_antes_del_token(self) -> None:
        for tipo, codigo in (("demo/secreto", "command_denied"),
                             ("demo/dedicada", "use_dedicated_tool"),
                             ("demo/nada", "command_not_classified")):
            with self.subTest(tipo=tipo):
                r = await self.t["ha_call_ws_command"](tipo, {})
                self.assertEqual(r["error"], codigo)
        r = await self.t["ha_call_ws_command"]("demo/create", {"id": 3})
        self.assertEqual(r["error"], "invalid_argument")
        self.assertEqual(list(Path(self.temp_dir.name).glob("*")), [])
        self.ha.ws_send.assert_not_awaited()

    async def test_centinela_en_carga_y_respuesta(self) -> None:
        payload = {"name": "x", "password": _CENTINELA}
        self.ha.ws_send.return_value = {"password": _CENTINELA, "token": _CENTINELA}
        with capture_logs() as logs:
            vista = await self._vista(payload=payload)
            tras_vista = self.ficheros_de_tokens()
            r = await self.t["ha_call_ws_command"](
                "demo/create", payload, confirmation_token=vista["confirmation_token"])
        self.assertTrue(r["executed"])
        for nombre, texto in (("vista previa", json.dumps(vista)),
                              ("respuesta", json.dumps(r)),
                              ("log", json.dumps(logs, default=str)),
                              ("token tras la vista previa", tras_vista),
                              ("token tras confirmar", self.ficheros_de_tokens())):
            with self.subTest(donde=nombre):
                self.assertNotIn(_CENTINELA, texto)

    async def test_centinela_en_el_error_de_ha(self) -> None:
        payload = {"name": _CENTINELA}
        vista = await self._vista(payload=payload)
        self.ha.ws_send.side_effect = HAConnectionError(
            f"HA WS command failed: {_CENTINELA} already exists", code="invalid_info")
        with capture_logs() as logs:
            r = await self.t["ha_call_ws_command"](
                "demo/create", payload, confirmation_token=vista["confirmation_token"])
        self.assertEqual((r["error"], r["ha_code"]), ("ha_command_failed", "invalid_info"))
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertNotIn(_CENTINELA, json.dumps(logs, default=str))
        self.assertNotIn(_CENTINELA, self.ficheros_de_tokens())

    async def test_fichero_del_token_sin_respuesta(self) -> None:
        vista = await self._vista(payload={})
        token = vista["confirmation_token"]
        self.ha.ws_send.return_value = {"dato": "respuesta-de-ha-ficticia"}
        await self.t["ha_call_ws_command"]("demo/create", {}, confirmation_token=token)
        datos = json.loads((Path(self.temp_dir.name) / f"{token}.json").read_text(encoding="utf-8"))
        self.assertEqual(datos["cached_result"], {"executed": True})
        self.assertNotIn("stored_args", datos)
        self.assertNotIn("respuesta-de-ha-ficticia", self.ficheros_de_tokens())

    async def test_log_uno_por_llamada(self) -> None:
        payload = {"tag_id": "tag-ficticio-3", "api_key": _CENTINELA, "name": "x"}
        with capture_logs() as logs:
            vista = await self._vista(payload=payload)
            await self.t["ha_call_ws_command"](
                "demo/create", payload, confirmation_token=vista["confirmation_token"])
        ev = self.eventos(logs)
        self.assertEqual([e["outcome"] for e in ev], ["preview", "executed"])
        for e in ev:
            self.assertEqual(e["tool"], "ha_call_ws_command")
            self.assertEqual(e["command"], "demo/create")
            self.assertEqual(e["category"], "confirm")
            self.assertEqual(e["payload_keys"], ["api_key", "name", "tag_id"])
            self.assertEqual(e["payload_bytes"], len(json.dumps(payload).encode()))


class TestEscrituraCoreTablaReal(_Base):
    inyectadas = False

    async def test_tag_create_en_dos_pasos(self) -> None:
        payload = {"tag_id": "tag-ficticio-3", "name": "Llavero azul"}
        vista = await self.t["ha_call_ws_command"]("tag/create", payload)
        self.assertEqual(vista["preview"]["cap"], "CAP-066")
        self.ha.ws_send.assert_not_awaited()
        r = await self.t["ha_call_ws_command"](
            "tag/create", payload, confirmation_token=vista["confirmation_token"])
        self.assertTrue(r["executed"])
        self.ha.ws_send.assert_awaited_once_with({"type": "tag/create", **payload})


class TestMenoresDeCoreDeLa024(_Base):
    """Spec 024, tramo 1 (T009 y T012; FR-005, FR-009, FR-010), con la tabla
    real: preferencias de cámara, miniaturas tapadas en la navegación de
    medios, calendario y tareas en dos pasos, y lo denegado.

    Controles negativos (T013): (e) sin `redact_extra=("thumbnail",)` en
    `media_source/browse_media` → cae `test_browse_media_tapa_la_miniatura`;
    (f) `camera/update_prefs` de vuelta a `deny` → caen
    `test_update_prefs_en_dos_pasos` y `test_update_prefs_no_es_lectura`.
    """

    inyectadas = False

    async def test_get_prefs_lee(self) -> None:
        self.ha.ws_send.return_value = {"preload_stream": False, "orientation": 1}
        r = await self.t["ha_read_ws_command"]("camera/get_prefs", {"entity_id": "camera.entrada"})
        self.assertEqual(r["result"], {"preload_stream": False, "orientation": 1})
        self.ha.ws_send.assert_awaited_once_with(
            {"type": "camera/get_prefs", "entity_id": "camera.entrada"})

    async def test_update_prefs_en_dos_pasos(self) -> None:
        carga = {"entity_id": "camera.entrada", "preload_stream": True}
        vista = await self.t["ha_call_ws_command"]("camera/update_prefs", carga)
        self.assertIn("confirmation_token", vista)
        self.assertEqual((vista["preview"]["category"], vista["preview"]["cap"]),
                         ("confirm", "CAP-059"))
        self.assertIn("internet", vista["preview"]["reason"])
        self.ha.ws_send.assert_not_awaited()
        self.ha.ws_send.return_value = {"preload_stream": True, "orientation": 1}
        r = await self.t["ha_call_ws_command"](
            "camera/update_prefs", carga, confirmation_token=vista["confirmation_token"])
        self.assertTrue(r["executed"])
        self.ha.ws_send.assert_awaited_once_with({"type": "camera/update_prefs", **carga})

    async def test_update_prefs_no_es_lectura(self) -> None:
        r = await self.t["ha_read_ws_command"](
            "camera/update_prefs", {"entity_id": "camera.entrada", "preload_stream": True})
        self.assertEqual((r["error"], r["use_tool"]), ("wrong_generic_tool", "ha_call_ws_command"))
        self.ha.ws_send.assert_not_awaited()

    async def test_browse_media_tapa_la_miniatura(self) -> None:
        # Research R-6: la fuente de motionEye firma la miniatura de cada
        # vídeo con `async_sign_path` (authSig, 5 min). En dos niveles.
        firmada = f"/api/motioneye/media/x/y.mp4?authSig={_CENTINELA}"
        self.ha.ws_send.return_value = {
            "title": "motionEye", "media_content_id": "media-source://motioneye",
            "thumbnail": firmada, "can_expand": True,
            "children": [{
                "title": "Cámara", "media_content_id": "media-source://motioneye/x",
                "thumbnail": firmada,
                "children": [{"title": "vídeo", "thumbnail": firmada,
                              "media_content_id": "media-source://motioneye/x/y"}],
            }],
        }
        for comando, carga in (
            ("media_source/browse_media", {"media_content_id": "media-source://motioneye"}),
            ("media_source/search_media", {"search_query": "vídeo"}),
        ):
            with self.subTest(comando=comando):
                r = await self.t["ha_read_ws_command"](comando, carga)
                texto = json.dumps(r, ensure_ascii=False)
                self.assertNotIn(_CENTINELA, texto)
                self.assertNotIn("authSig", texto)
                # Lo demás se sigue viendo: navegar sigue siendo útil.
                self.assertIn("media-source://motioneye/x/y", texto)
                self.assertEqual(r["result"]["thumbnail"], security.REDACTED_MARKER)

    async def test_calendario_y_tareas_en_dos_pasos_de_mundo_abierto(self) -> None:
        from hermes.command_table import CORE_WS

        for comando, carga in (
            ("calendar/event/delete", {"entity_id": "calendar.casa", "uid": "evento-ficticio"}),
            ("todo/item/move", {"entity_id": "todo.compra", "uid": "tarea-ficticia"}),
        ):
            with self.subTest(comando=comando):
                self.assertTrue(CORE_WS[comando].open_world)
                vista = await self.t["ha_call_ws_command"](comando, carga)
                self.assertIn("confirmation_token", vista)
                self.assertIn("internet", vista["preview"]["reason"])
                self.assertEqual(vista["preview"]["cap"], CORE_WS[comando].cap)
        self.ha.ws_send.assert_not_awaited()

    async def test_lo_denegado(self) -> None:
        for comando, palabra in (("image/create", "multipart"),
                                 ("media_source/resolve_media", "authSig")):
            for tool in ("ha_read_ws_command", "ha_call_ws_command"):
                with self.subTest(comando=comando, tool=tool):
                    r = await self.t[tool](comando, {"media_content_id": "media-source://x"})
                    self.assertEqual(r["error"], "command_denied")
                    self.assertIn(palabra, json.dumps(r, ensure_ascii=False))
        self.ha.ws_send.assert_not_awaited()


class TestMenoresDeCoreDeLa024Tramo2(_Base):
    """Spec 024, tramo 2 (T017; FR-008, FR-011, FR-012, FR-014), con la tabla
    real y respuestas con la forma REAL de Core 2026.11.1:

    - `webhook/list` (`components/webhook/__init__.py`, `websocket_list`):
      lista de `{webhook_id, domain, name, local_only, allowed_methods}`.
    - `application_credentials/list`: la colección guarda `id`, `domain`,
      `client_id`, `client_secret`, `auth_domain` y `name`.
    - `application_credentials/config_entry` (`handle_config_entry`):
      `{"application_credentials_id": …}` o `{}`.

    Controles negativos (T029): (f) sacar `webhook_id` de los marcadores de
    `security._SENSITIVE_KEY_MARKERS` → cae `test_webhook_list_tapa_el_id`
    (restaurado enseguida); (e) dejar `lovelace/config/delete` en `deny` →
    caen `test_restablecer_va_a_la_tool_dedicada` y
    `test_restablecer_con_la_familia_desactivada`.
    """

    inyectadas = False
    _CENTINELA_024 = "centinela-024"

    async def test_webhook_list_tapa_el_id(self) -> None:
        # Un `webhook_id` basta para disparar la automatización sin
        # autenticación: con la forma real de la respuesta de Core.
        self.ha.ws_send.return_value = [
            {"webhook_id": self._CENTINELA_024, "domain": "automation",
             "name": "Automatización del garaje", "local_only": True,
             "allowed_methods": ["POST", "PUT"]},
            {"webhook_id": f"otro-{self._CENTINELA_024}", "domain": "mobile_app",
             "name": "Mobile App: teléfono", "local_only": False,
             "allowed_methods": ["POST"]},
        ]
        r = await self.t["ha_read_ws_command"]("webhook/list")
        texto = json.dumps(r, ensure_ascii=False)
        self.assertNotIn(self._CENTINELA_024, texto)
        primero = r["items"][0]
        self.assertEqual(primero["webhook_id"], security.REDACTED_MARKER)
        self.assertEqual(
            (primero["domain"], primero["name"], primero["local_only"],
             primero["allowed_methods"]),
            ("automation", "Automatización del garaje", True, ["POST", "PUT"]))
        self.ha.ws_send.assert_awaited_once_with({"type": "webhook/list"})

    async def test_credenciales_de_aplicacion_sin_secretos(self) -> None:
        self.ha.ws_send.return_value = [
            {"id": "spotify_cliente", "domain": "spotify", "client_id": "cliente-publico",
             "client_secret": self._CENTINELA_024, "auth_domain": "spotify",
             "name": "Spotify"},
        ]
        r = await self.t["ha_read_ws_command"]("application_credentials/list")
        self.assertNotIn(self._CENTINELA_024, json.dumps(r))
        self.assertEqual(r["items"][0]["client_id"], "cliente-publico")

        self.ha.ws_send.return_value = {"application_credentials_id": self._CENTINELA_024}
        r = await self.t["ha_read_ws_command"](
            "application_credentials/config_entry", {"config_entry_id": "01ABC"})
        self.assertNotIn(self._CENTINELA_024, json.dumps(r))
        self.assertEqual(r["result"], {"application_credentials_id": security.REDACTED_MARKER})
        # Y el motivo de la entrada lo dice (H2 de la revisión de la spec).
        from hermes.command_table import CORE_WS

        self.assertIn("el id sale tapado",
                      CORE_WS["application_credentials/config_entry"].reason)

    async def test_segmentos_de_mundo_abierto(self) -> None:
        from hermes.command_table import CORE_WS

        e = CORE_WS["vacuum/get_segments"]
        self.assertEqual((e.category, e.open_world), ("read", True))
        self.ha.ws_send.return_value = {"segments": [
            {"id": "cocina", "name": "Cocina", "group": None}]}
        r = await self.t["ha_read_ws_command"](
            "vacuum/get_segments", {"entity_id": "vacuum.banco"})
        self.assertEqual(r["result"]["segments"][0]["id"], "cocina")

    async def test_lecturas_de_cap_071(self) -> None:
        for comando in ("trace/contexts", "frontend/get_themes", "radio_frequency/list"):
            with self.subTest(comando=comando):
                self.ha.ws_send.reset_mock()
                self.ha.ws_send.return_value = {}
                r = await self.t["ha_read_ws_command"](comando)
                self.assertEqual((r["command"], r["category"]), (comando, "read"))
                self.ha.ws_send.assert_awaited_once_with({"type": comando})

    async def test_restablecer_va_a_la_tool_dedicada(self) -> None:
        for tool in ("ha_call_ws_command", "ha_read_ws_command"):
            with self.subTest(tool=tool):
                r = await self.t[tool]("lovelace/config/delete", {})
                self.assertEqual(
                    (r["error"], r["tool"], r["family"], r["family_disabled"]),
                    ("use_dedicated_tool", "ha_reset_lovelace_dashboard_config",
                     "dashboard_reset", False))
                self.assertNotIn("confirmation_token", r)
        self.ha.ws_send.assert_not_awaited()

    async def test_restablecer_con_la_familia_desactivada(self) -> None:
        mcp = DummyMCP()
        mod.register(mcp, self.ha, response_max_bytes=self.max_bytes,
                     familias_desactivadas=frozenset({"dashboard_reset"}))
        r = await mcp.tools["ha_call_ws_command"]("lovelace/config/delete", {})
        self.assertEqual((r["error"], r["family_disabled"]), ("use_dedicated_tool", True))
        self.assertIn("family_disabled", json.dumps(r))
        self.ha.ws_send.assert_not_awaited()

    async def test_orden_de_areas_en_dos_pasos(self) -> None:
        carga = {"area_ids": ["cocina", "salon"]}
        vista = await self.t["ha_call_ws_command"]("config/area_registry/reorder", carga)
        self.assertIn("confirmation_token", vista)
        self.assertEqual((vista["preview"]["category"], vista["preview"]["cap"]),
                         ("confirm", "CAP-070"))
        self.ha.ws_send.assert_not_awaited()
        self.ha.ws_send.return_value = None
        r = await self.t["ha_call_ws_command"](
            "config/area_registry/reorder", carga,
            confirmation_token=vista["confirmation_token"])
        self.assertTrue(r["executed"])
        self.ha.ws_send.assert_awaited_once_with(
            {"type": "config/area_registry/reorder", **carga})


# ── Supervisor (T021) ────────────────────────────────────────────────────────

_RUTAS_MALAS = (
    "addons/x/info", "", "//addons/x", "/addons//x", "/addons/x/", "/",
    "/addons\\x", "/addons/../host/reboot", "/addons/./x", "/addons/%2e%2e/host",
    "/addons/%2E%2E/host", "/addons/x%20y", "/addons/x?a=1", "/addons/x#f",
    "/addons/x\r\nHost: y", "/addons/x\x00", "http://x/addons", "https://x/core/api",
    "/core/api", "/core/api/states", "/homeassistant/api/x",
)


class TestSupervisor(_Base):
    async def test_read(self) -> None:
        self.ha.sv_request.return_value = {"version": "1"}
        r = await self.t["sv_read_api"]("/demo/info")
        self.ha.sv_request.assert_awaited_once_with("GET", "/demo/info")
        self.assertEqual(r, {"method": "GET", "path": "/demo/info", "route": "/demo/info",
                             "category": "read", "result": {"version": "1"}})

    async def test_read_con_parametro(self) -> None:
        r = await self.t["sv_read_api"]("/addons/core_mosquitto/info")
        self.ha.sv_request.assert_awaited_once_with("GET", "/addons/core_mosquitto/info")
        self.assertEqual(r["route"], "/addons/{app}/info")

    async def test_ruta_de_texto(self) -> None:
        self.ha.sv_request_text.return_value = (
            f"linea 1\nauth token={_CENTINELA}\nconexión de 192.0.2.7\n{_JWT}\n")
        with patch.object(mod, "redact_network",
                          side_effect=lambda t: t.replace("192.0.2.7", "<ip>")):
            r = await self.t["sv_read_api"]("/demo/logs")
        self.ha.sv_request_text.assert_awaited_once_with("/demo/logs")
        self.ha.sv_request.assert_not_awaited()
        self.assertEqual(r["count"], 4)
        self.assertEqual(r["route"], "/demo/logs")
        self.assertFalse(r["truncated"])
        texto = json.dumps(r)
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn(_JWT, texto)
        self.assertNotIn("192.0.2.7", texto)
        self.assertIn("<ip>", texto)

    async def test_ruta_de_texto_ultimas_lineas(self) -> None:
        self.ha.sv_request_text.return_value = "\n".join(
            f"linea {i:05d} " + "x" * 40 for i in range(4000))
        r = await self.t["sv_read_api"]("/demo/logs")
        self.assertTrue(r["truncated"])
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False).encode()), self.max_bytes)
        self.assertTrue(r["lines"][-1].startswith("linea 03999"))
        self.assertEqual(r["count"], len(r["lines"]))
        self.assertLess(r["count"], 4000)

    async def test_rutas_invalidas(self) -> None:
        for path in _RUTAS_MALAS:
            with self.subTest(path=path):
                for tool, args in (("sv_read_api", (path,)),
                                   ("sv_call_api", ("POST", path, {}))):
                    with capture_logs() as logs:
                        r = await self.t[tool](*args)
                    self.assertEqual(r["error"], "path_not_allowed")
                    self.assertIn(r["rule"], ("shape", "core_proxy"))
                    if len(path) > 3:
                        self.assertNotIn(path, json.dumps(logs, default=str))
        self.ha.sv_request.assert_not_awaited()
        self.ha.sv_request_text.assert_not_awaited()

    async def test_proxy_de_core_aunque_la_tabla_lo_permita(self) -> None:
        r = await self.t["sv_read_api"]("/core/api/states")
        self.assertEqual((r["error"], r["rule"]), ("path_not_allowed", "core_proxy"))

    async def test_app_propia(self) -> None:
        for app in ("self", "hermes", "algo_hermes", "SELF"):
            with self.subTest(app=app):
                r = await self.t["sv_read_api"](f"/addons/{app}/info")
                self.assertEqual((r["error"], r["rule"]), ("path_not_allowed", "self_target"))
                r = await self.t["sv_call_api"]("POST", f"/addons/{app}/restart")
                self.assertEqual((r["error"], r["rule"]), ("path_not_allowed", "self_target"))
        self.ha.sv_request.assert_not_awaited()
        self.assertEqual(list(Path(self.temp_dir.name).glob("*")), [])

    async def test_rechazos(self) -> None:
        casos = {
            "/demo/denegada": "command_denied",
            "/demo/dedicada": "use_dedicated_tool",
            "/demo/escribe": "wrong_generic_tool",
            "/demo/nada": "command_not_classified",
        }
        for path, codigo in casos.items():
            with self.subTest(path=path):
                self.assertEqual((await self.t["sv_read_api"](path))["error"], codigo)
        r = await self.t["sv_read_api"]("/demo/escribe")
        self.assertEqual(r["use_tool"], "sv_call_api")
        r = await self.t["sv_call_api"]("GET", "/demo/info")
        self.assertEqual((r["error"], r["use_tool"]), ("wrong_generic_tool", "sv_read_api"))
        self.ha.sv_request.assert_not_awaited()

    async def test_metodo_y_cuerpo_invalidos(self) -> None:
        for metodo in ("FETCH", "", 3, "GE T"):
            with self.subTest(metodo=metodo):
                r = await self.t["sv_call_api"](metodo, "/demo/opciones")
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "method"))
        for cuerpo in ("x", [1], 3):
            with self.subTest(cuerpo=cuerpo):
                r = await self.t["sv_call_api"]("POST", "/demo/opciones", cuerpo)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "body"))
        self.ha.sv_request.assert_not_awaited()

    async def test_call_vista_previa_y_confirmacion(self) -> None:
        cuerpo = {"debug": True, "password": _CENTINELA}
        vista = await self.t["sv_call_api"]("post", "/addons/core_mosquitto/restart", cuerpo)
        self.ha.sv_request.assert_not_awaited()
        p = vista["preview"]
        self.assertEqual((p["tool"], p["method"], p["path"], p["route"], p["category"]),
                         ("sv_call_api", "POST", "/addons/core_mosquitto/restart",
                          "/addons/{app}/restart", "confirm"))
        self.assertEqual(p["reason"], "reinicia una app")
        self.assertIn("body_summary", p)
        self.assertIn("note", p)
        self.assertNotIn(_CENTINELA, json.dumps(vista))
        self.ha.sv_request.return_value = {"ok": True, "password": _CENTINELA}
        r = await self.t["sv_call_api"](
            "POST", "/addons/core_mosquitto/restart", cuerpo,
            confirmation_token=vista["confirmation_token"])
        self.ha.sv_request.assert_awaited_once_with(
            "POST", "/addons/core_mosquitto/restart", json_body=cuerpo)
        self.assertTrue(r["executed"])
        self.assertEqual(r["route"], "/addons/{app}/restart")
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertNotIn(_CENTINELA, self.ficheros_de_tokens())
        token = json.loads(
            (Path(self.temp_dir.name) / f"{vista['confirmation_token']}.json").read_text(
                encoding="utf-8"))
        self.assertEqual(token["cached_result"], {"executed": True})

    async def test_token_atado_a_metodo_ruta_y_cuerpo(self) -> None:
        cuerpo = {"a": 1}
        vista = await self.t["sv_call_api"]("POST", "/addons/core_a/restart", cuerpo)
        token = vista["confirmation_token"]
        for metodo, path, c in (("GET", "/demo/escribe", cuerpo),
                                ("POST", "/addons/core_b/restart", cuerpo),
                                ("POST", "/addons/core_a/restart", {"a": 2}),
                                ("POST", "/addons/core_a/restart", None)):
            with self.subTest(metodo=metodo, path=path, c=c):
                r = await self.t["sv_call_api"](metodo, path, c, confirmation_token=token)
                self.assertEqual(r["error"], "invalid_confirmation_token")
        self.ha.sv_request.assert_not_awaited()

    async def test_error_del_supervisor(self) -> None:
        cuerpo = {"nombre": _CENTINELA}
        vista = await self.t["sv_call_api"]("POST", "/demo/opciones", cuerpo)
        self.ha.sv_request.side_effect = HAConnectionError(
            f"Supervisor REST POST /demo/opciones failed 400: {_CENTINELA} invalid, "
            f"token={_JWT}", status=400)
        with capture_logs() as logs:
            r = await self.t["sv_call_api"](
                "POST", "/demo/opciones", cuerpo,
                confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "supervisor_request_failed")
        self.assertEqual(r["status"], 400)
        for texto in (json.dumps(r), json.dumps(logs, default=str), self.ficheros_de_tokens()):
            self.assertNotIn(_CENTINELA, texto)
            self.assertNotIn(_JWT, texto)

    async def test_error_del_supervisor_en_lectura(self) -> None:
        self.ha.sv_request.side_effect = HAConnectionError(
            "Supervisor REST GET /demo/info failed 404: not found", status=404)
        r = await self.t["sv_read_api"]("/demo/info")
        self.assertEqual((r["error"], r["status"]), ("supervisor_request_failed", 404))

    async def test_respuesta_redactada(self) -> None:
        self.ha.sv_request.return_value = {"opciones": {"password": _CENTINELA, "pin": "1"},
                                           "nota": f"Bearer {_JWT}"}
        r = await self.t["sv_read_api"]("/demo/info")
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertNotIn(_JWT, json.dumps(r))
        self.assertNotEqual(r["result"]["opciones"]["pin"], "1")

    async def test_log_con_plantilla_y_sin_ruta(self) -> None:
        with capture_logs() as logs:
            await self.t["sv_read_api"]("/addons/core_concreta_ficticia/info")
            vista = await self.t["sv_call_api"](
                "POST", "/addons/core_concreta_ficticia/restart", {"b": _CENTINELA, "a": 1})
            await self.t["sv_call_api"](
                "POST", "/addons/core_concreta_ficticia/restart", {"b": _CENTINELA, "a": 1},
                confirmation_token=vista["confirmation_token"])
        ev = self.eventos(logs)
        self.assertEqual([e["outcome"] for e in ev], ["executed", "preview", "executed"])
        self.assertEqual(ev[0]["route"], "/addons/{app}/info")
        self.assertEqual(ev[0]["method"], "GET")
        self.assertEqual(ev[1]["route"], "/addons/{app}/restart")
        self.assertEqual(ev[1]["payload_keys"], ["a", "b"])
        texto = json.dumps(logs, default=str)
        self.assertNotIn("core_concreta_ficticia", texto)
        self.assertNotIn(_CENTINELA, texto)


class TestSupervisorTablaReal(_Base):
    inyectadas = False

    async def test_supervisor_info_por_la_tabla(self) -> None:
        self.ha.sv_request.return_value = {"version": "2026.11.0"}
        r = await self.t["sv_read_api"]("/supervisor/info")
        self.assertEqual(r["category"], "read")
        self.ha.sv_request.assert_awaited_once_with("GET", "/supervisor/info")

    async def test_dedicada_real(self) -> None:
        r = await self.t["sv_read_api"]("/host/info")
        self.assertEqual((r["error"], r["tool"]), ("use_dedicated_tool", "sv_get_host_info"))

    async def test_proxy_real(self) -> None:
        r = await self.t["sv_read_api"]("/core/api/config")
        self.assertEqual(r["rule"], "core_proxy")

    async def test_montajes_por_su_tool(self) -> None:
        """Spec 019 (FR-015): las rutas de montajes llevan a su tool
        dedicada sin llamar al Supervisor; tampoco para un montaje `disk`,
        que crea `sv_create_mount`."""
        r = await self.t["sv_read_api"]("/mounts")
        self.assertEqual((r["error"], r["tool"]), ("use_dedicated_tool", "sv_list_mounts"))
        r = await self.t["sv_call_api"](
            "POST", "/mounts", {"name": "usb", "type": "disk", "usage": "share",
                                "device": "/dev/sdb1"})
        self.assertEqual((r["error"], r["tool"]), ("use_dedicated_tool", "sv_create_mount"))
        self.assertNotIn("confirmation_token", r)
        r = await self.t["sv_call_api"]("POST", "/mounts/options",
                                        {"default_backup_mount": None})
        self.assertEqual(r["tool"], "sv_set_default_backup_mount")
        self.ha.sv_request.assert_not_awaited()

    async def test_ajustes_de_backup_por_su_tool(self) -> None:
        """Spec 019, tramo 2 (FR-015): las rutas de ajustes de backup
        llevan a su tool dedicada sin llamar al Supervisor."""
        r = await self.t["sv_read_api"]("/backups/info")
        self.assertEqual((r["error"], r["tool"]),
                         ("use_dedicated_tool", "sv_get_backup_settings"))
        r = await self.t["sv_call_api"]("POST", "/backups/options",
                                        {"days_until_stale": 7})
        self.assertEqual((r["error"], r["tool"]),
                         ("use_dedicated_tool", "sv_set_backup_settings"))
        self.assertNotIn("confirmation_token", r)
        r = await self.t["sv_call_api"]("POST", "/backups/reload", None)
        self.assertEqual(r["tool"], "sv_reload_backups")
        self.ha.sv_request.assert_not_awaited()


# ── Registro ──────────────────────────────────────────────────────────────────

# ── Con familias desactivadas (T033; FR-003, FR-004, US5 escenario 2) ────────

class TestFamiliasDesactivadasInyectadas(_Base):
    """La genérica no es una vía para usar lo que el usuario apagó."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.mcp = DummyMCP()
        core = {
            "demo/dedicada": _e("dedicated", tool="ha_get_demo", family="lovelace"),
            "demo/leer": _e("read", family="data"),
            "demo/cambiar": _e("confirm", family="data"),
        }
        sv = {("GET", "/demo/leer"): _e("read", family="data")}
        mod.register(self.mcp, self.ha, response_max_bytes=self.max_bytes,
                     familias_desactivadas=frozenset({"lovelace", "data"}),
                     tabla_core=core, tabla_supervisor=sv)
        self.t = self.mcp.tools

    async def test_dedicada_de_familia_desactivada(self) -> None:
        r = await self.t["ha_read_ws_command"]("demo/dedicada")
        self.assertEqual((r["error"], r["tool"], r["family"], r["family_disabled"]),
                         ("use_dedicated_tool", "ha_get_demo", "lovelace", True))
        self.ha.ws_send.assert_not_awaited()

    async def test_read_y_confirm_de_familia_desactivada(self) -> None:
        r = await self.t["ha_read_ws_command"]("demo/leer")
        self.assertEqual((r["error"], r["family"]), ("family_disabled", "data"))
        r = await self.t["ha_call_ws_command"]("demo/cambiar", {"a": 1})
        self.assertEqual((r["error"], r["family"]), ("family_disabled", "data"))
        self.assertNotIn("confirmation_token", r)
        r = await self.t["sv_read_api"]("/demo/leer")
        self.assertEqual((r["error"], r["family"]), ("family_disabled", "data"))
        self.ha.ws_send.assert_not_awaited()
        self.ha.sv_request.assert_not_awaited()


class TestDedicadasDeLa016(_Base):
    """Spec 016 (T010, FR-018): con la tabla real, los tres comandos del tramo
    A van a su tool dedicada; nada llega a HA ni se emite token.

    Control negativo (T016 g): dejar `config_entries/update` en `deny` →
    cae `test_update_hacia_la_dedicada` (`command_denied`)."""

    inyectadas = False

    async def test_progreso_hacia_la_dedicada(self) -> None:
        r = await self.t["ha_read_ws_command"]("config_entries/flow/progress")
        self.assertEqual((r["error"], r["tool"], r["family"], r["family_disabled"]),
                         ("use_dedicated_tool", "ha_list_discovered_integrations",
                          "integration_flows", False))
        self.ha.ws_send.assert_not_awaited()

    async def test_update_hacia_la_dedicada(self) -> None:
        r = await self.t["ha_call_ws_command"](
            "config_entries/update", {"entry_id": "entrada-1", "pref_disable_polling": True})
        self.assertEqual((r["error"], r["tool"]), ("use_dedicated_tool", "ha_update_config_entry"))
        self.assertNotIn("confirmation_token", r)
        self.ha.ws_send.assert_not_awaited()

    async def test_ignorar_hacia_la_dedicada(self) -> None:
        r = await self.t["ha_call_ws_command"](
            "config_entries/ignore_flow", {"flow_id": "flow-1", "title": "x"})
        self.assertEqual((r["error"], r["tool"]), ("use_dedicated_tool", "ha_ignore_discovery"))
        self.ha.ws_send.assert_not_awaited()

    async def test_subentries_hacia_sus_dedicadas(self) -> None:
        # Tramo B (T025): las tres de subentries; borrar no emite token aquí.
        for tipo, tool in (("config_entries/subentries/delete", "ha_delete_subentry"),
                           ("config_entries/subentries/update", "ha_update_subentry")):
            r = await self.t["ha_call_ws_command"](
                tipo, {"entry_id": "entrada-1", "subentry_id": "sub-1"})
            self.assertEqual((r["error"], r["tool"], r["family"]),
                             ("use_dedicated_tool", tool, "integration_flows"))
            self.assertNotIn("confirmation_token", r)
        r = await self.t["ha_read_ws_command"](
            "config_entries/subentries/list", {"entry_id": "entrada-1"})
        self.assertEqual((r["error"], r["tool"]), ("use_dedicated_tool", "ha_list_config_subentries"))
        self.ha.ws_send.assert_not_awaited()

    async def test_datos_internos_de_un_aviso_hacia_ha_get_repair(self) -> None:
        # Tramo C (T040): los datos internos solo salen redactados y
        # recortados por la dedicada. Control negativo: dejarlo en `deny` →
        # este test en rojo (T044 g).
        r = await self.t["ha_read_ws_command"](
            "repairs/get_issue_data", {"domain": "banco_flujos", "issue_id": "aviso"})
        self.assertEqual((r["error"], r["tool"], r["family"]),
                         ("use_dedicated_tool", "ha_get_repair", "repair_flows"))
        self.ha.ws_send.assert_not_awaited()

    async def test_con_la_familia_desactivada(self) -> None:
        mcp = DummyMCP()
        mod.register(mcp, self.ha, response_max_bytes=self.max_bytes,
                     familias_desactivadas=frozenset({"integration_flows"}))
        r = await mcp.tools["ha_read_ws_command"]("config_entries/flow/progress")
        self.assertEqual((r["error"], r["tool"], r["family_disabled"]),
                         ("use_dedicated_tool", "ha_list_discovered_integrations", True))
        self.ha.ws_send.assert_not_awaited()


def _registrar_todo(desactivadas: list[str]) -> tuple[DummyMCP, MagicMock]:
    """`register_all_tools` de verdad con un cliente simulado."""
    from hermes.tools import register_all_tools

    mcp = DummyMCP()
    ha = _cliente()
    register_all_tools(
        mcp, ha, fire_event_allowlist=[], response_max_bytes=131_072,
        safety_backup_window_minutes=30, safety_backup_enabled=False,
        file_backup_max_per_path=20, file_backup_max_total_mb=200,
        config_write_min_interval_seconds=5, config_write_max_per_minute=10,
        call_service_denylist_extra=[], call_service_restricted_entities=[],
        call_service_auto_classify=False, wait_for_event_max_seconds=90,
        wait_for_event_max_concurrent=5, safety_backup_keep=3,
        tool_families_disabled=desactivadas,
    )
    return mcp, ha


class TestFamiliasDesdeElRegistro(unittest.IsolatedAsyncioTestCase):
    """Cableado: `register_all_tools` pasa las familias desactivadas a las
    genéricas.

    Control negativo (T042 c): no pasárselas → cae
    `test_dedicada_de_familia_desactivada_por_la_opcion`
    (`family_disabled` sale False).
    """

    async def test_dedicada_de_familia_desactivada_por_la_opcion(self) -> None:
        mcp, ha = _registrar_todo(["lovelace"])
        self.assertNotIn("ha_save_lovelace_dashboard", mcp.tools)
        r = await mcp.tools["ha_call_ws_command"]("lovelace/config/save", {"config": {}})
        self.assertEqual(r["error"], "use_dedicated_tool")
        self.assertEqual((r["tool"], r["family"], r["family_disabled"]),
                         ("ha_save_lovelace_dashboard", "lovelace", True))
        ha.ws_send.assert_not_awaited()

    async def test_montajes_con_su_familia_apagada(self) -> None:
        """Spec 019: con `mounts` apagada, la genérica tampoco llega a
        `/mounts` (sigue `dedicated`, con `family_disabled`)."""
        mcp, ha = _registrar_todo(["mounts"])
        self.assertNotIn("sv_create_mount", mcp.tools)
        r = await mcp.tools["sv_call_api"]("PUT", "/mounts/nas", {"name": "nas"})
        self.assertEqual((r["error"], r["tool"], r["family"], r["family_disabled"]),
                         ("use_dedicated_tool", "sv_update_mount", "mounts", True))
        ha.sv_request.assert_not_awaited()

    def test_sin_generic_commands_no_se_registran(self) -> None:
        mcp, _ = _registrar_todo(["generic_commands"])
        for nombre in ("ha_read_ws_command", "ha_call_ws_command",
                       "sv_read_api", "sv_call_api"):
            self.assertNotIn(nombre, mcp.tools)
        self.assertIn("hermes_guide", mcp.tools)


# Spec 029 (CAP-043): los cinco comandos con tool dedicada en `system_status`.
_DEDICADAS_029_SYSTEM_STATUS = {
    "system_health/info": "ha_get_system_health",
    "subscribe_system_state": "ha_get_system_state",
    "integration/setup_info": "ha_list_integration_setup_times",
    "manifest/list": "ha_list_integration_manifests",
    "manifest/get": "ha_get_integration_manifest",
}


class TestDedicadasDeLa029(unittest.IsolatedAsyncioTestCase):
    """Spec 029, T013 (FR-016): con la tabla real, la genérica de lectura
    rechaza los cinco comandos de CAP-043 hacia su tool, sin llegar a HA; con
    `system_status` desactivada, además `family_disabled: true` (la genérica
    no es una vía hacia lo que el usuario apagó).

    Control negativo (T018 e): dejar `manifest/get` en `deny` → cae
    `test_rechazo_hacia_su_tool` («manifest/get») y el de dedicadas de
    test_command_table."""

    async def test_rechazo_hacia_su_tool(self) -> None:
        mcp, ha = _registrar_todo([])
        for comando, tool in _DEDICADAS_029_SYSTEM_STATUS.items():
            with self.subTest(comando=comando):
                r = await mcp.tools["ha_read_ws_command"](comando)
                self.assertEqual(r["error"], "use_dedicated_tool")
                self.assertEqual((r["tool"], r["family"], r["family_disabled"]),
                                 (tool, "system_status", False))
                self.assertIn(tool, mcp.tools)
        ha.ws_send.assert_not_awaited()
        ha.ws_one_shot_subscription.assert_not_awaited()

    async def test_con_la_familia_desactivada(self) -> None:
        mcp, ha = _registrar_todo(["system_status"])
        for comando, tool in _DEDICADAS_029_SYSTEM_STATUS.items():
            with self.subTest(comando=comando):
                self.assertNotIn(tool, mcp.tools)
                r = await mcp.tools["ha_read_ws_command"](comando)
                self.assertEqual((r["error"], r["tool"], r["family_disabled"]),
                                 ("use_dedicated_tool", tool, True))
        ha.ws_send.assert_not_awaited()


class TestDedicadasDeLaSpec012(unittest.IsolatedAsyncioTestCase):
    """Spec 012 (FR-014, T013): los comandos de logs de Core pasan a sus
    tools dedicadas; la genérica los rechaza con `use_dedicated_tool` y, con
    `core_diagnostics` desactivada, con `family_disabled: true` (sin
    ejecutarlos por la genérica).

    Control negativo (T018 g): dejar `system_log/list` en `deny` →
    cae `test_system_log_list_a_su_dedicada` (`command_denied`).
    """

    async def test_system_log_list_a_su_dedicada(self) -> None:
        mcp, ha = _registrar_todo([])
        r = await mcp.tools["ha_read_ws_command"]("system_log/list")
        self.assertEqual((r["error"], r["tool"], r["family"], r["family_disabled"]),
                         ("use_dedicated_tool", "ha_list_system_log", "core_diagnostics", False))
        r = await mcp.tools["ha_call_ws_command"](
            "logger/integration_log_level",
            {"integration": "mqtt", "level": "DEBUG", "persistence": "none"})
        self.assertEqual((r["error"], r["tool"]), ("use_dedicated_tool", "ha_set_log_level"))
        ha.ws_send.assert_not_awaited()

    async def test_con_la_familia_desactivada(self) -> None:
        mcp, ha = _registrar_todo(["core_diagnostics"])
        self.assertNotIn("ha_list_system_log", mcp.tools)
        for tipo, tool in (("system_log/list", "ha_list_system_log"),
                           ("logger/log_info", "ha_get_log_levels")):
            with self.subTest(tipo=tipo):
                r = await mcp.tools["ha_read_ws_command"](tipo)
                self.assertEqual((r["error"], r["tool"], r["family_disabled"]),
                                 ("use_dedicated_tool", tool, True))
        ha.ws_send.assert_not_awaited()


# Spec 029 (CAP-049): los cuatro comandos con tool dedicada en `recorder`.
_DEDICADAS_029_RECORDER = {
    "recorder/info": "ha_get_recorder_info",
    "recorder/entity_options/get": "ha_get_recorder_info",
    "recorder/validate_statistics": "ha_validate_statistics",
    "recorder/get_statistics_metadata": "ha_get_statistics_metadata",
}


class TestDedicadasDeLa029Recorder(unittest.IsolatedAsyncioTestCase):
    """Spec 029, T023 (FR-016): con la tabla real, las genéricas rechazan los
    cuatro comandos de CAP-049 hacia su tool de `recorder`, sin llegar a HA;
    con la familia desactivada, además `family_disabled: true`.

    Control negativo (T034 f): dejar `recorder/info` en `deny` -> cae
    `test_rechazo_hacia_su_tool` («recorder/info») y
    `test_dedicadas_de_la_029` de test_command_table."""

    async def test_rechazo_hacia_su_tool(self) -> None:
        mcp, ha = _registrar_todo([])
        for comando, tool in _DEDICADAS_029_RECORDER.items():
            with self.subTest(comando=comando):
                r = await mcp.tools["ha_read_ws_command"](comando)
                self.assertEqual(r["error"], "use_dedicated_tool")
                self.assertEqual((r["tool"], r["family"], r["family_disabled"]),
                                 (tool, "recorder", False))
                self.assertIn(tool, mcp.tools)
                # Tampoco por la de escritura: no es una vía alternativa.
                r = await mcp.tools["ha_call_ws_command"](comando, {})
                self.assertEqual((r["error"], r["tool"]), ("use_dedicated_tool", tool))
        ha.ws_send.assert_not_awaited()

    async def test_con_la_familia_desactivada(self) -> None:
        mcp, ha = _registrar_todo(["recorder"])
        for comando, tool in _DEDICADAS_029_RECORDER.items():
            with self.subTest(comando=comando):
                self.assertNotIn(tool, mcp.tools)
                r = await mcp.tools["ha_read_ws_command"](comando)
                self.assertEqual((r["error"], r["tool"], r["family_disabled"]),
                                 ("use_dedicated_tool", tool, True))
        ha.ws_send.assert_not_awaited()


class TestDedicadasDelTramoBDeLa012(unittest.IsolatedAsyncioTestCase):
    """Spec 012, tramo B (FR-014, T028): validación, diagnósticos y
    notificaciones pasan a sus tools dedicadas; la genérica de lectura las
    rechaza con `use_dedicated_tool` sin ejecutarlas.

    Control negativo (T033 f): dejar `diagnostics/list` en `deny` → cae
    `test_a_su_dedicada` (`command_denied`).
    """

    async def test_a_su_dedicada(self) -> None:
        mcp, ha = _registrar_todo([])
        for tipo, tool in (("diagnostics/list", "ha_list_diagnostics_handlers"),
                           ("diagnostics/get", "ha_list_diagnostics_handlers"),
                           ("validate_config", "ha_validate_config"),
                           ("test_condition", "ha_test_condition"),
                           ("persistent_notification/get",
                            "ha_list_persistent_notifications")):
            with self.subTest(tipo=tipo):
                r = await mcp.tools["ha_read_ws_command"](tipo)
                self.assertEqual((r["error"], r["tool"], r["family"], r["family_disabled"]),
                                 ("use_dedicated_tool", tool, "core_diagnostics", False))
        ha.ws_send.assert_not_awaited()

    async def test_con_la_familia_desactivada(self) -> None:
        mcp, ha = _registrar_todo(["core_diagnostics"])
        r = await mcp.tools["ha_read_ws_command"]("persistent_notification/get")
        self.assertEqual((r["error"], r["tool"], r["family_disabled"]),
                         ("use_dedicated_tool", "ha_list_persistent_notifications", True))
        ha.ws_send.assert_not_awaited()


class TestTiendaDeLa030(unittest.IsolatedAsyncioTestCase):
    """Spec 030, T009 (FR-014, FR-015): con la tabla real, las genéricas del
    Supervisor rechazan las rutas de repositorios y recarga hacia su tool de
    `app_store`, sin llegar al Supervisor; con la familia desactivada, además
    `family_disabled: true`. Los iconos siguen `deny` (clase B).

    Control negativo (T012 g): dejar `POST /store/repositories` como `deny`
    → cae `test_rechazo_hacia_su_tool` (sale `command_denied`)."""

    _CASOS = (
        ("sv_read_api", ("/store/repositories",), "sv_list_store_repositories"),
        ("sv_read_api", ("/store",), "sv_list_store_repositories"),
        ("sv_read_api", ("/store/repositories/abcd1234",), "sv_list_store_repositories"),
        ("sv_call_api", ("POST", "/store/repositories",
                         {"repository": "https://example.com/repo-ficticio"}),
         "sv_add_store_repository"),
        ("sv_call_api", ("DELETE", "/store/repositories/abcd1234"),
         "sv_remove_store_repository"),
        ("sv_call_api", ("POST", "/store/repositories/abcd1234/repair"),
         "sv_repair_store_repository"),
        ("sv_call_api", ("POST", "/store/reload"), "sv_reload_store"),
    )

    async def test_rechazo_hacia_su_tool(self) -> None:
        mcp, ha = _registrar_todo([])
        for generica, args, tool in self._CASOS:
            with self.subTest(args=args):
                r = await mcp.tools[generica](*args)
                self.assertEqual(r.get("error"), "use_dedicated_tool", r)
                self.assertEqual((r["tool"], r["family"], r["family_disabled"]),
                                 (tool, "app_store", False))
                self.assertIn(tool, mcp.tools)
        ha.sv_request.assert_not_awaited()

    async def test_con_la_familia_desactivada(self) -> None:
        mcp, ha = _registrar_todo(["app_store"])
        for generica, args, tool in self._CASOS:
            with self.subTest(args=args):
                self.assertNotIn(tool, mcp.tools)
                r = await mcp.tools[generica](*args)
                self.assertEqual((r["error"], r["tool"], r["family_disabled"]),
                                 ("use_dedicated_tool", tool, True))
        ha.sv_request.assert_not_awaited()

    async def test_iconos_siguen_denegados(self) -> None:
        mcp, ha = _registrar_todo([])
        r = await mcp.tools["sv_read_api"]("/store/addons/abcd1234_ejemplo/icon")
        self.assertEqual(r["error"], "command_denied")
        ha.sv_request.assert_not_awaited()

    # Tramo 2 (T022): las de `app_store` y las que apuntan a una tool de la
    # 1.1.2 (`supervisor`), que siguen ahí aunque `app_store` se apague.
    _CASOS_T2_TIENDA = (
        ("sv_read_api", ("/store/addons/abcd1234_ejemplo/changelog",), "sv_get_addon_changelog"),
        ("sv_read_api", ("/store/addons/abcd1234_ejemplo/documentation",),
         "sv_get_addon_documentation"),
        ("sv_read_api", ("/store/addons/abcd1234_ejemplo/availability",),
         "sv_get_addon_availability"),
        ("sv_call_api", ("POST", "/addons/local_ejemplo/rebuild", {"force": True}),
         "sv_rebuild_addon"),
    )
    _CASOS_T2_SUPERVISOR = (
        ("sv_call_api", ("POST", "/store/addons/abcd1234_ejemplo/install/1.0.0"),
         "sv_install_addon"),
        ("sv_call_api", ("POST", "/store/addons/abcd1234_ejemplo/update/1.0.0"),
         "sv_update_addon"),
        ("sv_read_api", ("/store/addons/abcd1234_ejemplo/1.0.0",), "sv_get_addon"),
        ("sv_call_api", ("POST", "/addons/abcd1234_ejemplo/options/validate", {"a": 1}),
         "sv_set_addon_options"),
    )

    async def test_tramo_2_hacia_su_tool(self) -> None:
        """Control negativo (T026 g): dejar `POST /addons/{app}/rebuild` como
        `deny` → cae este test (sale `command_denied`)."""
        for desactivadas in ([], ["app_store"]):
            mcp, ha = _registrar_todo(desactivadas)
            for casos, familia in ((self._CASOS_T2_TIENDA, "app_store"),
                                   (self._CASOS_T2_SUPERVISOR, "supervisor")):
                for generica, args, tool in casos:
                    with self.subTest(args=args, desactivadas=desactivadas):
                        r = await mcp.tools[generica](*args)
                        self.assertEqual(r.get("error"), "use_dedicated_tool", r)
                        apagada = familia in desactivadas
                        self.assertEqual((r["tool"], r["family"], r["family_disabled"]),
                                         (tool, familia, apagada))
                        self.assertEqual(tool in mcp.tools, not apagada)
            ha.sv_request.assert_not_awaited()
class TestDedicadasDeLa017(unittest.IsolatedAsyncioTestCase):
    """Spec 017, tramo A (FR-012, T010): los comandos de blueprints pasan a
    sus tools dedicadas; las genéricas los rechazan con `use_dedicated_tool`
    sin ejecutarlos y, con `blueprints` desactivada, con `family_disabled:
    true`.

    Control negativo (T016, 7): dejar `blueprint/delete` en `deny` → cae
    `test_a_su_dedicada` (`command_denied`).
    """

    async def test_a_su_dedicada(self) -> None:
        mcp, ha = _registrar_todo([])
        r = await mcp.tools["ha_call_ws_command"](
            "blueprint/delete", {"domain": "automation", "path": "hermes/luz.yaml"})
        self.assertEqual((r["error"], r["tool"], r["family"], r["family_disabled"]),
                         ("use_dedicated_tool", "ha_delete_blueprint", "blueprints", False))
        for tipo, tool in (("blueprint/list", "ha_list_blueprints"),
                           ("blueprint/substitute", "ha_preview_blueprint_substitution")):
            with self.subTest(tipo=tipo):
                r = await mcp.tools["ha_read_ws_command"](tipo)
                self.assertEqual((r["error"], r["tool"], r["family_disabled"]),
                                 ("use_dedicated_tool", tool, False))
        r = await mcp.tools["ha_call_ws_command"]("blueprint/save", {})
        self.assertEqual((r["error"], r["tool"]), ("use_dedicated_tool", "ha_save_blueprint"))
        ha.ws_send.assert_not_awaited()

    async def test_importar_a_su_dedicada(self) -> None:
        """Tramo B (T021): `blueprint/import` pasa a `ha_import_blueprint`; antes
        era `deny` («pendiente de tool dedicada»). Control negativo
        comprobado: dejarla en `deny` → `command_denied` y cae este test."""
        mcp, ha = _registrar_todo([])
        url = {"url": "https://example.com/blueprints/luz.yaml"}
        for generica in ("ha_call_ws_command", "ha_read_ws_command"):
            with self.subTest(generica=generica):
                r = await mcp.tools[generica]("blueprint/import", url)
                self.assertEqual((r["error"], r["tool"], r["family"], r["family_disabled"]),
                                 ("use_dedicated_tool", "ha_import_blueprint", "blueprints",
                                  False))
        mcp, ha_off = _registrar_todo(["blueprints"])
        r = await mcp.tools["ha_call_ws_command"]("blueprint/import", url)
        self.assertEqual((r["tool"], r["family_disabled"]), ("ha_import_blueprint", True))
        ha.ws_send.assert_not_awaited()
        ha_off.ws_send.assert_not_awaited()

    async def test_con_la_familia_desactivada(self) -> None:
        mcp, ha = _registrar_todo(["blueprints"])
        self.assertNotIn("ha_delete_blueprint", mcp.tools)
        r = await mcp.tools["ha_call_ws_command"](
            "blueprint/delete", {"domain": "automation", "path": "hermes/luz.yaml"})
        self.assertEqual((r["error"], r["tool"], r["family_disabled"]),
                         ("use_dedicated_tool", "ha_delete_blueprint", True))
        r = await mcp.tools["ha_read_ws_command"]("blueprint/list")
        self.assertEqual((r["error"], r["family_disabled"]), ("use_dedicated_tool", True))
        ha.ws_send.assert_not_awaited()


class TestDedicadasDeLa017TramoC(unittest.IsolatedAsyncioTestCase):
    """Spec 017, tramo C (FR-012, T032): las genéricas rechazan los comandos
    de dispositivo y de targets con `use_dedicated_tool` y el nombre de la
    tool, sin ejecutarlos; con `automation_assist` desactivada, con
    `family_disabled: true`.

    Control negativo (T037, 4): dejar `device_automation/trigger/list` en
    `deny` → cae `test_a_su_dedicada` (`command_denied`).
    """

    async def test_a_su_dedicada(self) -> None:
        mcp, ha = _registrar_todo([])
        for generica in ("ha_read_ws_command", "ha_call_ws_command"):
            for tipo, args, tool in (
                ("device_automation/trigger/list", {"device_id": "x"},
                 "ha_list_device_triggers"),
                ("get_services_for_target", {"target": {"entity_id": "light.salon"}},
                 "ha_list_actions_for_target"),
            ):
                with self.subTest(generica=generica, tipo=tipo):
                    r = await mcp.tools[generica](tipo, args)
                    self.assertEqual(
                        (r["error"], r["tool"], r["family"], r["family_disabled"]),
                        ("use_dedicated_tool", tool, "automation_assist", False))
        ha.ws_send.assert_not_awaited()

    async def test_con_la_familia_desactivada(self) -> None:
        mcp, ha = _registrar_todo(["automation_assist"])
        self.assertNotIn("ha_resolve_target", mcp.tools)
        r = await mcp.tools["ha_read_ws_command"](
            "extract_from_target", {"target": {"area_id": "salon"}})
        self.assertEqual((r["error"], r["tool"], r["family_disabled"]),
                         ("use_dedicated_tool", "ha_resolve_target", True))
        ha.ws_send.assert_not_awaited()


class TestDedicadaDeLa017TramoD(unittest.IsolatedAsyncioTestCase):
    """Spec 017, tramo D (FR-012, T045): `subscribe_trigger` deja de ser
    clase B y las genéricas lo mandan a `ha_wait_for_trigger` sin ejecutarlo.

    Control negativo (T054, 8): `subscribe_trigger` de vuelta a `deny` →
    cae `test_a_su_dedicada` (`command_denied`).
    """

    async def test_a_su_dedicada(self) -> None:
        mcp, ha = _registrar_todo([])
        for generica in ("ha_read_ws_command", "ha_call_ws_command"):
            with self.subTest(generica=generica):
                r = await mcp.tools[generica](
                    "subscribe_trigger", {"trigger": {"trigger": "state"}})
                self.assertEqual(
                    (r["error"], r["tool"], r["family"], r["family_disabled"]),
                    ("use_dedicated_tool", "ha_wait_for_trigger", "automation_assist", False))
        ha.ws_send.assert_not_awaited()


class TestRegistro(unittest.TestCase):
    def test_registra_las_cuatro(self) -> None:
        mcp = DummyMCP()
        mod.register(mcp, _cliente(), response_max_bytes=131_072)
        self.assertEqual(sorted(mcp.tools), ["ha_call_ws_command", "ha_read_ws_command",
                                             "sv_call_api", "sv_read_api"])

    def test_descripciones_honestas(self) -> None:
        mcp = DummyMCP()
        mod.register(mcp, _cliente(), response_max_bytes=131_072)
        for nombre, fn in mcp.tools.items():
            with self.subTest(tool=nombre):
                doc = fn.__doc__ or ""
                self.assertIn("table", doc)
                self.assertIn("hermes_guide", doc)
        for nombre in ("ha_call_ws_command", "sv_call_api"):
            self.assertIn("confirmation_token", mcp.tools[nombre].__doc__)

    def test_la_guia_que_citan_existe_y_busca(self) -> None:
        """Las cuatro remiten a `hermes_guide(topic="generic_commands")` y a
        `search=`: el tema existe y la búsqueda encuentra comandos de la tabla
        (principio V: la descripción no puede prometer lo que no hay).

        Control negativo comprobado: sin el tema en `_GUIDE` (tramo 2) cae.
        """
        import asyncio
        import re

        from hermes.tools import guide

        mcp = DummyMCP()
        mod.register(mcp, _cliente(), response_max_bytes=131_072)
        guia = DummyMCP()
        guide.register(guia)
        temas = set()
        for nombre, fn in mcp.tools.items():
            m = re.search(r'hermes_guide\(topic="(\w+)"\)', fn.__doc__ or "")
            self.assertIsNotNone(m, nombre)
            self.assertIn("search=", fn.__doc__)
            temas.add(m.group(1))
        self.assertEqual(temas, {"generic_commands"})
        self.assertIn("generic_commands", guide._GUIDE)
        texto = asyncio.run(guia.tools["hermes_guide"]("generic_commands", search="tag/"))
        self.assertIn("| `tag/list` | read |", texto)
        self.assertIn("| `tag/create` | confirm |", texto)


if __name__ == "__main__":
    unittest.main()
