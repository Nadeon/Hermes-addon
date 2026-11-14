"""Hermes — Validación de configuración de Core (spec 012, tramo B).

Dos tools de la familia `core_diagnostics` (CAP-040 de la 008):

- `ha_validate_config`: valida disparadores, condiciones y acciones con los
  validadores de Home Assistant (`validate_config`), sin guardar nada.
- `ha_test_condition`: evalúa una condición contra el estado actual
  (`test_condition`), sin guardar nada.

POR QUÉ ACEPTAR `config` ENTERA
-------------------------------
Lo natural para un agente es validar la automatización o el script que va a
guardar, tal cual. HA solo valida tres partes (`triggers`, `conditions`,
`actions`), así que el resto de claves (`alias`, `mode`, `fields`…) se
devuelven en `not_validated`: la respuesta no puede sugerir que se comprobó
todo (principio V; research R-1).

Todo texto de error que viene de HA pasa por `redact_secrets`: el error de un
validador puede repetir el valor que se le pasó.
"""

from __future__ import annotations

from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import redact_secrets
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)

# Las tres partes que valida HA y, para cada una, los nombres con los que
# puede venir en una automatización (plural, singular) o en un script
# (`sequence`). Orden de la tupla = orden en que se buscan.
_PARTES: dict[str, tuple[str, ...]] = {
    "triggers": ("triggers", "trigger"),
    "conditions": ("conditions", "condition"),
    "actions": ("actions", "action", "sequence"),
}


def _invalid(field: str, detail: str) -> dict[str, Any]:
    return {"error": "invalid_argument", "field": field, "detail": detail}


def _error_ha(exc: HAConnectionError) -> dict[str, Any]:
    return {"error": redact_secrets(str(exc))}


def _redactar_textos(valor: Any) -> Any:
    """`redact_secrets` sobre cada texto de una estructura (sin tocar claves)."""
    if isinstance(valor, str):
        return redact_secrets(valor)
    if isinstance(valor, list):
        return [_redactar_textos(v) for v in valor]
    if isinstance(valor, dict):
        return {k: _redactar_textos(v) for k, v in valor.items()}
    return valor


