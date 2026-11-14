"""Tests de la resolución del Supervisor (spec 005, US6).

`sv_get_resolution` lee; `sv_dismiss_resolution_*` descartan con token. Lo que
NUNCA puede hacer Hermes es aplicar una sugerencia del Supervisor
(`POST /resolution/suggestion/{uuid}`): algunas borran backups, reinician el
host o resetean datos (FR-024).
"""

from __future__ import annotations

import ast
import json
import pathlib
import unittest
from typing import Any

from hermes.ha import HAConnectionError
from hermes.tools import resolution as resolution_mod

_TOOLS_DIR = (pathlib.Path(__file__).resolve().parents[1]
              / "hermes" / "src" / "hermes" / "tools")

_ISSUE = "0123456789abcdef0123456789abcdef"
_SUG = "fedcba9876543210fedcba9876543210"


class _MCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, *a: Any, **k: Any):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def _info() -> dict[str, Any]:
    return {
        "unsupported": ["os"],
        "unhealthy": ["docker"],
        "issues": [{"uuid": _ISSUE, "type": "free_space", "context": "system",
                    "reference": None, "extra_field": "SENTINEL-EXTRA"}],
        "suggestions": [{"uuid": _SUG, "type": "clear_full_backup", "context": "system",
                         "reference": None, "auto": False}],
        "checks": [{"slug": "free_space", "enabled": True, "other": 1}],
    }


class _Supervisor:
    def __init__(self, info: Any = None, fallar_delete: Exception | None = None) -> None:
        self.info = info if info is not None else _info()
        self.fallar_delete = fallar_delete
        self.peticiones: list[tuple[str, str]] = []

    async def sv_request(self, method, path, json_body=None, params=None,
                         timeout_seconds=60.0):
        self.peticiones.append((method, path))
        if method == "GET" and path == "/resolution/info":
            if isinstance(self.info, Exception):
                raise self.info
            return self.info
        if method == "DELETE":
            if self.fallar_delete:
                raise self.fallar_delete
            return {}
        raise AssertionError(f"petición inesperada {method} {path}")


class _Base(unittest.IsolatedAsyncioTestCase):
    def _tools(self, sv: _Supervisor) -> dict[str, Any]:
        mcp = _MCP()
        resolution_mod.register(mcp, sv)
        return mcp.tools


class TestGetResolution(_Base):
    async def test_returns_the_five_lists_with_contract_fields(self) -> None:
        sv = _Supervisor()
        r = await self._tools(sv)["sv_get_resolution"]()
        self.assertEqual(r["unsupported"], ["os"])
        self.assertEqual(r["unhealthy"], ["docker"])
        self.assertEqual(r["issues"], [{"uuid": _ISSUE, "type": "free_space",
                                        "context": "system", "reference": None,
                                        "reference_extra": None}])
        self.assertEqual(r["suggestions"], [{"uuid": _SUG, "type": "clear_full_backup",
                                             "context": "system", "reference": None,
                                             "reference_extra": None, "auto": False}])
        self.assertEqual(r["checks"], [{"slug": "free_space", "enabled": True}])
        self.assertNotIn("SENTINEL-EXTRA", json.dumps(r))
        self.assertEqual(sv.peticiones, [("GET", "/resolution/info")])

    async def test_sensitive_reference_is_redacted(self) -> None:
        info = _info()
        info["issues"][0]["reference"] = "password=SENTINEL-P"
        info["issues"][0]["reference_extra"] = {"api_token": "SENTINEL-T", "addon": "x"}
        info["suggestions"][0]["reference"] = "token: SENTINEL-S"
        r = await self._tools(_Supervisor(info))["sv_get_resolution"]()
        texto = json.dumps(r)
        for s in ("SENTINEL-P", "SENTINEL-T", "SENTINEL-S"):
            self.assertNotIn(s, texto)
        self.assertEqual(r["issues"][0]["reference_extra"]["addon"], "x")

    async def test_supervisor_error(self) -> None:
        r = await self._tools(_Supervisor(HAConnectionError("boom", status=500)))[
            "sv_get_resolution"]()
        self.assertIn("error", r)

    async def test_unexpected_shape_is_error(self) -> None:
        r = await self._tools(_Supervisor(["x"]))["sv_get_resolution"]()
        self.assertIn("error", r)


