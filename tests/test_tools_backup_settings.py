"""Ajustes de backup del Supervisor (spec 019, tramo 2; CAP-083).

`sv_get_backup_settings`, `sv_set_backup_settings` y `sv_reload_backups`
contra el Supervisor simulado de `tests/fixtures/supervisor_montajes.py`
(forma del Supervisor 2026.11.0, datos ficticios).

Lo que se vigila, además de cada petición exacta:

- los ajustes juntan `days_until_stale`, el montaje por defecto y los
  montajes de uso `backup`, sin repetir la lista de backups (FR-011);
- `days_until_stale` es un entero ≥ 1 y no booleano; lo inválido no llega al
  Supervisor (FR-012);
- releer backups devuelve cuántos ve el Supervisor después (FR-013);
- los errores del Supervisor vuelven redactados y una forma inesperada es un
  error, nunca un valor inventado (FR-010).

Controles negativos del tramo 2 (T030), con recuentos, en el mensaje del
commit que añade este fichero.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from structlog.testing import capture_logs

from hermes.ha import HAConnectionError
from hermes.tools.backup_settings import register
from tests.fixtures.supervisor_montajes import CLAVE, USUARIO, SupervisorDeMontajes


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _texto(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, default=str)


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sv = SupervisorDeMontajes()
        self.mcp = DummyMCP()
        register(self.mcp, self.sv)
        self.t = self.mcp.tools

    def _rutas(self) -> list[tuple[str, str]]:
        return [(c["metodo"], c["ruta"]) for c in self.sv.llamadas]


# ── T021: leer los ajustes (FR-011) ───────────────────────────────────────────


class TestAjustes(_Base):
    async def test_ajustes_sin_la_lista_de_backups(self) -> None:
        self.sv.days_until_stale = 12
        self.sv.estados["nas_backups"] = "failed"
        with capture_logs() as eventos:
            r = await self.t["sv_get_backup_settings"]()
        self.assertEqual(r, {
            "days_until_stale": 12,
            "default_backup_mount": "nas_backups",
            # Solo los de uso `backup`: `nas_media` y `usb_share` no salen.
            "backup_mounts": [{"name": "nas_backups", "state": "failed"}],
        })
        self.assertEqual(sorted(self._rutas()),
                         [("GET", "/backups/info"), ("GET", "/mounts")])
        self.assertEqual([e["event"] for e in eventos], ["sv_get_backup_settings_ok"])

    async def test_sin_montaje_por_defecto_ni_de_backup(self) -> None:
        self.sv.montajes = [m for m in self.sv.montajes if m["usage"] != "backup"]
        self.sv.por_defecto = None
        r = await self.t["sv_get_backup_settings"]()
        self.assertEqual((r["default_backup_mount"], r["backup_mounts"]), (None, []))

    async def test_forma_inesperada_en_cualquiera_de_las_dos(self) -> None:
        malas = {
            ("GET", "/backups/info"): [{"backups": []}, {"days_until_stale": "30"},
                                       {"days_until_stale": True}, []],
            ("GET", "/mounts"): [{"default_backup_mount": None}, [],
                                 {"mounts": "x", "default_backup_mount": None}],
        }
        for clave, formas in malas.items():
            for forma in formas:
                with self.subTest(clave=clave, forma=forma):
                    self.sv.formas = {clave: forma}
                    r = await self.t["sv_get_backup_settings"]()
                    self.assertEqual(list(r), ["error"])
                    self.assertIn("unexpected response shape", r["error"])

    async def test_error_del_supervisor_redactado(self) -> None:
        self.sv.errores[("GET", "/mounts")] = HAConnectionError(
            f"Supervisor error: mount nas_backups user {USUARIO} password {CLAVE}")
        r = await self.t["sv_get_backup_settings"]()
        self.assertNotIn(CLAVE, r["error"])
        self.assertNotIn(USUARIO, r["error"])


# ── T022: days_until_stale (FR-012, FR-020) ───────────────────────────────────


class TestDiasHastaViejo(_Base):
    async def test_cambia_y_devuelve_el_anterior(self) -> None:
        with capture_logs() as eventos:
            r = await self.t["sv_set_backup_settings"](days_until_stale=7)
        self.assertEqual(r, {"result": "ok", "days_until_stale": 7, "previous": 30})
        self.assertEqual(self.sv.escrituras, [{
            "metodo": "POST", "ruta": "/backups/options",
            "json": {"days_until_stale": 7}}])
        self.assertEqual(self.sv.days_until_stale, 7)
        ok = [e for e in eventos if e["event"] == "sv_set_backup_settings_ok"]
        self.assertEqual(len(ok), 1)
        self.assertEqual((ok[0]["days_until_stale"], ok[0]["previous"]), (7, 30))

    async def test_valores_invalidos_sin_llamada(self) -> None:
        for valor in (0, -1, True, False, 7.5, "7", None):
            with self.subTest(valor=valor):
                self.sv.llamadas.clear()
                r = await self.t["sv_set_backup_settings"](days_until_stale=valor)
                self.assertEqual(r["error"], "invalid_argument")
                self.assertIn("days_until_stale", r["detail"])
                self.assertEqual(self.sv.llamadas, [])

    async def test_tope_superior_sin_llamada(self) -> None:
        """T037: por encima de 3650 días, error claro y sin llamar al
        Supervisor (con N ≥ ~740 000 su `is_current` lanza `OverflowError`
        en cada comprobación y el aviso desaparece sin decirlo). El tope
        exacto se acepta, y la descripción de la tool lo dice.

        Control negativo comprobado: con `_valido` sin el tope (`dias >= 1`)
        caen los 3 subtests de valores por encima; restaurado, verde."""
        for valor in (3651, 1_000_000, 10**12):
            with self.subTest(valor=valor):
                self.sv.llamadas.clear()
                r = await self.t["sv_set_backup_settings"](days_until_stale=valor)
                self.assertEqual(r["error"], "invalid_argument")
                self.assertIn("3650", r["detail"])
                self.assertEqual(self.sv.llamadas, [])
        r = await self.t["sv_set_backup_settings"](days_until_stale=3650)
        self.assertEqual(r["result"], "ok")
        self.assertEqual(self.sv.days_until_stale, 3650)
        self.assertIn("3650", self.t["sv_set_backup_settings"].__doc__)

    async def test_error_del_supervisor_redactado(self) -> None:
        self.sv.errores[("POST", "/backups/options")] = HAConnectionError(
            "Supervisor error: token=abc123secreto rejected")
        r = await self.t["sv_set_backup_settings"](days_until_stale=7)
        self.assertNotIn("abc123secreto", r["error"])
        self.assertIn("rejected", r["error"])

    async def test_forma_inesperada_al_leer_el_anterior(self) -> None:
        self.sv.formas[("GET", "/backups/info")] = {"backups": []}
        r = await self.t["sv_set_backup_settings"](days_until_stale=7)
        self.assertIn("unexpected response shape", r["error"])
        self.assertEqual(self.sv.escrituras, [])


# ── T023: releer backups (FR-013) ─────────────────────────────────────────────


class TestReleerBackups(_Base):
    async def test_relee_y_cuenta(self) -> None:
        with capture_logs() as eventos:
            r = await self.t["sv_reload_backups"]()
        self.assertEqual(r, {"result": "ok", "backups_count": 30})
        self.assertEqual(self._rutas(), [("POST", "/backups/reload"), ("GET", "/backups")])
        ok = [e for e in eventos if e["event"] == "sv_reload_backups_ok"]
        self.assertEqual(ok[0]["backups_count"], 30)

    async def test_error_redactado(self) -> None:
        self.sv.errores[("POST", "/backups/reload")] = HAConnectionError(
            f"Supervisor error: cannot read nas_backups (username={USUARIO}, "
            f"password={CLAVE})")
        r = await self.t["sv_reload_backups"]()
        self.assertNotIn(CLAVE, r["error"])
        self.assertNotIn(USUARIO, r["error"])
        self.assertIn("cannot read nas_backups", r["error"])
        self.assertEqual(self._rutas(), [("POST", "/backups/reload")])

    async def test_releido_pero_sin_poder_contar(self) -> None:
        self.sv.formas[("GET", "/backups")] = {"nada": []}
        r = await self.t["sv_reload_backups"]()
        self.assertEqual(r["result"], "ok")
        self.assertIsNone(r["backups_count"])
        self.assertIn("sv_list_backups", r["warning"])


if __name__ == "__main__":
    unittest.main()
