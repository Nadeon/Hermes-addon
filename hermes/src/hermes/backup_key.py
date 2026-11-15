"""Clave de cifrado de los backups de Home Assistant (spec 031, FR-011).

POR QUÉ ESTA CLAVE (research R-3, D-031-1 aceptada)
---------------------------------------------------
Es `create_backup.password` de `backup/config/info`: la que la interfaz de HA
genera al configurar los backups automáticos y entrega como «kit de
emergencia». Cifrar con ella (los backups que crea Hermes y, en el tramo 4,
los safety backups) deja que el usuario restaure desde la interfaz o la CLI
de HA aunque Hermes esté roto, que es justo cuando hace falta. Una clave
generada en `/data` solo la conocería Hermes y viajaría dentro del propio
backup que cifra.

POR QUÉ SIN CACHÉ
-----------------
Cada uso la vuelve a leer y la descarta al terminar la llamada: así no queda
en memoria más de lo necesario, y si el usuario cambia la clave en HA, el
siguiente backup ya usa la nueva.

POR QUÉ SE TAPA EL `repr`
-------------------------
Un `logger.info(..., clave=resultado)` o una excepción que formatee el objeto
sacarían la clave al log. `__repr__` y `__str__` la ocultan; quien la
necesita lee `.clave` a propósito, y solo para mandarla a HA en el momento.

Distingue los cuatro casos de FR-011 (hay clave, HA sin clave, integración no
disponible, HA inalcanzable) y, ante cualquier respuesta inesperada, NO hay
clave (fail-closed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hermes.ha import HAConnectionError

# Plazo corto: la lectura va delante de crear un backup (y, en el tramo 4, de
# un safety backup que bloquea una escritura en /config); no puede retrasarla
# los 30 s por defecto de `ws_send`.
_PLAZO_S = 10

SIN_CLAVE = "no_key_configured"
SIN_INTEGRACION = "backup_integration_unavailable"
HA_INALCANZABLE = "ha_unreachable"


@dataclass(frozen=True)
class ClaveDeBackups:
    """Resultado de leer la clave. `clave` es None si `motivo` no lo es."""

    clave: str | None
    motivo: str | None

    def __repr__(self) -> str:
        oculta = "<oculta>" if self.clave is not None else "None"
        return f"ClaveDeBackups(clave={oculta}, motivo={self.motivo!r})"

    __str__ = __repr__


async def leer_clave_de_backups(ha_client: Any) -> ClaveDeBackups:
    """Lee la clave de cifrado de los backups de HA en este momento."""
    try:
        data = await ha_client.ws_send({"type": "backup/config/info"},
                                       timeout_seconds=_PLAZO_S)
    except HAConnectionError as exc:
        if getattr(exc, "code", None) == "unknown_command":
            return ClaveDeBackups(None, SIN_INTEGRACION)
        if getattr(exc, "code", None) is None:
            # Sin código WS: no hubo respuesta de HA (WebSocket caído,
            # plazo agotado).
            return ClaveDeBackups(None, HA_INALCANZABLE)
        return ClaveDeBackups(None, SIN_INTEGRACION)
    config = data.get("config") if isinstance(data, dict) else None
    if not isinstance(config, dict):
        return ClaveDeBackups(None, SIN_INTEGRACION)
    crear = config.get("create_backup")
    if not isinstance(crear, dict):
        return ClaveDeBackups(None, SIN_INTEGRACION)
    clave = crear.get("password")
    if clave is None or clave == "":
        return ClaveDeBackups(None, SIN_CLAVE)
    if not isinstance(clave, str):
        return ClaveDeBackups(None, SIN_INTEGRACION)
    return ClaveDeBackups(clave, None)
