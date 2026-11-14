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


# ── Revisión de 1.1.1: tools que ya recortaban, vistas previas y logs ──
#
# El recorrido de arriba solo da al guardián formas sintéticas. Estos tests
# llaman a las tools REALES por el servidor MCP en memoria, con un HA
# simulado que devuelve más de lo que cabe, y comprueban que salen datos
# útiles con su aviso: nunca `response_too_large` (B-1, M-1, M-2, M-4).


def _cliente_ws(session: ClientSession, resultado: Any) -> Any:
    ha_client = make_ready_client(session, {})

    async def ws_send(payload: dict, timeout_seconds: int = 30) -> Any:
        return resultado

    ha_client.ws_send = ws_send  # type: ignore[method-assign]
    return ha_client


async def _llamar(ha_client: Any, tool: str, args: dict, tope: int) -> tuple[CallToolResult, Any]:
    server = _server(ha_client, tope)
    async with Client(server) as client:
        result = await client.call_tool(tool, args)
    assert _bytes(result) <= tope, (tool, _bytes(result))
    return result, json.loads(result.content[0].text)


def _sin_error(result: CallToolResult, payload: Any, tool: str) -> None:
    assert result.is_error is False, (tool, payload)
    assert "error" not in payload, (tool, payload)


async def test_history_amplio_recorta_con_datos_y_no_da_error() -> None:
    """B-1: 3000 puntos y tope de 10 KiB daban `response_too_large`."""
    puntos = [
        {"s": "encendido", "a": {"friendly_name": "Salón ñ"}, "lu": 1_712_000_000.0 + i}
        for i in range(3000)
    ]
    for tope in (10_240, 10_272, 12_000, 16_384):
        async with ClientSession() as session:
            ha_client = _cliente_ws(session, {"light.test": puntos})
            result, payload = await _llamar(
                ha_client, "ha_get_history",
                {"entity_ids": ["light.test"], "hours_back": 48}, tope,
            )
        _sin_error(result, payload, "ha_get_history")
        assert payload["truncated"] is True
        assert payload["history"]["light.test"], tope
        assert payload["truncated_at"] == payload["history"]["light.test"][-1]["last_updated"]
        # Lo recortó la tool, no el guardián.
        assert "_response_limit" not in payload


async def test_statistics_amplio_recorta_con_datos_y_no_da_error() -> None:
    """B-1: 5 ids × 400 puntos fallaban en 50 de 50 casos."""
    raw = {
        f"sensor.test_{n}": [
            {"start": 1_712_000_000_000 + i * 3_600_000,
             "end": 1_712_003_600_000 + i * 3_600_000, "mean": 1.5, "min": 1.0, "max": 2.0}
            for i in range(400)
        ]
        for n in range(5)
    }
    async with ClientSession() as session:
        ha_client = _cliente_ws(session, raw)
        result, payload = await _llamar(
            ha_client, "ha_statistics_during_period",
            {"statistic_ids": list(raw), "hours_back": 400}, 16_384,
        )
    _sin_error(result, payload, "ha_statistics_during_period")
    assert payload["truncated"] is True
    assert all(payload["statistics"][sid] for sid in raw)
    assert payload["covered_range"]["start"] is not None
    assert "_response_limit" not in payload


async def test_logbook_recortado_cuenta_bien_y_no_pierde_eventos_al_paginar() -> None:
    """M-1: el guardián quitaba más eventos y `count`/`truncated_at` seguían
    apuntando al último que había quitado."""
    eventos = [
        {"when": 1_712_000_000.0 + i, "entity_id": "light.test", "name": "Luz ñ",
         "message": "turned on", "state": "on"}
        for i in range(400)
    ]
    for tope in (10_240, 12_345, 16_384):
        async with ClientSession() as session:
            ha_client = _cliente_ws(session, eventos)
            result, payload = await _llamar(ha_client, "ha_get_logbook", {}, tope)
        _sin_error(result, payload, "ha_get_logbook")
        assert payload["truncated"] is True
        assert payload["count"] == len(payload["events"]) > 0
        assert payload["truncated_at"] == payload["events"][-1]["when"]
        assert "_response_limit" not in payload


