# Investigación: Assist y conversación (023)

Contrastado con el código de HA Core 2026.11.1 (carpeta `fuentes`, solo
lectura) y con el código de Hermes en `feat/cobertura-total` (punta
`1752984`, 293 tools).

## R-1 — Tools, nombres y familia

**Decisión**: cuatro tools en el módulo nuevo `tools/conversation.py`,
familia nueva `conversation` («desde» 1.2.0, desactivable):

| Tool | Comandos WS | Modifica |
|---|---|---|
| `ha_list_conversation_agents` | `conversation/agent/list` y, con `include_language_scores=true`, `conversation/agent/homeassistant/language_scores` | no |
| `ha_list_conversation_sentences` | `conversation/sentences/list` | no |
| `ha_debug_conversation` | `conversation/agent/homeassistant/debug` | no |
| `ha_process_conversation` | `conversation/process` (y, en la vista previa, `agent/list` y `homeassistant/debug`) | sí, con token |

**Por qué**: son los nombres que propone la 008 (S-05 los deja fijar aquí) y
siguen FR-018: `ha_list_*` hereda `readOnlyHint` del prefijo.
`ha_debug_conversation` no tiene prefijo de lectura: va por nombre exacto en
`_READ_ONLY_EXACT` (como `ha_validate_statistics` en la 029). Se descartó
`ha_get_conversation_debug`, que esconde que analiza frases que se le pasan.

`language_scores` no merece una tool propia (D-04 de la 008: cada tool cuesta
~1 KB de contexto en la lista): es un dato del agente por defecto y su sitio
natural es la lista de agentes. La entrada de la tabla apunta a
`ha_list_conversation_agents` con el matiz «con include_language_scores=true»
(`_ConMatiz` del generador, como `/reload_updates` en la 015).

Una sola familia y un solo módulo: es un caso de uso («usar y depurar
Assist») y un tema de la guía. No amplía `services` ni ninguna familia de la
1.1.2 (FR-010 de la 008).

**Alternativas**: una quinta tool `ha_get_conversation_language_scores`
(rechazada, coste de contexto); meter las tools en `generic_commands` o en
`services` (rechazado, FR-010).

## R-2 — La vista previa de `ha_process_conversation`

`conversation/process` llama a `async_converse` (`agent_manager.py`): sin
`agent_id` usa `HOME_ASSISTANT_AGENT` (`conversation.home_assistant`), el
agente por defecto, local; con un agente que no existe lanza
`ValueError("Agent … not found")`, que por WebSocket llega como error
genérico. El agente por defecto ejecuta el intent reconocido sobre las
entidades **expuestas a Assist** (`exposed_entities.py`: por defecto, luces,
interruptores, persianas, climatización, reproductores…) o, si la frase
coincide con un **disparador de frase**, ejecuta esa automatización. Otro
agente (OpenAI, Google, Anthropic, Ollama, uno de una integración
personalizada) recibe el texto y hace lo que su integración decida; con la
API «Assist» de LLM, también controla las entidades expuestas.

`conversation/agent/homeassistant/debug` (`default_agent.py`,
`async_debug_recognize`) reconoce sin ejecutar: devuelve `null` si no
reconoce nada, `{"match": true, "source": "trigger", "sentence_template"}`
si coincide con un disparador («We can't provide the response here without
executing the trigger», dice el propio código) o el intent con `slots`,
`details`, `targets` (`entity_id → {matched}`), `match`, `sentence_template`,
`unmatched_slots` y `source` (`builtin` o `custom`, con `file`). Solo
funciona con el agente por defecto.

**Decisión**: la vista previa

1. comprueba el agente con `conversation/agent/list`: si el `agent_id` dado
   no está, `agent_not_found` con los ids disponibles y **sin token**
   (fail-closed: confirmar algo que HA va a rechazar no sirve de nada);
2. dice el agente: `id`, `name`, `is_default_agent` y `local` (`true` solo
   para el agente por defecto; `"unknown"` para cualquier otro: Hermes no
   puede saber dónde corre un agente, y decir `false` también podría
   mentir);
3. con el agente por defecto, añade `recognition` con el resultado de
   `debug` para esa misma frase, idioma y `device_id` (objetivos como mucho
   50, con `targets_total`); si `source` es `trigger`, el aviso de que se
   ejecutará la automatización entera y que su efecto no se puede prever; si
   no hay coincidencia, `match: false` y la nota de que HA responderá con un
   error sin accionar nada;
4. con otro agente, en lugar de `recognition`, el aviso: «Hermes no puede
   predecir qué hará este agente; el texto se envía a él y puede salir a un
   servicio externo (p. ej. un LLM en la nube); puede controlar las
   entidades expuestas»;
5. siempre: el texto, el idioma (el dado o «el de HA»), si continúa una
   conversación (`conversation_id`) y el `device_id`.

