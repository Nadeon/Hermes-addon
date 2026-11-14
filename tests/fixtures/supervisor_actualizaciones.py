"""Supervisor (y Core) simulados para la spec 015 (actualizaciones del sistema).

Reproducen la FORMA de las respuestas del Supervisor 2026.11.0, leída en su
código (research R-12): `api/root.py` (`/available_updates`,
`/refresh_updates`), `api/homeassistant.py` (`/core/info`, `/core/check`,
`/core/update`), `api/supervisor.py` (`/supervisor/info` con `addons[]`),
`api/os.py` (`/os/info` con `version_pending`), `api/host.py` (`disk_free` en
GB), `api/resolution.py` y los `/{plugin}/info`. `sv_request` ya devuelve el
campo `data`, así que aquí va solo eso.

Datos ficticios: versiones inventadas, slugs `a0b1c2d3_ejemplo` y
`a1b2c3d4_hermes`, URLs de `example.invalid` y centinelas de texto. Nada sale
de una instalación real (principio VIII). Nunca hay una actualización real:
las rutas de actualización solo se apuntan.

Además de lo que apunta el simulado de la 013 (método, ruta, `params`,
espera), este apunta el CUERPO de cada petición, que es lo que el token ata
(`version`, `backup`, `background`). Una respuesta puede ser:

- un valor (se devuelve una copia);
- una excepción (se lanza: un 404, un error del Supervisor o
  `TimeoutError` para simular lentitud o un corte);
- una función sin argumentos (se llama en cada petición: sirve para que la
  versión cambie entre la vista previa y la confirmación).

Core simulado (para la `release_url` de la entidad `update` de la plataforma
`hassio`): `get_states` y `ws_send` con `config/entity_registry/get_entries`.
Con `core_caido = True`, las dos fallan como si Core no respondiera.
"""

from __future__ import annotations

import copy
from typing import Any

from hermes.ha import HAConnectionError
from tests.fixtures.supervisor_diagnostico import (
    CENTINELA_JWT,
    CENTINELA_PASSWORD,
    SupervisorSimulado,
)

__all__ = [
    "CENTINELA_JWT", "CENTINELA_PASSWORD", "CORE_ACTUAL", "CORE_ULTIMA",
    "SLUG_APP", "SLUG_HERMES", "SupervisorActualizaciones", "URL_NOTAS_CORE",
    "ENTIDAD_CORE", "error_404", "sistema_sano",
]

CORE_ACTUAL = "2026.11.1"
CORE_ULTIMA = "2026.12.0"
SUPERVISOR_ACTUAL = "2026.11.0"
OS_ACTUAL = "16.2"
OS_ULTIMA = "16.3"
SLUG_APP = "a0b1c2d3_ejemplo"
# El Supervisor pone al slug de Hermes el prefijo del repositorio; `_es_hermes`
# lo reconoce por el sufijo `_hermes`.
SLUG_HERMES = "a1b2c3d4_hermes"
URL_NOTAS_CORE = "https://example.invalid/notas-de-core"
# Un `entity_id` renombrado a propósito: la entidad se reconoce por el
# registro (plataforma y `unique_id`), nunca por el nombre (research R-10).
ENTIDAD_CORE = "update.nombre_cambiado_por_el_usuario"

PLUGINS = ("dns", "audio", "cli", "observer", "multicast")


def error_404(metodo: str, ruta: str) -> HAConnectionError:
    return HAConnectionError(
        f"Supervisor {metodo} {ruta} failed 404: not found", status=404)


class SupervisorActualizaciones(SupervisorSimulado):
    """Supervisor simulado que apunta también el cuerpo de cada petición, y
    Core simulado mínimo para las entidades `update`."""

    def __init__(self) -> None:
        super().__init__()
        self.estados: list[dict[str, Any]] = []
        self.registro: dict[str, dict[str, Any]] = {}
        self.core_caido = False
        self.ws_llamadas: list[dict[str, Any]] = []

    async def wait_ready(self, timeout: float = 5.0) -> bool:
        return not self.core_caido

    async def sv_request(
        self,
        method: str,
        sv_path: str,
        json_body: Any = None,
        params: Any = None,
        timeout_seconds: float = 60.0,
    ) -> Any:
        self.llamadas.append({
            "metodo": method.upper(), "ruta": sv_path,
            "params": copy.deepcopy(params), "timeout": timeout_seconds,
            "cuerpo": copy.deepcopy(json_body), "texto": False,
        })
        valor = self.json.get((method.upper(), sv_path))
        if callable(valor) and not isinstance(valor, Exception):
            valor = valor()
        if valor is None:
            raise error_404(method.upper(), sv_path)
        if isinstance(valor, BaseException):
            raise valor
        return copy.deepcopy(valor)

    # ── Core ────────────────────────────────────────────────────────────────

    async def get_states(self) -> list[dict[str, Any]]:
        self.ws_llamadas.append({"type": "get_states"})
        if self.core_caido:
            raise HAConnectionError("Home Assistant no responde")
        return copy.deepcopy(self.estados)

    async def ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.ws_llamadas.append(copy.deepcopy(payload))
        if self.core_caido:
            raise HAConnectionError("Home Assistant no responde")
        if payload.get("type") == "config/entity_registry/get_entries":
            return {e: copy.deepcopy(self.registro.get(e)) for e in payload["entity_ids"]}
        raise HAConnectionError(f"comando no simulado: {payload.get('type')}")

    # ── Atajos para los tests ───────────────────────────────────────────────

    def rutas(self, metodo: str | None = None) -> list[tuple[str, str]]:
        return [(c["metodo"], c["ruta"]) for c in self.llamadas
                if metodo is None or c["metodo"] == metodo]

    def posts(self) -> list[tuple[str, str]]:
        return self.rutas("POST")


