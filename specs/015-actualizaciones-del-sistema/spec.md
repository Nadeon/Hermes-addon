# Especificación: Hermes 1.2.0 — actualizaciones del sistema (sub-feature 015)

**Directorio de la spec**: `specs/015-actualizaciones-del-sistema`

**Creada**: 2026-11-14

**Estado**: Borrador

**Programa**: cobertura total de HA 2026.11, spec paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/spec.md). Esta
sub-feature es la tarea T013 de su `tasks.md` y cubre **CAP-080
(actualizaciones del sistema con vista previa útil) y CAP-064 (notas de versión
e instalación de entidades `update`)** con tools dedicadas (FR-049 y FR-050 de
la 008). Depende de la 009 (rechazo de `sv_update_addon` sobre Hermes), la 010
(banco de pruebas de Core), la 011 (tabla, genéricas y familias) y la 013
(diagnóstico del Supervisor: título `OS`, `/jobs/info` y la regla del test de la
tabla que admite `dedicated`).

**Entrada**: `specs/008-cobertura-total/` (spec, plan con la matriz de
trazabilidad, research CAP-064 y CAP-080, `inventario/core-ws.tsv` e
`inventario/supervisor-rutas.tsv`), la spec 011 (`command_table.py`,
`command_policy.py`, `tool_families.py`), la 013 (`sv_get_os_info`) y el código
de Hermes: `tools/addons.py` (`sv_update_addon`, `_track_job`, `_es_hermes`),
`tools/supervisor.py` (`sv_restart_core`, `sv_check_core_config`),
`tools/ha.py` (`ha_call_service`), `service_policy.py` (denylist con
`update.install`), `security.py` (token atado), `supervisor_jobs.py`,
`tools/_annotations.py`, `tools/_common.py` y `tools/guide.py`. Contrastado con
el código del Supervisor 2026.11.0 (`api/root.py`, `api/homeassistant.py`,
`api/os.py`, `api/supervisor.py`, `api/middleware/security.py`,
`homeassistant/core.py`, `os/manager.py`, `supervisor.py`,
`jobs/decorator.py`) y de Core 2026.11.1 (`components/update/`,
`components/hassio/update.py`, `update_helper.py`, `websocket_api.py`,
`components/api/__init__.py`, `components/template/update.py`).

## Clarificaciones

### Sesión 2026-11-14

Decisiones vinculantes del programa (ya están en la 008 y en la 011):

- CAP-080 y CAP-064 van por **tools dedicadas** (prioridad alta y media-alta,
  riesgo alto): la vista previa necesita entender el efecto.
- Las tools nuevas van en una **familia nueva** de la 1.2.0 (FR-010 de la 008).
- Las entidades `update` de Core, OS y Supervisor se encaminan a las tools del
  Supervisor, para que no haya dos caminos con vistas previas distintas
  (FR-050 de la 008).
- **Fuera**: la tienda de apps y actualizar una app a una versión concreta o
  leer su changelog (030, CAP-082); los plugins del Supervisor (actualizar,
  reiniciar, opciones: `confirm` en la tabla, 022, FR-078 de la 008); el
  backup previo de la integración `backup` (`hassio/update/config/*`, 031).
- En el banco de la 010 el Supervisor es simulado y solo reenvía a Core: las
  tools `sv_*` de esta sub-feature se prueban con un Supervisor simulado en
  unitarios y su prueba real queda **pendiente manual** (VM de la 014). Las
  `ha_*` se ejecutan en el banco con una entidad `update` de plantilla.

Decisiones tomadas al especificar (no había a quién preguntar; se justifican
en [research.md](research.md)):

- P: ¿Una familia o dos? → R: **una**, `system_updates` («desde» 1.2.0,
  desactivable), con dos módulos: `system_updates` (las cinco `sv_*`, CAP-080)
  y `update_entities` (las tres `ha_*`, CAP-064). Un tema de guía, `updates`
  (research R-1).
- P: ¿Qué ruta busca actualizaciones? → R: `POST /refresh_updates`, no
  `/reload_updates`: recarga también la tienda (sin eso no aparecen las
  actualizaciones de apps) y es la que el rol `manager` puede llamar en la API
  v1 si un día se baja el rol (D-02 de la 008). El inventario la marca como
  alias «desaconsejado» de clase B, pero no es un alias exacto (research R-2).
