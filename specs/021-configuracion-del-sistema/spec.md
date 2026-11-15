# Especificación: Hermes 1.2.0 — configuración del sistema (sub-feature 021)

**Directorio de la spec**: `specs/021-configuracion-del-sistema`

**Creada**: 2026-11-15

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T019 de su `tasks.md` y cubre **CAP-053, CAP-055,
CAP-056 y CAP-069** con tools dedicadas y **CAP-074** por la tabla de
clasificación (FR-071…FR-075 de la 008), más los transversales que le tocan
(FR-010…FR-012, FR-015, FR-018…FR-021, FR-023 y FR-024 de la 008). Ola 3,
tamaño L, 3 tramos: (a) núcleo y exposición; (b) usuarios; (c) red y HTTP,
analytics y labs.

**Entrada**: `specs/008-cobertura-total/` (spec, plan con la matriz de
trazabilidad, research CAP-053, CAP-055, CAP-056, CAP-069 y CAP-074, R-4 con
la clase D y las candidatas D-01, e `inventario/core-ws.tsv`), la 011
(`command_table.py`, `command_policy.py`, `tool_families.py`,
`tools/generic_commands.py`, el generador `scripts/inventario/generar_tabla.py`),
el banco de la 010 y la 028, los inventarios de la 014, la 018 y la 033, las
specs 012 y 029 (mismo mecanismo de `dedicated`; la 029 dejó en el tema
`system_status` el texto que esta sub-feature actualiza), el código de Hermes
(`ha.py`, `security.py`, `fs_write.py`, `tools/_annotations.py`,
`tools/_common.py`, `tools/guide.py`, `tools/supervisor.py`) y el código de
Home Assistant Core 2026.11.1 (`config/core.py`, `config/auth.py`,
`core_config.py`, `homeassistant/exposed_entities.py`, `auth/__init__.py`,
`network/websocket.py`, `network/network.py`, `http/websocket_api.py`,
`http/config.py`, `hassio/__init__.py`, `homeassistant/services.py`,
`analytics/__init__.py`, `labs/websocket_api.py`, `bootstrap.py`), leído sin
ejecutar nada.

**Fuera de esta sub-feature**: la lectura de la red, las URLs y el HTTP
(`network`, `network/url`, `http/config`: CAP-068, ya `read` por la 029); la
red del **host** (CAP-086/CAP-090, 032); las opciones de Core y del
Supervisor por la API del Supervisor (CAP-084, 022); la exposición a Alexa y
Google **de la nube** (`cloud/alexa/*`, `cloud/google_assistant/*`: clase D,
candidata D-01); contraseñas, nombres de usuario, MFA, tokens de larga
duración, revocar sesiones o fijar su caducidad (`config/auth_provider/*`,
`auth/*`: clase D o candidatas D-01); personas (`person/*`, ya cubiertas en la
1.1.2).

## Clarificaciones

### Sesión 2026-11-15

Decisiones vinculantes de la 008 (no se discuten aquí): tools dedicadas para
CAP-053, CAP-055, CAP-056 y CAP-069; CAP-074 por la tabla; la detección de la
configuración del núcleo queda `read` en la tabla (FR-071); usuarios sin
credenciales y nunca el propietario ni el usuario del propio Hermes (FR-073);
aviso de pérdida de acceso en red y HTTP (FR-074); tools nuevas en familias
nuevas, **activas por defecto** (decisión del mantenedor; duda D-03 de la
008); prueba de cada tool nueva de Core que modifica en el banco, con lector
independiente; lo que la 008 dejó en clase D o como candidata D-01 sigue en
`deny`.

Decisiones tomadas al especificar (no había a quién preguntar; se justifican
en [research.md](research.md)):

- P: ¿Cuántas tools y cuáles? → R: **doce**. Núcleo: `ha_get_core_config`,
  `ha_update_core_config`. Exposición: `ha_list_exposed_entities`,
  `ha_set_entity_exposure`, `ha_set_expose_new_entities`. Usuarios:
  `ha_list_users`, `ha_create_user`, `ha_update_user`, `ha_delete_user`. Red
  y HTTP: `ha_update_network_config`, `ha_update_http_config`,
  `ha_promote_http_config`. Research R-2 de la 008 nombraba además
  `ha_detect_core_config` (la 008 decidió después que la detección va por la
  tabla), `ha_get_expose_new_entities` (se pliega en la lista de exposición:
  misma clase de riesgo, una llamada menos; research R-3) y
  `ha_list_user_sessions` (no es posible: siguiente punto).
- P: ¿Sesiones de los usuarios (`auth/refresh_tokens`)? → R: **no hay tool y
  la entrada pasa a `deny` revisada**. Según `auth/__init__.py` de Core, el
  comando solo devuelve los tokens del usuario **de la propia conexión**
  (`connection.user`), nunca los de otros usuarios. En producción esa conexión
  es la del Supervisor (el usuario de sistema por el que entra Hermes), así
  que la lista serían las credenciales del propio Hermes, igual que
  `auth/current_user` (clase B). FR-073 de la 008 («listar usuarios y sus
  sesiones») no se puede cumplir en su segunda mitad; se anota como desviación
  y duda D-1 (research R-5).
