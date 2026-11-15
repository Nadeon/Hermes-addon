# Investigación: plataforma y deprecaciones (027)

Fase 0 del plan. Todo se ha comprobado leyendo, sin ejecutar nada, el código
de Home Assistant Core **2026.11.1** y del Supervisor **2026.11.0**, el SDK
`mcp` **2.3.0** instalado en el entorno de desarrollo y el código de Hermes de
esta rama (la 011 hasta su tramo 3, sin la 009 ni la 010). Las rutas de HA y
del Supervisor son relativas a la raíz de su repositorio.

## R-0 — Alcance y correcciones a la 008

- **Alcance**: CAP-025, CAP-026 y CAP-028…CAP-033 (FR-092…FR-097 de la 008),
  ninguna de prioridad alta: todas son documentales, de preparación o de
  textos. Ninguna CAP pide una tool nueva; la 027 no añade tools, familias ni
  entradas `dedicated` en la tabla de la 011.
- **Corrección 1** (research R-0, punto 3, de la 008): el fichero del
  Supervisor que arranca las apps es `supervisor/docker/app.py`, no
  `docker/addon.py` (que ya no existe en 2026.11.0). Lo que dice la 008 sigue
  siendo cierto: `docker/app.py` inyecta `SUPERVISOR_TOKEN` (y el alias
  antiguo) pero no `SUPERVISOR_SOCKET`; `docker/homeassistant.py` sí lo inyecta
  a Core cuando `api.supports_unix_socket`.
- **Corrección 2** (FR-092 de la 008): «cualquier entrada en `errors` da
  `success: false`» solo vale para los errores del propio job; los de sus
  sub-jobs no suben (R-1). La 027 lo documenta, lo hace visible
  (`child_errors`) y, por decisión del supervisor (D-1), los cuenta en
  `success` y en el sondeo del safety backup.
- **Corrección 3** (CAP-029): `hermes/translations/` no existe; las
  «traducciones de las opciones» hay que crearlas (R-5).

## R-1 — Jobs del Supervisor: errores, avisos y sub-jobs (CAP-025)

**Hechos**:

- `supervisor/jobs/__init__.py`, `SupervisorJobError.as_dict()`: cada error
  lleva `type`, `message`, `stage`, `error_key` y `extra_fields`. **No hay
  gravedad**: el Supervisor no distingue un aviso de un error fatal.
- `SupervisorJob.capture_error` añade el error **al job actual**
  (`self.sys_jobs.current`). `supervisor/api/jobs.py`, `job_info` →
  `_list_jobs(job)`: la respuesta de `GET /jobs/{uuid}` es el job con
  `child_jobs` (lista recursiva con la misma forma); los errores de un hijo
  están en `child_jobs[i].errors` y **no** se copian al padre.
- `supervisor/backups/backup.py`, `store_apps` (job `backup_store_apps`):
  si guardar una app falla con `BackupError`, lo captura en ese sub-job y
  sigue con las demás; el backup completo termina y existe
  (`backups/manager.py` pone `reference = backup.slug`). Lo mismo con
  `_copy_to_additional_locations` (job `backup_copy_to_additional_locations`)
  para las copias a otras ubicaciones, y con las carpetas.
- Hermes (`tools/backups.py`, `sv_get_job_status`; `supervisor_jobs.job_errors`)
  calcula `success = not errores if done else None` con los errores del nivel
  superior. Con una app que no se pudo guardar, devuelve `success: true` y
  `errors: []`.
- `job_errors` lo usan también el sondeo del safety backup (`fs_write.py`) y la
  retención (`safety_retention.py`).

