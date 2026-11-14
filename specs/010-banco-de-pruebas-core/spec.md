# Especificación: banco de pruebas de Core (infraestructura y helpers)

**Directorio de la spec**: `specs/010-banco-de-pruebas-core`

**Creada**: 2026-11-14

**Estado**: Borrador

**Programa**: sub-feature 010 de la spec paraguas
[`specs/008-cobertura-total/`](../008-cobertura-total/spec.md) (tarea T003,
ola 0). Cubre **CAP-005** entera y la parte de **CAP-034** que toca a los 11
dominios de helpers; cumple **FR-013** y la parte de **FR-014** de esos
dominios. El resto de escrituras de Core en el banco es de la sub-feature 028;
el banco del Supervisor, de la 014.

**Entrada**: de las 124 tools que modifican, solo las de dashboards se han
ejecutado contra una HA real (1.1.2); el resto se verificó leyendo el código de
Hermes y el de Home Assistant y con simuladores que el propio proyecto escribe
(`tests/_ha_fixture.py`). Un simulador solo comprueba lo que su autor creía que
hace HA: ya ha pasado que el falso de helpers aceptaba actualizaciones
parciales que HA rechaza (comentario de `FakeCollectionStore`). El principio VI
pide que la suite corra «contra las mismas versiones que se despliegan»; para
Core, hasta ahora, no era así.

## Clarificaciones

### Sesión 2026-11-14

Decisión del supervisor del programa, vinculante:

- P: ¿Dónde corre HA? → R: **HA Core 2026.11.1 real, en contenedor, dentro del
  CI** (GitHub Actions; el repositorio es público y los runners estándar son
  gratis).
- P: ¿Cómo se conecta Hermes? → R: a través de un **Supervisor simulado
  mínimo** que vive en `tests/`, para que Hermes hable con HA por el mismo
  camino que en producción (`/core/api` y `/core/api/websocket` del
  Supervisor).
- P: ¿Se toca el código de producto? → R: **no**, salvo lo imprescindible y
  justificado (FR-013 de la 008). No hace falta nada: `HAClient` ya recibe la
  URL base del Supervisor como argumento (research R-4).
- P: ¿Es un check obligatorio? → R: **sí** (enmienda E-3 de la 008). El texto
  de la constitución lo cambia la 011, que es donde se aplican las enmiendas;
  aquí se deja el job listo, con nombre estable y sin `continue-on-error`.

Decisiones tomadas al especificar (el mantenedor no estaba; se anotan aquí en
lugar de preguntar):

- P: ¿Qué se hace con el onboarding? → R: **se completan los cuatro pasos**
  (usuario, configuración del núcleo, analytics e integración), como pide
  FR-013 de la 008 («completa el onboarding»), para que la instancia quede como
  una instalación real recién configurada. El paso de configuración del núcleo
  lanza en segundo plano integraciones que salen a internet (`met`,
  `radio_browser`, `google_translate`); para que el banco no dependa de
  internet, el contenedor de HA no tiene salida a la red exterior (research
  R-3).
- P: ¿Con qué token habla Hermes? → R: con un **token de add-on** aleatorio que
  solo conoce el Supervisor simulado, como en producción (`SUPERVISOR_TOKEN`).
  El simulado habla con Core con su propio token de larga duración, igual que
  el Supervisor real habla con Core con el suyo.
- P: ¿Cómo se comprueba el efecto? → R: con un **lector independiente** que
  habla directamente con Core (sin Hermes ni el Supervisor simulado), para no
  comprobar Hermes con el propio Hermes.
- P: ¿Qué pasa en una máquina sin Docker? → R: los tests del banco **se
  saltan** con un motivo que dice qué falta y dónde corren. En el job del banco
  un salto es un **fallo**: el job no puede quedar verde sin haber ejecutado
  nada.
- P: ¿Qué tools entran aquí? → R: las **47** tools que modifican de los 11
  dominios de helpers (`input_boolean`, `input_button`, `input_datetime`,
  `input_number`, `input_select`, `input_text`, `counter`, `timer`, `schedule`,
  `zone`, `person`). El resto de escrituras `ha_*` de la 1.1.2 son de la 028.

## Escenarios de usuario y pruebas *(obligatorio)*

### Historia 1 — El CI arranca una HA real y Hermes se conecta a ella como en producción (Prioridad: P1)