- P: ¿Qué confirma? → R: **todo lo que escribe**: núcleo, exposición (también
  quitar, porque FR-072 pide confirmación en lote y una vista previa por
  asistente evita sorpresas con la nube), usuarios (crear, editar y borrar),
  red, HTTP y promover. Las vistas previas dicen quién o qué cambia, el antes
  y el después, y los avisos concretos (pérdida de acceso, administrador
  nuevo, último administrador, nube). Ninguna lleva una contraseña ni un
  token porque ninguna tool los acepta ni los devuelve.
- P: ¿Cómo se identifica «el usuario del propio Hermes»? → R: con
  `auth/current_user` por la conexión de Hermes (uso interno; la entrada de la
  tabla sigue `deny` para la genérica). Si no se puede leer, las tools de
  usuarios que escriben se niegan (`preview_unavailable`, fail-closed).
  Además de lo que HA ya rechaza (borrar al propietario, desactivarlo, borrarse
  a uno mismo, tocar usuarios de sistema), Hermes rechaza **antes de llamar a
  HA** cualquier escritura sobre el propietario, el usuario de Hermes y los
  usuarios de sistema, y cualquier cambio que deje cero administradores
  activos (research R-4).
- P: ¿El grupo de un usuario? → R: un argumento `group` con los tres grupos
  de HA (`system-admin`, `system-users`, `system-read-only`), como la
  interfaz; HA admite una lista, pero la interfaz asigna uno y la vista previa
  se entiende mejor así. La vista previa marca `grants_admin` y
  `removes_admin`.
- P: ¿HTTP con un documento entero o por campos? → R: por campos (`changes`,
  un dict con las claves de `HTTP_STORAGE_SCHEMA`; `null` quita la clave).
  Hermes funde los cambios sobre la configuración **activa** y manda el
  documento completo, porque HA rellena con valores por defecto lo que falte
  (quitaría el certificado, por ejemplo). `discard_pending` descarta una
  configuración pendiente (`config: null`) (research R-6).
- P: ¿Aplicar el HTTP reinicia HA? → R: **sí** (HA llama a
  `homeassistant.restart` en cuanto cambia lo pendiente). Por eso la tool
  respeta el mismo bloqueo que `sv_restart_core` (configuración escrita por
  Hermes sin validar después → se niega) y la vista previa explica la prueba
  de HA: arranca con lo pendiente y, si nadie lo promueve en 5 minutos o no
  arranca, vuelve a lo estable. `ha_promote_http_config` es el «sí, funciona».
- P: ¿Qué no se puede ejecutar en el banco? → R: `ha_update_http_config` y
  `ha_promote_http_config` aplicadas: la primera reinicia la HA del banco (el
  job la perdería) y la segunda solo tiene efecto con una configuración
  pendiente, que exige ese reinicio. En el banco se ejecuta su vista previa y
  su rechazo real; quedan en `NO_EJECUTABLES_021` con el motivo y se prueban en
  la VM (matriz de la 014). Las otras diez se ejecutan contra HA real con el
  lector independiente. `ha_update_network_config` sí se ejecuta: no toca la
  dirección ni el puerto en que escucha HA (research R-8).
- P: ¿Familias? → R: cuatro nuevas, activas por defecto y desactivables:
  `core_config` (núcleo), `assistant_exposure` (exposición), `users`
  (usuarios) y `core_network` (red y HTTP de Core; no es la red del host de la
  032). Cada una con su tema de la guía (research R-9).
- P: ¿Analytics y labs (CAP-074)? → R: siguen por la tabla como los dejó la
  011 (`analytics` y `labs/list` `read`; `analytics/preferences` y
  `labs/update` `confirm`), revisadas contra el código: `analytics/preferences`
  pasa a llevar `open_world=True` (activar el envío hace que HA mande datos a
  los servidores de Home Assistant). Se prueban en el banco por las genéricas
  y se explican en el tema `core_config` (research R-10).
- P: ¿`config/core/detect`? → R: `read` con `open_world=True` (HA consulta un
  servicio de geolocalización por IP) y `CAP-053`; el test de la clase A de
  vía D la admite por `_POR_LA_TABLA` con su porqué (research R-7).

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es el administrador de Home Assistant que trabaja desde un cliente
MCP.

### Historia 1 — Ajustar la configuración general de la casa (Prioridad: P1)

Quien acaba de mudarse, o instaló HA con valores por defecto, quiere cambiar
el nombre, la ubicación, la zona horaria, las unidades, la moneda, el país,
el idioma o las URLs sin abrir la interfaz, viendo antes qué cambia.

**Prueba independiente**: con HA simulado, una llamada sin token devuelve el
antes y el después solo de lo pedido, los avisos que tocan y un token; con el
token, HA recibe exactamente lo previsualizado y la respuesta lleva la
configuración releída.

**Escenarios de aceptación**:

1. **Dado** la configuración actual, **cuando** se pide
   `ha_get_core_config()`, **entonces** devuelve los campos editables, la
   fuente (`storage` o `yaml`) y la versión de HA, y no cambia nada.
2. **Dado** `ha_update_core_config(time_zone="Europe/Madrid")` sin token,
   **entonces** la vista previa dice el antes y el después, avisa de que los
   disparadores de hora y el historial pasan a la zona nueva y devuelve un
   token; HA no recibe nada.
3. **Dado** el token, **cuando** se repite la llamada, **entonces** HA recibe
   `config/core/update` con `time_zone` y la respuesta trae la configuración
   releída.
4. **Dado** que entre la vista previa y la confirmación alguien cambia la
   configuración, **entonces** la confirmación responde que el estado cambió
   y no aplica nada.
5. **Dado** una configuración que viene de `configuration.yaml`, **entonces**
   la vista previa avisa de que el cambio se perderá al reiniciar.
6. **Dado** valores que ya son los actuales, **entonces** `no_changes` sin
   token.

---

### Historia 2 — Decidir qué controla la voz (Prioridad: P1)

Quien usa Assist, un agente conversacional (local o en la nube) o la
integración MCP Server quiere ver qué entidades están expuestas y exponer u
ocultar varias a la vez, sabiendo cuándo algo sale hacia Amazon o Google.

**Prueba independiente**: con HA simulado, la lista devuelve las entidades
expuestas por asistente y si se exponen las nuevas; un lote para
`cloud.alexa` y `conversation` devuelve una vista previa por asistente con
lo que cambia y el aviso de la nube.

**Escenarios de aceptación**:

1. **Dado** entidades expuestas, **cuando** se pide
   `ha_list_exposed_entities()`, **entonces** devuelve el sobre común con
   `entity_id` y sus asistentes, y la cabecera `expose_new` de los tres
   asistentes.
2. **Dado** `ha_set_entity_exposure(["light.salon","lock.puerta"],
   ["cloud.alexa"], expose=True)` sin token, **entonces** la vista previa
   lista qué entidades cambian y cuáles ya estaban así, avisa de que Alexa
   recibe su estado y puede controlarlas a través de Home Assistant Cloud, y
   marca `lock.puerta` como de dominio sensible.
3. **Dado** el token, **entonces** HA recibe un solo
   `homeassistant/expose_entity` y la respuesta trae `changed_entity_ids`.
4. **Dado** una entidad que no existe, **entonces** `not_found` con la lista
   de las que faltan, sin llamar a HA (HA crearía una entrada huérfana).
5. **Dado** `ha_set_expose_new_entities("conversation", True)` sin token,
   **entonces** la vista previa dice el valor actual y que toda entidad nueva
   quedará expuesta a Assist y a los agentes conversacionales.

---

### Historia 3 — Gestionar quién entra en casa (Prioridad: P1)

Quien administra a la familia quiere ver los usuarios, crear uno (sin
contraseña: la pone una persona), cambiarle el nombre, el grupo o si solo
entra desde la red local, desactivarlo o borrarlo, sin poder dejar la casa
sin administrador ni tocar al propietario ni al usuario de Hermes.

**Prueba independiente**: con HA simulado (propietario, usuario de Hermes de
sistema, un administrador y un usuario normal), la lista marca quién es quién;
cada escritura sobre el propietario o el usuario de Hermes se rechaza sin
llamar a HA; dar administrador o desactivar enseña el antes y el después y el
recuento de administradores activos.

**Escenarios de aceptación**:

1. **Dado** los usuarios, **cuando** se pide `ha_list_users()`, **entonces**
   devuelve id, nombre, nombre de acceso, propietario, activo, administrador,
   solo local, grupos, tipos de credencial e `is_hermes`; los usuarios de
   sistema solo con `include_system=True`; nunca un token ni una contraseña.
2. **Dado** `ha_create_user("Invitada", group="system-users")` sin token,
   **entonces** la vista previa dice el nombre, el grupo, que no tendrá
   credenciales (no podrá iniciar sesión hasta que una persona se las dé) y si
   ya hay otro usuario con ese nombre.
3. **Dado** `ha_update_user(id, group="system-admin")` sin token, **entonces**
   la vista previa marca `grants_admin: true` con el antes y el después.
4. **Dado** `ha_update_user(id_del_propietario, name="x")` o el id del usuario
   de Hermes o de uno de sistema, **entonces** `protected_user` con el motivo,
   sin token y sin llamar a HA.
5. **Dado** un cambio que dejaría cero administradores activos, **entonces**
   `last_admin` sin token.
6. **Dado** `ha_delete_user(id)` sin token, **entonces** la vista previa dice
   quién es, si es administrador, qué persona tiene vinculada y que borrar no
   se deshace (sus sesiones y credenciales desaparecen).
7. **Dado** cualquiera de estas llamadas, **entonces** ni la respuesta ni el
   log ni el fichero del token contienen una contraseña o un token.

---

### Historia 4 — Cambiar la red y el servidor HTTP sin quedarse fuera (Prioridad: P2)

