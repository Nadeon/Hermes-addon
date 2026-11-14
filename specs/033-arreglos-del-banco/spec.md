# Especificación: Hermes 1.2.0 — arreglos de tools existentes destapados por el banco (033)

**Directorio de la spec**: `specs/033-arreglos-del-banco`

**Creada**: 2026-11-14

**Estado**: Borrador

**Entrada**: sub-feature 033 del programa «cobertura total»
([spec 008](../008-cobertura-total/spec.md)). No estaba en el desglose
original: la añade el supervisor del programa al ver lo que el banco de
pruebas de Core (010) y las revisiones de la 010 y de la 028 han destapado en
tools de la 1.1.2. Entra en la 008 con este mismo cambio: FR-099 y CAP-039,
fila 033 del desglose y de la matriz de `plan.md`, tarea T030 de `tasks.md` y
fila de la tabla del programa en `docs/HOJA-DE-RUTA.md`.

No añade tools. Corrige siete tools que ya existen para que hagan lo que dicen
o digan lo que hacen (principios IV y V), sin quitar ninguna y sin romper a
quien hoy las usa bien (FR-020 de la 008). Las tools siguen en sus familias.

## Clarificaciones

### Sesión 2026-11-14

Decisiones del supervisor del programa, que no se discuten aquí:

- P: ¿Se quita `ha_reload_counters`? → R: **no**. Quitarla rompería a quien la
  tenga en uso. Pasa a ser honesta: devuelve `not_supported` explicando que HA
  no ofrece recarga de contadores, su descripción y la guía lo dicen, y queda
  deprecada con retirada en la 1.3.0. En el banco sale de `FALLAN_EN_BANCO`.
- P: ¿Qué se arregla primero? → R: el token de `ha_trigger_automation` y
  `ha_run_script` que no ata `variables` (ALTO, seguridad, principio IV), y
  cualquier otra tool con confirmación que deje argumentos fuera del hash.
  Va en el tramo 1; el resto, en el tramo 2.
- P: ¿Se puede cambiar la instantánea de esquemas
  (`tests/fixtures/esquemas_1_1_2.json`)? → R: solo con excepciones
  justificadas en el propio test: quitar un argumento obligatorio que ningún
  cliente podía rellenar con sentido (`ctx`) y añadir uno opcional. La
  instantánea no se regenera.

Decisiones tomadas al especificar (comprobadas en el código de Hermes y en el
de HA Core 2026.11.1; el detalle está en [research.md](research.md)):

- P: ¿Hay más tools con confirmación que dejen argumentos fuera del hash? → R:
  **no**. Se revisaron las 79 tools con `confirmation_token` y los cuatro
  ayudantes comunes (R-1): solo `guarded_entity_invoke` deja fuera un
  argumento que cambia el efecto (`variables`). `ha_call_service`,
  `ha_fire_event` (sin confirmación), los flujos (sin confirmación), las
  `sv_*` y las `fs_*` atan todo lo que envían. Para que no vuelva a pasar, un
  test de inventario exige que cada argumento de cada tool con token esté
  atado o exento con un motivo escrito (FR-003).
- P: ¿Hay otra forma correcta de recargar contadores? → R: **no**. La
  integración `counter` de 2026.11.1 solo registra `increment`, `decrement`,
  `reset` y `set_value`; su YAML se lee una vez al arrancar y no hay servicio
  `reload`. `homeassistant.reload_all` recarga todo lo demás y no los
  contadores: no es una alternativa honesta (R-2).
- P: ¿Hay una vía correcta de leer las opciones de una config entry? → R:
  **no**. Ningún comando WebSocket ni ruta REST de Core 2026.11.1 devuelve
  `options`: `as_json_fragment` no las incluye, los diagnósticos dependen de
  cada integración y `.storage` está vetado en Hermes. La tool pasa a ser
  honesta (`not_supported`) y queda deprecada con retirada en la 1.3.0, como
  `ha_reload_counters` (R-6).
