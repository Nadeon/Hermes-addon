"""Hermes — Tools MCP de la red y el servidor HTTP de Core (spec 021, tramo c).

Tres tools de la familia `core_network` (CAP-069 de la 008). No es la red del
host (eso es el Supervisor, spec 032): aquí solo se toca lo que guarda Core.

- `ha_update_network_config`: qué adaptadores usa HA para descubrir
  dispositivos y qué direcciones anuncia (`network/configure`).
- `ha_update_http_config`: la configuración del servidor HTTP (puerto, SSL,
  proxy inverso, bloqueo de IP...) por `http/config/configure`.
- `ha_promote_http_config`: confirma la configuración HTTP de prueba
  (`http/config/promote`).

POR QUÉ SE FUNDE Y SE MANDA EL DOCUMENTO ENTERO
-----------------------------------------------
`http/config/configure` no acepta un parche: valida un documento completo con
`HTTP_STORAGE_SCHEMA` y rellena por defecto lo que falta (puerto, CORS, bloqueo
de IP...). Mandar solo lo cambiado devolvería al valor por defecto todo lo
demás. Se funde sobre la configuración con la que HA está funcionando
(`active_config_type`: estable, pendiente o por defecto), se quitan los
metadatos que HA guarda pero no admite (`created_at`, `error`,
`error_message`) y se manda el resultado, que es lo que enseña la vista
previa.

POR QUÉ REINICIO Y PRUEBA DE 5 MINUTOS
--------------------------------------
HA guarda lo nuevo como pendiente y reinicia. Arranca con lo pendiente y, si
nadie lo promueve en 5 minutos (`AUTO_REVERT_DELAY`) o no se puede aplicar,
vuelve a lo estable y reinicia otra vez. Promover lo convierte en la
configuración de recuperación. Por eso todo confirma y la vista previa avisa
de cada cambio que puede dejar HA inaccesible.

POR QUÉ SE RECHAZA UN `server_host` SIN EL SUPERVISOR (D-3, fail-closed)
------------------------------------------------------------------------
Core corre con la red del host y el Supervisor le llega por la pasarela de su
red interna de Docker (`hassio`, 172.30.32.0/23): `api_url` del Supervisor es
`http://172.30.32.1:<puerto>` (`DOCKER_IPV4_NETWORK_MASK[1]`, IPv4). Hermes y
todas las apps entran a Core a través del Supervisor. Si Core deja de escuchar
en esa dirección, todos se quedan fuera. Solo valen `0.0.0.0` (todas las IPv4)
o la propia `172.30.32.1`. `::` sola NO vale: HA enlaza con
`loop.create_server`, que pone `IPV6_V6ONLY` en los sockets IPv6, así que `::`
no acepta conexiones IPv4. Sin `server_host`, HA escucha en `0.0.0.0` y `::`.

POR QUÉ EL PUERTO NO CORTA A HERMES
-----------------------------------
Al arrancar, la integración `hassio` de Core le dice al Supervisor el puerto y
el SSL (`update_hass_api`), y el Supervisor no verifica el certificado de Core
(`ssl=False`). Un puerto o un certificado nuevo no dejan fuera a Hermes; sí a
las URLs, apps, proxies y redirecciones que usen el puerto o el esquema viejos.

POR QUÉ EL BLOQUEO DE REINICIO
------------------------------
Aplicar reinicia HA. Si Hermes escribió configuración sin validarla después,
`sv_restart_core` se niega hasta `sv_check_core_config`; esta tool hace lo
mismo (`fs_write.check_restart_allowed_sync`), en la vista previa y al
confirmar.

PRIVACIDAD (principio VIII)
---------------------------
Puertos, hosts, rutas de certificados, proxies y nombres de adaptador
describen la red de la casa: el log solo lleva nombres de claves y recuentos.
"""

from __future__ import annotations

import ipaddress
from typing import Any

import structlog

