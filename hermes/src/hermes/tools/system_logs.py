"""Hermes — Tools MCP de logs del sistema (spec 013, CAP-081).

Familia `system_diagnostics` (1.2.0). Solo leen.

Tools:
  sv_get_core_logs              — log de Home Assistant Core
  sv_get_supervisor_logs        — log del Supervisor
  sv_get_plugin_logs            — log de un plugin (dns, audio, multicast)
  sv_get_host_logs              — journal del host (por identificador)
  sv_list_host_log_identifiers  — identificadores de syslog del journal
  sv_list_boots                 — arranques del journal (desplazamiento e id)

POR QUÉ
-------
Hasta la 1.1.2, Hermes solo leía el log de un add-on. Para diagnosticar «HA no
arranca» o «el host se reinició solo» hacen falta el log de Core, del
Supervisor y del journal del host, también de arranques anteriores: lo que se
quiere ver suele estar justo antes del último reinicio.

Todo log pasa por `redact_secrets` antes de devolverse, igual que
`sv_get_addon_logs`: Core y los add-ons escriben contraseñas y tokens en
claro. El log del propio Hermes por el journal del host (`addon_<slug>` o
`app_<slug>`) lleva además la redacción de red, como en `sv_get_addon_logs`.
Si el log no cabe en `response_max_bytes`, se devuelven sus ÚLTIMAS líneas: en
un log, lo que importa es el final.

El log de Hermes (`system_diagnostics_read`) lleva la plantilla de la ruta y
recuentos; nunca el contenido, un id de arranque, el `identifier` ni el
`search`, porque ese log se pega en issues públicos (principio VIII).
"""

from __future__ import annotations

from typing import Any

import structlog

from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes.ha import HAClient, HAConnectionError
from hermes.logging_setup import network_redaction_enabled, redact_network
from hermes.security import redact_secrets, redact_structure
from hermes.tools._common import ajustar_lista_a_bytes, sobre_de_lista
from hermes.tools._logs import (
    ArgumentoInvalido,
    acotar_lineas,
    comprobar_latest,
    normalizar_boot,
    ruta_de_host,
    ruta_de_log,
    ruta_de_plugin,
    validar_identifier,
    validar_plugin,
)
from hermes.tools._common import ultimas_lineas_que_caben
from hermes.tools.addons import _es_hermes

logger = structlog.get_logger(__name__)

_EVENTO = "system_diagnostics_read"


def _identifier_de_hermes(identifier: str | None) -> bool:
    """True si el identificador del journal es el del contenedor de Hermes.

    El Supervisor 2026.11 etiqueta el log de un add-on con `addon_<slug>` y,
    en los nuevos, `app_<slug>`.
    """
    if not identifier:
        return False
    for prefijo in ("addon_", "app_"):
        if identifier.startswith(prefijo) and _es_hermes(identifier[len(prefijo):]):
            return True
    return False


def _forma_inesperada(tool: str, plantilla: str) -> dict[str, Any]:
    # Nunca se da por buena una respuesta vacía o de otra forma (FR-016),
    # como en `host_system.py`.
    logger.info(_EVENTO, tool=tool, route=plantilla, outcome="error")
    return {"error": f"Unexpected Supervisor response for GET {plantilla}."}


def _error(exc: HAConnectionError) -> dict[str, Any]:
    # El mensaje del Supervisor puede repetir parte de la petición o del log:
    # se redacta igual que el log (research R-8).
    return {"error": redact_secrets(str(exc))}