- P: ¿Cómo no mentir sobre la versión de destino? → R: la vista previa
  **resuelve** la versión de destino y la ata al token; al confirmar se vuelve
  a resolver y, si cambió, el token no vale (`preview_outdated`). La ejecución
  envía siempre la versión explícita, nunca «la última» (research R-3).
- P: ¿Notas de la versión de Core, OS y Supervisor? → R: Home Assistant **no
  las tiene en local**: las entidades de Core y Supervisor no admiten
  `release_notes`, y la del OS solo devuelve el aviso de reinicio. La vista
  previa lo dice, da la `release_url` de la entidad y no sale a internet a
  buscarlas (research R-4). Desviación de la letra de FR-049 de la 008,
  impuesta por HA.
- P: ¿Backup antes de actualizar? → R: Core: `backup=True` por defecto, con el
  backup parcial del propio Supervisor (`core_<versión actual>`, solo Core, sin
  apps), que la vista previa describe. OS: el Supervisor no hace backup; la
  tool tampoco, y lo dice con la pista de crear uno antes. Supervisor: no hay
  backup posible (research R-5).
- P: ¿Qué hace la vista previa con lo que hará fallar la actualización? → R:
  detecta las condiciones que el Supervisor comprueba y que se pueden leer
  (sistema no saludable, Supervisor pendiente de actualizar, plugins
  desactualizados con la actualización automática apagada, menos de 2 GB
  libres, OS pendiente de reinicio, configuración de Core inválida) y, si hay
  alguna, devuelve la vista previa con `blocked` y **sin token** (fail-closed;
  research R-6).
- P: ¿Cómo se sigue una actualización del OS o del Supervisor, que no
  devuelven `job_id`? → R: Hermes lanza la petición en segundo plano y busca el
  job por su nombre (`os_manager_update`, `supervisor_update`) en `/jobs/info`
  durante unos segundos; si lo encuentra, lo devuelve para
  `sv_get_job_status`; si no, lo dice y da la tool con la que comprobar la
  versión (research R-7).
- P: ¿Y las entidades `update` de las apps? → R: se encaminan a
  `sv_update_addon` (y la de Hermes, a su rechazo `self_update_not_supported`
  de la 009), como las de Core, OS y Supervisor: un solo camino por cosa. Las
  notas de una app sí se leen con `ha_get_update_release_notes` (research R-8).
- P: ¿Una tool para listar las entidades `update`? → R: sí,
  `ha_list_updates`: `sv_list_available_updates` solo ve lo del Supervisor, y el
  firmware de dispositivos o las integraciones con entidad `update` solo se ven
  por Core (research R-9).
- P: ¿Plugins? → R: `sv_list_available_updates` los **lista** (su versión y si
  hay actualización), porque la de Core depende de ellos; actualizarlos sigue
  por la tabla (`sv_call_api`, `confirm`, 022) y el elemento lo dice.

## Escenarios de usuario y pruebas *(obligatorio)*

El «usuario» es el administrador de Home Assistant que mantiene su sistema al
día desde un cliente MCP.

### Historia 1 — Saber qué hay que actualizar (Prioridad: P1)

Quien administra HA quiere ver de un vistazo qué tiene actualización pendiente
(Core, OS, Supervisor, apps, plugins y dispositivos) y poder buscar
actualizaciones nuevas sin esperar al ciclo del Supervisor.

**Prueba independiente**: con un Supervisor simulado, `sv_list_available_updates`
devuelve cada pieza con su versión instalada y la disponible y la tool con que
se actualiza; `sv_check_for_updates` hace un `POST /refresh_updates` y devuelve
la lista fresca.

**Escenarios de aceptación**:

1. **Dado** Core y una app con actualización, **cuando** el agente llama a
   `sv_list_available_updates`, **entonces** recibe dos elementos con
   `installed_version`, `latest_version` y `update_with` (`sv_update_core`,
   `sv_update_addon`), con el sobre `{count, items, truncated}`.
2. **Dado** un plugin desactualizado, **entonces** aparece con
   `update_with` que nombra la ruta de la tabla y la nota de que el Supervisor
   lo actualiza solo antes de actualizar Core.
3. **Dado** Hermes con actualización, **entonces** su elemento dice que se
   actualiza desde la interfaz de HA (no ofrece una tool que lo rechazaría).
4. **Dado** que el agente quiere datos frescos, **cuando** llama a
   `sv_check_for_updates`, **entonces** Hermes pide `POST /refresh_updates` y
   devuelve la lista actualizada; no pide token.