- P: ¿Qué hace `name` en `ha_create_scene_from_current`? → R: `scene.create`
  no admite nombre y las escenas que crea no están en el registro de
  entidades, así que no hay forma de ponérselo. `name` sigue en el esquema
  (FR-020 de la 008), pero si se pasa la tool responde `name_not_supported`
  sin llamar a HA (hoy falla siempre con un 400 de HA), y el argumento queda
  deprecado con retirada en la 1.3.0. No se ignora en silencio: quien lo pasa
  espera un nombre que no va a tener (R-4).
- P: ¿Cómo se trata la colisión en `ha_create_scene_from_current`? → R: como
  `ha_create_or_update_scene`: si la escena no existe, se crea en un paso; si
  ya existe, la tool pasa a **dos pasos** con una vista previa que dice lo que
  hará HA. Si la escena existente no la creó `scene.create` (tiene `id` en sus
  atributos o está en el registro de entidades), HA no haría nada y solo
  dejaría un aviso en su log: la tool lo dice como error `scene_exists` sin
  emitir token. Tras ejecutar, la tool comprueba que la escena quedó con las
  entidades pedidas; si no, lo dice (R-4).
- P: ¿Y el `amount` de los contadores? → R: la sospecha se confirma en el
  código de HA: `counter.set_value` lanza `ValueError` si el valor no es
  múltiplo del `step` o sale de `minimum`/`maximum`, y el REST de Core lo
  convierte en un 500 sin mensaje. Pasa con `step` distinto de 1 aunque
  `amount` sea múltiplo del `step` (un contador con `initial` 5 y `step` 3).
  `amount` conserva su significado (se suma al valor actual); la tool
  comprueba antes esas reglas con los atributos del contador y, si no se
  cumplen, responde `invalid_amount` con el motivo, sin llamar a HA (R-7).

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es un administrador de Home Assistant que trabaja a través de un
cliente MCP, y el mantenedor de Hermes que lee el banco de pruebas.

### Historia 1 — Lo que se confirma es lo que se vio (Prioridad: P1)

Quien ejecuta un script o dispara una automatización restringida (su contenido
invoca servicios de la denylist) ve una vista previa y confirma con el token.
Hoy el token no cubre `variables`: se puede pedir la vista previa con unas
variables y confirmar con otras, y la vista previa ni siquiera las enseña. Un
script restringido puede hacer cosas muy distintas según sus variables.

**Prueba independiente**: con un script restringido, una vista previa con
`variables` A y una confirmación con `variables` B se rechazan sin llamar a HA;
con las mismas variables, se ejecuta con ellas.

**Escenarios de aceptación**:

1. **Dado** un script restringido, **cuando** se llama a `ha_run_script` con
   `variables={"modo": "suave"}` sin token, **entonces** la vista previa
   enseña esas variables y devuelve un token.
2. **Dado** ese token, **cuando** se confirma con `variables={"modo": "todo"}`,
   **entonces** la tool rechaza el token por no coincidir y HA no recibe
   ninguna llamada.
3. **Dado** ese token, **cuando** se confirma sin `variables`, **entonces** se
   rechaza igual (pedir con variables y confirmar sin ellas es otra acción).
4. **Dado** ese token, **cuando** se confirma con las mismas variables (en
   otro orden de claves), **entonces** se ejecuta y HA recibe esas variables.
5. Lo mismo con `ha_trigger_automation` y una automatización restringida.
6. **Dado** un script NO restringido, **entonces** sigue en un solo paso, con
   o sin variables, como en la 1.1.2.

---

### Historia 2 — Las tools que no pueden hacer su trabajo lo dicen (Prioridad: P1)

Quien pide recargar los contadores o leer las opciones de una integración
quiere saber si se ha hecho. Hoy `ha_reload_counters` falla con un 400 tras
pedir confirmación, y `ha_get_config_entry_options` devuelve `{}` siempre,
como si la integración no tuviera opciones.

**Prueba independiente**: las dos tools devuelven `not_supported` con una
explicación, sin llamar a HA en el caso de los contadores, y su descripción y
la guía dicen lo mismo.

**Escenarios de aceptación**:

1. **Dado** cualquier estado, **cuando** se llama a `ha_reload_counters` con o
   sin token, **entonces** responde `not_supported`, explica que HA no ofrece
   recarga de contadores (los creados desde la UI o con Hermes no la
   necesitan; los de YAML se leen al reiniciar HA), avisa de que está
   deprecada (retirada en la 1.3.0), no emite token y HA no recibe ninguna
   llamada.
2. **Dado** una config entry existente, **cuando** se llama a
   `ha_get_config_entry_options`, **entonces** responde `not_supported` con
   `entry_id`, `domain`, `title` y `supports_options`, explica que HA no
   publica las opciones y cómo verlas (el formulario de
   `ha_start_options_flow`, que en muchas integraciones trae los valores
   actuales, y abortarlo después), y avisa de la deprecación.
3. **Dado** un `entry_id` que no existe, **entonces** sigue respondiendo
   `not_found`, como en la 1.1.2.

---

### Historia 3 — `ha_wait_for_event` se puede llamar como dice su esquema (Prioridad: P1)

Quien espera un evento hoy tiene que mandar un argumento `ctx` obligatorio que
no significa nada, y el aviso de progreso que mantiene viva la conexión en las
esperas largas nunca se envía.

**Prueba independiente**: el esquema publicado de `ha_wait_for_event` no tiene
`ctx`; una llamada sin `ctx` funciona; una espera larga envía avisos de
progreso; un cliente que siga mandando `ctx` no se rompe.

**Escenarios de aceptación**:

1. **Dado** el registro de tools, **entonces** el esquema de entrada de
   `ha_wait_for_event` tiene `event_type`, `filters` y `timeout_seconds`, y
   solo `event_type` es obligatorio.
2. **Dado** un cliente MCP, **cuando** llama sin `ctx` y ocurre el evento,
   **entonces** recibe `matched: true`.
3. **Dado** una espera más larga que el intervalo de keepalive, **entonces**
   el cliente recibe avisos de progreso.
4. **Dado** un cliente que manda `ctx` como antes, **entonces** la llamada
   funciona igual (el argumento sobrante se ignora).

---

### Historia 4 — Capturar una escena funciona y dice la verdad (Prioridad: P2)

Quien guarda «cómo están ahora las luces» como escena quiere que funcione con
nombre o sin él, saber que la escena es temporal y no perder sin aviso otra
escena con el mismo id.

**Prueba independiente**: sin `name` y con un id nuevo, la escena se crea en un
paso; con un id de una escena temporal existente, pide confirmación; con un id
de una escena de configuración, responde `scene_exists`; con `name`, responde
`name_not_supported` sin llamar a HA.

**Escenarios de aceptación**:

1. **Dado** un `scene_id` que no existe, **cuando** se llama sin `name`,
   **entonces** HA crea la escena con el estado actual de las entidades y la
   respuesta lo confirma tras leerla de vuelta.
2. **Dado** un `scene_id` de una escena creada antes con `scene.create`,
   **cuando** se llama sin token, **entonces** devuelve una vista previa con las
   entidades actuales y las nuevas y un token; con el token, HA la reemplaza.
3. **Dado** un `scene_id` de una escena de `scenes.yaml` o de otra
   integración, **entonces** responde `scene_exists` sin token y sin llamar a
   `scene.create`.
4. **Dado** `name`, **entonces** responde `name_not_supported`, explica que
   `scene.create` no admite nombre y sugiere `ha_create_or_update_scene` para
   una escena con nombre y persistente; HA no recibe ninguna llamada.
5. **Dado** una entidad de `entity_ids` que no existe, **entonces** responde
   `entity_not_found` con la lista, sin llamar a HA (hoy HA la salta y, si no
   queda ninguna, no crea nada y responde bien).
6. La descripción dice que la escena es **temporal**: desaparece al reiniciar
   HA y en cada recarga de escenas, también la que provoca
   `ha_create_or_update_scene` o `ha_delete_scene` al guardar o borrar.
7. La anotación la marca como destructiva (puede reemplazar una escena).

---

### Historia 5 — Las descripciones de las escenas dicen dónde se guardan (Prioridad: P3)

