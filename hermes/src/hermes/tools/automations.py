"""Hermes — Tools MCP para automations de Home Assistant."""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.models.automation import AutomationConfig
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    validate_confirmation_token,
)
from hermes.tools.ha import classify_saved_config
from hermes.tools._common import (
    guarded_entity_invoke,
    guarded_reload,
    entity_exists,
    not_found_response,
    requires_ready,
)


def _dump_config(model: AutomationConfig) -> dict[str, Any]:
    """Serializa el modelo sin claves null y con nombres modernos."""
    return model.model_dump(exclude_none=True, by_alias=True, mode="json")

logger = structlog.get_logger(__name__)


async def _resolve_automation_config_id(
    ha_client: HAClient,
    automation_id: str,
) -> str:
    """Resuelve el id interno que usa el endpoint REST de config.

    Acepta tanto el entity_id (`automation.cocina`) como el id interno
    crudo (`1689234567890`). Si se pasa entity_id, busca
    `attributes.id` en el state. Si no se encuentra, devuelve el valor
    original y deja que HA responda 404 — la semántica de "no existe"
    queda a cargo de `config_read`.
    """
    if not automation_id.startswith("automation."):
        return automation_id

    state = await ha_client.get_state(automation_id)
    if isinstance(state, dict):
        attrs = state.get("attributes") or {}
        if isinstance(attrs, dict):
            internal_id = attrs.get("id")
            if isinstance(internal_id, str) and internal_id:
                return internal_id
    logger.warning(
        "automation_id_resolve_failed",
        input=automation_id,
        reason="no_attributes_id_in_state",
        state_present=state is not None,
    )
    return automation_id


