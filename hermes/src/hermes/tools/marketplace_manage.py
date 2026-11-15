"""Hermes — Tools MCP de mantenimiento del Marketplace (spec 026, tramos 1 y
2; CAP-075, FR-091 de la 008).

Familia `marketplace_manage` (1.2.0).

Tools:
  ha_marketplace_acknowledge_critical — reconoce un aviso crítico (dos pasos)
  ha_marketplace_ignore_repository    — deja de avisar de un retirado (dos pasos)
  ha_marketplace_remove_repository    — quita un personalizado no instalado (dos pasos)
  ha_marketplace_refresh_repository   — HA vuelve a pedir su información a GitHub (dos pasos)
  ha_marketplace_uninstall            — desinstala uno instalado, con backup antes (dos pasos)

POR QUÉ
-------
Las cuatro cambian el catálogo o los avisos del Marketplace y ninguna toca
ficheros de /config ni instala nada. Aun así van en dos pasos (criterio del
supervisor: todo lo que escribe): reconocer e ignorar no tienen comando que
los deshaga en HA 2026.11.1, quitar cambia la lista y refrescar sale a GitHub
y gasta su límite. Todo lo que HA rechazaría y Hermes puede saber antes se
rechaza sin token, y el token se ata a lo leído en la vista previa (`estado`
de la 018): si cambia antes de confirmar, no se hace nada.

Desinstalar (tramo 2) va en esta misma familia (decisión D-2 del
supervisor): con una sola tool no merecía familia propia. Es la única que
borra ficheros de /config, así que antes hace un backup parcial de la
configuración sin la base de datos y, si falla, no envía nada a HA.

Añadir repositorios, instalar, fijar versión y mostrar betas NO tienen tool:
HA exige que el usuario de HA que manda el comando haya aceptado el aviso de
riesgos del Marketplace, y el de Hermes (el del Supervisor) no puede
aceptarlo (DESVIACIÓN DV-1 de la 026, duda D-29). Estas cinco no lo exigen.

Converge (T031, T032): esa protección de HA tiene dos huecos que Hermes no
puede cerrar aquí. Una automatización o un script (sin usuario) instalan con
`update.install` si alguna persona aceptó el aviso: la vista previa de
crearlos lo avisa (`tools/ha.py`, `menciona_update_install`). Y el interruptor
«pre-release» de cada repositorio activa betas sin el aviso: por
`ha_call_service` pide token (`_marketplace_write.comprobar_interruptor_beta`).

Los textos de terceros (`name`, `reason`, `link`, `removal_type`) salen
recortados y marcados con `_third_party_text`, y toda la salida pasa por
`tapar_en_estructura` (la parte de usuario de cualquier URL, como en la 030).
"""

from __future__ import annotations

import functools
from typing import Any

