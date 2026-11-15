# Especificación: Hermes 1.2.0 — montajes de red y ajustes de backup del Supervisor (sub-feature 019)

**Directorio de la spec**: `specs/019-montajes-y-ajustes-de-backup`

**Creada**: 2026-11-14

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T016 de su `tasks.md` y cubre **CAP-083** (montajes de
red CIFS/NFS para backups, medios y `share`, y ajustes de backup del
Supervisor) con tools dedicadas, que es **FR-066** de la 008. Depende de la
011 (tabla, genéricas y familias) y de la 014 (matriz de pruebas y
procedimiento del Supervisor); el inventario de argumentos atados al token es
de la 033.

**Entrada**: `specs/008-cobertura-total/` (spec FR-066 y transversales
FR-010, FR-012, FR-016, FR-018…FR-021, FR-023, FR-024; plan con la matriz de
trazabilidad; research CAP-083; `inventario/supervisor-rutas.tsv`), la spec 011
(`command_table.py`, `command_policy.py`, `tool_families.py`, `sv_read_api`,
`sv_call_api`), la 014 (matriz de `docs/HOJA-DE-RUTA.md` y
`docs/BANCO-SUPERVISOR.md`), la 033 (`tests/test_confirmation_args_inventory.py`)
y el código de Hermes: `tools/backups.py` (`sv_create_backup_full`,
`sv_create_backup_partial`, `sv_list_backups`), `tools/addons.py`
(`sv_set_addon_options`), `tools/filesystem_write.py` (`fs_set_secret`),
`security.py` (`create_confirmation_token`, `validate_confirmation_token`,
`redact_secrets`, `redact_structure`, `REDACTED_MARKER`),
`tools/_annotations.py` y `tools/guide.py`. Contrastado con el código del
Supervisor 2026.11.0 (`supervisor/api/mounts.py`, `api/backups.py`,
`mounts/manager.py`, `mounts/mount.py`, `mounts/validate.py`,
`mounts/const.py`, `backups/manager.py`, `backups/backup.py`,
`api/middleware/security.py`).

## Clarificaciones

### Sesión 2026-11-14

Decisiones vinculantes del programa (ya están en la 008):

- CAP-083 va por **tools dedicadas** (vía D de la matriz): las nueve rutas del
  Supervisor de montajes y ajustes de backup pasan de `deny` «pendiente de tool
  dedicada (spec 019)» a `dedicated`.
- **Confirmación** en crear, editar y borrar montajes y en fijar el montaje
  por defecto de backups. La contraseña CIFS entra, pero nunca se devuelve ni
  se registra (FR-066 de la 008).
- `location` en `sv_create_backup_*`, **nunca `.cloud_backup`** (research
  CAP-083 de la 008).
- Las tools nuevas van en una **familia nueva** de la 1.2.0 (FR-010 de la 008).
- El Supervisor del banco de pruebas es **simulado**: todas las `sv_*` de esta
  sub-feature se prueban con el Supervisor simulado de la suite y van a la
  matriz de la 014 como **VM / pendiente** (FR-016 de la 008).
- Los backups de la integración `backup` de Home Assistant (`backup/*`,
  agentes, safety backups cifrados) son de la **031**: esta sub-feature no los
  toca.

Decisiones tomadas al especificar (no había a quién preguntar; se justifican
en [research.md](research.md)):

- P: ¿Una familia o dos? → R: **una**, `mounts` («desde» 1.2.0, desactivable),
  con dos módulos: `mounts` (montajes) y `backup_settings` (ajustes de backup).
  `location` se queda en las tools de la familia `backups` de la 1.1.2
  (research R-1).
- P: ¿Qué tipos de montaje se crean y editan? → R: **CIFS, NFS y `disk`**
  (decisión del supervisor del programa al implementar el tramo 1, que
  sustituye a la de especificar: «CIFS y NFS; `disk` como duda»). El
  Supervisor 2026.11.0 crea montajes de un disco local por `POST /mounts`, y
  al pasar esa ruta (y `PUT /mounts/{mount}`) a `dedicated` no puede quedar
  ningún hueco. Un `disk` lleva `device` y/o `uuid` y nada de red (research
  R-2).
- P: ¿Argumentos sueltos o un documento de configuración? → R: **sueltos**,
  uno por campo del Supervisor, para que el esquema diga qué es cada cosa y
  la contraseña no viaje anidada en un documento que se pueda copiar a una
  vista previa (research R-3).
