# Research: montajes de red y ajustes de backup del Supervisor (019)

Fase 0 del plan. Cada decisión dice qué se eligió, por qué y qué se
descartó. Fuentes: el código del Supervisor 2026.11.0 (solo leído), el de
Hermes en `feat/cobertura-total` (`cc92b4a`) y la spec 008 (CAP-083, FR-066).

## Comprobación contra el Supervisor 2026.11.0

Rutas (`supervisor/api/__init__.py`, `_register_mounts` y `_register_backups`):

| Método | Ruta | Manejador | Qué hace (código leído) |
|---|---|---|---|
| GET | `/mounts` | `APIMounts.info` | `{default_backup_mount, mounts: [to_dict() + state + user_path]}`. `to_dict()` usa `skip_secrets=True`: `CIFSMount` no añade `username` ni `password`. Sin la cabecera de `aiohasupervisor` ≥ 0.7.0 también lista los `disk` |
| POST | `/mounts` | `create_mount` | valida con `SCHEMA_MOUNT_CONFIG` (CIFS, NFS o `disk`); nombre repetido → `APIError`; `MountManager.create_mount` comprueba que el destino local no tenga datos, monta (`mount.load()`) y, si falla, deshace; uso `backup` → relee backups y, si no hay montaje por defecto, **lo fija a este** |
| PUT | `/mounts/{mount}` | `update_mount` | el nombre no puede cambiar; **reemplaza** la configuración entera (`Mount.from_dict(body)`): lo que no viene en el cuerpo, credenciales incluidas, se pierde; desmonta y monta (`create_mount` con `retain_entry`); uso `backup` → relee backups; si era el por defecto y deja de ser `backup`, el por defecto pasa a `None` |
| DELETE | `/mounts/{mount}` | `delete_mount` | desmonta (borra el fichero de credenciales), lo quita y, si era el por defecto, lo deja en `None`; uso `backup` → relee backups |
| POST | `/mounts/{mount}/reload` | `reload_mount` | `repair_trigger()`: comprueba la salud, rearma el disparador autofs y actualiza el aviso del centro de resolución; un montaje sano no se toca. Uso `backup` → relee backups |
| POST | `/mounts/options` | `options` | `{default_backup_mount: str \| null}`; un montaje que no es de uso `backup` → `APIError` |
| GET | `/backups/info` | `info` | `{backups: [...], days_until_stale}` |
| POST | `/backups/options` | `options` | solo `days_until_stale` (`vol.Coerce(int)`, `Range(min=1)`; por defecto 30) |
| POST | `/backups/reload` | `reload` | `sys_backups.reload()` de todas las ubicaciones; devuelve `true` |

Esquemas (`mounts/validate.py`): `name` `^[A-Za-z0-9_]+$`; `type` en
`cifs`/`nfs`/`disk`; `usage` en `backup`/`media`/`share` (`MountUsage`);
`read_only` booleano (por defecto `False`, y no admitido con `backup`);
`server` `vol.Match(r"^[^\\\/]+")` (solo mira el principio); `port`
`network_port`; CIFS: `share` como `server`, `username` y `password`
`vol.Inclusive` (los dos o ninguno), `version` `1.0`/`2.0`/`None`; NFS:
`path` `str`. `extra=vol.REMOVE_EXTRA`: lo que sobra se descarta en silencio.

CIFS (`mounts/mount.py`): con credenciales, escribe
`username=<u>\npassword=<p>` en un fichero propio (modo 600) y monta con
`credentials=<fichero>`; sin ellas, `guest`. Un salto de línea en el usuario o
la contraseña añadiría líneas a ese fichero.

Ubicación de los backups (`backups/manager.py`, `api/backups.py`): sin
`location` se usa el montaje por defecto (`DEFAULT`); `.local` o `null` es el
disco local; `.cloud_backup` solo lo puede pedir Home Assistant
(`_validate_cloud_backup_location`); `location` admite una lista (la primera
es la principal y el resto, `additional_locations`); un montaje que no es de
uso `backup` → `APIError`. `GET /backups` da `location` y `locations` de cada
backup. Al quitar una ubicación, `reload` reconstruye la lista: un backup que
solo estaba en ella desaparece de la lista; los ficheros del servidor no se
tocan.