5. **Dado** dispositivos o integraciones con entidad `update`, **cuando** el
   agente llama a `ha_list_updates`, **entonces** recibe las que tienen
   actualización con su versión, qué admiten (versión concreta, backup, notas)
   y con qué tool se instalan.

### Historia 2 — Actualizar Core sabiendo lo que va a pasar (Prioridad: P1)

Quien actualiza Core quiere saber, antes de confirmar, de qué versión a qué
versión va, si habrá backup y de qué, qué se reinicia, si el sistema está sano,
si la configuración es válida y si algo hará que el Supervisor lo rechace.

**Prueba independiente**: con un Supervisor simulado, la vista previa de
`sv_update_core` contiene cada dato; con un bloqueo, no hay token; la
confirmación envía la versión de la vista previa y devuelve el `job_id`.

**Escenarios de aceptación**:

1. **Dado** Core 2026.11.0 con 2026.11.1 disponible, **cuando** el agente llama
   a `sv_update_core()`, **entonces** la vista previa dice `from_version`
   2026.11.0, `to_version` 2026.11.1, que se creará un backup parcial de Core
   llamado `core_2026.11.0` (y si excluye la base de datos), que Core se
   reinicia y que, si la versión nueva no arranca, el Supervisor intenta volver
   a la anterior; el estado de `/resolution/info`; el resultado de la
   comprobación de configuración; y que las notas no están en local, con la
   URL de la entidad.
2. **Dado** el Supervisor con actualización pendiente, **entonces** la vista
   previa tiene `blocked` con «actualiza antes el Supervisor
   (`sv_update_supervisor`)» y no hay token.
3. **Dado** un sistema no saludable, una configuración inválida o menos de
   2 GB libres, **entonces** igual: `blocked` con el motivo y sin token.
4. **Dado** plugins desactualizados con la actualización automática activa,
   **entonces** la vista previa dice que el Supervisor los actualizará antes;
   con la actualización automática apagada, `blocked`.
5. **Dado** el token de la vista previa, **cuando** se confirma, **entonces**
   Hermes envía `POST /core/update` con `version` = la de la vista previa,
   `backup` y `background: true`, y devuelve `job_id` con
   `poll_with: sv_get_job_status`.
6. **Dado** que entre la vista previa y la confirmación la última versión
   cambió, **cuando** se confirma sin `version`, **entonces** se rechaza con
   `preview_outdated` y no se envía nada.
7. **Dado** `version` igual a la instalada, **entonces** `already_installed`
   sin token; **dado** `version` menor que la instalada, la vista previa lo
   marca como `downgrade` con un aviso.

### Historia 3 — Actualizar el OS y el Supervisor (Prioridad: P1)

Quien actualiza el OS quiere saber que no se aplica hasta reiniciar el host; y
quien actualiza el Supervisor, que se reinicia solo y que Core y las apps
siguen funcionando.

**Prueba independiente**: con un Supervisor simulado, cada vista previa
describe el efecto; la confirmación lanza la petición y devuelve el job que
encuentra en `/jobs/info`.

**Escenarios de aceptación**:

1. **Dado** HAOS 16.2 con 16.3 disponible, **cuando** el agente llama a
   `sv_update_os()`, **entonces** la vista previa dice 16.2 → 16.3, que se
   instala en la ranura de arranque inactiva y que se aplica al reiniciar el
   host (`sv_reboot_host`, que reinicia todo, Hermes incluido), que esta tool
   no hace backup (pista: `sv_create_backup_full` antes) y el estado de salud.
2. **Dado** una actualización del OS ya instalada y pendiente de reinicio a esa
   misma versión, **entonces** `reboot_pending` sin token.
3. **Dado** un sistema sin Home Assistant OS, **entonces** `not_haos` sin
   token y sin llamar a `/os/update`.
4. **Dado** el Supervisor con actualización, **cuando** el agente llama a
   `sv_update_supervisor()`, **entonces** la vista previa dice versión actual →
   disponible, canal, que el Supervisor se reinicia solo, que Core y las apps
   no se reinician, que las tools `sv_*` fallan durante un minuto
   aproximadamente y que no hay backup posible.
5. **Dado** el token, **cuando** se confirma el OS o el Supervisor, **entonces**
   Hermes lanza la petición, devuelve el `job_id` del job encontrado por su
   nombre, o, si no aparece a tiempo, `status: started` y con qué tool
   comprobar la versión.

### Historia 4 — Instalar la actualización de un dispositivo o una integración (Prioridad: P2)

