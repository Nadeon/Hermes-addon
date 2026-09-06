"""Helpers compartidos entre módulos de tools."""

from __future__ import annotations

import functools
from typing import Any, Callable

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    validate_confirmation_token,
)

logger = structlog.get_logger(__name__)


def requires_ready(ha_client: HAClient, timeout: float = 5.0) -> Callable:
    """Decorator: espera a que HAClient esté listo antes de ejecutar.

    Si el timeout expira, devuelve `{"error": "not_ready", "retry_after_seconds": 2}`
    y loguea `ha_client_not_ready`. Evita los fallos intermitentes de la
    primera llamada tras arranque, cuando la WS aún no ha completado el
    handshake con HA.
    """

    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not await ha_client.wait_ready(timeout=timeout):
                logger.warning("ha_client_not_ready", tool=fn.__name__)
                return {"error": "not_ready", "retry_after_seconds": 2}
            return await fn(*args, **kwargs)

        return wrapper

    return decorator


async def entity_exists(ha_client: HAClient, entity_id: str) -> bool:
    """Devuelve True si la entidad existe (cache o REST)."""
    try:
        state = await ha_client.get_state(entity_id)
    except HAConnectionError:
        return False
    return state is not None


def not_found_response(entity_id: str) -> dict[str, str]:
    """Respuesta estructurada cuando una entidad no existe."""
    return {"error": "not_found", "entity_id": entity_id}


# ── Helpers flujos WS collection (create/update/delete) ──────
#
# Comparten lógica idéntica entre los 9 tipos editables: preview+token,
# decisión create-vs-update, validación de id derivado de slugify(name),
# completar token en éxito/fallo. Cada módulo de tool solo valida su
# Pydantic model y delega aquí.


def _object_id_of(domain: str, entity_id: str) -> str:
    prefix = f"{domain}."
    return entity_id[len(prefix):] if entity_id.startswith(prefix) else entity_id


