"""Tools de la red y el HTTP de Core (spec 021, tramo c; T038, T039 y T040).

`ha_update_network_config`, `ha_update_http_config` y `ha_promote_http_config`
con Home Assistant simulado: un `AsyncMock` de `ws_send` que responde por
`type` y FALLA si recibe una escritura (`network/configure`,
`http/config/configure`, `http/config/promote`) que el test no espera. Datos
ficticios: `192.0.2.10`, `/ssl/fullchain.pem` y el centinela `centinela-021`,
que no pueden aparecer en el log de Hermes.

Controles negativos (T056), comprobados y con recuentos en el commit:
(a) fundir siempre sobre `stable` → cae `test_funde_sobre_pending`;
(b) no quitar los metadatos → cae `test_confirmacion_manda_el_documento`;
(c) mandar solo los cambios → cae `test_confirmacion_manda_el_documento`;
(d) sin bloqueo de reinicio al confirmar → cae
`test_bloqueo_al_confirmar`; (e) sin el rechazo de `server_host` (D-3) →
caen los de `TestServerHost`; (f) promover sin mirar `active_config_type` →
cae `test_no_funciona_con_la_pendiente`.
"""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from structlog.testing import capture_logs

import hermes.security as security
import hermes.tools.core_network as mod
from hermes.ha import HAConnectionError

_CENTINELA = "centinela-021"
_IP = "192.0.2.10"
_CERT = "/ssl/fullchain.pem"
_KEY = "/ssl/privkey.pem"

_ADAPTADORES = [
    {"name": "eth0", "index": 2, "enabled": True, "auto": True, "default": True,
     "ipv4": [{"address": _IP, "network_prefix": 24}], "ipv6": []},
    {"name": "wlan0", "index": 3, "enabled": True, "auto": True, "default": False,
     "ipv4": [{"address": "192.0.2.11", "network_prefix": 24}], "ipv6": []},
    {"name": "docker0", "index": 4, "enabled": False, "auto": False, "default": False,
     "ipv4": [{"address": "192.0.2.12", "network_prefix": 24}], "ipv6": []},
]

_DEFECTO = {"server_port": 8123, "cors_allowed_origins": ["https://cast.home-assistant.io"],
            "login_attempts_threshold": -1, "ip_ban_enabled": True,
            "ssl_profile": "modern_v5", "use_x_frame_options": True,
            "created_at": "2026-11-15T00:00:00+00:00", "error": None,
            "error_message": None}
_ESTABLE = {**_DEFECTO, "created_at": "2026-11-14T00:00:00+00:00"}


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.adaptadores = copy.deepcopy(_ADAPTADORES)
        self.configurados: list[str] = []
        self.http: dict[str, Any] = {
            "stable": copy.deepcopy(_ESTABLE), "pending": None, "revert_at": None,
            "active_config_type": "stable", "default": copy.deepcopy(_DEFECTO)}
        self.enviados: list[dict[str, Any]] = []
        self.escrituras_esperadas = 0
        self.fallo_escritura: HAConnectionError | None = None
        self.fallo_lectura: HAConnectionError | None = None
        self.permitido = (True, "")
        self.ha = MagicMock()
        self.ha.wait_ready = AsyncMock(return_value=True)
        self.ha.ws_send = AsyncMock(side_effect=self._ws_send)
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha, response_max_bytes=131_072)
        self.t = self.mcp.tools
        self._parche = patch.object(mod, "_check_restart_allowed",
                                    side_effect=lambda: self.permitido)
        self._parche.start()

    async def asyncTearDown(self) -> None:
        self._parche.stop()
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    def escrituras(self) -> list[dict[str, Any]]:
        return [p for p in self.enviados
                if p["type"] in ("network/configure", "http/config/configure",
                                 "http/config/promote")]

    async def _ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.enviados.append(payload)
        tipo = payload["type"]
        if tipo in ("network", "http/config") and self.fallo_lectura is not None:
            raise self.fallo_lectura
        if tipo == "network":
            return {"adapters": copy.deepcopy(self.adaptadores),
                    "configured_adapters": list(self.configurados)}
        if tipo == "http/config":
            return copy.deepcopy(self.http)
        if tipo in ("network/configure", "http/config/configure", "http/config/promote"):
            if len(self.escrituras()) > self.escrituras_esperadas:
                raise AssertionError(f"escritura inesperada: {payload}")
            if self.fallo_escritura is not None:
                raise self.fallo_escritura
            if tipo == "network/configure":
                self.configurados = list(payload["config"]["configured_adapters"])
                return {"configured_adapters": self.configurados}
            if tipo == "http/config/configure":
                anterior = self.http["pending"]
                self.http["pending"] = payload["config"]
                return {"restart": payload["config"] != anterior}
            return None
        raise AssertionError(f"comando inesperado: {payload}")

    async def confirmar(self, tool: str, **args: Any) -> Any:
        vista = await self.t[tool](**args)
        self.assertIn("confirmation_token", vista, vista)
        self.escrituras_esperadas += 1
        return await self.t[tool](**args, confirmation_token=vista["confirmation_token"])