`ha_create_or_update_scene`, `ha_get_scene` y `ha_delete_scene` dicen que las
escenas editables están en `.storage/core.scene_*`. Están en `scenes.yaml`.

**Prueba independiente**: ninguna descripción de las tools de escenas ni la
guía mencionan `.storage` como sitio de las escenas, y dicen `scenes.yaml`.

**Escenarios de aceptación**:

1. **Dado** el registro, **entonces** las descripciones de esas tres tools
   nombran `scenes.yaml` y no `.storage/core.scene_*`.
2. La de `ha_create_or_update_scene` deja de decir que ve las escenas creadas
   con `scene.create` (no las ve: son temporales y no están en `scenes.yaml`).

---

### Historia 6 — Incrementar un contador «de golpe» no da un 500 (Prioridad: P2)

Quien pide «suma 3 al contador» a un contador con `step` 3 recibe hoy un error
500 de HA sin explicación si el valor actual no es múltiplo de 3, o si el
resultado sale del máximo.

**Prueba independiente**: con un contador de `step` 3 en 5, `amount=3`
responde `invalid_amount` con el motivo y el contador no cambia; con `step` 1,
`amount` funciona como en la 1.1.2.

**Escenarios de aceptación**:

1. **Dado** un contador con `step` 1, **cuando** se incrementa con `amount=4`,
   **entonces** sube 4, como en la 1.1.2.
2. **Dado** un contador con `step` 3 en 6, **cuando** se incrementa con
   `amount=3`, **entonces** queda en 9.
3. **Dado** un contador con `step` 3 en 5, **cuando** se incrementa con
   `amount=3`, **entonces** responde `invalid_amount` explicando que HA exige
   un valor múltiplo del `step` y que se puede usar la tool sin `amount`; el
   contador sigue en 5 y HA no recibe `set_value`.
4. **Dado** un contador con `maximum` 10 en 9, **cuando** se incrementa con
   `amount=5`, **entonces** responde `invalid_amount` por salir del máximo
   (sin `amount`, `increment` se queda en el máximo como en HA).
5. Lo mismo con `ha_decrement_counter` y el mínimo.

---

### Historia 7 — El banco da cada arreglo por probado contra HA real (Prioridad: P1)

El mantenedor quiere que el banco deje de marcar estos fallos como hallazgos
pendientes y que cada arreglo se haya visto funcionar contra HA Core
2026.11.1.

**Prueba independiente**: en el job del banco no queda ningún `xfail`
`HALLAZGO` de estas tools, `FALLAN_EN_BANCO` está vacío y cada arreglo tiene
un test del banco que pasa.

**Escenarios de aceptación**:

1. **Dado** el job del banco, **entonces** `XFAIL_PERMITIDOS` ya no tiene el
   test de `ha_reload_counters`, ni el de `ha_create_scene_from_current` de la
   028 si llegó a añadirse.
2. **Dado** el inventario del banco, **entonces** `ha_reload_counters` está en
   `NO_EJECUTABLES` con un motivo concreto, y su test del banco comprueba que
   Core sigue sin `counter.reload` (si HA lo añade, el test cae y avisa) y que
   la tool responde `not_supported`.
3. Cada historia anterior que toca HA tiene su test en el banco.

### Casos límite

- **Variables `None` frente a `{}`**: no son la misma acción. HA trata igual
  `variables` ausente y `{}`, pero el token se ata a lo que se pidió; un
  cliente que confirma con la forma distinta recibe el rechazo y repite la
  vista previa. Más estricto, nunca menos.
- **Variables con números**: la canonicalización del token ya trata `1` y
  `1.0` como iguales y `true` distinto de `1` (spec 007).
- **Variables enormes**: la vista previa las enseña enteras; si la respuesta
  pasa del tope, se recorta con el mecanismo común de vistas previas, que
  conserva el token.
- **Token emitido por la 1.1.2 para un script restringido**: deja de valer
  (los argumentos atados cambian). Caduca en 60 s, así que solo afecta a una
  confirmación en vuelo durante la actualización.
- **Entidad que deja de estar restringida entre la vista previa y la
  confirmación**: comportamiento de la 1.1.2, sin cambios.
