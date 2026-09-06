"""Modelo de input_boolean de Home Assistant."""

from __future__ import annotations

from pydantic import BaseModel


class InputBooleanConfig(BaseModel):
    """Configuración de un input_boolean (toggle simple)."""

    name: str | None = None
    icon: str | None = None
    initial: bool | None = None

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
        "validate_default": True,
    }
