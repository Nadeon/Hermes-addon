"""Tests de ha_render_template — cubre el flujo WS de suscripción completo."""

from __future__ import annotations

import asyncio
import json
import unittest

from aiohttp import ClientSession

import hermes.tools.templates as mod
from tests._ha_fixture import make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _make_client_with_subscription(session, event_payload: dict, delay: float = 0.0, fail_result: bool = False):
    """Construye un HAClient cuyo ws_one_shot_subscription finge el flujo HA:
       - Devuelve event_payload como si HA lo hubiera emitido como type:event.
       - Si fail_result=True, lanza HAConnectionError (suscripción rechazada).
       - Si delay>0, espera antes de devolver (simula latencia de HA).
    """
    from hermes.ha import HAConnectionError

    client = make_ready_client(session, {})

    async def fake_one_shot(payload, event_timeout_seconds=10.0, collect_warnings=False):
        if fail_result:
            raise HAConnectionError("HA WS command failed: template error")
        if delay > 0:
            await asyncio.sleep(delay)
        return event_payload

    client.ws_one_shot_subscription = fake_one_shot  # type: ignore[method-assign]
    return client


def _make_client_with_timeout(session):
    """Simula timeout en ws_one_shot_subscription."""
    from hermes.ha import HAConnectionError

    client = make_ready_client(session, {})

    async def fake_timeout(payload, event_timeout_seconds=10.0, collect_warnings=False):
        raise HAConnectionError("Timeout waiting for subscription event: render_template")

    client.ws_one_shot_subscription = fake_timeout  # type: ignore[method-assign]
    return client


