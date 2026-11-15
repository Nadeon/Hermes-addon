"""Red del host del Supervisor (spec 032, tramo 2; CAP-090, FR-082 de la 008).

`sv_reload_network`, `sv_update_network_interface` y `sv_create_vlan` contra
el Supervisor simulado de `tests/fixtures/supervisor_host.py` (forma v1 del
Supervisor 2026.11.0, datos genéricos: 192.0.2.x, «mi-red» y la PSK
centinela).

Lo que se vigila, además de cada petición exacta:

- la guarda de la interfaz de acceso: la principal, la única conectada y
  cualquiera si no se sabe cuál es la principal se rechazan SIEMPRE, sin
  token y sin ninguna escritura, también con un cambio inocuo (FR-007,
  D-032-2, SC-002);
- los bloques incompletos o contradictorios se rechazan antes de llamar,
  porque el Supervisor los reemplaza enteros (FR-008);
- la PSK no sale en la vista previa, la respuesta, un error del Supervisor
  que la repite, el log ni el directorio de tokens (FR-010, SC-003);
- el token ata los argumentos (la PSK por el HMAC) y la huella del estado,
  pero no la señal Wi-Fi ni `ready` (FR-011, SC-004);
- un corte después de enviar es `outcome: "unknown"` (FR-013);
- el log no lleva IP, puerta de enlace, DNS, SSID, MAC ni PSK (FR-012).

Controles negativos del tramo 2 (T026), con recuentos, en el mensaje del
commit y en `specs/032-host-y-red-del-host/tasks.md`.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from structlog.testing import capture_logs

from hermes import security
from hermes.tools.host_network import register
from tests.fixtures.supervisor_host import (
    GATEWAY,
    IP_ETH0,
    IP_WLAN0,
    MAC,
    PSK,
    SSID,
    UUID_MADRE,
    SupervisorDeRed,
    corte,
    error_que_repite_la_psk,
    interfaz_eth1,
    red,
    red_sin_principal,
    red_vlan_principal,
    red_vlan_sobre_vlan,
    red_wlan0_unica_conectada,
)
from hermes.ha import HAConnectionError


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _texto(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, default=str)


WIFI = {"mode": "infrastructure", "auth": "wpa-psk", "ssid": SSID, "psk": PSK}
KW_WLAN = {"interface": "wlan0", "wifi": WIFI, "ipv4": {"method": "auto"}}
IP_NUEVA = "192.0.2.50/24"


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._montar()

    def _montar(self, interfaces: list[dict[str, Any]] | None = None) -> None:
        self.sv = SupervisorDeRed(interfaces)
        self.mcp = DummyMCP()
        register(self.mcp, self.sv)
        self.t = self.mcp.tools

    async def _vista(self, tool: str, **kw: Any) -> dict[str, Any]:
        antes = len(self.sv.escrituras)
        vista = await self.t[tool](**kw)
        self.assertIn("confirmation_token", vista, vista)
        self.assertEqual(len(self.sv.escrituras), antes, "la vista previa escribió")
        return vista

    async def _confirmar(self, tool: str, **kw: Any) -> tuple[dict, dict]:
        vista = await self._vista(tool, **kw)
        hecho = await self.t[tool](**kw, confirmation_token=vista["confirmation_token"])
        return vista, hecho

    def _sin_escrituras_ni_token(self, r: dict[str, Any]) -> None:
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras, [])


# ── T017: recargar, editar y crear VLAN ─────────────────────────────────────


class TestRecargar(_Base):
    async def test_post_sin_token_y_conectividad(self) -> None:
        self.sv.host_internet = False
        r = await self.t["sv_reload_network"]()
        self.assertEqual(r, {"result": "ok", "host_internet": False,
                             "supervisor_internet": True})
        self.assertEqual(self.sv.escrituras, [
            {"metodo": "POST", "ruta": "/network/reload", "json_body": None}])

    async def test_no_tiene_token(self) -> None:
        with self.assertRaises(TypeError):
            await self.t["sv_reload_network"](confirmation_token="x")

    async def test_error_del_supervisor(self) -> None:
        self.sv.errores[("POST", "/network/reload")] = corte()
        r = await self.t["sv_reload_network"]()
        self.assertIn("error", r)
        self.assertNotIn("result", r)

    async def test_relectura_fallida(self) -> None:
        self.sv.interfaces = None
        r = await self.t["sv_reload_network"]()
        self.assertEqual(r["result"], "ok")
        self.assertIsNone(r["host_internet"])
        self.assertIn("/network/info", r["verify_with"])


class TestEditarInterfaz(_Base):
    async def test_vista_previa(self) -> None:
        vista = await self._vista("sv_update_network_interface", **KW_WLAN)
        p = vista["preview"]
        self.assertEqual(p["action"], "update_network_interface")
        self.assertEqual(p["interface"], "wlan0")
        self.assertEqual(p["role"], {"primary": False, "connected": False,
                                     "other_connected": ["eth0", "eth0.10"]})
        # Antes: la interfaz leída, sin la MAC.
        self.assertEqual(p["before"]["interface"], "wlan0")
        self.assertNotIn("mac", p["before"])
        self.assertEqual(p["before"]["ipv4"]["address"], [IP_WLAN0])
        # Después: lo que se envía, con la PSK como "set".
        self.assertEqual(p["after"], {
            "ipv4": {"method": "auto"},
            "wifi": {"mode": "infrastructure", "auth": "wpa-psk", "ssid": SSID,
                     "psk": "set"}})
        self.assertEqual(p["replaces_blocks"], ["ipv4", "wifi"])
        self.assertIn("does NOT roll", p["warning"])
        self.assertIn("default route", p["warning"])
        self.assertNotIn("route_warning", p)
        self.assertEqual([(c["metodo"], c["ruta"]) for c in self.sv.llamadas],
                         [("GET", "/network/info"), ("GET", "/network/interface/wlan0/info")])

    async def test_aviso_de_ruta_con_gateway(self) -> None:
        vista = await self._vista(
            "sv_update_network_interface", interface="wlan0",
            ipv4={"method": "static", "address": [IP_NUEVA], "gateway": GATEWAY})
        p = vista["preview"]
        self.assertIn("default route", p["route_warning"])
        self.assertTrue(p["route_warning"].startswith("WARNING"))
        # La IP vieja y la nueva sí salen: son lo que hay que decidir.
        self.assertEqual(p["before"]["ipv4"]["address"], [IP_WLAN0])
        self.assertEqual(p["after"]["ipv4"]["address"], [IP_NUEVA])

    async def test_confirmar_con_la_carga_exacta(self) -> None:
        _, hecho = await self._confirmar("sv_update_network_interface", **KW_WLAN)
        self.assertEqual(hecho["result"], "ok", hecho)
        self.assertEqual(self.sv.escrituras, [
            {"metodo": "POST", "ruta": "/network/interface/wlan0/update",
             "json_body": {"ipv4": {"method": "auto"}, "wifi": WIFI}}])
        # La interfaz releída, sin MAC ni PSK.
        self.assertEqual(hecho["interface"]["interface"], "wlan0")
        self.assertEqual(hecho["interface"]["wifi"]["ssid"], SSID)
        self.assertNotIn("mac", hecho["interface"])
        self.assertNotIn("psk", hecho["interface"]["wifi"])

    async def test_carga_normalizada(self) -> None:
        _, hecho = await self._confirmar(
            "sv_update_network_interface", interface="wlan0",
            ipv6={"method": "static", "address": ["2001:DB8:0:0::20/64"]},
            mdns="resolve", enabled=True)
        self.assertEqual(hecho["result"], "ok")
        self.assertEqual(self.sv.escrituras[0]["json_body"], {
            "ipv6": {"method": "static", "address": ["2001:db8::20/64"]},
            "enabled": True, "mdns": "resolve"})

    async def test_relectura_fallida(self) -> None:
        vista = await self._vista("sv_update_network_interface", **KW_WLAN)
        # La guarda relee la interfaz antes de enviar: el fallo tiene que
        # llegar DESPUÉS del POST, así que se arma en ese momento.
        original = self.sv.sv_request

        async def fallar_tras_post(method, sv_path, json_body=None, **kw):
            r = await original(method, sv_path, json_body, **kw)
            if method == "POST":
                self.sv.errores[("GET", "/network/interface/wlan0/info")] = corte()
            return r

        self.sv.sv_request = fallar_tras_post  # type: ignore[method-assign]
        hecho = await self.t["sv_update_network_interface"](
            **KW_WLAN, confirmation_token=vista["confirmation_token"])
        self.assertEqual(hecho["result"], "ok")
        self.assertIsNone(hecho["interface"])
        self.assertIn("/network/interface/wlan0/info", hecho["verify_with"])

    async def test_interfaz_inexistente(self) -> None:
        r = await self.t["sv_update_network_interface"](interface="eth9", mdns="off")
        self.assertEqual(r["error"], "interface_not_found")
        self._sin_escrituras_ni_token(r)

    async def test_vlan_cuya_madre_es_la_principal_se_puede_editar(self) -> None:
        vista = await self._vista("sv_update_network_interface", interface="eth0.10",
                                  mdns="off")
        self.assertIn("does NOT roll", vista["preview"]["warning"])


class TestCrearVlan(_Base):
    async def test_vista_previa_y_confirmar(self) -> None:
        vista = await self._vista("sv_create_vlan", interface="eth0", vlan_id=20,
                                  ipv4={"method": "auto"})
        p = vista["preview"]
        self.assertEqual((p["action"], p["parent"], p["new_interface"], p["vlan_id"]),
                         ("create_vlan", "eth0", "eth0.20", 20))
        self.assertEqual(p["config"], {"ipv4": {"method": "auto"}})
        # Crear sobre la madre principal se permite, con el aviso de ruta.
        self.assertTrue(p["parent_is_primary"])
        self.assertIn("default route", p["route_warning"])
        hecho = await self.t["sv_create_vlan"](
            interface="eth0", vlan_id=20, ipv4={"method": "auto"},
            confirmation_token=vista["confirmation_token"])
        self.assertEqual(hecho["result"], "ok", hecho)
        self.assertEqual(self.sv.escrituras, [
            {"metodo": "POST", "ruta": "/network/interface/eth0/vlan/20",
             "json_body": {"ipv4": {"method": "auto"}}}])
        self.assertEqual(hecho["interface"]["interface"], "eth0.20")
        self.assertNotIn("mac", hecho["interface"])

    async def test_sin_bloques_usa_los_valores_del_supervisor(self) -> None:
        _, hecho = await self._confirmar("sv_create_vlan", interface="eth0", vlan_id=30)
        self.assertEqual(hecho["result"], "ok")
        self.assertEqual(self.sv.escrituras[0]["json_body"], {})

    async def test_rechazos_sin_token(self) -> None:
        casos = (
            ({"interface": "eth0", "vlan_id": 10}, "vlan_exists"),
            ({"interface": "wlan0", "vlan_id": 20}, "not_ethernet"),
            ({"interface": "eth9", "vlan_id": 20}, "interface_not_found"),
        )
        for kw, error in casos:
            with self.subTest(error=error):
                r = await self.t["sv_create_vlan"](**kw)
                self.assertEqual(r["error"], error, r)
                self._sin_escrituras_ni_token(r)

    async def test_vlan_id_fuera_de_rango(self) -> None:
        for vlan_id in (0, 4095, -1, True, "20", 20.0):
            with self.subTest(vlan_id=vlan_id):
                r = await self.t["sv_create_vlan"](interface="eth0", vlan_id=vlan_id)
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "vlan_id"))
                self.assertEqual(self.sv.llamadas, [])

    async def test_lectura_de_la_red_fallida(self) -> None:
        self.sv.interfaces = None
        r = await self.t["sv_create_vlan"](interface="eth0", vlan_id=20)
        self.assertIn("error", r)
        self._sin_escrituras_ni_token(r)


# ── T018: guarda de acceso y validación de bloques ─────────────────────────


class TestGuardaDeAcceso(_Base):
    async def test_principal_rechazada_siempre(self) -> None:
        # También un cambio inocuo (`mdns`): la regla no razona caso a caso.
        for kw in ({"mdns": "off"}, {"enabled": True},
                   {"ipv4": {"method": "auto"}}):
            with self.subTest(kw=kw):
                r = await self.t["sv_update_network_interface"](interface="eth0", **kw)
                self.assertEqual(r["error"], "primary_interface", r)
                self.assertIn("Home Assistant UI", r["detail"])
                self.assertIn("roll", r["detail"])
                self._sin_escrituras_ni_token(r)

    async def test_default_es_la_principal(self) -> None:
        for nombre in ("default", "DEFAULT"):
            r = await self.t["sv_update_network_interface"](interface=nombre, mdns="off")
            self.assertEqual((r["error"], r["field"]), ("invalid_argument", "interface"))
        self.assertEqual(self.sv.llamadas, [])

    async def test_unica_conectada(self) -> None:
        self._montar(red_wlan0_unica_conectada())
        r = await self.t["sv_update_network_interface"](interface="wlan0", mdns="off")
        self.assertEqual(r["error"], "only_connected_interface", r)
        self._sin_escrituras_ni_token(r)

    async def test_principal_desconocida(self) -> None:
        casos = {
            "sin principal": lambda sv: setattr(sv, "interfaces", red_sin_principal()),
            "lectura fallida": lambda sv: setattr(sv, "interfaces", None),
            "forma inesperada": lambda sv: sv.formas.__setitem__(
                ("GET", "/network/info"), {"interfaces": "eth0"}),
            "dos principales": lambda sv: sv.interfaz("wlan0").__setitem__("primary", True),
            "corte": lambda sv: sv.errores.__setitem__(("GET", "/network/info"), corte()),
        }
        for nombre, preparar in casos.items():
            with self.subTest(caso=nombre):
                self._montar()
                preparar(self.sv)
                r = await self.t["sv_update_network_interface"](interface="wlan0",
                                                                 mdns="off")
                self.assertEqual(r["error"], "primary_unknown", r)
                self.assertIn("Home Assistant UI", r["detail"])
                self._sin_escrituras_ni_token(r)

    async def test_la_guarda_se_repite_al_confirmar(self) -> None:
        vista = await self._vista("sv_update_network_interface", **KW_WLAN)
        self.sv.interfaz("eth0")["primary"] = False
        self.sv.interfaz("wlan0")["primary"] = True
        r = await self.t["sv_update_network_interface"](
            **KW_WLAN, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "primary_interface", r)
        self.assertEqual(self.sv.escrituras, [])

    async def test_pasa_a_unica_conectada_al_confirmar(self) -> None:
        vista = await self._vista("sv_update_network_interface", **KW_WLAN)
        for i in self.sv.interfaces:
            i["connected"] = i["interface"] == "wlan0"
        r = await self.t["sv_update_network_interface"](
            **KW_WLAN, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "only_connected_interface", r)
        self.assertEqual(self.sv.escrituras, [])


class TestValidacionDeBloques(_Base):
    CASOS: tuple[tuple[str, dict[str, Any], str], ...] = (
        ("sin method", {"ipv4": {"address": [IP_NUEVA]}}, "ipv4.method"),
        ("method raro", {"ipv4": {"method": "dhcp"}}, "ipv4.method"),
        ("static sin dirección", {"ipv4": {"method": "static"}}, "ipv4.address"),
        ("static lista vacía", {"ipv4": {"method": "static", "address": []}}, "ipv4.address"),
        ("auto con dirección", {"ipv4": {"method": "auto", "address": [IP_NUEVA]}},
         "ipv4.address"),
        ("auto con gateway", {"ipv4": {"method": "auto", "gateway": GATEWAY}},
         "ipv4.address"),
        ("disabled con dirección",
         {"ipv6": {"method": "disabled", "address": ["2001:db8::1/64"]}}, "ipv6.address"),
        ("IPv6 en ipv4", {"ipv4": {"method": "static", "address": ["2001:db8::1/64"]}},
         "ipv4.address"),
        ("sin prefijo", {"ipv4": {"method": "static", "address": ["192.0.2.50"]}},
         "ipv4.address"),
        ("IP mal formada", {"ipv4": {"method": "static", "address": ["192.0.2.500/24"]}},
         "ipv4.address"),
        ("máscara mal", {"ipv4": {"method": "static", "address": ["192.0.2.5/40"]}},
         "ipv4.address"),
        ("address no lista", {"ipv4": {"method": "static", "address": IP_NUEVA}},
         "ipv4.address"),
        ("gateway IPv6 en ipv4",
         {"ipv4": {"method": "static", "address": [IP_NUEVA], "gateway": "2001:db8::1"}},
         "ipv4.gateway"),
        ("dns de otra familia", {"ipv4": {"method": "auto", "nameservers": ["2001:db8::53"]}},
         "ipv4.nameservers"),
        ("demasiados dns", {"ipv4": {"method": "auto",
                                     "nameservers": [f"192.0.2.{n}" for n in range(9)]}},
         "ipv4.nameservers"),
        ("route_metric bool", {"ipv4": {"method": "auto", "route_metric": True}},
         "ipv4.route_metric"),
        ("route_metric negativo", {"ipv4": {"method": "auto", "route_metric": -1}},
         "ipv4.route_metric"),
        ("addr_gen_mode raro", {"ipv6": {"method": "auto", "addr_gen_mode": "random"}},
         "ipv6.addr_gen_mode"),
        ("ip6_privacy en ipv4", {"ipv4": {"method": "auto", "ip6_privacy": "enabled"}},
         "ipv4.ip6_privacy"),
        ("clave desconocida", {"ipv4": {"method": "auto", "dns": ["192.0.2.1"]}},
         "ipv4.dns"),
        ("ipv4 no dict", {"ipv4": "auto"}, "ipv4"),
        ("wifi sin auth", {"wifi": {"mode": "infrastructure", "ssid": SSID, "psk": PSK}},
         "wifi.auth"),
        ("wifi sin ssid", {"wifi": {"mode": "infrastructure", "auth": "wpa-psk", "psk": PSK}},
         "wifi.ssid"),
        ("wifi sin mode", {"wifi": {"auth": "wpa-psk", "ssid": SSID, "psk": PSK}},
         "wifi.mode"),
        ("ssid de 33 bytes", {"wifi": {**WIFI, "ssid": "x" * 33}}, "wifi.ssid"),
        ("ssid multibyte largo", {"wifi": {**WIFI, "ssid": "ñ" * 17}}, "wifi.ssid"),
        ("ssid vacío", {"wifi": {**WIFI, "ssid": ""}}, "wifi.ssid"),
        ("wpa-psk sin psk", {"wifi": {"mode": "infrastructure", "auth": "wpa-psk",
                                      "ssid": SSID}}, "wifi.psk"),
        ("wep", {"wifi": {**WIFI, "auth": "wep", "psk": "clave"}}, "wifi.auth"),
        ("wep sin psk", {"wifi": {"mode": "infrastructure", "auth": "wep", "ssid": SSID}},
         "wifi.auth"),
        ("dns con disabled", {"ipv4": {"method": "disabled", "nameservers": [GATEWAY]}},
         "ipv4.nameservers"),
        ("dns ipv6 con disabled",
         {"ipv6": {"method": "disabled", "nameservers": ["2001:db8::53"]}},
         "ipv6.nameservers"),
        ("addr_gen_mode con static",
         {"ipv6": {"method": "static", "address": ["2001:db8::20/64"],
                   "addr_gen_mode": "eui64"}}, "ipv6.addr_gen_mode"),
        ("ip6_privacy con disabled", {"ipv6": {"method": "disabled", "ip6_privacy": "enabled"}},
         "ipv6.ip6_privacy"),
        ("enabled false con otro bloque", {"enabled": False, "mdns": "off"}, "enabled"),
        ("enabled false con wifi", {"enabled": False, "wifi": WIFI}, "enabled"),
        ("psk de 7", {"wifi": {**WIFI, "psk": "1234567"}}, "wifi.psk"),
        ("psk de 64 no hex", {"wifi": {**WIFI, "psk": "z" * 64}}, "wifi.psk"),
        ("psk con open", {"wifi": {**WIFI, "auth": "open"}}, "wifi.psk"),
        ("auth unsupported", {"wifi": {**WIFI, "auth": "unsupported"}}, "wifi.auth"),
        ("clave desconocida wifi", {"wifi": {**WIFI, "bssid": "x"}}, "wifi.bssid"),
        ("enabled texto", {"enabled": "yes"}, "enabled"),
        ("mdns on", {"mdns": "on"}, "mdns"),
        ("llmnr raro", {"llmnr": True}, "llmnr"),
        ("ningún cambio", {}, "interface"),
    )

    async def test_cada_regla(self) -> None:
        for nombre, kw, campo in self.CASOS:
            with self.subTest(caso=nombre):
                self._montar()
                r = await self.t["sv_update_network_interface"](interface="wlan0", **kw)
                self.assertEqual((r.get("error"), r.get("field")),
                                 ("invalid_argument", campo), r)
                self.assertEqual(self.sv.llamadas, [])
                # El mensaje dice la regla, nunca el valor.
                for valor in (PSK, IP_NUEVA, "192.0.2.500", "2001:db8::53", "dhcp", "x" * 33):
                    self.assertNotIn(valor, r["detail"])

    async def test_validos(self) -> None:
        validos = (
            {"ipv4": {"method": "static", "address": [IP_NUEVA], "gateway": GATEWAY,
                      "nameservers": [GATEWAY], "route_metric": 100}},
            {"ipv4": {"method": "disabled"}},
            {"ipv6": {"method": "auto", "ip6_privacy": "enabled-prefer-public"}},
            {"wifi": {"mode": "infrastructure", "auth": "open", "ssid": SSID}},
            {"wifi": {**WIFI, "psk": "a" * 64}},
            {"ipv4": {"method": "disabled", "nameservers": [], "route_metric": 10}},
            {"ipv6": {"method": "auto", "addr_gen_mode": "eui64", "ip6_privacy": "enabled"}},
            {"enabled": True, "mdns": "off"},
            {"llmnr": "announce"},
            {"enabled": False},
        )
        for kw in validos:
            with self.subTest(kw=kw):
                self._montar()
                r = await self.t["sv_update_network_interface"](interface="wlan0", **kw)
                self.assertIn("confirmation_token", r, r)

    async def test_vlan_valida_sus_bloques(self) -> None:
        r = await self.t["sv_create_vlan"](interface="eth0", vlan_id=20,
                                           ipv4={"method": "static"})
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "ipv4.address"))
        self.assertEqual(self.sv.llamadas, [])

    async def test_nombres_de_interfaz_invalidos(self) -> None:
        for nombre in ("", "../x", "eth0/update", "wlan 0", "a" * 16, None, 5, "e%2f"):
            with self.subTest(nombre=nombre):
                r = await self.t["sv_update_network_interface"](interface=nombre, mdns="off")
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "interface"))
        self.assertEqual(self.sv.llamadas, [])


# ── T019: PSK, token atado, corte tras enviar y log ────────────────────────


def _ficheros_de_tokens() -> str:
    directorio = Path(security.CONFIRMATIONS_DIR)
    if not directorio.exists():
        return ""
    return "".join(p.read_text(encoding="utf-8", errors="replace")
                   for p in directorio.iterdir() if p.is_file())


class TestPsk(_Base):
    """SC-003: la PSK centinela no aparece en ningún camino."""

    async def test_no_sale_por_ningun_camino(self) -> None:
        with capture_logs() as eventos:
            vista = await self._vista("sv_update_network_interface", **KW_WLAN)
            self.assertNotIn(PSK, _texto(vista))
            self.assertNotIn(PSK, _ficheros_de_tokens())
            hecho = await self.t["sv_update_network_interface"](
                **KW_WLAN, confirmation_token=vista["confirmation_token"])
            self.assertEqual(hecho["result"], "ok")
            self.assertNotIn(PSK, _texto(hecho))
            self.assertNotIn(PSK, _ficheros_de_tokens())
            # Pero al Supervisor sí le llega.
            self.assertEqual(self.sv.escrituras[0]["json_body"]["wifi"]["psk"], PSK)
        self.assertNotIn(PSK, _texto(eventos))

    async def test_error_que_la_repite(self) -> None:
        self.sv.errores[("POST", "/network/interface/wlan0/update")] = \
            error_que_repite_la_psk()
        with capture_logs() as eventos:
            _, r = await self._confirmar("sv_update_network_interface", **KW_WLAN)
        self.assertIn("error", r)
        self.assertIn("rejected", r["error"])
        self.assertNotIn(PSK, _texto(r))
        self.assertNotIn(PSK, _texto(eventos))
        self.assertNotIn(PSK, _ficheros_de_tokens())

    async def test_error_de_lectura_que_la_repite(self) -> None:
        # Al confirmar, la relectura previa falla con un texto que trae la PSK.
        vista = await self._vista("sv_update_network_interface", **KW_WLAN)
        self.sv.errores[("GET", "/network/interface/wlan0/info")] = \
            error_que_repite_la_psk()
        r = await self.t["sv_update_network_interface"](
            **KW_WLAN, confirmation_token=vista["confirmation_token"])
        self.assertIn("error", r)
        self.assertNotIn(PSK, _texto(r))

    async def test_psk_invalidas(self) -> None:
        for psk in (security.REDACTED_MARKER, "clave\ncon-salto", "set", "", 12345678):
            with self.subTest(psk=psk):
                r = await self.t["sv_update_network_interface"](
                    interface="wlan0", wifi={**WIFI, "psk": psk})
                self.assertEqual((r["error"], r["field"]), ("invalid_argument", "wifi.psk"))
        self.assertEqual(self.sv.llamadas, [])


class TestTokenAtado(_Base):
    async def _con_otro(self, kw: dict, otro: dict) -> dict:
        vista = await self._vista("sv_update_network_interface", **kw)
        return await self.t["sv_update_network_interface"](
            **otro, confirmation_token=vista["confirmation_token"])

    async def test_otro_argumento_no_ejecuta(self) -> None:
        estatica = {"interface": "wlan0",
                    "ipv4": {"method": "static", "address": [IP_NUEVA]}}
        casos = (
            (KW_WLAN, {**KW_WLAN, "wifi": {**WIFI, "psk": "otra-clave-larga"}}),
            (KW_WLAN, {**KW_WLAN, "wifi": {**WIFI, "ssid": "otra-red"}}),
            (estatica, {**estatica, "ipv4": {"method": "static",
                                              "address": ["192.0.2.51/24"]}}),
            (KW_WLAN, {**KW_WLAN, "mdns": "off"}),
        )
        for kw, otro in casos:
            with self.subTest(otro=otro):
                self._montar()
                r = await self._con_otro(kw, otro)
                self.assertIn("error", r)
                self.assertNotEqual(r.get("result"), "ok")
                self.assertEqual(self.sv.escrituras, [])

    async def test_vlan_con_otro_id_no_ejecuta(self) -> None:
        vista = await self._vista("sv_create_vlan", interface="eth0", vlan_id=20)
        r = await self.t["sv_create_vlan"](interface="eth0", vlan_id=21,
                                           confirmation_token=vista["confirmation_token"])
        self.assertIn("error", r)
        self.assertEqual(self.sv.escrituras, [])

    async def test_estado_cambiado_no_ejecuta(self) -> None:
        def config(sv: SupervisorDeRed) -> None:
            sv.interfaz("wlan0")["ipv4"]["address"] = ["192.0.2.21/24"]

        def conectada(sv: SupervisorDeRed) -> None:
            sv.interfaz("wlan0")["connected"] = True

        def otra_conectada(sv: SupervisorDeRed) -> None:
            sv.interfaz("eth0.10")["connected"] = False

        for cambiar in (config, conectada, otra_conectada):
            with self.subTest(cambio=cambiar.__name__):
                self._montar()
                vista = await self._vista("sv_update_network_interface", **KW_WLAN)
                cambiar(self.sv)
                r = await self.t["sv_update_network_interface"](
                    **KW_WLAN, confirmation_token=vista["confirmation_token"])
                self.assertEqual(r["error"], "state_changed", r)
                self.assertEqual(self.sv.escrituras, [])

    async def test_vlan_estado_cambiado(self) -> None:
        vista = await self._vista("sv_create_vlan", interface="eth0", vlan_id=20)
        self.sv.interfaz("eth0")["mdns"] = "off"
        r = await self.t["sv_create_vlan"](interface="eth0", vlan_id=20,
                                           confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "state_changed", r)
        self.assertEqual(self.sv.escrituras, [])

    async def test_senal_y_ready_no_invalidan(self) -> None:
        vista = await self._vista("sv_update_network_interface", **KW_WLAN)
        self.sv.interfaz("wlan0")["wifi"]["signal"] = 35
        self.sv.interfaz("wlan0")["ipv4"]["ready"] = True
        self.sv.interfaz("wlan0")["ipv6"]["ready"] = True
        self.sv.interfaz("eth0")["ipv4"]["ready"] = False
        hecho = await self.t["sv_update_network_interface"](
            **KW_WLAN, confirmation_token=vista["confirmation_token"])
        self.assertEqual(hecho["result"], "ok", hecho)

    async def test_un_token_sirve_una_vez(self) -> None:
        vista, hecho = await self._confirmar("sv_update_network_interface", **KW_WLAN)
        self.assertEqual(hecho["result"], "ok")
        otra = await self.t["sv_update_network_interface"](
            **KW_WLAN, confirmation_token=vista["confirmation_token"])
        self.assertIn("error", otra)
        self.assertEqual(len(self.sv.escrituras), 1)


class TestCorteTrasEnviar(_Base):
    async def test_corte_tras_enviar_es_unknown(self) -> None:
        casos = (
            ("sv_update_network_interface", KW_WLAN, "/network/interface/wlan0/update",
             "/network/interface/wlan0/info"),
            ("sv_create_vlan", {"interface": "eth0", "vlan_id": 20},
             "/network/interface/eth0/vlan/20", "/network/interface/eth0.20/info"),
        )
        for tool, kw, ruta, verify in casos:
            for exc in (corte(), TimeoutError()):
                with self.subTest(tool=tool, exc=type(exc).__name__):
                    self._montar()
                    self.sv.errores[("POST", ruta)] = exc
                    vista = await self._vista(tool, **kw)
                    token = vista["confirmation_token"]
                    r = await self.t[tool](**kw, confirmation_token=token)
                    self.assertEqual(r["outcome"], "unknown", r)
                    self.assertNotIn("result", r)
                    self.assertNotIn("error", r)
                    self.assertTrue(r["hint"])
                    self.assertIn(verify, r["verify_with"])
                    otra = await self.t[tool](**kw, confirmation_token=token)
                    self.assertIn("error", otra)
                    self.assertEqual(len(self.sv.escrituras), 1)


class TestContratoSent(_Base):
    """Integración con la 022: el `_enviar` de la red del host respeta el
    contrato de tres valores de `HAConnectionError.sent`. `False` (o una
    conexión que ni se estableció) es «no se hizo nada»: error con
    `sent: false`, sin la PSK, nunca `outcome: "unknown"`. `True` y `None`
    no aseguran nada: `unknown`, nunca `ok`. Recargar tampoco deja escapar
    un corte como excepción.

    Control negativo comprobado: con `_no_salio` devolviendo siempre False,
    `test_no_salio_es_error_sin_unknown` cae (sale `outcome: "unknown"`) y
    `test_recargar_sin_salir` también (sin `sent`); restaurado, verde."""

    async def test_no_salio_es_error_sin_unknown(self) -> None:
        import aiohttp
        from unittest.mock import MagicMock

        ruta = "/network/interface/wlan0/update"
        for exc in (HAConnectionError(f"Cliente HTTP no inicializado {PSK}", sent=False),
                    aiohttp.ClientConnectorError(MagicMock(), OSError(111, "refused"))):
            with self.subTest(exc=type(exc).__name__):
                self._montar()
                self.sv.errores[("POST", ruta)] = exc
                vista = await self._vista("sv_update_network_interface", **KW_WLAN)
                token = vista["confirmation_token"]
                r = await self.t["sv_update_network_interface"](
                    **KW_WLAN, confirmation_token=token)
                self.assertIs(r.get("sent"), False, r)
                self.assertIn("nothing was done", r["note"])
                self.assertNotIn("outcome", r)
                self.assertNotIn(PSK, json.dumps(r))
                otra = await self.t["sv_update_network_interface"](
                    **KW_WLAN, confirmation_token=token)
                self.assertIn("error", otra)
                self.assertEqual(len(self.sv.escrituras), 1)

    async def test_salio_es_unknown(self) -> None:
        self._montar()
        self.sv.errores[("POST", "/network/interface/eth0/vlan/20")] = HAConnectionError(
            "Timeout esperando al Supervisor", sent=True)
        kw = {"interface": "eth0", "vlan_id": 20}
        vista = await self._vista("sv_create_vlan", **kw)
        r = await self.t["sv_create_vlan"](**kw, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r.get("outcome"), "unknown", r)
        self.assertNotIn("sent", r)

    async def test_recargar_sin_salir(self) -> None:
        import aiohttp

        for exc, sent in ((HAConnectionError("no inicializado", sent=False), False),
                          (aiohttp.ServerDisconnectedError(), None),
                          (TimeoutError(), None)):
            with self.subTest(exc=type(exc).__name__):
                self._montar()
                self.sv.errores[("POST", "/network/reload")] = exc
                r = await self.t["sv_reload_network"]()
                self.assertTrue(r["error"], r)
                self.assertNotIn("result", r)
                self.assertIs(r.get("sent"), sent, r)


class TestLog(_Base):
    _PROHIBIDO = (IP_ETH0, IP_WLAN0, "192.0.2.", GATEWAY, SSID, MAC, PSK, IP_NUEVA)

    async def test_eventos_sin_valores(self) -> None:
        with capture_logs() as eventos:
            await self._confirmar("sv_update_network_interface", **KW_WLAN)
            self._montar()
            await self._confirmar(
                "sv_update_network_interface", interface="wlan0",
                ipv4={"method": "static", "address": [IP_NUEVA], "gateway": GATEWAY,
                      "nameservers": [GATEWAY]})
            await self._confirmar("sv_create_vlan", interface="eth0", vlan_id=20,
                                  ipv4={"method": "auto"})
            await self.t["sv_reload_network"]()
            await self.t["sv_update_network_interface"](interface="eth0", mdns="off")
            await self.t["sv_update_network_interface"](
                interface="wlan0", wifi={**WIFI, "ssid": "x" * 40})
        propios = [e for e in eventos if e.get("event") == "host_network"]
        self.assertTrue(propios)
        texto = _texto(eventos)
        for valor in self._PROHIBIDO:
            with self.subTest(valor=valor):
                self.assertNotIn(valor, texto)
        for e in propios:
            self.assertIn("tool", e)
            self.assertIn("outcome", e)
        ok = [e for e in propios if e["outcome"] == "ok"
              and e["tool"] != "sv_reload_network"]
        self.assertEqual([(e["tool"], e["interface"], e["changed"]) for e in ok], [
            ("sv_update_network_interface", "wlan0", ["ipv4", "wifi"]),
            ("sv_update_network_interface", "wlan0", ["ipv4"]),
            ("sv_create_vlan", "eth0", ["ipv4"]),
        ])
        resultados = {e["outcome"] for e in propios}
        self.assertLessEqual({"preview", "ok", "rejected", "invalid_argument"}, resultados)

    async def test_errores_y_cortes_sin_valores(self) -> None:
        self.sv.errores[("POST", "/network/interface/wlan0/update")] = \
            error_que_repite_la_psk()
        with capture_logs() as eventos:
            await self._confirmar("sv_update_network_interface", **KW_WLAN)
            self._montar()
            self.sv.errores[("POST", "/network/interface/eth0/vlan/20")] = corte()
            await self._confirmar("sv_create_vlan", interface="eth0", vlan_id=20)
        texto = _texto(eventos)
        for valor in self._PROHIBIDO:
            self.assertNotIn(valor, texto)
        resultados = {e["outcome"] for e in eventos if e.get("event") == "host_network"}
        self.assertLessEqual({"error", "unknown"}, resultados)


if __name__ == "__main__":
    unittest.main()


# ── T028–T034: arreglos de la convergencia ──────────────────────────────────


class TestMadreDeLaPrincipal(_Base):
    """T028 (A1 de la revisión): con la principal en la VLAN `eth0.10`, su
    madre `eth0` se rechaza igual que la principal. En la v1, `enabled:
    false` sobre `eth0` borra su perfil (`_apply_delete`) y la VLAN, que
    guarda como madre el UUID de ese perfil, no vuelve a levantarse.

    Control negativo: sin la comprobación de `_dependencias_de_la_principal`
    en `_guarda`, caen `test_madre_rechazada` (el escenario de la revisión:
    token y POST), `test_madre_como_uuid_rechaza_todo`,
    `test_vlan_sobre_vlan` y `test_se_repite_al_confirmar`.
    """

    async def test_madre_rechazada(self) -> None:
        self._montar(red_vlan_principal())
        for kw in ({"enabled": False}, {"ipv4": {"method": "auto"}}, {"mdns": "off"}):
            with self.subTest(kw=kw):
                r = await self.t["sv_update_network_interface"](interface="eth0", **kw)
                self.assertEqual(r["error"], "primary_interface_parent", r)
                self.assertIn("eth0.10", r["detail"])
                self.assertIn("Home Assistant UI", r["detail"])
                self._sin_escrituras_ni_token(r)

    async def test_las_demas_se_pueden_editar(self) -> None:
        self._montar(red_vlan_principal())
        for nombre in ("eth1", "wlan0"):
            with self.subTest(interfaz=nombre):
                await self._vista("sv_update_network_interface", interface=nombre,
                                  mdns="off")

    async def test_madre_como_uuid_rechaza_todo(self) -> None:
        # Lo normal tras la primera actualización: `vlan.parent` es el UUID
        # de la conexión, que la API v1 no permite resolver. Sin saber de
        # qué depende la principal, no se edita ninguna (fail-closed).
        for madre in (UUID_MADRE, None, "eth9"):
            self._montar(red_vlan_principal(madre))
            for nombre in ("eth0", "eth1", "wlan0"):
                with self.subTest(madre=madre, interfaz=nombre):
                    r = await self.t["sv_update_network_interface"](
                        interface=nombre, mdns="off")
                    self.assertEqual(r["error"], "primary_dependency_unknown", r)
                    self.assertIn("Home Assistant UI", r["detail"])
                    self._sin_escrituras_ni_token(r)

    async def test_vlan_sobre_vlan(self) -> None:
        self._montar(red_vlan_sobre_vlan())
        for nombre in ("eth0", "eth0.10"):
            with self.subTest(interfaz=nombre):
                r = await self.t["sv_update_network_interface"](interface=nombre,
                                                                 mdns="off")
                self.assertEqual(r["error"], "primary_interface_parent", r)
                self._sin_escrituras_ni_token(r)
        await self._vista("sv_update_network_interface", interface="eth1", mdns="off")

    async def test_se_repite_al_confirmar(self) -> None:
        # La vista previa sale con la principal en `eth1`; antes de
        # confirmar, la principal pasa a la VLAN `eth0.10` sobre `eth0`.
        self._montar([*red(), interfaz_eth1()])
        self.sv.interfaz("eth0")["primary"] = False
        self.sv.interfaz("eth1").update({"primary": True, "connected": True})
        vista = await self._vista("sv_update_network_interface", interface="eth0",
                                  mdns="off")
        self.sv.interfaz("eth1")["primary"] = False
        self.sv.interfaz("eth0.10")["primary"] = True
        r = await self.t["sv_update_network_interface"](
            interface="eth0", mdns="off", confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "primary_interface_parent", r)
        self.assertEqual(self.sv.escrituras, [])


class TestDesactivar(_Base):
    """T030 (A3): `enabled: false` borra el perfil guardado en la v1.

    Control negativo: sin el rechazo de `_validar_bloques`, cae
    `test_con_otros_bloques_sin_token` (la vista previa daba token y enseñaba
    `ipv4` en `after`); sin el aviso, cae `test_solo_avisa_que_borra`.
    """

    async def test_solo_avisa_que_borra(self) -> None:
        vista = await self._vista("sv_update_network_interface", interface="wlan0",
                                  enabled=False)
        p = vista["preview"]
        self.assertEqual(p["after"], {"enabled": False})
        self.assertIs(p["deletes_saved_connection"], True)
        self.assertIn("DELETES the saved connection", p["disable_warning"])
        self.assertIn("psk", p["disable_warning"])
        self.assertIn("full configuration", p["disable_warning"])

    async def test_con_otros_bloques_sin_token(self) -> None:
        r = await self.t["sv_update_network_interface"](
            interface="wlan0", enabled=False, ipv4={"method": "auto"})
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "enabled"))
        self.assertIn("discards", r["detail"])
        self.assertEqual(self.sv.llamadas, [])

    async def test_activar_no_avisa_de_borrado(self) -> None:
        vista = await self._vista("sv_update_network_interface", interface="wlan0",
                                  enabled=True)
        self.assertNotIn("disable_warning", vista["preview"])
        self.assertNotIn("deletes_saved_connection", vista["preview"])


class TestPskEscapada(_Base):
    """T031 (A4): la PSK sale tapada también en sus formas escapadas.

    Control negativo: con `_limpiar` sustituyendo solo el literal, caen los
    casos JSON, JSON sin `ensure_ascii`, `repr` y JSON dentro de JSON.
    """

    PSK_RARA = 'abc"de\\fgñ\'x'

    def _formas(self) -> dict[str, str]:
        psk = self.PSK_RARA
        return {
            "literal": psk,
            "json": json.dumps(psk)[1:-1],
            "json sin ascii": json.dumps(psk, ensure_ascii=False)[1:-1],
            "repr": repr(psk)[1:-1],
            "json en json": json.dumps(json.dumps(psk)[1:-1])[1:-1],
        }

    async def test_formas_escapadas_tapadas(self) -> None:
        wifi = {**WIFI, "psk": self.PSK_RARA}
        for nombre, forma in self._formas().items():
            with self.subTest(forma=nombre):
                self._montar()
                self.sv.errores[("POST", "/network/interface/wlan0/update")] = \
                    HAConnectionError(
                        "Supervisor REST POST http://supervisor/network/interface/"
                        'wlan0/update failed 400: {"result": "error", "message": '
                        f'"key {forma} rejected"}}', status=400)
                with capture_logs() as eventos:
                    _, r = await self._confirmar("sv_update_network_interface",
                                                 interface="wlan0", wifi=wifi)
                self.assertIn("rejected", r["error"])
                salida = _texto(r) + _texto(eventos) + _ficheros_de_tokens()
                for otra in self._formas().values():
                    self.assertNotIn(otra, salida)
                self.assertNotIn(forma, r["error"])


class TestBloquesIgnorados(_Base):
    """T034 (A7): lo que el Supervisor aceptaría e ignoraría se rechaza sin
    token, con el motivo.

    Control negativo: sin la comprobación del `type`, caen los dos casos de
    `test_wifi_fuera_de_una_wireless` (daban token); sin los rechazos de
    `_validar_ip`/`_validar_wifi`, caen sus casos de `TestValidacionDeBloques`
    (`dns con disabled`, `addr_gen_mode con static`, `wep`…).
    """

    async def test_wifi_fuera_de_una_wireless(self) -> None:
        self._montar([*red(), interfaz_eth1()])
        for nombre in ("eth1", "eth0.10"):
            with self.subTest(interfaz=nombre):
                self.sv.llamadas.clear()
                r = await self.t["sv_update_network_interface"](interface=nombre,
                                                                 wifi=WIFI)
                self.assertEqual(r["error"], "wifi_not_wireless", r)
                self.assertIn("not a wireless interface", r["detail"])
                self.assertNotIn(PSK, _texto(r))
                self._sin_escrituras_ni_token(r)

    async def test_wep_explica_el_motivo(self) -> None:
        r = await self.t["sv_update_network_interface"](
            interface="wlan0", wifi={**WIFI, "auth": "wep", "psk": "clave"})
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "wifi.auth"))
        self.assertIn("never connect", r["detail"])
        self.assertEqual(self.sv.llamadas, [])

    async def test_vlan_con_dns_y_disabled(self) -> None:
        r = await self.t["sv_create_vlan"](
            interface="eth0", vlan_id=20,
            ipv4={"method": "disabled", "nameservers": [GATEWAY]})
        self.assertEqual((r["error"], r["field"]), ("invalid_argument", "ipv4.nameservers"))
        self.assertEqual(self.sv.llamadas, [])
