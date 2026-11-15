"""Tools de usuarios (spec 021, tramo b; T021, T022, T023 y T033).

`ha_list_users`, `ha_create_user`, `ha_update_user` y `ha_delete_user` con
Home Assistant simulado: un `AsyncMock` de `ws_send` que responde por `type` y
FALLA si recibe un `config/auth/create|update|delete` que el test no espera
(SC-005: ninguna escritura sobre un protegido llega a HA). Datos ficticios:
`Invitada`, `person.invitada` y el centinela `centinela-021`, que HA mete
donde podría colarse una credencial (la lista de credenciales, un
`refresh_tokens` de más, un error) y que no puede aparecer en ninguna
respuesta, en el log ni en el fichero del token.

Controles negativos (T035), comprobados y con recuentos en el commit:
(a) sin la comprobación del usuario de Hermes → caen los `protected_user`
con `hermes`; (b) sin recomprobar las protecciones al confirmar → caen los
de `TestRecompruebaAlConfirmar`; (c) contando inactivos como administradores
→ caen `active_admins` y `last_admin`; (d) `auth/current_user` fallido
tratado como «no es Hermes» → caen los `preview_unavailable`; (e) devolver
`credentials` tal cual de HA → cae el centinela.
"""

from __future__ import annotations

import ast
import copy
import json
import pathlib
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from structlog.testing import capture_logs

import hermes.security as security
import hermes.tools.users as mod
from hermes.ha import HAConnectionError

_CENTINELA = "centinela-021"

_OWNER = "a" * 32
_SUPERVISOR = "b" * 32      # usuario de sistema por el que entra Hermes
_CONTENIDO = "c" * 32       # otro usuario de sistema
_ADMIN = "d" * 32
_INVITADA = "e" * 32
_INACTIVO = "f" * 32        # inactivo con system-admin: no cuenta


def _u(uid: str, name: str, *, owner: bool = False, active: bool = True,
       system: bool = False, groups: list[str] | None = None,
       username: str | None = None, creds: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": uid, "username": username, "name": name, "is_owner": owner,
        "is_active": active, "local_only": False, "system_generated": system,
        "group_ids": groups if groups is not None else ["system-users"],
        "credentials": creds if creds is not None else [],
    }


