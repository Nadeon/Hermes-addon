# Especificación: Hermes 1.2.0 — cobertura total de Home Assistant 2026.11 (paraguas)

**Directorio de la spec**: `specs/008-cobertura-total`

**Creada**: 2026-11-14

**Estado**: Borrador

**Tipo**: especificación paraguas de un programa. No se implementa por sí
misma: define qué significa «cobertura total», las reglas comunes y el
desglose en sub-features (009–032), cada una con su propia spec, plan y tareas.

**Entrada**: [research.md](research.md) (95 capacidades CAP-001…CAP-106,
correcciones a la hoja de ruta, exclusiones, opciones de arquitectura y
desglose) y los inventarios [inventario/core-ws.tsv](inventario/core-ws.tsv)
(623 comandos WebSocket de Core 2026.11.1) e
[inventario/supervisor-rutas.tsv](inventario/supervisor-rutas.tsv) (254 rutas
del Supervisor 2026.11.0 en 217 filas). Objetivo del mantenedor: que Hermes
cubra todo lo que Home Assistant Core 2026.11.1 y el Supervisor 2026.11.0
ofrecen a un administrador y Hermes todavía no tiene.

Hoy (1.1.2) Hermes cubre 130 de los 623 comandos de Core y 37 de las rutas del
Supervisor. Quedan 147 comandos de Core y 130 rutas del Supervisor con huecos
reales de administración (clase A), 192 comandos de gestión de integraciones
concretas (clase C), 103 comandos y 67 rutas internos del frontend o de
suscripción (clase B) y 51 comandos y 20 rutas peligrosos o no automatizables
(clase D).

## Clarificaciones

### Sesión 2026-11-14

Decisiones del mantenedor, vinculantes, que esta spec no discute:

- P: ¿Una tool por capacidad, solo tools genéricas o un modelo híbrido? → R:
  **híbrido**. Tools dedicadas para las capacidades de prioridad alta y
  media-alta y para todo lo que modifique algo con consecuencias y necesite una
  vista previa útil, con las convenciones de siempre (dos pasos en lo
  destructivo, anotaciones honestas, descripción que no miente, tema en la guía
  y tests con control negativo). Para la cola larga y la clase C, cuatro tools
  **genéricas** separadas en lectura y escritura (WebSocket de Core y API del
  Supervisor): la de lectura lleva `readOnlyHint`; la de escritura exige
  siempre confirmación, con una vista previa del comando y un resumen de la
  carga.
- P: ¿Qué decide lo que la genérica puede ejecutar? → R: una **tabla de
  clasificación** versionada dentro de Hermes, generada a partir de los
  inventarios, con una categoría por comando o ruta: `dedicated` (se rechaza
  con una pista hacia la tool dedicada), `read`, `confirm` o `deny` (la
  clase D). Lo que no está en la tabla se rechaza. Un test impide que un
  comando con verbo de escritura quede como `read`; otro compara la tabla con
  el inventario.
- P: ¿Familias de tools? → R: se pueden desactivar con una opción de
  configuración. **Por defecto, todas activas**, para que ninguna tool que
  existe hoy desaparezca.
- P: ¿Banco de pruebas? → R: en el CI, **HA Core 2026.11.1 real en contenedor**
  con un **Supervisor simulado mínimo** dentro de `tests/`, sin cambiar el
  código de producto salvo lo imprescindible y justificado. El Supervisor real
  (VM con HAOS) **no** se monta en la máquina del mantenedor: se documenta el
  procedimiento y queda como pendiente manual del final, igual que las pruebas
  en vivo de las tools nuevas (solo posibles tras publicar) y la prueba de
  `hassio_role: manager`.
- P: ¿Versionado? → R: todo el programa sale como **una sola versión 1.2.0**,
  desde la rama `feat/cobertura-total`. La versión se sube una vez, en la
  sub-feature 009. Una única entrada `## [1.2.0] — <fecha de publicación>` en
  el CHANGELOG, con secciones por bloque, que cada sub-feature completa. Los
  alias `ha_hacs_*` **no** se retiran (se retiran en la 1.3.0, como está
  anunciado) y `ha_remove_device_from_config_entry` se mantiene deprecada.
  Fusionar y publicar quedan para el final y los decide el mantenedor.
- P: ¿Qué queda fuera? → R: la clase B, por no aplicar a un servidor MCP
  (justificado por grupo), y la clase D, por diseño; esta entra en la tabla
  como `deny`. Las candidatas D viables con salvaguardas fuertes de research
  R-4 quedan como dudas para el final y no se implementan.
- P: ¿Desglose? → R: el de research R-6, revisado. Cada sub-feature la puede
  especificar un agente e implementar en tramos de 1 a 3 agentes; las que no
  caben se parten. 009 incluye la subida de versión. 011 (política y
  genéricas) va antes que las features de tools dedicadas.

Decisiones tomadas al especificar (se anotan aquí en lugar de preguntar):

- P: ¿Cómo se clasifica en la tabla un comando de clase A que tendrá tool
  dedicada en una sub-feature posterior? → R: **`deny` con el motivo
  «pendiente de tool dedicada (spec NNN)»** hasta que esa sub-feature lo pase a
  `dedicated`. Así la genérica nunca abre, ni de forma transitoria, una vía sin
  la vista previa semántica que se va a construir (principio III). El cierre del
  programa exige que no quede ninguno con ese motivo (ver S-02).
- P: ¿Y la clase B en la tabla? → R: `deny` con el motivo de su grupo
  (suscripción, frontend, alias legado…). La tabla no tiene más categorías que
  las cuatro decididas; el motivo distingue B de D.
- P: ¿Las tools nuevas pueden agrupar varias capacidades en una tool con un
  parámetro (por ejemplo, un solo `sv_get_system_logs(source)` en vez de
  cuatro)? → R: **sí**, si la sub-spec lo justifica y la tool resultante tiene
  una sola clase de riesgo (todo lectura o todo con confirmación), para que sus
  anotaciones sigan siendo verdad. Los nombres de research R-2 son propuestas.
- P: ¿Las tools existentes cambian de forma de respuesta para unificar las
  listas (CAP-023)? → R: **no en la 1.2.0**: solo las tools nuevas usan el
  sobre común `{count, items, truncated}`; unificar las viejas rompería
  clientes y queda como duda para el final.
- P: ¿`ha_marketplace_list_removed` filtra por defecto los instalados
  (CAP-016)? → R: **no**: se añaden `installed_only` y `limit` opcionales y un
  resumen por tipo, con valores por defecto que dan la misma lista que hoy
  (FR-020 de compatibilidad).
