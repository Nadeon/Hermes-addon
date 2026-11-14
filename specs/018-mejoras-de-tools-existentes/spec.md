# Especificación: Hermes 1.2.0 — mejoras de tools existentes (sub-feature 018)

**Directorio de la spec**: `specs/018-mejoras-de-tools-existentes`

**Creada**: 2026-11-14

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T011 de su `tasks.md` y cubre **CAP-019, CAP-020 y
CAP-023** (FR-063, FR-064 y FR-065 de la 008, y la parte de CAP-023 de
FR-018). Depende de la 011 (tabla, familias y genéricas) y la 023 (Assist y
conversación) depende de ella por CAP-020.

**Entrada**: la 008 (spec, plan con la matriz de trazabilidad, research
R-0 punto 2 y el catálogo de CAP) y el código de la rama de la 011 completa:
`tools/lovelace.py` (`ha_get_lovelace_dashboard` con `view_index` y
`top_level`; `ha_save_lovelace_dashboard` con el documento guardado junto al
token de la 1.1.2 y la protección `top_level_keys_missing`), `security.py`
(`create_confirmation_token`, `resolve_confirmation_token` con omitibles),
`tools/ha.py` (`ha_call_service`, `ha_call_service_response`),
`service_policy.py` (denylist y entidades restringidas), `tools/_common.py`
(tope de respuesta) y `tools/generic_commands.py` (el único sobre de lista de
la 1.2.0 hasta hoy). Código de HA consultado: `components/lovelace/websocket.py`
y `components/conversation/services.py` de Core 2026.11.1.

## Clarificaciones

### Sesión 2026-11-14

Decisiones vinculantes (de la 008 y del supervisor del programa):

- **Nada de lo que existe se rompe** (FR-020 de la 008): las 216 tools de la
  1.1.2 conservan nombre, anotaciones, argumentos, respuestas y comportamiento
  por defecto. Un argumento nuevo es opcional y su valor por defecto reproduce
  la 1.1.2. Lo comprueban la instantánea de esquemas
  `tests/fixtures/esquemas_1_1_2.json` y la de anotaciones.
- **Las tools existentes no cambian la forma de sus listas en la 1.2.0**
  (clarificación de la 008 y su duda D-07): el sobre común
  `{count, items, truncated}` es solo para las tools nuevas.
- La 018 no añade tools nuevas (fila de la 018 en el plan de la 008: 0 tools)
  ni familias, ni pasa ninguna entrada de la tabla a `dedicated`.

Decisiones tomadas al especificar (no había a quién preguntar; se justifican en
[research.md](research.md)):

- P: ¿Cómo se pide guardar una sola vista? → R: con dos argumentos opcionales
  nuevos de `ha_save_lovelace_dashboard`, **`view_index`** (el mismo índice
  0-based que `ha_get_lovelace_dashboard`) y **`view`** (el objeto de la
  vista). `config` conserva su significado (el dashboard entero) y no se mezcla
  con `view` (R-1).
- P: ¿Qué pasa si el dashboard cambia entre la vista previa y la
  confirmación? → R: **se rechaza** (`dashboard_changed`) y no se guarda nada.
  La vista previa promete conservar las demás vistas «como están ahora»; si
  otra cosa las cambió, guardar sería cumplir una promesa distinta de la
  previsualizada (principio IV). El token queda atado también al estado del
  dashboard que se leyó en la vista previa (R-2).
- P: ¿`ha_call_service_response` sin token ante una acción de la denylist
  sigue devolviendo el error de la 1.1.2? → R: **sí, y además** trae la vista
  previa y el token (cambio aditivo). Un cliente que solo mira `error` sigue
  viendo un rechazo, exactamente como en la 1.1.2 (fail-closed); uno que lea
  los campos nuevos puede confirmar (R-3). Quitar `error` de esa respuesta
  queda como duda para el final.
- P: ¿Solo la denylist o también las entidades restringidas
  (`entity_restricted`)? → R: **las dos**, con el mismo criterio que
  `ha_call_service` («misma vista previa que `ha_call_service`», FR-064 de la
  008): si no, un script restringido con respuesta seguiría sin poder
  devolverla aunque se confirme (R-3).
