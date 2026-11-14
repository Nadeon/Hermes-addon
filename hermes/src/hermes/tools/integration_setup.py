"""Hermes — Tools MCP para administrar integraciones más allá de instalarlas
(spec 016, tramo A; CAP-044 de la 008).

- `ha_list_discovered_integrations` — lo que HA ha descubierto y espera a que
  alguien lo configure (`config_entries/flow/progress`).
- `ha_ignore_discovery` — ignora un descubrimiento (`config_entries/ignore_flow`).
- `ha_list_config_flow_domains` — los dominios que se configuran por flujo
  (`GET /api/config/config_entries/flow_handlers`).
- `ha_update_config_entry` — título y preferencias de una entrada
  (`config_entries/update`).

Configurar un descubierto no necesita tool nueva: su flujo se continúa con
`ha_continue_config_entry_flow`, que habla con el mismo recurso REST.

Lo que llega de HA y puede llevar datos de terceros (los `title_placeholders`
de un descubrimiento, el texto de un error) pasa por la redacción por clave y
por patrón antes de salir. Al log solo van ids, dominios, recuentos y nombres
de campos (principio II).
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
    redact_secrets,
    validate_confirmation_token,
)
from hermes.tools._common import ajustar_lista_a_bytes, redactar_datos, requires_ready
from hermes.tools._validation import InvalidIdentifier, validate_identifier

logger = structlog.get_logger(__name__)

# Forma de un dominio de integración. Se valida antes de filtrar para que una
# errata («Hue») no devuelva una lista vacía que parece verdad.
_DOMINIO = re.compile(r"^[a-z0-9_]+$")

# Los cuatro `type_filter` que admite `async_get_config_flows` en HA
# 2026.11.1. HA no valida el valor: con otro devolvería una lista vacía, que
# también parecería verdad.
_TIPOS_DE_FLUJO = ("device", "helper", "hub", "service")

_TITULO_MAX = 255

# Principio V (T015): «HA lo redescubre» no es siempre verdad. Al borrar la
# entrada `ignore`, HA avisa a las integraciones que guardan claves de
# descubrimiento (zeroconf, dhcp…), que lo ofrecen otra vez enseguida; las
# demás, solo cuando lo vuelven a encontrar. En el banco, `banco_flujos` no
# lo redescubre.
_UNDO_HINT = (
    "HA created an ignored config entry (source 'ignore') for this device. "
    "To stop ignoring it, delete that entry with ha_delete_config_entry; the "
    "device is offered again when the integration discovers it again "
    "(at once for integrations that track discovery keys, such as zeroconf "
    "or dhcp)."
)


def _invalid(field: str, detail: str) -> str:
    return json.dumps({"error": "invalid_argument", "field": field, "detail": detail})


def _error_ha(exc: HAConnectionError) -> str:
    # El texto de un error de HA puede repetir lo que se le mandó o lo que
    # tenía guardado: siempre redactado.
    return redact_secrets(str(exc))


def _error_titulo(title: Any) -> str | None:
    if not isinstance(title, str) or not title.strip():
        return "must be a non-empty string"
    if len(title) > _TITULO_MAX:
        return f"must be at most {_TITULO_MAX} characters"
    return None


def _ignorable(contexto: dict[str, Any]) -> bool:
    # HA (`ignore_config_flow`) exige `unique_id` en el contexto: es la clave
    # con la que crea la entrada `ignore`. Uno nulo no identifica nada, así
    # que tampoco se ofrece.
    return contexto.get("unique_id") is not None


def _descubierto(flujo: dict[str, Any]) -> dict[str, Any]:
    """Los campos de data-model de un flujo en curso, nunca el contexto entero.

    El contexto puede llevar datos internos del descubrimiento (claves, el
    `unique_id`, la `entry_id` de un reauth): solo se devuelve lo que sirve
    para decidir, y `title_placeholders` redactado.
    """
    contexto = flujo.get("context")
    if not isinstance(contexto, dict):
        contexto = {}
    marcadores = contexto.get("title_placeholders")
    marcadores = redactar_datos(marcadores) if isinstance(marcadores, dict) else None
    nombre = marcadores.get("name") if marcadores else None
    return {
        "flow_id": flujo.get("flow_id"),
        "domain": flujo.get("handler"),
        "source": contexto.get("source"),
        "step_id": flujo.get("step_id"),
        "name": nombre if isinstance(nombre, str) else None,
        "title_placeholders": marcadores,
        "ignorable": _ignorable(contexto),
    }


async def _leer_progreso(ha_client: HAClient) -> list[dict[str, Any]]:
    """Flujos en curso que no abrió un usuario; lanza si la forma es otra.

    Lanzar en vez de devolver lista vacía es lo que hace fail-closed a las dos
    tools que lo usan: una lectura rara no puede convertirse en «no hay nada»
    ni en «ese flujo no existe».
    """
    raw: Any = await ha_client.ws_send({"type": "config_entries/flow/progress"})
    if not isinstance(raw, list):
        raise ValueError("unexpected_response")
    return [f for f in raw if isinstance(f, dict)]


def _sobre(items: list[Any], max_bytes: int, **extra: Any) -> dict[str, Any]:
    total = len(items)

    def construir(kept: list[Any], cut: bool) -> dict[str, Any]:
        out: dict[str, Any] = {"count": total, "truncated": cut, **extra, "items": kept}
        if cut:
            out["returned"] = len(kept)
            out["hint"] = "Narrow the request (for example with domain) to see the rest."
        return out

    return ajustar_lista_a_bytes(items, construir, max_bytes)


def register(
    mcp: object,
    ha_client: HAClient,
    *,
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
) -> None:
    """Registra las tools de descubiertos, dominios configurables y preferencias."""

    ready = requires_ready(ha_client)

    # ── ha_list_discovered_integrations ───────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_discovered_integrations(domain: str | None = None) -> object:
        """List the integrations Home Assistant has discovered and not set up yet.

        These are the config flows HA started by itself (zeroconf, ssdp, dhcp,
        bluetooth, integration discovery…), plus re-authentication and import
        flows, as shown in Settings → Devices & services → Discovered. Flows a
        user opened are not listed. To set one up, continue its flow with
        ha_continue_config_entry_flow(flow_id, {...}) (re-authentication
        flows, source "reauth", need a preview and a confirmation token on
        every step there, because they change credentials); to hide it, use
        ha_ignore_discovery. `ignorable` says whether HA can ignore it (it
        needs a unique ID). title_placeholders are redacted; the rest of the
        flow context is never returned.

        Args:
            domain: Only flows of this integration domain (e.g. "hue").

        Returns:
            JSON {"count", "truncated", "items": [{flow_id, domain, source,
            step_id, name, title_placeholders, ignorable}]}, sorted by domain
            and flow_id; or {"error": ...}.
        """
        if domain is not None and (not isinstance(domain, str) or not _DOMINIO.match(domain)):
            return _invalid("domain", "must be an integration domain: lowercase letters, digits and '_'")
        try:
            flujos = await _leer_progreso(ha_client)
        except HAConnectionError as exc:
            logger.error("ha_list_discovered_integrations_ws_error", error=_error_ha(exc))
            return json.dumps({"error": _error_ha(exc)})
        except ValueError:
            logger.error("ha_list_discovered_integrations_ws_error", error="unexpected_response")
            return json.dumps({"error": "unexpected_response"})

        items = [_descubierto(f) for f in flujos]
        if domain is not None:
            items = [i for i in items if i["domain"] == domain]
        items.sort(key=lambda i: (str(i["domain"]), str(i["flow_id"])))
        logger.info("ha_list_discovered_integrations_ok", domain=domain, count=len(items))
        return json.dumps(_sobre(items, response_max_bytes), ensure_ascii=False)

    # ── ha_ignore_discovery ───────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_ignore_discovery(flow_id: str, title: str | None = None) -> object:
        """Ignore a discovered integration, as "Ignore" does in the HA UI.

        HA aborts the discovery flow and stores an ignored config entry
        (source "ignore") with the device's unique ID, so it is not offered
        again. Reversible: delete that entry with ha_delete_config_entry; the
        device is offered again when its integration discovers it again (at
        once for those that track discovery keys, such as zeroconf or dhcp).
        Only flows with "ignorable": true in
        ha_list_discovered_integrations can be ignored. No confirmation token:
        it does not touch anything that is running.

        Args:
            flow_id: Flow id from ha_list_discovered_integrations.
            title: Title of the ignored entry (default: the discovered name,
                or the domain). At most 255 characters.

        Returns:
            JSON {"result": "ok", flow_id, domain, title, undo_hint}, or
            {"error": "not_found" | "cannot_ignore" | "invalid_argument" | ...}.
        """
        try:
            validate_identifier(flow_id, field="flow_id")
        except InvalidIdentifier as exc:
            return _invalid("flow_id", str(exc))
        if title is not None and (problema := _error_titulo(title)):
            return _invalid("title", problema)

        # Se lee antes de ignorar: así `not_found` y `cannot_ignore` se dicen
        # sin llamar a HA para nada, y el título por defecto es el que ve el
        # usuario en la interfaz.
        try:
            flujos = await _leer_progreso(ha_client)
        except HAConnectionError as exc:
            logger.error("ha_ignore_discovery_ws_error", flow_id=flow_id, error=_error_ha(exc))
            return json.dumps({"error": _error_ha(exc)})
        except ValueError:
            return json.dumps({"error": "unexpected_response"})

        flujo = next((f for f in flujos if f.get("flow_id") == flow_id), None)
        if flujo is None:
            return json.dumps({"error": "not_found", "flow_id": flow_id})
        contexto = flujo.get("context") if isinstance(flujo.get("context"), dict) else {}
        dominio = flujo.get("handler")
        if not _ignorable(contexto):
            return json.dumps({
                "error": "cannot_ignore", "reason": "no_unique_id", "flow_id": flow_id,
                "domain": dominio,
                "detail": "HA can only ignore a discovery that has a unique ID.",
            })

        if title is None:
            marcadores = contexto.get("title_placeholders")
            nombre = marcadores.get("name") if isinstance(marcadores, dict) else None
            title = nombre if isinstance(nombre, str) and nombre.strip() else str(dominio)

        try:
            await ha_client.ws_send({
                "type": "config_entries/ignore_flow", "flow_id": flow_id, "title": title,
            })
        except HAConnectionError as exc:
            logger.error("ha_ignore_discovery_ws_error", flow_id=flow_id, domain=dominio,
                         code=exc.code, error=_error_ha(exc))
            # El flujo pudo terminar entre la lectura y la llamada.
            if exc.code == "not_found":
                return json.dumps({"error": "not_found", "flow_id": flow_id})
            return json.dumps({"error": _error_ha(exc)})

        logger.info("ha_ignore_discovery_ok", flow_id=flow_id, domain=dominio)
        return json.dumps({
            "result": "ok", "flow_id": flow_id, "domain": dominio,
            # Lo que se mandó a HA es el nombre tal cual; lo que vuelve al
            # cliente, redactado (el nombre lo pone el dispositivo).
            "title": redact_secrets(title), "undo_hint": _UNDO_HINT,
        }, ensure_ascii=False)

    # ── ha_list_config_flow_domains ───────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_config_flow_domains(type: str | None = None) -> object:  # noqa: A002
        """List the integration domains that can be set up with a config flow.

        This is the catalog HA offers in "Add integration": built-in
        integrations and installed custom integrations with a config flow,
        whether or not they are configured (unlike ha_list_configured_domains,
        which lists the domains that already have config entries). Start one
        with ha_start_config_entry_flow(domain).

        Args:
            type: Only this kind: "device", "helper", "hub" or "service".
                "helper" lists the helpers created through a config flow
                (template, group, derivative…).

        Returns:
            JSON {"count", "truncated", "type", "items": [domain, ...]}
            sorted, or {"error": ...}.
        """
        if type is not None and type not in _TIPOS_DE_FLUJO:
            return _invalid("type", f"must be one of: {', '.join(_TIPOS_DE_FLUJO)}")
        try:
            raw: Any = await ha_client._request_json(  # noqa: SLF001
                "GET",
                "/config/config_entries/flow_handlers",
                params={"type": type} if type is not None else None,
            )
        except HAConnectionError as exc:
            logger.error("ha_list_config_flow_domains_rest_error", type=type, error=_error_ha(exc))
            return json.dumps({"error": _error_ha(exc)})
        if not isinstance(raw, list) or not all(isinstance(d, str) for d in raw):
            return json.dumps({"error": "unexpected_response"})

        dominios = sorted(set(raw))
        logger.info("ha_list_config_flow_domains_ok", type=type, count=len(dominios))
        return json.dumps(_sobre(dominios, response_max_bytes, type=type), ensure_ascii=False)

    # ── ha_update_config_entry ────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_update_config_entry(
        entry_id: str,
        title: str | None = None,
        pref_disable_polling: bool | None = None,
        pref_disable_new_entities: bool | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Change the title or the system options of a config entry.

        Only the fields that change are sent. Renaming, re-enabling polling or
        re-enabling new entities apply at once. Disabling polling
        (pref_disable_polling=true) or new entities
        (pref_disable_new_entities=true) is two steps: without
        confirmation_token it returns a preview with the effects and a token;
        repeat the same call with the token to apply. Changing polling makes
        HA reload the integration if it is loaded; with polling disabled its
        entities only update through homeassistant.update_entity or by push.
        With new entities disabled, what the integration adds from then on is
        created disabled.

        Args:
            entry_id: Config entry id (ha_list_config_entries).
            title: New title (at most 255 characters).
            pref_disable_polling: true to stop polling, false to poll again.
            pref_disable_new_entities: true to add new entities disabled,
                false to add them enabled.
            confirmation_token: Token from the preview call.

        Returns:
            {"result": "ok", "config_entry": {...}, "require_restart": bool,
            "reloaded": bool}, {"result": "unchanged"}, a preview with
            confirmation_token, or {"error": ...}.
        """
        try:
            validate_identifier(entry_id, field="entry_id")
        except InvalidIdentifier as exc:
            return _invalid("entry_id", str(exc))
        if title is None and pref_disable_polling is None and pref_disable_new_entities is None:
            return _invalid(
                "title, pref_disable_polling, pref_disable_new_entities",
                "nothing to change: pass title, pref_disable_polling or "
                "pref_disable_new_entities")
        if title is not None and (problema := _error_titulo(title)):
            return _invalid("title", problema)
        for campo, valor in (("pref_disable_polling", pref_disable_polling),
                             ("pref_disable_new_entities", pref_disable_new_entities)):
            if valor is not None and not isinstance(valor, bool):
                return _invalid(campo, "must be a boolean")

        # El token se ata a los cuatro argumentos tal como llegaron.
        args = {
            "entry_id": entry_id, "title": title,
            "pref_disable_polling": pref_disable_polling,
            "pref_disable_new_entities": pref_disable_new_entities,
        }

        # Lectura previa siempre: decide qué cambia de verdad (el comando solo
        # lleva eso), si hace falta token, y si HA va a recargar la entrada.
        try:
            raw: Any = await ha_client.ws_send(
                {"type": "config_entries/get_single", "entry_id": entry_id})
        except HAConnectionError as exc:
            if exc.code == "not_found":
                return json.dumps({"error": "not_found", "entry_id": entry_id})
            logger.warning("ha_update_config_entry_preview_read_failed",
                           entry_id=entry_id, error=_error_ha(exc))
            # Sin la entrada no hay vista previa veraz: no se emite token.
            return json.dumps({"error": "preview_unavailable", "detail": _error_ha(exc)})
        actual = raw.get("config_entry") if isinstance(raw, dict) else None
        if not isinstance(actual, dict):
            return json.dumps({"error": "preview_unavailable", "detail": "unexpected_response"})

        cambios: dict[str, Any] = {}
        if title is not None and title != actual.get("title"):
            cambios["title"] = title
        sondeo_antes = bool(actual.get("pref_disable_polling"))
        nuevas_antes = bool(actual.get("pref_disable_new_entities"))
        if pref_disable_polling is not None and pref_disable_polling != sondeo_antes:
            cambios["pref_disable_polling"] = pref_disable_polling
        if pref_disable_new_entities is not None and pref_disable_new_entities != nuevas_antes:
            cambios["pref_disable_new_entities"] = pref_disable_new_entities
        if not cambios:
            return json.dumps({"result": "unchanged"})

        # Token solo al DESACTIVAR (pasar a true) el sondeo o las entidades
        # nuevas: es lo que deja entidades sin actualizar o sin crear sin que
        # nadie lo note. Renombrar y reactivar se aplican sin más (research R-3).
        pide_token = (cambios.get("pref_disable_polling") is True
                      or cambios.get("pref_disable_new_entities") is True)
        estado = actual.get("state")

        if pide_token and not confirmation_token:
            efectos: list[str] = []
            if "pref_disable_polling" in cambios:
                if estado == "loaded":
                    efectos.append(
                        "Home Assistant reloads this integration now (it is loaded): "
                        "its entities are unavailable for a moment.")
                else:
                    efectos.append(
                        f"This integration is not loaded (state: {estado}): Home "
                        "Assistant does not reload it now; the change applies the "
                        "next time it loads.")
                efectos.append(
                    "The integration stops polling: its entities only update when "
                    "something calls homeassistant.update_entity, or by push if "
                    "the integration supports it.")
            if cambios.get("pref_disable_new_entities") is True:
                efectos.append(
                    "New devices and entities this integration adds from now on are "
                    "created disabled. Existing ones do not change.")
            titulo_actual = actual.get("title")
            preview = {
                "entry_id": entry_id,
                "domain": actual.get("domain"),
                "state": estado,
                # Los títulos los escribe el usuario o la integración: se
                # enseñan redactados por patrón, como cualquier texto de HA.
                "title": {
                    "current": redact_secrets(titulo_actual) if isinstance(titulo_actual, str) else titulo_actual,
                    "new": redact_secrets(cambios.get("title", titulo_actual))
                    if isinstance(cambios.get("title", titulo_actual), str) else titulo_actual,
                },
                "pref_disable_polling": {
                    "current": sondeo_antes,
                    "new": cambios.get("pref_disable_polling", sondeo_antes)},
                "pref_disable_new_entities": {
                    "current": nuevas_antes,
                    "new": cambios.get("pref_disable_new_entities", nuevas_antes)},
                "effects": efectos,
            }
            token_data = await create_confirmation_token(
                "ha_update_config_entry", args, preview=preview)
            logger.info("ha_update_config_entry_preview", entry_id=entry_id,
                        fields=sorted(cambios))
            return json.dumps(token_data, ensure_ascii=False)

        if confirmation_token:
            # Un token que llega se valida siempre, haga falta o no: si no
            # corresponde a esta llamada, no se ejecuta nada.
            valido, error = await validate_confirmation_token(
                confirmation_token, "ha_update_config_entry", args)
            if not valido:
                logger.warning("ha_update_config_entry_token_invalid",
                               entry_id=entry_id, reason=error)
                return json.dumps({"error": error})

        async def _cerrar(ok: bool, resultado: Any = None, error: str = "") -> None:
            if confirmation_token:
                await complete_confirmation_token(
                    confirmation_token, success=ok, result=resultado, error=error)

        try:
            resp: Any = await ha_client.ws_send(
                {"type": "config_entries/update", "entry_id": entry_id, **cambios})
        except HAConnectionError as exc:
            logger.error("ha_update_config_entry_ws_error", entry_id=entry_id,
                         code=exc.code, error=_error_ha(exc))
            await _cerrar(False, error=_error_ha(exc))
            if exc.code == "not_found":
                return json.dumps({"error": "not_found", "entry_id": entry_id})
            return json.dumps({"error": _error_ha(exc)})

        entrada = resp.get("config_entry") if isinstance(resp, dict) else None
        require_restart = bool(resp.get("require_restart")) if isinstance(resp, dict) else False
        # La regla de `config_entry_update` en HA 2026.11.1: recarga si el
        # sondeo cambió (en cualquier sentido) y la entrada estaba cargada.
        recargada = "pref_disable_polling" in cambios and estado == "loaded"
        resultado = {"result": "ok", "config_entry": entrada,
                     "require_restart": require_restart, "reloaded": recargada}
        # El token guarda solo un resumen, sin el título.
        await _cerrar(True, {"result": "ok", "fields": sorted(cambios)})
        logger.info("ha_update_config_entry_ok", entry_id=entry_id, fields=sorted(cambios),
                    reloaded=recargada, require_restart=require_restart)
        return json.dumps(resultado, ensure_ascii=False)
