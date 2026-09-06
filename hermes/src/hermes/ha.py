"""Hermes — Cliente del core de Home Assistant y del Supervisor.

Este módulo encapsula el acceso a los endpoints REST de Home Assistant
via Supervisor y mantiene una conexión WebSocket para suscripciones de
estado en tiempo real.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from typing import Any

import aiohttp
from aiohttp import ClientWSTimeout
import structlog
from aiohttp import ClientResponse, ClientSession, ClientTimeout, WSMsgType

from hermes.service_policy import (
    CALL_SERVICE_DENYLIST,
    DangerousServiceError,
    is_in_denylist,
)
from hermes.health import HealthServer
from hermes.identifiers import validate_path_segment
from urllib.parse import unquote

logger = structlog.get_logger(__name__)


class HAConnectionError(RuntimeError):
    """Error general de conexión a Home Assistant."""


# Sentinel para señalizar reconexión/cierre de WS a los waiter de eventos
_WS_CLOSED_SENTINEL = object()

# Caracteres de control: su presencia en un path permite CRLF / request splitting.
_UNSAFE_PATH_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def _assert_safe_request_path(path: str) -> None:
    """Defensa central anti path-injection en URLs hacia HA core / Supervisor.

    Los segmentos variables (slug, entry_id, domain, config_id…) provienen del
    cliente MCP y se interpolan en f-strings de path. Esta comprobación
    garantiza que nunca puedan escapar del endpoint previsto, aunque una tool
    olvide validar su input:

    - el path debe empezar por '/'
    - sin segmentos de traversal ('..'), **ni codificados**
    - sin caracteres de control (evita CRLF / HTTP request splitting)
    - sin '%', '#' ni '?' (ver más abajo)

    Es la segunda capa de defensa; la primera son los validadores de
    hermes.tools._validation aplicados en cada tool.

    POR QUÉ SE RECHAZA EL PORCENTAJE
    --------------------------------
    Comparar los segmentos con '..' no basta, porque yarl —dentro de aiohttp—
    decodifica `%2e%2e` a `..` y normaliza el path DESPUÉS de esta validación:

        URL("http://supervisor/core/api"
            + "/services/%2e%2e/%2e%2e/%2e%2e/host/reboot").raw_path
            -> "/host/reboot"

    Como el add-on corre con `hassio_role: admin`, un path así alcanzaría
    CUALQUIER endpoint del Supervisor saltándose a la vez la denylist (el
    "domain.service" compuesto no casaría), los confirmation tokens de
    `sv_reboot_host` / `sv_uninstall_addon` / `sv_delete_backup` y la
    autoprotección de `local_hermes`.

    Hermes construye todos estos paths internamente y ninguno legítimo
    necesita '%', así que se prohíbe de plano: eso cierra también la próxima
    peculiaridad de codificación que aparezca, sin depender de acertar con la
    lista de secuencias peligrosas.

    '#' y '?' se rechazan por la razón simétrica: yarl los interpreta como
    inicio de fragmento y de query, lo que TRUNCA el path previsto
    (`/addons/local_hermes#/stop` acaba siendo `/addons/local_hermes`), y eso
    convierte una llamada en otra distinta.
    """
    if not isinstance(path, str) or not path.startswith("/"):
        raise HAConnectionError(
            f"Unsafe request path (must start with '/'): {path!r}"
        )
    if _UNSAFE_PATH_CHARS_RE.search(path):
        raise HAConnectionError(
            "Unsafe request path: control characters are not allowed"
        )
    for char, reason in (("%", "percent-encoding"), ("#", "fragment"), ("?", "query")):
        if char in path:
            raise HAConnectionError(
                f"Unsafe request path ({reason} not allowed): {path!r}"
            )

    # Cinturón y tirantes: aunque el '%' ya está prohibido, se decodifica en
    # bucle antes de buscar traversal. Si algún día hiciera falta permitir
    # porcentaje en un endpoint concreto, esta comprobación seguiría cerrada.
    decoded = path
    for _ in range(3):
        candidate = unquote(decoded)
        if candidate == decoded:
            break
        decoded = candidate

    for candidate in (path, decoded):
        segments = candidate.replace("\\", "/").split("/")
        if any(segment == ".." for segment in segments):
            raise HAConnectionError(
                f"Unsafe request path (path traversal): {path!r}"
            )


def _state_timestamp(state: Any) -> float | None:
    """Devuelve `last_updated` de un estado de HA como epoch, o None.

    HA marca cada estado con `last_updated` en ISO-8601 con zona horaria. Si
    falta o no se puede leer se devuelve None y el llamador decide; ante la
    duda se prefiere escribir a descartar.
    """
    if not isinstance(state, dict):
        return None
    marca = state.get("last_updated")
    if not isinstance(marca, str):
        return None
    try:
        return datetime.fromisoformat(marca).timestamp()
    except (ValueError, TypeError):
        return None


def _state_is_newer(candidato: Any, cacheado: Any) -> bool:
    """True si `candidato` debe sustituir a `cacheado` en la cache.

    La cache se alimenta de dos sitios —el snapshot REST y los eventos de la
    WebSocket— y nada garantiza que lleguen en orden. Como la suscripcion se
    hace ANTES de pedir el snapshot, los eventos de esa ventana se procesan
    DESPUES del snapshot aunque sean anteriores: sin esta comprobacion
    escribirian un valor viejo encima de uno nuevo.

    Sin marcas de tiempo utilizables se escribe.
    """
    t_nuevo = _state_timestamp(candidato)
    t_viejo = _state_timestamp(cacheado)
    if t_nuevo is None or t_viejo is None:
        return True
    return t_nuevo >= t_viejo


class HAClient:
    """Cliente de Home Assistant que usa Supervisor core API y WebSocket."""

    def __init__(
        self,
        supervisor_base_url: str,
        supervisor_token: str,
        health_server: HealthServer,
        ws_max_msg_size: int = 4_194_304,
    ) -> None:
        self._ws_max_msg_size = ws_max_msg_size
        self._supervisor_base_url = supervisor_base_url.rstrip("/")
        self._supervisor_token = supervisor_token
        self._rest_base_url = f"{self._supervisor_base_url}/core/api"
        self._ws_url = f"{self._supervisor_base_url.replace('http://', 'ws://').replace('https://', 'wss://')}/core/api/websocket"
        self._health_server = health_server
        self._session: ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._background_task: asyncio.Task[None] | None = None
        self._connected_event = asyncio.Event()
        self._state_cache: dict[str, Any] = {}
        self._cache_lock = asyncio.Lock()
        self._ws_request_lock = asyncio.Lock()
        self._next_ws_request_id = 1  # único contador para todos los mensajes WS
        self._pending_ws_responses: dict[int, asyncio.Future[Any]] = {}
        self._stop_event = asyncio.Event()
        # Suscripciones one-shot (render_template, etc.): request_id → Future[event_dict]
        self._pending_ws_subscriptions: dict[int, asyncio.Future[Any]] = {}
        # Subscripciones persistentes (wait_for_event): sub_id → asyncio.Queue
        self._event_subscription_queues: dict[int, asyncio.Queue] = {}
        # Generation counter: incrementa en cada reconexión WS
        self._reconnect_generation: int = 0

    async def start(self, timeout_seconds: int = 30) -> None:
        """Arranca la conexión WS en background y espera a que quede lista."""
        self._session = ClientSession(
            timeout=ClientTimeout(total=30),
            headers={"Authorization": f"Bearer {self._supervisor_token}"},
        )
        self._stop_event.clear()
        self._background_task = asyncio.create_task(
            self._run_background(),
            name="ha_ws_client",
        )

        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise HAConnectionError(
                "No se pudo conectar al WebSocket de Home Assistant en el tiempo permitido."
            ) from exc

    async def stop(self) -> None:
        """Detiene la conexión WS y cierra los recursos asociados."""
        self._stop_event.set()

        if self._background_task and not self._background_task.done():
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass

        if self._ws is not None and not self._ws.closed:
            await self._ws.close()

        if self._session is not None and not self._session.closed:
            await self._session.close()

    @property
    def ready(self) -> bool:
        return self._connected_event.is_set()

    async def wait_ready(self, timeout: float = 5.0) -> bool:
        """Espera hasta que la WS complete handshake. Devuelve True si listo."""
        if self._connected_event.is_set():
            return True
        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        return True

    async def get_states(self) -> list[dict[str, Any]]:
        """Devuelve el listado completo de estados de entidades."""
        if self.ready:
            async with self._cache_lock:
                return [json.loads(json.dumps(state)) for state in self._state_cache.values()]
        return await self._request_json("GET", "/states")

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        """Devuelve el estado de una entidad o None si no existe."""
        async with self._cache_lock:
            state = self._state_cache.get(entity_id)
            if state is not None:
                return json.loads(json.dumps(state))

        # El entity_id llega del cliente y acaba dentro de la ruta. La red de
        # seguridad de `_assert_safe_request_path` impide lo grave, pero no que
        # un valor con '/' aterrice en un endpoint vecino, y aquí sí se sabe
        # qué forma tiene el valor.
        validate_path_segment(entity_id, field="entity_id")
        return await self._request_json("GET", f"/states/{entity_id}")

    async def get_services(self) -> list[dict[str, Any]]:
        """Devuelve los servicios disponibles en Home Assistant."""
        return await self._request_json("GET", "/services")

    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
        *,
        allow_dangerous: bool = False,
    ) -> dict[str, Any]:
        """Llama un servicio de Home Assistant.

        `allow_dangerous` es False por defecto **a propósito**. Este método es
        la puerta de bajo nivel al endpoint REST de servicios y por él pasa
        todo el tráfico: decenas de llamadas repartidas por los módulos de
        tools llegan aquí sin pasar por la tool `ha_call_service`. Si la
        denylist viviera solo en esa tool, cualquiera de esos caminos
        indirectos —una tool que ejecute un script, por ejemplo— la eludiría
        sin gastar un solo confirmation token, así que la comprobación tiene
        que estar aquí, donde pasa todo.

        Quien necesite de verdad ejecutar un servicio vetado tiene que pedirlo
        explícitamente, y el único camino que lo hace es la tool
        `ha_call_service`, después de validar su `confirmation_token`.
        """
        if not allow_dangerous and is_in_denylist(
            domain.strip().lower(), service.strip().lower(), CALL_SERVICE_DENYLIST
        ):
            raise DangerousServiceError(
                f"El servicio {domain}.{service} exige confirmación explícita. "
                f"Usa la tool ha_call_service, que emite un preview y un "
                f"confirmation_token, en vez de una tool de atajo."
            )
        validate_path_segment(domain, field="domain")
        validate_path_segment(service, field="service")
        if service_data is None:
            service_data = {}
        return await self._request_json(
            "POST",
            f"/services/{domain}/{service}",
            json_body=service_data,
        )

    async def call_service_response(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
    ) -> Any:
        """Llama un servicio de Home Assistant con return_response=1."""
        validate_path_segment(domain, field="domain")
        validate_path_segment(service, field="service")
        if service_data is None:
            service_data = {}
        return await self._request_json(
            "POST",
            f"/services/{domain}/{service}",
            json_body=service_data,
            params={"return_response": "1"},
        )

    async def _run_background(self) -> None:
        """Loop de conexión y reconexión al WebSocket de HA."""
        while not self._stop_event.is_set():
            try:
                await self._connect_and_watch()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "ha_ws_reconnect_failure",
                    error=str(exc),
                    ws_url=self._ws_url,
                )
            # `ready` se limpia en cada caída para que no sea un latch de un
            # solo sentido. Sin esto, con la WS caída `get_states()` seguiría
            # sirviendo la caché congelada como si fuera dato vivo (su fallback
            # REST quedaría inalcanzable) y `wait_ready()` devolvería True al
            # instante, dejando `requires_ready` sin efecto durante las
            # reconexiones.
            self._connected_event.clear()
            self._health_server.set_ws_connected(False)
            await asyncio.sleep(5)

    async def _connect_and_watch(self) -> None:
        """Establece la conexión WebSocket y procesa eventos de estado."""
        if self._session is None or self._session.closed:
            raise HAConnectionError("El cliente HTTP no está inicializado.")

        # `timeout` espera un ClientWSTimeout, y hay que pasarlo como tal: un
        # ClientTimeout aquí lo trata aiohttp como el parámetro float legacy y
        # construye `ClientWSTimeout(ws_close=<ClientTimeout>)` dejando
        # `ws_receive=None`, lo que a su vez pone `conn_proto.read_timeout =
        # None`. Con eso, si la conexión TCP muere en silencio (evicción de NAT,
        # cambio de red del host) `receive()` se bloquea PARA SIEMPRE,
        # `_connect_and_watch` no retorna y `set_ws_connected(False)` no llega a
        # ejecutarse — así que /health seguiría diciendo "healthy" y el watchdog
        # del Supervisor tampoco reiniciaría nada.
        #
        # `heartbeat` es lo que de verdad detecta una conexión muerta: aiohttp
        # manda un ping cada N segundos y cierra si no llega el pong, con lo que
        # `receive()` devuelve CLOSED y el bucle de reconexión hace su trabajo.
        # No se pone `ws_receive` porque la WS de HA es dirigida por eventos:
        # un rato sin tráfico es normal y no debe forzar una reconexión.
        async with self._session.ws_connect(
            self._ws_url,
            headers={"Authorization": f"Bearer {self._supervisor_token}"},
            timeout=ClientWSTimeout(ws_close=10.0),
            heartbeat=30.0,
            # Tope real del frame WS, que es lo que promete la opcion
            # `ha_ws_max_msg_size_bytes`. Sin cablearla aqui rige el default de
            # aiohttp y un unico resultado grande (un ha_get_history amplio)
            # tumba la WebSocket entera, no solo esa llamada.
            max_msg_size=self._ws_max_msg_size,
        ) as ws:
            self._ws = ws
            await self._authenticate_ws()
            # Suscribirse va PRIMERO. Al reves —snapshot y luego suscripcion—
            # se pierde todo lo que cambie entre una cosa y otra: la entrada se
            # queda con el valor viejo hasta que esa entidad vuelva a cambiar y
            # `ha_get_state` lo sirve sin avisar. Los eventos que lleguen
            # mientras se pide el snapshot se quedan en el socket y los procesa
            # el bucle de lectura despues; que uno de ellos sea mas viejo que
            # el snapshot lo resuelve `_state_is_newer` en el manejador.
            await self._subscribe_state_changes()
            await self._populate_state_cache()

            # Señalizar reconexión a waits activos
            self._reconnect_generation += 1
            for q in list(self._event_subscription_queues.values()):
                q.put_nowait(_WS_CLOSED_SENTINEL)
            self._event_subscription_queues.clear()

            self._connected_event.set()
            self._health_server.set_ws_connected(True)
            logger.info("ha_ws_connected", ws_url=self._ws_url)

            await self._read_ws_messages()

    async def _authenticate_ws(self) -> None:
        """Realiza el handshake de autenticación del WebSocket de HA."""
        if self._ws is None:
            raise HAConnectionError("WebSocket no disponible para autenticar.")

        # Esperar el mensaje inicial de auth_required antes de enviar las credenciales.
        msg = await self._ws.receive(timeout=10)
        if msg.type != WSMsgType.TEXT:
            raise HAConnectionError("Respuesta inválida del WebSocket de HA durante auth.")

        data = json.loads(msg.data)
        if data.get("type") != "auth_required":
            raise HAConnectionError(
                f"WebSocket unexpected auth handshake message: {data}"
            )

        await self._ws.send_json(
            {
                "type": "auth",
                "access_token": self._supervisor_token,
            }
        )

        msg = await self._ws.receive(timeout=10)
        if msg.type != WSMsgType.TEXT:
            raise HAConnectionError("Respuesta inválida del WebSocket de HA durante auth.")

        data = json.loads(msg.data)
        if data.get("type") != "auth_ok":
            raise HAConnectionError(
                f"WebSocket auth failed: {data.get('message', 'unknown')}"
            )

    async def _populate_state_cache(self) -> None:
        """Carga el snapshot inicial de estados desde el REST de HA."""
        states = await self._request_json("GET", "/states")
        if not isinstance(states, list):
            raise HAConnectionError("El endpoint /states devolvió un formato inesperado.")

        async with self._cache_lock:
            self._state_cache = {
                state["entity_id"]: state
                for state in states
                if isinstance(state, dict) and state.get("entity_id")
            }

    async def _subscribe_state_changes(self) -> None:
        """Se suscribe a los eventos state_changed de Home Assistant."""
        if self._ws is None:
            raise HAConnectionError("WebSocket no disponible para suscripción.")

        subscribe_id = self._next_ws_request_id
        self._next_ws_request_id += 1
        await self._ws.send_json(
            {
                "id": subscribe_id,
                "type": "subscribe_events",
                "event_type": "state_changed",
            }
        )

        msg = await self._ws.receive(timeout=10)
        if msg.type != WSMsgType.TEXT:
            raise HAConnectionError("Respuesta inválida al suscribir eventos de estado.")

        data = json.loads(msg.data)
        if data.get("type") != "result" or not data.get("success"):
            raise HAConnectionError(
                f"No se pudo suscribir a state_changed: {data}")

    async def _read_ws_messages(self) -> None:
        """Procesa mensajes entrantes del WebSocket de HA."""
        if self._ws is None:
            raise HAConnectionError("WebSocket no disponible para lectura.")

        while not self._stop_event.is_set():
            msg = await self._ws.receive()
            if msg.type == WSMsgType.TEXT:
                await self._handle_ws_message(json.loads(msg.data))
                continue

            if msg.type in {WSMsgType.CLOSED, WSMsgType.CLOSING}:
                self._fail_pending_requests(HAConnectionError("WebSocket cerrado por Home Assistant."))
                raise HAConnectionError("WebSocket cerrado por Home Assistant.")
            if msg.type == WSMsgType.ERROR:
                self._fail_pending_requests(HAConnectionError("WebSocket error en la conexión de HA."))
                raise HAConnectionError("WebSocket error en la conexión de HA.")

    async def _handle_ws_message(self, data: Any) -> None:
        """Procesa mensajes entrantes del WebSocket de HA."""
        if not isinstance(data, dict):
            return

        if data.get("type") == "result":
            request_id = data.get("id")
            if isinstance(request_id, int):
                future = self._pending_ws_responses.pop(request_id, None)
                if future is not None and not future.done():
                    if data.get("success") is False:
                        error = data.get("error", {})
                        message = error.get("message") if isinstance(error, dict) else str(error)
                        future.set_exception(
                            HAConnectionError(
                                f"HA WS command failed: {message or 'unknown error'}"
                            )
                        )
                    else:
                        future.set_result(data.get("result"))
            return

        if data.get("type") != "event":
            return

        event = data.get("event")
        if not isinstance(event, dict):
            return

        # Subscripciones persistentes (wait_for_event)
        msg_id = data.get("id")
        if isinstance(msg_id, int) and msg_id in self._event_subscription_queues:
            queue = self._event_subscription_queues[msg_id]
            queue.put_nowait(event)
            return

        # Eventos de suscripciones one-shot (render_template, etc.)
        if isinstance(msg_id, int) and msg_id in self._pending_ws_subscriptions:
            future = self._pending_ws_subscriptions.pop(msg_id, None)
            if future is not None and not future.done():
                future.set_result(event)
            return

        if event.get("event_type") != "state_changed":
            return

        event_data = event.get("data")
        if not isinstance(event_data, dict):
            return

        entity_id = event_data.get("entity_id")
        new_state = event_data.get("new_state")
        if not isinstance(entity_id, str):
            return

        # La actualizacion se aplica aqui mismo, sin `asyncio.create_task(...)`:
        # el loop solo guarda una referencia debil a la tarea, asi que el
        # recolector puede llevarsela a medias y perder la actualizacion en
        # silencio —la documentacion de asyncio avisa expresamente—, y varias
        # tareas compitiendo por el mismo lock no garantizan el orden de
        # aplicacion. No hace falta ninguna tarea: el manejador es async y el
        # bucle de lectura lo espera. El lock solo se sostiene para tocar un
        # dict, y ningun sitio lo retiene mientras espera algo de la WebSocket,
        # asi que no hay riesgo de bloqueo.
        async with self._cache_lock:
            if new_state is None:
                anterior = self._state_cache.get(entity_id)
                marca_evento = event.get("time_fired")
                borrar = True
                if isinstance(marca_evento, str) and anterior is not None:
                    try:
                        borrar = (datetime.fromisoformat(marca_evento).timestamp()
                                  >= (_state_timestamp(anterior) or 0.0))
                    except (ValueError, TypeError):
                        borrar = True
                if borrar:
                    self._state_cache.pop(entity_id, None)
            elif _state_is_newer(new_state, self._state_cache.get(entity_id)):
                self._state_cache[entity_id] = new_state

    async def ws_send(self, payload: dict[str, Any], timeout_seconds: int = 30) -> Any:
        """Envía un comando al WebSocket de Home Assistant y espera su resultado."""
        if self._ws is None or self._ws.closed:
            raise HAConnectionError("WebSocket no disponible para envío de comandos.")

        async with self._ws_request_lock:
            request_id = self._next_ws_request_id
            self._next_ws_request_id += 1

            future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
            self._pending_ws_responses[request_id] = future

            payload_with_id = dict(payload)
            payload_with_id["id"] = request_id
            await self._ws.send_json(payload_with_id)

            try:
                return await asyncio.wait_for(future, timeout_seconds)
            except asyncio.TimeoutError as exc:
                self._pending_ws_responses.pop(request_id, None)
                raise HAConnectionError(
                    f"Timeout waiting for HA WS response for command {payload.get('type')}"
                ) from exc
            finally:
                self._pending_ws_responses.pop(request_id, None)

    async def ws_one_shot_subscription(
        self,
        payload: dict[str, Any],
        event_timeout_seconds: float = 10.0,
    ) -> dict[str, Any]:
        """Envía un comando WS de suscripción, espera el primer evento y cancela.

        Protocolo (render_template y similares):
          1. HA responde type:result (confirmación de suscripción, result=None)
          2. HA emite type:event con los datos reales
          3. Hermes manda unsubscribe_events para cerrar la suscripción

        Garantiza que no quedan suscripciones huérfanas incluso en caso de
        timeout o error. Si no llega el event en event_timeout_seconds, lanza
        HAConnectionError con el template/payload original en el mensaje.

        Raises:
            HAConnectionError: WS no disponible, suscripción rechazada por HA,
                               o timeout esperando el evento.
        """
        if self._ws is None or self._ws.closed:
            raise HAConnectionError("WebSocket no disponible para envío de comandos.")

        loop = asyncio.get_running_loop()

        async with self._ws_request_lock:
            request_id = self._next_ws_request_id
            self._next_ws_request_id += 1

            result_future: asyncio.Future[Any] = loop.create_future()
            event_future: asyncio.Future[Any] = loop.create_future()

            self._pending_ws_responses[request_id] = result_future
            self._pending_ws_subscriptions[request_id] = event_future

            payload_with_id = dict(payload)
            payload_with_id["id"] = request_id
            await self._ws.send_json(payload_with_id)
        # Lock liberado — otros ws_send pueden proceder mientras esperamos

        # Esperar confirmación de suscripción (type:result)
        try:
            await asyncio.wait_for(result_future, timeout=event_timeout_seconds)
        except asyncio.TimeoutError:
            self._pending_ws_responses.pop(request_id, None)
            self._pending_ws_subscriptions.pop(request_id, None)
            await self._ws_unsubscribe(request_id)
            raise HAConnectionError(
                f"Timeout waiting for subscription confirmation: {payload.get('type')}"
            )
        except HAConnectionError:
            self._pending_ws_subscriptions.pop(request_id, None)
            await self._ws_unsubscribe(request_id)
            raise
        finally:
            self._pending_ws_responses.pop(request_id, None)

        # Esperar el primer evento con los datos reales
        try:
            event_data = await asyncio.wait_for(event_future, timeout=event_timeout_seconds)
            return event_data if isinstance(event_data, dict) else {}
        except asyncio.TimeoutError:
            self._pending_ws_subscriptions.pop(request_id, None)
            raise HAConnectionError(
                f"Timeout waiting for subscription event: {payload.get('type')}"
            )
        finally:
            # Siempre cancelar la suscripción al salir (con o sin error)
            await self._ws_unsubscribe(request_id)

    async def ws_subscribe_events_queue(
        self,
        event_type: str,
    ) -> "tuple[int, asyncio.Queue[Any], int]":
        """Suscribe a eventos HA de un tipo específico via cola persistente.

        Devuelve (sub_id, queue, generation) donde:
        - sub_id: ID de suscripción para usar en ws_unsubscribe_events
        - queue: Cola de eventos recibidos. Cada item es el dict 'event' de HA,
          o _WS_CLOSED_SENTINEL si la WS se reconectó/cerró.
        - generation: Número de reconexiones al momento de suscribir.

        El llamador es responsable de llamar ws_unsubscribe_events_queue(sub_id)
        cuando termine, incluso si recibe el sentinel.
        """
        if self._ws is None or self._ws.closed:
            raise HAConnectionError("WebSocket no disponible para suscripción.")

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Any] = asyncio.Queue()

        async with self._ws_request_lock:
            sub_id = self._next_ws_request_id
            self._next_ws_request_id += 1

            result_future: asyncio.Future[Any] = loop.create_future()
            self._pending_ws_responses[sub_id] = result_future
            self._event_subscription_queues[sub_id] = queue

            await self._ws.send_json({
                "id": sub_id,
                "type": "subscribe_events",
                "event_type": event_type,
            })

        # Si algo sale mal aqui hay que deshacer TODO lo que se dejo montado
        # antes de mandar el subscribe: la cola, el future pendiente y —sobre
        # todo— la suscripcion en el lado de Home Assistant.
        #
        # El `sub_id` no llega a devolverse por ninguno de los dos caminos de
        # error, asi que el `finally` del llamador no puede cancelar nada: si HA
        # creo la suscripcion y lo que tardo fue la confirmacion, HA seguiria
        # mandando ese tipo de evento por la WebSocket para siempre, sin nadie
        # al otro lado, y el future quedaria en `_pending_ws_responses` hasta la
        # siguiente reconexion.
        try:
            await asyncio.wait_for(result_future, timeout=10.0)
        except asyncio.TimeoutError as exc:
            self._pending_ws_responses.pop(sub_id, None)
            await self._ws_unsubscribe(sub_id)
            raise HAConnectionError(
                f"Timeout esperando confirmación de suscripción a '{event_type}'"
            ) from exc
        except BaseException:
            self._pending_ws_responses.pop(sub_id, None)
            await self._ws_unsubscribe(sub_id)
            raise

        generation = self._reconnect_generation
        return sub_id, queue, generation

    async def ws_unsubscribe_events_queue(self, sub_id: int) -> None:
        """Cancela una suscripción persistente de eventos (best-effort)."""
        self._event_subscription_queues.pop(sub_id, None)
        await self._ws_unsubscribe(sub_id)

    async def _ws_unsubscribe(self, subscription_id: int) -> None:
        """Cancela una suscripción WS enviando unsubscribe_events (fire-and-forget)."""
        self._event_subscription_queues.pop(subscription_id, None)
        if self._ws is None or self._ws.closed:
            return
        try:
            async with self._ws_request_lock:
                unsubscribe_id = self._next_ws_request_id
                self._next_ws_request_id += 1
                await self._ws.send_json({
                    "id": unsubscribe_id,
                    "type": "unsubscribe_events",
                    "subscription": subscription_id,
                })
        except Exception:  # noqa: BLE001
            pass  # Best-effort: no propagar errores de cleanup

    # ── Collection helpers vía WS (input_*, counter, timer, schedule)
    #
    # HA expone estos helpers solo por WebSocket usando el patrón
    # `StorageCollectionWebsocket`: commands `{domain}/{list|create|update|delete}`,
    # payload plano al top-level, id field = `{domain}_id`. No existe get
    # individual — hay que hacer list + filtrar.
    #
    # NO USAR `config_*` (REST `/api/config/...`) para estos tipos: ese endpoint
    # solo existe en HA para automation/script/scene y devuelve 404 en helpers.

    async def ws_collection_list(self, domain: str) -> list[dict[str, Any]]:
        """Lista items de una StorageCollection (helpers de colección).

        La mayoría de los tipos devuelven una lista plana. `person/list`
        devuelve `{"storage": [...], "config": [...]}` (storage = editables,
        config = YAML read-only). Aquí nos quedamos sólo con los editables —
        son los únicos que permiten update/delete por WS.
        """
        result = await self.ws_send({"type": f"{domain}/list"})
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and isinstance(result.get("storage"), list):
            return result["storage"]
        return []

    async def ws_collection_get(
        self, domain: str, object_id: str
    ) -> dict[str, Any] | None:
        """Busca un item por su object_id mediante list + filtro."""
        items = await self.ws_collection_list(domain)
        for item in items:
            if isinstance(item, dict) and item.get("id") == object_id:
                return item
        return None

    async def ws_collection_create(
        self, domain: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Crea un item. HA deriva el object_id de slugify(name)."""
        payload: dict[str, Any] = {"type": f"{domain}/create"}
        payload.update(config)
        result = await self.ws_send(payload)
        return result if isinstance(result, dict) else {}

    async def ws_collection_update(
        self, domain: str, object_id: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Actualiza un item existente usando `{domain}_id`."""
        id_key = f"{domain}_id"
        payload: dict[str, Any] = {"type": f"{domain}/update", id_key: object_id}
        payload.update(config)
        result = await self.ws_send(payload)
        return result if isinstance(result, dict) else {}

    async def ws_collection_delete(
        self, domain: str, object_id: str
    ) -> bool:
        """Borra un item. Devuelve True si se borró, False si no existía.

        HA WS devuelve error `not_found` (o similar) si el id no existe.
        Otros errores se propagan como HAConnectionError.
        """
        id_key = f"{domain}_id"
        payload: dict[str, Any] = {
            "type": f"{domain}/delete",
            id_key: object_id,
        }
        try:
            await self.ws_send(payload)
            return True
        except HAConnectionError as exc:
            if "not found" in str(exc).lower() or "not_found" in str(exc).lower():
                return False
            raise

    async def fire_event(
        self, event_type: str, event_data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Dispara un evento custom en el bus de HA vía WS `fire_event`.

        El allowlist de `event_type` se aplica en la capa de tool, no aquí.
        """
        payload: dict[str, Any] = {"type": "fire_event", "event_type": event_type}
        if event_data:
            payload["event_data"] = event_data
        result = await self.ws_send(payload)
        return result if isinstance(result, dict) else {"result": result}

    async def config_read(
        self,
        domain: str,
        config_id: str,
    ) -> dict[str, Any] | None:
        """Lee la configuración persistida de una entidad editable vía REST.

        Usa el endpoint `/api/config/{domain}/config/{config_id}` expuesto por
        `EditIdBasedConfigView` / `EditKeyBasedConfigView` en HA core. No es un
        comando WebSocket: HA no expone CRUD de automations/scripts vía WS.

        Devuelve `None` si la entidad no existe (404), o el dict de config
        completo si existe. Cualquier otro error → `HAConnectionError`.
        """
        return await self._config_request(
            "GET",
            domain,
            config_id,
            expect_ok=False,
            allow_missing=True,
        )

    async def config_save(
        self,
        domain: str,
        config_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Crea o actualiza la configuración de una entidad editable vía REST.

        Tras un save exitoso, HA dispara automáticamente el `post_write_hook`
        correspondiente, que recarga la entidad (equivalente a
        `automation.reload` / `script.reload`). No hace falta llamar a
        `ha_reload_*` a mano tras un save.

        Devuelve el dict de respuesta (típicamente `{"result": "ok"}`).
        """
        result = await self._config_request(
            "POST",
            domain,
            config_id,
            json_body=config,
            expect_ok=True,
            allow_missing=False,
        )
        return result or {}

    async def config_delete(
        self,
        domain: str,
        config_id: str,
    ) -> dict[str, Any] | None:
        """Elimina una entidad editable vía REST.

        Devuelve `None` si la entidad no existía (HA responde 400 con
        `Resource not found`); en caso de éxito devuelve `{"result": "ok"}`.
        """
        return await self._config_request(
            "DELETE",
            domain,
            config_id,
            expect_ok=True,
            allow_missing=True,
        )

    async def _config_request(
        self,
        method: str,
        domain: str,
        config_id: str,
        *,
        json_body: dict[str, Any] | None = None,
        expect_ok: bool,
        allow_missing: bool,
    ) -> dict[str, Any] | None:
        """Helper común para los endpoints `/config/{domain}/config/{id}`."""
        if self._session is None:
            raise HAConnectionError("Cliente HTTP de HA no inicializado.")

        validate_path_segment(domain, field="domain")
        validate_path_segment(config_id, field="config_id")
        path = f"/config/{domain}/config/{config_id}"
        _assert_safe_request_path(path)
        url = f"{self._rest_base_url}{path}"

        async with self._session.request(
            method,
            url,
            json=json_body,
            timeout=ClientTimeout(total=30),
        ) as resp:
            text = await resp.text()
            status = resp.status

            if status == 404 and allow_missing:
                return None

            if status == 400 and allow_missing and method == "DELETE":
                # HA devuelve 400 "Resource not found" al borrar algo inexistente.
                if "not found" in text.lower():
                    logger.info(
                        "ha_config_delete_missing",
                        domain=domain,
                        config_id=config_id,
                    )
                    return None

            if status >= 400:
                logger.warning(
                    "ha_config_request_http_error",
                    method=method,
                    domain=domain,
                    config_id=config_id,
                    status=status,
                    body=text[:500],
                )
                raise HAConnectionError(
                    f"HA REST {method} {url} failed {status}: {text}"
                )

            parsed: dict[str, Any] | None
            if not text:
                parsed = {}
            else:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as exc:
                    logger.error(
                        "ha_config_request_invalid_json",
                        method=method,
                        domain=domain,
                        config_id=config_id,
                        body=text[:500],
                    )
                    raise HAConnectionError(
                        f"HA REST returned invalid JSON: {text!r}"
                    ) from exc

            if expect_ok:
                if not isinstance(parsed, dict) or parsed.get("result") != "ok":
                    logger.warning(
                        "ha_config_request_unexpected_body",
                        method=method,
                        domain=domain,
                        config_id=config_id,
                        parsed=parsed,
                    )
                    raise HAConnectionError(
                        f"HA REST {method} {url} unexpected response: {parsed!r}"
                    )

            return parsed

    async def _request_json(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        """Hace un request REST a la API de Home Assistant y parsea JSON."""
        if self._session is None:
            raise HAConnectionError("Cliente HTTP de HA no inicializado.")

        _assert_safe_request_path(path)
        url = f"{self._rest_base_url}{path}"
        async with self._session.request(
            method,
            url,
            params=params,
            json=json_body,
            timeout=ClientTimeout(total=30),
        ) as resp:
            return await self._parse_response(resp)

    # ── Supervisor REST API ───────────────────────────────────────────────────

    async def sv_request(
        self,
        method: str,
        sv_path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        timeout_seconds: float = 60.0,
    ) -> Any:
        """Hace un request REST a la API del Supervisor (no la core API).

        La URL base es supervisor_base_url (ej. http://supervisor) — sin
        el sufijo /core/api que usa _request_json para la core API de HA.

        El Supervisor devuelve {result: "ok", data: {...}} o {result: "error",
        message: "..."}. Este método extrae y devuelve el campo data
        directamente, o lanza HAConnectionError si result==error.
        """
        if self._session is None:
            raise HAConnectionError("Cliente HTTP de HA no inicializado.")

        _assert_safe_request_path(sv_path)
        url = f"{self._supervisor_base_url}{sv_path}"
        async with self._session.request(
            method,
            url,
            params=params,
            json=json_body,
            timeout=ClientTimeout(total=timeout_seconds),
        ) as resp:
            return await self._parse_sv_response(resp)

    async def sv_request_text(
        self,
        sv_path: str,
        params: dict[str, str] | None = None,
        timeout_seconds: float = 60.0,
    ) -> str:
        """GET a la API del Supervisor y devuelve texto plano (logs de add-ons)."""
        if self._session is None:
            raise HAConnectionError("Cliente HTTP de HA no inicializado.")

        _assert_safe_request_path(sv_path)
        url = f"{self._supervisor_base_url}{sv_path}"
        async with self._session.get(
            url,
            params=params,
            timeout=ClientTimeout(total=timeout_seconds),
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise HAConnectionError(
                    f"Supervisor GET {sv_path} failed {resp.status}: {text}"
                )
            return text

    async def _parse_sv_response(self, resp: ClientResponse) -> Any:
        """Parsea una respuesta JSON del Supervisor.

        Extrae el campo data si result==ok; lanza HAConnectionError si
        result==error.
        """
        text = await resp.text()
        if resp.status >= 400:
            raise HAConnectionError(
                f"Supervisor REST {resp.method} {resp.url} failed {resp.status}: {text}"
            )

        if not text:
            return {}

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HAConnectionError(
                f"Supervisor returned invalid JSON: {text!r}"
            ) from exc

        if isinstance(parsed, dict):
            if parsed.get("result") == "error":
                raise HAConnectionError(
                    f"Supervisor error: {parsed.get('message', 'unknown error')}"
                )
            # result==ok: devolvemos data si existe, si no todo el dict
            if "data" in parsed:
                return parsed["data"]
        return parsed

    def _fail_pending_requests(self, error: Exception) -> None:
        """Fail all pending WS requests when the connection is lost."""
        for future in list(self._pending_ws_responses.values()):
            if not future.done():
                future.set_exception(error)
        self._pending_ws_responses.clear()

    async def _parse_response(self, resp: ClientResponse) -> Any:
        text = await resp.text()
        if resp.status >= 400:
            raise HAConnectionError(
                f"HA REST {resp.method} {resp.url} failed {resp.status}: {text}"
            )

        if not text:
            return {}

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise HAConnectionError(
                f"HA REST returned invalid JSON: {text!r}"
            ) from exc
