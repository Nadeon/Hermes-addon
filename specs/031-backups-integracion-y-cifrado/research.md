# Research: backups de la integración `backup` y safety backups cifrados (031)

Decisiones de diseño, con lo que se comprobó en el código de Home Assistant Core
2026.11.1 y del Supervisor 2026.11.0 (carpeta `fuentes`, solo leída) y en el de
Hermes en la punta de `feat/cobertura-total` (`8a101b7`).

## R-1 — Las ocho tools y por qué así

**Decisión**: ocho tools, una por comando de la integración que la 011 dejó
pendiente de la 031:

| Comando | Tool | Modifica | Confirma |
|---|---|---|---|
| `backup/agents/info` | `ha_list_backup_agents` | no | no |
| `backup/config/update` | `ha_update_backup_config` | sí | sí |
| `hassio/update/config/info` | `ha_get_update_backup_settings` | no | no |
| `hassio/update/config/update` | `ha_set_update_backup_settings` | sí | sí |
| `backup/generate` | `ha_create_backup` | sí | sí |
| `backup/generate_with_automatic_settings` | `ha_create_automatic_backup` | sí | sí |
| `backup/restore` | `ha_restore_backup` | sí | sí |
| `backup/delete` | `ha_delete_backup` | sí | sí |

**Por qué**:

- Research CAP-057 de la 008 nombraba cinco (`ha_list_backup_agents`,
  `ha_update_backup_config`, `ha_get_update_backup_settings`,
  `ha_set_update_backup_settings`, `ha_create_backup`). La 011 añadió
  después el compromiso de restaurar y borrar (sus entradas de la tabla dicen
  «pendiente de tool dedicada (spec 031)»), y `backup/generate_with_automatic_settings`
  también lleva la 031 en su motivo. El tamaño estimado de la 008 (~3 tools,
  2 tramos) se queda corto: ver R-15.
- **Dos tools para crear**: `backup/generate_with_automatic_settings` llama a
  `async_initiate_backup(..., with_automatic_settings=True)` y, al terminar,
  HA aplica `delete_backups_exceeding_configured_count`: **borra** backups
  automáticos. `backup/generate` no borra nada. Una sola tool con un modo
  tendría que anunciarse destructiva también cuando no lo es, o no anunciarse
  cuando sí (principio V). Con dos, cada una dice lo suyo.
- **Crear pide confirmación**: FR-067 de la 008 («crear un backup eligiendo
  agentes, con confirmación») y research CAP-057 («2P: sí»). El motivo de
  fondo: un agente remoto recibe una copia completa de la casa (con
  `secrets.yaml`, tokens de integraciones y datos de apps), sin cifrar si el
  agente tiene `protected: false` o se pide `encrypt: false`. Las
  `sv_create_backup_*` de la 1.1.2 no confirman porque solo escriben en el
  disco local (y, con la 019, en un montaje elegido); no se cambian.
- **Anotaciones** (`tools/_annotations.py`): el invariante de la 1.1.2
  (`test_every_tool_that_asks_for_a_token_says_it_is_destructive`) obliga a
  que toda tool con token sea `destructiveHint`. `ha_create_*` ya es no
  idempotente por prefijo. Mundo abierto: HA sube a la nube o a otro equipo al
  crear con un agente remoto, descarga de él al restaurar (`async_receive_backup`
  en `hassio/backup.py`) y le pide borrar; Hermes lo provoca aunque no salga él
  (mismo criterio que `ha_marketplace_list_releases` y `ha_get_system_health`).
  `ha_update_backup_config` no sale (guarda en `.storage`).
- **Nombres**: `ha_get_update_backup_settings`/`ha_set_update_backup_settings`
  son los de research CAP-057; `ha_update_update_backup_settings` sería
  ilegible y `ha_set_` ya existe (`ha_set_input_*`).
- **`ha_create_backup` no acepta contraseña**: `encrypt` (por defecto `true`)
  cifra con la clave de HA (R-3). Así ninguna contraseña viaja por el cliente
  para crear y el backup se descifra con el kit de emergencia del usuario. Si
  HA no tiene clave, `no_encryption_key`: crear un backup sin cifrar tiene que
  pedirse con `encrypt: false`, explícitamente.

