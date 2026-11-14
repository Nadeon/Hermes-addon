"""Hermes — Tools MCP para Repairs (avisos de Home Assistant).

Usa los comandos WS `repairs/list_issues` y `repairs/ignore_issue`, que
existen sin cambios desde 2024.10 y no exigen administrador.

Fuera de alcance a propósito: `repairs/get_issue_data` (datos internos de la
integración, que pueden llevar información sensible) y los flujos de
reparación (escrituras con efectos propios de cada integración).
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    redact_secrets,
    redact_structure,
    validate_confirmation_token,
)
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)

# Orden de gravedad para listar primero lo más urgente. Son los tres valores
# de `IssueSeverity` en HA; uno desconocido (versión futura) va al final en
# vez de romper la lista.
_SEVERIDADES: tuple[str, ...] = ("critical", "error", "warning")

# Lista blanca de campos que se devuelven. Se copia campo a campo en lugar de
# devolver el issue entero: si HA añade algo como `issue_data` (datos
# internos), no debe salir por defecto (FR-012).
_CAMPOS: tuple[str, ...] = (
    "domain", "issue_id", "issue_domain", "severity", "is_fixable",
    "breaks_in_ha_version", "created", "ignored", "dismissed_version",
    "translation_key", "translation_placeholders", "learn_more_url",
)


def _invalid(field: str, detail: str) -> str:
    return json.dumps(
        {"error": "invalid_argument", "field": field, "detail": detail}
    )


def _redactar(valor: Any) -> Any:
    """Redacta por clave (`redact_structure`) y por patrón en cada texto.

    Las dos capas hacen falta: la clave tapa `{"token": "…"}`, pero una URL
    con credenciales bajo una clave inocente (`url`) solo la detecta el
    patrón de `redact_secrets`.
    """
    valor = redact_structure(valor)
    if isinstance(valor, dict):
        return {k: _redactar(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_redactar(v) for v in valor]
    if isinstance(valor, str):
        return redact_secrets(valor)
    return valor


def _resumen(issue: dict[str, Any]) -> dict[str, Any]:
    out = {campo: issue.get(campo) for campo in _CAMPOS}
    out["translation_placeholders"] = _redactar(
        issue.get("translation_placeholders")
    )
    return out


def _rango(issue: dict[str, Any]) -> int:
    sev = issue.get("severity")
    return _SEVERIDADES.index(sev) if sev in _SEVERIDADES else len(_SEVERIDADES)


async def _leer_issues(ha_client: HAClient) -> list[dict[str, Any]]:
    """Lee los issues; lanza si la respuesta no tiene la forma esperada.

    Lanzar en vez de devolver lista vacía es lo que hace fail-closed a
    `ha_ignore_repair`: una lectura rara no puede convertirse en «no existe».
    """
    raw: Any = await ha_client.ws_send({"type": "repairs/list_issues"})
    issues = raw.get("issues") if isinstance(raw, dict) else None
    if not isinstance(issues, list):
        raise HAConnectionError("unexpected response from repairs/list_issues")
    return [i for i in issues if isinstance(i, dict)]


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de Repairs."""

    ready = requires_ready(ha_client)

    # ── ha_list_repairs ───────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_repairs(
        include_ignored: bool = False,
        domain: str | None = None,
        severity: str | None = None,
    ) -> object:
        """List the issues shown in Home Assistant's Repairs panel.

        Ordered by severity (critical, error, warning). Ignored issues are
        hidden unless include_ignored=true. Translation placeholders are
        redacted; internal issue data is never returned.

        Args:
            include_ignored: Also return issues the user has ignored.
            domain: Only issues of this integration domain.
            severity: Only issues of this severity: critical, error or warning.

        Returns:
            JSON {"count": n, "issues": [{domain, issue_id, issue_domain,
            severity, is_fixable, breaks_in_ha_version, created, ignored,
            dismissed_version, translation_key, translation_placeholders,
            learn_more_url}]}.
        """
        if severity is not None and severity not in _SEVERIDADES:
            return _invalid("severity", "must be one of: critical, error, warning")

        try:
            issues = await _leer_issues(ha_client)
        except HAConnectionError as exc:
            logger.error("ha_list_repairs_ws_error", error=str(exc))
            return json.dumps({"error": str(exc)})

        elegidos = [
            i for i in issues
            if (include_ignored or not i.get("ignored"))
            and (domain is None or i.get("domain") == domain)
            and (severity is None or i.get("severity") == severity)
        ]
        # `sorted` es estable: dentro de una gravedad se respeta el orden de HA.
        elegidos.sort(key=_rango)
        logger.info("ha_list_repairs_ok", count=len(elegidos))
        return json.dumps(
            {"count": len(elegidos), "issues": [_resumen(i) for i in elegidos]},
            ensure_ascii=False,
        )

    # ── ha_ignore_repair ──────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_ignore_repair(
        domain: str,
        issue_id: str,
        ignore: bool = True,
        confirmation_token: str | None = None,
    ) -> object:
        """Ignore (or un-ignore with ignore=false) a Repairs issue.

        Two steps: without confirmation_token returns a preview and a token;
        repeat the same call with the token to apply. If the issue is already
        in the requested state, returns {"result": "unchanged"} and no token.
        Ignoring hides the warning (it may announce a future breaking change)
        but does not fix anything; it is reversible with ignore=false.

        Args:
            domain: Integration domain of the issue.
            issue_id: Issue id, as returned by ha_list_repairs.
            ignore: True to ignore, false to show it again.
            confirmation_token: Token from the preview call.

        Returns:
            Preview + token, {"result": "unchanged", "ignored": bool},
            {"result": "ok", "ignored": bool}, or {"error": ...}.
        """
        if not isinstance(domain, str) or not domain.strip():
            return _invalid("domain", "must be a non-empty string")
        if not isinstance(issue_id, str) or not issue_id.strip():
            return _invalid("issue_id", "must be a non-empty string")
        if not isinstance(ignore, bool):
            return _invalid("ignore", "must be a boolean")

        args = {"domain": domain, "issue_id": issue_id, "ignore": ignore}

        if not confirmation_token:
            # Se lee el estado real antes de emitir nada: el token solo tiene
            # sentido si la llamada va a cambiar algo, y la vista previa tiene
            # que poder decir qué aviso se oculta y si anuncia una rotura.
            try:
                issues = await _leer_issues(ha_client)
            except HAConnectionError as exc:
                logger.warning(
                    "ha_ignore_repair_preview_read_failed",
                    domain=domain, issue_id=issue_id, error=str(exc),
                )
                return json.dumps(
                    {"error": "preview_unavailable", "detail": str(exc)}
                )

            issue = next(
                (i for i in issues
                 if i.get("domain") == domain and i.get("issue_id") == issue_id),
                None,
            )
            if issue is None:
                return json.dumps(
                    {"error": "not_found", "domain": domain, "issue_id": issue_id}
                )
            if bool(issue.get("ignored")) == ignore:
                return json.dumps({"result": "unchanged", "ignored": ignore})

            if ignore:
                efecto = (
                    "Hides this issue from Repairs. Reversible: call again "
                    "with ignore=false."
                )
            else:
                efecto = (
                    "Shows this issue again in Repairs. Reversible: call "
                    "again with ignore=true."
                )
            preview = {
                "domain": domain,
                "issue_id": issue_id,
                "severity": issue.get("severity"),
                "breaks_in_ha_version": issue.get("breaks_in_ha_version"),
                "action": "ignore" if ignore else "unignore",
                "effect": efecto,
            }
            token_data = await create_confirmation_token(
                "ha_ignore_repair", args, preview=preview
            )
            return json.dumps(token_data, ensure_ascii=False)

        valid, error = await validate_confirmation_token(
            confirmation_token, "ha_ignore_repair", args
        )
        if not valid:
            logger.warning(
                "ha_ignore_repair_token_invalid",
                domain=domain, issue_id=issue_id, reason=error,
            )
            return json.dumps({"error": error})

        try:
            await ha_client.ws_send({
                "type": "repairs/ignore_issue",
                "domain": domain,
                "issue_id": issue_id,
                "ignore": ignore,
            })
        except HAConnectionError as exc:
            logger.error(
                "ha_ignore_repair_ws_error",
                domain=domain, issue_id=issue_id, error=str(exc),
            )
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            if exc.code == "not_found":
                return json.dumps(
                    {"error": "not_found", "domain": domain, "issue_id": issue_id}
                )
            return json.dumps({"error": str(exc)})

        resultado = {"result": "ok", "ignored": ignore}
        await complete_confirmation_token(
            confirmation_token, success=True, result=resultado
        )
        logger.info(
            "ha_ignore_repair_ok", domain=domain, issue_id=issue_id, ignore=ignore
        )
        return json.dumps(resultado)