def _usuarios() -> list[dict[str, Any]]:
    return [
        _u(_OWNER, "Propietaria", owner=True, groups=["system-admin"], username="propietaria",
           creds=[{"type": "homeassistant"}]),
        _u(_SUPERVISOR, "Supervisor", system=True, groups=["system-admin"]),
        _u(_CONTENIDO, "Home Assistant Content", system=True, groups=["system-read-only"]),
        _u(_ADMIN, "Admin", groups=["system-admin"], username="admin",
           creds=[{"type": "homeassistant"}]),
        _u(_INVITADA, "Invitada", username="invitada", creds=[{"type": "homeassistant"}]),
        _u(_INACTIVO, "Antiguo", active=False, groups=["system-admin"]),
    ]


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_dir = security.CONFIRMATIONS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        security.CONFIRMATIONS_DIR = Path(self.temp_dir.name)
        self.usuarios = _usuarios()
        self.hermes = _SUPERVISOR
        self.personas: dict[str, list[dict[str, Any]]] = {
            "storage": [{"id": "invitada", "name": "Invitada", "user_id": _INVITADA,
                         "device_trackers": []}],
            "config": [],
        }
        self.enviados: list[dict[str, Any]] = []
        self.escrituras_esperadas = 0
        self.fallo_current: HAConnectionError | None = None
        self.fallo_lista: HAConnectionError | None = None
        self.fallo_escritura: HAConnectionError | None = None
        self.extra_respuesta: dict[str, Any] = {}
        self.ha = MagicMock()
        self.ha.wait_ready = AsyncMock(return_value=True)
        self.ha.ws_send = AsyncMock(side_effect=self._ws_send)
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha, response_max_bytes=131_072)
        self.t = self.mcp.tools

    async def asyncTearDown(self) -> None:
        security.CONFIRMATIONS_DIR = self.original_dir
        self.temp_dir.cleanup()

    def _buscar(self, uid: str) -> dict[str, Any] | None:
        return next((u for u in self.usuarios if u["id"] == uid), None)

    def escrituras(self) -> list[dict[str, Any]]:
        return [p for p in self.enviados if p["type"] in mod.ESCRITURAS]

    async def _ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        self.enviados.append(payload)
        tipo = payload["type"]
        if tipo == "auth/current_user":
            if self.fallo_current is not None:
                raise self.fallo_current
            return {"id": self.hermes, "name": "Supervisor", "is_owner": False,
                    "is_admin": True, "credentials": [], "mfa_modules": []}
        if tipo == "config/auth/list":
            if self.fallo_lista is not None:
                raise self.fallo_lista
            return [{**copy.deepcopy(u), **self.extra_respuesta} for u in self.usuarios]
        if tipo == "person/list":
            return copy.deepcopy(self.personas)
        if tipo in mod.ESCRITURAS:
            if len(self.escrituras()) > self.escrituras_esperadas:
                raise AssertionError(f"escritura inesperada: {payload}")
            if self.fallo_escritura is not None:
                raise self.fallo_escritura
            if tipo == "config/auth/create":
                nuevo = _u("9" * 32, payload["name"], groups=payload.get("group_ids"))
                nuevo["local_only"] = payload.get("local_only", False)
                self.usuarios.append(nuevo)
                return {"user": {**copy.deepcopy(nuevo), **self.extra_respuesta}}
            if tipo == "config/auth/update":
                u = self._buscar(payload["user_id"])
                assert u is not None
                for k in ("name", "is_active", "group_ids", "local_only"):
                    if k in payload:
                        u[k] = payload[k]
                return {"user": {**copy.deepcopy(u), **self.extra_respuesta}}
            if tipo == "config/auth/delete":
                self.usuarios = [u for u in self.usuarios if u["id"] != payload["user_id"]]
                return None
        raise AssertionError(f"comando inesperado: {payload}")

    def ficheros_de_token(self) -> str:
        return "".join(p.read_text(encoding="utf-8")
                       for p in Path(self.temp_dir.name).glob("*.json"))

    async def dos_pasos(self, tool: str, **args: Any) -> tuple[dict[str, Any], Any]:
        vista = await self.t[tool](**args)
        self.assertIn("confirmation_token", vista, vista)
        self.escrituras_esperadas += 1
        r = await self.t[tool](**args, confirmation_token=vista["confirmation_token"])
        return vista, r


# ── T021: ha_list_users ──────────────────────────────────────────────────────

