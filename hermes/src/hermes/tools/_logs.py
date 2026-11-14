"""Validación y rutas comunes de las tools de logs del Supervisor (spec 013).

Lo usan `tools/system_logs.py` (Core, Supervisor, plugins y host) y
`tools/addons.py` (`sv_get_addon_logs` con `boot` y `latest`). Va en un módulo
aparte porque `system_logs` importa de `addons` la detección del propio Hermes
y el recorte por el final: si `addons` importara de `system_logs`, habría un
ciclo.

POR QUÉ SE VALIDA ANTES DE LLAMAR (research R-2, principio III)
---------------------------------------------------------------
El Supervisor acepta cualquier texto como identificador de arranque y lo pasa
al journal, y el `identifier` del host va dentro de la ruta. Validar la forma
antes evita mandar basura y cierra cualquier rareza de ruta; la segunda capa
sigue siendo `_assert_safe_request_path` del cliente. Los mensajes dicen la
regla y nunca copian el valor rechazado (principio II): un agente podría pasar
ahí algo que no debe acabar en una respuesta ni en un log.
"""

from __future__ import annotations

import re
from typing import Any

from hermes.identifiers import InvalidIdentifier, validate_path_segment

# Rango del desplazamiento de arranque: sobra para cualquier journal real y
# evita enteros enormes (research R-2).
_BOOT_MAX = 999
_BOOT_ENTERO = re.compile(r"^-?[0-9]{1,3}$")
_BOOT_ID = re.compile(r"^[0-9A-Fa-f]{32}$")
# Identificadores de syslog habituales (`kernel`, `systemd-journald`,
# `NetworkManager`, `addon_<slug>`). No puede empezar por punto (ni `.` ni
# `..`) ni llevar `/`, `%`, `?`, `#` o espacios.
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_@-][A-Za-z0-9._@-]{0,63}$")

PLUGINS = ("dns", "audio", "multicast")

DETALLE_BOOT = (
    "boot must be an integer offset between -999 and 999 or a 32-character "
    "hexadecimal boot ID."
)
DETALLE_LATEST = "latest and boot cannot be combined."
DETALLE_IDENTIFIER = (
    "identifier must be 1-64 characters of letters, digits, '.', '_', '@' or "
    "'-', not starting with '.'."
)
DETALLE_PLUGIN = f"plugin must be one of: {', '.join(PLUGINS)}."

LINEAS_MAX = 1000


class ArgumentoInvalido(ValueError):
    """Un argumento no cumple su regla. `campo` y `detalle` van a la respuesta."""

    def __init__(self, campo: str, detalle: str) -> None:
        super().__init__(detalle)
        self.campo = campo
        self.detalle = detalle

    def respuesta(self) -> dict[str, Any]:
        return {"error": "invalid_argument", "field": self.campo, "detail": self.detalle}


def acotar_lineas(lines: int) -> int:
    """`lines` en [1, 1000], como `sv_get_addon_logs` desde la 1.1.2."""
    return min(max(1, lines), LINEAS_MAX)


def normalizar_boot(boot: Any) -> int | str | None:
    """`None`, un desplazamiento entero (-999…999) o un id de 32 hex en
    minúsculas. Cualquier otra cosa → `ArgumentoInvalido`.

    Un `bool` es un `int` en Python, pero `boot=True` no es un desplazamiento:
    se rechaza. Un texto con forma de entero (`"-1"`) vale lo mismo que el
    entero: es lo que manda un cliente que serializa todo como texto.
    """
    if boot is None:
        return None
    if isinstance(boot, bool):
        raise ArgumentoInvalido("boot", DETALLE_BOOT)
    if isinstance(boot, int):
        if -_BOOT_MAX <= boot <= _BOOT_MAX:
            return boot
        raise ArgumentoInvalido("boot", DETALLE_BOOT)
    if isinstance(boot, str):
        if _BOOT_ENTERO.fullmatch(boot):
            return int(boot)
        if _BOOT_ID.fullmatch(boot):
            # El journal guarda los ids en minúsculas.
            return boot.lower()
    raise ArgumentoInvalido("boot", DETALLE_BOOT)


def comprobar_latest(boot: int | str | None, latest: bool) -> None:
    """No hay ruta del Supervisor que combine `latest` y un arranque."""
    if latest and boot is not None:
        raise ArgumentoInvalido("latest", DETALLE_LATEST)


def validar_identifier(identifier: Any) -> str | None:
    if identifier is None:
        return None
    if isinstance(identifier, str) and _IDENTIFIER.fullmatch(identifier):
        return identifier
    raise ArgumentoInvalido("identifier", DETALLE_IDENTIFIER)


def validar_plugin(plugin: Any) -> str:
    # Exacto y en minúsculas: son segmentos de ruta del Supervisor. `cli` y
    # `observer` no tienen log en el Supervisor 2026.11.0.
    if isinstance(plugin, str) and plugin in PLUGINS:
        return plugin
    raise ArgumentoInvalido("plugin", DETALLE_PLUGIN)


def _segmento(valor: int | str, campo: str, detalle: str) -> str:
    """Segunda capa, la común de Hermes: nada que cambie la ruta de destino
    (`/`, `..`, `%`, `?`, `#`, espacios). Las reglas de arriba ya lo excluyen;
    esta es la red por si una de ellas se relaja algún día."""
    try:
        return validate_path_segment(str(valor), field=campo)
    except InvalidIdentifier:
        raise ArgumentoInvalido(campo, detalle) from None


def ruta_de_log(
    base: str, plantilla_base: str, boot: int | str | None, latest: bool
) -> tuple[str, str]:
    """(ruta real, plantilla) del log de `base` según `boot` y `latest`.

    `base` ya viene validada (una constante, o con el slug validado). La
    plantilla es la forma de la tabla de comandos (`{bootid}`, `{app}`): es lo
    que va a la respuesta y al log de Hermes, nunca el id concreto.
    """
    if latest:
        return f"{base}/logs/latest", f"{plantilla_base}/logs/latest"
    if boot is not None:
        segmento = _segmento(boot, "boot", DETALLE_BOOT)
        return f"{base}/logs/boots/{segmento}", f"{plantilla_base}/logs/boots/{{bootid}}"
    return f"{base}/logs", f"{plantilla_base}/logs"


def ruta_de_plugin(plugin: str, boot: int | str | None, latest: bool) -> tuple[str, str]:
    """Como `ruta_de_log` para un plugin ya validado con `validar_plugin`."""
    base = f"/{_segmento(plugin, 'plugin', DETALLE_PLUGIN)}"
    return ruta_de_log(base, base, boot, latest)


def ruta_de_host(boot: int | str | None, identifier: str | None) -> tuple[str, str]:
    """(ruta real, plantilla) del journal del host. No hay `latest` en el host."""
    ruta, plantilla = "/host/logs", "/host/logs"
    if boot is not None:
        ruta += f"/boots/{_segmento(boot, 'boot', DETALLE_BOOT)}"
        plantilla += "/boots/{bootid}"
    if identifier is not None:
        ruta += f"/identifiers/{_segmento(identifier, 'identifier', DETALLE_IDENTIFIER)}"
        plantilla += "/identifiers/{identifier}"
    return ruta, plantilla
