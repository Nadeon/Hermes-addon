"""Hermes — Control de Core y del Supervisor (spec 022, tramo 1; CAP-084).

Familia `system_control` (1.2.0), módulo `system_control`.

Tools:
  sv_start_core             — arranca Core si está parado (token)
  sv_rebuild_core           — reconstruye el contenedor de Core (token)
  sv_set_core_options       — opciones de Core, lista cerrada (token)
  sv_reload_supervisor      — el Supervisor relee versiones y secretos (sin token)
  sv_restart_supervisor     — reinicia el Supervisor (token)
  sv_repair_supervisor      — repara el entorno Docker del Supervisor (token)
  sv_set_supervisor_options — opciones del Supervisor, lista cerrada (token)

POR QUÉ
-------
Con Core parado o roto, la interfaz de Home Assistant no existe, pero Hermes
sí: sus tools `sv_*` hablan con el Supervisor, no con Core (research de la
022, «Lo que hay hoy»). Arrancar o reconstruir Core desde aquí es la forma de
recuperar una casa sin abrir la interfaz del Supervisor.

Todo lo que corta el servicio se confirma en dos pasos con una vista previa
que dice QUÉ se corta, CUÁNTO y qué le pasa a Hermes (research R-5). Lo que
haría perder trabajo en curso (reiniciar o reparar el Supervisor con jobs sin
terminar) se rechaza sin token. Las opciones van por listas cerradas (R-3 y
R-4): lo que permitiría ejecutar código arbitrario (`image`), es un secreto
(`refresh_token`), dejaría a Hermes sin Core (`port`, `ssl`) o es de
desarrollo (`channel`, `debug`…) se rechaza sin llamar.

Si Hermes no puede saber si una operación terminó (tiempo vencido o conexión
cortada), lo dice: `status: "started"` con la tool con la que comprobarlo,
nunca un «ok» ni un error inventados (R-7, principio V).

Al log van la tool, la ruta, los NOMBRES de las claves y el resultado; nunca
valores (zona horaria, país, dispositivos de audio) ni el texto de un error
del Supervisor, que puede repetir lo enviado (principio II).
"""

from __future__ import annotations

import re
from typing import Any

import aiohttp
import structlog

from hermes.fs_write import check_restart_allowed_sync
from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    redact_structure,
    resolve_confirmation_token,
)
from hermes.tools._common import recortar_a_bytes
from hermes.tools._eco_supervisor import sin_eco_del_supervisor

logger = structlog.get_logger(__name__)

# Tiempos de espera (research R-7). `start`, `rebuild` y `repair` esperan en
# el Supervisor a que la operación termine; con una imagen grande o un disco
# lento son minutos. Más allá, Hermes deja de esperar y lo dice.
_TIEMPO_START = 600.0
_TIEMPO_REBUILD = 600.0
_TIEMPO_REPAIR = 900.0
# El reinicio responde al entrar en STOPPING: un minuto basta para la
# respuesta; lo que tarda en volver se comprueba después.
_TIEMPO_RESTART = 60.0
_TIEMPO_RELOAD = 120.0
_TIEMPO_LECTURA = 15.0

_DETALLE_MAX = 500

# ── Listas cerradas de opciones (research R-3 y R-4) ─────────────────────────

_CORE_BOOL = ("boot", "watchdog", "backups_exclude_database", "duplicate_log_file")
_CORE_AUDIO = ("audio_input", "audio_output")
_CORE_ADMITIDAS = _CORE_BOOL + _CORE_AUDIO
_AUDIO_MAX = 128
_CORE_RECHAZADAS: dict[str, str] = {
    "image": ("it replaces Core's Docker image with any image, which is running "
              "arbitrary code as Home Assistant"),
    "refresh_token": "it is a secret and never goes through the MCP client",
    "port": ("the Supervisor (and Hermes through it) reaches Core on this port; "
             "a value that does not match Core's http settings cuts Hermes off "
             "from Core"),
    "ssl": ("the Supervisor (and Hermes through it) reaches Core with this "
            "setting; a value that does not match Core's http settings cuts "
            "Hermes off from Core"),
}

