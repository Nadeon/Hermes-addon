"""Hermes — Tool MCP ha_render_template."""

from __future__ import annotations

import json
import math
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)

# Rango admitido para `timeout`. El valor llega del cliente MCP y se usaba tal
# cual: un 0 o un negativo hacen que la espera venza antes de que HA pueda
# contestar (todo render devolvería "template_timeout"), y un valor enorme deja
# la suscripción viva —y el turno del cliente bloqueado— sin tope. Se acota en
# vez de rechazar porque el timeout es un parámetro accesorio: no merece tumbar
# una llamada por lo demás correcta.
_RENDER_TIMEOUT_MIN = 1.0
_RENDER_TIMEOUT_MAX = 60.0

# Texto con el que HA informa de que la plantilla agotó su `timeout`. Llega
# como error del comando con código `template_error`, el mismo que cualquier
# otro fallo de la plantilla, así que el código no distingue el timeout y hay
# que mirar el texto.
_HA_TIMEOUT_TEXT = "Exceeded maximum execution time"


def _clamp_timeout(timeout: float) -> float:
    """Acota el timeout al rango admitido; los valores no numéricos caen al mínimo."""
    try:
        value = float(timeout)
    except (TypeError, ValueError):
        return _RENDER_TIMEOUT_MIN
    if math.isnan(value):
        return _RENDER_TIMEOUT_MIN
    return min(max(value, _RENDER_TIMEOUT_MIN), _RENDER_TIMEOUT_MAX)


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra ha_render_template."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_render_template(
        template: str,
        variables: dict[str, Any] | None = None,
        timeout: float = 10.0,
        strict: bool = False,
    ) -> object:
        """Renderiza un template Jinja2 en Home Assistant y devuelve el resultado.

        Usa report_errors=True internamente: errores del template se devuelven
        como dict estructurado en vez de silenciarse. Así el cliente LLM puede
        identificar y corregir templates rotos sin depender de respuestas vacías.
        Los avisos de nivel WARNING no impiden el render: se devuelven en
        `warnings` junto al resultado.

        Args:
            template: Template Jinja2 de HA.
                      Ejemplos: "{{ states('light.salon') }}"
                                "{{ now().isoformat() }}"
                                "{{ states.sensor | selectattr('state','ne','unavailable') | list | count }}"
            variables: Variables adicionales accesibles en el template como
                       identificadores de primer nivel (ej. {"nombre": "cocina"} →
                       usar {{ nombre }} en el template).
            timeout: Segundos máximos para esperar la respuesta de HA.
                     Templates que acceden a entidades inexistentes pueden tardar.
                     Se acota al rango 1-60s. Default: 10s.
            strict: Si True, referencias a variables indefinidas en el template
                    son fatales (devuelven error) en vez de resolverse a cadena
                    vacía. Útil para validar templates antes de usarlos en
                    automations. Default: False.

        Returns:
            JSON con {"result": "<string_renderizado>", "listeners": {...}}
            en éxito (más "warnings": [...] si HA emitió avisos), o
            {"error": "template_error", "detail": "..."} si el template falla,
            o {"error": "template_timeout", "template": "..."} si HA no
            responde en el tiempo configurado o informa de que se agotó.

        Note:
            states('sensor.no_existe') devuelve "unknown" (comportamiento HA
            por defecto con report_errors=True y strict=False). Solo lanza
            error si strict=True o si hay un error de sintaxis en el template.
        """
        timeout = _clamp_timeout(timeout)
        payload: dict[str, Any] = {
            "type": "render_template",
            "template": template,
            "report_errors": True,
            "strict": strict,
            "timeout": timeout,
        }
        if variables:
            payload["variables"] = variables

        try:
            # Con `report_errors`, HA manda cada aviso como evento antes del
            # resultado; sin recogerlos, el primer aviso se tomaba como error
            # y el resultado se perdía.
            event = await ha_client.ws_one_shot_subscription(
                payload, event_timeout_seconds=timeout, collect_warnings=True
            )
        except HAConnectionError as exc:
            # "Timeout" es el plazo local de Hermes; el otro texto, el de HA.
            if "Timeout" in str(exc) or _HA_TIMEOUT_TEXT in str(exc):
                logger.warning(
                    "ha_render_template_timeout",
                    template=template[:100],
                    timeout=timeout,
                )
                return json.dumps({
                    "error": "template_timeout",
                    "template": template,
                    "hint": (
                        "HA did not render the template within the timeout. "
                        "Check that referenced entities exist or increase timeout."
                    ),
                })
            logger.error(
                "ha_render_template_ws_error",
                template=template[:100],
                error=str(exc),
            )
            return json.dumps({"error": str(exc)})

        # HA puede devolver {result: ..., listeners: ...} o {error: ..., level: ...}
        if "error" in event:
            logger.warning(
                "ha_render_template_error",
                template=template[:100],
                detail=event.get("error"),
            )
            return json.dumps({
                "error": "template_error",
                "detail": event.get("error"),
                "level": event.get("level", "ERROR"),
            })

        result = event.get("result")
        listeners = event.get("listeners", {})
        logger.info(
            "ha_render_template_ok",
            template=template[:100],
            result_type=type(result).__name__,
        )
        response: dict[str, Any] = {"result": result, "listeners": listeners}
        if event.get("warnings"):
            # Con `timeout`, HA hace un pre-render y luego el render real con
            # el mismo aviso: se quitan los repetidos conservando el orden.
            response["warnings"] = list(dict.fromkeys(event["warnings"]))
        return json.dumps(response)
