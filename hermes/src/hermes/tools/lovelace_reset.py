"""Hermes — Restablecer un dashboard Lovelace (spec 024, tramo 2, CAP-071).

Familia `dashboard_reset`. Una tool, `ha_reset_lovelace_dashboard_config`,
que borra la configuración guardada de un dashboard en modo almacenamiento
(`lovelace/config/delete`): el dashboard sigue existiendo, pero vuelve a la
vista autogenerada de Home Assistant.

POR QUÉ ASÍ (research R-4)
--------------------------
- Es irreversible salvo backup: siempre en dos pasos, y la vista previa dice
  cuántas vistas y tarjetas se pierden y cómo copiarlas antes.
- El dashboard principal (`url_path` nulo, vacío o `lovelace`) y el panel por
  defecto se protegen siempre, con y sin token, con la misma guarda que
  `ha_delete_lovelace_dashboard`: vaciar la pantalla de inicio de la casa es
  justo lo que esa tool impide. Si no se puede leer el panel por defecto, no
  se borra nada (fail-closed). La guarda se repite con token porque el panel
  puede cambiar en los 60 s del token.
- El token ata `url_path` y, con `estado` (spec 018), la configuración leída
  en la vista previa: si cambia antes de confirmar, la vista previa ya no
  dice la verdad sobre lo que se pierde y no se borra nada.
- Se reutilizan `_default_panel` y `_count_cards` de `tools/lovelace.py` sin
  tocarlo: la familia `lovelace` de la 1.1.2 no cambia (FR-010 de la 008).
  La búsqueda del dashboard NO reutiliza `_get_dashboard_meta_by_url_path`:
  esa devuelve `None` también cuando falla `lovelace/dashboards/list`, y aquí
  eso acababa en un `not_found` falso que, al confirmar, gastaba el token
  (T033). `_buscar_dashboard` distingue el fallo de lectura de la ausencia.
- Un dashboard de estrategia (`{"strategy": {...}}`, sin `views`) no pierde
  vistas ni tarjetas: pierde la estrategia y sus opciones, y la vista previa
  lo dice con el `type` de la estrategia (T034).
- El log lleva `tool`, `url_path` y el resultado; nunca la configuración del
  dashboard (puede llevar nombres de entidades y datos de la casa).
"""

from __future__ import annotations

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
from hermes.tools._common import requires_ready
from hermes.tools.lovelace import (
    _count_cards,
    _default_panel,
)

logger = structlog.get_logger(__name__)

_TOOL = "ha_reset_lovelace_dashboard_config"

_EFECTO = "deletes the stored config; the dashboard becomes auto-generated"
_AVISO = (
    "Irreversible except from a backup: every view and card listed here is "
    "lost and Home Assistant shows its auto-generated dashboard instead."
)
_AVISO_ESTRATEGIA = (
    "Irreversible except from a backup: the dashboard strategy and its options "
    "are lost and Home Assistant shows its auto-generated dashboard instead."
)
_RECUPERACION = (
    "Copy it first with ha_get_lovelace_dashboard(url_path); to restore it, "
    "save that copy with ha_save_lovelace_dashboard."
)


def _estrategia(config: dict[str, Any]) -> str | bool | None:
    """La estrategia guardada: su `type` si es un texto, `True` si la hay sin
    `type` legible, `None` si no hay estrategia.

    El frontend guarda un dashboard de estrategia como `{"strategy": {"type":
    "original-states", ...}}` (o `custom:<nombre>`). Restablecerlo borra esa
    estrategia y sus opciones aunque no haya ninguna vista guardada.
    """
    estrategia = config.get("strategy")
    if estrategia is None:
        return None
    tipo = estrategia.get("type") if isinstance(estrategia, dict) else None
    if isinstance(tipo, str) and tipo:
        return redact_secrets(tipo)
    return True


def _recuentos(config: dict[str, Any]) -> tuple[int, int]:
    """Vistas y tarjetas (con insignias y secciones) de una configuración.

    Un dashboard de estrategia no tiene `views` guardadas: 0 y 0, pero sigue
    teniendo configuración que restablecer (la propia estrategia).
    """
    vistas = config.get("views")
    if not isinstance(vistas, list):
        return 0, 0
    return len(vistas), _count_cards(vistas)


