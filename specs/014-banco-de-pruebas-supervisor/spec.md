# Especificación: banco de pruebas del Supervisor (procedimiento, matriz y `hassio_role`)

**Directorio de la spec**: `specs/014-banco-de-pruebas-supervisor`

**Creada**: 2026-11-14

**Estado**: Borrador

**Programa**: sub-feature 014 de la spec paraguas
[`specs/008-cobertura-total/`](../008-cobertura-total/spec.md) (tarea T009,
ola 2, tamaño S, 1 tramo). Cubre **CAP-006**, **CAP-022**, la parte de
**CAP-034** que toca al Supervisor y **CAP-035**; cumple **FR-016** y
**FR-017** de la 008 y la parte de **SC-011** que le toca.

**Entrada**: el banco de Core (010 y 028) ejecuta contra HA Core 2026.11.1 real
las tools `ha_*` que modifican, pero deja fuera 24 tools `sv_*` y `fs_*`
(`FUERA_DEL_BANCO` de la 028): reinicios, apagados, backups y restauraciones,
add-ons, avisos del centro de resolución y escrituras en `/config`. Esas solo
se prueban hoy con simuladores que escribe el propio proyecto. Además, el
comentario de `hassio_role` en `hermes/config.yaml` dice que `manager` y
`default` devuelven 403 en `/addons/self/options/config` y que esa ruta hace
falta para `bashio::config`; leyendo el código del Supervisor 2026.11.0, esa
ruta está en `api_bypass` (pasa con cualquier rol) y `hermes/run.sh` no usa
`bashio::config` (lee `/data/options.json` con `jq`). El comentario no dice la
verdad (principio V).

## Clarificaciones

### Sesión 2026-11-14

Decisiones del supervisor del programa, vinculantes:

- P: ¿Se monta la VM con HAOS? → R: **no**. Ni en la máquina del mantenedor ni
  en el CI se automatiza nada que cambie su sistema. El procedimiento se
  **documenta** y queda como **pendiente manual del final** (008, clarificación
  «Banco de pruebas» y «Fuera de alcance»).
- P: ¿Se cambia el rol? → R: **no**. El comentario dice la verdad sin cambiar
  `hassio_role: admin`. Bajar a `manager` es la duda D-02 de la 008 y exige
  probarlo en vivo.
- P: ¿Y la VM en un runner del CI con KVM? → R: queda como **duda para el
  final** (D-06 de la 008), sin implementarla.
- P: ¿Cuándo se prueban en vivo las tools nuevas del programa? → R: en una
  instalación real, **solo tras publicar**; en la VM, con una copia de
  desarrollo, cuando el mantenedor la monte. Las dos cosas son casillas de la
  hoja de ruta.

Decisiones tomadas al especificar (se anotan aquí en lugar de preguntar):

- P: ¿Scripts de apoyo para montar la VM? → R: **no** se versionan scripts. El
  procedimiento da los comandos dentro del documento, para que quien los
  ejecute los lea uno a uno; un script que nadie ejecuta es código sin probar
  en un repositorio público (principio VI; research R-3).
- P: ¿Dónde vive cada cosa? → R: el **procedimiento**, en un documento propio,
  `docs/BANCO-SUPERVISOR.md` (es largo y no es una hoja de ruta); la **matriz
  tool → entorno → resultado** y las **casillas de las pruebas manuales**, en
  `docs/HOJA-DE-RUTA.md`, como dice FR-016 de la 008, con un enlace al
  procedimiento.
- P: ¿Qué tools entran en la matriz? → R: **todas las que modifican** (las del
  registro de producción, con todas las familias activas, sin `readOnlyHint`),
  no solo las del Supervisor: la matriz de CAP-034 es «tool → entorno»; para
  las de Core el entorno es el banco y el resultado sale de sus inventarios.
  Así, una tool nueva que modifica, también una `sv_*` de las sub-features
  siguientes, no puede entrar sin su fila (research R-1).
