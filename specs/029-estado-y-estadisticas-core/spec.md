# Especificación: Hermes 1.2.0 — estado del sistema y estadísticas de Core (sub-feature 029)

**Directorio de la spec**: `specs/029-estado-y-estadisticas-core`

**Creada**: 2026-11-14

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T007 de su `tasks.md` y cubre **CAP-043 y CAP-049**
con tools dedicadas y **CAP-058 y CAP-068** por la tabla de clasificación
(FR-040…FR-043 de la 008), más los transversales que le tocan (FR-010…FR-012,
FR-015, FR-018…FR-021 y FR-023 de la 008). Ola 2, tamaño M, 2 tramos. Nace de
partir la 012 en dos (plan de la 008, «Cambios respecto a research R-6»).

**Entrada**: `specs/008-cobertura-total/` (spec, plan con la matriz de
trazabilidad, research CAP-043, CAP-049, CAP-058 y CAP-068, e
`inventario/core-ws.tsv`), la sub-feature 011 (`command_table.py`,
`command_policy.py`, `tool_families.py`, `tools/generic_commands.py`, el
generador `scripts/inventario/generar_tabla.py`), el banco de la 010, la spec
de la 012 (para no pisar su frontera ni su cambio del generador), el código de
Hermes (`ha.py`, `security.py`, `tools/_annotations.py`, `tools/_common.py`,
`tools/guide.py`, `tools/statistics.py`) y el código de Home Assistant Core
2026.11.1 (`system_health`, `websocket_api/commands.py`,
`helpers/system_state.py`, `setup.py`, `loader.py`, `recorder`, `logbook`,
`network`, `http`), leídos sin ejecutar nada.

**Fuera de esta sub-feature** (otras del programa): validación de
configuración, logs, diagnósticos y notificaciones persistentes (012, CAP-040,
CAP-041, CAP-042, CAP-047); **mantenimiento** de estadísticas (borrar,
cambiar unidad, ajustar sumas, importar, `update_statistics_issues`) y energía
(020, CAP-050, CAP-054); **cambiar** la red o el HTTP de Core
(`network/configure`, `http/config/configure|promote`: 021, CAP-069); logs de
Core, del Supervisor y del host por el journal (013, CAP-081); descartar el
aviso de reinicio (`dismiss_system_state`, clase B por la 011).

## Clarificaciones

### Sesión 2026-11-14

Decisiones vinculantes de la 008 (no se discuten aquí): tools dedicadas para
CAP-043 (prioridad alta) y CAP-049 (media-alta); CAP-058 y CAP-068 por la
tabla (vía T), con tema en la guía y prueba en el banco; ninguna de las cuatro
modifica nada; tools nuevas en familias nuevas; tope de respuesta y redacción
en todo; prueba de cada tool nueva en el banco de Core.

Decisiones tomadas al especificar (no había a quién preguntar; se justifican
en [research.md](research.md)):

- P: ¿Cuántas tools y cuáles? → R: **ocho**, todas de lectura. CAP-043:
  `ha_get_system_health`, `ha_get_system_state`,
  `ha_list_integration_setup_times`, `ha_list_integration_manifests` y
  `ha_get_integration_manifest`. CAP-049: `ha_validate_statistics`,
  `ha_get_statistics_metadata` y `ha_get_recorder_info`. Research R-2 de la
  008 nombraba una sola tool para `manifest/list|get`; aquí van dos porque la
  lista completa de manifiestos no cabe en el tope y su resumen no es el
  manifiesto entero (research R-3).
- P: ¿Y `recorder/entity_options/get`? → R: entra en `ha_get_recorder_info`
  con el argumento opcional `entity_id`: es una lectura menor del recorder (si
  una entidad se graba y quién lo desactivó), de la misma clase de riesgo; la
  008 permite agrupar así (Clarificaciones de la 008, tercera decisión al
  especificar). Así no queda ningún comando «pendiente (spec 029)».
- P: ¿Cómo se lee la salud del sistema, que es una suscripción? → R: Hermes
  pide `system_health/info`, recoge el mensaje inicial y las actualizaciones
  de lo pendiente **hasta el mensaje `finish` o hasta un tope de tiempo**
  (10 s por defecto, de 1 a 30), cancela siempre la suscripción y dice qué
  quedó pendiente (`complete: false` y la lista). Hace falta un método nuevo
  del cliente: `ws_one_shot_subscription` solo coge el primer evento
  (research R-1).
