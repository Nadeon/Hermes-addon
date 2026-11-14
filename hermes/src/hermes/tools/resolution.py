"""Hermes — Tools MCP del centro de resolución del Supervisor.

Tools:
  sv_get_resolution                 — estado de soporte/salud, issues, sugerencias y checks
  sv_dismiss_resolution_issue       — descarta un issue (con token)
  sv_dismiss_resolution_suggestion  — descarta una sugerencia SIN aplicarla (con token)

Hermes nunca APLICA sugerencias (`POST /resolution/suggestion/{uuid}`):
varias borran datos o reinician (`clear_full_backup`, `execute_remove`,
`execute_reset`, `execute_reboot`…) y quedan fuera de alcance por decisión
del mantenedor. Un test recorre el código de las tools y falla si aparece.
"""

from __future__ import annotations

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
from hermes.tools._validation import InvalidIdentifier, validate_identifier

logger = structlog.get_logger(__name__)

_EFECTO_ISSUE = (
    "Removes this issue from the Supervisor. It may come back on the next "
    "check if the condition persists."
)
_EFECTO_SUGERENCIA = (
    "Removes this suggestion from the Supervisor without applying it. It may "
    "come back on the next check if the condition persists. Hermes never "
    "applies Supervisor suggestions."
)


def _texto(valor: Any) -> Any:
    """Pasa por `redact_secrets` todo texto anidado.

    `reference` es texto libre del Supervisor (un slug, una ruta, un mensaje)
    bajo una clave que no parece sensible, así que `redact_structure` no lo
    taparía; `redact_secrets` sí reconoce `password=…` o `token: …` dentro.
    """
    if isinstance(valor, str):
        return redact_secrets(valor)
    if isinstance(valor, dict):
        return {k: _texto(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_texto(v) for v in valor]
    return valor


def _escalar(valor: Any) -> Any:
    return valor if isinstance(valor, (str, int, float, bool)) or valor is None else None


def _entrada(raw: dict[str, Any], con_auto: bool) -> dict[str, Any]:
    """Issue o sugerencia con los campos del contrato y nada más."""
    out = {
        "uuid": _escalar(raw.get("uuid")),
        "type": _escalar(raw.get("type")),
        "context": _escalar(raw.get("context")),
        "reference": _escalar(raw.get("reference")),
        "reference_extra": raw.get("reference_extra"),
    }
    if con_auto:
        out["auto"] = raw.get("auto") if isinstance(raw.get("auto"), bool) else None
    return out


def _normalizar(data: Any) -> dict[str, Any] | None:
    """Construye la respuesta de `/resolution/info`; None si la forma es rara."""
    if not isinstance(data, dict):
        return None

    def _lista(clave: str) -> list[Any]:
        valor = data.get(clave)
        return valor if isinstance(valor, list) else []

    out = {
        "unsupported": [x for x in _lista("unsupported") if isinstance(x, str)],
        "unhealthy": [x for x in _lista("unhealthy") if isinstance(x, str)],
        "issues": [_entrada(x, False) for x in _lista("issues") if isinstance(x, dict)],
        "suggestions": [_entrada(x, True) for x in _lista("suggestions")
                        if isinstance(x, dict)],
        "checks": [{"slug": _escalar(x.get("slug")),
                    "enabled": x.get("enabled") if isinstance(x.get("enabled"), bool)
                    else None}
                   for x in _lista("checks") if isinstance(x, dict)],
    }
    return _texto(redact_structure(out))


def register(mcp: object, ha_client: HAClient) -> None:
    """Registra las tools de resolución del Supervisor."""

    async def _leer() -> dict[str, Any]:
        try:
            data = await ha_client.sv_request("GET", "/resolution/info")
        except HAConnectionError as exc:
            return {"error": str(exc)}
        info = _normalizar(data)
        if info is None:
            return {"error": "unexpected_response from /resolution/info"}
        return info

    @mcp.tool()
    async def sv_get_resolution() -> object:
        """Read the Supervisor resolution center (read-only).

        Returns `unsupported` and `unhealthy` reasons, `issues`
        (uuid, type, context, reference, reference_extra), `suggestions`
        (the same plus `auto`) and `checks` (slug, enabled). Type names are
        returned as the Supervisor sends them. Use
        `sv_dismiss_resolution_issue` / `sv_dismiss_resolution_suggestion`
        to dismiss one; Hermes never applies suggestions.
        """
        return await _leer()

    async def _descartar(tool_name: str, clase: str, campo: str, uuid: str,
                         confirmation_token: str | None) -> dict[str, Any]:
        # El uuid va a la ruta del Supervisor: se valida antes de nada para
        # que `../` o `/` no puedan cambiar de endpoint.
        try:
            validate_identifier(uuid, field=campo)
        except InvalidIdentifier as exc:
            return {"error": "invalid_identifier", "detail": str(exc)}
        args = {campo: uuid}

        if not confirmation_token:
            # La preview solo se emite si el uuid existe AHORA: un token para
            # algo que no está haría que la confirmación mintiera.
            info = await _leer()
            if "error" in info:
                return info
            lista = info["issues"] if clase == "issue" else info["suggestions"]
            item = next((x for x in lista if x.get("uuid") == uuid), None)
            if item is None:
                return {"error": "not_found", campo: uuid}
            preview = {
                campo: uuid,
                "type": item.get("type"),
                "context": item.get("context"),
                "reference": item.get("reference"),
                "action": "dismiss",
                "effect": _EFECTO_ISSUE if clase == "issue" else _EFECTO_SUGERENCIA,
            }
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}
        try:
            # DELETE descarta; nunca POST, que APLICARÍA la sugerencia.
            await ha_client.sv_request("DELETE", f"/resolution/{clase}/{uuid}")
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False,
                                              error=str(exc))
            return {"error": str(exc)}
        result = {"result": "ok"}
        await complete_confirmation_token(confirmation_token, success=True, result=result)
        logger.info(f"{tool_name}_ok", uuid=uuid)
        return result

    @mcp.tool()
    async def sv_dismiss_resolution_issue(
        issue_uuid: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Dismiss a Supervisor resolution issue (requires confirmation_token).

        First call returns a preview (type, context, reference) and a token;
        repeat with the same `issue_uuid` and the token to dismiss it. A
        dismissed issue may come back on the next check if the condition
        persists. Unknown uuid → `not_found`, no token.
        """
        return await _descartar("sv_dismiss_resolution_issue", "issue", "issue_uuid",
                                issue_uuid, confirmation_token)

    @mcp.tool()
    async def sv_dismiss_resolution_suggestion(
        suggestion_uuid: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Dismiss a Supervisor suggestion WITHOUT applying it (requires confirmation_token).

        First call returns a preview and a token; repeat with the same
        `suggestion_uuid` and the token to dismiss it. Dismissing does not
        run the suggested action, and it may come back on the next check.
        Hermes never applies Supervisor suggestions. Unknown uuid →
        `not_found`, no token.
        """
        return await _descartar("sv_dismiss_resolution_suggestion", "suggestion",
                                "suggestion_uuid", suggestion_uuid, confirmation_token)
