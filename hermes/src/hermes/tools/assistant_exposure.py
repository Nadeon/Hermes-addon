"""Hermes — Tools MCP de la exposición a asistentes (spec 021, tramo a).

Tres tools de la familia `assistant_exposure` (CAP-055 de la 008):

- `ha_list_exposed_entities`: qué entidades están expuestas a cada asistente
  (`homeassistant/expose_entity/list`) y si las nuevas se exponen solas
  (`homeassistant/expose_new_entities/get`, una por asistente).
- `ha_set_entity_exposure`: expone u oculta entidades a uno o varios
  asistentes (`homeassistant/expose_entity`).
- `ha_set_expose_new_entities`: si las entidades que se creen a partir de
  ahora se exponen solas a un asistente
  (`homeassistant/expose_new_entities/set`).

Los asistentes son los de HA (`KNOWN_ASSISTANTS`): `conversation` es Assist y
todo lo que lo usa (agentes conversacionales, también los de LLM en la nube, y
la integración MCP Server); `cloud.alexa` y `cloud.google_assistant` son la
nube de Amazon y de Google a través de Home Assistant Cloud.

POR QUÉ EXPONER CONFIRMA Y OCULTAR NO (decisión D-4 del supervisor)
------------------------------------------------------------------
Exponer da a un asistente —a veces a la nube de un tercero— la capacidad de
ver y controlar entidades (una cerradura, la alarma): pide token, atado a los
argumentos y a la exposición leída. Ocultar reduce lo expuesto y no puede
abrir nada: se aplica a la primera. Por eso las dos tools que escriben se
anuncian no destructivas (`_annotations.py`): exponer no destruye nada, y
ocultar ni siquiera se hace confirmar.

POR QUÉ SE EXIGE QUE LA ENTIDAD EXISTA
--------------------------------------
Para un id sin entrada de registro, HA crea una entrada heredada en su
almacén de exposición: un error de escritura dejaría basura. Hermes comprueba
el estado de cada entidad antes de escribir (`entity_exists`).

POR QUÉ OCULTAR NO DICE «no_changes»
------------------------------------
La lista de HA solo trae lo expuesto con un ajuste guardado. Una entidad sin
ajuste puede estar expuesta por defecto (con `expose_new` activo y un dominio
expuesto por defecto). Decir «ya oculta» por no verla en la lista podría
dejarla expuesta: ocultar siempre se manda, y la respuesta es la de HA.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    ESTADO_CAMBIADO,
    complete_confirmation_token,
    create_confirmation_token,
    redact_secrets,
    resolve_confirmation_token,
)
from hermes.tools._common import (
    _LIMIT_HINT,
    ajustar_lista_a_bytes,
    entity_exists,
    requires_ready,
    sobre_de_lista,
)

logger = structlog.get_logger(__name__)

ASISTENTES = ("cloud.alexa", "cloud.google_assistant", "conversation")
_DOMINIO = re.compile(r"^[a-z0-9_]+$")
_ENTIDAD = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_MAX_ENTIDADES = 200
# Dominios que actúan sobre la seguridad física de la casa.
_SENSIBLES = ("lock", "alarm_control_panel", "cover", "valve")

_AVISO_EXPONER = {
    "conversation": ("Assist, every conversation agent (including cloud LLM agents) and "
                     "the MCP Server integration can see and control these entities."),
    "cloud.alexa": ("Amazon Alexa receives the state of these entities and can control "
                    "them through Home Assistant Cloud."),
    "cloud.google_assistant": ("Google Assistant receives the state of these entities and "
                               "can control them through Home Assistant Cloud."),
}
_AVISO_NUEVAS = {
    "conversation": ("New entities of the default exposed domains will be visible to and "
                     "controllable by Assist, every conversation agent and the MCP Server "
                     "integration as soon as they are created."),
    "cloud.alexa": ("New entities of the default exposed domains will be sent to Amazon "
                    "Alexa through Home Assistant Cloud as soon as they are created."),
    "cloud.google_assistant": ("New entities of the default exposed domains will be sent "
                               "to Google Assistant through Home Assistant Cloud as soon as "
                               "they are created."),
}


def _invalido(tool: str, campo: str, detalle: str) -> dict[str, Any]:
    logger.info(f"{tool}_failed", error="invalid_argument", field=campo)
    return {"error": "invalid_argument", "field": campo, "detail": detalle}


def _error_ha(tool: str, exc: HAConnectionError) -> dict[str, Any]:
    detalle = redact_secrets(str(exc))
    logger.warning(f"{tool}_failed", error=exc.code or "connection")
    if exc.code is None:
        return {"error": detalle}
    if exc.code == "unknown_command":
        from hermes.command_table import TABLE_HA_CORE
        return {
            "error": "unsupported_by_ha_version",
            "detail": ("The installed Home Assistant does not know this command; "
                       f"Hermes' table is for {TABLE_HA_CORE}."),
            "ha_code": exc.code,
            "table_ha_core": TABLE_HA_CORE,
        }
    return {"error": "ha_error", "ha_code": exc.code, "detail": detalle}


async def _leer_expuestas(ha_client: HAClient) -> dict[str, list[str]]:
    """`{entity_id: [asistentes ordenados]}` de las expuestas (ajuste guardado)."""
    raw: Any = await ha_client.ws_send({"type": "homeassistant/expose_entity/list"})
    expuestas = raw.get("exposed_entities") if isinstance(raw, dict) else None
    if not isinstance(expuestas, dict):
        raise HAConnectionError(
            "unexpected response from homeassistant/expose_entity/list")
    return {
        eid: sorted(a for a, v in asis.items() if v is True and a in ASISTENTES)
        for eid, asis in expuestas.items()
        if isinstance(eid, str) and isinstance(asis, dict)
    }


async def _leer_nuevas(ha_client: HAClient, asistente: str) -> bool:
    raw: Any = await ha_client.ws_send(
        {"type": "homeassistant/expose_new_entities/get", "assistant": asistente})
    valor = raw.get("expose_new") if isinstance(raw, dict) else None
    if not isinstance(valor, bool):
        raise HAConnectionError(
            "unexpected response from homeassistant/expose_new_entities/get")
    return valor


def _lista_de_textos(valor: Any) -> bool:
    return isinstance(valor, list) and all(isinstance(v, str) for v in valor)


def register(mcp: object, ha_client: HAClient, *, response_max_bytes: int) -> None:
    """Registra las tools de exposición a asistentes."""

    ready = requires_ready(ha_client)

    # ── ha_list_exposed_entities ──────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_exposed_entities(
        assistant: str | None = None,
        domain: str | None = None,
    ) -> object:
        """List which entities are exposed to each voice assistant.

        Assistants: "conversation" (Assist, every conversation agent, also
        cloud LLM agents, and the MCP Server integration), "cloud.alexa" and
        "cloud.google_assistant" (Amazon and Google through Home Assistant
        Cloud). Lists the entities with a stored "exposed" setting; hidden
        ones are not listed. expose_new says, per assistant, whether new
        entities are exposed automatically: with it on, an entity of a domain
        exposed by default may be exposed without being listed until Home
        Assistant stores its setting. Changes nothing.

        Args:
            assistant: Only entities exposed to this assistant.
            domain: Only entities of this domain (e.g. "light").

        Returns:
            {"expose_new": {assistant: bool}, "total": exposed entities before
             filtering, "count", "items": [{entity_id, assistants}],
             "truncated"} ordered by entity_id.
        """
        tool = "ha_list_exposed_entities"
        if assistant is not None and assistant not in ASISTENTES:
            return _invalido(tool, "assistant", "must be one of: " + ", ".join(ASISTENTES))
        if domain is not None and (not isinstance(domain, str) or not _DOMINIO.match(domain)):
            return _invalido(tool, "domain", "must be a domain like 'light'")
        try:
            expuestas = await _leer_expuestas(ha_client)
            nuevas = {a: await _leer_nuevas(ha_client, a) for a in ASISTENTES}
        except HAConnectionError as exc:
            return _error_ha(tool, exc)

        expuestas = {e: a for e, a in expuestas.items() if a}
        total = len(expuestas)
        items = [
            {"entity_id": eid, "assistants": asis}
            for eid, asis in sorted(expuestas.items())
            if (assistant is None or assistant in asis)
            and (domain is None or eid.split(".", 1)[0] == domain)
        ]
        filtradas = len(items)

        def construir(lista: list[Any], recortada: bool) -> dict[str, Any]:
            out = sobre_de_lista(lista, truncated=recortada, expose_new=nuevas, total=total)
            if recortada:
                out["_response_limit"] = {
                    "list": "items", "returned": len(lista), "total": filtradas,
                    "max_bytes": response_max_bytes, "hint": _LIMIT_HINT,
                }
            return out

        respuesta = ajustar_lista_a_bytes(items, construir, response_max_bytes)
        logger.info(f"{tool}_ok", count=respuesta["count"], total=total,
                    assistant=assistant, domain=domain)
        return respuesta

    # ── ha_set_entity_exposure ────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_set_entity_exposure(
        entity_ids: list[str],
        assistants: list[str],
        expose: bool,
        confirmation_token: str | None = None,
    ) -> object:
        """Expose entities to voice assistants, or hide them.

        expose=true asks for confirmation (two steps): without
        confirmation_token returns a preview per assistant (which entities
        change, which were already exposed, the warning of each assistant and
        the entities of sensitive domains: locks, alarms, covers, valves) and
        a token; repeat the same call with the token to apply. Exposing to
        cloud.alexa or cloud.google_assistant sends the entities to Amazon or
        Google through Home Assistant Cloud. expose=false hides them at once,
        without a token (it only reduces what assistants can see; a token
        passed with it is ignored). Every entity must exist.

        Args:
            entity_ids: 1 to 200 entity ids (repeated ones are ignored).
            assistants: 1 to 3 of "conversation", "cloud.alexa",
                "cloud.google_assistant".
            expose: true to expose, false to hide.
            confirmation_token: Token from the preview call (only to expose).

        Returns:
            Preview + token; {"result": "ok", "expose", "changed_entity_ids"}
            (the ones Home Assistant reports as changed);
            {"result": "no_changes"} when exposing entities already exposed;
            {"error": "not_found", "missing": [...]}; or {"error": ...}.
        """
        tool = "ha_set_entity_exposure"
        if not _lista_de_textos(entity_ids) or not entity_ids:
            return _invalido(tool, "entity_ids", "must be a non-empty list of entity ids")
        malas = [e for e in entity_ids if not _ENTIDAD.match(e)]
        if malas:
            return _invalido(tool, "entity_ids", "every item must look like 'light.salon'")
        # Repetidos fuera y orden fijo ANTES de atar el token: la misma lista
        # en otro orden es la misma acción.
        ids = sorted(set(entity_ids))
        if len(ids) > _MAX_ENTIDADES:
            return _invalido(tool, "entity_ids", f"at most {_MAX_ENTIDADES} entities per call")
        if (not _lista_de_textos(assistants) or not assistants
                or any(a not in ASISTENTES for a in assistants)):
            return _invalido(tool, "assistants",
                             "must be a non-empty list of: " + ", ".join(ASISTENTES))
        asis = sorted(set(assistants))
        if not isinstance(expose, bool):
            return _invalido(tool, "expose", "must be true or false")

        try:
            faltan = [e for e in ids if not await entity_exists(ha_client, e)]
        except HAConnectionError as exc:
            return _error_ha(tool, exc)
        if faltan:
            logger.info(f"{tool}_failed", error="not_found", missing=len(faltan))
            return {"error": "not_found", "missing": faltan}

        args = {"entity_ids": ids, "assistants": asis, "expose": expose}

        if not expose:
            # Ocultar: a la primera (ver el docstring del módulo).
            return await _escribir(tool, ids, asis, False, None)

        try:
            expuestas = await _leer_expuestas(ha_client)
        except HAConnectionError as exc:
            logger.warning(f"{tool}_failed", error="preview_unavailable")
            return {"error": "preview_unavailable", "detail": redact_secrets(str(exc))}
        # Estado atado: la exposición actual de las entidades pedidas en los
        # asistentes pedidos.
        estado = {e: [a for a in expuestas.get(e, []) if a in asis] for e in ids}

        if not confirmation_token:
            por_asistente = {}
            for a in asis:
                ya = [e for e in ids if a in estado[e]]
                cambia = [e for e in ids if a not in estado[e]]
                por_asistente[a] = {"change": cambia, "already": ya,
                                    "warning": _AVISO_EXPONER[a]}
            if not any(v["change"] for v in por_asistente.values()):
                logger.info(f"{tool}_ok", step="preview", result="no_changes",
                            entities=len(ids), assistants=asis)
                return {"result": "no_changes"}
            preview = {
                "action": "set_entity_exposure",
                "expose": True,
                "by_assistant": por_asistente,
                "sensitive": [e for e in ids if e.split(".", 1)[0] in _SENSIBLES],
            }
            logger.info(f"{tool}_ok", step="preview", entities=len(ids), assistants=asis)
            return await create_confirmation_token(tool, args, preview=preview, estado=estado)

        valido, error, _ = await resolve_confirmation_token(
            confirmation_token, tool, args, estado=estado)
        if not valido:
            logger.warning(f"{tool}_failed", step="confirm",
                           error="state_changed" if error == ESTADO_CAMBIADO else "token_invalid")
            return {"error": error}
        return await _escribir(tool, ids, asis, True, confirmation_token)

    async def _escribir(
        tool: str, ids: list[str], asis: list[str], expose: bool, token: str | None,
    ) -> dict[str, Any]:
        try:
            raw: Any = await ha_client.ws_send({
                "type": "homeassistant/expose_entity",
                "entity_ids": ids, "assistants": asis, "should_expose": expose,
            })
        except HAConnectionError as exc:
            fallo = _error_ha(tool, exc)
            if token:
                await complete_confirmation_token(token, success=False,
                                                  error=str(fallo["error"]))
            return fallo
        cambiadas = raw.get("changed_entity_ids") if isinstance(raw, dict) else None
        cambiadas = sorted(cambiadas) if _lista_de_textos(cambiadas) else []
        resultado = {"result": "ok", "expose": expose, "changed_entity_ids": cambiadas}
        if token:
            await complete_confirmation_token(token, success=True, result=resultado)
        logger.info(f"{tool}_ok", step="confirm" if token else "apply", expose=expose,
                    entities=len(ids), changed=len(cambiadas), assistants=asis)
        return resultado

    # ── ha_set_expose_new_entities ────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_set_expose_new_entities(
        assistant: str,
        expose_new: bool,
        confirmation_token: str | None = None,
    ) -> object:
        """Choose whether entities created from now on are exposed to an assistant.

        Does not change existing entities (use ha_set_entity_exposure).
        expose_new=true asks for confirmation (two steps): without
        confirmation_token returns a preview (current and new value and the
        assistant's warning) and a token; repeat the same call with the token
        to apply. expose_new=false applies at once, without a token (it only
        reduces what the assistant gets; a token passed with it is ignored).

        Args:
            assistant: "conversation", "cloud.alexa" or "cloud.google_assistant".
            expose_new: true or false.
            confirmation_token: Token from the preview call (only for true).

        Returns:
            Preview + token; {"result": "ok", "assistant", "expose_new"};
            {"result": "no_changes"}; or {"error": ...}.
        """
        tool = "ha_set_expose_new_entities"
        if assistant not in ASISTENTES:
            return _invalido(tool, "assistant", "must be one of: " + ", ".join(ASISTENTES))
        if not isinstance(expose_new, bool):
            return _invalido(tool, "expose_new", "must be true or false")
        args = {"assistant": assistant, "expose_new": expose_new}
        try:
            antes = await _leer_nuevas(ha_client, assistant)
        except HAConnectionError as exc:
            if exc.code == "unknown_command":
                return _error_ha(tool, exc)
            logger.warning(f"{tool}_failed", error="preview_unavailable")
            return {"error": "preview_unavailable", "detail": redact_secrets(str(exc))}
        if antes == expose_new:
            logger.info(f"{tool}_ok", result="no_changes", assistant=assistant)
            return {"result": "no_changes"}

        if expose_new and not confirmation_token:
            preview = {"action": "set_expose_new_entities", "assistant": assistant,
                       "before": antes, "after": True, "warning": _AVISO_NUEVAS[assistant]}
            logger.info(f"{tool}_ok", step="preview", assistant=assistant)
            return await create_confirmation_token(tool, args, preview=preview, estado=antes)

        if expose_new:
            valido, error, _ = await resolve_confirmation_token(
                confirmation_token, tool, args, estado=antes)
            if not valido:
                logger.warning(f"{tool}_failed", step="confirm",
                               error="state_changed" if error == ESTADO_CAMBIADO
                               else "token_invalid")
                return {"error": error}
        token = confirmation_token if expose_new else None
        try:
            await ha_client.ws_send({"type": "homeassistant/expose_new_entities/set",
                                     "assistant": assistant, "expose_new": expose_new})
        except HAConnectionError as exc:
            fallo = _error_ha(tool, exc)
            if token:
                await complete_confirmation_token(token, success=False,
                                                  error=str(fallo["error"]))
            return fallo
        resultado = {"result": "ok", "assistant": assistant, "expose_new": expose_new}
        if token:
            await complete_confirmation_token(token, success=True, result=resultado)
        logger.info(f"{tool}_ok", step="confirm" if token else "apply",
                    assistant=assistant, expose_new=expose_new)
        return resultado
