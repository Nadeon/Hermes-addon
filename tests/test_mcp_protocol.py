"""Superficie de protocolo del servidor MCP de Hermes (spec 003, lote B).

Dos promesas que el cliente lee en cada conexión y cada llamada:

- `serverInfo.version` dice qué Hermes responde. Hasta 1.0.12 salía vacía, y
  quien diagnosticaba un fallo desde el cliente no podía saber qué versión
  tenía delante (FR-039).
- `isError` distingue un fallo de un resultado. Las tools de Hermes devuelven
  sus fallos como `{"error": …}` y el SDK los entregaba con `isError: false`:
  el cliente tenía que leer el JSON para enterarse. La spec MCP pide que los
  errores de ejecución vayan marcados en el resultado (FR-041).

Los tests hablan con el servidor a través del cliente en memoria del SDK, el
mismo camino que recorre una llamada real, para que la marca se vea donde la ve
el cliente y no solo en el valor devuelto por un método.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp import Client

import hermes
from hermes.mcp_server import _NOT_AN_ERROR, HermesMCPServer, build_mcp_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _server_with(results: dict[str, Any]) -> HermesMCPServer:
    """Servidor de Hermes con una tool de prueba por cada resultado dado."""
    server = build_mcp_server("instrucciones de prueba")
    for name, value in results.items():
        def make(value: Any):
            async def fn() -> object:
                return value
            return fn
        server.tool(name=name)(make(value))
    return server


async def _plain_sdk_text(value: Any) -> str:
    """El texto que el SDK genera para ese valor sin la subclase de Hermes."""
    from mcp.server.mcpserver import MCPServer

    plain = MCPServer("plain")

    @plain.tool(name="t")
    async def t() -> object:
        return value

    result = await plain.call_tool("t", {})
    return result.content[0].text


# ── version (FR-039) ─────────────────────────────────────────────

def test_build_mcp_server_announces_name_and_version() -> None:
    server = build_mcp_server("x")
    assert isinstance(server, HermesMCPServer)
    assert server.name == "hermes"
    assert server.version == hermes.__version__
    assert server.version, "serverInfo.version no puede salir vacía"


async def test_server_info_reaches_the_client_with_version() -> None:
    async with Client(build_mcp_server("x")) as client:
        assert client.server_info is not None
        assert client.server_info.name == "hermes"
        assert client.server_info.version == hermes.__version__


# ── isError (FR-041) ─────────────────────────────────────────────

NOT_FOUND = {"error": "not_found", "entity_id": "light.x"}


async def test_top_level_error_is_marked_with_the_same_text() -> None:
    server = _server_with({"falla": NOT_FOUND})
    async with Client(server) as client:
        result = await client.call_tool("falla", {})
    assert result.is_error is True
    assert len(result.content) == 1
    # El contenido no cambia: el cliente sigue leyendo el mismo JSON de antes.
    assert result.content[0].text == await _plain_sdk_text(NOT_FOUND)
    assert json.loads(result.content[0].text) == NOT_FOUND


async def test_error_serialized_as_json_string_is_marked_too() -> None:
    """Varias tools (config entries, flows) devuelven `json.dumps(...)`."""
    texto = json.dumps({"error": "not_found", "entry_id": "abc"})
    server = _server_with({"falla": texto})
    async with Client(server) as client:
        result = await client.call_tool("falla", {})
    assert result.is_error is True
    assert result.content[0].text == texto


@pytest.mark.parametrize(
    "value",
    [
        pytest.param({"preview": {"action": "delete"}, "confirmation_token": "t"}, id="preview"),
        pytest.param(
            {"preview": {"action": "delete"}, "confirmation_token": "t", "error": "x"},
            id="preview-con-error",
        ),
        pytest.param({"ok": True}, id="ok"),
        pytest.param({"error": None, "ok": True}, id="error-null"),
        pytest.param({"result": {"error": "anidado"}}, id="error-anidado"),
        # El SDK convierte cada elemento de una lista en un contenido aparte;
        # con dos o más ya no hay un único objeto que mirar. (Una lista de un
        # solo elemento sale idéntica a ese objeto y no se puede distinguir.)
        pytest.param([{"error": "en-lista"}, {"ok": True}], id="lista"),
        pytest.param("texto libre con la palabra error", id="prosa"),
        pytest.param(json.dumps({"error": None}), id="json-error-null"),
    ],
)
async def test_non_errors_are_not_marked(value: Any) -> None:
    server = _server_with({"bien": value})
    async with Client(server) as client:
        result = await client.call_tool("bien", {})
    assert result.is_error is False
    assert result.content[0].text == await _plain_sdk_text(value)


async def test_exception_is_still_an_error() -> None:
    """Control: el SDK ya marcaba las excepciones; la subclase no lo estropea."""
    server = build_mcp_server("x")

    @server.tool(name="revienta")
    async def revienta() -> object:
        raise RuntimeError("boom")

    async with Client(server) as client:
        result = await client.call_tool("revienta", {})
    assert result.is_error is True


# ── Auditoría R-B3 ───────────────────────────────────────────────

def test_no_tool_is_exempted_without_a_reason() -> None:
    """La auditoría R-B3 no encontró tools que devuelvan `error` junto a un
    resultado útil: todas las respuestas con `error` en el nivel superior son
    fallos, y los demás campos (`detail`, `hint`, `path`…) solo los explican.
    Si algún día se añade una excepción, tiene que llevar su motivo."""
    assert isinstance(_NOT_AN_ERROR, dict)
    for name, reason in _NOT_AN_ERROR.items():
        assert name and reason, f"excepción sin motivo: {name!r}"


async def test_exempted_tool_is_not_marked(monkeypatch: pytest.MonkeyPatch) -> None:
    """La lista de excepciones funciona: una tool listada no se marca."""
    monkeypatch.setitem(_NOT_AN_ERROR, "parcial", "resultado parcial útil")
    server = _server_with({"parcial": {"error": "x", "items": [1]}})
    async with Client(server) as client:
        result = await client.call_tool("parcial", {})
    assert result.is_error is False
