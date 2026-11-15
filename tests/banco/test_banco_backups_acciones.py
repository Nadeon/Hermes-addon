"""Banco de Core: crear y borrar backups de HA (spec 031, tramo 2, T029).

Contra HA Core real (agente `backup.local`, sin Supervisor), con el lector
independiente leyendo directo de Core:

- El lector fija una clave de cifrado centinela (`create_backup.password`) y
  `leer_clave_de_backups`, con un `HAClient` como el de Hermes (por el proxy
  del Supervisor simulado), la devuelve.
- `ha_create_backup(agent_ids=["backup.local"])` con y sin `encrypt`: la
  vista previa no crea nada; al confirmar, el backup aparece en
  `backup/info` del lector con `protected` correcto, siguiéndolo con
  `ha_list_backups` hasta `state: idle`.
- Con `ha_update_backup_config` (`create_backup.agent_ids: ["backup.local"]`,
  `retention.copies: 1`) y dos `ha_create_automatic_backup`, la vista previa
  del segundo estima borrar el primero y el lector ve que HA lo borra.
- `ha_delete_backup` de los que quedan: la vista previa no borra nada; al
  confirmar, el lector ya no los ve.
- Ninguna respuesta ni el log capturado contienen la clave centinela.

Limpieza independiente de Hermes: el lector deja la clave, los agentes, la
retención y la programación como estaban y borra los backups que el test
haya creado. Solo corre en el job `banco-core` del CI; fuera se salta con su
motivo.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from structlog.testing import capture_logs

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo
from tests.banco.entorno import rechazo

pytestmark = pytest.mark.banco

# Crear un backup de Core (un tar de /config) tarda unos segundos en el
# runner; más que el plazo por defecto del lector.
_PLAZO_BACKUP = 120.0


async def _info(s: SesionEscrituras) -> dict[str, Any]:
    return await s.lector.comando({"type": "backup/info"})


async def _ids(s: SesionEscrituras) -> set[str]:
    return {b["backup_id"] for b in (await _info(s))["backups"]}


def _preparar(s: SesionEscrituras, centinela: str, creados: set[str]) -> Any:
    """Fija la clave centinela con el lector y registra la limpieza."""

    async def preparar() -> dict[str, Any]:
        original = (await s.lector.comando({"type": "backup/config/info"}))["config"]
        await s.lector.comando({"type": "backup/config/update",
                                "create_backup": {"password": centinela}})
        return original

    async def limpiar_con(original: dict[str, Any]) -> None:
        sched = original["schedule"]
        cb = original["create_backup"]
        await s.lector.comando({
            "type": "backup/config/update",
            "create_backup": {"password": cb.get("password"), "agent_ids": cb.get("agent_ids")},
            "retention": original["retention"],
            "schedule": {"recurrence": sched["recurrence"], "days": sched["days"],
                         "time": sched["time"]},
        })
        for bid in sorted(creados & await _ids(s)):
            await s.lector.comando({"type": "backup/delete", "backup_id": bid})

    return preparar, limpiar_con


class TestCrearYBorrarBackups(BancoEscrituras):
    async def _esperar_backup_nuevo(self, s: SesionEscrituras, antes: set[str]) -> str:
        """Sigue el backup con `ha_list_backups` (Hermes) hasta `idle` y lo
        busca con el lector; devuelve su id."""
        await s.lector.esperar(
            lambda: s.accion("ha_list_backups", limit=100),
            lambda r: r["state"] == "idle" and (
                {b["backup_id"] for b in r["backups"]} - antes),
            descripcion="backup nuevo terminado (ha_list_backups)",
            timeout=_PLAZO_BACKUP,
        )
        nuevos = await _ids(s) - antes
        self.assertEqual(len(nuevos), 1, nuevos)
        return nuevos.pop()

    async def test_leer_la_clave_de_ha(self) -> None:
        from hermes.backup_key import leer_clave_de_backups
        from hermes.ha import HAClient
        from hermes.health import HealthServer

        centinela = f"centinela-banco-{sufijo()}"
        async with self.sesion() as s:
            preparar, limpiar_con = _preparar(s, centinela, set())
            original = await preparar()

            async def limpiar() -> None:
                await limpiar_con(original)

            s.limpiezas.append(limpiar)
            ha_client = HAClient(self.entorno.supervisor_url, self.entorno.token_addon,
                                 HealthServer())
            try:
                await ha_client.start(timeout_seconds=30)
                with capture_logs() as logs:
                    leida = await leer_clave_de_backups(ha_client)
            finally:
                await ha_client.stop()
            self.assertEqual((leida.clave, leida.motivo), (centinela, None))
            self.assertNotIn(centinela, repr(leida))
            self.assertNotIn(centinela, json.dumps(logs, default=str))

    async def test_crear_automatico_y_borrar(self) -> None:
        centinela = f"centinela-banco-{sufijo()}"
        creados: set[str] = set()
        async with self.sesion() as s:
            preparar, limpiar_con = _preparar(s, centinela, creados)
            original = await preparar()

            async def limpiar() -> None:
                await limpiar_con(original)

            s.limpiezas.append(limpiar)
            respuestas: list[Any] = []
            with capture_logs() as logs:
                # ── ha_create_backup, cifrado y sin cifrar ──────────────────
                for encrypt in (True, False):
                    with self.subTest(encrypt=encrypt):
                        args = {"agent_ids": ["backup.local"], "encrypt": encrypt,
                                "name": f"banco-031-{sufijo()}"}
                        antes = await _ids(s)
                        vista = await s.vista("ha_create_backup", **args)
                        respuestas.append(vista)
                        p = vista["preview"]
                        self.assertEqual(p["agents"], [{"agent_id": "backup.local",
                                                        "kind": "local",
                                                        "encrypted": encrypt}])
                        # La vista previa no crea nada.
                        self.assertEqual(await _ids(s), antes)
                        r = await s.confirmar("ha_create_backup", vista, **args)
                        respuestas.append(r)
                        self.assertEqual(r["status"], "started")
                        self.assertTrue(r["backup_job_id"])
                        bid = await self._esperar_backup_nuevo(s, antes)
                        creados.add(bid)
                        b = next(x for x in (await _info(s))["backups"]
                                 if x["backup_id"] == bid)
                        self.assertEqual(b["name"], args["name"])
                        self.assertEqual(b["agents"]["backup.local"]["protected"], encrypt)

                # ── ha_create_automatic_backup con la retención real ─────────
                ajustes = {"create_backup": {"agent_ids": ["backup.local"]},
                           "retention": {"copies": 1}}
                vista = await s.vista("ha_update_backup_config", **ajustes)
                await s.confirmar("ha_update_backup_config", vista, **ajustes)

                antes = await _ids(s)
                vista = await s.vista("ha_create_automatic_backup")
                respuestas.append(vista)
                self.assertEqual(await _ids(s), antes)
                respuestas.append(await s.confirmar("ha_create_automatic_backup", vista))
                primero = await self._esperar_backup_nuevo(s, antes)
                creados.add(primero)

                antes = await _ids(s)
                vista = await s.vista("ha_create_automatic_backup")
                respuestas.append(vista)
                efecto = vista["preview"]["retention_effect"]
                self.assertIn(primero, [e["backup_id"] for e in efecto["would_delete"]])
                respuestas.append(await s.confirmar("ha_create_automatic_backup", vista))
                await s.lector.esperar(
                    lambda: _ids(s),
                    lambda ids: primero not in ids and bool(ids - antes),
                    descripcion="HA borra el primer automático por la retención",
                    timeout=_PLAZO_BACKUP,
                )
                segundo = (await _ids(s) - antes).pop()
                creados.add(segundo)

                # ── ha_delete_backup de lo que queda ─────────────────────────
                for bid in sorted(creados & await _ids(s)):
                    with self.subTest(borrar=bid):
                        vista = await s.vista("ha_delete_backup", backup_id=bid)
                        respuestas.append(vista)
                        p = vista["preview"]
                        self.assertEqual([u["agent_id"] for u in p["locations"]],
                                         ["backup.local"])
                        self.assertTrue(p["deleted_from_all_locations"])
                        self.assertIn(bid, await _ids(s))
                        r = await s.confirmar("ha_delete_backup", vista, backup_id=bid)
                        respuestas.append(r)
                        self.assertEqual((r["result"], r["deleted_from"]),
                                         ("ok", ["backup.local"]))
                        self.assertNotIn(bid, await _ids(s))

            texto = json.dumps([respuestas, logs], default=str)
            self.assertNotIn(centinela, texto)

    async def test_la_generica_rechaza_hacia_su_tool(self) -> None:
        async with self.sesion() as s:
            for comando, tool in (("backup/generate", "ha_create_backup"),
                                  ("backup/generate_with_automatic_settings",
                                   "ha_create_automatic_backup"),
                                  ("backup/delete", "ha_delete_backup")):
                with self.subTest(comando=comando):
                    r = await rechazo(s.cliente, "ha_call_ws_command", type=comando,
                                      payload={"backup_id": "x", "agent_ids": ["backup.local"]})
                    self.assertEqual((r["error"], r["tool"]), ("use_dedicated_tool", tool))
