"""`network_mode`: permite usar Hermes sin Tailscale.

El arranque no puede llamar siempre a `wait_for_tailscale0_ready()`, que
lanza `RuntimeError` si no encuentra una IP CGNAT. Nadie capturaba ese error,
así que terminaba en `sys.exit(1)`: **sin el add-on de Tailscale, Hermes no
arrancaba**. La IP obtenida solo se usaba en una línea de log, de modo que la
dependencia no aportaba nada funcional.

Con `network_mode: reverse_proxy` esa espera se salta y Hermes escucha en
`mcp_bind`, para que cualquier proxy inverso (Cloudflare Tunnel, Nginx Proxy
Manager, Caddy…) termine el TLS y le haga proxy.

Estos tests son la red de seguridad de esa ruta: la instalación de referencia
usa Tailscale, así que el modo `reverse_proxy` no se ejercita en producción.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from hermes.config import NETWORK_MODES, HermesConfig, load_config


def _valid(**over: object) -> HermesConfig:
    """Config mínima válida, con lo obligatorio ya relleno."""
    base: dict[str, object] = {
        "auth_password": "una-password-larga-y-aleatoria-1234",
        "public_hostname": "hermes.example.com",
        "supervisor_token": "token-de-prueba",
    }
    base.update(over)
    return HermesConfig(**base)  # type: ignore[arg-type]


class TestNetworkModeConfig(unittest.TestCase):
    def test_default_is_tailscale(self) -> None:
        """La instalación existente no debe cambiar de comportamiento."""
        cfg = _valid()
        self.assertEqual(cfg.network_mode, "tailscale")
        self.assertEqual(cfg.mcp_bind, "127.0.0.1")
        cfg.validate()

    def test_reverse_proxy_is_accepted(self) -> None:
        cfg = _valid(network_mode="reverse_proxy")
        cfg.validate()

    def test_unknown_mode_is_rejected_with_the_valid_ones(self) -> None:
        cfg = _valid(network_mode="wireguard")
        with self.assertRaises(ValueError) as ctx:
            cfg.validate()
        msg = str(ctx.exception)
        self.assertIn("wireguard", msg)
        for mode in NETWORK_MODES:
            self.assertIn(mode, msg)

    def test_empty_bind_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _valid(mcp_bind="").validate()

    def test_bind_can_be_the_hassio_bridge(self) -> None:
        """Un proxy en la red puente de HAOS no alcanza el loopback del host."""
        cfg = _valid(network_mode="reverse_proxy", mcp_bind="172.30.32.1")
        cfg.validate()
        self.assertEqual(cfg.mcp_bind, "172.30.32.1")

    def test_hostname_error_no_longer_assumes_tailscale(self) -> None:
        """El mensaje debe servir también a quien no usa Funnel."""
        with self.assertRaises(ValueError) as ctx:
            _valid(public_hostname="").validate()
        msg = str(ctx.exception).lower()
        self.assertIn("proxy inverso", msg)


class TestNetworkModeFromEnv(unittest.TestCase):
    """`run.sh` traduce las opciones del add-on a variables de entorno."""

    def _load(self, env: dict[str, str]) -> HermesConfig:
        full = {
            "HERMES_AUTH_PASSWORD": "una-password-larga-y-aleatoria-1234",
            "HERMES_PUBLIC_HOSTNAME": "hermes.example.com",
            "SUPERVISOR_TOKEN": "token-de-prueba",
        }
        full.update(env)
        with mock.patch.dict(os.environ, full, clear=False):
            return load_config()

    def test_env_defaults_preserve_tailscale(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HERMES_NETWORK_MODE", None)
            os.environ.pop("HERMES_MCP_BIND", None)
            cfg = self._load({})
        self.assertEqual(cfg.network_mode, "tailscale")
        self.assertEqual(cfg.mcp_bind, "127.0.0.1")

    def test_env_selects_reverse_proxy(self) -> None:
        cfg = self._load({"HERMES_NETWORK_MODE": "reverse_proxy",
                          "HERMES_MCP_BIND": "172.30.32.1"})
        self.assertEqual(cfg.network_mode, "reverse_proxy")
        self.assertEqual(cfg.mcp_bind, "172.30.32.1")

    def test_blank_env_falls_back_to_the_default(self) -> None:
        """`bashio::config` devuelve cadena vacía si la opción falta."""
        cfg = self._load({"HERMES_NETWORK_MODE": "   ", "HERMES_MCP_BIND": ""})
        self.assertEqual(cfg.network_mode, "tailscale")
        self.assertEqual(cfg.mcp_bind, "127.0.0.1")


class TestAddonManifest(unittest.TestCase):
    """Las opciones tienen que estar en config.yaml o no salen en la UI."""

    @staticmethod
    def _manifest() -> str:
        import pathlib
        return (pathlib.Path(__file__).resolve().parents[1] / "hermes" / "config.yaml").read_text(
            encoding="utf-8"
        )

    def test_options_are_declared_in_the_schema(self) -> None:
        m = self._manifest()
        self.assertIn('network_mode: "list(tailscale|reverse_proxy)?"', m)
        self.assertIn('mcp_bind: "str?"', m)

    def test_defaults_keep_the_current_installation_working(self) -> None:
        m = self._manifest()
        self.assertIn('network_mode: "tailscale"', m)
        self.assertIn('mcp_bind: "127.0.0.1"', m)

    def test_schema_offers_every_mode_the_code_accepts(self) -> None:
        """Si se añade un modo al código, el desplegable debe ofrecerlo."""
        m = self._manifest()
        declared = m.split('network_mode: "list(')[1].split(')')[0].split("|")
        self.assertEqual(set(declared), set(NETWORK_MODES))

    def test_run_sh_exports_both_options(self) -> None:
        import pathlib
        run = (pathlib.Path(__file__).resolve().parents[1] / "hermes" / "run.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("HERMES_NETWORK_MODE", run)
        self.assertIn("HERMES_MCP_BIND", run)


class TestBootSkipsTailscaleWait(unittest.IsolatedAsyncioTestCase):
    """El núcleo del cambio: en reverse_proxy NO se espera a Tailscale.

    Antes esta espera era incondicional y, sin el add-on de Tailscale, agotaba
    el tiempo, lanzaba RuntimeError y el arranque moría en sys.exit(1).
    """

    async def test_tailscale_mode_waits_and_returns_the_ip(self) -> None:
        from hermes import network

        with mock.patch.object(
            network, "wait_for_tailscale0_ready", new=mock.AsyncMock(return_value="100.1.2.3")
        ) as waiter:
            ip = await network.wait_for_tailscale_if_required(
                network_mode="tailscale", timeout_seconds=5
            )
        self.assertEqual(ip, "100.1.2.3")
        waiter.assert_awaited_once()

    async def test_reverse_proxy_never_calls_the_waiter(self) -> None:
        from hermes import network

        with mock.patch.object(
            network, "wait_for_tailscale0_ready", new=mock.AsyncMock()
        ) as waiter:
            ip = await network.wait_for_tailscale_if_required(
                network_mode="reverse_proxy", timeout_seconds=5, mcp_bind="172.30.32.1"
            )
        self.assertIsNone(ip)
        waiter.assert_not_awaited()

    async def test_reverse_proxy_survives_a_machine_without_tailscale(self) -> None:
        """Regresión directa: si el waiter reventara, el arranque moriría."""
        from hermes import network

        boom = mock.AsyncMock(side_effect=RuntimeError("No Tailscale CGNAT IP found"))
        with mock.patch.object(network, "wait_for_tailscale0_ready", new=boom):
            ip = await network.wait_for_tailscale_if_required(
                network_mode="reverse_proxy", timeout_seconds=5
            )
        self.assertIsNone(ip)

    async def test_tailscale_mode_still_propagates_the_failure(self) -> None:
        """Quien elige tailscale sí debe enterarse de que no está listo."""
        from hermes import network

        boom = mock.AsyncMock(side_effect=RuntimeError("No Tailscale CGNAT IP found"))
        with mock.patch.object(network, "wait_for_tailscale0_ready", new=boom):
            with self.assertRaises(RuntimeError):
                await network.wait_for_tailscale_if_required(
                    network_mode="tailscale", timeout_seconds=5
                )


if __name__ == "__main__":
    unittest.main()
