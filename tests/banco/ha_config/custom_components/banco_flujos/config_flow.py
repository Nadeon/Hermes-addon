"""Flujos de `banco_flujos`: descubrimiento, `user`, `reconfigure`, `reauth` y subentries.

Configuración del banco de pruebas de Core (spec 016): corre dentro de la HA
de prueba del CI. Nunca se empaqueta ni llega al add-on. Sin red.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import probatio

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import DOMAIN, NOMBRE_INICIAL, SUBENTRY_ELEMENTO

CAMPO = "valor"
# Campo de contraseña del reconfigure (tramo B): su nombre es inocente a
# propósito, para que solo el selector de contraseña lo delate. Su valor
# actual va como `default` del formulario, como hacen muchas integraciones:
# es lo que Hermes tiene que tapar.
CLAVE = "clave"


class BancoFlujosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Una entrada por el flujo `user` o al confirmar un descubrimiento."""

    VERSION = 1

    _nombre: str = NOMBRE_INICIAL

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Un tipo de subentry, con `user` y `reconfigure`."""
        return {SUBENTRY_ELEMENTO: ElementoSubentryFlow}

    async def async_step_integration_discovery(
        self, discovery_info: dict[str, Any]
    ) -> ConfigFlowResult:
        """Descubrimiento con unique_id: se puede ignorar."""
        await self.async_set_unique_id(discovery_info["unique_id"])
        self._abort_if_unique_id_configured()
        self._nombre = discovery_info.get("name") or NOMBRE_INICIAL
        self.context["title_placeholders"] = {"name": self._nombre}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirmar el descubrimiento (sin campos)."""
        if user_input is not None:
            return self.async_create_entry(title=self._nombre, data={CAMPO: "descubierto"})
        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"name": self._nombre},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Un campo y una entrada nueva cada vez (sin unique_id)."""
        if user_input is not None:
            return self.async_create_entry(title="Banco flujos", data={CAMPO: user_input[CAMPO]})
        return self.async_show_form(
            step_id="user",
            data_schema=probatio.Schema({probatio.Required(CAMPO, default="inicial"): str}),
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Reautenticación (tramo C): la abre el servicio `pedir_reauth`."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pide la clave nueva (selector de contraseña) y recarga la entrada."""
        if user_input is not None:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data_updates={CLAVE: user_input[CLAVE]}
            )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CLAVE): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Cambia el dato de la entrada y la recarga."""
        entrada = self._get_reconfigure_entry()
        if user_input is not None:
            return self.async_update_reload_and_abort(
                entrada,
                data_updates={CAMPO: user_input[CAMPO], CLAVE: user_input.get(CLAVE, "")},
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CAMPO, default=entrada.data.get(CAMPO, "")): str,
                    probatio.Optional(CLAVE, default=entrada.data.get(CLAVE, "")): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
        )


class ElementoSubentryFlow(ConfigSubentryFlow):
    """Subentry `elemento`: un título y un valor; cada una crea un sensor."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Crear un elemento."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input["nombre"], data={CAMPO: user_input[CAMPO]}
            )
        return self.async_show_form(
            step_id="user",
            data_schema=probatio.Schema(
                {
                    probatio.Required("nombre"): str,
                    probatio.Required(CAMPO, default="1"): str,
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Cambiar el título y el valor de un elemento."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=user_input["nombre"],
                data_updates={CAMPO: user_input[CAMPO]},
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=probatio.Schema(
                {
                    probatio.Required("nombre", default=subentry.title): str,
                    probatio.Required(CAMPO, default=subentry.data.get(CAMPO, "")): str,
                }
            ),
        )
