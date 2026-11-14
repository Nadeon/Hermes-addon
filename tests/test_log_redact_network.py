"""Redacción de datos de red en el log (spec 003, US6, FR-045…FR-049).

El repositorio es público y el log es lo que más se pega en un issue: hasta
1.0.12 salían en claro el hostname de Tailscale, la IP de la tailnet, la IP de
cada cliente y la cabecera `Host` que el SDK de MCP registra al rechazar una
petición. Estos tests fijan que, con la redacción activa, nada de eso sale,
pero que el log sigue sirviendo para diagnosticar: la misma IP lleva siempre el
mismo seudónimo y la clase (tailnet, privada, pública…) queda a la vista.

Todos los ejemplos son ficticios: `homeassistant.tailXXXX.ts.net` y rangos de
documentación. `1.1.1.1` (un resolvedor DNS público conocido) es la única IP
pública real, porque hace falta una para probar la clase `public` y los
rangos de documentación no son globales.
"""

from __future__ import annotations

import io
import json
import logging
import re
import unittest

import structlog

from hermes import logging_setup
from hermes.logging_setup import (
    configure_network_redaction,
    redact_network,
    setup_logging,
)

HOST = "homeassistant.tailXXXX.ts.net"
_SEUDONIMO = re.compile(r"<ip:(tailnet|link-local|private|public|other):[0-9a-f]{8}>")


def _seudonimo(texto: str) -> str:
    """Devuelve el único seudónimo de `texto` (falla si no hay exactamente uno)."""
    hallados = _SEUDONIMO.findall(texto)
    assert len(hallados) == 1, f"se esperaba un seudónimo en {texto!r}"
    return _SEUDONIMO.search(texto).group(0)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        configure_network_redaction(True, HOST)

    def tearDown(self) -> None:
        # El estado es del módulo: dejarlo desactivado, como en el arranque,
        # para no contaminar el resto de la suite.
        configure_network_redaction(False, "")


# ── T047: el redactor en sí ──────────────────────────────────────────────────


class TestHostname(_Base):
    def test_hostname_minusculas(self) -> None:
        self.assertEqual(redact_network(f"host={HOST}"), "host=<public_hostname>")

    def test_hostname_mayusculas(self) -> None:
        self.assertEqual(redact_network(HOST.upper()), "<public_hostname>")

    def test_hostname_con_puerto(self) -> None:
        out = redact_network(f"{HOST}:8443")
        self.assertNotIn("tailXXXX", out)
        self.assertTrue(out.startswith("<public_hostname>"))

    def test_hostname_en_url(self) -> None:
        out = redact_network(f"issuer https://{HOST}:8443/oauth ok")
        self.assertEqual(out, "issuer https://<public_hostname>:8443/oauth ok")

    def test_hostname_configurado_con_puerto(self) -> None:
        # `public_hostname` admite puerto; el hostname se redacta igual.
        configure_network_redaction(True, f"{HOST}:8443")
        self.assertEqual(redact_network(f"https://{HOST}/x"), "https://<public_hostname>/x")

    def test_otro_ts_net(self) -> None:
        self.assertEqual(
            redact_network("peer otro.tailYYYY.ts.net conectado"),
            "peer <redacted>.ts.net conectado",
        )


