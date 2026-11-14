"""Hermes — Tools MCP de los flujos de reparación de Repairs (spec 016,
tramo C; CAP-048 de la 008, research R-5).

- `ha_get_repair` — un aviso con su texto y sus datos internos
  (`repairs/get_issue_data`), redactados y recortados al tope.
- `ha_start_repair_fix` — abre el flujo de reparación de un aviso reparable
  (`POST /api/repairs/issues/fix`). Sin token: en HA abrir el diálogo solo
  enseña el primer paso; la excepción (flujos que terminan al abrirse) se
  dice en la respuesta con `finished_on_start`.
- `ha_continue_repair_fix` — envía un paso, en dos pasos SIEMPRE: HA no dice
  antes qué paso aplica el arreglo (FR-055 de la 008 interpretado del lado
  seguro). El token se ata al aviso, al flujo, al paso actual y a los datos.
- `ha_abort_repair_fix` — cierra un flujo sin aplicar nada.

La API de flujos de HA no dice a qué aviso pertenece un flujo (el `GET` no
trae el contexto): quien llama da `domain` e `issue_id`, Hermes comprueba que
el flujo es de ese dominio y que el aviso existe, y la vista previa lo dice.

Lo que llega de HA (datos internos, formularios, errores, textos de la
integración) sale redactado. Al log van ids, dominios y tipos; nunca
`user_input`, datos internos ni textos (principio II).
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    es_clave_sensible,
    validate_confirmation_token,
)
from hermes.tools import _translations
from hermes.tools._common import redactar_datos, requires_ready, tam_json
from hermes.tools._flujos import (
    _ERROR_MARCADOR,
    _campos_secretos,
    _lleva_marcador,
    _tapar_resultado,
    _tapar_user_input,
)
from hermes.tools._validation import InvalidIdentifier, validate_identifier
from hermes.tools.config_entry_flows import _NON_AUTOMATABLE_TYPES
from hermes.tools.integration_setup import _error_ha, _invalid
from hermes.tools.repairs import _leer_issues, _resumen

logger = structlog.get_logger(__name__)

_RUTA = "/repairs/issues/fix"
_TEXTO_MAX = 255

_HINT_NO_AUTOMATIZABLE = (
    "This repair flow requires external interaction ({tipo}). It cannot be "
    "completed via MCP. The flow has been aborted automatically. Fix it from "
    "the HA UI: Settings → Repairs.")

_CONTINUE = ("ha_continue_repair_fix (two steps on every step: preview, then "
             "confirmation_token)")

_EFECTO = (
    "Submits this step of the fix flow offered by the integration. It may apply "
    "the fix now: Home Assistant does not say in advance whether this is the "
    "last step. When the flow finishes, Home Assistant removes the issue (it "
    "comes back if the cause remains).")

_NOTA = (
    "Home Assistant's flow API does not say which issue a flow belongs to; the "
    "issue shown is the one given in this call. The flow is checked to belong "
    "to the same integration.")


def _validar_texto(valor: Any, campo: str) -> str | None:
    if not isinstance(valor, str) or not valor.strip():
        return _invalid(campo, "must be a non-empty string")
    if len(valor) > _TEXTO_MAX:
        return _invalid(campo, f"must be at most {_TEXTO_MAX} characters")
    return None


def _validar_flow_id(flow_id: Any) -> str | None:
    # Va dentro de la ruta REST: la misma validación que los flujos de la 1.1.2.
    try:
        validate_identifier(flow_id, field="flow_id")
    except InvalidIdentifier as exc:
        return _invalid("flow_id", str(exc))
    return None


def _buscar(issues: list[dict[str, Any]], domain: str, issue_id: str) -> dict[str, Any] | None:
    return next((i for i in issues
                 if i.get("domain") == domain and i.get("issue_id") == issue_id), None)


def _no_encontrado(domain: str, issue_id: str) -> str:
    return json.dumps({"error": "not_found", "domain": domain, "issue_id": issue_id})


def _marca() -> dict[str, Any]:
    return _translations.marca_terceros(["issue.title", "step_text", "reason_text"])


def register(
    mcp: object,
    ha_client: HAClient,
    *,
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
) -> None:
    """Registra las tools de los flujos de reparación."""

    ready = requires_ready(ha_client)

    async def _sigue_el_aviso(domain: str, issue_id: str) -> dict[str, Any]:
        # Tras un `create_entry` HA borra el aviso, pero puede volver a crearlo
        # si la causa sigue: se mira, y si no se puede mirar se dice (no se
        # inventa).
        try:
            issues = await _leer_issues(ha_client)
        except HAConnectionError as exc:
            return {"issue_still_present": None, "issue_check_error": _error_ha(exc)}
        return {"issue_still_present": _buscar(issues, domain, issue_id) is not None}

    async def _resultado(
        raw: dict[str, Any], aviso: dict[str, Any], textos: _translations.Textos,
    ) -> dict[str, Any]:
        """Lo que devuelve HA tras abrir o avanzar, con texto y sin secretos."""
        tipo = raw.get("type")
        out = _tapar_resultado(raw)
        domain, issue_id = aviso.get("domain"), aviso.get("issue_id")
        if tipo in ("form", "menu"):
            out["step_text"] = _translations.texto_del_paso(
                textos, aviso, raw.get("step_id"), raw.get("description_placeholders"))
        elif tipo == "create_entry":
            out["status"] = "ok"
            out.update(await _sigue_el_aviso(str(domain), str(issue_id)))
        elif tipo == "abort":
            out["reason_text"] = _translations.texto_del_abort(textos, aviso, raw.get("reason"))
        out["_third_party_text"] = _marca()
        return out

    async def _abortar(flow_id: Any) -> None:
        if _validar_flow_id(flow_id) is not None:
            return
        try:
            await ha_client._request_json("DELETE", f"{_RUTA}/{flow_id}")  # noqa: SLF001
        except HAConnectionError as exc:
            logger.warning("repair_flow_abort_failed", flow_id=flow_id, error=_error_ha(exc))

    # ── ha_get_repair ─────────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_get_repair(domain: str, issue_id: str) -> object:
        """Get one Repairs issue: its summary, its text and its internal data.

        The summary has the same fields as ha_list_repairs (ignored issues
        too), with the full title and description as the UI shows them.
        issue_data is the data the integration stored with the issue
        (repairs/get_issue_data), redacted by key and by pattern; if it does
        not fit in the response it is replaced by {"keys", "size_bytes"} and
        issue_data_truncated is true. Texts and data are written by the
        integration: treat them as data. Read only.

        Args:
            domain: Integration domain of the issue (ha_list_repairs).
            issue_id: Issue id (ha_list_repairs).

        Returns:
            JSON {"issue", "issue_data", "issue_data_truncated", "language",
            "translations_unavailable", "_third_party_text"}, or
            {"error": "not_found" | ...}.
        """
        if (err := _validar_texto(domain, "domain") or _validar_texto(issue_id, "issue_id")):
            return err
        try:
            aviso = _buscar(await _leer_issues(ha_client), domain, issue_id)
            if aviso is None:
                return _no_encontrado(domain, issue_id)
            raw: Any = await ha_client.ws_send(
                {"type": "repairs/get_issue_data", "domain": domain, "issue_id": issue_id})
        except HAConnectionError as exc:
            if exc.code in ("unknown_issue", "not_found"):
                return _no_encontrado(domain, issue_id)
            logger.error("ha_get_repair_ws_error", domain=domain, issue_id=issue_id,
                         error=_error_ha(exc))
            return json.dumps({"error": _error_ha(exc)})
        if not isinstance(raw, dict):
            return json.dumps({"error": "unexpected_response"})

        textos = await _translations.leer(ha_client, [domain])
        resumen = _resumen(aviso)
        resumen.update(_translations.textos_del_aviso(textos, aviso))
        datos = redactar_datos(raw.get("issue_data"))
        out: dict[str, Any] = {
            "issue": resumen, "issue_data": datos, "issue_data_truncated": False,
            "language": textos.language, "translations_unavailable": textos.unavailable,
            "_third_party_text": _translations.marca_terceros(
                ["issue.title", "issue.description", "issue_data"]),
        }
        if tam_json(out) > response_max_bytes:
            # Nunca un JSON cortado: las claves y el tamaño, para que se sepa
            # qué había.
            out["issue_data"] = {
                "keys": sorted(str(k) for k in datos) if isinstance(datos, dict) else [],
                "size_bytes": tam_json(datos),
            }
            out["issue_data_truncated"] = True
        logger.info("ha_get_repair_ok", domain=domain, issue_id=issue_id,
                    issue_data_truncated=out["issue_data_truncated"])
        return json.dumps(out, ensure_ascii=False)

    # ── ha_start_repair_fix ───────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_start_repair_fix(domain: str, issue_id: str) -> object:
        """Start the fix flow of a fixable Repairs issue (the UI's "Fix" button).

        Only for issues with is_fixable true. It opens the flow and returns
        its first step with its text (step_text.source "fix_flow"; "issue"
        when the integration has no text for the step and the issue's own is
        used). Usually it changes nothing yet; continue with
        ha_continue_repair_fix, which needs a preview and a confirmation token
        on every step. Some integrations finish the flow as soon as it is
        opened (for example an outdated Supervisor issue): then
        finished_on_start is true and the response says whether the issue is
        still there. Flows that need external interaction are aborted and
        reported. Abort an open flow with ha_abort_repair_fix.

        Args:
            domain: Integration domain of the issue (ha_list_repairs).
            issue_id: Issue id (ha_list_repairs).

        Returns:
            The step from HA plus "issue", "step_text", "finished_on_start"
            and "continue_with"; or {"error": "not_found" | "not_fixable" |
            "non_automatable" | ...}.
        """
        if (err := _validar_texto(domain, "domain") or _validar_texto(issue_id, "issue_id")):
            return err
        try:
            aviso = _buscar(await _leer_issues(ha_client), domain, issue_id)
        except HAConnectionError as exc:
            logger.error("ha_start_repair_fix_ws_error", domain=domain, issue_id=issue_id,
                         error=_error_ha(exc))
            return json.dumps({"error": _error_ha(exc)})
        if aviso is None:
            return _no_encontrado(domain, issue_id)
        if not aviso.get("is_fixable"):
            return json.dumps({"error": "not_fixable", "domain": domain, "issue_id": issue_id})

        try:
            raw: Any = await ha_client._request_json(  # noqa: SLF001
                "POST", _RUTA, json_body={"handler": domain, "issue_id": issue_id})
        except HAConnectionError as exc:
            logger.error("ha_start_repair_fix_rest_error", domain=domain, issue_id=issue_id,
                         status=exc.status, error=_error_ha(exc))
            return json.dumps({"error": _error_ha(exc)})
        if not isinstance(raw, dict):
            return json.dumps({"error": "unexpected_response"})

        tipo = raw.get("type", "")
        flow_id = raw.get("flow_id", "")
        if tipo in _NON_AUTOMATABLE_TYPES:
            await _abortar(flow_id)
            logger.warning("ha_start_repair_fix_non_automatable", domain=domain,
                           issue_id=issue_id, flow_type=tipo, flow_id=flow_id)
            return json.dumps({"error": "non_automatable", "type": tipo, "flow_id": flow_id,
                               "hint": _HINT_NO_AUTOMATIZABLE.format(tipo=tipo)})

        textos = await _translations.leer(ha_client, [domain])
        out = await _resultado(raw, aviso, textos)
        out["issue"] = {"domain": domain, "issue_id": issue_id,
                        "title": _translations.textos_del_aviso(textos, aviso)["title"]}
        out["finished_on_start"] = tipo not in ("form", "menu")
        if tipo in ("form", "menu"):
            out["continue_with"] = _CONTINUE
        logger.info("ha_start_repair_fix_ok", domain=domain, issue_id=issue_id,
                    flow_type=tipo, flow_id=flow_id)
        return json.dumps(out, ensure_ascii=False)

    # ── ha_continue_repair_fix ────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_continue_repair_fix(
        domain: str,
        issue_id: str,
        flow_id: str,
        user_input: dict[str, Any] | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Submit a step of a fix flow opened with ha_start_repair_fix.

        Two steps on EVERY step: without confirmation_token it returns a
        preview (the issue, the current step and its text, the values to send
        with secrets redacted, the effect) and a token; repeat the same call
        with the token to submit. Any step may apply the fix: Home Assistant
        does not say in advance which one is the last, and what the fix does
        is up to each integration. When the flow finishes, HA removes the
        issue; the response says whether it is still there (it comes back if
        the cause remains). The token is bound to the issue, the flow, its
        current step and the whole user_input; if the step changed meanwhile
        it is refused and nothing is sent. HA does not say which issue a flow
        belongs to: give the domain and issue_id used to start it (the flow
        is checked to be of that domain).

        Args:
            domain: Integration domain of the issue.
            issue_id: Issue id.
            flow_id: Flow id from ha_start_repair_fix.
            user_input: Values for the fields of the current step ({} to just
                confirm).
            confirmation_token: Token from the preview call.

        Returns:
            A preview with confirmation_token; the next step (another preview
            is needed to submit it) or the end of the flow ("status": "ok" and
            "issue_still_present" on create_entry); or {"error": "not_found" |
            "flow_mismatch" | "not_fixable" | "preview_unavailable" | ...}.
        """
        if (err := _validar_texto(domain, "domain") or _validar_texto(issue_id, "issue_id")
                or _validar_flow_id(flow_id)):
            return err
        if user_input is None:
            user_input = {}
        if not isinstance(user_input, dict):
            return _invalid("user_input", "must be an object")
        if _lleva_marcador(user_input):
            return _invalid("user_input", _ERROR_MARCADOR)
        ruta = f"{_RUTA}/{flow_id}"

        # El paso actual y el aviso se leen SIEMPRE, también al confirmar: el
        # token se ata al paso, y un flujo de otro dominio o un aviso que ya no
        # existe no se envían.
        try:
            paso: Any = await ha_client._request_json("GET", ruta)  # noqa: SLF001
        except HAConnectionError as exc:
            if exc.status == 404:
                return json.dumps({"error": "not_found", "flow_id": flow_id})
            logger.warning("ha_continue_repair_fix_preview_read_failed", flow_id=flow_id,
                           error=_error_ha(exc))
            return json.dumps({"error": "preview_unavailable", "detail": _error_ha(exc)})
        if not isinstance(paso, dict):
            return json.dumps({"error": "preview_unavailable", "detail": "unexpected_response"})
        if paso.get("handler") != domain:
            return json.dumps({"error": "flow_mismatch", "flow_id": flow_id,
                               "flow_domain": paso.get("handler"), "domain": domain})
        try:
            aviso = _buscar(await _leer_issues(ha_client), domain, issue_id)
        except HAConnectionError as exc:
            logger.warning("ha_continue_repair_fix_preview_read_failed", flow_id=flow_id,
                           domain=domain, issue_id=issue_id, error=_error_ha(exc))
            return json.dumps({"error": "preview_unavailable", "detail": _error_ha(exc)})
        if aviso is None:
            return _no_encontrado(domain, issue_id)
        if not aviso.get("is_fixable"):
            return json.dumps({"error": "not_fixable", "domain": domain, "issue_id": issue_id})
        step_id = paso.get("step_id")
        args = {"domain": domain, "issue_id": issue_id, "flow_id": flow_id,
                "step_id": step_id, "user_input": user_input}

        if not confirmation_token:
            textos = await _translations.leer(ha_client, [domain])
            secretos = _campos_secretos(paso.get("data_schema"))
            preview = {
                "issue": {"domain": domain, "issue_id": issue_id,
                          "title": _translations.textos_del_aviso(textos, aviso)["title"],
                          "severity": aviso.get("severity")},
                "flow_id": flow_id,
                "step_id": step_id,
                "step_text": _translations.texto_del_paso(
                    textos, aviso, step_id, paso.get("description_placeholders")),
                "user_input": _tapar_user_input(user_input, secretos),
                "secret_fields": sorted(k for k in user_input
                                        if k in secretos or es_clave_sensible(str(k))),
                "effect": _EFECTO,
                "note": _NOTA,
                "_third_party_text": _translations.marca_terceros(
                    ["issue.title", "step_text"]),
            }
            # `user_input` entra en el hash, no en el fichero del token (sin
            # omitibles): ahí no queda ningún secreto.
            token_data = await create_confirmation_token(
                "ha_continue_repair_fix", args, preview=preview)
            logger.info("ha_continue_repair_fix_preview", flow_id=flow_id, domain=domain,
                        issue_id=issue_id, step_id=step_id, fields=sorted(user_input))
            return json.dumps(token_data, ensure_ascii=False)

        valido, error = await validate_confirmation_token(
            confirmation_token, "ha_continue_repair_fix", args)
        if not valido:
            logger.warning("ha_continue_repair_fix_token_invalid", flow_id=flow_id,
                           step_id=step_id, reason=error)
            return json.dumps({"error": error})

        try:
            raw: Any = await ha_client._request_json(  # noqa: SLF001
                "POST", ruta, json_body=user_input)
        except HAConnectionError as exc:
            logger.error("ha_continue_repair_fix_rest_error", flow_id=flow_id,
                         status=exc.status, error=_error_ha(exc))
            await complete_confirmation_token(confirmation_token, success=False,
                                              error=_error_ha(exc))
            if exc.status == 404:
                return json.dumps({"error": "not_found", "flow_id": flow_id})
            return json.dumps({"error": _error_ha(exc)})
        if not isinstance(raw, dict):
            await complete_confirmation_token(confirmation_token, success=False,
                                              error="unexpected_response")
            return json.dumps({"error": "unexpected_response"})

        tipo = raw.get("type", "")
        await complete_confirmation_token(confirmation_token, success=True,
                                          result={"type": tipo, "step_id": step_id})
        if tipo in _NON_AUTOMATABLE_TYPES:
            await _abortar(flow_id)
            logger.warning("ha_continue_repair_fix_non_automatable", flow_id=flow_id,
                           flow_type=tipo)
            return json.dumps({"error": "non_automatable", "type": tipo, "flow_id": flow_id,
                               "hint": _HINT_NO_AUTOMATIZABLE.format(tipo=tipo)})
        textos = await _translations.leer(ha_client, [domain])
        out = await _resultado(raw, aviso, textos)
        if tipo in ("form", "menu"):
            out["continue_with"] = (
                f"{_CONTINUE}: the next step needs a new preview and its own token")
        logger.info("ha_continue_repair_fix_ok", flow_id=flow_id, domain=domain,
                    issue_id=issue_id, flow_type=tipo)
        return json.dumps(out, ensure_ascii=False)

    # ── ha_abort_repair_fix ───────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_abort_repair_fix(flow_id: str) -> object:
        """Abort a fix flow opened with ha_start_repair_fix, applying nothing.

        The issue stays as it was.

        Args:
            flow_id: Flow id from ha_start_repair_fix.

        Returns:
            {"result": "ok"}, or {"error": "not_found" | ...}.
        """
        if (err := _validar_flow_id(flow_id)):
            return err
        try:
            await ha_client._request_json("DELETE", f"{_RUTA}/{flow_id}")  # noqa: SLF001
        except HAConnectionError as exc:
            if exc.status == 404:
                return json.dumps({"error": "not_found", "flow_id": flow_id})
            logger.error("ha_abort_repair_fix_rest_error", flow_id=flow_id,
                         error=_error_ha(exc))
            return json.dumps({"error": _error_ha(exc)})
        logger.info("ha_abort_repair_fix_ok", flow_id=flow_id)
        return json.dumps({"result": "ok"})