- P: ¿Editar reemplaza o funde? → R: **funde**: lo que no se pasa conserva el
  valor actual leído del Supervisor. Las credenciales no se pueden leer (el
  Supervisor nunca las devuelve), así que en un montaje CIFS editado sin
  `username` y `password` **se quitan** si las tenía; la vista previa lo dice
  (research R-4).
- P: ¿Qué es secreto? → R: **el usuario y la contraseña** de CIFS. No salen en
  ninguna respuesta, vista previa, error ni log; la vista previa solo dice si
  se fijan, se reemplazan o se quitan. Entran en el hash del token como hoy
  `fs_set_secret`, `sv_set_addon_options` y `sv_restore_backup_*` (atados, no
  omitibles: en disco solo queda el SHA-256 de la acción) (research R-5).
- P: ¿Qué ata el token además de los argumentos? → R: la **huella del estado**
  que describe la vista previa (la configuración actual del montaje sin
  secretos, el montaje por defecto y, al borrar, los backups afectados). Si
  cambia entre la vista previa y la confirmación, no se ejecuta (research R-6).
- P: ¿Confirmación al recargar un montaje, fijar `days_until_stale` o recargar
  backups? → R: **no**: FR-066 de la 008 no la pide, ninguna borra ni
  interrumpe nada (recargar un montaje solo comprueba su salud y lo rearma) y
  las tres son idempotentes (research R-7).
- P: ¿Qué son «los ajustes de backup del Supervisor»? → R: en el Supervisor
  2026.11.0, `POST /backups/options` solo acepta `days_until_stale`.
  `sv_get_backup_settings` los lee junto con el montaje por defecto y los
  montajes de backup disponibles (research R-8).

### Decisiones del supervisor del programa (tramo 1)

- **Montajes `disk`**: `sv_create_mount` y `sv_update_mount` admiten
  `type="disk"` con `device` (ruta bajo `/dev/`) y/o `uuid`; ningún tipo que
  el Supervisor cree por esas rutas queda sin tool (research R-2).
- **Hash del token con clave** (transversal, `security.py`): el
  `action_hash` pasa a HMAC-SHA256 con una clave aleatoria de 32 bytes
  generada en memoria al arrancar, que nunca se escribe en disco ni en el
  log. El hash de unos argumentos con una contraseña ya no se puede atacar
  sin conexión aunque se lea el directorio de tokens (research R-5; cierra la
  duda D-019-2).
- **Huella del estado**: va por el `estado` de `create_confirmation_token` y
  `resolve_confirmation_token` que añadió la 018 (integrada después de
  especificar), no como una clave `_estado` dentro de los argumentos. Mismo
  efecto (el token ata el estado y, si cambia, no se ejecuta y se pide otra
  vista previa) con el mecanismo común (research R-6).

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es el administrador de Home Assistant que gestiona su sistema
desde un cliente MCP.

### Historia 1 — Llevar los backups a un NAS (Prioridad: P1)

Quien tiene un NAS quiere que los backups del Supervisor (también los safety
backups de Hermes) salgan del disco del equipo, sin abrir la interfaz.

**Prueba independiente**: con el Supervisor simulado, `sv_create_mount` sin
token devuelve una vista previa sin la contraseña y un token; con el token,
hace un `POST /mounts` con la carga exacta; ni la respuesta, ni la vista
previa, ni el log, ni el fichero del token contienen el usuario ni la
contraseña centinela.

**Escenarios de aceptación**:

1. **Dado** ningún montaje, **cuando** el agente llama a
   `sv_create_mount(name="nas_backups", type="cifs", usage="backup",
   server="nas.local", share="backups", username=…, password=…)`, **entonces**
   recibe una vista previa con nombre, tipo, uso, servidor, recurso y
   `credentials: "set"`, que dice que pasará a ser el montaje por defecto de
   backups (no hay otro) y que el Supervisor probará la conexión al crearlo; ni
   el usuario ni la contraseña aparecen.
2. **Dado** el token de esa vista previa, **cuando** se repite la llamada con
   los mismos argumentos, **entonces** el Supervisor recibe la carga con las
   credenciales y la respuesta devuelve el montaje creado, leído de vuelta, sin
   credenciales.