- P: ¿Cómo se verifica el sobre común «en las tools nuevas» si la 018 no crea
  ninguna? → R: con un **constructor compartido** del sobre en
  `tools/_common.py` y un **test transversal** que recorre las tools
  registradas que no están en la instantánea de la 1.1.2: toda `ha_list_*` o
  `sv_list_*` nueva tiene que construir su respuesta con él o figurar en una
  lista de excepciones con su motivo. Así vale para las tools que añadan las
  demás sub-features, antes o después de la 018 (R-4).

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es un administrador de Home Assistant que trabaja con un cliente
MCP (un asistente basado en un modelo de lenguaje).

### Historia de usuario 1 — Cambiar una vista de un dashboard grande sin reescribirlo entero (Prioridad: P1)

El usuario pide cambiar unas tarjetas de una vista de un dashboard que no cabe
en una respuesta (134 KB en la prueba en vivo de la 1.1.2). Hoy el cliente
tiene que leerlo por vistas y reconstruir el documento entero para guardarlo;
en la prueba en vivo se dejó tarjetas por el camino (la vista previa lo
enseñó, pero el riesgo es real). Con esta mejora el cliente lee la vista, la
modifica y guarda solo esa vista: el servidor conserva el resto.

**Por qué esta prioridad**: es la única CAP de prioridad alta de la 018 y la
que evita pérdidas de datos del usuario (tarjetas borradas sin querer).

**Prueba independiente**: con un dashboard de tres vistas y claves de nivel
superior, guardar la vista 1 en dos pasos y comprobar que la vista 1 es la
nueva y que las vistas 0 y 2 y las claves de nivel superior son idénticas a
las de antes.

**Escenarios de aceptación**:

1. **Dado** un dashboard con vistas 0, 1 y 2 y `title`, **cuando** el cliente
   llama a `ha_save_lovelace_dashboard` con `view_index=1` y `view`, **entonces**
   recibe una vista previa que dice qué vista cambia (índice, título, ruta,
   tarjetas antes y después), qué vistas se conservan y qué claves de nivel
   superior se conservan, y un `confirmation_token`; Home Assistant no cambia.
2. **Dado** esa vista previa, **cuando** confirma con `url_path`, `view_index`
   y el token (sin reenviar `view`), **entonces** el dashboard guardado tiene la
   vista 1 nueva y lo demás exactamente igual.
3. **Dado** una vista previa por vista, **cuando** otro cliente modifica
   cualquier parte del dashboard antes de confirmar, **entonces** la
   confirmación se rechaza con `dashboard_changed` y no se guarda nada.
4. **Dado** `view_index` fuera de rango, un dashboard de estrategia (sin
   `views`) o en modo YAML, **cuando** se pide la vista previa, **entonces**
   se devuelve un error que dice cuál (`view_index_out_of_range`, `no_views`,
   `yaml_mode`) sin token.
5. **Dado** una llamada sin `view_index` ni `view`, **cuando** se guarda el
   dashboard entero, **entonces** el comportamiento es el de la 1.1.2
   (reemplazo completo, `top_level_keys_missing`, `remove_top_level_keys`,
   `config` omitible al confirmar).

---

### Historia de usuario 2 — Obtener la respuesta de una acción peligrosa confirmándola (Prioridad: P2)

El usuario pide algo cuya acción de HA está en la denylist y devuelve datos;
el caso de referencia es `conversation.process`, que ejecuta intents (puede
abrir una cerradura) y devuelve la respuesta del asistente. Hoy
`ha_call_service_response` la rechaza siempre y `ha_call_service`, que sí
confirma, no devuelve la respuesta. Con esta mejora la misma tool da una vista
previa y un token, y al confirmar devuelve la respuesta.

**Por qué esta prioridad**: prioridad media-alta en la 008; desbloquea la 023
(Assist y conversación).

