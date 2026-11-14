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
