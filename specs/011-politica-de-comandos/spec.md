# Especificación: Hermes 1.2.0 — política de comandos, tools genéricas y familias (sub-feature 011)

**Directorio de la spec**: `specs/011-politica-de-comandos`

**Creada**: 2026-11-14

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T004 de su `tasks.md` y cubre **CAP-001, CAP-002,
CAP-003, CAP-004, CAP-007 y CAP-008** (FR-001…FR-012 de la 008). Es la pieza
central del programa: las sub-features de tools dedicadas (012 en adelante)
dependen de ella.

**Entrada**: `specs/008-cobertura-total/` (spec, plan con la arquitectura y
las enmiendas E-1…E-4, research R-2, R-4 y R-5, e inventarios
`inventario/core-ws.tsv` y `inventario/supervisor-rutas.tsv`) y el código de
Hermes 1.1.2: registro de tools (`tools/__init__.py`), anotaciones
(`tools/_annotations.py`), confirmación en dos pasos con la resolución de la
1.1.2 (`security.py`), denylist (`service_policy.py`), tope de respuesta
(`mcp_server.py` y `tools/_common.py`), redacción (`security.py`) y el cliente
de Core y del Supervisor (`ha.py`).

## Clarificaciones

### Sesión 2026-11-14

Decisiones del mantenedor y del supervisor del programa, vinculantes (ya están
en la 008):

- Tabla de clasificación versionada dentro de Hermes, generada desde
  `specs/008-cobertura-total/inventario/`, con cuatro categorías: `dedicated`
  (se rechaza con una pista a la tool dedicada), `read`, `confirm` y `deny`
  (la clase B y la D, y lo «pendiente de tool dedicada» hasta que exista).
- Un comando o una ruta desconocidos se rechazan (fail-closed).
- Cuatro tools genéricas, separadas en lectura y escritura, para el WebSocket
  de Core y para la API del Supervisor. La de lectura lleva `readOnlyHint`; la
  de escritura confirma siempre, con una vista previa del comando y un resumen
  de la carga con una regla medible.
- Test de verbos de escritura con la lista explícita de FR-004 de la 008 y test
  de deriva entre la tabla y el inventario.
- Familias de tools desactivables con una opción de configuración; todas
  activas por defecto; las tools nuevas en familias distintas de las de la
  1.1.2, para que desactivándolas queden exactamente las 216 de hoy.
- Guía (`hermes_guide`) y documentación.
- Las enmiendas E-1…E-4 de la constitución se aplican en esta sub-feature,
  antes del código.

Decisiones tomadas al especificar (no había a quién preguntar; se anotan aquí
y se justifican en [research.md](research.md)):

- P: ¿Dónde vive la tabla? → R: en un **módulo Python de datos** generado,
  `hermes/src/hermes/command_table.py`, con la lógica de consulta y las guardas
  en un módulo neutral aparte, `hermes/src/hermes/command_policy.py` (al estilo
  de `service_policy.py`). Sin ficheros de datos que leer de disco: la tabla
  se valida al importar, se revisa en el diff línea a línea y admite
  comentarios con el porqué de cada excepción (research R-1).
- P: ¿Cómo se genera y se mantiene? → R: un **generador** versionado en
  `scripts/inventario/` (fuera del paquete del add-on) crea la tabla la
  primera vez a partir de los inventarios y de las reglas de FR-002, y en
  versiones siguientes **conserva** las entradas revisadas, añade las filas
  nuevas del inventario como `deny` con el motivo «sin revisar» y quita las que
  ya no existen, diciendo cuáles. Después de generar, la tabla es la fuente de
  verdad y se revisa a mano. Un test impide que quede ninguna entrada «sin
  revisar» (research R-2).
- P: ¿El inventario del Supervisor tiene una fila por ruta? → R: hoy no (217
  filas para 254 rutas: alias y variantes de log agrupados). Se **normaliza**
  a una fila por método y ruta, con las columnas que ya tiene, en el mismo
  sitio (`specs/008-cobertura-total/inventario/supervisor-rutas.tsv`). El
  extractor lo genera ya así (research R-3).
