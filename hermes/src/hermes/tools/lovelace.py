"""Hermes — Tools MCP para Lovelace dashboards.

Lovelace usa comandos WebSocket directos (`lovelace/*`), no la API REST
de config ni la colección WS de helpers. Los dashboards viven en
`.storage/lovelace*`, nunca en YAML directo salvo `ui-lovelace.yaml` (YAML mode).

Comandos WS usados:
    lovelace/dashboards          — lista dashboards extra
    lovelace/config              — obtiene config (url_path opcional = default)
    lovelace/config/save         — guarda config (url_path opcional = default)
    lovelace/dashboards/create   — crea dashboard nuevo
    lovelace/dashboards/update   — actualiza metadata (dashboard_id)
    lovelace/dashboards/delete   — borra dashboard (dashboard_id)
    lovelace/resources           — lista resources
    lovelace/resources/create    — crea resource
    lovelace/resources/update    — modifica resource (resource_id)
    lovelace/resources/delete    — borra resource (resource_id)

El dashboard principal ("default") no aparece en `lovelace/dashboards`.
`ha_list_lovelace_dashboards` añade una entrada sintética para él.

Concurrencia: last-write-wins. HA no tiene locking de dashboard.
Si dos clientes guardan simultáneamente, el último gana.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    validate_confirmation_token,
)
from hermes.tools._validation import build_ws_payload
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)


# ── Helpers internos ───────────────────────────────────────────────────────────


def _count_cards(views: list[Any]) -> int:
    """Cuenta cards en todas las views (incluye sections en views tipo grid)."""
    total = 0
    for v in views:
        if not isinstance(v, dict):
            continue
        total += len(v.get("cards", []) or [])
        for section in v.get("sections", []) or []:
            if isinstance(section, dict):
                total += len(section.get("cards", []) or [])
        total += len(v.get("badges", []) or [])
    return total


def _summarize_dashboard_diff(
    current: dict[str, Any] | None,
    new: dict[str, Any],
) -> dict[str, Any]:
    """Calcula diff resumido para preview de ha_save_lovelace_dashboard.

    No incluye el JSON completo (puede ser enorme). Cuenta vistas, cards,
    badges y detecta cambios estructurales.
    """
    current = current or {}
    c_views: list[Any] = current.get("views", []) or []
    n_views: list[Any] = new.get("views", []) or []
    if not isinstance(c_views, list):
        c_views = []
    if not isinstance(n_views, list):
        n_views = []
    return {
        "views_count_before": len(c_views),
        "views_count_after": len(n_views),
        "total_cards_badges_before": _count_cards(c_views),
        "total_cards_badges_after": _count_cards(n_views),
        "theme_changed": current.get("theme") != new.get("theme"),
        "title_changed": current.get("title") != new.get("title"),
        "has_strategy": "strategy" in new,
    }


def _validate_dashboard_config(config: Any) -> str | None:
    """Validación básica de config Lovelace. Devuelve mensaje de error o None."""
    if not isinstance(config, dict):
        return "config must be a JSON object"
    if "views" not in config and "strategy" not in config:
        return "config must have a 'views' list or a 'strategy' object"
    views = config.get("views")
    if views is not None and not isinstance(views, list):
        return "'views' must be a list"
    return None


async def _list_extra_dashboards(ha_client: HAClient) -> list[dict[str, Any]]:
    """Lista los dashboards extra (excluye el default) vía WS.

    En HA 2024+ el comando `lovelace/dashboards` puede no estar registrado
    si no hay dashboards extra creados todavía. En ese caso devuelve lista
    vacía en lugar de propagar el error.
    """
    try:
        result = await ha_client.ws_send({"type": "lovelace/dashboards"})
        if isinstance(result, list):
            return result
        return []
    except HAConnectionError:
        # HA no registra lovelace/dashboards hasta que existe al menos un
        # dashboard extra, o el comando ha sido renombrado en versiones recientes.
        return []


async def _get_dashboard_meta_by_url_path(
    ha_client: HAClient,
    url_path: str,
) -> dict[str, Any] | None:
    """Busca metadata de un dashboard por url_path."""
    dashboards = await _list_extra_dashboards(ha_client)
    for d in dashboards:
        if isinstance(d, dict) and d.get("url_path") == url_path:
            return d
    return None


# ── Registro de tools ──────────────────────────────────────────────────────────


def register(
    mcp: object,
    ha_client: HAClient,
    response_max_bytes: int = 1_048_576,
) -> None:
    """Registra las tools de Lovelace dashboards."""

    ready = requires_ready(ha_client)

    # ── Dashboards ─────────────────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_lovelace_dashboards() -> object:
        """Lista todos los dashboards Lovelace configurados.

        Devuelve el dashboard principal (synthetic `url_path: null`) más los
        dashboards extra registrados. Cada item incluye:
        `url_path`, `title`, `icon`, `mode` ("storage"|"yaml"),
        `require_admin`, `show_in_sidebar`, `id` (null para el default),
        `is_default` (bool).

        El dashboard default no se puede borrar.
        Los dashboards en YAML mode no se pueden guardar con
        `ha_save_lovelace_dashboard` — usar `fs_write_file` en su lugar.
        """
        try:
            extra = await _list_extra_dashboards(ha_client)
            result: list[dict[str, Any]] = [
                {
                    "url_path": None,
                    "title": "Default",
                    "icon": None,
                    "mode": "storage",
                    "require_admin": False,
                    "show_in_sidebar": True,
                    "id": None,
                    "is_default": True,
                }
            ]
            for d in extra:
                if isinstance(d, dict):
                    result.append({**d, "is_default": False})
            return result
        except HAConnectionError as exc:
            logger.warning("ha_list_lovelace_dashboards_ws_error", error=str(exc))
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_list_lovelace_dashboards_failed", error=str(exc), exc_info=True
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_get_lovelace_dashboard(
        url_path: str | None = None,
        view_index: int | None = None,
    ) -> object:
        """Obtiene la configuración de un dashboard Lovelace.

        Args:
            url_path: URL path del dashboard (p.ej. "map"). Omitir o `null`
                para el dashboard principal.
            view_index: Si se especifica, devuelve solo esa view por índice
                (0-based). Útil cuando el dashboard entero supera el límite
                de respuesta.

        Errores posibles:
        - `yaml_mode`: el dashboard es YAML mode — leer con `fs_read_file`.
        - `too_large`: config > `response_max_bytes`. Usar `view_index`.
        - `view_index_out_of_range`: índice fuera de rango.
        """
        try:
            # Detectar YAML mode para dashboards extra
            if url_path is not None:
                try:
                    meta = await _get_dashboard_meta_by_url_path(ha_client, url_path)
                except HAConnectionError as exc:
                    return {"error": str(exc)}
                if meta is not None and meta.get("mode") == "yaml":
                    return {
                        "error": "yaml_mode",
                        "url_path": url_path,
                        "message": (
                            f"Dashboard '{url_path}' is managed via YAML file. "
                            "Use fs_read_file to read it directly."
                        ),
                    }

            payload: dict[str, Any] = {"type": "lovelace/config"}
            if url_path is not None:
                payload["url_path"] = url_path

            try:
                config = await ha_client.ws_send(payload)
            except HAConnectionError as exc:
                return {"error": str(exc)}

            if not isinstance(config, dict):
                config = {}

            # Devolver solo una view si se pide
            if view_index is not None:
                views = config.get("views")
                if not isinstance(views, list):
                    return {"error": "no_views", "url_path": url_path}
                if view_index < 0 or view_index >= len(views):
                    return {
                        "error": "view_index_out_of_range",
                        "url_path": url_path,
                        "views_count": len(views),
                        "requested": view_index,
                    }
                return {
                    "url_path": url_path,
                    "view_index": view_index,
                    "views_total": len(views),
                    "view": views[view_index],
                }

            # Comprobar tamaño
            encoded = json.dumps(config, ensure_ascii=False)
            size = len(encoded.encode("utf-8"))
            if size > response_max_bytes:
                views = config.get("views", [])
                return {
                    "error": "too_large",
                    "url_path": url_path,
                    "views_count": len(views) if isinstance(views, list) else 0,
                    "total_size_bytes": size,
                    "hint": (
                        "Dashboard config exceeds the response limit. "
                        "Call ha_get_lovelace_dashboard with view_index=N "
                        "to read individual views."
                    ),
                }

            return config

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_get_lovelace_dashboard_failed",
                url_path=url_path,
                error=str(exc),
                exc_info=True,
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_save_lovelace_dashboard(
        url_path: str | None,
        config: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Sobrescribe la configuración completa de un dashboard Lovelace.

        Esta operación **siempre requiere `confirmation_token`** porque sustituye
        el dashboard entero (no es un merge parcial). El preview muestra un diff
        resumido (vistas y cards antes/después), no el JSON completo.

        **Concurrencia**: last-write-wins. Si dos clientes guardan
        simultáneamente, el último gana. HA no tiene locking de dashboard.

        Args:
            url_path: URL path del dashboard. `null` para el dashboard principal.
            config: Configuración completa. Debe tener `views` o `strategy`.
            confirmation_token: Token de un solo uso obtenido en la llamada
                previa sin token.

        Rechaza si el dashboard está en YAML mode (usar `fs_write_file`).
        """
        err = _validate_dashboard_config(config)
        if err:
            return {"error": f"invalid_config: {err}"}

        # Detectar YAML mode
        if url_path is not None:
            try:
                meta = await _get_dashboard_meta_by_url_path(ha_client, url_path)
            except HAConnectionError as exc:
                return {"error": str(exc)}
            if meta is not None and meta.get("mode") == "yaml":
                return {
                    "error": "yaml_mode",
                    "url_path": url_path,
                    "message": (
                        f"Dashboard '{url_path}' is in YAML mode. "
                        "Use fs_write_file to modify it."
                    ),
                }

        args: dict[str, Any] = {"url_path": url_path, "config": config}

        if not confirmation_token:
            try:
                get_payload: dict[str, Any] = {"type": "lovelace/config"}
                if url_path is not None:
                    get_payload["url_path"] = url_path
                try:
                    current = await ha_client.ws_send(get_payload)
                    if not isinstance(current, dict):
                        current = None
                except HAConnectionError:
                    current = None

                preview: dict[str, Any] = {
                    "url_path": url_path,
                    "diff": _summarize_dashboard_diff(current, config),
                    "warning": "This replaces the ENTIRE dashboard configuration.",
                }
                return await create_confirmation_token(
                    "ha_save_lovelace_dashboard", args, preview=preview
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "ha_save_lovelace_dashboard_preview_failed",
                    url_path=url_path,
                    error=str(exc),
                    exc_info=True,
                )
                return {"error": f"{type(exc).__name__}: {exc}"}

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_save_lovelace_dashboard", args
        )
        if not valid:
            logger.warning(
                "ha_save_lovelace_dashboard_token_invalid",
                url_path=url_path,
                reason=error,
            )
            return {"error": error}

        try:
            save_payload: dict[str, Any] = {
                "type": "lovelace/config/save",
                "config": config,
            }
            if url_path is not None:
                save_payload["url_path"] = url_path
            await ha_client.ws_send(save_payload)
            result: dict[str, Any] = {"result": "ok", "url_path": url_path}
            await complete_confirmation_token(
                confirmation_token, success=True, result=result
            )
            logger.info("ha_save_lovelace_dashboard_ok", url_path=url_path)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_save_lovelace_dashboard_failed",
                url_path=url_path,
                error=str(exc),
                exc_info=True,
            )
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_create_lovelace_dashboard(
        url_path: str,
        title: str,
        icon: str | None = None,
        show_in_sidebar: bool = True,
        require_admin: bool = False,
    ) -> object:
        """Crea un nuevo dashboard Lovelace.

        No requiere `confirmation_token` — es una creación no destructiva.
        Después de crear, llamar a `ha_save_lovelace_dashboard` con el
        `url_path` devuelto para guardar la configuración inicial.

        Args:
            url_path: Ruta URL única (p.ej. "mi-dashboard"). Solo minúsculas,
                números y guiones.
            title: Título visible en la sidebar.
            icon: Icono MDI (p.ej. "mdi:home").
            show_in_sidebar: Si aparece en la barra lateral.
            require_admin: Si solo admins pueden acceder.

        Devuelve el id y url_path del dashboard creado.
        """
        try:
            payload: dict[str, Any] = {
                "type": "lovelace/dashboards/create",
                "url_path": url_path,
                "title": title,
                "mode": "storage",
                "show_in_sidebar": show_in_sidebar,
                "require_admin": require_admin,
            }
            if icon is not None:
                payload["icon"] = icon
            result = await ha_client.ws_send(payload)
            logger.info(
                "ha_create_lovelace_dashboard_ok", url_path=url_path, title=title
            )
            return result if isinstance(result, dict) else {"result": "ok", "url_path": url_path}
        except HAConnectionError as exc:
            logger.warning(
                "ha_create_lovelace_dashboard_ws_error",
                url_path=url_path,
                error=str(exc),
            )
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_create_lovelace_dashboard_failed",
                url_path=url_path,
                error=str(exc),
                exc_info=True,
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_update_lovelace_dashboard_metadata(
        url_path: str,
        updates: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Modifica metadata de un dashboard Lovelace (título, icono, sidebar, admin).

        Campos modificables: `title`, `icon`, `show_in_sidebar`, `require_admin`.
        **Token requerido** si `require_admin` o `show_in_sidebar` están en
        `updates` (afectan visibilidad y permisos de acceso).

        Args:
            url_path: URL path del dashboard a modificar.
            updates: Dict con los campos a actualizar.
            confirmation_token: Requerido solo cuando se cambian campos sensibles.
        """
        _SENSITIVE = {"require_admin", "show_in_sidebar"}
        needs_token = any(k in updates for k in _SENSITIVE)

        try:
            meta = await _get_dashboard_meta_by_url_path(ha_client, url_path)
        except HAConnectionError as exc:
            return {"error": str(exc)}

        if meta is None:
            return {"error": "not_found", "url_path": url_path}

        dashboard_id = meta.get("id")
        if not dashboard_id:
            return {"error": "cannot_identify_dashboard", "url_path": url_path}

        args: dict[str, Any] = {
            "url_path": url_path,
            "dashboard_id": dashboard_id,
            "updates": updates,
        }

        if needs_token and not confirmation_token:
            preview: dict[str, Any] = {
                "url_path": url_path,
                "dashboard_id": dashboard_id,
                "current_metadata": meta,
                "updates": updates,
                "warning": (
                    "Changes to 'require_admin' or 'show_in_sidebar' affect "
                    "dashboard visibility and access control."
                ),
            }
            return await create_confirmation_token(
                "ha_update_lovelace_dashboard_metadata", args, preview=preview
            )

        if needs_token:
            valid, error = await validate_confirmation_token(
                confirmation_token,
                "ha_update_lovelace_dashboard_metadata",
                args,
            )
            if not valid:
                logger.warning(
                    "ha_update_lovelace_dashboard_metadata_token_invalid",
                    url_path=url_path,
                    reason=error,
                )
                return {"error": error}

        try:
            payload = build_ws_payload(
                "lovelace/dashboards/update",
                {"dashboard_id": dashboard_id},
                updates,
            )
            result = await ha_client.ws_send(payload)
            if needs_token and confirmation_token:
                await complete_confirmation_token(
                    confirmation_token, success=True, result=result
                )
            logger.info(
                "ha_update_lovelace_dashboard_metadata_ok", url_path=url_path
            )
            return result if isinstance(result, dict) else {"result": "ok"}
        except HAConnectionError as exc:
            if needs_token and confirmation_token:
                await complete_confirmation_token(
                    confirmation_token, success=False, error=str(exc)
                )
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_update_lovelace_dashboard_metadata_failed",
                url_path=url_path,
                error=str(exc),
                exc_info=True,
            )
            if needs_token and confirmation_token:
                await complete_confirmation_token(
                    confirmation_token, success=False, error=str(exc)
                )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_delete_lovelace_dashboard(
        url_path: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina un dashboard Lovelace extra.

        Esta operación **siempre requiere `confirmation_token`**. No se puede
        eliminar el dashboard principal (`url_path=null`).

        Args:
            url_path: URL path del dashboard a borrar.
            confirmation_token: Token de un solo uso obtenido en la llamada
                previa sin token.
        """
        if url_path is None:
            return {
                "error": "cannot_delete_default_dashboard",
                "hint": "The default Lovelace dashboard cannot be deleted.",
            }

        args: dict[str, Any] = {"url_path": url_path}

        if not confirmation_token:
            try:
                meta = await _get_dashboard_meta_by_url_path(ha_client, url_path)
                if meta is None:
                    return {"error": "not_found", "url_path": url_path}
                preview: dict[str, Any] = {
                    "url_path": url_path,
                    "dashboard": meta,
                    "warning": (
                        "This permanently deletes the dashboard and its stored config."
                    ),
                }
                return await create_confirmation_token(
                    "ha_delete_lovelace_dashboard", args, preview=preview
                )
            except HAConnectionError as exc:
                return {"error": str(exc)}
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "ha_delete_lovelace_dashboard_preview_failed",
                    url_path=url_path,
                    error=str(exc),
                    exc_info=True,
                )
                return {"error": f"{type(exc).__name__}: {exc}"}

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_delete_lovelace_dashboard", args
        )
        if not valid:
            logger.warning(
                "ha_delete_lovelace_dashboard_token_invalid",
                url_path=url_path,
                reason=error,
            )
            return {"error": error}

        try:
            meta = await _get_dashboard_meta_by_url_path(ha_client, url_path)
            if meta is None:
                await complete_confirmation_token(
                    confirmation_token,
                    success=True,
                    result={"result": "not_found"},
                )
                return {"result": "not_found", "url_path": url_path}

            dashboard_id = meta.get("id")
            if not dashboard_id:
                await complete_confirmation_token(
                    confirmation_token, success=False, error="no_id"
                )
                return {"error": "cannot_identify_dashboard", "url_path": url_path}

            await ha_client.ws_send(
                {"type": "lovelace/dashboards/delete", "dashboard_id": dashboard_id}
            )
            result: dict[str, Any] = {"result": "ok", "url_path": url_path}
            await complete_confirmation_token(
                confirmation_token, success=True, result=result
            )
            logger.info("ha_delete_lovelace_dashboard_ok", url_path=url_path)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_delete_lovelace_dashboard_failed",
                url_path=url_path,
                error=str(exc),
                exc_info=True,
            )
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    # ── Resources ──────────────────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_lovelace_resources() -> object:
        """Lista los resources Lovelace (custom cards JS, themes).

        Los resources son ficheros JS (normalmente de HACS) que se cargan en
        el frontend de HA. Incluyen `id`, `url` y `type` ("module"|"css").
        """
        try:
            result = await ha_client.ws_send({"type": "lovelace/resources"})
            return result if isinstance(result, list) else []
        except HAConnectionError as exc:
            logger.warning("ha_list_lovelace_resources_ws_error", error=str(exc))
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_list_lovelace_resources_failed", error=str(exc), exc_info=True
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_create_lovelace_resource(
        url: str,
        res_type: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Añade un resource Lovelace (JS module / CSS).

        Esta operación **siempre requiere `confirmation_token`** porque carga
        código JavaScript arbitrario en el frontend de HA.

        **WARNING**: Solo añadir resources de fuentes de confianza. Un resource
        malicioso puede inyectar JS que robe el token de HA del navegador.

        Args:
            url: URL del fichero JS/CSS (p.ej. "/hacsfiles/card/card.js").
            res_type: Tipo de resource: "module" (ES module JS) o "css".
            confirmation_token: Token de confirmación requerido.
        """
        args: dict[str, Any] = {"url": url, "res_type": res_type}

        if not confirmation_token:
            preview: dict[str, Any] = {
                "url": url,
                "res_type": res_type,
                "warning": (
                    "WARNING: this loads a JavaScript file in the HA frontend. "
                    "Only add resources from trusted sources."
                ),
            }
            return await create_confirmation_token(
                "ha_create_lovelace_resource", args, preview=preview
            )

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_create_lovelace_resource", args
        )
        if not valid:
            logger.warning(
                "ha_create_lovelace_resource_token_invalid", url=url, reason=error
            )
            return {"error": error}

        try:
            result = await ha_client.ws_send(
                {
                    "type": "lovelace/resources/create",
                    "res_type": res_type,
                    "url": url,
                }
            )
            await complete_confirmation_token(
                confirmation_token, success=True, result=result
            )
            logger.info("ha_create_lovelace_resource_ok", url=url)
            return result if isinstance(result, dict) else {"result": "ok"}
        except HAConnectionError as exc:
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_create_lovelace_resource_failed",
                url=url,
                error=str(exc),
                exc_info=True,
            )
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_update_lovelace_resource(
        resource_id: str,
        updates: dict[str, Any],
        confirmation_token: str | None = None,
    ) -> object:
        """Modifica un resource Lovelace existente.

        Esta operación **siempre requiere `confirmation_token`** porque afecta
        código JS cargado en el frontend.

        Args:
            resource_id: ID del resource (de `ha_list_lovelace_resources`).
            updates: Campos a actualizar: `url` y/o `res_type`.
            confirmation_token: Token de confirmación requerido.
        """
        args: dict[str, Any] = {"resource_id": resource_id, "updates": updates}

        if not confirmation_token:
            preview: dict[str, Any] = {
                "resource_id": resource_id,
                "updates": updates,
                "warning": "Modifying resources changes JS/CSS loaded in the HA frontend.",
            }
            return await create_confirmation_token(
                "ha_update_lovelace_resource", args, preview=preview
            )

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_update_lovelace_resource", args
        )
        if not valid:
            logger.warning(
                "ha_update_lovelace_resource_token_invalid",
                resource_id=resource_id,
                reason=error,
            )
            return {"error": error}

        try:
            payload = build_ws_payload(
                "lovelace/resources/update",
                {"resource_id": resource_id},
                updates,
            )
            result = await ha_client.ws_send(payload)
            await complete_confirmation_token(
                confirmation_token, success=True, result=result
            )
            logger.info("ha_update_lovelace_resource_ok", resource_id=resource_id)
            return result if isinstance(result, dict) else {"result": "ok"}
        except HAConnectionError as exc:
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_update_lovelace_resource_failed",
                resource_id=resource_id,
                error=str(exc),
                exc_info=True,
            )
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.tool()
    @ready
    async def ha_delete_lovelace_resource(
        resource_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Elimina un resource Lovelace.

        Esta operación **siempre requiere `confirmation_token`** porque elimina
        JS/CSS del frontend de HA.

        Args:
            resource_id: ID del resource (de `ha_list_lovelace_resources`).
            confirmation_token: Token de confirmación requerido.
        """
        args: dict[str, Any] = {"resource_id": resource_id}

        if not confirmation_token:
            preview: dict[str, Any] = {
                "resource_id": resource_id,
                "warning": "Deletes this JS/CSS resource from the HA frontend.",
            }
            return await create_confirmation_token(
                "ha_delete_lovelace_resource", args, preview=preview
            )

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_delete_lovelace_resource", args
        )
        if not valid:
            logger.warning(
                "ha_delete_lovelace_resource_token_invalid",
                resource_id=resource_id,
                reason=error,
            )
            return {"error": error}

        try:
            await ha_client.ws_send(
                {
                    "type": "lovelace/resources/delete",
                    "resource_id": resource_id,
                }
            )
            result: dict[str, Any] = {"result": "ok", "resource_id": resource_id}
            await complete_confirmation_token(
                confirmation_token, success=True, result=result
            )
            logger.info("ha_delete_lovelace_resource_ok", resource_id=resource_id)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ha_delete_lovelace_resource_failed",
                resource_id=resource_id,
                error=str(exc),
                exc_info=True,
            )
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return {"error": f"{type(exc).__name__}: {exc}"}
