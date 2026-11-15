"""Hermes — Tools MCP de los repositorios de la tienda de apps (spec 030,
tramo 1; CAP-082).

Familia `app_store` (1.2.0).

Tools:
  sv_list_store_repositories  — repositorios de la tienda, con sus apps
  sv_add_store_repository     — añade un repositorio (dos pasos)
  sv_remove_store_repository  — quita un repositorio (dos pasos)
  sv_repair_store_repository  — vuelve a clonar un repositorio roto
  sv_reload_store             — actualiza todos los repositorios y el catálogo

POR QUÉ
-------
Añadir un repositorio es la vía de entrada de código de terceros: sus apps
pasan a poder instalarse y, una vez instaladas, se ejecutan con los permisos
que declaren. Por eso va en dos pasos, la vista previa dice la URL EXACTA que
se enviará (con la parte de usuario de una URL con credenciales tapada) y Hermes no
descarga nada para enseñarla: quien clona es el Supervisor, al confirmar
(research R-4).

Quitar uno deja sus apps sin poder instalarse; el Supervisor 2026.11.0
rechaza los integrados y los que tienen apps instaladas, así que Hermes lo
dice antes y sin token (dar un token para algo imposible sería mentir), y ata
el token al estado leído (`estado` de la 018): si entre la vista previa y la
confirmación se instala una app de ese repositorio, el token no vale.

Reparar y recargar no piden token (research R-6): recargar es un `git pull`
de lo ya añadido y reparar clona en una carpeta temporal y solo sustituye el
clon si la descarga sale bien. Ninguna instala, borra datos ni para nada.

El evento de log `app_store_action` lleva la tool, el resultado y el `slug`
del repositorio; nunca la URL (puede llevar credenciales y nombra servidores
privados) ni textos del repositorio.
"""

from __future__ import annotations

import functools
import re
import time
from typing import Any
from urllib.parse import urlsplit

import structlog

from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    redact_structure,
    resolve_confirmation_token,
    validate_confirmation_token,
)
from hermes.tools._common import ajustar_lista_a_bytes, sobre_de_lista
from hermes.tools._eco_supervisor import sin_eco_del_supervisor
from hermes.tools._logs import ArgumentoInvalido
from hermes.tools._store import (
    URLS_DE_CORE,
    anotar_recarga_de_tienda,
    candado_de_recarga,
    credenciales_de_url,
    es_integrado,
    redactar_mensaje,
    slug_de_repositorio,
    tapar_credenciales,
    tapar_en_estructura,
    texto_de_terceros,
)
from hermes.tools._validation import InvalidIdentifier, validate_slug
from hermes.tools.addons import _LONG_OP_TIMEOUT

logger = structlog.get_logger(__name__)

_EVENTO = "app_store_action"

# La forma que admite el Supervisor 2026.11.0 (`store/validate.py`,
# `RE_REPOSITORY`): URL sin espacios y `#rama` opcional.
_RE_REPOSITORIO = re.compile(r"^(?P<url>[^#\s]+)(?:#(?P<branch>[\w\-./]+))?$")
# Ninguna URL real de un repositorio se acerca; es un tope contra entradas
# absurdas, no una regla del Supervisor.
_LONGITUD_MAX = 2048

DETALLE_URL = (
    "repository must be an http(s) URL of a git repository, optionally "
    "followed by #branch."
)

_AVISO_TERCEROS = (
    "Third-party code: this repository is not reviewed by Home Assistant nor "
    "by Hermes. Once added, its apps become installable, and an installed app "
    "runs with the permissions it declares. Adding it does not install any "
    "app. When you confirm, the Supervisor clones it and refuses it if it is "
    "not a valid app repository."
)

_CAMPOS_REPO = ["repository.name", "repository.url", "repository.maintainer"]