Quien tiene firmware de un dispositivo o una integración con entidad `update`
quiere leer sus notas e instalarla con una vista previa que diga qué cambia.

**Prueba independiente**: en el banco, con una entidad `update` de plantilla,
`ha_install_update` da la vista previa, no cambia nada hasta confirmar e
instala al confirmar; el lector independiente ve la versión nueva.

**Escenarios de aceptación**:

1. **Dado** una entidad con `release_notes`, **cuando** el agente llama a
   `ha_get_update_release_notes`, **entonces** recibe las notas redactadas,
   recortadas y marcadas como texto de terceros; **dado** una que no las
   admite, recibe `supported: false` con `release_summary` y `release_url`.
2. **Dado** una entidad con actualización, **cuando** se llama a
   `ha_install_update(entity_id)`, **entonces** la vista previa dice versión
   instalada → destino, el título, las notas recortadas (o el resumen), si
   habrá backup y que el modo lo decide la integración, y si es firmware, que
   no se corte la alimentación.
3. **Dado** `backup=true` en una entidad sin backup, o `version` en una sin
   versión concreta, o una sin actualización, o una ya instalando,
   **entonces** error sin token y sin llamar a Core.
4. **Dado** la entidad `update` de Core, del OS o del Supervisor, **entonces**
   `use_dedicated_tool` con la tool `sv_update_*` y los argumentos
   equivalentes, sin token; **dado** la de una app, `sv_update_addon`; **dado**
   la de Hermes, `self_update_not_supported`.
5. **Dado** el token, **cuando** se confirma, **entonces** Hermes llama a
   `update.install` con la versión de la vista previa; si la instalación tarda
   más que la espera, la respuesta dice que sigue en HA y cómo seguirla.

### Historia 5 — Nada de lo que funciona hoy cambia (Prioridad: P1)

Quien usa la 1.1.2 quiere que sus llamadas sigan igual, y quien no quiere
estas tools, poder apagarlas.

**Escenarios de aceptación**:

1. **Dado** `ha_call_service("update", "install", …)` como en la 1.1.2,
   **entonces** sigue pidiendo token y funcionando igual; su vista previa gana
   solo una `hint` que recomienda `ha_install_update`.
2. **Dado** `tool_families_disabled: [system_updates]`, **entonces** las 8
   tools nuevas no se registran y sus entradas siguen `dedicated` en la tabla
   (la genérica sigue rechazándolas).

### Casos límite

- `version` con forma inválida (espacios, `/`, `..`, más de 32 caracteres) →
  `invalid_argument` sin llamar al Supervisor ni a Core; el log no copia el
  valor.
- `entity_id` que no es `update.<objeto>` → `invalid_argument` sin llamar.
- Supervisor caído o Core caído en la vista previa: lo que no se pueda leer
  sale como `null` con `unavailable` en su bloque; si falta la versión actual o
  la de destino, no hay token (no se puede describir el efecto).
- La comprobación de configuración tarda: la vista previa espera hasta 120 s;
  si vence, `config_check: {result: "timeout"}` y bloquea.
- `/core/check` responde error → el detalle se redacta y se recorta.
- Respuesta de `/core/update` sin `job_id` (terminó antes de responder) →
  `result: ok` con la versión pedida.
- La conexión con el Supervisor se corta al confirmar el Supervisor (se está
  reiniciando) → no es un error: `status: started` con la pista de comprobar
  con `sv_get_supervisor_info`.
- `update.install` tarda más que la espera de Hermes (30 s) → Core sigue
  instalando (protege la llamada con `shield`); la respuesta dice
  `status: running` y que se siga con `ha_list_updates`.
- Notas de versión más grandes que el tope → se recortan con `truncated`; en la
  vista previa, a 1500 caracteres.
- Dos actualizaciones a la vez: el Supervisor rechaza la segunda
  (concurrencia del job); el error llega redactado.

## Requisitos *(obligatorio)*

Cada FR cita el FR de la 008 y la CAP que cubre.

### Requisitos funcionales

#### Listar y buscar actualizaciones (CAP-080)

- **FR-001**: `sv_list_available_updates()` lee `GET /available_updates` y
  completa cada elemento con su versión instalada (`/core/info`,
  `/supervisor/info` —que trae las apps—, `/os/info` solo con Home Assistant
  OS) y los plugins (`/{dns,audio,cli,observer,multicast}/info`). Cada
  elemento: `type` (`core`, `os`, `supervisor`, `addon`, `plugin`), `name`,
  `slug` (apps y plugins), `installed_version`, `latest_version` y
  `update_with` (la tool, o la ruta de la tabla para plugins, o `null` con una
  nota para Hermes). Sobre `{count, items, truncated}` (008 FR-049, FR-018;
  CAP-080).