- P: ¿Cómo no se queda vieja la matriz? → R: un **test de la suite normal** la
  compara con el registro de producción y con los inventarios del banco
  (`tests/banco/cobertura*.py`), que descubre por convención de nombres; si la
  028 u otra sub-feature integra su inventario, la matriz tiene que ponerse al
  día en el mismo cambio (research R-2).
- P: ¿Se puede comprobar sin la VM lo que dice el comentario de
  `hassio_role`? → R: en parte. Un test copia del Supervisor 2026.11.0 los
  patrones de `api_bypass` y del rol `manager` y comprueba que todas las rutas
  del Supervisor que usa Hermes casan con ellos; las excepciones, si aparecen,
  quedan listadas con su motivo y el comentario las nombra. La prueba en vivo
  sigue pendiente (research R-4).

## Escenarios de usuario y pruebas *(obligatorio)*

### Historia 1 — El mantenedor sabe montar el banco del Supervisor y probar en él (Prioridad: P1)

El mantenedor quiere, cuando decida hacerlo, montar una VM con Home Assistant OS
(Supervisor 2026.11.0, Core 2026.11.1), instalar en ella una copia de
desarrollo de Hermes y ejecutar las tools que el banco de Core no puede
ejecutar —en especial las que reinician, apagan, restauran o desinstalan— sin
arriesgar su instalación real, con una instantánea previa a la que volver.

**Prueba independiente**: `docs/BANCO-SUPERVISOR.md` existe, la hoja de ruta lo
enlaza y tiene las secciones obligatorias; un test de la suite normal lo
comprueba. Seguirlo en la VM es la prueba manual.

**Escenarios de aceptación**:

1. **Dado** el procedimiento, **entonces** dice cómo crear la VM (imagen
   oficial de HAOS, recursos, red aislada), cómo fijar y comprobar la
   versión de Core y anotar la del Supervisor, y cómo tomar y restaurar una
   instantánea, con ejemplos para al menos dos hipervisores.
2. **Dado** el procedimiento, **entonces** dice cómo instalar Hermes como
   add-on local construido desde el Dockerfile (sin la línea `image:`), con
   qué opciones de prueba (contraseña generada para la ocasión, nunca la real
   ni versionada) y cómo conectar un cliente MCP con TLS delante, como en
   producción.
3. **Dado** el procedimiento, **entonces** ordena las pruebas en tandas: las
   que no interrumpen nada, después cada una de las que reinician, apagan,
   restauran o desinstalan con su instantánea previa, y al final el cambio de
   rol; y dice qué comprobar en cada una y cómo anotar el resultado en la
   matriz.
4. **Dado** el procedimiento, **entonces** no contiene hostnames, IPs, slugs,
   contraseñas ni rutas personales: solo marcadores genéricos.

### Historia 2 — La hoja de ruta dice, tool por tool, dónde se ha probado de verdad (Prioridad: P1)

El mantenedor quiere una matriz con una fila por cada tool que modifica: en
qué entorno real se prueba (banco de Core, VM, instalación real) y con qué
resultado; y quiere que ninguna tool nueva que modifica entre sin su fila.

**Prueba independiente**: un test de la suite normal lee la matriz de la hoja
de ruta y la compara con el registro de producción y con los inventarios del
banco; quitar una fila, añadir una tool que no existe o contradecir un
inventario lo pone en rojo nombrando la tool.

**Escenarios de aceptación**:

1. **Dado** el registro de producción, **entonces** la matriz tiene
   exactamente una fila por cada tool sin `readOnlyHint`, ni más ni menos.
2. **Dado** una tool del inventario de probadas del banco, **entonces** su
   fila dice «banco de Core» y «ok»; una de fallos conocidos, «banco de Core»
   y «falla» con su hallazgo; una no ejecutable en el banco, otro entorno.
3. **Dado** una tool `sv_*` o una `fs_*` que modifica, **entonces** su entorno
   es «VM» y su resultado, mientras nadie la pruebe, «pendiente».
4. **Dado** una sub-feature posterior que añade una tool que modifica sin
   tocar la matriz, **entonces** el test cae en su rama nombrándola.