Quien pone HA detrás de un proxy inverso, activa HTTPS, cambia el puerto o
limita las interfaces de descubrimiento quiere hacerlo sabiendo qué puede
dejar la interfaz inaccesible y con una salida si sale mal.

**Prueba independiente**: con HA simulado, la vista previa de un cambio de
puerto y de `use_x_forwarded_for` sin `trusted_proxies` avisa de cada riesgo;
con el token, HA recibe el documento completo fundido sobre la configuración
activa; la respuesta dice que HA reinicia y que hay que promoverla en 5
minutos.

**Escenarios de aceptación**:

1. **Dado** `ha_update_network_config(["eth0"])` sin token, **entonces** la
   vista previa dice qué adaptadores se usan antes y después y que no cambia
   la dirección ni el puerto en que escucha HA.
2. **Dado** un adaptador que no existe, **entonces** `invalid_argument` con
   los disponibles, sin token.
3. **Dado** `ha_update_http_config(changes={"server_port": 8443})` sin token,
   **entonces** la vista previa lleva el documento resultante, el diff, el
   aviso de reinicio, el de URLs y apps que dejan de funcionar con el puerto
   viejo y la explicación de la prueba de 5 minutos.
4. **Dado** `changes={"server_host": ["192.0.2.10"]}`, **entonces** la vista
   previa avisa de que el Supervisor (y con él Hermes y todas las apps) llega a
   Core por la red interna de Docker y puede perder el acceso.
5. **Dado** configuración escrita por Hermes sin validar después, **entonces**
   `ha_update_http_config` se niega como `sv_restart_core` y remite a
   `sv_check_core_config`.
6. **Dado** una configuración pendiente con la que HA ya arrancó,
   **cuando** se pide `ha_promote_http_config()` sin token, **entonces** la
   vista previa dice el diff con la estable, que la pendiente pasa a ser la de
   recuperación y cuándo se revertiría; sin pendiente, `nothing_to_promote`.

---

### Historia 5 — Analytics y funciones en pruebas (Prioridad: P3)

Quien quiere revisar qué datos de uso manda HA o probar una función de labs lo
hace por las genéricas, con la guía como mapa.

**Prueba independiente**: con la tabla real, `ha_read_ws_command("analytics")`
y `("labs/list")` leen; `ha_call_ws_command("analytics/preferences", …)` y
`("labs/update", …)` piden token; `analytics/preferences` hace que la
genérica se anuncie de mundo abierto.

**Escenarios de aceptación**:

1. **Dado** `hermes_guide(topic="core_config")`, **entonces** explica las
   cuatro entradas de CAP-074 con la llamada exacta y la de
   `config/core/detect`.
2. **Dado** el banco, **entonces** las cuatro se ejecutan por la genérica
   contra HA real sin activar el envío de datos.

---

### Historia 6 — Nada de lo actual se rompe (Prioridad: P1)

Quien no quiere las tools nuevas las apaga; quien no cambia nada sigue
teniendo lo de antes.

**Prueba independiente**: con las cuatro familias nuevas desactivadas, la
lista de tools es exactamente la de antes de la 021; los doce comandos siguen
`dedicated` y la genérica los rechaza diciendo que su familia está
desactivada.

**Escenarios de aceptación**:

1. **Dado** la configuración por defecto, **entonces** aparecen las doce
   tools y las anteriores siguen con el mismo nombre, anotaciones y
   argumentos.
2. **Dado** `ha_call_ws_command("config/auth/delete", …)`, **entonces**
   `use_dedicated_tool` con `ha_delete_user`, sin llegar a HA.
3. **Dado** que se regenera la tabla con el generador, **entonces** sale
   idéntica.

---

### Casos límite

- `config/core/update` con una zona horaria inválida: HA aplica en memoria lo
  anterior a la zona antes de fallar (`_async_update`, sin guardar). Hermes
  manda la zona horaria **sola y primero**; si falla, nada se aplicó; si la
  zona pasa y el resto falla, la respuesta dice `partial: true` con lo
  aplicado (releído de HA).
- `unit_system` desconocido: HA lo convertiría en silencio en métrico; Hermes
  lo valida antes (`metric` o `us_customary`).
- `update_units=True` cambia las unidades sugeridas de los sensores: aviso de
  que las estadísticas a largo plazo pueden necesitar arreglo.
- `internal_url` o `external_url` vacías (`""`) las quitan (`null` en HA);
  con ruta, `invalid_argument` (HA no admite ruta).
- Exposición de una entidad sin registro (YAML sin `unique_id`): HA la admite
  como entrada heredada; Hermes la acepta si el estado existe.
- Más de 200 entidades en un lote: `invalid_argument` (vista previa legible y
  token acotado).
- Usuario con varios grupos (posible por la API): `group` los sustituye por
  uno y la vista previa enseña la lista antes y después.
- `auth/current_user` falla: las escrituras de usuarios responden
  `preview_unavailable`; la lista sale sin `is_hermes` (`null`) y lo dice.
