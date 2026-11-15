"""Banco de Core: usuarios (spec 021, tramo b, T030).

Las cuatro tools de usuarios contra HA Core real, con el lector independiente
(`config/auth/list` directo a Core) comprobando cada efecto y dejando el banco
como estaba:

- **Lista**: `ha_list_users(include_system=True)` coincide con el lector, y
  el propietario del onboarding sale con `is_owner` e `is_hermes` (en el banco
  la conexión de Hermes es la del propietario; en producción es el usuario de
  sistema del Supervisor). Ninguna fila trae credenciales más allá del tipo.
- **Ciclo de un usuario creado por la tool**: crear (la vista previa no crea
  nada; con token, el lector lo ve sin credenciales y en `system-users`),
  renombrar, dar `system-admin` (vista previa con `grants_admin` y
  `active_admins` sumando uno), quitarlo, `local_only`, desactivar y borrar.
  Cada paso, comprobado por el lector. Si un paso falla, el lector borra el
  usuario al cerrar.
- **Protecciones**: `ha_update_user` y `ha_delete_user` sobre el propietario
  (que aquí es también el usuario de Hermes) → `protected_user` con
  `["owner", "hermes"]`, y el lector lo ve igual.
- **Tabla**: `config/auth/delete` por la genérica → `use_dedicated_tool`.

Solo corre en el job `banco-core` del CI; fuera se salta con su motivo.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.banco.base_escrituras import BancoEscrituras, SesionEscrituras, sufijo
from tests.banco.entorno import llamar, rechazo

pytestmark = pytest.mark.banco


async def _usuarios(s: SesionEscrituras) -> dict[str, dict[str, Any]]:
    return {u["id"]: u for u in await s.lector.comando({"type": "config/auth/list"})}


async def _propietario(s: SesionEscrituras) -> dict[str, Any]:
    return next(u for u in (await _usuarios(s)).values() if u["is_owner"])


class TestUsuarios(BancoEscrituras):
    async def test_lista_igual_que_el_lector(self) -> None:
        async with self.sesion() as s:
            r = await s.accion("ha_list_users", include_system=True)
            reales = await _usuarios(s)
            self.assertTrue(r["hermes_user_known"])
            self.assertEqual({i["id"] for i in r["items"]}, set(reales))
            for fila in r["items"]:
                real = reales[fila["id"]]
                with self.subTest(usuario=fila["id"]):
                    for campo in ("name", "is_owner", "is_active", "local_only",
                                  "system_generated", "group_ids"):
                        self.assertEqual(fila[campo], real[campo])
                    self.assertEqual(fila["credential_types"],
                                     sorted({c["type"] for c in real["credentials"]}))
                    self.assertNotIn("credentials", fila)
            dueno = next(i for i in r["items"] if i["is_owner"])
            self.assertTrue(dueno["is_hermes"])
            self.assertTrue(dueno["is_admin"])
            self.assertGreaterEqual(r["active_admins"], 1)

    async def test_ciclo_de_un_usuario(self) -> None:
        nombre = f"Banco 021 {sufijo()}"
        async with self.sesion() as s:
            antes = await _usuarios(s)

            async def borrar_si_queda() -> None:
                for uid, u in (await _usuarios(s)).items():
                    if uid not in antes and u["name"].startswith("Banco 021"):
                        await s.lector.comando({"type": "config/auth/delete", "user_id": uid})

            s.limpiezas.append(borrar_si_queda)

            # Crear: la vista previa no crea nada.
            vista = await s.vista("ha_create_user", name=nombre)
            p = vista["preview"]
            self.assertTrue(p["credentials"].startswith("none"), p)
            self.assertFalse(p["grants_admin"])
            self.assertEqual(set(await _usuarios(s)), set(antes))
            r = await s.confirmar("ha_create_user", vista, name=nombre)
            uid = r["user"]["id"]
            creado = (await _usuarios(s))[uid]
            self.assertEqual((creado["name"], creado["group_ids"], creado["credentials"]),
                             (nombre, ["system-users"], []))
            self.assertFalse(creado["is_owner"])

            async def paso(previa: dict[str, Any] | None = None, **cambios: Any) -> dict[str, Any]:
                v = await s.vista("ha_update_user", user_id=uid, **cambios)
                if previa:
                    for clave, valor in previa.items():
                        self.assertEqual(v["preview"][clave], valor, v["preview"])
                # La vista previa no cambia nada.
                self.assertEqual((await _usuarios(s))[uid], actual[0])
                r = await s.confirmar("ha_update_user", v, user_id=uid, **cambios)
                self.assertEqual(r["result"], "ok")
                actual[0] = (await _usuarios(s))[uid]
                return actual[0]

            actual = [creado]
            u = await paso(name=f"{nombre} bis")
            self.assertEqual(u["name"], f"{nombre} bis")

            admins = (await s.accion("ha_list_users"))["active_admins"]
            u = await paso({"grants_admin": True,
                            "active_admins": {"before": admins, "after": admins + 1}},
                           group="system-admin")
            self.assertEqual(u["group_ids"], ["system-admin"])

            u = await paso({"removes_admin": True,
                            "active_admins": {"before": admins + 1, "after": admins}},
                           group="system-users")
            self.assertEqual(u["group_ids"], ["system-users"])

            u = await paso({"restricts_remote": True}, local_only=True)
            self.assertTrue(u["local_only"])

            u = await paso({"deactivates": True}, is_active=False)
            self.assertFalse(u["is_active"])

            # Borrar: la vista previa no borra; con token, el lector ya no lo ve.
            vista = await s.vista("ha_delete_user", user_id=uid)
            self.assertEqual(vista["preview"]["user"]["id"], uid)
            self.assertIn(uid, await _usuarios(s))
            r = await s.confirmar("ha_delete_user", vista, user_id=uid)
            self.assertEqual(r, {"result": "ok", "deleted": uid})
            self.assertNotIn(uid, await _usuarios(s))
            self.assertEqual(set(await _usuarios(s)), set(antes))

    async def test_propietario_y_hermes_protegidos(self) -> None:
        async with self.sesion() as s:
            dueno = await _propietario(s)
            for tool, args in (("ha_update_user", {"name": "Otro nombre"}),
                               ("ha_update_user", {"group": "system-users"}),
                               ("ha_delete_user", {})):
                with self.subTest(tool=tool, args=args):
                    r = await rechazo(s.cliente, tool, user_id=dueno["id"], **args)
                    self.assertEqual(r["error"], "protected_user", r)
                    self.assertEqual(r["reasons"], ["owner", "hermes"])
                    self.assertNotIn("confirmation_token", r)
            self.assertEqual(await _propietario(s), dueno)

    async def test_borrar_por_la_generica_rechazado(self) -> None:
        async with self.sesion() as s:
            dueno = await _propietario(s)
            r = await rechazo(s.cliente, "ha_call_ws_command", type="config/auth/delete",
                              payload={"user_id": dueno["id"]})
            self.assertEqual((r["error"], r["tool"]), ("use_dedicated_tool", "ha_delete_user"))
            r = await llamar(s.cliente, "ha_list_users")
            self.assertIn(dueno["id"], [i["id"] for i in r["items"]])
