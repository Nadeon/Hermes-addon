# Contratos de las tools (021)

Doce tools nuevas: tres de solo lectura y nueve que escriben, todas estas con
`confirmation_token` (dos pasos siempre). Hints: `R`ead-only,
`D`estructive, `I`dempotent, `O`pen world. Formas de respuesta y errores en
[data-model.md](../data-model.md). Todas devuelven el objeto (`-> object`),
como el resto de módulos de la 1.2.0.

Reglas comunes de las que escriben:

- Validan todo antes de leer de HA; leen lo necesario para la vista previa
  (si falla, `preview_unavailable`); sin diferencias, `no_changes` sin token.
- El token ata todos los argumentos (salvo el propio token) y el estado leído
  del objetivo (`estado=` de la 018). Al confirmar se vuelve a leer, se
  vuelven a aplicar las protecciones y, si el estado cambió,
  `ESTADO_CAMBIADO` sin tocar nada.
- Errores de HA redactados y traducidos; log sin valores.

## Familia `core_config` (módulo `tools/core_config.py`, tramo a)

### `ha_get_core_config()`

- Hints `R-I-`. Comando `get_config`.
- Descripción: la configuración general editable (nombre, ubicación,
  unidades, zona horaria, moneda, país, idioma, URLs), de dónde viene
  (`storage` o `yaml`) y la versión; no cambia nada. Para proponer valores
  desde la IP pública, `ha_read_ws_command("config/core/detect")` (sale a
  internet).

### `ha_update_core_config(location_name=None, latitude=None, longitude=None, elevation=None, radius=None, unit_system=None, time_zone=None, currency=None, country=None, language=None, internal_url=None, external_url=None, update_units=False, confirmation_token=None)`

- Hints `-DI-` (`_DESTRUCTIVE_EXACT`: cambia cómo HA interpreta horas y
  unidades). Comando `config/core/update` (dos llamadas si hay
  `time_zone`).
- Validación: al menos un campo; `latitude` en [-90, 90], `longitude` en
  [-180, 180]; `elevation` entero; `radius` entero ≥ 0; `unit_system` en
  {`metric`, `us_customary`}; `country` `^[A-Z]{2}$`; `currency`
  `^[A-Z]{3}$`; `language` `^[a-z]{2,3}([-_][A-Za-z0-9]{2,8})*$`;
  `time_zone` texto no vacío ≤ 64 sin espacios; URLs `http(s)://host[:puerto]`
  sin ruta, o `""` para quitarlas; `location_name` ≤ 255;
  `update_units` solo con `unit_system`.
- Descripción: dos pasos; solo cambia lo que se pasa; avisos de lo que
  arrastra cada cambio; con la configuración en `configuration.yaml`, el
  cambio no sobrevive a un reinicio; `""` quita una URL.

## Familia `assistant_exposure` (módulo `tools/assistant_exposure.py`, tramo a)

### `ha_list_exposed_entities(assistant=None, domain=None)`

- Hints `R-I-`. Comandos `homeassistant/expose_entity/list` y
  `homeassistant/expose_new_entities/get` (×3).
- Validación: `assistant` en los tres de HA; `domain` `^[a-z0-9_]+$`.
- Descripción: entidades expuestas por asistente (`conversation` = Assist,
  agentes conversacionales y MCP Server; `cloud.alexa`,
  `cloud.google_assistant` = nube); las ocultas no salen; `expose_new` por
  asistente.

### `ha_set_entity_exposure(entity_ids, assistants, expose, confirmation_token=None)`

- Hints `-DIO` (`_DESTRUCTIVE_EXACT` y `_OPEN_WORLD`: con la nube activa, el
  cambio se sincroniza con Amazon o Google). Comando
  `homeassistant/expose_entity` (una llamada).
- Validación: `entity_ids` 1–200, forma `dominio.objeto`, sin repetidos (se
  quitan antes de atar el token); `assistants` 1–3 de los de HA; `expose`
  booleano estricto. Cada entidad tiene que tener estado (`not_found` con las
  que faltan).
- Descripción: dos pasos siempre (también para ocultar); vista previa por
  asistente con lo que cambia; marca dominios sensibles.

### `ha_set_expose_new_entities(assistant, expose_new, confirmation_token=None)`

