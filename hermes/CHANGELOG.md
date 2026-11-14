# Changelog

## [1.1.0] — 2026-11-14

Tools nuevas para organizar la casa y diagnosticar problemas, el Marketplace
que sustituye a HACS en Home Assistant 2026.11, backups de HA, retención de los
safety backups y un OAuth al día con lo que piden los clientes de Claude. Son
216 tools.

Trae también los arreglos de la 1.0.12, que no se publicó por separado: si
vienes de la 1.0.11, lee también la sección siguiente.

**Antes de actualizar:**

- `response_max_bytes` pasa a 128 KiB por defecto y `wait_for_event_max_seconds`
  admite como mucho 220 s. Si tenías valores guardados, mira *Changed — Límites
  alineados con los de Claude*.
- Si después de actualizar Claude no ve las tools nuevas, quita el conector y
  vuelve a añadirlo: algunos clientes guardan la lista de la primera conexión.

### Added — Plantas, etiquetas y categorías

Hermes ya gestionaba entidades, dispositivos y áreas; faltaban las otras tres
formas que tiene HA de organizar la casa. Doce tools nuevas:

- Plantas: `ha_list_floors`, `ha_create_floor`, `ha_update_floor`,
  `ha_delete_floor`.
- Etiquetas: `ha_list_labels`, `ha_create_label`, `ha_update_label`,
  `ha_delete_label`.
- Categorías, por ámbito (automation, script, scene o helpers):
  `ha_list_categories`, `ha_create_category`, `ha_update_category`,
  `ha_delete_category`.

Crear no pide confirmación (no se pierde nada). Editar y borrar sí. La vista
previa de un borrado separa lo que HA limpia solo (áreas, dispositivos o
entidades que pierden la planta, la etiqueta o la categoría) de lo que no
edita: automatizaciones, scripts y escenas que la usan como objetivo y que
dejarán de encontrar nada sin avisar. Si alguna lectura falla, no hay token.

### Added — Diagnóstico: Repairs, trazas y relaciones

Para responder «¿por qué no funciona?» sin abrir la interfaz:

- `ha_list_repairs` y `ha_ignore_repair`: los avisos del panel Reparaciones,
  ordenados por gravedad y con los datos internos redactados. Ignorar pide
  confirmación, porque oculta un aviso que puede anunciar una rotura futura;
  no arregla nada y se deshace con `ignore=false`.
- `ha_list_traces` y `ha_get_trace`: las últimas ejecuciones de una
  automatización o un script, con el `entity_id` de siempre. El detalle sale
  resumido por defecto, con las variables redactadas, y nunca pasa de 64 KiB
  ni de `response_max_bytes`.
- `ha_search_related`: qué usa algo y qué lo usa, para saber qué se romperá
  antes de renombrar o borrar.

### Added — Centro de resolución del Supervisor

`sv_get_resolution` devuelve, de solo lectura, por qué la instalación sale
como no soportada o no saludable, y los issues, sugerencias y checks del
Supervisor, con las referencias redactadas. `sv_dismiss_resolution_issue` y
`sv_dismiss_resolution_suggestion` los descartan con `confirmation_token`; la
vista previa dice qué se descarta y que puede volver si la causa sigue.

Hermes **nunca aplica** una sugerencia del Supervisor: algunas borran backups
o reinician el host. Si conviene aplicarla, hazlo desde la interfaz de Home
Assistant. Un test vigila que ninguna tool lo haga.

`hermes_guide("diagnostics")` (o `"repairs"`, `"traces"`, `"resolution"`)
explica todo el diagnóstico, y `hermes_guide("registries")` incluye plantas,
etiquetas y categorías.

### Added — Backups de Home Assistant

`ha_list_backups`, `ha_get_backup` y `ha_get_backup_config` (HA 2025.1 o
posterior) leen la integración `backup` de HA, que ve todas las ubicaciones
(local, red, nube) y no solo las del Supervisor. Las respuestas se construyen
con una lista cerrada de campos: nunca salen la contraseña de cifrado de los
backups automáticos (solo `password_set`), el identificador de la instalación
ni campos nuevos que HA añada en el futuro. Los errores de cada ubicación se
devuelven recortados y sin secretos, IPs ni hosts.

### Added — Retención de los safety backups (`safety_backup_keep`)

Con `safety_backup_enabled`, cada safety backup pesa varios GB y antes nadie
los borraba. La opción nueva `safety_backup_keep` (0–50, **3** por defecto)
hace que, tras cada safety backup automático correcto, Hermes conserve los más
recientes y borre el resto, como mucho 5 por vez. `0` la desactiva.

Solo borra backups que él mismo anotó al crearlos y cuyo identificador
confirmó. Nunca uno ajeno, aunque se llame `hermes-safety-…`, ni uno protegido
con contraseña, parcial, copiado a otra ubicación o con fecha ilegible, ni el
que acaba de crear. Ante cualquier duda no borra nada, y un fallo de la poda
nunca bloquea la escritura en `/config`.

Los safety backups creados antes de 1.1.0 no están anotados y no se podan
solos: bórralos con `sv_delete_backup` si ya no los necesitas.

### Added — Marketplace (antes HACS), de solo lectura

Desde Home Assistant 2026.11, HACS viene integrado en el core como el
Marketplace, con otra API, y las tools `ha_hacs_*` de la 1.0.12 solo podían
decir que no lo soportaban. Siete tools nuevas lo leen:

- `ha_marketplace_info`: estado del Marketplace; `warning_accepted` es del
  usuario de HA con el que se conecta Hermes.
- `ha_marketplace_list_repositories`: repositorios, por defecto solo los
  instalados, con `category`, `search` y `limit` (el catálogo completo tiene
  miles).
- `ha_marketplace_get_repository`: detalle de uno, con su entidad `update`.
- `ha_marketplace_list_updates`: instalados con actualización pendiente y cómo
  instalarla (`update.install`, con `confirmation_token`).
- `ha_marketplace_list_releases`: versiones publicadas. Es la única que
  consulta GitHub (a través de HA), y se anuncia de mundo abierto.
- `ha_marketplace_list_critical` y `ha_marketplace_list_removed`:
  repositorios marcados como críticos o retirados del catálogo.

Detectan en cada llamada si hay Marketplace o HACS 2.x (HA ≤ 2026.10) y lo
dicen en `api`, porque HA se actualiza sin reiniciar Hermes. Solo leen: Hermes
no instala, no acepta el aviso de riesgos ni marca nada como visto. Los nombres
y descripciones de los repositorios los escriben terceros: las respuestas lo
avisan y los recortan. `hermes_guide("marketplace")` (o `"hacs"`) lo explica.

### Added — Clientes con documento de metadatos (CIMD)

Claude Code, y cualquier cliente que publique un *Client ID Metadata Document*,
se identifica ahora con la URL de ese documento en lugar de registrarse por
DCR. Hermes lo descarga, comprueba su forma y sus `redirect_uris`, y la
pantalla de autorización muestra el host de esa URL, el nombre que declara el
cliente y a dónde irá el código. Léela: es la defensa contra un enlace de
autorización que no es tuyo. Los documentos válidos se guardan en memoria
según su `Cache-Control` (entre 5 min y 24 h); si una recarga dice que el
documento ya no es válido, se revocan los refresh tokens de ese cliente.

