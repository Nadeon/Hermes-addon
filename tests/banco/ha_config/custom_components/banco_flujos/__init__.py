"""Integración de prueba `banco_flujos` del banco de Core (spec 016, research R-9).

ES CONFIGURACIÓN DEL BANCO, NO CÓDIGO DE HERMES: el job `banco-core` del CI
copia `tests/banco/ha_config/` al `/config` de una HA Core de prueba, sin red,
y esta carpeta va con ella. Nunca se empaqueta ni llega al add-on (FR-013 de
la 008). No tiene requisitos ni sale a internet; los textos son genéricos.
`manifest.json` y `translations/en.json` no admiten comentarios: este vale
para toda la carpeta.

Por qué existe: el banco no tiene red ni hardware, así que no hay nada que
descubrir, ni avisos reparables, ni integraciones con subentries o
reconfigure que se puedan crear sin red. `kitchen_sink` tiene parte de eso,
pero ni un descubrimiento con unique_id ni reconfigure de la entrada.

Qué ofrece:
- Al arrancar (`banco_flujos:` en configuration.yaml): un flujo de
  descubrimiento con unique_id fijo y dos avisos reparables con
  `translation_key` y marcadores.
- Servicios para que cada test prepare lo suyo: `banco_flujos.descubrir`
  (otro descubrimiento, con el unique_id que diga el test) y
  `banco_flujos.crear_avisos` (vuelve a crear los dos avisos).
- Una entrada se crea por el flujo `user` (un campo, sin red) y admite
  `reconfigure`; cada entrada admite subentries de tipo `elemento`, con un
  sensor y un dispositivo por subentry (sensor.py).
"""

from __future__ import annotations

import probatio

from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, discovery_flow
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.typing import ConfigType

from .const import (
    AVISO_PARA_ABORTAR,
    AVISO_REPARABLE,
    DOMAIN,
    NOMBRE_INICIAL,
    UNIQUE_ID_INICIAL,
)

PLATFORMS = [Platform.SENSOR]

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)

_ESQUEMA_DESCUBRIR = probatio.Schema(
    {
        probatio.Required("unique_id"): cv.string,
        probatio.Optional("name", default=NOMBRE_INICIAL): cv.string,
    }
)


def _descubrir(hass: HomeAssistant, unique_id: str, nombre: str) -> None:
    # El helper de descubrimiento de HA, como una integración de verdad: si HA
    # aún no ha arrancado, espera a que arranque.
    discovery_flow.async_create_flow(
        hass,
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data={"unique_id": unique_id, "name": nombre},
    )


def _crear_avisos(hass: HomeAssistant) -> None:
    async_create_issue(
        hass,
        DOMAIN,
        AVISO_REPARABLE,
        is_fixable=True,
        severity=IssueSeverity.WARNING,
        translation_key=AVISO_REPARABLE,
        translation_placeholders={"valor": "42"},
        data={"origen": "banco"},
    )
    async_create_issue(
        hass,
        DOMAIN,
        AVISO_PARA_ABORTAR,
        is_fixable=True,
        severity=IssueSeverity.WARNING,
        translation_key=AVISO_PARA_ABORTAR,
        translation_placeholders={"valor": "7"},
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Descubrimiento inicial, avisos y servicios del banco."""

    async def descubrir(call: ServiceCall) -> None:
        _descubrir(hass, call.data["unique_id"], call.data["name"])

    async def crear_avisos(call: ServiceCall) -> None:
        _crear_avisos(hass)

    hass.services.async_register(DOMAIN, "descubrir", descubrir, schema=_ESQUEMA_DESCUBRIR)
    hass.services.async_register(DOMAIN, "crear_avisos", crear_avisos)

    if DOMAIN in config:
        _descubrir(hass, UNIQUE_ID_INICIAL, NOMBRE_INICIAL)
        _crear_avisos(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Carga los sensores de las subentries."""
    # Las subentries con las que se cargó: el listener solo recarga si cambian
    # (crear o borrar una). Cambiar el título o las preferencias de la entrada
    # no recarga por su cuenta, así que lo que el banco ve al cambiar el sondeo
    # es la recarga de HA, no una de la integración.
    entry.runtime_data = frozenset(entry.subentries)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_al_cambiar))


async def _al_cambiar(hass: HomeAssistant, entry: ConfigEntry) -> None:
    if frozenset(entry.subentries) != entry.runtime_data:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Descarga los sensores."""
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