class TestIPs(_Base):
    def _clase(self, ip: str) -> str:
        out = redact_network(f"src_ip={ip}")
        self.assertNotIn(ip, out)
        return _SEUDONIMO.search(out).group(1)

    def test_clases(self) -> None:
        casos = {
            "203.0.113.7": "other",  # documentación: no es global
            "1.1.1.1": "public",
            "172.30.32.2": "private",  # red interna del Supervisor
            "100.64.0.7": "tailnet",
            "10.0.0.5": "private",
            "169.254.1.1": "link-local",
            "fd7a:115c:a1e0::1": "tailnet",
            "fd00::1": "private",
            "::ffff:10.0.0.5": "private",
        }
        for ip, clase in casos.items():
            with self.subTest(ip=ip):
                self.assertEqual(self._clase(ip), clase)

    def test_ipv6_entre_corchetes_con_puerto(self) -> None:
        out = redact_network("origin=[2001:db8::1]:443")
        self.assertNotIn("2001:db8", out)
        self.assertRegex(out, r"^origin=\[<ip:other:[0-9a-f]{8}>\]:443$")

    def test_loopback_intacto(self) -> None:
        for texto in ("127.0.0.1", "::1", "http://127.0.0.1:8099/mcp"):
            with self.subTest(texto=texto):
                self.assertEqual(redact_network(texto), texto)

    def test_misma_ip_mismo_seudonimo(self) -> None:
        a = _seudonimo(redact_network("203.0.113.7"))
        b = _seudonimo(redact_network("otra vez 203.0.113.7"))
        c = _seudonimo(redact_network("203.0.113.8"))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_reconfigurar_cambia_el_seudonimo(self) -> None:
        # La sal es aleatoria en cada configuración: sin ella, el hash de una
        # IPv4 se invierte por fuerza bruta en segundos.
        a = _seudonimo(redact_network("203.0.113.7"))
        configure_network_redaction(True, HOST)
        b = _seudonimo(redact_network("203.0.113.7"))
        self.assertNotEqual(a, b)

    def test_falsos_positivos_intactos(self) -> None:
        for texto in (
            "version 2026.11.1",
            "999.1.1.1",
            "2026-11-14T06:54:12Z",
            "build v1.2.3.4-beta",
            "mac aa:bb:cc:dd:ee:ff",
        ):
            with self.subTest(texto=texto):
                self.assertEqual(redact_network(texto), texto)

    def test_ip_en_texto_libre(self) -> None:
        out = redact_network("Cannot connect to host 172.30.32.2:80 ssl:default")
        self.assertNotIn("172.30.32.2", out)
        self.assertIn(":80 ssl:default", out)

    def test_desactivado_no_toca_nada(self) -> None:
        configure_network_redaction(False, HOST)
        texto = f"{HOST} 203.0.113.7 otro.tailYYYY.ts.net"
        self.assertEqual(redact_network(texto), texto)


# ── T048: integración en el log ──────────────────────────────────────────────


class TestSetupLogging(unittest.TestCase):
    """`setup_logging` reconfigura structlog y el logging estándar.

    Se capturan las líneas con manejadores propios sobre el logger raíz. El
    processor de structlog se prueba con un manejador añadido DESPUÉS de
    `setup_logging` (sin el filtro), para que cada mecanismo tenga su propio
    test y el control negativo de uno no lo tape el otro.
    """

    def setUp(self) -> None:
        self.root = logging.getLogger()
        self.nivel_previo = self.root.level
        # Bajo pytest el raíz ya tiene manejadores y `basicConfig` no fija el
        # nivel; sin esto `filter_by_level` descartaría los `info`.
        self.root.setLevel(logging.INFO)
        self.antes = io.StringIO()
        self.h_antes = logging.StreamHandler(self.antes)
        self.root.addHandler(self.h_antes)

    def _quitar_filtros(self) -> None:
        for h in list(self.root.handlers):
            for f in list(h.filters):
                if isinstance(f, logging_setup._NetworkRedactionFilter):
                    h.removeFilter(f)

    def tearDown(self) -> None:
        self._quitar_filtros()
        self.root.removeHandler(self.h_antes)
        if getattr(self, "h_despues", None) is not None:
            self.root.removeHandler(self.h_despues)
        self.root.setLevel(self.nivel_previo)
        configure_network_redaction(False, "")
        structlog.reset_defaults()

    def _evento_structlog(self, **kwargs) -> dict:
        # El filtro modifica el registro compartido por todos los manejadores:
        # si siguiera puesto, taparía un processor ausente. Se quita para que
        # aquí solo actúe el processor.
        self._quitar_filtros()
        self.despues = io.StringIO()
        self.h_despues = logging.StreamHandler(self.despues)
        self.root.addHandler(self.h_despues)
        structlog.get_logger("test_redact").info("hermes_started", **kwargs)
        return json.loads(self.despues.getvalue().strip().splitlines()[-1])

    def _evento_completo(self) -> dict:
        return self._evento_structlog(
            public_hostname=HOST,
            src_ip="203.0.113.7",
            trusted_proxy_ips=["127.0.0.1", "172.30.32.2"],
            extra={"tailscale_ip": "100.64.12.34", "url": f"https://{HOST}/mcp"},
            error="Cannot connect to host 198.51.100.9:443",
            detalle="password=hunter2 Bearer abc.def",
        )

    def test_processor_redacta_campos(self) -> None:
        setup_logging("info", redact_network=True, public_hostname=HOST)
        ev = self._evento_completo()
        blob = json.dumps(ev)
        for dato in (HOST, "203.0.113.7", "172.30.32.2", "100.64.12.34", "198.51.100.9"):
            self.assertNotIn(dato, blob)
        self.assertEqual(ev["public_hostname"], "<public_hostname>")
        self.assertEqual(ev["trusted_proxy_ips"][0], "127.0.0.1")
        self.assertRegex(ev["extra"]["tailscale_ip"], r"^<ip:tailnet:[0-9a-f]{8}>$")
        self.assertNotIn("hunter2", blob)

    def test_aviso_del_sdk_redactado(self) -> None:
        setup_logging("info", redact_network=True, public_hostname=HOST)
        logging.getLogger("mcp.server.transport_security").warning(
            "Invalid Host header: %s", "198.51.100.9"
        )
        salida = self.antes.getvalue()
        self.assertIn("Invalid Host header: <ip:other:", salida)
        self.assertNotIn("198.51.100.9", salida)

    def test_traza_estandar_redactada(self) -> None:
        setup_logging("info", redact_network=True, public_hostname=HOST)
        try:
            raise ConnectionError(f"no route to {HOST} via 10.0.0.5")
        except ConnectionError:
            logging.getLogger("aiohttp.client").exception("fallo")
        salida = self.antes.getvalue()
        self.assertIn("Traceback", salida)
        self.assertNotIn(HOST, salida)
        self.assertNotIn("10.0.0.5", salida)

    def test_desactivado_deja_red_pero_redacta_secretos(self) -> None:
        setup_logging("info", redact_network=False, public_hostname=HOST)
        ev = self._evento_completo()
        self.assertEqual(ev["public_hostname"], HOST)
        self.assertEqual(ev["src_ip"], "203.0.113.7")
        self.assertNotIn("hunter2", ev["detalle"])
        self.assertNotIn("abc.def", ev["detalle"])
        logging.getLogger("mcp.server.transport_security").warning(
            "Invalid Host header: %s", "198.51.100.9"
        )
        self.assertIn("Invalid Host header: 198.51.100.9", self.antes.getvalue())

    def test_filtro_no_se_duplica(self) -> None:
        setup_logging("info", redact_network=True, public_hostname=HOST)
        setup_logging("info", redact_network=True, public_hostname=HOST)
        filtros = [
            f for f in self.h_antes.filters
            if isinstance(f, logging_setup._NetworkRedactionFilter)
        ]
        self.assertEqual(len(filtros), 1)


