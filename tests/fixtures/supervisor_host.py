"""Supervisor simulado para el host, el OS y la red de la spec 032 (CAP-086 y CAP-090).

Reproduce la FORMA de las respuestas y el comportamiento del Supervisor
2026.11.0 leídos en su código (`supervisor/api/host.py`, `api/os.py`,
`os/manager.py`), con datos genéricos: `homeassistant`, `casa-ha`, versiones
de OS inventadas. Nada sale de una instalación real (principio VIII).

Lo que importa del Supervisor real y se replica aquí:

- `GET /host/info` → `{hostname, disk_free, disk_total, disk_used, …}` con el
  disco en GiB (`get_disk_free_space` redondea a una décima).
- `POST /host/options` `{"hostname"}` cambia el hostname estático.
- `GET /os/config/swap` → `{swap_size, swappiness}`; 404 sin HAOS ≥ 15.
  `POST /os/config/swap` admite solo las dos claves.
- `GET /os/info` → `{version, boot, boot_slots: {A: {state, status,
  version}, B: …}, …}`; 404 sin HAOS. `POST /os/boot-slot` marca la ranura y
  reinicia en el acto.
- `POST /host/shutdown` comprueba la migración de la base de datos de Core
  (salvo `force`) y apaga.

`sv_request` devuelve el campo `data`, como el cliente real; un error del
Supervisor llega como `HAConnectionError` con `status`, y un corte de la
conexión, sin él.
"""

from __future__ import annotations

import copy
from typing import Any

from hermes.ha import HAConnectionError

# Marcadores genéricos que Hermes nunca debe escribir en su log (FR-012).
HOSTNAME_ACTUAL = "homeassistant"
HOSTNAME_NUEVO = "casa-ha"
SWAP_ACTUAL = "1G"
VERSION_A = "17.0"
VERSION_B = "17.1"


def host_info() -> dict[str, Any]:
    return {"hostname": HOSTNAME_ACTUAL, "disk_free": 20.5, "disk_total": 31.2,
            "disk_used": 10.7, "chassis": "embedded", "kernel": "6.12.0-haos",
            "operating_system": f"Home Assistant OS {VERSION_A}"}


def swap() -> dict[str, Any]:
    return {"swap_size": SWAP_ACTUAL, "swappiness": 1}


def os_info() -> dict[str, Any]:
    return {
        "version": VERSION_A, "version_latest": VERSION_B,
        "update_available": True, "board": "ova", "boot": "A",
        "data_disk": "generic-disk",
        "boot_slots": {
            "A": {"state": "booted", "status": "good", "version": VERSION_A},
            "B": {"state": "inactive", "status": "bad", "version": VERSION_B},
        },
    }


def error_404(ruta: str) -> HAConnectionError:
    return HAConnectionError(
        f"Supervisor REST GET http://supervisor{ruta} failed 404: "
        '{"result": "error", "message": "Home Assistant OS 15.0 or newer '
        'required for swap settings"}', status=404)


def error_migracion() -> HAConnectionError:
    """El de `_check_ha_offline_migration` cuando Core migra la base."""
    return HAConnectionError(
        "Supervisor REST POST http://supervisor/host/shutdown failed 503: "
        '{"result": "error", "message": "Home Assistant offline database '
        'migration in progress, please wait until complete before shutting '
        'down host"}', status=503)


def error_hostname_invalido() -> HAConnectionError:
    return HAConnectionError(
        "Supervisor REST POST http://supervisor/host/options failed 400: "
        '{"result": "error", "message": "Invalid hostname"}', status=400)


def corte() -> HAConnectionError:
    """La conexión cae después de enviar: el Supervisor no contestó."""
    return HAConnectionError("Server disconnected")


class SupervisorDeHost:
    """Supervisor simulado del host y del OS.

    - `host`, `swap`, `os`: estado actual (`None` en `swap` u `os` → 404).
    - `errores[(método, ruta)]`: excepción que lanza esa petición (la
      llamada queda registrada antes: para un POST, «enviado»).
    - `formas[(método, ruta)]`: respuesta cruda que sustituye a la normal.
    - `llamadas`: método, ruta y `json_body` de cada petición.
    """

    def __init__(self) -> None:
        self.host: dict[str, Any] = host_info()
        self.swap: dict[str, Any] | None = swap()
        self.os: dict[str, Any] | None = os_info()
        self.errores: dict[tuple[str, str], Exception] = {}
        self.formas: dict[tuple[str, str], Any] = {}
        self.llamadas: list[dict[str, Any]] = []

    @property
    def escrituras(self) -> list[dict[str, Any]]:
        return [c for c in self.llamadas if c["metodo"] != "GET"]

    async def sv_request(
        self,
        method: str,
        sv_path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        timeout_seconds: float = 60.0,
    ) -> Any:
        clave = (method, sv_path)
        self.llamadas.append({"metodo": method, "ruta": sv_path,
                              "json_body": copy.deepcopy(json_body)})
        if clave in self.errores:
            raise self.errores[clave]
        if clave in self.formas:
            return copy.deepcopy(self.formas[clave])
        if clave == ("GET", "/host/info"):
            return copy.deepcopy(self.host)
        if clave == ("GET", "/os/config/swap"):
            if self.swap is None:
                raise error_404(sv_path)
            return copy.deepcopy(self.swap)
        if clave == ("GET", "/os/info"):
            if self.os is None:
                raise error_404(sv_path)
            return copy.deepcopy(self.os)
        if clave == ("POST", "/host/options"):
            self.host["hostname"] = (json_body or {})["hostname"]
            return {}
        if clave == ("POST", "/os/config/swap"):
            if self.swap is None:
                raise error_404(sv_path)
            self.swap.update(json_body or {})
            return {}
        if clave in (("POST", "/os/boot-slot"), ("POST", "/host/shutdown")):
            return {}
        raise HAConnectionError(
            f"Supervisor REST {method} http://supervisor{sv_path} failed 404: "
            "not found", status=404)