def register(
    mcp: object,
    ha_client: HAClient,
    *,
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
) -> None:
    """Registra las tools de logs del sistema en la instancia MCP."""

    def _invalido(tool: str, exc: ArgumentoInvalido) -> dict[str, Any]:
        # Solo el campo: el valor rechazado puede ser cualquier cosa.
        logger.info(_EVENTO, tool=tool, field=exc.campo, outcome="invalid_argument")
        return exc.respuesta()

    async def _leer_log(
        tool: str,
        *,
        source: str,
        ruta: str,
        plantilla: str,
        lines: int,
        extra: dict[str, Any],
        tapar_red: bool,
    ) -> dict[str, Any]:
        try:
            raw = await ha_client.sv_request_text(ruta, params={"lines": str(lines)})
        except HAConnectionError as exc:
            logger.info(_EVENTO, tool=tool, route=plantilla, lines=lines,
                        status=getattr(exc, "status", None), outcome="error")
            return _error(exc)
        redactado = redact_secrets(raw)
        secrets_redacted = redactado != raw
        network_redacted = tapar_red and network_redaction_enabled()
        if tapar_red:
            # `redact_network` no hace nada si la opción está desactivada.
            redactado = redact_network(redactado)
        was_redacted = redactado != raw
        logger.info(_EVENTO, tool=tool, route=plantilla, lines=lines,
                    bytes=len(raw), redacted=was_redacted, outcome="ok")
        return ultimas_lineas_que_caben(
            {
                "source": source,
                "route": plantilla,
                **extra,
                "lines_requested": lines,
                "redacted": was_redacted,
                "secrets_redacted": secrets_redacted,
                "network_redacted": network_redacted,
            },
            redactado,
            response_max_bytes,
        )

    async def _log_con_arranque(
        tool: str, source: str, base: str | None, lines: int, boot: Any, latest: bool
    ) -> dict[str, Any]:
        # `base` es una constante (`/core`, `/supervisor`); sin ella, `source`
        # es un plugin ya validado.
        try:
            boot_n = normalizar_boot(boot)
            comprobar_latest(boot_n, latest)
            if base is None:
                ruta, plantilla = ruta_de_plugin(source, boot_n, latest)
            else:
                ruta, plantilla = ruta_de_log(base, base, boot_n, latest)
        except ArgumentoInvalido as exc:
            return _invalido(tool, exc)
        extra: dict[str, Any] = {}
        if boot_n is not None:
            extra["boot"] = boot_n
        if latest:
            extra["latest"] = True
        return await _leer_log(
            tool, source=source, ruta=ruta, plantilla=plantilla,
            lines=acotar_lineas(lines), extra=extra, tapar_red=False,
        )

    @mcp.tool()
    async def sv_get_core_logs(
        lines: int = 100, boot: int | str | None = None, latest: bool = False
    ) -> object:
        """Read the Home Assistant Core log from the Supervisor (read only).

        Secrets (passwords, tokens, JWTs, URLs with credentials) are redacted
        before the text is returned. If the log does not fit in the response
        size limit, the LAST lines that fit are returned with
        `truncated: true`, `lines_returned` and a hint.

        Args:
            lines: Number of lines (default 100, clamped to 1-1000).
            boot: Optional boot to read: an integer offset (0 = current boot,
                -1 = the previous one, -2 = the one before) or a boot ID from
                `sv_list_boots`. Without it, the current journal.
            latest: Only the lines since the Core container last started.
                Cannot be combined with `boot`.

        Returns:
            {"source": "core", "route": "<route template>", "lines_requested",
             "redacted", "secrets_redacted", "network_redacted", "logs"}, plus
            `boot` or `latest` when used. Invalid arguments return
            {"error": "invalid_argument", "field", "detail"} without calling
            the Supervisor.
        """
        return await _log_con_arranque(
            "sv_get_core_logs", "core", "/core", lines, boot, latest)

    @mcp.tool()
    async def sv_get_supervisor_logs(
        lines: int = 100, boot: int | str | None = None, latest: bool = False
    ) -> object:
        """Read the Supervisor's own log (read only).

        Secrets are redacted before the text is returned. If the log does not
        fit in the response size limit, the LAST lines that fit are returned
        with `truncated: true`, `lines_returned` and a hint. If the host has
        no systemd journal, the Supervisor returns its container log instead
        and ignores `boot` and `latest`.

        Args:
            lines: Number of lines (default 100, clamped to 1-1000).
            boot: Optional boot: an integer offset (0 = current boot, -1 = the
                previous one) or a boot ID from `sv_list_boots`.
            latest: Only the lines since the Supervisor container last
                started. Cannot be combined with `boot`.

        Returns:
            {"source": "supervisor", "route", "lines_requested", "redacted",
             "secrets_redacted", "network_redacted", "logs"}, plus `boot` or
            `latest` when used; or {"error": "invalid_argument", ...}.
        """
        return await _log_con_arranque(
            "sv_get_supervisor_logs", "supervisor", "/supervisor", lines, boot, latest)

    @mcp.tool()
    async def sv_get_plugin_logs(
        plugin: str,
        lines: int = 100,
        boot: int | str | None = None,
        latest: bool = False,
    ) -> object:
        """Read the log of a Supervisor plugin: `dns`, `audio` or `multicast`
        (read only).

        Secrets are redacted before the text is returned. If the log does not
        fit in the response size limit, the LAST lines that fit are returned
        with `truncated: true`, `lines_returned` and a hint.

        Args:
            plugin: `dns`, `audio` or `multicast` (lowercase).
            lines: Number of lines (default 100, clamped to 1-1000).
            boot: Optional boot: an integer offset (0 = current boot, -1 = the
                previous one) or a boot ID from `sv_list_boots`.
            latest: Only the lines since the plugin container last started.
                Cannot be combined with `boot`.

        Returns:
            {"source": "<plugin>", "route", "lines_requested", "redacted",
             "secrets_redacted", "network_redacted", "logs"}, plus `boot` or
            `latest` when used; or {"error": "invalid_argument", ...}.
        """
        try:
            plugin = validar_plugin(plugin)
        except ArgumentoInvalido as exc:
            return _invalido("sv_get_plugin_logs", exc)
        return await _log_con_arranque(
            "sv_get_plugin_logs", plugin, None, lines, boot, latest)

    @mcp.tool()
    async def sv_get_host_logs(
        lines: int = 100,
        boot: int | str | None = None,
        identifier: str | None = None,
    ) -> object:
        """Read the host's systemd journal (read only).

        Without `identifier`, the host's default services; with it, only that
        syslog identifier (list them with `sv_list_host_log_identifiers`, e.g.
        `kernel`, `NetworkManager`, `addon_<slug>`). There is no `latest` for
        the host. Secrets are redacted; Hermes' own container log
        (`addon_<Hermes slug>`) also gets the network redaction of
        `sv_get_addon_logs`. If the log does not fit in the response size
        limit, the LAST lines that fit are returned with `truncated: true`,
        `lines_returned` and a hint.

        Args:
            lines: Number of lines (default 100, clamped to 1-1000).
            boot: Optional boot: an integer offset (0 = current boot, -1 = the
                previous one) or a boot ID from `sv_list_boots`.
            identifier: Optional syslog identifier: 1-64 letters, digits, '.',
                '_', '@' or '-', not starting with '.'.

        Returns:
            {"source": "host", "route", "lines_requested", "redacted",
             "secrets_redacted", "network_redacted", "logs"}, plus `boot` and
            `identifier` when used; or {"error": "invalid_argument", ...}.
        """
        tool = "sv_get_host_logs"
        try:
            boot_n = normalizar_boot(boot)
            identifier = validar_identifier(identifier)
            ruta, plantilla = ruta_de_host(boot_n, identifier)
        except ArgumentoInvalido as exc:
            return _invalido(tool, exc)
        extra: dict[str, Any] = {}
        if boot_n is not None:
            extra["boot"] = boot_n
        if identifier is not None:
            extra["identifier"] = identifier
        return await _leer_log(
            tool, source="host", ruta=ruta, plantilla=plantilla,
            lines=acotar_lineas(lines), extra=extra,
            tapar_red=_identifier_de_hermes(identifier),
        )

    @mcp.tool()
    async def sv_list_host_log_identifiers(search: str | None = None) -> object:
        """List the syslog identifiers present in the host journal, sorted
        (read only). Use one as `identifier` in `sv_get_host_logs`.

        Args:
            search: Optional case-insensitive substring filter.

        Returns:
            {"count": N, "truncated": bool, "items": ["kernel", ...]}, plus
            `search` when given; `count` is how many items come back and, when
            cut, `total` says how many there were.
        """
        tool = "sv_list_host_log_identifiers"
        plantilla = "/host/logs/identifiers"
        try:
            data = await ha_client.sv_request("GET", plantilla)
        except HAConnectionError as exc:
            logger.info(_EVENTO, tool=tool, route=plantilla,
                        status=getattr(exc, "status", None), outcome="error")
            return _error(exc)
        brutos = data.get("identifiers") if isinstance(data, dict) else None
        if not isinstance(brutos, list):
            # Sin la clave, o con otra forma, no es «no hay identificadores»:
            # una lista vacía dada por buena engañaría al agente (FR-016).
            return _forma_inesperada(tool, plantilla)
        items = sorted(i for i in brutos if isinstance(i, str))
        if search:
            aguja = search.lower()
            items = [i for i in items if aguja in i.lower()]
        items = redact_structure(items)
        logger.info(_EVENTO, tool=tool, route=plantilla, count=len(items), outcome="ok")

        # Sobre común de la 1.2.0 (spec 018, FR-012): `count` es cuántos
        # `items` vienen; si se cortó, `total` dice cuántos había, como el
        # tope central (`recortar_a_bytes`).
        def construir(kept: list[str], cut: bool) -> dict[str, Any]:
            cabecera: dict[str, Any] = {}
            if search:
                cabecera["search"] = search
            if cut:
                cabecera["total"] = len(items)
                cabecera["hint"] = "Use search to narrow the list."
            return sobre_de_lista(kept, truncated=cut, **cabecera)

        return ajustar_lista_a_bytes(items, construir, response_max_bytes)

    @mcp.tool()
    async def sv_list_boots() -> object:
        """List the boots recorded in the host journal, from the current one
        (offset 0) to the oldest (read only). Use an `offset` or a `boot_id`
        as `boot` in the log tools.

        Returns:
            {"count": N, "truncated": bool,
             "items": [{"offset": 0, "boot_id": "<32 hex>"}, ...]}; when cut,
            `total` says how many there were.
        """
        tool = "sv_list_boots"
        plantilla = "/host/logs/boots"
        try:
            data = await ha_client.sv_request("GET", plantilla)
        except HAConnectionError as exc:
            logger.info(_EVENTO, tool=tool, route=plantilla,
                        status=getattr(exc, "status", None), outcome="error")
            return _error(exc)
        boots = data.get("boots") if isinstance(data, dict) else None
        if not isinstance(boots, dict):
            # El Supervisor da `{"boots": {"0": "<id>", ...}}`. Sin la clave o
            # con otra forma, error claro en vez de una lista vacía como si
            # estuviera bien, o de un `AttributeError` (FR-016).
            return _forma_inesperada(tool, plantilla)
        items: list[dict[str, Any]] = []
        for offset, boot_id in boots.items():
            # El Supervisor da las claves como texto («0», «-1»); una que no
            # sea un entero no es un desplazamiento que se pueda pedir.
            try:
                n = int(offset)
            except (TypeError, ValueError):
                continue
            items.append({"offset": n, "boot_id": boot_id})
        items.sort(key=lambda i: i["offset"], reverse=True)
        # Misma defensa en profundidad que el resto de respuestas JSON del
        # Supervisor (FR-016 para FR-006).
        items = redact_structure(items)
        logger.info(_EVENTO, tool=tool, route=plantilla, count=len(items), outcome="ok")

        # Sobre común de la 1.2.0 (spec 018, FR-012): `count` es cuántos
        # `items` vienen; si se cortó, `total` dice cuántos había, como el
        # tope central (`recortar_a_bytes`).
        def construir(kept: list[dict[str, Any]], cut: bool) -> dict[str, Any]:
            if cut:
                return sobre_de_lista(kept, truncated=True, total=len(items))
            return sobre_de_lista(kept)

        return ajustar_lista_a_bytes(items, construir, response_max_bytes)
