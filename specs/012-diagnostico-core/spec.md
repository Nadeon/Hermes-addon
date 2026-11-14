# Especificación: Hermes 1.2.0 — diagnóstico de Core (sub-feature 012)

**Directorio de la spec**: `specs/012-diagnostico-core`

**Creada**: 2026-11-14

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T006 de su `tasks.md` y cubre **CAP-040, CAP-041,
CAP-042 y CAP-047** (FR-036…FR-039 de la 008), más los transversales que le
tocan (FR-010…FR-012, FR-015, FR-018…FR-021 y FR-023 de la 008). Ola 2,
tamaño M, 2 tramos.

**Entrada**: `specs/008-cobertura-total/` (spec, plan con la matriz de
trazabilidad, research CAP-040…CAP-047 e `inventario/core-ws.tsv`), la
sub-feature 011 (tabla `command_table.py`, `command_policy.py`,
`tool_families.py`, generador `scripts/inventario/generar_tabla.py`), el banco
de la 010 y su regla de inventario de escrituras (028), el código de Hermes
(`security.py`, `tools/_annotations.py`, `tools/_common.py`, `tools/guide.py`,
`tools/repairs.py`, `tools/addons.py`, `ha.py`) y el código de Home Assistant
Core 2026.11.1 (`logger`, `system_log`, `api`, `diagnostics`,
`persistent_notification`, `websocket_api/commands.py`, `bootstrap.py`) y del
Supervisor 2026.11.0, leídos sin ejecutar nada.

**Fuera de esta sub-feature** (otras del programa): salud y estado del sistema,
tiempos de arranque, manifiestos, estadísticas y recorder (029, CAP-043 y
CAP-049); logs de Core, del Supervisor y del host por el journal del Supervisor
(013, CAP-081); validar al guardar una automatización o un script (017,
FR-062 de la 008, que se apoya en lo de aquí).

## Clarificaciones

### Sesión 2026-11-14

Decisiones vinculantes de la 008 (no se discuten aquí): tools dedicadas para
las cuatro CAP (vía D; CAP-040 es D+X y su parte X es de la 017); dos pasos
para fijar el nivel de log, limpiar el log del sistema y descartar una
notificación; redacción de Hermes y tope de respuesta además de los de HA; las
tools nuevas en familias nuevas; prueba en el banco de Core.

Decisiones tomadas al especificar (no había a quién preguntar; se justifican
en [research.md](research.md)):

- P: ¿Qué hace `ha_get_error_log` en una instalación con Supervisor, donde HA
  no escribe fichero de log salvo que se active `duplicate_log_file` en las
  opciones de Core? → R: lo dice. HA solo registra `/api/error_log` cuando hay
  fichero; sin él responde 404 y la tool devuelve `error_log_unavailable` con
  la explicación (no hay fichero; cómo activarlo; el log de Core se lee por el
  Supervisor). **No** cae al journal del Supervisor: eso es la tool de logs de
  Core de la 013 (CAP-081), y leerlo aquí sería invadirla. Queda como duda para
  el final si conviene la caída automática cuando exista la de la 013
  (research R-2).
- P: ¿`logger/log_level` lee o escribe? → R: **escribe** (fija el nivel de un
  módulo; el inventario de la 008 lo agrupaba con las lecturas). La lectura es
  `logger/log_info`. `ha_set_log_level` usa `logger/integration_log_level`
  (por integración) o `logger/log_level` (por módulo, es decir, un logger de
  Python cualquiera) según el argumento, y los dos pasan a `dedicated`
  (research R-3).
- P: ¿Qué es el «nivel anterior» de la vista previa? → R: para una
  integración, el nivel efectivo que da `logger/log_info`; para un módulo, HA
  no lo expone por ninguna API y la vista previa lo dice
  (`previous_level: null` con el motivo) en vez de inventarlo (principio V).
- P: ¿Persistencia del nivel? → R: argumento `persistence` con los tres
  valores de HA (`none`, `once`, `permanent`), por defecto `none` (hasta el
  próximo reinicio, lo menos sorprendente); `NOTSET` quita el ajuste guardado.
  La vista previa explica el valor elegido.
