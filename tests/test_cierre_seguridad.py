"""Cierre de seguridad de la 1.2.0, puntos 3 a 8 (el 1 está en
`test_cierre_seguridad_eco.py`; el 2 no necesitó código: ver el CHANGELOG).

Datos con la forma real, sacada de las fuentes de HA 2026.11.1 y del
Supervisor 2026.11.0:

- claves S0/S2 de Z-Wave: los nombres de `zwave_js/const.py`
  (`CONF_ADDON_S0_LEGACY_KEY`…), 32 dígitos hexadecimales;
- PSK del wifi: el objeto `wifi` de `api/network.py` (`mode`, `auth`,
  `ssid`, `psk`) en el `repr()` de `humanize_error`;
- formulario de opciones: el `data_schema` que serializa
  `cv.custom_serializer`, con una sección (`type: expandable`, su propia
  lista en `schema`) y el valor actual en `description.suggested_value`
  (`add_suggested_values_to_schema`), como el flujo de opciones de `scrape`;
- clave de backups: `backup/config/info` → `config.create_backup.password`;
- interruptor «pre-release»: `RepositoryPreReleaseSwitchEntity`
  (`marketplace/switch.py`), plataforma `marketplace`.

Controles negativos (comprobados al escribirlos, revirtiendo el código un
momento; recuentos de pytest con subtests):
(3a) quitar el paso 1c de `redact_secrets` → caen
     `test_zwave_en_json_dentro_de_un_texto`, `test_psk_en_el_repr_del_supervisor`,
     `test_network_key_de_zigbee2mqtt` y los tres subtests de
     `test_zwave_sin_comillas` (6 failed);
(3b) `_redact_dict` sin `tapar_entero` → cae `test_log_tapa_anidado`;
(3c) el procesador del log sin `tapar_entero` en el primer nivel → cae
     `test_log_tapa_la_estructura_entera`;
(4)  devolver `raw` sin `_tapar_resultado` en las dos tools de opciones →
     caen `test_start_tapa_el_formulario` y `test_continue_tapa_el_paso`; lo
     mismo sin la recursión en secciones de `_tapar_esquema` (la contraseña
     va en la sección `auth`);
(5)  `es_hermes` sin el slug propio → caen
     `test_otra_app_hermes_ya_no_se_bloquea`, `test_log_del_journal` y el
     subtest con slug de `test_generica` (3 failed);
(6)  `backup_previo` sin la clave → cae `test_auto_con_clave_cifra`; sin el
     rechazo de `required` → cae `test_required_sin_clave_no_desinstala`;
(7)  sin el aviso en la vista previa → caen los tres subtests de
     `test_habilitar_avisa` y `test_sin_registro_avisa_igual` (4 failed);
(8)  sin la guarda de `HermesMCPServer.call_tool` → cae
     `test_escritura_con_url_tapada`.
"""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import MagicMock

from aiohttp import ClientSession

from hermes import logging_setup
from hermes.security import REDACTED_MARKER, redact_secrets
from tests._ha_fixture import make_ready_client

_S0 = "0123456789ABCDEF0123456789ABCDEF"
_S2 = "FEDCBA9876543210FEDCBA9876543210"
_PSK = "wifi-centinela-7Qz"
_CLAVE_HA = "Clave-backups-centinela-3Rt"


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, *a: Any, **k: Any):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


# ── 3. Redacción en texto ────────────────────────────────────────────────────