- P: ¿`ha_get_statistics_metadata` sin ids? → R: no: `statistic_ids` es
  obligatorio (1–100). Sin ids, el comando de HA devuelve lo mismo que
  `ha_list_statistic_ids` de la 1.1.2; una tool «get» que lista todo
  duplicaría esa y confundiría al cliente. La respuesta dice qué ids pedidos
  no existen (`missing`).
- P: ¿Familias? → R: dos nuevas (1.2.0, desactivables): `system_status`
  (CAP-043) y `recorder` (CAP-049). Cada una con un tema de la guía del mismo
  nombre. La 020 (mantenimiento de estadísticas) podrá añadir sus módulos a
  `recorder`; lo decide ella.
- P: ¿Dónde se explican CAP-058 y CAP-068, que no tienen tool? → R: en los
  temas nuevos: la auditoría de llamadas a acciones en `recorder` (el logbook
  lee del recorder) y la red y el HTTP de Core en `system_status`, con la
  llamada exacta a `ha_read_ws_command`. La entrada de
  `logbook/get_action_calls` lleva un ejemplo de carga revisado.
- P: ¿La auditoría de acciones está bien redactada? → R: **no del todo**: la
  011 la dejó `read` diciendo que la respuesta se redacta, pero los códigos de
  alarma y cerraduras viajan en `service_data` bajo la clave `code`, que no es
  un marcador de `redact_structure`. La entrada pasa a llevar
  `redact_extra=("code",)` con un test centinela (FR-019 de la 008; research
  R-6).
- P: ¿Comandos que no existen en la versión mínima de HA (2024.10)? → R:
  `subscribe_system_state` y `recorder/entity_options/get` son recientes; con
  una HA que no los tiene, la tool responde `unsupported_by_ha_version` con
  el código de HA y la versión para la que está hecha la tabla, nunca un fallo
  de Hermes (research R-5).
- P: ¿Los manifiestos de integraciones personalizadas? → R: su texto lo
  escribe un tercero: llevan `_third_party_text` como el Marketplace.
- P: ¿Cómo se pasan los comandos a `dedicated`? → R: con el mismo mecanismo
  que la 012: las claves en `_DEDICADAS_INICIALES` del generador, que consulta
  el mapa también para la clase A antes de la regla «pendiente», y el test de
  la clase A de vía D que admite `dedicated`. Si la 012 ya lo integró, la 029
  solo añade sus claves; si no, lo hace con el mismo diseño (research R-7).

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es el administrador de Home Assistant que trabaja desde un cliente
MCP.

### Historia 1 — ¿Está sana mi instalación? (Prioridad: P1)

Quien nota algo raro quiere ver lo que enseña «Ajustes → Sistema →
Reparaciones → Información del sistema»: versión, tipo de instalación, estado
de la nube, del Supervisor, del recorder, de las integraciones que publican
salud, y si HA o el host piden un reinicio.

**Prueba independiente**: con un HA simulado que manda el mensaje inicial con
dos valores pendientes, una actualización y nunca el `finish`, la tool
responde dentro del tope de tiempo con lo recibido, marca el pendiente que no
llegó y cancela la suscripción.

**Escenarios de aceptación**:

1. **Dado** un HA cuya salud llega completa, **cuando** se pide
   `ha_get_system_health`, **entonces** devuelve cada dominio con su
   información, las fechas como texto ISO, `complete: true` y ninguna
   suscripción abierta.
2. **Dado** un valor que tarda más que el tope, **cuando** se pide,
   **entonces** la respuesta llega en el tope (con margen), dice
   `complete: false` y nombra `<dominio>.<clave>` en `pending`.
3. **Dado** un valor con un secreto (por ejemplo, un texto con
   `token=centinela`), **entonces** sale tapado y el log de Hermes no contiene
   ningún valor, ni URLs ni direcciones.
4. **Dado** un HA que pide reinicio porque se instaló una integración,
   **cuando** se pide `ha_get_system_state`, **entonces** devuelve
   `home_assistant_restart_required: true` con sus fuentes.