class TestListUsers(_Base):
    async def test_campos_y_orden(self) -> None:
        r = await self.t["ha_list_users"]()
        self.assertEqual(r["hermes_user_known"], True)
        # Propietaria y Admin; ni el inactivo ni los de sistema.
        self.assertEqual(r["active_admins"], 2)
        nombres = [i["name"] for i in r["items"]]
        # Sin include_system: fuera los de sistema salvo el de Hermes.
        self.assertEqual(nombres, ["Admin", "Antiguo", "Invitada", "Propietaria", "Supervisor"])
        self.assertEqual(r["count"], 5)
        self.assertFalse(r["truncated"])
        por_id = {i["id"]: i for i in r["items"]}
        self.assertEqual(set(por_id[_INVITADA]), {
            "id", "name", "username", "is_owner", "is_active", "is_admin", "local_only",
            "system_generated", "group_ids", "credential_types", "is_hermes"})
        self.assertTrue(por_id[_OWNER]["is_admin"])
        self.assertTrue(por_id[_ADMIN]["is_admin"])
        self.assertFalse(por_id[_INACTIVO]["is_admin"])
        self.assertFalse(por_id[_INVITADA]["is_admin"])
        self.assertEqual(por_id[_INVITADA]["credential_types"], ["homeassistant"])
        self.assertTrue(por_id[_SUPERVISOR]["is_hermes"])
        self.assertFalse(por_id[_OWNER]["is_hermes"])

    async def test_include_system(self) -> None:
        r = await self.t["ha_list_users"](include_system=True)
        self.assertIn(_CONTENIDO, [i["id"] for i in r["items"]])
        self.assertEqual(r["count"], 6)
        self.assertEqual(r["active_admins"], 2)

    async def test_include_system_estricto(self) -> None:
        r = await self.t["ha_list_users"](include_system="yes")
        self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()

    async def test_current_user_falla(self) -> None:
        self.fallo_current = HAConnectionError("caído", code="unknown_error")
        r = await self.t["ha_list_users"]()
        self.assertFalse(r["hermes_user_known"])
        self.assertTrue(all(i["is_hermes"] is None for i in r["items"]))
        # Sin saber cuál es el de Hermes, los de sistema no salen.
        self.assertNotIn(_SUPERVISOR, [i["id"] for i in r["items"]])

    async def test_lista_falla(self) -> None:
        self.fallo_lista = HAConnectionError("unauthorized", code="unauthorized")
        r = await self.t["ha_list_users"]()
        self.assertEqual((r["error"], r["ha_code"]), ("ha_error", "unauthorized"))

    async def test_centinela_de_credenciales(self) -> None:
        """Control negativo (T035 e): devolver `credentials` tal cual → cae."""
        self.usuarios[4]["credentials"] = [
            {"type": "homeassistant", "password": _CENTINELA, "data": {"token": _CENTINELA}}]
        self.extra_respuesta = {"refresh_tokens": [{"token": _CENTINELA}],
                                "access_token": _CENTINELA}
        with capture_logs() as logs:
            r = await self.t["ha_list_users"](include_system=True)
        self.assertNotIn(_CENTINELA, json.dumps(r))
        self.assertNotIn(_CENTINELA, json.dumps(logs, default=str))
        fila = next(i for i in r["items"] if i["id"] == _INVITADA)
        self.assertEqual(fila["credential_types"], ["homeassistant"])
        self.assertNotIn("credentials", fila)
        self.assertNotIn("refresh_tokens", fila)

    async def test_log_sin_nombres_ni_ids(self) -> None:
        with capture_logs() as logs:
            await self.t["ha_list_users"](include_system=True)
        texto = json.dumps(logs, default=str)
        for valor in ("Invitada", "Propietaria", "invitada", _INVITADA, _OWNER):
            self.assertNotIn(valor, texto)

    async def test_recorte(self) -> None:
        self.usuarios += [_u(f"{i:032x}", f"Usuario {i:03d}") for i in range(300)]
        self.mcp = DummyMCP()
        mod.register(self.mcp, self.ha, response_max_bytes=4096)
        r = await self.mcp.tools["ha_list_users"]()
        self.assertTrue(r["truncated"])
        self.assertEqual(r["count"], len(r["items"]))
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False).encode()), 4096)


# ── T022: protecciones ───────────────────────────────────────────────────────

