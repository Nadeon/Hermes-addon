"""Tests de seguridad del servidor OAuth: throttle anti-fuerza-bruta del login
y endurecimiento del Dynamic Client Registration."""

import json
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


class TestLoginThrottlePerIp(_OAuthTestBase):
    """Un freno único global convertía el login en un objetivo de denegación
    de servicio: una IP fallando una vez por minuto lo mantenía cerrado para
    el dueño el 100 % del tiempo."""

    async def test_one_ip_cannot_lock_another(self) -> None:
        now = time.time()
        for _ in range(oauth.LOGIN_FAIL_THRESHOLD + 5):
            await self.server._record_login_failure(now, "203.0.113.7")
        self.assertGreater(await self.server._login_lock_remaining(now, "203.0.113.7"), 0)
        self.assertEqual(await self.server._login_lock_remaining(now, "198.51.100.2"), 0)

    async def test_global_backstop_needs_many_distinct_ips(self) -> None:
        now = time.time()
        for i in range(oauth.LOGIN_GLOBAL_FAIL_THRESHOLD - 1):
            await self.server._record_login_failure(now, f"10.0.0.{i}")
        self.assertEqual(await self.server._login_lock_remaining(now, "192.0.2.1"), 0)
        await self.server._record_login_failure(now, "10.0.0.250")
        self.assertGreater(await self.server._login_lock_remaining(now, "192.0.2.1"), 0)

    async def test_owner_success_does_not_free_the_attacker(self) -> None:
        now = time.time()
        for _ in range(oauth.LOGIN_FAIL_THRESHOLD):
            await self.server._record_login_failure(now, "203.0.113.7")
        await self.server._reset_login_throttle("198.51.100.2")
        self.assertGreater(await self.server._login_lock_remaining(now, "203.0.113.7"), 0)

    async def test_per_ip_state_is_bounded(self) -> None:
        now = time.time()
        for i in range(oauth.LOGIN_MAX_TRACKED_IPS + 50):
            await self.server._record_login_failure(now, f"ip-{i}")
        self.assertLessEqual(len(self.server._login_ip_state), oauth.LOGIN_MAX_TRACKED_IPS)


class _FakeFormRequest:
    """Request mínimo para token()/revoke(): solo necesita .form()."""

    def __init__(self, form: dict | None = None) -> None:
        self._form = form or {}
        self.client = None

    async def form(self) -> dict:
        return self._form


def _body(resp) -> dict:
    return json.loads(resp.body)


