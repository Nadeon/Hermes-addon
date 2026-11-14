"""Flujo OAuth completo con clientes CIMD (Client ID Metadata Documents).

El documento de Claude Code se sirve con un resolvedor simulado o, en el
flujo de extremo a extremo, con `aioresponses` sobre el `CimdResolver` real.
No hay red.
"""

from __future__ import annotations

import hashlib
import json
import socket
import tempfile
import time
import unittest
from base64 import urlsafe_b64encode
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from aioresponses import aioresponses
from structlog.testing import capture_logs

from hermes import oauth
from hermes.cimd import CimdClient, CimdInvalidError, CimdResolver, CimdTemporaryError

HOST = "hermes.example.com"
ISSUER = f"https://{HOST}"
PASSWORD = "test-password-1234"
CLAUDE_CODE_URL = "https://claude.ai/oauth/claude-code-client-metadata"
CLAUDE_CODE_DOC = {
    "client_id": CLAUDE_CODE_URL,
    "client_name": "Claude Code",
    "client_uri": "https://claude.ai",
    "redirect_uris": ["http://localhost/callback", "http://127.0.0.1/callback"],
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "token_endpoint_auth_method": "none",
}
REDIRECT = "http://localhost:41000/callback"

_PATH_ATTRS = ("_OAUTH_DIR", "_CLIENTS_DIR", "_CODES_DIR", "_TOKENS_DIR")


