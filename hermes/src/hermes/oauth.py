"""Hermes — OAuth 2.1 Authorization Server + Resource Server.

Hermes es AS y RS a la vez, en el mismo proceso Python.
Implementa OAuth 2.1 con PKCE obligatorio, DCR, y revocación.

Endpoints:
  /.well-known/oauth-protected-resource
  /.well-known/oauth-authorization-server
  /oauth/register       — Dynamic Client Registration (RFC 7591)
  /oauth/authorize      — GET: formulario login, POST: valida password
  /oauth/token          — Token endpoint (auth_code + PKCE, refresh)
  /oauth/revoke         — Revocación de tokens (RFC 7009)
  /register, /authorize, /token, /revoke — alias de los anteriores en los
                          paths por defecto que la spec MCP asigna a un
                          cliente que no ha podido leer los metadatos del AS

Persistencia: ficheros JSON en /data/oauth/
  clients/<client_id>.json
  codes/<code>.json
  tokens/<token_hash>.json
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import secrets
import time
import uuid
from base64 import urlsafe_b64encode
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

from hermes import __version__
import re

import structlog
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

logger = structlog.get_logger(__name__)

# ── Constantes ────────────────────────────────────────────────
_OAUTH_DIR = Path("/data/oauth")
_CLIENTS_DIR = _OAUTH_DIR / "clients"
_CODES_DIR = _OAUTH_DIR / "codes"
_TOKENS_DIR = _OAUTH_DIR / "tokens"

ACCESS_TOKEN_TTL = 3600       # 1 hora
REFRESH_TOKEN_TTL = 604800    # 7 días
AUTH_CODE_TTL = 60            # 60 segundos

# ── Anti fuerza bruta del login ───────────────────────────────
# El freno es GLOBAL, no por IP, y es deliberado: la password es el único
# secreto que protege todo el sistema, así que un techo global es MÁS fuerte
# que uno por IP —que se evade sin más que rotar la IP de origen—. En uso
# normal el dueño no encadena fallos, así que no estorba.
LOGIN_FAIL_THRESHOLD = 5          # fallos consecutivos antes de empezar a bloquear
LOGIN_FAIL_WINDOW = 300           # ventana de conteo de fallos (s)
LOGIN_LOCK_BASE_SECONDS = 2       # backoff base
LOGIN_LOCK_MAX_SECONDS = 300      # tope de bloqueo por escalón (5 min)

# ── Límite de clientes DCR ────────────────────────────────────
# /oauth/register es público (RFC 7591). Sin tope, un atacante podría
# registrar clientes hasta llenar el disco. 100 es holgado para single-user.
MAX_REGISTERED_CLIENTS = 100

# Esquemas de redirect_uri rechazados en DCR (vectores XSS / exfiltración).
_DANGEROUS_REDIRECT_SCHEMES = frozenset({"javascript", "data", "vbscript", "file"})

# Sub fijo — no hay multi-usuario
_FIXED_SUB = "hermes-owner"


def _ensure_dirs() -> None:
    """Crea los directorios de persistencia si no existen."""
    for d in (_CLIENTS_DIR, _CODES_DIR, _TOKENS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Escritura atómica: write-temp + os.replace()."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _safe_read(path: Path) -> dict[str, Any] | None:
    """Lee un JSON, devuelve None si no existe o está corrupto."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _prune_clients_over_limit() -> None:
    """Poda clientes DCR antiguos (FIFO) para no superar MAX_REGISTERED_CLIENTS.

    /oauth/register es público; sin tope, registros repetidos llenarían el
    disco. Se borran los más antiguos por mtime hasta dejar sitio para uno nuevo.
    """
    try:
        clients = sorted(
            _CLIENTS_DIR.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
        )
    except OSError:
        return
    excess = len(clients) - (MAX_REGISTERED_CLIENTS - 1)
    for path in clients[: max(0, excess)]:
        _safe_unlink(path)


