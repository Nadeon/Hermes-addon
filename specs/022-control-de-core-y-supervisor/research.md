# Investigación: control de Core y del Supervisor (022)

Fuentes: `specs/008-cobertura-total/` (FR-076…FR-080; research CAP-084,
CAP-087, CAP-091, CAP-092, CAP-094 y R-4; plan, matriz de trazabilidad;
`inventario/supervisor-rutas.tsv`), el código de Hermes en la punta `c4a57bf`
de `feat/cobertura-total` y el código del Supervisor 2026.11.0 (solo leído).

## Lo que hay hoy (comprobado en el código)

- `tools/supervisor.py` (familia `supervisor`, 1.1.2): `sv_restart_core` y
  `sv_reboot_host` con token sin argumentos; `sv_restart_core` se niega si hay
  escrituras en `/config` sin un `sv_check_core_config` posterior
  (`fs_write.check_restart_allowed_sync`), en la vista previa (`blocked`) y
  otra vez al confirmar. Ninguna de las dos toca opciones.
- `tools/addons.py`: `_es_hermes(slug)` reconoce el propio add-on (hostname,
  `self`, `*_hermes`) y `_self_warning`; `_LONG_OP_TIMEOUT = 300`.
- `tools/resolution.py` (familia `diagnostics`, 1.1.2): leer, descartar issue y
  descartar sugerencia. Su docstring, la guía (`diagnostics`), `README.md`
  (fila de Diagnostics y la sección de seguridad) y el test
  `TestNuncaAplicaSugerencias` de `tests/test_tools_resolution.py` dicen que
  **Hermes nunca aplica una sugerencia**. Era una decisión de la 1.1.x; FR-077
  de la 008 la cambia de forma explícita (R-6).
- `security.py`: `create_confirmation_token(tool, args, preview, estado=…)` y
  `resolve_confirmation_token(…, estado=…)` (018) atan el token también al
  estado leído en la vista previa (`ESTADO_CAMBIADO` si cambia). Los tokens
  viven en disco: sobreviven a un corte de la conexión con Core.
- `health.py`: con Core caído, `/health` sigue respondiendo 200 (`degraded`,
  luego `degraded_long`); el watchdog del Supervisor no reinicia Hermes y el
  bucle de reconexión de `ha.py` vuelve solo. **Hermes funciona con Core
  parado**: sus tools `sv_*` hablan con el Supervisor (`sv_request`), no con
  Core. El WebSocket de Core va por el proxy del Supervisor
  (`ws://supervisor/core/api/websocket`), así que **reiniciar el Supervisor
  corta también la conexión con Core** hasta que vuelve.
- `command_table.py`: 14 entradas «pendiente de tool dedicada (spec 022)»
  (`grep -c` = 14). Las de CAP-091 (plugins), CAP-092 (Docker) y CAP-094
  (placas y hora) ya están clasificadas por la 011 como `read`/`confirm`, con
  su CAP. `/core/stop` está `deny` (clase D). Los alias `/homeassistant/*`,
  `deny`.
- `scripts/inventario/generar_tabla.py`: `_DEDICADAS_INICIALES` es el
  mecanismo para que una clave A pase a `dedicated` al regenerar.
- `tests/test_command_table.py`: `_POR_LA_TABLA` admite `read`/`confirm` en
  una clave de una CAP con vía `D`/`D+T` si lleva «spec NNN: porqué».
- `tests/fixtures/supervisor_diagnostico.py` (013): `SupervisorSimulado` con
  la forma del Supervisor 2026.11.0 y `CENTINELA_PASSWORD`.

### Supervisor 2026.11.0