- P: ¿Cómo se descarta una notificación? → R: con la acción
  `persistent_notification.dismiss` de HA (no hay comando WS de descarte). Una
  sola notificación por llamada; `dismiss_all` sigue disponible por
  `ha_call_service` con su token de siempre (denylist).
- P: ¿Qué devuelven los diagnósticos? → R: por defecto, `data` y `issues` del
  fichero que descarga HA; la información del sistema (`home_assistant`,
  `custom_components`, `integration_manifest`, `setup_times`) solo con
  `include_system_info=true` (es grande y es terreno de la 029). Si no cabe, el
  error lista las claves de primer nivel de `data` con su tamaño y el
  argumento `keys` permite pedir solo algunas.
- P: ¿Diagnóstico de dispositivo sin decir la integración? → R: sí: Hermes
  toma la integración dueña del dispositivo (`config_entry_id` del registro de
  dispositivos, la misma regla que aplica HA al servir el fichero).
- P: ¿Validar «una automatización o un script»? → R: `ha_validate_config`
  acepta las tres partes (`triggers`, `conditions`, `actions`) o una
  configuración entera (`config`) de la que Hermes toma esas partes (también
  las formas en singular y `sequence` de un script). La respuesta dice qué
  claves NO se validaron (`alias`, `mode`…): HA solo valida esas tres.
- P: ¿Familia? → R: una nueva, `core_diagnostics` (1.2.0, desactivable), con
  los cuatro módulos de la sub-feature y un tema de la guía con el mismo nombre.
- P: ¿Textos de terceros? → R: el mensaje de una notificación y de una entrada
  del log del sistema los puede escribir cualquier integración, automatización
  o dispositivo; se marcan con `_third_party_text` como en el Marketplace.

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es el administrador de Home Assistant que trabaja desde un cliente
MCP.

### Historia 1 — Saber qué está fallando (Prioridad: P1)

Quien ve que algo no funciona quiere leer lo que HA ha registrado sin abrir la
interfaz: los errores agrupados del log del sistema y, si hace falta, las
últimas líneas del log.

**Prueba independiente**: con un HA simulado que devuelve entradas de
`system_log/list` (una con un centinela de secreto), la tool las devuelve
agrupadas, ordenadas, recortadas al tope y con el centinela tapado.

**Escenarios de aceptación**:

1. **Dado** un log del sistema con entradas de varios niveles, **cuando** el
   agente llama a `ha_list_system_log`, **entonces** recibe cada entrada con su
   nivel, logger, mensaje, origen, número de apariciones y primera y última
   vez, la más reciente primero.
2. **Dado** `level="ERROR"` o `integration="mqtt"`, **cuando** lista,
   **entonces** solo recibe las entradas de ese nivel o de esa integración.
3. **Dado** una entrada con traza, **cuando** lista sin
   `include_tracebacks`, **entonces** ve solo la última línea de la traza; con
   `include_tracebacks=true`, la traza entera, redactada.
4. **Dado** una instalación con fichero de log, **cuando** pide
   `ha_get_error_log(lines=200)`, **entonces** recibe las últimas 200 líneas (o
   las últimas que quepan, dicho), redactadas.
5. **Dado** una instalación con Supervisor sin `duplicate_log_file`, **cuando**
   pide el log de errores, **entonces** recibe `error_log_unavailable` con la
   explicación, no un error opaco.

### Historia 2 — Probar antes de guardar (Prioridad: P1)

Quien escribe una automatización quiere saber si sus triggers, condiciones y
acciones son válidos, y qué daría una condición ahora mismo, sin guardar nada.

**Prueba independiente**: con HA simulado, `ha_validate_config` envía un solo
`validate_config` con las partes pedidas y devuelve el resultado por parte;
`ha_test_condition` envía un `test_condition` y devuelve `result`.

**Escenarios de aceptación**:

