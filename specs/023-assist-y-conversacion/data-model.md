# Modelo de datos: Assist y conversación (023)

Nada se persiste en Hermes. Son las formas que entran y salen de las tools y
las entradas de la tabla.

## Familia

```python
# tool_families.py — spec 023 (research R-1)
Familia("conversation",
        "Assist conversation agents, custom sentences, sentence analysis "
        "and sending a sentence to Assist (with confirmation).",
        "1.2.0", True, ("conversation",)),
```

## Validación de argumentos (antes de llamar a HA)

| Argumento | Regla | Error |
|---|---|---|
| `text` | `str`, 1…2000 caracteres tras quitar espacios de los extremos (se envía tal cual) | `invalid_argument` |
| `sentences` | lista de 1…20 `str`, cada una 1…500 caracteres | `invalid_argument` |
| `agent_id` | `str` 1…255 caracteres sin espacios ni caracteres de control; el resto lo decide `conversation/agent/list` | `invalid_argument` / `agent_not_found` |
| `language` | `^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})*$` | `invalid_argument` |
| `country` | `^[A-Za-z]{2}$` | `invalid_argument` |
| `conversation_id` | `str` 1…255 sin caracteres de control | `invalid_argument` |
| `device_id` | `^[0-9a-f]{32}$` (forma del registro de dispositivos) | `invalid_argument` |
| `search` | `str` 1…200 | `invalid_argument` |
| `limit` | entero 1…500 (por defecto 100) | `invalid_argument` |

## Agente (salida de `ha_list_conversation_agents`)

```json
{"id": "conversation.home_assistant", "name": "Home Assistant",
 "supported_languages": ["en", "es", "..."], "is_default_agent": true}
```

`supported_languages` es `"*"` (HA: `MATCH_ALL`) o la lista que da HA (ya
filtrada si se pidió `language`). Orden: el agente por defecto primero y el
resto por `id`.

Con `include_language_scores=true`, junto al sobre:

```json
"default_agent_language_scores": {
  "preferred_language": "es",
  "languages": {"es": {"cloud": 3, "focused_local": 2, "full_local": 3}}
}
```

(lo que da `language_scores`, pasando `language` y `country` si se dieron).

## Frases (salida de `ha_list_conversation_sentences`)

Sobre común; `items` son las frases (`str`), ordenadas sin distinguir
mayúsculas y sin repetir; `total` cuenta las que pasan el filtro.

## Reconocimiento (por frase, en `ha_debug_conversation` y en la vista previa)

```json
{"sentence": "enciende la luz del salón", "match": true, "source": "builtin",
 "intent": "HassTurnOn", "slots": {"name": "luz del salón"},
 "details": {"name": {"name": "name", "value": "luz del salón", "text": "luz del salón"}},
 "targets": {"light.salon": {"matched": true}}, "targets_total": 1,
 "targets_truncated": false, "sentence_template": "enciende [la] {name}",
 "unmatched_slots": {}}
```

- HA devuelve `null` → `{"sentence": …, "match": false, "recognized": false}`.
- `source: "trigger"` → solo `match`, `source`, `sentence_template` y la nota
  `"A sentence trigger matched: processing runs that automation; its effect cannot be previewed."`.
- `source: "custom"` → además `file` (ruta relativa de `custom_sentences/`).
- `targets`: como mucho 50, en el orden de HA.

## Vista previa de `ha_process_conversation`

```json
{
  "action": "process_conversation",
  "text": "frase centinela del banco",
  "language": "default (Home Assistant's language)",
  "agent": {"id": "conversation.home_assistant", "name": "Home Assistant",
            "is_default_agent": true, "local": true},
  "continues_conversation": false,
  "device_id": null,
  "recognition": {"checked": true, "match": true, "source": "trigger",
                  "sentence_template": "frase centinela del banco"},
  "warnings": ["A sentence trigger matched: processing runs that automation; its effect cannot be previewed."],
  "note": "Processing executes the recognized intent on the entities exposed to Assist."
}
```