async def test_registros_y_config_entries_recortados_cuentan_bien() -> None:
    """M-1: `count`/`returned` no coincidían con la lista devuelta."""
    entidades = [
        {"entity_id": f"sensor.test_{i}", "platform": "test", "name": "Sensor ñ",
         "disabled_by": None, "device_id": None, "area_id": None, "x": "y" * 200}
        for i in range(300)
    ]
    dispositivos = [
        {"id": f"d{i}", "name": "Dispositivo ñ", "manufacturer": "ACME",
         "disabled_by": None, "area_id": None, "x": "y" * 200}
        for i in range(300)
    ]
    entradas = [
        {"entry_id": f"e{i}", "domain": "test", "title": "Entrada ñ", "x": "y" * 200}
        for i in range(300)
    ]
    casos = [
        ("ha_list_entities_registry", entidades, "entities", "count"),
        ("ha_list_devices", dispositivos, "devices", "count"),
        ("ha_list_config_entries", entradas, "entries", "returned"),
    ]
    for tool, datos, clave, recuento in casos:
        for tope in (10_240, 12_345):
            async with ClientSession() as session:
                ha_client = _cliente_ws(session, datos)
                result, payload = await _llamar(ha_client, tool, {}, tope)
            _sin_error(result, payload, tool)
            assert payload["truncated"] is True, tool
            assert payload[recuento] == len(payload[clave]) > 0, (tool, tope)
            assert "_response_limit" not in payload, tool


async def test_fs_read_file_de_lineas_cortas_recorta_y_no_da_error(tmp_path) -> None:
    """B-1 en ficheros: el margen fijo de 2 KiB no cubría los `\\n` y `\\"`
    escapados de un YAML de líneas cortas."""
    import hermes.fs as fs_module

    (tmp_path / "grande.yaml").write_text(
        "".join(f'k{i}: "v"\n' for i in range(40_000)), encoding="utf-8"
    )
    with patch.object(fs_module, "CONFIG_BASE", tmp_path.resolve()):
        async with ClientSession() as session:
            result, payload = await _llamar(
                make_ready_client(session, {}), "fs_read_file", {"path": "grande.yaml"}, TOPE,
            )
    _sin_error(result, payload, "fs_read_file")
    assert payload["truncated"] is True
    n = payload["truncated_at_line"]
    assert n > 0 and payload["content"].count("\n") == n


async def test_logs_largos_de_un_addon_devuelven_las_ultimas_lineas() -> None:
    """M-2: un log que no cabía pasaba a `response_too_large`."""
    lineas = [f"2026-11-14 10:00:{i:04d} INFO linea {i} " + "x" * 220 for i in range(1000)]
    async with ClientSession() as session:
        ha_client = make_ready_client(session, {})

        async def sv_request_text(path: str, params: dict | None = None) -> str:
            return "\n".join(lineas) + "\n"

        ha_client.sv_request_text = sv_request_text  # type: ignore[method-assign]
        result, payload = await _llamar(
            ha_client, "sv_get_addon_logs", {"slug": "core_mosquitto", "lines": 1000}, TOPE,
        )
    _sin_error(result, payload, "sv_get_addon_logs")
    assert payload["truncated"] is True
    devueltas = payload["logs"].splitlines()
    assert devueltas[-1] == lineas[-1]
    assert payload["lines_returned"] == len(devueltas) > 0
    assert "lines" in payload["hint"]


async def test_fs_delete_file_de_un_fichero_grande_conserva_el_token(tmp_path) -> None:
    """A-1: la vista previa con el fichero entero pasaba del tope y el
    guardián se comía el `confirmation_token`: el borrado era imposible."""
    import hermes.fs as fs_module

    objetivo = tmp_path / "paquetes" / "grande.yaml"
    objetivo.parent.mkdir()
    objetivo.write_text("".join(f"k{i}: v\n" for i in range(30_000)), encoding="utf-8")
    assert objetivo.stat().st_size > 200_000
    with patch.object(fs_module, "CONFIG_BASE", tmp_path.resolve()):
        async with ClientSession() as session:
            ha_client = make_ready_client(session, {})
            server = _server(ha_client)
            async with Client(server) as client:
                primera = await client.call_tool(
                    "fs_delete_file", {"path": "paquetes/grande.yaml"}
                )
                assert _bytes(primera) <= TOPE
                vista = json.loads(primera.content[0].text)
                assert primera.is_error is False, vista
                assert vista["confirmation_token"]
                assert vista["preview_truncated"] is True
                omitido = vista["preview"]["current_content"]
                assert omitido["_omitted"] is True and omitido["lines"] == 30_000
                # Lo que sí cabe se ve entero.
                assert vista["preview"]["path"] == "paquetes/grande.yaml"
                segunda = await client.call_tool(
                    "fs_delete_file",
                    {"path": "paquetes/grande.yaml",
                     "confirmation_token": vista["confirmation_token"]},
                )
    assert segunda.is_error is False, segunda.content[0].text
    assert not objetivo.exists()