3. **Dado** el mismo token, **cuando** se confirma con otra contraseña,
   **entonces** no se ejecuta nada: el token no casa con la acción.
4. **Dado** un NAS que no responde, **cuando** se confirma, **entonces** el
   error del Supervisor vuelve redactado, sin el usuario ni la contraseña, y
   con una pista para mirar `sv_get_resolution`.
5. **Dado** un montaje de backup, **cuando** el agente llama a
   `sv_create_backup_full(name, location="nas_backups")` o con
   `location=".local"`, **entonces** el backup va a ese montaje o al disco
   local; sin `location`, la petición es la de la 1.1.2 (va al montaje por
   defecto, si lo hay).

### Historia 2 — Cambiar o quitar un montaje sin romper nada a ciegas (Prioridad: P1)

Quien cambia de NAS, de contraseña o deja de usar un montaje quiere saber
antes qué pasará con sus backups y con el montaje por defecto.

**Prueba independiente**: con el Supervisor simulado (montajes y lista de
backups con `locations`), las vistas previas de `sv_update_mount`,
`sv_delete_mount` y `sv_set_default_backup_mount` describen los efectos
exactos y no cambian nada; con el token, se hace la petición prevista.

**Escenarios de aceptación**:

1. **Dado** un montaje CIFS con credenciales, **cuando** el agente llama a
   `sv_update_mount(name, server="nas2.local")` sin credenciales, **entonces**
   la vista previa enseña el cambio de servidor, avisa de que las credenciales
   que tenga **se quitarán** (el Supervisor reemplaza la configuración entera y
   Hermes no puede leerlas) y de que el montaje se desmonta y se vuelve a
   montar.
2. **Dado** `sv_update_mount(name, password=…, username=…)`, **entonces** la
   vista previa dice `credentials: "replaced"` y no enseña ni el usuario ni la
   contraseña.
3. **Dado** un montaje de backup con 3 backups y que es el montaje por
   defecto, **cuando** el agente llama a `sv_delete_mount(name)`, **entonces**
   la vista previa dice que es el montaje por defecto (los backups nuevos irán
   al disco local), que esos 3 backups (con su nombre, fecha y slug)
   desaparecerán de la lista del Supervisor y dejarán de poder restaurarse
   desde Home Assistant, y que los ficheros siguen en el NAS.
4. **Dado** un montaje de medios o de `share`, **cuando** se previsualiza su
   borrado, **entonces** la vista previa dice que su contenido deja de estar
   disponible para Home Assistant y los add-ons en su ruta.
5. **Dado** un montaje que cambió (otro servidor, otro uso) entre la vista
   previa y la confirmación, **cuando** se confirma, **entonces** no se
   ejecuta y se pide una vista previa nueva.
6. **Dado** `sv_set_default_backup_mount(name=None)`, **entonces** la vista
   previa dice qué montaje deja de ser el de por defecto y que los backups
   nuevos sin `location` irán al disco local; con un montaje de uso `media`,
   **entonces** se rechaza sin token.

### Historia 3 — Ver y ajustar los montajes y los backups (Prioridad: P2)

Quien diagnostica un NAS caído o un aviso de «no hay backup reciente» quiere
ver el estado de los montajes, recargarlos, ver y cambiar cuándo un backup se
considera viejo y releer los backups tras copiarlos a mano al NAS.

**Escenarios de aceptación**:

1. **Dado** un montaje CIFS y uno NFS, **cuando** el agente llama a
   `sv_list_mounts()`, **entonces** recibe `{count, items, truncated}` con
   nombre, tipo, uso, servidor, recurso o ruta, puerto, versión, solo lectura,
   estado y ruta para los add-ons, el montaje por defecto, y nunca
   credenciales, aunque el Supervisor las mandara.
2. **Dado** un montaje caído, **cuando** el agente llama a
   `sv_reload_mount(name)`, **entonces** el Supervisor lo comprueba y lo
   rearma; si sigue fallando, el error vuelve redactado con la pista de
   `sv_get_resolution`.
3. **Dado** `sv_get_backup_settings()`, **entonces** recibe `days_until_stale`,
   el montaje por defecto (o `null` = disco local) y los montajes de uso
   `backup`.
4. **Dado** `sv_set_backup_settings(days_until_stale=7)`, **entonces** el
   Supervisor recibe `{"days_until_stale": 7}` y la respuesta dice el valor
   anterior y el nuevo; con `0`, `-1`, `true` o texto, se rechaza sin llamar.