# ── ha_update_network_config (T038) ──────────────────────────────────────────


class TestRed(_Base):
    async def test_validacion_sin_escritura(self) -> None:
        for valor in (["eth9"], ["eth0", "eth0"], [f"e{i}" for i in range(33)], "eth0",
                      [3]):
            with self.subTest(valor=valor):
                r = await self.t["ha_update_network_config"](configured_adapters=valor)
                self.assertEqual(r["error"], "invalid_argument")
                self.assertEqual(r["field"], "configured_adapters")
        r = await self.t["ha_update_network_config"](configured_adapters=["eth9"])
        self.assertEqual(r["available"], ["docker0", "eth0", "wlan0"])
        self.assertEqual(self.escrituras(), [])

    async def test_vista_previa(self) -> None:
        r = await self.t["ha_update_network_config"](configured_adapters=["eth0"])
        p = r["preview"]
        self.assertEqual(p["configured_adapters"], {"before": [], "after": ["eth0"]})
        self.assertEqual(p["enabled"], {"before": ["eth0", "wlan0"], "after": ["eth0"]})
        self.assertIn("does not change the address or port", p["note"])
        self.assertEqual(self.escrituras(), [])

    async def test_lista_vacia_son_los_auto(self) -> None:
        self.configurados = ["docker0"]
        r = await self.t["ha_update_network_config"](configured_adapters=[])
        self.assertEqual(r["preview"]["enabled"],
                         {"before": ["docker0"], "after": ["eth0", "wlan0"]})

    async def test_no_changes(self) -> None:
        self.configurados = ["eth0"]
        r = await self.t["ha_update_network_config"](configured_adapters=["eth0"])
        self.assertEqual(r, {"result": "no_changes"})

    async def test_confirmacion(self) -> None:
        r = await self.confirmar("ha_update_network_config", configured_adapters=["eth0"])
        self.assertEqual(r, {"result": "ok", "configured_adapters": ["eth0"]})
        self.assertEqual(self.escrituras(), [{"type": "network/configure",
                                              "config": {"configured_adapters": ["eth0"]}}])

    async def test_estado_cambiado_no_escribe(self) -> None:
        vista = await self.t["ha_update_network_config"](configured_adapters=["eth0"])
        self.configurados = ["wlan0"]
        self.escrituras_esperadas = 1
        r = await self.t["ha_update_network_config"](
            configured_adapters=["eth0"], confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], security.ESTADO_CAMBIADO)
        self.assertEqual(self.escrituras(), [])

    async def test_log_sin_nombres_ni_direcciones(self) -> None:
        with capture_logs() as logs:
            await self.confirmar("ha_update_network_config", configured_adapters=["eth0"])
            await self.t["ha_update_network_config"](configured_adapters=["eth9"])
        texto = repr(logs)
        for valor in ("eth0", "eth9", "wlan0", _IP):
            self.assertNotIn(valor, texto)


