# Especificación: Hermes 1.2.0 — diagnóstico del Supervisor (sub-feature 013)

**Directorio de la spec**: `specs/013-diagnostico-supervisor`

**Creada**: 2026-11-14

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T008 de su `tasks.md` y cubre **CAP-081 y CAP-085
con tools dedicadas, la parte de lectura de CAP-087, y CAP-088 y CAP-089 por
la tabla** (FR-044…FR-048 de la 008). Depende de la 009 (redacción lineal,
CAP-010) y de la 011 (tabla, genéricas y familias).

**Entrada**: `specs/008-cobertura-total/` (spec, plan con la matriz de
trazabilidad, research CAP-081…CAP-089 e `inventario/supervisor-rutas.tsv`),
la spec 011 (`command_table.py`, `command_policy.py`, `tool_families.py`, las
genéricas `sv_read_api`/`sv_call_api`) y el código de Hermes:
`tools/addons.py` (`sv_get_addon_logs`, `_ultimas_lineas_que_caben`,
`_es_hermes`), `tools/supervisor.py`, `ha.py` (`sv_request`,
`sv_request_text`), `security.py` (`redact_secrets`), `logging_setup.py`
(`redact_network`), `tools/_annotations.py` y `tools/guide.py`. Contrastado con
el código del Supervisor 2026.11.0 (`supervisor/api/__init__.py`, `host.py`,
`os.py`, `jobs.py`, `resolution.py`, `security.py`, `host/logs.py`,
`hardware/disk.py`).

## Clarificaciones

### Sesión 2026-11-14

Decisiones vinculantes del programa (ya están en la 008 y en la 011):

- CAP-081 (logs del sistema) y CAP-085 (disco, host y OS: lectura) van por
  **tools dedicadas**; la lectura de CAP-087 (jobs y sugerencias de un issue),
  CAP-088 (hardware, seguridad, Docker y hora) y CAP-089 (red del host) van
  **por la tabla** con `sv_read_api`.
- Todo es **lectura**. La escritura del control de Core y del Supervisor
  (CAP-084, CAP-087 escritura) es de la 022, y la de host y OS (CAP-086,
  CAP-090), de la 032: esta sub-feature no la toca.
- Las tools nuevas van en una **familia nueva** de la 1.2.0 (FR-010 de la 008).
- En el banco de pruebas de la 010 el Supervisor es simulado y solo reenvía a
  Core. Las tools `sv_*` de esta sub-feature se prueban con tests unitarios
  contra un Supervisor simulado (respuestas con la forma del Supervisor
  2026.11.0); su **prueba en vivo queda pendiente** para la 014 o para el
  cierre del programa.

Decisiones tomadas al especificar (no había a quién preguntar; se justifican
en [research.md](research.md)):

- P: ¿Una familia o dos? → R: **una**, `system_diagnostics` («desde» 1.2.0,
  desactivable), con dos módulos: `system_logs` (CAP-081) y `host_system`
  (CAP-085). Un tema de guía con el mismo nombre (research R-1).
- P: ¿Qué hace `sv_get_addon_logs` con el arranque? → R: dos argumentos
  **opcionales** nuevos, `boot` y `latest`, cuyo valor por defecto reproduce la
  1.1.2 (FR-020 de la 008). La tool sigue en la familia `supervisor` (research
  R-3).
- P: ¿Cómo se pide un arranque? → R: `boot` acepta un **desplazamiento**
  entero (0 = arranque actual, -1 = el anterior…; los positivos cuentan desde
  el más antiguo, como el Supervisor) o un **identificador** de arranque de 32
  caracteres hexadecimales. `latest` (solo el último arranque del contenedor)
  y `boot` se excluyen (research R-2).
- P: ¿Qué pasa con `GET /host/disks`? → R: no tiene tool en el research de la
  008 (lista los discos montables, que es de los montajes de la 019): pasa a
  **`read` en la tabla**, como lectura menor de una CAP dedicada que la 008
  permite si la sub-spec lo justifica (research R-5).
- P: ¿`/jobs/info` con tool o por la tabla? → R: **por la tabla** (`read`), como
  dice FR-046 de la 008, aunque la 011 lo dejó «pendiente de tool dedicada
  (spec 013)». Lo mismo para `/resolution/issue/{issue}/suggestions` (research
  R-5).
