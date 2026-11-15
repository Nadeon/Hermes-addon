# Research: escritura en el Marketplace (026)

Todo lo de aquí está leído en el código de HA Core 2026.11.1
(`homeassistant/components/marketplace/`) y del Supervisor 2026.11.0, y en el
código de Hermes de la punta `f108af0` de `feat/cobertura-total` (314 tools).
Línea base de la suite en Windows sobre esa punta: 3955 passed, 133 skipped,
6 failed (los 6 conocidos).

## R-1 — Dónde vive el Marketplace y qué comandos usa

**Decisión**: el Marketplace de 2026.11 es una **integración de Core**:
`homeassistant/components/marketplace/`. Está en `DEFAULT_INTEGRATIONS` de
`homeassistant/bootstrap.py` («set up unless recovery mode is activated»), y
su `async_setup` registra los comandos WS siempre y crea la entrada de
configuración con un flujo `system` (sin cuenta de GitHub) si no existe. Los
comandos se registran aunque la entrada no cargue: entonces responden
`not_loaded` (`websocket/decorators.py`, `marketplace_command`).

Comandos de escritura (los 10 «pendiente (spec 026)» de la tabla; todos en
`fuentes/core` y en `inventario/core-ws.tsv`, clase A, CAP-075):

| Comando | Fichero | Carga | Exige aviso | Exige GitHub | Sale a GitHub |
|---|---|---|---|---|---|
| `marketplace/repository/install` | `websocket/repository.py` | `repository`, `version?` (`valid_ref`), `confirm_replace_built_in?` | sí | no | sí (descarga) |
| `marketplace/repository/uninstall` | idem | `repository` | no | no | solo si GitHub conectado |
| `marketplace/repository/version` | idem | `repository`, `version` | sí | no | sí |
| `marketplace/repository/beta` | idem | `repository`, `show_beta` | sí | no | sí |
| `marketplace/repository/ignore` | idem | `repository` | no | no | no |
| `marketplace/repository/refresh` | idem | `repository` | no | no | sí |
| `marketplace/repositories/add` | `websocket/repositories.py` | `repository`, `category` | sí | sí | sí |
| `marketplace/repositories/remove` | idem | `repository` | no | no | no |
| `marketplace/repositories/detect` | idem | `repository` | sí | sí | sí (solo lee) |
| `marketplace/critical/acknowledge` | `websocket/critical.py` | `repository` (`full_name`) | no (sin decorador) | no | no |

`repository` es el **id** del repositorio salvo en `critical/acknowledge`
(el `full_name`) y en `repositories/add|detect` (URL o `owner/repo`). Todos
llevan `require_admin`.

Lecturas que usan las vistas previas, ya `dedicated` en la tabla por las tools
de la 004 o de otras familias: `marketplace/info`,
`marketplace/repositories/list` (por categoría), `marketplace/repositories/removed`,
`marketplace/critical/list`, `marketplace/repository/releases`,
`manifest/get` (029) y `config_entries/get` (1.1.2).

Ninguno empieza por `hassio/` ni `supervisor/`
(`DENIED_WS_TYPE_PREFIXES` de `supervisor/api/proxy.py`): el proxy los deja
pasar.

**HACS**: en HA ≤ 2026.10 el Marketplace era HACS 2.x, una integración
**externa**: sus comandos de escritura (`hacs/repository/download`, etc.) no
están en `fuentes/core` ni en el inventario y no se pueden comprobar. Las
tools nuevas **no** caen a `hacs/*`: con `unknown_command` responden
`marketplace_write_unsupported`. Es lo que Hermes ya hace de forma segura: la
lectura cae a HACS por compatibilidad (004), la escritura no se inventa.

**Alternativas descartadas**: escribir también con HACS (comandos no
verificables, semántica distinta, HA ≤ 2026.10 deja de ser la referencia).

## R-2 — HALLAZGO: el aviso de riesgos es por usuario, y el de Hermes es el del Supervisor