5. **Dado** backups copiados a mano al NAS, **cuando** el agente llama a
   `sv_reload_backups()`, **entonces** el Supervisor relee todas las
   ubicaciones.

### Historia 4 — Nada de lo que funciona hoy cambia (Prioridad: P1)

**Escenarios de aceptación**:

1. **Dado** `sv_create_backup_full(name, password)` o
   `sv_create_backup_partial(...)` como en la 1.1.2, **entonces** la petición
   (ruta y carga) y la respuesta son las de la 1.1.2: la carga no lleva
   `location`.
2. **Dado** `tool_families_disabled: [mounts]`, **entonces** las 9 tools nuevas
   no se registran, sus 9 rutas siguen `dedicated` en la tabla y
   `sv_create_backup_*` conserva `location`.
3. **Dado** `sv_read_api("/mounts")` o `sv_call_api("POST", "/mounts", …)`,
   **entonces** la respuesta es `use_dedicated_tool` con el nombre de la tool,
   sin llamar al Supervisor.

### Casos límite

- `username` sin `password` o al revés → `invalid_argument` (el Supervisor
  exige los dos o ninguno); sin ninguno, el montaje CIFS es de invitado
  (`guest`) y la vista previa lo dice.
- Credenciales, `share`, `version` o `port` fuera de lugar en NFS, o `path` en
  CIFS → `invalid_argument`: el Supervisor los descartaría en silencio y la
  vista previa enseñaría algo que no se aplica.
- `usage="backup"` con `read_only=True` → `invalid_argument` (el Supervisor
  no lo admite).
- `type` distinto de `cifs`, `nfs` o `disk` al crear o editar →
  `unsupported_mount_type`. Un `disk` sin `device` ni `uuid`, o con campos de
  red o credenciales → `invalid_argument`; `device` o `uuid` en CIFS o NFS →
  `invalid_argument`.
- Nombre que ya existe al crear → error que sugiere `sv_update_mount`, sin
  token. Nombre que no existe al editar, borrar o recargar → `mount_not_found`
  sin token y sin llamada de escritura.
- Un usuario o una contraseña con saltos de línea o caracteres de control →
  `invalid_argument` sin copiar el valor: el Supervisor los escribe en un
  fichero de credenciales `clave=valor` por líneas y un salto de línea
  inyectaría opciones.
- Un usuario o una contraseña igual al marcador de redacción
  (`***REDACTED***`) → `invalid_argument`: guardarlo machacaría la
  credencial real con el marcador (mismo criterio que `sv_set_addon_options`).
- El error del Supervisor contiene el usuario o la contraseña literal → se
  sustituyen antes de devolverlo, además de `redact_secrets`.
- `location` con `.cloud_backup` → `invalid_argument` (lo reserva el
  Supervisor para Home Assistant); lista vacía, repetida o con un nombre de
  forma inválida → `invalid_argument` sin llamar; un montaje que no existe o
  que no es de backup → el error del Supervisor, redactado.
- Borrar el único montaje de backup mientras un backup está en curso → el
  error del Supervisor (job en curso), redactado; nada se borra.
- `days_until_stale` < 1, booleano, decimal o texto → `invalid_argument`.
- Respuesta del Supervisor con una forma inesperada (sin `mounts`, no es un
  objeto) → `error` de forma inesperada; nunca una lista vacía como si fuera
  buena.
- Supervisor caído → el error de conexión de siempre.

## Requisitos *(obligatorio)*

Cada FR cita el FR de la 008 y la CAP que cubre.

### Requisitos funcionales

#### Montajes de red (CAP-083)

- **FR-001**: `sv_list_mounts()` lee `GET /mounts` y devuelve
  `{default_backup_mount, count, items, truncated}`. Cada elemento lleva solo
  las claves de una lista permitida (`name`, `type`, `usage`, `read_only`,
  `server`, `port`, `share`, `path`, `version`, `state`, `user_path` y, en un
  montaje `disk`, `uuid` y `filesystem`); cualquier otra clave, también
  `username` y `password`, se descarta, y el resultado pasa por
  `redact_structure` (008 FR-066, FR-018, FR-019; CAP-083).
