"""Regresiones de la revisión de seguridad independiente de Hermes 1.1.0.

Cada clase cubre un hallazgo (ALTO-1, MEDIO-1, MEDIO-2 y los BAJO) y lleva
su control negativo: la comprobación de que el test SÍ detectaría el fallo,
para que un test que pasa no pase porque no mira nada.

Sin red real: DNS falso, `aioresponses` y espías sobre el bucle de eventos.
Solo dominios de ejemplo e IPs de documentación (RFC 5737 / RFC 3849).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path
from typing import Any

import aiohappyeyeballs
import aiohttp
from aioresponses import aioresponses
from structlog.testing import capture_logs

from hermes import cimd, oauth
from hermes import logging_setup
from hermes import safety_retention as sr
from hermes.cimd import (
    CimdInvalidError,
    CimdResolver,
    CimdTemporaryError,
    _SafeResolver,
    is_forbidden_address,
    normalize_allowed_hosts,
    parse_client_id_url,
    redirect_uri_matches,
)
from hermes.config import HermesConfig, load_config
from tests.test_oauth_cimd_flow import (
    CLAUDE_CODE_DOC,
    CLAUDE_CODE_URL,
    HOST,
    PASSWORD,
    _Base,
    _body,
    _Req,
)

PUBLIC_V4 = "1.1.1.1"


def _gai(*ips: str):
    calls: list[str] = []

    async def fake(host, port, **kwargs):
        calls.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]

    fake.calls = calls  # type: ignore[attr-defined]
    return fake


def _doc(url: str) -> bytes:
    return json.dumps({**CLAUDE_CODE_DOC, "client_id": url}).encode()


# ── ALTO-1: literales IPv4 no canónicos ───────────────────────

NON_CANONICAL = [
    "https://127.1/x",
    "https://10.1/x",
    "https://2130706433/x",          # 127.0.0.1 en decimal
    "https://3232235777/x",          # 192.168.1.1 en decimal
    "https://0177.0.0.1/x",          # octal
    "https://127.0.0.1./x",          # punto final
    "https://0x7f.1/x",
    "https://0x7f.0.0.1/x",
    "https://[::ffff:7f00:1]/x",
    "https://[::1]/x",
    "https://192.0.2.10/x",
    "https://1.1.1.1/x",             # ni siquiera una IP pública vale
]


class _ConnectionSpy:
    """Cuenta cualquier intento de conexión del bucle y lo hace fallar."""

    def __init__(self) -> None:
        self.attempts: list[Any] = []

    async def create_connection(self, *args, **kwargs):
        self.attempts.append(("create_connection", args[1:3], kwargs.get("host")))
        raise OSError("blocked by test")

    async def sock_connect(self, sock, address):
        self.attempts.append(("sock_connect", address))
        raise OSError("blocked by test")

    async def start_connection(self, addr_infos, *args, **kwargs):
        # Lo que usa aiohttp para abrir el socket (Happy Eyeballs).
        self.attempts.append(("start_connection", [a[4] for a in addr_infos]))
        raise OSError("blocked by test")

    @contextlib.contextmanager
    def patch(self, loop):
        with unittest.mock.patch.multiple(
                loop, create_connection=self.create_connection,
                sock_connect=self.sock_connect), \
             unittest.mock.patch.object(aiohappyeyeballs, "start_connection",
                                        self.start_connection):
            yield


class TestAlto1NonCanonicalIp(unittest.IsolatedAsyncioTestCase):
    def test_every_numeric_form_is_rejected_by_the_url_shape(self) -> None:
        for url in NON_CANONICAL:
            with self.subTest(url=url):
                self.assertEqual(parse_client_id_url(url), "ip_host")

    def test_other_non_dns_hosts(self) -> None:
        for url in ("https://localhost/x", "https://claude.ai./x",
                    "https://a_b.example.com/x", "https://-a.example.com/x",
                    "https://%31.example.com/x"):
            with self.subTest(url=url):
                self.assertEqual(parse_client_id_url(url), "bad_host")

    def test_control_dns_names_still_accepted(self) -> None:
        # Control: la regla no tira también los nombres legítimos.
        for url in (CLAUDE_CODE_URL, "https://Claude.AI/oauth/x",
                    "https://docs.example.com/c", "https://example.xn--p1ai/c"):
            with self.subTest(url=url):
                self.assertIsNone(parse_client_id_url(url))

    def test_control_the_gap_exists_in_the_old_check(self) -> None:
        # Control negativo: la comprobación anterior (`_literal_ip`, estricta)
        # NO reconoce estas formas como IP, mientras que aiohttp sí las trata
        # como IP y no las pasa por el resolvedor seguro. Es el hueco que los
        # tests de abajo vigilan.
        is_ip = getattr(aiohttp.helpers, "is_ip_address", None)
        for host in ("127.1", "10.1", "2130706433", "0177.0.0.1", "127.0.0.1."):
            with self.subTest(host=host):
                self.assertIsNone(cimd._literal_ip(host))
                if is_ip is not None:
                    self.assertTrue(is_ip(host))

    async def test_no_connection_is_ever_attempted(self) -> None:
        spy = _ConnectionSpy()
        gai = _gai(PUBLIC_V4)
        resolver = CimdResolver(getaddrinfo=gai)
        with spy.patch(asyncio.get_running_loop()):
            for url in NON_CANONICAL:
                with self.subTest(url=url):
                    with self.assertRaises(CimdInvalidError) as ctx:
                        await resolver.resolve(url)
                    self.assertEqual(ctx.exception.reason, "ip_host")
                    # Defensa en profundidad: aunque alguien llame a la
                    # descarga saltándose la forma de la URL.
                    with self.assertRaises(CimdInvalidError):
                        await resolver._fetch(url)
        self.assertEqual(spy.attempts, [])
        self.assertEqual(gai.calls, [])

    async def test_control_spy_sees_a_direct_aiohttp_connection(self) -> None:
        # Control negativo del espía: la sesión de CIMD, usada a pelo sin las
        # comprobaciones de Hermes, SÍ intenta conectar a una IP literal sin
        # pasar por el resolvedor seguro (`gai` no se llama). Si el espía no
        # lo viera, el test anterior no probaría nada.
        spy = _ConnectionSpy()
        gai = _gai(PUBLIC_V4)
        resolver = CimdResolver(getaddrinfo=gai)
        with spy.patch(asyncio.get_running_loop()):
            async with resolver._new_session() as session:
                with self.assertRaises((aiohttp.ClientError, OSError)):
                    async with session.get("https://192.0.2.10/x"):
                        pass
        self.assertTrue(spy.attempts)
        self.assertEqual(gai.calls, [])


# ── MEDIO-1: lista de hosts permitidos ────────────────────────


class TestMedio1AllowedHostsNormalization(unittest.TestCase):
    def test_normalizes_case_and_trailing_dot(self) -> None:
        self.assertEqual(normalize_allowed_hosts(["Claude.AI.", " claude.ai "]),
                         frozenset({"claude.ai"}))

    def test_rejects_ips_and_garbage(self) -> None:
        for bad in ("192.0.2.1", "127.1", "https://claude.ai", "claude.ai/x",
                    "claude.ai:443", "*.example.com", "localhost", ""):
            with self.subTest(host=bad), self.assertRaises(ValueError):
                normalize_allowed_hosts([bad])

    def test_config_validation_fails_closed(self) -> None:
        base = dict(auth_password="Kq7#vX2!mR9$wL4@", public_hostname="hermes.example.com",
                    supervisor_token="t")
        HermesConfig(**base, oauth_cimd_allowed_hosts=["claude.ai"]).validate()
        with self.assertRaises(ValueError):
            HermesConfig(**base, oauth_cimd_allowed_hosts=["192.0.2.1"]).validate()

    def test_unparseable_env_is_not_an_empty_list(self) -> None:
        # Vacía = cualquier host: un JSON roto no puede acabar así.
        with unittest.mock.patch.dict(os.environ,
                                      {"HERMES_OAUTH_CIMD_ALLOWED_HOSTS": "claude.ai"}):
            self.assertEqual(load_config().oauth_cimd_allowed_hosts, ["claude.ai"])
        with unittest.mock.patch.dict(os.environ,
                                      {"HERMES_OAUTH_CIMD_ALLOWED_HOSTS": '["claude.ai"]'}):
            self.assertEqual(load_config().oauth_cimd_allowed_hosts, ["claude.ai"])
        with unittest.mock.patch.dict(os.environ,
                                      {"HERMES_OAUTH_CIMD_ALLOWED_HOSTS": "[]"}):
            self.assertEqual(load_config().oauth_cimd_allowed_hosts, [])

    def test_user_agent_has_no_version(self) -> None:
        async def _ua() -> str:
            session = CimdResolver()._new_session()
            try:
                return session.headers.get("User-Agent", "")
            finally:
                await session.close()

        ua = asyncio.run(_ua())
        self.assertEqual(ua, "Hermes-CIMD")


class _AllowedBase(_Base):
    allowed: tuple[str, ...] = ("Claude.AI.",)

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.server = oauth.OAuthServer(
            auth_password=PASSWORD, public_hostname=HOST,
            cimd_resolver=self.resolver,  # type: ignore[arg-type]
            cimd_allowed_hosts=list(self.allowed),
        )


class TestMedio1AllowedHostsFlow(_AllowedBase):
    async def test_other_host_is_rejected_without_download(self) -> None:
        other = "https://claude.ai.evil.example/oauth/c"
        with capture_logs() as logs:
            get = await self.server.authorize_get(_Req(query=self._params(client_id=other)))
            post = await self._authorize(client_id=other)
        for resp in (get, post):
            self.assertEqual(resp.status_code, 400)
            self.assertIn("oauth_cimd_allowed_hosts", resp.body.decode())
        self.assertEqual(self.resolver.calls, [])
        self.assertIn("host_not_allowed",
                      [e.get("reason") for e in logs if e["event"] == "oauth_cimd_rejected"])

    async def test_control_listed_host_works(self) -> None:
        get = await self.server.authorize_get(_Req(query=self._params()))
        self.assertEqual(get.status_code, 200)
        datos = await self._full_flow()
        self.assertTrue(await self.server.validate_token(datos["access_token"]))

    async def test_removing_the_host_cuts_live_tokens_without_revoking(self) -> None:
        datos = await self._full_flow()
        cerrado = oauth.OAuthServer(
            auth_password=PASSWORD, public_hostname=HOST,
            cimd_resolver=self.resolver,  # type: ignore[arg-type]
            cimd_allowed_hosts=["example.org"],
        )
        self.assertFalse(await cerrado.validate_token(datos["access_token"]))
        resp = await cerrado.token(_Req(form={
            "grant_type": "refresh_token", "refresh_token": datos["refresh_token"]}))
        self.assertEqual(resp.status_code, 401)
        # No se borra nada: con el host de vuelta en la lista, todo vale.
        self.assertTrue(await self.server.validate_token(datos["access_token"]))


class TestMedio1EmptyListMeansAnyHost(_AllowedBase):
    allowed = ()

    async def test_any_public_host_is_downloaded(self) -> None:
        other = "https://client.example.com/oauth/c"
        await self.server.authorize_get(_Req(query=self._params(client_id=other)))
        self.assertEqual(self.resolver.calls, [other])


# ── MEDIO-2: cupo y caché frente a anónimos ───────────────────


class _ResolverBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = 1_000_000.0
        self.mono = 5_000.0
        self.resolver = CimdResolver(
            getaddrinfo=_gai(PUBLIC_V4),
            clock=lambda: self.now,
            monotonic=lambda: self.mono,
        )


class TestMedio2Quota(_ResolverBase):
    async def test_per_source_quota(self) -> None:
        n = cimd.MAX_FETCHES_PER_SOURCE_PER_WINDOW
        urls = [f"https://c{i}.example.com/doc" for i in range(n + 2)]
        with aioresponses() as m:
            for u in urls:
                m.get(u, body=_doc(u))
            for u in urls[:n]:
                await self.resolver.resolve(u, source="192.0.2.1")
            with self.assertRaises(CimdTemporaryError) as ctx:
                await self.resolver.resolve(urls[n], source="192.0.2.1")
            self.assertEqual(ctx.exception.reason, "rate_limited")
            self.assertEqual(len(m.requests), n, "el rechazo no conecta")
            # Control: otra IP sí tiene cupo.
            await self.resolver.resolve(urls[n], source="192.0.2.2")
            self.assertEqual(len(m.requests), n + 1)

    async def _exhaust_global(self, m: aioresponses) -> None:
        for i in range(cimd.MAX_FETCHES_PER_WINDOW):
            u = f"https://a{i}.example.com/doc"
            m.get(u, body=_doc(u))
            await self.resolver.resolve(u, source=f"192.0.2.{i % 250 + 1}")

    async def test_trusted_refresh_does_not_depend_on_the_quota(self) -> None:
        with aioresponses() as m:
            await self._exhaust_global(m)
            m.get(CLAUDE_CODE_URL, body=_doc(CLAUDE_CODE_URL), repeat=True)
            # Control negativo: un anónimo con el cupo agotado no pasa.
            with self.assertRaises(CimdTemporaryError):
                await self.resolver.resolve(CLAUDE_CODE_URL, source="198.51.100.7")
            client = await self.resolver.resolve(CLAUDE_CODE_URL, trusted=True)
        self.assertEqual(client.client_name, "Claude Code")

    async def test_pinned_client_does_not_depend_on_the_quota(self) -> None:
        self.resolver.pin(CLAUDE_CODE_URL)
        with aioresponses() as m:
            await self._exhaust_global(m)
            m.get(CLAUDE_CODE_URL, body=_doc(CLAUDE_CODE_URL))
            client = await self.resolver.resolve(CLAUDE_CODE_URL, source="198.51.100.7")
        self.assertEqual(client.client_name, "Claude Code")


class TestMedio2Cache(_ResolverBase):
    async def _flood(self, m: aioresponses) -> None:
        for i in range(cimd.CACHE_MAX_ENTRIES + 5):
            u = f"https://f{i}.example.com/doc"
            m.get(u, body=_doc(u))
            self.mono += 3
            await self.resolver.resolve(u, source=f"192.0.2.{i % 250 + 1}")

    async def test_known_client_survives_a_flood_of_valid_documents(self) -> None:
        with aioresponses() as m:
            m.get(CLAUDE_CODE_URL, body=_doc(CLAUDE_CODE_URL))
            await self.resolver.resolve(CLAUDE_CODE_URL, trusted=True)
            await self._flood(m)
        self.assertIn(CLAUDE_CODE_URL, self.resolver._cache)
        self.assertEqual(len(self.resolver._cache), cimd.CACHE_MAX_ENTRIES)

    async def test_control_unknown_client_is_evicted(self) -> None:
        with aioresponses() as m:
            m.get(CLAUDE_CODE_URL, body=_doc(CLAUDE_CODE_URL))
            await self.resolver.resolve(CLAUDE_CODE_URL)
            await self._flood(m)
        self.assertNotIn(CLAUDE_CODE_URL, self.resolver._cache)

    async def test_soft_failure_keeps_the_good_copy(self) -> None:
        with aioresponses() as m:
            m.get(CLAUDE_CODE_URL, body=_doc(CLAUDE_CODE_URL))
            await self.resolver.resolve(CLAUDE_CODE_URL, trusted=True)
            self.now += 3_601
            m.get(CLAUDE_CODE_URL, status=403)
            with self.assertRaises(CimdInvalidError):
                await self.resolver.resolve(CLAUDE_CODE_URL, trusted=True)
        self.assertIn(CLAUDE_CODE_URL, self.resolver._cache)

    async def test_control_definitive_failure_drops_the_copy(self) -> None:
        with aioresponses() as m:
            m.get(CLAUDE_CODE_URL, body=_doc(CLAUDE_CODE_URL))
            await self.resolver.resolve(CLAUDE_CODE_URL, trusted=True)
            self.now += 3_601
            m.get(CLAUDE_CODE_URL, status=404)
            with self.assertRaises(CimdInvalidError):
                await self.resolver.resolve(CLAUDE_CODE_URL, trusted=True)
        self.assertNotIn(CLAUDE_CODE_URL, self.resolver._cache)
        self.assertNotIn(CLAUDE_CODE_URL, self.resolver._pinned)


class TestMedio2OAuthWiring(_Base):
    async def test_authorize_passes_source_and_login_pins(self) -> None:
        req = _Req(query=self._params())
        req.client = type("C", (), {"host": "192.0.2.44"})()
        await self.server.authorize_get(req)
        self.assertEqual(self.resolver.kwargs[-1], {"source": "192.0.2.44", "trusted": False})
        self.assertEqual(self.resolver.pinned, [])
        await self._full_flow()
        self.assertEqual(self.resolver.pinned, [CLAUDE_CODE_URL])

    async def test_refresh_is_trusted(self) -> None:
        datos = await self._full_flow()
        await self.server.token(_Req(form={
            "grant_type": "refresh_token", "refresh_token": datos["refresh_token"]}))
        self.assertEqual(self.resolver.kwargs[-1]["trusted"], True)

    async def test_wrong_password_does_not_pin(self) -> None:
        await self._authorize(password="mala")
        self.assertEqual(self.resolver.pinned, [])


# ── BAJO-1: sv_get_addon_logs("self") ─────────────────────────


class TestBajo1SelfSlug(unittest.TestCase):
    def test_self_is_hermes(self) -> None:
        from hermes.tools.addons import _es_hermes

        self.assertTrue(_es_hermes("self"))
        self.assertTrue(_es_hermes("SELF"))
        # Control: un add-on ajeno no se toma por Hermes.
        self.assertFalse(_es_hermes("core_mosquitto"))
        self.assertFalse(_es_hermes("selfhosted"))


class TestBajo1SelfLogsAreRedacted(unittest.IsolatedAsyncioTestCase):
    async def test_self_logs_go_through_network_redaction(self) -> None:
        from hermes.tools import addons

        class _MCP:
            def __init__(self) -> None:
                self.tools: dict = {}

            def tool(self):
                def deco(fn):
                    self.tools[fn.__name__] = fn
                    return fn
                return deco

        class _HA:
            async def sv_request_text(self, path, params=None):
                return "peer 192.0.2.77 connected\n"

        mcp = _MCP()
        addons.register(mcp, _HA())
        logging_setup.configure_network_redaction(True, "hermes.example.com")
        try:
            fuera = await mcp.tools["sv_get_addon_logs"]("self", lines=10)
            otro = await mcp.tools["sv_get_addon_logs"]("core_mosquitto", lines=10)
        finally:
            logging_setup.configure_network_redaction(False, "")
        self.assertNotIn("192.0.2.77", json.dumps(fuera))
        # Control: el log de otro add-on no pasa por la redacción de red.
        self.assertIn("192.0.2.77", json.dumps(otro))


# ── BAJO-2: huecos de la redacción de IPs ─────────────────────


class TestBajo2Redaction(unittest.TestCase):
    def setUp(self) -> None:
        logging_setup.configure_network_redaction(True, "hermes.example.com")

    def tearDown(self) -> None:
        logging_setup.configure_network_redaction(False, "")

    def test_gaps_are_closed(self) -> None:
        for texto, secreto in (
            ("prefix 2001:db8:5678::/48", "2001:db8:5678::"),
            ("addr 2001:db8:5678:9abc:: end", "2001:db8:5678:9abc::"),
            ("line\\n192.0.2.5 next", "192.0.2.5"),
            ("line\\t192.0.2.5 next", "192.0.2.5"),
            ("x_192.0.2.5", "192.0.2.5"),
            ("ip 192.168.001.010 ok", "192.168.001.010"),
        ):
            with self.subTest(texto=texto):
                self.assertNotIn(secreto, logging_setup.redact_network(texto))

    def test_control_non_ips_untouched(self) -> None:
        for texto in ("v1.2.3.4-beta", "time 06:54:12", "a:: b", ":: c",
                      "std::vector", "version 2026.11.1", "mac aa:bb:cc:dd:ee:ff",
                      "loopback 127.0.0.1"):
            with self.subTest(texto=texto):
                self.assertEqual(logging_setup.redact_network(texto), texto)


# ── BAJO-3: el host de un client_id inválido no va al log ─────


class TestBajo3NoAttackerChosenIpInLog(_Base):
    async def test_ip_client_id_logs_no_host(self) -> None:
        with capture_logs() as logs:
            await self.server.authorize_get(_Req(query=self._params(
                client_id="https://192.168.1.7/x")))
        ev = [e for e in logs if e["event"] == "oauth_cimd_rejected"]
        self.assertEqual(ev[0]["client_host"], "?")
        self.assertNotIn("192.168.1.7", json.dumps(ev, default=str))

    async def test_control_valid_host_is_logged(self) -> None:
        self.resolver.result = CimdTemporaryError("timeout")
        with capture_logs() as logs:
            await self.server.authorize_get(_Req(query=self._params()))
        ev = [e for e in logs if e["event"] == "oauth_cimd_rejected"]
        self.assertEqual(ev[0]["client_host"], "claude.ai")


# ── BAJO-4: sin descompresión ─────────────────────────────────


class TestBajo4NoDecompression(_ResolverBase):
    async def test_session_does_not_decompress(self) -> None:
        session = self.resolver._new_session()
        try:
            self.assertFalse(session.auto_decompress)
        finally:
            await session.close()

    async def test_asks_identity_and_rejects_compressed_body(self) -> None:
        vistos: list[dict] = []

        def cb(url, **kwargs):
            vistos.append(dict(kwargs.get("headers") or {}))

        with aioresponses() as m:
            m.get(CLAUDE_CODE_URL, body=_doc(CLAUDE_CODE_URL),
                  headers={"Content-Encoding": "gzip"}, callback=cb)
            with self.assertRaises(CimdInvalidError) as ctx:
                await self.resolver.resolve(CLAUDE_CODE_URL)
        self.assertEqual(ctx.exception.reason, "content_encoding")
        self.assertEqual(vistos[0].get("Accept-Encoding"), "identity")
        # Control: sin Content-Encoding el mismo cuerpo vale.
        with aioresponses() as m:
            m.get(CLAUDE_CODE_URL, body=_doc(CLAUDE_CODE_URL))
            await self.resolver.resolve(CLAUDE_CODE_URL)


# ── BAJO-5: getaddrinfo en un pool propio ─────────────────────


class TestBajo5DnsPool(unittest.IsolatedAsyncioTestCase):
    async def test_default_resolution_runs_in_the_private_pool(self) -> None:
        hilos: list[str] = []

        def fake_gai(host, port, family=0, type=0, *a):
            hilos.append(threading.current_thread().name)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_V4, port))]

        with unittest.mock.patch("hermes.cimd.socket.getaddrinfo", fake_gai):
            res = await _SafeResolver().resolve("docs.example.com", 443)
        self.assertEqual(res[0]["host"], PUBLIC_V4)
        self.assertTrue(hilos[0].startswith("hermes-cimd-dns"), hilos)


# ── BAJO-6: revocación solo con fallos definitivos ────────────


class TestBajo6Definitive(unittest.TestCase):
    def test_classification(self) -> None:
        for reason in ("http_404", "http_410", "client_id_mismatch", "bad_json",
                       "too_large", "ip_host"):
            with self.subTest(reason=reason):
                self.assertTrue(CimdInvalidError(reason).definitive)
        for reason in ("http_403", "http_401", "http_400", "http_204", "redirect",
                       "forbidden_address", "content_encoding"):
            with self.subTest(reason=reason):
                self.assertFalse(CimdInvalidError(reason).definitive)


class TestBajo6RefreshDoesNotRevoke(_Base):
    async def test_soft_errors_are_503_and_keep_sessions(self) -> None:
        for reason in ("http_403", "redirect", "forbidden_address"):
            with self.subTest(reason=reason):
                self.resolver.result = CLAUDE_OK
                datos = await self._full_flow()
                self.resolver.result = CimdInvalidError(reason)
                resp = await self.server.token(_Req(form={
                    "grant_type": "refresh_token", "refresh_token": datos["refresh_token"]}))
                self.assertEqual(resp.status_code, 503)
                self.assertEqual(_body(resp), {"error": "temporarily_unavailable"})
                self.assertTrue(await self.server.validate_token(datos["access_token"]))

    async def test_control_404_still_revokes(self) -> None:
        datos = await self._full_flow()
        self.resolver.result = CimdInvalidError("http_404")
        resp = await self.server.token(_Req(form={
            "grant_type": "refresh_token", "refresh_token": datos["refresh_token"]}))
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(await self.server.validate_token(datos["access_token"]))


# ── BAJO-7: rangos especiales que se colaban ──────────────────


class TestBajo7SpecialRanges(unittest.TestCase):
    def test_forbidden(self) -> None:
        import ipaddress

        for ip in ("::ffff:0:a00:5", "fec0::1", "5f00::1"):
            with self.subTest(ip=ip):
                self.assertTrue(is_forbidden_address(ipaddress.ip_address(ip)))
        # Control: lo público sigue permitido, también traducido por SIIT.
        for ip in ("1.1.1.1", "2606:4700:4700::1111", "::ffff:0:101:101"):
            with self.subTest(ip=ip):
                self.assertFalse(is_forbidden_address(ipaddress.ip_address(ip)))


# ── BAJO-8: caracteres de control en el redirect_uri ──────────


class TestBajo8ControlChars(unittest.TestCase):
    def test_rejected(self) -> None:
        for req in ("http://local\nhost:1/callback", "http://localhost:5/call\tback",
                    "http://localhost:5/callback\r", "http://localhost:5/callback\x7f"):
            with self.subTest(req=req):
                self.assertFalse(redirect_uri_matches("http://localhost/callback", req))
        # Control: sin el carácter, casa.
        self.assertTrue(redirect_uri_matches("http://localhost/callback",
                                             "http://localhost:5/callback"))


# ── BAJO-9: apagar CIMD corta lo ya emitido ───────────────────


class TestBajo9DisableCutsIssued(_Base):
    def _apagado(self) -> oauth.OAuthServer:
        return oauth.OAuthServer(
            auth_password=PASSWORD, public_hostname=HOST, cimd_enabled=False,
            cimd_resolver=self.resolver,  # type: ignore[arg-type]
        )

    async def test_access_token_stops_validating(self) -> None:
        datos = await self._full_flow()
        self.assertFalse(await self._apagado().validate_token(datos["access_token"]))
        # Control: con CIMD encendido sigue valiendo (no se borró nada).
        self.assertTrue(await self.server.validate_token(datos["access_token"]))

    async def test_pending_code_is_not_exchanged(self) -> None:
        resp = await self._authorize()
        self.server = self._apagado()
        tok = await self._exchange(resp.headers["location"])
        self.assertEqual(tok.status_code, 401)
        self.assertEqual(_body(tok), {"error": "invalid_client"})

    async def test_control_dcr_tokens_unaffected(self) -> None:
        class _JsonReq(_Req):
            async def json(self) -> dict:
                return {"client_name": "x", "redirect_uris": ["https://client.example.com/cb"]}

        cid = _body(await self.server.register_client(_JsonReq()))["client_id"]
        resp = await self._authorize(client_id=cid, redirect_uri="https://client.example.com/cb")
        tok = await self._exchange(resp.headers["location"], client_id=cid,
                                   redirect_uri="https://client.example.com/cb")
        self.assertTrue(await self._apagado().validate_token(_body(tok)["access_token"]))


CLAUDE_OK = cimd.CimdClient(
    client_id=CLAUDE_CODE_URL, client_name="Claude Code",
    redirect_uris=("http://localhost/callback", "http://127.0.0.1/callback"),
    allow_refresh=True,
)


# ── BAJO-10: anotación de retención ilegible ──────────────────


class TestBajo10CorruptLedger(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ruta = Path(self._tmp.name) / "safety_backups.json"
        self._p = unittest.mock.patch.object(sr, "LEDGER_PATH", self.ruta)
        self._p.start()

    def tearDown(self) -> None:
        self._p.stop()
        self._tmp.cleanup()

    async def test_corrupt_ledger_is_set_aside_not_overwritten(self) -> None:
        self.ruta.write_text("{roto", encoding="utf-8")
        with capture_logs() as logs:
            await sr.record_launch("n1", "job1", origin="auto")
        apartados = list(self.ruta.parent.glob("safety_backups.json.corrupt-*"))
        self.assertEqual(len(apartados), 1)
        self.assertEqual(apartados[0].read_text(encoding="utf-8"), "{roto")
        self.assertIn(("safety_backup_ledger_corrupt", "error"),
                      [(e["event"], e["log_level"]) for e in logs])
        self.assertEqual(
            [e["name"] for e in json.loads(self.ruta.read_text())["entries"]], ["n1"])

    async def test_not_overwritten_if_it_cannot_be_set_aside(self) -> None:
        self.ruta.write_text("{roto", encoding="utf-8")
        with unittest.mock.patch.object(Path, "replace", side_effect=OSError("EIO")):
            await sr.record_launch("n1", "job1", origin="auto")
        self.assertEqual(self.ruta.read_text(encoding="utf-8"), "{roto")

    async def test_control_readable_ledger_is_not_set_aside(self) -> None:
        await sr.record_launch("n1", "job1", origin="auto")
        await sr.record_launch("n2", "job2", origin="auto")
        self.assertEqual(list(self.ruta.parent.glob("*.corrupt-*")), [])


# ── BAJO-11 y BAJO-12: lock del safety backup ─────────────────


class TestBajo11y12SafetyLock(unittest.IsolatedAsyncioTestCase):
    async def test_write_does_not_wait_forever(self) -> None:
        from hermes import fs_write

        lock = sr.safety_backup_lock()
        await lock.acquire()
        try:
            with unittest.mock.patch.object(sr, "SAFETY_LOCK_WAIT_SECONDS", 0.05), \
                 unittest.mock.patch.object(fs_write, "_maybe_trigger_safety_backup") as cuerpo:
                res = await fs_write.maybe_trigger_safety_backup(None, 30, enabled=True)
        finally:
            lock.release()
        self.assertTrue(res["error"].startswith("safety_backup_in_progress"))
        cuerpo.assert_not_called()

    async def test_control_free_lock_runs_and_releases(self) -> None:
        from hermes import fs_write

        async def _cuerpo(*a, **k):
            self.assertTrue(sr.safety_backup_lock().locked())
            return None

        with unittest.mock.patch.object(fs_write, "_maybe_trigger_safety_backup", _cuerpo):
            self.assertIsNone(await fs_write.maybe_trigger_safety_backup(None, 30, enabled=True))
        self.assertFalse(sr.safety_backup_lock().locked())
        self.assertIs(fs_write._safety_lock(), sr.safety_backup_lock())

    async def test_tool_takes_the_same_lock(self) -> None:
        from hermes.tools import backups

        class _MCP:
            def __init__(self) -> None:
                self.tools: dict = {}

            def tool(self):
                def deco(fn):
                    self.tools[fn.__name__] = fn
                    return fn
                return deco

        mcp = _MCP()
        backups.register(mcp, unittest.mock.MagicMock())
        lock = sr.safety_backup_lock()
        await lock.acquire()
        try:
            with unittest.mock.patch.object(sr, "SAFETY_LOCK_WAIT_SECONDS", 0.05), \
                 unittest.mock.patch.object(backups, "_load_safety_state") as estado:
                res = await mcp.tools["sv_create_safety_backup"]()
        finally:
            lock.release()
        self.assertTrue(res["error"].startswith("safety_backup_in_progress"))
        estado.assert_not_called()


# ── BAJO-13: webhook_id y !secret en las trazas ───────────────


class TestBajo13Traces(unittest.TestCase):
    def setUp(self) -> None:
        from hermes import fs as _fs

        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        (base / "secrets.yaml").write_text(
            "notify_url: https://hooks.example.com/abcdefSECRET\n"
            "short: on\n"
            "included: !include other.yaml\n",
            encoding="utf-8")
        self._p = unittest.mock.patch.object(_fs, "CONFIG_BASE", base)
        self._p.start()

    def tearDown(self) -> None:
        self._p.stop()
        self._tmp.cleanup()

    def _traza(self) -> dict:
        return {
            "run_id": "r1", "item_id": "1", "state": "stopped",
            "timestamp": {"start": "2026-11-14T08:00:00Z"},
            "trace": {"trigger/0": [{"path": "trigger/0", "timestamp": "2026-11-14T08:00:00Z",
                                     "changed_variables": {"trigger": {
                                         "platform": "webhook", "webhook_id": "hook-abc-123"}}}]},
            "config": {
                "triggers": [{"platform": "webhook", "webhook_id": "hook-abc-123"}],
                "actions": [{"action": "rest_command.x",
                             "data": {"url": "https://hooks.example.com/abcdefSECRET",
                                      "message": "on"}}],
            },
        }

    def test_secrets_and_webhook_id_do_not_leak(self) -> None:
        from hermes.tools import traces

        doc = traces._completo(self._traza(), "automation")
        texto = json.dumps(doc)
        self.assertNotIn("abcdefSECRET", texto)
        self.assertNotIn("hook-abc-123", texto)
        # Control: los valores cortos y el resto de la configuración siguen.
        self.assertIn('"message": "on"', texto)
        self.assertIn("rest_command.x", texto)

    def test_control_without_secrets_file_value_is_visible(self) -> None:
        from hermes.tools import traces

        (Path(self._tmp.name) / "secrets.yaml").unlink()
        texto = json.dumps(traces._completo(self._traza(), "automation"))
        self.assertIn("abcdefSECRET", texto)


# ── CodeQL: sin import circular backups ↔ safety_retention ────


class TestNoCircularImport(unittest.TestCase):
    def test_safety_retention_does_not_import_tools(self) -> None:
        import ast

        fuente = Path(sr.__file__).read_text(encoding="utf-8")
        modulos = {
            n.module for n in ast.walk(ast.parse(fuente))
            if isinstance(n, ast.ImportFrom) and n.module
        }
        self.assertFalse([m for m in modulos if m.startswith("hermes.tools")], modulos)

    def test_job_errors_alias_kept(self) -> None:
        from hermes.supervisor_jobs import job_errors
        from hermes.tools.backups import _job_errors

        self.assertIs(_job_errors, job_errors)


if __name__ == "__main__":
    unittest.main()