# ── ha_update_http_config (T039) ─────────────────────────────────────────────


class TestHttpValidacion(_Base):
    async def test_validacion_sin_llamar(self) -> None:
        casos = [
            ({}, "changes"),
            ({"changes": {"server_port": 8443}, "discard_pending": True}, "changes"),
            ({"changes": {"base_url": "x"}}, "base_url"),
            ({"changes": {"server_port": "8443"}}, "server_port"),
            ({"changes": {"server_port": 70000}}, "server_port"),
            ({"changes": {"server_port": True}}, "server_port"),
            ({"changes": {"ip_ban_enabled": "yes"}}, "ip_ban_enabled"),
            ({"changes": {"login_attempts_threshold": 0}}, "login_attempts_threshold"),
            ({"changes": {"server_host": []}}, "server_host"),
            ({"changes": {"trusted_proxies": _IP}}, "trusted_proxies"),
            ({"changes": {"ssl_certificate": ""}}, "ssl_certificate"),
            ({"discard_pending": "true"}, "discard_pending"),
        ]
        for args, campo in casos:
            with self.subTest(args=args):
                r = await self.t["ha_update_http_config"](**args)
                self.assertEqual(r["error"], "invalid_argument", r)
                self.assertEqual(r["field"], campo)
        self.assertEqual(self.enviados, [])

    async def test_forwarded_sin_proxies_en_el_resultado(self) -> None:
        r = await self.t["ha_update_http_config"](changes={"use_x_forwarded_for": True})
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "trusted_proxies"))
        r = await self.t["ha_update_http_config"](
            changes={"use_x_forwarded_for": True, "trusted_proxies": ["192.0.2.0/24"]})
        self.assertIn("confirmation_token", r)
        self.assertEqual(self.escrituras(), [])


class TestServerHost(_Base):
    """D-3 (decidida: fail-closed): sin la dirección por la que el Supervisor
    llega a Core, `supervisor_lockout` sin token y sin escribir."""

    async def test_rechaza_sin_el_supervisor(self) -> None:
        for hosts in ([_IP], ["::"], ["homeassistant.local"], ["172.30.33.5"],
                      ["192.0.2.10", "::1"]):
            with self.subTest(hosts=hosts):
                r = await self.t["ha_update_http_config"](changes={"server_host": hosts})
                self.assertEqual(r["error"], "supervisor_lockout")
                self.assertNotIn("confirmation_token", r)
                self.assertIn("172.30.32.0/23", r["detail"])
                self.assertIn("Hermes", r["detail"])
        self.assertEqual(self.escrituras(), [])

    async def test_acepta_con_el_supervisor(self) -> None:
        for hosts in (["0.0.0.0"], ["172.30.32.1", _IP], ["0.0.0.0", "::"]):
            with self.subTest(hosts=hosts):
                r = await self.t["ha_update_http_config"](changes={"server_host": hosts})
                self.assertIn("confirmation_token", r)
                codigos = [a["code"] for a in r["preview"]["warnings"]]
                self.assertIn("server_host", codigos)
                self.assertIn("access_risk", r["preview"])

    async def test_quitar_server_host_vale(self) -> None:
        self.http["stable"]["server_host"] = ["0.0.0.0", "::"]
        r = await self.t["ha_update_http_config"](changes={"server_host": None})
        self.assertIn("confirmation_token", r)

    async def test_mira_el_resultado_no_solo_lo_pedido(self) -> None:
        # La base ya deja fuera al Supervisor: cualquier cambio se rechaza.
        self.http["stable"]["server_host"] = [_IP]
        r = await self.t["ha_update_http_config"](changes={"server_port": 8443})
        self.assertEqual(r["error"], "supervisor_lockout")


