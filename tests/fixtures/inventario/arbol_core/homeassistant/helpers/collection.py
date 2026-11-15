"""Colecciones de almacenamiento inventadas para los tests del extractor
(spec 011, T038). Solo la forma: los comandos salen de `self.api_prefix`."""

import probatio as vol

from homeassistant.components import websocket_api


class StorageCollectionWebsocket:
    def __init__(self, storage_collection, api_prefix, model_name, create, update):
        self.api_prefix = api_prefix

    def async_setup(self, hass):
        for sufijo in ("list", "create", "update", "delete", "subscribe"):
            pass
        websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
            {vol.Required("type"): f"{self.api_prefix}/list"})
        websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
            {vol.Required("type"): f"{self.api_prefix}/create"})
        websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
            {vol.Required("type"): f"{self.api_prefix}/update"})
        websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
            {vol.Required("type"): f"{self.api_prefix}/delete"})
        websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
            {vol.Required("type"): f"{self.api_prefix}/subscribe"})


class DictStorageCollectionWebsocket(StorageCollectionWebsocket):
    pass
