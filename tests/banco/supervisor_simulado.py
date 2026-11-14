"""Supervisor simulado del banco de pruebas de Core (spec 010, FR-004).

Réplica mínima de lo que el Supervisor 2026.11.0 ofrece a un add-on para
hablar con Core (`supervisor/api/proxy.py` y las rutas de
`supervisor/api/__init__.py`), más las dos rutas que Hermes usa al arrancar.
Contrato en `specs/010-banco-de-pruebas-core/contracts/supervisor-simulado.md`.

Existe para que Hermes hable con la HA real del banco por el MISMO camino que
en producción: `HAClient` con la URL del Supervisor y el token de add-on,
REST por `/core/api` y WebSocket por `/core/api/websocket`. Por eso no puede
ser más permisivo que el real: si aceptase algo que el real rechaza, el banco
daría por buena una llamada que en producción falla.

Escucha solo en `127.0.0.1`. No registra cuerpos, cabeceras ni tokens.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import re
from typing import Any
from urllib.parse import unquote

import aiohttp
from aiohttp import WSMsgType, web
from yarl import URL

# `CORE_API_DENY` del real: rutas del proxy REST reservadas al frontend de HA.
CORE_API_DENY = re.compile(r"^hassio(?:/|_)")
# `DENIED_WS_TYPE_PREFIXES` del real: comandos WebSocket que solo puede usar el
# frontend de HA, porque Core los ejecuta llamando al Supervisor con su token
# de máximo privilegio.
DENIED_WS_TYPE_PREFIXES = ("supervisor/", "hassio/")
# `FILTERS` de `supervisor/api/middleware/security.py` del Supervisor
# 2026.11.0, copiado tal cual. El real lo aplica (`block_bad_requests`, su
# primer middleware, antes incluso de mirar el token) a la ruta y a la query
# decodificadas con `recursive_unquote`, y responde 400. Sin él, el simulado
# dejaría pasar peticiones (`concat(`, `union … select (`, `<script>`, `../`)
# que en producción no llegan a Core: un test de history, logbook o queries
# podría pasar en el banco y fallar en una instalación real.
FILTERS = re.compile(
    r"(?:"
    # Common exploits
    r"proc/self/environ"
    r"|^(?>.*?(?:<|%3C))(?>.*?script).*?(?:>|%3E)"
    # File Injections
    r"|(\.\.//?)+"  # ../../anywhere
    r"|[a-zA-Z0-9_]=/([a-z0-9_.]//?)+"  # .html?v=/.//test
    # SQL Injections
    r"|^(?>.*?union)(?>.*?select).*?\("
    r"|^(?>.*?union)(?>.*?all).*?select"
    r"|^(?>.*?concat).*?\("
    r")",
    flags=re.IGNORECASE | re.MULTILINE,
)
# El real reenvía a Core solo estas cabeceras del cliente (y nunca su token).
CABECERAS_REENVIADAS = ("Content-Type", "Accept")
# El real espera la fase de auth del add-on como mucho 10 s, igual que Core.
TIMEOUT_AUTH_WS = 10

_CLAVE_SESION = web.AppKey("sesion_core", aiohttp.ClientSession)


def _desescapar(ruta: str) -> str:
    """`recursive_unquote` del real: decodifica hasta que no cambie.

    Así `hassio%255Fauth` no se cuela por el filtro tras una segunda
    decodificación en Core.
    """
    anterior = None
    while anterior != ruta:
        anterior, ruta = ruta, unquote(ruta)
    return ruta


def _tipos_denegados(datos: Any) -> list[str | None]:
    """Tipos de comando que el add-on no puede mandar; None si está mal formado.

    Como el real: Core trata cada elemento de una lista JSON como un comando,
    así que se mira cada uno.
    """
    comandos = datos if isinstance(datos, list) else [datos]
    denegados: list[str | None] = []
    for comando in comandos:
        tipo = comando.get("type") if isinstance(comando, dict) else None
        if not isinstance(tipo, str):
            denegados.append(None)
        elif tipo.startswith(DENIED_WS_TYPE_PREFIXES):
            denegados.append(tipo)
    return denegados


def _error(estado: int, mensaje: str) -> web.Response:
    return web.json_response({"result": "error", "message": mensaje}, status=estado)


def crear_app(core_url: str, token_addon: str, token_core: str, version_core: str) -> web.Application:
    """Aplicación `aiohttp` con las rutas del contrato."""
    core_url = core_url.rstrip("/")
    core_ws_url = core_url.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"

    def token_valido(token: object) -> bool:
        return isinstance(token, str) and hmac.compare_digest(token, token_addon)

    def comprobar_acceso(request: web.Request) -> None:
        # Como `_check_access` del real: `Authorization: Bearer` o, si no hay,
        # la cabecera `X-HA-Access`.
        if "Authorization" in request.headers:
            token = request.headers["Authorization"].split(" ")[-1]
        else:
            token = request.headers.get("X-HA-Access", "")
        if not token_valido(token):
            raise web.HTTPUnauthorized(
                text=json.dumps({"result": "error", "message": "Unauthorized"}),
                content_type="application/json",
            )

    @web.middleware
    async def bloquear_peticiones_peligrosas(
        request: web.Request, handler: Any
    ) -> web.StreamResponse:
        # `block_bad_requests` del real: `request.path` ya viene decodificado
        # una vez y `_desescapar` termina el trabajo, igual que allí.
        if FILTERS.search(_desescapar(request.path)) or FILTERS.search(
            _desescapar(request.query_string)
        ):
            raise web.HTTPBadRequest()
        return await handler(request)

    @web.middleware
    async def no_encontrado(request: web.Request, handler: Any) -> web.StreamResponse:
        # Cualquier ruta que el simulado no tenga responde con el formato de
        # error del Supervisor: si Hermes la usa, el test falla a la vista en
        # vez de pasar por un camino que producción no tiene.
        try:
            return await handler(request)
        except web.HTTPNotFound:
            return _error(404, f"Not found: {request.method} {request.path}")

    async def ping(request: web.Request) -> web.Response:
        # Sin token, como el real (`_ping_supervisor` no lo manda).
        return web.json_response({"result": "ok", "data": {}})

    async def core_info(request: web.Request) -> web.Response:
        comprobar_acceso(request)
        return web.json_response(
            {"result": "ok", "data": {"version": version_core, "machine": "banco", "arch": "amd64"}}
        )

    async def api(request: web.Request) -> web.Response:
        comprobar_acceso(request)
        # La ruta se reenvía tal cual llegó por la red, sin decodificar: en el
        # real, re-codificar una ruta decodificada pierde información (%2F).
        ruta = request.url.raw_path.partition("/api/")[2]
        if CORE_API_DENY.match(_desescapar(ruta)):
            raise web.HTTPForbidden()
        query = request.rel_url.raw_query_string
        destino = URL(f"{core_url}/api/{ruta}" + (f"?{query}" if query else ""), encoded=True)
        cabeceras = {n: request.headers[n] for n in CABECERAS_REENVIADAS if n in request.headers}
        cabeceras["Authorization"] = f"Bearer {token_core}"
        sesion = request.app[_CLAVE_SESION]
        try:
            async with sesion.request(
                request.method, destino, headers=cabeceras, data=await request.read()
            ) as resp:
                cuerpo = await resp.read()
                return web.Response(body=cuerpo, status=resp.status, content_type=resp.content_type)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise web.HTTPBadGateway() from None

    async def websocket(request: web.Request) -> web.WebSocketResponse:
        servidor = web.WebSocketResponse(heartbeat=30)
        await servidor.prepare(request)

        # Fase de auth propia con el add-on, como el real.
        await servidor.send_json({"type": "auth_required", "ha_version": version_core})
        try:
            respuesta = await servidor.receive_json(timeout=TIMEOUT_AUTH_WS)
        except (asyncio.TimeoutError, TypeError, ValueError):
            await servidor.close()
            return servidor
        token = None
        if isinstance(respuesta, dict):
            token = respuesta.get("api_password") or respuesta.get("access_token")
        if not token_valido(token):
            await servidor.send_json({"type": "auth_invalid", "message": "Invalid access"})
            await servidor.close()
            return servidor
        await servidor.send_json({"type": "auth_ok", "ha_version": version_core})

        # Conexión propia con Core, con el token del Supervisor (aquí, el de
        # larga duración del banco). El del add-on nunca llega a Core.
        sesion = request.app[_CLAVE_SESION]
        try:
            cliente = await sesion.ws_connect(core_ws_url)
            inicio = await cliente.receive_json(timeout=10)
            if inicio.get("type") != "auth_required":
                raise ValueError("Core no pidió auth")
            await cliente.send_json({"type": "auth", "access_token": token_core})
            auth = await cliente.receive_json(timeout=10)
            if auth.get("type") != "auth_ok":
                raise ValueError("Core rechazó el token del simulado")
        except (aiohttp.ClientError, asyncio.TimeoutError, TypeError, ValueError):
            await servidor.close()
            return servidor

        async def de_core_al_addon() -> None:
            async for msg in cliente:
                if msg.type == WSMsgType.TEXT:
                    await servidor.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await servidor.send_bytes(msg.data)
                else:
                    break

        async def del_addon_a_core() -> None:
            async for msg in servidor:
                if msg.type == WSMsgType.BINARY:
                    await cliente.send_bytes(msg.data)
                    continue
                if msg.type != WSMsgType.TEXT:
                    break
                try:
                    datos = json.loads(msg.data)
                except ValueError:
                    # Core también cierra con un JSON inválido.
                    break
                if not _tipos_denegados(datos):
                    await cliente.send_str(msg.data)
                    continue
                # Como el real: una sola respuesta, con el id si el mensaje es
                # un objeto y sin id si es una lista; no se reenvía nada.
                await servidor.send_json(
                    {
                        "id": datos.get("id") if isinstance(datos, dict) else None,
                        "type": "result",
                        "success": False,
                        "error": {"code": "unauthorized", "message": "Unauthorized"},
                    }
                )

        tareas = [asyncio.ensure_future(de_core_al_addon()), asyncio.ensure_future(del_addon_a_core())]
        try:
            await asyncio.wait(tareas, return_when=asyncio.FIRST_COMPLETED)
        finally:
            # Cierre en un lado → cierre del otro.
            for tarea in tareas:
                tarea.cancel()
            await asyncio.gather(*tareas, return_exceptions=True)
            await cliente.close()
            await servidor.close()
        return servidor

    async def abrir_sesion(app: web.Application) -> None:
        app[_CLAVE_SESION] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300))

    async def cerrar_sesion(app: web.Application) -> None:
        await app[_CLAVE_SESION].close()

    # Mismo orden que el real: el filtro va primero.
    app = web.Application(middlewares=[bloquear_peticiones_peligrosas, no_encontrado])
    app.on_startup.append(abrir_sesion)
    app.on_cleanup.append(cerrar_sesion)
    app.router.add_get("/supervisor/ping", ping)
    app.router.add_get("/core/info", core_info)
    # Mismo orden que el real: las rutas de la WebSocket antes que el proxy
    # genérico. Solo GET, POST y DELETE: el real no registra PUT ni PATCH y
    # aiohttp responde 405, igual que él.
    app.router.add_get("/core/api/websocket", websocket)
    app.router.add_get("/core/websocket", websocket)
    app.router.add_post("/core/api/{path:.+}", api)
    app.router.add_get("/core/api/{path:.+}", api)
    app.router.add_delete("/core/api/{path:.+}", api)
    app.router.add_get("/core/api/", api)
    return app


async def arrancar(
    core_url: str, token_addon: str, token_core: str, version_core: str
) -> tuple[web.AppRunner, str]:
    """Levanta el simulado en un puerto libre de 127.0.0.1. Devuelve (runner, url)."""
    runner = web.AppRunner(crear_app(core_url, token_addon, token_core, version_core))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    puerto = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    return runner, f"http://127.0.0.1:{puerto}"