- En el banco, el usuario de la conexión es el propietario (token del
  onboarding): las dos protecciones se prueban sobre el mismo usuario; la de
  usuarios de sistema, en unitarios (el banco no tiene ninguno).
- HA anterior a la configuración HTTP en almacenamiento (versión mínima
  declarada, 2024.10): `http/config` no existe; las dos tools de HTTP
  responden `unsupported_by_ha_version` sin escribir nada.
- HA no admite cambiar el HTTP si no está en marcha (`not_running`): se
  traduce con su motivo.
- La prueba de enlace del puerto falla (`bind_failed`): HA no guarda nada; se
  devuelve el motivo redactado.
- Pendiente con error registrado (`error` en `pending`): no se puede promover;
  `nothing_to_promote` con el error.
- `configuration.yaml` inválida: `homeassistant.restart` se niega después de
  guardar lo pendiente; la respuesta lo dice (lo pendiente se aplicará en el
  siguiente reinicio).
- Core caído: todas fallan con el error de conexión de siempre; la conexión
  se corta durante el reinicio que provoca `ha_update_http_config` después de
  recibir el resultado.

## Requisitos *(obligatorio)*

### Requisitos funcionales

Cada FR cita el FR y la CAP de la 008 que cumple.

#### Configuración del núcleo (CAP-053; FR-071 de la 008)

- **FR-001**: `ha_get_core_config()` lee `get_config` y devuelve solo los
  campos editables (`location_name`, `latitude`, `longitude`, `elevation`,
  `radius`, `unit_system` como nombre, `time_zone`, `currency`, `country`,
  `language`, `internal_url`, `external_url`), `config_source` y `version`.
  No modifica nada (FR-071; CAP-053).
- **FR-002**: `ha_update_core_config(location_name, latitude, longitude,
  elevation, radius, unit_system, time_zone, currency, country, language,
  internal_url, external_url, update_units=False, confirmation_token)`
  cambia solo los argumentos dados, en dos pasos. Valida antes de llamar
  (rangos de coordenadas, enteros, `unit_system` conocido, país de dos letras,
  moneda de tres, URL sin ruta o `""` para quitarla). La vista previa lleva el
  antes y el después de cada campo pedido y los avisos que tocan: zona
  horaria, unidades (y `update_units`), ubicación (`zone.home` y presencia),
  URLs (apps, enlaces y nube), país/moneda/idioma, y fuente `yaml` (el cambio
  no sobrevive a un reinicio). Sin diferencias, `no_changes` sin token. El
  token se ata a los argumentos y al estado leído (spec 018). Al confirmar,
  manda la zona horaria sola y primero, después el resto; devuelve la
  configuración releída y `partial` si algo no se aplicó (FR-071; CAP-053).
- **FR-003**: `config/core/detect` pasa a `read` en la tabla con
  `open_world=True`, `cap="CAP-053"`, un motivo que dice que consulta un
  servicio externo de geolocalización y que no guarda nada, y su clave en
  `_POR_LA_TABLA` del test de la clase A con el porqué (FR-071; CAP-053).

#### Exposición a asistentes (CAP-055; FR-072 de la 008)

- **FR-004**: `ha_list_exposed_entities(assistant=None, domain=None)` lee
  `homeassistant/expose_entity/list` y `expose_new_entities/get` de los tres
  asistentes (`conversation`, `cloud.alexa`, `cloud.google_assistant`) y
  devuelve el sobre común con `{entity_id, assistants}` ordenado por
  `entity_id`, filtrable por asistente y por dominio, con la cabecera
  `expose_new` (FR-072; CAP-055).
- **FR-005**: `ha_set_entity_exposure(entity_ids, assistants, expose,
  confirmation_token)` expone u oculta 1–200 entidades existentes a 1–3
  asistentes en un solo `homeassistant/expose_entity`, siempre en dos pasos.
  La vista previa, por asistente, dice qué entidades cambian y cuáles ya
  estaban así, marca las de dominios sensibles (`lock`,
  `alarm_control_panel`, `cover`, `valve`) y lleva el aviso de cada asistente
  (nube de Amazon o Google a través de Home Assistant Cloud; Assist, agentes
  conversacionales locales o en la nube e integración MCP Server). Sin
  cambios, `no_changes`. Token atado al estado de exposición leído (FR-072;
  CAP-055).
- **FR-006**: `ha_set_expose_new_entities(assistant, expose_new,
  confirmation_token)` cambia si las entidades nuevas se exponen a un
  asistente, en dos pasos, con el valor actual, el nuevo y el aviso del
  asistente; sin cambio, `no_changes` (FR-072; CAP-055).

#### Usuarios (CAP-056; FR-073 de la 008)

- **FR-007**: `ha_list_users(include_system=False)` lee `config/auth/list` y
  `auth/current_user` y devuelve el sobre común con `id`, `name`, `username`,
  `is_owner`, `is_active`, `is_admin` (propietario o grupo `system-admin`),
  `local_only`, `system_generated`, `group_ids`, `credential_types` e
  `is_hermes`, ordenado por nombre; cabecera `active_admins`. Sin
  `include_system`, sin los de sistema (salvo que sea el de Hermes, que sale
  siempre). Ningún campo de credencial salvo su tipo (FR-073; CAP-056).
