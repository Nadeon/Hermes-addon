"""Hermes — Agentes y ajustes de los backups de Home Assistant (spec 031, tramo 1).

Cuatro tools de la familia `backup_integration` (CAP-057 de la 008):

- `ha_list_backup_agents`: dónde puede guardar HA sus backups (local, montajes
  de red del Supervisor, nube…), con su cifrado y su retención.
- `ha_update_backup_config`: programación, retención, agentes y contenido de
  los backups automáticos, en dos pasos.
- `ha_get_update_backup_settings` y `ha_set_update_backup_settings`: si HA
  hace un backup antes de actualizar Core o una app, y cuántos guarda.

POR QUÉ CONFIRMAN LAS DOS QUE ESCRIBEN
--------------------------------------
Cambiar la retención BORRA backups: HA aplica la nueva regla por días al día
siguiente y la de copias al terminar el siguiente backup automático. Poner un
agente en `protected: false` sube la casa entera (con `secrets.yaml`) sin
cifrar. Y quitar el backup previo a actualizar deja una actualización sin
vuelta atrás. La vista previa dice lo que cambia, lo que HA borraría (una
ESTIMACIÓN con sus reglas, `backup_retention_estimate.py`) y los avisos; el
token ata los argumentos y la huella de la configuración leída y de lo que se
estimó borrar (estado atado de la spec 018): si algo cambia en los 60 s del
token, no se ejecuta.

POR QUÉ NO HAY CONTRASEÑA
-------------------------
`create_backup.password` es la clave que cifra TODOS los backups automáticos
(la del kit de emergencia). Cambiarla aquí dejaría al usuario sin poder
descifrar los backups futuros si no la apunta, y la interfaz de HA es la que
entrega el kit. Por eso se rechaza `password` en cualquier sitio, sin repetir
el valor en la respuesta ni en el log, y la configuración sale por la lista
blanca de `tools/ha_backups.py`, que dice solo `password_set`.

Todo lo que sale pasa por esa lista blanca y por `redact_structure` +
`redact_secrets` (`_saneado`). El log lleva recuentos y nombres de campo,
nunca valores.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import structlog

from hermes.backup_retention_estimate import estimar_retencion
from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    ESTADO_CAMBIADO,
    complete_confirmation_token,
    create_confirmation_token,
    redact_secrets,
    resolve_confirmation_token,
)
from hermes.tools import ha_backups as _hb
from hermes.tools._common import ajustar_lista_a_bytes, requires_ready, sobre_de_lista

logger = structlog.get_logger(__name__)

# ── Validación (esquema de `backup/config/update` de HA 2026.11.1) ──────────

_RECURRENCIAS = ("never", "daily", "custom_days")
_DIAS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_CARPETAS = ("share", "addons/local", "ssl", "media")
_CLAVES_SCHEDULE = ("recurrence", "days", "time")
_CLAVES_RETENTION = ("copies", "days")
_CLAVES_AGENTE = ("protected", "retention")
_CLAVES_CREATE = ("agent_ids", "include_addons", "include_all_addons",
                  "include_database", "include_folders", "name")
_MAX_AGENTES = 20
_MAX_LISTA = 100
_MAX_NOMBRE = 255
# Cuántos backups enseña la estimación de la retención como mucho.
_MAX_WOULD_DELETE = 50
_MAX_COPIAS_ACTUALIZAR = 100

# `<dominio>.<id>`: `backup.local`, `hassio.nas_backups`, `cloud.cloud`. El id
# lo pone cada integración (a veces un identificador de su servicio), así que
# solo se exige que no tenga espacios ni caracteres de control.
_AGENTE_RE = re.compile(r"^[a-z0-9_]+\.[^\s\x00-\x1f\x7f]{1,200}$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_HORA_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?$")

_UPDATE_CAMPOS = ("core_backup_before_update", "add_on_backup_before_update",
                  "add_on_backup_retain_copies")

_NO_SUPERVISOR = {
    "error": "supervisor_integration_unavailable",
    "detail": "The Home Assistant Supervisor integration (hassio) is not loaded: "
              "these settings only exist on installations with a Supervisor.",
}

_ESTIMACION_DETALLE = (
    "Computed with Home Assistant's retention rules; it depends on what "
    "happens until then."
)


class _Invalido(Exception):
    """Argumento inválido: `field` y un detalle que NUNCA lleva el valor."""

    def __init__(self, campo: str, detalle: str) -> None:
        super().__init__(detalle)
        self.campo = campo
        self.detalle = detalle


def _invalido(exc: _Invalido) -> dict[str, Any]:
    return {"error": "invalid_argument", "field": exc.campo, "detail": exc.detalle}


def _es_entero(valor: Any) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _dict(valor: Any, campo: str, permitidas: tuple[str, ...]) -> dict[str, Any]:
    """Un objeto con claves conocidas. `password` va antes que «desconocida»:
    tiene su propio motivo, y su valor no se repite nunca."""
    if not isinstance(valor, dict):
        raise _Invalido(campo, "must be an object")
    if "password" in valor:
        raise _Invalido(
            f"{campo}.password",
            "the backup encryption key cannot be read or changed through Hermes; "
            "change it in the Home Assistant UI (Settings > System > Backups), "
            "which gives you the emergency kit",
        )
    for clave in valor:
        if clave not in permitidas:
            raise _Invalido(f"{campo}.{clave}", "unknown key; allowed: " + ", ".join(permitidas))
    return valor


def _lista_unica(valor: Any, campo: str, *, forma: re.Pattern[str] | None = None,
                 valores: tuple[str, ...] | None = None) -> list[str]:
    if not isinstance(valor, list) or len(valor) > _MAX_LISTA:
        raise _Invalido(campo, f"must be a list of at most {_MAX_LISTA} strings")
    for x in valor:
        if not isinstance(x, str):
            raise _Invalido(campo, "must be a list of strings")
        if valores is not None and x not in valores:
            raise _Invalido(campo, "each item must be one of: " + ", ".join(valores))
        if forma is not None and not forma.match(x):
            raise _Invalido(campo, "an item has an invalid shape")
    if len(set(valor)) != len(valor):
        raise _Invalido(campo, "items must not repeat")
    return valor


def _retencion_valida(valor: Any, campo: str) -> dict[str, Any]:
    r = _dict(valor, campo, _CLAVES_RETENTION)
    for clave, v in r.items():
        if v is not None and (not _es_entero(v) or v < 1):
            raise _Invalido(f"{campo}.{clave}", "must be an integer of at least 1, or null")
    return r


def _hora(valor: str) -> str:
    """`HH:MM` o `HH:MM:SS` → `HH:MM:SS`, como la guarda y la devuelve HA."""
    m = _HORA_RE.match(valor)
    assert m is not None
    return f"{m.group(1)}:{m.group(2)}:{m.group(3) or '00'}"


def _validar_config(
    schedule: Any, retention: Any, agents: Any, create_backup: Any,
    automatic_backups_configured: Any,
) -> dict[str, Any]:
    """Valida antes de llamar a HA; devuelve los argumentos normalizados."""
    if all(v is None for v in (schedule, retention, agents, create_backup,
                               automatic_backups_configured)):
        raise _Invalido("arguments", "pass at least one of schedule, retention, agents, "
                                     "create_backup or automatic_backups_configured")
    out: dict[str, Any] = {}
    if schedule is not None:
        s = dict(_dict(schedule, "schedule", _CLAVES_SCHEDULE))
        if "recurrence" in s and s["recurrence"] not in _RECURRENCIAS:
            raise _Invalido("schedule.recurrence", "must be one of: " + ", ".join(_RECURRENCIAS))
        if "days" in s:
            _lista_unica(s["days"], "schedule.days", valores=_DIAS)
        if "time" in s and s["time"] is not None:
            if not isinstance(s["time"], str) or not _HORA_RE.match(s["time"]):
                raise _Invalido("schedule.time", "must be HH:MM or HH:MM:SS (24 h), or null")
            s["time"] = _hora(s["time"])
        out["schedule"] = s
    if retention is not None:
        out["retention"] = dict(_retencion_valida(retention, "retention"))
    if agents is not None:
        if not isinstance(agents, dict) or not 1 <= len(agents) <= _MAX_AGENTES:
            raise _Invalido("agents", f"must be an object with 1 to {_MAX_AGENTES} agents")
        ag: dict[str, Any] = {}
        for agente, datos in agents.items():
            if not isinstance(agente, str) or not _AGENTE_RE.match(agente):
                raise _Invalido("agents", "an agent id has an invalid shape "
                                          "(expected <integration>.<id>)")
            d = dict(_dict(datos, f"agents.{agente}", _CLAVES_AGENTE))
            if "protected" in d and not isinstance(d["protected"], bool):
                raise _Invalido(f"agents.{agente}.protected", "must be true or false")
            if d.get("retention") is not None:
                d["retention"] = dict(_retencion_valida(d["retention"],
                                                        f"agents.{agente}.retention"))
            ag[agente] = d
        out["agents"] = ag
    if create_backup is not None:
        c = dict(_dict(create_backup, "create_backup", _CLAVES_CREATE))
        if "agent_ids" in c:
            _lista_unica(c["agent_ids"], "create_backup.agent_ids", forma=_AGENTE_RE)
        if c.get("include_addons") is not None:
            _lista_unica(c["include_addons"], "create_backup.include_addons", forma=_SLUG_RE)
        if c.get("include_folders") is not None:
            _lista_unica(c["include_folders"], "create_backup.include_folders",
                         valores=_CARPETAS)
        for clave in ("include_all_addons", "include_database"):
            if clave in c and not isinstance(c[clave], bool):
                raise _Invalido(f"create_backup.{clave}", "must be true or false")
        if "name" in c and c["name"] is not None and (
            not isinstance(c["name"], str) or len(c["name"]) > _MAX_NOMBRE
        ):
            raise _Invalido("create_backup.name",
                            f"must be a string of at most {_MAX_NOMBRE} characters, or null")
        if c.get("include_all_addons") is True and c.get("include_addons"):
            raise _Invalido("create_backup.include_addons",
                            "include_all_addons already includes every app; "
                            "do not pass include_addons with it")
        out["create_backup"] = c
    if automatic_backups_configured is not None:
        if not isinstance(automatic_backups_configured, bool):
            raise _Invalido("automatic_backups_configured", "must be true or false")
        out["automatic_backups_configured"] = automatic_backups_configured
    return out


# ── Fusión: lo que se manda y la configuración resultante ────────────────────

def _carga_y_resultante(
    actual: dict[str, Any], pedido: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(carga de `backup/config/update`, configuración resultante).

    HA SUSTITUYE `schedule` y `retention` enteros (`BackupSchedule(**schedule)`,
    `RetentionConfig(**retention)`): lo no pasado vuelve al valor por defecto,
    que en `recurrence` es `never`. Pasar solo `{"time": "04:30"}` apagaría
    los backups automáticos sin que nadie lo pidiera. Por eso se completan
    con los valores actuales de lo no pasado (un `null` explícito sí se
    respeta), y lo mismo la `retention` de cada agente. `create_backup` ya lo
    funde HA (`replace`), y `agents`, por agente.
    """
    carga: dict[str, Any] = {}
    resultante = {
        "agents": {k: dict(v) for k, v in (actual.get("agents") or {}).items()},
        "automatic_backups_configured": actual.get("automatic_backups_configured"),
        "create_backup": dict(actual.get("create_backup") or {}),
        "retention": actual.get("retention"),
        "schedule": actual.get("schedule"),
    }
    if "schedule" in pedido:
        sch_actual = actual.get("schedule") or {}
        sched = {
            "recurrence": sch_actual.get("recurrence") or "never",
            "days": list(sch_actual.get("days") or []),
            "time": sch_actual.get("time"),
        }
        sched.update(pedido["schedule"])
        carga["schedule"] = sched
        resultante["schedule"] = dict(sched)
    if "retention" in pedido:
        ret_actual = actual.get("retention") or {}
        ret = {"copies": ret_actual.get("copies"), "days": ret_actual.get("days")}
        ret.update(pedido["retention"])
        carga["retention"] = ret
        resultante["retention"] = dict(ret)
    if "agents" in pedido:
        carga["agents"] = {}
        for agente, datos in pedido["agents"].items():
            previo = resultante["agents"].get(agente)
            enviado = dict(datos)
            if isinstance(datos.get("retention"), dict):
                ret_previa = (previo or {}).get("retention") or {}
                ret = {"copies": ret_previa.get("copies"), "days": ret_previa.get("days")}
                ret.update(datos["retention"])
                enviado["retention"] = ret
            carga["agents"][agente] = enviado
            # Como `BackupConfig.update` de HA: un agente nuevo nace
            # protegido salvo que se diga otra cosa.
            nuevo = dict(previo) if previo is not None else {"protected": True, "retention": None}
            if "protected" in enviado:
                nuevo["protected"] = enviado["protected"]
            if "retention" in enviado:
                nuevo["retention"] = enviado["retention"]
            resultante["agents"][agente] = nuevo
    if "create_backup" in pedido:
        carga["create_backup"] = dict(pedido["create_backup"])
        resultante["create_backup"].update(pedido["create_backup"])
    if "automatic_backups_configured" in pedido:
        carga["automatic_backups_configured"] = pedido["automatic_backups_configured"]
        resultante["automatic_backups_configured"] = pedido["automatic_backups_configured"]
    return carga, resultante


