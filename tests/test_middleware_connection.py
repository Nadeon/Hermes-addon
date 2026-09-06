"""Tests de la capa de conexión: discovery OAuth determinista, alias de paths
por defecto, motivo de los errores del MCP en el log y rechazo legible de
versiones de protocolo MCP no soportadas por el SDK."""

import json
import unittest
from typing import Any
from unittest import mock

from mcp_types.version import (
    HANDSHAKE_PROTOCOL_VERSIONS,
    SUPPORTED_PROTOCOL_VERSIONS,
)
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from hermes import middleware as mw
from hermes.middleware import (
    LoggingMiddleware,
    McpProtocolVersionMiddleware,
    OAuthBearerAuth,
    _is_public_path,
)

# Una versión que el SDK instalado NO habla. 2026-07-28 es la revisión real
# del protocolo que introdujo el modelo sin handshake; si algún día el SDK la
# soporta, el test cae a una versión ficticia para seguir probando el caso.
UNSUPPORTED_VERSION = (
    "2026-07-28" if "2026-07-28" not in SUPPORTED_PROTOCOL_VERSIONS else "2099-01-01"
)
SUPPORTED_VERSION = SUPPORTED_PROTOCOL_VERSIONS[-1]

# El SDK 2.x separa las versiones que usan el handshake clásico (`initialize`)
# de las "modernas" (2026-07-28+, sin handshake). Para probar el flujo clásico
# hay que usar la última de las primeras: mandar `initialize` anunciando una
# versión moderna es incoherente y el SDK lo rechaza, con razón.
HANDSHAKE_VERSION = HANDSHAKE_PROTOCOL_VERSIONS[-1]

MCP_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}


