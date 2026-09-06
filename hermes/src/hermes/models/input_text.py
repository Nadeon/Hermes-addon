"""Modelo de input_text de Home Assistant."""

from __future__ import annotations

from pydantic import BaseModel


class InputTextConfig(BaseModel):
    """Configuración de un input_text (cadena con longitud y patrón)."""

    name: str | None = None
    icon: str | None = None
    min: int | None = None
    max: int | None = None
    initial: str | None = None
    pattern: str | None = None
    mode: str | None = None  # "text" o "password"

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
        "validate_default": True,
    }
