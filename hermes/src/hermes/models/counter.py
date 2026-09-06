"""Modelo de counter de Home Assistant."""

from __future__ import annotations

from pydantic import BaseModel


class CounterConfig(BaseModel):
    """Configuración de un counter (contador persistente)."""

    name: str | None = None
    icon: str | None = None
    initial: int | None = None
    minimum: int | None = None
    maximum: int | None = None
    step: int | None = None
    restore: bool | None = None

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
        "validate_default": True,
    }