**Decisión** (revisada con D-1, decisión vinculante del supervisor del
programa): documentar en la descripción y en la guía lo que dice FR-092 de la
008 (sin gravedad, cualquier error → `false`, `done` también al fallar),
añadir `child_errors` con los errores de los sub-jobs **y contarlos en
`success`**: un backup completo con una app fallida daba `success: true`, y
eso miente. Es un arreglo, coherente con la 009 (cualquier error da
`false`), no un cambio de contrato. El sondeo del safety backup
(`fs_write.py`, `_evaluar_job`) también los cuenta como fallo (principio III:
no se escribe sin un backup válido). `job_errors` no cambia. La retención
(`safety_retention.py`) no lo olvida, porque el backup existe y tiene que
poder podarse, pero tampoco lo cuenta como copia buena: queda `incomplete`,
se poda el primero y no entra en las `keep` (corregido en la convergencia,
T030, por decisión del supervisor; antes esta decisión decía que la retención
no cambiaba).
La nueva función vive en `supervisor_jobs.py` junto a la existente.

**Alternativas descartadas**:

- Solo documentar «no se miran los sub-jobs»: la descripción sería cierta
  pero dejaría al agente sin forma de ver que a un backup le falta una app.
- No contar los errores de los sub-jobs en `success` (propuesta inicial de
  la 027): dejaba `success: true` en un backup incompleto. El supervisor lo
  descartó (D-1): un backup al que le falta una app no es un backup correcto,
  aunque exista y se pueda restaurar en parte.

**Topes**: 20 entradas y 5 niveles (un backup completo con muchas apps tiene
un sub-job por app dentro de `backup_store_apps`; 20 errores bastan para
decidir y el resto se indica con `child_errors_truncated`). Mensajes a 500
caracteres y `redact_secrets`, como `job_errors`. El nombre del sub-job
(`name`, un identificador interno como `backup_app_save`) se devuelve tal cual
si es texto; no contiene datos de la instalación.

## R-2 — Socket Unix del Supervisor (CAP-032)

**Hechos**:

- `supervisor/docker/homeassistant.py`, `run()`: con
  `self.sys_homeassistant.api.supports_unix_socket`, inyecta
  `SUPERVISOR_SOCKET=/run/supervisor/api/supervisor.sock` (`docker/const.py`:
  `PATH_RUN_API`, `const.py`: `SOCKET_NAME_SUPERVISOR`) y monta el directorio.
  `supervisor/docker/app.py` no inyecta nada parecido: **las apps no tienen
  socket en 2026.11.0**.
- `supervisor/api/sockets.py`: `SocketRegistry.register(principal, path)`
  escucha en un `web.UnixSite` y asocia cada socket a **un** principal; en el
  socket **no se lee ningún token** (`api/middleware/security.py`: «The socket
  identifies the caller, a token is never read on one»). Hoy solo se registra
  el de Core (`api/__init__.py`, `_listen_for_core`).
- `api/middleware/security.py`, `_report_tcp_api_request`: el aviso
  `deprecated_tcp_api_request` (y su issue de resolución) solo salta cuando el
  **token de Core** llega por TCP después de que Core haya usado el socket.
  Con el token de una app no se avisa de nada. Hermes no está afectado.

**Qué hará falta cuando se publique para apps** (para la hoja de ruta):

1. Conectar con `aiohttp.UnixConnector(path=SUPERVISOR_SOCKET)` y URL base
   `http://supervisor` (el host no se resuelve por DNS con el conector Unix).
   Sin cabecera `Authorization` en esas peticiones; el WebSocket de Core que
   usa Hermes (`/core/api/websocket`, por el proxy del Supervisor) seguiría
   pidiendo el token en el mensaje `auth`.
2. Caída a TCP si el socket no existe o no responde a `/supervisor/ping`, y
   el arranque igual que hoy.
3. Revisar qué rutas permite el principal «app» por el socket
   (`check_principal_access`, mismos patrones que por TCP) y la redacción de
   red del log (no hay IP en el socket).
4. Tests con un servidor aiohttp en un socket Unix (solo Linux: marcar como
   omitido en Windows o probar con un conector simulado, para no depender del
   sistema).

**Decisión para la 1.2.0**: solo detectar `SUPERVISOR_SOCKET` (no vacío) y
avisar; nunca usarlo. Si un Supervisor futuro lo inyecta, Hermes sigue por
TCP, que el Supervisor mantiene (el aviso de deprecación es solo para Core).