El mantenedor quiere que cada push y cada PR arranquen HA Core 2026.11.1 de
verdad y que Hermes se conecte a ella por el mismo camino que en un add-on:
ping al Supervisor, versión de Core por `/core/info`, REST y WebSocket por el
proxy del Supervisor. Si algo de eso falla, el CI se pone en rojo.

**Prueba independiente**: un push a la rama ejecuta el job del banco; los tests
de humo pasan: el Supervisor simulado responde al ping, `/core/info` da
`2026.11.1`, Hermes autentica la WebSocket a través del proxy, lee estados y
llama a un servicio.

**Escenarios de aceptación**:

1. **Dado** un push a cualquier rama o un PR, **entonces** el CI arranca HA
   Core 2026.11.1 con la imagen fijada por digest, completa el onboarding sin
   intervención humana y ejecuta los tests del banco.
2. **Dado** el banco arrancado, **cuando** Hermes comprueba la versión de Core
   como al arrancar, **entonces** obtiene `2026.11.1`, que es igual a
   `HA_CORE_LAST_TESTED`.
3. **Dado** el banco arrancado, **cuando** se crea el cliente de HA de Hermes
   con la URL del Supervisor simulado y el token de add-on, **entonces** la
   WebSocket queda autenticada y las tools responden por el servidor MCP real.
4. **Dado** un token de add-on incorrecto, **entonces** el Supervisor simulado
   responde 401 en REST y `auth_invalid` en la WebSocket, como el real.
5. **Dado** que HA no arranca o no se completa el onboarding, **entonces** el
   job falla con un mensaje que dice en qué paso y muestra el final del log de
   HA, sin credenciales.

### Historia 2 — Las escrituras de helpers se ejecutan de verdad y se comprueba su efecto (Prioridad: P1)

El mantenedor quiere saber que las 47 tools que modifican helpers hacen en una
HA real lo que dicen: crear, editar, borrar, cambiar el valor, recargar. Y que
lo comprueba algo que no es Hermes.

**Prueba independiente**: en el job del banco, cada una de las 47 tools se
ejecuta (en dos pasos si pide token) y el lector independiente encuentra en HA
el efecto esperado; un test local comprueba que no hay ninguna tool de
escritura de esos dominios sin su prueba en el banco.

**Escenarios de aceptación**:

1. **Dado** `ha_create_or_update_input_boolean` sin token, **entonces** la
   vista previa no crea nada en HA; **cuando** se confirma con el token,
   **entonces** el lector independiente encuentra el helper con la
   configuración pedida.
2. **Dado** un helper creado, **cuando** se ejecutan sus acciones (`set`,
   `toggle`, `increment`, `press`, `start`…), **entonces** el lector
   independiente ve el estado esperado en HA.
3. **Dado** una tool `ha_reload_*`, **cuando** se confirma, **entonces** HA
   ejecuta el servicio `<dominio>.reload` (el lector lo ve en el bus de
   eventos) y los helpers creados siguen ahí.
4. **Dado** `ha_delete_*` confirmado, **entonces** el helper ya no existe en
   HA.
5. **Dado** una tool nueva de escritura en uno de los 11 dominios sin prueba en
   el banco, **entonces** un test de la suite normal falla y la nombra.

### Historia 3 — Quien no tiene Docker sigue trabajando (Prioridad: P2)

Quien ejecuta la suite en su máquina (Windows, sin Docker) quiere que los tests
del banco no fallen ni se cuelguen, y que el motivo del salto diga qué hace
falta. Las piezas que no necesitan HA (Supervisor simulado, onboarding,
comprobaciones del workflow) se prueban igual en local.

**Prueba independiente**: la suite completa en Windows sin variables del banco
da los mismos fallos conocidos que hoy, más los tests del banco saltados con
su motivo.

**Escenarios de aceptación**:

1. **Dado** una máquina sin las variables del banco, **entonces** cada test del
   banco se salta con un motivo que nombra la variable que falta y el job del
   CI donde corre.
2. **Dado** el job del banco (variable de obligatoriedad activa) sin HA
   configurada, **entonces** el test falla en vez de saltarse.
3. **Dado** el banco configurado pero HA inalcanzable, **entonces** el test
   falla con el motivo, nunca se salta.

### Historia 4 — El banco no filtra credenciales (Prioridad: P2)

El repositorio es público y los logs del CI también. Quien lo mantiene quiere
que la contraseña del usuario de onboarding, el token de Core y el token de
add-on no aparezcan en ningún log, salida de test ni fichero versionado.