from hermes.fs_write import check_restart_allowed_sync
from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    ESTADO_CAMBIADO,
    complete_confirmation_token,
    create_confirmation_token,
    redact_secrets,
    redact_structure,
    resolve_confirmation_token,
)
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)

_MAX_ADAPTADORES = 32
_MAX_LISTA = 64

# Claves de `HTTP_STORAGE_SCHEMA` (http/config.py de Core 2026.11.1) y el tipo
# básico de cada una. El resto (rutas que existan, redes IP válidas, perfiles
# SSL) lo valida HA antes de guardar nada (`invalid_format`).
_CLAVES_HTTP: dict[str, str] = {
    "server_host": "hosts",
    "server_port": "port",
    "ssl_certificate": "path",
    "ssl_peer_certificate": "path",
    "ssl_key": "path",
    "cors_allowed_origins": "str_list",
    "use_x_forwarded_for": "bool",
    "trusted_proxies": "str_list",
    "login_attempts_threshold": "threshold",
    "ip_ban_enabled": "bool",
    "ssl_profile": "str",
    "use_x_frame_options": "bool",
}
_META = ("created_at", "error", "error_message")

# La pasarela de la red interna del Supervisor: por donde llega a Core (ver
# el docstring). Red completa, para el mensaje.
_RED_SUPERVISOR = ipaddress.ip_network("172.30.32.0/23")
_PASARELA_SUPERVISOR = ipaddress.ip_address("172.30.32.1")
_TODAS_IPV4 = ipaddress.ip_address("0.0.0.0")

_REINICIO = (
    "Home Assistant restarts to apply this. It runs the new configuration on "
    "trial: if nobody promotes it with ha_promote_http_config within 5 minutes, "
    "or if it fails to start, Home Assistant goes back to the stable "
    "configuration and restarts again."
)
_RIESGO_ACCESO = (
    "WARNING: this change can leave Home Assistant unreachable from browsers, the "
    "mobile apps, a reverse proxy or remote access. Before confirming, make sure "
    "the user can reach Home Assistant with the new settings. If nobody can, "
    "Home Assistant goes back to the stable configuration by itself 5 minutes "
    "after the restart (it is not promoted). Hermes keeps access through the "
    "Supervisor."
)
_SIGUIENTE = (
    "Check that Home Assistant works with the new configuration (browser, apps, "
    "proxy) and promote it with ha_promote_http_config within 5 minutes of the "
    "restart; otherwise it goes back to the stable configuration."
)
_CONFIG_CHECK = (
    "If configuration.yaml is invalid, Home Assistant refuses to restart: the "
    "new configuration stays pending and applies on the next restart. Validate "
    "with sv_check_core_config."
)

# Avisos (código y texto en inglés). `acceso` marca los que pueden dejar HA
# inaccesible y activan `access_risk` en la vista previa.
_AVISOS_HTTP: dict[str, tuple[str, bool]] = {
    "port": ("The port changes: URLs, bookmarks, the mobile apps, port forwards "
             "and reverse proxies that use the old port stop working until they "
             "are updated (internal_url and external_url too). The Supervisor "
             "learns the new port when Home Assistant starts.", True),
    "server_host": ("Home Assistant will only listen on these addresses: devices "
                    "that reach it through other addresses or networks lose access. "
                    "The Supervisor's address is included, so Hermes and the apps "
                    "keep working.", True),
    "ssl": ("Certificate settings change. With a certificate, HTTPS is mandatory "
            "and http:// stops working; a certificate browsers or the apps do not "
            "accept, or a missing file, blocks access. With ssl_peer_certificate, "
            "clients without a valid client certificate cannot connect.", True),
    "reverse_proxy": ("Reverse proxy settings change. With use_x_forwarded_for, "
                      "requests that carry X-Forwarded-For from an address not in "
                      "trusted_proxies are rejected: a wrong list blocks access "
                      "through the proxy (remote access, tunnels, the add-on "
                      "proxies).", True),
    "ip_ban": ("Login ban settings change. After login_attempts_threshold failed "
               "logins the client's IP is banned (ip_bans.yaml). Behind a proxy "
               "that is not trusted, every client shares the proxy's IP and one ban "
               "locks everybody out.", True),
    "ssl_profile": ("The SSL profile changes: a stricter profile rejects older "
                    "browsers, apps and devices.", True),
    "cors": ("The web origins allowed to call the API from a browser change.", False),
    "x_frame_options": ("Whether other sites can embed Home Assistant in a frame "
                        "changes.", False),
    "pending_replaced": ("There is already a pending (unpromoted) configuration: "
                         "this one replaces it.", False),
}
_GRUPO_HTTP: dict[str, str] = {
    "server_port": "port",
    "server_host": "server_host",
    "ssl_certificate": "ssl", "ssl_key": "ssl", "ssl_peer_certificate": "ssl",
    "use_x_forwarded_for": "reverse_proxy", "trusted_proxies": "reverse_proxy",
    "ip_ban_enabled": "ip_ban", "login_attempts_threshold": "ip_ban",
    "ssl_profile": "ssl_profile",
    "cors_allowed_origins": "cors",
    "use_x_frame_options": "x_frame_options",
}
_ORDEN_AVISOS = ("port", "server_host", "ssl", "reverse_proxy", "ip_ban",
                 "ssl_profile", "cors", "x_frame_options")

