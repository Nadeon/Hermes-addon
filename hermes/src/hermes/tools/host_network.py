"""Hermes — Red del host (spec 032, tramo 2; CAP-090).

Familia `host_network` (1.2.0), módulo `host_network`.

Tools:
  sv_reload_network            — vuelve a leer el estado de la red (sin token)
  sv_update_network_interface  — edita una interfaz que NO sea la de acceso
  sv_create_vlan               — crea una VLAN `<madre>.<id>`

POR QUÉ
-------
Las tres rutas eran `deny` «pendiente de tool dedicada»: por la genérica solo
se ve un método y una ruta, y un cambio de red mal hecho puede dejar la casa
sin Home Assistant y sin Hermes para deshacerlo. El Supervisor aplica el
cambio con `apply_changes` y NO lo revierte solo (no hay commit-confirm): si
la interfaz se queda sin red, nadie puede arreglarlo a distancia.

GUARDA DE LA INTERFAZ DE ACCESO (FR-007, research R-2, D-032-2)
Hermes corre en la red interna de Docker y no ve por qué interfaz del host
llega el cliente. Lo que llega de fuera (LAN, acceso remoto, Funnel) sale por
la ruta por defecto, la de la interfaz `primary`. Por eso se rechaza SIEMPRE,
sin token y sin escribir:
  - la interfaz principal, también con un cambio inocuo como `mdns` (una
    regla simple que no hay que razonar caso a caso);
  - si la principal es una VLAN, su madre (y la madre de esta, si también es
    VLAN): borrar o reactivar el perfil de la madre tumba la VLAN (T028). Si
    la madre no se resuelve a un nombre (el Supervisor la da como UUID de la
    conexión), no se sabe de qué depende la principal y no se edita ninguna;
  - la única conectada, aunque no esté marcada como principal (transitorios
    de NetworkManager: es igualmente el único camino);
  - cualquier interfaz si no se sabe cuál es la principal (lectura fallida,
    ninguna o varias `primary`, forma inesperada): si no se sabe, no se toca;
  - el nombre `default`, que en el Supervisor es un alias de la principal.
La guarda se repite justo antes de enviar, y el papel de la interfaz entra en
la huella del token: si pasa a principal en los 60 s, no se ejecuta.
Crear una VLAN sobre la madre principal SÍ se permite: no edita la madre, y en
un equipo con una sola tarjeta es el único sitio donde crearla. El riesgo real
es que la VLAN (o una interfaz secundaria con puerta de enlace) se quede con
la ruta por defecto: la vista previa lo avisa con fuerza (D-032-3).

BLOQUES COMPLETOS (FR-008, research R-4)
`interface_update` reemplaza cada bloque entero y rellena lo que falta con
valores por defecto: un `ipv4` sin `method` pasa a estático SIN dirección y un
`wifi` sin `auth` pasa a red abierta. Hermes no puede fundir con lo actual (no
puede leer la PSK), así que exige los campos que deciden el resultado y
rechaza los bloques incompletos o contradictorios antes de llamar. También
lo que el Supervisor aceptaría e IGNORARÍA, que la vista previa daría por
aplicado (T034): `wifi` en una interfaz que no es `wireless`, DNS con
`disabled`, `addr_gen_mode`/`ip6_privacy` sin `auto` y la autenticación `wep`
(la clave acaba donde NetworkManager no la lee y la red no conecta).
`enabled: false` BORRA el perfil guardado en la v1 y descarta los demás
bloques: va solo y la vista previa lo dice (T030).

LA PSK NUNCA SALE (FR-010, research R-9)
Entra, se envía al Supervisor y no aparece en la vista previa (`"psk":
"set"`), la respuesta, los errores (se sustituyen el valor literal y sus
formas escapadas de JSON o `repr`, porque el texto del Supervisor puede
repetirla, y se pasa por `redact_secrets`), el log
ni el fichero del token: no hay `omitibles`, así que en disco solo queda el
HMAC de la acción (019). El token la ata por ese HMAC.

`sv_reload_network` va SIN token (D-032-1, research R-3): solo relee el estado
de NetworkManager y fuerza la comprobación de conectividad. Un token obligaría
a anunciarla destructiva y a inventarse un riesgo en la vista previa
(principio V). Es una desviación literal de FR-082 de la 008, anotada.

El log (eventos `host_network`) lleva la tool, el resultado, los nombres de
los bloques que cambian y el nombre de la interfaz (`wlan0`), nunca IP,
puerta de enlace, DNS, SSID, MAC ni PSK (principio VIII, FR-012).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
from typing import Any

import aiohttp
import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.identifiers import InvalidIdentifier, validate_path_segment
from hermes.security import (
    ESTADO_CAMBIADO,
    REDACTED_MARKER,
    complete_confirmation_token,
    create_confirmation_token,
    redact_secrets,
    redact_structure,
    resolve_confirmation_token,
)
from hermes.tools._logs import ArgumentoInvalido

logger = structlog.get_logger(__name__)

_EVENTO = "host_network"

# Vocabularios de `supervisor/host/const.py` (2026.11.0). `unsupported` de
# `AuthMethod` es de solo lectura: el Supervisor no lo acepta al escribir.
_METODOS = ("auto", "static", "disabled")
_ADDR_GEN = ("eui64", "stable-privacy", "default-or-eui64", "default")
_IP6_PRIVACY = ("disabled", "enabled-prefer-public", "enabled", "default")
_WIFI_MODOS = ("infrastructure", "mesh", "adhoc", "ap")
# `wep` NO se admite (T034): el Supervisor 2026.11.0 escribe la clave en
# `802-11-wireless-security.psk` con `key-mgmt: none`, pero NetworkManager
# lee la clave WEP de `wep-key0`, así que la red nunca llega a conectar y la
# vista previa la daría por buena (principio V).
_WIFI_AUTH = ("open", "wpa-psk")
_MULTICAST = ("default", "off", "resolve", "announce")

_CLAVES_IP = {
    "ipv4": ("method", "address", "gateway", "nameservers", "route_metric"),
    "ipv6": ("method", "address", "gateway", "nameservers", "route_metric",
             "addr_gen_mode", "ip6_privacy"),
}
_CLAVES_WIFI = ("mode", "auth", "ssid", "psk")
_DNS_MAX = 8

# Nombre de interfaz de Linux (IFNAMSIZ: 15 caracteres útiles).
_INTERFAZ = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")
# Una clave desconocida solo se repite en el mensaje si tiene forma de clave:
# así un valor pegado por error en el sitio de la clave no sale.
_CLAVE_LEGIBLE = re.compile(r"^[a-z0-9_-]{1,32}$")
_HEX64 = re.compile(r"^[0-9A-Fa-f]{64}$")

# Lo que fluctúa solo y no puede invalidar un token (decisión del supervisor):
# la señal Wi-Fi y si la configuración IP está «lista».
_FLUCTUANTES_IP = ("ready",)
_FLUCTUANTES_WIFI = ("signal",)

_COMO_HACERLO = (
    "Change it from the Home Assistant UI (Settings > System > Network) "
    "with local or physical access to the machine, where a mistake can be "
    "fixed at the console."
)
_PISTA_TOKEN = "Request a new preview and confirm with the token it returns."

_AVISO_FUERTE = (
    "WARNING: the Supervisor applies this immediately and does NOT roll it "
    "back. A wrong setting can leave this interface without network; if it "
    "takes the default route (a gateway, or one handed out by DHCP), it can "
    "cut access to Home Assistant and to Hermes, and nobody could undo it "
    "remotely."
)
_AVISO_RUTA = (
    "WARNING: a gateway on this interface may take the default route from "
    "the primary interface. If it does, Home Assistant and Hermes become "
    "unreachable through the current path until it is fixed locally."
)
_AVISO_DESACTIVAR = (
    "WARNING: enabled false DELETES the saved connection of this interface: "
    "its IP settings and, on Wi-Fi, the network and its key (psk) are lost; "
    "any other block would be discarded. It is not a pause: enabling it "
    "again needs the full configuration (ipv4, ipv6 and, on Wi-Fi, wifi with "
    "its psk)."
)
_AVISO_RUTA_VLAN = (
    "WARNING: a gateway on this VLAN (static, or handed out by DHCP with the "
    "default 'auto') may take the default route from the primary interface. "
    "If it does, Home Assistant and Hermes become unreachable through the "
    "current path until it is fixed locally."
)


# ── Validación (sin llamar a nada; los mensajes dicen la regla, nunca el valor)


def _validar_interfaz(nombre: Any, campo: str = "interface") -> str:
    try:
        validate_path_segment(nombre, field=campo)
    except InvalidIdentifier:
        raise ArgumentoInvalido(
            campo, f"{campo} must be a Linux interface name like 'wlan0' or "
                   "'eth1' (1-15 letters, digits, '.', '_' or '-').") from None
    if not _INTERFAZ.fullmatch(nombre):
        raise ArgumentoInvalido(
            campo, f"{campo} must be a Linux interface name like 'wlan0' or "
                   "'eth1' (1-15 letters, digits, '.', '_' or '-').")
    if nombre.lower() == "default":
        # En el Supervisor, `default` es la interfaz principal.
        raise ArgumentoInvalido(
            campo, "'default' is the Supervisor's alias of the primary "
                   "interface, which Hermes never edits. Name a secondary "
                   "interface.")
    return nombre


def _claves_conocidas(bloque: str, valor: dict[str, Any], permitidas: tuple[str, ...]) -> None:
    for clave in valor:
        if clave not in permitidas:
            nombre = f"{bloque}.{clave}" if isinstance(clave, str) and \
                _CLAVE_LEGIBLE.fullmatch(clave) else bloque
            raise ArgumentoInvalido(
                nombre, f"Unknown key in {bloque}. Allowed: {', '.join(permitidas)}.")


def _elegir(campo: str, valor: Any, vocabulario: tuple[str, ...]) -> str:
    if isinstance(valor, str) and valor in vocabulario:
        return valor
    raise ArgumentoInvalido(campo, f"{campo} must be one of: {', '.join(vocabulario)}.")


def _ip(campo: str, valor: Any, version: int) -> str:
    if isinstance(valor, str):
        try:
            ip = ipaddress.ip_address(valor)
        except ValueError:
            ip = None
        if ip is not None and ip.version == version:
            return str(ip)
    raise ArgumentoInvalido(campo, f"{campo} must be an IPv{version} address.")


def _direcciones(campo: str, valor: Any, version: int) -> list[str]:
    regla = (f"{campo} must be a list of IPv{version} addresses with their "
             f"prefix, like {'192.0.2.20/24' if version == 4 else '2001:db8::20/64'}.")
    if not isinstance(valor, list):
        raise ArgumentoInvalido(campo, regla)
    salida = []
    for d in valor:
        # Sin prefijo, `ip_interface` supone /32 o /128: una dirección sin red.
        if not isinstance(d, str) or "/" not in d:
            raise ArgumentoInvalido(campo, regla)
        try:
            interfaz = ipaddress.ip_interface(d)
        except ValueError:
            raise ArgumentoInvalido(campo, regla) from None
        if interfaz.version != version:
            raise ArgumentoInvalido(campo, regla)
        salida.append(interfaz.with_prefixlen)
    return salida


def _validar_ip(bloque: str, valor: Any) -> dict[str, Any]:
    """Un bloque `ipv4`/`ipv6` completo y coherente, normalizado.

    El Supervisor lo reemplaza entero: lo que falta no se conserva, se pone
    por defecto (research R-4). Por eso `method` es obligatorio y se rechaza
    lo contradictorio (una dirección con `auto`) en vez de dejar que el
    Supervisor la ignore o la convierta en otra cosa.
    """
    version = 4 if bloque == "ipv4" else 6
    if not isinstance(valor, dict):
        raise ArgumentoInvalido(bloque, f"{bloque} must be an object with at least 'method'.")
    _claves_conocidas(bloque, valor, _CLAVES_IP[bloque])
    if "method" not in valor:
        raise ArgumentoInvalido(
            f"{bloque}.method",
            f"{bloque}.method is required: the Supervisor replaces the whole "
            f"block, and without it {bloque} becomes static with no address.")
    metodo = _elegir(f"{bloque}.method", valor["method"], _METODOS)
    salida: dict[str, Any] = {"method": metodo}
    if "address" in valor:
        salida["address"] = _direcciones(f"{bloque}.address", valor["address"], version)
    if "gateway" in valor and valor["gateway"] is not None:
        salida["gateway"] = _ip(f"{bloque}.gateway", valor["gateway"], version)
    if metodo == "static":
        if not salida.get("address"):
            raise ArgumentoInvalido(
                f"{bloque}.address",
                f"{bloque}.address needs at least one address with its prefix "
                "when method is 'static'.")
    elif salida.get("address") or "gateway" in salida:
        raise ArgumentoInvalido(
            f"{bloque}.address",
            f"{bloque}.address and {bloque}.gateway are only allowed when "
            "method is 'static'.")
    if "nameservers" in valor:
        dns = valor["nameservers"]
        # Con `disabled`, `generate.py` (`_get_ipv4/6_connection_settings`)
        # no escribe los DNS: el Supervisor los aceptaría y los tiraría, y la
        # vista previa los enseñaría como aplicados (T034). Una lista vacía
        # no pide nada y se admite.
        if metodo == "disabled" and dns:
            raise ArgumentoInvalido(
                f"{bloque}.nameservers",
                f"{bloque}.nameservers are ignored by the Supervisor when "
                "method is 'disabled'; remove them or use 'auto' or 'static'.")
        if not isinstance(dns, list) or len(dns) > _DNS_MAX:
            raise ArgumentoInvalido(
                f"{bloque}.nameservers",
                f"{bloque}.nameservers must be a list of up to {_DNS_MAX} "
                f"IPv{version} addresses.")
        salida["nameservers"] = [_ip(f"{bloque}.nameservers", d, version) for d in dns]
    if "route_metric" in valor and valor["route_metric"] is not None:
        metrica = valor["route_metric"]
        # `bool` es un `int` en Python: `True` llegaría como métrica 1.
        if isinstance(metrica, bool) or not isinstance(metrica, int) or metrica < 0:
            raise ArgumentoInvalido(
                f"{bloque}.route_metric",
                f"{bloque}.route_metric must be an integer 0 or greater.")
        salida["route_metric"] = metrica
    if bloque == "ipv6":
        # `addr_gen_mode` e `ip6_privacy` solo se escriben con `auto` (rama
        # AUTO de `_get_ipv6_connection_settings`): con `static` o `disabled`
        # el Supervisor los ignora, así que se rechazan (T034).
        for clave in ("addr_gen_mode", "ip6_privacy"):
            if clave in valor and metodo != "auto":
                raise ArgumentoInvalido(
                    f"ipv6.{clave}",
                    f"ipv6.{clave} is ignored by the Supervisor unless "
                    "ipv6.method is 'auto'; remove it.")
        if "addr_gen_mode" in valor:
            salida["addr_gen_mode"] = _elegir(
                "ipv6.addr_gen_mode", valor["addr_gen_mode"], _ADDR_GEN)
        if "ip6_privacy" in valor:
            salida["ip6_privacy"] = _elegir(
                "ipv6.ip6_privacy", valor["ip6_privacy"], _IP6_PRIVACY)
    return salida


def _tiene_control(texto: str) -> bool:
    return any(ord(c) < 0x20 or ord(c) == 0x7F for c in texto)


def _validar_wifi(valor: Any) -> dict[str, Any]:
    """Un bloque `wifi` completo. Sin `auth`, el Supervisor lo convierte en
    una red ABIERTA; sin `ssid`, en una red sin nombre (research R-4)."""
    if not isinstance(valor, dict):
        raise ArgumentoInvalido("wifi", "wifi must be an object with mode, auth and ssid.")
    _claves_conocidas("wifi", valor, _CLAVES_WIFI)
    for obligatorio in ("mode", "auth", "ssid"):
        if obligatorio not in valor:
            raise ArgumentoInvalido(
                f"wifi.{obligatorio}",
                f"wifi.{obligatorio} is required: the Supervisor replaces the "
                "whole block, and a missing auth becomes an OPEN network.")
    modo = _elegir("wifi.mode", valor["mode"], _WIFI_MODOS)
    if valor["auth"] == "wep":
        raise ArgumentoInvalido(
            "wifi.auth", "wifi.auth 'wep' is not supported: the Supervisor stores "
                         "a WEP key where NetworkManager does not read it, so the "
                         "network would never connect. Use 'wpa-psk' or 'open'.")
    auth = _elegir("wifi.auth", valor["auth"], _WIFI_AUTH)
    ssid = valor["ssid"]
    if (not isinstance(ssid, str) or not 1 <= len(ssid.encode("utf-8")) <= 32
            or _tiene_control(ssid)):
        raise ArgumentoInvalido(
            "wifi.ssid", "wifi.ssid must be 1-32 bytes of text without control characters.")
    salida: dict[str, Any] = {"mode": modo, "auth": auth, "ssid": ssid}
    psk = valor.get("psk")
    if auth == "open":
        if psk is not None:
            raise ArgumentoInvalido(
                "wifi.psk", "wifi.psk is not allowed when wifi.auth is 'open'.")
        return salida
    if psk is None:
        raise ArgumentoInvalido(
            "wifi.psk", f"wifi.psk is required when wifi.auth is '{auth}'.")
    # El marcador de redacción no es una clave: es lo que devuelve una
    # respuesta redactada, y aceptarlo dejaría la red con «***REDACTED***».
    if (not isinstance(psk, str) or not psk or _tiene_control(psk)
            or psk == REDACTED_MARKER or psk == "set"):
        raise ArgumentoInvalido(
            "wifi.psk", "wifi.psk must be the real key as text, without control "
                        "characters (not a redacted placeholder).")
    if auth == "wpa-psk" and not (8 <= len(psk) <= 63 or _HEX64.fullmatch(psk)):
        raise ArgumentoInvalido(
            "wifi.psk", "wifi.psk for 'wpa-psk' must be 8-63 characters or 64 "
                        "hexadecimal digits.")
    salida["psk"] = psk
    return salida


def _validar_multicast(campo: str, valor: Any) -> str:
    return _elegir(campo, valor, _MULTICAST)


def _validar_bloques(
    *, ipv4: Any = None, ipv6: Any = None, wifi: Any = None, enabled: Any = None,
    mdns: Any = None, llmnr: Any = None,
) -> dict[str, Any]:
    """La carga normalizada, solo con lo que se pasó (orden fijo)."""
    carga: dict[str, Any] = {}
    if ipv4 is not None:
        carga["ipv4"] = _validar_ip("ipv4", ipv4)
    if ipv6 is not None:
        carga["ipv6"] = _validar_ip("ipv6", ipv6)
    if wifi is not None:
        carga["wifi"] = _validar_wifi(wifi)
    if enabled is not None:
        if not isinstance(enabled, bool):
            raise ArgumentoInvalido("enabled", "enabled must be true or false.")
        carga["enabled"] = enabled
    if mdns is not None:
        carga["mdns"] = _validar_multicast("mdns", mdns)
    if llmnr is not None:
        carga["llmnr"] = _validar_multicast("llmnr", llmnr)
    if carga.get("enabled") is False and len(carga) > 1:
        # En la v1, `enabled: false` va a `apply_changes(destructive_disable=
        # True)`, que BORRA el perfil guardado: los demás bloques se asignan
        # y se tiran sin aplicarse. Mezclarlos daría una vista previa que
        # miente (T030, principio V).
        raise ArgumentoInvalido(
            "enabled", "enabled false deletes the saved connection and the "
                       "Supervisor discards every other block sent with it. "
                       "Send enabled false alone.")
    return carga


def _validar_vlan_id(vlan_id: Any) -> int:
    # 0 lo admite el Supervisor (etiquetado de prioridad 802.1p, no una VLAN);
    # nadie lo pide a propósito y Hermes lo rechaza (research R-7).
    if isinstance(vlan_id, bool) or not isinstance(vlan_id, int) or not 1 <= vlan_id <= 4094:
        raise ArgumentoInvalido("vlan_id", "vlan_id must be an integer from 1 to 4094.")
    return vlan_id


# ── Formas públicas y huellas ────────────────────────────────────────────────


def _publica(interfaz: dict[str, Any]) -> dict[str, Any]:
    """La interfaz sin `mac` (dato personal que no hace falta para decidir) y
    con el bloque `wifi` solo con las claves conocidas: si un Supervisor
    futuro devolviera la PSK, no saldría."""
    salida = {k: v for k, v in interfaz.items() if k != "mac"}
    wifi = salida.get("wifi")
    if isinstance(wifi, dict):
        salida["wifi"] = {k: wifi[k] for k in ("mode", "auth", "ssid", "signal") if k in wifi}
    return salida


def _sin_fluctuantes(interfaz: dict[str, Any]) -> dict[str, Any]:
    """Para la huella: sin la señal Wi-Fi ni `ready`, que cambian solos y no
    pueden invalidar el token (decisión del supervisor al validar la spec)."""
    salida = _publica(interfaz)
    for bloque in ("ipv4", "ipv6"):
        if isinstance(salida.get(bloque), dict):
            salida[bloque] = {k: v for k, v in salida[bloque].items()
                              if k not in _FLUCTUANTES_IP}
    if isinstance(salida.get("wifi"), dict):
        salida["wifi"] = {k: v for k, v in salida["wifi"].items()
                          if k not in _FLUCTUANTES_WIFI}
    return salida


def _carga_publica(carga: dict[str, Any]) -> dict[str, Any]:
    """Lo que se enviará, con la PSK como `"set"`."""
    salida = dict(carga)
    if isinstance(salida.get("wifi"), dict) and "psk" in salida["wifi"]:
        salida["wifi"] = {**salida["wifi"], "psk": "set"}
    return salida


def _formas_de_la_psk(psk: str) -> list[str]:
    """La PSK y sus formas escapadas, de la más larga a la más corta.

    El texto de un error puede traerla dentro de un JSON (`\\"`, `\\\\`,
    `\\u00f1`), de un `repr` de Python o de un JSON metido en otro JSON: el
    literal no basta si lleva comillas, barras o caracteres no ASCII (T031).
    """
    formas = {psk}
    for base in (json.dumps(psk)[1:-1], json.dumps(psk, ensure_ascii=False)[1:-1],
                 repr(psk)[1:-1]):
        formas.add(base)
        # Un nivel más: el JSON de un error metido en el mensaje de otro.
        formas.add(json.dumps(base)[1:-1])
        formas.add(json.dumps(base, ensure_ascii=False)[1:-1])
    return sorted((f for f in formas if f), key=len, reverse=True)


def _limpiar(texto: str, psk: str | None) -> str:
    """Un texto del Supervisor sin la PSK: primero el valor literal y sus
    formas escapadas (el Supervisor puede repetirla en su mensaje y
    `redact_secrets` no la reconoce sin una clave delante) y después la
    redacción general."""
    if psk:
        for forma in _formas_de_la_psk(psk):
            texto = texto.replace(forma, REDACTED_MARKER)
    return redact_secrets(texto)


class _Rechazo(Exception):
    """Una regla dice que no (sin token). Va tal cual al cliente."""

    def __init__(self, respuesta: dict[str, Any], motivo: str) -> None:
        super().__init__(motivo)
        self.respuesta = respuesta
        self.motivo = motivo


class _Red:
    """`GET /network/info` leído y comprobado."""

    def __init__(self, interfaces: dict[str, dict[str, Any]], principal: str | None,
                 conectadas: list[str]) -> None:
        self.interfaces = interfaces
        self.principal = principal
        self.conectadas = conectadas


def _dependencias_de_la_principal(red: _Red) -> set[str] | None:
    """Las interfaces de las que depende la principal (T028); None si no se
    puede saber.

    En el modelo del Supervisor 2026.11.0 solo hay `ethernet`, `wireless` y
    `vlan` (`InterfaceType`); puentes y *bonds* no se listan (`dbus/network`
    salta cualquier otro tipo), así que si uno de ellos es la principal
    ninguna interfaz sale `primary` y ya se rechaza todo (`primary_unknown`).
    La única dependencia posible es la madre de una VLAN, y la de una VLAN
    sobre otra VLAN. Borrar o reactivar el perfil de la madre tumba la VLAN:
    la VLAN guarda como madre el UUID de la conexión de la madre
    (`generate.py`) y no vuelve a levantarse.

    `vlan.parent` llega como NOMBRE recién creada la VLAN, pero como UUID de
    la conexión después (`VlanConfig` en `host/configuration.py`), y la API
    v1 no da los UUID de las conexiones. Si la madre no se resuelve a una
    interfaz por su nombre, la cadena no se conoce: None, y la guarda no deja
    editar ninguna (fail-closed; decisión del supervisor). No se adivina por
    la forma `<madre>.<id>` del nombre: es una costumbre, no una garantía.
    """
    dependencias: set[str] = set()
    actual = red.principal
    while actual is not None:
        interfaz = red.interfaces.get(actual)
        if interfaz is None:
            return None
        if interfaz["type"] != "vlan":
            return dependencias
        vlan = interfaz.get("vlan")
        madre = vlan.get("parent") if isinstance(vlan, dict) else None
        if (not isinstance(madre, str) or madre not in red.interfaces
                or madre == red.principal or madre in dependencias):
            return None
        dependencias.add(madre)
        actual = madre
    return dependencias


def _es_respuesta_del_supervisor(exc: Exception) -> bool:
    """True si el Supervisor CONTESTÓ con un error (el cambio no se aplicó).
    Lo demás (corte, tiempo agotado) no dice si se aplicó: «unknown»."""
    if isinstance(exc, HAConnectionError):
        return exc.status is not None or str(exc).startswith("Supervisor error:")
    return False


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de la red del host en la instancia MCP."""

    def _log(tool: str, outcome: str, **campos: Any) -> None:
        # Solo nombres: la interfaz (`wlan0`), los bloques y el motivo. Nunca
        # IP, puerta de enlace, DNS, SSID, MAC ni PSK (FR-012).
        logger.info(_EVENTO, tool=tool, outcome=outcome, **campos)

    async def _leer_red(*, para_guarda: bool, psk: str | None = None) -> _Red:
        """Las interfaces por nombre, la principal y las conectadas.

        Con `para_guarda`, todo lo que impida saber cuál es la principal es
        `primary_unknown` (fail-closed, FR-007); sin ella (crear una VLAN),
        un error normal.
        """
        def desconocida(detalle: str) -> _Rechazo:
            if para_guarda:
                return _Rechazo({
                    "error": "primary_unknown",
                    "detail": (f"{detail_base} {detalle} Hermes only edits an "
                               "interface when it knows it is not the one "
                               f"used to reach Home Assistant. {_COMO_HACERLO}"),
                }, "primary_unknown")
            return _Rechazo({"error": f"{detalle}"}, "read_failed")

        detail_base = "Cannot tell which interface is the primary one."
        try:
            datos = await ha_client.sv_request("GET", "/network/info")
        except HAConnectionError as exc:
            raise desconocida(f"GET /network/info failed: {_limpiar(str(exc), psk)}") from None
        lista = datos.get("interfaces") if isinstance(datos, dict) else None
        if not isinstance(lista, list) or not all(
                isinstance(i, dict) and isinstance(i.get("interface"), str)
                and isinstance(i.get("primary"), bool)
                and isinstance(i.get("connected"), bool)
                and isinstance(i.get("type"), str) for i in lista):
            raise desconocida("Unexpected Supervisor response for GET /network/info.")
        interfaces = {i["interface"]: i for i in lista}
        principales = [n for n, i in interfaces.items() if i["primary"]]
        if len(principales) > 1 or (para_guarda and not principales):
            raise desconocida("The Supervisor reports "
                              f"{'no' if not principales else 'more than one'} "
                              "primary interface.")
        conectadas = sorted(n for n, i in interfaces.items() if i["connected"])
        return _Red(interfaces, principales[0] if principales else None, conectadas)

    def _guarda(nombre: str, red: _Red) -> None:
        """FR-007: nunca la interfaz por la que se llega a Home Assistant."""
        if nombre == red.principal:
            raise _Rechazo({
                "error": "primary_interface",
                "detail": (f"{nombre} is the primary interface (the default "
                           "route): it is how the home network, remote access "
                           "and Hermes reach Home Assistant. The Supervisor "
                           "does not roll network changes back, so a mistake "
                           "would leave the house without access and nobody "
                           f"could fix it remotely. Hermes never edits it. "
                           f"{_COMO_HACERLO}"),
            }, "primary_interface")
        if nombre not in red.interfaces:
            raise _Rechazo({"error": "interface_not_found",
                            "detail": f"The Supervisor has no interface {nombre}."},
                           "interface_not_found")
        dependencias = _dependencias_de_la_principal(red)
        if dependencias is None:
            raise _Rechazo({
                "error": "primary_dependency_unknown",
                "detail": (f"The primary interface {red.principal} is a VLAN and "
                           "the Supervisor does not say, by name, which "
                           "interface carries it (it may report the parent as a "
                           "connection id). Editing or disabling that parent "
                           "would take the primary down with it, and Hermes "
                           "cannot tell which one it is, so it edits none. "
                           f"{_COMO_HACERLO}"),
            }, "primary_dependency_unknown")
        if nombre in dependencias:
            raise _Rechazo({
                "error": "primary_interface_parent",
                "detail": (f"{nombre} carries the primary interface "
                           f"{red.principal} (a VLAN on it): disabling or "
                           "reconfiguring it takes the primary down too, and "
                           "the Supervisor does not roll it back. Hermes never "
                           f"edits it. {_COMO_HACERLO}"),
            }, "primary_interface_parent")
        if red.conectadas == [nombre]:
            raise _Rechazo({
                "error": "only_connected_interface",
                "detail": (f"{nombre} is the only connected interface: it is "
                           "the only way to reach Home Assistant right now. "
                           f"Hermes never edits it. {_COMO_HACERLO}"),
            }, "only_connected_interface")

    async def _interfaz(nombre: str, psk: str | None = None) -> dict[str, Any]:
        try:
            datos = await ha_client.sv_request("GET", f"/network/interface/{nombre}/info")
        except HAConnectionError as exc:
            if exc.status == 404:
                raise _Rechazo({"error": "interface_not_found",
                                "detail": f"The Supervisor has no interface {nombre}."},
                               "interface_not_found") from None
            raise _Rechazo({"error": _limpiar(str(exc), psk)}, "read_failed") from None
        if not isinstance(datos, dict) or datos.get("interface") != nombre:
            raise _Rechazo({"error": "Unexpected Supervisor response for GET "
                                     f"/network/interface/{nombre}/info."},
                           "unexpected_shape")
        return datos

    async def _confirmar(tool: str, token: str, args: dict[str, Any],
                         huella: Any) -> dict[str, Any] | None:
        """None si el token vale para estos argumentos y este estado."""
        ok, error, _ = await resolve_confirmation_token(token, tool, args, estado=huella)
        if ok:
            return None
        _log(tool, "rejected", reason="token")
        if error == ESTADO_CAMBIADO:
            return {"error": "state_changed", "detail": error}
        return {"error": error, "hint": _PISTA_TOKEN}

    async def _enviar(tool: str, ruta: str, carga: dict[str, Any], token: str, *,
                      interfaz: str, changed: list[str], verify_with: str,
                      psk: str | None) -> dict[str, Any] | None:
        """POST con la carga exacta. None si fue bien; si no, la respuesta.

        Un error del Supervisor (no se aplicó) es `error`, con el texto sin
        la PSK; un corte después de enviar (no se sabe) es `outcome:
        "unknown"` con cómo comprobarlo. En los dos casos el token queda
        completado como fallido, y lo que se guarda tampoco lleva la PSK.
        """
        try:
            await ha_client.sv_request("POST", ruta, json_body=carga)
        except (HAConnectionError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
            if _es_respuesta_del_supervisor(exc):
                texto = _limpiar(str(exc), psk)
                await complete_confirmation_token(token, success=False, error=texto)
                _log(tool, "error", interface=interfaz, changed=changed, reason="supervisor")
                return {"error": texto}
            await complete_confirmation_token(
                token, success=False, error="connection lost after sending; outcome unknown")
            _log(tool, "unknown", interface=interfaz, changed=changed,
                 reason="connection_lost")
            return {
                "outcome": "unknown",
                "hint": ("The connection dropped after the change was sent: it "
                         "may or may not have been applied. Do not repeat it; "
                         "read the interface first."),
                "verify_with": verify_with,
            }
        return None

    async def _hecho(tool: str, token: str, result: dict[str, Any], *,
                     interfaz: str, changed: list[str]) -> dict[str, Any]:
        result = redact_structure(result)
        await complete_confirmation_token(token, success=True, result=result)
        _log(tool, "ok", interface=interfaz, changed=changed)
        return result

    # ── Recargar ──────────────────────────────────────────────────────────

    @mcp.tool()
    async def sv_reload_network() -> object:
        """Re-read the host network state from NetworkManager and re-check
        internet connectivity. Changes nothing (no configuration is written),
        so it needs no confirmation. Answers with host_internet and
        supervisor_internet read again afterwards. To read the interfaces,
        use sv_read_api("/network/info").
        """
        tool = "sv_reload_network"
        try:
            await ha_client.sv_request("POST", "/network/reload")
        except HAConnectionError as exc:
            _log(tool, "error", reason="supervisor")
            return {"error": redact_secrets(str(exc))}
        result: dict[str, Any] = {"result": "ok", "host_internet": None,
                                  "supervisor_internet": None}
        try:
            datos = await ha_client.sv_request("GET", "/network/info")
        except HAConnectionError:
            datos = None
        if isinstance(datos, dict):
            for clave in ("host_internet", "supervisor_internet"):
                if isinstance(datos.get(clave), bool):
                    result[clave] = datos[clave]
        if result["host_internet"] is None:
            result["verify_with"] = 'sv_read_api("/network/info")'
        _log(tool, "ok")
        return result

    # ── Editar una interfaz ───────────────────────────────────────────────

    @mcp.tool()
    async def sv_update_network_interface(
        interface: str,
        ipv4: dict | None = None,
        ipv6: dict | None = None,
        wifi: dict | None = None,
        enabled: bool | None = None,
        mdns: str | None = None,
        llmnr: str | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Change the configuration of a SECONDARY host network interface
        (for example a backup Wi-Fi or a second card). The primary interface
        (the default route), the card that carries it when the primary is a
        VLAN, the only connected one, or any interface when the primary or
        what it depends on cannot be determined are ALWAYS refused, even for
        a harmless change: change those from the Home Assistant UI with
        local access. 'default' is refused too (it means the primary).

        Each block you pass REPLACES the whole block (nothing is merged):
        ipv4/ipv6 need method ('auto', 'static' or 'disabled'); 'static'
        needs address (like ['192.0.2.20/24']) and may have gateway;
        nameservers (not with 'disabled') and route_metric are optional;
        ipv6 with 'auto' also accepts addr_gen_mode and ip6_privacy. wifi
        (wireless interfaces only) needs mode ('infrastructure', 'mesh',
        'adhoc', 'ap'), auth ('open' or 'wpa-psk'; WEP is refused because the
        Supervisor stores it where the network never connects) and ssid; psk
        is required for 'wpa-psk' and is never returned or logged. Settings
        the Supervisor would ignore are refused. mdns/llmnr are 'default',
        'off', 'resolve' or 'announce'. enabled false DELETES the saved
        connection (IP settings, Wi-Fi network and psk), so it must be sent
        alone, and enabling it again needs the full configuration. Read the
        current values with sv_read_api("/network/interface/<interface>/info").

        Two steps: the preview shows the interface before, what will be sent
        (psk as "set"), its role and a warning, and returns a
        confirmation_token; repeat the call with it to apply. The Supervisor
        applies it at once and does NOT roll it back. If the interface or its
        role change in between, nothing is done (state_changed).
        """
        tool = "sv_update_network_interface"
        psk = wifi.get("psk") if isinstance(wifi, dict) and isinstance(
            wifi.get("psk"), str) else None
        try:
            interface = _validar_interfaz(interface)
            carga = _validar_bloques(ipv4=ipv4, ipv6=ipv6, wifi=wifi, enabled=enabled,
                                     mdns=mdns, llmnr=llmnr)
            if not carga:
                raise ArgumentoInvalido(
                    "interface", "Pass at least one of ipv4, ipv6, wifi, enabled, "
                                 "mdns or llmnr: there is nothing to change.")
        except ArgumentoInvalido as exc:
            _log(tool, "invalid_argument", field=exc.campo)
            return exc.respuesta()
        # El token ata todo lo que se envía, ya normalizado (la PSK incluida:
        # en disco solo queda el HMAC).
        args = {"interface": interface, **carga}
        changed = list(carga)
        try:
            red = await _leer_red(para_guarda=True, psk=psk)
            _guarda(interface, red)
            if "wifi" in carga and red.interfaces[interface]["type"] != "wireless":
                # `generate.py` solo usa el bloque `wifi` con WIRELESS: en una
                # ethernet o una VLAN el Supervisor lo aceptaría y lo tiraría,
                # y la vista previa lo enseñaría como aplicado (T034).
                raise _Rechazo({
                    "error": "wifi_not_wireless",
                    "detail": (f"{interface} is not a wireless interface; the "
                               "Supervisor ignores a wifi block on it. Remove "
                               "wifi or name a wireless interface."),
                }, "wifi_not_wireless")
            antes = await _interfaz(interface, psk)
        except _Rechazo as r:
            _log(tool, "rejected", interface=interface, reason=r.motivo)
            return r.respuesta
        huella = {"interface": _sin_fluctuantes(antes), "primary": red.principal,
                  "connected": red.conectadas}
        if not confirmation_token:
            preview: dict[str, Any] = {
                "action": "update_network_interface",
                "interface": interface,
                "role": {"primary": False, "connected": bool(antes.get("connected")),
                         "other_connected": [n for n in red.conectadas if n != interface]},
                "before": redact_structure(_publica(antes)),
                "after": _carga_publica(carga),
                "replaces_blocks": [b for b in ("ipv4", "ipv6", "wifi") if b in carga],
                "warning": _AVISO_FUERTE,
            }
            if any(isinstance(carga.get(b), dict) and carga[b].get("gateway")
                   for b in ("ipv4", "ipv6")):
                preview["route_warning"] = _AVISO_RUTA
            if carga.get("enabled") is False:
                # La v1 borra el perfil (`destructive_disable`), no lo apaga:
                # hay que decirlo, no basta el aviso genérico (T030).
                preview["deletes_saved_connection"] = True
                preview["disable_warning"] = _AVISO_DESACTIVAR
            # Sin `redact_structure` sobre la respuesta entera: taparía el
            # propio `confirmation_token` y el `"psk": "set"` que dice que la
            # clave va. La PSK ya no está en la vista previa.
            _log(tool, "preview", interface=interface, changed=changed)
            return await create_confirmation_token(tool, args, preview=preview, estado=huella)
        if (fallo := await _confirmar(tool, confirmation_token, args, huella)):
            return fallo
        if (fallo := await _enviar(
                tool, f"/network/interface/{interface}/update", carga, confirmation_token,
                interfaz=interface, changed=changed,
                verify_with=f'sv_read_api("/network/interface/{interface}/info")',
                psk=psk)):
            return fallo
        result: dict[str, Any] = {"result": "ok"}
        try:
            result["interface"] = _publica(await _interfaz(interface, psk))
        except _Rechazo:
            result["interface"] = None
            result["verify_with"] = f'sv_read_api("/network/interface/{interface}/info")'
        return await _hecho(tool, confirmation_token, result, interfaz=interface,
                            changed=changed)

    # ── Crear una VLAN ────────────────────────────────────────────────────

    @mcp.tool()
    async def sv_create_vlan(
        interface: str,
        vlan_id: int,
        ipv4: dict | None = None,
        ipv6: dict | None = None,
        mdns: str | None = None,
        llmnr: str | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Create the VLAN interface <interface>.<vlan_id> on an ethernet
        card (vlan_id 1-4094). It does not change the parent card, so it is
        allowed on the primary one; but a gateway on the VLAN (static, or
        from DHCP with the default 'auto') may take the default route and cut
        access: the preview warns. ipv4/ipv6 follow the same rules as in
        sv_update_network_interface (each needs method; omitted, the
        Supervisor uses 'auto'); mdns/llmnr are 'default', 'off', 'resolve'
        or 'announce'. A VLAN that already exists (vlan_exists), a parent
        that is not ethernet (not_ethernet) or does not exist is refused.
        There is no tool to delete a VLAN.

        Two steps: the preview shows the parent, the new interface and its
        settings and returns a confirmation_token; repeat the call with it to
        create. If the network changes in between, nothing is done.
        """
        tool = "sv_create_vlan"
        try:
            interface = _validar_interfaz(interface)
            vlan_id = _validar_vlan_id(vlan_id)
            carga = _validar_bloques(ipv4=ipv4, ipv6=ipv6, mdns=mdns, llmnr=llmnr)
        except ArgumentoInvalido as exc:
            _log(tool, "invalid_argument", field=exc.campo)
            return exc.respuesta()
        nueva = f"{interface}.{vlan_id}"
        args = {"interface": interface, "vlan_id": vlan_id, **carga}
        changed = list(carga)
        try:
            red = await _leer_red(para_guarda=False)
            madre = red.interfaces.get(interface)
            if madre is None:
                raise _Rechazo({"error": "interface_not_found",
                                "detail": f"The Supervisor has no interface {interface}."},
                               "interface_not_found")
            if madre["type"] != "ethernet":
                raise _Rechazo({"error": "not_ethernet",
                                "detail": (f"{interface} is not an ethernet card; "
                                           "the Supervisor only creates VLANs on "
                                           "ethernet.")}, "not_ethernet")
            existe = nueva in red.interfaces or any(
                isinstance(i.get("vlan"), dict) and i["vlan"].get("id") == vlan_id
                and i["vlan"].get("parent") == interface for i in red.interfaces.values())
            if existe:
                raise _Rechazo({"error": "vlan_exists",
                                "detail": f"VLAN {vlan_id} on {interface} already exists."},
                               "vlan_exists")
        except _Rechazo as r:
            _log(tool, "rejected", interface=interface, reason=r.motivo)
            return r.respuesta
        huella = {"parent": _sin_fluctuantes(madre), "existing": sorted(red.interfaces),
                  "primary": red.principal, "connected": red.conectadas}
        if not confirmation_token:
            preview: dict[str, Any] = {
                "action": "create_vlan",
                "parent": interface,
                "parent_is_primary": interface == red.principal,
                "new_interface": nueva,
                "vlan_id": vlan_id,
                "config": carga or {"ipv4": {"method": "auto"}, "ipv6": {"method": "auto"},
                                    "note": "Supervisor defaults"},
                "warning": ("The Supervisor creates the VLAN connection at once "
                            "and there is no tool to delete it; remove it from "
                            "the Home Assistant UI if needed."),
                "route_warning": _AVISO_RUTA_VLAN,
            }
            _log(tool, "preview", interface=interface, changed=changed)
            return await create_confirmation_token(tool, args, preview=preview, estado=huella)
        if (fallo := await _confirmar(tool, confirmation_token, args, huella)):
            return fallo
        verify = f'sv_read_api("/network/interface/{nueva}/info")'
        if (fallo := await _enviar(
                tool, f"/network/interface/{interface}/vlan/{vlan_id}", carga,
                confirmation_token, interfaz=interface, changed=changed,
                verify_with=verify, psk=None)):
            return fallo
        result: dict[str, Any] = {"result": "ok"}
        try:
            result["interface"] = _publica(await _interfaz(nueva))
        except _Rechazo:
            result["interface"] = None
            result["verify_with"] = verify
        return await _hecho(tool, confirmation_token, result, interfaz=interface,
                            changed=changed)
