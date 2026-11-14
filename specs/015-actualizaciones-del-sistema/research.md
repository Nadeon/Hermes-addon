# Research: actualizaciones del sistema (015)

Fase 0 del plan. Cada decisión dice qué se eligió, por qué y qué se descartó.
Todo lo afirmado sobre HA se leyó en el código de Core 2026.11.1 y del
Supervisor 2026.11.0 (solo lectura); las rutas de fichero son relativas a cada
proyecto.

## Hechos comprobados de partida

- **H-1**: En Core 2026.11.1 la integración `hassio` ya no tiene las acciones
  `hassio.core_update`, `os_update` ni `supervisor_update` (siguen en la
  denylist de `service_policy.py` por si una versión anterior las tuviera). La
  vía actual es `update.install` sobre la entidad `update`, en la denylist: pide
  token, pero la vista previa de `ha_call_service` solo enseña dominio,
  servicio y datos.
- **H-2**: `sv_update_addon` sobre el propio Hermes lo rechaza el Supervisor
  (403 «can't update itself»); la 009 lo rechaza antes con
  `self_update_not_supported`.
- **H-3**: La tabla de la 011 deja «pendiente de tool dedicada (spec 015)»:
  `update/release_notes`, `GET /available_updates`, `POST /reload_updates`,
  `POST /core/update`, `POST /os/update` y `POST /supervisor/update`.
  `hassio/update/core` está `dedicated` apuntando a `ha_call_service` (familia
  `services`); `POST /refresh_updates` y `GET /supervisor/available_updates`,
  `deny` como alias de clase B; los `/{plugin}/update`, `confirm` (CAP-091,
  022).
- **H-4**: Línea base de la suite al especificar (rama de la 011, punta
  `2d53a0a`): 2139 passed, 17 skipped, 6 failed (los 6 conocidos de Windows).

## R-1 — Una familia, dos módulos

**Decisión**: familia `system_updates` («desde» 1.2.0, desactivable) con los
módulos `system_updates` (cinco `sv_*`) y `update_entities` (tres `ha_*`). Tema
de guía `updates`.

**Por qué**: es un solo asunto para el usuario («mantener el sistema al día»)
y las dos mitades se llaman entre sí (el encaminamiento de FR-014 nombra las
`sv_*`; la lista de las `sv_*` remite a las entidades). Dos módulos para que
ninguno pase de unas 500 líneas y cada tramo toque uno.

**Descartado**: meterlas en `supervisor` o `services` (familias de la 1.1.2:
FR-010 de la 008 lo prohíbe); dos familias (el usuario apagaría media
funcionalidad sin entender por qué).

## R-2 — `POST /refresh_updates` para buscar actualizaciones

**Decisión**: `sv_check_for_updates` llama a `POST /refresh_updates`.
`/refresh_updates` y `/reload_updates` pasan ambas a `dedicated` hacia esa
tool.

**Por qué** (`api/root.py`, `api/__init__.py`, `api/middleware/security.py`):

- `refresh_updates` hace `sys_updater.reload()` **y** `sys_store.reload()`;
  `reload_updates`, solo el primero. Sin recargar la tienda, las
  actualizaciones de apps no aparecen: no es un alias exacto, aunque el
  inventario de la 008 lo clasifique como «alias desaconsejado» (clase B).
- En la API v1, el patrón del rol `manager` incluye `/refresh_updates` y
  `/available_updates`, pero **no** `/reload_updates` (que solo está en el
  patrón de `manager` de la v2). Hermes usa la v1 con `admin`; si un día baja a
  `manager` (D-02 de la 008), `/reload_updates` daría 403.
- `/available_updates` y `/refresh_updates` existen solo en la v1
  («Discouraged»). Hermes no usa la v2 (S-03 de la 013).

**Descartado**: `/reload_updates` (no refresca apps; 403 con `manager`).
`/supervisor/available_updates` (alias «Remove: 2023») sigue `deny`.

## R-3 — El token se ata al destino resuelto

**Decisión**: la vista previa resuelve `from_version` y `to_version`; el
`action_hash` del token se calcula con los argumentos **más** esas dos
versiones. Al confirmar, la tool vuelve a leerlas **antes** de validar el
token y calcula el hash con lo recién leído. Si cambiaron, el hash no
coincide: `resolve_confirmation_token` no marca el token (no se gasta), no se
envía nada y la respuesta es el error de siempre («does not match this
action») con `preview_outdated: true` y una `hint` que dice que el token está
atado a los argumentos y a las versiones de origen y destino y que hay que
pedir otra vista previa. La tool no guarda la vista previa, así que no
distingue «cambió la versión» de «cambiaron los argumentos»: en los dos casos
lo correcto es pedir otra, y `preview_outdated` se pone siempre que el token
no coincide. La ejecución envía `version` explícita.

**Por qué**: sin `version`, el Supervisor instala «la última» que tenga en ese
momento (`api/homeassistant.py`: `body.get(ATTR_VERSION, latest_version)`). Si
entre la vista previa y la confirmación corre un `refresh_updates`
(automático o manual), la vista previa habría mentido (principio IV).

**Cómo**: `security.py` calcula el hash con los argumentos que la tool le pase
(`compute_action_hash(tool_name, args)`), así que basta con pasar
`{**args, "_from_version": …, "_to_version": …}` a `create_confirmation_token`
y a `validate_confirmation_token`. Sin estado nuevo en memoria ni en disco;
funciona tras un reinicio de Hermes dentro del TTL.

**Descartado**: reutilizar `omitibles` para guardar las versiones (anunciaría
al cliente que puede omitir argumentos que no existen); un registro en memoria
`token → versiones` (se pierde al reiniciar y añade estado); no atar el
destino (la vista previa podría mentir).

## R-4 — Notas de versión de Core, OS y Supervisor

**Hecho** (`components/hassio/update.py`): la entidad de Core admite
`INSTALL | SPECIFIC_VERSION | BACKUP | PROGRESS` (sin `RELEASE_NOTES`); la del
Supervisor, `INSTALL | PROGRESS`; la del OS sí admite `RELEASE_NOTES`, pero
devuelve solo un aviso de reinicio (`OS_UPDATE_REBOOT_NOTICE`). Las tres dan
`release_url` (GitHub o la web de HA). Las de las apps sí tienen notas: el
apartado del changelog entre la versión instalada y la última.

**Decisión**: la vista previa de las `sv_update_*` pone
`release_notes.available: false`, el motivo («Home Assistant does not provide
release notes for <componente> locally») y la `release_url` del estado de la
entidad `update` correspondiente (buscada por plataforma y `unique_id`, R-10)
si Core responde; en el OS, el texto del aviso de reinicio. No se descarga nada
de internet.

**Por qué**: FR-049 de la 008 pide «notas de la versión recortadas», pero no
existen en la instalación; inventarlas o descargarlas de GitHub sería abrir
una vía a internet que la 004 evitó a propósito (`marketplace/repository/info`
está `deny` por eso). Es una **desviación justificada** de la letra de la 008:
se da todo lo que HA tiene.

## R-5 — Backup antes de actualizar

**Hechos**:

- `POST /core/update` admite `backup`; con `true`, el Supervisor hace
  `do_backup_partial(name=f"core_{versión actual}", homeassistant=True)`
  (`homeassistant/core.py`) en la ubicación por defecto. Excluye la base de
  datos si `backups_exclude_database` de `/core/info` es `true`.
- `POST /os/update` solo admite `version`: el Supervisor no hace backup. La
  entidad del OS de la interfaz hace uno de Core con la integración `backup`
  antes (`update_helper.update_os`).
- `POST /supervisor/update` no admite backup.
- La vía de Core (`hassio/update/core`, `update_helper.update_core`) hace el
  backup con la integración `backup` (agentes, cifrado), no con el Supervisor.

**Decisión**: `sv_update_core(backup=True)` por defecto, con el backup del
Supervisor, descrito tal cual. `sv_update_os` sin backup y con la pista de
`sv_create_backup_full`/`sv_create_backup_partial` antes (D-2).
`sv_update_supervisor`, `backup: {possible: false}`.

**Descartado**: usar `hassio/update/core` (su backup depende de la
configuración de la integración `backup`, que es de la 031, y la vista previa
tendría que describir agentes y cifrado); encadenar un backup en
`sv_update_os` (otra operación larga dentro de la ejecución; D-2).

## R-6 — Bloqueos: lo que el Supervisor rechazaría

**Hechos** (`jobs/decorator.py`, `homeassistant/core.py`, `os/manager.py`):

| Job | Condiciones |
|---|---|
| `home_assistant_core_update` | `FREE_SPACE`, `HEALTHY`, `INTERNET_HOST`, `PLUGINS_UPDATED`, `SUPERVISOR_UPDATED` |
| `os_manager_update` | `HAOS`, `HEALTHY`, `INTERNET_SYSTEM`, `RUNNING`, `SUPERVISOR_UPDATED` |
| `supervisor_update` | ninguna (concurrencia `REJECT`) |

- `HEALTHY`: falla si `/resolution/info` tiene `unhealthy`.
- `SUPERVISOR_UPDATED`: falla si el Supervisor tiene actualización.
- `PLUGINS_UPDATED`: con plugins desactualizados, si la actualización
  automática del Supervisor (`auto_update` de `/supervisor/info`) está activa,
  el Supervisor los actualiza antes; si no, falla.
- `FREE_SPACE`: menos de 2 GB libres (`MINIMUM_FREE_SPACE_THRESHOLD = 2`,
  `resolution/const.py`), lo mismo que `disk_free` de `/host/info`.
- OS: `version == version_pending` → `HassOSUpdatePendingRebootError`.
- `INTERNET_*` y `RUNNING` no se pueden leer de forma fiable desde fuera: la
  vista previa lo dice en `warnings` («the Supervisor also checks internet
  access when it runs»).

**Decisión**: lo que se puede leer bloquea (sin token); lo que no, se avisa.
Más la comprobación de configuración de Core (regla de Hermes, no del
Supervisor: actualizar con la configuración rota termina en una vuelta atrás o
en un Core que no arranca). D-3 pregunta si debe poder saltarse.

**Por qué no escribir `check_config_state.json` en la vista previa**: la vista
previa no puede tener efectos más allá de leer; `sv_check_core_config` sigue
siendo la tool que levanta el bloqueo de reinicio. `POST /core/check` en sí no
cambia nada: ejecuta `python3 -m homeassistant --script check_config` dentro
del contenedor de Core y devuelve el log si falla (`api/homeassistant.py`,
`homeassistant/core.py`). Ese log puede citar valores de la configuración:
pasa por `redact_secrets` y se recorta a 500 caracteres (FR-018).

## R-7 — Seguir la actualización del OS y del Supervisor

**Hechos**: `POST /core/update` admite `background: true` y devuelve `job_id`.
`POST /os/update` y `POST /supervisor/update` no: esperan a que termine la
descarga e instalación (el OS, el bundle entero) y protegen la tarea con
`asyncio.shield`, así que cortar la conexión no la cancela. Los jobs se llaman
`os_manager_update` y `supervisor_update` y salen en `GET /jobs/info`
(`api/jobs.py`) con `uuid`, `name` y `done`. El del Supervisor termina con un
`sys_core.stop()`: el Supervisor se reinicia y pierde sus jobs.

**Decisión**: lanzar la petición en una tarea de fondo de Hermes (con una
referencia guardada para que no la recoja el recolector, y su resultado en el
log), buscar el job durante 10 s y devolverlo, o `status: started` con la tool
con que verificar la versión. Para el Supervisor, la respuesta añade que tras
el reinicio el job desaparece y `sv_get_job_status` dará error: hay que mirar
`sv_get_supervisor_info`.

**Descartado**: esperar la petición en primer plano (un cliente MCP corta en
minutos); no devolver nada que seguir (FR-049 lo pide).

## R-8 — Entidades `update` de las apps

**Hecho** (`components/hassio/update.py`): cada app instalada tiene una entidad
`update` de la plataforma `hassio` con `unique_id` `<slug>_version_latest`, con
`INSTALL | BACKUP | RELEASE_NOTES | PROGRESS`. Su `async_install` llama al
Supervisor con el token de Core, que no tiene la restricción «can't update
itself».

**Decisión**: `ha_install_update` las encamina a `sv_update_addon` (un camino
por cosa, como pide FR-050 para Core, OS y Supervisor) y la de Hermes, al
rechazo de la 009. Las notas sí se leen con `ha_get_update_release_notes`
(lectura, sin riesgo).

**Descartado**: dejar que Core actualice Hermes (D-1: la llamada se corta al
reiniciarse Hermes y la 009 decidió lo contrario); mejorar aquí la vista previa
de `sv_update_addon` con notas o versión concreta (030).

## R-9 — `ha_list_updates`

**Decisión**: tool nueva de lectura sobre los estados del dominio `update`.

**Por qué**: «listar las actualizaciones disponibles» no está completo con
`sv_list_available_updates`, que solo ve Core, OS, Supervisor y apps. El
firmware de un dispositivo (ZHA, Matter, ESPHome…), HACS o cualquier
integración con entidad `update` solo se ve por Core. `ha_get_states` lo da,
pero sin decodificar `supported_features` ni decir con qué tool se instala. La
008 estimaba unas 7 tools; quedan 8.

**Cómo**: estados por REST (`get_states`, filtrado por dominio) y una sola
petición `config/entity_registry/get_entries` con esos `entity_id` para
`platform` y `unique_id`. Ese comando es `deny` para las genéricas (clase B,
optimización de la UI), pero la tabla solo gobierna las genéricas; una tool
dedicada puede usarlo dentro.

## R-10 — Reconocer las entidades del Supervisor

**Decisión**: por el registro de entidades: plataforma `hassio` y `unique_id`
`home_assistant_core_version_latest`, `home_assistant_os_version_latest`,
`home_assistant_supervisor_version_latest` o `<slug>_version_latest`
(`components/hassio/entity.py`: prefijos `home_assistant_core`,
`home_assistant_os`, `home_assistant_supervisor` y el slug, más la clave
`version_latest`). Nunca por el `entity_id`: se puede renombrar.

## R-11 — `update.install` y la espera

**Hechos**: `update.install` valida (sin actualización y sin `version`,
`version` sin `SPECIFIC_VERSION`, `backup` sin `BACKUP`, ya en curso) y espera
a que termine la instalación (`components/update/services.py`). La API REST
de servicios la protege con `shield` y una tarea de HA
(`components/api/__init__.py`): si el cliente corta, la instalación sigue.
`ha.py` espera 30 s en `_request_json`.

**Decisión**: `ha_install_update` replica las cuatro validaciones en la vista
previa (para no emitir tokens imposibles), llama con `allow_dangerous=True`
tras validar su propio token (comentario del porqué, como el de
`ha_call_service`), y trata el `TimeoutError` de la espera como
`status: running`, no como error.

## R-12 — Probar sin actualizaciones reales

- **`sv_*`**: unitarios con un Supervisor simulado (el `MockHAClient` de
  `tests/test_tools_supervisor.py` ampliado para registrar método, ruta,
  cuerpo y espera, y responder por ruta) con las formas del Supervisor
  2026.11.0: `/available_updates`, `/core/info`, `/supervisor/info`,
  `/os/info` (y su 404), `/host/info`, `/resolution/info`, `/core/check` (bien,
  error y tiempo), `/{plugin}/info`, `/jobs/info`, `/core/update` con
  `job_id`, `/os/update` y `/supervisor/update` lentos o cortados. El banco de
  la 010 no sirve: su Supervisor simulado solo reenvía a Core. La prueba real
  queda pendiente manual en la VM de la 014 (quickstart.md).
- **`ha_*`**: banco de Core con una entidad `update` de la integración
  `template` (`components/template/update.py`): `installed_version` sale de un
  `input_text`, `latest_version` es fija, `specific_version: true`,
  `backup: true` y la acción `install` escribe en el `input_text` la versión
  pedida (variable `specific_version`) y en un `input_boolean` si se pidió
  backup (variable `backup`). El lector independiente lo comprueba. La
  plantilla no admite `release_notes`: el camino con notas se prueba en
  unitarios. El encaminamiento a las `sv_*` también (en el banco no hay
  integración `hassio`).
- Se descarta la integración `demo` en el banco: arrastra decenas de
  plataformas y su instalación con progreso duerme por pasos.

## R-13 — Hallazgos sobre el inventario de la 008

- `POST /os/update`: el inventario dice «reinicia»; no reinicia: instala en la
  ranura inactiva y abre el aviso `reboot_required` (`os/manager.py`).
- `POST /refresh_updates`: no es un alias exacto de `/reload_updates` (R-2).

Se anotan en la matriz de la 008 al cerrar; el TSV no se cambia (lo regenera
el extractor de la 011).