class TestHttpVistaPrevia(_Base):
    async def test_puerto(self) -> None:
        r = await self.t["ha_update_http_config"](changes={"server_port": 8443})
        p = r["preview"]
        self.assertEqual(p["base"], "stable")
        self.assertEqual(p["changes"], {"server_port": {"before": 8123, "after": 8443}})
        self.assertEqual(p["new_config"]["server_port"], 8443)
        for meta in ("created_at", "error", "error_message"):
            self.assertNotIn(meta, p["new_config"])
        self.assertIn("5 minutes", p["restart"])
        self.assertEqual([a["code"] for a in p["warnings"]], ["port"])
        self.assertIn("unreachable", p["access_risk"])
        self.assertFalse(p["pending_replaced"])
        self.assertEqual(self.escrituras(), [])

    async def test_un_aviso_por_codigo(self) -> None:
        casos = {
            "port": {"server_port": 8443},
            "ssl": {"ssl_certificate": _CERT, "ssl_key": _KEY},
            "reverse_proxy": {"use_x_forwarded_for": True, "trusted_proxies": [_IP]},
            "ip_ban": {"login_attempts_threshold": 5},
            "cors": {"cors_allowed_origins": ["https://example.com"]},
            "ssl_profile": {"ssl_profile": "intermediate_v5"},
            "x_frame_options": {"use_x_frame_options": False},
            "server_host": {"server_host": ["0.0.0.0"]},
        }
        riesgo = {"port", "ssl", "reverse_proxy", "ip_ban", "ssl_profile", "server_host"}
        for codigo, cambios in casos.items():
            with self.subTest(codigo=codigo):
                r = await self.t["ha_update_http_config"](changes=cambios)
                p = r["preview"]
                self.assertEqual([a["code"] for a in p["warnings"]], [codigo])
                self.assertEqual("access_risk" in p, codigo in riesgo)

    async def test_pending_replaced(self) -> None:
        self.http["pending"] = {**_ESTABLE, "server_port": 8124}
        r = await self.t["ha_update_http_config"](changes={"cors_allowed_origins": []})
        p = r["preview"]
        self.assertTrue(p["pending_replaced"])
        self.assertIn("pending_replaced", [a["code"] for a in p["warnings"]])

    async def test_funde_sobre_pending(self) -> None:
        self.http["pending"] = {**_ESTABLE, "server_port": 8124, "created_at": "x"}
        self.http["active_config_type"] = "pending"
        r = await self.t["ha_update_http_config"](changes={"ip_ban_enabled": False})
        p = r["preview"]
        self.assertEqual(p["base"], "pending")
        self.assertEqual(p["new_config"]["server_port"], 8124)
        self.assertEqual(p["changes"], {"ip_ban_enabled": {"before": True, "after": False}})

    async def test_funde_sobre_default(self) -> None:
        self.http["stable"] = {**_ESTABLE, "server_port": 9999}
        for tipo, puerto in (("default", 8123), ("default_legacy_port", 8123)):
            with self.subTest(tipo=tipo):
                self.http["active_config_type"] = tipo
                r = await self.t["ha_update_http_config"](changes={"ip_ban_enabled": False})
                self.assertEqual(r["preview"]["base"], tipo)
                self.assertEqual(r["preview"]["new_config"]["server_port"], puerto)

    async def test_null_quita_la_clave(self) -> None:
        self.http["stable"]["ssl_certificate"] = _CERT
        r = await self.t["ha_update_http_config"](changes={"ssl_certificate": None})
        p = r["preview"]
        self.assertNotIn("ssl_certificate", p["new_config"])
        self.assertEqual(p["changes"], {"ssl_certificate": {"before": _CERT, "after": None}})

    async def test_no_changes(self) -> None:
        r = await self.t["ha_update_http_config"](changes={"server_port": 8123})
        self.assertEqual(r, {"result": "no_changes"})
        # Quitar una clave que vale lo mismo que el defecto tampoco cambia nada.
        self.http["stable"]["ip_ban_enabled"] = True
        r = await self.t["ha_update_http_config"](changes={"ip_ban_enabled": None})
        self.assertEqual(r, {"result": "no_changes"})