def validar_url_repositorio(valor: Any) -> tuple[str, str | None]:
    """(URL completa sin espacios en los extremos, rama o `None`).

    Más estricta que el Supervisor en un punto (research R-4): exige `http`
    o `https` y un servidor, aunque `vol.Url` admita otros esquemas; es lo que
    usa un repositorio de apps y deja fuera `file://` y similares. El
    `detail` del error nunca copia el valor (puede llevar credenciales).
    """
    if not isinstance(valor, str):
        raise ArgumentoInvalido("repository", DETALLE_URL)
    url = valor.strip()
    if not url or len(url) > _LONGITUD_MAX:
        raise ArgumentoInvalido("repository", DETALLE_URL)
    m = _RE_REPOSITORIO.match(url)
    if not m:
        raise ArgumentoInvalido("repository", DETALLE_URL)
    try:
        partes = urlsplit(m.group("url"))
        servidor = partes.hostname
        # `https://u:p/ss@servidor/r`: `urlsplit` toma `u` como servidor y
        # `p` como puerto (no numérico), y la vista previa enseñaba un
        # servidor falso con el usuario a la vista. Un puerto que no es un
        # número no es una URL válida (convergencia de la 030, T034).
        _ = partes.port  # lanza ValueError si no es un número
    except ValueError:
        raise ArgumentoInvalido("repository", DETALLE_URL) from None
    if partes.scheme not in ("http", "https") or not servidor:
        raise ArgumentoInvalido("repository", DETALLE_URL)
    return url, m.group("branch")


def _ya_anadido(url: str, repos: list[dict[str, Any]]) -> str | None:
    """El `slug` del repositorio que ya es esta URL, o `None`.

    Como el Supervisor: las URL de `home-assistant/apps` y `…/addons` son
    `core`, y el `slug` de uno propio es el hash de la URL en minúsculas. Se
    compara además con `source` sin distinguir mayúsculas, que es lo mismo
    para uno propio y además reconoce los integrados de URL fija.
    """
    baja = url.lower()
    if baja in URLS_DE_CORE:
        return "core"
    for repo in repos:
        source = repo.get("source")
        if isinstance(source, str) and source.lower() == baja:
            return str(repo.get("slug"))
    slug = slug_de_repositorio(url)
    if any(repo.get("slug") == slug for repo in repos):
        return slug
    return None