**Prueba independiente**: llamar a `ha_call_service_response("conversation",
"process", {"text": …})` sin token (rechazo con vista previa y token, sin
ejecutar), confirmar con el token y comprobar que se ejecuta una vez y
devuelve la respuesta.

**Escenarios de aceptación**:

1. **Dado** un servicio de la denylist, **cuando** se llama sin token,
   **entonces** la respuesta conserva `error: service_in_denylist` de la 1.1.2
   y añade `confirmation_token`, `expires_in_seconds`, `preview` (dominio,
   servicio, datos y motivo, como en `ha_call_service`) y una pista que dice
   cómo confirmar; HA no recibe nada.
2. **Dado** ese token, **cuando** se repite la llamada con los mismos
   argumentos y el token, **entonces** el servicio se ejecuta una sola vez con
   `return_response` y se devuelve la respuesta de HA.
3. **Dado** ese token, **cuando** se confirma con otros datos, otro servicio o
   desde `ha_call_service`, **entonces** se rechaza y no se ejecuta nada; y un
   token de `ha_call_service` tampoco sirve aquí.
4. **Dado** un servicio que alcanza una entidad restringida, **cuando** se
   llama sin token, **entonces** se conserva `error: entity_restricted` y se
   añaden la vista previa (con `restricted_entities`) y el token, igual que en
   el caso de la denylist.
5. **Dado** un servicio fuera de la denylist, **cuando** se llama, **entonces**
   se ejecuta a la primera, como en la 1.1.2.

---

### Historia de usuario 3 — Listas con la misma forma en las tools nuevas (Prioridad: P3)

El cliente que usa las tools nuevas de la 1.2.0 encuentra siempre la misma
forma de lista, `{count, items, truncated}`, documentada en la guía. Las
sub-features que añaden tools de lista no pueden olvidarlo: un test lo
comprueba en todas las tools nuevas.

**Por qué esta prioridad**: prioridad media; no cambia nada para el usuario de
la 1.1.2, pero evita que el problema 21 de la 1.0.11 crezca con las ~120 tools
nuevas.

**Prueba independiente**: el test transversal falla si se registra una tool
`ha_list_*` nueva que no construye su respuesta con el constructor del sobre,
y pasa con las tools reales de la rama.

**Escenarios de aceptación**:

1. **Dado** el constructor del sobre, **cuando** recibe una lista,
   **entonces** devuelve `count` igual al número de elementos, `items` y
   `truncated` (falso salvo que se diga).
2. **Dado** un sobre más grande que el tope de respuesta, **cuando** pasa por
   el tope central, **entonces** se recorta por el final con `truncated: true`
   y `count` igual a los elementos devueltos.
3. **Dado** `hermes_guide()`, **cuando** se lee el índice, **entonces**
   describe el sobre y dice que las tools anteriores a la 1.2.0 conservan su
   forma.
4. **Dado** una tool nueva de lista que devuelve otra forma, **cuando** corre
   la suite, **entonces** el test transversal falla con su nombre.

---

### Casos límite

- `view_index` y `config` a la vez, `view_index` y `remove_top_level_keys` a
  la vez, `view` sin `view_index` o `view_index` sin `view` en la vista
  previa → `invalid_argument` sin token y sin tocar HA.
- `view` que no es un objeto, o que trae la clave `views` (parece un dashboard
  entero pasado por error) → `invalid_argument`.
- `view_index` que no es un entero (incluido un booleano) → `invalid_argument`;
  negativo o mayor o igual que el número de vistas → `view_index_out_of_range`
  con `views_count`.
- Dashboard sin configuración guardada (`config_not_found`) o de estrategia →
  `no_views`: no hay vista que sustituir.
- Lectura del dashboard fallida en la vista previa → `preview_unavailable`;
  en la confirmación → error de conexión, el token sigue pendiente.
- La vista nueva idéntica a la actual: se previsualiza y se guarda igual; la
  vista previa lo dice (`view_unchanged: true`).
- Tope de documentos guardados lleno: la vista no se guarda junto al token y
  la confirmación tiene que reenviar `view` (como `config` en la 1.1.2).