DCR sigue funcionando igual: los clientes y tokens que ya existían siguen
valiendo. La opción nueva `oauth_cimd_enabled` (por defecto `true`) desactiva
CIMD si un cliente falla con él.

### Added — OAuth: `iss` en las redirecciones, scope y audiencia de los tokens

- Toda redirección de vuelta al cliente, de éxito o de error, lleva `iss` con
  el mismo valor que `issuer` en los metadatos (RFC 9207), que anuncian
  `authorization_response_iss_parameter_supported`. El cliente puede
  comprobar así que la respuesta viene de Hermes y no de otro servidor.
- Los metadatos del recurso protegido anuncian `scopes_supported: ["mcp"]` y
  el `WWW-Authenticate` de los 401 lleva `scope="mcp"`.
- Los tokens emitidos desde esta versión quedan ligados al recurso `/mcp` de
  Hermes. Los de versiones anteriores se aceptan hasta que caduquen y su
  renovación ya sale ligada: no hace falta volver a autorizar.

### Added — Datos del servidor MCP

El servidor anuncia su versión en `serverInfo`, cada tool lleva un `title`
legible y las respuestas con `error` salen marcadas con `isError: true`, con el
mismo contenido que antes. Los nombres, parámetros y anotaciones de las tools
existentes no cambian.

### Changed — Límites alineados con los de Claude

`response_max_bytes` pasa de 1 MiB a **128 KiB** por defecto, con un máximo
efectivo de **512 KiB**. `wait_for_event_max_seconds` admite como mucho
**220 s** (el defecto sigue en 90).

Qué hacer si tenías valores guardados: nada, salvo que necesites respuestas
más grandes. La interfaz guarda el valor por defecto aunque nadie lo toque, así
que un `response_max_bytes` de `1048576` se trata como no personalizado y pasa
a `131072`. Un valor por encima de `524288`, o un `wait_for_event_max_seconds`
por encima de `220`, se recorta al máximo. El add-on arranca igual y lo anota
en el log (`config_legacy_default_replaced` o `config_value_clamped`, con el
valor guardado y el aplicado). Si las respuestas te llegan truncadas, sube
`response_max_bytes` hasta `524288`.

Claude Code corta una llamada si no recibe ningún byte en 60 s. Hermes manda
un *ping* cada 15 s, así que una espera larga no se corta; si el proxy de
delante almacena la respuesta, DOCS.md explica cómo ampliar el plazo en Claude
Code.

### Changed — Las `ha_hacs_*` devuelven la forma del Marketplace

Son alias de las `ha_marketplace_*`: misma respuesta, con `api` y sin
`_disclaimer`, más `_deprecated`. Desaparece el error
`hacs_moved_to_marketplace`. `ha_hacs_list_repositories` acepta
`installed_only` (por defecto `true`: antes devolvía el catálogo entero),
`search` y `limit`. Ya no se anuncian de mundo abierto: leen lo que HA tiene en
memoria, y `ha_hacs_get_repository` ya no pide `repository/info`, que salía a
GitHub y quitaba la marca de «nuevo».

### Changed — `sv_create_safety_backup` entra en la retención

Los backups que crea quedan anotados como safety backups de Hermes, así que
`safety_backup_keep` los cuenta y los poda en el siguiente safety backup
automático correcto. La tool sigue sin borrar nada por sí misma.

### Changed — Detalles menores

- El ejemplo de `url` de `ha_create_lovelace_resource` pasa a
  `/local/community/…`, que es donde instala el Marketplace; `/hacsfiles/`
  sigue funcionando.
- El protocolo MCP toma las versiones admitidas de las listas nuevas del SDK
  en lugar del alias deprecado. El conjunto admitido no cambia.

### Deprecated — `ha_hacs_info`, `ha_hacs_list_repositories`, `ha_hacs_get_repository` y `ha_hacs_list_updates`

Se retiran en 1.3.0. Usa la `ha_marketplace_*` del mismo nombre; la
descripción de cada alias y su respuesta (`_deprecated`) lo dicen.

### Security — El log ya no expone tu hostname ni tus IPs

Hasta la 1.0.12, el hostname de Tailscale, que identifica la tailnet, y las IPs
de los clientes salían en claro en un log que se suele compartir al pedir
ayuda. La opción nueva `log_redact_network` (por defecto `true`) sustituye el
`public_hostname`, cualquier nombre `*.ts.net` y las IPs que no sean de
loopback por marcadores. Las IPs pasan a un seudónimo con su clase (`tailnet`,
`private`, `public`…) que cambia en cada arranque, de modo que las líneas de
una misma ejecución se pueden correlacionar sin revelar la dirección. Cubre
también los mensajes del SDK de MCP, uvicorn y aiohttp, y las líneas que
devuelve `sv_get_addon_logs` sobre el propio Hermes, incluidas las escritas
antes de actualizar. Con la opción desactivada, el arranque lo avisa con
`log_network_redaction_disabled`; los secretos se redactan siempre.

### Security — Descargas de CIMD acotadas contra SSRF

Con CIMD, quien llama al endpoint público `/oauth/authorize` elige una URL que
Hermes descarga. Para que eso no convierta a Hermes en un proxy hacia tu red:
la forma de la URL se comprueba antes de descargar nada; Hermes resuelve el
host y rechaza la petición si **alguna** dirección es de uso especial
(loopback, privadas, link-local, CGNAT y por tanto la tailnet, ULA,
multicast…), y conecta a las direcciones ya validadas sin volver a resolver.
Sin redirecciones ni proxies del entorno, 5 s en total, 5 120 bytes como
mucho, 4 descargas a la vez y 30 por minuto. Cada rechazo queda en el log como
`oauth_cimd_rejected` con el motivo y el host, nunca con el documento.

## [1.0.12] — 2026-11-14

No se publicó por separado: estos cambios llegan a los usuarios con la 1.1.0.

Solo arreglos, tras revisar Hermes contra Home Assistant 2026.11. Varios
venían de cambios de HA (2026.2, 2026.4, 2026.9, 2026.11) que Hermes no había
seguido; otros eran fallos propios. La lista completa, con su severidad, está
en `docs/HOJA-DE-RUTA.md`.

### Fixed — Editar los alias de una entidad le quitaba el nombre por voz

Desde HA 2026.4, un `null` dentro de `aliases` significa «el nombre calculado
de la entidad». `ha_update_entity_registry` lo convertía en el texto `"None"`,
así que leer los alias, añadir uno y guardarlos dejaba la entidad sin
responder a su nombre en Assist, sin ningún error. Ahora el `null` llega a HA
tal cual, en HA 2026.4 o posterior. En versiones anteriores HA no lo admite
(en la 2024.10 lo guardaba y Assist fallaba después), así que Hermes lo
rechaza con `null_alias_requires_ha_2026_4`; si no puede leer la versión de
HA, también (`ha_version_unknown`).

`aliases: null`, que la descripción presentaba como «limpiar alias», lo
rechazaba HA. Ahora lo rechaza Hermes antes de llamar a HA y explica qué usar:
`[]` para vaciar, `[null]` para dejar solo el nombre calculado. La
descripción avisa también de que, desde HA 2026.11, `name` es solo la parte de
la entidad: HA le antepone el nombre del dispositivo.