- **FR-008**: Protecciones de toda escritura de usuarios, comprobadas en la
  vista previa **y otra vez al confirmar**, antes de llamar a HA: el
  propietario, el usuario de Hermes y los usuarios de sistema son
  `protected_user` (con el motivo); un cambio o borrado que deje cero
  administradores activos (no de sistema) es `last_admin`; si
  `auth/current_user` no se puede leer, `preview_unavailable` (FR-073;
  CAP-056; principio III).
- **FR-009**: `ha_create_user(name, group="system-users", local_only=False,
  confirmation_token)` crea un usuario **sin credenciales** con
  `config/auth/create`, en dos pasos. La vista previa avisa de que no podrá
  iniciar sesión hasta que una persona le dé credenciales, de `grants_admin`
  si el grupo es `system-admin` y de los usuarios con el mismo nombre. No hay
  argumento de contraseña ni de nombre de acceso (FR-073; CAP-056).
- **FR-010**: `ha_update_user(user_id, name=None, is_active=None, group=None,
  local_only=None, confirmation_token)` cambia solo lo dado, en dos pasos. La
  vista previa dice quién es, el antes y el después, `grants_admin`,
  `removes_admin`, `deactivates` (deja de poder entrar), `restricts_remote`
  (`local_only` a `true`) y los administradores activos antes y después. Sin
  cambios, `no_changes`. Token atado al estado del usuario leído (FR-073;
  CAP-056).
- **FR-011**: `ha_delete_user(user_id, confirmation_token)` borra con
  `config/auth/delete`, en dos pasos. La vista previa dice quién es, si es
  administrador, las personas vinculadas (`person/list`), que se borran sus
  credenciales y sesiones y que no se deshace. Token atado al estado del
  usuario (FR-073; CAP-056).
- **FR-012**: Ninguna tool de usuarios acepta, devuelve, registra ni deja en
  el fichero del token una contraseña o un token. `auth/refresh_tokens` pasa a
  `deny` con el motivo revisado (solo da las sesiones del usuario de la propia
  conexión, el de Hermes) y su clave en una excepción documentada del test de
  la clase A; `config/auth_provider/homeassistant/*` y `auth/*` siguen como
  los dejó la 011 (clase D) (FR-073; CAP-056; FR-019 de la 008; R-4 y D-01 de
  la 008).

#### Red y HTTP de Core (CAP-069; FR-074 de la 008)

- **FR-013**: `ha_update_network_config(configured_adapters,
  confirmation_token)` fija los adaptadores de red que usa HA (lista vacía =
  detección automática) con `network/configure`, en dos pasos. Valida cada
  nombre contra `network`. La vista previa dice los adaptadores habilitados
  antes y después y que el cambio afecta al descubrimiento y a las direcciones
  que HA anuncia, no a la dirección ni al puerto en que escucha (FR-074;
  CAP-069).
- **FR-014**: `ha_update_http_config(changes=None, discard_pending=False,
  confirmation_token)`: con `changes` (claves de la configuración HTTP de HA;
  `null` quita una), funde sobre la configuración activa (estable, pendiente o
  por defecto, según `active_config_type`), quita los metadatos y manda el
  documento completo a `http/config/configure`; con `discard_pending`, manda
  `config: null`. Siempre en dos pasos. La vista previa lleva el documento
  resultante, el diff, el aviso de reinicio y de la prueba de 5 minutos, y uno
  por cada riesgo: puerto, `server_host` (acceso del Supervisor, de Hermes y
  de las apps), certificados (HTTPS obligatorio), proxy inverso
  (`use_x_forwarded_for`/`trusted_proxies`), bloqueo de IP, CORS y perfil
  SSL. Respeta el bloqueo de reinicio de `sv_restart_core` en la vista previa
  y al confirmar. La respuesta dice si HA reinicia, que lo pendiente se
  revierte si no se promueve y que, con `configuration.yaml` inválida, HA no
  reinicia (FR-074; CAP-069).
- **FR-015**: `ha_promote_http_config(confirmation_token)` promueve la
  configuración pendiente con `http/config/promote`, en dos pasos. Solo si hay
  pendiente sin error y HA está funcionando con ella
  (`active_config_type == "pending"`); si no, `nothing_to_promote` con el
  motivo. La vista previa dice el diff con la estable, `revert_at` y que la
  promovida pasa a ser la de recuperación (FR-074; CAP-069).

#### Analytics y labs (CAP-074; FR-075 de la 008)

- **FR-016**: `analytics` y `labs/list` siguen `read`; `analytics/preferences`
  y `labs/update` siguen `confirm`; `analytics/preferences` pasa a llevar
  `open_world=True` con su porqué. Las cuatro se ejecutan en el banco por las
  genéricas sin activar el envío de datos y se explican en el tema
  `core_config` (FR-075; CAP-074; FR-015 de la 008).

