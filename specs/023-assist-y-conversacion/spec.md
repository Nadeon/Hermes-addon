# Especificación: Hermes 1.2.0 — Assist y conversación (sub-feature 023)

**Directorio de la spec**: `specs/023-assist-y-conversacion`

**Creada**: 2026-11-15

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T022 de su `tasks.md` (tamaño S, 1 tramo) y cubre
**CAP-060** (conversación, por tools dedicadas) y **CAP-061**, **CAP-062** y
**CAP-063** (pipelines de Assist, motores de voz, LLM, AI Task y satélites,
por la tabla), es decir, FR-083 y FR-084 de la 008. Depende de la 011 (tabla,
genéricas y familias) y de la 018 (sobre común de las listas;
`ha_call_service_response` con token para la denylist).

**Entrada**: `specs/008-cobertura-total/` (spec, plan con la matriz de
trazabilidad, research CAP-060…CAP-063 e `inventario/core-ws.tsv`), la 011
(`command_table.py`, `command_policy.py`, `tool_families.py`,
`scripts/inventario/generar_tabla.py`), la 010 y la 028 (banco de Core e
inventarios de escrituras), la 014 (matriz de pruebas), la 033 (inventario de
argumentos atados) y el código de Hermes: `tools/ha.py`
(`ha_call_service_response`), `tools/generic_commands.py`,
`tools/_common.py` (sobre común, recortes, `requires_ready`), `security.py`
(`create_confirmation_token`, `validate_confirmation_token`,
`complete_confirmation_token`, `redact_secrets`, `redact_structure`),
`tools/_annotations.py` y `tools/guide.py`. Contrastado con el código de HA
Core 2026.11.1: `components/conversation/http.py` (los ocho comandos WS de
`conversation/*`), `conversation/agent_manager.py` (`async_converse`,
`trigger_sentences`), `conversation/default_agent.py`
(`async_debug_recognize`), `conversation/const.py`
(`HOME_ASSISTANT_AGENT`), `homeassistant/exposed_entities.py`,
`assist_pipeline/pipeline.py` y `websocket_api.py`, `assist_satellite/websocket_api.py`,
`tts/__init__.py` (`TextToSpeechView`, `requires_auth = False`),
`stt/__init__.py`, `wake_word/__init__.py`, `llm/websocket_api.py` y
`ai_task/http.py` y `__init__.py`.

## Clarificaciones

### Sesión 2026-11-15

Decisiones vinculantes del programa (ya están en la 008 y en la 011):

- CAP-060 es de prioridad **media-alta** y va por **tools dedicadas**
  (decisión 1 de la 008). Procesar una frase **ejecuta intents** (puede abrir
  una cerradura): pide **confirmación en dos pasos**. Analizarla sin
  ejecutar, no.
- CAP-061, CAP-062 y CAP-063 son de prioridad **baja** y van **por la
  tabla**: lectura `read` (`ha_read_ws_command`) y escritura `confirm`
  (`ha_call_ws_command`, siempre en dos pasos). La 011 ya las clasificó así;
  esta sub-feature las revisa contra el código y las prueba.
- `assist_pipeline/run` (audio y *streaming*) es **clase D** y sigue `deny`;
  la variante «solo texto» es una candidata D-01 de la 008 y queda fuera.
  Las suscripciones (`conversation/chat_log/subscribe*`,
  `assist_pipeline/pipeline/subscribe`) y los asistentes interactivos de los
  satélites son **clase B** y siguen `deny`.
- La **exposición de entidades a asistentes** (CAP-055) es de la 021
  (familia `assistant_exposure`, sin integrar todavía): aquí no se duplica.
- Las tools nuevas van en una **familia nueva** de la 1.2.0 (FR-010 de la
  008): con las familias de la 1.2.0 desactivadas, la lista vuelve a ser la
  de la 1.1.2.

Decisiones tomadas al especificar (se justifican en
[research.md](research.md)):

