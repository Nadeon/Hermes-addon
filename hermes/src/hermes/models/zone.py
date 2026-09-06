"""Modelo de zone de Home Assistant."""

from __future__ import annotations

from pydantic import BaseModel, field_validator


class ZoneConfig(BaseModel):
    """Configuración de una zone (área geográfica circular).

    HA registra zones con `DictStorageCollectionWebsocket("zone", ...)`. Campos
    conocidos: name, latitude, longitude, radius (metros), passive, icon. El
    modelo permite extras por si HA añade campos en el futuro.
    """

    name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    radius: float | None = None
    passive: bool | None = None
    icon: str | None = None

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
        "validate_default": True,
    }

    @field_validator("latitude")
    @classmethod
    def _lat_range(cls, v: float | None) -> float | None:
        if v is not None and not -90.0 <= v <= 90.0:
            raise ValueError("latitude must be in [-90, 90]")
        return v

    @field_validator("longitude")
    @classmethod
    def _lon_range(cls, v: float | None) -> float | None:
        if v is not None and not -180.0 <= v <= 180.0:
            raise ValueError("longitude must be in [-180, 180]")
        return v

    @field_validator("radius")
    @classmethod
    def _radius_positive(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("radius must be > 0")
        return v