def _plugin(nombre: str, *, desactualizado: bool = False) -> dict[str, Any]:
    return {
        "version": "2026.10.0",
        "version_latest": "2026.11.0" if desactualizado else "2026.10.0",
        "update_available": desactualizado,
        "image": f"ghcr.io/ejemplo/{nombre}",
    }


def sistema_sano(sv: SupervisorActualizaciones) -> SupervisorActualizaciones:
    """Un sistema con Home Assistant OS, sano, con 50 GB libres, Core con
    actualización y nada más pendiente, y Core respondiendo."""
    sv.respuesta("GET", "/core/info", {
        "version": CORE_ACTUAL, "version_latest": CORE_ULTIMA,
        "update_available": True, "machine": "maquina-ficticia",
        "ip_address": "192.0.2.20", "arch": "amd64", "image": "ghcr.io/ejemplo/core",
        "boot": True, "port": 8123, "ssl": False, "watchdog": True,
        "audio_input": None, "audio_output": None,
        "backups_exclude_database": False, "duplicate_log_file": False,
    })
    sv.respuesta("GET", "/supervisor/info", {
        "version": SUPERVISOR_ACTUAL, "version_latest": SUPERVISOR_ACTUAL,
        "update_available": False, "channel": "stable", "arch": "amd64",
        "supported": True, "healthy": True, "auto_update": True,
        "addons": [
            {"name": "Ejemplo", "slug": SLUG_APP, "version": "1.0.0",
             "version_latest": "1.0.0", "update_available": False,
             "state": "started", "repository": "a0b1c2d3", "icon": False},
        ],
    })
    sv.respuesta("GET", "/os/info", {
        "version": OS_ACTUAL, "version_latest": OS_ACTUAL, "version_pending": None,
        "update_available": False, "board": "ova", "boot": "A",
        "data_disk": "disco-ficticio", "boot_slots": {},
    })
    sv.respuesta("GET", "/host/info", {
        "hostname": "anfitrion-ficticio", "disk_free": 50.0, "disk_total": 100.0,
        "disk_used": 50.0, "operating_system": "Home Assistant OS 16.2",
    })
    sv.respuesta("GET", "/resolution/info", {
        "unsupported": [], "unhealthy": [], "suggestions": [], "issues": [],
        "checks": [],
    })
    for p in PLUGINS:
        sv.respuesta("GET", f"/{p}/info", _plugin(p))
    sv.respuesta("GET", "/available_updates", {"available_updates": [
        {"update_type": "core", "panel_path": "/update-available/core",
         "version_latest": CORE_ULTIMA},
    ]})
    sv.respuesta("POST", "/core/check", {})
    sv.respuesta("POST", "/refresh_updates", {})
    sv.respuesta("POST", "/core/update", {"job_id": "0a1b2c3d4e5f40718293a4b5c6d7e8f9"})
    # Core: la entidad `update` de Core, con un `entity_id` renombrado, y otra
    # de una integración cualquiera que no debe confundirse con ella.
    sv.estados = [
        {"entity_id": ENTIDAD_CORE, "state": "on", "attributes": {
            "installed_version": CORE_ACTUAL, "latest_version": CORE_ULTIMA,
            "release_url": URL_NOTAS_CORE, "title": "Home Assistant Core"}},
        {"entity_id": "update.firmware_ficticio", "state": "on", "attributes": {
            "installed_version": "1.0", "latest_version": "1.1",
            "release_url": "https://example.invalid/otra"}},
        {"entity_id": "light.salon", "state": "on", "attributes": {}},
    ]
    sv.registro = {
        ENTIDAD_CORE: {"entity_id": ENTIDAD_CORE, "platform": "hassio",
                       "unique_id": "home_assistant_core_version_latest"},
        "update.firmware_ficticio": {"entity_id": "update.firmware_ficticio",
                                     "platform": "ficticia",
                                     "unique_id": "home_assistant_core_version_latest"},
    }
    return sv


def con_plugin_desactualizado(sv: SupervisorActualizaciones, nombre: str = "dns") -> None:
    sv.respuesta("GET", f"/{nombre}/info", _plugin(nombre, desactualizado=True))


def con_actualizaciones_de_todo(sv: SupervisorActualizaciones) -> None:
    """Core, una app, Hermes y un plugin desactualizados (T004)."""
    info = copy.deepcopy(sv.json[("GET", "/supervisor/info")])
    info["addons"] = [
        {"name": "Ejemplo", "slug": SLUG_APP, "version": "1.0.0",
         "version_latest": "1.1.0", "update_available": True, "state": "started",
         "repository": "a0b1c2d3", "icon": False},
        {"name": "Hermes", "slug": SLUG_HERMES, "version": "1.2.0",
         "version_latest": "1.2.1", "update_available": True, "state": "started",
         "repository": "a1b2c3d4", "icon": True},
    ]
    sv.respuesta("GET", "/supervisor/info", info)
    sv.respuesta("GET", "/available_updates", {"available_updates": [
        {"update_type": "core", "panel_path": "/update-available/core",
         "version_latest": CORE_ULTIMA},
        {"update_type": "addon", "name": "Ejemplo", "icon": None,
         "panel_path": f"/update-available/{SLUG_APP}", "version_latest": "1.1.0"},
        {"update_type": "addon", "name": "Hermes", "icon": f"/addons/{SLUG_HERMES}/icon",
         "panel_path": f"/update-available/{SLUG_HERMES}", "version_latest": "1.2.1"},
    ]})
    con_plugin_desactualizado(sv, "dns")