| Ruta | Código | Qué hace de verdad |
|---|---|---|
| `POST /core/start` | `api/homeassistant.py` `start` (`@require_running_system`); `homeassistant/core.py` `start` | Si Core ya corre, solo avisa en su log y vuelve. Si no, arranca el contenedor (o lo crea) y espera a que responda. |
| `POST /core/rebuild` | `rebuild` con `SCHEMA_RESTART` (`safe_mode`, `force`) | Comprueba que no haya una migración offline de la base de datos (salvo `force`), para Core y lo vuelve a arrancar; con `safe_mode` crea el marcador de modo seguro. Job `home_assistant_core_rebuild` (`GROUP_REJECT`). |
| `POST /core/options` | `options` con `SCHEMA_OPTIONS` | Guarda `boot`, `image`, `port`, `ssl`, `watchdog`, `refresh_token`, `audio_input`, `audio_output`, `backups_exclude_database`, `duplicate_log_file`. **No reinicia nada**; `duplicate_log_file` y el audio se aplican al crear el contenedor (próximo arranque o rebuild). |
| `GET /core/stats` | `stats_v1` | CPU, memoria, red y bloques del contenedor de Core; `HomeAssistantNotRunningError` si no corre. |
| `POST /supervisor/reload` | `reload` | Vuelve a leer las versiones (sale a internet si hay conectividad), recarga `secrets` y reevalúa el sistema. Nada se corta. |
| `POST /supervisor/restart` | `restart` → `Supervisor.restart` (`exit_code = 100`, `core.stop`) | Reinicio «suave» del contenedor del Supervisor: responde cuando entra en `STOPPING`; la API y el proxy de Core desaparecen hasta que el sistema lo vuelve a levantar. Core y las apps siguen corriendo. Un job en curso se pierde. |
| `POST /supervisor/repair` | `Core.repair` | `docker.repair` (poda contenedores parados, **imágenes sin usar**, caché de builds y **volúmenes sin usar**), repara plugins, apps y Core (descarga la imagen si falta) y re-etiqueta la del Supervisor. Espera al final: puede tardar minutos. |
| `POST /supervisor/options` (v1) | `options_v1` / `_options` | `channel`, `timezone` (también la del host), `logging`, `debug`, `debug_block`, `diagnostics` (activa o cierra Sentry), `auto_update`, `detect_blocking_io`, `country`, `feature_flags`, y en v1 `addons_repositories` y `wait_boot`. No reinicia nada. |
| `GET /supervisor/stats` | `stats_v1` | Estadísticas del contenedor del Supervisor. |
| `POST /host/reload` | `api/host.py` | Refresca la información del host (D-Bus). Nada se corta. |
| `POST /resolution/suggestion/{s}` | `apply_suggestion` → `fixup.apply_fixup` | Ejecuta **cada** fixup cuyo `(tipo, contexto)` coincida; **si no hay ninguno, no hace nada y responde ok**. Después, `healthcheck`. Un fallo del fixup vuelve como error de la API. |
| `POST /resolution/check/{c}/run`, `/options`, `POST /resolution/healthcheck` | `run_check`, `options_check`, `healthcheck` | Ejecuta un chequeo, lo activa o desactiva (`enabled`), o relanza todos. |
| `POST /core/stop` | `stop` | Para Core. Clase D (R-5). |

Fixups del Supervisor 2026.11.0 (`resolution/fixups/*.py`), es decir, los
únicos pares `(tipo, contexto)` que hacen algo:

