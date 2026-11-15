"""Hermes — Restaurar un backup con la integración `backup` de HA (spec 031, tramo 3).

Una tool de la familia `backup_integration` (CAP-057 de la 008):
`ha_restore_backup`, con `backup/restore`. Ese comando no empieza por
`hassio/` ni `supervisor/`: el proxy WebSocket del Supervisor lo deja pasar
(DV-1, `TestProxyDelSupervisor`).

POR QUÉ UNA VISTA PREVIA TAN COMPLETA
-------------------------------------
Restaurar sustituye lo que se elija por su estado en la fecha del backup y
reinicia Core: lo hecho desde entonces se pierde. La vista previa enseña al
menos lo que la de `sv_restore_backup_full` (FR-007): el backup, la ubicación
elegida con su cifrado, de dónde sale la contraseña (nunca el valor), qué se
sobrescribe (cada app con su versión, cada carpeta) y qué hay en el backup
que no se restaura. El token ata los argumentos (también `password`: desde la
019 el `action_hash` es un HMAC con una clave del proceso, así que el fichero
del token no permite atacarla sin conexión) y la huella del backup en esa
ubicación (estado atado de la 018): si el backup cambia en los 60 s del
token, no se restaura (compromiso de la 011).

POR QUÉ `restore_started`
-------------------------
`backup/restore` no responde hasta terminar y, si se restaura la
configuración, Core se reinicia y la conexión cae. Sin respuesta en el plazo,
o con la conexión caída DESPUÉS de enviar la orden (`HAConnectionError.sent`,
research R-6), la restauración puede estar en marcha: se responde
`restore_started` con cómo comprobarlo, nunca `completed` (principio V). Si la
orden no llegó a salir, es un error y el token falla.

LA CLAVE DE CIFRADO
-------------------
Sin `password`, un backup protegido se descifra con la clave de los backups
de HA (la del kit de emergencia, `backup_key.py`). Se lee en cada llamada
solo para saber si existe y, al confirmar, para mandarla a HA. Nunca entra en
los argumentos del token, en su estado (que lleva `password_source`), en la
vista previa, en la respuesta, en un error ni en el log.
"""

from __future__ import annotations

from typing import Any

import structlog

from hermes.backup_key import leer_clave_de_backups, por_que_sin_clave, sin_secretos
from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes.ha import HAClient, HAConnectionError
from hermes.identifiers import InvalidIdentifier, validate_identifier
from hermes.security import (
    ESTADO_CAMBIADO,
    complete_confirmation_token,
    create_confirmation_token,
    redact_secrets,
    resolve_confirmation_token,
)
from hermes.tools import ha_backup_settings as _s
from hermes.tools import ha_backups as _hb
from hermes.tools._common import requires_ready, tam_json
from hermes.tools.addons import es_hermes

logger = structlog.get_logger(__name__)

# Plazo de la orden (research R-6): lo que HA tarde de más es una
# restauración en marcha, no un error.
_PLAZO_S = 30
_AGENTE_SUPERVISOR = "hassio.local"
# Preferencia sin `agent_id`: la ubicación local, sin descarga previa.
_LOCALES = ("hassio.local", "backup.local")
_MAX_PASSWORD = 1024
# Lo que añade el sobre del token (token, caducidad) a la vista previa.
_MARGEN_SOBRE = 256

_COMPROBAR = [
    "ha_list_backups: state returns to idle and last_action_event says completed "
    "or failed (once Home Assistant is back)",
    "sv_list_pending_jobs (with the Supervisor)",
]

# Fuentes de la contraseña (data-model sección 6).
PROVIDED = "provided"
CLAVE_HA = "backup_encryption_key"
CLAVE_HA_NO = "backup_encryption_key_unavailable"
NO_HACE_FALTA = "not_needed"


def _bool(valor: Any, campo: str) -> bool:
    if not isinstance(valor, bool):
        raise _s._Invalido(campo, "must be true or false")
    return valor


