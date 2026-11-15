# Especificación: Hermes 1.2.0 — backups de la integración `backup` y safety backups cifrados (sub-feature 031)

**Directorio de la spec**: `specs/031-backups-integracion-y-cifrado`

**Creada**: 2026-11-15

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T017 de su `tasks.md` y cubre **CAP-057** (backups de
la integración `backup` de Home Assistant: agentes, programación, retención,
crear, restaurar y borrar) y **CAP-027** (safety backups cifrados), que son
**FR-067 y FR-068** de la 008, más los transversales que le tocan (FR-010…FR-012,
FR-015, FR-016, FR-018…FR-021, FR-023 y FR-024 de la 008). Ola 3, tamaño M.
Nace de partir la 019 en dos (plan de la 008, «Cambios respecto a research
R-6»).

**Entrada**: `specs/008-cobertura-total/` (spec FR-067 y FR-068; plan con la
matriz de trazabilidad; research CAP-027 y CAP-057; `inventario/core-ws.tsv`),
los compromisos que la 011 dejó en `command_table.py` (`backup/restore`,
`backup/delete`, `backup/generate` y `backup/generate_with_automatic_settings`
en `deny` «pendiente de tool dedicada (spec 031)»), la 019 (montajes,
`location` en `sv_create_backup_*` y el `action_hash` con HMAC de
`security.py`), la 027 (traducciones de las opciones), el banco de Core de la
010 y la 028, la matriz de pruebas de la 014 y el código de Hermes
(`tools/ha_backups.py`, `tools/backups.py`, `fs_write.py`,
`safety_retention.py`, `security.py`, `config.py`, `tools/_annotations.py`,
`tools/guide.py`, `tool_families.py`). Contrastado con el código de Home
Assistant Core 2026.11.1 (`components/backup/websocket.py`, `manager.py`,
`config.py`, `models.py`; `components/hassio/backup.py` y
`websocket_api.py`) y del Supervisor 2026.11.0 (`api/backups.py`,
`backups/manager.py`), leídos sin ejecutar nada.

**Fuera de esta sub-feature** (otras del programa): montajes de red, montaje
por defecto de backups, `days_until_stale`, recargar backups y `location` en
`sv_create_backup_*` (019, CAP-083); el `action_hash` con HMAC (lo trae la
019; aquí se usa); cambiar o generar la **clave de cifrado** de los backups de
HA (se hace en la interfaz de HA, que entrega el «kit de emergencia»); subir o
descargar ficheros de backup (`/backups/new/upload`, descargas: clase D);
`backup/can_decrypt_on_download` y las señales internas `backup/start|end`
(clase B); la suscripción `backup/subscribe_events` (clase B para la
genérica).

## Clarificaciones

### Sesión 2026-11-15

Decisiones vinculantes del programa (ya están en la 008 o en la 011):

- CAP-057 va por **tools dedicadas** (vía D+T de la matriz) en una **familia
  nueva** de la 1.2.0 (FR-010 de la 008).
- **Compromiso de la 011**: `backup/restore`, `backup/delete`,
  `backup/generate` y `backup/generate_with_automatic_settings` tienen tool
  dedicada en esta sub-feature y pasan a `dedicated`. Restaurar lleva una
  vista previa **tan fuerte como la de `sv_restore_backup_full`**: qué se
  sobrescribe (Core, apps, carpetas), desde qué ubicación (local o remota), de
  qué fecha y con qué contenido, con el token atado a todo eso. Borrar dice
  qué backup y en qué ubicaciones.
- La **contraseña de cifrado** de los backups es un secreto: no sale nunca en
  una respuesta, una vista previa, un error ni el log, y no se guarda en el
  fichero del token (FR-019 de la 008; principio II).
- FR-068 de la 008: los safety backups se crean **cifrados** y la
  restauración sigue funcionando.
- Lo que no dependa del Supervisor se prueba en el banco de Core contra HA
  real (FR-015 de la 008); lo que sí, con simuladores y en la matriz de la 014
  como VM pendiente (FR-016).

Decisiones tomadas al especificar (no había a quién preguntar; se justifican
en [research.md](research.md)):

- P: ¿Cuántas tools y cuáles? → R: **ocho**. Lectura:
  `ha_list_backup_agents` (`backup/agents/info`) y
  `ha_get_update_backup_settings` (`hassio/update/config/info`). Con
  confirmación: `ha_update_backup_config` (`backup/config/update`),
  `ha_set_update_backup_settings` (`hassio/update/config/update`),
  `ha_create_backup` (`backup/generate`), `ha_create_automatic_backup`
  (`backup/generate_with_automatic_settings`), `ha_restore_backup`
  (`backup/restore`) y `ha_delete_backup` (`backup/delete`). Research R-1.
- P: ¿Por qué una tool aparte para el backup con los ajustes automáticos? →
  R: porque **borra**: tras crearlo, HA aplica la retención configurada y
  elimina los backups automáticos que sobran. `ha_create_backup` no borra
  nada. Mezclarlas en una tool con un modo obligaría a anunciar las dos como
  destructivas o a mentir en una (principio V). Research R-1.
