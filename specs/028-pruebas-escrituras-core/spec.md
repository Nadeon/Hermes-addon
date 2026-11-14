# Especificación: pruebas de las escrituras de Core en el banco

**Directorio de la spec**: `specs/028-pruebas-escrituras-core`

**Creada**: 2026-11-14

**Estado**: Borrador

**Programa**: sub-feature 028 de la spec paraguas
[`specs/008-cobertura-total/`](../008-cobertura-total/spec.md) (tarea T005,
ola 1). Cubre la parte de **CAP-034** que no es de helpers y cumple **FR-014**
de la 008 para el resto de tools `ha_*` de la 1.1.2 que modifican. Usa el
banco de la [010](../010-banco-de-pruebas-core/spec.md) (HA Core 2026.11.1
real en el CI, Supervisor simulado y lector independiente) sin rehacerlo. Las
47 tools de los 11 dominios de helpers son de la 010; el banco del Supervisor,
de la 014.

**Entrada**: de las 124 tools que modifican en la 1.1.2, la 010 ejecuta en el
banco las 47 de helpers. Quedan **53 tools `ha_*`** (automatizaciones,
scripts, escenas, registros, Lovelace, config entries y sus flujos,
reparaciones, servicios, eventos y esperas) que solo se han comprobado con
simuladores escritos por el propio proyecto, salvo los dashboards, probados a
mano en la 1.1.2. Las otras 24 que modifican son 5 `fs_*` y 19 `sv_*`.

## Clarificaciones

### Sesión 2026-11-14

Decisiones del supervisor del programa, vinculantes (encargo de la 028):

- P: ¿Qué se hace si una tool falla contra HA real? → R: se deja su test como
  **`xfail` estricto** con el motivo, se anota como **hallazgo** para el
  supervisor y no se arregla el producto en esta sub-feature, **salvo que el
  arreglo sea trivial**.
- P: ¿Cómo se reparte el trabajo? → R: en **2 tramos por dominios**, cada uno
  para un agente nuevo, cada uno con el CI en verde y su propio commit.
- P: ¿Se duplica algo de la 010? → R: **no**. Las 47 tools de helpers, la
  infraestructura del banco (job, onboarding, Supervisor simulado, entorno,
  lector) y su inventario son de la 010; aquí solo se amplían donde haga falta.

Decisiones tomadas al especificar (el mantenedor no estaba; se anotan aquí en
lugar de preguntar):

- P: ¿Entran las `fs_*`? → R: **no**. FR-014 de la 008 habla de «tools `ha_*`
  de la 1.1.2 que modifican». Las `fs_*` no hablan con HA: escriben en el
  `/config` que ve Hermes, que en el banco es una carpeta del runner distinta
  de la de HA, y la suite normal ya las ejecuta contra un sistema de ficheros
  real. Quedan en la lista de fuera del banco con su motivo.
- P: ¿Y las `sv_*`? → R: **fuera**: el Supervisor del banco es un simulado
  que solo reenvía a Core; reinicios, backups, add-ons y avisos del Supervisor
  se prueban con simuladores en la suite normal y en la VM de la 014.
- P: ¿Qué es «una tool que modifica»? → R: la que **no** tiene
  `readOnlyHint` en la tabla central de anotaciones
  (`hermes/src/hermes/tools/_annotations.py`), no la que no empieza por
  `ha_get_`/`ha_list_`. Es la misma definición que da la cifra de 124 y la que
  ve el cliente.
- P: ¿Qué es un arreglo «trivial»? → R: el que cambia **como mucho 10 líneas**
  de `hermes/src/` en **una sola tool**, no cambia su firma, sus anotaciones ni
  lo que dice su descripción, no toca la confirmación en dos pasos ni la
  denylist,
  y lleva su test unitario de regresión con control negativo y su línea en
  «Correcciones» del CHANGELOG. Lo que no cumpla todo eso es `xfail` estricto y
  hallazgo.
- P: ¿Qué integraciones se usan para tener dispositivos, reparaciones y flujos
  sin hardware ni internet? → R: **`kitchen_sink`** (la integración de
  demostración de Core: dispositivos que se pueden borrar a mano, avisos de
  reparación y un flujo de opciones) y **`uptime`** (flujo de configuración de
  un paso, sin datos, que crea una entrada con un dispositivo de servicio).
  Detalle en [research.md](research.md).