- **FR-002**: `sv_check_for_updates()` llama a `POST /refresh_updates` (recarga
  el registro de versiones y la tienda) con una espera de 120 s y devuelve la
  lista de FR-001. No pide token: no borra, no interrumpe y no toca secretos
  (008 FR-049; CAP-080).

#### Actualizar Core, OS y Supervisor (CAP-080)

- **FR-003**: La vista previa de `sv_update_core`, `sv_update_os` y
  `sv_update_supervisor` tiene siempre los mismos bloques: `component`,
  `from_version`, `to_version`, `downgrade`, `release_notes` (`available`,
  texto recortado si lo hay, `release_url` de la entidad `update` si Core la
  da, y por qué no hay notas si no las hay), `backup` (`will_create`, qué
  contiene, nombre, ubicación o por qué no hay), `restarts` (qué se reinicia y
  qué deja de responder), `system_health` (`unhealthy`, `unsupported` e issues
  de `/resolution/info`), `blocked` (lista de motivos, vacía si nada bloquea) y
  `warnings`. Nada se describe que no vaya a ocurrir (principio IV; 008
  FR-049; CAP-080).
- **FR-004**: Si `blocked` no está vacío, o si no se pueden leer la versión
  actual o la de destino, la tool devuelve la vista previa **sin**
  `confirmation_token` y con `error: "update_blocked"` (o el error concreto).
  Motivos que bloquean y se comprueban: sistema no saludable (`HEALTHY`);
  Supervisor con actualización pendiente (`SUPERVISOR_UPDATED`, para Core y
  OS); plugins desactualizados con la actualización automática del Supervisor
  apagada (`PLUGINS_UPDATED`, Core); menos de 2 GB libres según `/host/info`
  (`FREE_SPACE`, Core); OS pendiente de reinicio a la misma versión
  (`reboot_pending`); configuración de Core inválida o sin respuesta (Core).
  Con plugins desactualizados y la actualización automática activa, un aviso
  dice que el Supervisor los actualizará antes (008 FR-049; principio III;
  CAP-080).
- **FR-005**: `sv_update_core(version=None, backup=True)`: destino = `version`
  o `version_latest` de `/core/info`; la vista previa ejecuta
  `POST /core/check` (sin escribir `check_config_state.json`) y da su
  resultado; `backup` describe el backup parcial que hace el Supervisor
  (`core_<versión actual>`, solo Home Assistant, `exclude_database` según
  `/core/info`, en la ubicación por defecto); `restarts` dice que Core se para
  y arranca en la versión nueva, que las tools `ha_*` fallan mientras tanto,
  que Hermes sigue en marcha y que, si la nueva no arranca, el Supervisor
  intenta volver a la anterior. Al confirmar: `POST /core/update` con
  `{version: <destino>, backup, background: true}` y el `job_id` seguido como
  en `sv_update_addon` (008 FR-049; CAP-080).
- **FR-006**: `sv_update_os(version=None)`: solo con Home Assistant OS (si
  `/os/info` responde 404, `not_haos` sin token); destino = `version` o
  `version_latest`; `restarts` dice que no reinicia nada al instalar, que se
  instala en la ranura inactiva, que se aplica al reiniciar el host con
  `sv_reboot_host` y que el Supervisor abre el aviso `reboot_required`;
  `backup.will_create` es `false` con la pista de crear uno antes. Al
  confirmar: `POST /os/update` con `{version: <destino>}` (008 FR-049;
  CAP-080).
- **FR-007**: `sv_update_supervisor()`: sin `version` (el Supervisor solo la
  admite en desarrollo); sin actualización disponible → `no_update_available`
  sin token; destino = `version_latest` de `/supervisor/info`; `restarts` dice
  que el Supervisor se reinicia solo, que Core y las apps no se reinician y que
  las tools `sv_*` fallan durante un minuto aproximadamente; `backup` no es
  posible. Al confirmar: `POST /supervisor/update` sin cuerpo (008 FR-049;
  CAP-080).
- **FR-008**: El token de las tres va atado a los argumentos **y** al destino
  resuelto (`to_version`) y al `from_version`. Al confirmar, la tool vuelve a
  leer las versiones antes de validar el token; si no coinciden con las de la
  vista previa, el token no coincide, no se gasta, no se envía nada y la
  respuesta lleva `preview_outdated: true` y la pista de pedir otra vista
  previa. La ejecución envía siempre la versión explícita cuando la ruta la
  admite (principio IV; 008 FR-049; CAP-080).