1. **Dado** una configuración de automatización con un trigger inválido,
   **cuando** la valida, **entonces** recibe `triggers: valid=false` con el
   error de HA y las otras partes válidas, y nada se guarda.
2. **Dado** un script con `sequence`, **cuando** lo valida con `config`,
   **entonces** las acciones se validan como `actions` y la respuesta lista las
   claves que no se validaron.
3. **Dado** una condición de estado sobre una entidad, **cuando** la prueba,
   **entonces** recibe `true` o `false` y, si una plantilla falló, sus errores.
4. **Dado** una condición mal formada, **cuando** la prueba, **entonces**
   recibe `invalid_condition` con el mensaje de HA redactado.

### Historia 3 — Depurar una integración (Prioridad: P2)

Quien persigue un fallo de una integración quiere ver y subir su nivel de log
y descargar sus diagnósticos, sabiendo qué cambia.

**Prueba independiente**: con HA simulado, `ha_set_log_level` sin token
devuelve una vista previa con el nivel anterior y no envía nada; con el token,
envía un solo comando.

**Escenarios de aceptación**:

1. **Dado** las integraciones cargadas, **cuando** pide
   `ha_get_log_levels`, **entonces** recibe cada una con su nivel efectivo por
   nombre y número.
2. **Dado** `ha_set_log_level(level="debug", integration="mqtt")` sin token,
   **cuando** se llama, **entonces** recibe una vista previa con el nivel
   anterior, el nuevo, qué significa la persistencia elegida y un token, y HA
   no recibe nada; **cuando** repite con el token, HA recibe
   `logger/integration_log_level` una vez.
3. **Dado** un módulo (`module="homeassistant.core"`), **cuando** pide la
   vista previa, **entonces** `previous_level` es `null` con el motivo.
4. **Dado** una integración con diagnóstico de entrada, **cuando** pide
   `ha_get_config_entry_diagnostics(entry_id)`, **entonces** recibe `data` e
   `issues` redactados por HA y por Hermes; si no caben, un error con las
   claves de `data` y su tamaño.
5. **Dado** un dispositivo de una integración con diagnóstico de dispositivo,
   **cuando** pide `ha_get_device_diagnostics(device_id)`, **entonces** Hermes
   localiza la integración dueña y devuelve el diagnóstico; si la integración
   no lo ofrece, `diagnostics_not_supported` sin llamar a la descarga.
6. **Dado** `ha_list_diagnostics_handlers`, **cuando** se llama, **entonces**
   lista qué integraciones ofrecen diagnóstico de entrada y de dispositivo.

### Historia 4 — Ordenar avisos y log (Prioridad: P2)

Quien tiene notificaciones persistentes acumuladas o un log del sistema lleno
de ruido ya resuelto quiere verlas y quitarlas, sabiendo exactamente qué quita.

**Prueba independiente**: con HA simulado, `ha_dismiss_persistent_notification`
sin token devuelve una vista previa con el título y el texto y no llama a la
acción; con el token, la llama una vez.

**Escenarios de aceptación**:

1. **Dado** notificaciones activas, **cuando** las lista, **entonces** recibe
   id, título, mensaje y fecha de cada una, marcadas como texto de terceros.
2. **Dado** una notificación, **cuando** pide descartarla sin token,
   **entonces** la vista previa enseña su título y su mensaje (redactados) y
   da un token; con el token, la notificación desaparece.
3. **Dado** un id que no existe, **cuando** pide descartarlo, **entonces**
   recibe `not_found` sin token.
4. **Dado** un log del sistema con entradas, **cuando** pide
   `ha_clear_system_log` sin token, **entonces** la vista previa dice cuántas
   entradas hay por nivel y que no toca el fichero ni el journal; con el token,
   el log queda vacío. Con el log ya vacío, `unchanged` sin token.

### Historia 5 — Nada se rompe ni se salta una protección (Prioridad: P1)

Quien usa Hermes hoy quiere que estas tools no cambien nada de lo que ya
funciona, ni abran un camino alrededor de la denylist o de la tabla.

**Prueba independiente**: tests de registro, de la tabla y de anotaciones.

