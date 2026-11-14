"""Banco de Core: las cinco tools de `system_status` contra HA Core 2026.11.1
real (spec 029, T016; FR-022; FR-015 de la 008).

Todas leen, así que lo que se comprueba es que funcionan contra la HA de
verdad (formas reales de `system_health/info`, `subscribe_system_state`,
`integration/setup_info` y `manifest/*`) y, donde se puede, se contrasta con
el lector independiente (directo a Core, sin Hermes):

- salud: el dominio `homeassistant` con la versión que da `get_config` al
  lector; la recogida termina y NO deja la suscripción registrada en el
  cliente de Hermes; una segunda llamada responde igual;
- estado: sin reinicio pendiente en un HA recién arrancado;
- tiempos de arranque: incluye `http`;
- manifiestos: `input_boolean` (de HA) y `no_existe` en `missing`; el
  detalle de `input_boolean` con `is_built_in: true`;
- la genérica de lectura rechaza `system_health/info` hacia su tool.

La configuración del banco carga `system_health:` (sin él, el comando no
existe) y `network:` (lo usa el tramo 2 para `network` y `network/url`).

Inventario: `PROBADAS_EN_BANCO_029` (`tests/banco/cobertura.py`); el job exige
que cada una se haya llamado con éxito en un test que ha pasado.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.banco.base_helpers import BancoHelpers, sin_error
from tests.banco.entorno import llamar

pytestmark = pytest.mark.banco


async def _rechazo(cliente: Any, tool: str, **args: Any) -> dict[str, Any]:
    """Llama a una tool que DEBE rechazar y devuelve su `{"error": …}` (como
    en `test_banco_genericas.py`: `llamar` convertiría el rechazo en fallo)."""
    resultado = await cliente.call_tool(tool, args)
    assert getattr(resultado, "is_error", False), f"{tool}: se esperaba un rechazo"
    return json.loads(resultado.content[0].text)


class TestEstadoDelSistema(BancoHelpers):
    async def test_salud_del_sistema(self) -> None:
        tool = "ha_get_system_health"
        async with self.sesion() as s:
            config = await s.lector.comando({"type": "get_config"})
            r = sin_error(tool, await llamar(s.cliente, tool, timeout_seconds=15))
            self.assertIn("homeassistant", r["domains"])
            info = r["domains"]["homeassistant"]["info"]
            self.assertEqual(info["version"], f"core-{config['version']}")
            self.assertIn("2026.11.1", info["version"])
            self.assertIs(r["complete"], True, r)
            self.assertEqual(r["pending"], [])
            self.assertIs(r["truncated"], False)
            # La suscripción se canceló: nada queda registrado en el cliente.
            self.assertEqual(s.ha_client._event_subscription_queues, {})
            self.assertEqual(s.ha_client._pending_ws_responses, {})
            # Y una segunda llamada responde igual (HA no se quedó con nada
            # a medias de la primera).
            otra = sin_error(tool, await llamar(s.cliente, tool, domain="homeassistant"))
            self.assertEqual(otra["domains"]["homeassistant"]["info"]["version"],
                             info["version"])

    async def test_estado_del_sistema(self) -> None:
        tool = "ha_get_system_state"
        async with self.sesion() as s:
            r = sin_error(tool, await llamar(s.cliente, tool))
            for clave in ("home_assistant_restart_required",
                          "home_assistant_restart_sources",
                          "home_assistant_restart_dismissed",
                          "host_reboot_required", "host_reboot_dismissed"):
                self.assertIn(clave, r)
            self.assertIs(r["home_assistant_restart_required"], False)
            self.assertEqual(s.ha_client._event_subscription_queues, {})

    async def test_tiempos_de_arranque(self) -> None:
        tool = "ha_list_integration_setup_times"
        async with self.sesion() as s:
            r = sin_error(tool, await llamar(s.cliente, tool, limit=500))
            dominios = [i["domain"] for i in r["items"]]
            self.assertIn("http", dominios)
            segundos = [i["seconds"] for i in r["items"]]
            self.assertEqual(segundos, sorted(segundos, reverse=True))
            self.assertEqual(r["total"], r["count"])

    async def test_manifiestos(self) -> None:
        async with self.sesion() as s:
            tool = "ha_list_integration_manifests"
            r = sin_error(tool, await llamar(
                s.cliente, tool, integrations=["input_boolean", "no_existe"]))
            self.assertEqual([i["domain"] for i in r["items"]], ["input_boolean"])
            self.assertIs(r["items"][0]["is_built_in"], True)
            self.assertNotIn("_third_party_text", r["items"][0])
            self.assertEqual(r["missing"], ["no_existe"])

            tool = "ha_get_integration_manifest"
            m = sin_error(tool, await llamar(s.cliente, tool, integration="input_boolean"))
            self.assertEqual(m["domain"], "input_boolean")
            self.assertIs(m["is_built_in"], True)
            self.assertNotIn("_third_party_text", m)
            # Contrastado con el lector, directo a Core.
            directo = await s.lector.comando(
                {"type": "manifest/get", "integration": "input_boolean"})
            self.assertEqual(m["name"], directo["name"])

    async def test_la_generica_rechaza_hacia_la_dedicada(self) -> None:
        async with self.sesion() as s:
            r = await _rechazo(s.cliente, "ha_read_ws_command", type="system_health/info")
            self.assertEqual((r["error"], r["tool"]),
                             ("use_dedicated_tool", "ha_get_system_health"))
