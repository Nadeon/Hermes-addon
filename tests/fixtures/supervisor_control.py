"""Supervisor simulado para la spec 022 (control de Core y del Supervisor).

Reproduce la FORMA de las respuestas del Supervisor 2026.11.0 (leída en su
código: `api/homeassistant.py`, `api/supervisor.py`, `api/jobs.py` y
`exceptions.py`), con datos ficticios. Nada sale de una instalación real
(principio VIII).

Apunta cada petición (método, ruta, cuerpo y `timeout_seconds`) para que los
tests comprueben lo que Hermes MANDA, y en especial que ningún rechazo
produce un `POST`. Simula:

- Core parado: `/core/stats` responde el error `HomeAssistantNotRunningError`
  (`error_key` `homeassistant_not_running_error`, HTTP 400);
- jobs en curso en `/jobs/info` (árbol con `child_jobs`);
- errores, tiempos vencidos y conexiones cortadas por ruta (`errores`);
- (tramo 2) el centro de resolución (`/resolution/info`, forma de
  `api/resolution.py`), los backups (`/backups`), la información de las apps
  (`/addons/<slug>/info`) y la del propio Hermes (`/addons/self/info`, con un
  slug ficticio `SLUG_HERMES`).
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from hermes.ha import HAConnectionError

CENTINELA_SV = "centinela-control-7"

# Slug ficticio del propio Hermes tal como lo daría `/addons/self/info`, y el
# de OTRA app cuyo nombre también acaba en `_hermes` (no es Hermes: el slug se
# compara exacto, nunca por el sufijo).
SLUG_HERMES = "0a1b2c3d_hermes"
SLUG_OTRA_HERMES = "9f8e7d6c_hermes"


def sugerencia(uuid: str, tipo: str, contexto: str, referencia: str | None = None,
               auto: bool = False) -> dict[str, Any]:
    """Una sugerencia con la forma de `Suggestion` en `/resolution/info`."""
    return {"uuid": uuid, "type": tipo, "context": contexto,
            "reference": referencia, "reference_extra": None, "auto": auto}


def issue(uuid: str, tipo: str, contexto: str, referencia: str | None = None) -> dict[str, Any]:
    return {"uuid": uuid, "type": tipo, "context": contexto,
            "reference": referencia, "reference_extra": None}


def backup(slug: str, fecha: str, tipo: str = "full") -> dict[str, Any]:
    """Un backup con la forma de `_list_backups` de `api/backups.py`."""
    return {"slug": slug, "name": f"Backup {slug}", "date": fecha, "type": tipo,
            "size": 1.5, "size_bytes": 1_500_000, "location": None,
            "locations": [None], "protected": False, "compressed": True,
            "content": {"homeassistant": True, "apps": [], "folders": []}}

# Error del Supervisor 2026.11.0 cuando Core no corre, como lo deja
# `HAClient._parse_sv_response` (HTTP 400 con el cuerpo de `api_return_error`).
_CUERPO_NO_CORRE = json.dumps({
    "result": "error", "message": "Home Assistant is not running",
    "error_key": "homeassistant_not_running_error", "extra_fields": None,
})


def error_core_parado() -> HAConnectionError:
    return HAConnectionError(
        f"Supervisor REST GET http://supervisor/core/stats failed 400: {_CUERPO_NO_CORRE}",
        status=400)


def error_400(ruta: str, mensaje: str) -> HAConnectionError:
    cuerpo = json.dumps({"result": "error", "message": mensaje})
    return HAConnectionError(
        f"Supervisor REST POST http://supervisor{ruta} failed 400: {cuerpo}", status=400)


def job(name: str, done: bool | None, hijos: list[dict[str, Any]] | None = None,
        progress: float = 0.0, stage: str | None = None) -> dict[str, Any]:
    """Un job con la forma de `SupervisorJob.as_dict()` y sus hijos."""
    return {"name": name, "reference": None, "uuid": hashlib.sha256(name.encode()).hexdigest()[:32],
            "progress": progress, "stage": stage, "done": done, "errors": [],
            "created": "2026-11-15T10:00:00+00:00", "extra": None,
            "child_jobs": hijos or []}


class SupervisorDeControl:
    """Cliente simulado con estado: Core y el Supervisor con sus opciones."""

    ready = True

    def __init__(self) -> None:
        self.core_info: dict[str, Any] = {
            "version": "2026.11.1", "version_latest": "2026.11.1",
            "update_available": False, "machine": "generic-x86-64",
            "ip_address": "192.0.2.10", "arch": "amd64", "image": "registro.example/core",
            "boot": True, "port": 8123, "ssl": False, "watchdog": True,
            "audio_input": None, "audio_output": None,
            "backups_exclude_database": False, "duplicate_log_file": False,
        }
        self.supervisor_info: dict[str, Any] = {
            "version": "2026.11.0", "version_latest": "2026.11.0",
            "update_available": False, "channel": "stable", "arch": "amd64",
            "supported": True, "healthy": True, "ip_address": "192.0.2.2",
            "timezone": "UTC", "country": None, "logging": "info", "debug": False,
            "debug_block": False, "diagnostics": False, "auto_update": True,
            "detect_blocking_io": False, "wait_boot": 5, "addons_repositories": [],
        }
        self.core_corre = True
        self.jobs: list[dict[str, Any]] = []
        # (método, ruta) → excepción a lanzar en esa petición.
        self.errores: dict[tuple[str, str], BaseException] = {}
        # Llamadas a hacer ANTES de responder una ruta (para cambiar el
        # estado entre la vista previa y la confirmación).
        self.formas: dict[tuple[str, str], Any] = {}
        self.llamadas: list[dict[str, Any]] = []
        # Tramo 2: centro de resolución, backups y apps.
        self.resolution: dict[str, Any] = {
            "unsupported": [], "unhealthy": [], "suggestions": [], "issues": [],
            "checks": [{"slug": "free_space", "enabled": True}],
        }
        self.backups: list[dict[str, Any]] = []
        self.addons: dict[str, dict[str, Any]] = {
            SLUG_HERMES: {"slug": SLUG_HERMES, "name": "Hermes", "state": "started"},
        }
        self.slug_propio = SLUG_HERMES

    async def wait_ready(self, timeout: float = 5.0) -> bool:
        # Las genéricas esperan a que el cliente esté listo (`requires_ready`).
        return True

    @property
    def escrituras(self) -> list[dict[str, Any]]:
        return [c for c in self.llamadas if c["metodo"] != "GET"]

    async def sv_request(
        self,
        method: str,
        sv_path: str,
        json_body: Any = None,
        params: Any = None,
        timeout_seconds: float = 60.0,
    ) -> Any:
        metodo = method.upper()
        self.llamadas.append({"metodo": metodo, "ruta": sv_path,
                              "json": copy.deepcopy(json_body),
                              "timeout": timeout_seconds})
        clave = (metodo, sv_path)
        if clave in self.errores:
            raise self.errores[clave]
        if clave in self.formas:
            return copy.deepcopy(self.formas[clave])
        if clave == ("GET", "/core/info"):
            return copy.deepcopy(self.core_info)
        if clave == ("GET", "/supervisor/info"):
            return copy.deepcopy(self.supervisor_info)
        if clave == ("GET", "/core/stats"):
            if not self.core_corre:
                raise error_core_parado()
            return {"cpu_percent": 1.5, "memory_usage": 1000, "memory_limit": 4000,
                    "memory_percent": 25.0, "network_rx": 1, "network_tx": 2,
                    "blk_read": 3, "blk_write": 4}
        if clave == ("GET", "/supervisor/stats"):
            return {"cpu_percent": 0.5, "memory_usage": 500}
        if clave == ("GET", "/jobs/info"):
            return {"ignore_conditions": [], "jobs": copy.deepcopy(self.jobs)}
        if clave == ("GET", "/resolution/info"):
            return copy.deepcopy(self.resolution)
        if clave == ("GET", "/backups"):
            return {"backups": copy.deepcopy(self.backups)}
        if clave == ("GET", "/addons/self/info"):
            return copy.deepcopy(self.addons.get(self.slug_propio, {"slug": self.slug_propio}))
        if metodo == "GET" and sv_path.startswith("/addons/") and sv_path.endswith("/info"):
            slug = sv_path[len("/addons/"):-len("/info")]
            if slug in self.addons:
                return copy.deepcopy(self.addons[slug])
        if metodo == "POST" and sv_path.startswith("/resolution/suggestion/"):
            uuid = sv_path.rsplit("/", 1)[1]
            self.resolution["suggestions"] = [
                s for s in self.resolution["suggestions"] if s["uuid"] != uuid]
            return {}
        if clave == ("POST", "/core/options"):
            self.core_info.update(json_body or {})
            return {}
        if clave == ("POST", "/supervisor/options"):
            self.supervisor_info.update(json_body or {})
            return {}
        if clave == ("POST", "/core/start"):
            self.core_corre = True
            return {}
        if metodo == "POST" and sv_path in (
                "/core/rebuild", "/supervisor/reload", "/supervisor/restart",
                "/supervisor/repair", "/host/reload"):
            return {}
        raise HAConnectionError(
            f"Supervisor REST {metodo} http://supervisor{sv_path} failed 404: not found",
            status=404)
