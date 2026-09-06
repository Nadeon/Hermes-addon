"""Hermes — Tools: ping y test_progress.

Herramientas de verificación de conectividad.
- ping: devuelve "pong" — verifica que el MCP es accesible.
- test_progress: verifica que ctx.report_progress funciona correctamente sobre
  Streamable HTTP. Es andamiaje de desarrollo: solo se registra con
  HERMES_DEV=1, porque en producción ocuparía sitio en el schema y podría
  bloquear una conversación 40 segundos si el modelo la invocara por error.
"""

from __future__ import annotations

import asyncio
import os

from mcp.server.mcpserver import Context

def register(mcp: object) -> None:
    """Registra las tools de conectividad en la instancia MCP.

    Patrón: cada módulo de tools expone una función register(mcp).
    tools/__init__.py las llama todas. Esto evita variables globales
    frágiles y escala a N módulos sin repetir boilerplate.
    """

    @mcp.tool()
    async def ping() -> str:
        """Connectivity check. Returns 'pong' if the MCP server is reachable
        and operational.

        Use this tool to verify that:
        - The MCP server is running
        - Authentication is working
        - The connection through Tailscale Funnel is established

        Returns:
            str: "pong" if everything is working correctly
        """
        return "pong"

    if os.environ.get("HERMES_DEV") != "1":
        return

    @mcp.tool()
    async def test_progress(
        duration_seconds: int = 40,
        ctx: Context = None,
    ) -> object:
        """Test tool to verify that progress notifications work correctly
        over Streamable HTTP.

        It sends progress notifications every 5 seconds for the requested
        duration, so a long-running tool call can be observed end to end.

        Comprueba que las notificaciones de progreso atraviesan el transporte.
        If the connection drops after 60-75 seconds, progress notifications
        are not getting through the transport.

        Args:
            duration_seconds: How long to run the test (default 40s)

        Returns:
            dict: {"done": True, "ticks_sent": N} on success
        """
        ticks = duration_seconds // 5
        for i in range(ticks):
            await asyncio.sleep(5)
            if ctx is not None:
                await ctx.report_progress(
                    progress=i * 5,
                    total=duration_seconds,
                )
        return {"done": True, "ticks_sent": ticks}