class TestProtecciones(_Base):
    async def _protegido(self, uid: str, esperadas: list[str]) -> None:
        for tool, args in (("ha_update_user", {"name": "Otro"}), ("ha_delete_user", {})):
            with self.subTest(tool=tool, user=uid):
                r = await self.t[tool](user_id=uid, **args)
                self.assertEqual(r["error"], "protected_user", r)
                self.assertEqual(r["reasons"], esperadas)
                self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.escrituras(), [])

    async def test_propietario(self) -> None:
        await self._protegido(_OWNER, ["owner"])

    async def test_usuario_de_hermes(self) -> None:
        """Control negativo (T035 a): sin la comprobación de Hermes → cae."""
        # Un usuario normal que es por el que entra Hermes (no de sistema).
        self.hermes = _ADMIN
        await self._protegido(_ADMIN, ["hermes"])

    async def test_de_sistema_y_hermes(self) -> None:
        await self._protegido(_SUPERVISOR, ["hermes", "system_generated"])

    async def test_de_sistema(self) -> None:
        await self._protegido(_CONTENIDO, ["system_generated"])

    async def test_todos_los_motivos(self) -> None:
        # En el banco el propietario es también el usuario de Hermes.
        self.hermes = _OWNER
        await self._protegido(_OWNER, ["owner", "hermes"])

    def _sin_propietario_activo(self) -> None:
        """Escenario a mano: sin propietario y con un solo administrador."""
        self.usuarios = [u for u in _usuarios() if u["id"] not in (_OWNER,)]

    async def test_ultimo_admin_quitar_grupo(self) -> None:
        """Control negativo (T035 c): contar inactivos → cae."""
        self._sin_propietario_activo()
        r = await self.t["ha_update_user"](user_id=_ADMIN, group="system-users")
        self.assertEqual(r["error"], "last_admin", r)
        self.assertEqual(self.escrituras(), [])

    async def test_ultimo_admin_desactivar(self) -> None:
        self._sin_propietario_activo()
        r = await self.t["ha_update_user"](user_id=_ADMIN, is_active=False)
        self.assertEqual(r["error"], "last_admin")

    async def test_ultimo_admin_borrar(self) -> None:
        self._sin_propietario_activo()
        r = await self.t["ha_delete_user"](user_id=_ADMIN)
        self.assertEqual(r["error"], "last_admin")
        self.assertEqual(self.escrituras(), [])

    async def test_ultimo_admin_renombrar_si(self) -> None:
        self._sin_propietario_activo()
        r = await self.t["ha_update_user"](user_id=_ADMIN, name="Admin 2")
        self.assertIn("confirmation_token", r)

    async def test_current_user_falla_en_las_tres(self) -> None:
        """Control negativo (T035 d): tratarlo como «no es Hermes» → cae."""
        self.fallo_current = HAConnectionError("caído", code="unknown_error")
        llamadas = (
            ("ha_create_user", {"name": "Nueva"}),
            ("ha_update_user", {"user_id": _INVITADA, "name": "Otra"}),
            ("ha_delete_user", {"user_id": _INVITADA}),
        )
        for tool, args in llamadas:
            with self.subTest(tool=tool):
                r = await self.t[tool](**args)
                self.assertEqual(r["error"], "preview_unavailable", r)
        self.assertEqual(self.escrituras(), [])

    async def test_lista_falla_cierra(self) -> None:
        self.fallo_lista = HAConnectionError("caído", code="unknown_error")
        r = await self.t["ha_delete_user"](user_id=_INVITADA)
        self.assertEqual(r["error"], "preview_unavailable")


class TestRecompruebaAlConfirmar(_Base):
    """Control negativo (T035 b): sin recomprobar al confirmar → caen."""

    async def test_pasa_a_ser_el_de_hermes(self) -> None:
        for tool, args in (("ha_update_user", {"name": "Otra"}), ("ha_delete_user", {})):
            with self.subTest(tool=tool):
                self.hermes = _SUPERVISOR
                vista = await self.t[tool](user_id=_INVITADA, **args)
                self.hermes = _INVITADA
                self.escrituras_esperadas = 1  # si llegara, el test lo vería
                r = await self.t[tool](user_id=_INVITADA, **args,
                                       confirmation_token=vista["confirmation_token"])
                self.assertEqual(r["error"], "protected_user", r)
                self.assertEqual(r["reasons"], ["hermes"])
                self.assertEqual(self.escrituras(), [])
                self.escrituras_esperadas = 0

    async def test_pasa_a_ser_el_ultimo_admin(self) -> None:
        self.usuarios = [u for u in _usuarios() if u["id"] != _OWNER]
        vista = await self.t["ha_update_user"](user_id=_ADMIN, is_active=False)
        # Sin propietario hay otro administrador... que se desactiva entre medias.
        self.assertEqual(vista["error"], "last_admin")
        self.usuarios.append(_u("1" * 32, "Segunda", groups=["system-admin"]))
        vista = await self.t["ha_update_user"](user_id=_ADMIN, is_active=False)
        self.assertIn("confirmation_token", vista)
        self.usuarios = [u for u in self.usuarios if u["id"] != "1" * 32]
        self.escrituras_esperadas = 1
        r = await self.t["ha_update_user"](user_id=_ADMIN, is_active=False,
                                           confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "last_admin")
        self.assertEqual(self.escrituras(), [])

    async def test_current_user_falla_al_confirmar(self) -> None:
        vista = await self.t["ha_delete_user"](user_id=_INVITADA)
        self.fallo_current = HAConnectionError("caído", code="unknown_error")
        self.escrituras_esperadas = 1
        r = await self.t["ha_delete_user"](user_id=_INVITADA,
                                           confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "preview_unavailable")
        self.assertEqual(self.escrituras(), [])