| Tipo | Contexto | Efecto | Corta | Reversible |
|---|---|---|---|---|
| `clear_port_config` | `addon` | Quita de la app el puerto que choca | Reinicio de la app si corría | Sí (opciones de la app) |
| `disable_boot` | `addon` | La app deja de arrancar con el sistema | No | Sí |
| `execute_rebuild` | `addon` | Reconstruye el contenedor de la app | La app, minutos | Sí |
| `execute_remove` | `addon` | **Desinstala la app y borra sus datos** | La app, para siempre | **No** |
| `execute_repair` | `addon` | Descarga otra vez la imagen de la app (internet) | No | Sí |
| `execute_restart` | `addon` | Reinicia la app | La app, segundos | Sí |
| `execute_start` | `addon` | Arranca la app | No | Sí |
| `execute_rebuild` | `core` | Reconstruye el contenedor de Core | **Home Assistant, minutos** | Sí |
| `execute_reload` | `mount` | Vuelve a montar | El montaje, segundos | Sí |
| `execute_remove` | `mount` | Quita el montaje (no borra lo remoto) | El montaje | No (hay que volver a crearlo) |
| `move_local_data` | `mount` | Mueve datos locales fuera del punto de montaje y monta | El montaje | No |
| `execute_rebuild` | `plugin` | Reconstruye un plugin (DNS, audio…) | El plugin, segundos | Sí |
| `execute_reload` | `store` | Recarga un repositorio de la tienda (internet) | No | Sí |
| `execute_remove` | `store` | Quita un repositorio de la tienda | No | No (hay que añadirlo) |
| `execute_reset` | `store` | Vuelve a clonar un repositorio (internet) | No | Sí |
| `adopt_data_disk` | `system` | Renombra discos de datos y **reinicia el host** | Todo | No |
| `clear_full_backup` | `system` | **Borra los backups completos salvo los 2 más recientes** (`MINIMUM_FULL_BACKUPS = 2`) | No | **No** |
| `create_full_backup` | `system` | Hace un backup completo | No (tarda; ocupa disco) | Sí (se puede borrar) |
| `enable_ntp` | `system` | Arranca `systemd-timesyncd` | No | Sí |
| `execute_reboot` | `system` | **Reinicia el host** | Todo, minutos | — |
| `execute_rebuild` | `system` | Reconstruye todos los contenedores con la configuración de Docker mal (los de las otras sugerencias `execute_rebuild`) | Lo reconstruido | Sí |
| `rename_data_disk` | `system` | Renombra un disco de datos que choca | No (requiere reinicio después) | No |
| `execute_reset` | `system` | Limpia el estado «failed» de una unidad systemd | No | Sí |
| `execute_restart` | `system` | Reinicia una unidad systemd | Esa unidad | Sí |

`SuggestionType` tiene además `execute_stop`, `execute_update` y
`registry_login`, **sin fixup**: aplicarlas no hace nada y el Supervisor
responde ok.

## R-1 — Dos familias nuevas

**Decisión**: `system_control` (módulo nuevo `tools/system_control.py`: las
siete tools de Core y del Supervisor) y `resolution_fixes` (módulo nuevo
`tools/resolution_fixes.py`: `sv_apply_resolution_suggestion`). Las dos
«desde» 1.2.0 y desactivables. Un tema de guía, `system_control`, para las
dos.

**Por qué**: FR-010 de la 008 (tools nuevas en familias nuevas; apagando las
de la 1.2.0 la lista vuelve a la 1.1.2). Aplicar una sugerencia es lo más
arriesgado de la sub-feature (puede desinstalar una app o borrar backups) y
su caso de uso es distinto del control de Core: quien quiera reiniciar el
Supervisor pero no dejar que un agente aplique sugerencias tiene que poder
apagar solo eso. No se mete en `diagnostics` (1.1.2), que solo lee y descarta,
ni en `supervisor` (1.1.2).

**Alternativas descartadas**: una sola familia (no deja apagar lo más
peligroso por separado); meter las tools en `tools/supervisor.py` (rompería
la equivalencia de familias con la 1.1.2).

## R-2 — Qué va por tool y qué por la tabla

**Decisión**, siguiendo FR-076 y FR-077 de la 008 al pie de la letra:

| Ruta | Vía | Por qué |
|---|---|---|
| `POST /core/start` | `sv_start_core` | FR-076 |
| `POST /core/rebuild` | `sv_rebuild_core` | FR-076 |
| `POST /core/options` | `sv_set_core_options` | FR-076 |
| `POST /supervisor/reload` | `sv_reload_supervisor` (sin token) | FR-076: «con confirmación salvo recargar» |
| `POST /supervisor/restart` | `sv_restart_supervisor` | FR-076 |
| `POST /supervisor/repair` | `sv_repair_supervisor` | FR-076 |
| `POST /supervisor/options` | `sv_set_supervisor_options` | FR-076 (lista cerrada de claves) |
| `POST /resolution/suggestion/{s}` | `sv_apply_resolution_suggestion` | FR-077 |
| `GET /core/stats`, `GET /supervisor/stats` | `read` | FR-076: «estadísticas `read` en la tabla». El research de la 008 proponía `sv_get_core_stats`/`sv_get_supervisor_stats`; manda el FR. |
| `POST /resolution/check/{check}/run`, `/options`, `POST /resolution/healthcheck` | `confirm` | FR-077: «quedan `confirm` en la tabla» |
| `POST /host/reload` | `confirm` | Está en CAP-084 (research de la 008) pero FR-076 no le da tool. Es un `POST` que solo refresca datos del host: `confirm` por la tabla, sin tool nueva (principio IX). |

