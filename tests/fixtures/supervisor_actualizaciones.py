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
  versión cambie entre la vista previa y la confirmación);
- una función `async` sin argumentos (se espera: sirve para que la petición
  de fondo de OS y Supervisor quede «en curso» hasta que el test la suelte, o
  para que lance un corte de conexión).

Core simulado (para la `release_url` de la entidad `update` de la plataforma
`hassio`): `get_states` y `ws_send` con `config/entity_registry/get_entries` y
`update/release_notes` (texto de `notas` por `entity_id`). Con
`core_caido = True`, fallan como si Core no respondiera.
"""

from __future__ import annotations

import copy
import inspect
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
    "OS_ACTUAL", "OS_ULTIMA", "SUPERVISOR_ACTUAL", "SUPERVISOR_ULTIMA",
    "URL_NOTAS_OS", "URL_NOTAS_SUPERVISOR", "AVISO_REINICIO_OS",
    "con_os_y_supervisor_desactualizados", "sin_supervisor_pendiente", "job",
]

CORE_ACTUAL = "2026.11.1"
CORE_ULTIMA = "2026.12.0"
SUPERVISOR_ACTUAL = "2026.11.0"
SUPERVISOR_ULTIMA = "2026.11.1"
OS_ACTUAL = "16.2"
OS_ULTIMA = "16.3"
URL_NOTAS_OS = "https://example.invalid/notas-del-os"
URL_NOTAS_SUPERVISOR = "https://example.invalid/notas-del-supervisor"
ENTIDAD_OS = "update.sistema_operativo_renombrado"
ENTIDAD_SUPERVISOR = "update.supervisor_renombrado"
AVISO_REINICIO_OS = (
    "<ha-alert alert-type='info'>A reboot is required after install for the "
    "update to take effect.</ha-alert>\n"
)
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
        self.notas: dict[str, str] = {}
        self.core_caido = False
        self.ws_llamadas: list[dict[str, Any]] = []
        # Tramo 3: `update.install` por `call_service`. Cada llamada se apunta
        # (dominio, servicio, datos, allow_dangerous); la respuesta puede ser
        # un valor, una excepción o una función sin argumentos.
        self.servicios: list[dict[str, Any]] = []
        self.respuesta_servicio: Any = []

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
        if inspect.iscoroutinefunction(valor):
            valor = await valor()
        elif callable(valor) and not isinstance(valor, Exception):
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
        if payload.get("type") == "update/release_notes":
            notas = self.notas.get(payload["entity_id"])
            if isinstance(notas, BaseException):
                raise notas
            return notas
        raise HAConnectionError(f"comando no simulado: {payload.get('type')}")

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        self.ws_llamadas.append({"type": "get_state", "entity_id": entity_id})
        if self.core_caido:
            raise HAConnectionError("Home Assistant no responde")
        for e in self.estados:
            if e.get("entity_id") == entity_id:
                return copy.deepcopy(e)
        return None

    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
        *,
        allow_dangerous: bool = False,
    ) -> Any:
        self.servicios.append({
            "dominio": domain, "servicio": service,
            "datos": copy.deepcopy(service_data), "allow_dangerous": allow_dangerous,
        })
        valor = self.respuesta_servicio
        if callable(valor) and not isinstance(valor, BaseException):
            valor = valor()
        if isinstance(valor, BaseException):
            raise valor
        return copy.deepcopy(valor)

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


def con_os_y_supervisor_desactualizados(sv: SupervisorActualizaciones) -> None:
    """OS 16.2 → 16.3 y Supervisor con actualización, y sus entidades `update`
    en Core (tramo 2). El Supervisor desactualizado bloquea el OS (R-6): los
    tests del OS lo quitan con `sin_supervisor_pendiente`."""
    os_info = copy.deepcopy(sv.json[("GET", "/os/info")])
    os_info.update(version_latest=OS_ULTIMA, update_available=True)
    sv.respuesta("GET", "/os/info", os_info)
    sup = copy.deepcopy(sv.json[("GET", "/supervisor/info")])
    sup.update(version_latest=SUPERVISOR_ULTIMA, update_available=True)
    sv.respuesta("GET", "/supervisor/info", sup)
    sv.respuesta("POST", "/os/update", {})
    sv.respuesta("POST", "/supervisor/update", {})
    sv.estados += [
        {"entity_id": ENTIDAD_OS, "state": "on", "attributes": {
            "installed_version": OS_ACTUAL, "latest_version": OS_ULTIMA,
            "release_url": URL_NOTAS_OS, "title": "Home Assistant Operating System"}},
        {"entity_id": ENTIDAD_SUPERVISOR, "state": "on", "attributes": {
            "installed_version": SUPERVISOR_ACTUAL, "latest_version": SUPERVISOR_ULTIMA,
            "release_url": URL_NOTAS_SUPERVISOR, "title": "Home Assistant Supervisor"}},
    ]
    sv.registro[ENTIDAD_OS] = {"entity_id": ENTIDAD_OS, "platform": "hassio",
                               "unique_id": "home_assistant_os_version_latest"}
    sv.registro[ENTIDAD_SUPERVISOR] = {
        "entity_id": ENTIDAD_SUPERVISOR, "platform": "hassio",
        "unique_id": "home_assistant_supervisor_version_latest"}
    # El texto que da Core para el OS (`OS_UPDATE_REBOOT_NOTICE`).
    sv.notas[ENTIDAD_OS] = AVISO_REINICIO_OS


def sin_supervisor_pendiente(sv: SupervisorActualizaciones) -> None:
    sup = copy.deepcopy(sv.json[("GET", "/supervisor/info")])
    sup.update(version_latest=SUPERVISOR_ACTUAL, update_available=False)
    sv.respuesta("GET", "/supervisor/info", sup)


def job(nombre: str, uuid: str, *, done: bool = False,
        hijos: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Un job con la forma de `SupervisorJob.as_dict()` en `/jobs/info`."""
    return {"name": nombre, "reference": None, "uuid": uuid, "progress": 0,
            "stage": None, "done": done, "errors": [], "created": "2026-11-14T10:00:00+00:00",
            "extra": None, "child_jobs": hijos or []}


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