_EXPLICACIONES = {
    "bind_failed": ("Home Assistant could not bind the new address or port (in use "
                    "or not available on this machine); nothing was saved."),
    "not_running": ("Home Assistant is still starting or stopping; the HTTP "
                    "configuration can only change while it is running."),
    "invalid_format": ("Home Assistant rejected the configuration (for example a "
                       "certificate file that does not exist or an invalid proxy "
                       "network); nothing was saved."),
    "not_allowed": "Home Assistant has no pending configuration it can promote.",
}


def _check_restart_allowed() -> tuple[bool, str]:
    """El bloqueo de `sv_restart_core` (los tests lo sustituyen)."""
    return check_restart_allowed_sync()


def _invalido(tool: str, campo: str, detalle: str, **extra: Any) -> dict[str, Any]:
    logger.info(f"{tool}_failed", error="invalid_argument", field=campo)
    return {"error": "invalid_argument", "field": campo, "detail": detalle, **extra}


def _error_ha(tool: str, exc: HAConnectionError, **log: Any) -> dict[str, Any]:
    """Error de HA redactado y traducido (FR-020)."""
    logger.warning(f"{tool}_failed", error=exc.code or "connection", **log)
    detalle = redact_secrets(str(exc))
    if exc.code is None:
        return {"error": detalle}
    if exc.code == "unknown_command":
        from hermes.command_table import TABLE_HA_CORE
        return {
            "error": "unsupported_by_ha_version",
            "detail": ("The installed Home Assistant does not know this command "
                       "(the HTTP configuration in storage is new in 2026.11); "
                       f"Hermes' table is for {TABLE_HA_CORE}."),
            "ha_code": exc.code,
            "table_ha_core": TABLE_HA_CORE,
        }
    out: dict[str, Any] = {"error": "ha_error", "ha_code": exc.code, "detail": detalle}
    if exc.code in _EXPLICACIONES:
        out["explanation"] = _EXPLICACIONES[exc.code]
    return out


def _no_disponible(tool: str, exc: HAConnectionError) -> dict[str, Any]:
    if exc.code == "unknown_command":
        return _error_ha(tool, exc, step="preview")
    logger.warning(f"{tool}_failed", error="preview_unavailable",
                   code=exc.code or "connection")
    return {"error": "preview_unavailable",
            "detail": "Hermes could not read the current configuration; nothing was "
                      "done. " + redact_secrets(str(exc))}


def _token_fallido(tool: str, error: str) -> dict[str, Any]:
    logger.warning(f"{tool}_failed", step="confirm",
                   error="state_changed" if error == ESTADO_CAMBIADO else "token_invalid")
    return {"error": error}


