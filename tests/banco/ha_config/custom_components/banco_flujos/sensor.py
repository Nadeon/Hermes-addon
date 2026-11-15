"""Un sensor y un dispositivo por subentry `elemento` de `banco_flujos`.

Configuración del banco de pruebas de Core (spec 016): corre dentro de la HA
de prueba del CI. Nunca se empaqueta ni llega al add-on.

Existen para que borrar una subentry (tramo B) borre algo que se pueda ver:
HA borra las entidades y los dispositivos con ese `config_subentry_id`.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, SUBENTRY_ELEMENTO


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Un sensor por subentry, atado a ella con `config_subentry_id`."""
    for subentry_id, subentry in config_entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_ELEMENTO:
            continue
        async_add_entities(
            [SensorElemento(subentry_id, subentry.title, subentry.data.get("valor"))],
            config_subentry_id=subentry_id,
        )


class SensorElemento(SensorEntity):
    """Sensor fijo: su valor es el de la subentry."""

    _attr_should_poll = False

    def __init__(self, subentry_id: str, titulo: str, valor: object) -> None:
        self._attr_unique_id = subentry_id
        self._attr_name = titulo
        self._attr_native_value = None if valor is None else str(valor)
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, subentry_id)}, name=titulo)