5. **Dado** un HA anterior al comando de estado, **entonces**
   `ha_get_system_state` responde `unsupported_by_ha_version`, no un error de
   conexión.

---

### Historia 2 — ¿Qué tarda en arrancar y qué tengo instalado? (Prioridad: P2)

Quien tiene un arranque lento quiere saber qué integraciones lo frenan; quien
investiga una integración quiere su manifiesto (versión, tipo, clase de IoT,
calidad, si es personalizada).

**Prueba independiente**: con tiempos y manifiestos simulados (uno
personalizado), las dos listas salen ordenadas, con el sobre común y
recortadas al tope; el manifiesto personalizado lleva `_third_party_text`.

**Escenarios de aceptación**:

1. **Dado** los tiempos de arranque, **cuando** se pide
   `ha_list_integration_setup_times(limit=10)`, **entonces** devuelve las 10
   más lentas de mayor a menor, `total` con cuántas hay y `truncated: true`.
2. **Dado** cientos de integraciones cargadas, **cuando** se pide
   `ha_list_integration_manifests()`, **entonces** devuelve un resumen fijo
   por integración, recortado al tope con `truncated` si no cabe.
3. **Dado** una integración que no existe, **cuando** se pide
   `ha_get_integration_manifest("no_existe")`, **entonces** responde
   `integration_not_found`, sin traza de HA.
4. **Dado** un nombre de integración inválido (mayúsculas, `/`, espacios),
   **entonces** `invalid_argument` sin llamar a HA.

---

### Historia 3 — ¿Por qué mis estadísticas están mal? (Prioridad: P1)

Quien ve un gráfico de energía roto o una estadística que dejó de crecer
quiere saber qué problemas detecta HA (unidad cambiada, entidad sin
`state_class`, entidad que ya no existe), los metadatos de esas estadísticas
y si el recorder está grabando.

**Prueba independiente**: con un resultado de validación simulado (tres
problemas en dos estadísticas), la tool lo devuelve como lista plana con el
recuento por tipo y filtra por estadística y por tipo.

**Escenarios de aceptación**:

1. **Dado** problemas de validación, **cuando** se pide
   `ha_validate_statistics()`, **entonces** devuelve
   `{count, items, truncated, by_type}` con `statistic_id`, `type` y `data`
   de cada problema, y no cambia nada en HA.
2. **Dado** dos ids pedidos y uno inexistente, **cuando** se pide
   `ha_get_statistics_metadata`, **entonces** devuelve los metadatos del que
   existe y el otro en `missing`.
3. **Dado** el recorder grabando, **cuando** se pide `ha_get_recorder_info()`,
   **entonces** devuelve si graba, si su hilo corre, la cola y si hay una
   migración en curso.
4. **Dado** una entidad excluida del recorder, **cuando** se pide
   `ha_get_recorder_info(entity_id=...)`, **entonces** dice que no se graba y
   quién lo desactivó; con una entidad que no existe, `not_found`.
5. **Dado** una HA sin el recorder cargado, **entonces** las tres responden
   `recorder_not_loaded`.

---

### Historia 4 — ¿Quién ha llamado a qué, y cómo se llega a mi HA? (Prioridad: P2)

Quien audita su casa quiere ver las acciones llamadas en un intervalo (qué
automatización o usuario abrió la cerradura); quien revisa el acceso, las URLs
interna y externa, los adaptadores de red y la configuración HTTP. Todo por
la genérica de lectura, sin tool propia.

**Prueba independiente**: con HA simulado, `ha_read_ws_command` ejecuta
`logbook/get_action_calls`, `network`, `network/url` y `http/config`; un
`code` centinela en `service_data` sale tapado, y ninguna URL ni dirección de
la respuesta aparece en el log de Hermes.

**Escenarios de aceptación**:

1. **Dado** una llamada a `alarm_control_panel.alarm_disarm` con `code`,
   **cuando** se leen las llamadas a acciones, **entonces** el código sale
   tapado y el resto de la llamada se ve.
