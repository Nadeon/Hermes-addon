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
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)

_HACS_DISCLAIMER = (
    "HACS integration is best-effort. Its API is not officially stable and may "
    "change between HACS versions. If this tool returns unexpected errors, verify "
    "the HACS version installed and update Hermes if needed."
)

_VALID_CATEGORIES = {"integration", "plugin", "theme", "python_script", "appdaemon", "netdaemon"}


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
            return {"error": str(exc), "_disclaimer": _HACS_DISCLAIMER}

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
                "python_script", "appdaemon", "netdaemon"
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
                payload["category"] = category
            result = await ha_client.ws_send(payload)
            if isinstance(result, list):
                return {
                    "count": len(result),
                    "repositories": result,
                    "_disclaimer": _HACS_DISCLAIMER,
                }
            return {"error": f"Unexpected response: {type(result).__name__}", "_disclaimer": _HACS_DISCLAIMER}
        except HAConnectionError as exc:
            return {"error": str(exc), "_disclaimer": _HACS_DISCLAIMER}

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
            return {"error": str(exc), "_disclaimer": _HACS_DISCLAIMER}

    @mcp.tool()
    @ready
    async def ha_hacs_list_updates() -> object:
        """Lista repositorios HACS con actualizaciones disponibles.

        NOTE: HACS integration is best-effort. Its API is not officially stable.

        Filtra de ha_hacs_list_repositories() los repos donde
        installed=true y available_version != installed_version.

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
                if installed and available and installed != available:
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
            return {"error": str(exc), "_disclaimer": _HACS_DISCLAIMER}
