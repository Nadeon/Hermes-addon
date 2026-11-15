"""Banco de Core: agentes y ajustes de los backups de HA (spec 031, tramo 1, T013).

Contra HA Core real, con el lector independiente leyendo directo de Core:

- `ha_list_backup_agents` ve el agente local de Core (`backup.local`, que
  existe porque la configuración del banco carga `backup:` y no hay
  Supervisor) con `kind: local`, y su forma cuadra con `backup/agents/info`
  del lector.
- `ha_update_backup_config` cambia `schedule` (`daily` a las 04:30) y
  `retention` (`copies: 2`) en dos pasos: la vista previa no cambia nada (el
  lector lee `backup/config/info` antes y después y son iguales) y la
  confirmación sí (el lector lo lee). Hermes completa lo no pasado con lo
  actual: los `days` de la programación y de la retención no se pierden.
- `ha_get_update_backup_settings` responde
  `supervisor_integration_unavailable`: el banco es Core sin Supervisor, y
  `hassio/update/config/*` solo existe con la integración `hassio`.
- La genérica de escritura rechaza `backup/config/update` hacia su tool.

Limpieza: el lector deja la programación y la retención como estaban, pase lo
que pase. Solo corre en el job `banco-core` del CI; fuera se salta con su
motivo.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras
from tests.banco.entorno import rechazo

pytestmark = pytest.mark.banco


async def _config(s: SesionEscrituras) -> dict[str, Any]:
    return (await s.lector.comando({"type": "backup/config/info"}))["config"]


def _ajustes(config: dict[str, Any]) -> dict[str, Any]:
    """Lo que la tool puede cambiar y el test comprueba (sin `next_*`, que HA
    recalcula al aplicar la programación)."""
    return {"schedule": config["schedule"], "retention": config["retention"],
            "agents": config["agents"],
            "create_backup": {k: v for k, v in config["create_backup"].items()
                              if k != "password"},
            "automatic_backups_configured": config["automatic_backups_configured"]}


def _restaurar(s: SesionEscrituras, original: dict[str, Any]) -> None:
    """Limpieza independiente de Hermes: la programación y la retención de antes."""

    async def limpiar() -> None:
        sched = original["schedule"]
        await s.lector.comando({
            "type": "backup/config/update",
            "schedule": {"recurrence": sched["recurrence"], "days": sched["days"],
                         "time": sched["time"]},
            "retention": original["retention"],
        })

    s.limpiezas.append(limpiar)


class TestAgentesYAjustes(BancoEscrituras):
    async def test_agentes(self) -> None:
        async with self.sesion() as s:
            r = await s.accion("ha_list_backup_agents")
            del_lector = await s.lector.comando({"type": "backup/agents/info"})
            self.assertEqual([a["agent_id"] for a in r["items"]],
                             [a["agent_id"] for a in del_lector["agents"]])
            local = next(a for a in r["items"] if a["agent_id"] == "backup.local")
            self.assertEqual(local["kind"], "local")
            self.assertIsInstance(local["protected"], bool)
            self.assertEqual(r["count"], len(r["items"]))
            self.assertFalse(r["truncated"])

    async def test_programacion_y_retencion(self) -> None:
        tool = "ha_update_backup_config"
        async with self.sesion() as s:
            original = await _config(s)
            _restaurar(s, original)
            # Unos días en la programación y en la retención, puestos por el
            # lector, para ver que la tool los conserva al cambiar lo demás.
            await s.lector.comando({
                "type": "backup/config/update",
                "schedule": {"recurrence": "custom_days", "days": ["mon", "thu"],
                             "time": None},
                "retention": {"copies": None, "days": 30},
            })
            antes = _ajustes(await _config(s))

            args = {"schedule": {"recurrence": "daily", "time": "04:30"},
                    "retention": {"copies": 2}}
            vista = await s.vista(tool, **args)
            p = vista["preview"]
            self.assertEqual(p["sends"]["schedule"],
                             {"recurrence": "daily", "days": ["mon", "thu"], "time": "04:30:00"})
            self.assertEqual(p["sends"]["retention"], {"copies": 2, "days": 30})
            self.assertIn("retention.copies", p["changed"])
            self.assertTrue(p["retention_effect"]["estimate"])
            # La vista previa no ha cambiado nada en HA.
            self.assertEqual(_ajustes(await _config(s)), antes)

            r = await s.confirmar(tool, vista, **args)
            self.assertEqual(r["result"], "ok")
            despues = await _config(s)
            self.assertEqual(despues["schedule"]["recurrence"], "daily")
            self.assertEqual(despues["schedule"]["time"], "04:30:00")
            self.assertEqual(despues["schedule"]["days"], ["mon", "thu"])
            self.assertEqual(despues["retention"], {"copies": 2, "days": 30})
            # La respuesta y la vista previa no llevan la clave en ningún sitio.
            self.assertNotIn('"password"', json.dumps([vista, r]))

    async def test_ajustes_previos_a_actualizar_sin_supervisor(self) -> None:
        async with self.sesion() as s:
            r = await rechazo(s.cliente, "ha_get_update_backup_settings")
            self.assertEqual(r["error"], "supervisor_integration_unavailable")

    async def test_la_generica_rechaza_hacia_su_tool(self) -> None:
        async with self.sesion() as s:
            r = await rechazo(s.cliente, "ha_call_ws_command", type="backup/config/update",
                              payload={"retention": {"copies": 1}})
            self.assertEqual((r["error"], r["tool"]),
                             ("use_dedicated_tool", "ha_update_backup_config"))
