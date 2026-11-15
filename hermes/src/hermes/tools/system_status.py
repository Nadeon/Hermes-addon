"""Hermes — estado del sistema de Core, de solo lectura (spec 029, CAP-043).

Cinco tools, familia `system_status`:

- `ha_get_system_health`: lo que enseña «Información del sistema» de HA
  (`system_health/info`), por dominio.
- `ha_get_system_state`: si HA o el host piden reinicio
  (`subscribe_system_state`).
- `ha_list_integration_setup_times`: cuánto tardó cada integración en
  arrancar (`integration/setup_info`).
- `ha_list_integration_manifests` y `ha_get_integration_manifest`: los
  manifiestos de las integraciones (`manifest/list` y `manifest/get`).

POR QUÉ ASÍ
-----------
Ninguna modifica nada ni pide token. Lo que tienen en común:

- Se valida la forma de cada argumento ANTES de llamar a HA (fail-closed): un
  argumento inválido nunca llega a Core.
- Toda respuesta pasa por `redact_structure` (claves sensibles) y por
  `redact_secrets` en cada texto: la salud del sistema y los manifiestos son
  textos libres de las integraciones, y un `token=…` o un JWT no llevan una
  clave que los delate.
- El tope de respuesta se aplica AQUÍ, con la forma de cada tool: las listas
  con el sobre común (`ajustar_lista_a_bytes`), la salud quitando dominios
  enteros (un dominio a medias engañaría) y un manifiesto suelto, entero o
  `response_too_large` (un manifiesto recortado por dentro sería falso).
- El texto de un manifiesto de una integración que no es de HA lo escribe un
  tercero: va marcado con `_third_party_text`, como en el Marketplace.
- El log lleva solo el nombre de la tool, el resultado y recuentos; nunca
  valores, URLs, direcciones ni nombres de integraciones (FR-019).
- Un `unknown_command` se traduce por su causa real (FR-020, principio V):
  `system_health/info` solo existe con `system_health:` cargado
  (`system_health_not_loaded`); los comandos de núcleo, por la versión de HA
  (`unsupported_by_ha_version`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import es_clave_sensible, REDACTED_MARKER, redact_secrets, tapar_entero
from hermes.tools._validation import es_numero_finito
from hermes.tools._common import (
    ajustar_lista_a_bytes,
    requires_ready,
    sobre_de_lista,
    tam_json,
)
from hermes.tools.marketplace import _third_party

logger = structlog.get_logger(__name__)

# La forma de un dominio de HA (y de una integración): la de `loader.py`.
_DOMINIO_RE = re.compile(r"[a-z0-9_]+")
_DOMINIO_MAX = 64

_SALUD_TIMEOUT_MIN = 1.0
_SALUD_TIMEOUT_MAX = 30.0
# Plazo propio de la confirmación de `system_health/info` (T038). HA no la
# manda hasta reunir la información rápida de TODOS los dominios, cada uno con
# su tope `INFO_CALLBACK_TIMEOUT` = 5 s (`components/system_health`): 10 s
# cubre ese tope con margen. `timeout_seconds` cuenta desde la confirmación y
# es la espera de los valores lentos, que es lo que la descripción promete.
_SALUD_CONFIRMACION_TIMEOUT = 10.0
# `subscribe_system_state` manda su estado en cuanto confirma: 10 s es de
# sobra y es el mismo plazo que las genéricas dan a una suscripción.
_ESTADO_TIMEOUT = 10.0

_LIMIT_MAX = 500
_MANIFIESTOS_MAX = 100

# Resumen fijo de un manifiesto (FR-005): lo que sirve para decidir sin
# gastar contexto en requisitos, propietarios o dependencias.
_CAMPOS_RESUMEN = (
    "domain", "name", "integration_type", "iot_class", "quality_scale",
    "version", "is_built_in", "overwrites_built_in", "config_flow",
    "documentation",
)
# Campos de texto que escribe el autor de una integración personalizada.
_TERCEROS_RESUMEN = ["name", "documentation"]
_TERCEROS_COMPLETO = ["name", "documentation", "issue_tracker", "codeowners"]

_PISTA_SALUD_RECORTADA = (
    "Whole domains were left out to fit response_max_bytes; ask for one of "
    "them with domain=<name>."
)


# ── Utilidades ───────────────────────────────────────────────────────────────

def _limpio(valor: Any, clave: str = "") -> Any:
    """`redact_structure` + `redact_secrets` en todos los textos (FR-018)."""
    # Bajo una clave sensible, el valor ENTERO, sea del tipo que sea (spec
    # 025, D-2): el mismo criterio que `redact_structure`.
    if clave and es_clave_sensible(clave) and tapar_entero(valor):
        return REDACTED_MARKER
    if isinstance(valor, Mapping):
        return {k: _limpio(v, str(k)) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_limpio(v, clave) for v in valor]
    if isinstance(valor, str):
        return redact_secrets(valor)
    return valor


def _es_dominio(valor: Any) -> bool:
    return (isinstance(valor, str) and 0 < len(valor) <= _DOMINIO_MAX
            and _DOMINIO_RE.fullmatch(valor) is not None)


def _es_numero(valor: Any) -> bool:
    # `bool` es un `int` en Python: `True` no es un número de segundos. Un
    # entero enorme tampoco (lanzaba `OverflowError`; cierre de la 1.2.0).
    return es_numero_finito(valor)


def _invalido(tool: str, campo: str, detalle: str) -> dict[str, Any]:
    logger.info(f"{tool}_failed", error="invalid_argument", field=campo)
    return {"error": "invalid_argument", "field": campo, "detail": detalle}


def _error_ha(tool: str, exc: HAConnectionError, *, sin_comando: str) -> dict[str, Any]:
    """Traduce un error de HA. `sin_comando` es el código para un
    `unknown_command`: `unsupported_by_ha_version` en los comandos de núcleo,
    `system_health_not_loaded` en el de la integración `system_health`."""
    detalle = redact_secrets(str(exc))
    if exc.code is None:
        # Sin código de HA es un fallo de conexión: el error de siempre.
        logger.info(f"{tool}_failed", error="connection")
        return {"error": detalle}
    logger.info(f"{tool}_failed", error=exc.code)
    if exc.code == "unknown_command":
        if sin_comando == "unsupported_by_ha_version":
            from hermes.command_table import TABLE_HA_CORE
            return {
                "error": "unsupported_by_ha_version",
                "detail": ("The installed Home Assistant does not know this command; "
                           f"Hermes' table is for {TABLE_HA_CORE}."),
                "ha_code": exc.code,
                "table_ha_core": TABLE_HA_CORE,
            }
        return {
            "error": sin_comando,
            "detail": ("The system_health integration is not loaded in Home Assistant "
                       "(it is part of default_config); add `system_health:` to "
                       "configuration.yaml to enable it."),
            "ha_code": exc.code,
        }
    return {"error": "ha_command_failed", "detail": detalle, "ha_code": exc.code}


# ── Salud del sistema ────────────────────────────────────────────────────────

def _es_fin(evento: Any) -> bool:
    return isinstance(evento, dict) and evento.get("type") == "finish"


def _valor(valor: Any) -> Any:
    """Las fechas de HA (`{"type": "date", "value": iso}`) como texto ISO."""
    if isinstance(valor, dict) and valor.get("type") == "date" and "value" in valor:
        return valor["value"]
    return valor


def _es_fallo(valor: Any) -> bool:
    """Un fallo que HA da como VALOR: `{"type": "failed", "error": …}`.

    HA lo usa en dos sitios que no son `success: false` (T036): el `healthy`
    y el `supported` de `hassio` con el Supervisor «Unhealthy» o
    «Unsupported» (en el inicial) y `async_check_can_reach_url` cuando no
    llega (en un `update` con `success: true`). La propia interfaz de HA los
    pinta como fallos; si Hermes no los listara en `failed`, un cliente que
    mire `failed` daría por sano un Supervisor enfermo (principio V).
    """
    return isinstance(valor, dict) and valor.get("type") == "failed"


def _fusionar_salud(eventos: list[Any]) -> tuple[dict[str, Any], list[str], list[str], int]:
    """El mensaje inicial con las actualizaciones aplicadas.

    Devuelve `(dominios, pendientes, fallidos, ignoradas)`. Un pendiente sin
    actualización sale como `None` y en `pendientes`; uno que HA dio por
    fallido (`success: false`), como `None` y en `fallidos`. Un valor que es
    un fallo de HA (`_es_fallo`), en el inicial o en una actualización, se
    deja tal cual (lleva el motivo) y también va en `fallidos`. Una
    actualización de algo que no estaba pendiente se ignora (y se cuenta):
    inventar la estructura sería afirmar algo que HA no dijo.
    """
    dominios: dict[str, Any] = {}
    pendientes: dict[tuple[str, str], None] = {}
    fallidos: list[str] = []
    ignoradas = 0
    for evento in eventos:
        if not isinstance(evento, dict):
            continue
        tipo = evento.get("type")
        if tipo == "initial" and isinstance(evento.get("data"), dict):
            for dominio, datos in evento["data"].items():
                if not isinstance(datos, dict):
                    continue
                info = datos.get("info")
                salida: dict[str, Any] = {}
                if (isinstance(info, dict) and set(info) == {"error"}
                        and isinstance(info["error"], dict)
                        and info["error"].get("type") == "failed"):
                    # El callback entero del dominio falló o venció en HA:
                    # se deja como lo da HA y el dominio va en `failed`.
                    salida["info"] = info
                    fallidos.append(f"{dominio}.*")
                elif isinstance(info, dict):
                    claves: dict[str, Any] = {}
                    for clave, valor in info.items():
                        if isinstance(valor, dict) and valor.get("type") == "pending":
                            pendientes[(dominio, clave)] = None
                            claves[clave] = None
                        else:
                            if _es_fallo(valor):
                                fallidos.append(f"{dominio}.{clave}")
                            claves[clave] = _valor(valor)
                    salida["info"] = claves
                else:
                    salida["info"] = info
                if "manage_url" in datos:
                    salida["manage_url"] = datos["manage_url"]
                dominios[dominio] = salida
        elif tipo == "update":
            par = (evento.get("domain"), evento.get("key"))
            if par not in pendientes:
                ignoradas += 1
                continue
            del pendientes[par]
            dominio, clave = par
            if evento.get("success") is True:
                dato = evento.get("data")
                if _es_fallo(dato):
                    fallidos.append(f"{dominio}.{clave}")
                dominios[dominio]["info"][clave] = _valor(dato)
            else:
                fallidos.append(f"{dominio}.{clave}")
    pend = [f"{d}.{k}" for d, k in pendientes]
    return dominios, pend, fallidos, ignoradas


def _de(lista: list[str], dominios: Mapping[str, Any]) -> list[str]:
    return [x for x in lista if x.split(".", 1)[0] in dominios]


def _recortar_salud(
    dominios: dict[str, Any], pendientes: list[str], fallidos: list[str],
    completo: bool, max_bytes: int,
) -> dict[str, Any] | None:
    """La respuesta de la salud dentro del tope, quitando dominios enteros
    por el final (orden de HA). `None` si ni el primero cabe solo."""
    nombres = list(dominios)

    def construir(n: int) -> dict[str, Any]:
        dentro = {k: dominios[k] for k in nombres[:n]}
        out: dict[str, Any] = {
            "complete": completo,
            "domains": dentro,
            "pending": _de(pendientes, dentro),
            "failed": _de(fallidos, dentro),
            "truncated": n < len(nombres),
        }
        if n < len(nombres):
            out["omitted_domains"] = nombres[n:]
            out["hint"] = _PISTA_SALUD_RECORTADA
        return out

    completa = construir(len(nombres))
    if tam_json(completa) <= max_bytes:
        return completa
    for n in range(len(nombres) - 1, 0, -1):
        out = construir(n)
        if tam_json(out) <= max_bytes:
            return out
    return None


# ── Registro ─────────────────────────────────────────────────────────────────

def register(mcp: Any, ha_client: HAClient, *, response_max_bytes: int) -> None:
    """Registra las cinco tools de la familia `system_status`."""
    ready = requires_ready(ha_client)

    def demasiado_grande(tool: str, tam: int) -> dict[str, Any]:
        logger.info(f"{tool}_failed", error="response_too_large")
        return {
            "error": "response_too_large",
            "detail": (f"The response ({tam} bytes) exceeds response_max_bytes "
                       f"({response_max_bytes}) and cannot be cut without "
                       "misrepresenting it."),
        }

    @mcp.tool()
    @ready
    async def ha_get_system_health(
        domain: str | None = None, timeout_seconds: float = 10,
    ) -> object:
        """Read Home Assistant's system health report (what Settings > System > Repairs > System information shows), per domain.

        Read only: it changes nothing, but some of Home Assistant's checks
        (Home Assistant Cloud, the Marketplace and other integrations) make
        Home Assistant contact internet services to see if they are
        reachable. Each domain (homeassistant, cloud,
        hassio, recorder and any integration that reports health) comes with
        its `info` and, when Home Assistant gives one, its `manage_url`.
        Slow values are awaited up to `timeout_seconds`; the ones that did not
        arrive are null and listed in `pending` as `<domain>.<key>`
        (`complete: false`), and the ones Home Assistant reported as failed
        are listed in `failed` (a value Home Assistant gives as
        `{type: failed, error}`, such as an unhealthy Supervisor or a service
        it cannot reach, is kept with its reason). Dates come as ISO text. If the report does not
        fit in the response size limit, whole domains are left out from the
        end and named in `omitted_domains` (`truncated: true`): ask for one
        with `domain`.

        Args:
            domain: Only this domain, e.g. "homeassistant" (lowercase letters,
                digits and '_').
            timeout_seconds: Total wait for slow values, 1-30 (default 10),
                counted once Home Assistant has gathered the fast ones (which
                can take it up to about 5 s).

        Returns:
            {complete, domains: {<domain>: {info, manage_url?}}, pending,
            failed, truncated, omitted_domains?}. Secrets in the values are
            redacted. Errors: invalid_argument, domain_not_found (with the
            available domains), system_health_not_loaded.
        """
        tool = "ha_get_system_health"
        if domain is not None and not _es_dominio(domain):
            return _invalido(tool, "domain",
                             "domain must be a Home Assistant domain such as "
                             "'homeassistant' (lowercase letters, digits and '_').")
        if (not _es_numero(timeout_seconds)
                or not _SALUD_TIMEOUT_MIN <= timeout_seconds <= _SALUD_TIMEOUT_MAX):
            return _invalido(tool, "timeout_seconds",
                             "timeout_seconds must be a number between 1 and 30.")
        try:
            eventos, completo = await ha_client.ws_collect_subscription(
                {"type": "system_health/info"}, terminado=_es_fin,
                timeout_seconds=float(timeout_seconds),
                confirmacion_timeout_seconds=_SALUD_CONFIRMACION_TIMEOUT)
        except HAConnectionError as exc:
            return _error_ha(tool, exc, sin_comando="system_health_not_loaded")

        dominios, pendientes, fallidos, ignoradas = _fusionar_salud(eventos)
        if domain is not None:
            if domain not in dominios:
                logger.info(f"{tool}_failed", error="domain_not_found",
                            domains=len(dominios))
                return {"error": "domain_not_found",
                        "detail": "Home Assistant reports no health for that domain.",
                        "available_domains": sorted(dominios)}
            dominios = {domain: dominios[domain]}
            pendientes = _de(pendientes, dominios)
            fallidos = _de(fallidos, dominios)
            # Con `domain`, `complete` es el de ESE dominio (T039): sin
            # `finish` porque otro seguía pendiente, el pedido puede estar
            # entero, y decir `complete: false` con `pending: []` se
            # contradice. Sus pendientes ya están filtrados arriba.
            completo = True

        dominios = _limpio(dominios)
        out = _recortar_salud(dominios, pendientes, fallidos,
                              completo and not pendientes, response_max_bytes)
        if out is None:
            return demasiado_grande(tool, tam_json(dominios))
        logger.info(
            f"{tool}_ok", domains=len(out["domains"]), pending=len(out["pending"]),
            failed=len(out["failed"]), ignored_updates=ignoradas,
            complete=out["complete"], truncated=out["truncated"],
            omitted_domains=len(out.get("omitted_domains", ())),
        )
        return out

    @mcp.tool()
    @ready
    async def ha_get_system_state() -> object:
        """Read whether Home Assistant or the host needs a restart, and why.

        Read only: it does not dismiss the notice. To restart Home Assistant
        use `sv_restart_core` (it checks the configuration first).

        Returns:
            {home_assistant_restart_required, home_assistant_restart_sources,
            home_assistant_restart_dismissed, host_reboot_required,
            host_reboot_dismissed} as Home Assistant reports them. Error
            unsupported_by_ha_version on a Home Assistant without this command.
        """
        tool = "ha_get_system_state"
        try:
            estado = await ha_client.ws_one_shot_subscription(
                {"type": "subscribe_system_state"}, event_timeout_seconds=_ESTADO_TIMEOUT)
        except HAConnectionError as exc:
            return _error_ha(tool, exc, sin_comando="unsupported_by_ha_version")
        out = _limpio(estado if isinstance(estado, dict) else {})
        logger.info(
            f"{tool}_ok",
            restart_required=out.get("home_assistant_restart_required"),
            restart_sources=len(out.get("home_assistant_restart_sources") or ()),
            host_reboot_required=out.get("host_reboot_required"),
        )
        return out

    @mcp.tool()
    @ready
    async def ha_list_integration_setup_times(
        limit: int = 50, min_seconds: float | None = None,
    ) -> object:
        """List how many seconds each integration took to set up at the last Home Assistant start, slowest first.

        Read only. `total` and `total_seconds` count every integration, not
        only the ones returned.

        Args:
            limit: Maximum integrations returned, 1-500 (default 50).
            min_seconds: Only integrations that took at least this long (>= 0).

        Returns:
            {total, total_seconds, count, items: [{domain, seconds}],
            truncated}. `truncated` is true when `limit` or the response
            size limit left out integrations that pass `min_seconds`.
        """
        tool = "ha_list_integration_setup_times"
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= _LIMIT_MAX:
            return _invalido(tool, "limit", "limit must be an integer between 1 and 500.")
        if min_seconds is not None and (not _es_numero(min_seconds) or min_seconds < 0):
            return _invalido(tool, "min_seconds", "min_seconds must be a number >= 0.")
        try:
            bruto = await ha_client.ws_send({"type": "integration/setup_info"})
        except HAConnectionError as exc:
            return _error_ha(tool, exc, sin_comando="unsupported_by_ha_version")

        filas = [
            {"domain": f.get("domain"), "seconds": float(f["seconds"])}
            for f in (bruto if isinstance(bruto, list) else [])
            if isinstance(f, dict) and _es_numero(f.get("seconds"))
        ]
        filas.sort(key=lambda f: (-f["seconds"], str(f["domain"])))
        total = len(filas)
        total_seconds = round(sum(f["seconds"] for f in filas), 3)
        if min_seconds is not None:
            filas = [f for f in filas if f["seconds"] >= min_seconds]
        por_limite = len(filas) > limit
        items = [{"domain": f["domain"], "seconds": round(f["seconds"], 3)}
                 for f in filas[:limit]]

        # Sobre común de las listas nuevas de la 1.2.0 (spec 018, FR-014):
        # misma forma que el resto, con los totales como cabecera.
        def construir(xs: list[Any], recortada: bool) -> dict[str, Any]:
            return sobre_de_lista(xs, truncated=recortada or por_limite,
                                  total=total, total_seconds=total_seconds)

        out = ajustar_lista_a_bytes(_limpio(items), construir, response_max_bytes)
        logger.info(f"{tool}_ok", count=out["count"], total=total,
                    truncated=out["truncated"])
        return out

    @mcp.tool()
    @ready
    async def ha_list_integration_manifests(
        integrations: list[str] | None = None, custom_only: bool = False,
    ) -> object:
        """List a fixed summary of integration manifests: the loaded integrations, or the ones named.

        Read only. Ten fields per integration (domain, name, integration_type,
        iot_class, quality_scale, version, is_built_in, overwrites_built_in,
        config_flow, documentation; missing ones are null), sorted by domain.
        Integrations that are not part of Home Assistant (custom ones) carry
        `_third_party_text`: their text is written by third parties. For the
        whole manifest (requirements, dependencies, codeowners...) use
        `ha_get_integration_manifest`.

        Args:
            integrations: Up to 100 integration domains; without it, the
                loaded integrations.
            custom_only: Only integrations that are not part of Home Assistant.

        Returns:
            {missing, count, items, truncated}. `missing` lists the requested
            integrations Home Assistant did not return (unknown or failing to
            load); `truncated` is true when the response size limit cut the
            list.
        """
        tool = "ha_list_integration_manifests"
        pedidas: list[str] | None = None
        if integrations is not None:
            if (not isinstance(integrations, list) or len(integrations) > _MANIFIESTOS_MAX
                    or not all(_es_dominio(x) for x in integrations)):
                return _invalido(tool, "integrations",
                                 "integrations must be a list of up to 100 integration "
                                 "domains (lowercase letters, digits and '_').")
            pedidas = list(dict.fromkeys(integrations))
        if not isinstance(custom_only, bool):
            return _invalido(tool, "custom_only", "custom_only must be true or false.")
        mensaje: dict[str, Any] = {"type": "manifest/list"}
        if pedidas:
            mensaje["integrations"] = pedidas
        try:
            bruto = await ha_client.ws_send(mensaje)
        except HAConnectionError as exc:
            return _error_ha(tool, exc, sin_comando="unsupported_by_ha_version")

        manifiestos = [m for m in (bruto if isinstance(bruto, list) else [])
                       if isinstance(m, dict)]
        devueltas = {m.get("domain") for m in manifiestos}
        missing = [d for d in (pedidas or []) if d not in devueltas]
        items = []
        for m in sorted(manifiestos, key=lambda m: str(m.get("domain"))):
            resumen: dict[str, Any] = {c: m.get(c) for c in _CAMPOS_RESUMEN}
            # Fail-closed: lo que HA no marca como suyo es de terceros.
            if resumen["is_built_in"] is not True:
                resumen["_third_party_text"] = _third_party(_TERCEROS_RESUMEN)
            elif custom_only:
                continue
            items.append(resumen)

        # Sobre común de las listas nuevas de la 1.2.0 (spec 018, FR-014),
        # con `missing` como cabecera.
        def construir(xs: list[Any], recortada: bool) -> dict[str, Any]:
            return sobre_de_lista(xs, truncated=recortada, missing=missing)

        out = ajustar_lista_a_bytes(_limpio(items), construir, response_max_bytes)
        logger.info(f"{tool}_ok", count=out["count"], missing=len(missing),
                    custom=sum(1 for x in out["items"] if "_third_party_text" in x),
                    truncated=out["truncated"])
        return out

    @mcp.tool()
    @ready
    async def ha_get_integration_manifest(integration: str) -> object:
        """Read the full manifest of one integration (dependencies, requirements, version, codeowners, documentation...).

        Read only. If the integration is not part of Home Assistant, its text
        is written by third parties and the answer carries
        `_third_party_text`.

        Args:
            integration: The integration domain, e.g. "input_boolean".

        Returns:
            The manifest as Home Assistant gives it (with is_built_in and
            overwrites_built_in). Errors: invalid_argument,
            integration_not_found, response_too_large.
        """
        tool = "ha_get_integration_manifest"
        if not _es_dominio(integration):
            return _invalido(tool, "integration",
                             "integration must be an integration domain such as "
                             "'input_boolean' (lowercase letters, digits and '_').")
        try:
            bruto = await ha_client.ws_send({"type": "manifest/get", "integration": integration})
        except HAConnectionError as exc:
            if exc.code == "not_found":
                logger.info(f"{tool}_failed", error="integration_not_found")
                return {"error": "integration_not_found",
                        "detail": "Home Assistant does not know this integration."}
            return _error_ha(tool, exc, sin_comando="unsupported_by_ha_version")
        out = _limpio(bruto if isinstance(bruto, dict) else {})
        tercero = out.get("is_built_in") is not True
        if tercero:
            out["_third_party_text"] = _third_party(_TERCEROS_COMPLETO)
        tam = tam_json(out)
        if tam > response_max_bytes:
            return demasiado_grande(tool, tam)
        logger.info(f"{tool}_ok", third_party=tercero, keys=len(out))
        return out
