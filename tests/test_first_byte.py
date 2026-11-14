"""El primer byte de una tool lenta sale antes de que termine (spec 003, FR-036).

Claude Code corta una petición si no recibe ningún byte en 60 s. Una tool
lenta —`ha_wait_for_event` puede esperar hasta 220 s— solo sobrevive si la
respuesta se compromete pronto a `text/event-stream` y manda comentarios
`: ping` mientras tanto. El SDK ya lo hace (cada 15 s, en las dos familias de
versión), pero basta un middleware de Hermes que almacene la respuesta entera
para que esos bytes se queden retenidos hasta el final y el cliente corte.

Este test pasa una tool lenta por la misma pila de middlewares que monta
`__main__`, en el mismo orden, con el intervalo de ping del SDK reducido a
0,2 s, y exige que las cabeceras SSE y un ping lleguen al cliente mucho antes
que el resultado. Un middleware futuro que almacene la respuesta lo rompe.
"""

from __future__ import annotations

import json
import time
from typing import Any

import anyio
import pytest
from mcp.server.transport_security import TransportSecuritySettings
from sse_starlette import EventSourceResponse
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount

import mcp.server._streamable_http_modern as modern
from hermes.mcp_server import build_mcp_server
from hermes.middleware import (
    BodySizeLimitMiddleware,
    LoggingMiddleware,
    McpProtocolVersionMiddleware,
    OAuthBearerAuth,
    RateLimitPostAuth,
    RateLimitPreAuth,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
)

pytestmark = pytest.mark.anyio

PING = 0.2
TOOL_SECONDS = 1.0


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def fast_pings(monkeypatch: pytest.MonkeyPatch) -> None:
    # Los dos relojes de keepalive del SDK: `sse-starlette` en las versiones
    # con handshake y el aplazamiento propio del transporte de 2026-07-28.
    monkeypatch.setattr(EventSourceResponse, "DEFAULT_PING_INTERVAL", PING)
    monkeypatch.setattr(modern, "_SSE_PING_INTERVAL", PING)


class _AcceptAll:
    """Validador OAuth falso: el test es del transporte, no de la autenticación."""

    async def validate_token(self, token: str) -> bool:
        return True


def _build_app(*, json_response: bool = False):
    server = build_mcp_server("x")

    @server.tool(name="slow")
    async def slow() -> object:
        await anyio.sleep(TOOL_SECONDS)
        return {"ok": True}

    # La misma pila y el mismo orden que `__main__` (de fuera a dentro).
    middleware = [
        Middleware(SecurityHeadersMiddleware),
        Middleware(RateLimitPreAuth, max_per_minute=1000, authenticated_max_per_minute=1000),
        Middleware(OAuthBearerAuth, oauth_validator=_AcceptAll(), resource_metadata_url=None),
        Middleware(BodySizeLimitMiddleware, max_body_bytes=1_048_576),
        Middleware(RateLimitPostAuth, max_per_minute=1000),
        Middleware(RequestIdMiddleware),
        Middleware(LoggingMiddleware),
        Middleware(McpProtocolVersionMiddleware),
    ]
    app = Starlette(
        routes=[
            Mount(
                "/",
                app=server.streamable_http_app(
                    stateless_http=True,
                    json_response=json_response,
                    transport_security=TransportSecuritySettings(
                        enable_dns_rebinding_protection=True,
                        allowed_hosts=["testserver"],
                        allowed_origins=[],
                    ),
                ),
            )
        ],
        middleware=middleware,
    )
    return server, app


def _request(version: str) -> tuple[dict[str, Any], dict[str, str]]:
    params: dict[str, Any] = {"name": "slow", "arguments": {}}
    headers = {
        "host": "testserver",
        "authorization": "Bearer token-de-prueba",
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "mcp-protocol-version": version,
    }
    if version == "2026-07-28":
        # Sin handshake: la versión y las capacidades viajan en cada petición,
        # y el transporte exige que las cabeceras repitan el método y la tool.
        params["_meta"] = {
            "io.modelcontextprotocol/protocolVersion": version,
            "io.modelcontextprotocol/clientCapabilities": {},
        }
        headers["mcp-method"] = "tools/call"
        headers["mcp-name"] = "slow"
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}
    return body, headers


async def _call(app: Any, server: Any, version: str) -> list[tuple[float, dict[str, Any]]]:
    """Ejecuta la app ASGI y anota cada mensaje enviado con su instante."""
    body, headers = _request(version)
    raw = json.dumps(body).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "root_path": "",
        "query_string": b"",
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    finished = anyio.Event()
    sent_body = False

    async def receive() -> dict[str, Any]:
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": raw, "more_body": False}
        # El cliente sigue conectado hasta que llega la respuesta completa.
        await finished.wait()
        return {"type": "http.disconnect"}

    events: list[tuple[float, dict[str, Any]]] = []
    start = time.monotonic()

    async def send(message: dict[str, Any]) -> None:
        events.append((time.monotonic() - start, message))
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            finished.set()

    async with server.session_manager.run():
        with anyio.fail_after(10):
            await app(scope, receive, send)
    return events


def _headers(message: dict[str, Any]) -> dict[str, str]:
    return {k.decode().lower(): v.decode() for k, v in message.get("headers", [])}


@pytest.mark.parametrize("version", ["2025-11-25", "2026-07-28"])
async def test_headers_and_ping_arrive_before_the_result(version: str) -> None:
    server, app = _build_app()
    events = await _call(app, server, version)

    starts = [(t, m) for t, m in events if m["type"] == "http.response.start"]
    assert starts, "no hubo http.response.start"
    t_start, start = starts[0]
    assert start["status"] == 200
    assert _headers(start)["content-type"].startswith("text/event-stream")
    assert t_start < 0.5, f"cabeceras a los {t_start:.2f} s"

    bodies = [(t, m.get("body", b"")) for t, m in events if m["type"] == "http.response.body"]
    pings = [(t, b) for t, b in bodies if b.lstrip().startswith(b":")]
    assert pings, f"ningún comentario de ping: {bodies!r}"
    assert pings[0][0] < 0.5, f"primer ping a los {pings[0][0]:.2f} s"

    # El resultado llega al final, cuando la tool termina.
    everything = b"".join(b for _, b in bodies)
    assert b'"ok": true' in everything or b'\\"ok\\": true' in everything, everything
    t_last = bodies[-1][0]
    assert t_last >= TOOL_SECONDS * 0.9
