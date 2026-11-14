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


class _FakeQueryRequest:
    """Request mínimo para authorize_get: solo necesita .query_params."""

    def __init__(self, params: dict | None = None) -> None:
        self.query_params = params or {}
        self.client = None


def _pkce_pair() -> tuple[str, str]:
    import hashlib
    from base64 import urlsafe_b64encode
    verifier = "v" * 43
    challenge = urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class TestPkceBeforePassword(_OAuthTestBase):
    """Un cliente sin PKCE no puede terminar el flujo: no debe costarle al
    dueño ni la contraseña ni un fallo en el freno anti-fuerza-bruta."""

    async def test_get_without_pkce_shows_no_password_form(self) -> None:
        resp = await self.server.authorize_get(_FakeQueryRequest({
            "client_id": "cid", "redirect_uri": "https://claude.ai/cb", "state": "s",
        }))
        self.assertEqual(resp.status_code, 400)
        self.assertNotIn("<form", resp.body.decode())

    async def test_post_without_pkce_is_rejected_before_the_password_counts(self) -> None:
        for _ in range(oauth.LOGIN_FAIL_THRESHOLD + 3):
            resp = await self.server.authorize_post(_FakeFormRequest({
                "password": "incorrecta", "client_id": "cid",
                "redirect_uri": "https://claude.ai/cb",
            }))
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(_body(resp)["error"], "invalid_request")
        self.assertEqual(
            await self.server._login_lock_remaining(time.time(), "unknown"), 0,
            "un cliente sin PKCE no debe consumir intentos del freno del login",
        )


class TestResourceIndicator(_OAuthTestBase):
    """RFC 8707: el único recurso es el servidor MCP; cualquier otro se rechaza."""

    async def test_foreign_resource_is_rejected_at_authorize(self) -> None:
        _, challenge = _pkce_pair()
        resp = await self.server.authorize_post(_FakeFormRequest({
            "password": "test-password-1234", "client_id": "cid",
            "redirect_uri": "https://claude.ai/cb",
            "code_challenge": challenge, "code_challenge_method": "S256",
            "resource": "https://otro.example/mcp",
        }))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(_body(resp)["error"], "invalid_target")

    async def test_own_resource_is_accepted_and_recorded_in_the_code(self) -> None:
        reg = await self.server.register_client(_FakeRequest({
            "client_name": "Claude", "redirect_uris": ["https://claude.ai/cb"],
        }))
        client_id = _body(reg)["client_id"]
        _, challenge = _pkce_pair()
        resp = await self.server.authorize_post(_FakeFormRequest({
            "password": "test-password-1234", "client_id": client_id,
            "redirect_uri": "https://claude.ai/cb",
            "code_challenge": challenge, "code_challenge_method": "S256",
            "resource": "https://hermes.tail-xxxx.ts.net/mcp/",
        }))
        self.assertEqual(resp.status_code, 302, getattr(resp, "body", b""))
        codes = list(oauth._CODES_DIR.glob("*.json"))
        self.assertEqual(len(codes), 1)
        self.assertEqual(oauth._safe_read(codes[0])["resource"],
                         "https://hermes.tail-xxxx.ts.net/mcp")

    async def test_foreign_resource_is_rejected_at_token(self) -> None:
        resp = await self.server.token(_FakeFormRequest({
            "grant_type": "authorization_code", "code": "c", "client_id": "cid",
            "code_verifier": "v" * 43, "resource": "https://otro.example/mcp",
        }))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(_body(resp)["error"], "invalid_target")
        resp = await self.server.token(_FakeFormRequest({
            "grant_type": "refresh_token", "refresh_token": "r",
            "resource": "https://otro.example/mcp",
        }))
        self.assertEqual(_body(resp)["error"], "invalid_target")


class TestTokenEndpointRedirectUri(_OAuthTestBase):
    async def test_omitting_redirect_uri_is_logged_but_still_accepted(self) -> None:
        from structlog.testing import capture_logs
        verifier, challenge = _pkce_pair()
        code = "codigo-de-prueba"
        oauth._atomic_write(oauth._CODES_DIR / f"{oauth._hash_token(code)}.json", {
            "client_id": "cid", "redirect_uri": "https://claude.ai/cb",
            "code_challenge": challenge, "code_challenge_method": "S256",
            "scope": "mcp", "sub": oauth._FIXED_SUB,
            "expires_at": time.time() + 60,
        })
        with capture_logs() as logs:
            resp = await self.server._token_auth_code({
                "code": code, "client_id": "cid", "code_verifier": verifier,
            })
        self.assertEqual(resp.status_code, 200, _body(resp))
        self.assertIn("oauth_token_redirect_uri_omitted", [e["event"] for e in logs])