- Confirmar por vista con un token emitido para un guardado completo (o al
  revés) → «does not match», sin guardar.
- `ha_call_service_response` con `service_data` inseguro → `unsafe_service_data`
  antes de cualquier token, como hoy.
- `ha_call_service_response` con token para un servicio que no lo necesita:
  se ignora el token y se ejecuta (mismo criterio que `ha_call_service`).
- La respuesta de una acción confirmada no se escribe nunca en el fichero del
  token: solo `{"called": true}`.

## Requisitos *(obligatorio)*

### Requisitos funcionales

Cada FR indica entre paréntesis el FR y la CAP de la 008 de los que sale.

#### Guardado por vistas (US1)

- **FR-001**: `ha_save_lovelace_dashboard` acepta dos argumentos opcionales
  nuevos, `view_index` (entero, 0-based) y `view` (objeto). Con ellos guarda
  **solo esa vista**: el documento guardado es el dashboard actual con
  `views[view_index]` sustituida por `view`; las demás vistas y todas las
  claves de nivel superior quedan idénticas, byte a byte en su contenido JSON
  (FR-063; CAP-019).
- **FR-002**: El guardado por vista va siempre en dos pasos. La vista previa
  dice exactamente qué cambia y qué se conserva: `url_path`, `mode:
  "single_view"`, `view_index`, `views_total`, un resumen de la vista antes y
  después (título, ruta, tipo y recuento de tarjetas, insignias y secciones),
  `view_unchanged`, la lista de vistas que se conservan (índice, título y
  ruta), las claves de nivel superior que se conservan y el resumen de
  recuentos del dashboard entero; nunca el JSON completo (FR-063, FR-018;
  CAP-019; principio IV).
- **FR-003**: El token de un guardado por vista queda atado, además de a sus
  argumentos, al **estado del dashboard leído en la vista previa**. Si al
  confirmar el dashboard ya no es el mismo, se responde `dashboard_changed`,
  no se guarda nada y el cliente tiene que pedir otra vista previa. El
  mecanismo es opcional en el módulo de confirmaciones y no cambia nada para
  las tools que no lo usan (FR-063, FR-020; CAP-019; principios III y IV).
- **FR-004**: `view` se puede omitir al confirmar, como `config`: la vista
  previa lo guarda junto al token y `confirm_with` dice `url_path`,
  `view_index` y `confirmation_token`. Lo que se reenvíe tiene que ser
  idéntico (FR-063; CAP-019; spec 007).
- **FR-005**: Las combinaciones y valores inválidos de los casos límite se
  rechazan sin escribir nada en HA y sin emitir token (las mezclas de
  argumentos, incluso antes de leer el dashboard), con los
  códigos `invalid_argument`, `view_index_out_of_range`, `no_views`,
  `yaml_mode` y `preview_unavailable` (FR-063; CAP-019; principio III).
- **FR-006**: Sin `view_index` ni `view`, `ha_save_lovelace_dashboard` se
  comporta exactamente como en la 1.1.2: reemplazo completo, vista previa de
  siempre, `top_level_keys_missing`, `remove_top_level_keys`, `config`
  omitible al confirmar, y los tokens emitidos antes del cambio siguen valiendo
  (FR-020).
- **FR-007**: La descripción de `ha_save_lovelace_dashboard` y la de
  `ha_get_lovelace_dashboard` (incluida la pista de `too_large`), el tema
  `lovelace` de la guía y la trampa de `INSTRUCTIONS` sobre Lovelace explican
  el guardado por vista (FR-018; principio V).

#### Acciones de la denylist con respuesta (US2)

- **FR-008**: `ha_call_service_response` acepta `confirmation_token`
  opcional. Para una acción de la denylist o que alcanza una entidad
  restringida (el mismo criterio que `ha_call_service`), la llamada sin token
  no ejecuta nada y devuelve el `error` de la 1.1.2 (`service_in_denylist` o
  `entity_restricted`) **más** `confirmation_token`, `expires_in_seconds`,
  `preview` y una `hint` que dice cómo confirmar. La vista previa tiene los
  mismos campos que la de `ha_call_service` (`domain`, `service`,
  `service_data`, `reason` y, si aplica, `restricted_entities`) con
  `action: "call_service_response"` (FR-064, FR-020; CAP-020).
