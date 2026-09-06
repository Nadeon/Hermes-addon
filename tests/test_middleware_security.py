"""Tests del límite de body (incluido chunked) y de las cabeceras de seguridad."""

import unittest

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from hermes.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware


async def _echo(request):
    body = await request.body()
    return PlainTextResponse(f"ok:{len(body)}")


async def _hi(request):
    return PlainTextResponse("hi")


class TestBodySizeLimit(unittest.TestCase):
    def _client(self, max_bytes: int) -> TestClient:
        app = Starlette(
            routes=[Route("/", _echo, methods=["POST"])],
            middleware=[Middleware(BodySizeLimitMiddleware, max_body_bytes=max_bytes)],
        )
        return TestClient(app)

    def test_allows_small_body(self) -> None:
        client = self._client(1000)
        resp = client.post("/", content=b"x" * 100)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "ok:100")

    def test_rejects_large_content_length(self) -> None:
        client = self._client(100)
        resp = client.post("/", content=b"x" * 500)
        self.assertEqual(resp.status_code, 413)

    def test_rejects_large_chunked_without_content_length(self) -> None:
        client = self._client(100)

        def gen():
            # Sin longitud conocida → httpx usa Transfer-Encoding: chunked
            yield b"x" * 500

        resp = client.post("/", content=gen())
        self.assertEqual(resp.status_code, 413)

    def test_allows_get_without_body(self) -> None:
        app = Starlette(
            routes=[Route("/", _hi, methods=["GET"])],
            middleware=[Middleware(BodySizeLimitMiddleware, max_body_bytes=100)],
        )
        resp = TestClient(app).get("/")
        self.assertEqual(resp.status_code, 200)


class TestSecurityHeaders(unittest.TestCase):
    def test_headers_present(self) -> None:
        app = Starlette(
            routes=[Route("/", _hi)],
            middleware=[Middleware(SecurityHeadersMiddleware)],
        )
        resp = TestClient(app).get("/")
        self.assertEqual(resp.headers["x-content-type-options"], "nosniff")
        self.assertEqual(resp.headers["x-frame-options"], "DENY")
        self.assertEqual(resp.headers["referrer-policy"], "no-referrer")
        self.assertIn("content-security-policy", resp.headers)
        self.assertIn("frame-ancestors 'none'", resp.headers["content-security-policy"])
        # `form-action` rompe el redirect OAuth post-login en Chromium: no debe estar.
        self.assertNotIn("form-action", resp.headers["content-security-policy"])


if __name__ == "__main__":
    unittest.main()
