"""Modelo de input_button de Home Assistant."""

from __future__ import annotations

from pydantic import BaseModel


class InputButtonConfig(BaseModel):
    """Configuración de un input_button (botón stateless, útil para scripts/automations)."""

    name: str | None = None
    icon: str | None = None

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
        "validate_default": True,
    }
