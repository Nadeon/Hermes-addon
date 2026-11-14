"""Tests de `hermes.cimd`: forma del client_id, defensa SSRF, descarga acotada,
validación del documento, caché y comparación de redirect_uri.

Sin red real: el DNS es un `getaddrinfo` falso y las respuestas HTTP salen de
`aioresponses`. La única conexión TCP que se abre es contra un servidor local
del propio test, para comprobar que una dirección prohibida no llega a
conectar.
"""

from __future__ import annotations

import asyncio
import json
import socket
import unittest.mock

import aiohttp
from aioresponses import aioresponses
from yarl import URL

from hermes import cimd
from hermes.cimd import (
    CimdInvalidError,
    CimdResolver,
    CimdTemporaryError,
    _SafeResolver,
    parse_client_id_url,
    redirect_uri_matches,
    validate_document,
)

# URL pública y real del documento de Claude Code (data-model.md). Es la única
# URL real que usan estos tests; nunca se descarga de verdad.
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

# Direcciones públicas para el DNS falso: resolvedores DNS públicos conocidos.
PUBLIC_V4 = "1.1.1.1"
PUBLIC_V4_B = "1.0.0.1"
PUBLIC_V6 = "2606:4700:4700::1111"


def _doc(url: str = CLAUDE_CODE_URL, **overrides: object) -> dict:
    doc = dict(CLAUDE_CODE_DOC)
    doc["client_id"] = url
    for key, value in overrides.items():
        if value is _DROP:
            doc.pop(key, None)
        else:
            doc[key] = value
    return doc


_DROP = object()


def _raw(doc: object) -> bytes:
    return json.dumps(doc).encode("utf-8")


def _gai(*ips: str):
    """`getaddrinfo` falso que devuelve `ips` y cuenta las llamadas."""
    calls: list[str] = []

    async def fake(host, port, **kwargs):
        calls.append(host)
        out = []
        for ip in ips:
            if ":" in ip:
                out.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, port, 0, 0)))
            else:
                out.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)))
        return out

    fake.calls = calls  # type: ignore[attr-defined]
    return fake


# ── T011: forma de la URL (FR-002) ───────────────────────────


class TestParseClientIdUrl(unittest.TestCase):
    def test_accepts_claude_code_and_explicit_443(self) -> None:
        self.assertIsNone(parse_client_id_url(CLAUDE_CODE_URL))
        self.assertIsNone(parse_client_id_url("https://example.com:443/c"))

    def test_rejects_bad_shapes(self) -> None:
        casos = {
            "http://example.com/c": "not_https",
            "https://example.com": "no_path",
            "https://example.com/": "no_path",
            "https://example.com/c#frag": "fragment",
            "https://example.com/c?q=1": "query",
            "https://example.com/c?": "query",
            "https://user@example.com/c": "userinfo",
            "https://user:pw@example.com/c": "userinfo",
            "https://example.com/a/./c": "dot_segment",
            "https://example.com/a/../c": "dot_segment",
            "https://example.com/a/%2e%2e/c": "dot_segment",
            "https://example.com/%2E/c": "dot_segment",
            "https://example.com/a/..": "dot_segment",
            "https://example.com:8443/c": "bad_port",
            "https://example.com:/c": "bad_port",
            "https://example.com:99999/c": "bad_port",
            "https://example.com/a b": "bad_characters",
            "https://example.com/a\\b": "bad_characters",
            "https:///c": "no_host",
            "": "empty",
        }
        for url, motivo in casos.items():
            with self.subTest(url=url):
                self.assertEqual(parse_client_id_url(url), motivo)

    def test_length_limit(self) -> None:
        base = "https://example.com/"
        ok = base + "a" * (cimd.MAX_URL_LEN - len(base))
        self.assertIsNone(parse_client_id_url(ok))
        self.assertEqual(parse_client_id_url(ok + "a"), "too_long")


# ── T012: resolvedor seguro (FR-006) ─────────────────────────


