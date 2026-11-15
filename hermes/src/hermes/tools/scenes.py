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
    resolve_confirmation_token,
    validate_confirmation_token,
)
from hermes.tools._validation import validate_path_segment
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

# Argumentos que se pueden omitir al confirmar (spec 007). `config` es lo único
# grande de la llamada: a unos 0,4 KB/s, un cliente LLM no reescribe uno de
# 20–25 KB antes de que caduque el token (60 s), así que la vista previa lo
# guarda en el servidor. `scene_id` no está aquí a propósito: el destino
# tiene que venir en las dos llamadas.
_OMITIBLES_GUARDAR = ("config",)


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
        lee vía REST desde `/api/config/scene/config/{id}`, que sirve las
        scenes editables de `scenes.yaml` (las de la UI y las de Hermes). Si
        la scene no está ahí (definida en `configuration.yaml` con `scene:`,
        temporal de `scene.create` o de una integración), el campo `config`
        será `None` y solo habrá `state`.
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
        config: dict[str, Any] | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Crea o modifica una scene en Home Assistant.

        Dos caminos según si la scene ya existe:

        - **Nueva scene** (la lectura de `/api/config/scene/config/{id}`
          devuelve None): no requiere `confirmation_token`, se guarda
          directamente.
        - **Scene existente**: si no se suministra `confirmation_token`,
          devuelve un preview con el diff `current` vs `new` y un token
          para confirmar. Con token, valida y aplica. Para confirmar basta
          con `scene_id` y `confirmation_token` (`confirm_with`): la vista
          previa guarda `config` en el servidor; si se reenvía, tiene que ser
          idéntico. Sin token, `config` es obligatorio (también al crear).

        Tras el save, HA recarga automáticamente las scenes editables
        (post_write_hook → scene.reload). No es necesario llamar a
        `ha_reload_scenes` a mano.

        **Limitación**: las scenes definidas en `configuration.yaml` con el
        bloque `scene:` son read-only vía REST. Este endpoint solo ve las
        guardadas en `scenes.yaml`, creadas desde la UI o con esta tool; no
        ve las temporales de `scene.create` (`ha_create_scene_from_current`),
        que no están en ningún fichero. Un intento de actualizar una scene
        YAML devolverá error por parte de HA.
        """
        if config is None and not confirmation_token:
            return {
                "error": "invalid_argument", "field": "config",
                "detail": (
                    "config is required to request a preview; it can only be "
                    "omitted when confirming with confirmation_token."
                ),
            }
        args: dict[str, Any] = {"scene_id": scene_id}
        # El documento guardado en la vista previa ya se validó y normalizó;
        # solo se valida el que llega. Ausente si se omite al confirmar: lo
        # pone resolve_confirmation_token.
        if config is not None:
            try:
                normalized_config = _dump_config(SceneConfig.model_validate(config))
            except Exception as exc:
                logger.warning(
                    "ha_create_or_update_scene_validation_failed",
                    scene_id=scene_id,
                    error=str(exc),
                )
                return {"error": f"config validation: {exc}"}
            args["config"] = normalized_config

        if not confirmation_token:
            try:
                config_id = await _resolve_scene_config_id(ha_client, scene_id)
                try:
                    current = await ha_client.config_read("scene", config_id)
                except HAConnectionError as exc:
                    # No se sabe si la escena existe, así que no se puede
                    # decidir entre "crear sin token" y "pedir confirmación".
                    # Tratar el fallo como "no existe" sobreescribía una
                    # escena real sin vista previa ni token.
                    logger.warning(
                        "ha_create_or_update_scene_preview_read_failed",
                        config_id=config_id,
                        error=str(exc),
                    )
                    return {
                        "error": "ha_unavailable",
                        "detail": str(exc),
                        "hint": (
                            "Could not read the current scene config, so it "
                            "is unknown whether this call would overwrite an "
                            "existing scene. Retry when Home Assistant responds."
                        ),
                    }

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
                    omitibles=_OMITIBLES_GUARDAR,
                )
            except Exception as exc:
                logger.error(
                    "ha_create_or_update_scene_preview_failed",
                    scene_id=scene_id,
                    error=str(exc),
                    exc_info=True,
                )
                return {"error": f"{type(exc).__name__}: {exc}"}

        valid, error, resueltos = await resolve_confirmation_token(
            confirmation_token,
            "ha_create_or_update_scene",
            args,
            omitibles=_OMITIBLES_GUARDAR,
        )
        if not valid:
            logger.warning(
                "ha_create_or_update_scene_token_invalid",
                scene_id=scene_id,
                reason=error,
            )
            return {"error": error}
        # Se guarda lo previsualizado: el reenviado (idéntico, porque el hash
        # casa) o el que se guardó en la vista previa.
        normalized_config = resueltos["config"]

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

        **Limitación**: solo se pueden borrar scenes editables, las de
        `scenes.yaml`. Las definidas en `configuration.yaml` con el bloque
        `scene:` son read-only vía REST, y las temporales de `scene.create`
        no están en ningún fichero (desaparecen al recargar o reiniciar).
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
        confirmation_token: str | None = None,
    ) -> object:
        """Crea una scene TEMPORAL capturando el estado actual de las entidades.

        Usa el servicio `scene.create` de HA con `snapshot_entities`. La scene
        es temporal: no se guarda en `scenes.yaml`, no tiene `id` ni entrada
        en el registro de entidades, y se pierde al reiniciar Home Assistant
        o al recargar las scenes (también al guardar o borrar cualquier scene
        con `ha_create_or_update_scene` / `ha_delete_scene`, que recargan).
        Para una scene persistente y con nombre, usa
        `ha_create_or_update_scene`.

        - Si `scene.<scene_id>` no existe, la crea sin token.
        - Si existe y es otra temporal, HA la REEMPLAZA: sin
          `confirmation_token` devuelve un preview (entidades actuales y
          nuevas) y un token; con el token, la reemplaza.
        - Si existe y no es temporal (de `scenes.yaml`, de YAML con `id` o de
          una integración), responde `scene_exists`: HA no la tocaría.
        - Si alguna entidad no existe, responde `entity_not_found`.
        - Después comprueba que la scene tiene esas entidades (y, si la
          reemplazaba, que HA la ha recreado); si no, responde
          `scene_not_created`.

        Args:
            scene_id: id de la scene. Acepta `scene.fiesta` o simplemente
                `fiesta`; se normaliza.
            entity_ids: lista de entity_ids cuyo estado actual se captura.
            name: DEPRECATED (removed in 1.3.0). `scene.create` no admite
                nombre; si se pasa, responde `name_not_supported` sin hacer
                nada.
            confirmation_token: solo para reemplazar una scene temporal.
        """
        # Spec 033 (FR-006, research R-4). `CREATE_SCENE_SCHEMA` de Core no
        # tiene `name` y rechaza las claves de más: con `name` HA respondía
        # 400 siempre. Y la escena no entra en el registro, así que tampoco
        # se puede renombrar después. Ignorarlo en silencio daría por buena
        # una petición que no se cumple: se rechaza antes de tocar HA.
        if name is not None:
            return {
                "error": "name_not_supported",
                "message": (
                    "scene.create does not accept a name: Home Assistant names the "
                    "temporary scene after its scene_id and keeps no registry entry "
                    "to rename it later."
                ),
                "hint": "use ha_create_or_update_scene for a named, persistent scene",
                "_deprecated": (
                    "the name argument of ha_create_scene_from_current is deprecated "
                    "and will be removed in 1.3.0"
                ),
            }

        object_id = scene_id.removeprefix("scene.")
        eid = f"scene.{object_id}"

        # Core salta en silencio las entidades que no existen (y, si no
        # queda ninguna, no crea nada y no da error): se dice antes.
        missing = [e for e in entity_ids if not await entity_exists(ha_client, e)]
        if missing:
            return {"error": "entity_not_found", "entity_ids": missing}

        args = {"scene_id": object_id, "entity_ids": entity_ids}
        current = await ha_client.get_state(eid)
        replaced = False
        if current is not None:
            attrs = current.get("attributes") or {}
            # Core solo reemplaza una escena creada con `scene.create`; con
            # cualquier otra (con `id` de configuración, o de una
            # integración, que está en el registro) avisa en el log y vuelve
            # sin error ni cambios. Las de `scene.create` no tienen ni lo uno
            # ni lo otro.
            if attrs.get("id") or await _in_entity_registry(eid):
                return {
                    "error": "scene_exists",
                    "scene_id": eid,
                    "message": (
                        f"{eid} exists and was not created with scene.create: Home "
                        "Assistant would keep it and ignore the request. Choose another "
                        "scene_id, or use ha_create_or_update_scene to edit it."
                    ),
                }
            if not confirmation_token:
                return await create_confirmation_token(
                    "ha_create_scene_from_current",
                    args,
                    preview={
                        "action": "scene.create",
                        "scene_id": eid,
                        "current_entities": attrs.get("entity_id"),
                        "new_entities": entity_ids,
                        "effect": (
                            "Replaces the temporary scene. Temporary scenes are lost "
                            "when Home Assistant restarts or scenes are reloaded."
                        ),
                    },
                )
            replaced = True

        # Con token se valida siempre, también si la escena ya no existe: quien
        # lo manda está confirmando una vista previa concreta (fail-closed).
        if confirmation_token:
            valid, error = await validate_confirmation_token(
                confirmation_token, "ha_create_scene_from_current", args
            )
            if not valid:
                logger.warning(
                    "ha_create_scene_from_current_token_invalid", scene_id=eid, reason=error
                )
                return {"error": error}

        # Al reemplazar, que las entidades coincidan no basta: una escena de
        # YAML sin `id` (indistinguible de una temporal por su estado, S-03)
        # con las mismas entidades seguiría igual aunque Core ignorase la
        # petición. Core quita la escena y añade otra, así que un reemplazo
        # real deja un `last_updated` nuevo: se guarda el de antes (por REST,
        # sin la caché) y se exige que cambie.
        before: dict[str, Any] | None = None
        if replaced:
            try:
                before = await _fresh_state(eid)
            except Exception as exc:
                if confirmation_token:
                    await complete_confirmation_token(
                        confirmation_token, success=False, error=str(exc)
                    )
                raise
        try:
            result = await ha_client.call_service(
                "scene", "create", {"scene_id": object_id, "snapshot_entities": entity_ids}
            )
            # Core puede volver sin error y sin crear nada (escena de YAML sin
            # `id` con ese nombre, ninguna entidad que capturar). Se lee el
            # estado por REST, sin la caché, que puede ir por detrás del bus.
            after = await _fresh_state(eid)
        except Exception as exc:
            if confirmation_token:
                await complete_confirmation_token(
                    confirmation_token, success=False, error=str(exc)
                )
            raise
        seen = (after.get("attributes") or {}).get("entity_id") if after else None
        unchanged = (
            before is not None
            and after is not None
            and after.get("last_updated") == before.get("last_updated")
        )
        if (
            not isinstance(seen, list)
            or sorted(set(seen)) != sorted(set(entity_ids))
            or unchanged
        ):
            if confirmation_token:
                await complete_confirmation_token(
                    confirmation_token, success=False, error="scene_not_created"
                )
            logger.warning("ha_create_scene_from_current_not_created", scene_id=eid)
            return {
                "error": "scene_not_created",
                "scene_id": eid,
                "seen_entity_ids": seen if isinstance(seen, list) else None,
            }
        if confirmation_token:
            await complete_confirmation_token(confirmation_token, success=True, result=result)
        return {
            "result": "ok",
            "scene_id": eid,
            "entity_ids": entity_ids,
            "replaced": replaced,
            "temporary": True,
            "ha_response": result,
        }

    async def _in_entity_registry(entity_id: str) -> bool:
        """Si la entidad está en el registro de entidades de HA."""
        try:
            await ha_client.ws_send(
                {"type": "config/entity_registry/get", "entity_id": entity_id}
            )
        except HAConnectionError as exc:
            # Se decide por el código, no por el texto (como registry_entity).
            if exc.code == "not_found":
                return False
            raise
        return True

    async def _fresh_state(entity_id: str) -> dict[str, Any] | None:
        """Estado leído por REST, sin la caché; None si Core no la conoce."""
        # El id viene del cliente y acaba en la ruta: misma comprobación que
        # `HAClient.get_state`, que aquí no se usa por la caché.
        validate_path_segment(entity_id, field="scene_id")
        try:
            return await ha_client._request_json(  # noqa: SLF001
                "GET", f"/states/{entity_id}"
            )
        except HAConnectionError as exc:
            if getattr(exc, "status", None) == 404:
                return None
            raise