`days_until_stale` (`backups/backup.py`, `is_current`): un backup completo
más reciente que ese número de días cuenta como «actual» para el chequeo del
centro de resolución (`resolution/checks/backups.py`), que avisa cuando no hay
ninguno.

Rol (`api/middleware/security.py`): `/mounts.*` y `/backups.*` pasan con el
rol `manager`; `tests/test_rutas_supervisor_rol.py` no necesita excepciones.

Tabla de Hermes hoy: las 9 rutas son `deny` «pendiente de tool dedicada (spec
019)» con `cap="CAP-083"` (`grep -c "spec 019"` = 9).

## R-1 — Una familia, `mounts`, con dos módulos

**Decisión**: familia `mounts` («Supervisor network mounts (CIFS/NFS) for
backups and media, and Supervisor backup settings.»), `desde="1.2.0"`,
desactivable, módulos `mounts` (6 tools) y `backup_settings` (3 tools). Tema de
guía con el mismo nombre. `location` se añade a las tools que ya existen y
siguen en la familia `backups` de la 1.1.2.

**Por qué**: FR-010 de la 008 exige familias nuevas para las tools nuevas, de
modo que apagar las de la 1.2.0 deje la lista de la 1.1.2. Una CAP, una
familia: quien no tiene NAS apaga todo de una vez. Dos módulos porque los
ajustes de backup no tienen secretos ni token y se leen mejor aparte.

**Descartado**: meterlas en `backups` (rompería FR-010); dos familias (dos
opciones para una sola capacidad); llamarla `backup_storage` (los montajes
también son de medios y de `share`).

## R-2 — CIFS, NFS y `disk`

**Decisión vigente (supervisor del programa, tramo 1)**: `sv_create_mount` y
`sv_update_mount` aceptan `type` `cifs`, `nfs` o `disk`; cualquier otro (por
ejemplo `bind`, que el Supervisor tiene en su enumeración pero no acepta por
la API) → `unsupported_mount_type`. Un `disk` lleva `device` (ruta bajo
`/dev/`, solo de entrada: el Supervisor la resuelve a `uuid`) y/o `uuid`, al
menos uno (`_device_identifier_required` de `api/mounts.py`), y ni campos de
red ni credenciales. Al editar un `disk` se conserva su `uuid` si no se pasa
otro; `filesystem` no se envía nunca (el Supervisor no lo acepta por la API y
lo vuelve a sondear). La comprobación de que el dispositivo es montable y no
es de Home Assistant OS la hace el Supervisor (`HAOS_LABEL_PREFIX`, guarda de
UDisks2); su error vuelve redactado. Motivo: al pasar `POST /mounts` y
`PUT /mounts/{mount}` a `dedicated`, la genérica deja de alcanzarlos y no
puede quedar ningún tipo sin tool.

**Decisión inicial (sustituida)**: `sv_create_mount` y `sv_update_mount`
aceptan `type` `cifs` o
`nfs`; cualquier otro → `unsupported_mount_type`. `sv_list_mounts`,
`sv_reload_mount` y `sv_delete_mount` funcionan con cualquier montaje que el
Supervisor liste, también `disk`.

**Por qué**: CAP-083 y FR-066 hablan de montajes de red. Los de disco (nuevos
en el Supervisor 2026.x, con `device`/`uuid` y la resolución por UDisks2) son
otra capacidad con otros riesgos (formatear no, pero sí montar una partición
del sistema). Como `POST /mounts` pasa a `dedicated`, crear un montaje de
disco deja de ser alcanzable por la genérica: es fail-closed y se anota como
duda para el final.

**Descartado**: cubrir `disk` (amplía el alcance, principio IX); dejar
`POST /mounts` en la tabla para `disk` (una ruta no se puede repartir entre
`dedicated` y `confirm`).