- **FR-009**: Con un token válido se ejecuta la acción una sola vez con
  `return_response` y se devuelve la respuesta de HA igual que para una acción
  fuera de la denylist. El token está atado a `ha_call_service_response` y a
  `domain`, `service` y `service_data` normalizados: otros argumentos, otra
  tool o un token de `ha_call_service` se rechazan sin ejecutar; es de un solo
  uso y caduca. En el fichero del token solo queda `{"called": true}`, nunca la
  respuesta (FR-064, FR-019; CAP-020; principios II y IV).
- **FR-010**: Fuera de la denylist y de las entidades restringidas no cambia
  nada: se ejecuta a la primera y un token, si llega, se ignora (como en
  `ha_call_service`). `unsafe_service_data` se sigue comprobando antes que
  todo lo demás (FR-020; CAP-020).
- **FR-011**: La descripción de `ha_call_service_response`, el tema `services`
  de la guía, `INSTRUCTIONS` si lo menciona y `SECURITY.md` dicen que acepta
  confirmación para la denylist (FR-018, FR-023; principio V).

#### Sobre común de listas (US3)

- **FR-012**: Hay un constructor compartido del sobre de lista que devuelve
  `{count, items, truncated}` (más los campos de cabecera que pase quien lo
  usa), con `count` igual a `len(items)`; las genéricas de la 011 lo usan en
  vez de su copia propia, sin cambiar su respuesta (FR-018, FR-065; CAP-023).
- **FR-013**: La guía documenta el sobre en el índice (`hermes_guide()`):
  qué significa cada campo, que el tope central recorta por el final con
  `truncated: true` y que las tools anteriores a la 1.2.0 conservan su forma
  (FR-065; CAP-023).
- **FR-014**: Un test transversal recorre las tools registradas que no están
  en la instantánea de la 1.1.2 y exige que toda `ha_list_*` o `sv_list_*`
  construya su respuesta con el constructor del sobre o esté en una lista de
  excepciones con su motivo; tiene un control negativo con una tool sintética
  que lo incumple (FR-065; CAP-023; principio VII).
- **FR-015**: Ninguna tool de la 1.1.2 cambia la forma de su lista
  (clarificación de la 008, D-07) (FR-020; CAP-023).

#### Transversales

- **FR-016**: La instantánea de esquemas admite exactamente estas diferencias,
  todas opcionales: `ha_save_lovelace_dashboard` gana `view_index` y `view`;
  `ha_call_service_response` gana `confirmation_token`. `required` no cambia en
  ninguna tool, las anotaciones tampoco y la excepción
  `SIN_TOKEN_A_PROPOSITO` del test de tokens queda vacía (FR-020).
- **FR-017**: El banco de pruebas de Core ejecuta de verdad el guardado por
  vista (incluido el rechazo por `dashboard_changed`) y
  `conversation.process` por `ha_call_service_response` en dos pasos, con el
  efecto comprobado por el lector independiente cuando lo hay (FR-015 de la
  008; CAP-019 y CAP-020 en la matriz).
- **FR-018**: La vista guardada junto al token sigue las reglas del documento
  guardado de la 1.1.2 (tope, borrado al completar o caducar) y no aparece en
  el log; los eventos de log nuevos llevan solo `url_path`, `view_index`,
  dominio y servicio, nunca contenido (FR-019; principio II).
- **FR-019**: Documentación en el mismo cambio: sección propia en
  `## [1.2.0]` de `hermes/CHANGELOG.md`; estado de la 018 y del problema 21 en
  `docs/HOJA-DE-RUTA.md`; `SECURITY.md`; y la matriz de la 008 con los tests
  definitivos (FR-023, FR-098; CAP-019, CAP-020, CAP-023).