- P: ¿Cómo se clasifica en la tabla inicial la clase C (192 comandos)? → R:
  **`deny` con el motivo «pendiente de revisión (spec 025)»**. La 008 manda
  clasificarla «uno a uno» en la 025 (FR-089 de la 008), y una clasificación
  provisional por verbo podría abrir con un solo token comandos que borran la
  red o devuelven claves (principio III). La 025 la pasa a `read`/`confirm`/
  `deny`, y el cierre del programa exige que no quede ningún motivo
  «pendiente» (research R-4).
- P: ¿Y la clase A cuya CAP va por la tabla (vía T en la matriz de la 008)? →
  R: se clasifica aquí, `read` o `confirm` según su efecto, revisando cada
  comando (53 de Core y las rutas del Supervisor de CAP-088, 089, 091, 092 y
  094). Lo de vía D, D+T o D+X queda `deny` «pendiente de tool dedicada
  (spec NNN)»; la sub-feature dedicada pasa a `read`/`confirm` lo que de su CAP
  vaya por la tabla.
- P: ¿Qué familia tiene una entrada que no es `dedicated`? → R: la de las
  genéricas, `generic_commands`, salvo que una sub-feature posterior le asigne
  otra suya. Si la familia de una entrada `read` o `confirm` está desactivada,
  la genérica la rechaza con `family_disabled` (desactivar una familia apaga su
  capacidad por cualquier vía).
- P: ¿La carga de `ha_call_ws_command` y el cuerpo de `sv_call_api` se pueden
  omitir al confirmar, como el documento de la 1.1.2? → R: **no**. Se confirma
  con los mismos argumentos; el token se resuelve con
  `resolve_confirmation_token` sin omitibles. Motivo: la carga de una genérica
  puede llevar contraseñas y no se escribe en disco (lo mismo que se decidió
  para `sv_set_addon_options` en la 007), y las cargas de comandos son
  pequeñas.
- P: ¿Cómo se consulta la tabla desde la guía? → R: con un argumento opcional
  nuevo, `hermes_guide(topic="generic_commands", search=…)`, que lista las
  entradas que casan con el texto (comando, integración, área de ruta, CAP o
  familia). Argumento opcional: sin él, `hermes_guide` responde como en la
  1.1.2.
- P: ¿Nombre de la opción? → R: `tool_families_disabled` (lista de nombres de
  familia), por defecto vacía.

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es el administrador de Home Assistant que trabaja desde un cliente
MCP, y el mantenedor de Hermes, que mantiene la tabla en cada versión de HA.

### Historia 1 — La cola larga es alcanzable por las genéricas (Prioridad: P1)

Quien administra su casa quiere poder leer y, con confirmación, cambiar lo que
HA ofrece y no tiene tool propia en Hermes, sin encontrarse con «Hermes no
tiene eso».

**Prueba independiente**: con un HA simulado, un comando `read` de la tabla
devuelve la respuesta de HA recortada y redactada; un comando `confirm` da una
vista previa con token y solo se ejecuta al confirmar.

**Escenarios de aceptación**:

1. **Dado** un comando `read` (por ejemplo, la lista de tags), **cuando** el
   agente llama a `ha_read_ws_command` con él, **entonces** recibe la respuesta
   de HA recortada al tope y redactada.
2. **Dado** un comando `confirm`, **cuando** el agente llama a
   `ha_call_ws_command` sin token, **entonces** recibe una vista previa con el
   comando, su categoría y motivo, el resumen de la carga y un token, y HA no
   recibe nada; **cuando** repite la llamada con el token, **entonces** HA
   recibe el comando una sola vez.
3. **Dado** una ruta `read` del Supervisor (por ejemplo, la información de un
   plugin), **cuando** el agente llama a `sv_read_api`, **entonces** recibe la
   respuesta recortada y redactada.
4. **Dado** un comando que HA 2026.11.1 tiene y la HA instalada no, **cuando**
   se pide, **entonces** la respuesta dice que HA no lo conoce, con el código
   de HA, y no parece un fallo de Hermes.

### Historia 2 — Ninguna vía nueva se salta una protección (Prioridad: P1)

Quien confía en las vistas previas y en las protecciones de las tools
dedicadas quiere que las genéricas no abran un camino alrededor de ellas.