def _hash_token(token: str) -> str:
    """SHA-256 del token para almacenamiento (nunca guardar en claro)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generate_token() -> str:
    """Genera un token opaco seguro."""
    return secrets.token_urlsafe(48)



# ── OAuth Server ──────────────────────────────────────────────

# `client_id` viene del formulario y se interpola en una ruta del sistema de
# ficheros (`clients/{client_id}.json`). Todos los demás nombres de fichero del
# módulo se derivan de `_hash_token()` (hex); este es el único que no, así que
# sin validarlo un `client_id` con `../` leería un JSON de fuera del directorio
# de clientes. Solo se llega aquí tras comprobar la password, de ahí que no sea
# grave, pero es higiene barata.
_CLIENT_ID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")


def _is_valid_client_id(client_id: str) -> bool:
    """True si `client_id` puede usarse como nombre de fichero sin riesgo."""
    return bool(client_id) and bool(_CLIENT_ID_RE.match(client_id))


# ── Rotación de refresh tokens ────────────────────────────────
# Un refresh token vive 7 días y es el único credencial duradero del sistema:
# quien lo tenga puede fabricar access tokens durante una semana, sin la
# password y sin que nada lo delate — el cliente legítimo sigue funcionando
# igual, así que el robo es invisible. OAuth 2.1 exige rotarlos justamente por
# eso para clientes públicos, que es lo que es Claude (registro dinámico, sin
# secreto).
#
# Con rotación, cada refresh entrega uno nuevo y anula el anterior. Si alguien
# vuelve a presentar el anterior, es que hay dos copias: se revoca la cadena
# entera y quien lo robó se queda fuera — y el dueño se entera porque tiene que
# volver a autorizar.
#
# GRACIA: si el cliente pide un refresh y la respuesta se pierde por el camino,
# reintentará con el token viejo sin tener el nuevo. Durante esta ventana ese
# reintento se atiende devolviendo el sucesor vigente en vez de tratarlo como
# robo. Pasada la ventana, ya no hay excusa inocente.
REFRESH_ROTATION_GRACE_SECONDS = 60

# Sesiones (cadenas de refresh token) que pueden estar vivas a la vez.
# Cinco deja sitio de sobra para móvil + escritorio + alguna suelta, y
# acota el número de credenciales duraderas que existen en cualquier
# momento. Sin tope se acumulan sin límite (ver _revoke_previous_sessions).
MAX_ACTIVE_SESSIONS = 5


def _revoke_token_chain(token_hash: str) -> int:
    """Borra un refresh token, sus sucesores y los access que colgaran de ellos.

    Se usa al detectar reutilización: si hay dos copias del mismo token, no se
    sabe cuál es la del dueño, así que caen las dos.
    """
    borrados = 0
    visitados: set[str] = set()
    actual = token_hash
    while actual and actual not in visitados:
        visitados.add(actual)
        ruta = _TOKENS_DIR / f"{actual}.json"
        datos = _safe_read(ruta)
        if datos is None:
            break
        acceso = datos.get("access_token_hash", "")
        if acceso:
            _safe_unlink(_TOKENS_DIR / f"{acceso}.json")
            borrados += 1
        _safe_unlink(ruta)
        borrados += 1
        actual = datos.get("successor_hash", "")
    return borrados


def _revoke_previous_sessions(client_id: str, keep_hash: str) -> int:
    """Acota cuántas sesiones quedan vivas al autorizar una nueva.

    Sin esto, cada autorización dejaría un refresh token más que sigue
    valiendo sus 7 días aunque nadie lo use: llaves de casa sueltas, cada una
    capaz de fabricar access tokens durante una semana.

    Se hacen dos cosas, y la segunda es la que de verdad acota:

      1. Se retiran las sesiones del mismo client_id, que es lo correcto
         cuando un cliente sí reutiliza su registro.
      2. Se acota el TOTAL de sesiones vivas a `MAX_ACTIVE_SESSIONS`,
         quedándose con las más recientes. Hace falta porque un cliente como
         Claude hace un registro dinámico nuevo en cada autorización: «el
         mismo cliente» no vuelve nunca, así que filtrar por client_id no
         retiraría nada. El margen deja sitio de sobra para varios
         dispositivos —móvil, escritorio— sin que autorizar en uno eche al
         otro, que es lo que pasaría revocándolo todo.
    """
    ahora = time.time()
    sesiones: list[tuple[float, Any, dict[str, Any]]] = []
    for fichero in _TOKENS_DIR.glob("*.json"):
        datos = _safe_read(fichero)
        if not datos or datos.get("token_type") not in ("refresh", "refresh_rotated"):
            continue
        if datos.get("token_hash") == keep_hash:
            continue
        if datos.get("successor_hash"):
            # Eslabón ya canjeado de una cadena viva: se conserva mientras dure
            # su ventana de detección de reutilización, no cuenta como sesión.
            continue
        sesiones.append((float(datos.get("created_at", 0) or 0), fichero, datos))

    sesiones.sort(key=lambda s: s[0], reverse=True)
    a_revocar = [s for s in sesiones if s[2].get("client_id") == client_id and client_id]
    restantes = [s for s in sesiones if s not in a_revocar]
    # -1 porque la sesión que se acaba de crear ya ocupa una plaza.
    sobrantes = max(0, len(restantes) - (MAX_ACTIVE_SESSIONS - 1))
    if sobrantes:
        a_revocar += restantes[-sobrantes:]

    revocados = 0
    for _, fichero, datos in a_revocar:
        acceso = datos.get("access_token_hash", "")
        if acceso:
            _safe_unlink(_TOKENS_DIR / f"{acceso}.json")
        _safe_unlink(fichero)
        revocados += 1
    return revocados


# Límites del registro dinámico de clientes (RFC 7591).
#
# `MAX_REGISTERED_CLIENTS` acota cuántos registros hay; esto acota el contenido
# de cada uno, que si no queda sin techo: un `client_name` sin comprobar
# siquiera el tipo, y `redirect_uris` sin tope de elementos ni de longitud. El
# límite de cuerpo de las rutas públicas ya acota el ataque a 64 KiB, pero un
# nombre de 64 KiB sigue sin tener sentido y acaba almacenado: mejor
# rechazarlo aquí, donde el motivo es explícito.
#
# Un cliente MCP legítimo registra uno o dos redirect_uris y un nombre corto.
MAX_CLIENT_NAME_LEN = 200
MAX_REDIRECT_URIS = 10
MAX_REDIRECT_URI_LEN = 2048


class OAuthServer:
    """Servidor OAuth 2.1 integrado en Hermes."""

    def __init__(self, auth_password: str, public_hostname: str) -> None:
        self._auth_password = auth_password
        self._public_hostname = public_hostname
        self._base_url = f"https://{public_hostname}"
        _ensure_dirs()
        self._cleanup_expired()
        self._cleanup_task: asyncio.Task | None = None

        # URL de los metadatos del recurso protegido (RFC 9728). Se anuncia en
        # el WWW-Authenticate del 401 para que el cliente vaya directo a ella.
        self.resource_metadata_url = (
            f"{self._base_url}/.well-known/oauth-protected-resource"
        )

        # Estado del throttle anti-fuerza-bruta del login (global)
        self._login_lock = asyncio.Lock()
        self._login_failed_attempts = 0
        self._login_first_fail_ts = 0.0
        self._login_locked_until = 0.0

    def _cleanup_expired(self) -> None:
        """Limpia codes y tokens expirados.

        Se ejecuta al boot (desde __init__) y cada hora vía _periodic_cleanup_loop.

        IMPORTANTE: este método DEBE permanecer síncrono (sin await).
        Se llama desde __init__ antes de que exista un event loop activo.
        Si necesitas I/O async, hazlo en _periodic_cleanup_loop.
        """
        now = time.time()
        cleaned = 0

        for code_file in _CODES_DIR.glob("*.json"):
            data = _safe_read(code_file)
            if data and now > data.get("expires_at", 0):
                _safe_unlink(code_file)
                cleaned += 1

        for token_file in _TOKENS_DIR.glob("*.json"):
            data = _safe_read(token_file)
            if data and now > data.get("expires_at", 0):
                _safe_unlink(token_file)
                cleaned += 1

        # Limpiar .tmp huérfanos (crash a media escritura atómica)
        for tmp_dir in (_CLIENTS_DIR, _CODES_DIR, _TOKENS_DIR):
            for tmp_file in tmp_dir.glob("*.tmp"):
                _safe_unlink(tmp_file)

        if cleaned:
            logger.info("oauth_cleanup", cleaned=cleaned)

    async def _periodic_cleanup_loop(self) -> None:
        """Ejecuta _cleanup_expired cada hora en background.

        Previene acumulación indefinida de codes/tokens expirados
        en instalaciones que no reinician durante semanas.
        """
        while True:
            await asyncio.sleep(3600)  # 1 hora
            try:
                self._cleanup_expired()
            except Exception:
                logger.warning("oauth_periodic_cleanup_failed", exc_info=True)

    def start_periodic_cleanup(self) -> None:
        """Arranca la task de limpieza periódica.

        Llamar desde el lifespan de Starlette.
        """
        self._cleanup_task = asyncio.create_task(
            self._periodic_cleanup_loop(),
            name="oauth_periodic_cleanup",
        )

    def stop_periodic_cleanup(self) -> None:
        """Detiene la task de limpieza periódica."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()

    # ── Well-Known endpoints ──────────────────────────────────

    async def protected_resource_metadata(self, request: Request) -> JSONResponse:
        """GET /.well-known/oauth-protected-resource"""
        return JSONResponse({
            "resource": self._base_url,
            "authorization_servers": [self._base_url],
            "bearer_methods_supported": ["header"],
        })

    async def authorization_server_metadata(self, request: Request) -> JSONResponse:
        """GET /.well-known/oauth-authorization-server"""
        return JSONResponse({
            "issuer": self._base_url,
            "authorization_endpoint": f"{self._base_url}/oauth/authorize",
            "token_endpoint": f"{self._base_url}/oauth/token",
            "registration_endpoint": f"{self._base_url}/oauth/register",
            "revocation_endpoint": f"{self._base_url}/oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": ["mcp"],
        })

    # ── Dynamic Client Registration (RFC 7591) ────────────────

    async def register_client(self, request: Request) -> JSONResponse:
        """POST /oauth/register — registra un nuevo cliente."""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"error": "invalid_request", "error_description": "Invalid JSON body"},
                status_code=400,
            )

        client_id = str(uuid.uuid4())
        redirect_uris = body.get("redirect_uris", [])
        client_name = body.get("client_name", "unknown")

        if not redirect_uris or not isinstance(redirect_uris, list):
            return JSONResponse(
                {"error": "invalid_request",
                 "error_description": "redirect_uris is required"},
                status_code=400,
            )

        if len(redirect_uris) > MAX_REDIRECT_URIS:
            return JSONResponse(
                {"error": "invalid_request",
                 "error_description":
                     f"redirect_uris admite como máximo {MAX_REDIRECT_URIS} entradas"},
                status_code=400,
            )

        # Un `null` explícito se trata como ausente, igual que si no viniera la
        # clave: el registro queda como «cliente sin nombre» y rechazarlo solo
        # rompería a clientes que hoy funcionan, sin ganar nada. Lo que sí se
        # rechaza es un tipo que no sea texto (un dict acabaría en el JSON del
        # cliente y en la pantalla de consentimiento) y un nombre desmesurado.
        if client_name is None:
            client_name = "unknown"

        if not isinstance(client_name, str) or len(client_name) > MAX_CLIENT_NAME_LEN:
            return JSONResponse(
                {"error": "invalid_request",
                 "error_description":
                     f"client_name debe ser texto de {MAX_CLIENT_NAME_LEN} "
                     "caracteres como máximo"},
                status_code=400,
            )

        # Validar cada redirect_uri: rechazar esquemas peligrosos (XSS via redirect)
        for uri in redirect_uris:
            if isinstance(uri, str) and len(uri) > MAX_REDIRECT_URI_LEN:
                return JSONResponse(
                    {"error": "invalid_request",
                     "error_description":
                         f"redirect_uri excede {MAX_REDIRECT_URI_LEN} caracteres"},
                    status_code=400,
                )
            if not isinstance(uri, str) or not uri.strip():
                return JSONResponse(
                    {"error": "invalid_request",
                     "error_description": "each redirect_uri must be a non-empty string"},
                    status_code=400,
                )
            if urlparse(uri).scheme.lower() in _DANGEROUS_REDIRECT_SCHEMES:
                return JSONResponse(
                    {"error": "invalid_request",
                     "error_description": "redirect_uri scheme not allowed"},
                    status_code=400,
                )

        # Tope de clientes registrados (anti relleno de disco vía DCR abierto)
        _prune_clients_over_limit()

        client_data = {
            "client_id": client_id,
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "created_at": time.time(),
        }

        _atomic_write(_CLIENTS_DIR / f"{client_id}.json", client_data)
        logger.info("oauth_client_registered", client_id=client_id, name=client_name)

        return JSONResponse(
            {
                "client_id": client_id,
                "client_name": client_name,
                "redirect_uris": redirect_uris,
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
            status_code=201,
        )

    # ── Authorization endpoint ────────────────────────────────

    async def authorize_get(self, request: Request) -> HTMLResponse:
        """GET /oauth/authorize — muestra formulario de login."""
        client_id = request.query_params.get("client_id", "")
        redirect_uri = request.query_params.get("redirect_uri", "")
        state = request.query_params.get("state", "")
        code_challenge = request.query_params.get("code_challenge", "")
        code_challenge_method = request.query_params.get("code_challenge_method", "")
        scope = request.query_params.get("scope", "mcp")

        return HTMLResponse(self._login_html(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scope=scope,
            error="",
        ))

    async def authorize_post(self, request: Request) -> Response:
        """POST /oauth/authorize — valida password, genera auth code."""
        form = await request.form()
        password = str(form.get("password", ""))
        client_id = str(form.get("client_id", ""))
        redirect_uri = str(form.get("redirect_uri", ""))
        state = str(form.get("state", ""))
        code_challenge = str(form.get("code_challenge", ""))
        code_challenge_method = str(form.get("code_challenge_method", ""))
        scope = str(form.get("scope", "mcp"))

        # Throttle anti-fuerza-bruta (global, no por IP: ver LOGIN_FAIL_THRESHOLD)
        now = time.time()
        lock_remaining = await self._login_lock_remaining(now)
        if lock_remaining > 0:
            logger.warning(
                "oauth_login_throttled",
                retry_after=lock_remaining,
                src_ip=request.client.host if request.client else "unknown",
            )
            return HTMLResponse(
                self._login_html(
                    client_id=client_id,
                    redirect_uri=redirect_uri,
                    state=state,
                    code_challenge=code_challenge,
                    code_challenge_method=code_challenge_method,
                    scope=scope,
                    error=f"Too many failed attempts. Try again in {lock_remaining}s.",
                ),
                status_code=429,
                headers={"Retry-After": str(lock_remaining)},
            )

        # Validar password con compare_digest (timing-safe)
        password_valid = secrets.compare_digest(
            password.encode("utf-8"),
            self._auth_password.encode("utf-8"),
        )

        if not password_valid:
            # Registrar el fallo para el backoff; mensaje genérico
            await self._record_login_failure(now)
            logger.warning(
                "oauth_auth_failed",
                client_id=client_id,
                src_ip=request.client.host if request.client else "unknown",
            )
            return HTMLResponse(
                self._login_html(
                    client_id=client_id,
                    redirect_uri=redirect_uri,
                    state=state,
                    code_challenge=code_challenge,
                    code_challenge_method=code_challenge_method,
                    scope=scope,
                    error="Authentication failed. Please try again.",
                ),
                status_code=200,
            )

        # Password correcta: resetear el throttle de fuerza bruta
        await self._reset_login_throttle()

        # Validar cliente. El formato se comprueba ANTES de construir la ruta:
        # como guarda explícita y no como expresión condicional, para que se lea
        # en el mismo orden en que se ejecuta.
        if not _is_valid_client_id(client_id):
            client_data = None
        else:
            client_data = _safe_read(_CLIENTS_DIR / f"{client_id}.json")
        if not client_data:
            return HTMLResponse(
                self._login_html(
                    client_id=client_id,
                    redirect_uri=redirect_uri,
                    state=state,
                    code_challenge=code_challenge,
                    code_challenge_method=code_challenge_method,
                    scope=scope,
                    error="Authentication failed. Please try again.",
                ),
                status_code=200,
            )

        # Validar redirect_uri
        if redirect_uri not in client_data.get("redirect_uris", []):
            return HTMLResponse(
                self._login_html(
                    client_id=client_id,
                    redirect_uri=redirect_uri,
                    state=state,
                    code_challenge=code_challenge,
                    code_challenge_method=code_challenge_method,
                    scope=scope,
                    error="Authentication failed. Please try again.",
                ),
                status_code=200,
            )

        # PKCE obligatorio
        if not code_challenge or code_challenge_method != "S256":
            return JSONResponse(
                {"error": "invalid_request",
                 "error_description": "PKCE with S256 is required"},
                status_code=400,
            )

        # Generar authorization code
        code = secrets.token_urlsafe(32)
        code_data = {
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "scope": scope,
            "sub": _FIXED_SUB,
            "expires_at": time.time() + AUTH_CODE_TTL,
        }

        _atomic_write(_CODES_DIR / f"{_hash_token(code)}.json", code_data)

        # Redirect con code y state
        params = {"code": code}
        if state:
            params["state"] = state

        redirect_url = f"{redirect_uri}?{urlencode(params)}"
        logger.info("oauth_code_issued", client_id=client_id)
        return RedirectResponse(redirect_url, status_code=302)

    # ── Token endpoint ────────────────────────────────────────

    @staticmethod
    def _token_error(error: str, reason: str, grant: str, client_id: str = "") -> JSONResponse:
        """Respuesta de error del token endpoint, con el motivo en el log.

        Al cliente solo le llega el `error` genérico de RFC 6749; el motivo
        concreto va al log. Sin esto, un refresh fallido (que obliga a
        Claude a rehacer el login) solo deja `POST /oauth/token 400` en el
        log del add-on, sin forma de saber por qué. Nunca se loguean tokens.
        """
        logger.warning(
            "oauth_token_rejected",
            grant=grant,
            reason=reason,
            client_id=client_id or None,
        )
        return JSONResponse({"error": error}, status_code=400)

    async def token(self, request: Request) -> JSONResponse:
        """POST /oauth/token — exchange code for tokens or refresh."""
        try:
            form = await request.form()
            grant_type = str(form.get("grant_type", ""))
        except Exception:
            return self._token_error("invalid_request", "unreadable_form", "")

        if grant_type == "authorization_code":
            return await self._token_auth_code(form)
        elif grant_type == "refresh_token":
            return await self._token_refresh(form)
        else:
            return self._token_error(
                "unsupported_grant_type", "unsupported_grant_type", grant_type
            )

    async def _token_auth_code(self, form: Any) -> JSONResponse:
        """Exchange authorization code for access + refresh tokens."""
        code = str(form.get("code", ""))
        client_id = str(form.get("client_id", ""))
        redirect_uri = str(form.get("redirect_uri", ""))
        code_verifier = str(form.get("code_verifier", ""))

        grant = "authorization_code"
        if not code or not client_id or not code_verifier:
            return self._token_error("invalid_request", "missing_parameters", grant, client_id)

        # Buscar y validar code
        code_hash = _hash_token(code)
        code_path = _CODES_DIR / f"{code_hash}.json"
        code_data = _safe_read(code_path)

        if not code_data:
            # Desconocido, ya canjeado (single-use) o purgado por expiración.
            return self._token_error("invalid_grant", "unknown_or_used_code", grant, client_id)

        # Verificar expiración
        if time.time() > code_data.get("expires_at", 0):
            _safe_unlink(code_path)
            return self._token_error("invalid_grant", "code_expired", grant, client_id)

        # Verificar client_id y redirect_uri
        if code_data.get("client_id") != client_id:
            _safe_unlink(code_path)
            return self._token_error("invalid_grant", "client_id_mismatch", grant, client_id)
        if redirect_uri and code_data.get("redirect_uri") != redirect_uri:
            _safe_unlink(code_path)
            return self._token_error("invalid_grant", "redirect_uri_mismatch", grant, client_id)

        # Invalidar code ANTES de verificar PKCE (single-use enforcement).
        # Si PKCE falla, el code ya no existe — no se puede reintentar.
        _safe_unlink(code_path)

        # Verificar PKCE (S256)
        challenge = code_data.get("code_challenge", "")
        expected = urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")

        if not secrets.compare_digest(challenge, expected):
            return self._token_error("invalid_grant", "pkce_verification_failed", grant, client_id)

        # Generar tokens
        access_token = _generate_token()
        refresh_token = _generate_token()
        now = time.time()

        # Almacenar access token
        _atomic_write(_TOKENS_DIR / f"{_hash_token(access_token)}.json", {
            "token_hash": _hash_token(access_token),
            "token_type": "access",
            "client_id": client_id,
            "sub": _FIXED_SUB,
            "scope": code_data.get("scope", "mcp"),
            "created_at": now,
            "expires_at": now + ACCESS_TOKEN_TTL,
        })

        # Almacenar refresh token
        _atomic_write(_TOKENS_DIR / f"{_hash_token(refresh_token)}.json", {
            "token_hash": _hash_token(refresh_token),
            "token_type": "refresh",
            "client_id": client_id,
            "sub": _FIXED_SUB,
            "scope": code_data.get("scope", "mcp"),
            "created_at": now,
            "expires_at": now + REFRESH_TOKEN_TTL,
            "access_token_hash": _hash_token(access_token),
        })

        # Una autorización nueva jubila las anteriores: sin esto cada login
        # dejaría otro refresh token vivo sus 7 días. El criterio exacto (mismo
        # client_id, más un tope global de sesiones) está en el docstring de
        # `_revoke_previous_sessions`.
        jubilados = _revoke_previous_sessions(client_id, _hash_token(refresh_token))
        if jubilados:
            logger.info(
                "oauth_previous_sessions_revoked",
                client_id=client_id,
                revoked=jubilados,
            )

        logger.info("oauth_tokens_issued", client_id=client_id, grant="authorization_code")

        return JSONResponse({
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_TTL,
            "refresh_token": refresh_token,
            "scope": code_data.get("scope", "mcp"),
        })

    async def _token_refresh(self, form: Any) -> JSONResponse:
        """Refresh an access token, rotando el refresh token."""
        refresh_token = str(form.get("refresh_token", ""))
        client_id = str(form.get("client_id", ""))

        grant = "refresh_token"
        if not refresh_token:
            return self._token_error("invalid_request", "missing_refresh_token", grant, client_id)

        token_hash = _hash_token(refresh_token)
        token_path = _TOKENS_DIR / f"{token_hash}.json"
        token_data = _safe_read(token_path)

        if not token_data:
            # Desconocido, revocado o purgado (p. ej. al expirar, 7 días).
            return self._token_error("invalid_grant", "unknown_refresh_token", grant, client_id)

        tipo = token_data.get("token_type")

        if tipo == "refresh_rotated":
            # Ya se canjeó. Dentro de la ventana de gracia se asume reintento
            # honesto —la respuesta anterior pudo perderse— y se reenvía el
            # sucesor vigente. Fuera de ella, hay dos copias del mismo token en
            # circulación: se revoca la cadena entera.
            rotado_hace = time.time() - float(token_data.get("rotated_at", 0) or 0)
            sucesor_hash = token_data.get("successor_hash", "")
            sucesor = _safe_read(_TOKENS_DIR / f"{sucesor_hash}.json") if sucesor_hash else None
            if rotado_hace <= REFRESH_ROTATION_GRACE_SECONDS and sucesor:
                logger.info(
                    "oauth_refresh_replay_within_grace",
                    client_id=token_data.get("client_id"),
                    seconds_since_rotation=round(rotado_hace, 1),
                )
                return self._issue_from_refresh(sucesor, sucesor_hash, rotate=False)

            revocados = _revoke_token_chain(token_hash)
            logger.warning(
                "oauth_refresh_reuse_detected",
                client_id=token_data.get("client_id"),
                seconds_since_rotation=round(rotado_hace, 1),
                revoked=revocados,
                reason="refresh_token_replayed",
            )
            return self._token_error("invalid_grant", "refresh_token_reused", grant, client_id)

        if tipo != "refresh":
            return self._token_error("invalid_grant", "unknown_refresh_token", grant, client_id)

        if time.time() > token_data.get("expires_at", 0):
            _safe_unlink(token_path)
            return self._token_error("invalid_grant", "refresh_token_expired", grant, client_id)

        if client_id and token_data.get("client_id") != client_id:
            return self._token_error("invalid_grant", "client_id_mismatch", grant, client_id)

        return self._issue_from_refresh(token_data, token_hash, rotate=True)

    def _issue_from_refresh(
        self,
        token_data: dict[str, Any],
        token_hash: str,
        *,
        rotate: bool,
    ) -> JSONResponse:
        """Emite un access token nuevo a partir de un refresh token válido.

        Con `rotate`, entrega además un refresh token nuevo y marca el anterior
        como canjeado. Sin él (reintento dentro de la gracia) reutiliza el que
        ya está vigente, para que un reintento no encadene rotaciones.
        """
        now = time.time()

        # Revocar el access token anterior: solo debe haber uno vivo.
        anterior = token_data.get("access_token_hash", "")
        if anterior:
            _safe_unlink(_TOKENS_DIR / f"{anterior}.json")

        nuevo_access = _generate_token()
        _atomic_write(_TOKENS_DIR / f"{_hash_token(nuevo_access)}.json", {
            "token_hash": _hash_token(nuevo_access),
            "token_type": "access",
            "client_id": token_data.get("client_id", ""),
            "sub": _FIXED_SUB,
            "scope": token_data.get("scope", "mcp"),
            "created_at": now,
            "expires_at": now + ACCESS_TOKEN_TTL,
        })

        respuesta: dict[str, Any] = {
            "token_type": "bearer",
            "access_token": nuevo_access,
            "expires_in": ACCESS_TOKEN_TTL,
            "scope": token_data.get("scope", "mcp"),
        }

        if not rotate:
            token_data["access_token_hash"] = _hash_token(nuevo_access)
            _atomic_write(_TOKENS_DIR / f"{token_hash}.json", token_data)
            return JSONResponse(respuesta)

        nuevo_refresh = _generate_token()
        nuevo_hash = _hash_token(nuevo_refresh)
        # La caducidad NO se estira al rotar: sigue siendo la de la
        # autorización original. Si se estirara, una sesión no terminaría nunca
        # y un token robado se renovaría solo indefinidamente.
        _atomic_write(_TOKENS_DIR / f"{nuevo_hash}.json", {
            "token_hash": nuevo_hash,
            "token_type": "refresh",
            "client_id": token_data.get("client_id", ""),
            "sub": _FIXED_SUB,
            "scope": token_data.get("scope", "mcp"),
            "created_at": now,
            "expires_at": token_data.get("expires_at", now + REFRESH_TOKEN_TTL),
            "access_token_hash": _hash_token(nuevo_access),
        })

        # El anterior queda como canjeado, no borrado: hace falta conservarlo
        # para poder DETECTAR que alguien lo reutiliza. Caduca cuando le tocaba.
        token_data["token_type"] = "refresh_rotated"
        token_data["rotated_at"] = now
        token_data["successor_hash"] = nuevo_hash
        token_data.pop("access_token_hash", None)
        _atomic_write(_TOKENS_DIR / f"{token_hash}.json", token_data)

        respuesta["refresh_token"] = nuevo_refresh
        logger.info("oauth_token_refreshed", client_id=token_data.get("client_id"), rotated=True)
        return JSONResponse(respuesta)

    # ── Revocation (RFC 7009) ─────────────────────────────────

    async def revoke(self, request: Request) -> JSONResponse:
        """POST /oauth/revoke — revoca un token."""
        try:
            form = await request.form()
            token_value = str(form.get("token", ""))
        except Exception:
            return JSONResponse({"error": "invalid_request"}, status_code=400)

        if not token_value:
            # RFC 7009: revocación de token desconocido → 200
            return JSONResponse({}, status_code=200)

        token_hash = _hash_token(token_value)
        token_path = _TOKENS_DIR / f"{token_hash}.json"
        token_data = _safe_read(token_path)

        if token_data:
            # Si es refresh, también revocar su access token
            if token_data.get("token_type") == "refresh":
                access_hash = token_data.get("access_token_hash", "")
                if access_hash:
                    _safe_unlink(_TOKENS_DIR / f"{access_hash}.json")
            _safe_unlink(token_path)
            logger.info("oauth_token_revoked",
                        token_type=token_data.get("token_type", "unknown"))

        # RFC 7009: siempre 200, incluso si el token no existía
        return JSONResponse({}, status_code=200)

    # ── Validación de tokens (usado por el middleware) ─────────

    async def validate_token(self, token_value: str) -> bool:
        """Valida un access token. True si es válido y no ha expirado.

        La lectura de disco se hace en un thread para no bloquear el event
        loop: validate_token se invoca en CADA request autenticada.
        """
        token_hash = _hash_token(token_value)
        token_path = _TOKENS_DIR / f"{token_hash}.json"
        token_data = await asyncio.to_thread(_safe_read, token_path)

        if not token_data:
            return False
        if token_data.get("token_type") != "access":
            return False
        if time.time() > token_data.get("expires_at", 0):
            await asyncio.to_thread(_safe_unlink, token_path)
            return False

        return True

    # ── Throttle anti-fuerza-bruta del login ──────────────────

    async def _login_lock_remaining(self, now: float) -> int:
        """Segundos restantes de bloqueo del login, o 0 si no está bloqueado."""
        async with self._login_lock:
            if now < self._login_locked_until:
                return int(self._login_locked_until - now) + 1
        return 0

    async def _record_login_failure(self, now: float) -> None:
        """Registra un fallo de password y aplica backoff exponencial global."""
        async with self._login_lock:
            if now - self._login_first_fail_ts > LOGIN_FAIL_WINDOW:
                self._login_failed_attempts = 0
                self._login_first_fail_ts = now
            self._login_failed_attempts += 1
            if self._login_failed_attempts >= LOGIN_FAIL_THRESHOLD:
                over = self._login_failed_attempts - LOGIN_FAIL_THRESHOLD
                lock = min(
                    LOGIN_LOCK_BASE_SECONDS * (2 ** over),
                    LOGIN_LOCK_MAX_SECONDS,
                )
                self._login_locked_until = now + lock
                logger.warning(
                    "oauth_login_locked",
                    failed_attempts=self._login_failed_attempts,
                    lock_seconds=lock,
                )

    async def _reset_login_throttle(self) -> None:
        """Resetea el throttle tras un login con password correcta."""
        async with self._login_lock:
            self._login_failed_attempts = 0
            self._login_locked_until = 0.0
            self._login_first_fail_ts = 0.0

    # ── HTML del login ────────────────────────────────────────

    def _login_html(
        self,
        client_id: str,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        code_challenge_method: str,
        scope: str,
        error: str,
    ) -> str:
        """Genera el HTML inline del formulario de login.

        SEGURIDAD: todos los valores interpolados pasan por html.escape(quote=True)
        para prevenir XSS vía DCR malicioso (ej. redirect_uri con "><script>…).
        """
        # Escapar TODOS los valores que se interpolan en el HTML
        e_client_id = html.escape(client_id, quote=True)
        e_redirect_uri = html.escape(redirect_uri, quote=True)
        e_state = html.escape(state, quote=True)
        e_code_challenge = html.escape(code_challenge, quote=True)
        e_code_challenge_method = html.escape(code_challenge_method, quote=True)
        e_scope = html.escape(scope, quote=True)
        e_error = html.escape(error, quote=True) if error else ""

        # BLOQUE DE CONSENTIMIENTO
        # Como `/oauth/register` es público —lo exige RFC 7591— y quien se
        # registra aporta su propio `redirect_uri`, cualquiera puede registrar
        # un cliente, mandar el enlace de autorización al dueño y recibir el
        # código: dominio real, TLS real, página de login auténtica. Y el
        # hostname público no es un secreto.
        #
        # Mostrar el nombre registrado y el destino convierte un "Autorizar" a
        # ciegas en una decisión informada, que es la única defensa real contra
        # esto: la lista de redirects la escribe el propio cliente, así que
        # validarla contra sí misma no aporta nada.
        client_label = ""
        if client_id and _is_valid_client_id(client_id):
            registered = _safe_read(_CLIENTS_DIR / f"{client_id}.json") or {}
            client_label = str(registered.get("client_name") or "")
        e_client_label = html.escape(client_label or "cliente sin nombre", quote=True)

        destination = redirect_uri
        try:
            from urllib.parse import urlsplit

            parts = urlsplit(redirect_uri)
            if parts.scheme and parts.netloc:
                destination = f"{parts.scheme}://{parts.netloc}"
        except ValueError:
            pass
        e_destination = html.escape(destination or "(sin destino)", quote=True)

        consent_html = (
            '<div class="consent">'
            f'<span class="who">{e_client_label}</span> solicita acceso completo a '
            "tu Home Assistant.<br>El código de autorización se enviará a "
            f'<span class="dest">{e_destination}</span>.'
            '<span class="warn">Si no reconoces ese destino, no continúes: '
            "quien lo reciba podrá controlar tu instalación.</span>"
            "</div>"
        )
        e_version = html.escape(__version__, quote=True)

        error_html = ""
        if e_error:
            error_html = f'<div class="error">{e_error}</div>'

        return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hermes — Iniciar sesión</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #e0e0e0;
  }}