- **`ha_reload_counters` con un token**: no se valida ni se gasta; la
  respuesta es `not_supported` igual.
- **Contador sin `step` en los atributos** (no debería pasar en 2026.11.1):
  se asume 1, que es el valor por defecto de HA.
- **Estado del contador no numérico** (`unavailable`): sigue respondiendo
  `invalid_state`, como en la 1.1.2.
- **Escena temporal que existe y otra petición la reemplaza entre la vista
  previa y la confirmación**: la comprobación posterior lee lo que hay y lo
  dice; la confirmación no revalida el estado (igual que el resto de tools de
  dos pasos).
- **`scene_id` con prefijo `scene.`**: se normaliza como hoy.
- **Cliente MCP que sigue mandando `ctx`**: se ignora; no da error.

## Requisitos *(obligatorio)*

### Requisitos funcionales

Cada requisito cita el FR de la 008 y la CAP que cumple. Todos son de la CAP-039
(«tools de la 1.1.2 que el banco destapa») y del FR-099 de la 008, que los
agrupa; los transversales que aplican son FR-014, FR-018, FR-020 y FR-023.

#### Tramo 1 — el token ata lo que se ejecuta

- **FR-001** (008 FR-099, CAP-039; principio IV): el token de
  `ha_trigger_automation` y de `ha_run_script` para una entidad restringida
  queda atado a la tool, la entidad, el servicio y `variables` tal como llegan
  (incluido que no lleguen). Confirmar con otras variables, sin ellas o con
  ellas cuando la vista previa no las tenía se rechaza como un token que no
  coincide, sin llamar a HA. Con las mismas, HA recibe exactamente esas
  variables.
- **FR-002** (008 FR-099, CAP-039; principio IV): la vista previa de esas dos
  tools enseña `variables` tal como se enviarán (o `null` si no hay), igual
  que `ha_call_service` enseña `service_data`.
- **FR-003** (008 FR-099, FR-018, CAP-039; principio VI): un test de
  inventario recorre todas las tools registradas con `confirmation_token` y
  exige, para cada argumento de su firma, que esté **atado** al token o
  **exento** con un motivo escrito (`confirmation_token`; los documentos
  omitibles, que se atan igual por hash). Una tool nueva con token y sin
  entrada, o un argumento nuevo sin clasificar, hacen fallar el test. Cada
  entrada «atado» de las tools que se arreglan aquí tiene además su test de
  comportamiento (FR-001).

#### Tramo 2 — honestidad de las demás tools

- **FR-004** (008 FR-099, FR-020, CAP-039; principio V): `ha_reload_counters`
  responde siempre `not_supported` con el motivo, el campo `_deprecated`
  (retirada en la 1.3.0) y ninguna llamada a HA ni token emitido. Su
  descripción empieza por `DEPRECATED (removed in 1.3.0)` y explica por qué;
  la guía lo dice. Nombre, argumentos y anotaciones no cambian.
- **FR-005** (008 FR-099, FR-020, CAP-039): `ha_wait_for_event` recibe el
  contexto MCP inyectado por el servidor: `ctx` desaparece del esquema
  publicado, el servidor lo reconoce como contexto, los avisos de progreso
  llegan al cliente y una llamada que siga mandando `ctx` funciona igual. Un
  test del registro comprueba el esquema y que el servidor inyecta el
  contexto.
- **FR-006** (008 FR-099, FR-018, FR-020, CAP-039; principios IV y V):
  `ha_create_scene_from_current`:
  - nunca envía `name` a `scene.create`; si se pasa `name`, responde
    `name_not_supported` sin llamar a HA, y el argumento queda deprecado
    (retirada en la 1.3.0);
  - si alguna entidad de `entity_ids` no existe, responde `entity_not_found`
    con la lista, sin llamar a HA;
  - si `scene.<scene_id>` no existe, crea la escena en un paso;
  - si existe y la creó `scene.create`, pide confirmación en dos pasos con
    una vista previa que enseña las entidades actuales y las nuevas y dice que
    HA la reemplaza; el token ata `scene_id` y `entity_ids`;
  - si existe y no la creó `scene.create`, responde `scene_exists` sin token;
  - tras ejecutar, lee la escena y comprueba que sus entidades son las
    pedidas; si no, responde `scene_not_created` con lo que vio;
  - gana el argumento opcional `confirmation_token` y la anotación
    `destructiveHint`; la descripción dice que la escena es temporal
    (desaparece al reiniciar HA y en cada recarga de escenas, incluida la que
    hacen `ha_create_or_update_scene` y `ha_delete_scene`).