class TestToolsTemplates(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_render_simple_template(self) -> None:
        client = _make_client_with_subscription(
            self.session,
            {"result": "on", "listeners": {"entities": ["light.salon"], "all_states": False}},
        )
        mcp = DummyMCP()
        mod.register(mcp, client)
        raw = await mcp.tools["ha_render_template"]("{{ states('light.salon') }}")
        result = json.loads(raw)
        self.assertEqual(result["result"], "on")
        self.assertIn("listeners", result)

    async def test_render_returns_numeric_result(self) -> None:
        client = _make_client_with_subscription(
            self.session,
            {"result": 42, "listeners": {}},
        )
        mcp = DummyMCP()
        mod.register(mcp, client)
        raw = await mcp.tools["ha_render_template"]("{{ 6 * 7 }}")
        result = json.loads(raw)
        self.assertEqual(result["result"], 42)

    async def test_render_nonexistent_entity_returns_unknown(self) -> None:
        """states('sensor.no_existe_xxx') devuelve 'unknown' — no error.

        Con report_errors=True y strict=False (defaults), HA devuelve
        event con result='unknown'.
        """
        client = _make_client_with_subscription(
            self.session,
            {"result": "unknown", "listeners": {"entities": [], "all_states": False}},
        )
        mcp = DummyMCP()
        mod.register(mcp, client)
        raw = await mcp.tools["ha_render_template"]("{{ states('sensor.no_existe_xxx') }}")
        result = json.loads(raw)
        self.assertEqual(result["result"], "unknown")

    async def test_render_template_error_returned_as_structured(self) -> None:
        """Errores de template vienen como event {error: ..., level: ...}."""
        client = _make_client_with_subscription(
            self.session,
            {"error": "UndefinedError: 'no_var' is undefined", "level": "ERROR"},
        )
        mcp = DummyMCP()
        mod.register(mcp, client)
        raw = await mcp.tools["ha_render_template"]("{{ no_var }}", strict=True)
        result = json.loads(raw)
        self.assertEqual(result["error"], "template_error")
        self.assertIn("undefined", result["detail"])
        self.assertEqual(result["level"], "ERROR")

    async def test_render_timeout_returns_structured_error(self) -> None:
        """Timeout devuelve {"error": "template_timeout", "template": ...}."""
        client = _make_client_with_timeout(self.session)
        mcp = DummyMCP()
        mod.register(mcp, client)
        raw = await mcp.tools["ha_render_template"]("{{ states.all | list }}", timeout=5.0)
        result = json.loads(raw)
        self.assertEqual(result["error"], "template_timeout")
        self.assertIn("template", result)
        self.assertIn("hint", result)

    async def test_render_with_variables(self) -> None:
        """Variables se pasan al payload WS."""
        received_payload: list[dict] = []
        session = self.session
        client = make_ready_client(session, {})

        async def capture_payload(payload, event_timeout_seconds=10.0, collect_warnings=False):
            received_payload.append(payload)
            return {"result": "hola mundo", "listeners": {}}

        client.ws_one_shot_subscription = capture_payload  # type: ignore[method-assign]

        mcp = DummyMCP()
        mod.register(mcp, client)
        await mcp.tools["ha_render_template"](
            "{{ greeting }} {{ name }}",
            variables={"greeting": "hola", "name": "mundo"},
        )
        self.assertEqual(received_payload[0]["variables"], {"greeting": "hola", "name": "mundo"})

    async def test_render_strict_flag_passed(self) -> None:
        """strict=True se pasa al payload WS."""
        received_payload: list[dict] = []
        session = self.session
        client = make_ready_client(session, {})

        async def capture_payload(payload, event_timeout_seconds=10.0, collect_warnings=False):
            received_payload.append(payload)
            return {"result": "x", "listeners": {}}

        client.ws_one_shot_subscription = capture_payload  # type: ignore[method-assign]

        mcp = DummyMCP()
        mod.register(mcp, client)
        await mcp.tools["ha_render_template"]("{{ x }}", strict=True)
        self.assertTrue(received_payload[0]["strict"])
        self.assertTrue(received_payload[0]["report_errors"])

    async def test_timeout_se_acota_al_rango_admitido(self) -> None:
        """El timeout del cliente se acota: iba tal cual a la espera del WS.

        Un 0 o un negativo hacía que la suscripción venciera antes de que HA
        pudiera contestar, y un valor enorme dejaba la llamada colgada sin tope.
        """
        recibidos: list[tuple[dict, float]] = []
        client = make_ready_client(self.session, {})

        async def capture(payload, event_timeout_seconds=10.0, collect_warnings=False):
            recibidos.append((payload, event_timeout_seconds))
            return {"result": "x", "listeners": {}}

        client.ws_one_shot_subscription = capture  # type: ignore[method-assign]

        mcp = DummyMCP()
        mod.register(mcp, client)

        for pedido, esperado in ((0, 1.0), (-5, 1.0), (3600, 60.0), (12, 12.0)):
            recibidos.clear()
            await mcp.tools["ha_render_template"]("{{ 1 }}", timeout=pedido)
            payload, event_timeout = recibidos[0]
            self.assertEqual(event_timeout, esperado)
            self.assertEqual(payload["timeout"], esperado)

    # ── D2: avisos y timeout de HA (FR-033, FR-034) ─────────

    async def test_render_with_warning_returns_result_and_warnings(self) -> None:
        """(b) Un aviso de nivel WARNING no es un error: la plantilla se
        renderizó y el resultado no se puede perder."""
        llamadas: list[bool] = []
        client = make_ready_client(self.session, {})

        async def fake_one_shot(payload, event_timeout_seconds=10.0, collect_warnings=False):
            llamadas.append(collect_warnings)
            if not collect_warnings:
                # Sin recoger avisos, HA entrega primero el aviso.
                return {"error": "'x' is undefined", "level": "WARNING"}
            return {"result": "ok", "listeners": {}, "warnings": ["'x' is undefined"]}

        client.ws_one_shot_subscription = fake_one_shot  # type: ignore[method-assign]
        mcp = DummyMCP()
        mod.register(mcp, client)
        result = json.loads(await mcp.tools["ha_render_template"]("{{ x }}ok"))
        self.assertEqual(llamadas, [True])
        self.assertNotIn("error", result)
        self.assertEqual(result["result"], "ok")
        self.assertEqual(result["warnings"], ["'x' is undefined"])

    async def test_render_error_level_is_still_template_error(self) -> None:
        """(c) Un error de nivel ERROR sigue siendo `template_error`."""
        client = _make_client_with_subscription(
            self.session, {"error": "boom", "level": "ERROR"}
        )
        mcp = DummyMCP()
        mod.register(mcp, client)
        result = json.loads(await mcp.tools["ha_render_template"]("{{ x }}"))
        self.assertEqual(result["error"], "template_error")

    async def test_ha_side_timeout_is_template_timeout(self) -> None:
        """(d) Cuando el timeout lo detecta HA, llega como error del comando
        con código `template_error`; antes salía como error genérico."""
        from hermes.ha import HAConnectionError

        client = make_ready_client(self.session, {})

        async def fake_one_shot(payload, event_timeout_seconds=10.0, collect_warnings=False):
            raise HAConnectionError(
                "HA WS command failed: Exceeded maximum execution time of 5s",
                code="template_error",
            )

        client.ws_one_shot_subscription = fake_one_shot  # type: ignore[method-assign]
        mcp = DummyMCP()
        mod.register(mcp, client)
        result = json.loads(
            await mcp.tools["ha_render_template"]("{{ states | list }}", timeout=5)
        )
        self.assertEqual(result["error"], "template_timeout")


class _ScriptedWS:
    """WebSocket falsa: al recibir la suscripción, entrega por el manejador
    real la confirmación y después `events`, como haría HA."""

    closed = False

    def __init__(self, client, events: list[dict]) -> None:
        self.client = client
        self.events = events
        self.sent: list[dict] = []
        self._tasks: list[asyncio.Task] = []

    async def send_json(self, msg: dict) -> None:
        self.sent.append(msg)
        if msg.get("type") == "render_template":
            self._tasks.append(asyncio.create_task(self._feed(msg["id"])))

    async def _feed(self, request_id: int) -> None:
        await self.client._handle_ws_message(
            {"id": request_id, "type": "result", "success": True, "result": None}
        )
        for event in self.events:
            await asyncio.sleep(0)
            await self.client._handle_ws_message(
                {"id": request_id, "type": "event", "event": event}
            )


class TestOneShotSubscriptionWarnings(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.client = make_ready_client(self.session, {})
        # make_ready_client no crea las colas de suscripciones persistentes.
        self.client._event_subscription_queues = {}

    async def asyncTearDown(self) -> None:
        await self.session.close()

    _EVENTS = [
        {"error": "'x' is undefined", "level": "WARNING"},
        {"result": "ok", "listeners": {}},
    ]

    async def test_collect_warnings_returns_result_with_warnings(self) -> None:
        """(a) Con `collect_warnings`, el aviso se acumula y se devuelve el
        resultado; la suscripción se cancela al terminar."""
        ws = _ScriptedWS(self.client, self._EVENTS)
        self.client._ws = ws  # type: ignore[assignment]
        event = await self.client.ws_one_shot_subscription(
            {"type": "render_template", "template": "{{ x }}ok"},
            event_timeout_seconds=2,
            collect_warnings=True,
        )
        self.assertEqual(
            event,
            {"result": "ok", "listeners": {}, "warnings": ["'x' is undefined"]},
        )
        self.assertTrue(any(m["type"] == "unsubscribe_events" for m in ws.sent))
        self.assertEqual(self.client._event_subscription_queues, {})

    async def test_without_collect_warnings_behaviour_unchanged(self) -> None:
        """(e) Sin `collect_warnings`, se devuelve el primer evento, como
        antes."""
        ws = _ScriptedWS(self.client, self._EVENTS)
        self.client._ws = ws  # type: ignore[assignment]
        event = await self.client.ws_one_shot_subscription(
            {"type": "render_template", "template": "{{ x }}ok"},
            event_timeout_seconds=2,
        )
        self.assertEqual(event, {"error": "'x' is undefined", "level": "WARNING"})
        self.assertTrue(any(m["type"] == "unsubscribe_events" for m in ws.sent))