class _FakeResolver:
    """`CimdResolver` simulado: devuelve un cliente o lanza lo que se le diga."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.kwargs: list[dict] = []
        self.pinned: list[str] = []
        self.result: CimdClient | Exception = CimdClient(
            client_id=CLAUDE_CODE_URL,
            client_name="Claude Code",
            redirect_uris=("http://localhost/callback", "http://127.0.0.1/callback"),
            allow_refresh=True,
        )

    async def resolve(self, url: str, *, source: str | None = None,
                      trusted: bool = False) -> CimdClient:
        self.calls.append(url)
        self.kwargs.append({"source": source, "trusted": trusted})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def pin(self, url: str) -> None:
        self.pinned.append(url)


class _Req:
    def __init__(self, *, query: dict | None = None, form: dict | None = None) -> None:
        self.query_params = query or {}
        self._form = form or {}
        self.client = None

    async def form(self) -> dict:
        return self._form


def _pkce() -> tuple[str, str]:
    verifier = "v" * 43
    challenge = urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _body(resp) -> dict:
    return json.loads(resp.body)


class _Base(unittest.IsolatedAsyncioTestCase):
    cimd_enabled = True

    async def asyncSetUp(self) -> None:
        self._orig = {a: getattr(oauth, a) for a in _PATH_ATTRS}
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name) / "oauth"
        oauth._OAUTH_DIR = base
        oauth._CLIENTS_DIR = base / "clients"
        oauth._CODES_DIR = base / "codes"
        oauth._TOKENS_DIR = base / "tokens"
        self.resolver = _FakeResolver()
        self.server = oauth.OAuthServer(
            auth_password=PASSWORD, public_hostname=HOST,
            cimd_enabled=self.cimd_enabled, cimd_resolver=self.resolver,  # type: ignore[arg-type]
        )
        self.verifier, self.challenge = _pkce()

    async def asyncTearDown(self) -> None:
        for a, v in self._orig.items():
            setattr(oauth, a, v)
        self._tmp.cleanup()

    def _params(self, client_id: str = CLAUDE_CODE_URL, redirect_uri: str = REDIRECT,
                **extra: str) -> dict:
        p = {
            "client_id": client_id, "redirect_uri": redirect_uri, "state": "st-1",
            "code_challenge": self.challenge, "code_challenge_method": "S256",
            "scope": "mcp",
        }
        p.update(extra)
        return p

    async def _authorize(self, **kw) -> object:
        form = self._params(**kw)
        form.setdefault("password", PASSWORD)
        return await self.server.authorize_post(_Req(form=form))

    async def _exchange(self, location: str, client_id: str = CLAUDE_CODE_URL,
                        redirect_uri: str = REDIRECT) -> object:
        code = parse_qs(urlsplit(location).query)["code"][0]
        return await self.server.token(_Req(form={
            "grant_type": "authorization_code", "code": code, "client_id": client_id,
            "redirect_uri": redirect_uri, "code_verifier": self.verifier,
        }))

    async def _full_flow(self) -> dict:
        resp = await self._authorize()
        self.assertEqual(resp.status_code, 302, getattr(resp, "body", b""))
        tok = await self._exchange(resp.headers["location"])
        self.assertEqual(tok.status_code, 200, tok.body)
        return _body(tok)

    def _assert_rejected_page(self, resp, mensaje: str) -> None:
        self.assertEqual(resp.status_code, 400)
        self.assertNotIn("location", resp.headers)
        cuerpo = resp.body.decode()
        self.assertNotIn("<form", cuerpo)
        self.assertNotIn('type="password"', cuerpo)
        self.assertIn(mensaje, cuerpo)


# ── T020: metadatos, consentimiento, autorización y rechazos ──


class TestMetadata(_Base):
    async def test_cimd_is_advertised_and_dcr_kept(self) -> None:
        meta = _body(await self.server.authorization_server_metadata(None))
        self.assertIs(meta["client_id_metadata_document_supported"], True)
        self.assertIs(meta["authorization_response_iss_parameter_supported"], True)
        self.assertEqual(meta["registration_endpoint"], f"{ISSUER}/oauth/register")
        self.assertIn("none", meta["token_endpoint_auth_methods_supported"])


class TestMetadataDisabled(_Base):
    cimd_enabled = False

    async def test_not_advertised_when_disabled(self) -> None:
        meta = _body(await self.server.authorization_server_metadata(None))
        self.assertNotIn("client_id_metadata_document_supported", meta)
        self.assertIs(meta["authorization_response_iss_parameter_supported"], True)

    async def test_https_client_id_is_rejected_with_explanation(self) -> None:
        resp = await self.server.authorize_get(_Req(query=self._params()))
        self._assert_rejected_page(
            resp, "Client ID Metadata Documents are disabled on this server")
        resp = await self._authorize()
        self._assert_rejected_page(
            resp, "Client ID Metadata Documents are disabled on this server")
        self.assertEqual(self.resolver.calls, [])

    async def test_dcr_still_works(self) -> None:
        class _JsonReq(_Req):
            async def json(self) -> dict:
                return {"client_name": "Claude",
                        "redirect_uris": ["https://client.example.com/cb"]}

        reg = await self.server.register_client(_JsonReq())
        self.assertEqual(reg.status_code, 201)
        cid = _body(reg)["client_id"]
        resp = await self._authorize(client_id=cid,
                                     redirect_uri="https://client.example.com/cb")
        self.assertEqual(resp.status_code, 302)


class TestConsent(_Base):
    async def test_get_shows_identity_declared_name_destination_and_loopback_warning(self) -> None:
        resp = await self.server.authorize_get(_Req(query=self._params()))
        self.assertEqual(resp.status_code, 200)
        cuerpo = resp.body.decode()
        self.assertIn('<span class="who">claude.ai</span>', cuerpo)
        self.assertIn("nombre declarado por el cliente: «Claude Code»", cuerpo)
        self.assertIn('<span class="dest">http://localhost</span>', cuerpo)
        self.assertIn("aplicación de este mismo dispositivo", cuerpo)
        self.assertIn('type="password"', cuerpo)

    async def test_declared_name_is_escaped(self) -> None:
        self.resolver.result = CimdClient(
            client_id=CLAUDE_CODE_URL, client_name='<script>alert(1)</script>',
            redirect_uris=("http://localhost/callback",), allow_refresh=True)
        cuerpo = (await self.server.authorize_get(_Req(query=self._params()))).body.decode()
        self.assertNotIn("<script>alert", cuerpo)
        self.assertIn("&lt;script&gt;", cuerpo)

    async def test_dcr_consent_unchanged(self) -> None:
        cuerpo = (await self.server.authorize_get(_Req(query=self._params(
            client_id="0b5e6f8a-1111-4222-8333-444455556666",
            redirect_uri="https://client.example.com/cb")))).body.decode()
        self.assertIn("cliente sin nombre", cuerpo)
        self.assertNotIn("nombre declarado", cuerpo)
        self.assertEqual(self.resolver.calls, [])


class TestAuthorizeAndExchange(_Base):
    async def test_full_flow_with_ephemeral_port(self) -> None:
        resp = await self._authorize()
        self.assertEqual(resp.status_code, 302)
        loc = resp.headers["location"]
        self.assertTrue(loc.startswith("http://localhost:41000/callback?"))
        q = parse_qs(urlsplit(loc).query)
        self.assertEqual(q["state"], ["st-1"])
        self.assertEqual(q["iss"], [ISSUER])
        self.assertIn("code", q)
        tok = await self._exchange(loc)
        self.assertEqual(tok.status_code, 200)
        datos = _body(tok)
        self.assertIn("refresh_token", datos)
        self.assertTrue(await self.server.validate_token(datos["access_token"]))
        tokens = [oauth._safe_read(f) for f in oauth._TOKENS_DIR.glob("*.json")]
        self.assertEqual(len(tokens), 2)
        for t in tokens:
            self.assertEqual(t["client_id"], CLAUDE_CODE_URL)
            self.assertEqual(t["resource"], f"{ISSUER}/mcp")

    async def test_code_records_client_kind(self) -> None:
        await self._authorize()
        codes = [oauth._safe_read(f) for f in oauth._CODES_DIR.glob("*.json")]
        self.assertEqual(len(codes), 1)
        self.assertEqual(codes[0]["client_kind"], "cimd")
        self.assertIs(codes[0]["allow_refresh"], True)

    async def test_ipv4_loopback_redirect(self) -> None:
        resp = await self._authorize(redirect_uri="http://127.0.0.1:53127/callback")
        self.assertEqual(resp.status_code, 302)


class TestRejections(_Base):
    async def _check_both(self, mensaje: str, motivo: str, **kw) -> None:
        with capture_logs() as logs:
            get = await self.server.authorize_get(_Req(query=self._params(**kw)))
            # Contraseña incorrecta repetida: no debe contar como fallo de login.
            posts = [await self._authorize(password="mala", **kw)
                     for _ in range(oauth.LOGIN_FAIL_THRESHOLD + 2)]
        self._assert_rejected_page(get, mensaje)
        for p in posts:
            self._assert_rejected_page(p, mensaje)
        self.assertEqual(await self.server._login_lock_remaining(time.time()), 0)
        rechazos = [e for e in logs if e["event"] == "oauth_cimd_rejected"]
        self.assertTrue(rechazos)
        for e in rechazos:
            self.assertEqual(e["reason"], motivo)
            self.assertIn("client_host", e)
            self.assertNotIn("Claude Code", json.dumps(e, default=str))
        self.assertFalse([e for e in logs if e["event"] == "oauth_auth_failed"])
        self.assertEqual(list(oauth._CODES_DIR.glob("*.json")), [])

    async def test_document_unreachable(self) -> None:
        self.resolver.result = CimdTemporaryError("http_503")
        await self._check_both(
            "could not retrieve the client metadata document; try again later", "http_503")

    async def test_document_invalid(self) -> None:
        self.resolver.result = CimdInvalidError("client_id_mismatch")
        await self._check_both("client metadata document is invalid", "client_id_mismatch")

    async def test_forbidden_host(self) -> None:
        self.resolver.result = CimdInvalidError("forbidden_address")
        await self._check_both("client metadata document host is not allowed",
                               "forbidden_address")

    async def test_unregistered_redirect_uri(self) -> None:
        for uri in ("https://attacker.example.com/callback",
                    "http://localhost:41000/other",
                    "http://localhost.evil.example:41000/callback"):
            with self.subTest(redirect_uri=uri):
                await self._check_both("redirect_uri is not registered for this client",
                                       "redirect_uri_mismatch", redirect_uri=uri)

    async def test_bad_shape_is_rejected_without_download(self) -> None:
        await self._check_both("client_id is not an acceptable metadata document URL",
                               "query", client_id=CLAUDE_CODE_URL + "?x=1")
        self.assertEqual(self.resolver.calls, [])

    async def test_own_urls_are_rejected_without_download(self) -> None:
        casos = {
            ISSUER: "no_path",
            f"{ISSUER}/": "no_path",
            f"{ISSUER}/mcp": "own_url",
            f"{ISSUER}/clients/doc.json": "own_url",
            f"https://{HOST.upper()}/doc": "own_url",
        }
        for client_id, motivo in casos.items():
            with self.subTest(client_id=client_id):
                await self._check_both(
                    "client_id is not an acceptable metadata document URL", motivo,
                    client_id=client_id)
        self.assertEqual(self.resolver.calls, [])

    async def test_pkce_still_checked_first(self) -> None:
        resp = await self.server.authorize_get(_Req(query=self._params(code_challenge="")))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.resolver.calls, [])


class TestOwnHostWithPort(_Base):
    async def test_own_host_with_port_is_rejected(self) -> None:
        server = oauth.OAuthServer(
            auth_password=PASSWORD, public_hostname=f"{HOST}:8443",
            cimd_resolver=self.resolver,  # type: ignore[arg-type]
        )
        resp = await server.authorize_get(_Req(query=self._params(
            client_id=f"https://{HOST}/doc")))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.resolver.calls, [])


# ── T021: tokens ──────────────────────────────────────────────


class TestTokens(_Base):
    async def test_no_refresh_when_document_does_not_allow_it(self) -> None:
        self.resolver.result = CimdClient(
            client_id=CLAUDE_CODE_URL, client_name="Claude Code",
            redirect_uris=("http://localhost/callback",), allow_refresh=False)
        datos = await self._full_flow()
        self.assertNotIn("refresh_token", datos)
        tipos = [oauth._safe_read(f)["token_type"] for f in oauth._TOKENS_DIR.glob("*.json")]
        self.assertEqual(tipos, ["access"])
        self.assertTrue(await self.server.validate_token(datos["access_token"]))

    async def _refresh(self, token: str) -> object:
        return await self.server.token(_Req(form={
            "grant_type": "refresh_token", "refresh_token": token,
            "client_id": CLAUDE_CODE_URL,
        }))

    async def test_refresh_with_valid_document(self) -> None:
        datos = await self._full_flow()
        n = len(self.resolver.calls)
        resp = await self._refresh(datos["refresh_token"])
        self.assertEqual(resp.status_code, 200, resp.body)
        self.assertEqual(len(self.resolver.calls), n + 1, "el refresh consulta el documento")
        nuevo = _body(resp)
        self.assertTrue(await self.server.validate_token(nuevo["access_token"]))

    async def test_refresh_with_invalid_document_revokes_the_client(self) -> None:
        for error in (CimdInvalidError("http_404"), CimdInvalidError("client_id_mismatch")):
            with self.subTest(reason=error.reason):
                for f in oauth._TOKENS_DIR.glob("*.json"):
                    f.unlink()
                self.resolver.result = CimdClient(
                    client_id=CLAUDE_CODE_URL, client_name="Claude Code",
                    redirect_uris=("http://localhost/callback",), allow_refresh=True)
                uno = await self._full_flow()
                dos = await self._full_flow()  # otro dispositivo, mismo client_id
                self.resolver.result = error
                with capture_logs() as logs:
                    resp = await self._refresh(uno["refresh_token"])
                self.assertEqual(resp.status_code, 401)
                self.assertEqual(_body(resp), {"error": "invalid_client"})
                self.assertEqual(list(oauth._TOKENS_DIR.glob("*.json")), [],
                                 "deben caer todas las sesiones del cliente")
                self.assertFalse(await self.server.validate_token(dos["access_token"]))
                self.assertIn("oauth_cimd_rejected", [e["event"] for e in logs])

    async def test_refresh_with_temporary_failure_is_503_and_keeps_sessions(self) -> None:
        datos = await self._full_flow()
        self.resolver.result = CimdTemporaryError("timeout")
        resp = await self._refresh(datos["refresh_token"])
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(_body(resp), {"error": "temporarily_unavailable"})
        self.assertTrue(await self.server.validate_token(datos["access_token"]))

    async def test_refresh_when_document_drops_refresh_grant(self) -> None:
        datos = await self._full_flow()
        self.resolver.result = CimdClient(
            client_id=CLAUDE_CODE_URL, client_name="Claude Code",
            redirect_uris=("http://localhost/callback",), allow_refresh=False)
        resp = await self._refresh(datos["refresh_token"])
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(_body(resp), {"error": "unauthorized_client"})

    async def test_two_devices_with_the_same_client_id_stay_alive(self) -> None:
        uno = await self._full_flow()
        dos = await self._full_flow()
        self.assertTrue(await self.server.validate_token(uno["access_token"]))
        self.assertTrue(await self.server.validate_token(dos["access_token"]))
        for d in (uno, dos):
            resp = await self._refresh(d["refresh_token"])
            self.assertEqual(resp.status_code, 200, resp.body)

    async def test_global_session_cap_still_applies(self) -> None:
        for _ in range(oauth.MAX_ACTIVE_SESSIONS + 2):
            await self._full_flow()
            time.sleep(0.001)
        vivas = [d for d in (oauth._safe_read(f) for f in oauth._TOKENS_DIR.glob("*.json"))
                 if d and d["token_type"] == "refresh"]
        self.assertEqual(len(vivas), oauth.MAX_ACTIVE_SESSIONS)


class TestRefreshCimdDisabled(_Base):
    async def test_refresh_rejected_when_cimd_disabled_later(self) -> None:
        datos = await self._full_flow()
        apagado = oauth.OAuthServer(
            auth_password=PASSWORD, public_hostname=HOST, cimd_enabled=False,
            cimd_resolver=self.resolver,  # type: ignore[arg-type]
        )
        n = len(self.resolver.calls)
        resp = await apagado.token(_Req(form={
            "grant_type": "refresh_token", "refresh_token": datos["refresh_token"],
        }))
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(len(self.resolver.calls), n)


# ── Extremo a extremo con el resolvedor real ─────────────────


class TestEndToEndWithRealResolver(_Base):
    async def test_flow_with_mocked_http(self) -> None:
        async def gai(host, port, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", port))]

        real = CimdResolver(getaddrinfo=gai)
        self.server._cimd = real
        with aioresponses() as m:
            m.get(CLAUDE_CODE_URL, body=json.dumps(CLAUDE_CODE_DOC),
                  headers={"Cache-Control": "max-age=3600"})
            get = await self.server.authorize_get(_Req(query=self._params()))
            self.assertEqual(get.status_code, 200)
            post = await self._authorize()
            self.assertEqual(post.status_code, 302)
            tok = await self._exchange(post.headers["location"])
            self.assertEqual(tok.status_code, 200)
            # GET, POST y refresh comparten una sola descarga gracias a la caché.
            ref = await self.server.token(_Req(form={
                "grant_type": "refresh_token",
                "refresh_token": _body(tok)["refresh_token"],
            }))
            self.assertEqual(ref.status_code, 200)
            self.assertEqual(sum(len(v) for v in m.requests.values()), 1)


if __name__ == "__main__":
    unittest.main()