**Prueba independiente**: ningún comando `dedicated`, `deny` o desconocido, ni
ninguna ruta peligrosa, llega a HA o al Supervisor por una genérica; un token
de la genérica no sirve para otro comando ni para otra carga.

**Escenarios de aceptación**:

1. **Dado** un comando con tool dedicada (por ejemplo, guardar un dashboard),
   **cuando** se pide por cualquier genérica, **entonces** se rechaza con
   `use_dedicated_tool` y el nombre de la tool, sin llegar a HA.
2. **Dado** un comando de clase D o B, **entonces** se rechaza con
   `command_denied` y su motivo.
3. **Dado** un comando que no está en la tabla, **entonces** se rechaza con
   `command_not_classified`.
4. **Dado** un comando `confirm` pedido por la genérica de lectura (o uno
   `read` por la de escritura), **entonces** se rechaza indicando la otra
   genérica.
5. **Dado** un token emitido para un comando y una carga, **cuando** se
   confirma con otro comando u otra carga, **entonces** se rechaza y no llega
   nada a HA.
6. **Dado** `sv_read_api` o `sv_call_api` con una ruta que intenta salir de la
   API (`..`, `%2e`, esquema u host, consulta o fragmento) o que apunta al
   proxy de Core (`/core/api…`) o al propio Hermes, **entonces** se rechaza
   antes de llamar al Supervisor.
7. **Dado** una carga con una contraseña, **entonces** la vista previa, el
   error, el log y el fichero del token no contienen la contraseña.

### Historia 3 — La tabla no se queda atrás (Prioridad: P1)

El mantenedor quiere que una versión nueva de HA no abra puertas sin revisar y
que ningún error de clasificación convierta una escritura en lectura.

**Prueba independiente**: con un inventario que tiene un comando que la tabla
no tiene (o al revés), el test de deriva falla y lo nombra; con un comando de
escritura clasificado `read`, el test de verbos falla y lo nombra.

**Escenarios de aceptación**:

1. **Dado** un comando nuevo en el inventario, **entonces** el test de deriva
   falla con su nombre y la genérica lo rechaza.
2. **Dado** una entrada de la tabla que ya no está en el inventario,
   **entonces** el test de deriva falla con su nombre.
3. **Dado** un comando con un verbo de escritura (o una ruta con método
   distinto de `GET`) clasificado `read` y fuera de la lista de excepciones,
   **entonces** el test de verbos falla con su nombre.
4. **Dado** el código fuente de una versión nueva de HA, **cuando** el
   mantenedor ejecuta el extractor y el generador, **entonces** obtiene los
   inventarios actualizados y la tabla con las filas nuevas como `deny` «sin
   revisar», y un test le impide cerrar sin revisarlas.

### Historia 4 — Nada de lo que funciona hoy cambia (Prioridad: P1)

Quien usa Hermes 1.1.2 quiere actualizar sin cambiar su cliente ni su
configuración.

**Prueba independiente**: con la configuración por defecto, las 216 tools de la
1.1.2 siguen con el mismo nombre y las mismas anotaciones; con la familia de
las genéricas desactivada, la lista es exactamente la de la 1.1.2.

**Escenarios de aceptación**:

1. **Dado** una configuración de la 1.1.2 sin la opción de familias,
   **entonces** Hermes arranca con todas las familias activas.
2. **Dado** `tool_families_disabled: [generic_commands]`, **entonces** la lista
   de tools es exactamente la de la 1.1.2, con las mismas anotaciones.
3. **Dado** `hermes_guide(topic)` sin el argumento nuevo, **entonces** responde
   lo mismo que en la 1.1.2 para los temas de la 1.1.2.

### Historia 5 — Menos contexto para quien no lo necesita (Prioridad: P2)

Quien usa un cliente con pocas tools o poco contexto quiere desactivar las
familias que no usa.

**Prueba independiente**: con una familia desactivada, sus tools no se
registran y las genéricas siguen rechazando sus comandos, diciendo que la
familia está desactivada.

**Escenarios de aceptación**:

1. **Dado** una familia desactivada, **entonces** ninguna de sus tools aparece
   en la lista y el log de arranque dice cuáles se desactivaron.
