# Especificación: Hermes 1.2.0 — plataforma y deprecaciones (sub-feature 027)

**Directorio de la spec**: `specs/027-plataforma-y-deprecaciones`

**Creada**: 2026-11-14

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T012 de su `tasks.md` y cubre **CAP-025, CAP-026 y
CAP-028…CAP-033** (FR-092…FR-097 de la 008), más los transversales que le
tocan (FR-018…FR-021, FR-023 y FR-024 de la 008, y FR-020 en concreto para
CAP-030 y CAP-031). Ola 2, tamaño S en la 008; aquí se parte en dos tramos
cortos (plan, «Desviaciones»).

**Entrada**: `specs/008-cobertura-total/` (spec, plan con la matriz de
trazabilidad, research R-0, R-1 y R-2), la sub-feature 011 (tabla
`command_table.py`, `tool_families.py`, generador e inventario), el código de
Hermes (`supervisor_jobs.py`, `tools/backups.py`, `tools/addons.py`,
`tools/registry_device.py`, `tools/config_entries.py`, `tools/hacs.py`,
`tools/guide.py`, `mcp_server.py`, `middleware.py`, `network.py`, `ha.py`,
`__main__.py`, `config.yaml`, `requirements.txt`), el SDK `mcp` 2.3.0 instalado
y el código de Home Assistant Core 2026.11.1 (`helpers/device_registry.py`,
`components/config/device_registry.py`, `components/hassio/`) y del Supervisor
2026.11.0 (`api/__init__.py`, `api/sockets.py`, `api/middleware/security.py`,
`api/supervisor.py`, `api/utils.py`, `jobs/__init__.py`, `backups/backup.py`,
`docker/homeassistant.py`, `docker/app.py`, `store/data.py`,
`apps/validate.py`, `const.py`), leídos sin ejecutar nada.

**Fuera de esta sub-feature** (otras del programa): cifrado de los safety
backups (031, CAP-027); `hassio_role` y la matriz de pruebas manuales (014);
la forma de las listas de las tools existentes (018, CAP-023); los logs y la
salud del Supervisor (013).

## Clarificaciones

### Sesión 2026-11-14

Decisiones vinculantes de la 008 y del supervisor del programa (no se discuten
aquí):

- **La 027 no retira nada en la 1.2.0** (decisión 3 de la 008): los alias
  `ha_hacs_*` se retiran en la 1.3.0 y `ha_remove_device_from_config_entry`
  sigue registrada y deprecada.
- **Lo que aún no existe en HA o en el Supervisor 2026.11** (el socket Unix
  para apps y la API `/v2` estable) **se prepara**: detección, avisos y tests
  contra el comportamiento que documenta el código fuente, sin activar nada que
  pueda romper la 1.2.0 en una instalación actual.
- **Lo que solo se puede decidir cuando salga la versión de HA** va como «duda
  para el final».
- El valor por defecto de `oauth_cimd_allowed_hosts` y los dos pasos de
  confirmación no cambian (FR-093 y FR-094 de la 008).

Decisiones tomadas al especificar (no había a quién preguntar; se justifican
en [research.md](research.md)):

- P: ¿Es verdad lo que pide FR-092 de la 008, «cualquier entrada en `errors`
  da `success: false`»? → R: **solo para el job que se consulta**. En el
  Supervisor 2026.11.0 los errores de un sub-job se guardan en ese sub-job
  (`child_jobs[].errors`) y no suben al padre: por ejemplo, una app que no se
  pudo guardar en un backup completo deja el error en el sub-job
  `backup_store_apps` y el backup termina y existe. Hoy `sv_get_job_status`
  no mira los sub-jobs y da `success: true`. Documentarlo sin más dejaría una
  descripción que, aun siendo cierta, esconde un fallo real; la 027 añade un
  campo `child_errors` (aditivo: `success` no cambia) y lo explica en la
  descripción y en la guía (research R-1). Si `success` debe tener en cuenta
  los sub-jobs queda como duda D-1.