2. **Dado** `hermes_guide(topic="recorder")`, **entonces** explica la
   auditoría con la llamada exacta y el ejemplo de la tabla; y
   `hermes_guide(topic="system_status")`, cómo leer red, URLs y HTTP.
3. **Dado** `ha_read_ws_command("network/url")`, **entonces** el log de Hermes
   lleva el comando y la categoría, nunca las URLs.

---

### Historia 5 — Nada de lo actual se rompe (Prioridad: P1)

Quien no quiere las tools nuevas las apaga; quien no cambia nada sigue
teniendo lo de antes.

**Prueba independiente**: con `tool_families_disabled: [system_status,
recorder]` la lista de tools es exactamente la de antes de la 029; los nueve
comandos siguen `dedicated` en la tabla y la genérica los rechaza diciendo que
su familia está desactivada.

**Escenarios de aceptación**:

1. **Dado** la configuración por defecto, **entonces** aparecen las ocho tools
   nuevas y todas las anteriores siguen con el mismo nombre, anotaciones y
   argumentos.
2. **Dado** `ha_read_ws_command("system_health/info")`, **entonces**
   `use_dedicated_tool` con `ha_get_system_health`, sin llegar a HA.
3. **Dado** que se regenera la tabla con el generador, **entonces** sale
   idéntica.

---

### Casos límite

- `system_health/info` sin nada pendiente: HA manda el inicial y el `finish`
  juntos; la tool responde sin esperar al tope.
- Un pendiente que falla en HA (`success: false`): se devuelve como fallido
  (`failed`), no como pendiente.
- Actualización de un dominio o clave que no venía en el inicial: se ignora y
  se cuenta en el log (no se inventa estructura).
- Respuesta de salud mayor que el tope: se quitan dominios enteros por el
  final (orden alfabético de HA), se listan en `omitted_domains` y
  `truncated: true`; con `domain=` se pide uno solo.
- WebSocket caída a mitad de la recogida: error de conexión de siempre y la
  suscripción no queda registrada en el cliente.
- `ha_validate_statistics` en una base grande: HA la ejecuta en un hilo; el
  plazo es el de `ws_send` (30 s) y un timeout se devuelve como error claro.
- `ha_get_statistics_metadata` con ids repetidos: se piden una vez; con más de
  100 o con un id sin forma `dominio.objeto` o `dominio:objeto`:
  `invalid_argument` sin llamar a HA.
- `manifest/list` con una integración que HA no puede cargar: HA la omite (y
  la registra en su log); la tool la pone en `missing` si se pidió por nombre.
- `ha_get_recorder_info(entity_id=…)` con una HA sin
  `recorder/entity_options/get`: la información del recorder sale igual y
  `entity` lleva `unsupported_by_ha_version`.
- Core caído: las ocho fallan con el error de conexión de siempre.

## Requisitos *(obligatorio)*

### Requisitos funcionales

Cada FR cita el FR y la CAP de la 008 que cumple.

#### Salud y estado del sistema (CAP-043; FR-040 de la 008)

- **FR-001**: `ha_get_system_health(domain=None, timeout_seconds=10)` lee
  `system_health/info`: el mensaje inicial y las actualizaciones de lo
  pendiente hasta `finish` o hasta `timeout_seconds` (de 1 a 30; fuera de
  rango, `invalid_argument`), y cancela siempre la suscripción. Devuelve cada
  dominio con `info` (fechas como texto ISO) y `manage_url` si HA lo da,
  `complete`, `pending` (`<dominio>.<clave>` sin valor al vencer el tope) y
  `failed` (los que HA dio por fallidos). Con `domain`, solo ese dominio; si
  no está, `domain_not_found` con los disponibles (FR-040; CAP-043).
- **FR-002**: El cliente de HA tiene un método que recoge los eventos de una
  suscripción hasta que un predicado dice que terminó o vence un plazo total,
  y cancela la suscripción en todos los casos (éxito, plazo, error de HA,
  cancelación de la tarea). `ws_one_shot_subscription` no cambia (FR-040;
  CAP-043; FR-020 de la 008). Convergencia (T038): la confirmación puede
  tener un plazo propio, y entonces el plazo total de los eventos cuenta
  desde ella; la salud lo usa (10 s) porque HA no confirma
  `system_health/info` hasta reunir la información rápida
  (`INFO_CALLBACK_TIMEOUT` = 5 s por dominio).