- P: ¿Qué tools y con qué nombres? → R: **cuatro**, las que propone la 008:
  `ha_list_conversation_agents`, `ha_list_conversation_sentences`,
  `ha_debug_conversation` y `ha_process_conversation`.
  `conversation/agent/homeassistant/language_scores` no tiene tool propia: se
  pliega en `ha_list_conversation_agents(include_language_scores=true)`
  (research R-1).
- P: ¿Familia? → R: una nueva, `conversation` («desde» 1.2.0, desactivable),
  con el módulo `conversation`. Un tema de guía, `conversation` (research
  R-1).
- P: ¿Qué dice la vista previa de `ha_process_conversation`? → R: el agente
  que procesará la frase (id, nombre, si es el agente por defecto de HA) y,
  **si es el agente por defecto**, lo que HA reconoce en la frase sin
  ejecutarla (`conversation/agent/homeassistant/debug`): intent, huecos,
  entidades objetivo (como mucho 50, con el total) y si coincide con una
  frase de una automatización (que se ejecutaría entera). Con **otro agente**
  (un LLM, local o en la nube), Hermes no puede predecir qué hará: la vista
  previa lo dice y avisa de que el texto se envía a ese agente, que puede ser
  un servicio externo (research R-2).
- P: ¿Qué anotaciones lleva `ha_process_conversation`? → R: **destructiva**
  (puede abrir cerraduras o puertas de garaje, desarmar alarmas y ejecutar
  automatizaciones), **no idempotente** (repetirla repite la acción; «apaga
  o enciende» alterna) y **de mundo abierto** (el agente puede ser un LLM en
  la nube; la anotación estática dice el peor caso). Las otras tres, de solo
  lectura y sin mundo abierto: solo usan el agente por defecto, que es local
  (research R-3).
- P: ¿Se emite token si el agente por defecto no reconoce la frase? → R:
  **sí**, con `recognition.match: false` y la nota de que HA responderá con
  un error sin accionar nada. El análisis y el proceso usan el mismo
  reconocedor, pero no son la misma llamada; negar el token por el análisis
  bloquearía frases que HA sí entiende (research R-2).
- P: ¿Qué se rechaza sin token? → R: argumentos inválidos y un `agent_id` que
  no está en `conversation/agent/list` (`agent_not_found`, con los
  disponibles): HA respondería con un error genérico (`ValueError`) y no
  serviría de nada confirmar (research R-2).
- P: ¿Qué pasa si el proceso tarda más que el plazo? → R: la respuesta dice
  que **puede haberse ejecutado igualmente** (`outcome_unknown`): un
  `timeout` del cliente no cancela lo que HA ya está haciendo. El token queda
  consumido (research R-4).
- P: ¿Qué se corrige en la tabla para CAP-061…CAP-063? → R: dos cosas
  halladas al revisar el código. (1) `assist_pipeline/pipeline_debug/get`
  devuelve, en el evento `tts-end`, la `url` `/api/tts_proxy/<token>`; esa
  vista de HA **no pide autenticación** (`requires_auth = False`): la URL es
  una credencial de hecho para descargar el audio. La clave `token` ya se
  tapa por su nombre, la `url` no: la entrada gana `redact_extra=("url",)`.
  (2) El motivo de `ai_task/preferences/set` dice ahora que
  `allow_automatic_evaluation` deja a HA usar por su cuenta el modelo de
  decisión (un LLM, que puede estar en la nube). El resto se confirma tal
  cual (research R-5).
- P: ¿Cómo se prueban CAP-061…CAP-063? → R: CAP-061 y CAP-062 en el banco de
  Core (la configuración del banco carga `assist_pipeline:` y `ai_task:`):
  leer pipelines, idiomas, dispositivos, motores y APIs de LLM, y el ciclo
  crear → actualizar → preferido → borrar de un pipeline y fijar las
  preferencias de AI Task, todo por las genéricas. CAP-063 en unitarios: el
  banco no tiene ningún satélite (research R-6).

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es el administrador de Home Assistant que trabaja desde un
cliente MCP (un agente) y quiere usar o depurar Assist sin abrir la
interfaz.

### Historia 1 — Entender qué haría Assist con una frase (Prioridad: P1)