class TestDismiss(_Base):
    casos = (("sv_dismiss_resolution_issue", "issue_uuid", _ISSUE, "issue"),
             ("sv_dismiss_resolution_suggestion", "suggestion_uuid", _SUG, "suggestion"))

    async def test_invalid_uuid_no_request(self) -> None:
        for tool, campo, _uuid, _ruta in self.casos:
            sv = _Supervisor()
            r = await self._tools(sv)[tool](**{campo: "../x"})
            self.assertEqual(r["error"], "invalid_identifier", tool)
            self.assertEqual(sv.peticiones, [])

    async def test_unknown_uuid_not_found_without_token(self) -> None:
        for tool, campo, _uuid, _ruta in self.casos:
            sv = _Supervisor()
            r = await self._tools(sv)[tool](**{campo: "a" * 32})
            self.assertEqual(r["error"], "not_found", tool)
            self.assertNotIn("confirmation_token", r)

    async def test_issue_uuid_is_not_found_as_suggestion(self) -> None:
        sv = _Supervisor()
        r = await self._tools(sv)["sv_dismiss_resolution_suggestion"](suggestion_uuid=_ISSUE)
        self.assertEqual(r["error"], "not_found")

    async def test_listing_failure_gives_no_token(self) -> None:
        sv = _Supervisor(HAConnectionError("boom", status=500))
        r = await self._tools(sv)["sv_dismiss_resolution_issue"](issue_uuid=_ISSUE)
        self.assertIn("error", r)
        self.assertNotIn("confirmation_token", r)

    async def test_issue_preview(self) -> None:
        r = await self._tools(_Supervisor())["sv_dismiss_resolution_issue"](issue_uuid=_ISSUE)
        p = r["preview"]
        self.assertEqual((p["issue_uuid"], p["type"], p["context"], p["reference"]),
                         (_ISSUE, "free_space", "system", None))
        self.assertEqual(p["action"], "dismiss")
        self.assertIn("come back", p["effect"])

    async def test_suggestion_preview_says_not_applied(self) -> None:
        r = await self._tools(_Supervisor())["sv_dismiss_resolution_suggestion"](
            suggestion_uuid=_SUG)
        p = r["preview"]
        self.assertEqual((p["suggestion_uuid"], p["type"], p["context"]),
                         (_SUG, "clear_full_backup", "system"))
        self.assertIn("without applying it", p["effect"])
        self.assertIn("never applies", p["effect"])

    async def test_with_token_exactly_one_delete_and_no_post(self) -> None:
        for tool, campo, uuid, ruta in self.casos:
            sv = _Supervisor()
            tools = self._tools(sv)
            primero = await tools[tool](**{campo: uuid})
            r = await tools[tool](**{campo: uuid,
                                     "confirmation_token": primero["confirmation_token"]})
            self.assertEqual(r, {"result": "ok"}, tool)
            borrados = [p for m, p in sv.peticiones if m == "DELETE"]
            self.assertEqual(borrados, [f"/resolution/{ruta}/{uuid}"])
            self.assertFalse([p for m, p in sv.peticiones if m == "POST"])

    async def test_token_for_other_uuid_is_rejected(self) -> None:
        sv = _Supervisor()
        tools = self._tools(sv)
        primero = await tools["sv_dismiss_resolution_issue"](issue_uuid=_ISSUE)
        r = await tools["sv_dismiss_resolution_issue"](
            issue_uuid="b" * 32, confirmation_token=primero["confirmation_token"])
        self.assertIn("error", r)
        self.assertFalse([p for m, p in sv.peticiones if m == "DELETE"])

    async def test_delete_404_is_error_and_token_spent(self) -> None:
        sv = _Supervisor(fallar_delete=HAConnectionError("gone", status=404))
        tools = self._tools(sv)
        primero = await tools["sv_dismiss_resolution_issue"](issue_uuid=_ISSUE)
        token = primero["confirmation_token"]
        r = await tools["sv_dismiss_resolution_issue"](issue_uuid=_ISSUE,
                                                       confirmation_token=token)
        self.assertIn("error", r)
        otra = await tools["sv_dismiss_resolution_issue"](issue_uuid=_ISSUE,
                                                          confirmation_token=token)
        self.assertIn("error", otra)
        self.assertEqual(len([p for m, p in sv.peticiones if m == "DELETE"]), 1)


def _textos(nodo: ast.AST) -> str:
    """Parte literal de un str o un f-string."""
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    if isinstance(nodo, ast.JoinedStr):
        return "".join(v.value for v in nodo.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return ""


def posts_a_sugerencias(directorio: pathlib.Path) -> list[str]:
    """Llamadas `sv_request("POST", ".../resolution/suggestion/...")` en el código."""
    hallazgos = []
    for ruta in sorted(directorio.glob("*.py")):
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if not (isinstance(nodo, ast.Call)
                    and getattr(nodo.func, "attr", getattr(nodo.func, "id", None))
                    == "sv_request"):
                continue
            args = list(nodo.args)
            metodo = _textos(args[0]) if args else ""
            ruta_sv = _textos(args[1]) if len(args) > 1 else ""
            for kw in nodo.keywords:
                if kw.arg == "method":
                    metodo = _textos(kw.value)
                if kw.arg == "sv_path":
                    ruta_sv = _textos(kw.value)
            if metodo.upper() == "POST" and "/resolution/suggestion/" in ruta_sv:
                hallazgos.append(f"{ruta.name}:{nodo.lineno}")
    return hallazgos


class TestNuncaAplicaSugerencias(unittest.TestCase):
    """FR-024: ninguna tool aplica sugerencias del Supervisor."""

    def test_no_post_to_resolution_suggestion(self) -> None:
        self.assertEqual(posts_a_sugerencias(_TOOLS_DIR), [])

    def test_guard_detects_a_post(self) -> None:
        # El propio detector se prueba con un caso positivo: un test de guarda
        # que no encuentra nada nunca no protege nada.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "x.py"
            p.write_text('async def f(c, u):\n'
                         '    await c.sv_request("POST", f"/resolution/suggestion/{u}")\n',
                         encoding="utf-8")
            self.assertEqual(posts_a_sugerencias(pathlib.Path(tmp)), ["x.py:2"])


if __name__ == "__main__":
    unittest.main()