## R-3 — API `/v2` del Supervisor (CAP-033)

**Hechos**:

- `supervisor/api/__init__.py`, `load()`: `v2_enabled =
  self.sys_config.feature_flags.get(FeatureFlag.SUPERVISOR_V2_API, False)`;
  la V1 se registra **siempre** en la raíz y la V2 se monta como sub-app en
  `/v2` solo con la opción. Activar la V2 no quita la V1.
- `supervisor/const.py`, `FeatureFlag`: `app_drop_net_raw`,
  `app_reduced_capabilities`, `supervisor_v2_api`,
  `supervisor_websocket_v2_api` («Development features that can be toggled»).
- `supervisor/api/supervisor.py`, `_info_data()` (común a V1 y V2):
  `feature_flags` con todas las opciones y su valor. `GET /supervisor/info` es
  la ruta que ya usa `sv_get_supervisor_info`; con `hassio_role: admin`
  siempre está permitida.
- `api/utils.py`: en la V1 algunas claves de error se traducen a sus nombres
  antiguos (`app_not_supported_*` → `addon_not_supported_*`); en la V2 no.
- `api/middleware/security.py`: la V2 tiene sus propios patrones de rol
  (`_V2_PATTERNS`), con las mismas reglas sobre rutas `/v2/...`.

**Rutas que usa Hermes y su equivalente en la V2** (de `_register_*` en
`api/__init__.py`):

| Hermes (V1) | V2 | Cambio de formato en la V2 |
|---|---|---|
| `GET /supervisor/info` | `GET /v2/supervisor/info` | `info` en vez de `info_v1`: sin `addons` ni `wait_boot` |
| `GET /info`, `GET /host/info`, `GET /core/info` | igual con `/v2` | `host/info`: `info` en vez de `info_v1` |
| `GET /addons` | `GET /v2/apps` | lista de apps (`list_apps` frente a `list_apps_v1`) |
| `GET /store/addons` | `GET /v2/store/apps` | `apps_list` frente a `apps_list_v1` |
| `GET /addons/{slug}/info` | `GET /v2/apps/{app}/info` | solo apps instaladas: la V1 caía al catálogo (`apps_app_info`) si no estaba instalada; en la V2 hay que ir a `GET /v2/store/apps/{app}` |
| `GET /addons/{slug}/stats` | `GET /v2/apps/{app}/stats` | `stats` frente a `stats_v1` |
| `GET /addons/{slug}/logs` | `GET /v2/apps/{app}/logs` | mismo texto |
| `POST /addons/{slug}/start|stop|restart|options|uninstall` | `POST /v2/apps/{app}/…` | — |
| `POST /store/addons/{slug}/install|update` | `POST /v2/store/apps/{app}/install|update` | — |
| `GET /backups`, `GET /backups/{slug}/info` | igual con `/v2` | contenido con la clave `apps` en vez de `addons` |
| `POST /backups/new/full|partial`, `POST /backups/{slug}/restore/full|partial` | igual con `/v2` | `partial`: cuerpo con `apps` en vez de `addons` |
| `DELETE /backups/{slug}` | igual con `/v2` | — |
| `GET /jobs/{id}` | igual con `/v2` | — |
| `GET /resolution/info`, `DELETE /resolution/{clase}/{uuid}` | igual con `/v2` | `info` frente a `info_v1` |
| `POST /core/check|restart`, `POST /host/reboot` | igual con `/v2` | — |
| `GET /addons/self/options/config` (bashio, `run.sh`) | `GET /v2/apps/self/options/config` | — (lo usa bashio, no Hermes) |