def _validar(
    backup_id: Any, agent_id: Any, restore_homeassistant: Any, restore_database: Any,
    restore_addons: Any, restore_folders: Any, password: Any,
) -> None:
    """Valida la forma antes de llamar a HA (esquema de `backup/restore`)."""
    try:
        validate_identifier(backup_id, field="backup_id")
    except InvalidIdentifier as exc:
        raise _s._Invalido("backup_id", str(exc)) from None
    if agent_id is not None and (not isinstance(agent_id, str)
                                 or not _s._AGENTE_RE.match(agent_id)):
        raise _s._Invalido("agent_id", "must be an agent id such as backup.local or "
                                       "hassio.local")
    _bool(restore_homeassistant, "restore_homeassistant")
    if restore_database is not None:
        _bool(restore_database, "restore_database")
    if restore_addons is not None:
        _s._lista_unica(restore_addons, "restore_addons", forma=_s._SLUG_RE)
    if restore_folders is not None:
        _s._lista_unica(restore_folders, "restore_folders", valores=_s._CARPETAS)
    if password is not None and (not isinstance(password, str)
                                 or not 1 <= len(password) <= _MAX_PASSWORD):
        # Sin el valor en el mensaje.
        raise _s._Invalido("password", f"must be a string of 1 to {_MAX_PASSWORD} characters")
    if restore_database is True and not restore_homeassistant:
        raise _s._Invalido("restore_database", "the database cannot be restored without "
                                               "Home Assistant (restore_homeassistant)")
    if not restore_homeassistant and not restore_addons and not restore_folders:
        raise _s._Invalido("restore_homeassistant", "nothing to restore")


def _slug(addon: Any) -> str | None:
    if isinstance(addon, dict):
        s = addon.get("slug")
        return s if isinstance(s, str) else None
    return addon if isinstance(addon, str) else None


