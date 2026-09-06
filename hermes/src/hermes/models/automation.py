"""Modelos de automations de Home Assistant."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator


class AutomationConfig(BaseModel):
    """Modelo ligero para configuración de automatizaciones.

    Acepta como entrada tanto las claves legacy (`trigger`, `condition`,
    `action`) como las modernas (`triggers`, `conditions`, `actions`), y
    normaliza a las modernas antes del dump. HA rechaza POSTs con ambas
    formas coexistiendo ("Cannot specify both").
    """

    id: str | None = None
    alias: str | None = None
    description: str | None = None
    mode: str | None = None
    triggers: list[dict[str, Any]] | None = None
    conditions: list[dict[str, Any]] | None = None
    actions: list[dict[str, Any]] | None = None
    variables: dict[str, Any] | None = None

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
        "validate_default": True,
    }

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        for legacy, modern in (
            ("trigger", "triggers"),
            ("condition", "conditions"),
            ("action", "actions"),
        ):
            if legacy in out:
                legacy_val = out.pop(legacy)
                if out.get(modern) is None:
                    out[modern] = legacy_val
        return out