**El test de deriva** (FR-005 de la 008; `scripts/inventario/extraer.py`,
`_rama_v1`) extrae **solo la V1**: sigue las ramas `if app is
self.versions[AppVersion.V1]` y descarta las de la V2. Avisa si una versión
del Supervisor quita o cambia rutas de la V1 (lo que pasará si algún día se
retira), pero no ve las rutas nuevas de la V2. La activación de la V2 en una
instalación la ve la detección de FR-011. Un inventario de la V2
(`supervisor-rutas-v2.tsv`, con un modo del extractor) queda como duda D-4:
no tiene sentido mantenerlo mientras la V2 sea una opción de desarrollo.

**Decisión para la 1.2.0**: leer `feature_flags.supervisor_v2_api` una vez al
arrancar y avisar si está activa; Hermes sigue con la V1, que está montada
igual. Nada va a `/v2`.

## R-4 — Deprecaciones de Core con fecha (CAP-030 y relacionadas)

**Hechos** (Core 2026.11.1):

- `components/config/device_registry.py`,
  `websocket_remove_config_entry_from_device`: «The websocket command
  config/device_registry/remove_config_entry is deprecated and will be removed
  in Home Assistant 2027.9; use …». Cuando se retire, HA responderá
  `unknown_command` (`websocket_api`, comando no registrado), como en otros
  comandos que Hermes ya traduce (`tools/ha_backups.py`, `tools/lovelace.py`,
  `tools/marketplace.py`, `tools/generic_commands.py`).
- `helpers/device_registry.py`, `dict_repr`: `config_entries` y
  `config_entries_subentries` «can be removed in HA Core 2027.8»;
  `primary_config_entry` «can be removed in HA Core 2027.10».
- Hermes: `tools/registry_device.py`, `device_config_entries` une
  `config_entry_id` (el vigente) y `config_entries` (respaldo); la usan
  `tools/config_entries.py` (`_count_config_entry_dependents`, vistas previas
  de `ha_disable_config_entry` y `ha_delete_config_entry`) y el plan de
  `ha_remove_device`. Ningún fichero de Hermes lee `primary_config_entry` ni
  `config_entries_subentries`.
- `ha_remove_device_from_config_entry`: descripción «DEPRECATED: usa
  ha_remove_device. Se retirará antes de HA 2027.9», vista previa con
  `deprecated: true`, `replacement` y el aviso con 2027.9
  (`tests/test_tools_registry_device.py` ya lo comprueba). Al confirmar, un
  `unknown_command` hoy sale como `{"error": "<texto de HA>"}`.

**Decisión**: traducir `unknown_command` (por `HAConnectionError.code`, nunca
por el texto) a `command_removed_in_ha` con la sustituta, sin reintentar con
`config/device_registry/remove` (el token se dio para «quitar la asociación»
y la vista previa no anunció otro efecto, principio IV). No se decide nada por
número de versión de HA: si HA aplaza la retirada, la tool sigue funcionando.
Para los campos de 2027.8 y 2027.10 basta con fijar con tests la forma futura
(sin los campos): el código ya está preparado desde la 1.0.12.

**Alias `ha_hacs_*`** (`tools/hacs.py`, `_REMOVED_IN = "1.3.0"`): devuelven
la respuesta de su sustituta más `_deprecated`; `tests/test_tools_hacs.py` lo
comprueba. La 027 solo añade la comprobación de que siguen registrados con las
mismas anotaciones (FR-020 de la 008).

**Otras deprecaciones comprobadas** (sin efecto en Hermes, para la tabla de la
hoja de ruta):

- Parámetros de `async_get_or_create` (`via_device` en 2027.8; `default_*`,
  `created_at`, `modified_at` en 2027.9): son de integraciones, no de la API.
- `hassio`: el alias de carpeta `homeassistant` en backups parciales rompe en
  2026.12 (`components/hassio/services.py`, `breaks_in_ha_version`); afecta a
  las acciones `hassio.backup_partial`/`restore_partial`, que van por la
  denylist con token. Hermes usa la API del Supervisor, no esas acciones.
- `hassio` tiene acciones `app_*` además de `addon_*`; las dos están en la
  denylist (`service_policy.py`). No hay fecha de retirada de las `addon_*` en
  el código.

