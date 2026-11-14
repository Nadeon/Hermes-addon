"""`response_max_bytes` en todas las tools (spec 006, historia 2).

Hasta 1.1.0 el tope solo lo cumplían las tools que lo recibían y recortaban
por su cuenta. `ha_get_states(domain="sensor")` devolvió en vivo unos 245 KB
con el tope en 128 KiB, sin recorte ni aviso, aunque el CHANGELOG decía que se
aplicaba a todas. Desde 1.1.1 lo aplica `HermesMCPServer.call_tool`, el único
camino de `tools/call`.

Todos los datos son ficticios (`sensor.test_*`).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import ClientSession
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, TextContent

from hermes.mcp_server import HermesMCPServer, build_mcp_server
from hermes.tools import register_all_tools
from hermes.tools._common import recortar_a_bytes, tam_json
from tests._ha_fixture import make_ready_client

pytestmark = pytest.mark.anyio

TOPE = 131_072


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _server(ha_client: Any, tope: int = TOPE) -> HermesMCPServer:
    server = build_mcp_server("x")
    register_all_tools(
        server,
        ha_client,
        fire_event_allowlist=[],
        response_max_bytes=tope,
        safety_backup_window_minutes=30,
        safety_backup_enabled=False,
        file_backup_max_per_path=20,
        file_backup_max_total_mb=200,
        config_write_min_interval_seconds=5,
        config_write_max_per_minute=10,
        call_service_denylist_extra=[],
        call_service_restricted_entities=[],
        # False: sin la task de auto-clasificación, que pediría la WS.
        call_service_auto_classify=False,
        wait_for_event_max_seconds=90,
        wait_for_event_max_concurrent=5,
        safety_backup_keep=3,
    )
    return server


def _bytes(result: CallToolResult) -> int:
    return sum(len(b.text.encode("utf-8")) for b in result.content)


def _sensores(n: int = 465) -> dict[str, dict[str, Any]]:
    """Unos 245 KB de estados compactos, como en la prueba en vivo."""
    out = {}
    for i in range(n):
        eid = f"sensor.test_{i:04d}"
        out[eid] = {
            "entity_id": eid,
            "state": str(i),
            "attributes": {
                "friendly_name": f"Test sensor {i}",
                "unit_of_measurement": "W",
                "device_class": "power",
                "state_class": "measurement",
                "note": "x" * 320,
            },
            "last_changed": "2026-11-14T10:00:00+00:00",
            "last_updated": "2026-11-14T10:00:00+00:00",
        }
    return out


# ── El caso que falló en vivo ─────────────────────────────────────


async def test_ha_get_states_respeta_el_tope_y_lo_dice() -> None:
    async with ClientSession() as session:
        ha_client = make_ready_client(session, _sensores())
        server = _server(ha_client)
        async with Client(server) as client:
            result = await client.call_tool("ha_get_states", {"domain": "sensor"})
    assert _bytes(result) <= TOPE
    payload = json.loads(result.content[0].text)
    assert payload["truncated"] is True
    assert payload["total"] == 465
    assert 0 < payload["count"] == len(payload["items"]) < 465
    # Se recorta por el final: los primeros llegan enteros.
    assert payload["items"][0]["entity_id"] == "sensor.test_0000"
    assert payload["_response_limit"]["max_bytes"] == TOPE
    assert result.is_error is False


async def test_ha_get_states_pequeno_sale_igual() -> None:
    """Lo que cabe no se toca: la misma lista de siempre."""
    async with ClientSession() as session:
        ha_client = make_ready_client(session, _sensores(3))
        server = _server(ha_client)
        async with Client(server) as client:
            result = await client.call_tool("ha_get_states", {"domain": "sensor"})
    payload = json.loads(result.content[0].text)
    assert isinstance(payload, list) and len(payload) == 3


# ── Todas las tools registradas ───────────────────────────────────


_LISTA = [{"entity_id": f"sensor.test_{i}", "v": "y" * 60} for i in range(3000)]
_FORMAS: dict[str, Any] = {
    "lista": _LISTA,
    "objeto_con_lista": {"count": 3000, "truncated": False, "items": _LISTA},
    "texto": "z" * 200_000,
    "json_texto": json.dumps({"entries": _LISTA}),
}


async def test_ninguna_tool_registrada_pasa_del_tope() -> None:
    """Recorre las 216 tools: con cualquier resultado enorme que la tool
    pudiera producir, lo que sale del servidor cabe en el tope.

    El resultado se construye con la conversión real de cada tool
    (`fn_metadata.convert_result`), así que vale también para las que tienen
    `outputSchema` o devuelven una lista (un bloque por elemento)."""
    tope = 16_384
    server = _server(MagicMock(), tope)
    tools = server._tool_manager.list_tools()
    assert len(tools) >= 200, "no se han registrado las tools de Hermes"

    revisadas = 0
    for tool in tools:
        for forma, valor in _FORMAS.items():
            try:
                bruto = tool.fn_metadata.convert_result(valor)
            except Exception:
                # Una tool con `outputSchema` de texto no puede devolver un
                # objeto: esa forma no se le puede dar.
                continue
            assert _bytes(bruto) > tope

            async def falso(self, name, arguments, context=None, _r=bruto):
                return _r

            with patch.object(MCPServer, "call_tool", falso):
                result = await server.call_tool(tool.name, {})
            assert _bytes(result) <= tope, (tool.name, forma)
            payload = json.loads(result.content[0].text)
            if forma in ("texto",):
                assert payload["error"] == "response_too_large", (tool.name, forma)
                assert result.is_error is True
            else:
                assert payload["truncated"] is True, (tool.name, forma)
            revisadas += 1
    assert revisadas >= 3 * len(tools)


# ── El recorte ────────────────────────────────────────────────────


def test_recorte_de_objeto_marca_truncated_y_mantiene_lo_demas() -> None:
    payload = {"count": 3000, "truncated": False, "items": _LISTA, "api": "x"}
    out = recortar_a_bytes(payload, 8192)
    assert tam_json(out) <= 8192
    assert out["truncated"] is True and out["api"] == "x"
    assert out["_response_limit"]["list"] == "items"
    assert out["_response_limit"]["total"] == 3000
    assert out["_response_limit"]["returned"] == len(out["items"])


def test_recorte_sin_lista_es_error_explicito() -> None:
    out = recortar_a_bytes({"a": {"b": "c" * 50_000}}, 8192)
    assert out["error"] == "response_too_large"


def test_sangria_del_sdk_no_cuesta_datos() -> None:
    """Una respuesta que la tool ya ajustó al tope pero que el SDK serializa
    con sangría se reserializa compacta, sin quitar nada."""
    from hermes.mcp_server import _limitar

    payload = {"items": [{"k": i} for i in range(400)]}
    tope = tam_json(payload) + 10
    con_sangria = json.dumps(payload, indent=2)
    assert len(con_sangria) > tope
    result = CallToolResult(content=[TextContent(type="text", text=con_sangria)])
    out = _limitar(result, tope)
    assert json.loads(out.content[0].text) == payload
