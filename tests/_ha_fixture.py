"""Helpers compartidos para tests que necesitan un HAClient operativo sin WS."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from aiohttp import ClientSession

from hermes.ha import HAClient, HAConnectionError

SUPERVISOR_BASE = "http://supervisor"
REST_BASE = f"{SUPERVISOR_BASE}/core/api"


def make_ready_client(
    session: ClientSession,
    state_cache: dict[str, dict[str, Any]] | None = None,
) -> HAClient:
    """Construye un HAClient listo para REST, sin arrancar la WS.

    Salta HAClient.__init__ (que no toca la red) solo para no necesitar un
    HealthServer real. Rellena el cache de estados y marca el cliente como
    `ready` para que `get_state` / `get_states` no caigan al endpoint REST.
    """
    client = HAClient.__new__(HAClient)
    client._supervisor_base_url = SUPERVISOR_BASE
    client._supervisor_token = "test-token"
    client._rest_base_url = REST_BASE
    client._ws_url = f"ws://supervisor/core/api/websocket"
    client._health_server = None  # type: ignore[assignment]
    client._session = session
    client._ws = None
    client._background_task = None
    client._connected_event = asyncio.Event()
    client._state_cache = dict(state_cache or {})
    client._cache_lock = asyncio.Lock()
    client._next_subscribe_id = 1
    client._ws_request_lock = asyncio.Lock()
    client._next_ws_request_id = 1
    client._pending_ws_responses = {}
    client._pending_ws_subscriptions = {}
    client._stop_event = asyncio.Event()
    client._connected_event.set()
    return client


def _slugify(name: str) -> str:
    """Aproximación a la slugify de HA suficiente para tests."""
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "unnamed"


class FakeCollectionStore:
    """Fake en memoria para los comandos WS `{domain}/{list,create,update,delete}`.

    Sustituye a aioresponses: no existen endpoints REST
    equivalentes en HA, así que monkey-patcheamos los métodos `ws_collection_*`
    del `HAClient` con versiones que operan sobre este dict. El comportamiento
    emulado replica el de `StorageCollectionWebsocket`: id generado desde
    slugify(name), update/delete sobre id existente, errores `not_found`.
    """

    def __init__(self) -> None:
        # domain -> {object_id: config_dict}
        self.items: dict[str, dict[str, dict[str, Any]]] = {}

    def seed(self, domain: str, object_id: str, config: dict[str, Any]) -> None:
        self.items.setdefault(domain, {})[object_id] = dict(config)

    def get(self, domain: str, object_id: str) -> dict[str, Any] | None:
        return self.items.get(domain, {}).get(object_id)

    def install(self, ha_client: HAClient) -> None:
        store = self

        async def ws_collection_list(domain: str) -> list[dict[str, Any]]:
            return [
                {"id": oid, **cfg}
                for oid, cfg in store.items.get(domain, {}).items()
            ]

        async def ws_collection_get(
            domain: str, object_id: str
        ) -> dict[str, Any] | None:
            d = store.items.get(domain, {})
            if object_id in d:
                return {"id": object_id, **d[object_id]}
            return None

        async def ws_collection_create(
            domain: str, config: dict[str, Any]
        ) -> dict[str, Any]:
            name = config.get("name", "unnamed")
            oid = _slugify(str(name))
            d = store.items.setdefault(domain, {})
            # Emula colisión con sufijo _2, _3...
            base = oid
            n = 2
            while oid in d:
                oid = f"{base}_{n}"
                n += 1
            d[oid] = dict(config)
            return {"id": oid, **d[oid]}

        async def ws_collection_update(
            domain: str, object_id: str, config: dict[str, Any]
        ) -> dict[str, Any]:
            d = store.items.setdefault(domain, {})
            if object_id not in d:
                raise HAConnectionError("HA WS command failed: Item not found.")
            d[object_id].update(config)
            return {"id": object_id, **d[object_id]}

        async def ws_collection_delete(
            domain: str, object_id: str
        ) -> bool:
            d = store.items.setdefault(domain, {})
            if object_id in d:
                del d[object_id]
                return True
            return False

        ha_client.ws_collection_list = ws_collection_list  # type: ignore[method-assign]
        ha_client.ws_collection_get = ws_collection_get  # type: ignore[method-assign]
        ha_client.ws_collection_create = ws_collection_create  # type: ignore[method-assign]
        ha_client.ws_collection_update = ws_collection_update  # type: ignore[method-assign]
        ha_client.ws_collection_delete = ws_collection_delete  # type: ignore[method-assign]