_SV_LOGGING = ("debug", "info", "warning", "error", "critical")
_SV_BOOL = ("auto_update", "diagnostics")
_SV_ADMITIDAS = ("timezone", "country", "logging") + _SV_BOOL
# Forma de zona IANA; la lista real la valida el Supervisor. Sin `.` ni
# espacios: «../x» no pasa.
_TIMEZONE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+\-/]{0,63}")
_COUNTRY_RE = re.compile(r"[A-Z]{2}")
_SV_RECHAZADAS: dict[str, str] = {
    "channel": ("switching the update channel (beta, dev) is left to the user "
                "in the Supervisor UI"),
    "debug": "developer option",
    "debug_block": "developer option",
    "detect_blocking_io": "developer option",
    "feature_flags": "developer option",
    "addons_repositories": ("store repositories are managed by the store tools, "
                            "not as a Supervisor option"),
    "wait_boot": "legacy option of the v1 API",
}

# ── Lo que corta cada operación (data-model, «Vista previa de interrupción») ─

_HERMES_CON_CORE_CAIDO = (
    "Hermes keeps running while Core is down (its sv_* tools talk to the "
    "Supervisor) and reconnects to Core by itself when it is back."
)

_PASOS_REPAIR = [
    "prune Docker: stopped containers, unused images, build cache and unused volumes",
    "repair the plugins (DNS, audio, CLI, observer, multicast)",
    "repair the apps (add-ons): download any missing image",
    "repair Home Assistant Core: download its image if missing",
    "re-tag the Supervisor image",
]


def _detalle(exc: BaseException, *enviado: Any) -> str:
    """Texto de un error del Supervisor, sin secretos y recortado.

    Sin el eco de lo enviado (cierre de seguridad de la 1.2.0): `/core/options`
    y `/supervisor/options` se validan con `api_validate`, que repite el valor
    rechazado con «Got …». Se limpia ANTES de recortar."""
    return sin_eco_del_supervisor(str(exc), *enviado)[:_DETALLE_MAX]


def _no_enviada(exc: BaseException) -> bool:
    """True si la petición NO llegó a salir hacia el Supervisor.

    El cliente HTTP sin inicializar (`HAConnectionError` con `sent=False`) o
    una conexión que ni se estableció (`ClientConnectorError`: rechazada, sin
    ruta, DNS) no pueden haber hecho nada en el Supervisor. Decir entonces
    `status: "started"` y «the request was sent» sería mentir (spec 022,
    T032; principio V).
    """
    return (getattr(exc, "sent", None) is False
            or isinstance(exc, aiohttp.ClientConnectorError))


def _error_sv(exc: BaseException, *enviado: Any) -> dict[str, Any]:
    """Respuesta de error de una petición al Supervisor: redactada y, si no
    llegó a salir, diciendo que no se hizo nada."""
    resp: dict[str, Any] = {"error": "supervisor_request_failed",
                            "detail": _detalle(exc, *enviado)}
    if _no_enviada(exc):
        resp["sent"] = False
        resp["note"] = ("The request never reached the Supervisor: nothing was "
                        "done. Try again when Hermes is connected.")
    return resp


def _es_corte(exc: BaseException) -> bool:
    """True si Hermes no puede saber si el Supervisor hizo la operación.

    Un tiempo vencido o una conexión cortada antes de la respuesta (la del
    reinicio del Supervisor, que se lleva su propia API) no dicen nada del
    resultado. Un `HAConnectionError` con `status`, o con el `result: error`
    del Supervisor, sí: es un error de verdad (research R-7 y R-12). Y una
    petición que ni salió (`_no_enviada`) tampoco es un corte: no se hizo.
    """
    if _no_enviada(exc):
        return False
    if isinstance(exc, (TimeoutError, aiohttp.ClientConnectionError)):
        return True
    if isinstance(exc, HAConnectionError):
        texto = str(exc)
        return exc.status is None and not texto.startswith("Supervisor error:")
    return False


def _es_core_parado(exc: BaseException) -> bool:
    """El error con el que el Supervisor 2026.11.0 responde a `/core/stats`
    cuando Core no corre (`HomeAssistantNotRunningError`)."""
    texto = str(exc)
    return ("homeassistant_not_running_error" in texto
            or "Home Assistant is not running" in texto)


