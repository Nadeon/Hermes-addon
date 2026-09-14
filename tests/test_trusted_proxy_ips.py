"""`trusted_proxy_ips`: que los límites por IP sigan siendo por IP tras un proxy.

uvicorn solo hace caso a `X-Forwarded-For` cuando la conexión llega desde una IP
de confianza, y de fábrica esa lista es solo `127.0.0.1`. Con
`network_mode: reverse_proxy` y `mcp_bind` en la red puente, la conexión llega
desde el proxy: uvicorn descarta la cabecera y **todas** las peticiones se ven
con la misma IP, así que el cubo pre-auth (20/min), el de fallos de
autenticación y el freno por IP del login se convierten en un único cubo global.

La opción `trusted_proxy_ips` alimenta `forwarded_allow_ips`. Estos tests cubren
las cuatro capas por las que viaja el valor —manifiesto, run.sh, config y el
middleware de uvicorn— porque un fallo en cualquiera de ellas se ve igual desde
fuera: nada, hasta que alguien fuerza el login y nadie lo frena.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any

import yaml

from hermes.__main__ import build_forwarded_allow_ips
from hermes.config import HermesConfig, load_config

RAIZ = Path(__file__).resolve().parents[1]
CONFIG_YAML = RAIZ / "hermes" / "config.yaml"
RUN_SH = RAIZ / "hermes" / "run.sh"


def _valida(**over: object) -> HermesConfig:
    """Config mínima válida, con lo obligatorio ya relleno."""
    base: dict[str, object] = {
        "auth_password": "T7qm-Zx4Vk9bRw2s",
        "public_hostname": "hermes.example.com",
        "supervisor_token": "token-de-prueba",
    }
    base.update(over)
    return HermesConfig(**base)  # type: ignore[arg-type]


class TestConfigDeProxiesDeConfianza(unittest.TestCase):
    def test_por_defecto_no_se_confia_en_nadie(self) -> None:
        """Quien no toca la opción no debe empezar a creerse cabeceras."""
        cfg = _valida()
        self.assertEqual(cfg.trusted_proxy_ips, [])
        cfg.validate()

    def test_una_ip_suelta_es_valida(self) -> None:
        _valida(trusted_proxy_ips=["172.30.32.2"]).validate()

    def test_un_rango_cidr_es_valido(self) -> None:
        """La red puente de HAOS entera es el caso de uso principal."""
        _valida(trusted_proxy_ips=["172.30.32.0/23"]).validate()

    def test_ipv6_tambien_vale(self) -> None:
        _valida(trusted_proxy_ips=["::1", "fd00::/8"]).validate()

    def test_cidr_con_bits_de_host_se_acepta(self) -> None:
        """Copiar la IP del gateway y añadirle la máscara es lo que hace todo
        el mundo; `ip_network(strict=False)` lo interpreta como su red."""
        _valida(trusted_proxy_ips=["172.30.32.1/23"]).validate()

    def test_una_entrada_que_no_es_ip_se_rechaza_al_arrancar(self) -> None:
        """uvicorn se la tragaría en silencio como literal que no casa nunca."""
        for basura in ("172.30.32", "172.30.32,1", "proxy.local", "172.30.32.0/99"):
            with self.subTest(valor=basura):
                with self.assertRaises(ValueError) as ctx:
                    _valida(trusted_proxy_ips=[basura]).validate()
                self.assertIn(basura, str(ctx.exception))

    def test_el_mensaje_explica_que_escribir(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _valida(trusted_proxy_ips=["no-soy-una-ip"]).validate()
        mensaje = str(ctx.exception)
        self.assertIn("trusted_proxy_ips", mensaje)
        self.assertIn("CIDR", mensaje)

    def test_una_entrada_mala_invalida_la_lista_entera(self) -> None:
        with self.assertRaises(ValueError):
            _valida(trusted_proxy_ips=["172.30.32.2", "ups"]).validate()


class TestCargaDesdeElEntorno(unittest.TestCase):
    """`run.sh` entrega la lista como array JSON en HERMES_TRUSTED_PROXY_IPS."""

    def _load(self, env: dict[str, str]) -> HermesConfig:
        full = {
            "HERMES_AUTH_PASSWORD": "T7qm-Zx4Vk9bRw2s",
            "HERMES_PUBLIC_HOSTNAME": "hermes.example.com",
            "SUPERVISOR_TOKEN": "token-de-prueba",
        }
        full.update(env)
        with mock.patch.dict(os.environ, full, clear=False):
            return load_config()

    def test_lista_vacia(self) -> None:
        cfg = self._load({"HERMES_TRUSTED_PROXY_IPS": "[]"})
        self.assertEqual(cfg.trusted_proxy_ips, [])

    def test_lista_con_valores(self) -> None:
        cfg = self._load(
            {"HERMES_TRUSTED_PROXY_IPS": '["172.30.32.0/23","10.0.0.7"]'}
        )
        self.assertEqual(cfg.trusted_proxy_ips, ["172.30.32.0/23", "10.0.0.7"])

    def test_variable_ausente_no_rompe_el_arranque(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HERMES_TRUSTED_PROXY_IPS", None)
            cfg = self._load({})
        self.assertEqual(cfg.trusted_proxy_ips, [])


class TestListaEfectivaParaUvicorn(unittest.TestCase):
    def test_el_loopback_va_siempre(self) -> None:
        """Es el caso de `tailscale`: tailscaled hace proxy desde el loopback."""
        self.assertEqual(build_forwarded_allow_ips([]), ["127.0.0.1"])

    def test_las_de_la_opcion_se_añaden_detras(self) -> None:
        self.assertEqual(
            build_forwarded_allow_ips(["172.30.32.0/23"]),
            ["127.0.0.1", "172.30.32.0/23"],
        )

    def test_no_se_repiten_entradas(self) -> None:
        self.assertEqual(
            build_forwarded_allow_ips(["127.0.0.1", "10.0.0.7", "10.0.0.7"]),
            ["127.0.0.1", "10.0.0.7"],
        )

    def test_se_limpian_los_espacios(self) -> None:
        self.assertEqual(
            build_forwarded_allow_ips(["  10.0.0.7 ", "   "]),
            ["127.0.0.1", "10.0.0.7"],
        )


class TestMiddlewareDeUvicorn(unittest.IsolatedAsyncioTestCase):
    """El efecto real: qué IP acaba viendo el stack de rate limiting.

    Se ejercita el `ProxyHeadersMiddleware` del uvicorn instalado —no una
    reimplementación— con la lista que calcula Hermes, porque lo que se quiere
    comprobar es que ESA versión entiende los rangos CIDR: si no los entendiera,
    los guardaría como literales que no casan con nadie y el arranque seguiría
    tan contento con los límites colapsados.
    """

    async def _ip_vista(
        self, trusted: list[str], peer: str, x_forwarded_for: str
    ) -> str:
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

        visto: dict[str, Any] = {}

        async def app(scope: Any, receive: Any, send: Any) -> None:
            cliente = scope.get("client")
            visto["ip"] = cliente[0] if cliente else None
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = ProxyHeadersMiddleware(
            app, trusted_hosts=build_forwarded_allow_ips(trusted)
        )

        scope = {
            "type": "http",
            "scheme": "http",
            "client": (peer, 54321),
            "headers": [(b"x-forwarded-for", x_forwarded_for.encode())],
        }

        async def receive() -> dict[str, Any]:  # pragma: no cover — no hay body
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(_message: dict[str, Any]) -> None:
            return None

        await middleware(scope, receive, send)
        return visto["ip"]

    async def test_sin_la_opcion_todo_se_ve_con_la_ip_del_proxy(self) -> None:
        """El bug: con el bind en la red puente, un único cubo para todos."""
        ip = await self._ip_vista([], peer="172.30.32.1", x_forwarded_for="203.0.113.9")
        self.assertEqual(ip, "172.30.32.1")

    async def test_con_el_rango_de_la_puente_se_recupera_la_ip_del_cliente(self) -> None:
        ip = await self._ip_vista(
            ["172.30.32.0/23"], peer="172.30.32.1", x_forwarded_for="203.0.113.9"
        )
        self.assertEqual(ip, "203.0.113.9")

    async def test_con_la_ip_exacta_del_proxy_tambien(self) -> None:
        ip = await self._ip_vista(
            ["172.30.32.1"], peer="172.30.32.1", x_forwarded_for="203.0.113.9"
        )
        self.assertEqual(ip, "203.0.113.9")

    async def test_un_peer_fuera_del_rango_no_puede_falsificar_su_ip(self) -> None:
        """Confiar en la puente no es confiar en todo el que sepa poner la
        cabecera: desde fuera del rango, se sigue viendo la IP del socket."""
        ip = await self._ip_vista(
            ["172.30.32.0/23"], peer="10.9.9.9", x_forwarded_for="203.0.113.9"
        )
        self.assertEqual(ip, "10.9.9.9")

    async def test_el_loopback_sigue_funcionando_sin_configurar_nada(self) -> None:
        """Modo `tailscale`: no debe cambiar de comportamiento."""
        ip = await self._ip_vista([], peer="127.0.0.1", x_forwarded_for="203.0.113.9")
        self.assertEqual(ip, "203.0.113.9")


class TestManifiestoYRunSh(unittest.TestCase):
    """La opción tiene que estar en config.yaml o no sale en el formulario."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.manifiesto = yaml.safe_load(CONFIG_YAML.read_text(encoding="utf-8"))
        cls.run_sh = RUN_SH.read_text(encoding="utf-8")

    def test_esta_declarada_como_lista_de_strings(self) -> None:
        self.assertEqual(self.manifiesto["schema"]["trusted_proxy_ips"], ["str?"])

    def test_por_defecto_esta_vacia(self) -> None:
        self.assertEqual(self.manifiesto["options"]["trusted_proxy_ips"], [])

    def test_el_comentario_avisa_del_riesgo_y_del_caso_de_uso(self) -> None:
        """Quien lea el manifiesto tiene que saber qué rango poner y qué cede."""
        texto = CONFIG_YAML.read_text(encoding="utf-8")
        bloque = texto.split("trusted_proxy_ips:")[0]
        self.assertIn("172.30.32.0/23", bloque)
        self.assertIn("X-Forwarded-For", bloque)
        self.assertIn("AVISO", bloque)

    def test_run_sh_la_exporta(self) -> None:
        self.assertIn("HERMES_TRUSTED_PROXY_IPS", self.run_sh)