def _apps_por_repositorio(apps: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    por_repo: dict[str, list[dict[str, Any]]] = {}
    for app in apps:
        if isinstance(app, dict):
            por_repo.setdefault(str(app.get("repository")), []).append(app)
    return por_repo


def _resumen_repositorio(
    repo: dict[str, Any], apps: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """Los campos de data-model, con `source` y `url` tapadas.

    `apps` son las del catálogo de ESTE repositorio, o `None` si el catálogo
    no se pudo leer (entonces los recuentos son `null`, no cero: cero diría
    que se puede quitar sin desinstalar nada).
    """
    slug = str(repo.get("slug"))
    return {
        "slug": slug,
        "name": repo.get("name"),
        "source": tapar_credenciales(repo.get("source")),
        "url": tapar_credenciales(repo.get("url")),
        "maintainer": repo.get("maintainer"),
        "builtin": es_integrado(slug),
        "apps_count": None if apps is None else len(apps),
        "installed_apps": None if apps is None else sorted(
            str(a.get("slug")) for a in apps if a.get("installed") is True),
    }


def _orden(item: dict[str, Any]) -> tuple[bool, str]:
    # Integrados primero; dentro de cada grupo, por `slug`.
    return (not item["builtin"], item["slug"])


def register(
    mcp: object,
    ha_client: HAClient,
    *,
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
) -> None:
    """Registra las cinco tools de repositorios de la tienda."""

    def _log(tool: str, outcome: str, **campos: Any) -> None:
        logger.info(_EVENTO, tool=tool, outcome=outcome, **campos)

    def _rechazo(tool: str, respuesta: dict[str, Any], **campos: Any) -> dict[str, Any]:
        _log(tool, f"rejected:{respuesta['error']}", **campos)
        return respuesta

    def _redactar(texto: str, repos: list[dict[str, Any]]) -> str:
        """`texto` con las credenciales de las URL de `repos` tapadas
        LITERALMENTE (también un token suelto, fuera de la URL) y después la
        redacción general. Para los errores en los que el Supervisor pudo
        nombrar cualquier repositorio (recargar, el catálogo)."""
        for repo in repos:
            for campo in ("source", "url"):
                valor = repo.get(campo)
                if isinstance(valor, str):
                    texto = redactar_mensaje(texto, valor)
        return redactar_mensaje(texto)

    def _error(tool: str, exc: Exception, url: str | None = None, **campos: Any) -> dict[str, Any]:
        _log(tool, "error", **campos)
        return {"error": redactar_mensaje(str(exc), url)}

    def _slug_invalido(slug: Any) -> dict[str, Any] | None:
        try:
            validate_slug(slug, field="repository")
            return None
        except InvalidIdentifier as exc:
            return {"error": "invalid_identifier", "detail": str(exc)}

    def _no_encontrado() -> dict[str, Any]:
        return {
            "error": "repository_not_found",
            "detail": "No store repository with that slug. List them with "
                      "sv_list_store_repositories.",
        }

    async def _repositorios() -> list[dict[str, Any]]:
        data = await ha_client.sv_request("GET", "/store/repositories")
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []

    async def _apps() -> list[dict[str, Any]]:
        data = await ha_client.sv_request("GET", "/store/addons")
        apps = data.get("addons", []) if isinstance(data, dict) else []
        return [a for a in apps if isinstance(a, dict)]

    async def _repositorio(slug: str) -> dict[str, Any] | None:
        """Un repositorio por `slug`, o `None` si el Supervisor da 404."""
        try:
            data = await ha_client.sv_request("GET", f"/store/repositories/{slug}")
        except HAConnectionError as exc:
            if exc.status == 404:
                return None
            raise
        return data if isinstance(data, dict) else None

    def _instaladas(slug: str, apps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            ({"slug": str(a.get("slug")), "name": a.get("name")}
             for a in apps
             if a.get("repository") == slug and a.get("installed") is True),
            key=lambda a: a["slug"],
        )

    def _tapar_salida(fn: Any) -> Any:
        """Última capa de cada tool de repositorios (extra b del supervisor
        del programa): ningún texto de lo que devuelve lleva la parte de
        usuario de una URL (`esquema://algo@`), venga de la lista, de una
        vista previa, de un error o de un mensaje del Supervisor. Las
        funciones de dentro ya tapan lo que conocen; esto cubre lo que no
        (un nombre o un mantenedor con una URL, un error de otra URL).

        `functools.wraps` conserva el nombre, la firma y las anotaciones: el
        esquema MCP y las anotaciones de la tool no cambian.
        """
        @functools.wraps(fn)
        async def envoltura(*args: Any, **kwargs: Any) -> Any:
            return tapar_en_estructura(await fn(*args, **kwargs))
        return envoltura

    # ── Listar ──

    @mcp.tool()
    @_tapar_salida
    async def sv_list_store_repositories(repository: str | None = None) -> object:
        """List the repositories of the Supervisor app (add-on) store: each
        one offers apps that can be installed (read only).

        `builtin` repositories come with the Supervisor and cannot be
        removed; a repository with `installed_apps` cannot be removed until
        those apps are uninstalled. `name`, `url` and `maintainer` are written
        by third parties (see `_third_party_text`). The credentials of a
        repository URL (user, password or token before `@`) are shown as
        ***REDACTED***. To list the apps
        themselves, use sv_list_addons(installed_only=false).

        Args:
            repository: Optional repository slug; returns only that one.

        Returns:
            {"count", "items", "truncated", "_third_party_text"}; each item
            has slug, name, source, url, maintainer, builtin, apps_count and
            installed_apps (null, with "apps_unavailable", if the app catalog
            could not be read). With `repository`: {"repository": {...},
            "_third_party_text"} or {"error": "repository_not_found"}.
        """
        tool = "sv_list_store_repositories"
        if repository is not None:
            if (err := _slug_invalido(repository)):
                return _rechazo(tool, err)
            try:
                repo = await _repositorio(repository)
            except HAConnectionError as exc:
                return _error(tool, exc, repository=repository)
            if repo is None:
                return _rechazo(tool, _no_encontrado(), repository=repository)
            try:
                apps: list[dict[str, Any]] | None = _apps_por_repositorio(
                    await _apps()).get(repository, [])
                sin_apps = None
            except HAConnectionError as exc:
                apps, sin_apps = None, _redactar(str(exc), [repo])
            out: dict[str, Any] = {
                "repository": _resumen_repositorio(repo, apps),
                "_third_party_text": texto_de_terceros(_CAMPOS_REPO),
            }
            if sin_apps is not None:
                out["apps_unavailable"] = sin_apps
            _log(tool, "ok", repository=repository)
            return redact_structure(out)

        try:
            repos = await _repositorios()
        except HAConnectionError as exc:
            return _error(tool, exc)
        # La lista de repositorios no depende del catálogo de apps: si este
        # falla, se devuelve igual con los recuentos a `null` y el motivo.
        cabecera: dict[str, Any] = {
            "_third_party_text": texto_de_terceros(["name", "url", "maintainer"]),
        }
        try:
            por_repo: dict[str, list[dict[str, Any]]] | None = _apps_por_repositorio(await _apps())
        except HAConnectionError as exc:
            por_repo = None
            cabecera["apps_unavailable"] = _redactar(str(exc), repos)
        items = sorted(
            (_resumen_repositorio(
                r, None if por_repo is None else por_repo.get(str(r.get("slug")), []))
             for r in repos),
            key=_orden,
        )
        items = redact_structure(items)

        def construir(parte: list[Any], recortada: bool) -> dict[str, Any]:
            return sobre_de_lista(parte, truncated=recortada, **cabecera)

        out = ajustar_lista_a_bytes(items, construir, response_max_bytes)
        _log(tool, "ok", count=out["count"])
        return out

    # ── Añadir ──

    @mcp.tool()
    @_tapar_salida
    async def sv_add_store_repository(
        repository: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Add a repository to the Supervisor app (add-on) store. Two steps:
        the first call returns a preview and a confirmation_token; repeat it
        with the same `repository` and the token to add it.

        THIRD-PARTY CODE: the repository is not reviewed by Home Assistant
        nor by Hermes; once added, its apps become installable. Adding it
        does not install any app (use sv_install_addon for that, after
        reviewing them). The preview downloads nothing: it shows the exact
        URL that will be sent (its credentials, the user part before `@`,
        are shown as ***REDACTED***; the confirmation sends them unchanged),
        the server and the branch. The Supervisor clones the repository when
        you confirm and rejects it if it is not a valid app repository.

        Args:
            repository: Git repository URL, `https://…` or `http://…`,
                optionally followed by `#branch`.
            confirmation_token: Token from the preview.

        Returns:
            Without token: {"confirmation_token", "preview"}, or
            {"error": "repository_already_added", "repository": <slug>}.
            With token: {"result": "ok", "repository": {...},
            "_third_party_text", "next"}.
        """
        tool = "sv_add_store_repository"
        try:
            url, rama = validar_url_repositorio(repository)
        except ArgumentoInvalido as exc:
            return _rechazo(tool, exc.respuesta())
        # Al log, solo el `slug` que le dará el Supervisor: nunca la URL.
        slug = slug_de_repositorio(url)
        args: dict[str, Any] = {"repository": url}

        if not confirmation_token:
            try:
                repos = await _repositorios()
            except HAConnectionError as exc:
                return _error(tool, exc, url, repository=slug)
            existente = _ya_anadido(url, repos)
            if existente is not None:
                return _rechazo(tool, {
                    "error": "repository_already_added",
                    "repository": existente,
                    "detail": "This repository is already in the store.",
                }, repository=existente)
            servidor = urlsplit(url.split("#", 1)[0]).hostname
            preview: dict[str, Any] = {
                "action": "add_store_repository",
                "repository": tapar_credenciales(url),
                "host": servidor,
                "branch": rama,
                "credentials_hidden": credenciales_de_url(url) is not None,
                "warning": _AVISO_TERCEROS,
                "note": (
                    "Nothing is downloaded until you confirm. Review the "
                    "repository and its apps before installing any of them."
                ),
            }
            _log(tool, "preview", repository=slug)
            return await create_confirmation_token(tool, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool, args)
        if not valid:
            return _rechazo(tool, {"error": error}, repository=slug)
        # T047: añadir vuelve a leer todas las fichas. Convergencia 2
        # (T052): bajo el candado común de las recargas, con el inicio
        # tomado ya con él cogido y anotado solo si termina bien.
        async with candado_de_recarga():
            inicio = time.time()
            try:
                await ha_client.sv_request(
                    "POST", "/store/repositories",
                    json_body={"repository": url},
                    timeout_seconds=_LONG_OP_TIMEOUT,
                )
            except HAConnectionError as exc:
                # Las credenciales de la URL, tapadas primero (así la URL
                # sigue legible); después, sin el eco de la carga (cierre de
                # seguridad).
                mensaje = sin_eco_del_supervisor(redactar_mensaje(str(exc), url),
                                                 {"repository": url})
                await complete_confirmation_token(confirmation_token, success=False,
                                                  error=mensaje)
                _log(tool, "error", repository=slug)
                return {"error": mensaje}
            anotar_recarga_de_tienda(inicio)
        result: dict[str, Any] = {"result": "ok"}
        try:
            repos = await _repositorios()
            nuevo_slug = _ya_anadido(url, repos)
            nuevo = next((r for r in repos if r.get("slug") == nuevo_slug), None)
        except HAConnectionError:
            nuevo = None
        if nuevo is not None:
            result["repository"] = redact_structure({
                "slug": nuevo.get("slug"),
                "name": nuevo.get("name"),
                "url": tapar_credenciales(nuevo.get("url")),
                "maintainer": nuevo.get("maintainer"),
            })
            result["_third_party_text"] = texto_de_terceros(_CAMPOS_REPO)
            result["next"] = "Install its apps with sv_install_addon after reviewing them."
        else:
            result["repository"] = None
            result["hint"] = (
                "Added, but it could not be read back. List the repositories "
                "with sv_list_store_repositories."
            )
        await complete_confirmation_token(confirmation_token, success=True, result=result)
        _log(tool, "ok", repository=slug)
        return result

    # ── Quitar ──

    async def _estado_para_quitar(
        tool: str, slug: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
        """(error, repositorio, apps del catálogo). El error ya va listo."""
        try:
            repo = await _repositorio(slug)
        except HAConnectionError as exc:
            return _error(tool, exc, repository=slug), None, []
        if repo is None:
            return _rechazo(tool, _no_encontrado(), repository=slug), None, []
        try:
            apps = await _apps()
        except HAConnectionError as exc:
            # Sin saber qué apps están instaladas no se puede prometer que el
            # Supervisor lo aceptará: sin token (fail-closed).
            return _error(tool, exc, repository=slug), None, []
        return None, repo, apps

    @mcp.tool()
    @_tapar_salida
    async def sv_remove_store_repository(
        repository: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Remove a repository from the Supervisor app (add-on) store. Two
        steps: the first call returns a preview and a confirmation_token;
        repeat it with the token to remove it.

        Its apps will no longer be installable; it can be added again later.
        Built-in repositories cannot be removed (`builtin_repository`), and
        neither can a repository with installed apps (`repository_in_use`,
        with the list): uninstall them first with sv_uninstall_addon. Both are
        rejected without a token. If an app of the repository is installed
        between the preview and the confirmation, the token is refused.

        Args:
            repository: Repository slug (from sv_list_store_repositories).
            confirmation_token: Token from the preview.

        Returns:
            Without token: {"confirmation_token", "preview"} or an error.
            With token: {"result": "ok", "repository": <slug>}.
        """
        tool = "sv_remove_store_repository"
        if (err := _slug_invalido(repository)):
            return _rechazo(tool, err)
        args: dict[str, Any] = {"repository": repository}

        error, repo, apps = await _estado_para_quitar(tool, repository)
        if error is not None:
            return error
        assert repo is not None
        instaladas = _instaladas(repository, apps)
        estado = {"repository": repo, "installed_apps": instaladas}

        if not confirmation_token:
            if es_integrado(repository):
                return _rechazo(tool, {
                    "error": "builtin_repository",
                    "detail": "Built-in repositories cannot be removed.",
                }, repository=repository)
            if instaladas:
                return _rechazo(tool, {
                    "error": "repository_in_use",
                    "installed_apps": redact_structure(instaladas),
                    "detail": (
                        "The Supervisor refuses to remove a repository with "
                        "installed apps. Uninstall them first with "
                        "sv_uninstall_addon."
                    ),
                }, repository=repository)
            resumen = _resumen_repositorio(repo, None)
            preview: dict[str, Any] = {
                "action": "remove_store_repository",
                "repository": redact_structure({
                    k: resumen[k] for k in ("slug", "name", "source", "url", "maintainer")}),
                "apps_count": sum(1 for a in apps if a.get("repository") == repository),
                "effect": (
                    "Its apps will no longer be installable. You can add it "
                    "again later."
                ),
                "_third_party_text": texto_de_terceros(_CAMPOS_REPO),
            }
            _log(tool, "preview", repository=repository)
            return await create_confirmation_token(tool, args, preview=preview, estado=estado)

        # El token se ata al repositorio y a sus apps instaladas leídos en la
        # vista previa (spec 018): si algo cambió, no se borra nada.
        valid, error_token, _ = await resolve_confirmation_token(
            confirmation_token, tool, args, estado=estado)
        if not valid:
            return _rechazo(tool, {"error": error_token}, repository=repository)
        # T047: quitar vuelve a leer todas las fichas; convergencia 2
        # (T052): bajo el candado común de las recargas.
        async with candado_de_recarga():
            inicio = time.time()
            try:
                await ha_client.sv_request(
                    "DELETE", f"/store/repositories/{repository}",
                    timeout_seconds=_LONG_OP_TIMEOUT,
                )
            except HAConnectionError as exc:
                mensaje = _redactar(str(exc), [repo])
                await complete_confirmation_token(confirmation_token, success=False,
                                                  error=mensaje)
                _log(tool, "error", repository=repository)
                return {"error": mensaje}
            anotar_recarga_de_tienda(inicio)
        result = {"result": "ok", "repository": repository}
        await complete_confirmation_token(confirmation_token, success=True, result=result)
        _log(tool, "ok", repository=repository)
        return result

    # ── Reparar y recargar ──

    @mcp.tool()
    @_tapar_salida
    async def sv_repair_store_repository(repository: str) -> object:
        """Repair a repository of the Supervisor app (add-on) store whose
        local copy is broken: the Supervisor clones it again into a temporary
        folder and replaces the old copy only if the download succeeds.
        Installs, updates and removes nothing. Not available for the `local`
        repository.

        Args:
            repository: Repository slug (from sv_list_store_repositories).

        Returns:
            {"result": "ok", "repository": <slug>} or an error.
        """
        tool = "sv_repair_store_repository"
        if (err := _slug_invalido(repository)):
            return _rechazo(tool, err)
        if repository == "local":
            # El Supervisor no puede volver a clonar una carpeta local
            # (`StoreRepositoryLocalCannotReset`).
            return _rechazo(tool, {
                "error": "not_supported",
                "detail": "The local repository cannot be repaired.",
            }, repository=repository)
        try:
            repo = await _repositorio(repository)
        except HAConnectionError as exc:
            return _error(tool, exc, repository=repository)
        if repo is None:
            return _rechazo(tool, _no_encontrado(), repository=repository)
        try:
            await ha_client.sv_request(
                "POST", f"/store/repositories/{repository}/repair",
                timeout_seconds=_LONG_OP_TIMEOUT,
            )
        except HAConnectionError as exc:
            mensaje = _redactar(str(exc), [repo])
            _log(tool, "error", repository=repository)
            return {"error": mensaje}
        _log(tool, "ok", repository=repository)
        return {"result": "ok", "repository": repository}

    @mcp.tool()
    @_tapar_salida
    async def sv_reload_store() -> object:
        """Reload the Supervisor app (add-on) store: updates every repository
        (git pull) and re-reads the app catalog, so new apps and new versions
        appear. Installs and updates no app. It may take a while.

        Returns:
            {"result": "ok", "hint"} or an error.
        """
        tool = "sv_reload_store"
        # Convergencia T047: la hora de INICIO, antes de mandar la petición.
        # Convergencia 2 (T052): con el candado común de las recargas cogido,
        # para que no empiece hasta que termine otra recarga de Hermes.
        async with candado_de_recarga():
            inicio = time.time()
            try:
                await ha_client.sv_request(
                    "POST", "/store/reload", timeout_seconds=_LONG_OP_TIMEOUT)
            except HAConnectionError as exc:
                fallo: HAConnectionError | None = exc
            else:
                fallo = None
                anotar_recarga_de_tienda(inicio)
        if fallo is not None:
            # El error puede nombrar cualquier repositorio (y su token suelto):
            # se leen para tapar sus credenciales. Si tampoco se pueden leer,
            # queda el tapado de toda URL del texto.
            try:
                repos = await _repositorios()
            except HAConnectionError:
                repos = []
            _log(tool, "error")
            return {"error": _redactar(str(fallo), repos)}
        _log(tool, "ok")
        return {
            "result": "ok",
            "hint": "List the catalog with sv_list_addons(installed_only=false).",
        }
