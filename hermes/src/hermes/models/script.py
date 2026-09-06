"""Modelos de scripts de Home Assistant."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ScriptConfig(BaseModel):
    """Modelo ligero para la configuración de scripts."""

    alias: str | None = None
    description: str | None = None
    icon: str | None = None
    mode: str | None = None
    max: int | None = None
    sequence: list[dict[str, Any]] | None = None
    variables: dict[str, Any] | None = None
    fields: dict[str, Any] | None = None
    trace: list[dict[str, Any]] | None = None

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
        "validate_default": True,
    }