- P: ¿Las familias nuevas de riesgo alto (usuarios, red del host, HTTP,
  escritura del Marketplace, cámaras) también activas por defecto? → R: sí,
  porque la decisión del mantenedor es «todas activas»; se anota como duda para
  el final (D-03) por su coste en contexto y su riesgo.

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» de Hermes es un administrador de Home Assistant que trabaja a
través de un cliente MCP (un asistente basado en un modelo de lenguaje). El
mantenedor es el segundo usuario: necesita saber qué está cubierto y qué está
probado de verdad.

### Historia 1 — Todo lo que HA ofrece a un administrador es alcanzable (Prioridad: P1)

Quien administra su casa con Hermes quiere poder hacer desde el cliente MCP
cualquier cosa que Home Assistant 2026.11 le deja hacer desde la interfaz o la
API, sin encontrarse con «Hermes no tiene eso».

**Prueba independiente**: para cada CAP de las clases A y C (CAP-040 a
CAP-106), existe una tool dedicada registrada o una entrada `read`/`confirm` en
la tabla, y un test automático la ejerce.

**Escenarios de aceptación**:

1. **Dado** un comando de Core de clase A sin tool dedicada (por ejemplo, la
   lista de tags), **cuando** el agente llama a la tool genérica de lectura con
   ese comando, **entonces** obtiene la respuesta de HA, recortada y redactada.
2. **Dado** un comando de gestión de una integración concreta clasificado como
   `confirm` (por ejemplo, un parámetro de configuración de Z-Wave), **cuando**
   el agente llama a la genérica de escritura, **entonces** recibe una vista
   previa con el comando y un resumen de la carga y un token, y solo ejecuta al
   confirmar.
3. **Dado** una capacidad de prioridad alta (por ejemplo, los logs del
   sistema), **entonces** existe una tool dedicada con nombre predecible,
   descripción y tema en la guía.
4. **Dado** un comando o una ruta que no está en la tabla, **cuando** se pide
   por una genérica, **entonces** se rechaza sin llegar a HA y la respuesta dice
   que no está clasificado.

### Historia 2 — Lo que tiene consecuencias se ve antes de hacerse (Prioridad: P1)

Quien confía en la vista previa como única revisión antes de un cambio grave
quiere que ninguna vía nueva le permita saltársela.

**Prueba independiente**: ningún comando `dedicated`, `deny` o desconocido se
ejecuta por las genéricas; todo `confirm` pasa por dos pasos; las tools
dedicadas destructivas devuelven una vista previa que describe el efecto real.

**Escenarios de aceptación**:

1. **Dado** un comando que tiene tool dedicada (por ejemplo, guardar un
   dashboard), **cuando** se pide por la genérica de escritura, **entonces** se
   rechaza con el nombre de la tool dedicada y no llega a HA, aunque su familia
   esté desactivada.
2. **Dado** un comando de clase D (por ejemplo, la consola de depuración),
   **cuando** se pide por cualquier genérica, **entonces** se rechaza con su
   motivo.
3. **Dado** la genérica de escritura con una carga que lleva una contraseña,
   **entonces** la vista previa, el error y el log no contienen la contraseña.
4. **Dado** una actualización de Core desde su tool dedicada, **entonces** la
   vista previa dice la versión actual y la de destino, las notas de la versión
   recortadas, si habrá backup y el estado de salud del sistema.
5. **Dado** un token emitido para un comando de la genérica, **cuando** se
   confirma con otro comando u otra carga, **entonces** se rechaza.

### Historia 3 — Nada de lo que funciona hoy se rompe (Prioridad: P1)

Quien ya usa Hermes 1.1.2 quiere actualizar a la 1.2.0 sin cambiar nada en su
cliente ni en su configuración.

**Prueba independiente**: con la configuración por defecto, las 216 tools de la
1.1.2 siguen registradas con el mismo nombre y las mismas anotaciones, y la
suite de la 1.1.2 pasa sin cambios salvo los textos que la 1.2.0 cambia a
propósito y deja anotados.

**Escenarios de aceptación**:

1. **Dado** una configuración de la 1.1.2 sin la opción de familias,
   **entonces** Hermes arranca con todas las familias activas.
2. **Dado** una tool de la 1.1.2 a la que el programa añade un argumento,
   **cuando** se llama sin él, **entonces** se comporta como en la 1.1.2.
3. **Dado** los alias `ha_hacs_*` y `ha_remove_device_from_config_entry`,
   **entonces** siguen disponibles y deprecados, como en la 1.1.2.

### Historia 4 — Diagnosticar sin tocar nada (Prioridad: P2)

Quien tiene un problema en su instalación quiere que el agente lea logs,
diagnósticos, salud del sistema, disco, notificaciones y estadísticas sin
riesgo de cambiar nada.

**Prueba independiente**: todas las tools de diagnóstico nuevas llevan
`readOnlyHint`, sus respuestas pasan por la redacción y el tope de respuesta, y
el log de Hermes no contiene su contenido.

**Escenarios de aceptación**:

1. **Dado** un log del sistema con una línea muy larga sin espacios, **cuando**
   se lee, **entonces** la redacción termina en un tiempo acotado y la
   respuesta no pasa del tope.
2. **Dado** el diagnóstico de una integración, **entonces** sale redactado y
   recortado como cualquier otra respuesta.

### Historia 5 — El mantenedor sabe qué está probado de verdad (Prioridad: P2)

El mantenedor quiere saber, tool por tool, si se ha ejecutado contra una HA
real, contra el Supervisor real o solo con simuladores.

**Prueba independiente**: el CI ejecuta las escrituras de Core contra HA Core
2026.11.1 real; la hoja de ruta tiene la matriz tool → entorno → resultado con
lo que queda manual.

**Escenarios de aceptación**:

1. **Dado** un PR a la rama, **entonces** el CI arranca HA Core 2026.11.1,
   ejecuta las tools de Core que modifican y comprueba su efecto leyendo de
   vuelta desde HA.
2. **Dado** una tool del Supervisor, **entonces** la matriz dice si está
   probada con simuladores, pendiente en la VM o pendiente en vivo.

### Historia 6 — Una versión nueva de HA no abre puertas sin revisar (Prioridad: P2)

Cuando salga una HA nueva, el mantenedor quiere ver qué comandos han aparecido
o desaparecido y que ninguno nuevo sea alcanzable hasta clasificarlo.