- P: ¿Comprobación de integridad (`POST /security/integrity`)? → R: sigue
  **`deny`**: el Supervisor 2026.11.0 la eliminó y responde 410 Gone. Es una
  desviación de FR-047 de la 008, que la pedía `confirm`, impuesta por la
  versión de destino (research R-6).
- P: ¿Se redactan los números de serie de los discos? → R: **no** en la
  respuesta (el identificador del disco ya los lleva y es lo que se necesita
  para elegir un disco), y **nunca** en el log (research R-7).
- P: ¿Profundidad del uso de disco? → R: `max_depth` de 0 a 3 (por defecto 1,
  el del Supervisor) y, en cada nivel, los 20 hijos que más ocupan, con
  cuántos se omiten y cuánto ocupan (research R-4).

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es el administrador de Home Assistant que diagnostica su sistema
desde un cliente MCP.

### Historia 1 — Ver por qué se cayó algo, también tras un reinicio (Prioridad: P1)

Quien tiene un Core que no arranca, un Supervisor que falla o un host que se
reinició solo quiere leer los logs de cada pieza, incluidos los del arranque
anterior, sin entrar por SSH.

**Prueba independiente**: con un Supervisor simulado, cada tool de logs pide la
ruta correcta con `lines`, devuelve el texto redactado y, si no cabe, sus
últimas líneas.

**Escenarios de aceptación**:

1. **Dado** un Core que acaba de reiniciarse, **cuando** el agente llama a
   `sv_get_core_logs(boot=-1)`, **entonces** recibe el log de Core del
   arranque anterior del host, redactado y dentro del tope.
2. **Dado** un log con una contraseña o un JWT, **cuando** se lee por
   cualquiera de las tools de logs, **entonces** el valor no aparece en la
   respuesta ni en el log de Hermes, y `redacted` es `true`.
3. **Dado** un log más grande que `response_max_bytes`, **cuando** se lee,
   **entonces** llegan sus últimas líneas que caben, con `truncated: true`,
   `lines_returned` y una pista.
4. **Dado** que el agente no sabe qué arranques hay, **cuando** llama a
   `sv_list_boots`, **entonces** recibe la lista de arranques del más reciente
   al más antiguo con su desplazamiento y su identificador.
5. **Dado** un servicio del host con problemas, **cuando** el agente llama a
   `sv_list_host_log_identifiers` y luego a `sv_get_host_logs(identifier=…)`,
   **entonces** recibe el journal de ese servicio.
6. **Dado** un add-on que se colgó, **cuando** el agente llama a
   `sv_get_addon_logs(slug, latest=true)` o con `boot`, **entonces** recibe
   solo el último arranque del contenedor o el del arranque pedido; sin esos
   argumentos, la respuesta es la de la 1.1.2.

### Historia 2 — Saber qué llena el disco y cómo está el sistema operativo (Prioridad: P1)

Quien tiene el disco lleno (una causa frecuente de fallos) quiere saber qué
ocupa el espacio, en qué versión está el OS, si hay swap y qué servicios del
host fallan.

**Prueba independiente**: con un Supervisor simulado, cada tool pide su ruta y
devuelve su respuesta acotada; en una instalación sin Home Assistant OS el
error dice por qué.

**Escenarios de aceptación**:

1. **Dado** un disco casi lleno, **cuando** el agente llama a
   `sv_get_disk_usage(max_depth=2)`, **entonces** recibe el total, lo usado y
   el desglose por carpeta hasta dos niveles, con como mucho 20 hijos por
   nivel ordenados por tamaño y lo omitido resumido.
2. **Dado** un montaje de red, **cuando** se pide `sv_get_disk_usage(disk=<nombre>)`,
   **entonces** se pide ese montaje; un nombre con forma inválida se rechaza
   sin llamar al Supervisor.
3. **Dado** un servicio del host en estado `failed`, **cuando** el agente llama
   a `sv_list_host_services(state="failed")`, **entonces** lo ve.
4. **Dado** un sistema con Home Assistant OS, **cuando** se llama a
   `sv_get_os_info`, `sv_get_swap` y `sv_list_datadisk_candidates`,
   **entonces** se reciben versión, slots de arranque, disco de datos, swap y
   discos candidatos; **dado** un sistema sin él, **entonces** el error dice
   que hace falta Home Assistant OS.

### Historia 3 — El resto del diagnóstico por la tabla (Prioridad: P2)

Quien diagnostica quiere leer jobs, sugerencias del centro de resolución,
hardware, seguridad, Docker, hora y red del host sin una tool por cada cosa.