Quien escribe frases personalizadas o automatizaciones con disparador de
frase quiere saber si HA entiende una frase, qué intent reconoce y sobre qué
entidades actuaría, **sin** que se ejecute nada.

**Prueba independiente**: en el banco de Core, con una automatización de
prueba con disparador de frase, `ha_debug_conversation` la reconoce como
`source: "trigger"`, una frase sin sentido sale `match: false`, y el estado
que vigila el lector independiente no cambia.

**Escenarios de aceptación**:

1. **Dado** `ha_debug_conversation(sentences=["frase centinela del banco"])`
   y una automatización con ese disparador, **entonces** el resultado de esa
   frase trae `match: true`, `source: "trigger"` y la plantilla, y la
   automatización **no** se ejecuta.
2. **Dado** una frase que HA no entiende, **entonces** su resultado es
   `{"match": false, "recognized": false}` (HA devuelve `null`) y el orden
   de los resultados es el de las frases.
3. **Dado** más de 20 frases, una vacía o una de más de 500 caracteres,
   **entonces** `invalid_argument` sin llamar a HA.
4. **Dado** una frase que reconoce un intent con muchas entidades objetivo,
   **entonces** salen como mucho 50 con `targets_total` y
   `targets_truncated: true`.

### Historia 2 — Ver agentes y frases (Prioridad: P1)

Quien tiene varios agentes de conversación (el de HA, uno de OpenAI, uno de
Ollama…) quiere ver cuáles hay, qué idiomas admiten y qué frases de
automatizaciones tiene registradas.

**Prueba independiente**: en el banco, `ha_list_conversation_agents` trae
`conversation.home_assistant` marcado como agente por defecto, y
`ha_list_conversation_sentences` trae la frase de la automatización de
prueba.

**Escenarios de aceptación**:

1. **Dado** `ha_list_conversation_agents()`, **entonces** el sobre común con
   `id`, `name`, `supported_languages` (`"*"` o la lista) y
   `is_default_agent` en cada agente.
2. **Dado** `language="es"`, **entonces** HA filtra los idiomas de cada
   agente a los que encajan (`country` opcional).
3. **Dado** `include_language_scores=true`, **entonces** la respuesta añade
   `default_agent_language_scores` con `preferred_language` y la puntuación
   por idioma del agente por defecto.
4. **Dado** `ha_list_conversation_sentences(search="luz")`, **entonces** solo
   las frases que contienen el texto (sin distinguir mayúsculas), ordenadas,
   sin repetir, con el sobre común; la descripción dice que son solo las de
   los disparadores de frase de automatizaciones, no las integradas de HA ni
   las de `custom_sentences/`.

### Historia 3 — Mandar una frase a Assist con confirmación (Prioridad: P1)

Quien quiere que la casa haga algo diciéndolo como lo diría por voz («apaga
las luces del salón») quiere mandar la frase a Assist desde el agente, pero
sabiendo antes qué va a pasar y a quién se manda el texto.

**Prueba independiente**: en el banco, la primera llamada a
`ha_process_conversation` devuelve vista previa y token y no ejecuta nada (el
lector ve el estado sin cambios); la segunda, con el token, ejecuta la
automatización de prueba y el lector ve el efecto; repetir el token falla.

**Escenarios de aceptación**:

1. **Dado** `ha_process_conversation(text="frase centinela del banco")` sin
   token, **entonces** `preview` con el agente (`conversation.home_assistant`,
   `is_default_agent: true`, `local: true`), el reconocimiento (`match:
   true`, `source: "trigger"`) y el aviso de que se ejecutará la
   automatización, más `confirmation_token`; nada se ejecuta.
2. **Dado** la misma llamada con el token, **entonces** HA procesa la frase y
   la respuesta trae `response_type`, `speech` (texto), `data` (objetivos con
   éxito y fallidos, o el código de error), `conversation_id` y
   `continue_conversation`.
3. **Dado** el token con otro `text`, otro `agent_id`, otro `language`, otro
   `conversation_id` u otro `device_id`, **entonces** el token no vale (está
   atado a los cinco).