### Fixed — `ha_remove_device_from_config_entry` borraba el dispositivo entero

Desde HA 2026.9, el comando que usa es un alias del borrado de dispositivos:
si la integración es la del dispositivo, lo borra del registro con todas sus
entidades. La tool anunciaba que solo quitaba la asociación, y su vista
previa también. La vista previa es la única revisión antes de confirmar, y
mentía. Ver *Added* y *Deprecated*.

### Fixed — El dashboard principal se podía borrar

En las instalaciones migradas en HA 2026.2, el dashboard principal es uno
normal con `url_path: "lovelace"`, y `ha_delete_lovelace_dashboard` lo borraba
con un token, aunque su descripción decía que no se podía. Sus vistas solo
vuelven desde un backup.

Ahora la tool se niega siempre, antes de emitir token, con `lovelace`, con el
dashboard que HA abre por defecto y sin `url_path`
(`cannot_delete_default_dashboard`). Si no puede saber cuál es el de por
defecto, también se niega (`default_panel_unknown`). Quien quiera borrarlo de
verdad tiene la interfaz de HA. `ha_list_lovelace_dashboards` ya no lo enseña
dos veces.

### Fixed — Con `safety_backup_enabled` activada no se escribía ningún fichero

Solo afectaba a quien activó esa opción, que viene desactivada. Hermes
sondeaba un endpoint del Supervisor que no existe, así que el backup completo
nunca se daba por terminado: cada escritura `fs_*` esperaba 5 minutos, fallaba
y dejaba otro backup completo de varios GB en disco.

Ahora consulta el job del backup y solo escribe si terminó sin errores. Es
fail-closed:

- Si el backup falla, no se escribe: `safety_backup_job_failed`, con los
  errores del Supervisor.
- Si Hermes no puede saber cómo acabó —el Supervisor no responde o ya no
  conoce el job—, tampoco: `safety_backup_state_unknown`.
- Si tarda más de 5 minutos, la escritura se rechaza
  (`safety_backup_timeout`), pero el backup queda anotado. La escritura
  siguiente comprueba ese mismo backup en vez de lanzar otro: escribe si ya
  terminó bien y, si sigue en marcha, responde `safety_backup_in_progress`.
  Ese backup cuenta desde que se lanzó: si es más antiguo que la ventana, la
  escritura se rechaza (`safety_backup_stale`) y la siguiente lanza uno nuevo.
- Un backup que lleva más de 2 horas sin terminar se da por colgado: se deja
  de esperar (`safety_backup_state_unknown`, con cómo salir) para que no
  bloquee las escrituras para siempre, y la escritura siguiente lanza otro.
- Entre dos intentos pasan al menos 60 s, también después de uno fallido o de
  uno cuyo envío al Supervisor falló, para que un fallo no encadene backups
  completos. Si una escritura llega antes, la respuesta es
  `safety_backup_rate_limited`. Dos escrituras a la vez ya no lanzan dos
  backups: la segunda espera a la primera.

### Fixed — `sv_get_job_status` daba por terminado un job que había fallado

El Supervisor marca `done: true` también cuando el job falla, y Hermes no
miraba sus errores. Ahora la respuesta trae `errors` y `success`, y
`sv_list_pending_jobs` marca esos jobs como `failed`.

### Fixed — No se podía guardar un script con `trace`

`ha_create_or_update_script` esperaba `trace` como lista, pero en HA es un
objeto (`stored_traces`…). Cualquier script con trazas configuradas se
rechazaba.

### Fixed — Errores genéricos donde debía decir `not_found`

Borrar un helper que no existe, o pedir la entrada del registro de una entidad
que no existe, devolvía el texto crudo de HA. Hermes buscaba en el mensaje
una frase que el de HA no siempre contiene. Ahora decide por el
código de error de HA (`not_found`), que no cambia entre versiones, y responde
`{"error": "not_found", …}`.

### Fixed — `ha_render_template` perdía el resultado si la plantilla daba un aviso

Con un simple aviso de HA (una variable sin definir, por ejemplo), la tool
devolvía error y el resultado se perdía. Ahora devuelve el resultado con los
avisos en `warnings`, sin repetidos (HA puede enviar el mismo aviso dos
veces). Si HA informa de que la plantilla tardó demasiado, el
error es `template_timeout`.

### Fixed — Los dispositivos hijo no salían al filtrar por área

Desde HA 2026.9 un dispositivo puede colgar de otro y, si no tiene área
propia, está en la de su padre. `ha_list_devices`, `ha_list_entities_registry`
y la vista previa de `ha_delete_area` usan ahora esa área efectiva. Las vistas
previas de deshabilitar o borrar una integración cuentan sus dispositivos por
`config_entry_id`, con `config_entries` solo como respaldo, así que siguen
bien cuando HA retire ese campo (2027.8). Los hijos no tienen fabricante y
quedan fuera del filtro `manufacturer`; la descripción lo dice.

### Fixed — Campos siempre a `null` en la información del sistema

`sv_get_supervisor_info` y `sv_get_host_info` devolvían `null` en la máquina,
la versión de Docker y el kernel porque los leían de donde el Supervisor no
los pone. Ahora salen de `/info` y del campo `kernel` del host.

### Fixed — Las tools de HACS fallaban con «Unknown command» en HA 2026.11

Desde HA 2026.11, HACS viene integrado como el Marketplace y los comandos
`hacs/*` ya no existen. Las tools `ha_hacs_*` todavía no lo soportan (es
trabajo de la 1.1.0), pero ahora lo dicen claro: `hacs_moved_to_marketplace`
con la forma de ver las actualizaciones pendientes, o `hacs_not_installed` en
versiones anteriores. Antes sugerían actualizar Hermes, que no lo arreglaba.
También usan las categorías reales de HACS y cuentan como pendientes las
actualizaciones que HACS marca con `pending_upgrade`.

### Fixed — `period: "year"` en estadísticas con HA antiguo

`ha_statistics_during_period` lo aceptaba sin mirar la versión, y HA lo
rechaza antes de la 2026.3. Ahora Hermes da un error claro en esas versiones.

### Fixed — Descripciones de tools que no coincidían con la respuesta real

`ha_list_statistic_ids`, `sv_get_host_info`, `sv_get_addon_stats` y
`sv_list_backups` describían campos que no devuelven o una ubicación de los
backups que no es la real. Ahora describen lo que hay.

### Fixed — La guía enseñaba sintaxis antigua de automatizaciones

El ejemplo de `hermes_guide("automations")` usaba `platform:` y `service:`.
Ahora usa `triggers`/`trigger:` y `actions`/`action:`, como el editor de HA.
La guía de registros presenta `ha_remove_device` y la de servicios recomienda
filtrar `ha_list_services` por dominio.

### Added — `ha_remove_device`

