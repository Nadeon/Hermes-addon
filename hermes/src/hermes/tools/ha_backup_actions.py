"""Hermes — Crear y borrar backups con la integración `backup` de HA (spec 031, tramo 2).

Tres tools de la familia `backup_integration` (CAP-057 de la 008):

- `ha_create_backup`: un backup a medida (`backup/generate`) en los agentes
  que se elijan, cifrado con la clave de HA.
- `ha_create_automatic_backup`: un backup con los ajustes automáticos
  (`backup/generate_with_automatic_settings`); al terminar, HA aplica la
  retención y puede BORRAR backups automáticos antiguos.
- `ha_delete_backup`: borra un backup de TODAS sus ubicaciones
  (`backup/delete`).

Ninguno de esos comandos empieza por `hassio/` ni `supervisor/`: el proxy
WebSocket del Supervisor los deja pasar (DV-1, `TestProxyDelSupervisor`).

POR QUÉ CONFIRMAN LAS TRES
--------------------------
Crear un backup completo ocupa GB en cada agente y, en uno remoto, sube la
casa entera (con `secrets.yaml`) fuera; crear con los ajustes automáticos
dispara la retención, que borra; y borrar no tiene vuelta atrás. Por eso las
tres van en dos pasos y el token ata, además de los argumentos, la huella de
lo que enseñó la vista previa (estado atado de la 018): los agentes y su
cifrado al crear; la configuración y lo que la retención borraría al crear
con los ajustes automáticos; el backup, su contenido y TODAS sus ubicaciones
al borrar. Si algo cambia en los 60 s del token, no se ejecuta.

POR QUÉ BORRAR FALLA CERRADO SI UNA UBICACIÓN NO SE LEE
-------------------------------------------------------
`backup/delete` borra el backup de todos los agentes. Si un agente (un NAS o
la nube) no responde a `backup/details`, la vista previa no puede decir si el
backup está ahí ni qué se perdería: no se emite token (decisión del
supervisor del programa al validar la spec).

LA CLAVE DE CIFRADO
-------------------
`ha_create_backup` cifra con la clave de los backups de HA (la del kit de
emergencia, `backup_key.py`), sin aceptar ninguna contraseña del cliente. La
clave se lee en la vista previa solo para saber si existe, y otra vez en la
confirmación para mandarla a HA; nunca entra en los argumentos del token, en
su estado (que lleva `key_set`), en la vista previa, en la respuesta ni en el
log.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from hermes.backup_key import (
    HA_INALCANZABLE,
    SIN_CLAVE,
    leer_clave_de_backups,
    por_que_sin_clave,
    sin_secretos,
)
from hermes.backup_retention_estimate import POR_COPIAS, estimar_retencion
from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes.ha import HAClient, HAConnectionError
from hermes.identifiers import InvalidIdentifier, validate_identifier
from hermes.safety_retention import es_safety_backup_confirmado
from hermes.security import (
    ESTADO_CAMBIADO,
    complete_confirmation_token,
    create_confirmation_token,
    resolve_confirmation_token,
)
from hermes.tools import ha_backup_settings as _s
from hermes.tools import ha_backups as _hb
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)

_MAX_AGENTES = 10
_MAX_NOMBRE = 100
_AGENTE_SUPERVISOR = "hassio.local"
_SEGUIMIENTO = ("ha_list_backups (state returns to idle; last_action_event says "
                "completed or failed)")


def _protegido(config: dict[str, Any], agent_id: str) -> bool:
    """¿Cifra HA la copia de ese agente? Sin entrada en la configuración, sí:
    es el valor con el que HA crea la entrada del agente."""
    propio = (config.get("agents") or {}).get(agent_id) or {}
    return propio.get("protected") is not False


def _aviso_sin_cifrar(agent_id: str) -> str:
    return (f"A copy of the whole configuration, including secrets.yaml, is uploaded "
            f"UNENCRYPTED to {agent_id}.")


def _bool(valor: Any, campo: str) -> bool:
    if not isinstance(valor, bool):
        raise _s._Invalido(campo, "must be true or false")
    return valor


def _validar_crear(
    agent_ids: Any, include_homeassistant: Any, include_database: Any,
    include_addons: Any, include_all_addons: Any, include_folders: Any,
    name: Any, encrypt: Any,
) -> None:
    """Valida antes de llamar a HA (esquema de `backup/generate` de 2026.11.1)."""
    if not isinstance(agent_ids, list) or not 1 <= len(agent_ids) <= _MAX_AGENTES:
        raise _s._Invalido("agent_ids", f"must be a list of 1 to {_MAX_AGENTES} agent ids")
    _s._lista_unica(agent_ids, "agent_ids", forma=_s._AGENTE_RE)
    for campo, valor in (("include_homeassistant", include_homeassistant),
                         ("include_database", include_database),
                         ("include_all_addons", include_all_addons),
                         ("encrypt", encrypt)):
        _bool(valor, campo)
    if include_addons is not None:
        _s._lista_unica(include_addons, "include_addons", forma=_s._SLUG_RE)
    if include_folders is not None:
        _s._lista_unica(include_folders, "include_folders", valores=_s._CARPETAS)
    if include_all_addons and include_addons:
        raise _s._Invalido("include_addons", "include_all_addons already includes every app; "
                                             "do not pass include_addons with it")
    if name is not None and (not isinstance(name, str) or not 1 <= len(name.strip()) <= _MAX_NOMBRE):
        raise _s._Invalido("name", f"must be a string of 1 to {_MAX_NOMBRE} characters")
    if not include_homeassistant and not include_addons and not include_all_addons \
            and not include_folders:
        raise _s._Invalido("include_homeassistant", "nothing to back up")


def _contenido(include_homeassistant: bool, include_database: bool, addons: Any,
               all_addons: bool, folders: Any) -> dict[str, Any]:
    return {
        "homeassistant": include_homeassistant,
        # La base de datos va dentro de la configuración de Core.
        "database": include_homeassistant and include_database,
        "addons": "all" if all_addons else list(addons or []),
        "folders": list(folders or []),
    }


def _ubicaciones(backup: dict[str, Any]) -> list[dict[str, Any]]:
    """Ubicaciones del backup (lista blanca ya aplicada), ordenadas por id."""
    return [
        {"agent_id": aid, "kind": _s._kind(aid), "size": datos.get("size"),
         "protected": datos.get("protected")}
        for aid, datos in sorted((backup.get("agents") or {}).items())
    ]


def register(
    mcp: object,
    ha_client: HAClient,
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
) -> None:
    """Registra las tools de crear y borrar backups de HA."""

    ready = requires_ready(ha_client)

    async def _ws(payload: dict[str, Any]) -> tuple[Any, dict[str, Any] | None]:
        try:
            return await ha_client.ws_send(payload), None
        except HAConnectionError as exc:
            if getattr(exc, "code", None) == "unknown_command":
                return None, dict(_hb._NO_DISPONIBLE)
            return None, {"error": _s._error_ha(exc)}

    async def _agentes() -> tuple[list[str] | None, dict[str, Any] | None]:
        data, err = await _ws({"type": "backup/agents/info"})
        if err:
            return None, err
        if not isinstance(data, dict) or not isinstance(data.get("agents"), list):
            return None, {"error": "unexpected_response from backup/agents/info"}
        return [a["agent_id"] for a in data["agents"]
                if isinstance(a, dict) and isinstance(a.get("agent_id"), str)], None

    async def _config() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        data, err = await _ws({"type": "backup/config/info"})
        if err:
            return None, err
        config = data.get("config") if isinstance(data, dict) else None
        if not isinstance(config, dict):
            return None, {"error": "unexpected_response from backup/config/info"}
        # Lista blanca: la contraseña se queda fuera, solo `password_set`.
        return _hb._config_permitida(config), None

    async def _backups() -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
        data, err = await _ws({"type": "backup/info"})
        if err:
            return None, err
        if not isinstance(data, dict) or not isinstance(data.get("backups"), list):
            return None, {"error": "unexpected_response from backup/info"}
        return [_hb._backup_permitido(b) for b in data["backups"] if isinstance(b, dict)], None

    async def _rechazo_token(tool: str, error: str) -> dict[str, Any]:
        if error == ESTADO_CAMBIADO:
            logger.warning(f"{tool}_error", code="state_changed")
            return {"error": "state_changed", "detail": error}
        logger.warning(f"{tool}_error", code="token_invalid")
        return {"error": error}

    async def _fallo_ha(tool: str, token: str, exc: HAConnectionError) -> dict[str, Any]:
        detalle = _s._error_ha(exc)
        await complete_confirmation_token(token, success=False, error=detalle)
        logger.warning(f"{tool}_error", code=exc.code or "connection")
        return {"error": detalle}

    # ── ha_create_backup ──────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_create_backup(
        agent_ids: list[str],
        include_homeassistant: bool = True,
        include_database: bool = True,
        include_addons: list[str] | None = None,
        include_all_addons: bool = False,
        include_folders: list[str] | None = None,
        name: str | None = None,
        encrypt: bool = True,
        confirmation_token: str | None = None,
    ) -> object:
        """Create a Home Assistant backup with the backup integration (HA 2025.1+).

        Two steps: without confirmation_token returns a preview (what is
        saved, in which backup agents, and whether each copy is encrypted)
        and a token; repeat the same call with the token to start it. The
        backup runs in the background: the answer has backup_job_id; follow
        it with ha_list_backups. A full backup takes several GB in each agent,
        and a remote agent (such as the cloud) receives a copy of the whole
        configuration. encrypt uses Home Assistant's backup encryption key
        (the emergency kit one); no password is accepted, and without a key
        configured in HA, encrypt=true answers "no_encryption_key". An agent
        with protected=false stores its copy unencrypted (see
        ha_list_backup_agents). Apps and folders need the Supervisor
        (agent hassio.local).

        Args:
            agent_ids: 1-10 agent ids from ha_list_backup_agents.
            include_homeassistant: Include Core's configuration (default true).
            include_database: Include the recorder database (default true).
            include_addons: App slugs to include; not with include_all_addons.
            include_all_addons: Include every app (default false).
            include_folders: Any of "share", "addons/local", "ssl", "media".
            name: Backup name (1-100 characters); HA picks one if omitted.
            encrypt: Encrypt with HA's backup key (default true).
            confirmation_token: Token from the preview call.

        Returns:
            Preview + token; {"backup_job_id", "status": "started",
            "follow_with"}; or {"error": ...} ("state_changed" if the agents,
            their encryption or the key changed since the preview).
        """
        tool = "ha_create_backup"
        try:
            _validar_crear(agent_ids, include_homeassistant, include_database, include_addons,
                           include_all_addons, include_folders, name, encrypt)
        except _s._Invalido as exc:
            logger.warning(f"{tool}_error", code="invalid_argument", field=exc.campo)
            return _s._invalido(exc)
        if (err := await _hb.comprobar_version_backup(ha_client)):
            return err

        disponibles, err = await _agentes()
        if err:
            return err
        faltan = [a for a in agent_ids if a not in disponibles]
        if faltan:
            logger.warning(f"{tool}_error", code="unknown_agent", agents=faltan)
            return {"error": "unknown_agent", "agents": faltan, "available": disponibles}
        if _AGENTE_SUPERVISOR not in disponibles:
            # Core sin Supervisor: HA lo rechazaría a mitad de camino
            # («Addons and folders are not supported by core backup»,
            # «Home Assistant must be included in backup»).
            if include_addons or include_all_addons or include_folders:
                campo = "include_folders" if include_folders and not (
                    include_addons or include_all_addons) else "include_addons"
                return _s._invalido(_s._Invalido(
                    campo, "apps and folders need the Supervisor (agent hassio.local), "
                           "which is not available on this installation"))
            if not include_homeassistant:
                return _s._invalido(_s._Invalido(
                    "include_homeassistant", "without the Supervisor a backup must include "
                                             "Home Assistant"))
        config, err = await _config()
        if err:
            return err

        clave = None
        if encrypt:
            leida = await leer_clave_de_backups(ha_client)
            if leida.clave is None:
                logger.warning(f"{tool}_error", code="no_encryption_key", reason=leida.motivo)
                # El texto según el motivo (T064): si HA no respondió, no se
                # sabe si tiene clave y no se puede decir que no la tiene.
                if leida.motivo == SIN_CLAVE:
                    consejo = ("set up automatic backups in the Home Assistant UI, which "
                               "gives you the emergency kit")
                elif leida.motivo == HA_INALCANZABLE:
                    consejo = "retry when Home Assistant answers"
                else:
                    consejo = "check that the backup integration is loaded"
                return {"error": "no_encryption_key", "reason": leida.motivo,
                        "detail": f"{por_que_sin_clave(leida.motivo)} ({consejo}), or pass "
                                  f"encrypt=false."}
            clave = leida.clave

        cifrado = {a: encrypt and _protegido(config, a) for a in agent_ids}
        # La huella: los agentes disponibles, si cifra cada destino y si hay
        # clave. NUNCA la clave: el estado se guarda como hash en disco.
        estado = {"agents": sorted(disponibles), "encrypted": cifrado,
                  "key_set": clave is not None}
        args = {
            "agent_ids": agent_ids, "include_homeassistant": include_homeassistant,
            "include_database": include_database, "include_addons": include_addons,
            "include_all_addons": include_all_addons, "include_folders": include_folders,
            "name": name, "encrypt": encrypt,
        }

        if not confirmation_token:
            avisos = [_aviso_sin_cifrar(a) for a in agent_ids
                      if not cifrado[a] and _s._kind(a) == "remote"]
            if include_homeassistant and not include_database:
                avisos.append("The recorder database (history, statistics) is NOT included.")
            preview = _hb._saneado({
                "action": "create_backup",
                "name": name,
                "agents": [{"agent_id": a, "kind": _s._kind(a), "encrypted": cifrado[a]}
                           for a in agent_ids],
                "content": _contenido(include_homeassistant, include_database, include_addons,
                                      include_all_addons, include_folders),
                "warnings": avisos,
            })
            logger.info(f"{tool}_preview", agents=agent_ids, encrypt=encrypt)
            return await create_confirmation_token(tool, args, preview=preview, estado=estado)

        ok, error, _ = await resolve_confirmation_token(
            confirmation_token, tool, args, estado=estado)
        if not ok:
            return await _rechazo_token(tool, error)
        payload: dict[str, Any] = {
            "type": "backup/generate", "agent_ids": agent_ids,
            "include_homeassistant": include_homeassistant,
            "include_database": include_database,
            "include_all_addons": include_all_addons,
        }
        if include_addons is not None:
            payload["include_addons"] = include_addons
        if include_folders is not None:
            payload["include_folders"] = include_folders
        if name is not None:
            payload["name"] = name
        if clave is not None:
            payload["password"] = clave
        try:
            # La llamada que lleva la clave pasa por el único punto que la
            # tapa (T061): su error sale ya sin ella hacia la respuesta, el
            # log y el fichero del token.
            data = await sin_secretos(ha_client.ws_send(payload), clave)
        except HAConnectionError as exc:
            return await _fallo_ha(tool, confirmation_token, exc)
        finally:
            # La carga lleva la clave: no se queda más de lo necesario.
            payload.pop("password", None)
        job = data.get("backup_job_id") if isinstance(data, dict) else None
        resultado = {"backup_job_id": _hb._escalar(job), "status": "started",
                     "follow_with": _SEGUIMIENTO}
        await complete_confirmation_token(confirmation_token, success=True, result=resultado)
        logger.info(f"{tool}_ok", agents=agent_ids, encrypt=encrypt)
        return resultado

    # ── ha_create_automatic_backup ────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_create_automatic_backup(confirmation_token: str | None = None) -> object:
        """Create a backup now with Home Assistant's automatic backup settings (HA 2025.1+).

        Two steps: without confirmation_token returns a preview (agents,
        content, whether each copy is encrypted and an ESTIMATE of the
        automatic backups the retention would delete) and a token; repeat
        with the token to start it. When it finishes, HA applies the
        retention and may DELETE old automatic backups. Change the settings
        with ha_update_backup_config. Follow it with ha_list_backups.

        Returns:
            Preview + token; {"backup_job_id", "status": "started",
            "follow_with"}; or {"error": ...}
            ("automatic_backups_not_configured" without agents in the
            settings; "state_changed" if the settings, the backups or the
            available agents changed since the preview).
        """
        tool = "ha_create_automatic_backup"
        if (err := await _hb.comprobar_version_backup(ha_client)):
            return err
        config, err = await _config()
        if err:
            return err
        crear = config["create_backup"]
        destinos = crear.get("agent_ids") or []
        if not destinos:
            logger.warning(f"{tool}_error", code="automatic_backups_not_configured")
            return {"error": "automatic_backups_not_configured",
                    "detail": "The automatic backup settings have no backup agents; set "
                              "create_backup.agent_ids with ha_update_backup_config."}
        backups, err = await _backups()
        if err:
            return err
        # Solo la regla de copias: es la que HA aplica al terminar este
        # backup; la de días va por su cuenta, cada día.
        estimacion = [e for e in estimar_retencion(config, backups, datetime.now(timezone.utc))
                      if e["when"] == POR_COPIAS]
        ids_borrar = [e["backup_id"] for e in estimacion]
        # Los agentes se leen en los DOS pasos (T065): la vista previa dice
        # en qué destinos se guarda y cuáles se saltarán; si uno desaparece
        # (o vuelve) en los 60 s del token, el backup no saldría donde se
        # enseñó.
        disponibles, err = await _agentes()
        if err:
            return err
        estado = {"config": config, "would_delete": ids_borrar,
                  "available_agents": [a for a in destinos if a in disponibles]}

        if not confirmation_token:
            con_clave = bool(crear.get("password_set"))
            cifrado = {a: con_clave and _protegido(config, a) for a in destinos}
            avisos = [_aviso_sin_cifrar(a) for a in destinos
                      if not cifrado[a] and _s._kind(a) == "remote"]
            faltan = [a for a in destinos if a not in disponibles]
            if faltan:
                avisos.append("These agents are not available and will be skipped: "
                              + ", ".join(faltan) + ".")
            if not con_clave:
                avisos.append("No backup encryption key is configured: the backup is "
                              "NOT encrypted.")
            preview = _hb._saneado({
                "action": "create_automatic_backup",
                "name": crear.get("name"),
                "agents": [{"agent_id": a, "kind": _s._kind(a), "encrypted": cifrado[a]}
                           for a in destinos],
                "content": _contenido(True, crear.get("include_database") is not False,
                                      crear.get("include_addons"),
                                      crear.get("include_all_addons") is True,
                                      crear.get("include_folders")),
                "retention_effect": {
                    "estimate": True,
                    "detail": _s._ESTIMACION_DETALLE,
                    "would_delete": estimacion[:_s._MAX_WOULD_DELETE],
                    "truncated": len(estimacion) > _s._MAX_WOULD_DELETE,
                },
                "warnings": avisos,
            })
            logger.info(f"{tool}_preview", agents=destinos, would_delete=len(ids_borrar))
            return await create_confirmation_token(tool, {}, preview=preview, estado=estado)

        ok, error, _ = await resolve_confirmation_token(
            confirmation_token, tool, {}, estado=estado)
        if not ok:
            return await _rechazo_token(tool, error)
        try:
            data = await ha_client.ws_send({"type": "backup/generate_with_automatic_settings"})
        except HAConnectionError as exc:
            return await _fallo_ha(tool, confirmation_token, exc)
        job = data.get("backup_job_id") if isinstance(data, dict) else None
        resultado = {"backup_job_id": _hb._escalar(job), "status": "started",
                     "follow_with": _SEGUIMIENTO}
        await complete_confirmation_token(confirmation_token, success=True, result=resultado)
        logger.info(f"{tool}_ok", agents=destinos, would_delete=len(ids_borrar))
        return resultado

    # ── ha_delete_backup ──────────────────────────────────────────────────

    async def _lo_que_se_borra(
        backup_id: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """(vista y huella del backup en todas sus ubicaciones, error).

        Falla cerrado si un agente no se pudo leer: `backup/delete` borra de
        todos, y la vista previa no sabría si el backup está ahí.
        """
        data, err = await _ws({"type": "backup/details", "backup_id": backup_id})
        if err:
            return None, err
        if not isinstance(data, dict):
            return None, {"error": "unexpected_response from backup/details"}
        errores = _hb._errores_agentes(data.get("agent_errors"))
        if errores:
            return None, _hb._saneado({
                "error": "backup_locations_unreadable",
                "detail": "Some backup agents could not be read, so the preview cannot "
                          "say where this backup is or what would be lost. Nothing was "
                          "done; retry when they respond.",
                "agent_errors": errores,
            })
        crudo = data.get("backup")
        if crudo is None:
            return None, {"error": "not_found", "backup_id": backup_id}
        if not isinstance(crudo, dict):
            return None, {"error": "unexpected_response from backup/details"}
        b = _hb._backup_permitido(crudo)
        backups, err = await _backups()
        if err:
            return None, err
        con_config = [x["backup_id"] for x in backups if x.get("homeassistant_included") is True]
        unico_con_config = b.get("homeassistant_included") is True and con_config == [backup_id]
        ubicaciones = _ubicaciones(b)
        datos = {
            "backup": {
                "backup_id": backup_id,
                "name": b.get("name"),
                "date": b.get("date"),
                "homeassistant_version": b.get("homeassistant_version"),
                "automatic": b.get("with_automatic_settings") is True,
                "hermes_safety_backup": es_safety_backup_confirmado(backup_id),
            },
            "locations": ubicaciones,
            "lost": {
                "homeassistant_configuration": b.get("homeassistant_included") is True,
                "database": b.get("database_included") is True,
                "addons": b.get("addons") or [],
                "folders": b.get("folders") or [],
            },
            "only_backup_with_configuration": unico_con_config,
        }
        return datos, None

    @mcp.tool()
    @ready
    async def ha_delete_backup(backup_id: str, confirmation_token: str | None = None) -> object:
        """Delete a Home Assistant backup from ALL its locations (HA 2025.1+).

        Two steps: without confirmation_token returns a preview (the backup,
        its date, every location with its size and encryption, what it
        contains and is lost, and warnings) and a token; repeat with the
        token to delete it. Home Assistant deletes it from every backup agent
        (local, network storage, cloud); it cannot be undone. If an agent
        cannot be read, no token is given ("backup_locations_unreadable").

        Args:
            backup_id: Backup id from ha_list_backups.
            confirmation_token: Token from the preview call.

        Returns:
            Preview + token; {"result": "ok" | "partial", "deleted_from":
            [...], "failed": {agent_id: error}}; or {"error": ...}
            ("not_found"; "state_changed" if the backup or its locations
            changed since the preview).
        """
        tool = "ha_delete_backup"
        try:
            validate_identifier(backup_id, field="backup_id")
        except InvalidIdentifier as exc:
            logger.warning(f"{tool}_error", code="invalid_argument", field="backup_id")
            return {"error": "invalid_argument", "field": "backup_id", "detail": str(exc)}
        if (err := await _hb.comprobar_version_backup(ha_client)):
            return err
        datos, err = await _lo_que_se_borra(backup_id)
        if err:
            logger.warning(f"{tool}_error", code=err.get("error"))
            return err
        ubicaciones = [u["agent_id"] for u in datos["locations"]]
        # La huella es todo lo que enseña la vista previa: el backup, su
        # contenido y cada ubicación con su tamaño y su cifrado.
        estado = datos
        args = {"backup_id": backup_id}

        if not confirmation_token:
            avisos = ["The backup is deleted from EVERY location listed; this cannot be undone."]
            if datos["only_backup_with_configuration"]:
                avisos.append("This is the only backup that includes the Home Assistant "
                              "configuration.")
            if datos["backup"]["hermes_safety_backup"]:
                avisos.append("This is a Hermes safety backup (taken before a write to "
                              "/config).")
            preview = _hb._saneado({
                "action": "delete_backup",
                "backup": datos["backup"],
                "deleted_from_all_locations": True,
                "locations": datos["locations"],
                "lost": datos["lost"],
                "warnings": avisos,
            })
            logger.info(f"{tool}_preview", locations=ubicaciones)
            return await create_confirmation_token(tool, args, preview=preview, estado=estado)

        ok, error, _ = await resolve_confirmation_token(
            confirmation_token, tool, args, estado=estado)
        if not ok:
            return await _rechazo_token(tool, error)
        try:
            data = await ha_client.ws_send({"type": "backup/delete", "backup_id": backup_id})
        except HAConnectionError as exc:
            return await _fallo_ha(tool, confirmation_token, exc)
        fallidos = _hb._errores_agentes(
            data.get("agent_errors") if isinstance(data, dict) else None)
        borrado_de = [u for u in ubicaciones if u not in fallidos]
        if fallidos and not borrado_de:
            resultado_error = _hb._saneado({"error": "delete_failed", "failed": fallidos})
            await complete_confirmation_token(confirmation_token, success=False,
                                              error="delete_failed")
            logger.warning(f"{tool}_error", code="delete_failed", failed=sorted(fallidos))
            return resultado_error
        resultado = _hb._saneado({"result": "partial" if fallidos else "ok",
                                  "deleted_from": borrado_de, "failed": fallidos})
        await complete_confirmation_token(confirmation_token, success=True, result=resultado)
        logger.info(f"{tool}_ok", deleted_from=borrado_de, failed=sorted(fallidos))
        return resultado