**Prueba independiente**: al regenerar el inventario con un comando nuevo, el
test de deriva falla y la genérica lo rechaza.

**Escenarios de aceptación**:

1. **Dado** un inventario con un comando que no está en la tabla, **entonces**
   el test de deriva falla y nombra el comando.
2. **Dado** una entrada de la tabla que ya no está en el inventario,
   **entonces** el test de deriva falla y la nombra.

### Historia 7 — Menos contexto para quien no lo necesita (Prioridad: P3)

Quien usa un cliente con pocas tools o poco contexto quiere desactivar las
familias que no usa.

**Prueba independiente**: con una familia desactivada, sus tools no aparecen en
la lista y sus comandos siguen rechazados por la genérica.

**Escenarios de aceptación**:

1. **Dado** la opción con la familia de usuarios desactivada, **entonces** sus
   tools no se registran y la genérica rechaza sus comandos indicando que la
   familia está desactivada.
2. **Dado** un nombre de familia que no existe en la opción, **entonces** Hermes
   no arranca y el log dice qué nombre es inválido.

### Casos límite

- Comando que existe en 2026.11.1 pero no en la versión de HA instalada (la
  mínima es 2024.10): HA responde «unknown command»; la genérica lo devuelve
  como error claro, no como fallo de Hermes.
- Suscripciones: la genérica no mantiene suscripciones. Las que la tabla marca
  como de un solo mensaje se leen una vez con tope de tiempo y se cancelan; el
  resto son `deny`.
- `sv_call_api`/`sv_read_api` con rutas que intentan salir de la API (`..`,
  `%2e`, rutas absolutas a otro host, `/core/api*`, que es el proxy de Core):
  rechazadas antes de llamar al Supervisor.
- Respuesta mayor que `response_max_bytes`: `response_too_large` o recorte con
  `truncated`, como el resto de tools; nunca se corta una vista previa con
  token.
- Familia desactivada cuyos comandos son `dedicated`: la genérica los sigue
  rechazando (no es una vía alternativa).
- Comando con verbo ambiguo (por ejemplo, un `get` que en realidad crea algo):
  lo decide la revisión manual de la tabla; el test de verbos lista las
  excepciones justificadas.
- `sv_update_addon` sobre el propio Hermes: rechazo previo sin token
  (`self_update_not_supported`).
- Core caído: las tools de Core fallan con el error de conexión de siempre;
  las del Supervisor que no dependen de Core siguen funcionando.

## Requisitos *(obligatorio)*

Cada requisito dice entre paréntesis la sub-feature que lo implementa y las CAP
que cubre. La matriz completa CAP → sub-feature → FR → vía → test está en
[plan.md](plan.md).

### Requisitos funcionales

#### Transversales: política de comandos y tools genéricas (011)

- **FR-001**: Hermes incluye una **tabla de clasificación** versionada con una
  entrada por cada comando WebSocket del inventario de Core y por cada
  plantilla de ruta (método + ruta) del inventario del Supervisor. Cada entrada
  tiene categoría (`dedicated`, `read`, `confirm` o `deny`), motivo, familia,
  la tool dedicada cuando la categoría es `dedicated`, la CAP cuando la tiene y
  las marcas que necesite la ejecución (redactar la respuesta, suscripción de
  un solo mensaje). La tabla se genera a partir de los inventarios y se revisa a
  mano (011; CAP-001).
- **FR-002**: Clasificación inicial: lo cubierto hoy → `dedicated` con su tool
  (lo cubierto por acción genérica, a `ha_call_service`); clase B → `deny` con
  el motivo de su grupo; clase D → `deny` con su motivo; clase A o C sin tool
  dedicada prevista → `read` o `confirm` según su efecto; clase A con tool
  dedicada prevista en este programa → `deny` con motivo «pendiente de tool
  dedicada (spec NNN)» hasta que esa sub-feature la pase a `dedicated` (011;
  CAP-001).
- **FR-003**: **Fail-closed**: un comando o ruta que no está en la tabla se
  rechaza con `command_not_classified`; uno `deny`, con `command_denied` y su
  motivo; uno `dedicated`, con `use_dedicated_tool` y el nombre de la tool (y,
  si su familia está desactivada, que lo está). Ninguno de los tres llega a HA
  ni al Supervisor (011; CAP-001, CAP-002, CAP-003).
- **FR-004**: Un test impide que un comando con verbo de escritura en su nombre
  (`create`, `delete`, `remove`, `update`, `set`, `save`, `install`,
  `uninstall`, `restart`, `reload`, `import`, `clear`, `adjust`, `change`,
  `configure`, `reset`, `move`, `reorder`, `enable`, `disable`, `ignore`,
  `dismiss`, `add`, `promote`, `run`, `start`, `stop`; la lista completa es
  explícita en el test y solo crece) o una ruta del Supervisor con método
  distinto de `GET` quede como `read`. Las excepciones van en una lista
  explícita, cada una con su justificación, y el test la enumera (011;
  CAP-001).
- **FR-005**: Un **test de deriva** compara la tabla con los inventarios y falla
  si un comando o ruta del inventario no tiene entrada, si una entrada no está
  en el inventario o si una fila de clase A o C no tiene CAP. El extractor que
  genera los inventarios se versiona en el repositorio, fuera del paquete del
  add-on, para regenerarlos con cada versión nueva de HA (011; CAP-007).
- **FR-006**: Tool `ha_read_ws_command(type, payload)`, con `readOnlyHint`, que
  solo ejecuta comandos `read`; y tool `ha_call_ws_command(type, payload,
  confirmation_token)`, con `destructiveHint`, que solo ejecuta comandos
  `confirm` y **siempre** en dos pasos: la vista previa muestra el comando, su
  categoría y motivo, y un resumen de la carga: todas las claves con su tipo y
  tamaño, y el valor solo si es un escalar de 64 caracteres o menos cuya clave
  no es sensible para `redact_secrets` (el resto, tapado); el token se ata al
  comando y a la carga completa (011; CAP-002).
- **FR-007**: Tool `sv_read_api(path)`, con `readOnlyHint`, solo para rutas
  `GET` clasificadas `read`; y tool `sv_call_api(method, path, body,
  confirmation_token)`, con `destructiveHint`, solo para rutas `confirm`, siempre
  en dos pasos con la misma vista previa. La ruta se valida antes de llamar
  (sin `..`, `%2e` ni otras codificaciones, sin host ni esquema) y `/core/api*`
  se rechaza siempre (011; CAP-003).