def _bloqueado(tool: str, motivo: str, step: str) -> dict[str, Any]:
    logger.warning(f"{tool}_failed", step=step, error="restart_blocked")
    return {"error": "restart_blocked",
            "detail": ("Applying this restarts Home Assistant, and Hermes has written "
                       "configuration that was not validated since. Call "
                       "sv_check_core_config first, then retry. " + motivo)}


# ── Red ───────────────────────────────────────────────────────────────────────


def _habilitados(adaptadores: list[dict[str, Any]], configurados: list[str]) -> list[str]:
    """Los adaptadores que HA habilitaría con `configurados` (`network/util.py`).

    Si la lista está vacía o ningún nombre casa, HA habilita los detectados
    automáticamente (`auto`).
    """
    nombres = [a["name"] for a in adaptadores if a.get("name") in configurados]
    if not nombres:
        nombres = [a["name"] for a in adaptadores if a.get("auto")]
    return sorted(nombres)


async def _leer_red(ha_client: HAClient) -> tuple[list[dict[str, Any]], list[str]]:
    raw = await ha_client.ws_send({"type": "network"})
    if not isinstance(raw, dict):
        raise HAConnectionError("unexpected response from network: not an object")
    adaptadores = [a for a in raw.get("adapters") or []
                   if isinstance(a, dict) and isinstance(a.get("name"), str)]
    configurados = [c for c in raw.get("configured_adapters") or [] if isinstance(c, str)]
    return adaptadores, configurados


# ── HTTP ──────────────────────────────────────────────────────────────────────


def _sin_meta(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict):
        return {}
    return {k: v for k, v in doc.items() if k not in _META}