async def _leer_config(
    ha_client: HAClient, url_path: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Lee la configuración guardada. Devuelve `(config, error)`.

    `config_not_found` es la respuesta de Core a un dashboard sin
    configuración guardada (ya autogenerado): `nothing_to_reset`. Cualquier
    otro fallo o forma: `preview_unavailable` (fail-closed: sin saber qué hay,
    no se puede decir qué se pierde).
    """
    try:
        config = await ha_client.ws_send({"type": "lovelace/config", "url_path": url_path})
    except HAConnectionError as exc:
        if exc.code == "config_not_found":
            return None, "nothing_to_reset"
        return None, "preview_unavailable"
    if not isinstance(config, dict):
        return None, "preview_unavailable"
    return config, None


async def _buscar_dashboard(
    ha_client: HAClient, url_path: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Busca el dashboard en `lovelace/dashboards/list`. Devuelve `(meta, error)`.

    - Está: `(meta, None)`.
    - La lista se lee y no está: `(None, "not_found")`.
    - La lista NO se puede leer (error de Core o forma inesperada): `(None,
      "dashboards_unavailable")`. Sin la lista no se sabe si existe ni si es
      YAML; decir `not_found` sería mentir (principio V) y, al confirmar,
      daría el token por completado con un resultado falso.
    """
    try:
        dashboards = await ha_client.ws_send({"type": "lovelace/dashboards/list"})
    except HAConnectionError as exc:
        logger.warning("lovelace_dashboards_list_failed", tool=_TOOL,
                       error=redact_secrets(str(exc)))
        return None, "dashboards_unavailable"
    if not isinstance(dashboards, list):
        logger.warning("lovelace_dashboards_list_unexpected_type", tool=_TOOL,
                       got=type(dashboards).__name__)
        return None, "dashboards_unavailable"
    for d in dashboards:
        if isinstance(d, dict) and d.get("url_path") == url_path:
            return d, None
    return None, "not_found"


def register(
    mcp: object,
    ha_client: HAClient,
    *,
    response_max_bytes: int | None = None,
) -> None:
    """Registra la tool de restablecer un dashboard.

    `response_max_bytes` se recibe por uniformidad con el resto de módulos;
    la respuesta es un resumen de pocos bytes (nunca la configuración).
    """
    del response_max_bytes
    ready = requires_ready(ha_client)

    def _fin(url_path: Any, outcome: str, respuesta: dict[str, Any]) -> dict[str, Any]:
        # Un evento por llamada, sin la configuración del dashboard (FR-007).
        logger.info("lovelace_dashboard_reset", tool=_TOOL, url_path=url_path,
                    outcome=outcome)
        return respuesta

    async def _guarda(url_path: Any) -> dict[str, Any] | None:
        """Protección del principal y del panel por defecto (FR-006)."""
        if url_path is None or url_path == "" or url_path == "lovelace":
            return {
                "error": "cannot_reset_default_dashboard",
                "url_path": url_path,
                "hint": "The main Lovelace dashboard cannot be reset.",
            }
        default_panel, panel_error = await _default_panel(ha_client)
        if panel_error:
            # Sin saber cuál es el panel por defecto, cualquier dashboard
            # podría ser la pantalla de inicio: no se toca ninguno.
            return {
                "error": panel_error,
                "url_path": url_path,
                "hint": ("Could not read the default panel from Home Assistant; "
                         "refusing to reset any dashboard."),
            }
        if url_path == default_panel:
            return {
                "error": "cannot_reset_default_dashboard",
                "url_path": url_path,
                "hint": ("This dashboard is the default panel of Home Assistant "
                         "and cannot be reset."),
            }
        return None

    def _sin_lista(url_path: Any) -> dict[str, Any]:
        return {
            "error": "dashboards_unavailable",
            "url_path": url_path,
            "hint": ("Could not read the dashboard list from Home Assistant, so it "
                     "is unknown whether this dashboard exists. Nothing was reset; "
                     "try again (a confirmation token stays valid until it expires)."),
        }

    async def _cerrar_sin_objetivo(
        confirmation_token: str, args: dict[str, Any], resultado: dict[str, Any],
    ) -> dict[str, Any] | None:
        """El objetivo desapareció entre los dos pasos: nada que borrar.

        El token se da por completado (no queda nada que confirmar), pero solo
        si es de ESTA acción: `resolve_confirmation_token` comprueba el
        action_hash antes que el estado, así que `ESTADO_CAMBIADO` quiere
        decir que el token es de esta tool y este `url_path`. Con cualquier
        otro error (otro destino, caducado, usado) se devuelve ese error y
        no se toca el token de nadie.
        """
        ok, error, _ = await resolve_confirmation_token(
            confirmation_token, _TOOL, args, estado=None)
        if not ok and error != ESTADO_CAMBIADO:
            return {"error": error}
        await complete_confirmation_token(confirmation_token, success=True, result=resultado)
        return None

    @mcp.tool()
    @ready
    async def ha_reset_lovelace_dashboard_config(
        url_path: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Delete the stored config of a storage-mode Lovelace dashboard so it
        goes back to the auto-generated one.

        The dashboard itself is kept; only its saved views and cards (or its
        strategy, for a strategy dashboard) are deleted. Irreversible (except from a backup): copy it first with
        `ha_get_lovelace_dashboard`, restore it with
        `ha_save_lovelace_dashboard`.

        **Always requires `confirmation_token`**: the first call returns a
        preview with the views and cards that would be lost; repeat the same
        call with the token to reset. If the config changes before you
        confirm, nothing is reset (request a new preview).

        The main dashboard (`lovelace`, or no `url_path`) and the default
        panel are always protected (`cannot_reset_default_dashboard`); if
        the default panel cannot be read nothing is reset
        (`default_panel_unknown`). YAML dashboards cannot be reset
        (`yaml_mode_dashboard`). If the dashboard list cannot be read, nothing
        is reset and the token is not spent (`dashboards_unavailable`).

        Args:
            url_path: URL path of the dashboard, for example "panel-tests".
            confirmation_token: One-time token from the preview call.

        Returns:
            Preview ({preview: {url_path, title, mode, views, cards,
            strategy?, effect, warning, recovery}, confirmation_token}), the
            result ({result: "ok", url_path, views_removed, cards_removed,
            strategy_removed?}) or {"error": ...}:
            cannot_reset_default_dashboard, default_panel_unknown,
            dashboards_unavailable, not_found, yaml_mode_dashboard,
            nothing_to_reset, preview_unavailable, dashboard_changed or a
            token error.
        """
        rechazo = await _guarda(url_path)
        if rechazo is not None:
            return _fin(url_path, f"rejected:{rechazo['error']}", rechazo)

        args: dict[str, Any] = {"url_path": url_path}

        if not confirmation_token:
            meta, error = await _buscar_dashboard(ha_client, url_path)
            if error == "dashboards_unavailable":
                return _fin(url_path, "rejected:dashboards_unavailable",
                            _sin_lista(url_path))
            if meta is None:
                return _fin(url_path, "rejected:not_found",
                            {"error": "not_found", "url_path": url_path})
            if meta.get("mode") == "yaml":
                return _fin(url_path, "rejected:yaml_mode_dashboard", {
                    "error": "yaml_mode_dashboard",
                    "url_path": url_path,
                    "hint": ("This dashboard is defined in YAML; edit or remove "
                             "its file with the fs_* tools."),
                })
            config, error = await _leer_config(ha_client, url_path)
            if error:
                return _fin(url_path, f"rejected:{error}",
                            {"error": error, "url_path": url_path})
            vistas, tarjetas = _recuentos(config)
            estrategia = _estrategia(config)
            preview: dict[str, Any] = {
                "url_path": url_path,
                "title": meta.get("title"),
                "mode": meta.get("mode"),
                "views": vistas,
                "cards": tarjetas,
                "effect": _EFECTO,
                "warning": _AVISO,
                "recovery": _RECUPERACION,
            }
            if estrategia is not None:
                # Lo que se pierde es la estrategia: «0 vistas y 0 tarjetas»
                # a secas haría creer que no se pierde nada (T034).
                preview["strategy"] = estrategia
                if not isinstance(config.get("views"), list):
                    preview["warning"] = _AVISO_ESTRATEGIA
            respuesta = await create_confirmation_token(
                _TOOL, args, preview=preview, estado=config)
            return _fin(url_path, "preview", respuesta)

        # Confirmación: metadata y configuración leídas otra vez justo antes
        # de resolver el token, que exige la misma configuración.
        meta, error = await _buscar_dashboard(ha_client, url_path)
        if error == "dashboards_unavailable":
            # Fallo de lectura, no ausencia: el token sigue pendiente para
            # reintentar en su plazo (T033).
            return _fin(url_path, "rejected:dashboards_unavailable",
                        _sin_lista(url_path))
        if meta is None:
            resultado = {"result": "not_found", "url_path": url_path}
            error_token = await _cerrar_sin_objetivo(confirmation_token, args, resultado)
            if error_token:
                return _fin(url_path, "rejected:token", error_token)
            return _fin(url_path, "not_found", resultado)
        config, error = await _leer_config(ha_client, url_path)
        if error == "nothing_to_reset":
            resultado = {"result": "nothing_to_reset", "url_path": url_path}
            error_token = await _cerrar_sin_objetivo(confirmation_token, args, resultado)
            if error_token:
                return _fin(url_path, "rejected:token", error_token)
            return _fin(url_path, "nothing_to_reset", resultado)
        if error:
            # Fallo de lectura: el token sigue pendiente (se puede reintentar
            # dentro de su plazo), como al guardar una vista.
            return _fin(url_path, f"rejected:{error}",
                        {"error": error, "url_path": url_path})

        valid, error, _ = await resolve_confirmation_token(
            confirmation_token, _TOOL, args, estado=config)
        if not valid:
            if error == ESTADO_CAMBIADO:
                return _fin(url_path, "rejected:dashboard_changed", {
                    "error": "dashboard_changed",
                    "url_path": url_path,
                    "detail": ("The dashboard config changed since the preview, so "
                               "the preview no longer says what would be lost. "
                               "Nothing was reset; request a new preview."),
                })
            return _fin(url_path, "rejected:token", {"error": error})

        vistas, tarjetas = _recuentos(config)
        try:
            await ha_client.ws_send({"type": "lovelace/config/delete", "url_path": url_path})
        except HAConnectionError as exc:
            detalle = redact_secrets(str(exc))
            await complete_confirmation_token(
                confirmation_token, success=False, error=detalle)
            return _fin(url_path, "error", {"error": detalle, "url_path": url_path})
        resultado = {"result": "ok", "url_path": url_path,
                     "views_removed": vistas, "cards_removed": tarjetas}
        estrategia = _estrategia(config)
        if estrategia is not None:
            resultado["strategy_removed"] = estrategia
        await complete_confirmation_token(confirmation_token, success=True, result=resultado)
        return _fin(url_path, "ok", resultado)