Con otro agente: `agent.is_default_agent: false`, `agent.local: "unknown"`,
sin `recognition`, y en `warnings`: `"Hermes cannot predict what this agent will do. The text is sent to this agent, which may be an external service (for example a cloud LLM); it can control the entities exposed to Assist."`.

Si `debug` falla: `recognition: {"checked": false, "reason": "<error redactado>"}`.

Token: `create_confirmation_token("ha_process_conversation", {"text",
"agent_id", "language", "conversation_id", "device_id"}, preview)` con los
valores tal como llegan (`None` incluido); sin `omitibles` ni `estado`.

## Respuesta de `ha_process_conversation` (confirmada)

```json
{"success": true, "response_type": "action_done",
 "speech": "Hecho", "speech_truncated": false,
 "data": {"targets": [], "success": [{"type": "entity", "id": "light.salon", "name": "Salón"}], "failed": []},
 "language": "es", "conversation_id": "01J…", "continue_conversation": false}
```

Errores: `invalid_argument`, `agent_not_found` (`available_agents`), token
inválido (el texto de `validate_confirmation_token`), `outcome_unknown`
(`HAConnectionError` sin código de HA al confirmar: plazo vencido o conexión caída; `"The sentence may have been processed anyway; check the affected entities or ha_get_logbook."`),
`conversation_not_loaded` (`unknown_command`), `ha_error` (error de HA
redactado), y el de Core caído de siempre.

## Entradas de la tabla

`command_table.py`, familia `conversation`, `cap="CAP-060"`:

```python
"conversation/agent/homeassistant/debug": E("dedicated", "cubierto por ha_debug_conversation", "conversation", tool="ha_debug_conversation", cap="CAP-060"),
"conversation/agent/homeassistant/language_scores": E("dedicated", "cubierto por ha_list_conversation_agents (con include_language_scores=true)", "conversation", tool="ha_list_conversation_agents", cap="CAP-060"),
"conversation/agent/list": E("dedicated", "cubierto por ha_list_conversation_agents", "conversation", tool="ha_list_conversation_agents", cap="CAP-060"),
"conversation/process": E("dedicated", "cubierto por ha_process_conversation", "conversation", tool="ha_process_conversation", cap="CAP-060"),
"conversation/sentences/list": E("dedicated", "cubierto por ha_list_conversation_sentences", "conversation", tool="ha_list_conversation_sentences", cap="CAP-060"),
```

`_DEDICADAS_INICIALES` (bloque «023»): las cuatro claves con su tool y
`"conversation/agent/homeassistant/language_scores": _ConMatiz("ha_list_conversation_agents", "con include_language_scores=true")`.

Cambios en CAP-061 y CAP-062 (research R-5):

```python
"assist_pipeline/pipeline_debug/get": E("read", "eventos de depuración de una ejecución de pipeline (incluye el texto reconocido); el `token` del audio, su `url` (/api/tts_proxy/…, sin autenticación en HA) y su `media_id` (media-source://tts/-stream-/…, el mismo token) salen tapados; solo lee", "generic_commands", cap="CAP-061", redact_extra=("url",)),
"ai_task/preferences/set": E("confirm", "cambia las entidades por defecto de AI Task y `allow_automatic_evaluation`, que deja a HA usar por su cuenta el modelo de decisión (un LLM, quizá en la nube)", "generic_commands", cap="CAP-062"),
"assist_pipeline/pipeline/create": E("confirm", "crea un pipeline de Assist", "generic_commands", cap="CAP-061", example={"name": "Pipeline de ejemplo", "language": "es", "conversation_engine": "conversation.home_assistant", "conversation_language": "es", "stt_engine": None, "stt_language": None, "tts_engine": None, "tts_language": None, "tts_voice": None, "wake_word_entity": None, "wake_word_id": None}),
```

(El texto exacto de los motivos lo fija la implementación; tiene que decir lo
mismo.)