5. **Dado** un resultado «ok» fuera del banco (VM o instalación real),
   **entonces** la fila lleva la versión de Hermes y la fecha en la nota.

### Historia 3 — Las pruebas manuales abiertas tienen casilla y entorno (Prioridad: P2)

El mantenedor quiere que cada prueba manual pendiente tenga su casilla en la
hoja de ruta, diga dónde se hace (VM, instalación real o cliente) y, si se
puede hacer en la VM, remita al procedimiento.

**Prueba independiente**: un test comprueba que la sección de pruebas manuales
pendientes contiene las casillas de SC-011 de la 008 (Supervisor real,
`hassio_role: manager`, pruebas en vivo de las tools nuevas tras publicar) y
las de CAP-035.

**Escenarios de aceptación**:

1. **Dado** la sección «Pruebas manuales pendientes», **entonces** tiene
   casilla para: la matriz del Supervisor en la VM; `hassio_role: manager`;
   las pruebas en vivo de las tools nuevas del programa tras publicar; y las
   abiertas de CAP-035 (confirmar `fs_write_file` sin documento y la limpieza
   del directorio de confirmaciones, CIMD con Claude Code, primer byte tras el
   proxy, clave `homeassistant` en una HA antigua, Funnel en el 8443,
   `sv_get_resolution` con issues reales y trazas de un script).
2. **Dado** la casilla de `hassio_role: manager`, **entonces** ya no habla de
   `bashio::config` (Hermes no lo usa) y dice qué comprobar: arranque, lectura
   de las opciones de otros add-ons y cada tool `sv_*`.

### Historia 4 — El comentario de `hassio_role` dice la verdad (Prioridad: P1)

El mantenedor quiere que el comentario de `hassio_role` en `hermes/config.yaml`
describa el Supervisor 2026.11.0, sin cambiar el rol.

**Prueba independiente**: un test lee `hermes/config.yaml` y comprueba que el
rol sigue siendo `admin`, que el comentario ya no afirma el 403 ni la
dependencia de `bashio::config`, y que remite a la prueba pendiente; otro test
comprueba que las rutas del Supervisor que usa Hermes casan con `api_bypass` o
con el patrón de `manager` del Supervisor 2026.11.0.

**Escenarios de aceptación**:

1. **Dado** `hermes/config.yaml`, **entonces** `hassio_role` vale `admin`.
2. **Dado** el comentario, **entonces** dice que `/addons/self/options/config`
   pasa con cualquier rol desde el Supervisor 2026.11.0 (`api_bypass`), que
   Hermes no usa `bashio::config`, por qué se mantiene `admin` y que bajar a
   `manager` está pendiente de prueba manual.
3. **Dado** las rutas del Supervisor que usa Hermes, **cuando** una no casa con
   `api_bypass` ni con `manager`, **entonces** el test cae nombrándola, salvo
   que esté en la lista de excepciones con su motivo.

### Casos límite

- **Una tool cambia de anotación** (pasa a `readOnlyHint` o lo pierde): la
  matriz tiene que ganar o perder su fila en el mismo cambio; el test lo
  exige.
- **Se integra la 028 (u otra sub-feature con inventario del banco)** en una
  rama donde ya está la 014: el test descubre el inventario nuevo y cae hasta
  que la matriz refleja sus probadas como «ok».
- **Familias desactivadas**: la matriz se compara con el registro con todas
  las familias activas (el de la 008, FR-012), no con el de una configuración
  concreta.
- **Una ruta del Supervisor construida en tiempo de ejecución** (no literal):
  el test no puede leerla; la llamada tiene que estar declarada con su origen
  (por ejemplo, la tabla de clasificación de la 011, cuyas entradas `read` y
  `confirm` del Supervisor se comprueban también si la tabla existe).
- **El Supervisor de la VM ya no es 2026.11.0** (se actualizó antes de
  desactivar la actualización automática): el procedimiento dice cómo
  comprobarlo y que el resultado se anota con la versión real usada.
- **Una prueba destructiva deja la VM inservible**: se restaura la instantánea
  y se anota «falla» con la causa; nunca se repite en la instalación real.

