"""Hermes — Tools MCP para scenes de Home Assistant."""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.models.scene import SceneConfig
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    validate_confirmation_token,
)
from hermes.tools._common import (
    guarded_reload,
    entity_exists,
    not_found_response,
    requires_ready,
)


def _dump_config(model: SceneConfig) -> dict[str, Any]:
    """Serializa el modelo sin claves null."""
    return model.model_dump(exclude_none=True, by_alias=True, mode="json")

logger = structlog.get_logger(__name__)


async def _resolve_scene_config_id(
    ha_client: HAClient,
    scene_id: str,
) -> str:
    """Resuelve el id interno que usa el endpoint REST de config.

    Acepta entity_id (`scene.fiesta`) o id interno crudo. Si se pasa
    entity_id, busca `attributes.id` en el state cacheado. Si no se
    encuentra, devuelve el valor original (HA responderá 404 y `config_read`
    lo traducirá a None).
    """
    if not scene_id.startswith("scene."):
        return scene_id

    state = await ha_client.get_state(scene_id)
    if isinstance(state, dict):
        attrs = state.get("attributes") or {}
        if isinstance(attrs, dict):
            internal_id = attrs.get("id")
            if isinstance(internal_id, str) and internal_id:
                return internal_id
    logger.warning(
        "scene_id_resolve_failed",
        input=scene_id,
        reason="no_attributes_id_in_state",
        state_present=state is not None,
    )
    return scene_id