**Prueba independiente**: `sv_read_api` ejecuta cada ruta de lectura de
CAP-087 (lectura), CAP-088 y CAP-089 contra el Supervisor simulado; las rutas
de escritura siguen rechazadas.

**Escenarios de aceptación**:

1. **Dado** `GET /jobs/info`, **cuando** el agente llama a `sv_read_api`,
   **entonces** recibe todos los jobs del Supervisor (no solo los de Hermes).
2. **Dado** `GET /hardware/info`, `/hardware/audio`, `/security/info`,
   `/docker/info`, `/time/info`, `/network/info`,
   `/network/interface/{interface}/info`,
   `/network/interface/{interface}/accesspoints`, `/host/disks` o
   `/resolution/issue/{issue}/suggestions`, **cuando** se pide con
   `sv_read_api`, **entonces** se ejecuta y se devuelve redactado.
3. **Dado** `POST /security/integrity`, **cuando** se pide por cualquier
   genérica, **entonces** se rechaza sin llamar al Supervisor y el motivo dice
   que el Supervisor 2026.11 la eliminó.
4. **Dado** la red del host, **cuando** se lee, **entonces** el log de Hermes
   no lleva direcciones IP, MAC ni nombres de red.
5. **Dado** cualquier ruta de logs, disco u OS de esta sub-feature, **cuando**
   se pide por `sv_read_api`, **entonces** la respuesta es
   `use_dedicated_tool` con el nombre de la tool.

### Historia 4 — Nada de lo que funciona hoy cambia (Prioridad: P1)

Quien usa la 1.1.2 quiere que sus llamadas sigan igual, y quien no quiere más
tools, poder apagarlas.

**Escenarios de aceptación**:

1. **Dado** `sv_get_addon_logs(slug, lines)` como en la 1.1.2, **entonces** la
   ruta, los parámetros y la forma de la respuesta son los de la 1.1.2.
2. **Dado** `tool_families_disabled: [system_diagnostics]`, **entonces** las 11
   tools nuevas no se registran, sus rutas siguen `dedicated` en la tabla, y
   `sv_get_addon_logs` conserva `boot` y `latest`.

### Casos límite

- `boot` y `latest` a la vez → `invalid_argument`, sin llamar al Supervisor.
- `boot` fuera de lo que el journal tiene → el error del Supervisor («Logs only
  contain N boots»), redactado, como `error`.
- `boot` con forma inválida (texto, decimales, identificador que no es
  hexadecimal de 32) o `identifier` con caracteres fuera del alfabeto
  permitido, que empieza por punto o de más de 64 caracteres →
  `invalid_argument` sin llamar al Supervisor; el log no copia el valor.
- `plugin` que no es `dns`, `audio` ni `multicast` → `invalid_argument` con la
  lista válida (`cli` y `observer` no tienen log en el Supervisor 2026.11.0).
- `lines` fuera de [1, 1000] → se acota, como hoy en `sv_get_addon_logs`; el
  Supervisor devuelve al menos 2 líneas.
- `latest` en el host: no existe; `sv_get_host_logs` no lo ofrece.
- Journal no disponible: el Supervisor responde con error, o, en su propio log,
  cae al log del contenedor sin respetar `boot` ni `latest`; la descripción de
  `sv_get_supervisor_logs` lo dice.
- Log de Hermes leído por el host (`identifier` `addon_<slug de Hermes>` o
  `app_<slug de Hermes>`) → se aplica también `redact_network`, igual que en
  `sv_get_addon_logs` sobre Hermes.
- `max_depth` fuera de [0, 3] → `invalid_argument`. Montaje de red lento → el
  Supervisor espera hasta 60 s; Hermes espera algo más antes de dar el error.
- Sin Home Assistant OS (Supervised), o OS < 15 para la swap → el Supervisor
  responde 404; la tool devuelve `error` con una pista que lo explica.
- Respuesta de la lista de identificadores o de servicios más grande que el
  tope → la recorta el tope central con `truncated`.
- Supervisor caído → el error de conexión de siempre.

## Requisitos *(obligatorio)*

Cada FR cita el FR de la 008 y la CAP que cubre.

### Requisitos funcionales

#### Logs del sistema (CAP-081)

- **FR-001**: `sv_get_core_logs(lines=100, boot=None, latest=False)` lee el
  journal de Core: `GET /core/logs`, `/core/logs/latest` o
  `/core/logs/boots/{boot}`, siempre con `lines` (008 FR-044; CAP-081).