def _cambios(actual: dict[str, Any], resultante: dict[str, Any]) -> list[str]:
    """Rutas con punto de los campos que cambian."""
    cambios: list[str] = []
    sa, sr = actual.get("schedule") or {}, resultante.get("schedule") or {}
    for clave in _CLAVES_SCHEDULE:
        if sa.get(clave) != sr.get(clave):
            cambios.append(f"schedule.{clave}")
    ra, rr = actual.get("retention") or {}, resultante.get("retention") or {}
    for clave in _CLAVES_RETENTION:
        if ra.get(clave) != rr.get(clave):
            cambios.append(f"retention.{clave}")
    aa, ar = actual.get("agents") or {}, resultante.get("agents") or {}
    for agente in sorted(set(aa) | set(ar)):
        a, r = aa.get(agente) or {}, ar.get(agente) or {}
        for clave in _CLAVES_AGENTE:
            if a.get(clave) != r.get(clave):
                cambios.append(f"agents.{agente}.{clave}")
    ca, cr = actual.get("create_backup") or {}, resultante.get("create_backup") or {}
    for clave in _CLAVES_CREATE:
        if ca.get(clave) != cr.get(clave):
            cambios.append(f"create_backup.{clave}")
    if actual.get("automatic_backups_configured") != resultante.get("automatic_backups_configured"):
        cambios.append("automatic_backups_configured")
    return cambios


