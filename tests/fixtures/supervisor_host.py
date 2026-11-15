"""Supervisor simulado para el host y el OS de la spec 032 (tramo 1, CAP-086).

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
