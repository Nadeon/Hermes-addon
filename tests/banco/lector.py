"""Lector independiente del banco de pruebas de Core (spec 010, FR-008).

Comprueba en la HA real el efecto de lo que hace Hermes sin pasar por Hermes ni
por el Supervisor simulado: habla directamente con Core (`core_url`) con el
token de larga duración. Comprobar Hermes con el propio Hermes no prueba nada:
un error en `HAClient` daría el mismo resultado equivocado en la acción y en la
comprobación.

Uso: `async with Lector(entorno.core_url, entorno.token_core) as lector:`.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable

import aiohttp

# Sondeo de las comprobaciones de efecto (FR-011): nunca pausas fijas.
INTERVALO = 0.25
TIMEOUT = 10.0


class ErrorCore(Exception):
    """Core respondió a un comando WebSocket con `success: false`."""

    def __init__(self, codigo: str, mensaje: str) -> None:
        self.codigo = codigo
        super().__init__(f"{codigo}: {mensaje}")


class Lector:
    def __init__(self, core_url: str, token_core: str) -> None:
        self._core_url = core_url.rstrip("/")
        self._token = token_core
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._lectura: asyncio.Task[None] | None = None
        self._ids = itertools.count(1)
        self._pendientes: dict[int, asyncio.Future[dict[str, Any]]] = {}
        # id de suscripción → función que recibe cada evento (`event` del mensaje).
        self._suscripciones: dict[int, Callable[[dict[str, Any]], None]] = {}

    def __repr__(self) -> str:
        return f"Lector(core_url={self._core_url!r})"

    async def __aenter__(self) -> "Lector":
        self._session = aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=aiohttp.ClientTimeout(total=30),
        )
        ws_url = self._core_url.replace("http://", "ws://").replace("https://", "wss://")
        self._ws = await self._session.ws_connect(f"{ws_url}/api/websocket")
        inicio = await self._ws.receive_json(timeout=10)
        if inicio.get("type") != "auth_required":
            raise AssertionError(f"lector: Core no pidió auth ({inicio.get('type')})")
        await self._ws.send_json({"type": "auth", "access_token": self._token})
        auth = await self._ws.receive_json(timeout=10)
        if auth.get("type") != "auth_ok":
            raise AssertionError(f"lector: Core rechazó el token ({auth.get('type')})")
        self._lectura = asyncio.ensure_future(self._leer())
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._lectura is not None:
            self._lectura.cancel()
            await asyncio.gather(self._lectura, return_exceptions=True)
        if self._ws is not None:
            await self._ws.close()
        if self._session is not None:
            await self._session.close()

    async def _leer(self) -> None:
        assert self._ws is not None
        async for msg in self._ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                break
            datos = json.loads(msg.data)
            for item in datos if isinstance(datos, list) else [datos]:
                id_ = item.get("id")
                if item.get("type") == "result":
                    futuro = self._pendientes.pop(id_, None)
                    if futuro is not None and not futuro.done():
                        futuro.set_result(item)
                elif item.get("type") == "event" and id_ in self._suscripciones:
                    self._suscripciones[id_](item.get("event") or {})
        for futuro in self._pendientes.values():
            if not futuro.done():
                futuro.set_exception(AssertionError("lector: Core cerró la WebSocket"))

    async def _comando(self, mensaje: dict[str, Any]) -> Any:
        assert self._ws is not None
        id_ = next(self._ids)
        futuro: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pendientes[id_] = futuro
        await self._ws.send_json({"id": id_, **mensaje})
        respuesta = await asyncio.wait_for(futuro, timeout=TIMEOUT)
        if not respuesta.get("success"):
            error = respuesta.get("error") or {}
            raise ErrorCore(str(error.get("code")), str(error.get("message")))
        return respuesta.get("result")

    # ── Operaciones ──────────────────────────────────────────────────────
    async def comando(self, mensaje: dict[str, Any]) -> Any:
        """Cualquier comando WebSocket de Core; devuelve su `result`.

        Spec 028: las escrituras que no son de helpers se comprueban con
        comandos propios de cada dominio (`lovelace/dashboards/list`,
        `lovelace/config`, `lovelace/resources/list`…). Un `success: false`
        lanza `ErrorCore` con el código de Core.
        """
        return await self._comando(mensaje)

    async def rest(
        self, metodo: str, ruta: str, cuerpo: Any = None
    ) -> tuple[int, Any]:
        """REST directo a Core con el token de larga duración: `(estado, cuerpo)`.

        Spec 028: la configuración guardada de automatizaciones, scripts y
        escenas solo se lee por `/api/config/<dominio>/config/<id>`. No falla
        con un estado de error: quien llama decide (un 404 es justo lo que
        se espera tras un borrado). El cuerpo sale como JSON si lo es y como
        texto si no.
        """
        assert self._session is not None
        opciones: dict[str, Any] = {}
        if cuerpo is not None:
            opciones["json"] = cuerpo
        async with self._session.request(
            metodo, f"{self._core_url}{ruta}", **opciones
        ) as resp:
            texto = await resp.text()
            try:
                datos: Any = json.loads(texto) if texto else None
            except ValueError:
                datos = texto
            return resp.status, datos

    async def listar(self, dominio: str) -> list[dict[str, Any]]:
        """Elementos de un dominio de helpers (`<dominio>/list`)."""
        return await self._comando({"type": f"{dominio}/list"})

    async def servicios(self) -> dict[str, dict[str, Any]]:
        """Servicios que Core tiene registrados (`get_services`), por dominio."""
        return await self._comando({"type": "get_services"})

    async def estado(self, entity_id: str) -> dict[str, Any] | None:
        """Estado de una entidad por REST; None si Core no la conoce."""
        assert self._session is not None
        async with self._session.get(f"{self._core_url}/api/states/{entity_id}") as resp:
            if resp.status == 404:
                return None
            if resp.status != 200:
                raise AssertionError(f"lector: GET /api/states/{entity_id} devolvió {resp.status}")
            return await resp.json()

    async def esperar(
        self,
        obtener: Callable[[], Awaitable[Any]],
        comprobar: Callable[[Any], bool],
        *,
        descripcion: str = "condición",
        timeout: float = TIMEOUT,
    ) -> Any:
        """Sondea `obtener()` hasta que `comprobar(valor)`; falla con el último valor."""
        bucle = asyncio.get_running_loop()
        limite = bucle.time() + timeout
        while True:
            valor = await obtener()
            if comprobar(valor):
                return valor
            if bucle.time() >= limite:
                raise AssertionError(
                    f"lector: {descripcion} no se cumplió en {timeout:g} s; "
                    f"último valor visto: {valor!r}"
                )
            await asyncio.sleep(INTERVALO)

    @asynccontextmanager
    async def _suscripcion(
        self, event_type: str, recibir: Callable[[dict[str, Any]], None]
    ) -> AsyncIterator[None]:
        """Suscripción a un tipo de evento del bus mientras dura el bloque."""
        id_ = next(self._ids)
        self._suscripciones[id_] = recibir
        assert self._ws is not None
        futuro: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pendientes[id_] = futuro
        await self._ws.send_json({"id": id_, "type": "subscribe_events", "event_type": event_type})
        respuesta = await asyncio.wait_for(futuro, timeout=TIMEOUT)
        if not respuesta.get("success"):
            raise AssertionError(f"lector: no se pudo suscribir a {event_type}")
        try:
            yield
        finally:
            self._suscripciones.pop(id_, None)
            try:
                await self._comando({"type": "unsubscribe_events", "subscription": id_})
            except (ErrorCore, asyncio.TimeoutError, AssertionError):
                pass

    @asynccontextmanager
    async def servicios_llamados(self) -> AsyncIterator[list[tuple[str, str]]]:
        """Suscripción a `call_service`: la lista se llena con `(dominio, servicio)`.

        Se abre ANTES de la acción y se cierra después, para no perder la
        llamada que se quiere ver.
        """
        vistos: list[tuple[str, str]] = []

        def recibir(evento: dict[str, Any]) -> None:
            datos = evento.get("data") or {}
            vistos.append((str(datos.get("domain")), str(datos.get("service"))))

        async with self._suscripcion("call_service", recibir):
            yield vistos

    @asynccontextmanager
    async def eventos(self, event_type: str) -> AsyncIterator[list[dict[str, Any]]]:
        """Suscripción a un tipo de evento: la lista se llena con su `data`.

        Para efectos que no dejan rastro en el estado, como `timer.finished`
        (el temporizador vuelve a `idle` igual que al cancelarlo).
        """
        vistos: list[dict[str, Any]] = []

        def recibir(evento: dict[str, Any]) -> None:
            vistos.append(dict(evento.get("data") or {}))

        async with self._suscripcion(event_type, recibir):
            yield vistos

    async def crear(self, dominio: str, datos: dict[str, Any]) -> dict[str, Any]:
        """Crea un helper sin pasar por Hermes (para preparar un caso)."""
        return await self._comando({"type": f"{dominio}/create", **datos})

    async def borrar(self, dominio: str, id_: str) -> None:
        """Borra un helper; si ya no existe, no es un error (limpieza)."""
        try:
            await self._comando({"type": f"{dominio}/delete", f"{dominio}_id": id_})
        except ErrorCore as exc:
            if exc.codigo != "not_found":
                raise
