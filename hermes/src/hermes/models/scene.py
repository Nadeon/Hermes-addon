"""Modelos de scenes de Home Assistant."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SceneConfig(BaseModel):
    """Modelo ligero para la configuración de scenes.

    Las scenes editables en HA se definen con `name`, `icon` opcional y un
    diccionario `entities` que mapea `entity_id` a su estado (string) o a
    un diccionario con `state` y atributos. El modelo es permisivo con
    `extra = "allow"` para soportar variantes.
    """

    name: str | None = None
    icon: str | None = None
    entities: dict[str, Any] | None = None

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
        "validate_default": True,
    }