class TestSafeResolver(unittest.IsolatedAsyncioTestCase):
    FORBIDDEN = [
        "127.0.0.1", "10.0.0.5", "172.16.0.1", "192.168.1.1", "100.64.0.7",
        "169.254.1.1", "0.0.0.0", "224.0.0.1", "::1", "fd00::1", "fe80::1",
        "::ffff:10.0.0.5", "2002:0a00:0005::1",
        # Más allá de la lista de la tarea: documentación, broadcast, NAT64 e
        # IPv4-compatible de una privada, y multicast IPv6.
        "192.0.2.10", "255.255.255.255", "64:ff9b::a00:5", "::a00:5", "ff02::1",
    ]

    async def test_rejects_every_special_address(self) -> None:
        for ip in self.FORBIDDEN:
            with self.subTest(ip=ip):
                resolver = _SafeResolver(_gai(ip))
                with self.assertRaises(CimdInvalidError) as ctx:
                    await resolver.resolve("docs.example.com", 443)
                self.assertEqual(ctx.exception.reason, "forbidden_address")

    async def test_one_bad_address_rejects_the_whole_answer(self) -> None:
        resolver = _SafeResolver(_gai(PUBLIC_V4, "10.0.0.5"))
        with self.assertRaises(CimdInvalidError):
            await resolver.resolve("docs.example.com", 443)

    async def test_public_answer_is_returned_with_hostname_for_sni(self) -> None:
        resolver = _SafeResolver(_gai(PUBLIC_V4, PUBLIC_V4_B, PUBLIC_V6))
        res = await resolver.resolve("docs.example.com", 443)
        self.assertEqual([r["host"] for r in res], [PUBLIC_V4, PUBLIC_V4_B, PUBLIC_V6])
        self.assertTrue(all(r["hostname"] == "docs.example.com" for r in res))
        self.assertTrue(all(r["port"] == 443 for r in res))

    async def test_dns_failure_is_temporary(self) -> None:
        async def broken(host, port, **kwargs):
            raise socket.gaierror(socket.EAI_NONAME, "no such host")

        with self.assertRaises(CimdTemporaryError) as ctx:
            await _SafeResolver(broken).resolve("docs.example.com", 443)
        self.assertEqual(ctx.exception.reason, "dns")

    async def test_literal_special_ip_in_url_is_rejected_without_dns(self) -> None:
        gai = _gai(PUBLIC_V4)
        resolver = CimdResolver(getaddrinfo=gai)
        with aioresponses() as m:
            for url in ("https://10.0.0.5/c", "https://[::1]/c", "https://127.0.0.1/c",
                        "https://[::ffff:10.0.0.5]/c"):
                with self.subTest(url=url):
                    with self.assertRaises(CimdInvalidError) as ctx:
                        await resolver.resolve(url)
                    # Desde la revisión 1.1.0 (ALTO-1) ningún literal IP pasa
                    # la forma de la URL: se rechaza antes de llegar al filtro
                    # de direcciones.
                    self.assertEqual(ctx.exception.reason, "ip_host")
            self.assertEqual(len(m.requests), 0)
        self.assertEqual(gai.calls, [])

    async def test_forbidden_resolution_opens_no_connection(self) -> None:
        """El control de verdad: con aiohttp real, un servidor local escucha y
        el DNS falso apunta a él. Si el filtro fallara, habría una conexión."""
        conexiones = 0

        async def handle(reader, writer):
            nonlocal conexiones
            conexiones += 1
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            resolver = CimdResolver(getaddrinfo=_gai("127.0.0.1"))
            # Se llama a `_fetch` porque la forma de la URL no admite otro
            # puerto que el 443, y el servidor del test no puede escuchar ahí.
            with self.assertRaises(CimdInvalidError) as ctx:
                await resolver._fetch(f"https://docs.example.com:{port}/c")
            self.assertEqual(ctx.exception.reason, "forbidden_address")
        finally:
            server.close()
            await server.wait_closed()
        self.assertEqual(conexiones, 0)


# ── T013: descarga (FR-004, FR-005, FR-007) ──────────────────


class _FetchBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = 1_000_000.0
        self.mono = 5_000.0
        self.resolver = CimdResolver(
            getaddrinfo=_gai(PUBLIC_V4),
            clock=lambda: self.now,
            monotonic=lambda: self.mono,
        )


