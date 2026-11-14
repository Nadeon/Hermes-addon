"""Onboarding automático de la HA Core del banco de pruebas (spec 010, FR-003).

Deja una HA recién arrancada como una instalación real recién configurada y
devuelve un token de larga duración para hablar con ella. Los pasos y su forma
salen de `components/onboarding/views.py` y `components/auth/__init__.py` de
Core 2026.11.1 (research R-3):

1. esperar a que `GET /api/onboarding` responda 200 (vista sin auth);
2. `POST /api/onboarding/users` → `auth_code` (crea el usuario administrador,
   su persona y las áreas por defecto);
3. `POST /auth/token` con ese código → `access_token`;
4. `core_config`, `analytics` e `integration`, con el `access_token`. Se hacen
   los cuatro pasos porque FR-013 de la 008 pide completar el onboarding: con
   el primero bastaría para la API, pero entonces el banco probaría contra una
   HA que nadie tiene;
5. esperar a `GET /api/config` con `state: RUNNING`, porque el HTTP responde
   antes de que terminen de cargarse las integraciones;
6. pedir por WebSocket un token de larga duración. El de acceso caduca a los
   30 min y el job se puede acercar a ese tiempo.

Credenciales (FR-003, FR-012): usuario, contraseña y tokens se generan aquí
con `secrets` y solo viven en memoria. Nunca se imprimen ni se registran: el
log dice el paso y el código HTTP, y los errores, lo mismo; jamás un cuerpo.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from typing import Callable

import aiohttp
import structlog

logger = structlog.get_logger("hermes.banco.onboarding")

# Topes por defecto (FR-011). Están solo aquí y en el job.
TIMEOUT_HTTP = 300.0
TIMEOUT_RUNNING = 180.0
INTERVALO = 2.0


class BancoNoDisponible(Exception):
    """La HA del banco no quedó lista. Dice el paso y el estado, nada más."""

    def __init__(self, paso: str, estado: object) -> None:
        self.paso = paso
        self.estado = estado
        super().__init__(f"onboarding: paso {paso} devolvió {estado}")


@dataclass(frozen=True)
class CredencialesCore:
    """Lo que el banco necesita de Core. El token no sale en `repr`."""

    token_core: str = field(repr=False)
    version_core: str

    def __str__(self) -> str:
        return repr(self)


def _paso_ok(paso: str, estado: int) -> None:
    logger.info("banco_onboarding_paso", paso=paso, estado=estado)


async def _esperar_http(
    session: aiohttp.ClientSession, core_url: str, timeout: float, intervalo: float
) -> None:
    bucle = asyncio.get_running_loop()
    limite = bucle.time() + timeout
    ultimo: object = "sin respuesta"
    while True:
        try:
            async with session.get(
                f"{core_url}/api/onboarding", timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    _paso_ok("espera_http", resp.status)
                    return
                ultimo = resp.status
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            ultimo = f"sin respuesta ({type(exc).__name__})"
        if bucle.time() + intervalo > limite:
            raise BancoNoDisponible("espera_http", f"{ultimo} tras {timeout:g} s")
        await asyncio.sleep(intervalo)


async def _post(
    session: aiohttp.ClientSession,
    paso: str,
    url: str,
    *,
    json: object | None = None,
    data: dict[str, str] | None = None,
    token: str | None = None,
) -> dict:
    cabeceras = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with session.post(url, json=json, data=data, headers=cabeceras) as resp:
            if resp.status != 200:
                # Solo el código: el cuerpo de un error de Core puede repetir
                # lo que se le mandó, y aquí se le manda la contraseña.
                raise BancoNoDisponible(paso, resp.status)
            cuerpo = await resp.json()
    except aiohttp.ClientError as exc:
        raise BancoNoDisponible(paso, type(exc).__name__) from None
    _paso_ok(paso, 200)
    return cuerpo if isinstance(cuerpo, dict) else {}


async def _esperar_running(
    session: aiohttp.ClientSession, core_url: str, token: str, timeout: float, intervalo: float
) -> str:
    bucle = asyncio.get_running_loop()
    limite = bucle.time() + timeout
    ultimo: object = "sin respuesta"
    while True:
        try:
            async with session.get(
                f"{core_url}/api/config",
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    config = await resp.json()
                    ultimo = config.get("state")
                    if ultimo == "RUNNING":
                        _paso_ok("running", resp.status)
                        return str(config.get("version", ""))
                else:
                    ultimo = resp.status
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            ultimo = f"sin respuesta ({type(exc).__name__})"
        if bucle.time() + intervalo > limite:
            raise BancoNoDisponible("running", f"{ultimo} tras {timeout:g} s")
        await asyncio.sleep(intervalo)


async def _token_larga_duracion(
    session: aiohttp.ClientSession, core_url: str, token: str
) -> str:
    ws_url = core_url.replace("http://", "ws://").replace("https://", "wss://")
    try:
        async with session.ws_connect(f"{ws_url}/api/websocket") as ws:
            inicio = await ws.receive_json(timeout=10)
            if inicio.get("type") != "auth_required":
                raise BancoNoDisponible("long_lived", inicio.get("type"))
            await ws.send_json({"type": "auth", "access_token": token})
            auth = await ws.receive_json(timeout=10)
            if auth.get("type") != "auth_ok":
                raise BancoNoDisponible("long_lived", auth.get("type"))
            await ws.send_json(
                {
                    "id": 1,
                    "type": "auth/long_lived_access_token",
                    "client_name": "hermes-banco",
                    # Un día: el contenedor muere mucho antes.
                    "lifespan": 1,
                }
            )
            resultado = await ws.receive_json(timeout=10)
    except (aiohttp.ClientError, asyncio.TimeoutError, TypeError, ValueError) as exc:
        raise BancoNoDisponible("long_lived", type(exc).__name__) from None
    if not resultado.get("success") or not isinstance(resultado.get("result"), str):
        codigo = (resultado.get("error") or {}).get("code", "sin resultado")
        raise BancoNoDisponible("long_lived", codigo)
    _paso_ok("long_lived", 200)
    return resultado["result"]


async def preparar_core(
    core_url: str,
    *,
    timeout_http: float = TIMEOUT_HTTP,
    timeout_running: float = TIMEOUT_RUNNING,
    intervalo: float = INTERVALO,
    anotar_secreto: Callable[[str], None] | None = None,
) -> CredencialesCore:
    """Completa el onboarding y devuelve el token de larga duración.

    Lanza `BancoNoDisponible(paso, estado)` en cuanto algo falla. No reintenta
    los pasos: un segundo intento daría 403 «already done» y escondería el
    primer error.

    `anotar_secreto` recibe cada credencial en cuanto existe (usuario,
    contraseña, código, token de acceso y de larga duración). Solo lo usa el
    entorno del banco para comprobar, sobre el onboarding real, que ninguna
    acaba en el log (FR-012); no las guarda en ningún otro sitio.
    """
    anotar = anotar_secreto or (lambda _secreto: None)
    core_url = core_url.rstrip("/")
    # indieauth exige que `client_id` y `redirect_uri` tengan el mismo esquema
    # y netloc, y que el host sea el de la petición: la URL base con barra
    # final, como la manda el frontend de HA.
    client_id = f"{core_url}/"
    redirect_uri = f"{client_id}?auth_callback=1"

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        await _esperar_http(session, core_url, timeout_http, intervalo)

        # Core exige el usuario en minúsculas y sin espacios: hex.
        usuario = f"banco{secrets.token_hex(6)}"
        contrasena = secrets.token_urlsafe(24)
        anotar(usuario)
        anotar(contrasena)
        alta = await _post(
            session,
            "users",
            f"{core_url}/api/onboarding/users",
            json={
                "client_id": client_id,
                "name": "Banco",
                "username": usuario,
                "password": contrasena,
                "language": "en",
            },
        )
        del usuario, contrasena
        codigo = alta.get("auth_code")
        if not isinstance(codigo, str):
            raise BancoNoDisponible("users", "sin auth_code")
        anotar(codigo)

        tokens = await _post(
            session,
            "token",
            f"{core_url}/auth/token",
            data={"grant_type": "authorization_code", "code": codigo, "client_id": client_id},
        )
        acceso = tokens.get("access_token")
        if not isinstance(acceso, str):
            raise BancoNoDisponible("token", "sin access_token")
        anotar(acceso)

        await _post(session, "core_config", f"{core_url}/api/onboarding/core_config", token=acceso)
        await _post(session, "analytics", f"{core_url}/api/onboarding/analytics", token=acceso)
        await _post(
            session,
            "integration",
            f"{core_url}/api/onboarding/integration",
            json={"client_id": client_id, "redirect_uri": redirect_uri},
            token=acceso,
        )

        version = await _esperar_running(session, core_url, acceso, timeout_running, intervalo)
        token_core = await _token_larga_duracion(session, core_url, acceso)
        anotar(token_core)

    return CredencialesCore(token_core=token_core, version_core=version)
