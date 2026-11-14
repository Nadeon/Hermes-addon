"""Banco de Core: descubiertos, dominios configurables y preferencias (spec 016, tramo A).

Contra HA Core 2026.11.1 real, con la integración de prueba `banco_flujos`
(`tests/banco/ha_config/custom_components/banco_flujos/`, research R-9):

- `TestEntornoBancoFlujos` (T012): el lector ve que la integración cargó, con
  su descubrimiento inicial y sus dos avisos reparables.
- `TestDescubiertos` (T013): `ha_list_discovered_integrations` y
  `ha_ignore_discovery` sobre un descubrimiento propio del test.
- `TestDominiosConfigurables` (T013): `ha_list_config_flow_domains`.
- `TestPreferencias` (T013): `ha_update_config_entry` sobre una entrada que
  crea el lector por el flujo `user`; la vista previa no cambia nada y el
  token sí.

Hermes hace; el lector independiente comprueba en Core y limpia lo suyo. El
tramo B añade aquí las subentries y el reconfigure.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo
from tests.banco.lector import ErrorCore

pytestmark = pytest.mark.banco

DOMINIO = "banco_flujos"
_RUTA_FLUJOS = "/api/config/config_entries/flow"


async def _descubiertos(s: SesionEscrituras) -> list[dict[str, Any]]:
    """Flujos de `banco_flujos` que no abrió un usuario, según el lector."""
    return [
        f
        for f in await s.lector.comando({"type": "config_entries/flow/progress"})
        if f.get("handler") == DOMINIO
    ]


async def _entradas(s: SesionEscrituras) -> list[dict[str, Any]]:
    return await s.lector.comando({"type": "config_entries/get", "domain": DOMINIO})


async def _entrada(s: SesionEscrituras, entry_id: str) -> dict[str, Any] | None:
    try:
        respuesta = await s.lector.comando(
            {"type": "config_entries/get_single", "entry_id": entry_id}
        )
    except ErrorCore as exc:
        if exc.codigo == "not_found":
            return None
        raise
    return respuesta["config_entry"]


def _borrar_entrada(s: SesionEscrituras, entry_id: str) -> None:
    async def borrar() -> None:
        await s.lector.rest("DELETE", f"/api/config/config_entries/entry/{entry_id}")

    s.limpiezas.append(borrar)


async def _descubrimiento_propio(s: SesionEscrituras) -> tuple[str, str]:
    """Abre con el servicio de la integración un descubrimiento con unique_id
    aleatorio y devuelve `(flow_id, nombre)`.

    Un descubrimiento ignorado no vuelve (la integración no redescubre al
    borrar la entrada `ignore`), así que cada test abre el suyo y no depende
    del inicial ni del orden de los tests.
    """
    marca = sufijo()
    unique_id, nombre = f"banco-{marca}", f"Banco {marca}"
    await s.lector.comando(
        {
            "type": "call_service",
            "domain": DOMINIO,
            "service": "descubrir",
            "service_data": {"unique_id": unique_id, "name": nombre},
        }
    )
    flujos = await s.lector.esperar(
        lambda: _descubiertos(s),
        lambda fs: any(f["context"].get("unique_id") == unique_id for f in fs),
        descripcion=f"descubrimiento {unique_id} de banco_flujos en flow/progress",
    )
    flow_id = next(f["flow_id"] for f in flujos if f["context"].get("unique_id") == unique_id)

    async def abortar() -> None:
        # Si el test falla antes de ignorarlo, que no quede abierto.
        await s.lector.rest("DELETE", f"{_RUTA_FLUJOS}/{flow_id}")

    s.limpiezas.append(abortar)
    return flow_id, nombre


class TestEntornoBancoFlujos(BancoEscrituras):
    async def test_banco_flujos_cargada(self) -> None:
        """T012: la integración de prueba cargó con lo que necesitan los tramos."""
        async with self.sesion() as s:
            # El descubrimiento inicial se abre cuando HA termina de arrancar.
            await s.lector.esperar(
                lambda: _descubiertos(s),
                lambda fs: any(
                    f["context"].get("unique_id") == "banco-flujos-inicial"
                    and f["context"].get("source") == "integration_discovery"
                    for f in fs
                ),
                descripcion=(
                    "entorno del banco: descubrimiento inicial de banco_flujos (ver "
                    "tests/banco/ha_config/custom_components/banco_flujos/)"
                ),
            )
            avisos = await s.lector.esperar(
                lambda: s.lector.comando({"type": "repairs/list_issues"}),
                lambda r: {"aviso_reparable", "aviso_para_abortar"}
                <= {i["issue_id"] for i in r["issues"] if i["domain"] == DOMINIO},
                descripcion="entorno del banco: los dos avisos reparables de banco_flujos",
            )
            propios = [i for i in avisos["issues"] if i["domain"] == DOMINIO]
            for aviso in propios:
                self.assertTrue(aviso["is_fixable"], aviso)
                self.assertEqual(aviso["translation_key"], aviso["issue_id"])
            estado, dominios = await s.lector.rest(
                "GET", "/api/config/config_entries/flow_handlers"
            )
            self.assertEqual(estado, 200)
            self.assertIn(DOMINIO, dominios)


class TestDescubiertos(BancoEscrituras):
    async def test_listar_e_ignorar(self) -> None:
        async with self.sesion() as s:
            flow_id, nombre = await _descubrimiento_propio(s)

            listado = await s.accion("ha_list_discovered_integrations", domain=DOMINIO)
            item = next(i for i in listado["items"] if i["flow_id"] == flow_id)
            self.assertEqual(
                (item["domain"], item["source"], item["name"], item["ignorable"]),
                (DOMINIO, "integration_discovery", nombre, True),
            )
            self.assertEqual(item["step_id"], "discovery_confirm")
            # Hermes no devuelve el unique_id ni el contexto entero.
            self.assertNotIn("context", item)

            hecho = await s.accion("ha_ignore_discovery", flow_id=flow_id)
            self.assertEqual((hecho["result"], hecho["title"]), ("ok", nombre))

            # El lector ve la entrada `ignore` con ese título y el
            # descubrimiento ya no está.
            ignoradas = await s.lector.esperar(
                lambda: _entradas(s),
                lambda es: any(e["source"] == "ignore" and e["title"] == nombre for e in es),
                descripcion=f"entrada ignore «{nombre}» de banco_flujos",
            )
            entrada = next(e for e in ignoradas if e["source"] == "ignore" and e["title"] == nombre)
            _borrar_entrada(s, entrada["entry_id"])
            self.assertFalse(any(f["flow_id"] == flow_id for f in await _descubiertos(s)))

            # Deshacer como dice la respuesta: borrar la entrada `ignore`.
            # `banco_flujos` no redescubre (no tiene claves de descubrimiento):
            # no vuelve el flujo, y así se anota.
            estado, _ = await s.lector.rest(
                "DELETE", f"/api/config/config_entries/entry/{entrada['entry_id']}"
            )
            self.assertEqual(estado, 200)
            self.assertIsNone(await _entrada(s, entrada["entry_id"]))


class TestDominiosConfigurables(BancoEscrituras):
    async def test_catalogo_y_helpers(self) -> None:
        async with self.sesion() as s:
            todos = await s.accion("ha_list_config_flow_domains")
            self.assertIn(DOMINIO, todos["items"])
            self.assertEqual(todos["items"], sorted(todos["items"]))
            helpers = await s.accion("ha_list_config_flow_domains", type="helper")
            self.assertIn("template", helpers["items"])
            # `banco_flujos` es de tipo `hub`: no es un helper.
            self.assertNotIn(DOMINIO, helpers["items"])


class TestPreferencias(BancoEscrituras):
    async def _entrada_nueva(self, s: SesionEscrituras) -> str:
        """El lector crea una entrada de `banco_flujos` por el flujo `user`."""
        estado, paso = await s.lector.rest("POST", _RUTA_FLUJOS, {"handler": DOMINIO})
        self.assertEqual((estado, paso["type"], paso["step_id"]), (200, "form", "user"), paso)
        estado, hecho = await s.lector.rest(
            "POST", f"{_RUTA_FLUJOS}/{paso['flow_id']}", {"valor": f"banco-{sufijo()}"}
        )
        self.assertEqual((estado, hecho["type"]), (200, "create_entry"), hecho)
        entry_id = hecho["result"]["entry_id"]
        _borrar_entrada(s, entry_id)
        await s.lector.esperar(
            lambda: _entrada(s, entry_id),
            lambda e: e is not None and e["state"] == "loaded",
            descripcion=f"entrada {entry_id} de banco_flujos en estado loaded",
        )
        return entry_id

    async def test_titulo_y_preferencias(self) -> None:
        tool = "ha_update_config_entry"
        async with self.sesion() as s:
            entry_id = await self._entrada_nueva(s)

            # Título: sin token.
            titulo = f"Banco {sufijo()}"
            hecho = await s.accion(tool, entry_id=entry_id, title=titulo)
            self.assertNotIn("confirmation_token", hecho)
            self.assertEqual((hecho["result"], hecho["reloaded"]), ("ok", False))
            self.assertEqual((await _entrada(s, entry_id))["title"], titulo)

            # Desactivar el sondeo: la vista previa no cambia nada.
            vista = await s.vista(tool, entry_id=entry_id, pref_disable_polling=True)
            self.assertEqual(vista["preview"]["state"], "loaded")
            self.assertEqual(
                vista["preview"]["pref_disable_polling"], {"current": False, "new": True}
            )
            self.assertFalse((await _entrada(s, entry_id))["pref_disable_polling"])
            hecho = await s.confirmar(tool, vista, entry_id=entry_id, pref_disable_polling=True)
            self.assertEqual((hecho["result"], hecho["reloaded"]), ("ok", True))
            despues = await s.lector.esperar(
                lambda: _entrada(s, entry_id),
                lambda e: e is not None and e["pref_disable_polling"] and e["state"] == "loaded",
                descripcion=f"entrada {entry_id} sin sondeo y cargada de nuevo",
            )
            self.assertTrue(despues["pref_disable_polling"])

            # Desactivar las entidades nuevas: igual.
            vista = await s.vista(tool, entry_id=entry_id, pref_disable_new_entities=True)
            self.assertFalse((await _entrada(s, entry_id))["pref_disable_new_entities"])
            await s.confirmar(tool, vista, entry_id=entry_id, pref_disable_new_entities=True)
            self.assertTrue((await _entrada(s, entry_id))["pref_disable_new_entities"])

            # Volver a activar las dos: sin token.
            hecho = await s.accion(
                tool, entry_id=entry_id, pref_disable_polling=False, pref_disable_new_entities=False
            )
            self.assertNotIn("confirmation_token", hecho)
            final = await _entrada(s, entry_id)
            self.assertEqual(
                (final["pref_disable_polling"], final["pref_disable_new_entities"]), (False, False)
            )

            # Sin cambios: ni token ni llamada.
            self.assertEqual(
                await s.accion(tool, entry_id=entry_id, title=titulo), {"result": "unchanged"}
            )