class TestAuthorizationServerMetadataWithPath(_OAuthTestBase):
    async def test_path_inserted_form_is_served(self) -> None:
        rutas = [r for r in self.server.get_routes()
                 if r.path == "/.well-known/oauth-authorization-server/mcp"]
        self.assertEqual(len(rutas), 1)
        resp = await rutas[0].endpoint(None)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_body(resp)["issuer"], "https://hermes.tail-xxxx.ts.net")


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


class TestPasswordChangeRevokesSessions(_OAuthTestBase):
    """Cambiar `auth_password` no cerraba ninguna sesión: los tokens solo
    dependen de la contraseña en el login, así que las sesiones abiertas
    seguían vivas sus 7 días. Justo lo contrario de lo que espera quien la
    cambia porque sospecha que se la han visto."""

    def _seed(self) -> tuple[Path, Path, Path]:
        now = time.time()
        refresh = oauth._TOKENS_DIR / "r.json"
        access = oauth._TOKENS_DIR / "a.json"
        code = oauth._CODES_DIR / "c.json"
        for ruta, tipo in ((refresh, "refresh"), (access, "access")):
            oauth._atomic_write(ruta, {
                "token_type": tipo, "client_id": "cid", "sub": oauth._FIXED_SUB,
                "created_at": now, "expires_at": now + 3600,
            })
        oauth._atomic_write(code, {"client_id": "cid", "expires_at": now + 60})
        return refresh, access, code

    def _rearrancar(self, password: str) -> None:
        self.server = oauth.OAuthServer(
            auth_password=password, public_hostname="hermes.tail-xxxx.ts.net",
        )

    async def test_new_password_revokes_every_session_and_pending_code(self) -> None:
        from structlog.testing import capture_logs

        refresh, access, code = self._seed()
        with capture_logs() as logs:
            self._rearrancar("otra-password-distinta-9876")
        eventos = [e for e in logs if e["event"] == "oauth_sessions_revoked_password_changed"]
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["tokens_revoked"], 2)
        self.assertFalse(refresh.exists())
        self.assertFalse(access.exists())
        self.assertFalse(code.exists(), "un código emitido con la contraseña vieja tampoco vale")

    async def test_same_password_keeps_sessions(self) -> None:
        refresh, access, code = self._seed()
        self._rearrancar("test-password-1234")
        self.assertTrue(refresh.exists())
        self.assertTrue(access.exists())
        self.assertTrue(code.exists())

    async def test_first_start_without_fingerprint_keeps_sessions(self) -> None:
        """Al actualizar desde una versión que no guardaba la huella no hay con
        qué comparar: no se cierra nada, o actualizar obligaría a todo el mundo
        a autorizar de nuevo."""
        (oauth._OAUTH_DIR / oauth._PASSWORD_FINGERPRINT_FILE).unlink()
        refresh, access, _ = self._seed()
        self._rearrancar("otra-password-distinta-9876")
        self.assertTrue(refresh.exists())
        self.assertTrue(access.exists())
        # Y desde ahí ya compara: volver a cambiarla sí cierra.
        self._rearrancar("tercera-password-larga-5555")
        self.assertFalse(refresh.exists())

    async def test_unreadable_fingerprint_counts_as_change(self) -> None:
        (oauth._OAUTH_DIR / oauth._PASSWORD_FINGERPRINT_FILE).write_text("{roto", encoding="utf-8")
        refresh, _, _ = self._seed()
        self._rearrancar("test-password-1234")
        self.assertFalse(refresh.exists())

    async def test_fingerprint_never_stores_the_password(self) -> None:
        contenido = (oauth._OAUTH_DIR / oauth._PASSWORD_FINGERPRINT_FILE).read_text(encoding="utf-8")
        self.assertNotIn("test-password-1234", contenido)
        datos = json.loads(contenido)
        self.assertEqual(datos["algorithm"], "scrypt")
        self.assertEqual(len(bytes.fromhex(datos["salt"])), 16)

    async def test_fingerprint_failure_never_blocks_startup(self) -> None:
        """Si la huella no se puede calcular o guardar, Hermes arranca igual:
        perder el cierre de sesiones es menos grave que no arrancar."""
        from unittest.mock import patch
        from structlog.testing import capture_logs

        with patch.object(oauth.hashlib, "scrypt", side_effect=ValueError("sin scrypt")), \
                capture_logs() as logs:
            self._rearrancar("otra-password-distinta-9876")
        self.assertIsNotNone(self.server)
        self.assertIn("oauth_password_fingerprint_failed", [e["event"] for e in logs])


