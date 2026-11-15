"""Hermes — Tools MCP para Config Entry Flows.

Gestiona los flujos de configuración (config flows) y flujos de opciones
(options flows) de Home Assistant mediante los comandos WS:

  config_entries/flow/init          — Inicia un nuevo config flow
  config_entries/flow/configure     — Envía datos a un paso del flow
  config_entries/flow/delete        — Aborta / cancela un flow en curso
  config_entries/options/flow/init  — Inicia un options flow
  config_entries/options/flow/configure — Envía datos al options flow

Tipos de resultado de un flow (FlowResultType):
  "form"         — El flow espera input del usuario (automatable).
  "create_entry" — El flow terminó creando/actualizando una entry.
  "abort"        — El flow fue abortado (con reason).
  "external"     — Requiere autenticación externa (OAuth). No automatable.
  "progress"     — Flujo en progreso (descubrimiento). No automatable.
  "menu"         — El flow presenta un menú de opciones.
  "external_done", "progress_done" — Transiciones intermedias.

Regla de seguridad:
  Si el resultado tras init es "external", "progress", "external_done" o
  "progress_done", el flow se aborta automáticamente y se devuelve
  {"error": "non_automatable", ...}. Esto evita flows huérfanos en HA.

Nota sobre ha_list_configured_domains:
  Devuelve los dominios únicos de las config entries existentes. La lista de
  los handlers que se pueden configurar existe por REST
  (`/api/config/config_entries/flow_handlers`) y la expone
  ha_list_config_flow_domains (spec 016, familia integration_flows). Para
  instalar una integración nueva, ha_start_config_entry_flow con su dominio.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    es_clave_sensible,
    redact_secrets,
    validate_confirmation_token,
)
from hermes.tools import _flujos_propios, _reconfigure
from hermes.tools._flujos import (
    _ERROR_MARCADOR,
    _campos_secretos,
    _lleva_marcador,
    _tapar_resultado,
    _tapar_user_input,
)
from hermes.tools._validation import (
    InvalidIdentifier,
    identifier_error,
    validate_identifier,
)
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)

# Tipos de resultado que no pueden automatizarse: abortar inmediatamente
_NON_AUTOMATABLE_TYPES = frozenset(
    {"external", "external_done", "progress", "progress_done"}
)

# Spec 016, tramo C (decisión del supervisor): un flujo `reauth` cambia las
# credenciales de una entrada; cada paso que se envía pide token.
_EFECTO_REAUTH = (
    "Submits this step of the re-authentication flow of this config entry. "
    "When the flow finishes, the integration saves the new credentials of the "
    "entry and Home Assistant reloads it: wrong credentials can leave it "
    "failing to load. Home Assistant does not say in advance whether this "
    "step is the last one.")

_CONTINUE_REAUTH = (
    "ha_continue_config_entry_flow: this is a re-authentication flow, the next "
    "step needs a new preview and its own confirmation_token")


def _invalid(field: str, detail: str) -> str:
    return json.dumps({"error": "invalid_argument", "field": field, "detail": detail})


class _ProgresoIlegible(Exception):
    """`config_entries/flow/progress` falló o devolvió otra forma."""


async def _flujo_en_curso(ha_client: HAClient, flow_id: str) -> dict[str, Any] | None:
    """El flujo tal como lo lista `config_entries/flow/progress`, o `None`.

    HA lista ahí los flujos que no abrió un usuario, `reauth` incluidos (los
    `reconfigure` y los `user` no salen). `None` si no está. Si no se puede
    leer, lanza `_ProgresoIlegible`: desde T048 la tool no envía nada sin
    saber el origen (fail-closed).
    """
    try:
        raw: Any = await ha_client.ws_send({"type": "config_entries/flow/progress"})
    except HAConnectionError as exc:
        logger.warning("ha_continue_config_entry_flow_progress_read_failed",
                       flow_id=flow_id, error=redact_secrets(str(exc)))
        raise _ProgresoIlegible from exc
    if not isinstance(raw, list):
        logger.warning("ha_continue_config_entry_flow_progress_read_failed",
                       flow_id=flow_id, error="unexpected_response")
        raise _ProgresoIlegible
    return next((f for f in raw if isinstance(f, dict) and f.get("flow_id") == flow_id), None)


# T048: lo que se responde a un flujo cuyo origen Hermes no conoce. No remite
# a ninguna tool que envíe un paso sin token.
_ABRIR_DE_NUEVO = (
    "Nothing was sent. Start the flow again: ha_start_config_entry_flow(domain) "
    "to set up an integration, or ha_start_reconfigure_flow(entry_id) to "
    "reconfigure an entry; abort the old flow with ha_abort_config_entry_flow "
    "if it is still open.")


def _flow_path(flow_id: str, *, options: bool = False) -> str:
    """Construye la ruta REST de un flow, validando el id primero.

    El `flow_id` lo pone el cliente MCP y acaba interpolado dentro de la ruta
    REST en cinco sitios distintos. La validación se centraliza aquí para que
    no pueda olvidarse en el sexto.
    """
    validate_identifier(flow_id, field="flow_id")
    if options:
        return f"/config/config_entries/options/flow/{flow_id}"
    return f"/config/config_entries/flow/{flow_id}"


async def _abort_flow(
    ha_client: HAClient,
    flow_id: str,
    flow_type: str = "config_entries",
) -> None:
    """Aborta un flow en curso (best-effort, no lanza excepción).

    HA gestiona los flows via REST. El DELETE cancela el flow.
    """
    try:
        path = _flow_path(flow_id, options=flow_type != "config_entries")
    except InvalidIdentifier as exc:
        logger.warning("flow_abort_invalid_id", flow_id=flow_id, error=str(exc))
        return
    try:
        await ha_client._request_json("DELETE", path)  # noqa: SLF001
    except HAConnectionError as exc:
        logger.warning(
            "flow_abort_failed", flow_id=flow_id, flow_type=flow_type, error=str(exc)
        )


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de config entry flows."""

    ready = requires_ready(ha_client)

    # ── ha_list_configured_domains ─────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_configured_domains() -> object:
        """Dominios YA configurados (NO es el catálogo de integraciones instalables).

        Para añadir una integración nueva llama directamente a
        ha_start_config_entry_flow con su dominio (p. ej. "spotify"), aunque no
        aparezca en esta lista.

        NOTA: Esta tool devuelve los dominios únicos de las config entries ya
        configuradas. Útil para saber qué integraciones están activas y pueden
        recibir un nuevo flow (ej. añadir segundo bridge Hue). La lista de los
        dominios que se pueden configurar por flujo (el catálogo de «Añadir
        integración») la da ha_list_config_flow_domains, si la familia
        integration_flows está activa.

        Returns:
            JSON {"count": int, "domains": ["hue", "mqtt", ...]}
        """
        try:
            raw: Any = await ha_client.ws_send({"type": "config_entries/get"})
        except HAConnectionError as exc:
            logger.error("ha_list_configured_domains_ws_error", error=str(exc))
            return json.dumps({"error": str(exc)})

        items: list[dict] = raw if isinstance(raw, list) else []
        domains = sorted({e.get("domain", "") for e in items if e.get("domain")})

        logger.info("ha_list_configured_domains_ok", count=len(domains))
        return json.dumps(
            {"count": len(domains), "domains": domains}, ensure_ascii=False
        )

    # ── ha_start_config_entry_flow ────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_start_config_entry_flow(handler: str) -> object:
        """Inicia un nuevo config flow para una integración.

        El flow queda abierto en HA hasta que se complete (create_entry),
        se aborte (ha_abort_config_entry_flow) o expire el timeout de HA
        (~15 min). Siempre aborta el flow si el resultado inicial no es
        automatable (OAuth, descubrimiento en progreso).

        Args:
            handler: Dominio de la integración (ej. "hue", "mqtt", "shelly").
                     Case-sensitive, en minúsculas.

        Returns:
            Si el primer paso es un formulario:
            {
              "flow_id": "abc123",
              "step_id": "user",
              "type": "form",
              "schema": [...],        # campos esperados
              "description_placeholders": {...} | null
            }
            Si el flow crea la entry directamente (ej. integraciones sin
            configuración):
            {"type": "create_entry", "entry_id": "...", "title": "..."}
            Si no es automatable (OAuth requerido):
            {"error": "non_automatable", "type": "external", "flow_id": "...",
             "hint": "Este flow requiere autenticación externa (OAuth). ..."}
            Error: {"error": "..."}
        """
        if not handler or not handler.strip():
            return json.dumps({"error": "handler must be a non-empty string"})

        try:
            raw: Any = await ha_client._request_json(  # noqa: SLF001
                "POST",
                "/config/config_entries/flow",
                json_body={"handler": handler},
            )
        except HAConnectionError as exc:
            logger.error(
                "ha_start_config_entry_flow_rest_error",
                handler=handler,
                error=str(exc),
            )
            return json.dumps({"error": str(exc)})

        if not isinstance(raw, dict):
            return json.dumps(
                {"error": "unexpected_response", "raw": str(raw)[:200]}
            )

        flow_type = raw.get("type", "")
        flow_id = raw.get("flow_id", "")

        # Auto-abort non-automatable flows to prevent orphans in HA
        if flow_type in _NON_AUTOMATABLE_TYPES:
            if flow_id:
                await _abort_flow(ha_client, flow_id, "config_entries")
            logger.warning(
                "ha_start_config_entry_flow_non_automatable",
                handler=handler,
                flow_type=flow_type,
                flow_id=flow_id,
            )
            return json.dumps(
                {
                    "error": "non_automatable",
                    "type": flow_type,
                    "flow_id": flow_id,
                    "hint": (
                        f"This flow requires external interaction ({flow_type}). "
                        "It cannot be completed via MCP. The flow has been "
                        "aborted automatically to avoid leaving orphaned flows "
                        "in Home Assistant. Configure this integration manually "
                        "via the HA UI Settings → Devices & Services."
                    ),
                }
            )

        # T048: Hermes apunta los flujos que abre (origen `user`) para que
        # ha_continue_config_entry_flow los reconozca; HA no los lista.
        if flow_type in ("form", "menu") and isinstance(flow_id, str) and flow_id:
            _flujos_propios.registrar(flow_id)

        logger.info(
            "ha_start_config_entry_flow_ok",
            handler=handler,
            flow_type=flow_type,
            flow_id=flow_id,
        )
        return json.dumps(raw, ensure_ascii=False)

    # ── ha_continue_config_entry_flow ─────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_continue_config_entry_flow(
        flow_id: str,
        user_input: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Envía datos a un paso de un config flow en curso.

        Úsala después de ha_start_config_entry_flow cuando el resultado
        sea type="form". Rellena los campos del schema devuelto y llama
        a esta tool con los valores correspondientes.

        Los flujos de reconfigure que abre ha_start_reconfigure_flow NO se
        continúan aquí: se rechazan con {"error": "use_dedicated_tool"} y se
        siguen con ha_continue_reconfigure_flow (vista previa y token en
        cada paso).

        Los flujos de reautenticación (source "reauth", los que abre HA
        cuando unas credenciales dejan de valer; salen en
        ha_list_discovered_integrations) piden confirmación en CADA paso,
        porque cambian las credenciales de la entrada y HA la recarga: sin
        confirmation_token devuelve una vista previa (entrada, paso, campos
        con los secretos tapados, efecto) y un token; repite la misma llamada
        con el token para enviar. El token se ata al flujo, a su paso actual
        y al user_input entero. Hermes lo sabe por config_entries/flow/progress.

        Solo se continúan los flujos que abrió ha_start_config_entry_flow en
        esta sesión de Hermes (sin usar más de una hora) y los que HA lista
        como descubiertos o de reautenticación
        (ha_list_discovered_integrations); esos van sin token, salvo los
        reauth, como en la 1.1.2. Cualquier otro flow_id (uno abierto antes
        de reiniciar Hermes o desde la interfaz de HA, o un reconfigure) se
        rechaza con {"error": "unknown_flow"} sin enviar nada, y también si
        no se puede leer config_entries/flow/progress: ábrelo de nuevo.

        Args:
            flow_id:    ID del flow (obtenido de ha_start_config_entry_flow).
            user_input: Dict con los valores para los campos del formulario.
                        Las claves deben coincidir con los nombres del schema.
            confirmation_token: Solo para flujos de reautenticación: el token
                        de la vista previa.

        Returns:
            type="form":         Siguiente paso, con nuevo step_id y schema.
            type="create_entry": {"type": "create_entry", "status": "ok",
                                  "title": "...", "result": {...}} donde
                                 `result` es la config entry recién creada tal
                                 como la manda HA (entry_id, domain, title,
                                 source, state...). No hay `entry_id` en la
                                 raíz: está dentro de `result`.
            type="abort":        {"type": "abort", "reason": "..."}
            type="menu":         {"type": "menu", "menu_options": [...]}
            Reautenticación sin token: vista previa y confirmation_token.
            Flujo desconocido:   {"error": "unknown_flow", "reason": ...}
            Error:               {"error": "..."}
        """
        # Spec 016 (decisión del supervisor): un reconfigure puede cambiar
        # credenciales y recarga la integración, así que cada paso pide token
        # y va por su tool dedicada. HA no dice el `source` de un flujo: lo
        # sabe el registro de los que abrió Hermes. Caducado o no, se rechaza
        # (ver `_reconfigure.buscar`). Los demás, abajo (T048).
        if isinstance(flow_id, str) and _reconfigure.buscar(flow_id) is not None:
            logger.warning("ha_continue_config_entry_flow_reconfigure_refused",
                           flow_id=flow_id)
            return json.dumps({
                "error": "use_dedicated_tool",
                "tool": "ha_continue_reconfigure_flow",
                "flow_id": flow_id,
                "detail": (
                    "This is a reconfigure flow opened by Hermes: every step "
                    "needs a preview and a confirmation token."),
            })
        try:
            ruta = _flow_path(flow_id)
        except InvalidIdentifier as exc:
            return json.dumps(identifier_error(exc))

        # T048 (decisión del supervisor, fail-closed): un flujo que abrió
        # Hermes con ha_start_config_entry_flow se continúa como en la 1.1.2,
        # sin leer nada más (es de origen `user`).
        propio = _flujos_propios.conocido(flow_id)
        if not propio:
            # Spec 016, tramo C (decisión del supervisor): un `reauth` cambia
            # credenciales, así que cada paso pide token (principio IV). A
            # diferencia de los reconfigure, HA sí los lista en flow/progress:
            # se mira ahí su `source` antes de enviar nada.
            try:
                en_curso = await _flujo_en_curso(ha_client, flow_id)
            except _ProgresoIlegible:
                return json.dumps({
                    "error": "unknown_flow", "reason": "flow_progress_unavailable",
                    "flow_id": flow_id,
                    "detail": ("Hermes could not read the flows in progress from Home "
                               "Assistant, so it cannot tell where this flow comes from. "
                               "Nothing was sent; try again."),
                })
            if en_curso is None:
                # Ni lo abrió Hermes ni HA lo lista: puede ser un `user` de
                # antes de reiniciar Hermes o de la interfaz de HA, o un
                # `reconfigure` (HA excluye los dos de flow/progress). La
                # 1.1.2 lo enviaba sin token; ahora se rechaza sin tocar HA.
                logger.warning("ha_continue_config_entry_flow_unknown_flow",
                               flow_id=flow_id)
                return json.dumps({
                    "error": "unknown_flow", "reason": "not_opened_by_hermes",
                    "flow_id": flow_id,
                    "detail": ("Hermes cannot continue this flow: it was not opened with "
                               "ha_start_config_entry_flow in this Hermes session (or it "
                               "was idle for more than an hour), and Home Assistant does "
                               "not list it as a discovered or re-authentication flow. "
                               "It may be a reconfigure flow, a flow opened in the Home "
                               "Assistant UI, or one opened before Hermes restarted. "
                               + _ABRIR_DE_NUEVO),
                })
            contexto = en_curso.get("context")
            if isinstance(contexto, dict) and contexto.get("source") == "reauth":
                return await _continuar_reauth(
                    flow_id, ruta, user_input, confirmation_token, en_curso, contexto)

        try:
            raw: Any = await ha_client._request_json(  # noqa: SLF001
                "POST",
                ruta,
                json_body=user_input,
            )
        except HAConnectionError as exc:
            logger.error(
                "ha_continue_config_entry_flow_rest_error",
                flow_id=flow_id,
                error=str(exc),
            )
            return json.dumps({"error": str(exc)})

        if not isinstance(raw, dict):
            return json.dumps(
                {"error": "unexpected_response", "raw": str(raw)[:200]}
            )

        flow_type = raw.get("type", "")
        if propio:
            # Un flujo terminado ya no existe en HA; uno que sigue renueva su
            # caducidad.
            if flow_type in ("form", "menu"):
                _flujos_propios.tocar(flow_id)
            else:
                _flujos_propios.olvidar(flow_id)
        if flow_type == "create_entry":
            # OJO: en un config flow, `result` es de HA y trae la config entry
            # creada serializada (entry_id, domain, title, source, state...).
            # Escribir "ok" encima la borraba, y con ella el único sitio donde
            # viaja el entry_id — sin él no se puede seguir con options flow ni
            # con ha_get_config_entry. El estado va en `status`, que es campo
            # nuestro y no pisa nada de HA.
            raw["status"] = "ok"

        logger.info(
            "ha_continue_config_entry_flow_ok",
            flow_id=flow_id,
            flow_type=flow_type,
        )
        return json.dumps(raw, ensure_ascii=False)

    async def _continuar_reauth(
        flow_id: str,
        ruta: str,
        user_input: Any,
        confirmation_token: str | None,
        en_curso: dict[str, Any],
        contexto: dict[str, Any],
    ) -> str:
        """Un paso de un flujo `reauth`, en dos pasos (como el reconfigure)."""
        if not isinstance(user_input, dict):
            return _invalid("user_input", "must be an object")
        if _lleva_marcador(user_input):
            return _invalid("user_input", _ERROR_MARCADOR)
        # El paso actual se lee SIEMPRE, también al confirmar: el token se ata
        # a él, y si el flujo avanzó entre la vista previa y la confirmación,
        # el token deja de valer y no se envía nada.
        try:
            paso: Any = await ha_client._request_json("GET", ruta)  # noqa: SLF001
        except HAConnectionError as exc:
            if exc.status == 404:
                return json.dumps({"error": "not_found", "flow_id": flow_id})
            logger.warning("ha_continue_config_entry_flow_preview_read_failed",
                           flow_id=flow_id, error=redact_secrets(str(exc)))
            return json.dumps({"error": "preview_unavailable",
                               "detail": redact_secrets(str(exc))})
        if not isinstance(paso, dict):
            return json.dumps({"error": "preview_unavailable", "detail": "unexpected_response"})
        step_id = paso.get("step_id")
        args = {"flow_id": flow_id, "step_id": step_id, "user_input": user_input}

        if not confirmation_token:
            esquema = paso.get("data_schema")
            secretos = _campos_secretos(esquema)
            pedidos = ({c.get("name") for c in esquema if isinstance(c, dict)}
                       if isinstance(esquema, list) else set())
            preview = {
                "flow_id": flow_id,
                "source": "reauth",
                "domain": en_curso.get("handler"),
                "entry_id": contexto.get("entry_id"),
                "step_id": step_id,
                "user_input": _tapar_user_input(user_input, secretos),
                "secret_fields": sorted(k for k in user_input
                                        if k in secretos or es_clave_sensible(str(k))),
                "unknown_fields": sorted(k for k in user_input if k not in pedidos),
                "effect": _EFECTO_REAUTH,
            }
            # `user_input` entra en el hash, no en el fichero del token.
            token_data = await create_confirmation_token(
                "ha_continue_config_entry_flow", args, preview=preview)
            logger.info("ha_continue_config_entry_flow_reauth_preview", flow_id=flow_id,
                        step_id=step_id, fields=sorted(user_input))
            return json.dumps(token_data, ensure_ascii=False)

        valido, error = await validate_confirmation_token(
            confirmation_token, "ha_continue_config_entry_flow", args)
        if not valido:
            logger.warning("ha_continue_config_entry_flow_token_invalid", flow_id=flow_id,
                           step_id=step_id, reason=error)
            return json.dumps({"error": error})
        try:
            raw: Any = await ha_client._request_json(  # noqa: SLF001
                "POST", ruta, json_body=user_input)
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False,
                                              error=redact_secrets(str(exc)))
            logger.error("ha_continue_config_entry_flow_rest_error", flow_id=flow_id,
                         status=exc.status, error=redact_secrets(str(exc)))
            if exc.status == 404:
                return json.dumps({"error": "not_found", "flow_id": flow_id})
            return json.dumps({"error": redact_secrets(str(exc))})
        if not isinstance(raw, dict):
            await complete_confirmation_token(confirmation_token, success=False,
                                              error="unexpected_response")
            return json.dumps({"error": "unexpected_response"})
        tipo = raw.get("type", "")
        await complete_confirmation_token(confirmation_token, success=True,
                                          result={"type": tipo, "step_id": step_id})
        if tipo in _NON_AUTOMATABLE_TYPES:
            await _abort_flow(ha_client, flow_id, "config_entries")
            return json.dumps({"error": "non_automatable", "type": tipo, "flow_id": flow_id,
                               "hint": ("This flow requires external interaction. "
                                        "Re-authenticate from the HA UI.")})
        # Un formulario de reauth puede traer la contraseña actual como valor
        # sugerido: sale tapada, como en el reconfigure.
        resultado = _tapar_resultado(raw)
        if tipo in ("form", "menu"):
            resultado["continue_with"] = _CONTINUE_REAUTH
        elif tipo == "create_entry" or (tipo == "abort"
                                        and raw.get("reason") == "reauth_successful"):
            resultado["status"] = "ok"
        logger.info("ha_continue_config_entry_flow_ok", flow_id=flow_id, flow_type=tipo,
                    source="reauth")
        return json.dumps(resultado, ensure_ascii=False)

    # ── ha_abort_config_entry_flow ────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_abort_config_entry_flow(flow_id: str) -> object:
        """Aborta y cancela un config flow en curso.

        Limpia el flow de la lista de flows activos de HA. Llama a esta tool
        si decides no completar un flow iniciado con ha_start_config_entry_flow.

        Args:
            flow_id: ID del flow a abortar.

        Returns:
            {"result": "ok"} si el flow fue abortado.
            {"error": "..."} si el flow no existe o ya fue completado.
        """
        try:
            await ha_client._request_json(  # noqa: SLF001
                "DELETE",
                _flow_path(flow_id),
            )
        except InvalidIdentifier as exc:
            return json.dumps(identifier_error(exc))
        except HAConnectionError as exc:
            logger.error(
                "ha_abort_config_entry_flow_rest_error",
                flow_id=flow_id,
                error=str(exc),
            )
            return json.dumps({"error": str(exc)})

        # Un flujo abortado ya no existe en HA: sale de los registros.
        _reconfigure.olvidar(flow_id)
        _flujos_propios.olvidar(flow_id)
        logger.info("ha_abort_config_entry_flow_ok", flow_id=flow_id)
        return json.dumps({"result": "ok"})

    # ── ha_get_config_entry_options ───────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_get_config_entry_options(entry_id: str) -> object:
        """DEPRECATED (removed in 1.3.0): Home Assistant does not expose config entry options.

        Ninguna API de Home Assistant devuelve las opciones de una config
        entry, así que esta tool no puede leerlas. Para una entry existente
        responde `not_supported` con lo que sí sabe (`entry_id`, `domain`,
        `title`, `supports_options`) y una indicación: `ha_start_options_flow`
        enseña el formulario de opciones (muchas integraciones lo rellenan con
        los valores actuales, pero depende de cada una) y después
        `ha_abort_config_entry_flow` lo cierra sin cambiar nada.

        Args:
            entry_id: UUID de la config entry.

        Returns:
            JSON {"error": "not_supported", "entry_id", "domain", "title",
            "supports_options", "message", "hint", "_deprecated"},
            o {"error": "not_found"}.
        """
        try:
            raw: Any = await ha_client.ws_send(
                {"type": "config_entries/get_single", "entry_id": entry_id}
            )
        except HAConnectionError as exc:
            logger.error(
                "ha_get_config_entry_options_ws_error",
                entry_id=entry_id,
                error=str(exc),
            )
            return json.dumps({"error": str(exc)})

        if not isinstance(raw, dict):
            return json.dumps({"error": "not_found", "entry_id": entry_id})

        entry = raw.get("config_entry", raw) if "config_entry" in raw else raw
        if entry is None:
            return json.dumps({"error": "not_found", "entry_id": entry_id})

        # Spec 033 (FR-008, research R-6): `get_single` devuelve
        # `ConfigEntry.as_json_fragment`, que no incluye `options` (ni
        # `data`), y no hay otra vía general (diagnósticos dependen de cada
        # integración; `.storage` está vetado en las fs_*). Antes se devolvía
        # `options: {}`, que el cliente leía como «sin opciones»: era falso.
        # Se responde lo que sí se sabe y la vía alternativa, sin `options`.
        result = {
            "error": "not_supported",
            "entry_id": entry_id,
            "domain": entry.get("domain"),
            "title": entry.get("title"),
            "supports_options": entry.get("supports_options", False),
            "message": "Home Assistant does not expose config entry options through its API.",
            "hint": (
                "Start ha_start_options_flow to see the form (many integrations "
                "prefill the current values, but it depends on the integration), "
                "then ha_abort_config_entry_flow to close it without changes."
            ),
            "_deprecated": (
                "ha_get_config_entry_options is deprecated and will be removed in "
                "1.3.0; use ha_start_options_flow and ha_abort_config_entry_flow."
            ),
        }
        logger.info("ha_get_config_entry_options_not_supported", entry_id=entry_id)
        return json.dumps(result, ensure_ascii=False)

    # ── ha_start_options_flow ─────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_start_options_flow(entry_id: str) -> object:
        """Inicia un options flow para modificar la configuración de una integración.

        Solo disponible para integraciones con supports_options: true.
        El flow devuelve un formulario con los campos de opciones actuales.

        Args:
            entry_id: UUID de la config entry cuyas opciones se van a editar.

        Returns:
            {
              "flow_id": "abc123",
              "step_id": "init",
              "type": "form",
              "schema": [...],
              "data": {...}  # valores actuales de las opciones
            }
            Error: {"error": "..."}
        """
        try:
            raw: Any = await ha_client._request_json(  # noqa: SLF001
                "POST",
                "/config/config_entries/options/flow",
                json_body={"handler": entry_id},
            )
        except HAConnectionError as exc:
            logger.error(
                "ha_start_options_flow_rest_error", entry_id=entry_id, error=str(exc)
            )
            return json.dumps({"error": str(exc)})

        if not isinstance(raw, dict):
            return json.dumps(
                {"error": "unexpected_response", "raw": str(raw)[:200]}
            )

        flow_type = raw.get("type", "")
        flow_id = raw.get("flow_id", "")

        # Auto-abort non-automatable options flows
        if flow_type in _NON_AUTOMATABLE_TYPES:
            if flow_id:
                await _abort_flow(ha_client, flow_id, "options")
            logger.warning(
                "ha_start_options_flow_non_automatable",
                entry_id=entry_id,
                flow_type=flow_type,
            )
            return json.dumps(
                {
                    "error": "non_automatable",
                    "type": flow_type,
                    "hint": (
                        "Options flow requires external interaction. "
                        "Configure options manually via HA UI."
                    ),
                }
            )

        logger.info(
            "ha_start_options_flow_ok",
            entry_id=entry_id,
            flow_type=flow_type,
            flow_id=flow_id,
        )
        return json.dumps(raw, ensure_ascii=False)

    # ── ha_continue_options_flow ──────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_continue_options_flow(
        flow_id: str,
        user_input: dict[str, Any],
    ) -> object:
        """Envía datos al paso actual de un options flow en curso.

        Úsala después de ha_start_options_flow. Rellena los campos del
        schema devuelto con los valores deseados.

        Args:
            flow_id:    ID del options flow (obtenido de ha_start_options_flow).
            user_input: Dict con los nuevos valores para las opciones.

        Returns:
            type="form":         Siguiente paso del options flow.
            type="create_entry": {"type": "create_entry", "status": "ok"}
                                 Las opciones han sido guardadas. (Aquí HA sí
                                 hace `pop("result")`, así que no hay entry que
                                 preservar; se usa `status` igual que en
                                 ha_continue_config_entry_flow.)
            type="abort":        {"type": "abort", "reason": "..."}
            Error:               {"error": "..."}
        """
        try:
            raw: Any = await ha_client._request_json(  # noqa: SLF001
                "POST",
                _flow_path(flow_id, options=True),
                json_body=user_input,
            )
        except InvalidIdentifier as exc:
            return json.dumps(identifier_error(exc))
        except HAConnectionError as exc:
            logger.error(
                "ha_continue_options_flow_rest_error",
                flow_id=flow_id,
                error=str(exc),
            )
            return json.dumps({"error": str(exc)})

        if not isinstance(raw, dict):
            return json.dumps(
                {"error": "unexpected_response", "raw": str(raw)[:200]}
            )

        flow_type = raw.get("type", "")
        if flow_type == "create_entry":
            raw["status"] = "ok"

        logger.info(
            "ha_continue_options_flow_ok",
            flow_id=flow_id,
            flow_type=flow_type,
        )
        return json.dumps(raw, ensure_ascii=False)