def _compact_scene(state: dict[str, Any]) -> dict[str, Any]:
    attributes = state.get("attributes", {}) or {}
    return {
        "entity_id": state.get("entity_id"),
        "friendly_name": attributes.get("friendly_name") or state.get("entity_id"),
        "state": state.get("state"),
        "last_activated": attributes.get("last_activated"),
        "icon": attributes.get("icon"),
    }


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de scenes."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_list_scenes() -> object:
        """Lista las scenes disponibles en Home Assistant.

        Cada scene devuelve `entity_id`, `friendly_name`, `state` y
        `last_activated` (si HA lo expone). Se leen desde la cache de
        estados, no implica REST.
        """
        states = await ha_client.get_states()
        scenes = [
            _compact_scene(state)
            for state in states
            if isinstance(state, dict)
            and isinstance(state.get("entity_id"), str)
            and state["entity_id"].startswith("scene.")
        ]
        return json.dumps(scenes, ensure_ascii=False, separators=(",", ":"))

    @mcp.tool()
    @ready
    async def ha_get_scene(scene_id: str) -> object:
        """Devuelve la configuración persistida y el estado de una scene.

        Acepta entity_id (`scene.fiesta`) o id interno crudo. La config se
        lee vía REST desde `/api/config/scene/config/{id}`. Si la scene no
        tiene config editable (definida en `configuration.yaml` con `scene:`
        en lugar de en el storage), el campo `config` será `None` y solo
        habrá `state`.
        """
        try:
            config_id = await _resolve_scene_config_id(ha_client, scene_id)
            try:
                config = await ha_client.config_read("scene", config_id)
            except HAConnectionError as exc:
                logger.warning(
                    "scene_config_read_ha_error",
                    config_id=config_id,
                    error=str(exc),
                )
                config = None

            try:
                state = await ha_client.get_state(scene_id)
            except HAConnectionError:
                state = None
            return {"config": config, "state": state}
        except Exception as exc:
            logger.error(
                "ha_get_scene_failed",
                scene_id=scene_id,
                error=str(exc),
                exc_info=True,
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_create_or_update_scene(
        scene_id: str,
        config: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Crea o modifica una scene en Home Assistant.

        Dos caminos según si la scene ya existe:

        - **Nueva scene** (la lectura de `/api/config/scene/config/{id}`
          devuelve None): no requiere `confirmation_token`, se guarda
          directamente.
        - **Scene existente**: si no se suministra `confirmation_token`,
          devuelve un preview con el diff `current` vs `new` y un token
          para confirmar. Con token, valida y aplica.

        Tras el save, HA recarga automáticamente las scenes editables
        (post_write_hook → scene.reload). No es necesario llamar a
        `ha_reload_scenes` a mano.

        **Limitación**: las scenes definidas en `configuration.yaml` con el
        bloque `scene:` son read-only vía REST. Este endpoint solo ve las
        almacenadas en `.storage/core.scene_*`, creadas desde la UI o con
        `scene.create`. Un intento de actualizar una scene YAML devolverá
        error por parte de HA.
        """
        try:
            normalized_config = _dump_config(SceneConfig.model_validate(config))
        except Exception as exc:
            logger.warning(
                "ha_create_or_update_scene_validation_failed",
                scene_id=scene_id,
                error=str(exc),
            )
            return {"error": f"config validation: {exc}"}

        args = {
            "scene_id": scene_id,
            "config": normalized_config,
        }

        if not confirmation_token:
            try:
                config_id = await _resolve_scene_config_id(ha_client, scene_id)
                try:
                    current = await ha_client.config_read("scene", config_id)
                except HAConnectionError as exc:
                    logger.warning(
                        "ha_create_or_update_scene_preview_read_failed",
                        config_id=config_id,
                        error=str(exc),
                    )
                    current = None

                if current is None:
                    # Scene nueva — creación directa, sin token.
                    result = await ha_client.config_save(
                        "scene",
                        config_id,
                        normalized_config,
                    )
                    logger.info(
                        "ha_create_or_update_scene_created",
                        scene_id=scene_id,
                        config_id=config_id,
                    )
                    return result

                preview = {
                    "scene_id": scene_id,
                    "config_id": config_id,
                    "current": current,
                    "new": normalized_config,
                }
                return await create_confirmation_token(
                    "ha_create_or_update_scene",
                    args,
                    preview=preview,
                )
            except Exception as exc:
                logger.error(
                    "ha_create_or_update_scene_preview_failed",
                    scene_id=scene_id,
                    error=str(exc),
                    exc_info=True,
                )
                return {"error": f"{type(exc).__name__}: {exc}"}

        valid, error = await validate_confirmation_token(
            confirmation_token,
            "ha_create_or_update_scene",
            args,
        )
        if not valid:
            logger.warning(
                "ha_create_or_update_scene_token_invalid",
                scene_id=scene_id,
                reason=error,
            )
            return {"error": error}

        try:
            config_id = await _resolve_scene_config_id(ha_client, scene_id)
            result = await ha_client.config_save(
                "scene",
                config_id,
                normalized_config,
            )
            await complete_confirmation_token(
                confirmation_token,
                success=True,
                result=result,
            )
            logger.info(
                "ha_create_or_update_scene_ok",
                scene_id=scene_id,
                config_id=config_id,
            )
            return result
        except Exception as exc:
            logger.error(
                "ha_create_or_update_scene_failed",
                scene_id=scene_id,
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
    async def ha_delete_scene(
        scene_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina una scene de Home Assistant.

        Esta operación siempre requiere `confirmation_token`. Si no se pasa
        token, devuelve un preview con la config actual y un token para
        confirmar. Tras el delete, HA recarga automáticamente las scenes
        editables.

        **Limitación**: solo se pueden borrar scenes editables
        (`.storage/core.scene_*`). Las definidas en `configuration.yaml`
        con el bloque `scene:` son read-only vía REST.
        """
        args = {"scene_id": scene_id}

        if not confirmation_token:
            try:
                config_id = await _resolve_scene_config_id(ha_client, scene_id)
                try:
                    current = await ha_client.config_read("scene", config_id)
                except HAConnectionError as exc:
                    logger.warning(
                        "ha_delete_scene_preview_read_failed",
                        config_id=config_id,
                        error=str(exc),
                    )
                    current = None
                preview = {
                    "scene_id": scene_id,
                    "config_id": config_id,
                    "current": current,
                }
                return await create_confirmation_token(
                    "ha_delete_scene",
                    args,
                    preview=preview,
                )
            except Exception as exc:
                logger.error(
                    "ha_delete_scene_preview_failed",
                    scene_id=scene_id,
                    error=str(exc),
                    exc_info=True,
                )
                return {"error": f"{type(exc).__name__}: {exc}"}

        valid, error = await validate_confirmation_token(
            confirmation_token,
            "ha_delete_scene",
            args,
        )
        if not valid:
            logger.warning(
                "ha_delete_scene_token_invalid",
                scene_id=scene_id,
                reason=error,
            )
            return {"error": error}

        try:
            config_id = await _resolve_scene_config_id(ha_client, scene_id)
            result = await ha_client.config_delete("scene", config_id)
            await complete_confirmation_token(
                confirmation_token,
                success=True,
                result=result,
            )
            logger.info(
                "ha_delete_scene_ok",
                scene_id=scene_id,
                config_id=config_id,
                found=result is not None,
            )
            return result if result is not None else {"result": "not_found"}
        except Exception as exc:
            logger.error(
                "ha_delete_scene_failed",
                scene_id=scene_id,
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
    async def ha_activate_scene(
        scene_id: str,
        transition: float | None = None,
    ) -> object:
        """Activa una scene mediante `scene.turn_on`.

        Opcionalmente acepta `transition` (segundos) para interpolar los
        cambios de estado. Es una acción reversible (basta activar otra
        scene o cambiar los estados a mano) e idempotente, así que no
        requiere `confirmation_token`.
        """
        if not await entity_exists(ha_client, scene_id):
            logger.warning("ha_activate_scene_not_found", scene_id=scene_id)
            return not_found_response(scene_id)
        payload: dict[str, Any] = {"entity_id": scene_id}
        if transition is not None:
            payload["transition"] = transition
        return await ha_client.call_service("scene", "turn_on", payload)

    @mcp.tool()
    @ready
    async def ha_reload_scenes(
        confirmation_token: str | None = None,
    ) -> object:
        """Recarga las scenes en Home Assistant.

        Requiere `confirmation_token`. Una recarga activa el YAML tal y
        como esté en /config en ese instante, así que es el paso que
        materializa cualquier escritura previa: el servicio
        `scene.reload` está en la denylist justo por eso.
        """
        return await guarded_reload(
            ha_client, "scene", "ha_reload_scenes", confirmation_token, "las escenas"
        )

    @mcp.tool()
    @ready
    async def ha_create_scene_from_current(
        scene_id: str,
        entity_ids: list[str],
        name: str | None = None,
    ) -> object:
        """Crea una scene nueva capturando el estado actual de las entidades.

        Usa el servicio `scene.create` de HA con `snapshot_entities`, lo que
        hace que HA tome el snapshot del momento de cada entidad. No
        requiere `confirmation_token` porque es una creación no destructiva
        (no sobreescribe automáticamente una scene existente: si el
        `scene_id` colisiona, HA devolverá error).

        Args:
            scene_id: id de la scene a crear. Acepta `scene.fiesta` o
                simplemente `fiesta`; se normaliza.
            entity_ids: lista de entity_ids cuyo estado actual se captura.
            name: friendly_name opcional. No todas las versiones de HA
                soportan este campo en el servicio `scene.create`; si se
                pasa, se incluye en el payload y HA decide.
        """
        object_id = scene_id.removeprefix("scene.")
        payload: dict[str, Any] = {
            "scene_id": object_id,
            "snapshot_entities": entity_ids,
        }
        if name is not None:
            payload["name"] = name
        return await ha_client.call_service("scene", "create", payload)