- P: ¿Qué es «preparar» el socket Unix y la `/v2`? → R: **detectar y avisar,
  nunca usar**. Al arrancar, Hermes mira si el Supervisor le ha inyectado
  `SUPERVISOR_SOCKET` (hoy solo se inyecta en Core) y si la opción de
  desarrollo `supervisor_v2_api` está activada (`feature_flags` de
  `/supervisor/info`), lo anota en el log y sigue por TCP y por la V1, que el
  Supervisor sigue sirviendo con la V2 activada (research R-2 y R-3). La
  lectura es tolerante: un fallo no para el arranque.
- P: ¿Qué es «preparar» la retirada de `config/device_registry/remove_config_entry`
  en HA 2027.9? → R: si HA responde `unknown_command`, la tool deprecada lo
  traduce a un error claro que remite a `ha_remove_device`, sin reintentar con
  otro comando (el efecto sería otro y el token se dio para este). Hermes no
  decide la retirada por número de versión: si HA la aplaza, la tool sigue
  funcionando (research R-4).
- P: ¿Y los campos del dispositivo que HA retira (`config_entries` y
  `config_entries_subentries` en 2027.8, `primary_config_entry` en 2027.10)?
  → R: ya se usan solo como respaldo (desde la 1.0.12) o no se usan; la 027 lo
  fija con tests con la forma que tendrán las respuestas (research R-4).
- P: ¿Qué son «las traducciones de las opciones» si el add-on no tiene
  `translations/`? → R: se crean `hermes/translations/en.yaml` y `es.yaml` con
  el nombre y la descripción de cada opción, como el Supervisor las lee
  (`store/data.py`, `SCHEMA_APP_TRANSLATIONS`), usando «app». Un fichero que
  el Supervisor no entienda solo produce un aviso en su log y la interfaz
  enseña los nombres crudos, como hoy (research R-5).
- P: ¿Qué descripciones pasan a decir «app»? → R: las de las doce tools de
  `tools/addons.py`, el tema `supervisor` de la guía, la línea de operaciones
  largas de las instrucciones del servidor y las descripciones de las opciones
  en `DOCS.md` y los README. Ninguna tool ni argumento cambia de nombre; el
  resto de textos que dicen «add-on» se quedan como están (cambios mínimos).
- P: ¿En qué idioma van los textos que se editan? → R: **en el del texto que
  se edita**. Las descripciones de `sv_get_job_status` y de las tools de
  `tools/addons.py` y la guía están hoy en español; el principio X pide inglés
  para lo que ve el cliente, pero traducir esos textos enteros no es de la 027
  (principio IX: no se traduce lo que no forma parte del cambio). Las líneas
  nuevas siguen el idioma de su texto; `translations/en.yaml` va en inglés y
  `es.yaml` en español. Traducir las descripciones heredadas queda como duda
  D-6.
- P: ¿«Versiones del SDK MCP» entra? → R: sí, como parte de CAP-028 (el
  servidor MCP y su SDK): la fila de la hoja de ruta sobre la constante
  deprecada del SDK está desfasada (el middleware usa ya las dos tuplas nuevas
  desde la spec 003) y la 027 añade una guarda que hace fallar la suite si
  Hermes usa algo que el SDK marque como deprecado (research R-6).
- P: ¿Qué hosts CIMD se conocen? → R: solo `claude.ai` (claude.ai comprobado
  en vivo en la 1.1.0; Claude Code publica su documento ahí según su
  documentación y la prueba en vivo sigue pendiente). No se inventa ninguno
  más; la hoja de ruta dice cómo saberlo con el evento `oauth_cimd_document`
  (research R-7).
- P: ¿Familia nueva? → R: **no hay tools nuevas**, así que no hay familia
  nueva ni entradas de la tabla que pasen a `dedicated`.

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es el administrador de Home Assistant que trabaja desde un cliente
MCP y, en las historias 3 y 5, quien mantiene Hermes.

### Historia 1 — Saber si un job terminó bien de verdad (Prioridad: P1)

Quien lanza un backup o instala una app y consulta el job quiere saber si
terminó bien, y si hubo errores que no lo hicieron fallar del todo.

**Prueba independiente**: con un Supervisor simulado que devuelve un job
terminado sin errores propios y con un error en un sub-job, la tool devuelve
`success: true` (como hoy) y el error del sub-job en `child_errors`, redactado.

**Escenarios de aceptación**:

1. **Dado** un job terminado con un error en `errors`, **cuando** el agente
   llama a `sv_get_job_status`, **entonces** recibe `success: false` y el
   motivo, como hoy.