- **FR-003**: `ha_get_system_state()` lee `subscribe_system_state` una vez
  (primer evento, tope de 10 s) y cancela: si HA pide reinicio, sus fuentes,
  si el aviso se pospuso, y si el host pide reiniciarse (FR-040; CAP-043).
- **FR-004**: `ha_list_integration_setup_times(limit=50, min_seconds=None)`
  lee `integration/setup_info` y devuelve las integraciones ordenadas de más
  lenta a más rápida con el sobre `{count, items, truncated}`, más `total`
  (cuántas hay antes de `limit`) y `total_seconds`. `limit` de 1 a 500
  (FR-040; CAP-043).
- **FR-005**: `ha_list_integration_manifests(integrations=None,
  custom_only=False)` lee `manifest/list` (sin `integrations`, las cargadas) y
  devuelve un resumen fijo por integración (`domain`, `name`,
  `integration_type`, `iot_class`, `quality_scale`, `version`, `is_built_in`,
  `overwrites_built_in`, `config_flow`, `documentation`) ordenado por
  dominio, con el sobre común, recortado al tope, y `missing` con las pedidas
  que HA no devolvió. Hasta 100 nombres, cada uno con forma de dominio
  (FR-040; CAP-043).
- **FR-006**: `ha_get_integration_manifest(integration)` lee `manifest/get` y
  devuelve el manifiesto completo; `not_found` de HA →
  `integration_not_found`. Nombre inválido → `invalid_argument` sin llamar a
  HA (FR-040; CAP-043).
- **FR-007**: Todo manifiesto de una integración que no es de HA
  (`is_built_in: false`), en la lista y en el detalle, lleva
  `_third_party_text` con los campos de texto que escribe su autor, como el
  Marketplace (FR-018 de la 008; principio I).

#### Estadísticas: lectura y validación (CAP-049; FR-041 de la 008)

- **FR-008**: `ha_validate_statistics(statistic_id=None, issue_type=None)`
  lee `recorder/validate_statistics` y devuelve una lista plana de problemas
  (`statistic_id`, `type`, `data`) ordenada por `statistic_id`, con el sobre
  común y `by_type` (recuento por tipo antes de filtrar). No modifica nada:
  solo valida; crear o borrar los avisos de Repairs es de la 020
  (`update_statistics_issues`) (FR-041; CAP-049).
- **FR-009**: `ha_get_statistics_metadata(statistic_ids)` lee
  `recorder/get_statistics_metadata` para 1–100 ids (sin repetidos) y
  devuelve sus metadatos con el sobre común y `missing`. La descripción remite
  a `ha_list_statistic_ids` para listar todos (FR-041; CAP-049).
- **FR-010**: `ha_get_recorder_info(entity_id=None)` lee `recorder/info`
  (grabando, hilo vivo, cola y su máximo, migración en curso y si es en vivo,
  base en la ubicación por defecto) y, con `entity_id`, también
  `recorder/entity_options/get`: `entity` con `entity_id`, `recorded` y
  `recording_disabled_by`. La entidad tiene que existir (si no, `not_found`,
  sin preguntar al recorder) (FR-041; CAP-049).
- **FR-011**: Si el recorder no está cargado (HA responde que no conoce el
  comando del recorder), las tres tools de CAP-049 responden
  `recorder_not_loaded` con una explicación; la de `entity_options/get` en
  una HA que no lo tiene, `unsupported_by_ha_version` solo en `entity`
  (FR-041; CAP-049).

#### Por la tabla (CAP-058 y CAP-068; FR-042 y FR-043 de la 008)

- **FR-012**: `logbook/get_action_calls` sigue `read`, con
  `redact_extra=("code",)` (los códigos de alarmas y cerraduras de
  `service_data`) y un `example` de carga revisado contra el código de Core
  (`start_time` y `end_time` ficticios); el motivo dice la verdad sobre lo que
  se tapa. Un test centinela lo comprueba en la respuesta y en el log (FR-042;
  CAP-058; FR-019 de la 008).