`marketplace_command(requires_accepted_warning=True)` comprueba
`marketplace.warning_accepted(connection.user.id)`
(`websocket/decorators.py`; `base.py`, `warning_acceptances` guarda la
aceptación por `user_id` en los datos de la entrada). Lo exigen `install`,
`version`, `beta`, `repositories/detect` y `repositories/add`; los dos
últimos exigen además `github_connected` (token de GitHub de la entrada,
global).

Hermes se conecta a Core por el proxy WS del Supervisor
(`ha.py`: `ws://supervisor/core/api/websocket` con `SUPERVISOR_TOKEN`); el
proxy autentica a la app y abre la conexión con Core con el token del propio
Supervisor (`supervisor/api/proxy.py`). Para Core, `connection.user` es el
**usuario del Supervisor** (usuario de sistema, administrador). Nadie inicia
sesión con él en la interfaz, así que **nadie puede aceptar el aviso en su
nombre**; solo lo aceptaría `marketplace/warning/accept` enviado por esa misma
conexión, que FR-091 prohíbe (clase D). La entidad `update` tampoco ayuda: su
`async_install` usa el `user_id` del contexto, que con Hermes es el mismo
usuario (`update.py`); solo una automatización sin usuario se conforma con que
alguien lo haya aceptado, y usar eso para saltarse el aviso sería engañar a
HA. La 004 ya lo anotó como supuesto (S-08) para `update.install`.

Consecuencia: con HA 2026.11.1, `ha_marketplace_install`,
`ha_marketplace_set_version`, `ha_marketplace_set_beta` y
`ha_marketplace_add_repository` **fallarán siempre** desde Hermes con
`warning_not_accepted`, salvo que HA cambie (aviso global, o aceptación por
administrador) o que Hermes llegue a conectarse con otro usuario.
`ha_marketplace_uninstall`, `ha_marketplace_remove_repository`,
`ha_marketplace_refresh_repository`, `ha_marketplace_ignore_repository` y
`ha_marketplace_acknowledge_critical` **sí** funcionan.

**Decisión**: se construyen las nueve (FR-091 las pide y quedan listas para
cuando la condición se cumpla), con tres salvaguardas de honestidad:

1. La vista previa de las cuatro afectadas lee `marketplace/info` (la misma
   conexión, el mismo usuario) y, si `warning_accepted` no es `true`,
   responde `marketplace_warning_not_accepted` **sin token**, con un `detail`
   que explica la causa y la salida (la interfaz del Marketplace).
2. Sus descripciones lo dicen en la primera frase útil: «Requires the
   Marketplace risk warning to be accepted by the Home Assistant user Hermes
   connects as (the Supervisor user); Hermes never accepts it, so with Home
   Assistant 2026.11 this normally fails: install from the Marketplace UI».
3. Van en una familia propia (`marketplace_install`, salvo añadir) para que
   el mantenedor pueda apagarlas si decide que no compensan.

**Duda para el final D-1**: ¿se publican estas cuatro tools (forward
compatible, con el rechazo honesto) o se quitan y sus comandos quedan `deny`
con el motivo «exige el aviso aceptado por el usuario del Supervisor: decisión
humana imposible desde Hermes»? La spec elige publicarlas; quitarlas es borrar
un módulo y cambiar cinco entradas de la tabla.

**Alternativas descartadas**: aceptar el aviso con una opción del add-on
(prohibido por FR-091 y por la 008, clase D); instalar por una automatización
sin usuario (saltarse a sabiendas una salvaguarda de HA).

## R-3 — Nombres, familias y módulos

- Nombres con el prefijo de las tools de lectura (`ha_marketplace_`), que es
  como el agente busca lo del Marketplace, y verbo explícito:
  `ha_marketplace_install`, `ha_marketplace_uninstall`,
  `ha_marketplace_set_version`, `ha_marketplace_set_beta`,
  `ha_marketplace_add_repository`, `ha_marketplace_remove_repository`,
  `ha_marketplace_refresh_repository`, `ha_marketplace_ignore_repository`,
  `ha_marketplace_acknowledge_critical`. Respecto a research CAP-075 de la
  008: `refresh` e `ignore` llevan `_repository` (refrescar o ignorar ¿qué?), y
  se añade `set_beta` (R-4).