# ── 1.1.0: `iss` en la redirección (RFC 9207) ─────────────────


class TestIssParameter(_OAuthTestBase):
    """Toda redirección de éxito lleva `iss`, igual carácter a carácter al
    `issuer` de los metadatos; ningún error redirige."""

    async def _register(self, server, redirect_uri: str) -> str:
        reg = await server.register_client(_FakeRequest({
            "client_name": "Claude", "redirect_uris": [redirect_uri],
        }))
        return _body(reg)["client_id"]

    async def _authorize(self, server, client_id: str, redirect_uri: str, **extra):
        _, challenge = _pkce_pair()
        form = {
            "password": "test-password-1234", "client_id": client_id,
            "redirect_uri": redirect_uri, "state": "s1",
            "code_challenge": challenge, "code_challenge_method": "S256",
        }
        form.update(extra)
        return await server.authorize_post(_FakeFormRequest(form))

    async def test_dcr_success_carries_iss_equal_to_issuer(self) -> None:
        from urllib.parse import parse_qs, urlsplit

        for host in ("hermes.tail-xxxx.ts.net", "homeassistant.tailXXXX.ts.net:8443"):
            with self.subTest(public_hostname=host):
                server = oauth.OAuthServer(auth_password="test-password-1234",
                                           public_hostname=host)
                issuer = _body(await server.authorization_server_metadata(None))["issuer"]
                cid = await self._register(server, "https://client.example.com/cb")
                resp = await self._authorize(server, cid, "https://client.example.com/cb")
                self.assertEqual(resp.status_code, 302)
                q = parse_qs(urlsplit(resp.headers["location"]).query)
                self.assertEqual(q["iss"], [issuer])
                self.assertEqual(q["iss"][0], f"https://{host}")

    async def test_existing_query_is_kept_and_iss_added_once(self) -> None:
        from urllib.parse import parse_qs, urlsplit

        uri = "https://client.example.com/cb?tenant=42"
        cid = await self._register(self.server, uri)
        resp = await self._authorize(self.server, cid, uri)
        self.assertEqual(resp.status_code, 302)
        loc = resp.headers["location"]
        self.assertTrue(loc.startswith("https://client.example.com/cb?tenant=42&"))
        q = parse_qs(urlsplit(loc).query)
        self.assertEqual(q["tenant"], ["42"])
        self.assertEqual(len(q["iss"]), 1)
        self.assertEqual(loc.count("iss="), 1)

    async def test_metadata_advertises_iss_support(self) -> None:
        meta = _body(await self.server.authorization_server_metadata(None))
        self.assertIs(meta["authorization_response_iss_parameter_supported"], True)

    async def test_errors_never_redirect(self) -> None:
        cid = await self._register(self.server, "https://client.example.com/cb")
        casos = {
            "sin PKCE": (cid, "https://client.example.com/cb",
                         {"code_challenge": "", "code_challenge_method": ""}),
            "resource ajeno": (cid, "https://client.example.com/cb",
                               {"resource": "https://otro.example/mcp"}),
            "cliente desconocido": ("0b5e6f8a-1111-4222-8333-444455556666",
                                    "https://client.example.com/cb", {}),
            "redirect_uri no registrado": (cid, "https://attacker.example.com/cb", {}),
        }
        for nombre, (client_id, uri, extra) in casos.items():
            with self.subTest(caso=nombre):
                resp = await self._authorize(self.server, client_id, uri, **extra)
                self.assertFalse(300 <= resp.status_code < 400, resp.status_code)
                self.assertNotIn("location", resp.headers)


# ── 1.1.0: recurso protegido, audiencia y compatibilidad ──────