## R-3 — Argumentos sueltos

**Decisión**: un argumento por campo del Supervisor (`name`, `type`, `usage`,
`server`, `share`, `path`, `port`, `version`, `read_only`, `username`,
`password`).

**Por qué**: el esquema de la tool dice qué es cada cosa y su tipo (el cliente
no inventa claves que el Supervisor descartaría en silencio por
`REMOVE_EXTRA`); la contraseña es un argumento con nombre, fácil de excluir de
la vista previa, del log y de cualquier copia del documento; el inventario de
la 033 clasifica argumentos de la firma, no claves de un documento.

**Descartado**: `config: dict` como en las tools de helpers (habría que
filtrar claves anidadas y el inventario no vería la contraseña).

## R-4 — Editar funde con lo actual; las credenciales no se pueden conservar

**Decisión**: `sv_update_mount` lee `GET /mounts`, toma el montaje actual y
sobrescribe solo los campos pasados; si cambia `type`, parte de cero con los
campos del tipo nuevo (los del viejo no se arrastran). Las credenciales: si se
pasan, se envían (`credentials: "replaced"`); si no, el cuerpo no las lleva y
el Supervisor quita las que hubiera (`credentials: "removed_if_present"` con el
aviso).

**Por qué**: el Supervisor reemplaza la configuración entera y nunca devuelve
las credenciales; Hermes no puede saber si un montaje CIFS las tiene. Fundir
evita que el agente tenga que reescribir servidor, recurso y uso para cambiar
solo la versión; avisar de las credenciales evita que una edición inocente
deje un montaje de invitado que deja de montar. La vista previa no puede
afirmar «se quitarán» (puede que no tuviera), por eso dice «si las tiene».

**Descartado**: reemplazo puro como el Supervisor (obliga a repetir todo y no
quita la trampa de las credenciales); exigir siempre las credenciales en CIFS
(rompe los montajes de invitado); un argumento `keep_credentials` (imposible
de cumplir: Hermes no las tiene).

## R-5 — Credenciales: qué entra, qué sale y qué se guarda

**Decisión**:

- `username` y `password` se tratan como secretos los dos (el usuario de un
  NAS es la mitad de la credencial y suele ser una cuenta de la casa).
- La vista previa dice solo `credentials` (`"set"`, `"none"`, `"replaced"` o
  `"removed_if_present"`).
- Atados en el hash del token y **no omitibles**: `create_confirmation_token`
  solo escribe en disco el `action_hash` (HMAC-SHA256 de la acción canónica
  con una clave en memoria, ver abajo) y,
  sin `omitibles`, ningún argumento (lo dice su comentario: «guardar todos los
  argumentos escribiría en disco, por ejemplo, las opciones con contraseñas de
  sv_set_addon_options»). Es el patrón de `fs_set_secret` (`value` atado),
  `sv_set_addon_options` (`options` atadas) y `sv_restore_backup_*`
  (`password` atada) en el inventario de la 033.
- Rechazo local de caracteres de control y del marcador `***REDACTED***`
  (mismo criterio que `sv_set_addon_options`: un valor tapado que se reenvía
  machacaría el real).
- Los errores del Supervisor se limpian de los dos valores literales (si el
  valor mide 4 caracteres o más; uno más corto se tapa igual, pero el test
  usa centinelas largos) y pasan por `redact_secrets`.
- `redact_structure` no tapa `username` (no es una clave sensible para Hermes y
  cambiarlo afectaría a todas las tools): por eso las respuestas usan una
  lista **permitida** de claves y no confían solo en la redacción.

**Por qué**: principio II (un secreto no llega a un log, un error ni un
retorno) y el punto de atención del encargo («no se guardan en el disco de los
tokens»).