## Requisitos *(obligatorio)*

### Requisitos funcionales

- **FR-001** *(008: FR-016; CAP-006)*: Existe `docs/BANCO-SUPERVISOR.md` con
  el procedimiento del banco del Supervisor: (a) crear una VM con la imagen
  oficial de HAOS, recursos mínimos y red aislada, con ejemplos para Hyper-V y
  para QEMU/libvirt; (b) fijar y comprobar Core 2026.11.1, anotar la
  versión real del Supervisor (no se puede fijar fuera del modo de
  desarrollo) y por qué no se desactiva su actualización automática; (c) tomar
  una instantánea antes de cada tanda y restaurarla; (d) instalar Hermes como
  add-on local construido desde el Dockerfile, sin la línea `image:` (slug
  `local_hermes`), con opciones de prueba y una contraseña generada para la
  ocasión que nunca se versiona; (e) poner TLS delante y conectar un cliente
  MCP como en producción; (f) las tandas de pruebas y, para cada tool de la
  matriz con entorno «VM», qué comprobar; (g) el cambio de rol a `manager`
  (FR-006); (h) cómo anotar el resultado en la matriz y limpiar la VM.
- **FR-002** *(008: FR-016; CAP-034, parte del Supervisor)*:
  `docs/HOJA-DE-RUTA.md` tiene una **matriz tool → entorno → resultado**,
  delimitada por marcadores, con una fila por cada tool del registro de
  producción (todas las familias activas) sin `readOnlyHint`, y las columnas
  tool, entorno, resultado y nota. Entorno ∈ {banco de Core, VM, instalación
  real}; resultado ∈ {ok, falla, pendiente}. Los simuladores de la suite
  normal no son un entorno de la matriz: corren siempre, para todas.
- **FR-003** *(008: FR-016, CAP-034: «las del Supervisor y las destructivas
  solo en la VM»)*: Reglas de la matriz: (a) toda `sv_*` que modifica y toda
  `fs_*` que modifica tienen entorno «VM»; (b) una tool de un inventario de
  probadas del banco tiene «banco de Core» y «ok», y «ok» con «banco de Core»
  solo lo puede tener una tool de esos inventarios; (c) una de fallos
  conocidos del banco tiene «banco de Core» y «falla»; (d) una no ejecutable
  en el banco tiene un entorno distinto de «banco de Core»; (e) una de
  `FUERA_DEL_BANCO` tiene «VM»; (f) «falla» lleva nota con la causa o el
  hallazgo; (g) «ok» en «VM» o «instalación real» lleva en la nota la versión
  de Hermes y la fecha. Las tools de Core que modifican y aún no están en
  ningún inventario tienen «banco de Core» y «pendiente».
- **FR-004** *(008: FR-016, FR-014)*: Un test de la suite normal comprueba
  FR-002 y FR-003: lee la matriz entre sus marcadores, la compara con el
  registro de producción y con los inventarios del banco, que descubre en
  `tests/banco/cobertura*.py` por convención de nombres (`PROBADAS*`,
  `FALLAN*`, `NO_EJECUTABLES*`, `FUERA_DEL_BANCO`), y cae nombrando cada tool
  que sobra, falta, se repite o contradice una regla.
- **FR-005** *(008: FR-016, SC-011; CAP-035)*: La sección «Pruebas manuales
  pendientes» de la hoja de ruta tiene casilla, con su entorno (VM, instalación
  real o cliente), para: la matriz del Supervisor en la VM (con enlace al
  procedimiento); `hassio_role: manager`; las pruebas en vivo de las tools
  nuevas del programa, solo tras publicar; y las abiertas de CAP-035. La
  casilla de `hassio_role: manager` deja de nombrar `bashio::config`. Un test
  comprueba que las casillas de SC-011 y de CAP-035 existen, con su entorno, y
  que la hoja de ruta enlaza el procedimiento.