Las 6 entradas `read`/`confirm` de una CAP de vía `D+T` van a `_POR_LA_TABLA`
con «spec 022: porqué». Las 8 dedicadas, a `_DEDICADAS_INICIALES` del
generador. Total: 14 entradas, las 14 «spec 022».

**No es de la 022** (lo hacen otras): actualizar Core, OS y Supervisor
(`/core/update`, `/supervisor/update`, `/reload_updates`: 015); la tienda,
`/store/reload` y `rebuild` de una app (030); montajes y opciones de backup
(019); host y OS escritura (032); `sv_restart_core`, `sv_check_core_config`,
`sv_reboot_host`, `sv_restart_addon` (1.1.2, sin cambios).

## R-3 — `sv_set_core_options`: lista cerrada

**Decisión**: admite `boot`, `watchdog`, `backups_exclude_database`,
`duplicate_log_file`, `audio_input` y `audio_output`. Rechaza sin llamar
(`not_allowed`, con el motivo):

- `image`: cambia la imagen de Docker de Core por cualquiera; es ejecutar
  código arbitrario como Home Assistant (equivale a la clase D).
- `refresh_token`: es un secreto; nunca pasa por el cliente MCP (principio II).
- `port` y `ssl`: son los que usa el Supervisor para llegar a Core, y por
  tanto el proxy por el que entra Hermes. Si no coinciden con la sección
  `http:` de Core, el proxy deja de funcionar y Hermes pierde Core sin poder
  arreglarlo. Cambiar la red de Core es FR-074 (021), con su propio aviso.

**Por qué**: FR-076 no limita las opciones de Core, pero la lista del
research de la 008 para el Supervisor marca el criterio (solo lo seguro).
`boot=false` y `watchdog=false` se admiten porque son ajustes legítimos y
reversibles, con aviso fuerte en la vista previa.

## R-4 — `sv_set_supervisor_options`: lista cerrada

**Decisión**: `timezone`, `country`, `logging`, `auto_update` y
`diagnostics` (FR-076). Rechazadas sin llamar (`not_allowed`): `channel`
(candidata D-01: sigue imposible por cualquier vía, porque
`POST /supervisor/options` pasa a `dedicated` y la genérica la rechaza hacia
esta tool), `debug`, `debug_block`, `detect_blocking_io` y `feature_flags`
(ajustes de desarrollo; el inventario los marca D), y `addons_repositories` y
`wait_boot` (alias de la v1: los repositorios son de la 030).

Validación antes de llamar: `timezone` con forma de zona IANA
(`^[A-Za-z][A-Za-z0-9_+\-/]{0,63}$`; la lista real la valida el Supervisor),
`country` de dos letras mayúsculas (ISO 3166-1 alfa-2), `logging` en
`debug|info|warning|error|critical`, los demás booleanos.

**Avisos**: `auto_update=false` (en cuanto salga un Supervisor nuevo, instalar
o actualizar apps y actualizar Core quedan bloqueados hasta actualizarlo;
research de la 014); `timezone` cambia también la zona del host (la de Core
es otra cosa: FR-071, 021); `diagnostics=true` envía informes de fallos a un
tercero (Sentry); `logging=debug` llena el log.

## R-5 — Interrupción del servicio y recuperación

Criterio del supervisor del programa: todo lo que corta el servicio se
confirma en dos pasos con una vista previa honesta de **qué se corta y
cuánto**, y el token ata todo lo que cambia la acción. Si una acción dejaría a
Hermes sin poder confirmar ni recuperarse, se valora rechazarla.