- **FR-009**: La ejecución de OS y Supervisor (rutas sin `background`) lanza la
  petición en segundo plano dentro de Hermes (espera máxima 1800 s, el
  Supervisor la protege con `shield`) y busca en `GET /jobs/info`, durante
  hasta 10 s, el job no terminado con su nombre (`os_manager_update`,
  `supervisor_update`); si lo encuentra, devuelve `job_id` y
  `poll_with: sv_get_job_status` y lo registra con `_track_job`; si no,
  `status: started` con `verify_with` (`sv_get_os_info` o
  `sv_get_supervisor_info`). Un corte de conexión durante la actualización del
  Supervisor no es un error. El resultado final de la petición en segundo
  plano queda en el log de Hermes (008 FR-049; CAP-080).
- **FR-010**: `version` se valida antes de llamar a nada:
  `^[0-9][0-9A-Za-z.]{0,31}$`; lo inválido es `invalid_argument` con la regla y
  sin copiar el valor. Igual que hoy en `sv_update_addon`, ninguna vista previa
  de estas tools se emite para una acción imposible (principio III; 008
  FR-049).

#### Entidades `update` (CAP-064)

- **FR-011**: `ha_list_updates(include_up_to_date=False)` lee los estados del
  dominio `update` y, con una lectura del registro de entidades, devuelve por
  entidad: `entity_id`, `title`, `installed_version`, `latest_version`,
  `skipped_version`, `in_progress`, `update_percentage`, `auto_update`,
  `device_class`, `supports` (`install`, `specific_version`, `backup`,
  `release_notes`, `progress`, decodificados de `supported_features`),
  `release_summary` recortado, `release_url` e `install_with`
  (`ha_install_update` o la tool `sv_*` de FR-014). Por defecto solo las que
  tienen actualización (`state: on`). Sobre común con `_third_party_text`
  (008 FR-050, FR-018; CAP-064).
- **FR-012**: `ha_get_update_release_notes(entity_id)` llama a
  `update/release_notes`; si la entidad no las admite, devuelve
  `supported: false` con `release_summary` y `release_url` del estado. Las
  notas pasan por `redact_secrets`, se recortan al tope con `truncated` y van
  marcadas como texto de terceros (008 FR-050; CAP-064).
- **FR-013**: `ha_install_update(entity_id, version=None, backup=False)`:
  rechaza sin token y sin llamar a Core lo que Core rechazaría
  (`no_update_available`, `specific_version_not_supported`,
  `backup_not_supported`, `update_in_progress`, entidad inexistente). Vista
  previa: `title`, `from_version`, `to_version` (`version` o
  `latest_version`), `downgrade`, notas recortadas a 1500 caracteres (o
  `release_summary`), `release_url`, `backup` (si se pide, que lo hace la
  integración y cómo depende de ella), la integración (`platform` del
  registro) y, si `device_class` es `firmware`, un aviso de no cortar la
  alimentación. Token atado a `from_version` y `to_version` como en FR-008.
  Ejecución: `update.install` con `version` explícita y `backup`, con la
  espera de 30 s del cliente REST; si vence, `status: running` (Core sigue la
  instalación) y la pista de seguirla con `ha_list_updates` (008 FR-050;
  CAP-064).
- **FR-014**: Encaminamiento: si la entidad es de la plataforma `hassio`
  (registro de entidades) con `unique_id`
  `home_assistant_core_version_latest`, `home_assistant_os_version_latest` o
  `home_assistant_supervisor_version_latest`, `ha_install_update` devuelve
  `use_dedicated_tool` con `sv_update_core`, `sv_update_os` o
  `sv_update_supervisor` y los argumentos equivalentes; si es la de una app
  (`<slug>_version_latest`), `sv_update_addon` con el `slug`, y si la app es
  Hermes, `self_update_not_supported`. Nunca emite token para ellas (008
  FR-050; CAP-064, CAP-080).
- **FR-015**: `ha_call_service("update", "install", …)` no cambia de
  comportamiento (sigue en la denylist y pide token); su vista previa gana una
  `hint` que recomienda `ha_install_update` (008 FR-050, FR-020; CAP-064).

#### Tabla de clasificación

