"""Flujos de reparación de los avisos de `banco_flujos` (los usa el tramo C).

Configuración del banco de pruebas de Core (spec 016): corre dentro de la HA
de prueba del CI. Nunca se empaqueta ni llega al add-on.

Los dos avisos tienen el mismo flujo: un formulario de confirmación con un
campo opcional. Enviarlo termina en `create_entry` y HA borra el aviso; para
el segundo, el test abre el flujo y lo aborta.
"""

from __future__ import annotations

import probatio

from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.core import HomeAssistant


class ConfirmarArreglo(RepairsFlow):
    """Confirmar el arreglo, con una nota opcional."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Primer paso: el formulario de confirmación."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Al enviarlo, el aviso queda arreglado."""
        if user_input is not None:
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm",
            data_schema=probatio.Schema({probatio.Optional("nota"): str}),
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """El mismo flujo para los dos avisos."""
    return ConfirmarArreglo()