| Tool | Qué se corta | Cuánto (orientativo) | ¿Hermes se recupera solo? | Decisión |
|---|---|---|---|---|
| `sv_start_core` | Nada (arranca) | HA tarda 1–5 min en estar entero | Sí: se reconecta | Confirmar. Si Core ya corre: `already_running` sin token |
| `sv_rebuild_core` | Home Assistant entero | 1–5 min (más con una imagen grande) | Sí: Hermes sigue vivo con Core caído (`health.py`) y se reconecta | Confirmar; **mismo bloqueo** que `sv_restart_core` con escrituras sin validar |
| `sv_set_core_options` | Nada ahora | — | — | Confirmar; aviso fuerte en `boot=false` y `watchdog=false` |
| `sv_reload_supervisor` | Nada | segundos | — | Sin token (FR-076) |
| `sv_restart_supervisor` | API del Supervisor **y el proxy de Core** (Hermes pierde Core y todas las `sv_*`) | ~30–90 s | Sí: el sistema levanta el Supervisor y Hermes se reconecta; Core y las apps siguen | Confirmar; **rechazo** (`jobs_in_progress`, sin token) si hay jobs en curso, porque se perderían |
| `sv_repair_supervisor` | Nada en marcha salvo lo que se repare | minutos | — | Confirmar; rechazo con jobs en curso; borra imágenes, contenedores parados y volúmenes sin usar |
| `sv_set_supervisor_options` | Nada | — | — | Confirmar |
| `sv_apply_resolution_suggestion` | Según el fixup (tabla de arriba) | según el fixup | Según el fixup | Confirmar con el efecto traducido; rechazos de R-6 |

**`/core/stop` sigue `deny`** (clase D de la 008, candidata D-01 «parar
Core»). La 008 la condicionaba a que existiera `sv_start_core` y a que el
vigilante de Hermes tolerase Core parado: las dos cosas se cumplen tras esta
sub-feature, pero decidir abrirla es del mantenedor al final del programa
(duda para el final). Lo mismo el `channel` del Supervisor.

**Ninguna tool para el Supervisor**: no existe ruta para pararlo; reiniciarlo
vuelve solo. No hay acción en esta sub-feature que deje a Hermes sin poder
recuperarse, salvo las sugerencias de R-6 que se rechazan por eso.

## R-6 — Aplicar sugerencias del centro de resolución

**Decisión**: `sv_apply_resolution_suggestion(suggestion_uuid,
confirmation_token=None)` en `resolution_fixes`. Cambia la política de la
1.1.x («Hermes nunca aplica sugerencias») porque FR-077 de la 008 lo pide; se
actualizan en el mismo cambio el docstring de `tools/resolution.py`, el tema
`diagnostics`, `README.md`/`README.es.md` y el test de guarda, que pasa a
«solo `resolution_fixes.py` hace `POST /resolution/suggestion/…`, y solo
después de validar el token».

Vista previa: lee `/resolution/info`, localiza la sugerencia y sus issues
(misma `context`/`reference`), y traduce `(type, context)` con la tabla de
fixups de arriba a `effect`, `interrupts`, `duration`, `reversible` y
`warnings`. Datos concretos cuando se pueden leer sin escribir:

- `clear_full_backup`: la lista de backups completos que se borrarían (todos
  menos los 2 más recientes, por fecha, de `/backups`), con nombre, fecha y
  tamaño. Si quedan 2 o menos, `effect` dice que no borrará nada.
- `execute_rebuild`/`system`: los contenedores que se reconstruirían (las
  demás sugerencias `execute_rebuild`).
- contexto `addon`: nombre y estado de la app (`/addons/{slug}/info`).
- `also_auto_applied`: tras el fixup, el Supervisor lanza `healthcheck()`,
  que ejecuta `run_autofix()` (`resolution/module.py`, `apply_suggestion`):
  las demás sugerencias con `auto: true` (reparar la imagen de una app,
  reconstruir un plugin, recargar o volver a clonar un repositorio) pueden
  aplicarse en la misma llamada. La vista previa las lista; lo mismo avisa la
  entrada `confirm` de `POST /resolution/healthcheck`.

**Rechazos sin token (fail-closed, principio III)**:

| Código | Cuándo | Por qué |
|---|---|---|
| `suggestion_not_found` | El uuid no está en `/resolution/info` | No hay nada que enseñar |
| `no_fixup` | `(type, context)` sin fixup en el Supervisor 2026.11.0 (`execute_stop`, `execute_update`, `registry_login`, o un par que no esté en la tabla) | El Supervisor respondería ok sin hacer nada: sería mentir (principio V) |
| `unknown_effect` | Un par que el Supervisor tenga y Hermes no traduzca (versión futura) | Sin vista previa honesta no hay token |
| `not_allowed` | `adopt_data_disk` y `rename_data_disk` | Renombran discos de datos y reinician: equivalen a mover el disco de datos, que la 008 deja en clase D; desde la interfaz |
| `targets_hermes` | Contexto `addon` con la referencia del propio Hermes (`_es_hermes`), `execute_rebuild`/`system` cuando entre lo reconstruido está Hermes, o una de `also_auto_applied` sobre Hermes | Hermes se cortaría a sí mismo a mitad de la llamada (o se desinstalaría) y no podría informar ni recuperarse |

`execute_reboot`, `execute_remove` (app), `clear_full_backup` y
`execute_rebuild`/`core` **se permiten** con aviso fuerte: ya existen tools
con token que hacen lo mismo (`sv_reboot_host`, `sv_uninstall_addon`,
`sv_delete_backup`, el rebuild de esta spec), y Hermes se recupera solo de
todas.

**Token**: ata `suggestion_uuid` y, como `estado` (018), `type`, `context`,
`reference` y, si los hay, la lista de backups a borrar y la de contenedores a
reconstruir y la de `also_auto_applied`. Al confirmar se vuelve a leer `/resolution/info` (y `/backups`
si toca): si la sugerencia ya no está → `suggestion_not_found`; si algo del
estado cambió → `suggestion_changed` (el `ESTADO_CAMBIADO` de la 018, traducido como hace `dashboard_changed`), sin llamar; las comprobaciones de
`targets_hermes` y `not_allowed` se repiten.

**Respuesta**: ok con `effect` resumido y la pista de comprobar con
`sv_get_resolution`; error del Supervisor (fixup fallido) redactado.

## R-7 — Operaciones largas y cortes de conexión

`POST /core/start`, `/core/rebuild` y `/supervisor/repair` esperan a terminar
en el Supervisor. Hermes llama con `timeout_seconds=600` (start, rebuild) y
`900` (repair). Si vence el tiempo, la respuesta es `status: "started"` con
`verify_with` (`sv_get_core_info`, `sv_get_resolution`) y **nunca** ok ni
error inventados. `POST /supervisor/restart` responde al entrar en
`STOPPING`; si la conexión se corta antes de la respuesta (sin `status`), la
respuesta es igualmente `status: "started"` con `verify_with:
"sv_get_supervisor_info"` y la advertencia de que Core volverá a conectarse.
Un error con `status` del Supervisor (400, 500) es `error`, redactado.

## R-8 — Lo que va por la tabla sin tool (CAP-091, CAP-092, CAP-094)

Comprobado contra `supervisor-rutas.tsv` y el Supervisor 2026.11.0: todas las
rutas de plugins (`/{dns,audio,multicast,observer,cli}/{info,stats}` `read`;
`update`, `restart`, `reset`, `reload`, `options`, `profile`, `volume`,
`mute`, `default` `confirm`), de Docker (`GET /docker/registries` `read`;
`POST /docker/registries`, `DELETE /docker/registries/{hostname}`,
`POST /docker/options` `confirm`) y de placas y hora (`GET /os/boards/*`
`read`; `POST /os/boards/{green,yellow}`,
`/os/boards/raspberrypi/firmware/update`, `POST /time/options` `confirm`) ya
están en la tabla de la 011 con su CAP y un motivo correcto. **No cambia
ninguna entrada**. La 022 añade tests con el Supervisor simulado y la tabla
real (como la 013): cada `read` se ejecuta por `sv_read_api` y cada
`confirm` da vista previa y token por `sv_call_api`.