class TestRedaccionEnTexto(unittest.TestCase):
    def test_zwave_en_json_dentro_de_un_texto(self) -> None:
        opciones = {"device": "/dev/ttyUSB0", "s0_legacy_key": _S0,
                    "s2_access_control_key": _S2, "s2_authenticated_key": _S2,
                    "s2_unauthenticated_key": _S2, "lr_s2_access_control_key": _S2,
                    "lr_s2_authenticated_key": _S2}
        texto = f"App core_zwave_js options: {json.dumps(opciones)}"
        limpio = redact_secrets(texto)
        self.assertNotIn(_S0, limpio)
        self.assertNotIn(_S2, limpio)
        self.assertIn("/dev/ttyUSB0", limpio)
        # El JSON sigue siendo JSON.
        self.assertEqual(json.loads(limpio.split(": ", 1)[1])["s0_legacy_key"],
                         REDACTED_MARKER)

    def test_zwave_sin_comillas(self) -> None:
        for texto in (f"s0_legacy_key: {_S0}", f"s2_authenticated_key={_S2}",
                      f"network_key: {_S0}"):
            with self.subTest(texto=texto):
                self.assertNotIn(_S0 if "s0" in texto or "network" in texto else _S2,
                                 redact_secrets(texto))

    def test_psk_en_el_repr_del_supervisor(self) -> None:
        wifi = {"mode": "infrastructure", "auth": "wpa-psk", "ssid": "casa", "psk": _PSK}
        limpio = redact_secrets(f"... @ data['wifi']. Got {wifi!r}")
        self.assertNotIn(_PSK, limpio)
        self.assertIn("'ssid': 'casa'", limpio)

    def test_network_key_de_zigbee2mqtt(self) -> None:
        texto = "advanced:\n  network_key: [1, 3, 5, 7, 9, 11, 13, 15]\n  pan_id: 6754"
        limpio = redact_secrets(texto)
        self.assertNotIn("1, 3, 5", limpio)
        self.assertIn("pan_id: 6754", limpio)
        limpio = redact_secrets('{"network_key": {"key": [1, 3, 5], "tx_counter": 0}}')
        self.assertNotIn("1, 3, 5", limpio)
        json.loads(limpio)

    def test_psk_set_no_se_toca(self) -> None:
        for texto in ("psk_set: true", '"network_key": null'):
            with self.subTest(texto=texto):
                self.assertEqual(redact_secrets(texto), texto)

    def test_log_tapa_la_estructura_entera(self) -> None:
        evento = {"event": "x", "network_key": {"key": [1, 3, 5], "tx_counter": 0},
                  "psk": _PSK, "ok": True}
        r = logging_setup._redact_processor(None, "info", evento)
        self.assertEqual(r["network_key"], REDACTED_MARKER)
        self.assertEqual(r["psk"], REDACTED_MARKER)
        self.assertIs(r["ok"], True)

    def test_log_tapa_anidado(self) -> None:
        evento = {"event": "x", "options": {"mqtt_password": "m-centinela",
                                            "zigbee": {"network_key": [1, 3, 5]},
                                            "s0_legacy_key": _S0, "secure": False}}
        r = logging_setup._redact_processor(None, "info", evento)
        texto = json.dumps(r)
        for centinela in ("m-centinela", "1, 3, 5", _S0):
            self.assertNotIn(centinela, texto)
        self.assertIs(r["options"]["secure"], False)


# ── 4. Flujos de opciones ────────────────────────────────────────────────────


def _formulario_scrape(clave: str) -> dict[str, Any]:
    """Lo que devuelve `POST /config/config_entries/options/flow` para un
    flujo de opciones como el de `scrape`: valores actuales sugeridos, la
    contraseña dentro de la sección `auth`."""
    return {
        "type": "form", "flow_id": "f0123", "handler": "e1", "step_id": "init",
        "data_schema": [
            {"name": "resource", "required": True, "selector": {"text": {}},
             "description": {"suggested_value": "https://example.com/estado"}},
            {"name": "auth", "required": True, "type": "expandable", "expanded": False,
             "schema": [
                 {"name": "username", "optional": True,
                  "selector": {"text": {"type": "text", "autocomplete": "username"}},
                  "description": {"suggested_value": "lector"}},
                 {"name": "clave_de_acceso", "optional": True,
                  "selector": {"text": {"type": "password",
                                        "autocomplete": "current-password"}},
                  "description": {"suggested_value": clave}},
             ]},
            {"name": "api_token", "required": False, "default": clave, "type": "string"},
        ],
        "errors": {}, "description_placeholders": None, "last_step": None,
        "preview": None,
    }


