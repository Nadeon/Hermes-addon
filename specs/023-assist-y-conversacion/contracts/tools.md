# Contrato de las tools: Assist y conversación (023)

Módulo `hermes/src/hermes/tools/conversation.py`, familia `conversation`.
`register(mcp, ha_client, *, response_max_bytes)`, todas con
`requires_ready`. Descripciones en inglés (lo que ve el cliente); el sentido
de cada una es el que sigue y no puede prometer más (principio V).

## `ha_list_conversation_agents`

```text
ha_list_conversation_agents(language: str | None = None,
                            country: str | None = None,
                            include_language_scores: bool = False)
```

- **Descripción (sentido)**: lista los agentes de conversación de Assist y
  los idiomas que admiten. `conversation.home_assistant` es el agente
  integrado de HA y funciona en local; los demás (OpenAI, Google, Ollama…)
  los añaden integraciones y pueden mandar el texto a servicios externos.
  `include_language_scores=true` añade cuánto admite cada idioma el agente
  integrado.
- **HA**: `conversation/agent/list` (`language`, `country`) y, si se pide,
  `conversation/agent/homeassistant/language_scores` (`language`,
  `country`).
- **Respuesta**: sobre común con los agentes (data-model) y, si se pidió,
  `default_agent_language_scores`. Recorte con `ajustar_lista_a_bytes`.
- **Anotaciones**: `R-I-` (prefijo).
- **Errores**: `invalid_argument`, `conversation_not_loaded`, `ha_error`.

## `ha_list_conversation_sentences`

```text
ha_list_conversation_sentences(search: str | None = None, limit: int = 100)
```

- **Descripción (sentido)**: frases de los disparadores de frase de las
  automatizaciones (`trigger: conversation`). No incluye las frases
  integradas de HA ni las de `custom_sentences/`; para saber qué entiende HA
  de una frase, `ha_debug_conversation`.
- **HA**: `conversation/sentences/list` (exige administrador).
- **Respuesta**: sobre común de `str`, ordenadas y sin repetir; `search`
  filtra por subcadena sin distinguir mayúsculas.
- **Anotaciones**: `R-I-` (prefijo).
- **Errores**: `invalid_argument`, `unauthorized` (HA no lo permite al
  usuario de Hermes), `conversation_not_loaded`, `ha_error`.

## `ha_debug_conversation`

```text
ha_debug_conversation(sentences: list[str], language: str | None = None,
                      device_id: str | None = None)
```

- **Descripción (sentido)**: analiza frases con el agente integrado de HA
  **sin ejecutar nada**: qué intent reconoce, con qué huecos y sobre qué
  entidades actuaría, o si coincide con un disparador de frase (cuyo efecto
  no se puede prever sin ejecutarlo). Solo el agente integrado; no llama a
  agentes externos. `device_id` da el área del dispositivo como contexto.
- **HA**: `conversation/agent/homeassistant/debug` (`sentences`,
  `language`, `device_id`).
- **Respuesta**: `{"results": [reconocimiento por frase, en orden]}`
  (data-model); objetivos como mucho 50 por frase; dentro del tope (si no
  cabe, se quitan objetivos por el final con `targets_truncated` y, en
  último caso, `response_too_large`).
- **Anotaciones**: `R-I-` (`_READ_ONLY_EXACT`, con el porqué).
- **Errores**: `invalid_argument`, `conversation_not_loaded`, `ha_error`.

## `ha_process_conversation`

```text
ha_process_conversation(text: str, agent_id: str | None = None,
                        language: str | None = None,
                        conversation_id: str | None = None,
                        device_id: str | None = None,
                        confirmation_token: str | None = None)
```

- **Descripción (sentido)**: manda una frase a Assist como si se dijera por
  voz y **la ejecuta**: puede encender, apagar, abrir cerraduras o puertas,
  desarmar alarmas o ejecutar automatizaciones con disparador de frase, sobre
  las entidades expuestas a Assist. Siempre en dos pasos: la primera llamada
  devuelve una vista previa (agente y, con el agente integrado, lo que HA
  reconoce) y un `confirmation_token`; repetir la misma llamada con el token
  la ejecuta. Con un agente que no es el integrado, el texto se envía a ese
  agente, que puede ser un servicio externo (un LLM en la nube), y Hermes no
  puede predecir qué hará. Para analizar sin ejecutar, `ha_debug_conversation`.
- **HA**: vista previa: `conversation/agent/list` y, con el agente por
  defecto, `conversation/agent/homeassistant/debug`; confirmación:
  `conversation/process` (`text`, `agent_id`, `language`,
  `conversation_id`, `device_id`; solo los dados), plazo 90 s.
- **Token**: atado a `text`, `agent_id`, `language`, `conversation_id` y
  `device_id`. Sin `omitibles` ni `estado`.
- **Respuesta**: vista previa (data-model) o la respuesta confirmada.
- **Anotaciones**: `-D-O` (`_DESTRUCTIVE_EXACT`, `_NON_IDEMPOTENT_EXACT` y
  `_OPEN_WORLD`, con el porqué).
- **Errores**: `invalid_argument`, `agent_not_found`, token inválido o
  caducado, `outcome_unknown`, `conversation_not_loaded`, `ha_error`.
- **Log**: `conversation_processed` (data-model, research R-4).

## Genéricas (sin cambios de código)

- `ha_read_ws_command` / `ha_call_ws_command` con los cinco comandos de
  CAP-060 → `use_dedicated_tool` con su tool (o `family_disabled: true` con
  `conversation` apagada).
- Con los de CAP-061…CAP-063 → según la tabla (`read` / `confirm`).
