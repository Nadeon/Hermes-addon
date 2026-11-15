"""Hermes — Tools MCP de los usuarios de Home Assistant (spec 021, tramo b).

Cuatro tools de la familia `users` (CAP-056 de la 008):

- `ha_list_users`: los usuarios con su papel, por `config/auth/list`.
- `ha_create_user`: crea un usuario SIN credenciales (`config/auth/create`).
- `ha_update_user`: nombre, activo, grupo y solo-local (`config/auth/update`).
- `ha_delete_user`: borra un usuario (`config/auth/delete`).

Las tres que escriben confirman siempre en dos pasos.

POR QUÉ NINGUNA MANEJA CREDENCIALES
-----------------------------------
Una contraseña o un token en manos de un cliente MCP es una cuenta de la casa
fuera de la casa. Ninguna tool acepta contraseñas, nombres de acceso ni
tokens, y lo que devuelve HA se copia campo a campo de una lista cerrada: de
`credentials` solo sale el tipo, y cualquier clave de más que mande HA
(`refresh_tokens`, una credencial con datos) se queda fuera. Dar usuario y
contraseña (`config/auth_provider/homeassistant/*`) sigue `deny` en la tabla
(clase D, D-01 de la 008) y es la duda D-27 del programa.

POR QUÉ PROTECCIONES DE HERMES ENCIMA DE LAS DE HA (research R-4)
------------------------------------------------------------------
HA rechaza borrarse a uno mismo, borrar o tocar a los de sistema y borrar o
desactivar al propietario, pero deja renombrar al propietario, quitarle
grupos, desactivar al usuario por el que entra Hermes o quitarle el grupo de
administrador (cortaría a Hermes) y quitar el último administrador. Hermes
protege: el propietario, el usuario de Hermes (el de `auth/current_user` de
su conexión), los de sistema y el último administrador activo. Se comprueba
en la vista previa y otra vez al confirmar, releyendo los usuarios de HA,
antes de llamar a nada; si no se puede leer quién es Hermes, no se escribe
(fail-closed). `auth/current_user` se usa solo por dentro: su entrada de la
tabla sigue `deny` para la genérica (es la identidad del propio Hermes).

ADMINISTRADOR
-------------
El modelo de HA (`homeassistant/auth/models.py`, `User.is_admin`): el
propietario siempre; el resto, activo y en `system-admin`. Para el recuento
de administradores activos no cuentan los de sistema (son de HA, no de la
casa) ni los inactivos.

PRIVACIDAD (principio VIII)
---------------------------
El log solo lleva el nombre de la tool, el paso, el resultado y, en las
escrituras, el `user_id` (decisión del supervisor, para poder auditar a quién
se tocó). Nunca nombres ni nombres de acceso. El fichero del token guarda la
huella del estado y `{"result": "ok"}`.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    ESTADO_CAMBIADO,
    complete_confirmation_token,
    create_confirmation_token,
    redact_secrets,
    resolve_confirmation_token,
)
from hermes.tools._common import (
    _LIMIT_HINT,
    ajustar_lista_a_bytes,
    requires_ready,
    sobre_de_lista,
)

logger = structlog.get_logger(__name__)

TOOLS = ("ha_list_users", "ha_create_user", "ha_update_user", "ha_delete_user")
ESCRITURAS = ("config/auth/create", "config/auth/update", "config/auth/delete")
GRUPOS = ("system-admin", "system-users", "system-read-only")
_ADMIN = "system-admin"
_USER_ID = re.compile(r"^[0-9a-f]{32}$")
_NOMBRE_MAX = 100

_CREDENCIALES = (
    "none: this user cannot log in until a username and password are added to it. "
    "Hermes never handles passwords. Home Assistant's API can add them to an existing "
    "user, but Hermes has not verified that the Home Assistant interface offers it for "
    "a user created without them; if it does not, delete this user and create it from "
    "Settings > People instead."
)
_IRREVERSIBLE = ("The user, their credentials and their sessions are deleted; this "
                 "cannot be undone. Linked persons stay, without a user.")

# Errores de HA que se explican (research R-4): el código y el detalle de HA
# van siempre; esto dice qué significa para quien lo lee.
_EXPLICACIONES = {
    "no_delete_self": "Home Assistant does not let a user delete the account it is connected with.",
    "cannot_delete_owner": "Home Assistant does not let anyone delete the owner.",
    "cannot_deactivate_owner": "Home Assistant does not let anyone deactivate the owner.",
    "cannot_modify_system_generated": "System users belong to Home Assistant and cannot be changed.",
    "not_found": "The user no longer exists in Home Assistant.",
}


class _Ilegible(Exception):
    """No se pudo leer lo necesario para decidir (fail-closed)."""

    def __init__(self, exc: HAConnectionError) -> None:
        super().__init__(str(exc))
        self.exc = exc


def _invalido(tool: str, campo: str, detalle: str) -> dict[str, Any]:
    logger.info(f"{tool}_failed", error="invalid_argument", field=campo)
    return {"error": "invalid_argument", "field": campo, "detail": detalle}


def _error_ha(tool: str, exc: HAConnectionError, **log: Any) -> dict[str, Any]:
    """Error de HA redactado y traducido (FR-020)."""
    logger.warning(f"{tool}_failed", error=exc.code or "connection", **log)
    detalle = redact_secrets(str(exc))
    if exc.code is None:
        return {"error": detalle}
    if exc.code == "unknown_command":
        from hermes.command_table import TABLE_HA_CORE
        return {
            "error": "unsupported_by_ha_version",
            "detail": ("The installed Home Assistant does not know this command; "
                       f"Hermes' table is for {TABLE_HA_CORE}."),
            "ha_code": exc.code,
            "table_ha_core": TABLE_HA_CORE,
        }
    out: dict[str, Any] = {"error": "ha_error", "ha_code": exc.code, "detail": detalle}
    if exc.code in _EXPLICACIONES:
        out["explanation"] = _EXPLICACIONES[exc.code]
    return out


def _no_disponible(tool: str, exc: HAConnectionError, **log: Any) -> dict[str, Any]:
    if exc.code == "unknown_command":
        return _error_ha(tool, exc, **log)
    logger.warning(f"{tool}_failed", error="preview_unavailable",
                   code=exc.code or "connection", **log)
    return {
        "error": "preview_unavailable",
        "detail": ("Hermes could not read the users or which user it connects as, so it "
                   "cannot check the protections; nothing was done. "
                   + redact_secrets(str(exc))),
    }


def _es_admin(u: dict[str, Any]) -> bool:
    return bool(u.get("is_owner")) or (
        bool(u.get("is_active")) and _ADMIN in (u.get("group_ids") or []))


def _ficha(raw: Any, hermes_id: str | None) -> dict[str, Any]:
    """Un usuario de HA, campo a campo de una lista cerrada.

    Lo que no está aquí no sale, mande HA lo que mande: de `credentials`
    solo el tipo (FR-012). `is_hermes` es `None` si no se sabe quién es Hermes.
    """
    u = raw if isinstance(raw, dict) else {}
    grupos = [g for g in (u.get("group_ids") or []) if isinstance(g, str)]
    tipos = sorted({c.get("type") for c in (u.get("credentials") or [])
                    if isinstance(c, dict) and isinstance(c.get("type"), str)})
    nombre_acceso = u.get("username")
    ficha = {
        "id": u.get("id") if isinstance(u.get("id"), str) else None,
        "name": u.get("name") if isinstance(u.get("name"), str) else None,
        "username": nombre_acceso if isinstance(nombre_acceso, str) else None,
        "is_owner": u.get("is_owner") is True,
        "is_active": u.get("is_active") is True,
        "is_admin": False,
        "local_only": u.get("local_only") is True,
        "system_generated": u.get("system_generated") is True,
        "group_ids": grupos,
        "credential_types": tipos,
        "is_hermes": None if hermes_id is None else u.get("id") == hermes_id,
    }
    ficha["is_admin"] = _es_admin(ficha)
    return ficha


def _admins_activos(usuarios: list[dict[str, Any]]) -> int:
    return sum(1 for u in usuarios
               if not u["system_generated"] and u["is_active"] and u["is_admin"])


def _protecciones(objetivo: dict[str, Any], hermes_id: str) -> list[str]:
    """Todos los motivos por los que un usuario no se toca (FR-008)."""
    motivos = []
    if objetivo["is_owner"]:
        motivos.append("owner")
    if objetivo["id"] == hermes_id:
        motivos.append("hermes")
    if objetivo["system_generated"]:
        motivos.append("system_generated")
    return motivos


def _deja_sin_admin(usuarios: list[dict[str, Any]], objetivo: dict[str, Any],
                    despues: dict[str, Any] | None) -> tuple[bool, int, int]:
    """`(último_admin, antes, después)` al cambiar `objetivo` por `despues`
    (`None`: borrado). Solo es «último administrador» si el cambio le quita a
    la casa su último administrador activo; renombrarlo no."""
    antes = _admins_activos(usuarios)
    resto = [u for u in usuarios if u["id"] != objetivo["id"]]
    despues_n = _admins_activos(resto + ([despues] if despues is not None else []))
    return antes > 0 and despues_n == 0, antes, despues_n


def _ultimo_admin(tool: str, user_id: str, **log: Any) -> dict[str, Any]:
    logger.warning(f"{tool}_failed", error="last_admin", user_id=user_id, **log)
    return {
        "error": "last_admin",
        "user_id": user_id,
        "detail": ("This would leave Home Assistant without an active administrator; "
                   "nothing was done."),
    }


def _protegido(tool: str, user_id: str, motivos: list[str], **log: Any) -> dict[str, Any]:
    logger.warning(f"{tool}_failed", error="protected_user", user_id=user_id,
                   reasons=motivos, **log)
    return {
        "error": "protected_user",
        "user_id": user_id,
        "reasons": motivos,
        "detail": ("Hermes does not change or delete the owner, the user it connects as, "
                   "system users or the last active administrator; nothing was done."),
    }


async def _leer(ha_client: HAClient) -> tuple[list[dict[str, Any]], str]:
    """Usuarios (fichas) y el id del usuario de Hermes; `_Ilegible` si falla."""
    try:
        actual: Any = await ha_client.ws_send({"type": "auth/current_user"})
        hermes_id = actual.get("id") if isinstance(actual, dict) else None
        if not isinstance(hermes_id, str) or not hermes_id:
            raise HAConnectionError("unexpected response from auth/current_user")
        raw: Any = await ha_client.ws_send({"type": "config/auth/list"})
        if not isinstance(raw, list):
            raise HAConnectionError("unexpected response from config/auth/list")
    except HAConnectionError as exc:
        raise _Ilegible(exc) from exc
    return [_ficha(u, hermes_id) for u in raw], hermes_id


def _validar_nombre(tool: str, name: Any) -> dict[str, Any] | None:
    if (not isinstance(name, str) or not name.strip() or len(name) > _NOMBRE_MAX
            or "\n" in name or "\r" in name):
        return _invalido(tool, "name",
                         f"must be a non-empty text of at most {_NOMBRE_MAX} characters, "
                         "on one line")
    return None


def _validar_grupo(tool: str, group: Any) -> dict[str, Any] | None:
    if group not in GRUPOS:
        return _invalido(tool, "group", "must be one of: " + ", ".join(GRUPOS))
    return None


def _validar_id(tool: str, user_id: Any) -> dict[str, Any] | None:
    if not isinstance(user_id, str) or not _USER_ID.match(user_id):
        return _invalido(tool, "user_id",
                         "must be a Home Assistant user id (32 lowercase hex characters, "
                         "from ha_list_users)")
    return None


def _resumen(u: dict[str, Any]) -> dict[str, Any]:
    return {"id": u["id"], "name": u["name"], "is_admin": u["is_admin"],
            "is_active": u["is_active"]}


def _no_encontrado(tool: str, user_id: str) -> dict[str, Any]:
    logger.info(f"{tool}_failed", error="not_found", user_id=user_id)
    return {"error": "not_found", "missing": [user_id]}


async def _token_valido(tool: str, token: str, args: dict[str, Any], estado: Any,
                        **log: Any) -> dict[str, Any] | None:
    valido, error, _ = await resolve_confirmation_token(token, tool, args, estado=estado)
    if valido:
        return None
    logger.warning(f"{tool}_failed", step="confirm",
                   error="state_changed" if error == ESTADO_CAMBIADO else "token_invalid",
                   **log)
    return {"error": error}


def register(mcp: object, ha_client: HAClient, *, response_max_bytes: int) -> None:
    """Registra las tools de usuarios."""

    ready = requires_ready(ha_client)

    # ── ha_list_users ─────────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_users(include_system: bool = False) -> object:
        """List Home Assistant users (Settings > People > Users) and their role.

        Each user: id, name, username (login name, if they have one), is_owner,
        is_active, is_admin (the owner, or active and in "system-admin"),
        local_only, system_generated, group_ids, credential_types (only the
        type, e.g. "homeassistant") and is_hermes (the user Hermes connects
        as; in an app it is the Supervisor's system user). Never passwords or
        tokens. Sessions cannot be listed: Home Assistant only gives those of
        the connection's own user. Changes nothing.

        Args:
            include_system: Also list system users (created by Home Assistant
                itself). The user Hermes connects as is always listed.

        Returns:
            {"active_admins": active non-system administrators,
             "hermes_user_known": false if Hermes could not tell which user it
             is (then is_hermes is null and system users are hidden),
             "count", "items", "truncated"} ordered by name.
        """
        tool = "ha_list_users"
        if not isinstance(include_system, bool):
            return _invalido(tool, "include_system", "must be true or false")
        try:
            raw: Any = await ha_client.ws_send({"type": "config/auth/list"})
            if not isinstance(raw, list):
                raise HAConnectionError("unexpected response from config/auth/list")
        except HAConnectionError as exc:
            return _error_ha(tool, exc)
        # Saber quién es Hermes es un extra en la lectura: si falla, se dice y
        # se lista igual (las escrituras, en cambio, no siguen).
        hermes_id: str | None
        try:
            actual: Any = await ha_client.ws_send({"type": "auth/current_user"})
            hermes_id = actual.get("id") if isinstance(actual, dict) else None
            if not isinstance(hermes_id, str) or not hermes_id:
                hermes_id = None
        except HAConnectionError:
            hermes_id = None

        usuarios = [_ficha(u, hermes_id) for u in raw]
        activos = _admins_activos(usuarios)
        items = sorted(
            (u for u in usuarios
             if include_system or not u["system_generated"] or u["is_hermes"]),
            key=lambda u: ((u["name"] or "").casefold(), u["id"] or ""),
        )

        def construir(lista: list[Any], recortada: bool) -> dict[str, Any]:
            out = sobre_de_lista(lista, truncated=recortada, active_admins=activos,
                                 hermes_user_known=hermes_id is not None)
            if recortada:
                out["_response_limit"] = {
                    "list": "items", "returned": len(lista), "total": len(items),
                    "max_bytes": response_max_bytes, "hint": _LIMIT_HINT,
                }
            return out

        respuesta = ajustar_lista_a_bytes(items, construir, response_max_bytes)
        logger.info(f"{tool}_ok", count=respuesta["count"], include_system=include_system,
                    hermes_user_known=hermes_id is not None)
        return respuesta

    # ── ha_create_user ────────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_create_user(
        name: str,
        group: str = "system-users",
        local_only: bool = False,
        confirmation_token: str | None = None,
    ) -> object:
        """Create a Home Assistant user WITHOUT credentials. Two steps.

        Without confirmation_token returns a preview (name, group, whether it
        grants admin, users with the same name) and a token; repeat the same
        call with the token to create it. The new user has no username or
        password, so it cannot log in until they are added to it: Hermes
        never handles passwords, and the preview says what that means in
        Home Assistant.

        Args:
            name: Display name (1-100 characters, one line).
            group: "system-users" (default), "system-admin" (administrator)
                or "system-read-only".
            local_only: Only allow logging in from the local network.
            confirmation_token: Token from the preview call.

        Returns:
            Preview + token; {"result": "ok", "user": {...as ha_list_users}};
            or {"error": ...} (preview_unavailable if Hermes cannot read the
            users or which user it connects as).
        """
        tool = "ha_create_user"
        error = (_validar_nombre(tool, name) or _validar_grupo(tool, group)
                 or (None if isinstance(local_only, bool)
                     else _invalido(tool, "local_only", "must be true or false")))
        if error is not None:
            return error
        args = {"name": name, "group": group, "local_only": local_only}
        paso = "confirm" if confirmation_token else "preview"
        try:
            usuarios, hermes_id = await _leer(ha_client)
        except _Ilegible as e:
            return _no_disponible(tool, e.exc, step=paso)
        clave = name.strip().casefold()
        mismo_nombre = sorted(u["id"] for u in usuarios
                              if (u["name"] or "").strip().casefold() == clave)
        estado = {"same_name": mismo_nombre}

        if not confirmation_token:
            preview = {
                "action": "create_user",
                "name": name,
                "group": group,
                "local_only": local_only,
                "grants_admin": group == _ADMIN,
                "credentials": _CREDENCIALES,
                "same_name": mismo_nombre,
            }
            logger.info(f"{tool}_ok", step="preview")
            return await create_confirmation_token(tool, args, preview=preview, estado=estado)

        fallo = await _token_valido(tool, confirmation_token, args, estado)
        if fallo is not None:
            return fallo
        try:
            r: Any = await ha_client.ws_send({"type": "config/auth/create", "name": name,
                                              "group_ids": [group], "local_only": local_only})
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False,
                                              error=exc.code or "connection")
            return _error_ha(tool, exc, step="confirm")
        ficha = _ficha(r.get("user") if isinstance(r, dict) else None, hermes_id)
        await complete_confirmation_token(confirmation_token, success=True,
                                          result={"result": "ok"})
        logger.info(f"{tool}_ok", step="confirm", user_id=ficha["id"])
        return {"result": "ok", "user": ficha}

    # ── ha_update_user ────────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_update_user(
        user_id: str,
        name: str | None = None,
        is_active: bool | None = None,
        group: str | None = None,
        local_only: bool | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Change a Home Assistant user's name, active state, group or local_only. Two steps.

        Without confirmation_token returns a preview (who, before and after,
        whether it grants or removes admin, deactivates them or restricts them
        to the local network, and active administrators before and after) and
        a token; repeat the same call with the token to apply. Only the fields
        you pass change; group replaces the user's groups. Deactivating a
        user stops them from logging in. Hermes never changes the owner, the
        user it connects as or system users, and never leaves Home Assistant
        without an active administrator (protected_user / last_admin). If
        nothing would change, {"result": "no_changes"} and no token.

        Args:
            user_id: User id (from ha_list_users).
            name: New display name (1-100 characters, one line).
            is_active: false deactivates the user, true activates them.
            group: "system-admin", "system-users" or "system-read-only".
            local_only: Only allow logging in from the local network.
            confirmation_token: Token from the preview call.

        Returns:
            Preview + token; {"result": "ok", "user": {...as ha_list_users}};
            {"result": "no_changes"}; or {"error": ...}.
        """
        tool = "ha_update_user"
        error = _validar_id(tool, user_id)
        if error is None and name is not None:
            error = _validar_nombre(tool, name)
        if error is None and group is not None:
            error = _validar_grupo(tool, group)
        for campo, valor in (("is_active", is_active), ("local_only", local_only)):
            if error is None and valor is not None and not isinstance(valor, bool):
                error = _invalido(tool, campo, "must be true or false")
        pedidos = {k: v for k, v in (("name", name), ("is_active", is_active),
                                     ("group", group), ("local_only", local_only))
                   if v is not None}
        if error is None and not pedidos:
            error = _invalido(tool, "fields", "give at least one field to change")
        if error is not None:
            return error
        args = {"user_id": user_id, **{k: None for k in ("name", "is_active", "group",
                                                          "local_only")}, **pedidos}
        paso = "confirm" if confirmation_token else "preview"

        # Se lee y se comprueba igual en los dos pasos: al confirmar, con lo
        # que hay AHORA en HA (alguien pudo cambiar al usuario, quién es
        # Hermes o los administradores en los 60 s del token).
        try:
            usuarios, hermes_id = await _leer(ha_client)
        except _Ilegible as e:
            return _no_disponible(tool, e.exc, step=paso, user_id=user_id)
        objetivo = next((u for u in usuarios if u["id"] == user_id), None)
        if objetivo is None:
            return _no_encontrado(tool, user_id)
        motivos = _protecciones(objetivo, hermes_id)
        if motivos:
            return _protegido(tool, user_id, motivos, step=paso)

        despues = dict(objetivo)
        if "name" in pedidos:
            despues["name"] = name
        if "is_active" in pedidos:
            despues["is_active"] = is_active
        if "group" in pedidos:
            despues["group_ids"] = [group]
        if "local_only" in pedidos:
            despues["local_only"] = local_only
        despues["is_admin"] = _es_admin(despues)
        cambios = {
            c: {"before": objetivo[c], "after": despues[c]}
            for c in ("name", "is_active", "group_ids", "local_only")
            if objetivo[c] != despues[c]
        }
        if not cambios:
            logger.info(f"{tool}_ok", step=paso, result="no_changes", user_id=user_id)
            return {"result": "no_changes"}
        ultimo, antes_n, despues_n = _deja_sin_admin(usuarios, objetivo, despues)
        if ultimo:
            return _ultimo_admin(tool, user_id, step=paso)
        estado = {"user": objetivo, "hermes": hermes_id, "active_admins": antes_n}

        if not confirmation_token:
            preview = {
                "action": "update_user",
                "user": _resumen(objetivo),
                "changes": cambios,
                "grants_admin": not objetivo["is_admin"] and despues["is_admin"],
                "removes_admin": objetivo["is_admin"] and not despues["is_admin"],
                "deactivates": objetivo["is_active"] and not despues["is_active"],
                "restricts_remote": not objetivo["local_only"] and despues["local_only"],
                "active_admins": {"before": antes_n, "after": despues_n},
            }
            logger.info(f"{tool}_ok", step="preview", user_id=user_id, fields=sorted(cambios))
            return await create_confirmation_token(tool, args, preview=preview, estado=estado)

        fallo = await _token_valido(tool, confirmation_token, args, estado, user_id=user_id)
        if fallo is not None:
            return fallo
        carga: dict[str, Any] = {"type": "config/auth/update", "user_id": user_id}
        for k, v in pedidos.items():
            if k == "group":
                carga["group_ids"] = [v]
            else:
                carga[k] = v
        try:
            r: Any = await ha_client.ws_send(carga)
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False,
                                              error=exc.code or "connection")
            return _error_ha(tool, exc, step="confirm", user_id=user_id)
        await complete_confirmation_token(confirmation_token, success=True,
                                          result={"result": "ok"})
        logger.info(f"{tool}_ok", step="confirm", user_id=user_id, fields=sorted(cambios))
        return {"result": "ok",
                "user": _ficha(r.get("user") if isinstance(r, dict) else None, hermes_id)}

    # ── ha_delete_user ────────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_delete_user(user_id: str, confirmation_token: str | None = None) -> object:
        """Delete a Home Assistant user. Two steps; cannot be undone.

        Without confirmation_token returns a preview (who, whether they are
        an administrator, the persons linked to them, active administrators
        before and after) and a token; repeat the same call with the token to
        delete. Their credentials and sessions are deleted too; a linked
        person stays, without a user. Hermes never deletes the owner, the
        user it connects as, system users or the last active administrator
        (protected_user / last_admin).

        Args:
            user_id: User id (from ha_list_users).
            confirmation_token: Token from the preview call.

        Returns:
            Preview + token; {"result": "ok", "deleted": user_id}; or
            {"error": ...}.
        """
        tool = "ha_delete_user"
        error = _validar_id(tool, user_id)
        if error is not None:
            return error
        args = {"user_id": user_id}
        paso = "confirm" if confirmation_token else "preview"
        try:
            usuarios, hermes_id = await _leer(ha_client)
        except _Ilegible as e:
            return _no_disponible(tool, e.exc, step=paso, user_id=user_id)
        objetivo = next((u for u in usuarios if u["id"] == user_id), None)
        if objetivo is None:
            return _no_encontrado(tool, user_id)
        motivos = _protecciones(objetivo, hermes_id)
        if motivos:
            return _protegido(tool, user_id, motivos, step=paso)
        ultimo, antes_n, despues_n = _deja_sin_admin(usuarios, objetivo, None)
        if ultimo:
            return _ultimo_admin(tool, user_id, step=paso)
        estado = {"user": objetivo, "hermes": hermes_id, "active_admins": antes_n}

        if not confirmation_token:
            try:
                personas = await _personas_vinculadas(ha_client, user_id)
            except HAConnectionError as exc:
                return _no_disponible(tool, exc, step=paso, user_id=user_id)
            preview = {
                "action": "delete_user",
                "user": _resumen(objetivo),
                "linked_persons": personas,
                "irreversible": _IRREVERSIBLE,
                "active_admins": {"before": antes_n, "after": despues_n},
            }
            logger.info(f"{tool}_ok", step="preview", user_id=user_id)
            return await create_confirmation_token(tool, args, preview=preview, estado=estado)

        fallo = await _token_valido(tool, confirmation_token, args, estado, user_id=user_id)
        if fallo is not None:
            return fallo
        try:
            await ha_client.ws_send({"type": "config/auth/delete", "user_id": user_id})
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False,
                                              error=exc.code or "connection")
            return _error_ha(tool, exc, step="confirm", user_id=user_id)
        await complete_confirmation_token(confirmation_token, success=True,
                                          result={"result": "ok"})
        logger.info(f"{tool}_ok", step="confirm", user_id=user_id)
        return {"result": "ok", "deleted": user_id}


async def _personas_vinculadas(ha_client: HAClient, user_id: str) -> list[dict[str, Any]]:
    """Personas (de almacenamiento y de YAML) con ese usuario.

    `person` quita el `user_id` de la persona al borrarse el usuario
    (`_handle_user_removed`): la vista previa lo dice. Sin la integración
    `person` (`unknown_command`) no hay personas que vincular.
    """
    try:
        raw: Any = await ha_client.ws_send({"type": "person/list"})
    except HAConnectionError as exc:
        if exc.code == "unknown_command":
            return []
        raise
    if not isinstance(raw, dict):
        raise HAConnectionError("unexpected response from person/list")
    personas = [p for clave in ("storage", "config")
                for p in (raw.get(clave) or []) if isinstance(p, dict)]
    return [{"id": p.get("id"), "name": p.get("name")}
            for p in personas if p.get("user_id") == user_id]
