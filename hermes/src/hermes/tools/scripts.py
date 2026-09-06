"""Hermes — Tools MCP para scripts de Home Assistant."""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.models.script import ScriptConfig
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


def _dump_config(model: ScriptConfig) -> dict[str, Any]:
    """Serializa el modelo sin claves null."""
    return model.model_dump(exclude_none=True, by_alias=True, mode="json")

logger = structlog.get_logger(__name__)


def _script_object_id(script_id: str) -> str:
    """Devuelve el object_id que usa el endpoint REST de config.

    Acepta `script.foo` o `foo` y normaliza al segundo. El endpoint
    REST `/api/config/script/config/{object_id}` no usa el entity_id.
    """
    if script_id.startswith("script."):
        return script_id[len("script.") :]
    return script_id


def _compact_script(state: dict[str, Any]) -> dict[str, Any]:
    attributes = state.get("attributes", {}) or {}
    return {
        "entity_id": state.get("entity_id"),
        "alias": attributes.get("friendly_name") or state.get("entity_id"),
        "state": state.get("state"),
        "last_triggered": attributes.get("last_triggered"),
        "mode": attributes.get("mode"),
    }


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de scripts."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_list_scripts() -> object:
        """Lista los scripts disponibles en Home Assistant.

        El estado `on`/`off` refleja si el script está ejecutándose ahora mismo,
        no si está habilitado o deshabilitado. Los scripts no tienen un
        toggle de activación como las automatizaciones.
        """
        states = await ha_client.get_states()
        scripts = [
            _compact_script(state)
            for state in states
            if isinstance(state, dict)
            and isinstance(state.get("entity_id"), str)
            and state["entity_id"].startswith("script.")
        ]
        return json.dumps(scripts, ensure_ascii=False, separators=(",", ":"))

    @mcp.tool()
    @ready
    async def ha_get_script(script_id: str) -> object:
        """Devuelve la configuración persistida y el estado de un script.

        Acepta entity_id (`script.saludar`) u object_id crudo. La config se
        lee vía REST desde `/api/config/script/config/{object_id}`.
        """
        try:
            object_id = _script_object_id(script_id)
            try:
                config = await ha_client.config_read("script", object_id)
            except HAConnectionError as exc:
                logger.warning(
                    "script_config_read_ha_error",
                    object_id=object_id,
                    error=str(exc),
                )
                config = None

            entity_id = (
                script_id if script_id.startswith("script.") else f"script.{script_id}"
            )
            try:
                state = await ha_client.get_state(entity_id)
            except HAConnectionError:
                state = None
            return {"config": config, "state": state}
        except Exception as exc:
            logger.error(
                "ha_get_script_failed",
                script_id=script_id,
                error=str(exc),
                exc_info=True,
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_create_or_update_script(
        script_id: str,
        config: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Crea o modifica un script en Home Assistant.

        Si no se suministra `confirmation_token`, devuelve un preview y un token
        para confirmar la acción. Tras el save, HA recarga automáticamente
        el script (post_write_hook → script.reload); no es necesario llamar a
        `ha_reload_scripts` a mano.
        """
        try:
            normalized_config = _dump_config(ScriptConfig.model_validate(config))
        except Exception as exc:
            logger.warning(
                "ha_create_or_update_script_validation_failed",
                script_id=script_id,
                error=str(exc),
            )
            return {"error": f"config validation: {exc}"}

        args = {
            "script_id": script_id,
            "config": normalized_config,
        }

        if not confirmation_token:
            try:
                object_id = _script_object_id(script_id)
                try:
                    current = await ha_client.config_read("script", object_id)
                except HAConnectionError as exc:
                    logger.warning(
                        "ha_create_or_update_script_preview_read_failed",
                        object_id=object_id,
                        error=str(exc),
                    )
                    current = None
                preview = {
                    "script_id": script_id,
                    "object_id": object_id,
                    "current": current,
                    "new": normalized_config,
                }
                return await create_confirmation_token(
                    "ha_create_or_update_script",
                    args,
                    preview=preview,
                )
            except Exception as exc:
                logger.error(
                    "ha_create_or_update_script_preview_failed",
                    script_id=script_id,
                    error=str(exc),
                    exc_info=True,
                )
                return {"error": f"{type(exc).__name__}: {exc}"}

        valid, error = await validate_confirmation_token(
            confirmation_token,
            "ha_create_or_update_script",
            args,
        )
        if not valid:
            logger.warning(
                "ha_create_or_update_script_token_invalid",
                script_id=script_id,
                reason=error,
            )
            return {"error": error}

        try:
            object_id = _script_object_id(script_id)
            result = await ha_client.config_save(
                "script",
                object_id,
                normalized_config,
            )
            # Clasificar de inmediato: sin esto, un script recién guardado
            # no quedaría restringido hasta reiniciar el add-on.
            classify_saved_config(script_id if script_id.startswith("script.") else f"script.{script_id}", normalized_config)
            await complete_confirmation_token(
                confirmation_token,
                success=True,
                result=result,
            )
            logger.info(
                "ha_create_or_update_script_ok",
                script_id=script_id,
                object_id=object_id,
            )
            return result
        except Exception as exc:
            logger.error(
                "ha_create_or_update_script_failed",
                script_id=script_id,
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
    async def ha_delete_script(
        script_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina un script de Home Assistant.

        Esta operación siempre requiere `confirmation_token`.
        Si no se pasa token, devuelve un preview con la config actual y un
        token para confirmar. Tras el delete, HA recarga automáticamente.
        """
        args = {"script_id": script_id}

        if not confirmation_token:
            try:
                object_id = _script_object_id(script_id)
                try:
                    current = await ha_client.config_read("script", object_id)
                except HAConnectionError as exc:
                    logger.warning(
                        "ha_delete_script_preview_read_failed",
                        object_id=object_id,
                        error=str(exc),
                    )
                    current = None
                preview = {
                    "script_id": script_id,
                    "object_id": object_id,
                    "current": current,
                }
                return await create_confirmation_token(
                    "ha_delete_script",
                    args,
                    preview=preview,
                )
            except Exception as exc:
                logger.error(
                    "ha_delete_script_preview_failed",
                    script_id=script_id,
                    error=str(exc),
                    exc_info=True,
                )
                return {"error": f"{type(exc).__name__}: {exc}"}

        valid, error = await validate_confirmation_token(
            confirmation_token,
            "ha_delete_script",
            args,
        )
        if not valid:
            logger.warning(
                "ha_delete_script_token_invalid",
                script_id=script_id,
                reason=error,
            )
            return {"error": error}

        try:
            object_id = _script_object_id(script_id)
            result = await ha_client.config_delete("script", object_id)
            await complete_confirmation_token(
                confirmation_token,
                success=True,
                result=result,
            )
            logger.info(
                "ha_delete_script_ok",
                script_id=script_id,
                object_id=object_id,
                found=result is not None,
            )
            return result if result is not None else {"result": "not_found"}
        except Exception as exc:
            logger.error(
                "ha_delete_script_failed",
                script_id=script_id,
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
    async def ha_run_script(
        script_id: str,
        variables: dict[str, Any] | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Ejecuta un script de Home Assistant con variables opcionales.

        Ejemplo:
            await ha_run_script(
                "script.saludar",
                variables={"greeting": "hola", "count": 3},
            )
        """
        entity_id = (
            script_id if script_id.startswith("script.") else f"script.{script_id}"
        )
        if not await entity_exists(ha_client, entity_id):
            logger.warning("ha_run_script_not_found", script_id=script_id)
            return not_found_response(entity_id)
        return await guarded_entity_invoke(
            ha_client,
            "script",
            "turn_on",
            entity_id,
            "ha_run_script",
            confirmation_token,
            {"variables": variables} if variables is not None else None,
        )

    @mcp.tool()
    @ready
    async def ha_reload_scripts(
        confirmation_token: str | None = None,
    ) -> object:
        """Recarga los scripts en Home Assistant.

        Requiere `confirmation_token`. Una recarga activa el YAML tal y
        como esté en /config en ese instante, así que es el paso que
        materializa cualquier escritura previa: el servicio
        `script.reload` está en la denylist justo por eso.
        """
        return await guarded_reload(
            ha_client, "script", "ha_reload_scripts", confirmation_token, "los scripts"
        )