#### Familias, tabla, convenciones y documentación (transversales de la 008)

- **FR-017**: Cuatro familias nuevas en `tool_families.py`, `desde="1.2.0"`,
  desactivables y activas por defecto: `core_config` (módulo `core_config`),
  `assistant_exposure` (módulo `assistant_exposure`), `users` (módulo
  `users`) y `core_network` (módulo `core_network`). Con las cuatro
  desactivadas, la lista de tools es la de antes de la 021 (FR-010 de la 008;
  CAP-004).
- **FR-018**: Los doce comandos pasan de `deny` «pendiente de tool dedicada
  (spec 021)» a `dedicated` con su tool, su familia y su CAP:
  `config/core/update`, `homeassistant/expose_entity`,
  `homeassistant/expose_entity/list`, `homeassistant/expose_new_entities/get`,
  `homeassistant/expose_new_entities/set`, `config/auth/list`,
  `config/auth/create`, `config/auth/update`, `config/auth/delete`,
  `network/configure`, `http/config/configure` y `http/config/promote`. El
  generador los nombra en `_DEDICADAS_INICIALES`; regenerar la tabla la deja
  idéntica; no queda ninguna entrada con «(spec 021)» (FR-012 de la 008;
  CAP-001).
- **FR-019**: Anotaciones verdaderas en la tabla central: las tres de lectura
  por su prefijo; las nueve que escriben, con token y destructivas
  (`ha_delete_user` por prefijo; las demás en `_DESTRUCTIVE_EXACT` con su
  porqué); `ha_create_user` no idempotente (prefijo); de mundo abierto
  `ha_set_entity_exposure` y `ha_set_expose_new_entities` (la nube de Amazon
  y Google). Hints y títulos en `_HINTS_NUEVAS_1_2_0` (FR-018 de la 008;
  principio V).
- **FR-020**: Toda respuesta y vista previa pasa por `redact_structure` y
  `redact_secrets` y por el tope de respuesta; las listas usan
  `sobre_de_lista` y `ajustar_lista_a_bytes`. Los errores de HA salen
  redactados y traducidos (`invalid_format`, `invalid_info`, `bind_failed`, `not_running`,
  `not_allowed`, `not_found`, `no_delete_self`, `cannot_*`). Un comando que HA
  no conoce → `unsupported_by_ha_version` con `ha_code` (FR-018, FR-019,
  FR-020 de la 008; principio II).
- **FR-021**: El log de las doce lleva solo el nombre de la tool, el
  resultado, el paso (vista previa o confirmación) y recuentos o nombres de
  campos cambiados; nunca valores: ni coordenadas, URLs, direcciones, puertos,
  nombres de usuario ni de entidad, ids de usuario ni rutas de certificados
  (FR-019, FR-021 de la 008; CAP-011).
- **FR-022**: Cada tool tiene descripción en inglés que dice lo que hace y lo
  que no, y su tema en la guía: `core_config` (con `config/core/detect` y
  CAP-074), `assistant_exposure`, `users` y `core_network`, con alias e
  índice; el tema `system_status` deja de decir que Hermes no tiene tool para
  cambiar la red y el HTTP y remite a `core_network` (su test se actualiza)
  (FR-011, FR-018 de la 008).
- **FR-023**: Las diez tools que se pueden ejecutar en el banco se ejecutan
  contra HA Core 2026.11.1 real y su efecto lo comprueba el lector
  independiente; `ha_update_http_config` y `ha_promote_http_config` ejecutan
  en el banco su vista previa y su rechazo real y quedan en
  `NO_EJECUTABLES_021` con el motivo. Las listas van en
  `tests/banco/cobertura_021.py` y se suman al invariante de escrituras y a lo
  que el job exige por ejecución (FR-015 de la 008; CAP-034).
- **FR-024**: Inventarios del programa en el mismo cambio: una fila por cada
  tool que modifica en la matriz de la 014 (`docs/HOJA-DE-RUTA.md`), una
  entrada por cada tool con token en el inventario de argumentos atados de la
  033 (todo atado salvo el token), y ninguna entrada nueva en el de
  `allow_dangerous` de la 018 (ninguna llama a `call_service`) (FR-016 de la
  008; invariantes de la 014, la 018 y la 033).
- **FR-025**: Documentación en el mismo cambio: sección «Sistema» en
  `## [1.2.0]` del CHANGELOG; estado de la 021 en la tabla del programa de
  `docs/HOJA-DE-RUTA.md`; recuento y tablas de tools en `README.md`,
  `README.es.md` y `hermes/DOCS.md` (con las cuatro familias en
  `tool_families_disabled`); filas CAP-053, CAP-055, CAP-056, CAP-069 y CAP-074
  de la matriz de la 008 con las tools, entradas y tests definitivos (FR-023,
  FR-024 de la 008).

### Entidades clave

- **Configuración del núcleo**: los campos editables, su fuente y la versión.
- **Exposición**: entidad, asistentes a los que está expuesta y, por
  asistente, si se exponen las nuevas.