class TestHttpConfirmacion(_Base):
    async def test_confirmacion_manda_el_documento(self) -> None:
        self.http["stable"]["trusted_proxies"] = ["192.0.2.0/24"]
        r = await self.confirmar("ha_update_http_config", changes={"server_port": 8443})
        self.assertEqual(r["result"], "ok")
        self.assertTrue(r["restart"])
        self.assertIn("ha_promote_http_config", r["next"])
        self.assertIn("configuration.yaml", r["config_check"])
        esperado = {k: v for k, v in _ESTABLE.items()
                    if k not in ("created_at", "error", "error_message")}
        esperado.update(server_port=8443, trusted_proxies=["192.0.2.0/24"])
        self.assertEqual(self.escrituras(),
                         [{"type": "http/config/configure", "config": esperado}])

    async def test_discard_pending(self) -> None:
        r = await self.t["ha_update_http_config"](discard_pending=True)
        self.assertEqual(r, {"result": "no_changes"})
        self.http["pending"] = {**_ESTABLE, "server_port": 8124}
        vista = await self.t["ha_update_http_config"](discard_pending=True)
        self.assertEqual(vista["preview"]["pending"]["server_port"], 8124)
        self.escrituras_esperadas = 1
        r = await self.t["ha_update_http_config"](
            discard_pending=True, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["result"], "ok")
        self.assertEqual(self.escrituras(), [{"type": "http/config/configure", "config": None}])

    async def test_bloqueo_en_la_vista_previa(self) -> None:
        self.permitido = (False, "Pending /config changes have not been validated.")
        r = await self.t["ha_update_http_config"](changes={"server_port": 8443})
        self.assertEqual(r["error"], "restart_blocked")
        self.assertIn("sv_check_core_config", r["detail"])
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.enviados, [])

    async def test_bloqueo_al_confirmar(self) -> None:
        vista = await self.t["ha_update_http_config"](changes={"server_port": 8443})
        self.permitido = (False, "Pending /config changes have not been validated.")
        self.escrituras_esperadas = 1
        r = await self.t["ha_update_http_config"](
            changes={"server_port": 8443}, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "restart_blocked")
        self.assertEqual(self.escrituras(), [])

    async def test_errores_de_ha_traducidos(self) -> None:
        for codigo in ("bind_failed", "not_running", "invalid_format"):
            with self.subTest(codigo=codigo):
                self.http["pending"] = None
                self.fallo_escritura = HAConnectionError(
                    f"fallo password={_CENTINELA}", code=codigo)
                self.escrituras_esperadas = len(self.escrituras())
                r = await self.confirmar("ha_update_http_config",
                                         changes={"server_port": 8443})
                self.assertEqual((r["error"], r["ha_code"]), ("ha_error", codigo))
                self.assertIn("explanation", r)
                self.assertNotIn(_CENTINELA, r["detail"])

    async def test_estado_cambiado_no_escribe(self) -> None:
        vista = await self.t["ha_update_http_config"](changes={"server_port": 8443})
        self.http["stable"]["ip_ban_enabled"] = False
        self.escrituras_esperadas = 1
        r = await self.t["ha_update_http_config"](
            changes={"server_port": 8443}, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], security.ESTADO_CAMBIADO)
        self.assertEqual(self.escrituras(), [])

    async def test_token_de_otros_argumentos(self) -> None:
        vista = await self.t["ha_update_http_config"](changes={"server_port": 8443})
        self.escrituras_esperadas = 1
        r = await self.t["ha_update_http_config"](
            changes={"server_port": 8444}, confirmation_token=vista["confirmation_token"])
        self.assertIn("error", r)
        self.assertEqual(self.escrituras(), [])

    async def test_unsupported_by_ha_version(self) -> None:
        self.fallo_lectura = HAConnectionError("Unknown command.", code="unknown_command")
        for tool, args in (("ha_update_http_config", {"changes": {"server_port": 8443}}),
                           ("ha_promote_http_config", {}),
                           ("ha_update_network_config", {"configured_adapters": []})):
            with self.subTest(tool=tool):
                r = await self.t[tool](**args)
                self.assertEqual(r["error"], "unsupported_by_ha_version")
                self.assertEqual(r["ha_code"], "unknown_command")
                self.assertIn("table_ha_core", r)
        self.assertEqual(self.escrituras(), [])

    async def test_preview_unavailable(self) -> None:
        self.fallo_lectura = HAConnectionError("boom")
        r = await self.t["ha_update_http_config"](changes={"server_port": 8443})
        self.assertEqual(r["error"], "preview_unavailable")

    async def test_log_sin_valores_de_red(self) -> None:
        self.http["stable"]["server_host"] = ["0.0.0.0", _IP]
        with capture_logs() as logs:
            await self.confirmar("ha_update_http_config", changes={
                "ssl_certificate": _CERT, "trusted_proxies": [_IP],
                "use_x_forwarded_for": True, "server_port": 8443,
                "cors_allowed_origins": [f"https://{_CENTINELA}.example"]})
            await self.t["ha_update_http_config"](changes={"server_host": [_IP]})
        texto = repr(logs)
        for valor in (_IP, _CERT, "8443", _CENTINELA):
            self.assertNotIn(valor, texto)
        self.assertIn("ha_update_http_config_ok", texto)


