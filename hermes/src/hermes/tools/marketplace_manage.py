"""Hermes — Tools MCP de mantenimiento del Marketplace (spec 026, tramo 1;
CAP-075, FR-091 de la 008).

Familia `marketplace_manage` (1.2.0).

Tools:
  ha_marketplace_acknowledge_critical — reconoce un aviso crítico (dos pasos)
  ha_marketplace_ignore_repository    — deja de avisar de un retirado (dos pasos)
  ha_marketplace_remove_repository    — quita un personalizado no instalado (dos pasos)
  ha_marketplace_refresh_repository   — HA vuelve a pedir su información a GitHub (dos pasos)

POR QUÉ
-------
Las cuatro cambian el catálogo o los avisos del Marketplace y ninguna toca
ficheros de /config ni instala nada. Aun así van en dos pasos (criterio del
supervisor: todo lo que escribe): reconocer e ignorar no tienen comando que
los deshaga en HA 2026.11.1, quitar cambia la lista y refrescar sale a GitHub
y gasta su límite. Todo lo que HA rechazaría y Hermes puede saber antes se
rechaza sin token, y el token se ata a lo leído en la vista previa (`estado`
de la 018): si cambia antes de confirmar, no se hace nada.

Añadir repositorios, instalar, fijar versión y mostrar betas NO tienen tool:
HA exige que el usuario de HA que manda el comando haya aceptado el aviso de
riesgos del Marketplace, y el de Hermes (el del Supervisor) no puede
aceptarlo (DESVIACIÓN DV-1 de la 026, duda D-29). Estas cuatro no lo exigen.

Los textos de terceros (`name`, `reason`, `link`, `removal_type`) salen
recortados y marcados con `_third_party_text`, y toda la salida pasa por
`tapar_en_estructura` (la parte de usuario de cualquier URL, como en la 030).
"""

from __future__ import annotations

import functools
from typing import Any

from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes.ha import HAClient
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    resolve_confirmation_token,
)
from hermes.tools._common import requires_ready
from hermes.tools._logs import ArgumentoInvalido
from hermes.tools._marketplace_write import (
    SIN_BACKUP,
    ErrorMarketplace,
    buscar_por_nombre,
    carga_ignorar,
    carga_quitar,
    carga_reconocer,
    carga_refrescar,
    criticos,
    entrada_critica,
    entrada_retirada,
    registrar,
    repositorio_por_id,
    resumen,
    retirados,
    terceros,
    validar_full_name,
    validar_repository_id,
    ws_escritura,
)
from hermes.tools._store import tapar_en_estructura, texto_de_terceros

_NO_ENCONTRADO = {
    "error": "repository_not_found",
    "detail": (
        "No repository with that id in the Marketplace list. Use the id from "
        "ha_marketplace_list_repositories (installed_only=false for the whole "
        "catalogue)."
    ),
}

_IRREVERSIBLE = (
    "Home Assistant 2026.11 has no command to undo it (neither has Hermes)."
)