**Riesgo residual, cerrado en el tramo 1**: el SHA-256 de la acción incluía
la contraseña; con acceso de lectura a `/data` durante los 60 s del token,
una contraseña débil se podía adivinar probando contra el hash (lo mismo con
`fs_set_secret` y `sv_restore_backup_*`). Por decisión del supervisor del
programa, `compute_action_hash` pasa a HMAC-SHA256 con una clave aleatoria de
32 bytes generada al arrancar, que nunca se escribe en disco ni en el log.
Cambia en cada arranque y no pasa nada: los tokens caducan a los 60 s y uno
de antes del arranque se responde como «lost across restart»; la
idempotencia y `cached_result` van por el fichero del token, y
`canonicalize_for_hash` (sin clave) solo compara valores en el momento.

## R-6 — La huella del estado entra en el token

**Mecanismo vigente (tramo 1)**: la 018, integrada después de especificar,
añadió `estado=` a `create_confirmation_token` y a
`resolve_confirmation_token`: la huella se guarda como `state_hash` y, si el
estado cambió, la confirmación da `ESTADO_CAMBIADO` sin gastar el token. Las
tools de montajes usan ese mecanismo común (error `mount_changed`) en vez de
una clave `_estado` dentro de los argumentos; el contenido de la huella es el
de la tabla.

**Decisión inicial (sustituida en el mecanismo)**: además de los argumentos,
el dict que se pasa a
`create_confirmation_token` y a `validate_confirmation_token` lleva una clave
reservada `_estado` con la huella canónica de lo que la vista previa describe:

| Tool | Huella |
|---|---|
| `sv_create_mount` | montaje por defecto actual (decide si el nuevo pasa a serlo) |
| `sv_update_mount` | el montaje actual sin secretos y el montaje por defecto |
| `sv_delete_mount` | el montaje actual sin secretos, el montaje por defecto y los slugs de los backups afectados |
| `sv_set_default_backup_mount` | montaje por defecto actual y uso del montaje pedido |

En la confirmación se vuelve a leer el estado y se recalcula; si no casa, la
validación del token falla («does not match this action») y la tool añade la
pista de pedir una vista previa nueva porque el argumento o el montaje
cambiaron. `_estado` no es un argumento de la firma, así que el inventario de
la 033 no lo ve; el comentario del inventario lo menciona.

**Por qué**: en `sv_update_mount` el cuerpo que se envía depende del estado
actual (fusión, R-4): sin la huella, una confirmación tras un cambio ajeno
enviaría algo distinto de lo previsualizado (principio IV: la vista previa no
miente). En borrar y en el montaje por defecto, los efectos anunciados
dependen del estado.

**Descartado**: guardar el cuerpo fundido como omitible (escribiría en disco la
configuración y, con credenciales, las credenciales); no atar el estado (la
vista previa podría describir otra cosa); una comprobación aparte con un error
propio `state_changed` (necesitaría guardar la huella junto al token: la hay
en el hash y basta).

## R-7 — Sin confirmación: recargar un montaje, `days_until_stale`, recargar backups

**Decisión**: `sv_reload_mount`, `sv_set_backup_settings` y
`sv_reload_backups` se ejecutan en una llamada, sin token. Anotaciones: ni de
solo lectura ni destructivas, idempotentes, sin mundo abierto.

**Por qué**: FR-066 de la 008 pide confirmación solo en crear, editar, borrar y
el montaje por defecto. Recargar un montaje no desmonta nada sano
(`repair_trigger`); releer backups no cambia ficheros; `days_until_stale` solo
cambia cuándo avisa el centro de resolución y se deshace con otra llamada.
Ninguna borra datos, interrumpe un servicio ni toca secretos (principio IV).

**Descartado**: pedir token también aquí (fricción sin protección: el
invariante de `test_tools_registration.py` obligaría a anunciarlas
destructivas, que sería mentir).

## R-8 — Qué son «los ajustes de backup»

**Decisión**: `sv_get_backup_settings` = `days_until_stale` (`/backups/info`)
+ `default_backup_mount` y los montajes de uso `backup` con su estado
(`/mounts`). `sv_set_backup_settings(days_until_stale)` = `/backups/options`.
El montaje por defecto se cambia con su propia tool, que confirma.

