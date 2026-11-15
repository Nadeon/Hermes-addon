"""Banco de Core: textos de Repairs y flujos de reparación (spec 016, tramo C).

Contra HA Core 2026.11.1 real, con los dos avisos reparables de la
integración de prueba `banco_flujos`
(`tests/banco/ha_config/custom_components/banco_flujos/`, research R-9):

- `TestTextosDeRepairs` (T042): `ha_list_repairs` trae el título y la
  descripción de `translations/en.json` con los marcadores sustituidos, y
  `ha_get_repair` los datos internos del aviso.
- `TestArreglarUnAviso` (T042): `ha_start_repair_fix` →
  `ha_continue_repair_fix` sin token (el lector ve que el aviso sigue) → con
  el token (el lector ya no lo ve).
- `TestAbortarUnArreglo` (T042): `ha_start_repair_fix` y
  `ha_abort_repair_fix` sobre el segundo aviso; el aviso sigue.

Hermes hace; el lector independiente comprueba en Core. Cada test vuelve a
crear los dos avisos al empezar y al terminar (servicio
`banco_flujos.crear_avisos`), para no depender del orden.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras

pytestmark = pytest.mark.banco

DOMINIO = "banco_flujos"
REPARABLE = "aviso_reparable"
PARA_ABORTAR = "aviso_para_abortar"
_RUTA_FIX = "/api/repairs/issues/fix"


async def _avisos(s: SesionEscrituras) -> dict[str, dict[str, Any]]:
    """Los avisos de `banco_flujos` que ve el lector, por `issue_id`."""
    r = await s.lector.comando({"type": "repairs/list_issues"})
    return {i["issue_id"]: i for i in r["issues"] if i["domain"] == DOMINIO}


async def _preparar_avisos(s: SesionEscrituras) -> None:
    async def crear() -> None:
        await s.lector.comando(
            {"type": "call_service", "domain": DOMINIO, "service": "crear_avisos"}
        )

    await crear()
    # Al terminar, otra vez: el test de entorno del tramo A los espera.
    s.limpiezas.append(crear)
    await s.lector.esperar(
        lambda: _avisos(s),
        lambda a: {REPARABLE, PARA_ABORTAR} <= set(a),
        descripcion="los dos avisos reparables de banco_flujos",
    )


def _abortar_al_final(s: SesionEscrituras, flow_id: str) -> None:
    async def abortar() -> None:
        # Si el test falla antes, que el flujo no quede abierto (404 si ya no está).
        await s.lector.rest("DELETE", f"{_RUTA_FIX}/{flow_id}")

    s.limpiezas.append(abortar)


class TestTextosDeRepairs(BancoEscrituras):
    async def test_titulo_descripcion_y_datos_internos(self) -> None:
        async with self.sesion() as s:
            await _preparar_avisos(s)

            lista = await s.accion("ha_list_repairs", domain=DOMINIO)
            self.assertFalse(lista["translations_unavailable"], lista)
            self.assertEqual(lista["language"], "en")
            aviso = next(i for i in lista["issues"] if i["issue_id"] == REPARABLE)
            self.assertEqual(aviso["title"], "Test bench: value 42 to confirm")
            self.assertEqual(aviso["description"], "The test value 42 must be confirmed.")
            self.assertTrue(aviso["is_fixable"])

            detalle = await s.accion("ha_get_repair", domain=DOMINIO, issue_id=REPARABLE)
            self.assertEqual(detalle["issue_data"], {"origen": "banco"})
            self.assertFalse(detalle["issue_data_truncated"])
            self.assertEqual(detalle["issue"]["title"], aviso["title"])


class TestArreglarUnAviso(BancoEscrituras):
    async def test_arreglo_con_token(self) -> None:
        async with self.sesion() as s:
            await _preparar_avisos(s)

            inicio = await s.accion("ha_start_repair_fix", domain=DOMINIO, issue_id=REPARABLE)
            self.assertEqual((inicio["type"], inicio["step_id"]), ("form", "confirm"), inicio)
            self.assertFalse(inicio["finished_on_start"])
            self.assertEqual(
                inicio["step_text"],
                {"title": "Confirm the test value",
                 "description": "Submit to mark the test value as confirmed.",
                 "source": "fix_flow"},
            )
            flow_id = inicio["flow_id"]
            _abortar_al_final(s, flow_id)

            # Vista previa: no envía nada; el aviso sigue y el flujo, en su paso.
            tool = "ha_continue_repair_fix"
            args = {"domain": DOMINIO, "issue_id": REPARABLE, "flow_id": flow_id,
                    "user_input": {"nota": "banco"}}
            vista = await s.vista(tool, **args)
            p = vista["preview"]
            self.assertEqual((p["step_id"], p["issue"]["title"]),
                             ("confirm", "Test bench: value 42 to confirm"))
            self.assertIn(REPARABLE, await _avisos(s))
            estado, paso = await s.lector.rest("GET", f"{_RUTA_FIX}/{flow_id}")
            self.assertEqual((estado, paso.get("step_id")), (200, "confirm"), paso)

            # Con el token: HA termina el flujo y borra el aviso.
            hecho = await s.confirmar(tool, vista, **args)
            self.assertEqual((hecho["type"], hecho["status"]), ("create_entry", "ok"), hecho)
            self.assertIs(hecho["issue_still_present"], False)
            await s.lector.esperar(
                lambda: _avisos(s),
                lambda a: REPARABLE not in a,
                descripcion=f"aviso {REPARABLE} arreglado y retirado",
            )


class TestAbortarUnArreglo(BancoEscrituras):
    async def test_abrir_y_abortar(self) -> None:
        async with self.sesion() as s:
            await _preparar_avisos(s)

            inicio = await s.accion("ha_start_repair_fix", domain=DOMINIO, issue_id=PARA_ABORTAR)
            self.assertEqual(inicio["step_text"]["title"], "Review the test value")
            flow_id = inicio["flow_id"]
            _abortar_al_final(s, flow_id)

            self.assertEqual(await s.accion("ha_abort_repair_fix", flow_id=flow_id),
                             {"result": "ok"})
            estado, _ = await s.lector.rest("GET", f"{_RUTA_FIX}/{flow_id}")
            self.assertEqual(estado, 404)
            self.assertIn(PARA_ABORTAR, await _avisos(s))
