"""Helpers compartidos entre módulos de tools."""

from __future__ import annotations

import functools
import json
from typing import Any, Callable

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    validate_confirmation_token,
)

logger = structlog.get_logger(__name__)


def tam_json(valor: Any) -> int:
    """Bytes UTF-8 de `valor` serializado como lo devuelven las tools."""
    return len(json.dumps(valor, ensure_ascii=False).encode("utf-8"))


def ajustar_lista_a_bytes(
    items: list[Any],
    construir: Callable[[list[Any], bool], Any],
    max_bytes: int,
) -> Any:
    """Respuesta con tantos `items` como quepan en `max_bytes`.

    `construir(items, recortada)` arma la respuesta completa; así los
    recuentos y la marca `truncated` los decide quien conoce su forma. Se
    estima cuántos caben sumando el tamaño de cada elemento (lineal, en vez de
    reserializar la lista entera por cada uno que se quita) y se verifica al
    final con el tamaño real, quitando de uno en uno si la estimación se pasó.
    Es el mismo criterio que `ha_list_entities_registry`: recortar por el
    final y decirlo, nunca dejar que el cliente corte a ciegas (spec 003).
    """
    completa = construir(items, False)
    if tam_json(completa) <= max_bytes:
        return completa
    presupuesto = max_bytes - tam_json(construir([], True))
    n = usado = 0
    for item in items:
        # ", " separa los elementos en la serialización por defecto.
        coste = tam_json(item) + (2 if n else 0)
        if usado + coste > presupuesto:
            break
        usado += coste
        n += 1
    while True:
        out = construir(items[:n], True)
        if n == 0 or tam_json(out) <= max_bytes:
            return out
        n -= 1


_LIMIT_HINT = (
    "The response was cut to fit response_max_bytes. Filter more (by domain, "
    "entity, dates or a search argument) instead of repeating the same call."
)

# Pista propia del error: la de arriba decía «se ha recortado» cuando no se
# había devuelto nada y proponía filtros que la tool quizá no tiene (revisión
# de 1.1.1, L-1).
_TOO_LARGE_HINT = (
    "Nothing was returned: the response exceeds response_max_bytes and has no "
    "list that can be cut safely. Ask for less (fewer lines, a single view, a "
    "shorter range, a narrower filter) or use a paginated read tool."
)

_PREVIEW_HINT = (
    "Some preview fields did not fit in response_max_bytes and were replaced "
    "by a summary marked _omitted. The confirmation_token still covers exactly "
    "the arguments of this call. If you need to see the omitted content, read "
    "it with the matching read tool before confirming."
)

# Metadatos con los que una tool cuenta la lista que devuelve. Si el guardián
# recorta esa lista y los deja como estaban, el agente lee un `count` que no
# es el de la respuesta (revisión de 1.1.1, M-1).
_RECUENTOS = ("count", "returned", "returned_lines")


def _resumen_omitido(valor: Any) -> dict[str, Any]:
    """Lo que queda de un campo de vista previa que no cabe: qué era y cuánto."""
    resumen: dict[str, Any] = {"_omitted": True, "bytes": tam_json(valor)}
    if isinstance(valor, str):
        resumen["type"] = "text"
        resumen["lines"] = len(valor.splitlines())
    elif isinstance(valor, dict):
        resumen["type"] = "object"
        resumen["keys"] = sorted(str(k) for k in valor)[:50]
    elif isinstance(valor, list):
        resumen["type"] = "list"
        resumen["items"] = len(valor)
    return resumen