class TestDownload(_FetchBase):
    async def test_sends_accept_json_and_no_proxy_session(self) -> None:
        vistos: list[dict] = []

        def cb(url, **kwargs):
            vistos.append(dict(kwargs.get("headers") or {}))

        with aioresponses() as m:
            m.get(CLAUDE_CODE_URL, body=_raw(_doc()), callback=cb)
            client = await self.resolver.resolve(CLAUDE_CODE_URL)
        self.assertEqual(client.client_name, "Claude Code")
        self.assertEqual(vistos[0].get("Accept"), "application/json")

    async def test_session_configuration(self) -> None:
        session = self.resolver._new_session()
        try:
            self.assertEqual(session.timeout.total, 5)
            self.assertFalse(session.trust_env)
            self.assertFalse(session.connector.use_dns_cache)
            self.assertIsInstance(session.connector._resolver, _SafeResolver)
        finally:
            await session.close()

    async def test_redirects_are_errors_and_not_followed(self) -> None:
        destino = "https://internal.example.com/doc"
        for status in (301, 302, 307, 308):
            with self.subTest(status=status), aioresponses() as m:
                m.get(CLAUDE_CODE_URL, status=status, headers={"Location": destino})
                m.get(destino, body=_raw(_doc()))
                with self.assertRaises(CimdInvalidError) as ctx:
                    await self.resolver.resolve(CLAUDE_CODE_URL)
                self.assertEqual(ctx.exception.reason, "redirect")
                pedidas = {str(k[1]) for k in m.requests}
                self.assertNotIn(destino, pedidas)

    async def test_status_codes(self) -> None:
        for status, tipo in ((404, CimdInvalidError), (410, CimdInvalidError),
                             (403, CimdInvalidError), (204, CimdInvalidError),
                             (500, CimdTemporaryError), (503, CimdTemporaryError),
                             (429, CimdTemporaryError)):
            with self.subTest(status=status), aioresponses() as m:
                m.get(CLAUDE_CODE_URL, status=status, body=_raw(_doc()))
                with self.assertRaises(tipo):
                    await self.resolver.resolve(CLAUDE_CODE_URL)

    async def test_size_limit(self) -> None:
        base = _raw(_doc())
        exacto = base + b" " * (cimd.MAX_DOCUMENT_BYTES - len(base))
        self.assertEqual(len(exacto), 5120)
        with aioresponses() as m:
            m.get(CLAUDE_CODE_URL, body=exacto)
            await self.resolver.resolve(CLAUDE_CODE_URL)
        self.resolver.forget(CLAUDE_CODE_URL)
        with aioresponses() as m:
            m.get(CLAUDE_CODE_URL, body=exacto + b" ")
            with self.assertRaises(CimdInvalidError) as ctx:
                await self.resolver.resolve(CLAUDE_CODE_URL)
        self.assertEqual(ctx.exception.reason, "too_large")

    async def test_timeout_is_temporary(self) -> None:
        async def lento(url, **kwargs):
            await asyncio.sleep(1)

        with unittest.mock.patch.object(cimd, "FETCH_TIMEOUT_SECONDS", 0.05), aioresponses() as m:
            m.get(CLAUDE_CODE_URL, body=_raw(_doc()), callback=lento)
            with self.assertRaises(CimdTemporaryError) as ctx:
                await self.resolver.resolve(CLAUDE_CODE_URL)
        self.assertEqual(ctx.exception.reason, "timeout")

    async def test_network_error_is_temporary(self) -> None:
        with aioresponses() as m:
            m.get(CLAUDE_CODE_URL, exception=aiohttp.ClientConnectionError("down"))
            with self.assertRaises(CimdTemporaryError) as ctx:
                await self.resolver.resolve(CLAUDE_CODE_URL)
        self.assertEqual(ctx.exception.reason, "network")

    async def test_at_most_four_downloads_in_flight(self) -> None:
        liberar = asyncio.Event()
        en_vuelo = 0
        maximo = 0

        async def cb(url, **kwargs):
            nonlocal en_vuelo, maximo
            en_vuelo += 1
            maximo = max(maximo, en_vuelo)
            await liberar.wait()
            en_vuelo -= 1

        urls = [f"https://c{i}.example.com/doc" for i in range(5)]
        with aioresponses() as m:
            for u in urls:
                m.get(u, body=_raw(_doc(u)), callback=cb)
            tareas = [asyncio.create_task(self.resolver.resolve(u)) for u in urls]
            for _ in range(50):
                await asyncio.sleep(0)
            self.assertEqual(en_vuelo, 4, "la quinta descarga debe esperar")
            liberar.set()
            clientes = await asyncio.gather(*tareas)
        self.assertEqual(len(clientes), 5)
        self.assertEqual(maximo, 4)

    async def test_31st_download_in_a_minute_is_rate_limited_without_connecting(self) -> None:
        urls = [f"https://c{i}.example.com/doc" for i in range(31)]
        with aioresponses() as m:
            for u in urls:
                m.get(u, body=_raw(_doc(u)))
            for u in urls[:30]:
                await self.resolver.resolve(u)
            self.assertEqual(len(m.requests), 30)
            with self.assertRaises(CimdTemporaryError) as ctx:
                await self.resolver.resolve(urls[30])
            self.assertEqual(ctx.exception.reason, "rate_limited")
            self.assertEqual(len(m.requests), 30, "el rechazo por cupo no debe conectar")
            # Pasado el minuto, vuelve a haber cupo.
            self.mono += 60
            await self.resolver.resolve(urls[30])
            self.assertEqual(len(m.requests), 31)