- **FR-007** (008 FR-099, CAP-039; principio V): las descripciones de
  `ha_create_or_update_scene`, `ha_get_scene` y `ha_delete_scene` dicen que
  las escenas editables están en `scenes.yaml`, no en `.storage`, y la de
  `ha_create_or_update_scene` deja de decir que ve las de `scene.create`.
- **FR-008** (008 FR-099, FR-020, CAP-039; principio V):
  `ha_get_config_entry_options` responde `not_supported` con `entry_id`,
  `domain`, `title`, `supports_options`, el motivo, una indicación de cómo ver
  los valores (`ha_start_options_flow` y abortar después) y `_deprecated`
  (retirada en la 1.3.0). Una entry inexistente sigue dando `not_found`. Su
  descripción y la guía lo dicen.
- **FR-009** (008 FR-099, FR-020, CAP-039): `ha_increment_counter` y
  `ha_decrement_counter` con `amount` comprueban, con los atributos del
  contador, que el valor resultante es múltiplo del `step` y está dentro de
  `minimum`/`maximum`; si no, responden `invalid_amount` con el motivo y no
  llaman a HA. Si se cumple, hacen lo mismo que en la 1.1.2. Sin `amount`, no
  cambian. Su descripción explica la regla.

#### Banco, compatibilidad y documentación

- **FR-010** (008 FR-014, FR-099, CAP-034, CAP-039): cada arreglo que toca HA
  tiene su test en el banco de Core contra HA 2026.11.1 real, con el efecto (o
  su ausencia) comprobado por el lector independiente:
  - tramo 1: la vista previa con variables, el rechazo con otras variables
    (HA sin llamadas) y la ejecución con las mismas (HA ve las variables), en
    un script y una automatización restringidos;
  - tramo 2: `ha_reload_counters` (`not_supported` y Core sin
    `counter.reload`), `ha_wait_for_event` llamada sin `ctx`,
    `ha_create_scene_from_current` (crear, reemplazar con token,
    `scene_exists`, `name_not_supported`), `ha_get_config_entry_options`
    (`not_supported` sobre una entry real) y `amount` de los contadores con
    `step` 3.

  Se quitan los `xfail` `HALLAZGO` de estas tools y sus entradas de
  `XFAIL_PERMITIDOS` (y de `XFAIL_PERMITIDOS_028` / `HALLAZGOS_028` si
  existen); `FALLAN_EN_BANCO` queda vacío y `ha_reload_counters` pasa a
  `NO_EJECUTABLES` con su motivo.
- **FR-011** (008 FR-020, FR-099; SC-005 de la 008): con la configuración por
  defecto siguen las 216 tools con los mismos nombres. Las únicas diferencias
  de esquema y anotaciones respecto a la 1.1.2 son:
  - `ha_wait_for_event` pierde `ctx` (propiedad y obligatorio);
  - `ha_create_scene_from_current` gana `confirmation_token` opcional y pasa
    de `----` a `-D--`.

  Las dos quedan como excepciones escritas, con su porqué, en los tests de la
  instantánea de esquemas y de anotaciones; la instantánea no se regenera.
- **FR-012** (008 FR-022, FR-023, FR-096, FR-099): en el mismo cambio,
  `hermes/CHANGELOG.md` (sección propia en `## [1.2.0]`, bloque
  «Correcciones»), la guía (`tools/guide.py`), `docs/HOJA-DE-RUTA.md` (fila
  033 a «hecha» y las tres deprecaciones nuevas con retirada en la 1.3.0) y la
  matriz de la 008. `SECURITY.md` ya dice que el token se ata a la tool y a sus
  argumentos: pasa a ser verdad también aquí, sin cambiar el texto.