**Escenarios de aceptación**:

1. **Dado** la configuración por defecto, **cuando** arranca, **entonces** las
   tools de antes siguen con los mismos nombres, anotaciones y argumentos, y
   aparecen las 12 nuevas en la familia `core_diagnostics`.
2. **Dado** `tool_families_disabled: [core_diagnostics]`, **cuando** arranca,
   **entonces** las 12 no se registran y sus comandos siguen `dedicated` en la
   tabla (la genérica los rechaza con `family_disabled`).
3. **Dado** `ha_call_service("logger", "set_level", …)` o
   `("system_log", "clear")`, **cuando** se llama, **entonces** sigue pidiendo
   token como en la 1.1.2.
4. **Dado** la genérica de lectura con `system_log/list`, **cuando** se llama,
   **entonces** recibe `use_dedicated_tool` con `ha_list_system_log`.

### Casos límite

- `system_log` no cargado (configuración sin `default_config` ni
  `system_log:`): HA responde `unknown_command`; la tool devuelve
  `system_log_unavailable` con el código de HA.
- `diagnostics` no cargado: `unknown_command` → `diagnostics_unavailable`.
- Entrada inexistente o de una integración sin diagnóstico de entrada:
  `not_found` o `diagnostics_not_supported` sin pedir la descarga.
- Dispositivo sin `config_entry_id` (compuesto o huérfano):
  `diagnostics_not_supported` con el motivo.
- Diagnóstico que no cabe ni pidiendo una sola clave: `response_too_large`
  con los tamaños; nunca un JSON cortado.
- Log de errores enorme (cientos de MB): se lee en flujo y solo se conservan
  las últimas líneas pedidas; `lines` fuera de [1, 1000] se acota.
- `ha_set_log_level` con nivel desconocido, con las dos o ninguna de
  `integration`/`module`, o con `persistence` desconocida: `invalid_argument`
  sin token. Integración que HA no conoce: HA responde `not_found` al
  confirmar y la tool lo dice.
- Token de `ha_set_log_level` usado con otro nivel, otro objetivo u otra
  persistencia: rechazado.
- La notificación desaparece entre la vista previa y la confirmación: la
  acción de HA no falla; la respuesta dice `already_dismissed`.
- Entradas nuevas del log entre la vista previa de la limpieza y la
  confirmación: también se borran, y la vista previa lo avisa.
- `ha_validate_config` sin ninguna parte, o con `config` y partes a la vez:
  `invalid_argument`.
- Condición que evalúa plantillas con variables que faltan: `result` y
  `template_errors`, no un error.
- Core caído: el error de conexión de siempre.

## Requisitos *(obligatorio)*

Cada requisito cita entre paréntesis el FR y la CAP de la 008 que cumple.

### Requisitos funcionales

#### Validación (FR-036 de la 008, CAP-040)

- **FR-001**: `ha_validate_config` valida `triggers`, `conditions` y
  `actions` con el comando `validate_config` de HA, o las toma de una
  configuración entera (`config`: `triggers`/`trigger`, `conditions`/
  `condition`, `actions`/`action` o `sequence`), sin guardar nada. Devuelve
  por parte `valid` y `error` (redactado), y en `not_validated` las claves de
  `config` que HA no valida. Sin ninguna parte, o con `config` y partes a la
  vez: `invalid_argument` sin llamar a HA. Solo lectura (FR-036, CAP-040).
- **FR-002**: `ha_test_condition` evalúa una condición contra el estado actual
  con `test_condition` (y `variables` opcionales) y devuelve `result` y, si
  los hay, `template_errors`. Una condición inválida devuelve
  `invalid_condition` con el mensaje de HA redactado. Solo lectura (FR-036,
  CAP-040).

#### Log del sistema y niveles (FR-037 de la 008, CAP-041)