@unittest.skipIf(shutil.which("jq") is None, "jq no está instalado")
@unittest.skipIf(shutil.which("sh") is None, "sh no está instalado")
class TestExportDeRunSh(unittest.TestCase):
    """Se ejecuta la línea REAL de run.sh, no una copia que se desincronice."""

    @classmethod
    def setUpClass(cls) -> None:
        texto = RUN_SH.read_text(encoding="utf-8")
        linea = re.search(
            r"^export HERMES_TRUSTED_PROXY_IPS=.*$", texto, re.MULTILINE
        )
        assert linea is not None, "run.sh no exporta HERMES_TRUSTED_PROXY_IPS"
        cls.linea = linea.group(0)

    def _exportar(self, opciones: dict[str, object]) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            options_path = Path(tmp) / "options.json"
            options_path.write_text(json.dumps(opciones), encoding="utf-8")
            script = (
                f'OPTIONS="{options_path}"\n'
                f"{self.linea}\n"
                'printf "%s" "$HERMES_TRUSTED_PROXY_IPS"\n'
            )
            proc = subprocess.run(
                ["sh", "-c", script], capture_output=True, text=True, timeout=30
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_lista_con_valores_viaja_como_json(self) -> None:
        salida = self._exportar({"trusted_proxy_ips": ["172.30.32.0/23", "10.0.0.7"]})
        self.assertEqual(json.loads(salida), ["172.30.32.0/23", "10.0.0.7"])

    def test_lista_vacia_viaja_como_array_vacio(self) -> None:
        self.assertEqual(json.loads(self._exportar({"trusted_proxy_ips": []})), [])

    def test_clave_ausente_da_array_vacio(self) -> None:
        """Una instalación que actualiza no tiene la clave en options.json."""
        self.assertEqual(json.loads(self._exportar({})), [])

    def test_clave_a_null_da_array_vacio(self) -> None:
        self.assertEqual(json.loads(self._exportar({"trusted_proxy_ips": None})), [])

    def test_lo_exportado_lo_entiende_load_config(self) -> None:
        """Las dos mitades del puente, atornilladas: shell → entorno → config."""
        salida = self._exportar({"trusted_proxy_ips": ["172.30.32.0/23"]})
        entorno = {
            "HERMES_AUTH_PASSWORD": "T7qm-Zx4Vk9bRw2s",
            "HERMES_PUBLIC_HOSTNAME": "hermes.example.com",
            "SUPERVISOR_TOKEN": "token-de-prueba",
            "HERMES_TRUSTED_PROXY_IPS": salida,
        }
        with mock.patch.dict(os.environ, entorno, clear=False):
            cfg = load_config()
        self.assertEqual(cfg.trusted_proxy_ips, ["172.30.32.0/23"])
        cfg.validate()


class TestArranqueDeUvicorn(unittest.TestCase):
    """El valor tiene que llegar a `uvicorn.Config`, no quedarse en la config."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fuente = (RAIZ / "hermes" / "src" / "hermes" / "__main__.py").read_text(
            encoding="utf-8"
        )

    def test_se_pasa_a_uvicorn(self) -> None:
        self.assertIn("forwarded_allow_ips=forwarded_allow_ips", self.fuente)
        self.assertIn("proxy_headers=True", self.fuente)

    def test_se_registra_en_el_log_de_arranque(self) -> None:
        """Sin esto no hay forma de comprobar qué quedó configurado."""
        self.assertIn("trusted_proxy_ips=forwarded_allow_ips", self.fuente)


if __name__ == "__main__":
    unittest.main()