2. **Dado** un backup completo en el que una app no se pudo guardar (error en
   el sub-job), **cuando** consulta el job, **entonces** recibe
   `success: true`, `child_errors` con el nombre del sub-job y el mensaje, y la
   descripción le dice que el backup existe pero puede estar incompleto.
3. **Dado** un job sin sub-jobs, **cuando** lo consulta, **entonces** recibe
   `child_errors: []` y el resto de campos idénticos a la 1.1.2.
4. **Dado** un mensaje de error con un secreto, **cuando** lo consulta,
   **entonces** el secreto sale tapado en `errors` y en `child_errors`.

### Historia 2 — Nada se rompe hoy y lo que caduca avisa (Prioridad: P1)

Quien usa las tools deprecadas quiere que sigan funcionando en la 1.2.0 y, el
día que HA retire lo que usan, recibir un mensaje que diga qué usar.

**Prueba independiente**: con la configuración por defecto se registran las
mismas tools con los mismos argumentos y anotaciones que antes de la 027; con
un HA simulado que responde `unknown_command`, la tool deprecada devuelve
`command_removed_in_ha` con la sustituta.

**Escenarios de aceptación**:

1. **Dado** Hermes 1.2.0 con la configuración por defecto, **cuando** el
   cliente lista las tools, **entonces** están los cuatro `ha_hacs_*` y
   `ha_remove_device_from_config_entry` con sus nombres, argumentos y
   anotaciones de siempre.
2. **Dado** un alias `ha_hacs_*`, **cuando** se llama, **entonces** devuelve
   lo mismo que su sustituta más `_deprecated`, que cita la 1.3.0.
3. **Dado** un HA que ya no tiene `config/device_registry/remove_config_entry`,
   **cuando** se confirma `ha_remove_device_from_config_entry`, **entonces**
   recibe `command_removed_in_ha` con `replacement: "ha_remove_device"`, no se
   envía ningún otro comando y el token queda gastado.
4. **Dado** un HA que ya no envía `config_entries` ni `primary_config_entry`
   en los dispositivos, **cuando** se cuentan los dispositivos de una
   integración en la vista previa de `ha_delete_config_entry` o se prepara el
   borrado de un dispositivo, **entonces** el resultado es el mismo que con los
   campos.

### Historia 3 — Hermes avisa cuando el Supervisor cambia de plataforma (Prioridad: P2)

Quien mantiene una instalación quiere enterarse por el log de Hermes si el
Supervisor ya ofrece el socket Unix a las apps o tiene activada la API `/v2`,
sin que eso cambie lo que hace Hermes.

**Prueba independiente**: arrancando con un Supervisor simulado en las cuatro
combinaciones (socket sí/no, `/v2` sí/no), el log tiene un evento
`supervisor_platform` con los valores correctos, un aviso por cada cosa
detectada, y el cliente sigue usando la misma URL TCP y las rutas de la V1.

**Escenarios de aceptación**:

1. **Dado** un Supervisor 2026.11.0 normal, **cuando** arranca Hermes,
   **entonces** el log dice `transport: tcp`, `unix_socket_offered: false`,
   `api_v2_enabled: false` y no hay avisos.
2. **Dado** un entorno con `SUPERVISOR_SOCKET`, **cuando** arranca,
   **entonces** hay un aviso `supervisor_unix_socket_offered` que dice que
   Hermes sigue por TCP, y nada más cambia.
3. **Dado** `feature_flags.supervisor_v2_api: true`, **cuando** arranca,
   **entonces** hay un aviso `supervisor_api_v2_enabled` que dice que Hermes
   sigue con la V1, que sigue disponible, y ninguna petición va a `/v2`.
4. **Dado** que `/supervisor/info` falla, tarda o devuelve algo raro,
   **cuando** arranca, **entonces** el evento dice `api_v2_enabled: null` y el
   arranque sigue.

### Historia 4 — La configuración habla de apps (Prioridad: P3)

Quien abre la configuración de Hermes en Home Assistant quiere ver nombres y
descripciones de las opciones en su idioma y con el término que usa el
Supervisor («app»).