Borra un dispositivo del registro junto con sus entidades, y la vista previa
dice qué comando de HA va a usar. Desde HA 2026.9, borrar un dispositivo borra
también sus dispositivos hijo y las entidades de estos: la vista previa los
lista (`child_devices`) y los cuenta en `entities_count`. Si no puede saber
cuáles son, se niega (`child_devices_unknown`), y si aparece uno nuevo entre la
vista previa y la confirmación, aborta (`child_devices_changed`).

- HA 2026.9 o posterior: el borrado de dispositivos.
- Versiones anteriores: quitar la única integración del dispositivo, que HA
  convierte en borrado. Si tiene varias, se niega (`multiple_config_entries`)
  sin tocar nada.
- Si no puede leer la versión de HA, se niega (`ha_version_unknown`). Si entre
  la vista previa y la confirmación HA se actualiza y el comando que toca usar
  cambia, aborta (`ha_version_changed`) en vez de ejecutar algo distinto de lo
  revisado.

### Added — Filtro `domain` en `ha_list_services`

Sin filtro, la lista de servicios de una casa grande podía superar el límite
de respuesta del cliente. `ha_list_services(domain="light")` devuelve solo los
de ese dominio.

### Changed — Home Assistant 2024.10 como versión mínima

Hermes guarda las automatizaciones con las claves en plural (`triggers`,
`conditions`, `actions`), que HA solo entiende desde la 2024.10. La 1.0.11
declaraba la 2024.1, así que una HA 2024.1–2024.9 arrancaba sin aviso y luego
no podía guardar ninguna automatización. El add-on declara ahora la mínima en
su manifiesto (`homeassistant: "2024.10.0"`), así que con una HA anterior el
Supervisor rechaza instalar o actualizar Hermes con un error claro, en vez de
instalar una versión que no arranca. Si aun así llega a arrancar, el log dice
`HA core … < minimum supported 2024.10.0`: actualiza Home Assistant antes de
actualizar Hermes.

### Changed — Tailscale Funnel en el 8443 en lugar del 443

Los README recomiendan publicar Hermes con
`tailscale funnel --bg --https=8443 8765` (o 10000) y
`public_hostname: homeassistant.tailXXXX.ts.net:8443`. La opción
`share_homeassistant: funnel` del add-on de Tailscale publica Home Assistant en
el 443 por defecto y, en el mismo puerto, uno de los dos deja de responder. El
443 sigue valiendo si no se usa esa opción. Los README explican cómo pasar del
443 al 8443: quitar el Funnel viejo, crear el nuevo, cambiar
`public_hostname` y volver a añadir el conector en Claude.

No hace falta cambiar nada si tu instalación ya funciona.

### Changed — Publicación de la imagen con las actions nuevas de Home Assistant

La action `home-assistant/builder` que compilaba la imagen está retirada; sin
cambiarla, la próxima versión se habría anunciado en la tienda sin imagen que
instalar. La imagen se compila ahora con la action `build-image` de Home
Assistant, cada arquitectura en su propia máquina y firmada. `build.yaml`
desaparece: el Dockerfile trae su imagen base.

El add-on declara `timeout: 20`: al pararlo, Docker espera 20 s antes de
matarlo, en vez de 10, para que el apagado ordenado termine.

### Deprecated — `ha_remove_device_from_config_entry`

Usa `ha_remove_device`. La antigua sigue funcionando para no romper a quien la
use, pero su descripción y su vista previa dicen ahora la verdad: en HA 2026.9
o posterior borra el dispositivo entero, con sus dispositivos hijo y las
entidades de todos, no solo la asociación; la vista previa los lista. Si no
puede leer la versión de HA, o no puede saber qué hijos tiene el dispositivo,
se niega antes de emitir token. HA retira el
comando que usa en la 2027.9, así que la tool desaparecerá en una versión de
Hermes anterior a esa.


## [1.0.11] — 2026-11-14

### Fixed — Cambiar `auth_password` no cerraba ninguna sesión

Los tokens solo dependen de la contraseña en el momento del login. Cambiarla
dejaba vivas todas las sesiones abiertas hasta cumplir sus 7 días, justo lo
contrario de lo que espera quien la cambia porque sospecha que se la han
visto. La única forma de cortarlas era desinstalar el add-on.

Ahora, al arrancar, Hermes compara la contraseña con la del arranque
anterior. Si cambió, borra todos los tokens y los códigos de autorización
pendientes, y lo registra como `oauth_sessions_revoked_password_changed`.
Cada cliente tiene que autorizarse otra vez con la contraseña nueva.

Para notar el cambio guarda en `/data/oauth` una huella scrypt de la
contraseña con sal propia, nunca la contraseña. Detalles:

- Sin huella previa no hay con qué comparar y no se cierra nada. Es el caso
  de esta misma actualización: pasar a la 1.0.11 no obliga a nadie a
  autorizar de nuevo.
- Una huella ilegible cuenta como cambio: ante la duda, se cierra.
- Si la huella no se puede calcular o guardar, Hermes arranca igual y lo
  registra como `oauth_password_fingerprint_failed`.

### Fixed — `sv_get_core_info` devolvía siempre `state: null`

Leía el estado del `/core/info` del Supervisor, que no tiene ese campo. El
test pasaba porque su respuesta simulada se lo inventaba. Ahora el estado se
lo pregunta al propio Core por la WebSocket (`get_config`): `running`,
`starting`, `stopping`, `not_running`… Sin conexión con el Core, por
ejemplo mientras reinicia, devuelve `unreachable` en vez de colgarse.

### Fixed — Aviso de versión de Home Assistant «no probada» con versiones que funcionan

La 1.0.10 salió con 2026.9.0 como última versión probada de Home Assistant,
así que cualquier instalación al día avisaba en cada arranque con
`ha_core_version_untested`. Hermes está comprobado contra 2026.11.1. La regla
de revisar ese valor en cada versión estaba solo en un comentario; ahora un
test la exige.

## [1.0.10] — 2026-11-07

### Fixed — `sv_set_addon_options` borraba las opciones que no se le pasaban

Su descripción decía «pasa solo los campos que quieres cambiar; el resto se
mantiene como está», pero enviaba al Supervisor únicamente lo que pasaba el
llamante. Y el Supervisor no mezcla: `POST /addons/{slug}/options` valida el
cuerpo con el schema del add-on y **sustituye** las opciones guardadas por él.
Lo que no se envía se pierde y vuelve a su valor por defecto, si lo tiene.

Cambiar una sola opción de Zigbee2MQTT habría borrado el puerto serie y la
contraseña de MQTT. La contraseña, además, el llamante no podía reponerla:
Hermes solo se la enseña redactada. Se vio en la vista previa, antes de
confirmar nada.

Ahora la tool lee las opciones actuales de `/addons/{slug}/info` —las mismas
que usa `sv_get_addon_options`, con las referencias `!secret` sin resolver—,
pone los cambios encima y envía el conjunto completo:

- Los objetos anidados (`mqtt`, `serial`…) se mezclan clave a clave; las listas
  y los valores simples se sustituyen enteros.
- `null` quita una opción. Si el add-on le da un valor por defecto, vuelve ese
  valor.
- Un valor que lleve `***REDACTED***`, a cualquier nivel, se rechaza: es el
  marcador con que Hermes tapa los secretos, y guardarlo machacaría el real.