def _avisos(actual: dict[str, Any], resultante: dict[str, Any],
            disponibles: list[str] | None) -> list[str]:
    avisos: list[str] = []
    for agente, datos in sorted((resultante.get("agents") or {}).items()):
        if datos.get("protected") is False:
            avisos.append(
                f"Backups uploaded to {agente} will NOT be encrypted: a copy of the "
                "whole configuration, including secrets.yaml, is stored there in clear."
            )
    sr = resultante.get("schedule") or {}
    sa = actual.get("schedule") or {}
    if sr.get("recurrence") == "never" and sa.get("recurrence") not in (None, "never"):
        avisos.append("Automatic backups will be turned off (schedule.recurrence: never).")
    elif sr.get("recurrence") == "custom_days" and not sr.get("days"):
        avisos.append("schedule.recurrence is custom_days with no days: "
                      "no automatic backup will run.")
    destinos = (resultante.get("create_backup") or {}).get("agent_ids")
    if disponibles is not None and isinstance(destinos, list):
        faltan = sorted(set(destinos) - set(disponibles))
        if faltan:
            avisos.append(
                "These automatic backup agents are not available in Home Assistant: "
                + ", ".join(faltan) + "."
            )
    return avisos


def _efecto_retencion(resultante: dict[str, Any], backups: list[dict[str, Any]]) -> dict[str, Any]:
    estimacion = estimar_retencion(resultante, backups, datetime.now(timezone.utc))
    return {
        "estimate": True,
        "detail": _ESTIMACION_DETALLE,
        "would_delete": estimacion[:_MAX_WOULD_DELETE],
        "truncated": len(estimacion) > _MAX_WOULD_DELETE,
        "_ids": [e["backup_id"] for e in estimacion],
    }