.card {{
    background: rgba(255,255,255,0.07);
    backdrop-filter: blur(20px);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 16px;
    padding: 40px;
    max-width: 400px;
    width: 100%;
    box-shadow: 0 8px 32px rgba(0,0,0,0.3);
  }}
  h1 {{
    font-size: 1.5rem;
    margin-bottom: 8px;
    background: linear-gradient(90deg, #00d2ff, #3a7bd5);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }}
  p {{ font-size: 0.9rem; color: #aaa; margin-bottom: 24px; }}
  label {{ display: block; font-size: 0.85rem; margin-bottom: 6px; color: #ccc; }}
  input[type="password"] {{
    width: 100%;
    padding: 12px 16px;
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 8px;
    background: rgba(0,0,0,0.3);
    color: #fff;
    font-size: 1rem;
    outline: none;
    transition: border-color 0.2s;
  }}
  input[type="password"]:focus {{
    border-color: #3a7bd5;
  }}
  button {{
    width: 100%;
    padding: 12px;
    margin-top: 20px;
    border: none;
    border-radius: 8px;
    background: linear-gradient(90deg, #00d2ff, #3a7bd5);
    color: #fff;
    font-size: 1rem;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.2s;
  }}
  button:hover {{ opacity: 0.9; }}
.error {{
    background: rgba(255,60,60,0.15);
    border: 1px solid rgba(255,60,60,0.3);
    border-radius: 8px;
    padding: 10px 14px;
    margin-bottom: 16px;
    font-size: 0.85rem;
    color: #ff6b6b;
  }}
.consent {{
    background: rgba(255,180,0,0.10);
    border: 1px solid rgba(255,180,0,0.35);
    border-radius: 8px;
    padding: 12px 14px;
    margin-bottom: 16px;
    font-size: 0.85rem;
    line-height: 1.5;
    text-align: left;
  }}
.consent .who {{ font-weight: 600; }}
.consent .dest {{ font-family: ui-monospace, monospace; word-break: break-all; }}
.consent .warn {{ display: block; margin-top: 8px; color: #ffb400; }}
.footer {{ text-align: center; margin-top: 16px; font-size: 0.75rem; color: #666; }}
</style>
</head>
<body>
<div class="card">
  <h1>⚡ Hermes</h1>
  <p>Autorizar acceso al servidor MCP de Home Assistant</p>
  {consent_html}
  {error_html}
  <form method="POST" action="/oauth/authorize">
    <input type="hidden" name="client_id" value="{e_client_id}">
    <input type="hidden" name="redirect_uri" value="{e_redirect_uri}">
    <input type="hidden" name="state" value="{e_state}">
    <input type="hidden" name="code_challenge" value="{e_code_challenge}">
    <input type="hidden" name="code_challenge_method" value="{e_code_challenge_method}">
    <input type="hidden" name="scope" value="{e_scope}">
    <label for="password">Contraseña del add-on</label>
    <input type="password" id="password" name="password" autofocus required
           placeholder="Introduce tu contraseña">
    <button type="submit">Autorizar</button>
  </form>
  <div class="footer">Hermes MCP v{e_version}</div>
</div>
</body>
</html>"""

    # ── Rutas Starlette ───────────────────────────────────────

    def get_routes(self) -> list[Route]:
        """Devuelve las rutas OAuth para montar en Starlette.

        Además de los paths canónicos bajo /oauth/, se sirven los mismos
        handlers en /register, /authorize, /token y /revoke: son los paths por
        defecto que la spec MCP (sección Authorization, fallback RFC 8414)
        obliga a usar al cliente cuando no consigue los metadatos del
        authorization server. Sin estos alias, un cliente en ese fallback
        recibe 401 de /register y da la conexión por fallida.
        """
        return [
            Route(
                "/.well-known/oauth-protected-resource",
                self.protected_resource_metadata,
                methods=["GET"],
            ),
            Route(
                "/.well-known/oauth-protected-resource/mcp",
                self.protected_resource_metadata,
                methods=["GET"],
            ),
            Route(
                "/.well-known/oauth-protected-resource/{path:path}",
                self.protected_resource_metadata,
                methods=["GET"],
            ),
            Route(
                "/.well-known/oauth-authorization-server",
                self.authorization_server_metadata,
                methods=["GET"],
            ),
            Route("/oauth/register", self.register_client, methods=["POST"]),
            Route(
                "/oauth/authorize",
                self.authorize_get,
                methods=["GET"],
            ),
            Route(
                "/oauth/authorize",
                self.authorize_post,
                methods=["POST"],
            ),
            Route("/oauth/token", self.token, methods=["POST"]),
            Route("/oauth/revoke", self.revoke, methods=["POST"]),
            # Alias en los paths por defecto de la spec MCP / RFC 8414.
            Route("/register", self.register_client, methods=["POST"]),
            Route("/authorize", self.authorize_get, methods=["GET"]),
            Route("/authorize", self.authorize_post, methods=["POST"]),
            Route("/token", self.token, methods=["POST"]),
            Route("/revoke", self.revoke, methods=["POST"]),
        ]
