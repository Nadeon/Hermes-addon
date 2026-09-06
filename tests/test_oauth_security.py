"""Tests de seguridad del servidor OAuth: throttle anti-fuerza-bruta del login
y endurecimiento del Dynamic Client Registration."""

import tempfile
import time
import unittest
from pathlib import Path

from hermes import oauth

_PATH_ATTRS = (
    "_OAUTH_DIR",
    "_CLIENTS_DIR",
    "_CODES_DIR",
    "_TOKENS_DIR",
)


class _FakeRequest:
    """Request mínimo para register_client: solo necesita .json()."""

    def __init__(self, json_body: dict | None = None) -> None:
        self._json = json_body or {}

    async def json(self) -> dict:
        return self._json


def _point_oauth_paths_to(base: Path) -> None:
    oauth._OAUTH_DIR = base
    oauth._CLIENTS_DIR = base / "clients"
    oauth._CODES_DIR = base / "codes"
    oauth._TOKENS_DIR = base / "tokens"


class _OAuthTestBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._orig = {attr: getattr(oauth, attr) for attr in _PATH_ATTRS}
        self._tmp = tempfile.TemporaryDirectory()
        _point_oauth_paths_to(Path(self._tmp.name) / "oauth")
        self.server = oauth.OAuthServer(
            auth_password="test-password-1234",
            public_hostname="hermes.tail-xxxx.ts.net",
        )

    async def asyncTearDown(self) -> None:
        for attr, value in self._orig.items():
            setattr(oauth, attr, value)
        self._tmp.cleanup()


class TestLoginThrottle(_OAuthTestBase):
    async def test_not_locked_initially(self) -> None:
        self.assertEqual(await self.server._login_lock_remaining(time.time()), 0)

    async def test_locks_after_threshold(self) -> None:
        now = time.time()
        for _ in range(oauth.LOGIN_FAIL_THRESHOLD):
            await self.server._record_login_failure(now)
        self.assertGreater(await self.server._login_lock_remaining(now), 0)

    async def test_reset_clears_lock(self) -> None:
        now = time.time()
        for _ in range(oauth.LOGIN_FAIL_THRESHOLD + 2):
            await self.server._record_login_failure(now)
        self.assertGreater(await self.server._login_lock_remaining(now), 0)
        await self.server._reset_login_throttle()
        self.assertEqual(await self.server._login_lock_remaining(now), 0)

    async def test_backoff_is_monotonic(self) -> None:
        now = time.time()
        for _ in range(oauth.LOGIN_FAIL_THRESHOLD):
            await self.server._record_login_failure(now)
        first = await self.server._login_lock_remaining(now)
        await self.server._record_login_failure(now)
        second = await self.server._login_lock_remaining(now)
        self.assertGreaterEqual(second, first)


class TestDCRHardening(_OAuthTestBase):
    async def test_rejects_javascript_redirect(self) -> None:
        resp = await self.server.register_client(
            _FakeRequest({"redirect_uris": ["javascript:alert(1)"], "client_name": "x"})
        )
        self.assertEqual(resp.status_code, 400)

    async def test_rejects_data_redirect(self) -> None:
        resp = await self.server.register_client(
            _FakeRequest({"redirect_uris": ["data:text/html,<script>"]})
        )
        self.assertEqual(resp.status_code, 400)

    async def test_rejects_file_redirect(self) -> None:
        resp = await self.server.register_client(
            _FakeRequest({"redirect_uris": ["file:///etc/passwd"]})
        )
        self.assertEqual(resp.status_code, 400)

    async def test_accepts_https_redirect(self) -> None:
        resp = await self.server.register_client(
            _FakeRequest(
                {
                    "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
                    "client_name": "Claude",
                }
            )
        )
        self.assertEqual(resp.status_code, 201)

    async def test_requires_redirect_uris(self) -> None:
        resp = await self.server.register_client(_FakeRequest({"client_name": "x"}))
        self.assertEqual(resp.status_code, 400)

    async def test_client_limit_is_enforced(self) -> None:
        for i in range(oauth.MAX_REGISTERED_CLIENTS + 5):
            await self.server.register_client(
                _FakeRequest({"redirect_uris": [f"https://c{i}.example/cb"]})
            )
        count = len(list(oauth._CLIENTS_DIR.glob("*.json")))
        self.assertLessEqual(count, oauth.MAX_REGISTERED_CLIENTS)


class TestTokenValidation(_OAuthTestBase):
    async def test_unknown_token_is_invalid(self) -> None:
        self.assertFalse(await self.server.validate_token("does-not-exist"))


if __name__ == "__main__":
    unittest.main()
