"""Hermes — Tools MCP para wait_for_event.

ha_wait_for_event es una tool bloqueante que espera hasta que ocurra un
evento HA que cumple los filtros especificados, o hasta que expire el timeout.

LIMITACIÓN ARQUITECTÓNICA: esta tool captura el PRIMER evento que matchea
y termina. No es streaming continuo. Para monitorización de muchos eventos
usa automations (ha_create_or_update_automation) que disparen servicios, no esta tool.

Filtros con dot-path:
    Los filtros operan sobre la estructura completa del evento HA:
    {"event_type": "...", "data": {...}, "origin": "...", "time_fired": "...", "context": {...}}

    Ejemplos de paths:
    - "data.entity_id"          → entity_id dentro de data
    - "data.new_state.state"    → nuevo estado en un state_changed
    - "data.old_state.state"    → estado anterior
    - "data.domain"             → dominio en call_service

    Operadores en el valor esperado:
    - ">80"   → numérico mayor que 80
    - "<20"   → numérico menor que 20
    - ">=80"  → numérico mayor o igual
    - "<=20"  → numérico menor o igual
    - "!=on"  → distinto de "on"
    - "on"    → igual a "on" (default)
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError, _WS_CLOSED_SENTINEL
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)

_KEEPALIVE_INTERVAL = 15.0  # segundos entre report_progress


# ── Filtros dot-path ───────────────────────────────────────────────────────────

def _resolve_dot_path(obj: Any, path: str) -> Any:
    """Resuelve un dot-path sobre una estructura anidada de dicts/listas."""
    for part in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list):
            try:
                obj = obj[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return obj


def _compare_value(actual: Any, expected_str: str) -> bool:
    """Compara un valor actual contra una especificación de filtro."""
    if not isinstance(expected_str, str):
        return actual == expected_str

    # Detectar operadores numéricos
    for op, fn in (
        (">=", lambda a, b: float(a) >= float(b)),
        ("<=", lambda a, b: float(a) <= float(b)),
        (">",  lambda a, b: float(a) > float(b)),
        ("<",  lambda a, b: float(a) < float(b)),
        ("!=", lambda a, b: str(a) != str(b)),
    ):
        if expected_str.startswith(op):
            rhs = expected_str[len(op):]
            try:
                return fn(actual, rhs)
            except (TypeError, ValueError):
                return False

    # Igualdad (default)
    return str(actual) == expected_str if actual is not None else (expected_str == "None")


def _match_event(event: dict, filters: dict[str, str]) -> bool:
    """Devuelve True si el evento cumple TODOS los filtros."""
    for path, expected in filters.items():
        actual = _resolve_dot_path(event, path)
        if not _compare_value(actual, expected):
            return False
    return True


# ── Gestor de waits activos ────────────────────────────────────────────────────

@dataclass
class _ActiveWait:
    wait_id: str
    event_type: str
    filters: dict[str, str]
    started_at: float
    timeout_at: float
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


class _WaitManager:
    """Gestiona los wait_for_event activos con límite de concurrencia."""

    def __init__(self, max_concurrent: int = 5) -> None:
        self._max = max_concurrent
        self._active: dict[str, _ActiveWait] = {}
        self._lock = asyncio.Lock()

    async def register(self, wait: _ActiveWait) -> bool:
        """Registra un wait. Devuelve False si se supera el límite."""
        async with self._lock:
            if len(self._active) >= self._max:
                return False
            self._active[wait.wait_id] = wait
            return True

    async def unregister(self, wait_id: str) -> None:
        async with self._lock:
            self._active.pop(wait_id, None)

    def list_active(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        result = []
        for w in self._active.values():
            result.append({
                "wait_id": w.wait_id,
                "event_type": w.event_type,
                "filters": w.filters,
                "started_at_iso": _monotonic_to_approx_iso(w.started_at),
                "timeout_at_iso": _monotonic_to_approx_iso(w.timeout_at),
                "elapsed_seconds": round(now - w.started_at, 1),
            })
        return result

    def cancel(self, wait_id: str) -> bool:
        """Señaliza cancelación. Devuelve True si existía."""
        wait = self._active.get(wait_id)
        if wait is None:
            return False
        wait.cancel_event.set()
        return True

    @property
    def max_concurrent(self) -> int:
        return self._max

    @property
    def active_count(self) -> int:
        return len(self._active)


def _monotonic_to_approx_iso(mono: float) -> str:
    """Convierte tiempo monotónico a ISO aproximado (best-effort)."""
    import datetime
    offset = time.time() - time.monotonic()
    ts = mono + offset
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()


# ── Registro de tools ──────────────────────────────────────────────────────────

def register(
    mcp: object,
    ha_client: HAClient,
    wait_for_event_max_seconds: int = 90,
    wait_for_event_max_concurrent: int = 5,
) -> None:
    """Registra las tools de wait_for_event."""

    ready = requires_ready(ha_client)
    manager = _WaitManager(max_concurrent=wait_for_event_max_concurrent)

    @mcp.tool()
    @ready
    async def ha_wait_for_event(
        ctx: Any,
        event_type: str,
        filters: dict[str, str] | None = None,
        timeout_seconds: int = 30,
    ) -> object:
        """Espera UNA vez, bloqueando, a que ocurra un evento que cumpla los filtros.

        Es para "avísame cuando pase X" dentro de esta conversación. Si el
        usuario quiere un aviso permanente y automático, crea una automatización
        con ha_create_or_update_automation en lugar de usar esta tool.

        Suscribe al bus de eventos de HA y espera hasta que llegue un evento
        del tipo especificado que cumpla todos los filtros, o hasta timeout.

        LIMITACIÓN ARQUITECTÓNICA: captura el PRIMER evento que matchea y termina.
        NO es monitorización continua. Para vigilar muchos eventos usa automations.

        Args:
            event_type: Tipo de evento HA. Ej: "state_changed", "call_service",
                "automation_triggered", "zone_entered". No se aplica allowlist
                (solo escuchamos, no disparamos).
            filters: Condiciones dot-path sobre la estructura del evento:
                {"event_type": "...", "data": {...}, "origin": "...", "context": {...}}
                Ejemplos:
                  {"data.entity_id": "binary_sensor.puerta"}
                  {"data.new_state.state": ">80"}  (numérico mayor que)
                  {"data.old_state.state": "closed", "data.new_state.state": "open"}
                Operadores: >, <, >=, <=, != al inicio del valor. Sin operador = igualdad.
            timeout_seconds: Segundos a esperar (máx configurado en opciones del add-on).

        Devuelve:
            match: {matched: true, event: {...}, waited_seconds: N}
            timeout: {matched: false, reason: "timeout", waited_seconds: N}
            reconexión: {matched: false, reason: "ws_reconnect", waited_seconds: N,
                         note: "WS reconnected; event may have occurred. Verify state."}
            cancelado: {matched: false, reason: "cancelled", waited_seconds: N}
            error: {error: "..."}
        """
        if timeout_seconds > wait_for_event_max_seconds:
            return {
                "error": f"timeout_seconds ({timeout_seconds}) exceeds max allowed "
                         f"({wait_for_event_max_seconds}). Reduce timeout or increase "
                         "wait_for_event_max_seconds in add-on options."
            }
        if timeout_seconds < 1:
            return {"error": "timeout_seconds must be >= 1"}

        _filters: dict[str, str] = filters or {}

        wait_id = str(uuid.uuid4())[:8]
        now = time.monotonic()
        wait = _ActiveWait(
            wait_id=wait_id,
            event_type=event_type,
            filters=_filters,
            started_at=now,
            timeout_at=now + timeout_seconds,
        )

        if not await manager.register(wait):
            return {
                "error": "too_many_waits",
                "active_count": manager.active_count,
                "max": manager.max_concurrent,
                "hint": "Wait for existing waits to complete or use shorter timeouts.",
            }

        sub_id: int | None = None
        try:
            sub_id, queue, generation = await ha_client.ws_subscribe_events_queue(event_type)

            deadline = asyncio.get_running_loop().time() + timeout_seconds
            last_keepalive = asyncio.get_running_loop().time()

            while True:
                # Tiempo hasta próximo deadline (keepalive o total)
                loop_now = asyncio.get_running_loop().time()
                next_keepalive = last_keepalive + _KEEPALIVE_INTERVAL
                time_left = deadline - loop_now
                if time_left <= 0:
                    elapsed = time.monotonic() - wait.started_at
                    return {
                        "matched": False,
                        "reason": "timeout",
                        "waited_seconds": round(elapsed, 1),
                    }

                wait_secs = min(time_left, next_keepalive - loop_now)
                if wait_secs < 0:
                    wait_secs = 0.0

                # Verificar cancelación sin bloquear
                if wait.cancel_event.is_set():
                    elapsed = time.monotonic() - wait.started_at
                    return {
                        "matched": False,
                        "reason": "cancelled",
                        "waited_seconds": round(elapsed, 1),
                    }

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=wait_secs)
                except asyncio.TimeoutError:
                    # Keepalive o deadline — volvemos al inicio del loop
                    loop_now2 = asyncio.get_running_loop().time()
                    if loop_now2 >= next_keepalive:
                        elapsed_so_far = round(time.monotonic() - wait.started_at, 1)
                        if hasattr(ctx, "report_progress"):
                            await ctx.report_progress(
                                progress=int(elapsed_so_far),
                                total=timeout_seconds,
                                message=f"waiting for {event_type} ({elapsed_so_far}s)",
                            )
                        last_keepalive = loop_now2
                    continue

                # Sentinel de reconexión
                if event is _WS_CLOSED_SENTINEL:
                    elapsed = time.monotonic() - wait.started_at
                    return {
                        "matched": False,
                        "reason": "ws_reconnect",
                        "waited_seconds": round(elapsed, 1),
                        "note": (
                            "WS client reconnected during wait; event may have occurred "
                            "and been missed. Verify state with ha_get_state before deciding."
                        ),
                    }

                # Aplicar filtros
                if _match_event(event, _filters):
                    elapsed = time.monotonic() - wait.started_at
                    return {
                        "matched": True,
                        "event": event,
                        "waited_seconds": round(elapsed, 1),
                    }
                # No matchea — seguir esperando

        except HAConnectionError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.error("ha_wait_for_event_error", error=str(exc), exc_info=True)
            return {"error": f"{type(exc).__name__}: {exc}"}
        finally:
            if sub_id is not None:
                await ha_client.ws_unsubscribe_events_queue(sub_id)
            await manager.unregister(wait_id)

    @mcp.tool()
    async def ha_list_active_waits() -> object:
        """Lista los ha_wait_for_event activos en este momento.

        Útil para diagnóstico si hay un wait colgado o para verificar
        cuántos waits concurrentes están en curso.

        Returns:
            {"count": N, "max_concurrent": M, "waits": [...]}
            Cada wait incluye: wait_id, event_type, filters, elapsed_seconds,
            started_at_iso, timeout_at_iso.
        """
        waits = manager.list_active()
        return {
            "count": len(waits),
            "max_concurrent": manager.max_concurrent,
            "waits": waits,
        }

    @mcp.tool()
    async def ha_cancel_wait(wait_id: str) -> object:
        """Cancela un ha_wait_for_event activo por su wait_id.

        El wait activo recibirá {matched: false, reason: "cancelled"} y terminará.

        Args:
            wait_id: ID del wait a cancelar (obtenido de ha_list_active_waits).

        Returns:
            {"result": "ok"} si se canceló, {"error": "not_found"} si no existe.
        """
        if manager.cancel(wait_id):
            return {"result": "ok", "wait_id": wait_id}
        return {"error": "not_found", "wait_id": wait_id}