- **FR-006** *(008: FR-017; CAP-022)*: El procedimiento documenta la prueba de
  `hassio_role: manager` en la VM: cambiar el rol en la copia local, reconstruir
  e instalar, y comprobar el arranque, la lectura de las opciones de otros
  add-ons y cada tool `sv_*` (lectura y escritura), con el criterio de éxito
  (ningún 403 nuevo en el log del Supervisor ni en las respuestas). El rol del
  add-on publicado no cambia (D-02 de la 008).
- **FR-007** *(008: FR-017; CAP-022)*: El comentario de `hassio_role` en
  `hermes/config.yaml` dice la verdad según el Supervisor 2026.11.0:
  `/addons/self/options/config` está en `api_bypass` y pasa con cualquier rol;
  Hermes no usa `bashio::config` (`run.sh` lee `/data/options.json`); con el
  código del Supervisor 2026.11.0, todas las rutas que usa Hermes están
  permitidas para `manager`, y el rol no se ha bajado porque falta probarlo en
  una instalación real (no dice de dónde salía el 403 de antes: no se puede
  comprobar; corregido en la convergencia, T021); se mantiene `admin`
  hasta probar `manager` en vivo, y esa prueba está en la hoja de ruta. El
  valor de `hassio_role` sigue siendo `admin`. Un test lo comprueba.
- **FR-008** *(008: FR-017; CAP-022, «qué añade `admin` y qué hay que
  probar»)*: Un test de la suite normal copia, citando fichero y versión, los
  patrones `api_bypass` y del rol `manager` de
  `supervisor/api/middleware/security.py` del Supervisor 2026.11.0 y comprueba
  que cada ruta del Supervisor que usa Hermes casa con uno de los dos. Las
  rutas salen de las llamadas a `sv_request` y `sv_request_text` del código
  (literales y f-strings), de las rutas del proxy de Core que usa `HAClient` y,
  si existe la tabla de clasificación de la 011, de sus entradas del
  Supervisor `read` y `confirm`. Una llamada con una ruta que no se puede leer
  estáticamente cae salvo que esté declarada con su origen. Las rutas fuera de
  `manager` solo se admiten en una lista de excepciones con motivo, que el
  comentario de FR-007 y la casilla de FR-005 nombran; hoy se espera vacía.
- **FR-009** *(008: FR-022, FR-023)*: Documentación en el mismo cambio: viñeta
  en la sección «Banco de pruebas» de `## [1.2.0]` de `hermes/CHANGELOG.md`;
  fila de la 014 a «hecha» en la tabla del programa de `docs/HOJA-DE-RUTA.md`;
  la frase de «Verificado contra» y el párrafo «Probar `hassio_role:
  manager`» al día; las filas de CAP-006, CAP-022, CAP-034 y CAP-035 de la
  matriz de trazabilidad de `specs/008-cobertura-total/plan.md` con sus tests.
  `README.md`, `README.es.md` y `hermes/DOCS.md` no cambian: no hay opciones
  ni comportamiento nuevos para el usuario.
- **FR-010** *(008: FR-018; principio VII)*: Cada requisito con test tiene su
  control negativo comprobado y anotado en el commit: quitar una fila de la
  matriz, poner «ok» a una `sv_*` sin nota, devolver el comentario viejo,
  cambiar el rol, y añadir una ruta fuera de `manager`.
- **FR-011** *(008: FR-013, decisión del supervisor; principio IX)*: **El
  código de producto no cambia**: en `hermes/` solo cambian el comentario de
  `config.yaml` y `CHANGELOG.md`. No se añade ninguna tool, opción, entrada de
  la tabla de clasificación ni familia, y no se versiona ningún script para
  montar la VM.

### Entidades clave

- **Matriz de pruebas**: tabla de la hoja de ruta; una fila por tool que
  modifica, con entorno, resultado y nota.
- **Inventarios del banco**: `tests/banco/cobertura*.py` (010, 028 y los que
  añadan otras sub-features).
- **Procedimiento del banco del Supervisor**: `docs/BANCO-SUPERVISOR.md`.
- **Patrones de acceso del Supervisor 2026.11.0**: `api_bypass` y el de
  `manager`, copiados en el test con su cita.