- P: ¿Crear un backup pide confirmación? → R: **sí**, las dos tools de crear
  (FR-067 de la 008: «crear un backup eligiendo agentes, con confirmación»).
  Una copia completa de la casa (con `secrets.yaml`) puede salir a un agente
  remoto (nube, otro equipo), sin cifrar si así se pide, y llena el disco. Por
  el invariante de la 1.1.2, toda tool que pide token se anuncia
  `destructiveHint`. Research R-1.
- P: ¿De dónde sale la contraseña de los safety backups y cómo se custodia? →
  R: es la **clave de cifrado de los backups de Home Assistant** (la del kit de
  emergencia, `create_backup.password` de la integración `backup`), que Hermes
  lee de HA en el momento de crear el backup, usa y descarta: nunca la escribe
  en disco, ni en el estado del safety backup, ni en la anotación de la
  retención, ni en el log. Así el usuario puede restaurar un safety backup
  desde la interfaz de HA o la CLI con la clave que ya tiene, aunque Hermes
  esté roto, que es justo cuando hace falta. Se descartan la contraseña
  generada y guardada en `/data` (research de la 008: solo Hermes podría
  descifrar sus backups y la clave viajaría dentro del propio backup que
  cifra) y una opción del add-on con la contraseña (un secreto más que
  custodiar y que el usuario puede perder). Es una **desviación** del texto de
  FR-068 de la 008 («contraseña generada, guardada en el almacenamiento del
  add-on»), que cumple su intención (cifrados, nunca devuelta ni registrada,
  restaurables) mejor que su mecanismo; queda como duda D-031-1. Research R-3.
- P: ¿Y si no hay clave de cifrado en HA (no se configuraron los backups
  automáticos, HA anterior a 2025.1 o HA caído)? → R: opción nueva del add-on
  **`safety_backup_encryption`**: `auto` (por defecto; cifra si hay clave y,
  si no, crea el backup sin cifrar y lo dice en la respuesta y en el log),
  `required` (sin clave no hay safety backup: la tool responde error y la
  escritura en `/config` se bloquea, como cualquier fallo del safety backup)
  y `off` (como en la 1.1.2). Research R-4.
- P: ¿La retención de los safety backups (`safety_backup_keep`) sigue podando
  los cifrados? → R: **sí**. Hoy excluye los `protected` por prudencia; con el
  cifrado, los suyos lo son todos y el disco volvería a llenarse. La anotación
  de la retención guarda `encrypted: true` cuando Hermes lanzó el backup con
  la clave, y solo esos pueden estar protegidos. Las entradas anteriores no
  cambian de regla. Research R-5.
- P: ¿Cómo se restaura un backup cifrado? → R: `sv_restore_backup_full`,
  `sv_restore_backup_partial` y `ha_restore_backup` usan la clave de cifrado
  de HA cuando el backup está protegido y no se pasa `password`; la vista
  previa dice de dónde sale la contraseña («la clave de cifrado de los backups
  de HA», sin enseñarla). Con `password`, se usa esa. Hoy un backup protegido
  sin `password` falla en el Supervisor; el cambio solo afecta a ese caso
  (FR-020 de la 008). Research R-4.
- P: ¿`ha_update_backup_config` permite cambiar la contraseña? → R: **no**.
  No acepta `password` en ningún sitio: cambiar la clave de cifrado deja sin
  poder descifrar los backups futuros a quien no tenga la nueva, y la interfaz
  de HA es la que entrega el kit de emergencia. Sí permite poner
  `protected: false` en un agente, con un aviso en la vista previa. Research
  R-10.
- P: ¿`ha_create_backup` acepta una contraseña? → R: **no**: `encrypt` (por
  defecto `true`) cifra con la clave de HA, la misma de los backups
  automáticos; sin clave configurada y con `encrypt: true`, responde
  `no_encryption_key` sin crear nada. Ninguna contraseña viaja por el cliente
  MCP para crear. Research R-1.
- P: ¿`ha_restore_backup` acepta `password`? → R: **sí, opcional**, para
  backups cifrados con otra clave (una anterior, otra instalación). Entra en
  el hash del token, que desde la 019 es un HMAC con clave en memoria, y nunca
  en el fichero del token ni en la vista previa. Research R-8.
- P: ¿Qué ata el token además de los argumentos? → R: la **huella del estado**
  que describe la vista previa, por el `estado` de
  `create_confirmation_token`/`resolve_confirmation_token` (018): al
  restaurar, el backup en esa ubicación (fecha, nombre, versión, contenido,
  protección y tamaño); al borrar, el backup y sus ubicaciones; al cambiar la
  configuración, la configuración actual sin contraseña y los backups que la
  retención borraría; al crear, los agentes disponibles y si hay clave. Si
  cambia entre la vista previa y la confirmación, no se ejecuta y se pide otra
  vista previa. Research R-8.
- P: ¿Qué hace la vista previa con la retención? → R: **estima**, con las
  mismas reglas que HA 2026.11.1 (global y por agente; copias y días; solo
  backups automáticos), qué backups borraría la configuración nueva y cuándo
  (por días: en las próximas 24 h; por copias: tras el próximo backup
  automático). Lo llama estimación, porque depende de lo que pase hasta
  entonces. Research R-9.
