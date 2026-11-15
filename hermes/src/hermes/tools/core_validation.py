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


def partes_de_config(config: dict[str, Any]) -> tuple[dict[str, Any], list[str]] | dict[str, Any]:
    """(partes a validar, claves no validadas) o un error `invalid_argument`.

    Función de módulo (spec 017, research R-9): la usan `ha_validate_config`
    y la validación al guardar de `ha_create_or_update_automation` y
    `_script`, que no dependen de que la familia `core_diagnostics` esté
    activa.
    """
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


# Nombre anterior, por si algo lo importa así.
_partes_de_config = partes_de_config


# ── Validación al guardar (spec 017, tramo D, research R-9, FR-062 de la 008) ─

_PISTA_INVALIDA = (
    "Home Assistant would reject this config. Fix the parts listed in "
    "'parts' and ask for a new preview (ha_validate_config checks parts "
    "without saving)."
)
_PISTA_SIN_VALIDAR = (
    "No confirmation token was issued because the config could not be "
    "validated; try again when Home Assistant responds."
)
_NOTA_SIN_PARTES = (
    "No triggers, conditions or actions to validate: Home Assistant checks "
    "the rest when saving."
)


async def validar_al_guardar(
    ha_client: HAClient, dominio: str, config: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(`validation` para la vista previa, None) o (None, el error sin token).

    La usan las vistas previas de `ha_create_or_update_automation`
    (`dominio="automation"`) y `_script` (`"script"`): una configuración que
    HA rechazaría no recibe token (FR-062 de la 008). Solo en la vista
    previa: lo que se confirma es lo previsualizado (spec 007) y HA vuelve a
    validar todo al guardar.

    - Con `use_blueprint`, `validate_config` no tiene partes que mirar: se
      sustituye antes (`blueprint/substitute`, con la ruta tal cual se va a
      guardar) y se validan las partes del resultado.
    - Fail-closed: si HA no responde o responde algo inesperado,
      `validation_unavailable` (dar token sin haber validado incumpliría en
      silencio la regla).
    - Honestidad (D-22): `validate_config` solo mira triggers, condiciones y
      acciones; el resto (`alias`, `mode`, `fields`…) va en
      `not_validated`: lo valida HA al guardar.
    """
    via_blueprint: str | None = None
    origen = config
    excluir: set[str] = set()
    if "use_blueprint" in config:
        uso = config.get("use_blueprint")
        if not isinstance(uso, dict) or not isinstance(uso.get("path"), str)                 or not uso.get("path"):
            return None, _invalid("config.use_blueprint",
                                  "must be an object with 'path' (and 'input')")
        entradas = uso.get("input", {})
        if entradas is None:
            entradas = {}
        if not isinstance(entradas, dict):
            return None, _invalid("config.use_blueprint.input", "must be an object")
        # Importación tardía: `blueprints` es un módulo de tools y aquí solo
        # hace falta su función de sustitución.
        from hermes.tools.blueprints import SustitucionInesperada, sustituir

        via_blueprint = uso["path"]
        try:
            origen = await sustituir(ha_client, dominio, via_blueprint, entradas)
        except HAConnectionError as exc:
            logger.warning("validar_al_guardar_substitution_failed", domain=dominio,
                           code=exc.code or "connection")
            return None, {"error": "blueprint_substitution_failed",
                          "detail": redact_secrets(str(exc)), "blueprint": via_blueprint}
        except SustitucionInesperada as exc:
            logger.warning("validar_al_guardar_substitution_failed", domain=dominio,
                           code="unexpected_response")
            return None, {"error": "blueprint_substitution_failed",
                          "detail": str(exc), "blueprint": via_blueprint}
        excluir = {"use_blueprint"}

    resultado = partes_de_config(origen)
    if isinstance(resultado, dict):
        return None, resultado
    partes, no_validadas = resultado
    if via_blueprint is not None:
        # Lo que no valida HA: lo de la configuración guardada (sin
        # `use_blueprint`) y lo que añade el blueprint fuera de las partes.
        no_validadas = sorted(
            {str(k) for k in config if k not in excluir} | set(no_validadas))

    validation: dict[str, Any] = {
        "validated": sorted(partes),
        "not_validated": no_validadas,
        "via_blueprint": via_blueprint,
    }
    if not partes:
        validation["note"] = _NOTA_SIN_PARTES
        return validation, None

    try:
        resultado_ha = await validar_partes(ha_client, partes)
    except HAConnectionError as exc:
        logger.warning("validar_al_guardar_unavailable", domain=dominio,
                       code=exc.code or "connection")
        return None, {"error": "validation_unavailable",
                      "detail": redact_secrets(str(exc)), "hint": _PISTA_SIN_VALIDAR}
    except RespuestaInesperada as exc:
        logger.warning("validar_al_guardar_unavailable", domain=dominio,
                       code="unexpected_response")
        return None, {"error": "validation_unavailable", "detail": str(exc),
                      "hint": _PISTA_SIN_VALIDAR}
    if any(r.get("missing") for r in resultado_ha.values()):
        # Sin resultado de una parte, no se sabe si es válida: no hay token.
        return None, {"error": "validation_unavailable",
                      "detail": "Home Assistant returned no result for some parts",
                      "hint": _PISTA_SIN_VALIDAR}
    invalidas = {parte: r["error"] for parte, r in resultado_ha.items() if not r["valid"]}
    if invalidas:
        logger.info("validar_al_guardar_invalid", domain=dominio, parts=sorted(invalidas))
        error: dict[str, Any] = {"error": "invalid_config", "parts": invalidas,
                                 "hint": _PISTA_INVALIDA}
        if via_blueprint is not None:
            error["via_blueprint"] = via_blueprint
        return None, error
    return validation, None


class RespuestaInesperada(Exception):
    """`validate_config` respondió algo que no es un objeto."""


async def validar_partes(ha_client: HAClient, partes: dict[str, Any]) -> dict[str, Any]:
    """Resultado de `validate_config` por parte: `{"valid": bool, "error": …}`.

    El texto de error de cada parte sale ya redactado. Una parte enviada sin
    resultado sale como no válida con un mensaje que lo dice (no se da por
    buena). Deja pasar `HAConnectionError` y lanza `RespuestaInesperada` si HA
    no responde un objeto: cada llamador decide qué hacer (spec 017,
    research R-9).
    """
    raw: Any = await ha_client.ws_send({"type": "validate_config", **partes})
    if not isinstance(raw, dict):
        raise RespuestaInesperada("validate_config did not return an object")
    respuesta: dict[str, Any] = {}
    for parte in partes:
        r = raw.get(parte)
        if not isinstance(r, dict):
            # Una parte enviada sin resultado no es «válida»: se dice.
            respuesta[parte] = {"valid": False,
                                "error": "Home Assistant returned no result for this part",
                                "missing": True}
            continue
        error = r.get("error")
        respuesta[parte] = {
            "valid": r.get("valid") is True,
            "error": redact_secrets(error) if isinstance(error, str) else error,
        }
    return respuesta


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
            resultado = partes_de_config(config)
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
            resultado_ha = await validar_partes(ha_client, partes)
        except HAConnectionError as exc:
            logger.warning("ha_validate_config_error", code=exc.code or "connection")
            return _error_ha(exc)
        except RespuestaInesperada:
            logger.warning("ha_validate_config_error", code="unexpected_response")
            return {"error": "unexpected response from validate_config: not an object"}

        respuesta: dict[str, Any] = {
            parte: {"valid": r["valid"], "error": r["error"]}
            for parte, r in resultado_ha.items()
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
