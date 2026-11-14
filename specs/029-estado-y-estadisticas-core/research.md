# Research: estado del sistema y estadísticas de Core (029)

Fase 0 del plan. Todo se ha comprobado leyendo el código de Home Assistant
Core 2026.11.1 (carpeta local de fuentes, solo lectura) y el de Hermes en la
punta de `feat/029-estado-y-estadisticas-core` (la 011 hasta T037).

## R-0 — Punto de partida en Hermes

- `command_table.py` (011) tiene **nueve** comandos `deny` «pendiente de tool
  dedicada (spec 029)»: `system_health/info`, `subscribe_system_state`,
  `integration/setup_info`, `manifest/list`, `manifest/get` (CAP-043) y
  `recorder/info`, `recorder/entity_options/get`,
  `recorder/validate_statistics`, `recorder/get_statistics_metadata`
  (CAP-049). Son todos los de la 029: ninguna ruta del Supervisor.
- Las cuatro de vía T ya están `read` por la revisión manual de la 011:
  `logbook/get_action_calls` (CAP-058), `network`, `network/url` y
  `http/config` (CAP-068). Les falta lo que pide la 008: tema en la guía y
  prueba en el banco; y a la primera, una redacción que cumpla lo que su
  motivo promete (R-6).
- `tests/test_command_table.py::test_clase_a_de_via_dedicada_pendiente_de_su_spec`
  exige `deny` «pendiente» para toda la clase A de vía D, y el generador solo
  consulta `_DEDICADAS_INICIALES` para la clase «cubierto». La 012 cambia las
  dos cosas (su research R-7); la 029 necesita el mismo cambio (R-7).
- Ya existen `ha_list_statistic_ids` y `ha_statistics_during_period`
  (`tools/statistics.py`, familia `data` de la 1.1.2), que usan
  `recorder/list_statistic_ids` y `recorder/statistics_during_period`. No
  cambian.
- `ws_one_shot_subscription` (`ha.py`) manda el comando, espera el `result`,
  devuelve el PRIMER evento y cancela con `unsubscribe_events` en un
  `finally`; con `collect_warnings` sigue tras avisos, pero termina en el
  primer evento con `result`. Sirve para `subscribe_system_state`, no para
  `system_health/info` (R-1).
- Línea base de la suite en Windows al especificar (punta `ab5098d`): 2126
  passed, 17 skipped, 6 failed (los 6 conocidos).

## R-1 — `system_health/info` es una suscripción de varios mensajes

**Código** (`components/system_health/__init__.py`, `handle_info`): HA calcula
la información de cada dominio registrado; los valores que son corrutinas los
lanza como tareas y los pone como `{"type": "pending"}`. Manda el `result`
(confirma la suscripción), luego un evento `{"type": "initial", "data":
{dominio: {"info": {...}, "manage_url"?}}}`; si no hay pendientes, un evento
`{"type": "finish"}` y termina. Si los hay, un evento `{"type": "update",
"domain", "key", "success", "data" | "error"}` por cada tarea que termina y,
al final, `finish`. Las fechas van como `{"value": iso, "type": "date"}`
(`_format_value`). Cada callback de dominio tiene su propio tope en HA
(`INFO_CALLBACK_TIMEOUT`); las tareas pendientes, no (por ejemplo,
`can_reach_cert_server` de la nube).

**Decisión**: método nuevo del cliente,
`HAClient.ws_collect_subscription(payload, *, terminado, timeout_seconds)`,
que manda el comando, espera el `result`, acumula eventos en orden hasta que
`terminado(evento)` es verdad o vence el plazo TOTAL (no por evento), y
cancela siempre en un `finally` (mismo `_ws_unsubscribe` que la de un solo
mensaje). Devuelve `(eventos, completo)`. Un error de HA en el `result` lanza
`HAConnectionError` con `code`, como `ws_send`.

**Por qué no reutilizar `ws_one_shot_subscription`**: cambiar su contrato
(FR-020 de la 008) afectaría a `ha_render_template` y las demás que la usan;
un método aparte con su test no toca nada existente.

