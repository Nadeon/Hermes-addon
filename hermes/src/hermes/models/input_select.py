"""Modelo de input_select de Home Assistant."""

from __future__ import annotations

from pydantic import BaseModel


class InputSelectConfig(BaseModel):
    """Configuración de un input_select (selector de opciones)."""

    name: str | None = None
    icon: str | None = None
    options: list[str] | None = None
    initial: str | None = None

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
        "validate_default": True,
    }