- **FR-008**: Las respuestas de las cuatro genéricas pasan por el tope central
  de respuesta y por `redact_secrets`, más la redacción adicional que marque su
  entrada. El log de una llamada genérica lleva solo el comando o la plantilla
  de ruta, la categoría, los nombres de las claves de la carga y su tamaño;
  nunca valores (011; CAP-002, CAP-003).
- **FR-009**: Las suscripciones marcadas en la tabla como de un solo mensaje se
  leen una vez, con un tope de tiempo, y se cancelan; ninguna genérica mantiene
  una suscripción abierta tras responder (011; CAP-002).
- **FR-010**: **Familias de tools**: una opción de configuración permite
  desactivar familias por nombre. Por defecto todas están activas y las tools de
  la 1.1.2 quedan exactamente como hoy. Las cuatro genéricas forman su propia
  familia. Las tools nuevas del programa van en familias distintas de las que
  agrupan las tools de la 1.1.2, para que desactivar las nuevas deje
  exactamente la lista de la 1.1.2. Con una familia desactivada sus tools no se
  registran, pero sus comandos siguen siendo `dedicated` en la tabla. Un nombre de familia
  desconocido impide arrancar con un mensaje que lo nombra (011; CAP-004).
- **FR-011**: `hermes_guide` tiene un tema por cada familia nueva y una consulta
  de la tabla que, para un tema o integración, lista los comandos disponibles
  con su categoría, su tool dedicada si la hay y, cuando la tabla lo tenga, un
  ejemplo de carga. La guía no inventa cargas que la tabla no documente (011;
  CAP-008).
- **FR-012**: Cada sub-feature que añade una tool dedicada pasa a `dedicated`,
  en el mismo cambio, los comandos y rutas que esa tool usa. Un test comprueba
  que toda entrada `dedicated` nombra una tool que existe en el registro con
  todas las familias activas (011 y siguientes; CAP-001).

#### Transversales: banco de pruebas (010, 028, 014)

- **FR-013**: El CI tiene un job que arranca **HA Core 2026.11.1 real** en un
  contenedor fijado por digest, completa el onboarding de forma automática con
  credenciales generadas en el propio job (nunca guardadas ni impresas) y
  conecta Hermes a través de un **Supervisor simulado mínimo** que vive en
  `tests/`, responde a lo que Hermes necesita al arrancar y reenvía a Core las
  peticiones REST y WebSocket. El código de producto no cambia; si algún
  cambio fuese imprescindible, la sub-spec lo justifica y no puede abrir una vía
  nueva en producción (por ejemplo, una variable que cambie la URL base)
  (010; CAP-005).
- **FR-014**: En el banco se ejecutan de verdad todas las tools `ha_*` de la
  1.1.2 que modifican y no dependen de hardware, del Supervisor, de internet ni
  de la nube; cada ejecución comprueba el efecto leyendo de vuelta desde HA. Las
  que no se pueden ejecutar ahí quedan listadas con su motivo (010 y 028;
  CAP-034).
- **FR-015**: Cada tool dedicada nueva de Core se ejecuta en el banco en la
  sub-feature que la añade, y cada familia de la tabla con entradas `read` o
  `confirm` de Core tiene al menos un comando ejecutado en el banco por la
  genérica (todas las sub-features de Core; CAP-034).
- **FR-016**: El **banco del Supervisor** queda documentado como procedimiento
  (VM con HAOS e instantánea previa, Hermes instalado como add-on local, qué se
  prueba solo ahí: reinicios, apagados, restauraciones, desinstalaciones y
  cambio de rol) y la hoja de ruta tiene una **matriz tool → entorno (CI de
  Core, simuladores, VM, instalación real) → resultado** con lo pendiente
  manual, incluidas las pruebas manuales abiertas (014; CAP-006, CAP-034,
  CAP-035).
- **FR-017**: El comentario de `hassio_role` en `hermes/config.yaml` se corrige
  según el código del Supervisor 2026.11.0 (`/addons/self/options/config` pasa
  con cualquier rol). El rol no cambia en este programa: la prueba de
  `manager` queda como pendiente manual y su procedimiento, documentado (014;
  CAP-022).

#### Transversales: compatibilidad, convenciones, seguridad, privacidad y versión

- **FR-018**: Toda tool dedicada nueva sigue las convenciones de Hermes:
  confirmación en dos pasos con vista previa que describe exactamente el efecto
  cuando borra datos, interrumpe un servicio, toca secretos, reescribe
  histórico o cambia permisos o accesos; anotaciones MCP en la tabla central de
  anotaciones (nunca heredadas por prefijo si no son verdad); descripción que
  dice lo que hace; tema en la guía; tests con control negativo; y, si lista,
  el sobre común `{count, items, truncated}` (todas; CAP-023).
- **FR-019**: Ningún secreto que pase por las tools nuevas (contraseñas de
  montajes CIFS, credenciales de registros Docker, `client_secret`, claves de
  red de Thread, Z-Wave o Matter, tokens) aparece en una respuesta, una vista
  previa, un error o el log. Cada familia con entradas o salidas sensibles
  tiene un test con un valor centinela (todas; principio II).
- **FR-020**: **Nada de lo actual se rompe**: con la configuración por defecto
  las 216 tools de la 1.1.2 siguen registradas con el mismo nombre, las mismas
  anotaciones y los mismos argumentos con el mismo significado; los argumentos
  nuevos son opcionales y su valor por defecto reproduce el comportamiento de la
  1.1.2. Los alias `ha_hacs_*` siguen hasta la 1.3.0 y
  `ha_remove_device_from_config_entry` sigue deprecada (todas; CAP-030,
  CAP-031).
- **FR-021**: Los ficheros del repositorio que añade el programa (tests,
  fixtures, tabla, inventarios, documentación) usan solo marcadores genéricos y
  no contienen datos de ninguna instalación ni identificadores de modelos
  (todas; principio VIII).
- **FR-022**: La versión pasa a **1.2.0** una sola vez, en la sub-feature 009,
  en `hermes/config.yaml`, `hermes/src/hermes/__init__.py` y
  `HA_CORE_LAST_TESTED_IN_HERMES`. `hermes/CHANGELOG.md` tiene una única
  entrada `## [1.2.0] — <fecha de publicación>`, con secciones por bloque, que
  cada sub-feature completa; la fecha se fija al publicar. Fusionar y publicar
  los decide el mantenedor (009 y cierre).