# ── T049: sv_get_addon_logs ──────────────────────────────────────────────────


class _MCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


class _Supervisor:
    """Supervisor simulado: solo responde a `sv_request_text`."""

    def __init__(self, textos: dict[str, str]) -> None:
        self.textos = textos

    async def sv_request_text(self, sv_path, params=None, timeout_seconds=60.0) -> str:
        return self.textos[sv_path]


_LINEAS = (
    f'{{"event": "hermes_started", "public_hostname": "{HOST}", '
    '"tailscale_ip": "100.64.12.34"}\n'
    "Invalid Host header: 198.51.100.9\n"
    "password: hunter2\n"
)


class TestSvGetAddonLogs(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from hermes.tools.addons import register

        configure_network_redaction(True, HOST)
        self.slugs = ("local_hermes", "a1b2c3d4_hermes", "core_mosquitto")
        cliente = _Supervisor({f"/addons/{s}/logs": _LINEAS for s in self.slugs})
        mcp = _MCP()
        register(mcp, cliente)
        self.tool = mcp.tools["sv_get_addon_logs"]

    def tearDown(self) -> None:
        configure_network_redaction(False, "")

    async def test_hermes_redactado(self) -> None:
        for slug in ("local_hermes", "a1b2c3d4_hermes"):
            with self.subTest(slug=slug):
                out = await self.tool(slug)
                self.assertTrue(out["redacted"])
                for dato in (HOST, "100.64.12.34", "198.51.100.9", "hunter2"):
                    self.assertNotIn(dato, out["logs"])
                self.assertIn("<public_hostname>", out["logs"])
                self.assertIn("Invalid Host header: <ip:other:", out["logs"])

    async def test_otro_addon_solo_secretos(self) -> None:
        # Las IPs de otro add-on (un broker MQTT, un proxy) son justo lo que
        # se quiere ver al diagnosticarlo; como en 1.0.12, solo secretos.
        out = await self.tool("core_mosquitto")
        self.assertIn(HOST, out["logs"])
        self.assertIn("198.51.100.9", out["logs"])
        self.assertNotIn("hunter2", out["logs"])

    async def test_desactivado_sin_cambios(self) -> None:
        configure_network_redaction(False, HOST)
        out = await self.tool("local_hermes")
        self.assertIn(HOST, out["logs"])
        self.assertIn("198.51.100.9", out["logs"])
        self.assertNotIn("hunter2", out["logs"])


if __name__ == "__main__":
    unittest.main()
