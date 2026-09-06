"""Hermes — Middleware Starlette para seguridad y observabilidad.

Stack de middleware (de fuera a dentro):
  1. RateLimitPreAuth  — DoS por IP antes del bearer
  2. OAuthBearerAuth   — valida el access token
  3. RateLimitPostAuth — rate limit global post-auth
  4. RequestIdMiddleware — UUID4 por request en contextvars
  5. LoggingMiddleware — structlog con campos estándar
  6. McpProtocolVersionMiddleware — error JSON-RPC legible ante versiones
     de protocolo que el SDK no habla (y log del motivo)

Este orden es intencional y crítico. Comentarios numerados para que
ningún refactor lo mueva por accidente.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import structlog
from mcp_types.version import SUPPORTED_PROTOCOL_VERSIONS
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from hermes.logging_setup import REQUEST_ID

logger = structlog.get_logger(__name__)

# ── Paths que NO requieren autenticación OAuth ────────────────
# Estos endpoints son pre-auth por definición (discovery, login, token exchange)
# pero SÍ están sujetos al rate limit pre-auth.
#
# /register, /authorize, /token y /revoke son los paths POR DEFECTO que la
# spec MCP manda usar a un cliente que no consigue leer los metadatos del
# authorization server (RFC 8414). Si respondieran 401, el cliente lo
# interpreta como fallo de registro y reinicia el flujo desde cero.
_OAUTH_PUBLIC_PATHS = frozenset({
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-authorization-server",
    "/oauth/register",
    "/oauth/authorize",
    "/oauth/token",
    "/oauth/revoke",
    "/register",
    "/authorize",
    "/token",
    "/revoke",
})


def _is_public_path(path: str) -> bool:
    """Devuelve True si el path es un endpoint público (OAuth/well-known)."""
    return path in _OAUTH_PUBLIC_PATHS or path.startswith("/.well-known/")


# Código JSON-RPC para "demasiadas peticiones". El rango -32000..-32099
# está reservado a errores definidos por la implementación (JSON-RPC 2.0 §5.1).
RATE_LIMITED = -32029


def _too_many_requests(request: Request) -> JSONResponse:
    """429 con `Retry-After` y, en el endpoint MCP, cuerpo JSON-RPC.

    Un cuerpo plano `{"error": "too_many_requests"}` no es una respuesta
    JSON-RPC válida: el cliente MCP no puede leer el motivo y lo reporta como
    fallo genérico de transporte. Con un error JSON-RPC bien formado sí puede
    decir lo que pasa y respetar el Retry-After, en vez de rehacer el handshake
    (que gasta más cupo todavía).
    """
    headers = {"Retry-After": "60"}
    if not _is_public_path(request.url.path):
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": RATE_LIMITED,
                    "message": "Too many requests",
                    "data": {"retry_after_seconds": 60},
                },
            },
            status_code=429,
            headers=headers,
        )
    return JSONResponse(
        {"error": "too_many_requests"}, status_code=429, headers=headers
    )


# Cubo para intentos con un bearer inválido. Va aparte del cupo del dueño a
# propósito: si compartieran cubo, un atacante sin credenciales podría echarlo
# del servidor simplemente gastándolo.
_AUTH_FAILURE_BUCKET: dict[str, list[float]] = {}
_AUTH_FAILURE_WINDOW = 60.0


def record_auth_failure(client_ip: str, max_per_minute: int) -> bool:
    """Anota un fallo de autenticación. Devuelve True si hay que cortar ya.

    Se llama desde `OAuthBearerAuth` cuando el token no valida. Acota un flood
    de tokens basura sin tocar el cupo del tráfico legítimo.
    """
    now = time.monotonic()
    cutoff = now - _AUTH_FAILURE_WINDOW
    stamps = [t for t in _AUTH_FAILURE_BUCKET.get(client_ip, []) if t > cutoff]
    stamps.append(now)
    _AUTH_FAILURE_BUCKET[client_ip] = stamps
    if len(_AUTH_FAILURE_BUCKET) > 10_000:  # cota de memoria, igual que arriba
        _AUTH_FAILURE_BUCKET.clear()
        _AUTH_FAILURE_BUCKET[client_ip] = stamps
    return len(stamps) > max_per_minute



# ── 1. Rate Limit Pre-Auth (por IP) ──────────────────────────

class RateLimitPreAuth(BaseHTTPMiddleware):
    """Rate limit por IP de origen, antes de validar autenticación.

    QUÉ IP SE VE DE VERDAD
    ----------------------
    Tras el Funnel el par TCP es el loopback, pero el cubo NO es global:
    uvicorn monta `ProxyHeadersMiddleware` por defecto (`proxy_headers=True`,
    `forwarded_allow_ips="127.0.0.1"`), y como tailscaled hace proxy desde el
    loopback, uvicorn confía en su `X-Forwarded-For` y reescribe el cliente con
    la IP real del origen.

    Falsificar esa cabecera no sirve: tailscaled la reescribe en vez de
    respetarla, y uvicorn, además, recorre la lista en orden inverso y se queda
    con el primer salto que no sea de confianza.

    CAVEAT del modo `reverse_proxy`: si `mcp_bind` apunta a la red puente
    (172.30.32.1) el par TCP ya no es 127.0.0.1, así que uvicorn ignora la
    cabecera y todas las peticiones se ven con la IP del proxy. Ahí el cubo sí
    es global.

    Nada del sistema AUTORIZA por IP —solo se usa para rate limit y logs—, así
    que una IP falseada no daría escalada de privilegio.

    POR QUÉ LA CLAVE DEL CUBO NO MIRA EL BEARER
    -------------------------------------------
    La clave no puede depender de nada que el cliente pueda inventar. Repartir
    en dos cubos según si la request trae `Authorization: Bearer` deja el
    discriminante en manos del atacante: basta con mandar
    `Authorization: Bearer basura` para ascender del cubo estricto al caro, y en
    los endpoints OAuth ese token no lo valida nadie aguas abajo
    (`_is_public_path` los salta), así que el techo de fuerza bruta contra el
    login subiría del límite estricto al global.

    El reparto real, por tanto, es por ruta:

      - Rutas públicas (OAuth, discovery, health): cubo estricto. Es la
        superficie donde de verdad no hay autenticación y donde vive la fuerza
        bruta contra la password.
      - Rutas protegidas: este middleware NO limita. Pasan a `OAuthBearerAuth`,
        que rechaza el token inválido, y solo el tráfico legítimo llega a
        `RateLimitPostAuth` (120/min). Un flood de tokens basura queda acotado
        por el cubo de fallos de autenticación (ver `record_auth_failure`), que
        va aparte del cupo del dueño y por tanto no puede expulsarlo.

    Un cubo único para todo el tráfico tampoco vale: su límite estricto acaba
    siendo el techo real del servidor y `mcp_max_requests_per_minute` no se
    aplica nunca. Una ráfaga de llamadas en paralelo —el cliente MCP las hace—
    agota el cupo, el cliente reacciona rehaciendo el handshake OAuth, que
    gasta más cupo, y el fallo se realimenta.

    Purga IPs inactivas cada _PURGE_INTERVAL dispatches y mantiene un tope de
    _MAX_TRACKED_IPS para evitar fuga de memoria.
    """

    _PURGE_INTERVAL = 100
    _MAX_TRACKED_IPS = 10_000

    def __init__(
        self,
        app: ASGIApp,
        max_per_minute: int = 20,
        authenticated_max_per_minute: int = 120,
    ) -> None:
        super().__init__(app)
        self._max = max_per_minute
        self._auth_max = authenticated_max_per_minute
        self._window = 60.0
        # clave de cubo -> timestamps. La clave es siempre "<ip>|public":
        # aquí solo se contabilizan las rutas públicas, y el sufijo fijo deja
        # sitio a futuros cubos sin que la clave dependa de la request.
        self._requests: dict[str, list[float]] = {}
        self._dispatch_count = 0

    def _purge_stale_ips(self, now: float) -> None:
        """Elimina IPs sin requests recientes para evitar crecimiento sin tope."""
        cutoff = now - self._window
        stale = [ip for ip, ts in self._requests.items() if not ts or ts[-1] <= cutoff]
        for ip in stale:
            del self._requests[ip]

        # Hard cap: si aún hay demasiadas IPs, descartar las más antiguas
        if len(self._requests) > self._MAX_TRACKED_IPS:
            sorted_ips = sorted(
                self._requests.items(),
                key=lambda item: item[1][-1] if item[1] else 0,
            )
            excess = len(self._requests) - self._MAX_TRACKED_IPS
            for ip, _ in sorted_ips[:excess]:
                del self._requests[ip]

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()

        path = request.url.path

        # Las rutas protegidas no se limitan aquí: las gobierna
        # RateLimitPostAuth DESPUÉS de validar el token, para que nadie pueda
        # consumir el cupo del dueño sin autenticarse. Los fallos de
        # autenticación tienen su propio cubo (`_AUTH_FAILURE_BUCKET`), que se
        # incrementa desde OAuthBearerAuth.
        if not _is_public_path(path) and path != "/health":
            return await call_next(request)

        bucket = f"{client_ip}|public"
        limit, which = self._max, "public"

        # Purga periódica de IPs inactivas
        self._dispatch_count += 1
        if self._dispatch_count % self._PURGE_INTERVAL == 0:
            self._purge_stale_ips(now)

        # Limpiar ventana para esta IP
        cutoff = now - self._window
        timestamps = self._requests.get(bucket, [])
        timestamps = [t for t in timestamps if t > cutoff]
        self._requests[bucket] = timestamps

        if len(timestamps) >= limit:
            logger.warning(
                "rate_limit_pre_auth",
                src_ip=client_ip,
                path=request.url.path,
                bucket=which,
                limit=limit,
                reason="rate_limit_pre_auth",
            )
            return _too_many_requests(request)

        timestamps.append(now)
        return await call_next(request)


# ── 2. OAuth Bearer Auth ─────────────────────────────────────

class OAuthBearerAuth(BaseHTTPMiddleware):
    """Valida el access token OAuth 2.1.

    Los tokens son opacos: cadenas aleatorias que se validan buscando su
    SHA-256 en disco. No son JWT y no llevan nada dentro.

    Los endpoints públicos (/.well-known/*, /oauth/*) se saltan la
    validación. Todo lo demás requiere un bearer token válido.

    El 401 lleva `resource_metadata` en WWW-Authenticate (RFC 9728 §5.1):
    la spec MCP obliga al cliente a usar esa URL como primera opción de
    discovery, antes de adivinar los well-known por path y por raíz. Sin
    ella, cada reconexión son 2-3 round trips más a través de Funnel, y
    cada round trip es una oportunidad de fallo.
    """

    def __init__(
        self,
        app: ASGIApp,
        oauth_validator: Any = None,
        resource_metadata_url: str | None = None,
        auth_failure_max_per_minute: int = 20,
    ) -> None:
        super().__init__(app)
        self._oauth_validator = oauth_validator
        self._auth_failure_max = auth_failure_max_per_minute
        challenge = 'Bearer realm="hermes"'
        if resource_metadata_url:
            challenge += f', resource_metadata="{resource_metadata_url}"'
        self._www_authenticate = challenge

    def _reject(self, request: Request) -> Response:
        """401 + anota el fallo en el cubo de autenticación.

        `RateLimitPreAuth` no limita las rutas protegidas (ver su docstring),
        así que este cubo es lo que acota un flood de tokens basura. Vive
        aparte del cupo del tráfico legítimo para que un atacante sin
        credenciales no pueda expulsar al dueño consumiéndolo.
        """
        client_ip = request.client.host if request.client else "unknown"
        if record_auth_failure(client_ip, self._auth_failure_max):
            logger.warning(
                "auth_failure_flood",
                src_ip=client_ip,
                path=request.url.path,
                reason="too_many_auth_failures",
            )
            return _too_many_requests(request)
        return self._unauthorized(request)

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path

        # Endpoints públicos no requieren auth
        if _is_public_path(path):
            return await call_next(request)

        # Health endpoint tampoco requiere auth (red interna hassio)
        if path == "/health":
            return await call_next(request)

        # Extraer bearer token
        auth_header = request.headers.get("authorization", "")
        if not auth_header:
            return self._reject(request)

        # Validar formato
        parts = auth_header.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return self._reject(request)

        token = parts[1].strip()
        if not token:
            return self._reject(request)

        # Validar el token con el servidor OAuth
        if self._oauth_validator is not None:
            valid = await self._oauth_validator.validate_token(token)
            if not valid:
                return self._reject(request)

        return await call_next(request)

    def _unauthorized(self, request: Request) -> Response:
        """Respuesta 401 genérica — nunca distingue el motivo."""
        client_ip = request.client.host if request.client else "unknown"
        logger.warning(
            "auth_rejected",
            src_ip=client_ip,
            path=request.url.path,
            user_agent=request.headers.get("user-agent", ""),
            reason="unauthorized",
        )
        return JSONResponse(
            {"error": "unauthorized"},
            status_code=401,
            headers={
                "WWW-Authenticate": self._www_authenticate,
            },
        )


# ── 3. Rate Limit Post-Auth (global) ─────────────────────────

class RateLimitPostAuth(BaseHTTPMiddleware):
    """Rate limit global post-autenticación.

    Defensa contra bugs del cliente MCP en bucle cerrado y contra
    tokens filtrados.

    LIMITACIÓN CONOCIDA: el bucket es global, NO por client_id. Encaja con el
    modelo single-user de Hermes, pero significa que dos clientes MCP legítimos
    (p. ej. móvil y escritorio) activos a la vez compiten por el mismo cupo de
    requests/min. Separarlo exigiría que el access token llevase la identidad
    del cliente y que el middleware la leyera tras la validación OAuth.
    """

    def __init__(self, app: ASGIApp, max_per_minute: int = 120) -> None:
        super().__init__(app)
        self._max = max_per_minute
        self._window = 60.0
        self._requests: list[float] = []

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path

        # Solo aplicar a endpoints autenticados (no OAuth, no health)
        if _is_public_path(path) or path == "/health":
            return await call_next(request)

        now = time.monotonic()
        cutoff = now - self._window
        self._requests = [t for t in self._requests if t > cutoff]

        if len(self._requests) >= self._max:
            logger.warning(
                "rate_limit_post_auth",
                path=request.url.path,
                reason="rate_limit_post_auth",
            )
            return _too_many_requests(request)

        self._requests.append(now)
        return await call_next(request)


# ── 4. Request ID ─────────────────────────────────────────────

class RequestIdMiddleware(BaseHTTPMiddleware):
    """Genera UUID4 por request y lo propaga por contextvars."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request_id = str(uuid.uuid4())
        REQUEST_ID.set(request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ── 5. Logging ────────────────────────────────────────────────

class LoggingMiddleware(BaseHTTPMiddleware):
    """Log estructurado de cada request con campos estándar.

    Para respuestas 4xx/5xx del endpoint MCP se añade el motivo: el SDK
    devuelve la causa en el cuerpo (JSON-RPC error) sin loguear nada, y un
    `status: 400` a secas no permite diagnosticar (versión de protocolo no
    soportada, JSON inválido, cabeceras…). Se incluyen también las cabeceras
    del cliente que deciden esos rechazos. Nunca se loguea Authorization.
    """

    # Tope de bytes del cuerpo de error que se leen y se loguean.
    _ERROR_BODY_MAX_BYTES = 4096
    _ERROR_BODY_LOG_CHARS = 600

    # Cabeceras de request útiles para diagnosticar un rechazo del transporte.
    _DIAG_HEADERS = (
        ("user-agent", "user_agent"),
        ("mcp-protocol-version", "mcp_protocol_version"),
        ("mcp-session-id", "mcp_session_id"),
        ("content-type", "content_type"),
        ("accept", "accept"),
        ("origin", "origin"),
    )

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        start = time.monotonic()

        response = await call_next(request)

        duration_ms = round((time.monotonic() - start) * 1000, 1)
        log_level = "info" if response.status_code < 400 else "warning"

        extra: dict[str, Any] = {}
        if response.status_code >= 400 and not _is_public_path(request.url.path):
            response, error_body = await self._buffer_error_body(response)
            if error_body:
                extra["error"] = error_body
            for header, field in self._DIAG_HEADERS:
                value = request.headers.get(header)
                if value:
                    extra[field] = value

        getattr(logger, log_level)(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
            src_ip=request.client.host if request.client else "unknown",
            **extra,
        )

        return response

    async def _buffer_error_body(self, response: Response) -> tuple[Response, str]:
        """Lee el cuerpo (acotado) de una respuesta de error y la reconstruye.

        Solo se llama para 4xx/5xx: son cuerpos pequeños de JSON, nunca el
        stream SSE de una respuesta 200. Si el cuerpo supera el tope se
        devuelve la respuesta original sin tocar y no se loguea el motivo.
        """
        body_iterator = getattr(response, "body_iterator", None)
        if body_iterator is None:
            return response, ""

        chunks: list[bytes] = []
        total = 0
        overflow = False
        async for chunk in body_iterator:
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            chunks.append(chunk)
            total += len(chunk)
            if total > self._ERROR_BODY_MAX_BYTES:
                overflow = True
                break

        if overflow:
            # Reconstruir un iterador que reemita lo leído y siga con el resto.
            consumed = chunks

            async def _replay() -> Any:
                for c in consumed:
                    yield c
                async for c in body_iterator:
                    yield c

            response.body_iterator = _replay()
            return response, ""

        body = b"".join(chunks)
        rebuilt = Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
            background=response.background,
        )
        text = body.decode("utf-8", errors="replace").strip()
        if len(text) > self._ERROR_BODY_LOG_CHARS:
            text = text[: self._ERROR_BODY_LOG_CHARS] + "…"
        return rebuilt, text


# ── 6. Versión de protocolo MCP no soportada ─────────────────

class McpProtocolVersionMiddleware:
    """Rechaza con un error JSON-RPC legible las versiones de protocolo MCP
    que el SDK instalado no habla.

    Ante un POST con un `MCP-Protocol-Version` que no negocia, el SDK responde
    400 con un error genérico (-32600 "Bad Request") y sin loguear nada: en los
    logs del add-on solo queda un `status: 400`, y el cliente no recibe ningún
    motivo estructurado con el que decidir su fallback.

    Este middleware, delante del SDK, hace dos cosas:
      1. Loguea `mcp_protocol_version_unsupported` con la versión pedida, el
         método y el user-agent, para que el fallo sea diagnosticable.
      2. Responde el error que define la spec para este caso: JSON-RPC -32022
         UNSUPPORTED_PROTOCOL_VERSION con `data.supported` (las versiones que
         sí hablamos) y `data.requested`, HTTP 400, con el `id` de la request.
         Un cliente moderno usa `supported` para decidir el fallback al
         `initialize` clásico.

    Las requests `initialize` se dejan pasar siempre: el SDK ignora la
    cabecera en el handshake (la versión se negocia en el body). Las versiones
    soportadas se leen del SDK en runtime, así que el middleware deja de
    intervenir por sí solo en cuanto una actualización del SDK añade la versión
    que antes rechazaba.
    """

    UNSUPPORTED_PROTOCOL_VERSION = -32022

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._supported = tuple(SUPPORTED_PROTOCOL_VERSIONS)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return

        requested = None
        user_agent = ""
        for name, value in scope.get("headers") or []:
            if name == b"mcp-protocol-version":
                requested = value.decode("latin-1").strip()
            elif name == b"user-agent":
                user_agent = value.decode("latin-1", errors="replace")

        if not requested or requested in self._supported:
            await self.app(scope, receive, send)
            return

        # Cabecera presente y no soportada: hace falta el body para conocer
        # el método (initialize pasa) y el id (para la respuesta JSON-RPC).
        chunks: list[bytes] = []
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                async def _passthrough(_m: dict = message) -> Any:
                    return _m
                await self.app(scope, _passthrough, send)
                return
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        body = b"".join(chunks)

        method, request_id = self._peek(body)
        if method == "initialize":
            replayed = False

            async def _replay() -> Any:
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            await self.app(scope, _replay, send)
            return

        logger.warning(
            "mcp_protocol_version_unsupported",
            requested=requested,
            supported=list(self._supported),
            method=method,
            user_agent=user_agent,
        )

        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": self.UNSUPPORTED_PROTOCOL_VERSION,
                "message": "Unsupported protocol version",
                "data": {
                    "supported": list(self._supported),
                    "requested": requested,
                },
            },
        }
        response = JSONResponse(payload, status_code=400)
        await response(scope, receive, send)

    @staticmethod
    def _peek(body: bytes) -> tuple[str | None, Any]:
        """Extrae (method, id) de un body JSON-RPC sin validarlo.

        Devuelve (None, None) si no es un objeto JSON; el SDK ya responderá
        al body malformado con su propio error.
        """
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return None, None
        if not isinstance(data, dict):
            return None, None
        method = data.get("method")
        request_id = data.get("id")
        if not isinstance(method, str):
            method = None
        if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
            request_id = None
        return method, request_id


# ── Body Size Limit ────────────────────────────────────────
# Posición 0 en la numeración porque se aplica ANTES de todo.
# h11_max_incomplete_event_size solo limita headers HTTP incompletos,
# NO el body. Este middleware rechaza bodies >max_body_bytes con 413.

class BodySizeLimitMiddleware:
    """Rechaza requests cuyo body excede el tope aplicable.

    Implementado a nivel ASGI (no BaseHTTPMiddleware) para cubrir DOS casos:
    1. Content-Length declarado y excesivo → 413 inmediato (fast-path, gratis).
    2. Transfer-Encoding: chunked SIN Content-Length → se bufferiza el body
       con un tope y, al superarlo, se responde 413 sin pasar la request a la
       app. El body (hasta el tope) se re-inyecta intacto hacia abajo.

    Sin (2), un cliente podría enviar un body chunked ilimitado: ni uvicorn
    ni Starlette aplican límite de body por defecto en ese caso.

    POR QUÉ NO VA EL PRIMERO DEL STACK
    ----------------------------------
    El caso (2) obliga a bufferizar: para responder un 413 limpio hay que leer
    por delante, y para poder reenviar el body hay que conservarlo. Eso es
    intrínseco al diseño y no se puede evitar contando sin guardar.

    Lo que sí se puede evitar es **bufferizar el cuerpo de quien va a ser
    rechazado igualmente**. Si fuese el middleware más externo, una petición
    anónima con 4 MiB de body chunked se leería entera en memoria y solo DESPUÉS
    la rechazaría `OAuthBearerAuth` con un 401: memoria del host a coste cero
    para un atacante sin credenciales.

    Por eso va **después** de la autenticación. Ni `RateLimitPreAuth` ni
    `OAuthBearerAuth` ni el logger leen el body, así que una petición sin token
    se rechaza sin haber leído un solo byte del cuerpo.

    TOPES DISTINTOS SEGÚN LA RUTA
    -----------------------------
    Los endpoints públicos de OAuth quedan por delante de la autenticación, así
    que siguen siendo alcanzables sin credenciales. Pero un registro DCR o una
    petición de token son de unos pocos KB: aceptar megabytes ahí no tiene
    ningún uso legítimo y sí habilita un flood de escrituras a disco. Por eso
    llevan su propio tope, mucho más pequeño.
    """

    #: Tope para los endpoints públicos (OAuth y discovery). Un registro DCR
    #: legítimo son cientos de bytes; 64 KiB deja margen de sobra.
    PUBLIC_MAX_BODY_BYTES = 65_536

    def __init__(
        self,
        app: ASGIApp,
        max_body_bytes: int = 4_194_304,
        public_max_body_bytes: int | None = None,
    ) -> None:
        self.app = app
        self._max = max_body_bytes
        self._public_max = (
            public_max_body_bytes
            if public_max_body_bytes is not None
            else min(self.PUBLIC_MAX_BODY_BYTES, max_body_bytes)
        )

    def _limit_for(self, path: str) -> int:
        return self._public_max if _is_public_path(path) else self._max

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        limit = self._limit_for(path)

        # Fast-path: Content-Length declarado y excesivo → 413 inmediato.
        for name, value in scope.get("headers") or []:
            if name == b"content-length":
                try:
                    if int(value) > limit:
                        await self._reject(send, path, limit, declared=int(value))
                        return
                except (ValueError, TypeError):
                    pass
                break

        # Bufferizar el body con tope (cubre chunked sin Content-Length).
        chunks: list[bytes] = []
        total = 0
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                # http.disconnect u otro mensaje: re-emitirlo tal cual.
                async def _passthrough(_m: dict = message) -> Any:
                    return _m
                await self.app(scope, _passthrough, send)
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > limit:
                await self._reject(send, path, limit, declared=None)
                return
            chunks.append(chunk)
            more = message.get("more_body", False)

        buffered = b"".join(chunks)
        replayed = False

        async def replay() -> Any:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": buffered, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    async def _reject(
        self,
        send: Send,
        path: str = "",
        limit: int | None = None,
        declared: int | None = None,
    ) -> None:
        limit = self._max if limit is None else limit
        # Se loguea aquí porque este 413 se genera por fuera del
        # LoggingMiddleware: sin esta línea, un flood de cuerpos grandes sería
        # invisible en los logs del add-on.
        logger.warning(
            "body_too_large",
            path=path,
            limit_bytes=limit,
            declared_bytes=declared,
            reason="payload_too_large",
        )
        body = (
            b'{"error":"payload_too_large","max_bytes":'
            + str(limit).encode("ascii")
            + b"}"
        )
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})


# ── Security headers ──────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Añade cabeceras de seguridad a todas las respuestas.

    - X-Content-Type-Options: nosniff — evita MIME sniffing.
    - X-Frame-Options: DENY — evita clickjacking del formulario de login.
    - Referrer-Policy: no-referrer — la URL puede llevar code/state OAuth.
    - Content-Security-Policy restrictiva para el login HTML inline
      (estilos inline permitidos, sin scripts).

    NO se usa la directiva `form-action`: rompe el flujo OAuth. Tras el POST
    del login, Hermes responde con un 302 al `redirect_uri` del cliente (p. ej.
    claude.ai), y los navegadores Chromium aplican `form-action` a ese redirect
    post-submit, bloqueándolo en silencio (el login parece "colgarse" sin
    error). El destino del redirect ya se valida en la capa OAuth (DCR +
    allowlist de redirect_uris por cliente), así que `form-action` sería
    redundante además de romper el flujo.

    HSTS lo añade Tailscale Funnel (termina TLS); no se duplica aquí.
    """

    _CSP = (
        "default-src 'none'; style-src 'unsafe-inline'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Content-Security-Policy", self._CSP)
        return response