**FR-079 (credenciales del registro)**: el cuerpo de
`POST /docker/registries` es `{<hostname>: {username, password}}`
(`SCHEMA_DOCKER_REGISTRY`). `resumir_carga` ya oculta `password`
(`es_clave_sensible`) en la vista previa; falta probarlo, y probar que la
contraseña no sale en el log de Hermes ni en un error del Supervisor que la
repita. Si un test destapa una fuga, se arregla en la genérica (fallo de la
011) con su control negativo, sin cambiar la forma de la vista previa.

`/dns/options` (servidores DNS de todos los contenedores) y `/docker/options`
(IPv6 y MTU de la red de contenedores) pueden dejar sin red a las apps:
quedan `confirm` como dice la 008; la guía lo avisa.

## R-9 — Pruebas

- Las 8 tools nuevas son `sv_*`: unitarias contra un Supervisor simulado con
  la forma de 2026.11.0 (fixture nueva `tests/fixtures/supervisor_control.py`,
  sobre la de la 013), con `structlog.testing.capture_logs`.
- No entran en el banco de Core (su Supervisor es un simulado que solo
  reenvía a Core y no sobreviviría a un rebuild): `FUERA_DEL_BANCO` de
  `tests/banco/cobertura_escrituras.py` con su motivo, fila `VM | pendiente`
  en la matriz de la 014 (`docs/HOJA-DE-RUTA.md`) y su línea en «Tandas de
  pruebas» de `docs/BANCO-SUPERVISOR.md` (tanda 1: opciones y recarga; tanda
  3: start, rebuild, restart, repair y una sugerencia).
- Ninguna tool nueva de Core modifica nada: no hay casilla del banco de Core.

## R-10 — Anotaciones

| Tool | readOnly | destructive | idempotent | openWorld | Cómo |
|---|---|---|---|---|---|
| `sv_start_core` | no | no | sí | no | por defecto (prefijo `sv_` sin regla) |
| `sv_rebuild_core` | no | **sí** | no | no | `_DESTRUCTIVE_EXACT`, `_NON_IDEMPOTENT_EXACT` |
| `sv_set_core_options` | no | **sí** (`boot=false` deja HA apagado tras reiniciar el host) | sí | no | `_DESTRUCTIVE_EXACT` |
| `sv_reload_supervisor` | no | no | sí | **sí** (lee versiones de internet) | `_OPEN_WORLD` |
| `sv_restart_supervisor` | no | **sí** | no | no | `_DESTRUCTIVE_EXACT`, `_NON_IDEMPOTENT_EXACT` |
| `sv_repair_supervisor` | no | **sí** (borra imágenes y volúmenes sin usar) | no | **sí** (descarga imágenes) | las tres |
| `sv_set_supervisor_options` | no | no | sí | no | por defecto; `diagnostics` se explica en la descripción |
| `sv_apply_resolution_suggestion` | no | **sí** | no | **sí** (algunos fixups descargan o clonan) | las tres |

`sv_rebuild_core` y `sv_restart_supervisor` no se anuncian idempotentes:
repetirlas vuelve a cortar el servicio. `sv_restart_core` (1.1.2) se anuncia
idempotente y no se toca aquí (FR-020 de la 008: las tools existentes no
cambian salvo que una CAP lo pida); la diferencia se anota como duda menor.

## R-11 — Guía

Tema nuevo `system_control` (alias `core_control`, `supervisor_control`,
`suggestions`, `fixups`) con las 8 tools, lo que cortan, las listas cerradas
de opciones, los rechazos, las rutas por la tabla de CAP-084/087/091/092/094
y la receta «Core no arranca» (`sv_get_core_logs` → `sv_check_core_config` →
`sv_start_core` o `sv_rebuild_core`). Cambia `diagnostics` (ya no «nunca
aplica»: apunta a `sv_apply_resolution_suggestion`) y `supervisor` (una línea
que remite a `system_control`), con sus huellas en `tests/test_tools_guide.py`.

## R-12 — Errores

Forma común de Hermes `{"error": <código>, "detail": …}` (la de las genéricas de la 011) con `field` en
`invalid_argument` y `allowed` en `not_allowed`. Errores del Supervisor
pasados por `redact_secrets`. `HAConnectionError` sin `status` en las
operaciones que cortan la conexión → `status: "started"` (R-7); en el resto,
`error`.