## R-5 — Traducciones de las opciones y término «app» (CAP-029)

**Hechos**:

- `supervisor/store/data.py`, `_read_app_translations`: lee
  `translations/*.{json,yaml,yml}` junto a `config.yaml` y valida cada fichero
  con `SCHEMA_APP_TRANSLATIONS` (`apps/validate.py`):
  `configuration: {str: {name: str (obligatorio), description: str|null,
  fields: {…}}}` y `network: {str: str}`, `extra=REMOVE_EXTRA`. Un fichero que
  no valida se ignora con un aviso en el log del Supervisor; no impide
  instalar ni arrancar.
- El Supervisor 2026.11.0 llama «apps» a lo que antes eran add-ons (paquete
  `apps/`, rutas `/apps` de la V2, `App`, acciones `hassio.app_*` en Core,
  selector `app:` en `services.yaml`).
- Hermes no tiene `translations/`: la interfaz enseña los nombres crudos
  (`response_max_bytes`…) y las descripciones solo están en `DOCS.md` y en los
  README.
- Las tools `sv_*addon*` (doce en `tools/addons.py`) dicen «add-on» en su
  descripción; el tema `supervisor` de la guía y el apartado 4 de las
  instrucciones del servidor, también.

**Decisión**: crear `translations/en.yaml` y `translations/es.yaml` con
`configuration` (nombre y descripción de cada una de las 31 opciones del
esquema) y textos derivados de `DOCS.md`. La sección `network` (descripción de
los puertos) queda fuera: no la pide CAP-029 y los dos puertos ya se explican
en `DOCS.md`. En las descripciones de las tools de apps,
la guía y las instrucciones, «app» con «(add-on)» la primera vez. Ningún
nombre de tool ni de argumento cambia (`slug` sigue siendo `slug`). El resto
de textos de Hermes que dicen «add-on» no se tocan (principio IX).

**Test**: el test lee `config.yaml` (`schema`) y cada traducción con PyYAML y
comprueba la forma (sin importar nada del Supervisor), que las claves
coinciden una a una y que no aparece «add-on»/«addon». El esquema de
traducciones del Supervisor se copia en el test como estructura esperada, con
el fichero de origen en un comentario.

## R-6 — `outputSchema`, la vía nativa de MCP y el SDK (CAP-028)

**Hechos** (SDK `mcp` 2.3.0, que implementa MCP 2026-07-28; no se ha leído el
texto de la especificación):

- `Tool.outputSchema` es opcional. `MCPServer.add_tool`/`tool()`
  (`mcp/server/mcpserver/server.py`) acepta `structured_output`; con `None`,
  lo infiere de la anotación de retorno. Medido registrando las 221 tools de
  esta rama en un `MCPServer` real: **solo `ping` y `hermes_guide`** declaran
  `outputSchema` (`{"result": string}`, inferido de `-> str`); el resto
  devuelve `object` y no declara nada.
- `mcp_server.py`, `_limitar`: cuando recorta, pone `structured_content` a
  `None`. Si alguna vez se recortara `ping` o `hermes_guide` (sus respuestas
  son pequeñas: hoy no pasa), el resultado tendría `outputSchema` declarado y
  sin contenido estructurado. Se anota como duda D-3, no se cambia.
- **Qué daría `outputSchema` a Hermes**: el cliente podría validar las
  respuestas y algunos lo usan para presentar datos. **Coste**: cada tool
  pasaría a devolver el JSON dos veces (texto y `structuredContent`, salvo que
  se omita el texto, que rompería a los clientes que solo leen texto), el
  tamaño de `tools/list` crecería (D-04 de la 008) y las respuestas de Hermes
  no tienen una forma única por tool (errores `{"error": …}`, vistas previas
  con `confirmation_token`, listas recortadas): el esquema tendría que ser una
  unión que no aporta validación real. **Recomendación**: no declararlo en la
  1.2.0; reconsiderarlo solo para las tools nuevas con sobre común
  (`{count, items, truncated}`) en una versión posterior.