# ── Red del host (spec 032, tramo 2; CAP-090) ────────────────────────────────
#
# Forma v1 de `supervisor/api/network.py` (`interface_struct_v1`, `info_v1`):
# cada interfaz con `interface`, `type`, `enabled`, `connected`, `primary`,
# `mac`, `ipv4`, `ipv6`, `wifi` (sin PSK: el Supervisor nunca la devuelve),
# `vlan`, `mdns` y `llmnr`. `default` es un alias de la principal
# (`_get_interface`). `interface_update` REEMPLAZA cada bloque que recibe;
# `create_vlan` exige una madre `ethernet` y crea `<madre>.<id>`.

# PSK centinela: no puede aparecer en ninguna salida, log ni fichero (FR-010).
PSK = "PSK-CENTINELA-032"
SSID = "mi-red"
MAC = "aa:bb:cc:dd:ee:ff"
IP_ETH0 = "192.0.2.10/24"
IP_WLAN0 = "192.0.2.20/24"
GATEWAY = "192.0.2.1"


def _ipv4(direccion: str | None, *, ready: bool = True) -> dict[str, Any]:
    return {"method": "auto", "address": [direccion] if direccion else [],
            "nameservers": [GATEWAY] if direccion else [],
            "gateway": GATEWAY if direccion else None, "route_metric": None,
            "ready": ready}


def _ipv6() -> dict[str, Any]:
    return {"method": "auto", "addr_gen_mode": "default", "ip6_privacy": "default",
            "address": [], "nameservers": [], "gateway": None, "route_metric": None,
            "ready": False}


def interfaz_eth0() -> dict[str, Any]:
    return {"interface": "eth0", "type": "ethernet", "enabled": True,
            "connected": True, "primary": True, "mac": "aa:bb:cc:dd:ee:01",
            "ipv4": _ipv4(IP_ETH0), "ipv6": _ipv6(), "wifi": None, "vlan": None,
            "mdns": "default", "llmnr": "default"}


def interfaz_wlan0() -> dict[str, Any]:
    return {"interface": "wlan0", "type": "wireless", "enabled": True,
            "connected": False, "primary": False, "mac": MAC,
            "ipv4": _ipv4(IP_WLAN0, ready=False), "ipv6": _ipv6(),
            "wifi": {"mode": "infrastructure", "auth": "wpa-psk", "ssid": SSID,
                     "signal": 60},
            "vlan": None, "mdns": "default", "llmnr": "default"}


def interfaz_vlan10() -> dict[str, Any]:
    return {"interface": "eth0.10", "type": "vlan", "enabled": True,
            "connected": True, "primary": False, "mac": "aa:bb:cc:dd:ee:01",
            "ipv4": _ipv4("192.0.2.130/25"), "ipv6": _ipv6(), "wifi": None,
            "vlan": {"id": 10, "parent": "eth0"}, "mdns": "default",
            "llmnr": "default"}


def red() -> list[dict[str, Any]]:
    return [interfaz_eth0(), interfaz_wlan0(), interfaz_vlan10()]


def red_sin_principal() -> list[dict[str, Any]]:
    interfaces = red()
    for i in interfaces:
        i["primary"] = False
    return interfaces


def red_wlan0_unica_conectada() -> list[dict[str, Any]]:
    """Transitorio de NetworkManager: la principal sigue marcada en `eth0`,
    pero la única conectada es `wlan0`, que no es la principal."""
    interfaces = [interfaz_eth0(), interfaz_wlan0()]
    interfaces[0]["connected"] = False
    interfaces[1]["connected"] = True
    return interfaces