class _FakeLogger:
    """Sustituto del logger de structlog que guarda las llamadas."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _record(self, level: str):
        def _log(event: str, **kw: Any) -> None:
            self.calls.append((level, event, kw))
        return _log

    def __getattr__(self, level: str):
        return self._record(level)

    def find(self, event: str) -> list[dict[str, Any]]:
        return [kw for _, ev, kw in self.calls if ev == event]


async def _echo(request: Request) -> PlainTextResponse:
    body = await request.body()
    return PlainTextResponse(body, headers={"x-echo-version": request.headers.get("mcp-protocol-version", "")})


async def _bad_request(request: Request) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": "server-error",
         "error": {"code": -32600, "message": "Bad Request: unsupported"}},
        status_code=400,
    )


async def _hi(request: Request) -> PlainTextResponse:
    return PlainTextResponse("hi")


# ── Discovery: WWW-Authenticate y paths públicos ──────────────

class TestWwwAuthenticate(unittest.TestCase):
    def _client(self, **kwargs: Any) -> TestClient:
        app = Starlette(
            routes=[Route("/mcp", _hi, methods=["GET", "POST"])],
            middleware=[Middleware(OAuthBearerAuth, oauth_validator=None, **kwargs)],
        )
        return TestClient(app)

    def test_401_announces_resource_metadata(self) -> None:
        url = "https://hermes.tail-xxxx.ts.net/.well-known/oauth-protected-resource"
        resp = self._client(resource_metadata_url=url).post("/mcp")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(
            resp.headers["www-authenticate"],
            f'Bearer realm="hermes", resource_metadata="{url}"',
        )

    def test_401_without_metadata_url_keeps_plain_challenge(self) -> None:
        resp = self._client().post("/mcp")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.headers["www-authenticate"], 'Bearer realm="hermes"')


class TestDefaultOAuthPathsArePublic(unittest.TestCase):
    def test_spec_default_paths(self) -> None:
        for path in ("/register", "/authorize", "/token", "/revoke"):
            self.assertTrue(_is_public_path(path), path)

    def test_canonical_paths_still_public(self) -> None:
        for path in ("/oauth/register", "/oauth/authorize", "/oauth/token", "/oauth/revoke"):
            self.assertTrue(_is_public_path(path), path)

    def test_mcp_is_not_public(self) -> None:
        self.assertFalse(_is_public_path("/mcp"))
        self.assertFalse(_is_public_path("/"))

    def test_default_paths_bypass_bearer_auth(self) -> None:
        app = Starlette(
            routes=[Route("/register", _hi, methods=["POST"])],
            middleware=[Middleware(OAuthBearerAuth, oauth_validator=None)],
        )
        resp = TestClient(app).post("/register")
        self.assertEqual(resp.status_code, 200)


class TestOAuthAliasRoutes(unittest.TestCase):
    def test_get_routes_exposes_default_paths(self) -> None:
        import tempfile
        from pathlib import Path

        from hermes import oauth

        attrs = ("_OAUTH_DIR", "_CLIENTS_DIR", "_CODES_DIR", "_TOKENS_DIR")
        orig = {a: getattr(oauth, a) for a in attrs}
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "oauth"
            oauth._OAUTH_DIR = base
            oauth._CLIENTS_DIR = base / "clients"
            oauth._CODES_DIR = base / "codes"
            oauth._TOKENS_DIR = base / "tokens"
            try:
                server = oauth.OAuthServer(
                    auth_password="pw", public_hostname="hermes.tail-xxxx.ts.net"
                )
                paths = {(r.path, m) for r in server.get_routes() for m in r.methods}
                for path, method in (
                    ("/register", "POST"),
                    ("/authorize", "GET"),
                    ("/authorize", "POST"),
                    ("/token", "POST"),
                    ("/revoke", "POST"),
                    ("/oauth/register", "POST"),
                    ("/oauth/token", "POST"),
                ):
                    self.assertIn((path, method), paths)
                # RFC 9728 §3.1: el recurso protegido vive en /mcp, así que la
                # URL de sus metadatos lleva ese path tras el .well-known.
                self.assertEqual(
                    server.resource_metadata_url,
                    "https://hermes.tail-xxxx.ts.net"
                    "/.well-known/oauth-protected-resource/mcp",
                )
            finally:
                for a, v in orig.items():
                    setattr(oauth, a, v)


class TestTokenEndpointLogsReason(unittest.IsolatedAsyncioTestCase):
    """Un `POST /oauth/token` rechazado deja el motivo en el log (sin tokens)."""

    async def asyncSetUp(self) -> None:
        import tempfile
        from pathlib import Path

        from hermes import oauth

        self._oauth = oauth
        self._attrs = ("_OAUTH_DIR", "_CLIENTS_DIR", "_CODES_DIR", "_TOKENS_DIR")
        self._orig = {a: getattr(oauth, a) for a in self._attrs}
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name) / "oauth"
        oauth._OAUTH_DIR = base
        oauth._CLIENTS_DIR = base / "clients"
        oauth._CODES_DIR = base / "codes"
        oauth._TOKENS_DIR = base / "tokens"
        self.server = oauth.OAuthServer(auth_password="pw", public_hostname="h.ts.net")
        self.fake = _FakeLogger()
        self._patch = mock.patch.object(oauth, "logger", self.fake)
        self._patch.start()

    async def asyncTearDown(self) -> None:
        self._patch.stop()
        for a, v in self._orig.items():
            setattr(self._oauth, a, v)
        self._tmp.cleanup()

    async def test_unknown_refresh_token_is_logged(self) -> None:
        resp = await self.server._token_refresh(
            {"refresh_token": "nope-secret-value", "client_id": "cid"}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(json.loads(resp.body), {"error": "invalid_grant"})
        logged = self.fake.find("oauth_token_rejected")
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0]["grant"], "refresh_token")
        self.assertEqual(logged[0]["reason"], "unknown_refresh_token")
        self.assertEqual(logged[0]["client_id"], "cid")
        self.assertNotIn("nope-secret-value", json.dumps(logged[0]))

    async def test_unknown_code_is_logged(self) -> None:
        resp = await self.server._token_auth_code(
            {"code": "x", "client_id": "cid", "code_verifier": "v"}
        )
        self.assertEqual(resp.status_code, 400)
        logged = self.fake.find("oauth_token_rejected")
        self.assertEqual(logged[0]["reason"], "unknown_or_used_code")

    async def test_missing_parameters_is_logged(self) -> None:
        resp = await self.server._token_auth_code({"code": "x"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(json.loads(resp.body), {"error": "invalid_request"})
        self.assertEqual(self.fake.find("oauth_token_rejected")[0]["reason"], "missing_parameters")


# ── LoggingMiddleware: motivo de los errores ──────────────────

class TestLoggingMiddlewareErrorBody(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = _FakeLogger()
        self._patch = mock.patch.object(mw, "logger", self.fake)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def _client(self) -> TestClient:
        app = Starlette(
            routes=[
                Route("/mcp", _bad_request, methods=["POST"]),
                Route("/ok", _hi, methods=["GET"]),
                Route("/oauth/token", _bad_request, methods=["POST"]),
            ],
            middleware=[Middleware(LoggingMiddleware)],
        )
        return TestClient(app)

    def test_error_body_and_headers_are_logged(self) -> None:
        resp = self._client().post(
            "/mcp",
            headers={**MCP_HEADERS, "mcp-protocol-version": "2026-07-28",
                     "user-agent": "Claude-User", "authorization": "Bearer secret"},
        )
        self.assertEqual(resp.status_code, 400)
        # El cuerpo llega íntegro al cliente aunque lo hayamos leído para el log
        self.assertEqual(resp.json()["error"]["code"], -32600)

        entries = self.fake.find("http_request")
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["status"], 400)
        self.assertIn("Bad Request: unsupported", entry["error"])
        self.assertEqual(entry["mcp_protocol_version"], "2026-07-28")
        self.assertEqual(entry["user_agent"], "Claude-User")
        self.assertEqual(entry["content_type"], "application/json")
        self.assertNotIn("authorization", json.dumps(entry).lower())

    def test_success_is_logged_without_body(self) -> None:
        resp = self._client().get("/ok")
        self.assertEqual(resp.status_code, 200)
        entry = self.fake.find("http_request")[0]
        self.assertEqual(entry["status"], 200)
        self.assertNotIn("error", entry)
        self.assertNotIn("user_agent", entry)

    def test_public_path_errors_are_not_expanded(self) -> None:
        resp = self._client().post("/oauth/token")
        self.assertEqual(resp.status_code, 400)
        entry = self.fake.find("http_request")[0]
        self.assertNotIn("error", entry)


# ── McpProtocolVersionMiddleware ──────────────────────────────

class TestMcpProtocolVersionMiddleware(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = _FakeLogger()
        self._patch = mock.patch.object(mw, "logger", self.fake)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        app = Starlette(
            routes=[Route("/mcp", _echo, methods=["POST", "GET"])],
            middleware=[Middleware(McpProtocolVersionMiddleware)],
        )
        self.client = TestClient(app)

    def _post(self, body: Any, version: str | None) -> Any:
        headers = dict(MCP_HEADERS)
        if version is not None:
            headers["mcp-protocol-version"] = version
        content = body if isinstance(body, (bytes, str)) else json.dumps(body)
        return self.client.post("/mcp", content=content, headers=headers)

    def test_no_header_passes_through(self) -> None:
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        resp = self._post(body, None)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.text), body)

    def test_supported_version_passes_through(self) -> None:
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        resp = self._post(body, SUPPORTED_VERSION)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["x-echo-version"], SUPPORTED_VERSION)
        self.assertEqual(self.fake.find("mcp_protocol_version_unsupported"), [])

    def test_unsupported_version_is_rejected_with_spec_error(self) -> None:
        body = {"jsonrpc": "2.0", "id": "probe-1", "method": "server/discover",
                "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": UNSUPPORTED_VERSION}}}
        resp = self._post(body, UNSUPPORTED_VERSION)
        self.assertEqual(resp.status_code, 400)
        payload = resp.json()
        self.assertEqual(payload["jsonrpc"], "2.0")
        self.assertEqual(payload["id"], "probe-1")
        self.assertEqual(payload["error"]["code"], -32022)
        self.assertEqual(payload["error"]["data"]["requested"], UNSUPPORTED_VERSION)
        self.assertEqual(payload["error"]["data"]["supported"], list(SUPPORTED_PROTOCOL_VERSIONS))

        logged = self.fake.find("mcp_protocol_version_unsupported")
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0]["requested"], UNSUPPORTED_VERSION)
        self.assertEqual(logged[0]["method"], "server/discover")

    def test_numeric_id_is_echoed(self) -> None:
        resp = self._post({"jsonrpc": "2.0", "id": 7, "method": "tools/list"}, UNSUPPORTED_VERSION)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["id"], 7)

    def test_initialize_passes_through_with_body_intact(self) -> None:
        body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": UNSUPPORTED_VERSION, "capabilities": {},
                           "clientInfo": {"name": "t", "version": "1"}}}
        resp = self._post(body, UNSUPPORTED_VERSION)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.text), body)
        self.assertEqual(self.fake.find("mcp_protocol_version_unsupported"), [])

    def test_malformed_body_still_returns_400(self) -> None:
        resp = self._post(b"{not json", UNSUPPORTED_VERSION)
        self.assertEqual(resp.status_code, 400)
        self.assertIsNone(resp.json()["id"])

    def test_get_is_untouched(self) -> None:
        resp = self.client.get("/mcp", headers={"mcp-protocol-version": UNSUPPORTED_VERSION})
        self.assertEqual(resp.status_code, 200)


# ── Integración con el transporte real del SDK (stateless) ────

class TestAgainstRealStatelessServer(unittest.TestCase):
    """Reproduce el fallo visto en producción contra el SDK real y verifica
    que con el middleware el rechazo es el que define la spec."""

    @staticmethod
    def _build(with_guard: bool) -> Starlette:
        import contextlib

        from mcp.server.mcpserver import MCPServer
        from mcp.server.transport_security import TransportSecuritySettings

        # Misma protección DNS-rebinding que en producción, con el Host que
        # usa el TestClient en lugar del public_hostname. Igual que en
        # __main__: desde el SDK 2.x estos ajustes van en streamable_http_app().
        transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["testserver", "testserver:*"],
            allowed_origins=[],
        )
        server = MCPServer("t")

        @server.tool()
        async def ping() -> str:
            """pong"""
            return "pong"

        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette):
            async with server.session_manager.run():
                yield

        middleware = [Middleware(McpProtocolVersionMiddleware)] if with_guard else []
        from starlette.routing import Mount
        return Starlette(
            routes=[
                Mount(
                    "/",
                    app=server.streamable_http_app(
                        stateless_http=True,
                        transport_security=transport_security,
                    ),
                )
            ],
            middleware=middleware,
            lifespan=lifespan,
        )

    def _discover(self) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": "probe", "method": "server/discover",
                "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": UNSUPPORTED_VERSION,
                                     "io.modelcontextprotocol/clientCapabilities": {}}}}

    # El transporte moderno exige que `mcp-method` coincida con el método del
    # cuerpo; sin ella el SDK 2.x rechaza por eso y nunca llega a mirar la
    # versión, que es lo que aquí se quiere probar.
    _DISCOVER_HEADERS = {**MCP_HEADERS,
                         "mcp-protocol-version": UNSUPPORTED_VERSION,
                         "mcp-method": "server/discover"}

    def test_sdk_alone_now_answers_the_spec_error(self) -> None:
        """Caracteriza al SDK sin nuestro middleware delante.

        En 1.x esto devolvía un `-32600 Bad Request` genérico y sin loguear
        nada: un 400 sin motivo en el log, que es la razón de que exista
        `McpProtocolVersionMiddleware`.

        El SDK 2.x responde por sí solo el error de la spec (-32022) con
        `data.supported` y `data.requested`, así que el middleware ya no tapa
        ningún agujero. Se mantiene porque sigue aportando lo que el SDK no
        hace: el log `mcp_protocol_version_unsupported` con versión, método y
        user-agent, que es lo que permite diagnosticar una reconexión rara sin
        entrar por SSH. Si este test empieza a fallar porque el SDK cambia de
        código, la decisión a revisar es si merece la pena conservarlo.
        """
        with TestClient(self._build(with_guard=False)) as client:
            resp = client.post("/mcp", json=self._discover(),
                               headers=self._DISCOVER_HEADERS)
            self.assertEqual(resp.status_code, 400)
            error = resp.json()["error"]
            self.assertEqual(error["code"], mw.McpProtocolVersionMiddleware.UNSUPPORTED_PROTOCOL_VERSION)
            self.assertEqual(error["data"]["requested"], UNSUPPORTED_VERSION)
            self.assertIn("supported", error["data"])

    def test_guard_answers_spec_error_and_handshake_still_works(self) -> None:
        with TestClient(self._build(with_guard=True)) as client:
            resp = client.post("/mcp", json=self._discover(),
                               headers=self._DISCOVER_HEADERS)
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(resp.json()["error"]["code"], -32022)
            self.assertIn(SUPPORTED_VERSION, resp.json()["error"]["data"]["supported"])

            # Fallback del cliente: handshake clásico → debe seguir funcionando.
            init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": HANDSHAKE_VERSION, "capabilities": {},
                               "clientInfo": {"name": "t", "version": "1"}}}
            resp = client.post("/mcp", json=init, headers=MCP_HEADERS)
            self.assertEqual(resp.status_code, 200)
            self.assertIn("text/event-stream", resp.headers["content-type"])
            self.assertIn('"protocolVersion"', resp.text)

            tools = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
            resp = client.post("/mcp", json=tools,
                               headers={**MCP_HEADERS, "mcp-protocol-version": HANDSHAKE_VERSION})
            self.assertEqual(resp.status_code, 200)
            self.assertIn('"ping"', resp.text)


if __name__ == "__main__":
    unittest.main()