- La vista previa enseña las opciones actuales, los cambios pedidos, las
  opciones finales y las rutas que cambian, todo con los secretos redactados.
  `new_options` desaparece: lo sustituyen `requested_changes` y
  `final_options`.
- Al confirmar se vuelven a leer las opciones actuales y se mezcla de nuevo:
  si alguien las tocó entre la vista previa y la confirmación, lo que el
  llamante no cambia conserva su valor más reciente.
- Si no se pueden leer las opciones actuales, no se envía nada ni se emite
  token (`current_options_unavailable`). Antes la vista previa seguía adelante
  con `current_options: null`.

El Supervisor solo incluye las opciones en `/info` si quien pregunta tiene rol
`manager` o `admin`; a cualquier otro le manda `options: {}` con el schema
entero. Mezclar sobre ese `{}` volvería a borrarlo todo, así que la tool se
niega cuando recibe `{}` y el schema tiene alguna opción obligatoria: un
add-on así no tiene `{}` legítimo. Hermes declara `hassio_role: admin`, y un
test del manifiesto exige ahora `manager` o `admin`.

## [1.0.9] — 2026-09-14

Cierra los issues #2, #3, #6, #7, #8 y #9: lo que el repaso completo dejó
fuera de la 1.0.8 por bajo impacto o por exigir una decisión. Ninguno afecta
al uso diario con Tailscale Funnel; el #6 solo aplica a `reverse_proxy` en la
red puente. Un test de regresión por cambio, con control negativo.

### Changed — `fs_search_in_config` ejecuta la expresión regular en un proceso aparte (#2)

La heurística sintáctica de la 1.0.8 rechaza cuantificadores anidados y
retrorreferencias, pero no la explosión por alternativas solapadas: `(a|aa)+$b`
contra 38 «a» tarda 20 segundos y se multiplica por 2,6 cada dos caracteres
más. Como el motor `re` de CPython no se puede interrumpir, un patrón así
dejaba colgado para siempre un hilo del pool de `asyncio.to_thread`.

Ahora el escaneo corre en un proceso hijo (contexto `spawn`, no `fork`: el
add-on tiene un bucle de eventos con sockets y locks que un fork heredaría en
mal estado) con un plazo de 10 segundos; al vencer, se le envía SIGTERM y, si
hace falta, SIGKILL, y la herramienta devuelve `search_timeout`. La lista de
ficheros legibles la sigue calculando el padre: el hijo recibe rutas ya
filtradas por la lista negra y no decide nada. La heurística se queda como
primera capa barata. Coste aceptado: unas décimas de segundo por búsqueda
para arrancar el intérprete.

### Fixed — Los backups de `a/b.yaml` y `a__b.yaml` ya no comparten nombre (#3)

El aplanado de la ruta sustituía `/` por `__` y no era reversible. Los backups
nuevos codifican `%` como `%25` y `/` como `%2F`, que sí lo es. Los ficheros
antiguos siguen contando para la rotación y siguen siendo restaurables: los
lectores aceptan ambos formatos, y un nombre antiguo ambiguo se marca con
`legacy_name` y sus posibles rutas. La ambigüedad desaparece sola conforme
rotan los backups antiguos. El destino de una restauración es siempre la ruta
que pasa quien llama; el nombre del backup solo elige el origen.

### Added — `trusted_proxy_ips` (#6)

uvicorn solo cree `X-Forwarded-For` desde `127.0.0.1`, así que con
`reverse_proxy` y `mcp_bind` en la red puente todas las peticiones llegaban
con la IP del proxy y los tres límites por IP —pre-auth, fallos de
autenticación y freno del login— se convertían en uno global. La opción
nueva admite IPs sueltas o rangos CIDR (`172.30.32.0/23` es la red puente de
HAOS), se valida al arrancar y se registra en `hermes_started`. Vacía por
defecto: el modo `tailscale` no la necesita. Quien esté dentro de un rango de
confianza puede falsificar la IP del cliente, que solo alimenta límites y
logs, nunca la autorización.

### Changed — OAuth: cuatro flecos de la especificación (#7)

- `resource` (RFC 8707) se acepta en `/authorize` y `/token`, se compara con el
  único recurso, el servidor MCP, y cualquier otro valor devuelve
  `invalid_target`. Se guarda en el código de autorización como audiencia.
- PKCE se comprueba antes de enseñar el formulario y antes de mirar la
  contraseña: un cliente sin PKCE recibe un 400 que explica que el error es
  suyo, y ya no le cuesta al dueño ni la contraseña ni un intento del freno.
- `/.well-known/oauth-authorization-server/mcp` se sirve igual que la raíz
  (RFC 8414 §3.1). Cada 404 era un viaje más por Funnel.
- `redirect_uri` omitido en el token endpoint se registra en el log como
  `oauth_token_redirect_uri_omitted`. No se rechaza: PKCE ya ata el código a
  quien lo pidió, y no hay evidencia de que el cliente de Claude lo envíe;
  rechazarlo podría romper un flujo que hoy funciona. Si el log demuestra que
  nadie lo omite, se endurece.

### Fixed — Arranque y apagado: cinco observaciones (#8)

- El servidor de health comprueba el bind antes de arrancar y, si falla,
  registra `health_bind_failed` con host, puerto, errno y una pista, en vez de
  morir sin una línea. `HERMES_HEALTH_BIND` es una escotilla por variable de
  entorno solo para desarrollo fuera de HAOS; no es opción del add-on.
- Apagado ordenado: `S6_KILL_GRACETIME` sube a 10 s en la imagen, uvicorn
  recibe `timeout_graceful_shutdown=3`, y la espera de Hermes queda entre
  ambos. Un test lee el Dockerfile y el código para que los tres números no
  se separen.
- `health_startup_grace_seconds` se documenta como presupuesto **por paso**
  del arranque, que es lo que siempre fue, y se registra en el paso 4.
- La espera de Tailscale solo mira interfaces `tailscale*`. Antes cualquier
  dirección CGNAT valía, y un uplink LTE o satélite la satisfacía sin
  Tailscale. El modo userspace no crea ninguna interfaz, como ya exigía el
  README.
- Un `version` numérico en `/core/info` ya no aborta el arranque.

### Docs — Los 502 en ráfagas paralelas (#9)

El README, en ambos idiomas, explica el fallo intermitente que motivó el
repaso: en ráfagas de 6 o más llamadas en paralelo, entre el 15 % y el 30 %
vuelven con un 502 de Cloudflare para `api.anthropic.com` y nunca llegan a
Hermes. Cómo reconocerlo en el log y cómo aislar el lado de Funnel.

## [1.0.8] — 2026-09-14

Los 22 fallos restantes del repaso completo que empezó en la 1.0.7, con un
test de regresión por cada uno y control negativo (cada test nuevo falla
contra el código anterior). Ninguno es un agujero de seguridad como los de
la 1.0.7, pero varios rompen funciones enteras o fuerzan reautorizaciones.

La 1.0.7 no llegó a publicarse como versión propia: si vienes de la 1.0.6,
esta actualización trae también sus siete arreglos de seguridad, descritos en
la sección siguiente.

### Fixed — OAuth: la ventana de gracia del refresh token no devolvía el sucesor