- P: ¿Hay alguna `ha_*` que no se pueda ejecutar en el banco? → R: **ninguna**
  a priori; si al implementar aparece una, va a la lista de no ejecutables
  con un motivo concreto y el supervisor lo revisa.

## Escenarios de usuario y pruebas *(obligatorio)*

### Historia 1 — Las escrituras de automatización, ejecución, eventos y Lovelace se ejecutan contra HA real (Prioridad: P1)

El mantenedor quiere saber que las tools que crean, editan, ejecutan, recargan
y borran automatizaciones, scripts y escenas, las que llaman a servicios o
lanzan eventos, la que cancela una espera y las de dashboards y recursos
Lovelace hacen en una HA real lo que dicen, comprobado por algo que no es
Hermes.

**Prueba independiente**: en el job del banco, cada una de las 26 tools de este
grupo se ejecuta (en dos pasos si pide token) y el lector independiente
encuentra en HA el efecto esperado.

**Escenarios de aceptación**:

1. **Dado** `ha_create_or_update_automation` sin token, **entonces** la vista
   previa no crea nada en HA; **cuando** se confirma, **entonces** el lector
   lee la configuración guardada en HA y ve la entidad `automation.*`.
2. **Dado** una automatización o un script cuya acción enciende un
   `input_boolean` creado por el lector, **cuando** se confirma
   `ha_trigger_automation` o `ha_run_script`, **entonces** el lector ve el
   `input_boolean` encendido.
3. **Dado** `ha_call_service` con un servicio de la denylist que no hace daño en
   el banco (`input_boolean.reload`), **entonces** la vista previa no llama al
   servicio y la confirmación lo llama una sola vez (el lector lo ve en el bus).
4. **Dado** un dashboard creado con `ha_create_lovelace_dashboard`, **cuando**
   se guarda su configuración con `ha_save_lovelace_dashboard`, **entonces** el
   lector lee de HA exactamente la configuración guardada.
5. **Dado** una espera abierta con `ha_wait_for_event`, **cuando** se llama a
   `ha_cancel_wait`, **entonces** la espera termina antes de su tope con el
   resultado de cancelada.

### Historia 2 — Las escrituras de registros, integraciones y reparaciones se ejecutan contra HA real (Prioridad: P1)

El mantenedor quiere lo mismo para las tools que crean, editan y borran áreas,
plantas, etiquetas y categorías; editan y borran dispositivos y entidades del
registro; ignoran avisos de reparación; y manejan config entries y sus flujos
de configuración y de opciones.

**Prueba independiente**: en el job del banco, cada una de las 27 tools de este
grupo se ejecuta y el lector encuentra el efecto en HA.

**Escenarios de aceptación**:

1. **Dado** `ha_start_config_entry_flow` con `uptime`, **cuando** se continúa
   con `ha_continue_config_entry_flow`, **entonces** el lector ve una config
   entry nueva de `uptime`; **cuando** se recarga, se deshabilita, se habilita y
   se borra con sus tools, **entonces** el lector ve cada cambio de estado y, al
   final, que la entrada ya no existe.
2. **Dado** un flujo abierto, **cuando** se llama a
   `ha_abort_config_entry_flow`, **entonces** el flujo ya no está en curso en HA.
3. **Dado** un dispositivo de `kitchen_sink`, **cuando** se confirma
   `ha_remove_device`, **entonces** el lector ya no lo encuentra en el registro.
4. **Dado** un aviso de reparación de `kitchen_sink`, **cuando** se confirma
   `ha_ignore_repair`, **entonces** el lector ve el aviso como ignorado.
5. **Dado** el flujo de opciones de `kitchen_sink`, **cuando** se completa con
   `ha_start_options_flow` y `ha_continue_options_flow`, **entonces** el lector,
   abriendo él mismo un flujo de opciones, ve los valores nuevos como los
   actuales.

### Historia 3 — Ninguna escritura queda sin probar o sin motivo (Prioridad: P1)