# ── T016: validación del documento (FR-008…FR-010) ───────────


class TestValidateDocument(unittest.TestCase):
    def test_claude_code_document_is_valid(self) -> None:
        client = validate_document(CLAUDE_CODE_URL, _raw(CLAUDE_CODE_DOC))
        self.assertEqual(client.client_id, CLAUDE_CODE_URL)
        self.assertEqual(client.client_name, "Claude Code")
        self.assertEqual(client.redirect_uris,
                         ("http://localhost/callback", "http://127.0.0.1/callback"))
        self.assertTrue(client.allow_refresh)

    def test_missing_grant_types_means_no_refresh(self) -> None:
        client = validate_document(CLAUDE_CODE_URL, _raw(_doc(grant_types=_DROP)))
        self.assertFalse(client.allow_refresh)

    def test_invalid_documents(self) -> None:
        casos: dict[str, bytes] = {
            "client_id con barra final": _raw(_doc(client_id=CLAUDE_CODE_URL + "/")),
            "client_id en mayúsculas": _raw(_doc(client_id=CLAUDE_CODE_URL.replace(
                "claude.ai", "CLAUDE.AI"))),
            "sin client_id": _raw(_doc(client_id=_DROP)),
            "sin client_name": _raw(_doc(client_name=_DROP)),
            "client_name vacío": _raw(_doc(client_name="  ")),
            "client_name no texto": _raw(_doc(client_name=["x"])),
            "client_name de 201": _raw(_doc(client_name="x" * 201)),
            "redirect_uris vacío": _raw(_doc(redirect_uris=[])),
            "redirect_uris ausente": _raw(_doc(redirect_uris=_DROP)),
            "redirect_uris texto": _raw(_doc(redirect_uris="http://localhost/cb")),
            "con fragmento": _raw(_doc(redirect_uris=["http://localhost/cb#x"])),
            "relativo": _raw(_doc(redirect_uris=["/callback"])),
            "javascript": _raw(_doc(redirect_uris=["javascript:alert(1)"])),
            "data": _raw(_doc(redirect_uris=["data:text/html,x"])),
            "demasiado largo": _raw(_doc(redirect_uris=["https://example.com/" + "a" * 2048])),
            "11 entradas": _raw(_doc(redirect_uris=[
                f"http://localhost/cb{i}" for i in range(11)])),
            "client_secret": _raw(_doc(client_secret="s")),
            "client_secret_expires_at": _raw(_doc(client_secret_expires_at=0)),
            "auth method": _raw(_doc(token_endpoint_auth_method="client_secret_basic")),
            "grant client_credentials": _raw(_doc(grant_types=["client_credentials"])),
            "response token": _raw(_doc(response_types=["token"])),
            "NaN": _raw(_doc())[:-1] + b', "x": NaN}',
            "Infinity": _raw(_doc())[:-1] + b', "x": Infinity}',
            "BOM": b"\xef\xbb\xbf" + _raw(_doc()),
            "no UTF-8 (latin-1)": json.dumps(
                _doc(client_name="Cláude"), ensure_ascii=False
            ).encode("utf-8").replace("á".encode("utf-8"), b"\xe1"),
            "raíz lista": _raw([_doc()]),
            "claves duplicadas": _raw(_doc())[:-1] + b', "client_name": "Otro"}',
            "JSON roto": b"{",
        }
        for nombre, raw in casos.items():
            with self.subTest(caso=nombre):
                with self.assertRaises(CimdInvalidError):
                    validate_document(CLAUDE_CODE_URL, raw)

    def test_non_utf8_is_detected(self) -> None:
        raw = _raw(_doc()).replace(b"Claude Code", b"Claude \xff")
        with self.assertRaises(CimdInvalidError) as ctx:
            validate_document(CLAUDE_CODE_URL, raw)
        self.assertEqual(ctx.exception.reason, "not_utf8")


