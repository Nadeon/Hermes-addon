"""Hermes — Ajustes de backup del Supervisor (spec 019, tramo 2; CAP-083).

Familia `mounts` (1.2.0), módulo `backup_settings`.

Tools:
  sv_get_backup_settings  — days_until_stale, montaje por defecto y montajes de backup
  sv_set_backup_settings  — cambia days_until_stale
  sv_reload_backups       — el Supervisor relee los backups de todas las ubicaciones

POR QUÉ
-------
Quien pregunta «a dónde van mis backups y cuándo se consideran viejos»
necesita tres cosas que el Supervisor da por dos rutas: `days_until_stale`
(`/backups/info`) y el montaje por defecto con los montajes de uso `backup`
(`/mounts`). Se juntan sin repetir la lista de backups, que ya da
`sv_list_backups` con su recorte (research R-8).

Ninguna pide token (research R-7): `days_until_stale` solo cambia cuándo
avisa el centro de resolución y se deshace con otra llamada; releer backups
no cambia ningún fichero. El montaje por defecto, que sí decide a dónde van
los backups, se cambia con `sv_set_default_backup_mount`, que confirma.

Los errores del Supervisor pasan por la misma limpieza que los de los
montajes: un error de lectura de un NAS puede repetir el usuario CIFS.
"""

from __future__ import annotations

from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.tools.mounts import _FormaInesperada, _leer_montajes, _limpiar_error

logger = structlog.get_logger(__name__)

_FORMA = ("The Supervisor returned an unexpected response shape for the backup "
          "settings or the mounts list.")


def _dias(datos: Any) -> int:
    """`days_until_stale` de `GET /backups/info`; una forma inesperada lanza."""
    valor = datos.get("days_until_stale") if isinstance(datos, dict) else None
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise _FormaInesperada
    return valor


# Tope superior de `days_until_stale` (T037): diez años. El Supervisor no
# pone ninguno, pero su `Backup.is_current` hace `utcnow() -
# timedelta(days=N)`, y con N ≥ ~740 000 eso lanza `OverflowError` en cada
# comprobación del centro de resolución: el aviso de «sin backup reciente»
# desaparece sin que nadie lo diga. Diez años ya equivale a no avisar nunca.
_DIAS_MAX = 3650


def _valido(dias: Any) -> bool:
    # `bool` es un `int` en Python: `True` llegaría como 1 al Supervisor.
    return (isinstance(dias, int) and not isinstance(dias, bool)
            and 1 <= dias <= _DIAS_MAX)


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de ajustes de backup en la instancia MCP."""

    def _error(exc: Exception) -> dict[str, Any]:
        if isinstance(exc, _FormaInesperada):
            return {"error": _FORMA}
        return {"error": _limpiar_error(str(exc), ())}

    @mcp.tool()
    async def sv_get_backup_settings() -> object:
        """Get the Supervisor's backup settings: days_until_stale (days after
        which the latest full backup no longer counts as recent and the
        Supervisor raises an issue), default_backup_mount (where backups
        without a location go, including Hermes safety backups; null = local
        storage) and backup_mounts (the mounts with usage 'backup' and their
        state). Read only; the backups themselves are listed by
        sv_list_backups.
        """
        try:
            dias = _dias(await ha_client.sv_request("GET", "/backups/info"))
            por_defecto, montajes = _leer_montajes(
                await ha_client.sv_request("GET", "/mounts"))
        except (HAConnectionError, _FormaInesperada) as exc:
            return _error(exc)
        logger.info("sv_get_backup_settings_ok")
        return {
            "days_until_stale": dias,
            "default_backup_mount": por_defecto,
            "backup_mounts": [{"name": m["name"], "state": m.get("state")}
                              for m in montajes if m.get("usage") == "backup"],
        }

    @mcp.tool()
    async def sv_set_backup_settings(days_until_stale: int) -> object:
        """Set days_until_stale: after how many days without a new full
        backup the Supervisor reports that backups are stale (an integer
        from 1 to 3650, ten years; the Supervisor's default is 30). Only
        changes when that warning appears; no backup is created or deleted.
        Values above 3650 are refused without calling the Supervisor. No
        confirmation needed. Returns the new and the previous value. To
        change where backups go, use sv_set_default_backup_mount.
        """
        if not _valido(days_until_stale):
            return {"error": "invalid_argument",
                    "detail": f"days_until_stale must be an integer from 1 to "
                              f"{_DIAS_MAX} (ten years)."}
        try:
            anterior = _dias(await ha_client.sv_request("GET", "/backups/info"))
            await ha_client.sv_request("POST", "/backups/options",
                                       json_body={"days_until_stale": days_until_stale})
        except (HAConnectionError, _FormaInesperada) as exc:
            return _error(exc)
        logger.info("sv_set_backup_settings_ok", days_until_stale=days_until_stale,
                    previous=anterior)
        return {"result": "ok", "days_until_stale": days_until_stale,
                "previous": anterior}

    @mcp.tool()
    async def sv_reload_backups() -> object:
        """Ask the Supervisor to read the backups again from every location
        (local storage and backup mounts), for example after copying backup
        files to a network share by hand. Changes no file. No confirmation
        needed. Returns how many backups the Supervisor sees afterwards.
        """
        try:
            await ha_client.sv_request("POST", "/backups/reload")
        except HAConnectionError as exc:
            return _error(exc)
        try:
            datos = await ha_client.sv_request("GET", "/backups")
            if not isinstance(datos, dict) or not isinstance(datos.get("backups"), list):
                raise _FormaInesperada
        except (HAConnectionError, _FormaInesperada):
            # La relectura ya se hizo: contar es lo de menos, pero no se
            # inventa un número.
            return {"result": "ok", "backups_count": None,
                    "warning": "Reloaded, but the backups could not be counted; "
                               "check them with sv_list_backups."}
        cuantos = len(datos["backups"])
        logger.info("sv_reload_backups_ok", backups_count=cuantos)
        return {"result": "ok", "backups_count": cuantos}
