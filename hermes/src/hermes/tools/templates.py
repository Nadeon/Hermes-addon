"""Hermes — Tool MCP ha_render_template."""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)


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
                     Default: 10s.
            strict: Si True, referencias a variables indefinidas en el template
                    son fatales (devuelven error) en vez de resolverse a cadena
                    vacía. Útil para validar templates antes de usarlos en
                    automations. Default: False.

        Returns:
            JSON con {"result": "<string_renderizado>", "listeners": {...}}
            en éxito, o {"error": "template_error", "detail": "..."} si el
            template falla, o {"error": "template_timeout", "template": "..."}
            si HA no responde en el tiempo configurado.

        Note:
            states('sensor.no_existe') devuelve "unknown" (comportamiento HA
            por defecto con report_errors=True y strict=False). Solo lanza
            error si strict=True o si hay un error de sintaxis en el template.
        """
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
            event = await ha_client.ws_one_shot_subscription(
                payload, event_timeout_seconds=timeout
            )
        except HAConnectionError as exc:
            if "Timeout" in str(exc):
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
        return json.dumps({"result": result, "listeners": listeners})