def _base_activa(http: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """`(nombre, documento)` con el que HA está funcionando, sin metadatos."""
    tipo = http.get("active_config_type")
    if tipo == "stable" and isinstance(http.get("stable"), dict):
        return "stable", _sin_meta(http["stable"])
    if tipo == "pending" and isinstance(http.get("pending"), dict):
        return "pending", _sin_meta(http["pending"])
    if tipo in ("default", "default_legacy_port") and isinstance(http.get("default"), dict):
        doc = _sin_meta(http["default"])
        if tipo == "default_legacy_port":
            # HA cayó al puerto por defecto de antes (8123) porque no pudo
            # enlazar el por defecto del Supervisor (`_DEFAULT_CONFIG_LEGACY_PORT`).
            doc["server_port"] = 8123
        return tipo, doc
    return None


def _efectivo(doc: dict[str, Any], defecto: dict[str, Any], clave: str) -> Any:
    """El valor con que HA funcionaría: el del documento o el por defecto."""
    return doc[clave] if clave in doc else defecto.get(clave)


def _diff(antes: dict[str, Any], despues: dict[str, Any],
          defecto: dict[str, Any]) -> dict[str, dict[str, Any]]:
    claves = sorted((set(antes) | set(despues)) & set(_CLAVES_HTTP))
    out = {}
    for k in claves:
        a, d = _efectivo(antes, defecto, k), _efectivo(despues, defecto, k)
        if a != d:
            out[k] = {"before": a, "after": d}
    return out


def _es_texto(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip()) and not any(c in v for c in "\n\r\t")


def _validar_http(changes: Any) -> tuple[str, str] | None:
    """`(campo, detalle)` del primer valor que no vale, o `None`."""
    for clave, valor in changes.items():
        tipo = _CLAVES_HTTP.get(clave)
        if tipo is None:
            return clave, ("unknown key; valid keys: " + ", ".join(sorted(_CLAVES_HTTP)))
        if valor is None:
            continue  # quita la clave: HA usa su valor por defecto
        if tipo == "bool" and not isinstance(valor, bool):
            return clave, "must be true or false (or null to remove it)"
        if tipo == "port" and (not isinstance(valor, int) or isinstance(valor, bool)
                               or not 1 <= valor <= 65535):
            return clave, "must be an integer port between 1 and 65535"
        if tipo == "threshold" and (not isinstance(valor, int) or isinstance(valor, bool)
                                    or not (valor >= 1 or valor == -1)):
            return clave, "must be an integer >= 1, or -1 to never ban"
        if tipo in ("path", "str") and not _es_texto(valor):
            return clave, "must be a non-empty text (or null to remove it)"
        if tipo in ("hosts", "str_list"):
            if (not isinstance(valor, list) or len(valor) > _MAX_LISTA
                    or not all(_es_texto(x) for x in valor)):
                return clave, f"must be a list of at most {_MAX_LISTA} non-empty texts"
            if tipo == "hosts" and not valor:
                return clave, "must not be empty; use null to listen on every address"
    return None


def _supervisor_llega(hosts: Any) -> bool:
    """Si Core seguiría escuchando donde le llega el Supervisor (D-3)."""
    if hosts is None:
        return True  # sin server_host, HA escucha en 0.0.0.0 y ::
    for h in hosts if isinstance(hosts, list) else [hosts]:
        try:
            ip = ipaddress.ip_address(str(h).strip())
        except ValueError:
            continue  # un nombre: no se sabe a qué resuelve (fail-closed)
        if ip in (_TODAS_IPV4, _PASARELA_SUPERVISOR):
            return True
    return False


_SIN_SUPERVISOR = (
    "server_host must let the Supervisor reach Home Assistant. Home Assistant "
    "runs on the host network and the Supervisor, through which Hermes and every "
    "app reach it, calls it from its internal Docker network "
    f"({_RED_SUPERVISOR}) at the gateway {_PASARELA_SUPERVISOR} over IPv4. "
    "Include \"0.0.0.0\" (every IPv4 address) or \"172.30.32.1\". \"::\" alone "
    "does not accept IPv4 connections, and a host name cannot be checked. "
    "Nothing was done."
)


async def _leer_http(ha_client: HAClient) -> dict[str, Any]:
    raw = await ha_client.ws_send({"type": "http/config"})
    if not isinstance(raw, dict):
        raise HAConnectionError("unexpected response from http/config: not an object")
    return raw


def _estado_http(http: dict[str, Any]) -> dict[str, Any]:
    """Lo que ata el token: las dos ranuras y con cuál funciona HA."""
    return {k: http.get(k) for k in ("stable", "pending", "active_config_type")}


def register(mcp: object, ha_client: HAClient, *, response_max_bytes: int) -> None:
    """Registra las tools de la red y el HTTP de Core."""

    ready = requires_ready(ha_client)
    del response_max_bytes  # respuestas pequeñas: un documento de doce claves

    # ── ha_update_network_config ──────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_update_network_config(
        configured_adapters: list[str],
        confirmation_token: str | None = None,
    ) -> object:
        """Choose which network adapters Home Assistant uses (Settings > System > Network).

        Sets the adapters Home Assistant uses to discover devices (zeroconf,
        SSDP...) and the addresses it announces. An empty list means automatic
        detection. It does NOT change the address or port Home Assistant
        listens on (that is ha_update_http_config). Two steps: without
        confirmation_token returns a preview (configured and enabled adapters
        before and after) and a token; repeat the same call with the token to
        apply. To read the adapters first: ha_read_ws_command(type="network").

        Args:
            configured_adapters: Adapter names as Home Assistant reports them
                (0 to 32, no repeats); [] = automatic.
            confirmation_token: Token from the preview call.

        Returns:
            Preview + token; {"result": "ok", "configured_adapters": [...]};
            {"result": "no_changes"}; or {"error": ...} (invalid_argument with
            the available adapters if a name does not exist).
        """
        tool = "ha_update_network_config"
        if (not isinstance(configured_adapters, list)
                or not all(isinstance(n, str) and n for n in configured_adapters)):
            return _invalido(tool, "configured_adapters", "must be a list of adapter names")
        if len(configured_adapters) > _MAX_ADAPTADORES:
            return _invalido(tool, "configured_adapters",
                             f"at most {_MAX_ADAPTADORES} adapters")
        if len(set(configured_adapters)) != len(configured_adapters):
            return _invalido(tool, "configured_adapters", "repeated adapter names")
        args = {"configured_adapters": configured_adapters}

        try:
            adaptadores, actuales = await _leer_red(ha_client)
        except HAConnectionError as exc:
            return _no_disponible(tool, exc)
        disponibles = sorted(a["name"] for a in adaptadores)
        faltan = sorted(n for n in configured_adapters if n not in disponibles)
        if faltan:
            return _invalido(tool, "configured_adapters",
                             "unknown adapters: " + ", ".join(faltan),
                             available=disponibles)
        antes = _habilitados(adaptadores, actuales)
        despues = _habilitados(adaptadores, configured_adapters)
        estado = {"configured_adapters": actuales, "enabled": antes,
                  "adapters": disponibles}

        if not confirmation_token:
            if set(configured_adapters) == set(actuales):
                logger.info(f"{tool}_ok", step="preview", result="no_changes")
                return {"result": "no_changes"}
            preview = {
                "action": "update_network_config",
                "configured_adapters": {"before": actuales, "after": configured_adapters},
                "enabled": {"before": antes, "after": despues},
                "note": ("Changes discovery and the addresses Home Assistant "
                         "announces; it does not change the address or port Home "
                         "Assistant listens on."),
            }
            logger.info(f"{tool}_ok", step="preview", count=len(configured_adapters))
            return await create_confirmation_token(tool, args, preview=preview, estado=estado)

        valido, error, _ = await resolve_confirmation_token(
            confirmation_token, tool, args, estado=estado)
        if not valido:
            return _token_fallido(tool, error)
        try:
            resp = await ha_client.ws_send({
                "type": "network/configure",
                "config": {"configured_adapters": configured_adapters},
            })
        except HAConnectionError as exc:
            fallo = _error_ha(tool, exc, step="confirm")
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(fallo.get("error")))
            return fallo
        guardados = (resp.get("configured_adapters") if isinstance(resp, dict)
                     else None)
        if not isinstance(guardados, list):
            guardados = configured_adapters
        await complete_confirmation_token(
            confirmation_token, success=True, result={"result": "ok"})
        logger.info(f"{tool}_ok", step="confirm", count=len(guardados))
        return {"result": "ok", "configured_adapters": guardados}

    # ── ha_update_http_config ─────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_update_http_config(
        changes: dict[str, Any] | None = None,
        discard_pending: bool = False,
        confirmation_token: str | None = None,
    ) -> object:
        """Change Home Assistant's HTTP server configuration (port, SSL, reverse proxy, login bans).

        Pass either changes or discard_pending=true. changes are merged onto
        the configuration Home Assistant is running with (null removes a key,
        so Home Assistant uses its default) and the whole resulting document
        is sent. Two steps: without confirmation_token returns a preview (the
        resulting document, the diff, access-loss warnings) and a token;
        repeat the same call with the token to apply. Applying RESTARTS Home
        Assistant and runs the new configuration on trial: promote it with
        ha_promote_http_config within 5 minutes or Home Assistant goes back
        to the stable one. A server_host that leaves out the Supervisor
        (and with it Hermes and every app) is rejected. Refused while Hermes'
        restart block is on (call sv_check_core_config first). To read:
        ha_read_ws_command(type="http/config").

        Args:
            changes: Keys of the HTTP configuration: server_host (list),
                server_port, ssl_certificate, ssl_peer_certificate, ssl_key,
                cors_allowed_origins (list), use_x_forwarded_for,
                trusted_proxies (list of IPs or networks),
                login_attempts_threshold (-1 = never ban), ip_ban_enabled,
                ssl_profile, use_x_frame_options. null removes a key.
            discard_pending: True to drop a pending (unpromoted)
                configuration; Home Assistant restarts with the stable one.
            confirmation_token: Token from the preview call.

        Returns:
            Preview + token; {"result": "ok", "restart", "next",
            "config_check"}; {"result": "no_changes"}; or {"error": ...}.
        """
        tool = "ha_update_http_config"
        if not isinstance(discard_pending, bool):
            return _invalido(tool, "discard_pending", "must be true or false")
        if changes is not None and not isinstance(changes, dict):
            return _invalido(tool, "changes", "must be an object")
        if bool(changes) == discard_pending:
            return _invalido(tool, "changes",
                             "give either a non-empty changes object or "
                             "discard_pending=true, not both")
        if changes:
            mal = _validar_http(changes)
            if mal is not None:
                return _invalido(tool, *mal)
        args = {"changes": changes, "discard_pending": discard_pending}
        claves = sorted(changes or {})

        permitido, motivo = _check_restart_allowed()
        if not permitido and not confirmation_token:
            return _bloqueado(tool, motivo, "preview")

        try:
            http = await _leer_http(ha_client)
        except HAConnectionError as exc:
            return _no_disponible(tool, exc)
        pendiente = http.get("pending")
        defecto = _sin_meta(http.get("default"))

        if discard_pending:
            if pendiente is None:
                logger.info(f"{tool}_ok", step="preview", result="no_changes")
                return {"result": "no_changes"}
            nuevo: dict[str, Any] | None = None
            preview: dict[str, Any] = {
                "action": "discard_pending_http_config",
                "pending": redact_structure(_sin_meta(pendiente)),
                "pending_error": pendiente.get("error") if isinstance(pendiente, dict) else None,
                "restart": ("Home Assistant restarts and runs the stable configuration "
                            "again."),
            }
        else:
            base = _base_activa(http)
            if base is None:
                logger.warning(f"{tool}_failed", error="preview_unavailable",
                               code="active_config_type")
                return {"error": "preview_unavailable",
                        "detail": "Home Assistant did not say which HTTP configuration "
                                  "it is running with; nothing was done."}
            nombre_base, doc_base = base
            nuevo = dict(doc_base)
            for k, v in (changes or {}).items():
                if v is None:
                    nuevo.pop(k, None)
                else:
                    nuevo[k] = v
            if nuevo.get("use_x_forwarded_for") and not nuevo.get("trusted_proxies"):
                return _invalido(tool, "trusted_proxies",
                                 "use_x_forwarded_for needs at least one trusted proxy "
                                 "in the result (Home Assistant rejects it)")
            if not _supervisor_llega(nuevo.get("server_host")):
                logger.warning(f"{tool}_failed", error="supervisor_lockout")
                return {"error": "supervisor_lockout", "field": "server_host",
                        "detail": _SIN_SUPERVISOR}
            cambios = _diff(doc_base, nuevo, defecto)
            if not cambios:
                logger.info(f"{tool}_ok", step="preview", result="no_changes", fields=claves)
                return {"result": "no_changes"}
            grupos = {_GRUPO_HTTP[k] for k in cambios}
            avisos = [{"code": g, "detail": _AVISOS_HTTP[g][0]}
                      for g in _ORDEN_AVISOS if g in grupos]
            if pendiente is not None:
                avisos.append({"code": "pending_replaced",
                               "detail": _AVISOS_HTTP["pending_replaced"][0]})
            preview = {
                "action": "update_http_config",
                "base": nombre_base,
                "pending_replaced": pendiente is not None,
                "new_config": redact_structure(nuevo),
                "changes": redact_structure(cambios),
                "restart": _REINICIO,
                "warnings": avisos,
            }
            if any(_AVISOS_HTTP[g][1] for g in grupos):
                preview["access_risk"] = _RIESGO_ACCESO

        if not confirmation_token:
            logger.info(f"{tool}_ok", step="preview", fields=claves,
                        discard_pending=discard_pending)
            return await create_confirmation_token(
                tool, args, preview=preview, estado=_estado_http(http))

        valido, error, _ = await resolve_confirmation_token(
            confirmation_token, tool, args, estado=_estado_http(http))
        if not valido:
            return _token_fallido(tool, error)
        # Otra vez justo antes de escribir, como `sv_restart_core`.
        permitido, motivo = _check_restart_allowed()
        if not permitido:
            await complete_confirmation_token(
                confirmation_token, success=False, error="restart_blocked")
            return _bloqueado(tool, motivo, "confirm")
        try:
            resp = await ha_client.ws_send({"type": "http/config/configure", "config": nuevo})
        except HAConnectionError as exc:
            fallo = _error_ha(tool, exc, step="confirm")
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(fallo.get("error")))
            return fallo
        reinicia = bool(resp.get("restart")) if isinstance(resp, dict) else False
        await complete_confirmation_token(
            confirmation_token, success=True, result={"result": "ok", "restart": reinicia})
        logger.info(f"{tool}_ok", step="confirm", fields=claves,
                    discard_pending=discard_pending, restart=reinicia)
        out: dict[str, Any] = {"result": "ok", "restart": reinicia,
                               "config_check": _CONFIG_CHECK}
        if discard_pending:
            out["next"] = "Home Assistant restarts with the stable configuration."
        elif reinicia:
            out["next"] = _SIGUIENTE
        else:
            out["next"] = ("Home Assistant already had this pending configuration; "
                           "it did not restart.")
        return out

    # ── ha_promote_http_config ────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_promote_http_config(confirmation_token: str | None = None) -> object:
        """Confirm that the trial HTTP configuration works and keep it.

        Only when Home Assistant is running with a pending configuration set by
        ha_update_http_config that has not failed. The promoted configuration
        becomes the stable one, which recovery mode uses. Two steps: without
        confirmation_token returns a preview (diff from stable to pending and
        revert_at, when Home Assistant would go back by itself) and a token;
        repeat with the token to promote. The preview doubles as the status
        of the trial. Nothing to promote: {"error": "nothing_to_promote",
        "reason"} and no token.

        Args:
            confirmation_token: Token from the preview call.

        Returns:
            Preview + token; {"result": "ok"}; or {"error": ...}.
        """
        tool = "ha_promote_http_config"
        args: dict[str, Any] = {}
        try:
            http = await _leer_http(ha_client)
        except HAConnectionError as exc:
            return _no_disponible(tool, exc)
        pendiente = http.get("pending")
        motivo = None
        if not isinstance(pendiente, dict):
            motivo = "There is no pending HTTP configuration."
        elif pendiente.get("error") is not None:
            motivo = ("The pending configuration failed its trial "
                      f"({pendiente.get('error')}) and is never applied again; drop it "
                      "with ha_update_http_config(discard_pending=true).")
        elif http.get("active_config_type") != "pending":
            motivo = ("Home Assistant is not running with the pending configuration "
                      "yet (it applies on the next restart); promote it once it runs "
                      "with it.")
        if motivo is not None:
            logger.info(f"{tool}_failed", error="nothing_to_promote")
            return {"error": "nothing_to_promote", "reason": motivo}

        if not confirmation_token:
            defecto = _sin_meta(http.get("default"))
            preview = {
                "action": "promote_http_config",
                "changes": redact_structure(
                    _diff(_sin_meta(http.get("stable")), _sin_meta(pendiente), defecto)),
                "revert_at": http.get("revert_at"),
                "note": "The promoted configuration becomes the one recovery mode uses.",
            }
            logger.info(f"{tool}_ok", step="preview")
            return await create_confirmation_token(
                tool, args, preview=preview, estado=_estado_http(http))

        valido, error, _ = await resolve_confirmation_token(
            confirmation_token, tool, args, estado=_estado_http(http))
        if not valido:
            return _token_fallido(tool, error)
        try:
            await ha_client.ws_send({"type": "http/config/promote"})
        except HAConnectionError as exc:
            fallo = _error_ha(tool, exc, step="confirm")
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(fallo.get("error")))
            return fallo
        await complete_confirmation_token(
            confirmation_token, success=True, result={"result": "ok"})
        logger.info(f"{tool}_ok", step="confirm")
        return {"result": "ok"}