- **FR-016**: Pasan a `dedicated`, en el mismo cambio que su tool, con la
  familia `system_updates`: `GET /available_updates`
  (`sv_list_available_updates`); `POST /refresh_updates` y
  `POST /reload_updates` (`sv_check_for_updates`); `POST /core/update` y el
  comando `hassio/update/core` (`sv_update_core`); `POST /os/update`
  (`sv_update_os`); `POST /supervisor/update` (`sv_update_supervisor`);
  `update/release_notes` (`ha_get_update_release_notes`). Las entradas de
  clase A conservan su CAP. Siguen `deny` los alias `/homeassistant/update` y
  `/supervisor/available_updates`. Regenerar con
  `scripts/inventario/generar_tabla.py` deja la tabla idéntica; ninguna entrada
  queda «pendiente de tool dedicada (spec 015)» (008 FR-012, FR-049, FR-050;
  CAP-001).

#### Convenciones, familia, guía, banco y documentación

- **FR-017**: Las 8 tools nuevas van en la familia `system_updates` (1.2.0,
  desactivable; módulos `system_updates` y `update_entities`). Anotaciones en
  `tools/_annotations.py`, por nombre exacto donde el prefijo no basta:
  `sv_update_core`, `sv_update_os`, `sv_update_supervisor` y
  `ha_install_update` destructivas y de mundo abierto;
  `sv_check_for_updates` no de solo lectura, no destructiva, de mundo abierto;
  `ha_get_update_release_notes` de solo lectura y de mundo abierto;
  `sv_list_available_updates` y `ha_list_updates` de solo lectura y sin mundo
  abierto. Títulos con `OS`. Con la familia desactivada no se registran y sus
  entradas siguen `dedicated` (008 FR-010, FR-018; CAP-004).
- **FR-018**: Secretos y log: las notas, los errores del Supervisor y de Core y
  el detalle de `/core/check` pasan por `redact_secrets`; las respuestas JSON,
  por `redact_structure`. El log de Hermes lleva tool, componente, versiones y
  resultado; nunca el texto de las notas, del error de configuración ni un
  `version` inválido. Un test con centinelas lo comprueba (008 FR-019;
  principio II).
- **FR-019**: Las 216 tools de la 1.1.2 conservan nombre, anotaciones y
  argumentos; `ha_call_service` solo cambia el contenido de una vista previa
  (FR-015) (008 FR-020).
- **FR-020**: `hermes_guide` tiene el tema `updates` (alias `update`,
  `upgrade`) que explica el orden (Supervisor → Core → OS y reiniciar), los
  bloqueos, el token atado al destino, el seguimiento por job y el
  encaminamiento de las entidades; el tema `supervisor` lo menciona (008
  FR-011, FR-018).
- **FR-021**: Banco de Core: una entidad `update` de plantilla en la
  configuración del banco (instala escribiendo un `input_text` que el lector
  independiente lee); se ejecutan de verdad `ha_install_update` (vista previa
  sin cambios, confirmación, con y sin `version`, con `backup`) y las lecturas
  `ha_list_updates` y `ha_get_update_release_notes` (camino sin notas).
  `ha_install_update` entra en el inventario de cobertura del banco como
  probada; las cuatro `sv_*` que modifican, como no ejecutables con su motivo
  (Supervisor simulado) y pendientes manuales en la VM de la 014 (008 FR-015,
  FR-016; CAP-034).
- **FR-022**: Documentación en el mismo cambio: sección «Actualizaciones del
  sistema» en `## [1.2.0]` de `hermes/CHANGELOG.md`; estado de la 015 en la
  tabla del programa de `docs/HOJA-DE-RUTA.md`, con la prueba real de las
  `sv_update_*` y `sv_check_for_updates` como pendiente manual; `README.md` y
  `README.es.md` sincronizados si nombran familias o recuentos;
  `hermes/DOCS.md` con la familia en la lista de `tool_families_disabled`;
  filas CAP-064 y CAP-080 de la matriz de la 008 con las tools y los ficheros
  de test (008 FR-016, FR-021, FR-023, FR-024).

### Entidades clave

- **Actualización disponible**: `type`, `name`, `slug`, `installed_version`,
  `latest_version`, `update_with`, nota.
- **Vista previa de actualización**: los bloques de FR-003.
- **Bloqueo**: código (`unhealthy`, `supervisor_update_pending`,
  `plugins_outdated`, `low_disk_space`, `reboot_pending`, `config_invalid`,
  `config_check_failed`) y mensaje.