def _partes_de_config(config: dict[str, Any]) -> tuple[dict[str, Any], list[str]] | dict[str, Any]:
    """(partes a validar, claves no validadas) o un error `invalid_argument`."""
    partes: dict[str, Any] = {}
    usadas: set[str] = set()
    for parte, nombres in _PARTES.items():
        presentes = [n for n in nombres if n in config]
        if len(presentes) > 1:
            # HA rechazaría la configuración al guardarla y no sabríamos cuál
            # de las dos validar.
            return _invalid(
                "config",
                f"has both {' and '.join(repr(n) for n in presentes)}; keep only one",
            )
        if presentes:
            partes[parte] = config[presentes[0]]
            usadas.add(presentes[0])
    resto = sorted(str(k) for k in config if k not in usadas)
    return partes, resto


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de validación de Core."""

    ready = requires_ready(ha_client)

    # ── ha_validate_config ────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_validate_config(
        config: dict | None = None,
        triggers: Any = None,
        conditions: Any = None,
        actions: Any = None,
    ) -> object:
        """Validate triggers, conditions and actions with Home Assistant. Saves nothing.

        Use it before ha_create_or_update_automation or
        ha_create_or_update_script. Pass either a whole automation or script
        as config, or the parts (triggers, conditions, actions), not both.
        From config, "triggers"/"trigger" are validated as triggers,
        "conditions"/"condition" as conditions and "actions"/"action"/
        "sequence" as actions. Home Assistant validates only those three
        parts: every other key (alias, mode, fields...) is listed in
        "not_validated" and was NOT checked.

        Args:
            config: An automation or script configuration (object).
            triggers: Trigger or list of triggers.
            conditions: Condition or list of conditions.
            actions: Action or list of actions.

        Returns:
            {"<part>": {"valid": bool, "error": str|null} for each part sent,
             "not_validated": [keys], "saved": false}, or {"error": ...}.
        """
        sueltas = {
            k: v for k, v in (("triggers", triggers), ("conditions", conditions),
                              ("actions", actions))
            if v is not None
        }
        if config is not None:
            if not isinstance(config, dict):
                return _invalid("config", "must be an object (an automation or script)")
            if sueltas:
                return _invalid(
                    "config",
                    "pass either config or triggers/conditions/actions, not both",
                )
            resultado = _partes_de_config(config)
            if isinstance(resultado, dict):
                return resultado
            partes, no_validadas = resultado
            if not partes:
                return _invalid(
                    "config",
                    "has no triggers, conditions or actions to validate",
                )
        else:
            if not sueltas:
                return _invalid(
                    "config", "pass config or at least one of triggers, conditions, actions",
                )
            partes, no_validadas = sueltas, []

        try:
            raw: Any = await ha_client.ws_send({"type": "validate_config", **partes})
        except HAConnectionError as exc:
            logger.warning("ha_validate_config_error", code=exc.code or "connection")
            return _error_ha(exc)
        if not isinstance(raw, dict):
            logger.warning("ha_validate_config_error", code="unexpected_response")
            return {"error": "unexpected response from validate_config: not an object"}

        respuesta: dict[str, Any] = {}
        for parte in partes:
            r = raw.get(parte)
            if not isinstance(r, dict):
                # Una parte enviada sin resultado no es «válida»: se dice.
                respuesta[parte] = {"valid": False,
                                    "error": "Home Assistant returned no result for this part"}
                continue
            error = r.get("error")
            respuesta[parte] = {
                "valid": r.get("valid") is True,
                "error": redact_secrets(error) if isinstance(error, str) else error,
            }
        respuesta["not_validated"] = no_validadas
        respuesta["saved"] = False
        logger.info(
            "ha_validate_config_ok",
            parts=sorted(partes),
            invalid=sorted(p for p in partes if not respuesta[p]["valid"]),
            not_validated=len(no_validadas),
        )
        return respuesta

    # ── ha_test_condition ─────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_test_condition(
        condition: dict,
        variables: dict | None = None,
    ) -> object:
        """Evaluate a condition against Home Assistant's current state. Saves nothing.

        Useful to debug why an automation's condition passes or fails.

        Args:
            condition: One condition, as in an automation (for example
                {"condition": "state", "entity_id": "light.salon",
                "state": "on"}).
            variables: Variables available to templates in the condition.

        Returns:
            {"result": bool} plus "template_errors" if Home Assistant reports
            any; {"error": "invalid_condition", "detail"} if the condition is
            not valid; {"error": "condition_error", "detail"} if Home
            Assistant fails while evaluating it.
        """
        if not isinstance(condition, dict):
            return _invalid("condition", "must be an object")
        if variables is not None and not isinstance(variables, dict):
            return _invalid("variables", "must be an object")

        mensaje: dict[str, Any] = {"type": "test_condition", "condition": condition}
        if variables is not None:
            mensaje["variables"] = variables
        try:
            raw: Any = await ha_client.ws_send(mensaje)
        except HAConnectionError as exc:
            logger.warning("ha_test_condition_error", code=exc.code or "connection")
            if exc.code == "invalid_format":
                return {"error": "invalid_condition", "detail": redact_secrets(str(exc))}
            if exc.code == "home_assistant_error":
                return {"error": "condition_error", "detail": redact_secrets(str(exc))}
            return _error_ha(exc)
        if not isinstance(raw, dict) or not isinstance(raw.get("result"), bool):
            logger.warning("ha_test_condition_error", code="unexpected_response")
            return {"error": "unexpected response from test_condition"}

        respuesta: dict[str, Any] = {"result": raw["result"]}
        if "template_errors" in raw:
            respuesta["template_errors"] = _redactar_textos(raw["template_errors"])
        logger.info("ha_test_condition_ok", result=raw["result"],
                    template_errors="template_errors" in raw)
        return respuesta
