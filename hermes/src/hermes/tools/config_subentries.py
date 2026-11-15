"""Hermes — Tools MCP de subentries y del reconfigure de una entrada (spec 016,
tramo B; CAP-045 de la 008).

- `ha_list_config_subentries` — subentries de una entrada y tipos admitidos.
- `ha_start_subentry_flow` / `ha_continue_subentry_flow` /
  `ha_abort_subentry_flow` — crear o reconfigurar una subentry por su flujo
  (`/api/config/config_entries/subentries/flow`). Sin token, como los flujos
  de configuración y de opciones de la 1.1.2.
- `ha_update_subentry` — título de una subentry. Sin token.
- `ha_delete_subentry` — borrar una subentry, en dos pasos: HA se lleva con
  ella sus entidades y dispositivos, y la vista previa los enumera.
- `ha_start_reconfigure_flow` / `ha_continue_reconfigure_flow` — reconfigure
  de la entrada. Decisión del supervisor: cada paso que se envía pide token
  (puede cambiar credenciales y HA recarga la integración al terminar). Los
  `flow_id` que abre Hermes van al registro de `_reconfigure.py`, y
  `ha_continue_config_entry_flow` los rechaza.

Lo que llega de HA y puede llevar datos de terceros (títulos, esquemas de
formulario con valores sugeridos, errores) sale redactado. Al log van ids,
dominios, tipos y recuentos; nunca `user_input` ni títulos (principio II).
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    es_clave_sensible,
    redact_secrets,
    validate_confirmation_token,
)
from hermes.tools import _reconfigure
from hermes.tools._common import ajustar_lista_a_bytes, requires_ready
from hermes.tools._validation import InvalidIdentifier, validate_identifier
from hermes.tools.config_entry_flows import _NON_AUTOMATABLE_TYPES
from hermes.tools.integration_setup import _error_ha, _error_titulo, _invalid
# Tapado de secretos de los formularios: vive en `_flujos` desde el tramo C,
# que lo comparte con los flujos de reparación y con los `reauth` de la tool
# general (que no puede importar este módulo sin un ciclo).
from hermes.tools._flujos import (  # noqa: F401
    _ERROR_MARCADOR,
    _campos_secretos,
    _lleva_marcador,
    _tapar_resultado,
    _tapar_user_input,
)

logger = structlog.get_logger(__name__)

# Forma del tipo de subentry: la de un identificador de traducción de HA.
_TIPO = re.compile(r"^[a-z0-9_]+$")

# Tope de cada lista (entidades, dispositivos) en la vista previa de borrar
# una subentry: con el recuento total, la vista previa no miente por omisión
# y cabe en `response_max_bytes`.
_MAX_EN_VISTA = 50

_RUTA_SUBFLUJOS = "/config/config_entries/subentries/flow"
_RUTA_FLUJOS = "/config/config_entries/flow"

_HINT_NO_AUTOMATIZABLE = (
    "This flow requires external interaction ({tipo}). It cannot be completed "
    "via MCP. The flow has been aborted automatically to avoid leaving "
    "orphaned flows in Home Assistant. Do it from the HA UI: Settings → "
    "Devices & services.")

_CONTINUE_RECONFIGURE = (
    "ha_continue_reconfigure_flow (two steps on every step: preview, then "
    "confirmation_token)")

_EFECTO_RECONFIGURE = (
    "Submits this step of the reconfigure flow of this config entry. When the "
    "flow finishes, the integration usually saves the new data (which may "
    "include credentials or connection details) and Home Assistant reloads "
    "it: its entities are unavailable for a moment, and wrong data can leave "
    "it failing to load. Home Assistant does not say in advance whether this "
    "step is the last one.")

_EFECTO_BORRAR = (
    "Deletes this subentry. Home Assistant also deletes the entities and "
    "devices listed here (devices that belong to this subentry, and their "
    "child devices, with their entities). The integration may reload. Not "
    "reversible: to get it back, create the subentry again with its flow.")


# ── Ayudantes ─────────────────────────────────────────────────────────────────


def _validar_id(valor: Any, campo: str) -> str | None:
    try:
        validate_identifier(valor, field=campo)
    except InvalidIdentifier as exc:
        return _invalid(campo, str(exc))
    return None


def _texto(valor: Any) -> Any:
    return redact_secrets(valor) if isinstance(valor, str) else valor


async def _leer_entrada(ha_client: HAClient, entry_id: str) -> dict[str, Any] | None:
    """La entrada, o `None` si HA dice que no existe. Lanza en otro fallo."""
    try:
        raw: Any = await ha_client.ws_send(
            {"type": "config_entries/get_single", "entry_id": entry_id})
    except HAConnectionError as exc:
        if exc.code == "not_found":
            return None
        raise
    entrada = raw.get("config_entry") if isinstance(raw, dict) else None
    if not isinstance(entrada, dict):
        raise HAConnectionError("unexpected_response")
    return entrada


async def _leer_subentries(ha_client: HAClient, entry_id: str) -> list[dict[str, Any]]:
    raw: Any = await ha_client.ws_send(
        {"type": "config_entries/subentries/list", "entry_id": entry_id})
    if not isinstance(raw, list):
        raise HAConnectionError("unexpected_response")
    return [s for s in raw if isinstance(s, dict)]


async def _abortar(ha_client: HAClient, ruta: str) -> None:
    """DELETE best-effort de un flujo (como `_abort_flow` de la 1.1.2)."""
    try:
        await ha_client._request_json("DELETE", ruta)  # noqa: SLF001
    except HAConnectionError as exc:
        logger.warning("flow_abort_failed", path=ruta, error=_error_ha(exc))


def _no_automatizable(tipo: str, flow_id: Any) -> str:
    return json.dumps({
        "error": "non_automatable", "type": tipo, "flow_id": flow_id,
        "hint": _HINT_NO_AUTOMATIZABLE.format(tipo=tipo),
    })


def _recorte(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"count": len(items), "items": items[:_MAX_EN_VISTA],
            "truncated": len(items) > _MAX_EN_VISTA}


def _del_subentry_dispositivo(d: dict[str, Any], entry_id: str, subentry_id: str) -> bool:
    # HA 2026.11.1 tiene las dos formas: el modelo nuevo (`config_entry_id` y
    # `config_subentry_id`, uno por dispositivo) y la compatibilidad
    # (`config_entries_subentries`, que se quita en 2027.8). Vale cualquiera.
    if d.get("config_entry_id") == entry_id and d.get("config_subentry_id") == subentry_id:
        return True
    mapa = d.get("config_entries_subentries")
    if isinstance(mapa, dict):
        subs = mapa.get(entry_id)
        return isinstance(subs, list) and subentry_id in subs
    return False


def register(
    mcp: object,
    ha_client: HAClient,
    *,
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
) -> None:
    """Registra las tools de subentries y del reconfigure de una entrada."""

    ready = requires_ready(ha_client)

    # ── ha_list_config_subentries ─────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_config_subentries(entry_id: str) -> object:
        """List the subentries of a config entry and the types it can add.

        Subentries are parts of one integration entry with their own title,
        data, entities and devices (for example, one item per location or per
        model). `supported_subentry_types` maps each type the entry can add to
        {"supports_reconfigure": bool}; add one with ha_start_subentry_flow.

        Args:
            entry_id: Config entry id (ha_list_config_entries).

        Returns:
            JSON {"entry_id", "domain", "supported_subentry_types", "count",
            "truncated", "items": [{subentry_id, subentry_type, title,
            unique_id}]}, or {"error": ...}.
        """
        if (err := _validar_id(entry_id, "entry_id")):
            return err
        try:
            entrada = await _leer_entrada(ha_client, entry_id)
            if entrada is None:
                return json.dumps({"error": "not_found", "entry_id": entry_id})
            subs = await _leer_subentries(ha_client, entry_id)
        except HAConnectionError as exc:
            logger.error("ha_list_config_subentries_ws_error", entry_id=entry_id,
                         error=_error_ha(exc))
            if str(exc) == "unexpected_response":
                return json.dumps({"error": "unexpected_response"})
            return json.dumps({"error": _error_ha(exc)})

        items = [{
            "subentry_id": s.get("subentry_id"),
            "subentry_type": s.get("subentry_type"),
            "title": _texto(s.get("title")),
            "unique_id": _texto(s.get("unique_id")),
        } for s in subs]
        items.sort(key=lambda i: (str(i["subentry_type"]), str(i["subentry_id"])))
        tipos = entrada.get("supported_subentry_types")
        total = len(items)

        def construir(kept: list[Any], cut: bool) -> dict[str, Any]:
            out: dict[str, Any] = {
                "entry_id": entry_id, "domain": entrada.get("domain"),
                "supported_subentry_types": tipos if isinstance(tipos, dict) else {},
                "count": total, "truncated": cut, "items": kept,
            }
            if cut:
                out["returned"] = len(kept)
            return out

        logger.info("ha_list_config_subentries_ok", entry_id=entry_id, count=total)
        return json.dumps(ajustar_lista_a_bytes(items, construir, response_max_bytes),
                          ensure_ascii=False)

    # ── ha_start_subentry_flow ────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_start_subentry_flow(
        entry_id: str, subentry_type: str, subentry_id: str | None = None,
    ) -> object:
        """Start the flow that adds a subentry to a config entry, or reconfigures one.

        Without subentry_id it adds a new subentry of subentry_type; with
        subentry_id it reconfigures that subentry (its type must allow it:
        see ha_list_config_subentries). Continue with
        ha_continue_subentry_flow and close it with ha_abort_subentry_flow.
        No confirmation token: like the config and options flows. Flows that
        need an external login (OAuth) are aborted and reported. Values the
        form suggests for password fields are redacted.

        Args:
            entry_id: Config entry id.
            subentry_type: A type from supported_subentry_types.
            subentry_id: Subentry to reconfigure (optional).

        Returns:
            The flow step from HA (flow_id, type, step_id, data_schema…), with
            "status": "ok" on create_entry; or {"error": "not_found" |
            "subentry_type_not_supported" | "reconfigure_not_supported" |
            "non_automatable" | "invalid_argument" | ...}.
        """
        if (err := _validar_id(entry_id, "entry_id")):
            return err
        if not isinstance(subentry_type, str) or not _TIPO.match(subentry_type):
            return _invalid("subentry_type", "must be lowercase letters, digits and '_'")
        if subentry_id is not None and (err := _validar_id(subentry_id, "subentry_id")):
            return err

        # Comprobaciones previas: ninguna abre un flujo si falla (principio III).
        try:
            entrada = await _leer_entrada(ha_client, entry_id)
            if entrada is None:
                return json.dumps({"error": "not_found", "entry_id": entry_id})
            tipos = entrada.get("supported_subentry_types")
            tipos = tipos if isinstance(tipos, dict) else {}
            if subentry_type not in tipos:
                return json.dumps({"error": "subentry_type_not_supported",
                                   "subentry_type": subentry_type,
                                   "supported": sorted(tipos)})
            if subentry_id is not None:
                subs = await _leer_subentries(ha_client, entry_id)
                sub = next((s for s in subs if s.get("subentry_id") == subentry_id), None)
                if sub is None:
                    return json.dumps({"error": "not_found", "subentry_id": subentry_id})
                if sub.get("subentry_type") != subentry_type:
                    return _invalid("subentry_id",
                                    f"this subentry is of type {sub.get('subentry_type')!r}")
                info = tipos.get(subentry_type)
                if not (isinstance(info, dict) and info.get("supports_reconfigure")):
                    return json.dumps({"error": "reconfigure_not_supported",
                                       "subentry_type": subentry_type})
        except HAConnectionError as exc:
            logger.error("ha_start_subentry_flow_ws_error", entry_id=entry_id,
                         error=_error_ha(exc))
            return json.dumps({"error": _error_ha(exc)})

        cuerpo: dict[str, Any] = {"handler": [entry_id, subentry_type]}
        if subentry_id is not None:
            cuerpo["subentry_id"] = subentry_id
        try:
            raw: Any = await ha_client._request_json(  # noqa: SLF001
                "POST", _RUTA_SUBFLUJOS, json_body=cuerpo)
        except HAConnectionError as exc:
            logger.error("ha_start_subentry_flow_rest_error", entry_id=entry_id,
                         subentry_type=subentry_type, error=_error_ha(exc))
            return json.dumps({"error": _error_ha(exc)})
        return await _resultado_subflujo(raw, "ha_start_subentry_flow",
                                         entry_id=entry_id, subentry_type=subentry_type)

    async def _resultado_subflujo(raw: Any, tool: str, **log: Any) -> str:
        if not isinstance(raw, dict):
            return json.dumps({"error": "unexpected_response"})
        tipo = raw.get("type", "")
        flow_id = raw.get("flow_id", "")
        if tipo in _NON_AUTOMATABLE_TYPES:
            if flow_id and _validar_id(flow_id, "flow_id") is None:
                await _abortar(ha_client, f"{_RUTA_SUBFLUJOS}/{flow_id}")
            logger.warning(f"{tool}_non_automatable", flow_type=tipo, flow_id=flow_id, **log)
            return _no_automatizable(tipo, flow_id)
        resultado = _tapar_resultado(raw)
        if tipo == "create_entry":
            resultado["status"] = "ok"
        logger.info(f"{tool}_ok", flow_type=tipo, flow_id=flow_id, **log)
        return json.dumps(resultado, ensure_ascii=False)

    # ── ha_continue_subentry_flow ─────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_continue_subentry_flow(flow_id: str, user_input: dict[str, Any]) -> object:
        """Submit a step of a subentry flow opened with ha_start_subentry_flow.

        On create_entry HA adds the subentry (the integration may reload to
        create its entities); a reconfigure usually ends in "abort" with
        reason "reconfigure_successful". No confirmation token. Values equal
        to the redaction marker are refused: they would be saved as is.

        Args:
            flow_id: Flow id from ha_start_subentry_flow.
            user_input: Values for the fields of the current step.

        Returns:
            The next step or the end of the flow, with "status": "ok" on
            create_entry; or {"error": ...}.
        """
        if (err := _validar_id(flow_id, "flow_id")):
            return err
        if not isinstance(user_input, dict):
            return _invalid("user_input", "must be an object")
        if _lleva_marcador(user_input):
            return _invalid("user_input", _ERROR_MARCADOR)
        try:
            raw: Any = await ha_client._request_json(  # noqa: SLF001
                "POST", f"{_RUTA_SUBFLUJOS}/{flow_id}", json_body=user_input)
        except HAConnectionError as exc:
            logger.error("ha_continue_subentry_flow_rest_error", flow_id=flow_id,
                         status=exc.status, error=_error_ha(exc))
            if exc.status == 404:
                return json.dumps({"error": "not_found", "flow_id": flow_id})
            return json.dumps({"error": _error_ha(exc)})
        return await _resultado_subflujo(raw, "ha_continue_subentry_flow", flow_id_pedido=flow_id)

    # ── ha_abort_subentry_flow ────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_abort_subentry_flow(flow_id: str) -> object:
        """Abort a subentry flow that is still open. Changes nothing else.

        Args:
            flow_id: Flow id from ha_start_subentry_flow.

        Returns:
            {"result": "ok"}, or {"error": "not_found" | ...}.
        """
        if (err := _validar_id(flow_id, "flow_id")):
            return err
        try:
            await ha_client._request_json("DELETE", f"{_RUTA_SUBFLUJOS}/{flow_id}")  # noqa: SLF001
        except HAConnectionError as exc:
            logger.error("ha_abort_subentry_flow_rest_error", flow_id=flow_id,
                         status=exc.status, error=_error_ha(exc))
            if exc.status == 404:
                return json.dumps({"error": "not_found", "flow_id": flow_id})
            return json.dumps({"error": _error_ha(exc)})
        logger.info("ha_abort_subentry_flow_ok", flow_id=flow_id)
        return json.dumps({"result": "ok"})

    # ── ha_update_subentry ────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_update_subentry(entry_id: str, subentry_id: str, title: str) -> object:
        """Rename a subentry. Its data are changed with its reconfigure flow.

        No confirmation token: renaming changes no behaviour.

        Args:
            entry_id: Config entry id.
            subentry_id: Subentry id (ha_list_config_subentries).
            title: New title (at most 255 characters).

        Returns:
            {"result": "ok", "subentry_id", "title"}, {"result": "unchanged"},
            or {"error": "not_found" | "invalid_argument" | ...}.
        """
        if (err := _validar_id(entry_id, "entry_id")) or (err := _validar_id(subentry_id, "subentry_id")):
            return err
        if (problema := _error_titulo(title)):
            return _invalid("title", problema)
        try:
            if await _leer_entrada(ha_client, entry_id) is None:
                return json.dumps({"error": "not_found", "entry_id": entry_id})
            subs = await _leer_subentries(ha_client, entry_id)
        except HAConnectionError as exc:
            logger.error("ha_update_subentry_ws_error", entry_id=entry_id, error=_error_ha(exc))
            return json.dumps({"error": _error_ha(exc)})
        sub = next((s for s in subs if s.get("subentry_id") == subentry_id), None)
        if sub is None:
            return json.dumps({"error": "not_found", "subentry_id": subentry_id})
        if sub.get("title") == title:
            return json.dumps({"result": "unchanged"})
        try:
            await ha_client.ws_send({"type": "config_entries/subentries/update",
                                     "entry_id": entry_id, "subentry_id": subentry_id,
                                     "title": title})
        except HAConnectionError as exc:
            logger.error("ha_update_subentry_ws_error", entry_id=entry_id,
                         subentry_id=subentry_id, code=exc.code, error=_error_ha(exc))
            if exc.code == "not_found":
                return json.dumps({"error": "not_found", "subentry_id": subentry_id})
            return json.dumps({"error": _error_ha(exc)})
        logger.info("ha_update_subentry_ok", entry_id=entry_id, subentry_id=subentry_id)
        return json.dumps({"result": "ok", "subentry_id": subentry_id,
                           "title": redact_secrets(title)}, ensure_ascii=False)

    # ── ha_delete_subentry ────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_delete_subentry(
        entry_id: str, subentry_id: str, confirmation_token: str | None = None,
    ) -> object:
        """Delete a subentry of a config entry (two steps).

        Home Assistant also deletes the devices that belong to the subentry
        (with their child devices) and its entities; the integration may
        reload. Not reversible. Without confirmation_token it returns a
        preview listing those entities and devices, and a token; repeat the
        same call with the token to delete.

        Args:
            entry_id: Config entry id.
            subentry_id: Subentry id (ha_list_config_subentries).
            confirmation_token: Token from the preview call.

        Returns:
            A preview with confirmation_token, {"result": "ok"}, or
            {"error": "not_found" | "preview_unavailable" | ...}.
        """
        if (err := _validar_id(entry_id, "entry_id")) or (err := _validar_id(subentry_id, "subentry_id")):
            return err
        args = {"entry_id": entry_id, "subentry_id": subentry_id}

        if not confirmation_token:
            try:
                entrada = await _leer_entrada(ha_client, entry_id)
                if entrada is None:
                    return json.dumps({"error": "not_found", "entry_id": entry_id})
                subs = await _leer_subentries(ha_client, entry_id)
                sub = next((s for s in subs if s.get("subentry_id") == subentry_id), None)
                if sub is None:
                    return json.dumps({"error": "not_found", "subentry_id": subentry_id})
                entidades = await ha_client.ws_send({"type": "config/entity_registry/list"})
                dispositivos = await ha_client.ws_send({"type": "config/device_registry/list"})
                if not isinstance(entidades, list) or not isinstance(dispositivos, list):
                    raise HAConnectionError("unexpected_response")
            except HAConnectionError as exc:
                # Sin la lista de lo que HA se lleva con la subentry, la
                # vista previa mentiría por omisión: no se emite token.
                logger.warning("ha_delete_subentry_preview_read_failed",
                               entry_id=entry_id, subentry_id=subentry_id, error=_error_ha(exc))
                return json.dumps({"error": "preview_unavailable", "detail": _error_ha(exc)})

            ents = sorted((
                {"entity_id": e.get("entity_id"),
                 "name": _texto(e.get("name") or e.get("original_name"))}
                for e in entidades if isinstance(e, dict)
                and e.get("config_entry_id") == entry_id
                and e.get("config_subentry_id") == subentry_id),
                key=lambda e: str(e["entity_id"]))
            devs = sorted((
                {"id": d.get("id"), "name": _texto(d.get("name_by_user") or d.get("name"))}
                for d in dispositivos if isinstance(d, dict)
                and _del_subentry_dispositivo(d, entry_id, subentry_id)),
                key=lambda d: str(d["id"]))
            preview = {
                "entry": {"entry_id": entry_id, "domain": entrada.get("domain"),
                          "title": _texto(entrada.get("title"))},
                "subentry": {"subentry_id": subentry_id,
                             "subentry_type": sub.get("subentry_type"),
                             "title": _texto(sub.get("title"))},
                "entities": _recorte(ents),
                "devices": _recorte(devs),
                "effect": _EFECTO_BORRAR,
            }
            token_data = await create_confirmation_token("ha_delete_subentry", args, preview=preview)
            logger.info("ha_delete_subentry_preview", entry_id=entry_id, subentry_id=subentry_id,
                        entities=len(ents), devices=len(devs))
            return json.dumps(token_data, ensure_ascii=False)

        valido, error = await validate_confirmation_token(
            confirmation_token, "ha_delete_subentry", args)
        if not valido:
            logger.warning("ha_delete_subentry_token_invalid", entry_id=entry_id,
                           subentry_id=subentry_id, reason=error)
            return json.dumps({"error": error})
        try:
            await ha_client.ws_send({"type": "config_entries/subentries/delete",
                                     "entry_id": entry_id, "subentry_id": subentry_id})
        except HAConnectionError as exc:
            logger.error("ha_delete_subentry_ws_error", entry_id=entry_id,
                         subentry_id=subentry_id, code=exc.code, error=_error_ha(exc))
            await complete_confirmation_token(confirmation_token, success=False,
                                              error=_error_ha(exc))
            if exc.code == "not_found":
                return json.dumps({"error": "not_found", "subentry_id": subentry_id})
            return json.dumps({"error": _error_ha(exc)})
        await complete_confirmation_token(confirmation_token, success=True,
                                          result={"result": "ok"})
        logger.info("ha_delete_subentry_ok", entry_id=entry_id, subentry_id=subentry_id)
        return json.dumps({"result": "ok"})

    # ── ha_start_reconfigure_flow ─────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_start_reconfigure_flow(entry_id: str) -> object:
        """Start the reconfigure flow of a config entry (as "Reconfigure" in the UI).

        Only for entries with supports_reconfigure true. It opens the flow and
        returns its first step; it changes nothing yet. Continue it ONLY with
        ha_continue_reconfigure_flow, which needs a preview and a
        confirmation token on every step, because reconfiguring can change the
        entry's credentials or connection details and HA reloads the
        integration at the end. ha_continue_config_entry_flow refuses these
        flows. Abort with ha_abort_config_entry_flow. Flows that need an
        external login (OAuth) are aborted and reported. Values the form
        suggests for password fields are redacted.

        Args:
            entry_id: Config entry id (ha_list_config_entries).

        Returns:
            The first step from HA plus "entry" and "continue_with"; or
            {"error": "not_found" | "reconfigure_not_supported" |
            "non_automatable" | ...}.
        """
        if (err := _validar_id(entry_id, "entry_id")):
            return err
        await _reconfigure.barrer(ha_client)
        try:
            entrada = await _leer_entrada(ha_client, entry_id)
        except HAConnectionError as exc:
            logger.error("ha_start_reconfigure_flow_ws_error", entry_id=entry_id,
                         error=_error_ha(exc))
            return json.dumps({"error": _error_ha(exc)})
        if entrada is None:
            return json.dumps({"error": "not_found", "entry_id": entry_id})
        dominio = entrada.get("domain")
        if not entrada.get("supports_reconfigure"):
            return json.dumps({"error": "reconfigure_not_supported", "entry_id": entry_id,
                               "domain": dominio})

        try:
            raw: Any = await ha_client._request_json(  # noqa: SLF001
                "POST", _RUTA_FLUJOS, json_body={"handler": dominio, "entry_id": entry_id})
        except HAConnectionError as exc:
            logger.error("ha_start_reconfigure_flow_rest_error", entry_id=entry_id,
                         domain=dominio, error=_error_ha(exc))
            return json.dumps({"error": _error_ha(exc)})
        if not isinstance(raw, dict):
            return json.dumps({"error": "unexpected_response"})

        tipo = raw.get("type", "")
        flow_id = raw.get("flow_id", "")
        id_valido = isinstance(flow_id, str) and _validar_id(flow_id, "flow_id") is None
        if tipo in _NON_AUTOMATABLE_TYPES:
            if id_valido:
                await _abortar(ha_client, f"{_RUTA_FLUJOS}/{flow_id}")
            logger.warning("ha_start_reconfigure_flow_non_automatable", entry_id=entry_id,
                           flow_type=tipo, flow_id=flow_id)
            return _no_automatizable(tipo, flow_id)

        resultado = _tapar_resultado(raw)
        resultado["entry"] = {"entry_id": entry_id, "domain": dominio,
                              "title": _texto(entrada.get("title"))}
        if tipo in ("form", "menu"):
            if not id_valido:
                # Un flujo abierto que no se puede registrar no se deja
                # abierto: la tool general no sabría rechazarlo.
                return json.dumps({"error": "unexpected_response"})
            _reconfigure.registrar(flow_id, entry_id, str(dominio), entrada.get("title"))
            resultado["continue_with"] = _CONTINUE_RECONFIGURE
        elif tipo == "create_entry" or (tipo == "abort" and raw.get("reason") == "reconfigure_successful"):
            resultado["status"] = "ok"
        logger.info("ha_start_reconfigure_flow_ok", entry_id=entry_id, domain=dominio,
                    flow_type=tipo, flow_id=flow_id)
        return json.dumps(resultado, ensure_ascii=False)

    # ── ha_continue_reconfigure_flow ──────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_continue_reconfigure_flow(
        flow_id: str,
        user_input: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Submit a step of a reconfigure flow opened with ha_start_reconfigure_flow.

        Two steps on EVERY step: without confirmation_token it returns a
        preview (the entry, the current step, the values to send with
        secrets redacted, the effect) and a token; repeat the same call with
        the token to submit. Any step can finish the flow: the integration
        then saves the new data (credentials or connection details included)
        and HA reloads it. The token is bound to this flow, its current step
        and the whole user_input; if the step changed meanwhile, it is refused
        and nothing is sent. Only for flows opened by ha_start_reconfigure_flow
        since Hermes last started. A flow left idle for an hour expires:
        Hermes aborts it the next time a reconfigure flow is started or
        continued.

        Args:
            flow_id: Flow id from ha_start_reconfigure_flow.
            user_input: Values for the fields of the current step.
            confirmation_token: Token from the preview call.

        Returns:
            A preview with confirmation_token; the next step (another preview
            is needed to submit it) or the end of the flow ("status": "ok"
            when HA reports reconfigure_successful); or {"error":
            "not_a_reconfigure_flow" | "expired" | "not_found" |
            "preview_unavailable" | ...}.
        """
        if (err := _validar_id(flow_id, "flow_id")):
            return err
        if not isinstance(user_input, dict):
            return _invalid("user_input", "must be an object")
        if _lleva_marcador(user_input):
            return _invalid("user_input", _ERROR_MARCADOR)
        registro = _reconfigure.buscar(flow_id)
        if registro is None:
            return json.dumps({
                "error": "not_a_reconfigure_flow", "flow_id": flow_id,
                # T047: la pista no remite a ninguna tool que envíe un paso
                # sin token. Un reconfigure abierto antes de reiniciar Hermes
                # o desde la interfaz de HA no se puede continuar: se abre otro.
                "hint": ("Hermes does not know this flow as a reconfigure flow opened by "
                         "ha_start_reconfigure_flow in this Hermes session (for example, "
                         "it was opened before Hermes restarted, or in the Home Assistant "
                         "UI). It cannot be continued: start the reconfigure again with "
                         "ha_start_reconfigure_flow(entry_id), and abort the old flow with "
                         "ha_abort_config_entry_flow if it is still open."),
            })
        if _reconfigure.caducado(registro):
            await _reconfigure.barrer(ha_client)
            return json.dumps({
                "error": "expired", "flow_id": flow_id,
                "hint": ("This reconfigure flow was idle for too long and Hermes aborted it. "
                         "Start again with ha_start_reconfigure_flow."),
            })
        await _reconfigure.barrer(ha_client)
        ruta = f"{_RUTA_FLUJOS}/{flow_id}"

        # El paso actual se lee SIEMPRE, también al confirmar: el token se ata
        # a él, y si el flujo avanzó por otro lado entre la vista previa y la
        # confirmación, el token deja de valer y no se envía nada.
        try:
            paso: Any = await ha_client._request_json("GET", ruta)  # noqa: SLF001
        except HAConnectionError as exc:
            if exc.status == 404:
                _reconfigure.olvidar(flow_id)
                return json.dumps({"error": "not_found", "flow_id": flow_id})
            logger.warning("ha_continue_reconfigure_flow_preview_read_failed",
                           flow_id=flow_id, error=_error_ha(exc))
            return json.dumps({"error": "preview_unavailable", "detail": _error_ha(exc)})
        if not isinstance(paso, dict):
            return json.dumps({"error": "preview_unavailable", "detail": "unexpected_response"})
        step_id = paso.get("step_id")
        args = {"flow_id": flow_id, "step_id": step_id, "user_input": user_input}

        if not confirmation_token:
            esquema = paso.get("data_schema")
            secretos = _campos_secretos(esquema)
            pedidos = {c.get("name") for c in esquema if isinstance(c, dict)} \
                if isinstance(esquema, list) else set()
            preview = {
                "entry": {"entry_id": registro.entry_id, "domain": registro.domain,
                          "title": _texto(registro.title)},
                "flow_id": flow_id,
                "step_id": step_id,
                "user_input": _tapar_user_input(user_input, secretos),
                "secret_fields": sorted(k for k in user_input
                                        if k in secretos or es_clave_sensible(str(k))),
                "unknown_fields": sorted(k for k in user_input if k not in pedidos),
                "effect": _EFECTO_RECONFIGURE,
            }
            # `user_input` entra en el hash, no en el fichero del token (sin
            # omitibles): ahí no queda ningún secreto.
            token_data = await create_confirmation_token(
                "ha_continue_reconfigure_flow", args, preview=preview)
            _reconfigure.tocar(flow_id)
            logger.info("ha_continue_reconfigure_flow_preview", flow_id=flow_id,
                        entry_id=registro.entry_id, step_id=step_id, fields=sorted(user_input))
            return json.dumps(token_data, ensure_ascii=False)

        valido, error = await validate_confirmation_token(
            confirmation_token, "ha_continue_reconfigure_flow", args)
        if not valido:
            logger.warning("ha_continue_reconfigure_flow_token_invalid", flow_id=flow_id,
                           step_id=step_id, reason=error)
            return json.dumps({"error": error})

        try:
            raw: Any = await ha_client._request_json(  # noqa: SLF001
                "POST", ruta, json_body=user_input)
        except HAConnectionError as exc:
            logger.error("ha_continue_reconfigure_flow_rest_error", flow_id=flow_id,
                         status=exc.status, error=_error_ha(exc))
            await complete_confirmation_token(confirmation_token, success=False,
                                              error=_error_ha(exc))
            if exc.status == 404:
                _reconfigure.olvidar(flow_id)
                return json.dumps({"error": "not_found", "flow_id": flow_id})
            return json.dumps({"error": _error_ha(exc)})
        if not isinstance(raw, dict):
            await complete_confirmation_token(confirmation_token, success=False,
                                              error="unexpected_response")
            return json.dumps({"error": "unexpected_response"})

        tipo = raw.get("type", "")
        await complete_confirmation_token(confirmation_token, success=True,
                                          result={"type": tipo, "step_id": step_id})
        if tipo in _NON_AUTOMATABLE_TYPES:
            await _abortar(ha_client, ruta)
            _reconfigure.olvidar(flow_id)
            logger.warning("ha_continue_reconfigure_flow_non_automatable",
                           flow_id=flow_id, flow_type=tipo)
            return _no_automatizable(tipo, flow_id)
        resultado = _tapar_resultado(raw)
        if tipo in ("form", "menu"):
            _reconfigure.tocar(flow_id)
            resultado["continue_with"] = _CONTINUE_RECONFIGURE
        else:
            _reconfigure.olvidar(flow_id)
            if tipo == "create_entry" or (tipo == "abort" and raw.get("reason") == "reconfigure_successful"):
                resultado["status"] = "ok"
        logger.info("ha_continue_reconfigure_flow_ok", flow_id=flow_id,
                    entry_id=registro.entry_id, flow_type=tipo)
        return json.dumps(resultado, ensure_ascii=False)
