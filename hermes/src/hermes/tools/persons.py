"""Hermes — Tools MCP para person de Home Assistant."""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.models.person import PersonConfig
from hermes.tools._common import (
    collection_delete_flow,
    collection_get_current,
    collection_update_flow,
    entity_exists,
    requires_ready,
)

logger = structlog.get_logger(__name__)

DOMAIN = "person"


def _entity_id_of(raw: str) -> str:
    return raw if raw.startswith(f"{DOMAIN}.") else f"{DOMAIN}.{raw}"


def _dump_config(model: PersonConfig) -> dict[str, Any]:
    return model.model_dump(exclude_none=True, by_alias=True, mode="json")


async def _validate_device_trackers(
    ha_client: HAClient, trackers: list[str] | None
) -> list[str]:
    """Devuelve la lista de device_trackers que NO existen en HA."""
    if not trackers:
        return []
    missing: list[str] = []
    for tracker in trackers:
        if not isinstance(tracker, str) or not tracker:
            missing.append(str(tracker))
            continue
        if not await entity_exists(ha_client, tracker):
            missing.append(tracker)
    return missing


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de person."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_list_persons() -> object:
        """Lista las persons disponibles.

        Usa `person/list` vía WS porque el state sólo expone la última
        localización conocida, no la lista de `device_trackers` configurados.
        """
        try:
            items = await ha_client.ws_collection_list(DOMAIN)
        except HAConnectionError as exc:
            logger.error("ha_list_persons_failed", error=str(exc))
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        return json.dumps(items, ensure_ascii=False, separators=(",", ":"))

    @mcp.tool()
    @ready
    async def ha_get_person(entity_id: str) -> object:
        """Devuelve la config persistida y el estado de una person."""
        try:
            config = await collection_get_current(ha_client, DOMAIN, entity_id)
            try:
                state = await ha_client.get_state(_entity_id_of(entity_id))
            except HAConnectionError:
                state = None
            return {"config": config, "state": state}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_get_person_failed",
                entity_id=entity_id,
                error=str(exc),
                exc_info=True,
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_create_person(
        name: str,
        device_trackers: list[str] | None = None,
        user_id: str | None = None,
        picture: str | None = None,
    ) -> object:
        """Crea una person vía WS `person/create`. No requiere token.

        La creación es no-destructiva (un nuevo person_id no sobrescribe
        nada), así que se omite el flujo de confirmación. HA deriva el
        object_id desde `slugify(name)`.
        """
        try:
            model = PersonConfig.model_validate(
                {
                    "name": name,
                    "device_trackers": device_trackers,
                    "user_id": user_id,
                    "picture": picture,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ha_create_person_validation_failed", error=str(exc))
            return {"error": f"config validation: {exc}"}

        missing = await _validate_device_trackers(ha_client, device_trackers)
        if missing:
            logger.warning("ha_create_person_trackers_missing", missing=missing)
            return {
                "error": "unknown_device_trackers",
                "missing": missing,
                "hint": "device_trackers must reference entities that already exist",
            }

        try:
            created = await ha_client.ws_collection_create(
                DOMAIN, _dump_config(model)
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("ha_create_person_failed", error=str(exc), exc_info=True)
            return {"error": f"{type(exc).__name__}: {exc}"}
        object_id = created.get("id") if isinstance(created, dict) else None
        logger.info("ha_create_person_ok", object_id=object_id)
        return {
            "result": "ok",
            "entity_id": f"{DOMAIN}.{object_id}" if object_id else None,
            "config": created,
        }

    @mcp.tool()
    @ready
    async def ha_update_person(
        entity_id: str,
        config: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Modifica una person vía WS. Preview + token en el flujo dual."""
        try:
            model = PersonConfig.model_validate(config)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ha_update_person_validation_failed",
                entity_id=entity_id,
                error=str(exc),
            )
            return {"error": f"config validation: {exc}"}

        if model.device_trackers is not None:
            missing = await _validate_device_trackers(
                ha_client, model.device_trackers
            )
            if missing:
                logger.warning(
                    "ha_update_person_trackers_missing",
                    entity_id=entity_id,
                    missing=missing,
                )
                return {
                    "error": "unknown_device_trackers",
                    "missing": missing,
                    "hint": "device_trackers must reference entities that already exist",
                }

        return await collection_update_flow(
            ha_client,
            DOMAIN,
            entity_id,
            _dump_config(model),
            "ha_update_person",
            confirmation_token,
            logger,
        )

    @mcp.tool()
    @ready
    async def ha_delete_person(
        entity_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina una person vía WS. Siempre requiere `confirmation_token`."""
        return await collection_delete_flow(
            ha_client,
            DOMAIN,
            entity_id,
            "ha_delete_person",
            confirmation_token,
            logger,
        )