- P: ¿Cómo sabe el cliente que un backup creado terminó? → R:
  `backup/generate` vuelve en el acto con un `backup_job_id`. `ha_list_backups`
  ya devuelve `state` (`idle` cuando termina) y gana, sin cambiar nada de lo
  que ya da, `last_action_event` (estado, fase y motivo del último evento de
  crear o restaurar, por lista blanca): así se ve si terminó bien o falló.
  Research R-14.
- P: ¿Y al restaurar, que reinicia HA? → R: el comando de HA no responde hasta
  que termina, y con HA OS reinicia Core (y con Core sin Supervisor escribe la
  orden y reinicia). La tool espera la respuesta un tiempo acotado: un error
  temprano (contraseña incorrecta, backup inexistente, contenido que no
  cuadra) se devuelve como error; si no hay respuesta en el plazo o se cae la
  conexión **después de enviar** la orden, responde `restore_started` y cómo
  seguirlo; si la orden no se llegó a enviar, error y el token queda como
  fallido. Research R-6.
- P: ¿Familias? → R: **una** nueva, `backup_integration` (1.2.0,
  desactivable), con tres módulos: `ha_backup_settings` (agentes y ajustes),
  `ha_backup_actions` (crear y borrar) y `ha_backup_restore` (restaurar). Las
  tres lecturas de la 1.1.2 (`ha_list_backups`, `ha_get_backup`,
  `ha_get_backup_config`) se quedan en `backups`. Research R-2.
- P: ¿Qué se prueba en el banco de Core? → R: el banco carga `backup:` (Core
  sin Supervisor, agente `backup.local`): se ejecutan de verdad
  `ha_list_backup_agents`, `ha_update_backup_config`, `ha_create_backup`,
  `ha_create_automatic_backup` (con la retención borrando de verdad) y
  `ha_delete_backup`, y la lectura de la clave de cifrado contra HA real.
  `ha_restore_backup` no se puede ejecutar con éxito en el banco (restaurar
  reinicia Core y el banco no lo sobrevive): se prueban su vista previa, el
  token y el rechazo de una contraseña incorrecta, que HA comprueba antes de
  reiniciar. Las dos de `hassio/update/config` necesitan la integración
  `hassio`, que solo existe con Supervisor. Research R-12.

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es el administrador de Home Assistant que trabaja desde un cliente
MCP.

### Historia 1 — Configurar los backups automáticos (Prioridad: P1)

Quien quiere que su casa haga backups solos pide al asistente que programe un
backup diario a las 4:30, que guarde siete copias y que los suba también a la
nube, cifrados.

**Prueba independiente**: con un HA simulado que tiene la configuración por
defecto y dos agentes (`hassio.local` y uno remoto), la tool devuelve una
vista previa con la configuración actual y la nueva, sin la contraseña, y al
confirmar manda a HA exactamente los cambios previsualizados.

**Escenarios de aceptación**:

1. **Dado** HA con la integración `backup`, **cuando** se pide
   `ha_list_backup_agents`, **entonces** devuelve cada agente con su id, su
   nombre, su tipo (local, montaje de red o remoto), si cifra, su retención
   propia y si lo usan los backups automáticos.
2. **Dado** un cambio de programación, retención y agentes, **cuando** se pide
   `ha_update_backup_config` sin token, **entonces** la vista previa enseña lo
   actual y lo nuevo campo a campo, sin ningún valor de contraseña (solo
   `password_set`), y no cambia nada en HA.
3. **Dado** que la retención nueva es menor que los backups automáticos que
   hay, **entonces** la vista previa lista los que HA borraría y cuándo, y lo
   llama estimación.
4. **Dado** `agents: {"<id>": {"protected": false}}`, **entonces** la vista
   previa avisa de que los backups subidos a ese agente irán sin cifrar.
5. **Dado** un `password` en `create_backup`, **entonces** la tool responde
   `invalid_argument` sin llamar a HA y sin repetir el valor.
6. **Dado** que la configuración de HA cambia entre la vista previa y la
   confirmación, **entonces** no se aplica nada y se pide otra vista previa.
7. (**DESVIACIÓN DV-1: no aplica**; ver «Requisitos».) **Dado** HA OS, **cuando** se pide `ha_get_update_backup_settings`,
   **entonces** devuelve si se hace backup antes de actualizar Core y las apps
   y cuántas copias se guardan; y `ha_set_update_backup_settings` cambia esos
   tres valores con confirmación. Sin la integración `hassio`, las dos
   responden `supervisor_integration_unavailable`.

---

### Historia 2 — Crear un backup ahora, donde yo diga (Prioridad: P1)

Antes de un cambio grande, el usuario pide un backup completo en el disco
local y en el NAS, cifrado, con un nombre propio.

**Prueba independiente**: con un HA simulado, la vista previa dice qué se
guarda (configuración, base de datos, apps y carpetas), en qué agentes y si va
cifrado; al confirmar, HA recibe `backup/generate` con la clave de cifrado de
HA leída en ese momento, y ni la respuesta ni el log la contienen.

**Escenarios de aceptación**:

1. **Dado** `agent_ids` con un agente que no existe, **entonces** la tool
   responde `unknown_agent` con los disponibles, sin llamar a `backup/generate`.