async def collection_update_flow(
    ha_client: HAClient,
    domain: str,
    entity_id: str,
    normalized_config: dict[str, Any],
    tool_name: str,
    confirmation_token: str | None,
    log: Any,
) -> object:
    """Flujo completo de update (create-or-update) para helpers WS.

    Todos los helpers de colección (`input_*`, `counter`, `timer`, `schedule`) usan
    comandos WS `{domain}/{create,update}` con payload plano. El object_id en
    create lo genera HA desde `slugify(name)`; si el resultado no coincide con
    el entity_id solicitado, devolvemos respuesta con el id real.
    """
    object_id = _object_id_of(domain, entity_id)
    args = {"entity_id": entity_id, "config": normalized_config}

    if not confirmation_token:
        try:
            try:
                current = await ha_client.ws_collection_get(domain, object_id)
            except HAConnectionError as exc:
                log.warning(
                    f"{tool_name}_preview_read_failed",
                    object_id=object_id,
                    error=str(exc),
                )
                current = None
            preview = {
                "entity_id": entity_id,
                "object_id": object_id,
                "current": current,
                "new": normalized_config,
            }
            return await create_confirmation_token(
                tool_name, args, preview=preview
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                f"{tool_name}_preview_failed",
                entity_id=entity_id,
                error=str(exc),
                exc_info=True,
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    valid, error = await validate_confirmation_token(
        confirmation_token, tool_name, args
    )
    if not valid:
        log.warning(
            f"{tool_name}_token_invalid",
            entity_id=entity_id,
            reason=error,
        )
        return {"error": error}

    try:
        existing = await ha_client.ws_collection_get(domain, object_id)
        if existing is None:
            created = await ha_client.ws_collection_create(
                domain, normalized_config
            )
            created_id = (
                created.get("id") if isinstance(created, dict) else None
            )
            if created_id != object_id:
                log.warning(
                    f"{tool_name}_id_mismatch",
                    requested=object_id,
                    actual=created_id,
                )
                await complete_confirmation_token(
                    confirmation_token, success=True, result=created
                )
                return {
                    "result": "created_with_different_id",
                    "requested_entity_id": entity_id,
                    "actual_entity_id": (
                        f"{domain}.{created_id}" if created_id else None
                    ),
                    "hint": (
                        "HA derives object_id from slugify(name). Pass a "
                        "name whose slug matches the object_id you want."
                    ),
                }
        else:
            await ha_client.ws_collection_update(
                domain, object_id, normalized_config
            )
        result = {"result": "ok"}
        await complete_confirmation_token(
            confirmation_token, success=True, result=result
        )
        log.info(f"{tool_name}_ok", entity_id=entity_id, object_id=object_id)
        return result
    except Exception as exc:  # noqa: BLE001
        log.error(
            f"{tool_name}_failed",
            entity_id=entity_id,
            error=str(exc),
            exc_info=True,
        )
        await complete_confirmation_token(
            confirmation_token, success=False, error=str(exc)
        )
        return {"error": f"{type(exc).__name__}: {exc}"}


async def collection_delete_flow(
    ha_client: HAClient,
    domain: str,
    entity_id: str,
    tool_name: str,
    confirmation_token: str | None,
    log: Any,
) -> object:
    """Flujo completo de delete para helpers WS. Siempre requiere token."""
    object_id = _object_id_of(domain, entity_id)
    args = {"entity_id": entity_id}

    if not confirmation_token:
        try:
            try:
                current = await ha_client.ws_collection_get(domain, object_id)
            except HAConnectionError as exc:
                log.warning(
                    f"{tool_name}_preview_read_failed",
                    object_id=object_id,
                    error=str(exc),
                )
                current = None
            preview = {
                "entity_id": entity_id,
                "object_id": object_id,
                "current": current,
            }
            return await create_confirmation_token(
                tool_name, args, preview=preview
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                f"{tool_name}_preview_failed",
                entity_id=entity_id,
                error=str(exc),
                exc_info=True,
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    valid, error = await validate_confirmation_token(
        confirmation_token, tool_name, args
    )
    if not valid:
        log.warning(
            f"{tool_name}_token_invalid",
            entity_id=entity_id,
            reason=error,
        )
        return {"error": error}

    try:
        deleted = await ha_client.ws_collection_delete(domain, object_id)
        result = {"result": "ok"} if deleted else {"result": "not_found"}
        await complete_confirmation_token(
            confirmation_token, success=True, result=result
        )
        log.info(
            f"{tool_name}_ok",
            entity_id=entity_id,
            object_id=object_id,
            found=deleted,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log.error(
            f"{tool_name}_failed",
            entity_id=entity_id,
            error=str(exc),
            exc_info=True,
        )
        await complete_confirmation_token(
            confirmation_token, success=False, error=str(exc)
        )
        return {"error": f"{type(exc).__name__}: {exc}"}


async def collection_get_current(
    ha_client: HAClient, domain: str, entity_id: str
) -> dict[str, Any] | None:
    """Lee la config actual de un helper por entity_id (list + filtro)."""
    object_id = _object_id_of(domain, entity_id)
    try:
        return await ha_client.ws_collection_get(domain, object_id)
    except HAConnectionError:
        return None


async def guarded_reload(
    ha_client: Any,
    domain: str,
    tool_name: str,
    confirmation_token: str | None,
    what: str,
) -> object:
    """Recarga un dominio de HA con confirmación en dos pasos.

    Los servicios `<domain>.reload` están en la denylist bajo el comentario del
    propio código «Reloads que pueden activar YAML envenenado»: una recarga
    materializa lo que haya en el YAML en ese momento.

    Las tools dedicadas —`ha_reload_automations`, `ha_reload_scripts` y cinco
    más— ejecutan ese mismo servicio, así que sin confirmación serían la ruta
    limpia para activar un `fs_write_file` malicioso previo: escribir el YAML
    (que sí pide token) y luego recargarlo con una tool que el cliente aprueba
    sin mirar. Por eso piden confirmación como cualquier otra acción
    destructiva, y son el único sitio que pasa `allow_dangerous=True` además
    de `ha_call_service`.
    """
    args = {"domain": domain}
    if not confirmation_token:
        preview = {
            "action": f"reload_{domain}",
            "service": f"{domain}.reload",
            "effect": (
                f"Aplica el YAML de {what} tal y como esté AHORA en /config. "
                "Si se ha escrito algo antes, esta llamada es la que lo activa."
            ),
        }
        return await create_confirmation_token(tool_name, args, preview=preview)

    valid, error = await validate_confirmation_token(
        confirmation_token, tool_name, args
    )
    if not valid:
        logger.warning(f"{tool_name}_token_invalid", reason=error)
        return {"error": error}

    result = await ha_client.call_service(domain, "reload", allow_dangerous=True)
    await complete_confirmation_token(confirmation_token, success=True, result=result)
    logger.info(f"{tool_name}_ok", domain=domain)
    return result


async def guarded_entity_invoke(
    ha_client: Any,
    domain: str,
    service: str,
    entity_id: str,
    tool_name: str,
    confirmation_token: str | None,
    extra_data: dict[str, Any] | None = None,
) -> object:
    """Ejecuta `domain.service` sobre una entidad, con token si está restringida.

    Hermes clasifica como peligrosos los scripts y automatizaciones cuyo
    contenido invoca servicios de la denylist, y `ha_call_service` exige
    confirmación para ellos. Las tools de atajo —`ha_run_script`,
    `ha_trigger_automation`— hacen exactamente lo mismo por otra puerta, así
    que tienen que consultar ese mismo set; si no, `ha_run_script` ejecutaría
    sin preguntar lo que llamar al servicio a mano sí somete a confirmación.

    Aquí se consulta el set y, si la entidad está restringida, se aplica el
    mismo flujo de dos pasos que en `ha_call_service`. Si no lo está, la
    llamada es directa y de un solo paso.
    """
    from hermes.service_policy import get_auto_restricted_entities

    payload: dict[str, Any] = {"entity_id": entity_id}
    if extra_data:
        payload.update(extra_data)

    if entity_id not in get_auto_restricted_entities():
        return await ha_client.call_service(domain, service, payload)

    args = {"entity_id": entity_id, "service": f"{domain}.{service}"}
    if not confirmation_token:
        return await create_confirmation_token(
            tool_name,
            args,
            preview={
                "action": f"{domain}.{service}",
                "entity_id": entity_id,
                "reason": (
                    "Esta entidad está restringida: su contenido invoca "
                    "servicios de la denylist (borrado, reinicio, ejecución "
                    "arbitraria o apertura de cerraduras)."
                ),
            },
        )

    valid, error = await validate_confirmation_token(
        confirmation_token, tool_name, args
    )
    if not valid:
        logger.warning(f"{tool_name}_token_invalid", entity_id=entity_id, reason=error)
        return {"error": error}

    result = await ha_client.call_service(
        domain, service, payload, allow_dangerous=True
    )
    await complete_confirmation_token(confirmation_token, success=True, result=result)
    logger.info(f"{tool_name}_restricted_ok", entity_id=entity_id)
    return result