**Prueba independiente**: cada opción del esquema de `config.yaml` tiene
nombre y descripción en `translations/en.yaml` y `translations/es.yaml`, con
la forma que acepta el Supervisor, sin la palabra «add-on».

**Escenarios de aceptación**:

1. **Dado** el esquema de opciones, **cuando** se comparan sus claves con las
   de cada traducción, **entonces** coinciden una a una.
2. **Dado** el cliente MCP, **cuando** lee la descripción de una tool de apps
   (`sv_list_addons`…), **entonces** habla de apps y nombra «add-on» como el
   nombre anterior, y la tool se llama igual que antes.

### Historia 5 — Quien mantiene Hermes tiene escrito qué hacer (Prioridad: P3)

Quien prepare la 1.3.0 o la adaptación a un Supervisor nuevo quiere encontrar
en la hoja de ruta las fechas, lo bloqueado y lo que habrá que hacer.

**Prueba independiente**: la hoja de ruta tiene la tabla de deprecaciones al
día, los hosts CIMD conocidos, el resumen de la investigación de
`outputSchema` y de la vía nativa de MCP, y la lista de cambios para el socket
y la `/v2`; la matriz de la 008 tiene sus filas rellenas.

**Escenarios de aceptación**:

1. **Dado** la hoja de ruta, **cuando** se busca una deprecación con fecha,
   **entonces** cada fila dice la fecha, el efecto en Hermes y, si lo hay, el
   test que fija el comportamiento.
2. **Dado** el día en que el Supervisor active la `/v2` por defecto,
   **cuando** quien mantiene Hermes abre la hoja de ruta, **entonces**
   encuentra la tabla de rutas V1 → V2 que usa Hermes y los cambios de formato.

### Casos límite

- Job con sub-jobs anidados en varios niveles: se recorren todos, con un tope
  de entradas y de profundidad; si se pasa, `child_errors_truncated: true`.
- Sub-job con error sin `message`: cuenta como `"unknown error"`, igual que en
  `errors`.
- `child_jobs` que no es lista o con entradas que no son objetos: se ignoran
  esas entradas; nunca se inventa un error.
- `SUPERVISOR_SOCKET` presente pero vacío: no cuenta como ofrecido.
- `/supervisor/info` sin `feature_flags` (Supervisor antiguo): `api_v2_enabled:
  false` si la respuesta es un objeto válido sin la clave; `null` si no se
  pudo leer.
- `unknown_command` en el primer paso: no aplica (el primer paso no envía el
  comando); solo se traduce al confirmar.
- HA que aplaza la retirada de `remove_config_entry`: la tool sigue
  funcionando; nada se decide por número de versión.
- Traducciones: una opción nueva en `config.yaml` sin traducir hace fallar el
  test; una opción de la traducción que no está en el esquema, también.

## Requisitos *(obligatorio)*

Cada requisito cita entre paréntesis el FR y la CAP de la 008 que cumple.

### Requisitos funcionales

#### Jobs del Supervisor (FR-092 de la 008, CAP-025)

- **FR-001**: La descripción de `sv_get_job_status` y la guía (temas
  `backups` y `supervisor`, y el apartado de operaciones largas de las
  instrucciones del servidor) explican que `success` es `false` si hay
  cualquier entrada en `errors` del job consultado, porque el Supervisor
  2026.11.0 no distingue avisos de errores fatales (sus errores llevan tipo,
  mensaje, fase, `error_key` y `extra_fields`, sin gravedad); que `done` es
  `true` también cuando falla; y que, con errores, `reference` puede apuntar a
  un backup que sí se creó. El cálculo de `success` no cambia (FR-092,
  CAP-025).
- **FR-002**: `sv_get_job_status` añade `child_errors`: los errores de los
  sub-jobs (`child_jobs`, recorridos en profundidad) como `{job, message}`,
  con el mensaje recortado a 500 caracteres y pasado por `redact_secrets`,
  hasta 20 entradas y 5 niveles, con `child_errors_truncated: true` si se
  pasa. No cambia `success` ni ningún otro campo. La descripción dice que un
  error en un sub-job (por ejemplo, una app que no se pudo guardar en un
  backup) no hace fallar el job y aparece ahí (FR-092, CAP-025; aditivo según
  FR-020).

#### CIMD (FR-093 de la 008, CAP-026)