2. **Dado** `encrypt: true` (por defecto) y HA sin clave de cifrado,
   **entonces** responde `no_encryption_key` sin crear nada y explica cómo
   configurarla en HA o pedir `encrypt: false`.
3. **Dado** un agente remoto y `encrypt: false` (o ese agente con
   `protected: false`), **entonces** la vista previa marca ese agente
   `encrypted: false` y avisa de que una copia sin cifrar de toda la
   configuración (con `secrets.yaml`) sale a ese destino.
4. **Dado** la confirmación, **entonces** la respuesta trae el
   `backup_job_id` y cómo seguirlo (`ha_list_backups`: `state` y
   `last_action_event`).
5. **Dado** los backups automáticos configurados, **cuando** se pide
   `ha_create_automatic_backup`, **entonces** la vista previa dice qué se
   guarda y dónde según esos ajustes y qué backups automáticos borraría la
   retención después (estimación); sin ajustes automáticos (sin agentes),
   responde `automatic_backups_not_configured`.

---

### Historia 3 — Restaurar sabiendo exactamente qué se pisa (Prioridad: P1)

Algo se rompió tras una actualización y el usuario quiere volver al backup de
anoche, que está en el NAS y en la nube.

**Prueba independiente**: con un HA simulado y un backup en dos ubicaciones,
la vista previa dice el backup (id, nombre, fecha, versión de HA), la
ubicación elegida (y si es local o remota), si está cifrado y con qué
contraseña se abrirá (sin enseñarla), y qué se sobrescribe: la configuración
de Core, la base de datos, cada app y cada carpeta, y lo que hay en el backup
pero NO se restaura.

**Escenarios de aceptación**:

1. **Dado** un backup en varias ubicaciones y sin `agent_id`, **entonces** se
   elige la local si la hay; si no, la tool responde `agent_id_required` con
   las ubicaciones disponibles.
2. **Dado** `restore_addons` con una app que no está en el backup, **entonces**
   responde `not_in_backup` sin emitir token.
3. **Dado** que la lista de apps incluye a Hermes, **entonces** la vista previa
   avisa de que Hermes se sustituirá por la versión del backup.
4. **Dado** un backup protegido y sin `password`, **entonces** la vista previa
   dice que se usará la clave de cifrado de HA; con `password`, que se usará la
   dada; ninguna de las dos se ve ni se guarda en el fichero del token.
5. **Dado** que el backup cambia en esa ubicación entre la vista previa y la
   confirmación (otra fecha, otro contenido, ya no está), **entonces** no se
   restaura nada.
6. **Dado** una contraseña incorrecta, **entonces** la tool devuelve
   `password_incorrect` y HA no se reinicia.
7. **Dado** que HA no responde en el plazo tras recibir la orden (reinicio),
   **entonces** la respuesta es `restore_started`, sin inventarse un éxito ni
   un fallo, con cómo comprobar el resultado.

---

### Historia 4 — Borrar un backup sabiendo de dónde desaparece (Prioridad: P2)

El usuario quiere liberar espacio borrando un backup viejo.

**Escenarios de aceptación**:

1. **Dado** un backup en el disco local y en la nube, **cuando** se pide
   `ha_delete_backup` sin token, **entonces** la vista previa dice que se borra
   de **todas** sus ubicaciones y las lista, con su tamaño en cada una, su
   fecha, si es automático y si es un safety backup de Hermes.
2. **Dado** que es el único backup que incluye la configuración de Home
   Assistant, **entonces** la vista previa lo avisa.
3. **Dado** que una ubicación falla al borrar, **entonces** la respuesta dice
   en cuáles se borró y en cuáles no, con el error redactado.
4. **Dado** un id que no existe, **entonces** `not_found` sin token.

---

### Historia 5 — Safety backups cifrados (Prioridad: P1)

El usuario tiene activado el safety backup de Hermes antes de escribir en
`/config`. Desde la 1.2.0 esos backups (con `secrets.yaml`, los tokens de las
integraciones y los datos de las apps) se guardan cifrados con la clave de los
backups de HA, que el usuario tiene en su kit de emergencia.

**Prueba independiente**: con un Supervisor y un HA simulados, el safety
backup automático y `sv_create_safety_backup` mandan `password` al Supervisor
con la clave leída de HA; la respuesta, el estado del safety backup, la
anotación de la retención, `pending_jobs.json` y el log no contienen la clave.

**Escenarios de aceptación**:

1. **Dado** `safety_backup_encryption: auto` y HA con clave, **entonces** el
   safety backup sale cifrado y la respuesta dice `encrypted: true`.
2. **Dado** `auto` y HA sin clave (o caído, o anterior a 2025.1), **entonces**
   el safety backup sale sin cifrar, la respuesta dice `encrypted: false` con
   el motivo y el log lo avisa.
3. **Dado** `required` y sin clave, **entonces** no se crea el backup:
   `sv_create_safety_backup` responde `encryption_key_unavailable` y la
   escritura automática en `/config` se bloquea con ese motivo.
4. **Dado** `off`, **entonces** todo es como en la 1.1.2.
5. **Dado** varios safety backups cifrados y `safety_backup_keep: 3`,
   **entonces** la retención borra los que sobran como antes; un backup
   protegido que Hermes no anotó como cifrado sigue sin tocarse.