def _jobs_en_curso(datos: Any) -> list[dict[str, Any]]:
    """Jobs del árbol de `/jobs/info` que no han terminado, hijos incluidos.

    `done` es `None` en un job creado y aún no arrancado: también cuenta
    (fail-closed). Una forma inesperada lanza `ValueError`: sin saber si hay
    jobs, no se reinicia.
    """
    if not isinstance(datos, dict) or not isinstance(datos.get("jobs"), list):
        raise ValueError("unexpected /jobs/info shape")
    salida: list[dict[str, Any]] = []
    pendientes = list(datos["jobs"])
    while pendientes:
        job = pendientes.pop(0)
        if not isinstance(job, dict):
            raise ValueError("unexpected job shape")
        if job.get("done") is not True:
            salida.append({"name": job.get("name"), "progress": job.get("progress"),
                           "stage": job.get("stage")})
        hijos = job.get("child_jobs") or []
        if not isinstance(hijos, list):
            raise ValueError("unexpected child_jobs shape")
        pendientes.extend(hijos)
    return salida


def _validar_opciones(
    options: Any,
    admitidas: tuple[str, ...],
    rechazadas: dict[str, str],
    validar_valor: Any,
) -> dict[str, Any] | None:
    """Error de validación de `options`, o `None` si vale. Nada llama al
    Supervisor antes de pasar por aquí."""
    if not isinstance(options, dict) or not options:
        return {"error": "invalid_argument", "field": "options",
                "detail": "options must be a non-empty object."}
    for clave in sorted(options, key=str):
        if clave in rechazadas:
            return {"error": "not_allowed", "field": clave,
                    "allowed": list(admitidas),
                    "reason": rechazadas[clave],
                    "detail": f"Hermes does not change {clave!r}: {rechazadas[clave]}."}
    for clave in sorted(options, key=str):
        if clave not in admitidas:
            return {"error": "invalid_argument", "field": str(clave),
                    "detail": f"Unknown option {clave!r}. Accepted: "
                              f"{', '.join(admitidas)}."}
        problema = validar_valor(clave, options[clave])
        if problema:
            return {"error": "invalid_argument", "field": clave, "detail": problema}
    return None


def _valor_core(clave: str, valor: Any) -> str | None:
    if clave in _CORE_BOOL:
        return None if isinstance(valor, bool) else f"{clave} must be true or false."
    # Audio: el nombre de un dispositivo de PulseAudio o null (por defecto).
    if valor is None or (isinstance(valor, str) and len(valor) <= _AUDIO_MAX):
        return None
    return f"{clave} must be a device name of at most {_AUDIO_MAX} characters, or null."


def _valor_supervisor(clave: str, valor: Any) -> str | None:
    if clave in _SV_BOOL:
        return None if isinstance(valor, bool) else f"{clave} must be true or false."
    if clave == "timezone":
        if isinstance(valor, str) and _TIMEZONE_RE.fullmatch(valor):
            return None
        return "timezone must look like an IANA time zone, e.g. 'Europe/Madrid'."
    if clave == "country":
        if isinstance(valor, str) and _COUNTRY_RE.fullmatch(valor):
            return None
        return "country must be a two-letter ISO 3166-1 code in capitals, e.g. 'ES'."
    if isinstance(valor, str) and valor in _SV_LOGGING:
        return None
    return f"logging must be one of: {', '.join(_SV_LOGGING)}."


def _avisos_core(cambios: dict[str, Any], info: dict[str, Any]) -> list[str]:
    avisos: list[str] = []
    nuevo = {k: v["new"] for k, v in cambios.items()}
    if nuevo.get("boot") is False:
        avisos.append("boot=false: after a host reboot Home Assistant stays stopped; "
                      "start it with sv_start_core.")
    if nuevo.get("watchdog") is False:
        avisos.append("watchdog=false: the Supervisor will not restart Home "
                      "Assistant if it crashes.")
    if nuevo.get("backups_exclude_database") is True:
        avisos.append("backups_exclude_database=true: backups will not include the "
                      "recorder database (history).")
    for clave in ("duplicate_log_file", *_CORE_AUDIO):
        if clave in nuevo:
            avisos.append(f"{clave}: applies the next time Core starts or is rebuilt.")
    return avisos