def _kind(agent_id: str) -> str:
    if agent_id in ("backup.local", "hassio.local"):
        return "local"
    if agent_id.startswith("hassio."):
        return "mount"
    return "remote"


def _error_ha(exc: HAConnectionError) -> str:
    # Los errores de un agente pueden nombrar el NAS o la red del usuario.
    return _hb._mascara_red(redact_secrets(str(exc)))


def register(
    mcp: object,
    ha_client: HAClient,
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
) -> None:
    """Registra las tools de agentes y ajustes de los backups de HA."""

    ready = requires_ready(ha_client)

    async def _leer(tipo: str, *, sin_integracion: dict[str, Any]) -> tuple[Any, dict[str, Any] | None]:
        try:
            return await ha_client.ws_send({"type": tipo}), None
        except HAConnectionError as exc:
            if getattr(exc, "code", None) == "unknown_command":
                return None, dict(sin_integracion)
            return None, {"error": _error_ha(exc)}

    async def _config_actual() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        data, err = await _leer("backup/config/info", sin_integracion=_hb._NO_DISPONIBLE)
        if err:
            return None, err
        config = data.get("config") if isinstance(data, dict) else None
        if not isinstance(config, dict):
            return None, {"error": "unexpected_response from backup/config/info"}
        return _hb._config_permitida(config), None

    async def _backups() -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
        data, err = await _leer("backup/info", sin_integracion=_hb._NO_DISPONIBLE)
        if err:
            return None, err
        if not isinstance(data, dict) or not isinstance(data.get("backups"), list):
            return None, {"error": "unexpected_response from backup/info"}
        return [_hb._backup_permitido(b) for b in data["backups"] if isinstance(b, dict)], None

    async def _agentes() -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
        data, err = await _leer("backup/agents/info", sin_integracion=_hb._NO_DISPONIBLE)
        if err:
            return None, err
        if not isinstance(data, dict) or not isinstance(data.get("agents"), list):
            return None, {"error": "unexpected_response from backup/agents/info"}
        return [a for a in data["agents"]
                if isinstance(a, dict) and isinstance(a.get("agent_id"), str)], None

    # ── ha_list_backup_agents ─────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_backup_agents() -> object:
        """List where Home Assistant can store backups (backup agents, HA 2025.1+).

        Read-only. Returns {"count", "items", "truncated"}; each item has
        agent_id, name, kind ("local" for backup.local and hassio.local,
        "mount" for Supervisor network storage, "remote" for the rest, such
        as the cloud), protected (whether HA encrypts the copy stored there),
        retention (that agent's own retention, or null when it uses the global
        one) and used_by_automatic_backups. The encryption key is never
        returned.
        """
        if (err := await _hb.comprobar_version_backup(ha_client)):
            return err
        agentes, err = await _agentes()
        if err:
            return err
        config, err = await _config_actual()
        if err:
            return err
        destinos = config["create_backup"].get("agent_ids") or []
        items = []
        for a in agentes:
            aid = a["agent_id"]
            propio = config["agents"].get(aid)
            items.append(_hb._saneado({
                "agent_id": aid,
                "name": _hb._escalar(a.get("name")),
                "kind": _kind(aid),
                # Sin entrada en la configuración, HA cifra (es el valor con
                # el que crea la entrada del agente).
                "protected": propio["protected"] if propio and propio.get("protected") is not None else True,
                "retention": propio.get("retention") if propio else None,
                "used_by_automatic_backups": aid in destinos,
            }))
        out = ajustar_lista_a_bytes(
            items, lambda its, recortada: sobre_de_lista(its, truncated=recortada),
            response_max_bytes,
        )
        logger.info("ha_list_backup_agents_ok", count=out["count"], truncated=out["truncated"])
        return out

    # ── ha_update_backup_config ───────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_update_backup_config(
        schedule: dict[str, Any] | None = None,
        retention: dict[str, Any] | None = None,
        agents: dict[str, Any] | None = None,
        create_backup: dict[str, Any] | None = None,
        automatic_backups_configured: bool | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Change Home Assistant's automatic backup settings (HA 2025.1+).

        Two steps: without confirmation_token returns a preview (current and
        resulting settings, what changes, warnings and an ESTIMATE of the
        backups the retention would delete) and a token; repeat the same call
        with the token to apply. Retention changes DELETE automatic backups:
        by days within about 24 h, by copies after the next automatic backup.
        The encryption key cannot be read or changed here (use the Home
        Assistant UI, which gives you the emergency kit): any "password" is
        rejected.

        Args:
            schedule: {"recurrence": "never"|"daily"|"custom_days",
                "days": ["mon", ...], "time": "HH:MM" or null}. Fields you
                leave out keep their current value.
            retention: {"copies": int >= 1 or null, "days": int >= 1 or null};
                null means no limit. Fields you leave out keep their value.
            agents: {agent_id: {"protected": bool, "retention": {...} or
                null}}; 1-20 agents. protected false stores that agent's copy
                unencrypted; retention null uses the global one.
            create_backup: {"agent_ids": [...], "include_addons": [...] or
                null, "include_all_addons": bool, "include_database": bool,
                "include_folders": ["share", "addons/local", "ssl", "media"]
                or null, "name": str or null}.
            automatic_backups_configured: bool.
            confirmation_token: Token from the preview call.

        Returns:
            Preview + token; {"result": "ok", "changed": [...]}; or
            {"error": ...} ("state_changed" if the settings or the backups
            changed since the preview).
        """
        tool = "ha_update_backup_config"
        try:
            pedido = _validar_config(schedule, retention, agents, create_backup,
                                     automatic_backups_configured)
        except _Invalido as exc:
            logger.warning(f"{tool}_error", code="invalid_argument", field=exc.campo)
            return _invalido(exc)
        if (err := await _hb.comprobar_version_backup(ha_client)):
            return err

        actual, err = await _config_actual()
        if err:
            return err
        backups, err = await _backups()
        if err:
            return err
        carga, resultante = _carga_y_resultante(actual, pedido)
        efecto = _efecto_retencion(resultante, backups)
        ids_borrar = efecto.pop("_ids")
        # La huella cubre la configuración leída (sin contraseña: la lista
        # blanca solo dice `password_set`) y lo que se estimó borrar.
        estado = {"config": actual, "would_delete": ids_borrar}
        args = {
            "schedule": schedule, "retention": retention, "agents": agents,
            "create_backup": create_backup,
            "automatic_backups_configured": automatic_backups_configured,
        }

        if not confirmation_token:
            agentes, err = await _agentes()
            disponibles = [a["agent_id"] for a in agentes] if not err and agentes is not None else None
            cambios = _cambios(actual, resultante)
            preview = _hb._saneado({
                "action": "update_backup_config",
                "current": actual,
                "resulting": resultante,
                "sends": carga,
                "changed": cambios,
                "warnings": _avisos(actual, resultante, disponibles),
                "retention_effect": efecto,
            })
            logger.info(f"{tool}_preview", changed=len(cambios),
                        would_delete=len(ids_borrar))
            return await create_confirmation_token(tool, args, preview=preview, estado=estado)

        ok, error, _ = await resolve_confirmation_token(
            confirmation_token, tool, args, estado=estado)
        if not ok:
            if error == ESTADO_CAMBIADO:
                logger.warning(f"{tool}_error", code="state_changed")
                return {"error": "state_changed", "detail": error}
            logger.warning(f"{tool}_error", code="token_invalid")
            return {"error": error}
        try:
            await ha_client.ws_send({"type": "backup/config/update", **carga})
        except HAConnectionError as exc:
            detalle = _error_ha(exc)
            await complete_confirmation_token(confirmation_token, success=False, error=detalle)
            logger.warning(f"{tool}_error", code=exc.code or "connection")
            return {"error": detalle}
        cambios = _cambios(actual, resultante)
        resultado = {"result": "ok", "changed": cambios}
        await complete_confirmation_token(confirmation_token, success=True, result=resultado)
        logger.info(f"{tool}_ok", changed=len(cambios), would_delete=len(ids_borrar))
        return resultado

    # ── hassio/update/config ──────────────────────────────────────────────

    async def _ajustes_actualizar() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        data, err = await _leer("hassio/update/config/info", sin_integracion=_NO_SUPERVISOR)
        if err:
            return None, err
        if not isinstance(data, dict):
            return None, {"error": "unexpected_response from hassio/update/config/info"}
        return {k: _hb._escalar(data.get(k)) for k in _UPDATE_CAMPOS}, None

    @mcp.tool()
    @ready
    async def ha_get_update_backup_settings() -> object:
        """Get whether Home Assistant backs up before updating (HA 2025.1+, read-only).

        Returns {"core_backup_before_update", "add_on_backup_before_update",
        "add_on_backup_retain_copies"}. Needs the Supervisor integration
        (hassio): elsewhere returns {"error": "supervisor_integration_unavailable"}.
        """
        if (err := await _hb.comprobar_version_backup(ha_client)):
            return err
        actual, err = await _ajustes_actualizar()
        if err:
            return err
        logger.info("ha_get_update_backup_settings_ok")
        return actual

    @mcp.tool()
    @ready
    async def ha_set_update_backup_settings(
        core_backup_before_update: bool | None = None,
        add_on_backup_before_update: bool | None = None,
        add_on_backup_retain_copies: int | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Change whether Home Assistant backs up before updating (HA 2025.1+).

        Two steps: without confirmation_token returns a preview (current and
        resulting settings, what changes, warnings) and a token; repeat the
        same call with the token to apply. Turning a backup off leaves that
        kind of update without a way back. Needs the Supervisor integration
        (hassio).

        Args:
            core_backup_before_update: Back up before updating Core.
            add_on_backup_before_update: Back up an app before updating it.
            add_on_backup_retain_copies: 1-100 backups kept per app; on each
                app update, HA deletes that app's older update backups.
            confirmation_token: Token from the preview call.

        Returns:
            Preview + token; {"result": "ok", "changed": [...]}; or
            {"error": ...}.
        """
        tool = "ha_set_update_backup_settings"
        pedido = {
            "core_backup_before_update": core_backup_before_update,
            "add_on_backup_before_update": add_on_backup_before_update,
            "add_on_backup_retain_copies": add_on_backup_retain_copies,
        }
        if all(v is None for v in pedido.values()):
            return _invalido(_Invalido("arguments", "pass at least one setting"))
        for clave in ("core_backup_before_update", "add_on_backup_before_update"):
            if pedido[clave] is not None and not isinstance(pedido[clave], bool):
                return _invalido(_Invalido(clave, "must be true or false"))
        copias = add_on_backup_retain_copies
        if copias is not None and (not _es_entero(copias)
                                   or not 1 <= copias <= _MAX_COPIAS_ACTUALIZAR):
            return _invalido(_Invalido("add_on_backup_retain_copies",
                                       f"must be an integer from 1 to {_MAX_COPIAS_ACTUALIZAR}"))
        if (err := await _hb.comprobar_version_backup(ha_client)):
            return err
        actual, err = await _ajustes_actualizar()
        if err:
            return err
        carga = {k: v for k, v in pedido.items() if v is not None}
        resultante = {**actual, **carga}
        cambios = [k for k in _UPDATE_CAMPOS if actual.get(k) != resultante.get(k)]

        if not confirmation_token:
            avisos = []
            previas = actual.get("add_on_backup_retain_copies")
            if copias is not None and _es_entero(previas) and copias < previas:
                avisos.append(
                    "On the next update of each app, Home Assistant deletes that app's "
                    f"update backups beyond the newest {copias}."
                )
            for clave, texto in (("core_backup_before_update", "Core"),
                                 ("add_on_backup_before_update", "an app")):
                if actual.get(clave) is True and resultante.get(clave) is False:
                    avisos.append(f"Updating {texto} will no longer make a backup first.")
            preview = {
                "action": "set_update_backup_settings",
                "current": actual, "resulting": resultante,
                "changed": cambios, "warnings": avisos,
            }
            logger.info(f"{tool}_preview", changed=len(cambios))
            return await create_confirmation_token(tool, pedido, preview=preview, estado=actual)

        ok, error, _ = await resolve_confirmation_token(
            confirmation_token, tool, pedido, estado=actual)
        if not ok:
            if error == ESTADO_CAMBIADO:
                logger.warning(f"{tool}_error", code="state_changed")
                return {"error": "state_changed", "detail": error}
            logger.warning(f"{tool}_error", code="token_invalid")
            return {"error": error}
        try:
            await ha_client.ws_send({"type": "hassio/update/config/update", **carga})
        except HAConnectionError as exc:
            detalle = _error_ha(exc)
            await complete_confirmation_token(confirmation_token, success=False, error=detalle)
            logger.warning(f"{tool}_error", code=exc.code or "connection")
            return {"error": detalle}
        resultado = {"result": "ok", "changed": cambios}
        await complete_confirmation_token(confirmation_token, success=True, result=resultado)
        logger.info(f"{tool}_ok", changed=len(cambios))
        return resultado
