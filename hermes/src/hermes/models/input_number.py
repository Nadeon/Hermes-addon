"""Modelo de input_number de Home Assistant."""

from __future__ import annotations

from pydantic import BaseModel


class InputNumberConfig(BaseModel):
    """Configuración de un input_number (número con min/max/step)."""

    name: str | None = None
    icon: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    initial: float | None = None
    mode: str | None = None  # "box" o "slider"
    unit_of_measurement: str | None = None

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
        "validate_default": True,
    }
