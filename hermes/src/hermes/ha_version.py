"""Versión de Home Assistant en ejecución.

Algunas tools tienen que saber QUÉ comando WS usarán antes de ejecutar nada,
para que la preview de la confirmación diga la verdad: probar el comando nuevo
y caer al viejo ante `unknown_command` no permite anunciarlo de antemano. Por
eso se pregunta la versión y se decide por ella.

No hay caché: HA puede actualizarse sin que Hermes se reinicie, y una versión
guardada llevaría a elegir el comando equivocado.
"""

from __future__ import annotations

from typing import Any

from packaging.version import InvalidVersion, Version

from hermes.ha import HAConnectionError


async def ha_core_version(ha_client: Any) -> Version | None:
    """Devuelve la versión de HA o `None` si no se puede saber.

    Las versiones de desarrollo (`2026.12.0.dev0`) se reducen a su
    `base_version`: ya traen los cambios de esa versión, y compararlas tal cual
    las dejaría por debajo de la final. `None` significa «desconocida»; cada
    tool decide cómo negarse en ese caso en vez de adivinar.
    """
    try:
        config = await ha_client.ws_send({"type": "get_config"}, timeout_seconds=5)
    except (HAConnectionError, TimeoutError):
        return None
    if not isinstance(config, dict):
        return None
    texto = config.get("version")
    if not isinstance(texto, str):
        return None
    try:
        return Version(Version(texto).base_version)
    except InvalidVersion:
        # Durante el arranque HA puede responder cosas como «landingpage».
        return None


async def ha_at_least(ha_client: Any, minimo: str) -> bool | None:
    """`True`/`False` si HA es al menos `minimo`; `None` si la versión es desconocida."""
    version = await ha_core_version(ha_client)
    if version is None:
        return None
    return version >= Version(minimo)