# ── T023: escrituras ─────────────────────────────────────────────────────────

class TestCreateUser(_Base):
    async def test_validacion(self) -> None:
        malos = (
            {"name": ""}, {"name": "   "}, {"name": "a" * 101}, {"name": "a\nb"},
            {"name": 5}, {"name": "Nueva", "group": "admins"},
            {"name": "Nueva", "local_only": "no"},
        )
        for args in malos:
            with self.subTest(args=args):
                r = await self.t["ha_create_user"](**args)
                self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()

    async def test_vista_previa(self) -> None:
        r = await self.t["ha_create_user"](name="Invitada", group="system-admin")
        p = r["preview"]
        self.assertEqual(p["action"], "create_user")
        self.assertEqual((p["name"], p["group"], p["local_only"]),
                         ("Invitada", "system-admin", False))
        self.assertTrue(p["grants_admin"])
        self.assertTrue(p["credentials"].startswith("none"))
        self.assertIn("cannot log in", p["credentials"])
        self.assertEqual(p["same_name"], [_INVITADA])
        self.assertEqual(self.escrituras(), [])

    async def test_confirmacion(self) -> None:
        _, r = await self.dos_pasos("ha_create_user", name="Nueva", local_only=True)
        self.assertEqual(r["result"], "ok")
        self.assertEqual(r["user"]["name"], "Nueva")
        self.assertEqual(r["user"]["credential_types"], [])
        self.assertEqual(r["user"]["is_hermes"], False)
        (escritura,) = self.escrituras()
        self.assertEqual(escritura, {"type": "config/auth/create", "name": "Nueva",
                                     "group_ids": ["system-users"], "local_only": True})

    async def test_otro_nombre_igual_entre_pasos(self) -> None:
        vista = await self.t["ha_create_user"](name="Nueva")
        self.usuarios.append(_u("2" * 32, "Nueva"))
        self.escrituras_esperadas = 1
        r = await self.t["ha_create_user"](name="Nueva",
                                           confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], security.ESTADO_CAMBIADO)
        self.assertEqual(self.escrituras(), [])

    async def test_respuesta_y_token_sin_credenciales(self) -> None:
        self.extra_respuesta = {"refresh_tokens": [{"token": _CENTINELA}],
                                "credentials": [{"type": "homeassistant",
                                                 "password": _CENTINELA}]}
        with capture_logs() as logs:
            vista, r = await self.dos_pasos("ha_create_user", name="Nueva")
        texto = json.dumps([vista, r]) + self.ficheros_de_token()
        self.assertNotIn(_CENTINELA, texto)
        self.assertNotIn(_CENTINELA, json.dumps(logs, default=str))
        self.assertEqual(r["user"]["credential_types"], ["homeassistant"])


