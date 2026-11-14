"""Hermes — Tools MCP de disco, host y OS (spec 013, tramo 2; CAP-085).

Familia `system_diagnostics` (1.2.0), junto a `system_logs`. Solo leen.

Tools:
  sv_list_host_services        — servicios systemd del host y su estado
  sv_get_disk_usage            — qué ocupa el disco del sistema o un montaje
  sv_get_os_info               — versión, placa y slots de Home Assistant OS
  sv_get_swap                  — tamaño y swappiness de la swap (OS ≥ 15)
  sv_list_datadisk_candidates  — discos que pueden ser el disco de datos

POR QUÉ
-------
«Me he quedado sin disco», «¿qué versión de OS tengo y en qué slot arranca?» o
«¿qué servicio del host ha fallado?» eran preguntas que Hermes no podía
contestar sin pedir al usuario que mirase la interfaz. Son lecturas sin
efecto, así que no llevan confirmación.

Todas las respuestas JSON pasan por `redact_structure` (FR-016): hoy no llevan
secretos, pero es la misma defensa en profundidad que el resto de tools del
Supervisor. El número de serie de un disco SÍ va en la respuesta (research
R-7): no es un secreto, el `id` del disco ya lo contiene y sirve para
distinguir dos discos iguales. Lo que no puede pasar es que acabe en el log de
Hermes, que se pega en issues públicos (principio VIII): el evento
`system_diagnostics_read` solo lleva la plantilla de la ruta, recuentos,
bytes y el resultado.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes.ha import HAClient, HAConnectionError
from hermes.identifiers import InvalidIdentifier, validate_path_segment
from hermes.security import redact_secrets, redact_structure
from hermes.tools._common import ajustar_lista_a_bytes
from hermes.tools._logs import ArgumentoInvalido

logger = structlog.get_logger(__name__)

_EVENTO = "system_diagnostics_read"

# El Supervisor reserva `default` para el disco del sistema; un montaje se
# llama con letras, dígitos y `_` (`^[A-Za-z0-9_]+$` en el Supervisor). El
# tope de 64 es de Hermes: ningún nombre real se acerca.
_DISK = re.compile(r"^[A-Za-z0-9_]{1,64}$")
DETALLE_DISK = "disk must be 'default' or a mount name (letters, digits and '_')."
DETALLE_MAX_DEPTH = "max_depth must be between 0 and 3."
_MAX_DEPTH = 3

# Hijos que se conservan por nodo del árbol de uso (research R-4).
MAX_HIJOS = 20

# El Supervisor espera hasta 60 s (`MOUNT_USAGE_TIMEOUT`) a un montaje lento y
# después responde con error; con 75 s ese error llega a Hermes en vez de un
# corte de la petición que no diría nada (research R-4).
_ESPERA_USO_DE_DISCO = 75.0

_PISTA_OS = "Requires Home Assistant OS (swap needs OS 15 or newer)."


def podar_arbol(nodo: dict[str, Any], max_hijos: int = MAX_HIJOS) -> dict[str, Any]:
    """Copia del nodo con, en cada nivel, solo los `max_hijos` hijos que más
    ocupan (empate por `id`, para que el resultado no dependa del orden del
    Supervisor).

    POR QUÉ: con `max_depth` 3, una carpeta con miles de subcarpetas da un
    árbol que no cabe en `response_max_bytes`, y el tope central solo sabe
    recortar listas del primer nivel. Para «qué llena el disco» lo que importa
    son las carpetas grandes. Lo quitado se resume en `children_omitted` y
    `omitted_bytes` para que la suma siga cuadrando y la respuesta no mienta
    (principio V). Un nodo sin nada quitado no gana esas claves.
    """
    copia = {k: v for k, v in nodo.items() if k != "children"}
    hijos = nodo.get("children")
    if not isinstance(hijos, list):
        return copia
    validos = [h for h in hijos if isinstance(h, dict)]
    ordenados = sorted(
        validos,
        key=lambda h: (-_bytes(h.get("used_bytes")), str(h.get("id", ""))),
    )
    quedan, quitados = ordenados[:max_hijos], ordenados[max_hijos:]
    copia["children"] = [podar_arbol(h, max_hijos) for h in quedan]
    if quitados:
        copia["children_omitted"] = len(quitados)
        copia["omitted_bytes"] = sum(_bytes(h.get("used_bytes")) for h in quitados)
    return copia


def _bytes(valor: Any) -> int:
    # Un `used_bytes` que no sea un número cuenta como 0 para ordenar y sumar;
    # el valor original sigue en el nodo tal cual.
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return 0
    return int(valor)


def _validar_disk(disk: Any) -> str:
    if not isinstance(disk, str) or not _DISK.fullmatch(disk):
        raise ArgumentoInvalido("disk", DETALLE_DISK)
    # Segunda capa, la común de Hermes, por si la regla de arriba se relaja.
    try:
        return validate_path_segment(disk, field="disk")
    except InvalidIdentifier:
        raise ArgumentoInvalido("disk", DETALLE_DISK) from None


def _validar_max_depth(max_depth: Any) -> int:
    # `True` es un `int` en Python, pero no es una profundidad.
    if (
        isinstance(max_depth, bool)
        or not isinstance(max_depth, int)
        or not 0 <= max_depth <= _MAX_DEPTH
    ):
        raise ArgumentoInvalido("max_depth", DETALLE_MAX_DEPTH)
    return max_depth


def _tam(valor: Any) -> int:
    return len(json.dumps(valor, ensure_ascii=False, default=str).encode("utf-8"))


def register(
    mcp: object,
    ha_client: HAClient,
    *,
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
) -> None:
    """Registra las tools de disco, host y OS en la instancia MCP."""

    async def _leer(
        tool: str, plantilla: str, ruta: str, **kwargs: Any
    ) -> tuple[Any, dict[str, Any] | None]:
        """(datos, None) o (None, respuesta de error). Registra el error."""
        try:
            return await ha_client.sv_request("GET", ruta, **kwargs), None
        except HAConnectionError as exc:
            status = getattr(exc, "status", None)
            logger.info(_EVENTO, tool=tool, route=plantilla, status=status,
                        outcome="error")
            # El mensaje del Supervisor puede repetir parte de la petición: se
            # redacta como los logs (research R-8).
            out: dict[str, Any] = {"error": redact_secrets(str(exc))}
            if status == 404 and plantilla.startswith("/os/"):
                # Sin Home Assistant OS (o la swap antes de OS 15) el
                # Supervisor da 404: la pista evita que el agente reintente
                # algo que no puede funcionar en esta instalación.
                out["hint"] = _PISTA_OS
            return None, out

    def _forma_inesperada(tool: str, plantilla: str) -> dict[str, Any]:
        # Nunca se da por buena una respuesta vacía o de otra forma (FR-016).
        logger.info(_EVENTO, tool=tool, route=plantilla, outcome="error")
        return {"error": f"Unexpected Supervisor response for GET {plantilla}."}

    def _invalido(tool: str, exc: ArgumentoInvalido) -> dict[str, Any]:
        # Solo el campo: el valor rechazado puede ser cualquier cosa.
        logger.info(_EVENTO, tool=tool, field=exc.campo, outcome="invalid_argument")
        return exc.respuesta()

    async def _objeto(tool: str, ruta: str) -> dict[str, Any]:
        data, error = await _leer(tool, ruta, ruta)
        if error is not None:
            return error
        if not isinstance(data, dict) or not data:
            return _forma_inesperada(tool, ruta)
        out = redact_structure(data)
        logger.info(_EVENTO, tool=tool, route=ruta, bytes=_tam(out), outcome="ok")
        return out

    @mcp.tool()
    async def sv_list_host_services(state: str | None = None) -> object:
        """List the host's systemd services with their state (read only).

        Args:
            state: Optional exact state to keep, e.g. `failed`, `active` or
                `inactive`.

        Returns:
            {"count": N, "truncated": bool,
             "items": [{"name", "description", "state"}, ...]}, plus `state`
            when given.
        """
        tool, plantilla = "sv_list_host_services", "/host/services"
        data, error = await _leer(tool, plantilla, plantilla)
        if error is not None:
            return error
        servicios = data.get("services") if isinstance(data, dict) else None
        if not isinstance(servicios, list):
            return _forma_inesperada(tool, plantilla)
        items = [s for s in servicios if isinstance(s, dict)]
        if state is not None:
            items = [s for s in items if s.get("state") == state]
        items = redact_structure(items)
        logger.info(_EVENTO, tool=tool, route=plantilla, count=len(items), outcome="ok")

        def construir(kept: list[Any], cut: bool) -> dict[str, Any]:
            out: dict[str, Any] = {"count": len(items), "truncated": cut, "items": kept}
            if cut:
                out["returned"] = len(kept)
                out["hint"] = "Use state to narrow the list."
            if state is not None:
                out["state"] = state
            return out

        return ajustar_lista_a_bytes(items, construir, response_max_bytes)

    @mcp.tool()
    async def sv_get_disk_usage(disk: str = "default", max_depth: int = 1) -> object:
        """Show what uses the space of the system disk or of a network
        storage mount, as a tree of folders (read only).

        Each level keeps the 20 children that use the most space; when more
        exist, the node carries `children_omitted` and `omitted_bytes` so the
        sizes still add up. Measuring a slow network mount can take up to a
        minute.

        Args:
            disk: `default` (the system disk) or the name of a storage mount
                (letters, digits and '_').
            max_depth: How many folder levels to break down, 0-3 (default 1).

        Returns:
            {"disk", "max_depth", "id", "label", "total_bytes", "used_bytes",
             "children": [{"id", "label", "used_bytes", "children"?, ...}]},
            or {"error": "invalid_argument", "field", "detail"} without
            calling the Supervisor.
        """
        tool, plantilla = "sv_get_disk_usage", "/host/disks/{disk}/usage"
        try:
            disk = _validar_disk(disk)
            max_depth = _validar_max_depth(max_depth)
        except ArgumentoInvalido as exc:
            return _invalido(tool, exc)
        data, error = await _leer(
            tool, plantilla, f"/host/disks/{disk}/usage",
            params={"max_depth": str(max_depth)},
            timeout_seconds=_ESPERA_USO_DE_DISCO,
        )
        if error is not None:
            return error
        if not isinstance(data, dict) or "used_bytes" not in data:
            return _forma_inesperada(tool, plantilla)
        arbol = redact_structure(podar_arbol(data))
        out = {"disk": disk, "max_depth": max_depth, **arbol}
        logger.info(_EVENTO, tool=tool, route=plantilla, bytes=_tam(out), outcome="ok")
        return out

    @mcp.tool()
    async def sv_get_os_info() -> object:
        """Home Assistant OS information: version, latest version, whether an
        update is available, board, boot slot, data disk and boot slots
        (read only). Requires Home Assistant OS.

        Returns:
            The Supervisor's `/os/info` object; on an installation without
            Home Assistant OS, {"error", "hint"}.
        """
        return await _objeto("sv_get_os_info", "/os/info")

    @mcp.tool()
    async def sv_get_swap() -> object:
        """Swap size and swappiness of Home Assistant OS (read only).
        Requires Home Assistant OS 15 or newer.

        Returns:
            {"swap_size", "swappiness"}; without Home Assistant OS 15+,
            {"error", "hint"}.
        """
        return await _objeto("sv_get_swap", "/os/config/swap")

    @mcp.tool()
    async def sv_list_datadisk_candidates() -> object:
        """List the disks that could become the Home Assistant OS data disk
        (read only; it does not move anything). Requires Home Assistant OS.

        Returns:
            {"count": N, "truncated": bool, "devices": ["<disk id>", ...],
             "items": [{"name", "vendor", "model", "serial", "size", "id",
             "dev_path"}, ...]}; without Home Assistant OS, {"error", "hint"}.
        """
        tool, plantilla = "sv_list_datadisk_candidates", "/os/datadisk/list"
        data, error = await _leer(tool, plantilla, plantilla)
        if error is not None:
            return error
        discos = data.get("disks") if isinstance(data, dict) else None
        if not isinstance(discos, list):
            return _forma_inesperada(tool, plantilla)
        items = redact_structure([d for d in discos if isinstance(d, dict)])
        devices = redact_structure(data.get("devices") or [])
        logger.info(_EVENTO, tool=tool, route=plantilla, count=len(items), outcome="ok")

        def construir(kept: list[Any], cut: bool) -> dict[str, Any]:
            out: dict[str, Any] = {
                "count": len(items), "truncated": cut, "devices": devices, "items": kept,
            }
            if cut:
                out["returned"] = len(kept)
            return out

        return ajustar_lista_a_bytes(items, construir, response_max_bytes)