def _compact_automation(state: dict[str, Any]) -> dict[str, Any]:
    compacted = {
        "entity_id": state.get("entity_id"),
        "state": state.get("state"),
        "attributes": state.get("attributes", {}),
    }
    if isinstance(compacted["attributes"], dict):
        compacted["attributes"] = {
            k: v
            for k, v in compacted["attributes"].items()
            if v is not None
        }
    return compacted


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de automations."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_list_automations() -> object:
        """Lista las automatizaciones de Home Assistant con su estado actual.

        Devuelve JSON con `entity_id`, `state` y los `attributes` no nulos de
        cada `automation.*`. Para la configuración persistida de una en
        concreto, usa ha_get_automation.
        """
        states = await ha_client.get_states()
        automations = [
            _compact_automation(state)
            for state in states
            if isinstance(state, dict)
            and isinstance(state.get("entity_id"), str)
            and state["entity_id"].startswith("automation.")
        ]
        return json.dumps(automations, ensure_ascii=False, separators=(",", ":"))

    @mcp.tool()
    @ready
    async def ha_get_automation(automation_id: str) -> object:
        """Devuelve la configuración persistida y el estado de una automatización.

        Acepta entity_id (`automation.cocina`) o id interno crudo. La config
        se lee vía REST desde `/api/config/automation/config/{id}`. Si la
        automatización no tiene config editable (ej. creada en YAML sin `id`),
        devuelve solo el estado.
        """
        try:
            config_id = await _resolve_automation_config_id(ha_client, automation_id)
            try:
                config = await ha_client.config_read("automation", config_id)
            except HAConnectionError as exc:
                logger.warning(
                    "automation_config_read_ha_error",
                    config_id=config_id,
                    error=str(exc),
                )
                config = None

            try:
                state = await ha_client.get_state(automation_id)
            except HAConnectionError:
                state = None
            return {"config": config, "state": state}
        except Exception as exc:
            logger.error(
                "ha_get_automation_failed",
                automation_id=automation_id,
                error=str(exc),
                exc_info=True,
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_create_or_update_automation(
        automation_id: str,
        config: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Crea o actualiza la configuración de una automatización.

        Si no se suministra `confirmation_token`, devuelve un preview y un
        token para confirmar la acción. Tras el save, HA recarga
        automáticamente la automatización (post_write_hook → automation.reload);
        no es necesario llamar a `ha_reload_automations` a mano.
        """
        try:
            normalized_config = _dump_config(AutomationConfig.model_validate(config))
        except Exception as exc:
            logger.warning(
                "ha_create_or_update_automation_validation_failed",
                automation_id=automation_id,
                error=str(exc),
            )
            return {"error": f"config validation: {exc}"}

        args = {
            "automation_id": automation_id,
            "config": normalized_config,
        }

        if not confirmation_token:
            try:
                config_id = await _resolve_automation_config_id(ha_client, automation_id)
                try:
                    current = await ha_client.config_read("automation", config_id)
                except HAConnectionError as exc:
                    logger.warning(
                        "ha_create_or_update_automation_preview_read_failed",
                        config_id=config_id,
                        error=str(exc),
                    )
                    current = None
                preview = {
                    "automation_id": automation_id,
                    "config_id": config_id,
                    "current": current,
                    "new": normalized_config,
                }
                return await create_confirmation_token(
                    "ha_create_or_update_automation",
                    args,
                    preview=preview,
                )
            except Exception as exc:
                logger.error(
                    "ha_create_or_update_automation_preview_failed",
                    automation_id=automation_id,
                    error=str(exc),
                    exc_info=True,
                )
                return {"error": f"{type(exc).__name__}: {exc}"}

        valid, error = await validate_confirmation_token(
            confirmation_token,
            "ha_create_or_update_automation",
            args,
        )
        if not valid:
            logger.warning(
                "ha_create_or_update_automation_token_invalid",
                automation_id=automation_id,
                reason=error,
            )
            return {"error": error}

        try:
            config_id = await _resolve_automation_config_id(ha_client, automation_id)
            result = await ha_client.config_save(
                "automation",
                config_id,
                normalized_config,
            )
            # Clasificar de inmediato: sin esto, una automatización recién
            # guardada no quedaría restringida hasta reiniciar el add-on.
            classify_saved_config(automation_id if automation_id.startswith("automation.") else f"automation.{automation_id}", normalized_config)
            await complete_confirmation_token(
                confirmation_token,
                success=True,
                result=result,
            )
            logger.info(
                "ha_create_or_update_automation_ok",
                automation_id=automation_id,
                config_id=config_id,
            )
            return result
        except Exception as exc:
            logger.error(
                "ha_create_or_update_automation_failed",
                automation_id=automation_id,
                error=str(exc),
                exc_info=True,
            )
            await complete_confirmation_token(
                confirmation_token,
                success=False,
                error=str(exc),
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_delete_automation(
        automation_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina una automatización de Home Assistant.

        Esta operación siempre requiere `confirmation_token`.
        Si no se pasa token, devuelve un preview con la config actual y un
        token para confirmar. Tras el delete, HA recarga automáticamente.

        Ejemplo:
            preview = await ha_delete_automation("automation.cocina")
            result = await ha_delete_automation(
                "automation.cocina",
                confirmation_token=preview["confirmation_token"],
            )
        """
        args = {"automation_id": automation_id}

        if not confirmation_token:
            try:
                config_id = await _resolve_automation_config_id(ha_client, automation_id)
                try:
                    current = await ha_client.config_read("automation", config_id)
                except HAConnectionError as exc:
                    logger.warning(
                        "ha_delete_automation_preview_read_failed",
                        config_id=config_id,
                        error=str(exc),
                    )
                    current = None
                preview = {
                    "automation_id": automation_id,
                    "config_id": config_id,
                    "current": current,
                }
                return await create_confirmation_token(
                    "ha_delete_automation",
                    args,
                    preview=preview,
                )
            except Exception as exc:
                logger.error(
                    "ha_delete_automation_preview_failed",
                    automation_id=automation_id,
                    error=str(exc),
                    exc_info=True,
                )
                return {"error": f"{type(exc).__name__}: {exc}"}

        valid, error = await validate_confirmation_token(
            confirmation_token,
            "ha_delete_automation",
            args,
        )
        if not valid:
            logger.warning(
                "ha_delete_automation_token_invalid",
                automation_id=automation_id,
                reason=error,
            )
            return {"error": error}

        try:
            config_id = await _resolve_automation_config_id(ha_client, automation_id)
            result = await ha_client.config_delete("automation", config_id)
            await complete_confirmation_token(
                confirmation_token,
                success=True,
                result=result,
            )
            logger.info(
                "ha_delete_automation_ok",
                automation_id=automation_id,
                config_id=config_id,
                found=result is not None,
            )
            return result if result is not None else {"result": "not_found"}
        except Exception as exc:
            logger.error(
                "ha_delete_automation_failed",
                automation_id=automation_id,
                error=str(exc),
                exc_info=True,
            )
            await complete_confirmation_token(
                confirmation_token,
                success=False,
                error=str(exc),
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_enable_automation(automation_id: str) -> object:
        """Activa una automatización mediante el servicio `automation.turn_on`.

        Ejemplo:
            await ha_enable_automation("automation.cocina")
        """
        return await ha_client.call_service(
            "automation",
            "turn_on",
            {"entity_id": automation_id},
        )

    @mcp.tool()
    @ready
    async def ha_disable_automation(automation_id: str) -> object:
        """Desactiva una automatización mediante el servicio `automation.turn_off`.

        Ejemplo:
            await ha_disable_automation("automation.cocina")
        """
        return await ha_client.call_service(
            "automation",
            "turn_off",
            {"entity_id": automation_id},
        )

    @mcp.tool()
    @ready
    async def ha_trigger_automation(
        automation_id: str,
        variables: dict[str, Any] | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Dispara una automatización de Home Assistant."""
        if not await entity_exists(ha_client, automation_id):
            logger.warning("ha_trigger_automation_not_found", automation_id=automation_id)
            return not_found_response(automation_id)
        return await guarded_entity_invoke(
            ha_client,
            "automation",
            "trigger",
            automation_id,
            "ha_trigger_automation",
            confirmation_token,
            {"variables": variables} if variables is not None else None,
        )

    @mcp.tool()
    @ready
    async def ha_reload_automations(
        confirmation_token: str | None = None,
    ) -> object:
        """Recarga las automatizaciones en Home Assistant.

        Requiere `confirmation_token`. Una recarga activa el YAML tal y
        como esté en /config en ese instante, así que es el paso que
        materializa cualquier escritura previa: el servicio
        `automation.reload` está en la denylist justo por eso.
        """
        return await guarded_reload(
            ha_client, "automation", "ha_reload_automations", confirmation_token, "las automatizaciones"
        )