6. **Dado** un safety backup cifrado, **cuando** se restaura con
   `sv_restore_backup_full` sin `password`, **entonces** la vista previa dice
   que se usará la clave de cifrado de HA y el Supervisor la recibe al
   confirmar.

---

### Historia 6 — Nada se rompe (Prioridad: P1)

**Escenarios de aceptación**:

1. **Dado** la configuración por defecto, **entonces** las tools de la 1.1.2
   siguen con el mismo nombre, anotaciones y argumentos; `ha_list_backups`
   solo añade `last_action_event`.
2. **Dado** `tool_families_disabled: ["backup_integration"]`, **entonces** no
   se registra ninguna de las ocho y las genéricas rechazan sus comandos con
   `use_dedicated_tool` y `family_disabled: true`.
3. **Dado** cualquiera de los ocho comandos por `ha_read_ws_command` o
   `ha_call_ws_command`, **entonces** `use_dedicated_tool` con su tool y sin
   llegar a HA.

### Casos límite

- HA anterior a 2025.1 (sin integración `backup`): las tools responden
  `ha_version_unsupported` como las de lectura de la 1.1.2; `unknown_command`
  de un comando concreto → `backup_integration_unavailable`.
- El gestor de backups está ocupado (`Backup manager busy`): el error de HA se
  devuelve redactado; la confirmación queda como fallida.
- Un agente remoto da error al listar: los backups de los demás salen y el
  error del agente sale enmascarado (hosts, IPs) como en `ha_list_backups`.
- Un backup con más de cien apps o una configuración enorme: las vistas
  previas se recortan al tope de respuesta diciendo cuántos elementos se
  omiten, nunca omitiendo en silencio lo que se sobrescribe (si no cabe lo que
  se sobrescribe, `response_too_large` sin token).
- Restaurar en Core sin Supervisor con apps o carpetas: HA lo rechaza; la
  vista previa ya lo dice si la instalación no tiene el agente `hassio.local`.
- `restore_database` distinto de lo que trae el backup al restaurar la
  configuración: HA OS lo rechaza («Restore database must match backup»); la
  tool lo comprueba antes y responde `invalid_argument`.
- La clave de cifrado cambia entre crear un safety backup y restaurarlo: el
  Supervisor responde contraseña incorrecta; el error dice que el backup puede
  estar cifrado con una clave anterior y que se pase `password`.
- Dos safety backups a la vez o un safety backup durante un backup de HA: el
  lock y los límites de la 1.1.2 no cambian.

## Requisitos *(obligatorio)*

> **DESVIACIÓN DV-1 (HALLAZGO del tramo 1, decisión del supervisor del
> programa)**: `ha_get_update_backup_settings` y
> `ha_set_update_backup_settings` NO existen. Hermes es una app y habla con
> Core por el proxy WebSocket del Supervisor, que en 2026.11.0 rechaza con
> «Unauthorized» todo comando `hassio/*` y `supervisor/*` de las apps
> (`DENIED_WS_TYPE_PREFIXES` de `supervisor/api/proxy.py`): esas dos tools no
> podrían funcionar nunca, y una tool que no puede funcionar viola el
> principio V. Se quitaron (eran nuevas de la 1.2.0: no hay compatibilidad
> que guardar). `hassio/update/config/info` y `hassio/update/config/update`
> quedan en `deny` con el motivo del proxy, y un test impide que una entrada
> `hassio/*` o `supervisor/*` quede en `read`/`confirm` o como `dedicated`
> hacia una tool que la mande por WebSocket. Donde esta spec dice «ocho»
> tools o comandos, son **seis**; FR-004 y el escenario 7 de la historia 1
> no se cumplen por diseño; en FR-017, esas dos entradas van a `deny` y no a
> `dedicated`; en FR-018, FR-020 y FR-022 lo de esas dos tools no aplica.

### Requisitos funcionales

#### Agentes y configuración (CAP-057)

- **FR-001**: `ha_list_backup_agents` lee `backup/agents/info` y
  `backup/config/info` y devuelve cada agente con `agent_id`, `name`, `kind`
  (`local` para `backup.local` y `hassio.local`, `mount` para los demás
  `hassio.*`, `remote` para el resto), `protected` y `retention` de su
  configuración (o `null`) y `used_by_automatic_backups`. Solo lee; nunca
  devuelve la contraseña (FR-067 de la 008; CAP-057).
- **FR-002**: `ha_update_backup_config` cambia la configuración de los backups
  automáticos de HA (`schedule`, `retention`, `agents`, `create_backup` sin
  contraseña y `automatic_backups_configured`) con confirmación. Valida cada
  clave y valor contra el esquema de HA 2026.11.1 antes de llamar; rechaza
  `password` en cualquier sitio con `invalid_argument` sin repetir el valor;
  como HA sustituye `schedule` y `retention` enteros (lo no pasado vuelve a
  su valor por defecto: `recurrence: never`, retención sin límite), Hermes
  completa esos documentos con los valores actuales de lo no pasado y manda
  el documento completo (un `null` explícito se respeta); la vista previa
  enseña lo actual y lo que se manda, los campos que cambian, los avisos (agente sin cifrar, programación
  a `never`, agentes de `create_backup` que no existen) y la estimación de
  FR-003; el token ata los argumentos y la huella de la configuración actual
  sin contraseña y de los backups que la retención borraría (FR-067; CAP-057).