- **FR-003**: La hoja de ruta recoge los hosts CIMD conocidos (`claude.ai`,
  comprobado con claude.ai y documentado para Claude Code, con su prueba en
  vivo pendiente) y cómo averiguar el de otro cliente (evento
  `oauth_cimd_document`). El valor por defecto de `oauth_cimd_allowed_hosts`
  sigue siendo `[]` en `config.yaml` y en la configuración cargada (FR-093,
  CAP-026).

#### MCP: `outputSchema`, vía nativa y SDK (FR-094 de la 008, CAP-028)

- **FR-004**: La investigación de `outputSchema` y de la vía nativa de MCP
  para pedir datos a mitad de una llamada (`InputRequiredResult` y
  elicitación del SDK 2.3.0) queda escrita en research de la 027 y resumida en
  la hoja de ruta, con la recomendación. Los dos pasos de confirmación no
  cambian. Un test fija qué tools declaran `outputSchema` hoy (solo `ping` y
  `hermes_guide`, que el SDK infiere de `-> str`), para que cambiarlo sea una
  decisión explícita (FR-094, CAP-028).
- **FR-005**: La suite falla si Hermes usa algo que el SDK `mcp` marque como
  deprecado: importar los módulos de Hermes y registrar todas las tools en un
  `MCPServer` real no emite ningún aviso de deprecación del SDK
  (`MCPDeprecationWarning`, que el SDK hereda de `UserWarning`, ni
  `DeprecationWarning`/`PendingDeprecationWarning` originados en `mcp`,
  `mcp_types` o `hermes`), ningún fichero de `hermes/src` nombra
  `SUPPORTED_PROTOCOL_VERSIONS`, y `requirements.txt` mantiene el tope `<3`. La fila de la
  constante deprecada del SDK en la hoja de ruta dice que Hermes ya usa las
  sustitutas (FR-094, CAP-028; FR-020).

#### Terminología «apps» (FR-095 de la 008, CAP-029)

- **FR-006**: `hermes/translations/en.yaml` y `hermes/translations/es.yaml`
  dan nombre y descripción a cada opción del esquema de `config.yaml` (las
  mismas claves, ni una más ni una menos), con la forma que acepta el
  Supervisor (`configuration: {opción: {name, description}}`), usando «app»
  y sin la palabra «add-on» (FR-095, CAP-029).
- **FR-007**: Las descripciones de las doce tools de `tools/addons.py`, el tema
  `supervisor` de la guía, el apartado de operaciones largas de las
  instrucciones del servidor y las descripciones de las opciones en
  `hermes/DOCS.md`, `README.md` y `README.es.md` dicen «app» (con «add-on»
  como nombre anterior en la primera mención). Ninguna tool ni argumento
  cambia de nombre (FR-095, CAP-029; FR-020).

#### Deprecaciones (FR-096 de la 008, CAP-030 y CAP-031)

- **FR-008**: En la 1.2.0 siguen registrados, con los mismos nombres,
  argumentos y anotaciones, los cuatro alias `ha_hacs_*` (que devuelven
  `_deprecated` con la 1.3.0) y `ha_remove_device_from_config_entry` (cuya
  descripción y vista previa citan HA 2027.9 y `ha_remove_device`). La hoja de
  ruta fija la retirada de los alias en la 1.3.0 y la de la tool deprecada como
  tarde en la última versión de Hermes publicada antes de HA 2027.9 (FR-096,
  CAP-030, CAP-031; FR-020).
- **FR-009**: Si HA responde `unknown_command` a
  `config/device_registry/remove_config_entry` al confirmar,
  `ha_remove_device_from_config_entry` devuelve `command_removed_in_ha` con
  `replacement: "ha_remove_device"` y una explicación, marca el token como
  fallido y no envía ningún otro comando. Cualquier otro error se devuelve
  como hoy (FR-096, CAP-030).
- **FR-010**: Con dispositivos sin `config_entries` ni
  `config_entries_subentries` (forma de HA 2027.8) y sin
  `primary_config_entry` (2027.10), los recuentos de dispositivos por
  integración de las vistas previas de `ha_disable_config_entry` y
  `ha_delete_config_entry` y el plan de borrado de `ha_remove_device` dan el
  mismo resultado que con esos campos; Hermes no lee `primary_config_entry`
  (FR-096, CAP-030; FR-020).