# ── El guardián, en unidad ────────────────────────────────────────


def test_vista_previa_grande_nunca_pierde_el_token() -> None:
    """A-1: `current` y `new` de una automatización de más de 64 KiB."""
    grande = {"alias": "x", "actions": [{"service": "light.turn_on", "n": i} for i in range(3000)]}
    payload = {
        "confirmation_token": "tok", "expires_in_seconds": 60,
        "preview": {"automation_id": "automation.test", "current": grande, "new": grande},
    }
    out = recortar_a_bytes(payload, 16_384)
    assert tam_json(out) <= 16_384
    assert out["confirmation_token"] == "tok"
    assert out["preview_truncated"] is True
    assert out["preview"]["automation_id"] == "automation.test"
    assert out["preview"]["current"]["_omitted"] is True
    assert out["preview"]["current"]["keys"] == ["actions", "alias"]
    # Una lista de la vista previa nunca se recorta a medias.
    assert "truncated" not in out
    # Ni con un tope absurdo se pierde el token.
    assert recortar_a_bytes(payload, 200)["confirmation_token"] == "tok"


def test_diccionario_de_listas_se_recorta_en_vez_de_dar_error() -> None:
    """B-1, red de seguridad: `{id: [puntos]}` sin lista en el nivel superior."""
    payload = {
        "history": {f"sensor.test_{n}": [{"s": "1", "i": i} for i in range(500)] for n in range(4)},
        "truncated": False, "truncated_at": None,
    }
    out = recortar_a_bytes(payload, 8192, recortar_anidadas=True)
    assert tam_json(out) <= 8192
    assert out["truncated"] is True
    assert all(out["history"].values())
    assert out["_response_limit"]["list"] == "history"
    assert out["_response_limit"]["total"] == 2000
    assert "truncated_at" not in out


def test_un_objeto_con_mas_campos_no_se_recorta_por_dentro() -> None:
    """Una vista de Lovelace recortada a medias se podría guardar de vuelta."""
    vista = {"view": {"title": "x", "cards": [{"type": "entities", "i": i} for i in range(3000)]}}
    assert recortar_a_bytes(vista, 8192)["error"] == "response_too_large"


def test_recuentos_de_la_tool_se_corrigen_al_recortar() -> None:
    """M-1: `count`, `returned` y `truncated_at` no pueden quedar obsoletos."""
    payload = {"count": 3000, "returned": 3000, "truncated": False,
               "truncated_at": 99, "items": _LISTA}
    out = recortar_a_bytes(payload, 8192)
    assert out["count"] == out["returned"] == len(out["items"]) < 3000
    assert "truncated_at" not in out
    # Un `count` que era el total de otra cosa se deja.
    otro = recortar_a_bytes({"count": 7, "items": _LISTA}, 8192)
    assert otro["count"] == 7


def test_la_pista_del_error_no_dice_que_se_recorto() -> None:
    """L-1: `response_too_large` no devuelve nada; su pista no puede decir
    «The response was cut»."""
    out = recortar_a_bytes({"a": {"b": "c" * 50_000}}, 8192)
    assert "was cut" not in out["hint"]
    assert "Nothing was returned" in out["hint"]


_FORMAS_1_1_1: dict[str, Any] = {
    # Cerca del tope y con envoltorio: lo que la tool ya ajustó a mano.
    "dict_de_listas": {"history": {"a": _LISTA[:1500], "b": _LISTA[1500:]},
                       "truncated": True, "truncated_at": "x"},
    "vista_previa": {"confirmation_token": "tok", "expires_in_seconds": 60,
                     "preview": {"path": "x", "current_content": "l\n" * 100_000}},
}


