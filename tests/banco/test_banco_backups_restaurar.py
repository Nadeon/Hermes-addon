"""Banco de Core: restaurar un backup de HA (spec 031, tramo 3, T044).

`ha_restore_backup` no se puede ejecutar con éxito en el banco: restaurar
escribe `.HA_RESTORE` y reinicia Core, y el banco no sobrevive al reinicio
(`NO_EJECUTABLES_031`; la prueba completa es de la VM de la 014). Lo que sí se
prueba contra HA Core real (agente `backup.local`, sin Supervisor), con el
lector independiente leyendo directo de Core:

- Con la clave centinela fijada por el lector, `ha_create_backup` cifrado.
- La vista previa de `ha_restore_backup(backup_id, agent_id="backup.local")`
  trae los datos de FR-007 (`kind: local`, `protected: true`,
  `password_source: backup_encryption_key`) y no cambia nada.
- Con `restore_addons`, `invalid_argument` (sin Supervisor, HA lo
  rechazaría: «Addons and folders are not supported in core restore»).
- La confirmación con `password="incorrecta"` da `password_incorrect`: HA
  comprueba la contraseña ANTES de escribir nada, y sigue respondiendo sin
  haberse reiniciado (el lector, con la misma conexión abierta antes, lee
  `backup/info` después y ve el intento fallido en `last_action_event`).
- Nunca una restauración con éxito. Ninguna respuesta ni el log contienen la
  clave ni la contraseña.

Limpieza independiente de Hermes: el lector deja la clave como estaba y
borra el backup creado. Solo corre en el job `banco-core` del CI; fuera se
salta con su motivo.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from structlog.testing import capture_logs

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo
from tests.banco.entorno import rechazo

pytestmark = pytest.mark.banco

_PLAZO_BACKUP = 120.0
_INCORRECTA = f"incorrecta-banco-{sufijo()}"


async def _info(s: SesionEscrituras) -> dict[str, Any]:
    return await s.lector.comando({"type": "backup/info"})


async def _ids(s: SesionEscrituras) -> set[str]:
    return {b["backup_id"] for b in (await _info(s))["backups"]}


class TestRestaurarBackup(BancoEscrituras):
    async def test_vista_previa_token_y_contrasena_incorrecta(self) -> None:
        centinela = f"centinela-banco-{sufijo()}"
        creados: set[str] = set()
        async with self.sesion() as s:
            original = (await s.lector.comando({"type": "backup/config/info"}))["config"]
            await s.lector.comando({"type": "backup/config/update",
                                    "create_backup": {"password": centinela}})

            async def limpiar() -> None:
                await s.lector.comando({
                    "type": "backup/config/update",
                    "create_backup": {"password": original["create_backup"].get("password")},
                })
                for bid in sorted(creados & await _ids(s)):
                    await s.lector.comando({"type": "backup/delete", "backup_id": bid})

            s.limpiezas.append(limpiar)
            respuestas: list[Any] = []
            with capture_logs() as logs:
                # ── Un backup cifrado con la clave de HA ─────────────────────
                args_crear = {"agent_ids": ["backup.local"], "encrypt": True,
                              "name": f"banco-031-restaurar-{sufijo()}"}
                antes = await _ids(s)
                vista = await s.vista("ha_create_backup", **args_crear)
                respuestas.append(await s.confirmar("ha_create_backup", vista, **args_crear))
                await s.lector.esperar(
                    lambda: _info(s),
                    lambda r: r["state"] == "idle" and bool(
                        {b["backup_id"] for b in r["backups"]} - antes),
                    descripcion="backup cifrado terminado",
                    timeout=_PLAZO_BACKUP,
                )
                nuevos = await _ids(s) - antes
                self.assertEqual(len(nuevos), 1, nuevos)
                bid = nuevos.pop()
                creados.add(bid)

                # ── Vista previa: los datos de FR-007, sin cambiar nada ──────
                args = {"backup_id": bid, "agent_id": "backup.local"}
                info_antes = await _info(s)
                vista = await s.vista("ha_restore_backup", **args)
                respuestas.append(vista)
                p = vista["preview"]
                self.assertEqual(p["backup"]["backup_id"], bid)
                self.assertEqual(p["backup"]["name"], args_crear["name"])
                self.assertEqual((p["location"]["agent_id"], p["location"]["kind"],
                                  p["location"]["protected"]),
                                 ("backup.local", "local", True))
                self.assertEqual(p["password_source"], "backup_encryption_key")
                self.assertIs(p["overwrites"]["homeassistant_configuration"], True)
                self.assertIs(p["overwrites"]["database"], True)
                self.assertTrue(any("restarts" in a for a in p["warnings"]))
                info_despues = await _info(s)
                self.assertEqual(info_despues["backups"], info_antes["backups"])
                self.assertEqual(info_despues["state"], "idle")

                # ── Apps sin Supervisor: rechazo antes de llamar a HA ────────
                r = await rechazo(s.cliente, "ha_restore_backup", **args,
                                  restore_addons=["core_mosquitto"])
                respuestas.append(r)
                self.assertEqual((r["error"], r["field"]),
                                 ("invalid_argument", "restore_addons"))

                # ── Contraseña incorrecta: HA la rechaza y no se reinicia ────
                args_mal = {**args, "password": _INCORRECTA}
                vista = await s.vista("ha_restore_backup", **args_mal)
                respuestas.append(vista)
                self.assertEqual(vista["preview"]["password_source"], "provided")
                r = await rechazo(s.cliente, "ha_restore_backup", **args_mal,
                                  confirmation_token=vista["confirmation_token"])
                respuestas.append(r)
                self.assertEqual(r["error"], "password_incorrect")
                # La misma conexión del lector, abierta antes, sigue viva:
                # Core no se reinició.
                info = await _info(s)
                self.assertIn(bid, {b["backup_id"] for b in info["backups"]})
                self.assertEqual(info["state"], "idle")
                evento = info.get("last_action_event") or {}
                self.assertEqual((evento.get("manager_state"), evento.get("state")),
                                 ("restore_backup", "failed"))

                # ── El token fallido no vale otra vez ────────────────────────
                r = await rechazo(s.cliente, "ha_restore_backup", **args_mal,
                                  confirmation_token=vista["confirmation_token"])
                respuestas.append(r)
                self.assertIn("confirmation_token", r["error"])
                self.assertEqual((await _info(s))["state"], "idle")

            texto = json.dumps([respuestas, logs], default=str)
            self.assertNotIn(centinela, texto)
            self.assertNotIn(_INCORRECTA, texto)

    async def test_la_generica_rechaza_hacia_su_tool(self) -> None:
        async with self.sesion() as s:
            r = await rechazo(s.cliente, "ha_call_ws_command", type="backup/restore",
                              payload={"backup_id": "x", "agent_id": "backup.local"})
            self.assertEqual((r["error"], r["tool"]), ("use_dedicated_tool", "ha_restore_backup"))