- **Usuario**: identidad, estado, grupos, tipo de credenciales y si es el
  propietario, el de Hermes o de sistema. Nunca credenciales.
- **Configuración HTTP**: estable, pendiente (con su error), activa, por
  defecto y plazo de reversión.
- **Adaptador de red**: nombre, direcciones, si está habilitado y si es
  automático.

## Criterios de éxito *(obligatorio)*

- **SC-001**: Las doce tools aparecen con la configuración por defecto; con
  las cuatro familias nuevas desactivadas, el conjunto de tools es exactamente
  el anterior a la 021.
- **SC-002**: Cero entradas de la tabla con «(spec 021)»; doce `dedicated`
  hacia tools registradas; regenerar la tabla no cambia ni un byte.
- **SC-003**: Diez de las doce tools se ejecutan en el banco contra HA Core
  2026.11.1 real: las siete que escriben con su efecto comprobado por el
  lector y las tres de lectura contrastadas con él; las dos de HTTP, su vista
  previa y su rechazo real; las cuatro entradas de CAP-074 y
  `config/core/detect`, por las genéricas.
- **SC-004**: En el 100 % de las escrituras probadas, la llamada sin token no
  cambia nada en HA (comprobado por el lector) y la vista previa nombra el
  objetivo, el antes y el después.
- **SC-005**: Ninguna escritura sobre el propietario, el usuario de Hermes o
  un usuario de sistema, ni ninguna que deje cero administradores activos,
  llega a HA (tests con el cliente simulado que fallan si se llama a
  `ws_send` de escritura).
- **SC-006**: En los tests, ningún centinela (contraseña o token en un error
  de HA, ruta de certificado, coordenadas, URL, nombre de usuario o de
  entidad) aparece en el log; ninguna respuesta ni fichero de token contiene
  una contraseña o un token.
- **SC-007**: Suite completa con solo los 6 fallos conocidos en Windows y CI
  (tests, banco de Core, Semgrep y CodeQL) en verde al cerrar cada tramo.

## Supuestos

- La implementación parte de `feat/cobertura-total` con la 009, 010, 011,
  028, 014, 013, 018, 029, 012, 033 y 027 integradas (base de esta rama,
  `c4a57bf`).
- `analytics`, `labs`, `network`, `backup` y `person` se cargan en el banco
  aunque no use `default_config:`: están en `DEFAULT_INTEGRATIONS` de
  `bootstrap.py` («set up unless recovery mode is activated»), y `person:` y
  `network:` ya están además en su `configuration.yaml`. Si alguna no
  respondiera en el banco, el tramo que la necesita la añade a
  `tests/banco/ha_config/configuration.yaml` con su porqué.
- La conexión de Hermes en el banco es la del propietario (token del
  onboarding a través del Supervisor simulado); en producción es el usuario de
  sistema del Supervisor. Las dos protecciones (propietario y Hermes) se
  prueban en el banco sobre el mismo usuario y por separado en unitarios.
- La copia de `fuentes` no incluye `homeassistant/auth/`: la definición de
  administrador (propietario o activo con `system-admin`) y el efecto de
  desactivar se toman de la API documentada de Core y se comprueban en el
  banco (tramo b).
- Cambiar la configuración del núcleo en el banco no rompe a los demás tests
  si se restaura al terminar (cada test lo hace en `finally`).

## Dudas para el final

- **D-1**: `auth/refresh_tokens` solo da las sesiones del usuario de la propia
  conexión: FR-073 de la 008 («y sus sesiones») no se puede cumplir para otros
  usuarios. Queda `deny` revisado. ¿Se reconsidera la candidata D-01 de
  revocar sesiones, que tendría el mismo límite?
- **D-2**: Un usuario creado sin credenciales no puede iniciar sesión. No se
  ha comprobado (no está en la copia de `fuentes`) que la interfaz de HA deje
  añadir credenciales a un usuario ya creado; si no lo deja, `ha_create_user`
  aporta poco. ¿Se mantiene?
- **D-3**: `server_host` sin la dirección por la que el Supervisor llega a
  Core deja sin acceso a Hermes y a todas las apps. Hoy se avisa y la prueba
  de 5 minutos de HA lo revierte si nadie lo promueve. ¿Se rechaza en vez de
  avisar?
  - *Nota posterior (integración en la rama del programa)*: decidida como
    rechazo (fail-closed). El texto de arriba es el histórico: desde Core
    2026.4 el Supervisor, y Hermes a través de él, llegan a Core por un
    socket Unix; lo que se corta son las apps que conectan directamente a
    `homeassistant:8123`. Por eso el código de error, que se llamó
    `supervisor_lockout`, pasa a ser `apps_lockout` (la tool es nueva de la
    1.2.0: no hay compatibilidad que guardar).
- **D-4**: Quitar la exposición también confirma (FR-072 pide confirmación en
  lote). ¿Se permite ocultar sin token, que reduce lo expuesto?
- **D-5**: `users` y `core_network` (riesgo alto) quedan activas por defecto
  por la decisión del mantenedor (D-03 de la 008).
