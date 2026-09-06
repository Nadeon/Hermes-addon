"""Modelo de schedule de Home Assistant."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScheduleRange(BaseModel):
    """Rango horario de un schedule (`from`/`to` en formato HH:MM[:SS])."""

    from_: str | None = Field(default=None, alias="from")
    to: str | None = None

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
        "validate_default": True,
    }


class ScheduleConfig(BaseModel):
    """Configuración de un schedule (rangos horarios por día de la semana).

    Cada día es una lista de rangos `{from, to}`. Días omitidos se tratan
    como vacíos (helper inactivo ese día).
    """

    name: str | None = None
    icon: str | None = None
    monday: list[ScheduleRange] | None = None
    tuesday: list[ScheduleRange] | None = None
    wednesday: list[ScheduleRange] | None = None
    thursday: list[ScheduleRange] | None = None
    friday: list[ScheduleRange] | None = None
    saturday: list[ScheduleRange] | None = None
    sunday: list[ScheduleRange] | None = None

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
        "validate_default": True,
    }
