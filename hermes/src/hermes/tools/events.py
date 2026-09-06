"""Hermes — Tool MCP para disparar eventos en el bus de HA."""

from __future__ import annotations

from typing import Any

import structlog

from hermes.ha import HAClient
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)


def register(
    mcp: object, ha_client: HAClient, allowlist: list[str]
) -> None:
    """Registra `ha_fire_event` con el allowlist de event_types permitidos.

    El allowlist se pasa como lista inmutable al registrar para que la tool
    quede atada al valor de config que había en el boot. Cambios en
    `fire_event_allowlist` requieren restart del add-on.
    """

    ready = requires_ready(ha_client)
    allowed: frozenset[str] = frozenset(a for a in (allowlist or []) if a)

    @mcp.tool()
    @ready
    async def ha_fire_event(
        event_type: str, event_data: dict[str, Any] | None = None
    ) -> object:
        """Dispara un evento custom en el bus de Home Assistant.

        Requiere que `event_type` esté en `fire_event_allowlist` de las
        opciones del add-on. Si la allowlist está vacía, la tool rechaza
        cualquier llamada.
        """
        if not allowed:
            logger.warning("ha_fire_event_disabled", event_type=event_type)
            return {
                "error": "event firing disabled",
                "hint": (
                    "add event types to fire_event_allowlist in add-on options"
                ),
            }
        if event_type not in allowed:
            logger.warning(
                "ha_fire_event_not_allowed",
                event_type=event_type,
                allowed=sorted(allowed),
            )
            return {
                "error": "event_type not in allowlist",
                "event_type": event_type,
                "allowed": sorted(allowed),
            }
        try:
            result = await ha_client.fire_event(event_type, event_data)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_fire_event_failed",
                event_type=event_type,
                error=str(exc),
                exc_info=True,
            )
            return {"error": f"{type(exc).__name__}: {exc}"}
        logger.info(
            "event_fired",
            event_type=event_type,
            has_data=event_data is not None,
        )
        return {"result": "ok", "event_type": event_type, "response": result}