from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    resolve_confirmation_token,
)
from hermes.tools._common import requires_ready
from hermes.tools._logs import ArgumentoInvalido
from hermes.tools._marketplace_write import (
    ESPERA_DESINSTALAR,
    SIN_BACKUP,
    ErrorMarketplace,
    backup_previo,
    buscar_por_nombre,
    carga_desinstalar,
    carga_ignorar,
    carga_quitar,
    carga_reconocer,
    carga_refrescar,
    criticos,
    entradas_del_dominio,
    entrada_critica,
    entrada_retirada,
    lo_que_puede_romper,
    lo_que_quita,
    nombre_backup,
    registrar,
    reinicio_probable,
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


def _resultado_desconocido(causa: BaseException | None) -> bool:
    """True si Hermes no puede saber si HA hizo la desinstalación (T037).

    Un plazo agotado o una conexión caída esperando la respuesta no dicen
    nada del resultado. Una respuesta de error de HA (con `code`) sí es un
    error de verdad, y una orden que seguro no salió (`sent is False`,
    contrato de la 022) no hizo nada."""
    if causa is None:
        return False
    if getattr(causa, "sent", None) is False:
        return False
    if isinstance(causa, TimeoutError):
        return True
    return (isinstance(causa, HAConnectionError)
            and causa.code is None and causa.status is None)


def register(
    mcp: object,
    ha_client: HAClient,
    *,
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
) -> None:
    """Registra las cinco tools de mantenimiento del Marketplace.

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
        espera: int | None = None,
    ) -> tuple[dict[str, Any] | None, Any]:
        """Resuelve el token con el estado releído y envía el comando.
        Devuelve `(error, resultado de HA)`; con error, nada más que hacer."""
        valido, error, _ = await resolve_confirmation_token(token, tool, args, estado=estado)
        if not valido:
            return _rechazo(tool, {"error": error}, categoria), None
        try:
            resultado = await ws_escritura(ha_client, sufijo, carga, espera)
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
                # T034: `marketplace/repository/ignore` solo añade el nombre a
                # `ignored_repositories`; el aviso `removed_<id>` ya creado
                # (no persistente) sigue en Repairs hasta el próximo
                # reinicio de Core, y entonces ya no se vuelve a crear.
                "repairs_issue": (
                    "An existing Repairs issue about this removal is NOT "
                    "deleted now: it stays until Home Assistant Core restarts, "
                    "and then it is not created again."
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
        must be uninstalled first (ha_marketplace_uninstall). Two steps: the first
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
                    "Uninstall it first with ha_marketplace_uninstall."
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
                    "Marketplace UI, which needs GitHub connected in the "
                    "Marketplace."
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

    # ── Desinstalar (tramo 2) ──

    @mcp.tool()
    @ready
    @_salida
    async def ha_marketplace_uninstall(
        repository_id: str,
        backup: bool = True,
        confirmation_token: str | None = None,
    ) -> object:
        """Uninstall a repository installed from the Marketplace (HACS before
        Home Assistant 2026.11): Home Assistant deletes its files under
        /config (a card also loses its Lovelace resource) and the Marketplace
        update entity of the repository. An integration with config entries
        (ignored ones too) is refused: delete them first with
        ha_delete_config_entry. Two steps: the first call returns a preview
        (what is removed, whether Core will need a restart, what may stop
        working, the backup) and a confirmation_token; repeat it with the
        same arguments and the token. With backup=true (default), Hermes
        first asks the Supervisor for a partial backup of the Home Assistant
        configuration without the database (not encrypted) and uninstalls
        only if it finishes; if it fails, nothing is sent to Home Assistant.
        Hermes does not restart Core (sv_restart_core). Does not work with
        HACS 2.x (Home Assistant 2026.10 or older).

        Args:
            repository_id: Repository id from ha_marketplace_list_repositories.
            backup: Make the partial backup first (default true).
            confirmation_token: Token from the preview.

        Returns:
            Without token: {"confirmation_token", "preview"}, or an error:
            repository_not_found, repository_not_installed, repository_in_use.
            With token: {"result": "ok", "repository", "restart_required",
            "backup"}, backup_failed (nothing sent to Home Assistant), or
            outcome_unknown (no answer in time: it may have been uninstalled;
            read it back with ha_marketplace_get_repository).
        """
        tool = "ha_marketplace_uninstall"
        try:
            repository_id = validar_repository_id(repository_id)
        except ArgumentoInvalido as exc:
            return _rechazo(tool, exc.respuesta())
        if not isinstance(backup, bool):
            return _rechazo(tool, ArgumentoInvalido(
                "backup", "backup must be true or false.").respuesta())
        args = {"repository_id": repository_id, "backup": backup}

        repo = await _repositorio(tool, repository_id)
        if repo is None:
            return _rechazo(tool, dict(_NO_ENCONTRADO))
        categoria = repo.get("category")
        if repo.get("installed") is not True:
            return _rechazo(tool, {
                "error": "repository_not_installed",
                "detail": "That repository is not installed: there is nothing "
                          "to uninstall.",
            }, categoria)
        domain = repo.get("domain")
        if categoria == "integration" and isinstance(domain, str) and domain:
            # HA lo rechaza igual (`repository_in_use`): sus entradas, también
            # las ignoradas, ejecutan el código instalado. Se mira antes para
            # no hacer un backup en balde ni dar un token que no sirve.
            entradas = await _leer(tool, entradas_del_dominio(ha_client, domain))
            if entradas:
                return _rechazo(tool, {
                    "error": "repository_in_use",
                    "detail": (
                        "This integration still has config entries (ignored "
                        "ones count too): Home Assistant refuses to uninstall "
                        "it while they exist."
                    ),
                    "config_entries": [
                        {"entry_id": e.get("entry_id"), "source": e.get("source")}
                        for e in entradas
                    ],
                    "hint": "Delete them first with ha_delete_config_entry, "
                            "then ask for the preview again.",
                }, categoria)
        # T036: también la carpeta y el dominio. Si cambian entre la vista
        # previa y la confirmación, `removes.path` ya no es lo que se borraría
        # y el token no vale.
        estado = {
            "full_name": repo.get("full_name"),
            "category": categoria,
            "installed_version": repo.get("installed_version"),
            "domain": domain,
            "local_path": repo.get("local_path"),
        }

        if not confirmation_token:
            if backup:
                copia: dict[str, Any] = {
                    "will_create": True,
                    "kind": (
                        "partial backup of the Home Assistant configuration, "
                        "without the database, apps or folders"
                    ),
                    "name_pattern": "hermes_marketplace_uninstall_<UTC date and time>",
                    "encrypted": False,
                    "if_it_fails": (
                        "nothing is sent to Home Assistant, the token is spent "
                        "and the answer is backup_failed"
                    ),
                }
            else:
                copia = {
                    "will_create": False,
                    "reason": "backup=false",
                    "warning": (
                        "The Marketplace keeps no copy of what it uninstalls: "
                        "without a backup the files cannot be brought back "
                        "from one."
                    ),
                }
            preview = {
                "action": "uninstall",
                "repository": {**resumen(repo), "domain": domain},
                "removes": {
                    **lo_que_quita(repo),
                    # T036: con GitHub conectado (o un tema sin nombre de
                    # fichero) HA refresca el repositorio justo antes de
                    # borrar (`marketplace_repository_uninstall`).
                    "path_note": (
                        "With GitHub connected, Home Assistant refreshes the "
                        "repository just before deleting, which may recompute "
                        "this path."
                    ),
                },
                "restart": reinicio_probable(repo),
                "may_break": lo_que_puede_romper(repo),
                "effect": (
                    "Home Assistant deletes the installed files of this "
                    "repository and keeps it in the Marketplace list as not "
                    "installed (it can be installed again from the Marketplace "
                    "UI)."
                ),
                "backup": copia,
                **terceros(repo.get("custom")),
                "_third_party_text": texto_de_terceros(["repository.name", "removes.path"]),
            }
            registrar(tool, "preview", categoria)
            return await create_confirmation_token(tool, args, preview=preview, estado=estado)

        valido, error, _ = await resolve_confirmation_token(
            confirmation_token, tool, args, estado=estado)
        if not valido:
            return _rechazo(tool, {"error": error}, categoria)

        hecho_backup: dict[str, Any] = {"created": False}
        if backup:
            try:
                hecho_backup = {"created": True, **await backup_previo(
                    ha_client, nombre_backup("uninstall"))}
            except ErrorMarketplace as exc:
                # SC-005: sin backup terminado no se envía el comando de HA.
                await complete_confirmation_token(
                    confirmation_token, success=False, error="backup_failed")
                registrar(tool, "error", categoria)
                return {
                    **exc.payload,
                    "sent_to_home_assistant": False,
                    "hint": (
                        "Nothing was uninstalled. Check the backup with "
                        "sv_get_job_status (job_id) or sv_list_backups, then ask "
                        "for a new preview."
                    ),
                }

        try:
            await ws_escritura(ha_client, "repository/uninstall",
                               carga_desinstalar(repository_id), ESPERA_DESINSTALAR)
        except ErrorMarketplace as exc:
            causa = exc.__cause__
            if _resultado_desconocido(causa):
                # T037: plazo agotado o conexión caída con la orden enviada. El
                # manejador sigue corriendo en HA: puede haber desinstalado.
                # Contrato de `sent` (spec 022): `None` = no se sabe. El token
                # queda gastado para que un reintento no lo repita a ciegas.
                await complete_confirmation_token(
                    confirmation_token, success=False, error="outcome_unknown")
                registrar(tool, "outcome_unknown", categoria)
                return {
                    "error": "outcome_unknown",
                    "detail": (
                        "Home Assistant did not answer in time. The uninstall "
                        "MAY have happened anyway: it keeps running in Home "
                        "Assistant."
                    ),
                    "sent": getattr(causa, "sent", None),
                    "backup": hecho_backup,
                    "hint": (
                        "Read it back with ha_marketplace_get_repository "
                        "(installed) before trying again."
                    ),
                }
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc.payload.get("error")))
            registrar(tool, "error", categoria)
            # El backup ya está hecho: que se sepa a qué volver.
            fallo = {**exc.payload, "backup": hecho_backup}
            if getattr(causa, "sent", None) is False:
                fallo["sent"] = False
            return fallo

        result: dict[str, Any] = {"result": "ok", "backup": hecho_backup}
        try:
            releido = await repositorio_por_id(ha_client, repository_id)
        except ErrorMarketplace:
            releido = None
        if releido is not None:
            result["repository"] = resumen(releido)
            result["_third_party_text"] = texto_de_terceros(["repository.name"])
            # HA marca `pending-restart` cuando crea el aviso de Repairs.
            reiniciar = releido.get("status") == "pending-restart"
            result["restart_required"] = reiniciar
            if reiniciar:
                result["next"] = ("Restart Core with sv_restart_core when it suits "
                                  "you; Hermes does not restart it.")
        else:
            result["repository"] = None
            result["restart_required"] = None
            result["hint"] = (
                "Uninstalled, but it could not be read back. Check it with "
                "ha_marketplace_get_repository and Repairs (ha_list_repairs)."
            )
        await complete_confirmation_token(confirmation_token, success=True, result={"result": "ok"})
        registrar(tool, "ok", categoria)
        return result