def register(
    mcp: object,
    ha_client: HAClient,
    *,
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
) -> None:
    """Registra las cuatro tools de mantenimiento del Marketplace.

    `response_max_bytes` se acepta por uniformidad con el resto de
    `register`: ninguna devuelve listas que haya que recortar.
    """
    del response_max_bytes
    ready = requires_ready(ha_client)

    def _salida(fn: Any) -> Any:
        """Última capa: ningún texto de lo que devuelven lleva la parte de
        usuario de una URL (`esquema://algo@`), venga de donde venga (un
        `link` o un `reason` de terceros, un error de HA). Las tools nunca
        lanzan: un `ErrorMarketplace` es su respuesta. `functools.wraps`
        conserva nombre, firma y anotaciones del esquema MCP."""
        @functools.wraps(fn)
        async def envoltura(*args: Any, **kwargs: Any) -> Any:
            try:
                return tapar_en_estructura(await fn(*args, **kwargs))
            except ErrorMarketplace as exc:
                return tapar_en_estructura(exc.payload)
        return envoltura

    def _rechazo(tool: str, respuesta: dict[str, Any], categoria: Any = None) -> dict[str, Any]:
        registrar(tool, f"rejected:{respuesta['error']}", categoria)
        return respuesta

    async def _leer(tool: str, lectura: Any) -> Any:
        """Una lectura de la vista previa; su error, ya traducido, se
        registra y sale tal cual."""
        try:
            return await lectura
        except ErrorMarketplace as exc:
            registrar(tool, "error")
            raise exc

    async def _confirmar(
        tool: str,
        token: str,
        args: dict[str, Any],
        estado: Any,
        sufijo: str,
        carga: dict[str, Any],
        categoria: Any,
    ) -> tuple[dict[str, Any] | None, Any]:
        """Resuelve el token con el estado releído y envía el comando.
        Devuelve `(error, resultado de HA)`; con error, nada más que hacer."""
        valido, error, _ = await resolve_confirmation_token(token, tool, args, estado=estado)
        if not valido:
            return _rechazo(tool, {"error": error}, categoria), None
        try:
            resultado = await ws_escritura(ha_client, sufijo, carga)
        except ErrorMarketplace as exc:
            await complete_confirmation_token(
                token, success=False, error=str(exc.payload.get("error")))
            registrar(tool, "error", categoria)
            return exc.payload, None
        return None, resultado

    async def _repositorio(tool: str, repository_id: str) -> dict[str, Any] | None:
        return await _leer(tool, repositorio_por_id(ha_client, repository_id))

    # ── Reconocer un aviso crítico ──

    @mcp.tool()
    @ready
    @_salida
    async def ha_marketplace_acknowledge_critical(
        repository: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Acknowledge a critical repository of the Marketplace (HACS before
        Home Assistant 2026.11): marks its critical notice as seen and clears
        its Repairs issue. Two steps: the first call returns a preview and a
        confirmation_token; repeat it with the same `repository` and the
        token. It cannot be undone, and it installs or uninstalls nothing
        (Home Assistant already removed the repository when it was flagged).
        Does not work with HACS 2.x (Home Assistant 2026.10 or older).

        Args:
            repository: The owner/repo full name from
                ha_marketplace_list_critical.
            confirmation_token: Token from the preview.

        Returns:
            Without token: {"confirmation_token", "preview"}, or an error:
            not_critical, already_acknowledged. With token: {"result": "ok",
            "entry"}. reason and link are third-party text.
        """
        tool = "ha_marketplace_acknowledge_critical"
        try:
            repository = validar_full_name(repository)
        except ArgumentoInvalido as exc:
            return _rechazo(tool, exc.respuesta())
        args = {"repository": repository}

        entrada = buscar_por_nombre(await _leer(tool, criticos(ha_client)), repository)
        if entrada is None:
            return _rechazo(tool, {
                "error": "not_critical",
                "detail": "That repository is not in the list of critical "
                          "repositories (ha_marketplace_list_critical).",
            })
        if entrada.get("acknowledged") is True:
            return _rechazo(tool, {
                "error": "already_acknowledged",
                "detail": "That critical repository is already acknowledged.",
            })
        vista = entrada_critica(entrada)
        estado = {"entry": vista}

        if not confirmation_token:
            preview = {
                "action": "acknowledge_critical",
                "entry": vista,
                "effect": (
                    "Home Assistant marks this critical notice as seen and "
                    "removes its Repairs issue. It installs, uninstalls and "
                    "runs nothing."
                ),
                "reversible": False,
                "note": _IRREVERSIBLE,
                "backup": SIN_BACKUP,
                **terceros(None),
                "_third_party_text": texto_de_terceros(["entry.reason", "entry.link"]),
            }
            registrar(tool, "preview")
            return await create_confirmation_token(tool, args, preview=preview, estado=estado)

        # HA compara el nombre con `==`: se envía el que guarda, no el que
        # escribió el cliente (pueden diferir en mayúsculas).
        error, resultado = await _confirmar(
            tool, confirmation_token, args, estado, "critical/acknowledge",
            carga_reconocer(str(entrada.get("repository"))), None)
        if error is not None:
            return error
        # HA devuelve la lista entera tal como queda: solo esta entrada.
        queda = buscar_por_nombre(resultado if isinstance(resultado, list) else [], repository)
        result: dict[str, Any] = {
            "result": "ok",
            "entry": entrada_critica(queda) if queda else None,
            "_third_party_text": texto_de_terceros(["entry.reason", "entry.link"]),
        }
        await complete_confirmation_token(confirmation_token, success=True, result={"result": "ok"})
        registrar(tool, "ok")
        return result

    # ── Ignorar un retirado ──

    @mcp.tool()
    @ready
    @_salida
    async def ha_marketplace_ignore_repository(
        repository_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Ignore the removal of a Marketplace (HACS before Home Assistant
        2026.11) repository that was removed from the catalogue: Home
        Assistant stops warning about the removal and keeps the repository.
        Only for a repository listed by ha_marketplace_list_removed that is
        not critical (a critical one is acknowledged with
        ha_marketplace_acknowledge_critical). Two steps: the first call
        returns a preview and a confirmation_token; repeat it with the token.
        It cannot be undone through the API. Does not work with HACS 2.x.

        Args:
            repository_id: Repository id from ha_marketplace_list_repositories.
            confirmation_token: Token from the preview.

        Returns:
            Without token: {"confirmation_token", "preview"}, or an error:
            repository_not_found, repository_not_removed, critical_repository.
            With token: {"result": "ok", "repository"}.
        """
        tool = "ha_marketplace_ignore_repository"
        try:
            repository_id = validar_repository_id(repository_id)
        except ArgumentoInvalido as exc:
            return _rechazo(tool, exc.respuesta())
        args = {"repository_id": repository_id}

        repo = await _repositorio(tool, repository_id)
        if repo is None:
            return _rechazo(tool, dict(_NO_ENCONTRADO))
        categoria = repo.get("category")
        nombre = repo.get("full_name")
        retirada = buscar_por_nombre(await _leer(tool, retirados(ha_client)), nombre)
        critica = buscar_por_nombre(await _leer(tool, criticos(ha_client)), nombre)
        if critica is not None or (retirada or {}).get("removal_type") == "critical":
            return _rechazo(tool, {
                "error": "critical_repository",
                "detail": (
                    "This repository is flagged as critical. Critical ones are "
                    "not ignored: acknowledge its notice with "
                    "ha_marketplace_acknowledge_critical."
                ),
            }, categoria)
        if retirada is None:
            return _rechazo(tool, {
                "error": "repository_not_removed",
                "detail": (
                    "This repository is not in the list of repositories removed "
                    "from the catalogue (ha_marketplace_list_removed), so there "
                    "is no removal to ignore."
                ),
            }, categoria)
        vista = entrada_retirada(retirada)
        estado = {"full_name": nombre, "category": categoria, "removed": vista}

        if not confirmation_token:
            preview = {
                "action": "ignore_repository",
                "repository": resumen(repo),
                "removed": vista,
                "effect": (
                    "Home Assistant stops warning that this repository was "
                    "removed from the catalogue and does not take it off the "
                    "list. Nothing is installed, uninstalled or updated."
                ),
                "reversible": False,
                "note": _IRREVERSIBLE,
                "backup": SIN_BACKUP,
                **terceros(repo.get("custom")),
                "_third_party_text": texto_de_terceros(
                    ["repository.name", "removed.reason", "removed.removal_type",
                     "removed.link"]),
            }
            registrar(tool, "preview", categoria)
            return await create_confirmation_token(tool, args, preview=preview, estado=estado)

        error, _ = await _confirmar(
            tool, confirmation_token, args, estado, "repository/ignore",
            carga_ignorar(repository_id), categoria)
        if error is not None:
            return error
        result = {
            "result": "ok",
            "repository": {"id": repository_id, "full_name": nombre},
            "hint": "It no longer appears in ha_marketplace_list_removed.",
        }
        await complete_confirmation_token(confirmation_token, success=True, result=result)
        registrar(tool, "ok", categoria)
        return result

    # ── Quitar un personalizado ──

    @mcp.tool()
    @ready
    @_salida
    async def ha_marketplace_remove_repository(
        repository_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Remove a custom repository from the Marketplace (HACS before Home
        Assistant 2026.11) list. Only custom repositories (added by hand, not
        from the default catalogue) that are not installed: an installed one
        must be uninstalled first in the Marketplace. Two steps: the first
        call returns a preview and a confirmation_token; repeat it with the
        token. Removes nothing from /config. Does not work with HACS 2.x.

        Args:
            repository_id: Repository id from ha_marketplace_list_repositories.
            confirmation_token: Token from the preview.

        Returns:
            Without token: {"confirmation_token", "preview"}, or an error:
            repository_not_found, not_custom_repository, repository_installed.
            With token: {"result": "ok", "repository"}.
        """
        tool = "ha_marketplace_remove_repository"
        try:
            repository_id = validar_repository_id(repository_id)
        except ArgumentoInvalido as exc:
            return _rechazo(tool, exc.respuesta())
        args = {"repository_id": repository_id}

        repo = await _repositorio(tool, repository_id)
        if repo is None:
            return _rechazo(tool, dict(_NO_ENCONTRADO))
        categoria = repo.get("category")
        if repo.get("custom") is not True:
            # Uno del catálogo por defecto volvería con la siguiente descarga
            # del catálogo: quitarlo no haría lo que el usuario cree.
            return _rechazo(tool, {
                "error": "not_custom_repository",
                "detail": (
                    "Only custom repositories can be removed: this one comes "
                    "from the default catalogue and would come back with its "
                    "next download."
                ),
            }, categoria)
        if repo.get("installed") is not False:
            # HA lo rechaza (`repository_installed`): olvidarlo dejaría sus
            # ficheros funcionando sin actualizaciones.
            return _rechazo(tool, {
                "error": "repository_installed",
                "detail": (
                    "Home Assistant refuses to remove an installed repository. "
                    "Uninstall it first from the Marketplace UI."
                ),
            }, categoria)
        estado = {
            "full_name": repo.get("full_name"), "category": categoria,
            "custom": repo.get("custom"), "installed": repo.get("installed"),
        }

        if not confirmation_token:
            preview = {
                "action": "remove_repository",
                "repository": resumen(repo),
                "effect": (
                    "Home Assistant takes this custom repository off the "
                    "Marketplace list. It is not installed, so no file under "
                    "/config changes. It can be added again later from the "
                    "Marketplace UI."
                ),
                "backup": SIN_BACKUP,
                **terceros(repo.get("custom")),
                "_third_party_text": texto_de_terceros(["repository.name"]),
            }
            registrar(tool, "preview", categoria)
            return await create_confirmation_token(tool, args, preview=preview, estado=estado)

        error, _ = await _confirmar(
            tool, confirmation_token, args, estado, "repositories/remove",
            carga_quitar(repository_id), categoria)
        if error is not None:
            return error
        result = {
            "result": "ok",
            "repository": {"id": repository_id, "full_name": repo.get("full_name")},
        }
        await complete_confirmation_token(confirmation_token, success=True, result=result)
        registrar(tool, "ok", categoria)
        return result

    # ── Refrescar ──

    @mcp.tool()
    @ready
    @_salida
    async def ha_marketplace_refresh_repository(
        repository_id: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Refresh the information of a Marketplace (HACS before Home
        Assistant 2026.11) repository: Home Assistant asks GitHub again (it
        uses its rate limit) and stores what it gets, such as the available
        version. Installs and updates nothing. Two steps: the first call
        returns a preview and a confirmation_token; repeat it with the token.
        Does not work with HACS 2.x.

        Args:
            repository_id: Repository id from ha_marketplace_list_repositories.
            confirmation_token: Token from the preview.

        Returns:
            Without token: {"confirmation_token", "preview"}, or an error:
            repository_not_found. With token: {"result": "ok", "repository"}
            read back (null with a hint if it could not be read), or
            github_rate_limited.
        """
        tool = "ha_marketplace_refresh_repository"
        try:
            repository_id = validar_repository_id(repository_id)
        except ArgumentoInvalido as exc:
            return _rechazo(tool, exc.respuesta())
        args = {"repository_id": repository_id}

        repo = await _repositorio(tool, repository_id)
        if repo is None:
            return _rechazo(tool, dict(_NO_ENCONTRADO))
        categoria = repo.get("category")
        estado = {"full_name": repo.get("full_name"), "category": categoria}

        if not confirmation_token:
            preview = {
                "action": "refresh_repository",
                "repository": resumen(repo),
                "effect": (
                    "Home Assistant asks GitHub again for this repository and "
                    "stores what it gets (description, versions). Nothing is "
                    "installed or updated."
                ),
                "contacts_github": True,
                "note": "It uses the GitHub rate limit of Home Assistant.",
                "backup": SIN_BACKUP,
                **terceros(repo.get("custom")),
                "_third_party_text": texto_de_terceros(["repository.name"]),
            }
            registrar(tool, "preview", categoria)
            return await create_confirmation_token(tool, args, preview=preview, estado=estado)

        error, _ = await _confirmar(
            tool, confirmation_token, args, estado, "repository/refresh",
            carga_refrescar(repository_id), categoria)
        if error is not None:
            return error
        result: dict[str, Any] = {"result": "ok"}
        try:
            releido = await repositorio_por_id(ha_client, repository_id)
        except ErrorMarketplace:
            releido = None
        if releido is not None:
            result["repository"] = resumen(releido)
            result["_third_party_text"] = texto_de_terceros(["repository.name"])
        else:
            result["repository"] = None
            result["hint"] = (
                "Refreshed, but it could not be read back. Read it with "
                "ha_marketplace_get_repository."
            )
        await complete_confirmation_token(confirmation_token, success=True, result={"result": "ok"})
        registrar(tool, "ok", categoria)
        return result
