"""Modelo de input_datetime de Home Assistant."""

from __future__ import annotations

from pydantic import BaseModel


class InputDatetimeConfig(BaseModel):
    """Configuración de un input_datetime (fecha/hora/ambos)."""

    name: str | None = None
    icon: str | None = None
    has_date: bool | None = None
    has_time: bool | None = None
    initial: str | None = None

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
        "validate_default": True,
    }