def _avisos_supervisor(cambios: dict[str, Any], info: dict[str, Any]) -> list[str]:
    """Avisos de `sv_set_supervisor_options`, leídos en el Supervisor 2026.11.0
    (T034): `evaluations/supervisor_version.py`, la condición
    `SUPERVISOR_UPDATED` de los jobs de OS, plugins y tienda,
    `Supervisor.auto_update_supervisor` y `APISupervisor._options` (que también
    llama a `dbus.agent.set_diagnostics`)."""
    avisos: list[str] = []
    nuevo = {k: v["new"] for k, v in cambios.items()}
    hay_version_nueva = info.get("update_available") is True
    if nuevo.get("auto_update") is False:
        avisos.append(
            "auto_update=false: once a newer Supervisor exists"
            + (" (one exists now)" if hay_version_nueva else "")
            + ", the installation is marked unsupported and, until the Supervisor "
            "is updated, installing or updating apps, updating Core, updating "
            "the OS and the plugins, reloading the store and adding store "
            "repositories are blocked.")
    if nuevo.get("auto_update") is True:
        avisos.append(
            "auto_update=true: whenever a newer Supervisor exists"
            + (" (one exists now, so soon)" if hay_version_nueva else "")
            + ", the Supervisor updates and restarts itself on its own; meanwhile "
            "Hermes loses its sv_* tools and its connection to Core for about "
            "30-90 seconds and then reconnects.")
    if "timezone" in nuevo:
        avisos.append("timezone: also changes the host time zone; Home Assistant's "
                      "own time zone is a Core setting.")
    if nuevo.get("diagnostics") is True:
        avisos.append("diagnostics=true: crash reports are sent to a third party "
                      "(Sentry). It also turns on the OS Agent's diagnostics.")
    if nuevo.get("diagnostics") is False:
        avisos.append("diagnostics=false: also turns off the OS Agent's "
                      "diagnostics, not only the Supervisor's.")
    if nuevo.get("logging") == "debug":
        avisos.append("logging=debug: very verbose Supervisor log.")
    return avisos


