"""Plataforma del Supervisor vista por Hermes: socket Unix y API `/v2`.

El Supervisor está cambiando de plataforma, pero en la 2026.11.0 nada de eso
llega a las apps:

- El socket Unix (`supervisor/docker/homeassistant.py`, `run()`) solo se
  inyecta en Core con `SUPERVISOR_SOCKET`; `docker/app.py` no lo inyecta en
  las apps (spec 027, research R-2).
- La API `/v2` (`supervisor/api/__init__.py`, `load()`) es una opción de
  desarrollo (`feature_flags.supervisor_v2_api`) que se monta APARTE: la V1
  sigue servida en la raíz aunque la V2 esté activada (research R-3).

Por eso Hermes 1.2.0 solo DETECTA y avisa en el log, sin usar ninguno de los
dos: cambiar de transporte o de rutas sin haberlo probado contra un Supervisor
real podría romper una instalación que hoy funciona. El día que el Supervisor
los publique, el aviso dice a quien mantiene la instalación que Hermes sigue
por TCP y por la V1, y la hoja de ruta dice qué habrá que cambiar.

La comprobación nunca para el arranque: cualquier fallo de la lectura da
`api_v2_enabled: None` («no se sabe»), nunca `False` («no hay `/v2`»), para no
afirmar lo que no se ha visto (principio III). El log no lleva la ruta del
socket ni el texto de los errores (principio II).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

SOCKET_ENV = "SUPERVISOR_SOCKET"
# Tope de la lectura de `/supervisor/info` en el arranque: es informativa y no
# puede retrasar el servicio más que esto.
TIMEOUT_S = 10.0


def socket_ofrecido(environ: Mapping[str, str]) -> bool:
    """¿El Supervisor ha inyectado `SUPERVISOR_SOCKET` (no vacío)?"""
    valor = environ.get(SOCKET_ENV, "")
    return isinstance(valor, str) and valor.strip() != ""


def api_v2_activada(info: Any) -> bool | None:
    """`feature_flags.supervisor_v2_api` de `GET /supervisor/info`.

    `True` solo si la opción es exactamente `true`. Un objeto válido sin
    `feature_flags` (Supervisor anterior a las opciones) o sin la clave es
    `False`: ese Supervisor no tiene `/v2`. Una respuesta que no es un objeto,
    o un `feature_flags` que no lo es, es `None`: no se sabe.
    """
    if not isinstance(info, dict):
        return None
    if "feature_flags" not in info:
        return False
    flags = info["feature_flags"]
    if not isinstance(flags, dict):
        return None
    return flags.get("supervisor_v2_api") is True


async def comprobar_plataforma(ha_client: Any, environ: Mapping[str, str]) -> dict[str, Any]:
    """Detecta el socket y la `/v2`, lo anota en el log y NO cambia nada.

    Nunca lanza (salvo `asyncio.CancelledError`, que es del arranque y no
    nuestra) y tarda como mucho `TIMEOUT_S`. Devuelve el evento escrito.
    """
    ofrecido = socket_ofrecido(environ)
    motivo: str | None = None
    try:
        info = await asyncio.wait_for(
            ha_client.sv_request("GET", "/supervisor/info", timeout_seconds=TIMEOUT_S),
            timeout=TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        info, motivo = None, "timeout"
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — informativa: ningún fallo para el arranque
        info, motivo = None, "error"
    v2 = api_v2_activada(info) if motivo is None else None
    if v2 is None and motivo is None:
        motivo = "unexpected_response"

    evento: dict[str, Any] = {
        "transport": "tcp",
        "unix_socket_offered": ofrecido,
        "api_v2_enabled": v2,
    }
    logger.info("supervisor_platform", **evento)
    if motivo is not None:
        # Sin el texto del error: puede citar la URL o cabeceras.
        logger.debug("supervisor_platform_check_failed", reason=motivo)
    if ofrecido:
        logger.warning(
            "supervisor_unix_socket_offered",
            message="The Supervisor offers a Unix socket to apps; Hermes "
                    "1.2.0 keeps using TCP, which is still supported.",
        )
    if v2 is True:
        logger.warning(
            "supervisor_api_v2_enabled",
            message="The Supervisor /v2 API is enabled; Hermes 1.2.0 keeps "
                    "using the V1 API, which is still served.",
        )
    return evento