El mantenedor quiere un test de la suite normal que garantice que **todas** las
tools que modifican están en una de estas listas: probadas en el banco por la
010, probadas en el banco por la 028, no ejecutables en el banco con su motivo,
o fuera del banco (`fs_*` y `sv_*`) con su motivo. Una tool nueva que modifica
y no está en ninguna hace caer el test, que la nombra.

**Prueba independiente**: la suite normal (sin Docker) ejecuta el invariante
sobre el registro de producción y pasa; quitar una tool de su lista lo pone en
rojo nombrándola.

**Escenarios de aceptación**:

1. **Dado** el registro de producción con la configuración por defecto,
   **entonces** las 124 tools que modifican están clasificadas: 47 de la 010,
   53 de la 028 y 24 fuera del banco.
2. **Dado** una tool `ha_*` en la lista de fuera del banco, **entonces** el test
   falla: una `ha_*` solo puede no ejecutarse con un motivo concreto en la
   lista de no ejecutables.
3. **Dado** una tool de la lista de probadas de la 028 que ningún test del
   banco llama, **entonces** el test falla y la nombra.

### Historia 4 — Un fallo contra HA real se ve y no se esconde (Prioridad: P2)

Si una tool no hace en HA real lo que dice, el mantenedor quiere verlo como
hallazgo, con el CI en verde pero sin perderlo: el test queda marcado como fallo
esperado estricto, con el motivo, y si un día pasa el CI se pone en rojo para
quitar la marca.

**Prueba independiente**: el hallazgo de la 010 (`ha_reload_counters`) sirve
de patrón; un hallazgo nuevo de la 028 aparece en las notas del tramo, en el
informe al supervisor y en el propio test.

**Escenarios de aceptación**:

1. **Dado** una tool que falla contra HA real, **entonces** su test lleva
   `xfail` estricto con un motivo que dice qué devuelve HA, el comentario
   empieza por `HALLAZGO` y la tool sigue en la lista de probadas.
2. **Dado** ese test, **cuando** la tool empieza a funcionar, **entonces** el CI
   se pone en rojo («XPASS strict») y obliga a quitar la marca.

## Casos límite

- **Recursos compartidos entre tests**: `kitchen_sink` es uno para todo el
  banco. Cada test que borra un dispositivo usa uno distinto, ninguno borra la
  config entry de `kitchen_sink` y el aviso de reparación que se ignora se
  vuelve a dejar como estaba al terminar.
- **Una recarga que recrea lo borrado**: el flujo de opciones de
  `kitchen_sink` recarga la integración y puede volver a crear dispositivos
  borrados por otro test. Las comprobaciones de borrado se hacen justo después
  de confirmar, nunca al final del job.
- **Integración de un solo uso** (`uptime`): si ya hay una entrada, empezar el
  flujo aborta. El test de flujos la borra al terminar, pase lo que pase.
- **Automatización, script o escena que llama a un servicio peligroso**: los
  tests solo usan acciones inocuas (`input_boolean.turn_on`), para que Hermes no
  las marque como restringidas y no se mezclen dos comportamientos.
- **Dashboard sin guion en `url_path`**: HA lo rechaza; los nombres de prueba
  son `banco-<hex>`.
- **Recurso Lovelace con URL externa**: nunca; se usa una ruta local
  (`/local/banco-<hex>.js`), porque el contenedor no tiene salida a internet y
  porque el recurso solo se registra, no se descarga.
- **Servicios que reinician o paran HA** (`homeassistant.restart`,
  `homeassistant.stop`): no se llaman nunca, ni confirmados; el banco no
  sobreviviría y no prueban nada que no pruebe `input_boolean.reload`.
- **Espera cancelada**: su efecto vive en Hermes, no en HA; se comprueba con la
  propia espera, que termina antes de su tope (excepción justificada a la
  regla del lector, research R-7).
- **Restos de un test fallido**: nombres únicos `banco_<x>_<hex>` y limpieza por
  el lector al cerrar la sesión, como en la 010.

## Requisitos *(obligatorio)*

### Requisitos funcionales

Cada requisito cita el FR o la CAP de la spec 008 del que sale.

