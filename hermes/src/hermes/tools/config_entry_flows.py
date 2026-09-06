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
  No existe un comando WS/REST que liste todos los handlers disponibles.
  Esta tool devuelve los dominios únicos de las config entries existentes
  como referencia. Para instalar una nueva integración desde cero, usa
  ha_start_config_entry_flow con el domain conocido.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
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

        NOTA: No existe un comando HA que liste todos los handlers disponibles
        para instalación nueva. Esta tool devuelve los dominios únicos de las
        config entries ya configuradas. Útil para saber qué integraciones están
        activas y pueden recibir un nuevo flow (ej. añadir segundo bridge Hue).

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
    ) -> object:
        """Envía datos a un paso de un config flow en curso.

        Úsala después de ha_start_config_entry_flow cuando el resultado
        sea type="form". Rellena los campos del schema devuelto y llama
        a esta tool con los valores correspondientes.

        Args:
            flow_id:    ID del flow (obtenido de ha_start_config_entry_flow).
            user_input: Dict con los valores para los campos del formulario.
                        Las claves deben coincidir con los nombres del schema.

        Returns:
            type="form":         Siguiente paso, con nuevo step_id y schema.
            type="create_entry": {"type": "create_entry", "entry_id": "...",
                                  "title": "...", "result": "ok"}
            type="abort":        {"type": "abort", "reason": "..."}
            type="menu":         {"type": "menu", "menu_options": [...]}
            Error:               {"error": "..."}
        """
        try:
            raw: Any = await ha_client._request_json(  # noqa: SLF001
                "POST",
                _flow_path(flow_id),
                json_body=user_input,
            )
        except InvalidIdentifier as exc:
            return json.dumps(identifier_error(exc))
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
        if flow_type == "create_entry":
            raw["result"] = "ok"

        logger.info(
            "ha_continue_config_entry_flow_ok",
            flow_id=flow_id,
            flow_type=flow_type,
        )
        return json.dumps(raw, ensure_ascii=False)

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

        logger.info("ha_abort_config_entry_flow_ok", flow_id=flow_id)
        return json.dumps({"result": "ok"})

    # ── ha_get_config_entry_options ───────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_get_config_entry_options(entry_id: str) -> object:
        """Devuelve las opciones actuales de una config entry.

        Las opciones son los parámetros configurables de una integración
        (distintos a los datos de la setup inicial). Requiere que la
        integración soporte opciones (supports_options: true).

        Args:
            entry_id: UUID de la config entry.

        Returns:
            JSON {"entry_id": "...", "supports_options": bool, "options": {...}}
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

        result = {
            "entry_id": entry_id,
            "domain": entry.get("domain"),
            "title": entry.get("title"),
            "supports_options": entry.get("supports_options", False),
            "options": entry.get("options", {}),
        }
        logger.info("ha_get_config_entry_options_ok", entry_id=entry_id)
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
            type="create_entry": {"type": "create_entry", "result": "ok"}
                                 Las opciones han sido guardadas.
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
            raw["result"] = "ok"

        logger.info(
            "ha_continue_options_flow_ok",
            flow_id=flow_id,
            flow_type=flow_type,
        )
        return json.dumps(raw, ensure_ascii=False)