4. **Dado** `agent_id` de un agente que no es el de HA (p. ej.
   `conversation.ejemplo_llm`), **entonces** la vista previa dice
   `is_default_agent: false`, `local: "unknown"`, que Hermes no puede predecir
   qué hará el agente y que el texto se enviará a ese agente, que puede ser
   un servicio externo; no trae reconocimiento.
5. **Dado** un `agent_id` que no existe, **entonces** `agent_not_found` con
   los agentes disponibles y sin token.
6. **Dado** que HA no responde dentro del plazo al confirmar, **entonces**
   `outcome_unknown`: la respuesta dice que la frase pudo ejecutarse y cómo
   comprobarlo (estados, `ha_get_logbook`).
7. **Dado** `ha_read_ws_command` o `ha_call_ws_command` con cualquiera de los
   cinco comandos de CAP-060, **entonces** `use_dedicated_tool` con su tool y
   sin llamar a HA.

### Historia 4 — Pipelines, motores y satélites por la tabla (Prioridad: P2)

Quien configura Assist quiere ver y cambiar sus pipelines, los motores de
voz y las preferencias de AI Task, y las palabras de activación de un
satélite, con las genéricas.

**Prueba independiente**: en el banco, las lecturas de CAP-061 y CAP-062
responden por `ha_read_ws_command`, y el ciclo de un pipeline de prueba y las
preferencias de AI Task se hacen por `ha_call_ws_command` en dos pasos; el
lector independiente ve cada efecto. En unitarios, los dos comandos de
satélite pasan por la genérica que les toca.

**Escenarios de aceptación**:

1. **Dado** `ha_read_ws_command("assist_pipeline/pipeline/list")`,
   **entonces** los pipelines y el preferido.
2. **Dado** `ha_call_ws_command("assist_pipeline/pipeline/create", …)` sin
   token, **entonces** vista previa y token; con el token, el pipeline
   existe; lo mismo con `update`, `set_preferred` y `delete`.
3. **Dado** `ha_call_ws_command` con un comando `read` (p. ej.
   `assist_pipeline/pipeline/list`), **entonces** el rechazo de siempre hacia
   la de lectura; y al revés con `ha_read_ws_command` y uno `confirm`.
4. **Dado** `ha_read_ws_command("assist_pipeline/pipeline_debug/get", …)` con
   un evento `tts-end`, **entonces** la `url` del audio y el `token` salen
   tapados.
5. **Dado** `ha_read_ws_command("assist_satellite/get_configuration",
   {"entity_id": "assist_satellite.salon"})`, **entonces** la configuración;
   y `assist_satellite/set_wake_words` solo por `ha_call_ws_command` en dos
   pasos.
6. **Dado** `assist_pipeline/run`, `assist_pipeline/device/capture` o
   `assist_satellite/intercept_wake_word`, **entonces** siguen rechazados por
   las dos genéricas.

### Historia 5 — Nada se rompe (Prioridad: P1)

**Prueba independiente**: con la familia `conversation` desactivada, la
lista de tools es la de antes de la 023 y los cinco comandos de CAP-060
responden `use_dedicated_tool` con `family_disabled: true`.

### Casos límite

- `conversation/sentences/list` exige administrador en HA: si el token de
  Hermes no lo es, el error de HA se traduce (`unauthorized`) sin inventar
  una lista vacía.
- El agente por defecto no existe todavía (HA arrancando, `conversation` sin
  cargar): `unknown_command` → `conversation_not_loaded` en las cuatro.
- Una frase que coincide con un disparador de frase: el análisis no puede
  decir qué hará la automatización (HA tampoco: «no se puede dar la
  respuesta sin ejecutar el disparador»); la vista previa lo dice.
- Respuesta de un LLM muy larga: `speech` se recorta al tope con
  `speech_truncated: true`; el resto de la respuesta se conserva.
- `conversation_id` de una conversación caducada: HA abre una nueva y
  devuelve otro id; la tool lo devuelve tal cual.
- `device_id` cambia el área por defecto («enciende la luz» en la habitación
  del dispositivo): por eso está atado al token.