- **FR-023**: La sub-feature que cambia el comportamiento actualiza en el mismo
  cambio la documentación afectada: `README.md` y `README.es.md`
  sincronizados, `hermes/DOCS.md` (opción de familias), `SECURITY.md` (tabla y
  genéricas) y el estado del programa en `docs/HOJA-DE-RUTA.md` (todas).
- **FR-024**: Cada sub-feature tiene su spec, plan y tareas en
  `specs/NNN-nombre/`, y sus requisitos citan los FR de esta spec y las CAP que
  cubren (todas).

#### 009 — correcciones pendientes y subida de versión

- **FR-025**: `redact_secrets` crece de forma lineal con el tamaño de la
  entrada: 1 MiB sin espacios se redacta en menos de 1 s en el CI, con test de
  tiempo (CAP-010).
- **FR-026**: `external_url` e `internal_url` de HA se redactan en el log desde
  que se conocen al arrancar, antes de las líneas que podrían contenerlas
  (CAP-011).
- **FR-027**: `auto_classify_restricted` deja de escribir `entity_id` en el
  log: solo contadores (CAP-012).
- **FR-028**: La redacción de red del log cubre los nombres de host con forma
  `ip-a-b-c-d` (CAP-013).
- **FR-029**: `sv_get_addon_logs` informa por separado si redactó secretos y si
  redactó red, sin cambiar el significado del campo `redacted` actual
  (CAP-014).
- **FR-030**: `ha_get_history` añade el bloque `_response_limit` cuando marca
  `truncated`, como las demás tools recortadas (CAP-015).
- **FR-031**: `ha_marketplace_list_removed` acepta `installed_only` y `limit`
  opcionales y añade un resumen por tipo; `removal_type` se trata como texto de
  terceros (CAP-016).
- **FR-032**: Las tools del Marketplace y `sv_get_resolution` escriben su
  evento `*_ok` con contadores (CAP-017).
- **FR-033**: Emitir una vista previa con documento no relee todos los ficheros
  de token: el total guardado se lleva en memoria o el barrido se hace como
  mucho una vez por segundo (CAP-018).
- **FR-034**: `sv_update_addon` sobre el propio Hermes se rechaza antes de
  llamar al Supervisor con `self_update_not_supported` e indica actualizar
  desde la interfaz de HA; no emite token (CAP-021).
- **FR-035**: Apagar Hermes no deja un traceback en el log (CAP-024).

#### 010 y 028 — banco de pruebas de Core

Cubiertos por FR-013 a FR-015 (CAP-005, CAP-034).

#### 012 — diagnóstico de Core

- **FR-036**: Validar la configuración de una automatización o un script y
  probar una condición sin guardar nada (CAP-040).
- **FR-037**: Leer el log del sistema de HA agrupado (contador, primera y
  última vez), el log de errores por número de líneas acotado y los niveles de
  log; fijar el nivel de un logger (vista previa con el nivel anterior) y
  limpiar el log del sistema, los dos con confirmación (CAP-041).
- **FR-038**: Leer los diagnósticos de una integración y de un dispositivo, con
  la redacción de Hermes y el tope de respuesta además de la de HA (CAP-042).
- **FR-039**: Listar las notificaciones persistentes y descartarlas con
  confirmación, con su texto en la vista previa (CAP-047).

#### 029 — estado del sistema y estadísticas de Core

- **FR-040**: Leer la salud del sistema (primer mensaje y pendientes con tope
  de tiempo), el estado del sistema, los tiempos de arranque de integraciones y
  los manifiestos (CAP-043).
- **FR-041**: Validar estadísticas y leer sus metadatos y la información del
  recorder (CAP-049).
- **FR-042**: La auditoría de llamadas a acciones (`logbook/get_action_calls`)
  queda `read` en la tabla, con tema en la guía y prueba en el banco
  (CAP-058).
- **FR-043**: La configuración de red y HTTP de Core queda `read` en la tabla,
  con sus URLs y direcciones fuera del log (CAP-068).

#### 013 — diagnóstico del Supervisor

- **FR-044**: Leer los logs de Core, del Supervisor, del host y de los plugins,
  los arranques y los identificadores del journal, y pedir en
  `sv_get_addon_logs` el arranque actual o uno anterior, con redacción y tope
  (CAP-081).
- **FR-045**: Leer servicios del host, uso de disco por directorio con
  profundidad acotada, información del OS, swap y discos candidatos a disco de
  datos (CAP-085).
- **FR-046**: La lista de jobs y las sugerencias de un issue del centro de
  resolución quedan `read` en la tabla (CAP-087, lectura).
- **FR-047**: Hardware, seguridad, Docker y hora quedan `read` en la tabla y la
  comprobación de integridad, `confirm` (CAP-088).
- **FR-048**: La red del host queda `read` en la tabla, con las direcciones
  fuera del log (CAP-089).

#### 014 — banco de pruebas del Supervisor (procedimiento)

Cubierto por FR-016 y FR-017 (CAP-006, CAP-022, CAP-034, CAP-035).

#### 015 — actualizaciones del sistema

- **FR-049**: Listar actualizaciones disponibles, buscar actualizaciones y
  actualizar Core, OS y Supervisor con confirmación. La vista previa dice
  versión actual → destino, notas de la versión recortadas como texto de
  terceros, si habrá backup, el estado de `/resolution/info` y el resultado de
  la comprobación de configuración de Core; la ejecución devuelve el job para
  seguirlo (CAP-080).
- **FR-050**: Leer las notas de versión de una entidad `update` e instalarla
  con confirmación y vista previa (versión instalada → destino, notas
  recortadas, backup si la entidad lo admite). Las entidades `update` de Core,
  OS y Supervisor se encaminan a las tools de FR-049, para que no haya dos
  caminos con vistas previas distintas (CAP-064).

#### 030 — tienda de apps

- **FR-051**: Listar, añadir (con confirmación), quitar (con confirmación) y
  reparar repositorios de la tienda; recargarla; leer changelog, documentación
  (como texto de terceros) y disponibilidad de una app; e instalar o actualizar
  una versión concreta (CAP-082).
- **FR-052**: Reconstruir una app con confirmación, y validar las opciones de
  una app en la vista previa de `sv_set_addon_options` antes de emitir el token
  (CAP-093).

#### 016 — integraciones: flujos y Repairs

- **FR-053**: Listar integraciones descubiertas e ignorar un descubrimiento;
  cambiar título y preferencias de una entrada (confirmación al desactivar el
  sondeo o las entidades nuevas); listar los manejadores de flujo (CAP-044).