### Entidades clave

- **Guardado por vista**: `url_path`, `view_index`, `view` y el estado del
  dashboard en la vista previa; produce el documento resultante (el actual con
  una vista sustituida).
- **Estado ligado al token**: huella del documento actual que se compara al
  confirmar; no la manda el cliente.
- **Vista previa por vista**: lo que cambia (una vista) y lo que se conserva
  (las demás vistas y las claves de nivel superior).
- **Confirmación de una acción con respuesta**: los argumentos de la llamada
  normalizados, la vista previa de `ha_call_service` y la respuesta de HA (que
  no se guarda).
- **Sobre de lista**: `count`, `items`, `truncated` y los campos de cabecera
  de cada tool.

## Criterios de éxito *(obligatorio)*

### Resultados medibles

- **SC-001**: Cambiar una vista de un dashboard de más de 100 KB no exige
  enviar más que esa vista: en la confirmación no se reenvía nada más que
  `url_path`, `view_index` y el token.
- **SC-002**: En el 100 % de los guardados por vista probados (unitarios y
  banco), las vistas no tocadas y las claves de nivel superior quedan
  idénticas a las de antes.
- **SC-003**: Ninguna confirmación por vista guarda un dashboard que cambió
  después de la vista previa (test unitario y banco).
- **SC-004**: `conversation.process` devuelve su respuesta a través de Hermes
  confirmando en dos pasos, y sin token nunca llega a HA.
- **SC-005**: Las 216 tools de la 1.1.2 conservan esquemas (salvo las tres
  propiedades opcionales de FR-016), anotaciones y respuestas por defecto: la
  suite de la 1.1.2 pasa sin cambiar ningún test existente salvo los que
  enumeran las diferencias permitidas.
- **SC-006**: Toda tool de lista nueva que llegue a la rama con otra forma
  hace fallar la suite.
- **SC-007**: Cada comportamiento nuevo con riesgo tiene su control negativo
  anotado (principio VII).

## Supuestos

- La huella del estado se calcula sobre el documento que devuelve
  `lovelace/config` con la misma canonicalización que el `action_hash`; dos
  lecturas sin cambios dan la misma huella.
- Entre la confirmación y la escritura en HA queda la ventana de
  «last-write-wins» que ya documenta la 1.1.2 (HA no tiene bloqueo de
  dashboards); FR-003 cierra la ventana larga (los hasta 60 s del token), no
  esa.
- Sustituir una vista no añade ni quita vistas: para eso sigue el guardado
  completo.
- `conversation.process` está en la denylist de Hermes y en Core 2026.11.1
  admite respuesta (`SupportsResponse.OPTIONAL`).
- El banco de la 010 se integra en esta rama más tarde: sus tests se escriben
  como los de la 011 (se saltan con su motivo hasta integrarlo), y la
  configuración del banco necesita `lovelace:` y `conversation:`.

## Fuera de alcance

- Unificar la forma de las listas de las tools de la 1.1.2 (D-07 de la 008).
- Atar al estado el guardado completo del dashboard (cambiaría la 1.1.2).
- Añadir, quitar o reordenar vistas por vista.
- Tools dedicadas de conversación (sub-feature 023) y cualquier cambio de la
  tabla de comandos.
- Poner una guarda de denylist dentro de `HAClient.call_service_response`
  (hallazgo anotado en research R-3; defensa en profundidad para otra spec).

## Dudas para el final

- **DF-1**: La respuesta sin token de `ha_call_service_response` lleva `error`
  y token a la vez para no romper a los clientes de la 1.1.2. ¿Pasar en la
  1.3.0 a la forma de las demás vistas previas (sin `error`), con aviso, junto
  con D-07?
- **DF-2**: ¿Atar también al estado el guardado completo de un dashboard
  (rechazar si cambió desde la vista previa)? Es más seguro, pero cambia el
  comportamiento de la 1.1.2.
- **DF-3**: ¿Guardado por vista para añadir o borrar una vista
  (`view_index == len(views)` para añadir)?
