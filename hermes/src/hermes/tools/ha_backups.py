"""Hermes — Tools MCP de la integración `backup` de Home Assistant.

Tools (solo lectura, HA ≥ 2025.1):
  ha_list_backups       — backups que conoce HA (todas sus ubicaciones), del más reciente al más antiguo
  ha_get_backup         — detalle de un backup
  ha_get_backup_config  — configuración de los backups automáticos de HA

Por qué lista blanca y no reenviar la respuesta: `backup/config/info`
devuelve EN CLARO la contraseña de cifrado de los backups automáticos, y
`backup/info` lleva el `instance_id` de la instalación (`extra_metadata`) y
mensajes de error de los agentes que pueden nombrar el NAS o el recurso SMB
del usuario con sus credenciales. Con `redact_structure` se taparía la clave
`password`, pero cualquier campo que HA añadiera después saldría tal cual.
Copiando solo los campos conocidos, lo nuevo no sale hasta que alguien decida
que puede salir (fail-closed). Al final se pasa igualmente por
`redact_structure` y `redact_secrets` como defensa en profundidad.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.ha_version import ha_at_least, ha_core_version
from hermes.security import redact_secrets, redact_structure
from hermes.tools._common import requires_ready
from hermes.tools._validation import InvalidIdentifier, validate_identifier

logger = structlog.get_logger(__name__)

_VERSION_MINIMA = "2025.1.0"
_MAX_ERROR_AGENTE = 300

_NO_DISPONIBLE = {
    "error": "backup_integration_unavailable",
    "detail": "The Home Assistant backup integration is not available on this installation.",
}

# Host de una URL, con las credenciales que lleve delante (`user:pass@`).
_URL_HOST_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)(?:[^/\s@]*@)?(\[[^\]]*\]|[^/\s:?#]+)")
_IPV4_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
# IPv6: al menos «::» o tres «:» entre grupos hex, para no tapar horas
# como 12:30:45.
_IPV6_RE = re.compile(
    r"(?i)(?<![\w:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![\w:])"
)
# `host:puerto` sin esquema (p. ej. `nas.lan:445`).
_HOST_PUERTO_RE = re.compile(r"(?i)\b[a-z0-9-]+(?:\.[a-z0-9-]+)+:\d{1,5}\b")


def _es_ipv6(texto: str) -> bool:
    return "::" in texto or texto.count(":") >= 3


def _mascara_red(texto: str) -> str:
    """Tapa hosts de URL, `host:puerto`, IPv4 e IPv6.

    Los errores de un agente de backup (SMB, NFS, NAS) citan direcciones de
    la red del usuario; no hacen falta para entender el fallo.
    """
    texto = _URL_HOST_RE.sub(lambda m: f"{m.group(1)}<host>", texto)
    texto = _HOST_PUERTO_RE.sub("<host>", texto)
    texto = _IPV6_RE.sub(lambda m: "<ip>" if _es_ipv6(m.group(0)) else m.group(0), texto)
    texto = _IPV4_RE.sub("<ip>", texto)
    return texto


def _errores_agentes(raw: Any) -> dict[str, str]:
    """`{agent_id: mensaje}` con el mensaje redactado, enmascarado y recortado.

    Se enmascara ANTES de recortar: recortar primero podría dejar media IP o
    media contraseña al final del texto.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for agente, mensaje in raw.items():
        if not isinstance(mensaje, str):
            # Un error con estructura no se interpreta: se dice que lo hubo.
            mensaje = "error (details withheld)"
        out[str(agente)] = _mascara_red(redact_secrets(mensaje))[:_MAX_ERROR_AGENTE]
    return out


def _escalar(valor: Any) -> Any:
    """Solo valores simples: un dict o una lista inesperados no se copian."""
    return valor if isinstance(valor, (str, int, float, bool)) or valor is None else None


def _lista_textos(valor: Any) -> list[str] | None:
    if not isinstance(valor, list):
        return None
    return [x for x in valor if isinstance(x, str)]


def _addon(raw: Any) -> dict[str, Any] | str | None:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        return {k: _escalar(raw.get(k)) for k in ("slug", "name", "version")}
    return None


def _lista_addons(valor: Any) -> list[Any] | None:
    if not isinstance(valor, list):
        return None
    return [a for a in (_addon(x) for x in valor) if a is not None]


