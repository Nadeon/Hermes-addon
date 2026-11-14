"""Entorno del banco de pruebas de Core (spec 010, FR-005, FR-007).

Una sola instancia por proceso de tests: la primera vez que un test la pide se
completa el onboarding de la HA del banco y se levanta el Supervisor simulado;
las siguientes reciben el mismo objeto (o el mismo fallo, sin reintentar: un
segundo onboarding daría 403 «already done» y escondería el primer error).

La suite usa `unittest.IsolatedAsyncioTestCase`, que crea un bucle por test.
El simulado tiene que vivir más que un test, así que corre en un hilo con su
propio bucle (research R-11); cada test crea en su bucle su `HAClient`, su
servidor MCP y su lector, y hablan con el simulado por sockets reales.

Reglas de salto y fallo (data-model.md):

| HERMES_BANCO_HA_URL | HERMES_BANCO_OBLIGATORIO | Resultado              |
|---------------------|--------------------------|------------------------|
| ausente             | distinto de "1"          | salto con motivo       |
| ausente             | "1" (lo pone el job)     | fallo con el motivo    |
| presente            | cualquiera               | corre, o falla si HA no está lista; nunca salto |
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import json
import logging
import os
import secrets
import threading
import unittest
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator

import structlog
import structlog.testing
from aiohttp import web

from tests.banco import onboarding
from tests.banco.supervisor_simulado import arrancar

VAR_URL = "HERMES_BANCO_HA_URL"
VAR_OBLIGATORIO = "HERMES_BANCO_OBLIGATORIO"
MOTIVO_SIN_BANCO = (
    f"banco de Core no configurado: falta {VAR_URL}. Estos tests corren en el job "
    "`banco-core` del CI (ver specs/010-banco-de-pruebas-core/quickstart.md)"
)

# Topes del onboarding (FR-011). Los tests de la suite normal los bajan.
TIMEOUT_HTTP = onboarding.TIMEOUT_HTTP
TIMEOUT_RUNNING = onboarding.TIMEOUT_RUNNING
INTERVALO = onboarding.INTERVALO


@dataclass(frozen=True)
class EntornoBanco:
    """Lo que necesitan los tests del banco. Los tokens no salen en `repr`."""

    core_url: str
    supervisor_url: str
    token_addon: str = field(repr=False)
    token_core: str = field(repr=False)
    version_core: str

    def __str__(self) -> str:
        return repr(self)


def motivo_sin_banco() -> str | None:
    """Motivo para no correr el banco, o None si está configurado."""
    if os.environ.get(VAR_URL, "").strip():
        return None
    return MOTIVO_SIN_BANCO


def _obligatorio() -> bool:
    return os.environ.get(VAR_OBLIGATORIO, "").strip() == "1"


def exigir_banco() -> EntornoBanco:
    """Devuelve el entorno, o salta o falla según las reglas de arriba.

    Se llama en `setUpClass` (o en `setUp`): lanza `unittest.SkipTest` o
    `AssertionError`, que funcionan en los dos sitios.
    """
    motivo = motivo_sin_banco()
    if motivo is not None:
        if _obligatorio():
            # En el job, un salto escondería que el banco no ha corrido.
            raise AssertionError(motivo)
        raise unittest.SkipTest(motivo)
    return obtener_entorno()


# ── Instancia única por proceso ─────────────────────────────────────────────

_cerrojo = threading.Lock()
_entorno: EntornoBanco | None = None
_fallo: str | None = None
_bucle: asyncio.AbstractEventLoop | None = None
_hilo: threading.Thread | None = None
_runner: web.AppRunner | None = None
_parada_registrada = False


async def _crear(core_url: str, secretos: list[str]) -> EntornoBanco:
    global _runner
    cred = await onboarding.preparar_core(
        core_url,
        timeout_http=TIMEOUT_HTTP,
        timeout_running=TIMEOUT_RUNNING,
        intervalo=INTERVALO,
        anotar_secreto=secretos.append,
    )
    # El token que Hermes usa como SUPERVISOR_TOKEN: solo lo conoce el
    # simulado, como en producción.
    token_addon = secrets.token_urlsafe(32)
    secretos.append(token_addon)
    _runner, supervisor_url = await arrancar(
        core_url, token_addon, cred.token_core, cred.version_core
    )
    return EntornoBanco(
        core_url=core_url,
        supervisor_url=supervisor_url,
        token_addon=token_addon,
        token_core=cred.token_core,
        version_core=cred.version_core,
    )


def _arrancar_bucle() -> asyncio.AbstractEventLoop:
    global _bucle, _hilo
    if _bucle is None:
        _bucle = asyncio.new_event_loop()
        _hilo = threading.Thread(target=_bucle.run_forever, name="banco-core", daemon=True)
        _hilo.start()
    return _bucle


def obtener_entorno() -> EntornoBanco:
    """El entorno del banco; lo crea la primera vez. Falla, nunca salta."""
    global _entorno, _fallo, _parada_registrada
    with _cerrojo:
        if _entorno is not None:
            return _entorno
        if _fallo is not None:
            raise AssertionError(_fallo)
        motivo = motivo_sin_banco()
        if motivo is not None:
            raise AssertionError(motivo)

        core_url = os.environ[VAR_URL].strip().rstrip("/")
        bucle = _arrancar_bucle()
        if not _parada_registrada:
            atexit.register(_parar)
            _parada_registrada = True
        with _capturar_arranque() as secretos:
            futuro = asyncio.run_coroutine_threadsafe(_crear(core_url, secretos), bucle)
            try:
                _entorno = futuro.result(timeout=TIMEOUT_HTTP + TIMEOUT_RUNNING + 60)
                return _entorno
            except onboarding.BancoNoDisponible as exc:
                # El mensaje solo lleva el paso y el estado (FR-012).
                _fallo = f"banco de Core no disponible en {core_url}: {exc}"
            except concurrent.futures.TimeoutError:
                futuro.cancel()
                _fallo = f"banco de Core no disponible en {core_url}: tiempo agotado"
            except Exception as exc:  # noqa: BLE001 — cualquier otra cosa también es un fallo
                _fallo = f"banco de Core no disponible en {core_url}: {type(exc).__name__}"
            except BaseException as exc:
                # El tope por test de pytest-timeout (y un Ctrl+C) no son
                # `Exception`: cortan la espera del onboarding en el primer
                # test. Sin fijar `_fallo` aquí, el test siguiente repetiría
                # el onboarding y recibiría 403 «already done», que esconde
                # la causa real (Core lento). Se anota y se deja pasar.
                futuro.cancel()
                _fallo = (
                    f"banco de Core no disponible en {core_url}: la espera del onboarding "
                    f"se cortó con {type(exc).__name__} (¿el tope por test de pytest?)"
                )
                raise
        raise AssertionError(_fallo)


# ── Log del arranque (FR-012) ───────────────────────────────────────────────


@dataclass(frozen=True)
class RegistroDelArranque:
    """Lo que se registró mientras se creaba el entorno, y los secretos de
    entonces (usuario, contraseña, código, token de acceso, token de larga
    duración y token de add-on). Solo vive en memoria y no sale en `repr`."""

    log: str = field(repr=False)
    secretos: tuple[str, ...] = field(repr=False)
    eventos: int


_arranque: RegistroDelArranque | None = None


def registro_del_arranque() -> RegistroDelArranque | None:
    """El registro del onboarding de este proceso; None si no se ha hecho."""
    return _arranque


class _Lista(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
        self.lineas: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lineas.append(self.format(record))


@contextmanager
def _capturar_arranque() -> Iterator[list[str]]:
    """Captura el log (stdlib y structlog, a nivel DEBUG) mientras se crea el
    entorno, junto con los secretos que se generan o se reciben.

    El onboarding pasa una sola vez por proceso y antes del primer test, así
    que el test de FR-012 del banco no puede capturarlo por su cuenta: lo
    captura aquí y el test lo lee con `registro_del_arranque()`.
    """
    global _arranque
    secretos: list[str] = []
    raiz = logging.getLogger()
    nivel = raiz.level
    lista = _Lista()
    raiz.addHandler(lista)
    raiz.setLevel(logging.DEBUG)
    try:
        with structlog.testing.capture_logs() as eventos:
            yield secretos
    finally:
        raiz.removeHandler(lista)
        raiz.setLevel(nivel)
        _arranque = RegistroDelArranque(
            log="\n".join(lista.lineas) + "\n" + repr(eventos),
            secretos=tuple(secretos),
            eventos=len(eventos),
        )


def _parar() -> None:
    """Para el simulado y el hilo del bucle. Lo registra `atexit`."""
    global _bucle, _hilo, _runner
    if _bucle is None:
        return
    if _runner is not None:
        try:
            asyncio.run_coroutine_threadsafe(_runner.cleanup(), _bucle).result(timeout=10)
        except Exception:  # noqa: BLE001 — al salir no hay nada más que hacer
            pass
        _runner = None
    _bucle.call_soon_threadsafe(_bucle.stop)
    if _hilo is not None:
        _hilo.join(timeout=10)
    if not _bucle.is_running():
        _bucle.close()
    _bucle = None
    _hilo = None


def _reiniciar() -> None:
    """Solo para los tests de este módulo: vuelve al estado `sin_crear`."""
    global _entorno, _fallo, _arranque
    with _cerrojo:
        _parar()
        _entorno = None
        _fallo = None
        _arranque = None


# ── Hermes conectado como en producción ─────────────────────────────────────


@dataclass
class HermesConectado:
    ha_client: Any
    cliente: Any


@asynccontextmanager
async def hermes_conectado(entorno: EntornoBanco) -> AsyncIterator[HermesConectado]:
    """Hermes conectado a la HA del banco por el Supervisor simulado (FR-005).

    `HAClient` con la URL del Supervisor y el token de add-on, como en el
    add-on; las tools, con el cableado de producción (`_build_mcp` con la
    configuración por defecto) y un cliente MCP en memoria.
    """
    from mcp import Client

    from hermes.__main__ import _build_mcp
    from hermes.config import HermesConfig
    from hermes.ha import HAClient
    from hermes.health import HealthServer

    ha_client = HAClient(entorno.supervisor_url, entorno.token_addon, HealthServer())
    try:
        await ha_client.start(timeout_seconds=30)
        mcp = _build_mcp(HermesConfig(), ha_client)
        async with Client(mcp) as cliente:
            yield HermesConectado(ha_client=ha_client, cliente=cliente)
    finally:
        await ha_client.stop()


def _decodificar_texto(texto: str) -> Any:
    try:
        return json.loads(texto)
    except ValueError:
        return texto


def _decodificar(resultado: Any) -> Any:
    # Una tool que devuelve una lista sale como un bloque por elemento (una
    # llamada a servicio devuelve los estados cambiados, a menudo ninguno): se
    # reconstruye la lista en vez de quedarse con el primer bloque.
    bloques = [_decodificar_texto(c.text) for c in resultado.content]
    if len(bloques) == 1:
        return bloques[0]
    return bloques


async def llamar(cliente: Any, tool: str, **args: Any) -> Any:
    """Llama a una tool por MCP y devuelve su respuesta decodificada.

    Una excepción dentro de la tool llega como resultado con `is_error`; se
    convierte en fallo del test (si no, el texto del error pasaría por una
    respuesta normal y el test fallaría después, lejos de la causa).
    """
    resultado = await cliente.call_tool(tool, args)
    if getattr(resultado, "is_error", False):
        textos = " ".join(getattr(c, "text", "") for c in resultado.content)
        raise AssertionError(f"{tool}: la tool falló: {textos}")
    return _decodificar(resultado)


async def confirmar(cliente: Any, tool: str, respuesta: dict[str, Any], **args: Any) -> Any:
    """Segundo paso: la misma llamada con el `confirmation_token` de la vista previa."""
    token = respuesta.get("confirmation_token")
    if not isinstance(token, str):
        raise AssertionError(f"{tool}: la vista previa no trae confirmation_token")
    return await llamar(cliente, tool, **args, confirmation_token=token)