- Dos familias nuevas, desde 1.2.0 y desactivables, una por módulo y por
  tramo:
  - `marketplace_manage` (módulo `marketplace_manage`): catálogo y avisos.
  - `marketplace_install` (módulo `marketplace_install`): código instalado.
- Módulo común sin tools `tools/_marketplace_write.py`: guarda de comandos
  (lista cerrada de escritura), lectura del repositorio por id con la lista
  por categorías de `tools/marketplace.py`, comprobación del aviso,
  traducción de errores, evento de log, validación de argumentos y de la URL.
  Reutiliza de `tools/marketplace.py` `_list_catalog`, `_summaries`,
  `_third_party`, `_trim`, `_REPOSITORY_ID_RE` y `MARKETPLACE_CATEGORIES`
  (importados, sin moverlos: cambio mínimo) y de `tools/_store.py`
  `tapar_credenciales`, `credenciales_de_url`, `redactar_mensaje` y
  `tapar_en_estructura`.
- `tools/marketplace.py` **no** envía ningún comando nuevo: su lista cerrada
  (`_ALLOWED_SUFFIXES`) sigue siendo de lectura y `TestOnlyAllowedCommands`
  sigue valiendo. La lectura por categorías se llama con `_ws_read`, que sigue
  rechazando sufijos de escritura; la escritura usa su propia lista cerrada en
  `_marketplace_write.py` (`_WRITE_SUFFIXES`, los 9 de escritura más
  `repositories/detect`).

## R-4 — De comando a tool, y la tabla

| Comando | Tool | Motivo en la tabla |
|---|---|---|
| `marketplace/critical/acknowledge` | `ha_marketplace_acknowledge_critical` | cubierto por … |
| `marketplace/repository/ignore` | `ha_marketplace_ignore_repository` | cubierto por … |
| `marketplace/repositories/remove` | `ha_marketplace_remove_repository` | cubierto por … |
| `marketplace/repository/refresh` | `ha_marketplace_refresh_repository` | cubierto por … |
| `marketplace/repositories/add` | `ha_marketplace_add_repository` | cubierto por … |
| `marketplace/repositories/detect` | `ha_marketplace_add_repository` | `_ConMatiz`: «la usa su vista previa para saber las categorías» |
| `marketplace/repository/install` | `ha_marketplace_install` | cubierto por … |
| `marketplace/repository/uninstall` | `ha_marketplace_uninstall` | cubierto por … |
| `marketplace/repository/version` | `ha_marketplace_set_version` | cubierto por … |
| `marketplace/repository/beta` | `ha_marketplace_set_beta` | cubierto por … |

Familia de cada entrada: la de su tool (`marketplace_manage` o
`marketplace_install`), `cap="CAP-075"`. Se añaden a
`_DEDICADAS_INICIALES` del generador (regla de la 011: la generación desde
cero coincide con la tabla en todas las filas A dedicadas).

`beta` con tool propia y no `confirm` por la genérica: CAP-075 es de vía D, y
el generador solo produce `dedicated` o «pendiente» para sus filas A; dejarla
`confirm` exigiría una excepción en el generador y una vista previa genérica
que no sabe decir qué cambia. `detect` sin tool propia: solo lee (GitHub) y
solo sirve para añadir.

Siguen igual: `github/connect` y `warning/accept` (`deny`, clase D),
`repository/info`, `repositories/clear_new` y `subscribe` (`deny`, clase B),
y las cinco de lectura (`dedicated` a las tools de la 004).

## R-5 — Añadir un repositorio: validación, credenciales y lo que se envía

