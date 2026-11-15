"""Hermes — Tools MCP de las fichas de las apps de la tienda y de su
reconstrucción (spec 030, tramo 2; CAP-082 y CAP-093).

Familia `app_store` (1.2.0).

Tools:
  sv_get_addon_changelog      — changelog de la versión de la tienda, por trozos
  sv_get_addon_documentation  — documentación de la versión de la tienda, por trozos
  sv_get_addon_availability   — si la app se puede instalar en este sistema
  sv_rebuild_addon            — reconstruye una app instalada (dos pasos)

POR QUÉ
-------
El changelog y la documentación los escribe el autor de la app: son texto de
terceros (`_third_party_text`) y pueden llevar cualquier cosa (una app local,
hasta una contraseña de ejemplo real), así que se redactan ENTEROS antes de
cortarlos en trozos (research R-9). El Supervisor 2026.11.0 los devuelve con
un 200 aunque falle («No changelog found…», «App … does not exist…»): por eso
se lee antes la ficha de la tienda y se reconocen esos textos exactos, para
no presentar un mensaje de error como si fuera el changelog.

Reconstruir borra el contenedor y la imagen de la app y los vuelve a hacer con
la misma versión; si la construcción falla, la app se queda sin imagen. Va en
dos pasos y la vista previa rechaza sin token todo lo que el Supervisor
rechazaría (no instalada, desligada de la tienda, con otra versión en la
tienda, de imagen sin `force`): dar un token para algo imposible sería mentir
(research R-8).

El evento de log `app_store_action` lleva la tool, el resultado, el `slug` de
la app y, con texto, cuántos bytes se devolvieron; nunca el texto.
"""

from __future__ import annotations

from typing import Any

import structlog

from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    ESTADO_CAMBIADO,
    complete_confirmation_token,
    create_confirmation_token,
    redact_secrets,
    redact_structure,
    resolve_confirmation_token,
)
from hermes.tools._logs import ArgumentoInvalido
from hermes.tools._store import (
    disponibilidad,
    estado_de_privilegios,
    ficha_de_tienda,
    candado_de_app,
    comprobar_copia_de_tienda,
    leer_declarado,
    privilegios_de,
    privilegios_para_mostrar,
    texto_de_la_app,
    texto_de_terceros,
    trozo_de_texto,
)
from hermes.tools._validation import InvalidIdentifier, validate_slug
from hermes.tools.addons import _LONG_OP_TIMEOUT, _self_warning, es_hermes

logger = structlog.get_logger(__name__)

_EVENTO = "app_store_action"

# Trozos de texto (data-model): 20 000 caracteres por defecto, 100 000 como
# máximo. El tope de bytes de la respuesta manda igualmente.
MAX_CHARS_DEFECTO = 20_000
MAX_CHARS_TOPE = 100_000

_DETALLE_OFFSET = "offset must be an integer >= 0."
_DETALLE_MAX_CHARS = f"max_chars must be an integer from 1 to {MAX_CHARS_TOPE}."
_DETALLE_FORCE = "force must be true or false."


def _entero(valor: Any) -> bool:
    # `True` es un `int` en Python, pero no es un desplazamiento.
    return isinstance(valor, int) and not isinstance(valor, bool)


def validar_trozo(offset: Any, max_chars: Any) -> None:
    """Lanza `ArgumentoInvalido` si `offset` o `max_chars` no valen. El
    `detail` dice la regla, no copia el valor."""
    if not _entero(offset) or offset < 0:
        raise ArgumentoInvalido("offset", _DETALLE_OFFSET)
    if not _entero(max_chars) or not 1 <= max_chars <= MAX_CHARS_TOPE:
        raise ArgumentoInvalido("max_chars", _DETALLE_MAX_CHARS)


def _redactar(campos: dict[str, Any]) -> dict[str, Any]:
    """Campos de la ficha listos para el cliente: `redact_structure` (claves
    sensibles) y `redact_secrets` en cada texto, porque el nombre y lo demás
    los escribe el autor de la app y un secreto puede ir en cualquier valor."""
    return {k: redact_secrets(v) if isinstance(v, str) else v
            for k, v in redact_structure(campos).items()}


def _no_encontrada() -> dict[str, Any]:
    return {"error": "addon_not_found", "detail": "No app with that slug in the store."}