- **FR-001** *(008: FR-014, SC-006; CAP-034)*: En el banco se ejecutan de
  verdad las **53** tools `ha_*` de la 1.1.2 que modifican y no son de los 11
  dominios de helpers (lista en [data-model.md](data-model.md)). Las que piden
  `confirmation_token` se ejecutan en sus dos pasos y se comprueba que la vista
  previa no cambia HA. Cada ejecución comprueba su efecto con el **lector
  independiente** de la 010, salvo `ha_cancel_wait`, cuyo efecto está en
  Hermes (research R-7).
- **FR-002** *(008: FR-014)*: Las 53 se reparten en dos grupos por dominio, uno
  por tramo: **A** automatizaciones, scripts, escenas, servicios y eventos,
  esperas y Lovelace (26); **B** áreas, plantas, etiquetas, categorías,
  dispositivos, entidades, reparaciones, config entries y flujos (27).
- **FR-003** *(008: FR-014, historia 5)*: Un test de la suite normal comprueba
  que el conjunto de tools que **modifican** del registro de producción (las
  que no tienen `readOnlyHint` según `hermes/src/hermes/tools/_annotations.py`)
  es exactamente la unión, sin solapes, de: probadas en el banco por la 010,
  no ejecutables de la 010, probadas en el banco por la 028, no ejecutables de
  la 028 y fuera del banco. El mensaje de fallo nombra lo que sobra y lo que
  falta. Comprueba además que cada tool probada por la 028 aparece en algún
  test del banco de la 028.
- **FR-004** *(008: FR-014; CAP-034)*: La lista de **fuera del banco** solo
  contiene `fs_*` y `sv_*`, cada una con su motivo (5 `fs_*`: no hablan con HA
  y la suite normal las ejecuta contra ficheros reales; 19 `sv_*`: el
  Supervisor del banco es simulado y su banco es la 014). Una `ha_*` que no se
  pueda ejecutar va a la lista de **no ejecutables de la 028** con un motivo
  concreto (qué falta: hardware, internet, nube o Supervisor). Ningún motivo
  puede estar vacío.
- **FR-005** *(008: FR-013, FR-014)*: La configuración de HA del banco se amplía
  lo mínimo para estas tools: `automation:`, `script:` y `scene:` con sus
  ficheros YAML vacíos, `frontend:` (Lovelace y reparaciones) y
  `kitchen_sink:`. Nada que salga a internet ni datos de una instalación real;
  el contenedor sigue sin salida a la red exterior.
- **FR-006** *(008: FR-013)*: **El código de producto no cambia**, salvo un
  arreglo trivial (definido en «Clarificaciones») de una tool que falle contra
  HA real. El Supervisor simulado solo cambia si una de estas tools usa una
  ruta que no tiene; ninguna la usa hoy (research R-9).
- **FR-007** *(encargo del supervisor; 008: FR-014, principio VI)*: Una tool que
  falla contra HA real deja su test con **`xfail` estricto**
  (`strict=True`, `raises` con la excepción concreta y un `reason` que dice qué
  responde HA), un comentario que empieza por `HALLAZGO`, la tool en la lista de
  probadas y una nota en `tasks.md` y en el informe del tramo. Si el arreglo es
  trivial, se arregla en vez de marcarla, con su test unitario, su control
  negativo y su línea en el CHANGELOG.
- **FR-008** *(008: FR-014; principio III)*: Los tests son independientes:
  nombres únicos, limpieza por el lector al cerrar la sesión, comprobaciones
  por sondeo acotado (como mucho 10 s) y sin pausas fijas. Ningún test borra la
  config entry de `kitchen_sink`, la persona del usuario de onboarding ni lo
  que haya creado otro test, ni llama a servicios que reinician o paran HA.
- **FR-009** *(008: FR-018; principio VII)*: Controles negativos: en local,
  los del invariante de FR-003 (quitar una probada, poner una `ha_*` fuera del
  banco, vaciar un motivo); en el CI, uno por tramo que pone en rojo el test
  del banco correspondiente. Todos anotados en el commit del tramo.