2. **Dado** un comando `dedicated` cuya tool es de una familia desactivada,
   **cuando** se pide por una genérica, **entonces** se rechaza con
   `use_dedicated_tool`, el nombre de la tool y `family_disabled: true`.
3. **Dado** un nombre de familia que no existe en la opción, **entonces**
   Hermes no arranca y el log dice qué nombre es inválido y cuáles valen.

### Historia 6 — El agente sabe qué puede pedir (Prioridad: P2)

Quien usa las genéricas quiere saber qué comandos hay para una integración o un
tema, sin adivinar.

**Prueba independiente**: `hermes_guide(topic="generic_commands",
search="tag")` lista los comandos de tags con su categoría y, si los hay, su
tool dedicada y un ejemplo de carga que esté en la tabla.

**Escenarios de aceptación**:

1. **Dado** una búsqueda que casa con varias entradas, **entonces** la guía las
   lista con categoría, tool dedicada o motivo, y ejemplo de carga solo si la
   tabla lo tiene.
2. **Dado** una búsqueda sin resultados, **entonces** la guía lo dice y cómo
   buscar.
3. **Dado** el índice de la guía, **entonces** menciona el tema de las
   genéricas y cuándo usar una genérica en vez de una tool dedicada.

### Casos límite

- Carga de `ha_*_ws_command` que no es un objeto, o que trae `id` o `type`:
  `invalid_argument`, sin llegar a HA (`id` y `type` los pone Hermes).
- `type` con forma imposible (mayúsculas, espacios, más de 128 caracteres):
  `invalid_argument`; el log no copia el texto.
- Suscripción `read` de un solo mensaje: se lee el primer evento con tope de
  tiempo y se cancela siempre, también con error o timeout.
- Respuesta mayor que `response_max_bytes`: recorte con `truncated` si es una
  lista, o `response_too_large`, como el resto de tools.
- Vista previa de `ha_call_ws_command`/`sv_call_api` que no cabe en
  `response_max_bytes`: se rechaza sin token (`preview_too_large`); nunca se
  emite un token sobre una vista previa recortada.
- Plantilla de ruta ambigua (una ruta concreta casa con un segmento literal y
  con un parámetro): gana el literal; si dos plantillas casan con el mismo
  número de literales, `command_not_classified`.
- Ruta concreta con un parámetro vacío o con caracteres fuera de
  `[A-Za-z0-9._-]`: no casa con ninguna plantilla.
- Ruta de respuesta de texto (logs de plugins): se devuelve por líneas, con las
  últimas que quepan y la redacción de secretos y de red de los logs.
- Core caído: las genéricas de Core fallan con el error de conexión de siempre;
  las del Supervisor siguen funcionando.
- `tool_families_disabled` con la familia `base` (`ping`, `hermes_guide`): no
  arranca; esa familia no se puede desactivar.
- Familia desactivada cuyos comandos son `dedicated`: siguen siendo `dedicated`
  en la tabla; la genérica no es una vía alternativa.

## Requisitos *(obligatorio)*

Cada requisito cita entre paréntesis los FR de la 008 y las CAP que cubre.

### Requisitos funcionales

#### Tabla de clasificación

- **FR-001**: Hermes incluye una **tabla de clasificación** versionada con una
  entrada por cada comando WebSocket del inventario de Core (623) y por cada
  método + plantilla de ruta del inventario del Supervisor (254). Cada entrada
  tiene categoría (`dedicated`, `read`, `confirm` o `deny`), motivo, familia,
  la tool dedicada cuando la categoría es `dedicated`, la CAP cuando la tiene y
  las marcas de ejecución: suscripción de un solo mensaje, respuesta de texto,
  claves extra que redactar, si sale a internet y un ejemplo de carga opcional.
  La tabla lleva las versiones de Core y del Supervisor de las que sale (008
  FR-001; CAP-001).
- **FR-002**: Clasificación inicial: lo cubierto hoy → `dedicated` con la tool
  que lo cubre (lo cubierto por acción genérica, a `ha_call_service`; lo que
  Hermes solo usa por dentro y ninguna tool expone, `deny` «uso interno de
  Hermes»); clase B → `deny` con el motivo de su grupo; clase D → `deny` con su
  motivo; clase A cuya CAP va por tool dedicada (vía D, D+T o D+X de la matriz
  de la 008) → `deny` «pendiente de tool dedicada (spec NNN)»; clase A cuya CAP
  va por la tabla (vía T) → `read` o `confirm` según su efecto, revisado comando
  a comando; clase C → `deny` «pendiente de revisión (spec 025)»; cualquier
  ruta `/core/api*` y `/homeassistant/api*` → `deny`, aunque el inventario la
  dé por cubierta (esta regla prevalece sobre las demás) (008 FR-002;
  CAP-001).