- **FR-002**: `sv_get_supervisor_logs(lines=100, boot=None, latest=False)` lee
  el log del Supervisor por `/supervisor/logs[/latest|/boots/{boot}]`, y su
  descripción dice que, sin journal, el Supervisor devuelve el log de su
  contenedor sin filtrar por arranque (008 FR-044; CAP-081).
- **FR-003**: `sv_get_plugin_logs(plugin, lines=100, boot=None, latest=False)`
  lee el log de un plugin (`dns`, `audio` o `multicast`) por
  `/{plugin}/logs[/latest|/boots/{boot}]` (008 FR-044; CAP-081).
- **FR-004**: `sv_get_host_logs(lines=100, boot=None, identifier=None)` lee el
  journal del host por `/host/logs`, `/host/logs/boots/{boot}`,
  `/host/logs/identifiers/{identifier}` o
  `/host/logs/boots/{boot}/identifiers/{identifier}` (008 FR-044; CAP-081).
- **FR-005**: `sv_list_host_log_identifiers(search=None)` devuelve los
  identificadores de syslog del journal (`/host/logs/identifiers`), ordenados,
  con el sobre `{count, items, truncated}` y, si se pasa, filtrados por
  subcadena sin distinguir mayúsculas (008 FR-044, FR-018; CAP-081).
- **FR-006**: `sv_list_boots()` devuelve los arranques del journal
  (`/host/logs/boots`) como lista `{offset, boot_id}` del más reciente
  (`offset` 0) al más antiguo, con el sobre común (008 FR-044, FR-018;
  CAP-081).
- **FR-007**: `sv_get_addon_logs(slug, lines=100, boot=None, latest=False)`:
  con `boot` pide `/addons/{slug}/logs/boots/{boot}`; con `latest`,
  `/addons/{slug}/logs/latest`; sin ninguno de los dos, exactamente la
  petición y la respuesta de la 1.1.2 (008 FR-044, FR-020; CAP-081).
- **FR-008**: Validación común, fail-closed y antes de llamar al Supervisor:
  `boot` es un entero de -999 a 999 o 32 caracteres hexadecimales en
  minúsculas (se normaliza); `boot` y `latest` se excluyen; `identifier`
  casa `^[A-Za-z0-9_@-][A-Za-z0-9._@-]{0,63}$`; `plugin` es uno de los tres;
  `lines` se acota a [1, 1000]. Lo inválido devuelve `invalid_argument` con la
  regla que falla y sin copiar el valor (principio II, III; 008 FR-044).
- **FR-009**: Toda respuesta de log pasa por `redact_secrets`; la de Hermes
  (por `sv_get_addon_logs` sobre Hermes o por `sv_get_host_logs` con el
  identificador del contenedor de Hermes) también por `redact_network`.
  `redacted` dice si la redacción cambió algo. Si el log no cabe en
  `response_max_bytes`, se devuelven sus últimas líneas que caben, con
  `truncated`, `lines_returned` y la pista de la 1.1.2 (008 FR-044, FR-019;
  CAP-081, CAP-010).
- **FR-010**: Cada lectura de log deja un evento en el log de Hermes con la
  tool, la plantilla de ruta, `lines`, los bytes y `redacted`; nunca el
  contenido, ni el identificador de arranque ni un `identifier` inválido
  (principio II; 008 FR-019).

#### Disco, host y OS (CAP-085)

- **FR-011**: `sv_list_host_services(state=None)` devuelve los servicios
  systemd del host (`/host/services`: nombre, descripción y estado) con el
  sobre común, filtrados por estado exacto si se pasa (008 FR-045; CAP-085).
- **FR-012**: `sv_get_disk_usage(disk="default", max_depth=1)` lee
  `/host/disks/{disk}/usage?max_depth=N`: `disk` es `default` (el disco del
  sistema) o el nombre de un montaje (`^[A-Za-z0-9_]{1,64}$`); `max_depth` de
  0 a 3. En cada nivel quedan los 20 hijos que más ocupan; si hay más, el nodo
  lleva `children_omitted` y `omitted_bytes`. La espera cubre los 60 s que el
  Supervisor da a un montaje lento (008 FR-045; CAP-085).
- **FR-013**: `sv_get_os_info()` devuelve `/os/info` (versión, última,
  pendiente, placa, slot de arranque, disco de datos y slots) (008 FR-045;
  CAP-085).
- **FR-014**: `sv_get_swap()` devuelve `/os/config/swap` (tamaño y
  swappiness) (008 FR-045; CAP-085).