Si Claude perdía la respuesta de una rotación y reintentaba con el token
anterior, Hermes contestaba dentro de la ventana de gracia con un access
token **sin** `refresh_token`: solo tenía el hash del sucesor y no podía
devolverlo. El cliente se quedaba con el viejo, y una hora después ese viejo
ya estaba fuera de gracia: se revocaba la cadena entera y tocaba volver a
autorizar. Era una reautorización forzada con origen en el código.

Ahora, al rotar, el sucesor se guarda sellado con AES-GCM bajo una clave
derivada del valor del token que se presenta, que nunca está en disco. Solo
quien presente ese token puede abrirlo, que es exactamente el cliente que
reintenta. La gracia exige además que el sucesor siga siendo la cabeza viva
de la cadena: un token dos rotaciones por detrás ya no se atiende, es
reutilización y revoca todo. Antes esa réplica obtenía un access token
válido sin disparar la alarma.

### Fixed — OAuth y middleware, ocho más

- `redirect_uri` con query recibía `?tenant=42?code=…`; ahora se añade con `&`.
- Revocar un refresh token ya rotado no tocaba la sesión viva; ahora sigue la
  cadena entera, como pide la RFC 7009.
- Un `code_verifier` fuera del alfabeto de la RFC 7636 producía un 500 con
  traza desde un endpoint sin autenticar; ahora es `invalid_grant`.
- Las respuestas del token endpoint llevan `Cache-Control: no-store`.
- El código de autorización ya no se guarda en claro dentro de su fichero.
- `/.well-known/oauth-protected-resource/<otro path>` responde 404 en vez de
  anunciar `/mcp` como recurso de rutas que no existen.
- Las rutas OAuth públicas con barra final (`/oauth/token/`) devolvían 401, que
  el cliente leía como fallo de registro.
- El cubo de fallos de autenticación se vaciaba entero al superar 10.000 IPs,
  reseteando el contador de todas; ahora purga primero las entradas con menos
  fallos. Y el log de errores del MCP perdía las cabeceras repetidas al
  reconstruir la respuesta.

### Fixed — Arranque y ciclo de vida

- `startup: services` arrancaba Hermes **antes** de Home Assistant Core, al
  revés de lo que decía su comentario; en hardware lento el paso 8 agotaba su
  plazo y salía con error. Ahora es `application`.
- Una caída larga de Core dejaba Hermes parado para siempre: `/health` daba
  503 a los 300 s, el vigilante reiniciaba, el arranque exigía Core y fallaba,
  y tras varios intentos el Supervisor se rendía. El paso 8 ya no es fatal, y
  `/health` devuelve 200 con `degraded_long` en vez de 503: reiniciar nunca
  arregla una caída de Core, y el bucle de reconexión se recupera solo.
- `call_service_auto_classify_dangerous: false` era imposible: `jq` con
  `// empty` trata `false` como vacío y caía al valor por defecto.
- La comprobación de versión de Core abortaba el arranque ante una respuesta
  transitoria no reintentable (`version: "landingpage"`, cuerpo no JSON).
- La protección anti crash-loop corría después de validar la configuración,
  así que un bucle por configuración inválida, el caso real del 6 de
  septiembre, nunca contaba; ahora corre antes. Un fichero de arranques
  corrupto la desactivaba para siempre, y el umbral exigía un arranque más de
  los que el Supervisor llega a hacer.
- Los ficheros de confirmación caducados solo se limpiaban al arrancar; ahora
  también cada hora.

### Fixed — Cliente de Home Assistant

- `ws_send` retenía el lock durante toda la espera de respuesta: una llamada
  colgada serializaba todo el tráfico WebSocket hasta 30 s.
- Al caer la WebSocket solo se fallaban los comandos pendientes; las
  suscripciones de `ha_render_template` y las colas de `ha_wait_for_event`
  esperaban su propio timeout con HA caída.
- `ha_cancel_wait` tardaba hasta 15 s en hacer efecto.
- `ha_render_template` aceptaba un timeout sin tope; se acota a 1-60 s.
- El hash que ata un token de confirmación a sus argumentos podía colisionar:
  `{"x": 1.5}` y `{"x": {"__float__": "1.5"}}` daban el mismo. Las claves de
  usuario que empiezan por `__` se escapan.
- `ha_get_state` de una entidad inexistente lanzaba error en vez de devolver
  `not_found`, y a la inversa, con HA caída `ha_run_script` decía `not_found`
  de un script que sigue ahí.

### Fixed — Herramientas de Supervisor y registros

- Todas las herramientas de dashboards adicionales estaban muertas: enviaban
  `lovelace/dashboards`, que HA no registra; el comando es
  `lovelace/dashboards/list`. El test simulaba el comando inexistente.
- Actualizar un helper fallaba o borraba campos: HA reemplaza el objeto entero
  y exige `name`; ahora se envía el objeto actual fusionado con el cambio. El
  fixture de tests hacía un merge, por eso pasaban.
- `size_mb` de los backups era siempre 0.0: el Supervisor ya devuelve
  megabytes.
- Al terminar un flujo de integración se perdía el `entry_id`: el estado
  pisaba el campo `result` donde HA lo pone. Ahora va en `status`.
- `ha_hacs_list_repositories` con filtro siempre fallaba: HACS espera
  `categories`, no `category`.
- `sv_set_addon_options` seguía leyendo el endpoint prohibido en su vista
  previa; `installed_only=False` no hacía nada; `period="year"` se rechazaba.
- La redacción de opciones de add-ons dejaba pasar `psk`, `pre_shared_key`,
  `network_key` y las variantes con guion.
- La vista previa de `ha_delete_area` no contaba las entidades que heredan el
  área de su dispositivo. Y un `pending_jobs.json` que no fuera un objeto
  perdía el job tras haber lanzado la operación.

### Fixed — Sandbox de ficheros

- `fs_search_in_config` ejecutaba cualquier expresión regular: `(a+)+$b` colgaba
  un hilo del pool para siempre. Se rechazan cuantificadores anidados y
  retrorreferencias, y se acotan patrón y línea.
- Un `!include` circular en `configuration.yaml` rompía todas las vistas previas
  de escritura, incluida la que hacía falta para arreglarlo; y un `!include`
  fuera de `/config` se abría igualmente. Ahora hay detección de ciclos y
  contención, y el conjunto de ficheros ejecutables se guarda resuelto.
- El backup recién creado podía borrarse en la misma llamada por cuota, porque
  la evicción ordenaba por una fecha que se copiaba del original; y la rotación
  por ruta confundía `x.yaml` con `pkg/x.yaml`.
- Rutas con byte nulo o demasiado largas hacían reventar la tool en vez de
  devolver error; escribir o mover sobre un directorio fallaba después de
  emitir token y consumir cupo.
- La escritura atómica seguía un symlink plantado en el nombre temporal, dejaba
  el fichero legible por todos un instante y no hacía `fsync`.

## [1.0.7] — 2026-09-14

No se publicó por separado: estos cambios llegaron a los usuarios con la 1.0.8.

Siete fallos graves encontrados en un repaso completo del código, con un test
de regresión por cada uno y control negativo: los 19 tests nuevos de guarda
fallan contra el código de la 1.0.6. Actualiza cuanto antes.