async def test_ninguna_tool_pierde_datos_ni_token_con_formas_de_1_1_1() -> None:
    """M-4: el recorrido de todas las tools con las formas que no cubría:
    un `{id: [puntos]}` cerca del tope y una vista previa con token. El
    `{id: [puntos]}` solo se recorta en las tools de series de la lista
    blanca; en las demás falla cerrado (N-1)."""
    from hermes.mcp_server import RECORTE_ANIDADO

    tope = 16_384
    server = _server(MagicMock(), tope)
    tools = server._tool_manager.list_tools()
    revisadas = 0
    for tool in tools:
        for forma, valor in _FORMAS_1_1_1.items():
            try:
                bruto = tool.fn_metadata.convert_result(valor)
            except Exception:
                continue

            async def falso(self, name, arguments, context=None, _r=bruto):
                return _r

            with patch.object(MCPServer, "call_tool", falso):
                result = await server.call_tool(tool.name, {})
            assert _bytes(result) <= tope, (tool.name, forma)
            payload = json.loads(result.content[0].text)
            if forma == "dict_de_listas" and tool.name not in RECORTE_ANIDADO:
                assert payload["error"] == "response_too_large", tool.name
                assert result.is_error is True, tool.name
                revisadas += 1
                continue
            assert result.is_error is False, (tool.name, forma)
            if forma == "vista_previa":
                assert payload["confirmation_token"] == "tok", tool.name
                assert payload["preview_truncated"] is True, tool.name
            else:
                assert payload["truncated"] is True, tool.name
                assert payload["history"]["a"] and payload["history"]["b"], tool.name
            revisadas += 1
    assert revisadas >= 2 * len(tools) - 4


# ── Verificación de 1.1.1, N-1: objetos que se guardan de vuelta ──
#
# 0533c73 recortaba por dentro CUALQUIER objeto cuyos valores fueran todos
# listas. Un script `{"sequence": [...]}` o una vista `{"cards": [...]}` salían
# recortados con `is_error: false`; si el agente los editaba y los guardaba,
# perdía pasos o tarjetas. Solo las tools de series de la lista blanca pueden
# recortar listas anidadas; el resto falla cerrado con `response_too_large`.


async def test_script_grande_sin_alias_no_sale_recortado() -> None:
    """N-1, escenario 2: `ha_get_script` de un script de 3000 pasos."""
    config = {"sequence": [{"service": "light.turn_on", "n": i, "x": "y" * 40} for i in range(3000)]}
    async with ClientSession() as session:
        ha_client = make_ready_client(
            session, {"script.test": {"entity_id": "script.test", "state": "off"}}
        )

        async def config_read(domain: str, object_id: str) -> Any:
            return config

        ha_client.config_read = config_read  # type: ignore[method-assign]
        result, payload = await _llamar(
            ha_client, "ha_get_script", {"script_id": "script.test"}, TOPE,
        )
    assert result.is_error is True, payload
    assert payload["error"] == "response_too_large"
    assert "config" not in payload


async def test_vista_de_lovelace_grande_no_sale_recortada() -> None:
    """N-1, escenario 1: dashboard con solo `views` y una vista de 1500 cards.

    `top_level_keys` sale vacío, así que no hay lista de primer nivel; la
    vista recortada se podía guardar con la receta `{**top_level, views}`."""
    vista = {"cards": [{"type": "entities", "entity": f"sensor.test_{i}", "x": "y" * 100}
                       for i in range(1500)]}
    config = {"views": [{"cards": []}, vista]}
    async with ClientSession() as session:
        ha_client = _cliente_ws(session, config)
        result, payload = await _llamar(
            ha_client, "ha_get_lovelace_dashboard", {"view_index": 1}, TOPE,
        )
    assert result.is_error is True, payload
    assert payload["error"] == "response_too_large"
    assert "view" not in payload


async def test_dashboard_entero_que_cabe_sale_intacto() -> None:
    """La lectura completa de un dashboard nunca se recorta por arriba: o
    cabe entera, o la propia tool da `too_large` con `top_level`."""
    vistas = [{"title": f"v{i}", "cards": [{"type": "entities", "x": "y" * 100}] * 40}
              for i in range(40)]
    config = {"title": "Casa", "views": vistas}
    async with ClientSession() as session:
        ha_client = _cliente_ws(session, config)
        _, cabe = await _llamar(
            ha_client, "ha_get_lovelace_dashboard", {}, tam_json(config) + 10,
        )
        _, no_cabe = await _llamar(
            ha_client, "ha_get_lovelace_dashboard", {}, tam_json(config) - 10,
        )
    assert cabe == config
    assert no_cabe["error"] == "too_large"
    assert no_cabe["top_level"] == {"title": "Casa"}
    assert "views" not in no_cabe


def test_dict_de_listas_solo_se_recorta_si_se_pide() -> None:
    """La red de `{id: [puntos]}` es opcional y por defecto falla cerrado."""
    script = {"config": {"sequence": [{"n": i, "x": "y" * 40} for i in range(3000)]},
              "state": {"entity_id": "script.test"}}
    assert recortar_a_bytes(script, 8192)["error"] == "response_too_large"
    out = recortar_a_bytes(script, 8192, recortar_anidadas=True)
    assert out["truncated"] is True