def error_que_repite_la_psk() -> HAConnectionError:
    """Un error del Supervisor que copia la PSK que recibió (FR-010): Hermes
    tiene que taparla antes de devolverlo, registrarlo o guardarlo."""
    return HAConnectionError(
        "Supervisor REST POST http://supervisor/network/interface/wlan0/update "
        'failed 400: {"result": "error", "message": "Cannot apply config to '
        f'wlan0: key {PSK} rejected by NetworkManager"}}', status=400)


class SupervisorDeRed(SupervisorDeHost):
    """Supervisor simulado con la red del host además del host y el OS.

    - `interfaces`: lista de interfaces (forma v1); `None` → `/network/info`
      falla con un 500.
    - `host_internet` / `supervisor_internet`: conectividad.
    """

    def __init__(self, interfaces: list[dict[str, Any]] | None = None) -> None:
        super().__init__()
        self.interfaces: list[dict[str, Any]] | None = (
            red() if interfaces is None else interfaces)
        self.host_internet = True
        self.supervisor_internet = True

    def _buscar(self, nombre: str) -> dict[str, Any] | None:
        for i in self.interfaces or []:
            if nombre == "default" and i["primary"]:
                return i
            if i["interface"] == nombre:
                return i
        return None

    def interfaz(self, nombre: str) -> dict[str, Any]:
        i = self._buscar(nombre)
        assert i is not None, nombre
        return i

    @staticmethod
    def _no_existe(metodo: str, ruta: str, nombre: str) -> HAConnectionError:
        return HAConnectionError(
            f"Supervisor REST {metodo} http://supervisor{ruta} failed 404: "
            f'{{"result": "error", "message": "Interface {nombre} does not exist"}}',
            status=404)

    def _actualizar(self, i: dict[str, Any], cuerpo: dict[str, Any]) -> None:
        for bloque, valor in cuerpo.items():
            if bloque == "wifi":
                # El Supervisor guarda la PSK en NetworkManager y nunca la
                # devuelve.
                i["wifi"] = {k: v for k, v in valor.items() if k != "psk"}
                i["wifi"]["signal"] = None
            elif bloque in ("ipv4", "ipv6"):
                nuevo: dict[str, Any] = {"address": [], "nameservers": [],
                                         "gateway": None, "route_metric": None,
                                         "ready": False}
                nuevo.update(valor)
                i[bloque] = nuevo
            else:
                i[bloque] = valor

    async def sv_request(
        self,
        method: str,
        sv_path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        timeout_seconds: float = 60.0,
    ) -> Any:
        if not sv_path.startswith("/network/"):
            return await super().sv_request(method, sv_path, json_body, params,
                                            timeout_seconds)
        clave = (method, sv_path)
        self.llamadas.append({"metodo": method, "ruta": sv_path,
                              "json_body": copy.deepcopy(json_body)})
        if clave in self.errores:
            raise self.errores[clave]
        if clave in self.formas:
            return copy.deepcopy(self.formas[clave])
        partes = sv_path.strip("/").split("/")
        if clave == ("GET", "/network/info"):
            if self.interfaces is None:
                raise HAConnectionError(
                    "Supervisor REST GET http://supervisor/network/info failed 500: "
                    "NetworkManager not available", status=500)
            return {"interfaces": copy.deepcopy(self.interfaces),
                    "docker": {"interface": "hassio", "address": "172.30.32.0/23",
                               "gateway": "172.30.32.1", "dns": "172.30.32.3"},
                    "host_internet": self.host_internet,
                    "supervisor_internet": self.supervisor_internet}
        if clave == ("POST", "/network/reload"):
            return {}
        if len(partes) == 4 and partes[1] == "interface":
            i = self._buscar(partes[2])
            if (method, partes[3]) == ("GET", "info"):
                if i is None:
                    raise self._no_existe(method, sv_path, partes[2])
                return copy.deepcopy(i)
            if (method, partes[3]) == ("POST", "update"):
                if i is None:
                    raise self._no_existe(method, sv_path, partes[2])
                self._actualizar(i, json_body or {})
                return {}
        if len(partes) == 5 and partes[1] == "interface" and partes[3] == "vlan" \
                and method == "POST":
            madre = self._buscar(partes[2])
            if madre is None:
                raise self._no_existe(method, sv_path, partes[2])
            cuerpo = json_body or {}
            nueva: dict[str, Any] = {
                "interface": f"{madre['interface']}.{partes[4]}", "type": "vlan",
                "enabled": True, "connected": False, "primary": False,
                "mac": madre["mac"], "ipv4": None, "ipv6": None, "wifi": None,
                "vlan": {"id": int(partes[4]), "parent": madre["interface"]},
                "mdns": "default", "llmnr": "default"}
            self._actualizar(nueva, {"ipv4": {"method": "auto"},
                                     "ipv6": {"method": "auto"}, **cuerpo})
            assert self.interfaces is not None
            self.interfaces.append(nueva)
            return {}
        raise HAConnectionError(
            f"Supervisor REST {method} http://supervisor{sv_path} failed 404: "
            "not found", status=404)