**Alternativas descartadas**: una tool `ha_manage_backup` con acción
(`create|restore|delete`): una sola anotación para tres riesgos distintos y
vistas previas mezcladas. Seguir con `ha_call_service` + `backup.create`:
crea siempre en el agente local con un contenido fijo y en HA OS ni existe la
acción (`backup/services.py` solo la registra sin Supervisor).

## R-2 — Familia y módulos

**Decisión**: una familia nueva `backup_integration` (`desde="1.2.0"`,
desactivable): «Home Assistant backup integration: agents, automatic backup
settings, backups before updates, create, restore and delete». Tres módulos:
`ha_backup_settings` (agentes, configuración y ajustes previos a actualizar),
`ha_backup_actions` (crear, crear con ajustes automáticos y borrar) y
`ha_backup_restore` (restaurar).

**Por qué**: FR-010 de la 008 (las tools nuevas en familias nuevas, para que
desactivarlas deje la 1.1.2 intacta). Las lecturas de la 1.1.2
(`ha_list_backups`, `ha_get_backup`, `ha_get_backup_config`) siguen en
`backups` (módulo `ha_backups`). Tres módulos para que cada tramo toque el
suyo y ninguno crezca de más; restaurar va aparte porque su vista previa es la
más larga del programa. El nombre `backup_settings` ya lo usa la 019 para los
ajustes del Supervisor: por eso el prefijo `ha_`.

## R-3 — De dónde sale la contraseña de los safety backups

**Hechos**:

- Un safety backup es un backup COMPLETO del Supervisor (`/backups/new/full`):
  `secrets.yaml`, `.storage` (tokens de integraciones), los datos de todas las
  apps (también el `/data` de Hermes) y la base de datos.
- Hoy (1.1.2) se crean **sin contraseña** (`tools/backups.py`,
  `_crear_safety_backup`; `fs_write.py`, `_maybe_trigger_safety_backup`).
- HA 2025.1+ tiene una clave de cifrado de backups (`create_backup.password`
  de `backup/config/info`) que la interfaz genera al configurar los backups
  automáticos y entrega como «kit de emergencia». HA la usa para sus backups y
  para descifrar al restaurar desde la interfaz. Hermes ya la recibe al leer
  `backup/config/info` y la descarta (`_config_permitida`, `password_set`).
- Un backup del Supervisor con `password` queda `protected: true`; para
  restaurarlo hace falta la misma contraseña (`/backups/{slug}/restore/*`
  con `password`; si no cuadra, «Invalid password for backup»).

**Opciones**:

| Opción | Restaurar sin Hermes | Secretos nuevos que custodiar | Riesgo |
|---|---|---|---|
| A. Contraseña generada por Hermes en `/data` (research de la 008) | **No**: solo Hermes la conoce y no la devuelve nunca | uno, en `/data` | La clave viaja **dentro** del propio backup que cifra (el `/data` de Hermes entra en el backup completo). Si Hermes está roto —justo cuando se restaura un safety backup— el usuario no puede abrirlo desde la interfaz ni la CLI |
| B. **Clave de cifrado de HA** | **Sí**, con el kit de emergencia | ninguno | Si el usuario cambia la clave, los anteriores se abren con la anterior (igual que los backups de HA) |
| C. Opción del add-on (`password`) | Sí, si el usuario la recuerda | uno, en las opciones del add-on | Otro secreto que el usuario puede perder; viaja en `options.json` y en cada backup de Hermes |

**Decisión**: **B**. Hermes lee la clave de HA cuando va a crear (o restaurar)
un backup, la manda al Supervisor y la descarta. No la escribe nunca: ni en
`last_safety_backup.json`, ni en `safety_backups.json`, ni en
`pending_jobs.json`, ni en un token, ni en el log; no la guarda en memoria
entre llamadas (cada uso la vuelve a leer, así un cambio de clave en HA se
respeta en el siguiente backup).

**Desviación de la 008**: FR-068 dice «contraseña generada, guardada en el
almacenamiento del add-on». Su intención —cifrados, la contraseña nunca
devuelta ni registrada, y que la restauración siga funcionando— se cumple
mejor con B; con A, «la restauración sigue funcionando» solo si Hermes
funciona. Queda como **duda D-031-1** para el mantenedor.

## R-4 — Sin clave: la opción `safety_backup_encryption`