- **FR-013** (008 FR-018; principio VII): cada FR de código tiene su test
  unitario y su control negativo comprobado y anotado (deshacer el arreglo,
  ver el test en rojo, restaurar).

### Entidades clave

- **Argumentos atados**: lo que entra en el `action_hash` del token de una
  tool. Lo que no entra se puede cambiar entre la vista previa y la
  confirmación.
- **Escena temporal**: la que crea `scene.create`; vive en memoria de HA, no
  tiene `id` ni entrada en el registro de entidades y desaparece al reiniciar
  o recargar escenas.
- **Inventario del banco**: `PROBADAS_EN_BANCO`, `NO_EJECUTABLES`,
  `FALLAN_EN_BANCO` y `XFAIL_PERMITIDOS` (010) y sus equivalentes de la 028.

## Supuestos

- **S-01**: la 011 (instantánea de esquemas y su test) y la 028 (base del
  banco para automatizaciones, scripts y escenas, y los scripts restringidos
  de su T033) están integradas en `feat/cobertura-total` antes de implementar.
  Si no, el tramo integra primero la rama del programa (como hizo la 028).
- **S-02**: el `mcp` SDK 2.x del proyecto reconoce como contexto un parámetro
  anotado `Context` aunque la tool esté envuelta por `requires_ready`
  (`typing.get_type_hints` sigue `__wrapped__`) e ignora argumentos sobrantes
  al validar. Los dos se comprueban con un test.
- **S-03**: en HA Core 2026.11.1 las escenas de `scene.create` no tienen el
  atributo `id` y las de `scenes.yaml` con `id` sí; las de otras integraciones
  están en el registro de entidades. Una escena de `configuration.yaml` sin
  `id` no se distingue de una temporal por su estado: se trata como temporal,
  y la comprobación posterior dice si HA no la reemplazó.
- **S-04**: el CI de Linux es la referencia; en Windows fallan 6 tests
  conocidos ajenos a esta spec.

## Fuera de alcance

- Cualquier tool nueva, la tabla de clasificación y las familias.
- Retirar las tools o argumentos deprecados (1.3.0).
- ~~`ha_set_counter_value` con un valor que no es múltiplo del `step`~~:
  ampliación del alcance. El supervisor lo metió como extra del tramo 2
  (notas de `tasks.md`): responde `invalid_value` con la misma comprobación
  que `amount` (research R-7), en vez del 500 genérico de HA.
- Unificar la forma de los errores de las tools existentes (CAP-023).
- Revalidar el estado entre la vista previa y la confirmación en general.
- Los demás hallazgos de las revisiones de la 010 y de la 028 sobre los
  propios tests del banco (los cierra la convergencia de cada una).

## Criterios de éxito *(obligatorio)*

- **SC-001**: en el 100 % de los casos probados, confirmar
  `ha_run_script` o `ha_trigger_automation` con `variables` distintas de las
  de la vista previa no llega a HA, en la suite y en el banco.
- **SC-002**: el test de inventario de argumentos atados cubre el 100 % de las
  tools registradas con `confirmation_token`, y ningún argumento queda sin
  clasificar.
- **SC-003**: en el job del banco, `FALLAN_EN_BANCO` está vacío, ningún `xfail`
  `HALLAZGO` es de una tool de esta spec y cada tool de esta spec que toca HA
  tiene un test del banco que pasa.
- **SC-004**: con la configuración por defecto, los 216 nombres de la 1.1.2
  siguen; esquemas y anotaciones coinciden con la 1.1.2 salvo las dos
  excepciones de FR-011.
- **SC-005**: ninguna descripción de las siete tools tocadas ni la guía
  afirman algo que el código o HA contradigan (revisión en el cierre de cada
  tramo, con la lista de frases en el commit).
- **SC-006**: la suite completa pasa (en Windows fallan solo los 6
  conocidos), el CI de Linux y el banco quedan en verde y cada FR de código
  tiene su control negativo anotado.