- Hints `-DIO`. Comandos `homeassistant/expose_new_entities/get` y `/set`.
- Descripción: si las entidades que se creen a partir de ahora se exponen a
  ese asistente; no cambia las existentes.

## Familia `users` (módulo `tools/users.py`, tramo b)

### `ha_list_users(include_system=False)`

- Hints `R-I-`. Comandos `config/auth/list` y `auth/current_user` (interno).
- Descripción: usuarios con su papel; `is_hermes` marca el usuario por el que
  entra Hermes (en un add-on, el de sistema del Supervisor); nunca
  contraseñas ni tokens; las sesiones no se pueden listar (HA solo da las del
  usuario de la conexión).

### `ha_create_user(name, group="system-users", local_only=False, confirmation_token=None)`

- Hints `-D--` (`_DESTRUCTIVE_EXACT`: puede crear un administrador; no
  idempotente por prefijo). Comandos `config/auth/list`,
  `auth/current_user`, `config/auth/create`.
- Validación: `name` 1–100 caracteres sin saltos de línea; `group` en los
  tres grupos de HA.
- Descripción: crea un usuario SIN credenciales (no puede iniciar sesión
  hasta que una persona le dé usuario y contraseña en HA); Hermes nunca
  maneja contraseñas; dos pasos.

### `ha_update_user(user_id, name=None, is_active=None, group=None, local_only=None, confirmation_token=None)`

- Hints `-DI-` (`_DESTRUCTIVE_EXACT`). Comandos `config/auth/list`,
  `auth/current_user`, `config/auth/update`.
- Validación: `user_id` `^[0-9a-f]{32}$` (forma de HA); al menos un campo.
- Descripción: dos pasos; no toca al propietario, al usuario de Hermes ni a
  los de sistema; nunca deja la casa sin administrador; desactivar impide
  entrar.

### `ha_delete_user(user_id, confirmation_token=None)`

- Hints `-DI-` (prefijo `ha_delete_`). Comandos `config/auth/list`,
  `auth/current_user`, `person/list`, `config/auth/delete`.
- Descripción: dos pasos; irreversible; borra credenciales y sesiones; la
  persona vinculada se queda sin usuario; mismas protecciones.

## Familia `core_network` (módulo `tools/core_network.py`, tramo c)

### `ha_update_network_config(configured_adapters, confirmation_token=None)`

- Hints `-DI-` (`_DESTRUCTIVE_EXACT`). Comandos `network` y
  `network/configure`.
- Validación: lista de 0–32 nombres existentes en `network` (vacía =
  automático), sin repetidos.
- Descripción: qué interfaces usa HA para descubrir dispositivos y qué
  direcciones anuncia; no cambia dónde escucha la interfaz web. Para leer:
  `ha_read_ws_command("network")`.

### `ha_update_http_config(changes=None, discard_pending=False, confirmation_token=None)`

- Hints `-DI-` (`_DESTRUCTIVE_EXACT`: reinicia HA y puede cortar el acceso).
  Comandos `http/config` y `http/config/configure`.
- Validación: exactamente uno de `changes` (dict no vacío) o
  `discard_pending=True`; claves de `changes` en `server_host`,
  `server_port`, `ssl_certificate`, `ssl_peer_certificate`, `ssl_key`,
  `cors_allowed_origins`, `use_x_forwarded_for`, `trusted_proxies`,
  `login_attempts_threshold`, `ip_ban_enabled`, `ssl_profile`,
  `use_x_frame_options`; tipos básicos por clave (el resto lo valida HA);
  `use_x_forwarded_for: true` exige `trusted_proxies` en el resultado.
  Bloqueo de reinicio de Hermes en la vista previa y al confirmar.
- Descripción: dos pasos; funde sobre la configuración activa y manda el
  documento completo; HA reinicia y prueba la configuración 5 minutos;
  promover con `ha_promote_http_config`; avisos de pérdida de acceso.

### `ha_promote_http_config(confirmation_token=None)`

- Hints `-DI-` (`_DESTRUCTIVE_EXACT`: la promovida pasa a ser la de
  recuperación). Comandos `http/config` y `http/config/promote`.
- Descripción: confirma que la configuración HTTP de prueba funciona; solo con
  una pendiente con la que HA ya está funcionando; su vista previa sirve de
  estado de la prueba (diff y `revert_at`).