- **FR-003**: Estimación de la retención: con las reglas de HA 2026.11.1
  (`delete_backups_exceeding_configured_count` y el borrado por días de
  `RetentionConfig`), solo sobre backups con `with_automatic_settings`, por
  agente cuando hay retención por agente, la vista previa lista los backups
  que se borrarían (id, nombre, fecha, agentes) y cuándo: `within_24h` por
  días y `after_next_automatic_backup` por copias. Se presenta como
  estimación (FR-067; CAP-057).
- **FR-004** (**DESVIACIÓN DV-1: no se implementa**; el proxy WebSocket del
  Supervisor rechaza `hassio/*` a las apps): `ha_get_update_backup_settings` (lectura) y
  `ha_set_update_backup_settings` (con confirmación) leen y cambian
  `core_backup_before_update`, `add_on_backup_before_update` y
  `add_on_backup_retain_copies` (entero ≥ 1). La vista previa enseña lo actual
  y lo nuevo y, si baja `add_on_backup_retain_copies`, avisa de que en la
  próxima actualización de cada app HA borrará sus backups de actualización
  que sobren. Sin la integración `hassio`, `supervisor_integration_unavailable`
  (FR-067; CAP-057).

#### Crear, restaurar y borrar (CAP-057 y compromisos de la 011)

- **FR-005**: `ha_create_backup` crea un backup con `backup/generate` con
  confirmación: `agent_ids` (1–10, cada uno entre los de
  `backup/agents/info`; si no, `unknown_agent` con los disponibles),
  `include_homeassistant`, `include_database`, `include_addons` o
  `include_all_addons` (excluyentes), `include_folders` (`share`,
  `addons/local`, `ssl`, `media`; apps o carpetas sin el agente
  `hassio.local` → `invalid_argument`, como haría HA en Core sin
  Supervisor), `name` (opcional, 1–100) y `encrypt` (por defecto `true`:
  cifra con la clave de HA; sin clave, `no_encryption_key` sin crear nada).
  La vista previa dice qué se guarda, dónde (con `kind` de cada agente) y si
  va cifrado **en cada agente** (HA descifra la copia de un agente con
  `protected: false`), y avisa si una copia sin cifrar sale a un agente
  remoto. Al confirmar devuelve `backup_job_id` y cómo
  seguirlo (FR-067; CAP-057).
- **FR-006**: `ha_create_automatic_backup` crea un backup con
  `backup/generate_with_automatic_settings` con confirmación. La vista previa
  dice qué se guarda y dónde según los ajustes automáticos, si va cifrado en
  cada agente, y
  la estimación de FR-003 de lo que la retención borraría después. Sin agentes
  en `create_backup.agent_ids`, `automatic_backups_not_configured` sin token
  (FR-067; CAP-057).
- **FR-007**: `ha_restore_backup` restaura con `backup/restore` con
  confirmación y una vista previa al menos tan completa como la de
  `sv_restore_backup_full`: `backup_id`, nombre, fecha, versión de HA del
  backup; ubicación elegida (`agent_id`, nombre, `kind`), si está protegido y
  de dónde sale la contraseña (`provided`, `backup_encryption_key` o
  `not_needed` o `backup_encryption_key_unavailable`, nunca el valor); qué
  se sobrescribe (configuración de Core,
  base de datos, cada app con nombre y versión del backup, cada carpeta) y qué
  hay en el backup que no se restaura; el aviso de que lo actual se pierde,
  de que HA se reinicia y, si se restaura Hermes, de que se sustituye.
  Elección de ubicación: `agent_id` explícito, o la local si el backup está en
  ella, o `agent_id_required`. `restore_database` por defecto igual a lo que
  trae el backup; con Supervisor (agente `hassio.local` presente), distinto
  con `restore_homeassistant` → `invalid_argument` (HA OS lo rechazaría);
  `restore_database` sin `restore_homeassistant` → `invalid_argument`. Apps o
  carpetas pedidas que no están en el backup → `not_in_backup`; apps o
  carpetas sin `hassio.local` → `invalid_argument`. El token
  ata los argumentos (también `password`, por el HMAC de la 019) y la huella
  del backup en esa ubicación (compromiso de la 011; FR-018 de la 008).
- **FR-008**: Resultado de restaurar: error de HA en el plazo de espera
  (`password_incorrect`, `backup_not_found`, otro redactado) → error y token
  fallido; respuesta correcta → `completed`; sin respuesta en el plazo o
  conexión caída **tras enviar la orden** → `restore_started` con cómo
  comprobarlo; orden no enviada → error de conexión y token fallido. Nunca se
  presenta como éxito lo que no se ha visto terminar (principio V; FR-018).
- **FR-009**: `ha_delete_backup` borra con `backup/delete` con confirmación.
  La vista previa dice el backup (id, nombre, fecha, versión, si es automático,
  si es un safety backup de Hermes según su anotación) y que se borra de
  **todas** sus ubicaciones, con cada una (`agent_id`, `kind`, tamaño,
  protegido); avisa si es el único backup con la configuración de Home
  Assistant. El token ata el id y la huella del backup y sus ubicaciones. La
  respuesta dice en qué ubicaciones se borró y en cuáles falló (errores
  enmascarados como en `ha_list_backups`) (compromiso de la 011).