# ── T017: caché y redirect_uri (FR-011, FR-012, FR-016, FR-017) ──


class TestCache(_FetchBase):
    async def _resolve_with(self, m: aioresponses, **kwargs) -> None:
        m.get(CLAUDE_CODE_URL, **kwargs)
        await self.resolver.resolve(CLAUDE_CODE_URL)

    async def test_second_resolution_within_lifetime_does_not_download(self) -> None:
        with aioresponses() as m:
            m.get(CLAUDE_CODE_URL, body=_raw(_doc()), repeat=True)
            await self.resolver.resolve(CLAUDE_CODE_URL)
            self.now += 100
            await self.resolver.resolve(CLAUDE_CODE_URL)
            llamadas = m.requests[("GET", URL(CLAUDE_CODE_URL))]
        self.assertEqual(len(llamadas), 1)

    async def test_lifetimes(self) -> None:
        casos = {
            "max-age=60": 300,
            "public, max-age=999999": 86_400,
            None: 3_600,
            "no-store": 300,
            "no-cache, max-age=7200": 300,
            "max-age=7200": 7_200,
            "max-age=abc": 3_600,
        }
        for cabecera, vida in casos.items():
            with self.subTest(cache_control=cabecera), aioresponses() as m:
                self.resolver.forget(CLAUDE_CODE_URL)
                headers = {"Cache-Control": cabecera} if cabecera else {}
                m.get(CLAUDE_CODE_URL, body=_raw(_doc()), headers=headers)
                await self.resolver.resolve(CLAUDE_CODE_URL)
                entrada = self.resolver._cache[CLAUDE_CODE_URL]
                self.assertEqual(entrada.expires_at - entrada.fetched_at, vida)

    async def test_stale_copy_used_on_temporary_failure_under_24h(self) -> None:
        with aioresponses() as m:
            m.get(CLAUDE_CODE_URL, body=_raw(_doc()))
            await self.resolver.resolve(CLAUDE_CODE_URL)
            self.now += 3_600 + 1          # caducada, pero de hace menos de 24 h
            m.get(CLAUDE_CODE_URL, status=500)
            client = await self.resolver.resolve(CLAUDE_CODE_URL)
        self.assertEqual(client.client_name, "Claude Code")

    async def test_stale_copy_not_used_after_24h(self) -> None:
        with aioresponses() as m:
            m.get(CLAUDE_CODE_URL, body=_raw(_doc()))
            await self.resolver.resolve(CLAUDE_CODE_URL)
            self.now += 86_400
            m.get(CLAUDE_CODE_URL, status=503)
            with self.assertRaises(CimdTemporaryError):
                await self.resolver.resolve(CLAUDE_CODE_URL)
        self.assertNotIn(CLAUDE_CODE_URL, self.resolver._cache)

    async def test_definitive_failure_after_expiry_drops_the_copy(self) -> None:
        for nombre, kwargs in (("404", {"status": 404}),
                               ("inválido", {"body": _raw(_doc(client_secret="s"))})):
            with self.subTest(caso=nombre), aioresponses() as m:
                self.resolver.forget(CLAUDE_CODE_URL)
                m.get(CLAUDE_CODE_URL, body=_raw(_doc()))
                await self.resolver.resolve(CLAUDE_CODE_URL)
                self.now += 3_601
                m.get(CLAUDE_CODE_URL, **kwargs)
                with self.assertRaises(CimdInvalidError):
                    await self.resolver.resolve(CLAUDE_CODE_URL)
                self.assertNotIn(CLAUDE_CODE_URL, self.resolver._cache)

    async def test_errors_are_never_cached(self) -> None:
        with aioresponses() as m:
            m.get(CLAUDE_CODE_URL, status=500)
            with self.assertRaises(CimdTemporaryError):
                await self.resolver.resolve(CLAUDE_CODE_URL)
            m.get(CLAUDE_CODE_URL, body=_raw(_doc(client_secret="s")))
            with self.assertRaises(CimdInvalidError):
                await self.resolver.resolve(CLAUDE_CODE_URL)
            m.get(CLAUDE_CODE_URL, body=_raw(_doc()))
            client = await self.resolver.resolve(CLAUDE_CODE_URL)
            llamadas = m.requests[("GET", URL(CLAUDE_CODE_URL))]
        self.assertEqual(client.client_name, "Claude Code")
        self.assertEqual(len(llamadas), 3)

    async def test_lru_evicts_the_oldest(self) -> None:
        urls = [f"https://c{i}.example.com/doc" for i in range(cimd.CACHE_MAX_ENTRIES + 1)]
        with aioresponses() as m:
            for i, u in enumerate(urls):
                m.get(u, body=_raw(_doc(u)))
                self.mono += 3      # fuera de la ventana del cupo
                await self.resolver.resolve(u)
        self.assertEqual(len(self.resolver._cache), cimd.CACHE_MAX_ENTRIES)
        self.assertNotIn(urls[0], self.resolver._cache)
        self.assertIn(urls[-1], self.resolver._cache)