- **FR-002**: `sv_create_mount(name, type, usage, server, share=None,
  path=None, port=None, version=None, read_only=False, username=None,
  password=None, confirmation_token=None)` crea un montaje CIFS o NFS con
  `POST /mounts`, **siempre en dos pasos**; también un montaje de disco local
  (`type="disk"`, con `device` y/o `uuid`; firma ampliada con
  `device=None, uuid=None`). La vista previa enseña la carga sin
  credenciales, `credentials` (`"set"` o `"none"`, que en CIFS es acceso de
  invitado), si pasará a ser el montaje por defecto de backups (uso `backup` y
  ninguno por defecto), que el Supervisor relee los backups (uso `backup`) y
  que el Supervisor prueba la conexión al crearlo y no lo crea si falla (en
  `disk`: que comprueba que el dispositivo es un sistema de ficheros montable
  que no es de Home Assistant OS). Un
  nombre que ya existe se rechaza en la vista previa. Tras ejecutar, devuelve
  el montaje leído de vuelta de `GET /mounts` (008 FR-066; CAP-083).
- **FR-003**: `sv_update_mount(name, type=None, usage=None, server=None,
  share=None, path=None, port=None, version=None, read_only=None,
  username=None, password=None, device=None, uuid=None,
  confirmation_token=None)` edita un montaje CIFS, NFS o `disk` existente con
  `PUT /mounts/{name}`, **siempre en dos pasos**. Los
  campos no pasados conservan el valor actual leído de `GET /mounts`
  (`version="auto"` vuelve a la negociación automática); cambiar `type` exige
  los campos del tipo nuevo y descarta los del viejo. La vista
  previa enseña cada campo que cambia (de → a), `credentials` (`"replaced"` si
  se pasan; si no, `"removed_if_present"` con el aviso de que el Supervisor
  quita las que tuviera y Hermes no puede saber si las tiene), que el montaje
  se desmonta y se vuelve a montar, si deja de ser el montaje por defecto
  (deja de ser de uso `backup`) y, si era de uso `backup` y cambia de uso o
  de destino (tipo, servidor, recurso, ruta, puerto, `device` o `uuid`),
  cuántos backups dejarán
  de verse, como en FR-004 (008 FR-066; CAP-083).
- **FR-004**: `sv_delete_mount(name, confirmation_token=None)` borra un
  montaje con `DELETE /mounts/{name}`, **siempre en dos pasos**. La vista
  previa enseña el montaje (sin credenciales), su uso y su estado; si es de
  uso `backup`, si es el montaje por defecto (los backups nuevos sin
  `location`, también los safety backups de Hermes, irán al disco local) y los
  backups cuya lista de ubicaciones (`locations` de `GET /backups`) lo incluye:
  cuántos, los 20 más recientes con nombre, fecha y slug (y si hay más),
  cuántos solo están en ese
  montaje (desaparecen de la lista y no se pueden restaurar desde Home
  Assistant) y que los ficheros siguen en el servidor; si es de uso `media` o
  `share`, que su contenido deja de estar disponible en esa ruta para Home
  Assistant y los add-ons (008 FR-066; CAP-083).
- **FR-005**: `sv_reload_mount(name)` pide `POST /mounts/{name}/reload` (el
  Supervisor comprueba la salud del montaje y rearma su disparador) y devuelve
  el montaje leído de vuelta. Sin confirmación (008 FR-066; CAP-083).
- **FR-006**: `sv_set_default_backup_mount(name, confirmation_token=None)`
  fija el montaje por defecto de backups con `POST /mounts/options`
  (`{"default_backup_mount": name}`; `name=None` vuelve al disco local),
  **siempre en dos pasos**. La vista previa dice el montaje por defecto actual
  y el nuevo y que los backups sin `location` (también los safety backups de
  Hermes) irán ahí. Un montaje que no existe o que no es de uso `backup` se
  rechaza sin token (008 FR-066; CAP-083).
