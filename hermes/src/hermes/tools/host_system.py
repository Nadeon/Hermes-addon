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

import copy
import json
import re
from collections.abc import Callable
from typing import Any

import structlog

from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes.ha import HAClient, HAConnectionError
from hermes.identifiers import InvalidIdentifier, validate_path_segment
from hermes.security import redact_secrets, redact_structure
from hermes.tools._common import ajustar_lista_a_bytes, sobre_de_lista, tam_json
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

_PISTA_ARBOL = (
    "The smallest folders were folded into their parent's children_omitted "
    "and omitted_bytes to fit response_max_bytes; a lower max_depth shows "
    "fewer levels with less folding."
)

_PISTA_OS = "Requires Home Assistant OS (swap needs OS 15 or newer)."


def podar_arbol(nodo: dict[str, Any], max_hijos: int = MAX_HIJOS) -> dict[str, Any]:
    """Copia del nodo con, en cada nivel, solo los `max_hijos` hijos que más
    ocupan (empate por `id`, para que el resultado no dependa del orden del
    Supervisor).

    POR QUÉ: con `max_depth` 3, una carpeta con miles de subcarpetas da un
    árbol enorme. Para «qué llena el disco» lo que importa son las carpetas
    grandes. Aun así, 20 por nivel en tres niveles puede no caber en
    `response_max_bytes`: eso lo resuelve después `ajustar_arbol_a_bytes`. Lo quitado se resume en `children_omitted` y
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


def ajustar_arbol_a_bytes(
    arbol: dict[str, Any],
    construir: Callable[[dict[str, Any], bool], dict[str, Any]],
    max_bytes: int,
) -> dict[str, Any]:
    """Respuesta con el árbol que quepa en `max_bytes`, quitando primero las
    carpetas que MENOS ocupan.

    `construir(arbol, recortado)` arma la respuesta completa (con la marca y la
    pista cuando `recortado`). Cada carpeta quitada se suma al
    `children_omitted` y al `omitted_bytes` de su padre, así que en CADA nivel
    los hijos que quedan más `omitted_bytes` suman lo mismo que los hijos que
    dio el Supervisor (research R-4, principio V).

    POR QUÉ: con `max_depth` 3, aun podado a 20 hijos por nivel, el árbol del
    disco del sistema pasa de 200 KB. El guardián central solo sabe recortar
    la lista del primer nivel: quitaba ramas enteras sin decir cuánto
    ocupaban y la suma dejaba de cuadrar. Quitar por tamaño conserva lo que
    responde a «qué llena el disco»: las carpetas grandes.

    Se estima lo que ahorra cada carpeta con su tamaño serializado y se
    verifica con el tamaño real, repitiendo si las claves añadidas
    (`children_omitted`, `omitted_bytes`) se comen lo ahorrado. El orden
    (tamaño, más profunda antes, `id`) no depende del orden del Supervisor.
    """
    completa = construir(arbol, False)
    if tam_json(completa) <= max_bytes:
        return completa
    arbol = copy.deepcopy(arbol)
    # (nodo, padre, profundidad) de todo nodo salvo la raíz.
    nodos: list[tuple[dict[str, Any], dict[str, Any], int]] = []

    def recorrer(nodo: dict[str, Any], profundidad: int) -> None:
        hijos = nodo.get("children")
        if not isinstance(hijos, list):
            return
        for hijo in hijos:
            if isinstance(hijo, dict):
                nodos.append((hijo, nodo, profundidad + 1))
                recorrer(hijo, profundidad + 1)

    recorrer(arbol, 0)
    nodos.sort(key=lambda t: (_bytes(t[0].get("used_bytes")), -t[2], str(t[0].get("id", ""))))
    quitados: set[int] = set()

    def marcar(nodo: dict[str, Any]) -> None:
        # Un descendiente de una carpeta quitada ya no está en el árbol: no
        # puede quitarse otra vez ni sumarse dos veces.
        quitados.add(id(nodo))
        for hijo in nodo.get("children") or []:
            if isinstance(hijo, dict):
                marcar(hijo)

    i = 0
    out = construir(arbol, True)
    while tam_json(out) > max_bytes and i < len(nodos):
        exceso = tam_json(out) - max_bytes
        ahorro = 0
        while ahorro < exceso and i < len(nodos):
            nodo, padre, _ = nodos[i]
            i += 1
            if id(nodo) in quitados:
                continue
            marcar(nodo)
            padre["children"] = [h for h in padre["children"] if h is not nodo]
            padre["children_omitted"] = padre.get("children_omitted", 0) + 1
            padre["omitted_bytes"] = (
                padre.get("omitted_bytes", 0) + _bytes(nodo.get("used_bytes"))
            )
            # ", " entre elementos de la lista.
            ahorro += tam_json(nodo) + 2
        out = construir(arbol, True)
    return out


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
            when given; `count` is how many items come back and, when cut,
            `total` says how many there were.
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

        # Sobre común de la 1.2.0 (spec 018, FR-012): `count` es cuántos
        # `items` vienen; si se cortó, `total` dice cuántos había, como el
        # tope central (`recortar_a_bytes`).
        def construir(kept: list[Any], cut: bool) -> dict[str, Any]:
            cabecera: dict[str, Any] = {}
            if state is not None:
                cabecera["state"] = state
            if cut:
                cabecera["total"] = len(items)
                cabecera["hint"] = "Use state to narrow the list."
            return sobre_de_lista(kept, truncated=cut, **cabecera)

        return ajustar_lista_a_bytes(items, construir, response_max_bytes)

    @mcp.tool()
    async def sv_get_disk_usage(disk: str = "default", max_depth: int = 1) -> object:
        """Show what uses the space of the system disk or of a network
        storage mount, as a tree of folders (read only).

        Each level keeps the 20 children that use the most space; when more
        exist, the node carries `children_omitted` and `omitted_bytes` so the
        sizes still add up. If the tree still does not fit in the response
        limit, the smallest folders anywhere in it are folded the same way
        and the answer carries `truncated: true` and a `hint`. Measuring a
        slow network mount can take up to a minute.

        Levels you get for each `max_depth` (the Supervisor decides them):
        - system disk: the first level is always its fixed areas (system,
          add-on data and config, media, share, backup, ssl, homeassistant);
          0 and 1 give only that level, 2 adds one level of folders inside
          each area and 3 adds two.
        - storage mount: 0 and 1 give only the totals, with no children; 2
          gives one level of folders and 3 gives two.

        Args:
            disk: `default` (the system disk) or the name of a storage mount
                (letters, digits and '_').
            max_depth: 0-3 (default 1); see the levels above.

        Returns:
            {"disk", "max_depth", "id", "label", "total_bytes", "used_bytes",
             "children": [{"id", "label", "used_bytes", "children"?, ...}]},
            plus `truncated` and `hint` when folded to fit; or
            {"error": "invalid_argument", "field", "detail"} without calling
            the Supervisor.
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

        def construir(nodo: dict[str, Any], recortado: bool) -> dict[str, Any]:
            out = {"disk": disk, "max_depth": max_depth, **nodo}
            if recortado:
                out["truncated"] = True
                out["hint"] = _PISTA_ARBOL
            return out

        # La tool cabe por su cuenta: el guardián central no llega a actuar
        # (quitaría ramas enteras del primer nivel sin cuadrar la suma).
        # `max_depth` se manda tal cual: en un montaje el Supervisor da un
        # nivel menos que en el disco del sistema (convierte < 2 en 0 y solo
        # desglosa con > 1; `api/host.py` del 2026.11.0). Compensarlo con +1
        # haría que `max_depth=3` recorriera cuatro niveles de un recurso de
        # red lento, más allá del tope de 3; la descripción dice qué niveles
        # da cada valor (principio V).
        out = ajustar_arbol_a_bytes(arbol, construir, response_max_bytes)
        logger.info(_EVENTO, tool=tool, route=plantilla, bytes=_tam(out),
                    truncated=bool(out.get("truncated")), outcome="ok")
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
             "dev_path"}, ...]}, plus `total` when cut; without Home
            Assistant OS, {"error", "hint"}.
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

        # Sobre común de la 1.2.0 (spec 018, FR-012): `count` es cuántos
        # `items` vienen; si se cortó, `total` dice cuántos había, como el
        # tope central (`recortar_a_bytes`).
        def construir(kept: list[Any], cut: bool) -> dict[str, Any]:
            if cut:
                return sobre_de_lista(kept, truncated=True, devices=devices,
                                      total=len(items))
            return sobre_de_lista(kept, devices=devices)

        return ajustar_lista_a_bytes(items, construir, response_max_bytes)
