"""Hermes — Alias deprecados `ha_hacs_*` de las tools `ha_marketplace_*`.

Desde HA 2026.11 HACS viene integrado en Home Assistant como el Marketplace y
los comandos `hacs/*` ya no existen. Las tools nuevas viven en
`marketplace.py`, que detecta en cada llamada cuál de las dos API hay.

Estos alias se mantienen hasta 1.3.0 para no romper a quien ya los usa
(prompts, automatizaciones de clientes). Llaman a las MISMAS funciones que las
`ha_marketplace_*` en vez de tener código propio: así no pueden divergir, y
cualquier arreglo en `marketplace.py` les llega sin tocar este fichero. Lo
único que añaden es `_deprecated`, para que el agente sepa a qué tool pasarse.
"""
from __future__ import annotations

from typing import Any

from hermes.ha import HAClient
from hermes.tools import marketplace
from hermes.tools._common import requires_ready

# Versión en la que se retiran los alias (spec 004, FR-022).
_REMOVED_IN = "1.3.0"


def _deprecated(result: Any, alias: str, replacement: str) -> Any:
    """Añade el aviso de retirada a la respuesta de la sustituta."""
    if isinstance(result, dict):
        result["_deprecated"] = (
            f"{alias} is deprecated and will be removed in {_REMOVED_IN}; "
            f"use {replacement}"
        )
    return result


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra los cuatro alias `ha_hacs_*`."""

    ready = requires_ready(ha_client)

    @mcp.tool()
    @ready
    async def ha_hacs_info() -> object:
        """DEPRECATED (removed in 1.3.0): use ha_marketplace_info.

        Same response as ha_marketplace_info plus `_deprecated`.
        """
        return _deprecated(
            await marketplace.info(ha_client), "ha_hacs_info", "ha_marketplace_info"
        )

    @mcp.tool()
    @ready
    async def ha_hacs_list_repositories(
        category: str | None = None,
        installed_only: bool = True,
        search: str | None = None,
        limit: int = 50,
    ) -> object:
        """DEPRECATED (removed in 1.3.0): use ha_marketplace_list_repositories.

        Same arguments and response as ha_marketplace_list_repositories plus
        `_deprecated`. By default only installed repositories.
        """
        return _deprecated(
            await marketplace.list_repositories(
                ha_client, category, installed_only, search, limit
            ),
            "ha_hacs_list_repositories",
            "ha_marketplace_list_repositories",
        )

    @mcp.tool()
    @ready
    async def ha_hacs_get_repository(repository_id: str) -> object:
        """DEPRECATED (removed in 1.3.0): use ha_marketplace_get_repository.

        Same arguments and response as ha_marketplace_get_repository plus
        `_deprecated`.
        """
        return _deprecated(
            await marketplace.get_repository(ha_client, repository_id),
            "ha_hacs_get_repository",
            "ha_marketplace_get_repository",
        )

    @mcp.tool()
    @ready
    async def ha_hacs_list_updates() -> object:
        """DEPRECATED (removed in 1.3.0): use ha_marketplace_list_updates.

        Same response as ha_marketplace_list_updates plus `_deprecated`.
        Hermes does not install anything from the Marketplace: to update, call
        ha_call_service('update', 'install', {'entity_id': <update_entity_id>}),
        which requires a confirmation_token.
        """
        return _deprecated(
            await marketplace.list_updates(ha_client),
            "ha_hacs_list_updates",
            "ha_marketplace_list_updates",
        )