**Prueba independiente**: un test captura el log de un arranque completo del
banco (onboarding, Supervisor simulado y Hermes) y no encuentra ninguna de las
credenciales generadas.

**Escenarios de aceptación**:

1. **Dado** un arranque del banco, **entonces** ni la contraseña ni los tokens
   aparecen en el log capturado ni en los mensajes de error.
2. **Dado** un fallo del onboarding, **entonces** el mensaje dice el paso y el
   código HTTP, nunca el cuerpo de la petición.

## Casos límite

- **Core tarda en arrancar**: el HTTP de HA responde antes de que terminen de
  cargarse las integraciones. El banco espera a `state: RUNNING` en
  `/api/config` antes de cualquier test (research R-6).
- **Onboarding ya hecho** (reejecución sobre la misma instancia): el paso
  devuelve 403 «already done»; con un contenedor nuevo por job no ocurre, y si
  ocurre es un fallo explícito, no un salto.
- **Descarga de la imagen fallida** por un problema de red puntual: hasta 3
  intentos con espera creciente; después, fallo del job.
- **Un test deja helpers creados** (fallo a mitad): cada test usa nombres
  únicos y limpia en su `tearDown` por el lector independiente; un resto no
  afecta a otros tests.
- **Vista previa que no debería tocar HA**: se comprueba que, tras la primera
  llamada sin token, el lector no ve el cambio.
- **El token de acceso de Core caduca a los 30 min**: por eso el simulado usa
  un token de larga duración (research R-3).
- **Hermes llama a una ruta del Supervisor que el simulado no tiene**: el
  simulado responde 404 con el formato de error del Supervisor; el test falla y
  la ruta queda a la vista, en vez de pasar por un camino que producción no
  tiene.
- **Comando WebSocket reservado** (`supervisor/…`, `hassio/…`) o ruta REST
  `hassio…`: el simulado los rechaza como el real (research R-5).
- **Método REST que el proxy real no admite** (`PUT`, `PATCH`): el simulado
  responde 405, como el real.
- **Desfase de versión**: si se cambia `HA_CORE_LAST_TESTED` sin cambiar la
  imagen (o al revés), un test local falla.

## Requisitos *(obligatorio)*

### Requisitos funcionales

Cada requisito cita el FR o la CAP de la spec 008 del que sale.

- **FR-001** *(008: FR-013; CAP-005)*: El CI tiene un job, `banco-core`, que
  arranca **HA Core 2026.11.1** con la imagen oficial
  `ghcr.io/home-assistant/home-assistant` fijada por **digest** (índice
  multiplataforma), con la etiqueta igual a `HA_CORE_LAST_TESTED` de
  `hermes/src/hermes/config.py`. Un test de la suite normal comprueba que la
  imagen del workflow lleva digest `sha256` de 64 hexadecimales y que su
  etiqueta coincide con `HA_CORE_LAST_TESTED`.
- **FR-002** *(008: FR-013, FR-021)*: La configuración de HA del banco está
  versionada en `tests/banco/` y es mínima: los 11 dominios de helpers, lo que
  necesitan la API, la WebSocket y el onboarding, ubicación y zona horaria
  genéricas. Solo marcadores genéricos; nada de una instalación real. El
  contenedor de HA no tiene salida a la red exterior; solo el runner llega a
  su puerto, publicado en `127.0.0.1`.
- **FR-003** *(008: FR-013)*: El onboarding se completa de forma automática:
  usuario administrador, configuración del núcleo, analytics e integración, en
  ese orden; con el código de autorización se obtiene un token de acceso y,
  con él, un **token de larga duración** por WebSocket. Usuario, contraseña y
  tokens se generan en el propio job con un generador criptográfico, viven
  solo en memoria del proceso de tests y nunca se guardan, se imprimen ni se
  registran.
- **FR-004** *(008: FR-013)*: El **Supervisor simulado** vive en `tests/banco/`
  y ofrece solo lo que Hermes necesita: `GET /supervisor/ping`,
  `GET /core/info` (con la versión que da Core), el proxy REST
  `/core/api/{ruta}` (solo `GET`, `POST` y `DELETE`, como el real) y el proxy
  WebSocket `/core/api/websocket` (y su alias `/core/websocket`). Exige el
  token de add-on (`Authorization: Bearer` en REST; fase `auth` propia en la
  WebSocket, con `auth_ok`/`auth_invalid` y la versión de Core, como el real) y
  habla con Core con el token de larga duración. Rechaza como el real los
  comandos WebSocket `supervisor/…` y `hassio/…` y las rutas REST `hassio…`.
  Cualquier otra ruta responde 404 con el formato de error del Supervisor.
