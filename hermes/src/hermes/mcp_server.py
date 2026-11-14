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

3. `response_max_bytes` en TODAS las tools (spec 006). Hasta 1.1.0 cada
   módulo recortaba por su cuenta y los que no recibían el tope lo ignoraban:
   `ha_get_states(domain="sensor")` devolvía 245 KB con el tope en 128 KiB.
   Aplicarlo aquí, en el único camino de `tools/call`, hace que no dependa de
   que cada tool se acuerde. Las que ya recortan siguen haciéndolo con su
   forma propia y miden la respuesta ENTERA, envoltorio incluido: si se
   pasaran por unos bytes, esto las recortaría otra vez o las cambiaría por
   `response_too_large` (revisión de 1.1.1, B-1). Esto es la red de seguridad,
   y nunca quita el `confirmation_token` de una vista previa (A-1).
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, TextContent

from hermes import __version__
from hermes.tools._common import recortar_a_bytes

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


def _limitar(result: CallToolResult, max_bytes: int) -> CallToolResult:
    """El mismo resultado si cabe en `max_bytes`; si no, uno que cabe.

    Se mide lo que de verdad viaja: la suma de los textos. Una tool que
    devuelve una lista Python llega aquí como un bloque por elemento, y el
    SDK serializa los objetos con sangría, así que hasta una tool que ya
    recortó a su tope puede pasarse: por eso se reserializa en compacto antes
    de quitar nada.
    """
    if not result.content or not all(isinstance(b, TextContent) for b in result.content):
        return result
    if sum(len(b.text.encode("utf-8")) for b in result.content) <= max_bytes:
        return result

    def valor(texto: str) -> Any:
        try:
            return json.loads(texto)
        except ValueError:
            return texto

    valores = [valor(b.text) for b in result.content]
    payload = valores[0] if len(valores) == 1 else valores
    nuevo = recortar_a_bytes(payload, max_bytes)
    texto = nuevo if isinstance(nuevo, str) else json.dumps(nuevo, ensure_ascii=False)
    # Sin `structured_content`: llevaría el resultado entero otra vez.
    return result.model_copy(update={
        "content": [TextContent(type="text", text=texto)],
        "structured_content": None,
    })


class HermesMCPServer(MCPServer):
    """`MCPServer` que marca `isError` y aplica `response_max_bytes`."""

    # Lo fija `register_all_tools`, que es quien resuelve el valor efectivo.
    # `None` (servidor sin tools de Hermes, tests de protocolo) no limita.
    response_max_bytes: int | None = None

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Any = None
    ) -> Any:
        result = await super().call_tool(name, arguments, context)
        if isinstance(result, CallToolResult) and self.response_max_bytes:
            # Antes de marcar `isError`: `response_too_large` es un fallo.
            result = _limitar(result, self.response_max_bytes)
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