- **Vía nativa para pedir datos a mitad de una llamada**: `InputRequiredResult`
  con `inputRequests` y `requestState` (MCP 2026-07-28), y la elicitación
  (`ctx.elicit`, `elicit_url`) en `mcp/server/mcpserver/context.py` y
  `mcp/server/elicitation.py`. En HTTP sin estado, el servidor devuelve
  `InputRequiredResult` y el cliente repite la llamada con las respuestas y el
  `requestState`, que el SDK sella con AES-GCM ligado al principal
  autenticado (`mcp/server/request_state.py`, `RequestStateBoundary`).
- **Qué daría como confirmación**: el cliente enseñaría la vista previa y
  pediría el «sí» al humano con su propia interfaz, en vez de que el modelo
  repita la llamada con el token. **Por qué no sustituye a los dos pasos**:
  depende de que el cliente lo implemente (no se puede contar con ello), el
  token de Hermes ya está atado a la tool y a los argumentos (1.1.2) y lo usan
  todas las tools destructivas; con dos caminos, cada tool tendría que
  probarse en los dos. **Recomendación**: segunda vía opcional en una versión
  posterior, detrás de la capacidad del cliente, con el mismo token por
  debajo (D-10 de la 008; duda D-5 aquí).
- **SDK y deprecaciones**: `mcp_types/version.py` marca como deprecada
  `SUPPORTED_PROTOCOL_VERSIONS` («Kept as the union for v1.x compatibility»).
  `middleware.py` usa ya `HANDSHAKE_PROTOCOL_VERSIONS` y
  `MODERN_PROTOCOL_VERSIONS` desde la spec 003, y
  `tests/test_middleware_connection.py::test_middleware_does_not_use_the_deprecated_alias`
  lo vigila en ese módulo. La fila «Constante de versiones de protocolo
  admitidas del SDK» de la hoja de ruta («Puede romper con un futuro SDK 3.x»)
  está desfasada. `requirements.txt` fija `mcp>=2,<3`.

- **Cómo avisa el SDK**: con `MCPDeprecationWarning`
  (`mcp/shared/exceptions.py`), que **hereda de `UserWarning`, no de
  `DeprecationWarning`**: un filtro solo de `DeprecationWarning` no lo vería.
  Lo emiten, entre otros, `Context.log` y `ServerConnection.log` (capacidad de
  logging deprecada en 2026-07-28, SEP-2577), el `__init__` deprecado de
  `lowlevel.Server` y `AuthSettings` sin `validate_token_resource`. Hermes no
  usa ninguno (`grep` de `AuthSettings`, `.log(` sobre un contexto y
  `lowlevel` en `hermes/src`: sin resultados); usa `ctx.report_progress`, que
  no está deprecado.

**Decisión**: research y hoja de ruta (FR-004); un test que fija qué tools
declaran `outputSchema` hoy; una guarda general de deprecaciones del SDK
(FR-005): importar los módulos de Hermes (salvo `__main__`), registrar todas
las tools en un `MCPServer` real con `_build_mcp`, listar las tools y llamar a
`ping`, todo con `warnings.catch_warnings(record=True)` y
`simplefilter("always")`, y fallar si aparece un `MCPDeprecationWarning` o un
`DeprecationWarning`/`PendingDeprecationWarning` cuyo fichero de origen esté
en `mcp`, `mcp_types` o `hermes`; más la búsqueda de
`SUPPORTED_PROTOCOL_VERSIONS` en todo `hermes/src` (hoy solo se vigila
`middleware.py`) y la comprobación del tope `<3` en `requirements.txt`. El
control negativo: emitir un `MCPDeprecationWarning` desde `tools/ping.py` al
registrar y ver el test en rojo.

## R-7 — Hosts CIMD conocidos (CAP-026)

**Hechos**:

- `docs/HOJA-DE-RUTA.md`, pruebas en vivo de la 1.1.0: «claude.ai inicia
  sesión con CIMD con su documento en el host `claude.ai`; si solo usas
  Claude, `oauth_cimd_allowed_hosts: ["claude.ai"]` basta».
