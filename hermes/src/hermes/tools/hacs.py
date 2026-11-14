"""Hermes — Tools MCP para HACS (best-effort).

IMPORTANTE: La API de HACS no es oficial y puede cambiar entre versiones.
Estas tools son best-effort. Si devuelven errores inesperados, verifica
la versión de HACS instalada y actualiza Hermes si es necesario.

Comandos WS usados:
    hacs/info             — información del sistema HACS
    hacs/repositories/list — lista repositorios (filtro por categoría opcional)
    hacs/repository/info  — detalles de un repositorio por ID
"""
from __future__ import annotations

from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.ha_version import ha_at_least
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)

_HACS_DISCLAIMER = (
    "HACS integration is best-effort. Its API is not officially stable and may "
    "change between HACS versions. If this tool returns unexpected errors, verify "
    "the HACS version installed."
)

# Categorías reales de HACS: `template` existe y `netdaemon` se retiró.
_VALID_CATEGORIES = {"integration", "plugin", "theme", "python_script", "appdaemon", "template"}


async def _hacs_error(ha_client: HAClient, exc: HAConnectionError) -> dict[str, Any]:
    """Traduce un error de los comandos `hacs/*` a una respuesta útil.

    `unknown_command` significa que HA no conoce `hacs/*`. Desde 2026.11 HACS
    viene integrado como Marketplace y esos comandos ya no existen; antes,
    significa que HACS no está instalado. En ningún caso lo arregla actualizar
    Hermes, que es lo que sugería el mensaje genérico. Con versión desconocida
    no se puede afirmar lo del Marketplace, así que se dice lo seguro.
    """
    if exc.code == "unknown_command":
        if await ha_at_least(ha_client, "2026.11.0") is True:
            return {
                "error": "hacs_moved_to_marketplace",
                "hint": (
                    "HACS is built into Home Assistant as the Marketplace since "
                    "2026.11 and the hacs/* commands no longer exist. Pending "
                    'updates: ha_get_states(domain="update").'
                ),
            }
        return {
            "error": "hacs_not_installed",
            "hint": "Home Assistant does not know the hacs/* commands: HACS is not installed.",
        }
    return {"error": str(exc), "_disclaimer": _HACS_DISCLAIMER}


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de HACS."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_hacs_info() -> object:
        """Devuelve información del sistema HACS instalado.

        NOTE: HACS integration is best-effort. Its API is not officially stable.

        Returns:
            Información de HACS: version, categorías activas, modo de desarrollo,
            país configurado, estado de la cola de descarga, etc.
        """
        try:
            result = await ha_client.ws_send({"type": "hacs/info"})
            if isinstance(result, dict):
                result["_disclaimer"] = _HACS_DISCLAIMER
            return result
        except HAConnectionError as exc:
            return await _hacs_error(ha_client, exc)

    @mcp.tool()
    @ready
    async def ha_hacs_list_repositories(
        category: str | None = None,
    ) -> object:
        """Lista repositorios HACS instalados o disponibles.

        NOTE: HACS integration is best-effort. Its API is not officially stable.

        Args:
            category: Filtra por categoría. Valores válidos:
                "integration" — integraciones custom
                "plugin"      — Lovelace custom cards (frontend)
                "theme"       — temas
                "python_script", "appdaemon", "template"
                Omitir para listar todos.

        Returns:
            {"count": N, "repositories": [...], "_disclaimer": "..."}
            Cada repo incluye: id, name, description, installed, installed_version,
            available_version, category, authors, stars, last_updated, issues, etc.
        """
        if category is not None and category not in _VALID_CATEGORIES:
            return {
                "error": f"Invalid category '{category}'. Valid: {sorted(_VALID_CATEGORIES)}",
                "_disclaimer": _HACS_DISCLAIMER,
            }
        try:
            payload: dict[str, Any] = {"type": "hacs/repositories/list"}
            if category is not None:
                # El schema de HACS es `{Optional("categories"): [str]}` con
                # PREVENT_EXTRA: mandar `category` (singular, string) hacía que
                # el WS de HA rechazara el comando entero, así que CUALQUIER
                # llamada filtrada fallaba.
                payload["categories"] = [category]
            result = await ha_client.ws_send(payload)
            if isinstance(result, list):
                return {
                    "count": len(result),
                    "repositories": result,
                    "_disclaimer": _HACS_DISCLAIMER,
                }
            return {"error": f"Unexpected response: {type(result).__name__}", "_disclaimer": _HACS_DISCLAIMER}
        except HAConnectionError as exc:
            return await _hacs_error(ha_client, exc)

    @mcp.tool()
    @ready
    async def ha_hacs_get_repository(repository_id: str) -> object:
        """Devuelve información detallada de un repositorio HACS.

        NOTE: HACS integration is best-effort. Its API is not officially stable.

        Args:
            repository_id: ID del repositorio (obtenido de ha_hacs_list_repositories).

        Returns:
            Detalles del repositorio: name, full_name, description, installed,
            installed_version, available_version, release_notes, authors,
            stars, issues, last_updated, etc.
        """
        try:
            result = await ha_client.ws_send({
                "type": "hacs/repository/info",
                "repository_id": repository_id,
            })
            if isinstance(result, dict):
                result["_disclaimer"] = _HACS_DISCLAIMER
            return result
        except HAConnectionError as exc:
            return await _hacs_error(ha_client, exc)

    @mcp.tool()
    @ready
    async def ha_hacs_list_updates() -> object:
        """Lista repositorios HACS con actualizaciones disponibles.

        NOTE: HACS integration is best-effort. Its API is not officially stable.

        Filtra de ha_hacs_list_repositories() los repos instalados con
        actualización: usa `pending_upgrade` de HACS cuando lo trae y, si no,
        available_version != installed_version.

        Returns:
            {"count": N, "updates": [...], "_disclaimer": "..."}
            Cada item incluye: id, name, category, installed_version,
            available_version.
        """
        try:
            result = await ha_client.ws_send({"type": "hacs/repositories/list"})
            if not isinstance(result, list):
                return {"error": "Unexpected HACS response", "_disclaimer": _HACS_DISCLAIMER}

            updates = []
            for repo in result:
                if not isinstance(repo, dict):
                    continue
                if not repo.get("installed"):
                    continue
                installed = repo.get("installed_version") or repo.get("version_installed")
                releases = repo.get("releases")
                available = (
                    repo.get("available_version")
                    or repo.get("version_available")
                    or (releases[0] if releases else None)
                )
                # `pending_upgrade` lo calcula HACS comparando de verdad
                # (commits, versiones con o sin prefijo); el texto de las
                # versiones puede coincidir y haber actualización, o al revés.
                pending = repo.get("pending_upgrade")
                if isinstance(pending, bool):
                    has_update = pending
                else:
                    has_update = bool(installed and available and installed != available)
                if has_update:
                    updates.append({
                        "id": repo.get("id"),
                        "name": repo.get("name"),
                        "full_name": repo.get("full_name"),
                        "category": repo.get("category"),
                        "installed_version": installed,
                        "available_version": available,
                    })
            return {
                "count": len(updates),
                "updates": updates,
                "_disclaimer": _HACS_DISCLAIMER,
            }
        except HAConnectionError as exc:
            return await _hacs_error(ha_client, exc)