## Requisitos *(obligatorio)*

### Requisitos funcionales

- **FR-001**: `ha_list_conversation_agents(language?, country?,
  include_language_scores=false)` lista los agentes de conversación
  (`conversation/agent/list`) con el sobre común (`sobre_de_lista`), cada uno
  con `id`, `name`, `supported_languages` y `is_default_agent`; con
  `include_language_scores=true` añade
  `conversation/agent/homeassistant/language_scores`. Solo lee (FR-083,
  CAP-060).
- **FR-002**: `ha_list_conversation_sentences(search?, limit=100)` lista las
  frases de los disparadores de frase (`conversation/sentences/list`),
  ordenadas y sin repetir, filtradas por `search` y con el sobre común. Solo
  lee (FR-083, CAP-060).
- **FR-003**: `ha_debug_conversation(sentences, language?, device_id?)`
  devuelve, por frase y en orden, lo que el agente por defecto reconoce
  (`conversation/agent/homeassistant/debug`): `match`, `source`, intent,
  huecos, objetivos (como mucho 50 por frase, con `targets_total`) y
  plantilla. Nunca ejecuta nada; la descripción lo dice (FR-083, CAP-060).
- **FR-004**: `ha_process_conversation(text, agent_id?, language?,
  conversation_id?, device_id?, confirmation_token?)` procesa la frase
  (`conversation/process`) **solo con un token** emitido por una vista previa
  que dice el agente, si es local y, con el agente por defecto, el
  reconocimiento; el token se ata a los cinco argumentos (FR-083, CAP-060).
- **FR-005**: `ha_process_conversation` rechaza sin token los argumentos
  inválidos y el agente que no existe (`agent_not_found`), y al confirmar
  devuelve la respuesta de HA (tipo, texto, datos, `conversation_id`,
  `continue_conversation`) redactada y dentro del tope; si vence el plazo,
  `outcome_unknown` (FR-083, CAP-060).
- **FR-006**: Las descripciones de las cuatro tools dicen la verdad: que
  procesar ejecuta intents y automatizaciones sobre las entidades expuestas,
  que con un agente que no es el de HA el texto sale hacia ese agente (que
  puede ser un servicio en la nube), y que analizar no ejecuta (principio V;
  FR-083).
- **FR-007**: Anotaciones: `ha_process_conversation` destructiva, no
  idempotente y de mundo abierto; las otras tres, de solo lectura,
  idempotentes y sin mundo abierto (`ha_debug_conversation` por nombre
  exacto en `_READ_ONLY_EXACT`) (FR-018 de la 008).
- **FR-008**: Los cinco comandos de CAP-060 pasan de `deny` «pendiente de
  tool dedicada (spec 023)» a `dedicated` con su tool y la familia
  `conversation`, por el mecanismo del generador (`_DEDICADAS_INICIALES`);
  regenerar la tabla no cambia nada (FR-012 de la 008; FR-083).
- **FR-009**: Las entradas de CAP-061, CAP-062 y CAP-063 quedan `read` /
  `confirm` revisadas contra el código de Core 2026.11.1;
  `assist_pipeline/pipeline_debug/get` gana `redact_extra=("url",)` y
  `ai_task/preferences/set` un motivo que dice la evaluación automática;
  `assist_pipeline/pipeline/create` gana un `example` revisado con datos
  ficticios (FR-084, CAP-061…CAP-063).
- **FR-010**: Las tools van en la familia nueva `conversation` («desde»
  1.2.0, desactivable); con ella desactivada no se registra ninguna y el
  resto no cambia (FR-010 de la 008).
- **FR-011**: Respuestas redactadas (`redact_structure` + `redact_secrets`
  en los textos) y dentro de `response_max_bytes`; el log lleva solo la
  tool, el resultado y recuentos (y si el agente es el por defecto), nunca
  el texto, la respuesta hablada, el `conversation_id` ni ids de entidades
  (FR-019 de la 008; principio II).
- **FR-012**: Un `unknown_command` de HA se traduce por su causa
  (`conversation_not_loaded`); un error de HA se devuelve redactado (FR-020
  de la 008).
