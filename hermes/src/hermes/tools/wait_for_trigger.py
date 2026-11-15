"""Hermes — Espera de un trigger de Home Assistant (spec 017, tramo D, CAP-038).

`ha_wait_for_trigger` se suscribe con `subscribe_trigger` a un trigger escrito
como en una automatización y devuelve el PRIMER disparo, o `timeout`,
`cancelled` o `ws_reconnect` como `ha_wait_for_event`. Es un solo disparo:
para un aviso permanente se crea una automatización.

POR QUÉ UNA LISTA CERRADA DE TRIGGERS (research R-8, principio III)
-------------------------------------------------------------------
Un trigger activo no siempre se limita a escuchar. En HA 2026.11.1,
`webhook` registra un endpoint HTTP sin autenticación; `conversation`
registra frases y contesta en Assist; `samsungtv`, `webostv`, `lg_netcast` y
`philips_js` (`turn_on`, también como trigger de dispositivo) dan a la tele la
acción de encender mientras el trigger existe (con `PluggableAction`: la
entidad anuncia `TURN_ON` y `async_turn_on` ejecuta el trigger); uno de una
integración personalizada puede hacer cualquier cosa. Una lista negra dejaría pasar lo que aún no se
conoce, así que se admite SOLO lo que se sabe que escucha:

- sin punto: las plataformas de `_PLATAFORMAS_SIN_PUNTO` (y `device` con la
  regla de la integración sobre su `domain`);
- `<integración>.<nombre>` (los de propósito, `light.turned_on`) y `device`
  con `domain`: la integración no puede estar en `_INTEGRACIONES_EXCLUIDAS`;
- en TODOS los casos, la integración que HA carga para el trigger tiene que
  ser de HA (`manifest/get` → `is_built_in: true`; una personalizada que
  sobrescribe una de HA da `false`). Las sin punto también: HA carga su
  `trigger.py` con `async_get_integration`, que prefiere una personalizada
  con el mismo nombre (`custom_components/mqtt`). Para las que HA traduce
  (`_ALIAS_DE_HA`: `state`, `event`… → `homeassistant`; `device` →
  `device_automation`) se consulta la traducida, que es la que HA carga, y en
  `device`, además, la integración de su `domain`;
- todo lo demás, o si `manifest/get` falla: `trigger_not_allowed`, sin
  suscribirse (fail-closed).

REVISAR EN CADA VERSIÓN DE HA DE REFERENCIA (duda D-3 de la spec): las dos
listas se escribieron leyendo los `trigger.py` y `device_trigger.py` de
`components/` de HA 2026.11.1. Al subir la versión de referencia hay que
volver a leerlos: una plataforma nueva sin punto no entra hasta que alguien la
añada aquí (fail-closed), y una integración de HA que empiece a hacer algo más
que escuchar mientras su trigger existe tiene que ir a la lista de excluidas.
Criterio de revisión: `grep -rl PluggableAction components/` (en la 2026.11.1
da exactamente `lg_netcast`, `philips_js`, `samsungtv` y `webostv`), y leer los
`async_attach_trigger` de `trigger.py`, `triggers/` y `device_trigger.py`
buscando los que registran algo (endpoints, frases, acciones de la entidad) o
llaman a servicios; en la 2026.11.1, además de esas cuatro, `webhook` y
`conversation`. Los `turn_on` de `arcam_fmj` y `kodi` solo escuchan un evento
que la entidad lanza siempre, exista o no el trigger: se admiten.

La espera comparte gestor y cupo con `ha_wait_for_event` (se lista y se
cancela con `ha_list_active_waits` y `ha_cancel_wait`, de la familia
`events`), el mismo tope de segundos (`wait_for_event_max_seconds`) y
siempre cancela la suscripción al salir, también con error o plazo.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import structlog
from mcp.server.mcpserver import Context

from hermes.ha import HAClient, HAConnectionError, _WS_CLOSED_SENTINEL
from hermes.security import redact_secrets, redact_structure
from hermes.tools._common import requires_ready, tam_json
from hermes.tools.wait_for_event import _ActiveWait, _WaitManager

logger = structlog.get_logger(__name__)

_KEEPALIVE_INTERVAL = 15.0  # segundos entre report_progress, como ha_wait_for_event

# Plataformas sin punto que solo escuchan (HA 2026.11.1). `device` no está:
# va aparte porque depende de la integración de su `domain`. Revisar con cada
# versión de HA de referencia (ver el docstring del módulo).
_PLATAFORMAS_SIN_PUNTO: frozenset[str] = frozenset({
    "state",
    "numeric_state",
    "event",
    "time",
    "time_pattern",
    "template",
    "sun",
    "zone",
    "geo_location",
    "homeassistant",
    "mqtt",
    "tag",
    "calendar",
    "persistent_notification",
})

# Integraciones de HA cuyo trigger hace algo más que escuchar mientras existe
# (research R-8): un endpoint HTTP sin autenticación, frases de Assist que
# contestan, o la acción de encender de una tele. Revisar con cada versión.
_INTEGRACIONES_EXCLUIDAS: frozenset[str] = frozenset({
    "webhook",
    "conversation",
    "samsungtv",
    "webostv",
    "lg_netcast",
    "philips_js",
})

# Plataformas sin punto que HA traduce a otra integración antes de cargarla
# (`_PLATFORM_ALIASES` de `helpers/trigger/__init__.py`, HA 2026.11.1). Las
# demás sin punto se cargan con su propio nombre. Revisar con cada versión.
_ALIAS_DE_HA: dict[str, str] = {
    "device": "device_automation",
    "event": "homeassistant",
    "numeric_state": "homeassistant",
    "state": "homeassistant",
    "time_pattern": "homeassistant",
    "time": "homeassistant",
}

_PISTA_NO_PERMITIDO = (
    "ha_wait_for_trigger only accepts triggers known to just listen. For this "
    "trigger, create an automation with ha_create_or_update_automation instead."
)


def _invalid(field: str, detail: str) -> dict[str, Any]:
    return {"error": "invalid_argument", "field": field, "detail": detail}


def _no_permitido(detail: str) -> dict[str, Any]:
    return {"error": "trigger_not_allowed", "detail": detail, "hint": _PISTA_NO_PERMITIDO}


def _lista_de_triggers(trigger: Any) -> list[dict[str, Any]] | dict[str, Any]:
    """La lista de triggers o el error `invalid_argument`."""
    lista = trigger if isinstance(trigger, list) else [trigger]
    if not lista:
        return _invalid("trigger", "must be a trigger object or a non-empty list of them")
    for elemento in lista:
        if not isinstance(elemento, dict):
            return _invalid("trigger", "each trigger must be an object")
    return lista


def _plataforma(elemento: dict[str, Any]) -> str | None:
    """La plataforma de un trigger (`trigger` o la clave antigua `platform`)."""
    if "trigger" in elemento and "platform" in elemento:
        return None
    valor = elemento.get("trigger", elemento.get("platform"))
    return valor if isinstance(valor, str) and valor else None


async def _comprobar_triggers(
    ha_client: HAClient, lista: list[dict[str, Any]]
) -> tuple[list[str], dict[str, Any] | None]:
    """(plataformas, None) si todos se admiten; si no, ([], el error).

    Se comprueban TODOS los elementos de la lista: un solo trigger no
    admitido rechaza la espera entera.
    """
    plataformas: list[str] = []
    # Integraciones ya consultadas en esta llamada (una consulta por dominio).
    de_ha: dict[str, bool] = {}

    async def integracion_de_ha(dominio: str) -> dict[str, Any] | None:
        if dominio in _INTEGRACIONES_EXCLUIDAS:
            return _no_permitido(
                f"triggers of the '{dominio}' integration do more than listen while "
                "they exist, so Hermes does not set them up"
            )
        if dominio not in de_ha:
            try:
                manifiesto = await ha_client.ws_send(
                    {"type": "manifest/get", "integration": dominio}
                )
            except HAConnectionError as exc:
                # Sin saber si es de HA, no se admite (fail-closed).
                logger.warning("ha_wait_for_trigger_manifest_failed", integration=dominio,
                               code=exc.code or "connection")
                return _no_permitido(
                    f"could not check that '{dominio}' is an integration included in "
                    f"Home Assistant: {redact_secrets(str(exc))}"
                )
            de_ha[dominio] = (
                isinstance(manifiesto, dict) and manifiesto.get("is_built_in") is True
            )
        if not de_ha[dominio]:
            return _no_permitido(
                f"'{dominio}' is not an integration included in Home Assistant "
                "(custom integrations can do anything while their trigger exists)"
            )
        return None

    for elemento in lista:
        plataforma = _plataforma(elemento)
        if plataforma is None:
            return [], _invalid(
                "trigger",
                "each trigger needs a 'trigger' key (or the old 'platform' key, not both) "
                "with the platform name",
            )
        if "." in plataforma:
            # Los de propósito no se traducen: HA carga la integración del
            # prefijo tal cual.
            cargada = plataforma.split(".", 1)[0]
            if not cargada:
                return [], _no_permitido(f"'{plataforma}' is not a known trigger platform")
        elif plataforma == "device" or plataforma in _PLATAFORMAS_SIN_PUNTO:
            cargada = _ALIAS_DE_HA.get(plataforma, plataforma)
        else:
            if plataforma in _INTEGRACIONES_EXCLUIDAS:
                return [], await integracion_de_ha(plataforma) or _no_permitido(plataforma)
            return [], _no_permitido(
                f"'{plataforma}' is not in the list of triggers that only listen "
                f"({', '.join(sorted(_PLATAFORMAS_SIN_PUNTO))}, device, "
                "and '<integration>.<name>' of integrations included in Home Assistant)"
            )
        if plataforma == "device":
            # La del dispositivo, que es la que pone el `device_trigger.py`:
            # primero, para que una excluida se nombre a ella.
            dominio = elemento.get("domain")
            if not isinstance(dominio, str) or not dominio:
                return [], _no_permitido("a device trigger needs its 'domain'")
            error = await integracion_de_ha(dominio)
            if error:
                return [], error
        # La integración que HA carga para este trigger, sea cual sea la
        # plataforma: también `mqtt`, `template` o `homeassistant` pueden venir
        # de una personalizada que sobrescribe la de HA.
        error = await integracion_de_ha(cargada)
        if error:
            return [], error
        if plataforma not in plataformas:
            plataformas.append(plataforma)
    return plataformas, None


def _ajustar_disparo(trigger: Any, max_bytes: int) -> tuple[Any, bool]:
    """El disparo redactado y si se recortó para caber en `max_bytes`."""
    limpio = redact_structure(trigger)
    if tam_json({"matched": True, "trigger": limpio, "waited_seconds": 0.0}) <= max_bytes:
        return limpio, False
    if isinstance(limpio, dict):
        # Lo grande son los estados completos (atributos): se quitan.
        sin_estados = {k: v for k, v in limpio.items() if k not in ("from_state", "to_state")}
        if tam_json({"matched": True, "trigger": sin_estados, "waited_seconds": 0.0,
                     "truncated": True}) <= max_bytes:
            return sin_estados, True
        # Aún no cabe: solo los valores simples (plataforma, id, entity_id…).
        simples = {k: v for k, v in sin_estados.items()
                   if v is None or isinstance(v, (str, int, float, bool))}
        return simples, True
    return None, True


def register(
    mcp: object,
    ha_client: HAClient,
    *,
    manager: _WaitManager,
    wait_for_event_max_seconds: int = 90,
    response_max_bytes: int = 65536,
) -> None:
    """Registra `ha_wait_for_trigger` con el gestor de esperas compartido."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_wait_for_trigger(
        # `Context` y no `Any` (como el arreglo de `ha_wait_for_event` de la
        # 033): el SDK solo inyecta un parámetro anotado con su `Context`; con
        # `Any` lo publicaría como argumento obligatorio. Los tests que llaman
        # a la función directamente pasan `None` (de ahí el `hasattr`).
        ctx: Context,
        trigger: dict | list,
        variables: dict | None = None,
        timeout_seconds: int = 30,
    ) -> object:
        """Wait ONCE, blocking, until a Home Assistant trigger fires. Read only.

        The trigger is written as in an automation (for example
        {"trigger": "state", "entity_id": "light.salon", "to": "on"} or a
        purpose trigger such as {"trigger": "light.turned_on", "target":
        {"entity_id": "light.salon"}}); a list fires on the first of them.
        Returns on the FIRST firing: for a permanent reaction, create an
        automation instead.

        Only triggers known to just listen are accepted: state,
        numeric_state, event, time, time_pattern, template, sun, zone,
        geo_location, homeassistant, mqtt, tag, calendar,
        persistent_notification, and "<integration>.<name>" or device
        triggers of integrations included in Home Assistant, except webhook,
        conversation, samsungtv, webostv, lg_netcast and philips_js (their
        triggers do more than listen while they exist). Anything else,
        including a custom integration (also one that replaces a built-in
        one, such as a custom mqtt), gives "trigger_not_allowed".

        Shares the limits of ha_wait_for_event (maximum seconds and number of
        concurrent waits); list or cancel it with ha_list_active_waits and
        ha_cancel_wait.

        Args:
            trigger: One trigger (object) or a list of triggers.
            variables: Variables available to templates in the trigger.
            timeout_seconds: Seconds to wait (maximum set in the add-on options).

        Returns:
            {"matched": true, "trigger": {...}, "waited_seconds"} (plus
            "truncated": true if from_state/to_state were dropped to fit);
            {"matched": false, "reason": "timeout"|"cancelled"|"ws_reconnect",
            "waited_seconds"}; or {"error": "invalid_trigger"|
            "trigger_not_allowed"|"too_many_waits"|"invalid_argument", ...}.
        """
        if timeout_seconds > wait_for_event_max_seconds:
            # El mismo texto que `ha_wait_for_event`: es el mismo tope.
            return {
                "error": f"timeout_seconds ({timeout_seconds}) exceeds max allowed "
                         f"({wait_for_event_max_seconds}). Reduce timeout or increase "
                         "wait_for_event_max_seconds in add-on options."
            }
        if timeout_seconds < 1:
            return {"error": "timeout_seconds must be >= 1"}
        if variables is not None and not isinstance(variables, dict):
            return _invalid("variables", "must be an object")

        lista = _lista_de_triggers(trigger)
        if isinstance(lista, dict):
            return lista
        plataformas, error = await _comprobar_triggers(ha_client, lista)
        if error:
            logger.warning("ha_wait_for_trigger_rejected", error=error["error"])
            return error

        wait_id = str(uuid.uuid4())[:8]
        ahora = time.monotonic()
        espera = _ActiveWait(
            wait_id=wait_id,
            event_type="",
            filters={},
            started_at=ahora,
            timeout_at=ahora + timeout_seconds,
            kind="trigger",
            trigger_platform=", ".join(plataformas),
        )
        if not await manager.register(espera):
            return {
                "error": "too_many_waits",
                "active_count": manager.active_count,
                "max": manager.max_concurrent,
                "hint": "Wait for existing waits to complete or use shorter timeouts.",
            }

        def transcurrido() -> float:
            return round(time.monotonic() - espera.started_at, 1)

        payload: dict[str, Any] = {"type": "subscribe_trigger", "trigger": trigger}
        if variables is not None:
            payload["variables"] = variables

        sub_id: int | None = None
        try:
            try:
                sub_id, cola, _generacion = await ha_client.ws_subscribe_queue(payload)
            except HAConnectionError as exc:
                if exc.code in ("invalid_format", "home_assistant_error"):
                    # HA valida el trigger al suscribir: su mensaje puede
                    # repetir valores del trigger, de ahí la redacción.
                    logger.info("ha_wait_for_trigger_invalid", code=exc.code)
                    return {"error": "invalid_trigger", "detail": redact_secrets(str(exc))}
                logger.warning("ha_wait_for_trigger_error", code=exc.code or "connection")
                return {"error": redact_secrets(str(exc))}

            bucle = asyncio.get_running_loop()
            limite = bucle.time() + timeout_seconds
            ultimo_aviso = bucle.time()

            while True:
                ahora_bucle = bucle.time()
                proximo_aviso = ultimo_aviso + _KEEPALIVE_INTERVAL
                queda = limite - ahora_bucle
                if queda <= 0:
                    return {"matched": False, "reason": "timeout",
                            "waited_seconds": transcurrido()}
                if espera.cancel_event.is_set():
                    return {"matched": False, "reason": "cancelled",
                            "waited_seconds": transcurrido()}

                # Se espera a la vez el disparo y la cancelación, para que
                # `ha_cancel_wait` corte en el acto y no en el siguiente aviso.
                tarea_cola = asyncio.ensure_future(cola.get())
                tarea_cancelar = asyncio.ensure_future(espera.cancel_event.wait())
                hechas, pendientes = await asyncio.wait(
                    {tarea_cola, tarea_cancelar},
                    timeout=max(0.0, min(queda, proximo_aviso - ahora_bucle)),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for tarea in pendientes:
                    tarea.cancel()
                if pendientes:
                    await asyncio.gather(*pendientes, return_exceptions=True)

                if tarea_cola not in hechas:
                    if tarea_cancelar in hechas:
                        return {"matched": False, "reason": "cancelled",
                                "waited_seconds": transcurrido()}
                    if bucle.time() >= proximo_aviso:
                        if hasattr(ctx, "report_progress"):
                            # Solo mantiene viva la llamada: si el aviso
                            # falla, la espera sigue (como en la 033).
                            try:
                                await ctx.report_progress(
                                    progress=int(transcurrido()),
                                    total=timeout_seconds,
                                    message=f"waiting for trigger ({transcurrido()}s)",
                                )
                            except Exception as exc:  # noqa: BLE001
                                logger.debug("wait_for_trigger_progress_failed",
                                             wait_id=wait_id, error=str(exc))
                        ultimo_aviso = bucle.time()
                    continue

                evento = tarea_cola.result()
                if evento is _WS_CLOSED_SENTINEL:
                    return {
                        "matched": False,
                        "reason": "ws_reconnect",
                        "waited_seconds": transcurrido(),
                        "note": (
                            "WS client reconnected during wait; the trigger may have "
                            "fired and been missed. Verify state with ha_get_state "
                            "before deciding."
                        ),
                    }
                variables_evento = evento.get("variables") if isinstance(evento, dict) else None
                disparo = (variables_evento.get("trigger")
                           if isinstance(variables_evento, dict) else None)
                # Un estado puede llevar un secreto en sus atributos (el
                # `access_token` de una cámara): el disparo sale redactado.
                disparo, recortado = _ajustar_disparo(disparo, response_max_bytes)
                respuesta: dict[str, Any] = {"matched": True, "trigger": disparo,
                                             "waited_seconds": transcurrido()}
                if recortado:
                    respuesta["truncated"] = True
                logger.info("ha_wait_for_trigger_matched", wait_id=wait_id,
                            platforms=plataformas, truncated=recortado)
                return respuesta
        except Exception as exc:  # noqa: BLE001
            logger.error("ha_wait_for_trigger_error", error=str(exc), exc_info=True)
            return {"error": redact_secrets(f"{type(exc).__name__}: {exc}")}
        finally:
            # Siempre: con disparo, plazo, cancelación o error. Una
            # suscripción olvidada dejaría el trigger vivo en HA.
            if sub_id is not None:
                await ha_client.ws_unsubscribe_events_queue(sub_id)
            await manager.unregister(wait_id)