**Por qué**: en el Supervisor 2026.11.0 `/backups/options` solo tiene
`days_until_stale`; quien pregunta «a dónde van mis backups y cuándo se
consideran viejos» necesita las tres cosas juntas. No se repite la lista de
backups (`sv_list_backups` ya la da, con su recorte).

**Descartado**: devolver `/backups/info` tal cual (repite la lista de backups,
sin tope propio); meter `default_backup_mount` en `sv_set_backup_settings`
(mezclaría una acción sin confirmación con una que la pide).

## R-9 — `location` en `sv_create_backup_*`

**Decisión**: argumento opcional `location: str | list[str] | None = None`.
Cada valor es `.local` o un nombre `^[A-Za-z0-9_]{1,64}$`; lista no vacía y
sin repetidos; `.cloud_backup` → `invalid_argument` con el motivo. Sin
`location` (o `None`), la carga no lleva la clave: idéntica a la 1.1.2. No se
comprueba de antemano que el montaje exista y sea de backup: lo comprueba el
Supervisor y su error vuelve redactado (una lectura previa sería otra llamada
y otra carrera).

**Por qué**: FR-066 y el research CAP-083 de la 008; `.cloud_backup` es una
ubicación interna de Home Assistant que el Supervisor rechaza a un add-on, y
decirlo antes evita un error opaco. FR-020 de la 008: argumento nuevo
opcional con el comportamiento de la 1.1.2 por defecto. La instantánea de
esquemas (`tests/fixtures/esquemas_1_1_2.json`) gana esta diferencia anotada,
como `search` en `hermes_guide`.

**Descartado**: `location` en `sv_create_safety_backup` (los safety backups
van al sitio por defecto, que ya se elige con `sv_set_default_backup_mount`; y
la 031 los toca por el cifrado) y en `sv_restore_backup_*` (fuera de CAP-083).

## R-10 — Lo que se registra en el log

**Decisión**: eventos `sv_<tool>_preview`, `sv_<tool>_ok`, `sv_<tool>_error`
con `mount` (nombre), `type`, `usage`, `changed` (nombres de campos),
`credentials` (el estado, no el valor) y, en los errores, el tipo de error.
Nunca `server`, `share`, `path`, `username`, `password` ni el texto del error
del Supervisor.

**Por qué**: el servidor y el recurso son datos de la red de casa (principio
VIII y la redacción de red de la 009 no conoce nombres de NAS); el texto de un
error del Supervisor puede repetir valores.

## R-11 — Pruebas: simulado y matriz

**Decisión**: tests unitarios con `DummyMCP` y un `MockHAClient` que registra
método, ruta y carga y devuelve respuestas con la forma del Supervisor
2026.11.0 (el de `tests/test_tools_supervisor.py`, ampliado), un fichero de
fixtures `tests/fixtures/supervisor_montajes.py` y `capture_logs`. Para el
fichero del token, `CONFIRMATIONS_DIR` en una carpeta temporal y una búsqueda
de los centinelas en todo su contenido. Las 7 tools que modifican van a la
matriz de la 014 como `VM` / `pendiente` con su línea en el procedimiento.

**Por qué**: decisión 2 de la 008 y FR-016: el Supervisor del banco de Core es
simulado y solo reenvía a Core; lo real es la VM de la 014.

## R-12 — Tramos

**Decisión**: dos tramos, como dice la 008 (M, 2 tramos):

1. **Montajes** (6 tools, familia y módulo `mounts`, 6 entradas, secretos,
   token con huella, inventario de la 033, matriz y procedimiento de las 5 que
   modifican, guía de montajes).
2. **Ajustes de backup y `location`** (3 tools del módulo `backup_settings`, 3
   entradas, `location`, instantánea de esquemas, matriz y procedimiento de
   las 2 que modifican, guía completa, toda la documentación y la fila de la
   008).

**Por qué**: el tramo 1 concentra el riesgo (secretos y confirmación) y es la
historia P1; el tramo 2 es pequeño y cierra la documentación. Cada tramo cabe
en el contexto de un agente (6 y 3 tools).