def register(
    mcp: object,
    ha_client: HAClient,
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
) -> None:
    """Registra la tool de restaurar backups de HA."""

    ready = requires_ready(ha_client)
    # D-13 (cierre de seguridad): Hermes por el slug EXACTO de
    # `/addons/self/info`, con el sufijo `_hermes` de respaldo si no se puede
    # leer. Import aquí: `system_updates` importa `addons`.
    from hermes.tools.system_updates import lector_slug_propio

    slug_propio = lector_slug_propio(ha_client)

    async def _ws(payload: dict[str, Any]) -> tuple[Any, dict[str, Any] | None]:
        try:
            return await ha_client.ws_send(payload), None
        except HAConnectionError as exc:
            if getattr(exc, "code", None) == "unknown_command":
                return None, dict(_hb._NO_DISPONIBLE)
            return None, {"error": _s._error_ha(exc)}

    async def _rechazo_token(error: str) -> dict[str, Any]:
        if error == ESTADO_CAMBIADO:
            logger.warning("ha_restore_backup_error", code="state_changed")
            return {"error": "state_changed", "detail": error}
        logger.warning("ha_restore_backup_error", code="token_invalid")
        return {"error": error}

    async def _leer(
        backup_id: str, agent_id: str | None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """(backup por lista blanca, agentes disponibles con nombre, error)."""
        data, err = await _ws({"type": "backup/details", "backup_id": backup_id})
        if err:
            return None, err
        if not isinstance(data, dict):
            return None, {"error": "unexpected_response from backup/details"}
        crudo = data.get("backup")
        errores = _hb._errores_agentes(data.get("agent_errors"))
        if crudo is None:
            if errores:
                # Puede estar en el agente que no respondió: no se afirma
                # que no existe.
                return None, _hb._saneado({
                    "error": "backup_locations_unreadable",
                    "detail": "The backup was not found in the agents that answered, "
                              "and some agents could not be read. Nothing was done.",
                    "agent_errors": errores})
            return None, {"error": "not_found", "backup_id": backup_id}
        if not isinstance(crudo, dict):
            return None, {"error": "unexpected_response from backup/details"}
        if agent_id is not None and agent_id in errores:
            return None, _hb._saneado({
                "error": "backup_locations_unreadable",
                "detail": f"The agent {agent_id} could not be read. Nothing was done.",
                "agent_errors": errores})
        agentes, err = await _ws({"type": "backup/agents/info"})
        if err:
            return None, err
        if not isinstance(agentes, dict) or not isinstance(agentes.get("agents"), list):
            return None, {"error": "unexpected_response from backup/agents/info"}
        nombres = {a["agent_id"]: _hb._escalar(a.get("name"))
                   for a in agentes["agents"]
                   if isinstance(a, dict) and isinstance(a.get("agent_id"), str)}
        return {"backup": _hb._backup_permitido(crudo), "names": nombres,
                "unreadable": errores}, None

    @mcp.tool()
    @ready
    async def ha_restore_backup(
        backup_id: str,
        agent_id: str | None = None,
        restore_homeassistant: bool = True,
        restore_database: bool | None = None,
        restore_addons: list[str] | None = None,
        restore_folders: list[str] | None = None,
        password: str | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Restore a Home Assistant backup with the backup integration (HA 2025.1+).

        Two steps: without confirmation_token returns a preview (the backup,
        the location it is restored from and whether it is encrypted, where
        the password comes from, what is OVERWRITTEN and what in the backup
        is not restored) and a token; repeat the same call with the token to
        restore. Everything restored is replaced by its state on the backup
        date: changes made since then are LOST, and Home Assistant Core
        restarts. An encrypted backup without password uses Home Assistant's
        backup encryption key (the emergency kit one). The answer can be
        "restore_started" instead of "completed": HA did not answer before
        restarting; check it with ha_list_backups. Apps and folders need the
        Supervisor (agent hassio.local).

        Args:
            backup_id: Backup id from ha_list_backups.
            agent_id: Location to restore from; default the local one if the
                backup is there (otherwise "agent_id_required").
            restore_homeassistant: Restore Core's configuration (default true).
            restore_database: Restore the recorder database; default what the
                backup contains. With the Supervisor it must match it.
            restore_addons: App slugs to restore (they must be in the backup).
            restore_folders: Any of "share", "addons/local", "ssl", "media"
                that is in the backup.
            password: Backup password; omit it to use HA's backup key.
            confirmation_token: Token from the preview call.

        Returns:
            Preview + token; {"result": "completed"}; {"status":
            "restore_started", "check_with": [...]}; or {"error": ...}
            ("password_incorrect", "backup_not_found", "restore_failed",
            "not_in_backup", "agent_id_required", "state_changed").
        """
        tool = "ha_restore_backup"
        try:
            _validar(backup_id, agent_id, restore_homeassistant, restore_database,
                     restore_addons, restore_folders, password)
        except _s._Invalido as exc:
            logger.warning(f"{tool}_error", code="invalid_argument", field=exc.campo)
            return _s._invalido(exc)
        if (err := await _hb.comprobar_version_backup(ha_client)):
            return err

        leido, err = await _leer(backup_id, agent_id)
        if err:
            logger.warning(f"{tool}_error", code=err.get("error"))
            return err
        b = leido["backup"]
        ubicaciones = b.get("agents") or {}
        con_supervisor = _AGENTE_SUPERVISOR in leido["names"]

        # Ubicación (FR-007): la pedida, o la local, o que la elija el cliente.
        if agent_id is None:
            elegido = next((a for a in _LOCALES if a in ubicaciones), None)
            if elegido is None:
                logger.warning(f"{tool}_error", code="agent_id_required")
                return {"error": "agent_id_required",
                        "detail": "The backup is not in a local location; pass agent_id.",
                        "locations": sorted(ubicaciones)}
        else:
            if agent_id not in ubicaciones:
                logger.warning(f"{tool}_error", code="not_found", agent=agent_id)
                return {"error": "not_found", "backup_id": backup_id, "agent_id": agent_id,
                        "locations": sorted(ubicaciones)}
            elegido = agent_id

        db_incluida = b.get("database_included") is True
        restore_database_arg = restore_database
        if restore_database is None:
            # Por defecto, lo que trae el backup (solo con la configuración).
            restore_database = db_incluida and restore_homeassistant
        if con_supervisor and restore_homeassistant and restore_database != db_incluida:
            # HA con Supervisor lo rechaza («Restore database must match
            # backup»); sin Supervisor sí se admite.
            return _s._invalido(_s._Invalido(
                "restore_database", f"with the Supervisor it must match the backup "
                                    f"(database_included: {str(db_incluida).lower()})"))
        if (restore_addons or restore_folders) and not con_supervisor:
            campo = "restore_addons" if restore_addons else "restore_folders"
            return _s._invalido(_s._Invalido(
                campo, "apps and folders need the Supervisor (agent hassio.local), which is "
                       "not available on this installation (HA: 'Addons and folders are not "
                       "supported in core restore')"))
        slugs = [s for s in (_slug(a) for a in b.get("addons") or []) if s]
        carpetas = list(b.get("folders") or [])
        faltan = {
            k: v for k, v in (
                ("addons", [a for a in restore_addons or [] if a not in slugs]),
                ("folders", [f for f in restore_folders or [] if f not in carpetas]),
            ) if v
        }
        if restore_homeassistant and b.get("homeassistant_included") is not True:
            faltan["homeassistant"] = True
        if faltan:
            logger.warning(f"{tool}_error", code="not_in_backup", missing=sorted(faltan))
            return {"error": "not_in_backup", "missing": faltan,
                    "in_backup": {"homeassistant": b.get("homeassistant_included") is True,
                                  "addons": slugs, "folders": carpetas}}

        ubicacion = ubicaciones[elegido]
        protegido = ubicacion.get("protected") is True

        # De dónde sale la contraseña. La clave de HA se lee en cada llamada
        # (sin caché): en la vista previa, solo para saber si existe.
        clave: str | None = None
        motivo: str | None = None
        if password is not None:
            fuente = PROVIDED
        elif not protegido:
            fuente = NO_HACE_FALTA
        else:
            leida = await leer_clave_de_backups(ha_client)
            clave, motivo = leida.clave, leida.motivo
            fuente = CLAVE_HA if clave is not None else CLAVE_HA_NO

        fecha = b.get("date")
        datos_backup = {
            "backup_id": backup_id, "name": b.get("name"), "date": fecha,
            "homeassistant_version": b.get("homeassistant_version"),
        }
        datos_ubicacion = {
            "agent_id": elegido, "name": leido["names"].get(elegido),
            "kind": _s._kind(elegido), "protected": ubicacion.get("protected"),
            "size": ubicacion.get("size"),
        }
        # La huella (research R-8): el backup en esa ubicación, su contenido
        # y la fuente de la contraseña. NUNCA la clave ni `password` (que ya
        # ata el action_hash con HMAC).
        estado = {
            "backup": {**datos_backup, **datos_ubicacion,
                       "database_included": db_incluida,
                       "homeassistant_included": b.get("homeassistant_included") is True},
            "content": {"addons": b.get("addons") or [], "folders": carpetas},
            "password_source": fuente,
        }
        args = {
            "backup_id": backup_id, "agent_id": agent_id,
            "restore_homeassistant": restore_homeassistant,
            # El argumento tal como llegó (None si se omitió): el resuelto
            # sale del backup, que ya ata el estado.
            "restore_database": restore_database_arg,
            "restore_addons": restore_addons, "restore_folders": restore_folders,
            "password": password,
        }

        if not confirmation_token:
            avisos = [f"Everything restored is replaced by its state on {fecha}; changes "
                      f"made since then are LOST."]
            if restore_homeassistant:
                avisos.append("Home Assistant Core restarts during the restore.")
            if _s._kind(elegido) == "remote":
                avisos.append("The backup is downloaded from a remote location before "
                              "restoring.")
            if any([await es_hermes(a, slug_propio) for a in restore_addons or []]):
                avisos.append("Hermes itself is replaced by the version in the backup; if "
                              "that version is broken, recovery needs manual intervention.")
            if fuente == CLAVE_HA_NO:
                # Según el motivo (T064): «no tiene clave» solo si es verdad.
                avisos.append(f"The backup is encrypted and {por_que_sin_clave(motivo)}: "
                              f"the restore will fail unless you pass password.")
            if fuente == CLAVE_HA:
                avisos.append("The backup is decrypted with Home Assistant's backup "
                              "encryption key (the emergency kit one); if the backup was "
                              "made with an older key, pass that one as password.")
            if leido["unreadable"]:
                avisos.append("Some backup agents could not be read: "
                              + ", ".join(sorted(leido["unreadable"])) + ".")
            restaurar = set(restore_addons or [])
            preview = _hb._saneado({
                "action": "restore_backup",
                "backup": datos_backup,
                "location": {**datos_ubicacion,
                             "also_in": sorted(a for a in ubicaciones if a != elegido)},
                "overwrites": {
                    "homeassistant_configuration": restore_homeassistant,
                    "database": restore_database,
                    "addons": [a for a in b.get("addons") or [] if _slug(a) in restaurar],
                    "folders": [f for f in carpetas if f in (restore_folders or [])],
                },
                "not_restored": {
                    "homeassistant_configuration": (b.get("homeassistant_included") is True
                                                    and not restore_homeassistant),
                    "database": db_incluida and not restore_database,
                    "addons": [a for a in b.get("addons") or [] if _slug(a) not in restaurar],
                    "folders": [f for f in carpetas if f not in (restore_folders or [])],
                },
                "warnings": avisos,
            })
            # Después del saneado: `redact_structure` taparía cualquier clave
            # que contenga «password», y estos dos campos no son secretos
            # (dicen de dónde sale la contraseña, nunca su valor).
            preview["password_source"] = fuente
            if fuente == CLAVE_HA_NO:
                preview["password_source_reason"] = motivo
            # Una vista previa recortada haría aprobar algo que no se ha visto
            # entero (principio IV): sin token.
            if tam_json(preview) + _MARGEN_SOBRE > response_max_bytes:
                logger.warning(f"{tool}_error", code="response_too_large")
                return {"error": "response_too_large",
                        "detail": f"The restore preview does not fit in response_max_bytes "
                                  f"({response_max_bytes}); no token was issued. Raise "
                                  f"response_max_bytes or restore fewer apps."}
            logger.info(f"{tool}_preview", agent=elegido, password_source=fuente,
                        addons=len(restaurar), folders=len(restore_folders or []))
            return await create_confirmation_token(tool, args, preview=preview, estado=estado)

        ok, error, _ = await resolve_confirmation_token(
            confirmation_token, tool, args, estado=estado)
        if not ok:
            return await _rechazo_token(error)
        payload: dict[str, Any] = {
            "type": "backup/restore", "backup_id": backup_id, "agent_id": elegido,
            "restore_homeassistant": restore_homeassistant,
            "restore_database": restore_database,
        }
        if restore_addons is not None:
            payload["restore_addons"] = restore_addons
        if restore_folders is not None:
            payload["restore_folders"] = restore_folders
        secreto = password if password is not None else clave
        if secreto is not None:
            payload["password"] = secreto
        try:
            # La llamada que lleva la contraseña o la clave pasa por el único
            # punto que las tapa (T061): el error ya sale sin ellas.
            await sin_secretos(ha_client.ws_send(payload, timeout_seconds=_PLAZO_S),
                               password, clave)
        except HAConnectionError as exc:
            codigo = getattr(exc, "code", None)
            # Contrato de tres valores de `HAConnectionError.sent` (spec
            # 022): solo `True` dice que la orden salió y solo `False` que
            # no salió. `None` es «no se sabe o no aplica» (una respuesta de
            # error de HA): ni `restore_started` ni «nada cambió».
            enviada = getattr(exc, "sent", None)
            if codigo is None and enviada is True:
                # Sin respuesta tras enviar: puede estar restaurándose y Core
                # reiniciándose. No se reintenta ni se da por hecho.
                resultado = {
                    "status": "restore_started",
                    "detail": "The restore order was sent but Home Assistant did not answer "
                              "(it may be restoring and restarting). It is NOT confirmed as "
                              "completed.",
                    "check_with": list(_COMPROBAR),
                }
                await complete_confirmation_token(confirmation_token, success=True,
                                                  result=resultado)
                logger.warning(f"{tool}_started", agent=elegido)
                return resultado
            # `exc` ya viene sin la contraseña ni la clave (`sin_secretos`,
            # antes de redactar: la redacción podría partirlas y dejar un trozo).
            detalle = _hb._mascara_red(redact_secrets(str(exc)))
            if codigo == "password_incorrect":
                error_tool = {"error": "password_incorrect",
                              "detail": "Home Assistant rejected the password."}
                if fuente == CLAVE_HA:
                    error_tool["hint"] = ("It was Home Assistant's current backup key; the "
                                          "backup may be encrypted with an older key. Pass "
                                          "that one as password.")
            elif codigo == "backup_not_found":
                error_tool = {"error": "backup_not_found", "detail": detalle}
            elif codigo is None and enviada is False:
                # Seguro que no llegó a salir: nada cambió.
                error_tool = {"error": "ha_unreachable", "detail": detalle}
            else:
                error_tool = {"error": "restore_failed", "detail": detalle}
            await complete_confirmation_token(confirmation_token, success=False,
                                              error=error_tool["error"])
            logger.warning(f"{tool}_error", code=error_tool["error"])
            return error_tool
        finally:
            # La carga lleva la contraseña o la clave: no se queda más.
            payload.pop("password", None)
        resultado = {"result": "completed"}
        await complete_confirmation_token(confirmation_token, success=True, result=resultado)
        logger.info(f"{tool}_ok", agent=elegido, password_source=fuente)
        return resultado
