"""Hermes — Aplicar sugerencias del centro de resolución (spec 022, tramo 2; CAP-087).

Familia `resolution_fixes` (1.2.0), módulo `resolution_fixes`.

Tools:
  sv_apply_resolution_suggestion — aplica una sugerencia del Supervisor (token)

POR QUÉ
-------
Hasta la 1.1.x Hermes nunca aplicaba sugerencias: varias borran datos o
reinician, y «aplicar» no decía QUÉ iba a pasar. FR-077 de la 008 cambia esa
política, pero solo con una vista previa honesta (research R-6): la tabla
`_FIXUPS` traduce cada par `(type, context)` que el Supervisor 2026.11.0 sabe
arreglar (`supervisor/resolution/fixups/*.py`) a su efecto, lo que corta,
cuánto tarda y si se puede deshacer. Lo que Hermes no puede explicar no recibe
token (fail-closed, principio III):

- `no_fixup`: el Supervisor respondería «ok» sin hacer nada (no tiene fixup
  para ese par): dar token sería mentir (principio V);
- `unknown_effect`: un tipo o contexto que el Supervisor 2026.11.0 no conoce
  (una versión futura): sin traducción no hay vista previa;
- `not_allowed`: renombrar o adoptar discos de datos (equivale a mover el
  disco de datos, clase D en la 008);
- `targets_hermes`: lo que pararía, reconstruiría o desinstalaría al propio
  Hermes, que no podría informar ni recuperarse. Hermes se reconoce por el
  slug EXACTO que da `/addons/self/info` (decisión del supervisor del
  programa), nunca por el sufijo `_hermes`: otra app puede llamarse así.

Tras aplicar el fixup, el Supervisor lanza su `healthcheck()`, que ejecuta
`run_autofix()` (`resolution/module.py`): las demás sugerencias con
`auto: true` pueden aplicarse en la misma llamada. La vista previa las lista
(`also_auto_applied`) y el token ata esa lista: si cambia antes de confirmar,
se rechaza sin aplicar (`suggestion_changed`).

Al log van el tipo, el contexto y el resultado; nunca `reference` (un slug,
una ruta o un nombre de la instalación) ni el texto de un error (principio II).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import aiohttp
import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.identifiers import InvalidIdentifier, validate_slug
from hermes.security import (
    ESTADO_CAMBIADO,
    complete_confirmation_token,
    create_confirmation_token,
    redact_secrets,
    redact_structure,
    resolve_confirmation_token,
)
from hermes.tools._common import recortar_a_bytes
from hermes.tools.system_control import _detalle, _es_corte

logger = structlog.get_logger(__name__)

_TOOL = "sv_apply_resolution_suggestion"
# Algunos fixups esperan a terminar en el Supervisor (un backup completo,
# reconstruir varios contenedores): minutos. Más allá, Hermes deja de esperar
# y lo dice (research R-7).
_TIEMPO_FIXUP = 900.0
_TIEMPO_LECTURA = 15.0
# El Supervisor guarda al menos estos backups completos (`MINIMUM_FULL_BACKUPS`
# en `resolution/const.py` de 2026.11.0); `clear_full_backup` borra el resto.
_BACKUPS_COMPLETOS_MINIMOS = 2

# `uuid4().hex` del Supervisor, o el mismo uuid con guiones.
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

# `SuggestionType` y `ContextType` del Supervisor 2026.11.0
# (`supervisor/resolution/const.py`). Un valor fuera de estas listas es de una
# versión que Hermes no conoce: `unknown_effect`.
_TIPOS_2026_11 = frozenset({
    "adopt_data_disk", "clear_full_backup", "clear_port_config",
    "create_full_backup", "disable_boot", "enable_ntp", "execute_reboot",
    "execute_rebuild", "execute_reload", "execute_remove", "execute_repair",
    "execute_reset", "execute_restart", "execute_start", "execute_stop",
    "execute_update", "move_local_data", "registry_login", "rename_data_disk",
})
_CONTEXTOS_2026_11 = frozenset({
    "addon", "core", "dns_server", "mount", "os", "plugin", "supervisor",
    "store", "system",
})
# Tipos que existen en el enum pero sin ningún fixup en 2026.11.0: el
# Supervisor respondería «ok» sin hacer nada.
_TIPOS_SIN_FIXUP = frozenset({"execute_stop", "execute_update", "registry_login"})
# Con fixup, pero Hermes no los aplica (research R-6).
_NO_PERMITIDOS: dict[tuple[str, str], str] = {
    ("adopt_data_disk", "system"): (
        "it relabels the data disks and reboots the host, which is like moving "
        "the data disk: left to the user in the Supervisor UI"),
    ("rename_data_disk", "system"): (
        "it relabels a data disk, which is like moving the data disk: left to "
        "the user in the Supervisor UI"),
}


@dataclass(frozen=True)
class _Fixup:
    effect: str
    interrupts: str
    duration: str | None
    reversible: bool | None


# Traducción de cada fixup del Supervisor 2026.11.0 (data-model, fuente:
# `supervisor/resolution/fixups/*.py`). Si una versión nueva del Supervisor
# cambia lo que hace un fixup, esta tabla se revisa con ella.
_FIXUPS: dict[tuple[str, str], _Fixup] = {
    ("clear_port_config", "addon"): _Fixup(
        "removes the conflicting port mapping from the app",
        "the app restarts if it is running", "seconds", True),
    ("disable_boot", "addon"): _Fixup(
        "the app no longer starts at boot", "nothing", None, True),
    ("execute_rebuild", "addon"): _Fixup(
        "rebuilds the app container", "the app", "minutes", True),
    ("execute_remove", "addon"): _Fixup(
        "uninstalls the app and deletes its data", "the app, permanently", None, False),
    ("execute_repair", "addon"): _Fixup(
        "downloads the app image again", "nothing", "minutes", True),
    ("execute_restart", "addon"): _Fixup(
        "restarts the app", "the app", "seconds", True),
    ("execute_start", "addon"): _Fixup(
        "starts the app", "nothing", "seconds", True),
    ("execute_rebuild", "core"): _Fixup(
        "rebuilds the Home Assistant Core container", "Home Assistant",
        "1-5 minutes", True),
    ("execute_reload", "mount"): _Fixup(
        "remounts the mount", "the mount", "seconds", True),
    ("execute_remove", "mount"): _Fixup(
        "removes the mount (the remote data is kept)", "the mount", None, False),
    ("move_local_data", "mount"): _Fixup(
        "moves the local data out of the mount target and remounts",
        "the mount", "minutes", False),
    ("execute_rebuild", "plugin"): _Fixup(
        "rebuilds the plugin container", "the plugin", "seconds", True),
    ("execute_reload", "store"): _Fixup(
        "reloads the store repository (internet)", "nothing", "seconds", True),
    ("execute_remove", "store"): _Fixup(
        "removes the store repository", "nothing", None, False),
    ("execute_reset", "store"): _Fixup(
        "clones the store repository again (internet)", "nothing", "seconds", True),
    ("clear_full_backup", "system"): _Fixup(
        "deletes all full backups except the 2 newest", "nothing", None, False),
    ("create_full_backup", "system"): _Fixup(
        "creates a full backup", "nothing (uses disk space)", "minutes", True),
    ("enable_ntp", "system"): _Fixup(
        "starts the time sync service", "nothing", None, True),
    ("execute_reboot", "system"): _Fixup(
        "reboots the host", "everything, Hermes included", "minutes", None),
    ("execute_rebuild", "system"): _Fixup(
        "rebuilds every container with a Docker configuration issue",
        "the rebuilt containers", "minutes", True),
    ("execute_reset", "system"): _Fixup(
        "clears the failed state of a systemd unit", "nothing", None, True),
    ("execute_restart", "system"): _Fixup(
        "restarts a systemd unit", "that unit", "seconds", True),
}


def _escalar(valor: Any) -> Any:
    return valor if isinstance(valor, (str, int, float, bool)) or valor is None else None


def _uuid_normal(valor: str) -> str:
    return valor.replace("-", "").lower()


def _texto(valor: Any) -> Any:
    """`redact_secrets` sobre todo texto anidado: `reference` es texto libre
    del Supervisor bajo una clave que no parece sensible (como en
    `tools/resolution.py`)."""
    if isinstance(valor, str):
        return redact_secrets(valor)
    if isinstance(valor, dict):
        return {k: _texto(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_texto(v) for v in valor]
    return valor


class _Rechazo(Exception):
    """Un rechazo sin token: `code` y los campos de la respuesta."""

    def __init__(self, code: str, **campos: Any) -> None:
        super().__init__(code)
        self.code = code
        self.campos = campos


def register(mcp: object, ha_client: HAClient, *, response_max_bytes: int) -> None:
    """Registra la tool que aplica sugerencias del centro de resolución."""

    def log_rechazo(code: str, tipo: Any = None, contexto: Any = None) -> None:
        logger.info("resolution_fix_rejected", suggestion_type=_escalar(tipo),
                    context=_escalar(contexto), code=code)

    def rechazado(code: str, tipo: Any = None, contexto: Any = None,
                  **campos: Any) -> dict[str, Any]:
        log_rechazo(code, tipo, contexto)
        return recortar_a_bytes(_texto(redact_structure({"error": code, **campos})),
                                response_max_bytes)

    async def leer(ruta: str) -> Any:
        try:
            return await ha_client.sv_request("GET", ruta, timeout_seconds=_TIEMPO_LECTURA)
        except (HAConnectionError, TimeoutError, aiohttp.ClientError) as exc:
            # Al log, solo el tipo y el `status`: el texto puede repetir datos.
            logger.warning("resolution_fix_read_failed", route=ruta.split("/")[1],
                           status=getattr(exc, "status", None),
                           exc_type=type(exc).__name__)
            raise _Rechazo("supervisor_request_failed", detail=_detalle(exc)) from exc

    async def slug_de_hermes() -> str:
        """El slug exacto del propio Hermes según el Supervisor. Sin él no se
        puede saber si algo apunta a Hermes: se rechaza (fail-closed)."""
        datos = await leer("/addons/self/info")
        slug = datos.get("slug") if isinstance(datos, dict) else None
        if not isinstance(slug, str) or not slug:
            raise _Rechazo("supervisor_request_failed",
                           detail="The Supervisor did not say which app Hermes is "
                                  "(/addons/self/info without slug).")
        return slug

    async def analizar(suggestion_uuid: str) -> dict[str, Any]:
        """Lee el estado actual y decide: lanza `_Rechazo` o devuelve la vista
        previa con su `estado`. Se llama al emitir el token y otra vez al
        confirmar, así que los rechazos se repiten con lo que haya ENTONCES."""
        info = await leer("/resolution/info")
        if not isinstance(info, dict):
            raise _Rechazo("supervisor_request_failed",
                           detail="Unexpected response from /resolution/info.")
        sugerencias = [s for s in info.get("suggestions") or [] if isinstance(s, dict)]
        issues = [i for i in info.get("issues") or [] if isinstance(i, dict)]
        buscado = _uuid_normal(suggestion_uuid)
        sug = next((s for s in sugerencias
                    if isinstance(s.get("uuid"), str)
                    and _uuid_normal(s["uuid"]) == buscado), None)
        if sug is None:
            raise _Rechazo("suggestion_not_found", suggestion_uuid=suggestion_uuid,
                           detail="There is no suggestion with that uuid now; "
                                  "list them with sv_get_resolution.")
        tipo, contexto = _escalar(sug.get("type")), _escalar(sug.get("context"))
        referencia = _escalar(sug.get("reference"))
        if tipo not in _TIPOS_2026_11 or contexto not in _CONTEXTOS_2026_11:
            raise _Rechazo(
                "unknown_effect", type=tipo, context=contexto,
                detail="Hermes does not know what this suggestion does (it is "
                       "newer than Supervisor 2026.11.0), so it cannot show an "
                       "honest preview. Apply it from the Supervisor UI if needed.")
        if (tipo, contexto) in _NO_PERMITIDOS:
            motivo = _NO_PERMITIDOS[(tipo, contexto)]
            raise _Rechazo("not_allowed", type=tipo, context=contexto, reason=motivo,
                           detail=f"Hermes does not apply {tipo}: {motivo}.")
        fixup = _FIXUPS.get((tipo, contexto))
        if tipo in _TIPOS_SIN_FIXUP or fixup is None:
            raise _Rechazo(
                "no_fixup", type=tipo, context=contexto,
                detail="The Supervisor has no automatic fix for this suggestion: "
                       "applying it would do nothing. It is advice for the user "
                       "(dismiss it with sv_dismiss_resolution_suggestion once "
                       "handled).")

        otras = [s for s in sugerencias if s is not sug]
        auto = [s for s in otras if s.get("auto") is True]
        contenedores = (
            [{"context": _escalar(s.get("context")), "reference": _escalar(s.get("reference"))}
             for s in otras if s.get("type") == "execute_rebuild"
             and s.get("context") != "system"]
            if (tipo, contexto) == ("execute_rebuild", "system") else [])

        # ¿Algo de esto toca al propio Hermes? Solo se pregunta al Supervisor
        # cuando hay una app en juego.
        apps = ([referencia] if contexto == "addon" else []) + [
            c["reference"] for c in contenedores if c["context"] == "addon"] + [
            _escalar(s.get("reference")) for s in auto if s.get("context") == "addon"]
        if apps:
            hermes = await slug_de_hermes()
            if contexto == "addon" and referencia == hermes:
                motivo = "the suggestion acts on Hermes itself"
            elif any(c["context"] == "addon" and c["reference"] == hermes
                     for c in contenedores):
                motivo = "Hermes is among the containers that would be rebuilt"
            elif any(s.get("context") == "addon" and s.get("reference") == hermes
                     for s in auto):
                motivo = ("one of the automatic fixes the Supervisor applies "
                          "afterwards acts on Hermes itself")
            else:
                motivo = ""
            if motivo:
                raise _Rechazo(
                    "targets_hermes", type=tipo, context=contexto,
                    detail=f"Refused: {motivo}. Hermes would stop or remove itself "
                           "in the middle of the call and could not report or "
                           "recover. Apply it from the Supervisor UI.")

        detalles: dict[str, Any] = {}
        avisos: list[str] = []
        efecto = fixup.effect
        a_borrar: list[dict[str, Any]] = []
        if (tipo, contexto) == ("clear_full_backup", "system"):
            datos = await leer("/backups")
            lista = datos.get("backups") if isinstance(datos, dict) else None
            if not isinstance(lista, list):
                raise _Rechazo("supervisor_request_failed",
                               detail="Unexpected response from /backups.")
            completos = sorted(
                (b for b in lista if isinstance(b, dict) and b.get("type") == "full"),
                key=lambda b: str(b.get("date") or ""))
            a_borrar = [{"slug": _escalar(b.get("slug")), "name": _escalar(b.get("name")),
                         "date": _escalar(b.get("date")), "size": _escalar(b.get("size"))}
                        for b in completos[:-_BACKUPS_COMPLETOS_MINIMOS]]
            detalles["backups_to_delete"] = a_borrar
            if not a_borrar:
                efecto = (f"deletes nothing: there are {len(completos)} full backups "
                          f"and the Supervisor keeps the {_BACKUPS_COMPLETOS_MINIMOS} "
                          "newest")
            else:
                avisos.append(f"{len(a_borrar)} full backup(s) will be deleted for "
                              "good; partial backups are not touched.")
        if contenedores:
            detalles["containers_to_rebuild"] = contenedores
        if contexto == "addon" and isinstance(referencia, str):
            app: dict[str, Any] = {"slug": referencia, "name": None, "state": None}
            try:
                validate_slug(referencia)
                datos = await leer(f"/addons/{referencia}/info")
                if isinstance(datos, dict):
                    app.update(name=_escalar(datos.get("name")),
                               state=_escalar(datos.get("state")))
            except (InvalidIdentifier, _Rechazo):
                # Solo es contexto para la vista previa: sin él se avisa.
                avisos.append("Hermes could not read the app's name and state.")
            detalles["app"] = app

        # Irreversible, salvo un `clear_full_backup` que no borraría nada.
        nada_que_borrar = (tipo, contexto) == ("clear_full_backup", "system") and not a_borrar
        if fixup.reversible is False and not nada_que_borrar:
            avisos.append("This cannot be undone.")
        if (tipo, contexto) == ("execute_reboot", "system"):
            avisos.append("The whole host reboots: Home Assistant, the apps and "
                          "Hermes go down for minutes; Hermes comes back by itself.")
        tambien = [{"uuid": _escalar(s.get("uuid")), "type": _escalar(s.get("type")),
                    "context": _escalar(s.get("context"))} for s in auto]
        if tambien:
            avisos.append(
                "After the fix the Supervisor runs its health check, which may "
                "also apply its automatic fixes listed in also_auto_applied.")

        preview = {
            "action": "apply_resolution_suggestion",
            "suggestion": {"uuid": _escalar(sug.get("uuid")), "type": tipo,
                           "context": contexto, "reference": referencia,
                           "auto": sug.get("auto") if isinstance(sug.get("auto"), bool)
                           else None},
            "issues": [{"uuid": _escalar(i.get("uuid")), "type": _escalar(i.get("type")),
                        "context": _escalar(i.get("context")),
                        "reference": _escalar(i.get("reference"))}
                       for i in issues
                       if i.get("context") == contexto and i.get("reference") == referencia],
            "effect": efecto,
            "interrupts": fixup.interrupts,
            "duration": fixup.duration,
            "reversible": fixup.reversible,
            "details": detalles,
            "also_auto_applied": tambien,
            "warnings": avisos,
            "verify_with": "sv_get_resolution",
        }
        estado = {
            "type": tipo, "context": contexto, "reference": referencia,
            "backups_to_delete": [b["slug"] for b in a_borrar],
            "containers_to_rebuild": contenedores,
            "also_auto_applied": [t["uuid"] for t in tambien],
        }
        return {"preview": _texto(redact_structure(preview)), "estado": estado,
                "uuid": sug["uuid"], "type": tipo, "context": contexto,
                "effect": efecto}

    @mcp.tool()
    async def sv_apply_resolution_suggestion(
        suggestion_uuid: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Apply a Supervisor resolution suggestion (from sv_get_resolution).
        Two steps: the first call returns a preview that explains what the
        fix does (effect, what it interrupts, duration, whether it can be
        undone, and concrete details such as the full backups it would
        delete) and a confirmation_token; repeat with the same
        suggestion_uuid and the token to apply it. Some fixes delete data
        (an app with its data, old full backups) or reboot the host.
        Refused without a token: suggestions the Supervisor has no fix for
        (no_fixup), that Hermes cannot explain (unknown_effect), that touch
        the data disks (not_allowed) or that act on Hermes itself
        (targets_hermes). After the fix the Supervisor may also apply its
        automatic fixes; the preview lists them (also_auto_applied) and, if
        anything changes before confirming, nothing is applied
        (suggestion_changed). Check the result with sv_get_resolution.
        """
        if not isinstance(suggestion_uuid, str) or not _UUID_RE.fullmatch(suggestion_uuid):
            return rechazado("invalid_argument", field="suggestion_uuid",
                             detail="suggestion_uuid must be the uuid of a suggestion "
                                    "(32 hexadecimal characters) from sv_get_resolution.")
        args = {"suggestion_uuid": _uuid_normal(suggestion_uuid)}
        try:
            analisis = await analizar(suggestion_uuid)
        except _Rechazo as r:
            return rechazado(r.code, r.campos.get("type"), r.campos.get("context"),
                             **r.campos)
        tipo, contexto = analisis["type"], analisis["context"]
        if not confirmation_token:
            logger.info("resolution_fix_preview", suggestion_type=tipo, context=contexto,
                        outcome="token_issued")
            return recortar_a_bytes(
                await create_confirmation_token(_TOOL, args, preview=analisis["preview"],
                                                estado=analisis["estado"]),
                response_max_bytes)
        ok, motivo, _ = await resolve_confirmation_token(
            confirmation_token, _TOOL, args, estado=analisis["estado"])
        if not ok:
            if motivo == ESTADO_CAMBIADO:
                # La sugerencia, los backups a borrar, los contenedores o los
                # arreglos automáticos ya no son los de la vista previa.
                return rechazado("suggestion_changed", tipo, contexto,
                                 detail="The suggestion or what it would touch changed "
                                        "since the preview (including the automatic "
                                        "fixes). Nothing was applied; request a new "
                                        "preview.")
            return rechazado("invalid_confirmation_token", tipo, contexto, detail=motivo)

        try:
            # La ruta, literal en la llamada: la guarda de test_tools_resolution
            # la busca para comprobar que solo este módulo aplica sugerencias.
            await ha_client.sv_request("POST", f"/resolution/suggestion/{analisis['uuid']}",
                                       timeout_seconds=_TIEMPO_FIXUP)
        except (HAConnectionError, TimeoutError, aiohttp.ClientError) as exc:
            if _es_corte(exc):
                resp = {"status": "started", "verify_with": "sv_get_resolution",
                        "note": "The request was sent but Hermes stopped waiting for "
                                "the answer (time limit reached or connection lost): "
                                "it cannot tell whether the fix finished. Check with "
                                "sv_get_resolution."}
                await complete_confirmation_token(confirmation_token, success=True,
                                                  result=resp)
                logger.info("resolution_fix_done", suggestion_type=tipo,
                            context=contexto, outcome="started")
                return resp
            await complete_confirmation_token(confirmation_token, success=False,
                                              error="supervisor_request_failed")
            logger.warning("resolution_fix_rejected", suggestion_type=tipo,
                           context=contexto, code="supervisor_request_failed",
                           status=getattr(exc, "status", None),
                           exc_type=type(exc).__name__)
            return {"error": "supervisor_request_failed", "detail": _detalle(exc)}
        resp = {"result": "ok", "effect": analisis["effect"],
                "verify_with": "sv_get_resolution"}
        await complete_confirmation_token(confirmation_token, success=True, result=resp)
        logger.info("resolution_fix_done", suggestion_type=tipo, context=contexto,
                    outcome="ok")
        return resp