- **FR-003**: **Fail-closed**: un comando o una ruta que no está en la tabla se
  rechaza con `command_not_classified`; uno `deny`, con `command_denied` y su
  motivo; uno `dedicated`, con `use_dedicated_tool` y el nombre de la tool, más
  `family_disabled: true` si la familia de esa tool está desactivada. Ninguno de
  los tres llega a HA ni al Supervisor (008 FR-003; CAP-001, CAP-002, CAP-003).
- **FR-004**: La genérica de lectura solo ejecuta entradas `read` y la de
  escritura solo `confirm`; la otra categoría se rechaza con
  `wrong_generic_tool` y el nombre de la genérica que corresponde. Una entrada
  `read` o `confirm` cuya familia está desactivada se rechaza con
  `family_disabled` (008 FR-003, FR-006, FR-007, FR-010).
- **FR-005**: **Test de verbos**: ninguna entrada cuyo comando contenga como
  palabra (separando por `/`, `_` y `-`) un verbo de escritura —`create`,
  `delete`, `remove`, `update`, `set`, `save`, `install`, `uninstall`,
  `restart`, `reload`, `import`, `clear`, `adjust`, `change`, `configure`,
  `reset`, `move`, `reorder`, `enable`, `disable`, `ignore`, `dismiss`, `add`,
  `promote`, `run`, `start`, `stop`; la lista está escrita en el test y solo
  crece— ni ninguna ruta del Supervisor con método distinto de `GET` queda como
  `read`. Las excepciones están en una lista explícita del test, cada una con
  su justificación, y el test las enumera (008 FR-004; CAP-001).
- **FR-006**: **Test de deriva**: compara la tabla con los dos inventarios y
  falla, nombrando cada caso, si un comando o una ruta del inventario no tiene
  entrada, si una entrada no está en el inventario, si una fila de clase A o C
  no tiene CAP o si queda alguna entrada con el motivo «sin revisar». El
  inventario del Supervisor tiene una fila por método y ruta (254) (008 FR-005;
  CAP-007).
- **FR-007**: El **extractor** de los inventarios (comandos WebSocket de Core
  por análisis del código, sin importarlo ni ejecutarlo; rutas del Supervisor
  desde su registro de rutas) y el **generador** de la tabla se versionan en
  `scripts/inventario/`, fuera del paquete del add-on. El extractor conserva las
  columnas revisadas a mano de las filas que ya existían y deja las nuevas sin
  clase; el generador conserva las entradas revisadas, añade las filas nuevas
  como `deny` «sin revisar» y quita las que ya no existen, listándolas (008
  FR-005; CAP-007).

#### Tools genéricas

- **FR-008**: Tool `ha_read_ws_command(type, payload)`, con `readOnlyHint`,
  que envía a Core por WebSocket el comando `type` con la carga `payload` solo
  si la entrada es `read`, y devuelve su resultado (008 FR-006; CAP-002).
- **FR-009**: Tool `ha_call_ws_command(type, payload, confirmation_token)`, con
  `destructiveHint`, que solo ejecuta entradas `confirm` y **siempre** en dos
  pasos. La vista previa contiene el comando, la categoría, el motivo, la CAP,
  una nota de que describe exactamente lo que se enviará y no interpreta su
  efecto, y el **resumen de la carga** de FR-010. El token se ata a la tool, al
  comando y a la carga completa; se confirma repitiendo los mismos argumentos
  más el token (008 FR-006; CAP-002).