- **FR-010**: `ha_list_backups` añade `last_action_event` (`manager_state`,
  `state`, `stage`, `reason`, por lista blanca) sin cambiar nada de lo que ya
  devuelve, para seguir un backup creado o restaurado (FR-067; FR-020 de la
  008).

#### Clave de cifrado y safety backups (CAP-027)

- **FR-011**: Un módulo de Hermes lee la clave de cifrado de los backups de HA
  (`create_backup.password` de `backup/config/info`) cuando hace falta y la
  devuelve solo a quien la usa en ese momento. Distingue «hay clave»,
  «HA sin clave», «integración no disponible» y «HA inalcanzable». La clave no
  se guarda en disco ni en memoria más allá de la llamada, no entra en ningún
  token, vista previa, respuesta, error ni log, y un error de HA que la citara
  sale redactado. Test con centinela en cada salida (FR-019 de la 008;
  principio II; CAP-027).
- **FR-012**: Opción nueva del add-on `safety_backup_encryption`
  (`auto` | `required` | `off`, por defecto `auto`) en `hermes/config.yaml`
  (schema y opciones), `run.sh`, `config.py` (validación fail-closed de un
  valor desconocido), las traducciones de la 027 (si están en la base) y
  `hermes/DOCS.md` (FR-068 de la 008; CAP-027).
- **FR-013**: El safety backup automático (antes de escribir en `/config`) y
  `sv_create_safety_backup` mandan `password` con la clave según la opción:
  `auto` cifra si hay clave y, si no, crea sin cifrar con `encrypted: false` y
  `encryption_skipped_reason` en la respuesta de la tool y un aviso en el log
  (sin la clave); `required` sin clave no crea nada (`encryption_key_unavailable`
  y, en la escritura automática, la escritura no se hace); `off` como en la
  1.1.2. La respuesta de la tool dice siempre `encrypted` (FR-068; CAP-027).
- **FR-014**: La anotación de la retención guarda `encrypted: true` en los
  safety backups lanzados con clave, y la poda admite `protected: true` solo en
  esas entradas; las anteriores siguen excluyendo los protegidos (FR-068;
  CAP-027).
- **FR-015**: `sv_restore_backup_full` y `sv_restore_backup_partial` sin
  `password` sobre un backup `protected` usan la clave de cifrado de HA; su
  vista previa dice `password_source` (`provided`, `backup_encryption_key`,
  `not_needed` o `backup_encryption_key_unavailable`). Con `password`, nada
  cambia. Si el Supervisor rechaza la contraseña, el error lo dice y sugiere
  que el backup puede estar cifrado con una clave anterior (FR-068; CAP-027).

#### Transversales

- **FR-016**: Familia nueva `backup_integration` (`desde="1.2.0"`,
  desactivable) con los módulos `ha_backup_settings`, `ha_backup_actions` y
  `ha_backup_restore`; las ocho tools solo se registran con la familia activa
  (FR-010 de la 008; CAP-004).
- **FR-017**: `backup/agents/info`, `backup/config/update`, `backup/generate`,
  `backup/generate_with_automatic_settings`, `backup/restore`,
  `backup/delete`, `hassio/update/config/info` y
  `hassio/update/config/update` pasan a `dedicated` hacia su tool (con
  `cap="CAP-057"` las cuatro de clase A del inventario; sin `cap` las cuatro
  que el inventario da por cubiertas, como `backup/config/info`), por el mapa
  del generador; la tabla regenerada sale idéntica; ninguna entrada dice
  «(spec 031)» (FR-012 de la 008; CAP-001).
- **FR-018**: Anotaciones verdaderas en la tabla central: las dos de lectura
  por prefijo (`R-I-`); `ha_update_backup_config` y
  `ha_set_update_backup_settings` destructivas e idempotentes (`-DI-`);
  `ha_create_backup` y `ha_create_automatic_backup` destructivas, no
  idempotentes y de mundo abierto (`-D-O`); `ha_restore_backup` y
  `ha_delete_backup` destructivas, idempotentes y de mundo abierto (`-DIO`),
  porque un agente remoto hace que HA salga a internet; cada excepción, con su
  porqué (FR-018 de la 008; principio V).
- **FR-019**: Respuestas y vistas previas por lista blanca (como
  `tools/ha_backups.py`), por `redact_structure` + `redact_secrets`, con los
  errores de los agentes enmascarados y por el tope de respuesta
  (`ajustar_lista_a_bytes` en las listas); el log lleva recuentos y ids de
  agente, nunca contraseñas, nombres de apps o carpetas ni errores en claro
  (FR-018, FR-019 y FR-021 de la 008).
- **FR-020**: HA anterior a 2025.1 → `ha_version_unsupported`;
  `unknown_command` → `backup_integration_unavailable` (o
  `supervisor_integration_unavailable` en las de `hassio`); argumentos
  inválidos → `invalid_argument` sin llamar a HA (FR-018 de la 008;
  principio III).
