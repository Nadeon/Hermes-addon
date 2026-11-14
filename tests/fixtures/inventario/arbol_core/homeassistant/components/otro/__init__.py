"""Otro componente inventado: una colección con un comando propio (T038)."""

import probatio as vol

from homeassistant.components import websocket_api
from homeassistant.helpers.collection import StorageCollectionWebsocket

PREFIJO = "otro/elementos"


class OtroWebsocket(StorageCollectionWebsocket):
    def async_setup(self, hass):
        super().async_setup(hass)
        websocket_api.async_register_command(
            hass,
            f"{self.api_prefix}/get",
            self.ws_get,
            websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
                {vol.Required("type"): f"{self.api_prefix}/get"}
            ),
        )


def preparar(hass, coleccion):
    OtroWebsocket(coleccion, PREFIJO, "elemento", {}, {}).async_setup(hass)