- **FR-010**: **Regla del resumen de la carga** (medible): una fila por cada
  clave de la carga, a cualquier profundidad (los elementos de una lista, por
  índice), con su ruta (`a.b[0].c`), su tipo JSON (`string`, `integer`,
  `number`, `boolean`, `null`, `object`, `array`) y su tamaño en bytes de JSON.
  La fila lleva el valor **solo si** es un escalar, su longitud es de 64
  caracteres o menos (la del texto tal cual si es una cadena, sin comillas; la
  de su JSON si es número, booleano o `null`), ninguna clave de su ruta es sensible para la redacción
  de Hermes (los marcadores de `redact_structure` más las claves extra de la
  entrada) y `redact_secrets` no cambia el texto. Si no, la fila dice por qué
  no lo lleva (`sensitive`, `too_long` o `container`). El resumen lleva también
  el tamaño total de la carga. Si la vista previa no cabe en
  `response_max_bytes`, no se emite token (`preview_too_large`) (008 FR-006;
  CAP-002).
- **FR-011**: Tool `sv_read_api(path)`, con `readOnlyHint`, solo para rutas
  `GET` clasificadas `read`; y tool `sv_call_api(method, path, body,
  confirmation_token)`, con `destructiveHint`, solo para rutas `confirm`,
  siempre en dos pasos con la misma vista previa (método, ruta concreta,
  plantilla, categoría, motivo, CAP y resumen del cuerpo según FR-010) y el
  token atado a la tool, al método, a la ruta y al cuerpo completo (008 FR-007;
  CAP-003).