HA extrae el repositorio con `RE_REPOSITORY` (`utils/regex.py`):
`(?:(?:.*github.com.)|^)([A-Za-z0-9-]+\/[\w.-]+?)(?:(?:\.git)?|(?:[^\w.-].*)?)$`,
en minúsculas. Acepta cualquier cosa que termine en `github.com` y algo, y
descarta todo lo demás de la URL (esquema, credenciales, rama). El Marketplace
solo habla con GitHub con su propio token.

**Decisión**: Hermes es más estricto que HA y nunca envía credenciales:

- Admite `owner/repo` (`owner` `[A-Za-z0-9-]{1,39}`, `repo` `[\w.-]{1,100}`,
  sin empezar por `.`) o una URL `https://` cuyo servidor es exactamente
  `github.com` o `www.github.com`, con puerto vacío o numérico (lección de
  T034 de la 030), sin consulta ni fragmento, y cuya ruta es exactamente
  `/owner/repo` con `.git` o `/` final opcionales. Hasta 2048 caracteres.
  Espacios en los extremos se quitan; cualquier otra forma es
  `invalid_argument` con `field: "repository"` y un `detail` que no copia el
  valor.
- La parte de usuario (todo lo que va antes de `@`) se tapa entera con
  `tapar_credenciales` de `tools/_store.py`, como en la 030, en la vista
  previa, la respuesta, los errores y el log; la vista previa dice
  `credentials_hidden` y `credentials_sent: false`.
- A HA se envía solo `owner/repo` en minúsculas (forma que HA acepta por la
  rama `^` de su patrón): las credenciales no salen de Hermes.
- El token se ata a la **URL completa** tal como llegó (sin espacios en los
  extremos) y a la categoría: otra URL con el mismo `owner/repo` pide otra
  vista previa.

## R-6 — Backup previo

El Marketplace ya guarda los ficheros anteriores mientras instala y los
restaura si la instalación falla (`repositories/base.py`, `Backup`,
`restore_interrupted_backups`), pero no deja nada a lo que volver si la
instalación sale bien y lo instalado rompe Home Assistant.

**Decisión**: `backup: bool = True` en instalar y desinstalar (las únicas que
cambian ficheros de `/config`), atado al token. Al confirmar, Hermes envía
`POST /backups/new/partial` al Supervisor con
`{"name": "hermes_marketplace_<install|uninstall>_<AAAAMMDDTHHMMSSZ>",
"homeassistant": true, "homeassistant_exclude_database": true,
"background": false}` y la espera larga de `tools/addons.py`
(`_LONG_OP_TIMEOUT`). La base de datos queda fuera porque es lo que hace lento
un backup y no la toca el Marketplace. El nombre no lleva el repositorio (los
backups se listan en sitios que se comparten). Si el Supervisor responde error
o no termina en la espera, no se envía el comando a HA, el token se completa
como fallido y la respuesta da el `job_id` si lo hay. Con `backup=false`, la
vista previa lo dice con el aviso de que solo queda la copia temporal del
Marketplace.

`ha_marketplace_set_version`, `set_beta`, `refresh`, `ignore`,
`acknowledge_critical`, `add_repository` y `remove_repository` no cambian
ficheros (solo el storage del Marketplace o sus avisos): no hacen backup y la
vista previa lo dice (`backup: {"will_create": false, "reason": …}`). Lectura
de FR-091 («con backup previo»): se aplica a lo que cambia el código
instalado. Se anota como lectura, no como desviación.

**Alternativas descartadas**: el safety backup completo de Hermes
(`maybe_trigger_safety_backup`: varios GB y desactivado por defecto); backup
de la integración `backup` de Core (`backup/generate`, otra operación larga
con su propia configuración); no encadenar el backup como la D-2 de la 015
(FR-091 lo pide expresamente).

## R-7 — Reinicio y vista previa de instalar