def register(
    mcp: object,
    ha_client: HAClient,
    *,
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
) -> None:
    """Registra las cuatro tools de fichas y reconstrucción de apps."""

    # D-13 (cierre de seguridad): Hermes por el slug EXACTO de
    # `/addons/self/info`, con el sufijo `_hermes` de respaldo si no se puede
    # leer. Antes, reconstruir otra app `<x>_hermes` avisaba de que se
    # reconstruía Hermes. Import aquí: `system_updates` importa `addons`.
    from hermes.tools.system_updates import lector_slug_propio

    slug_propio = lector_slug_propio(ha_client)

    def _log(tool: str, outcome: str, **campos: Any) -> None:
        logger.info(_EVENTO, tool=tool, outcome=outcome, **campos)

    def _rechazo(tool: str, respuesta: dict[str, Any], **campos: Any) -> dict[str, Any]:
        _log(tool, f"rejected:{respuesta['error']}", **campos)
        return respuesta

    def _error(tool: str, exc: Exception, **campos: Any) -> dict[str, Any]:
        _log(tool, "error", **campos)
        return {"error": redact_secrets(str(exc))}

    def _slug_invalido(slug: Any) -> dict[str, Any] | None:
        try:
            validate_slug(slug, field="slug")
            return None
        except InvalidIdentifier as exc:
            return {"error": "invalid_identifier", "detail": str(exc)}

    # ── Changelog y documentación ──

    async def _texto(tool: str, tipo: str, slug: str, offset: Any, max_chars: Any) -> object:
        if (err := _slug_invalido(slug)):
            return _rechazo(tool, err)
        try:
            validar_trozo(offset, max_chars)
        except ArgumentoInvalido as exc:
            return _rechazo(tool, exc.respuesta(), slug=slug)
        no_tiene = {
            "changelog": {"error": "changelog_not_found",
                          "detail": "The app has no changelog."},
            "documentation": {"error": "documentation_not_found",
                              "detail": "The app has no documentation."},
        }[tipo]
        try:
            ficha = await ficha_de_tienda(ha_client, slug)
            if ficha is None:
                return _rechazo(tool, _no_encontrada(), slug=slug)
            # La ficha ya dice si hay documentación: no se pide un texto que
            # el Supervisor sustituiría por «No documentation found…».
            if ficha.get(tipo) is False:
                return _rechazo(tool, no_tiene, slug=slug)
            texto = await texto_de_la_app(ha_client, slug, tipo)
        except HAConnectionError as exc:
            if exc.status == 404:
                return _rechazo(tool, _no_encontrada(), slug=slug)
            return _error(tool, exc, slug=slug)
        if texto is None:
            return _rechazo(tool, no_tiene, slug=slug)
        base = _redactar({
            "slug": slug,
            "name": ficha.get("name"),
            "version_latest": ficha.get("version_latest"),
        })
        out = trozo_de_texto(
            texto, offset, max_chars,
            {**base, "_third_party_text": texto_de_terceros(["name", "text"])},
            response_max_bytes,
        )
        _log(tool, "ok", slug=slug, bytes=len(out["text"].encode("utf-8")))
        return out

    @mcp.tool()
    async def sv_get_addon_changelog(
        slug: str,
        offset: int = 0,
        max_chars: int = MAX_CHARS_DEFECTO,
    ) -> object:
        """Read the changelog of an app (add-on) from the Supervisor store, in
        chunks (read only).

        It is the changelog of the version the STORE offers
        (`version_latest`), not of the installed one. Written by the app
        author: third-party text (see `_third_party_text`), with secrets
        redacted (`secrets_redacted`). Long texts come in chunks: repeat with
        `offset` = `next_offset` while `truncated` is true.

        Args:
            slug: App slug (e.g. 'core_mosquitto').
            offset: First character to return (default 0).
            max_chars: Maximum characters of this chunk, 1 to 100000 (default
                20000). The chunk is shortened further to fit the response
                size limit.

        Returns:
            {"slug", "name", "version_latest", "text", "total_chars",
             "offset", "truncated", "next_offset" (if truncated),
             "secrets_redacted", "_third_party_text"}, or
            {"error": "addon_not_found" | "changelog_not_found"}.
        """
        return await _texto("sv_get_addon_changelog", "changelog", slug, offset, max_chars)

    @mcp.tool()
    async def sv_get_addon_documentation(
        slug: str,
        offset: int = 0,
        max_chars: int = MAX_CHARS_DEFECTO,
    ) -> object:
        """Read the documentation of an app (add-on) from the Supervisor
        store, in chunks (read only).

        It is the documentation of the version the STORE offers
        (`version_latest`), not of the installed one. Written by the app
        author: third-party text (see `_third_party_text`), with secrets
        redacted (`secrets_redacted`). Long texts come in chunks: repeat with
        `offset` = `next_offset` while `truncated` is true.

        Args:
            slug: App slug (e.g. 'core_mosquitto').
            offset: First character to return (default 0).
            max_chars: Maximum characters of this chunk, 1 to 100000 (default
                20000). The chunk is shortened further to fit the response
                size limit.

        Returns:
            {"slug", "name", "version_latest", "text", "total_chars",
             "offset", "truncated", "next_offset" (if truncated),
             "secrets_redacted", "_third_party_text"}, or
            {"error": "addon_not_found" | "documentation_not_found"}.
        """
        return await _texto("sv_get_addon_documentation", "documentation", slug,
                            offset, max_chars)

    # ── Disponibilidad ──

    @mcp.tool()
    async def sv_get_addon_availability(slug: str) -> object:
        """Check whether an app (add-on) of the Supervisor store can be
        installed on this system (read only): CPU architecture, machine type
        and minimum Home Assistant version.

        Args:
            slug: App slug.

        Returns:
            {"slug", "name", "available", "reason" (the Supervisor's message,
             or null), "installed", "version", "version_latest", "arch",
             "homeassistant", "stage", "advanced", "build", "repository",
             "_third_party_text"}, or {"error": "addon_not_found"}.
        """
        tool = "sv_get_addon_availability"
        if (err := _slug_invalido(slug)):
            return _rechazo(tool, err)
        try:
            ficha = await ficha_de_tienda(ha_client, slug)
            if ficha is None:
                return _rechazo(tool, _no_encontrada(), slug=slug)
            # `available` sale de la ruta `availability`, no del campo de la
            # ficha: se calcula igual pero la ruta lo comprueba en el momento.
            disponible, motivo = await disponibilidad(ha_client, slug)
        except HAConnectionError as exc:
            if exc.status == 404:
                return _rechazo(tool, _no_encontrada(), slug=slug)
            return _error(tool, exc, slug=slug)
        out = _redactar({
            "slug": slug,
            "name": ficha.get("name"),
            "available": disponible,
            "reason": motivo,
            **{k: ficha.get(k) for k in (
                "installed", "version", "version_latest", "arch",
                "homeassistant", "stage", "advanced", "build", "repository")},
        })
        out["_third_party_text"] = texto_de_terceros(["name"])
        _log(tool, "ok", slug=slug)
        return out

    # ── Reconstruir ──

    async def _rechazo_de_reconstruir(
        tool: str, slug: str, force: bool
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """(error listo, info de la app). Lo que el Supervisor 2026.11.0
        rechazaría (`apps/manager.py`, `rebuild`) se rechaza aquí sin token."""
        try:
            info = await ha_client.sv_request("GET", f"/addons/{slug}/info")
        except HAConnectionError as exc:
            if exc.status in (400, 404):
                return _rechazo(tool, _no_encontrada(), slug=slug), None
            # Sin la ficha no se puede prometer nada: sin token.
            return _error(tool, exc, slug=slug), None
        if not isinstance(info, dict):
            return _rechazo(tool, {"error": "unexpected_response"}, slug=slug), None
        # Con una app no instalada, el Supervisor responde con la ficha de la
        # tienda: `installed: false` (o sin versión instalada).
        if info.get("installed") is False or info.get("version") is None:
            return _rechazo(tool, {
                "error": "addon_not_installed",
                "detail": "The app is not installed. Install it with sv_install_addon.",
            }, slug=slug), None
        if info.get("detached") is True:
            return _rechazo(tool, {
                "error": "addon_not_in_store",
                "detail": ("The app is no longer in any store repository and "
                           "cannot be rebuilt."),
            }, slug=slug), None
        if info.get("version") != info.get("version_latest"):
            return _rechazo(tool, {
                "error": "rebuild_version_changed",
                "version": info.get("version"),
                "version_latest": info.get("version_latest"),
                "detail": ("The store offers another version: the Supervisor "
                           "only rebuilds the installed version when it is the "
                           "store's. Update the app first with sv_update_addon."),
            }, slug=slug), None
        if info.get("build") is not True and not force:
            return _rechazo(tool, {
                "error": "rebuild_not_supported",
                "detail": ("The app uses a prebuilt image. Pass force=true to "
                           "download the image again."),
            }, slug=slug), None
        return None, info

    async def _privilegios_de_reconstruir(
        slug: str, info: dict[str, Any] | None, motivo_info: str | None
    ) -> dict[str, Any] | None:
        """Bloque `privileges` de reconstruir (spec 034, FR-022): lo que se
        aplicará (la ficha de la tienda, que el Supervisor copia a la app al
        reconstruir: `apps/app.py`, `rebuild`), lo actual (`info`, de
        `/addons/{slug}/info`) y, para `local_*`, lo que declara su `config.*`
        en `/addons`. La ficha de la tienda es una lectura nueva (GET, sin
        efecto)."""
        motivos: dict[str, str] = {}
        if motivo_info:
            motivos["installed"] = motivo_info
        try:
            ficha = await ficha_de_tienda(ha_client, slug)
            if ficha is None:
                motivos["store"] = "The app is not in the store."
        except HAConnectionError as exc:
            ficha = None
            motivos["store"] = redact_secrets(str(exc))
        declarado, motivo_carpeta = await leer_declarado(slug)
        if motivo_carpeta:
            motivos["declared_in_folder"] = motivo_carpeta
        return privilegios_de(store=ficha, installed=info, declared=declarado,
                              motivos=motivos)

    async def _estado_de_reconstruir(slug: str) -> Any:
        """El bloque `privileges` leído otra vez al confirmar (FR-023), con
        las mismas lecturas que la vista previa. Lo que no se puede leer
        cuenta como `None`: si la vista previa sí lo leyó, no casa."""
        motivo: str | None = None
        try:
            info = await ha_client.sv_request("GET", f"/addons/{slug}/info")
        except HAConnectionError as exc:
            info, motivo = None, redact_secrets(str(exc))
        if not isinstance(info, dict):
            info = None
            motivo = motivo or "Unexpected response from the Supervisor."
        return estado_de_privilegios(
            await _privilegios_de_reconstruir(slug, info, motivo))

    @mcp.tool()
    async def sv_rebuild_addon(
        slug: str,
        force: bool = False,
        confirmation_token: str | None = None,
    ) -> object:
        """Rebuild an installed app (add-on): removes its container and image
        and makes them again with the SAME version. Two steps: the first call
        returns a preview and a confirmation_token; repeat it with the same
        `slug`, `force` and the token.

        Only apps built locally (`build: true`, typically local apps after
        changing their code) can be rebuilt, unless `force=true`, which for an
        app that uses a prebuilt image downloads that image again. Options
        and the app's /data are kept; the app is stopped and returns to its
        previous state. If the build fails, the app is left WITHOUT an image
        and cannot start until it is rebuilt or reinstalled. It may take
        minutes. Rejected without a token if the app is not installed, is no
        longer in the store, or the store offers another version (update it
        first).

        The preview shows the app's privileges (`privileges`): what will be
        applied (`store`, the store's copy, which the rebuild applies), what
        applies now (`installed`), for a local app (`local_*`) what its
        config file in /addons declares (`declared_in_folder`, including
        `map` and `ports`), and which ones are elevated (`elevated`). The
        token is bound to them: if they change before confirming, the answer
        is `preview_outdated` and nothing is rebuilt.

        Local app (`local_*`): the rebuild applies the Supervisor's OWN copy
        of its config file, read at the last store reload, which may not be
        the file in /addons. If the config file or a folder on its path
        changed after the start of the last store reload launched by Hermes
        (sv_reload_store, sv_check_for_updates, adding or removing a
        repository), or Hermes has launched none since it started, it is
        rejected WITHOUT a token with `store_copy_stale` (hint:
        sv_reload_store). Also without /addons, without the app in its index,
        with two config files for the same slug or with an unreadable one.
        Checked in the preview and again when confirming, together with the
        request, with no Hermes write to /addons in between.

        Args:
            slug: App slug.
            force: Rebuild even an app that uses a prebuilt image (default false).
            confirmation_token: Token from the preview.

        Returns:
            Without token: {"confirmation_token", "preview"} or an error.
            With token: {"result": "ok", "slug", "force"}.
        """
        tool = "sv_rebuild_addon"
        if (err := _slug_invalido(slug)):
            return _rechazo(tool, err)
        if not isinstance(force, bool):
            return _rechazo(tool, ArgumentoInvalido("force", _DETALLE_FORCE).respuesta(),
                            slug=slug)
        args: dict[str, Any] = {"slug": slug, "force": force}

        if not confirmation_token:
            error, info = await _rechazo_de_reconstruir(tool, slug, force)
            if error is not None:
                return error
            assert info is not None
            construye = info.get("build") is True
            preview: dict[str, Any] = {
                "action": "rebuild_addon",
                **_redactar({
                    "slug": slug,
                    "name": info.get("name"),
                    "version": info.get("version"),
                    "state": info.get("state"),
                    "build": info.get("build"),
                }),
                "force": force,
                "effect": (
                    "Removes the app container and image and builds the image "
                    "again locally, with the same version."
                    if construye else
                    "Removes the app container and image and downloads the "
                    "same version of the image again."
                ),
                "keeps": "Options and the app's /data are kept.",
                "state_after": (
                    "The app is stopped during the rebuild and returns to its "
                    "previous state."
                ),
                "on_failure": (
                    "If the build fails, the app is left without an image and "
                    "cannot start until it is rebuilt or reinstalled."
                ),
                "_third_party_text": texto_de_terceros(["name"]),
            }
            aviso = (_self_warning(slug, "rebuilding")
                     if await es_hermes(slug, slug_propio) else None)
            if aviso:
                preview["critical_warning"] = aviso
            # Spec 034 (FR-022, FR-023): los privilegios, y el token atado a
            # ellos.
            bloque = await _privilegios_de_reconstruir(slug, info, None)
            # Convergencia T047: para una app local, `rebuild` aplica la copia
            # de la última recarga de la tienda, no el fichero.
            if (desfase := await comprobar_copia_de_tienda(slug)) is not None:
                return _rechazo(tool, desfase, slug=slug)
            preview["privileges"] = privilegios_para_mostrar(bloque)
            _log(tool, "preview", slug=slug)
            return await create_confirmation_token(
                tool, args, preview=preview, estado=estado_de_privilegios(bloque))

        # T047 y T048: la comprobación y la petición, bajo el candado de
        # /addons (solo para `local_*`).
        async with candado_de_app(slug):
            return await _confirmar_reconstruir(slug, force, args, confirmation_token)

    async def _confirmar_reconstruir(
        slug: str, force: bool, args: dict[str, Any], confirmation_token: str
    ) -> dict[str, Any]:
        tool = "sv_rebuild_addon"
        # Primero el token con su estado: un cambio en los privilegios es
        # `preview_outdated` sin gastar el token (como en instalar).
        valid, error_token, _ = await resolve_confirmation_token(
            confirmation_token, tool, args, estado=await _estado_de_reconstruir(slug))
        if not valid:
            if error_token == ESTADO_CAMBIADO:
                _log(tool, "rejected:preview_outdated", slug=slug)
                return {
                    "error": error_token,
                    "preview_outdated": True,
                    "slug": slug,
                    "hint": ("The app's privileges changed since the preview. "
                             "Nothing was done; request a new preview (call "
                             "again without confirmation_token)."),
                }
            return _rechazo(tool, {"error": error_token}, slug=slug)
        if (desfase := await comprobar_copia_de_tienda(slug)) is not None:
            await complete_confirmation_token(
                confirmation_token, success=False, error="store_copy_stale")
            return _rechazo(tool, desfase, slug=slug)
        try:
            # Sin `background`: la ruta no lo admite (`api/apps.py`, `rebuild`)
            # y espera a que la app vuelva a arrancar. De ahí la espera larga.
            await ha_client.sv_request(
                "POST", f"/addons/{slug}/rebuild",
                json_body={"force": force},
                timeout_seconds=_LONG_OP_TIMEOUT,
            )
        except HAConnectionError as exc:
            mensaje = redact_secrets(str(exc))
            await complete_confirmation_token(confirmation_token, success=False, error=mensaje)
            _log(tool, "error", slug=slug)
            return {
                "error": mensaje,
                "hint": ("If the request timed out, the rebuild may still be "
                         "running in the Supervisor: check the app with "
                         "sv_get_addon."),
            }
        result: dict[str, Any] = {"result": "ok", "slug": slug, "force": force}
        await complete_confirmation_token(confirmation_token, success=True, result=result)
        _log(tool, "ok", slug=slug)
        return result