# ── ha_promote_http_config (T040) ────────────────────────────────────────────


class TestPromover(_Base):
    def _con_pendiente(self) -> None:
        self.http["pending"] = {**_ESTABLE, "server_port": 8443}
        self.http["active_config_type"] = "pending"
        self.http["revert_at"] = "2026-11-15T10:05:00+00:00"

    async def test_sin_pendiente(self) -> None:
        r = await self.t["ha_promote_http_config"]()
        self.assertEqual(r["error"], "nothing_to_promote")
        self.assertIn("no pending", r["reason"])

    async def test_pendiente_con_error(self) -> None:
        self._con_pendiente()
        self.http["pending"]["error"] = "apply_failed"
        self.http["active_config_type"] = "stable"
        r = await self.t["ha_promote_http_config"]()
        self.assertEqual(r["error"], "nothing_to_promote")
        self.assertIn("apply_failed", r["reason"])

    async def test_no_funciona_con_la_pendiente(self) -> None:
        self._con_pendiente()
        self.http["active_config_type"] = "stable"
        r = await self.t["ha_promote_http_config"]()
        self.assertEqual(r["error"], "nothing_to_promote")
        self.assertIn("not running with the pending", r["reason"])
        self.assertEqual(self.escrituras(), [])

    async def test_vista_previa_y_confirmacion(self) -> None:
        self._con_pendiente()
        vista = await self.t["ha_promote_http_config"]()
        p = vista["preview"]
        self.assertEqual(p["changes"], {"server_port": {"before": 8123, "after": 8443}})
        self.assertEqual(p["revert_at"], "2026-11-15T10:05:00+00:00")
        self.assertIn("recovery mode", p["note"])
        self.assertEqual(self.escrituras(), [])
        self.escrituras_esperadas = 1
        r = await self.t["ha_promote_http_config"](confirmation_token=vista["confirmation_token"])
        self.assertEqual(r, {"result": "ok"})
        self.assertEqual(self.escrituras(), [{"type": "http/config/promote"}])

    async def test_not_allowed_traducido(self) -> None:
        self._con_pendiente()
        self.fallo_escritura = HAConnectionError("No pending HTTP config to promote",
                                                 code="not_allowed")
        r = await self.confirmar("ha_promote_http_config")
        self.assertEqual((r["error"], r["ha_code"]), ("ha_error", "not_allowed"))

    async def test_estado_cambiado_no_escribe(self) -> None:
        self._con_pendiente()
        vista = await self.t["ha_promote_http_config"]()
        self.http["pending"]["server_port"] = 8444
        self.escrituras_esperadas = 1
        r = await self.t["ha_promote_http_config"](confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], security.ESTADO_CAMBIADO)
        self.assertEqual(self.escrituras(), [])


if __name__ == "__main__":
    unittest.main()