- **FR-054**: Listar subentries, crearlas y editarlas por flujo, borrarlas con
  confirmación, y reconfigurar una entrada (CAP-045).
- **FR-055**: Ejecutar los flujos de reparación de Repairs; el paso que aplica
  el arreglo pide confirmación (CAP-048).
- **FR-056**: Las tools de Repairs devuelven título y descripción traducidos de
  los avisos (CAP-036).
- **FR-057**: La guía explica cómo crear y editar helpers por config entry con
  los flujos existentes (CAP-037).

#### 017 — automatización asistida

- **FR-058**: Listar, importar (con confirmación y como texto de terceros),
  guardar, borrar (con confirmación) y previsualizar la sustitución de
  blueprints (CAP-046).
- **FR-059**: Listar triggers, condiciones y acciones de un dispositivo con sus
  capacidades (CAP-051).
- **FR-060**: Resolver un target y listar triggers, condiciones y acciones
  aplicables a un target (CAP-052).
- **FR-061**: Esperar a un trigger una sola vez, con el mismo tope que
  `ha_wait_for_event` (CAP-038).
- **FR-062**: `ha_create_or_update_automation` y `ha_create_or_update_script`
  validan la configuración antes de emitir el token; una configuración que HA
  rechazaría se devuelve como error sin token (CAP-040).

#### 018 — mejoras de tools existentes

- **FR-063**: `ha_save_lovelace_dashboard` permite guardar una sola vista; el
  servidor conserva las demás vistas y las claves de nivel superior, con
  confirmación y vista previa (CAP-019).
- **FR-064**: `ha_call_service_response` acepta `confirmation_token` para las
  acciones de la denylist, con la misma vista previa que `ha_call_service`
  (CAP-020).
- **FR-065**: El sobre común de listas de FR-018 queda documentado en la guía y
  en una prueba que lo verifica en las tools nuevas (CAP-023).

#### 019 — montajes y ajustes de backup del Supervisor

- **FR-066**: Listar, crear, editar, borrar y recargar montajes de red, fijar el
  montaje por defecto de backups, leer y fijar los ajustes de backup y recargar
  backups; `location` en `sv_create_backup_*`. Confirmación en crear, editar,
  borrar y en el montaje por defecto; la contraseña CIFS entra pero nunca se
  devuelve ni se registra (CAP-083).

#### 031 — backups de la integración `backup` y safety backups cifrados

- **FR-067**: Leer agentes de backup y ajustes de backup previos a una
  actualización; cambiar la configuración de backups (programación, retención,
  agentes) y crear un backup eligiendo agentes, con confirmación; la contraseña
  de cifrado nunca se devuelve (CAP-057).
- **FR-068**: Los safety backups se crean cifrados con una contraseña generada,
  guardada en el almacenamiento del add-on y nunca devuelta ni registrada; la
  restauración sigue funcionando (CAP-027).

#### 020 — estadísticas y energía

- **FR-069**: Limpiar estadísticas, cambiar su unidad, editar sus metadatos,
  ajustar sumas e importar estadísticas, todo con confirmación y una vista
  previa que dice qué estadísticas y qué rango reescribe y que solo se deshace
  con un backup (CAP-050).
- **FR-070**: Leer y guardar las preferencias de energía (documento completo con
  diferencias, con confirmación); validación, información, consumo fósil y
  previsión solar quedan `read` en la tabla (CAP-054).

#### 021 — configuración del sistema

- **FR-071**: Leer y cambiar la configuración del núcleo (ubicación, unidades,
  zona horaria, moneda…) con confirmación y diferencias; la detección queda
  `read` en la tabla (CAP-053).
- **FR-072**: Listar la exposición de entidades a asistentes y cambiarla en
  lote y la de las entidades nuevas, con confirmación (CAP-055).
- **FR-073**: Listar usuarios y sus sesiones (solo metadatos), crear usuarios
  sin credenciales, editarlos y borrarlos, con confirmación; nunca el
  propietario ni el usuario del propio Hermes (CAP-056).
- **FR-074**: Cambiar la configuración de red y HTTP de Core con confirmación y
  un aviso de pérdida de acceso de la interfaz (CAP-069).
- **FR-075**: Analytics y funciones de labs: lectura `read` y cambios `confirm`
  en la tabla (CAP-074).

#### 022 — control de Core y del Supervisor

- **FR-076**: Arrancar, reconstruir y fijar opciones de Core; recargar,
  reiniciar, reparar y fijar opciones del Supervisor (solo zona horaria, país,
  logging, actualización automática y diagnósticos), con confirmación salvo
  recargar; estadísticas de Core y del Supervisor `read` en la tabla (CAP-084).
- **FR-077**: Aplicar una sugerencia del centro de resolución con confirmación y
  una vista previa que traduce su efecto (reinicio, borrado, reinicio de
  fábrica…); ejecutar chequeos, el healthcheck y activar o desactivar un
  chequeo quedan `confirm` en la tabla (CAP-087, escritura).
- **FR-078**: Plugins (DNS, audio, multicast, observer, CLI): información y
  estadísticas `read`, actualizar, reiniciar y opciones `confirm` en la tabla
  (CAP-091).
- **FR-079**: Registros privados de Docker y opciones de Docker: lista `read`,
  altas, bajas y opciones `confirm`, con las credenciales tapadas en la vista
  previa y en el log (CAP-092).
- **FR-080**: Placas (LED, firmware) y servidores NTP: lectura `read` y
  escritura `confirm` en la tabla (CAP-094).

#### 032 — host y red del host

- **FR-081**: Apagar el host, cambiar el hostname, la swap y la ranura de
  arranque, con confirmación y un aviso explícito (nadie enciende el host a
  distancia; la ranura de arranque reinicia en el OS anterior) (CAP-086).
- **FR-082**: Recargar la red del host, editar una interfaz y crear una VLAN,
  con confirmación y un aviso fuerte; nunca sobre la interfaz por la que entra
  Hermes, porque el Supervisor no revierte solo (CAP-090).

#### 023 — Assist y conversación

- **FR-083**: Listar agentes de conversación y frases, analizar una frase sin
  ejecutarla y procesarla con confirmación (ejecuta intents) (CAP-060).
- **FR-084**: Pipelines de Assist, motores de voz, LLM, AI Task y satélites:
  lectura `read` y escritura `confirm` en la tabla (CAP-061, CAP-062,
  CAP-063).

#### 024 — menores de Core