- **FR-003**: `ha_list_system_log` devuelve las entradas agrupadas de
  `system_log/list` (nivel, logger, mensaje, origen, número de apariciones,
  primera y última vez en ISO 8601), la más reciente primero, con filtros
  opcionales `level` e `integration`; la traza solo en su última línea salvo
  `include_tracebacks=true`. Mensajes y trazas redactados y marcados como texto
  de terceros; sobre `{count, items, truncated}` ajustado al tope (FR-037,
  CAP-041).
- **FR-004**: `ha_get_error_log` devuelve las últimas `lines` líneas (por
  defecto 100, acotado a [1, 1000]) del log de HA (`/api/error_log`),
  redactadas, leyendo en flujo sin guardar más que esas líneas, y las últimas
  que quepan en el tope con `truncated` si no caben. Sin fichero de log (404),
  `error_log_unavailable` con la explicación de research R-2 (FR-037,
  CAP-041).
- **FR-005**: `ha_get_log_levels` devuelve el nivel efectivo de cada
  integración cargada (`logger/log_info`) por nombre y número, ordenado por
  dominio, con filtro opcional `domain`; sobre común (FR-037, CAP-041).
- **FR-006**: `ha_set_log_level` fija el nivel de una integración
  (`logger/integration_log_level`) o de un módulo (`logger/log_level`) en dos
  pasos. Argumentos: `level` (DEBUG, INFO, WARNING, ERROR, CRITICAL o NOTSET,
  sin distinguir mayúsculas), exactamente uno de `integration` y `module`, y
  `persistence` (`none` por defecto, `once`, `permanent`). La vista previa
  tiene el objetivo, el nivel anterior (el efectivo para una integración;
  `null` con motivo para un módulo), el nuevo y qué significa la persistencia;
  el token se ata a los cuatro argumentos (FR-037, CAP-041).
- **FR-007**: `ha_clear_system_log` vacía el log del sistema (acción
  `system_log.clear`) en dos pasos. La vista previa da el número de entradas y
  su reparto por nivel, y dice que no toca el fichero de log ni el journal y
  que lo que se registre antes de confirmar también se borra. Con el log vacío,
  `unchanged` sin token (FR-037, CAP-041).

#### Diagnósticos (FR-038 de la 008, CAP-042)

- **FR-008**: `ha_list_diagnostics_handlers` lista las integraciones que
  ofrecen diagnóstico y de qué tipo (entrada, dispositivo), con `domain`
  opcional para una sola (`diagnostics/list` o `diagnostics/get`); sobre común
  (FR-038, CAP-042).
- **FR-009**: `ha_get_config_entry_diagnostics` devuelve el diagnóstico de una
  entrada (`/api/diagnostics/config_entry/{entry_id}`): `data` e `issues`, y
  la información del sistema solo con `include_system_info=true`. Antes de
  descargar comprueba que la entrada existe y que su integración ofrece ese
  diagnóstico. Redacción de Hermes sobre la de HA (por clave y por patrón).
  Con `keys`, solo esas claves de primer nivel de `data`. Si no cabe,
  `response_too_large` con las claves de `data` y su tamaño, sin cortar el
  JSON (FR-038, CAP-042).
- **FR-010**: `ha_get_device_diagnostics` hace lo mismo para un dispositivo
  (`/api/diagnostics/config_entry/{entry_id}/device/{device_id}`), con la
  entrada dueña tomada del registro de dispositivos (`config_entry_id`). Sin
  dueña única, o sin diagnóstico de dispositivo en esa integración,
  `diagnostics_not_supported` sin descargar (FR-038, CAP-042).

#### Notificaciones persistentes (FR-039 de la 008, CAP-047)

- **FR-011**: `ha_list_persistent_notifications` devuelve las notificaciones
  activas (`persistent_notification/get`): id, título, mensaje y fecha de
  creación, redactados y marcados como texto de terceros, la más reciente
  primero; sobre común (FR-039, CAP-047).
- **FR-012**: `ha_dismiss_persistent_notification` descarta una notificación
  (acción `persistent_notification.dismiss`) en dos pasos. La vista previa
  enseña su título y su mensaje redactados (el mensaje recortado si es muy
  largo, dicho). Id inexistente: `not_found` sin token. Si ya no existe al
  confirmar: `already_dismissed` (FR-039, CAP-047).

