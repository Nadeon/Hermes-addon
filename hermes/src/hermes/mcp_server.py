"""Servidor MCP de Hermes: `MCPServer` del SDK con dos ajustes de protocolo.

1. `serverInfo.version` lleva la versión de Hermes. El SDK la deja vacía si no
   se le pasa, y entonces quien diagnostica un fallo desde el cliente no puede
   saber qué versión del add-on tiene delante.

2. `isError` en los resultados que son fallos. Las tools de Hermes devuelven
   sus errores como un objeto `{"error": …}` —unas 370 respuestas en 37
   ficheros— y el SDK los entregaba con `isError: false`, así que el cliente
   solo se enteraba del fallo leyendo el JSON. La spec MCP pide que los errores
   de ejecución vayan marcados en el propio resultado. Hacerlo aquí, en un solo
   sitio, evita tocar cada `return` de cada tool (principio IX) y no cambia ni
   una letra del contenido que el cliente ya sabe leer.

   El SDK llama a `self.call_tool` desde su manejador de `tools/call` y deja
   pasar tal cual un `CallToolResult`, así que basta con sobrescribir ese
   método. Las excepciones ya las marca el SDK por su cuenta.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, TextContent

from hermes import __version__

# Tools cuyo `{"error": …}` acompaña a un resultado útil y por eso NO deben
# marcarse como fallo (nombre → motivo). La auditoría de la spec 003 (R-B3)
# no encontró ninguna: en todas las respuestas con `error` en el nivel superior
# los demás campos (`detail`, `hint`, `path`…) solo explican el fallo. Si
# aparece una, se añade aquí con su motivo y un test, sin cambiar la forma de
# su respuesta: marcar como error un resultado parcial confundiría al cliente.
_NOT_AN_ERROR: dict[str, str] = {}


def _is_error_payload(result: CallToolResult) -> bool:
    """¿Es este resultado un `{"error": …}` de Hermes?

    Solo cuenta un objeto con `error` no nulo en el nivel superior. Un `error`
    anidado es un dato (por ejemplo, el estado de algo en HA), y una vista
    previa con `confirmation_token` es el primer paso de una confirmación, no
    un fallo, aunque traiga un aviso con esa clave.
    """
    if len(result.content) != 1 or not isinstance(result.content[0], TextContent):
        return False
    try:
        payload = json.loads(result.content[0].text)
    except ValueError:
        return False
    return (
        isinstance(payload, dict)
        and payload.get("error") is not None
        and "confirmation_token" not in payload
    )


class HermesMCPServer(MCPServer):
    """`MCPServer` que marca `isError` en las respuestas `{"error": …}`."""

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Any = None
    ) -> Any:
        result = await super().call_tool(name, arguments, context)
        if (
            isinstance(result, CallToolResult)
            and not result.is_error
            and name not in _NOT_AN_ERROR
            and _is_error_payload(result)
        ):
            # Copia con el mismo contenido: el cliente sigue leyendo el JSON
            # de siempre y, además, sabe que es un fallo.
            return result.model_copy(update={"is_error": True})
        return result


def build_mcp_server(instructions: str) -> HermesMCPServer:
    """Crea el servidor MCP de Hermes con nombre y versión."""
    return HermesMCPServer("hermes", instructions=instructions, version=__version__)