### Fixed — El `confirmation_token` se usaba como ruta de fichero sin validar

Cualquier tool destructiva construía `CONFIRMATIONS_DIR / f"{token}.json"` con
el token tal cual, y al no encontrar en él un token vigente **borraba** ese
fichero. Con `confirmation_token="../options"` se borraba `/data/options.json`,
la configuración del propio add-on con `auth_password` dentro; con
`../write_rate_limit` se reseteaba el limitador de escrituras; con más `..` se
llegaba a `/config`. Ahora el token debe tener la forma exacta de un UUID4
antes de tocar el disco, y si no la tiene se rechaza sin construir ninguna ruta.

### Fixed — `fs_delete_file` no comprobaba la lista negra

`fs_delete_file("secrets.yaml")` devolvía `{"result": "ok"}` y lo borraba. Lo
mismo con la base de datos del recorder, certificados y claves privadas, e
`ip_bans.yaml`. El backup previo caía en `backups/sensitive/`, que Hermes no
lista ni restaura: la pérdida era irrecuperable desde aquí. `fs_write_file` y
`fs_move_file` sí lo comprobaban; delete se quedó fuera. Ahora rechaza con
`blacklisted`, con y sin token, igual que ellos.

### Fixed — `fs_set_secret` inyectaba YAML

El valor se concatenaba tal cual en `secrets.yaml`. Un salto de línea añadía
claves nuevas que sobreescribían secretos existentes, y la vista previa no lo
enseñaba porque solo muestra la clave. Un `: ` dejaba el fichero inválido y
Home Assistant sin arrancar, sin poder repararlo por Hermes porque el fichero
está en la lista negra. Un `#` truncaba el valor; `no` y `007` se convertían
en booleano y número.

Ahora el valor se escribe como escalar YAML entre comillas dobles, así que se
lee de vuelta exactamente igual sea cual sea su contenido; los caracteres de
control se rechazan antes de emitir la vista previa; la clave se valida con
`fullmatch`, porque `$` aceptaba un salto de línea final; y actualizar un
secreto guardado como escalar de bloque (`clave: |`) se rechaza en vez de
dejar las líneas de continuación pegadas al valor nuevo.

### Fixed — Los scripts clasificados como peligrosos se ejecutaban sin token

Home Assistant registra un servicio `script.<object_id>` por cada script, que
lo ejecuta sin ningún `entity_id` en los datos. La comprobación de entidades
restringidas solo miraba `entity_id`, así que `ha_call_service("script",
"peligroso")` pasaba sin confirmación aunque el script invocara
`shell_command.*`. Por la misma vía, `homeassistant.turn_on` con `entity_id:
all` o por área alcanza todos los dominios y tampoco se detectaba. Y
`ha_call_service_response` no consultaba las entidades restringidas en
absoluto.

`targets_restricted_entity` compara ahora también la pareja `dominio.servicio`
contra el set, trata los servicios genéricos de `homeassistant` como capaces
de alcanzar cualquier dominio, y `ha_call_service_response` la aplica y
rechaza con `entity_restricted`.

### Fixed — Una automatización recién guardada quedaba sin restringir

Al guardar con `ha_create_or_update_automation` se clasificaba bajo
`automation.<id_numérico>`, mientras Home Assistant deriva la entidad del
alias (`automation.<slug>`), que es lo que registra el escáner de arranque y
por lo que la invoca cualquiera. Una automatización nueva con
`shell_command.*` se podía disparar sin token hasta el siguiente reinicio del
add-on. Ahora se registra bajo el mismo entity_id que en el arranque.

### Fixed — `ha_create_or_update_scene` sobreescribía sin token si HA fallaba al leer

Un error transitorio al leer la configuración actual se trataba como "la
escena no existe", y ese camino crea sin vista previa ni token: la escena real
se reemplazaba entera. Ahora ese error devuelve `ha_unavailable` y no escribe
nada.

### Changed — El freno anti-fuerza-bruta del login es por IP, con techo global de respaldo

El freno era un único bloqueo global y escalonado. Bien contra la fuerza bruta,
pero convertía el login en un objetivo de denegación de servicio: una sola IP
reintentando justo al expirar cada bloqueo, 92 intentos por hora, muy por
debajo del límite pre-auth, mantenía `/oauth/authorize` en 429 el 100 % del
tiempo. Nadie podía volver a autorizar un conector mientras durase.

Ahora cada IP acumula sus propios fallos y su propio bloqueo exponencial, y el
nivel global solo cuenta los fallos de IPs que no están ya bloqueadas: hace
falta que veinte direcciones distintas fallen en cinco minutos para que salte,
que es lo que hace quien rota la IP para esquivar el primer nivel. Con
`network_mode: reverse_proxy` y `mcp_bind` en la red puente todas las
peticiones llegan con la IP del proxy, así que ahí los dos niveles coinciden,
como ya pasaba con el resto de límites por IP (ver el README).

## [1.0.6] — 2026-09-06

### Fixed — `sv_get_addon_options` no funcionaba con ningún add-on

Leía `/addons/{slug}/options/config`, un endpoint que el Supervisor reserva al
add-on que se consulta a sí mismo. A cualquier otra petición responde
`403 This can be only read by the app itself!`, así que la tool devolvía un
error siempre, para todos los add-ons, incluido el propio Hermes. Su
descripción prometía «devuelve las opciones actuales», que es exactamente lo
que no podía hacer.

Ahora las lee de `/addons/{slug}/info`, que las incluye. Sigue siendo la
versión enfocada de `sv_get_addon`: aquella devuelve el manifiesto entero
—schema, traducciones, red, permisos—, del orden de varios kilobytes para leer
cuatro valores. Devuelve `{"slug": ..., "options": {...}}`, con los secretos
redactados.

Se detectó llamando a las herramientas contra un Home Assistant en marcha. La suite
no podía verlo: **el test mockeaba el endpoint roto**, así que daba por buena
una tool que en producción no funcionaba nunca.

### Changed — La comprobación de redacción miraba solo la primera coincidencia

`test_addon_options_is_redacted` buscaba la primera aparición del endpoint en
el fichero y comprobaba que hubiera redacción cerca. Al cambiar de sitio esa
primera aparición, el test pasó a vigilar otra tool distinta sin que nada lo
delatara. Ahora comprueba, por tool, las tres que devuelven datos de un add-on.

## [1.0.5] — 2026-09-06

### Fixed — El identificador del recurso protegido no era el del servidor MCP

`/.well-known/oauth-protected-resource` anunciaba como `resource` la raíz del
host —`https://tu-host`— cuando el recurso protegido es el servidor MCP, que
vive en `https://tu-host/mcp`. Es la misma URL que el usuario pega en su
cliente.

La RFC 9728 pide al cliente comprobar que el `resource` de esos metadatos
corresponde con el recurso que está usando. Con los dos valores distintos no
puede casarlos, y un cliente estricto tiene motivo para no seguir adelante.

Por lo mismo, el puntero `resource_metadata` de la cabecera `WWW-Authenticate`
pasa a llevar el path insertado —`/.well-known/oauth-protected-resource/mcp`—,
que es la forma que define la RFC 9728 §3.1 para un recurso con path. Esa ruta
ya se servía.