- **FR-013**: `network`, `network/url` y `http/config` siguen `read`. Un test
  comprueba que el log de una llamada a cada uno por `ha_read_ws_command` no
  contiene ninguna URL, dirección IP ni host de la respuesta (FR-043;
  CAP-068; FR-008 de la 011).
- **FR-014**: La guía explica la auditoría de llamadas a acciones en el tema
  `recorder` y la red, las URLs y el HTTP de Core en el tema
  `system_status`, con la llamada exacta a `ha_read_ws_command`, lo que
  devuelven y que Hermes aún no tiene tool para cambiarlos (CAP-069, de la
  021, que actualizará ese texto) (FR-042, FR-043; CAP-058, CAP-068; FR-011
  de la 008).

#### Familias, tabla, convenciones y documentación (transversales de la 008)

- **FR-015**: Dos familias nuevas en `tool_families.py`, `desde="1.2.0"` y
  desactivables: `system_status` (el módulo de las cinco de CAP-043) y
  `recorder` (el de las tres de CAP-049). Con las dos desactivadas, la lista
  de tools es la de antes de la 029 (FR-010 de la 008; CAP-004).
- **FR-016**: Los nueve comandos de la 029 pasan de `deny` «pendiente de tool
  dedicada (spec 029)» a `dedicated` con su tool, la familia de esa tool y su
  CAP: `system_health/info`, `subscribe_system_state`,
  `integration/setup_info`, `manifest/list`, `manifest/get`, `recorder/info`,
  `recorder/entity_options/get`, `recorder/validate_statistics` y
  `recorder/get_statistics_metadata`. El generador los nombra en
  `_DEDICADAS_INICIALES` y regenerar la tabla la deja idéntica. No queda
  ninguna entrada con «(spec 029)» (FR-012 de la 008; CAP-001).
- **FR-017**: Las ocho tools son de solo lectura y lo anuncian: las de prefijo
  `ha_get_`/`ha_list_` por el prefijo; `ha_validate_statistics` por nombre
  exacto en `_READ_ONLY_EXACT`. Ninguna destructiva y, salvo
  `ha_get_system_health`, ninguna de mundo abierto (desviación de la
  convergencia, T037: `system_health/info` hace que HA salga a internet con
  `async_check_can_reach_url`, así que va en `_OPEN_WORLD` y su código es
  `R-IO`);
  ninguna pide token. Hints y títulos en `_HINTS_NUEVAS_1_2_0` (FR-018 de la
  008; principio V).
- **FR-018**: Toda respuesta pasa por `redact_structure` y `redact_secrets`
  (textos) y por el tope de respuesta: las listas, con `ajustar_lista_a_bytes`
  y `truncated`; la salud, quitando dominios enteros (`omitted_domains`); un
  manifiesto suelto que no cabe, `response_too_large`. Los errores de HA salen
  redactados (FR-018, FR-019 de la 008; principio II).
- **FR-019**: El log de las ocho lleva solo el nombre de la tool, el resultado
  y recuentos (dominios, pendientes, problemas, items); nunca valores de la
  respuesta, URLs, direcciones, ids de estadísticas ni nombres de entidades
  (FR-019, FR-021 de la 008; CAP-011).
- **FR-020**: Un comando que HA no conoce (`unknown_command`) se traduce
  según su causa real, sin decir lo que no es (principio V): si es de una
  integración que puede no estar cargada, `system_health_not_loaded`
  (`system_health/info`) o `recorder_not_loaded` (FR-011); si es de núcleo
  (`subscribe_system_state`, `integration/setup_info`, `manifest/*`, o
  `recorder/entity_options/get` con el recorder cargado),
  `unsupported_by_ha_version` con `ha_code` y la versión de HA para la que
  está hecha la tabla. Core caído, como el error de conexión de siempre
  (FR-020 de la 008; casos límite de la 008).
- **FR-021**: Cada tool tiene descripción en inglés que dice lo que hace y lo
  que no (que no modifica, de dónde salen los datos, qué recorta) y su tema en
  la guía: `system_status` y `recorder`, con alias, mencionados en el índice
  (FR-011, FR-018 de la 008).