def _recortar_vista_previa(payload: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """Vista previa que cabe en `max_bytes` SIN perder el `confirmation_token`.

    Hasta 1.1.1 el guardián sustituía una vista previa grande por
    `response_too_large`, y con ella se iba el token: no había forma de borrar
    un fichero de texto grande ni de editar una automatización larga (revisión
    de 1.1.1, A-1). Recortar a medias una lista de la vista previa tampoco
    vale, porque el usuario aprobaría algo que no ha visto entero sin saberlo
    (principio IV). Así que se sustituyen los campos más grandes, de uno en
    uno, por un resumen marcado `_omitted` con su tamaño, y la respuesta lo
    dice con `preview_truncated: true`. El token no cambia: sigue atado a los
    argumentos de la llamada, no a lo que se ve.
    """
    intocables = {"confirmation_token", "expires_in_seconds"}
    out = dict(payload)
    out["preview_truncated"] = True
    out["_response_limit"] = {"max_bytes": max_bytes, "hint": _PREVIEW_HINT}
    preview = out.get("preview")
    if isinstance(preview, dict):
        preview = dict(preview)
        out["preview"] = preview
    candidatos: list[tuple[dict[str, Any], str]] = []
    if isinstance(preview, dict):
        candidatos += [(preview, k) for k in preview]
    candidatos += [
        (out, k) for k in payload
        if k not in intocables and not (k == "preview" and isinstance(preview, dict))
    ]
    candidatos.sort(key=lambda c: tam_json(c[0][c[1]]), reverse=True)
    for contenedor, clave in candidatos:
        if tam_json(out) <= max_bytes:
            return out
        resumen = _resumen_omitido(contenedor[clave])
        if tam_json(resumen) < tam_json(contenedor[clave]):
            contenedor[clave] = resumen
    if tam_json(out) <= max_bytes:
        return out
    # Último recurso (un tope absurdo): el token y la marca, nada más. Aun así
    # el token se conserva; sin él la acción sería imposible por Hermes.
    minimo = {
        k: payload[k] for k in ("confirmation_token", "expires_in_seconds") if k in payload
    }
    minimo["preview_truncated"] = True
    return minimo


def _corregir_recuentos(
    out: dict[str, Any], original: dict[str, Any], antes: int, ahora: int
) -> None:
    """Pone al día los recuentos de la tool tras recortar su lista.

    Solo se toca un recuento que contaba esa lista (vale lo mismo que su
    longitud original); un `count` que ya era el total de otra cosa se deja.
    `truncated_at` apunta al último elemento que la tool incluyó, que ya no
    está: paginar desde él saltaría elementos, así que se quita y manda
    `_response_limit`.
    """
    for k in _RECUENTOS:
        if original.get(k) == antes and not isinstance(original.get(k), bool):
            out[k] = ahora
    out.pop("truncated_at", None)


def _es_dict_de_listas(valor: Any) -> bool:
    return (
        isinstance(valor, dict) and bool(valor)
        and all(isinstance(v, list) for v in valor.values())
        and any(valor.values())
    )


def _recortar_dict_de_listas(
    payload: dict[str, Any], clave: str, max_bytes: int
) -> dict[str, Any] | None:
    """Recorta `payload[clave]`, un `{id: [puntos]}`, quitando por el final.

    Es la forma de history y statistics. Antes de 1.1.1 no había lista en el
    nivel superior y el guardián lo convertía todo en `response_too_large`
    (revisión de 1.1.1, B-1). Se quita el último punto de la lista más larga,
    el mismo criterio que esas tools, que iguala las longitudes. Solo se
    aplica a un objeto cuyos valores son TODOS listas: un objeto con más
    campos (una vista de Lovelace, una automatización) recortado a medias se
    podría guardar de vuelta y perder datos.
    """
    grupos = {k: list(v) for k, v in payload[clave].items()}
    total = sum(len(v) for v in grupos.values())

    def construir() -> dict[str, Any]:
        out = {
            **payload, clave: grupos, "truncated": True,
            "_response_limit": {
                "list": clave, "returned": sum(len(v) for v in grupos.values()),
                "total": total, "max_bytes": max_bytes, "hint": _LIMIT_HINT,
            },
        }
        out.pop("truncated_at", None)
        return out

    exceso = tam_json(construir()) - max_bytes
    while exceso > 0 and any(grupos.values()):
        mayor = max(grupos, key=lambda k: len(grupos[k]))
        item = grupos[mayor].pop()
        # Estimación lineal; se verifica con el tamaño real al llegar a cero.
        exceso -= tam_json(item) + (2 if grupos[mayor] else 0)
        if exceso <= 0:
            exceso = tam_json(construir()) - max_bytes
    out = construir()
    return out if tam_json(out) <= max_bytes else None


def recortar_a_bytes(payload: Any, max_bytes: int) -> Any:
    """`payload` tal cual si cabe en `max_bytes`; si no, recortado y dicho.

    Es la red de seguridad de `HermesMCPServer` para las tools que no recortan
    por su cuenta (spec 006). Una lista se envuelve en un objeto, porque una
    lista no tiene dónde decir `truncated`. En un objeto se recorta su lista
    más grande del nivel superior y se ponen al día sus recuentos; si no hay
    ninguna, un `{id: [puntos]}` del nivel superior. Una vista previa con
    `confirmation_token` nunca pierde el token: se resumen sus campos grandes.
    Si no hay nada que recortar (un texto enorme, un objeto de objetos), se
    devuelve un error en vez de cortar a ciegas: un JSON partido o un texto
    cortado sin aviso engañan al agente.
    """
    if tam_json(payload) <= max_bytes:
        return payload

    if isinstance(payload, dict) and "confirmation_token" in payload:
        return _recortar_vista_previa(payload, max_bytes)

    def aviso(clave: str | None, devueltos: int, total: int) -> dict[str, Any]:
        return {
            "list": clave, "returned": devueltos, "total": total,
            "max_bytes": max_bytes, "hint": _LIMIT_HINT,
        }

    out: Any = None
    if isinstance(payload, list):
        def construir(items: list[Any], _recortada: bool) -> dict[str, Any]:
            return {
                "truncated": True, "count": len(items), "total": len(payload),
                "items": items, "_response_limit": aviso("items", len(items), len(payload)),
            }
        out = ajustar_lista_a_bytes(payload, construir, max_bytes)
    elif isinstance(payload, dict):
        listas = [k for k, v in payload.items() if isinstance(v, list) and v]
        dicts = [k for k, v in payload.items() if _es_dict_de_listas(v)]
        if listas:
            clave = max(listas, key=lambda k: tam_json(payload[k]))
            lista = payload[clave]

            def construir(items: list[Any], _recortada: bool) -> dict[str, Any]:
                # `truncated` se fuerza a true aunque la tool ya lo trajera a
                # false: ahora sí se ha recortado.
                nuevo = {
                    **payload, clave: items, "truncated": True,
                    "_response_limit": aviso(clave, len(items), len(lista)),
                }
                _corregir_recuentos(nuevo, payload, len(lista), len(items))
                return nuevo
            out = ajustar_lista_a_bytes(lista, construir, max_bytes)
        elif dicts:
            clave = max(dicts, key=lambda k: tam_json(payload[k]))
            out = _recortar_dict_de_listas(payload, clave, max_bytes)
    if out is not None and tam_json(out) <= max_bytes:
        return out
    return {
        "error": "response_too_large",
        "detail": (
            f"The response ({tam_json(payload)} bytes) exceeds response_max_bytes "
            f"({max_bytes}) and has no list that can be cut."
        ),
        "hint": _TOO_LARGE_HINT,
    }


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
    """Devuelve True si la entidad existe (cache o REST).

    Lo único que significa "no existe" es que `get_state` devuelva None (el
    404 del endpoint /states). Antes se tragaba cualquier HAConnectionError:
    con Home Assistant caído, `ha_run_script` / `ha_trigger_automation`
    respondían `not_found` y el cliente daba por borrado un script que sigue
    ahí —y podía "recrearlo" encima del original—. Los errores de conexión se
    propagan para que se vean como lo que son.
    """
    state = await ha_client.get_state(entity_id)
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
            # `{domain}/update` de HA NO es un PATCH: `_update_data` devuelve
            # `{CONF_ID: item[CONF_ID]} | CREATE_UPDATE_SCHEMA(update_data)`,
            # así que el item se REEMPLAZA por lo enviado. Como `name` es
            # Required en ese schema, mandar solo los campos que cambian falla
            # con "required key not provided @ data['name']" o —si el name va
            # incluido— borra en silencio el resto de la configuración
            # (initial, step, minimum, icon…). Se parte del item actual, sin
            # su id (HA rechaza actualizar el id), y encima lo que pide el
            # usuario.
            merged = {
                k: v for k, v in existing.items() if k != "id"
            } | normalized_config
            await ha_client.ws_collection_update(domain, object_id, merged)
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
