# Research: configuración del sistema (021)

Todo lo de HA sale de leer el código de Core 2026.11.1 de la carpeta de
fuentes (sin ejecutar nada). Las rutas son relativas a `homeassistant/`.

## R-0 — Punto de partida en Hermes

- Rama `feat/021-configuracion-del-sistema` desde `feat/cobertura-total`
  (`c4a57bf`), con la 009, 010, 011, 028, 014, 013, 018, 029, 012, 033 y 027
  integradas. Línea base en Windows (2026-11-15): 2926 passed, 95 skipped,
  6 failed (los 6 conocidos).
- Tabla (`command_table.py`): los doce comandos de esta sub-feature y
  `config/core/detect` y `auth/refresh_tokens` están en `deny` «pendiente de
  tool dedicada (spec 021)». `analytics`, `labs/list` (`read`),
  `analytics/preferences` y `labs/update` (`confirm`) los dejó revisados la
  011 con `cap="CAP-074"`. `network`, `network/url` y `http/config` son
  `read` (CAP-068, 029). `config/auth_provider/homeassistant/*` y los `auth/*`
  de credenciales son `deny` clase D.
- El mecanismo para pasar a `dedicated` ya existe (012 y 029): clave en
  `_DEDICADAS_INICIALES` del generador; `_clasificar` lo consulta para la
  clase A antes de la regla «pendiente»; `test_clase_a_de_via_dedicada_pendiente_de_su_spec`
  admite `dedicated` hacia una tool de una familia de la 1.2.0 y, por
  `_POR_LA_TABLA`, `read`/`confirm` de una clave con su spec y su porqué.
- Confirmación en dos pasos: `create_confirmation_token`,
  `resolve_confirmation_token` y, desde la 018, el argumento `estado` que ata
  el token al estado leído en la vista previa (`ESTADO_CAMBIADO` si cambia).
- Bloqueo de reinicio: `fs_write.check_restart_allowed_sync()`, que usa
  `sv_restart_core` (configuración escrita por Hermes sin validar después →
  se niega hasta `sv_check_core_config`).
- Inventarios que hay que alimentar: matriz de la 014
  (`tests/test_matriz_pruebas.py`), argumentos atados de la 033
  (`tests/test_confirmation_args_inventory.py`), `allow_dangerous` de la 018
  (sin cambios: nada llama a `call_service`), invariante de escrituras de la
  028 (`tests/test_banco_cobertura_escrituras.py`, con un módulo
  `tests/banco/cobertura_<NNN>.py` por sub-feature, como `cobertura_012.py`).

## R-1 — Configuración del núcleo (`config/core.py`, `core_config.py`)

- `config/core/update` (admin): `country` (`cv.country`), `currency`
  (`cv.currency`), `elevation` (int), `external_url` e `internal_url`
  (`cv.url_no_path` o `None`), `language` (`cv.language`), `latitude`,
  `longitude`, `location_name`, `radius` (`cv.positive_int`), `time_zone`
  (str, validado dentro), `update_units` (bool) y `unit_system`
  (`validate_unit_system`). Responde sin datos; `ValueError` →
  `invalid_info`.
- `Config._async_update` aplica campo a campo en memoria y la zona horaria
  casi al final (`async_set_time_zone` lanza `ValueError` si no existe);
  `async_update` guarda y dispara `core_config_updated` **después**. Una zona
  inválida deja en memoria lo anterior a ella sin guardar: por eso Hermes
  manda la zona sola y primero (casos límite de la spec). Los errores de
  esquema los rechaza el WebSocket antes de llamar al manejador: son atómicos.
- `_async_update` pone `config_source = storage`; al arrancar, una
  configuración en `configuration.yaml` (`homeassistant:`) vuelve a mandar
  (`config_source = yaml`). El banco la tiene en YAML: sirve para probar el
  aviso.
- `unit_system` desconocido en `_async_update` → métrico en silencio (el
  esquema ya lo valida; Hermes también, para dar un error claro).
- `update_units=True` → `async_update_suggested_units`: cambia la unidad
  sugerida de los sensores (afecta a estadísticas a largo plazo).
- `get_config` (`as_dict`) devuelve los campos, `config_source`, `version`,
  `state`, `components` y más; `ha_get_core_config` se queda con los
  editables para que el antes de la vista previa sea legible.
- `config/core/detect` llama a `location_util.async_detect_location_info` con
  la sesión HTTP de HA (servicio externo de geolocalización por IP) y no
  guarda nada: `read` con `open_world=True` (FR-071 de la 008).