async def test_el_guardian_solo_recorta_listas_anidadas_en_la_lista_blanca() -> None:
    """Con la misma respuesta `{x: {id: [puntos]}}`, solo history y
    statistics la recortan; `ha_get_script` y la vista de Lovelace fallan."""
    from hermes.mcp_server import RECORTE_ANIDADO

    assert RECORTE_ANIDADO == frozenset({"ha_get_history", "ha_statistics_during_period"})
    tope = 16_384
    server = _server(MagicMock(), tope)
    valor = _FORMAS_1_1_1["dict_de_listas"]
    for nombre in ("ha_get_history", "ha_statistics_during_period",
                   "ha_get_script", "ha_get_automation", "ha_get_lovelace_dashboard",
                   "sv_get_addon_options"):
        bruto = server._tool_manager.get_tool(nombre).fn_metadata.convert_result(valor)

        async def falso(self, name, arguments, context=None, _r=bruto):
            return _r

        with patch.object(MCPServer, "call_tool", falso):
            result = await server.call_tool(nombre, {})
        payload = json.loads(result.content[0].text)
        if nombre in RECORTE_ANIDADO:
            assert payload["truncated"] is True, nombre
        else:
            assert payload["error"] == "response_too_large", nombre
            assert result.is_error is True, nombre


# ── Verificación de 1.1.1, N-2: topes por cantidad que no avisaban ──


async def test_topes_por_cantidad_marcan_truncated() -> None:
    """N-2: history con 3000 estados devolvía 500 con `truncated: false`."""
    from hermes.tools.history import _MAX_STATES_PER_ENTITY
    from hermes.tools.logbook import _MAX_EVENTS
    from hermes.tools.statistics import _MAX_POINTS_PER_STATISTIC

    historia = {"light.test": [{"s": "on", "lu": 1_712_000_000.0 + i}
                               for i in range(_MAX_STATES_PER_ENTITY + 50)]}
    estadisticas = {"sensor.test": [{"start": 1_712_000_000_000 + i * 3_600_000,
                                     "end": 1_712_003_600_000 + i * 3_600_000, "mean": 1.0}
                                    for i in range(_MAX_POINTS_PER_STATISTIC + 50)]}
    eventos = [{"when": 1_712_000_000.0 + i, "entity_id": "light.test"}
               for i in range(_MAX_EVENTS + 10)]
    tope = 8 * 1024 * 1024
    async with ClientSession() as session:
        _, h = await _llamar(_cliente_ws(session, historia), "ha_get_history",
                             {"entity_ids": ["light.test"]}, tope)
        _, s = await _llamar(_cliente_ws(session, estadisticas), "ha_statistics_during_period",
                             {"statistic_ids": ["sensor.test"]}, tope)
        _, e = await _llamar(_cliente_ws(session, eventos), "ha_get_logbook", {}, tope)
    assert len(h["history"]["light.test"]) == _MAX_STATES_PER_ENTITY
    assert h["truncated"] is True
    assert h["truncated_at"] == h["history"]["light.test"][-1]["last_updated"]
    assert len(s["statistics"]["sensor.test"]) == _MAX_POINTS_PER_STATISTIC
    assert s["truncated"] is True
    assert s["truncated_at"] == s["statistics"]["sensor.test"][-1]["end"]
    assert e["count"] == _MAX_EVENTS
    assert e["truncated"] is True
    assert e["truncated_at"] == e["events"][-1]["when"]


# ── Verificación de 1.1.1, N-3: recorte cuadrático ────────────────