- **FR-007**: Validación común, **fail-closed y antes de cualquier llamada de
  escritura**: `name` casa `^[A-Za-z0-9_]{1,64}$`; `type` es `cifs`, `nfs` o
  `disk` al crear o editar; `usage` es `backup`, `media` o `share`; en `disk`,
  `device` (ruta absoluta bajo `/dev/`, sin `..` ni caracteres de control,
  como mucho 255) o `uuid` (`^[A-Za-z0-9-]{1,64}$`), al menos uno, y ningún
  campo de red ni credenciales; `device` y `uuid` solo en `disk`; `server` no tiene
  `/`, `\`, espacios ni caracteres de control y mide como mucho 253
  caracteres; `share` no tiene `/`, `\` ni caracteres de control; `path`
  (NFS) es absoluto y sin caracteres de control; `port` es un entero de 1 a
  65535; `version` (CIFS) es `1.0`, `2.0`, `auto` o nada (`auto` y nada piden
  la negociación automática al crear; al editar, nada deja la actual y `auto`
  vuelve a la automática); `read_only` es
  booleano y no se admite con uso `backup`; `username` y `password` van los dos
  o ninguno, solo en CIFS, sin caracteres de control y distintos del marcador
  de redacción. Lo inválido devuelve `invalid_argument` con la regla que
  falla, **nunca con el valor** (principio II, III; 008 FR-066).
- **FR-008**: **Secretos.** `username` y `password` de CIFS no aparecen en
  ninguna respuesta, vista previa, error ni evento de log de Hermes. Entran en
  el hash del token (atados) y no se guardan en el fichero del token (no son
  omitibles): en disco solo queda el HMAC-SHA256 de la acción, con una clave
  que vive solo en memoria, como con
  `fs_set_secret`, `sv_set_addon_options` y `sv_restore_backup_*`. Todo texto
  de error del Supervisor pasa por la sustitución literal de los dos valores y
  por `redact_secrets` antes de devolverse (principio II; 008 FR-019, FR-066;
  CAP-083).
- **FR-009**: **Token atado a la acción y al estado.** El token de
  `sv_create_mount`, `sv_update_mount`, `sv_delete_mount` y
  `sv_set_default_backup_mount` ata todos los argumentos de su firma (salvo
  el propio token) y la huella del estado que describe su vista previa: el
  montaje actual sin secretos, el montaje por defecto y, al borrar, los slugs
  de los backups afectados. En la confirmación, Hermes vuelve a leer el estado
  y, si la huella cambió, no ejecuta y pide una vista previa nueva. Las cuatro
  tools entran en el inventario de argumentos atados de la 033 con todos sus
  argumentos `atado` (principio IV; 008 FR-018, FR-066).
- **FR-010**: Si el Supervisor responde con error, la tool devuelve `error`
  con el mensaje redactado (FR-008); en los fallos al montar
  (`sv_create_mount`, `sv_update_mount`, `sv_reload_mount`), con la pista de
  mirar `sv_get_resolution`, donde el Supervisor deja el aviso del montaje.
  Una respuesta de forma inesperada da `error`, nunca datos inventados ni una
  lista vacía (principio I, III, V; 008 FR-066).

#### Ajustes de backup del Supervisor (CAP-083)

- **FR-011**: `sv_get_backup_settings()` lee `GET /backups/info` y
  `GET /mounts` y devuelve `days_until_stale` (días tras los que un backup
  completo deja de contar como reciente para el aviso del Supervisor),
  `default_backup_mount` (`null` = disco local) y `backup_mounts` (nombres de
  los montajes de uso `backup`, con su estado). No devuelve la lista de
  backups (eso es `sv_list_backups`) (008 FR-066; CAP-083).
- **FR-012**: `sv_set_backup_settings(days_until_stale)` envía
  `POST /backups/options` con `{"days_until_stale": N}` y devuelve el valor
  anterior y el nuevo. `days_until_stale` es un entero ≥ 1 (no booleano). Sin
  confirmación (008 FR-066; CAP-083).
- **FR-013**: `sv_reload_backups()` pide `POST /backups/reload` (el Supervisor
  relee los backups de todas las ubicaciones) y devuelve el número de backups
  que ve después, leído de `GET /backups`. Sin confirmación (008 FR-066;
  CAP-083).
- **FR-014**: `sv_create_backup_full` y `sv_create_backup_partial` aceptan
  `location` **opcional**: el nombre de un montaje de uso `backup`, `.local`
  (disco local) o una lista sin repetidos de esos valores (el primero es la
  ubicación principal y el resto, copias). `.cloud_backup` se rechaza, como
  una lista vacía o un nombre de forma inválida, sin llamar al Supervisor. Sin
  `location`, la carga y la respuesta son exactamente las de la 1.1.2 (el
  Supervisor usa el montaje por defecto). Con `location`, la respuesta y el
  evento de log nombran la ubicación pedida (008 FR-066, FR-020; CAP-083).

#### Tabla de clasificación (CAP-083)

- **FR-015**: Pasan a `dedicated`, en el mismo cambio que su tool, las 9
  entradas del Supervisor de CAP-083 (lista en
  [data-model.md](data-model.md)), con la familia `mounts` y `cap="CAP-083"`.
  Regenerar con `scripts/inventario/generar_tabla.py` deja la tabla idéntica
  y no queda ninguna entrada «pendiente de tool dedicada (spec 019)» (008
  FR-012, FR-066; CAP-001).

#### Convenciones, familia, guía y documentación

- **FR-016**: Las 9 tools nuevas van en la familia nueva `mounts` (1.2.0,
  desactivable; módulos `mounts` y `backup_settings`). Anotaciones:
  `sv_list_mounts` y `sv_get_backup_settings`, `readOnlyHint`;
  `sv_create_mount`, `sv_update_mount`, `sv_delete_mount` y
  `sv_set_default_backup_mount`, `destructiveHint` (piden token);
  `sv_reload_mount`, `sv_set_backup_settings` y `sv_reload_backups`, ni de
  solo lectura ni destructivas, e idempotentes; ninguna de mundo abierto. Con
  la familia desactivada no se registran y sus entradas siguen `dedicated`
  (008 FR-010, FR-018; CAP-004).
- **FR-017**: Las 216 tools de la 1.1.2 conservan nombre, anotaciones y
  argumentos; la única diferencia de esquema es `location`, opcional, en
  `sv_create_backup_full` y `sv_create_backup_partial`, anotada junto a las
  que ya permite la instantánea de esquemas de la 011 (008 FR-020).
- **FR-018**: `hermes_guide` tiene el tema `mounts` (con alias `cifs`, `nfs`,
  `nas`, `network_storage` y `backup_settings`), que explica las 9 tools, el
  flujo de llevar los backups a un NAS, que las credenciales no se devuelven y
  que editar sin ellas las quita; el tema `backups` menciona `location` (008
  FR-011, FR-018).
- **FR-019**: Tests con valores centinela de usuario y contraseña en
  `sv_create_mount` y `sv_update_mount` (vista previa, confirmación, error del
  Supervisor que los repite, respuesta y fichero del token) y en
  `sv_list_mounts` (un Supervisor que los devolviera) comprueban que no
  aparecen en la respuesta, el error, el log de Hermes ni el directorio de
  tokens (008 FR-019; principio II).
- **FR-020**: Cada evento de log de las tools nuevas lleva la tool, el nombre
  del montaje, el tipo, el uso, los nombres de los campos que cambian y el
  resultado; nunca el servidor, el recurso, la ruta, el usuario ni la
  contraseña (principio II, VIII; 008 FR-019).
- **FR-021**: Las 7 tools nuevas que modifican (`sv_create_mount`,
  `sv_update_mount`, `sv_delete_mount`, `sv_reload_mount`,
  `sv_set_default_backup_mount`, `sv_set_backup_settings`,
  `sv_reload_backups`) tienen su fila en la matriz de la 014 como `VM` /
  `pendiente` y su línea en «Tandas de pruebas» de
  `docs/BANCO-SUPERVISOR.md`; la línea de `sv_create_backup_*` dice que se
  prueba también `location` (008 FR-016; CAP-006).
- **FR-022**: Documentación en el mismo cambio: sección propia en
  `## [1.2.0]` de `hermes/CHANGELOG.md`; estado de la 019 en la tabla del
  programa de `docs/HOJA-DE-RUTA.md`, con la prueba en la VM como pendiente;
  `README.md` y `README.es.md` sincronizados con la familia nueva en la lista
  de `tool_families_disabled`; `hermes/DOCS.md` con la familia en «Familias de
  tools»; fila CAP-083 de la matriz de la 008 con las tools y los ficheros de
  test (008 FR-016, FR-021, FR-023, FR-024).