- **FR-021**: Guía: tema nuevo `backup_integration` (las ocho tools, cuándo
  usar estas o las `sv_*`, la retención, restaurar y su resultado
  `restore_started`, que la clave de cifrado no sale nunca y se cambia en la
  interfaz de HA) con alias; el tema `backups` explica los safety backups
  cifrados y la opción. El índice lo menciona (FR-011 de la 008; CAP-008).
- **FR-022**: Banco de Core: `backup:` en la configuración; se ejecutan
  `ha_list_backup_agents` (lectura, exigida por ejecución como las de la 029),
  `ha_update_backup_config`, `ha_create_backup`, `ha_create_automatic_backup`
  y `ha_delete_backup` (en el inventario de escrituras) comprobando el efecto
  con el lector, y la lectura de la clave; `ha_restore_backup` (se prueban la
  vista previa, el token y la contraseña incorrecta sin reinicio) y
  `ha_set_update_backup_settings` van a su lista de no ejecutables con motivo;
  de `ha_get_update_backup_settings` se prueba en el banco su
  `supervisor_integration_unavailable`; las seis modificadoras, en la matriz de
  la 014 (FR-015 y FR-016 de la 008; CAP-034).
- **FR-023**: Nada de lo actual se rompe con la configuración por defecto
  salvo lo que FR-068 de la 008 manda (los safety backups salen cifrados si
  hay clave): mismas tools, nombres, anotaciones y argumentos de la 1.1.2;
  `ha_list_backups` solo añade un campo; un backup protegido sin `password` en
  `sv_restore_backup_*` pasa de fallar a intentar la clave de HA (FR-020 de la
  008).
- **FR-024**: Documentación en el mismo cambio: sección «Backups de Home
  Assistant» en `## [1.2.0]` de `hermes/CHANGELOG.md`; estado de la 031 en la
  tabla del programa de `docs/HOJA-DE-RUTA.md` y quitar «Cifrado de los safety
  backups» de lo pendiente; filas de la matriz de pruebas; `hermes/DOCS.md`
  (opción y familia); `README.md` y `README.es.md` sincronizados (recuento y
  familia); `SECURITY.md` (cómo se custodia la clave); filas CAP-027 y CAP-057
  de la matriz de la 008. Solo marcadores genéricos (FR-021, FR-023 y FR-024
  de la 008; principio VIII).

### Entidades clave

- **Agente de backup**: ubicación de la integración `backup` (`agent_id`,
  nombre, tipo, si cifra, retención propia).
- **Configuración de backups de HA**: programación, retención, agentes y
  contenido de los backups automáticos; su contraseña nunca sale.
- **Estimación de retención**: backups automáticos que la retención borraría y
  cuándo.
- **Vista previa de restaurar / borrar / crear**: lo que se describe y se ata
  al token (data-model.md).
- **Clave de cifrado de HA**: la de `create_backup.password`; Hermes la usa y
  la descarta.
- **Opción `safety_backup_encryption`** y la marca `encrypted` de la anotación
  de la retención.

## Criterios de éxito *(obligatorio)*

### Resultados medibles

- **SC-001**: Los seis comandos de CAP-057 que una app puede mandar tienen
  tool dedicada, los dos de `hassio/update/config/*` están en `deny` con el
  motivo del proxy del Supervisor (DV-1), y ninguna entrada de la tabla dice
  «pendiente de tool dedicada (spec 031)».
- **SC-002**: Un valor centinela puesto como clave de cifrado en HA no aparece
  en ninguna respuesta, vista previa, error, fichero de token, fichero de
  estado ni log de ninguna tool de esta sub-feature ni de los safety backups
  (tests unitarios y del banco).
- **SC-003**: Una vista previa de restaurar enseña todos los datos de FR-007
  (sección 8 de data-model.md) y cualquier cambio del backup entre vista
  previa y confirmación impide restaurar (un test por cada dato atado).
- **SC-004**: Con `safety_backup_encryption: auto` y clave en HA, el 100 % de
  los safety backups se crean cifrados, y la retención los poda igual que hoy
  poda los no cifrados.
- **SC-005**: Las cinco tools que se ejecutan en el banco pasan contra HA Core
  2026.11.1 real con el efecto comprobado por el lector; la estimación de
  retención acierta el backup que HA borra de verdad en el banco.
- **SC-006**: Con la familia desactivada, el registro de tools es exactamente
  el de antes de la 031.

## Supuestos

- La instalación de producción es HA OS con Supervisor (agentes `hassio.*`);
  el banco es Core sin Supervisor (agente `backup.local`). Las reglas de HA que
  difieren (apps y carpetas, restaurar la base de datos) se describen en la
  vista previa según los agentes presentes.
- La 019 está integrada antes de implementar el tramo 3 (HMAC del
  `action_hash`): sin él, una contraseña atada al token dejaría en disco un
  SHA-256 atacable sin conexión. El tramo 3 no empieza sin ella.
- La clave de cifrado de HA es la que el usuario guarda en su kit de
  emergencia; si la cambia en HA, los backups anteriores (de HA y de Hermes) se
  descifran con la anterior, como hoy en HA.
- Los textos de los agentes (nombres de montajes) los elige el usuario y no
  son secretos; los errores de los agentes sí se enmascaran.