- Integración (`repositories/integration.py`): tras instalar,
  `pending_restart` es verdadero si el `domain` ya estaba cargado o si la
  integración no tiene `config_flow`; si no, HA la encuentra sin reiniciar.
  Tras desinstalar, lo mismo con «cargada o sin `config_flow`». HA crea un
  aviso `restart_required` en Repairs. La vista previa dice
  `restart: {"likely": true|false, "reason": …}` con esa regla (el
  `config_flow` viene en el resumen del repositorio; «cargada» se sabe con
  `config_entries/get` del `domain` o porque ya estaba instalada) y, tras
  confirmar, `restart_required` sale del `status` releído
  (`pending-restart`). Hermes **no** reinicia: pista `sv_restart_core`.
- Tarjeta (`plugin.py`): registra o quita el recurso de Lovelace; solo pide
  reinicio si creó `www/` en esta sesión. `restart.likely: false` con la pista
  de recargar el navegador.
- Tema y plantilla: sin reinicio; tema, pista de `frontend.reload_themes`.
- `can_install` falso (HA más antigua que la que pide el repositorio):
  `cannot_install` con `homeassistant` del resumen.
- Versión: `version` opcional, validada como `valid_ref` de HA
  (`utils/validate.py`: no vacía, sin `?`, `#`, `%`, `\`, espacios ni
  segmentos que empiezan por `.`). Destino = `version` o `available_version`.
  `action`: `install` (no instalado), `reinstall` (destino = instalada),
  `change_version` (otra). Si se pide una versión distinta de
  `available_version`, la vista previa consulta `repository/releases` (sale a
  GitHub, ya lo hace `ha_marketplace_list_releases`) y dice
  `version_check: {checked, in_releases, prerelease}`; no rechaza porque HA
  admite ramas y commits.

## R-8 — Sustituir una integración de Home Assistant

`marketplace/repository/install` rechaza (`replaces_built_in`) una integración
cuyo `domain` tiene manifiesto en `homeassistant/components/` salvo con
`confirm_replace_built_in: true` (y lo recuerda para las actualizaciones). Lo
calcula `async_replaces_built_in`, que solo expone `repository/info` (clase
B: sale a GitHub y escribe en el storage). **Decisión**: la vista previa usa
`manifest/get` con el `domain` y mira `is_built_in` (si la personalizada ya
está instalada y cargada, `manifest/get` devuelve la personalizada: entonces
ya se confirmó en su día y HA no vuelve a pedirlo). Si HA responde que la
integración no existe (`not_found`: ni de HA ni personalizada cargada),
`replaces_built_in: false`. Sin `replace_built_in=true`
→ `replaces_built_in` sin token; con él, la vista previa lo destaca. Si
`manifest/get` falla, `replaces_built_in: null` y el token sale: HA vuelve a
comprobarlo y, si rechaza, se traduce el error.

## R-9 — Confirmación, anotaciones y estado atado

- Las nueve piden token (criterio del supervisor: todo lo que escribe).
  Ignorar y reconocer no tienen vuelta atrás por API en 2026.11.1; quitar y
  añadir cambian el catálogo; refrescar escribe en el storage y gasta el
  límite de GitHub. Invariante de la 1.1.2: lo que pide token va en
  `_DESTRUCTIVE_EXACT`.
- Idempotentes todas (repetir deja el mismo estado o da «ya hecho»).
  `openWorldHint` las que hacen que HA hable con GitHub: instalar,
  desinstalar (si GitHub está conectado), fijar versión, betas, refrescar y
  añadir.
- `estado` (018): instalar ata `full_name`, `category`, `installed_version`,
  `available_version`; desinstalar, `full_name`, `category`,
  `installed_version`; fijar versión y betas, `full_name`, `category`;
  quitar, `full_name`, `custom`, `installed`; ignorar, `full_name` y la
  entrada de retirados; reconocer, la entrada crítica; añadir, `owner/repo` y
  que no esté ya en la lista (la detección no se repite al confirmar: saldría
  otra vez a GitHub, y HA valida la categoría al añadir). Se relee al confirmar con
  `resolve_confirmation_token`; si no se puede leer, el token no vale.

## R-10 — Ignorar, quitar y reconocer: semántica

- Ignorar (`base.py`, `async_handle_removed_repositories`): un repositorio
  retirado del catálogo e ignorado no se quita de la lista ni genera el aviso
  `removed_<id>`, y sale de `repositories/removed`. No hay comando para
  quitarlo de `ignored_repositories`. Solo tiene sentido con un retirado: la
  vista previa exige que esté en `repositories/removed`
  (`repository_not_removed` si no) y que no sea `critical`
  (`critical_repository`: un crítico se desinstala solo y se reconoce).
- Quitar: HA rechaza el instalado (`repository_installed`); uno del catálogo
  por defecto volvería en la siguiente descarga: Hermes solo quita
  personalizados (`custom: true`).
- Reconocer: `async_acknowledge_critical_repository` marca `acknowledged` en
  el storage `marketplace.critical` y borra el aviso
  `critical_repository_<repo>` de Repairs; no usa el decorador (funciona aunque
  la entrada no cargue). La vista previa exige que esté en `critical/list` y
  sin reconocer.

## R-11 — Banco de pruebas

- El banco (010) arranca HA Core 2026.11.1 sin `default_config:`, pero
  `marketplace` está en `DEFAULT_INTEGRATIONS`: se carga igual. Sin internet,
  la entrada puede cargar (restaura un storage vacío) pero las tareas de
  arranque no descargan el catálogo, así que `repositories/list` vuelve vacío
  y no hay repositorio que instalar, desinstalar, fijar, refrescar, ignorar,
  quitar ni añadir (añadir exige además GitHub conectado y el aviso). Se
  comprueba en el tramo 1 con un test del banco que lee `marketplace/info`.
- `ha_marketplace_acknowledge_critical` sí se ejecuta: se siembra
  `tests/banco/ha_config/.storage/marketplace.critical` (formato `Store`
  versión 1, clave `marketplace.critical`, una entrada ficticia
  `ejemplo/tarjeta-critica` sin reconocer). La tarea de arranque crea su aviso
  en Repairs si la entrada carga; la de los críticos de la red falla sin
  internet y no toca el storage (`async_handle_critical_repositories` retorna
  antes de escribir). El lector comprueba `acknowledged: true` en
  `critical/list` y, si el aviso existía, que ya no está.
- Test de contrato: el lector del banco envía la carga exacta que construye
  Hermes para cada comando de escritura (función pública del módulo común)
  con un repositorio inexistente; HA tiene que responder un error del
  manejador (`repository_not_found`, `warning_not_accepted`,
  `github_not_connected`, `not_loaded`) y nunca `invalid_format` ni
  `unknown_command`. Así una clave mal escrita se ve contra HA real.
- Motivo de `NO_EJECUTABLES_026`: «Marketplace: el banco no tiene internet,
  así que el Marketplace no descarga el catálogo y no hay ningún repositorio
  sobre el que actuar (HA respondería repository_not_found); instalar, fijar
  versión, betas y añadir exigen además el aviso de riesgos aceptado por el
  usuario de Hermes (y añadir, GitHub conectado), que el banco no puede dar
  sin hacer lo que Hermes nunca hace. Se prueban con HA simulado en la suite
  normal y con el test de contrato del banco».
- Matriz de la 014: reconocer, «banco de Core / ok»; las otras ocho,
  «instalación real / pendiente» con «no ejecutable en el banco: …» en la
  nota. El test de la matriz admite para un `NO_EJECUTABLES*` un entorno
  fuera del banco, y es la verdad: lo que falta es probarlas con internet y
  el Marketplace configurado (R-12), no en una VM (la 014 no la monta).

## R-12 — Pruebas en vivo

Quedan pendientes, como todo el programa (la 014 no monta VM): con internet y
el Marketplace configurado, comprobar desinstalar (repositorio de prueba),
quitar, refrescar, ignorar y reconocer, y que instalar responde
`marketplace_warning_not_accepted` (R-2). Se anotan en la viñeta de la 026 de
la hoja de ruta, no en `docs/BANCO-SUPERVISOR.md` (no son del Supervisor).