# ── Tramo 3: entidades `update` de Core (CAP-064) ────────────────────────────

ENTIDAD_FIRMWARE = "update.firmware_ficticio"
ENTIDAD_SIN_NOTAS = "update.integracion_sin_notas"
ENTIDAD_AL_DIA = "update.integracion_al_dia"
ENTIDAD_APP = "update.app_renombrada"
ENTIDAD_HERMES = "update.hermes_renombrada"
# Una app cuyo slug TAMBIÉN termina en `_hermes` pero no es este Hermes: el
# criterio de D-1 es el slug exacto de `/addons/self/info`, no el sufijo.
SLUG_OTRO_HERMES = "b9c8d7e6_hermes"
ENTIDAD_OTRO_HERMES = "update.otra_app_hermes"
FIRMWARE_ACTUAL = "1.0"
FIRMWARE_ULTIMA = "1.1"
CENTINELA_NOTAS = "texto-centinela-de-las-notas-NO-DEBE-SALIR-EN-EL-LOG"


def con_entidades_update(sv: SupervisorActualizaciones) -> None:
    """Entidades `update` de integraciones y de apps (tramo 3, T031–T034).

    - firmware (plataforma `ficticia`, `device_class: firmware`) con
      INSTALL | SPECIFIC_VERSION | BACKUP | RELEASE_NOTES (27) y notas con un
      secreto y un centinela;
    - otra integración solo con INSTALL (1), sin notas;
    - una al día (`off`);
    - la app de ejemplo, la de Hermes y otra app con sufijo `_hermes`, de la
      plataforma `hassio`, con `entity_id` renombrados;
    - `/addons/self/info` con el slug de Hermes.
    """
    for e in sv.estados:
        if e["entity_id"] == ENTIDAD_FIRMWARE:
            e["attributes"].update({
                "title": "Firmware ficticio", "supported_features": 27,
                "device_class": "firmware", "in_progress": False,
                "auto_update": False, "skipped_version": None,
                "update_percentage": None,
                "release_summary": "Resumen corto de la version",
            })
    sv.estados += [
        {"entity_id": ENTIDAD_SIN_NOTAS, "state": "on", "attributes": {
            "installed_version": "2.0.0", "latest_version": "2.1.0",
            "supported_features": 1, "in_progress": False, "title": "Integracion",
            "release_summary": "Resumen sin notas",
            "release_url": "https://example.invalid/sin-notas"}},
        {"entity_id": ENTIDAD_AL_DIA, "state": "off", "attributes": {
            "installed_version": "3.0.0", "latest_version": "3.0.0",
            "supported_features": 1, "in_progress": False}},
        {"entity_id": ENTIDAD_APP, "state": "on", "attributes": {
            "installed_version": "1.0.0", "latest_version": "1.1.0",
            "supported_features": 29, "in_progress": False}},
        {"entity_id": ENTIDAD_HERMES, "state": "on", "attributes": {
            "installed_version": "1.2.0", "latest_version": "1.2.1",
            "supported_features": 29, "in_progress": False}},
        {"entity_id": ENTIDAD_OTRO_HERMES, "state": "on", "attributes": {
            "installed_version": "0.1.0", "latest_version": "0.2.0",
            "supported_features": 29, "in_progress": False}},
    ]
    sv.registro[ENTIDAD_SIN_NOTAS] = {"entity_id": ENTIDAD_SIN_NOTAS,
                                      "platform": "otra_ficticia", "unique_id": "x1"}
    sv.registro[ENTIDAD_AL_DIA] = {"entity_id": ENTIDAD_AL_DIA,
                                   "platform": "otra_ficticia", "unique_id": "x2"}
    sv.registro[ENTIDAD_APP] = {"entity_id": ENTIDAD_APP, "platform": "hassio",
                                "unique_id": f"{SLUG_APP}_version_latest"}
    sv.registro[ENTIDAD_HERMES] = {"entity_id": ENTIDAD_HERMES, "platform": "hassio",
                                   "unique_id": f"{SLUG_HERMES}_version_latest"}
    sv.registro[ENTIDAD_OTRO_HERMES] = {"entity_id": ENTIDAD_OTRO_HERMES,
                                        "platform": "hassio",
                                        "unique_id": f"{SLUG_OTRO_HERMES}_version_latest"}
    sv.notas[ENTIDAD_FIRMWARE] = (
        f"## Cambios\n{CENTINELA_NOTAS}\npassword: {CENTINELA_PASSWORD}\n"
        f"token {CENTINELA_JWT}\n")
    sv.respuesta("GET", "/addons/self/info", {"slug": SLUG_HERMES, "name": "Hermes",
                                              "version": "1.2.0"})