- **FR-012**: **Validación de rutas** antes de buscar en la tabla y de llamar:
  la ruta empieza por `/`, no lleva esquema, host, `?`, `#`, `%`, caracteres de
  control, `\`, segmentos vacíos ni `..`; casa con una plantilla de la tabla
  (cada `{parámetro}` es un segmento de `[A-Za-z0-9._-]`, de 1 a 64
  caracteres; un literal gana a un parámetro). Se rechazan siempre, aunque la
  tabla dijera otra cosa, `/core/api*` y `/homeassistant/api*` (el proxy de
  Core) y cualquier ruta cuyo parámetro `{app}` sea el propio Hermes (`self`,
  su slug o un slug que termine en `_hermes`, el mismo criterio que
  `tools/addons.py`), con
  `path_not_allowed` (008 FR-007; CAP-003).
- **FR-013**: Validación de los argumentos de Core: `type` casa con
  `^[a-z0-9_-]+(/[a-z0-9_-]+)*$` y tiene 128 caracteres o menos; `payload` es
  un objeto o se omite, y no lleva `id` ni `type`. Si no, `invalid_argument`
  sin llegar a HA (008 FR-006; CAP-002).
- **FR-014**: Las respuestas de las cuatro genéricas pasan por
  `redact_structure` (más las claves extra de su entrada) y por
  `redact_secrets` en los textos, y por el tope central de respuesta. Una lista
  se devuelve con el sobre común `{count, items, truncated}` para que el tope
  pueda recortarla; un objeto, en `result`. Las rutas marcadas como de texto se
  devuelven por líneas, con la redacción de secretos y de red de los logs y,
  si no caben, las últimas líneas con `truncated: true` (008 FR-008; CAP-002,
  CAP-003).
- **FR-015**: El log de una llamada genérica lleva solo la tool, el comando o
  la plantilla de ruta (nunca la ruta concreta), el método, la categoría, el
  resultado (ejecutado, vista previa o código de rechazo), los nombres de las
  claves de primer nivel de la carga y su tamaño; nunca valores. Un `type` o una
  ruta que no tienen forma válida no se copian al log (008 FR-008; CAP-002,
  CAP-003).
- **FR-016**: Las entradas `read` marcadas como suscripción de un solo mensaje
  se leen una vez, con un tope de tiempo, y se cancelan siempre; ninguna
  genérica deja una suscripción abierta tras responder. Solo una entrada `read`
  puede llevar esa marca (008 FR-009; CAP-002).
- **FR-017**: Los errores de HA y del Supervisor se devuelven como
  `ha_command_failed` o `supervisor_request_failed`, con el código de HA cuando
  lo hay (por ejemplo, `unknown_command` con una pista sobre la versión de HA
  instalada). El mensaje de HA o del Supervisor se devuelve pasado por
  `redact_secrets` y con cada valor de texto de la carga de 4 o más caracteres
  sustituido por `***` (HA puede repetir en su error el valor que rechaza); el
  log no lleva el mensaje. Al confirmar, el resultado guardado
  junto al token es solo `{"executed": true}`, nunca la respuesta de HA
  (principio II; casos límite de la 008).
- **FR-018**: Anotaciones verdaderas en `tools/_annotations.py`, por nombre
  exacto: las dos de lectura, `readOnlyHint` y sin mundo abierto (y ninguna
  entrada `read` de la tabla sale a internet, lo comprueba un test); las dos de
  escritura, `destructiveHint`, no idempotentes y de mundo abierto. Sus
  descripciones dicen que ejecutan solo lo que la tabla permite y cómo
  consultarla (008 FR-006, FR-007, FR-018; principio V).

#### Familias

- **FR-019**: **Catálogo de familias** en un módulo neutral: cada módulo de
  tools pertenece a una sola familia; las de la 1.1.2 agrupan las 216 tools de
  hoy por área (las de los temas de la guía) y `base` agrupa `ping`,
  `test_progress` y `hermes_guide`, que no se puede desactivar. Las cuatro
  genéricas forman la familia nueva `generic_commands`. Cada familia dice desde
  qué versión existe; las tools nuevas del programa van en familias de la
  1.2.0, distintas de las de la 1.1.2 (008 FR-010; CAP-004).
- **FR-020**: Opción `tool_families_disabled` (lista de nombres, por defecto
  vacía) en `hermes/config.yaml` (esquema y opciones), exportada por `run.sh`
  y validada en `config.py`: un nombre desconocido, o `base`, impide arrancar
  con un mensaje que nombra el valor inválido y los válidos. `register_all_tools`
  no registra las tools de las familias desactivadas y el log de arranque dice
  cuáles se desactivaron y cuántas tools quedan (008 FR-010; CAP-004).
- **FR-021**: Con la configuración por defecto, las 216 tools de la 1.1.2 siguen
  registradas con el mismo nombre, las mismas anotaciones y los mismos
  argumentos; con todas las familias de la 1.2.0 desactivadas, la lista es
  exactamente la de la 1.1.2 (008 FR-010, FR-020, SC-005).

#### Guía, invariantes y documentación

- **FR-022**: `hermes_guide` tiene un tema `generic_commands` (con alias) que
  explica cuándo usar las genéricas, las categorías, los dos pasos y los
  códigos de rechazo, y acepta un argumento opcional `search` que lista las
  entradas de la tabla que casan (por comando, integración, área de ruta, CAP o
  familia) con su categoría, su tool dedicada o su motivo y, solo si la tabla
  lo tiene, su ejemplo de carga; con un máximo de filas y la indicación de
  afinar la búsqueda si hay más. El índice menciona el tema y las
  `INSTRUCTIONS` del servidor no dan un recuento de tools que deje de ser
  cierto (008 FR-011; CAP-008).
- **FR-023**: Un test comprueba que toda entrada `dedicated` nombra una tool
  que existe en el registro con todas las familias activas y que la familia de
  la entrada es la de esa tool. Cada sub-feature que añada una tool dedicada
  pasa a `dedicated`, en el mismo cambio, los comandos y rutas que use (008
  FR-012; CAP-001).
- **FR-024**: **Enmiendas de la constitución** E-1 (principio IV, vista previa
  de las genéricas), E-2 (principio V, honestidad atada a la tabla), E-3
  (puerta 4 del flujo, el banco de Core en los checks) y E-4 (principio XI,
  fecha de publicación pendiente en el CHANGELOG), en `docs/PRINCIPIOS.md` y en
  `.specify/memory/constitution.md` en el mismo cambio, **antes** del código,
  con la versión de la constitución subida según su propia regla (008, plan,
  «Comprobación de la constitución»).
- **FR-025**: Ningún valor centinela de secreto que pase por una genérica (en
  la carga, en el cuerpo o en la respuesta) aparece en una respuesta, una vista
  previa, un error, el log o el fichero del token; hay un test con centinela
  por cada genérica (008 FR-019, SC-008; principio II).
- **FR-026**: Documentación en el mismo cambio: sección «Política y genéricas»
  en la entrada `## [1.2.0]` de `hermes/CHANGELOG.md`; opción y familias en
  `hermes/DOCS.md`; tabla y genéricas en `SECURITY.md`; `README.md` y
  `README.es.md` sincronizados si cambian; estado de la 011 en
  `docs/HOJA-DE-RUTA.md`; filas de CAP-001…004, 007 y 008 de la matriz de
  trazabilidad de `specs/008-cobertura-total/plan.md` con los nombres
  definitivos y los ficheros de test. Todo con marcadores genéricos (008
  FR-021, FR-023, FR-024).

