"""Banco de Core: red y HTTP de Core (spec 021, tramo c, T047).

Las tres tools de `core_network` contra HA Core real, con el lector
independiente comprobando cada efecto directamente en Core:

- **Red**: `ha_update_network_config` con los adaptadores del contenedor que
  lee el lector en `network`. La vista previa no cambia `configured_adapters`
  (lo mira el lector); la confirmación sí. El lector restaura la lista previa
  al cerrar, pase lo que pase. No toca el enlace HTTP.
- **HTTP, solo la vista previa** (research R-8): confirmar guardaría una
  configuración pendiente y reiniciaría la HA del banco, que el job perdería.
  La vista previa de un cambio de `cors_allowed_origins` trae el documento
  fundido sobre la configuración real con la que HA funciona, el aviso de
  reinicio y su aviso `cors`, y el lector ve `http/config` idéntico antes y
  después. Un `server_host` sin el Supervisor se rechaza de verdad
  (`supervisor_lockout`, decisión D-3) sin tocar nada.
- **Promover**: el banco no tiene pendiente: `nothing_to_promote` real.
- **Tabla**: `http/config/configure` por la genérica da `use_dedicated_tool`.

La confirmación de las dos de HTTP va a la VM (`NO_EJECUTABLES_021` y la
matriz de la 014). Solo corre en el job `banco-core` del CI.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras
from tests.banco.entorno import rechazo

pytestmark = pytest.mark.banco

_META = ("created_at", "error", "error_message")


async def _red(s: SesionEscrituras) -> dict[str, Any]:
    return await s.lector.comando({"type": "network"})


async def _http(s: SesionEscrituras) -> dict[str, Any]:
    return await s.lector.comando({"type": "http/config"})


def _base_activa(http: dict[str, Any]) -> dict[str, Any]:
    tipo = http["active_config_type"]
    doc = http["stable"] if tipo == "stable" else (
        http["pending"] if tipo == "pending" else http["default"])
    doc = {k: v for k, v in doc.items() if k not in _META}
    if tipo == "default_legacy_port":
        doc["server_port"] = 8123
    return doc


class TestRedDeCore(BancoEscrituras):
    async def test_cambiar_y_restaurar_los_adaptadores(self) -> None:
        tool = "ha_update_network_config"
        async with self.sesion() as s:
            antes = await _red(s)
            original = list(antes["configured_adapters"])

            async def restaurar() -> None:
                await s.lector.comando({"type": "network/configure",
                                        "config": {"configured_adapters": original}})

            s.limpiezas.append(restaurar)
            nombres = [a["name"] for a in antes["adapters"]]
            self.assertTrue(nombres, "el contenedor no tiene adaptadores")
            habilitados = sorted(a["name"] for a in antes["adapters"] if a["enabled"])
            # Un objetivo distinto de lo configurado: los habilitados, o el
            # primero si ya estaban configurados así.
            objetivo = habilitados or nombres[:1]
            if set(objetivo) == set(original):
                objetivo = [] if original else nombres[:1]

            vista = await s.vista(tool, configured_adapters=objetivo)
            p = vista["preview"]
            self.assertEqual(p["configured_adapters"],
                             {"before": original, "after": objetivo})
            self.assertIn("does not change the address or port", p["note"])
            self.assertEqual((await _red(s))["configured_adapters"], original)

            r = await s.confirmar(tool, vista, configured_adapters=objetivo)
            self.assertEqual(r["result"], "ok")
            await s.lector.esperar(
                lambda: _red(s),
                lambda red: set(red["configured_adapters"]) == set(objetivo),
                descripcion="adaptadores configurados con la lista nueva",
            )

            # Restaurar por la propia tool y comprobarlo con el lector.
            vista = await s.vista(tool, configured_adapters=original)
            await s.confirmar(tool, vista, configured_adapters=original)
            self.assertEqual(set((await _red(s))["configured_adapters"]), set(original))


class TestHttpDeCore(BancoEscrituras):
    async def test_vista_previa_sin_efecto(self) -> None:
        tool = "ha_update_http_config"
        async with self.sesion() as s:
            antes = await _http(s)
            self.assertIsNone(antes["pending"])
            origenes = ["https://banco-021.example"]
            vista = await s.vista(tool, changes={"cors_allowed_origins": origenes})
            p = vista["preview"]
            esperado = {**_base_activa(antes), "cors_allowed_origins": origenes}
            self.assertEqual(p["new_config"], esperado)
            self.assertEqual(list(p["changes"]), ["cors_allowed_origins"])
            self.assertEqual([a["code"] for a in p["warnings"]], ["cors"])
            self.assertNotIn("access_risk", p)
            self.assertIn("5 minutes", p["restart"])
            # Ni la vista previa ni el rechazo han cambiado nada.
            r = await rechazo(s.cliente, tool, changes={"server_host": ["192.0.2.10"]})
            self.assertEqual(r["error"], "supervisor_lockout")
            self.assertEqual(await _http(s), antes)

    async def test_promover_sin_pendiente(self) -> None:
        async with self.sesion() as s:
            antes = await _http(s)
            r = await rechazo(s.cliente, "ha_promote_http_config")
            self.assertEqual(r["error"], "nothing_to_promote")
            self.assertEqual(await _http(s), antes)

    async def test_configure_por_la_generica_rechazado(self) -> None:
        async with self.sesion() as s:
            antes = await _http(s)
            r = await rechazo(s.cliente, "ha_call_ws_command",
                              type="http/config/configure", payload={"config": None})
            self.assertEqual((r["error"], r["tool"]),
                             ("use_dedicated_tool", "ha_update_http_config"))
            self.assertEqual(await _http(s), antes)