#### Familia, tabla, convenciones y documentación (transversales de la 008)

- **FR-013**: Las 12 tools van en una familia nueva `core_diagnostics`
  (`desde="1.2.0"`, desactivable) con los módulos `core_logs`,
  `core_validation`, `integration_diagnostics` y `persistent_notifications`.
  Con la familia desactivada no se registra ninguna; con las familias de la
  1.2.0 desactivadas, la lista sigue siendo la de la 1.1.2 (FR-010 de la 008,
  CAP-004).
- **FR-014**: En `command_table.py` pasan a `dedicated`, en el mismo cambio que
  su tool y con la familia `core_diagnostics`: `validate_config` y
  `test_condition` (CAP-040), `system_log/list`, `logger/log_info`,
  `logger/log_level` y `logger/integration_log_level` (CAP-041),
  `diagnostics/list` y `diagnostics/get` (CAP-042) y
  `persistent_notification/get` (CAP-047). El mapa del generador
  (`_DEDICADAS_INICIALES`) los nombra y regenerar la tabla la deja idéntica.
  El test que exige «pendiente de tool dedicada» para la clase A de vía D
  admite `dedicated` hacia una tool que existe (FR-012 de la 008, CAP-001).
- **FR-015**: Anotaciones por nombre exacto en `tools/_annotations.py`:
  `ha_validate_config` y `ha_test_condition` de solo lectura (no tienen
  prefijo de lectura); `ha_set_log_level`, `ha_clear_system_log` y
  `ha_dismiss_persistent_notification` destructivas (piden token y ocultan
  rastro: misma razón que las tienen en la denylist); ninguna de mundo
  abierto; títulos legibles (FR-018 de la 008).
- **FR-016**: `hermes_guide` tiene el tema `core_diagnostics` (con alias
  `logs`, `log`, `notifications`, `validation`) que explica cuándo usar cada
  tool, el caso del log sin fichero, la persistencia de los niveles y la
  receta «¿por qué falla esta integración?» (FR-011 de la 008).
- **FR-017**: Ningún secreto que llegue en mensajes del log, trazas, líneas del
  log de errores, diagnósticos, errores de HA o notificaciones aparece en una
  respuesta, una vista previa, un error o el log de Hermes; el log de Hermes
  de estas tools lleva recuentos, niveles y objetivos, nunca mensajes, líneas
  ni datos de diagnóstico. Test con centinela por tool (FR-019 de la 008,
  principio II).
- **FR-018**: Toda respuesta de lista usa el sobre `{count, items, truncated}`
  ajustado a `response_max_bytes`; las vistas previas caben en el tope (FR-018
  de la 008, CAP-023).
- **FR-019**: Las tres tools que modifican se ejecutan en el banco de Core
  contra HA 2026.11.1 real, con el efecto comprobado por el lector, y están en
  la lista de probadas de la sub-feature (`tests/banco/cobertura_012.py`)
  sumada al invariante de escrituras; las de lectura también se ejecutan en el
  banco. Lo que no se puede ejecutar ahí queda con su motivo (FR-015 de la
  008, CAP-034).
- **FR-020**: Nada de lo actual cambia: las tools existentes, sus argumentos y
  anotaciones, la denylist (`logger.set_level`, `system_log.clear` y
  `persistent_notification.dismiss*` siguen pidiendo token por
  `ha_call_service`) y la tabla fuera de las nueve entradas de FR-014 (FR-020
  de la 008).
- **FR-021**: Documentación en el mismo cambio: sección propia en
  `## [1.2.0]` de `hermes/CHANGELOG.md`; estado de la 012 en la tabla del
  programa de `docs/HOJA-DE-RUTA.md`; tools nuevas en `README.md` y
  `README.es.md` sincronizados; familia en `hermes/DOCS.md` si la opción de
  familias las enumera; filas CAP-040, CAP-041, CAP-042 y CAP-047 de la matriz
  de `specs/008-cobertura-total/plan.md` con las tools y los tests (FR-023 de
  la 008).