def _backup_permitido(b: dict[str, Any]) -> dict[str, Any]:
    """Backup de HA por lista blanca (data-model.md). Fuera `extra_metadata`."""
    out: dict[str, Any] = {}
    for clave in ("backup_id", "name", "date", "database_included",
                  "homeassistant_included", "homeassistant_version",
                  "with_automatic_settings"):
        out[clave] = _escalar(b.get(clave))
    agentes = b.get("agents")
    out["agents"] = {
        str(aid): {"protected": _escalar(a.get("protected")), "size": _escalar(a.get("size"))}
        for aid, a in agentes.items() if isinstance(a, dict)
    } if isinstance(agentes, dict) else {}
    out["addons"] = _lista_addons(b.get("addons")) or []
    out["folders"] = _lista_textos(b.get("folders")) or []
    out["failed_agent_ids"] = _lista_textos(b.get("failed_agent_ids")) or []
    out["failed_addons"] = _lista_addons(b.get("failed_addons")) or []
    out["failed_folders"] = _lista_textos(b.get("failed_folders")) or []
    return out


def _retencion(valor: Any) -> dict[str, Any] | None:
    if not isinstance(valor, dict):
        return None
    return {"copies": _escalar(valor.get("copies")), "days": _escalar(valor.get("days"))}


def _config_permitida(c: dict[str, Any]) -> dict[str, Any]:
    """Configuración de backups por lista blanca. `password` NUNCA se copia."""
    out: dict[str, Any] = {}
    agentes = c.get("agents")
    out["agents"] = {
        str(aid): {"protected": _escalar(a.get("protected")),
                   "retention": _retencion(a.get("retention"))}
        for aid, a in agentes.items() if isinstance(a, dict)
    } if isinstance(agentes, dict) else {}
    out["automatic_backups_configured"] = _escalar(c.get("automatic_backups_configured"))
    cb = c.get("create_backup") if isinstance(c.get("create_backup"), dict) else {}
    password = cb.get("password")
    out["create_backup"] = {
        "agent_ids": _lista_textos(cb.get("agent_ids")),
        "include_addons": _lista_textos(cb.get("include_addons")),
        "include_all_addons": _escalar(cb.get("include_all_addons")),
        "include_database": _escalar(cb.get("include_database")),
        "include_folders": _lista_textos(cb.get("include_folders")),
        "name": _escalar(cb.get("name")),
        # Se dice SI hay contraseña, nunca cuál: es la que descifra todos
        # los backups automáticos y sobrevive a cualquier revocación.
        "password_set": isinstance(password, str) and password != "",
    }
    for clave in ("last_attempted_automatic_backup", "last_completed_automatic_backup",
                  "next_automatic_backup", "next_automatic_backup_additional"):
        out[clave] = _escalar(c.get(clave))
    out["retention"] = _retencion(c.get("retention"))
    sched = c.get("schedule")
    out["schedule"] = {
        "days": _lista_textos(sched.get("days")),
        "recurrence": _escalar(sched.get("recurrence")),
        "state": _escalar(sched.get("state")),
        "time": _escalar(sched.get("time")),
    } if isinstance(sched, dict) else None
    return out