class TestRefreshRotationGrace(_OAuthTestBase):
    """La ventana de gracia devolvía un access token SIN refresh_token: el
    cliente que perdió la respuesta se quedaba con el viejo, y una hora
    después la cadena entera caía como reutilizada."""

    def _seed_refresh(self) -> str:
        token = oauth._generate_token()
        now = time.time()
        oauth._atomic_write(oauth._TOKENS_DIR / f"{oauth._hash_token(token)}.json", {
            "token_hash": oauth._hash_token(token),
            "token_type": "refresh",
            "client_id": "cid",
            "sub": oauth._FIXED_SUB,
            "scope": "mcp",
            "created_at": now,
            "expires_at": now + oauth.REFRESH_TOKEN_TTL,
            "access_token_hash": "",
        })
        return token

    async def _refresh(self, token: str) -> tuple[int, dict]:
        resp = await self.server._token_refresh({"refresh_token": token, "client_id": "cid"})
        return resp.status_code, _body(resp)

    async def test_replay_within_grace_returns_the_same_successor(self) -> None:
        r1 = self._seed_refresh()
        status, first = await self._refresh(r1)
        self.assertEqual(status, 200)
        r2 = first["refresh_token"]

        status, replay = await self._refresh(r1)
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay.get("refresh_token"), r2,
                         "el reintento debe recibir el sucesor vigente")
        self.assertTrue(await self.server.validate_token(replay["access_token"]))

        # La cadena sigue intacta: el sucesor rota con normalidad.
        status, third = await self._refresh(r2)
        self.assertEqual(status, 200, third)
        self.assertNotEqual(third["refresh_token"], r2)

    async def test_replay_two_rotations_behind_is_reuse(self) -> None:
        r1 = self._seed_refresh()
        _, first = await self._refresh(r1)
        r2 = first["refresh_token"]
        _, second = await self._refresh(r2)
        r3 = second["refresh_token"]

        status, replay = await self._refresh(r1)
        self.assertEqual(status, 400)
        self.assertEqual(replay["error"], "invalid_grant")
        # Y la cadena entera queda revocada, incluida la cabeza.
        status, _ = await self._refresh(r3)
        self.assertEqual(status, 400)

    async def test_sealed_successor_only_opens_with_the_presented_token(self) -> None:
        r1 = self._seed_refresh()
        _, first = await self._refresh(r1)
        record = oauth._safe_read(oauth._TOKENS_DIR / f"{oauth._hash_token(r1)}.json")
        self.assertIn("successor_sealed", record)
        self.assertNotIn(first["refresh_token"], json.dumps(record),
                         "el sucesor no puede estar en claro en disco")
        self.assertEqual(oauth._open_successor(r1, record["successor_sealed"]),
                         first["refresh_token"])
        self.assertIsNone(oauth._open_successor("otro-token", record["successor_sealed"]))

    async def test_revoking_a_rotated_token_kills_the_live_session(self) -> None:
        r1 = self._seed_refresh()
        _, first = await self._refresh(r1)
        r2 = first["refresh_token"]

        resp = await self.server.revoke(_FakeFormRequest({"token": r1}))
        self.assertEqual(resp.status_code, 200)
        status, _ = await self._refresh(r2)
        self.assertEqual(status, 400, "la sesión viva sobrevivió a la revocación")


class TestTokenEndpointHardening(_OAuthTestBase):
    async def test_malformed_code_verifier_is_a_400_not_a_500(self) -> None:
        code = "un-codigo"
        oauth._atomic_write(oauth._CODES_DIR / f"{oauth._hash_token(code)}.json", {
            "client_id": "cid",
            "redirect_uri": "",
            "code_challenge": "x",
            "code_challenge_method": "S256",
            "scope": "mcp",
            "sub": oauth._FIXED_SUB,
            "expires_at": time.time() + 60,
        })
        resp = await self.server._token_auth_code({
            "code": code, "client_id": "cid", "redirect_uri": "",
            "code_verifier": "ñ" * 43,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(_body(resp)["error"], "invalid_grant")

    async def test_token_responses_are_not_cacheable(self) -> None:
        resp = await self.server.token(_FakeFormRequest({"grant_type": "nope"}))
        self.assertEqual(resp.headers.get("cache-control"), "no-store")

    def test_authorization_code_is_not_stored_in_clear(self) -> None:
        fuente = Path(oauth.__file__).read_text(encoding="utf-8")
        self.assertNotIn('"code": code,', fuente)

    async def test_unknown_protected_resource_path_is_404(self) -> None:
        catch_all = [r for r in self.server.get_routes()
                     if r.path == "/.well-known/oauth-protected-resource/{path:path}"]
        self.assertEqual(len(catch_all), 1)
        resp = await catch_all[0].endpoint(None)
        self.assertEqual(resp.status_code, 404)


class TestRedirectQuery(unittest.TestCase):
    def test_keeps_an_existing_query(self) -> None:
        self.assertEqual(
            oauth._append_query("https://claude.ai/cb?tenant=42", {"code": "c", "state": "s"}),
            "https://claude.ai/cb?tenant=42&code=c&state=s",
        )

    def test_plain_uri_gets_a_question_mark(self) -> None:
        self.assertEqual(
            oauth._append_query("https://claude.ai/cb", {"code": "c"}),
            "https://claude.ai/cb?code=c",
        )

    def test_fragment_is_dropped(self) -> None:
        self.assertEqual(
            oauth._append_query("https://claude.ai/cb#frag", {"code": "c"}),
            "https://claude.ai/cb?code=c",
        )


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