**Alternativas descartadas**: usar `system_health/info` solo con el inicial
(deja «pending» lo más interesante: conectividad de la nube, versiones de
las apps); esperar sin tope (un pendiente colgado bloquearía la tool);
`ws_subscribe_events_queue` (es para `subscribe_events` de un tipo de evento,
no para un comando cualquiera).

**Tope**: `timeout_seconds` 10 por defecto, de 1 a 30. Lo que no llegue
queda en `pending`; lo que llegue con `success: false`, en `failed`. Un
`update` de un dominio o clave que no venía en el inicial se ignora (se cuenta
en el log) en vez de inventar estructura.

## R-2 — `subscribe_system_state`

**Código** (`websocket_api/commands.py`, `handle_subscribe_system_state`,
`require_admin`): manda el `result` y, en seguida, un evento con
`SystemState.as_dict()`: `home_assistant_restart_required`,
`home_assistant_restart_sources` (lista ordenada), `home_assistant_restart_dismissed`,
`host_reboot_required` y `host_reboot_dismissed`
(`helpers/system_state.py`). Después, un evento por cada cambio.

**Decisión**: `ws_one_shot_subscription` con su tope de 10 s; se devuelve el
diccionario tal cual (los nombres de HA son claros). Las fuentes son dominios
o identificadores de HA, no datos del usuario. Descartar el aviso
(`dismiss_system_state`) es clase B por la 011 y no se toca.

## R-3 — Tiempos de arranque y manifiestos

- `integration/setup_info` (sin `require_admin`): lista de `{"domain",
  "seconds"}` de `async_get_setup_timings` (suma de fases de nivel superior más
  el máximo de los grupos). Decisión: ordenar de más lenta a más rápida,
  `limit` 1–500 (50 por defecto), `min_seconds` opcional, `total` y
  `total_seconds` sobre todas (no solo las devueltas), `seconds` redondeados a
  milésimas.
- `manifest/list` (`integrations` opcional; sin él, las cargadas) devuelve el
  `manifest_json_fragment` de cada una; HA omite las que no puede cargar y lo
  registra en su log. `manifest/get` (`integration` obligatorio) responde
  `not_found` si no existe. `loader.py` añade al manifiesto `is_built_in` y
  `overwrites_built_in`. Un manifiesto ocupa del orden de 0,5–2 KB y una
  instalación típica carga cientos: la lista entera no cabe en el tope.
- **Decisión**: dos tools. `ha_list_integration_manifests` con un resumen de
  diez campos fijos (los que sirven para decidir: dominio, nombre, tipo, clase
  de IoT, calidad, versión, de HA o no, si sustituye a una de HA, si tiene
  flujo de configuración, documentación), `custom_only` y `missing`;
  `ha_get_integration_manifest` con el manifiesto entero. Research R-2 de la
  008 proponía un solo nombre (`ha_get_integration_manifest`); sus nombres son
  propuestas (S-05 de la 008).
- Texto de terceros: el manifiesto de una integración personalizada lo escribe
  su autor (`name`, `documentation`, `issue_tracker`, `codeowners`…). Se marca
  con `_third_party_text`, como en `tools/marketplace.py`.
- Forma del nombre de integración: `^[a-z0-9_]+$`, hasta 64 caracteres (la de
  los dominios de HA).

## R-4 — Estadísticas y recorder

- `recorder/validate_statistics` (sin `require_admin`): ejecuta en un hilo
  `validate_statistics`, que pregunta a cada plataforma de recorder (en la
  práctica, `sensor/recorder.py`) y devuelve `{statistic_id: [{"type",
  "data"}]}`. **Solo lee**: crear o actualizar los avisos de Repairs es
  `recorder/update_statistics_issues` (CAP-050, 020). Decisión: lista plana
  con `statistic_id`, `type` y `data`, orden por `statistic_id`, filtros
  `statistic_id` e `issue_type`, `by_type` antes de filtrar. Su nombre no
  tiene prefijo de lectura: `readOnlyHint` por nombre exacto.
