"""Hermes — Tools MCP de montajes del Supervisor (spec 019, tramo 1; CAP-083).

Familia `mounts` (1.2.0).

Tools:
  sv_list_mounts               — montajes y montaje por defecto de backups
  sv_create_mount              — crea un montaje CIFS, NFS o de disco (token)
  sv_update_mount              — edita un montaje, fundiendo con lo actual (token)
  sv_delete_mount              — borra un montaje (token)
  sv_reload_mount              — comprueba un montaje y lo rearma
  sv_set_default_backup_mount  — fija a dónde van los backups sin `location` (token)

POR QUÉ
-------
Llevar los backups (también los safety backups de Hermes) a un NAS, o
quitar un montaje sin romper nada a ciegas, exigía abrir la interfaz. Lo
delicado es:

- **Credenciales CIFS** (research R-5). `username` y `password` entran y no
  salen nunca: ni en la respuesta, ni en la vista previa, ni en un error, ni
  en el log, ni en el fichero del token. Las respuestas se construyen con una
  lista PERMITIDA de claves (no basta `redact_structure`, que no tapa
  `username`), los errores del Supervisor se limpian de los dos valores
  literales y pasan por `redact_secrets`, y el token no guarda argumentos (sin
  `omitibles`): en disco solo queda el HMAC de la acción.
- **Editar reemplaza** (research R-4). El Supervisor sustituye la
  configuración entera y nunca devuelve las credenciales: Hermes funde lo
  pasado con lo actual, pero no puede conservar unas credenciales que no ve.
  La vista previa lo dice (`removed_if_present`).
- **La vista previa no puede mentir** (research R-6). Lo que se envía al editar
  depende del estado actual, y los efectos de borrar o del montaje por
  defecto también: el token se ata a la huella de ese estado (`estado=` de la
  018) y, si cambia, no se ejecuta.
- **Disco local** (research R-2, decisión del supervisor del programa): el
  Supervisor 2026.11.0 crea montajes `disk` por las mismas rutas, que pasan a
  `dedicated`; no puede quedar un tipo sin tool. Que el dispositivo sea
  montable y no de Home Assistant OS lo comprueba el Supervisor.

El log (research R-10) lleva el nombre del montaje, el tipo, el uso, los
NOMBRES de los campos que cambian y el estado de las credenciales; nunca el
servidor, el recurso, la ruta, el dispositivo ni el texto de un error: son
datos de la red de casa (principio VIII) y un error puede repetir valores.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.identifiers import InvalidIdentifier, validate_path_segment
from hermes.security import (
    ESTADO_CAMBIADO,
    REDACTED_MARKER,
    complete_confirmation_token,
    create_confirmation_token,
    redact_secrets,
    redact_structure,
    resolve_confirmation_token,
)
from hermes.tools._common import sobre_de_lista

logger = structlog.get_logger(__name__)

# ── Reglas (FR-007) ───────────────────────────────────────────────────────────
# El Supervisor acepta `^[A-Za-z0-9_]+$`; el tope de 64 es de Hermes, como en
# el `disk` de `sv_get_disk_usage` (013).
_NOMBRE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_TIPOS = ("cifs", "nfs", "disk")
_USOS = ("backup", "media", "share")
_VERSIONES = ("1.0", "2.0", "auto")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
# UUID de sistema de ficheros: los de ext4 (con guiones) y los de FAT/exFAT
# (`ABCD-1234`). El Supervisor lo busca en /dev/disk/by-uuid/.
_UUID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
# Un dispositivo bajo /dev/, sin `..` ni espacios. El Supervisor lo resuelve
# con UDisks2 y rechaza lo que no es un sistema de ficheros montable o es de
# Home Assistant OS; aquí solo se descarta lo que no puede ser un dispositivo.
_DEVICE = re.compile(r"^/dev/[A-Za-z0-9_.:+/-]{1,250}$")

# Campos de escritura de cada tipo, además de `name`, `type`, `usage` y
# `read_only` (`mounts/validate.py` y `api/mounts.py` del Supervisor).
# El Supervisor descarta en silencio lo que sobra (`REMOVE_EXTRA`): un campo
# de otro tipo se rechaza aquí para que la vista previa no enseñe algo que no
# se aplica.
_CAMPOS_DEL_TIPO: dict[str, tuple[str, ...]] = {
    "cifs": ("server", "port", "share", "version", "username", "password"),
    "nfs": ("server", "port", "path"),
    "disk": ("device", "uuid"),
}
_TODOS_LOS_CAMPOS = ("server", "port", "share", "path", "version",
                     "username", "password", "device", "uuid")
# Campos que cambian a dónde apunta el montaje: si cambian en uno de backup,
# los backups que había allí dejan de verse.
_DESTINO = ("type", "server", "port", "share", "path", "device", "uuid")

# Lista PERMITIDA de lo que se devuelve de un montaje (FR-001; data-model).
_PUBLICAS_COMUNES = ("name", "type", "usage", "read_only", "server", "port",
                     "share", "path", "version")
_PUBLICAS_DISCO = ("uuid", "filesystem")
_PUBLICAS_ESTADO = ("state", "user_path")

# Tope de backups afectados que se listan en una vista previa (data-model).
_MAX_AFECTADOS = 20

_PISTA_RESOLUCION = (
    "The Supervisor could not mount it. sv_get_resolution shows the issue it "
    "raised for this mount; sv_reload_mount retries once the server or device "
    "is reachable."
)
_PISTA_TOKEN = "Arguments or the mount changed since the preview; request a new preview."

_NOTA_RED = (
    "The Supervisor mounts it while creating it; if the server cannot be "
    "reached, nothing is created. Credentials are never shown or returned."
)
_NOTA_DISCO = (
    "The Supervisor checks that the device is a mountable filesystem that "
    "does not belong to Home Assistant OS and mounts it; if it cannot, "
    "nothing is created."
)
_AVISO_CREDENCIALES = (
    "The Supervisor replaces the whole mount configuration and never returns "
    "credentials, so Hermes cannot keep them. If this mount uses a username "
    "and password, they will be removed unless you pass both."
)


class _Rechazo(Exception):
    """Argumento inválido: lleva el código y la regla, nunca el valor."""

    def __init__(self, codigo: str, detalle: str) -> None:
        super().__init__(detalle)
        self.respuesta = {"error": codigo, "detail": detalle}


def _inv(detalle: str) -> _Rechazo:
    return _Rechazo("invalid_argument", detalle)


# ── Validación de cada argumento (FR-007) ─────────────────────────────────────


def _validar_nombre(name: Any) -> None:
    """El nombre va dentro de la ruta (`/mounts/{name}`): además de la forma
    del Supervisor, la red común de los tramos de ruta."""
    if not isinstance(name, str) or not _NOMBRE.match(name):
        raise _inv("name must be 1-64 letters, digits or '_'.")
    try:
        validate_path_segment(name, field="name")
    except InvalidIdentifier as exc:  # pragma: no cover - la regex ya lo cubre
        raise _inv("name must be 1-64 letters, digits or '_'.") from exc


def _validar_argumentos(a: dict[str, Any]) -> None:
    """Forma de cada argumento PASADO (`None` = no pasado). La coherencia con
    el tipo se mira después, sobre la configuración resultante."""
    _validar_nombre(a["name"])
    if a.get("type") is not None and a["type"] not in _TIPOS:
        raise _Rechazo("unsupported_mount_type",
                       "type must be 'cifs', 'nfs' or 'disk'.")
    if a.get("usage") is not None and a["usage"] not in _USOS:
        raise _inv("usage must be 'backup', 'media' or 'share'.")
    server = a.get("server")
    if server is not None and (
            not isinstance(server, str) or not 1 <= len(server) <= 253
            or re.search(r"[/\\\s]", server) or _CONTROL.search(server)):
        raise _inv("server must be a host name or IP address (1-253 characters, "
                   "no '/', '\\', spaces or control characters).")
    share = a.get("share")
    if share is not None and (
            not isinstance(share, str) or not share
            or re.search(r"[/\\]", share) or _CONTROL.search(share)):
        raise _inv("share must be the share name, without '/', '\\' or control "
                   "characters.")
    path = a.get("path")
    if path is not None and (
            not isinstance(path, str) or not path.startswith("/")
            or _CONTROL.search(path)):
        raise _inv("path must be an absolute export path without control characters.")
    port = a.get("port")
    if port is not None and (
            isinstance(port, bool) or not isinstance(port, int)
            or not 1 <= port <= 65535):
        raise _inv("port must be an integer from 1 to 65535.")
    if a.get("version") is not None and a["version"] not in _VERSIONES:
        raise _inv("version must be '1.0', '2.0' or 'auto'.")
    if a.get("read_only") is not None and not isinstance(a["read_only"], bool):
        raise _inv("read_only must be true or false.")
    for campo in ("username", "password"):
        valor = a.get(campo)
        if valor is None:
            continue
        # El Supervisor escribe las credenciales en un fichero `clave=valor`
        # por líneas: un salto de línea inyectaría opciones. Y un valor con el
        # marcador de redacción machacaría la credencial real (mismo criterio
        # que `sv_set_addon_options`).
        if not isinstance(valor, str) or not valor or _CONTROL.search(valor):
            raise _inv(f"{campo} must be non-empty text without control characters.")
        if REDACTED_MARKER in valor:
            raise _inv(f"{campo} contains the redaction marker {REDACTED_MARKER}; "
                       "pass the real value.")
    if (a.get("username") is None) != (a.get("password") is None):
        raise _inv("username and password go together: pass both or neither.")
    device = a.get("device")
    if device is not None and (
            not isinstance(device, str) or not _DEVICE.match(device)
            or ".." in device.split("/")):
        raise _inv("device must be a device path under /dev/ (no '..' or spaces).")
    uuid = a.get("uuid")
    if uuid is not None and (not isinstance(uuid, str) or not _UUID.match(uuid)):
        raise _inv("uuid must be a filesystem UUID (letters, digits and '-').")


def _validar_configuracion(cfg: dict[str, Any]) -> None:
    """Coherencia de la configuración que se va a enviar con su tipo."""
    tipo = cfg["type"]
    propios = _CAMPOS_DEL_TIPO[tipo]
    ajenos = sorted(c for c in _TODOS_LOS_CAMPOS
                    if c not in propios and cfg.get(c) is not None)
    if ajenos:
        raise _inv(f"{', '.join(ajenos)} cannot be used with a {tipo} mount.")
    if tipo in ("cifs", "nfs") and cfg.get("server") is None:
        raise _inv(f"a {tipo} mount needs server.")
    if tipo == "cifs" and cfg.get("share") is None:
        raise _inv("a cifs mount needs share.")
    if tipo == "nfs" and cfg.get("path") is None:
        raise _inv("an nfs mount needs path.")
    if tipo == "disk" and cfg.get("device") is None and cfg.get("uuid") is None:
        raise _inv("a disk mount needs device or uuid.")
    if cfg["usage"] == "backup" and cfg.get("read_only"):
        raise _inv("a backup mount cannot be read only.")


def _cuerpo(cfg: dict[str, Any]) -> dict[str, Any]:
    """La carga para el Supervisor, en un orden fijo y solo con lo del tipo.
    CIFS lleva siempre `version` (`None` = negociación automática)."""
    out: dict[str, Any] = {
        "name": cfg["name"], "type": cfg["type"], "usage": cfg["usage"],
        "read_only": bool(cfg.get("read_only")),
    }
    tipo = cfg["type"]
    if tipo in ("cifs", "nfs"):
        out["server"] = cfg["server"]
    if tipo == "cifs":
        out["share"] = cfg["share"]
        out["version"] = cfg.get("version")
    if tipo == "nfs":
        out["path"] = cfg["path"]
    if tipo in ("cifs", "nfs") and cfg.get("port") is not None:
        out["port"] = cfg["port"]
    if tipo == "disk":
        for c in ("device", "uuid"):
            if cfg.get(c) is not None:
                out[c] = cfg[c]
    if tipo == "cifs" and cfg.get("username") is not None:
        out["username"] = cfg["username"]
        out["password"] = cfg["password"]
    return out


def _sin_secretos(cuerpo: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in cuerpo.items() if k not in ("username", "password")}


# ── Lo que devuelve el Supervisor ─────────────────────────────────────────────


class _FormaInesperada(Exception):
    pass


def _publico(m: dict[str, Any], *, con_estado: bool = True) -> dict[str, Any]:
    """Un montaje con solo las claves permitidas (FR-001). `uuid` y
    `filesystem`, solo en `disk`; `state` y `user_path`, si `con_estado`."""
    claves = _PUBLICAS_COMUNES
    if m.get("type") == "disk":
        claves += _PUBLICAS_DISCO
    if con_estado:
        claves += _PUBLICAS_ESTADO
    return redact_structure({k: m[k] for k in claves if k in m})


def _leer_montajes(datos: Any) -> tuple[str | None, list[dict[str, Any]]]:
    """`GET /mounts` → (montaje por defecto, montajes). Una forma inesperada
    lanza: nunca una lista vacía como si fuera buena (FR-010)."""
    if not isinstance(datos, dict) or not isinstance(datos.get("mounts"), list):
        raise _FormaInesperada
    montajes = datos["mounts"]
    if not all(isinstance(m, dict) and isinstance(m.get("name"), str) for m in montajes):
        raise _FormaInesperada
    por_defecto = datos.get("default_backup_mount")
    if por_defecto is not None and not isinstance(por_defecto, str):
        raise _FormaInesperada
    return por_defecto, montajes


def _backups_en(datos: Any, nombre: str) -> list[dict[str, Any]]:
    """Backups de `GET /backups` cuyo `locations` incluye `nombre`."""
    if not isinstance(datos, dict) or not isinstance(datos.get("backups"), list):
        raise _FormaInesperada
    out = []
    for b in datos["backups"]:
        if not isinstance(b, dict):
            raise _FormaInesperada
        locs = b.get("locations")
        if not isinstance(locs, list):
            locs = [b.get("location")]
        if nombre in locs:
            out.append({**b, "_only_here": locs == [nombre]})
    return out


def _resumen_afectados(afectados: list[dict[str, Any]]) -> dict[str, Any]:
    """Cuántos, cuántos solo están ahí y los 20 más recientes (data-model)."""
    ordenados = sorted(afectados, key=lambda b: (str(b.get("date") or ""),
                                                 str(b.get("slug") or "")),
                       reverse=True)
    return {
        "count": len(afectados),
        "only_here": sum(1 for b in afectados if b["_only_here"]),
        "items": [{"slug": b.get("slug"), "name": b.get("name"), "date": b.get("date")}
                  for b in ordenados[:_MAX_AFECTADOS]],
        "truncated": len(afectados) > _MAX_AFECTADOS,
    }


def _limpiar_error(texto: str, secretos: tuple[Any, ...]) -> str:
    """Quita los valores literales de las credenciales (los más largos antes,
    para no dejar trozos) y pasa por `redact_secrets` (FR-008)."""
    for s in sorted((s for s in secretos if isinstance(s, str) and s),
                    key=len, reverse=True):
        texto = texto.replace(s, REDACTED_MARKER)
    return redact_secrets(texto)


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de montajes en la instancia MCP."""

    async def _estado() -> tuple[str | None, dict[str, dict[str, Any]]]:
        datos = await ha_client.sv_request("GET", "/mounts")
        por_defecto, montajes = _leer_montajes(datos)
        return por_defecto, {m["name"]: m for m in montajes}

    async def _afectados(nombre: str) -> list[dict[str, Any]]:
        return _backups_en(await ha_client.sv_request("GET", "/backups"), nombre)

    def _error_lectura(exc: Exception, secretos: tuple[Any, ...] = ()) -> dict[str, Any]:
        if isinstance(exc, _FormaInesperada):
            return {"error": "The Supervisor returned an unexpected response shape "
                             "for the mounts or backups list."}
        return {"error": _limpiar_error(str(exc), secretos)}

    async def _confirmar(
        tool: str, token: str, args: dict[str, Any], huella: Any,
    ) -> dict[str, Any] | None:
        ok, error, _ = await resolve_confirmation_token(token, tool, args, estado=huella)
        if ok:
            return None
        if error == ESTADO_CAMBIADO:
            return {"error": "mount_changed", "detail": error}
        return {"error": error, "hint": _PISTA_TOKEN}

    async def _leer_de_vuelta(nombre: str) -> dict[str, Any]:
        """Tras escribir: el montaje y el por defecto, leídos de nuevo."""
        try:
            por_defecto, montajes = await _estado()
        except (HAConnectionError, _FormaInesperada):
            return {"mount": None, "default_backup_mount": None,
                    "warning": "Done, but the mount could not be read back; "
                               "check it with sv_list_mounts."}
        m = montajes.get(nombre)
        return {"mount": _publico(m) if m else None, "default_backup_mount": por_defecto}

    # ── Lectura ───────────────────────────────────────────────────────────

    @mcp.tool()
    async def sv_list_mounts() -> object:
        """List the Supervisor's mounts (CIFS and NFS network shares and local
        disks) and the default backup mount.

        Returns {default_backup_mount, count, items, truncated}. Each item has
        name, type (cifs, nfs or disk), usage (backup, media or share),
        read_only, server, port, share, path, version (CIFS, null = automatic),
        uuid and filesystem (disk), state (systemd unit state, e.g. active or
        failed) and user_path (where add-ons and Home Assistant see it).
        default_backup_mount null means backups go to local storage.
        Credentials are never returned.
        """
        try:
            por_defecto, montajes = _leer_montajes(
                await ha_client.sv_request("GET", "/mounts"))
        except (HAConnectionError, _FormaInesperada) as exc:
            return _error_lectura(exc)
        items = [_publico(m) for m in montajes]
        logger.info("sv_list_mounts_ok", count=len(items))
        return sobre_de_lista(items, default_backup_mount=por_defecto)

    # ── Crear ─────────────────────────────────────────────────────────────

    @mcp.tool()
    async def sv_create_mount(
        name: str,
        type: str,
        usage: str,
        server: str | None = None,
        share: str | None = None,
        path: str | None = None,
        port: int | None = None,
        version: str | None = None,
        read_only: bool = False,
        username: str | None = None,
        password: str | None = None,
        device: str | None = None,
        uuid: str | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Create a Supervisor mount. Always two steps: the first call returns
        a preview and a confirmation_token; repeat the same call with
        confirmation_token to create it.

        type: 'cifs' (needs server and share; optional username+password,
        both or neither — without them it mounts as guest; version '1.0',
        '2.0' or 'auto'/omitted for automatic), 'nfs' (needs server and an
        absolute export path) or 'disk' (a local disk: device under /dev/
        and/or filesystem uuid; nothing else). port is optional for cifs and
        nfs. usage: 'backup', 'media' or 'share'; a backup mount cannot be
        read_only.

        The Supervisor mounts it while creating it (network mounts test the
        connection; disks are checked to be mountable and not part of Home
        Assistant OS) and creates nothing if that fails. A backup mount
        becomes the default backup mount when there is none. Credentials are
        never shown, returned or logged.
        """
        tool = "sv_create_mount"
        args: dict[str, Any] = {
            "name": name, "type": type, "usage": usage, "server": server,
            "share": share, "path": path, "port": port, "version": version,
            "read_only": read_only, "username": username, "password": password,
            "device": device, "uuid": uuid,
        }
        secretos = (username, password)
        try:
            _validar_argumentos(args)
            if type is None:
                raise _Rechazo("unsupported_mount_type",
                               "type must be 'cifs', 'nfs' or 'disk'.")
            if usage is None:
                raise _inv("usage must be 'backup', 'media' or 'share'.")
            cfg = {**args, "version": None if version in (None, "auto") else version}
            _validar_configuracion(cfg)
        except _Rechazo as r:
            return r.respuesta
        cuerpo = _cuerpo(cfg)

        try:
            por_defecto, montajes = await _estado()
        except (HAConnectionError, _FormaInesperada) as exc:
            return _error_lectura(exc, secretos)
        if name in montajes:
            return {"error": "mount_exists",
                    "detail": f"A mount named {name} already exists.",
                    "hint": "Use sv_update_mount to change it."}
        huella = {"default_backup_mount": por_defecto}
        credenciales = ("set" if username else "none") if type == "cifs" else None
        campos_log = {"mount": name, "type": type, "usage": usage,
                      "credentials": credenciales}

        if not confirmation_token:
            preview: dict[str, Any] = {"action": "create_mount",
                                       "mount": _sin_secretos(cuerpo)}
            if credenciales is not None:
                preview["credentials"] = credenciales
            preview["becomes_default_backup_mount"] = (
                usage == "backup" and por_defecto is None)
            preview["reloads_backups"] = usage == "backup"
            preview["note"] = _NOTA_DISCO if type == "disk" else _NOTA_RED
            logger.info("sv_create_mount_preview", **campos_log)
            return await create_confirmation_token(tool, args, preview=preview,
                                                   estado=huella)

        if (fallo := await _confirmar(tool, confirmation_token, args, huella)):
            return fallo
        try:
            await ha_client.sv_request("POST", "/mounts", json_body=cuerpo)
        except HAConnectionError as exc:
            texto = _limpiar_error(str(exc), secretos)
            await complete_confirmation_token(confirmation_token, success=False, error=texto)
            logger.warning("sv_create_mount_error", **campos_log, error_kind="supervisor")
            return {"error": texto, "hint": _PISTA_RESOLUCION}
        result = {"result": "ok", **(await _leer_de_vuelta(name))}
        await complete_confirmation_token(confirmation_token, success=True, result=result)
        logger.info("sv_create_mount_ok", **campos_log)
        return result

    # ── Editar ────────────────────────────────────────────────────────────

    @mcp.tool()
    async def sv_update_mount(
        name: str,
        type: str | None = None,
        usage: str | None = None,
        server: str | None = None,
        share: str | None = None,
        path: str | None = None,
        port: int | None = None,
        version: str | None = None,
        read_only: bool | None = None,
        username: str | None = None,
        password: str | None = None,
        device: str | None = None,
        uuid: str | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Change an existing Supervisor mount. Always two steps (preview,
        then the same call with confirmation_token).

        Fields you omit keep their current value; version='auto' goes back
        to automatic negotiation. Changing type starts from scratch: pass the
        new type's fields (cifs: server and share; nfs: server and path; disk:
        device or uuid). For a disk, a new device replaces the stored uuid.

        WARNING: the Supervisor replaces the whole configuration and never
        returns credentials, so Hermes cannot keep them: editing a CIFS mount
        without username and password REMOVES them if it had any. The
        Supervisor unmounts and mounts it again. The preview lists every
        change, whether it stops being the default backup mount and which
        backups stop being visible if a backup mount changes its target or
        usage. Credentials are never shown, returned or logged.
        """
        tool = "sv_update_mount"
        args: dict[str, Any] = {
            "name": name, "type": type, "usage": usage, "server": server,
            "share": share, "path": path, "port": port, "version": version,
            "read_only": read_only, "username": username, "password": password,
            "device": device, "uuid": uuid,
        }
        secretos = (username, password)
        try:
            _validar_argumentos(args)
        except _Rechazo as r:
            return r.respuesta

        try:
            por_defecto, montajes = await _estado()
        except (HAConnectionError, _FormaInesperada) as exc:
            return _error_lectura(exc, secretos)
        actual = montajes.get(name)
        if actual is None:
            return {"error": "mount_not_found", "detail": f"No mount named {name}.",
                    "hint": "sv_list_mounts lists the mounts."}
        if actual.get("type") not in _TIPOS:
            return {"error": "unsupported_mount_type",
                    "detail": "Only cifs, nfs and disk mounts can be changed."}

        # Fusión (research R-4). Lo común (uso y solo lectura) se conserva;
        # los campos del tipo, solo si el tipo no cambia. Las credenciales
        # nunca salen de lo actual: el Supervisor no las devuelve.
        nuevo_tipo = type or actual["type"]
        cfg: dict[str, Any] = {"name": name, "type": nuevo_tipo,
                               "usage": actual.get("usage"),
                               "read_only": actual.get("read_only", False)}
        if nuevo_tipo == actual["type"]:
            for c in _CAMPOS_DEL_TIPO[nuevo_tipo]:
                if c not in ("username", "password", "device") and c in actual:
                    cfg[c] = actual[c]
            # Un `device` nuevo manda: el `uuid` guardado podría ser de otro
            # disco y el Supervisor rechazaría la pareja.
            if nuevo_tipo == "disk" and device is not None and uuid is None:
                cfg.pop("uuid", None)
        for c, v in args.items():
            if c in ("name", "type") or v is None:
                continue
            cfg[c] = None if (c == "version" and v == "auto") else v
        try:
            if cfg["usage"] not in _USOS:
                raise _inv("the mount's usage must be 'backup', 'media' or 'share'.")
            _validar_configuracion(cfg)
        except _Rechazo as r:
            return r.respuesta
        cuerpo = _cuerpo(cfg)

        antes = _publico(actual, con_estado=False)
        despues = _sin_secretos(cuerpo)
        cambios = {
            k: {"from": antes.get(k), "to": despues.get(k)}
            for k in sorted(set(antes) | set(despues) - {"filesystem"})
            if k != "filesystem" and antes.get(k) != despues.get(k)
        }
        era_backup = actual.get("usage") == "backup"
        cambia_destino = any(k in cambios for k in _DESTINO)
        deja_backup = era_backup and cfg["usage"] != "backup"
        huella = {"mount": antes, "default_backup_mount": por_defecto}
        credenciales = None
        if nuevo_tipo == "cifs":
            credenciales = "replaced" if username else "removed_if_present"
        campos_log = {"mount": name, "type": nuevo_tipo, "usage": cfg["usage"],
                      "changed": sorted(cambios), "credentials": credenciales}

        if not confirmation_token:
            preview: dict[str, Any] = {"action": "update_mount", "mount": name,
                                       "changes": cambios}
            if credenciales is not None:
                preview["credentials"] = credenciales
                if credenciales == "removed_if_present":
                    preview["credentials_warning"] = _AVISO_CREDENCIALES
            preview["remount"] = True
            preview["stops_being_default_backup_mount"] = (
                deja_backup and por_defecto == name)
            if era_backup and (deja_backup or cambia_destino):
                try:
                    preview["affected_backups"] = _resumen_afectados(
                        await _afectados(name))
                except (HAConnectionError, _FormaInesperada) as exc:
                    return _error_lectura(exc, secretos)
            preview["note"] = "The Supervisor unmounts and mounts it again."
            logger.info("sv_update_mount_preview", **campos_log)
            return await create_confirmation_token(tool, args, preview=preview,
                                                   estado=huella)

        if (fallo := await _confirmar(tool, confirmation_token, args, huella)):
            return fallo
        try:
            await ha_client.sv_request("PUT", f"/mounts/{name}", json_body=cuerpo)
        except HAConnectionError as exc:
            texto = _limpiar_error(str(exc), secretos)
            await complete_confirmation_token(confirmation_token, success=False, error=texto)
            logger.warning("sv_update_mount_error", **campos_log, error_kind="supervisor")
            return {"error": texto, "hint": _PISTA_RESOLUCION}
        result = {"result": "ok", **(await _leer_de_vuelta(name))}
        await complete_confirmation_token(confirmation_token, success=True, result=result)
        logger.info("sv_update_mount_ok", **campos_log)
        return result

    # ── Borrar ────────────────────────────────────────────────────────────

    @mcp.tool()
    async def sv_delete_mount(name: str, confirmation_token: str | None = None) -> object:
        """Delete a Supervisor mount (cifs, nfs or disk). Always two steps
        (preview, then the same call with confirmation_token).

        The preview says whether it is the default backup mount (new backups
        without a location, including Hermes safety backups, then go to local
        storage) and, for a backup mount, which backups are stored there: the
        ones stored only there disappear from the Supervisor's list and cannot
        be restored from Home Assistant. The files stay on the server or disk.
        For a media or share mount, its content stops being available to Home
        Assistant and add-ons.
        """
        tool = "sv_delete_mount"
        args = {"name": name}
        try:
            _validar_nombre(name)
        except _Rechazo as r:
            return r.respuesta
        try:
            por_defecto, montajes = await _estado()
            actual = montajes.get(name)
            afectados = (await _afectados(name)
                         if actual is not None and actual.get("usage") == "backup" else [])
        except (HAConnectionError, _FormaInesperada) as exc:
            return _error_lectura(exc)
        if actual is None:
            return {"error": "mount_not_found", "detail": f"No mount named {name}.",
                    "hint": "sv_list_mounts lists the mounts."}
        huella = {"mount": _publico(actual, con_estado=False),
                  "default_backup_mount": por_defecto,
                  "affected_backups": sorted(str(b.get("slug")) for b in afectados)}
        uso = actual.get("usage")
        campos_log = {"mount": name, "usage": uso, "affected_backups": len(afectados)}

        if not confirmation_token:
            es_defecto = por_defecto == name
            preview: dict[str, Any] = {
                "action": "delete_mount", "mount": _publico(actual),
                "is_default_backup_mount": es_defecto,
                "default_after": None if es_defecto else por_defecto,
            }
            donde = "disk" if actual.get("type") == "disk" else "server"
            avisos = []
            if uso == "backup":
                resumen = _resumen_afectados(afectados)
                preview["affected_backups"] = resumen
                if resumen["only_here"]:
                    avisos.append(
                        f"{resumen['only_here']} backups are stored only on this "
                        "mount: they disappear from the Supervisor's list and "
                        "cannot be restored from Home Assistant until a mount "
                        "pointing to the same place is created again.")
                avisos.append(f"The files stay on the {donde}.")
            elif uso in ("media", "share"):
                ruta = actual.get("user_path") or f"/{uso}/{name}"
                avisos.append(
                    f"Its content stops being available at {ruta} for Home "
                    f"Assistant and add-ons. The files stay on the {donde}.")
            if es_defecto:
                avisos.append(
                    "New backups without a location (including Hermes safety "
                    "backups) will go to local storage.")
            preview["warning"] = " ".join(avisos)
            logger.info("sv_delete_mount_preview", **campos_log)
            return await create_confirmation_token(tool, args, preview=preview,
                                                   estado=huella)

        if (fallo := await _confirmar(tool, confirmation_token, args, huella)):
            return fallo
        try:
            await ha_client.sv_request("DELETE", f"/mounts/{name}")
        except HAConnectionError as exc:
            texto = _limpiar_error(str(exc), ())
            await complete_confirmation_token(confirmation_token, success=False, error=texto)
            logger.warning("sv_delete_mount_error", **campos_log, error_kind="supervisor")
            return {"error": texto}
        leido = await _leer_de_vuelta(name)
        result = {"result": "ok", "deleted": name,
                  "default_backup_mount": leido["default_backup_mount"]}
        await complete_confirmation_token(confirmation_token, success=True, result=result)
        logger.info("sv_delete_mount_ok", **campos_log)
        return result

    # ── Recargar ──────────────────────────────────────────────────────────

    @mcp.tool()
    async def sv_reload_mount(name: str) -> object:
        """Ask the Supervisor to check a mount and re-arm it (for a mount in
        a failed state after the server or disk came back). A healthy mount
        is left as is. No confirmation needed. Returns the mount read back.
        """
        try:
            _validar_nombre(name)
        except _Rechazo as r:
            return r.respuesta
        try:
            _, montajes = await _estado()
        except (HAConnectionError, _FormaInesperada) as exc:
            return _error_lectura(exc)
        if name not in montajes:
            return {"error": "mount_not_found", "detail": f"No mount named {name}.",
                    "hint": "sv_list_mounts lists the mounts."}
        try:
            await ha_client.sv_request("POST", f"/mounts/{name}/reload")
        except HAConnectionError as exc:
            logger.warning("sv_reload_mount_error", mount=name, error_kind="supervisor")
            return {"error": _limpiar_error(str(exc), ()), "hint": _PISTA_RESOLUCION}
        logger.info("sv_reload_mount_ok", mount=name)
        leido = await _leer_de_vuelta(name)
        return {"result": "ok", "mount": leido["mount"]}

    # ── Montaje por defecto ───────────────────────────────────────────────

    @mcp.tool()
    async def sv_set_default_backup_mount(
        name: str | None,
        confirmation_token: str | None = None,
    ) -> object:
        """Set the default backup mount: where backups created without a
        location go, including Hermes safety backups. name=null goes back to
        local storage. The mount must exist and have usage 'backup'. Always
        two steps (preview, then the same call with confirmation_token).
        """
        tool = "sv_set_default_backup_mount"
        args = {"name": name}
        if name is not None:
            try:
                _validar_nombre(name)
            except _Rechazo as r:
                return r.respuesta
        try:
            por_defecto, montajes = await _estado()
        except (HAConnectionError, _FormaInesperada) as exc:
            return _error_lectura(exc)
        uso = None
        if name is not None:
            if name not in montajes:
                return {"error": "mount_not_found", "detail": f"No mount named {name}.",
                        "hint": "sv_list_mounts lists the mounts."}
            uso = montajes[name].get("usage")
            if uso != "backup":
                return {"error": "not_a_backup_mount",
                        "detail": f"{name} does not have usage 'backup'.",
                        "hint": "Change its usage with sv_update_mount first."}
        huella = {"default_backup_mount": por_defecto, "target_usage": uso}
        campos_log = {"from": por_defecto, "to": name}

        if not confirmation_token:
            destino = f"the mount {name}" if name else "local storage"
            preview = {
                "action": "set_default_backup_mount", "from": por_defecto, "to": name,
                "note": f"Backups created without a location, including Hermes "
                        f"safety backups, will go to {destino}.",
            }
            logger.info("sv_set_default_backup_mount_preview", **campos_log)
            return await create_confirmation_token(tool, args, preview=preview,
                                                   estado=huella)

        if (fallo := await _confirmar(tool, confirmation_token, args, huella)):
            return fallo
        try:
            await ha_client.sv_request("POST", "/mounts/options",
                                       json_body={"default_backup_mount": name})
        except HAConnectionError as exc:
            texto = _limpiar_error(str(exc), ())
            await complete_confirmation_token(confirmation_token, success=False, error=texto)
            return {"error": texto}
        leido = await _leer_de_vuelta(name or "")
        result = {"result": "ok", "default_backup_mount": leido["default_backup_mount"]}
        await complete_confirmation_token(confirmation_token, success=True, result=result)
        logger.info("sv_set_default_backup_mount_ok", **campos_log)
        return result