- **FR-010** *(008: FR-022, FR-023)*: Documentación en el mismo cambio: la
  sección «Banco de pruebas» de la entrada `## [1.2.0]` de `hermes/CHANGELOG.md`
  con las 53 tools; la fila 028 de la tabla del programa en
  `docs/HOJA-DE-RUTA.md` («en curso» tras el tramo A, «hecha» tras el B), con
  la lista de tools ejecutadas en el banco, la de fuera del banco con su motivo
  y los hallazgos; y la columna de test de la fila CAP-034 de la matriz de
  `specs/008-cobertura-total/plan.md`. `README.md`, `README.es.md` y
  `hermes/DOCS.md` no cambian.
- **FR-011** *(008: FR-021; principio VIII)*: Datos de prueba genéricos
  (`banco_<x>_<hex>`, `banco-<hex>`, coordenadas y nombres de ejemplo); ninguna
  credencial nueva; las de la 010 siguen sin aparecer en logs ni salidas.
- **FR-012** *(008: plan, riesgo «imagen de Core grande o lenta»)*: El job
  `banco de Core` sigue por debajo de su tope de 20 min, cada test por debajo de
  120 s. Si el job pasa de 10 min en una ejecución normal, se anota y se
  propone repartirlo en varios jobs (sin hacerlo en esta sub-feature).

### Entidades clave

- **Inventario de escrituras de la 028**: probadas en el banco, no ejecutables
  con motivo y fuera del banco con motivo.
- **Configuración de HA del banco**: la de la 010 más los dominios de FR-005.
- **Recursos compartidos de prueba**: la config entry de `kitchen_sink`, sus
  dispositivos y sus avisos de reparación.
- **Hallazgo**: una tool que falla contra HA real, con su test en `xfail`
  estricto y su nota.

Detalle en [data-model.md](data-model.md).

## Supuestos

- **S-01**: El banco de la 010 (job, onboarding, Supervisor simulado, entorno,
  lector y `base_helpers`) está en la rama base y en verde. El tramo B de la
  010 puede integrarse después; la 028 no toca sus ficheros salvo para añadir
  métodos al lector y dominios a la configuración de HA.
- **S-02**: `kitchen_sink` y `uptime` vienen en la imagen de Core 2026.11.1 y
  cargan sin internet (código revisado en research R-1 y R-2). Si una no
  carga en el banco, las tools que dependen de ella pasan a no ejecutables con
  el motivo concreto y se avisa al supervisor; si carga y la tool falla, es un
  hallazgo como cualquier otro (FR-007).
- **S-03**: Ninguna de las 53 tools usa rutas del Supervisor ni comandos REST
  con `PUT` o `PATCH` (research R-9): el simulado de la 010 basta.
- **S-04**: Las tools nuevas de otras sub-features (011 y siguientes) se
  prueban en el banco en su propia sub-feature (FR-015 de la 008) y añaden su
  lista al invariante de FR-003 cuando se integran.

## Fuera de alcance

- Las 47 tools de helpers, la infraestructura del banco y su inventario: 010.
- Las `sv_*` y el banco del Supervisor, la VM y la matriz tool → entorno: 014.
- Las `fs_*` en el banco: no hablan con HA; se quedan en la suite normal.
- Las tools genéricas y las nuevas tools de Core: sus sub-features.
- Arreglar en el producto un fallo que no sea trivial: hallazgo para el
  supervisor.
- Repartir el banco en varios jobs.

## Criterios de éxito *(obligatorio)*

- **SC-001**: **53 de 53** tools se ejecutan en el banco contra HA Core
  2026.11.1 real: pasan con su efecto comprobado o están en `xfail` estricto
  con su hallazgo anotado; **0** tests del banco saltados.
- **SC-002**: El invariante de la suite normal clasifica **124 de 124** tools
  que modifican (47 + 53 + 24), sin solapes y sin motivos vacíos.
- **SC-003**: **0** líneas cambiadas en `hermes/src/` salvo arreglos triviales,
  cada uno con su test y su control negativo anotados.
- **SC-004**: En Windows sin Docker, la suite completa da exactamente los 6
  fallos conocidos y los tests del banco saltados con su motivo.
- **SC-005**: El job `banco de Core` nunca pasa de 20 minutos; en una
  ejecución normal termina en menos de 10 o, si no, la duración queda anotada
  con la propuesta de repartirlo (FR-012).
- **SC-006**: Cada tramo deja anotados sus controles negativos (locales y de
  CI) en su commit.