- **FR-022**: Las ocho se ejecutan en el banco de Core contra HA 2026.11.1
  real, y las cuatro entradas `read` de CAP-058 y CAP-068 por
  `ha_read_ws_command`; un test de la suite normal impide que una tool de las
  dos familias quede sin ejecutar en el banco (FR-015 de la 008; CAP-034).
- **FR-023**: Documentación en el mismo cambio: sección propia en
  `## [1.2.0]` del CHANGELOG; estado de la 029 en la tabla del programa de
  `docs/HOJA-DE-RUTA.md`; recuento y tablas de tools en `README.md`,
  `README.es.md` y `hermes/DOCS.md` (con las dos familias en la lista de
  `tool_families_disabled`); filas CAP-043, CAP-049, CAP-058 y CAP-068 de la
  matriz de la 008 con las tools, las entradas y los ficheros de test
  definitivos (FR-023, FR-024 de la 008).

### Entidades clave

- **Informe de salud**: dominios de HA con su información, pendientes y
  fallidos, y si la recogida terminó.
- **Estado del sistema**: si HA o el host piden reinicio, sus fuentes y si el
  aviso se pospuso.
- **Tiempo de arranque**: integración y segundos.
- **Manifiesto**: descripción de una integración (resumen o completo), con la
  marca de texto de terceros si no es de HA.
- **Problema de estadística**: estadística, tipo y datos del problema.
- **Metadatos de estadística**: id, nombre, fuente, unidades, media y suma.
- **Estado del recorder**: si graba, su cola y su migración; opcionalmente,
  si una entidad se graba.

## Criterios de éxito *(obligatorio)*

- **SC-001**: Las ocho tools aparecen con la configuración por defecto; con
  las dos familias nuevas desactivadas, el conjunto de tools es exactamente
  el anterior a la 029.
- **SC-002**: Cero entradas de la tabla con «(spec 029)»; nueve `dedicated`
  hacia tools registradas; regenerar la tabla no cambia ni un byte.
- **SC-003**: El 100 % de las ocho tools y de las cuatro entradas `read` de
  CAP-058 y CAP-068 se ha ejecutado en el banco contra HA Core 2026.11.1 real.
- **SC-004**: En los tests, ningún valor centinela (secreto en la salud,
  `code` en las llamadas a acciones, secreto en un manifiesto o en un error de
  HA) aparece en respuestas, errores ni log.
- **SC-005**: Con una salud que nunca termina, `ha_get_system_health`
  responde en menos de `timeout_seconds` + 2 s y, en el 100 % de los caminos
  probados (fin, plazo, error, caída), la suscripción se cancela.
- **SC-006**: Ninguna URL, IP ni host de las respuestas de salud, red o HTTP
  aparece en el log capturado en los tests.
- **SC-007**: Suite completa con solo los 6 fallos conocidos en Windows y CI
  (tests, banco de Core, Semgrep y CodeQL) en verde al cerrar cada tramo.

## Supuestos

- La implementación empieza con la 011 completa (sus tres tramos), la 009
  (versión 1.2.0 y entrada del CHANGELOG) y el banco de la 010 integrados en
  la rama. Al especificar, la rama tiene la 011 hasta T037 (sin el extractor
  ni su documentación) y ni la 009 ni la 010.
- El banco carga `recorder:`, `logbook:`, `system_health:` y `network:` en su
  configuración; si alguno no arranca sin red en el contenedor, la tarea del
  banco lo anota y su prueba queda en unitarios con el motivo.
- Las fechas de aparición exactas de `subscribe_system_state` y
  `recorder/entity_options/get` no se pueden fijar con el código leído; por eso
  la tool responde al `unknown_command` en vez de comprobar la versión antes.

## Dudas para el final

- **D-1**: ¿Un `ha_get_system_health` resumido (solo versión, tipo de
  instalación y lo que falla) por defecto, con el informe completo bajo un
  argumento? Hoy devuelve todo (es lo que enseña la interfaz).
- **D-2**: Si la 020 debe añadir sus tools de mantenimiento a la familia
  `recorder` o crear la suya (afecta al tema de la guía y a quien desactive
  `recorder` pensando que solo lee).
- **D-3**: La 012 y la 029 tocan el mismo mapa del generador y el mismo test
  de la clase A: la segunda que se integre resuelve el conflicto conservando
  las claves de las dos.
