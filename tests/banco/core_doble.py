"""Doble de HA Core para probar sin Docker las piezas del banco (spec 010).

El banco de verdad solo existe en el job `banco-core` del CI. Para que el
onboarding, el Supervisor simulado, el entorno y el lector independiente se
puedan probar en cualquier máquina (también en Windows), este servidor `aiohttp`
local imita lo justo de Core 2026.11.1:

- el onboarding (`/api/onboarding`, `/api/onboarding/{users,core_config,analytics,integration}`)
  y `/auth/token`, con la forma de `components/onboarding/views.py` y
  `components/auth/__init__.py`;
- `/api/config` con un `state` que tarda N sondeos en llegar a `RUNNING`;
- `/api/`, `/api/states/{entity_id}` y una ruta REST de eco que devuelve lo que
  ha recibido (método, ruta, query, `Content-Type` y token);
- `/api/websocket` con la fase de auth, `auth/long_lived_access_token`,
  `subscribe_events` (emite un evento de prueba), `eco/error` (lo rechaza,
  spec 028) y eco de cualquier
  otro comando.

Registra lo que recibe para que los tests comprueben, por ejemplo, con qué
token le llegó una petición. Nunca registra los cuerpos de
`/api/onboarding/users` ni de `/auth/token`: llevan la contraseña y el código.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from typing import Any

from aiohttp import WSMsgType, web


@dataclass
class Registro:
    """Lo que el doble ha visto, sin credenciales en claro salvo los tokens.

    Los tokens se guardan porque es justo lo que se comprueba («a Core le llega
    el token de Core y no el de add-on»); son del propio test, no reales.
    """

    pasos: list[str] = field(default_factory=list)
    rest: list[dict[str, Any]] = field(default_factory=list)
    ws_comandos: list[dict[str, Any]] = field(default_factory=list)
    ws_tokens: list[str] = field(default_factory=list)
    ws_cerradas: int = 0
    integracion: dict[str, Any] = field(default_factory=dict)
    sondeos_config: int = 0


class CoreDoble:
    """Servidor local que imita a Core. Se usa con `async with`."""

    def __init__(
        self,
        *,
        version: str = "2026.11.1",
        sondeos_not_running: int = 0,
        fallos: dict[str, int] | None = None,
        token_core: str | None = None,
        estados: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.version = version
        self.sondeos_not_running = sondeos_not_running
        # paso → código HTTP que devuelve en vez de responder bien.
        self.fallos = dict(fallos or {})
        self.estados = dict(estados or {})
        self.registro = Registro()
        self._usuario_hecho = False
        self._codigos: set[str] = set()
        self._tokens: set[str] = set()
        if token_core is not None:
            self._tokens.add(token_core)
        self._runner: web.AppRunner | None = None
        self.url = ""

    # ── Ciclo de vida ────────────────────────────────────────────────────
    async def __aenter__(self) -> "CoreDoble":
        app = web.Application()
        app.router.add_get("/api/onboarding", self._onboarding)
        app.router.add_post("/api/onboarding/users", self._users)
        app.router.add_post("/api/onboarding/{paso}", self._paso)
        app.router.add_post("/auth/token", self._token)
        app.router.add_get("/api/config", self._config)
        app.router.add_get("/api/websocket", self._websocket)
        app.router.add_get("/api/", self._raiz)
        app.router.add_get("/api/states/{entity_id}", self._estado)
        for metodo in ("GET", "POST", "DELETE", "PUT", "PATCH"):
            app.router.add_route(metodo, "/api/eco/{ruta:.*}", self._eco)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        puerto = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        self.url = f"http://127.0.0.1:{puerto}"
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._runner is not None:
            await self._runner.cleanup()

    # ── Utilidades ───────────────────────────────────────────────────────
    def _token_de(self, request: web.Request) -> str | None:
        cabecera = request.headers.get("Authorization", "")
        if cabecera.startswith("Bearer "):
            return cabecera[len("Bearer "):]
        return None

    def _autorizado(self, request: web.Request) -> bool:
        token = self._token_de(request)
        return token is not None and token in self._tokens

    def _fallo(self, paso: str) -> web.Response | None:
        if paso in self.fallos:
            # Cuerpo con un marcador: el test comprueba que el onboarding no lo
            # copia en el mensaje de error.
            return web.json_response(
                {"message": f"cuerpo-del-error-{paso}"}, status=self.fallos[paso]
            )
        return None

    def _nuevo_token(self) -> str:
        token = secrets.token_urlsafe(16)
        self._tokens.add(token)
        return token

    # ── Onboarding ───────────────────────────────────────────────────────
    async def _onboarding(self, request: web.Request) -> web.Response:
        fallo = self._fallo("onboarding")
        if fallo is not None:
            return fallo
        pasos = ("user", "core_config", "analytics", "integration")
        return web.json_response([{"step": p, "done": False} for p in pasos])

    async def _users(self, request: web.Request) -> web.Response:
        self.registro.pasos.append("users")
        fallo = self._fallo("users")
        if fallo is not None:
            return fallo
        datos = await request.json()
        faltan = {"name", "username", "password", "client_id", "language"} - set(datos)
        if faltan:
            return web.json_response({"message": "faltan campos"}, status=400)
        if self._usuario_hecho:
            # Igual que Core: el paso de usuario solo se hace una vez.
            return web.json_response({"message": "User step already done"}, status=403)
        self._usuario_hecho = True
        codigo = secrets.token_urlsafe(8)
        self._codigos.add(codigo)
        return web.json_response({"auth_code": codigo})

    async def _token(self, request: web.Request) -> web.Response:
        self.registro.pasos.append("token")
        fallo = self._fallo("token")
        if fallo is not None:
            return fallo
        datos = await request.post()
        if datos.get("grant_type") != "authorization_code" or datos.get("code") not in self._codigos:
            return web.json_response({"error": "invalid_request"}, status=400)
        self._codigos.discard(str(datos.get("code")))
        return web.json_response(
            {
                "access_token": self._nuevo_token(),
                "token_type": "Bearer",
                "refresh_token": secrets.token_urlsafe(16),
                "expires_in": 1800,
            }
        )

    async def _paso(self, request: web.Request) -> web.Response:
        paso = request.match_info["paso"]
        if paso not in ("core_config", "analytics", "integration"):
            raise web.HTTPNotFound()
        self.registro.pasos.append(paso)
        if not self._autorizado(request):
            return web.json_response({"message": "Unauthorized"}, status=401)
        fallo = self._fallo(paso)
        if fallo is not None:
            return fallo
        if paso == "integration":
            datos = await request.json()
            self.registro.integracion = {
                "client_id": datos.get("client_id"),
                "redirect_uri": datos.get("redirect_uri"),
            }
            return web.json_response({"auth_code": secrets.token_urlsafe(8)})
        return web.json_response({})

    # ── API REST ─────────────────────────────────────────────────────────
    async def _config(self, request: web.Request) -> web.Response:
        if not self._autorizado(request):
            return web.json_response({"message": "Unauthorized"}, status=401)
        self.registro.sondeos_config += 1
        fallo = self._fallo("config")
        if fallo is not None:
            return fallo
        estado = (
            "NOT_RUNNING"
            if self.registro.sondeos_config <= self.sondeos_not_running
            else "RUNNING"
        )
        return web.json_response({"version": self.version, "state": estado})

    async def _raiz(self, request: web.Request) -> web.Response:
        self._anotar(request, "")
        if not self._autorizado(request):
            return web.json_response({"message": "Unauthorized"}, status=401)
        return web.json_response({"message": "API running."})

    async def _estado(self, request: web.Request) -> web.Response:
        if not self._autorizado(request):
            return web.json_response({"message": "Unauthorized"}, status=401)
        entity_id = request.match_info["entity_id"]
        if entity_id not in self.estados:
            return web.json_response({"message": "Entity not found."}, status=404)
        return web.json_response(self.estados[entity_id])

    def _anotar(self, request: web.Request, ruta: str) -> dict[str, Any]:
        anotacion = {
            "metodo": request.method,
            "ruta": ruta,
            "ruta_cruda": request.raw_path,
            "query": request.query_string,
            "content_type": request.headers.get("Content-Type"),
            "token": self._token_de(request),
        }
        self.registro.rest.append(anotacion)
        return anotacion

    async def _eco(self, request: web.Request) -> web.Response:
        anotacion = self._anotar(request, request.match_info["ruta"])
        if not self._autorizado(request):
            return web.json_response({"message": "Unauthorized"}, status=401)
        cuerpo = await request.read()
        respuesta = dict(anotacion)
        respuesta["cuerpo"] = cuerpo.decode("utf-8", "replace")
        return web.json_response(respuesta, status=200)

    # ── WebSocket ────────────────────────────────────────────────────────
    async def _websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        try:
            await ws.send_json({"type": "auth_required", "ha_version": self.version})
            msg = await ws.receive_json(timeout=10)
            token = msg.get("access_token") if isinstance(msg, dict) else None
            if not isinstance(token, str) or token not in self._tokens:
                await ws.send_json({"type": "auth_invalid", "message": "Invalid access token"})
                await ws.close()
                return ws
            self.registro.ws_tokens.append(token)
            await ws.send_json({"type": "auth_ok", "ha_version": self.version})

            async for mensaje in ws:
                if mensaje.type != WSMsgType.TEXT:
                    break
                datos = json.loads(mensaje.data)
                comandos = datos if isinstance(datos, list) else [datos]
                for comando in comandos:
                    await self._comando_ws(ws, comando)
        finally:
            self.registro.ws_cerradas += 1
        return ws

    async def _comando_ws(self, ws: web.WebSocketResponse, comando: dict[str, Any]) -> None:
        tipo = comando.get("type")
        self.registro.ws_comandos.append(comando)
        id_ = comando.get("id")
        if tipo == "auth/long_lived_access_token":
            fallo = self.fallos.get("long_lived")
            if fallo is not None:
                await ws.send_json(
                    {"id": id_, "type": "result", "success": False,
                     "error": {"code": "invalid_format", "message": "cuerpo-del-error-long_lived"}}
                )
                return
            await ws.send_json(
                {"id": id_, "type": "result", "success": True, "result": self._nuevo_token()}
            )
            return
        if tipo == "eco/error":
            # Spec 028: un comando que Core rechaza, para probar `Lector.comando`.
            await ws.send_json(
                {"id": id_, "type": "result", "success": False,
                 "error": {"code": "eco_error", "message": "rechazado por el doble"}}
            )
            return
        if isinstance(tipo, str) and tipo.endswith("/delete"):
            claves = [v for k, v in comando.items() if k.endswith("_id")]
            if any(isinstance(v, str) and v.startswith("no_existe") for v in claves):
                await ws.send_json(
                    {"id": id_, "type": "result", "success": False,
                     "error": {"code": "not_found", "message": "Unable to find"}}
                )
                return
        await ws.send_json(
            {"id": id_, "type": "result", "success": True, "result": {"eco": tipo, "datos": comando}}
        )
        if tipo == "subscribe_events":
            # Un evento de prueba, como si alguien hubiera llamado a un servicio.
            await ws.send_json(
                {"id": id_, "type": "event",
                 "event": {"event_type": comando.get("event_type"),
                           "data": {"domain": "eco", "service": "prueba"}}}
            )