class TestAudienceAndCompat(_OAuthTestBase):
    RESOURCE = "https://hermes.tail-xxxx.ts.net/mcp"

    async def test_protected_resource_advertises_scopes(self) -> None:
        meta = _body(await self.server.protected_resource_metadata(None))
        self.assertEqual(meta["scopes_supported"], ["mcp"])
        self.assertEqual(meta["resource"], self.RESOURCE)

    async def _issue_tokens(self) -> dict:
        from urllib.parse import parse_qs, urlsplit

        reg = await self.server.register_client(_FakeRequest({
            "client_name": "Claude", "redirect_uris": ["https://client.example.com/cb"],
        }))
        cid = _body(reg)["client_id"]
        verifier, challenge = _pkce_pair()
        resp = await self.server.authorize_post(_FakeFormRequest({
            "password": "test-password-1234", "client_id": cid,
            "redirect_uri": "https://client.example.com/cb",
            "code_challenge": challenge, "code_challenge_method": "S256",
        }))
        code = parse_qs(urlsplit(resp.headers["location"]).query)["code"][0]
        tok = await self.server._token_auth_code({
            "code": code, "client_id": cid, "code_verifier": verifier,
            "redirect_uri": "https://client.example.com/cb",
        })
        self.assertEqual(tok.status_code, 200, tok.body)
        return _body(tok)

    async def test_issued_tokens_carry_the_canonical_resource(self) -> None:
        datos = await self._issue_tokens()
        for valor in (datos["access_token"], datos["refresh_token"]):
            rec = oauth._safe_read(oauth._TOKENS_DIR / f"{oauth._hash_token(valor)}.json")
            self.assertEqual(rec["resource"], self.RESOURCE)

    def _seed(self, token_type: str, **extra) -> str:
        token = oauth._generate_token()
        now = time.time()
        data = {
            "token_hash": oauth._hash_token(token), "token_type": token_type,
            "client_id": "cid", "sub": oauth._FIXED_SUB, "scope": "mcp",
            "created_at": now, "expires_at": now + 3600,
        }
        data.update(extra)
        oauth._atomic_write(oauth._TOKENS_DIR / f"{oauth._hash_token(token)}.json", data)
        return token

    async def test_token_for_another_resource_is_rejected(self) -> None:
        otro = self._seed("access", resource="https://otro.example/mcp")
        self.assertFalse(await self.server.validate_token(otro))
        propio = self._seed("access", resource=self.RESOURCE)
        self.assertTrue(await self.server.validate_token(propio))

    async def test_tokens_from_1_0_12_without_resource_still_work(self) -> None:
        acceso = self._seed("access")
        self.assertTrue(await self.server.validate_token(acceso))
        refresh = self._seed("refresh", access_token_hash="")
        resp = await self.server._token_refresh({"refresh_token": refresh})
        self.assertEqual(resp.status_code, 200, resp.body)
        nuevo = _body(resp)
        for valor in (nuevo["access_token"], nuevo["refresh_token"]):
            rec = oauth._safe_read(oauth._TOKENS_DIR / f"{oauth._hash_token(valor)}.json")
            self.assertEqual(rec["resource"], self.RESOURCE)
        self.assertTrue(await self.server.validate_token(nuevo["access_token"]))

    async def test_live_code_from_1_0_12_is_exchanged_as_dcr_with_refresh(self) -> None:
        verifier, challenge = _pkce_pair()
        code = "codigo-de-la-1012"
        oauth._atomic_write(oauth._CODES_DIR / f"{oauth._hash_token(code)}.json", {
            "client_id": "cid", "redirect_uri": "https://client.example.com/cb",
            "code_challenge": challenge, "code_challenge_method": "S256",
            "scope": "mcp", "sub": oauth._FIXED_SUB, "resource": self.RESOURCE,
            "expires_at": time.time() + 60,
        })
        resp = await self.server._token_auth_code({
            "code": code, "client_id": "cid", "code_verifier": verifier,
            "redirect_uri": "https://client.example.com/cb",
        })
        self.assertEqual(resp.status_code, 200, resp.body)
        self.assertIn("refresh_token", _body(resp))

    async def test_dcr_client_id_is_uuid_and_redirect_is_exact(self) -> None:
        import uuid as _uuid

        reg = await self.server.register_client(_FakeRequest({
            "client_name": "App", "redirect_uris": ["http://localhost/callback"],
        }))
        cid = _body(reg)["client_id"]
        self.assertEqual(str(_uuid.UUID(cid)), cid)
        self.assertFalse(cid.startswith("https://"))
        _, challenge = _pkce_pair()
        # DCR no tiene la excepción de loopback de CIMD: otro puerto no vale.
        resp = await self.server.authorize_post(_FakeFormRequest({
            "password": "test-password-1234", "client_id": cid,
            "redirect_uri": "http://localhost:41000/callback",
            "code_challenge": challenge, "code_challenge_method": "S256",
        }))
        self.assertNotEqual(resp.status_code, 302)