def test_recorte_de_history_y_statistics_es_lineal() -> None:
    """N-3: 20 entidades × 500 estados con atributos tardaban ~60 s de CPU,
    con el bucle de eventos bloqueado (y la WS de HA sin heartbeat)."""
    import time

    from hermes.tools.history import _truncate_to_bytes
    from hermes.tools.statistics import _truncate_stats_to_bytes

    estados = {
        f"sensor.test_{n}": [
            {"state": str(i), "last_updated": f"2026-11-14T10:{i % 60:02d}:00+00:00",
             "last_changed": f"2026-11-14T10:{i % 60:02d}:00+00:00",
             "attributes": {"friendly_name": "Sensor ñ", "nota": "x" * 280}}
            for i in range(500)
        ]
        for n in range(20)
    }
    inicio = time.process_time()
    final, recortado, _ = _truncate_to_bytes(estados, TOPE)
    assert time.process_time() - inicio < 5
    assert recortado is True
    assert tam_json({"history": final, "truncated": True,
                     "truncated_at": "2026-11-14T10:00:00+00:00"}) <= TOPE
    # Iguala longitudes, como antes: ninguna entidad se queda sin datos.
    longitudes = {len(v) for v in final.values()}
    assert max(longitudes) - min(longitudes) <= 1 and min(longitudes) > 0

    puntos = {k: [{"start": f"2026-11-14T{i % 24:02d}:00:00+00:00",
                   "end": f"2026-11-14T{i % 24:02d}:59:00+00:00", "mean": 1.0, "nota": "x" * 280}
                  for i in range(1000)] for k in list(estados)[:10]}
    inicio = time.process_time()
    final_s, recortado_s, _ = _truncate_stats_to_bytes(puntos, TOPE)
    assert time.process_time() - inicio < 5
    assert recortado_s is True and all(final_s.values())


# ── Spec 007: la vista previa recortada sigue diciendo cómo confirmar ──
#
# Desde 1.1.2 las cinco tools con documento grande añaden `confirm_with`,
# `omit_on_confirm` y `confirm_hint`. Si el guardián los resumiera, el agente
# no sabría que puede confirmar sin reenviar el documento y volvería a llegar
# tarde. Control negativo comprobado: sin los tres campos en `intocables` de
# `_recortar_vista_previa` caen los dos tests de Lovelace.

_PISTAS = {
    "confirm_with": ["confirmation_token", "url_path"],
    "omit_on_confirm": ["config"],
    "confirm_hint": "To confirm, call ha_save_lovelace_dashboard again with only "
                    "confirmation_token, url_path. config can be omitted: the "
                    "server kept the one from this preview. Any argument you do "
                    "send must be identical to the preview.",
}


def test_vista_previa_recortada_conserva_como_confirmar() -> None:
    payload = {
        "confirmation_token": "tok", "expires_in_seconds": 60,
        "preview": {"url_path": "panel-ficticio", "diff": {"x": "y" * 50_000}},
        **_PISTAS,
    }
    out = recortar_a_bytes(payload, 16_384)
    assert tam_json(out) <= 16_384
    assert out["preview_truncated"] is True
    assert out["confirmation_token"] == "tok"
    for clave, valor in _PISTAS.items():
        assert out[clave] == valor, clave
    # Ni con un tope absurdo se pierden.
    minimo = recortar_a_bytes(payload, 200)
    assert minimo["confirmation_token"] == "tok"
    for clave, valor in _PISTAS.items():
        assert minimo[clave] == valor, clave


async def test_ha_save_lovelace_dashboard_por_encima_del_tope_conserva_las_pistas() -> None:
    vistas = [{"title": f"Vista ficticia {i}", "cards": []} for i in range(5)]
    config = {"views": vistas}
    async with ClientSession() as session:
        ha_client = _cliente_ws(session, config)
        _, entera = await _llamar(
            ha_client, "ha_save_lovelace_dashboard", {"url_path": None, "config": config}, TOPE,
        )
        assert "preview_truncated" not in entera
        tope = tam_json(entera) - 1
        result, payload = await _llamar(
            ha_client, "ha_save_lovelace_dashboard", {"url_path": None, "config": config}, tope,
        )
    assert result.is_error is False, payload
    assert payload["preview_truncated"] is True
    assert payload["confirmation_token"]
    assert entera["confirm_with"] == _PISTAS["confirm_with"]
    assert entera["omit_on_confirm"] == _PISTAS["omit_on_confirm"]
    for clave in _PISTAS:
        assert payload[clave] == entera[clave], clave


async def test_fs_delete_file_no_trae_pistas_de_omision(tmp_path) -> None:
    """Las tools sin omitibles responden como en 1.1.1."""
    import hermes.fs as fs_module

    (tmp_path / "ficticio.yaml").write_text("k: v\n", encoding="utf-8")
    with patch.object(fs_module, "CONFIG_BASE", tmp_path.resolve()):
        async with ClientSession() as session:
            ha_client = make_ready_client(session, {})
            result, payload = await _llamar(
                ha_client, "fs_delete_file", {"path": "ficticio.yaml"}, TOPE,
            )
    assert result.is_error is False, payload
    assert payload["confirmation_token"]
    for clave in _PISTAS:
        assert clave not in payload, clave