### Entidades clave

- **Montaje**: `name`, `type` (`cifs`, `nfs`, `disk`), `device` y `uuid`
  (`disk`; `device` solo de entrada),
  `usage` (`backup`, `media`, `share`), `read_only`, `server`, `port`,
  `share` y `version` (CIFS), `path` (NFS), `state` y `user_path` (de
  lectura); credenciales CIFS (`username`, `password`), que entran pero nunca
  salen.
- **Montaje por defecto de backups**: nombre de un montaje de uso `backup` o
  `null` (disco local).
- **Ajustes de backup**: `days_until_stale`.
- **Ubicación de backup** (`location`): `.local`, nombre de un montaje de
  backup o lista de ellos.
- **Huella del estado**: lo que la vista previa describe y el token ata
  (data-model).
- **Entrada de la tabla**: la de la 011; cambian categoría, motivo, familia y
  tool (data-model).

## Fuera de alcance

- Los backups de la integración `backup` de Home Assistant
  (`backup/restore`, `backup/delete`, `backup/generate`, agentes, ajustes
  automáticos) y los safety backups cifrados: 031.
- `GET /host/disks` (lo dejó la 013 en `read`) y el uso de disco de un
  montaje (`sv_get_disk_usage` de la 013).
- `POST /backups/freeze`, `/backups/thaw`, `/backups/new/upload` y
  `GET /backups/{slug}/download`: siguen `deny` (clase D).
