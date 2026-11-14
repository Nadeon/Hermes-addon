"""Registro de los flujos de reconfigure que abre Hermes (spec 016, tramo B).

POR QUÉ existe (decisión del supervisor, FR-010a…FR-010c): reconfigurar una
entrada puede cambiar sus credenciales o sus datos de conexión y HA la recarga
al terminar, así que cada paso que se envía pide token. Pero HA no deja
reconocer un flujo de reconfigure por su `flow_id`: el `GET` de un flujo no
trae su `source`, y `config_entries/flow/progress` excluye los `reconfigure`.
Sin este registro, `ha_continue_config_entry_flow` (sin token, de la 1.1.2)
continuaría un reconfigure como si fuera un flujo de configuración más.

En memoria y con caducidad, como pidió el supervisor. Un reconfigure caducado
NO se olvida sin más: si saliera del registro con el flujo vivo en HA, la tool
general volvería a aceptarlo. Se aborta en HA y solo sale del registro cuando
el abort sale o HA dice que el flujo ya no existe; mientras tanto sigue
rechazado por la vía general.

Riesgo residual (documentado en la spec, FR-010c): al reiniciar Hermes el
registro empieza vacío. Un reconfigure abierto antes del reinicio solo se
podría continuar por la vía general conociendo su `flow_id`, que HA no lista
en ningún comando.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import redact_secrets
from hermes.tools._validation import InvalidIdentifier, validate_identifier

logger = structlog.get_logger(__name__)

# Una hora desde el último uso: un reconfigure es interactivo (el usuario
# revisa cada vista previa), pero un flujo olvidado no debe quedar abierto en
# HA indefinidamente.
CADUCIDAD_S = 3600.0


@dataclass
class Reconfigure:
    flow_id: str
    entry_id: str
    domain: str
    title: str | None
    ultimo_uso: float


_REGISTRO: dict[str, Reconfigure] = {}


def _ahora() -> float:
    # Reloj monótono: un cambio de hora del sistema no caduca nada. Los tests
    # lo sustituyen para adelantar el tiempo.
    return time.monotonic()


def registrar(flow_id: str, entry_id: str, domain: str, title: str | None) -> None:
    _REGISTRO[flow_id] = Reconfigure(flow_id, entry_id, domain, title, _ahora())


def buscar(flow_id: str) -> Reconfigure | None:
    """El reconfigure registrado con ese `flow_id`, caducado o no.

    Caducado o no, a propósito: para la tool general un caducado sigue siendo
    un reconfigure (y se rechaza) hasta que su flujo está abortado en HA.
    """
    return _REGISTRO.get(flow_id)


def caducado(r: Reconfigure) -> bool:
    return _ahora() - r.ultimo_uso > CADUCIDAD_S


def tocar(flow_id: str) -> None:
    r = _REGISTRO.get(flow_id)
    if r is not None:
        r.ultimo_uso = _ahora()


def olvidar(flow_id: str) -> None:
    _REGISTRO.pop(flow_id, None)


def limpiar() -> None:
    """Vacía el registro (para los tests)."""
    _REGISTRO.clear()


async def barrer(ha_client: HAClient) -> list[str]:
    """Aborta en HA los reconfigure caducados; devuelve los que salieron.

    Best-effort: si el `DELETE` falla por otra cosa que un 404, el flujo se
    queda en el registro (y rechazado por la vía general) y se reintenta en
    el siguiente barrido.
    """
    salidos: list[str] = []
    for flow_id, r in list(_REGISTRO.items()):
        if not caducado(r):
            continue
        # Lo validó quien lo registró; se vuelve a validar donde se construye
        # la ruta, como en el resto de Hermes.
        try:
            validate_identifier(flow_id, field="flow_id")
        except InvalidIdentifier:
            olvidar(flow_id)
            continue
        try:
            await ha_client._request_json(  # noqa: SLF001
                "DELETE", f"/config/config_entries/flow/{flow_id}")
        except HAConnectionError as exc:
            if exc.status != 404:
                logger.warning("reconfigure_expired_abort_failed", flow_id=flow_id,
                               entry_id=r.entry_id, error=redact_secrets(str(exc)))
                continue
        olvidar(flow_id)
        salidos.append(flow_id)
        logger.info("reconfigure_expired_aborted", flow_id=flow_id, entry_id=r.entry_id)
    return salidos