## R-2 — Exposición a asistentes (`homeassistant/exposed_entities.py`)

- `KNOWN_ASSISTANTS = ("cloud.alexa", "cloud.google_assistant",
  "conversation")`. `conversation` es Assist y lo que lo usa: agentes
  conversacionales (también los de LLM en la nube) y la API de LLM de HA que
  usa la integración MCP Server. `cloud.*` sincronizan con Amazon y Google a
  través de Home Assistant Cloud cuando la nube está activa; si no, HA guarda
  la preferencia igual.
- `homeassistant/expose_entity` (admin): `assistants` (lista de los tres),
  `entity_ids` (lista de str, sin validar), `should_expose`. Devuelve
  `changed_entity_ids`. Para un id sin entrada de registro ni entrada
  heredada, `async_expose_entity` crea una entrada heredada: un error de
  escritura deja basura. Hermes exige que el estado exista.
- `homeassistant/expose_entity/list`: solo las expuestas (`{entity_id:
  {assistant: true}}`); las ocultas no salen.
- `expose_new_entities/get|set` por asistente.
- Las cuatro son `@callback` y responden en el acto.

## R-3 — Por qué no hay `ha_get_expose_new_entities`

Research R-2 de la 008 la proponía. Es una lectura de un booleano por
asistente, de la misma clase de riesgo que la lista; la 008 permite agrupar
(Clarificaciones, tercera decisión al especificar). `ha_list_exposed_entities`
la incluye como cabecera `expose_new` (tres `ws_send` cortos). Una tool menos
en el contexto del cliente (D-04 de la 008).

## R-4 — Usuarios (`config/auth.py`)

- `config/auth/list` (admin): `_user_info` → `id`, `username` (de la
  credencial `homeassistant`, si la hay), `name`, `is_owner`, `is_active`,
  `local_only`, `system_generated`, `group_ids`, `credentials` (solo
  `type`). Ningún secreto.
- `config/auth/create`: `name` (obligatorio), `group_ids`, `local_only`; crea
  el usuario **sin credenciales** (la interfaz llama después a
  `config/auth_provider/homeassistant/create`, clase D). Devuelve `{user}`.
- `config/auth/update`: `user_id`, `name`, `is_active`, `group_ids`,
  `local_only`. HA rechaza: `not_found`, `cannot_modify_system_generated`,
  `cannot_deactivate_owner` (y solo eso del propietario: dejaría cambiarle
  nombre o grupos).
- `config/auth/delete`: HA rechaza borrarse a uno mismo (`no_delete_self`),
  `not_found`, usuarios de sistema y el propietario.
- Administrador: el propietario siempre; el resto, activo y con
  `system-admin` (modelo de `homeassistant/auth/models.py`, que no está en la
  copia de fuentes; se comprueba en el banco). Grupos de HA:
  `system-admin`, `system-users`, `system-read-only`.
- Usuario de Hermes: en producción, el Supervisor autentica la WebSocket del
  add-on contra Core con su propio token, el del usuario de sistema
  «Supervisor» que crea `hassio` (`system_generated`, admin). En el banco, el
  token del onboarding (el propietario). `auth/current_user` lo identifica en
  los dos casos.
- Protecciones de Hermes por encima de las de HA (defensa en profundidad y un
  error claro antes de llamar): propietario (HA deja renombrarlo o quitarle
  grupos), usuario de Hermes (HA solo impide borrarlo; desactivarlo o
  quitarle admin cortaría a Hermes), usuarios de sistema (HA ya los rechaza)
  y último administrador. Con el propietario intocable y siempre activo, el
  último administrador no debería darse nunca; la comprobación se queda
  (fail-closed) y se prueba en unitarios.
- `person` escucha `EVENT_USER_REMOVED` y quita el `user_id` de la persona
  vinculada (`person/__init__.py`, `_handle_user_removed`): la vista previa de
  borrar lo dice.

## R-5 — `auth/refresh_tokens` y las sesiones

`websocket_refresh_tokens` (`auth/__init__.py`) recorre
`connection.user.refresh_tokens`: solo los tokens del usuario de la conexión,
con `last_used_ip`, `client_id` e `is_current`. No hay comando para listar
los de otro usuario. Con Hermes, eso son las credenciales del usuario por el
que entra Hermes (el del Supervisor en producción), igual que
`auth/current_user`, que la 011 dejó en clase B («es el propio token de
Hermes»). Una tool `ha_list_user_sessions` mentiría en su nombre. Decisión:
`deny` con el motivo revisado y la clave en una excepción documentada del test
de la clase A (`_DENY_TRAS_REVISION`, mismo patrón que `_POR_LA_TABLA`); el
inventario de la 008 no se toca (sus recuentos están fijados por tests).
Desviación de FR-073 de la 008, duda D-1.