- `recorder/get_statistics_metadata` (`statistic_ids` opcional) usa
  `async_list_statistic_ids`: lo mismo que `recorder/list_statistic_ids` (que
  ya usa `ha_list_statistic_ids`) pero filtrado por id. Decisión:
  `statistic_ids` obligatorio, 1–100, sin repetidos, con forma
  `^[a-z0-9_]+[.:][a-z0-9_]+$` (entidad o estadística externa); `missing` con
  los pedidos que no vuelven.
- `recorder/info`: espera a que la base esté conectada y devuelve siete
  campos (`backlog`, `max_backlog`, `recording`, `thread_running`,
  `migration_in_progress`, `migration_is_live`, `db_in_default_location`).
  No da la URL de la base (bien: puede llevar credenciales).
- `recorder/entity_options/get` (`require_admin`, `entity_id` con
  `cv.strict_entity_id`): `{"recording_disabled_by": null | "user"}` según
  `is_entity_recorded`, que mira los filtros del recorder y NO comprueba que la
  entidad exista. Decisión: dentro de `ha_get_recorder_info(entity_id=…)`,
  comprobando antes que la entidad existe (`entity_exists` de
  `tools/_common.py`) para no decir «se graba» de algo que no está; `recorded`
  es `recording_disabled_by is None`.
- Sin `recorder:` cargado, los comandos no están registrados: HA responde
  `unknown_command`. En una HA con recorder, ninguno de los cuatro es nuevo
  salvo `entity_options/get` (R-5). Decisión: `recorder_not_loaded` para las
  tres tools si falla el comando principal; para `entity_options/get`,
  `unsupported_by_ha_version` solo en `entity`.

## R-5 — Comandos recientes y la versión mínima

`subscribe_system_state` usa `helpers/system_state.py` y
`recorder/entity_options/get` vive en `recorder/entity_options.py`; los dos
son de la serie 2026 y no existen en la versión mínima declarada (2024.10).
Las fuentes son un único árbol sin historia, así que no se puede fijar la
versión exacta en que aparecieron. **Decisión**: no comprobar la versión antes
(`ha_at_least` exigiría una cifra que no se puede verificar); traducir el
`unknown_command` de HA a `unsupported_by_ha_version` con `ha_code` y la
versión de la tabla (`TABLE_HA_CORE`), como hace la genérica con su pista. El
resto de comandos de la 029 existen en 2024.10.

Un `unknown_command` no siempre es la versión: `system_health/info` y los del
recorder solo existen si su integración está cargada (en HA OS lo están por
`default_config`, pero el banco y quien no use `default_config` pueden no
tenerlas). Decir «tu HA es antigua» en ese caso sería mentir (principio V):
esos dos casos dan `system_health_not_loaded` y `recorder_not_loaded`.

## R-6 — `logbook/get_action_calls` y el código de las alarmas

**Código** (`logbook/websocket_api.py`, `ws_get_action_calls`,
`require_admin`): `start_time` obligatorio y `end_time` opcional (texto ISO);
devuelve las entradas del logbook de los eventos `call_service` del intervalo
con `domain`, `service`, `service_data` y el contexto. El propio HA lo
restringe a administradores porque «los datos de la acción pueden contener
secretos como códigos de alarma».

**Hallazgo**: la entrada de la 011 dice que «la respuesta se redacta», pero
`redact_structure` solo tapa claves con marcadores (`password`, `token`,
`secret`…); `code` (el de `alarm_control_panel.alarm_disarm`,
`lock.unlock`…) no lo es. **Decisión**: `redact_extra=("code",)` en la entrada
(la genérica lo aplica por nombre exacto de clave, en cualquier nivel) y test
centinela en respuesta y log. Se tapa cualquier `code` de cualquier acción: es
fail-closed y el valor de un `code` no hace falta para auditar quién llamó a
qué. Ejemplo de carga: `{"start_time": "2026-01-01T00:00:00+00:00",
"end_time": "2026-01-01T06:00:00+00:00"}`.

## R-7 — Cómo pasar a `dedicated` (mismo mecanismo que la 012)

- El generador conserva byte a byte cada entrada existente, así que editar la
  tabla a mano y regenerar la deja igual. Para que una generación desde cero
  también dé `dedicated`, las nueve claves van en `_DEDICADAS_INICIALES` y
  `_clasificar` consulta el mapa también para la clase A, antes de la regla
  «pendiente de tool dedicada».