class TestRedirectUriMatches(unittest.TestCase):
    def test_loopback_ignores_only_the_port(self) -> None:
        casan = [
            ("http://localhost/callback", "http://localhost:41000/callback"),
            ("http://localhost/callback", "http://localhost/callback"),
            ("http://127.0.0.1/callback", "http://127.0.0.1:53127/callback"),
            ("http://[::1]/cb", "http://[::1]:9/cb"),
            ("http://localhost:3000/cb?x=1", "http://localhost:41000/cb?x=1"),
        ]
        for reg, req in casan:
            with self.subTest(registered=reg, requested=req):
                self.assertTrue(redirect_uri_matches(reg, req))

    def test_mismatches(self) -> None:
        no_casan = [
            ("http://localhost/callback", "http://localhost:1/other"),
            ("http://localhost/callback?a=1", "http://localhost:1/callback?a=2"),
            ("http://localhost/callback", "http://localhost:1/callback?a=1"),
            ("http://localhost/callback", "https://localhost:1/callback"),
            ("http://localhost/callback", "http://localhost.evil.example:1/callback"),
            ("http://127.0.0.1/callback", "http://127.0.0.2:1/callback"),
            ("http://localhost/callback", "http://127.0.0.1:1/callback"),
            ("http://localhost/callback", "http://user@localhost:1/callback"),
            ("http://localhost/callback", "http://localhost:1/callback#f"),
            ("http://localhost/callback", "http://localhost:abc/callback"),
            # Fuera de loopback, igualdad exacta: el puerto cuenta.
            ("https://app.example.com/cb", "https://app.example.com:8443/cb"),
            ("http://app.example.com/cb", "http://app.example.com:8080/cb"),
            ("https://app.example.com/cb", "https://app.example.com/cb/"),
        ]
        for reg, req in no_casan:
            with self.subTest(registered=reg, requested=req):
                self.assertFalse(redirect_uri_matches(reg, req))

    def test_exact_equality_outside_loopback(self) -> None:
        self.assertTrue(redirect_uri_matches("https://app.example.com/cb",
                                             "https://app.example.com/cb"))


if __name__ == "__main__":
    unittest.main()