**Hechos**: la clave puede faltar porque el usuario nunca configuró los backups
automáticos (`create_backup.password` es `None`), porque HA es anterior a 2025.1
(`unknown_command`), o porque Core no responde (un safety backup se puede
disparar con Core caído: escribir en `/config` para arreglarlo es un caso de
uso real, y el Supervisor hace el backup sin Core).

**Decisión**: opción `safety_backup_encryption`, `list(auto|required|off)`,
por defecto `auto`:

- `auto`: con clave, cifrado; sin clave, el backup se crea sin cifrar, la
  respuesta de `sv_create_safety_backup` lo dice (`encrypted: false`,
  `encryption_skipped_reason`: `no_key_configured`,
  `backup_integration_unavailable` o `ha_unreachable`) y el log avisa (sin
  valores). Es el valor por defecto porque un safety backup sin cifrar es
  mejor que ninguno y porque bloquear las escrituras de quien no configuró los
  backups de HA rompería a quien hoy usa `safety_backup_enabled`.
- `required`: sin clave no hay safety backup. La tool responde
  `encryption_key_unavailable` con el motivo; el disparo automático devuelve
  ese error y la escritura no se hace (fail-closed, como cualquier fallo del
  safety backup).
- `off`: como en la 1.1.2.

**Restaurar**: `sv_restore_backup_full`, `sv_restore_backup_partial` y
`ha_restore_backup`, sin `password` y con el backup `protected`, usan la clave
de HA. La vista previa dice `password_source`. Hoy ese caso falla en el
Supervisor por falta de contraseña, así que el cambio no rompe nada que
funcione (FR-020 de la 008). Sin clave en HA, la vista previa dice
`backup_encryption_key_unavailable` y la confirmación seguirá fallando como
hoy, con un error que lo explica. Si el Supervisor responde «Invalid password
for backup», el error añade que el backup puede estar cifrado con una clave
anterior y que se pase `password`.

## R-5 — La retención de los safety backups cifrados

**Hecho**: `safety_retention._motivo_exclusion` excluye todo backup
`protected` (`"protected"`). Con R-3, todos los safety backups nuevos lo son:
sin cambio, la retención no borraría ninguno y los backups completos volverían
a llenar el disco (el problema que `safety_backup_keep` resolvió en la 1.1.0).

**Decisión**: `record_launch` acepta `encrypted: bool` y la entrada lo guarda.
`_motivo_exclusion` admite `protected: true` solo si la entrada dice
`encrypted: true`; con `encrypted` ausente o falso, la regla es la de hoy. Así
un backup que el usuario protegió (o uno de una versión anterior) sigue
intocable, y uno que Hermes cifró se poda como antes. Control negativo: sin el
cambio, el test de la poda de cifrados cae.

## R-6 — Restaurar: qué hace HA y cómo se responde

**Hechos** (`backup/websocket.py` `handle_restore`, `manager.py`
`async_restore_backup`, `hassio/backup.py`, `backup/manager.py`
`CoreBackupReaderWriter.async_restore_backup`):

- Argumentos: `backup_id`, `agent_id` (obligatorio), `password`,
  `restore_addons`, `restore_database` (por defecto `true`),
  `restore_folders`, `restore_homeassistant` (por defecto `true`).
- El comando **no responde hasta terminar**. Con Supervisor, HA pide al
  Supervisor una restauración parcial en segundo plano y espera a su job; si la
  configuración de Core se restaura, Core se reinicia y la conexión cae. Sin
  Supervisor, HA comprueba la contraseña, escribe `.HA_RESTORE` y llama a
  `homeassistant.restart`.
- Errores tempranos: `backup_not_found`, `password_incorrect` («Invalid
  password for backup» del Supervisor, que valida antes de lanzar el job;
  `validate_password` en Core), «Restore database must match backup» (con
  Supervisor, si `restore_homeassistant` y `restore_database` no coinciden con
  `database_included`), «Cannot restore database without Home Assistant»,
  «Addons and folders are not supported in core restore» (sin Supervisor), y
  `Backup manager busy`.
- Un agente que no es `hassio.*` (nube, otro equipo): HA descarga el backup
  al Supervisor antes de restaurar.

**Decisión**:

- Comprobaciones previas en la vista previa (sin token si fallan):
  `restore_database` por defecto igual a `database_included`; con Supervisor
  (agente `hassio.local` presente), distinto con `restore_homeassistant: true`
  → `invalid_argument` (en Core sin Supervisor HA sí permite restaurar la
  configuración sin la base de datos, y no se le quita esa opción); `restore_database: true`
  con `restore_homeassistant: false` → `invalid_argument`; apps o carpetas que
  no están en el backup → `not_in_backup`; nada que restaurar →
  `invalid_argument`; apps o carpetas sin agente `hassio.local` presente
  (instalación sin Supervisor) → `invalid_argument` con el motivo de HA.
- Al confirmar, `ws_send` con un plazo de 30 s. Error de HA → error (token
  fallido). Respuesta → `{"result": "completed"}`. Sin respuesta en el plazo o
  conexión caída **después** de enviar → `{"status": "restore_started", ...}`
  con cómo comprobarlo (`ha_list_backups`: `state` y `last_action_event`;
  `sv_list_pending_jobs`), y el token se completa con ese resultado (no se
  reintenta solo). Orden no enviada (WebSocket caído antes) → error y token
  fallido.
- Distinguir «enviado» de «no enviado» necesita una señal del cliente:
  `HAConnectionError` lleva hoy un mensaje distinto («WebSocket no
  disponible…» antes de enviar; «Timeout waiting…» después). Se añade un
  atributo `sent: bool` (aditivo; por defecto `False`) que `ws_send` pone a
  `True` en los errores posteriores al envío, en vez de comparar textos.

## R-7 — Borrar: todas las ubicaciones

**Hechos**: `backup/delete` solo recibe `backup_id` y llama a
`async_delete_backup(backup_id)` con `agent_ids=None`: borra en **todos** los
agentes. Devuelve `agent_errors` por agente; un `BackupNotFound` de un agente
no es error. Si no hubo errores, quita el id de `known_backups`.

**Decisión**: la vista previa lee `backup/details` y dice que se borra de
todas sus ubicaciones, listándolas. Avisa si es el único backup con
`homeassistant_included` (leyendo `backup/info`). Dice si es un safety backup
de Hermes (el id está confirmado en `safety_backups.json`). El token ata el id
y la huella `{date, name, agentes ordenados con tamaño y protección}`. La
respuesta separa `deleted_from` y `failed` (errores enmascarados con
`_mascara_red` y `redact_secrets`, como en `ha_list_backups`).

## R-8 — Qué ata el token

- Argumentos: todos, como siempre (`create_confirmation_token`). En
  `ha_restore_backup` y `sv_restore_backup_*`, `password` incluido: desde la
  019 el `action_hash` es HMAC-SHA256 con una clave aleatoria en memoria, así
  que lo que queda en el fichero del token no permite atacar la contraseña sin
  conexión. **Dependencia**: el tramo que lo usa (3) no empieza sin la 019
  integrada. La clave de HA no es un argumento y no entra.
- Estado (`estado=` de la 018):
  - restaurar: el backup en el agente elegido (`date`, `name`,
    `homeassistant_version`, `database_included`, `homeassistant_included`,
    apps con versión, carpetas, `protected` y `size` en ese agente) y la
    fuente de la contraseña;
  - borrar: R-7;
  - configuración: la configuración actual por lista blanca (con
    `password_set`, nunca la contraseña) y los ids de la estimación de R-9;
  - ajustes previos a actualizar: los tres valores actuales;
  - crear: los agentes disponibles y si hay clave;
  - crear con ajustes automáticos: la configuración automática (sin
    contraseña) y los ids de la estimación.

## R-9 — Estimación de la retención

**Hechos** (`backup/config.py`): solo se borran backups con
`with_automatic_settings` (`async_delete_filtered_backups` con
`include_filter`). Por copias (`delete_backups_exceeding_configured_count`):
tras cada backup automático, por agente si alguno tiene retención propia; si
no, global, ordenando por fecha y quitando los más antiguos que pasen de
`copies`. Por días (`RetentionConfig.apply` → `_schedule_next`): se programa un
borrado a 1 día y se repite; borra los más antiguos que `days`, por agente si
hay retención por agente. Un agente con retención propia ignora la global; con
`copies` y `days` a `None`, conserva todo.

