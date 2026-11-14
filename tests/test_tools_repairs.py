"""Tests de las tools de Repairs (`ha_list_repairs`, `ha_ignore_repair`).

Home Assistant se simula con un `ws_send` falso que registra cada comando. Los
datos son ficticios: dominios e ids inventados y secretos centinela que no
deben aparecer en ninguna respuesta.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from aiohttp import ClientSession

import hermes.tools.repairs as repairs_mod
from hermes.ha import HAConnectionError
from tests._ha_fixture import make_ready_client


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


_CAMPOS_CONTRATO = {
    "domain", "issue_id", "issue_domain", "severity", "is_fixable",
    "breaks_in_ha_version", "created", "ignored", "dismissed_version",
    "translation_key", "translation_placeholders", "learn_more_url",
}


def _issue(issue_id: str, severity: str, *, domain: str = "demo_integ",
           ignored: bool = False, **extra: Any) -> dict[str, Any]:
    base = {
        "breaks_in_ha_version": None,
        "created": "2026-11-01T10:00:00+00:00",
        "dismissed_version": "2026.11.0" if ignored else None,
        "domain": domain,
        "ignored": ignored,
        "is_fixable": False,
        "issue_domain": domain,
        "issue_id": issue_id,
        "learn_more_url": "https://example.invalid/help",
        "severity": severity,
        "translation_key": f"key_{issue_id}",
        "translation_placeholders": None,
        # Datos internos que HA no expone en la lista, pero si algún día lo
        # hiciera no deben salir.
        "issue_data": {"internal": "x"},
    }
    base.update(extra)
    return base


class _FakeHA:
    """Simula `repairs/list_issues` y `repairs/ignore_issue`."""

    def __init__(self, issues: list[dict[str, Any]]) -> None:
        self.issues = issues
        self.sent: list[dict[str, Any]] = []
        self.fail_list = False
        # Código WS con el que falla `repairs/ignore_issue` (None = no falla).
        self.ignore_error_code: str | None = None

    async def ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.sent.append(payload)
        if payload["type"] == "repairs/list_issues":
            if self.fail_list:
                raise HAConnectionError("offline")
            return {"issues": self.issues}
        if payload["type"] == "repairs/ignore_issue":
            if self.ignore_error_code is not None:
                raise HAConnectionError("Issue not found",
                                        code=self.ignore_error_code)
            return None
        raise AssertionError(f"comando inesperado: {payload}")

    def tipos(self) -> list[str]:
        return [p["type"] for p in self.sent]


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()

    def _montar(self, issues: list[dict[str, Any]]) -> tuple[DummyMCP, _FakeHA]:
        client = make_ready_client(self.session, {})
        fake = _FakeHA(issues)
        client.ws_send = fake.ws_send  # type: ignore[method-assign]
        mcp = DummyMCP()
        repairs_mod.register(mcp, client)
        return mcp, fake


# ── ha_list_repairs ──────────────────────────────────────────────────────────


class TestListRepairs(_Base):
    def _tres(self) -> list[dict[str, Any]]:
        return [
            _issue("aviso", "warning", domain="otra_integ"),
            _issue("oculto", "critical", ignored=True),
            _issue("roto", "error", breaks_in_ha_version="2027.3.0"),
        ]

    async def test_por_defecto_oculta_los_ignorados(self) -> None:
        mcp, fake = self._montar(self._tres())
        res = json.loads(await mcp.tools["ha_list_repairs"]())
        self.assertEqual(res["count"], 2)
        self.assertEqual([i["issue_id"] for i in res["issues"]], ["roto", "aviso"])
        self.assertEqual(fake.tipos(), ["repairs/list_issues"])

    async def test_include_ignored_devuelve_los_tres_ordenados(self) -> None:
        mcp, _ = self._montar(self._tres())
        res = json.loads(await mcp.tools["ha_list_repairs"](include_ignored=True))
        self.assertEqual(res["count"], 3)
        self.assertEqual(
            [i["issue_id"] for i in res["issues"]], ["oculto", "roto", "aviso"]
        )
        oculto = res["issues"][0]
        self.assertTrue(oculto["ignored"])
        self.assertEqual(oculto["dismissed_version"], "2026.11.0")

    async def test_filtro_domain(self) -> None:
        mcp, _ = self._montar(self._tres())
        res = json.loads(await mcp.tools["ha_list_repairs"](domain="otra_integ"))
        self.assertEqual([i["issue_id"] for i in res["issues"]], ["aviso"])

    async def test_filtro_severity(self) -> None:
        mcp, _ = self._montar(self._tres())
        res = json.loads(
            await mcp.tools["ha_list_repairs"](severity="error", include_ignored=True)
        )
        self.assertEqual([i["issue_id"] for i in res["issues"]], ["roto"])

    async def test_severity_invalida(self) -> None:
        mcp, fake = self._montar(self._tres())
        res = json.loads(await mcp.tools["ha_list_repairs"](severity="info"))
        self.assertEqual(res["error"], "invalid_argument")
        self.assertEqual(res["field"], "severity")
        self.assertEqual(fake.sent, [])

    async def test_placeholders_redactados(self) -> None:
        issue = _issue(
            "secreto", "warning",
            translation_placeholders={
                "url": "https://user:SENTINEL-PASS@example.invalid",
                "token": "SENTINEL-TOKEN",
                "name": "Dispositivo demo",
            },
        )
        mcp, _ = self._montar([issue])
        raw = await mcp.tools["ha_list_repairs"]()
        self.assertNotIn("SENTINEL-", raw)
        res = json.loads(raw)
        ph = res["issues"][0]["translation_placeholders"]
        self.assertEqual(ph["name"], "Dispositivo demo")
        self.assertIn("example.invalid", ph["url"])

    async def test_solo_campos_del_contrato(self) -> None:
        mcp, _ = self._montar(self._tres())
        res = json.loads(await mcp.tools["ha_list_repairs"](include_ignored=True))
        for issue in res["issues"]:
            self.assertEqual(set(issue), _CAMPOS_CONTRATO)
        self.assertEqual(set(res), {"count", "issues"})

    async def test_error_de_ha(self) -> None:
        mcp, fake = self._montar(self._tres())
        fake.fail_list = True
        res = json.loads(await mcp.tools["ha_list_repairs"]())
        self.assertIn("error", res)


# ── ha_ignore_repair ─────────────────────────────────────────────────────────


class TestIgnoreRepair(_Base):
    def _issues(self) -> list[dict[str, Any]]:
        return [
            _issue("activo", "warning", breaks_in_ha_version="2027.3.0"),
            _issue("ya_oculto", "error", ignored=True),
            _issue("otro", "warning"),
        ]

    async def test_sin_token_da_preview_sin_enviar(self) -> None:
        mcp, fake = self._montar(self._issues())
        res = json.loads(
            await mcp.tools["ha_ignore_repair"]("demo_integ", "activo")
        )
        self.assertIn("confirmation_token", res)
        prev = res["preview"]
        self.assertEqual(prev["action"], "ignore")
        self.assertEqual(prev["severity"], "warning")
        self.assertEqual(prev["breaks_in_ha_version"], "2027.3.0")
        self.assertIn("Reversible", prev["effect"])
        self.assertNotIn("repairs/ignore_issue", fake.tipos())

    async def test_con_token_envia_ignore(self) -> None:
        mcp, fake = self._montar(self._issues())
        tool = mcp.tools["ha_ignore_repair"]
        token = json.loads(await tool("demo_integ", "activo"))["confirmation_token"]
        res = json.loads(await tool("demo_integ", "activo", confirmation_token=token))
        self.assertEqual(res, {"result": "ok", "ignored": True})
        enviados = [p for p in fake.sent if p["type"] == "repairs/ignore_issue"]
        self.assertEqual(
            enviados,
            [{"type": "repairs/ignore_issue", "domain": "demo_integ",
              "issue_id": "activo", "ignore": True}],
        )

    async def test_ya_ignorado_es_unchanged_sin_token(self) -> None:
        mcp, fake = self._montar(self._issues())
        res = json.loads(
            await mcp.tools["ha_ignore_repair"]("demo_integ", "ya_oculto")
        )
        self.assertEqual(res, {"result": "unchanged", "ignored": True})
        self.assertNotIn("confirmation_token", res)
        self.assertNotIn("repairs/ignore_issue", fake.tipos())

    async def test_unignore_sobre_ignorado(self) -> None:
        mcp, fake = self._montar(self._issues())
        tool = mcp.tools["ha_ignore_repair"]
        res = json.loads(await tool("demo_integ", "ya_oculto", ignore=False))
        self.assertEqual(res["preview"]["action"], "unignore")
        token = res["confirmation_token"]
        res2 = json.loads(
            await tool("demo_integ", "ya_oculto", ignore=False,
                       confirmation_token=token)
        )
        self.assertEqual(res2, {"result": "ok", "ignored": False})
        self.assertEqual(fake.sent[-1]["ignore"], False)

    async def test_inexistente(self) -> None:
        mcp, fake = self._montar(self._issues())
        res = json.loads(
            await mcp.tools["ha_ignore_repair"]("demo_integ", "no_existe")
        )
        self.assertEqual(res["error"], "not_found")
        self.assertNotIn("confirmation_token", res)

    async def test_token_de_otro_issue_rechazado(self) -> None:
        mcp, fake = self._montar(self._issues())
        tool = mcp.tools["ha_ignore_repair"]
        token = json.loads(await tool("demo_integ", "activo"))["confirmation_token"]
        res = json.loads(await tool("demo_integ", "otro", confirmation_token=token))
        self.assertIn("error", res)
        self.assertNotIn("repairs/ignore_issue", fake.tipos())

    async def test_lectura_fallida_es_fail_closed(self) -> None:
        mcp, fake = self._montar(self._issues())
        fake.fail_list = True
        res = json.loads(
            await mcp.tools["ha_ignore_repair"]("demo_integ", "activo")
        )
        self.assertIn("error", res)
        self.assertNotIn("confirmation_token", res)

    async def _desaparece_antes_de_confirmar(self, codigo: str) -> dict[str, Any]:
        mcp, fake = self._montar(self._issues())
        tool = mcp.tools["ha_ignore_repair"]
        token = json.loads(await tool("demo_integ", "activo"))["confirmation_token"]
        # HA resuelve el issue solo entre la preview y la confirmación.
        fake.ignore_error_code = codigo
        return json.loads(await tool("demo_integ", "activo",
                                     confirmation_token=token))

    async def test_desaparecido_al_confirmar_es_not_found(self) -> None:
        # HA responde `unknown_issue` (repairs/websocket_api.py), no `not_found`.
        res = await self._desaparece_antes_de_confirmar("unknown_issue")
        self.assertEqual(
            res, {"error": "not_found", "domain": "demo_integ", "issue_id": "activo"}
        )

    async def test_otro_codigo_al_confirmar_no_es_not_found(self) -> None:
        # Control negativo: un fallo distinto no se disfraza de not_found.
        res = await self._desaparece_antes_de_confirmar("home_assistant_error")
        self.assertNotEqual(res.get("error"), "not_found")


if __name__ == "__main__":
    unittest.main()