class TestUpdateUser(_Base):
    async def test_validacion(self) -> None:
        malos = (
            {"user_id": "abc", "name": "x"}, {"user_id": "A" * 32, "name": "x"},
            {"user_id": _INVITADA}, {"user_id": _INVITADA, "is_active": "no"},
            {"user_id": _INVITADA, "group": "root"}, {"user_id": _INVITADA, "name": ""},
            {"user_id": _INVITADA, "local_only": 1},
        )
        for args in malos:
            with self.subTest(args=args):
                r = await self.t["ha_update_user"](**args)
                self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()

    async def test_inexistente(self) -> None:
        r = await self.t["ha_update_user"](user_id="0" * 32, name="x")
        self.assertEqual(r["error"], "not_found")
        self.assertEqual(r["missing"], ["0" * 32])

    async def test_vista_previa_dar_admin(self) -> None:
        r = await self.t["ha_update_user"](user_id=_INVITADA, group="system-admin",
                                           local_only=True)
        p = r["preview"]
        self.assertEqual(p["action"], "update_user")
        self.assertEqual(p["user"], {"id": _INVITADA, "name": "Invitada",
                                     "is_admin": False, "is_active": True})
        self.assertEqual(p["changes"], {
            "group_ids": {"before": ["system-users"], "after": ["system-admin"]},
            "local_only": {"before": False, "after": True}})
        self.assertEqual((p["grants_admin"], p["removes_admin"], p["deactivates"],
                          p["restricts_remote"]), (True, False, False, True))
        self.assertEqual(p["active_admins"], {"before": 2, "after": 3})

    async def test_vista_previa_quitar_y_desactivar(self) -> None:
        r = await self.t["ha_update_user"](user_id=_ADMIN, is_active=False)
        p = r["preview"]
        self.assertEqual((p["removes_admin"], p["deactivates"]), (True, True))
        self.assertEqual(p["active_admins"], {"before": 2, "after": 1})

    async def test_sin_cambios(self) -> None:
        r = await self.t["ha_update_user"](user_id=_INVITADA, name="Invitada",
                                           group="system-users", is_active=True)
        self.assertEqual(r, {"result": "no_changes"})

    async def test_confirmacion_solo_lo_dado(self) -> None:
        _, r = await self.dos_pasos("ha_update_user", user_id=_INVITADA, name="Invitada 2")
        self.assertEqual(r["result"], "ok")
        self.assertEqual(r["user"]["name"], "Invitada 2")
        self.assertEqual(self.escrituras(), [
            {"type": "config/auth/update", "user_id": _INVITADA, "name": "Invitada 2"}])

    async def test_grupo_reemplaza(self) -> None:
        await self.dos_pasos("ha_update_user", user_id=_INVITADA, group="system-read-only")
        self.assertEqual(self.escrituras()[0]["group_ids"], ["system-read-only"])

    async def test_estado_cambiado(self) -> None:
        vista = await self.t["ha_update_user"](user_id=_INVITADA, name="Otra")
        self._buscar(_INVITADA)["local_only"] = True
        self.escrituras_esperadas = 1
        r = await self.t["ha_update_user"](user_id=_INVITADA, name="Otra",
                                           confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], security.ESTADO_CAMBIADO)
        self.assertEqual(self.escrituras(), [])

    async def test_token_de_otros_argumentos(self) -> None:
        vista = await self.t["ha_update_user"](user_id=_INVITADA, name="Otra")
        self.escrituras_esperadas = 1
        r = await self.t["ha_update_user"](user_id=_INVITADA, name="Distinta",
                                           confirmation_token=vista["confirmation_token"])
        self.assertIn("does not match", r["error"])
        self.assertEqual(self.escrituras(), [])

    async def test_errores_de_ha(self) -> None:
        for codigo in ("cannot_deactivate_owner", "cannot_modify_system_generated",
                       "not_found"):
            with self.subTest(codigo=codigo):
                self.enviados.clear()
                self.escrituras_esperadas = 0
                self.fallo_escritura = HAConnectionError(
                    f"rechazado token={_CENTINELA}", code=codigo)
                _, r = await self.dos_pasos("ha_update_user", user_id=_INVITADA,
                                            name=f"Otra {codigo}")
                self.assertEqual((r["error"], r["ha_code"]), ("ha_error", codigo))
                self.assertNotIn(_CENTINELA, json.dumps(r))
                self.assertIn("explanation", r)

    async def test_unknown_command(self) -> None:
        self.fallo_lista = HAConnectionError("Unknown command.", code="unknown_command")
        r = await self.t["ha_update_user"](user_id=_INVITADA, name="x")
        self.assertEqual((r["error"], r["ha_code"]), ("unsupported_by_ha_version",
                                                      "unknown_command"))