- **FR-085**: Leer una instantánea reducida de una cámara y una entidad
  `image`; preferencias de cámara `read`/`confirm` en la tabla (CAP-059).
- **FR-086**: Restablecer la configuración de un dashboard con confirmación,
  con la misma protección del dashboard principal que el resto de tools de
  Lovelace; contextos de trazas, temas, webhooks, segmentos de aspiradores y
  radiofrecuencia quedan `read` en la tabla (CAP-071).
- **FR-087**: Calendario y tareas, tags, navegación de medios, orden e ids de
  los registros e imágenes subidas: lectura `read` y escritura `confirm` en la
  tabla (CAP-065, CAP-066, CAP-067, CAP-070, CAP-072).
- **FR-088**: Credenciales de aplicación: lectura `read` en la tabla con
  `client_secret` siempre fuera de la respuesta (CAP-073).

#### 025 — integraciones específicas (clase C)

- **FR-089**: Los 192 comandos de clase C (Z-Wave JS, ZHA, Matter, Thread y
  OTBR, MQTT, USB y Bluetooth, y el resto) se clasifican uno a uno: lecturas
  `read`; escrituras `confirm` tras revisarlas; lo que devuelve secretos, borra
  la red, restaura firmware o necesita una acción física o un PIN, `deny`;
  suscripciones, `deny` salvo las de un solo mensaje (CAP-100 a CAP-106).
- **FR-090**: La guía tiene un tema por grupo de integraciones con los comandos
  más útiles y sus cargas (CAP-100 a CAP-106).

#### 026 — escritura en el Marketplace

- **FR-091**: Instalar, desinstalar, fijar versión, añadir y quitar
  repositorios, refrescar, ignorar y reconocer avisos críticos del
  Marketplace, con confirmación, backup previo y textos de terceros marcados;
  nunca conectar GitHub ni aceptar el aviso de riesgos; anotaciones por nombre
  exacto, nunca por el prefijo `ha_marketplace_` (CAP-075).

#### 027 — plataforma y deprecaciones

- **FR-092**: La descripción de `sv_get_job_status` y la guía explican que
  cualquier entrada en `errors` da `success: false` mientras el Supervisor no
  distinga avisos de fatales (CAP-025).
- **FR-093**: La hoja de ruta recoge los hosts CIMD conocidos de los clientes;
  el valor por defecto de `oauth_cimd_allowed_hosts` no cambia en este
  programa (CAP-026).
- **FR-094**: La investigación de `outputSchema` y de la vía nativa de MCP
  para pedir datos a mitad de una llamada queda escrita en la hoja de ruta; los
  dos pasos actuales no cambian (CAP-028).
- **FR-095**: Las descripciones y traducciones de las opciones usan «apps»
  donde el Supervisor ya lo hace, sin renombrar ninguna tool (CAP-029).
- **FR-096**: La hoja de ruta fija la retirada de los alias `ha_hacs_*` en la
  1.3.0 y la de `ha_remove_device_from_config_entry` antes de HA 2027.9; en la
  1.2.0 las dos siguen (CAP-030, CAP-031).
- **FR-097**: El socket Unix del Supervisor para apps y la API `/v2` quedan
  documentados como bloqueados por el Supervisor, con lo que hará falta cuando
  se publiquen; el test de deriva de FR-005 avisará de los cambios de rutas
  (CAP-032, CAP-033).

#### Cierre del programa

- **FR-098**: Al cerrar el programa no queda en la tabla ninguna entrada con
  motivo «pendiente de tool dedicada», la matriz de trazabilidad está completa,
  la entrada 1.2.0 del CHANGELOG cubre todos los bloques y las dudas para el
  final están listadas para el mantenedor.

### Entidades clave

- **Capacidad (CAP)**: algo que HA ofrece a un administrador y Hermes no tiene;
  identificador estable de research R-2, con prioridad, riesgo y origen.
- **Entrada de la tabla de clasificación**: comando WebSocket de Core o
  plantilla de ruta del Supervisor, con categoría, motivo, familia, tool
  dedicada, CAP y marcas de ejecución.
- **Familia de tools**: grupo con nombre que se puede desactivar; cada tool
  pertenece a una.
- **Inventario**: lista extraída del código de HA de una versión concreta; la
  fuente de la tabla y del test de deriva.
- **Sub-feature**: unidad de especificación e implementación del programa
  (009–032), con su propia spec en `specs/NNN-nombre/`.

## Exclusiones

### Clase B: no aplica a un servidor MCP (103 comandos de Core, 67 rutas del Supervisor)

Entran en la tabla como `deny` con el motivo de su grupo:

| Grupo | Por qué queda fuera |
|---|---|
| Suscripciones y streaming (`subscribe_*`, `*/subscribe`, `history/stream`, `logbook/event_stream`, logs `follow`) | MCP es petición-respuesta y Hermes no tiene estado entre llamadas; `ha_wait_for_event` y FR-061 cubren las esperas puntuales y FR-009 las de un solo mensaje |
| Datos internos del frontend (iconos, traducciones, datos de usuario de la UI, paneles) | Son para el navegador; las traducciones de Repairs se usan por dentro (FR-056) |
| Vistas previas en vivo de formularios de helpers | Suscripciones de la interfaz |
| Depurador paso a paso de trazas | Interactivo |
| Vídeo y audio en el navegador (HLS, WebRTC, captura de audio) | Binario o tiempo real |
| Ayudas de formulario, orden, sugerencias, `slugify`, `ping`, negociación del protocolo | Sin valor para un agente |
| Ingress y señales internas entre Core, Supervisor y apps | Las usa el frontend u otra app; algunas exigen ser Core |
| Alias legados de rutas del Supervisor | Se usa la ruta canónica |
| Iconos y logos de la tienda | Binario para la interfaz |
| `auth/current_user`, `entity/source`, lotes de la UI, `marketplace/repository/info` | Hermes no es una persona o ya hay equivalente |

### Clase D: peligroso o no automatizable por diseño (51 comandos, 20 rutas)

Entran en la tabla como `deny` con su motivo: cuenta de Nabu Casa (`cloud/*`);
consola de depuración (Python arbitrario); tokens de larga duración, MFA,
firma de rutas y revocación de sesiones (`auth/*`); contraseñas y nombres de
usuario; `client_secret` de OAuth de terceros; login de GitHub y aceptación
humana del riesgo del Marketplace; `execute_script` (el camino seguro ya
existe); invocar webhooks; la pipeline de Assist con audio; rutas `core_only`
del Supervisor; escalada de privilegios o borrado total; entrada arbitraria
por `stdin`; parar Core; congelar Core; subir y descargar backups binarios;
operaciones que exigen hardware o reinicio, borran imágenes o rebajan la
seguridad. El detalle por grupo está en research R-4.