#### Socket Unix y API `/v2` del Supervisor (FR-097 de la 008, CAP-032 y CAP-033)

- **FR-011**: Al arrancar, tras conectar con HA y antes de servir MCP, Hermes
  detecta si el entorno trae `SUPERVISOR_SOCKET` no vacío y si
  `GET /supervisor/info` dice `feature_flags.supervisor_v2_api: true`, y
  escribe un evento `supervisor_platform` (`transport: "tcp"`,
  `unix_socket_offered`, `api_v2_enabled`) y un aviso por cada cosa detectada
  (`supervisor_unix_socket_offered`, `supervisor_api_v2_enabled`) que dice que
  Hermes sigue por TCP y por la V1. No cambia el transporte, la URL base ni
  ninguna ruta. Un error, una respuesta rara o más de 10 s dan
  `api_v2_enabled: null` y el arranque sigue. El log no lleva la ruta del
  socket ni otros valores del entorno (FR-097, CAP-032, CAP-033).
- **FR-012**: La hoja de ruta documenta lo que hará falta cuando el Supervisor
  publique el socket para apps y la `/v2`: cómo conectar por el socket (sin
  token, con caída a TCP), la tabla de rutas V1 → V2 que usa Hermes, los
  cambios de formato (`*_v1`) y de claves de error, `sv_get_addon` de una app
  no instalada (`/store/apps/{app}`), y que el test de deriva de FR-005 de la
  008 solo vigila la V1: los cambios de la V1 los avisa la deriva y la
  activación de la `/v2`, la detección de FR-011 (FR-097, CAP-032, CAP-033).
- **FR-013**: La tabla «Deprecaciones con fecha» de la hoja de ruta queda al
  día con lo comprobado en el código de HA 2026.11.1 y del Supervisor
  2026.11.0, y cada fila con efecto en Hermes nombra el test que fija el
  comportamiento preparado (FR-096, FR-097; CAP-030…CAP-033).

#### Transversales (FR-018…FR-021, FR-023, FR-024 de la 008)

- **FR-014**: La 027 no añade tools, familias ni opciones de configuración, y
  no cambia la tabla de clasificación: con la configuración por defecto se
  registran las mismas tools que antes, con los mismos nombres, argumentos y
  anotaciones, y regenerar la tabla da el mismo fichero (FR-020; FR-010 y
  FR-012 de la 008 no aplican).
- **FR-015**: En el mismo cambio: sección «Plataforma y deprecaciones» en
  `## [1.2.0]` de `hermes/CHANGELOG.md`; estado de la 027 en la tabla del
  programa de `docs/HOJA-DE-RUTA.md`; `hermes/DOCS.md`, `README.md` y
  `README.es.md` sincronizados en lo que cambie; y las filas CAP-025, CAP-026
  y CAP-028…CAP-033 de la matriz de la 008 con su test o su entrada de la hoja
  de ruta (FR-023, FR-024).
- **FR-016**: Cada FR tiene su test de regresión; cada comportamiento nuevo con
  riesgo (FR-002, FR-009, FR-011), su control negativo anotado; los mensajes
  de `child_errors` pasan un test con un centinela de secreto; los ficheros
  nuevos usan solo marcadores genéricos (FR-018, FR-019, FR-021).

### Entidades clave

- **Job del Supervisor**: `uuid`, `name`, `done`, `progress`, `stage`,
  `reference`, `errors` (de ese job) y `child_jobs` (cada uno con la misma
  forma). Los errores de un sub-job no suben al padre.
- **Plataforma del Supervisor vista por Hermes**: transporte (hoy siempre TCP),
  socket ofrecido (sí/no) y API `/v2` activada (sí/no/desconocido).
- **Traducción de opciones**: fichero por idioma con `configuration`, una
  entrada por opción con `name` y `description`.
- **Deprecación con fecha**: qué retira HA o el Supervisor, cuándo, efecto en
  Hermes y test que lo fija.

## Fuera de alcance

- Retirar los alias `ha_hacs_*` o `ha_remove_device_from_config_entry`
  (1.3.0 o la versión que decida el mantenedor, D-08 de la 008).