- **Entidad `update`**: la de FR-011.
- **Entrada de la tabla**: la de la 011; cambian categoría, motivo, familia y
  tool (data-model).

## Fuera de alcance

- La tienda de apps, el changelog de una app y actualizarla a una versión
  concreta (030); mejorar la vista previa de `sv_update_addon` (030).
- Actualizar, reiniciar u opciones de los plugins (022, por la tabla).
- El ajuste de backup previo de la integración `backup`
  (`hassio/update/config/*`, 031) y la vía `hassio/update/core` con ese backup.
- Saltar o recuperar una versión (`update.skip`, `update.clear_skipped`):
  siguen por `ha_call_service` sin token, como hoy.
- Cambiar el canal del Supervisor (clase D, D-01 de la 008) o la actualización
  automática (022).
- Elegir la ranura de arranque o reiniciar el host tras actualizar el OS (032 y
  `sv_reboot_host`).
- Que Hermes se actualice a sí mismo (D-1).
- Salir a internet a buscar notas de versión.

## Supuestos

- **S-01**: Antes de implementar están integradas en la rama la 009 (rechazo
  de `sv_update_addon` sobre Hermes, `## [1.2.0]`), la 010 (banco y su
  inventario de cobertura), la 011 completa y, de la 013, el título `OS` y la
  regla del test de la tabla que admite `dedicated`. Si falta la 013, el
  tramo que los necesita hace esos dos cambios mínimos (la regla, el tramo 1;
  el título, el tramo 2) y lo anota para la fusión.
- **S-02**: Las respuestas del Supervisor simulado salen del código del
  Supervisor 2026.11.0 leído y usan datos ficticios.
- **S-03**: Hermes usa la API v1 del Supervisor con `hassio_role: admin`; con
  `manager`, `POST /refresh_updates` y el resto de rutas de esta sub-feature
  siguen permitidas (`/reload_updates`, no).
- **S-04**: Las entidades `update` del Supervisor se reconocen por la
  plataforma `hassio` y su `unique_id` (Core 2026.11.1,
  `components/hassio/entity.py`), no por su `entity_id`, que el usuario puede
  renombrar.

## Criterios de éxito *(obligatorio)*

- **SC-001**: Las 8 tools están registradas con la configuración por defecto,
  con las anotaciones de FR-017, y ninguna con `system_updates` desactivada.
- **SC-002**: Las 8 entradas de FR-016 son `dedicated` y apuntan a una tool
  registrada de la familia; ninguna queda «pendiente de tool dedicada (spec
  015)»; regenerar la tabla no cambia nada.
- **SC-003**: En el 100 % de los casos probados de bloqueo, argumento inválido,
  entidad encaminada o acción imposible no se emite token ni se llama a la ruta
  o servicio de actualización.
- **SC-004**: En el 100 % de las confirmaciones probadas, la versión enviada es
  la de la vista previa; con el destino cambiado, `preview_outdated` y ninguna
  llamada.
- **SC-005**: Ningún centinela de secreto aparece en respuestas, vistas
  previas, errores ni log de las 8 tools.
- **SC-006**: `ha_install_update` se ejecuta en el banco contra HA Core real y
  el lector independiente ve la versión instalada; antes de confirmar, no ve
  cambios.
- **SC-007**: Con las familias de la 1.2.0 desactivadas, la lista de tools es
  la de la 1.1.2 con las mismas anotaciones.
- **SC-008**: La suite pasa en el CI de Linux al final de cada tramo, con los 6
  fallos conocidos de Windows en local y ninguno más; cada tramo deja anotado
  su control negativo con recuentos.
- **SC-009**: La hoja de ruta lista la prueba real de las cuatro `sv_*` que
  modifican como pendiente manual en la VM de la 014.

## Dudas para el final

- **D-1**: Que Hermes pueda actualizarse a sí mismo a través de Core
  (`update.install` sobre su entidad lo pide Core, no el add-on, y el
  Supervisor lo permitiría). Hoy se rechaza como en la 009; habría que decidir
  qué pasa con la llamada que se corta al reiniciarse Hermes.
- **D-2**: Si `sv_update_os` debería ofrecer `backup=True` creando antes un
  backup parcial de Core, como hace la entidad del OS en la interfaz de HA (con
  la integración `backup`). Hoy no lo hace y lo dice.
- **D-3**: Si la configuración de Core inválida debe poder saltarse con un
  argumento explícito (por ejemplo, para actualizar precisamente para arreglar
  una incompatibilidad). Hoy bloquea sin excepción.