### Entidades clave

- **Entrada de la tabla**: clave (comando de Core, o método + plantilla de ruta
  del Supervisor), categoría, motivo, familia, tool dedicada, CAP y marcas de
  ejecución.
- **Familia de tools**: nombre, descripción, versión en la que aparece, si se
  puede desactivar y los módulos de tools que agrupa.
- **Inventario**: comandos de Core y rutas del Supervisor de una versión
  concreta de HA, con las columnas revisadas a mano (cobertura, clase, nota,
  CAP).
- **Resumen de la carga**: filas por clave con ruta, tipo, tamaño y valor o
  motivo de ocultarlo.

## Fuera de alcance

- Tools dedicadas nuevas: son de las sub-features 012 en adelante.
- Clasificar uno a uno la clase C (025) y pasar a `read`/`confirm` lo de las
  CAP con tool dedicada (sus sub-features).
- Parámetros de consulta (`?lines=`…) en las rutas del Supervisor: las rutas
  que los necesitan tienen tool dedicada prevista.
- Suscripciones persistentes, binarios, subidas y descargas.
- Cambiar la forma de respuesta de las tools existentes, `hassio_role` o el
  banco de pruebas (010, 014, 028).
- Las candidatas D de research R-4 de la 008.

## Supuestos

- **S-01**: La 009 (redacción lineal) y la 010 (banco de Core) están integradas
  en la rama antes de implementar el tramo 2; si la 010 no lo está, la prueba
  en el banco (T027) queda anotada como pendiente de la 010 y el tramo sigue.
- **S-02**: La 1.2.0 sale entera (S-02 de la 008): los motivos «pendiente» de
  la tabla nunca llegan a usuarios; el cierre del programa (FR-098 de la 008)
  los vigila.
- **S-03**: El código fuente de HA para el extractor está en una carpeta local
  del mantenedor; el CI no lo descarga ni ejecuta el extractor. Los tests del
  extractor usan árboles de código mínimos de ejemplo dentro de `tests/`.
- **S-04**: Los comandos y rutas de vía T se clasifican con la información del
  inventario y del código de HA leído; el banco de la 010 corrige lo que se
  haya clasificado mal (S-01 de la 008).

## Criterios de éxito *(obligatorio)*

- **SC-001**: La tabla tiene exactamente 623 entradas de Core y 254 del
  Supervisor, ninguna «sin revisar», y el test de deriva pasa.
- **SC-002**: Cero entradas con verbo de escritura o método distinto de `GET`
  en `read`, salvo las excepciones listadas y justificadas.
- **SC-003**: En el 100 % de los casos probados, un comando o ruta `dedicated`,
  `deny`, desconocido, de categoría equivocada, de familia desactivada, con
  ruta inválida o dirigida a Hermes no llega a HA ni al Supervisor; cada guarda
  tiene su control negativo anotado.
- **SC-004**: El 100 % de las ejecuciones de `ha_call_ws_command` y
  `sv_call_api` pasan por una vista previa con token; un token no sirve con otro
  comando, ruta, método o carga.
- **SC-005**: Con la configuración por defecto, los 216 nombres de la 1.1.2
  siguen con las mismas anotaciones; con las familias de la 1.2.0 desactivadas,
  la lista tiene exactamente esos 216 nombres.
- **SC-006**: Ningún centinela de secreto aparece en respuestas, vistas
  previas, errores, log ni fichero del token de las genéricas.
- **SC-007**: La suite pasa en el CI de Linux al final de cada uno de los tres
  tramos, con los mismos fallos conocidos de Windows en local que en la línea
  base (6) y ninguno más.
- **SC-008**: La constitución y `docs/PRINCIPIOS.md` tienen E-1…E-4 en el commit
  del tramo 1, antes del primer cambio de código.
