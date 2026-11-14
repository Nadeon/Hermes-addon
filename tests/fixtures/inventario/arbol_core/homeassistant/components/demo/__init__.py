"""Componente inventado para los tests del extractor (spec 011, T038).

No es código de Home Assistant ni se importa nunca: el extractor solo lo lee
con `ast`. Si alguien lo importara, la primera línea ejecutable lo delata.
"""

raise RuntimeError("el extractor no debe importar el código que lee")

import probatio as vol  # noqa: E402

from homeassistant.components import websocket_api  # noqa: E402
from homeassistant.helpers import collection  # noqa: E402

from .const import DOMAIN, TIPO_IMPORTADO  # noqa: E402


@websocket_api.websocket_command({vol.Required("type"): "demo/listar"})
def listar(hass, connection, msg):
    """Tipo literal."""


@websocket_api.websocket_command({vol.Required("type"): TIPO_IMPORTADO, "x": str})
def importado(hass, connection, msg):
    """Tipo en una constante de otro módulo."""


@websocket_api.websocket_command({"type": f"{DOMAIN}/con_fstring"})
def con_fstring(hass, connection, msg):
    """Clave sin `Required` y tipo en un f-string con una constante."""


ESQUEMA = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {vol.Required("type"): "demo/extendido", vol.Optional("type_de_dato"): str}
)

# No es un comando: un esquema cualquiera con un campo `type`.
OTRO = vol.Schema({vol.Required("type"): "demo/no_es_comando"})


def preparar(hass, coleccion):
    collection.DictStorageCollectionWebsocket(
        coleccion, "demo_coleccion", "demo", {}, {}
    ).async_setup(hass)
