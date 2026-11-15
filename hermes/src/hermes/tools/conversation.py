"""Hermes — Assist y conversación (spec 023, CAP-060 de la 008).

Cuatro tools de la familia `conversation`:

- `ha_list_conversation_agents`: los agentes de Assist y sus idiomas
  (`conversation/agent/list`) y, si se piden, las puntuaciones de idioma del
  agente integrado (`conversation/agent/homeassistant/language_scores`).
- `ha_list_conversation_sentences`: las frases de los disparadores de frase
  de las automatizaciones (`conversation/sentences/list`).
- `ha_debug_conversation`: qué reconoce el agente integrado en unas frases,
  SIN ejecutarlas (`conversation/agent/homeassistant/debug`).
- `ha_process_conversation`: manda una frase a Assist y la EJECUTA
  (`conversation/process`), siempre en dos pasos.

POR QUÉ ASÍ
-----------
Procesar una frase es lo mismo que decirla por voz: el agente integrado
ejecuta el intent reconocido sobre las entidades expuestas a Assist (abrir una
cerradura, desarmar una alarma) o la automatización cuyo disparador de frase
coincide. Por eso confirma SIEMPRE, igual que la acción `conversation.process`
está en la denylist de las acciones (research R-2 y R-3).

La vista previa no puede mentir (principio V): con el agente integrado dice lo
que `debug` reconoce para esa misma frase, idioma y dispositivo, sin ejecutar
nada; si coincide un disparador de frase, avisa de que se ejecutará la
automatización entera y de que su efecto no se puede prever. Con cualquier
otro agente (un LLM, quizá en la nube) Hermes no puede saber qué hará ni dónde
corre: `local: "unknown"` y el aviso de que el texto se le envía. El análisis
es información, no una puerta: el token se emite también si no hay
coincidencia o si `debug` falla, porque el proceso no es la misma llamada.

El token ata los cinco argumentos que cambian el efecto (`text`, `agent_id`,
`language`, `conversation_id` y `device_id`) y solo guarda su hash: el texto no
llega a `/data`, que entra en los backups del add-on. Un plazo vencido no se
presenta como «no ejecutado»: HA puede seguir procesando la frase, así que la
respuesta lo dice (`outcome_unknown`) y el token queda consumido, para que un
reintento no la ejecute dos veces (research R-4).

Las respuestas pasan por `redactar_datos` (un LLM puede repetir cualquier
texto). El log nunca lleva frases, respuestas, `conversation_id`, ids de
agentes ni entidades: solo recuentos (FR-011).
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import (
    complete_confirmation_token,
    create_confirmation_token,
    redact_secrets,
    validate_confirmation_token,
)
from hermes.tools._common import (
    _LIMIT_HINT,
    ajustar_lista_a_bytes,
    redactar_datos,
    requires_ready,
    sobre_de_lista,
    tam_json,
)

logger = structlog.get_logger(__name__)

# El agente integrado de HA (`HOME_ASSISTANT_AGENT` en `conversation/const.py`):
# reconoce en local con las plantillas de la imagen y las frases propias.
AGENTE_INTEGRADO = "conversation.home_assistant"

# Un LLM puede tardar decenas de segundos en contestar; los 30 s de siempre
# cortarían respuestas normales (research R-4).
_PLAZO_PROCESO_S = 90

_MAX_TEXTO = 2000
_MAX_FRASES = 20
_MAX_FRASE = 500
_MAX_ID = 255
_MAX_SEARCH = 200
_MAX_LIMIT = 500
_MAX_OBJETIVOS = 50

_RE_IDIOMA = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})*$")
_RE_PAIS = re.compile(r"^[A-Za-z]{2}$")
_RE_DISPOSITIVO = re.compile(r"^[0-9a-f]{32}$")
_RE_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_RE_ESPACIO_O_CONTROL = re.compile(r"[\s\x00-\x1f\x7f]")

NOTA_DISPARADOR = (
    "A sentence trigger matched: processing runs that automation; its effect "
    "cannot be previewed."
)
AVISO_AGENTE_EXTERNO = (
    "Hermes cannot predict what this agent will do. The text is sent to this "
    "agent, which may be an external service (for example a cloud LLM); it can "
    "control the entities exposed to Assist."
)
NOTA_SIN_COINCIDENCIA = (
    "The built-in agent did not recognize this sentence in the analysis. "
    "Processing will most likely answer that it did not understand, but the "
    "analysis is not the processing itself."
)
_NOTA_INTEGRADO = (
    "Processing executes the recognized intent on the entities exposed to Assist."
)
_NOTA_OTRO_AGENTE = (
    "Processing sends the text to this agent; what it does is decided by the "
    "agent, not by Hermes."
)
DETALLE_RESULTADO_DESCONOCIDO = (
    "The sentence may have been processed anyway; check the affected entities "
    "or ha_get_logbook."
)
_IDIOMA_POR_DEFECTO = "default (Home Assistant's language)"


# ── Validación (data-model, antes de llamar a HA) ─────────────────────────────

def _invalid(field: str, detail: str) -> dict[str, Any]:
    return {"error": "invalid_argument", "field": field, "detail": detail}


def _validar_idioma(valor: Any, campo: str = "language") -> dict[str, Any] | None:
    if valor is None:
        return None
    if not isinstance(valor, str) or not _RE_IDIOMA.match(valor):
        return _invalid(campo, "must be a language code such as 'es' or 'en-US'")
    return None


def _validar_pais(valor: Any) -> dict[str, Any] | None:
    if valor is None:
        return None
    if not isinstance(valor, str) or not _RE_PAIS.match(valor):
        return _invalid("country", "must be a two-letter country code such as 'ES'")
    return None


def _validar_dispositivo(valor: Any) -> dict[str, Any] | None:
    if valor is None:
        return None
    if not isinstance(valor, str) or not _RE_DISPOSITIVO.match(valor):
        return _invalid("device_id", "must be a device id (32 lowercase hex characters)")
    return None


def _validar_agente(valor: Any) -> dict[str, Any] | None:
    if valor is None:
        return None
    if (not isinstance(valor, str) or not valor or len(valor) > _MAX_ID
            or _RE_ESPACIO_O_CONTROL.search(valor)):
        return _invalid("agent_id", f"must be an agent id of 1 to {_MAX_ID} characters "
                                    "without spaces (see ha_list_conversation_agents)")
    return None


def _validar_conversacion(valor: Any) -> dict[str, Any] | None:
    if valor is None:
        return None
    if (not isinstance(valor, str) or not valor or len(valor) > _MAX_ID
            or _RE_CONTROL.search(valor)):
        return _invalid("conversation_id",
                        f"must be a string of 1 to {_MAX_ID} characters")
    return None


def _validar_texto(valor: Any) -> dict[str, Any] | None:
    if not isinstance(valor, str) or not valor.strip() or len(valor.strip()) > _MAX_TEXTO:
        return _invalid("text", f"must be a non-empty sentence of at most {_MAX_TEXTO} characters")
    return None


def _validar_frases(valor: Any) -> dict[str, Any] | None:
    if (not isinstance(valor, list) or not 1 <= len(valor) <= _MAX_FRASES
            or any(not isinstance(f, str) or not f.strip() or len(f) > _MAX_FRASE
                   for f in valor)):
        return _invalid("sentences", f"must be a list of 1 to {_MAX_FRASES} non-empty "
                                     f"sentences of at most {_MAX_FRASE} characters")
    return None


def _primero(*errores: dict[str, Any] | None) -> dict[str, Any] | None:
    return next((e for e in errores if e is not None), None)


# ── Errores de HA ─────────────────────────────────────────────────────────────

def error_de_ha(exc: HAConnectionError) -> dict[str, Any]:
    """Un error de HA con la forma de data-model.

    Sin código de HA es la caída de siempre (WebSocket cerrada, plazo
    vencido): el mensaje redactado, como el resto de tools. `unknown_command`
    quiere decir que la integración `conversation` no está cargada.
    """
    detalle = redact_secrets(str(exc))
    if exc.code is None:
        return {"error": detalle}
    if exc.code == "unknown_command":
        return {"error": "conversation_not_loaded",
                "detail": "Home Assistant's conversation integration is not loaded."}
    if exc.code == "unauthorized":
        return {"error": "unauthorized",
                "detail": "Home Assistant does not allow this to Hermes' user (admin required)."}
    return {"error": "ha_error", "ha_code": exc.code, "detail": detalle}


# ── Funciones puras ───────────────────────────────────────────────────────────

def agentes(respuesta: Any) -> list[dict[str, Any]]:
    """Los agentes de `conversation/agent/list`: el integrado primero y el
    resto por `id`; `is_default_agent` solo para el integrado."""
    crudos = respuesta.get("agents") if isinstance(respuesta, dict) else None
    out = []
    for a in crudos if isinstance(crudos, list) else []:
        if not isinstance(a, dict) or not isinstance(a.get("id"), str):
            continue
        idiomas = a.get("supported_languages")
        out.append({
            "id": a["id"],
            "name": redact_secrets(a["name"]) if isinstance(a.get("name"), str) else a["id"],
            # "*" es `MATCH_ALL` de HA: el agente admite cualquier idioma.
            "supported_languages": idiomas if idiomas == "*" else list(idiomas or []),
            "is_default_agent": a["id"] == AGENTE_INTEGRADO,
        })
    out.sort(key=lambda a: (not a["is_default_agent"], a["id"]))
    return out


def reconocimiento(frase: str, resultado: Any) -> dict[str, Any]:
    """Lo que `debug` reconoce en una frase, con la forma de data-model."""
    if not isinstance(resultado, dict):
        return {"sentence": frase, "match": False, "recognized": False}
    if resultado.get("source") == "trigger":
        # HA no puede dar la respuesta sin ejecutar la automatización: solo
        # se sabe que coincide y con qué plantilla.
        return {"sentence": frase, "match": bool(resultado.get("match", True)),
                "source": "trigger",
                "sentence_template": resultado.get("sentence_template"),
                "note": NOTA_DISPARADOR}
    intent = resultado.get("intent")
    objetivos = resultado.get("targets") if isinstance(resultado.get("targets"), dict) else {}
    claves = list(objetivos)
    out: dict[str, Any] = {
        "sentence": frase,
        "match": bool(resultado.get("match")),
        "source": resultado.get("source"),
        "intent": intent.get("name") if isinstance(intent, dict) else intent,
        "slots": redactar_datos(resultado.get("slots") or {}),
        "details": redactar_datos(resultado.get("details") or {}),
        "targets": {k: objetivos[k] for k in claves[:_MAX_OBJETIVOS]},
        "targets_total": len(claves),
        "targets_truncated": len(claves) > _MAX_OBJETIVOS,
        "sentence_template": resultado.get("sentence_template"),
        "unmatched_slots": redactar_datos(resultado.get("unmatched_slots") or {}),
    }
    if resultado.get("source") == "custom":
        out["file"] = resultado.get("file")
    return out


def _con_tope_de_objetivos(resultados: list[dict[str, Any]], tope: int) -> list[dict[str, Any]]:
    out = []
    for r in resultados:
        if "targets" not in r or len(r["targets"]) <= tope:
            out.append(r)
            continue
        claves = list(r["targets"])[:tope]
        out.append({**r, "targets": {k: r["targets"][k] for k in claves},
                    "targets_truncated": True})
    return out


def ajustar_analisis(resultados: list[dict[str, Any]], max_bytes: int) -> dict[str, Any]:
    """`{"results": …}` dentro del tope: si no cabe, se quitan objetivos por
    el final (el mismo tope para todas las frases, buscado por bisección) y,
    si ni sin objetivos cabe, `response_too_large`."""
    completa = {"results": resultados}
    if tam_json(completa) <= max_bytes:
        return completa
    bajo, alto = 0, _MAX_OBJETIVOS
    if tam_json({"results": _con_tope_de_objetivos(resultados, 0)}) > max_bytes:
        return {"error": "response_too_large",
                "detail": (f"The analysis exceeds response_max_bytes ({max_bytes}) even "
                           "without targets; analyse fewer sentences at a time.")}
    while bajo < alto:
        medio = (bajo + alto + 1) // 2
        if tam_json({"results": _con_tope_de_objetivos(resultados, medio)}) <= max_bytes:
            bajo = medio
        else:
            alto = medio - 1
    return {"results": _con_tope_de_objetivos(resultados, bajo)}


def _texto_de_voz(respuesta: dict[str, Any]) -> str:
    voz = respuesta.get("speech")
    if isinstance(voz, dict):
        for forma in ("plain", "ssml"):
            parte = voz.get(forma)
            if isinstance(parte, dict) and isinstance(parte.get("speech"), str):
                return parte["speech"]
    return ""


def respuesta_de_proceso(resultado: Any, max_bytes: int) -> dict[str, Any]:
    """La respuesta de `conversation/process` con los campos elegidos,
    redactada y dentro del tope (se recorta `speech` y, si no basta, las
    listas de `data`)."""
    crudo = resultado if isinstance(resultado, dict) else {}
    resp = crudo.get("response") if isinstance(crudo.get("response"), dict) else {}
    voz = redact_secrets(_texto_de_voz(resp))
    out: dict[str, Any] = {
        "success": True,
        "response_type": resp.get("response_type"),
        "speech": voz,
        "speech_truncated": False,
        "data": redactar_datos(resp.get("data") if resp.get("data") is not None else {}),
        "language": resp.get("language"),
        "conversation_id": crudo.get("conversation_id"),
        "continue_conversation": bool(crudo.get("continue_conversation")),
    }
    for extra in ("card", "speech_slots"):
        if resp.get(extra):
            out[extra] = redactar_datos(resp[extra])
    if tam_json(out) <= max_bytes:
        return out

    # Primero las listas de `data`, solo si ni sin texto cabe: el texto es lo
    # que el usuario espera leer.
    sin_voz = {**out, "speech": "", "speech_truncated": bool(voz)}
    if tam_json(sin_voz) > max_bytes and isinstance(out["data"], dict):
        datos = dict(out["data"])
        listas = [k for k, v in datos.items() if isinstance(v, list) and v]
        while tam_json({**sin_voz, "data": datos}) > max_bytes and listas:
            clave = max(listas, key=lambda k: tam_json(datos[k]))
            datos[clave] = datos[clave][: len(datos[clave]) // 2]
            if not datos[clave]:
                listas.remove(clave)
        sin_voz = {**sin_voz, "data": datos, "data_truncated": True,
                   "_response_limit": {"max_bytes": max_bytes, "hint": _LIMIT_HINT}}
        if tam_json(sin_voz) > max_bytes:
            return {"error": "response_too_large",
                    "detail": f"The response exceeds response_max_bytes ({max_bytes}).",
                    "processed": True}
        out = {**sin_voz, "speech": voz}
    # El texto más largo que cabe (bisección sobre su longitud).
    bajo, alto = 0, len(voz)
    while bajo < alto:
        medio = (bajo + alto + 1) // 2
        if tam_json({**out, "speech": voz[:medio], "speech_truncated": True}) <= max_bytes:
            bajo = medio
        else:
            alto = medio - 1
    return {**out, "speech": voz[:bajo], "speech_truncated": bajo < len(voz)}


def _recuentos(respuesta: dict[str, Any]) -> tuple[int, int]:
    datos = respuesta.get("data") if isinstance(respuesta.get("data"), dict) else {}
    ok = datos.get("success") if isinstance(datos.get("success"), list) else []
    mal = datos.get("failed") if isinstance(datos.get("failed"), list) else []
    return len(ok), len(mal)


# ── Registro ──────────────────────────────────────────────────────────────────

def register(
    mcp: object,
    ha_client: HAClient,
    *,
    response_max_bytes: int,
) -> None:
    """Registra las cuatro tools de Assist y conversación."""

    ready = requires_ready(ha_client)

    async def listar_agentes(language: str | None, country: str | None) -> list[dict[str, Any]]:
        mensaje: dict[str, Any] = {"type": "conversation/agent/list"}
        # Solo los dados: sin ellos HA no filtra los idiomas.
        if language is not None:
            mensaje["language"] = language
        if country is not None:
            mensaje["country"] = country
        return agentes(await ha_client.ws_send(mensaje))

    async def analizar(frases: list[str], language: str | None,
                       device_id: str | None) -> list[dict[str, Any]]:
        mensaje: dict[str, Any] = {"type": "conversation/agent/homeassistant/debug",
                                   "sentences": frases}
        if language is not None:
            mensaje["language"] = language
        if device_id is not None:
            mensaje["device_id"] = device_id
        crudo = await ha_client.ws_send(mensaje)
        resultados = crudo.get("results") if isinstance(crudo, dict) else None
        if not isinstance(resultados, list):
            resultados = []
        # En el orden de las frases; si HA devolviera menos, las que faltan
        # salen como no reconocidas (nunca se inventa una coincidencia).
        return [reconocimiento(f, resultados[i] if i < len(resultados) else None)
                for i, f in enumerate(frases)]

    # ── ha_list_conversation_agents ───────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_conversation_agents(
        language: str | None = None,
        country: str | None = None,
        include_language_scores: bool = False,
    ) -> object:
        """List Assist conversation agents and the languages they support.

        `conversation.home_assistant` is Home Assistant's built-in agent: only
        that one is known to run locally. The others are added by integrations
        (OpenAI, Google, Ollama...) and may send the text to external
        services. Read only.

        Args:
            language: Optional language code (e.g. "es"): filters each agent's
                supported_languages to the ones that match.
            country: Optional two-letter country code to refine `language`.
            include_language_scores: true adds how well the built-in agent
                supports each language (`default_agent_language_scores`).

        Returns:
            {"count", "items": [{id, name, supported_languages ("*" = any),
             is_default_agent}], "truncated"} (built-in agent first), plus
            "default_agent_language_scores" if requested; or {"error": ...}.
        """
        invalido = _primero(_validar_idioma(language), _validar_pais(country))
        if invalido is None and not isinstance(include_language_scores, bool):
            invalido = _invalid("include_language_scores", "must be true or false")
        if invalido is not None:
            return invalido
        try:
            items = await listar_agentes(language, country)
            puntuaciones = None
            if include_language_scores:
                mensaje: dict[str, Any] = {
                    "type": "conversation/agent/homeassistant/language_scores"}
                if language is not None:
                    mensaje["language"] = language
                if country is not None:
                    mensaje["country"] = country
                puntuaciones = await ha_client.ws_send(mensaje)
        except HAConnectionError as exc:
            logger.warning("ha_list_conversation_agents_error", code=exc.code or "connection")
            return error_de_ha(exc)

        cabecera: dict[str, Any] = {}
        if include_language_scores:
            cabecera["default_agent_language_scores"] = puntuaciones

        def construir(lista: list[Any], recortada: bool) -> dict[str, Any]:
            out = sobre_de_lista(lista, truncated=recortada, **cabecera)
            if recortada:
                out["_response_limit"] = {
                    "list": "items", "returned": len(lista), "total": len(items),
                    "max_bytes": response_max_bytes, "hint": _LIMIT_HINT,
                }
            return out

        respuesta = ajustar_lista_a_bytes(items, construir, response_max_bytes)
        logger.info("ha_list_conversation_agents_ok", count=respuesta["count"],
                    language_scores=include_language_scores)
        return respuesta

    # ── ha_list_conversation_sentences ────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_conversation_sentences(
        search: str | None = None,
        limit: int = 100,
    ) -> object:
        """List the sentences of automations' sentence triggers (trigger: conversation).

        Only those: it does not include Home Assistant's built-in sentences
        nor custom_sentences/. To know what Home Assistant understands from a
        sentence, use ha_debug_conversation. Read only; needs an admin user.

        Args:
            search: Optional case-insensitive substring filter.
            limit: Maximum sentences to return (1-500, default 100).

        Returns:
            {"total", "count", "items": [sentence], "truncated"} sorted
            case-insensitively without duplicates; or {"error": ...}.
        """
        if search is not None and (not isinstance(search, str) or not search.strip()
                                   or len(search) > _MAX_SEARCH):
            return _invalid("search", f"must be a non-empty string of at most {_MAX_SEARCH} characters")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_LIMIT:
            return _invalid("limit", f"must be an integer between 1 and {_MAX_LIMIT}")
        try:
            crudo = await ha_client.ws_send({"type": "conversation/sentences/list"})
        except HAConnectionError as exc:
            logger.warning("ha_list_conversation_sentences_error", code=exc.code or "connection")
            return error_de_ha(exc)
        frases = crudo.get("trigger_sentences") if isinstance(crudo, dict) else None
        unicas = {redact_secrets(f) for f in frases or [] if isinstance(f, str)}
        if search is not None:
            aguja = search.casefold()
            unicas = {f for f in unicas if aguja in f.casefold()}
        todas = sorted(unicas, key=lambda f: (f.casefold(), f))
        total = len(todas)

        def construir(lista: list[Any], recortada: bool) -> dict[str, Any]:
            out = sobre_de_lista(lista, truncated=recortada or total > limit, total=total)
            if recortada:
                out["_response_limit"] = {
                    "list": "items", "returned": len(lista), "total": total,
                    "max_bytes": response_max_bytes, "hint": _LIMIT_HINT,
                }
            return out

        respuesta = ajustar_lista_a_bytes(todas[:limit], construir, response_max_bytes)
        logger.info("ha_list_conversation_sentences_ok", count=respuesta["count"], total=total)
        return respuesta

    # ── ha_debug_conversation ─────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_debug_conversation(
        sentences: list[str],
        language: str | None = None,
        device_id: str | None = None,
    ) -> object:
        """Analyse sentences with Home Assistant's built-in agent WITHOUT executing anything.

        For each sentence: the recognized intent, its slots and the entities
        it would act on, or whether it matches an automation's sentence
        trigger (whose effect cannot be known without running it). Only the
        built-in local agent; no other agent is called. Nothing is executed:
        to execute a sentence, use ha_process_conversation.

        Args:
            sentences: 1 to 20 sentences (at most 500 characters each).
            language: Optional language code (default: Home Assistant's).
            device_id: Optional device id: its area is used as context
                ("turn on the light" in that room).

        Returns:
            {"results": [{sentence, match, source, intent, slots, details,
             targets (at most 50), targets_total, targets_truncated,
             sentence_template, unmatched_slots}]} in the same order, or
            {"sentence", "match": false, "recognized": false}; or {"error": ...}.
        """
        invalido = _primero(_validar_frases(sentences), _validar_idioma(language),
                            _validar_dispositivo(device_id))
        if invalido is not None:
            return invalido
        try:
            resultados = await analizar(sentences, language, device_id)
        except HAConnectionError as exc:
            logger.warning("ha_debug_conversation_error", code=exc.code or "connection")
            return error_de_ha(exc)
        respuesta = ajustar_analisis(resultados, response_max_bytes)
        logger.info("ha_debug_conversation_ok", sentences=len(resultados),
                    matches=sum(1 for r in resultados if r.get("match")))
        return respuesta

    # ── ha_process_conversation ───────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_process_conversation(
        text: str,
        agent_id: str | None = None,
        language: str | None = None,
        conversation_id: str | None = None,
        device_id: str | None = None,
        confirmation_token: str | None = None,
    ) -> object:
        """Send a sentence to Assist as if it were spoken, and EXECUTE it.

        It can turn things on or off, open locks or garage doors, disarm
        alarms or run automations with a sentence trigger, on the entities
        exposed to Assist. Always two steps: the first call returns a preview
        (the agent and, with the built-in agent, what Home Assistant
        recognizes) and a confirmation_token; repeat the same call with the
        token to execute it. With an agent other than the built-in one, the
        text is sent to that agent, which may be an external service (a cloud
        LLM), and Hermes cannot predict what it will do. To analyse without
        executing, use ha_debug_conversation.

        Args:
            text: The sentence (at most 2000 characters).
            agent_id: Optional agent from ha_list_conversation_agents
                (default: the built-in conversation.home_assistant).
            language: Optional language code (default: Home Assistant's).
            conversation_id: Optional id of a conversation to continue.
            device_id: Optional device id whose area is used as context.
            confirmation_token: Token from the preview call.

        Returns:
            Preview + token; {"success", "response_type", "speech",
            "speech_truncated", "data", "language", "conversation_id",
            "continue_conversation"}; {"error": "agent_not_found",
            "available_agents"}; {"error": "outcome_unknown"} if Home
            Assistant did not answer in time (it may have run anyway); or
            {"error": ...}.
        """
        invalido = _primero(_validar_texto(text), _validar_agente(agent_id),
                            _validar_idioma(language), _validar_conversacion(conversation_id),
                            _validar_dispositivo(device_id))
        if invalido is not None:
            return invalido
        args = {"text": text, "agent_id": agent_id, "language": language,
                "conversation_id": conversation_id, "device_id": device_id}
        integrado = agent_id is None or agent_id == AGENTE_INTEGRADO

        if not confirmation_token:
            # El agente se comprueba antes de emitir el token: confirmar algo
            # que HA va a rechazar no sirve de nada (fail-closed).
            try:
                lista = await listar_agentes(None, None)
            except HAConnectionError as exc:
                logger.warning("ha_process_conversation_error", code=exc.code or "connection")
                return error_de_ha(exc)
            elegido = agent_id or AGENTE_INTEGRADO
            agente = next((a for a in lista if a["id"] == elegido), None)
            if agente is None:
                logger.info("ha_process_conversation_error", code="agent_not_found")
                return {"error": "agent_not_found", "agent_id": agent_id,
                        "available_agents": [a["id"] for a in lista]}
            preview: dict[str, Any] = {
                "action": "process_conversation",
                "text": text,
                "language": language or _IDIOMA_POR_DEFECTO,
                "agent": {"id": agente["id"], "name": agente["name"],
                          "is_default_agent": integrado,
                          # Hermes no puede saber dónde corre otro agente:
                          # decir `false` también podría mentir.
                          "local": True if integrado else "unknown"},
                "continues_conversation": conversation_id is not None,
                "device_id": device_id,
            }
            avisos: list[str] = []
            coincide: bool | None = None
            if integrado:
                try:
                    rec = (await analizar([text], language, device_id))[0]
                    coincide = bool(rec.get("match"))
                    recon = {k: v for k, v in rec.items() if k not in ("sentence", "note")}
                    preview["recognition"] = {"checked": True, **recon}
                    if rec.get("source") == "trigger":
                        avisos.append(NOTA_DISPARADOR)
                    elif not coincide:
                        avisos.append(NOTA_SIN_COINCIDENCIA)
                except HAConnectionError as exc:
                    # `debug` es información, no una puerta: se dice que no se
                    # pudo comprobar y el token se emite igual.
                    preview["recognition"] = {"checked": False,
                                              "reason": error_de_ha(exc).get("detail")
                                              or redact_secrets(str(exc))}
                preview["note"] = _NOTA_INTEGRADO
            else:
                avisos.append(AVISO_AGENTE_EXTERNO)
                preview["note"] = _NOTA_OTRO_AGENTE
            preview["warnings"] = avisos
            logger.info("ha_process_conversation_preview", is_default_agent=integrado,
                        match=coincide)
            return await create_confirmation_token("ha_process_conversation", args,
                                                   preview=preview)

        valido, error = await validate_confirmation_token(
            confirmation_token, "ha_process_conversation", args)
        if not valido:
            logger.warning("ha_process_conversation_error", code="token_invalid")
            return {"error": error}

        mensaje: dict[str, Any] = {"type": "conversation/process"}
        mensaje.update({k: v for k, v in args.items() if v is not None})
        try:
            resultado = await ha_client.ws_send(mensaje, timeout_seconds=_PLAZO_PROCESO_S)
        except HAConnectionError as exc:
            if exc.code is None:
                # Plazo vencido o conexión caída esperando: HA puede haberla
                # procesado igualmente. El token queda consumido para que un
                # reintento no la ejecute dos veces.
                await complete_confirmation_token(confirmation_token, success=False,
                                                  error="outcome_unknown")
                logger.warning("conversation_processed", is_default_agent=integrado,
                               ok=False, outcome="unknown")
                return {"error": "outcome_unknown", "detail": DETALLE_RESULTADO_DESCONOCIDO}
            fallo = error_de_ha(exc)
            await complete_confirmation_token(confirmation_token, success=False,
                                              error=str(fallo.get("error")))
            logger.warning("conversation_processed", is_default_agent=integrado,
                           ok=False, code=exc.code)
            return fallo
        respuesta = respuesta_de_proceso(resultado, response_max_bytes)
        exitos, fallos = _recuentos(respuesta)
        await complete_confirmation_token(
            confirmation_token, success=True,
            result={"response_type": respuesta.get("response_type")})
        logger.info("conversation_processed", is_default_agent=integrado, ok=True,
                    response_type=respuesta.get("response_type"),
                    success_count=exitos, failed_count=fallos)
        return respuesta
