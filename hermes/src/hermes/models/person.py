"""Modelo de person de Home Assistant."""

from __future__ import annotations

from pydantic import BaseModel


class PersonConfig(BaseModel):
    """Configuración de una person.

    HA registra persons con `PersonStorageCollectionWebsocket("person", ...)`.
    Campos conocidos: name, device_trackers (lista de entity_ids), user_id
    (opcional — asocia con usuario del sistema), picture (URL o path).
    `extra="allow"` para preservar cualquier campo adicional que HA introduzca.
    """

    name: str | None = None
    device_trackers: list[str] | None = None
    user_id: str | None = None
    picture: str | None = None

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
        "validate_default": True,
    }