def register(mcp: object, ha_client: HAClient, *, response_max_bytes: int) -> None:
    """Registra las tools de control de Core y del Supervisor."""

    def rechazado(tool: str, ruta: str, code: str, keys: list[str] | None = None,
                  **resp: Any) -> dict[str, Any]:
        logger.info("system_control_rejected", tool=tool, route=ruta,
                    keys=keys or [], code=code)
        return recortar_a_bytes({"error": code, **resp}, response_max_bytes)

    def error_sv(tool: str, ruta: str, exc: BaseException,
                 keys: list[str] | None = None, enviado: Any = None) -> dict[str, Any]:
        # Al log, solo el tipo y el `status`: el texto puede repetir lo enviado.
        logger.warning("system_control_rejected", tool=tool, route=ruta,
                       keys=keys or [], code="supervisor_request_failed",
                       status=getattr(exc, "status", None),
                       exc_type=type(exc).__name__)
        return _error_sv(exc, *(() if enviado is None else (enviado,)))

    def vista_previa_emitida(tool: str, ruta: str, keys: list[str] | None = None) -> None:
        logger.info("system_control_preview", tool=tool, route=ruta,
                    keys=keys or [], outcome="token_issued")

    def hecho(tool: str, ruta: str, outcome: str, keys: list[str] | None = None) -> None:
        logger.info("system_control_done", tool=tool, route=ruta,
                    keys=keys or [], outcome=outcome)

    async def token_invalido(tool: str, ruta: str, motivo: str,
                             keys: list[str] | None = None) -> dict[str, Any]:
        return rechazado(tool, ruta, "invalid_confirmation_token", keys, detail=motivo)

    async def leer_version(ruta: str) -> Any:
        try:
            datos = await ha_client.sv_request("GET", ruta, timeout_seconds=_TIEMPO_LECTURA)
        except (HAConnectionError, TimeoutError, aiohttp.ClientError):
            return None
        return datos.get("version") if isinstance(datos, dict) else None

    async def estado_core() -> str:
        """`running`, `stopped` o `unknown` según `GET /core/stats`."""
        try:
            await ha_client.sv_request("GET", "/core/stats", timeout_seconds=_TIEMPO_LECTURA)
        except (HAConnectionError, TimeoutError, aiohttp.ClientError) as exc:
            return "stopped" if _es_core_parado(exc) else "unknown"
        return "running"

    async def ejecutar_larga(
        tool: str, ruta: str, token: str, *, cuerpo: dict[str, Any] | None,
        tiempo: float, verify_with: str, ok: dict[str, Any], keys: list[str] | None = None,
    ) -> dict[str, Any]:
        """Hace el `POST` de una operación larga y dice la verdad del resultado.

        Si el Supervisor responde, `ok`. Si vence el tiempo o se corta la
        conexión, Hermes no sabe si terminó: `status: "started"` con la tool
        con la que comprobarlo (research R-7). Un error del Supervisor,
        redactado. El token se cierra en los tres casos: la petición salió.
        """
        try:
            await ha_client.sv_request("POST", ruta, json_body=cuerpo, timeout_seconds=tiempo)
        except (HAConnectionError, TimeoutError, aiohttp.ClientError) as exc:
            if _es_corte(exc):
                resp = {
                    "status": "started", "verify_with": verify_with,
                    "note": ("The request was sent but Hermes stopped waiting for "
                             "the answer (time limit reached or connection lost): "
                             "it cannot tell whether the operation finished or "
                             f"succeeded. Check with {verify_with}."),
                }
                await complete_confirmation_token(token, success=True, result=resp)
                hecho(tool, ruta, "started", keys)
                return resp
            await complete_confirmation_token(token, success=False,
                                              error="supervisor_request_failed")
            return error_sv(tool, ruta, exc, keys, cuerpo)
        await complete_confirmation_token(token, success=True, result=ok)
        hecho(tool, ruta, "ok", keys)
        return ok

    # ── Core ─────────────────────────────────────────────────────────────────

    @mcp.tool()
    async def sv_start_core(confirmation_token: str | None = None) -> object:
        """Start Home Assistant Core when it is stopped (for example after a
        crash, or with boot disabled). Two steps: the first call returns a
        preview (Core state, version, how long it usually takes) and a
        confirmation_token; repeat it with the token to start Core. If Core
        is already running it does nothing and returns `already_running`
        (also at confirmation time). Hermes keeps working while Core is
        down: it talks to the Supervisor. Waits up to 10 minutes; if that is
        not enough the answer is `status: "started"`: check with
        sv_get_core_info.
        """
        tool, ruta = "sv_start_core", "/core/start"
        estado = await estado_core()
        if estado == "running":
            return rechazado(tool, ruta, "already_running",
                             detail="Home Assistant Core is already running; nothing to do.")
        if not confirmation_token:
            permitido, motivo = check_restart_allowed_sync()
            avisos: list[str] = []
            if not permitido:
                # Arrancar es recuperar: se avisa, no se bloquea (FR-001).
                avisos.append(f"{motivo} Core will load the configuration as it "
                              "is now; sv_check_core_config validates it.")
            if estado == "unknown":
                avisos.append("Hermes could not tell whether Core is running "
                              "(the Supervisor gave an unexpected error).")
            preview = {
                "action": "start_core",
                "core_state": estado,
                "version": await leer_version("/core/info"),
                "interrupts": {
                    "stops": [],
                    "keeps_running": ["apps (add-ons)", "Supervisor"],
                    "duration": "about 1-5 minutes until Home Assistant is fully up",
                },
                "hermes": _HERMES_CON_CORE_CAIDO,
                "warnings": avisos,
                "blocked": None,
            }
            vista_previa_emitida(tool, ruta)
            return await create_confirmation_token(
                tool, {}, preview=preview, estado={"core_state": estado})
        ok, motivo, _ = await resolve_confirmation_token(
            confirmation_token, tool, {}, estado={"core_state": estado})
        if not ok:
            return await token_invalido(tool, ruta, motivo)
        return await ejecutar_larga(
            tool, ruta, confirmation_token, cuerpo=None, tiempo=_TIEMPO_START,
            verify_with="sv_get_core_info",
            ok={"result": "ok", "note": "Core started. Integrations may still be "
                                        "loading; check with sv_get_core_info."})

    @mcp.tool()
    async def sv_rebuild_core(
        safe_mode: bool = False,
        confirmation_token: str | None = None,
    ) -> object:
        """Rebuild the Home Assistant Core container: Core is stopped and
        recreated, so Home Assistant is down for a few minutes (Hermes keeps
        running and reconnects). `safe_mode=true` starts Core in safe mode:
        custom integrations and YAML are not loaded. Two steps (preview +
        confirmation_token; the token binds safe_mode). Blocked like
        sv_restart_core while there are /config writes not validated with
        sv_check_core_config. Waits up to 10 minutes; if that is not enough
        the answer is `status: "started"`: check with sv_get_core_info.
        """
        tool, ruta = "sv_rebuild_core", "/core/rebuild"
        if not isinstance(safe_mode, bool):
            return rechazado(tool, ruta, "invalid_argument", field="safe_mode",
                             detail="safe_mode must be true or false.")
        args = {"safe_mode": safe_mode}
        if not confirmation_token:
            permitido, motivo = check_restart_allowed_sync()
            preview = {
                "action": "rebuild_core",
                "version": await leer_version("/core/info"),
                "safe_mode": safe_mode,
                "safe_mode_meaning": (
                    "Core starts in safe mode: custom integrations and YAML are "
                    "not loaded" if safe_mode else
                    "Core starts normally, with custom integrations and YAML"),
                "interrupts": {
                    "stops": ["Home Assistant Core"],
                    "keeps_running": ["apps (add-ons)", "Supervisor"],
                    "duration": "about 1-5 minutes (longer with a large image)",
                },
                "hermes": _HERMES_CON_CORE_CAIDO,
                "warnings": [],
                "blocked": None,
            }
            if not permitido:
                # Mismo bloqueo que sv_restart_core: el token se emite, pero la
                # confirmación se rechaza mientras siga sin validar.
                preview["blocked"] = (f"{motivo} Call sv_check_core_config first "
                                      "to clear the block.")
            vista_previa_emitida(tool, ruta, ["safe_mode"])
            return await create_confirmation_token(tool, args, preview=preview)
        ok, motivo, _ = await resolve_confirmation_token(confirmation_token, tool, args)
        if not ok:
            return await token_invalido(tool, ruta, motivo, ["safe_mode"])
        permitido, motivo = check_restart_allowed_sync()
        if not permitido:
            await complete_confirmation_token(confirmation_token, success=False, error=motivo)
            return rechazado(tool, ruta, "blocked", ["safe_mode"], detail=motivo,
                             hint="Call sv_check_core_config first to clear the block.")
        # Nunca `force`: se saltaría la comprobación de una migración offline
        # de la base de datos (research, tabla del Supervisor).
        return await ejecutar_larga(
            tool, ruta, confirmation_token, cuerpo={"safe_mode": safe_mode},
            tiempo=_TIEMPO_REBUILD, verify_with="sv_get_core_info",
            ok={"result": "ok", "safe_mode": safe_mode,
                "note": "Core rebuilt. Integrations may still be loading; check "
                        "with sv_get_core_info."},
            keys=["safe_mode"])

    async def opciones(
        tool: str, ruta_info: str, ruta: str, options: Any, confirmation_token: str | None,
        admitidas: tuple[str, ...], rechazadas: dict[str, str], validar_valor: Any,
        avisos: Any, accion: str,
    ) -> dict[str, Any]:
        """Flujo común de las dos tools de opciones (data-model): diferencia por
        clave con lo actual, `no_changes`, token atado a `options` y, como
        estado, a los valores actuales; solo se envían las claves que
        cambian."""
        error = _validar_opciones(options, admitidas, rechazadas, validar_valor)
        claves = sorted(str(k) for k in options) if isinstance(options, dict) else []
        if error is not None:
            code = error.pop("error")
            return rechazado(tool, ruta, code, claves, **error)
        try:
            info = await ha_client.sv_request("GET", ruta_info, timeout_seconds=_TIEMPO_LECTURA)
        except (HAConnectionError, TimeoutError, aiohttp.ClientError) as exc:
            return error_sv(tool, ruta_info, exc, claves)
        if not isinstance(info, dict):
            return rechazado(tool, ruta_info, "supervisor_request_failed", claves,
                             detail="The Supervisor returned an unexpected response shape.")
        actuales = {k: info.get(k) for k in claves}
        cambios = {k: {"current": actuales[k], "new": options[k]}
                   for k in claves if actuales[k] != options[k]}
        sin_cambio = [k for k in claves if k not in cambios]
        normalizado = {k: options[k] for k in claves}
        args = {"options": normalizado}
        if not confirmation_token:
            if not cambios:
                return rechazado(tool, ruta, "no_changes", claves, unchanged=sin_cambio,
                                 detail="Every option already has that value.")
            preview = {
                "action": accion,
                "changes": redact_structure(cambios),
                "unchanged": sin_cambio,
                "restart_needed": False,
                "warnings": avisos(cambios, info),
            }
            vista_previa_emitida(tool, ruta, claves)
            return await create_confirmation_token(tool, args, preview=preview,
                                                   estado=actuales)
        ok, motivo, _ = await resolve_confirmation_token(
            confirmation_token, tool, args, estado=actuales)
        if not ok:
            return await token_invalido(tool, ruta, motivo, claves)
        cuerpo = {k: v["new"] for k, v in cambios.items()}
        try:
            await ha_client.sv_request("POST", ruta, json_body=cuerpo,
                                       timeout_seconds=_TIEMPO_LECTURA)
        except (HAConnectionError, TimeoutError, aiohttp.ClientError) as exc:
            await complete_confirmation_token(confirmation_token, success=False,
                                              error="supervisor_request_failed")
            return error_sv(tool, ruta, exc, claves, cuerpo)
        resp = {"result": "ok", "changed": sorted(cuerpo), "restart_needed": False}
        await complete_confirmation_token(confirmation_token, success=True, result=resp)
        hecho(tool, ruta, "ok", claves)
        return resp

    @mcp.tool()
    async def sv_set_core_options(
        options: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Change Home Assistant Core's Supervisor options. Accepted keys:
        boot, watchdog, backups_exclude_database, duplicate_log_file
        (true/false) and audio_input, audio_output (device name or null).
        image, refresh_token, port and ssl are refused (not_allowed). Two
        steps: the preview shows, per key, the current and the new value and
        warns about boot=false and watchdog=false; repeat with the same
        options plus confirmation_token. Nothing restarts now; audio and
        duplicate_log_file apply the next time Core starts or is rebuilt.
        Returns no_changes when every value is already set.
        """
        return await opciones(
            "sv_set_core_options", "/core/info", "/core/options", options,
            confirmation_token, _CORE_ADMITIDAS, _CORE_RECHAZADAS, _valor_core,
            _avisos_core, "set_core_options")

    # ── Supervisor ───────────────────────────────────────────────────────────

    @mcp.tool()
    async def sv_reload_supervisor() -> object:
        """Ask the Supervisor to reload: it reads the available versions
        again (from the internet when online), reloads secrets and
        re-evaluates the system. Nothing is interrupted and no confirmation
        is needed.
        """
        tool, ruta = "sv_reload_supervisor", "/supervisor/reload"
        try:
            await ha_client.sv_request("POST", ruta, timeout_seconds=_TIEMPO_RELOAD)
        except (HAConnectionError, TimeoutError, aiohttp.ClientError) as exc:
            return error_sv(tool, ruta, exc)
        hecho(tool, ruta, "ok")
        return {"result": "ok", "note": "versions, secrets and system evaluation reloaded"}

    async def comprobar_jobs(tool: str, ruta: str) -> dict[str, Any] | None:
        """Rechazo si hay jobs del Supervisor sin terminar, o si no se puede
        saber (fail-closed): reiniciar o reparar los perdería."""
        try:
            datos = await ha_client.sv_request("GET", "/jobs/info",
                                               timeout_seconds=_TIEMPO_LECTURA)
            en_curso = _jobs_en_curso(datos)
        except (HAConnectionError, TimeoutError, aiohttp.ClientError) as exc:
            return error_sv(tool, "/jobs/info", exc)
        except ValueError:
            return rechazado(tool, "/jobs/info", "supervisor_request_failed",
                             detail="The Supervisor's job list has an unexpected "
                                    "shape; Hermes will not proceed without knowing "
                                    "whether a job is running.")
        if en_curso:
            return rechazado(tool, ruta, "jobs_in_progress", jobs=en_curso,
                             detail="The Supervisor has jobs in progress that this "
                                    "would interrupt. Wait until they finish "
                                    "(sv_list_pending_jobs, sv_get_job_status).")
        return None

    @mcp.tool()
    async def sv_restart_supervisor(confirmation_token: str | None = None) -> object:
        """Restart the Supervisor. The Supervisor API and Hermes' connection
        to Core (which goes through the Supervisor) drop for about 30-90
        seconds; Core and the apps keep running and Hermes reconnects by
        itself. Refused (jobs_in_progress) while a Supervisor job runs.
        Two steps: preview + confirmation_token. The answer is
        `status: "started"`: Hermes cannot see the Supervisor come back from
        inside the call; check with sv_get_supervisor_info.
        """
        tool, ruta = "sv_restart_supervisor", "/supervisor/restart"
        rechazo = await comprobar_jobs(tool, ruta)
        if rechazo is not None:
            return rechazo
        if not confirmation_token:
            preview = {
                "action": "restart_supervisor",
                "version": await leer_version("/supervisor/info"),
                "interrupts": {
                    "stops": ["Supervisor API", "Hermes' connection to Core"],
                    "keeps_running": ["Home Assistant Core", "apps (add-ons)"],
                    "duration": "about 30-90 seconds",
                },
                "hermes": ("Hermes loses Core and every sv_* tool until the "
                           "Supervisor is back, then reconnects by itself. It "
                           "cannot report the end of the restart: check with "
                           "sv_get_supervisor_info."),
                "warnings": [],
                "blocked": None,
            }
            vista_previa_emitida(tool, ruta)
            return await create_confirmation_token(tool, {}, preview=preview,
                                                   estado={"jobs": []})
        ok, motivo, _ = await resolve_confirmation_token(
            confirmation_token, tool, {}, estado={"jobs": []})
        if not ok:
            return await token_invalido(tool, ruta, motivo)
        try:
            await ha_client.sv_request("POST", ruta, timeout_seconds=_TIEMPO_RESTART)
        except (HAConnectionError, TimeoutError, aiohttp.ClientError) as exc:
            if not _es_corte(exc):
                await complete_confirmation_token(confirmation_token, success=False,
                                                  error="supervisor_request_failed")
                return error_sv(tool, ruta, exc)
            nota = ("The connection dropped before the Supervisor answered: Hermes "
                    "cannot tell whether the restart began.")
        else:
            nota = "The Supervisor accepted the restart and is going down now."
        resp = {"status": "started", "verify_with": "sv_get_supervisor_info",
                "note": nota + " Core and the apps keep running; Hermes reconnects "
                               "to Core when the Supervisor is back."}
        await complete_confirmation_token(confirmation_token, success=True, result=resp)
        hecho(tool, ruta, "started")
        return resp

    @mcp.tool()
    async def sv_repair_supervisor(confirmation_token: str | None = None) -> object:
        """Repair the Supervisor environment. It DELETES stopped containers,
        unused Docker images, the build cache and unused volumes, then
        repairs the plugins, the apps and Core, downloading any missing
        image (internet). Takes several minutes. Refused (jobs_in_progress)
        while a Supervisor job runs. Two steps: preview + confirmation_token.
        Waits up to 15 minutes; if that is not enough the answer is
        `status: "started"`: check with sv_get_resolution.
        """
        tool, ruta = "sv_repair_supervisor", "/supervisor/repair"
        rechazo = await comprobar_jobs(tool, ruta)
        if rechazo is not None:
            return rechazo
        if not confirmation_token:
            preview = {
                "action": "repair_supervisor",
                "steps": list(_PASOS_REPAIR),
                "deletes": "stopped containers, unused images, build cache, unused volumes",
                "downloads": "missing images of plugins, apps and Core",
                "interrupts": {
                    "stops": ["only what has to be repaired"],
                    "keeps_running": ["Home Assistant Core", "apps (add-ons)"],
                    "duration": "several minutes",
                },
                "hermes": ("Hermes keeps running; the answer arrives when the "
                           "repair ends (up to 15 minutes of waiting)."),
                "warnings": ["Unused images and volumes are deleted for good; a "
                             "stopped app's image may have to be downloaded again."],
                "blocked": None,
            }
            vista_previa_emitida(tool, ruta)
            return await create_confirmation_token(tool, {}, preview=preview,
                                                   estado={"jobs": []})
        ok, motivo, _ = await resolve_confirmation_token(
            confirmation_token, tool, {}, estado={"jobs": []})
        if not ok:
            return await token_invalido(tool, ruta, motivo)
        return await ejecutar_larga(
            tool, ruta, confirmation_token, cuerpo=None, tiempo=_TIEMPO_REPAIR,
            verify_with="sv_get_resolution",
            ok={"result": "ok", "verify_with": "sv_get_resolution",
                "note": "Repair finished; sv_get_resolution shows what is left."})

    @mcp.tool()
    async def sv_set_supervisor_options(
        options: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Change Supervisor options. Accepted keys: timezone (IANA name,
        also changes the host time zone), country (two capital letters),
        logging (debug, info, warning, error, critical), auto_update and
        diagnostics (true/false). channel and the developer options (debug,
        debug_block, detect_blocking_io, feature_flags) are refused
        (not_allowed). Two steps: the preview shows, per key, the current
        and the new value, with warnings: auto_update=false, once a newer
        Supervisor exists, marks the installation unsupported and blocks
        app, Core, OS and plugin updates and store reloads; auto_update=true
        lets the Supervisor update and restart itself when a new version
        exists (Hermes loses the sv_* tools for a while); diagnostics also
        switches the OS Agent's diagnostics, and diagnostics=true sends
        crash reports to a third party. Nothing restarts now. Returns
        no_changes when every value is already set.
        """
        return await opciones(
            "sv_set_supervisor_options", "/supervisor/info", "/supervisor/options",
            options, confirmation_token, _SV_ADMITIDAS, _SV_RECHAZADAS,
            _valor_supervisor, _avisos_supervisor, "set_supervisor_options")