class TestDeleteUser(_Base):
    async def test_validacion(self) -> None:
        r = await self.t["ha_delete_user"](user_id="no-es-un-id")
        self.assertEqual(r["error"], "invalid_argument")
        self.ha.ws_send.assert_not_awaited()

    async def test_vista_previa(self) -> None:
        self.personas["config"] = [{"id": "yaml_invitada", "name": "Invitada YAML",
                                    "user_id": _INVITADA}]
        r = await self.t["ha_delete_user"](user_id=_INVITADA)
        p = r["preview"]
        self.assertEqual(p["action"], "delete_user")
        self.assertEqual(p["user"]["id"], _INVITADA)
        self.assertEqual(p["linked_persons"], [
            {"id": "invitada", "name": "Invitada"},
            {"id": "yaml_invitada", "name": "Invitada YAML"}])
        self.assertIn("cannot be undone", p["irreversible"])
        self.assertEqual(p["active_admins"], {"before": 2, "after": 2})
        self.assertEqual(self.escrituras(), [])

    async def test_vista_previa_admin(self) -> None:
        r = await self.t["ha_delete_user"](user_id=_ADMIN)
        self.assertEqual(r["preview"]["active_admins"], {"before": 2, "after": 1})
        self.assertEqual(r["preview"]["linked_persons"], [])

    async def test_confirmacion(self) -> None:
        _, r = await self.dos_pasos("ha_delete_user", user_id=_INVITADA)
        self.assertEqual(r, {"result": "ok", "deleted": _INVITADA})
        self.assertEqual(self.escrituras(),
                         [{"type": "config/auth/delete", "user_id": _INVITADA}])

    async def test_ya_borrado_entre_pasos(self) -> None:
        vista = await self.t["ha_delete_user"](user_id=_INVITADA)
        self.usuarios = [u for u in self.usuarios if u["id"] != _INVITADA]
        self.escrituras_esperadas = 1
        r = await self.t["ha_delete_user"](user_id=_INVITADA,
                                           confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["error"], "not_found")
        self.assertEqual(self.escrituras(), [])

    async def test_no_delete_self(self) -> None:
        self.fallo_escritura = HAConnectionError(
            "Unable to delete your own account", code="no_delete_self")
        _, r = await self.dos_pasos("ha_delete_user", user_id=_INVITADA)
        self.assertEqual((r["error"], r["ha_code"]), ("ha_error", "no_delete_self"))


# ── T033: seguridad ──────────────────────────────────────────────────────────

_FUENTE = pathlib.Path(mod.__file__)


class TestSeguridad(_Base):
    def test_ningun_argumento_de_credenciales(self) -> None:
        arbol = ast.parse(_FUENTE.read_text(encoding="utf-8"))
        tools = [n for n in ast.walk(arbol) if isinstance(n, ast.AsyncFunctionDef)
                 and n.name in mod.TOOLS]
        self.assertEqual(sorted(n.name for n in tools), sorted(mod.TOOLS))
        malos = []
        for nodo in tools:
            for arg in nodo.args.args + nodo.args.kwonlyargs:
                nombre = arg.arg.lower()
                if nombre == "confirmation_token":
                    continue
                if any(p in nombre for p in ("password", "secret", "token", "username",
                                             "credential")):
                    malos.append(f"{nodo.name}.{arg.arg}")
        self.assertEqual(malos, [])

    async def test_sesion_completa_sin_datos_en_el_log(self) -> None:
        """El log solo lleva el nombre de la tool, el paso, el resultado y, en
        las escrituras, el `user_id` (decisión del supervisor). Nunca un nombre
        ni un nombre de acceso."""
        with capture_logs() as logs:
            await self.t["ha_list_users"](include_system=True)
            await self.dos_pasos("ha_create_user", name="Nueva Persona")
            await self.dos_pasos("ha_update_user", user_id=_INVITADA, name="Invitada 2")
            await self.dos_pasos("ha_delete_user", user_id=_INVITADA)
        texto = json.dumps(logs, default=str)
        for valor in ("Nueva Persona", "Invitada", "invitada", "Propietaria", "propietaria",
                      _OWNER, _ADMIN):
            self.assertNotIn(valor, texto)
        for entrada in logs:
            ids = [v for k, v in entrada.items() if isinstance(v, str) and len(v) == 32
                   and k != "user_id"]
            self.assertEqual(ids, [], entrada)


if __name__ == "__main__":
    unittest.main()