class TestFlujosDeOpciones(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        import hermes.tools.config_entry_flows as flows

        self.session = ClientSession()
        self.client = make_ready_client(self.session, {})
        self.enviado: list[Any] = []

        async def rest(method: str, path: str, json_body: Any = None, params: Any = None) -> Any:
            self.enviado.append((method, path, json_body))
            return _formulario_scrape(_PSK)

        self.client._request_json = rest  # type: ignore[method-assign]
        self.mcp = DummyMCP()
        flows.register(self.mcp, self.client)

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def test_start_tapa_el_formulario(self) -> None:
        r = json.loads(await self.mcp.tools["ha_start_options_flow"]("e1"))
        self.assertNotIn(_PSK, json.dumps(r))
        esquema = {c["name"]: c for c in r["data_schema"]}
        self.assertEqual(esquema["api_token"]["default"], REDACTED_MARKER)
        seccion = {c["name"]: c for c in esquema["auth"]["schema"]}
        self.assertEqual(seccion["clave_de_acceso"]["description"]["suggested_value"],
                         REDACTED_MARKER)
        # Lo que no es secreto se sigue viendo.
        self.assertEqual(seccion["username"]["description"]["suggested_value"], "lector")

    async def test_continue_tapa_el_paso(self) -> None:
        r = json.loads(await self.mcp.tools["ha_continue_options_flow"](
            "f0123", {"resource": "https://example.com/otro"}))
        self.assertNotIn(_PSK, json.dumps(r))

    async def test_continue_rechaza_el_marcador(self) -> None:
        r = json.loads(await self.mcp.tools["ha_continue_options_flow"](
            "f0123", {"auth": {"clave_de_acceso": REDACTED_MARKER}}))
        self.assertEqual(r["error"], "invalid_argument")
        self.assertEqual(self.enviado, [])


# ── 5. D-13: Hermes por su slug exacto ───────────────────────────────────────


class _Supervisor:
    """`sv_request` mínimo: `/addons/self/info` con el slug de Hermes."""

    def __init__(self, propio: str | None) -> None:
        self.propio = propio
        self.llamadas: list[tuple[str, str]] = []

    async def __call__(self, method: str, path: str, json_body: Any = None,
                       params: Any = None, timeout_seconds: Any = None) -> Any:
        self.llamadas.append((method, path))
        if path == "/addons/self/info":
            if self.propio is None:
                from hermes.ha import HAConnectionError
                raise HAConnectionError("failed 503", status=503)
            return {"slug": self.propio, "name": "Hermes"}
        if path.endswith("/info"):
            return {"version": "1.0.0", "version_latest": "1.1.0",
                    "update_available": True, "state": "started"}
        return {}


class TestSlugExacto(unittest.IsolatedAsyncioTestCase):
    def _addons(self, propio: str | None) -> tuple[dict[str, Any], _Supervisor]:
        from hermes.tools.addons import register

        from unittest.mock import AsyncMock

        from hermes.ha import HAConnectionError

        sv = _Supervisor(propio)
        ha = MagicMock()
        ha.sv_request = sv
        # El changelog de la vista previa de `sv_update_addon`: sin él.
        ha.sv_request_text = AsyncMock(side_effect=HAConnectionError("failed 404", status=404))
        mcp = DummyMCP()
        register(mcp, ha)
        return mcp.tools, sv

    async def test_otra_app_hermes_ya_no_se_bloquea(self) -> None:
        tools, _ = self._addons("a1b2c3d4_hermes")
        r = await tools["sv_update_addon"]("e5f6a7b8_hermes")
        self.assertIn("confirmation_token", r, r)
        r = await tools["sv_restart_addon"]("e5f6a7b8_hermes")
        self.assertNotIn("WARNING", json.dumps(r))

    async def test_hermes_sigue_bloqueado(self) -> None:
        tools, _ = self._addons("a1b2c3d4_hermes")
        for slug in ("a1b2c3d4_hermes", "self"):
            with self.subTest(slug=slug):
                r = await tools["sv_update_addon"](slug)
                self.assertEqual(r["error"], "self_update_not_supported")

    async def test_sin_slug_propio_bloquea_de_mas(self) -> None:
        tools, _ = self._addons(None)
        r = await tools["sv_update_addon"]("e5f6a7b8_hermes")
        self.assertEqual(r["error"], "self_update_not_supported")

    async def test_otra_app_no_pregunta(self) -> None:
        tools, sv = self._addons("a1b2c3d4_hermes")
        await tools["sv_update_addon"]("core_mosquitto")
        self.assertNotIn(("GET", "/addons/self/info"), sv.llamadas)

    async def test_generica(self) -> None:
        from unittest.mock import AsyncMock

        from hermes.command_policy import Entrada
        from hermes.tools.generic_commands import register

        tabla = {("GET", "/addons/{app}/info"): Entrada(
            category="read", reason="lee una app", family="generic_commands")}
        for propio, bloqueado in (("a1b2c3d4_hermes", False), (None, True)):
            with self.subTest(propio=propio):
                ha = MagicMock()
                ha.wait_ready = AsyncMock(return_value=True)
                ha.sv_request = _Supervisor(propio)
                mcp = DummyMCP()
                register(mcp, ha, response_max_bytes=65536, tabla_core={},
                         tabla_supervisor=tabla)
                r = await mcp.tools["sv_read_api"]("/addons/e5f6a7b8_hermes/info")
                self.assertEqual(r.get("rule") == "self_target", bloqueado, r)

    async def test_log_del_journal(self) -> None:
        from hermes.tools.addons import es_hermes
        from hermes.tools.system_logs import _identifier_de_hermes

        async def propio() -> str:
            return "a1b2c3d4_hermes"

        self.assertTrue(await _identifier_de_hermes("addon_a1b2c3d4_hermes", propio))
        self.assertFalse(await _identifier_de_hermes("addon_e5f6a7b8_hermes", propio))
        self.assertTrue(await es_hermes("self", propio))


# ── 6. Backup previo de ha_marketplace_uninstall ─────────────────────────────


class TestBackupDeDesinstalarCifrado(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from tests.fixtures.marketplace_escritura import MarketplaceSimulado, SupervisorSimulado

        self.session = ClientSession()
        self.client = make_ready_client(self.session, {})
        self.ha = MarketplaceSimulado()
        self.sv = SupervisorSimulado(self.ha)
        self.clave: str | None = _CLAVE_HA

        async def ws(payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
            if payload["type"] == "backup/config/info":
                # `handle_config_info` de `components/backup/websocket.py`.
                return {"config": {"create_backup": {
                    "agent_ids": ["backup.local"], "include_addons": None,
                    "include_all_addons": False, "include_database": True,
                    "include_folders": None, "name": None, "password": self.clave}}}
            return await self.ha(payload, timeout_seconds)

        self.client.ws_send = ws  # type: ignore[method-assign]
        self.client.sv_request = self.sv  # type: ignore[method-assign]

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def _tools(self, modo: str) -> dict[str, Any]:
        from hermes.tools import marketplace_manage as mm

        mcp = DummyMCP()
        mm.register(mcp, self.client, safety_backup_encryption=modo)
        return mcp.tools

    async def _desinstalar(self, modo: str) -> tuple[dict[str, Any], dict[str, Any]]:
        from tests.fixtures.marketplace_escritura import ID_INSTALADO

        t = self._tools(modo)["ha_marketplace_uninstall"]
        vista = await t(repository_id=ID_INSTALADO)
        if "confirmation_token" not in vista:
            return vista, {}
        hecho = await t(repository_id=ID_INSTALADO,
                        confirmation_token=vista["confirmation_token"])
        return vista, hecho

    async def test_auto_con_clave_cifra(self) -> None:
        vista, hecho = await self._desinstalar("auto")
        copia = vista["preview"]["backup"]
        self.assertIs(copia["encrypted"], True)
        self.assertIn("emergency kit", copia["restore_note"])
        self.assertEqual(self.sv.llamadas[0]["json_body"]["password"], _CLAVE_HA)
        self.assertIs(hecho["backup"]["encrypted"], True)
        self.assertNotIn(_CLAVE_HA, json.dumps(vista) + json.dumps(hecho))

    async def test_auto_sin_clave_avisa(self) -> None:
        self.clave = None
        vista, hecho = await self._desinstalar("auto")
        copia = vista["preview"]["backup"]
        self.assertIs(copia["encrypted"], False)
        self.assertIn("NOT be encrypted", copia["warning"])
        self.assertNotIn("password", self.sv.llamadas[0]["json_body"])
        self.assertEqual(hecho["result"], "ok")

    async def test_required_sin_clave_no_desinstala(self) -> None:
        self.clave = None
        vista, hecho = await self._desinstalar("required")
        self.assertEqual(vista["error"], "encryption_key_unavailable")
        self.assertNotIn("confirmation_token", vista)
        self.assertEqual(hecho, {})
        self.assertEqual(self.sv.llamadas, [])
        self.assertEqual(self.ha.escrituras(), [])

    async def test_off_como_en_la_026(self) -> None:
        vista, _ = await self._desinstalar("off")
        self.assertIs(vista["preview"]["backup"]["encrypted"], False)
        self.assertNotIn("password", self.sv.llamadas[0]["json_body"])


# ── 7. El interruptor «pre-release» por el registro de entidades ─────────────


class TestInterruptorBetaEnElRegistro(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()
        self.client = make_ready_client(self.session, {})
        self.entrada: Any = None

    async def asyncTearDown(self) -> None:
        await self.session.close()

    async def _vista(self, entity_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        from hermes.tools import registry_entity

        async def ws(payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
            if self.entrada is None:
                from hermes.ha import HAConnectionError
                raise HAConnectionError("offline")
            return self.entrada

        self.client.ws_send = ws  # type: ignore[method-assign]
        mcp = DummyMCP()
        registry_entity.register(mcp, self.client)
        return json.loads(await mcp.tools["ha_update_entity_registry"](entity_id, updates))

    def _entrada(self, plataforma: str) -> dict[str, Any]:
        return {"entity_id": "switch.ejemplo_pre_release", "platform": plataforma,
                "disabled_by": "integration", "hidden_by": None,
                "entity_category": "config", "translation_key": "pre-release"}

    async def test_habilitar_avisa(self) -> None:
        self.entrada = self._entrada("marketplace")
        for updates in ({"disabled_by": None}, {"disabled_by": False}, {"hidden_by": None}):
            with self.subTest(updates=updates):
                r = await self._vista("switch.ejemplo_pre_release", updates)
                self.assertIn("confirmation_token", r)
                self.assertIn("BETA", r["preview"]["warning_marketplace_beta"])

    async def test_sin_registro_avisa_igual(self) -> None:
        r = await self._vista("switch.ejemplo_pre_release", {"disabled_by": None})
        self.assertIn("warning_marketplace_beta", r["preview"])

    async def test_otro_interruptor_o_deshabilitar_no_avisa(self) -> None:
        self.entrada = self._entrada("template")
        r = await self._vista("switch.ejemplo_pre_release", {"disabled_by": None})
        self.assertNotIn("warning_marketplace_beta", r["preview"])
        self.entrada = self._entrada("marketplace")
        r = await self._vista("switch.ejemplo_pre_release", {"disabled_by": "user"})
        self.assertNotIn("warning_marketplace_beta", r["preview"])


# ── 8. Credenciales de una URL tapadas como `usuario:***@` ───────────────────


class TestCredencialTapada(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from hermes.mcp_server import build_mcp_server

        self.server = build_mcp_server("prueba")
        self.llamadas: list[tuple[str, Any]] = []

        async def escribe(url: str, confirmation_token: str | None = None) -> dict[str, Any]:
            self.llamadas.append(("escribe", url))
            return {"confirmation_token": "t", "preview": {}}

        async def lee(texto: str) -> dict[str, Any]:
            self.llamadas.append(("lee", texto))
            return {"ok": True}

        # Nombres que la clasificación conoce: uno que escribe y uno que lee.
        self.server.add_tool(escribe, name="sv_add_store_repository")
        self.server.add_tool(lee, name="ha_render_template")

    async def test_escritura_con_url_tapada(self) -> None:
        tapada = redact_secrets("https://usuario:token-real@git.example.com/repo")
        self.assertIn(":***@", tapada)  # la forma que deja la lectura
        r = await self.server.call_tool("sv_add_store_repository", {"url": tapada})
        self.assertTrue(r.is_error)
        datos = json.loads(r.content[0].text)
        self.assertEqual(datos["error"], "redacted_value_in_payload")
        self.assertEqual(datos["paths"], ["url"])
        self.assertEqual(self.llamadas, [])

    async def test_anidado_en_una_lista(self) -> None:
        from hermes.tools._common import CREDENCIAL_TAPADA, rutas_con_marcador

        carga = {"cors_allowed_origins": ["https://ok.example", "http://u:***@x.example"]}
        self.assertEqual(rutas_con_marcador(carga, marcador=CREDENCIAL_TAPADA),
                         ["cors_allowed_origins[1]"])

    async def test_url_real_y_lectura_pasan(self) -> None:
        await self.server.call_tool("sv_add_store_repository",
                                    {"url": "https://usuario:token@git.example.com/repo"})
        await self.server.call_tool("ha_render_template", {"texto": "http://u:***@x"})
        self.assertEqual([n for n, _ in self.llamadas], ["escribe", "lee"])