- **FR-005** *(008: FR-013)*: Hermes se conecta **como en producción**: el
  ping y la comprobación de versión usan las funciones de arranque de
  `hermes/src/hermes/network.py`; el cliente es `HAClient` con
  `supervisor_base_url` igual a la URL del Supervisor simulado y
  `supervisor_token` igual al token de add-on; las tools se registran con el
  cableado de producción (`_build_mcp` de `hermes/src/hermes/__main__.py`
  con la configuración por defecto) y se invocan por un cliente MCP en memoria.
- **FR-006** *(008: FR-013)*: **El código de producto no cambia**: ningún
  fichero de `hermes/` se modifica en esta sub-feature salvo
  `hermes/CHANGELOG.md` (documentación, FR-013). Si algún cambio
  resultase imprescindible, se justifica en el plan y nunca abre una vía nueva
  en producción (por ejemplo, una variable que cambie la URL base).
- **FR-007** *(decisión del supervisor; 008: CAP-005)*: Sin las variables del
  banco, cada test del banco **se salta** con un motivo que nombra la variable
  que falta y el job donde corre. Con la variable de obligatoriedad activa (la
  pone el job), su ausencia es un **fallo**. Con el banco configurado, HA
  inalcanzable o un onboarding fallido son un **fallo**, nunca un salto. Las
  piezas que no necesitan HA (Supervisor simulado, onboarding, comprobaciones
  del workflow, inventario de cobertura) se prueban en la suite normal contra
  dobles locales, en cualquier sistema operativo.
- **FR-008** *(008: FR-014; CAP-034, parte de helpers)*: En el banco se
  ejecutan de verdad las **47** tools que modifican de los 11 dominios de
  helpers (lista en [data-model.md](data-model.md)). Las que piden
  `confirmation_token` se ejecutan en sus dos pasos y se comprueba que la
  vista previa no cambia HA. Cada ejecución comprueba su efecto con el
  **lector independiente**, que habla directamente con Core con el token de
  larga duración, sin pasar por Hermes ni por el Supervisor simulado.
- **FR-009** *(008: FR-014)*: Un test de la suite normal comprueba que el
  conjunto de tools que modifican de los 11 dominios (las del registro de
  producción que no son de solo lectura) es exactamente el conjunto de tools
  probadas en el banco más las listadas como no ejecutables con su motivo. Hoy
  esa lista de no ejecutables está vacía.
- **FR-010** *(008: plan, flujo puerta 4 y enmienda E-3)*: El job del banco se
  ejecuta en los mismos eventos que `Tests` (push, pull request y la ejecución
  semanal), no tiene `continue-on-error` y su nombre de check es estable
  (`banco de Core`), para que pueda figurar en los checks obligatorios. Añadirlo
  a los checks obligatorios del ruleset del repositorio es una acción del
  mantenedor; nombrarlo en la constitución es la enmienda E-3, que aplica la
  011.
- **FR-011** *(008: plan, riesgos «imagen de Core grande o lenta»)*: Tiempos y
  reintentos acotados: descarga de la imagen con hasta 3 intentos; espera al
  HTTP de HA de hasta 300 s y a `state: RUNNING` de hasta 180 s; tope por test
  de 120 s; tope del job de 20 min. Los tests no se reintentan. Cuando el job
  falla, muestra las últimas líneas del log de HA. Las comprobaciones de
  efecto esperan con sondeo acotado (como mucho 10 s), nunca con pausas fijas.
- **FR-012** *(008: FR-019, FR-021; principio II)*: Ninguna credencial del
  banco (contraseña del usuario, token de acceso, token de larga duración,
  token de add-on) aparece en el log, en la salida de los tests, en los
  mensajes de error ni en ficheros del repositorio. Un test con el log
  capturado lo comprueba sobre un arranque completo del banco, y otro, en la
  suite normal, sobre el onboarding contra un doble.