- **FR-022**: Tests, fixtures y documentación solo con marcadores genéricos
  (`light.salon`, `<entry_id>`, centinelas de texto); ningún dato de una
  instalación ni identificador de modelo (FR-021 de la 008, principio VIII).

### Entidades clave

- **Entrada del log del sistema**: grupo de mensajes iguales de un logger, con
  nivel, origen (fichero y línea), mensajes (hasta 5 distintos), traza,
  apariciones y primera y última vez. HA guarda 50 por defecto.
- **Nivel de log**: por integración (todos sus loggers) o por módulo (un
  logger), con persistencia `none`, `once` o `permanent`; `NOTSET` lo quita.
- **Diagnóstico**: documento JSON que la integración genera y redacta, servido
  por HA con información del sistema; de entrada o de dispositivo.
- **Notificación persistente**: id, título, mensaje y fecha; vive en memoria
  de HA hasta que se descarta o HA se reinicia.

## Fuera de alcance

- Salud y estado del sistema, tiempos de arranque, manifiestos, recorder y
  estadísticas (029).
- Logs del journal del Supervisor (de Core, del Supervisor, del host y de los
  plugins) y la caída de `ha_get_error_log` a ellos (013; duda D-1).
- Validar al guardar automatizaciones y scripts (017, FR-062 de la 008).
- Crear notificaciones (ya se puede con `ha_call_service`), descartar todas de
  una vez (sigue por `ha_call_service` con token) y escribir en el log
  (`system_log.write`, igual).
- Fijar el nivel por defecto (`logger.set_default_level`): no está en ninguna
  CAP; sigue por `ha_call_service` (duda D-3).
- Suscripciones (`system_log/subscribe_raw`, `persistent_notification/subscribe`,
  `subscribe_condition`): clase B, `deny`.

## Supuestos

- **S-01**: Antes del tramo A la rama tiene integradas la 009 (redacción
  lineal, CAP-010, y la entrada `## [1.2.0]`), la 010 (banco) y la 011 entera
  (genéricas, opción de familias y registro por familias). Si la 010 no lo
  está, las tareas del banco quedan pendientes con una nota en el commit y en
  la hoja de ruta, y el tramo sigue.
- **S-02**: Si la 028 está integrada, su invariante de escrituras suma la lista
  de la 012; si no, la 012 trae su propio test del invariante para sus tres
  tools y la unión se hace al integrar.
- **S-03**: En el banco hay al menos una integración sin red con diagnóstico de
  entrada que se pueda crear por su flujo (research R-8); el diagnóstico de
  dispositivo solo se puede probar ahí en su camino de error (ninguna
  integración sin hardware lo ofrece), y su camino feliz queda en unitarios y
  como pendiente manual en la matriz de la 014.
- **S-04**: HA 2026.11.1 es la referencia; las formas de respuesta están en
  research con el fichero de HA de donde salen.

## Criterios de éxito *(obligatorio)*

- **SC-001**: Con la configuración por defecto se registran las 12 tools
  nuevas y las de antes siguen idénticas (nombres, anotaciones, esquemas).
- **SC-002**: Las nueve entradas de FR-014 son `dedicated` hacia una tool
  registrada de `core_diagnostics`, y regenerar la tabla no cambia ni un byte.
- **SC-003**: El 100 % de las llamadas sin token a las tres tools que
  modifican no envían nada a HA; un token no sirve con otros argumentos.
- **SC-004**: Ningún centinela de secreto aparece en respuestas, vistas
  previas, errores, log de Hermes ni ficheros de token de estas tools.
- **SC-005**: Las tres tools que modifican pasan en el banco con el efecto
  comprobado por el lector, y las de lectura devuelven datos reales.
- **SC-006**: Cada FR tiene su test, y cada comportamiento con riesgo, su
  control negativo anotado.
- **SC-007**: La suite pasa en el CI de Linux al final de cada tramo, con
  exactamente los 6 fallos conocidos de Windows en local.