- `hermes/DOCS.md` y los README: `claude.ai` es donde publica su documento
  Claude Code; la prueba en vivo de CIMD con Claude Code sigue pendiente.
- No hay en el repositorio ningún otro host CIMD comprobado. El evento
  `oauth_cimd_document` (`cimd.py`) registra el host de cada documento
  resuelto, y `oauth_cimd_rejected` con `host_not_allowed` dice cuál faltaba.
- `config.yaml`: `oauth_cimd_allowed_hosts: []`; `config.py`:
  `field(default_factory=list)`.

**Decisión**: la hoja de ruta lista `claude.ai` (comprobado con claude.ai;
documentado para Claude Code, prueba pendiente) y explica cómo averiguar el
host de otro cliente con esos eventos. No se añade ningún host sin
comprobarlo. El valor por defecto no cambia; un test lo fija en `config.yaml`
y en la configuración cargada. El valor por defecto restrictivo sigue siendo
D-09 de la 008.

## R-8 — Tabla «Deprecaciones con fecha» de la hoja de ruta (FR-013)

Filas que cambian (el resto queda como está):

| Fila | Cambio |
|---|---|
| `config_entries`/`config_entries_subentries` (2027.8), `primary_config_entry` (2027.10) | Añadir el test que fija la forma futura (FR-010) |
| `config/device_registry/remove_config_entry` (2027.9) | «Se retira como tarde en la última versión de Hermes publicada antes de HA 2027.9 (D-08). Desde la 1.2.0, si HA ya no tiene el comando, la tool devuelve `command_removed_in_ha` con `ha_remove_device`» y el test |
| Acceso TCP de las apps (socket Unix) | Añadir: «Desde la 1.2.0 Hermes detecta `SUPERVISOR_SOCKET` al arrancar y lo anota en el log; sigue por TCP» y el test |
| API `/v2` del Supervisor | Añadir: «Desde la 1.2.0 Hermes detecta la opción `supervisor_v2_api` al arrancar y lo anota; sigue con la V1, que no se retira al activarla», el enlace a la tabla de rutas y el test |
| Alias `ha_hacs_*` (1.3.0) | Añadir el test que los fija en la 1.2.0 |
| Constante de versiones de protocolo del SDK | «Ninguno: el middleware usa las dos tuplas nuevas desde la spec 003; la suite falla si Hermes usa algo deprecado del SDK (027)» |
| Fila nueva: alias de carpeta `homeassistant` en backups parciales de `hassio` | HA **2026.12**; ninguno (Hermes usa la API del Supervisor; las acciones van por la denylist) |

## R-9 — Hallazgos fuera de alcance (para el informe, no se tocan)

- `tools/config_entries.py`, `_count_config_entry_dependents`:
  `entry_id in (e.get("config_entry_id") or "")` compara por **subcadena**
  sobre un texto: un `entry_id` que fuera subcadena del de otra entrada
  contaría entidades ajenas en la vista previa. Con los ids de HA (ULID de 26
  caracteres) no se da en la práctica; corregirlo es de quien toque esas
  vistas previas (018 o el cierre).
- `tests/banco` (010) no sirve `/supervisor/info` en su Supervisor simulado;
  FR-011 lo tolera (S-03).

## R-10 — Tramos

La 008 la estima en un tramo (S). Con el código (FR-002, FR-009, FR-011 y las
guardas de FR-004, FR-005, FR-008 y FR-010) y los textos (dos traducciones de
31 opciones, doce descripciones, guía, `DOCS.md`, dos README, hoja de ruta,
CHANGELOG y matriz) un solo agente iría justo de contexto. Se parte en dos
tramos cortos, independientes en ficheros: **A** (código y tests) y **B**
(textos, traducciones y documentación). B no depende de A salvo en la
documentación final (CHANGELOG y hoja de ruta citan los tests de A).