- Usar el socket Unix o la API `/v2` (bloqueados; FR-011 solo detecta).
- Cambiar el valor por defecto de `oauth_cimd_allowed_hosts` (D-09 de la 008).
- Añadir `outputSchema` a tools, quitarlo de `ping` y `hermes_guide` o
  adoptar la vía nativa de MCP para confirmar (D-10 de la 008; dudas D-3 y D-5).
- Que `success` de `sv_get_job_status` tenga en cuenta los sub-jobs, y que el
  sondeo de los safety backups (`fs_write.py`, `safety_retention.py`) mire
  los sub-jobs (duda D-1).
- Renombrar tools o argumentos `*_addon*` a `*_app*`, o cambiar «add-on» en el
  resto de textos de Hermes.
- Un inventario de la `/v2` en `scripts/inventario/` (duda D-4).

## Dudas para el final

No bloquean la 027; las decide el mantenedor (detalle en
[checklists/requirements.md](checklists/requirements.md)).

- **D-1**: ¿`success` de `sv_get_job_status` (y el sondeo de los safety
  backups) debe contar los errores de los sub-jobs?
- **D-2**: Versión exacta de la retirada de `ha_remove_device_from_config_entry`
  (D-08 de la 008; propuesta: 1.3.0, como tarde antes de HA 2027.9).
- **D-3**: `outputSchema` inferido de `ping` y `hermes_guide`: mantenerlo,
  quitarlo (`structured_output=False`) o declararlo en más tools.
- **D-4**: Inventario de la `/v2` y su deriva, cuando deje de ser una opción de
  desarrollo; usar el socket Unix cuando el Supervisor lo inyecte en las apps.
  Depende de versiones del Supervisor que aún no existen.
- **D-5**: Vía nativa de MCP como segunda forma de confirmar (D-10 de la 008).
- **D-6**: Traducir al inglés las descripciones de tools y la guía heredadas en
  español (principio X frente a IX).

## Supuestos

- **S-01**: Antes del tramo A la rama tiene integradas la 009 (entrada
  `## [1.2.0]` y versión), la 010 (banco de Core) y la 011 entera, por merge
  desde `feat/cobertura-total` o desde sus ramas. Hoy la rama tiene la 011
  hasta su tramo 3 y no tiene la 009 ni la 010: **la implementación espera a
  la integración** (plan, «Dependencias»).
- **S-02**: Si la 028 está integrada y prueba `ha_remove_device_from_config_entry`
  en el banco, FR-009 no cambia lo que esa prueba ve (solo el camino de
  `unknown_command`, que HA 2026.11.1 no da).
- **S-03**: El Supervisor simulado del banco (010) no tiene que servir
  `/supervisor/info`: FR-011 tolera su ausencia.
- **S-04**: HA Core 2026.11.1 y Supervisor 2026.11.0 son la referencia; cada
  afirmación sobre su comportamiento cita el fichero en research.

## Criterios de éxito *(obligatorio)*

- **SC-001**: Con la configuración por defecto, la lista de tools es idéntica a
  la de antes de la 027 en nombres, argumentos y anotaciones, y regenerar la
  tabla no cambia ni un byte.
- **SC-002**: En el 100 % de los casos de prueba con errores en sub-jobs,
  `child_errors` los recoge, y `success` es el mismo que daba la 1.1.2 en
  todos los casos de prueba existentes.
- **SC-003**: En las cuatro combinaciones de socket y `/v2` el evento dice la
  verdad, la URL base y las rutas no cambian, y con `/supervisor/info` roto el
  arranque sigue en menos de 10 s de más.
- **SC-004**: Las dos traducciones cubren el 100 % de las opciones del esquema
  y ninguna contiene «add-on».
- **SC-005**: Ningún centinela de secreto aparece en `errors`, `child_errors`
  ni en el log del arranque.
- **SC-006**: Cada FR tiene su test y cada comportamiento con riesgo, su
  control negativo anotado.
- **SC-007**: La suite pasa en el CI de Linux al final de cada tramo, con
  exactamente los 6 fallos conocidos de Windows en local.
- **SC-008**: Las filas CAP-025, CAP-026 y CAP-028…CAP-033 de la matriz de la
  008 tienen su test o su entrada de la hoja de ruta.