- **FR-013** *(008: FR-022, FR-023)*: Documentación en el mismo cambio: sección
  «Banco de pruebas» en la entrada `## [1.2.0]` de `hermes/CHANGELOG.md`; fila
  de la 010 a «hecha» en la tabla del programa de `docs/HOJA-DE-RUTA.md`, con
  la lista de tools de helpers ejecutadas en el banco y la frase de la
  cabecera sobre «las 124 tools que modifican» al día; `CONTRIBUTING.md` y
  `CONTRIBUTING.es.md` explican el check nuevo y cómo correr el banco en local
  con Docker. `README.md`, `README.es.md` y `hermes/DOCS.md` no cambian: no
  hay opciones ni comportamiento nuevos para el usuario.
- **FR-014** *(008: FR-018; principio VII)*: Cada requisito tiene su test de
  regresión, y cada pieza con riesgo, su control negativo comprobado y
  anotado: los de la suite normal en local; los del banco, con un push de
  control a una rama desechable que el CI pone en rojo (research R-9).

### Entidades clave

- **Instancia del banco**: el contenedor de HA Core del job, con su
  configuración versionada y su URL en `127.0.0.1`. Vive lo que dura el job.
- **Credenciales efímeras**: usuario y contraseña de onboarding, token de
  acceso, token de larga duración y token de add-on. Solo en memoria.
- **Supervisor simulado**: servidor HTTP local con las rutas de FR-004.
- **Lector independiente**: cliente directo a Core para comprobar efectos.
- **Inventario de cobertura**: la lista de tools de helpers probadas en el
  banco y la de no ejecutables con motivo.

Detalle en [data-model.md](data-model.md).

## Supuestos

- **S-01**: Los runners Linux estándar de GitHub tienen Docker y `sudo`, y son
  gratis sin límite de minutos en repositorios públicos (008, S-03).
- **S-02**: La imagen 2026.11.1 pesa unos 640 MiB comprimidos (amd64) y Core,
  con una configuración mínima, llega a `RUNNING` en menos de un minuto.
- **S-03**: El Supervisor simulado solo tiene que cubrir lo que usan Hermes al
  arrancar y las tools de helpers; las rutas del Supervisor que necesiten la
  028 u otras sub-features las añadirán ellas (008, S-04).
- **S-04**: Los helpers no usan el Supervisor (ni safety backups ni
  `sv_request`): sus recargas son una llamada a servicio (research R-7).
- **S-05**: Las capas HTTP y OAuth de Hermes no intervienen en la conexión con
  HA; se siguen probando en la suite normal. El banco invoca las tools por el
  servidor MCP real en memoria.

## Fuera de alcance

- Las escrituras `ha_*` que no son de helpers (automatizaciones, scripts,
  escenas, registros, Lovelace, flujos de config entries, servicios, eventos,
  temporizadores de espera): sub-feature 028.
- El banco del Supervisor, la VM con HAOS y la matriz tool → entorno: 014.
- Las tools genéricas y las nuevas tools de Core: sus sub-features (011 y
  siguientes) las ejecutan en este banco (FR-015 de la 008).
- Ejecutar el banco contra la versión mínima declarada (D-05 de la 008).
- Cambiar el texto de la constitución (E-3): 011.
- Editar el ruleset del repositorio: lo hace el mantenedor.
- El contenedor del add-on entero contra el banco (research R-4, opción c).

## Criterios de éxito *(obligatorio)*

- **SC-001**: En la punta de la rama, el job del banco está en verde y ha
  ejecutado los tests de humo y los de las 47 tools, con **0** tests del banco
  saltados.
- **SC-002**: **47 de 47** tools que modifican de los 11 dominios de helpers se
  han ejecutado contra HA Core 2026.11.1 real con su efecto comprobado por el
  lector independiente. (Convergencia, T038: queda en 46 de 47;
  `ha_reload_counters` falla contra HA real porque Core no tiene
  `counter.reload`, y su arreglo es de la spec 033.)
- **SC-003**: **0** líneas cambiadas en `hermes/` en el diff de la
  sub-feature, salvo `hermes/CHANGELOG.md`.
- **SC-004**: En Windows sin Docker, la suite completa da exactamente los 6
  fallos conocidos y los tests del banco saltados con su motivo.
- **SC-005**: Ninguna de las credenciales generadas aparece en el log ni en la
  salida de un arranque completo del banco.
- **SC-006**: El job del banco tarda menos de 10 minutos en una ejecución
  normal (con la descarga de la imagen incluida) y nunca más de 20.
- **SC-007**: Cada requisito tiene su test, y los controles negativos
  (locales y de CI) están anotados en los commits de los tramos.