## R-6 — HTTP de Core (`http/websocket_api.py`, `http/config.py`)

- Desde 2026.11 la configuración HTTP vive en almacenamiento con dos huecos:
  `stable` (la que funciona) y `pending` (sin confirmar). `http/config`
  devuelve `stable`, `pending`, `revert_at`, `active_config_type`
  (`stable`, `pending`, `default`, `default_legacy_port`) y `default`.
- `http/config/configure` (admin): `config` = documento completo validado con
  `HTTP_STORAGE_SCHEMA` (rellena por defecto `server_port`,
  `cors_allowed_origins`, `login_attempts_threshold`, `ip_ban_enabled`,
  `ssl_profile`, `use_x_frame_options`; certificados con `cv.isfile`;
  `trusted_proxies` como redes IP) y `_validate_trusted_proxies`
  (`use_x_forwarded_for` sin proxies → inválido), o `None` (borra lo
  pendiente). Exige `CoreState.running` (`not_running`). Si cambia el puerto,
  prueba a enlazarlo (`bind_failed`); si cambian los hosts, comprueba que no
  se pisan. Guarda como pendiente, responde `{restart}` y, si lo pendiente
  cambió, llama a `homeassistant.restart`.
- Metadatos `created_at`, `error`, `error_message` van en lo guardado pero
  no en el esquema: hay que quitarlos al fundir.
- Prueba: al arrancar con lo pendiente, HA programa la vuelta a lo estable a
  los 5 minutos (`AUTO_REVERT_DELAY`) y reinicia si nadie promueve; si lo
  pendiente no se puede aplicar, registra el error en él y vuelve a lo
  estable.
- `http/config/promote`: lo pendiente pasa a estable (la de recuperación);
  sin pendiente o con error, `not_allowed`.
- `homeassistant.restart` (`homeassistant/services.py`) comprueba
  `configuration.yaml` y se niega si no es válida (después de que
  `configure` haya respondido): lo pendiente queda guardado y se aplicará en
  el siguiente reinicio. Hermes, además, respeta su propio bloqueo de reinicio
  (R-0).
- `hassio/__init__.py` (`update_hass_api`) comunica al Supervisor el puerto y
  el SSL de Core al arrancar: Hermes, que entra por el Supervisor, sobrevive a
  un cambio de puerto. Lo que puede cortarle el acceso es `server_host` sin la
  dirección de la red interna por la que el Supervisor llega a Core (aviso;
  duda D-3) o un certificado que el Supervisor no acepte (aviso).

## R-7 — Red de Core (`network/websocket.py`, `network/network.py`)

- `network/configure` (admin): `config.configured_adapters` (lista de
  nombres). `async_reconfig` guarda y recalcula los habilitados; lista vacía
  o sin coincidencias → detección automática. Responde los configurados.
- Afecta a qué interfaces usa HA para descubrimiento (zeroconf, SSDP…) y qué
  direcciones anuncia; no al enlace del servidor HTTP. No corta el acceso a la
  interfaz ni a Hermes.
- `config/core/detect`: ver R-1. Va por `_POR_LA_TABLA` con «spec 021:
  FR-071 de la 008 la deja `read` en la tabla; consulta un servicio externo de
  geolocalización y no guarda nada».

## R-8 — Banco de Core

- La conexión de Hermes en el banco es el propietario (token del
  onboarding a través del Supervisor simulado). Con eso se prueban en real
  las dos protecciones (propietario y Hermes) sobre el mismo usuario y todo el
  ciclo de un usuario creado por la tool (crear, renombrar, dar admin,
  quitarlo, desactivar, borrar), comprobado por el lector con
  `config/auth/list` directo a Core.
- Núcleo: `location_name` y `radius` (efecto visible y sin consecuencias
  para otros tests), restaurados en `finally`. El banco tiene la ubicación en
  YAML: la vista previa debe llevar el aviso `yaml`.
- Exposición: un `input_boolean` creado por el lector, expuesto a
  `conversation` y a `cloud.alexa` (sin nube cargada, HA guarda la
  preferencia), comprobado con `expose_entity/list` directo; `expose_new` de
  `conversation` cambiado y restaurado.
- Red: `ha_update_network_config` con los nombres de los adaptadores que el
  lector lee de `network` (habilitados), comprobado y restaurado a la lista
  previa. No toca el enlace HTTP.
