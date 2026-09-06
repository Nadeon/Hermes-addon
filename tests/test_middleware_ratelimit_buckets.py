"""El rate limit no puede depender de nada que el cliente pueda inventarse.

El primer intento de arreglo estaba mal; este es el segundo.

Al principio `RateLimitPreAuth` contaba TODAS las requests. Tras el proxy todas
llegan de la misma IP, así que su límite (20/min) era el techo global real y
`mcp_max_requests_per_minute` (120) nunca se aplicaba. Medido entonces contra
producción: 16 llamadas en paralelo → 3 con éxito; 24 → 0.

El arreglo siguiente separaba los cubos según si la request traía
`Authorization: Bearer`. La revisión posterior demostró que eso seguía
mal, y por un motivo peor que el original:

  1. El discriminante lo elige el atacante: basta añadir `Bearer basura` para
     saltar del cubo estricto al caro. En los endpoints OAuth nadie valida ese
     token aguas abajo, así que el techo de fuerza bruta contra la password
     pasaba de 20 a 120 intentos/min.
  2. Tras el proxy el atacante y el dueño compartían la MISMA clave de cubo.
     Cinco peticiones con un bearer inválido lo agotaban y el dueño recibía 429
     con su token bueno: denegación de servicio por alguien sin credenciales.

Diseño actual: la clave del cubo la decide la RUTA, no la cabecera. Las rutas
públicas tienen cupo estricto; las protegidas no se limitan aquí, sino después
de autenticar (`RateLimitPostAuth`), y los fallos de autenticación van a un cubo
propio para que un flood de tokens basura no toque el cupo del dueño.
"""

from __future__ import annotations

import json
import unittest

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from hermes import middleware as mw
from hermes.middleware import RATE_LIMITED, RateLimitPreAuth


def _app(max_per_minute: int = 3) -> TestClient:
    async def ok(request):  # noqa: ANN001
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[
            Route("/mcp", ok, methods=["GET", "POST"]),
            Route("/oauth/token", ok, methods=["GET", "POST"]),
            Route("/oauth/authorize", ok, methods=["GET", "POST"]),
        ],
        middleware=[Middleware(RateLimitPreAuth, max_per_minute=max_per_minute)],
    )
    return TestClient(app)


_BEARER = {"Authorization": "Bearer token-de-prueba"}


class TestBucketKeyIsNotAttackerControlled(unittest.TestCase):
    """El núcleo del arreglo: la cabecera no puede cambiar de cubo."""

    def test_garbage_bearer_does_not_raise_the_public_ceiling(self) -> None:
        """Antes: `Bearer basura` multiplicaba por 6 el techo del login."""
        client = _app(max_per_minute=3)
        codes = [
            client.post("/oauth/authorize", headers={"Authorization": "Bearer basura"},
                        json={}).status_code
            for _ in range(6)
        ]
        self.assertEqual(codes.count(200), 3, f"el cupo público debe seguir siendo 3: {codes}")
        self.assertEqual(codes.count(429), 3)

    def test_public_ceiling_is_the_same_with_and_without_header(self) -> None:
        con = [_app(max_per_minute=2).post("/oauth/token", headers=_BEARER, json={}).status_code
               for _ in range(4)]
        sin = [_app(max_per_minute=2).post("/oauth/token", json={}).status_code
               for _ in range(4)]
        self.assertEqual(con.count(200), sin.count(200))

    def test_attacker_cannot_evict_the_owner(self) -> None:
        """El núcleo de la parte grave: quien no tiene credenciales no puede
        gastarle el cupo al dueño.

        Antes, el atacante y el dueño compartían la clave `127.0.0.1|bearer`,
        así que unas pocas peticiones con un bearer inválido dejaban al dueño
        fuera. Ahora las rutas protegidas no se limitan aquí en absoluto.
        """
        client = _app(max_per_minute=2)
        for _ in range(10):
            client.post("/mcp", headers={"Authorization": "Bearer basura"}, json={})
        resp = client.post("/mcp", headers=_BEARER, json={})
        self.assertEqual(resp.status_code, 200,
                         "el dueño no puede quedar fuera por el ruido de un atacante")


class TestPublicSurfaceStillLimited(unittest.TestCase):
    def test_oauth_endpoints_are_limited(self) -> None:
        client = _app(max_per_minute=3)
        for _ in range(3):
            self.assertEqual(client.post("/oauth/token", json={}).status_code, 200)
        self.assertEqual(client.post("/oauth/token", json={}).status_code, 429)

    def test_protected_paths_are_not_limited_here(self) -> None:
        """Las gobierna RateLimitPostAuth, después de autenticar."""
        client = _app(max_per_minute=2)
        codes = [client.post("/mcp", headers=_BEARER, json={}).status_code for _ in range(16)]
        self.assertEqual(codes.count(200), 16, f"ráfaga legítima rechazada: {codes}")


class TestAuthFailureBucket(unittest.TestCase):
    """Un flood de tokens basura sigue acotado, pero en su propio cubo."""

    def setUp(self) -> None:
        mw._AUTH_FAILURE_BUCKET.clear()

    def test_counts_and_trips(self) -> None:
        for i in range(3):
            self.assertFalse(mw.record_auth_failure("1.2.3.4", max_per_minute=3),
                             f"no debería cortar en el intento {i + 1}")
        self.assertTrue(mw.record_auth_failure("1.2.3.4", max_per_minute=3))

    def test_is_independent_per_client(self) -> None:
        for _ in range(4):
            mw.record_auth_failure("1.2.3.4", max_per_minute=3)
        self.assertFalse(mw.record_auth_failure("5.6.7.8", max_per_minute=3))


class TestRateLimitResponseIsReadable(unittest.TestCase):
    """El 429 debe decir por qué, o el cliente lo reporta como fallo de red."""

    def test_oauth_endpoint_keeps_the_plain_body(self) -> None:
        client = _app(max_per_minute=1)
        client.post("/oauth/token", json={})
        resp = client.post("/oauth/token", json={})
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.headers.get("Retry-After"), "60")
        self.assertEqual(json.loads(resp.content), {"error": "too_many_requests"})

    def test_mcp_endpoint_returns_a_jsonrpc_error(self) -> None:
        """El cuerpo JSON-RPC se emite en el endpoint MCP (lo usa el cubo de
        fallos de auth y RateLimitPostAuth)."""
        from starlette.requests import Request

        scope = {"type": "http", "method": "POST", "path": "/mcp",
                 "headers": [], "query_string": b""}
        resp = mw._too_many_requests(Request(scope))
        self.assertEqual(resp.status_code, 429)
        body = json.loads(resp.body)
        self.assertEqual(body["jsonrpc"], "2.0")
        self.assertEqual(body["error"]["code"], RATE_LIMITED)
        self.assertIn("retry_after_seconds", body["error"]["data"])


if __name__ == "__main__":
    unittest.main()