- **FR-015**: `sv_list_datadisk_candidates()` devuelve los discos candidatos a
  disco de datos (`/os/datadisk/list`) con el sobre común (008 FR-045;
  CAP-085).
- **FR-016**: Si el Supervisor responde con error (sin Home Assistant OS, OS
  anterior a la 15 para la swap, montaje desconocido, arranque inexistente),
  la tool devuelve `error` con el mensaje del Supervisor redactado y, para los
  404 de `/os/*`, una pista que dice que hace falta Home Assistant OS. Nunca
  inventa datos ni devuelve una respuesta vacía como si fuera buena. Las
  respuestas JSON de FR-005, FR-006 y FR-011…FR-015 pasan por
  `redact_structure` antes de devolverse, como defensa en profundidad aunque
  hoy no lleven secretos (principio I, III, V; 008 FR-045).

#### Tabla de clasificación (CAP-081, CAP-085, CAP-087 lectura, CAP-088, CAP-089)

- **FR-017**: Pasan a `dedicated`, en el mismo cambio que su tool, las 28
  entradas del Supervisor que usan las tools de FR-001…FR-007 y FR-011…FR-015
  (lista en [data-model.md](data-model.md)), con la familia de la tool. Las
  variantes `follow` y los alias `/homeassistant/logs*` siguen `deny`.
  Regenerar con `scripts/inventario/generar_tabla.py` deja la tabla idéntica
  (008 FR-012, FR-044, FR-045; CAP-001).
- **FR-018**: Pasan a `read` `GET /jobs/info` y
  `GET /resolution/issue/{issue}/suggestions` (008 FR-046; CAP-087 lectura) y
  `GET /host/disks` (lectura menor de CAP-085, justificada). La regla del test
  de la tabla que exige «pendiente de tool dedicada» para la clase A de vía
  D/D+T/D+X admite `dedicated` y, para las claves listadas con su porqué, `read`
  (008 FR-046; CAP-087, CAP-085).
- **FR-019**: `GET /hardware/info`, `/hardware/audio`, `/security/info`,
  `/docker/info` y `/time/info` siguen `read`, con un test que las ejecuta por
  `sv_read_api` contra el Supervisor simulado; `POST /security/integrity` sigue
  `deny` con su motivo, y un test comprueba que no llega al Supervisor por
  ninguna genérica (008 FR-047; CAP-088).
- **FR-020**: `GET /network/info`, `/network/interface/{interface}/info` y
  `/network/interface/{interface}/accesspoints` siguen `read`, con un test que
  las ejecuta y comprueba que el log de Hermes no lleva direcciones, MAC ni
  nombres de red de la respuesta (008 FR-048; CAP-089).

#### Convenciones, familia, guía y documentación

- **FR-021**: Las 11 tools nuevas van en la familia nueva `system_diagnostics`
  (1.2.0, desactivable; módulos `system_logs` y `host_system`); se anuncian
  `readOnlyHint`, idempotentes y sin mundo abierto, con títulos correctos
  (`OS`); ninguna toma `confirmation_token`. Con la familia desactivada no se
  registran y sus entradas siguen `dedicated` (008 FR-010, FR-018; CAP-004).
- **FR-022**: Las 216 tools de la 1.1.2 conservan nombre, anotaciones y
  argumentos; la única diferencia de esquema que añade esta sub-feature es
  `boot` y `latest`, opcionales, en `sv_get_addon_logs`, anotada junto a las
  que ya permite la instantánea de esquemas de la 011 (008 FR-020).
- **FR-023**: `hermes_guide` tiene el tema `system_diagnostics` (con alias),
  que explica las 11 tools, `boot`/`latest`, y qué rutas de diagnóstico se
  leen por `sv_read_api`; el tema `supervisor` menciona `boot` y `latest` de
  `sv_get_addon_logs` (008 FR-011, FR-018).
- **FR-024**: Un test con valores centinela (contraseña, JWT, `token=`) en los
  logs de Core, Supervisor, host, plugin y add-on comprueba que no aparecen en
  la respuesta, en el error ni en el log de Hermes (008 FR-019; principio II).