El `issuer` y `authorization_servers` **no** cambian: el servidor de
autorización sí es el host, sin path.

Un test daba por buena la URL antigua, así que afirmaba el fallo en vez de
comprobar la regla.

## [1.0.4] — 2026-09-06

### Changed — Al rechazar `public_hostname`, Hermes propone el valor correcto

`public_hostname` es solo el hostname, pero la cadena que uno acaba de copiar
para pegarla en el cliente MCP es la URL entera: con `https://` delante y `/mcp`
detrás. Pegar esa es el error más fácil de cometer, y Hermes se negaba a
arrancar diciendo «sin esquema ni path ni barras» — correcto, pero dejándole a
quien lo lee el trabajo de deducir cuál era el valor bueno.

Ahora el mensaje termina proponiendo el valor limpio, cuando limpiarlo da algo
válido. Si no da nada válido, no se inventa una sugerencia.

Sigue negándose a arrancar: aceptar un hostname con path produciría URLs de
descubrimiento OAuth malformadas, y el fallo aparecería mucho más tarde y sin
relación aparente con la causa.

## [1.0.3] — 2026-09-06

### Added — El flujo OAuth deja rastro donde antes no dejaba ninguno

Un cliente MCP puede recibir su código de autorización y no volver nunca a
canjearlo. Cuando eso pasa, el log no decía **nada**: ni un error, ni un aviso.
Era indistinguible de que el usuario jamás hubiera llegado a autorizarse, y sin
forma de saber si el problema estaba en el servidor o en el cliente.

Tres señales nuevas:

- **`oauth_auth_failed` dice ahora el motivo**: `bad_password`, `unknown_client`
  o `redirect_uri_mismatch`. Los tres caminos devolvían el mismo
  «Authentication failed», así que la pantalla decía «contraseña incorrecta»
  aunque la contraseña fuera buena. El mensaje **en pantalla no cambia** —el
  motivo va solo al log—, siguiendo el mismo criterio que el endpoint del
  token. Distinguirlos ahí es seguro porque los tres se comprueban *después* de
  validar la contraseña.
- **`oauth_code_issued` registra a dónde va la redirección** (solo el host) y si
  venía `state`. Nunca la URL entera: lleva el código dentro.
- **`oauth_code_expired_unused`** avisa de los códigos que se emitieron y nadie
  presentó. Un código se borra en cuanto se toca el endpoint del token, con
  éxito o sin él, así que todo el que sobrevive hasta caducar es exactamente
  ese caso.

## [1.0.2] — 2026-09-06

### Fixed — Hermes anunciaba la versión equivocada

La pantalla de autorización, el endpoint `/health` y las tres líneas de arranque
del log decían **0.38.0** en una instalación de 1.0.1.

La versión está escrita a mano en dos sitios: `version:` en `config.yaml`, que
es lo que ve el Supervisor, y `__version__` en el paquete Python, que es lo que
Hermes enseña. El segundo seguía anunciando 0.38.0 mientras el primero subía
tres veces.

No afectaba al funcionamiento, pero sí a poder diagnosticar nada: tanto
`SECURITY.md` como `CONTRIBUTING.md` piden que digas qué versión ejecutas al
reportar un fallo, y el número que Hermes daba para eso era falso.

Los dos números no pueden derivarse uno del otro, porque `config.yaml` no viaja
dentro de la imagen —el `Dockerfile` copia solo `src/` y `run.sh`—. Así que la
sincronía la sostiene ahora un test, que falla si vuelven a separarse.

## [1.0.1] — 2026-09-06

### Fixed — El add-on se dejaba arrancar sin `auth_password` ni `public_hostname`

Las dos opciones estaban declaradas como obligatorias en el schema, pero
`options:` les daba `""` por defecto. Una cadena vacía es un valor **válido**
para los tipos `password` y `str`, así que el Supervisor las daba por
configuradas: el formulario no pedía nada y el botón de arrancar quedaba
disponible.

No era un agujero de seguridad —`run.sh` y `config.validate()` paran el arranque
si falta cualquiera de las dos, y siempre lo hicieron—, pero el error salía en
el log en vez de en el formulario, que es donde el usuario está mirando.

Ahora el schema exige longitud (`password(12,)` y `str(1,253)`) y `options:` las
deja en `null`, que es como se marca una opción obligatoria. El Supervisor
rechaza la configuración vacía antes de arrancar nada. El mínimo de 12 es el
mismo que aplica el código, y hay un test que comprueba que no se separen.

Se añaden siete tests del manifiesto, que hasta ahora no tenía ninguno: el
manifiesto lo valida el Supervisor, no Python, así que un error ahí no lo
detectaba nada y aparecía al instalar, en la máquina de otro. Uno de ellos
comprueba cada tipo del schema contra el regex real del Supervisor, porque un
tipo mal escrito hace que rechace el add-on entero.

## [1.0.0] — 2026-09-06

Primera versión publicada.

Hermes se desarrolló en privado desde abril de 2026. Las versiones anteriores no
llegaron a instalarse fuera de la máquina del autor —no hubo tags ni imágenes—,
así que no se documentan una a una: un changelog de esos cambios no le sirve a
nadie. Lo que sí conviene saber de cómo llega esta versión:

- **Auditoría de seguridad completa** sobre las 185 herramientas y los 54
  módulos, con verificación adversarial de cada hallazgo y un test de regresión
  por cada corrección. Endurecimiento en autenticación, límites de recursos,
  validación de rutas, redacción de secretos en logs y anotaciones MCP.
- **OAuth 2.1 con PKCE obligatorio**, registro dinámico de clientes, tokens
  opacos guardados solo como hash, y rotación de refresh tokens con detección de
  reutilización, tope de sesiones activas y caducidad que no se estira al rotar.
- **`auth_password` se comprueba, no solo se mide.** El login frena la fuerza
  bruta con un bloqueo global y escalonado que deja el techo de un atacante en
  unos 2.000 intentos al día, y que no se sube rotando de IP. Con ese techo una
  password generada al azar es inalcanzable, así que lo que se comprueba es que
  no sea *adivinable*: repeticiones, tiradas del teclado, listas de las más
  usadas y palabras del propio contexto. Las reglas siguen NIST SP 800-63B
  §5.1.1.2, y los umbrales están calibrados sobre 200.000 passwords generadas al
  azar para no rechazar ninguna legítima.
- **Confirmación en dos pasos** para las acciones destructivas: la primera
  llamada devuelve una vista previa y un token; sin ese token no se ejecuta
  nada. El token está atado a la acción y a sus argumentos, caduca, y vale una
  sola vez.
- **Denylist de servicios** aplicada en el cliente de Home Assistant, no en cada
  herramienta, para que no haya forma de rodearla. Clasificación automática de
  scripts y automatizaciones que invocan servicios peligrosos.
- **Sandbox de `/config`**: resolución de la ruta y contención comprobadas antes
  de aplicar cualquier regla, listas negras por nombre, patrón y directorio, y
  allowlist restrictiva para `.storage/`.

954 tests, con control negativo por cada guarda: se reintroduce el fallo y se
comprueba que el test lo detecta.