- HTTP: aplicar reinicia la HA del banco (el job la perdería); promover exige
  una pendiente, que exige ese reinicio. En el banco: la vista previa real de
  `ha_update_http_config` (documento fundido sobre la configuración real y sus
  avisos) con el lector comprobando que `http/config` no cambió, y
  `ha_promote_http_config` real devolviendo `nothing_to_promote`. Las dos van a
  `NO_EJECUTABLES_021` con ese motivo; en la matriz de la 014, VM pendiente.
- CAP-074: `analytics` y `labs/list` por `ha_read_ws_command`;
  `analytics/preferences` con `{"base": false}` (el valor de un banco recién
  hecho; no activa el envío) por `ha_call_ws_command` en dos pasos;
  `labs/update` con la primera función de `labs/list` si hay alguna (activar
  y volver a desactivar, sin `create_backup`) o, si la lista está vacía, su
  `not_found` real. El contenedor no tiene salida a internet.
- `config/core/detect` por `ha_read_ws_command`: sin salida a internet HA
  devuelve `{}`; se comprueba la forma, no el contenido.

## R-9 — Familias, guía y anotaciones

- Cuatro familias por área y por riesgo, para que quien quiera apagar lo de
  riesgo alto (usuarios, red y HTTP) lo haga sin perder el resto:
  `core_config` («Core configuration: location, units, time zone, currency,
  language and URLs»), `assistant_exposure` («Which entities voice
  assistants and conversation agents can see and control»), `users` («Home
  Assistant users: list, create without credentials, edit and delete; never
  passwords or tokens») y `core_network` («Core network adapters and HTTP
  server configuration»). Nombres distintos de las de la 1.1.2 y de la red
  del host (032).
- Temas de la guía con el mismo nombre. Alias: `location`, `units`,
  `time_zone`, `analytics`, `labs` → `core_config`; `exposure`, `expose`,
  `voice`, `assist` → `assistant_exposure`; `user`, `accounts` → `users`;
  `http`, `ssl`, `port`, `proxy` → `core_network`. El alias `network` (hoy en
  `system_status`) pasa a `core_network`, que remite a la lectura;
  `urls` sigue en `system_status`. El texto de `system_status` sobre la red
  cambia (la 029 lo dejó dicho) y su test se actualiza; ninguna huella de la
  013 cambia (los temas con huella no se tocan).
- Anotaciones: `ha_get_core_config`, `ha_list_exposed_entities` y
  `ha_list_users` por prefijo (`R-I-`). Destructivas por nombre exacto (piden
  token: invariante de registro) `ha_update_core_config`,
  `ha_set_entity_exposure`, `ha_set_expose_new_entities`, `ha_create_user`,
  `ha_update_user`, `ha_update_network_config`, `ha_update_http_config` y
  `ha_promote_http_config`; `ha_delete_user` por prefijo. De mundo abierto
  `ha_set_entity_exposure` y `ha_set_expose_new_entities`. `ha_create_user`
  no idempotente por prefijo.

## R-10 — Analytics y labs (`analytics/__init__.py`, `labs/websocket_api.py`)

- `analytics` (admin, lee), `analytics/preferences` (`PREFERENCE_SCHEMA`:
  `base`, `snapshots`, `diagnostics`, `statistics`, `usage`; guarda y
  reprograma el envío). Activar `base` hace que HA mande datos a los
  servidores de Home Assistant: `open_world=True` en la entrada.
- `labs/list`: funciones en pruebas de las integraciones cargadas y si están
  activas. `labs/update`: `domain`, `preview_feature`, `enabled`,
  `create_backup` (backup automático antes de activar); `not_found` si no
  existe. Local.
- `analytics` y `labs` están en `DEFAULT_INTEGRATIONS` (`bootstrap.py`): se
  cargan en el banco sin `default_config:`.

## R-11 — Log y privacidad

- El log de las tools: nombre, `paso` (`preview`/`confirm`), resultado y
  recuentos o nombres de campos (`fields=["time_zone"]`), nunca valores. Los
  ids de usuario tampoco (enlazan con personas reales en el log del
  mantenedor).
- Fixtures: `light.salon`, `lock.puerta`, `Invitada`, `192.0.2.10`,
  `homeassistant.tailXXXX.ts.net`, `/ssl/fullchain.pem`, `centinela-021`.
- Las vistas previas y el fichero del token (que guarda los argumentos) no
  llevan nada que no haya pasado el cliente o que no devuelva ya la lectura;
  no hay argumentos de credenciales.
