"""Las cinco tools de la familia `system_status` (spec 029, CAP-043; T006–T008).

FR-001, FR-003…FR-007, FR-018…FR-020; SC-004, SC-006. El cliente de HA es un
doble con `AsyncMock` (`ws_collect_subscription`, `ws_one_shot_subscription`,
`ws_send`): lo que importa es qué se le pide, qué se devuelve y qué queda en
el log. Datos ficticios (`homeassistant.tailXXXX.ts.net`, `192.0.2.10`,
`centinela-029`, un JWT de prueba); nada de una instalación real.

Controles negativos (T018 b–d), con recuentos en el commit del tramo:
- no mover lo pendiente a `pending` (dejar `{"type": "pending"}`) → caen los
  de pendientes;
- no redactar → cae el centinela;
- registrar la URL en el log → cae el de log;
- no recortar por dominios → cae el del tope;
- `_third_party_text` en todas → cae el de los manifiestos de HA.
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from structlog.testing import capture_logs

from hermes.command_table import TABLE_HA_CORE
from hermes.ha import HAConnectionError
from hermes.tools import system_status as mod
from hermes.tools._common import tam_json

_CENTINELA = "centinela-029"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJh"
_URL = "https://homeassistant.tailXXXX.ts.net"
_IP = "192.0.2.10"
_TOPE = 131_072


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _cliente() -> MagicMock:
    c = MagicMock()
    c.wait_ready = AsyncMock(return_value=True)
    c.ws_send = AsyncMock(return_value=[])
    c.ws_one_shot_subscription = AsyncMock(return_value={})
    c.ws_collect_subscription = AsyncMock(return_value=([], True))
    return c


def _tools(cliente: MagicMock, tope: int = _TOPE) -> dict[str, Any]:
    mcp = DummyMCP()
    mod.register(mcp, cliente, response_max_bytes=tope)
    return mcp.tools


def _inicial(data: dict[str, Any]) -> dict[str, Any]:
    return {"type": "initial", "data": data}


_FIN = {"type": "finish"}


def _salud_basica() -> dict[str, Any]:
    return {
        "cloud": {
            "info": {"logged_in": True,
                     "can_reach_cert_server": {"type": "pending"},
                     "can_reach_cloud": {"type": "pending"},
                     "remote_server": f"{_URL}"},
            "manage_url": "/config/cloud",
        },
        "homeassistant": {
            "info": {"version": "2026.11.1", "installation_type": "Home Assistant OS",
                     "last_boot": {"type": "date", "value": "2026-11-14T08:00:00+00:00"},
                     "internal_url": f"http://{_IP}:8123"},
        },
    }


def _textos_de_log(logs: list[dict[str, Any]]) -> str:
    return json.dumps(logs, default=str, ensure_ascii=False)


class TestSalud(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.c = _cliente()
        self.t = _tools(self.c)

    async def _salud(self, eventos, completo=True, **kw) -> dict[str, Any]:
        self.c.ws_collect_subscription.return_value = (eventos, completo)
        return await self.t["ha_get_system_health"](**kw)

    async def test_completa_con_fechas_y_manage_url(self) -> None:
        r = await self._salud([
            _inicial(_salud_basica()),
            {"type": "update", "domain": "cloud", "key": "can_reach_cert_server",
             "success": True, "data": True},
            {"type": "update", "domain": "cloud", "key": "can_reach_cloud",
             "success": True, "data": {"type": "date", "value": "2026-11-14T09:00:00+00:00"}},
            _FIN,
        ])
        self.assertTrue(r["complete"])
        self.assertEqual(r["pending"], [])
        self.assertEqual(r["failed"], [])
        self.assertFalse(r["truncated"])
        self.assertNotIn("omitted_domains", r)
        self.assertEqual(r["domains"]["homeassistant"]["info"]["last_boot"],
                         "2026-11-14T08:00:00+00:00")
        self.assertEqual(r["domains"]["cloud"]["info"]["can_reach_cert_server"], True)
        self.assertEqual(r["domains"]["cloud"]["info"]["can_reach_cloud"],
                         "2026-11-14T09:00:00+00:00")
        self.assertEqual(r["domains"]["cloud"]["manage_url"], "/config/cloud")
        self.assertNotIn("manage_url", r["domains"]["homeassistant"])

    async def test_pide_el_comando_con_el_plazo_pedido(self) -> None:
        await self._salud([_inicial({}), _FIN], timeout_seconds=3)
        args, kw = self.c.ws_collect_subscription.call_args
        self.assertEqual(args[0], {"type": "system_health/info"})
        self.assertEqual(kw["timeout_seconds"], 3.0)
        self.assertTrue(kw["terminado"](_FIN))
        self.assertFalse(kw["terminado"]({"type": "update"}))
        # Por defecto, 10 s.
        await self._salud([_inicial({}), _FIN])
        self.assertEqual(self.c.ws_collect_subscription.call_args.kwargs["timeout_seconds"], 10.0)

    async def test_pendiente_sin_actualizacion_al_vencer(self) -> None:
        r = await self._salud([
            _inicial(_salud_basica()),
            {"type": "update", "domain": "cloud", "key": "can_reach_cloud",
             "success": True, "data": True},
        ], completo=False)
        self.assertFalse(r["complete"])
        self.assertEqual(r["pending"], ["cloud.can_reach_cert_server"])
        self.assertIsNone(r["domains"]["cloud"]["info"]["can_reach_cert_server"])
        self.assertEqual(r["domains"]["cloud"]["info"]["can_reach_cloud"], True)

    async def test_update_fallido_va_a_failed(self) -> None:
        r = await self._salud([
            _inicial(_salud_basica()),
            {"type": "update", "domain": "cloud", "key": "can_reach_cert_server",
             "success": False, "error": {"type": "failed", "error": "unknown"}},
            {"type": "update", "domain": "cloud", "key": "can_reach_cloud",
             "success": True, "data": True},
            _FIN,
        ])
        self.assertTrue(r["complete"])
        self.assertEqual(r["failed"], ["cloud.can_reach_cert_server"])
        self.assertEqual(r["pending"], [])
        self.assertIsNone(r["domains"]["cloud"]["info"]["can_reach_cert_server"])

    async def test_dominio_entero_fallido_en_ha(self) -> None:
        r = await self._salud([
            _inicial({"lenta": {"info": {"error": {"type": "failed", "error": "timeout"}}}}),
            _FIN,
        ])
        self.assertEqual(r["failed"], ["lenta.*"])
        self.assertEqual(r["domains"]["lenta"]["info"],
                         {"error": {"type": "failed", "error": "timeout"}})

    async def test_update_de_algo_desconocido_se_ignora(self) -> None:
        with capture_logs() as logs:
            r = await self._salud([
                _inicial(_salud_basica()),
                {"type": "update", "domain": "inventado", "key": "x", "success": True,
                 "data": 1},
                {"type": "update", "domain": "homeassistant", "key": "version",
                 "success": True, "data": "9999.1.1"},
            ], completo=False)
        self.assertNotIn("inventado", r["domains"])
        self.assertEqual(r["domains"]["homeassistant"]["info"]["version"], "2026.11.1")
        ok = [e for e in logs if e["event"] == "ha_get_system_health_ok"]
        self.assertEqual(ok[0]["ignored_updates"], 2)

    async def test_un_dominio(self) -> None:
        r = await self._salud([_inicial(_salud_basica())], completo=False,
                              domain="homeassistant")
        self.assertEqual(list(r["domains"]), ["homeassistant"])
        # Lo pendiente de otro dominio no cuenta.
        self.assertEqual(r["pending"], [])

    async def test_dominio_que_no_esta(self) -> None:
        r = await self._salud([_inicial(_salud_basica()), _FIN], domain="zigbee")
        self.assertEqual(r["error"], "domain_not_found")
        self.assertEqual(r["available_domains"], ["cloud", "homeassistant"])

    async def test_argumentos_invalidos_sin_llamar_a_ha(self) -> None:
        casos = (
            {"timeout_seconds": 0.5}, {"timeout_seconds": 31}, {"timeout_seconds": True},
            {"timeout_seconds": "5"}, {"domain": "Cloud"}, {"domain": "a/b"},
            {"domain": ""}, {"domain": "x" * 65},
        )
        for kw in casos:
            with self.subTest(kw=kw):
                r = await self.t["ha_get_system_health"](**kw)
                self.assertEqual(r["error"], "invalid_argument")
        self.c.ws_collect_subscription.assert_not_awaited()

    async def test_secretos_tapados(self) -> None:
        r = await self._salud([
            _inicial({"demo": {"info": {
                "estado": f"conectado token={_CENTINELA}",
                "cabecera": f"Bearer {_JWT}",
                "api_token": "otro-valor-secreto",
            }}}),
            _FIN,
        ])
        texto = json.dumps(r)
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn(_JWT, texto)
        self.assertNotIn("otro-valor-secreto", texto)
        self.assertIn("conectado", texto)

    async def test_sin_system_health_cargado(self) -> None:
        self.c.ws_collect_subscription.side_effect = HAConnectionError(
            "HA WS command failed: Unknown command.", code="unknown_command")
        r = await self.t["ha_get_system_health"]()
        self.assertEqual(r["error"], "system_health_not_loaded")
        self.assertEqual(r["ha_code"], "unknown_command")

    async def test_otro_error_de_ha_redactado(self) -> None:
        self.c.ws_collect_subscription.side_effect = HAConnectionError(
            f"HA WS command failed: boom token={_CENTINELA}", code="home_assistant_error")
        r = await self.t["ha_get_system_health"]()
        self.assertEqual((r["error"], r["ha_code"]), ("ha_command_failed", "home_assistant_error"))
        self.assertNotIn(_CENTINELA, json.dumps(r))

    async def test_core_caido(self) -> None:
        self.c.ws_collect_subscription.side_effect = HAConnectionError(
            "WebSocket no disponible para envío de comandos.")
        r = await self.t["ha_get_system_health"]()
        self.assertEqual(r, {"error": "WebSocket no disponible para envío de comandos."})

    async def test_recorte_por_dominios(self) -> None:
        grande = "x" * 3000
        data = {f"d{i:02d}": {"info": {"valor": grande}} for i in range(10)}
        self.c.ws_collect_subscription.return_value = ([_inicial(data), _FIN], True)
        t = _tools(self.c, tope=12_000)
        r = await t["ha_get_system_health"]()
        self.assertTrue(r["truncated"])
        self.assertLessEqual(tam_json(r), 12_000)
        self.assertEqual(list(r["domains"]) + r["omitted_domains"], sorted(data))
        self.assertGreater(len(r["domains"]), 0)
        # Los dominios que salen, enteros.
        for d in r["domains"].values():
            self.assertEqual(d["info"]["valor"], grande)

    async def test_un_dominio_que_no_cabe(self) -> None:
        data = {"enorme": {"info": {"valor": "x" * 20_000}}}
        self.c.ws_collect_subscription.return_value = ([_inicial(data), _FIN], True)
        t = _tools(self.c, tope=10_240)
        r = await t["ha_get_system_health"](domain="enorme")
        self.assertEqual(r["error"], "response_too_large")

    async def test_respuesta_tipica_cabe_en_el_tope_minimo(self) -> None:
        """Aviso 2 del supervisor: medido con una salud realista de HA OS
        (claves de `system_health.py` de homeassistant, hassio, cloud,
        recorder, lovelace y cinco integraciones más): unos 2,3 KB, menos de
        la mitad del tope MÍNIMO de `response_max_bytes` (10 KiB). El
        filtro `domain` existe igualmente para una instalación grande."""
        r = await self._salud([_inicial(_SALUD_REALISTA), _FIN])
        self.assertFalse(r["truncated"])
        self.assertLess(tam_json(r), 10_240 // 2, tam_json(r))

    async def test_log_sin_valores_urls_ni_ips(self) -> None:
        with capture_logs() as logs:
            await self._salud([_inicial(_salud_basica()), _FIN])
        texto = _textos_de_log(logs)
        for prohibido in ("tailXXXX", _IP, "2026.11.1", "Home Assistant OS", "/config/cloud"):
            self.assertNotIn(prohibido, texto)
        ok = [e for e in logs if e["event"] == "ha_get_system_health_ok"]
        self.assertEqual(len(ok), 1)
        self.assertEqual(ok[0]["domains"], 2)
        self.assertEqual(ok[0]["pending"], 2)


# Salud realista de un HA OS (valores ficticios, claves de las plataformas
# `system_health.py` de Core 2026.11.1).
_SALUD_REALISTA: dict[str, Any] = {
    "homeassistant": {"info": {
        "installation_type": "Home Assistant OS", "version": "2026.11.1", "dev": False,
        "hassio": True, "virtualenv": False, "python_version": "3.13.9",
        "docker": True, "arch": "aarch64", "timezone": "Etc/UTC",
        "os_name": "Linux", "os_version": "6.12.47-haos-raspi", "user": "root",
        "config_dir": "/config", "run_as_root": True}},
    "hassio": {"info": {
        "host_os": "Home Assistant OS 16.3", "update_channel": "stable",
        "supervisor_version": "supervisor-2026.11.0", "agent_version": "1.8.0",
        "docker_version": "28.3.3", "disk_total": "116.7 GB", "disk_used": "31.2 GB",
        "nameservers": "192.0.2.1", "healthy": True, "supported": True,
        "host_connectivity": True, "supervisor_connectivity": True,
        "ntp_synchronized": True, "virtualization": "", "board": "rpi5-64",
        "supervisor_api": "ok", "version_api": "ok",
        "installed_addons": ", ".join(f"App {i} (1.{i}.0)" for i in range(15))},
        "manage_url": "/hassio/system"},
    "cloud": {"info": {
        "logged_in": True, "subscription_expiration": "2027-01-01T00:00:00+00:00",
        "relayer_connected": True, "relayer_region": "eu-central-1",
        "remote_enabled": True, "remote_connected": True, "alexa_enabled": False,
        "google_enabled": True, "cloud_ice_servers_enabled": True,
        "remote_server": "eu-remote-1.ui.nabu.casa", "certificate_status": "ready",
        "instance_id": "0123456789abcdef0123456789abcdef",
        "can_reach_cert_server": "ok", "can_reach_cloud_auth": "ok",
        "can_reach_cloud": "ok"}, "manage_url": "/config/cloud"},
    "recorder": {"info": {
        "oldest_recorder_run": "2026-11-04T08:00:00+00:00",
        "current_recorder_run": "2026-11-14T08:00:00+00:00",
        "estimated_db_size": "812.43 MiB", "database_engine": "sqlite",
        "database_version": "3.48.0"}},
    "lovelace": {"info": {"dashboards": 4, "resources": 6, "views": 12, "mode": "storage"}},
    "auth": {"info": {"auth_providers": "homeassistant"}},
    "mqtt": {"info": {"broker": "core-mosquitto", "port": 1883}},
    "zha": {"info": {"radio_type": "ezsp", "devices": 34}},
    "met": {"info": {"can_reach_server": "ok"}},
    "search": {"info": {"index_size": 1200}},
}


class TestEstado(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.c = _cliente()
        self.t = _tools(self.c)

    async def test_cinco_campos(self) -> None:
        estado = {
            "home_assistant_restart_required": True,
            "home_assistant_restart_sources": ["integration_installed"],
            "home_assistant_restart_dismissed": False,
            "host_reboot_required": False,
            "host_reboot_dismissed": False,
        }
        self.c.ws_one_shot_subscription.return_value = estado
        r = await self.t["ha_get_system_state"]()
        self.assertEqual(r, estado)
        args, kw = self.c.ws_one_shot_subscription.call_args
        self.assertEqual(args[0], {"type": "subscribe_system_state"})
        self.assertEqual(kw["event_timeout_seconds"], 10.0)

    async def test_ha_sin_el_comando(self) -> None:
        self.c.ws_one_shot_subscription.side_effect = HAConnectionError(
            "HA WS command failed: Unknown command.", code="unknown_command")
        r = await self.t["ha_get_system_state"]()
        self.assertEqual(r["error"], "unsupported_by_ha_version")
        self.assertEqual(r["ha_code"], "unknown_command")
        self.assertEqual(r["table_ha_core"], TABLE_HA_CORE)

    async def test_otro_error_redactado(self) -> None:
        self.c.ws_one_shot_subscription.side_effect = HAConnectionError(
            f"HA WS command failed: no {_JWT}", code="unauthorized")
        r = await self.t["ha_get_system_state"]()
        self.assertEqual(r["error"], "ha_command_failed")
        self.assertNotIn(_JWT, json.dumps(r))

    async def test_core_caido(self) -> None:
        self.c.ws_one_shot_subscription.side_effect = HAConnectionError("caída")
        self.assertEqual(await self.t["ha_get_system_state"](), {"error": "caída"})


class TestTiemposDeArranque(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.c = _cliente()
        self.c.ws_send.return_value = [
            {"domain": "http", "seconds": 0.123456},
            {"domain": "zha", "seconds": 12.5},
            {"domain": "recorder", "seconds": 2.0004},
            {"domain": "met", "seconds": 0.5},
        ]
        self.t = _tools(self.c)

    async def test_orden_y_totales(self) -> None:
        r = await self.t["ha_list_integration_setup_times"]()
        self.c.ws_send.assert_awaited_once_with({"type": "integration/setup_info"})
        self.assertEqual([i["domain"] for i in r["items"]], ["zha", "recorder", "met", "http"])
        self.assertEqual(r["items"][3]["seconds"], 0.123)
        self.assertEqual((r["count"], r["total"], r["truncated"]), (4, 4, False))
        self.assertEqual(r["total_seconds"], round(12.5 + 2.0004 + 0.5 + 0.123456, 3))

    async def test_limit_y_min_seconds(self) -> None:
        r = await self.t["ha_list_integration_setup_times"](limit=2)
        self.assertEqual([i["domain"] for i in r["items"]], ["zha", "recorder"])
        self.assertTrue(r["truncated"])
        self.assertEqual(r["total"], 4)
        r = await self.t["ha_list_integration_setup_times"](min_seconds=1)
        self.assertEqual([i["domain"] for i in r["items"]], ["zha", "recorder"])
        # `min_seconds` filtra, no recorta.
        self.assertFalse(r["truncated"])
        self.assertEqual(r["total"], 4)

    async def test_argumentos_invalidos(self) -> None:
        for kw in ({"limit": 0}, {"limit": 501}, {"limit": True}, {"limit": 1.5},
                   {"min_seconds": -1}, {"min_seconds": "1"}):
            with self.subTest(kw=kw):
                r = await self.t["ha_list_integration_setup_times"](**kw)
                self.assertEqual(r["error"], "invalid_argument")
        self.c.ws_send.assert_not_awaited()

    async def test_tope_de_bytes(self) -> None:
        self.c.ws_send.return_value = [{"domain": f"dominio_{i:03d}", "seconds": i}
                                       for i in range(500)]
        t = _tools(self.c, tope=10_240)
        r = await t["ha_list_integration_setup_times"](limit=500)
        self.assertTrue(r["truncated"])
        self.assertLessEqual(tam_json(r), 10_240)
        self.assertEqual(r["count"], len(r["items"]))
        self.assertEqual(r["total"], 500)

    async def test_ha_sin_el_comando(self) -> None:
        self.c.ws_send.side_effect = HAConnectionError("x", code="unknown_command")
        r = await self.t["ha_list_integration_setup_times"]()
        self.assertEqual(r["error"], "unsupported_by_ha_version")

    async def test_log_sin_dominios(self) -> None:
        with capture_logs() as logs:
            await self.t["ha_list_integration_setup_times"]()
        texto = _textos_de_log(logs)
        self.assertNotIn("zha", texto)
        self.assertNotIn("recorder", texto)


def _manifiesto(dominio: str, de_ha: bool = True, **extra: Any) -> dict[str, Any]:
    m = {"domain": dominio, "name": dominio.title(), "integration_type": "helper",
         "iot_class": "local_push", "quality_scale": "internal", "is_built_in": de_ha,
         "overwrites_built_in": False, "config_flow": True,
         "documentation": f"https://www.home-assistant.io/integrations/{dominio}",
         "requirements": [], "dependencies": [], "codeowners": ["@ficticio"]}
    if not de_ha:
        m["version"] = "1.2.3"
        m["issue_tracker"] = "https://example.invalid/issues"
    m.update(extra)
    return m


class TestManifiestos(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.c = _cliente()
        self.c.ws_send.return_value = [
            _manifiesto("zha"), _manifiesto("input_boolean"),
            _manifiesto("mi_custom", de_ha=False),
        ]
        self.t = _tools(self.c)

    async def test_resumen_de_diez_campos_ordenado(self) -> None:
        r = await self.t["ha_list_integration_manifests"]()
        self.c.ws_send.assert_awaited_once_with({"type": "manifest/list"})
        self.assertEqual([i["domain"] for i in r["items"]], ["input_boolean", "mi_custom", "zha"])
        zha = r["items"][2]
        self.assertEqual(set(zha), set(mod._CAMPOS_RESUMEN))
        self.assertIsNone(zha["version"])
        self.assertEqual((r["count"], r["truncated"], r["missing"]), (3, False, []))

    async def test_third_party_solo_en_las_que_no_son_de_ha(self) -> None:
        r = await self.t["ha_list_integration_manifests"]()
        por = {i["domain"]: i for i in r["items"]}
        self.assertIn("_third_party_text", por["mi_custom"])
        self.assertEqual(por["mi_custom"]["_third_party_text"]["fields"], ["name", "documentation"])
        self.assertNotIn("_third_party_text", por["zha"])
        self.assertNotIn("_third_party_text", por["input_boolean"])

    async def test_custom_only(self) -> None:
        r = await self.t["ha_list_integration_manifests"](custom_only=True)
        self.assertEqual([i["domain"] for i in r["items"]], ["mi_custom"])

    async def test_pedidas_y_missing(self) -> None:
        self.c.ws_send.return_value = [_manifiesto("input_boolean")]
        r = await self.t["ha_list_integration_manifests"](
            integrations=["input_boolean", "no_existe", "input_boolean"])
        self.c.ws_send.assert_awaited_once_with(
            {"type": "manifest/list", "integrations": ["input_boolean", "no_existe"]})
        self.assertEqual(r["missing"], ["no_existe"])
        self.assertEqual(r["count"], 1)

    async def test_argumentos_invalidos_sin_llamar_a_ha(self) -> None:
        for valor in (["Mayus"], ["a/b"], ["con espacio"], [""], [1],
                      [f"d{i}" for i in range(101)], "zha"):
            with self.subTest(valor=valor):
                r = await self.t["ha_list_integration_manifests"](integrations=valor)
                self.assertEqual(r["error"], "invalid_argument")
        self.c.ws_send.assert_not_awaited()

    async def test_recorte_al_tope(self) -> None:
        self.c.ws_send.return_value = [_manifiesto(f"d{i:03d}") for i in range(300)]
        t = _tools(self.c, tope=10_240)
        r = await t["ha_list_integration_manifests"]()
        self.assertTrue(r["truncated"])
        self.assertLessEqual(tam_json(r), 10_240)
        self.assertEqual(r["count"], len(r["items"]))

    async def test_ha_sin_el_comando(self) -> None:
        self.c.ws_send.side_effect = HAConnectionError("x", code="unknown_command")
        r = await self.t["ha_list_integration_manifests"]()
        self.assertEqual(r["error"], "unsupported_by_ha_version")

    async def test_log_sin_nombres(self) -> None:
        with capture_logs() as logs:
            await self.t["ha_list_integration_manifests"](integrations=["zha", "no_existe"])
        texto = _textos_de_log(logs)
        for prohibido in ("zha", "no_existe", "mi_custom", "home-assistant.io"):
            self.assertNotIn(prohibido, texto)


class TestManifiesto(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.c = _cliente()
        self.t = _tools(self.c)

    async def test_completo_de_ha(self) -> None:
        m = _manifiesto("input_boolean")
        self.c.ws_send.return_value = m
        r = await self.t["ha_get_integration_manifest"]("input_boolean")
        self.c.ws_send.assert_awaited_once_with(
            {"type": "manifest/get", "integration": "input_boolean"})
        self.assertEqual(r, m)

    async def test_personalizado_con_third_party_y_secreto_tapado(self) -> None:
        self.c.ws_send.return_value = _manifiesto(
            "mi_custom", de_ha=False, api_key=_CENTINELA,
            documentation=f"https://example.invalid/?token={_CENTINELA}")
        r = await self.t["ha_get_integration_manifest"]("mi_custom")
        self.assertEqual(r["_third_party_text"]["fields"],
                         ["name", "documentation", "issue_tracker", "codeowners"])
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertEqual(r["version"], "1.2.3")

    async def test_no_existe(self) -> None:
        self.c.ws_send.side_effect = HAConnectionError(
            "HA WS command failed: Integration not found", code="not_found")
        r = await self.t["ha_get_integration_manifest"]("no_existe")
        self.assertEqual(r["error"], "integration_not_found")

    async def test_nombre_invalido(self) -> None:
        for valor in ("Mayus", "a/b", "", "x" * 65, None, 3):
            with self.subTest(valor=valor):
                r = await self.t["ha_get_integration_manifest"](valor)
                self.assertEqual(r["error"], "invalid_argument")
        self.c.ws_send.assert_not_awaited()

    async def test_no_cabe(self) -> None:
        self.c.ws_send.return_value = _manifiesto("grande", requirements=["x" * 20_000])
        t = _tools(self.c, tope=10_240)
        r = await t["ha_get_integration_manifest"]("grande")
        self.assertEqual(r["error"], "response_too_large")

    async def test_ha_sin_el_comando_y_log(self) -> None:
        self.c.ws_send.side_effect = HAConnectionError("x", code="unknown_command")
        with capture_logs() as logs:
            r = await self.t["ha_get_integration_manifest"]("zha")
        self.assertEqual(r["error"], "unsupported_by_ha_version")
        self.assertNotIn("zha", _textos_de_log(logs))