- **FR-025**: Documentación en el mismo cambio: sección propia en
  `## [1.2.0]` de `hermes/CHANGELOG.md`; estado de la 013 en la tabla del
  programa de `docs/HOJA-DE-RUTA.md`, con la prueba en vivo de las 11 tools y
  de las rutas de la tabla como **pendiente manual** (014 o cierre); `README.md`
  y `README.es.md` sincronizados si nombran familias o recuentos de tools;
  `hermes/DOCS.md` con la familia nueva en la lista de `tool_families_disabled`;
  filas CAP-081, CAP-085, CAP-087, CAP-088 y CAP-089 de la matriz de la 008
  con las tools y los ficheros de test (008 FR-016, FR-021, FR-023, FR-024).

### Entidades clave

- **Petición de log**: fuente (Core, Supervisor, plugin, host, add-on),
  `lines`, arranque (`boot`: desplazamiento o identificador), `latest`,
  identificador de syslog (solo host).
- **Respuesta de log**: `source`, `route` (plantilla), `lines_requested`,
  `redacted`, `logs` y, si se recorta, `truncated`, `lines_returned`, `hint`.
- **Arranque**: `offset` (0 = actual) y `boot_id`.
- **Nodo de uso de disco**: `id`, `label`, `used_bytes`, `children` y, si se
  podan, `children_omitted` y `omitted_bytes`.
- **Entrada de la tabla**: la de la 011; cambian categoría, motivo, familia y
  tool (data-model).

## Fuera de alcance

- Cualquier escritura: reinicios, opciones y estadísticas de Core y del
  Supervisor, aplicar sugerencias, ejecutar chequeos (022); apagado del host,
  hostname, swap, slot de arranque y red del host (032); montajes (019);
  actualizaciones (015).
- Seguir un log en directo (`follow`): MCP es petición-respuesta.
- Logs de `cli` y `observer` (el Supervisor 2026.11.0 no los ofrece) y la API
  `/v2`.
- `GET /core/stats` y `/supervisor/stats` (CAP-084, 022).
- Cambiar `hassio_role` o el banco del Supervisor (014).
- La prueba en vivo contra un Supervisor real (014 o cierre del programa).

## Supuestos

- **S-01**: La 009 (redacción lineal de `redact_secrets`, CAP-010) y la 011
  completa (tabla, genéricas, registro por familias, guía con consulta de la
  tabla y la instantánea `esquemas_1_1_2.json`) están integradas en la rama
  antes de implementar. Si al empezar un tramo falta algo de la 011, el tramo
  se detiene y lo anota.
- **S-02**: Las formas de respuesta del Supervisor simulado salen del código
  del Supervisor 2026.11.0 leído (no de una instalación real) y usan datos
  ficticios (`192.0.2.x`, `light.salon`, `<slug>`).
- **S-03**: Hermes llama a la API v1 del Supervisor (sin `/v2`): el uso de
  disco lleva los ids heredados `addons_data` y `addons_config`.
- **S-04**: La 1.2.0 sale entera: los motivos «pendiente» que quedan en la
  tabla son de otras sub-features y los vigila el cierre (FR-098 de la 008).

## Criterios de éxito *(obligatorio)*

- **SC-001**: Las 11 tools nuevas están registradas con la configuración por
  defecto, con `readOnlyHint` y sin `confirmation_token`, y ninguna con la
  familia `system_diagnostics` desactivada.
- **SC-002**: Las 28 entradas de FR-017 son `dedicated` y apuntan a una tool
  registrada; las 3 de FR-018 son `read`; ninguna entrada de la tabla queda
  «pendiente de tool dedicada (spec 013)»; regenerar la tabla no cambia nada.
- **SC-003**: En el 100 % de los casos probados de argumento inválido
  (`boot`, `latest` con `boot`, `identifier`, `plugin`, `disk`, `max_depth`)
  no hay ninguna llamada al Supervisor.
- **SC-004**: Ningún centinela de secreto aparece en respuestas, errores ni log
  de las tools de logs; ninguna dirección de red de la respuesta de
  `/network/info` aparece en el log de Hermes.
- **SC-005**: Con las familias de la 1.2.0 desactivadas, la lista de tools es
  la de la 1.1.2 con las mismas anotaciones, y `sv_get_addon_logs` llamada
  como en la 1.1.2 hace la misma petición y devuelve la misma forma.
- **SC-006**: La suite pasa en el CI de Linux al final de cada tramo, con los
  mismos 6 fallos conocidos de Windows en local y ninguno más; cada tramo deja
  anotado su control negativo con recuentos.
- **SC-007**: La hoja de ruta lista la prueba en vivo de las 11 tools y de las
  rutas `read` de esta sub-feature como pendiente manual.