- Mover un backup existente entre ubicaciones o borrarlo de una sola
  ubicación (`location` en `DELETE /backups/{slug}`): no está en CAP-083.
- `location` en `sv_restore_backup_*` y en `sv_create_safety_backup`.
- La prueba contra un Supervisor real (VM de la 014 o cierre del programa).

## Supuestos

- **S-01**: La 011 completa y la 014 están integradas en la rama (lo están en
  `feat/cobertura-total` desde `cc92b4a`). La 033 (inventario de argumentos
  atados) puede no estarlo al implementar: si `tests/test_confirmation_args_inventory.py`
  existe en la rama, las cuatro tools con token entran en él en el tramo que
  las añade; si no, se anota y se añaden al integrar la 033.
- **S-02**: Las formas de respuesta del Supervisor simulado salen del código
  del Supervisor 2026.11.0 leído, con datos ficticios (`nas.local`,
  `192.0.2.10`, `backups`, centinelas de texto).
- **S-03**: Hermes llama a la API sin la cabecera de versión de
  `aiohasupervisor`, así que `GET /mounts` le enseña también los montajes de
  disco.
- **S-04**: El hash del token con la contraseña dentro es un HMAC-SHA256
  con una clave en memoria (decisión del programa, en `security.py` para
  todas las tools): el fichero del token vive en `/data` del add-on, caduca a
  los 60 s y lleva solo ese hash, nunca el valor.
- **S-05**: La 1.2.0 sale entera: los motivos «pendiente» que queden en la
  tabla son de otras sub-features y los vigila el cierre (FR-098 de la 008).

## Criterios de éxito *(obligatorio)*

- **SC-001**: Las 9 tools nuevas están registradas con la configuración por
  defecto y ninguna con la familia `mounts` desactivada; las 4 con token se
  anuncian destructivas y las 2 de lectura, `readOnlyHint`.
- **SC-002**: Las 9 entradas de FR-015 son `dedicated` y apuntan a una tool
  registrada; `grep -c "spec 019" hermes/src/hermes/command_table.py` da 0;
  regenerar la tabla no cambia nada.
- **SC-003**: En el 100 % de los casos probados de argumento inválido no hay
  ninguna llamada de escritura al Supervisor, y ningún mensaje de error copia
  el valor rechazado.
- **SC-004**: Ningún centinela de usuario o contraseña aparece en respuestas,
  vistas previas, errores, eventos de log ni ficheros del directorio de
  tokens.
- **SC-005**: Un token emitido para una acción no ejecuta otra: cambiar
  cualquier argumento (también la contraseña) o el estado descrito entre la
  vista previa y la confirmación deja la llamada sin ejecutar.
- **SC-006**: Con las familias de la 1.2.0 desactivadas, la lista de tools es
  la de la 1.1.2 con las mismas anotaciones, y `sv_create_backup_*` llamada
  como en la 1.1.2 envía la misma carga.
- **SC-007**: La suite pasa en el CI de Linux al final de cada tramo, con los
  mismos 6 fallos conocidos de Windows en local y ninguno más; cada tramo deja
  anotado su control negativo con recuentos.
- **SC-008**: La matriz de la 014 lista las 7 tools que modifican como
  `VM` / `pendiente` y el procedimiento dice cómo probar cada una.