**Decisión**: una función pura `estimar_retencion(config, backups, ahora)` que
reproduce esas reglas y devuelve `[{backup_id, name, date, agents, when}]` con
`when` en `within_24h` (días) o `after_next_automatic_backup` (copias: con la
configuración nueva, de los backups automáticos actuales, los que quedarían
fuera al sumar uno nuevo). La vista previa la presenta como `estimate` con una
frase que dice de qué depende. Tests con los casos de HA (global, por agente,
copias y días, `None`); en el banco, el backup que HA borra de verdad.

## R-10 — `ha_update_backup_config`

**Hechos**: `backup/config/update` acepta `agents` (`{agent_id: {protected,
retention}}`), `automatic_backups_configured`, `create_backup` (`agent_ids`,
`include_addons`, `include_all_addons`, `include_database`, `include_folders`,
`name`, `password`), `retention` (`copies`, `days`: enteros ≥ 1 o `None`) y
`schedule` (`days` de `mon`…`sun`, `recurrence` `never|daily|custom_days`,
`time` `HH:MM[:SS]` o `None`). HA funde: `create_backup` con `replace`, cada
agente por separado, y aplica la retención o la programación si cambian.

**Ojo**: `schedule` y `retention` HA los **sustituye** (`BackupSchedule(**schedule)`,
`RetentionConfig(**retention)`): lo no pasado vuelve al valor por defecto. Un
`{"schedule": {"time": "04:30"}}` dejaría `recurrence: never` y apagaría los
backups automáticos sin que nadie lo pidiera.

**Decisión**: argumentos `schedule`, `retention`, `agents`, `create_backup` y
`automatic_backups_configured`, todos opcionales, con la forma de HA; Hermes
completa `schedule`, `retention` y la `retention` de cada agente con los
valores actuales de lo no pasado y manda el documento completo (un `null`
explícito sí se manda), para que editar un campo no cambie los demás
(documentos pequeños y conocidos; los sueltos de la 019 tenían sentido por la
contraseña CIFS, que aquí no entra). Al menos uno. Hermes valida claves y
valores (claves desconocidas → `invalid_argument` con su nombre; `password`
→ `invalid_argument` «la clave de cifrado se cambia en la interfaz de HA», sin
repetir el valor). Cambiar la clave queda fuera (lo hace la interfaz con el kit
de emergencia; una clave que el usuario no conoce dejaría sus backups futuros
sin poder abrir). Avisos de la vista previa: `protected: false` en un agente;
`recurrence: never`; `create_backup.agent_ids` con agentes que no existen o
vacío; `include_database: false`.

## R-11 — `hassio/update/config/*`

**Hechos**: solo existen con la integración `hassio` (Core con Supervisor).
`info` devuelve `add_on_backup_before_update`, `add_on_backup_retain_copies` y
`core_backup_before_update`; `update` acepta esos tres
(`add_on_backup_retain_copies` ≥ 1) y los funde en las opciones de la config
entry de `hassio`. `add_on_backup_retain_copies` lo usa
`hassio/backup.py` al actualizar una app: borra los backups de actualización
de esa app que pasen de ese número.

**Decisión**: dos tools; `unknown_command` → `supervisor_integration_unavailable`.
La vista previa de `set` avisa al bajar `add_on_backup_retain_copies`. No se
pueden ejecutar en el banco (Core sin Supervisor): van a la lista de no
ejecutables con ese motivo; la matriz de la 014, VM pendiente.

## R-12 — Banco de Core

**Hechos**: el banco es Core 2026.11.1 sin Supervisor; `backup:` no está en su
configuración (no hay `default_config:`). Con `backup:`, HA registra el agente
`backup.local` (`/config/backups`), todos los comandos de `backup/*` salvo
`backup/start|end`, y crea backups de verdad (un tar del `/config` del banco,
pequeño). Restaurar escribe `.HA_RESTORE` y reinicia Core: el banco no lo
sobrevive (tests de la 028: «Nunca `homeassistant.restart`»). Con una
contraseña incorrecta, `validate_password` falla **antes** de escribir nada y
de reiniciar.