## Dudas para el final

No bloquean el programa; las decide el mantenedor al cerrarlo.

- **D-01**: Las candidatas D viables con salvaguardas fuertes (research R-4):
  lectura de la cuenta de Nabu Casa; exposición a Alexa y Google; conectar o
  desconectar Remote UI; revocar sesiones y fijar su caducidad;
  `execute_script` con vista previa; la pipeline de Assist solo texto;
  borrar credenciales de aplicación; cambiar un nombre de usuario; `stdin` de
  apps con lista blanca; parar Core; canal del Supervisor.
- **D-02**: Bajar `hassio_role` a `manager` tras la prueba manual (cambio de
  permisos que el Supervisor enseña al actualizar).
- **D-03**: Familias nuevas de riesgo alto (usuarios, red del host y de HTTP,
  escritura del Marketplace, cámaras) activas por defecto, como manda la
  decisión, o desactivadas por defecto.
- **D-04**: Coste de contexto: con todas las familias activas la lista de tools
  pasará de unas 216 a unas 330–360 (de ~215 KB a unos 350 KB de JSON). ¿Un
  conjunto por defecto más pequeño en una versión posterior?
- **D-05**: Ejecutar el banco también contra la versión mínima declarada (HA
  2024.10) en una matriz del CI.
- **D-06**: Llevar la VM con HAOS a un runner del CI con KVM, como job nocturno
  o manual.
- **D-07**: Unificar la forma de las listas de las tools existentes (CAP-023)
  en la 1.3.0, con aviso previo.
- **D-08**: Versión exacta de la retirada de `ha_remove_device_from_config_entry`
  (propuesta: 1.3.0, junto con los alias `ha_hacs_*`).
- **D-09**: Valor por defecto restrictivo de `oauth_cimd_allowed_hosts`
  (CAP-026).
- **D-10**: Adoptar la vía nativa de MCP para pedir datos a mitad de una
  llamada como segunda forma de confirmar (CAP-028).

## Supuestos

- **S-01**: Los inventarios de research se extrajeron del código de Core
  2026.11.1 y del Supervisor 2026.11.0 sin ejecutarlos; el banco de 010 y la
  revisión manual de 011 corrigen los errores de clasificación que tengan.
- **S-02**: La 1.2.0 sale entera o no sale: no hay versiones intermedias, así
  que la clasificación transitoria `deny` «pendiente» nunca llega a usuarios;
  si una sub-feature se cae del programa, su capacidad queda inalcanzable
  (fail-closed) y el cierre lo hace visible.
- **S-03**: GitHub Actions es gratis en repositorios públicos con los runners
  estándar y puede arrancar la imagen de Core como servicio del job.
- **S-04**: El Supervisor simulado solo tiene que cubrir lo que Hermes usa al
  arrancar y el reenvío a Core; las tools `sv_*` se siguen probando con los
  simuladores de la suite y, en real, en la VM o en vivo (manual).
- **S-05**: Los nombres de tools de research R-2 son propuestas; cada sub-spec
  fija los definitivos dentro de las convenciones de FR-018.
- **S-06**: Medido en research: la lista de las 216 tools ocupa unos 215 KB de
  JSON (~1 KB por tool).

## Fuera de alcance

- La clase B y la clase D (ver Exclusiones), y las candidatas D-01.
- Retirar los alias `ha_hacs_*` o `ha_remove_device_from_config_entry`.
- Cambiar `hassio_role`, el valor por defecto de `oauth_cimd_allowed_hosts` o
  la forma de respuesta de las tools existentes.
- Montar el Supervisor real o una VM en el CI o en la máquina del mantenedor.
- Fusionar a `main`, etiquetar y publicar (los decide el mantenedor).
- El socket Unix y la API `/v2` del Supervisor mientras no se publiquen.

## Criterios de éxito *(obligatorio)*

- **SC-001**: Cero comandos de los 623 del inventario de Core y cero rutas de
  las 254 del Supervisor sin clasificar en la tabla, y el test de deriva pasa.
- **SC-002**: El 100 % de las CAP de clase A y C (CAP-040 a CAP-106, 58 CAP)
  está cubierto por una tool dedicada registrada o por entradas `read`/`confirm`
  de la tabla, cada una con al menos un test automático; las CAP 001–038 tienen
  su FR con test o, si son manuales o documentales, su entrada en la hoja de
  ruta.
- **SC-003**: Cero comandos o rutas con verbo de escritura (o método distinto
  de `GET`) clasificados como `read`, salvo las excepciones listadas y
  justificadas.
- **SC-004**: En el 100 % de los casos probados, un comando `dedicated`,
  `deny` o desconocido pedido por una genérica no llega a HA ni al Supervisor;
  cada guarda tiene su control negativo anotado.
- **SC-005**: Con la configuración por defecto, los 216 nombres de tools de la
  1.1.2 siguen en la lista con las mismas anotaciones, y con todas las familias
  nuevas y las genéricas desactivadas la lista tiene exactamente esos 216
  nombres.
- **SC-006**: El 100 % de las tools `ha_*` que modifican y se pueden ejecutar
  sin hardware, Supervisor, internet ni nube se han ejecutado en el banco
  contra HA Core 2026.11.1 real con su efecto comprobado, y el 100 % de las
  tools dedicadas nuevas de Core también.
- **SC-007**: La suite completa y todos los checks del CI (tests, banco de
  Core, Semgrep y CodeQL) están en verde en la punta de la rama al abrir el PR
  final.
- **SC-008**: Ningún valor centinela de secreto aparece en respuestas, vistas
  previas, errores ni log en los tests de las familias con datos sensibles.
- **SC-009**: La versión es 1.2.0 en los tres sitios y el CHANGELOG tiene una
  sola entrada nueva, con una sección por bloque del programa.
- **SC-010**: La revisión del diff final no encuentra datos personales ni
  identificadores de modelos.
- **SC-011**: Cada pendiente manual (Supervisor real, `hassio_role: manager`,
  pruebas en vivo de las tools nuevas) tiene su procedimiento y su casilla en
  la hoja de ruta.
- **SC-012**: La redacción de 1 MiB sin espacios tarda menos de 1 s en el CI
  (hoy, 30 KB tardan unos 0,5 s).
