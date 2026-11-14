"""Tools genéricas: la cola larga de Core y del Supervisor por la tabla
(spec 011, FR-003, FR-004, FR-008…FR-017, FR-025; research R-6 y R-7).

Cuatro tools:

- `ha_read_ws_command(type, payload)`: comandos WebSocket de Core `read`.
- `ha_call_ws_command(type, payload, confirmation_token)`: comandos `confirm`,
  siempre en dos pasos.
- `sv_read_api(path)`: rutas `GET` del Supervisor `read`.
- `sv_call_api(method, path, body, confirmation_token)`: rutas `confirm`,
  siempre en dos pasos.

POR QUÉ ASÍ
-----------
Con `hassio_role: admin` y el token de Core, estas tools podrían mandar casi
cualquier cosa. Lo único que las separa de un acceso sin control es la tabla
(`command_table.py`) y las guardas de `command_policy`. Aquí no se decide
nada: se valida la forma de los argumentos, se pide la decisión a
`command_policy.decidir` y se aplica. Orden de las guardas (R-6): forma →
ruta (forma y proxy de Core) → tabla (en el Supervisor, plantilla y después
`self_target`) → categoría → dos pasos → ejecución → redacción → log sin
valores. Ninguna guarda se puede saltar: un rechazo vuelve sin tocar HA ni el
Supervisor.

Lo que nunca hacen (principio II):
- guardar la carga en disco: el token se ata a la carga por su hash, sin
  omitibles, y al confirmar solo se guarda `{"executed": true}`;
- copiar valores al log: solo la tool, el comando o la PLANTILLA de ruta, el
  método, la categoría, el resultado y los NOMBRES de las claves de primer
  nivel con su tamaño;
- devolver un error de HA o del Supervisor sin pasarlo por `redact_secrets`
  y sin tapar los valores de texto de la carga que repita.

El tope de respuesta lo aplica el servidor al final de cada llamada (spec
006); por eso una lista se devuelve con el sobre `{count, items, truncated}`,
que el tope sabe recortar. Los logs de texto los recorta esta tool por el
principio, porque lo que importa de un log es el final.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

import structlog

from hermes import command_policy as cp
from hermes.command_policy import Entrada, Permitido, Rechazo
from hermes.ha import HAClient, HAConnectionError
from hermes.logging_setup import redact_network
from hermes.security import (
    REDACTED_MARKER,
    complete_confirmation_token,
    create_confirmation_token,
    es_clave_sensible,
    redact_secrets,
    resolve_confirmation_token,
)
from hermes.tools._common import ajustar_lista_a_bytes, requires_ready, tam_json
from hermes.tools.addons import _es_hermes

logger = structlog.get_logger(__name__)

# FR-013: la forma de un `type` de Core. Exacta y en minúsculas: un `type` con
# otra forma no puede estar en la tabla, así que se rechaza sin buscarlo y sin
# copiarlo a ningún sitio (podría ser texto arbitrario del cliente).
_TIPO_RE = re.compile(r"[a-z0-9_-]+(?:/[a-z0-9_-]+)*")
_TIPO_MAX = 128

_METODOS = frozenset({"GET", "POST", "PUT", "DELETE", "PATCH"})

# FR-016: una suscripción de un solo mensaje espera como mucho esto y se
# cancela siempre (lo garantiza `ws_one_shot_subscription`).
_ONE_SHOT_TIMEOUT_SECONDS = 10.0

# Un valor de texto de la carga de 4 caracteres o más se tapa en los errores:
# HA y el Supervisor repiten a veces el valor que rechazan. Por debajo de 4,
# tapar destrozaría el mensaje («on», «1») sin proteger nada.
_MIN_TAPAR_EN_ERROR = 4
_TAPADO = "***"

# Longitud de un token emitido (UUID): para medir la vista previa ANTES de
# crear el token, con el mismo tamaño que tendrá.
_TOKEN_DE_MUESTRA = "00000000-0000-0000-0000-000000000000"

# La nota dice exactamente lo que enseña el resumen (enmienda E-1, T045):
# todas las claves; los valores cortos enteros, los largos por su inicio, su
# tamaño y un hash, y los sensibles tapados.
_NOTA_CORE = (
    "This preview lists every key that will be sent to Home Assistant: short "
    "values in full, long ones by their first 32 characters, size and a short "
    "SHA-256, sensitive ones hidden. It does not interpret the effect of the "
    "command."
)
_NOTA_SUPERVISOR = (
    "This preview lists every key that will be sent to the Supervisor: short "
    "values in full, long ones by their first 32 characters, size and a short "
    "SHA-256, sensitive ones hidden. It does not interpret the effect of the "
    "request."
)
_PISTA_VERSION = (
    "The installed Home Assistant does not know this command; Hermes' table is "
    "for {version}."
)

_DETALLES = {
    "command_not_classified": "This command is not in Hermes' command table.",
    "path_not_allowed": "This path is not allowed for the generic tools.",
    "family_disabled": "The tool family of this entry is disabled in the add-on options.",
}


# ── Utilidades ───────────────────────────────────────────────────────────────

def _valores_de_texto(valor: Any) -> set[str]:
    """Valores de texto de la carga (a cualquier profundidad) que se tapan en
    los mensajes de error."""
    out: set[str] = set()
    if isinstance(valor, str):
        if len(valor) >= _MIN_TAPAR_EN_ERROR:
            out.add(valor)
    elif isinstance(valor, Mapping):
        for v in valor.values():
            out |= _valores_de_texto(v)
    elif isinstance(valor, (list, tuple)):
        for v in valor:
            out |= _valores_de_texto(v)
    return out


def _mensaje_seguro(mensaje: str, carga: Any) -> str:
    """El mensaje de HA o del Supervisor sin secretos ni valores de la carga."""
    # Del más largo al más corto: si uno contiene a otro, se tapa entero.
    for v in sorted(_valores_de_texto(carga), key=len, reverse=True):
        mensaje = mensaje.replace(v, _TAPADO)
    return redact_secrets(mensaje)


def _redactar(valor: Any, extra: frozenset[str], clave: str = "") -> Any:
    """`redact_structure` más las claves extra de la entrada, y
    `redact_secrets` en todos los textos (FR-014): un JWT o un `password=…`
    dentro de un texto no lleva una clave que lo delate."""
    if isinstance(valor, Mapping):
        return {k: _redactar(v, extra, str(k)) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_redactar(v, extra, clave) for v in valor]
    if isinstance(valor, str):
        if valor and (es_clave_sensible(clave) or clave.lower() in extra):
            return REDACTED_MARKER
        return redact_secrets(valor)
    if clave and clave.lower() in extra and valor is not None:
        # Una clave extra de la tabla es sensible por decisión explícita
        # (p. ej. un PIN numérico): se tapa sea cual sea su tipo.
        return REDACTED_MARKER
    return valor


def _extra(entrada: Entrada) -> frozenset[str]:
    return frozenset(k.lower() for k in entrada.redact_extra)


def _respuesta(cabecera: dict[str, Any], resultado: Any) -> dict[str, Any]:
    """Una lista va con el sobre común para que el tope central la recorte;
    un objeto o un escalar, en `result` (R-6)."""
    if isinstance(resultado, list):
        return {**cabecera, "count": len(resultado), "items": resultado,
                "truncated": False}
    return {**cabecera, "result": resultado}


def _ultimas_lineas(cabecera: dict[str, Any], texto: str, max_bytes: int) -> dict[str, Any]:
    """Las ÚLTIMAS líneas del log que caben (FR-014): de un log importa el
    final. Se recorta aquí porque el tope central quitaría las del final."""
    lineas = texto.splitlines()
    al_reves = list(reversed(lineas))

    def construir(items: list[str], recortada: bool) -> dict[str, Any]:
        return {**cabecera, "count": len(items), "lines": list(reversed(items)),
                "truncated": recortada}

    return ajustar_lista_a_bytes(al_reves, construir, max_bytes)


def _claves(carga: Any) -> list[str] | None:
    if isinstance(carga, Mapping):
        return sorted(str(k) for k in carga)
    return None


# ── Registro ─────────────────────────────────────────────────────────────────

def register(
    mcp: Any,
    ha_client: HAClient,
    *,
    response_max_bytes: int,
    familias_desactivadas: frozenset[str] = frozenset(),
    tabla_core: Mapping[str, Entrada] | None = None,
    tabla_supervisor: Mapping[tuple[str, str], Entrada] | None = None,
) -> None:
    """Registra las cuatro genéricas.

    `tabla_core` y `tabla_supervisor` solo los pasan los tests (tablas
    inyectadas); en producción, la tabla real de `command_table.py`.
    """
    ready = requires_ready(ha_client)
    desactivadas = frozenset(familias_desactivadas)

    def log(tool: str, outcome: str, **campos: Any) -> None:
        # Nunca valores ni la ruta concreta: solo lo que deja ver QUÉ se hizo.
        logger.info("generic_command", tool=tool, outcome=outcome,
                    **{k: v for k, v in campos.items() if v is not None})

    def rechazo(tool: str, r: Rechazo, sujeto: str | None, **log_campos: Any) -> dict[str, Any]:
        log(tool, f"rejected:{r.codigo}", **log_campos)
        if r.codigo == "command_denied":
            detalle = f"{sujeto} is not allowed."
        elif r.codigo == "use_dedicated_tool":
            detalle = f"{sujeto} has a dedicated tool."
        elif r.codigo == "wrong_generic_tool":
            detalle = (f"{sujeto} needs confirmation." if r.campos.get("use_tool", "").endswith(
                ("_call_ws_command", "_call_api")) else f"{sujeto} only reads.")
        else:
            detalle = _DETALLES.get(r.codigo, r.codigo)
        return {"error": r.codigo, "detail": detalle, **r.campos}

    def argumento_invalido(tool: str, campo: str, detalle: str, **log_campos: Any) -> dict[str, Any]:
        log(tool, "rejected:invalid_argument", field=campo, **log_campos)
        return {"error": "invalid_argument", "detail": detalle, "field": campo}

    # ── Core ──────────────────────────────────────────────────────────────

    def validar_core(tool: str, type: Any, payload: Any) -> dict[str, Any] | None:
        if not isinstance(type, str) or len(type) > _TIPO_MAX or not _TIPO_RE.fullmatch(type):
            return argumento_invalido(
                tool, "type",
                "type must be a Home Assistant WebSocket command such as 'search/related' "
                f"(lowercase letters, digits, '_', '-' and '/'; at most {_TIPO_MAX} characters).",
            )
        if payload is not None and not isinstance(payload, Mapping):
            return argumento_invalido(tool, "payload", "payload must be an object.",
                                      command=type)
        if isinstance(payload, Mapping) and ({"id", "type"} & set(payload)):
            return argumento_invalido(
                tool, "payload",
                "payload must not contain 'id' or 'type': Hermes sets them.",
                command=type)
        return None

    def decidir_core(tool: str, type: str) -> Permitido | Rechazo:
        entrada = cp.buscar_core(type, tabla=tabla_core)
        return cp.decidir(tool, entrada, familias_desactivadas=desactivadas)

    async def ejecutar_core(
        tool: str, type: str, entrada: Entrada, carga: dict[str, Any],
        log_campos: dict[str, Any],
    ) -> tuple[Any, dict[str, Any] | None]:
        """(resultado redactado, None) o (None, error)."""
        mensaje = {"type": type, **carga}
        try:
            if entrada.one_shot:
                # Nunca `ws_send`: dejaría la suscripción abierta (FR-016).
                bruto = await ha_client.ws_one_shot_subscription(
                    mensaje, event_timeout_seconds=_ONE_SHOT_TIMEOUT_SECONDS)
            else:
                bruto = await ha_client.ws_send(mensaje)
        except HAConnectionError as exc:
            log(tool, "failed", **log_campos)
            seguro = _mensaje_seguro(str(exc), carga)
            if exc.code is None:
                # Sin código de HA es un fallo de conexión: el error de
                # siempre de las tools (WebSocket caída, timeout).
                return None, {"error": seguro}
            error: dict[str, Any] = {"error": "ha_command_failed", "detail": seguro,
                                     "ha_code": exc.code}
            if exc.code == "unknown_command":
                from hermes.command_table import TABLE_HA_CORE
                error["hint"] = _PISTA_VERSION.format(version=TABLE_HA_CORE)
            return None, error
        return _redactar(bruto, _extra(entrada)), None

    @mcp.tool()
    @ready
    async def ha_read_ws_command(type: str, payload: dict | None = None) -> object:
        """Run a read-only Home Assistant WebSocket command that Hermes' command table classifies as `read`.

        Use it only for what no dedicated tool covers (the long tail of Home
        Assistant). It executes ONLY commands the table marks `read`; anything
        else is rejected without reaching Home Assistant:
        - not in the table → `command_not_classified`;
        - `deny` → `command_denied` with the reason;
        - covered by a dedicated tool → `use_dedicated_tool` with its name;
        - `confirm` (it changes something) → `wrong_generic_tool`: use
          `ha_call_ws_command`.
        `hermes_guide(topic="generic_commands")` explains the categories and
        searches the table (`search=`).

        Args:
            type: The WebSocket command, e.g. "tag/list".
            payload: Its fields, without `id` or `type` (Hermes sets them).

        Returns:
            {"command", "category": "read", "result"} or, for a list,
            {"command", "category", "count", "items", "truncated"}. Secrets in
            the answer are redacted.
        """
        tool = "ha_read_ws_command"
        if (err := validar_core(tool, type, payload)):
            return err
        carga = dict(payload or {})
        log_campos = {"command": type, "payload_keys": _claves(carga),
                      "payload_bytes": tam_json(carga)}
        decision = decidir_core(tool, type)
        if isinstance(decision, Rechazo):
            return rechazo(tool, decision, type, **log_campos)
        entrada = decision.entrada
        log_campos["category"] = entrada.category
        resultado, error = await ejecutar_core(tool, type, entrada, carga, log_campos)
        if error is not None:
            return error
        log(tool, "executed", **log_campos)
        return _respuesta({"command": type, "category": entrada.category}, resultado)

    @mcp.tool()
    @ready
    async def ha_call_ws_command(
        type: str,
        payload: dict | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Run a Home Assistant WebSocket command that Hermes' command table classifies as `confirm`, always in two steps.

        Use it only for what no dedicated tool covers. It executes ONLY
        commands the table marks `confirm`; `read` ones go through
        `ha_read_ws_command`, and `deny`, dedicated or unknown ones are
        rejected without reaching Home Assistant.

        First call (no token): returns `preview` and `confirmation_token`.
        The preview shows what will be sent (command, category, reason, CAP
        and a summary of every payload key with its type and size; short
        values in full, long ones by their start and a short hash, sensitive
        ones hidden). It does NOT
        interpret what the command will do. Show it to the user. Second call:
        the same `type` and `payload` plus `confirmation_token` (valid ~60 s,
        once). If the preview does not fit in the response limit, nothing is
        issued (`preview_too_large`).
        `hermes_guide(topic="generic_commands")` explains the categories and
        searches the table (`search=`).

        Args:
            type: The WebSocket command, e.g. "tag/create".
            payload: Its fields, without `id` or `type`.
            confirmation_token: Token from the preview, to execute.

        Returns:
            The preview, or {"command", "category", "executed": true,
            "result"} (a list comes as `count`/`items`/`truncated`).
        """
        tool = "ha_call_ws_command"
        if (err := validar_core(tool, type, payload)):
            return err
        carga = dict(payload or {})
        log_campos = {"command": type, "payload_keys": _claves(carga),
                      "payload_bytes": tam_json(carga)}
        decision = decidir_core(tool, type)
        if isinstance(decision, Rechazo):
            return rechazo(tool, decision, type, **log_campos)
        entrada = decision.entrada
        log_campos["category"] = entrada.category
        # El hash ata el token a la tool, al comando y a la carga COMPLETA.
        args = {"type": type, "payload": carga}

        if not confirmation_token:
            preview = {
                "tool": tool, "command": type, "category": entrada.category,
                "reason": entrada.reason, "cap": entrada.cap, "note": _NOTA_CORE,
                "payload_summary": cp.resumir_carga(carga, entrada.redact_extra),
            }
            return await emitir_vista_previa(tool, args, preview, carga, log_campos)

        ok, motivo, _ = await resolve_confirmation_token(confirmation_token, tool, args)
        if not ok:
            log(tool, "rejected:invalid_confirmation_token", **log_campos)
            return {"error": "invalid_confirmation_token", "detail": motivo}
        resultado, error = await ejecutar_core(tool, type, entrada, carga, log_campos)
        if error is not None:
            # Solo el código, nunca el mensaje: el fichero del token vive en
            # /data, que entra en los backups.
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(error.get("ha_code") or "failed"))
            return error
        await complete_confirmation_token(confirmation_token, result={"executed": True})
        log(tool, "executed", **log_campos)
        return _respuesta(
            {"command": type, "category": entrada.category, "executed": True}, resultado)

    async def emitir_vista_previa(
        tool: str, args: dict[str, Any], preview: dict[str, Any], carga: Any,
        log_campos: dict[str, Any],
    ) -> dict[str, Any]:
        # Se mide ANTES de crear el token: si no cabe, el tope central la
        # resumiría y el usuario confirmaría algo que no ha visto entero.
        muestra = {"confirmation_token": _TOKEN_DE_MUESTRA,
                   "expires_in_seconds": 60, "preview": preview}
        if tam_json(muestra) > response_max_bytes:
            log(tool, "rejected:preview_too_large", **log_campos)
            return {
                "error": "preview_too_large",
                "detail": ("The preview does not fit in response_max_bytes, so no "
                           "confirmation_token was issued. Send a smaller payload."),
                "payload_bytes": tam_json(carga),
                "keys": preview.get("payload_summary", preview.get("body_summary", {})).get("keys"),
            }
        resp = await create_confirmation_token(tool, args, preview)
        log(tool, "preview", **log_campos)
        return resp

    # ── Supervisor ────────────────────────────────────────────────────────

    def decidir_supervisor(
        tool: str, method: str, path: str,
    ) -> tuple[Permitido | Rechazo, str | None]:
        """(decisión, plantilla casada o None)."""
        if (r := cp.validar_ruta(path)) is not None:
            return r, None
        casado = cp.casar_ruta(method, path, tabla=tabla_supervisor)
        if casado is None:
            return cp.decidir(tool, None, familias_desactivadas=desactivadas), None
        (_, plantilla), entrada = casado
        decision = cp.decidir(
            tool, entrada, familias_desactivadas=desactivadas,
            parametros=cp.parametros(plantilla, path), es_hermes=_es_hermes,
        )
        return decision, plantilla

    async def ejecutar_supervisor(
        tool: str, method: str, path: str, ruta: str, entrada: Entrada,
        body: dict[str, Any] | None, cabecera: dict[str, Any],
        log_campos: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        try:
            if entrada.response == "text" and method == "GET":
                texto = await ha_client.sv_request_text(path)
            elif body is None:
                bruto = await ha_client.sv_request(method, path)
            else:
                bruto = await ha_client.sv_request(method, path, json_body=body)
        except HAConnectionError as exc:
            log(tool, "failed", **log_campos)
            error: dict[str, Any] = {
                "error": "supervisor_request_failed",
                "detail": _mensaje_seguro(str(exc), body),
            }
            if exc.status is not None:
                error["status"] = exc.status
            return None, error
        if entrada.response == "text" and method == "GET":
            # La redacción de los logs: secretos y datos de red (FR-014).
            limpio = redact_network(redact_secrets(texto))
            return _ultimas_lineas(cabecera, limpio, response_max_bytes), None
        return _respuesta(cabecera, _redactar(bruto, _extra(entrada))), None

    @mcp.tool()
    @ready
    async def sv_read_api(path: str) -> object:
        """Read a Supervisor API path (GET) that Hermes' command table classifies as `read`.

        Use it only for what no dedicated `sv_*` tool covers. It executes ONLY
        GET routes the table marks `read`; anything else is rejected without
        reaching the Supervisor (`command_not_classified`, `command_denied`,
        `use_dedicated_tool`, or `wrong_generic_tool` → `sv_call_api`).
        Never allowed: the Core API proxy (`/core/api*`,
        `/homeassistant/api*`) and paths whose app is Hermes itself
        (`path_not_allowed`). The path is a plain absolute path: no query,
        fragment, `%`, `..` or trailing slash.
        `hermes_guide(topic="generic_commands")` explains the categories and
        searches the table (`search=`).

        Args:
            path: Concrete path, e.g. "/dns/info".

        Returns:
            {"method", "path", "route", "category", "result"} (a list comes as
            `count`/`items`/`truncated`). Log routes return their LAST lines
            that fit: {"…", "count", "lines", "truncated"}. Secrets redacted.
        """
        tool = "sv_read_api"
        decision, ruta = decidir_supervisor(tool, "GET", path)
        log_campos = {"method": "GET", "route": ruta}
        if isinstance(decision, Rechazo):
            return rechazo(tool, decision, ruta, **log_campos)
        entrada = decision.entrada
        log_campos["category"] = entrada.category
        cabecera = {"method": "GET", "path": path, "route": ruta,
                    "category": entrada.category}
        resp, error = await ejecutar_supervisor(
            tool, "GET", path, ruta or "", entrada, None, cabecera, log_campos)
        if error is not None:
            return error
        log(tool, "executed", **log_campos)
        return resp

    @mcp.tool()
    @ready
    async def sv_call_api(
        method: str,
        path: str,
        body: dict | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Call a Supervisor API path that Hermes' command table classifies as `confirm`, always in two steps.

        Use it only for what no dedicated `sv_*` tool covers. It executes ONLY
        routes the table marks `confirm`; `read` ones go through
        `sv_read_api`, and `deny`, dedicated or unknown ones are rejected
        without reaching the Supervisor. Never allowed: the Core API proxy
        and paths whose app is Hermes itself (`path_not_allowed`).

        First call (no token): returns `preview` and `confirmation_token`. The
        preview shows what will be sent (method, concrete path, route
        template, category, reason, CAP and a summary of every body key; short
        values in full, long ones by their start and a short hash, sensitive
        ones hidden). It does NOT interpret what the
        request will do. Show it to the user. Second call: the same `method`,
        `path` and `body` plus `confirmation_token` (valid ~60 s, once).
        `hermes_guide(topic="generic_commands")` explains the categories and
        searches the table (`search=`).

        Args:
            method: GET, POST, PUT, DELETE or PATCH.
            path: Concrete path, e.g. "/dns/restart".
            body: JSON body, if the route takes one.
            confirmation_token: Token from the preview, to execute.

        Returns:
            The preview, or {"method", "path", "route", "category",
            "executed": true, "result"}.
        """
        tool = "sv_call_api"
        if not isinstance(method, str) or method.upper() not in _METODOS:
            return argumento_invalido(
                tool, "method", "method must be GET, POST, PUT, DELETE or PATCH.")
        metodo = method.upper()
        if body is not None and not isinstance(body, Mapping):
            return argumento_invalido(tool, "body", "body must be an object.",
                                      method=metodo)
        cuerpo = dict(body) if body is not None else None
        decision, ruta = decidir_supervisor(tool, metodo, path)
        log_campos = {"method": metodo, "route": ruta, "payload_keys": _claves(cuerpo),
                      "payload_bytes": tam_json(cuerpo) if cuerpo is not None else None}
        if isinstance(decision, Rechazo):
            return rechazo(tool, decision, ruta, **log_campos)
        entrada = decision.entrada
        log_campos["category"] = entrada.category
        # El hash ata el token al método, a la ruta CONCRETA y al cuerpo
        # completo: otra app con la misma plantilla no vale.
        args = {"method": metodo, "path": path, "body": cuerpo}

        if not confirmation_token:
            preview = {
                "tool": tool, "method": metodo, "path": path, "route": ruta,
                "category": entrada.category, "reason": entrada.reason,
                "cap": entrada.cap, "note": _NOTA_SUPERVISOR,
                "body_summary": cp.resumir_carga(cuerpo or {}, entrada.redact_extra),
            }
            return await emitir_vista_previa(tool, args, preview, cuerpo or {}, log_campos)

        ok, motivo, _ = await resolve_confirmation_token(confirmation_token, tool, args)
        if not ok:
            log(tool, "rejected:invalid_confirmation_token", **log_campos)
            return {"error": "invalid_confirmation_token", "detail": motivo}
        cabecera = {"method": metodo, "path": path, "route": ruta,
                    "category": entrada.category, "executed": True}
        resp, error = await ejecutar_supervisor(
            tool, metodo, path, ruta or "", entrada, cuerpo, cabecera, log_campos)
        if error is not None:
            await complete_confirmation_token(
                confirmation_token, success=False, error="supervisor_request_failed")
            return error
        await complete_confirmation_token(confirmation_token, result={"executed": True})
        log(tool, "executed", **log_campos)
        return resp