**Decisión**: `backup:` en `tests/banco/ha_config/configuration.yaml` con
comentario. `tests/banco/cobertura_031.py` con `PROBADAS_031` (solo las que
modifican: `ha_update_backup_config`, `ha_create_backup`,
`ha_create_automatic_backup`, `ha_delete_backup`; el invariante de la 028 no
admite lecturas en esa unión) y `NO_EJECUTABLES_031` (`ha_restore_backup`:
reinicia Core; `ha_set_update_backup_settings`: necesita `hassio`), sumados a
la unión del invariante; y `LECTURAS_EN_BANCO_031`
(`ha_list_backup_agents`), que, como `PROBADAS_EN_BANCO_029`, solo se suma a
`TOOLS_EXIGIDAS_DEL_JOB` para que el job la exija por ejecución. La lectura de la clave se prueba con el módulo de
R-3 contra HA real tras fijar una clave centinela con el lector
(`backup/config/update` directo, que la tool no permite). `ha_get_update_backup_settings`
es de lectura y no entra en el inventario de escrituras; su
`supervisor_integration_unavailable` se comprueba en el banco.

## R-13 — La tabla y el generador

**Hechos**: `scripts/inventario/generar_tabla.py`, `_DEDICADAS_INICIALES`,
tiene `backup/delete → sv_delete_backup`, `backup/restore →
sv_restore_backup_full` y `backup/generate*` → `ha_call_service` (la clase del
inventario es `cubierto`); la tabla revisada a mano los tiene en `deny`. Las
filas `backup/agents/info`, `backup/config/update` y `hassio/update/config/*`
son clase A de CAP-057: desde la 029, una clave en `_DEDICADAS_INICIALES` las
lleva a `dedicated` antes de la regla «pendiente».

**Decisión**: las ocho claves en `_DEDICADAS_INICIALES` hacia las tools nuevas
(bloque «031»); en `command_table.py`, las ocho entradas
`E("dedicated", "cubierto por <tool>", "backup_integration", tool=…,
cap="CAP-057")`, quitando los comentarios de «hasta la tool dedicada de la
031». Regenerar sobre la tabla editada: 0 nuevas, 0 quitadas, idéntica; desde
cero, las ocho salen iguales. La `cap` sale del inventario: las cuatro filas
de clase A llevan `CAP-057`; las cuatro de clase `cubierto`
(`backup/delete`, `backup/restore`, `backup/generate*`) no tienen CAP en
`core-ws.tsv` y su entrada va **sin** `cap`, como `backup/config/info` hoy. Así
la generación desde cero coincide. Pero `dedicada()` añade « (acción de HA)»
al motivo cuando la fila es `accion-generica` (las dos de `backup/generate*`), y
`backup/delete`/`backup/restore` son `si-equivalente` con una nota que nombra
las `sv_*`: con tools dedicadas eso ya no es verdad. En esas cuatro filas de
`specs/008-cobertura-total/inventario/core-ws.tsv` la columna de cobertura pasa
a `si` y la nota nombra la tool nueva (como hizo la 012 con las suyas); la
entrada generada es entonces `cubierto por <tool>`, sin sufijo.

## R-14 — Seguir un backup: `last_action_event`

**Hechos**: `backup/generate` devuelve `{"backup_job_id": …}` en cuanto empieza.
`backup/info` da `state` (`idle`, `create_backup`, `restore_backup`…) y
`last_action_event` (`manager_state`, `state`, `stage`, `reason`, y en
subidas `agent_id`, `uploaded_bytes`, `total_bytes`). `ha_list_backups` ya
devuelve `state` pero no `last_action_event`.

**Decisión**: `ha_list_backups` añade `last_action_event` por lista blanca
(`manager_state`, `state`, `stage`, `reason`; escalares). Aditivo (FR-020 de
la 008). `ha_create_backup` responde `backup_job_id` y `follow_with`.

## R-15 — Tramos

La 008 estima la 031 en M y 2 tramos con ~3 tools. Con el compromiso de la 011
(restaurar y borrar con vista previa fuerte) y el cifrado, son ocho tools, un
módulo de clave, una opción del add-on y cambios en la retención y en las
`sv_restore_*`. Se parte en **cuatro** tramos para que ninguno llene el
contexto de un agente: 1 ajustes (cuatro tools y la estimación de la
retención), 2 crear y borrar (tres, el módulo de la clave y
`last_action_event`), 3 restaurar (una, la de la vista previa más larga, y las
`sv_restore_*` con la clave), 4 safety backups cifrados y cierre. Desviación
anotada (D-031-2).
