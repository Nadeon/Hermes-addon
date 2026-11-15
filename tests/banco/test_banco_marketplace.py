"""Banco de Core: escritura en el Marketplace (spec 026, tramo 1, T014).

Contra HA Core 2026.11.1 real, con el lector independiente leyendo cada
efecto directamente en Core por su propia WebSocket:

- **Estado del Marketplace del banco**: el Marketplace es una integración de
  Core que se carga siempre (`DEFAULT_INTEGRATIONS`), pero el banco no tiene
  internet y no descarga el catálogo. El lector comprueba que su lista de
  repositorios está vacía (o que la entrada no cargó): es el motivo de
  `NO_EJECUTABLES_026` (ignorar, quitar y refrescar no tienen sobre qué
  actuar).
- **Reconocer un aviso crítico**: `ha_config/.storage/marketplace.critical`
  siembra `ejemplo/tarjeta-critica` sin reconocer. El lector lo ve sin
  reconocer; la vista previa de `ha_marketplace_acknowledge_critical` no
  cambia nada; con el token, el lector ve `acknowledged: true` y, si el aviso
  `critical_repository_ejemplo/tarjeta-critica` estaba en Repairs, que ya no
  está. Una segunda vista previa responde `already_acknowledged`, sin token.
- **Contrato de las cargas**: el lector envía a HA la carga EXACTA que
  construye Hermes (`carga_*` de `tools/_marketplace_write.py`) para cada
  comando de escritura del tramo, con un repositorio inexistente. HA tiene
  que aceptarla (un error del manejador: `repository_not_found` o
  `not_loaded`), nunca `invalid_format` ni `unknown_command`: así una clave
  mal escrita se ve contra HA real y no solo contra el simulador.
  `critical/acknowledge` responde con éxito y la lista sin cambios.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from hermes.tools import _marketplace_write as mw
from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras
from tests.banco.lector import ErrorCore

pytestmark = pytest.mark.banco

_SEMBRADO = "ejemplo/tarjeta-critica"
_AVISO_REPAIRS = f"critical_repository_{_SEMBRADO}"
# Errores del manejador que prueban que HA aceptó la forma de la carga.
_DEL_MANEJADOR = {"repository_not_found", "not_loaded"}
_DE_FORMA = {"invalid_format", "unknown_command"}


async def _rechazo(s: SesionEscrituras, tool: str, **args: Any) -> dict[str, Any]:
    """Llama a una tool que DEBE rechazar y devuelve su `{"error": …}`
    (mismo patrón que test_banco_blueprints.py)."""
    resultado = await s.cliente.call_tool(tool, args)
    assert getattr(resultado, "is_error", False), f"{tool}: se esperaba un rechazo"
    return json.loads(resultado.content[0].text)


async def _criticos(s: SesionEscrituras) -> list[dict[str, Any]]:
    return await s.lector.comando({"type": "marketplace/critical/list"})


async def _avisos_del_marketplace(s: SesionEscrituras) -> set[str]:
    datos = await s.lector.comando({"type": "repairs/list_issues"})
    return {i.get("issue_id") for i in datos.get("issues", [])
            if i.get("domain") == "marketplace"}


class TestEstadoDelMarketplace(BancoEscrituras):
    async def test_sin_catalogo(self) -> None:
        async with self.sesion() as s:
            try:
                repos = await s.lector.comando({
                    "type": "marketplace/repositories/list",
                    "categories": sorted(mw._ORDEN_CATEGORIAS),
                })
            except ErrorCore as exc:
                # La entrada no cargó: tampoco hay repositorios.
                self.assertEqual(exc.codigo, "not_loaded", str(exc))
                return
            self.assertEqual(repos, [], "el banco no debería tener catálogo (sin internet)")


class TestReconocerCritico(BancoEscrituras):
    async def test_ciclo_completo(self) -> None:
        async with self.sesion() as s:
            antes = mw.buscar_por_nombre(await _criticos(s), _SEMBRADO)
            self.assertIsNotNone(antes, "la semilla del banco no está en critical/list")
            self.assertIs(antes["acknowledged"], False)
            avisos_antes = await _avisos_del_marketplace(s)

            vista = await s.vista("ha_marketplace_acknowledge_critical", repository=_SEMBRADO)
            self.assertEqual(vista["preview"]["entry"]["repository"], _SEMBRADO)
            self.assertIs(vista["preview"]["reversible"], False)
            # La vista previa no cambia nada.
            self.assertIs(mw.buscar_por_nombre(await _criticos(s), _SEMBRADO)["acknowledged"],
                          False)

            hecho = await s.confirmar("ha_marketplace_acknowledge_critical", vista,
                                      repository=_SEMBRADO)
            self.assertEqual(hecho["result"], "ok")
            self.assertIs(hecho["entry"]["acknowledged"], True)
            # Efecto leído por el lector, directamente en Core.
            self.assertIs(mw.buscar_por_nombre(await _criticos(s), _SEMBRADO)["acknowledged"],
                          True)
            if _AVISO_REPAIRS in avisos_antes:
                self.assertNotIn(_AVISO_REPAIRS, await _avisos_del_marketplace(s))

            otra = await _rechazo(s, "ha_marketplace_acknowledge_critical",
                                  repository=_SEMBRADO)
            self.assertEqual(otra["error"], "already_acknowledged")
            self.assertNotIn("confirmation_token", otra)


class TestContratoDeCargas(BancoEscrituras):
    async def test_ha_acepta_cada_carga(self) -> None:
        inexistente = "999999999"
        casos = {
            "repository/ignore": mw.carga_ignorar(inexistente),
            "repositories/remove": mw.carga_quitar(inexistente),
            "repository/refresh": mw.carga_refrescar(inexistente),
        }
        # Las cuatro del tramo, ni una más ni una menos.
        self.assertEqual(set(casos) | {"critical/acknowledge"}, set(mw._WRITE_SUFFIXES))
        async with self.sesion() as s:
            for sufijo, carga in casos.items():
                with self.subTest(sufijo=sufijo):
                    with self.assertRaises(ErrorCore) as ctx:
                        await s.lector.comando({"type": f"marketplace/{sufijo}", **carga})
                    self.assertNotIn(ctx.exception.codigo, _DE_FORMA, str(ctx.exception))
                    self.assertIn(ctx.exception.codigo, _DEL_MANEJADOR, str(ctx.exception))
            antes = await _criticos(s)
            despues = await s.lector.comando({
                "type": "marketplace/critical/acknowledge",
                **mw.carga_reconocer("ejemplo/inexistente-026"),
            })
            self.assertEqual(despues, antes)