def _saneado(valor: Any) -> Any:
    """Defensa en profundidad sobre lo ya filtrado: claves y texto sensibles."""
    valor = redact_structure(valor)
    if isinstance(valor, str):
        return redact_secrets(valor)
    if isinstance(valor, dict):
        return {k: _saneado(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_saneado(v) for v in valor]
    return valor


def _orden_fecha(b: dict[str, Any]) -> float:
    fecha = b.get("date")
    if isinstance(fecha, str):
        try:
            return datetime.fromisoformat(fecha.replace("Z", "+00:00")).timestamp()
        except (ValueError, OverflowError):
            pass
    # Sin fecha legible, al final de la lista.
    return float("-inf")


def _json(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False)


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de backups de Home Assistant."""

    ready = requires_ready(ha_client)

    async def _comprobar_version() -> dict[str, Any] | None:
        """Error común si HA es anterior a 2025.1; None si se puede seguir.

        Con la versión desconocida se intenta igualmente: el comando dirá
        `unknown_command` si no existe, y eso se traduce abajo.
        """
        if await ha_at_least(ha_client, _VERSION_MINIMA) is False:
            actual = await ha_core_version(ha_client)
            return {"error": "ha_version_unsupported", "feature": "backup",
                    "required": _VERSION_MINIMA,
                    "current": str(actual) if actual is not None else None}
        return None

    async def _enviar(payload: dict[str, Any]) -> tuple[Any, dict[str, Any] | None]:
        try:
            return await ha_client.ws_send(payload), None
        except HAConnectionError as exc:
            if getattr(exc, "code", None) == "unknown_command":
                return None, dict(_NO_DISPONIBLE)
            return None, {"error": str(exc)}

    @mcp.tool()
    @ready
    async def ha_list_backups(limit: int = 20) -> object:
        """List Home Assistant backups (backup integration, HA 2025.1+), newest first.

        Covers every backup location HA knows (local, network storage, cloud).
        Returns {"count", "total", "backups": [...], "last_attempted_automatic_backup",
        "last_completed_automatic_backup", "next_automatic_backup", "state",
        "agent_errors"}. Each backup has backup_id, name, date, agents
        ({agent_id: {protected, size}}), addons, folders, database_included,
        homeassistant_included, homeassistant_version, failed_* lists and
        with_automatic_settings. The installation id is never returned.

        Args:
            limit: 1–100 (default 20).
        """
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            return _json({"error": "invalid_argument", "field": "limit",
                          "detail": "limit must be an integer between 1 and 100"})
        if (err := await _comprobar_version()):
            return _json(err)
        data, err = await _enviar({"type": "backup/info"})
        if err:
            return _json(err)
        if not isinstance(data, dict) or not isinstance(data.get("backups"), list):
            return _json({"error": "unexpected_response from backup/info"})
        backups = [_backup_permitido(b) for b in data["backups"] if isinstance(b, dict)]
        backups.sort(key=_orden_fecha, reverse=True)
        seleccion = backups[:limit]
        out = {
            "count": len(seleccion),
            "total": len(backups),
            "backups": seleccion,
            "last_attempted_automatic_backup": _escalar(
                data.get("last_attempted_automatic_backup")),
            "last_completed_automatic_backup": _escalar(
                data.get("last_completed_automatic_backup")),
            "next_automatic_backup": _escalar(data.get("next_automatic_backup")),
            "state": _escalar(data.get("state")),
            "agent_errors": _errores_agentes(data.get("agent_errors")),
        }
        logger.info("ha_list_backups_ok", count=len(seleccion))
        return _json(_saneado(out))

    @mcp.tool()
    @ready
    async def ha_get_backup(backup_id: str) -> object:
        """Get one Home Assistant backup by backup_id (HA 2025.1+, read-only).

        Returns {"backup": {...}, "agent_errors": {...}} with the same fields
        as ha_list_backups; unknown id → {"error": "not_found"}.
        """
        try:
            validate_identifier(backup_id, field="backup_id")
        except InvalidIdentifier as exc:
            return _json({"error": "invalid_identifier", "detail": str(exc)})
        if (err := await _comprobar_version()):
            return _json(err)
        data, err = await _enviar({"type": "backup/details", "backup_id": backup_id})
        if err:
            return _json(err)
        if not isinstance(data, dict):
            return _json({"error": "unexpected_response from backup/details"})
        backup = data.get("backup")
        if backup is None:
            return _json({"error": "not_found", "backup_id": backup_id})
        if not isinstance(backup, dict):
            return _json({"error": "unexpected_response from backup/details"})
        out = {"backup": _backup_permitido(backup),
               "agent_errors": _errores_agentes(data.get("agent_errors"))}
        logger.info("ha_get_backup_ok")
        return _json(_saneado(out))

    @mcp.tool()
    @ready
    async def ha_get_backup_config() -> object:
        """Get Home Assistant automatic backup settings (HA 2025.1+, read-only).

        Returns {"config": {...}}: agents (protected, retention),
        automatic_backups_configured, create_backup (agent_ids, include_*,
        name, password_set), retention, schedule and the last/next automatic
        backup times. The encryption password is NEVER returned: only
        `password_set` says whether one is configured.
        """
        if (err := await _comprobar_version()):
            return _json(err)
        data, err = await _enviar({"type": "backup/config/info"})
        if err:
            return _json(err)
        config = data.get("config") if isinstance(data, dict) else None
        if not isinstance(config, dict):
            return _json({"error": "unexpected_response from backup/config/info"})
        logger.info("ha_get_backup_config_ok")
        return _json(_saneado({"config": _config_permitida(config)}))