- **FR-013**: Tema `conversation` en la guía (con alias) que explica las
  cuatro tools, el aviso del agente externo, qué controla Assist (la
  exposición) y las entradas de pipelines, motores, AI Task y satélites por
  las genéricas; el índice lo menciona; los temas existentes no cambian
  (FR-011 y FR-018 de la 008).
- **FR-014**: `ha_process_conversation` se ejecuta en el banco de Core
  (inventario `tests/banco/cobertura_023.py`, exigida por ejecución en el
  job) y tiene su fila en la matriz de la 014 y en el inventario de
  argumentos atados de la 033; las entradas de CAP-061 y CAP-062 se ejecutan
  en el banco por las genéricas; las de CAP-063, en unitarios (FR-014 y
  FR-016 de la 008; FR-084).
- **FR-015**: Documentación en el mismo cambio: sección «Assist y
  conversación» en `## [1.2.0]` del CHANGELOG, estado de la 023 en la hoja de
  ruta, recuento de tools y familia en `README.md`, `README.es.md` y
  `hermes/DOCS.md`, y filas CAP-060…CAP-063 de la matriz de la 008 (FR-023
  de la 008).

### Entidades clave

- **Agente de conversación**: id (`conversation.<x>` o el de un agente
  heredado), nombre e idiomas; el agente por defecto es
  `conversation.home_assistant` (`HOME_ASSISTANT_AGENT`), local.
- **Reconocimiento**: lo que el agente por defecto entiende de una frase sin
  ejecutarla.
- **Vista previa de proceso**: agente, si es local, reconocimiento (solo con
  el agente por defecto) y avisos.
- Ver [data-model.md](data-model.md).

## Criterios de éxito *(obligatorio)*

- **SC-001**: Con la familia `conversation` desactivada, la lista de tools es
  exactamente la de antes de la 023.
- **SC-002**: Ninguna entrada de la tabla dice «(spec 023)».
- **SC-003**: `ha_process_conversation` no ejecuta nada sin token en ningún
  test (unitario ni de banco): el lector independiente del banco no ve
  cambios tras la vista previa.
- **SC-004**: Ningún texto de frase, respuesta hablada ni `conversation_id`
  aparece en el log capturado de ningún test (centinelas).
- **SC-005**: El banco ejecuta `ha_process_conversation` con éxito y el job lo
  exige; las lecturas y escrituras de CAP-061 y CAP-062 por las genéricas
  pasan contra HA Core 2026.11.1 real o quedan como hallazgo `xfail`
  estricto con su causa.
- **SC-006**: La suite termina con los 6 fallos conocidos de Windows y
  ninguno más; el CI de Linux, en verde.

## Supuestos

- **S-01**: El token de Hermes contra Core es de administrador (como en el
  resto de tools que usan comandos con `require_admin`).
- **S-02**: `assist_pipeline:` y `ai_task:` arrancan en el banco sin
  internet (sus dependencias `tts`, `stt` y `wake_word` son locales). Si no,
  se anota como hallazgo y esas pruebas pasan a unitarios con la causa.
- **S-03**: `conversation/agent/list` lista también los agentes que no son
  entidades (heredados); su id no siempre es un `entity_id` y se acepta tal
  cual como `agent_id`.
- **S-04**: La 021 se integra en paralelo; el tema de guía solo nombra sus
  tools de exposición si ya están en la rama al implementar.

## Fuera de alcance

- `assist_pipeline/run` (audio, *streaming*; clase D) y su variante solo
  texto (candidata D-01 de la 008).
- Las suscripciones del historial de chat y de pipelines, `conversation/prepare`
  y los asistentes interactivos de satélites (clase B).
- La exposición de entidades a asistentes (021, CAP-055) y la de Alexa y
  Google de la nube (clase D).
- Tools dedicadas para pipelines, motores, AI Task o satélites: van por la
  tabla (FR-084 de la 008).
- Cambiar el tema `services` de la guía o `ha_call_service_response`
  (`conversation.process` como acción sigue en la denylist y con token).