El token se emite también con `match: false` (no se niega por el análisis):
proceso y análisis usan el mismo reconocedor, pero no son la misma llamada
(el proceso abre una sesión de chat, maneja temporizadores y respuestas de
seguimiento), y negar el token bloquearía frases que HA sí entiende. Si
`debug` falla, la vista previa lo dice (`recognition.checked: false`) y el
token se emite: `debug` es información, no una puerta (como la validación de
opciones de la 030).

**Por qué no atar el token al estado** (`estado` de la 018): la vista previa
no promete conservar nada; si cambia la exposición en los 60 s del token, HA
decide con lo vigente, igual que haría con la voz.

**Restringidas** (`call_service_restricted_entities`): no se cruzan con los
objetivos. La tool confirma **siempre**, que es lo máximo que hace Hermes con
una restringida; cruzar solo serviría con el agente por defecto y daría una
falsa sensación de control con los demás.

## R-3 — Anotaciones MCP

| Tool | read_only | destructive | idempotent | open_world |
|---|---|---|---|---|
| `ha_list_conversation_agents` | sí | no | sí | no |
| `ha_list_conversation_sentences` | sí | no | sí | no |
| `ha_debug_conversation` | sí (exacta) | no | sí | no |
| `ha_process_conversation` | no | **sí** (exacta) | **no** (exacta) | **sí** |

- **Destructiva**: una frase puede abrir una cerradura o la puerta del
  garaje, desarmar una alarma, parar la calefacción o disparar una
  automatización arbitraria. Es el mismo motivo por el que
  `conversation.process` está en la denylist de las acciones.
- **No idempotente**: repetirla repite la acción («sube el volumen»,
  «alterna la luz»), crea o continúa una sesión de chat.
- **Mundo abierto**: la anotación es estática y tiene que decir el peor caso
  (principio V; mismo criterio que `ha_read_ws_command` con
  `media_source/browse_media`, 011 T047): con un agente en la nube, el texto
  sale de la casa.
- **`ha_debug_conversation` sin mundo abierto**: solo usa el agente por
  defecto, que reconoce en local (plantillas de `home-assistant-intents` en
  la imagen y frases propias); no llama a otros agentes.

Títulos (de `title_for`): «Process conversation (Home Assistant)», «Debug
conversation (Home Assistant)», «List conversation agents (Home
Assistant)», «List conversation sentences (Home Assistant)».

## R-4 — Ejecución, plazo y respuesta

- **Plazo**: 90 s (`ws_send(timeout_seconds=90)`). Un LLM puede tardar
  decenas de segundos; 30 s (el de siempre) cortaría respuestas normales.
  `ws_send` convierte el plazo vencido en un `HAConnectionError` sin código
  de HA (como una conexión que se cae mientras espera). Regla: un
  `HAConnectionError` **sin código de HA** al confirmar → `outcome_unknown`;
  con código (HA respondió con un error) → `ha_error`. En `outcome_unknown`: el `timeout` del cliente no cancela lo que HA ya
  está haciendo; la respuesta dice que la frase pudo ejecutarse y sugiere
  comprobar los estados o `ha_get_logbook`. El token queda consumido
  (`complete_confirmation_token(success=False)`), porque reintentar con
  otro token podría ejecutar dos veces.
- **Respuesta** (`ConversationResult.as_dict()`, `helpers/intent.py`
  `IntentResponse.as_dict`): `response.response_type` (`action_done`,
  `query_answer`, `error`), `response.speech.plain.speech`, `response.data`
  (`targets`, `success`, `failed` o `code`), `conversation_id` y
  `continue_conversation`. Hermes devuelve `response_type`, `speech` (el
  texto plano), `data`, `language`, `conversation_id` y
  `continue_conversation`; omite `card` y `speech_slots` si vienen vacíos.
  Todo por `redact_structure` y `redact_secrets` (el texto de un LLM puede
  repetir cualquier cosa). Si no cabe en `response_max_bytes`, se recorta
  `speech` (`speech_truncated: true`) y después las listas de `data` con el
  sobre de recorte (`recortar_a_bytes`).
- **Token en disco**: `create_confirmation_token` guarda solo el
  `action_hash` (sin `omitibles`): el texto de la frase no se escribe en
  `/data`, que entra en los backups.
- **Log**: `conversation_processed` con `is_default_agent`,
  `response_type`, recuentos de `success`/`failed` y `ok`; nunca el texto, la
  respuesta, el `conversation_id`, el `agent_id` de un agente que no es el
  de HA (puede llevar el nombre que puso el usuario) ni entidades.

## R-5 — Revisión de las entradas de CAP-061, CAP-062 y CAP-063

Comprobado comando a comando contra el código:

| Comando | Tabla | Comprobación |
|---|---|---|
| `assist_pipeline/pipeline/list`, `get` | `read` | colección y `pipeline.py`; solo leen. OK |
| `assist_pipeline/pipeline/create`, `update`, `delete`, `set_preferred` | `confirm` | colección de almacenamiento (`PIPELINE_FIELDS`: once obligatorios); HA no deja borrar el preferido. OK |
| `assist_pipeline/language/list`, `device/list` | `read` | `websocket_api.py`. OK |
| `assist_pipeline/pipeline_debug/list` | `read` | ids y fechas de ejecuciones. OK |
| `assist_pipeline/pipeline_debug/get` | `read` | eventos de una ejecución: texto reconocido, respuesta y, en `tts-end`, `tts_output = {media_id, token, url, mime_type}` con `url = /api/tts_proxy/<token>`. **`TextToSpeechView.requires_auth = False`**: quien tenga la URL descarga el audio sin autenticarse. `token` se tapa por su nombre; `url` no. **Cambio**: `redact_extra=("url",)` y el motivo lo dice |
| `tts/engine/list`, `get`, `voices`; `stt/engine/list`; `wake_word/info`; `llm/api/list` | `read` | solo leen. OK |
| `ai_task/preferences/get` | `read` | OK |
| `ai_task/preferences/set` | `confirm` | `require_admin`; cambia las entidades por defecto y `allow_automatic_evaluation`, que deja a HA usar por su cuenta el modelo de decisión (`async_is_automatic_evaluation_enabled`), un LLM que puede estar en la nube. **Cambio**: el motivo lo dice |
| `assist_satellite/get_configuration` | `read` | OK |
| `assist_satellite/set_wake_words` | `confirm` | `require_admin`; HA valida el máximo y que existan. OK |
| `assist_pipeline/run` | `deny` (D) | se respeta (D-01 de la 008) |
| `assist_pipeline/device/capture`, `pipeline/subscribe`, `assist_satellite/intercept_wake_word`, `test_connection` | `deny` (B) | se respetan |

`ha_call_ws_command` ya se anuncia de mundo abierto (011), así que
`ai_task/preferences/set` no cambia ninguna anotación. Ningún comando de esta
lista empieza por `hassio/` ni `supervisor/` (proxy del Supervisor).

Un ejemplo revisado (`example`) para `assist_pipeline/pipeline/create`, el
comando con más campos obligatorios, ayuda a no fallar a la primera; se
añade con datos ficticios (ver data-model).

## R-6 — Banco de Core

- **Agente en el banco**: el banco ya carga `conversation:` (018, tramo 2)
  sin internet: el único agente es el por defecto,
  `conversation.home_assistant`, que reconoce en local. No hay LLM: el
  camino «otro agente» se prueba en unitarios con un agente simulado.
- **Efecto observable**: el banco no tiene entidades expuestas que un intent
  pueda accionar. La prueba usa un **disparador de frase**: el test crea con
  tools ya probadas un `input_text` de apoyo y una automatización con
  `trigger: conversation` y una frase centinela cuya acción escribe en el
  `input_text`. Así `ha_list_conversation_sentences` la lista,
  `ha_debug_conversation` la reconoce (`source: trigger`) sin ejecutarla, la
  vista previa de `ha_process_conversation` no la ejecuta y la confirmación
  sí; el lector independiente lee el `input_text`. Se borra al terminar. No
  se añade nada fijo a `automations.yaml` (la 028 lo usa vacío).
- **CAP-061 y CAP-062**: la configuración del banco añade `assist_pipeline:`
  (arrastra `tts`, `stt` y `wake_word`) y `ai_task:`. Si `llm/api/list`
  responde `unknown_command`, se añade `llm:`. Se leen pipelines, idiomas,
  dispositivos, motores y APIs de LLM; se crea, actualiza, marca como
  preferido (y se devuelve el preferido original) y borra un pipeline de
  prueba; se fijan las preferencias de AI Task a su valor actual y se
  comprueba. `wake_word/info` y `tts/engine/voices` necesitan una entidad o
  un motor que el banco no tiene: se comprueba que llegan a HA (error
  `not_found` de HA, no rechazo de Hermes).
- **CAP-063**: el banco no tiene satélites; unitarios con la WebSocket
  simulada.
- **Inventarios**: `tests/banco/cobertura_023.py` con
  `PROBADAS_023 = {"ha_process_conversation"}`, sumado al invariante de
  escrituras y a `TOOLS_EXIGIDAS_DEL_JOB`. `ha_call_ws_command` ya es de
  `PROBADAS_GENERICAS` (011).

## R-7 — Lo que no se duplica

- La exposición (021, `assistant_exposure`): el tema `conversation` dice que
  lo que Assist puede controlar depende de la exposición y, si las tools de
  la 021 están en la rama al implementar, las nombra; si no, describe el
  concepto sin nombrar tools que no existen (principio V). Al integrarse la
  segunda de las dos, se completa (anotado en el plan).
- `ha_call_service_response` con `conversation.process` (018): sigue igual.
  Es la acción de HA (la de las automatizaciones), no el comando WS; está en
  la denylist y pide token. El tema `services` no se toca (su huella no
  cambia); el tema `conversation` dice que la vía recomendada es
  `ha_process_conversation`, porque su vista previa dice qué reconoce HA.