- **Rutas del Supervisor que usa Hermes**: las de las llamadas del código, las
  del proxy de Core y, si existe, las de la tabla de la 011.

Detalle en [data-model.md](data-model.md).

## Supuestos

- **S-01**: El Supervisor 2026.11.0 decide el acceso de un add-on con
  `api_bypass` y el patrón de su rol (`SecurityMiddleware`, leído en
  `fuentes/supervisor`); no hay otra comprobación por rol para las rutas que
  usa Hermes.
- **S-02**: El registro de producción con la configuración por defecto tiene
  todas las familias activas (008, decisión «Familias»), así que es el
  conjunto completo de tools.
- **S-03**: Las sub-features que añadan inventarios del banco siguen la
  convención de nombres de la 010 y la 028 (`PROBADAS*`, `NO_EJECUTABLES*`,
  `FALLAN*`, `FUERA_DEL_BANCO`); la 028 la fija en su contrato.
- **S-04**: HAOS se distribuye en imágenes para Hyper-V (`vhdx`), QEMU/KVM
  (`qcow2`), VMware (`vmdk`) y VirtualBox (`vdi`/`ova`). Core se puede actualizar a una
  versión concreta (`POST /core/update`), pero el Supervisor no: fuera del
  modo de desarrollo (`SUPERVISOR_DEV=1`), `POST /supervisor/update` ignora
  `version` y va a la última (`supervisor/api/supervisor.py` de 2026.11.0).
  Desactivar su actualización automática no lo fija: en cuanto hay uno más
  nuevo, la condición `supervisor_updated` bloquea instalar y actualizar
  add-ons, recargar la tienda y actualizar Core
  (`supervisor/jobs/decorator.py`). Corregido en la convergencia (T017).
- **S-05**: Un add-on local se construye desde `hermes/Dockerfile` cuando el
  manifiesto no tiene `image:` (comentario de `hermes/config.yaml`).

## Fuera de alcance

- Montar la VM, en la máquina del mantenedor o en el CI, y ejecutar en ella
  cualquier prueba: pendiente manual del final.
- La VM en un runner del CI con KVM (D-06 de la 008).
- Cambiar `hassio_role` (D-02 de la 008).
- Tools, opciones, entradas de la tabla de clasificación o familias nuevas.
- Ejecutar en el banco de Core lo que no es de la 014 (010 y 028).
- La frase «run.sh lee options.json con bashio» del docstring de
  `hermes/src/hermes/config.py`: es el mismo error que el comentario, pero
  está en código de producto y FR-017 de la 008 solo pide el comentario; se
  anota como hallazgo para otra sub-feature.

## Criterios de éxito *(obligatorio)*

- **SC-001**: La matriz tiene una fila por cada tool que modifica del registro
  de producción (hoy 124) y **0** filas de más; el test lo comprueba.
- **SC-002**: **24 de 24** tools `sv_*` y `fs_*` que modifican tienen entorno
  «VM» y un apartado en el procedimiento que dice qué comprobar.
- **SC-003**: **0** contradicciones entre la matriz y los inventarios del
  banco (probadas, fallos conocidos, no ejecutables y fuera del banco).
- **SC-004**: Las casillas de SC-011 de la 008 (Supervisor real,
  `hassio_role: manager`, pruebas en vivo de las tools nuevas) y las 7 de
  CAP-035 están en la hoja de ruta, con su entorno.
- **SC-005**: `hassio_role` sigue en `admin`; el comentario no contiene «403»
  ni afirma que Hermes use `bashio::config`.
- **SC-006**: El 100 % de las rutas del Supervisor que usa Hermes casan con
  `api_bypass` o con `manager` del Supervisor 2026.11.0, o están en la lista
  de excepciones con su motivo (hoy, 0 excepciones esperadas).
- **SC-007**: **0** líneas cambiadas en `hermes/` salvo el comentario de
  `hassio_role` en `config.yaml` y `CHANGELOG.md`.
- **SC-008**: En Windows, la suite completa da exactamente los 6 fallos
  conocidos; los controles negativos de FR-010 están anotados en el commit.
