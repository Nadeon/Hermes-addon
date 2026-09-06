"""Modelo de timer de Home Assistant."""

from __future__ import annotations

from pydantic import BaseModel


class TimerConfig(BaseModel):
    """Configuración de un timer (temporizador persistente)."""

    name: str | None = None
    icon: str | None = None
    duration: str | None = None  # "HH:MM:SS" o segundos como str
    restore: bool | None = None

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
        "validate_default": True,
    }