- `test_clase_a_de_via_dedicada_pendiente_de_su_spec` pasa a admitir, para una
  fila A de vía D/D+T/D+X, `dedicated` con una tool de una familia de la 1.2.0;
  `read` o `confirm` siguen fallando.
- **Ese cambio es el T013 de la 012** (su research R-7). La 029 no lo
  duplica: si al implementar la 012 ya está integrada, solo añade sus nueve
  claves y sus tests; si no, lo hace ella con el mismo diseño y la que se
  integre segunda resuelve el conflicto conservando las claves de las dos
  (duda D-3 de la spec).

## R-8 — Familias, guía y anotaciones

- Dos familias de la 1.2.0: `system_status` («System health, pending restart
  state, integration setup times and manifests (read only).») con el módulo
  `system_status`, y `recorder` («Recorder status and long-term statistics
  validation and metadata (read only).») con el módulo `recorder_status`.
  `recorder_status` y no `recorder` para no confundir el módulo de tools con
  la integración. Si la 020 añade escrituras a `recorder`, cambia la
  descripción (duda D-2).
- Temas de la guía con el nombre de la familia. Alias: `system_status` ←
  `health`, `system_health`, `system_state`, `manifest`, `manifests`,
  `setup_times`, `urls`; `recorder` ← `recorder_info`,
  `statistics_validation`, `action_calls`, `audit`. **No** se toca el alias
  `statistics` (→ `data`, de la 1.1.2): `test_sin_search_los_temas_de_la_1_1_2_no_cambian`
  y FR-020 de la 008. El índice (`_OVERVIEW`) añade dos líneas.
- Anotaciones: los prefijos `ha_get_`/`ha_list_` ya dan `readOnlyHint`;
  `ha_validate_statistics` va en `_READ_ONLY_EXACT` con su porqué. Las ocho en
  `_HINTS_NUEVAS_1_2_0` de `tests/test_tools_registration.py` con código
  `R-I-` y el título que genere `_annotations` (único).

## R-9 — Banco de Core

- `tests/banco/ha_config/configuration.yaml` de la 010 no lleva
  `default_config`. Hay que añadir `system_health:`, `recorder:` (SQLite en
  `/config`, sin red), `logbook:` y `network:`. `http` ya está.
- Pruebas: salud con el dominio `homeassistant` y su versión 2026.11.1;
  estado sin reinicio pendiente; tiempos con `recorder` o `http`; manifiestos
  de `input_boolean` (de HA) y lista con él; validación (lista, quizá vacía);
  metadatos de un id inexistente en `missing`; recorder grabando; opciones de
  un `input_boolean` creado por el lector; auditoría tras llamar a
  `input_boolean.turn_on` (si el banco no graba `call_service`, se anota);
  `network`, `network/url` y `http/config` por la genérica.
- Invariante de cobertura: la 010 tiene `tests/banco/cobertura.py` y
  `tests/test_banco_cobertura.py` solo para las escrituras de los helpers. La
  029 añade `PROBADAS_EN_BANCO_029` (sus ocho tools) y un test que comprueba
  que coincide exactamente con lo que registran los dos módulos y que cada
  nombre aparece en un fichero `tests/banco/test_banco_*.py`.

## R-10 — Log y privacidad

- El log de cada tool: `<tool>_ok` con recuentos, o `<tool>_failed` con el
  código de error. Ni valores, ni URLs, ni ids de estadística, ni entidades
  (CAP-011, CAP-012 de la 009).
- `ha_read_ws_command` ya registra solo comando, categoría y claves de la
  carga (011, FR-008). La 029 lo comprueba para las cuatro entradas de CAP-058
  y CAP-068 con respuestas que llevan URLs (`http://192.0.2.10:8123`,
  `https://homeassistant.tailXXXX.ts.net`) e IPs.
- Fixtures: `light.salon`, `sensor.consumo`, `homeassistant.tailXXXX.ts.net`,
  `192.0.2.x`, centinelas `centinela-029`; nada de una instalación real.
